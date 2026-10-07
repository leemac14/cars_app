"""„Co przede mną”: słowa i kontrolki osi przyszłości (db.os_przyszlosci).

Liczby liczy warstwa danych, tu składa się z nich zdania i wiersze — tak jak
dla „Ile zostało do…” (utils/pojazd.py). Pozycje, które przyszły z odliczań
(dokumenty, gwarancje, podzespoły, okrągły przebieg), mówią tymi samymi
słowami co tamta lista (opis_odliczania, podpis_odliczania), żeby ten sam termin
nie brzmiał w dwóch miejscach inaczej.

Wiersz osi to kalendarz, nie odliczanie: z lewej dzień miesiąca dużą cyfrą
i dzień tygodnia, z prawej nazwa, kwota i jedno zdanie. Kolor mówi to samo, co
wszędzie: czerwony — po terminie albo ponad budżet, pomarańczowy — w progu
przypomnienia, niebieski — informacja (okrągły przebieg, podpowiedź zmiany
opon). Zwykły termin ma kolor akcentu, a założona kolejna wymiana — zwykły
tekst: to rachunek „jeśli wszystko w terminie”, a nie termin.
"""

import flet as ft

import db
from state import MIESIACE_NAZWY

from .stale import FS, KOLOR_STATUS, RADIUS, SPACING, formatuj_liczba, ikona_z_mapy
from .format import (
    MIESIACE_DOPELNIACZ, _odleglosc_w_czasie, formatuj_date_pl, formatuj_dni, opis_odliczania,
    podpis_odliczania, symbol_waluty, tytul_odliczania,
)
from .typografia import etykieta, podpis
from .wyglad import powierzchnia, tlo_karty, tlo_toru
from .pojazd import IKONY_ODLICZAN, KOLORY_STATUSU_ODLICZANIA


# Klucze ikon z db.os_przyszlosci: to, co znają odliczania, plus wpisy
# cykliczne — te same ikony co w panelu wydatków cyklicznych i w dzwonku.
IKONY_OSI = {
    **IKONY_ODLICZAN,
    "cykliczny": ft.Icons.AUTORENEW,
    "przypomnienie": ft.Icons.NOTIFICATIONS_ACTIVE,
    "opony": ft.Icons.TIRE_REPAIR,
    "budzet": ft.Icons.SAVINGS,
}

SKROTY_DNI_TYGODNIA = ("pn", "wt", "śr", "cz", "pt", "sb", "nd")

SKROTY_MIESIECY = ("sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru")

# Szerokość kolumny dnia — stała, żeby nazwy w kolejnych wierszach zaczynały
# się w jednej linii także wtedy, gdy dzień się nie powtarza.
SZEROKOSC_DNIA = 40

# Okresy wpisów cyklicznych, które mają swoje słowo („co miesiąc” czyta się
# szybciej niż „co 30 dni”); reszta — liczbą dni.
OKRESY_SLOWAMI = {
    1: "codziennie", 7: "co tydzień", 14: "co dwa tygodnie", 30: "co miesiąc", 31: "co miesiąc",
    91: "co kwartał", 92: "co kwartał", 182: "co pół roku", 183: "co pół roku",
    365: "co rok", 366: "co rok",
}

# Statusy, które coś mówią — reszta stoi w kolorze akcentu.
STATUSY_Z_KOLOREM = ("po_terminie", "blisko", "info")

# „sezon zimowy już trwa” — spóźniona zmiana opon z podpowiedzi kalendarza.
SEZONY_PRZYMIOTNIKIEM = {"Zimowe": "zimowy", "Letnie": "letni"}

# Oś bez żadnej kwoty: same terminy, a średniej jeszcze nie ma.
BEZ_KWOT_OSI = ("Bez kwot do zsumowania: prognoza ruszy po pierwszym pełnym miesiącu wpisów, "
                "a kwoty dadzą też wydatki cykliczne, raty i ceny wymian.")


# ============================================================================
#  SŁOWA
# ============================================================================

def kolor_pozycji_osi(pozycja):
    status = pozycja.get("status")
    if status in STATUSY_Z_KOLOREM:
        return KOLORY_STATUSU_ODLICZANIA[status]
    if pozycja.get("zakladana"):
        return KOLOR_STATUS["neutral"]
    return ft.Colors.PRIMARY


