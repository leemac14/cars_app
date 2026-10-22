"""Usterki z przeglądu 22.10.2026 (klikacz na prawdziwej sesji Fleta i lektura kodu): pliki na
telefonie przez „Udostępnij”, zamykanie właściwego okna, wczytanie kopii bez interfejsu w wątku,
licznik z dystansu odporny na „inf”, błąd sieci opisany po ludzku."""

import asyncio
import os
import threading
import weakref
from types import SimpleNamespace

import flet as ft
import pytest

import db
import pomoce
import utils


@pytest.fixture
def aplikacja(baza, monkeypatch):
    """main.main() na stronie testowej; zadania z `run_task` zbierane, nie puszczane."""
    monkeypatch.setattr(ft, "run", lambda *args, **kwargs: None)
    import log
    import main

    monkeypatch.setattr(log, "wlacz", lambda: True)
    monkeypatch.setitem(utils.wyglad._OSTATNI_MOTYW, "nazwa", utils.wyglad._OSTATNI_MOTYW["nazwa"])
    strona = pomoce.zbuduj_strone()
    zadania = []
    monkeypatch.setattr(type(strona.page), "run_task", lambda self, f, *a, **k: zadania.append(f))
    pomoce.utworz_pojazd("Kopiowany")
    main.main(strona.page)
    return SimpleNamespace(strona=strona, page=strona.page, zadania=zadania)


def _okna_na_stronie(page):
    """Strona testowa nie montuje stosu okien — bez tego `show_dialog` nie ma czego odświeżyć."""
    page._dialogs._parent = weakref.ref(page)


# ======================================================= pliki na telefonie

@pytest.mark.parametrize("platforma, przez_udostepnij", [
    (ft.PagePlatform.ANDROID, True), (ft.PagePlatform.IOS, True), (ft.PagePlatform.WINDOWS, False),
])
def test_plik_na_telefonie_idzie_przez_udostepnij(aplikacja, monkeypatch, platforma, przez_udostepnij):
    """`page.platform` to enum — porównanie z napisem „android” nigdy nie trafiało i kalendarz,
    eksport i kopia na telefonie zawsze pytały „zapisz jako”."""
    udostepnione, zapisane = [], []

    async def udostepnij(pliki, **_k):
        udostepnione.extend(pliki)
        return SimpleNamespace(status=ft.ShareResultStatus.SUCCESS)

    async def zapisz(self, *a, **k):
        zapisane.append(k.get("file_name"))
        return "C:/Pobrane/terminy.ics"

    monkeypatch.setattr(aplikacja.page.share_service, "share_files", udostepnij)
    monkeypatch.setattr(ft.FilePicker, "save_file", zapisz)
    monkeypatch.setattr(utils, "pokaz_komunikat", lambda *a, **k: None)
    aplikacja.page.platform = platforma

    assert asyncio.run(aplikacja.page.zapisz_bajty_pliku("terminy.ics", b"BEGIN:VCALENDAR")) is True
    if przez_udostepnij:
        assert [os.path.basename(p.path) for p in udostepnione] == ["terminy.ics"] and zapisane == []
    else:
        assert udostepnione == [] and zapisane == ["terminy.ics"]


# ======================================================= zamykanie okien

def test_ukrycie_kolka_nie_zamyka_okna_otwartego_nad_nim(baza):
    strona = pomoce.zbuduj_strone()
    page = strona.page
    _okna_na_stronie(page)
    ladowanie = utils.pokaz_ladowanie(page, "Synchronizowanie danych...")
    konflikty = ft.AlertDialog(title=ft.Text("Edycja z dwóch urządzeń"),
                               actions=[ft.TextButton("Zostaw", on_click=lambda e: None)])
    utils.otworz_dialog(page, konflikty)

    utils.ukryj_ladowanie(page, ladowanie)
    assert ladowanie.open is False and konflikty.open is True, "zamyka się kółko, nie okno z wierzchu"

    utils.ukryj_ladowanie(page, ladowanie)
    assert konflikty.open is True, "drugie zamknięcie zamkniętego okna nie rusza innych"
    utils.zamknij_dialog(page, konflikty)
    assert konflikty.open is False


def test_synchronizacja_z_konfliktami_zostawia_okno_konfliktow(baza, monkeypatch):
    """Przycisk „Synchronizuj”: okno konfliktów otwiera się przed zdjęciem kółka ładowania."""
    strona = pomoce.zbuduj_strone()
    page = strona.page
    _okna_na_stronie(page)
    zadania = []
    monkeypatch.setattr(type(page), "run_task", lambda self, f, *a, **k: zadania.append(f))
    konflikty = ft.AlertDialog(title=ft.Text("Edycja z dwóch urządzeń"),
                               actions=[ft.TextButton("Zostaw", on_click=lambda e: None)])

    async def synchronizuj():
        utils.otworz_dialog(page, konflikty)

    przycisk = utils.przycisk_synchronizacji(page, synchronizuj, pokaz_czas=False)
    przycisk.on_click(None)
    asyncio.run(zadania[-1]())

    ladowanie = [d for d in page._dialogs.controls if d is not konflikty]
    assert konflikty.open is True and [d.open for d in ladowanie] == [False]


