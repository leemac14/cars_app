"""Koszt części z magazynu doliczany do serwisu.

Olej kupiony do magazynu nie liczył się dotąd nigdzie: zakup nie jest wydatkiem
w statystykach, a zużycie przy wymianie zostawiało koszt wpisu taki, jaki ktoś
wpisał — zwykle samą robociznę albo zero. Teraz koszt zużytych części trafia do
`historia.cena` i `wizyty.koszt_calkowity`, więc widzą go wszystkie statystyki.

Najłatwiej to zepsuć na EDYCJI: każdy kolejny zapis formularza nie może doliczać
części od nowa, późniejsza zmiana ceny w magazynie nie może przepisywać zamkniętej
wizyty, a duplikat nie może przenieść kosztu części, których nie przenosi. Dlatego
większość testów przechodzi przez prawdziwe formularze, a nie przez same funkcje
warstwy danych.
"""

import sqlite3

import flet as ft
import pytest

import audyty
import db
import pomoce
import probki_baz
import utils


DRABINKA = probki_baz.wczytaj_drabinke()


# ============================================================================
#  POMOCE
# ============================================================================

@pytest.fixture
def bez_nawigacji(monkeypatch):
    """Zapis formularza kończy się przejściem na inny ekran i snackbarem — bez
    okna nie ma dokąd przejść. Zapamiętujemy komunikaty, żeby dało się je sprawdzić."""
    komunikaty = []
    monkeypatch.setattr(utils, "przejdz", lambda page, trasa: None)
    monkeypatch.setattr(utils, "pokaz_komunikat", lambda page, tekst, *a, **k: komunikaty.append(tekst))
    return komunikaty


def pojazd_z_magazynem():
    """Pojazd z podzespołem i trzema pozycjami magazynu: olej z ceną za litr,
    filtr z ceną za sztukę i żarówki bez ceny."""
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO samochody (nazwa, typ_paliwa, status, rola_wspoldzielenia) VALUES (?,?,?,?)",
            ("Magazynowy", "Benzyna", db.STATUS_POJAZDU_AKTYWNY, db.ROLA_WLASCICIEL),
        )
        auto = c.lastrowid
        c.execute("INSERT INTO zadania (auto_id, nazwa, interwal_km) VALUES (?,?,?)", (auto, "Olej silnikowy i filtr", 15000))
        zadanie = c.lastrowid
        czesci = {}
        for klucz, nazwa, ilosc, jednostka, cena, cena_jedn in (
            ("olej", "Olej 5W-30", 5.0, "l", 150.0, 30.0),
            ("filtr", "Filtr oleju", 2.0, "szt", 80.0, 40.0),
            ("zarowka", "Żarówka H7", 3.0, "szt", None, None),
        ):
            c.execute(
                "INSERT INTO magazyn_czesci (auto_id, nazwa, kategoria, ilosc, jednostka, cena, cena_jednostkowa) "
                "VALUES (?,?,?,?,?,?,?)",
                (auto, nazwa, "Inne", ilosc, jednostka, cena, cena_jedn),
            )
            czesci[klucz] = c.lastrowid
    return {"auto_id": auto, "zadanie": zadanie, **czesci}


def wybierz(zuzycie, magazyn_id, ilosc):
    """Zaznacza pozycję w karcie magazynu tak, jak zrobiłby to palec."""
    zuzycie.c_uzyj.value = True
    for pozycja in zuzycie._pozycje:
        if pozycja["id"] == magazyn_id:
            pozycja["chk"].value = True
            pozycja["pole"].value = ilosc
            pozycja["pole"].visible = True
            return pozycja
    raise AssertionError(f"pozycji {magazyn_id} nie ma w karcie magazynu")


def wpisz_koszt(widok, kwota):
    """Koszt usługi jedną kwotą — tak jak przed podziałem na robociznę
    i części (ten sprawdza tests/test_robocizna_czesci.py). Tu chodzi
    wyłącznie o to, co dolicza magazyn."""
    widok.koszt.przelacz(False)
    widok.koszt.e_kwota.value = kwota


def odznacz(zuzycie, magazyn_id):
    for pozycja in zuzycie._pozycje:
        if pozycja["id"] == magazyn_id:
            pozycja["chk"].value = False


def jeden(sql, parametry=()):
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute(sql, parametry)
        wiersz = c.fetchone()
    return wiersz[0] if wiersz and len(wiersz) == 1 else wiersz


