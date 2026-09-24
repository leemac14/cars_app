"""Robocizna osobno od części — przy wizycie i przy pojedynczym wpisie.

Jedna kwota nie odpowiada na pytanie, czy drogi jest warsztat, czy części,
a od tego zależy, czy szukać innego mechanika, czy kupować części samemu.
W bazie są dwie liczby: koszt całkowity i robocizna (NULL = bez podziału).
Części na rachunku to reszta po robociźnie i częściach z magazynu — dlatego
rozbicie sumuje się zawsze, także po zmianach, które robocizny nie znają.

Najłatwiej to zepsuć w trzech miejscach: w formularzu (stara wizyta bez
podziału musi się dać rozbić bez przepisywania kwoty, a zapis bez zmian nie
może niczego ruszyć), w synchronizacji (nowa kolumna nie może zamienić
pierwszej synchronizacji po aktualizacji w wysyłkę całej tabeli i lawinę
fałszywych konfliktów) i w porównaniach (naprawa bez podziału ani mieszana
nie może przekłamać proporcji).
"""

import sqlite3
from datetime import date, timedelta

import flet as ft
import pytest

import audyty
import db
import pomoce
import probki_baz
import sync
import utils
from sync import konflikty as sync_konflikty
from sync import wysylanie as sync_wysylanie


DRABINKA = probki_baz.wczytaj_drabinke()


# ============================================================================
#  POMOCE
# ============================================================================

@pytest.fixture
def bez_nawigacji(monkeypatch):
    komunikaty = []
    monkeypatch.setattr(utils, "przejdz", lambda page, trasa: None)
    monkeypatch.setattr(utils, "pokaz_komunikat", lambda page, tekst, *a, **k: komunikaty.append(tekst))
    return komunikaty


def dni_temu(dni):
    return (date.today() - timedelta(days=dni)).strftime("%d.%m.%Y")


def pojazd():
    """Auto z dwoma podzespołami i olejem w magazynie (30 zł za litr)."""
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO samochody (nazwa, typ_paliwa, status, rola_wspoldzielenia) VALUES (?,?,?,?)",
            ("Rozbity", "Benzyna", db.STATUS_POJAZDU_AKTYWNY, db.ROLA_WLASCICIEL),
        )
        auto = c.lastrowid
        zadania = []
        for nazwa in ("Olej silnikowy i filtr", "Klocki hamulcowe"):
            c.execute("INSERT INTO zadania (auto_id, nazwa, interwal_km) VALUES (?,?,?)", (auto, nazwa, 15000))
            zadania.append(c.lastrowid)
        c.execute(
            "INSERT INTO magazyn_czesci (auto_id, nazwa, kategoria, ilosc, jednostka, cena, cena_jednostkowa) "
            "VALUES (?,?,?,?,?,?,?)", (auto, "Olej 5W-30", "Inne", 10.0, "l", 300.0, 30.0),
        )
        olej = c.lastrowid
    return {"auto_id": auto, "olej_zad": zadania[0], "klocki_zad": zadania[1], "olej": olej}


def wizyta(auto, koszt, robocizna=None, wykonawca="AutoFix", zadania=(), z_magazynu=None, data=None, magazyn_id=None):
    """Wizyta wpisana wprost do bazy. `z_magazynu` — koszt zużycia z półki,
    już zawarty w `koszt` (tak jak zapisuje go formularz)."""
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO wizyty (auto_id, data, przebieg, wykonawca, koszt_calkowity, koszt_robocizny) "
            "VALUES (?,?,?,?,?,?)", (auto, data or dni_temu(30), 120000, wykonawca, koszt, robocizna),
        )
        w_id = c.lastrowid
        for zadanie in zadania:
            c.execute("INSERT INTO historia (wizyta_id, zadanie_id, data, przebieg, cena, wykonawca) "
                      "VALUES (?,?,?,?,0,?)", (w_id, zadanie, data or dni_temu(30), 120000, wykonawca))
        if z_magazynu is not None:
            c.execute("INSERT INTO wizyta_czesci_magazynu (wizyta_id, magazyn_id, ilosc_uzyta, koszt) VALUES (?,?,?,?)",
                      (w_id, magazyn_id, 1.0, z_magazynu))
    return w_id


def wpis(zadanie, cena, robocizna=None, wykonawca="Warsztat", z_magazynu=None, data=None, magazyn_id=None):
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO historia (zadanie_id, data, przebieg, cena, koszt_robocizny, wykonawca) VALUES (?,?,?,?,?,?)",
            (zadanie, data or dni_temu(30), 120000, cena, robocizna, wykonawca),
        )
        h_id = c.lastrowid
        if z_magazynu is not None:
            c.execute("INSERT INTO historia_czesci_magazynu (historia_id, magazyn_id, ilosc_uzyta, koszt) VALUES (?,?,?,?)",
                      (h_id, magazyn_id, 1.0, z_magazynu))
    return h_id


