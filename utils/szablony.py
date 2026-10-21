"""Szablony wpisów w interfejsie (M-02): szybkie pozycje menu „+”, arkusz „Szablony…”, okno
„Zapisz jako szablon” i wypełnienie nowego formularza. Dane i zapis — db/szablony.py."""

import flet as ft

import db
import log

from .stale import FS, KOLOR_STATUS, SPACING, formatuj_liczba, ikona_kategorii_innych
from .format import parsuj_float, symbol_waluty
from .typografia import podpis
from .wyglad import powierzchnia
from .haptyka import wibracja
from .zgodnosc import ustaw_blad
from .dialogi import (otworz_dialog, otworz_dno, pokaz_komunikat, pokaz_komunikat_cofnij, pokaz_menu_kontekstowe,
                      potwierdz, przejdz, zamknij_dialog, zamknij_dno)
from .sync_ui import wolno_dodawac, wypchnij_w_tle
from .formularze import styl_pola
from .magazyn import liczba_do_pola

SZEROKOSC_OKNA_SZABLONU = 340
# Nazwa na pigułce menu „+” — dłuższa rozpychałaby rząd szybkich pozycji.
MAKS_NAPISU_W_MENU = 22


def _kwota(kwota):
    return f"{formatuj_liczba(kwota, 0 if float(kwota).is_integer() else 2)} {symbol_waluty()}"


def _odswiez(page: ft.Page, opis):
    try:
        page.update()
    except Exception:
        log.polkniety(opis)


def napis_szablonu(szablon, maks=MAKS_NAPISU_W_MENU):
    """„Myjnia · 40 zł” — nazwa z kwotą, gdy szablon zapisuje koszt od razu."""
    nazwa = db.skrot_notatki(szablon["nazwa"], maks)
    return f"{nazwa} · {_kwota(szablon['dane']['kwota'])}" if db.czy_szablon_od_razu(szablon) else nazwa


def ikona_szablonu(szablon):
    dane = szablon["dane"]
    if szablon["rodzaj"] == db.SZABLON_TANKOWANIE:
        return ft.Icons.EV_STATION if dane.get("rodzaj_energii") == db.ENERGIA_PRAD else ft.Icons.LOCAL_GAS_STATION
    return ikona_kategorii_innych(dane.get("kategoria"))


def opis_szablonu(szablon):
    """Co szablon wpisze: kategoria i kwota kosztu albo stacja, paliwo i „do pełna”, plus tagi."""
    dane = szablon["dane"]
    if szablon["rodzaj"] == db.SZABLON_KOSZT:
        czesci = [dane.get("kategoria"),
                  _kwota(dane["kwota"]) if dane.get("kwota") else "kwotę wpiszesz w formularzu"]
    else:
        prad = dane.get("rodzaj_energii") == db.ENERGIA_PRAD
        czesci = [dane.get("stacja"), "ładowanie" if prad else "tankowanie",
                  dane.get("typ_ladowania") if prad else None,
                  "do pełna" if dane.get("do_pelna") and not prad else None]
    if dane.get("tagi"):
        czesci.append("tagi: " + ", ".join(t.strip() for t in dane["tagi"].split(",") if t.strip()))
    return " · ".join(c for c in czesci if c)


def _komunikat_zapisu(page: ft.Page, tekst, cofnij, sekundy=5):
    """Pasek „Zapisano…” z „Cofnij” — jak po usunięciu, tylko w drugą stronę."""
    snack = ft.SnackBar(content=ft.Text(tekst), action="Cofnij", on_action=lambda e: cofnij(),
                        duration=sekundy * 1000)
    if hasattr(page, "open"):
        page.open(snack)
    else:
        page.overlay.append(snack)
        snack.open = True
        page.update()


def _cofnij_koszt(page: ft.Page, auto_id, koszt_id):
    if not db.cofnij_koszt_z_szablonu(koszt_id):
        return pokaz_komunikat(page, "Nie cofnięto — tego kosztu już nie ma.", KOLOR_STATUS["error"])
    wypchnij_w_tle(page, auto_id, "cofnięty koszt z szablonu")
    przejdz(page, "/")
    pokaz_komunikat(page, "Cofnięto zapis kosztu.")


