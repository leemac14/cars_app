"""Dolewki płynów w interfejsie (N-12): stan zużycia (KOLOR_STATUS), chip płynu, linijka na karcie
podzespołu, karta podsumowania i słupki okresów. Liczy db/dolewki.py."""

from datetime import datetime

import flet as ft

import db
from date import parsuj_date

from .stale import FS, IKONY_PLYNOW, KOLOR_STATUS, KOLORY_PLYNOW, RADIUS, SPACING
from .format import formatuj_dystans
from .typografia import KOLOR_DRUGIEGO_PLANU, etykieta, podpis, wartosc
from .wyglad import pasek_przewijany, powierzchnia

ROLE_STATUSU = {db.STATUS_NORMA: "ok", db.STATUS_PODWYZSZONE: "warning", db.STATUS_WYSOKIE: "critical"}
ETYKIETY_STATUSU = {db.STATUS_NORMA: "W normie", db.STATUS_PODWYZSZONE: "Podwyższone", db.STATUS_WYSOKIE: "Wysokie"}
WYSOKOSC_SLUPKA_ZUZYCIA = 90
MAKS_SLUPKOW = 8


def stan_zuzycia(z) -> tuple[str | None, str | None]:
    """(etykieta, rola z KOLOR_STATUS) — albo (None, None), gdy płyn nie ma oceny albo pomiaru."""
    if not z:
        return None, None
    if z.get("ubytek"):
        return "Ubywa", "warning"
    if z.get("rosnie"):
        return "Rośnie", "critical" if z.get("status") == db.STATUS_WYSOKIE else "warning"
    status = z.get("status")
    return (ETYKIETY_STATUSU[status], ROLE_STATUSU[status]) if status else (None, None)


def kolor_zuzycia(z, domyslny=ft.Colors.PRIMARY):
    _tekst, rola = stan_zuzycia(z)
    return KOLOR_STATUS[rola] if rola else domyslny


def chip_stanu_zuzycia(z):
    tekst, rola = stan_zuzycia(z)
    if not tekst:
        return None
    kolor = KOLOR_STATUS[rola]
    return ft.Container(
        padding=ft.Padding(8, 2, 10, 2), border_radius=RADIUS["pill"], bgcolor=ft.Colors.with_opacity(0.12, kolor),
        content=ft.Text(tekst, size=FS["caption"], weight="bold", color=kolor, no_wrap=True),
    )


def chip_plynu(plyn, aktywny, on_click, liczba=None):
    """Chip wyboru płynu nad listą — ikona w kolorze płynu, liczba dolewek."""
    tekst = db.nazwa_plynu(plyn) + (f" ({liczba})" if liczba else "")
    return ft.Container(
        height=30, padding=ft.Padding(10, 0, 12, 0), border_radius=RADIUS["pill"], ink=True,
        bgcolor=ft.Colors.PRIMARY if aktywny else ft.Colors.TRANSPARENT,
        border=None if aktywny else ft.Border.all(1, ft.Colors.OUTLINE),
        on_click=on_click,
        content=ft.Row([
            ft.Icon(IKONY_PLYNOW.get(plyn, ft.Icons.WATER_DROP), size=15,
                    color=ft.Colors.ON_PRIMARY if aktywny else KOLORY_PLYNOW.get(plyn)),
            ft.Text(tekst, size=FS["caption"], weight="bold" if aktywny else "normal", no_wrap=True,
                    color=ft.Colors.ON_PRIMARY if aktywny else ft.Colors.ON_SURFACE_VARIANT),
        ], spacing=4, tight=True),
    )


def pasek_plynow(plyny, aktualny, wybierz, liczby=None, page=None):
    return pasek_przewijany([chip_plynu(p, p == aktualny, lambda e, p=p: wybierz(p), (liczby or {}).get(p))
                             for p in plyny], spacing=8, page=page)


def zdanie_okresu(okres, j=None) -> str:
    """„Od wymiany 12.03.2026 (145 300 km)” i w drugiej linii „dolano 0,8 l na 4 200 km”."""
    poczatek = "Od pierwszej dolewki" if okres["od_dolewki"] else "Od wymiany"
    data = f" {okres['od_data']}" if okres["od_data"] else ""
    return f"{poczatek}{data} ({formatuj_dystans(okres['od_przebieg'], 0, j)})\n{db.opis_okresu(okres, j)}"


def tekst_liczby_zuzycia(z, j=None) -> str:
    if z.get("na_1000") is not None:
        return db.tekst_zuzycia(z["na_1000"], j)
    return f"Za mało {db.slowo_dystansu('dopelniacz_pelny', j)}" if z.get("liczba") else "Brak dolewek"


