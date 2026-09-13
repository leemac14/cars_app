"""Przejścia między zakładkami: co ma zostać na miejscu, co ma się wyzerować.

Zakładki przełącza się teraz BEZ przebudowy ekranu — i to jest sedno całej
zmiany, ale też jej jedyne realne ryzyko. Konstruktor widoku zerował dotąd przy
okazji cały stan per zakładka (tryb zaznaczania, referencje kart, stan kokpitu);
skoro już nie powstaje, zerowanie musi robić ktoś inny. Zaznaczenie, które
przeszłoby z Serwisu na Koszty, kasowałoby nie te wpisy, co trzeba.
"""

import asyncio

import flet as ft
import pytest

import db
import pomoce
import utils


def teksty(kontrolka, limit=20000):
    zebrane = []
    do_odwiedzenia = [kontrolka]
    while do_odwiedzenia and len(zebrane) < limit:
        biezaca = do_odwiedzenia.pop()
        if isinstance(biezaca, ft.Text):
            zebrane.append(biezaca.value)
        for nazwa in ("controls", "content", "title", "appbar",
                      "floating_action_button", "drawer", "navigation_bar"):
            wartosc = getattr(biezaca, nazwa, None)
            if isinstance(wartosc, (list, tuple)):
                do_odwiedzenia.extend(w for w in wartosc if isinstance(w, ft.Control))
            elif isinstance(wartosc, ft.Control):
                do_odwiedzenia.append(wartosc)
    return zebrane


def ekran_glowny(scenariusz="pojazd_z_danymi", zakladka=0):
    stan, _ = pomoce.przygotuj_scenariusz(scenariusz)
    stan.zakladka = zakladka
    strona = pomoce.zbuduj_strone()
    # Router w teście nie istnieje; ekran bez pojazdu próbuje przez niego wrócić.
    strona.page.on_route_change = lambda e=None: None
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], strona, stan)
    widok._strona_testowa = strona   # referencja musi żyć: sesja wisi na słabej
    return widok, stan


# ============================================================================
#  PRZEŁĄCZNIK
# ============================================================================

def test_kierunek_bierze_sie_z_kolejnosci_w_pasku():
    kierunek = utils.PrzelacznikEkranow.kierunek

    assert kierunek((0, 0), (2, 0)) == 1, "zakładka po prawej wjeżdża z prawej"
    assert kierunek((3, 0), (1, 0)) == -1
    assert kierunek((2, 0), (2, 1)) == 1, "podzakładka po prawej też jedzie w prawo"
    assert kierunek((2, 1), (2, 0)) == -1
    assert kierunek((1, 0), (1, 0)) == 0


def test_nowa_zawartosc_wjezdza_z_zadanej_strony():
    przelacznik = utils.PrzelacznikEkranow(ft.Text("stara"))

    assert przelacznik.kontrolka.content.offset.x == 0, "pierwsza zawartość nie wjeżdża znikąd"

    opakowanie = przelacznik.pokaz(None, ft.Text("nowa"), kierunek=1)

    assert opakowanie.offset.x > 0
    assert przelacznik.kontrolka.content is opakowanie
    assert opakowanie.animate_offset is not None, "bez animate_offset przesunięcie byłoby skokiem"


def test_kazda_zawartosc_ma_wlasny_klucz():
    """Bez różnych kluczy Flutter uzna nowe dziecko za to samo co poprzednie
    i przejścia po prostu nie będzie."""
    przelacznik = utils.PrzelacznikEkranow(ft.Text("a"))
    klucze = {przelacznik.kontrolka.content.key}

    for _ in range(3):
        klucze.add(przelacznik.pokaz(None, ft.Text("b"), kierunek=1).key)

    assert len(klucze) == 4


def test_wylaczone_animacje_gasza_i_czas_i_przesuniecie():
    przelacznik = utils.PrzelacznikEkranow(ft.Text("a"), wlaczony=False)

    opakowanie = przelacznik.pokaz(None, ft.Text("b"), kierunek=1)

    assert przelacznik.kontrolka.duration == 0
    assert opakowanie.offset.x == 0


def test_bez_petli_zdarzen_przesuniecie_nie_zostaje_w_polowie():
    """Offset zeruje się w osobnym zadaniu. Gdyby nie było go komu wykonać,
    zawartość zostałaby przesunięta w bok na stałe."""
    przelacznik = utils.PrzelacznikEkranow(ft.Text("a"))
    strona = pomoce.zbuduj_strone()

    opakowanie = przelacznik.pokaz(strona.page, ft.Text("b"), kierunek=-1)

    assert opakowanie.offset.x == 0


# ============================================================================
#  EKRAN GŁÓWNY
# ============================================================================

