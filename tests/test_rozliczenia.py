"""Saldo współdzielonego auta i „Rozliczone” (U-19).

Ekran podziału pokazywał proporcje miesiąca, ale nie prowadził rachunku.
Saldo liczy się teraz z całej podpisanej historii minus migawki rozliczeń,
a to jest miejsce, które najłatwiej zepsuć po cichu:

* rozliczenie ma wyzerować saldo CO DO GROSZA, także przy kwotach, które nie
  dzielą się równo, a suma sald ma być zawsze zerem;
* wpis sprzed rozliczenia dopisany, poprawiony albo usunięty po nim (albo
  przysłany z drugiego telefonu dzień później) ma trafić do bieżącego salda,
  a nie przepaść — przy dacie odcięcia zniknąłby bez śladu;
* dwa „Rozliczone” kliknięte naraz na dwóch telefonach nie mogą wyzerować
  salda dwa razy — odwróciłoby się wtedy na drugą stronę;
* rozliczenie jedzie do chmury, zostawia nagrobek po cofnięciu i wraca
  z kosza razem z pojazdem.
"""

import json
import random
from datetime import date, timedelta

import flet as ft
import pytest

import audyty
import db
import pomoce
import sync
import utils
from sync import pobieranie as sync_pobieranie
from sync import wysylanie as sync_wysylanie


# ============================================================================
#  POMOCE
# ============================================================================

def dzien(dni_temu):
    return (date.today() - timedelta(days=dni_temu)).strftime("%d.%m.%Y")


def auto(nazwa="Wspólne", rola=db.ROLA_WLASCICIEL, wspolny="wspolny-1"):
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO samochody (nazwa, typ_paliwa, status, wspolny_pojazd_id, rola_wspoldzielenia) "
            "VALUES (?,?,?,?,?)", (nazwa, "Benzyna", db.STATUS_POJAZDU_AKTYWNY, wspolny, rola),
        )
        return c.lastrowid


def tankowanie(a, dni, kwota, kto, przebieg=10000):
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO tankowania (auto_id, data, przebieg, dystans, litry, kwota, dodane_przez) "
                  "VALUES (?,?,?,?,?,?,?)", (a, dzien(dni), przebieg, 400.0, kwota / 6.5, kwota, kto))
        return c.lastrowid


def inny(a, dni, kwota, kto, data=None):
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO inne_koszty (auto_id, data, kategoria, nazwa, kwota, dodane_przez) "
                  "VALUES (?,?,?,?,?,?)", (a, data or dzien(dni), "Myjnia i kosmetyka", "Myjnia", kwota, kto))
        return c.lastrowid


def podzespol(a):
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO zadania (auto_id, nazwa, interwal_km) VALUES (?,?,?)", (a, "Olej", 15000))
        return c.lastrowid


def wizyta(a, dni, kwota, kto, pozycje=()):
    zadanie = podzespol(a)
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO wizyty (auto_id, data, przebieg, wykonawca, koszt_calkowity, dodane_przez) "
                  "VALUES (?,?,?,?,?,?)", (a, dzien(dni), 10000, "Warsztat", kwota, kto))
        w_id = c.lastrowid
        for cena in pozycje:
            c.execute("INSERT INTO historia (zadanie_id, wizyta_id, data, przebieg, kategoria, cena, dodane_przez) "
                      "VALUES (?,?,?,?,?,?,?)", (zadanie, w_id, dzien(dni), 10000, "Serwis", cena, kto))
        return w_id


def wpis(a, dni, cena, kto):
    zadanie = podzespol(a)
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO historia (zadanie_id, data, przebieg, kategoria, cena, dodane_przez) "
                  "VALUES (?,?,?,?,?,?)", (zadanie, dzien(dni), 10000, "Serwis", cena, kto))
        return c.lastrowid


def salda(a, do_dnia=None):
    return {o["osoba"]: o["saldo"] for o in db.saldo_rozliczen(a, do_dnia)["osoby"]}


