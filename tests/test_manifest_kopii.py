"""Manifest kopii zapasowej i podgląd archiwum przed wczytaniem
(db/manifest_kopii.py, db/kopie.py, utils/kopie.py, main.py, views/settings_view.py).

Archiwum kopii — ręcznej i automatycznej, bo obie powstają w jednym miejscu —
dostaje `manifest.json`: wersję schematu, liczbę wpisów, sumę SHA-256 bazy
i bilans załączników. „Wczytaj kopię” pokazuje zawartość, zanim cokolwiek
nadpisze, a przy niezgodności z manifestem ostrzega na czerwono i wymaga
świadomego „Wczytaj mimo to”.

Podgląd liczy z samej bazy w archiwum, więc działa tak samo dla kopii sprzed
manifestu i dla gołych plików .db. Manifest służy tylko do sprawdzenia, czy to,
co leży w archiwum, jest tym, co eksport zapisał.
"""

import asyncio
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import zipfile
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import flet as ft
import pytest

import db
import log
import pomoce
import utils


MANIFEST = "manifest.json"
NAZWA_BAZY = os.path.basename(db.BAZA_DANYCH)
# Pojazd z `pomoce.utworz_pojazd` ma jeden wpis w każdej tabeli, którą liczy kosz.
WPISOW_NA_POJAZD = len(db.KOSZ_TABELE_LICZONE)
ZDJEC_NA_POJAZD = 7


# ======================================================= pomocnicze

def _pojazd(nazwa="Octavia"):
    return pomoce.utworz_pojazd(nazwa)["auto_id"]


def _wpisy(liczba):
    return db.liczba_z_odmiana(liczba, "wpis", "wpisy", "wpisów")


def _datuj_ostatnie_tankowanie(data):
    """Ostatnio dodane tankowanie dostaje datę (DD.MM.RRRR) — daje to pewny „ostatni wpis”."""
    with db.polacz_baze() as conn:
        conn.execute("UPDATE tankowania SET data=? WHERE id=(SELECT MAX(id) FROM tankowania)", (data,))
        db.przelicz_daty_iso(conn)


def _archiwum(katalog, nazwa="kopia.zip"):
    """Archiwum bieżącej bazy — dokładnie to, co robi „Eksportuj kopię”."""
    sciezka = katalog / nazwa
    sciezka.write_bytes(db.przygotuj_zip_kopii())
    return sciezka


def _manifest(archiwum):
    with zipfile.ZipFile(archiwum) as zf:
        return json.loads(zf.read(MANIFEST).decode("utf-8"))


def _przepakuj(zrodlo, cel, podmien=None, pomin=(), kompresja=zipfile.ZIP_DEFLATED):
    """Kopia archiwum z poprawką: `podmien` {nazwa: nowe bajty}, `pomin` — nazwy,
    których w kopii ma nie być. Tak powstają kopie „ruszone po utworzeniu”."""
    podmien = podmien or {}
    with zipfile.ZipFile(zrodlo) as we, zipfile.ZipFile(cel, "w", kompresja) as wy:
        for informacja in we.infolist():
            if informacja.filename not in pomin:
                wy.writestr(informacja.filename, podmien.get(informacja.filename, we.read(informacja.filename)))
    return cel


def _baza_po_zmianie(archiwum, katalog, *polecenia):
    """Bajty bazy z archiwum po poleceniach SQL — baza, której ktoś dotknął po
    zrobieniu kopii."""
    with zipfile.ZipFile(archiwum) as zf:
        zf.extract(NAZWA_BAZY, katalog)
    sciezka = katalog / NAZWA_BAZY
    polaczenie = sqlite3.connect(sciezka)
    try:
        for polecenie in polecenia:
            polaczenie.execute(polecenie)
        polaczenie.commit()
    finally:
        polaczenie.close()
    dane = sciezka.read_bytes()
    sciezka.unlink()
    return dane


def _teksty(korzen):
    """Wszystkie napisy z drzewa kontrolek, łącznie z etykietami przycisków."""
    wynik, do_odwiedzenia = [], [korzen]
    while do_odwiedzenia:
        kontrolka = do_odwiedzenia.pop()
        for pole in ("value", "label", "tooltip"):
            wartosc = getattr(kontrolka, pole, None)
            if isinstance(wartosc, str):
                wynik.append(wartosc)
        for pole in ("controls", "content", "title", "subtitle", "leading", "trailing", "actions"):
            dziecko = getattr(kontrolka, pole, None)
            if isinstance(dziecko, str):
                wynik.append(dziecko)
            elif isinstance(dziecko, (list, tuple)):
                do_odwiedzenia.extend(d for d in dziecko if isinstance(d, ft.Control))
            elif isinstance(dziecko, ft.Control):
                do_odwiedzenia.append(dziecko)
    return wynik


def _przyciski(dlg):
    return [przycisk.content for przycisk in dlg.actions]


@pytest.fixture
def okna(monkeypatch):
    """Okna i komunikaty, które utils/kopie.py pokazałby na ekranie. Strona
    testowa nie ma ekranu, więc zamiast otwierać dialogi — zbieramy je."""
    zebrane = SimpleNamespace(otwarte=[], zamkniete=[], ladowanie=[], komunikaty=[], ostrzezenia=[])

    def pokaz_ladowanie(page, tekst=""):
        zebrane.ladowanie.append(("pokaz", tekst))
        return "okno-ladowania"

    monkeypatch.setattr(utils.kopie, "otworz_dialog", lambda page, dlg: zebrane.otwarte.append(dlg))
    monkeypatch.setattr(utils.kopie, "zamknij_dialog", lambda page, dlg: zebrane.zamkniete.append(dlg))
    monkeypatch.setattr(utils.kopie, "pokaz_ladowanie", pokaz_ladowanie)
    monkeypatch.setattr(utils.kopie, "ukryj_ladowanie", lambda page, dlg: zebrane.ladowanie.append(("ukryj", dlg)))
    monkeypatch.setattr(utils.kopie, "pokaz_komunikat", lambda page, tekst, *a, **k: zebrane.komunikaty.append(tekst))
    monkeypatch.setattr(utils.kopie, "pokaz_ostrzezenie",
                        lambda page, tytul, tresc, **k: zebrane.ostrzezenia.append((tytul, tresc)))
    return zebrane


