"""Kopia zapasowa po stronie interfejsu: baner na kokpicie, „Zrób teraz” i opisy
stanu wspólne dla kokpitu, dzwonka i Ustawień. Dane i sama kopia: db/kopie.py."""

import asyncio
from datetime import datetime

import db
import flet as ft
import log

from .stale import FS, KOLOR_STATUS, RADIUS, SPACING
from .format import formatuj_date_pl, formatuj_dni, formatuj_rozmiar
from .typografia import podpis, wartosc
from .dialogi import pokaz_komunikat, pokaz_ladowanie, pokaz_ostrzezenie, przejdz, ukryj_ladowanie


def opis_wieku_kopii(dni):
    """„dziś”, „wczoraj”, „74 dni temu” — albo „nigdy”."""
    if dni is None:
        return "nigdy"
    if dni <= 0:
        return "dziś"
    if dni == 1:
        return "wczoraj"
    return f"{formatuj_dni(dni)} temu"


def moment_kopii(moment):
    """„dziś, 21:15”, „wczoraj, 08:02”, „1 października, 21:15” (rok tylko
    wtedy, gdy inny niż bieżący)."""
    if moment is None:
        return "—"
    dni = (datetime.now().date() - moment.date()).days
    dzien = "dziś" if dni == 0 else "wczoraj" if dni == 1 else formatuj_date_pl(moment.date())
    return f"{dzien}, {moment.strftime('%H:%M')}"


def tytul_stanu_kopii(stan):
    """„Ostatnia kopia: 74 dni temu” albo „Brak kopii zapasowej”."""
    if stan.get("ostatnia") is None:
        return "Brak kopii zapasowej"
    return f"Ostatnia kopia: {opis_wieku_kopii(stan.get('dni'))}"


def powod_stanu_kopii(stan):
    """Czemu kopia jest zaległa — pusty napis, gdy nie ma czego dodać. Błąd
    ostatniej próby wygrywa z „wyłączona”: mówi, co trzeba naprawić."""
    if stan.get("blad"):
        return f"Kopia nie wyszła: {stan['blad']}"
    if not stan.get("wlaczona"):
        return "Automatyczna kopia jest wyłączona"
    return ""


def linie_stanu_kopii(stan):
    """Linie opisu dla dzwonka: wiek kopii, a pod nim powód."""
    powod = powod_stanu_kopii(stan)
    return [tytul_stanu_kopii(stan)] + ([powod] if powod else [])


def czy_udostepniono(wynik):
    """Czy systemowe „Udostępnij” dowiozło plik — wybrana aplikacja (Dysk,
    Gmail, Pliki), a nie zamknięty arkusz. Wynik bez statusu (starszy Flet)
    znaczy „nie wiadomo” i się nie liczy."""
    status = getattr(wynik, "status", None)
    return str(getattr(status, "value", status) or "").lower() == "success"


def zrob_kopie_teraz(page: ft.Page, po_zakonczeniu=None):
    """„Zrób teraz” z banera, dzwonka i Ustawień: ta sama kopia co automatyczna
    (folder, sprawdzenie, rotacja), tylko bez czekania na termin.
    `po_zakonczeniu(wynik)` dostaje słownik z `db.wykonaj_kopie`."""
    async def _wykonaj():
        dlg = pokaz_ladowanie(page, "Zapisywanie kopii zapasowej...")
        try:
            wynik = await asyncio.to_thread(db.wykonaj_kopie, True)
        except Exception as ex:
            log.blad("kopia zapasowa na żądanie")
            wynik = {"ok": False, "w_toku": False, "blad": str(ex), "folder": None, "rozmiar": 0}
        finally:
            ukryj_ladowanie(page, dlg)

        if wynik["ok"]:
            pokaz_komunikat(page, f"Zapisano kopię zapasową ({formatuj_rozmiar(wynik['rozmiar'])}).",
                            KOLOR_STATUS["ok"])
        elif wynik["w_toku"]:
            pokaz_komunikat(page, "Kopia zapasowa właśnie się zapisuje — zajrzyj za chwilę.",
                            KOLOR_STATUS["info"])
        else:
            blad = wynik["blad"] or "nieznany błąd"
            tresc = blad[:1].upper() + blad[1:] + "."
            if wynik.get("folder"):
                tresc += f"\n\nFolder: {wynik['folder']}"
            tresc += "\n\nFolder i rytm kopii zmienisz w Ustawieniach → Kopia zapasowa."
            pokaz_ostrzezenie(page, "Kopia zapasowa nie powstała", tresc)

        if po_zakonczeniu:
            try:
                po_zakonczeniu(wynik)
            except Exception:
                log.polkniety("odświeżenie ekranu po kopii zapasowej")

    page.run_task(_wykonaj)


def baner_kopii(page: ft.Page, stan, po_kopii=None):
    """„Ostatnia kopia: 74 dni temu” nad kafelkami kokpitu — wyłącznie przy
    kopii zaległej (`stan["zalegla"]`), czyli wtedy, gdy kopia automatyczna się
    nie udała albo jest wyłączona. Dotknięcie prowadzi do Ustawień, przycisk
    robi kopię od razu."""
    kolor = KOLOR_STATUS["warning"]
    return ft.Container(
        padding=ft.Padding(SPACING["md"], SPACING["sm"], SPACING["xs"], SPACING["sm"]),
        border_radius=RADIUS["lg"], bgcolor=ft.Colors.with_opacity(0.10, kolor),
        ink=True, tooltip="Ustawienia kopii zapasowej",
        on_click=lambda e: przejdz(page, "/ustawienia"),
        content=ft.Row([
            ft.Icon(ft.Icons.BACKUP, size=22, color=kolor),
            ft.Column([
                wartosc(tytul_stanu_kopii(stan), size=FS["body_strong"]),
                podpis(powod_stanu_kopii(stan) or "Dotknij, żeby ustawić kopię zapasową"),
            ], spacing=0, tight=True, expand=True),
            ft.TextButton("Zrób teraz", on_click=lambda e: zrob_kopie_teraz(page, po_zakonczeniu=po_kopii)),
        ], spacing=SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.CENTER),
    )


__all__ = [
    "baner_kopii",
    "czy_udostepniono",
    "linie_stanu_kopii",
    "moment_kopii",
    "opis_wieku_kopii",
    "powod_stanu_kopii",
    "tytul_stanu_kopii",
    "zrob_kopie_teraz",
]
