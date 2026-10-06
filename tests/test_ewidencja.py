"""Ewidencja przebiegu i podział prywatne / służbowe (N-01).

Aplikacja znała stan licznika, ale nie wiedziała, PO CO były kilometry. Teraz
przejazd (data, skąd, dokąd, cel, km, rodzaj, kierowca, opcjonalnie licznik)
siedzi w tabeli `przejazdy`, a db/ewidencja.py liczy z niego miesiąc. Sprawdzamy:

1. rachunek — zapis, kilometry i udział, podział kosztów, kilometrówka, licznik
   na granicach okresu i nieopisane km, zamknięcie miesiąca, podpowiedzi;
2. przejazd z licznikiem jako źródło historii licznika;
3. raport miesiąca w trzech układach — treść, PDF i CSV;
4. przypomnienie w dzwonku i kafelek kokpitu;
5. formularz przejazdu (szablon, kalkulator, powtórz, powrót, licznik);
6. ekran ewidencji, router i role;
7. wyszukiwarka, eksport i import CSV;
8. migracja 50, chmura (przejazdy i `dopisane` w trasach) i usuwanie.
"""

import sqlite3
from datetime import date, datetime, timedelta

import flet as ft
import pytest

import db
import pomoce
import probki_baz
import sync
import utils
from sync import konflikty as sync_konflikty
from sync import pobieranie as sync_pobieranie
from sync import wysylanie as sync_wysylanie

DRABINKA = probki_baz.wczytaj_drabinke()
KONFIG_PRZEJAZDOW = next(k for k in sync.KONFIGURACJA_SYNC if k["tabela"] == "przejazdy")
KONFIG_TRAS = next(k for k in sync.KONFIGURACJA_SYNC if k["tabela"] == "trasy_szablony")
POLA_DZIECI = ("controls", "content", "items", "actions", "leading", "trailing", "title", "subtitle",
               "floating_action_button")

# Zamknięty, miniony miesiąc — nie zależy od dnia, w którym biegną testy.
ROK, MIESIAC = 2026, 3
PO_MIESIACU = date(2026, 4, 3)


# ============================================================================
#  POMOCNIKI
# ============================================================================

def auto(nazwa="Octavia", **pola):
    kolumny = {"nazwa": nazwa, "typ_paliwa": "Diesel", "status": db.STATUS_POJAZDU_AKTYWNY,
               "rola_wspoldzielenia": db.ROLA_WLASCICIEL, "nr_rej": "WX 12345", "pojemnosc_silnika": "1598",
               "marka": "Skoda", "model": "Octavia"}
    kolumny.update(pola)
    with db.polacz_baze() as conn:
        kursor = conn.execute(
            f"INSERT INTO samochody ({', '.join(kolumny)}) VALUES ({', '.join('?' for _ in kolumny)})",
            list(kolumny.values()))
        return kursor.lastrowid


def przejazd(auto_id, data, km, skad="Warszawa", dokad="Łódź", cel="Spotkanie z klientem", sluzbowy=True,
             powrot=False, kierowca="Kamil Wroczyński", licznik=None):
    """`km` to dystans w jedną stronę — jak w formularzu."""
    return db.zapisz_przejazd(auto_id, {
        "data": data, "skad": skad, "dokad": dokad, "cel": cel, "km": db.km_przejazdu(km, powrot),
        "powrot": powrot, "sluzbowy": sluzbowy, "kierowca": kierowca, "licznik": licznik,
    })


def marzec(auto_id):
    """Miesiąc z trzema służbowymi i jednym prywatnym przejazdem (977,5 km),
    odczytem licznika z końca lutego i stanem licznika po ostatnim przejeździe."""
    db.dodaj_odczyt_przebiegu(auto_id, 120100, "28.02.2026")
    ids = [
        przejazd(auto_id, "02.03.2026", 135, powrot=True, cel="Spotkanie z klientem ABC"),
        przejazd(auto_id, "05.03.2026", 105, dokad="Radom", cel="Serwis u klienta"),
        przejazd(auto_id, "07.03.2026", 12.5, dokad="Sklep", cel="Zakupy", sluzbowy=False, kierowca="Ola"),
        przejazd(auto_id, "20.03.2026", 295, dokad="Kraków", cel="Targi", powrot=True, licznik=121078),
    ]
    return ids


def jeden(zapytanie, *parametry):
    with db.polacz_baze() as conn:
        return conn.execute(zapytanie, parametry).fetchone()


def _wszystkie(korzen, typ):
    znalezione = []

    def zejdz(k):
        if isinstance(k, typ):
            znalezione.append(k)
        for pole in POLA_DZIECI:
            wartosc = getattr(k, pole, None)
            if isinstance(wartosc, (list, tuple)):
                for dziecko in wartosc:
                    if isinstance(dziecko, ft.Control):
                        zejdz(dziecko)
            elif isinstance(wartosc, ft.Control):
                zejdz(wartosc)

    zejdz(korzen)
    return znalezione


def teksty(kontrolka):
    return [t.value for t in _wszystkie(kontrolka, ft.Text) if isinstance(t.value, str)]


def widok(nazwa, auto_id, identyfikatory=None, stan=None, **argumenty):
    stan = stan or pomoce.stan_aplikacji(auto_id, "Octavia")
    klasa = pomoce.klasy_widokow()[nazwa]
    strona = pomoce.zbuduj_strone()
    if argumenty:
        ekran = klasa(strona.page, stan, **argumenty)
    else:
        ekran = pomoce.zbuduj_widok(klasa, strona, stan, identyfikatory)
    # Strona trzyma sesję; bez niej `page.update()` w oknie rzuca „destroyed session”.
    ekran._strona_testowa = strona
    return ekran


@pytest.fixture
def zapis_formularza(monkeypatch):
    """Zapis bez nawigacji, okienek i sieci; zbiera komunikaty i trasy."""
    zdarzenia = {"komunikaty": [], "trasy": []}
    monkeypatch.setattr(utils, "przejdz", lambda strona, trasa: zdarzenia["trasy"].append(trasa))
    monkeypatch.setattr(utils, "pokaz_komunikat", lambda strona, tekst, *a, **k: zdarzenia["komunikaty"].append(tekst))
    monkeypatch.setattr(utils, "wypchnij_w_tle", lambda strona, auto_id, powod="zapis": None)
    monkeypatch.setattr(utils, "pokaz_bledy_formularza",
                        lambda strona, bledy: zdarzenia["komunikaty"].extend(k for _, k in bledy))
    return zdarzenia


# ============================================================================
#  1. RACHUNEK
# ============================================================================

def test_zapis_przejazdu_z_autorem_i_data_iso(baza):
    a = auto()
    db.zapisz_moje_imie("Kamil")
    p_id = przejazd(a, "02.03.2026", 135, powrot=True)

    p = db.pobierz_przejazd(p_id)
    assert (p["km"], p["km_jednej_strony"], p["powrot"], p["sluzbowy"]) == (270.0, 135.0, True, True)
    assert p["trasa"] == "Warszawa – Łódź – Warszawa" and p["rodzaj"] == db.RODZAJ_SLUZBOWY
    assert jeden("SELECT data_iso, dodane_przez FROM przejazdy WHERE id=?", p_id) == ("2026-03-02", "Kamil")

    # Poprawka nie zmienia autora — współautor rozpoznaje swoje przejazdy po podpisie.
    db.zapisz_moje_imie("Ola")
    assert db.zapisz_przejazd(a, {**p, "km": 100, "powrot": False}, p_id) == p_id
    assert jeden("SELECT km, powrot, dodane_przez FROM przejazdy WHERE id=?", p_id) == (100.0, 0, "Kamil")
    # Przejazd innego pojazdu nie daje się poprawić cudzym id.
    assert db.zapisz_przejazd(auto("Inne"), {**p, "km": 1}, p_id) is None


