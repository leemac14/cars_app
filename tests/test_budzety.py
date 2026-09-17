"""Budżet w oknie „ostatnie 30 dni”: ten sam pasek, inny mianownik.

Miesiąc kalendarzowy pasuje do pensji, ale nie do kosztów auta. Dwa tankowania
i przegląd potrafią wypaść w jednym tygodniu na przełomie miesiąca — wtedy
rozchodzą się po dwóch okresach i w żadnym nie wyglądają groźnie. Okno
30-dniowe liczy je razem, bo kończy się dzisiaj i przesuwa z każdym dniem.

Cena za to jest jedna: okno jest CAŁE za nami. Nie ma końca okresu, więc nie ma
czego prognozować — znika data przekroczenia i znika znacznik upływu na pasku.
Testy poniżej pilnują obu stron tej umowy: zasięgu okna i braku prognozy.
"""

from datetime import date, timedelta

import flet as ft
import pytest

import db
import pomoce
import utils


LIMIT = 1000.0


def _auto():
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO samochody (nazwa, marka, model, typ_paliwa, status) VALUES (?,?,?,?,?)",
            ("Budżetowy", "Marka", "Model", "Benzyna", db.STATUS_POJAZDU_AKTYWNY),
        )
        return c.lastrowid


def _tankowanie(auto_id, d, kwota, przebieg=10000):
    with db.polacz_baze() as conn:
        conn.execute(
            "INSERT INTO tankowania (auto_id, data, przebieg, litry, kwota) VALUES (?,?,?,?,?)",
            (auto_id, d.strftime("%d.%m.%Y"), przebieg, kwota / 6.0, kwota),
        )


def _wizyta(auto_id, d, kwota, przebieg=10000):
    with db.polacz_baze() as conn:
        conn.execute(
            "INSERT INTO wizyty (auto_id, data, przebieg, wykonawca, koszt_calkowity) VALUES (?,?,?,?,?)",
            (auto_id, d.strftime("%d.%m.%Y"), przebieg, "Serwis", kwota),
        )


def _stan(auto_id, dzis, okres="30dni", kategoria="razem"):
    for s in db.stan_budzetow(auto_id, dzis):
        if s["kategoria"] == kategoria and s["okres"] == okres:
            return s
    raise AssertionError(f"brak stanu dla {kategoria}/{okres}")


def _podpis(pasek):
    return [k for k in pasek.controls if isinstance(k, ft.Text)][-1].value


def _warstwy_paska(pasek):
    return [k for k in pasek.controls if isinstance(k, ft.Stack)][0].controls


def test_limit_30dni_zapisuje_sie_obok_miesiaca_i_roku(baza):
    """Trzeci okres to nowa wartość w istniejącej kolumnie — bez migracji.
    Kolejność, w jakiej ekran układa karty: miesiąc, okno, rok."""
    auto = _auto()

    for okres in ("rok", "30dni", "miesiac"):
        assert db.zapisz_budzet(auto, "paliwo", okres, 500) is True

    assert [b["okres"] for b in db.pobierz_budzety(auto)] == ["miesiac", "30dni", "rok"]


def test_okno_konczy_sie_dzisiaj_i_siega_30_dni_wstecz(baza):
    """Granica okna jest twarda: dzień sprzed 29 jeszcze się liczy, sprzed 30
    już wypadł. Całe okno jest minione, więc mianownik to zawsze 30 dni."""
    auto = _auto()
    dzis = date(2026, 6, 15)
    db.zapisz_budzet(auto, "razem", "30dni", LIMIT)
    _tankowanie(auto, dzis, 100)
    _tankowanie(auto, dzis - timedelta(days=29), 100)
    _tankowanie(auto, dzis - timedelta(days=30), 100)

    s = _stan(auto, dzis)

    assert s["wydano"] == pytest.approx(200.0)
    assert (s["poczatek"], s["koniec"]) == (dzis - timedelta(days=29), dzis)
    assert (s["dni_okresu"], s["dni_minione"]) == (30, 30)