def jeden(sql, parametry=()):
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute(sql, parametry)
        wiersz = c.fetchone()
    return wiersz[0] if wiersz and len(wiersz) == 1 else wiersz


def zbuduj(klasa, stan, *argumenty):
    strona = pomoce.zbuduj_strone()
    widok = klasa(strona.page, stan, *argumenty)
    widok._strona_testowa = strona
    return widok


def formularz_wizyty(stan, w_id=None):
    from views.formularze import FormularzWizytyView
    return zbuduj(FormularzWizytyView, stan, w_id)


def formularz_wpisu(stan, zadanie, h_id=None):
    from views.formularze import FormularzWpisView
    return zbuduj(FormularzWpisView, stan, h_id, zadanie)


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


# ============================================================================
#  RDZEŃ: db.rozbicie_kosztu
# ============================================================================

@pytest.mark.parametrize("koszt, robocizna, magazyn, oczekiwane", [
    (950, 300, 200, (300.0, 450.0, 200.0, True)),
    (950, None, 200, (None, None, 200.0, False)),
    # Poza magazynem nie ma czego dzielić, więc robocizny też nie było.
    (200, None, 200, (0.0, 0.0, 200.0, True)),
    (0, None, None, (0.0, 0.0, 0.0, True)),
    # Koszt zmniejszony z pominięciem robocizny (zwrot pozycji, starsza wersja):
    # różnica schodzi najpierw z części, nic nie idzie na minus.
    (100, 300, 0, (100.0, 0.0, 0.0, True)),
    (100, 50, 300, (0.0, 0.0, 100.0, True)),
])
def test_rozbicie_zawsze_sie_sumuje(koszt, robocizna, magazyn, oczekiwane):
    r = db.rozbicie_kosztu(koszt, robocizna, magazyn)
    assert (r["robocizna"], r["czesci"], r["z_magazynu"], r["podzielony"]) == oczekiwane
    if r["podzielony"]:
        assert round(r["robocizna"] + r["czesci"] + r["z_magazynu"], 2) == r["razem"]


def test_zwrot_pozycji_schodzi_z_czesci_a_cofniecie_wraca(baza):
    d = pojazd()
    with db.polacz_baze() as conn:
        c = conn.cursor()
        idy = []
        for tytul, koszt, zadanie in (("Olej", 300.0, d["olej_zad"]), ("Klocki", 200.0, d["klocki_zad"])):
            c.execute("INSERT INTO do_zrobienia (auto_id, tytul, szacowany_koszt, zadanie_id) VALUES (?,?,?,?)",
                      (d["auto_id"], tytul, koszt, zadanie))
            idy.append(c.lastrowid)
    w_id, _, _ = db.utworz_wizyte_z_do_zrobienia(d["auto_id"], idy)
    # Wizytę rozbito (na innym telefonie), zanim pozycje straciły cenę.
    with db.polacz_baze() as conn:
        conn.execute("UPDATE wizyty SET koszt_robocizny=150 WHERE id=?", (w_id,))
    klocki = jeden("SELECT id FROM historia WHERE wizyta_id=? AND zadanie_id=?", (w_id, d["klocki_zad"]))

    wynik = db.zwroc_pozycje_wizyty_do_zrobienia(w_id, [klocki])
    r = db.rozbicie_kosztu(*jeden("SELECT koszt_calkowity, koszt_robocizny FROM wizyty WHERE id=?", (w_id,)))
    assert (r["razem"], r["robocizna"], r["czesci"]) == (300.0, 150.0, 150.0)

    wynik["cofnij"]()
    r = db.rozbicie_kosztu(*jeden("SELECT koszt_calkowity, koszt_robocizny FROM wizyty WHERE id=?", (w_id,)))
    assert (r["razem"], r["robocizna"], r["czesci"]) == (500.0, 150.0, 350.0)


def test_koszt_usunietej_pozycji_magazynu_przechodzi_do_czesci(baza):
    d = pojazd()
    w_id = wizyta(d["auto_id"], 810.0, 300.0, z_magazynu=60.0, magazyn_id=d["olej"])
    with db.polacz_baze() as conn:
        conn.execute("DELETE FROM wizyta_czesci_magazynu WHERE wizyta_id=?", (w_id,))
    r = db.rozbicie_kosztu(810.0, 300.0, None)
    assert (r["robocizna"], r["czesci"], r["z_magazynu"]) == (300.0, 510.0, 0.0), \
        "koszt oleju został w kwocie — był częścią, więc liczy się jako część"