def w_groszach(a):
    return sum(round(o["saldo"] * 100) for o in db.saldo_rozliczen(a)["osoby"])


def wiersz_rozliczenia(r_id):
    with db.polacz_baze() as conn:
        conn.row_factory = __import__("sqlite3").Row
        return dict(conn.execute("SELECT * FROM rozliczenia WHERE id=?", (r_id,)).fetchone())


@pytest.fixture
def ja(baza):
    """Ten telefon podpisuje wpisy jako Kamil."""
    db.zapisz_moje_imie("Kamil")
    return "Kamil"


@pytest.fixture
def wspolne(ja):
    """Kamil zatankował za 300 zł, Ola zapłaciła za myjnię 100 zł."""
    a = auto()
    tankowanie(a, 10, 300.0, "Kamil")
    inny(a, 8, 100.0, "Ola")
    return a


# ============================================================================
#  SALDO
# ============================================================================

def test_dwie_osoby_saldo_i_jeden_przelew(wspolne):
    s = db.saldo_rozliczen(wspolne)

    assert salda(wspolne) == {"Kamil": 100.0, "Ola": -100.0}
    assert s["przelewy"] == [{"od": "Ola", "do": "Kamil", "kwota": 100.0}]
    kamil = next(o for o in s["osoby"] if o["osoba"] == "Kamil")
    assert (kamil["zaplacil"], kamil["przypada"], kamil["korekta"]) == (300.0, 200.0, 0.0)
    assert (s["suma"], s["na_osobe"], s["uczestnikow"], s["od_dnia"], s["rozliczen"]) == (400.0, 200.0, 2, None, 0)


def test_kto_nic_nie_zaplacil_tez_ponosi_czesc(baza):
    """Dawny ekran pokazywał przy jednej płacącej osobie „dokładnie tyle, ile
    powinien” — druga osoba nie istniała, bo nie miała ani jednego wpisu."""
    db.zapisz_moje_imie("Ola")
    a = auto()
    tankowanie(a, 5, 200.0, "Kamil")

    assert salda(a) == {"Kamil": 100.0, "Ola": -100.0}


def test_podglad_nie_dzieli_kosztow_i_nie_rozlicza(baza):
    db.zapisz_moje_imie("Dziadek")
    a = auto(rola=db.ROLA_PODGLAD)
    tankowanie(a, 5, 200.0, "Kamil")
    inny(a, 4, 100.0, "Ola")

    assert salda(a) == {"Kamil": 50.0, "Ola": -50.0}
    assert db.zapisz_rozliczenie(a) is None
    assert db.pobierz_rozliczenia(a) == []


def test_wizyta_raz_jej_wpisy_wcale_a_wydatki_bez_podpisu_poza_saldem(ja):
    a = auto()
    wizyta(a, 9, 500.0, "Kamil", pozycje=(200.0, 300.0))
    wpis(a, 7, 100.0, "Ola")
    inny(a, 6, 999.0, None)

    s = db.saldo_rozliczen(a)

    assert s["suma"] == 600.0
    assert salda(a) == {"Kamil": 200.0, "Ola": -200.0}
    assert (s["bez_podpisu"], s["kwota_bez_podpisu"]) == (1, 999.0)


def test_podpis_rozny_wielkoscia_liter_to_ta_sama_osoba(ja):
    a = auto()
    inny(a, 0, 100.0, "Ola", data="10.03.2026")
    inny(a, 0, 100.0, " ola  ", data="11.03.2026")
    inny(a, 0, 100.0, "Ola", data="12.03.2026")
    inny(a, 0, 100.0, "Kamil", data="13.03.2026")

    assert salda(a) == {"Ola": 100.0, "Kamil": -100.0}
    miesiac = db.pobierz_podzial_kosztow(a, 2026, 3)
    assert [(m["osoba"], m["razem"]) for m in miesiac] == [("Ola", 300.0), ("Kamil", 100.0)]


