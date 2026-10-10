"""Plik pojazdu po stronie interfejsu: okno sekcji przed zapisem, zapis albo „Udostępnij”,
podgląd z pytaniem „zastąp czy dodaj” i wczytanie. Dane: db/plik_pojazdu.py."""

import asyncio
import os
import shutil
import tempfile
from datetime import datetime

import db
import flet as ft
import log

from .stale import FS, KOLOR_STATUS, RADIUS, SPACING, bezpieczna_nazwa_pliku
from .format import formatuj_rozmiar
from .typografia import etykieta, podpis, wartosc
from .dialogi import (
    otworz_dialog, pokaz_komunikat, pokaz_ladowanie, pokaz_ostrzezenie, przejdz, ukryj_ladowanie, zamknij_dialog,
)
from .komponenty import segmented_control
from .kopie import czy_udostepniono, moment_kopii


ZESTAWY_PLIKU_POJAZDU = [
    (db.ZESTAW_PELNY, "Pełny", ft.Icons.INVENTORY_2),
    (db.ZESTAW_DLA_KUPUJACEGO, "Dla kupującego", ft.Icons.SELL),
]
_GRUPY_SEKCJI = ((True, "Historia auta"), (False, "Prywatne i ustawienia"))
_FOLDER_TYMCZASOWY = "pliki_pojazdow"


def _na_telefonie(page):
    return getattr(page, "platform", None) in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS)


def _para(nazwa, tekst, opis=None):
    kolumna = [etykieta(nazwa), wartosc(tekst)]
    if opis:
        kolumna.append(podpis(opis))
    return ft.Column(kolumna, spacing=2, tight=True)


def _blok(ikona, kolor, linie):
    return ft.Container(
        padding=SPACING["md"], border_radius=RADIUS["md"], bgcolor=ft.Colors.with_opacity(0.10, kolor),
        content=ft.Column([
            ft.Row([ft.Icon(ikona, size=18, color=kolor), ft.Text(linie[0], size=FS["body"], expand=True)],
                   spacing=SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.START),
            *[podpis(linia) for linia in linie[1:]],
        ], spacing=SPACING["xs"], tight=True),
    )


def _tytul_okna(ikona, tekst):
    return ft.Row([ft.Icon(ikona, color=ft.Colors.PRIMARY), ft.Text(tekst, weight="bold", expand=True)],
                  spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)


# ------------------------------------------------------------------ zapis

def zapisz_pojazd_do_pliku(page: ft.Page, auto_id, zestaw=db.ZESTAW_PELNY):
    """Okno sekcji z zestawami „Pełny” i „Dla kupującego”, potem zapis (komputer) albo
    „Udostępnij” (telefon). `zestaw` — który zestaw jest zaznaczony na starcie."""
    if not auto_id:
        return

    async def _otworz_okno():
        dlg = pokaz_ladowanie(page, "Sprawdzanie danych pojazdu...")
        try:
            zawartosc = await asyncio.to_thread(db.zawartosc_pojazdu, auto_id)
        finally:
            ukryj_ladowanie(page, dlg)
        if not zawartosc:
            pokaz_komunikat(page, "Tego pojazdu nie ma już w aplikacji.", KOLOR_STATUS["error"])
            return
        pokaz_okno_zapisu(page, auto_id, zawartosc, zestaw)

    page.run_task(_otworz_okno)


