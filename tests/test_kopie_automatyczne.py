"""Automatyczna kopia zapasowa (db/kopie.py, utils/kopie.py, main.py).

Kopia co N dni do wskazanego folderu z rotacją do K ostatnich. Starsze kopie
znikają dopiero po sprawdzeniu nowej, rotacja rusza tylko własne pliki,
zepsuta baza nie wypycha dobrych kopii. Ostrzeżenie na kokpicie i w dzwonku
wyłącznie przy kopii zaległej. Ustawienia kopii należą do urządzenia
i przeżywają wczytanie kopii. Start aplikacji i powrót z tła robią kopię,
„Wczytaj” z listy w Ustawieniach przywraca ją tą samą drogą co plik."""

import asyncio
import os
import sqlite3
import zipfile
from datetime import datetime, timedelta
from types import SimpleNamespace

import flet as ft
import pytest

import db
import pomoce
import utils


# ======================================================= pomocnicze

def _auto(nazwa="Kopiowany"):
    return pomoce.utworz_pojazd(nazwa)["auto_id"]


def _moment(dni_temu):
    return (datetime.now() - timedelta(days=dni_temu)).isoformat(timespec="seconds")


def _stara_kopia(folder, dni_temu, tresc=b"stara kopia"):
    """Plik o nazwie kopii automatycznej sprzed `dni_temu` dni."""
    os.makedirs(folder, exist_ok=True)
    moment = datetime.now() - timedelta(days=dni_temu)
    sciezka = os.path.join(folder, moment.strftime("flota_kopia_%Y-%m-%d_%H%M%S.zip"))
    with open(sciezka, "wb") as plik:
        plik.write(tresc)
    return sciezka


def _teksty(korzen):
    wynik, do_odwiedzenia = [], [korzen]
    while do_odwiedzenia:
        kontrolka = do_odwiedzenia.pop()
        for pole in ("value", "label", "tooltip"):
            wartosc = getattr(kontrolka, pole, None)
            if isinstance(wartosc, str):
                wynik.append(wartosc)
        for pole in ("controls", "content", "title", "subtitle", "leading", "trailing", "actions",
                     "appbar", "floating_action_button"):
            dziecko = getattr(kontrolka, pole, None)
            if isinstance(dziecko, (list, tuple)):
                do_odwiedzenia.extend(d for d in dziecko if isinstance(d, ft.Control))
            elif isinstance(dziecko, ft.Control):
                do_odwiedzenia.append(dziecko)
    return wynik


def _ekran_glowny(auto_id):
    stan = pomoce.stan_aplikacji(auto_id, "Kopiowany")
    stan.zakladka = 0
    return pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(), stan)


def _zepsuj_folder():
    """Folder kopii wskazujący na PLIK — zapis musi się nie udać na każdym systemie
    (testy chodzą jako root, więc odebranie uprawnień niczego by nie zablokowało)."""
    plik = os.path.join(db.STORAGE_PATH, "to_nie_folder")
    with open(plik, "wb") as f:
        f.write(b"x")
    db.zapisz_folder_kopii(plik)
    return plik


# ======================================================= kiedy kopia

def test_pusta_instalacja_nie_ma_czego_chronic(baza):
    stan = db.stan_kopii_zapasowej()
    assert not stan["ma_dane"] and not stan["nalezna"] and not stan["zalegla"]

    wynik = db.wykonaj_kopie()
    assert wynik["pominieta"] and not wynik["ok"]
    assert not os.path.exists(db.domyslny_folder_kopii()), "żadnego folderu dla pustej bazy"


def test_pierwszy_start_z_danymi_robi_kopie_od_razu(baza):
    _auto()
    stan = db.stan_kopii_zapasowej()
    assert stan["nalezna"] and stan["wlaczona"] and stan["co_dni"] == 7 and stan["ile"] == 5
    assert not stan["zalegla"], "kopia zaraz się zrobi — ostrzeżenie mignęłoby tylko na chwilę"

    wynik = db.wykonaj_kopie()
    assert wynik["ok"] and wynik["blad"] is None
    assert os.path.dirname(wynik["sciezka"]) == db.domyslny_folder_kopii() == os.path.join(db.STORAGE_PATH, "kopie")
    assert os.path.basename(wynik["sciezka"]).startswith("flota_kopia_")

    po = db.stan_kopii_zapasowej()
    assert po["dni"] == 0 and po["rodzaj_ostatniej"] == "automatyczna"
    assert not po["nalezna"] and not po["zalegla"]
    assert db.wykonaj_kopie()["pominieta"], "druga kopia tego samego dnia — dopiero za N dni"


