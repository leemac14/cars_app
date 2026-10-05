"""Ekran „Co nowego” (M-19): wydania, wersja aplikacji, start po aktualizacji.

Trzy rzeczy muszą się zgadzać naraz, a żadna nie krzyczy, gdy się rozjedzie:

* **lista wydań** (db/nowosci.py) — numer wersji to data, najnowsze na górze,
  każdy „Pokaż” prowadzi do ekranu z rejestru, a `pyproject.toml` niesie tę
  samą wersję, którą Android pokaże w informacjach o aplikacji;
* **start** — telefon bez zapamiętanej wersji odgaduje ją ze schematu bazy
  sprzed migracji, świeża instalacja nie widzi nic, a ekran otwiera się sam
  dokładnie raz;
* **urządzenie, nie dane** — wczytanie kopii z drugiego telefonu nie podmienia
  tego, co ten telefon już pokazał.
"""

import asyncio
import os
import pathlib
import re
import tomllib

import flet as ft
import pytest

import audyty
import db
import pomoce
import probki_baz
import utils


KORZEN = pathlib.Path(__file__).resolve().parent.parent
WERSJA = db.WERSJA_APLIKACJI

# Oczekiwania niżej opisują listę wydań z 5 października 2026 (najnowsze:
# 2026.10.5). Każda kolejna funkcja dokłada wydanie NA GÓRZE listy, więc te
# dopisane później stoją przed nimi — bez tego każde nowe wydanie oblewało
# sześć testów, które nie mówią nic o nim samym.
NOWSZE = [w["wersja"] for w in db.NOWOSCI if db.klucz_wersji(w["wersja"]) > db.klucz_wersji("2026.10.5")]

# Ten sam wzorzec, co w test_jednostka_dystansu.py: ekran w milach nie może
# pokazać samotnego „km”, a historia zmian jest tekstem jak każdy inny.
SAMOTNE_KM = re.compile(r"(?<![\w/])km(?![\w/])")
WZOR_WERSJI = re.compile(r"^[1-9]\d{3}\.[1-9]\d?\.[1-9]\d?(\.[2-9]|\.[1-9]\d+)?$")
KLUCZE_WYDANIA = {"wersja", "schemat", "pozycje"}
KLUCZE_POZYCJI = {"tytul", "opis", "ekran", "ikona"}


def _kontrolki(korzen):
    wynik, do_odwiedzenia = [], [korzen]
    while do_odwiedzenia:
        biezaca = do_odwiedzenia.pop(0)
        wynik.append(biezaca)
        do_odwiedzenia.extend(dziecko for _, dziecko in audyty._dzieci(biezaca))
        if isinstance(biezaca, ft.View) and biezaca.appbar is not None:
            do_odwiedzenia.append(biezaca.appbar)
    return wynik


def _teksty(korzen):
    return [k.value for k in _kontrolki(korzen) if isinstance(k, ft.Text) and k.value]


def _przyciski_pokaz(widok):
    """{tytuł pozycji: przycisk „Pokaż”} — po karcie, w której przycisk stoi."""
    wynik = {}
    for karta in _kontrolki(widok):
        if not isinstance(karta, ft.Row) or len(karta.controls) != 2:
            continue
        kolumna = karta.controls[1]
        if not isinstance(kolumna, ft.Column) or not kolumna.controls:
            continue
        tytul = kolumna.controls[0]
        if not isinstance(tytul, ft.Text):
            continue
        for k in _kontrolki(kolumna):
            if isinstance(k, ft.TextButton) and k.content == "Pokaż":
                wynik[tytul.value] = k
    return wynik


def _widok(stan, wolno_wejsc=None):
    from views.co_nowego_view import CoNowegoView

    strona = pomoce.zbuduj_strone()
    strona.page.on_route_change = lambda e: None
    return strona, CoNowegoView(strona.page, stan, wolno_wejsc=wolno_wejsc)


def _wersje(wydania):
    return [w["wersja"] for w in wydania]


# ======================================================= lista wydań

