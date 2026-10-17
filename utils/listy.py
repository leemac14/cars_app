"""Sortowanie list, przycisk wyboru porządku i gesty na kartach."""

import flet as ft

from .stale import KOLOR_STATUS, RADIUS, SPACING
from .haptyka import wibracja
from .dialogi import odswiez_ekran


def _tlo_gestu(ikona, napis, tlo, kolor, z_prawej):
    """Tło odsłaniane pod przesuwaną kartą: ikona i napis od strony, od której karta odjeżdża."""
    tresc = [ft.Icon(ikona, color=kolor), ft.Text(napis, color=kolor, weight=ft.FontWeight.W_500)]
    return ft.Container(
        bgcolor=tlo, border_radius=RADIUS["lg"], padding=ft.Padding(SPACING["lg"], 0, SPACING["lg"], 0),
        content=ft.Row(tresc[::-1] if z_prawej else tresc, spacing=SPACING["sm"],
                       alignment=ft.MainAxisAlignment.END if z_prawej else ft.MainAxisAlignment.START,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
    )


def _kierunek(e):
    kierunek = getattr(e, "direction", None)
    return getattr(kierunek, "value", kierunek)


def gesty_karty(page: ft.Page, karta, usun=None, notatka=None, widok=None):
    """Karta listy z gestami (W-07): w lewo — usuń (bez pytania, ratunkiem jest „Cofnij”), w prawo —
    notatka. `usun`/`notatka` to akcje bez argumentów, None wyłącza gest (rola bez prawa zmian).
    W trybie zaznaczania (`widok.tryb_zaznaczania`) karta odbija bez akcji."""
    if not usun and not notatka:
        return karta
    tlo_usun = _tlo_gestu(ft.Icons.DELETE_OUTLINE, "Usuń", KOLOR_STATUS["destructive"], ft.Colors.WHITE, True)
    tlo_notatki = _tlo_gestu(ft.Icons.EDIT_NOTE, "Notatka", ft.Colors.PRIMARY, ft.Colors.ON_PRIMARY, False)
    if usun and notatka:
        kierunek, tlo, tlo_drugie = ft.DismissDirection.HORIZONTAL, tlo_notatki, tlo_usun
    elif usun:
        kierunek, tlo, tlo_drugie = ft.DismissDirection.END_TO_START, tlo_usun, None
    else:
        kierunek, tlo, tlo_drugie = ft.DismissDirection.START_TO_END, tlo_notatki, None

    async def _potwierdz(e):
        if getattr(widok, "tryb_zaznaczania", False):
            await e.control.confirm_dismiss(False)
        elif _kierunek(e) == ft.DismissDirection.END_TO_START.value:
            await e.control.confirm_dismiss(True)     # karta odjeżdża, usuwa `on_dismiss`
        else:
            await e.control.confirm_dismiss(False)    # notatka nie zabiera karty z listy
            wibracja(page, "wybor")
            notatka()

    return ft.Dismissible(
        content=karta, dismiss_direction=kierunek, background=tlo, secondary_background=tlo_drugie,
        dismiss_thresholds={ft.DismissDirection.END_TO_START: 0.4, ft.DismissDirection.START_TO_END: 0.25},
        on_confirm_dismiss=_potwierdz,
        on_dismiss=(lambda e: usun()) if usun else None,
    )


WYSOKOSC_PIGULKI_SORTOWANIA = 40


def przycisk_sortowania(page: ft.Page, state, klucz_stanu, opcje):
    pole_akt, malejaco_akt = state.sort.setdefault(klucz_stanu, (opcje[0][1], False))
    
    def zmien_pole(pole):
        _, mal = state.sort[klucz_stanu]
        state.sort[klucz_stanu] = (pole, mal)
        odswiez_ekran(page)
        
    def zmien_kierunek(e):
        pole, mal = state.sort[klucz_stanu]
        state.sort[klucz_stanu] = (pole, not mal)
        odswiez_ekran(page)

    etykieta_akt = next((et for et, p, _ in opcje if p == pole_akt), str(pole_akt))

    elementy_menu = []
    for etykieta, pole, _ in opcje:
        zaznaczone = (pole == pole_akt)
        elementy_menu.append(
            ft.PopupMenuItem(
                content=ft.Row([
                    ft.Icon(ft.Icons.CHECK, size=16, color=ft.Colors.PRIMARY, visible=zaznaczone),
                    ft.Text(etykieta, weight="bold" if zaznaczone else "normal")
                ]),
                on_click=lambda e, p=pole: zmien_pole(p)
            )
        )

    # Cel dotyku 40 dp na obu częściach pigułki (W-19): pole sortowania i strzałka.
    popup = ft.PopupMenuButton(
        items=elementy_menu,
        content=ft.Container(height=WYSOKOSC_PIGULKI_SORTOWANIA, content=ft.Row([
            ft.Icon(ft.Icons.SORT_ROUNDED, size=14, color=ft.Colors.PRIMARY),
            ft.Text(etykieta_akt, size=11, weight="bold", color=ft.Colors.PRIMARY),
        ], spacing=2, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER)),
        tooltip="Wybierz pole sortowania"
    )

    return ft.Container(
        height=WYSOKOSC_PIGULKI_SORTOWANIA,
        bgcolor=ft.Colors.with_opacity(0.1, ft.Colors.PRIMARY),
        border_radius=WYSOKOSC_PIGULKI_SORTOWANIA / 2,
        padding=ft.Padding(12, 0, 0, 0),
        alignment=ft.Alignment.CENTER,
        content=ft.Row([
            popup,
            ft.Container(width=1, height=16, bgcolor=ft.Colors.with_opacity(0.2, ft.Colors.PRIMARY)),
            ft.IconButton(
                icon=ft.Icons.ARROW_DOWNWARD_ROUNDED if malejaco_akt else ft.Icons.ARROW_UPWARD_ROUNDED,
                icon_size=16,
                icon_color=ft.Colors.PRIMARY,
                tooltip="Zmień kierunek sortowania",
                on_click=zmien_kierunek,
                width=WYSOKOSC_PIGULKI_SORTOWANIA,
                height=WYSOKOSC_PIGULKI_SORTOWANIA,
                style=ft.ButtonStyle(padding=0)
            )
        ], spacing=2, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    )


def posortuj_liste(lista, state, klucz_stanu, opcje):
    pole_akt, malejaco = state.sort.get(klucz_stanu, (opcje[0][1], False))
    for _, pole, fn in opcje:
        if pole == pole_akt:
            lista.sort(key=fn, reverse=malejaco)
            break
    return lista


__all__ = [
    "WYSOKOSC_PIGULKI_SORTOWANIA",
    "gesty_karty",
    "posortuj_liste",
    "przycisk_sortowania",
]
