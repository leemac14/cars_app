"""Gwarancja naprawy na ekranie: pola ze skrótami, okno przy pozycji wizyty, linijka
„Gwarancja jeszcze 8 miesięcy”. Liczy db/gwarancje.py, tu tylko wygląd; gwarancja, która
minęła, jest szara (to nie usterka)."""

import db
import flet as ft
import log
from date import parsuj_date
from datetime import date, datetime

from .stale import FS, KOLOR_STATUS, RADIUS, SPACING
from .format import parsuj_int
from .typografia import podpis
from .wyglad import pasek_zawijany
from .zgodnosc import ustaw_blad
from .dialogi import otworz_dialog, pokaz_komunikat, zamknij_dialog
from .sync_ui import wypchnij_w_tle
from .formularze import pole_daty, styl_pola


KOLORY_GWARANCJI = {
    db.STATUS_GWARANCJI_OK: KOLOR_STATUS["ok"],
    db.STATUS_GWARANCJI_BLISKO: KOLOR_STATUS["warning"],
    db.STATUS_GWARANCJI_PO_TERMINIE: KOLOR_STATUS["neutral"],
}

IKONY_GWARANCJI = {
    db.STATUS_GWARANCJI_OK: ft.Icons.GPP_GOOD,
    db.STATUS_GWARANCJI_BLISKO: ft.Icons.GPP_MAYBE,
    db.STATUS_GWARANCJI_PO_TERMINIE: ft.Icons.GPP_BAD,
}


def _dzien(tekst):
    """date albo None z tekstu pola daty."""
    dzien = parsuj_date(tekst)
    return None if dzien == datetime.min.date() else dzien


def _niczego_nie_chroni(stan):
    """Minęła albo część wymieniono później — w obu przypadkach to już tylko zapis."""
    return bool(stan.get("wygasla") or stan.get("wymieniona"))


def kolor_gwarancji(stan):
    if _niczego_nie_chroni(stan):
        return KOLOR_STATUS["neutral"]
    return KOLORY_GWARANCJI.get(stan.get("status"), KOLOR_STATUS["ok"])


def ikona_gwarancji(stan):
    if _niczego_nie_chroni(stan):
        return IKONY_GWARANCJI[db.STATUS_GWARANCJI_PO_TERMINIE]
    return IKONY_GWARANCJI.get(stan.get("status"), ft.Icons.GPP_GOOD)


def tekst_gwarancji(stan, j=None, szczegoly=True):
    """„Gwarancja jeszcze 7 miesięcy · do 12.05.2027”, „Gwarancja wygasła
    12.05.2025”, a przy części, którą wymieniono jeszcze raz — „Gwarancja do
    12.05.2027 · część wymieniona ponownie 01.08.2026” (stan z gwarancje_wpisow).
    `szczegoly=False` zostawia samo „ile zostało” — na kartę podzespołu."""
    if stan["wygasla"]:
        return f"Gwarancja {db.ile_zostalo_gwarancji(stan, j)}"
    if stan.get("wymieniona"):
        return f"Gwarancja {db.zakres_gwarancji(stan, j)} · część wymieniona ponownie {stan['wymieniona']}"
    ile = db.ile_zostalo_gwarancji(stan, j)
    tekst = f"Gwarancja {ile}"
    # „do 180 000 km” (limit bez znanego licznika) sam jest już zakresem.
    if szczegoly and not ile.startswith("do "):
        tekst += f" · {db.zakres_gwarancji(stan, j)}"
    return tekst