def test_rozliczone_zeruje_co_do_grosza_przy_nierownym_podziale(baza):
    db.zapisz_moje_imie("Ania")
    a = auto()
    inny(a, 6, 100.00, "Ania")
    inny(a, 5, 0.01, "Bartek")
    inny(a, 4, 33.33, "Celina")
    przed = db.saldo_rozliczen(a)
    assert w_groszach(a) == 0

    r_id = db.zapisz_rozliczenie(a, notatka="  BLIK   do Ani ")

    assert r_id
    assert all(o["saldo"] == 0.0 for o in db.saldo_rozliczen(a)["osoby"])
    assert db.saldo_rozliczen(a)["przelewy"] == []
    historia = db.pobierz_rozliczenia(a)
    assert historia[0]["przelewy"] == przed["przelewy"]
    assert historia[0]["notatka"] == "BLIK do Ani"
    assert historia[0]["dodane_przez"] == "Ania"
    zapis = wiersz_rozliczenia(r_id)
    # Migawka w groszach i komplet uczestników — z nich drugi telefon liczy to samo.
    assert json.loads(zapis["uczestnicy"]) == ["Ania", "Bartek", "Celina"]
    assert sum(json.loads(zapis["salda"]).values()) == 0


def test_suma_sald_jest_zawsze_zerem(baza):
    db.zapisz_moje_imie("Ania")
    los = random.Random(19)
    a = auto()
    osoby = ["Ania", "Bartek", "Celina", "Darek"]
    for krok in range(6):
        for _ in range(7):
            inny(a, 60 - krok * 10 + los.randint(0, 9), round(los.uniform(0.01, 480), 2), los.choice(osoby))
        assert w_groszach(a) == 0
        if krok % 2:
            db.zapisz_rozliczenie(a, dzien(60 - krok * 10))
            assert w_groszach(a) == 0


# ============================================================================
#  ROZLICZENIE NIE JEST DATĄ ODCIĘCIA
# ============================================================================

def test_wpis_sprzed_rozliczenia_dopisany_po_nim_trafia_do_salda(wspolne):
    """Tankowanie Oli z poniedziałku doszło z jej telefonu dopiero po tym, jak
    Kamil kliknął „Rozliczone” — ma się pojawić, a nie przepaść."""
    db.zapisz_rozliczenie(wspolne)

    tankowanie(wspolne, 3, 80.0, "Ola")

    s = db.saldo_rozliczen(wspolne)
    assert salda(wspolne) == {"Ola": 40.0, "Kamil": -40.0}
    assert s["korekty"] is True and s["od_dnia"] == date.today()
    ola = next(o for o in s["osoby"] if o["osoba"] == "Ola")
    assert (ola["zaplacil"], ola["korekta"]) == (0.0, 40.0)


def test_poprawka_i_usuniecie_starego_wpisu_koryguja_saldo(wspolne):
    with db.polacz_baze() as conn:
        t_id = conn.execute("SELECT id FROM tankowania WHERE auto_id=?", (wspolne,)).fetchone()[0]
    db.zapisz_rozliczenie(wspolne)

    with db.polacz_baze() as conn:
        conn.execute("UPDATE tankowania SET kwota=250 WHERE id=?", (t_id,))
    assert salda(wspolne) == {"Ola": 25.0, "Kamil": -25.0}

    # Ola oddała 100 zł za paliwo, którego już nie ma, i sama zapłaciła za myjnię.
    db.usun_z_cofnieciem("tankowania", t_id)
    assert salda(wspolne) == {"Ola": 150.0, "Kamil": -150.0}


def test_rozliczenie_z_data_wstecz_zostawia_pozniejsze_wpisy(ja):
    a = auto()
    tankowanie(a, 10, 200.0, "Kamil")
    tankowanie(a, 2, 100.0, "Ola")

    podglad = db.saldo_rozliczen(a, date.today() - timedelta(days=5))
    assert podglad["przelewy"] == [{"od": "Ola", "do": "Kamil", "kwota": 100.0}]

    db.zapisz_rozliczenie(a, dzien(5))

    s = db.saldo_rozliczen(a)
    assert salda(a) == {"Ola": 50.0, "Kamil": -50.0}
    assert s["od_dnia"] == date.today() - timedelta(days=5) and s["suma"] == 100.0 and not s["korekty"]