def _zapisz_od_razu(page: ft.Page, state, szablon):
    auto_id = state.auto_id
    koszt_id = db.zapisz_koszt_z_szablonu(auto_id, szablon["id"])
    if not koszt_id:
        return pokaz_komunikat(page, "Nie zapisano — tego szablonu już nie ma.", KOLOR_STATUS["error"])
    wibracja(page, "zapis")
    wypchnij_w_tle(page, auto_id, "inny koszt z szablonu")
    przejdz(page, "/")
    _komunikat_zapisu(page, f"Zapisano: {napis_szablonu(szablon, 40)}.",
                      lambda: _cofnij_koszt(page, auto_id, koszt_id))


def uzyj_szablonu(page: ft.Page, state, szablon):
    """Koszt z kwotą zapisuje się od razu (dziś, z „Cofnij”); reszta otwiera wypełniony formularz."""
    auto_id = getattr(state, "auto_id", None)
    if not szablon or szablon.get("auto_id") != auto_id:
        return None
    if not wolno_dodawac(auto_id):
        return pokaz_komunikat(page, "Przy tej roli nie dodajesz wpisów do tego pojazdu.", KOLOR_STATUS["error"])
    if db.czy_szablon_od_razu(szablon):
        if db.ostrzezenie_szablonu_dzis(auto_id, szablon):
            return potwierdz(
                page, "Taki koszt już dziś jest",
                f"Dziś jest już zapisany koszt „{szablon['dane'].get('nazwa') or szablon['nazwa']}” na "
                f"{_kwota(szablon['dane']['kwota'])}. Dodać drugi taki sam?",
                lambda: _zapisz_od_razu(page, state, szablon), tekst_potwierdzenia="Dodaj", destrukcyjne=False,
            )
        return _zapisz_od_razu(page, state, szablon)
    db.zanotuj_uzycie_szablonu(szablon["id"])
    state.szablon_wpisu = {"id": szablon["id"], "auto_id": auto_id, "rodzaj": szablon["rodzaj"],
                           "dane": dict(szablon["dane"])}
    przejdz(page, "/inne/nowy" if szablon["rodzaj"] == db.SZABLON_KOSZT else "/tankowanie/nowe")
    return None


def szablon_do_formularza(state, rodzaj, rekord_id=None):
    """Pola szablonu dla NOWEGO wpisu tego rodzaju — zużywane raz, jak źródło duplikatu.
    Edycja, inny rodzaj albo inne auto dają None."""
    szablon = getattr(state, "szablon_wpisu", None)
    state.szablon_wpisu = None
    if (rekord_id or not szablon or szablon.get("rodzaj") != rodzaj
            or szablon.get("auto_id") != getattr(state, "auto_id", None)):
        return None
    return dict(szablon.get("dane") or {})


def szybkie_szablony(page: ft.Page, state):
    """Rząd szybkich pozycji menu „+”: najczęściej używane szablony i „Szablony…” (pusty bez szablonów
    albo przy roli bez dodawania)."""
    auto_id = getattr(state, "auto_id", None)
    if not auto_id or not wolno_dodawac(auto_id):
        return []
    szablony = db.pobierz_szablony(auto_id)
    if not szablony:
        return []
    akcje = [(ikona_szablonu(s), napis_szablonu(s), lambda e, s=s: uzyj_szablonu(page, state, s))
             for s in szablony[:db.SZABLONY_W_MENU]]
    akcje.append((ft.Icons.BOOKMARKS, "Szablony…", lambda e: pokaz_szablony(page, state)))
    return akcje


