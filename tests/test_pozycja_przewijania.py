"""Pozycja przewijania: ekran ma zostawać tam, gdzie był.

Router przebudowuje CAŁY stos widoków przy każdej zmianie sortowania, filtra
i po każdej akcji na wpisie (`przejdz(page, page.route)` → `page.views.clear()`).
Nowa lista zaczynała się od zera, więc ktoś, kto przewinął sto tankowań w dół
i odhaczył jedno z nich, lądował z powrotem na samej górze.

Plik sprawdza trzy rzeczy:

1. **Pamięć** — co się zapisuje, czego się nie zapisuje i kiedy się kasuje.
2. **Podpięcie** — czy dokładamy się do `on_scroll`, zamiast po cichu wyłączać
   tego, kto był tam pierwszy (na listach siedzi jeszcze nagłówek miesiąca).
3. **Prawdziwe widoki** — czy listy naprawdę to dostały i czy po przebudowie
   wracają tam, gdzie były.
"""

import pathlib
import sys

sys.path[:0] = [str(pathlib.Path(__file__).resolve().parent), str(pathlib.Path(__file__).resolve().parents[1])]

import flet as ft  # noqa: E402
import pytest  # noqa: E402

import pomoce  # noqa: E402
import utils  # noqa: E402


class Zdarzenie:
    """`OnScrollEvent` ma wiele pól; liczy się jedno."""

    def __init__(self, pixels):
        self.pixels = pixels


class Stan:
    """Namiastka AppState — pamięć pozycji nie potrzebuje niczego więcej."""

    def __init__(self, **pola):
        self.pozycje_przewijania = {}
        for nazwa, wartosc in pola.items():
            setattr(self, nazwa, wartosc)


class StronaZPetla:
    """Strona, na której `run_task` da się podejrzeć, zamiast naprawdę uruchamiać."""

    def __init__(self):
        self.zadania = []

    def run_task(self, handler, *a, **k):
        self.zadania.append(handler)


class Lista:
    """Kontrolka przewijalna w minimalnej postaci."""

    def __init__(self):
        self.on_scroll = None
        self.scroll_interval = None
        self.przewinieto_na = []

    def scroll_to(self, offset=None, duration=None, **k):
        self.przewinieto_na.append(offset)


@pytest.fixture
def petla(monkeypatch):
    """Udaje działającą pętlę zdarzeń — bez niej powrót w ogóle się nie planuje."""
    monkeypatch.setattr(utils.pozycja, "_petla_dziala", lambda page: True)


async def _odpal(strona):
    for zadanie in list(strona.zadania):
        await zadanie()


# ============================================================================
#  1. PAMIĘĆ
# ============================================================================

def test_pozycja_powyzej_progu_zostaje_zapamietana():
    stan = Stan()

    utils.zapisz_pozycje(stan, "lista:tankowania", 1500)

    assert utils.pobierz_pozycje(stan, "lista:tankowania") == 1500


@pytest.mark.parametrize("pikseli", [0, None, utils.PROG_PAMIETANIA - 1])
def test_prawie_gora_nie_jest_pozycja(pikseli):
    """Bez progu każde muśnięcie palcem zapisywałoby „prawie na górze", a powrót
    na taką pozycję wyglądałby jak usterka: ekran drgałby po każdym wejściu."""
    stan = Stan()
    utils.zapisz_pozycje(stan, "lista:tankowania", 900)

    utils.zapisz_pozycje(stan, "lista:tankowania", pikseli)

    assert utils.pobierz_pozycje(stan, "lista:tankowania") is None


def test_nieznane_miejsce_nie_ma_pozycji():
    assert utils.pobierz_pozycje(Stan(), "lista:czegos-takiego-nie-ma") is None


def test_zapomnienie_jednego_miejsca_nie_rusza_reszty():
    stan = Stan()
    utils.zapisz_pozycje(stan, "lista:a", 500)
    utils.zapisz_pozycje(stan, "lista:b", 700)

    utils.zapomnij_pozycje(stan, "lista:a")

    assert utils.pobierz_pozycje(stan, "lista:a") is None
    assert utils.pobierz_pozycje(stan, "lista:b") == 700


def test_zapomnienie_bez_klucza_czysci_wszystko():
    """Wołane przy zmianie pojazdu: to samo miejsce na liście, ale zupełnie inne
    wpisy — powrót na dwa tysiące pikseli w dół nie znaczyłby już nic."""
    stan = Stan()
    utils.zapisz_pozycje(stan, "lista:a", 500)
    utils.zapisz_pozycje(stan, "lista:b", 700)

    utils.zapomnij_pozycje(stan)

    assert stan.pozycje_przewijania == {}


