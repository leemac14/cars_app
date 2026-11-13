"""Licznik wpisany przy okazji jako źródło przebiegu, prognozy liczone od dnia odczytu, terminy
wpisów cyklicznych od terminu i kalendarzowo, drobne napisy (dziennik zmian 2026-11-13)."""

from datetime import date, timedelta

import pytest

import db
from date import parsuj_date
from pomoce import dzien, wstaw


@pytest.fixture
def auto(baza):
    return wstaw("samochody", nazwa="Auto")


def _komplet(auto_id, sezon="Zimowe"):
    return wstaw("zestawy_opon", auto_id=auto_id, sezon=sezon, marka_model="Nokian", zamontowane=1)


# ---------------------------------------------------------------- licznik wpisany przy okazji


def test_zmiana_opon_bez_podzespolu_aktualizuje_przebieg(auto):
    wstaw("tankowania", auto_id=auto, data=dzien(30), przebieg=100000, litry=40, kwota=250)
    komplet = _komplet(auto)
    wstaw("montaze_opon", auto_id=auto, zestaw_id=komplet, data=dzien(3), przebieg=101200)
    assert db.pobierz_aktualny_przebieg(auto) == 101200
    assert db.pobierz_historie_przebiegu(auto)[-1] == (dzien(3), 101200)
    wpis = db.pobierz_pelna_historie_przebiegu(auto)[-1]
    assert (wpis["zrodlo"], wpis["etykieta_zrodla"], wpis["trasa"]) == ("opony", "Zmiana opon",
                                                                        f"/magazyn/opony/{komplet}")
    assert wpis["dystans"] == 1200 and wpis["notatka"] is None and not wpis["edytowalny"]


@pytest.mark.parametrize("zrodlo", ["bieznik", "karoseria", "do_zrobienia", "do_zrobienia_koszt", "zdjecie_opon"])
def test_kazdy_licznik_przy_okazji_trafia_do_historii(auto, zrodlo):
    wstaw("tankowania", auto_id=auto, data=dzien(30), przebieg=100000, litry=40, kwota=250)
    if zrodlo == "bieznik":
        wstaw("pomiary_bieznika", auto_id=auto, zestaw_id=_komplet(auto), data=dzien(2), przebieg=100900, lp=6.0)
        oczekiwane = "bieznik"
    elif zrodlo == "karoseria":
        wstaw("zdjecia_karoserii", auto_id=auto, data=dzien(2), strefa="Przód", zalacznik="x.jpg", przebieg=100900)
        oczekiwane = "karoseria"
    elif zrodlo == "zdjecie_opon":
        wstaw("montaze_opon", auto_id=auto, zestaw_id=_komplet(auto), data=dzien(200), data_zdjecia=dzien(2),
              przebieg_zdjecia=100900)
        oczekiwane = "opony"
    else:
        koszt = wstaw("inne_koszty", auto_id=auto, data=dzien(2), kategoria="Inne", nazwa="Mycie",
                      kwota=50) if zrodlo == "do_zrobienia_koszt" else None
        # Dzień kosztu wygrywa z dniem zapisanym w pozycji (koszt poprawia się w Kosztach).
        wstaw("do_zrobienia", auto_id=auto, tytul="Mycie", wykonane=1, przebieg_wykonania=100900, koszt_id=koszt,
              data_wykonania=dzien(9) if koszt else dzien(2))
        oczekiwane = "do_zrobienia"
    assert db.pobierz_aktualny_przebieg(auto) == 100900
    ostatni = db.pobierz_pelna_historie_przebiegu(auto)[-1]
    assert (ostatni["zrodlo"], ostatni["data"], ostatni["przebieg"]) == (oczekiwane, dzien(2), 100900)
    assert db.swiezosc_licznika(auto)["dni"] == 2


