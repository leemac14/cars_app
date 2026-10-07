"""Karta warsztatu: telefon, adres, „Zadzwoń” i „Pokaż na mapie” — dla ekranu
„Warsztaty” i panelu z karty wizyty (jedna definicja). Dane:
db.pobierz_karty_warsztatow, zapis: db.zapisz_warsztat."""

import flet as ft

import db
import log

from .stale import FS, RADIUS, SPACING
from .typografia import podpis, wartosc
from .zgodnosc import ustaw_blad
from .dialogi import (
    odswiez_ekran, otworz_dialog, otworz_dno, pokaz_komunikat, przejdz, zamknij_dialog, zamknij_dno,
)
from .sync_ui import wolno_zmieniac_rekord, wypchnij_w_tle
from .formularze import styl_pola
from .system import pokaz_na_mapie, zadzwon


def opis_wizyt_warsztatu(karta):
    """„3 wizyty · ostatnia 12.05.2026” — podpis pod nazwą warsztatu."""
    ile = karta.get("wizyt") or 0
    if not ile:
        return "Jeszcze bez wizyt"
    tekst = db.liczba_z_odmiana(ile, "wizyta", "wizyty", "wizyt")
    if karta.get("ostatnia"):
        tekst += f" · ostatnia {karta['ostatnia']}"
    return tekst


def przyciski_kontaktu(page: ft.Page, telefon, adres):
    """„Zadzwoń” i „Pokaż na mapie” — tylko te, dla których są dane."""
    przyciski = []
    if telefon:
        przyciski.append(ft.FilledTonalButton(
            "Zadzwoń", icon=ft.Icons.PHONE, on_click=lambda e: zadzwon(page, telefon)))
    if adres:
        przyciski.append(ft.FilledTonalButton(
            "Pokaż na mapie", icon=ft.Icons.MAP, on_click=lambda e: pokaz_na_mapie(page, adres)))
    return przyciski


def _wiersz_kontaktu(ikona, tekst):
    return ft.Row([
        ft.Icon(ikona, size=16, color=ft.Colors.ON_SURFACE_VARIANT),
        ft.Text(tekst, size=FS["body"], selectable=True, expand=True),
    ], spacing=SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.START)


def tresc_karty_warsztatu(page: ft.Page, karta, na_uzupelnienie=None):
    """Środek karty warsztatu. `na_uzupelnienie` dostaje przycisk „Dodaj telefon
    i adres”, gdy karta nie ma żadnego z nich; None zostawia sam podpis — rola
    „tylko podgląd” niczego nie uzupełni, a przycisk, który zawsze odmawia, jest
    gorszy od jego braku."""
    telefon, adres, notatki = karta.get("telefon"), karta.get("adres"), karta.get("notatki")
    wiersze = [ft.Row([
        ft.Icon(ft.Icons.CAR_REPAIR, size=22, color=ft.Colors.PRIMARY),
        ft.Column([
            wartosc(karta.get("nazwa") or "", size=FS["title"]),
            podpis(opis_wizyt_warsztatu(karta)),
        ], spacing=0, tight=True, expand=True),
    ], spacing=SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.CENTER)]
    if telefon:
        wiersze.append(_wiersz_kontaktu(ft.Icons.PHONE, telefon))
    if adres:
        wiersze.append(_wiersz_kontaktu(ft.Icons.PLACE, adres))
    if notatki:
        wiersze.append(podpis(notatki))

    przyciski = przyciski_kontaktu(page, telefon, adres)
    if przyciski:
        wiersze.append(ft.Row(przyciski, wrap=True, spacing=SPACING["sm"], run_spacing=SPACING["xs"]))
    elif na_uzupelnienie:
        wiersze.append(ft.TextButton("Dodaj telefon i adres", icon=ft.Icons.EDIT_NOTE,
                                     on_click=lambda e: na_uzupelnienie()))
    else:
        wiersze.append(podpis("Bez telefonu i adresu"))
    return ft.Column(wiersze, spacing=SPACING["sm"], tight=True)


