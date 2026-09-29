"""Gwarancje na wykonane naprawy (M-06) — dwa limity przy wpisie historii.

Gwarancja na całe auto siedzi w terminach pojazdu, a gwarancja na część —
przy wpisie, który ją dał: `gwarancja_data` i `gwarancja_przebieg` (stan
licznika w km). Kończy ją to, co przyjdzie pierwsze. Liczy się tylko gwarancja
z OSTATNIEJ wymiany podzespołu — część z wcześniejszej w aucie już nie siedzi.

Psuje się tu osobno:
1. **Rachunek i słowa** — „gwarancja jeszcze 7 miesięcy” pełnymi miesiącami,
   oba limity, próg przypomnienia, duplikat przenoszący okres, a nie datę.
2. **Migracja, chmura, kosz** — nowe kolumny nie mogą zamienić pierwszej
   synchronizacji po aktualizacji w wysyłkę całej historii, a starszy telefon
   nie może skasować gwarancji wpisanej na nowszym.
3. **Formularze** — skróty trzymają się wymiany; wizyta ma gwarancję wspólną,
   a wyjątek przy pozycji przeżywa zapis wizyty.
4. **Gdzie ją widać** — karta wpisu, karta podzespołu, Karta pojazdu,
   „Ile zostało do…”, dzwonek i paszport PDF.
"""

import sqlite3
from datetime import date, timedelta

import flet as ft
import pytest

import db
import pomoce
import probki_baz
import sync
import utils
from date import na_iso
from sync import konflikty as sync_konflikty
from sync import pobieranie as sync_pobieranie
from sync import wysylanie as sync_wysylanie


DRABINKA = probki_baz.wczytaj_drabinke()
DZIS = date(2026, 9, 30)
KONFIG_HISTORII = next(k for k in sync.KONFIGURACJA_SYNC if k["tabela"] == "historia")


# ============================================================================
#  POMOCE
# ============================================================================

def dzien(dni):
    """Data przesunięta o `dni` od dzisiaj, tak jak zapisuje ją formularz."""
    return (date.today() + timedelta(days=dni)).strftime("%d.%m.%Y")


def po_miesiacach(tekst, miesiace):
    d = date(int(tekst[6:]), int(tekst[3:5]), int(tekst[:2]))
    return db.dodaj_miesiace(d, miesiace).strftime("%d.%m.%Y")


def ile_czasu(dni):
    """To, co karta powie o terminie za `dni` dni."""
    return db.czas_slownie(date.today(), date.today() + timedelta(days=dni))


def pojazd(nazwa="Gwarancyjny"):
    """Auto z dwoma podzespołami i odczytem licznika 150 000 km sprzed tygodnia."""
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO samochody (nazwa, typ_paliwa, status, rola_wspoldzielenia) VALUES (?,?,?,?)",
            (nazwa, "Benzyna", db.STATUS_POJAZDU_AKTYWNY, db.ROLA_WLASCICIEL),
        )
        auto = c.lastrowid
        zadania = []
        for nazwa_zadania in ("Klocki hamulcowe", "Akumulator"):
            c.execute("INSERT INTO zadania (auto_id, nazwa) VALUES (?,?)", (auto, nazwa_zadania))
            zadania.append(c.lastrowid)
        c.execute("INSERT INTO odczyty_przebiegu (auto_id, data, data_iso, przebieg, zrodlo) VALUES (?,?,?,?,?)",
                  (auto, dzien(-7), na_iso(dzien(-7)), 150000, "reczny"))
    return {"auto_id": auto, "klocki": zadania[0], "akumulator": zadania[1]}


def wpis(zadanie, data, przebieg, koniec=None, limit=None, wizyta=None, wykonawca="Warsztat u Janka"):
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO historia (zadanie_id, wizyta_id, data, data_iso, przebieg, cena, wykonawca, "
            "gwarancja_data, gwarancja_przebieg) VALUES (?,?,?,?,?,?,?,?,?)",
            (zadanie, wizyta, data, na_iso(data), przebieg, 200.0, wykonawca, koniec, limit),
        )
        h_id = c.lastrowid
    db.aktualizuj_najnowszy_wpis(zadanie)
    return h_id


def wizyta(auto, zadania, data, przebieg):
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO wizyty (auto_id, data, data_iso, przebieg, wykonawca, koszt_calkowity) "
                  "VALUES (?,?,?,?,?,?)", (auto, data, na_iso(data), przebieg, "AutoFix", 600.0))
        w_id = c.lastrowid
    for zadanie in zadania:
        wpis(zadanie, data, przebieg, wizyta=w_id, wykonawca="AutoFix")
    return w_id


def jeden(sql, parametry=()):
    with db.polacz_baze() as conn:
        wiersz = conn.execute(sql, parametry).fetchone()
    return wiersz[0] if wiersz and len(wiersz) == 1 else wiersz


def gwarancje_wizyty(w_id):
    with db.polacz_baze() as conn:
        return {z: (d, k) for z, d, k in conn.execute(
            "SELECT zadanie_id, gwarancja_data, gwarancja_przebieg FROM historia WHERE wizyta_id=?", (w_id,))}


def zbuduj(klasa, stan, *argumenty):
    strona = pomoce.zbuduj_strone()
    widok = klasa(strona.page, stan, *argumenty)
    widok._strona_testowa = strona
    return widok


def formularz_wpisu(stan, zadanie, h_id=None):
    from views.formularze import FormularzWpisView
    return zbuduj(FormularzWpisView, stan, h_id, zadanie)


def formularz_wizyty(stan, w_id=None):
    from views.formularze import FormularzWizytyView
    return zbuduj(FormularzWizytyView, stan, w_id)