def stan_magazynu(magazyn_id):
    return jeden("SELECT ilosc FROM magazyn_czesci WHERE id=?", (magazyn_id,))


def koszty_zuzycia(tabela, kolumna, rekord_id):
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute(f"SELECT magazyn_id, ilosc_uzyta, koszt FROM {tabela} WHERE {kolumna}=? ORDER BY magazyn_id", (rekord_id,))
        return c.fetchall()


def teksty(korzen):
    """Wszystkie napisy z ZBUDOWANEGO drzewa kontrolek, razem z etykietami pól."""
    wynik, do_odwiedzenia = [], [korzen]
    while do_odwiedzenia:
        kontrolka = do_odwiedzenia.pop()
        for pole in ("value", "label"):
            wartosc = getattr(kontrolka, pole, None)
            if isinstance(wartosc, str) and wartosc.strip():
                wynik.append(wartosc)
        do_odwiedzenia.extend(dziecko for _, dziecko in audyty._dzieci(kontrolka))
        for pole in ("appbar", "floating_action_button"):
            dziecko = getattr(kontrolka, pole, None)
            if isinstance(dziecko, ft.Control):
                do_odwiedzenia.append(dziecko)
    return wynik


def zbuduj(klasa, stan, *argumenty):
    """Widok na stronie bez okna. Strona trzyma sesję przez weakref, więc musi
    żyć tak długo jak widok — inaczej page.update() w walidacji wywala się na
    „destroyed session”."""
    strona = pomoce.zbuduj_strone()
    widok = klasa(strona.page, stan, *argumenty)
    widok._strona_testowa = strona
    return widok


def formularz_wpisu(stan, dane, h_id=None):
    from views.formularze import FormularzWpisView
    return zbuduj(FormularzWpisView, stan, h_id, dane["zadanie"])


def formularz_wizyty(stan, w_id=None):
    from views.formularze import FormularzWizytyView
    return zbuduj(FormularzWizytyView, stan, w_id)


def nowy_wpis(dane, koszt="50", czesci=(("olej", "4"),)):
    """Zapisany przez formularz pojedynczy wpis; zwraca jego id."""
    stan = pomoce.stan_aplikacji(dane["auto_id"], "Magazynowy")
    widok = formularz_wpisu(stan, dane)
    widok.e_p.value = "120000"
    wpisz_koszt(widok, koszt)
    for klucz, ilosc in czesci:
        wybierz(widok.zuzycie, dane[klucz], ilosc)
    widok.zapisz(None)
    return jeden("SELECT MAX(id) FROM historia WHERE zadanie_id=?", (dane["zadanie"],))


# ============================================================================
#  MIGRACJA 41
# ============================================================================

def test_migracja_liczy_cene_jednostkowa_i_niczego_nie_dolicza_wstecz(magazyn):
    probki_baz.zbuduj_baze_w_wersji(db.BAZA_DANYCH, 40, DRABINKA)
    conn = sqlite3.connect(db.BAZA_DANYCH)
    c = conn.cursor()
    c.execute("INSERT INTO samochody (nazwa, typ_paliwa) VALUES ('Stary', 'Benzyna')")
    auto = c.lastrowid
    c.execute("INSERT INTO zadania (auto_id, nazwa) VALUES (?, 'Olej')", (auto,))
    zadanie = c.lastrowid
    c.execute("INSERT INTO historia (zadanie_id, data, przebieg, cena) VALUES (?, '14.09.2026', 135830, 0.0)", (zadanie,))
    wpis = c.lastrowid
    c.execute("INSERT INTO wizyty (auto_id, data, przebieg, koszt_calkowity) VALUES (?, '01.09.2026', 135000, 500.0)", (auto,))
    wizyta = c.lastrowid

    def pozycja(nazwa, ilosc, cena):
        c.execute("INSERT INTO magazyn_czesci (auto_id, nazwa, ilosc, jednostka, cena) VALUES (?,?,?,?,?)",
                  (auto, nazwa, ilosc, "szt", cena))
        return c.lastrowid

    # 5 l za 150 zł: 1 l zeszedł przy wpisie, 1 l przy wizycie, 3 l leżą na półce.
    olej = pozycja("Olej", 3.0, 150.0)
    c.execute("INSERT INTO historia_czesci_magazynu (historia_id, magazyn_id, ilosc_uzyta) VALUES (?,?,1)", (wpis, olej))
    c.execute("INSERT INTO wizyta_czesci_magazynu (wizyta_id, magazyn_id, ilosc_uzyta) VALUES (?,?,1)", (wizyta, olej))
    # Butelka zużyta do zera — stan 0, sam stan dałby dzielenie przez zero.
    butelka = pozycja("Olej 5W-30", 0.0, 200.0)
    c.execute("INSERT INTO historia_czesci_magazynu (historia_id, magazyn_id, ilosc_uzyta) VALUES (?,?,1)", (wpis, butelka))
    pozycja("Żarówka", 2.0, None)
    pozycja("Pusta", 0.0, 50.0)
    conn.commit()
    conn.close()

    db.init_db()

    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT nazwa, cena_jednostkowa FROM magazyn_czesci")
        assert dict(c.fetchall()) == {"Olej": 30.0, "Olej 5W-30": 200.0, "Żarówka": None, "Pusta": None}

        c.execute("SELECT cena FROM historia WHERE id=?", (wpis,))
        assert c.fetchone()[0] == 0.0, "wpis zapisany przed zmianą nie może dostać kosztu wstecz"
        c.execute("SELECT koszt_calkowity FROM wizyty WHERE id=?", (wizyta,))
        assert c.fetchone()[0] == 500.0
        c.execute("SELECT koszt FROM historia_czesci_magazynu UNION ALL SELECT koszt FROM wizyta_czesci_magazynu")
        assert {k for (k,) in c.fetchall()} == {None}, "dotychczasowe zużycia zostają „nie doliczone”"


