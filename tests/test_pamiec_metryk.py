"""Pamięć metryk kokpitu (U-24): liczone raz, trzymane do najbliższego zapisu.

Kokpit pytał bazę kafelek po kafelku przy każdej przebudowie — z kompletem
kafelków ponad sto wejść do bazy, a na ekran główny wraca się po każdej
czynności. Teraz metryki trzyma pamięć pod kluczem: metryka + pojazd +
znacznik ostatniej zmiany danych + dzień (db/pamiec.py, db/kokpit.py).

Pamięć jest warta tyle, co jej unieważnianie, więc większość tego pliku
pilnuje granic:

* zapis zmieniający choć jeden wiersz czyści pamięć — także podmiana całego
  pliku przy wczytaniu kopii zapasowej, która idzie z pominięciem polacz_baze;
* zapis pamięci interfejsu (ostatnio używane ekrany, pozycja startowa, układ
  kafelków, historia wyszukiwania) NIE czyści — router zapisuje „byłem tu”
  przy każdym przejściu i wyłączałby pamięć po cichu;
* nowy dzień czyści, bo terminy i miesiące przesuwają się same;
* znacznik rośnie PO zatwierdzeniu zapisu, a wynik liczony w trakcie cudzego
  zapisu nie trafia do pamięci.
"""

import copy
import shutil
import sqlite3
from datetime import date, datetime, timedelta

import pytest

import db
import pomoce
import utils
from conftest import _moduly_aplikacji


def _licznik_wywolan(monkeypatch, nazwa):
    """Funkcja danych podmieniona we WSZYSTKICH modułach (`from .x import y`
    kopiuje wiązanie) na wersję, która zapisuje każde wywołanie."""
    oryginal = getattr(db, nazwa)
    wywolania = []

    def licz(*a, **k):
        wywolania.append(a)
        return oryginal(*a, **k)

    for modul in _moduly_aplikacji():
        if getattr(modul, nazwa, None) is oryginal:
            monkeypatch.setattr(modul, nazwa, licz)
    return wywolania


def _licznik_liczenia(monkeypatch, modul, nazwa):
    """Liczy faktyczne LICZENIE (prywatną funkcję za pamięcią), a nie pytania —
    publiczna funkcja bywa wołana wiele razy i za każdym razem trafia w pamięć."""
    oryginal = getattr(modul, nazwa)
    wywolania = []

    def licz(*a, **k):
        wywolania.append(a)
        return oryginal(*a, **k)

    monkeypatch.setattr(modul, nazwa, licz)
    return wywolania


def _ekran_glowny(stan, zakladka=0):
    stan.zakladka = zakladka
    strona = pomoce.zbuduj_strone()
    strona.page.on_route_change = lambda e=None: None
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], strona, stan)
    widok._strona_testowa = strona   # sesja strony wisi na słabej referencji
    return widok


def _komplet_kafelkow(scenariusz="pojazd_z_historia"):
    stan, _ = pomoce.przygotuj_scenariusz(scenariusz)
    db.zapisz_chowanie_pustych_kafelkow(False)
    db.zapisz_widgety_kokpitu(list(db.KOKPIT_WIDGETY), stan.auto_id)
    return stan


def _dopisz_oplate_drogowa(auto_id, kwota=35.0):
    with db.polacz_baze() as conn:
        conn.execute(
            "INSERT INTO inne_koszty (auto_id, data, kategoria, nazwa, kwota) VALUES (?,?,?,?,?)",
            (auto_id, datetime.now().strftime("%d.%m.%Y"), db.KATEGORIA_INNE_DROGOWE, "Bramka", kwota),
        )


# ============================================================================
#  PAMIĘĆ DZIAŁA
# ============================================================================