def widok(nazwa, stan, **kwargs):
    strona = pomoce.zbuduj_strone()
    for pole, wartosc in kwargs.items():
        setattr(stan, pole, wartosc)
    zbudowany = pomoce.zbuduj_widok(pomoce.klasy_widokow()[nazwa], strona, stan)
    zbudowany._strona_testowa = strona
    return zbudowany


def teksty(korzen):
    """Napisy z ZBUDOWANEGO drzewa kontrolek (z etykietami pól)."""
    wynik, do_odwiedzenia = [], [korzen]
    while do_odwiedzenia:
        kontrolka = do_odwiedzenia.pop()
        for pole in ("value", "label"):
            wartosc = getattr(kontrolka, pole, None)
            if isinstance(wartosc, str):
                wynik.append(wartosc)
        for pole in ("controls", "content", "title", "subtitle", "leading", "trailing", "actions", "appbar"):
            dziecko = getattr(kontrolka, pole, None)
            if isinstance(dziecko, (list, tuple)):
                do_odwiedzenia.extend(d for d in dziecko if isinstance(d, ft.Control))
            elif isinstance(dziecko, ft.Control):
                do_odwiedzenia.append(dziecko)
    return wynik


def wpisz(pole, tekst):
    """Tekst w polu tak, jak wpisałby go palec — razem z on_change."""
    pole.value = tekst
    if pole.on_change:
        pole.on_change(None)


def zaznaczony(chip):
    return chip.bgcolor is not None


@pytest.fixture
def bez_nawigacji(monkeypatch):
    komunikaty = []
    monkeypatch.setattr(utils, "przejdz", lambda page, trasa: None)
    monkeypatch.setattr(utils, "pokaz_komunikat", lambda page, tekst, *a, **k: komunikaty.append(tekst))
    return komunikaty


@pytest.fixture
def bez_okien(monkeypatch):
    """Okno gwarancji bez strony na ekranie: otwarcie i zamknięcie to gesty."""
    from utils import gwarancja as modul
    komunikaty = []
    monkeypatch.setattr(modul, "otworz_dialog", lambda page, dlg: None)
    monkeypatch.setattr(modul, "zamknij_dialog", lambda page, dlg: None)
    monkeypatch.setattr(modul, "pokaz_komunikat", lambda page, tekst, *a, **k: komunikaty.append(tekst))
    return komunikaty


# ============================================================================
#  1. RACHUNEK I SŁOWA
# ============================================================================

@pytest.mark.parametrize("koniec, limit, licznik, status, tekst", [
    ("12.05.2027", None, 150000, "ok", "gwarancja jeszcze 7 miesięcy"),
    ("30.11.2026", None, 150000, "ok", "gwarancja jeszcze 2 miesiące"),
    ("15.10.2026", None, 150000, "blisko", "gwarancja jeszcze 15 dni"),
    ("30.09.2026", None, 150000, "blisko", "gwarancja kończy się dziś"),
    ("01.10.2026", None, 150000, "blisko", "gwarancja kończy się jutro"),
    ("29.09.2026", None, 150000, "po_terminie", "gwarancja wygasła 29.09.2026"),
    ("12.12.2028", None, 150000, "ok", "gwarancja jeszcze 2 lata i 2 miesiące"),
    (None, 180000, 168000, "ok", "gwarancja jeszcze 12 000 km"),
    (None, 180000, 179000, "blisko", "gwarancja jeszcze 1 000 km"),
    (None, 180000, 180500, "po_terminie", "gwarancja wygasła — przekroczono 180 000 km"),
    (None, 180000, None, "ok", "gwarancja do 180 000 km"),
    ("12.05.2027", 180000, 168000, "ok", "gwarancja jeszcze 7 miesięcy albo 12 000 km"),
    ("12.05.2027", 180000, 180500, "po_terminie", "gwarancja wygasła — przekroczono 180 000 km"),
    ("12.05.2027", 180000, None, "ok", "gwarancja jeszcze 7 miesięcy albo do 180 000 km"),
])
def test_stan_i_slowa_gwarancji(koniec, limit, licznik, status, tekst):
    stan = db.stan_gwarancji(koniec, limit, "12.05.2025", 150000, licznik, None, DZIS, prog_dni=30, prog_km=1500)

    assert stan["status"] == status
    assert stan["wygasla"] is (status == "po_terminie")
    assert db.opis_gwarancji(stan, "km") == tekst


def test_bez_limitow_nie_ma_gwarancji():
    assert db.stan_gwarancji(None, None) is None
    assert db.stan_gwarancji("", 0) is None
    assert db.stan_gwarancji("historia-gwarancja_data-1", "x") is None, "śmieci w bazie to brak gwarancji, nie wyjątek"


def test_obowiazuje_to_co_skonczy_sie_pierwsze():
    # 12 000 km przy 100 km dziennie to 120 dni — wcześniej niż termin za 224 dni.
    stan = db.stan_gwarancji("12.05.2027", 180000, "12.05.2025", 150000, 168000, 100, DZIS, 30, 1500)
    assert (stan["pierwsze"], stan["dni_km"], stan["dni_do_konca"]) == ("przebieg", 120, 120)
    assert stan["data_km"] == DZIS + timedelta(days=120)

    # Bez średniego przebiegu kilometry nie mają daty — koniec wyznacza termin.
    stan = db.stan_gwarancji("12.05.2027", 180000, "12.05.2025", 150000, 168000, None, DZIS, 30, 1500)
    assert (stan["pierwsze"], stan["dni_do_konca"]) == ("data", 224)
    # Pasek: bliżej końca jest ten limit, który zjadł więcej (506 z 730 dni > 18 z 30 tys. km).
    assert stan["udzial"] == pytest.approx(506 / 730)