@pytest.fixture
def zadania(monkeypatch):
    """`page.run_task` nie uruchamia niczego, tylko zbiera zadania — test sam
    decyduje, które i kiedy puścić."""
    zebrane = []
    monkeypatch.setattr(ft.Page, "run_task", lambda self, f, *a, **k: zebrane.append(f))
    return zebrane


def _puszczaj(zebrane, nazwa):
    """Uruchamia ostatnie zebrane zadanie o tej nazwie."""
    zadanie = [f for f in zebrane if getattr(f, "__name__", "") == nazwa][-1]
    asyncio.run(zadanie())


# ======================================================= manifest w archiwum

def test_archiwum_kopii_ma_manifest_z_zawartoscia(baza, tmp_path):
    """Schemat, wpisy, suma SHA-256 bazy i bilans załączników — liczone z tego,
    co FAKTYCZNIE leży w archiwum, łącznie z koszem."""
    _pojazd()
    with open(os.path.join(db.FOLDER_KOSZ, "w_koszu.jpg"), "wb") as plik:
        plik.write(b"zdjecie z kosza")
    archiwum = _archiwum(tmp_path)

    manifest = _manifest(archiwum)

    with zipfile.ZipFile(archiwum) as zf:
        baza_w_archiwum = zf.read(NAZWA_BAZY)
        zdjecia = [i for i in zf.infolist() if i.filename.startswith(("zalaczniki/", "kosz_zalaczniki/"))]
    assert manifest["format"] == 1
    assert manifest["schemat"] == db.wersja_schematu_aplikacji()
    assert manifest["baza"] == {
        "plik": NAZWA_BAZY,
        "rozmiar": len(baza_w_archiwum),
        "sha256": hashlib.sha256(baza_w_archiwum).hexdigest(),
    }
    assert set(manifest["wpisy"]["wg_tabel"]) == set(db.KOSZ_TABELE_LICZONE)
    assert manifest["wpisy"]["razem"] == sum(manifest["wpisy"]["wg_tabel"].values()) == WPISOW_NA_POJAZD
    assert len(zdjecia) == ZDJEC_NA_POJAZD + 1, "zdjęcia pojazdu i jedno w koszu"
    assert manifest["zalaczniki"] == {"liczba": len(zdjecia), "rozmiar": sum(i.file_size for i in zdjecia)}
    utworzono = datetime.fromisoformat(manifest["utworzono"])
    assert utworzono.tzinfo is not None
    assert abs(datetime.now().astimezone() - utworzono) < timedelta(minutes=1)


def test_kopia_automatyczna_ma_manifest_tak_samo_jak_reczna(baza):
    _pojazd()
    wynik = db.wykonaj_kopie()
    assert wynik["ok"], wynik

    with zipfile.ZipFile(io.BytesIO(db.przygotuj_zip_kopii())) as reczna:
        reczny = json.loads(reczna.read(MANIFEST).decode("utf-8"))
    automatyczny = _manifest(wynik["sciezka"])

    assert set(automatyczny) == set(reczny)
    assert automatyczny["wpisy"] == reczny["wpisy"] and automatyczny["zalaczniki"] == reczny["zalaczniki"]
    assert db.sprawdz_archiwum_kopii(wynik["sciezka"]) == (True, "")
    assert db.podglad_kopii(wynik["sciezka"])["uwagi"] == []


def test_blad_manifestu_nie_zatrzymuje_kopii(baza, monkeypatch):
    """Manifest to metadane o kopii, nie jej treść: kopia bez niego wczytuje się
    jak kopia sprzed tej zmiany, a w logu zostaje ślad."""
    _pojazd()
    slady = []

    def zepsuty(*_args, **_kwargs):
        raise RuntimeError("nie da się policzyć")

    monkeypatch.setattr(db.manifest_kopii, "zbuduj_manifest_kopii", zepsuty)
    monkeypatch.setattr(log, "polkniety", slady.append)

    wynik = db.wykonaj_kopie()

    assert wynik["ok"], wynik
    with zipfile.ZipFile(wynik["sciezka"]) as zf:
        assert NAZWA_BAZY in zf.namelist() and MANIFEST not in zf.namelist()
    assert db.sprawdz_archiwum_kopii(wynik["sciezka"]) == (True, "")
    assert "manifest kopii zapasowej" in slady
    podglad = db.podglad_kopii(wynik["sciezka"])
    assert not podglad["manifest"] and not podglad["nieczytelna"] and podglad["uwagi"] == []


# ======================================================= podgląd: co leży w kopii

def test_podglad_opisuje_zawartosc_kopii(baza, tmp_path):
    _pojazd("Octavia")
    _pojazd("Berlingo")
    _datuj_ostatnie_tankowanie("15.09.2099")
    archiwum = _archiwum(tmp_path)

    podglad = db.podglad_kopii(archiwum)

    assert (podglad["plik"], podglad["rodzaj"]) == ("kopia.zip", "zip")
    assert podglad["manifest"] and podglad["data_z_manifestu"]
    assert not podglad["nieczytelna"] and podglad["uwagi"] == [] and podglad["odmowa"] == ""
    assert podglad["schemat"] == podglad["schemat_aplikacji"] == db.wersja_schematu_aplikacji()
    assert podglad["wpisy"] == 2 * WPISOW_NA_POJAZD
    assert podglad["wpisy_wg_tabel"]["tankowania"] == 2
    assert podglad["pojazdy"] == [
        {"nazwa": "Octavia", "wpisy": WPISOW_NA_POJAZD},
        {"nazwa": "Berlingo", "wpisy": WPISOW_NA_POJAZD},
    ]
    assert podglad["ostatni_wpis"] == "2099-09-15"
    assert podglad["zalaczniki"]["liczba"] == 2 * ZDJEC_NA_POJAZD
    assert podglad["obecna"] == {"wpisy": 2 * WPISOW_NA_POJAZD, "pojazdy": 2}
    assert abs(datetime.now().astimezone() - datetime.fromisoformat(podglad["utworzono"])) < timedelta(minutes=1)


