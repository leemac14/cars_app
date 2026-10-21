"""Analiza › Wykresy: spis pytań i ekran jednego wykresu (/wykres/<klucz>).

Pilnujemy: spis w trzech grupach z odpowiedzią na każde pytanie, ekran każdego wykresu
z opisem i „Następnym wykresem”, dymki bez surowych liczb, podpisy osi na kreskach
podziałki (inaczej Flet ich nie rysuje), audyty drzewa na 360 dp, kafelki kokpitu
prowadzące do swojego wykresu i Liczby na powierzchniach zamiast ft.Card.
"""

import random
from datetime import date, timedelta

import flet as ft
import flet_charts as fc
import pytest

import audyty
import db
import pomoce
import utils


# ============================================================================
#  POMOCNIKI
# ============================================================================

def _d(x):
    return x.strftime("%d.%m.%Y")


def bogate_auto(nazwa="Octavia", paliwo="Benzyna"):
    """Ponad dwa lata historii: tankowania do pełna na kilku stacjach, serwis z rodzajem
    i robocizną, inne koszty w kilku kategoriach, cena i data zakupu."""
    los = random.Random(7)
    dzis = date.today()
    start = date(dzis.year - 2, 3, 12)
    prad = paliwo == "Elektryczny"
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO samochody (nazwa, typ_paliwa, status, rola_wspoldzielenia, data_zakupu, "
                  "cena_zakupu, przebieg_zakupu) VALUES (?,?,?,?,?,?,?)",
                  (nazwa, paliwo, db.STATUS_POJAZDU_AKTYWNY, db.ROLA_WLASCICIEL, _d(start), 42000.0, 98000))
        auto_id = c.lastrowid
        przebieg, dzien = 98000, start
        while dzien <= dzis:
            km = los.randint(380, 560)
            przebieg += km
            ilosc = round(km * (16.0 if prad else 6.8 + los.uniform(-0.5, 0.6)) / 100, 2)
            stacja = los.choice(["Orlen", "BP", "Shell", "Moya"])
            cena = (1.1 if prad else 6.1) + los.uniform(-0.2, 0.3)
            c.execute("INSERT INTO tankowania (auto_id, data, przebieg, dystans, litry, kwota, do_pelna, stacja, "
                      "rodzaj_energii) VALUES (?,?,?,?,?,?,?,?,?)",
                      (auto_id, _d(dzien), przebieg, km, ilosc, round(ilosc * cena, 2), 1, stacja,
                       db.ENERGIA_PRAD if prad else db.ENERGIA_PALIWO))
            dzien += timedelta(days=los.randint(8, 13))
        zadania = {}
        for nazwa_z in ("Filtr kabinowy", "Alternator", "Klocki hamulcowe"):
            c.execute("INSERT INTO zadania (auto_id, nazwa, interwal_km) VALUES (?,?,?)", (auto_id, nazwa_z, 0))
            zadania[nazwa_z] = c.lastrowid
        for dni, warsztat, koszt, robocizna, rodzaj, zadanie in (
                (700, "Serwis ASO", 690.0, 250.0, db.SERWIS_PLANOWE, "Filtr kabinowy"),
                (520, "Warsztat u Janka", 1850.0, 450.0, db.SERWIS_AWARIA, "Alternator"),
                (300, "Warsztat u Janka", 920.0, 300.0, db.SERWIS_PLANOWE, "Klocki hamulcowe"),
                (120, "Warsztat u Janka", 560.0, 60.0, db.SERWIS_AWARIA, "Alternator")):
            kiedy = _d(dzis - timedelta(days=dni))
            c.execute("INSERT INTO wizyty (auto_id, data, przebieg, wykonawca, koszt_calkowity, koszt_robocizny, "
                      "rodzaj) VALUES (?,?,?,?,?,?,?)", (auto_id, kiedy, przebieg - dni * 40, warsztat, koszt,
                                                         robocizna, rodzaj))
            c.execute("INSERT INTO historia (zadanie_id, wizyta_id, data, przebieg, kategoria, cena, wykonawca, "
                      "rodzaj) VALUES (?,?,?,?,?,?,?,?)", (zadania[zadanie], c.lastrowid, kiedy, przebieg - dni * 40,
                                                           "Serwis", koszt, warsztat, rodzaj))
        # Tagi (U-16): wpis z dwoma tagami liczy się przy każdym z nich.
        for dni, kategoria, kwota, tagi in ((690, "Ubezpieczenie", 1650.0, None), (330, "Ubezpieczenie", 1770.0, "Rachunki"),
                                            (40, "Myjnia i kosmetyka", 60.0, "Wyjazd"),
                                            (200, db.KATEGORIA_INNE_DROGOWE, 72.0, "Wyjazd,Praca"),
                                            (90, "Parking i garaż", 18.0, "Praca"), (400, "Opłaty urzędowe", 149.0, None)):
            c.execute("INSERT INTO inne_koszty (auto_id, data, kategoria, nazwa, kwota, tagi) VALUES (?,?,?,?,?,?)",
                      (auto_id, _d(dzis - timedelta(days=dni)), kategoria, kategoria, kwota, tagi))
        db.przelicz_daty_iso(conn)
    db.zanotuj_zmiane_danych()
    return auto_id