def test_kopia_ostatniego_stanu_nie_jest_odczytem(auto):
    """Obchód i pole wypełnione ostatnim stanem: ten sam licznik później nie odświeża przebiegu."""
    wstaw("tankowania", auto_id=auto, data=dzien(40), przebieg=100000, litry=40, kwota=250)
    wstaw("zdjecia_karoserii", auto_id=auto, data=dzien(1), strefa="Tył", zalacznik="y.jpg", przebieg=100000)
    wstaw("do_zrobienia", auto_id=auto, tytul="Wosk", wykonane=1, przebieg_wykonania=100000, data_wykonania=dzien(1))
    assert db.pobierz_historie_przebiegu(auto) == [(dzien(40), 100000)]
    assert db.swiezosc_licznika(auto)["dni"] == 40


def test_licznik_przy_okazji_nie_robi_cofki_we_wpisach(auto):
    """Niższy od wcześniejszych i wyższy od późniejszego wpisu głównego nie wchodzi do historii."""
    wstaw("tankowania", auto_id=auto, data=dzien(30), przebieg=100000, litry=40, kwota=250)
    wstaw("tankowania", auto_id=auto, data=dzien(10), przebieg=101000, litry=40, kwota=250)
    komplet = _komplet(auto)
    wstaw("pomiary_bieznika", auto_id=auto, zestaw_id=komplet, data=dzien(20), przebieg=99000, lp=6.0)
    wstaw("pomiary_bieznika", auto_id=auto, zestaw_id=komplet, data=dzien(19), przebieg=101500, lp=6.0)
    dobry = wstaw("pomiary_bieznika", auto_id=auto, zestaw_id=komplet, data=dzien(18), przebieg=100600, lp=6.0)
    historia = db.pobierz_pelna_historie_przebiegu(auto)
    assert [(w["zrodlo"], w["przebieg"]) for w in historia] == [
        ("tankowanie", 100000), ("bieznik", 100600), ("tankowanie", 101000)]
    assert historia[1]["trasa"] == f"/magazyn/opony/pomiar/edytuj/{dobry}"
    assert not any(w["anomalia"] for w in historia)


def test_wykonanie_z_wpisem_serwisowym_liczy_sie_raz(auto):
    zadanie = wstaw("zadania", auto_id=auto, nazwa="Olej")
    wpis = wstaw("historia", zadanie_id=zadanie, data=dzien(5), przebieg=100500, cena=300)
    wstaw("do_zrobienia", auto_id=auto, tytul="Olej", wykonane=1, przebieg_wykonania=100500, data_wykonania=dzien(5),
          historia_id=wpis)
    assert [w["zrodlo"] for w in db.pobierz_pelna_historie_przebiegu(auto)] == ["serwis"]


def test_ostrzezenie_o_przebiegu_widzi_licznik_przy_okazji_i_pomija_poprawiany(auto):
    wstaw("tankowania", auto_id=auto, data=dzien(30), przebieg=100000, litry=40, kwota=250)
    pomiar = wstaw("pomiary_bieznika", auto_id=auto, zestaw_id=_komplet(auto), data=dzien(5), przebieg=100800, lp=6.0)
    assert "niższy" in db.sprawdz_czy_przebieg_podejrzany(auto, 100300, nowa_data_str=dzien(1))
    assert db.sprawdz_czy_przebieg_podejrzany(auto, 100300, wyklucz_id=pomiar, tabela="pomiary_bieznika",
                                              nowa_data_str=dzien(5)) is None


# ---------------------------------------------------------------- prognozy od dnia odczytu


def _jazda(auto_id, dni_od_odczytu=38):
    """40 km dziennie przez 100 dni; ostatni stan licznika (104 000) sprzed `dni_od_odczytu` dni."""
    wstaw("odczyty_przebiegu", auto_id=auto_id, data=dzien(dni_od_odczytu + 100), przebieg=100000)
    wstaw("odczyty_przebiegu", auto_id=auto_id, data=dzien(dni_od_odczytu), przebieg=104000)
    return db.oblicz_sredni_dzienny_przebieg(auto_id)


