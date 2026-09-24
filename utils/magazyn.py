"""Zużycie części z magazynu w formularzu wpisu serwisowego i wizyty.

Oba formularze miały kartę „Magazyn części” skopiowaną co do linijki. Dopóki
zużycie tylko zdejmowało sztuki ze stanu, kopia była tania. Od kiedy niesie
KOSZT — podgląd kwoty na żywo, cenę zapamiętaną przy edycji, walidację ilości
i dopisek pod polem kosztu — musiałaby zgadzać się w dwóch miejscach naraz,
a to rozjeżdża się przy pierwszej poprawce.
"""

import db
import flet as ft
import log

from .stale import FS, formatuj_liczba
from .format import _odmiana_liczby, parsuj_float, symbol_waluty
from .typografia import KOLOR_DRUGIEGO_PLANU
from .zgodnosc import ustaw_blad
from .formularze import karta_formularza, styl_pola


def _liczba_zwiezle(wartosc, najwiecej=2, najmniej=0):
    """Liczba bez ogona zer: tyle miejsc po przecinku, ile naprawdę niesie
    treści. Skład zostaje w rdzeniu (formatuj_liczba) — tu zapada tylko decyzja,
    ile miejsc pokazać."""
    pelna = formatuj_liczba(wartosc, najwiecej)
    znaczace = len(pelna.partition(",")[2].rstrip("0"))
    return formatuj_liczba(wartosc, max(najmniej, znaczace))


def tekst_ilosci(ilosc):
    """„1”, „2,5”, „0,25” — w magazynie liczy się sztuki i litry, a „1,00 szt”
    czyta się jak kwota."""
    return _liczba_zwiezle(ilosc, 2)


def tekst_ceny(cena):
    """Cena za jednostkę: dwa miejsca po przecinku, a przy groszowych cenach
    (mililitr, gram) do czterech — 0,05 zł zamiast 0,045 zł za mililitr to
    jedenaście procent błędu na litrze."""
    if cena is not None and 0 < abs(cena) < 1:
        return _liczba_zwiezle(cena, 4, 2)
    return formatuj_liczba(cena, 2)


def liczba_do_pola(wartosc):
    """Wartość do wpisania w pole formularza: pusta, gdy liczby nie ma, i bez
    ogona zer, gdy jest (parsuj_float czyta z powrotem i przecinek, i spacje)."""
    if wartosc is None or wartosc == "":
        return ""
    return _liczba_zwiezle(wartosc, 4)


def koszt_bez_czesci_do_pola(zapisany_koszt, doliczone):
    """Zapisany koszt wpisu albo wizyty BEZ części doliczonych z magazynu — to,
    co ma stanąć w polu kosztu. Inaczej każdy kolejny zapis doliczałby części od
    nowa. Zero daje puste pole, tak jak dotąd."""
    wlasny = max(0.0, round((parsuj_float(zapisany_koszt, 0.0) or 0.0) - (doliczone or 0.0), 2))
    return liczba_do_pola(wlasny) if wlasny else ""


def opis_zuzycia_z_magazynu(zuzycie):
    """„Z magazynu: olej 5W-30 (1 szt) · w tym 200,00 zł” — dopisek na kartach
    wpisów i wizyt (element wyniku db.pobierz_zuzycie_rekordow). Kwota tylko
    wtedy, gdy coś faktycznie doliczono: zużycie zapisane przed doliczaniem
    kosztów nie może udawać, że jest w kwocie karty."""
    if not zuzycie or not zuzycie.get("pozycje"):
        return ""
    pozycje = ", ".join(
        f"{p['nazwa']} ({tekst_ilosci(p['ilosc'])} {p['jednostka']})" for p in zuzycie["pozycje"]
    )
    tekst = f"Z magazynu: {pozycje}"
    if (zuzycie.get("koszt") or 0) > 0:
        tekst += f" · w tym {formatuj_liczba(zuzycie['koszt'])} {symbol_waluty()}"
    return tekst