def test_podglad_kopii_sprzed_manifestu(baza, tmp_path):
    """Kopia zrobiona przed manifestem wczytuje się jak każda inna: liczby idą
    z samej bazy, data z pliku, a brak manifestu nie jest uwagą — to nie jest
    uszkodzenie."""
    _pojazd()
    nowa = _archiwum(tmp_path, "nowa.zip")
    stara = _przepakuj(nowa, tmp_path / "stara.zip", pomin=(MANIFEST,))

    podglad = db.podglad_kopii(stara)

    assert not podglad["manifest"] and not podglad["data_z_manifestu"]
    assert podglad["uwagi"] == [] and not podglad["nieczytelna"]
    assert podglad["wpisy"] == WPISOW_NA_POJAZD == db.podglad_kopii(nowa)["wpisy"]
    assert podglad["zalaczniki"]["liczba"] == ZDJEC_NA_POJAZD
    assert abs(datetime.now() - datetime.fromisoformat(podglad["utworzono"])) < timedelta(minutes=5)


def test_podglad_golego_pliku_bazy(baza, tmp_path):
    """Dawny format kopii: sam plik .db, bez załączników. Data to czas zapisu pliku."""
    _pojazd()
    goly = tmp_path / "stara_kopia.db"
    db.skopiuj_baze(db.BAZA_DANYCH, str(goly))

    podglad = db.podglad_kopii(goly)

    assert (podglad["rodzaj"], podglad["zalaczniki"], podglad["manifest"]) == ("baza", None, False)
    assert podglad["uwagi"] == [] and podglad["wpisy"] == WPISOW_NA_POJAZD
    assert [p["nazwa"] for p in podglad["pojazdy"]] == ["Octavia"]
    assert abs(datetime.now() - datetime.fromisoformat(podglad["utworzono"])) < timedelta(minutes=5)


def test_podglad_niczego_nie_zmienia_i_po_sobie_sprzata(baza, tmp_path, monkeypatch):
    """Oglądana kopia nie ma prawa się zmienić ani zostawić rozpakowanej bazy,
    a obecna baza — ruszyć się wcale."""
    _pojazd()
    archiwum = _archiwum(tmp_path)
    goly = tmp_path / "goly.db"
    db.skopiuj_baze(db.BAZA_DANYCH, str(goly))
    roboczy = tmp_path / "roboczy"
    roboczy.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(roboczy))
    pliki = (archiwum, goly, db.BAZA_DANYCH)
    przed = {str(p): pomoce.suma_pliku(p) for p in pliki}
    obok_przed, dane_przed = sorted(os.listdir(tmp_path)), sorted(os.listdir(db.STORAGE_PATH))

    db.podglad_kopii(archiwum)
    db.podglad_kopii(goly)

    assert {str(p): pomoce.suma_pliku(p) for p in pliki} == przed
    assert sorted(os.listdir(tmp_path)) == obok_przed, "bez pliku .journal ani śmieci obok kopii"
    assert sorted(os.listdir(db.STORAGE_PATH)) == dane_przed
    assert not os.path.exists(db.BAZA_DANYCH + ".bak")
    assert os.listdir(roboczy) == [], "rozpakowana baza z kopii znika po podglądzie"


def _tekst_zamiast_zip(katalog):
    sciezka = katalog / "tekst.zip"
    sciezka.write_text("to nie jest archiwum", encoding="utf-8")
    return sciezka


def _zip_bez_bazy(katalog):
    sciezka = katalog / "bez_bazy.zip"
    with zipfile.ZipFile(sciezka, "w") as zf:
        zf.writestr("zalaczniki/a.jpg", b"a")
    return sciezka


def _zip_ze_smieciem_zamiast_bazy(katalog):
    sciezka = katalog / "smiec.zip"
    with zipfile.ZipFile(sciezka, "w") as zf:
        zf.writestr(NAZWA_BAZY, b"to nie jest baza SQLite" * 50)
    return sciezka


def _smiec_zamiast_bazy(katalog):
    sciezka = katalog / "smiec.db"
    sciezka.write_bytes(b"to nie jest baza SQLite" * 50)
    return sciezka


def _brak_pliku(katalog):
    return katalog / "nie-ma-mnie.zip"


@pytest.mark.parametrize("zrob, powod", [
    pytest.param(_tekst_zamiast_zip, "Plik nie jest poprawnym archiwum ZIP albo jest uszkodzony.", id="tekst-zamiast-zip"),
    pytest.param(_zip_bez_bazy, "Archiwum nie zawiera pliku bazy danych.", id="zip-bez-bazy"),
    pytest.param(_zip_ze_smieciem_zamiast_bazy, "Plik bazy danych w kopii nie jest poprawną bazą SQLite.",
                 id="zip-ze-smieciem-zamiast-bazy"),
    pytest.param(_smiec_zamiast_bazy, "Plik bazy danych w kopii nie jest poprawną bazą SQLite.",
                 id="smiec-zamiast-bazy"),
    pytest.param(_brak_pliku, "Nie udało się odczytać pliku.", id="brak-pliku"),
])
def test_podglad_nieczytelnej_kopii_mowi_dlaczego(baza, tmp_path, zrob, powod):
    """Podgląd nie rzuca wyjątków: nieczytelna kopia wraca z powodem po polsku.
    Odmowy nie ma — diagnostyka nie zamyka drogi, której nie umie ocenić (patrz
    db.sprawdz_kopie_przed_wczytaniem)."""
    _pojazd()

    podglad = db.podglad_kopii(zrob(tmp_path))

    assert podglad["nieczytelna"] and podglad["wpisy"] == 0 and podglad["pojazdy"] == []
    assert podglad["uwagi"] == [f"Nie można odczytać zawartości kopii. {powod}"]
    assert podglad["odmowa"] == ""
    assert podglad["obecna"] == {"wpisy": WPISOW_NA_POJAZD, "pojazdy": 1}


