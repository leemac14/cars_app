"""Krótka notatka przy wpisie — podgląd, edycja i zapis."""

import db
import flet as ft

from .stale import FS, RADIUS, SPACING
from .dialogi import otworz_dialog, pokaz_komunikat, zamknij_dialog
from .sync_ui import wypchnij_w_tle
from .formularze import styl_pola


# ==================== KRÓTKA NOTATKA PRZY WPISIE ====================
# Jeden zestaw komponentów na całą aplikację: podgląd na karcie, pełna treść w
# dialogu, szybka edycja z menu wpisu i pole w formularzu. Dołożenie notatki do
# kolejnej listy to dzięki temu dwie linijki, a nie kopia UI — i wszędzie
# wygląda tak samo, więc użytkownik uczy się tego raz.

def _podpis_notatki(autor, data):
    """„Kasia • 04.09.2026 18:12”, z pominięciem części, których brakuje."""
    return " • ".join(str(x) for x in (autor, data) if x)


def pokaz_notatke(page: ft.Page, tresc, autor=None, data=None, tytul="Notatka", on_edytuj=None):
    """Pełna treść notatki w dialogu — podgląd na karcie jest przycięty do
    dwóch linijek, więc musi istnieć miejsce, gdzie widać całość."""
    if not (tresc or "").strip():
        return
    podpis = _podpis_notatki(autor, data)
    tresc_dialogu = [ft.Text(str(tresc), size=FS["body_strong"], selectable=True)]
    if podpis:
        tresc_dialogu.append(ft.Container(height=SPACING["sm"]))
        tresc_dialogu.append(ft.Text(podpis, size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT))

    dlg = ft.AlertDialog(
        title=ft.Row([ft.Icon(ft.Icons.STICKY_NOTE_2_OUTLINED, size=20, color=ft.Colors.PRIMARY),
                      ft.Text(tytul, weight="bold", expand=True)], spacing=SPACING["sm"]),
        content=ft.Column(tresc_dialogu, tight=True, spacing=0),
        shape=ft.RoundedRectangleBorder(radius=RADIUS["lg"]),
    )
    akcje = [ft.TextButton("Zamknij", on_click=lambda e: zamknij_dialog(page, dlg))]
    if on_edytuj:
        def edytuj(e):
            zamknij_dialog(page, dlg)
            on_edytuj()
        akcje.insert(0, ft.TextButton("Edytuj", on_click=edytuj))
    dlg.actions = akcje
    dlg.actions_alignment = ft.MainAxisAlignment.END
    otworz_dialog(page, dlg)


def podglad_notatki(page: ft.Page, tresc, autor=None, data=None, tytul="Notatka",
                    on_edytuj=None, pokaz_podpis=True):
    """Notatka na karcie wpisu: ikona dymka + treść kursywą, maks. dwie linijki
    z wielokropkiem. Klik otwiera pełną treść — dzięki temu długa uwaga nie
    rozpycha listy, a mimo to jest cała dostępna jednym dotknięciem.
    Brak notatki = pusty kontener, więc wołający nie musi tego sprawdzać."""
    tekst = (tresc or "").strip()
    if not tekst:
        return ft.Container(width=0, height=0)

    linie = [ft.Text(tekst, size=FS["body"], italic=True, color=ft.Colors.ON_SURFACE_VARIANT,
                     max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)]
    podpis = _podpis_notatki(autor, data) if pokaz_podpis else ""
    if podpis:
        linie.append(ft.Text(podpis, size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT))

    return ft.Container(
        margin=ft.Margin(0, SPACING["xs"], 0, 0),
        padding=ft.Padding(SPACING["sm"], 6, SPACING["sm"], 6),
        border_radius=RADIUS["sm"],
        bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.ON_SURFACE),
        border=ft.Border.only(left=ft.BorderSide(3, ft.Colors.with_opacity(0.35, ft.Colors.PRIMARY))),
        tooltip="Pokaż całą notatkę",
        on_click=lambda e: pokaz_notatke(page, tekst, autor, data, tytul, on_edytuj),
        content=ft.Row([
            ft.Icon(ft.Icons.STICKY_NOTE_2_OUTLINED, size=14, color=ft.Colors.with_opacity(0.7, ft.Colors.PRIMARY)),
            ft.Column(linie, spacing=1, expand=True),
        ], spacing=SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.START),
    )


def pole_notatki(wartosc="", page: ft.Page = None, label="Notatka (krótka uwaga do tego wpisu)"):
    """Pole notatki w formularzu — ten sam limit co przy szybkiej edycji, więc
    treści nie da się „przemycić” dłuższej jedną z dwóch dróg."""
    return ft.TextField(
        label=label,
        value=str(wartosc or ""),
        multiline=True, min_lines=1, max_lines=3,
        max_length=db.MAKS_DLUGOSC_NOTATKI,
        **styl_pola(page=page)
    )


