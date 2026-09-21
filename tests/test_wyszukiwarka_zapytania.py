"""Wyszukiwarka: zapytania datowe, operatory pól i cichy powrót do tekstu.

Wzorzec jest ten sam, co przy kwotach: wzorzec rozpoznawany WPROST w polu
tekstowym, a gdy nic nie pasuje — zwykłe szukanie po tekście. Ryzyko takiego
rozwiązania leży całe w drugiej połowie tego zdania: parser, który rozpozna
za dużo, POŁYKA zapytanie tekstowe i nie zgłasza tego niczym. „Listwa” nie
jest listopadem, „opony 205” nie są kwotą 205 zł, a „31.02.2026” nie jest
żadną datą — każdy z tych przypadków ma tu swój test, bo objawem błędu jest
pusta lista wyników, a nie wyjątek.

Druga pilnowana rzecz to zgodność wstecz: sama liczba i „>1000” mają dalej
chodzić dokładnie tą ścieżką, co przed zapytaniami datowymi.
"""

from datetime import date, datetime, timedelta

import pytest

import db
import pomoce


DZIS = datetime.now().date()


# ------------------------------------------------------------------ daty


@pytest.mark.parametrize("zapytanie, od, do", [
    ("marzec 2026", date(2026, 3, 1), date(2026, 3, 31)),
    ("marca 2026", date(2026, 3, 1), date(2026, 3, 31)),
    ("mar 2026", date(2026, 3, 1), date(2026, 3, 31)),
    ("MARZEC 2026", date(2026, 3, 1), date(2026, 3, 31)),
    ("03.2026", date(2026, 3, 1), date(2026, 3, 31)),
    ("03/2026", date(2026, 3, 1), date(2026, 3, 31)),
    ("2026-03", date(2026, 3, 1), date(2026, 3, 31)),
    ("luty 2024", date(2024, 2, 1), date(2024, 2, 29)),
    ("grudzień 2026", date(2026, 12, 1), date(2026, 12, 31)),
    ("rok 2026", date(2026, 1, 1), date(2026, 12, 31)),
    ("2026 rok", date(2026, 1, 1), date(2026, 12, 31)),
    ("rok:2025", date(2025, 1, 1), date(2025, 12, 31)),
    ("01.03.2026", date(2026, 3, 1), date(2026, 3, 1)),
    ("2026-03-01", date(2026, 3, 1), date(2026, 3, 1)),
    ("od 01.03.2026", date(2026, 3, 1), None),
    ("do 31.03.2026", None, date(2026, 3, 31)),
    ("01.01.2026-31.03.2026", date(2026, 1, 1), date(2026, 3, 31)),
    ("01.01.2026 .. 31.03.2026", date(2026, 1, 1), date(2026, 3, 31)),
])
def test_zapytania_datowe_daja_zakres(zapytanie, od, do):
    zakres = db.parsuj_zapytanie_datowe(zapytanie)
    assert zakres is not None, f"„{zapytanie}” nie zostało rozpoznane jako data"
    assert (zakres[0], zakres[1]) == (od, do)


@pytest.mark.parametrize("zapytanie, od, do", [
    ("dziś", DZIS, DZIS),
    ("dzisiaj", DZIS, DZIS),
    ("wczoraj", DZIS - timedelta(days=1), DZIS - timedelta(days=1)),
    ("ostatni tydzień", DZIS - timedelta(days=6), DZIS),
    ("ostatnie 7 dni", DZIS - timedelta(days=6), DZIS),
    ("ostatnie 30 dni", DZIS - timedelta(days=29), DZIS),
    ("ostatni miesiąc", DZIS - timedelta(days=29), DZIS),
    ("ten miesiąc", DZIS.replace(day=1), DZIS),
    ("ten rok", date(DZIS.year, 1, 1), DZIS),
    ("zeszły rok", date(DZIS.year - 1, 1, 1), date(DZIS.year - 1, 12, 31)),
])
def test_okresy_wzgledne_licza_sie_od_dzis(zapytanie, od, do):
    zakres = db.parsuj_zapytanie_datowe(zapytanie)
    assert zakres is not None, f"„{zapytanie}” nie zostało rozpoznane jako data"
    assert (zakres[0], zakres[1]) == (od, do)