# ============================================================================
#  MIGRACJA 42
# ============================================================================

def test_migracja_zostawia_stare_naprawy_bez_podzialu(magazyn):
    probki_baz.zbuduj_baze_w_wersji(db.BAZA_DANYCH, 41, DRABINKA)
    conn = sqlite3.connect(db.BAZA_DANYCH)
    c = conn.cursor()
    c.execute("INSERT INTO samochody (nazwa, typ_paliwa) VALUES ('Stary', 'Benzyna')")
    auto = c.lastrowid
    c.execute("INSERT INTO zadania (auto_id, nazwa) VALUES (?, 'Olej')", (auto,))
    zadanie = c.lastrowid
    c.execute("INSERT INTO wizyty (auto_id, data, przebieg, koszt_calkowity) VALUES (?, '01.09.2026', 135000, 750.0)", (auto,))
    c.execute("INSERT INTO historia (zadanie_id, data, przebieg, cena) VALUES (?, '14.09.2026', 135830, 200.0)", (zadanie,))
    conn.commit()
    conn.close()

    db.init_db()

    assert "koszt_robocizny" in pomoce.kolumny("wizyty") and "koszt_robocizny" in pomoce.kolumny("historia")
    assert jeden("SELECT koszt_calkowity, koszt_robocizny FROM wizyty WHERE auto_id=?", (auto,)) == (750.0, None)
    assert jeden("SELECT cena, koszt_robocizny FROM historia WHERE zadanie_id=?", (zadanie,)) == (200.0, None)
    rozbicie = db.pobierz_rozbicie_napraw(auto)
    assert (rozbicie["napraw"], rozbicie["bez_podzialu"], rozbicie["kwota_bez_podzialu"]) == (0, 2, 950.0)


# ============================================================================
#  SYNCHRONIZACJA
# ============================================================================

class _Odpowiedz:
    def __init__(self, data=None):
        self.data = data


class ChmuraWPamieci:
    """Supabase na tyle, na ile potrzebuje go `_wypchnij_tabele`."""

    def __init__(self, rekordy=None):
        self.rekordy = dict(rekordy or {})
        self.wyslane = []

    def rpc(self, nazwa, parametry):
        chmura = self

        class _Wywolanie:
            def execute(self):
                chmura.wyslane.append((nazwa, parametry))
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


KONFIG_WIZYT = next(k for k in sync.KONFIGURACJA_SYNC if k["tabela"] == "wizyty")


def dane_wizyty(w_id, bez=()):
    with db.polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        wiersz = conn.execute("SELECT * FROM wizyty WHERE id=?", (w_id,)).fetchone()
    return {k: wiersz[k] for k in KONFIG_WIZYT["kolumny"] if k not in bez}


@pytest.fixture
def wizyta_sprzed_aktualizacji(baza):
    """Wizyta zsynchronizowana starszą wersją: hash i rekord w chmurze bez
    klucza `koszt_robocizny`, bo tej kolumny jeszcze nie było."""
    d = pojazd()
    w_id = wizyta(d["auto_id"], 750.0)
    stare = dane_wizyty(w_id, bez=("koszt_robocizny",))
    with db.polacz_baze() as conn:
        conn.execute("UPDATE wizyty SET zdalne_id='wiz-A', zdalny_hash=? WHERE id=?",
                     (sync_wysylanie._hash_zawartosci(stare), w_id))
    sync_konflikty._konflikty_biezacej_synchronizacji.clear()
    return {"auto_id": d["auto_id"], "w_id": w_id, "stare": stare}


def test_nowa_kolumna_jest_w_synchronizacji_jako_dopisana():
    for tabela in ("wizyty", "historia"):
        konfig = next(k for k in sync.KONFIGURACJA_SYNC if k["tabela"] == tabela)
        assert "koszt_robocizny" in konfig["kolumny"] and "koszt_robocizny" in konfig["dopisane"]
    for konfig in sync.KONFIGURACJA_SYNC:
        assert set(konfig.get("dopisane") or ()) <= set(konfig["kolumny"]), konfig["tabela"]


def test_pusta_dopisana_kolumna_nie_zmienia_rekordu():
    stare = {"koszt_calkowity": 750.0, "notatki": None}
    hash_stary = sync_wysylanie._hash_zawartosci(stare)
    assert sync_wysylanie._zgodny_z_zapamietanym({**stare, "koszt_robocizny": None}, hash_stary, {"koszt_robocizny"})
    assert not sync_wysylanie._zgodny_z_zapamietanym({**stare, "koszt_robocizny": 300.0}, hash_stary, {"koszt_robocizny"})
    # Pusta kolumna spoza `dopisane` to zwykła zmiana treści.
    assert not sync_wysylanie._zgodny_z_zapamietanym({**stare, "tagi": None}, hash_stary, {"koszt_robocizny"})


