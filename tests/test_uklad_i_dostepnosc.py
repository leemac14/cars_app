"""Układ ekranu głównego i dostępność (unowocześnienie 16.10.2026): siatka kokpitu bez
dziur, pasek auta poza Kokpitem, zdjęcie 16:9 (W-18), skala tekstu i gęstość list (W-10),
czytnik ekranu i cele dotyku (W-19), puste stany z rysunkiem (W-12)."""

import ast

import flet as ft
import pytest

import audyty
import db
import pomoce
import utils
from views.ekran_glowny.kokpit import KOL_KAFLA_1X1, KOL_KAFLA_2X1, upakuj_kafelki


def _kafel(nazwa, duzy=False):
    return ft.Container(data=nazwa, col=KOL_KAFLA_2X1 if duzy else KOL_KAFLA_1X1)


def test_maly_kafelek_przed_duzym_dostaje_sasiada():
    kafelki = [_kafel("termin"), _kafel("odliczania", True), _kafel("wydatki", True),
               _kafel("koszt_km"), _kafel("uloz")]
    assert [k.data for k in upakuj_kafelki(kafelki)] == ["termin", "koszt_km", "odliczania", "wydatki", "uloz"]


def test_bez_malego_na_zapas_kolejnosc_zostaje():
    kafelki = [_kafel("a", True), _kafel("b"), _kafel("c", True)]
    assert [k.data for k in upakuj_kafelki(kafelki)] == ["a", "b", "c"]
    assert upakuj_kafelki([]) == []


def _glowny(stan, zakladka=0):
    stan.zakladka = zakladka
    strona = pomoce.zbuduj_strone()
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], strona, stan)
    return strona, widok


def test_siatka_kokpitu_nie_ma_dziury_przed_duzym_kafelkiem(baza):
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_historia")
    db.zapisz_widgety_kokpitu(list(db.KOKPIT_WIDGETY), stan.auto_id)
    _strona, widok = _glowny(stan)
    (siatka,) = [r for r in pomoce.kontrolki(widok, ft.ResponsiveRow) if r.controls and getattr(r.controls[0], "col", None) in (KOL_KAFLA_1X1, KOL_KAFLA_2X1)]
    szerokosci = [2 if k.col == KOL_KAFLA_2X1 else 1 for k in siatka.controls]
    zajete = 0
    for i, szer in enumerate(szerokosci):
        if zajete == 1 and szer == 2:
            assert 1 not in szerokosci[i:], f"luka przed dużym kafelkiem, choć mały czeka dalej: {szerokosci}"
        zajete = (zajete + szer) % 2


def test_pelna_karta_tylko_na_kokpicie(baza):
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    _strona, widok = _glowny(stan, 0)
    assert widok.naglowek_auta.content is widok._naglowek_pelny

    widok.przelacz_zakladke(2)
    assert widok.naglowek_auta.content is widok._naglowek_kompaktowy
    assert "Pełny" in pomoce.napisy(widok.naglowek_auta.content)

    widok.przelacz_zakladke(0)
    assert widok.naglowek_auta.content is widok._naglowek_pelny


@pytest.mark.parametrize("zakladka", [1, 2, 3])
def test_inne_zakladki_startuja_z_paskiem_auta(baza, zakladka):
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    _strona, widok = _glowny(stan, zakladka)
    assert widok.naglowek_auta.content is widok._naglowek_kompaktowy


def test_zdjecie_auta_16_9_bez_rozmycia(baza):
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    _strona, widok = _glowny(stan)
    karta = widok._naglowek_pelny
    assert [k for k in pomoce.kontrolki(karta, ft.Container) if k.aspect_ratio == pytest.approx(16 / 9)]
    assert not [k for k in pomoce.kontrolki(karta, ft.Container) if k.blur is not None]
    assert "Pełny" in pomoce.napisy(karta)


def test_bez_zdjecia_karta_po_staremu(baza):
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_bez_danych")
    _strona, widok = _glowny(stan)
    assert not [k for k in pomoce.kontrolki(widok._naglowek_pelny, ft.Container) if k.aspect_ratio]


# ============================================================================
#  W-10 — SKALA TEKSTU I GĘSTOŚĆ LIST
# ============================================================================

@pytest.fixture
def skala():
    yield utils.ustaw_skale_tekstu
    utils.ustaw_skale_tekstu(1.0)


def test_skala_tekstu_mnozy_napisy_i_style_motywu(skala):
    assert ft.Text("x", size=10).size == 10 and utils.style_tekstu_motywu() is None

    skala(db.SKALE_TEKSTU["wiekszy"])
    assert ft.Text("x", size=10).size == pytest.approx(11.5)
    assert ft.Text("x").size is None, "napis bez rozmiaru bierze go z motywu"
    style = utils.style_tekstu_motywu()
    assert style.body_medium.size == pytest.approx(16.1) and style.body_medium.color == ft.Colors.ON_SURFACE
    assert utils.zbuduj_motyw(ft.Colors.INDIGO).text_theme is not None

    skala(db.SKALE_TEKSTU["mniejszy"])
    assert ft.Text("x", size=20).size == pytest.approx(18)