def pokaz_okno_zapisu(page: ft.Page, auto_id, zawartosc, zestaw=db.ZESTAW_PELNY):
    """Przełącznik przy każdej sekcji z danymi; zestaw podświetla się, gdy wybór mu odpowiada."""
    sekcje = zawartosc["sekcje"]
    poczatkowe = set(db.sekcje_zestawu(zestaw))
    przelaczniki = {s["id"]: ft.Switch(value=s["id"] in poczatkowe) for s in sekcje}
    kontener_zestawu = ft.Container()
    # Ostatnio kliknięty zestaw wygrywa, gdy oba dają ten sam wybór (auto bez prywatnych sekcji).
    ostatni = {"zestaw": next((i for i, z in enumerate(ZESTAWY_PLIKU_POJAZDU) if z[0] == zestaw), 0)}

    def wybrane():
        return [klucz for klucz, p in przelaczniki.items() if p.value]

    def aktywny_zestaw():
        teraz = set(wybrane())
        kolejnosc = sorted(range(len(ZESTAWY_PLIKU_POJAZDU)), key=lambda i: i != ostatni["zestaw"])
        for i in kolejnosc:
            if teraz == set(przelaczniki) & set(db.sekcje_zestawu(ZESTAWY_PLIKU_POJAZDU[i][0])):
                return i
        return None

    def odswiez():
        kontener_zestawu.content = segmented_control(
            page, [(nazwa, i, ikona) for i, (_, nazwa, ikona) in enumerate(ZESTAWY_PLIKU_POJAZDU)],
            aktywny_zestaw(), wybierz_zestaw)

    def wybierz_zestaw(i):
        ostatni["zestaw"] = i
        sekcje_zestawu = set(db.sekcje_zestawu(ZESTAWY_PLIKU_POJAZDU[i][0]))
        for klucz, p in przelaczniki.items():
            p.value = klucz in sekcje_zestawu
        odswiez()
        page.update()

    def po_przelaczeniu(e):
        odswiez()
        page.update()

    wiersze = [
        podpis("Jeden plik ZIP: karta pojazdu, wybrane dane i ich zdjęcia. Wczytasz go w tej aplikacji na innym "
               "telefonie przez „Wczytaj pojazd z pliku”."),
        kontener_zestawu,
    ]
    for dla_kupujacego, tytul in _GRUPY_SEKCJI:
        w_grupie = [s for s in sekcje if s["dla_kupujacego"] == dla_kupujacego]
        if w_grupie:
            wiersze.append(etykieta(tytul))
        for s in w_grupie:
            przelaczniki[s["id"]].on_change = po_przelaczeniu
            wiersze.append(ft.Row([
                ft.Column([
                    ft.Text(s["tytul"], size=FS["body"]),
                    podpis(" · ".join(x for x in (s["podsumowanie"], s["opis"]) if x)),
                ], spacing=0, tight=True, expand=True),
                przelaczniki[s["id"]],
            ], spacing=SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.CENTER))
    wiersze.append(podpis("Kody współdzielenia i powiązania z chmurą nie trafiają do pliku — wczytany pojazd "
                          "będzie tylko na tamtym telefonie."))
    odswiez()

    dlg = ft.AlertDialog(
        modal=True, scrollable=True, shape=ft.RoundedRectangleBorder(radius=RADIUS["lg"]),
        title=_tytul_okna(ft.Icons.SAVE_ALT, f"Zapisz „{zawartosc['nazwa']}” do pliku"),
        content=ft.Container(width=360, content=ft.Column(wiersze, spacing=SPACING["md"], tight=True)),
    )

    def zapisz(e):
        zamknij_dialog(page, dlg)

        async def _zapisz():
            await _zapisz_plik(page, auto_id, zawartosc["nazwa"], wybrane())

        page.run_task(_zapisz)

    dlg.actions = [
        ft.TextButton("Anuluj", on_click=lambda e: zamknij_dialog(page, dlg)),
        ft.Button("Zapisz plik", icon=ft.Icons.SAVE_ALT, on_click=zapisz,
                  bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY),
    ]
    dlg.actions_alignment = ft.MainAxisAlignment.END
    otworz_dialog(page, dlg)
    return dlg


def _nowy_folder_tymczasowy():
    """Folder na plik do udostępnienia; poprzedni plik (udostępniony dawno temu) znika."""
    folder = os.path.join(tempfile.gettempdir(), _FOLDER_TYMCZASOWY)
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder, exist_ok=True)
    return folder


