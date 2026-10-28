"""Lista „Wizyty w warsztacie”: karta wizyty, podsumowanie nad listą i treść arkusza
szczegółów. Dane: db.lista_wizyt, db.podsumowanie_wizyt."""

from datetime import datetime

import flet as ft

import db
from date import parsuj_date

from .stale import FS, KOLOR_STATUS, RADIUS, SPACING, formatuj_liczba
from .format import formatuj_dystans, formatuj_telefon, symbol_waluty
from .typografia import KOLOR_DRUGIEGO_PLANU, etykieta, podpis, pole, wartosc
from .wyglad import powierzchnia, tlo_odznaki, tlo_toru, wypelnienie_karty
from .system import pokaz_na_mapie, zadzwon
from .magazyn import opis_zuzycia_z_magazynu, tekst_ilosci
from .koszt_naprawy import SERIE_ROZBICIA, opis_rozbicia_kosztu
from .gwarancja import wiersz_gwarancji
from .notatki import podglad_notatki
from .zalaczniki import wskaznik_zalacznikow
from .wykresy import _kropka_legendy
from .komponenty import karta_listy, wizualizacja_tagow, znacznik_atrybucji
from .warsztaty import pokaz_karte_warsztatu
from .awarie import chip_rodzaju_serwisu


TYTUL_WIZYTY_BEZ_WARSZTATU = "Wizyta"
# Więcej chipów podzespołów karta nie pokazuje — resztę liczy „+N”, całość jest w arkuszu.
MAKS_CHIPOW_POZYCJI = 4
NAZWY_SERII_ROZBICIA = {"robocizna": "Robocizna", "czesci": "Części", "z_magazynu": "Z magazynu"}
KOLOR_MAGAZYNU = next(kolor for klucz, _n, _i, kolor in SERIE_ROZBICIA if klucz == "z_magazynu")


def _kwota(kwota):
    return f"{formatuj_liczba(kwota)} {symbol_waluty()}"


def tytul_wizyty(wizyta):
    """Nazwa warsztatu albo „Wizyta”, gdy go nie wybrano."""
    return wizyta.get("warsztat") or TYTUL_WIZYTY_BEZ_WARSZTATU


def opis_dnia_wizyty(wizyta, j=None):
    """„21.01.2026 · 106 000 km” — sama data, gdy licznika nie ma."""
    czesci = [str(wizyta.get("data") or "")]
    if int(wizyta.get("przebieg") or 0) > 0:
        czesci.append(formatuj_dystans(int(wizyta["przebieg"]), 0, j))
    return " · ".join(c for c in czesci if c)


def kiedy_ostatnia(ostatnia, dzis=None):
    """„dziś”, „wczoraj”, „9 miesięcy temu” — None dla daty z przyszłości."""
    dni = ostatnia["dni"]
    if dni < 0:
        return None
    if dni == 0:
        return "dziś"
    if dni == 1:
        return "wczoraj"
    dzis = dzis or datetime.now().date()
    return f"{db.czas_slownie(parsuj_date(ostatnia['data']), dzis)} temu"


def chip_pozycji(pozycja):
    """Podzespół wizyty na karcie, z ceną pozycji, gdy ją wpisano."""
    tekst = pozycja["nazwa"]
    if pozycja.get("cena"):
        tekst += f" · {_kwota(pozycja['cena'])}"
    return ft.Container(
        padding=ft.Padding(8, 3, 8, 3), border_radius=RADIUS["pill"], bgcolor=tlo_odznaki(),
        content=ft.Text(tekst, size=FS["label"], color=ft.Colors.ON_SURFACE),
    )


def chipy_pozycji(pozycje, maks=MAKS_CHIPOW_POZYCJI):
    """Podzespoły jako chipy zawijane do następnej linii; ponad `maks` — „+N”."""
    if not pozycje:
        return podpis("Bez wymienionych podzespołów", italic=True)
    chipy = [chip_pozycji(p) for p in pozycje[:maks]]
    if len(pozycje) > maks:
        chipy.append(ft.Container(
            padding=ft.Padding(8, 3, 8, 3), border_radius=RADIUS["pill"], bgcolor=tlo_odznaki(),
            content=ft.Text(f"+{len(pozycje) - maks}", size=FS["label"], color=ft.Colors.ON_SURFACE),
        ))
    return ft.Row(chipy, wrap=True, spacing=6, run_spacing=6)


