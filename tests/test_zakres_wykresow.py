"""Zakres czasu wykresów: siatka słupków, zapamiętanie per pojazd i obcięcie danych.

Agregacja jest tu sednem: przy trzech latach historii „Wszystko” ma dać
kilkanaście czytelnych słupków, a nie trzydzieści sześć kresek. Zakres jedzie
też z pojazdem do kosza — po przywróceniu ID bywa inne, więc to nie jest
oczywiste samo z siebie."""
import datetime

import db
import pytest
import utils

import pomoce


def test_siatka_slupkow_agreguje():
    dzis = datetime.date(2026, 9, 19)
    assert len(utils.okresy_slupkow(3, None, dzis)) == 3
    assert len(utils.okresy_slupkow(6, None, dzis)) == 6
    assert len(utils.okresy_slupkow(12, None, dzis)) == 12
    # trzy lata historii -> kwartały, nie 36 słupków
    kwartaly = utils.okresy_slupkow(0, "2023-10", dzis)
    assert len(kwartaly) == 12 and kwartaly[0][0] == "4kw/23"
    # ponad trzy lata -> lata
    lata = utils.okresy_slupkow(0, "2021-01", dzis)
    assert [e for e, _ in lata] == ["2021", "2022", "2023", "2024", "2025", "2026"]
    # każdy miesiąc trafia do dokładnie jednego słupka
    wszystkie = [k for _, klucze in kwartaly for k in klucze]
    assert len(wszystkie) == len(set(wszystkie)) == 12 * 3


def test_tygodnie_heatmapy():
    dzis = datetime.date(2026, 9, 19)
    assert utils.tygodnie_zakresu(3, (), dzis) == 14
    assert utils.tygodnie_zakresu(12, (), dzis) == 53
    assert utils.tygodnie_zakresu(0, ["01.01.2020"], dzis) == 261  # sufit


def test_zakres_zapamietany_per_pojazd(baza):
    idy = pomoce.utworz_pojazd("Z zakresem")
    auto = idy["auto_id"]
    assert db.pobierz_zakres_wykresu(auto, "wydatki") == 12
    db.zapisz_zakres_wykresu(auto, "wydatki", 3)
    db.zapisz_zakres_wykresu(auto, "spalanie", 0)
    assert db.pobierz_zakres_wykresu(auto, "wydatki") == 3
    assert db.pobierz_zakres_wykresu(auto, "spalanie") == 0
    assert db.pobierz_zakres_wykresu(auto, "ceny") == 12  # cudzy zakres nie przecieka
    db.zapisz_zakres_wykresu(auto, "wydatki", 99)  # śmieć -> wartość domyślna
    assert db.pobierz_zakres_wykresu(auto, "wydatki") == 12


def test_zakresy_jada_z_pojazdem_do_kosza(baza):
    idy = pomoce.utworz_pojazd("Do kosza")
    db.zapisz_zakres_wykresu(idy["auto_id"], "wydatki", 6)
    db.usun_auto_do_kosza(idy["auto_id"])
    nowe_id = db.przywroc_auto_z_kosza(db.pobierz_kosz()[0]["id"])
    assert db.pobierz_zakres_wykresu(nowe_id, "wydatki") == 6


def test_trend_cen_obcina_od_daty(baza):
    idy = pomoce.utworz_pojazd("Cenowy")
    auto = idy["auto_id"]
    with db.polacz_baze() as conn:
        conn.execute("DELETE FROM tankowania WHERE auto_id=?", (auto,))
        for data, litry, kwota, stacja in [
            ("01.01.2024", 40, 240, "Stara"),
            ("01.08.2026", 40, 280, "Nowa"),
        ]:
            conn.execute(
                "INSERT INTO tankowania (auto_id, data, przebieg, litry, kwota, stacja) VALUES (?,?,?,?,?,?)",
                (auto, data, 10000, litry, kwota, stacja))
    calosc = db.pobierz_trend_cen_paliwa(auto)
    ciety = db.pobierz_trend_cen_paliwa(auto, datetime.date(2026, 1, 1))
    assert len(calosc["punkty"]) == 2 and len(ciety["punkty"]) == 1
    assert [s["nazwa"] for s in ciety["stacje"]] == ["Nowa"]


@pytest.mark.parametrize("miesiace", [3, 6, 12, 0])
def test_zakladka_wykresow_buduje_sie_dla_kazdego_zakresu(baza, miesiace):
    stan, idy = pomoce.przygotuj_scenariusz("pojazd_z_historia")
    with db.polacz_baze() as conn:
        conn.execute(
            "INSERT INTO inne_koszty (auto_id, data, kwota, nazwa, kategoria) VALUES (?,?,?,?,?)",
            (idy["auto_id"], "15.03.2023", 500.0, "Stary wpis", "Mandat"))
    for klucz in ("struktura", "kategorie", "wydatki", "spalanie", "ceny"):
        db.zapisz_zakres_wykresu(idy["auto_id"], klucz, miesiace)
    stan.stat_podzakladka = 1
    strona = pomoce.zbuduj_strone()
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], strona, stan)
    assert pomoce.policz_kontrolki(widok) > 50