# ============================================================================
#  2. PODPIĘCIE
# ============================================================================

def test_dodanie_obslugi_nie_wylacza_poprzedniej():
    """Na liście tankowań siedzi nagłówek miesiąca i pamięć pozycji. Przypisanie
    wprost sprawiłoby, że ten, kto dopisze się drugi, po cichu wyłącza
    pierwszego — a najgorsze w takiej usterce jest to, że nic nie wybucha."""
    lista = Lista()
    slad = []
    utils.dodaj_obsluge_przewijania(lista, lambda e: slad.append("pierwszy"))

    utils.dodaj_obsluge_przewijania(lista, lambda e: slad.append("drugi"))
    lista.on_scroll(Zdarzenie(100))

    assert slad == ["pierwszy", "drugi"]


def test_odstep_zdarzen_nie_robi_sie_rzadszy():
    lista = Lista()
    lista.scroll_interval = 10

    utils.dodaj_obsluge_przewijania(lista, lambda e: None)

    assert lista.scroll_interval == 10, "ktoś chciał gęściej — nie rozrzedzamy mu tego"


def test_odstep_zdarzen_ustawia_sie_gdy_go_nie_bylo():
    lista = Lista()

    utils.dodaj_obsluge_przewijania(lista, lambda e: None)

    assert lista.scroll_interval == utils.ODSTEP_ZDARZEN_MS


def test_pamietanie_zapisuje_pozycje_z_przewijania():
    stan, lista = Stan(), Lista()
    utils.pamietaj_pozycje(None, stan, lista, "lista:historia")

    lista.on_scroll(Zdarzenie(820))

    assert utils.pobierz_pozycje(stan, "lista:historia") == 820


def test_klucz_moze_byc_liczony_w_chwili_przewijania():
    """Ekran główny NIE przebudowuje się przy zmianie zakładki — przewijana jest
    wciąż ta sama kontrolka, a miejsce, którego dotyczy, już inne."""
    stan, lista = Stan(zakladka=1), Lista()
    utils.pamietaj_pozycje(None, stan, lista, lambda: f"ekran:/#{stan.zakladka}")

    lista.on_scroll(Zdarzenie(300))
    stan.zakladka = 0
    lista.on_scroll(Zdarzenie(900))

    assert utils.pobierz_pozycje(stan, "ekran:/#1") == 300
    assert utils.pobierz_pozycje(stan, "ekran:/#0") == 900


# ============================================================================
#  3. POWRÓT
# ============================================================================

def test_powrot_planuje_sie_i_dojezdza_na_zapamietana_pozycje(petla):
    import asyncio

    stan, strona, lista = Stan(), StronaZPetla(), Lista()
    utils.zapisz_pozycje(stan, "lista:odczyty", 1240)

    utils.pamietaj_pozycje(strona, stan, lista, "lista:odczyty")

    assert strona.zadania, "powrót miał zostać zaplanowany"
    asyncio.run(_odpal(strona))
    assert lista.przewinieto_na == [1240, 1240], (
        "dwie próby: jedna po klatce, druga po oknie szkieletu"
    )


def test_bez_zapamietanej_pozycji_nic_sie_nie_planuje(petla):
    strona, lista = StronaZPetla(), Lista()

    utils.pamietaj_pozycje(strona, Stan(), lista, "lista:odczyty")

    assert strona.zadania == []
    assert lista.przewinieto_na == []


def test_bez_dzialajacej_petli_powrot_odpuszcza():
    """Budowa widoku bez okna (testy, audyty) ma dać ten sam ekran, tylko bez
    ruchu — a nie porzuconą korutynę."""
    strona, lista = StronaZPetla(), Lista()
    stan = Stan()
    utils.zapisz_pozycje(stan, "lista:odczyty", 1240)

    utils.pamietaj_pozycje(strona, stan, lista, "lista:odczyty")

    assert strona.zadania == []


def test_druga_proba_odpuszcza_gdy_uzytkownik_sam_przewinal(petla):
    """Szarpnięcie ekranem dwieście milisekund po wejściu byłoby gorsze niż
    zostanie na górze."""
    import asyncio

    stan, strona, lista = Stan(), StronaZPetla(), Lista()
    utils.zapisz_pozycje(stan, "lista:odczyty", 1240)
    utils.pamietaj_pozycje(strona, stan, lista, "lista:odczyty")

    # Użytkownik przewija sam, zanim druga próba zdąży dojść do głosu.
    lista.on_scroll(Zdarzenie(120))
    asyncio.run(_odpal(strona))

    assert lista.przewinieto_na == [1240], "druga próba miała odpuścić"