@pytest.mark.parametrize("dni_temu, co_dni, nalezna", [
    (6, 7, False), (7, 7, True), (30, 7, True), (2, 3, False), (3, 3, True), (0, 1, False), (1, 1, True),
])
def test_kopia_nalezna_po_n_dniach(baza, dni_temu, co_dni, nalezna):
    _auto()
    db.zapisz_kopie_co_dni(co_dni)
    db.zapisz_ustawienie(db.KLUCZ_KOPIA_OSTATNIA_AUTO, _moment(dni_temu))
    assert db.stan_kopii_zapasowej()["nalezna"] is nalezna
    assert db.wykonaj_kopie()["pominieta"] is (not nalezna)


def test_data_kopii_z_przyszlosci_nie_wstrzymuje_kopii(baza):
    """Zegar telefonu cofnięty po kopii: data „za tydzień” nie może oznaczać,
    że następna kopia ruszy dopiero za dwa tygodnie."""
    _auto()
    db.zapisz_ustawienie(db.KLUCZ_KOPIA_OSTATNIA_AUTO, _moment(-7))
    assert db.stan_kopii_zapasowej()["nalezna"]


def test_wylaczona_kopia_nie_rusza_sama_ale_przypomina(baza):
    _auto()
    db.zapisz_kopie_automatyczna(False)
    stan = db.stan_kopii_zapasowej()
    assert not stan["nalezna"] and stan["zalegla"], "brak jakiejkolwiek kopii przy wyłączonej automatycznej"
    assert db.wykonaj_kopie()["pominieta"]

    db.zapisz_ustawienie(db.KLUCZ_KOPIA_OSTATNIA_RECZNA, _moment(3))
    assert not db.stan_kopii_zapasowej()["zalegla"], "3 dni przy rytmie 7 — jeszcze nie"
    db.zapisz_ustawienie(db.KLUCZ_KOPIA_OSTATNIA_RECZNA, _moment(8))
    stan = db.stan_kopii_zapasowej()
    assert stan["zalegla"] and stan["dni"] == 8
    assert utils.linie_stanu_kopii(stan) == ["Ostatnia kopia: 8 dni temu", "Automatyczna kopia jest wyłączona"]

    assert db.wykonaj_kopie(wymus=True)["ok"], "„Zrób teraz” działa także przy wyłączonej"
    assert not db.stan_kopii_zapasowej()["zalegla"]


def test_kopia_reczna_gasi_ostrzezenie_ale_nie_przesuwa_harmonogramu(baza):
    _auto()
    db.zapisz_ustawienie(db.KLUCZ_KOPIA_OSTATNIA_AUTO, _moment(20))
    db.zapisz_ustawienie(db.KLUCZ_KOPIA_BLAD, "brak dostępu do folderu")
    assert db.stan_kopii_zapasowej()["zalegla"]

    db.zanotuj_kopie_reczna()
    stan = db.stan_kopii_zapasowej()
    assert not stan["zalegla"] and stan["dni"] == 0 and stan["rodzaj_ostatniej"] == "ręczna"
    assert stan["nalezna"], "rotacja w folderze idzie swoim rytmem"


def test_dwie_kopie_naraz_nie_pisza_jednoczesnie(baza):
    _auto()
    assert db.kopie._ZAMEK_KOPII.acquire(blocking=False)
    try:
        assert db.kopia_w_toku()
        wynik = db.wykonaj_kopie(wymus=True)
        assert wynik["w_toku"] and not wynik["ok"] and wynik["blad"] is None
    finally:
        db.kopie._ZAMEK_KOPII.release()
    assert not os.path.exists(db.domyslny_folder_kopii())


# ======================================================= archiwum

