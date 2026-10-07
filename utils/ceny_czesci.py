"""Historia cen części, sklep i link przy pozycji magazynu (M-15): linijka „Wcześniej…”
z chipem zmiany, podpowiedź ceny w formularzu, arkusz „Historia cen”, okna „Kupiłem
ponownie” i „Dopisz cenę”, pole sklepu. Za `system` i `wykresy` (strona produktu, iskra
ceny)."""

from datetime import datetime

import db
import flet as ft
import log

from .stale import FS, KOLOR_STATUS, RADIUS, SPACING, formatuj_liczba
from .format import parsuj_float, symbol_waluty
from .typografia import KOLOR_DRUGIEGO_PLANU, etykieta, podpis, wartosc
from .wyglad import pasek_zawijany, powierzchnia
from .zgodnosc import ustaw_blad
from .dialogi import otworz_dialog, otworz_dno, pokaz_komunikat, pokaz_komunikat_cofnij, zamknij_dialog, zamknij_dno
from .sync_ui import wolno_zmieniac_rekord, wypchnij_w_tle
from .formularze import pole_daty, styl_pola
from .magazyn import liczba_do_pola, tekst_ceny, tekst_ilosci
from .wykresy import sparkline, znacznik_trendu
from .system import kopiuj_do_schowka, otworz_strone


# Ile poprzednich cen mieści się w linijce na karcie pozycji, zanim zacznie
# się zawijać — reszta jest w arkuszu „Historia cen”.
CEN_NA_KARCIE = 2

# Ile sklepów podpowiadać chipami pod polem „Sklep”.
MAKS_PODPOWIEDZI_SKLEPOW = 6

# Szerokość treści okien „Kupiłem ponownie” i „Dopisz cenę”.
SZEROKOSC_OKNA = 340


# ============================================================================
#  TEKSTY
# ============================================================================


def tekst_ceny_jednostki(cena, jednostka):
    """„38,00 zł/szt”, „0,045 zł/ml”."""
    return f"{tekst_ceny(cena)} {symbol_waluty()}/{jednostka or 'szt'}"


def miesiac_zakupu(punkt):
    """„03.2025” — na karcie wystarczy miesiąc; „bez daty” dla starej ceny
    pozycji, która daty zakupu nie miała."""
    iso = punkt.get("data_iso") or ""
    return f"{iso[5:7]}.{iso[:4]}" if len(iso) >= 7 else "bez daty"


def dzien_zakupu(punkt):
    """Data zakupu tak, jak ją wpisano, albo „bez daty”."""
    return punkt.get("data") or "bez daty"


def opis_wczesniejszych_cen(poprzednie, jednostka, ile=CEN_NA_KARCIE):
    """„Wcześniej: 38,00 zł (03.2025) · 30,00 zł (01.2024)” — jednostkę
    dopisujemy tylko przy cenie w innej niż bieżąca."""
    kawalki = []
    for p in (poprzednie or [])[:ile]:
        cena = tekst_ceny(p["cena"]) + f" {symbol_waluty()}"
        if p["jednostka"] != (jednostka or "szt"):
            cena += f"/{p['jednostka']}"
        kawalki.append(f"{cena} ({miesiac_zakupu(p)})")
    return "Wcześniej: " + " · ".join(kawalki) if kawalki else ""


def szczegoly_zakupu(punkt):
    """„2 szt za 39,00 zł · Allegro” — ile kupiono i gdzie, jeśli wiadomo."""
    kawalki = []
    if punkt.get("ilosc"):
        koszt = formatuj_liczba(punkt["ilosc"] * punkt["cena"], 2)
        kawalki.append(f"{tekst_ilosci(punkt['ilosc'])} {punkt['jednostka']} za {koszt} {symbol_waluty()}")
    if punkt.get("sklep"):
        kawalki.append(punkt["sklep"])
    return " · ".join(kawalki)


