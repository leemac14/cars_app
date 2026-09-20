"""Koszt na 1000 km w oknie kroczącym — liczba, która mówi „sprzedaj”.

Roczna suma kosztów rośnie także wtedy, gdy po prostu jeździsz więcej, więc
na pytanie „czy auto drożeje" nie odpowiada. Koszt na przejechany dystans
odpowiada, bo dzieli wydatek przez to, co się za niego dostało.

Testy pilnują czterech rzeczy: że okno liczy się z CAŁEGO okna, że punkt
powstaje dopiero wtedy, gdy okno mieści się w danych (inaczej krzywa
zaczynałaby się od fałszywego szczytu), że większy przebieg przy proporcjonalnie
większych kosztach NIE rusza tej liczby, i że drożejące auto widać — na krzywej,
w chipie rok do roku i w zdaniu w Obserwacjach.
"""

from datetime import date

import flet as ft

import db
import pomoce
import utils

POLA_DZIECI = ("controls", "content", "items", "actions", "leading", "trailing", "title", "subtitle")


def _miesiac_wstecz(ile):
    dzis = date.today()
    m, y = dzis.month - ile, dzis.year
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


def _auto(nazwa="Kroczący"):
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO samochody (nazwa, typ_paliwa, status) VALUES (?,?,?)",
            (nazwa, "Benzyna", db.STATUS_POJAZDU_AKTYWNY),
        )
        return c.lastrowid


def _tankowanie(auto_id, d, przebieg, kwota):
    with db.polacz_baze() as conn:
        conn.execute(
            "INSERT INTO tankowania (auto_id, data, przebieg, litry, kwota, stacja) "
            "VALUES (?,?,?,?,?,?)",
            (auto_id, d.strftime("%d.%m.%Y"), przebieg, kwota / 6.0, kwota, "Orlen"),
        )


def _wizyta(auto_id, d, kwota):
    with db.polacz_baze() as conn:
        conn.execute(
            "INSERT INTO wizyty (auto_id, data, przebieg, wykonawca, koszt_calkowity) VALUES (?,?,?,?,?)",
            (auto_id, d.strftime("%d.%m.%Y"), 0, "Warsztat", kwota),
        )


def _historia(auto_id, plan, przebieg_startowy=100000):
    """plan: lista (km_w_miesiacu, kwota_paliwa) od NAJSTARSZEGO miesiąca.

    Jedno tankowanie na miesiąc daje jednocześnie odczyt licznika i koszt —
    dokładnie tak, jak wygląda dziennik prowadzony normalnie."""
    przebieg = przebieg_startowy
    ile = len(plan)
    for i, (km, kwota) in enumerate(plan):
        przebieg += km
        _tankowanie(auto_id, _miesiac_wstecz(ile - 1 - i), przebieg, kwota)
    return przebieg


def _teksty(korzen):
    znalezione = []

    def zejdz(kontrolka):
        if isinstance(kontrolka, ft.Text) and kontrolka.value:
            znalezione.append(str(kontrolka.value))
        for nazwa in POLA_DZIECI:
            wartosc = getattr(kontrolka, nazwa, None)
            if isinstance(wartosc, (list, tuple)):
                for dziecko in wartosc:
                    if isinstance(dziecko, ft.Control):
                        zejdz(dziecko)
            elif isinstance(wartosc, ft.Control):
                zejdz(wartosc)

    zejdz(korzen)
    return znalezione


# ------------------------------------------------------------------ rachunek

def test_okno_liczy_koszt_z_calego_okna(baza):
    """Punkt krzywej to suma wydatków z N miesięcy podzielona przez dystans
    z tych samych N miesięcy — nie średnia z miesięcznych ilorazów."""
    auto_id = _auto()
    _historia(auto_id, [(1000, 500.0)] * 24)
    dane = db.koszt_na_1000km(auto_id, 12)

    assert dane["okno"] == 12
    assert dane["punkty"], "krzywa nie powstała mimo dwóch lat danych"
    assert dane["punkty"][-1]["km"] == 12000
    assert dane["punkty"][-1]["razem"] == 6000.0
    assert dane["punkty"][-1]["koszt"] == 500.0
    assert dane["biezacy"] == 500.0


def test_punkt_powstaje_dopiero_przy_pelnym_oknie(baza):
    """Niepełne okno liczyłoby wydatki przez niepełny dystans i krzywa
    zaczynałaby się od szczytu, którego nie było — akurat tam, gdzie oko szuka
    trendu."""
    auto_id = _auto()
    _historia(auto_id, [(1000, 500.0)] * 14)
    dane = db.koszt_na_1000km(auto_id, 12)

    # 14 miesięcy wpisów, ale pierwszy nie ma od czego odjąć licznika, więc
    # kilometry są policzone dla 13 miesięcy → dwa pełne okna dwunastomiesięczne.
    assert len(dane["punkty"]) == 2
    assert db.koszt_na_1000km(auto_id, 24)["punkty"] == []


