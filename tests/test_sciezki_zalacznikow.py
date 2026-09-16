"""Ścieżki załączników w bazie: zawsze względne, sklejane ze STORAGE_PATH przy odczycie.

Notatka: `claude/kopia-zapasowa-sciezki-zalacznikow.md`. W testach STORAGE_PATH
to katalog tymczasowy, a katalog roboczy to korzeń repozytorium — jak na
Androidzie, gdzie ścieżka względna czytana wprost (bez sklejenia) nie trafia
w żaden plik. Miejsce, które zapomni o sklejeniu, wyłoży się tutaj.

„Inne urządzenie” to cały katalog danych przeniesiony pod nową ścieżkę: stara
przestaje istnieć, więc żaden wpis nie trafi w plik przez przypadek.
"""

import json
import os
import re
import shutil
import sys

import pytest
from PIL import Image

import db
import pomoce
import utils


ANDROID = "/data/user/0/com.flet.cars_app/files/data"


def pliki_w_koszu():
    folder = db.FOLDER_KOSZ
    return sorted(os.listdir(folder)) if os.path.isdir(folder) else []


def tresc(sciezka):
    with open(sciezka, "rb") as plik:
        return plik.read()


def zapisz(sciezka, dane=b"PLIK"):
    with open(sciezka, "wb") as plik:
        plik.write(dane)
    return sciezka


def przenies_na_inne_urzadzenie(monkeypatch, katalog, nowy_katalog):
    """Kopia zapasowa na urządzeniu z innym STORAGE_PATH. Podmiana stałych jak
    w fixture `magazyn` (conftest.py): po wszystkich modułach aplikacji, bo każdy
    ma własną kopię wartości z `from .stale import …`."""
    shutil.move(str(katalog), str(nowy_katalog))
    wartosci = {
        "STORAGE_PATH": str(nowy_katalog),
        "BAZA_DANYCH": str(nowy_katalog / "flota_zadania.db"),
        "FOLDER_ZALACZNIKI": str(nowy_katalog / "zalaczniki"),
        "FOLDER_ODROCZONE": str(nowy_katalog / "zalaczniki_odroczone"),
        "FOLDER_KOSZ": str(nowy_katalog / "kosz_zalaczniki"),
        "PLIK_LOGU": str(nowy_katalog / "flota.log"),
    }
    monkeypatch.setenv("FLET_APP_STORAGE_DATA", str(nowy_katalog))
    for nazwa_modulu, modul in list(sys.modules.items()):
        if modul is None or nazwa_modulu.split(".")[0] not in ("db", "utils", "views", "sync", "main", "state", "log"):
            continue
        for nazwa, wartosc in wartosci.items():
            if hasattr(modul, nazwa):
                monkeypatch.setattr(modul, nazwa, wartosc)


# ------------------------------------------------------------ same ścieżki


def test_postac_do_bazy_jest_wzgledna_z_kazdego_zapisu(magazyn):
    przypadki = [
        (os.path.join(db.FOLDER_ZALACZNIKI, "a.jpg"), "zalaczniki/a.jpg"),
        (f"{ANDROID}/zalaczniki/a.jpg", "zalaczniki/a.jpg"),
        ("C:\\Users\\Limak\\AppData\\cars_app\\zalaczniki\\a.jpg", "zalaczniki/a.jpg"),
        ("zalaczniki\\a.jpg", "zalaczniki/a.jpg"),
        ("zalaczniki/a.jpg", "zalaczniki/a.jpg"),
        (os.path.join(db.FOLDER_KOSZ, "z_1_a.jpg"), "kosz_zalaczniki/z_1_a.jpg"),
        # Spoza folderów aplikacji — bez zmian, nie zgadujemy.
        (os.path.join(db.FOLDER_ODROCZONE, "a.jpg"), os.path.join(db.FOLDER_ODROCZONE, "a.jpg")),
        (None, None),
        ("", ""),
    ]
    for wejscie, oczekiwane in przypadki:
        assert db.wzgledna_sciezka_zalacznika(wejscie) == oczekiwane, wejscie