@pytest.mark.parametrize("dane, powod", [
    ({"data": "", "km": 10, "cel": "x"}, "Podaj datę przejazdu"),
    ({"data": "02.03.2026", "km": 0, "cel": "x"}, "Podaj liczbę kilometrów większą od zera"),
    ({"data": "02.03.2026", "km": 10}, "Podaj trasę albo cel przejazdu"),
    ({"data": "02.03.2026", "km": 10, "dokad": "Łódź", "licznik": "abc"}, "Stan licznika to liczba całkowita"),
    ({"data": "02.03.2026", "km": 10, "skad": "Dom"}, None),
])
def test_blad_przejazdu(dane, powod):
    assert db.blad_przejazdu(dane) == powod


def test_miesiac_liczy_kilometry_udzial_i_rok(baza):
    a = auto()
    marzec(a)
    przejazd(a, "10.02.2026", 50, sluzbowy=False)   # luty — inny miesiąc, ale ten sam rok
    przejazd(a, "01.04.2026", 30)                   # kwiecień — poza okresem

    p = db.podsumowanie_ewidencji(a, ROK, MIESIAC, dzis=PO_MIESIACU)

    assert (p["liczba"], p["liczba_sluzbowych"], p["liczba_prywatnych"]) == (4, 3, 1)
    assert (p["km"], p["km_sluzbowe"], p["km_prywatne"]) == (977.5, 965.0, 12.5)
    assert p["udzial_sluzbowy"] == pytest.approx(965 / 977.5)
    assert [d for d, _ in p["kierowcy"]] == ["Kamil Wroczyński", "Ola"]
    assert (p["rok_do_dzis"]["km"], p["rok_do_dzis"]["km_sluzbowe"]) == (1027.5, 965.0)
    assert (p["zakonczony"], p["w_toku"]) == (True, False)


def test_koszty_miesiaca_dzielone_w_proporcji_kilometrow(baza):
    a = auto()
    przejazd(a, "02.03.2026", 300)
    przejazd(a, "03.03.2026", 100, sluzbowy=False)
    with db.polacz_baze() as conn:
        conn.execute("INSERT INTO tankowania (auto_id, data, data_iso, przebieg, litry, kwota, do_pelna) "
                     "VALUES (?, '04.03.2026', '2026-03-04', 120000, 40, 300, 1)", (a,))
        conn.execute("INSERT INTO inne_koszty (auto_id, data, data_iso, kategoria, nazwa, kwota) "
                     "VALUES (?, '05.03.2026', '2026-03-05', 'Inne', 'Myjnia', 100)", (a,))

    p = db.podsumowanie_ewidencji(a, ROK, MIESIAC, dzis=PO_MIESIACU)

    assert p["koszty"]["razem"] == 400.0
    assert (p["koszty_sluzbowe"], p["koszty_prywatne"]) == (300.0, 100.0)
    # Bez przejazdów nie ma proporcji — nie ma też podziału.
    assert db.podsumowanie_ewidencji(a, 2026, 1, dzis=PO_MIESIACU)["koszty_sluzbowe"] is None


def test_kilometrowka_stawka_z_ustawien_albo_z_pojemnosci(baza):
    a = auto()
    marzec(a)
    p = db.podsumowanie_ewidencji(a, ROK, MIESIAC, dzis=PO_MIESIACU)
    assert p["kilometrowka"]["stawka"] is None, "przy podziale kosztów bez wpisanej stawki nie ma kwoty"

    db.zapisz_ustawienia_ewidencji(a, "kilometrowka")
    p = db.podsumowanie_ewidencji(a, ROK, MIESIAC, dzis=PO_MIESIACU)
    assert p["kilometrowka"]["stawka"] == 1.15, "powyżej 900 cm³"
    assert p["kilometrowka"]["kwota"] == round(965 * 1.15, 2)

    maly = auto("Maluch", pojemnosc_silnika="0,65 l")
    db.zapisz_ustawienia_ewidencji(maly, "kilometrowka")
    assert db.stawka_kilometrowki(maly) == 0.89
    assert db.domyslna_stawka_kilometrowki(auto("Elektryk", pojemnosc_silnika=None)) is None

    db.zapisz_ustawienia_ewidencji(a, "kilometrowka", 0.8)
    assert db.pobierz_ustawienia_ewidencji(a) == {"tryb": "kilometrowka", "stawka": 0.8}
    assert db.podsumowanie_ewidencji(a, ROK, MIESIAC, dzis=PO_MIESIACU)["kilometrowka"]["kwota"] == 772.0
    assert db.stawka_ponad_limit(a, 1.5) == 1.15 and db.stawka_ponad_limit(maly, 1.0) == 0.89
    assert db.stawka_ponad_limit(a, 1.15) is None


def test_ustawienia_ewidencji_odporne_na_smieci(baza):
    a = auto()
    db.zapisz_ustawienie(db.ustawienia._klucz_ewidencji(a), "tryb=xyz;stawka=abc;cos")
    assert db.pobierz_ustawienia_ewidencji(a) == {"tryb": db.TRYB_EWIDENCJI_DOMYSLNY, "stawka": None}
    db.zapisz_dane_osoby_ewidencji("  Kamil   Wroczyński ", "ul. Długa 5", "")
    assert db.pobierz_dane_osoby_ewidencji() == {"osoba": "Kamil Wroczyński", "adres": "ul. Długa 5",
                                                  "pracodawca": ""}


def test_kwota_kilometrowki_to_suma_kwot_wierszy(baza):
    a = auto()
    db.zapisz_ustawienia_ewidencji(a, "kilometrowka", 1.15)
    for km in (12.5, 12.5, 12.5):     # 14,375 zł każdy — zaokrąglenie wiersza, nie sumy
        przejazd(a, "02.03.2026", km)
    p = db.podsumowanie_ewidencji(a, ROK, MIESIAC, dzis=PO_MIESIACU)
    assert db.kwota_kilometrowki(12.5, 1.15) == 14.38
    assert p["kilometrowka"]["kwota"] == 43.14

    r = db.dane_raportu_ewidencji(a, ROK, MIESIAC, "kilometrowka", dzis=PO_MIESIACU)
    assert [w[-1] for w in r["wiersze"]] == ["14,38"] * 3 and r["razem"][-1] == "43,14"


def test_licznik_na_granicach_okresu_i_nieopisane_km(baza):
    a = auto()
    marzec(a)
    db.dodaj_odczyt_przebiegu(a, 121300, "31.03.2026")

    licznik = db.podsumowanie_ewidencji(a, ROK, MIESIAC, dzis=PO_MIESIACU)["licznik"]

    assert (licznik["start"], licznik["data_start"], licznik["start_przed"]) == (120100, date(2026, 2, 28), True)
    assert (licznik["koniec"], licznik["data_koniec"], licznik["koniec_na_ostatni_dzien"]) == \
        (121300, date(2026, 3, 31), True)
    assert (licznik["km"], licznik["opisane_km"], licznik["nieopisane_km"]) == (1200, 977.5, 222.5)


def test_okno_licznika_bierze_przejazdy_po_odczycie_poczatkowym(baza):
    """Odczyt początkowy sprzed końca lutego: przejazdy z ostatnich dni lutego
    też są w oknie — inaczej nieopisanych byłoby za dużo."""
    a = auto()
    db.dodaj_odczyt_przebiegu(a, 10000, "25.02.2026")
    przejazd(a, "25.02.2026", 7)       # dzień odczytu — przed nim
    przejazd(a, "27.02.2026", 40)
    przejazd(a, "10.03.2026", 60)
    db.dodaj_odczyt_przebiegu(a, 10100, "31.03.2026")

    licznik = db.licznik_okresu(a, date(2026, 3, 1), date(2026, 3, 31))
    assert (licznik["km"], licznik["opisane_km"], licznik["nieopisane_km"]) == (100, 100.0, 0.0)

    # Licznik, który się cofa, nie udaje nieopisanych kilometrów.
    db.dodaj_odczyt_przebiegu(a, 9000, "31.03.2026")
    licznik = db.licznik_okresu(a, date(2026, 3, 1), date(2026, 3, 31))
    assert licznik["cofka"] and licznik["nieopisane_km"] is None