def test_uszkodzony_plik_bazy_w_archiwum_jest_nieczytelny(baza, tmp_path):
    """Błąd CRC wychodzi dopiero po ostatnim bajcie pliku — podgląd czyta go do końca."""
    _pojazd()
    zrodlo = _archiwum(tmp_path)
    bez_kompresji = _przepakuj(zrodlo, tmp_path / "bez_kompresji.zip", kompresja=zipfile.ZIP_STORED)
    with zipfile.ZipFile(bez_kompresji) as zf:
        dane = zf.read(NAZWA_BAZY)
    surowe = bytearray(bez_kompresji.read_bytes())
    srodek = surowe.find(dane[:64]) + len(dane) // 2
    surowe[srodek] ^= 0xFF
    bez_kompresji.write_bytes(bytes(surowe))

    podglad = db.podglad_kopii(bez_kompresji)

    assert podglad["nieczytelna"]
    assert podglad["uwagi"] == [
        "Nie można odczytać zawartości kopii. Plik nie jest poprawnym archiwum ZIP albo jest uszkodzony."
    ]


def test_kopia_z_nowszej_wersji_dostaje_odmowe_w_podgladzie(baza, tmp_path):
    """Migracji w tył nie ma, więc kopia z nowszej aplikacji nie dostaje pytania
    „wczytać?” — dostaje odmowę, tę samą co `wykonaj_import`."""
    _pojazd()
    kopia = _archiwum(tmp_path)
    nowsza = db.wersja_schematu_aplikacji() + 1
    dane = _baza_po_zmianie(kopia, tmp_path,
                            f"UPDATE ustawienia SET wartosc='{nowsza}' WHERE klucz='schema_version'")
    archiwum = _przepakuj(kopia, tmp_path / "nowsza.zip", podmien={NAZWA_BAZY: dane}, pomin=(MANIFEST,))

    podglad = db.podglad_kopii(archiwum)

    wolno, powod = db.sprawdz_kopie_przed_wczytaniem(archiwum)
    assert not wolno and podglad["odmowa"] == powod
    assert podglad["schemat"] == nowsza and podglad["schemat_aplikacji"] == nowsza - 1


def test_podsumowanie_bazy_ze_starego_schematu(tmp_path):
    """Kopia sprzed tabel i kolumn, które dopisały późniejsze migracje, wczytuje
    się drabinką — więc podgląd nie może się o nie wywracać."""
    stara = tmp_path / "stara.db"
    polaczenie = sqlite3.connect(stara)
    polaczenie.executescript("""
        CREATE TABLE ustawienia (klucz TEXT PRIMARY KEY, wartosc TEXT);
        INSERT INTO ustawienia VALUES ('schema_version', '12');
        CREATE TABLE samochody (id INTEGER PRIMARY KEY, nazwa TEXT);
        INSERT INTO samochody VALUES (1, 'Stary Golf');
        CREATE TABLE tankowania (id INTEGER PRIMARY KEY, auto_id INTEGER, data TEXT);
        INSERT INTO tankowania VALUES (1, 1, '01.02.2020'), (2, 1, '15.03.2020');
    """)
    polaczenie.commit()
    polaczenie.close()

    podsumowanie = db.podsumowanie_bazy(stara)

    assert podsumowanie["schemat"] == 12
    assert podsumowanie["wpisy"] == 2 and podsumowanie["wpisy_wg_tabel"]["tankowania"] == 2
    assert podsumowanie["pojazdy"] == [{"nazwa": "Stary Golf", "wpisy": 2}]
    assert podsumowanie["ostatni_wpis"] is None, "bez kolumny data_iso nie ma czego porównać"


def test_podsumowanie_pustej_bazy(baza):
    podsumowanie = db.podsumowanie_bazy(db.BAZA_DANYCH)

    assert podsumowanie["wpisy"] == 0 and podsumowanie["pojazdy"] == [] and podsumowanie["ostatni_wpis"] is None
    assert podsumowanie["schemat"] == db.wersja_schematu_aplikacji()
    assert db.podsumowanie_bazy("/nie/ma/takiej/bazy.db") is None


# ======================================================= sprawdzenie zgodności z manifestem

def test_zmieniona_baza_w_archiwum_psuje_sume_kontrolna(baza, tmp_path):
    """Z kasowanych wpisów wychodzi też różnica w liczbie wpisów — jako szczegół."""
    _pojazd()
    kopia = _archiwum(tmp_path)
    dane = _baza_po_zmianie(kopia, tmp_path, "DELETE FROM tankowania")
    zmieniona = _przepakuj(kopia, tmp_path / "zmieniona.zip", podmien={NAZWA_BAZY: dane})

    podglad = db.podglad_kopii(zmieniona)

    assert not podglad["nieczytelna"]
    assert podglad["uwagi"] == [
        "Suma kontrolna bazy nie zgadza się z manifestem — plik bazy w archiwum został zmieniony "
        "albo uszkodzony po utworzeniu kopii.",
        f"Manifest zapisuje {_wpisy(WPISOW_NA_POJAZD)}, a w bazie jest {_wpisy(WPISOW_NA_POJAZD - 1)}.",
    ]


