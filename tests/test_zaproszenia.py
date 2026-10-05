"""Zaproszenie kodem QR i linkiem carsapp:// (utils/zaproszenia.py,
sync/wspoldzielenie.py, trasa /dolacz/<KOD> w main.py).

Link musi się zgadzać w trzech miejscach naraz, a żadne nie krzyczy, gdy się
rozjedzie:

* treść kodu QR i zaproszenia z SMS-a (`sync.link_zaproszenia`);
* deklaracja dla Androida w pyproject.toml ([tool.flet.android.deep_linking]) —
  inny schemat albo host i system po prostu nie otworzy aplikacji;
* trasa w routerze — Flet podaje aplikacji samą ścieżkę, /dolacz/<KOD>.

Poza tym: link tylko WPISUJE kod, dołącza dotknięcie „Dołącz”; „Wklej” bierze
kod z czegokolwiek, co ktoś skopiował; jasność ekranu wraca do systemu.
"""

import asyncio
import pathlib
import tomllib

import flet as ft
import pytest

import audyty
import db
import pomoce
import sync
import utils
from utils import zaproszenia
from views.wspoldzielenie_view import WspoldzielenieView


KORZEN = pathlib.Path(__file__).resolve().parent.parent


def _kontrolki(korzen):
    wynik, do_odwiedzenia = [], [korzen]
    while do_odwiedzenia:
        biezaca = do_odwiedzenia.pop(0)
        wynik.append(biezaca)
        do_odwiedzenia.extend(dziecko for _, dziecko in audyty._dzieci(biezaca))
        for pole in ("title", "actions"):
            dodatkowe = getattr(biezaca, pole, None) if isinstance(biezaca, ft.AlertDialog) else None
            if isinstance(dodatkowe, ft.Control):
                do_odwiedzenia.append(dodatkowe)
            elif isinstance(dodatkowe, list):
                do_odwiedzenia.extend(dodatkowe)
    return wynik


def _teksty(korzen):
    return [k.value for k in _kontrolki(korzen) if isinstance(k, ft.Text) and k.value]


def _ikony(korzen, ikona):
    return [k for k in _kontrolki(korzen) if isinstance(k, ft.IconButton) and k.icon == ikona]


def _liczba_pojazdow():
    with db.polacz_baze() as conn:
        return conn.execute("SELECT COUNT(*) FROM samochody").fetchone()[0]


# ======================================================= link

def test_link_zaproszenia():
    assert sync.link_zaproszenia(" a1b2c3 ") == "carsapp://app/dolacz/A1B2C3"


@pytest.mark.parametrize("tekst, kod", [
    ("A1B2C3", "A1B2C3"),
    (" a1b2 c3 ", "A1B2C3"),
    ("carsapp://app/dolacz/a1b2c3", "A1B2C3"),
    ("Zaproszenie:\ncarsapp://app/dolacz/F00D42\n\nalbo wpisz kod F00D42.", "F00D42"),
    ("CARSAPP://APP/DOLACZ/A1B2C3", "A1B2C3"),
    ("https://example.com/dolacz/A1B2C3", ""),
    ("hej, jedziemy jutro?", ""),
    ("", ""),
    (None, ""),
])
def test_kod_z_zaproszenia(tekst, kod):
    assert sync.kod_z_zaproszenia(tekst) == kod


def test_cale_zaproszenie_z_sms_a_oddaje_swoj_kod():
    tekst = utils.tekst_zaproszenia("Octavia", db.ROLA_PODGLAD, "C3D4E5")
    assert "carsapp://app/dolacz/C3D4E5" in tekst and "tylko podgląd" in tekst and "„Octavia”" in tekst
    assert sync.kod_z_zaproszenia(tekst) == "C3D4E5"


def test_android_dostaje_ten_sam_schemat_i_host_co_link():
    """Flet przy budowaniu APK czyta deep linking WYŁĄCZNIE z sekcji
    [tool.flet.android.deep_linking] — `[tool.flet.deep_linking]` Android pomija."""
    pyproject = tomllib.loads((KORZEN / "pyproject.toml").read_text(encoding="utf-8"))
    sekcja = pyproject["tool"]["flet"]["android"]["deep_linking"]
    assert sekcja == {"scheme": sync.SCHEMAT_LINKU, "host": sync.HOST_LINKU}
    assert sync.link_zaproszenia("X1Y2").startswith(f"{sekcja['scheme']}://{sekcja['host']}/")
    # Android porównuje schemat i host dosłownie — wielka litera i link prowadzi donikąd.
    assert all(w == w.lower() for w in sekcja.values())