def test_pelna_sciezka_skleja_wzgledna_ze_storage_path(magazyn):
    oczekiwana = os.path.join(str(magazyn), "zalaczniki", "a.jpg")
    assert db.pelna_sciezka_zalacznika("zalaczniki/a.jpg") == oczekiwana
    assert db.pelna_sciezka_zalacznika("zalaczniki\\a.jpg") == oczekiwana
    assert db.pelna_sciezka_zalacznika(f"{ANDROID}/zalaczniki/a.jpg") == f"{ANDROID}/zalaczniki/a.jpg"
    assert db.pelna_sciezka_zalacznika(None) is None


def test_odczyt_trafia_w_plik_w_kazdym_formacie(magazyn):
    zdjecie = zapisz(os.path.join(db.FOLDER_ZALACZNIKI, "a.jpg"))
    w_koszu = zapisz(os.path.join(db.FOLDER_KOSZ, "z_1_b.jpg"))

    assert db.sciezka_pliku_zalacznika("zalaczniki/a.jpg") == zdjecie
    assert db.sciezka_pliku_zalacznika("zalaczniki\\a.jpg") == zdjecie
    assert db.sciezka_pliku_zalacznika(f"{ANDROID}/zalaczniki/a.jpg") == zdjecie
    assert db.sciezka_pliku_zalacznika(f"{ANDROID}/kosz_zalaczniki/z_1_b.jpg") == w_koszu
    assert db.sciezka_pliku_zalacznika("zalaczniki/brak.jpg") == os.path.join(str(magazyn), "zalaczniki", "brak.jpg")
    assert os.path.isabs(utils.abs_zalacznik("zalaczniki/a.jpg"))
    assert os.path.exists(utils.abs_zalacznik("zalaczniki/a.jpg"))

    # Plik odroczony nie może „znaleźć się” w załącznikach po samej nazwie —
    # kasowanie po nim skasowałoby cudzy plik.
    odroczony = os.path.join(db.FOLDER_ODROCZONE, "a.jpg")
    assert db.sciezka_pliku_zalacznika(odroczony) == odroczony


# ------------------------------------------------------------ zapis


def test_nowy_zalacznik_trafia_do_bazy_wzglednie(magazyn, tmp_path):
    zrodlo_pdf = zapisz(str(tmp_path / "faktura.pdf"), b"%PDF-1.4 faktura")
    zrodlo_jpg = str(tmp_path / "zdjecie.png")
    Image.new("RGB", (40, 30), (200, 20, 20)).save(zrodlo_jpg, "PNG")

    for zrodlo, rozszerzenie in ((zrodlo_pdf, ".pdf"), (zrodlo_jpg, ".jpg")):
        wpis = db.przygotuj_nowy_zalacznik(zrodlo)
        assert re.fullmatch(r"zalaczniki/[0-9a-f]{32}" + re.escape(rozszerzenie), wpis), wpis
        assert os.path.exists(db.pelna_sciezka_zalacznika(wpis))

    stary = db.zapisz_zalacznik(zrodlo_pdf)
    nowy = db.przygotuj_nowy_zalacznik(zrodlo_jpg)
    assert db.zatwierdz_zalacznik(stary, nowy) == nowy
    assert not os.path.exists(db.pelna_sciezka_zalacznika(stary)), "zatwierdzenie kasuje poprzedni plik"

    db.anuluj_nowy_zalacznik(nowy)
    assert not os.path.exists(db.pelna_sciezka_zalacznika(nowy))


# ------------------------------------------------------------ usuwanie z cofnięciem


USUWANIA = {
    "wpis": (lambda z: db.usun_z_cofnieciem("tankowania", z["tankowanie"]), "tankowania", "tankowanie"),
    "wpisy_grupowo": (lambda z: db.usun_wiele_z_cofnieciem("tankowania", [z["tankowanie"]]), "tankowania", "tankowanie"),
    "zadanie": (lambda z: db.usun_zadanie_z_cofnieciem(z["zadanie"]), "historia", "historia"),
    "wizyta": (lambda z: db.usun_wizyty_z_cofnieciem([z["wizyta"]]), "wizyty", "wizyta"),
    "zwrot_pozycji_wizyty": (lambda z: db.zwroc_pozycje_wizyty_do_zrobienia(z["wizyta"], [z["historia"]]), "historia", "historia"),
    "czesc_magazynu": (lambda z: db.usun_czesc_magazynu_z_cofnieciem(z["magazyn"]), "magazyn_czesci", "magazyn"),
}