# ============================================================================
#  WYCENA
# ============================================================================

def test_wycena_bierze_cene_zapamietana_przy_rekordzie_a_nowe_pozycje_biezaca():
    ceny = {1: 30.0, 2: 40.0, 3: None, 4: 0.045}
    poprzednie = {1: {"ilosc": 4.0, "koszt": 100.0}, 2: {"ilosc": 1.0, "koszt": None}}

    wycenione = db.wycen_zuzycie([(1, 2), (2, 1), (3, 5), (4, 1000), (5, 0)], ceny, poprzednie)

    assert wycenione == [
        (1, 2.0, 50.0),     # 100 zł za 4 l zapamiętane przy rekordzie — nie dzisiejsze 30 zł/l
        (2, 1.0, 40.0),     # zużycie bez kosztu wycenia się po cenie bieżącej
        (3, 5.0, None),     # bez ceny nic nie dolicza
        (4, 1000.0, 45.0),  # groszowa cena za mililitr nie gubi się w zaokrągleniu
    ]
    assert db.suma_kosztu_zuzycia(wycenione) == 135.0
    assert db.koszt_doliczony(poprzednie) == 100.0


def test_cena_jednostkowa_z_zakupu_i_srednia_po_scaleniu():
    assert db.cena_jednostkowa_z_zakupu(150, 5) == 30.0
    assert db.cena_jednostkowa_z_zakupu("45,20 zł", "2") == 22.6
    assert db.cena_jednostkowa_z_zakupu(10, 0) is None, "zero sztuk to nie „za darmo”"
    assert db.cena_jednostkowa_z_zakupu(None, 5) is None

    assert db.srednia_cena_jednostkowa([(2, 30.0), (3, 40.0)]) == 36.0
    assert db.srednia_cena_jednostkowa([(2, 30.0), (3, None)]) == 30.0, "pozycja bez ceny nie zaniża średniej"
    assert db.srednia_cena_jednostkowa([(0, 25.0), (0, 40.0)]) == 25.0
    assert db.srednia_cena_jednostkowa([(1, None)]) is None


def test_teksty_ilosci_ceny_i_pola():
    assert utils.tekst_ilosci(1.0) == "1"
    assert utils.tekst_ilosci(2.5) == "2,5"
    assert utils.tekst_ceny(30) == "30,00"
    assert utils.tekst_ceny(0.045) == "0,045"
    assert utils.tekst_ceny(0.5) == "0,50"
    assert utils.liczba_do_pola(None) == ""
    assert utils.liczba_do_pola(37.5) == "37,5"
    assert utils.koszt_bez_czesci_do_pola(170.0, 120.0) == "50"
    assert utils.koszt_bez_czesci_do_pola(0.0, 0.0) == "", "zero zostaje pustym polem, tak jak dotąd"
    assert utils.koszt_bez_czesci_do_pola(100.0, 120.0) == "", "rozjechane dane nie dają ujemnego kosztu"