class ZuzycieMagazynu:
    """Karta „Magazyn części” razem z kosztem zużycia.

    `zrodlo` to klucz z db.POWIAZANIA_MAGAZYNU („historia” albo „wizyty”),
    `rekord_id` — edytowany rekord. Nowy wpis i duplikat przychodzą bez niego:
    zużycia się nie kopiuje, bo stan magazynu mógł się od tamtej pory zmienić.

    Formularz odpowiada za trzy rzeczy: wstawia `karta()`, pokazuje koszt
    przez utils.KosztNaprawy (ten słucha zmian przez `przy_zmianie()`) i przy
    zapisie woła `sprawdz()`. W polach kosztu stoi SAMA usługa —
    `koszt_doliczony` to kwota, którą trzeba odjąć od zapisanego kosztu
    rekordu, zanim trafi do formularza."""

    def __init__(self, page: ft.Page, auto_id, zrodlo, rekord_id=None):
        self._page = page
        self._obserwatorzy = []
        self._waluta = symbol_waluty()
        self.poprzednie = db.pobierz_zuzycie_czesci(zrodlo, rekord_id) if rekord_id else {}
        self.koszt_doliczony = db.koszt_doliczony(self.poprzednie)
        self._ceny = {}
        self._pozycje = []

        wiersze = []
        for czesc in db.pobierz_czesci_do_zuzycia(auto_id):
            juz_uzyto = float((self.poprzednie.get(czesc["id"]) or {}).get("ilosc") or 0)
            # Przy edycji doliczamy to, co ten rekord już zdjął ze stanu — inaczej
            # własna, wcześniej zapisana ilość wyglądałaby na niedostępną.
            dostepna = czesc["ilosc"] + juz_uzyto
            if dostepna <= 0:
                continue

            self._ceny[czesc["id"]] = czesc["cena_jednostkowa"]
            zaznaczona = czesc["id"] in self.poprzednie
            pole = ft.TextField(
                value=tekst_ilosci(juz_uzyto) if zaznaczona else "1",
                width=90, visible=zaznaczona,
                keyboard_type=ft.KeyboardType.NUMBER,
                on_change=lambda e: self.przelicz(),
                **styl_pola(page=page)
            )
            pozycja = {
                "id": czesc["id"], "jednostka": czesc["jednostka"], "dostepna": dostepna,
                "pole": pole, "opis": ft.Text("", size=FS["label"], color=KOLOR_DRUGIEGO_PLANU),
            }
            pozycja["chk"] = ft.Checkbox(
                label=f"{czesc['nazwa']} (dost.: {tekst_ilosci(dostepna)} {czesc['jednostka']})",
                value=zaznaczona, data=czesc["id"],
                on_change=lambda e, p=pozycja: self._przelacz_pozycje(p),
            )
            self._pozycje.append(pozycja)
            wiersze.append(ft.Column([
                ft.Row([pozycja["chk"], pole], alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
                pozycja["opis"],
            ], spacing=0))

        self.lista = ft.Column(wiersze, spacing=8, visible=bool(self.poprzednie))
        self.c_uzyj = ft.Checkbox(
            label="Wykorzystaj własne części z magazynu",
            value=bool(self.poprzednie),
            on_change=lambda e: self._przelacz_magazyn(),
        )
        self.podsumowanie = ft.Text("", size=FS["body"], visible=False)
        self._odswiez_opisy()

    # ------------------------------------------------------------ dla formularza

    def karta(self):
        """Karta do wstawienia w formularz albo None, gdy w magazynie nie ma nic
        do wzięcia (wtedy formularz karty nie pokazuje w ogóle)."""
        if not self._pozycje:
            return None
        return karta_formularza(
            [self.c_uzyj, self.lista, self.podsumowanie],
            "Magazyn części", ft.Icons.INVENTORY_2,
            domyslnie_otwarte=bool(self.poprzednie),
        )

    def przy_zmianie(self, funkcja):
        """`funkcja()` po każdej zmianie zaznaczenia albo ilości, przed
        odświeżeniem strony. Tak pod polami kosztu staje linijka „+ części
        z magazynu … = razem …” — karta magazynu leży na dole formularza,
        a o kwocie myśli się przy kwocie."""
        self._obserwatorzy.append(funkcja)

    def migawka(self):
        """Stan karty do wykrywania niezapisanych zmian."""
        return (self.c_uzyj.value, tuple((p["chk"].value, p["pole"].value) for p in self._pozycje))

    def wybrane(self):
        """Pary (magazyn_id, ilość) z POPRAWNĄ ilością — do podglądu na żywo.
        Błędna ilość po prostu nic nie dolicza; komunikat pokaże dopiero zapis."""
        if not self.c_uzyj.value:
            return []
        wynik = []
        for p in self._pozycje:
            if not p["chk"].value:
                continue
            ilosc = parsuj_float(p["pole"].value, None)
            if ilosc is not None and 0 < ilosc <= p["dostepna"] + 1e-9:
                wynik.append((p["id"], ilosc))
        return wynik

    def koszt(self):
        """Ile doliczą zaznaczone części przy obecnym stanie formularza."""
        return db.suma_kosztu_zuzycia(db.wycen_zuzycie(self.wybrane(), self._ceny, self.poprzednie))

    def sprawdz(self):
        """Walidacja przed zapisem. Zwraca (wycenione zużycie, czy_blad) —
        wycenione w kształcie db.wycen_zuzycie, gotowe do db.rozlicz_czesci_*."""
        uzyte, blad = [], False
        for p in self._pozycje:
            ustaw_blad(p["pole"])
            if not (self.c_uzyj.value and p["chk"].value):
                continue
            ilosc = parsuj_float(p["pole"].value, None)
            if ilosc is None or ilosc <= 0 or ilosc > p["dostepna"] + 1e-9:
                ustaw_blad(p["pole"], f"Maks. {tekst_ilosci(p['dostepna'])}")
                blad = True
            else:
                uzyte.append((p["id"], ilosc))
        return db.wycen_zuzycie(uzyte, self._ceny, self.poprzednie), blad

    def przelicz(self):
        self._odswiez_opisy()
        for funkcja in self._obserwatorzy:
            funkcja()
        self._odswiez_strone()

    # ------------------------------------------------------------ środek

    def _przelacz_pozycje(self, pozycja):
        pozycja["pole"].visible = bool(pozycja["chk"].value)
        self.przelicz()

    def _przelacz_magazyn(self):
        self.lista.visible = bool(self.c_uzyj.value)
        self.przelicz()

    def _odswiez_strone(self):
        try:
            self._page.update()
        except Exception:
            log.polkniety("odświeżenie karty magazynu w formularzu")

    def _odswiez_opisy(self):
        w = self._waluta
        wycenione = db.wycen_zuzycie(self.wybrane(), self._ceny, self.poprzednie)
        koszty = {magazyn_id: koszt for magazyn_id, _, koszt in wycenione}
        bez_ceny = 0

        for p in self._pozycje:
            cena = db.cena_zuzycia(p["id"], self._ceny, self.poprzednie)
            zaznaczona = bool(self.c_uzyj.value and p["chk"].value)
            if cena is None:
                bez_ceny += 1 if zaznaczona else 0
                p["opis"].value = ("Bez ceny w magazynie — koszt nie zostanie doliczony"
                                   if zaznaczona else "Bez ceny w magazynie")
            elif zaznaczona and koszty.get(p["id"]) is not None:
                ilosc = parsuj_float(p["pole"].value, 0.0)
                p["opis"].value = (f"{tekst_ilosci(ilosc)} {p['jednostka']} × {tekst_ceny(cena)} {w}"
                                   f" = {formatuj_liczba(koszty[p['id']])} {w}")
            else:
                p["opis"].value = f"{tekst_ceny(cena)} {w} za 1 {p['jednostka']}"

        koszt = db.suma_kosztu_zuzycia(wycenione)
        czesci = []
        if koszt > 0:
            czesci.append(f"Części z magazynu: {formatuj_liczba(koszt)} {w} — doliczone do kosztu")
        if bez_ceny:
            czesci.append(f"{bez_ceny} {_odmiana_liczby(bez_ceny, 'pozycja', 'pozycje', 'pozycji')} "
                          "bez ceny nic nie doliczy")
        self.podsumowanie.value = " · ".join(czesci)
        self.podsumowanie.visible = bool(czesci)



__all__ = [
    "ZuzycieMagazynu",
    "_liczba_zwiezle",
    "koszt_bez_czesci_do_pola",
    "liczba_do_pola",
    "opis_zuzycia_z_magazynu",
    "tekst_ceny",
    "tekst_ilosci",
]