def test_wersja_aplikacji_to_najnowsze_wydanie_a_numery_sa_datami():
    assert WERSJA == db.NOWOSCI[0]["wersja"]
    klucze = [db.klucz_wersji(w["wersja"]) for w in db.NOWOSCI]
    assert klucze == sorted(klucze, reverse=True) and len(set(klucze)) == len(klucze), \
        "wydania od najnowszego, bez powtórzeń"
    for wydanie in db.NOWOSCI:
        # Bez zer wiodących: „2026.10.05” to dla Androida inny napis niż „2026.10.5”.
        assert WZOR_WERSJI.match(wydanie["wersja"]), wydanie["wersja"]
        assert db.data_wydania(wydanie["wersja"]) is not None, wydanie["wersja"]


def test_pyproject_niesie_te_sama_wersje_i_nic_wiecej():
    """`flet build apk` bierze stąd wersję widoczną w Androidzie. `name`
    i `dependencies` zmieniłyby nazwę paczki i źródło zależności buildu."""
    with open(KORZEN / "pyproject.toml", "rb") as plik:
        projekt = tomllib.load(plik)["project"]
    assert projekt == {"version": WERSJA}, (
        f"pyproject.toml ma [project] {projekt}, a najnowsze wydanie w db/nowosci.py to {WERSJA} — "
        "nowe wydanie zmienia oba miejsca naraz"
    )


def test_pozycje_sa_kompletne_i_prowadza_do_istniejacych_ekranow():
    for wydanie in db.NOWOSCI:
        assert set(wydanie) <= KLUCZE_WYDANIA, wydanie["wersja"]
        assert wydanie["pozycje"], f"{wydanie['wersja']}: wydanie bez pozycji"
        for pozycja in wydanie["pozycje"]:
            gdzie = f"{wydanie['wersja']} / {pozycja.get('tytul')}"
            assert set(pozycja) <= KLUCZE_POZYCJI, gdzie
            assert pozycja["tytul"].strip() and pozycja["opis"].strip(), gdzie
            assert not SAMOTNE_KM.search(pozycja["tytul"] + " " + pozycja["opis"]), \
                f"{gdzie}: samotne „km” — w milach ekran pokazałby złą jednostkę"
            if pozycja.get("ikona"):
                assert hasattr(ft.Icons, pozycja["ikona"]), gdzie
            if pozycja.get("ekran"):
                ekran = utils.EKRANY_WG_ID.get(pozycja["ekran"])
                assert ekran, f"{gdzie}: nie ma ekranu {pozycja['ekran']!r} w utils.EKRANY"
                assert ekran.get("trasa") or ekran.get("zakladka") is not None, \
                    f"{gdzie}: „Pokaż” prowadzi tylko do ekranu z trasą albo zakładką, nie do akcji"


def test_schemat_wydan_rosnie_razem_z_wydaniami(baza):
    progi = [w["schemat"] for w in reversed(db.NOWOSCI) if "schemat" in w]
    assert progi == sorted(progi)
    assert progi[-1] <= db.wersja_schematu_aplikacji()


def test_klucz_wersji_porownuje_liczby_a_nie_napisy():
    k = db.klucz_wersji
    assert k("2026.9.30") < k("2026.10.1") < k("2026.10.5") < k("2026.10.5.2") < k("2026.10.6")
    assert k(None) == k("") == k("dziwne") == k(db.WERSJA_ZEROWA) == (0,)
    assert db.data_wydania("2026.10.5.2").isoformat() == "2026-10-05"
    assert db.data_wydania("2026.13.1") is None and db.data_wydania("7") is None


def test_wydania_po_wersji():
    assert _wersje(db.wydania_po(WERSJA)) == []
    assert _wersje(db.wydania_po(None)) == _wersje(db.NOWOSCI)
    assert _wersje(db.wydania_po("2026.10.3")) == NOWSZE + ["2026.10.5", "2026.10.4"]
    # Wersja, której nie ma na liście (np. wydanie skasowane), też działa jak próg.
    assert _wersje(db.wydania_po("2026.10.2")) == NOWSZE + ["2026.10.5", "2026.10.4", "2026.10.3"]


