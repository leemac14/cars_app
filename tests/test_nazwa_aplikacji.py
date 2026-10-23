"""Nazwa i logo aplikacji: jedna nazwa wszędzie (podpis pod ikoną, okno, tablica startowa,
kalendarz, log, folder kopii), identyfikator pakietu Androida nietknięty, grafiki logo
w assets/ w kształcie, którego oczekuje `flet build`."""

import pathlib
import tomllib

import flet as ft
import pytest
from PIL import Image

import db
import log
import pomoce
import utils

KORZEN = pathlib.Path(__file__).resolve().parents[1]
ASSETS = KORZEN / "assets"


def _pyproject():
    with open(KORZEN / "pyproject.toml", "rb") as f:
        return tomllib.load(f)


def test_podpis_pod_ikona_to_nazwa_aplikacji():
    flet = _pyproject()["tool"]["flet"]
    assert flet["product"] == db.NAZWA_APLIKACJI == "LEEMAC APP"
    assert " " not in flet["artifact"], "nazwa pliku APK bez spacji — idzie na czat"


def test_identyfikator_pakietu_androida_bez_zmian():
    """Inny identyfikator to dla Androida nowa aplikacja — obok starej, z pustą bazą."""
    py = _pyproject()
    assert py["tool"]["flet"]["android"]["bundle_id"] == "com.flet.cars_app"
    assert "name" not in py["project"], "`name` przestawiłby nazwę paczki"


def test_stara_nazwa_tylko_przy_przenoszeniu_kopii():
    trafienia = sorted(
        p.relative_to(KORZEN).as_posix() for p in KORZEN.rglob("*.py")
        if p.relative_to(KORZEN).parts[0] not in ("tests", ".venv", "build")
        and "Flota Mobile" in p.read_text(encoding="utf-8")
    )
    assert trafienia == ["db/kopie.py"]
    assert db.STARA_NAZWA_FOLDERU_KOPII_ANDROID == "Flota Mobile"


def test_nazwa_w_tekstach_aplikacji():
    assert db.NAZWA_APLIKACJI in db.PRODID_KALENDARZA
    assert db.DOMENA_UID == "cars-app", "inne UID — kalendarz zdublowałby wysłane terminy"
    assert utils.NAZWA_NA_TABLICY == db.NAZWA_FOLDERU_KOPII_ANDROID == db.NAZWA_APLIKACJI
    assert f" {db.NAZWA_APLIKACJI} — log diagnostyczny" in log.zbierz_raport()


def test_okno_ma_nazwe_i_ikone_z_assets(baza, monkeypatch):
    monkeypatch.setattr(ft, "run", lambda *args, **kwargs: None)
    import main

    monkeypatch.setattr(log, "wlacz", lambda: True)
    monkeypatch.setitem(utils.wyglad._OSTATNI_MOTYW, "nazwa", utils.wyglad._OSTATNI_MOTYW["nazwa"])
    strona = pomoce.zbuduj_strone()
    page = strona.page
    monkeypatch.setattr(type(page), "run_task", lambda self, *args, **kwargs: None)
    main.main(page)

    assert page.title == db.NAZWA_APLIKACJI
    assert (ASSETS / page.window.icon).is_file() and page.window.icon.endswith(".ico")


@pytest.mark.parametrize("plik", ["icon.png", "splash_dark.png"])
def test_grafiki_dla_flet_build_kwadratowe_z_przezroczystym_tlem(plik):
    """Kwadrat i przezroczyste rogi: Flet sam dobiera margines pod maskę launchera
    i koło ekranu powitalnego, ale tylko dla grafiki z przezroczystym tłem."""
    with Image.open(ASSETS / plik) as im:
        assert im.mode == "RGBA" and im.width == im.height >= 1024
        assert im.getpixel((0, 0))[3] == 0 and im.getpixel((im.width - 1, im.height - 1))[3] == 0


def test_ciemny_ekran_powitalny_ma_biale_kolo_pod_autem():
    with Image.open(ASSETS / "splash_dark.png") as im:
        assert im.getpixel((im.width // 2, 8))[:3] == (255, 255, 255)


def test_logo_w_aplikacji_i_ikona_okna():
    with Image.open(ASSETS / utils.PLIK_LOGO) as im:
        assert im.mode == "RGBA" and im.width > 3 * im.height, "samo auto, bez pustego kwadratu"
    with Image.open(ASSETS / "icon.ico") as im:
        assert (16, 16) in im.info["sizes"] and (256, 256) in im.info["sizes"]
    assert pathlib.Path(db.PLIK_LOGO_GRAFIKI) == ASSETS / utils.PLIK_LOGO
