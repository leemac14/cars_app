"""Przegląd spójności 2026-11-03: te same liczby tą samą miarą na każdym ekranie (średnie spalanie,
koszt km paliwa, przejechany dystans, okres wpisu cyklicznego) i napisy, które się nie rozjeżdżają."""

import pytest

import db
from date import parsuj_date
import pomoce
import utils

ROK = 2025


def _auto_z_odcinkami(pojemnosc_baku=None):
    """Pełne baki: 1000 km (drogi, przed odcinkami) → 1100 km (8 l) → 1700 km (30 l), potem dolewka.
    Zwykła średnia odcinków to 6,5 l/100km, litry przez km — 38/700."""
    a = pomoce.wstaw("samochody", nazwa="Odcinki", typ_paliwa="Benzyna", status=db.STATUS_POJAZDU_AKTYWNY,
                     rola_wspoldzielenia=db.ROLA_WLASCICIEL, pojemnosc_baku=pojemnosc_baku)
    for data, prz, litry, kwota, pelny in (("01.03.2025", 1000, 40, 999, 1), ("05.03.2025", 1100, 8, 48, 1),
                                           ("20.03.2025", 1700, 30, 180, 1), ("25.03.2025", 1800, 10, 60, 0)):
        pomoce.wstaw("tankowania", auto_id=a, data=data, przebieg=prz, litry=litry, kwota=kwota, do_pelna=pelny,
                      rodzaj_energii=db.ENERGIA_PALIWO)
    db.zanotuj_zmiane_danych()
    return a


def test_srednie_spalanie_to_litry_przez_kilometry_wszedzie(baza):
    a = _auto_z_odcinkami(pojemnosc_baku=50)
    oczekiwane = 38 / 700 * 100

    assert db.srednie_spalanie(db.pobierz_odcinki_spalania(a)) == pytest.approx(oczekiwane)
    assert [w for _, w in db.pobierz_serie_spalania(a)] == pytest.approx([8.0, 5.0])
    assert db.metryka_kokpitu(a, "spalanie")["srednia"] == pytest.approx(oczekiwane)
    assert db.podsumowanie_roku(a, ROK)["srednie_zuzycie"] == pytest.approx(oczekiwane)
    assert db.pobierz_statystyki_energii(a)[0]["zuzycie"] == pytest.approx(oczekiwane)
    assert db.pobierz_zasieg_na_baku(a)["spalanie"] == pytest.approx(oczekiwane)


def test_trend_spalania_wazy_odcinki_kilometrami(baza):
    a = pomoce.wstaw("samochody", nazwa="Trend", typ_paliwa="Benzyna", status=db.STATUS_POJAZDU_AKTYWNY,
                     rola_wspoldzielenia=db.ROLA_WLASCICIEL)
    przebieg = 10000
    pomoce.wstaw("tankowania", auto_id=a, data="01.01.2025", przebieg=przebieg, litry=40, kwota=240, do_pelna=1)
    # Wcześniej: dwa odcinki po 500 km i 6 l/100km. Ostatnio: krótki 50 km po 12 i dwa długie po 6.
    for i, (km, litry) in enumerate(((500, 30), (500, 30), (50, 6), (600, 36), (600, 36))):
        przebieg += km
        pomoce.wstaw("tankowania", auto_id=a, data=f"{10 + i * 3:02d}.01.2025", przebieg=przebieg, litry=litry,
                      kwota=litry * 6, do_pelna=1)
    db.zanotuj_zmiane_danych()

    trend = db.analizuj_trend_spalania(a)

    assert trend["srednia_ostatnia"] == pytest.approx(78 / 1250 * 100), "nie (12 + 6 + 6) / 3 = 8"
    assert trend["srednia_wczesniej"] == pytest.approx(6.0)


def test_koszt_km_paliwa_zgadza_sie_ze_spalaniem_i_cena(baza):
    a = _auto_z_odcinkami()
    stat = db.pobierz_statystyki_energii(a)[0]

    assert stat["koszt_km"] == pytest.approx((48 + 180) / 700)
    assert stat["koszt_km"] == pytest.approx(stat["zuzycie"] / 100 * (48 + 180) / 38)


def test_dystans_z_historii_licznika_w_analizie_porownaniu_i_raporcie(baza):
    a = _auto_z_odcinkami()
    pomoce.wstaw("odczyty_przebiegu", auto_id=a, data="20.02.2025", przebieg=900, zrodlo=db.ZRODLO_ODCZYTU_DOMYSLNE)
    pomoce.wstaw("wizyty", auto_id=a, data="30.03.2025", przebieg=2000, koszt_calkowity=300)
    db.zanotuj_zmiane_danych()
    koszt_razem = 999 + 48 + 180 + 60 + 300

    assert db.przejechane_km(a) == 1100
    assert db.pobierz_dane_do_porownania(a)["koszt_km"] == pytest.approx(koszt_razem / 1100)
    assert db.oblicz_podsumowanie_okresu(a)["dystans"] == 1100
    assert db.podsumowanie_roku(a, ROK)["km"] == 1100
    assert db.przejechane_km(a, od=parsuj_date("01.03.2025"), do=parsuj_date("21.03.2025")) == 800

    stan = pomoce.stan_aplikacji(a, "Odcinki")
    stan.zakladka, stan.stat_podzakladka = 3, 0
    strona = pomoce.zbuduj_strone()
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], strona, stan)
    assert utils.formatuj_dystans(1100, 0, "km") in pomoce.napisy(widok)


@pytest.mark.parametrize("okres, oczekiwany", [
    (30, "co miesiąc"), (90, "co kwartał"), (180, "co pół roku"), (365, "co rok"), (1, "codziennie"),
    (2, "co 2 dni"), (45, "co 45 dni"),
])
def test_okres_wpisu_cyklicznego_slowami(okres, oczekiwany):
    assert db.opis_okresu_dni(okres) == oczekiwany
    assert utils.co_ile_osi(okres) == oczekiwany


def test_termin_przebiegowy_rowno_z_licznikiem_nie_jest_po_terminie_o_zero(baza):
    stan = db.stan_terminu_przebiegowego(104000, 101000, 104000)
    _lewa, prawa, _kolor = utils.opis_terminu_przebiegowego({"termin_przebieg": 104000, "stan_przebiegu": stan})

    assert prawa == "termin mija teraz"


def test_edycja_kosztu_pokazuje_kwote_jak_inne_formularze(baza):
    ids = pomoce.utworz_pojazd("Kwoty")
    with db.polacz_baze() as conn:
        conn.execute("UPDATE inne_koszty SET kwota=120.0 WHERE id=?", (ids["inny_koszt"],))
    stan = pomoce.stan_aplikacji(ids["auto_id"], "Kwoty")
    strona = pomoce.zbuduj_strone()
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["FormularzInneView"], strona, stan, ids)

    teksty = pomoce.napisy(widok)
    assert "120" in teksty and "120.0" not in teksty


def test_napisy_ustawien_i_dolewek_bez_starych_odeslan(baza):
    stan, ids = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    strona = pomoce.zbuduj_strone()
    ustawienia = " ".join(pomoce.napisy(pomoce.zbuduj_widok(pomoce.klasy_widokow()["UstawieniaView"], strona, stan)))
    dolewki = " ".join(pomoce.napisy(pomoce.zbuduj_widok(pomoce.klasy_widokow()["DolewkiView"], strona, stan)))

    assert "⋮" not in ustawienia and "Garaż i osoby › Kosz" in ustawienia
    assert "podzielone przez kilometry od wymiany" in dolewki