# ======================================================= odgadnięcie startu

@pytest.mark.parametrize("schemat, oczekiwana", [
    (38, None), (39, None), (40, "2026.9.7"), (41, "2026.9.15"), (42, "2026.9.24"),
    (43, "2026.9.24"), (44, "2026.9.26"), (45, "2026.9.29"), (46, "2026.9.30"),
    (47, "2026.10.3"), (48, "2026.10.4"), ("cokolwiek", None), (None, None),
])
def test_wersja_dla_schematu(schemat, oczekiwana):
    """Telefon ze schematem 46 ma kolejkę paragonów, ale mógł nie mieć Miesiąca
    w pigułce (przyszedł po migracji tego samego dnia) — dostaje oba."""
    assert db.wersja_dla_schematu(schemat) == oczekiwana


def test_przygotowanie_po_starcie(baza):
    # Świeża instalacja: nic nie jest zmianą.
    assert db.przygotuj_nowosci_po_starcie(0) == WERSJA
    assert db.niewidziane_wydania() == [] and not db.czy_pokazac_nowosci_po_starcie()

    # Zapamiętanej wersji start nie rusza — nawet z innym schematem.
    assert db.przygotuj_nowosci_po_starcie(40) == WERSJA

    db.usun_ustawienie(db.KLUCZ_NOWOSCI_WIDZIANE)
    assert db.przygotuj_nowosci_po_starcie(46) == "2026.9.30"
    assert _wersje(db.niewidziane_wydania()) == NOWSZE + ["2026.10.5", "2026.10.4", "2026.10.3", "2026.10.1"]
    assert db.liczba_niewidzianych_wydan() == len(NOWSZE) + 4 and db.czy_pokazac_nowosci_po_starcie()

    # Bazy nie dało się przeczytać przed migracjami — lepiej wszystko niż nic.
    db.usun_ustawienie(db.KLUCZ_NOWOSCI_WIDZIANE)
    assert db.przygotuj_nowosci_po_starcie(None) == db.WERSJA_ZEROWA
    assert len(db.niewidziane_wydania()) == len(db.NOWOSCI)

    # Schemat starszy od wszystkich wydań — też wszystko.
    db.usun_ustawienie(db.KLUCZ_NOWOSCI_WIDZIANE)
    assert db.przygotuj_nowosci_po_starcie(30) == db.WERSJA_ZEROWA


def test_baza_bez_startu_niczego_nie_zglasza(baza):
    """Brak klucza znaczy bazę, przez którą start nie przeszedł — bez odznaki
    i bez otwierania."""
    assert db.pobierz_widziana_wersje() is None
    assert db.niewidziane_wydania() == [] and db.liczba_niewidzianych_wydan() == 0
    assert not db.czy_pokazac_nowosci_po_starcie()


def test_oznaczenie_widzianych_nigdy_nie_cofa_wersji(baza):
    db.zapisz_widziana_wersje("2026.9.7")
    db.oznacz_nowosci_jako_widziane()
    assert db.pobierz_widziana_wersje() == WERSJA

    db.zapisz_widziana_wersje("2099.1.1")  # telefon miał już nowszą aplikację
    db.oznacz_nowosci_jako_widziane()
    assert db.pobierz_widziana_wersje() == "2099.1.1"


def test_przelacznik_wylacza_tylko_otwieranie_samo(baza):
    db.zapisz_widziana_wersje("2026.10.3")
    db.zapisz_pokazywanie_nowosci_po_aktualizacji(False)
    assert not db.czy_pokazywac_nowosci_po_aktualizacji()
    assert not db.czy_pokazac_nowosci_po_starcie()
    assert db.liczba_niewidzianych_wydan() == len(NOWSZE) + 2, "odznaka w menu zostaje"


# ======================================================= start aplikacji (main.py)