def test_sam_miesiac_to_ostatni_ktory_juz_byl():
    """W listopadzie „marzec” dotyczy tego roku, w styczniu — poprzedniego."""
    for numer, nazwa in ((1, "styczeń"), (12, "grudzień")):
        rok = DZIS.year if numer <= DZIS.month else DZIS.year - 1
        assert db.parsuj_zapytanie_datowe(nazwa)[0] == date(rok, numer, 1)


def test_liczba_z_kropka_nie_jest_miesiacem():
    """„13.2026” to liczba — trzynastego miesiąca nie ma, a kwoty bywają."""
    assert db.parsuj_zapytanie_datowe("13.2026") is None
    assert db.parsuj_zapytanie("13.2026")["kwota"] is not None


def test_skrot_miesiaca_dziala_tylko_z_rokiem():
    """Samo „lis” to za często zwykłe słowo, żeby przełączać tryb wyszukiwarki."""
    assert db.parsuj_zapytanie_datowe("lis") is None
    assert db.parsuj_zapytanie_datowe("lis 2026")[0] == date(2026, 11, 1)


# ------------------------------------------------------------ pola i łączenie


def test_operatory_pol_wycinaja_sie_z_tekstu():
    filtr = db.parsuj_zapytanie("stacja:orlen")
    assert filtr["pola"] == [("stacja", "orlen")]
    assert filtr["tekst"] == ""


@pytest.mark.parametrize("zapytanie, pole, wartosc", [
    ("tag:ubezpieczenie", "tag", "ubezpieczenie"),
    ("kategoria:opłaty", "kategoria", "oplaty"),
    ("kat:opłaty", "kategoria", "oplaty"),
    ("typ:tankowanie", "typ", "tankowanie"),
    ("warsztat:janek", "warsztat", "janek"),
    ("wykonawca:janek", "warsztat", "janek"),
    ("notatka:trasa", "notatka", "trasa"),
    ('stacja:"orlen na wylocie"', "stacja", "orlen na wylocie"),
])
def test_aliasy_i_ogonki_sprowadzaja_sie_do_jednego_pola(zapytanie, pole, wartosc):
    assert db.parsuj_zapytanie(zapytanie)["pola"] == [(pole, wartosc)]


def test_filtry_sumuja_sie_w_jednym_zapytaniu():
    filtr = db.parsuj_zapytanie("stacja:orlen marzec 2026 >200 pełny")
    assert filtr["pola"] == [("stacja", "orlen")]
    assert (filtr["data"][0], filtr["data"][1]) == (date(2026, 3, 1), date(2026, 3, 31))
    assert (filtr["kwota"][0], filtr["kwota"][1]) == (200.0, None)
    assert filtr["tekst"] == "pełny"


def test_opis_konczy_sie_kwota():
    """Pasek trybu dokleja walutę na końcu — kolejność opisu nie jest kosmetyką."""
    assert db.parsuj_zapytanie("stacja:orlen >200")["opis"].endswith("kwota od 200,00")


# -------------------------------------------------- cichy powrót do tekstu


@pytest.mark.parametrize("zapytanie", [
    "olej",
    "listwa",           # zaczyna się od „lis”, ale nie jest listopadem
    "lis",
    "opony 205",        # rozmiar, nie kwota 205 zł
    "5w40",
    "31.02.2026",       # data, której nie ma
    "http://serwis",    # dwukropek, ale nie operator
    "rozmiar:225",      # pole spoza mapy
    "do zrobienia",
])
def test_nierozpoznane_zapytanie_wraca_do_tekstu(zapytanie):
    assert db.parsuj_zapytanie(zapytanie) is None