def _za(dni):
    return date.today() + timedelta(days=dni)


def test_tempo_pamieta_dzien_ostatniego_stanu_licznika(auto):
    tempo = _jazda(auto)
    assert tempo == 40.0 and tempo.od == _za(-38)
    # 6000 km to 150 dni od dnia odczytu, czyli 112 od dziś — nie 150.
    assert db.prognoza_z_tempa(6000, tempo) == (112, _za(112))
    assert db.prognoza_z_tempa(6000, 40.0) == (150, _za(150))  # zwykła liczba: od dziś
    assert db.prognoza_z_tempa(400, tempo) == (0, _za(0))      # dzień już minął — dziś
    assert db.prognoza_z_tempa(-1, tempo) == (None, None) and db.prognoza_z_tempa(100, None) == (None, None)


def test_okragly_przebieg_i_limit_gwarancji_licza_od_dnia_odczytu(auto):
    _jazda(auto)
    with db.polacz_baze() as conn:
        conn.execute("UPDATE samochody SET gwarancja_przebieg=104400 WHERE id=?", (auto,))
    pozycje = {p["rodzaj"]: p for p in db.odliczania_pojazdu(auto)}
    assert (pozycje["przebieg"]["cel_km"], pozycje["przebieg"]["dni"], pozycje["przebieg"]["data"]) == (
        110000, 112, _za(112))
    assert (pozycje["gwarancja_km"]["zostalo_km"], pozycje["gwarancja_km"]["dni"]) == (400, 0)


def test_interwal_gwarancja_naprawy_i_dzwonek_licza_od_dnia_odczytu(auto):
    tempo = _jazda(auto)
    zadanie = {"interwal_km": 10000, "przebieg": 100000, "interwal_miesiace": None, "data": dzien(138)}
    km = db.oblicz_stan_interwalu(zadanie, 104000, tempo)["km"]
    assert (km["zostalo"], km["dni"], km["data"]) == (6000, 112, _za(112))
    gwarancja = db.stan_gwarancji(None, 106000, aktualny_przebieg=104000, sredni_dzienny=tempo)
    assert (gwarancja["zostalo_km"], gwarancja["dni_km"], gwarancja["data_km"]) == (2000, 12, _za(12))

    z = wstaw("zadania", auto_id=auto, nazwa="Olej", interwal_km=4500, przebieg=100000, data=dzien(138))
    powiadomienie = next(p for p in db.pobierz_powiadomienia(auto) if p["klucz"] == f"podzespol:{z}")
    assert "dziś" in powiadomienie["opis"]  # 500 km to 12 dni od odczytu sprzed 38 dni


def test_prognoza_bieznika_liczy_od_dnia_odczytu():
    tempo = db.TempoJazdy(40.0, _za(-38))
    dane = dict(sezon="Całoroczne", zamontowany=True, sezonowy=False, koniec_montazu=None, dzis=date.today())
    assert db.opony._data_prognozy(6000, tempo, **dane) == _za(112)
    assert db.opony._data_prognozy(6000, 40.0, **dane) == _za(150)
    assert db.opony._data_prognozy(400, tempo, **dane) == _za(0)


def test_bak_pusty_liczy_od_dnia_ostatniego_stanu_licznika(auto):
    with db.polacz_baze() as conn:
        conn.execute("UPDATE samochody SET pojemnosc_baku=50, typ_paliwa='Benzyna' WHERE id=?", (auto,))
    for dni, przebieg in ((70, 100000), (40, 101200), (10, 102400)):   # 40 km dziennie, 5 l/100 km
        wstaw("tankowania", auto_id=auto, data=dzien(dni), przebieg=przebieg, litry=60, kwota=400, do_pelna=1)
    bak = db.pobierz_zasieg_na_baku(auto)
    assert round(bak["zasieg_pozostaly"]) == 1000
    assert bak["dni_do_pustego"] == 15 and bak["data_pustego"] == _za(15).strftime("%d.%m.%Y")  # 25 dni − 10