# ======================================================= wczytanie kopii

def _watki_interfejsu(monkeypatch):
    """Wątki, w których szły przejścia i komunikaty — interfejs ma iść w pętli (wątek główny)."""
    watki, komunikaty = [], []

    def przejdz(page, trasa):
        watki.append(threading.current_thread() is threading.main_thread())

    def komunikat(page, tekst, *a, **k):
        watki.append(threading.current_thread() is threading.main_thread())
        komunikaty.append(tekst)

    monkeypatch.setattr(utils, "przejdz", przejdz)
    monkeypatch.setattr(utils, "pokaz_komunikat", komunikat)
    monkeypatch.setattr(utils, "pokaz_ladowanie", lambda page, tekst="": None)
    monkeypatch.setattr(utils, "ukryj_ladowanie", lambda page, dlg: None)
    return watki, komunikaty


def test_wczytanie_kopii_rysuje_ekran_w_petli_nie_w_watku(aplikacja, monkeypatch):
    """Przebudowa ekranu z wątku importu ścigała się z pętlą Fleta — po wczytaniu kopii aplikacja
    potrafiła stanąć (cykl w drzewie kontrolek, RecursionError)."""
    kopia = db.wykonaj_kopie(wymus=True)["sciezka"]
    pomoce.utworz_pojazd("Dopisany po kopii")
    watki, komunikaty = _watki_interfejsu(monkeypatch)

    asyncio.run(aplikacja.page.wczytaj_kopie(kopia))

    assert komunikaty and komunikaty[-1].startswith("Pomyślnie wczytano bazę!"), komunikaty
    assert watki and all(watki), "przejście i komunikat poza pętlą Fleta"
    with db.polacz_baze() as conn:
        assert {w[0] for w in conn.execute("SELECT nazwa FROM samochody")} == {"Kopiowany"}


def test_zepsuta_kopia_wraca_do_starej_bazy_z_komunikatem_w_petli(aplikacja, monkeypatch, tmp_path):
    zepsuta = tmp_path / "kopia.db"
    zepsuta.write_bytes(b"to nie jest baza SQLite " * 40)
    watki, komunikaty = _watki_interfejsu(monkeypatch)

    asyncio.run(aplikacja.page.wczytaj_kopie(str(zepsuta)))

    assert komunikaty == ["Wybrany plik nie jest poprawną bazą danych SQLite. Przywrócono poprzednią bazę."]
    assert watki and all(watki)
    with db.polacz_baze() as conn:
        assert {w[0] for w in conn.execute("SELECT nazwa FROM samochody")} == {"Kopiowany"}


# ======================================================= tankowanie: licznik z dystansu

@pytest.fixture
def tankowanie(baza, monkeypatch):
    from views.formularze.tankowanie import FormularzTankowanieView

    ident = pomoce.utworz_pojazd("Licznik")
    strona = pomoce.zbuduj_strone()
    widok = FormularzTankowanieView(strona.page, pomoce.stan_aplikacji(ident["auto_id"], "Licznik"), None)
    widok._strona_testowa = strona
    for kontrolka in (widok.e_p, widok.e_dys, widok.k_trojka, widok.baner_ciagu):
        monkeypatch.setattr(kontrolka, "update", lambda *a, **k: None)
    return widok


@pytest.mark.parametrize("wpisane", ["inf", "1e400", "nan", "-", "abc"])
def test_dziwny_dystans_nie_wywraca_formularza(tankowanie, wpisane):
    tankowanie.e_p.value = "101000"
    tankowanie.e_dys.value = wpisane
    tankowanie.e_dys.on_change(None)
    assert tankowanie.e_p.value.isdigit(), "licznik zostaje liczbą"


def test_dystans_liczy_licznik_tym_samym_parserem_co_zapis(tankowanie):
    tankowanie.e_dys.value = "1 234,5"
    tankowanie.e_dys.on_change(None)
    assert int(tankowanie.e_p.value) == tankowanie.ostatni_prz_pola + 1234


# ======================================================= błąd sieci po ludzku

def test_blad_sieci_opisany_po_ludzku():
    import httpx

    for blad in (OSError(11001, "getaddrinfo failed"), httpx.ConnectError("[Errno 11001] getaddrinfo failed"),
                 ConnectionResetError(), TimeoutError()):
        opis = utils.opis_bledu_synchronizacji(blad)
        assert "połączenia z serwerem" in opis and "Errno" not in opis, blad
    assert utils.opis_bledu_synchronizacji(ValueError("Nieprawidłowy kod")) == "Nieprawidłowy kod"