def test_pierwsza_synchronizacja_po_aktualizacji_niczego_nie_wysyla(wizyta_sprzed_aktualizacji):
    chmura = ChmuraWPamieci({"wiz-A": wizyta_sprzed_aktualizacji["stare"]})
    wyslano, _ = sync_wysylanie._wypchnij_tabele(chmura, "wspolny", wizyta_sprzed_aktualizacji["auto_id"],
                                                KONFIG_WIZYT, db.ROLA_WLASCICIEL)
    assert (wyslano, chmura.wyslane) == (0, [])

    # Bez tolerancji ta sama wizyta poleciałaby jeszcze raz — tak jak każda
    # inna wizyta i każdy wpis historii zaraz po aktualizacji.
    kopia = ChmuraWPamieci({"wiz-A": wizyta_sprzed_aktualizacji["stare"]})
    wyslano, _ = sync_wysylanie._wypchnij_tabele(kopia, "wspolny", wizyta_sprzed_aktualizacji["auto_id"],
                                                {**KONFIG_WIZYT, "dopisane": []}, db.ROLA_WLASCICIEL)
    assert wyslano == 1


def test_drugi_telefon_nie_widzi_konfliktu_w_wersji_z_pusta_kolumna(wizyta_sprzed_aktualizacji):
    """Pierwszy telefon po aktualizacji wysłał wizytę z pustym kluczem. Drugi
    rozbija ją u siebie: to jego zmiana, a nie konflikt z tamtą wysyłką."""
    w = wizyta_sprzed_aktualizacji
    chmura = ChmuraWPamieci({"wiz-A": {**w["stare"], "koszt_robocizny": None}})
    with db.polacz_baze() as conn:
        conn.execute("UPDATE wizyty SET koszt_robocizny=300 WHERE id=?", (w["w_id"],))

    wyslano, _ = sync_wysylanie._wypchnij_tabele(chmura, "wspolny", w["auto_id"], KONFIG_WIZYT, db.ROLA_WLASCICIEL)

    assert wyslano == 1 and chmura.rekordy["wiz-A"]["koszt_robocizny"] == 300
    assert sync_konflikty._konflikty_biezacej_synchronizacji == []
    # Po wysyłce zapamiętany hash jest już pełny — kolejny przebieg nic nie wysyła.
    assert sync_wysylanie._wypchnij_tabele(chmura, "wspolny", w["auto_id"], KONFIG_WIZYT, db.ROLA_WLASCICIEL)[0] == 0


def test_prawdziwy_konflikt_nadal_jest_konfliktem(wizyta_sprzed_aktualizacji):
    w = wizyta_sprzed_aktualizacji
    chmura = ChmuraWPamieci({"wiz-A": {**w["stare"], "koszt_calkowity": 999.0}})
    with db.polacz_baze() as conn:
        conn.execute("UPDATE wizyty SET koszt_robocizny=300 WHERE id=?", (w["w_id"],))

    sync_wysylanie._wypchnij_tabele(chmura, "wspolny", w["auto_id"], KONFIG_WIZYT, db.ROLA_WLASCICIEL)

    assert len(sync_konflikty._konflikty_biezacej_synchronizacji) == 1


# ============================================================================
#  FORMULARZE
# ============================================================================

def test_nowa_wizyta_z_podzialem_i_czesciami_z_magazynu(baza, bez_nawigacji):
    d = pojazd()
    stan = pomoce.stan_aplikacji(d["auto_id"], "Rozbity")

    widok = formularz_wizyty(stan)
    koszt = widok.koszt
    assert koszt.czy_podzial() and koszt.wiersz_podzialu.visible and not koszt.e_kwota.visible
    widok.e_p.value = "120100"
    next(chk for chk in widok.chk_czesci if chk.data == d["olej_zad"]).value = True
    wpisz(koszt.e_robocizna, "300")
    wpisz(koszt.e_czesci, "450")
    assert koszt.podsumowanie.value == "Razem 750,00 PLN"
    widok.zuzycie.c_uzyj.value = True
    pozycja = next(p for p in widok.zuzycie._pozycje if p["id"] == d["olej"])
    pozycja["chk"].value, pozycja["pole"].value = True, "2"
    widok.zuzycie.przelicz()
    assert koszt.podsumowanie.value == "+ części z magazynu 60,00 PLN = razem 810,00 PLN"
    widok.zapisz(None)

    w_id = jeden("SELECT MAX(id) FROM wizyty")
    assert jeden("SELECT koszt_calkowity, koszt_robocizny FROM wizyty WHERE id=?", (w_id,)) == (810.0, 300.0)

    # Edycja: te same dwie kwoty, bez części z magazynu, a zapis bez zmian nic nie rusza.
    widok = formularz_wizyty(stan, w_id)
    assert widok.koszt.czy_podzial()
    assert (widok.koszt.e_robocizna.value, widok.koszt.e_czesci.value) == ("300", "450")
    assert not widok._czy_zmieniono()
    widok.zapisz(None)
    assert jeden("SELECT koszt_calkowity, koszt_robocizny FROM wizyty WHERE id=?", (w_id,)) == (810.0, 300.0)

    # Duplikat przenosi podział, ale nie części z magazynu.
    stan.duplikuj_zrodlo_wizyta = w_id
    duplikat = formularz_wizyty(stan)
    assert (duplikat.koszt.e_robocizna.value, duplikat.koszt.e_czesci.value) == ("300", "450")
    assert duplikat.zuzycie.c_uzyj.value is False


