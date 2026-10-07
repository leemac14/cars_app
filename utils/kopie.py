"""Kopia zapasowa po stronie interfejsu: baner na kokpicie, „Zrób teraz” i opisy
stanu wspólne dla kokpitu, dzwonka i Ustawień. Dane i sama kopia: db/kopie.py."""

import asyncio
import os
from datetime import datetime

import db
import flet as ft
import log

from .stale import FS, KOLOR_STATUS, RADIUS, SPACING
from .format import formatuj_date_pl, formatuj_dni, formatuj_rozmiar
from .typografia import etykieta, podpis, wartosc
from .dialogi import (
    otworz_dialog, pokaz_komunikat, pokaz_ladowanie, pokaz_ostrzezenie, przejdz, ukryj_ladowanie,
    zamknij_dialog,
)


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


# ============================================================================
# PODGLĄD KOPII PRZED WCZYTANIEM
# ============================================================================
# Okno z datą, zawartością i stanem kopii, zanim cokolwiek zostanie nadpisane — dla
# pliku wybranego ręcznie i z listy w Ustawieniach. Dane: db.podglad_kopii
# (db/manifest_kopii.py).

# Nazwa typu wpisu w podglądzie, w odmianie jeden / kilka / wiele. Każda tabela
# z db.KOSZ_TABELE_LICZONE musi tu być — pilnuje tego tests/test_manifest_kopii.py.
NAZWY_WPISOW_W_PODGLADZIE = {
    "tankowania": ("tankowanie", "tankowania", "tankowań"),
    "historia": ("wpis serwisowy", "wpisy serwisowe", "wpisów serwisowych"),
    "wizyty": ("wizyta w warsztacie", "wizyty w warsztacie", "wizyt w warsztacie"),
    "inne_koszty": ("inny koszt", "inne koszty", "innych kosztów"),
    "zestawy_opon": ("komplet opon", "komplety opon", "kompletów opon"),
    "magazyn_czesci": ("część w magazynie", "części w magazynie", "części w magazynie"),
    "zdjecia_karoserii": ("zdjęcie karoserii", "zdjęcia karoserii", "zdjęć karoserii"),
    "odczyty_przebiegu": ("odczyt licznika", "odczyty licznika", "odczytów licznika"),
    "do_zrobienia": ("zadanie do zrobienia", "zadania do zrobienia", "zadań do zrobienia"),
    "szkice_wpisow": ("szkic do wpisania", "szkice do wpisania", "szkiców do wpisania"),
    "przejazdy": ("przejazd w ewidencji", "przejazdy w ewidencji", "przejazdów w ewidencji"),
}


def _wpisy_tekstem(liczba):
    return db.liczba_z_odmiana(liczba, "wpis", "wpisy", "wpisów")


def _rozbicie_wpisow(wg_tabel):
    """„120 tankowań · 48 wpisów serwisowych” — tylko typy, które coś mają."""
    return " · ".join(
        db.liczba_z_odmiana(liczba, *NAZWY_WPISOW_W_PODGLADZIE[tabela])
        for tabela, liczba in wg_tabel.items()
        if liczba and tabela in NAZWY_WPISOW_W_PODGLADZIE
    )


def _moment_z_iso(tekst):
    """Moment zapisany w ISO (z strefą albo bez) jako czas lokalny — albo None."""
    try:
        return datetime.fromisoformat(tekst).astimezone().replace(tzinfo=None)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _wiersz_podgladu(nazwa, tekst, opis=None, kolor=None):
    kolumna = [etykieta(nazwa), wartosc(tekst, color=kolor) if kolor else wartosc(tekst)]
    if opis:
        kolumna.append(podpis(opis))
    return ft.Column(kolumna, spacing=2, tight=True)


def _wiersz_z_ikona(ikona, kolor, tekst):
    return ft.Row([
        ft.Icon(ikona, size=18, color=kolor),
        ft.Text(tekst, size=FS["body"], color=kolor, expand=True),
    ], spacing=SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.START)


def _opis_schematu(podglad):
    schemat, aplikacji = podglad["schemat"], podglad["schemat_aplikacji"]
    if schemat is None:
        return "Nie udało się odczytać numeru wersji."
    if aplikacji and schemat < aplikacji:
        return f"Starsza niż ta aplikacja ({aplikacji}) — przy wczytaniu zostanie zaktualizowana."
    return "Taka sama jak w tej aplikacji."