# ---------------------------------------------------------------- wpisy cykliczne: od terminu, kalendarzowo


def _cykliczny(auto_id, okres=30, za_dni=0, **pola):
    db.dodaj_wydatek_cykliczny(auto_id, "Parking", 200.0, okres, dzien(-za_dni), **pola)
    return db.pobierz_wydatki_cykliczne(auto_id)[-1][0]


def _termin(wydatek_id):
    with db.polacz_baze() as conn:
        return conn.execute("SELECT nastepna_data FROM wydatki_cykliczne WHERE id=?", (wydatek_id,)).fetchone()[0]


@pytest.mark.parametrize("okres, termin, oczekiwany", [
    (30, date(2027, 1, 10), date(2027, 2, 10)),     # 10. zostaje 10., nie cofa się o 5 dni rocznie
    (90, date(2027, 1, 10), date(2027, 4, 10)),
    (180, date(2027, 1, 10), date(2027, 7, 10)),
    (182, date(2026, 10, 15), date(2027, 4, 15)),   # przypomnienie o oponach
    (365, date(2028, 2, 29), date(2029, 2, 28)),
    (30, date(2027, 1, 31), date(2027, 2, 28)),     # dnia nie ma — koniec miesiąca
    (14, date(2027, 1, 10), date(2027, 1, 24)),     # okres spoza listy dalej w dniach
])
def test_okres_liczy_sie_kalendarzowo(okres, termin, oczekiwany):
    assert db.termin_po_okresach(termin, okres) == oczekiwany
    assert db.termin_po_okresach(date(2027, 3, 10), 30, -2) == date(2027, 1, 10)


@pytest.mark.parametrize("za_dni", [4, -2])
def test_zaplacone_przed_terminem_i_po_nim_nie_przestawia_cyklu(auto, za_dni):
    wydatek = _cykliczny(auto, za_dni=za_dni)
    wynik = db.oznacz_zaplacony_wydatek_cykliczny(wydatek, auto)
    nowy = db.dodaj_miesiace(_za(za_dni), 1)
    assert _termin(wydatek) == wynik["nastepna_data"] == nowy.strftime("%d.%m.%Y")
    with db.polacz_baze() as conn:   # koszt z dniem zapłaty, nie terminu
        assert conn.execute("SELECT data, kwota FROM inne_koszty WHERE auto_id=?", (auto,)).fetchall() == [
            (dzien(0), 200.0)]


def test_spozniony_o_kilka_okresow_idzie_okres_po_okresie(auto):
    wydatek = _cykliczny(auto, za_dni=-95)
    terminy = []
    for _ in range(4):
        db.oznacz_zaplacony_wydatek_cykliczny(wydatek, auto)
        terminy.append(parsuj_date(_termin(wydatek)))
    oczekiwane, termin = [], _za(-95)
    for _ in range(4):
        termin = db.termin_po_okresach(termin, 30)
        oczekiwane.append(termin)
    assert terminy == oczekiwane and terminy[1] < date.today() < terminy[3]
    with db.polacz_baze() as conn:   # każdy okres to osobny koszt — nic nie przepada
        assert conn.execute("SELECT COUNT(*) FROM inne_koszty WHERE auto_id=?", (auto,)).fetchone()[0] == 4


@pytest.mark.parametrize("zmiana, oczekiwany", [
    (date(2026, 11, 7), date(2027, 4, 15)),    # spóźniona o trzy tygodnie
    (date(2026, 10, 1), date(2027, 4, 15)),    # dwa tygodnie przed terminem
    (date(2026, 3, 20), date(2026, 10, 15)),   # zmiana z poprzedniego sezonu — termin stoi
    (date(2025, 4, 5), date(2026, 10, 15)),    # dopisana dawna zmiana nie cofa przypomnienia
])
def test_przypomnienie_o_oponach_trzyma_termin_cyklu(zmiana, oczekiwany):
    assert db.termin_zmiany_opon(date(2026, 10, 15), db.OKRES_ZMIANY_OPON_DNI, zmiana) == oczekiwany