def test_archiwum_to_ta_sama_kopia_co_reczna(baza):
    """Kopia automatyczna to zwykłe archiwum „Wczytaj kopię bazy”: baza,
    załączniki i kosz, z ponowną walidacją wersji schematu przy wczytaniu."""
    _auto()
    with open(os.path.join(db.FOLDER_KOSZ, "w_koszu.jpg"), "wb") as f:
        f.write(b"zdjecie z kosza")

    wynik = db.wykonaj_kopie()
    with zipfile.ZipFile(wynik["sciezka"]) as zf:
        nazwy = set(zf.namelist())
        assert zf.getinfo("kosz_zalaczniki/w_koszu.jpg").compress_type == zipfile.ZIP_STORED, \
            "zdjęcia bez ponownej kompresji"
    assert "flota_zadania.db" in nazwy
    assert "zalaczniki/Kopiowany_glowne.jpg" in nazwy and "kosz_zalaczniki/w_koszu.jpg" in nazwy

    with zipfile.ZipFile(__import__("io").BytesIO(db.przygotuj_zip_kopii())) as reczna:
        assert set(reczna.namelist()) == nazwy
    assert db.sprawdz_archiwum_kopii(wynik["sciezka"]) == (True, "")
    assert db.sprawdz_kopie_przed_wczytaniem(wynik["sciezka"])[0]


def test_uszkodzone_archiwum_nie_przechodzi_sprawdzenia(baza, tmp_path):
    _auto()
    wynik = db.wykonaj_kopie()
    dane = bytearray(open(wynik["sciezka"], "rb").read())
    srodek = len(dane) // 3
    dane[srodek:srodek + 64] = b"\x00" * 64
    zepsuta = tmp_path / "zepsuta.zip"
    zepsuta.write_bytes(bytes(dane))
    poprawne, powod = db.sprawdz_archiwum_kopii(str(zepsuta))
    assert not poprawne and powod

    bez_bazy = tmp_path / "bez_bazy.zip"
    with zipfile.ZipFile(bez_bazy, "w") as zf:
        zf.writestr("zalaczniki/a.jpg", b"a")
    assert db.sprawdz_archiwum_kopii(str(bez_bazy)) == (False, "w archiwum brakuje pliku bazy")


# ======================================================= rotacja

def test_rotacja_zostawia_k_najnowszych_i_nie_rusza_cudzych_plikow(baza):
    _auto()
    folder = db.domyslny_folder_kopii()
    stare = [_stara_kopia(folder, dni) for dni in (40, 30, 20, 10, 5)]
    obce = {
        "kopia_baza.zip": b"reczna",
        "notatki.txt": b"moje",
        "flota_kopia_zla_nazwa.zip": b"?",
        "flota_kopia_2026-13-45_999999.zip": b"zla data",
    }
    for nazwa, tresc in obce.items():
        with open(os.path.join(folder, nazwa), "wb") as f:
            f.write(tresc)
    podfolder = os.path.join(folder, "archiwum")
    zagniezdzona = _stara_kopia(podfolder, 100)
    db.zapisz_ile_kopii(3)

    wynik = db.wykonaj_kopie(wymus=True)

    assert wynik["ok"] and wynik["usuniete"] == 3
    zostaly = [k["sciezka"] for k in db.lista_kopii(folder)]
    assert zostaly == [wynik["sciezka"], stare[4], stare[3]], "nowa i dwie najnowsze, od najnowszej"
    for nazwa, tresc in obce.items():
        assert open(os.path.join(folder, nazwa), "rb").read() == tresc, f"{nazwa} nie jest kopią automatyczną"
    assert os.path.exists(zagniezdzona), "rotacja nie schodzi do podfolderów"


def test_resztki_przerwanej_kopii_znikaja_przy_nastepnej(baza):
    _auto()
    folder = db.domyslny_folder_kopii()
    resztka = _stara_kopia(folder, 3) + db.KONCOWKA_CZESCI_KOPII
    with open(resztka, "wb") as f:
        f.write(b"urwane w pol")
    obca = os.path.join(folder, "film.mp4" + db.KONCOWKA_CZESCI_KOPII)
    with open(obca, "wb") as f:
        f.write(b"cudze")

    assert db.wykonaj_kopie(wymus=True)["ok"]
    assert not os.path.exists(resztka) and os.path.exists(obca)
    assert not [n for n in os.listdir(folder) if n.endswith(db.KONCOWKA_CZESCI_KOPII) and n.startswith("flota_kopia_")]