# ============================================================================
#  POJEDYNCZY WPIS SERWISOWY
# ============================================================================

def test_zuzycie_dolicza_koszt_do_nowego_wpisu(baza, bez_nawigacji):
    dane = pojazd_z_magazynem()

    h_id = nowy_wpis(dane, koszt="50", czesci=(("olej", "4"),))

    assert jeden("SELECT cena FROM historia WHERE id=?", (h_id,)) == 170.0
    assert koszty_zuzycia("historia_czesci_magazynu", "historia_id", h_id) == [(dane["olej"], 4.0, 120.0)]
    assert stan_magazynu(dane["olej"]) == 1.0
    assert any("120,00" in k for k in bez_nawigacji), "komunikat po zapisie mówi, ile doliczono"


def test_edycja_nie_dolicza_czesci_drugi_raz_i_trzyma_dawna_cene(baza, bez_nawigacji):
    dane = pojazd_z_magazynem()
    h_id = nowy_wpis(dane, koszt="50", czesci=(("olej", "4"),))
    stan = pomoce.stan_aplikacji(dane["auto_id"], "Magazynowy")

    # Olej zdrożał, zanim ktoś wrócił poprawić wpis.
    with db.polacz_baze() as conn:
        conn.execute("UPDATE magazyn_czesci SET cena_jednostkowa=40 WHERE id=?", (dane["olej"],))

    widok = formularz_wpisu(stan, dane, h_id)
    assert widok.koszt.e_kwota.value == "50", "w polu kosztu stoi sama usługa, bez części z magazynu"
    assert widok.zuzycie.c_uzyj.value is True
    assert "120,00" in widok.koszt.podsumowanie.value and "170,00" in widok.koszt.podsumowanie.value
    widok.zapisz(None)

    assert jeden("SELECT cena FROM historia WHERE id=?", (h_id,)) == 170.0
    assert koszty_zuzycia("historia_czesci_magazynu", "historia_id", h_id) == [(dane["olej"], 4.0, 120.0)]
    assert stan_magazynu(dane["olej"]) == 1.0

    # Mniej oleju: koszt po cenie zapamiętanej przy wpisie, różnica wraca na półkę.
    widok = formularz_wpisu(stan, dane, h_id)
    wybierz(widok.zuzycie, dane["olej"], "2")
    widok.zapisz(None)
    assert jeden("SELECT cena FROM historia WHERE id=?", (h_id,)) == 110.0
    assert stan_magazynu(dane["olej"]) == 3.0

    # Nowa pozycja w tym samym wpisie bierze cenę bieżącą; bez ceny nic nie dolicza.
    widok = formularz_wpisu(stan, dane, h_id)
    wybierz(widok.zuzycie, dane["filtr"], "1")
    wybierz(widok.zuzycie, dane["zarowka"], "2")
    widok.zuzycie.przelicz()
    assert "bez ceny" in widok.zuzycie.podsumowanie.value
    widok.zapisz(None)
    assert jeden("SELECT cena FROM historia WHERE id=?", (h_id,)) == 150.0
    assert koszty_zuzycia("historia_czesci_magazynu", "historia_id", h_id) == [
        (dane["olej"], 2.0, 60.0), (dane["filtr"], 1.0, 40.0), (dane["zarowka"], 2.0, None),
    ]

    # Rezygnacja z magazynu: zostaje sama usługa, wszystko wraca na stan.
    widok = formularz_wpisu(stan, dane, h_id)
    widok.zuzycie.c_uzyj.value = False
    widok.zapisz(None)
    assert jeden("SELECT cena FROM historia WHERE id=?", (h_id,)) == 50.0
    assert koszty_zuzycia("historia_czesci_magazynu", "historia_id", h_id) == []
    assert [stan_magazynu(dane[k]) for k in ("olej", "filtr", "zarowka")] == [5.0, 2.0, 3.0]


def test_zbyt_duza_ilosc_blokuje_zapis(baza, bez_nawigacji):
    dane = pojazd_z_magazynem()
    stan = pomoce.stan_aplikacji(dane["auto_id"], "Magazynowy")
    widok = formularz_wpisu(stan, dane)
    widok.e_p.value = "120000"
    pozycja = wybierz(widok.zuzycie, dane["olej"], "6")

    widok.zapisz(None)

    assert jeden("SELECT COUNT(*) FROM historia") == 0
    assert utils.blad_kontrolki(pozycja["pole"]) == "Maks. 5"
    assert stan_magazynu(dane["olej"]) == 5.0


