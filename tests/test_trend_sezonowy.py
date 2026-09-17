"""Sezon w trendzie spalania: listopad nie jest usterką.

`analizuj_trend_spalania` świadomie nie porównuje miesiąca do miesiąca, żeby nie
łapać efektu granicy kalendarza — ale i tak zestawiało listopad z wrześniem.
W listopadzie zawsze wychodził wzrost, bo zima: krótkie trasy, zimny silnik,
inne opony. Alarm, który zapala się co roku o tej samej porze, przestaje być
alarmem — użytkownik uczy się go przewijać i przewinie też ten prawdziwy.

Dlatego obok surowej zmiany liczymy SEZON: tę samą zmianę kalendarza na danych
sprzed roku (i sprzed dwóch, jeśli są). Dopiero różnica po jego odjęciu decyduje
o kierunku i o tym, czy obserwacja w ogóle się pojawi. Tu pilnujemy obu stron tej
umowy: że sezonowy skok milczy, a prawdziwy wzrost dalej krzyczy — łącznie
z przypadkiem odwrotnym, w którym płaski wynik na wiosnę JEST wzrostem, bo
o tej porze zużycie zwykle spada.
"""

from datetime import date, timedelta

import pytest

import db


# Umowny profil sezonowy jednego auta — ważne są nie liczby, tylko kształt roku.
ZIMA = 7.4
LATO = 6.5
MIESIACE_ZIMOWE = {10, 11, 12, 1, 2, 3}

# Każdy odcinek ma ten sam dystans, więc litry przekładają się wprost na l/100km.
DYSTANS_ODCINKA = 1000


def _sezonowo(d):
    return ZIMA if d.month in MIESIACE_ZIMOWE else LATO


def _punkty(od, do, spalanie=_sezonowo):
    """[(data, l/100km)] — po jednym odcinku na miesiąc, od (rok, miesiąc)
    do (rok, miesiąc) włącznie."""
    rok, miesiac = od
    punkty = []
    while (rok, miesiac) <= do:
        d = date(rok, miesiac, 15)
        punkty.append((d, spalanie(d)))
        rok, miesiac = (rok + 1, 1) if miesiac == 12 else (rok, miesiac + 1)
    return punkty


def _auto():
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO samochody (nazwa, marka, model, typ_paliwa, status) VALUES (?,?,?,?,?)",
            ("Sezonowy", "Marka", "Model", "Benzyna", db.STATUS_POJAZDU_AKTYWNY),
        )
        return c.lastrowid


def _zatankuj(auto_id, punkty):
    """Tankowania „do pełna” dające dokładnie zadaną serię odcinków.

    Pierwsze tankowanie tylko otwiera licznik — odcinek powstaje dopiero między
    dwoma pełnymi bakami, więc punkt nr 1 kończy się na drugim wpisie."""
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM tankowania WHERE auto_id=?", (auto_id,))
        przebieg = 100000
        start = punkty[0][0] - timedelta(days=30)
        c.execute(
            "INSERT INTO tankowania (auto_id, data, przebieg, dystans, litry, kwota, do_pelna) "
            "VALUES (?,?,?,?,?,?,1)",
            (auto_id, start.strftime("%d.%m.%Y"), przebieg, 0, 40.0, 280.0),
        )
        for data, spalanie in punkty:
            przebieg += DYSTANS_ODCINKA
            litry = spalanie * DYSTANS_ODCINKA / 100
            c.execute(
                "INSERT INTO tankowania (auto_id, data, przebieg, dystans, litry, kwota, do_pelna) "
                "VALUES (?,?,?,?,?,?,1)",
                (auto_id, data.strftime("%d.%m.%Y"), przebieg, DYSTANS_ODCINKA, litry, litry * 7.0),
            )


@pytest.fixture
def auto(baza):
    return _auto()


