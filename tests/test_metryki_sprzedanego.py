"""Sprzedane auto: rachunek kończy się w dniu sprzedaży, nie dzisiaj.

Utrata wartości domykała się już ceną sprzedaży, ale mianownik czasowy rósł
dalej — więc koszt miesięczny sprzedanego auta malał z każdym miesiącem sam
z siebie, bez żadnego zdarzenia w danych. Tu pilnujemy, żeby i licznik
(wydatki), i mianownik (dni posiadania, wiek) kończyły się tego samego dnia.
"""

from datetime import date, timedelta

import pytest

import db

ZAKUP = date(2024, 1, 1)
SPRZEDAZ = date(2025, 7, 1)
REJESTRACJA = date(2020, 6, 1)


def _dodaj_auto(status=db.STATUS_POJAZDU_AKTYWNY, data_sprzedazy=None, cena_sprzedazy=None):
    """Auto z kompletem danych zakupu i dwoma kosztami: przed i po sprzedaży."""
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO samochody (nazwa, marka, model, typ_paliwa, status, "
            "data_pierwszej_rejestracji, data_zakupu, cena_zakupu, przebieg_zakupu, "
            "wartosc_szacowana, data_sprzedazy, cena_sprzedazy) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("Sprzedane", "Marka", "Model", "Benzyna", status,
             REJESTRACJA.strftime("%d.%m.%Y"), ZAKUP.strftime("%d.%m.%Y"), 60000.0, 100000,
             40000.0, data_sprzedazy, cena_sprzedazy),
        )
        auto = c.lastrowid
        # przebieg (żeby było co dzielić na kilometry) — wpis sprzed sprzedaży
        c.execute(
            "INSERT INTO tankowania (auto_id, data, przebieg, litry, kwota, do_pelna) "
            "VALUES (?,?,?,?,?,?)",
            (auto, "2025-06-01", 130000, 40.0, 300.0, 1),
        )
        c.execute(
            "INSERT INTO inne_koszty (auto_id, data, kategoria, nazwa, kwota) VALUES (?,?,?,?,?)",
            (auto, "2025-03-01", "Ubezpieczenie", "OC", 1000.0),
        )
        # koszt z datą PO sprzedaży: nie należy już do rachunku posiadania
        c.execute(
            "INSERT INTO inne_koszty (auto_id, data, kategoria, nazwa, kwota) VALUES (?,?,?,?,?)",
            (auto, "2025-09-01", "Ubezpieczenie", "Zwrot polisy", 500.0),
        )
    return auto


# ==================== DOMKNIĘCIE OKRESU ====================

def test_okres_posiadania_konczy_sie_na_sprzedazy(baza):
    auto = _dodaj_auto(db.STATUS_POJAZDU_SPRZEDANY, SPRZEDAZ.strftime("%d.%m.%Y"), 38000.0)
    m = db.pobierz_metryki_pojazdu(auto)

    assert m["dni_posiadania"] == (SPRZEDAZ - ZAKUP).days
    assert m["dni_posiadania"] < (date.today() - ZAKUP).days
    assert m["zamkniete_na"] == SPRZEDAZ.strftime("%d.%m.%Y")


def test_wydatki_po_sprzedazy_nie_wchodza_do_rachunku(baza):
    auto = _dodaj_auto(db.STATUS_POJAZDU_SPRZEDANY, SPRZEDAZ.strftime("%d.%m.%Y"), 38000.0)
    m = db.pobierz_metryki_pojazdu(auto)

    assert m["wydatki_od_zakupu"] == pytest.approx(1300.0)  # 1000 + 300, bez 500 po sprzedaży


def test_koszt_miesieczny_nie_zalezy_od_dzisiejszej_daty(baza):
    auto = _dodaj_auto(db.STATUS_POJAZDU_SPRZEDANY, SPRZEDAZ.strftime("%d.%m.%Y"), 38000.0)
    m = db.pobierz_metryki_pojazdu(auto)

    miesiace = (SPRZEDAZ - ZAKUP).days / db.DNI_W_MIESIACU
    assert m["koszt_miesieczny"] == pytest.approx(m["koszt_calkowity"] / miesiace)
    # gdyby mianownik biegł do dzisiaj, koszt miesięczny byłby zauważalnie niższy
    assert m["koszt_miesieczny"] > m["koszt_calkowity"] / ((date.today() - ZAKUP).days / db.DNI_W_MIESIACU)


def test_wiek_i_tempo_jazdy_tez_zamrozone(baza):
    auto = _dodaj_auto(db.STATUS_POJAZDU_SPRZEDANY, SPRZEDAZ.strftime("%d.%m.%Y"), 38000.0)
    m = db.pobierz_metryki_pojazdu(auto)

    assert m["dni_wieku"] == (SPRZEDAZ - REJESTRACJA).days
    assert m["przebieg_roczny"] == pytest.approx(m["przebieg"] / (m["dni_wieku"] / 365.25))


# ==================== AUTO W GARAŻU I BRAKI DANYCH ====================

def test_aktywne_auto_liczy_do_dzisiaj(baza):
    auto = _dodaj_auto()
    m = db.pobierz_metryki_pojazdu(auto)

    assert m["dni_posiadania"] == (date.today() - ZAKUP).days
    assert m["zamkniete_na"] is None
    assert m["wydatki_od_zakupu"] == pytest.approx(1800.0)  # wszystkie trzy wpisy


def test_sprzedane_bez_daty_liczy_do_dzisiaj(baza):
    auto = _dodaj_auto(db.STATUS_POJAZDU_SPRZEDANY, None, 38000.0)
    m = db.pobierz_metryki_pojazdu(auto)

    assert m["dni_posiadania"] == (date.today() - ZAKUP).days
    assert m["zamkniete_na"] is None
    assert m["utrata_wartosci"] == pytest.approx(22000.0)  # cena sprzedaży dalej zamyka wartość


def test_data_sprzedazy_z_przyszlosci_nie_rozciaga_posiadania(baza):
    jutro = (date.today() + timedelta(days=1)).strftime("%d.%m.%Y")
    auto = _dodaj_auto(db.STATUS_POJAZDU_SPRZEDANY, jutro, 38000.0)
    m = db.pobierz_metryki_pojazdu(auto)

    assert m["dni_posiadania"] == (date.today() - ZAKUP).days
    assert m["zamkniete_na"] is None


def test_data_sprzedazy_przed_zakupem_nie_daje_ujemnego_okresu(baza):
    auto = _dodaj_auto(db.STATUS_POJAZDU_SPRZEDANY, "01.06.2023", 38000.0)
    m = db.pobierz_metryki_pojazdu(auto)

    assert m["dni_posiadania"] is None
    assert m["lata_posiadania"] is None
    assert m["koszt_miesieczny"] is None