def podpowiedz_ceny(punkty, czesc_id=None):
    """Linijka przy nazwie części w formularzu i w „Kupiłem ponownie”:
    „Ostatnio 38,00 zł/szt · 12.03.2025 · Inter Cars · najtaniej 32,00 zł/szt
    (Allegro, 05.2026)”. Pusty napis, gdy tej części jeszcze nie kupowano."""
    poprzednie = db.poprzednie_zakupy(punkty, czesc_id)
    if not poprzednie:
        return ""
    ostatni = poprzednie[0]
    kawalki = [f"Ostatnio {tekst_ceny_jednostki(ostatni['cena'], ostatni['jednostka'])}", dzien_zakupu(ostatni)]
    if ostatni.get("sklep"):
        kawalki.append(ostatni["sklep"])
    tekst = " · ".join(kawalki)
    najtanszy = db.najtanszy_zakup(poprzednie[::-1])
    if najtanszy and najtanszy is not ostatni and najtanszy["cena"] < ostatni["cena"]:
        gdzie = ", ".join(x for x in (najtanszy.get("sklep"), miesiac_zakupu(najtanszy)) if x)
        tekst += f" · najtaniej {tekst_ceny_jednostki(najtanszy['cena'], najtanszy['jednostka'])} ({gdzie})"
    return tekst


# ============================================================================
#  KARTA POZYCJI
# ============================================================================


def wiersz_cen_na_karcie(punkty, czesc_id, jednostka):
    """Linijka „Wcześniej: …” z chipem zmiany od pierwszego zapisanego zakupu
    („+50% od 01.2024”) pod ceną pozycji — albo None, gdy wcześniejszych
    zakupów tej części nie ma."""
    poprzednie = db.poprzednie_zakupy(punkty, czesc_id)
    opis = opis_wczesniejszych_cen(poprzednie, jednostka)
    if not opis:
        return None
    elementy = [
        ft.Icon(ft.Icons.HISTORY, size=14, color=KOLOR_DRUGIEGO_PLANU),
        ft.Text(opis, size=FS["label"], color=KOLOR_DRUGIEGO_PLANU, expand=True,
                max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
    ]
    wlasny = next((p for p in punkty or [] if p["obecna"] and p["magazyn_id"] == czesc_id), None)
    zmiana = db.zmiana_ceny(punkty, do=wlasny) if wlasny else None
    if zmiana:
        elementy.append(ft.Row([
            znacznik_trendu(zmiana["proc"], prog=5, wzrost_zly=True),
            ft.Text(f"od {miesiac_zakupu(zmiana['od'])}", size=FS["caption"], color=KOLOR_DRUGIEGO_PLANU, no_wrap=True),
        ], spacing=4, tight=True))
    return ft.Row(elementy, spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)


def chip_sklepu(page: ft.Page, sklep, link):
    """Sklep pozycji na karcie; z linkiem — dotknięcie otwiera stronę produktu
    w przeglądarce jako osobnej aplikacji (patrz otworz_strone). Bez sklepu,
    ale z linkiem, podpisem jest domena („allegro.pl”). None, gdy nie ma nic."""
    nazwa = (sklep or "").strip() or (db.domena_linku(link) if link else "")
    if not nazwa:
        return None
    tresc = [
        ft.Icon(ft.Icons.STOREFRONT, size=14, color=KOLOR_DRUGIEGO_PLANU),
        ft.Text(nazwa, size=FS["label"], color=KOLOR_DRUGIEGO_PLANU, no_wrap=True,
                overflow=ft.TextOverflow.ELLIPSIS),
    ]
    if not link:
        return ft.Row(tresc, spacing=4, tight=True)
    tresc.append(ft.Icon(ft.Icons.OPEN_IN_NEW, size=14, color=ft.Colors.PRIMARY))
    return ft.Container(
        content=ft.Row(tresc, spacing=4, tight=True),
        padding=ft.Padding(8, 4, 8, 4), border_radius=RADIUS["pill"],
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT), ink=True,
        tooltip="Otwórz stronę produktu",
        on_click=lambda e: otworz_strone(page, link),
    )