def test_przejazd_z_licznikiem_jest_zrodlem_historii(baza):
    a = auto()
    db.dodaj_odczyt_przebiegu(a, 120000, "01.03.2026")
    p_id = przejazd(a, "05.03.2026", 84, licznik=120084)
    przejazd(a, "06.03.2026", 10)       # bez licznika — w historii go nie ma

    historia = db.pobierz_pelna_historie_przebiegu(a)
    (z_przejazdu,) = [w for w in historia if w["zrodlo"] == "przejazd"]
    assert (z_przejazdu["przebieg"], z_przejazdu["trasa"], z_przejazdu["opis"]) == \
        (120084, f"/ewidencja/edytuj/{p_id}", "Warszawa – Łódź")
    assert z_przejazdu["etykieta_zrodla"] == db.ZRODLA_PRZEBIEGU["przejazd"]
    assert db.pobierz_aktualny_przebieg(a) == 120084
    assert db.pobierz_historie_przebiegu(a)[-1] == ("05.03.2026", 120084)

    # Poprawiany przejazd nie ostrzega sam przed sobą, nowy wpis niższy — tak.
    assert db.sprawdz_czy_przebieg_podejrzany(a, 120090, wyklucz_id=p_id, tabela="przejazdy",
                                              nowa_data_str="05.03.2026") is None
    assert db.sprawdz_czy_przebieg_podejrzany(a, 120050, nowa_data_str="06.03.2026")


def test_poprzedni_stan_licznika(baza):
    a = auto()
    db.dodaj_odczyt_przebiegu(a, 120000, "01.03.2026")
    p1 = przejazd(a, "05.03.2026", 84, licznik=120084)
    przejazd(a, "05.03.2026", 16, licznik=120100)

    assert db.poprzedni_stan_licznika(a, "05.03.2026")["przebieg"] == 120100
    assert db.poprzedni_stan_licznika(a, "05.03.2026", licznik=120090)["przebieg"] == 120084
    assert db.poprzedni_stan_licznika(a, "05.03.2026", licznik=120090, wyklucz_id=p1)["przebieg"] == 120000
    assert db.poprzedni_stan_licznika(a, "28.02.2026") is None


def test_zamkniecie_miesiaca_zapisuje_odczyt_z_ostatniego_dnia(baza):
    a = auto()
    marzec(a)
    przejazd(a, "28.03.2026", 40)

    stan = db.stan_na_koniec_miesiaca(a, ROK, MIESIAC, dzis=PO_MIESIACU)
    assert (stan["zamkniety"], stan["mozna_zamknac"]) == (False, True)
    assert (stan["odczyt"], stan["data_odczytu"], stan["km_po_odczycie"], stan["podpowiedz"]) == \
        (121078, date(2026, 3, 20), 40.0, 121118)
    assert db.stan_na_koniec_miesiaca(a, ROK, MIESIAC, dzis=date(2026, 3, 30))["mozna_zamknac"] is False

    assert db.zamknij_miesiac_ewidencji(a, ROK, MIESIAC, 121118)
    assert jeden("SELECT data, przebieg, zrodlo FROM odczyty_przebiegu WHERE data='31.03.2026'") == \
        ("31.03.2026", 121118, "ewidencja")
    assert db.stan_na_koniec_miesiaca(a, ROK, MIESIAC, dzis=PO_MIESIACU)["zamkniety"]
    # Ten sam dzień nadpisuje odczyt zamiast go dublować.
    db.zamknij_miesiac_ewidencji(a, ROK, MIESIAC, 121120)
    assert jeden("SELECT COUNT(*), MAX(przebieg) FROM odczyty_przebiegu WHERE data='31.03.2026'") == (1, 121120)
    assert not db.zamknij_miesiac_ewidencji(a, ROK, MIESIAC, "abc")


def test_podpowiedzi_z_historii(baza):
    a = auto()
    przejazd(a, "01.03.2026", 10, skad="Dom", dokad="Biuro", cel="Praca")
    przejazd(a, "02.03.2026", 10, skad="dom ", dokad="Klient ABC", cel="praca", kierowca="Ola")
    przejazd(a, "03.03.2026", 10, skad="Biuro", dokad="Dom", cel="Powrót")

    podp = db.podpowiedzi_przejazdow(a)
    assert podp["miejsca"][:2] == ["Dom", "Biuro"], "trzy razy Dom (bez wielkości liter), dwa razy Biuro"
    assert podp["cele"] == ["praca", "Powrót"] and podp["kierowcy"] == ["Kamil Wroczyński", "Ola"]

    ostatni = db.ostatni_przejazd_trasy(a, "biuro", "DOM")
    assert (ostatni["km_jednej_strony"], ostatni["data"]) == (10.0, "03.03.2026")
    assert db.ostatni_przejazd_trasy(a, "Dom", "Kraków") is None
    assert db.ostatni_przejazd_trasy(a, "Dom", "") is None


def test_miesiace_i_poczatek_ewidencji(baza):
    a = auto()
    marzec(a)
    przejazd(a, "10.01.2026", 50)
    assert db.miesiace_ewidencji(a) == [(2026, 3, 4, 977.5), (2026, 1, 1, 50.0)]
    assert db.pierwszy_przejazd(a) == date(2026, 1, 10)
    assert db.czy_ma_przejazdy(a) and not db.czy_ma_przejazdy(auto("Pusty"))


def test_zdania_miesiaca_zaleza_od_ukladu(baza):
    a = auto()
    marzec(a)
    przejazd(a, "21.03.2026", 5, skad="", dokad="", cel="Poczta", kierowca="")
    db.dodaj_odczyt_przebiegu(a, 121300, "31.03.2026")
    p = db.podsumowanie_ewidencji(a, ROK, MIESIAC, dzis=PO_MIESIACU)

    vat = [z for _, z in db.zdania_ewidencji(p, "vat")]
    assert any(z.startswith("W tym miesiącu są przejazdy prywatne: 1 (12,5 km)") for z in vat)
    assert "1 przejazd bez trasy (skąd – dokąd)." in vat and "1 przejazd bez kierowcy." in vat
    assert any(z.startswith("Licznik pokazuje o 217,5 km więcej") for z in vat)

    kilometrowka = [z for _, z in db.zdania_ewidencji(p, "kilometrowka")]
    assert not any("Licznik pokazuje" in z for z in kilometrowka), "kilometry spoza ewidencji to jazdy prywatne"
    assert "1 przejazd bez kierowcy." not in kilometrowka
    assert ("info", "Ustaw stawkę za kilometr, a policzę kwotę kilometrówki.") in db.zdania_ewidencji(p, "kilometrowka")

    podzial = [z for _, z in db.zdania_ewidencji(p, "podzial")]
    assert not any("prywatne:" in z or "bez trasy" in z for z in podzial)


# ============================================================================
#  3. RAPORT MIESIĄCA
# ============================================================================

def _wartosc(pary, etykieta):
    return dict(pary)[etykieta]


def test_raport_vat_ma_elementy_ewidencji(baza):
    a = auto()
    marzec(a)
    db.zamknij_miesiac_ewidencji(a, ROK, MIESIAC, 121300)

    r = db.dane_raportu_ewidencji(a, ROK, MIESIAC, "vat", dzis=PO_MIESIACU)

    assert r["tytul"] == "Ewidencja przebiegu pojazdu" and r["uklad"] == "vat"
    assert _wartosc(r["naglowek"], "Numer rejestracyjny") == "WX 12345"
    assert _wartosc(r["naglowek"], "Okres rozliczeniowy") == "01.03.2026 – 31.03.2026"
    assert _wartosc(r["naglowek"], "Ewidencja prowadzona od") == "02.03.2026"
    assert _wartosc(r["naglowek"], "Stan licznika na początek okresu") == "120 100 km"
    assert _wartosc(r["naglowek"], "Stan licznika na koniec okresu") == "121 300 km"
    assert [k[0] for k in r["kolumny"]] == ["Lp.", "Data", "Cel wyjazdu", "Opis trasy (skąd – dokąd)",
                                            "Liczba km", "Kierowca (imię i nazwisko)"]
    assert r["wiersze"][0] == ["1", "02.03.2026", "Spotkanie z klientem ABC", "Warszawa – Łódź – Warszawa",
                               "270", "Kamil Wroczyński"]
    assert [w[0] for w in r["wiersze"]] == ["1", "2", "3", "4"] and r["razem"][4] == "977,5"
    assert _wartosc(r["podsumowanie"], "Liczba przejechanych km w okresie") == "977,5"
    assert _wartosc(r["podsumowanie"], "Nieopisane (licznik a ewidencja)") == "222,5 km"
    assert any(u.startswith("W tym miesiącu są przejazdy prywatne") for u in r["uwagi"])
    assert r["podpisy"] == ["Potwierdzam zgodność wpisów — data i podpis podatnika"]
    assert r["nazwa_pliku"] == "ewidencja_vat_2026-03"