def pasek_rozbicia_kosztu(rozbicie):
    """Pasek robocizna / części / z magazynu z legendą kwot — None, gdy rachunku nie
    rozbito albo nie ma czego dzielić."""
    if not rozbicie or not rozbicie["podzielony"] or rozbicie["razem"] <= 0:
        return None
    serie = [(NAZWY_SERII_ROZBICIA[klucz], kolor, rozbicie[klucz])
             for klucz, _nazwa, _ikona, kolor in SERIE_ROZBICIA if (rozbicie[klucz] or 0) > 0]
    segmenty = [ft.Container(height=6, bgcolor=kolor, expand=max(1, round(kwota * 100)))
                for _n, kolor, kwota in serie]
    return ft.Column([
        ft.Container(height=6, border_radius=3, bgcolor=tlo_toru(), clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                     content=ft.Row(segmenty, spacing=2)),
        ft.Row([_kropka_legendy(kolor, f"{nazwa} {_kwota(kwota)}") for nazwa, kolor, kwota in serie],
               wrap=True, spacing=SPACING["md"], run_spacing=2),
    ], spacing=SPACING["xs"])


def wiersz_magazynu(zuzycie, z_kwota=True):
    """„Z magazynu: Filtr oleju (1 szt) · w tym 19,50 zł” z ikoną półki albo None. Bez kwoty,
    gdy podaje ją już legenda paska rozbicia."""
    opis = opis_zuzycia_z_magazynu(zuzycie)
    if not opis:
        return None
    if not z_kwota:
        opis = "Z magazynu: " + ", ".join(f"{c['nazwa']} ({tekst_ilosci(c['ilosc'])} {c['jednostka']})"
                                          for c in zuzycie["pozycje"])
    return ft.Row([ft.Icon(ft.Icons.INVENTORY_2, size=14, color=KOLOR_MAGAZYNU),
                   podpis(opis, expand=True)], spacing=6, vertical_alignment=ft.CrossAxisAlignment.START)


def _przyciski_kontaktu(page, kontakt):
    telefon, adres = kontakt or (None, None)
    przyciski = []
    if telefon:
        przyciski.append(ft.IconButton(
            ft.Icons.PHONE, icon_size=16, icon_color=ft.Colors.PRIMARY, tooltip="Zadzwoń",
            on_click=lambda e: zadzwon(page, telefon), style=ft.ButtonStyle(padding=0)))
    if adres:
        przyciski.append(ft.IconButton(
            ft.Icons.MAP, icon_size=16, icon_color=ft.Colors.PRIMARY, tooltip="Pokaż na mapie",
            on_click=lambda e: pokaz_na_mapie(page, adres), style=ft.ButtonStyle(padding=0)))
    return przyciski