def test_zepsuta_baza_nie_wypycha_dobrych_kopii(baza):
    """Najważniejsza obietnica rotacji: kopia, która nie przeszła sprawdzenia,
    nie kasuje niczego, a w folderze nie zostaje po niej żaden plik."""
    _auto()
    folder = db.domyslny_folder_kopii()
    dobre = [_stara_kopia(folder, dni) for dni in (9, 8)]
    db.zapisz_ile_kopii(2)
    # Zepsuty korzeń tabeli tankowań: baza dalej się otwiera, ustawienia i folder
    # dają się przeczytać, a migawka kopiuje strony bez zaglądania w nie — błąd
    # łapie dopiero kontrola spójności. Dokładnie ta cicha awaria, przed którą
    # rotacja ma chronić dobre kopie.
    conn = sqlite3.connect(db.BAZA_DANYCH)
    korzen = conn.execute("SELECT rootpage FROM sqlite_master WHERE name='tankowania'").fetchone()[0]
    strona = conn.execute("PRAGMA page_size").fetchone()[0]
    conn.close()
    with open(db.BAZA_DANYCH, "r+b") as plik:
        plik.seek((korzen - 1) * strona)
        plik.write(b"\xff" * 12)
    assert db.pobierz_folder_kopii() == folder, "ustawienia czytają się mimo uszkodzenia"

    wynik = db.wykonaj_kopie(wymus=True)

    assert not wynik["ok"] and wynik["usuniete"] == 0
    assert "spójności" in wynik["blad"] or "uszkodzona" in wynik["blad"]
    assert sorted(os.listdir(folder)) == sorted(os.path.basename(s) for s in dobre)


def test_archiwum_nie_do_wczytania_nie_wypycha_dobrych_kopii(baza, monkeypatch):
    """Zapis przekłamany po drodze (pełna karta, zepsuty nośnik): archiwum nie
    przechodzi testu CRC, więc nie dostaje nazwy kopii i niczego nie kasuje."""
    _auto()
    folder = db.domyslny_folder_kopii()
    dobre = [_stara_kopia(folder, dni) for dni in (9, 8)]
    db.zapisz_ile_kopii(2)
    prawdziwy = db.kopie.zapisz_archiwum_kopii

    def przeklamany(cel, sprawdz_spojnosc=False):
        prawdziwy(cel, sprawdz_spojnosc)
        with open(cel, "r+b") as plik:
            plik.seek(200)
            plik.write(b"\x00" * 64)

    monkeypatch.setattr(db.kopie, "zapisz_archiwum_kopii", przeklamany)
    wynik = db.wykonaj_kopie(wymus=True)

    assert not wynik["ok"] and "sprawdzenia" in wynik["blad"]
    assert sorted(os.listdir(folder)) == sorted(os.path.basename(s) for s in dobre)


def test_blad_zapisu_trafia_na_kokpit_i_do_dzwonka_a_udana_kopia_go_zdejmuje(baza):
    auto_id = _auto()
    plik = _zepsuj_folder()
    assert db.stan_kopii_zapasowej()["folder"] == plik

    wynik = db.wykonaj_kopie()
    assert not wynik["ok"] and wynik["blad"]
    stan = db.stan_kopii_zapasowej()
    assert stan["zalegla"] and stan["blad"] == wynik["blad"] and stan["ostatnia"] is None

    teksty = _teksty(_ekran_glowny(auto_id))
    assert "Brak kopii zapasowej" in teksty
    assert f"Kopia nie wyszła: {wynik['blad']}" in teksty

    przypomnienia = [p for p in db.pobierz_powiadomienia(auto_id) if p["typ"] == "kopia"]
    assert len(przypomnienia) == 1
    p = przypomnienia[0]
    assert p["trasa"] == "/ustawienia" and p["klucz"] == "kopia:brak" and p["status"] == "pilne"
    assert p["linie_opisu"][0] == "Brak kopii zapasowej"
    assert "kopia" in db.TYPY_POWIADOMIEN_O_DANYCH

    db.zapisz_folder_kopii(None)
    assert db.wykonaj_kopie()["ok"]
    assert db.stan_kopii_zapasowej()["blad"] is None
    assert not [p for p in db.pobierz_powiadomienia(auto_id) if p["typ"] == "kopia"]
    assert not any(t.startswith("Ostatnia kopia") or t == "Brak kopii zapasowej"
                   for t in _teksty(_ekran_glowny(auto_id)))