def test_powrot_na_ekran_glowny_bierze_metryki_z_pamieci(baza, monkeypatch):
    """Sedno U-24: drugie i każde następne wejście bez zapisu po drodze nie
    liczy żadnej metryki. Przy jednym wejściu kondycję liczyły dotąd osobno
    kafelek, nagłówek pojazdu i porównanie, a listę powiadomień — kafelek
    „Termin”, dzwonek, porównanie i każda z tych kondycji."""
    stan = _komplet_kafelkow()
    kondycja = _licznik_liczenia(monkeypatch, db.statystyki, "_policz_rozbicie_kondycji")
    powiadomienia = _licznik_liczenia(monkeypatch, db.powiadomienia, "_policz_powiadomienia")
    obserwacje = _licznik_wywolan(monkeypatch, "obserwacje_analityczne")

    _ekran_glowny(stan)
    po_pierwszym = (len(kondycja), len(powiadomienia), len(obserwacje))
    assert po_pierwszym[0] == 1, "kondycja liczona raz na całe wejście"
    # Raz lista bieżąca (kafelek, dzwonek, porównanie), raz z odłożonymi (kondycja).
    assert sorted(a[3] for a in powiadomienia) == [False, True]

    for zakladka in (0, 1, 2, 3, 0):
        _ekran_glowny(stan, zakladka)
    assert (len(kondycja), len(powiadomienia), len(obserwacje)) == po_pierwszym

    # Zapis danych — następne wejście liczy wszystko od nowa, ale znowu tylko
    # raz: dokładnie tyle, co pierwsze.
    _dopisz_oplate_drogowa(stan.auto_id)
    _ekran_glowny(stan)
    assert (len(kondycja), len(powiadomienia), len(obserwacje)) == tuple(2 * n for n in po_pierwszym)


def test_zapis_danych_zmienia_liczbe_na_kafelku(baza):
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    przed = db.metryki_kokpitu(stan.auto_id, ["oplaty_drogowe"])["oplaty_drogowe"]

    _dopisz_oplate_drogowa(stan.auto_id, 35.0)

    po = db.metryki_kokpitu(stan.auto_id, ["oplaty_drogowe"])["oplaty_drogowe"]
    assert po["liczba"] == przed["liczba"] + 1
    assert po["suma"] == pytest.approx(przed["suma"] + 35.0)


def test_odznaki_nawigacji_z_pamieci_do_zapisu(baza, monkeypatch):
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    kosz = _licznik_wywolan(monkeypatch, "liczba_w_koszu")
    przed = db.liczniki_nawigacji(stan.auto_id)
    db.liczniki_nawigacji(stan.auto_id)
    assert len(kosz) == 1, "drugie pytanie o odznaki bez zapisu po drodze nie liczy ich od nowa"

    with db.polacz_baze() as conn:
        conn.execute("INSERT INTO do_zrobienia (auto_id, tytul, wykonane) VALUES (?, ?, 0)",
                     (stan.auto_id, "Wymienić wycieraczki"))

    assert db.liczniki_nawigacji(stan.auto_id).get("do-zrobienia", 0) == przed.get("do-zrobienia", 0) + 1


def test_pamiec_wydaje_kopie(baza):
    """Ekran, który zmieni otrzymaną listę w miejscu, nie może po cichu zmienić
    liczb, które pamięć wyda następnemu."""
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    pierwsze = db.metryki_kokpitu(stan.auto_id, ["termin", "wykres"])
    wzor = copy.deepcopy(pierwsze)

    pierwsze["powiadomienia"].clear()
    pierwsze["koszty_miesieczne"].append((1999, 1, 1.0))
    drugie = db.metryki_kokpitu(stan.auto_id, ["termin", "wykres"])
    drugie["powiadomienia"].clear()

    assert db.metryki_kokpitu(stan.auto_id, ["termin", "wykres"]) == wzor


# ============================================================================
#  CO UNIEWAŻNIA, A CO NIE
# ============================================================================

def test_pamiec_interfejsu_nie_czysci_metryk(baza):
    """Router zapisuje „ostatnio używane” i pozycję startową przy KAŻDYM
    przejściu. Gdyby to czyściło pamięć, kokpit liczyłby się od nowa po każdym
    powrocie — i nikt by tego nie zauważył, bo liczby byłyby dobre."""
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    znacznik = db.znacznik_zmian_danych()

    utils.zanotuj_ekran_dla_trasy(stan, ["przebieg"])
    db.zanotuj_uzycie_ekranu("rok")
    db.zapamietaj_ostatnia_pozycje(stan.auto_id, 2)
    db.zapamietaj_podzakladke_kosztow(1)
    db.zapisz_widgety_kokpitu(["termin", "kondycja"], stan.auto_id)
    db.zapisz_widgety_kokpitu(["termin"])
    db.przywroc_kokpit_wspolny(stan.auto_id)
    db.zanotuj_wyszukiwanie("olej")
    db.wyczysc_ostatnie_wyszukiwania()
    assert db.znacznik_zmian_danych() == znacznik

    db.zapisz_ustawienie("waluta", "EUR")
    assert db.znacznik_zmian_danych() > znacznik