def test_przelom_miesiaca_nie_dzieli_wydatkow_na_dwa_okresy(baza):
    """Sedno trzeciego okresu. Dwa tankowania i przegląd w ciągu sześciu dni,
    ale po dwóch stronach pierwszego dnia miesiąca: limit miesięczny widzi sam
    ogon i mieści się w kwocie, okno 30-dniowe widzi całość i pęka."""
    auto = _auto()
    dzis = date(2026, 6, 3)
    for okres in ("miesiac", "30dni"):
        db.zapisz_budzet(auto, "razem", okres, LIMIT)
    _tankowanie(auto, date(2026, 5, 28), 350)
    _tankowanie(auto, date(2026, 6, 1), 350)
    _wizyta(auto, date(2026, 6, 2), 400)

    miesiac = _stan(auto, dzis, okres="miesiac")
    okno = _stan(auto, dzis)

    assert miesiac["wydano"] == pytest.approx(750.0)
    assert miesiac["status"] != "przekroczony"
    assert okno["wydano"] == pytest.approx(1100.0)
    assert okno["status"] == "przekroczony"


def test_okno_nie_prognozuje(baza):
    """Koniec okna to dzisiaj, więc nie ma dnia, na który wypada wyczerpanie
    limitu. „Tempo” jest wtedy równe temu, co już wydano — bez ekstrapolacji,
    która w ruchomym oknie liczyłaby drugi raz te same wydatki."""
    auto = _auto()
    dzis = date(2026, 6, 15)
    db.zapisz_budzet(auto, "razem", "30dni", LIMIT)
    _tankowanie(auto, dzis - timedelta(days=1), 850)

    s = _stan(auto, dzis)

    assert s["ruchomy"] is True
    assert s["dzien_przekroczenia"] is None
    assert s["tempo"] == pytest.approx(s["wydano"])
    assert s["status"] == "uwaga"


def test_miesiac_dalej_prognozuje(baza):
    """Kontrola odwrotna: zmiana nie ruszyła okresów kalendarzowych — miesiąc
    nadal podaje datę, na którą wypada wyczerpanie limitu."""
    auto = _auto()
    dzis = date(2026, 6, 10)
    db.zapisz_budzet(auto, "razem", "miesiac", LIMIT)
    _tankowanie(auto, date(2026, 6, 2), 500)

    s = _stan(auto, dzis, okres="miesiac")

    assert s["ruchomy"] is False
    assert s["dzien_przekroczenia"] is not None
    assert s["tempo"] > s["wydano"]


def test_pasek_okna_jest_bez_znacznika_uplywu(baza):
    """Kreska „tyle okresu już minęło” w oknie ruchomym stałaby zawsze na
    końcu paska. Pasek miesięczny ma trzy warstwy (tor, wypełnienie, kreska),
    pasek okna dwie — reszta bez zmian."""
    auto = _auto()
    dzis = date(2026, 6, 15)
    for okres in ("miesiac", "30dni"):
        db.zapisz_budzet(auto, "razem", okres, LIMIT)
    _tankowanie(auto, dzis - timedelta(days=1), 400)
    strona = pomoce.zbuduj_strone()

    miesiac = utils.pasek_budzetu(strona, _stan(auto, dzis, okres="miesiac"))
    okno = utils.pasek_budzetu(strona, _stan(auto, dzis))

    assert len(_warstwy_paska(miesiac)) == 3
    assert len(_warstwy_paska(okno)) == 2


def test_podpis_okna_nie_obiecuje_dni_do_konca(baza):
    """W oknie nie zostało ani jednego dnia — podpis musi mówić, ile zostało
    do limitu, a nie „na 0 dni”."""
    auto = _auto()
    dzis = date(2026, 6, 15)
    db.zapisz_budzet(auto, "razem", "30dni", LIMIT)
    _tankowanie(auto, dzis - timedelta(days=1), 400)

    podpis = _podpis(utils.pasek_budzetu(pomoce.zbuduj_strone(), _stan(auto, dzis)))

    assert "ostatnie 30 dni" in podpis
    assert "na 0 dni" not in podpis


def test_obserwacja_nazywa_okres_po_imieniu(baza):
    """Limit miesięczny i 30-dniowy na tę samą kategorię dają dwie osobne
    obserwacje. Bez nazwy okresu w treści wyglądałyby na duplikat jednej."""
    auto = _auto()
    db.zapisz_budzet(auto, "razem", "30dni", 500)
    _tankowanie(auto, date.today(), 600)

    obserwacje = {o["klucz"]: o for o in db.obserwacje_analityczne(auto)}

    assert "budzet_razem_30dni" in obserwacje
    assert "ostatnie 30 dni" in obserwacje["budzet_razem_30dni"]["tekst"]