def test_dolaczenie_przyjmuje_wklejony_link(baza, monkeypatch):
    wyslane = []

    def _dolacz_z_rola(klient, kod):
        wyslane.append(kod)
        return "pojazd-1", "Octavia", db.ROLA_WSPOLAUTOR

    monkeypatch.setattr(sync.wspoldzielenie, "_upewnij_sesje", lambda: (object(), "uid"))
    monkeypatch.setattr(sync.wspoldzielenie, "_dolacz_z_rola", _dolacz_z_rola)
    monkeypatch.setattr(sync.wspoldzielenie, "synchronizuj_wszystko", lambda auto_id: (0, 0))

    auto_id, _, _, rola = sync.dolacz_po_kodzie("Zaproszenie: carsapp://app/dolacz/a1b2c3 — do zobaczenia")
    assert wyslane == ["A1B2C3"] and rola == db.ROLA_WSPOLAUTOR
    assert db.kody_dostepu(auto_id)["pelny"] is None, "kod roli nie staje się kodem pojazdu"

    # Tekst bez rozpoznawalnego kodu idzie jak dawniej — serwer odpowie, że zły.
    sync.dolacz_po_kodzie(" zly-kod ")
    assert wyslane[-1] == "ZLY-KOD"


# ======================================================= trasa /dolacz/<KOD>

@pytest.fixture
def uruchom(monkeypatch):
    """main.main() na świeżej stronie testowej, opcjonalnie z trasą startową
    (link, którym system otworzył aplikację); zwraca stronę."""
    monkeypatch.setattr(ft, "run", lambda *args, **kwargs: None)
    import log
    import main

    monkeypatch.setattr(log, "wlacz", lambda: True)
    monkeypatch.setitem(utils.wyglad._OSTATNI_MOTYW, "nazwa", utils.wyglad._OSTATNI_MOTYW["nazwa"])

    def _uruchom(trasa=None):
        strona = pomoce.zbuduj_strone()
        monkeypatch.setattr(type(strona.page), "run_task", lambda self, f, *a, **k: None)
        if trasa:
            strona.page.route = trasa
        main.main(strona.page)
        return strona

    return _uruchom


def test_link_na_zimnym_starcie_wpisuje_kod_i_nie_dolacza_sam(baza, uruchom):
    pomoce.utworz_pojazd("Moje auto")
    strona = uruchom("/dolacz/a1b2c3")

    assert [type(w).__name__ for w in strona.page.views] == ["MainView", "WspoldzielenieView"]
    widok = strona.page.views[-1]
    assert widok.route == "/dolacz/A1B2C3"
    assert widok.e_kod.value == "A1B2C3"
    assert "Dołącz" in [k.content for k in _kontrolki(widok) if isinstance(k, ft.Button)]
    assert _liczba_pojazdow() == 1, "sam link niczego nie dołącza"


def test_link_w_trakcie_pracy_i_link_bez_kodu(baza, uruchom):
    db.zapisz_widziana_wersje(db.WERSJA_APLIKACJI)
    strona = uruchom()
    utils.przejdz(strona.page, "/dolacz/B2C3D4")
    assert strona.page.views[-1].e_kod.value == "B2C3D4"

    utils.przejdz(strona.page, "/dolacz")
    widok = strona.page.views[-1]
    assert widok.e_kod.value == ""
    assert any("W linku nie było kodu" in t for t in _teksty(widok))


# ======================================================= ekran Współdzielenia

def _wlasciciel_z_kodami(nazwa="Octavia"):
    auto_id = pomoce.utworz_pojazd(nazwa, wspolny=True)["auto_id"]
    with db.polacz_baze() as conn:
        conn.execute("UPDATE samochody SET kod_zaproszenia=?, rola_wspoldzielenia=? WHERE id=?",
                     ("A1B2C3", db.ROLA_WLASCICIEL, auto_id))
    db.zapisz_kody_dostepu(auto_id, "B2C3D4", "C3D4E5")
    return auto_id


def test_ikona_qr_przy_kazdym_kodzie_otwiera_okno_tej_roli(baza, monkeypatch):
    auto_id = _wlasciciel_z_kodami()
    otwarte = []
    monkeypatch.setattr(zaproszenia, "otworz_dialog", lambda page, dlg: otwarte.append(dlg))

    strona = pomoce.zbuduj_strone()
    widok = WspoldzielenieView(strona.page, pomoce.stan_aplikacji(auto_id, "Octavia"))
    ikony = _ikony(widok, ft.Icons.QR_CODE_2)
    assert len(ikony) == 3, "pełny, współautor, podgląd"

    ikony[1].on_click(None)
    teksty = _teksty(otwarte[-1])
    assert {"B2C3D4", "carsapp://app/dolacz/B2C3D4", "Współautor"} <= set(teksty)


def test_gosc_nie_widzi_kodow_ani_qr(baza):
    stan, _ = pomoce.przygotuj_scenariusz("wspoldzielony_podglad")
    strona = pomoce.zbuduj_strone()
    widok = WspoldzielenieView(strona.page, stan)
    assert _ikony(widok, ft.Icons.QR_CODE_2) == []


def test_pole_kodu_ma_wklej(baza):
    strona = pomoce.zbuduj_strone()
    widok = WspoldzielenieView(strona.page, pomoce.stan_aplikacji())
    assert len(_ikony(widok, ft.Icons.CONTENT_PASTE)) == 1
    assert widok.route == "/wspoldzielenie"


# ======================================================= okno z kodem QR