def test_klucze_interfejsu_zgodne_z_ich_wlascicielami():
    """Klucze pamięci interfejsu mieszkają w modułach późniejszych niż
    ustawienia, więc lista trzyma je jako napisy — ten test pilnuje zgodności."""
    assert db.KLUCZ_HISTORII_WYSZUKIWAN in db.USTAWIENIA_INTERFEJSU
    assert db.ustawienie_interfejsu(db.ustawienia._klucz_kokpitu(7))
    assert db.ustawienie_interfejsu(db.ustawienia._klucz_kokpitu(None))
    for klucz in ("waluta", "jednostka_dystansu", "prog_dni_powiadomien", "chowaj_puste_kafelki"):
        assert not db.ustawienie_interfejsu(klucz), klucz


def test_zapis_ktory_nic_nie_zmienil_nie_czysci_pamieci(baza):
    """„Zapisz” w Ustawieniach bez żadnej zmiany i UPDATE, który nic nie trafił,
    nie zmieniają żadnego wiersza — i żadnej liczby na ekranie."""
    db.zapisz_ustawienie("waluta", "EUR")
    znacznik = db.znacznik_zmian_danych()

    db.zapisz_ustawienie("waluta", "EUR")
    with db.polacz_baze() as conn:
        conn.execute("UPDATE samochody SET nazwa = 'nikt' WHERE id = -1")
    assert db.znacznik_zmian_danych() == znacznik

    db.zapisz_ustawienie("waluta", "PLN")
    assert db.znacznik_zmian_danych() == znacznik + 1


def test_nowy_dzien_liczy_metryki_od_nowa(baza, monkeypatch):
    """Dni do przeglądu, bieżący miesiąc i „po terminie” zmieniają się o północy
    same, bez żadnego zapisu."""
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    kondycja = _licznik_wywolan(monkeypatch, "oblicz_kondycje_pojazdu")

    db.metryka_kokpitu(stan.auto_id, "kondycja")
    db.metryka_kokpitu(stan.auto_id, "kondycja")
    assert len(kondycja) == 1

    jutro = date.today() + timedelta(days=1)
    monkeypatch.setattr(db.pamiec, "_dzien", lambda: jutro)
    db.metryka_kokpitu(stan.auto_id, "kondycja")
    assert len(kondycja) == 2


def test_wczytanie_kopii_zapasowej_czysci_pamiec(baza, tmp_path):
    """Import kopii (main.wykonaj_import) kopiuje plik bazy z pominięciem
    polacz_baze, a kopia już zmigrowana nie zapisze w init_db ani jednego
    wiersza. Bez wprost podbitego znacznika kokpit pokazywałby liczby ze
    starego pliku aż do pierwszego zapisu."""
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    kopia = tmp_path / "kopia.db"
    shutil.copyfile(db.BAZA_DANYCH, kopia)

    _dopisz_oplate_drogowa(stan.auto_id)
    przed_wczytaniem = db.metryka_kokpitu(stan.auto_id, "oplaty_drogowe")

    shutil.copyfile(kopia, db.BAZA_DANYCH)
    db.init_db()

    po_wczytaniu = db.metryka_kokpitu(stan.auto_id, "oplaty_drogowe")
    assert po_wczytaniu["liczba"] == przed_wczytaniem["liczba"] - 1


def test_budowa_ekranu_glownego_nie_zapisuje_danych(baza):
    """Ukryty zapis w drodze budowania ekranu głównego (przeliczenie, porządki)
    unieważniałby pamięć przy każdym wejściu — i wyłączał ją bez śladu."""
    stan = _komplet_kafelkow()
    widok = _ekran_glowny(stan)          # pierwsze wejście może posprzątać
    znacznik = db.znacznik_zmian_danych()

    for zakladka in range(4):
        widok = _ekran_glowny(stan, zakladka)
    for zakladka in (0, 1, 2, 3, 0):
        widok.przelacz_zakladke(zakladka)
    widok.odswiez_w_miejscu()

    assert db.znacznik_zmian_danych() == znacznik