def test_data_rozliczenia_nie_z_przyszlosci_ani_sprzed_poprzedniego(wspolne):
    jutro = (date.today() + timedelta(days=1)).strftime("%d.%m.%Y")
    assert db.blad_daty_rozliczenia(wspolne, "") == "Podaj datę rozliczenia"
    assert "przyszłości" in db.blad_daty_rozliczenia(wspolne, jutro)
    assert db.zapisz_rozliczenie(wspolne, jutro) is None

    db.zapisz_rozliczenie(wspolne, dzien(2))

    assert "nie może być wcześniejsze" in db.blad_daty_rozliczenia(wspolne, dzien(5))
    assert db.zapisz_rozliczenie(wspolne, dzien(5)) is None
    assert db.blad_daty_rozliczenia(wspolne, dzien(2)) is None
    assert len(db.pobierz_rozliczenia(wspolne)) == 1


def test_nowy_domownik_nie_placi_za_zamkniety_okres(ja):
    a = auto()
    tankowanie(a, 20, 200.0, "Kamil")
    inny(a, 18, 100.0, "Ola")
    db.zapisz_rozliczenie(a, dzien(15))

    inny(a, 5, 90.0, "Celina")
    assert salda(a) == {"Celina": 60.0, "Kamil": -30.0, "Ola": -30.0}

    # Spóźniony wpis z zamkniętego okresu dzieli się tylko między tych, którzy
    # wtedy dzielili auto — Celiny jeszcze nie było.
    tankowanie(a, 17, 60.0, "Kamil")
    assert salda(a) == {"Celina": 60.0, "Kamil": 0.0, "Ola": -60.0}


# ============================================================================
#  COFANIE, ROLE I RÓWNOLEGŁE ROZLICZENIA
# ============================================================================

def test_cofnac_mozna_tylko_ostatnie_a_cofniecie_sie_cofa(wspolne):
    pierwsze = db.zapisz_rozliczenie(wspolne, dzien(5))
    inny(wspolne, 1, 60.0, "Ola")
    drugie = db.zapisz_rozliczenie(wspolne)
    inny(wspolne, 0, 20.0, "Kamil")
    przed_cofnieciem = salda(wspolne)

    assert db.cofnij_rozliczenie(wspolne, pierwsze) is None

    wynik = db.cofnij_rozliczenie(wspolne, drugie)
    assert wynik
    assert salda(wspolne) == {"Ola": 20.0, "Kamil": -20.0}
    assert [r["id"] for r in db.pobierz_rozliczenia(wspolne)] == [pierwsze]

    wynik["cofnij"]()
    assert salda(wspolne) == przed_cofnieciem == {"Kamil": 10.0, "Ola": -10.0}


def test_wspolautor_cofa_tylko_swoje_rozliczenie(baza):
    a = auto(rola=db.ROLA_WSPOLAUTOR)
    tankowanie(a, 10, 300.0, "Kamil")
    inny(a, 8, 100.0, "Ola")
    db.zapisz_moje_imie("Kamil")
    cudze = db.zapisz_rozliczenie(a, dzien(3))
    db.zapisz_moje_imie("Ola")

    assert db.cofnij_rozliczenie(a, cudze) is None

    inny(a, 1, 50.0, "Ola")
    moje = db.zapisz_rozliczenie(a)
    assert moje and db.cofnij_rozliczenie(a, moje)