def _telefon():
    strona = pomoce.zbuduj_strone()
    strona.page.width = audyty.SZEROKOSC_TELEFONU
    return strona


def ekran(auto_id, klucz, strona=None):
    strona = strona or _telefon()
    widok = pomoce.klasy_widokow()["WykresView"](strona.page, pomoce.stan_aplikacji(auto_id, "Octavia"), klucz)
    assert not pomoce.bledy_kontrolek(widok), pomoce.bledy_kontrolek(widok)
    return widok


def spis(auto_id):
    stan = pomoce.stan_aplikacji(auto_id, "Octavia")
    stan.zakladka, stan.stat_podzakladka = 3, 1
    return pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], _telefon(), stan)


def kontrolki(korzen, typ):
    znalezione, kolejka = [], [korzen]
    while kolejka:
        k = kolejka.pop()
        if isinstance(k, typ):
            znalezione.append(k)
        for pole in ("controls", "content", "data_series", "points", "appbar", "title"):
            w = getattr(k, pole, None)
            kolejka.extend(w if isinstance(w, list) else [w] if isinstance(w, ft.BaseControl) else [])
    return znalezione


def klikalny(korzen, napis):
    """Najmniejszy klikalny kontener z tym napisem (kafel, wiersz spisu, chip)."""
    trafione = [k for k in kontrolki(korzen, ft.Container) if k.on_click and napis in pomoce.napisy(k)]
    assert trafione, f"nic klikalnego z napisem {napis!r}"
    return min(trafione, key=pomoce.policz_kontrolki)


def audyt_drzewa(korzen):
    znaleziska = (audyty.znajdz_uciete_napisy(korzen) + audyty.znajdz_expand_bez_ograniczenia(korzen)
                  + audyty.znajdz_expand_w_kontenerze(korzen) + audyty.znajdz_plaskie_powierzchnie(korzen))
    assert not audyty.znajdz_pogrubienia_na_drugim_planie(korzen)
    assert znaleziska == [], "\n".join(str(z) for z in znaleziska)


# ============================================================================
#  SPIS
# ============================================================================

def test_spis_ma_trzy_grupy_i_odpowiedz_na_kazde_pytanie(baza):
    widok = spis(bogate_auto())
    napisy = pomoce.napisy(widok)
    for grupa in ("Ile kosztuje auto", "Na co idą pieniądze", "Tankowanie"):
        assert grupa in napisy
    for wpis in utils.WYKRESY_ANALIZY:
        assert utils.tekst_wykresu(wpis, "pytanie") in napisy
    assert "Brak danych" not in napisy, "bogate auto ma odpowiedź na każde pytanie"
    assert any(t.endswith("% to awarie") for t in napisy)
    najtansza = db.pobierz_trend_cen_paliwa(widok.state.auto_id, utils.granica_zakresu(12))["stacje"][0]["nazwa"]
    assert najtansza in napisy, "odpowiedź na „Gdzie tankować taniej?” to nazwa stacji"
    # Stare nagłówki dziesięciu wykresów zniknęły ze spisu — są na ekranach wykresów.
    assert "Koszt skumulowany" not in napisy and "Trend spalania w czasie" not in napisy
    audyt_drzewa(widok)