def test_zmiana_bez_zmiany_liczby_wpisow_to_sama_suma(baza, tmp_path):
    _pojazd()
    kopia = _archiwum(tmp_path)
    dane = _baza_po_zmianie(kopia, tmp_path, "UPDATE tankowania SET stacja='Shell'")
    zmieniona = _przepakuj(kopia, tmp_path / "zmieniona.zip", podmien={NAZWA_BAZY: dane})

    uwagi = db.podglad_kopii(zmieniona)["uwagi"]

    assert len(uwagi) == 1 and uwagi[0].startswith("Suma kontrolna bazy nie zgadza się z manifestem")


def test_zgodna_suma_nie_robi_falszywego_alarmu(baza, tmp_path):
    """Przy zgodnej sumie plik jest bit w bit tym, który widział eksport. Inna
    liczba wpisów czy schematu w manifeście znaczyłaby tylko, że tamta wersja
    aplikacji liczyła po swojemu."""
    _pojazd()
    kopia = _archiwum(tmp_path)
    manifest = _manifest(kopia)
    manifest["wpisy"]["razem"] = 999
    manifest["schemat"] = 1
    inna = _przepakuj(kopia, tmp_path / "inna.zip", podmien={MANIFEST: json.dumps(manifest).encode("utf-8")})

    podglad = db.podglad_kopii(inna)

    assert podglad["manifest"] and podglad["uwagi"] == []


def test_brakujace_zalaczniki_sa_zgloszone(baza, tmp_path):
    _pojazd()
    kopia = _archiwum(tmp_path)
    with zipfile.ZipFile(kopia) as zf:
        zdjecia = sorted(n for n in zf.namelist() if n.startswith("zalaczniki/"))
    okrojona = _przepakuj(kopia, tmp_path / "okrojona.zip", pomin=zdjecia[:2])

    podglad = db.podglad_kopii(okrojona)

    assert podglad["uwagi"] == [
        f"W archiwum brakuje 2 załączników — manifest zapisuje ich {ZDJEC_NA_POJAZD}, "
        f"a w archiwum jest {ZDJEC_NA_POJAZD - 2}."
    ]
    assert podglad["zalaczniki"]["liczba"] == ZDJEC_NA_POJAZD - 2


def test_obciety_zalacznik_jest_wykryty_po_rozmiarze(baza, tmp_path):
    _pojazd()
    kopia = _archiwum(tmp_path)
    with zipfile.ZipFile(kopia) as zf:
        zdjecie = sorted(n for n in zf.namelist() if n.startswith("zalaczniki/"))[0]
    obcieta = _przepakuj(kopia, tmp_path / "obcieta.zip", podmien={zdjecie: b""})

    uwagi = db.podglad_kopii(obcieta)["uwagi"]

    assert len(uwagi) == 1
    assert uwagi[0].startswith("Załączniki w archiwum zajmują mniej, niż zapisano w manifeście")
    assert uwagi[0].endswith("któryś plik może być obcięty.")


def test_sprawdz_manifest_zglasza_tylko_to_co_podejrzane():
    podsumowanie = {"wpisy": 5, "schemat": 44}
    zalaczniki = {"liczba": 3, "rozmiar": 3 * 1024 * 1024}
    manifest = {"baza": {"sha256": "abc123"}, "wpisy": {"razem": 5}, "schemat": 44, "zalaczniki": dict(zalaczniki)}

    def uwagi(suma="abc123", zal=zalaczniki, pod=podsumowanie, man=manifest):
        return db.sprawdz_manifest(man, suma, pod, zal)

    assert uwagi() == []
    assert uwagi(man={**manifest, "baza": {"sha256": "ABC123"}}) == [], "wielkość liter sumy bez znaczenia"
    assert uwagi(zal={"liczba": 9, "rozmiar": 90 * 1024 * 1024}) == [], "dopisane później załączniki to nie uszkodzenie"
    assert uwagi(zal=None) == [], "goły plik .db nie ma załączników do policzenia"
    assert uwagi(pod={"wpisy": 99, "schemat": 12}) == [], "przy zgodnej sumie liczby wpisów nie są alarmem"
    assert uwagi(zal={"liczba": 1, "rozmiar": 10}) == [
        "W archiwum brakuje 2 załączników — manifest zapisuje ich 3, a w archiwum jest 1."
    ], "liczba plików wygrywa z rozmiarem"
    assert uwagi(zal={"liczba": 2, "rozmiar": 10}) == [
        "W archiwum brakuje 1 załącznika — manifest zapisuje ich 3, a w archiwum jest 2."
    ]
    assert uwagi(zal={"liczba": 3, "rozmiar": 1024 * 1024}) == [
        "Załączniki w archiwum zajmują mniej, niż zapisano w manifeście (1,0 MB zamiast 3,0 MB) "
        "— któryś plik może być obcięty."
    ]


def test_niezgodna_suma_dokleja_szczegoly_wpisow_i_schematu():
    manifest = {"baza": {"sha256": "aaa"}, "wpisy": {"razem": 5}, "schemat": 44}

    assert db.sprawdz_manifest(manifest, "bbb", {"wpisy": 6, "schemat": 45}, None) == [
        "Suma kontrolna bazy nie zgadza się z manifestem — plik bazy w archiwum został zmieniony "
        "albo uszkodzony po utworzeniu kopii.",
        "Manifest zapisuje 5 wpisów, a w bazie jest 6 wpisów.",
        "Manifest zapisuje schemat bazy 44, a baza ma 45.",
    ]
    assert len(db.sprawdz_manifest(manifest, "bbb", {"wpisy": 5, "schemat": 44}, None)) == 1
    assert len(db.sprawdz_manifest(manifest, "bbb", {"wpisy": 5, "schemat": None}, None)) == 1, \
        "nieczytelny schemat nie jest różnicą"