def test_stara_wizyte_rozbija_sie_jedna_liczba(baza, bez_nawigacji):
    d = pojazd()
    w_id = wizyta(d["auto_id"], 750.0, zadania=[d["olej_zad"]])
    stan = pomoce.stan_aplikacji(d["auto_id"], "Rozbity")

    widok = formularz_wizyty(stan, w_id)
    koszt = widok.koszt
    assert not koszt.czy_podzial() and koszt.e_kwota.value == "750"

    koszt.przelacz(True)
    assert (koszt.e_robocizna.value, koszt.e_czesci.value) == ("", "750")
    wpisz(koszt.e_robocizna, "300")
    assert koszt.e_czesci.value == "450", "części maleją o wpisywaną robociznę"
    wpisz(koszt.e_czesci, "400")
    wpisz(koszt.e_robocizna, "350")
    assert koszt.e_czesci.value == "400", "części poprawione ręcznie już się nie przeliczają"
    widok.zapisz(None)

    assert jeden("SELECT koszt_calkowity, koszt_robocizny FROM wizyty WHERE id=?", (w_id,)) == (750.0, 350.0)


def test_przelaczanie_nie_gubi_kwoty_i_nie_jest_zmiana(baza, bez_nawigacji):
    d = pojazd()
    stan = pomoce.stan_aplikacji(d["auto_id"], "Rozbity")
    widok = formularz_wizyty(stan)
    koszt = widok.koszt
    wpisz(koszt.e_robocizna, "120")
    wpisz(koszt.e_czesci, "80,5")
    migawka = koszt.migawka()

    koszt.przelacz(False)
    assert koszt.e_kwota.value == "200,5" and koszt.e_kwota.visible and not koszt.wiersz_podzialu.visible
    koszt.przelacz(True)
    assert koszt.e_czesci.value == "200,5" and koszt.e_robocizna.value == ""
    wpisz(koszt.e_robocizna, "120")
    wpisz(koszt.e_czesci, "80,5")
    assert koszt.migawka() == migawka


def test_jedna_kwota_to_bez_podzialu_a_ujemna_nie_przechodzi(baza, bez_nawigacji):
    d = pojazd()
    stan = pomoce.stan_aplikacji(d["auto_id"], "Rozbity")
    widok = formularz_wizyty(stan)
    widok.e_p.value = "120100"
    next(chk for chk in widok.chk_czesci if chk.data == d["olej_zad"]).value = True

    wpisz(widok.koszt.e_robocizna, "-10")
    widok.zapisz(None)
    assert utils.blad_kontrolki(widok.koszt.e_robocizna) and jeden("SELECT COUNT(*) FROM wizyty") == 0

    widok.koszt.przelacz(False)
    wpisz(widok.koszt.e_kwota, "640")
    widok.zapisz(None)
    assert jeden("SELECT koszt_calkowity, koszt_robocizny FROM wizyty") == (640.0, None)


def test_wymiana_zrobiona_samemu_to_robocizna_zero(baza, bez_nawigacji):
    from views.history_view import HistoriaView

    d = pojazd()
    stan = pomoce.stan_aplikacji(d["auto_id"], "Rozbity")
    widok = formularz_wpisu(stan, d["olej_zad"])
    assert widok.koszt.czy_podzial()
    widok.e_p.value = "120100"
    wpisz(widok.koszt.e_czesci, "150")
    widok.zapisz(None)

    h_id = jeden("SELECT MAX(id) FROM historia")
    assert jeden("SELECT cena, koszt_robocizny FROM historia WHERE id=?", (h_id,)) == (150.0, 0.0)
    edycja = formularz_wpisu(stan, d["olej_zad"], h_id)
    assert (edycja.koszt.e_robocizna.value, edycja.koszt.e_czesci.value) == ("", "150")
    assert "Robocizna 0,00 PLN · części 150,00 PLN" in teksty(zbuduj(HistoriaView, stan, d["olej_zad"]))