def test_sezonowy_skok_nie_zapala_alarmu(auto):
    """Dwie takie same jesienie z rzędu: surowo wzrost, po odjęciu sezonu zero."""
    _zatankuj(auto, _punkty((2024, 1), (2025, 11)))
    trend = db.analizuj_trend_spalania(auto)

    assert trend["zmiana_proc"] > db.PROG_ISTOTNOSCI_TRENDU
    assert trend["sezon_proc"] is not None
    assert trend["sezon_proc"] > db.PROG_ISTOTNOSCI_TRENDU
    assert abs(trend["zmiana_po_sezonie"]) < 1
    assert trend["kierunek"] == "stabilnie"
    # Nie ma czego przeliczać na złotówki: ten wzrost sam zejdzie na wiosnę.
    assert db.koszt_trendu_rocznie(auto, trend) is None
    assert "trend_spalania" not in {o["klucz"] for o in db.obserwacje_analityczne(auto)}


def test_wzrost_ponad_sezon_dalej_krzyczy(auto):
    """Ta jesień gorsza od poprzedniej — obserwacja zostaje, tylko uczciwsza."""
    punkty = [(d, w + 1.2 if d >= date(2025, 10, 1) else w)
              for d, w in _punkty((2024, 1), (2025, 11))]
    _zatankuj(auto, punkty)
    trend = db.analizuj_trend_spalania(auto)

    assert trend["kierunek"] == "wzrost"
    assert trend["zmiana_po_sezonie"] >= db.PROG_ISTOTNOSCI_TRENDU
    assert trend["zmiana_po_sezonie"] < trend["zmiana_proc"]   # sezon zabrał swoje
    assert "po odjęciu sezonu" in db.opis_sezonowosci_trendu(trend)

    trafienia = [o for o in db.obserwacje_analityczne(auto) if o["klucz"] == "trend_spalania"]
    assert trafienia and trafienia[0]["ton"] == "uwaga"
    assert "Typowo o tej porze roku" in trafienia[0]["tekst"]


def test_bez_historii_sprzed_roku_dziala_jak_dawniej(auto):
    """Pierwszy rok jazdy: nie ma z czym porównać sezonu i nic się nie psuje."""
    _zatankuj(auto, _punkty((2025, 1), (2025, 11)))
    trend = db.analizuj_trend_spalania(auto)

    assert trend["sezon_proc"] is None
    assert trend["zmiana_po_sezonie"] == trend["zmiana_proc"]
    assert trend["kierunek"] == "wzrost"
    assert trend["rdr_proc"] is None
    assert db.opis_sezonowosci_trendu(trend) is None


def test_sezon_w_druga_strone_odslania_wzrost(auto):
    """Wiosna bez spadku to wzrost, choć surowe liczby są prawie płaskie."""
    punkty = [(d, ZIMA if d >= date(2025, 3, 1) else w)
              for d, w in _punkty((2023, 10), (2025, 5))]
    _zatankuj(auto, punkty)
    trend = db.analizuj_trend_spalania(auto)

    assert trend["sezon_proc"] < -db.PROG_ISTOTNOSCI_TRENDU
    assert abs(trend["zmiana_proc"]) < db.PROG_ISTOTNOSCI_TRENDU
    assert trend["zmiana_po_sezonie"] >= db.PROG_ISTOTNOSCI_TRENDU
    assert trend["kierunek"] == "wzrost"


def test_rok_do_roku_bierze_ten_sam_kawalek_kalendarza(auto):
    """Osobne pytanie niż sezon: czy pali więcej niż rok temu o tej porze."""
    _zatankuj(auto, _punkty((2024, 1), (2025, 11)))
    trend = db.analizuj_trend_spalania(auto)

    assert trend["odcinkow_rok_temu"] >= db.MIN_ODCINKOW_SEZONU
    assert abs(trend["rdr_proc"]) < 1     # ten sam listopad co rok temu


def test_29_lutego_nie_wywraca_przesuniecia():
    assert db._przesun_o_lata(date(2024, 2, 29), 1) == date(2023, 2, 28)
    assert db._przesun_o_lata(date(2025, 11, 15), 2) == date(2023, 11, 15)