@pytest.mark.parametrize("rodzaj", sorted(USUWANIA))
def test_usuniecie_z_cofnieciem_odklada_i_oddaje_plik(baza, rodzaj):
    usun, tabela, klucz = USUWANIA[rodzaj]
    zid = pomoce.utworz_pojazd("Cofany")
    with db.polacz_baze() as conn:
        wpis = conn.execute(f"SELECT zalacznik FROM {tabela} WHERE id=?", (zid[klucz],)).fetchone()[0]
    plik = db.pelna_sciezka_zalacznika(wpis)
    przed = tresc(plik)

    wynik = usun(zid)
    assert wynik
    assert not os.path.exists(plik), "plik ma czekać w folderze odroczonym na cofnięcie"

    wynik["cofnij"]()
    assert tresc(plik) == przed
    with db.polacz_baze() as conn:
        assert conn.execute(f"SELECT COUNT(*) FROM {tabela} WHERE zalacznik=?", (wpis,)).fetchone()[0] == 1


def test_wygasniecie_cofania_kasuje_odlozony_plik(baza):
    zid = pomoce.utworz_pojazd("Kasowany")
    with db.polacz_baze() as conn:
        wpis = conn.execute("SELECT zalacznik FROM tankowania WHERE id=?", (zid["tankowanie"],)).fetchone()[0]

    wynik = db.usun_z_cofnieciem("tankowania", zid["tankowanie"])
    assert os.listdir(db.FOLDER_ODROCZONE)
    wynik["finalizuj"]()

    assert not os.path.exists(db.pelna_sciezka_zalacznika(wpis))
    assert os.listdir(db.FOLDER_ODROCZONE) == []


# ------------------------------------------------------------ kosz i inne urządzenie


def test_kosz_zapamietuje_pliki_wzglednie(baza):
    pomoce.utworz_pojazd("Pierwszy")
    wpisy = set(pomoce.odciski_zalacznikow())

    wynik = db.usun_auto_do_kosza(1)

    with db.polacz_baze() as conn:
        surowe, rozmiar = conn.execute(
            "SELECT pliki, rozmiar_plikow FROM kosz_pojazdy WHERE id=?", (wynik["kosz_id"],)
        ).fetchone()
    pliki = json.loads(surowe)
    assert str(baza) not in surowe, "w koszu nie może zostać ścieżka tego urządzenia"
    assert all(w_koszu.startswith("kosz_zalaczniki/") for w_koszu, _ in pliki)
    assert {oryginal for _, oryginal in pliki} == wpisy
    assert rozmiar == sum(os.path.getsize(os.path.join(db.FOLDER_KOSZ, nazwa)) for nazwa in pliki_w_koszu())


def test_naprawa_nie_rusza_wpisow_trafiajacych_w_plik(baza):
    """Bez migracji: dawny zapis bezwzględny i względny z '\\' zostają, jakie są."""
    zid = pomoce.utworz_pojazd("Stary", sciezki_wzgledne=False)
    pomoce.utworz_pojazd("Nowy")
    with db.polacz_baze() as conn:
        wpis = conn.execute("SELECT zalacznik FROM historia WHERE id=?", (zid["historia"],)).fetchone()[0]
        conn.execute("UPDATE historia SET zalacznik=? WHERE id=?",
                     ("zalaczniki\\" + os.path.basename(wpis), zid["historia"]))
    przed = pomoce.odciski_zalacznikow()

    assert db.napraw_sciezki_zalacznikow() == (0, 0)
    assert pomoce.odciski_zalacznikow() == przed