async def _zapisz_plik(page: ft.Page, auto_id, nazwa, sekcje):
    nazwa_pliku = f"pojazd_{bezpieczna_nazwa_pliku(nazwa)}_{datetime.now():%Y-%m-%d}.zip"
    dlg = pokaz_ladowanie(page, "Przygotowywanie pliku pojazdu...")
    try:
        sciezka = os.path.join(await asyncio.to_thread(_nowy_folder_tymczasowy), nazwa_pliku)
        wynik = await asyncio.to_thread(db.zapisz_plik_pojazdu, auto_id, sciezka, sekcje)
    except Exception as ex:
        log.blad("zapis pliku pojazdu")
        ukryj_ladowanie(page, dlg)
        pokaz_komunikat(page, f"Nie udało się przygotować pliku: {ex}", KOLOR_STATUS["error"])
        return None
    ukryj_ladowanie(page, dlg)

    if not await _oddaj_plik(page, sciezka, nazwa_pliku):
        return None
    tekst = (f"Zapisano „{wynik['nazwa']}”: {db.liczba_z_odmiana(wynik['wpisy'], 'wpis', 'wpisy', 'wpisów')}, "
             f"{db.liczba_z_odmiana(wynik['pliki'], 'plik', 'pliki', 'plików')} ({formatuj_rozmiar(wynik['rozmiar'])}).")
    if wynik["brakujace"]:
        tekst += (f" {db.liczba_z_odmiana(wynik['brakujace'], 'pliku', 'plików', 'plików').capitalize()} "
                  "nie ma na tym urządzeniu — wpisy zapisano bez nich.")
        pokaz_komunikat(page, tekst, KOLOR_STATUS["warning"])
    else:
        pokaz_komunikat(page, tekst)
    return wynik


async def _oddaj_plik(page: ft.Page, sciezka, nazwa_pliku):
    """Telefon: systemowe „Udostępnij” (Dysk, poczta, komunikator); komputer: okno zapisu.
    Zwraca True, gdy plik gdzieś trafił."""
    serwis = getattr(page, "share_service", None)
    if _na_telefonie(page) and serwis is not None:
        try:
            return czy_udostepniono(await serwis.share_files([ft.ShareFile.from_path(sciezka, name=nazwa_pliku)]))
        except Exception:
            log.polkniety("udostępnianie pliku pojazdu przez system")
    picker = getattr(page, "zalacznik_picker", None)
    if picker is None:
        pokaz_komunikat(page, "Zapis pliku jest niedostępny w tej wersji aplikacji.", KOLOR_STATUS["error"])
        return False
    try:
        if _na_telefonie(page):
            with open(sciezka, "rb") as plik:
                return bool(await picker.save_file(file_name=nazwa_pliku, src_bytes=plik.read()))
        cel = await picker.save_file(file_name=nazwa_pliku)
        if cel:
            await asyncio.to_thread(shutil.copyfile, sciezka, cel)
        return bool(cel)
    except Exception as ex:
        log.polkniety("zapis pliku pojazdu w wybranym miejscu")
        pokaz_komunikat(page, f"Błąd zapisu: {ex}", KOLOR_STATUS["error"])
        return False


# ---------------------------------------------------------------- wczytanie

def wczytaj_pojazd_z_pliku(page: ft.Page, state):
    """„Wczytaj pojazd z pliku”: wybór pliku, podgląd i pytanie — dopiero potem zapis."""
    async def _wybierz():
        picker = getattr(page, "zalacznik_picker", None)
        if picker is None:
            pokaz_komunikat(page, "Wybór pliku jest niedostępny w tej wersji aplikacji.", KOLOR_STATUS["error"])
            return
        try:
            pliki = await picker.pick_files(file_type=ft.FilePickerFileType.ANY)
        except Exception as ex:
            log.polkniety("wybór pliku pojazdu")
            pokaz_komunikat(page, f"Błąd otwierania menedżera: {ex}", KOLOR_STATUS["error"])
            return
        if pliki:
            zapytaj_o_wczytanie_pojazdu(page, state, pliki[0].path)

    page.run_task(_wybierz)