def test_duplikat_wpisu_nie_przenosi_kosztu_czesci(baza, bez_nawigacji):
    dane = pojazd_z_magazynem()
    h_id = nowy_wpis(dane, koszt="50", czesci=(("olej", "4"),))
    stan = pomoce.stan_aplikacji(dane["auto_id"], "Magazynowy")
    stan.duplikuj_zrodlo_wpis = h_id

    widok = formularz_wpisu(stan, dane)

    assert widok.koszt.e_kwota.value == "50", "duplikat nie niesie części, więc nie może nieść ich kosztu"
    assert widok.zuzycie.c_uzyj.value is False


def test_stare_zuzycie_bez_kosztu_dolicza_sie_dopiero_przy_edycji(baza, bez_nawigacji):
    dane = pojazd_z_magazynem()
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO historia (zadanie_id, data, przebieg, cena) VALUES (?, '14.09.2026', 120000, 0)", (dane["zadanie"],))
        h_id = c.lastrowid
        c.execute("INSERT INTO historia_czesci_magazynu (historia_id, magazyn_id, ilosc_uzyta) VALUES (?,?,1)", (h_id, dane["olej"]))
        c.execute("UPDATE magazyn_czesci SET ilosc=4 WHERE id=?", (dane["olej"],))
    stan = pomoce.stan_aplikacji(dane["auto_id"], "Magazynowy")

    widok = formularz_wpisu(stan, dane, h_id)
    assert widok.koszt.migawka() == ("podział", 0.0, 0.0), "poza magazynem nie ma czego dzielić"
    widok.zapisz(None)

    assert jeden("SELECT cena FROM historia WHERE id=?", (h_id,)) == 30.0
    assert koszty_zuzycia("historia_czesci_magazynu", "historia_id", h_id) == [(dane["olej"], 1.0, 30.0)]
    assert stan_magazynu(dane["olej"]) == 4.0


def test_usuniecie_wpisu_i_cofniecie_zachowuja_koszt_zuzycia(baza, bez_nawigacji):
    dane = pojazd_z_magazynem()
    h_id = nowy_wpis(dane, koszt="50", czesci=(("olej", "4"),))

    wynik = db.usun_z_cofnieciem("historia", h_id)
    assert stan_magazynu(dane["olej"]) == 5.0
    wynik["cofnij"]()

    nowe_id = jeden("SELECT MAX(id) FROM historia WHERE zadanie_id=?", (dane["zadanie"],))
    assert jeden("SELECT cena FROM historia WHERE id=?", (nowe_id,)) == 170.0
    assert koszty_zuzycia("historia_czesci_magazynu", "historia_id", nowe_id) == [(dane["olej"], 4.0, 120.0)]
    assert stan_magazynu(dane["olej"]) == 1.0


# ============================================================================
#  WIZYTA ZBIORCZA
# ============================================================================

def test_wizyta_dolicza_czesci_a_duplikat_i_usuniecie_ich_nie_gubia(baza, bez_nawigacji):
    dane = pojazd_z_magazynem()
    stan = pomoce.stan_aplikacji(dane["auto_id"], "Magazynowy")

    widok = formularz_wizyty(stan)
    widok.e_p.value = "120100"
    wpisz_koszt(widok, "300")
    next(chk for chk in widok.chk_czesci if chk.data == dane["zadanie"]).value = True
    wybierz(widok.zuzycie, dane["olej"], "2")
    widok.zapisz(None)

    w_id = jeden("SELECT MAX(id) FROM wizyty")
    assert jeden("SELECT koszt_calkowity FROM wizyty WHERE id=?", (w_id,)) == 360.0
    assert koszty_zuzycia("wizyta_czesci_magazynu", "wizyta_id", w_id) == [(dane["olej"], 2.0, 60.0)]
    assert stan_magazynu(dane["olej"]) == 3.0

    # Zapis bez zmian nie dolicza drugi raz.
    widok = formularz_wizyty(stan, w_id)
    assert widok.koszt.e_kwota.value == "300"
    widok.zapisz(None)
    assert jeden("SELECT koszt_calkowity FROM wizyty WHERE id=?", (w_id,)) == 360.0
    assert stan_magazynu(dane["olej"]) == 3.0

    stan.duplikuj_zrodlo_wizyta = w_id
    assert formularz_wizyty(stan).koszt.e_kwota.value == "300"

    wynik = db.usun_wizyty_z_cofnieciem([w_id])
    assert stan_magazynu(dane["olej"]) == 5.0
    wynik["cofnij"]()
    assert jeden("SELECT koszt_calkowity FROM wizyty WHERE id=?", (w_id,)) == 360.0
    assert koszty_zuzycia("wizyta_czesci_magazynu", "wizyta_id", w_id) == [(dane["olej"], 2.0, 60.0)]
    assert stan_magazynu(dane["olej"]) == 3.0