def test_kopia_na_innym_urzadzeniu_dziala_bez_naprawy(baza, monkeypatch, tmp_path):
    pomoce.utworz_pojazd("Pierwszy")
    drugi = pomoce.utworz_pojazd("Drugi")
    kosz = db.usun_auto_do_kosza(drugi["auto_id"])
    odciski_przed = pomoce.odciski_zalacznikow()
    pliki_przed = pliki_w_koszu()
    assert odciski_przed and pliki_przed

    przenies_na_inne_urzadzenie(monkeypatch, baza, tmp_path / "telefon")

    assert pomoce.odciski_zalacznikow() == odciski_przed, "każdy wpis trafia w swój plik bez naprawy"
    assert all(os.path.exists(utils.abs_zalacznik(wpis)) for wpis in odciski_przed)
    assert db.napraw_sciezki_zalacznikow() == (0, 0)

    db.posprzataj_kosz()
    assert pliki_w_koszu() == pliki_przed, "pozycja kosza z kopii nie jest sierotą"

    db.przywroc_auto_z_kosza(kosz["kosz_id"])
    odciski = pomoce.odciski_zalacznikow()
    assert len(odciski) == 2 * len(odciski_przed)
    assert all(suma is not None for suma in odciski.values())
    assert pliki_w_koszu() == []


def test_dawny_kosz_z_innego_urzadzenia_przetrwa_sprzatanie_i_wraca(baza, monkeypatch, tmp_path):
    """Pozycja kosza zapisana przed zmianą (obie ścieżki bezwzględne) i przywieziona
    kopią na inne urządzenie. Sprzątanie sierot porównywało ścieżki wprost, więc
    skasowałoby wszystkie jej zdjęcia przy pierwszym starcie."""
    pomoce.utworz_pojazd("Z telefonu", sciezki_wzgledne=False)
    sumy_przed = {os.path.basename(w): suma for w, suma in pomoce.odciski_zalacznikow().items()}
    wynik = db.usun_auto_do_kosza(1)
    with db.polacz_baze() as conn:
        pliki = json.loads(conn.execute("SELECT pliki FROM kosz_pojazdy WHERE id=?", (wynik["kosz_id"],)).fetchone()[0])
        dawne = [[os.path.join(db.FOLDER_KOSZ, os.path.basename(w_koszu)), oryginal] for w_koszu, oryginal in pliki]
        conn.execute("UPDATE kosz_pojazdy SET pliki=? WHERE id=?", (json.dumps(dawne), wynik["kosz_id"]))
    pliki_przed = pliki_w_koszu()

    przenies_na_inne_urzadzenie(monkeypatch, baza, tmp_path / "komputer")

    db.posprzataj_kosz()
    assert pliki_w_koszu() == pliki_przed, "zdjęcia pozycji kosza z kopii to nie sieroty"

    assert db.przywroc_auto_z_kosza(wynik["kosz_id"])
    odciski = pomoce.odciski_zalacznikow()
    assert all(wpis.startswith("zalaczniki/") for wpis in odciski), "obca ścieżka wraca jako względna"
    assert {os.path.basename(w): suma for w, suma in odciski.items()} == sumy_przed
    assert pliki_w_koszu() == []


# ------------------------------------------------------------ raport PDF


# Ostrzeżenia fpdf2 o `ln=` dotyczą rysowania raportu, nie ścieżek.
@pytest.mark.filterwarnings("ignore:The parameter \"ln\" is deprecated:DeprecationWarning")
def test_raport_pdf_bierze_zdjecia_ze_sciezek_wzglednych(magazyn):
    for nazwa, kolor in (("glowne.jpg", (10, 120, 200)), ("karoseria.jpg", (200, 120, 10))):
        Image.new("RGB", (60, 40), kolor).save(os.path.join(db.FOLDER_ZALACZNIKI, nazwa), "JPEG")

    pdf = db.generuj_pdf_raportu(
        "Testowy", {}, "cały okres", tryb_paszportu=True,
        zdjecie_glowne="zalaczniki/glowne.jpg",
        zdjecia_karoserii=[("2026-01-05", "Przód", "zalaczniki/karoseria.jpg", "Rysa")],
    )

    assert len(re.findall(rb"/Subtype\s*/Image", pdf)) == 2