def akcje_linku(page: ft.Page, link):
    """Pozycje menu pozycji magazynu dla linku do produktu. Tylko czytają,
    więc zostają także przy roli „podgląd”."""
    if not link:
        return []
    return [
        {"ikona": ft.Icons.OPEN_IN_NEW, "tekst": "Otwórz stronę produktu", "czyta": True,
         "akcja": lambda: otworz_strone(page, link)},
        {"ikona": ft.Icons.CONTENT_COPY, "tekst": "Kopiuj link", "czyta": True,
         "akcja": lambda: kopiuj_do_schowka(page, link, "Link skopiowany do schowka")},
    ]


# ============================================================================
#  POLE SKLEPU
# ============================================================================


class PoleSklepu:
    """Pole „Sklep” z podpowiedziami: chipy sklepów, w których już kupowano
    części do tego auta (db.sklepy_czesci). Przy zapisie pisownię i tak
    wyrównuje db.dopasuj_sklep — chip tylko oszczędza pisania."""

    def __init__(self, page: ft.Page, sklepy, wartosc_poczatkowa="", label="Sklep (opcjonalnie)"):
        self._page = page
        self.pole = ft.TextField(label=label, value=wartosc_poczatkowa or "",
                                 hint_text="np. Inter Cars, Allegro", **styl_pola())
        chipy = [self._chip(nazwa) for nazwa in list(sklepy or [])[:MAKS_PODPOWIEDZI_SKLEPOW]]
        self.kontrolka = ft.Column([self.pole] + ([pasek_zawijany(chipy)] if chipy else []),
                                   spacing=SPACING["sm"], tight=True)

    def _chip(self, nazwa):
        return ft.Container(
            content=ft.Text(nazwa, size=FS["label"]),
            padding=ft.Padding(10, 4, 10, 4), border_radius=RADIUS["pill"],
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT), ink=True,
            on_click=lambda e, n=nazwa: self.wybierz(n),
        )

    def wybierz(self, nazwa):
        self.pole.value = nazwa
        try:
            self._page.update()
        except Exception:
            log.polkniety("odświeżenie pola sklepu po wyborze podpowiedzi")

    @property
    def value(self):
        return self.pole.value


# ============================================================================
#  ARKUSZ „HISTORIA CEN”
# ============================================================================


def _zmiana_wzgledem(punkt, poprzedni):
    """„+12%” względem poprzedniego zakupu w tej samej jednostce, albo pusty."""
    if not poprzedni or poprzedni["jednostka"] != punkt["jednostka"] or not poprzedni["cena"]:
        return ""
    proc = (punkt["cena"] - poprzedni["cena"]) / poprzedni["cena"] * 100
    if abs(proc) < 0.5:
        return "bez zmiany"
    return f"{'+' if proc > 0 else '−'}{formatuj_liczba(abs(proc), 0)}%"


def _blok_wykresu(page: ft.Page, punkty):
    """Iskra cen w jednostce ostatniego zakupu, chip zmiany od pierwszego
    datowanego i najtańszy zakup ze sklepem. None przy jednym zakupie."""
    jednostka = punkty[-1]["jednostka"]
    porownywalne = [p for p in punkty if p["jednostka"] == jednostka]
    if len(porownywalne) < 2:
        return None
    ostatni = porownywalne[-1]
    naglowek = [ft.Column([
        etykieta("Ostatnia cena" if not ostatni["obecna"] else "Cena teraz"),
        wartosc(tekst_ceny_jednostki(ostatni["cena"], jednostka)),
    ], spacing=0, tight=True, expand=True)]
    zmiana = db.zmiana_ceny(punkty, do=ostatni)
    if zmiana:
        naglowek.append(ft.Column([
            znacznik_trendu(zmiana["proc"], prog=5, wzrost_zly=True, rozmiar=FS["label"]),
            podpis(f"od {miesiac_zakupu(zmiana['od'])}"),
        ], spacing=0, tight=True, horizontal_alignment=ft.CrossAxisAlignment.END))
    tresc = [ft.Row(naglowek, spacing=SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.CENTER)]
    iskra = sparkline([p["cena"] for p in porownywalne], wysokosc=44)
    if iskra:
        tresc.append(iskra)
    najtanszy = db.najtanszy_zakup(punkty)
    if najtanszy:
        gdzie = ", ".join(x for x in (najtanszy.get("sklep"), dzien_zakupu(najtanszy)) if x)
        tresc.append(podpis(f"Najtaniej: {tekst_ceny_jednostki(najtanszy['cena'], jednostka)} ({gdzie})"))
    return ft.Container(padding=ft.Padding(12, 10, 12, 10), **powierzchnia(page, "blok"),
                        content=ft.Column(tresc, spacing=SPACING["sm"], tight=True))