def pokaz_formularz_warsztatu(page: ft.Page, state, karta=None, po_zapisie=None):
    """Okno dodania albo poprawki warsztatu. `karta` z db.pobierz_karty_warsztatow:
    z `id` — poprawka; bez `id` (nazwa znana tylko z wizyt) — nowa karta pod tą
    nazwą; None — zupełnie nowy warsztat. Zwraca okno, żeby test mógł kliknąć
    „Zapisz”."""
    karta = karta or {}
    warsztat_id = karta.get("id")
    stara_nazwa = karta.get("nazwa") or ""
    ile_wizyt = karta.get("wizyt") or 0

    e_nazwa = ft.TextField(
        label="Nazwa warsztatu", value=stara_nazwa, autofocus=not stara_nazwa,
        capitalization=ft.TextCapitalization.SENTENCES, **styl_pola())
    e_telefon = ft.TextField(
        label="Telefon", value=karta.get("telefon") or "", hint_text="np. 61 123 45 67",
        keyboard_type=ft.KeyboardType.PHONE, **styl_pola())
    e_adres = ft.TextField(
        label="Adres", value=karta.get("adres") or "",
        hint_text="ulica i miasto — tak, jak wpisałbyś w mapy",
        keyboard_type=ft.KeyboardType.STREET_ADDRESS, **styl_pola())
    e_notatki = ft.TextField(
        label="Notatka", value=karta.get("notatki") or "",
        hint_text="godziny otwarcia, z kim rozmawiać",
        multiline=True, min_lines=1, max_lines=4, **styl_pola())
    # Nazwa warsztatu stoi też na wizytach — mówimy to, zanim ktoś ją zmieni,
    # a nie dopiero wtedy, gdy lista wizyt pokaże nową pisownię.
    uwaga_nazwy = podpis("", visible=False)

    def po_zmianie_nazwy(e):
        nowa = db.normalizuj_nazwe(e_nazwa.value)
        uwaga_nazwy.visible = bool(warsztat_id and ile_wizyt and nowa and nowa != stara_nazwa)
        uwaga_nazwy.value = (f"Nowa nazwa pojawi się też na "
                             f"{db.liczba_z_odmiana(ile_wizyt, 'wizycie', 'wizytach', 'wizytach')} w historii.")
        try:
            uwaga_nazwy.update()
        except Exception:
            log.polkniety("podpowiedź o zmianie nazwy warsztatu")

    e_nazwa.on_change = po_zmianie_nazwy

    def zapisz(e):
        ustaw_blad(e_nazwa)
        ustaw_blad(e_telefon)
        telefon = (e_telefon.value or "").strip()
        if telefon and sum(z.isdigit() for z in telefon) < 3:
            ustaw_blad(e_telefon, "Numer musi mieć cyfry, np. 61 123 45 67")
            page.update()
            return
        blad = db.zapisz_warsztat(state.auto_id, warsztat_id, e_nazwa.value, telefon,
                                  e_adres.value, e_notatki.value)
        if blad:
            ustaw_blad(e_nazwa, blad)
            page.update()
            return
        zamknij_dialog(page, dlg)
        pokaz_komunikat(page, "Zapisano warsztat" if warsztat_id else "Dodano warsztat")
        wypchnij_w_tle(page, state.auto_id, "warsztat")
        if po_zapisie:
            po_zapisie()

    dlg = ft.AlertDialog(
        modal=True,
        title=ft.Row([ft.Icon(ft.Icons.CAR_REPAIR, color=ft.Colors.PRIMARY),
                      ft.Text("Edycja warsztatu" if warsztat_id else "Nowy warsztat",
                              weight="bold", expand=True)], spacing=8),
        content=ft.Column([e_nazwa, uwaga_nazwy, e_telefon, e_adres, e_notatki],
                          tight=True, spacing=10, scroll=ft.ScrollMode.AUTO),
        actions=[
            ft.TextButton("Anuluj", on_click=lambda e: zamknij_dialog(page, dlg)),
            ft.Button("Zapisz", on_click=zapisz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    otworz_dialog(page, dlg)
    return dlg


def karta_warsztatu_po_nazwie(auto_id, nazwa):
    """Karta warsztatu, którego nazwa stoi na wpisie — z rejestru, a gdy tam
    jej nie ma, sama nazwa (panel zaproponuje wtedy dodanie karty)."""
    klucz = db.klucz_nazwy(nazwa)
    karta = next((k for k in db.pobierz_karty_warsztatow(auto_id) if k["klucz"] == klucz), None)
    return karta or {"id": None, "nazwa": db.normalizuj_nazwe(nazwa), "klucz": klucz}


def pokaz_karte_warsztatu(page: ft.Page, state, nazwa):
    """Panel z kartą warsztatu — otwierany z wiersza warsztatu na karcie wizyty."""
    karta = karta_warsztatu_po_nazwie(state.auto_id, nazwa)
    bs = ft.BottomSheet(ft.Container(padding=ft.Padding(16, 16, 16, 8), bgcolor=ft.Colors.SURFACE))

    def edytuj(e):
        zamknij_dno(page, bs)
        pokaz_formularz_warsztatu(page, state, karta, po_zapisie=lambda: odswiez_ekran(page))

    def wszystkie(e):
        zamknij_dno(page, bs)
        przejdz(page, "/warsztaty")

    akcje = []
    if wolno_zmieniac_rekord(state.auto_id, "warsztaty"):
        brak_danych = not (karta.get("telefon") or karta.get("adres"))
        akcje.append(ft.TextButton("Dodaj telefon i adres" if brak_danych else "Edytuj dane",
                                   icon=ft.Icons.EDIT_NOTE if brak_danych else ft.Icons.EDIT,
                                   on_click=edytuj))
    akcje.append(ft.TextButton("Wszystkie warsztaty", icon=ft.Icons.LIST, on_click=wszystkie))

    bs.content.content = ft.Column([
        tresc_karty_warsztatu(page, karta),
        ft.Row(akcje, alignment=ft.MainAxisAlignment.END, wrap=True, spacing=SPACING["xs"]),
    ], tight=True, spacing=SPACING["md"])
    otworz_dno(page, bs)
    return bs


def wiersz_warsztatu_wizyty(page: ft.Page, state, nazwa, kontakt=None):
    """Wiersz warsztatu na karcie wizyty. Nazwa otwiera kartę warsztatu, a przy
    znanym telefonie i adresie stoją od razu dwa małe przyciski — z listy wizyt
    dzwoni się tam, gdzie auto było ostatnio, bez przechodzenia dalej.
    `kontakt` to (telefon, adres) z rejestru albo None."""
    telefon, adres = kontakt or (None, None)
    wiersz = [ft.Container(
        content=ft.Row([
            ft.Icon(ft.Icons.CAR_REPAIR, size=14, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Text(nazwa, size=FS["label"], color=ft.Colors.ON_SURFACE_VARIANT, expand=True,
                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
        ], spacing=SPACING["xs"]),
        on_click=lambda e: pokaz_karte_warsztatu(page, state, nazwa),
        # Bez podpowiedzi (tooltip): na telefonie zajęłaby długie przytrzymanie,
        # którym karta wizyty włącza zaznaczanie grupowe.
        ink=True, border_radius=RADIUS["xs"], padding=ft.Padding(0, 2, 6, 2), expand=True,
    )]
    if telefon:
        wiersz.append(ft.IconButton(
            ft.Icons.PHONE, icon_size=16, icon_color=ft.Colors.PRIMARY, tooltip="Zadzwoń",
            on_click=lambda e: zadzwon(page, telefon), style=ft.ButtonStyle(padding=0),
            width=30, height=30,
        ))
    if adres:
        wiersz.append(ft.IconButton(
            ft.Icons.MAP, icon_size=16, icon_color=ft.Colors.PRIMARY, tooltip="Pokaż na mapie",
            on_click=lambda e: pokaz_na_mapie(page, adres), style=ft.ButtonStyle(padding=0),
            width=30, height=30,
        ))
    return ft.Row(wiersz, spacing=2, vertical_alignment=ft.CrossAxisAlignment.CENTER)


__all__ = [
    "karta_warsztatu_po_nazwie",
    "opis_wizyt_warsztatu",
    "pokaz_formularz_warsztatu",
    "pokaz_karte_warsztatu",
    "przyciski_kontaktu",
    "tresc_karty_warsztatu",
    "wiersz_warsztatu_wizyty",
]