def test_dwa_rozliczone_naraz_licza_sie_raz(wspolne):
    """Kamil i Ola klikają „Rozliczone” każde u siebie, zanim telefony się
    wymienią danymi. Bez łańcucha poprzedników saldo wyzerowałoby się dwa
    razy i Kamil byłby nagle winien Oli 100 zł."""
    pierwsze = db.zapisz_rozliczenie(wspolne)
    zapis = wiersz_rozliczenia(pierwsze)
    with db.polacz_baze() as conn:
        conn.execute(
            "INSERT INTO rozliczenia (auto_id, data, uczestnicy, salda, przelewy, klucz, poprzednie, "
            "dodane_przez, data_utworzenia) VALUES (?,?,?,?,?,?,?,?,?)",
            (wspolne, zapis["data"], zapis["uczestnicy"], zapis["salda"], zapis["przelewy"], "telefon-oli",
             zapis["poprzednie"], "Ola", "2099-01-01 00:00:00"),
        )

    assert salda(wspolne) == {"Kamil": 0.0, "Ola": 0.0}
    historia = db.pobierz_rozliczenia(wspolne)
    assert [(r["dodane_przez"], r["liczy_sie"], r["do_cofniecia"]) for r in historia] == [
        ("Ola", False, True), ("Kamil", True, True)]

    # Następne rozliczenie buduje na tym, które się liczy.
    inny(wspolne, 0, 40.0, "Ola")
    trzecie = db.zapisz_rozliczenie(wspolne)
    assert wiersz_rozliczenia(trzecie)["poprzednie"] == zapis["klucz"]
    assert salda(wspolne) == {"Kamil": 0.0, "Ola": 0.0}

    # Równoległe można usunąć w każdej chwili — saldo się nie rusza.
    rownolegle = next(r["id"] for r in historia if not r["liczy_sie"])
    assert db.cofnij_rozliczenie(wspolne, rownolegle)
    assert salda(wspolne) == {"Kamil": 0.0, "Ola": 0.0}


# ============================================================================
#  SYNCHRONIZACJA I KOSZ
# ============================================================================

class _Odpowiedz:
    def __init__(self, data=None):
        self.data = data


class ChmuraWPamieci:
    """Supabase na tyle, na ile potrzebuje go `_wypchnij_tabele`."""

    def __init__(self):
        self.rekordy = {}
        self.wyslane = []

    def rpc(self, nazwa, parametry):
        chmura = self

        class _Wywolanie:
            def execute(self):
                chmura.wyslane.append(nazwa)
                if nazwa == "aktualizuj_zdalny_rekord":
                    chmura.rekordy[parametry["p_id"]] = parametry["p_dane"]
                    return _Odpowiedz()
                nowe = f"zdalne-{len(chmura.rekordy) + 1}"
                chmura.rekordy[nowe] = json.loads(json.dumps(parametry["p_dane"]))
                return _Odpowiedz(nowe)
        return _Wywolanie()

    def table(self, _nazwa):
        chmura = self

        class _Zapytanie:
            def select(self, *_):
                return self

            def in_(self, _pole, identyfikatory):
                self.identyfikatory = list(identyfikatory)
                return self

            def execute(self):
                return _Odpowiedz([{"id": i, "dane": chmura.rekordy[i]} for i in self.identyfikatory
                                   if i in chmura.rekordy])
        return _Zapytanie()


KONFIG = next(k for k in sync.KONFIGURACJA_SYNC if k["tabela"] == "rozliczenia")


def wyslij(chmura, a):
    return sync_wysylanie._wypchnij_tabele(chmura, "wspolny-1", a, KONFIG, db.ROLA_WLASCICIEL)[0]


def odbierz(chmura, a):
    """Drugi telefon pobiera wszystko, czego jeszcze nie ma."""
    with db.polacz_baze() as conn:
        znane = {z: {"id": i, "hash": h} for i, z, h in conn.execute(
            "SELECT id, zdalne_id, zdalny_hash FROM rozliczenia WHERE auto_id=? AND zdalne_id IS NOT NULL", (a,))}
    return sum(sync_pobieranie._zastosuj_rekord(KONFIG, {"id": z, "dane": d}, a, znane)
               for z, d in chmura.rekordy.items())


