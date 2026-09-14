"""Ekran startowy: tablica rejestracyjna zamiast pustego okna.

Między uruchomieniem a pierwszym ekranem aplikacja otwiera bazę, przepuszcza
migracje i buduje widok. Do tej pory było w tym czasie puste okno — a puste okno
i zawieszona aplikacja wyglądają identycznie (ta sama obserwacja, co przy
szkieletach, patrz utils.szkielet).

Na ekranie startowym stoi `tablica_rejestracyjna()`: niebieski pasek UE, czarny
tekst na białym. To najbardziej charakterystyczny element całej aplikacji i to
samo, po czym rozpoznaje się auto na parkingu — więc ustawia ton reszty, zamiast
być logiem doklejonym na wierzchu.

Dwie decyzje, które warto znać:

1. **Tablica pojawia się PRZED otwarciem bazy**, więc najpierw nosi nazwę
   aplikacji. Gdy baza wstanie, numer wskakuje na jej miejsce. Odwrotna
   kolejność (czekać na numer) oznaczałaby, że najdłuższy kawałek startu —
   migracje — znowu odbywa się przy pustym oknie.
2. **Ruch robi `ProgressBar` w trybie nieokreślonym.** W chwili, gdy ekran
   startowy jest na wyświetlaczu, pętla zdarzeń jest zajęta otwieraniem bazy
   i żadna animacja sterowana z Pythona nie miałaby kiedy pojechać. Pasek
   nieokreślony rysuje Flutter po swojej stronie i nic go nie zatrzyma.

Ekran startowy znika sam: router zaczyna od `page.views.clear()`, więc pierwsza
nawigacja zdejmuje go razem z resztą stosu.
"""

import flet as ft
import log

from .stale import FS, RADIUS, SPACING
from .pojazd import tablica_rejestracyjna

# Napis na tablicy, dopóki nie wiadomo, czyje to auto.
NAZWA_NA_TABLICY = "FLOTA"

WYSOKOSC_TABLICY = 64

# Wąski pasek pod tablicą. Ma mówić „idzie", a nie „ile zostało" — postępu startu
# nikt tu uczciwie nie policzy, a pasek udający procenty kłamałby.
SZEROKOSC_PASKA = 120


class EkranStartowy:
    """Widok startowy i uchwyt do jego tablicy.

    Klasa, a nie sama funkcja, bo tablicę trzeba móc PODMIENIĆ po otwarciu bazy,
    a `ft.View` nie ma pola, w którym dałoby się ją trzymać (dopisanie własnego
    atrybutu do kontrolki Fleta przechodzi bez błędu i nic nie robi — patrz
    audyt pól kontrolek w tests/audyty.py)."""

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