def _wiersze_zawartosci(podglad):
    """Wiersze „co jest w kopii” — bez tych, których kopia nie ma jak wypełnić."""
    wiersze = []

    moment = _moment_z_iso(podglad["utworzono"])
    wiersze.append(_wiersz_podgladu(
        "Z dnia", moment_kopii(moment) if moment else "nieznana",
        None if podglad["data_z_manifestu"] or moment is None
        else "Data pliku — ta kopia nie ma manifestu.",
    ))
    wiersze.append(_wiersz_podgladu(
        "Wersja schematu bazy",
        "nieznana" if podglad["schemat"] is None else str(podglad["schemat"]),
        _opis_schematu(podglad),
    ))
    wiersze.append(_wiersz_podgladu(
        "Wpisy", _wpisy_tekstem(podglad["wpisy"]), _rozbicie_wpisow(podglad["wpisy_wg_tabel"]) or None,
    ))

    pojazdy = [ft.Column([
        wartosc(p["nazwa"] or "Bez nazwy", size=FS["body"]),
        podpis(_wpisy_tekstem(p["wpisy"])),
    ], spacing=0, tight=True) for p in podglad["pojazdy"]]
    wiersze.append(ft.Column([etykieta("Pojazdy"), *(pojazdy or [wartosc("brak")])], spacing=4, tight=True))

    if podglad["ostatni_wpis"]:
        try:
            ostatni = formatuj_date_pl(datetime.strptime(podglad["ostatni_wpis"], "%Y-%m-%d").date())
        except ValueError:
            ostatni = None
        if ostatni:
            wiersze.append(_wiersz_podgladu("Ostatni wpis", ostatni))

    zalaczniki = podglad["zalaczniki"]
    if zalaczniki is None:
        wiersze.append(_wiersz_podgladu("Załączniki", "brak", "Sam plik bazy (dawny format kopii) — bez zdjęć."))
    elif zalaczniki["liczba"]:
        wiersze.append(_wiersz_podgladu(
            "Załączniki",
            f"{db.liczba_z_odmiana(zalaczniki['liczba'], 'plik', 'pliki', 'plików')} ({formatuj_rozmiar(zalaczniki['rozmiar'])})",
        ))
    else:
        wiersze.append(_wiersz_podgladu("Załączniki", "brak"))
    return wiersze


def _wiersze_porownania(podglad):
    """Co przepadnie: stan bazy, którą import zastąpi, i różnica we wpisach."""
    obecna = podglad["obecna"]
    if obecna is None:
        return []
    wiersze = [_wiersz_podgladu(
        "W aplikacji teraz",
        f"{_wpisy_tekstem(obecna['wpisy'])}, {db.liczba_z_odmiana(obecna['pojazdy'], 'pojazd', 'pojazdy', 'pojazdów')}",
        "Zostaną zastąpione zawartością kopii.",
    )]
    roznica = podglad["wpisy"] - obecna["wpisy"]
    if roznica < 0:
        wiersze.append(_wiersz_z_ikona(
            ft.Icons.WARNING_AMBER, KOLOR_STATUS["warning"],
            f"Kopia ma o {_wpisy_tekstem(-roznica)} mniej niż obecna baza.",
        ))
    return wiersze


def _blok_sprawdzenia(podglad):
    """Czerwone uwagi, gdy kopia nie zgadza się z manifestem; zielony znaczek, gdy
    się zgadza; spokojna notka, gdy manifestu nie ma (kopia sprzed niego)."""
    if podglad["uwagi"]:
        kolor = KOLOR_STATUS["error"]
        return ft.Container(
            padding=SPACING["md"], border_radius=RADIUS["md"],
            bgcolor=ft.Colors.with_opacity(0.10, kolor),
            content=ft.Column([
                _wiersz_z_ikona(ft.Icons.ERROR_OUTLINE, kolor, "Ta kopia budzi wątpliwości"),
                *[ft.Text(uwaga, size=FS["body"]) for uwaga in podglad["uwagi"]],
            ], spacing=SPACING["sm"], tight=True),
        )
    if podglad["manifest"]:
        return _wiersz_z_ikona(
            ft.Icons.CHECK_CIRCLE, KOLOR_STATUS["ok"],
            "Suma kontrolna i załączniki zgadzają się z manifestem kopii.",
        )
    return _wiersz_z_ikona(
        ft.Icons.INFO_OUTLINE, KOLOR_STATUS["neutral"],
        "Brak manifestu z sumą kontrolną — kopia z wcześniejszej wersji aplikacji, "
        "więc nie da się sprawdzić, czy jest cała.",
    )


