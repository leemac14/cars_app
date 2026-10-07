"""Szkielet ekranu: zarys kart, zanim powstanie treść (pustka wygląda jak awaria).
1. Ruch nie zależy od Pythona: klocki to `ProgressBar` NIEOKREŚLONY (pętla jest zajęta
budową treści).
2. Szkielet znika sam: `zbuduj_etapami` oddaje sterowanie na moment i podmienia go na
treść."""

import asyncio
import flet as ft
import log

from .animacje import _petla_dziala
from .stale import RADIUS, SPACING
from .wyglad import tlo_karty

# Tyle czekamy, zanim zaczniemy budować treść. Ekran musi w tym czasie zdążyć
# trafić do drzewa strony i zostać narysowany — inaczej szkielet i treść poszłyby
# jednym patchem i cała rzecz nie miałaby sensu.
OPOZNIENIE_SZKIELETU_S = 0.05

# Widok pod spodem (ekran główny pod otwartym Rokiem w pigułce) ustępuje
# pierwszeństwa temu, który użytkownik faktycznie ogląda: gdyby zaczął liczyć
# pierwszy, zablokowałby pętlę i wierzchni ekran czekałby na niewidoczny.
OPOZNIENIE_POD_SPODEM_S = 0.25


def _kolory(page):
    return (
        ft.Colors.with_opacity(0.10, ft.Colors.ON_SURFACE),   # tło klocka
        ft.Colors.with_opacity(0.20, ft.Colors.ON_SURFACE),   # przesuwający się błysk
    )