@pytest.mark.parametrize("zapytanie, dolna, gorna", [
    ("450", 441.0, 459.0),
    (">1000", 1000.0, None),
    ("200-500", 200.0, 500.0),
    ("do 500", None, 500.0),
])
def test_zapytania_kwotowe_dzialaja_jak_dotad(zapytanie, dolna, gorna):
    """Kwoty chodziły przed datami i mają chodzić dalej tą samą ścieżką."""
    filtr = db.parsuj_zapytanie(zapytanie)
    assert filtr["data"] is None and filtr["pola"] == [] and filtr["tekst"] == ""
    assert filtr["kwota"][0] == (pytest.approx(dolna) if dolna is not None else None)
    assert filtr["kwota"][1] == (pytest.approx(gorna) if gorna is not None else None)


# ------------------------------------------------------------- na bazie


@pytest.fixture
def pojazd(baza):
    return pomoce.utworz_pojazd()["auto_id"]


def _typy(wyniki):
    return sorted(w["typ"] for w in wyniki)


def test_zakres_dat_obejmuje_wszystkie_rodzaje_wpisow(pojazd):
    """Luty 2026 w danych testowych: tankowanie, inny koszt i odczyt licznika."""
    wyniki = db.globalne_wyszukiwanie(pojazd, "luty 2026")
    assert _typy(wyniki) == ["Inny koszt", "Odczyt licznika", "Tankowanie"]


def test_zakres_dat_pomija_wpisy_bez_daty(pojazd):
    """Warsztat i zapisana trasa nie mają daty — żaden zakres ich nie łapie."""
    wyniki = db.globalne_wyszukiwanie(pojazd, "rok 2026")
    assert "Warsztat" not in _typy(wyniki)


def test_filtr_pola_zaweza_do_jednego_wpisu(pojazd):
    wyniki = db.globalne_wyszukiwanie(pojazd, "stacja:orlen")
    assert [w["typ"] for w in wyniki] == ["Tankowanie"]
    assert "210,00" in wyniki[0]["opis"]


def test_typ_wpisu_jako_filtr(pojazd):
    wyniki = db.globalne_wyszukiwanie(pojazd, "typ:opony")
    assert [w["typ"] for w in wyniki] == ["Opony"]


def test_pole_i_data_naraz(pojazd):
    assert db.globalne_wyszukiwanie(pojazd, "stacja:orlen luty 2026")
    assert db.globalne_wyszukiwanie(pojazd, "stacja:orlen marzec 2026") == []


def test_filtr_kwoty_z_data(pojazd):
    """Tankowanie za 210 zł jest w lutym, wizyta za 480 zł w styczniu."""
    wyniki = db.globalne_wyszukiwanie(pojazd, "luty 2026 >200")
    assert [w["typ"] for w in wyniki] == ["Tankowanie"]


def test_tekst_po_wycieciu_filtrow_dalej_szuka(pojazd):
    assert db.globalne_wyszukiwanie(pojazd, "luty 2026 winieta")
    assert db.globalne_wyszukiwanie(pojazd, "luty 2026 zderzak") == []


def test_szukanie_tekstowe_nie_dubluje_podzespolow(pojazd):
    """Podzespoły były odpytywane dwa razy, więc każdy trafiony pokazywał się
    podwójnie — dublet w wynikach nie wywala niczego i dlatego umiał przeżyć."""
    wyniki = db.globalne_wyszukiwanie(pojazd, "Olej silnikowy")
    assert [w["typ"] for w in wyniki].count("Podzespół") == 1


# ------------------------------------------------------------ ekran /szukaj


@pytest.fixture
def ekran(pojazd, monkeypatch):
    from views.search_view import SzukajView

    strona = pomoce.zbuduj_strone()
    widok = SzukajView(strona.page, pomoce.stan_aplikacji(pojazd, "Testowy"))
    # Strona trzyma sesję przez weakref — musi żyć tak długo jak widok.
    widok._strona_testowa = strona
    # Widok nie jest wpięty w stronę, a samo odświeżenie nie jest tu sprawdzane.
    monkeypatch.setattr(widok, "update", lambda *a, **k: None)
    return widok


