"""Liczniki wyników przy chipach filtrów.

Pytanie, na które chip ma odpowiadać, zanim się go kliknie, brzmi: „czy po
wybraniu tej wartości cokolwiek zostanie”. Dlatego licznik jest KRZYŻOWY —
liczy przy pozostałych filtrach ustawionych tak, jak są teraz. Licznik liczony
na surowej liście nigdy nie pokazałby zera (opcje biorą się z danych, więc
każda ma co najmniej jeden wpis) i obiecywałby wpisy, których po sąsiednim
filtrze już nie ma.

Testy pilnują trzech rzeczy: że licznik mówi to samo, co potem pokazuje lista,
że własny filtr NIE wpływa na swoje liczniki (inaczej po wybraniu wartości
wszystkie pozostałe pokazałyby zero) i że opcja bez pokrycia zostaje w menu —
tylko przestaje być klikalna.
"""

import flet as ft
import pytest

import db
import pomoce
import utils


def wpis(data, zrodlo, tagi="", autor=None):
    return {"data": data, "rodzaj_opis": zrodlo, "tagi": tagi, "dodane_przez": autor}


# 12 tankowań i 3 ładowania w 2026, w 2025 samo paliwo — czyli dokładnie ten
# układ, w którym „Prąd” po wybraniu roku 2025 nie wybierze niczego.
DANE = (
    [wpis(f"2026-0{m}-10", "Paliwo", "trasa" if m % 2 else "") for m in range(1, 7)]
    + [wpis(f"2026-0{m}-20", "Paliwo") for m in range(1, 7)]
    + [wpis(f"2026-0{m}-15", "Prąd") for m in range(1, 4)]
    + [wpis(f"2025-0{m}-10", "Paliwo") for m in range(1, 5)]
)

SPIS = [
    ("kategoria", "t_zrodlo", "rodzaj_opis", "Źródło"),
    ("rok", "t_rok", "data"),
    ("kategoria", "t_tagi", "tagi", "Tagi"),
]


def zbuduj(stan, dane=DANE, spis=SPIS):
    strona = pomoce.zbuduj_strone().page
    return utils.pasek_filtrow(strona, stan, dane, spis)


def menu(chip):
    """[(opcja, licznik, czy klikalna)] z rozwijanego menu chipa."""
    pozycje = []
    for poz in chip.content.items:
        teksty = [k for k in poz.content.controls if isinstance(k, ft.Text)]
        pozycje.append((teksty[0].value, teksty[1].value, not poz.disabled))
    return pozycje


def liczniki(chip):
    return {opcja: licznik for opcja, licznik, _ in menu(chip)}


def napis_chipa(chip):
    return [k for k in chip.content.content.controls if isinstance(k, ft.Text)][0].value


@pytest.fixture
def stan():
    return pomoce.stan_aplikacji()


# --------------------------------------------------------------- licznik


def test_licznik_stoi_przy_kazdej_opcji(stan):
    (chip_zrodlo, chip_rok, _), wynik = zbuduj(stan)

    assert liczniki(chip_zrodlo) == {"Wszystko": "(19)", "Paliwo": "(16)", "Prąd": "(3)"}
    assert liczniki(chip_rok) == {"Wszystko": "(19)", "2026": "(15)", "2025": "(4)"}
    assert len(wynik) == 19


def test_licznik_uwzglednia_pozostale_filtry(stan):
    """Rok 2025 to same tankowania — „Prąd” przestaje cokolwiek wybierać."""
    stan.filtry["t_rok"] = "2025"
    (chip_zrodlo, _, _), wynik = zbuduj(stan)

    assert liczniki(chip_zrodlo) == {"Wszystko": "(4)", "Paliwo": "(4)", "Prąd": "(0)"}
    assert len(wynik) == 4


def test_wlasny_filtr_nie_psuje_swoich_licznikow(stan):
    """Po wybraniu „Paliwo” sąsiednie wartości muszą dalej pokazywać SWOJE
    liczby. Gdyby licznik liczył na danych już odsianych tym samym filtrem,
    każda inna opcja pokazałaby zero i nie dałoby się przełączyć na drugą."""
    stan.filtry["t_zrodlo"] = "Paliwo"
    (chip_zrodlo, chip_rok, _), wynik = zbuduj(stan)

    assert liczniki(chip_zrodlo)["Prąd"] == "(3)"
    # Rok liczy się już z uwzględnieniem wybranego źródła.
    assert liczniki(chip_rok) == {"Wszystko": "(16)", "2026": "(12)", "2025": "(4)"}
    assert len(wynik) == 16


def test_licznik_na_chipie_zgadza_sie_z_lista(stan):
    stan.filtry["t_zrodlo"] = "Prąd"
    (chip_zrodlo, _, _), wynik = zbuduj(stan)

    assert napis_chipa(chip_zrodlo) == "Prąd (3)"
    assert len(wynik) == 3