def test_wiecej_jazdy_nie_rusza_ceny_jazdy(baza):
    """Sedno zgłoszenia: suma rośnie, gdy jeździsz więcej — koszt na 1000 km nie.

    Ostatnie pół roku to dwa razy więcej kilometrów i dwa razy większe rachunki.
    Roczna suma skacze o połowę, a cena jazdy stoi w miejscu."""
    # Trzydzieści miesięcy, nie dwadzieścia cztery: porównanie rok do roku
    # potrzebuje DWÓCH pełnych okien, a pierwszy miesiąc historii nie ma od
    # czego odjąć licznika.
    auto_id = _auto()
    _historia(auto_id, [(1000, 500.0)] * 24 + [(2000, 1000.0)] * 6)
    dane = db.koszt_na_1000km(auto_id, 12)

    ostatni = dane["punkty"][-1]
    rok_temu = next(p for p in dane["punkty"]
                    if p["klucz"] == f"{ostatni['rok'] - 1}-{ostatni['miesiac']:02d}")

    assert ostatni["razem"] == 9000.0 and rok_temu["razem"] == 6000.0  # suma w górę o 50%
    assert ostatni["koszt"] == 500.0 and rok_temu["koszt"] == 500.0    # cena jazdy bez zmian
    assert dane["zmiana_rdr"] == 0.0


def test_drozejace_auto_widac_w_oknie_i_rok_do_roku(baza):
    """To samo pół roku, ale rachunki w górę przy tym samym przebiegu."""
    auto_id = _auto()
    _historia(auto_id, [(1000, 500.0)] * 24 + [(1000, 1100.0)] * 6)
    dane = db.koszt_na_1000km(auto_id, 12)

    assert dane["biezacy"] == 800.0
    assert dane["biezacy"] > dane["srednia_zyciowa"]
    assert dane["zmiana_rdr"] == 60.0
    assert dane["szczyt"]["koszt"] == dane["biezacy"]

    # Dwa lata historii to za mało na rok do roku: krzywa ma wtedy dokładnie
    # jedno okno wstecz, a nie dwa. Chip nad wykresem po prostu się nie pokaże.
    krotkie = _auto("Krótka historia")
    _historia(krotkie, [(1000, 500.0)] * 24)
    assert db.koszt_na_1000km(krotkie, 12)["zmiana_rdr"] is None


def test_krotsze_okno_reaguje_szybciej(baza):
    """Po to są chipy: sześć miesięcy pokazuje świeży skok w pełnej wysokości,
    rok go uśrednia z tanim okresem sprzed skoku."""
    auto_id = _auto()
    _historia(auto_id, [(1000, 500.0)] * 18 + [(1000, 1100.0)] * 6)

    assert db.koszt_na_1000km(auto_id, 6)["biezacy"] == 1100.0
    assert db.koszt_na_1000km(auto_id, 12)["biezacy"] == 800.0


def test_kategorie_sumuja_sie_do_razem(baza):
    """Cienkie krzywe kategorii muszą leżeć w tej samej siatce, co gruba."""
    auto_id = _auto()
    _historia(auto_id, [(1000, 400.0)] * 24)
    for i in range(24):
        _wizyta(auto_id, _miesiac_wstecz(i), 100.0)
    ostatni = db.koszt_na_1000km(auto_id, 12)["punkty"][-1]

    assert round(ostatni["paliwo"] + ostatni["serwis"] + ostatni["inne"], 6) == round(ostatni["koszt"], 6)
    assert ostatni["serwis"] == 100.0 and ostatni["paliwo"] == 400.0


def test_srednia_zyciowa_z_tej_samej_historii(baza):
    """Linia odniesienia liczona z innego okresu niż krzywa leżałaby wobec niej
    krzywo i nie znaczyłaby nic."""
    auto_id = _auto()
    _historia(auto_id, [(1000, 500.0)] * 12 + [(1000, 900.0)] * 12)
    dane = db.koszt_na_1000km(auto_id, 12)

    # 23 miesiące z policzonymi kilometrami: 11 tanich i 12 drogich.
    assert 690 < dane["srednia_zyciowa"] < 710
    assert dane["biezacy"] == 900.0


def test_pusty_pojazd_nie_wywraca_sie(baza):
    assert db.koszt_na_1000km(None)["punkty"] == []
    assert db.koszt_na_1000km(_auto())["biezacy"] is None


# ------------------------------------------------------------------ ustawienie

def test_okno_zapamietane_per_pojazd_i_nie_miesza_sie_z_zakresami(baza):
    """Okno siedzi w tym samym wierszu, co zakresy wykresów — więc musi być
    pewne, że jedno nie nadpisuje drugiego."""
    a, b = _auto("A"), _auto("B")
    db.zapisz_okno_kroczace(a, 24)
    db.zapisz_zakres_wykresu(a, "wydatki", 3)

    assert db.pobierz_okno_kroczace(a) == 24
    assert db.pobierz_zakres_wykresu(a, "wydatki") == 3
    assert db.pobierz_okno_kroczace(b) == db.OKNO_1000KM_DOMYSLNE

    # Wartość spoza listy wraca do domyślnej, zamiast wywalać wykres.
    db.zapisz_okno_kroczace(a, 7)
    assert db.pobierz_okno_kroczace(a) == db.OKNO_1000KM_DOMYSLNE