def zapytaj_o_wczytanie_pojazdu(page: ft.Page, state, sciezka):
    """Sprawdza plik w tle i pokazuje podgląd. Kopia bazy idzie do `page.zapytaj_o_import`
    (main.py), więc obie drogi wyboru pliku rozumieją oba rodzaje archiwum."""
    if not sciezka or not os.path.exists(sciezka):
        pokaz_komunikat(page, "Nie można odczytać wybranego pliku.", KOLOR_STATUS["error"])
        return

    async def _sprawdz():
        dlg = pokaz_ladowanie(page, "Sprawdzanie pliku...")
        try:
            podglad = await asyncio.to_thread(db.podglad_pliku_pojazdu, sciezka)
        finally:
            ukryj_ladowanie(page, dlg)
        if podglad["rodzaj"] == "kopia":
            przekaz = getattr(page, "zapytaj_o_import", None)
            if callable(przekaz):
                przekaz(sciezka)
            else:
                pokaz_ostrzezenie(page, "To kopia zapasowa bazy",
                                  "Wczytasz ją przez „Wczytaj kopię bazy” w menu bocznym.")
            return
        if podglad["blad"]:
            pokaz_ostrzezenie(page, "Nie da się wczytać pojazdu", podglad["blad"])
            return
        pokaz_podglad_pojazdu(page, state, sciezka, podglad)

    page.run_task(_sprawdz)


def _moment(tekst):
    try:
        return datetime.fromisoformat(tekst).astimezone().replace(tzinfo=None)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def pokaz_podglad_pojazdu(page: ft.Page, state, sciezka, podglad):
    """„Wczytać pojazd?” z zawartością pliku; gdy auto już jest — „Zastąp” albo „Dodaj obok”."""
    wiersze = [podpis(podglad["plik"])]
    szczegoly = [podglad["opis_auta"], podglad["nr_rej"], f"VIN {podglad['vin']}" if podglad["vin"] else ""]
    wiersze.append(_para("Pojazd", podglad["nazwa"], " · ".join(x for x in szczegoly if x) or None))
    moment = _moment(podglad["utworzono"])
    wiersze.append(_para("Zapisany", moment_kopii(moment) if moment else "nieznana data",
                         f"Wersja aplikacji {podglad['aplikacja']}" if podglad["aplikacja"] else None))

    sekcje = [ft.Row([ft.Text(s["tytul"], size=FS["body"], expand=True), podpis(s["podsumowanie"])],
                     spacing=SPACING["sm"]) for s in podglad["sekcje"]]
    wiersze.append(ft.Column([etykieta("W pliku"), *(sekcje or [wartosc("sama karta pojazdu")])],
                             spacing=4, tight=True))
    wiersze.append(_para(
        "Zdjęcia i pliki",
        f"{db.liczba_z_odmiana(podglad['pliki'], 'plik', 'pliki', 'plików')} ({formatuj_rozmiar(podglad['rozmiar'])})"
        if podglad["pliki"] else "brak"))
    if podglad["sprzedany"]:
        wiersze.append(_blok(ft.Icons.INVENTORY, KOLOR_STATUS["info"],
                             ["W pliku auto jest sprzedane — trafi do Archiwum pojazdów."]))
    if podglad["uwagi"]:
        wiersze.append(_blok(ft.Icons.WARNING_AMBER, KOLOR_STATUS["warning"], podglad["uwagi"]))

    ten_sam = podglad["ten_sam"]
    if ten_sam:
        linie = [f"W aplikacji jest już „{ten_sam['nazwa']}” — ten sam {ten_sam['po_czym']}.",
                 "Zastąp: obecny trafi do kosza, skąd go przywrócisz. Dodaj obok: zostaną oba."]
        if ten_sam["wspolny"]:
            linie.append("Obecny jest współdzielony — wczytany będzie tylko na tym telefonie.")
        wiersze.append(_blok(ft.Icons.CONTENT_COPY, KOLOR_STATUS["info"], linie))
    wiersze.append(podpis("Pojazd wczyta się jako nowy, tylko na tym telefonie; dane innych aut zostają bez zmian."))

    dlg = ft.AlertDialog(
        modal=True, scrollable=True, shape=ft.RoundedRectangleBorder(radius=RADIUS["lg"]),
        title=_tytul_okna(ft.Icons.DRIVE_FOLDER_UPLOAD, "Wczytać pojazd?"),
        content=ft.Container(width=340, content=ft.Column(wiersze, spacing=SPACING["md"], tight=True)),
    )

    def wczytaj(zastap_id):
        def _klik(e):
            zamknij_dialog(page, dlg)

            async def _wczytaj():
                await _wczytaj_plik(page, state, sciezka, zastap_id)

            page.run_task(_wczytaj)
        return _klik

    dlg.actions = [ft.TextButton("Anuluj", on_click=lambda e: zamknij_dialog(page, dlg))]
    if ten_sam:
        dlg.actions += [
            ft.TextButton("Dodaj obok", on_click=wczytaj(None)),
            ft.TextButton("Zastąp", on_click=wczytaj(ten_sam["id"]),
                          style=ft.ButtonStyle(color=KOLOR_STATUS["destructive"])),
        ]
    else:
        dlg.actions.append(ft.TextButton("Wczytaj", on_click=wczytaj(None)))
    dlg.actions_alignment = ft.MainAxisAlignment.END
    otworz_dialog(page, dlg)
    return dlg