@pytest.mark.parametrize("do, tekst", [
    (date(2026, 11, 14), "45 dni"),
    (date(2027, 5, 12), "7 miesięcy"),
    (date(2027, 9, 30), "12 miesięcy"),
    (date(2028, 12, 30), "2 lata i 3 miesiące"),
    (date(2031, 9, 30), "5 lat"),
])
def test_czas_pelnymi_miesiacami(do, tekst):
    assert db.czas_slownie(DZIS, do) == tekst


def test_miesiace_i_okres_gwarancji():
    assert db.dodaj_miesiace(date(2025, 1, 31), 1) == date(2025, 2, 28)
    assert db.dodaj_miesiace(date(2024, 2, 29), 12) == date(2025, 2, 28)
    assert db.dodaj_miesiace(date(2025, 5, 12), 24) == date(2027, 5, 12)
    assert db.okres_gwarancji("12.05.2027", "12.05.2025") == 24
    assert db.okres_gwarancji("13.05.2027", "12.05.2025") is None, "data z faktury, nie okres"
    assert db.okres_gwarancji("12.05.2025", "12.05.2025") is None


def test_duplikat_przenosi_okres_a_nie_date():
    wynik = db.przesun_gwarancje("12.05.2027", 180000, "12.05.2025", 150000, "30.09.2026", 170000)
    assert wynik == {"koniec": "30.09.2028", "limit_km": 200000, "miesiace": 24, "dystans_km": 30000}
    # Koniec spoza pełnych miesięcy przesuwa się o tyle samo dni.
    assert db.przesun_gwarancje("20.05.2027", None, "12.05.2025", None, "30.09.2026", None)["koniec"] == "07.10.2028"
    # Bez czytelnej daty źródła nie ma od czego liczyć — stara data kłamałaby od pierwszego dnia.
    assert db.przesun_gwarancje("12.05.2027", None, "brak", None, "30.09.2026", None)["koniec"] is None


def test_klucz_gwarancji():
    assert db.klucz_gwarancji("2027-05-12", "180000") == ("12.05.2027", 180000)
    assert db.klucz_gwarancji("", 0) == (None, None)
    assert db.klucz_gwarancji("historia-gwarancja_data-1", -5) == (None, None)


def test_bledy_gwarancji():
    assert db.bledy_gwarancji("12.05.2027", 180000, "12.05.2025", 150000) == {}
    assert db.bledy_gwarancji(None, None, "12.05.2025", 150000) == {}
    assert db.bledy_gwarancji("12.05.2025", None, "12.05.2025", None) == {
        "data": "Gwarancja musi kończyć się po dniu wymiany"}
    assert db.bledy_gwarancji(None, 150000, None, 150000) == {
        "przebieg": "Limit musi być wyższy niż przebieg przy wymianie"}


# ============================================================================
#  2. MIGRACJA, CHMURA, KOSZ
# ============================================================================

def test_migracja_45_dokłada_kolumny_i_nie_rusza_wpisow(magazyn):
    probki_baz.zbuduj_baze_w_wersji(db.BAZA_DANYCH, 44, DRABINKA)
    conn = sqlite3.connect(db.BAZA_DANYCH)
    c = conn.cursor()
    c.execute("INSERT INTO samochody (nazwa, typ_paliwa) VALUES ('Stary', 'Benzyna')")
    auto = c.lastrowid
    c.execute("INSERT INTO zadania (auto_id, nazwa) VALUES (?, 'Klocki')", (auto,))
    zadanie = c.lastrowid
    c.execute("INSERT INTO historia (zadanie_id, data, przebieg, cena) VALUES (?, '14.09.2026', 135830, 200.0)", (zadanie,))
    conn.commit()
    conn.close()

    db.init_db()

    assert {"gwarancja_data", "gwarancja_przebieg"} <= set(pomoce.kolumny("historia"))
    assert {"gwarancja_data", "gwarancja_przebieg"} <= set(pomoce.kolumny("wizyty"))
    assert jeden("SELECT gwarancja_data, gwarancja_przebieg FROM historia") == (None, None)
    assert db.gwarancje_pojazdu(auto) == [] and db.gwarancje_wpisow(zadanie) == {}


def test_gwarancja_jedzie_do_chmury_jako_dopisana():
    konfig_wizyt = next(k for k in sync.KONFIGURACJA_SYNC if k["tabela"] == "wizyty")
    for konfig in (KONFIG_HISTORII, konfig_wizyt):
        for kolumna in ("gwarancja_data", "gwarancja_przebieg"):
            assert kolumna in konfig["kolumny"] and kolumna in konfig["dopisane"], konfig["tabela"]


def test_hash_miedzy_dwiema_aktualizacjami_tez_jest_zgodny():
    """Wpis zsynchronizowany po dojściu robocizny, a przed gwarancją: pusty klucz
    `koszt_robocizny` ma, kluczy gwarancji nie ma. Zdjęcie WSZYSTKICH pustych
    dopisanych naraz go nie odtworzy — a to większość pozycji wizyt."""
    dopisane = frozenset(KONFIG_HISTORII["dopisane"])
    hash_ = sync_wysylanie._hash_zawartosci
    zgodny = sync_wysylanie._zgodny_z_zapamietanym
    z_robocizna = {"cena": 200.0, "koszt_robocizny": None}
    teraz = {**z_robocizna, "gwarancja_data": None, "gwarancja_przebieg": None}

    assert zgodny(teraz, hash_(z_robocizna), dopisane)
    assert zgodny(teraz, hash_({"cena": 200.0}), dopisane), "sprzed obu aktualizacji"
    assert not zgodny({**teraz, "gwarancja_data": "12.05.2027"}, hash_(z_robocizna), dopisane)
    assert not zgodny({**teraz, "cena": 250.0}, hash_(z_robocizna), dopisane)


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
                chmura.rekordy[parametry["p_id"]] = parametry["p_dane"]
                return _Odpowiedz()
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