def test_pola_kosztu_przechodza_audyty_drzewa(baza, bez_nawigacji):
    d = pojazd()
    stan = pomoce.stan_aplikacji(d["auto_id"], "Rozbity")
    for widok in (formularz_wizyty(stan), formularz_wpisu(stan, d["olej_zad"])):
        kolumna = ft.Column(widok.koszt.kontrolki())
        assert audyty.znajdz_expand_bez_ograniczenia(kolumna) == []
        assert audyty.znajdz_expand_w_kontenerze(kolumna) == []
        assert audyty.znajdz_pogrubienia_na_drugim_planie(kolumna) == []


# ============================================================================
#  LISTY
# ============================================================================

def test_karty_wizyt_i_filtr_bez_podzialu(baza, bez_nawigacji):
    from views.history_view import WizytyZbiorczeView

    d = pojazd()
    wizyta(d["auto_id"], 810.0, 300.0, zadania=[d["olej_zad"]], z_magazynu=60.0, magazyn_id=d["olej"])
    wizyta(d["auto_id"], 700.0, None, zadania=[d["klocki_zad"]])
    wizyta(d["auto_id"], 0.0, None, zadania=[d["klocki_zad"]])
    stan = pomoce.stan_aplikacji(d["auto_id"], "Rozbity")

    widok = zbuduj(WizytyZbiorczeView, stan)
    napisy = teksty(widok)
    assert "Robocizna 300,00 PLN · części 510,00 PLN (w tym własne 60,00 PLN)" in napisy
    assert napisy.count("Bez podziału na robociznę i części") == 1, "wizyta za zero nie czeka na rozbicie"
    assert len(widok.wszystkie_karty) == 3

    stan.filtry["wizyty_podzial"] = utils.PODZIAL_NIE
    widok = zbuduj(WizytyZbiorczeView, stan)
    assert [k["kwota"] for k in widok.wszystkie_karty] == [700.0]


def test_historia_podzespolu_ma_filtr_podzialu_tylko_dla_wpisow(baza, bez_nawigacji):
    from views.history_view import HistoriaView

    d = pojazd()
    wpis(d["olej_zad"], 400.0, 100.0)
    wpis(d["olej_zad"], 250.0)
    wizyta(d["auto_id"], 900.0, 300.0, zadania=[d["olej_zad"]])
    stan = pomoce.stan_aplikacji(d["auto_id"], "Rozbity")

    napisy = teksty(zbuduj(HistoriaView, stan, d["olej_zad"]))
    assert "Robocizna 100,00 PLN · części 300,00 PLN" in napisy
    assert "Bez podziału na robociznę i części" in napisy
    assert not any(t.startswith("Robocizna 300,00") for t in napisy), "rozbicie wizyty niesie wizyta, nie pozycja"

    stan.filtry["historia_podzial"] = utils.PODZIAL_TAK
    widok = zbuduj(HistoriaView, stan, d["olej_zad"])
    assert [k["kwota"] for k in widok.wszystkie_karty] == [400.0]


# ============================================================================
#  ANALIZA I PORÓWNANIA
# ============================================================================

def naprawy_do_analizy(d):
    auto, olej = d["auto_id"], d["olej"]
    wizyta(auto, 1000.0, 400.0, "AutoFix", [d["olej_zad"], d["klocki_zad"]], data=dni_temu(20))
    wizyta(auto, 500.0, 300.0, "autofix ", [d["klocki_zad"]], z_magazynu=100.0, magazyn_id=olej, data=dni_temu(40))
    wizyta(auto, 600.0, 150.0, "Mechanik Nowak", [d["klocki_zad"]], data=dni_temu(60))
    wizyta(auto, 700.0, None, "Mechanik Nowak", [d["klocki_zad"]], data=dni_temu(80))
    wizyta(auto, 0.0, None, "AutoFix", [d["klocki_zad"]], data=dni_temu(90))
    wizyta(auto, 2000.0, 1000.0, "AutoFix", [d["klocki_zad"]], data=dni_temu(900))
    # Wymiana zrobiona samemu olejem z półki: nic na rachunku.
    wpis(d["olej_zad"], 200.0, 0.0, "Warsztat", z_magazynu=200.0, magazyn_id=olej, data=dni_temu(10))