def szybka_notatka(page: ft.Page, tabela, rekord_id, po_zapisie_callback=None, tytul="Notatka"):
    """Dopisanie/poprawienie notatki BEZ wchodzenia w edycję całego wpisu —
    odpowiednik `szybkie_dodanie_zdjecia` dla tekstu. Po zapisie wypychamy
    zmianę w tle, żeby uwaga dotarła do osób współdzielących pojazd."""
    biezaca, autor, data_notatki = db.pobierz_notatke(tabela, rekord_id)

    pole = ft.TextField(
        label="Twoja notatka",
        value=biezaca,
        multiline=True, min_lines=3, max_lines=5,
        max_length=db.MAKS_DLUGOSC_NOTATKI,
        autofocus=True,
        **styl_pola(page=page)
    )

    zawartosc = [pole]
    podpis = _podpis_notatki(autor, data_notatki)
    if podpis:
        zawartosc.append(ft.Text(f"Ostatnio: {podpis}", size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT))

    dlg = ft.AlertDialog(
        modal=True,
        title=ft.Row([ft.Icon(ft.Icons.STICKY_NOTE_2_OUTLINED, size=20, color=ft.Colors.PRIMARY),
                      ft.Text(tytul, weight="bold", expand=True)], spacing=SPACING["sm"]),
        content=ft.Container(width=420, content=ft.Column(zawartosc, tight=True, spacing=SPACING["sm"])),
        shape=ft.RoundedRectangleBorder(radius=RADIUS["lg"]),
    )

    def zapisz(e):
        nowa = db.przytnij_notatke(pole.value)
        if nowa == (biezaca or "").strip():
            zamknij_dialog(page, dlg)
            return
        try:
            auto_id = db.zapisz_notatke(tabela, rekord_id, nowa)
        except Exception as ex:
            zamknij_dialog(page, dlg)
            pokaz_komunikat(page, f"Nie udało się zapisać notatki: {ex}", ft.Colors.RED_700)
            return
        zamknij_dialog(page, dlg)
        wypchnij_w_tle(page, auto_id, "notatka")
        pokaz_komunikat(page, "Zapisano notatkę." if nowa else "Usunięto notatkę.")
        if po_zapisie_callback:
            po_zapisie_callback()

    dlg.actions = [
        ft.TextButton("Anuluj", on_click=lambda e: zamknij_dialog(page, dlg)),
        ft.FilledButton("Zapisz", on_click=zapisz),
    ]
    dlg.actions_alignment = ft.MainAxisAlignment.END
    otworz_dialog(page, dlg)


def zapisz_notatke_z_formularza(tabela, rekord_id, nowa_tresc, tresc_bazowa):
    """Zapis notatki przy zapisie CAŁEGO wpisu z formularza. Kluczowy warunek:
    piszemy tylko wtedy, gdy treść faktycznie się zmieniła. Bez tego poprawienie
    kwoty tankowania przestemplowałoby podpis pod cudzą notatką na własny —
    a przy wspólnym aucie to dokładnie ta informacja, po którą się tam sięga.
    Zwraca True, jeśli notatka została zapisana."""
    if not rekord_id:
        return False
    nowa = db.przytnij_notatke(nowa_tresc)
    if nowa == db.przytnij_notatke(tresc_bazowa):
        return False
    try:
        db.zapisz_notatke(tabela, rekord_id, nowa)
    except Exception:
        # Notatka nie może wywrócić zapisu samego wpisu — reszta danych
        # jest już w bazie i to ona jest tu najważniejsza.
        return False
    return True


def pozycja_menu_notatki(page: ft.Page, tabela, rekord_id, tresc, po_zapisie_callback=None, tytul="Notatka"):
    """Gotowa pozycja do `pokaz_menu_kontekstowe` — jedna linijka przy każdym
    typie wpisu zamiast powtarzania tego samego handlera pięć razy."""
    ma_notatke = bool((tresc or "").strip())
    return {
        "ikona": ft.Icons.EDIT_NOTE if ma_notatke else ft.Icons.NOTE_ADD_OUTLINED,
        "tekst": "Edytuj notatkę" if ma_notatke else "Dodaj notatkę",
        "akcja": lambda: szybka_notatka(page, tabela, rekord_id, po_zapisie_callback, tytul),
    }


__all__ = [
    "_podpis_notatki",
    "podglad_notatki",
    "pokaz_notatke",
    "pole_notatki",
    "pozycja_menu_notatki",
    "szybka_notatka",
    "zapisz_notatke_z_formularza",
]