def test_zalegla_kopia_na_kokpicie_mowi_ile_dni(baza):
    auto_id = _auto()
    db.zapisz_ustawienie(db.KLUCZ_KOPIA_OSTATNIA_AUTO, _moment(74))
    db.zapisz_ustawienie(db.KLUCZ_KOPIA_BLAD, "za mało miejsca w pamięci")
    teksty = _teksty(_ekran_glowny(auto_id))
    assert "Ostatnia kopia: 74 dni temu" in teksty
    assert "Kopia nie wyszła: za mało miejsca w pamięci" in teksty

    p = next(p for p in db.pobierz_powiadomienia(auto_id) if p["typ"] == "kopia")
    assert p["klucz"] == f"kopia:{(datetime.now() - timedelta(days=74)).date().isoformat()}"


def test_drzemka_kopii_dziala_we_wszystkich_pojazdach(baza):
    """Przypomnienie dotyczy urządzenia — odłożone przy jednym aucie milknie
    przy każdym."""
    pierwsze, drugie = _auto("Pierwsze"), _auto("Drugie")
    db.zapisz_kopie_automatyczna(False)
    p = next(p for p in db.pobierz_powiadomienia(drugie) if p["typ"] == "kopia")

    db.odloz_powiadomienie(pierwsze, db.klucz_drzemki(p), 7, p["tytul"])

    for auto_id in (pierwsze, drugie):
        assert not [x for x in db.pobierz_powiadomienia(auto_id) if x["typ"] == "kopia"]


# ======================================================= folder

def test_folder_z_innego_systemu_nie_liczy_sie(baza):
    db.zapisz_ustawienie(db.KLUCZ_KOPIA_FOLDER, "E:\\Aplikacja samochody\\kopie" if os.sep == "/" else "/sdcard/Documents")
    assert db.czy_folder_kopii_domyslny()
    assert db.pobierz_folder_kopii() == db.domyslny_folder_kopii()


def test_domyslny_folder_na_androidzie_w_dokumentach(baza, monkeypatch):
    monkeypatch.setenv("ANDROID_ROOT", "/system")
    monkeypatch.setenv("ANDROID_DATA", "/data")
    monkeypatch.setenv("EXTERNAL_STORAGE", "/sdcard")
    assert db.na_androidzie()
    assert db.domyslny_folder_kopii() == os.path.join("/sdcard", "Documents", "Flota Mobile")


def test_sprawdz_folder_kopii_plikiem_probnym(baza, tmp_path):
    dobry = tmp_path / "Kopie" / "nowy"
    assert db.sprawdz_folder_kopii(str(dobry)) == (True, "")
    assert os.listdir(dobry) == [], "plik próbny sprzątnięty"

    plik = tmp_path / "plik"
    plik.write_bytes(b"x")
    wolno, powod = db.sprawdz_folder_kopii(str(plik / "pod"))
    assert not wolno and powod
    assert db.sprawdz_folder_kopii("") == (False, "nie wskazano folderu")


# ======================================================= ustawienia urządzenia

def test_ustawienia_kopii_przezywaja_wczytanie_kopii(baza, tmp_path):
    """Kopia z innego urządzenia przynosi swoje `kopia_*` — po wczytaniu
    zostają te z TEGO urządzenia, łącznie z brakiem klucza."""
    _auto()
    obca = tmp_path / "obca.db"
    db.zapisz_ustawienie(db.KLUCZ_KOPIA_FOLDER, "E:\\obce\\kopie")
    db.zapisz_ustawienie(db.KLUCZ_KOPIA_OSTATNIA_AUTO, _moment(40))
    db.zapisz_ustawienie(db.KLUCZ_KOPIA_CO_DNI, "30")
    db.skopiuj_baze(db.BAZA_DANYCH, str(obca))

    moje = tmp_path / "moje"
    db.zapisz_folder_kopii(str(moje))
    db.zapisz_ustawienie(db.KLUCZ_KOPIA_OSTATNIA_AUTO, _moment(1))
    db.usun_ustawienie(db.KLUCZ_KOPIA_CO_DNI)
    przed = db.ustawienia_kopii_urzadzenia()

    db.skopiuj_baze(str(obca), db.BAZA_DANYCH)
    db.init_db()
    db.przywroc_ustawienia_kopii_urzadzenia(przed)

    assert db.ustawienia_kopii_urzadzenia() == przed
    stan = db.stan_kopii_zapasowej()
    assert stan["folder"] == str(moje) and stan["dni"] == 1 and stan["co_dni"] == 7