def test_pierwsza_synchronizacja_po_aktualizacji_niczego_nie_wysyla(baza):
    """Wpis zsynchronizowany starszą wersją: hash i chmura bez kluczy gwarancji.
    Puste nowe kolumny to nie zmiana — dopiero wpisana gwarancja jedzie."""
    d = pojazd()
    h_id = wpis(d["klocki"], dzien(-100), 140000)
    with db.polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        wiersz = conn.execute("SELECT * FROM historia WHERE id=?", (h_id,)).fetchone()
    stare = {k: wiersz[k] for k in KONFIG_HISTORII["kolumny"] if not k.startswith("gwarancja_")}
    stare.update(zadanie_id_zdalne=None, wizyta_id_zdalne=None)
    with db.polacz_baze() as conn:
        conn.execute("UPDATE historia SET zdalne_id='hist-A', zdalny_hash=? WHERE id=?",
                     (sync_wysylanie._hash_zawartosci(stare), h_id))
    sync_konflikty._konflikty_biezacej_synchronizacji.clear()
    chmura = ChmuraWPamieci({"hist-A": stare})

    assert sync_wysylanie._wypchnij_tabele(chmura, "wspolny", d["auto_id"], KONFIG_HISTORII, db.ROLA_WLASCICIEL)[0] == 0

    db.zapisz_gwarancje_wpisu(h_id, dzien(600), 170000)
    wyslano, _ = sync_wysylanie._wypchnij_tabele(chmura, "wspolny", d["auto_id"], KONFIG_HISTORII, db.ROLA_WLASCICIEL)

    assert wyslano == 1
    assert (chmura.rekordy["hist-A"]["gwarancja_data"], chmura.rekordy["hist-A"]["gwarancja_przebieg"]) == (dzien(600), 170000)
    assert sync_konflikty._konflikty_biezacej_synchronizacji == []


def test_rekord_z_chmury_niesie_gwarancje_a_starszy_jej_nie_kasuje(baza):
    d = pojazd()
    h_id = wpis(d["klocki"], dzien(-100), 140000)
    with db.polacz_baze() as conn:
        conn.execute("UPDATE zadania SET zdalne_id='zad-K' WHERE id=?", (d["klocki"],))
        conn.execute("UPDATE historia SET zdalne_id='hist-B', zdalny_hash='stary' WHERE id=?", (h_id,))
    dane = {"data": dzien(-100), "przebieg": 140000, "cena": 200.0, "wykonawca": "Warsztat u Janka",
            "zadanie_id_zdalne": "zad-K", "wizyta_id_zdalne": None}
    znane = {"hist-B": {"id": h_id, "hash": "stary"}}

    nowy = {**dane, "gwarancja_data": dzien(600), "gwarancja_przebieg": 170000}
    assert sync_pobieranie._zastosuj_rekord(KONFIG_HISTORII, {"id": "hist-B", "dane": nowy}, d["auto_id"], znane) == 1
    assert jeden("SELECT gwarancja_data, gwarancja_przebieg FROM historia WHERE id=?", (h_id,)) == (dzien(600), 170000)

    # Rekord wypchnięty wersją bez gwarancji nie ma jej kluczy — lokalna zostaje.
    stary = {**dane, "cena": 250.0}
    assert sync_pobieranie._zastosuj_rekord(KONFIG_HISTORII, {"id": "hist-B", "dane": stary}, d["auto_id"], znane) == 1
    assert jeden("SELECT cena, gwarancja_data, gwarancja_przebieg FROM historia WHERE id=?", (h_id,)) == (250.0, dzien(600), 170000)


def test_kosz_przenosi_gwarancje(baza):
    ids = pomoce.utworz_pojazd("Do kosza")
    przed = jeden("SELECT gwarancja_data, gwarancja_przebieg FROM historia WHERE id=?", (ids["historia"],))
    assert przed == ("10.01.2028", 130000), "pojazd testowy ma gwarancję na wpisie"

    wynik = db.usun_auto_do_kosza(ids["auto_id"])
    assert jeden("SELECT COUNT(*) FROM historia") == 0
    db.przywroc_auto_z_kosza(wynik["kosz_id"])

    assert jeden("SELECT gwarancja_data, gwarancja_przebieg FROM historia WHERE id=?", (ids["historia"],)) == przed


# ============================================================================
#  3. GWARANCJE POJAZDU — OSTATNIA WYMIANA
# ============================================================================

def test_liczy_sie_ostatnia_wymiana_podzespolu(baza):
    d = pojazd()
    wpis(d["klocki"], dzien(-400), 120000, koniec=dzien(330))
    nowy = wpis(d["klocki"], dzien(-100), 140000, koniec=dzien(265), limit=170000)
    wpis(d["akumulator"], dzien(-800), 100000, koniec=dzien(-70))

    (g,) = db.gwarancje_pojazdu(d["auto_id"])
    assert (g["historia_id"], g["nazwa"], g["zostalo_km"], g["dni"]) == (nowy, "Klocki hamulcowe", 20000, 265)
    assert [x["nazwa"] for x in db.gwarancje_pojazdu(d["auto_id"], tylko_aktywne=False)] == ["Akumulator", "Klocki hamulcowe"]

    # Nowsza wymiana BEZ gwarancji zamyka sprawę — tamtej części już nie ma w aucie.
    wpis(d["klocki"], dzien(-10), 149000)
    assert db.gwarancje_pojazdu(d["auto_id"]) == []