async def _wczytaj_plik(page: ft.Page, state, sciezka, zastap_id):
    dlg = pokaz_ladowanie(page, "Wczytywanie pojazdu...")
    try:
        wynik = await asyncio.to_thread(db.wczytaj_plik_pojazdu, sciezka, zastap_id)
    except db.BladPlikuPojazdu as ex:
        ukryj_ladowanie(page, dlg)
        pokaz_ostrzezenie(page, "Nie da się wczytać pojazdu", str(ex))
        return None
    except Exception as ex:
        log.blad("wczytanie pliku pojazdu")
        ukryj_ladowanie(page, dlg)
        pokaz_komunikat(page, f"Nie udało się wczytać pojazdu: {ex}", KOLOR_STATUS["error"])
        return None
    ukryj_ladowanie(page, dlg)

    tekst = f"Wczytano pojazd „{wynik['nazwa']}”."
    if wynik["pominiete"]:
        tekst += f" Bez {db.liczba_z_odmiana(wynik['pominiete'], 'pliku', 'plików', 'plików')}, których zabrakło w pliku."
    if wynik["kosz_id"]:
        tekst += " Poprzedni jest w koszu."
    if wynik["status"] == db.STATUS_POJAZDU_SPRZEDANY:
        if zastap_id and state.auto_id == zastap_id:
            state.auto_id = None
            db.zainicjuj_domyslne_auto(state)
        przejdz(page, "/archiwum")
        tekst += " Jest w Archiwum pojazdów, bo w pliku był sprzedany."
    else:
        state.auto_id = wynik["auto_id"]
        db.zainicjuj_domyslne_auto(state)
        przejdz(page, "/")
    pokaz_komunikat(page, tekst)
    return wynik


__all__ = [
    "ZESTAWY_PLIKU_POJAZDU",
    "pokaz_okno_zapisu",
    "pokaz_podglad_pojazdu",
    "wczytaj_pojazd_z_pliku",
    "zapisz_pojazd_do_pliku",
    "zapytaj_o_wczytanie_pojazdu",
]