@pytest.mark.parametrize("tresc", [
    pytest.param(b"{to nie jest json", id="nie-json"),
    pytest.param(b"[1, 2, 3]", id="tablica-zamiast-obiektu"),
    pytest.param(b"\xff\xfe\x00", id="nie-utf8"),
    pytest.param(b"{" + b" " * (1024 * 1024) + b"}", id="za-duzy"),
])
def test_uszkodzony_manifest_nie_blokuje_podgladu(baza, tmp_path, tresc):
    """Zepsuty manifest to uwaga (nie da się sprawdzić sumy), ale sama kopia
    jest czytelna — podgląd wciąż mówi, co w niej leży."""
    _pojazd()
    kopia = _archiwum(tmp_path)
    zepsuta = _przepakuj(kopia, tmp_path / "zepsuta.zip", podmien={MANIFEST: tresc})

    podglad = db.podglad_kopii(zepsuta)

    assert podglad["uwagi"] == ["Manifest w archiwum jest nieczytelny — nie da się sprawdzić sumy kontrolnej."]
    assert not podglad["manifest"] and not podglad["data_z_manifestu"] and not podglad["nieczytelna"]
    assert podglad["wpisy"] == WPISOW_NA_POJAZD


OBCE_MANIFESTY = [
    {},
    {"baza": None},
    {"baza": "x"},
    {"baza": {"sha256": 5}},
    {"wpisy": []},
    {"wpisy": {"razem": "10"}},
    {"schemat": "44"},
    {"zalaczniki": []},
    {"zalaczniki": {"liczba": "x", "rozmiar": None}},
    {"utworzono": "wczoraj"},
    {"utworzono": 5},
]


def test_manifest_z_obcymi_polami_niczego_nie_wywala(baza, tmp_path):
    """Manifest bywa niepełny, poprawiany ręcznie albo z innej wersji aplikacji.
    Bez sumy kontrolnej nie ma czego potwierdzać, więc nie ma też zielonego „zgadza się”."""
    _pojazd()
    kopia = _archiwum(tmp_path)

    for numer, manifest in enumerate(OBCE_MANIFESTY):
        obca = _przepakuj(kopia, tmp_path / f"obca_{numer}.zip",
                          podmien={MANIFEST: json.dumps(manifest).encode("utf-8")})
        podglad = db.podglad_kopii(obca)

        assert not podglad["nieczytelna"] and podglad["uwagi"] == [], manifest
        assert not podglad["manifest"] and not podglad["data_z_manifestu"], manifest
        assert podglad["wpisy"] == WPISOW_NA_POJAZD, manifest


# ======================================================= okno podglądu (utils/kopie.py)

def test_nazwy_wpisow_w_podgladzie_pokrywaja_tabele_kosza():
    """Nowa tabela w db.KOSZ_TABELE_LICZONE bez nazwy tutaj zniknęłaby z rozbicia
    wpisów w oknie, nie zmieniając sumy."""
    assert set(utils.NAZWY_WPISOW_W_PODGLADZIE) == set(db.KOSZ_TABELE_LICZONE)
    for tabela, formy in utils.NAZWY_WPISOW_W_PODGLADZIE.items():
        assert len(formy) == 3 and all(formy), tabela


def test_okno_podgladu_pokazuje_zawartosc_i_czeka_na_decyzje(baza, tmp_path, okna):
    _pojazd("Octavia")
    _pojazd("Berlingo")
    _datuj_ostatnie_tankowanie("15.09.2099")
    podglad = db.podglad_kopii(_archiwum(tmp_path))
    strona = pomoce.zbuduj_strone()
    wczytano = []

    dlg = utils.pokaz_podglad_kopii(strona.page, podglad, lambda: wczytano.append(True))

    assert okna.otwarte == [dlg]
    teksty = _teksty(dlg)
    assert "Wczytać tę kopię?" in teksty and "kopia.zip" in teksty
    assert any(t.startswith("dziś, ") for t in teksty), "Z dnia"
    assert str(db.wersja_schematu_aplikacji()) in teksty and "Taka sama jak w tej aplikacji." in teksty
    assert _wpisy(2 * WPISOW_NA_POJAZD) in teksty
    assert ("2 tankowania · 2 wpisy serwisowe · 2 wizyty w warsztacie · 2 inne koszty · 2 komplety opon · "
            "2 części w magazynie · 2 zdjęcia karoserii · 2 odczyty licznika · 2 zadania do zrobienia · "
            "2 szkice do wpisania") in teksty
    assert "Octavia" in teksty and "Berlingo" in teksty
    assert teksty.count(_wpisy(WPISOW_NA_POJAZD)) == 2
    assert utils.formatuj_date_pl(date(2099, 9, 15)) in teksty
    assert any(t.startswith(f"{2 * ZDJEC_NA_POJAZD} plików (") for t in teksty)
    assert f"{_wpisy(2 * WPISOW_NA_POJAZD)}, 2 pojazdy" in teksty
    assert "Suma kontrolna i załączniki zgadzają się z manifestem kopii." in teksty
    assert "Ta kopia budzi wątpliwości" not in teksty
    assert not any("mniej niż obecna baza" in t for t in teksty)
    assert _przyciski(dlg) == ["Anuluj", "Wczytaj"] and dlg.actions[1].style is None

    dlg.actions[0].on_click(None)
    assert okna.zamkniete == [dlg] and wczytano == [], "Anuluj nie wczytuje"

    dlg.actions[1].on_click(None)
    assert okna.zamkniete == [dlg, dlg] and wczytano == [True], "Wczytaj zamyka okno i rusza wczytanie"