def test_rozbicie_napraw_w_okresie_i_warsztaty(baza):
    d = pojazd()
    naprawy_do_analizy(d)

    r = db.pobierz_rozbicie_napraw(d["auto_id"], date.today() - timedelta(days=365))
    assert (r["robocizna"], r["czesci"], r["z_magazynu"], r["razem"]) == (850.0, 1150.0, 300.0, 2300.0)
    assert (r["napraw"], r["bez_podzialu"], r["kwota_bez_podzialu"]) == (4, 1, 700.0)
    warsztaty = [(w["nazwa"].lower(), w["napraw"], w["srednia_robocizna"], w["udzial_robocizny"]) for w in r["warsztaty"]]
    assert warsztaty == [("autofix", 2, 350.0, 50.0), ("mechanik nowak", 1, 150.0, 25.0)]

    calosc = db.pobierz_rozbicie_napraw(d["auto_id"])
    assert calosc["napraw"] == 5 and calosc["robocizna"] == 1850.0


def test_porownanie_czesci_tylko_z_napraw_jednego_podzespolu(baza):
    d = pojazd()
    auto, olej = d["auto_id"], d["olej"]
    # Z warsztatu: robocizna i części na rachunku, nic z półki.
    wpis(d["olej_zad"], 400.0, 100.0)
    wizyta(auto, 450.0, 150.0, zadania=[d["olej_zad"]])
    # Własne: części wyłącznie z magazynu.
    wpis(d["olej_zad"], 200.0, 0.0, z_magazynu=200.0, magazyn_id=olej)
    wizyta(auto, 320.0, 120.0, zadania=[d["olej_zad"]], z_magazynu=200.0, magazyn_id=olej)
    # Nie mówią nic: mieszana, bez podziału, wizyta z dwoma podzespołami.
    wpis(d["olej_zad"], 250.0, 100.0, z_magazynu=100.0, magazyn_id=olej)
    wpis(d["olej_zad"], 500.0)
    wizyta(auto, 900.0, 300.0, zadania=[d["olej_zad"], d["klocki_zad"]])
    # Klocki tylko z warsztatu — nie ma z czym porównać.
    wpis(d["klocki_zad"], 600.0, 200.0)

    assert db.porownaj_czesci_wlasne(auto) == [{
        "zadanie_id": d["olej_zad"], "nazwa": "Olej silnikowy i filtr",
        "z_warsztatu": 300.0, "ile_z_warsztatu": 2, "wlasne": 200.0, "ile_wlasnych": 2, "roznica": 100.0,
    }]


def test_obserwacje_robocizny_i_czesci(baza):
    d = pojazd()
    auto, olej = d["auto_id"], d["olej"]
    assert not {"robocizna_czesci", "czesci_wlasne"} & {o["klucz"] for o in db.obserwacje_analityczne(auto)}

    wpis(d["olej_zad"], 400.0, 100.0, "AutoFix")
    wpis(d["olej_zad"], 200.0, 0.0, z_magazynu=200.0, magazyn_id=olej)
    wizyta(auto, 600.0, 400.0, "AutoFix", [d["klocki_zad"]])
    wizyta(auto, 300.0, 100.0, "Tani Serwis", [d["klocki_zad"]])
    wizyta(auto, 300.0, 100.0, "Tani Serwis", [d["klocki_zad"]])
    wizyta(auto, 500.0, None, "AutoFix", [d["klocki_zad"]])

    obserwacje = {o["klucz"]: o for o in db.obserwacje_analityczne(auto)}
    robocizna = obserwacje["robocizna_czesci"]
    # 100 + 0 + 400 + 100 + 100 = 700 z 1800.
    assert robocizna["tekst"].startswith("W ostatnich 12 miesiącach robocizna to 39% kosztu napraw (700 PLN z 1800 PLN)")
    assert "— w tym 200 PLN z własnego magazynu" in robocizna["tekst"]
    assert "Najdrożej liczy „AutoFix”: średnio 250 PLN robocizny na naprawę, a „Tani Serwis” 100 PLN." in robocizna["tekst"]
    assert robocizna["tekst"].endswith("Naprawy bez podziału pominięte: 1.")

    czesci = obserwacje["czesci_wlasne"]
    assert czesci["ton"] == "dobry" and czesci["trasa"] == f"/historia/{d['olej_zad']}"
    assert "o 100 PLN mniej" in czesci["tekst"]


def test_obserwacja_mowi_tez_gdy_warsztat_kupuje_taniej(baza):
    d = pojazd()
    wpis(d["olej_zad"], 250.0, 100.0)
    wpis(d["olej_zad"], 260.0, 0.0, z_magazynu=260.0, magazyn_id=d["olej"])

    czesci = {o["klucz"]: o for o in db.obserwacje_analityczne(d["auto_id"])}["czesci_wlasne"]
    assert (czesci["ton"], czesci["tytul"]) == ("neutralny", "Warsztat kupuje części taniej")
    assert "o 110 PLN drożej" in czesci["tekst"]