def test_spis_bez_danych_mowi_czego_brakuje(baza):
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_bez_danych")
    stan.zakladka, stan.stat_podzakladka = 3, 1
    napisy = pomoce.napisy(pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], _telefon(), stan))
    assert napisy.count("Brak danych") == len(utils.WYKRESY_ANALIZY)
    assert "Pojawi się po pierwszych wpisach kosztowych." in napisy


def test_elektryk_ma_ladowanie_zamiast_tankowania(baza):
    napisy = pomoce.napisy(spis(bogate_auto("Prądowy", "Elektryczny")))
    assert "Ładowanie" in napisy and "Tankowanie" not in napisy
    assert "Czy zużywa więcej prądu?" in napisy and "Gdzie ładować taniej?" in napisy


def test_wiersz_spisu_otwiera_swoj_wykres(baza):
    widok = spis(bogate_auto())
    trasy = []
    widok._page.on_route_change = lambda e: trasy.append(widok._page.route)
    klikalny(widok, "Czy auto zaczyna się sypać?").on_click(None)
    assert trasy == ["/wykres/awarie"]


# ============================================================================
#  EKRAN WYKRESU
# ============================================================================

@pytest.mark.parametrize("klucz", utils.KLUCZE_WYKRESOW)
def test_ekran_kazdego_wykresu(baza, klucz):
    widok = ekran(bogate_auto(), klucz)
    wpis = utils.wykres_analizy(klucz)
    napisy = pomoce.napisy(widok)
    assert widok.route == f"/wykres/{klucz}"
    assert utils.tekst_wykresu(wpis, "pytanie") in napisy and utils.tekst_wykresu(wpis, "opis") in napisy
    assert utils.tekst_wykresu(wpis, "nazwa") in pomoce.napisy(widok.appbar)
    nastepny = utils.nastepny_wykres(klucz)
    if nastepny:
        assert "Następny wykres" in napisy
        assert utils.tekst_wykresu(utils.wykres_analizy(nastepny), "pytanie") in napisy
    else:
        assert "Wróć do wszystkich wykresów" in napisy
    assert not any(t.startswith(("Za mało danych", "Brak ")) for t in napisy), "bogate auto ma wykres"
    audyt_drzewa(widok)


@pytest.mark.parametrize("klucz", utils.KLUCZE_WYKRESOW)
def test_ekran_wykresu_bez_danych_i_bez_pojazdu(baza, klucz):
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_bez_danych")
    widok = pomoce.klasy_widokow()["WykresView"](_telefon().page, stan, klucz)
    assert pomoce.policz_kontrolki(widok) > 5
    audyt_drzewa(widok)
    pusty = pomoce.klasy_widokow()["WykresView"](_telefon().page, pomoce.stan_aplikacji(), klucz)
    assert "Brak wybranego pojazdu" in pomoce.napisy(pusty)


def test_kolejnosc_i_nieznany_klucz():
    assert utils.nastepny_wykres("skumulowany") == "koszt1000"
    assert utils.nastepny_wykres(utils.KLUCZE_WYKRESOW[-1]) is None
    assert utils.wykres_analizy("nie-ma-takiego")["klucz"] == utils.KLUCZE_WYKRESOW[0]
    assert len(set(utils.KLUCZE_WYKRESOW)) == len(utils.KLUCZE_WYKRESOW) == 11


def test_nastepny_wykres_prowadzi_dalej(baza):
    widok = ekran(bogate_auto(), "struktura")
    trasy = []
    widok._page.on_route_change = lambda e: trasy.append(widok._page.route)
    klikalny(widok, "Następny wykres").on_click(None)
    assert trasy == ["/wykres/kategorie"]


def test_zakres_zmienia_sie_na_ekranie_wykresu_w_miejscu(baza):
    auto_id = bogate_auto()
    strona = _telefon()
    widok = ekran(auto_id, "struktura", strona)
    strona.page.views.append(widok)
    widok.update = lambda *a, **k: None
    przed = pomoce.napisy(widok)
    klikalny(widok, "Wszystko").on_click(None)
    assert db.pobierz_zakres_wykresu(auto_id, "struktura") == 0
    assert "Razem — cała historia" in pomoce.napisy(widok) and "Razem — ostatni rok" in przed