def dwa_telefony():
    """Ten sam wspólny samochód widziany z dwóch telefonów (dwa pojazdy w jednej
    bazie testowej, z tymi samymi wpisami)."""
    telefony = []
    for nazwa in ("Telefon Kamila", "Telefon Oli"):
        a = auto(nazwa)
        tankowanie(a, 10, 300.0, "Kamil")
        inny(a, 8, 100.0, "Ola")
        telefony.append(a)
    return telefony


def test_rozliczenie_dochodzi_do_drugiego_telefonu_i_zeruje_tam_saldo(ja):
    kamil, ola = dwa_telefony()
    db.zapisz_rozliczenie(kamil, notatka="BLIK")
    chmura = ChmuraWPamieci()

    assert wyslij(chmura, kamil) == 1
    assert odbierz(chmura, ola) == 1

    assert salda(ola) == {"Kamil": 0.0, "Ola": 0.0}
    assert db.pobierz_rozliczenia(ola)[0]["przelewy"] == [{"od": "Ola", "do": "Kamil", "kwota": 100.0}]
    assert db.pobierz_rozliczenia(ola)[0]["notatka"] == "BLIK"
    # Treść wraca bez zmian, więc drugi telefon niczego nie odsyła z powrotem.
    assert wyslij(chmura, ola) == 0 and chmura.wyslane == ["dodaj_zdalny_rekord"]


def test_dwa_telefony_rozliczone_naraz_przez_chmure(ja):
    kamil, ola = dwa_telefony()
    db.zapisz_rozliczenie(kamil)
    pozniejsze = db.zapisz_rozliczenie(ola)
    with db.polacz_baze() as conn:
        conn.execute("UPDATE rozliczenia SET data_utworzenia='2099-01-01 00:00:00' WHERE id=?", (pozniejsze,))
    chmura = ChmuraWPamieci()

    wyslij(chmura, kamil)
    wyslij(chmura, ola)
    odbierz(chmura, kamil)
    odbierz(chmura, ola)

    for telefon in (kamil, ola):
        assert salda(telefon) == {"Kamil": 0.0, "Ola": 0.0}
        assert sorted(r["liczy_sie"] for r in db.pobierz_rozliczenia(telefon)) == [False, True]


def test_cofniecie_rozliczenia_zostawia_nagrobek(wspolne):
    r_id = db.zapisz_rozliczenie(wspolne)
    with db.polacz_baze() as conn:
        conn.execute("UPDATE rozliczenia SET zdalne_id='rozl-z-chmury' WHERE id=?", (r_id,))

    wynik = db.cofnij_rozliczenie(wspolne, r_id)

    assert ("rozliczenia", "rozl-z-chmury") in {(t, z) for _, t, z in db.pobierz_nagrobki(wspolne)}
    wynik["cofnij"]()
    assert db.pobierz_nagrobki(wspolne) == []
    assert salda(wspolne) == {"Kamil": 0.0, "Ola": 0.0}


def test_rozliczenia_wracaja_z_kosza_z_tym_samym_saldem(wspolne):
    db.zapisz_rozliczenie(wspolne, dzien(4))
    tankowanie(wspolne, 6, 50.0, "Ola")
    inny(wspolne, 1, 30.0, "Kamil")
    przed = (db.saldo_rozliczen(wspolne), db.pobierz_rozliczenia(wspolne))

    wynik = db.usun_auto_do_kosza(wspolne)
    assert db.pobierz_rozliczenia(wspolne) == []
    przywrocone = db.przywroc_auto_z_kosza(wynik["kosz_id"])

    assert przywrocone == wspolne
    assert (db.saldo_rozliczen(wspolne), db.pobierz_rozliczenia(wspolne)) == przed


# ============================================================================
#  EKRAN
# ============================================================================