def kolor_paska_osi(pozycja):
    """Pasek z boku karty tylko przy tym, co wymaga uwagi."""
    return {"po_terminie": KOLOR_STATUS["critical"], "blisko": KOLOR_STATUS["warning"]}.get(pozycja.get("status"))


def kiedy_osi(dni, prognoza=False):
    """„dzisiaj”, „jutro”, „za 8 dni”, „za ok. 143 dni (~5 mies.)”, „3 dni po terminie”."""
    if dni is None:
        return ""
    if dni < 0:
        return f"{formatuj_dni(-dni)} po terminie"
    if dni == 0:
        return "dzisiaj"
    if dni == 1:
        return "jutro"
    tekst = f"za {'ok. ' if prognoza else ''}{formatuj_dni(dni)}"
    return tekst if dni <= 60 else f"{tekst} ({_odleglosc_w_czasie(dni)})"


def co_ile_osi(okres_dni):
    okres = int(okres_dni or 0)
    return OKRESY_SLOWAMI.get(okres) or f"co {formatuj_dni(okres)}"


def kwota_osi(pozycja):
    """„49,00 zł”; cena ostatniej wymiany to szacunek — „~350 zł”."""
    kwota = pozycja.get("kwota")
    if not kwota:
        return ""
    if pozycja.get("szacunek"):
        return f"~{formatuj_liczba(kwota, 0)} {symbol_waluty()}"
    return f"{formatuj_liczba(kwota)} {symbol_waluty()}"


def tytul_pozycji_osi(pozycja, j=None):
    """Nazwa wiersza — przy okrągłym przebiegu i limicie gwarancji zależna od
    jednostki z Ustawień, jak w „Ile zostało do…”."""
    return tytul_odliczania(pozycja, j)


def _opis_budzetu(budzet):
    waluta = symbol_waluty()
    czesci = ["koniec roku" if budzet["okres"] == "rok" else "koniec miesiąca"]
    if budzet["status"] == "przekroczony":
        czesci.append(f"przekroczony o {formatuj_liczba(budzet['wydano'] - budzet['limit'], 0)} {waluta}")
    else:
        czesci.append(f"zostało {formatuj_liczba(budzet['pozostalo'], 0)} "
                      f"z {formatuj_liczba(budzet['limit'], 0)} {waluta}")
        if budzet.get("dzien_przekroczenia"):
            czesci.append(f"w tym tempie limit skończy się ok. {budzet['dzien_przekroczenia'][:5]}")
    return czesci


def opis_pozycji_osi(pozycja, j=None):
    """Zdanie pod nazwą: kiedy i co z tego wynika („za 8 dni · co miesiąc”,
    „za 12 dni · rata 13 z 48”, „koniec miesiąca · zostało 240 zł z 1 000 zł”)."""
    rodzaj = pozycja.get("rodzaj")
    if pozycja.get("zakladana"):
        czesci = [kiedy_osi(pozycja.get("dni"), prognoza=True), "kolejna, jeśli poprzednia w terminie"]
    elif pozycja.get("zrodlo") is not None:
        czesci = [opis_odliczania(pozycja["zrodlo"], j)]
        if pozycja.get("najpozniej"):
            czesci.append(f"najpóźniej {kiedy_osi(pozycja.get('dni'))}")
    elif rodzaj == "budzet":
        czesci = _opis_budzetu(pozycja["budzet"])
    else:
        czesci = [kiedy_osi(pozycja.get("dni"))]
        if pozycja.get("platnosc"):
            czesci.append(pozycja["platnosc"])
        elif pozycja.get("sugestia"):
            if pozycja.get("status") == "blisko":
                czesci.append(f"sezon {SEZONY_PRZYMIOTNIKIEM.get(pozycja.get('sezon'), '')} już trwa")
            czesci.append("przypomnienie nie jest ustawione")
        elif pozycja.get("okres_dni"):
            czesci.append(co_ile_osi(pozycja["okres_dni"]))
    return " · ".join(c for c in czesci if c)


def dopisek_pozycji_osi(pozycja, j=None):
    """Druga linijka albo None — z odliczań: drugi licznik podzespołu, zakres
    gwarancji naprawy, notatka najlepszej oferty przy OC i AC."""
    zrodlo = pozycja.get("zrodlo")
    if zrodlo is None or pozycja.get("zakladana"):
        return None
    return zrodlo.get("opis_oferty") or podpis_odliczania(zrodlo, j)