def test_wykonano_i_reczna_zmiana_opon_przesuwaja_przypomnienie_po_cyklu(auto):
    db.dodaj_przypomnienie_o_oponach(auto, nastepna_data=dzien(-10))   # termin za 10 dni
    (wpis,) = db.pobierz_przypomnienia_o_oponach(auto)
    db.oznacz_zaplacony_wydatek_cykliczny(wpis[0], auto)
    po_wykonaniu = db.dodaj_miesiace(_za(10), 6)
    assert _termin(wpis[0]) == po_wykonaniu.strftime("%d.%m.%Y")
    # Druga zmiana tego samego dnia (ręczna z Magazynu) to ta sama pora roku — termin stoi.
    assert db.przesun_przypomnienie_o_oponach(auto) and _termin(wpis[0]) == po_wykonaniu.strftime("%d.%m.%Y")


def test_seria_w_kalendarzu_powtarza_sie_kalendarzowo():
    regula = db.kalendarz._regula_serii
    assert regula(date(2027, 1, 10), 90, 4) == "FREQ=MONTHLY;INTERVAL=3;COUNT=4"
    assert regula(date(2027, 1, 31), 30, 12) == "FREQ=MONTHLY;INTERVAL=1;COUNT=12;BYMONTHDAY=28,29,30,31;BYSETPOS=-1"
    assert regula(date(2027, 1, 10), 365, 2) == "FREQ=MONTHLY;INTERVAL=12;COUNT=2"
    assert regula(date(2027, 1, 10), 14, 5) == "FREQ=DAILY;INTERVAL=14;COUNT=5"


@pytest.mark.parametrize("okres, teraz, zmienione", [
    (30, date(2027, 6, 10), 0),     # ten sam dzień pięć miesięcy później — ta sama seria
    (30, date(2027, 2, 28), 0),     # 31. w lutym stoi na końcu miesiąca
    (30, date(2027, 6, 16), 1),     # przestawiona na inny dzień miesiąca
    (90, date(2027, 3, 10), 1),     # kwartalna poza swoim miesiącem
])
def test_podpowiedz_kalendarza_zna_serie_kalendarzowe(okres, teraz, zmienione):
    wyslana = date(2027, 1, 31 if teraz.day == 28 else 10)
    assert db.kalendarz._zmienione_grupy({"cykliczny:1": [wyslana.isoformat(), okres]},
                                         {"cykliczny:1": (teraz, okres)}, wyslana) == zmienione


# ---------------------------------------------------------------- drobne napisy


def test_pasek_ekranu_glownego_ma_nazwe_i_logo(baza):
    import flet as ft
    import pomoce
    import utils

    strona = pomoce.zbuduj_strone()
    pasek = utils.zbuduj_pasek_glowny(strona.page, pomoce.stan_aplikacji(), None, None, None)
    napisy = pomoce.napisy(pasek.title)
    assert db.NAZWA_APLIKACJI in napisy and not any("KAMILA" in n or "Menedżer" in n for n in napisy)
    obrazy = [k for k in pomoce.kontrolki(pasek.title) if isinstance(k, ft.Image)]
    assert [o.src for o in obrazy] == [utils.PLIK_LOGO]