# ======================================================= interfejs

def test_opisy_stanu(baza):
    assert [utils.opis_wieku_kopii(d) for d in (None, 0, 1, 2, 74)] == \
        ["nigdy", "dziś", "wczoraj", "2 dni temu", "74 dni temu"]
    assert [utils.formatuj_rozmiar(b) for b in (0, 900, 12_998_000, 3 * 1024 ** 3)] == \
        ["0 kB", "1 kB", "12,4 MB", "3,0 GB"]
    teraz = datetime.now().replace(hour=21, minute=5)
    assert utils.moment_kopii(teraz) == "dziś, 21:05"
    assert utils.moment_kopii(teraz - timedelta(days=1)) == "wczoraj, 21:05"


def test_udostepnienie_liczy_sie_tylko_z_wybrana_aplikacja():
    assert utils.czy_udostepniono(ft.ShareResult(status=ft.ShareResultStatus.SUCCESS, raw="drive"))
    assert not utils.czy_udostepniono(ft.ShareResult(status=ft.ShareResultStatus.DISMISSED, raw=""))
    assert not utils.czy_udostepniono(ft.ShareResult(status=ft.ShareResultStatus.UNAVAILABLE, raw=""))
    assert not utils.czy_udostepniono(None)


def _ustawienia(strona, auto_id=None):
    stan = pomoce.stan_aplikacji(auto_id, "Kopiowany")
    return pomoce.zbuduj_widok(pomoce.klasy_widokow()["UstawieniaView"], strona, stan)


def test_karta_w_ustawieniach_pokazuje_kopie_w_folderze(baza):
    auto_id = _auto()
    db.wykonaj_kopie()
    db.wykonaj_kopie(wymus=True)
    widok = _ustawienia(pomoce.zbuduj_strone(), auto_id)

    teksty = _teksty(widok)
    assert "Automatyczna kopia przy starcie" in teksty
    assert "Kopie w folderze (2), od najnowszej" in teksty
    assert any(t.startswith("Ostatnia kopia: dziś, ") and t.endswith("(automatyczna)") for t in teksty)
    assert db.domyslny_folder_kopii() in teksty
    assert "Kopia zapasowa" not in _teksty(widok.controls[0]), "bez problemu karta stoi na swoim miejscu"


def test_karta_z_problemem_staje_na_gorze_ustawien(baza):
    auto_id = _auto()
    db.zapisz_kopie_automatyczna(False)
    widok = _ustawienia(pomoce.zbuduj_strone(), auto_id)
    assert "Kopia zapasowa" in _teksty(widok.controls[0])
    assert "Nie ma jeszcze żadnej kopii" in _teksty(widok.controls[0])


def test_wybor_folderu_sprawdza_zapis_zanim_go_zapamieta(baza, tmp_path, monkeypatch):
    _auto()
    strona = pomoce.zbuduj_strone()
    monkeypatch.setattr(type(strona.page), "run_task",
                        lambda self, f, *a, **k: asyncio.run(f(*a, **k)))
    ostrzezenia = []
    monkeypatch.setattr(utils, "pokaz_ostrzezenie", lambda page, tytul, tresc, **k: ostrzezenia.append(tresc))
    import views.settings_view as ekran_ustawien
    monkeypatch.setattr(ekran_ustawien.utils, "pokaz_ostrzezenie",
                        lambda page, tytul, tresc, **k: ostrzezenia.append(tresc))

    wybor = {}

    class Wybieracz:
        async def get_directory_path(self, dialog_title=None, initial_directory=None):
            return wybor["folder"]

    strona.page.zalacznik_picker = Wybieracz()
    widok = _ustawienia(strona)

    plik = tmp_path / "plik"
    plik.write_bytes(b"x")
    wybor["folder"] = str(plik / "kopie")
    widok._wybierz_folder_kopii()
    assert db.czy_folder_kopii_domyslny() and len(ostrzezenia) == 1

    wybor["folder"] = str(tmp_path / "Dokumenty" / "Kopie")
    widok._wybierz_folder_kopii()
    assert db.pobierz_folder_kopii() == wybor["folder"]
    assert widok.kopia_folder.value == wybor["folder"] and widok.btn_kopia_domyslny.visible

    widok._domyslny_folder_kopii()
    assert db.czy_folder_kopii_domyslny() and not widok.btn_kopia_domyslny.visible