def test_okno_z_uwagami_wymaga_swiadomego_kroku(baza, tmp_path, okna):
    """Uszkodzona kopia bywa jedyną, jaką ktoś ma — nie zamykamy jej na stałe,
    wymagamy tylko świadomego „Wczytaj mimo to”."""
    _pojazd()
    kopia = _archiwum(tmp_path)
    dane = _baza_po_zmianie(kopia, tmp_path, "DELETE FROM tankowania")
    zmieniona = _przepakuj(kopia, tmp_path / "zmieniona.zip", podmien={NAZWA_BAZY: dane})
    podglad = db.podglad_kopii(zmieniona)
    strona = pomoce.zbuduj_strone()
    wczytano = []

    dlg = utils.pokaz_podglad_kopii(strona.page, podglad, lambda: wczytano.append(True))

    teksty = _teksty(dlg)
    assert "Ta kopia budzi wątpliwości" in teksty
    assert all(uwaga in teksty for uwaga in podglad["uwagi"]) and len(podglad["uwagi"]) == 2
    assert not any("zgadzają się" in t for t in teksty)
    assert _przyciski(dlg) == ["Anuluj", "Wczytaj mimo to"]
    assert dlg.actions[1].style.color == utils.KOLOR_STATUS["destructive"]

    dlg.actions[1].on_click(None)
    assert wczytano == [True]


def test_okno_nieczytelnej_kopii_nie_udaje_zawartosci(baza, tmp_path, okna):
    _pojazd()
    podglad = db.podglad_kopii(_zip_bez_bazy(tmp_path))
    strona = pomoce.zbuduj_strone()

    dlg = utils.pokaz_podglad_kopii(strona.page, podglad, lambda: None)

    teksty = _teksty(dlg)
    assert "bez_bazy.zip" in teksty and "Ta kopia budzi wątpliwości" in teksty
    assert "Nie można odczytać zawartości kopii. Archiwum nie zawiera pliku bazy danych." in teksty
    assert not {"Z dnia", "Wpisy", "Pojazdy", "Załączniki"} & set(teksty)
    assert _przyciski(dlg) == ["Anuluj", "Wczytaj mimo to"]


def test_okno_kopii_sprzed_manifestu_i_porownanie_z_obecna_baza(baza, tmp_path, okna):
    """Brak manifestu to spokojna notka, nie alarm. Wyraźnie za to widać, co
    przepadnie: stan bazy, którą import zastąpi, i ostrzeżenie, gdy kopia ma
    mniej wpisów niż ona."""
    _pojazd("Octavia")
    stara = _przepakuj(_archiwum(tmp_path, "nowa.zip"), tmp_path / "stara.zip", pomin=(MANIFEST,))
    _pojazd("Berlingo")
    strona = pomoce.zbuduj_strone()

    dlg = utils.pokaz_podglad_kopii(strona.page, db.podglad_kopii(stara), lambda: None)

    teksty = _teksty(dlg)
    assert ("Brak manifestu z sumą kontrolną — kopia z wcześniejszej wersji aplikacji, "
            "więc nie da się sprawdzić, czy jest cała.") in teksty
    assert "Data pliku — ta kopia nie ma manifestu." in teksty
    assert "Octavia" in teksty and "Berlingo" not in teksty
    assert f"{_wpisy(2 * WPISOW_NA_POJAZD)}, 2 pojazdy" in teksty
    assert f"Kopia ma o {_wpisy(WPISOW_NA_POJAZD)} mniej niż obecna baza." in teksty
    assert _przyciski(dlg) == ["Anuluj", "Wczytaj"], "brak manifestu to nie powód do czerwieni"

    # Bieżąca baza z mniejszą liczbą wpisów niż kopia: nic nie przepada, więc bez ostrzeżenia.
    polaczenie = sqlite3.connect(db.BAZA_DANYCH)
    for tabela in db.KOSZ_TABELE_LICZONE:
        polaczenie.execute(f"DELETE FROM {tabela}")
    polaczenie.commit()
    polaczenie.close()
    dlg = utils.pokaz_podglad_kopii(strona.page, db.podglad_kopii(stara), lambda: None)
    teksty = _teksty(dlg)
    assert f"{_wpisy(0)}, 2 pojazdy" in teksty
    assert not any("mniej niż obecna baza" in t for t in teksty)

    # Brak bieżącej bazy (świeża instalacja): nie ma z czym porównywać.
    os.remove(db.BAZA_DANYCH)
    podglad = db.podglad_kopii(stara)
    assert podglad["obecna"] is None
    assert "W aplikacji teraz" not in _teksty(utils.pokaz_podglad_kopii(strona.page, podglad, lambda: None))


def test_okno_pustej_kopii_nie_udaje_zawartosci(baza, tmp_path, okna):
    podglad = db.podglad_kopii(_archiwum(tmp_path))
    strona = pomoce.zbuduj_strone()

    teksty = _teksty(utils.pokaz_podglad_kopii(strona.page, podglad, lambda: None))

    assert _wpisy(0) in teksty and teksty.count("brak") == 2, "pojazdy i załączniki"
    assert "Ostatni wpis" not in teksty


def test_zapytaj_o_wczytanie_sprawdza_w_tle_i_czeka_na_decyzje(baza, tmp_path, okna, zadania):
    _pojazd()
    kopia = _archiwum(tmp_path)
    przed = pomoce.suma_pliku(db.BAZA_DANYCH)
    strona = pomoce.zbuduj_strone()
    wczytano = []

    utils.zapytaj_o_wczytanie_kopii(strona.page, str(kopia), lambda: wczytano.append(True))

    assert len(zadania) == 1 and not okna.otwarte, "sprawdzanie rusza w tle, okna jeszcze nie ma"
    asyncio.run(zadania[0]())

    assert okna.ladowanie == [("pokaz", "Sprawdzanie kopii..."), ("ukryj", "okno-ladowania")]
    assert len(okna.otwarte) == 1 and "Wczytać tę kopię?" in _teksty(okna.otwarte[0])
    assert wczytano == [] and pomoce.suma_pliku(db.BAZA_DANYCH) == przed, "do decyzji nic się nie dzieje"

    okna.otwarte[0].actions[1].on_click(None)
    assert wczytano == [True]