def test_okno_przelacza_role_i_pokazuje_tylko_zalozone_kody(baza):
    strona = pomoce.zbuduj_strone()
    kody = {"pelny": "A1B2C3", "wspolautor": "B2C3D4", "podglad": None}
    okno = utils.OknoKoduQR(strona.page, kody, "Octavia", "podglad")
    assert okno.klucz == "pelny", "kodu podglądu nie ma — pierwszy założony"
    assert len(okno.przelacznik.content.content.controls) == 2
    assert okno.obraz.src[:4] == b"\x89PNG"

    pierwszy = okno.obraz.src
    okno.zmien_role(1)
    assert (okno.kod, okno.t_kod.value) == ("B2C3D4", "B2C3D4")
    assert okno.t_link.value == "carsapp://app/dolacz/B2C3D4"
    assert okno.t_rola.value == "Współautor" and okno.obraz.src != pierwszy

    jedyny = utils.OknoKoduQR(strona.page, {"pelny": "A1B2C3"}, "Octavia")
    assert jedyny.przelacznik.content is None, "jeden kod — bez przełącznika"
    with pytest.raises(ValueError):
        utils.OknoKoduQR(strona.page, {"pelny": None}, "Octavia")


def test_jasnosc_tylko_na_telefonie_i_wraca_raz(baza, monkeypatch):
    strona = pomoce.zbuduj_strone()
    zadania = []
    monkeypatch.setattr(type(strona.page), "run_task", lambda self, f, *a, **k: zadania.append(f))
    monkeypatch.setattr(zaproszenia, "otworz_dialog", lambda page, dlg: None)
    monkeypatch.setattr(zaproszenia, "zamknij_dialog", lambda page, dlg: None)

    utils.pokaz_kod_qr(strona.page, {"pelny": "A1B2C3"}, "Octavia").zamknij()
    assert zadania == [], "na komputerze jasności nie ruszamy"

    class Jasnosc:
        def __init__(self):
            self.wywolania = []

        async def set_application_screen_brightness(self, wartosc):
            self.wywolania.append(wartosc)

        async def reset_application_screen_brightness(self):
            self.wywolania.append("systemowa")

    strona.page.platform = ft.PagePlatform.ANDROID
    strona.page._jasnosc = jasnosc = Jasnosc()
    okno = utils.pokaz_kod_qr(strona.page, {"pelny": "A1B2C3"}, "Octavia")
    okno.zamknij()
    okno.dlg.on_dismiss(None)  # system zgłasza zamknięcie jeszcze raz
    for zadanie in zadania:
        asyncio.run(zadanie())
    assert jasnosc.wywolania == [1.0, "systemowa"]


def test_udostepnij_wysyla_zaproszenie_a_na_komputerze_kopiuje(baza, monkeypatch):
    strona = pomoce.zbuduj_strone()
    skopiowane = []
    monkeypatch.setattr(utils.system, "kopiuj_do_schowka",
                        lambda page, tekst, komunikat="": skopiowane.append(tekst))
    okno = utils.OknoKoduQR(strona.page, {"pelny": "A1B2C3", "podglad": "C3D4E5"}, "Octavia", "podglad")
    okno._udostepnij(None)
    assert skopiowane == [utils.tekst_zaproszenia("Octavia", db.ROLA_PODGLAD, "C3D4E5")]

    zadania = []
    monkeypatch.setattr(type(strona.page), "run_task", lambda self, f, *a, **k: zadania.append(f))

    class Arkusz:
        def __init__(self):
            self.wyslane = []

        async def share_text(self, tekst, subject=None):
            self.wyslane.append((tekst, subject))

    strona.page.platform = ft.PagePlatform.ANDROID
    strona.page.share_service = arkusz = Arkusz()
    okno._udostepnij(None)
    asyncio.run(zadania.pop()())
    assert arkusz.wyslane == [(skopiowane[0], "Zaproszenie do pojazdu „Octavia”")]


def test_wklej_bierze_kod_z_zaproszenia_a_bez_kodu_nie_rusza_pola(baza, monkeypatch):
    strona = pomoce.zbuduj_strone()
    zadania, komunikaty = [], []
    monkeypatch.setattr(type(strona.page), "run_task", lambda self, f, *a, **k: zadania.append(f))
    monkeypatch.setattr(zaproszenia, "pokaz_komunikat", lambda page, tekst, *a, **k: komunikaty.append(tekst))

    class Schowek:
        tekst = ""

        async def get(self):
            return self.tekst

    strona.page._schowek = schowek = Schowek()
    pole = ft.TextField(value="")

    schowek.tekst = utils.tekst_zaproszenia("Octavia", db.ROLA_PELNA, "A1B2C3")
    utils.wklej_kod_zaproszenia(strona.page, pole)
    asyncio.run(zadania.pop()())
    assert pole.value == "A1B2C3" and komunikaty == []

    schowek.tekst = "mleko, chleb, olej do frytek"
    utils.wklej_kod_zaproszenia(strona.page, pole)
    asyncio.run(zadania.pop()())
    assert pole.value == "A1B2C3"
    assert komunikaty == ["W schowku nie ma kodu ani linku zaproszenia."]