def test_raport_vat_bez_odczytu_z_ostatniego_dnia_prosi_o_zamkniecie(baza):
    a = auto()
    marzec(a)
    r = db.dane_raportu_ewidencji(a, ROK, MIESIAC, "vat", dzis=PO_MIESIACU)
    assert _wartosc(r["naglowek"], "Stan licznika na koniec okresu") == "121 078 km (odczyt z 20.03.2026)"
    assert any("Zamknij miesiąc" in u for u in r["uwagi"])


def test_raport_kilometrowki_tylko_sluzbowe_ze_stawka(baza):
    a = auto()
    marzec(a)
    db.zapisz_dane_osoby_ewidencji("Kamil Wroczyński", "ul. Długa 5, Warszawa", "ACME")
    db.zapisz_ustawienia_ewidencji(a, "kilometrowka")

    r = db.dane_raportu_ewidencji(a, ROK, MIESIAC, dzis=PO_MIESIACU)

    assert r["uklad"] == "kilometrowka", "układ z trybu pojazdu"
    assert _wartosc(r["naglowek"], "Osoba używająca pojazdu") == "Kamil Wroczyński"
    assert _wartosc(r["naglowek"], "Adres zamieszkania") == "ul. Długa 5, Warszawa"
    assert _wartosc(r["naglowek"], "Pracodawca") == "ACME"
    assert _wartosc(r["naglowek"], "Pojemność silnika") == "1 598 cm³"
    assert _wartosc(r["naglowek"], "Stawka za 1 km") == "1,15 PLN"
    assert len(r["wiersze"]) == 3 and "Zakupy" not in [w[2] for w in r["wiersze"]]
    assert r["wiersze"][0][-2:] == ["1,15", "310,50"]
    assert r["razem"][-1] == "1 109,75" and _wartosc(r["podsumowanie"], "Kwota do zwrotu") == "1 109,75 PLN"
    assert r["podpisy"] == ["Podpis osoby używającej pojazdu", "Data, podpis i pieczęć pracodawcy"]
    assert r["uwagi"] == []


def test_raport_podzialu_z_kosztami(baza):
    a = auto()
    przejazd(a, "02.03.2026", 300)
    przejazd(a, "03.03.2026", 100, sluzbowy=False)
    with db.polacz_baze() as conn:
        conn.execute("INSERT INTO inne_koszty (auto_id, data, data_iso, kategoria, nazwa, kwota) "
                     "VALUES (?, '05.03.2026', '2026-03-05', 'Inne', 'Myjnia', 400)", (a,))

    r = db.dane_raportu_ewidencji(a, ROK, MIESIAC, "podzial", dzis=PO_MIESIACU)

    assert [w[5] for w in r["wiersze"]] == ["służbowy", "prywatny"]
    assert _wartosc(r["podsumowanie"], "Służbowe") == "300 km (75%)"
    assert _wartosc(r["podsumowanie"], "Prywatne") == "100 km (25%)"
    assert _wartosc(r["podsumowanie"], "Część służbowa (75%)") == "300,00 PLN"
    assert _wartosc(r["podsumowanie"], "Część prywatna (25%)") == "100,00 PLN"


def test_pdf_i_csv_raportu(baza, monkeypatch):
    from db import raporty

    if db.FPDF is None:
        pytest.skip("brak fpdf2")
    a = auto()
    db.dodaj_odczyt_przebiegu(a, 100000, "28.02.2026")
    for dzien in range(1, 31):
        for _ in range(2):
            przejazd(a, f"{dzien:02d}.03.2026", 12, cel="Bardzo długi cel wyjazdu, który musi się zawinąć w komórce "
                                                    "tabeli zamiast wyjść poza jej krawędź")
    napisy = []
    oryginal = raporty._RaportPDF.cell

    def cell(self, *argumenty, **nazwane):
        if len(argumenty) >= 3:
            napisy.append(str(argumenty[2]))
        return oryginal(self, *argumenty, **nazwane)

    monkeypatch.setattr(raporty._RaportPDF, "cell", cell)
    r = db.dane_raportu_ewidencji(a, ROK, MIESIAC, "vat", dzis=PO_MIESIACU)
    pdf = db.generuj_pdf_ewidencji(r)

    t = raporty._RaportPDF(orientation="L").t
    assert pdf.startswith(b"%PDF")
    assert napisy.count(t("Lp.")) >= 2, "nagłówek tabeli powtarza się na kolejnej stronie"
    assert t("Ewidencja przebiegu pojazdu") in napisy and "60" in napisy and "720" in napisy
    assert t("Potwierdzam zgodność wpisów — data i podpis podatnika") in napisy
    assert t("Bardzo długi cel wyjazdu,") in " ".join(napisy)

    csv = db.generuj_csv_ewidencji(r).decode("utf-8-sig").splitlines()
    assert csv[0] == "Lp.;Data;Cel wyjazdu;Opis trasy (skąd – dokąd);Liczba km;Kierowca (imię i nazwisko)"
    assert len(csv) == 62 and csv[-1].startswith(";;Razem;;720")


def test_pdf_pustego_miesiaca(baza):
    if db.FPDF is None:
        pytest.skip("brak fpdf2")
    a = auto()
    r = db.dane_raportu_ewidencji(a, ROK, MIESIAC, "kilometrowka", dzis=PO_MIESIACU)
    assert r["wiersze"] == [] and r["razem"] is None
    assert db.generuj_pdf_ewidencji(r).startswith(b"%PDF")


# ============================================================================
#  4. PRZYPOMNIENIE I KAFELEK
# ============================================================================

def test_przypomnienie_o_zamknieciu_poprzedniego_miesiaca(baza):
    a = auto()
    marzec(a)

    stan = db.przypomnienie_ewidencji(a, dzis=date(2026, 4, 3))
    assert (stan["rok"], stan["miesiac"], stan["liczba"], stan["klucz"]) == (2026, 3, 4, "ewidencja:2026-03")
    assert db.przypomnienie_ewidencji(a, dzis=date(2026, 4, db.DNI_PRZYPOMNIENIA_EWIDENCJI + 1)) is None
    assert db.przypomnienie_ewidencji(a, dzis=date(2026, 5, 2)) is None, "kwiecień bez przejazdów"

    db.zamknij_miesiac_ewidencji(a, ROK, MIESIAC, 121300)
    assert db.przypomnienie_ewidencji(a, dzis=date(2026, 4, 3)) is None


def test_przypomnienie_w_dzwonku(baza, monkeypatch):
    a = auto()
    dzis = date.today()
    poprzedni = dzis.replace(day=1) - timedelta(days=1)
    przejazd(a, poprzedni.strftime("%d.%m.%Y"), 40)
    monkeypatch.setattr(db.ewidencja, "DNI_PRZYPOMNIENIA_EWIDENCJI", 31)

    (p,) = [x for x in db.pobierz_powiadomienia(a) if x["typ"] == "ewidencja"]
    assert p["trasa"] == f"/ewidencja/{poprzedni.year}/{poprzedni.month}"
    assert p["tytul"] == f"Ewidencja: {db.nazwa_miesiaca(poprzedni.year, poprzedni.month)}"
    assert p["opis"].startswith("1 przejazd, 40 km — wpisz stan licznika na ")
    assert "ewidencja" in db.TYPY_POWIADOMIEN_O_DANYCH

    with db.polacz_baze() as conn:
        conn.execute("UPDATE samochody SET rola_wspoldzielenia=? WHERE id=?", (db.ROLA_PODGLAD, a))
    assert not [x for x in db.pobierz_powiadomienia(a) if x["typ"] == "ewidencja"]