def test_zmiana_zakladki_nie_przebudowuje_naglowka_ani_paskow(baza):
    """To jest cały powód tej zmiany: nagłówek auta i oba paski mają ZOSTAĆ."""
    widok, stan = ekran_glowny(zakladka=0)
    naglowek = widok.controls[0]
    pasek_gorny = widok.appbar
    pasek_dolny = widok.navigation_bar

    widok.przelacz_zakladke(1)

    assert widok.controls[0] is naglowek
    assert widok.appbar is pasek_gorny
    assert widok.navigation_bar is pasek_dolny
    assert stan.zakladka == 1


def test_zmiana_zakladki_podmienia_zawartosc(baza):
    widok, _ = ekran_glowny(zakladka=0)
    przed = teksty(widok.przelacznik_zakladek.kontrolka)

    widok.przelacz_zakladke(1)

    assert teksty(widok.przelacznik_zakladek.kontrolka) != przed
    assert widok.pasek_zakladek.selected_index == 1


def test_powrot_na_zakladke_odbudowuje_jej_zawartosc(baza):
    widok, _ = ekran_glowny(zakladka=0)
    kokpit = teksty(widok.przelacznik_zakladek.kontrolka)

    widok.przelacz_zakladke(2)
    widok.przelacz_zakladke(0)

    assert teksty(widok.przelacznik_zakladek.kontrolka) == kokpit


def test_zaznaczanie_nie_przechodzi_miedzy_zakladkami(baza):
    """Najgroźniejszy skutek przełączania bez przebudowy: zaznaczenie zrobione na
    jednej liście, a usuwanie wykonane na drugiej."""
    widok, _ = ekran_glowny(zakladka=1)
    widok.tryb_zaznaczania = True
    widok.zaznaczone_id = {1, 2, 3}
    widok.tabela_cel = "zadania"
    widok.karty_ref = {"stara-karta": ft.Container()}
    widok.uzyj_wirtualizacji = True
    widok.appbar = ft.AppBar(title=ft.Text("Zaznaczono: 3"))

    widok.przelacz_zakladke(2)

    assert widok.tryb_zaznaczania is False
    assert widok.zaznaczone_id == set()
    assert widok.tabela_cel == ""
    # Nowa zakładka zapełnia `karty_ref` SWOIMI kartami — nie ma tu być ani
    # jednej pozostałości po poprzedniej liście.
    assert "stara-karta" not in widok.karty_ref
    assert widok.appbar is widok.oryginalny_appbar


def test_stan_kokpitu_nie_zostaje_po_wyjsciu_z_niego(baza):
    widok, _ = ekran_glowny(zakladka=0)
    widok.kokpit_edycja = True

    widok.przelacz_zakladke(3)

    assert widok.kokpit_edycja is False
    assert widok.kokpit_kontener is None
    assert widok._kokpit_budowniczy == {}


def test_listy_poprzedniej_zakladki_nie_zostaja_w_widoku(baza):
    """Atrybuty `lista_kart*` wskazywałyby kontrolki spoza drzewa, a przy obrocie
    ekranu dostają `update()` — jeden taki wyjątek przerywał dopasowanie
    wysokości WSZYSTKICH list, także tej widocznej."""
    widok, _ = ekran_glowny(zakladka=2)
    listy = [n for n in vars(widok) if n.startswith("lista_kart")]
    assert listy, "zakładka Koszty ma listę kart — bez niej test niczego nie sprawdza"

    widok.przelacz_zakladke(0)

    assert [n for n in vars(widok) if n.startswith("lista_kart")] == []


def test_fab_idzie_za_zakladka(baza):
    """Analiza nie ma czego dodawać, więc nie ma też plusa — a plus z Serwisu
    nie ma prawa na niej zostać."""
    widok, _ = ekran_glowny(zakladka=1)
    assert widok.floating_action_button is not None

    widok.przelacz_zakladke(3)
    assert widok.floating_action_button is None

    widok.przelacz_zakladke(1)
    assert widok.floating_action_button is not None


def test_zmiana_zakladki_zapisuje_pamiec_startu(baza):
    """Zapis robił dotąd router. Bez niego aplikacja po restarcie wracałaby na
    zakładkę, z której użytkownik dawno wyszedł."""
    widok, _ = ekran_glowny(zakladka=0)

    widok.przelacz_zakladke(2)

    assert db.pobierz_ostatnia_zakladke() == 2


def test_pelne_przejscie_wjezdza_z_boku_i_dojezdza_na_miejsce(baza, monkeypatch):
    """Sprawdzian końcowy: prawdziwy ekran, prawdziwe przejście. Zawartość
    pojawia się przesunięta, a osobne zadanie sprowadza ją na miejsce — to ten
    drugi patch jest całym przesunięciem, bez niego Flutter nie ma czego rysować."""
    widok, _ = ekran_glowny(zakladka=0)
    zaplanowane = []
    monkeypatch.setattr(utils.animacje, "_petla_dziala", lambda strona: True)
    monkeypatch.setattr(ft.Page, "run_task", lambda self, handler, *a, **k: zaplanowane.append(handler))
    monkeypatch.setattr(ft.Page, "update", lambda self, *kontrolki: None)

    widok.przelacz_zakladke(2)
    opakowanie = widok.przelacznik_zakladek.kontrolka.content

    assert opakowanie.offset.x > 0, "zakładka po prawej ma wjechać z prawej"
    assert zaplanowane, "dojazd ma zostać zaplanowany"

    asyncio.run(zaplanowane[-1]())

    assert opakowanie.offset.x == 0