def karta_wizyty(page: ft.Page, wizyta, j=None, kontakt=None, auto_id=None, mapa_tagow=None,
                 wspolny=False, on_notatka=None):
    """Karta listy wizyt: warsztat i koszt, dzień z licznikiem, rodzaj i kontakt, podzespoły,
    rozbicie rachunku, magazyn, gwarancja, tagi, notatka. Zwraca (karta, kontener) jak
    karta_listy. `kontakt` — (telefon, adres) warsztatu z rejestru albo None."""
    tresc = [
        ft.Row([
            wartosc(tytul_wizyty(wizyta), size=FS["title"], max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
                    expand=True),
            wskaznik_zalacznikow(page, wizyta["pliki"], "Wizyta"),
            wartosc(_kwota(wizyta["koszt"]), color=KOLOR_STATUS["cost"], no_wrap=True),
        ], spacing=SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ft.Row([podpis(opis_dnia_wizyty(wizyta, j), expand=True),
                *[c for c in (chip_rodzaju_serwisu(wizyta["rodzaj"]),) if c],
                *_przyciski_kontaktu(page, kontakt)],
               spacing=SPACING["xs"], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        chipy_pozycji(wizyta["pozycje"]),
    ]
    pasek = pasek_rozbicia_kosztu(wizyta["rozbicie"])
    for dodatek in (pasek, wiersz_magazynu(wizyta["zuzycie"], z_kwota=pasek is None)):
        if dodatek is not None:
            tresc.append(dodatek)
    if wizyta["gwarancja"]:
        tresc.append(wiersz_gwarancji(wizyta["gwarancja"], j, szczegoly=False))
    if wizyta["tagi"]:
        tresc.append(wizualizacja_tagow(wizyta["tagi"], auto_id, mapa_tagow))
    tresc.append(podglad_notatki(page, wizyta["notatki"], tytul="Notatka do wizyty", on_edytuj=on_notatka))
    if wspolny and (wizyta["dodane_przez"] or wizyta["zmodyfikowane_przez"]):
        tresc.append(znacznik_atrybucji(wizyta["dodane_przez"], wizyta["zmodyfikowane_przez"],
                                        wizyta["data_modyfikacji"]))
    return karta_listy(ft.Column(tresc, spacing=6), page=page)


def tekst_do_szukania(wizyta):
    """Wszystko, po czym wyszukiwarka listy znajduje wizytę — małymi literami."""
    czesci = [wizyta["data"], wizyta["wykonawca"], wizyta["koszt"], wizyta["tagi"], wizyta["notatki"],
              *(p["nazwa"] for p in wizyta["pozycje"]),
              opis_zuzycia_z_magazynu(wizyta["zuzycie"]), opis_rozbicia_kosztu(wizyta["rozbicie"])]
    if db.rodzaj_serwisu(wizyta["rodzaj"]):
        czesci.append(db.etykieta_rodzaju_serwisu(wizyta["rodzaj"]))
    return " ".join(str(c) for c in czesci if c).lower()


class PodsumowanieWizyt:
    """Karta nad listą: liczba wizyt, suma, średnia płatnych i ostatnia wizyta. `ustaw(dane)`
    przelicza ją po filtrze albo wyszukiwarce (dane z db.podsumowanie_wizyt)."""

    def __init__(self, page: ft.Page, dane=None):
        self._liczba = wartosc("0")
        self._suma = wartosc("—", color=KOLOR_STATUS["cost"])
        self._srednia = wartosc("—", color=KOLOR_STATUS["cost"])
        self._ostatnia = podpis("", expand=True)
        self._wiersz_ostatniej = ft.Row([ft.Icon(ft.Icons.HISTORY, size=16, color=KOLOR_DRUGIEGO_PLANU),
                                         self._ostatnia], spacing=6, vertical_alignment=ft.CrossAxisAlignment.START)
        kolumny = [("Wizyty", self._liczba), ("Razem", self._suma), ("Średnio", self._srednia)]
        self.kontrolka = ft.Container(
            padding=wypelnienie_karty(), **powierzchnia(page, "karta"),
            content=ft.Column([
                ft.Row([ft.Container(ft.Column([etykieta(nazwa), tekst], spacing=2), expand=True)
                        for nazwa, tekst in kolumny], spacing=SPACING["sm"],
                       vertical_alignment=ft.CrossAxisAlignment.START),
                self._wiersz_ostatniej,
            ], spacing=SPACING["sm"]),
        )
        if dane is not None:
            self.ustaw(dane)

    def ustaw(self, dane):
        self._liczba.value = str(dane["liczba"])
        self._suma.value = _kwota(dane["suma"]) if dane["suma"] else "—"
        self._srednia.value = _kwota(dane["srednia"]) if dane["srednia"] else "—"
        ostatnia = dane["ostatnia"]
        self._wiersz_ostatniej.visible = ostatnia is not None
        if ostatnia is not None:
            kiedy = kiedy_ostatnia(ostatnia)
            tekst = f"Ostatnia: {ostatnia['data']}" + (f" ({kiedy})" if kiedy else "")
            if ostatnia["warsztat"]:
                tekst += f" · {ostatnia['warsztat']}"
            self._ostatnia.value = tekst


def szczegoly_wizyty(page: ft.Page, wizyta, j=None, auto_id=None, wspolny=False):
    """Kontrolki arkusza wizyty nad akcjami: dzień i rodzaj, koszt z rozbiciem, podzespoły
    z cenami i własnymi gwarancjami, części z magazynu, gwarancja wspólna, notatka, tagi
    i autor (pliki otwiera akcja arkusza)."""
    elementy = [ft.Row([podpis(opis_dnia_wizyty(wizyta, j), expand=True),
                        *[c for c in (chip_rodzaju_serwisu(wizyta["rodzaj"], planowe=True),) if c]],
                       spacing=SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                pole("Koszt wizyty", _kwota(wizyta["koszt"]), color=KOLOR_STATUS["cost"])]
    pasek = pasek_rozbicia_kosztu(wizyta["rozbicie"])
    if pasek is not None:
        elementy.append(pasek)

    pozycje = wizyta["pozycje"]
    if pozycje:
        elementy.append(etykieta(f"Wymienione podzespoły ({len(pozycje)})"))
        for p in pozycje:
            wiersz = [ft.Icon(ft.Icons.BUILD, size=16, color=KOLOR_DRUGIEGO_PLANU),
                      ft.Text(p["nazwa"], size=FS["body"], expand=True)]
            if p["cena"]:
                wiersz.append(wartosc(_kwota(p["cena"]), no_wrap=True))
            elementy.append(ft.Row(wiersz, spacing=SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.CENTER))
            if p["gwarancja"] and p["wlasna_gwarancja"]:
                elementy.append(ft.Container(wiersz_gwarancji(p["gwarancja"], j), padding=ft.Padding(24, 0, 0, 0)))
    else:
        elementy.append(podpis("Bez wymienionych podzespołów", italic=True))

    zuzycie = (wizyta["zuzycie"] or {}).get("pozycje") or []
    if zuzycie:
        elementy.append(etykieta("Z magazynu"))
        for c in zuzycie:
            wiersz = [ft.Icon(ft.Icons.INVENTORY_2, size=16, color=KOLOR_MAGAZYNU),
                      ft.Text(f"{c['nazwa']} ({tekst_ilosci(c['ilosc'])} {c['jednostka']})", size=FS["body"],
                              expand=True)]
            if c["koszt"]:
                wiersz.append(wartosc(_kwota(c["koszt"]), no_wrap=True))
            elementy.append(ft.Row(wiersz, spacing=SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.CENTER))

    if wizyta["gwarancja"]:
        elementy.append(wiersz_gwarancji(wizyta["gwarancja"], j))
    if (wizyta["notatki"] or "").strip():
        elementy.append(ft.Row([ft.Icon(ft.Icons.STICKY_NOTE_2_OUTLINED, size=16, color=KOLOR_DRUGIEGO_PLANU),
                                ft.Text(wizyta["notatki"].strip(), size=FS["body"], italic=True, expand=True,
                                        selectable=True)],
                               spacing=SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.START))
    if wizyta["tagi"]:
        elementy.append(wizualizacja_tagow(wizyta["tagi"], auto_id))
    if wspolny and (wizyta["dodane_przez"] or wizyta["zmodyfikowane_przez"]):
        elementy.append(znacznik_atrybucji(wizyta["dodane_przez"], wizyta["zmodyfikowane_przez"],
                                           wizyta["data_modyfikacji"]))
    return elementy


def akcje_kontaktu_wizyty(page: ft.Page, state, wizyta, kontakt=None):
    """Pozycje arkusza dla warsztatu wizyty: telefon, mapa i karta warsztatu (wolno też
    w podglądzie)."""
    if not wizyta.get("warsztat"):
        return []
    telefon, adres = kontakt or (None, None)
    pozycje = []
    if telefon:
        pozycje.append({"ikona": ft.Icons.PHONE, "tekst": f"Zadzwoń: {formatuj_telefon(telefon)}", "czyta": True,
                        "akcja": lambda: zadzwon(page, telefon)})
    if adres:
        pozycje.append({"ikona": ft.Icons.MAP, "tekst": "Pokaż na mapie", "czyta": True,
                        "akcja": lambda: pokaz_na_mapie(page, adres)})
    pozycje.append({"ikona": ft.Icons.CAR_REPAIR, "tekst": "Karta warsztatu", "czyta": True,
                    "akcja": lambda: pokaz_karte_warsztatu(page, state, wizyta["warsztat"])})
    return pozycje


__all__ = [
    "KOLOR_MAGAZYNU",
    "MAKS_CHIPOW_POZYCJI",
    "NAZWY_SERII_ROZBICIA",
    "PodsumowanieWizyt",
    "TYTUL_WIZYTY_BEZ_WARSZTATU",
    "akcje_kontaktu_wizyty",
    "chip_pozycji",
    "chipy_pozycji",
    "karta_wizyty",
    "kiedy_ostatnia",
    "opis_dnia_wizyty",
    "pasek_rozbicia_kosztu",
    "szczegoly_wizyty",
    "tekst_do_szukania",
    "tytul_wizyty",
    "wiersz_magazynu",
]