def test_skala_tekstu_zapisuje_sie(baza):
    assert db.pobierz_skale_tekstu() == "normalny"
    db.zapisz_skale_tekstu("wiekszy")
    db.zapisz_skale_tekstu("olbrzymi")
    assert db.pobierz_skale_tekstu() == "wiekszy"


def test_gestosc_list_zmienia_odstepy_kart(baza):
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_historia")
    stan.koszty_podzakladka = 0
    _strona, widok = _glowny(stan, 2)
    assert widok.lista_kart_tankowania.spacing == 15 and utils.wypelnienie_karty() == 16

    db.zapisz_gestosc_list("zwarte")
    _strona, widok = _glowny(stan, 2)
    assert widok.lista_kart_tankowania.spacing == 8 and utils.wypelnienie_karty() == 10


def test_ustawienia_maja_skale_gestosc_i_wibracje(baza):
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    strona = pomoce.zbuduj_strone()
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["UstawieniaView"], strona, stan)
    napisy = pomoce.napisy(widok)
    for napis in ("Wielkość tekstu", "Mniejszy", "Większy", "Gęstość list", "Zwarte", "Wibracje"):
        assert napis in napisy, napis


# ============================================================================
#  W-19 — CZYTNIK EKRANU I CELE DOTYKU
# ============================================================================

def test_tablica_czyta_sie_jako_numer():
    tablica = utils.tablica_rejestracyjna("po 4k821")
    assert isinstance(tablica, ft.Semantics) and tablica.label == "Numer rejestracyjny PO 4K821"
    assert tablica.exclude_semantics


def test_pasek_terminu_i_kondycja_maja_opis(baza):
    pasek = utils.pasek_terminu(None, {"klucz": "oc", "etykieta": "OC", "data": "01.11.2026",
                                       "dni": 16, "status": "blisko", "prog": 30})
    (tor,) = pomoce.kontrolki(pasek, ft.ProgressBar)
    assert tor.semantics_label == "OC" and tor.semantics_value == "za 16 dni"

    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    _strona, widok = _glowny(stan)
    pierscienie = pomoce.kontrolki(widok.naglowek_auta, ft.ProgressRing)
    assert pierscienie and all(p.semantics_label == "Kondycja pojazdu" for p in pierscienie)


def test_przyciski_ikon_maja_cel_dotyku_co_najmniej_40_dp():
    """Jawna szerokość albo wysokość przycisku z ikoną zawęża cel dotyku (domyślnie 48 dp)."""
    za_male = []
    for plik in audyty._pliki_projektu():
        for wezel in ast.walk(ast.parse(plik.read_text(encoding="utf-8"))):
            if isinstance(wezel, ast.Call) and getattr(wezel.func, "attr", "") == "IconButton":
                for k in wezel.keywords:
                    if k.arg in ("width", "height") and isinstance(k.value, ast.Constant) and k.value.value < 40:
                        za_male.append(f"{plik.name}:{wezel.lineno} {k.arg}={k.value.value}")
    assert za_male == []


# ============================================================================
#  W-12 — PUSTE STANY Z RYSUNKIEM
# ============================================================================

def test_pusty_ekran_ma_rysunek_a_nie_sama_ikone():
    ekran = utils.ekran_braku_danych(ft.Icons.LOCAL_GAS_STATION, "Brak tankowań", "Opis", "Dodaj", lambda e: None)
    (rysunek,) = pomoce.kontrolki(ekran, ft.Stack)
    ikony = [i.icon for i in pomoce.kontrolki(rysunek, ft.Icon)]
    assert ft.Icons.LOCAL_GAS_STATION in ikony and len(pomoce.kontrolki(rysunek, ft.Container)) >= 5
    assert "Brak tankowań" in pomoce.napisy(ekran)


def test_widoki_nie_rysuja_pustego_stanu_sama_duza_ikona():
    """Wersje „tylko podgląd” pustych ekranów biorą ten sam rysunek co zwykłe."""
    duze = []
    for plik in audyty._pliki_projektu():
        if "views" not in plik.parts:
            continue
        for wezel in ast.walk(ast.parse(plik.read_text(encoding="utf-8"))):
            if isinstance(wezel, ast.Call) and getattr(wezel.func, "attr", "") == "Icon":
                rozmiar = next((k.value.value for k in wezel.keywords
                                if k.arg == "size" and isinstance(k.value, ast.Constant)), 0)
                if rozmiar >= 44:
                    duze.append(f"{plik.name}:{wezel.lineno}")
    assert duze == []