def test_liczniki_odswiezaja_sie_przy_zmianie_zakladki(baza):
    """Liczniki przy skrótach liczył konstruktor. Skoro nie powstaje, muszą
    przeliczać się przy przełączeniu — inaczej pokazywałyby stan sprzed niego."""
    widok, _ = ekran_glowny(zakladka=1)
    widok.liczniki_nawigacji = {"zmyslony": 999}

    widok.przelacz_zakladke(0)

    assert widok.liczniki_nawigacji.get("zmyslony") is None


def test_dotkniecie_aktywnej_zakladki_nic_nie_zmienia(baza):
    widok, _ = ekran_glowny(zakladka=2)
    zawartosc = widok.przelacznik_zakladek.kontrolka.content

    widok.przelacz_zakladke(2)

    assert widok.przelacznik_zakladek.kontrolka.content is zawartosc


def test_podzakladki_kosztow_przechodza_w_miejscu(baza):
    widok, stan = ekran_glowny(zakladka=2)
    stan.koszty_podzakladka = 0
    naglowek = widok.controls[0]

    widok.przelacz_zakladke(2, podzakladka=1)

    assert stan.koszty_podzakladka == 1
    assert widok.controls[0] is naglowek
    assert db.pobierz_podzakladke_kosztow() in (0, 1)


def test_ekran_bez_pojazdu_nie_wybucha_przy_zmianie_zakladki(baza):
    widok, stan = ekran_glowny("pusty_garaz", zakladka=0)

    assert widok.przelacznik_zakladek is None
    widok.przelacz_zakladke(2)

    assert stan.zakladka == 2


@pytest.mark.parametrize("zakladka", [0, 1, 2, 3])
def test_zawartosc_zakladki_nie_rozpycha_sie_na_wysokosc(baza, zakladka):
    """Zawartość siedzi teraz w `Column` wewnątrz przełącznika, a Column bez
    zadanej wysokości nie umie obsłużyć dziecka z `expand` — takie dziecko
    rozjechałoby układ na telefonie, czego test budowy widoku by nie zauważył."""
    widok, _ = ekran_glowny(zakladka=zakladka)

    kolumna = widok.przelacznik_zakladek.kontrolka.content.content
    rozpychajace = [type(k).__name__ for k in kolumna.controls if getattr(k, "expand", None)]

    assert rozpychajace == [], f"zakładka {zakladka}: {rozpychajace}"


# ============================================================================
#  MAGAZYN I DO ZROBIENIA
# ============================================================================

def test_magazyn_przelacza_polowy_w_miejscu(baza):
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    stan.magazyn_zakladka = 0
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MagazynView"], pomoce.zbuduj_strone(), stan)
    pasek = widok.pasek_podzakladek
    przed = teksty(widok.przelacznik.kontrolka)

    widok._przelacz_podzakladke(1)

    assert stan.magazyn_zakladka == 1
    assert widok.pasek_podzakladek is pasek, "pasek podzakładek ma zostać na miejscu"
    assert teksty(widok.przelacznik.kontrolka) != przed
    assert widok.trasa_fab == "/magazyn/czesci/nowa", "plus dodaje do tej połowy, którą widać"


def test_do_zrobienia_przelacza_podzakladki_z_tytulem(baza):
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    stan.do_zrobienia_podzakladka = 0
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["DoZrobieniaView"], pomoce.zbuduj_strone(), stan)

    widok._przelacz_podzakladke(1)

    assert stan.do_zrobienia_podzakladka == 1
    assert "Checklisty" in teksty(widok.appbar)
    assert widok.appbar is widok.oryginalny_appbar, "kopia dla trybu zaznaczania też idzie za tytułem"


@pytest.mark.parametrize("nazwa,pole,metoda", [
    ("MagazynView", "magazyn_zakladka", "_przelacz_podzakladke"),
    ("DoZrobieniaView", "do_zrobienia_podzakladka", "_przelacz_podzakladke"),
])
def test_zaznaczanie_nie_przechodzi_miedzy_podzakladkami(baza, nazwa, pole, metoda):
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    setattr(stan, pole, 0)
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()[nazwa], pomoce.zbuduj_strone(), stan)
    widok.tryb_zaznaczania = True
    widok.zaznaczone_id = {7}
    widok.karty_ref = {"stara-karta": ft.Container()}

    getattr(widok, metoda)(1)

    assert widok.tryb_zaznaczania is False
    assert widok.zaznaczone_id == set()
    assert "stara-karta" not in widok.karty_ref