def test_pasek_trybu_mowi_czego_szuka(ekran):
    """Bez paska nie wiadomo, czemu „stacja:orlen” pominęło wpis ze słowem
    „orlen” w notatce — a to pierwsze pytanie, jakie się wtedy zadaje."""
    widok = ekran

    widok.pole_wyszukiwarki.value = "stacja:orlen"
    widok._wyszukaj(None)
    assert widok.pasek_trybu.visible
    assert not widok.podpowiedz_skladni.visible
    assert widok.lista_wynikow.controls

    widok.pole_wyszukiwarki.value = "olej"
    widok._wyszukaj(None)
    assert not widok.pasek_trybu.visible
    assert widok.podpowiedz_skladni.visible


def test_chip_skladni_wstawia_wzor_do_pola(ekran):
    widok = ekran
    chipy = widok.podpowiedz_skladni.content.controls[1].controls
    assert len(chipy) == len(db.PRZYKLADY_SKLADNI)

    chipy[0].on_click(None)

    assert widok.pole_wyszukiwarki.value == db.PRZYKLADY_SKLADNI[0][0]
    assert widok.pasek_trybu.visible


# ----------------------------------------------- zwykły tekst kontra operator


def test_operator_tylko_zawezaja_to_co_znajduje_sam_tekst(pojazd):
    """„orlen” ma znajdować to samo, co „stacja:orlen” — operator jest
    pomocnikiem, a nie warunkiem, żeby cokolwiek dostać."""
    tekstem = db.globalne_wyszukiwanie(pojazd, "orlen")
    polem = db.globalne_wyszukiwanie(pojazd, "stacja:orlen")

    assert [w["typ"] for w in polem] == ["Tankowanie"]
    assert {w["trasa"] for w in polem} <= {w["trasa"] for w in tekstem}


@pytest.mark.parametrize("fraza", ["Pełny bak", "pelny bak", "PELNY BAK", "bak pełny"])
def test_ogonki_wielkosc_liter_i_kolejnosc_slow_nie_maja_znaczenia(pojazd, fraza):
    """Notatka brzmi „Pełny bak przed trasą”. Szukanie po jednym ciągu znaków
    wykładało się na każdej z tych trzech rzeczy naraz."""
    assert [w["typ"] for w in db.globalne_wyszukiwanie(pojazd, fraza)] == ["Tankowanie"]


def test_kazde_slowo_musi_trafic(pojazd):
    assert db.globalne_wyszukiwanie(pojazd, "orlen trasą")
    assert db.globalne_wyszukiwanie(pojazd, "orlen zderzak") == []


def test_slowa_moga_pochodzic_z_roznych_pol(pojazd):
    """„warsztat janka” — jedno słowo z nazwy, drugie z drugiej części nazwy;
    wpis dostaje się do wyniku, bo zawiera OBA, a nie ten konkretny ciąg."""
    typy = {w["typ"] for w in db.globalne_wyszukiwanie(pojazd, "janka warsztat")}
    assert {"Warsztat", "Wizyta zbiorcza"} <= typy


@pytest.mark.parametrize("fraza", ["wizyta", "brak", "km", "szacunek"])
def test_napisy_z_interfejsu_nie_zalewaja_wynikow(pojazd, fraza):
    """Podpis wyniku i nazwa rodzaju są składane przez aplikację, nie wpisane
    przez użytkownika — gdyby wchodziły do szukania, „wizyta” wyrzucałoby
    wszystkie wizyty, a „brak” wszystko, co ma pustą rubrykę."""
    assert db.globalne_wyszukiwanie(pojazd, fraza) == []


def test_dlugi_ciag_cyfr_to_tekst_a_nie_kwota(pojazd):
    """Numeru telefonu nikt nie wpisuje jako ceny — jako kwota nie znajdował nic."""
    assert db.parsuj_zapytanie("123456789") is None, "żaden filtr — zwykły tekst"
    assert [w["typ"] for w in db.globalne_wyszukiwanie(pojazd, "123456789")] == ["Warsztat"]
    assert db.parsuj_zapytanie("1234567")["kwota"] is not None, "krótsze zostaje kwotą"