def test_kafelek_ewidencji(baza):
    a = auto()
    assert db.kafel_ewidencji(a) is None, "auto bez przejazdów — kafelek nie dotyczy"
    dzis = date.today()
    przejazd(a, dzis.strftime("%d.%m.%Y"), 30)
    przejazd(a, dzis.strftime("%d.%m.%Y"), 10, sluzbowy=False)

    k = db.kafel_ewidencji(a)
    assert (k["rok"], k["miesiac"], k["km_sluzbowe"], k["km"]) == (dzis.year, dzis.month, 30.0, 40.0)
    assert k["udzial_sluzbowy"] == 0.75 and k["kwota"] is None
    assert db.metryki_kokpitu(a, ["ewidencja"])["ewidencja"]["km_sluzbowe"] == 30.0


# ============================================================================
#  2. SZABLONY TRAS
# ============================================================================

def test_trasa_z_formularza_jest_tez_w_kalkulatorze(baza):
    a = auto()
    t_id = db.zapisz_trase_szablon(a, "Do biura", 25, powrot=True, osoby=2, oplaty=10)
    assert db.zapisz_szablon_przejazdu(a, "do biura ", "Dom", "Biuro", "Praca", True, 26, True) == t_id

    (t,) = db.pobierz_trasy_szablony(a)
    assert (t["skad"], t["dokad"], t["cel"], t["sluzbowy"], t["dystans"]) == ("Dom", "Biuro", "Praca", True, 26.0)
    assert (t["osoby"], t["oplaty"]) == (2, 10.0), "liczba osób i opłaty kalkulatora zostają"

    # Kalkulator nadpisuje swoje pola — skąd, dokąd, cel i rodzaj zostają.
    db.zapisz_trase_szablon(a, "Do biura", 27, powrot=True, osoby=3, oplaty=0, trasa_id=t_id)
    (t,) = db.pobierz_trasy_szablony(a)
    assert (t["skad"], t["dokad"], t["cel"], t["sluzbowy"], t["dystans"]) == ("Dom", "Biuro", "Praca", True, 27.0)

    nowa = db.zapisz_szablon_przejazdu(a, "Zakupy", dokad="Sklep", sluzbowy=False, dystans=5)
    assert next(x for x in db.pobierz_trasy_szablony(a) if x["id"] == nowa)["sluzbowy"] is False
    assert db.zapisz_szablon_przejazdu(a, "  ") is None


# ============================================================================
#  5. FORMULARZ PRZEJAZDU
# ============================================================================

def formularz(auto_id, przejazd_id=None, **zrodlo):
    if zrodlo:
        return widok("FormularzPrzejazduView", auto_id, przejazd_id=przejazd_id, zrodlo=zrodlo)
    return widok("FormularzPrzejazduView", auto_id, {"przejazd": przejazd_id} if przejazd_id else None)


def test_formularz_zapisuje_przejazd_tam_i_z_powrotem(baza, zapis_formularza):
    a = auto()
    f = formularz(a)
    f.e_data.value = "02.03.2026"
    f.e_skad.value, f.e_dokad.value, f.e_cel.value = "Warszawa", "Łódź", "Spotkanie"
    f.e_km.value = "135"
    f.c_powrot.value = True
    f.e_kierowca.value = "Kamil"
    f.k_notatka.value = "Parking 12 zł"

    f.zapisz(None)

    (p,) = db.pobierz_przejazdy(a)
    assert (p["km"], p["powrot"], p["sluzbowy"], p["kierowca"], p["notatka"]) == \
        (270.0, True, True, "Kamil", "Parking 12 zł")
    assert zapis_formularza["trasy"] == ["/ewidencja/2026/3"]
    assert zapis_formularza["komunikaty"] == ["Zapisano przejazd • 270 km służbowo"]


def test_formularz_wymaga_kilometrow_i_trasy(baza, zapis_formularza):
    a = auto()
    f = formularz(a)
    f.zapisz(None)
    assert db.pobierz_przejazdy(a) == []
    assert zapis_formularza["komunikaty"] == ["Podaj kilometry większe od zera", "Podaj trasę albo cel przejazdu"]


def test_formularz_z_szablonu_i_z_kalkulatora(baza):
    a = auto()
    t_id = db.zapisz_szablon_przejazdu(a, "Klient", "Biuro", "Klient ABC", "Wdrożenie", False, 40, True)

    f = formularz(a, szablon=t_id)
    assert (f.e_skad.value, f.e_dokad.value, f.e_cel.value, f.e_km.value, f.c_powrot.value) == \
        ("Biuro", "Klient ABC", "Wdrożenie", "40", True)
    assert f.rodzaj == 1, "rodzaj z trasy — prywatny"

    f = formularz(a, kalkulator=(84.5, False, t_id))
    assert (f.e_skad.value, f.e_km.value, f.c_powrot.value) == ("Biuro", "84,5", False)
    f = formularz(a, kalkulator=(12, True, None))
    assert (f.e_skad.value, f.e_km.value, f.c_powrot.value) == ("", "12", True)


def test_formularz_powtorz_i_powrot(baza):
    a = auto()
    p_id = przejazd(a, "02.03.2026", 135, cel="Spotkanie", kierowca="Ola")

    f = formularz(a, powtorz=p_id)
    assert (f.e_data.value, f.e_skad.value, f.e_dokad.value, f.e_kierowca.value) == \
        (datetime.now().strftime("%d.%m.%Y"), "Warszawa", "Łódź", "Ola")
    assert f.przejazd_id is None, "powtórzenie to NOWY przejazd"

    f = formularz(a, powrot=p_id)
    assert (f.e_data.value, f.e_skad.value, f.e_dokad.value, f.e_cel.value) == \
        ("02.03.2026", "Łódź", "Warszawa", "Spotkanie")


def test_formularz_liczy_kilometry_z_licznika(baza, zapis_formularza):
    a = auto()
    db.dodaj_odczyt_przebiegu(a, 120000, "01.03.2026")
    f = formularz(a)
    f.e_data.value = "05.03.2026"
    f.e_dokad.value = "Klient"
    f._po_zmianie_licznika(aktualizuj=False)
    assert f.t_licznik.value.startswith("Poprzedni stan: 120 000 km (01.03.2026, odczyt licznika).")

    f.e_licznik.value = "120084"
    f._po_zmianie_licznika(aktualizuj=False)
    assert f.e_km.value == "84" and "84 km" in f.t_licznik.value

    f.zapisz(None)
    (p,) = db.pobierz_przejazdy(a)
    assert (p["km"], p["licznik"]) == (84.0, 120084)


def test_formularz_edycji_pokazuje_jedna_strone(baza, zapis_formularza):
    a = auto()
    p_id = przejazd(a, "02.03.2026", 135, powrot=True)
    f = formularz(a, p_id)
    assert (f.przejazd_id, f.e_km.value, f.c_powrot.value) == (p_id, "135", True)
    assert not f._czy_zmieniono()

    f.c_powrot.value = False
    f.zapisz(None)
    assert db.pobierz_przejazd(p_id)["km"] == 135.0


def test_dzien_dla_miesiaca():
    from views.formularze.przejazd import dzien_dla_miesiaca

    dzis = date(2026, 4, 15)
    assert dzien_dla_miesiaca(2026, 4, dzis) == "15.04.2026"
    assert dzien_dla_miesiaca(2026, 2, dzis) == "28.02.2026"
    assert dzien_dla_miesiaca(2026, 6, dzis) == "01.06.2026"


# ============================================================================
#  6. EKRAN, ROUTER, ROLE
# ============================================================================

def test_ekran_miesiaca_pokazuje_podzial_licznik_i_liste(baza):
    a = auto()
    marzec(a)
    db.dodaj_odczyt_przebiegu(a, 121300, "31.03.2026")

    ekran = widok("EwidencjaPrzebieguView", a, rok=ROK, miesiac=MIESIAC)
    napisy = teksty(ekran)

    assert ekran.route == "/ewidencja/2026/3" and "Marzec 2026" in napisy
    assert "965 km" in napisy and "12,5 km" in napisy
    assert "99% służbowo • 4 przejazdy • razem 977,5 km" in napisy
    assert "Nieopisane: 222,5 km" in napisy
    assert "Warszawa – Kraków – Warszawa" in napisy and "Targi" in napisy
    assert "nr 4 • Kamil Wroczyński • licznik 121 078 km" in napisy
    assert any(t.startswith("Stan na 31.03") for t in napisy), "miesiąc zamknięty odczytem z ostatniego dnia"
    assert isinstance(ekran.floating_action_button, ft.FloatingActionButton)


