"""Filtry list: rok, miesiąc, kategoria i autor wpisu."""

import db
import flet as ft
from date import parsuj_date
from datetime import datetime
from state import MIESIACE_NAZWY

from .dialogi import przejdz


def _zbuduj_popup_filtra(page: ft.Page, state, klucz_stanu, opcje, etykieta, ikona_aktywna, ikona_nieaktywna):
    """Generyczna metoda budująca przycisk filtra z menu rozwijanym."""
    aktualny_filtr = state.filtry.setdefault(klucz_stanu, "Wszystko")
    if aktualny_filtr not in opcje:
        aktualny_filtr = "Wszystko"
        state.filtry[klucz_stanu] = aktualny_filtr

    def zmien_filtr(wartosc):
        state.filtry[klucz_stanu] = wartosc
        przejdz(page, page.route)

    elementy_menu = []
    for o in opcje:
        zaznaczone = (o == aktualny_filtr)
        elementy_menu.append(
            ft.PopupMenuItem(
                content=ft.Row([
                    ft.Icon(ft.Icons.CHECK, size=16, color=ft.Colors.PRIMARY, visible=zaznaczone),
                    ft.Text(o, weight="bold" if zaznaczone else "normal")
                ]),
                on_click=lambda e, val=o: zmien_filtr(val)
            )
        )

    jest_aktywny = (aktualny_filtr != "Wszystko")
    kolor_glowny = ft.Colors.PRIMARY if jest_aktywny else ft.Colors.ON_SURFACE_VARIANT
    kolor_tla = ft.Colors.with_opacity(0.15, ft.Colors.PRIMARY) if jest_aktywny else ft.Colors.with_opacity(0.06, ft.Colors.ON_SURFACE)

    pokazywany_tekst = aktualny_filtr if jest_aktywny else etykieta
    if len(pokazywany_tekst) > 9:
        pokazywany_tekst = pokazywany_tekst[:7] + ".."

    # tight=True jest tu KONIECZNE. Bez niego wiersz ma mainAxisSize.max i bierze
    # całą szerokość, jaką dostanie. W pasku przewijanym poziomo szerokość była
    # nieograniczona, więc chip i tak kurczył się do treści — ale w pasku
    # ZAWIJANYM dostaje szerokość ekranu i każdy filtr ląduje w osobnej linijce.
    popup = ft.PopupMenuButton(
        items=elementy_menu,
        content=ft.Row([
            ft.Icon(ikona_aktywna if jest_aktywny else ikona_nieaktywna, size=13, color=kolor_glowny),
            ft.Text(pokazywany_tekst, size=11, weight="bold", color=kolor_glowny),
        ], spacing=2, tight=True),
        tooltip=f"Filtruj po: {etykieta}"
    )

    return ft.Container(
        height=36,  # <-- SZTYWNA WYSOKOŚĆ
        bgcolor=kolor_tla, 
        border_radius=18, 
        padding=ft.Padding(12, 0, 12, 0),
        alignment=ft.Alignment.CENTER,
        content=popup
    )


def przycisk_filtrowania_rok(page: ft.Page, state, klucz_stanu, lista_danych, index_daty):
    lata = set()
    for w in lista_danych:
        try:
            data_str = w[index_daty]
            d = parsuj_date(data_str)
            if d != datetime.min.date():
                lata.add(str(d.year))
        except Exception:
            pass
    
    opcje = ["Wszystko"] + sorted(list(lata), reverse=True)
    return _zbuduj_popup_filtra(
        page, state, klucz_stanu, opcje, "Rok",
        ft.Icons.FILTER_ALT_ROUNDED, ft.Icons.FILTER_ALT_OUTLINED
    )


def przycisk_filtrowania_kategoria(page: ft.Page, state, klucz_stanu, lista_danych, index_pola, etykieta="Tagi"):
    wartosci = set()
    for w in lista_danych:
        try:
            wartosc = str(w[index_pola] or "").strip()
            if wartosc and wartosc != "None":
                for tag in wartosc.split(","):
                    if tag.strip(): wartosci.add(tag.strip())
        except Exception:
            pass
    
    opcje = ["Wszystko"] + sorted(list(wartosci))
    return _zbuduj_popup_filtra(
        page, state, klucz_stanu, opcje, etykieta,
        ft.Icons.LABEL_ROUNDED, ft.Icons.LABEL_OUTLINE
    )


# Filtr autorstwa przy pojazdach współdzielonych: „kto to dodał”. Wpisy sprzed
# wprowadzenia kolumny dodane_przez (i te bez autora, jak odczyty licznika)
# lądują pod wspólną etykietą — inaczej filtr udawałby, że ich nie ma.
FILTR_AUTOR_MOJE = "Tylko moje"