def nazwa_miesiaca_osi(miesiac):
    return f"{MIESIACE_NAZWY[miesiac['miesiac'] - 1]} {miesiac['rok']}"


def prognoza_miesiaca_osi(miesiac):
    """„~1 650 zł” (z bieżącymi — szacunek), „850 zł” (same zaplanowane),
    pusto, gdy nie ma czego pokazać."""
    if miesiac["razem"] <= 0:
        return ""
    przyblizenie = "~" if miesiac["biezace"] else ""
    return f"{przyblizenie}{formatuj_liczba(miesiac['razem'], 0)} {symbol_waluty()}"


def opis_miesiaca_osi(miesiac):
    """„od dziś · bieżące ~540 zł + zaplanowane 360 zł · wydano już 380 zł”."""
    waluta = symbol_waluty()
    czesci = []
    if miesiac["biezacy"] and not miesiac["pelny"]:
        czesci.append("od dziś")
    elif not miesiac["pelny"]:
        koniec = miesiac["do"]
        czesci.append(f"do {koniec.day} {MIESIACE_DOPELNIACZ[koniec.month - 1]}")
    kwoty = []
    if miesiac["biezace"]:
        kwoty.append(f"bieżące ~{formatuj_liczba(miesiac['biezace'], 0)} {waluta}")
    if miesiac["zaplanowane"]:
        kwoty.append(f"zaplanowane {formatuj_liczba(miesiac['zaplanowane'], 0)} {waluta}")
    czesci.append(" + ".join(kwoty) or "nic zaplanowanego")
    if miesiac["wydano"]:
        czesci.append(f"wydano już {formatuj_liczba(miesiac['wydano'], 0)} {waluta}")
    return " · ".join(czesci)


def opis_okna_osi(os_dane):
    """„Następne 90 dni · do 5 stycznia 2027”."""
    return f"Następne {formatuj_dni(os_dane['dni'])} · do {formatuj_date_pl(os_dane['do'])}"


def sklad_prognozy_osi(podsumowanie):
    """„bieżące ~2 400 zł · zaplanowane 2 450 zł · zaległe 200 zł”."""
    waluta = symbol_waluty()
    czesci = []
    if podsumowanie["biezace"]:
        czesci.append(f"bieżące ~{formatuj_liczba(podsumowanie['biezace'], 0)} {waluta}")
    if podsumowanie["zaplanowane"]:
        czesci.append(f"zaplanowane {formatuj_liczba(podsumowanie['zaplanowane'], 0)} {waluta}")
    if podsumowanie["kwota_zalegla"]:
        czesci.append(f"zaległe {formatuj_liczba(podsumowanie['kwota_zalegla'], 0)} {waluta}")
    return " · ".join(czesci)


def razem_osi(podsumowanie):
    """Cała prognoza okna; z bieżącymi to szacunek („~”)."""
    przyblizenie = "~" if podsumowanie["biezace"] else ""
    return f"{przyblizenie}{formatuj_liczba(podsumowanie['razem'], 0)} {symbol_waluty()}"


def liczba_pozycji_osi(podsumowanie):
    """„14 pozycji · 2 zaległe”."""
    tekst = db.liczba_z_odmiana(podsumowanie["liczba"], "pozycja", "pozycje", "pozycji")
    if podsumowanie["zalegle"]:
        tekst += " · " + db.liczba_z_odmiana(podsumowanie["zalegle"], "zaległa", "zaległe", "zaległych")
    return tekst


# ============================================================================
#  KONTROLKI
# ============================================================================

def _kolor_wartosci(kolor):
    """Kolor liczby pogrubionej: wyciszony szary nie idzie w parze z
    pogrubieniem (audyt pogrubień), więc wtedy zwykły kolor tekstu."""
    return None if kolor == KOLOR_STATUS["neutral"] else kolor