# ------------------------------------------------------------------ wykres

def test_wykres_zaczyna_os_w_zerze(baza):
    """Obcięta oś robi z dziesięcioprocentowej zmiany urwisko, a to jest wykres,
    na podstawie którego sprzedaje się auto."""
    auto_id = _auto()
    _historia(auto_id, [(1000, 500.0)] * 18 + [(1000, 1100.0)] * 6)
    strona = pomoce.zbuduj_strone()
    wykres = utils.wykres_kosztu_1000km(strona.page, db.koszt_na_1000km(auto_id, 12))

    czart = wykres.controls[0].content
    assert czart.min_y == 0
    assert czart.max_y > 800
    # Cztery serie danych (razem + trzy kategorie) plus przerywana średnia.
    assert len(czart.data_series) == 5
    assert any(s.dash_pattern for s in czart.data_series), "brak linii odniesienia"


def test_karta_mowi_o_braku_danych_i_o_drozeniu(baza):
    strona = pomoce.zbuduj_strone()
    pusta = utils.karta_kosztu_1000km(strona.page, db.koszt_na_1000km(_auto("Goły"), 12))
    assert any("Za mało danych" in t for t in _teksty(pusta))

    auto_id = _auto()
    _historia(auto_id, [(1000, 500.0)] * 18 + [(1000, 1100.0)] * 6)
    karta = utils.karta_kosztu_1000km(strona.page, db.koszt_na_1000km(auto_id, 12))
    teksty = _teksty(karta)

    assert any("Ostatnie 12 mies." in t for t in teksty)
    assert any("DROŻEJ" in t for t in teksty)
    assert any("Najdroższe okno" in t for t in teksty)


def test_kafelek_kokpitu_pokazuje_cene_jazdy(baza):
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    stan.zakladka = 0
    db.zapisz_widgety_kokpitu(["koszt_1000km"], stan.auto_id)
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(), stan)

    assert "koszt_1000km" in widok._kokpit_budowniczy
    assert any("Koszt / 1000 km" in t for t in _teksty(widok.kokpit_kontener))


# ------------------------------------------------- obserwacja, rok, porównanie

def test_obserwacja_mowi_ze_auto_drozeje(baza):
    """Zdanie w Obserwacjach to miejsce, w którym aplikacja mówi „sprzedaj”
    bez wchodzenia w wykresy."""
    auto_id = _auto()
    _historia(auto_id, [(1000, 500.0)] * 18 + [(1000, 1100.0)] * 6)
    klucze = {o["klucz"] for o in db.obserwacje_analityczne(auto_id)}

    assert "drozeje_1000km" in klucze

    tanie = _auto("Tanie")
    _historia(tanie, [(1000, 900.0)] * 18 + [(1000, 400.0)] * 6)
    klucze_tanie = {o["klucz"] for o in db.obserwacje_analityczne(tanie)}
    assert "tanieje_1000km" in klucze_tanie and "drozeje_1000km" not in klucze_tanie


def test_stabilne_auto_nie_dostaje_zadnej_obserwacji(baza):
    """Cisza jest lepsza niż „wszystko w normie” przy każdym uruchomieniu."""
    auto_id = _auto()
    _historia(auto_id, [(1000, 500.0)] * 24)
    klucze = {o["klucz"] for o in db.obserwacje_analityczne(auto_id)}

    assert "drozeje_1000km" not in klucze and "tanieje_1000km" not in klucze


def test_rok_w_pigulce_liczy_cene_jazdy(baza):
    """Kwota rok do roku rośnie też wtedy, gdy jeździsz więcej — stąd druga
    liczba, liczona przez dystans."""
    auto_id = _auto()
    _historia(auto_id, [(1000, 500.0)] * 30)
    rok = date.today().year
    d = db.podsumowanie_roku(auto_id, rok)

    assert d["koszt_1000km"] == 500.0
    assert d["km_poprzedni"]
    assert d["koszt_1000km_poprzedni"] == 500.0
    assert d["zmiana_1000km"] == 0.0


def test_porownanie_pojazdow_zna_biezace_okno(baza):
    """Koszt z całego życia porównuje auta tak, jakby oba stały w tym samym
    miejscu historii; okno porównuje je dziś."""
    auto_id = _auto()
    _historia(auto_id, [(1000, 500.0)] * 18 + [(1000, 1100.0)] * 6)
    dane = db.pobierz_dane_do_porownania(auto_id)

    assert dane["koszt_1000km_okno"] == 800.0
    assert dane["okno_1000km"] == db.OKNO_1000KM_DOMYSLNE
