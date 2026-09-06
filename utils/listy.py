"""Sortowanie list i przycisk wyboru porządku."""

import flet as ft

from .dialogi import przejdz


def przycisk_sortowania(page: ft.Page, state, klucz_stanu, opcje):
    pole_akt, malejaco_akt = state.sort.setdefault(klucz_stanu, (opcje[0][1], False))
    
    def zmien_pole(pole):
        _, mal = state.sort[klucz_stanu]
        state.sort[klucz_stanu] = (pole, mal)
        przejdz(page, page.route)
        
    def zmien_kierunek(e):
        pole, mal = state.sort[klucz_stanu]
        state.sort[klucz_stanu] = (pole, not mal)
        przejdz(page, page.route)

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

    popup = ft.PopupMenuButton(
        items=elementy_menu,
        content=ft.Row([
            ft.Icon(ft.Icons.SORT_ROUNDED, size=14, color=ft.Colors.PRIMARY),  # Mniejsza ikona
            ft.Text(etykieta_akt, size=11, weight="bold", color=ft.Colors.PRIMARY),  # Mniejszy tekst
        ], spacing=2),
        tooltip="Wybierz pole sortowania"
    )

    return ft.Container(
        height=36,  # <-- SZTYWNA WYSOKOŚĆ
        bgcolor=ft.Colors.with_opacity(0.1, ft.Colors.PRIMARY),
        border_radius=18,
        padding=ft.Padding(12, 0, 12, 0),
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
                width=24,
                height=24,
                style=ft.ButtonStyle(padding=0)
            )
        ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    )


def posortuj_liste(lista, state, klucz_stanu, opcje):
    pole_akt, malejaco = state.sort.get(klucz_stanu, (opcje[0][1], False))
    for _, pole, fn in opcje:
        if pole == pole_akt:
            lista.sort(key=fn, reverse=malejaco)
            break
    return lista


__all__ = [
    "posortuj_liste",
    "przycisk_sortowania",
]