# ============================================================================
#  KOLEJNOŚĆ: NAJPIERW ZATWIERDZENIE, POTEM ZNACZNIK
# ============================================================================

def test_znacznik_rosnie_dopiero_po_zatwierdzeniu(baza, monkeypatch):
    """Kto zobaczy nowy znacznik, musi już widzieć nowe dane. Podbicie przed
    zatwierdzeniem pozwoliłoby ekranowi na innym wątku policzyć STARE liczby
    i zapamiętać je pod NOWYM kluczem — do następnego zapisu."""
    widziane = []
    oryginal = db.polaczenie.zanotuj_zmiane_danych

    def podgladaj():
        polaczenie = sqlite3.connect(db.BAZA_DANYCH)
        try:
            widziane.append(polaczenie.execute(
                "SELECT wartosc FROM ustawienia WHERE klucz='test_zatwierdzenia'").fetchone())
        finally:
            polaczenie.close()
        oryginal()

    monkeypatch.setattr(db.polaczenie, "zanotuj_zmiane_danych", podgladaj)
    przed = db.znacznik_zmian_danych()
    with db.polacz_baze() as conn:
        conn.execute("INSERT INTO ustawienia (klucz, wartosc) VALUES ('test_zatwierdzenia', 'tak')")
        assert db.znacznik_zmian_danych() == przed

    assert widziane == [("tak",)]
    assert db.znacznik_zmian_danych() == przed + 1


def test_wynik_liczony_w_trakcie_zapisu_nie_trafia_do_pamieci():
    """Nie wiadomo, czy taki wynik widział stan sprzed zapisu, czy po nim —
    następne wejście liczy go jeszcze raz."""
    wywolania = []

    def licz_w_trakcie_zapisu():
        wywolania.append(1)
        db.zanotuj_zmiane_danych()   # ktoś zapisał, zanim skończyliśmy liczyć
        return len(wywolania)

    assert db.z_pamieci("test:w_trakcie", 1, licz_w_trakcie_zapisu) == 1
    assert db.z_pamieci("test:w_trakcie", 1, licz_w_trakcie_zapisu) == 2

    def licz():
        wywolania.append(1)
        return len(wywolania)

    pierwszy = db.z_pamieci("test:spokojnie", 1, licz)
    assert db.z_pamieci("test:spokojnie", 1, licz) == pierwszy
    assert db.z_pamieci("test:spokojnie", 2, licz) != pierwszy, "inny pojazd to inny klucz"


# ============================================================================
#  KAŻDY KAFELEK MÓWI, CZEGO POTRZEBUJE
# ============================================================================

def test_kazdy_kafelek_ma_wpis_metryk():
    assert set(db.METRYKI_KAFELKOW) == set(db.KOKPIT_WIDGETY)
    nieznane = {m for metryki in db.METRYKI_KAFELKOW.values() for m in metryki} - set(db.METRYKI_KOKPITU)
    assert nieznane == set()


@pytest.mark.parametrize("scenariusz", ["pojazd_bez_danych", "pojazd_z_historia", "elektryk", "wspoldzielony_podglad"])
def test_kafelek_sam_na_kokpicie_ma_wszystko_czego_potrzebuje(baza, scenariusz):
    """Kafelek sięgający po metrykę spoza swojej listy działa tylko wtedy, gdy
    zamówił ją sąsiad — sam na kokpicie wywraca budowę ekranu (KeyError).
    Scenariusze, bo kafelki sięgają po metryki w różnych gałęziach: spalanie
    bez serii bierze średnią z porównania, elektryk ma zasięg EV."""
    stan = _komplet_kafelkow(scenariusz)
    widok = _ekran_glowny(stan)

    for wid in db.KOKPIT_WIDGETY:
        db.zapisz_widgety_kokpitu([wid], stan.auto_id)
        widok._zawartosc_kokpitu()
        assert set(widok._metryki_kokpitu) == set(db.METRYKI_KAFELKOW[wid]), wid