def test_chip_bez_wyboru_pokazuje_sama_nazwe(stan):
    (chip_zrodlo, chip_rok, chip_tagi), _ = zbuduj(stan)

    assert [napis_chipa(c) for c in (chip_zrodlo, chip_rok, chip_tagi)] == ["Źródło", "Rok", "Tagi"]


def test_dluga_wartosc_ustepuje_licznikowi(stan):
    """Skracamy wartość, nie liczbę — po liczbę się na chip patrzy."""
    dane = [wpis("2026-01-10", "Paliwo", "przegląd okresowy")]
    stan.filtry["t_tagi"] = "przegląd okresowy"
    (_, _, chip_tagi), _ = zbuduj(stan, dane)

    assert napis_chipa(chip_tagi) == "przeglą.. (1)"


# ----------------------------------------------------------- opcje w menu


def test_opcja_bez_pokrycia_zostaje_ale_nie_klika(stan):
    """Ukrywanie przestawiałoby listę przy każdej zmianie sąsiada — a „(0)” to
    właśnie ta odpowiedź, po którą zagląda się do menu."""
    stan.filtry["t_rok"] = "2025"
    (chip_zrodlo, _, _), _ = zbuduj(stan)

    assert menu(chip_zrodlo) == [("Wszystko", "(4)", True),
                                 ("Paliwo", "(4)", True),
                                 ("Prąd", "(0)", False)]


def test_opcje_nie_znikaja_przy_wlaczonym_filtrze(stan):
    """Lista opcji bierze się z danych NIEfiltrowanych — menu ma nie skakać."""
    stan.filtry["t_zrodlo"] = "Prąd"
    (_, chip_rok, _), _ = zbuduj(stan)

    assert [o for o, _, _ in menu(chip_rok)] == ["Wszystko", "2026", "2025"]
    assert liczniki(chip_rok)["2025"] == "(0)"


def test_wybrana_opcja_zostaje_klikalna(stan):
    """Wybrana wartość bez wyników nie może się zablokować — inaczej nie dałoby
    się z niej wyjść inaczej niż przez „Wszystko”."""
    stan.filtry["t_rok"] = "2025"
    stan.filtry["t_zrodlo"] = "Prąd"
    (chip_zrodlo, _, _), wynik = zbuduj(stan)

    assert ("Prąd", "(0)", True) in menu(chip_zrodlo)
    assert wynik == []


def test_zapomniany_filtr_wraca_do_wszystko(stan):
    """Tag skasowany po zapisaniu filtra nie może odsiewać po cichu."""
    stan.filtry["t_tagi"] = "nie ma takiego tagu"
    (chip_zrodlo, _, chip_tagi), wynik = zbuduj(stan)

    assert stan.filtry["t_tagi"] == "Wszystko"
    assert napis_chipa(chip_tagi) == "Tagi"
    assert liczniki(chip_zrodlo)["Paliwo"] == "(16)"
    assert len(wynik) == 19


# ------------------------------------------------------- wynik i autorzy


@pytest.mark.parametrize("filtry", [
    {},
    {"t_rok": "2026"},
    {"t_zrodlo": "Paliwo", "t_rok": "2026"},
    {"t_zrodlo": "Prąd", "t_tagi": "trasa"},
])
def test_wynik_taki_sam_jak_lancuch_filtrow(stan, filtry):
    """`pasek_filtrow` ma oddawać dokładnie to, co dawał ręczny łańcuch —
    liczniki są dodatkiem, a nie nową regułą filtrowania."""
    stan.filtry.update(filtry)
    _, wynik = zbuduj(stan)

    oczekiwane = utils.filtruj_po_kategorii(DANE, stan, "t_zrodlo", "rodzaj_opis")
    oczekiwane = utils.filtruj_po_roku(oczekiwane, stan, "t_rok", "data")
    oczekiwane = utils.filtruj_po_kategorii(oczekiwane, stan, "t_tagi", "tagi")
    assert wynik == oczekiwane


def test_licznik_autora_liczy_moje_i_bez_autora(baza, stan):
    db.zapisz_moje_imie("Ala")
    dane = [wpis("2026-01-10", "Paliwo", autor="Ala"),
            wpis("2026-01-11", "Paliwo", autor="Ala"),
            wpis("2026-02-10", "Paliwo", autor="Bartek"),
            wpis("2026-02-11", "Paliwo", autor=None)]
    spis = [("autor", "t_autor", "dodane_przez"), ("rok", "t_rok", "data")]

    (chip_autor, _), _ = zbuduj(stan, dane, spis)

    assert liczniki(chip_autor) == {"Wszystko": "(4)", "Tylko moje": "(2)",
                                    "Bartek": "(1)", "Bez autora": "(1)"}
