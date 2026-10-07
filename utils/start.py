"""Ekran startowy: tablica rejestracyjna zamiast pustego okna (pusta wygląda jak
zawieszona).
1. Tablica pojawia się PRZED otwarciem bazy z nazwą aplikacji; numer wskakuje, gdy baza
wstanie.
2. Ruch robi `ProgressBar` w trybie nieokreślonym — rysuje go Flutter, a pętla Pythona
jest zajęta bazą.
Znika sam: router zaczyna od `page.views.clear()`."""

import flet as ft
import log

from .stale import SPACING
from .pojazd import tablica_rejestracyjna

# Napis na tablicy, dopóki nie wiadomo, czyje to auto.
NAZWA_NA_TABLICY = "FLOTA"

WYSOKOSC_TABLICY = 64

# Wąski pasek pod tablicą. Ma mówić „idzie", a nie „ile zostało" — postępu startu
# nikt tu uczciwie nie policzy, a pasek udający procenty kłamałby.
SZEROKOSC_PASKA = 120


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
        self.widok = ft.View(
            route="/start",
            padding=SPACING["xl"],
            spacing=0,
            vertical_alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Column([
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
    "SZEROKOSC_PASKA",
    "WYSOKOSC_TABLICY",
    "pokaz_ekran_startowy",
]