def test_ekran_proponuje_zamkniecie_tylko_minionego_miesiaca(baza):
    a = auto()
    marzec(a)
    przyciski = [b.content for b in _wszystkie(widok("EwidencjaPrzebieguView", a, rok=ROK, miesiac=MIESIAC),
                                                ft.OutlinedButton)]
    assert przyciski == ["Raport miesiąca", "Zamknij miesiąc"]

    dzis = date.today()
    przejazd(a, dzis.strftime("%d.%m.%Y"), 10)
    biezacy = widok("EwidencjaPrzebieguView", a, rok=dzis.year, miesiac=dzis.month)
    if dzis != db.koniec_miesiaca(dzis.year, dzis.month):
        assert [b.content for b in _wszystkie(biezacy, ft.OutlinedButton)] == ["Raport miesiąca"]


def test_ekran_przyszlego_miesiaca_wraca_do_biezacego(baza):
    a = auto()
    dzis = date.today()
    ekran = widok("EwidencjaPrzebieguView", a, rok=dzis.year + 1, miesiac=1)
    assert ekran.route == f"/ewidencja/{dzis.year}/{dzis.month}"
    assert "Brak przejazdów w tym miesiącu" in teksty(ekran)


def test_ekran_trybu_kilometrowki(baza):
    a = auto()
    marzec(a)
    db.zapisz_ustawienia_ewidencji(a, "kilometrowka")
    napisy = teksty(widok("EwidencjaPrzebieguView", a, rok=ROK, miesiac=MIESIAC))
    assert f"{utils.formatuj_liczba(1109.75)} {utils.symbol_waluty()}" in napisy
    assert f"965 km służbowo × 1,15 {utils.symbol_waluty()}/km" in napisy
    assert not any(t.startswith("Nieopisane") for t in napisy)


def test_podglad_bez_dodawania(baza):
    a = auto(rola_wspoldzielenia=db.ROLA_PODGLAD)
    marzec(a)
    ekran = widok("EwidencjaPrzebieguView", a, rok=ROK, miesiac=MIESIAC)
    assert ekran.floating_action_button is None
    assert [b.content for b in _wszystkie(ekran, ft.OutlinedButton)] == ["Raport miesiąca"]


def test_menu_przejazdu_wedlug_roli(baza, monkeypatch):
    a = auto(rola_wspoldzielenia=db.ROLA_WSPOLAUTOR)
    db.zapisz_moje_imie("Ola")
    p_id = przejazd(a, "02.03.2026", 10)       # dodane przez „Ola” — moje
    with db.polacz_baze() as conn:
        cudzy = conn.execute("INSERT INTO przejazdy (auto_id, data, data_iso, dokad, km, dodane_przez) "
                             "VALUES (?, '03.03.2026', '2026-03-03', 'Biuro', 5, 'Kamil')", (a,)).lastrowid
    menu = {}
    monkeypatch.setattr(utils, "pokaz_menu_kontekstowe",
                        lambda strona, tytul, pozycje: menu.update({tytul: [p["tekst"] for p in pozycje]}))
    ekran = widok("EwidencjaPrzebieguView", a, rok=ROK, miesiac=MIESIAC)

    ekran._menu(db.pobierz_przejazd(p_id))
    ekran._menu(db.pobierz_przejazd(cudzy))

    assert menu["Warszawa – Łódź"] == ["Powtórz dziś", "Trasa powrotna", "Zapisz jako trasę", "Edytuj",
                                      "Oznacz jako prywatny", "Notatka", "Usuń przejazd"]
    assert menu["Biuro"][:2] == ["Powtórz dziś", "Zapisz jako trasę"]
    assert "Usuń przejazd" not in menu["Biuro"] and "Edytuj" not in menu["Biuro"]


@pytest.fixture
def router(baza, monkeypatch):
    monkeypatch.setattr(ft, "run", lambda *args, **kwargs: None)
    import log
    import main

    db.zapisz_widziana_wersje(db.WERSJA_APLIKACJI)
    monkeypatch.setattr(log, "wlacz", lambda: True)
    monkeypatch.setitem(utils.wyglad._OSTATNI_MOTYW, "nazwa", utils.wyglad._OSTATNI_MOTYW["nazwa"])
    strona = pomoce.zbuduj_strone()
    monkeypatch.setattr(type(strona.page), "run_task", lambda self, *args, **kwargs: None)
    return strona, main


def test_router_kladzie_formularz_na_miesiacu_przejazdu(router):
    strona, main = router
    a = auto()
    p_id = przejazd(a, "02.03.2026", 10)
    page = strona.page
    main.main(page)

    utils.przejdz(page, "/ewidencja/2026/3")
    assert [type(w).__name__ for w in page.views] == ["MainView", "EwidencjaPrzebieguView"]
    assert (page.views[-1].rok, page.views[-1].miesiac) == (2026, 3)

    utils.przejdz(page, f"/ewidencja/edytuj/{p_id}")
    assert [type(w).__name__ for w in page.views] == ["MainView", "EwidencjaPrzebieguView", "FormularzPrzejazduView"]
    assert page.views[1].route == "/ewidencja/2026/3" and page.views[-1].przejazd_id == p_id

    utils.przejdz(page, "/ewidencja/nowy/dzien/28.02.2026")
    assert page.views[1].route == "/ewidencja/2026/2" and page.views[-1].e_data.value == "28.02.2026"

    utils.przejdz(page, f"/ewidencja/powrot/{p_id}")
    assert page.views[-1].e_skad.value == "Łódź" and page.views[1].route == "/ewidencja/2026/3"

    utils.przejdz(page, "/kalkulator/ewidencja/84500/1/0")
    assert [type(w).__name__ for w in page.views] == ["MainView", "KalkulatorTrasyView", "FormularzPrzejazduView"]
    assert (page.views[-1].e_km.value, page.views[-1].c_powrot.value, page.views[-1].powrot_do) == \
        ("84,5", True, "/kalkulator")


def test_cel_tras_ewidencji(router):
    _, main = router
    assert main._cel_trasy(["ewidencja"])[0] is False
    assert main._cel_trasy(["ewidencja", "2026", "3"])[0] is False
    for trasa in (["ewidencja", "nowy"], ["ewidencja", "powtorz", "5"], ["ewidencja", "powrot", "5"],
                  ["kalkulator", "ewidencja", "1000", "0", "0"]):
        assert main._cel_trasy(trasa)[:2] == (True, True), trasa
    assert main._cel_trasy(["ewidencja", "edytuj", "7"]) == (True, False, "przejazdy", 7)

    a = auto(rola_wspoldzielenia=db.ROLA_PODGLAD)
    assert main._wolno_wejsc(a, ["ewidencja", "2026", "3"])[0]
    assert not main._wolno_wejsc(a, ["ewidencja", "nowy"])[0]


def test_kalkulator_przekazuje_trase_do_ewidencji(baza, monkeypatch):
    a = auto()
    trasy = []
    monkeypatch.setattr(utils, "przejdz", lambda strona, trasa: trasy.append(trasa))
    k = widok("KalkulatorTrasyView", a)
    assert any(b.content == "Dodaj do ewidencji przebiegu" for b in _wszystkie(k, ft.OutlinedButton))

    k.e_dystans.value = "42,5"
    k.c_powrot.value = True
    k._do_ewidencji()
    assert trasy == ["/kalkulator/ewidencja/42500/1/0"]

    # Trasa wczytana z zapisanych idzie w adresie — formularz weźmie z niej skąd, dokąd i cel.
    t_id = db.zapisz_trase_szablon(a, "Do biura", 25)
    k._trasa_wczytana = t_id
    k.c_powrot.value = False
    k._do_ewidencji()
    assert trasy[-1] == f"/kalkulator/ewidencja/42500/0/{t_id}"