@pytest.fixture
def uruchom(monkeypatch):
    """main.main() na świeżej stronie testowej; zwraca stronę."""
    monkeypatch.setattr(ft, "run", lambda *args, **kwargs: None)
    import log
    import main

    monkeypatch.setattr(log, "wlacz", lambda: True)
    monkeypatch.setitem(utils.wyglad._OSTATNI_MOTYW, "nazwa", utils.wyglad._OSTATNI_MOTYW["nazwa"])

    def _uruchom():
        strona = pomoce.zbuduj_strone()
        monkeypatch.setattr(type(strona.page), "run_task", lambda self, f, *a, **k: None)
        main.main(strona.page)
        return strona

    return _uruchom


def _stos(page):
    return [type(w).__name__ for w in page.views]


def test_start_po_aktualizacji_otwiera_co_nowego_raz(baza, uruchom):
    pomoce.utworz_pojazd("Po aktualizacji")
    db.zapisz_widziana_wersje("2026.10.3")

    strona = uruchom()
    assert _stos(strona.page) == ["MainView", "CoNowegoView"]
    assert strona.page.route == "/co-nowego"
    widok = strona.page.views[-1]
    assert widok.nowe == {"2026.10.5", "2026.10.4", *NOWSZE}
    assert db.pobierz_widziana_wersje() == WERSJA, "otwarcie = widziane"

    # Przebudowa ekranu przez router nie gasi plakietek w pół czytania.
    utils.przejdz(strona.page, "/co-nowego")
    assert strona.page.views[-1].nowe == {"2026.10.5", "2026.10.4", *NOWSZE}

    assert _stos(uruchom().page) == ["MainView"], "drugi start — już nic"


def test_start_ze_starej_bazy_odgaduje_wersje_po_schemacie(magazyn, uruchom):
    """Telefon drugiej osoby: baza ze schematem 43 (sprzed rozliczeń), bez
    zapamiętanej wersji. Po migracjach widzi wydania od 25 września."""
    probki_baz.odtworz_z_probki(probki_baz.KATALOG_PROBEK / probki_baz.nazwa_probki(43), db.BAZA_DANYCH)

    strona = uruchom()
    assert _stos(strona.page)[-1] == "CoNowegoView"
    nowe = strona.page.views[-1].nowe
    assert "2026.9.25" in nowe and "2026.9.24" not in nowe
    assert nowe == set(_wersje(db.wydania_po("2026.9.24")))


def test_swieza_instalacja_nie_pokazuje_niczego(magazyn, uruchom):
    assert not os.path.exists(db.BAZA_DANYCH)
    strona = uruchom()
    assert _stos(strona.page) == ["MainView"]
    assert db.pobierz_widziana_wersje() == WERSJA


def test_wylaczone_otwieranie_samo_zostawia_kokpit(baza, uruchom):
    db.zapisz_widziana_wersje("2026.10.3")
    db.zapisz_pokazywanie_nowosci_po_aktualizacji(False)
    assert _stos(uruchom().page) == ["MainView"]
    assert db.pobierz_widziana_wersje() == "2026.10.3", "niewidziane czekają na otwarcie"


def test_router_chowa_pokaz_przy_roli_podgladu(baza, uruchom):
    """Kolejka paragonów zakłada szkice — podgląd i tak by do niej nie wszedł,
    a do warsztatów owszem."""
    pomoce.przygotuj_scenariusz("wspoldzielony_podglad")
    strona = uruchom()
    utils.przejdz(strona.page, "/co-nowego")
    przyciski = _przyciski_pokaz(strona.page.views[-1])
    assert "Warsztaty" in przyciski and "Paragon na później" not in przyciski
    assert "Import z innych aplikacji" not in przyciski


# ======================================================= ekran