def test_historia_podzespolu_wie_o_czesci_wymienionej_pozniej(baza):
    d = pojazd()
    stary = wpis(d["klocki"], dzien(-400), 120000, koniec=dzien(330))
    nowy = wpis(d["klocki"], dzien(-100), 140000, koniec=dzien(265))

    gwarancje = db.gwarancje_wpisow(d["klocki"])

    assert gwarancje[stary]["wymieniona"] == dzien(-100)
    assert gwarancje[nowy]["wymieniona"] is None
    assert utils.tekst_gwarancji(gwarancje[stary], "km") == (
        f"Gwarancja do {dzien(330)} · część wymieniona ponownie {dzien(-100)}")


# ============================================================================
#  4. DZWONEK I „ILE ZOSTAŁO DO…”
# ============================================================================

def gwarancje_w_dzwonku(auto_id):
    return [p for p in db.pobierz_powiadomienia(auto_id) if p["typ"] == "gwarancja"]


def test_dzwonek_przypomina_przed_koncem_i_milknie_po_nim(baza):
    d = pojazd()
    h_id = wpis(d["klocki"], dzien(-700), 120000, koniec=dzien(10))

    (p,) = gwarancje_w_dzwonku(d["auto_id"])
    assert (p["klucz"], p["status"], p["trasa"]) == (f"gwarancja:{h_id}", "pilne", f"/historia/{d['klocki']}")
    assert p["tytul"] == "Gwarancja: Klocki hamulcowe"
    assert p["linie_opisu"] == [f"Gwarancja kończy się za 10 dni ({dzien(10)})",
                                f"Sprawdź część, zanim minie — wymiana {dzien(-700)}"]

    # Drzemka po kluczu jak każde inne powiadomienie.
    db.odloz_powiadomienie(d["auto_id"], db.klucz_drzemki(p), 7)
    assert gwarancje_w_dzwonku(d["auto_id"]) == []
    db.przywroc_powiadomienie(d["auto_id"], db.klucz_drzemki(p))

    # Po końcu gwarancji nie ma już czego zrobić — powiadomienie znika.
    db.zapisz_gwarancje_wpisu(h_id, dzien(-1), None)
    assert gwarancje_w_dzwonku(d["auto_id"]) == []
    # Daleko od końca — też cisza.
    db.zapisz_gwarancje_wpisu(h_id, dzien(200), None)
    assert gwarancje_w_dzwonku(d["auto_id"]) == []


def test_dzwonek_liczy_tez_kilometry_a_sprzedane_milczy(baza):
    d = pojazd()
    wpis(d["klocki"], dzien(-100), 140000, limit=151000)

    (p,) = gwarancje_w_dzwonku(d["auto_id"])
    assert p["linie_opisu"][0].startswith("Do końca gwarancji: 1 000 km (ok. "), "z prognozą daty ze średniego przebiegu"

    db.oznacz_pojazd_sprzedany(d["auto_id"], dzien(-1), 30000.0)
    assert gwarancje_w_dzwonku(d["auto_id"]) == []


def test_kondycja_nie_karze_za_gwarancje(baza):
    d = pojazd()
    przed = db.oblicz_kondycje_pojazdu(d["auto_id"])
    wpis(d["klocki"], dzien(-700), 120000, koniec=dzien(10))
    db.zanotuj_zmiane_danych()
    assert db.oblicz_kondycje_pojazdu(d["auto_id"]) == przed, "koniec gwarancji nie jest usterką"


def gwarancje_w_odliczaniach(auto_id):
    return [p for p in db.odliczania_pojazdu(auto_id) if p["rodzaj"] == "gwarancja_naprawy"]


def test_odliczania_maja_gwarancje_naprawy(baza):
    d = pojazd()
    h_id = wpis(d["klocki"], dzien(-100), 140000, koniec=dzien(265), limit=300000)
    wpis(d["akumulator"], dzien(-800), 100000, koniec=dzien(-70))

    (p,) = gwarancje_w_odliczaniach(d["auto_id"])

    assert (p["tytul"], p["dni"], p["prognoza"], p["status"], p["trasa"]) == (
        "Klocki hamulcowe — gwarancja", 265, False, "ok", f"/historia/{d['klocki']}")
    assert p["udzial"] == pytest.approx(100 / 365)
    assert utils.podpis_odliczania(p) == f"Wymiana {dzien(-100)} · do {dzien(265)} lub 300 000 km"
    assert utils.ikona_z_mapy(utils.IKONY_ODLICZAN, p["ikona"], None) == ft.Icons.GPP_GOOD

    napisy = teksty(widok("OdliczaniaView", pomoce.stan_aplikacji(d["auto_id"], "Gwarancyjny")))
    assert "Klocki hamulcowe — gwarancja" in napisy

    # 10 000 km przy ok. 100 km dziennie skończy się przed terminem — wtedy
    # wiersz odlicza kilometry, a data jest prognozą (jak przy podzespole).
    db.zapisz_gwarancje_wpisu(h_id, dzien(265), 160000)
    (p,) = gwarancje_w_odliczaniach(d["auto_id"])
    assert (p["zostalo_km"], p["prognoza"]) == (10000, True) and p["dni"] < 265
    assert p["udzial"] == pytest.approx(1 / 2)


# ============================================================================
#  5. FORMULARZE
# ============================================================================

