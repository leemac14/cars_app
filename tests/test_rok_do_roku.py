"""Rok do roku jako dwie krzywe na jednej osi miesięcy.

Porównanie rok do roku istniało jako ZDANIE („drożej o 23%") i liczba
w podsumowaniu roku. Obie mówią, O ILE. Nałożone krzywe mówią, OD KIEDY —
a to zwykle wskazuje konkretne zdarzenie: miesiąc, w którym zaczął się
abonament albo wypadła droga naprawa.

Testy pilnują: że krzywe stoją na tej samej osi dwunastu miesięcy i że rok
w toku urywa się na bieżącym miesiącu (po obu stronach porównania), że suma
narastająca liczy się od stycznia, a iloraz z sum składników, a nie jako
średnia miesięcznych ilorazów — i że miesiąc rozjazdu wskazuje zdarzenie
tylko wtedy, gdy zdarzenie było.
"""

from datetime import date

import flet as ft

import db
import pomoce
import utils

POLA_DZIECI = ("controls", "content", "items", "actions", "leading", "trailing", "title", "subtitle")

ROK = date.today().year
POPRZEDNI, PRZEDPOPRZEDNI = ROK - 1, ROK - 2


def _auto(nazwa="Rok do roku"):
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO samochody (nazwa, typ_paliwa, status) VALUES (?,?,?)",
            (nazwa, "Benzyna", db.STATUS_POJAZDU_AKTYWNY),
        )
        return c.lastrowid


def _tankowanie(auto_id, rok, miesiac, kwota, przebieg):
    with db.polacz_baze() as conn:
        conn.execute(
            "INSERT INTO tankowania (auto_id, data, przebieg, litry, kwota, stacja) "
            "VALUES (?,?,?,?,?,?)",
            (auto_id, date(rok, miesiac, 15).strftime("%d.%m.%Y"), przebieg,
             kwota / 6.0, kwota, "Orlen"),
        )


def _wizyta(auto_id, rok, miesiac, kwota):
    with db.polacz_baze() as conn:
        conn.execute(
            "INSERT INTO wizyty (auto_id, data, przebieg, wykonawca, koszt_calkowity) VALUES (?,?,?,?,?)",
            (auto_id, date(rok, miesiac, 20).strftime("%d.%m.%Y"), 0, "Warsztat", kwota),
        )


def _rok_rowny(auto_id, rok, kwota=500.0, km=1000, przebieg_startowy=100000, do_miesiaca=12):
    """Jedno tankowanie na miesiąc: równy koszt i równy przebieg."""
    for m in range(1, do_miesiaca + 1):
        _tankowanie(auto_id, rok, m, kwota, przebieg_startowy + m * km)


def _trzy_lata(auto_id, kwota_p=500.0, kwota_pp=500.0):
    """Dwa porównywane lata plus rok wcześniej — żeby styczeń najstarszego
    z porównywanych miał od czego odjąć licznik."""
    _rok_rowny(auto_id, PRZEDPOPRZEDNI - 1, kwota=400.0, przebieg_startowy=50000)
    _rok_rowny(auto_id, PRZEDPOPRZEDNI, kwota=kwota_pp, przebieg_startowy=62000)
    _rok_rowny(auto_id, POPRZEDNI, kwota=kwota_p, przebieg_startowy=74000)


def _teksty(korzen):
    znalezione = []

    def zejdz(kontrolka):
        if isinstance(kontrolka, ft.Text) and kontrolka.value:
            znalezione.append(str(kontrolka.value))
        for nazwa in POLA_DZIECI:
            wartosc = getattr(kontrolka, nazwa, None)
            if isinstance(wartosc, (list, tuple)):
                for dziecko in wartosc:
                    if isinstance(dziecko, ft.Control):
                        zejdz(dziecko)
            elif isinstance(wartosc, ft.Control):
                zejdz(wartosc)

    zejdz(korzen)
    return znalezione


# ----------------------------------------------------------------- dwie osie

def test_obie_krzywe_na_dwunastu_miesiacach(baza):
    auto_id = _auto()
    _trzy_lata(auto_id)
    dane = db.koszty_rok_do_roku(auto_id, rok=POPRZEDNI)

    assert dane["rok"] == POPRZEDNI and dane["rok_poprzedni"] == PRZEDPOPRZEDNI
    assert len(dane["biezacy"]) == 12 and len(dane["poprzedni"]) == 12
    assert dane["niepelny"] is False and dane["ostatni_miesiac"] == 12
    assert all(w is not None for w in dane["biezacy"])


def test_narastajaco_sumuje_od_stycznia(baza):
    auto_id = _auto()
    _trzy_lata(auto_id, kwota_p=600.0, kwota_pp=500.0)
    dane = db.koszty_rok_do_roku(auto_id, rok=POPRZEDNI, narastajaco=True)

    assert dane["biezacy"][0] == 600.0
    assert dane["biezacy"][11] == 7200.0
    assert dane["poprzedni"][11] == 6000.0
    assert dane["roznica_koncowa"] == 1200.0
    assert dane["zmiana_proc"] == 20.0


