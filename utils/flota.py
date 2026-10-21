"""Ekran floty (N-07): karta wydatków, karta auta, nagłówki i zdania. Liczby — db/flota.py;
terminy rysuje oś „Co przede mną” (utils/przyszlosc.py) z autem nad nazwą."""

import flet as ft

import db
from date import parsuj_date
from state import MIESIACE_NAZWY

from .stale import FS, IKONY_KATEGORII_KOSZTOW, IKONY_KOKPITU, KOLOR_STATUS, RADIUS, SPACING, formatuj_liczba
from .format import MIESIACE_DOPELNIACZ, symbol_waluty
from .typografia import etykieta, podpis, wartosc
from .animacje import ScenaWejscia
from .wyglad import pasek_zawijany, powierzchnia, tlo_toru, wiersz_udzialu
from .wykresy import KOLORY_SERII_KOSZTU, gauge_kondycji, znacznik_trendu
from .pojazd import tablica_rejestracyjna, wskaznik_kondycji
from .komponenty import karta_listy


IKONA_FLOTY = IKONY_KOKPITU["flota"]

# Kolejność „wiader” w podziale wydatków floty (jak na wykresie struktury kosztów).
KATEGORIE_FLOTY = ("paliwo", "serwis", "inne")


def kwota_floty(kwota):
    return f"{formatuj_liczba(kwota or 0.0, 0)} {symbol_waluty()}"


def _dzien_slowami(tekst):
    dzien = parsuj_date(tekst)
    return f"{dzien.day} {MIESIACE_DOPELNIACZ[dzien.month - 1]}"


def opis_sprzedanych(sprzedane):
    """„W sumie roku także sprzedane w tym roku: Golf (810 zł, do 3 marca).”"""
    czesci = [f"{s['nazwa']} ({kwota_floty(s['rok'])}, do {_dzien_slowami(s['data_sprzedazy'])})"
              for s in sprzedane]
    return "W sumie roku także sprzedane w tym roku: " + ", ".join(czesci) + "."


def opis_pilnych(pilne, zalegle):
    """„2 pilne terminy · 1 po terminie”; pusto, gdy nic nie goni."""
    if not pilne:
        return ""
    tekst = db.liczba_z_odmiana(pilne, "pilny termin", "pilne terminy", "pilnych terminów")
    if zalegle:
        tekst += f" · {formatuj_liczba(zalegle, 0)} po terminie"
    return tekst


def kolor_paska_auta(auto):
    """Pasek karty auta: czerwony — coś po terminie, pomarańczowy — w progu przypomnienia."""
    if auto["zalegle"]:
        return KOLOR_STATUS["critical"]
    if auto["pilne"]:
        return KOLOR_STATUS["warning"]
    return None


def _chip(ikona, tekst, kolor):
    return ft.Container(
        padding=ft.Padding(8, 2, 10, 2), border_radius=RADIUS["pill"], bgcolor=ft.Colors.with_opacity(0.12, kolor),
        content=ft.Row([
            ft.Icon(ikona, size=13, color=kolor),
            ft.Text(tekst, size=FS["caption"], weight="bold", color=kolor, no_wrap=True),
        ], spacing=4, tight=True),
    )


def chipy_auta(auto):
    """Pilne terminy, najdroższe w tym roku, tylko podgląd — to, co karta auta mówi na skróty."""
    chipy = []
    if auto["pilne"]:
        kolor = kolor_paska_auta(auto)
        ikona = ft.Icons.PRIORITY_HIGH if auto["zalegle"] else ft.Icons.EVENT
        chipy.append(_chip(ikona, opis_pilnych(auto["pilne"], auto["zalegle"]), kolor))
    if auto["najdrozsze"]:
        chipy.append(_chip(ft.Icons.WORKSPACE_PREMIUM, "Najdroższe w tym roku", KOLOR_STATUS["accent"]))
    if auto["podglad"]:
        chipy.append(_chip(ft.Icons.VISIBILITY, "Tylko podgląd", KOLOR_STATUS["info"]))
    return chipy