def test_ekran_podswietla_nowe_i_zapisuje_widziane(baza):
    db.zapisz_widziana_wersje("2026.10.3")
    stan = pomoce.stan_aplikacji()

    _, widok = _widok(stan)
    teksty = _teksty(widok)
    assert "Co się zmieniło od Twojej poprzedniej wersji" in teksty
    assert teksty.count("Nowe") == len(NOWSZE) + 2
    assert teksty.count("Wcześniej — to ten telefon już widział") == 1
    ile = sum(len(w["pozycje"]) for w in db.wydania_po("2026.10.3"))
    assert any(t.startswith(f"{ile} nowości · teraz wersja {WERSJA}") for t in teksty), teksty
    assert db.pobierz_widziana_wersje() == WERSJA and stan.nowosci_od == "2026.10.3"

    # Ten sam stan (ta sama sesja) — dalej te same plakietki.
    _, widok = _widok(stan)
    assert _teksty(widok).count("Nowe") == len(NOWSZE) + 2

    # Nowa sesja: wszystko widziane, zostaje historia zmian.
    _, widok = _widok(pomoce.stan_aplikacji())
    teksty = _teksty(widok)
    assert "Historia zmian" in teksty and "Nowe" not in teksty
    assert "Wcześniej — to ten telefon już widział" not in teksty
    tytuly = {p["tytul"] for w in db.NOWOSCI for p in w["pozycje"]}
    assert tytuly <= set(teksty), "każda pozycja na ekranie"


def test_pokaz_prowadzi_do_ekranu_albo_zakladki(baza):
    dane = pomoce.utworz_pojazd("Pokazowy")
    stan = pomoce.stan_aplikacji(dane["auto_id"], "Pokazowy")
    strona, widok = _widok(stan)
    przyciski = _przyciski_pokaz(widok)

    przyciski["Warsztaty"].on_click(None)
    assert strona.page.route == "/warsztaty"

    przyciski["Kolorowe tagi"].on_click(None)
    assert strona.page.route == "/" and (stan.zakladka, stan.koszty_podzakladka) == (2, 1)

    przyciski["Checklisty"].on_click(None)
    assert strona.page.route == "/do-zrobienia" and stan.do_zrobienia_podzakladka == 1


def test_pokaz_znika_tam_gdzie_nie_wpuszcza(baza):
    dane = pomoce.utworz_pojazd("Pilnowany")
    stan = pomoce.stan_aplikacji(dane["auto_id"], "Pilnowany")
    _, widok = _widok(stan, wolno_wejsc=lambda trasa: trasa != "/do-wpisania")
    przyciski = _przyciski_pokaz(widok)
    assert "Paragon na później" not in przyciski and "Warsztaty" in przyciski
    assert "Szybszy kokpit" not in przyciski, "pozycja bez ekranu nie ma dokąd prowadzić"
    assert "Menu boczne › Koszty › Do wpisania" in _teksty(widok), "„gdzie to jest” zostaje"

    # Bez pojazdu — tylko ekrany, które go nie wymagają.
    _, widok = _widok(pomoce.stan_aplikacji())
    przyciski = _przyciski_pokaz(widok)
    assert {"Archiwum sprzedanych aut", "Wyślij log"} <= set(przyciski)
    assert "Warsztaty" not in przyciski


def test_gotowe_wraca_na_kokpit_tylko_po_aktualizacji(baza):
    db.zapisz_widziana_wersje("2026.10.4")
    strona, widok = _widok(pomoce.stan_aplikacji())
    gotowe = [k for k in _kontrolki(widok) if isinstance(k, ft.FilledButton)]
    assert len(gotowe) == 1
    strona.page.route = "/co-nowego"
    gotowe[0].on_click(None)
    assert strona.page.route == "/"

    _, widok = _widok(pomoce.stan_aplikacji())
    assert not [k for k in _kontrolki(widok) if isinstance(k, ft.FilledButton)]


# ======================================================= menu, wyszukiwarka, Ustawienia

def test_odznaka_w_menu_do_otwarcia_ekranu(baza):
    dane = pomoce.utworz_pojazd("Z odznaką")
    db.zapisz_widziana_wersje("2026.10.3")
    assert db.liczniki_nawigacji(dane["auto_id"]).get("co-nowego") == len(NOWSZE) + 2

    _widok(pomoce.stan_aplikacji(dane["auto_id"], "Z odznaką"))
    assert "co-nowego" not in db.liczniki_nawigacji(dane["auto_id"])