# ============================================================================
#  MAGAZYN: WARTOŚĆ, HISTORIA ZUŻYCIA, OSTRZEŻENIE, FORMULARZ POZYCJI
# ============================================================================

def test_wartosc_podsumowanie_i_historia_zuzycia(baza, bez_nawigacji):
    dane = pojazd_z_magazynem()
    h_id = nowy_wpis(dane, koszt="50", czesci=(("olej", "4"), ("zarowka", "1")))

    assert db.pobierz_wartosc_magazynu(dane["auto_id"]) == {"wartosc": 110.0, "na_stanie": 3, "bez_ceny": 1}

    podsumowanie = db.pobierz_podsumowanie_zuzycia(dane["auto_id"])
    assert podsumowanie[dane["olej"]]["liczba"] == 1
    assert podsumowanie[dane["olej"]]["koszt"] == 120.0
    assert podsumowanie[dane["zarowka"]]["koszt"] == 0.0
    assert dane["filtr"] not in podsumowanie

    historia = db.pobierz_historie_zuzycia(dane["olej"])
    assert len(historia) == 1
    assert historia[0]["trasa"] == f"/wpis/edytuj/{h_id}"
    assert (historia[0]["ilosc"], historia[0]["koszt"], historia[0]["tytul"]) == (4.0, 120.0, "Olej silnikowy i filtr")


def test_ekran_magazynu_pokazuje_wartosc_i_zuzycie_i_przechodzi_audyty(baza, bez_nawigacji, monkeypatch):
    from views.garage_view import MagazynView

    dane = pojazd_z_magazynem()
    nowy_wpis(dane, koszt="50", czesci=(("olej", "4"),))
    stan = pomoce.stan_aplikacji(dane["auto_id"], "Magazynowy")
    stan.magazyn_zakladka = 1
    widok = zbuduj(MagazynView, stan)
    strona = widok._strona_testowa
    napisy = teksty(widok)

    assert "Wartość magazynu" in napisy, "treść podzakładki się nie zbudowała (wyjątek połknięty pod szkieletem)"
    assert any(n.startswith("30,00 PLN/l · wartość 30,00 PLN") for n in napisy)
    assert any(n.startswith("Użyto 1×, razem 4 l · doliczono 120,00 PLN") for n in napisy)
    assert audyty.znajdz_expand_bez_ograniczenia(widok) == []
    assert audyty.znajdz_rozciagliwe_chipy(widok) == []
    assert audyty.znajdz_plaskie_powierzchnie(widok, strona.page) == []
    assert audyty.znajdz_pogrubienia_na_drugim_planie(widok) == []

    ostrzezenie = widok._ostrzezenie_o_zuzyciu([dane["olej"]])
    assert "1 raz" in ostrzezenie and "120,00 PLN" in ostrzezenie
    assert widok._ostrzezenie_o_zuzyciu([dane["filtr"]]) == ""

    otwarte = []
    monkeypatch.setattr(utils, "otworz_dno", lambda page, arkusz: otwarte.append(arkusz))
    widok._pokaz_historie_zuzycia(dane["olej"], "Olej 5W-30", "l")
    napisy_arkusza = teksty(otwarte[0])
    assert "Olej silnikowy i filtr" in napisy_arkusza
    assert "120,00 PLN" in napisy_arkusza
    assert audyty.znajdz_pogrubienia_na_drugim_planie(otwarte[0]) == []