def test_trasa_routera_buduje_ekran_wykresu(baza, monkeypatch):
    monkeypatch.setattr(ft, "run", lambda *a, **k: None)
    import main
    zrodlo = open(main.__file__, encoding="utf-8").read()
    assert 'segmenty[0] == "wykres"' in zrodlo and "WykresView(" in zrodlo


# ============================================================================
#  OSIE I DYMKI
# ============================================================================

def test_skala_osi_ma_okragle_kroki():
    assert utils.skala_osi(62000, 75500, ile=3) == (60000, 80000, 5000, 1)
    assert utils.skala_osi(6.07, 6.75, ile=3) == (600, 675, 25, 100)
    assert utils.skala_osi(0, 972, ile=4, od_zera=True) == (0, 1000, 250, 1)
    assert utils.skala_osi(5, 5)[1] > utils.skala_osi(5, 5)[0], "płaska seria też ma oś"


def test_podpisy_osi_x_nie_nachodza_na_ostatni():
    assert utils.indeksy_podpisow(12) == [0, 3, 6, 9, 11]
    assert utils.indeksy_podpisow(11) == [0, 3, 6, 10]
    assert utils.indeksy_podpisow(1) == [0]


@pytest.mark.parametrize("klucz", ["skumulowany", "koszt1000", "rok_do_roku", "spalanie", "ceny"])
def test_dymki_i_podpisy_osi_na_kreskach(baza, klucz):
    wykresy = kontrolki(ekran(bogate_auto(), klucz), fc.LineChart)
    assert wykresy
    for wykres in wykresy:
        for seria in wykres.data_series:
            for punkt in seria.points:
                assert punkt.tooltip or not punkt.show_tooltip, "surowa liczba w dymku"
        os_y = wykres.left_axis
        assert os_y.label_spacing and os_y.labels
        assert all(round(e.value / os_y.label_spacing, 6).is_integer() for e in os_y.labels)
        assert wykres.min_y == os_y.labels[0].value and wykres.max_y == os_y.labels[-1].value
        os_x = wykres.bottom_axis
        assert os_x.label_spacing and all(round(e.value / os_x.label_spacing, 6).is_integer() for e in os_x.labels)


def test_spalanie_w_jednostce_z_ustawien(baza):
    auto_id = bogate_auto()
    db.zapisz_ustawienie("jednostka_spalania", "km/l")
    napisy = pomoce.napisy(ekran(auto_id, "spalanie"))
    assert any(t.endswith(" km/l") for t in napisy)


# ============================================================================
#  KOKPIT I LICZBY
# ============================================================================

@pytest.mark.parametrize("widget, napis, klucz", [
    ("skumulowany", "Koszt skumulowany", "skumulowany"),
    ("koszt_1000km", "Koszt / 1000 km", "koszt1000"),
    ("koszt_km", "Koszt / km", "koszt1000"),
    ("awarie", "Awarie w serwisie", "awarie"),
    ("wykres", "Wydatki 6 mies.", "wydatki"),
])
def test_kafelek_kokpitu_otwiera_swoj_wykres(baza, widget, napis, klucz):
    auto_id = bogate_auto()
    db.zapisz_widgety_kokpitu([widget], auto_id)
    stan = pomoce.stan_aplikacji(auto_id, "Octavia")
    stan.zakladka = 0
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(), stan)
    trasy = []
    widok._page.on_route_change = lambda e: trasy.append(widok._page.route)
    klikalny(widok.kokpit_kontener, napis).on_click(None)
    assert trasy == [f"/wykres/{klucz}"]


def test_liczby_na_powierzchniach_jak_wykresy(baza):
    stan = pomoce.stan_aplikacji(bogate_auto(), "Octavia")
    stan.zakladka, stan.stat_podzakladka = 3, 0
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], _telefon(), stan)
    assert not kontrolki(widok, ft.Card), "Liczby bez starych kart z ramką"
    assert "Całkowity koszt" in pomoce.napisy(widok)
    audyt_drzewa(widok)