def test_pierwsze_tankowanie_ma_kreske_zamiast_zera(baza):
    import pomoce

    auto_id = wstaw("samochody", nazwa="Auto", typ_paliwa="Benzyna")
    wstaw("tankowania", auto_id=auto_id, data=dzien(20), przebieg=100000, litry=40, kwota=250, do_pelna=1)
    wstaw("tankowania", auto_id=auto_id, data=dzien(5), przebieg=100600, litry=38, kwota=240, do_pelna=1)
    wstaw("tankowania", auto_id=auto_id, data=dzien(2), przebieg=0, dystans=310, litry=20, kwota=130)
    stan = pomoce.stan_aplikacji(auto_id, "Auto")
    stan.zakladka, stan.koszty_podzakladka = 2, 0
    strona = pomoce.zbuduj_strone()
    napisy = pomoce.napisy(pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], strona, stan))
    assert "—" in napisy and not any(n.strip() == "0 km" for n in napisy)
    assert "600 km" in napisy and "310 km" in napisy


def test_rok_w_pigulce_pisze_ile_bylo_rok_temu(baza):
    import pomoce
    import utils

    auto_id = wstaw("samochody", nazwa="Auto")
    rok = date.today().year
    wstaw("inne_koszty", auto_id=auto_id, data=f"01.01.{rok - 1}", kategoria="Inne", nazwa="Myjnia", kwota=1287)
    wstaw("inne_koszty", auto_id=auto_id, data=f"01.01.{rok}", kategoria="Inne", nazwa="Myjnia", kwota=617.76)
    strona = pomoce.zbuduj_strone()
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["RokWPigulceView"], strona, pomoce.stan_aplikacji(auto_id, "Auto"))
    assert f"Taniej o 52% (było 1 287,00 {utils.symbol_waluty()})" in pomoce.napisy(widok)


# ---------------------------------------------------------------- zamek: nowe miejsce z licznikiem

# Kolumny z licznikiem, które świadomie NIE są stanem licznika pojazdu (powód obok).
POZA_LICZNIKIEM_SWIADOMIE = {
    ("do_zrobienia", "termin_przebieg"): "cel, nie stan",
    ("do_zrobienia", "przebieg_startowy"): "kopia licznika z dnia planowania",
    ("ekrany_uzycie", "licznik"): "licznik użyć ekranu",
    ("historia", "gwarancja_przebieg"): "granica gwarancji",
    ("wizyty", "gwarancja_przebieg"): "granica gwarancji",
    ("samochody", "gwarancja_przebieg"): "granica gwarancji",
    ("samochody", "przebieg_zakupu"): "punkt sprzed lat zawyża przejechane_km pierwszego okresu",
    ("zestawy_opon", "przebieg_zakupu"): "dwuznaczne: licznik auta albo przebieg samych opon",
    ("szkice_wpisow", "przebieg"): "szkic nie jest jeszcze wpisem — licznik niesie wpis z niego",
    ("zadania", "przebieg"): "wyliczane z historii podzespołu",
}


def test_kazda_kolumna_z_licznikiem_jest_zrodlem_przebiegu_albo_wyjatkiem(baza):
    """Licznik wpisany w nowym miejscu ma aktualizować przebieg: nowa kolumna trafia do
    `_ZRODLA_LICZNIKA` (db/przebieg.py) albo — z powodem — na listę wyżej."""
    import re

    with db.polacz_baze() as conn:
        tabele = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        w_bazie = {(t, k[1]) for t in tabele for k in conn.execute(f"PRAGMA table_info({t})")
                   if re.search("przebieg|licznik", k[1])}
    zrodla = {(tabela, re.search(r",\s*(?:\w+\.)?(\w+) FROM", sql).group(1))
              for _zrodlo, tabela, _etap, sql in db.przebieg._ZRODLA_LICZNIKA}
    nierozstrzygniete = sorted(w_bazie - zrodla - set(POZA_LICZNIKIEM_SWIADOMIE))
    assert nierozstrzygniete == [], f"kolumny z licznikiem poza historią przebiegu: {nierozstrzygniete}"
    assert sorted((zrodla | set(POZA_LICZNIKIEM_SWIADOMIE)) - w_bazie) == [], "lista zna kolumnę, której nie ma w bazie"
