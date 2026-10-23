"""Ekran startowy: logo i tablica rejestracyjna zamiast pustego okna (pusta wygląda jak
zawieszona).
1. Logo i tablica pojawiają się PRZED otwarciem bazy, tablica z nazwą aplikacji; numer
wskakuje, gdy baza wstanie. Logo stoi na środku ekranu, jak chwilę wcześniej na
ekranie powitalnym Androida.
2. Ruch robi `ProgressBar` w trybie nieokreślonym — rysuje go Flutter, a pętla Pythona
jest zajęta bazą.
Znika sam: router zaczyna od `page.views.clear()`."""

import flet as ft

import db
import log

from .stale import RADIUS, SPACING
from .pojazd import tablica_rejestracyjna

# Napis na tablicy, dopóki nie wiadomo, czyje to auto.
NAZWA_NA_TABLICY = db.NAZWA_APLIKACJI

WYSOKOSC_TABLICY = 64

# Wąski pasek pod tablicą. Ma mówić „idzie", a nie „ile zostało" — postępu startu
# nikt tu uczciwie nie policzy, a pasek udający procenty kłamałby.
SZEROKOSC_PASKA = 120

# Rysunek auta z assets/ (przezroczyste tło). Na starcie w białym kole wielkości tego
# z ekranu powitalnego Androida w ciemnym motywie (assets/splash_dark.png).
PLIK_LOGO = "logo.png"
SREDNICA_LOGO_STARTU = 172
SZEROKOSC_LOGO_STARTU = 140


def logo_aplikacji(szerokosc=120, srednica_kola=None):
    """Auto z logo na białym tle: w kole (`srednica_kola`) albo w zaokrąglonej plakietce.
    Białe zawsze — w ciemnym motywie czarny dach i obrys zlałyby się z tłem."""
    obraz = ft.Image(src=PLIK_LOGO, width=szerokosc, fit=ft.BoxFit.CONTAIN,
                     semantics_label=f"Logo {db.NAZWA_APLIKACJI}")
    if srednica_kola:
        return ft.Container(content=obraz, width=srednica_kola, height=srednica_kola,
                            shape=ft.BoxShape.CIRCLE, bgcolor=ft.Colors.WHITE,
                            alignment=ft.Alignment.CENTER)
    return ft.Container(content=obraz, bgcolor=ft.Colors.WHITE, border_radius=RADIUS["md"],
                        padding=ft.Padding.symmetric(horizontal=SPACING["sm"], vertical=SPACING["xs"]))


class EkranStartowy:
    """Widok startowy z uchwytem do tablicy (podmienianej po otwarciu bazy). Klasa, bo
    `ft.View` nie ma pola na tablicę, a własny atrybut kontrolki Fleta nic nie robi
    (audyt pól w tests/audyty.py)."""

    def __init__(self, page: ft.Page = None, numer=None):
        self._page = page
        self.numer = str(numer or "").strip()
        self.ramka = ft.Container(
            content=tablica_rejestracyjna(self.numer or NAZWA_NA_TABLICY,
                                          wysokosc=WYSOKOSC_TABLICY),
        )
        # Nad logo tyle miejsca, ile zajmuje to pod nim (odstęp, tablica, odstęp, pasek
        # 3 px) — środek logo wypada na środku ekranu.
        nad_logo = 2 * SPACING["lg"] + WYSOKOSC_TABLICY + 3
        self.widok = ft.View(
            route="/start",
            padding=SPACING["xl"],
            spacing=0,
            vertical_alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Column([
                    ft.Container(height=nad_logo),
                    logo_aplikacji(SZEROKOSC_LOGO_STARTU, srednica_kola=SREDNICA_LOGO_STARTU),
                    ft.Container(height=SPACING["lg"]),
                    self.ramka,
                    ft.Container(height=SPACING["lg"]),
                    ft.ProgressBar(
                        value=None, width=SZEROKOSC_PASKA, height=3, border_radius=2,
                        color=ft.Colors.PRIMARY,
                        bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
                    ),
                ], spacing=0, tight=True,
                   horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            ],
        )

    def ustaw_numer(self, numer):
        """Podmienia napis na prawdziwy numer rejestracyjny.

        Pusty numer zostawia nazwę aplikacji: pojazd bez rejestracji (albo pusty
        garaż) nie ma czego pokazać, a tablica z niczym w środku wyglądałaby na
        usterkę."""
        numer = str(numer or "").strip()
        if not numer or numer == self.numer:
            return False
        self.numer = numer
        self.ramka.content = tablica_rejestracyjna(numer, wysokosc=WYSOKOSC_TABLICY)
        try:
            self.ramka.update()
        except Exception:
            log.polkniety("podmiana numeru na ekranie startowym")
        return True


def pokaz_ekran_startowy(page: ft.Page, numer=None):
    """Wstawia ekran startowy na stos i WYPYCHA go na wyświetlacz.

    `page.update()` jest tu istotą rzeczy, a nie formalnością: bez niego widok
    zostałby po stronie Pythona i pokazał się dopiero razem z pierwszym ekranem,
    czyli już po tym, jak przestał być potrzebny."""
    ekran = EkranStartowy(page, numer)
    try:
        page.views.append(ekran.widok)
        page.update()
    except Exception:
        log.polkniety("pokazanie ekranu startowego")
    return ekran


__all__ = [
    "EkranStartowy",
    "NAZWA_NA_TABLICY",
    "PLIK_LOGO",
    "SREDNICA_LOGO_STARTU",
    "SZEROKOSC_LOGO_STARTU",
    "SZEROKOSC_PASKA",
    "WYSOKOSC_TABLICY",
    "logo_aplikacji",
    "pokaz_ekran_startowy",
]