def test_ekran_w_rejestrze_i_wyszukiwarce():
    ekran = utils.EKRANY_WG_ID["co-nowego"]
    assert ekran["trasa"] == "/co-nowego" and ekran["wymaga_pojazdu"] is False
    assert utils.EKRANY_WG_SEGMENTU["co-nowego"] == "co-nowego"
    for fraza in ("co nowego", "nowości", "historia zmian", "aktualizacja"):
        assert "co-nowego" in [e["id"] for e in utils.znajdz_ekrany(fraza)], fraza


def test_karta_o_aplikacji_i_naglowek_logu(baza):
    stan = pomoce.stan_aplikacji()
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["UstawieniaView"], pomoce.zbuduj_strone(), stan)
    teksty = _teksty(widok)
    assert f"O aplikacji · wersja {WERSJA}" in teksty and f"Wersja {WERSJA}" in teksty
    assert "Wydana " + utils.formatuj_date_pl(db.data_wydania(WERSJA)) in teksty

    assert widok.e_nowosci.value is True
    widok.e_nowosci.value = False
    widok.e_nowosci.on_change(None)
    assert not db.czy_pokazywac_nowosci_po_aktualizacji()

    assert widok._naglowek_logu()["Wersja aplikacji"] == WERSJA


# ======================================================= urządzenie, nie dane

def test_wczytanie_kopii_nie_podmienia_widzianej_wersji(baza, tmp_path):
    """Kopia z drugiego telefonu przynosi jego `nowosci_*` — po wczytaniu
    zostają te z tego urządzenia, łącznie z brakiem klucza."""
    pomoce.utworz_pojazd("Z kopii")
    obca = tmp_path / "obca.db"
    db.zapisz_widziana_wersje("2026.9.7")
    db.zapisz_pokazywanie_nowosci_po_aktualizacji(False)
    db.skopiuj_baze(db.BAZA_DANYCH, str(obca))

    db.zapisz_widziana_wersje(WERSJA)
    db.usun_ustawienie(db.KLUCZ_NOWOSCI_PO_AKTUALIZACJI)
    przed = db.ustawienia_kopii_urzadzenia()
    assert przed.get(db.KLUCZ_NOWOSCI_WIDZIANE) == WERSJA

    db.skopiuj_baze(str(obca), db.BAZA_DANYCH)
    db.init_db()
    db.przywroc_ustawienia_kopii_urzadzenia(przed)

    assert db.pobierz_widziana_wersje() == WERSJA
    assert db.czy_pokazywac_nowosci_po_aktualizacji(), "klucza nie było — wraca domyślny"
    assert db.niewidziane_wydania() == []


def test_wczytanie_kopii_przez_aplikacje_nie_otwiera_nowosci(baza, uruchom, monkeypatch):
    """Cała droga z menu Ustawień: kopia sprzed miesiąca nie przynosi „nowości”."""
    komunikaty = []
    monkeypatch.setattr(utils, "pokaz_ladowanie", lambda page, tekst="": None)
    monkeypatch.setattr(utils, "ukryj_ladowanie", lambda page, dlg: None)
    monkeypatch.setattr(utils, "pokaz_komunikat", lambda page, tekst, *a, **k: komunikaty.append(tekst))
    pomoce.utworz_pojazd("Kopiowany")
    db.zapisz_widziana_wersje("2026.9.7")
    kopia = db.wykonaj_kopie()["sciezka"]
    db.zapisz_widziana_wersje(WERSJA)

    strona = uruchom()
    asyncio.run(strona.page.wczytaj_kopie(kopia))

    assert komunikaty and komunikaty[-1].startswith("Pomyślnie wczytano bazę!"), komunikaty
    assert db.pobierz_widziana_wersje() == WERSJA
    assert _stos(strona.page) == ["MainView"]
