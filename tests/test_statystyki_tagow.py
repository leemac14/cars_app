"""Statystyki tagów (U-16): ile poszło na każdy tag — pytanie w Analiza › Wykresy (dotknięcie
tagu otwiera jego wpisy), kafelek kokpitu z tagami miesiąca i kwota z bieżącego roku w edytorze
tagów. Wpis z kilkoma tagami liczy się przy każdym z nich."""

from datetime import date, timedelta

import flet as ft

import db
import pomoce
import utils


def _d(dzien):
    return dzien.strftime("%d.%m.%Y")


def _auto(nazwa):
    with db.polacz_baze() as conn:
        return conn.execute("INSERT INTO samochody (nazwa, typ_paliwa, status, rola_wspoldzielenia) VALUES (?,?,?,?)",
                            (nazwa, "Benzyna", db.STATUS_POJAZDU_AKTYWNY, db.ROLA_WLASCICIEL)).lastrowid


def auto_z_tagami():
    """Dziś: tankowanie 300 z dwoma tagami w innej pisowni niż słownik, koszt 100 „Wyjazd”,
    koszt 50 z tagiem spoza słownika, wizyta 500 bez tagu; ponad rok temu prom 1000 „Wyjazd”."""
    auto = _auto("Tagowane")
    dzis = _d(date.today())
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO tagi (auto_id, nazwa, kolor) VALUES (?,?,?)", (auto, "Wyjazd", "Zielony"))
        c.execute("INSERT INTO tagi (auto_id, nazwa, kolor) VALUES (?,?,?)", (auto, "Praca", "Niebieski"))
        c.execute("INSERT INTO tankowania (auto_id, data, przebieg, litry, kwota, do_pelna, tagi) VALUES (?,?,?,?,?,?,?)",
                  (auto, dzis, 1000, 40.0, 300.0, 1, "wyjazd,PRACA"))
        for nazwa, kwota, tagi, kiedy in (("Bramki", 100.0, "Wyjazd", dzis), ("Kawa", 50.0, "Kawa", dzis),
                                          ("Prom", 1000.0, "Wyjazd", _d(date.today() - timedelta(days=400)))):
            c.execute("INSERT INTO inne_koszty (auto_id, data, kategoria, nazwa, kwota, tagi) VALUES (?,?,?,?,?,?)",
                      (auto, kiedy, db.KATEGORIA_INNE_DOMYSLNA, nazwa, kwota, tagi))
        c.execute("INSERT INTO wizyty (auto_id, data, przebieg, wykonawca, koszt_calkowity) VALUES (?,?,?,?,?)",
                  (auto, dzis, 1000, "ASO", 500.0))
        db.przelicz_daty_iso(conn)
    db.zanotuj_zmiane_danych()
    return auto


def _tagi(wynik):
    return [(p["nazwa"], p["kwota"], p["liczba"]) for p in wynik["tagi"]]


def test_wpis_z_kilkoma_tagami_liczy_sie_przy_kazdym(baza):
    auto = auto_z_tagami()
    wynik = db.koszty_wg_tagow(auto, date.today() - timedelta(days=30))
    assert _tagi(wynik) == [("Wyjazd", 400.0, 2), ("Praca", 300.0, 1), ("Kawa", 50.0, 1)]
    assert wynik["bez_tagu"] == {"kwota": 500.0, "liczba": 1}
    assert (wynik["razem"], wynik["liczba"]) == (950.0, 4)
    assert {p["nazwa"]: p["kolor"] for p in wynik["tagi"]} == {"Wyjazd": "Zielony", "Praca": "Niebieski", "Kawa": None}
    assert _tagi(db.koszty_wg_tagow(auto))[0] == ("Wyjazd", 1400.0, 3)
    assert db.koszty_wg_tagow(None)["tagi"] == []


def test_tagi_miesiaca_dla_kafelka(baza):
    auto = auto_z_tagami()
    assert _tagi(db.tagi_miesiaca(auto))[0] == ("Wyjazd", 400.0, 2)
    assert db.tagi_miesiaca(_auto("Bez tagów")) is None
    stare = _auto("Stare tagi")
    with db.polacz_baze() as conn:
        conn.execute("INSERT INTO inne_koszty (auto_id, data, data_iso, kategoria, nazwa, kwota, tagi) "
                     "VALUES (?,?,?,?,?,?,?)", (stare, "01.01.2020", "2020-01-01", "Ogólne", "Prom", 10.0, "Wyjazd"))
    assert db.tagi_miesiaca(stare)["tagi"] == []
    assert set(db.sumy_tagow_roku(auto)) == {"wyjazd", "praca", "kawa"}