def szkielet_linia(page=None, szerokosc=None, wysokosc=12, expand=None):
    """Jedna „linijka tekstu" szkieletu.

    Nieokreślony `ProgressBar` zamiast zwykłego prostokąta jest tu celowy: to
    jedyny sposób na ruch, którego nie zatrzyma zajęty Python (patrz nagłówek
    modułu)."""
    tlo, blysk = _kolory(page)
    return ft.ProgressBar(
        value=None, height=wysokosc, width=szerokosc, expand=expand,
        color=blysk, bgcolor=tlo, border_radius=max(3, wysokosc // 2),
    )


def szkielet_karta(page=None, linie=2, wysokosc_linii=12, szerokosci=(None, 0.6)):
    """Zarys jednej karty: powierzchnia i kilka linijek w środku.

    `szerokosci` to udziały szerokości kolejnych linii (None = cała szerokość).
    Różna długość linii sprawia, że zarys czyta się jak tekst, a nie jak tabela
    pustych prostokątów."""
    wiersze = []
    for i in range(linie):
        udzial = szerokosci[i] if i < len(szerokosci) else 0.5
        if udzial is None:
            wiersze.append(szkielet_linia(page, wysokosc=wysokosc_linii))
        else:
            wiersze.append(ft.Row([
                szkielet_linia(page, wysokosc=wysokosc_linii, expand=max(1, int(udzial * 100))),
                ft.Container(expand=max(1, int((1 - udzial) * 100))),
            ], spacing=0))
    return ft.Container(
        padding=SPACING["md"], border_radius=RADIUS["lg"],
        bgcolor=tlo_karty(page, poziom=1),
        content=ft.Column(wiersze, spacing=SPACING["sm"]),
    )


def szkielet_listy(page=None, ile=3, linie=2):
    """Zarys listy kart — dla ekranów, które rysują wpisy jeden pod drugim."""
    return ft.Column(
        [szkielet_karta(page, linie=linie) for _ in range(ile)],
        spacing=SPACING["md"],
    )


def szkielet_kafli(page=None, ile=4, wysokosc=76, kolumny=2):
    """Zarys siatki kafli — dla kokpitu i podsumowań liczbowych."""
    kafel = lambda: ft.Container(
        padding=SPACING["md"], border_radius=RADIUS["lg"],
        bgcolor=tlo_karty(page, poziom=1), height=wysokosc,
        col={"xs": 12 // max(1, kolumny)},
        content=ft.Column([
            szkielet_linia(page, wysokosc=10),
            szkielet_linia(page, wysokosc=16),
        ], spacing=SPACING["sm"]),
    )
    return ft.ResponsiveRow([kafel() for _ in range(ile)], spacing=10, run_spacing=10)


def szkielet_wykresu(page=None, wysokosc=180):
    """Zarys wykresu: jedna duża powierzchnia i pasek podpisów pod nią."""
    return ft.Container(
        padding=SPACING["md"], border_radius=RADIUS["lg"],
        bgcolor=tlo_karty(page, poziom=1),
        content=ft.Column([
            szkielet_linia(page, wysokosc=12, expand=None),
            szkielet_linia(page, wysokosc=wysokosc),
            ft.Row([szkielet_linia(page, wysokosc=8, expand=1) for _ in range(4)], spacing=8),
        ], spacing=SPACING["sm"]),
    )


def szkielet_ekranu(page=None, kafle=0, wykres=False, karty=3, linie=2):
    """Gotowy zarys całego ekranu, składany z klocków w kolejności, w jakiej
    ekrany zwykle się układają: kafle na górze, wykres w środku, lista pod nim."""
    elementy = []
    if kafle:
        elementy.append(szkielet_kafli(page, ile=kafle))
    if wykres:
        elementy.append(szkielet_wykresu(page))
    if karty:
        elementy.append(szkielet_listy(page, ile=karty, linie=linie))
    return ft.Column(elementy, spacing=SPACING["md"])


def _pod_spodem(page, widok):
    """Czy widok jest w stosie, ale NIE na wierzchu (ekran główny pod innym) — wtedy
    ustępuje pierwszeństwa. Widok spoza stosu (budowa bez okna) nie jest „pod spodem”."""
    if widok is None:
        return False
    try:
        widoki = page.views
        # TOŻSAMOŚĆ, nie równość: kontrolki Fleta to dataclassy z wygenerowanym
        # `__eq__`, więc `in` uznałby dwa świeżo zbudowane, jeszcze puste widoki
        # za ten sam obiekt.
        return bool(widoki) and any(w is widok for w in widoki) and widoki[-1] is not widok
    except Exception:
        return False


def zbuduj_etapami(page, szkielet, zbuduj_tresc, widok=None, po_zbudowaniu=None):
    """Kontener: najpierw `szkielet`, treść chwilę później. `zbuduj_tresc()` woła się
    DOKŁADNIE RAZ i zwraca kontrolkę; `po_zbudowaniu()` (opcjonalne) poprawia to, co
    zależy od treści. Bez pętli zdarzeń (testy) treść powstaje od razu."""
    kontener = ft.Container(content=szkielet)

    def _wstaw_tresc():
        try:
            kontener.content = zbuduj_tresc()
        except Exception:
            # Treść się nie zbudowała — zostawiamy szkielet zamiast pustki, bo
            # pusty ekran wygląda tak samo jak ten sprzed sekundy.
            log.polkniety("budowa treści ekranu po szkielecie")
            return
        if po_zbudowaniu is not None:
            try:
                po_zbudowaniu()
            except Exception:
                log.polkniety("dokończenie ekranu po zbudowaniu treści")

    if not _petla_dziala(page):
        _wstaw_tresc()
        return kontener

    async def _dobuduj():
        await asyncio.sleep(OPOZNIENIE_SZKIELETU_S)
        if _pod_spodem(page, widok):
            await asyncio.sleep(OPOZNIENIE_POD_SPODEM_S)
        _wstaw_tresc()
        try:
            kontener.update()
        except Exception:
            log.polkniety("podmiana szkieletu na treść")

    try:
        page.run_task(_dobuduj)
    except Exception:
        _wstaw_tresc()
    return kontener


__all__ = [
    "OPOZNIENIE_POD_SPODEM_S",
    "OPOZNIENIE_SZKIELETU_S",
    "szkielet_ekranu",
    "szkielet_kafli",
    "szkielet_karta",
    "szkielet_linia",
    "szkielet_listy",
    "szkielet_wykresu",
    "zbuduj_etapami",
]