def test_skrocona_lista_nie_wywala_powrotu(petla):
    """Filtr mógł obciąć listę do trzech wpisów — `scroll_to` rzuci wtedy
    wyjątkiem, a ekran ma po prostu zostać na górze."""
    import asyncio

    class ListaKtoraRzuca(Lista):
        def scroll_to(self, **k):
            raise RuntimeError("nie ma dokąd przewijać")

    stan, strona = Stan(), StronaZPetla()
    utils.zapisz_pozycje(stan, "lista:krotka", 5000)

    utils.pamietaj_pozycje(strona, stan, ListaKtoraRzuca(), "lista:krotka")
    asyncio.run(_odpal(strona))


# ============================================================================
#  4. KLUCZ MIEJSCA
# ============================================================================

def test_klucz_ekranu_rozroznia_zakladki():
    """Ekran główny to cztery ekrany pod jedną trasą — bez tego Kokpit
    odziedziczyłby pozycję po Serwisie, z którego się przyszło."""
    widok = type("W", (), {"route": "/"})()
    kokpit = utils.klucz_ekranu(widok, Stan(zakladka=0, koszty_podzakladka=0, stat_podzakladka=0))
    serwis = utils.klucz_ekranu(widok, Stan(zakladka=1, koszty_podzakladka=0, stat_podzakladka=0))

    assert kokpit != serwis


def test_klucz_ekranu_rozroznia_podzakladki_kosztow():
    widok = type("W", (), {"route": "/"})()
    tankowania = utils.klucz_ekranu(widok, Stan(zakladka=2, koszty_podzakladka=0, stat_podzakladka=0))
    inne = utils.klucz_ekranu(widok, Stan(zakladka=2, koszty_podzakladka=1, stat_podzakladka=0))

    assert tankowania != inne


def test_klucz_ekranu_poza_glownym_to_sama_trasa():
    widok = type("W", (), {"route": "/magazyn"})()

    assert utils.klucz_ekranu(widok, Stan(zakladka=3)) == "ekran:/magazyn"


# ============================================================================
#  5. PRAWDZIWE WIDOKI
# ============================================================================

LISTY_WIDOKOW = [
    ("TimelineView", "lista_kart"),
    ("DoZrobieniaView", "lista_kart"),
    ("HistoriaView", "lista_kart"),
    ("WizytyZbiorczeView", "lista_kart"),
    ("OdczytyPrzebieguView", "lista_kart"),
    ("MagazynView", "lista_kart_opony"),
]


@pytest.mark.parametrize("nazwa_widoku, pole", LISTY_WIDOKOW, ids=[w for w, _ in LISTY_WIDOKOW])
def test_lista_widoku_zapamietuje_pozycje(baza, nazwa_widoku, pole):
    stan, identyfikatory = pomoce.przygotuj_scenariusz("pojazd_z_historia")
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()[nazwa_widoku], pomoce.zbuduj_strone(),
                                stan, identyfikatory)

    lista = getattr(widok, pole, None)
    assert isinstance(lista, ft.ListView), f"{nazwa_widoku} nie ma listy w polu {pole}"
    assert lista.on_scroll is not None, "lista nie zapamiętuje, gdzie stanął pasek"

    lista.on_scroll(Zdarzenie(777))
    assert 777 in stan.pozycje_przewijania.values()


def test_pozycja_przezywa_przebudowe_widoku(baza):
    """Sedno całej zmiany: zmiana sortowania buduje widok od nowa, a lista ma
    wrócić tam, gdzie była."""
    stan, identyfikatory = pomoce.przygotuj_scenariusz("pojazd_z_historia")
    klasa = pomoce.klasy_widokow()["OdczytyPrzebieguView"]

    pierwszy = pomoce.zbuduj_widok(klasa, pomoce.zbuduj_strone(), stan, identyfikatory)
    pierwszy.lista_kart.on_scroll(Zdarzenie(1100))

    stan.sort["odczyty"] = ("przebieg", True)
    drugi = pomoce.zbuduj_widok(klasa, pomoce.zbuduj_strone(), stan, identyfikatory)

    assert drugi is not pierwszy
    assert utils.pobierz_pozycje(stan, "lista:odczyty") == 1100, (
        "pamięć pozycji nie przeżyła przebudowy — a to jedyny moment, w którym jest potrzebna"
    )