def pokaz_podglad_kopii(page: ft.Page, podglad, po_potwierdzeniu):
    """Modalne „Wczytać tę kopię?” z zawartością (db.podglad_kopii). Niezgodność z
    manifestem albo nieczytelny plik → czerwone uwagi i „Wczytaj mimo to” (świadomy
    krok, nie blokada). Kopia z nowszej wersji tu nie trafia (osobne okno odmowy)."""
    z_uwagami = bool(podglad["uwagi"])
    kolor_tytulu = KOLOR_STATUS["warning"] if z_uwagami else ft.Colors.PRIMARY

    wiersze = [podpis(podglad["plik"])]
    if podglad["nieczytelna"]:
        wiersze += [
            _blok_sprawdzenia(podglad),
            podpis("Jeśli mimo to spróbujesz ją wczytać, a się nie uda, aplikacja przywróci obecną bazę."),
        ]
    else:
        wiersze += _wiersze_zawartosci(podglad)
        wiersze += _wiersze_porownania(podglad)
        wiersze.append(_blok_sprawdzenia(podglad))
        wiersze.append(podpis(
            "Obecna baza zostanie odłożona jako .bak; ustawienia kopii zapasowej (folder, rytm) zostają bez zmian."
        ))

    dlg = ft.AlertDialog(
        modal=True, scrollable=True,
        shape=ft.RoundedRectangleBorder(radius=RADIUS["lg"]),
        title=ft.Row([
            ft.Icon(ft.Icons.WARNING_AMBER if z_uwagami else ft.Icons.SETTINGS_BACKUP_RESTORE, color=kolor_tytulu),
            ft.Text("Wczytać tę kopię?", weight="bold", expand=True),
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        content=ft.Container(width=340, content=ft.Column(wiersze, spacing=SPACING["md"], tight=True)),
    )

    def anuluj(e):
        zamknij_dialog(page, dlg)

    def wczytaj(e):
        zamknij_dialog(page, dlg)
        po_potwierdzeniu()

    dlg.actions = [
        ft.TextButton("Anuluj", on_click=anuluj),
        ft.TextButton(
            "Wczytaj mimo to" if z_uwagami else "Wczytaj", on_click=wczytaj,
            style=ft.ButtonStyle(color=KOLOR_STATUS["destructive"]) if z_uwagami else None,
        ),
    ]
    dlg.actions_alignment = ft.MainAxisAlignment.END
    otworz_dialog(page, dlg)
    return dlg


def zapytaj_o_wczytanie_kopii(page: ft.Page, sciezka, po_potwierdzeniu):
    """Sprawdza kopię w tle i pyta „wczytać?” — przed jakimkolwiek nadpisaniem.
    `po_potwierdzeniu()` rusza dopiero po „Wczytaj”. Kopia z nowszej wersji
    aplikacji dostaje odmowę zamiast pytania (ta sama co w `wykonaj_import`)."""
    if not sciezka or not os.path.exists(sciezka):
        pokaz_komunikat(page, "Nie można odczytać wybranego pliku.", KOLOR_STATUS["error"])
        return

    async def _przygotuj():
        dlg = pokaz_ladowanie(page, "Sprawdzanie kopii...")
        try:
            podglad = await asyncio.to_thread(db.podglad_kopii, sciezka)
        finally:
            ukryj_ladowanie(page, dlg)
        if podglad["odmowa"]:
            log.ostrzezenie(f"Odmowa wczytania kopii: {podglad['odmowa']}")
            pokaz_ostrzezenie(page, "Kopia z nowszej wersji aplikacji", podglad["odmowa"])
            return
        pokaz_podglad_kopii(page, podglad, po_potwierdzeniu)

    page.run_task(_przygotuj)


__all__ = [
    "NAZWY_WPISOW_W_PODGLADZIE",
    "baner_kopii",
    "czy_udostepniono",
    "linie_stanu_kopii",
    "moment_kopii",
    "opis_wieku_kopii",
    "pokaz_podglad_kopii",
    "powod_stanu_kopii",
    "tytul_stanu_kopii",
    "zapytaj_o_wczytanie_kopii",
    "zrob_kopie_teraz",
]