def test_nowy_wpis_ze_skrotow_trzymajacych_sie_wymiany(baza, bez_nawigacji):
    d = pojazd()
    stan = pomoce.stan_aplikacji(d["auto_id"], "Gwarancyjny")
    formularz = formularz_wpisu(stan, d["klocki"])
    gw = formularz.gwarancja
    assert gw.podsumowanie.value.startswith("Bez gwarancji")

    formularz.e_d.value = "12.05.2026"
    wpisz(formularz.e_p, "140000")
    gw.ustaw_okres(24)
    gw.ustaw_dystans(30000)
    assert (gw.e_data.value, gw.e_km.value) == ("12.05.2028", "170000")
    assert gw.podsumowanie.value == "2 lata albo 30 000 km od wymiany — obowiązuje to, co skończy się pierwsze"
    assert zaznaczony(gw._chipy_okresu[24]) and zaznaczony(gw._chipy_dystansu[30000])

    # Skrót trzyma się wymiany: poprawiona data (pole daty woła wtedy
    # przy_zmianie_wymiany) i licznik przesuwają gwarancję.
    formularz.e_d.value = "10.05.2026"
    gw.przy_zmianie_wymiany()
    wpisz(formularz.e_p, "139500")
    assert (gw.e_data.value, gw.e_km.value) == ("10.05.2028", "169500")

    formularz.zapisz(None)
    h_id = jeden("SELECT MAX(id) FROM historia")
    assert jeden("SELECT gwarancja_data, gwarancja_przebieg FROM historia WHERE id=?", (h_id,)) == ("10.05.2028", 169500)

    # Edycja: pola wracają wypełnione, skrót podświetlony, zapis bez zmian niczego nie rusza.
    edycja = formularz_wpisu(stan, d["klocki"], h_id)
    assert (edycja.gwarancja.e_data.value, edycja.gwarancja.e_km.value) == ("10.05.2028", "169500")
    assert zaznaczony(edycja.gwarancja._chipy_okresu[24])
    assert not edycja._czy_zmieniono()


def test_recznie_wybrana_data_zostaje_na_miejscu(baza, bez_nawigacji):
    d = pojazd()
    formularz = formularz_wpisu(pomoce.stan_aplikacji(d["auto_id"], "Gwarancyjny"), d["klocki"])
    gw = formularz.gwarancja
    formularz.e_d.value = "12.05.2026"
    gw.ustaw_okres(12)

    # Wybór z kalendarza (pole_daty woła po_zmianie) odpina skrót.
    gw.e_data.value = "20.06.2027"
    gw._data_z_kalendarza()
    formularz.e_d.value = "01.05.2026"
    gw.przy_zmianie_wymiany()

    assert gw.e_data.value == "20.06.2027"
    assert not any(zaznaczony(c) for c in gw._chipy_okresu.values())
    # Krzyżyk w polu zdejmuje datę.
    gw._wyczysc_date(None)
    assert gw.e_data.value == "" and gw._przycisk_czysc.visible is False


def test_bledna_gwarancja_nie_zapisuje_wpisu(baza, bez_nawigacji):
    d = pojazd()
    formularz = formularz_wpisu(pomoce.stan_aplikacji(d["auto_id"], "Gwarancyjny"), d["klocki"])
    formularz.e_d.value = "12.05.2026"
    wpisz(formularz.e_p, "140000")
    formularz.gwarancja.e_data.value = "01.05.2026"
    wpisz(formularz.gwarancja.e_km, "139000")

    formularz.zapisz(None)

    assert jeden("SELECT COUNT(*) FROM historia") == 0
    assert utils.blad_kontrolki(formularz.gwarancja.e_data) == "Gwarancja musi kończyć się po dniu wymiany"
    assert utils.blad_kontrolki(formularz.gwarancja.e_km) == "Limit musi być wyższy niż przebieg przy wymianie"


def test_duplikat_wpisu_przenosi_okres(baza, bez_nawigacji):
    d = pojazd()
    zrodlo = wpis(d["klocki"], "12.05.2025", 120000, koniec="12.05.2027", limit=150000)
    stan = pomoce.stan_aplikacji(d["auto_id"], "Gwarancyjny")
    stan.duplikuj_zrodlo_wpis = zrodlo

    formularz = formularz_wpisu(stan, d["klocki"])
    gw = formularz.gwarancja

    assert gw.e_data.value == po_miesiacach(formularz.e_d.value, 24)
    assert gw.e_km.value == "150000", "licznik duplikatu jest ze źródła, więc limit też"
    # Poprawka licznika duplikatu przesuwa limit o tyle samo.
    wpisz(formularz.e_p, "148000")
    assert gw.e_km.value == "178000"