def blok_dnia_osi(dzien, kolor, z_miesiacem=False, pusty=False):
    """Kolumna dnia: dzień miesiąca dużą cyfrą, pod nim dzień tygodnia albo —
    wśród zaległych, gdzie miesiące się mieszają — skrót miesiąca. Pozycja bez
    daty dostaje ikonę, a kolejna pozycja tego samego dnia — pustą kolumnę."""
    if pusty:
        return ft.Container(width=SZEROKOSC_DNIA)
    if dzien is None:
        return ft.Container(width=SZEROKOSC_DNIA, alignment=ft.Alignment.CENTER,
                            content=ft.Icon(ft.Icons.EVENT_BUSY, size=18, color=ft.Colors.ON_SURFACE_VARIANT))
    dol = SKROTY_MIESIECY[dzien.month - 1] if z_miesiacem else SKROTY_DNI_TYGODNIA[dzien.weekday()]
    return ft.Container(width=SZEROKOSC_DNIA, content=ft.Column([
        ft.Text(str(dzien.day), size=FS["title"], weight="bold", color=_kolor_wartosci(kolor),
                text_align=ft.TextAlign.CENTER),
        ft.Text(dol, size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER),
    ], spacing=0, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER))


def wiersz_osi(pozycja, j=None, pokaz_dzien=True, z_miesiacem=False):
    """Wiersz osi: kolumna dnia, a obok ikona, nazwa i kwota, pod nimi zdanie
    „kiedy i co” i ewentualny dopisek."""
    kolor = kolor_pozycji_osi(pozycja)
    gora = [
        ft.Icon(ikona_z_mapy(IKONY_OSI, pozycja.get("ikona"), ft.Icons.EVENT), size=16, color=kolor),
        ft.Text(tytul_pozycji_osi(pozycja, j), size=FS["body_strong"], weight="bold", expand=True,
                no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
    ]
    kwota = kwota_osi(pozycja)
    if kwota:
        gora.append(ft.Text(kwota, size=FS["body_strong"], weight="bold", no_wrap=True))
    linie = [ft.Row(gora, spacing=6)]
    opis = opis_pozycji_osi(pozycja, j)
    if opis:
        mowi_kolorem = pozycja.get("status") in STATUSY_Z_KOLOREM
        linie.append(ft.Text(opis, size=FS["caption"],
                             color=kolor if mowi_kolorem else ft.Colors.ON_SURFACE_VARIANT))
    dopisek = dopisek_pozycji_osi(pozycja, j)
    if dopisek:
        linie.append(podpis(dopisek))
    return ft.Row([
        blok_dnia_osi(pozycja.get("data"), kolor, z_miesiacem=z_miesiacem, pusty=not pokaz_dzien),
        ft.Column(linie, spacing=SPACING["xs"], expand=True),
    ], spacing=SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.START)


def wiersz_osi_kafla(pozycja, j=None):
    """Jedna pozycja na kafelku kokpitu: dzień, nazwa i kwota — bez zdania,
    szczegóły są jedno dotknięcie dalej."""
    kolor = kolor_pozycji_osi(pozycja)
    dzien = pozycja.get("data")
    elementy = [
        ft.Text(dzien.strftime("%d.%m") if dzien else "—", size=FS["caption"], color=kolor,
                width=SZEROKOSC_DNIA, no_wrap=True),
        ft.Text(tytul_pozycji_osi(pozycja, j), size=FS["caption"], expand=True,
                no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
    ]
    kwota = kwota_osi(pozycja)
    if kwota:
        elementy.append(ft.Text(kwota, size=FS["caption"], no_wrap=True))
    return ft.Row(elementy, spacing=6)


def pasek_miesiaca_osi(page, miesiac, maks):
    """Pasek długości prognozy miesiąca względem najdroższego w oknie —
    zaplanowane pełnym kolorem, bieżące jaśniej. Przewijając rok widać od razu,
    który miesiąc będzie drogi, bez czytania kwot."""
    if not maks or maks <= 0 or miesiac["razem"] <= 0:
        return None
    zaplanowane = int(round(1000 * miesiac["zaplanowane"] / maks))
    biezace = int(round(1000 * (miesiac["biezace"] or 0.0) / maks))
    reszta = max(0, 1000 - zaplanowane - biezace)
    segmenty = []
    if zaplanowane > 0:
        segmenty.append(ft.Container(expand=zaplanowane, height=6, bgcolor=ft.Colors.PRIMARY))
    if biezace > 0:
        segmenty.append(ft.Container(expand=biezace, height=6,
                                     bgcolor=ft.Colors.with_opacity(0.4, ft.Colors.PRIMARY)))
    if reszta > 0:
        segmenty.append(ft.Container(expand=reszta, height=6))
    if not segmenty:
        return None
    return ft.Container(height=6, border_radius=3, bgcolor=tlo_toru(page),
                        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                        content=ft.Row(segmenty, spacing=0))


def naglowek_grupy_osi(page, tytul, opis="", wartosc="", kolor=None, pasek=None):
    """Nagłówek grupy osi (miesiąc, zaległe, bez daty): nazwa, kwota z prawej,
    pod spodem zdanie i ewentualnie pasek. Stoi na liście, nie w karcie —
    szczebel wyżej niż karty, jak separator miesięcy na długich listach."""
    elementy = [ft.Row([
        ft.Text(tytul, size=FS["label"], weight="bold", color=kolor or ft.Colors.PRIMARY,
                expand=True, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
        ft.Text(wartosc, size=FS["body_strong"], weight="bold", no_wrap=True),
    ], spacing=SPACING["sm"])]
    if opis:
        elementy.append(ft.Text(opis, size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT))
    if pasek is not None:
        elementy.append(pasek)
    return ft.Container(
        padding=ft.Padding(SPACING["md"], SPACING["sm"], SPACING["md"], SPACING["sm"]),
        border_radius=RADIUS["sm"], bgcolor=tlo_karty(page, poziom=2),
        content=ft.Column(elementy, spacing=SPACING["xs"]),
    )


def naglowek_miesiaca_osi(page, miesiac, maks):
    return naglowek_grupy_osi(
        page, nazwa_miesiaca_osi(miesiac), opis_miesiaca_osi(miesiac),
        prognoza_miesiaca_osi(miesiac), pasek=pasek_miesiaca_osi(page, miesiac, maks),
    )


def karta_podsumowania_osi(page, os_dane):
    """Ile przyniesie całe okno: kwota, z czego się składa i ile pozycji.
    Bez żadnej kwoty (same terminy, za mało wpisów na średnią) karta nie
    pokazuje „0 zł” — polisa ma swoją cenę, tylko jeszcze jej nie znamy."""
    p = os_dane["podsumowanie"]
    wiersze = [
        ft.Row([
            ft.Icon(ft.Icons.EVENT_NOTE, size=16, color=ft.Colors.PRIMARY),
            etykieta(opis_okna_osi(os_dane), expand=True),
        ], spacing=6),
    ]
    if p["razem"] > 0:
        wiersze.append(ft.Text(razem_osi(p), size=FS["display"], weight="bold"))
        sklad = sklad_prognozy_osi(p)
        if sklad:
            wiersze.append(podpis(sklad))
    else:
        wiersze.append(podpis(BEZ_KWOT_OSI))
    wiersze.append(ft.Text(
        liczba_pozycji_osi(p), size=FS["caption"],
        color=KOLOR_STATUS["critical"] if p["zalegle"] else ft.Colors.ON_SURFACE_VARIANT,
    ))
    return ft.Container(padding=SPACING["md"], **powierzchnia(page, "karta"),
                        content=ft.Column(wiersze, spacing=SPACING["xs"]))


__all__ = [
    "BEZ_KWOT_OSI",
    "IKONY_OSI",
    "OKRESY_SLOWAMI",
    "SEZONY_PRZYMIOTNIKIEM",
    "SKROTY_DNI_TYGODNIA",
    "SKROTY_MIESIECY",
    "STATUSY_Z_KOLOREM",
    "SZEROKOSC_DNIA",
    "blok_dnia_osi",
    "co_ile_osi",
    "dopisek_pozycji_osi",
    "karta_podsumowania_osi",
    "kiedy_osi",
    "kolor_paska_osi",
    "kolor_pozycji_osi",
    "kwota_osi",
    "liczba_pozycji_osi",
    "naglowek_grupy_osi",
    "naglowek_miesiaca_osi",
    "nazwa_miesiaca_osi",
    "opis_miesiaca_osi",
    "opis_okna_osi",
    "opis_pozycji_osi",
    "pasek_miesiaca_osi",
    "prognoza_miesiaca_osi",
    "razem_osi",
    "sklad_prognozy_osi",
    "tytul_pozycji_osi",
    "wiersz_osi",
    "wiersz_osi_kafla",
]
