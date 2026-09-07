"""Budowa wszystkich widoków bez okna.

Nie sprawdza wyglądu — sprawdza, że każdy ekran w ogóle daje się zbudować na
danych, które realnie występują: pusty garaż, auto bez ani jednego wpisu, auto
z kompletem wpisów, elektryk, hybryda plug-in, auto sprzedane. To jest ta klasa
błędów, która wychodzi dopiero po wejściu na ekran, a przy pustym garażu potrafi
nie wyjść nigdy u autora, bo on ma dane.

Maszyneria (odkrywanie klas, dobieranie argumentów, scenariusze danych) siedzi
w `pomoce.py`, bo korzysta z niej też `test_audyty.py`.
"""

import ast
import inspect
import pathlib

import flet as ft
import pytest

import db
import pomoce


KLASY_WIDOKOW = pomoce.klasy_widokow()


def test_znaleziono_wszystkie_widoki_z_routera(baza):
    """Widok używany przez router, którego nie ma w pakiecie `views`, uciekłby testom."""
    zrodlo = pathlib.Path(db.__file__).parent.parent / "main.py"
    drzewo = ast.parse(zrodlo.read_text(encoding="utf-8"))
    z_routera = set()
    for wezel in ast.walk(drzewo):
        if isinstance(wezel, ast.ImportFrom) and (wezel.module or "").startswith("views"):
            z_routera.update(alias.name for alias in wezel.names)

    assert z_routera, "main.py nie importuje już widoków — test wymaga aktualizacji"
    nieznalezione = z_routera - set(KLASY_WIDOKOW)
    assert nieznalezione == set(), (
        "widoki importowane przez main.py, których nie znalazło przejście pakietu: "
        + ", ".join(sorted(nieznalezione))
    )


@pytest.mark.parametrize("scenariusz", pomoce.SCENARIUSZE)
@pytest.mark.parametrize("nazwa_widoku", list(KLASY_WIDOKOW))
def test_widok_buduje_sie_bez_okna(baza, nazwa_widoku, scenariusz):
    stan, _ = pomoce.przygotuj_scenariusz(scenariusz)
    strona = pomoce.zbuduj_strone()

    widok = pomoce.zbuduj_widok(KLASY_WIDOKOW[nazwa_widoku], strona, stan)

    assert isinstance(widok, ft.View)
    assert pomoce.policz_kontrolki(widok) > 1, "widok nie narysował ani jednej kontrolki"


@pytest.mark.parametrize("nazwa_widoku", list(KLASY_WIDOKOW))
def test_formularz_buduje_sie_na_istniejacym_wpisie(baza, nazwa_widoku):
    """Tryb edycji: konstruktor dostaje prawdziwe ID i musi wczytać wpis.

    Widoki bez argumentu z identyfikatorem są tu pomijane — sprawdza je
    poprzedni test."""
    klasa = KLASY_WIDOKOW[nazwa_widoku]
    argumenty = set(inspect.signature(klasa.__init__).parameters) & set(pomoce.ARGUMENTY_IDENTYFIKATOROW)
    if not argumenty:
        pytest.skip("widok nie przyjmuje identyfikatora wpisu")

    identyfikatory = pomoce.utworz_pojazd("Pełny")
    stan = pomoce.stan_aplikacji(identyfikatory["auto_id"], "Pełny")
    strona = pomoce.zbuduj_strone()

    widok = pomoce.zbuduj_widok(klasa, strona, stan, identyfikatory)

    assert pomoce.policz_kontrolki(widok) > 1


@pytest.mark.parametrize("zakladka", [0, 1, 2, 3])
@pytest.mark.parametrize("scenariusz", ["pusty_garaz", "pojazd_bez_danych", "pojazd_z_danymi", "elektryk"])
def test_ekran_glowny_buduje_kazda_zakladke(baza, zakladka, scenariusz):
    """Kokpit, Serwis, Koszty i Analiza to cztery różne ekrany pod jedną klasą —
    i największa powierzchnia kodu w całej aplikacji."""
    stan, _ = pomoce.przygotuj_scenariusz(scenariusz)
    stan.zakladka = zakladka
    strona = pomoce.zbuduj_strone()

    widok = pomoce.zbuduj_widok(KLASY_WIDOKOW["MainView"], strona, stan)

    assert pomoce.policz_kontrolki(widok) > 1


@pytest.mark.parametrize("podzakladka", [0, 1])
def test_zakladka_kosztow_buduje_obie_podzakladki(baza, podzakladka):
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    stan.zakladka = 2
    stan.koszty_podzakladka = podzakladka
    strona = pomoce.zbuduj_strone()

    widok = pomoce.zbuduj_widok(KLASY_WIDOKOW["MainView"], strona, stan)

    assert pomoce.policz_kontrolki(widok) > 1