def test_kafelek_kokpitu_pokazuje_najdrozsze_tagi_miesiaca(baza):
    auto = auto_z_tagami()
    stan = pomoce.stan_aplikacji(auto, "Tagowane")
    stan.zakladka = 0
    db.zapisz_widgety_kokpitu(["tagi"], auto)
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(), stan)
    teksty = pomoce.napisy(widok.kokpit_kontener)
    waluta = utils.symbol_waluty()
    assert {"Tagi w tym miesiącu", "Wyjazd", f"400 {waluta}", "Praca", f"300 {waluta}", "Kawa"} <= set(teksty)
    assert widok._kokpit_puste == []

    goly = _auto("Bez tagów")
    db.zapisz_chowanie_pustych_kafelkow(True)
    db.zapisz_widgety_kokpitu(["tagi"], goly)
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(),
                                pomoce.stan_aplikacji(goly, "Bez tagów"))
    assert widok._kokpit_puste == ["tagi"]


def test_wykres_tagow_otwiera_wpisy_z_tagiem_z_tego_samego_okresu(baza):
    auto = auto_z_tagami()
    strona = pomoce.zbuduj_strone()
    trasy = []
    strona.page.on_route_change = lambda e: trasy.append(strona.page.route)
    stan = pomoce.stan_aplikacji(auto, "Tagowane")
    widok = pomoce.klasy_widokow()["WykresView"](strona.page, stan, "tagi")
    teksty = pomoce.napisy(widok)
    assert {"Ile kosztują twoje tagi?", "Wyjazd", "Praca", "Kawa", "Bez tagu"} <= set(teksty)

    wiersz = next(c for c in pomoce.kontrolki(widok, ft.Container) if c.tooltip == "Pokaż wpisy z tagiem „Wyjazd”")
    wiersz.on_click(None)
    assert trasy == ["/szukaj"] and stan.fraza_wyszukiwania.startswith("tag:Wyjazd od ")

    szukaj = pomoce.zbuduj_widok(pomoce.klasy_widokow()["SzukajView"], strona, stan)
    assert szukaj.pole_wyszukiwarki.value.startswith("tag:Wyjazd od ") and stan.fraza_wyszukiwania is None
    wyniki = " ".join(pomoce.napisy(szukaj.lista_wynikow))
    assert "Bramki" in wyniki and "Prom" not in wyniki and "Kawa" not in wyniki


def test_tag_ze_spacja_idzie_do_wyszukiwarki_w_cudzyslowie(baza):
    stan = pomoce.stan_aplikacji(1, "X")
    strona = pomoce.zbuduj_strone()
    strona.page.on_route_change = lambda e: None
    utils.wykresy_analizy._szukaj_tagu(strona.page, stan, "Wyjazd Chorwacja", date(2026, 8, 1))
    assert stan.fraza_wyszukiwania == 'tag:"Wyjazd Chorwacja" od 01.08.2026'
    filtr = db.parsuj_zapytanie(stan.fraza_wyszukiwania)
    assert filtr["pola"] == [("tag", "wyjazd chorwacja")] and filtr["tekst"] == ""


def test_spis_odpowiada_najdrozszym_tagiem(baza):
    auto = auto_z_tagami()
    stan = pomoce.stan_aplikacji(auto, "Tagowane")
    dane = utils.dane_wykresu(stan, "tagi")
    wartosc, _chip, zdanie, mini = utils.wykresy_analizy._odpowiedz(stan, "tagi", dane)
    assert wartosc == f"400 {utils.symbol_waluty()}" and zdanie.startswith("najwięcej: Wyjazd · 3 tagi")
    assert mini is not None

    goly = _auto("Bez tagów")
    pusty = utils.wykresy_analizy._odpowiedz(pomoce.stan_aplikacji(goly), "tagi",
                                             utils.dane_wykresu(pomoce.stan_aplikacji(goly), "tagi"))
    assert pusty[0] is None and pusty[2].startswith("Brak wydatków")


def test_edytor_tagow_pokazuje_kwote_z_tego_roku(baza, monkeypatch):
    auto = auto_z_tagami()
    okna = []
    monkeypatch.setattr(utils.komponenty, "otworz_dialog", lambda page, dlg: okna.append(dlg))
    strona = pomoce.zbuduj_strone()
    kontener, pobierz = utils.komponent_tagow(strona.page, pomoce.stan_aplikacji(auto), "Wyjazd")
    waluta = utils.symbol_waluty()
    chipy = {[k for k in c.content.controls if isinstance(k, ft.Text)][0].value: c
             for c in kontener.controls if isinstance(c.content, ft.Row)}
    assert f"400 {waluta}" in pomoce.napisy(chipy["Wyjazd"]) and f"300 {waluta}" in pomoce.napisy(chipy["Praca"])
    assert pobierz() == "Wyjazd"

    chipy["Wyjazd"].on_long_press(None)
    assert f"W tym roku: 400 {waluta} w 2 wpisach." in pomoce.napisy(okna[-1].content)