def test_wizyta_ma_wspolna_gwarancje_a_wyjatek_przy_pozycji_zostaje(baza, bez_nawigacji):
    d = pojazd()
    stan = pomoce.stan_aplikacji(d["auto_id"], "Gwarancyjny")
    formularz = formularz_wizyty(stan)
    formularz.e_d.value = dzien(-30)
    wpisz(formularz.e_p, "148000")
    for chk in formularz.chk_czesci:
        chk.value = True
    formularz.gwarancja.ustaw_okres(12)
    formularz.zapisz(None)

    w_id = jeden("SELECT MAX(id) FROM wizyty")
    rok, dwa, trzy = (po_miesiacach(dzien(-30), m) for m in (12, 24, 36))
    assert jeden("SELECT gwarancja_data, gwarancja_przebieg FROM wizyty WHERE id=?", (w_id,)) == (rok, None)
    assert gwarancje_wizyty(w_id) == {d["klocki"]: (rok, None), d["akumulator"]: (rok, None)}

    # Wyjątek przy pozycji: akumulator z trzyletnią.
    h_aku = jeden("SELECT id FROM historia WHERE wizyta_id=? AND zadanie_id=?", (w_id, d["akumulator"]))
    db.zapisz_gwarancje_wpisu(h_aku, trzy, None)

    edycja = formularz_wizyty(stan, w_id)
    assert edycja.gwarancja.e_data.value == rok
    assert any("własną gwarancję" in str(u.value) for u in edycja.gwarancja._uwagi)
    assert not edycja._czy_zmieniono()
    edycja.gwarancja.ustaw_okres(24)
    edycja.zapisz(None)

    assert gwarancje_wizyty(w_id) == {d["klocki"]: (dwa, None), d["akumulator"]: (trzy, None)}
    assert jeden("SELECT gwarancja_data FROM wizyty WHERE id=?", (w_id,)) == dwa

    # Nowo zaznaczony podzespół dostaje wspólną; wizyta z samym wyjątkiem też wie,
    # który jest wyjątkiem — wspólną zna z zapisu, a nie z większości pozycji.
    edycja = formularz_wizyty(stan, w_id)
    next(chk for chk in edycja.chk_czesci if chk.data == d["klocki"]).value = False
    edycja.zapisz(None)
    assert gwarancje_wizyty(w_id) == {d["akumulator"]: (trzy, None)}
    edycja = formularz_wizyty(stan, w_id)
    assert edycja.gwarancja.e_data.value == dwa
    next(chk for chk in edycja.chk_czesci if chk.data == d["klocki"]).value = True
    edycja.zapisz(None)
    assert gwarancje_wizyty(w_id) == {d["klocki"]: (dwa, None), d["akumulator"]: (trzy, None)}


def test_duplikat_wizyty_przenosi_okres_wspolnej(baza, bez_nawigacji):
    d = pojazd()
    w_id = wizyta(d["auto_id"], [d["klocki"]], "12.05.2025", 120000)
    with db.polacz_baze() as conn:
        conn.execute("UPDATE wizyty SET gwarancja_data='12.05.2027', gwarancja_przebieg=140000 WHERE id=?", (w_id,))
        conn.execute("UPDATE historia SET gwarancja_data='12.05.2027', gwarancja_przebieg=140000 WHERE wizyta_id=?", (w_id,))
    stan = pomoce.stan_aplikacji(d["auto_id"], "Gwarancyjny")
    stan.duplikuj_zrodlo_wizyta = w_id

    formularz = formularz_wizyty(stan)

    assert formularz.gwarancja.e_data.value == po_miesiacach(formularz.e_d.value, 24)
    assert formularz.gwarancja.e_km.value == "170000", "licznik wizyty jest dzisiejszy (150 000) + 20 000"
    assert any("okres gwarancji" in n for n in teksty(formularz))


def test_okno_gwarancji_pozycji_wizyty(baza, bez_okien):
    d = pojazd()
    w_id = wizyta(d["auto_id"], [d["klocki"], d["akumulator"]], dzien(-30), 148000)
    h_id = jeden("SELECT id FROM historia WHERE wizyta_id=? AND zadanie_id=?", (w_id, d["akumulator"]))
    strona = pomoce.zbuduj_strone()
    po_zapisie = []

    okno = utils.dialog_gwarancji_wpisu(strona.page, h_id, lambda: po_zapisie.append(True))
    okno.data.ustaw_okres(36)
    okno.data.ustaw_dystans(20000)
    okno.actions[1].on_click(None)

    assert gwarancje_wizyty(w_id) == {d["klocki"]: (None, None), d["akumulator"]: (po_miesiacach(dzien(-30), 36), 168000)}
    assert jeden("SELECT zmodyfikowane_przez FROM historia WHERE id=?", (h_id,)) == db.pobierz_moje_imie()
    assert po_zapisie == [True] and bez_okien == ["Zapisano gwarancję."]

    # Puste pola zdejmują gwarancję.
    okno = utils.dialog_gwarancji_wpisu(strona.page, h_id)
    okno.data._wyczysc_date(None)
    wpisz(okno.data.e_km, "")
    okno.actions[1].on_click(None)
    assert gwarancje_wizyty(w_id)[d["akumulator"]] == (None, None)
    assert bez_okien[-1] == "Usunięto gwarancję."


def test_menu_pozycji_wizyty_ma_gwarancje_a_podglad_nie(baza, monkeypatch):
    from views.history_view import HistoriaView

    d = pojazd()
    w_id = wizyta(d["auto_id"], [d["klocki"]], dzien(-30), 148000)
    h_id = jeden("SELECT id FROM historia WHERE wizyta_id=?", (w_id,))
    menu = []
    monkeypatch.setattr(utils, "pokaz_menu_kontekstowe", lambda page, tytul, pozycje: menu.append(pozycje))
    stan = pomoce.stan_aplikacji(d["auto_id"], "Gwarancyjny")

    widok_historii = zbuduj(HistoriaView, stan, d["klocki"])
    widok_historii.karty_ref[h_id].on_click(None)
    assert [p["tekst"] for p in menu[-1]] == ["Dodaj notatkę", "Gwarancja tej pozycji", "Edytuj w „Wizyty zbiorcze”"]

    with db.polacz_baze() as conn:
        conn.execute("UPDATE samochody SET wspolny_pojazd_id='wspolny-1' WHERE id=?", (d["auto_id"],))
    db.ustaw_role_pojazdu(d["auto_id"], db.ROLA_PODGLAD)
    widok_historii = zbuduj(HistoriaView, stan, d["klocki"])
    widok_historii.karty_ref[h_id].on_click(None)
    assert [p["tekst"] for p in menu[-1]] == ["Edytuj w „Wizyty zbiorcze”"]