def pokaz_historie_cen(page: ft.Page, auto_id, czesc, po_zmianie=None):
    """Arkusz „Historia cen”: iskra, zmiana od pierwszego zakupu, najtańszy, lista od
    najnowszego; zakup z dziennika usuwalny z cofnięciem (bieżącą cenę poprawia edycja
    pozycji). `czesc`: {id, nazwa, jednostka, link}; `po_zmianie` — przebudowa listy
    magazynu."""
    punkty = db.historia_cen_czesci(auto_id, czesc["nazwa"])
    wolno = wolno_zmieniac_rekord(auto_id, "ceny_czesci")
    bs = ft.BottomSheet(ft.Container(padding=ft.Padding(16, 16, 16, 8), bgcolor=ft.Colors.SURFACE))

    def usun(punkt):
        zamknij_dno(page, bs)
        wynik = db.usun_wiele_z_cofnieciem("ceny_czesci", punkt["ids"])
        if wynik:
            wypchnij_w_tle(page, auto_id, "historia cen")
        if po_zmianie:
            po_zmianie()
        pokaz_komunikat_cofnij(page, f"Usunięto cenę z {dzien_zakupu(punkt)}.", wynik)

    def po_dopisaniu():
        # Lista pod spodem dostaje nową linijkę „Wcześniej…”, a arkusz wraca
        # z dopisanym punktem — tam, skąd użytkownik przyszedł.
        if po_zmianie:
            po_zmianie()
        pokaz_historie_cen(page, auto_id, czesc, po_zmianie)

    def dopisz():
        zamknij_dno(page, bs)
        dialog_dopisania_ceny(page, auto_id, czesc["nazwa"], czesc.get("jednostka"), po_zapisie=po_dopisaniu)

    if punkty:
        daty = [p for p in punkty if p.get("data_iso")]
        opis = db.liczba_z_odmiana(len(punkty), "zakup", "zakupy", "zakupów")
        if daty:
            opis += f" · od {miesiac_zakupu(daty[0])}"
    else:
        opis = "Bez zapisanych cen"

    zawartosc = [
        ft.Row([
            ft.Icon(ft.Icons.SHOW_CHART, size=22, color=ft.Colors.PRIMARY),
            ft.Column([
                ft.Text(f"Historia cen: {czesc['nazwa']}", weight="bold", size=FS["heading"], color=ft.Colors.PRIMARY,
                        max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                podpis(opis),
            ], spacing=0, tight=True, expand=True),
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ft.Divider(height=14),
    ]
    if not punkty:
        zawartosc.append(podpis(
            "Ta część nie ma jeszcze ceny. Wpisz ją w edycji pozycji albo dopisz zakup ze starego "
            "paragonu — następne zakupy dołożą się same, przy zapisie pozycji i „Kupiłem ponownie”."))
    else:
        wykres = _blok_wykresu(page, punkty)
        if wykres:
            zawartosc.append(wykres)

    for indeks in range(len(punkty) - 1, -1, -1):
        punkt = punkty[indeks]
        poprzedni = punkty[indeks - 1] if indeks > 0 else None
        tytul = [ft.Text(dzien_zakupu(punkt), size=FS["body"], weight="w500")]
        if punkt["obecna"]:
            tytul.append(ft.Container(
                padding=ft.Padding(7, 1, 7, 1), border_radius=RADIUS["pill"],
                bgcolor=ft.Colors.with_opacity(0.15, KOLOR_STATUS["info"]),
                content=ft.Text("cena teraz", size=FS["caption"], color=KOLOR_STATUS["info"]),
            ))
        wiersz = [
            ft.Icon(ft.Icons.SHOPPING_CART, size=18, color=ft.Colors.PRIMARY),
            ft.Column([ft.Row(tytul, spacing=6, tight=True)]
                      + ([podpis(szczegoly_zakupu(punkt))] if szczegoly_zakupu(punkt) else []),
                      spacing=1, tight=True, expand=True),
            ft.Column([
                wartosc(tekst_ceny_jednostki(punkt["cena"], punkt["jednostka"]), size=FS["body"]),
                podpis(_zmiana_wzgledem(punkt, poprzedni)),
            ], spacing=1, tight=True, horizontal_alignment=ft.CrossAxisAlignment.END),
        ]
        if wolno and not punkt["obecna"] and punkt.get("ids"):
            wiersz.append(ft.IconButton(
                icon=ft.Icons.DELETE_OUTLINE, icon_size=20, icon_color=KOLOR_STATUS["destructive"],
                tooltip="Usuń tę cenę z historii", on_click=lambda e, p=punkt: usun(p),
            ))
        zawartosc.append(ft.Container(
            padding=ft.Padding(12, 8, 8 if len(wiersz) > 3 else 12, 8), **powierzchnia(page, "blok"),
            content=ft.Row(wiersz, spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ))

    przyciski = []
    if wolno:
        przyciski.append(ft.OutlinedButton("Dopisz cenę", icon=ft.Icons.ADD, on_click=lambda e: dopisz()))
    if czesc.get("link"):
        przyciski.append(ft.OutlinedButton("Strona produktu", icon=ft.Icons.OPEN_IN_NEW,
                                           on_click=lambda e: otworz_strone(page, czesc["link"])))
    if przyciski:
        zawartosc.append(ft.Row(przyciski, spacing=SPACING["sm"], wrap=True))

    bs.content.content = ft.Column(zawartosc, tight=True, spacing=SPACING["sm"])
    otworz_dno(page, bs)
    return bs


# ============================================================================
#  OKNA: „DOPISZ CENĘ” I „KUPIŁEM PONOWNIE”
# ============================================================================


def _odswiez(page: ft.Page, opis):
    try:
        page.update()
    except Exception:
        log.polkniety(opis)


def dialog_dopisania_ceny(page: ft.Page, auto_id, nazwa, jednostka=None, po_zapisie=None):
    """Zakup ze starego paragonu: data, cena za jednostkę, ilość i sklep. Bez
    daty nie przyjmujemy — punkt bez „kiedy” nie ma miejsca na krzywej."""
    jednostka = jednostka or "szt"
    e_data = pole_daty(page, "Data zakupu*")
    e_cena = ft.TextField(label=f"Cena za 1 {jednostka} ({symbol_waluty()})*",
                          keyboard_type=ft.KeyboardType.NUMBER, **styl_pola())
    e_ilosc = ft.TextField(label=f"Ile kupiono ({jednostka}, opcjonalnie)",
                           keyboard_type=ft.KeyboardType.NUMBER, **styl_pola())
    sklep = PoleSklepu(page, db.sklepy_czesci(auto_id))

    def zapisz(e):
        for pole in (e_data, e_cena, e_ilosc):
            ustaw_blad(pole)
        cena = parsuj_float(e_cena.value, None) if (e_cena.value or "").strip() else None
        ilosc = parsuj_float(e_ilosc.value, None) if (e_ilosc.value or "").strip() else None
        bledy = False
        if not (e_data.value or "").strip():
            ustaw_blad(e_data, "Podaj datę zakupu")
            bledy = True
        if cena is None or cena <= 0:
            ustaw_blad(e_cena, "Podaj cenę większą od zera")
            bledy = True
        if (e_ilosc.value or "").strip() and (ilosc is None or ilosc <= 0):
            ustaw_blad(e_ilosc, "Podaj poprawną ilość")
            bledy = True
        if bledy:
            return _odswiez(page, "błędy w oknie dopisania ceny")
        zakup_id = db.dopisz_cene_czesci(auto_id, nazwa, e_data.value, cena, jednostka, sklep.value, ilosc)
        zamknij_dialog(page, dlg)
        if not zakup_id:
            return pokaz_komunikat(page, "Nie zapisano ceny — nie masz uprawnień do zmian w tym pojeździe.",
                                   KOLOR_STATUS["error"])
        pokaz_komunikat(page, f"Dopisano cenę z {e_data.value} do historii.")
        wypchnij_w_tle(page, auto_id, "historia cen")
        if po_zapisie:
            po_zapisie()

    # Okno przewijane w całości (`scrollable`) z zadaną szerokością treści —
    # ten sam układ co podgląd kopii: na niskim ekranie z klawiaturą pola
    # nie wychodzą poza okno.
    dlg = ft.AlertDialog(
        modal=True, scrollable=True,
        title=ft.Row([ft.Icon(ft.Icons.ADD_CHART, color=ft.Colors.PRIMARY),
                      ft.Text("Dopisz cenę", weight="bold", expand=True)], spacing=8),
        content=ft.Container(width=SZEROKOSC_OKNA, content=ft.Column([
            podpis(f"{nazwa} — zakup ze starego paragonu albo faktury."),
            e_data, e_cena, e_ilosc, sklep.kontrolka,
        ], tight=True, spacing=10)),
        actions=[
            ft.TextButton("Anuluj", on_click=lambda e: zamknij_dialog(page, dlg)),
            ft.Button("Zapisz", on_click=zapisz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    otworz_dialog(page, dlg)
    return dlg


class OknoKupilemPonownie:
    """Okno „Kupiłem ponownie”: ilość, koszt albo cena za jednostkę (liczą się
    nawzajem), sklep, data (dziś); nad polami ostatnia i najtańsza cena, przy linku —
    strona produktu. Zapis: db.kup_ponownie."""

    def __init__(self, page: ft.Page, auto_id, czesc, po_zapisie=None):
        self._page = page
        self.auto_id = auto_id
        self.czesc = czesc
        self.po_zapisie = po_zapisie
        jednostka = czesc.get("jednostka") or "szt"
        punkty = db.historia_cen_czesci(auto_id, czesc["nazwa"])
        ostatnio_kupiono = next((p["ilosc"] for p in reversed(punkty) if p.get("ilosc")), None)

        self.e_ilosc = ft.TextField(label=f"Ile kupiono ({jednostka})*", value=liczba_do_pola(ostatnio_kupiono or 1),
                                    keyboard_type=ft.KeyboardType.NUMBER, **styl_pola())
        self.e_koszt = ft.TextField(label=f"Zapłacono razem ({symbol_waluty()})",
                                    keyboard_type=ft.KeyboardType.NUMBER, **styl_pola())
        self.e_cena = ft.TextField(label=f"Cena za 1 {jednostka} ({symbol_waluty()})",
                                   keyboard_type=ft.KeyboardType.NUMBER, **styl_pola())
        self.e_data = pole_daty(page, "Data zakupu", datetime.now().strftime("%d.%m.%Y"))
        self.sklep = PoleSklepu(page, db.sklepy_czesci(auto_id), czesc.get("sklep") or "")
        # Pole wpisane ręcznie przestaje być przeliczane — jak w formularzu pozycji.
        self._wpisane = {"koszt": False, "cena": False}
        self.e_koszt.on_change = lambda e: self._przelicz("koszt")
        self.e_cena.on_change = lambda e: self._przelicz("cena")
        self.e_ilosc.on_change = lambda e: self._przelicz("ilosc")

        tresc = [ft.Text(czesc["nazwa"], size=FS["body"], weight="w500")]
        podpowiedz = podpowiedz_ceny(punkty)
        if podpowiedz:
            tresc.append(podpis(podpowiedz))
        tresc += [self.e_ilosc, self.e_koszt, self.e_cena, self.sklep.kontrolka, self.e_data]
        if czesc.get("link"):
            tresc.append(ft.TextButton("Sprawdź cenę na stronie produktu", icon=ft.Icons.OPEN_IN_NEW,
                                       on_click=lambda e: otworz_strone(page, czesc["link"])))

        self.dlg = ft.AlertDialog(
            modal=True, scrollable=True,
            title=ft.Row([ft.Icon(ft.Icons.ADD_SHOPPING_CART, color=ft.Colors.PRIMARY),
                          ft.Text("Kupiłem ponownie", weight="bold", expand=True)], spacing=8),
            content=ft.Container(width=SZEROKOSC_OKNA, content=ft.Column(tresc, tight=True, spacing=10)),
            actions=[
                ft.TextButton("Anuluj", on_click=lambda e: zamknij_dialog(page, self.dlg)),
                ft.Button("Dodaj do stanu", on_click=self.zapisz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def _liczba(self, pole):
        return parsuj_float(pole.value, None) if (pole.value or "").strip() else None

    def _przelicz(self, zrodlo):
        ilosc, koszt, cena = self._liczba(self.e_ilosc), self._liczba(self.e_koszt), self._liczba(self.e_cena)
        if zrodlo in ("koszt", "cena"):
            self._wpisane[zrodlo] = (koszt if zrodlo == "koszt" else cena) is not None
        if self._wpisane["koszt"] and not self._wpisane["cena"]:
            self.e_cena.value = liczba_do_pola(db.cena_jednostkowa_z_zakupu(koszt, ilosc))
        elif self._wpisane["cena"] and not self._wpisane["koszt"]:
            self.e_koszt.value = liczba_do_pola(round(cena * ilosc, 2)) if cena is not None and ilosc else ""
        _odswiez(self._page, "przeliczenie ceny w oknie „Kupiłem ponownie”")

    def zapisz(self, e):
        for pole in (self.e_ilosc, self.e_koszt, self.e_cena):
            ustaw_blad(pole)
        ilosc = self._liczba(self.e_ilosc)
        cena = self._liczba(self.e_cena)
        if cena is None:
            cena = db.cena_jednostkowa_z_zakupu(self._liczba(self.e_koszt), ilosc)
        bledy = False
        if ilosc is None or ilosc <= 0:
            ustaw_blad(self.e_ilosc, "Podaj, ile kupiono")
            bledy = True
        if cena is None or cena <= 0:
            ustaw_blad(self.e_cena, "Podaj cenę albo kwotę z paragonu")
            bledy = True
        if bledy:
            return _odswiez(self._page, "błędy w oknie „Kupiłem ponownie”")

        wynik = db.kup_ponownie(self.czesc["id"], ilosc, cena, self.sklep.value, self.e_data.value)
        zamknij_dialog(self._page, self.dlg)
        if not wynik:
            return pokaz_komunikat(self._page, "Nie zapisano zakupu — pozycji już nie ma albo nie masz uprawnień.",
                                   KOLOR_STATUS["error"])
        jednostka = self.czesc.get("jednostka") or "szt"
        pokaz_komunikat(self._page, f"Dodano {tekst_ilosci(ilosc)} {jednostka} — na stanie "
                                    f"{tekst_ilosci(wynik['stan'])} {jednostka}.")
        wypchnij_w_tle(self._page, self.auto_id, "magazyn")
        if self.po_zapisie:
            self.po_zapisie()

    def pokaz(self):
        otworz_dialog(self._page, self.dlg)
        return self


def dialog_kupilem_ponownie(page: ft.Page, auto_id, czesc, po_zapisie=None):
    """Otwiera okno „Kupiłem ponownie” dla pozycji `czesc`
    ({"id", "nazwa", "jednostka", "sklep", "link"})."""
    return OknoKupilemPonownie(page, auto_id, czesc, po_zapisie).pokaz()


__all__ = [
    "CEN_NA_KARCIE",
    "MAKS_PODPOWIEDZI_SKLEPOW",
    "OknoKupilemPonownie",
    "PoleSklepu",
    "SZEROKOSC_OKNA",
    "akcje_linku",
    "chip_sklepu",
    "dialog_dopisania_ceny",
    "dialog_kupilem_ponownie",
    "dzien_zakupu",
    "miesiac_zakupu",
    "opis_wczesniejszych_cen",
    "podpowiedz_ceny",
    "pokaz_historie_cen",
    "szczegoly_zakupu",
    "tekst_ceny_jednostki",
    "wiersz_cen_na_karcie",
]