def test_miesiecznie_pokazuje_pojedynczy_skok(baza):
    """Na krzywej narastającej jednorazowa naprawa zostaje jako trwałe
    przesunięcie; w postaci miesięcznej widać, że to był jeden miesiąc."""
    auto_id = _auto()
    _trzy_lata(auto_id)
    _wizyta(auto_id, POPRZEDNI, 5, 6000.0)

    narastajaco = db.koszty_rok_do_roku(auto_id, rok=POPRZEDNI, narastajaco=True)
    miesiecznie = db.koszty_rok_do_roku(auto_id, rok=POPRZEDNI, narastajaco=False)

    assert narastajaco["biezacy"][4] == 8500.0 and narastajaco["biezacy"][5] == 9000.0
    assert miesiecznie["biezacy"][4] == 6500.0 and miesiecznie["biezacy"][5] == 500.0


# -------------------------------------------------------------- miesiąc rozjazdu

def test_miesiac_rozjazdu_wskazuje_zdarzenie(baza):
    """Jedna droga naprawa w maju — i to maj ma być wskazany, niezależnie od
    tego, w której postaci patrzy się na krzywe."""
    auto_id = _auto()
    _trzy_lata(auto_id)
    _wizyta(auto_id, POPRZEDNI, 5, 6000.0)

    for narastajaco in (True, False):
        dane = db.koszty_rok_do_roku(auto_id, rok=POPRZEDNI, narastajaco=narastajaco)
        assert dane["miesiac_rozjazdu"] == 5
        assert dane["roznica_koncowa"] == 6000.0


def test_stopniowa_roznica_nie_dostaje_miesiaca(baza):
    """Równomiernie droższy rok nie ma miesiąca, w którym „się rozjechało” —
    wskazanie palcem jednego byłoby zmyślaniem."""
    auto_id = _auto()
    _trzy_lata(auto_id, kwota_p=700.0, kwota_pp=500.0)
    dane = db.koszty_rok_do_roku(auto_id, rok=POPRZEDNI)

    assert dane["roznica_koncowa"] == 2400.0
    assert dane["miesiac_rozjazdu"] is None


def test_tanszy_rok_tez_ma_swoj_miesiac(baza):
    """Rozjazd działa w obie strony: rok z jedną wielką naprawą w tle wypada
    lepiej od poprzedniego i to też ma swój moment."""
    auto_id = _auto()
    _trzy_lata(auto_id)
    _wizyta(auto_id, PRZEDPOPRZEDNI, 9, 8000.0)
    dane = db.koszty_rok_do_roku(auto_id, rok=POPRZEDNI)

    assert dane["roznica_koncowa"] == -8000.0
    assert dane["miesiac_rozjazdu"] == 9


# ------------------------------------------------------------------ rok w toku

def test_rok_w_toku_porownuje_te_same_miesiace(baza):
    """Styczeń–maj kontra styczeń–maj. Porównanie niepełnego roku z CAŁYM
    poprzednim pokazywałoby spadek, którego nie ma."""
    auto_id = _auto()
    biezacy_miesiac = date.today().month
    _rok_rowny(auto_id, POPRZEDNI - 1, kwota=400.0, przebieg_startowy=50000)
    _rok_rowny(auto_id, POPRZEDNI, kwota=500.0, przebieg_startowy=62000)
    _rok_rowny(auto_id, ROK, kwota=600.0, przebieg_startowy=74000, do_miesiaca=biezacy_miesiac)
    dane = db.koszty_rok_do_roku(auto_id, rok=ROK)

    assert dane["niepelny"] is True
    assert dane["ostatni_miesiac"] == biezacy_miesiac
    # Krzywa bieżącego roku urywa się na dzisiaj, poprzedni rok leci do grudnia.
    assert dane["biezacy"][biezacy_miesiac - 1] is not None
    if biezacy_miesiac < 12:
        assert dane["biezacy"][biezacy_miesiac] is None
        assert dane["poprzedni"][11] == 6000.0
    assert dane["zmiana_proc"] == 20.0


# -------------------------------------------------------------- inne wielkości

def test_kilometry_jako_wielkosc(baza):
    auto_id = _auto()
    _trzy_lata(auto_id)
    dane = db.koszty_rok_do_roku(auto_id, rok=POPRZEDNI, wielkosc="km")

    assert dane["jednostka"] == "km"
    assert dane["wzrost_zly"] is False
    assert dane["biezacy"][11] == 12000.0