def test_karty_wpisow_i_wizyt_mowia_ile_przyszlo_z_magazynu(baza, bez_nawigacji):
    from views.history_view import HistoriaView, WizytyZbiorczeView

    dane = pojazd_z_magazynem()
    nowy_wpis(dane, koszt="50", czesci=(("olej", "4"),))
    stan = pomoce.stan_aplikacji(dane["auto_id"], "Magazynowy")

    widok = formularz_wizyty(stan)
    widok.e_p.value = "120100"
    wpisz_koszt(widok, "300")
    next(chk for chk in widok.chk_czesci if chk.data == dane["zadanie"]).value = True
    wybierz(widok.zuzycie, dane["filtr"], "1")
    widok.zapisz(None)

    napisy_historii = teksty(zbuduj(HistoriaView, stan, dane["zadanie"]))
    assert "Z magazynu: Olej 5W-30 (4 l) · w tym 120,00 PLN" in napisy_historii

    napisy_wizyt = teksty(zbuduj(WizytyZbiorczeView, stan))
    assert "Z magazynu: Filtr oleju (1 szt) · w tym 40,00 PLN" in napisy_wizyt


def test_formularz_pozycji_przelicza_koszt_zakupu_i_cene_za_jednostke(baza, bez_nawigacji):
    from views.garage_view import FormularzCzesciView

    dane = pojazd_z_magazynem()
    stan = pomoce.stan_aplikacji(dane["auto_id"], "Magazynowy")

    widok = zbuduj(FormularzCzesciView, stan)
    widok.e_ilosc.value = "5"
    widok.e_cena.value = "150"
    widok._przelicz_ceny("zakup")
    assert widok.e_cena_jedn.value == "30"

    widok.e_ilosc.value = "4"
    widok._przelicz_ceny("ilosc")
    assert widok.e_cena_jedn.value == "37,5", "pole wyliczane idzie za ilością"

    widok.e_cena_jedn.value = "40"
    widok._przelicz_ceny("jedn")
    widok.e_ilosc.value = "5"
    widok._przelicz_ceny("ilosc")
    assert (widok.e_cena.value, widok.e_cena_jedn.value) == ("150", "40"), "ręcznie wpisanych pól nic nie nadpisuje"

    widok.e_jedn.value = "l"
    widok._zmien_jednostke()
    assert widok.e_cena_jedn.label.startswith("Cena za 1 l")

    widok.e_nazwa.value = "Olej przekładniowy"
    widok.zapisz(None)
    assert jeden("SELECT cena, cena_jednostkowa, ilosc FROM magazyn_czesci WHERE nazwa='Olej przekładniowy'") == (150.0, 40.0, 5.0)

    # Puste pole ceny za jednostkę przy znanym koszcie zakupu liczy się przy zapisie.
    widok = zbuduj(FormularzCzesciView, stan)
    widok.e_nazwa.value = "Płyn do spryskiwaczy"
    widok.e_ilosc.value = "4"
    widok.e_cena.value = "100"
    widok.zapisz(None)
    assert jeden("SELECT cena_jednostkowa FROM magazyn_czesci WHERE nazwa='Płyn do spryskiwaczy'") == 25.0

    # Edycja pokazuje zapisane wartości i nie traktuje ich jak wyliczanych.
    czesc_id = jeden("SELECT id FROM magazyn_czesci WHERE nazwa='Olej przekładniowy'")
    widok = zbuduj(FormularzCzesciView, stan, czesc_id)
    assert (widok.e_cena.value, widok.e_cena_jedn.value) == ("150", "40")
    widok.e_ilosc.value = "9"
    widok._przelicz_ceny("ilosc")
    assert (widok.e_cena.value, widok.e_cena_jedn.value) == ("150", "40")


def test_scalanie_duplikatow_usrednia_cene_za_jednostke(baza):
    dane = pojazd_z_magazynem()
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO magazyn_czesci (auto_id, nazwa, ilosc, jednostka, cena_jednostkowa) VALUES (?,?,?,?,?)",
            (dane["auto_id"], "olej 5w-30 ", 3.0, "l", 40.0),
        )
        duplikat = c.lastrowid
        c.execute("UPDATE magazyn_czesci SET ilosc=2 WHERE id=?", (dane["olej"],))

    assert db.scal_duplikaty_nazw(dane["auto_id"], "magazyn_czesci", dane["olej"], [duplikat]) == 1

    assert jeden("SELECT ilosc, cena_jednostkowa FROM magazyn_czesci WHERE id=?", (dane["olej"],)) == (5.0, 36.0)