def test_ekran_w_rejestrze_i_wyszukiwarce():
    ekran = utils.EKRANY_WG_ID["ewidencja"]
    assert (ekran["trasa"], ekran["grupa"]) == ("/ewidencja", "koszty")
    for fraza in ("kilometrówka", "ewidencja", "przejazd", "vat"):
        assert "ewidencja" in [e["id"] for e in utils.znajdz_ekrany(fraza)], fraza


# ============================================================================
#  7. WYSZUKIWARKA, EKSPORT, IMPORT
# ============================================================================

def test_wyszukiwarka_znajduje_przejazdy(baza):
    a = auto()
    p_id = przejazd(a, "02.03.2026", 10, dokad="Biuro klienta", cel="Wdrożenie", kierowca="Ola")
    przejazd(a, "03.03.2026", 5, dokad="Sklep", sluzbowy=False)

    (wynik,) = db.globalne_wyszukiwanie(a, "biuro klienta")
    assert (wynik["typ"], wynik["tytul"], wynik["trasa"]) == ("Przejazd", "Warszawa – Biuro klienta",
                                                               f"/ewidencja/edytuj/{p_id}")
    assert wynik["opis"] == "Wdrożenie • 10 km • służbowy • Ola"
    assert [w["tytul"] for w in db.globalne_wyszukiwanie(a, "kategoria:prywatny")] == ["Warszawa – Sklep"]
    assert [w["typ"] for w in db.globalne_wyszukiwanie(a, "ola")] == ["Przejazd"]


def test_eksport_przejazdow(baza):
    a = auto()
    przejazd(a, "02.03.2026", 12.5, powrot=True, licznik=120025)
    naglowki, wiersze = db.pobierz_dane_eksportu(a, ["przejazdy"])["przejazdy"]
    assert naglowki[:5] == ["Data", "Skąd", "Dokąd", "Cel", "Dystans (km)"]
    assert wiersze == [["02.03.2026", "Warszawa", "Łódź", "Spotkanie z klientem", "25", "Tak", "Służbowy",
                        "Kamil Wroczyński", 120025, ""]]
    assert db.pobierz_dane_eksportu(a, ["przejazdy"], date(2026, 4, 1))["przejazdy"][1] == []
    assert "przejazdy" in db.KATEGORIE_EKSPORTU and "przejazdy" in utils.IKONY_EKSPORTU


def test_import_przejazdow_z_arkusza(baza):
    a = auto()
    przejazd(a, "02.03.2026", 135)       # już jest — duplikat
    naglowki = ["Data", "Opis trasy (skąd - dokąd)", "Cel wyjazdu", "Liczba km", "Rodzaj", "Kierowca", "Uwagi"]
    wiersze = [
        ["02.03.2026", "Warszawa - Łódź", "Spotkanie", "135", "służbowy", "Kamil", ""],
        ["03.03.2026", "Warszawa – Radom – Warszawa", "Serwis", "210", "", "Kamil", "Faktura 12"],
        ["04.03.2026", "Dom → Sklep", "Zakupy", "4,5", "prywatny", "", ""],
        ["05.03.2026", "", "", "10", "", "", ""],
        ["xx", "A - B", "C", "10", "", "", ""],
    ]
    typ = db.TYPY_IMPORTU["przejazdy"]
    mapowanie = typ["dopasuj"](naglowki)
    assert {k: mapowanie[k] for k in ("data", "trasa", "cel", "km", "rodzaj", "kierowca", "notatka")} == \
        {"data": 0, "trasa": 1, "cel": 2, "km": 3, "rodzaj": 4, "kierowca": 5, "notatka": 6}

    raport = typ["przygotuj"](a, naglowki, wiersze, mapowanie)
    assert raport["duplikaty"] == 1 and [n for n, _ in raport["bledy"]] == [5, 6]
    radom, sklep = raport["gotowe"]
    assert (radom["skad"], radom["dokad"], radom["powrot"], radom["km"], radom["sluzbowy"]) == \
        ("Warszawa", "Radom", True, 210.0, True)
    assert (sklep["skad"], sklep["dokad"], sklep["km"], sklep["sluzbowy"]) == ("Dom", "Sklep", 4.5, False)
    assert typ["podglad"](radom, "l") == "03.03.2026 • Warszawa – Radom – Warszawa • Serwis • 210 km • służbowy • Kamil"

    assert typ["zapisz"](a, raport["gotowe"]) == 2
    p = db.pobierz_przejazdy(a, date(2026, 3, 3), date(2026, 3, 3))[0]
    assert (p["km"], p["km_jednej_strony"], p["notatka"]) == (210.0, 105.0, "Faktura 12")


# ============================================================================
#  8. MIGRACJA, CHMURA, USUWANIE
# ============================================================================

def test_migracja_50_doklada_przejazdy_i_kolumny_tras(magazyn):
    probki_baz.zbuduj_baze_w_wersji(db.BAZA_DANYCH, 49, DRABINKA)
    conn = sqlite3.connect(db.BAZA_DANYCH)
    c = conn.cursor()
    c.execute("INSERT INTO samochody (nazwa, typ_paliwa) VALUES ('Stary', 'Benzyna')")
    a = c.lastrowid
    c.execute("INSERT INTO trasy_szablony (auto_id, nazwa, dystans, powrot, osoby, oplaty) "
              "VALUES (?, 'Do teściów', 180, 1, 2, 45)", (a,))
    conn.commit()
    conn.close()
    assert "przejazdy" not in pomoce.nazwy_tabel()

    db.init_db()

    assert {"skad", "dokad", "cel", "km", "powrot", "sluzbowy", "kierowca", "licznik",
            "data_iso"} <= set(pomoce.kolumny("przejazdy"))
    (t,) = db.pobierz_trasy_szablony(a)
    assert (t["nazwa"], t["dystans"], t["skad"], t["cel"], t["sluzbowy"]) == ("Do teściów", 180.0, "", "", None)


class _Odpowiedz:
    def __init__(self, data=None):
        self.data = data


class ChmuraWPamieci:
    """Supabase na tyle, na ile potrzebuje go `_wypchnij_tabele`."""

    def __init__(self, rekordy=None):
        self.rekordy = dict(rekordy or {})

    def rpc(self, nazwa, parametry):
        chmura = self

        class _Wywolanie:
            def execute(self):
                if nazwa == "aktualizuj_zdalny_rekord":
                    chmura.rekordy[parametry["p_id"]] = parametry["p_dane"]
                    return _Odpowiedz()
                nowe = f"nowy-{len(chmura.rekordy) + 1}"
                chmura.rekordy[nowe] = parametry["p_dane"]
                return _Odpowiedz(nowe)
        return _Wywolanie()

    def table(self, nazwa):
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


def wypchnij(chmura, auto_id, konfig):
    return sync_wysylanie._wypchnij_tabele(chmura, "wspolny", auto_id, konfig, db.ROLA_WLASCICIEL)[0]


def _trasa_jak_ze_starszej_wersji(auto_id, nazwa, zdalne_id):
    """Trasa zsynchronizowana starszą wersją: hash i chmura bez skąd, dokąd,
    celu i rodzaju (kolumny `dopisane`)."""
    t_id = db.zapisz_trase_szablon(auto_id, nazwa, 180, powrot=True, osoby=2, oplaty=45)
    with db.polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        wiersz = dict(conn.execute("SELECT * FROM trasy_szablony WHERE id=?", (t_id,)).fetchone())
    stare = {k: v for k, v in wiersz.items() if k in KONFIG_TRAS["kolumny"] and k not in KONFIG_TRAS["dopisane"]}
    with db.polacz_baze() as conn:
        conn.execute("UPDATE trasy_szablony SET zdalne_id=?, zdalny_hash=? WHERE id=?",
                     (zdalne_id, sync_wysylanie._hash_zawartosci(stare), t_id))
    return stare