FILTR_AUTOR_BEZ = "Bez autora"


def _autor_rekordu(rekord, pole):
    try:
        return " ".join(str(rekord[pole] or "").split())
    except Exception:
        return ""


def przycisk_filtrowania_autora(page: ft.Page, state, klucz_stanu, lista_danych, pole):
    """Filtr „Autor” obok Typ/Rok/Miesiąc. Opcje: Wszystko · Tylko moje ·
    każda osoba, która cokolwiek dodała. Przy dwóch domownikach działa jak
    przełącznik „tylko moje”, przy trzech od razu widać też konkretną osobę."""
    moje = db.pobierz_moje_imie()
    autorzy, sa_bez_autora = set(), False
    for w in lista_danych:
        autor = _autor_rekordu(w, pole)
        if autor:
            autorzy.add(autor)
        else:
            sa_bez_autora = True

    opcje = ["Wszystko", FILTR_AUTOR_MOJE]
    opcje += sorted(a for a in autorzy if a != moje)
    if sa_bez_autora:
        opcje.append(FILTR_AUTOR_BEZ)

    return _zbuduj_popup_filtra(
        page, state, klucz_stanu, opcje, "Autor",
        ft.Icons.PERSON, ft.Icons.PERSON_OUTLINE
    )


def filtruj_po_autorze(lista_danych, state, klucz_stanu, pole):
    filtr = state.filtry.get(klucz_stanu, "Wszystko")
    if filtr == "Wszystko":
        return lista_danych

    moje = db.pobierz_moje_imie()
    wynik = []
    for w in lista_danych:
        autor = _autor_rekordu(w, pole)
        if filtr == FILTR_AUTOR_MOJE:
            pasuje = bool(autor) and autor == moje
        elif filtr == FILTR_AUTOR_BEZ:
            pasuje = not autor
        else:
            pasuje = autor == filtr
        if pasuje:
            wynik.append(w)
    return wynik


def przycisk_filtrowania_miesiac(page: ft.Page, state, klucz_stanu, lista_danych, index_daty):
    miesiace_nr = set()
    for w in lista_danych:
        try:
            data_str = w[index_daty]
            d = parsuj_date(data_str)
            if d != datetime.min.date():
                miesiace_nr.add(d.month)
        except Exception:
            pass
    
    opcje = ["Wszystko"] + [MIESIACE_NAZWY[m - 1] for m in sorted(list(miesiace_nr))]
    return _zbuduj_popup_filtra(
        page, state, klucz_stanu, opcje, "Miesiąc",
        ft.Icons.DATE_RANGE_ROUNDED, ft.Icons.DATE_RANGE_OUTLINED
    )


def filtruj_po_roku(lista_danych, state, klucz_stanu, index_daty):
    filtr = state.filtry.get(klucz_stanu, "Wszystko")
    if filtr == "Wszystko":
        return lista_danych
    
    wynik = []
    for w in lista_danych:
        try:
            data_str = w[index_daty]
            d = parsuj_date(data_str)
            if d != datetime.min.date() and str(d.year) == filtr:
                wynik.append(w)
        except Exception:
            pass
    return wynik


def filtruj_po_kategorii(lista_danych, state, klucz_stanu, index_pola):
    filtr = state.filtry.get(klucz_stanu, "Wszystko")
    if filtr == "Wszystko":
        return lista_danych
    
    wynik = []
    for w in lista_danych:
        try:
            wartosc = str(w[index_pola] or "").strip()
            tagi_w_rekordzie = [t.strip() for t in wartosc.split(",")]
            if filtr in tagi_w_rekordzie:
                wynik.append(w)
        except Exception:
            pass
    return wynik


def filtruj_po_miesiacu(lista_danych, state, klucz_stanu, index_daty):
    filtr = state.filtry.get(klucz_stanu, "Wszystko")
    if filtr == "Wszystko":
        return lista_danych
    
    idx_miesiaca = MIESIACE_NAZWY.index(filtr) + 1
    wynik = []
    for w in lista_danych:
        try:
            data_str = w[index_daty]
            d = parsuj_date(data_str)
            if d != datetime.min.date() and d.month == idx_miesiaca:
                wynik.append(w)
        except Exception:
            pass
    return wynik


__all__ = [
    "FILTR_AUTOR_BEZ",
    "FILTR_AUTOR_MOJE",
    "_autor_rekordu",
    "_zbuduj_popup_filtra",
    "filtruj_po_autorze",
    "filtruj_po_kategorii",
    "filtruj_po_miesiacu",
    "filtruj_po_roku",
    "przycisk_filtrowania_autora",
    "przycisk_filtrowania_kategoria",
    "przycisk_filtrowania_miesiac",
    "przycisk_filtrowania_rok",
]