def naglowek_sekcji_floty(ikona, tytul, opis=""):
    elementy = [ft.Row([
        ft.Icon(ikona, size=18, color=ft.Colors.PRIMARY),
        ft.Text(tytul, size=FS["title"], weight="bold", color=ft.Colors.PRIMARY, expand=True,
                max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
    ], spacing=8)]
    if opis:
        elementy.append(podpis(opis, size=FS["caption"]))
    return ft.Container(padding=ft.Padding(0, SPACING["sm"], 0, 0), content=ft.Column(elementy, spacing=2))


# ============================================================================
#  WYDATKI
# ============================================================================

def _kolumna_okresu(tytul, teraz, wczesniej, za_wczesnie, scena):
    if za_wczesnie:
        chip = znacznik_trendu(None, rozmiar=FS["caption"], tekst_bez_trendu="Za wcześnie",
                               ikona_bez_trendu=ft.Icons.INFO_OUTLINE)
    else:
        chip = znacznik_trendu(db.zmiana_rok_do_roku(teraz, wczesniej), wzrost_zly=True, rozmiar=FS["caption"],
                               tekst_bez_trendu="Brak porównania", ikona_bez_trendu=ft.Icons.INFO_OUTLINE)
    return ft.Column([
        etykieta(tytul),
        scena.liczba(teraz, kwota_floty, size=FS["heading"], weight="bold", no_wrap=True),
        chip,
        podpis(f"rok temu {kwota_floty(wczesniej)}", size=FS["caption"]),
    ], spacing=SPACING["xs"], expand=True)


def _wiersz_najdrozszego(najdrozsze):
    tekst = (f"{najdrozsze['nazwa']} — {kwota_floty(najdrozsze['kwota'])}, "
             f"{formatuj_liczba(najdrozsze['udzial'] * 100, 0)}% roku floty")
    if najdrozsze["sprzedane"]:
        tekst += " (sprzedane)"
    return ft.Row([
        ft.Icon(ft.Icons.WORKSPACE_PREMIUM, size=18, color=KOLOR_STATUS["accent"]),
        ft.Column([
            etykieta("Najdroższe auto w tym roku"),
            ft.Text(tekst, size=FS["body"], max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
        ], spacing=0, expand=True),
    ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)


def karta_wydatkow_floty(page, koszty, scena=None):
    """Miesiąc i rok do dziś z porównaniem do tych samych dni rok wcześniej, najdroższe auto roku,
    podział roku na paliwo, serwis i inne (miesiąc w dopisku) i sprzedane w tym roku."""
    scena = scena or ScenaWejscia(wlaczona=False)
    dzis, razem = koszty["dzis"], koszty["razem"]
    wiersze = [
        ft.Row([
            ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET, size=16, color=ft.Colors.PRIMARY),
            etykieta("Wydatki wszystkich aut do dziś", expand=True),
        ], spacing=6),
        ft.Row([
            _kolumna_okresu(MIESIACE_NAZWY[dzis.month - 1], razem["miesiac"]["razem"],
                            razem["miesiac_rok_temu"]["razem"], dzis.day < db.DZIEN_POROWNANIA_MIESIACA, scena),
            _kolumna_okresu(f"Rok {dzis.year}", razem["rok"]["razem"], razem["rok_rok_temu"]["razem"], False, scena),
        ], spacing=SPACING["md"], vertical_alignment=ft.CrossAxisAlignment.START),
    ]
    if koszty["najdrozsze"]:
        wiersze.append(_wiersz_najdrozszego(koszty["najdrozsze"]))
    rok = razem["rok"]
    if rok["razem"] > 0:
        wiersze.append(ft.Divider(height=1))
        wiersze += [wiersz_udzialu(
            page, IKONY_KATEGORII_KOSZTOW[kat], db.KATEGORIE_BUDZETU[kat], rok[kat], rok[kat] / rok["razem"] * 100,
            KOLORY_SERII_KOSZTU[kat], dopisek=f"w tym miesiącu {kwota_floty(razem['miesiac'][kat])}", scena=scena,
        ) for kat in KATEGORIE_FLOTY]
    if koszty["sprzedane"]:
        wiersze.append(podpis(opis_sprzedanych(koszty["sprzedane"]), size=FS["caption"]))
    return ft.Container(padding=SPACING["md"], **powierzchnia(page, "karta"),
                        content=ft.Column(wiersze, spacing=SPACING["sm"]))


# ============================================================================
#  AUTA
# ============================================================================

def _pasek_udzialu(page, udzial, scena):
    tor = ft.ProgressBar(value=max(0.0, min(1.0, udzial)), color=ft.Colors.PRIMARY, bgcolor=tlo_toru(page),
                         height=6, border_radius=3)
    scena.nastepny_wiersz()
    return scena.wskaznik(tor)


def _linia_kondycji(auto):
    powod = auto["powod"]
    if powod:
        kolor = KOLOR_STATUS["critical" if powod["waga"] == "krytyczna" else "warning"]
        return ft.Text(f"{powod['opis']} (−{formatuj_liczba(powod['punkty'], 0)} pkt)", size=FS["caption"],
                       color=kolor, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)
    if auto["kondycja"] is None:
        return None
    return ft.Text("Nic nie obniża kondycji", size=FS["caption"], color=KOLOR_STATUS["ok"])


def karta_auta_floty(page, auto, on_kondycja, scena=None):
    """Karta auta: kondycja (dotknięcie — rozpiska), nazwa i tablica, wydatki roku, największy
    minus kondycji, udział we flocie i chipy. Zwraca (karta, kontener) jak karta_listy."""
    scena = scena or ScenaWejscia(wlaczona=False)
    _, _, opis_kondycji = wskaznik_kondycji(auto["kondycja"])
    wynik = auto["kondycja"] if auto["kondycja"] is not None else "–"
    pierscien = ft.Container(
        content=gauge_kondycji(auto["kondycja"], rozmiar=52, grubosc=5, pokaz_max=False, scena=scena),
        border_radius=RADIUS["pill"], ink=True, on_click=on_kondycja,
        tooltip=f"Kondycja {wynik}/100 ({opis_kondycji}) — dotknij, aby zobaczyć rozpiskę",
    )
    tablica = (tablica_rejestracyjna(auto["nr_rej"], wysokosc=20) if auto["nr_rej"]
               else podpis("Brak rejestracji", size=FS["caption"]))
    gora = ft.Row([
        pierscien,
        ft.Column([
            ft.Text(str(auto["nazwa"]), size=FS["body_strong"], weight="bold", max_lines=2,
                    overflow=ft.TextOverflow.ELLIPSIS),
            tablica,
        ], spacing=4, expand=True),
        ft.Column([
            wartosc(kwota_floty(auto["rok"]), no_wrap=True),
            etykieta("w tym roku"),
        ], spacing=0, horizontal_alignment=ft.CrossAxisAlignment.END),
    ], spacing=SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.CENTER)

    linie = [gora]
    kondycja = _linia_kondycji(auto)
    if kondycja is not None:
        linie.append(kondycja)
    linie.append(_pasek_udzialu(page, auto["udzial"], scena))
    linie.append(podpis(f"{formatuj_liczba(auto['udzial'] * 100, 0)}% wydatków floty w roku · "
                        f"w tym miesiącu {kwota_floty(auto['miesiac'])}", size=FS["caption"]))
    chipy = chipy_auta(auto)
    if chipy:
        linie.append(pasek_zawijany(chipy))
    return karta_listy(ft.Column(linie, spacing=SPACING["xs"]), kolor_paska=kolor_paska_auta(auto), page=page)


def nota_floty():
    return (
        "Wydatki to paliwo i prąd, serwis i inne koszty (raty leasingu i kredytu w całości) od pierwszego "
        "dnia miesiąca albo roku do dziś, porównane z tymi samymi dniami rok wcześniej — razem z autami, "
        "których już nie masz. Auto sprzedane w tym roku dolicza swoje wydatki do sumy roku. Terminy to "
        "„Co przede mną” każdego auta na jednej liście: zaległe na górze, prognoza miesiąca to suma "
        "prognoz aut. Pilne — po terminie albo w progu przypomnienia. Kondycja i jej największy minus "
        "liczą się tak samo jak na karcie auta."
    )


__all__ = [
    "IKONA_FLOTY",
    "KATEGORIE_FLOTY",
    "chipy_auta",
    "karta_auta_floty",
    "karta_wydatkow_floty",
    "kolor_paska_auta",
    "kwota_floty",
    "naglowek_sekcji_floty",
    "nota_floty",
    "opis_pilnych",
    "opis_sprzedanych",
]