def wiersz_gwarancji(stan, j=None, szczegoly=True):
    """Linijka gwarancji na karcie wpisu w historii i na karcie podzespołu."""
    kolor = kolor_gwarancji(stan)
    return ft.Row([
        ft.Icon(ikona_gwarancji(stan), size=14, color=kolor),
        ft.Text(tekst_gwarancji(stan, j, szczegoly), size=FS["caption"], color=kolor, expand=True),
    ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.START)


def szczegoly_gwarancji(gwarancja, j=None):
    """„do 12.05.2027 lub 180 000 km · wymiana 12.05.2025 · Warsztat u Janka” —
    pod nazwą części na Karcie pojazdu. Wpis bez wybranego warsztatu („Warsztat”)
    niczego tu nie dopowiada, więc go pomijamy."""
    tekst = f"{db.zakres_gwarancji(gwarancja, j)} · wymiana {gwarancja['data']}"
    wykonawca = str(gwarancja.get("wykonawca") or "").strip()
    if wykonawca and db.klucz_nazwy(wykonawca) != db.klucz_nazwy(db.WARSZTAT_BEZ_NAZWY):
        tekst += f" · {wykonawca}"
    return tekst


def pozycja_gwarancji(gwarancja, j=None, on_click=None):
    """Wiersz sekcji „Gwarancje na naprawy” na Karcie pojazdu: część, ile
    zostało (kolorem stanu) i pod spodem limity, dzień wymiany i warsztat."""
    kolor = kolor_gwarancji(gwarancja)
    return ft.Container(
        padding=ft.Padding(0, SPACING["xs"], 0, SPACING["xs"]),
        border_radius=RADIUS["sm"],
        ink=on_click is not None, on_click=on_click,
        content=ft.Row([
            ft.Icon(ikona_gwarancji(gwarancja), size=18, color=kolor),
            ft.Column([
                ft.Text(str(gwarancja["nazwa"]), size=FS["body_strong"], weight="bold"),
                ft.Text(db.opis_gwarancji(gwarancja, j), size=FS["body"], color=kolor),
                podpis(szczegoly_gwarancji(gwarancja, j)),
            ], spacing=1, tight=True, expand=True),
        ], spacing=SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.START),
    )


# ============================================================================
#  POLA W FORMULARZU
# ============================================================================

def _nazwa_okresu(miesiace):
    """„6 mies.”, „1 rok”, „2 lata” — napis skrótu okresu."""
    if miesiace % 12 == 0:
        return db.liczba_z_odmiana(miesiace // 12, "rok", "lata", "lat")
    return f"{miesiace} mies."


def _okres_slownie(start, koniec):
    """„2 lata”, „18 miesięcy”, a przy dacie spoza pełnych miesięcy — „400 dni”."""
    miesiace = db.okres_gwarancji(koniec, start)
    if miesiace is None:
        return db.czas_slownie(start, koniec)
    if miesiace % 12 == 0:
        return db.liczba_z_odmiana(miesiace // 12, "rok", "lata", "lat")
    return db.liczba_z_odmiana(miesiace, "miesiąc", "miesiące", "miesięcy")


class PolaGwarancji:
    """Gwarancja naprawy w formularzu (do kiedy, do jakiego licznika) ze skrótami („2
    lata”, „+20 tys. km”). Skrót trzyma się WYMIANY: zmiana jej daty lub licznika
    przesuwa gwarancję, dopóki ktoś nie wpisze końca ręcznie. `data_wymiany` i
    `przebieg_wymiany` to funkcje bez argumentów. Formularz: `kontrolki()`,
    `przy_zmianie_wymiany()`, `migawka()`, `sprawdz()`."""

    def __init__(self, page: ft.Page, koniec=None, limit_km=None, data_wymiany=None,
                 przebieg_wymiany=None, miesiace=None, dystans_km=None, uwagi=()):
        self._page = page
        self._data_wymiany = data_wymiany or (lambda: None)
        self._przebieg_wymiany = przebieg_wymiany or (lambda: None)
        self._j = db.jednostka_dystansu()
        koniec, limit_km = db.klucz_gwarancji(koniec, limit_km)
        # Kilometry, które pole pokazuje — nieruszone wracają do bazy co do
        # kilometra także przy milach (db.dystans_na_km, km_przy_otwarciu).
        self._km_pokazany = limit_km

        self.e_data = pole_daty(page, "Gwarancja do", koniec or "", po_zmianie=self._data_z_kalendarza)
        self._przycisk_czysc = ft.IconButton(
            icon=ft.Icons.CLOSE, icon_size=18, tooltip="Bez daty końca gwarancji",
            on_click=self._wyczysc_date,
        )
        self.e_data.suffix = ft.Row([self._przycisk_czysc, self.e_data.suffix], spacing=0, tight=True)
        self.e_km = ft.TextField(
            label=f"Gwarancja do przebiegu ({self._j})",
            value=db.wartosc_pola_dystansu(limit_km) if limit_km else "",
            hint_text="stan licznika, np. 180000",
            keyboard_type=ft.KeyboardType.NUMBER,
            on_change=lambda e: self._km_recznie(),
            **styl_pola(page=page)
        )
        self._chipy_okresu = {
            m: self._chip(_nazwa_okresu(m), lambda e, m=m: self.ustaw_okres(m),
                          f"Koniec gwarancji {_nazwa_okresu(m)} po dniu wymiany")
            for m in db.OKRESY_GWARANCJI_MIESIACE
        }
        self._chipy_dystansu = {
            d: self._chip(f"+{d // 1000} tys. {self._j}", lambda e, d=d: self.ustaw_dystans(d),
                          f"Limit {d // 1000} tys. {self._j} po przebiegu z wymiany")
            for d in db.DYSTANSE_GWARANCJI
        }
        self.podsumowanie = podpis("")
        self._uwagi = [podpis(tekst) for tekst in uwagi if tekst]

        # Skrót, za którym gwarancja jedzie: podany (duplikat przenosi okres)
        # albo odczytany z tego, co już zapisane.
        self._miesiace = miesiace
        self._dystans_km = dystans_km
        if self._miesiace is None:
            okres = db.okres_gwarancji(koniec, self._data_wymiany())
            self._miesiace = okres if okres in db.OKRESY_GWARANCJI_MIESIACE else None
        if self._dystans_km is None:
            baza = self._przebieg_wymiany()
            if limit_km and baza and limit_km - int(baza) in self._dystanse_km().values():
                self._dystans_km = limit_km - int(baza)

        self._stan_poczatkowy = self.migawka()
        self._odswiez()

    # ------------------------------------------------------------ dla formularza

    def kontrolki(self):
        return [
            self.e_data, pasek_zawijany(list(self._chipy_okresu.values())),
            self.e_km, pasek_zawijany(list(self._chipy_dystansu.values())),
            self.podsumowanie, *self._uwagi,
        ]

    def migawka(self):
        """Stan do wykrywania niezapisanych zmian — po wartościach: ta sama data
        wpisana inaczej albo limit przepisany z pola bez zmiany nie są zmianą."""
        limit, czytelny = self._limit_km()
        return (db.klucz_gwarancji(self.e_data.value, None)[0],
                limit if czytelny else (self.e_km.value or "").strip())

    def zmieniono(self):
        return self.migawka() != self._stan_poczatkowy

    def sprawdz(self):
        """(koniec albo None, limit w km albo None, błędy) — błędy w kształcie
        utils.pokaz_bledy_formularza."""
        ustaw_blad(self.e_data)
        ustaw_blad(self.e_km)
        koniec = db.klucz_gwarancji(self.e_data.value, None)[0]
        limit, czytelny = self._limit_km()
        bledy = []
        if not czytelny:
            bledy.append((self.e_km, "Błędny przebieg"))
        opisy = db.bledy_gwarancji(koniec, limit, self._data_wymiany(), self._przebieg_wymiany())
        if "data" in opisy:
            bledy.append((self.e_data, opisy["data"]))
        if "przebieg" in opisy and czytelny:
            bledy.append((self.e_km, opisy["przebieg"]))
        return koniec, limit, bledy

    def ustaw_okres(self, miesiace):
        """Skrót okresu: koniec N miesięcy po dniu wymiany (bez daty wymiany —
        od dzisiaj, bo formularz podpowiada dzisiejszą)."""
        start = _dzien(self._data_wymiany()) or date.today()
        self.e_data.value = db.dodaj_miesiace(start, miesiace).strftime("%d.%m.%Y")
        self._miesiace = miesiace
        ustaw_blad(self.e_data)
        self._odswiez(aktualizuj=True)

    def ustaw_dystans(self, dystans):
        """Skrót dystansu: limit = licznik przy wymianie + dystans w jednostce
        z Ustawień. Bez licznika wymiany nie ma od czego liczyć."""
        baza = self._przebieg_wymiany()
        if not baza:
            ustaw_blad(self.e_km, "Najpierw wpisz przebieg w momencie wymiany")
            self._odswiez(aktualizuj=True)
            return
        self._dystans_km = self._dystanse_km()[dystans]
        self._ustaw_limit(int(baza) + self._dystans_km)
        ustaw_blad(self.e_km)
        self._odswiez(aktualizuj=True)

    def przy_zmianie_wymiany(self):
        """Data albo licznik wymiany się zmieniły — gwarancja ze skrótu jedzie
        za nimi. Wpisana ręcznie zostaje, gdzie była."""
        if self._miesiace:
            start = _dzien(self._data_wymiany())
            if start:
                self.e_data.value = db.dodaj_miesiace(start, self._miesiace).strftime("%d.%m.%Y")
        if self._dystans_km:
            baza = self._przebieg_wymiany()
            if baza:
                self._ustaw_limit(int(baza) + self._dystans_km)
        self._odswiez(aktualizuj=True)

    # ------------------------------------------------------------ środek

    def _chip(self, tekst, akcja, podpowiedz):
        return ft.Container(
            content=ft.Text(tekst, size=FS["caption"]),
            padding=ft.Padding(10, 5, 10, 5),
            border_radius=RADIUS["pill"],
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            ink=True, on_click=akcja, tooltip=podpowiedz,
        )

    @staticmethod
    def _zaznacz(chip, zaznaczony):
        chip.bgcolor = ft.Colors.with_opacity(0.12, ft.Colors.PRIMARY) if zaznaczony else None
        chip.border = ft.Border.all(1, ft.Colors.PRIMARY if zaznaczony else ft.Colors.OUTLINE_VARIANT)
        chip.content.color = ft.Colors.PRIMARY if zaznaczony else None
        chip.content.weight = ft.FontWeight.BOLD if zaznaczony else None

    def _dystanse_km(self):
        """Skróty dystansu w km — „+20 tys.” w milach to 32 187 km."""
        return {d: int(db.dystans_na_km(d, self._j, calkowity=True)) for d in db.DYSTANSE_GWARANCJI}

    def _ustaw_limit(self, limit_km):
        self._km_pokazany = limit_km
        self.e_km.value = db.wartosc_pola_dystansu(limit_km, self._j)

    def _data_z_kalendarza(self):
        self._miesiace = None
        self._odswiez(aktualizuj=True)

    def _wyczysc_date(self, e):
        self.e_data.value = ""
        self._miesiace = None
        ustaw_blad(self.e_data)
        self._odswiez(aktualizuj=True)

    def _km_recznie(self):
        self._dystans_km = None
        ustaw_blad(self.e_km)
        self._odswiez(aktualizuj=True)

    def _limit_km(self):
        """(limit w km albo None, czy pole da się odczytać). Puste pole to brak
        limitu, a nie błąd."""
        tekst = (self.e_km.value or "").strip()
        if not tekst:
            return None, True
        wartosc = parsuj_int(tekst, None)
        if wartosc is None or wartosc <= 0:
            return None, False
        return db.dystans_na_km(wartosc, self._j, calkowity=True, km_przy_otwarciu=self._km_pokazany), True

    def _opis(self):
        """Podsumowanie pod polami: ile to od wymiany i co decyduje."""
        start = _dzien(self._data_wymiany())
        koniec = _dzien(self.e_data.value)
        limit, _ = self._limit_km()
        baza = self._przebieg_wymiany()
        if not koniec and not limit:
            return "Bez gwarancji — zostaw oba pola puste, jeśli naprawa jej nie ma."
        czesci = []
        if koniec and start and koniec > start:
            czesci.append(_okres_slownie(start, koniec))
        if limit and baza and limit > int(baza):
            czesci.append(db.tekst_dystansu(limit - int(baza), 0, self._j))
        if not czesci:
            return ""
        tekst = f"{' albo '.join(czesci)} od wymiany"
        if koniec and limit:
            tekst += " — obowiązuje to, co skończy się pierwsze"
        return tekst[:1].upper() + tekst[1:]

    def _odswiez(self, aktualizuj=False):
        self.podsumowanie.value = self._opis()
        self.podsumowanie.visible = bool(self.podsumowanie.value)
        self._przycisk_czysc.visible = bool((self.e_data.value or "").strip())
        start = _dzien(self._data_wymiany())
        okres = db.okres_gwarancji(self.e_data.value, start) if start else None
        for miesiace, chip in self._chipy_okresu.items():
            self._zaznacz(chip, miesiace == (self._miesiace or okres))
        limit, _ = self._limit_km()
        baza = self._przebieg_wymiany()
        dystans = limit - int(baza) if limit and baza else None
        for d, km in self._dystanse_km().items():
            self._zaznacz(self._chipy_dystansu[d], km == (self._dystans_km or dystans))
        if aktualizuj:
            try:
                self._page.update()
            except Exception:
                log.polkniety("odświeżenie pól gwarancji")


# ============================================================================
#  OKNO PRZY POZYCJI WIZYTY ZBIORCZEJ
# ============================================================================

def dialog_gwarancji_wpisu(page: ft.Page, historia_id, po_zapisie=None):
    """Okno „Gwarancja” przy jednej pozycji wizyty zbiorczej — wyjątek od
    wspólnej gwarancji wizyty (akumulator z trzyletnią, reszta z roczną). Data
    i licznik wymiany należą do wizyty, więc skróty liczą od nich, a zmienić ich
    tu nie można. Zwraca okno (albo None, gdy wpisu już nie ma)."""
    wpis = db.pobierz_gwarancje_wpisu(historia_id)
    if not wpis:
        return None
    km_wymiany = parsuj_int(wpis["przebieg"], None) or None
    pola = PolaGwarancji(page, wpis["gwarancja_data"], wpis["gwarancja_przebieg"],
                         data_wymiany=lambda: wpis["data"], przebieg_wymiany=lambda: km_wymiany)
    wymiana = f"Wymiana {wpis['data']}"
    if km_wymiany:
        wymiana += f" przy {db.tekst_dystansu(km_wymiany)}"

    dlg = ft.AlertDialog(
        modal=True,
        title=ft.Row([ft.Icon(ft.Icons.GPP_GOOD, size=20, color=ft.Colors.PRIMARY),
                      ft.Text(f"Gwarancja: {wpis['nazwa']}", weight="bold", expand=True)], spacing=SPACING["sm"]),
        content=ft.Container(width=420, content=ft.Column(
            [podpis(wymiana), *pola.kontrolki(),
             podpis("Tylko ta pozycja — pozostałe zostają przy gwarancji wizyty.")],
            tight=True, spacing=SPACING["sm"], scroll=ft.ScrollMode.AUTO,
        )),
        shape=ft.RoundedRectangleBorder(radius=RADIUS["lg"]),
        data=pola,
    )

    def zapisz(e):
        koniec, limit, bledy = pola.sprawdz()
        if bledy:
            for kontrolka, komunikat in bledy:
                ustaw_blad(kontrolka, komunikat)
            try:
                page.update()
            except Exception:
                log.polkniety("błąd w oknie gwarancji")
            return
        if not pola.zmieniono():
            zamknij_dialog(page, dlg)
            return
        auto_id = db.zapisz_gwarancje_wpisu(historia_id, koniec, limit)
        zamknij_dialog(page, dlg)
        wypchnij_w_tle(page, auto_id, "gwarancja")
        pokaz_komunikat(page, "Zapisano gwarancję." if (koniec or limit) else "Usunięto gwarancję.")
        if po_zapisie:
            po_zapisie()

    dlg.actions = [
        ft.TextButton("Anuluj", on_click=lambda e: zamknij_dialog(page, dlg)),
        ft.FilledButton("Zapisz", on_click=zapisz),
    ]
    dlg.actions_alignment = ft.MainAxisAlignment.END
    otworz_dialog(page, dlg)
    return dlg


__all__ = [
    "IKONY_GWARANCJI",
    "KOLORY_GWARANCJI",
    "PolaGwarancji",
    "dialog_gwarancji_wpisu",
    "ikona_gwarancji",
    "kolor_gwarancji",
    "pozycja_gwarancji",
    "szczegoly_gwarancji",
    "tekst_gwarancji",
    "wiersz_gwarancji",
]