def teksty(korzen):
    wynik, do_odwiedzenia = [], [korzen]
    while do_odwiedzenia:
        kontrolka = do_odwiedzenia.pop()
        for pole in ("value", "label", "tooltip"):
            wartosc = getattr(kontrolka, pole, None)
            if isinstance(wartosc, str):
                wynik.append(wartosc)
        if isinstance(getattr(kontrolka, "content", None), str):
            wynik.append(kontrolka.content)
        for pole in ("controls", "content", "title", "actions"):
            dziecko = getattr(kontrolka, pole, None)
            if isinstance(dziecko, (list, tuple)):
                do_odwiedzenia.extend(d for d in dziecko if isinstance(d, ft.Control))
            elif isinstance(dziecko, ft.Control):
                do_odwiedzenia.append(dziecko)
    return wynik


def kontrolki(korzen, typ):
    wynik, do_odwiedzenia = [], [korzen]
    while do_odwiedzenia:
        kontrolka = do_odwiedzenia.pop()
        if isinstance(kontrolka, typ):
            wynik.append(kontrolka)
        for pole in ("controls", "content", "title", "actions"):
            dziecko = getattr(kontrolka, pole, None)
            if isinstance(dziecko, (list, tuple)):
                do_odwiedzenia.extend(d for d in dziecko if isinstance(d, ft.Control))
            elif isinstance(dziecko, ft.Control):
                do_odwiedzenia.append(dziecko)
    return wynik


@pytest.fixture
def ekran(monkeypatch):
    """Buduje ekran podziału; dialogi, komunikaty i nawigacja lądują w liście."""
    from views.podzial_view import PodzialKosztowView

    zdarzenia = {"dialogi": [], "komunikaty": [], "cofnij": [], "wysylki": []}
    monkeypatch.setattr(utils, "przejdz", lambda page, trasa: None)
    monkeypatch.setattr(utils, "otworz_dialog", lambda page, dlg: zdarzenia["dialogi"].append(dlg))
    monkeypatch.setattr(utils, "zamknij_dialog", lambda page, dlg: None)
    monkeypatch.setattr(utils, "potwierdz", lambda page, tytul, tresc, akcja, **k: akcja())
    monkeypatch.setattr(utils, "pokaz_komunikat", lambda page, tekst, *a, **k: zdarzenia["komunikaty"].append(tekst))
    monkeypatch.setattr(utils, "pokaz_komunikat_cofnij",
                        lambda page, tekst, wynik, **k: zdarzenia["cofnij"].append((tekst, wynik)))
    monkeypatch.setattr(utils, "wypchnij_w_tle", lambda page, a, powod="": zdarzenia["wysylki"].append(powod))

    def zbuduj(a):
        strona = pomoce.zbuduj_strone()
        widok = PodzialKosztowView(strona.page, pomoce.stan_aplikacji(a, "Wspólne"))
        widok._strona_testowa = strona
        return widok

    zdarzenia["zbuduj"] = zbuduj
    return zdarzenia


def przycisk_rozliczenia(widok):
    return next((b for b in kontrolki(widok, ft.FilledButton) if b.content == "Rozliczone"), None)


def test_ekran_pokazuje_saldo_kto_komu_i_przycisk(wspolne, ekran):
    widok = ekran["zbuduj"](wspolne)
    napisy = teksty(widok)
    w = utils.symbol_waluty()

    for oczekiwany in ("Saldo", "Kto komu ile", f"+100,00 {w}", f"−100,00 {w}", "dostaje", "oddaje",
                       "Kto ile wydał w miesiącu", "Rozliczenia"):
        assert any(oczekiwany in n for n in napisy), oczekiwany
    assert not any("uczciwa część" in n or "Dopłacił" in n for n in napisy)
    assert przycisk_rozliczenia(widok) and not przycisk_rozliczenia(widok).disabled

    assert audyty.znajdz_expand_bez_ograniczenia(widok) == []
    assert audyty.znajdz_expand_w_kontenerze(widok) == []
    assert audyty.znajdz_pogrubienia_na_drugim_planie(widok) == []
    assert audyty.znajdz_plaskie_powierzchnie(widok, widok._strona_testowa.page) == []
    assert audyty.znajdz_rozciagliwe_chipy(widok) == []