def test_trasa_sprzed_aktualizacji_nie_jedzie_do_chmury(baza):
    """Puste nowe kolumny trasy to nie zmiana — jedzie dopiero wzór przejazdu."""
    for kolumna in ("skad", "dokad", "cel", "sluzbowy"):
        assert kolumna in KONFIG_TRAS["kolumny"] and kolumna in KONFIG_TRAS["dopisane"], kolumna
    a = auto()
    stare = _trasa_jak_ze_starszej_wersji(a, "Do teściów", "trasa-A")
    sync_konflikty._konflikty_biezacej_synchronizacji.clear()
    chmura = ChmuraWPamieci({"trasa-A": stare})

    assert wypchnij(chmura, a, KONFIG_TRAS) == 0

    db.zapisz_szablon_przejazdu(a, "Do teściów", "Dom", "Teściowie", "Wizyta", False, 180, True)
    assert wypchnij(chmura, a, KONFIG_TRAS) == 1
    assert chmura.rekordy["trasa-A"]["skad"] == "Dom" and chmura.rekordy["trasa-A"]["sluzbowy"] == 0
    assert sync_konflikty._konflikty_biezacej_synchronizacji == []

    # Bez tolerancji pustych dopisanych kolumn po aktualizacji pojechałyby wszystkie trasy.
    inne = _trasa_jak_ze_starszej_wersji(a, "Nad morze", "trasa-M")
    rekordy = {"trasa-A": chmura.rekordy["trasa-A"], "trasa-M": inne}
    assert wypchnij(ChmuraWPamieci(rekordy), a, KONFIG_TRAS) == 0
    assert wypchnij(ChmuraWPamieci(rekordy), a, {**KONFIG_TRAS, "dopisane": []}) == 1


def test_przejazd_jedzie_do_chmury_i_na_drugi_telefon(baza):
    a = auto()
    przejazd(a, "02.03.2026", 135, powrot=True, licznik=120270)
    chmura = ChmuraWPamieci()
    assert wypchnij(chmura, a, KONFIG_PRZEJAZDOW) == 1
    (wyslany,) = chmura.rekordy.values()
    assert "data_iso" not in wyslany and wyslany["km"] == 270.0

    drugie = auto("Drugi telefon")
    assert sync_pobieranie._zastosuj_rekord(KONFIG_PRZEJAZDOW, {"id": "prz-B", "dane": wyslany}, drugie, {}) == 1
    (p,) = db.pobierz_przejazdy(drugie)
    assert (p["data"], p["km"], p["powrot"], p["licznik"], p["kierowca"]) == \
        ("02.03.2026", 270.0, True, 120270, "Kamil Wroczyński")
    assert jeden("SELECT data_iso FROM przejazdy WHERE auto_id=?", drugie) == ("2026-03-02",)
    assert db.pobierz_aktualny_przebieg(drugie) == 120270


def test_usuniecie_przejazdu_z_cofnieciem_i_nagrobkiem(baza):
    a = auto()
    p_id = przejazd(a, "02.03.2026", 10)
    with db.polacz_baze() as conn:
        conn.execute("UPDATE przejazdy SET zdalne_id='prz-1' WHERE id=?", (p_id,))

    wynik = db.usun_z_cofnieciem("przejazdy", p_id)
    assert db.pobierz_przejazdy(a) == []
    assert "prz-1" in [n[2] for n in db.pobierz_nagrobki(a)]

    wynik["cofnij"]()
    (p,) = db.pobierz_przejazdy(a)
    assert p["km"] == 10.0 and "prz-1" not in [n[2] for n in db.pobierz_nagrobki(a)]


def test_kosz_pojazdu_zabiera_przejazdy(baza):
    d = pomoce.utworz_pojazd("Z ewidencją")
    db.usun_auto_do_kosza(d["auto_id"])
    assert jeden("SELECT COUNT(*) FROM przejazdy") == (0,)
    (pozycja,) = db.pobierz_kosz()
    db.przywroc_auto_z_kosza(pozycja["id"])
    assert jeden("SELECT km, licznik, notatka FROM przejazdy") == (84.0, 100700, "Parking 12 zł")


# ============================================================================
#  OKNA EKRANU EWIDENCJI
# ============================================================================

@pytest.fixture
def okna(monkeypatch):
    """Okienka zbierane zamiast pokazywane; odświeżenia i komunikaty liczone."""
    otwarte = []
    zdarzenia = {"komunikaty": [], "odswiezenia": 0}

    def odswiez(strona):
        zdarzenia["odswiezenia"] += 1

    monkeypatch.setattr(utils, "otworz_dialog", lambda strona, dlg: otwarte.append(dlg))
    monkeypatch.setattr(utils, "zamknij_dialog", lambda strona, dlg: None)
    monkeypatch.setattr(utils, "odswiez_ekran", odswiez)
    monkeypatch.setattr(utils, "pokaz_komunikat", lambda strona, tekst, *a, **k: zdarzenia["komunikaty"].append(tekst))
    monkeypatch.setattr(utils, "wypchnij_w_tle", lambda *a, **k: None)
    return otwarte, zdarzenia


def test_okno_ustawien_zapisuje_tryb_stawke_i_dane_osoby(baza, okna):
    otwarte, zdarzenia = okna
    a = auto()
    ekran = widok("EwidencjaPrzebieguView", a, rok=ROK, miesiac=MIESIAC)

    ekran._okno_ustawien()
    (dlg,) = otwarte
    (grupa,) = _wszystkie(dlg, ft.RadioGroup)
    stawka, osoba, adres, pracodawca = _wszystkie(dlg, ft.TextField)
    assert stawka.hint_text == "puste = 1,15 z pojemności silnika"
    grupa.value, stawka.value = "kilometrowka", "1,05"
    osoba.value, adres.value, pracodawca.value = "Kamil Wroczyński", "ul. Długa 5", ""
    dlg.actions[-1].on_click(None)

    assert db.pobierz_ustawienia_ewidencji(a) == {"tryb": "kilometrowka", "stawka": 1.05}
    assert db.pobierz_dane_osoby_ewidencji()["osoba"] == "Kamil Wroczyński"
    assert zdarzenia == {"komunikaty": ["Zapisano ustawienia ewidencji."], "odswiezenia": 1}

    ekran._okno_ustawien()
    _wszystkie(otwarte[-1], ft.TextField)[0].value = "abc"
    otwarte[-1].actions[-1].on_click(None)
    assert db.pobierz_ustawienia_ewidencji(a)["stawka"] == 1.05, "zła stawka nie nadpisuje dobrej"


def test_okno_zamkniecia_miesiaca(baza, okna):
    otwarte, zdarzenia = okna
    a = auto()
    marzec(a)
    przejazd(a, "28.03.2026", 40)
    ekran = widok("EwidencjaPrzebieguView", a, rok=ROK, miesiac=MIESIAC)

    ekran._okno_zamkniecia()
    (dlg,) = otwarte
    (pole,) = _wszystkie(dlg, ft.TextField)
    assert pole.value == "121118"
    assert "Podpowiedź: odczyt z 20.03 (121 078 km) + przejazdy po nim (40 km)." in teksty(dlg)
    dlg.actions[-1].on_click(None)

    assert db.stan_na_koniec_miesiaca(a, ROK, MIESIAC)["zamkniety"]
    assert zdarzenia["komunikaty"] == ["Zamknięto marzec 2026: stan 121 118 km na 31.03.2026."]


def test_okno_raportu_zapisuje_plik_w_ukladzie_trybu(baza, okna):
    import asyncio

    otwarte, _ = okna
    a = auto()
    marzec(a)
    db.zapisz_ustawienia_ewidencji(a, "vat")
    pliki = {}

    async def zapisz_bajty(nazwa, bajty):
        pliki[nazwa] = bajty

    ekran = widok("EwidencjaPrzebieguView", a, rok=ROK, miesiac=MIESIAC)
    ekran._page.zapisz_bajty_pliku = zapisz_bajty
    ekran._okno_raportu()
    (dlg,) = otwarte
    assert "Ewidencja do VAT" in teksty(dlg) and any("art. 86a" in t for t in teksty(dlg))

    asyncio.run(dlg.actions[-1].on_click(None))

    (nazwa,) = pliki
    assert nazwa == "ewidencja_vat_2026-03_Octavia.pdf"
    if db.FPDF is not None:
        assert pliki[nazwa].startswith(b"%PDF")