def test_karta_w_analizie(baza, bez_nawigacji):
    d = pojazd()
    naprawy_do_analizy(d)
    wpis(d["olej_zad"], 400.0, 100.0)
    stan = pomoce.stan_aplikacji(d["auto_id"], "Rozbity")
    rozbicie = db.pobierz_rozbicie_napraw(d["auto_id"])
    strona = pomoce.zbuduj_strone()
    karta = utils.karta_robocizny_i_czesci(strona.page, rozbicie,
                                           db.porownaj_czesci_wlasne(d["auto_id"]), utils.ScenaWejscia())
    napisy = teksty(karta)
    for tekst in ("Robocizna", "Części na rachunku", "Części z magazynu", "Warsztaty",
                  "Części z warsztatu a z magazynu", "Olej silnikowy i filtr"):
        assert tekst in napisy
    assert "Naprawy z podziałem: 6 · bez podziału: 1 na 700,00 PLN, poza porównaniem" in napisy
    assert audyty.znajdz_pogrubienia_na_drugim_planie(karta) == []
    assert audyty.znajdz_expand_bez_ograniczenia(karta) == []

    # Cała zakładka Wykresy składa się z nową kartą.
    stan.zakladka, stan.stat_podzakladka = 3, 1
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(), stan)
    assert "Robocizna czy części" in teksty(widok)


def test_karta_bez_podzialu_mowi_jak_to_naprawic(baza):
    d = pojazd()
    wizyta(d["auto_id"], 700.0, None)
    strona = pomoce.zbuduj_strone()
    napisy = teksty(utils.karta_robocizny_i_czesci(strona.page, db.pobierz_rozbicie_napraw(d["auto_id"])))
    assert any(t.startswith("Żadna naprawa z tego okresu nie ma podziału") for t in napisy)


# ============================================================================
#  EKSPORT
# ============================================================================

def test_eksport_ma_robocizne_i_czesci(baza):
    d = pojazd()
    wizyta(d["auto_id"], 810.0, 300.0, zadania=[d["olej_zad"]], z_magazynu=60.0, magazyn_id=d["olej"], data="01.09.2026")
    wizyta(d["auto_id"], 700.0, None, zadania=[d["klocki_zad"]], data="02.09.2026")
    wpis(d["olej_zad"], 150.0, 0.0, data="03.09.2026")

    dane = db.pobierz_dane_eksportu(d["auto_id"], ["wizyty", "historia"])
    f = db.formatuj_liczba_eksport

    naglowki, wiersze = dane["wizyty"]
    i_rob, i_cz = naglowki.index("Robocizna"), naglowki.index("Części")
    assert [(w[i_rob], w[i_cz]) for w in wiersze] == [(f(300.0), f(510.0)), ("", "")]

    naglowki, wiersze = dane["historia"]
    assert [(w[naglowki.index("Robocizna")], w[naglowki.index("Części")]) for w in wiersze] == [(f(0.0), f(150.0))]

    tresc, _ = db.generuj_eksport_csv(dane)
    assert tresc  # CSV składa się z nowymi kolumnami bez błędu


@pytest.mark.filterwarnings("ignore:The parameter \"ln\" is deprecated:DeprecationWarning")
def test_raport_pdf_ma_robocizne_i_czesci_bez_notatek_wizyt(baza, monkeypatch):
    """Tabela PDF dzieli szerokość po równo: dwie nowe kolumny zwężają resztę,
    więc wolny tekst notatek wizyt wypada z PDF — tak jak notatki innych wpisów."""
    from db import raporty

    d = pojazd()
    wizyta(d["auto_id"], 810.0, 300.0, zadania=[d["olej_zad"]], data="01.09.2026")
    napisy = []
    oryginal = raporty._RaportPDF.cell

    def cell(self, *argumenty, **nazwane):
        if len(argumenty) >= 3:
            napisy.append(str(argumenty[2]))
        return oryginal(self, *argumenty, **nazwane)

    monkeypatch.setattr(raporty._RaportPDF, "cell", cell)
    pdf = db.generuj_pdf_raportu("Rozbity", db.pobierz_dane_eksportu(d["auto_id"], ["wizyty"]), "wrzesień")

    assert pdf.startswith(b"%PDF")
    assert "Robocizna" in napisy and db.formatuj_liczba_eksport(300.0) in napisy
    assert "Notatki" not in napisy