def wiersz_zuzycia_podzespolu(z, j=None):
    """Linijka pod podzespołem wymiany w Serwisie: ile dolano od wymiany i zużycie — albo None."""
    okres = z.get("biezacy")
    if not okres:
        return None
    tekst = f"Od wymiany {db.opis_okresu(okres, j)}"
    if okres["na_1000"] is not None:
        tekst += f" · {db.tekst_zuzycia(okres['na_1000'], j)}"
    kolor = kolor_zuzycia(z, KOLOR_DRUGIEGO_PLANU)
    return ft.Row([
        ft.Icon(IKONY_PLYNOW.get(z["plyn"], ft.Icons.WATER_DROP), size=15, color=kolor),
        ft.Text(tekst, size=FS["body"], color=kolor, expand=True),
    ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)


def wykres_okresow(z, j=None):
    """Słupki zużycia kolejnych okresów (od najstarszego, najwyżej MAKS_SLUPKOW) — None poniżej dwóch."""
    okresy = [o for o in z["okresy"] if o["na_1000"] is not None][-MAKS_SLUPKOW:]
    if len(okresy) < 2:
        return None
    oleju = z["ocena"] == db.OCENA_OLEJU
    skala = max([o["na_1000"] for o in okresy] + [db.PROG_ZUZYCIA_PODWYZSZONEGO if oleju else 0.01])
    kolumny = []
    for o in okresy:
        kolor = (KOLOR_STATUS[ROLE_STATUSU[db.status_zuzycia(o["na_1000"])]] if oleju
                 else KOLORY_PLYNOW.get(z["plyn"], ft.Colors.PRIMARY))
        wartosc_txt = db.tekst_zuzycia(o["na_1000"], j).split(" ")[0]
        poczatek = parsuj_date(o["od_data"])
        podpis_txt = poczatek.strftime("%m.%y") if poczatek != datetime.min.date() else ""
        kolumny.append(ft.Column([
            ft.Text(wartosc_txt, size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Container(width=26, height=max(4, int(o["na_1000"] / skala * WYSOKOSC_SLUPKA_ZUZYCIA)), bgcolor=kolor,
                         border_radius=4, tooltip=zdanie_okresu(o, j)),
            ft.Text(podpis_txt + ("\nteraz" if o["trwa"] else ""), size=FS["caption"],
                    color=ft.Colors.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER),
        ], alignment=ft.MainAxisAlignment.END, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4))
    return ft.Column([
        etykieta(f"Zużycie w kolejnych okresach (l/1000 {db.slowo_dystansu('skrot', j)})"),
        ft.Row(kolumny, alignment=ft.MainAxisAlignment.SPACE_EVENLY, vertical_alignment=ft.CrossAxisAlignment.END),
    ], spacing=8)


def karta_zuzycia(page: ft.Page, z, j=None):
    """Karta płynu nad listą: zużycie, stan, bieżący okres, porównanie z wcześniejszymi i skąd wymiany."""
    kolor = kolor_zuzycia(z)
    naglowek = [ft.Icon(IKONY_PLYNOW.get(z["plyn"], ft.Icons.WATER_DROP), size=20, color=KOLORY_PLYNOW.get(z["plyn"])),
                wartosc(z["nazwa"], expand=True)]
    chip = chip_stanu_zuzycia(z)
    if chip:
        naglowek.append(chip)
    wiersze = [ft.Row(naglowek, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)]
    zrodlo = ("w bieżącym okresie" if z["z_biezacego"] else "w poprzednim okresie") if z["na_1000"] is not None else \
        "pomiar ruszy po kolejnej dolewce"
    wiersze.append(ft.Row([
        ft.Text(tekst_liczby_zuzycia(z, j), size=FS["display"], weight="bold", color=kolor),
        podpis(zrodlo, expand=True),
    ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER))
    if z["biezacy"]:
        wiersze.append(podpis(zdanie_okresu(z["biezacy"], j)))
    if z["poprzednio"] is not None:
        wiersze.append(podpis(f"Wcześniejsze okresy: {db.tekst_zuzycia(z['poprzednio'], j)}"))
    if z["ubytek"]:
        wiersze.append(podpis(f"{db.liczba_z_odmiana(z['dolewek_w_roku'], 'dolewka', 'dolewki', 'dolewek')} w ostatnim "
                              "roku — w zamkniętym układzie nie powinno go ubywać.", color=KOLOR_STATUS["warning"]))
    if db.RODZAJE_PLYNOW[z["plyn"]].get("wymiana"):
        wiersze.append(podpis(f"Wymiany: {', '.join(z['zadania'])}" if z["zadania"] else
                              "Brak podzespołu z wymianą tego płynu — okres liczy się od pierwszej dolewki."))
    wykres = wykres_okresow(z, j)
    if wykres is not None:
        wiersze.append(wykres)
    return ft.Container(padding=SPACING["lg"], **powierzchnia(page, "karta", cien="md"),
                        content=ft.Column(wiersze, spacing=8))


__all__ = [
    "ETYKIETY_STATUSU",
    "MAKS_SLUPKOW",
    "ROLE_STATUSU",
    "WYSOKOSC_SLUPKA_ZUZYCIA",
    "chip_plynu",
    "chip_stanu_zuzycia",
    "karta_zuzycia",
    "kolor_zuzycia",
    "pasek_plynow",
    "stan_zuzycia",
    "tekst_liczby_zuzycia",
    "wiersz_zuzycia_podzespolu",
    "wykres_okresow",
    "zdanie_okresu",
]