def test_cena_jazdy_liczona_z_sum_a_nie_ze_srednich(baza):
    """Iloraz miesięcznych ilorazów kłamie: miesiąc ze stu kilometrami ważyłby
    tyle samo, co grudzień z tysiącem."""
    auto_id = _auto()
    _rok_rowny(auto_id, PRZEDPOPRZEDNI - 1, kwota=400.0, przebieg_startowy=50000)
    _rok_rowny(auto_id, PRZEDPOPRZEDNI, kwota=500.0, przebieg_startowy=62000)
    # Styczeń: 100 km za 1000 zł, reszta roku po 1000 km za 500 zł.
    _tankowanie(auto_id, POPRZEDNI, 1, 1000.0, 74100)
    for m in range(2, 13):
        _tankowanie(auto_id, POPRZEDNI, m, 500.0, 74100 + (m - 1) * 1000)

    dane = db.koszty_rok_do_roku(auto_id, rok=POPRZEDNI, wielkosc="koszt1000")
    koszt, km = 1000.0 + 11 * 500.0, 100 + 11 * 1000

    assert round(dane["biezacy"][11], 6) == round(koszt / km * 1000, 6)
    assert dane["biezacy"][0] == 1000.0 / 100 * 1000


def test_kategoria_osobno(baza):
    auto_id = _auto()
    _trzy_lata(auto_id)
    _wizyta(auto_id, POPRZEDNI, 5, 6000.0)
    dane = db.koszty_rok_do_roku(auto_id, rok=POPRZEDNI, wielkosc="serwis")

    assert dane["etykieta"] == "Serwis"
    assert dane["biezacy"][11] == 6000.0
    assert dane["poprzedni"][11] == 0.0


def test_nieznana_wielkosc_wraca_do_kosztow(baza):
    auto_id = _auto()
    _trzy_lata(auto_id)
    assert db.koszty_rok_do_roku(auto_id, rok=POPRZEDNI, wielkosc="cokolwiek")["wielkosc"] == "razem"


def test_pusty_pojazd_nie_wywraca_sie(baza):
    assert db.koszty_rok_do_roku(None)["biezacy"] == []
    assert db.koszty_rok_do_roku(_auto("Goły"))["lata"] == []


# ----------------------------------------------------------------- wykres

def test_wykres_ma_dwie_krzywe_slupki_i_zero_na_osi(baza):
    auto_id = _auto()
    _trzy_lata(auto_id)
    _wizyta(auto_id, POPRZEDNI, 5, 6000.0)
    strona = pomoce.zbuduj_strone()
    dane = db.koszty_rok_do_roku(auto_id, rok=POPRZEDNI)
    wykres = utils.wykres_rok_do_roku(strona.page, dane)

    czart = wykres.controls[0].content
    assert czart.min_y == 0 and czart.min_x == 0 and czart.max_x == 11
    # Ostatnie dwie serie to krzywe lat, wcześniejsze to słupki różnicy.
    assert len(czart.data_series) > 2
    assert czart.data_series[-2].dash_pattern, "poprzedni rok ma być przerywany"
    assert not czart.data_series[-1].dash_pattern
    assert len(czart.data_series[-1].points) == 12


def test_karta_mowi_w_ktorym_miesiacu_sie_rozjechalo(baza):
    auto_id = _auto()
    _trzy_lata(auto_id)
    _wizyta(auto_id, POPRZEDNI, 5, 6000.0)
    stan = pomoce.stan_aplikacji(auto_id, "Rok do roku")
    stan.rdr_rok = POPRZEDNI
    karta = utils.karta_rok_do_roku(pomoce.zbuduj_strone().page, stan, rok=POPRZEDNI)
    teksty = _teksty(karta)

    assert any("Rozjechało się w maju" in t for t in teksty)
    assert any("kontra" in t for t in teksty)
    # Chipy wielkości: wszystkie sześć, plus przełącznik postaci krzywej.
    for opis, _jedn, _zly in db.WIELKOSCI_RDR.values():
        assert opis in teksty
    assert "Narastająco" in teksty and "Miesięcznie" in teksty


def test_karta_bez_poprzedniego_roku_mowi_o_braku(baza):
    auto_id = _auto()
    _rok_rowny(auto_id, POPRZEDNI, przebieg_startowy=62000)
    stan = pomoce.stan_aplikacji(auto_id, "Rok do roku")
    karta = utils.karta_rok_do_roku(pomoce.zbuduj_strone().page, stan, rok=POPRZEDNI)

    assert any("Brak danych do porównania" in t for t in _teksty(karta))


def test_stopniowa_roznica_ma_wlasne_zdanie(baza):
    auto_id = _auto()
    _trzy_lata(auto_id, kwota_p=700.0, kwota_pp=500.0)
    stan = pomoce.stan_aplikacji(auto_id, "Rok do roku")
    karta = utils.karta_rok_do_roku(pomoce.zbuduj_strone().page, stan, rok=POPRZEDNI)

    assert any("narastała stopniowo" in t for t in _teksty(karta))