def test_okno_rozliczone_zapisuje_zeruje_i_wysyla(wspolne, ekran):
    widok = ekran["zbuduj"](wspolne)
    przycisk_rozliczenia(widok).on_click(None)
    dlg = ekran["dialogi"][-1]
    podglad = teksty(dlg)
    assert {"Ola", "Kamil", f"100,00 {utils.symbol_waluty()}"} <= set(podglad)

    pola = {pole.label: pole for pole in kontrolki(dlg, ft.TextField)}
    e_data, e_notatka = pola["Data rozliczenia"], pola["Notatka (np. przelew, gotówka)"]
    zatwierdz = next(b for b in dlg.actions if isinstance(b, ft.FilledButton))

    e_data.value = (date.today() + timedelta(days=1)).strftime("%d.%m.%Y")
    zatwierdz.on_click(None)
    assert utils.blad_kontrolki(e_data) and db.pobierz_rozliczenia(wspolne) == []

    e_data.value = dzien(0)
    e_notatka.value = "Gotówka"
    zatwierdz.on_click(None)

    assert salda(wspolne) == {"Kamil": 0.0, "Ola": 0.0}
    assert db.pobierz_rozliczenia(wspolne)[0]["notatka"] == "Gotówka"
    assert ekran["wysylki"] == ["rozliczenie"]


def test_historia_cofa_tylko_ostatnie_rozliczenie(wspolne, ekran):
    db.zapisz_rozliczenie(wspolne, dzien(5))
    inny(wspolne, 1, 60.0, "Ola")
    ostatnie = db.zapisz_rozliczenie(wspolne)
    widok = ekran["zbuduj"](wspolne)

    cofnij = [b for b in kontrolki(widok, ft.IconButton) if b.tooltip == "Cofnij rozliczenie"]
    assert len(cofnij) == 1
    # Po rozliczeniu nie ma czego rozliczać — przycisk gaśnie.
    assert przycisk_rozliczenia(widok).disabled

    cofnij[0].on_click(None)

    tekst, wynik = ekran["cofnij"][-1]
    assert wynik and ostatnie not in [r["id"] for r in db.pobierz_rozliczenia(wspolne)]
    assert salda(wspolne) == {"Ola": 30.0, "Kamil": -30.0}


def test_podglad_widzi_saldo_ale_nie_rozlicza_ani_nie_cofa(baza, ekran):
    db.zapisz_moje_imie("Kamil")
    a = auto(rola=db.ROLA_PODGLAD)
    tankowanie(a, 10, 300.0, "Kamil")
    inny(a, 8, 100.0, "Ola")
    db.ustaw_role_pojazdu(a, db.ROLA_WLASCICIEL)
    db.zapisz_rozliczenie(a, dzien(9))
    db.ustaw_role_pojazdu(a, db.ROLA_PODGLAD)

    widok = ekran["zbuduj"](a)

    assert any("Kto komu ile" in n for n in teksty(widok))
    assert przycisk_rozliczenia(widok) is None
    assert [b for b in kontrolki(widok, ft.IconButton) if b.tooltip in ("Cofnij rozliczenie", "Usuń rozliczenie")] == []


def test_ekran_mowi_o_jednej_osobie_i_wpisach_bez_podpisu(ja, ekran):
    a = auto()
    tankowanie(a, 3, 120.0, "Kamil")
    inny(a, 2, 40.0, None)

    napisy = teksty(ekran["zbuduj"](a))

    assert any("jedna osoba" in n for n in napisy)
    assert any("1 wydatek bez podpisu" in n for n in napisy)
    assert any("od pierwszego podpisanego wpisu" in n for n in napisy)


def test_ekran_podzialu_da_sie_znalezc_po_saldzie():
    ekran = next(e for e in utils.EKRANY if e["id"] == "podzial")
    assert {"saldo", "rozliczone", "kto komu"} <= set(ekran["slowa"])