def okno_szablonu(page: ft.Page, state, rodzaj, dane, szablon=None, po_zapisie=None):
    """Nazwa (i kwota kosztu) — nowy szablon z wpisu albo poprawka istniejącego."""
    koszt = rodzaj == db.SZABLON_KOSZT
    e_nazwa = ft.TextField(
        label="Nazwa w menu „+”", max_length=db.MAKS_DLUGOSC_NAZWY_SZABLONU, **styl_pola(),
        value=szablon["nazwa"] if szablon else db.proponowana_nazwa_szablonu(rodzaj, dane),
    )
    e_kwota = ft.TextField(label=f"Kwota ({symbol_waluty()})", value=liczba_do_pola(dane.get("kwota")),
                           keyboard_type=ft.KeyboardType.NUMBER, **styl_pola()) if koszt else None
    if koszt:
        wyjasnienie = ("Z kwotą dotknięcie szablonu zapisze koszt od razu, z dzisiejszą datą. "
                       "Bez kwoty otworzy wypełniony formularz.")
    else:
        wyjasnienie = ("Szablon zapamięta stację, paliwo, „do pełna”, tagi i notatkę — litry, kwotę "
                       "i licznik wpiszesz przy tankowaniu.")

    def zapisz(e):
        ustaw_blad(e_nazwa)
        nowe = dict(dane)
        if koszt:
            ustaw_blad(e_kwota)
            tekst = (e_kwota.value or "").strip()
            kwota = parsuj_float(tekst, None) if tekst else None
            if tekst and (kwota is None or kwota <= 0):
                ustaw_blad(e_kwota, "Podaj kwotę większą od zera albo zostaw puste")
                return _odswiez(page, "błąd kwoty w oknie szablonu")
            nowe["kwota"] = kwota
        wynik = db.zapisz_szablon(state.auto_id, rodzaj, e_nazwa.value, nowe,
                                  szablon_id=szablon["id"] if szablon else None)
        if not wynik["ok"]:
            ustaw_blad(e_nazwa, wynik["powod"])
            return _odswiez(page, "błąd nazwy w oknie szablonu")
        zamknij_dialog(page, dlg)
        wypchnij_w_tle(page, state.auto_id, "szablon wpisu")
        nazwa = (e_nazwa.value or "").strip()
        if szablon:
            komunikat = f"Zapisano zmiany szablonu „{nazwa}”."
        elif wynik["nowy"]:
            komunikat = f"Szablon „{nazwa}” czeka w menu „+”."
        else:
            komunikat = f"Szablon „{nazwa}” już był — zapisano go od nowa z tego wpisu."
        if po_zapisie:
            po_zapisie()
        pokaz_komunikat(page, komunikat)

    dlg = ft.AlertDialog(
        modal=True, scrollable=True,
        title=ft.Row([ft.Icon(ft.Icons.BOOKMARK_ADD, color=ft.Colors.PRIMARY),
                      ft.Text("Szablon wpisu" if szablon else "Zapisz jako szablon", weight="bold", expand=True)],
                     spacing=8),
        content=ft.Container(width=SZEROKOSC_OKNA_SZABLONU, content=ft.Column(
            [podpis(wyjasnienie), e_nazwa] + ([e_kwota] if e_kwota else []), tight=True, spacing=10)),
        actions=[
            ft.TextButton("Anuluj", on_click=lambda e: zamknij_dialog(page, dlg)),
            ft.Button("Zapisz", on_click=zapisz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    otworz_dialog(page, dlg)
    return dlg


def pozycja_menu_szablonu(page: ft.Page, state, rodzaj, rekord_id):
    """„Zapisz jako szablon” do menu kosztu albo tankowania; None, gdy rola nie pozwala dodawać.
    Wpisu nie zmienia, więc zostaje też przy cudzym wpisie (`czyta`)."""
    auto_id = getattr(state, "auto_id", None)
    if not auto_id or not wolno_dodawac(auto_id):
        return None

    def akcja():
        dane = db.dane_szablonu_z_wpisu(rodzaj, rekord_id)
        if dane is None:
            return pokaz_komunikat(page, "Tego wpisu już nie ma.", KOLOR_STATUS["error"])
        return okno_szablonu(page, state, rodzaj, dane, po_zapisie=lambda: przejdz(page, page.route))

    return {"ikona": ft.Icons.BOOKMARK_ADD_OUTLINED, "tekst": "Zapisz jako szablon", "akcja": akcja, "czyta": True}


def _wiersz_szablonu(page: ft.Page, szablon, on_uzyj, on_opcje):
    return ft.Container(
        padding=ft.Padding(12, 8, 4, 8), ink=True, on_click=lambda e: on_uzyj(szablon),
        **powierzchnia(page, "blok"),
        content=ft.Row([
            ft.Icon(ikona_szablonu(szablon), size=20, color=ft.Colors.PRIMARY),
            ft.Column([
                ft.Text(szablon["nazwa"], size=FS["body_strong"], weight=ft.FontWeight.W_500,
                        max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                podpis(opis_szablonu(szablon)),
            ], spacing=1, tight=True, expand=True),
            ft.IconButton(icon=ft.Icons.MORE_VERT, tooltip="Opcje szablonu", on_click=lambda e: on_opcje(szablon)),
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
    )


def pokaz_szablony(page: ft.Page, state):
    """Arkusz „Szablony…”: wszystkie szablony auta — dotknięcie dodaje wpis, ⋮ zmienia albo usuwa."""
    auto_id = getattr(state, "auto_id", None)
    bs = ft.BottomSheet(ft.Container(padding=20, bgcolor=ft.Colors.SURFACE))

    def uzyj(szablon):
        zamknij_dno(page, bs)
        uzyj_szablonu(page, state, szablon)

    def po_zmianie():
        przejdz(page, page.route)
        pokaz_szablony(page, state)

    def usun(szablon):
        wynik = db.usun_z_cofnieciem("szablony_wpisow", szablon["id"])
        if wynik:
            wypchnij_w_tle(page, auto_id, "usunięty szablon")
        przejdz(page, page.route)
        pokaz_komunikat_cofnij(page, f"Usunięto szablon „{szablon['nazwa']}”.", wynik)

    def opcje(szablon):
        zamknij_dno(page, bs)
        pokaz_menu_kontekstowe(page, szablon["nazwa"], [
            {"ikona": ft.Icons.EDIT, "tekst": "Zmień nazwę" + (" i kwotę" if szablon["rodzaj"] == db.SZABLON_KOSZT else ""),
             "akcja": lambda: okno_szablonu(page, state, szablon["rodzaj"], szablon["dane"], szablon, po_zmianie)},
            {"ikona": ft.Icons.DELETE, "tekst": "Usuń szablon", "akcja": lambda: usun(szablon),
             "kolor": KOLOR_STATUS["destructive"]},
        ])

    szablony = db.pobierz_szablony(auto_id)
    zawartosc = [
        ft.Row([ft.Icon(ft.Icons.BOOKMARKS, size=22, color=ft.Colors.PRIMARY),
                ft.Text("Szablony wpisów", weight="bold", size=FS["heading"], color=ft.Colors.PRIMARY, expand=True)],
               spacing=10),
        podpis("Koszt z kwotą zapisze się od razu z dzisiejszą datą, reszta otworzy wypełniony formularz. "
               "Nowy szablon zrobisz z kosztu albo tankowania: menu wpisu → „Zapisz jako szablon”."),
    ]
    if not szablony:
        zawartosc.append(podpis("Ten pojazd nie ma jeszcze szablonów."))
    zawartosc.extend(_wiersz_szablonu(page, s, uzyj, opcje) for s in szablony)
    bs.content.content = ft.Column(zawartosc, tight=True, spacing=SPACING["sm"])
    otworz_dno(page, bs)
    return bs


__all__ = [
    "MAKS_NAPISU_W_MENU",
    "SZEROKOSC_OKNA_SZABLONU",
    "ikona_szablonu",
    "napis_szablonu",
    "okno_szablonu",
    "opis_szablonu",
    "pokaz_szablony",
    "pozycja_menu_szablonu",
    "szablon_do_formularza",
    "szybkie_szablony",
    "uzyj_szablonu",
]