def test_skroty_w_milach(baza, bez_nawigacji):
    db.zapisz_jednostke_dystansu("mi")
    d = pojazd()
    formularz = formularz_wpisu(pomoce.stan_aplikacji(d["auto_id"], "Gwarancyjny"), d["klocki"])
    gw = formularz.gwarancja
    assert [c.content.value for c in gw._chipy_dystansu.values()] == ["+10 tys. mi", "+20 tys. mi", "+30 tys. mi"]
    assert gw.e_km.label == "Gwarancja do przebiegu (mi)"

    formularz.e_d.value = dzien(-10)
    wpisz(formularz.e_p, "93000")
    gw.ustaw_dystans(20000)
    assert gw.e_km.value == "113000"
    formularz.zapisz(None)

    przebieg, limit = jeden("SELECT przebieg, gwarancja_przebieg FROM historia")
    assert limit - przebieg == round(20000 * db.KM_W_MILI), "limit to dokładnie 20 tys. mil po wymianie"


# ============================================================================
#  6. GDZIE JĄ WIDAĆ
# ============================================================================

@pytest.fixture
def auto_z_gwarancja(baza):
    d = pojazd()
    d["stary"] = wpis(d["klocki"], dzien(-400), 120000, koniec=dzien(330))
    d["nowy"] = wpis(d["klocki"], dzien(-100), 140000, koniec=dzien(265), limit=170000)
    d["stan"] = pomoce.stan_aplikacji(d["auto_id"], "Gwarancyjny")
    return d


def test_karta_wpisu_w_historii(auto_z_gwarancja):
    from views.history_view import HistoriaView

    d = auto_z_gwarancja
    napisy = teksty(zbuduj(HistoriaView, d["stan"], d["klocki"]))

    assert f"Gwarancja jeszcze {ile_czasu(265)} albo 20 000 km · do {dzien(265)} lub 170 000 km" in napisy
    assert f"Gwarancja do {dzien(330)} · część wymieniona ponownie {dzien(-100)}" in napisy


def test_karta_podzespolu_w_serwisie(auto_z_gwarancja):
    d = auto_z_gwarancja
    napisy = teksty(widok("MainView", d["stan"], zakladka=1))

    assert f"Gwarancja jeszcze {ile_czasu(265)} albo 20 000 km" in napisy
    assert len([n for n in napisy if n.startswith("Gwarancja ")]) == 1, "akumulator bez gwarancji — bez linijki"


def test_karta_pojazdu_ma_sekcje_tylko_z_trwajacymi(auto_z_gwarancja):
    d = auto_z_gwarancja
    napisy = teksty(widok("PojazdView", d["stan"]))

    assert "Gwarancje na naprawy" in napisy and "Klocki hamulcowe" in napisy
    assert f"gwarancja jeszcze {ile_czasu(265)} albo 20 000 km" in napisy
    assert f"do {dzien(265)} lub 170 000 km · wymiana {dzien(-100)} · Warsztat u Janka" in napisy

    wpis(d["klocki"], dzien(-5), 149500)
    assert "Gwarancje na naprawy" not in teksty(widok("PojazdView", d["stan"])), "bez trwających — bez sekcji"


def test_paszport_pdf_ma_gwarancje(auto_z_gwarancja, monkeypatch):
    from db import raporty

    d = auto_z_gwarancja
    dane = db.pobierz_dane_paszportu(d["auto_id"])
    assert dane["gwarancje"] == [(
        "Klocki hamulcowe", f"gwarancja jeszcze {ile_czasu(265)} albo 20 000 km",
        f"do {dzien(265)} lub 170 000 km · wymiana {dzien(-100)} · Warsztat u Janka", "ok",
    )]

    napisy = []
    oryginal = raporty._RaportPDF.cell

    def cell(self, *argumenty, **nazwane):
        if len(argumenty) >= 3:
            napisy.append(str(argumenty[2]))
        return oryginal(self, *argumenty, **nazwane)

    monkeypatch.setattr(raporty._RaportPDF, "cell", cell)
    pdf = db.generuj_pdf_raportu("Gwarancyjny", {}, "cały okres", tryb_paszportu=True, **dane)

    # Bez czcionki DejaVu w assets PDF spłaszcza ogonki i pauzy — porównujemy
    # z tym, co z napisu robi sam raport.
    t = raporty._RaportPDF(orientation="P").t
    assert pdf.startswith(b"%PDF")
    assert t("Gwarancje na naprawy") in napisy
    assert t("Klocki hamulcowe — ") in napisy
    assert t(f"gwarancja jeszcze {ile_czasu(265)} albo 20 000 km") in napisy
    assert t(f"do {dzien(265)} lub 170 000 km · wymiana {dzien(-100)} · Warsztat u Janka") in napisy


def test_dlugi_napis_w_paszporcie_miesci_sie_w_szerokosci():
    from db import raporty

    if db.FPDF is None:
        pytest.skip("brak fpdf2")
    pdf = raporty._RaportPDF()
    pdf.add_page()
    pdf.set_font(pdf.czcionka, "", 10)
    przyciety = raporty._przytnij_do_szerokosci(pdf, "Bardzo długa nazwa warsztatu " * 20, 60)
    assert przyciety.endswith("...") and pdf.get_string_width(przyciety) <= 60
    assert raporty._przytnij_do_szerokosci(pdf, "Krótko", 60) == pdf.t("Krótko")