# ======================================================= start aplikacji (main.py)

@pytest.fixture
def aplikacja(baza, monkeypatch):
    """main.main() na stronie testowej. `run_task` nie uruchamia niczego, tylko
    zbiera zadania — test sam decyduje, które i kiedy puścić."""
    # `main.py` kończy się `ft.run(main)` — podmiana PRZED importem.
    monkeypatch.setattr(ft, "run", lambda *args, **kwargs: None)
    import log
    import main

    monkeypatch.setattr(log, "wlacz", lambda: True)
    monkeypatch.setitem(utils.wyglad._OSTATNI_MOTYW, "nazwa", utils.wyglad._OSTATNI_MOTYW["nazwa"])
    strona = pomoce.zbuduj_strone()
    zadania = []
    monkeypatch.setattr(type(strona.page), "run_task", lambda self, f, *a, **k: zadania.append(f))
    _auto()
    main.main(strona.page)
    return SimpleNamespace(strona=strona, page=strona.page, zadania=zadania)


def _zadanie(aplikacja, nazwa):
    return next(f for f in aplikacja.zadania if getattr(f, "__name__", "") == nazwa)


def test_start_robi_kopie_po_porzadkach_a_powrot_z_tla_po_n_dniach(aplikacja):
    folder = db.domyslny_folder_kopii()
    assert not os.path.exists(folder), "przed pierwszym renderem nic się nie pakuje"

    asyncio.run(_zadanie(aplikacja, "_porzadki_po_starcie")())
    assert len(db.lista_kopii(folder)) == 1

    aplikacja.zadania.clear()
    aplikacja.page.on_app_lifecycle_state_change(SimpleNamespace(state=ft.AppLifecycleState.RESUME))
    kopia_w_tle = _zadanie(aplikacja, "_kopia_w_tle")
    asyncio.run(kopia_w_tle())
    assert len(db.lista_kopii(folder)) == 1, "świeża kopia — powrót z tła nic nie robi"

    db.zapisz_ustawienie(db.KLUCZ_KOPIA_OSTATNIA_AUTO, _moment(7))
    asyncio.run(kopia_w_tle())
    assert len(db.lista_kopii(folder)) == 2

    aplikacja.zadania.clear()
    aplikacja.page.on_app_lifecycle_state_change(SimpleNamespace(state=ft.AppLifecycleState.PAUSE))
    assert not [f for f in aplikacja.zadania if getattr(f, "__name__", "") == "_kopia_w_tle"]


def test_wczytaj_z_listy_przywraca_dane_i_zostawia_ustawienia_kopii(aplikacja, tmp_path, monkeypatch):
    # Strona testowa nie pokaże okna ani paska na dole — komunikaty zbieramy.
    komunikaty = []
    monkeypatch.setattr(utils, "pokaz_ladowanie", lambda page, tekst="": None)
    monkeypatch.setattr(utils, "ukryj_ladowanie", lambda page, dlg: None)
    monkeypatch.setattr(utils, "pokaz_komunikat", lambda page, tekst, *a, **k: komunikaty.append(tekst))
    kopia = db.wykonaj_kopie()["sciezka"]
    pomoce.utworz_pojazd("Dopisany po kopii")
    moje = tmp_path / "Moje kopie"
    db.zapisz_folder_kopii(str(moje))
    db.zapisz_kopie_co_dni(14)

    asyncio.run(aplikacja.page.wczytaj_kopie(kopia))

    assert komunikaty and komunikaty[-1].startswith("Pomyślnie wczytano bazę!"), komunikaty
    with sqlite3.connect(db.BAZA_DANYCH) as conn:
        nazwy = {r[0] for r in conn.execute("SELECT nazwa FROM samochody")}
    assert nazwy == {"Kopiowany"}, "dane z kopii"
    assert os.path.exists(db.BAZA_DANYCH + ".bak"), "poprzednia baza odłożona"
    stan = db.stan_kopii_zapasowej()
    assert stan["folder"] == str(moje) and stan["co_dni"] == 14 and stan["dni"] == 0