def test_zapytaj_o_wczytanie_odmawia_kopii_z_nowszej_wersji_bez_pytania(baza, tmp_path, okna, zadania):
    _pojazd()
    kopia = _archiwum(tmp_path)
    nowsza = db.wersja_schematu_aplikacji() + 1
    dane = _baza_po_zmianie(kopia, tmp_path,
                            f"UPDATE ustawienia SET wartosc='{nowsza}' WHERE klucz='schema_version'")
    archiwum = _przepakuj(kopia, tmp_path / "nowsza.zip", podmien={NAZWA_BAZY: dane}, pomin=(MANIFEST,))
    strona = pomoce.zbuduj_strone()
    wczytano = []

    utils.zapytaj_o_wczytanie_kopii(strona.page, str(archiwum), lambda: wczytano.append(True))
    asyncio.run(zadania[0]())

    assert okna.ostrzezenia == [("Kopia z nowszej wersji aplikacji", db.sprawdz_kopie_przed_wczytaniem(archiwum)[1])]
    assert not okna.otwarte and wczytano == []
    assert okna.ladowanie[-1][0] == "ukryj", "okno ładowania znika także przy odmowie"


def test_zapytaj_o_wczytanie_nie_otwiera_brakujacego_pliku(baza, tmp_path, okna, zadania):
    strona = pomoce.zbuduj_strone()

    for sciezka in ("", None, str(tmp_path / "nie-ma.zip")):
        utils.zapytaj_o_wczytanie_kopii(strona.page, sciezka, lambda: pytest.fail("nic nie ma się wczytać"))

    assert okna.komunikaty == ["Nie można odczytać wybranego pliku."] * 3
    assert zadania == [] and not okna.otwarte


# ======================================================= trzy drogi wczytania kopii

@pytest.fixture
def aplikacja(baza, monkeypatch, zadania):
    """main.main() na stronie testowej (jak w test_kopie_automatyczne.py)."""
    # `main.py` kończy się `ft.run(main)` — podmiana PRZED importem.
    monkeypatch.setattr(ft, "run", lambda *args, **kwargs: None)
    import main

    monkeypatch.setattr(log, "wlacz", lambda: True)
    monkeypatch.setitem(utils.wyglad._OSTATNI_MOTYW, "nazwa", utils.wyglad._OSTATNI_MOTYW["nazwa"])
    strona = pomoce.zbuduj_strone()
    _pojazd("Kopiowany")
    main.main(strona.page)
    return SimpleNamespace(strona=strona, page=strona.page)


def _wybierz_plik_z_menu(aplikacja, plik, monkeypatch):
    """„Wczytaj kopię bazy” z menu aż do okna podglądu; zwraca to okno."""
    async def wybierz(self, *args, **kwargs):
        return [SimpleNamespace(path=str(plik))]

    monkeypatch.setattr(ft.FilePicker, "pick_files", wybierz)
    asyncio.run(aplikacja.page.views[0].akcje_nawigacji["wczytaj"]())


def test_wybor_pliku_z_menu_pokazuje_podglad_zanim_nadpisze_baze(aplikacja, okna, zadania, tmp_path, monkeypatch):
    kopia = _archiwum(tmp_path)
    _pojazd("Dopisany po kopii")
    przed = pomoce.suma_pliku(db.BAZA_DANYCH)
    komunikaty = []
    monkeypatch.setattr(utils, "pokaz_komunikat", lambda page, tekst, *a, **k: komunikaty.append(tekst))

    _wybierz_plik_z_menu(aplikacja, kopia, monkeypatch)
    assert not okna.otwarte, "najpierw sprawdzanie w tle"
    _puszczaj(zadania, "_przygotuj")

    assert len(okna.otwarte) == 1
    dlg = okna.otwarte[0]
    assert "Wczytać tę kopię?" in _teksty(dlg)
    assert pomoce.suma_pliku(db.BAZA_DANYCH) == przed and not os.path.exists(db.BAZA_DANYCH + ".bak")

    dlg.actions[0].on_click(None)
    assert not [f for f in zadania if getattr(f, "__name__", "") == "_wczytaj"], "Anuluj nie wczytuje"
    assert pomoce.suma_pliku(db.BAZA_DANYCH) == przed

    _wybierz_plik_z_menu(aplikacja, kopia, monkeypatch)
    _puszczaj(zadania, "_przygotuj")
    okna.otwarte[-1].actions[1].on_click(None)
    _puszczaj(zadania, "_wczytaj")

    assert komunikaty and komunikaty[-1].startswith("Pomyślnie wczytano bazę!"), komunikaty
    assert os.path.exists(db.BAZA_DANYCH + ".bak"), "poprzednia baza odłożona"
    with sqlite3.connect(db.BAZA_DANYCH) as polaczenie:
        nazwy = {w[0] for w in polaczenie.execute("SELECT nazwa FROM samochody")}
    assert nazwy == {"Kopiowany"}, "dane z kopii"


def test_wczytaj_z_listy_w_ustawieniach_najpierw_pokazuje_podglad(baza, okna, zadania, tmp_path):
    auto_id = _pojazd("Kopiowany")
    kopia = _archiwum(tmp_path)
    strona = pomoce.zbuduj_strone()
    wczytane = []

    async def wczytaj(sciezka):
        wczytane.append(sciezka)

    strona.page.wczytaj_kopie = wczytaj
    widok = pomoce.zbuduj_widok(
        pomoce.klasy_widokow()["UstawieniaView"], strona, pomoce.stan_aplikacji(auto_id, "Kopiowany"))
    zadania.clear()

    widok._wczytaj_kopie({"sciezka": str(kopia)})
    _puszczaj(zadania, "_przygotuj")

    assert len(okna.otwarte) == 1 and "Wczytać tę kopię?" in _teksty(okna.otwarte[0])
    assert wczytane == [], "pytanie, nie wczytanie"

    okna.otwarte[0].actions[1].on_click(None)
    _puszczaj(zadania, "wykonaj_async")
    assert wczytane == [str(kopia)]
