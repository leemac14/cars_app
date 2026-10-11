"""Awarie kontra eksploatacja: rodzaj naprawy (planowe / awaria / modernizacja) przy wpisie
i wizycie, udział awarii w koszcie serwisu, odstępy między awariami i sygnał „auto zaczyna
się sypać”.

Najłatwiej zepsuć: liczenie pozycji wizyty drugi raz obok wizyty, fałszywy alarm zaraz po
aktualizacji (stare naprawy nie mają rodzaju), synchronizację (pusta nowa kolumna nie może
wysłać całej historii) i podpowiedź w formularzu, która nadpisałaby wybór użytkownika.
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
from sync import wysylanie as sync_wysylanie


DRABINKA = probki_baz.wczytaj_drabinke()


# ============================================================================
#  POMOCE
# ============================================================================

@pytest.fixture
def bez_nawigacji(monkeypatch):
    monkeypatch.setattr(utils, "przejdz", lambda page, trasa: None)
    monkeypatch.setattr(utils, "pokaz_komunikat", lambda page, tekst, *a, **k: None)


def dzien(dni):
    return date.today() - timedelta(days=dni)


def pojazd(nazwa="Sypiący"):
    """Auto z olejem (interwał km), rozrządem (interwał miesięcy) i alternatorem (bez interwału)."""
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO samochody (nazwa, typ_paliwa, status, rola_wspoldzielenia) VALUES (?,?,?,?)",
                  (nazwa, "Benzyna", db.STATUS_POJAZDU_AKTYWNY, db.ROLA_WLASCICIEL))
        auto = c.lastrowid
        wynik = {"auto_id": auto}
        for klucz, nazwa_z, km, miesiace in (("olej", "Olej silnikowy i filtr", 15000, None),
                                              ("rozrzad", "Rozrząd", None, 60),
                                              ("alternator", "Alternator", None, None)):
            c.execute("INSERT INTO zadania (auto_id, nazwa, interwal_km, interwal_miesiace) VALUES (?,?,?,?)",
                      (auto, nazwa_z, km, miesiace))
            wynik[klucz] = c.lastrowid
    return wynik


def wizyta(auto, dni, koszt, rodzaj=None, zadania=(), przebieg=100000, autor=None):
    """Wizyta z pozycjami wpisana wprost do bazy; pozycje mają rodzaj wizyty (jak z formularza)."""
    d = dzien(dni)
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO wizyty (auto_id, data, data_iso, przebieg, wykonawca, koszt_calkowity, rodzaj, "
                  "dodane_przez) VALUES (?,?,?,?,?,?,?,?)",
                  (auto, d.strftime("%d.%m.%Y"), d.isoformat(), przebieg, "AutoFix", koszt, rodzaj, autor))
        w_id = c.lastrowid
        for zadanie in zadania:
            c.execute("INSERT INTO historia (wizyta_id, zadanie_id, data, data_iso, przebieg, cena, wykonawca, rodzaj, "
                      "dodane_przez) VALUES (?,?,?,?,?,0,?,?,?)",
                      (w_id, zadanie, d.strftime("%d.%m.%Y"), d.isoformat(), przebieg, "AutoFix", rodzaj, autor))
    return w_id


def wpis(zadanie, dni, cena, rodzaj=None, przebieg=100000, autor=None):
    d = dzien(dni)
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO historia (zadanie_id, data, data_iso, przebieg, cena, wykonawca, rodzaj, dodane_przez) "
                  "VALUES (?,?,?,?,?,?,?,?)",
                  (zadanie, d.strftime("%d.%m.%Y"), d.isoformat(), przebieg, cena, "Warsztat", rodzaj, autor))
        return c.lastrowid


def jeden(sql, parametry=()):
    with db.polacz_baze() as conn:
        wiersz = conn.execute(sql, parametry).fetchone()
    return wiersz[0] if wiersz and len(wiersz) == 1 else wiersz


def naprawy_przykladowe(d):
    """4050 zł serwisu: awarie 2300 (wizyta i wpis jednego dnia + druga awaria), planowe 600,
    modernizacja 900, bez rodzaju 250."""
    a = d["auto_id"]
    wizyta(a, 400, 600.0, db.SERWIS_PLANOWE, [d["olej"]], przebieg=90000)
    wizyta(a, 300, 1200.0, db.SERWIS_AWARIA, [d["alternator"]], przebieg=95000)
    wpis(d["alternator"], 300, 300.0, db.SERWIS_AWARIA, przebieg=95000)
    wizyta(a, 200, 900.0, db.SERWIS_MODERNIZACJA, [d["rozrzad"]], przebieg=97000)
    wpis(d["olej"], 100, 250.0, przebieg=99000)
    wizyta(a, 60, 800.0, db.SERWIS_AWARIA, [d["alternator"]], przebieg=101000)


def zbuduj(klasa, stan, *argumenty):
    strona = pomoce.zbuduj_strone()
    widok = klasa(strona.page, stan, *argumenty)
    widok._strona_testowa = strona
    return widok


def formularz_wizyty(stan, w_id=None):
    from views.formularze import FormularzWizytyView
    widok = zbuduj(FormularzWizytyView, stan, w_id)
    widok.e_kat_wizyty.update = lambda *a, **k: None
    return widok


def formularz_wpisu(stan, zadanie, h_id=None):
    from views.formularze import FormularzWpisView
    return zbuduj(FormularzWpisView, stan, h_id, zadanie)


def dotknij(pole, etykieta):
    """Segment przełącznika rodzaju dotknięty palcem — przez jego on_click."""
    segment = next(s for s in pole.przelacznik.content.content.controls if s.content.value == etykieta)
    segment.on_click(None)


def zaznacz(widok, zadanie, wartosc=True):
    chk = next(c for c in widok.chk_czesci if c.data == zadanie)
    chk.value = wartosc
    chk.on_change(None)


def klikalne(korzen):
    """[(kontrolka z on_click, jej napisy)] z całego drzewa."""
    wynik, do_odwiedzenia = [], [korzen]
    while do_odwiedzenia:
        kontrolka = do_odwiedzenia.pop()
        if getattr(kontrolka, "on_click", None):
            wynik.append((kontrolka, pomoce.napisy(kontrolka)))
        for pole in ("controls", "content"):
            dziecko = getattr(kontrolka, pole, None)
            if isinstance(dziecko, (list, tuple)):
                do_odwiedzenia.extend(x for x in dziecko if isinstance(x, ft.Control))
            elif isinstance(dziecko, ft.Control):
                do_odwiedzenia.append(dziecko)
    return wynik


def wiersz_arkusza(korzen, data):
    """Wiersz arkusza oznaczania z naprawą z tego dnia: kontener z datą i trzema chipami."""
    do_odwiedzenia = [korzen]
    while do_odwiedzenia:
        kontrolka = do_odwiedzenia.pop()
        if isinstance(kontrolka, ft.Container) and data in pomoce.napisy(kontrolka) and len(klikalne(kontrolka)) == 3:
            return kontrolka
        for pole in ("controls", "content"):
            dziecko = getattr(kontrolka, pole, None)
            if isinstance(dziecko, (list, tuple)):
                do_odwiedzenia.extend(x for x in dziecko if isinstance(x, ft.Control))
            elif isinstance(dziecko, ft.Control):
                do_odwiedzenia.append(dziecko)
    raise AssertionError(f"brak wiersza z {data}")


# ============================================================================
#  RDZEŃ
# ============================================================================

def test_rodzaj_z_bazy_i_etykieta():
    assert db.rodzaj_serwisu(" Awaria ") == db.SERWIS_AWARIA
    assert db.rodzaj_serwisu("naprawa") is None and db.rodzaj_serwisu(None) is None
    assert db.etykieta_rodzaju_serwisu("modernizacja") == "Modernizacja"
    assert db.etykieta_rodzaju_serwisu("") == db.ETYKIETA_BEZ_RODZAJU


def test_podpowiedz_planowe_tylko_gdy_kazdy_podzespol_ma_interwal(baza):
    d = pojazd()
    assert db.domyslny_rodzaj_serwisu([d["olej"]]) == db.SERWIS_PLANOWE
    assert db.domyslny_rodzaj_serwisu([d["olej"], d["rozrzad"]]) == db.SERWIS_PLANOWE, "interwał w miesiącach też"
    assert db.domyslny_rodzaj_serwisu([d["olej"], d["alternator"]]) is None
    assert db.domyslny_rodzaj_serwisu([]) is None


def test_udzial_odstepy_i_pozycje_wizyty_nie_licza_sie_drugi_raz(baza):
    d = pojazd()
    naprawy_przykladowe(d)
    dane = db.awarie_i_eksploatacja(d["auto_id"])

    assert dane["razem"] == 4050.0
    assert {r: g["kwota"] for r, g in dane["rodzaje"].items()} == {
        db.SERWIS_PLANOWE: 600.0, db.SERWIS_AWARIA: 2300.0, db.SERWIS_MODERNIZACJA: 900.0, None: 250.0}
    assert dane["udzial_awarii"] == pytest.approx(2300 / 4050 * 100)
    assert dane["nieoznaczone"] == 1, "pozycje wizyt nie są osobnymi naprawami"
    # Wizyta i wpis z tego samego dnia to jedna awaria.
    assert dane["awarie"] == 2
    assert (dane["odstep_dni"], dane["odstep_km"]) == (240, 6000)
    assert dane["odstep_ostatnich_dni"] is None, "porównanie ostatnich odstępów dopiero od czterech awarii"
    assert (dane["ostatnia_awaria"], dane["dni_od_awarii"]) == (dzien(60), 60)

    okres = db.awarie_i_eksploatacja(d["auto_id"], dzien(250))
    assert (okres["razem"], okres["awarie"], okres["odstep_dni"]) == (1950.0, 1, None)


def test_dwa_ostatnie_odstepy_kontra_wczesniejsze(baza):
    d = pojazd()
    for dni in (640, 420, 220, 120, 60):
        wizyta(d["auto_id"], dni, 500.0, db.SERWIS_AWARIA, [d["alternator"]])
    dane = db.awarie_i_eksploatacja(d["auto_id"])
    assert (dane["odstep_ostatnich_dni"], dane["odstep_wczesniej_dni"]) == (80, 210)
    sygnal = db.sygnal_awarii(d["auto_id"])
    assert sygnal["skracaja_sie"] and not sygnal["rosnie"]
    assert "awarie_czesciej" in [o["klucz"] for o in db.obserwacje_analityczne(d["auto_id"])]


def test_rosnacy_udzial_awarii_to_sygnal_i_obserwacja(baza):
    d = pojazd()
    a = d["auto_id"]
    wizyta(a, 500, 1000.0, db.SERWIS_PLANOWE, [d["olej"]])
    wizyta(a, 450, 200.0, db.SERWIS_AWARIA, [d["alternator"]])
    wizyta(a, 400, 800.0, db.SERWIS_PLANOWE, [d["olej"]])
    wizyta(a, 200, 900.0, db.SERWIS_AWARIA, [d["alternator"]])
    wizyta(a, 100, 400.0, db.SERWIS_PLANOWE, [d["olej"]])
    wizyta(a, 50, 700.0, db.SERWIS_AWARIA, [d["alternator"]])

    sygnal = db.sygnal_awarii(a)
    assert (sygnal["teraz"], sygnal["wczesniej"]) == (pytest.approx(80.0), pytest.approx(10.0))
    assert sygnal["rosnie"] and sygnal["awarie_teraz"] == 2
    obserwacja = next(o for o in db.obserwacje_analityczne(a) if o["klucz"] == "awarie_rosna")
    assert obserwacja["ton"] == "zly" and "80%" in obserwacja["tekst"] and "10%" in obserwacja["tekst"]
    assert db.metryki_kokpitu(a, ["awarie"])["awarie"]["rosnie"]


def test_po_aktualizacji_nieoznaczony_rok_nie_robi_falszywego_alarmu(baza):
    """Stare naprawy nie mają rodzaju — rok wcześniej wyglądałby na „zero awarii”."""
    d = pojazd()
    a = d["auto_id"]
    wizyta(a, 500, 1800.0, None, [d["alternator"]])
    wizyta(a, 400, 200.0, db.SERWIS_PLANOWE, [d["olej"]])
    wizyta(a, 200, 900.0, db.SERWIS_AWARIA, [d["alternator"]])
    wizyta(a, 50, 700.0, db.SERWIS_AWARIA, [d["alternator"]])

    sygnal = db.sygnal_awarii(a)
    assert sygnal["teraz"] == pytest.approx(100.0) and sygnal["wczesniej"] is None
    assert not sygnal["rosnie"] and not sygnal["maleje"]
    assert not any(o["klucz"].startswith("awarie") for o in db.obserwacje_analityczne(a))


def test_naprawy_bez_rodzaju_z_podpowiedzia_i_wedlug_roli(baza):
    d = pojazd()
    a = d["auto_id"]
    w_olej = wizyta(a, 10, 300.0, None, [d["olej"]], autor="Ola")
    w_mieszana = wizyta(a, 20, 700.0, None, [d["olej"], d["alternator"]], autor="Kamil")
    h_alt = wpis(d["alternator"], 30, 450.0, autor="Ola")
    wpis(d["olej"], 40, 200.0, db.SERWIS_PLANOWE, autor="Ola")

    lista = db.naprawy_bez_rodzaju(a)
    assert [(n["tabela"], n["id"]) for n in lista] == [("wizyty", w_olej), ("wizyty", w_mieszana), ("historia", h_alt)]
    assert [n["sugestia"] for n in lista] == [db.SERWIS_PLANOWE, None, None]
    assert lista[0]["opis"] == "Olej silnikowy i filtr" and lista[0]["kwota"] == 300.0

    db.zapisz_moje_imie("Ola")
    db.ustaw_role_pojazdu(a, db.ROLA_WSPOLAUTOR)
    assert [n["id"] for n in db.naprawy_bez_rodzaju(a)] == [w_olej, h_alt], "współautor rusza tylko swoje"
    db.ustaw_role_pojazdu(a, db.ROLA_PODGLAD)
    assert db.naprawy_bez_rodzaju(a) == []


def test_ustawienie_rodzaju_przechodzi_na_pozycje_wizyty(baza):
    d = pojazd()
    a = d["auto_id"]
    w_id = wizyta(a, 10, 700.0, None, [d["olej"], d["alternator"]])
    h_id = wpis(d["rozrzad"], 20, 1500.0)
    obca = wizyta(pojazd("Drugie")["auto_id"], 10, 100.0)
    db.zapisz_moje_imie("Kamil")

    assert db.ustaw_rodzaj_napraw(a, [("wizyty", w_id), ("historia", h_id), ("wizyty", obca)], "awaria") == 2
    assert jeden("SELECT rodzaj, zmodyfikowane_przez FROM wizyty WHERE id=?", (w_id,)) == ("awaria", "Kamil")
    assert {r for (r,) in sqlite3.connect(db.BAZA_DANYCH).execute(
        "SELECT rodzaj FROM historia WHERE wizyta_id=?", (w_id,))} == {"awaria"}
    assert jeden("SELECT rodzaj FROM historia WHERE id=?", (h_id,)) == "awaria"
    assert jeden("SELECT rodzaj FROM wizyty WHERE id=?", (obca,)) is None, "wizyta innego auta zostaje"
    assert db.naprawy_bez_rodzaju(a) == []


def test_wizyta_z_listy_do_zrobienia_dostaje_podpowiedz(baza):
    d = pojazd()
    a = d["auto_id"]

    def zadanie_do_zrobienia(tytul, zadanie):
        with db.polacz_baze() as conn:
            return conn.execute("INSERT INTO do_zrobienia (auto_id, tytul, zadanie_id, wykonane) VALUES (?,?,?,0)",
                                (a, tytul, zadanie)).lastrowid

    w_id, _, _ = db.utworz_wizyte_z_do_zrobienia(a, [zadanie_do_zrobienia("Olej", d["olej"]),
                                                     zadanie_do_zrobienia("Rozrząd", d["rozrzad"])])
    assert jeden("SELECT rodzaj FROM wizyty WHERE id=?", (w_id,)) == db.SERWIS_PLANOWE
    assert jeden("SELECT COUNT(*) FROM historia WHERE wizyta_id=? AND rodzaj='planowe'", (w_id,)) == 2

    w_id, _, _ = db.utworz_wizyte_z_do_zrobienia(a, [zadanie_do_zrobienia("Stuk", d["alternator"])])
    assert jeden("SELECT rodzaj FROM wizyty WHERE id=?", (w_id,)) is None


def test_migracja_zostawia_stare_naprawy_bez_rodzaju(magazyn):
    probki_baz.zbuduj_baze_w_wersji(db.BAZA_DANYCH, 51, DRABINKA)
    conn = sqlite3.connect(db.BAZA_DANYCH)
    c = conn.cursor()
    c.execute("INSERT INTO samochody (nazwa, typ_paliwa) VALUES ('Stary', 'Benzyna')")
    auto = c.lastrowid
    c.execute("INSERT INTO zadania (auto_id, nazwa, interwal_km) VALUES (?, 'Olej', 15000)", (auto,))
    zadanie = c.lastrowid
    c.execute("INSERT INTO wizyty (auto_id, data, data_iso, przebieg, koszt_calkowity) "
              "VALUES (?, '01.09.2026', '2026-09-01', 135000, 750.0)", (auto,))
    c.execute("INSERT INTO historia (zadanie_id, data, data_iso, przebieg, cena) "
              "VALUES (?, '14.09.2026', '2026-09-14', 135830, 200.0)", (zadanie,))
    conn.commit()
    conn.close()

    db.init_db()

    assert "rodzaj" in pomoce.kolumny("wizyty") and "rodzaj" in pomoce.kolumny("historia")
    assert jeden("SELECT rodzaj FROM wizyty WHERE auto_id=?", (auto,)) is None
    assert jeden("SELECT rodzaj FROM historia WHERE zadanie_id=?", (zadanie,)) is None
    dane = db.awarie_i_eksploatacja(auto)
    assert (dane["razem"], dane["nieoznaczone"], dane["udzial_awarii"]) == (950.0, 2, 0.0)


# ============================================================================
#  SYNCHRONIZACJA
# ============================================================================

def test_rodzaj_jedzie_do_chmury_jako_ostatnia_dopisana_kolumna():
    for tabela in ("wizyty", "historia"):
        konfig = next(k for k in sync.KONFIGURACJA_SYNC if k["tabela"] == tabela)
        assert "rodzaj" in konfig["kolumny"] and konfig["dopisane"][-1] == "rodzaj", tabela


def test_wpis_sprzed_aktualizacji_nie_jest_zmiana_dopoki_nie_dostanie_rodzaju(baza):
    """Hash zapamiętany starszą wersją nie zna klucza `rodzaj` — także „między aktualizacjami”
    (po robociźnie, przed gwarancją)."""
    d = pojazd()
    h_id = wpis(d["olej"], 30, 200.0)
    konfig = next(k for k in sync.KONFIGURACJA_SYNC if k["tabela"] == "historia")
    dopisane = frozenset(konfig["dopisane"])
    with db.polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        wiersz = dict(conn.execute("SELECT * FROM historia WHERE id=?", (h_id,)).fetchone())
    teraz = {k: wiersz[k] for k in konfig["kolumny"]}
    hash_ = sync_wysylanie._hash_zawartosci
    zgodny = sync_wysylanie._zgodny_z_zapamietanym

    sprzed_rodzaju = {k: v for k, v in teraz.items() if k != "rodzaj"}
    sprzed_gwarancji = {k: v for k, v in sprzed_rodzaju.items() if not k.startswith("gwarancja")}
    assert zgodny(teraz, hash_(sprzed_rodzaju), dopisane)
    assert zgodny(teraz, hash_(sprzed_gwarancji), dopisane)
    assert not zgodny({**teraz, "rodzaj": db.SERWIS_AWARIA}, hash_(sprzed_rodzaju), dopisane)


# ============================================================================
#  EKSPORT, WYSZUKIWARKA, PIGUŁKA, ZAKRES
# ============================================================================

def test_eksport_ma_kolumne_rodzaju(baza):
    d = pojazd()
    wizyta(d["auto_id"], 20, 800.0, db.SERWIS_AWARIA, [d["alternator"]])
    wizyta(d["auto_id"], 10, 300.0, None, [d["olej"]])
    wpis(d["rozrzad"], 30, 900.0, db.SERWIS_MODERNIZACJA)
    dane = db.pobierz_dane_eksportu(d["auto_id"], ["wizyty", "historia"])

    naglowki, wiersze = dane["wizyty"]
    assert [w[naglowki.index("Rodzaj")] for w in wiersze] == ["Awaria", ""]
    naglowki, wiersze = dane["historia"]
    assert [w[naglowki.index("Rodzaj")] for w in wiersze] == ["Modernizacja"]
    tresc, _ = db.generuj_eksport_csv(dane)
    assert tresc


def test_wyszukiwarka_znajduje_awarie_i_modernizacje(baza):
    d = pojazd()
    wizyta(d["auto_id"], 20, 800.0, db.SERWIS_AWARIA, [d["alternator"]])
    wizyta(d["auto_id"], 10, 300.0, db.SERWIS_PLANOWE, [d["olej"]])
    wpis(d["rozrzad"], 30, 900.0, db.SERWIS_MODERNIZACJA)

    awarie = db.globalne_wyszukiwanie(d["auto_id"], "awaria")
    assert [w["typ"] for w in awarie] == ["Wizyta zbiorcza"] and "Awaria" in awarie[0]["opis"]
    assert [w["tytul"] for w in db.globalne_wyszukiwanie(d["auto_id"], "modernizacja")] == ["Rozrząd"]
    planowe = db.globalne_wyszukiwanie(d["auto_id"], "planowe")
    assert len(planowe) == 1 and "Planowe" not in planowe[0]["opis"], "dopisek tylko przy awarii i modernizacji"


def test_rok_w_pigulce_liczy_awarie_okresu(baza):
    d = pojazd()
    rok = date.today().year - 1
    with db.polacz_baze() as conn:
        for dzien_roku, koszt, rodzaj in (("03-10", 1000.0, db.SERWIS_PLANOWE), ("06-01", 600.0, db.SERWIS_AWARIA),
                                          ("06-01", 400.0, db.SERWIS_AWARIA), ("09-15", 500.0, None)):
            conn.execute("INSERT INTO wizyty (auto_id, data, data_iso, przebieg, koszt_calkowity, rodzaj) "
                         "VALUES (?,?,?,?,?,?)", (d["auto_id"], f"{dzien_roku[3:]}.{dzien_roku[:2]}.{rok}",
                                                  f"{rok}-{dzien_roku}", 100000, koszt, rodzaj))
    awarie = db.podsumowanie_roku(d["auto_id"], rok)["awarie"]
    assert (awarie["razem"], awarie["awarie"], awarie["nieoznaczone"]) == (2500.0, 1, 1)
    assert awarie["udzial_awarii"] == pytest.approx(40.0)

    from views.rok_view import RokWPigulceView
    stan = pomoce.stan_aplikacji(d["auto_id"], "Sypiący")
    napisy = pomoce.napisy(RokWPigulceView(pomoce.zbuduj_strone().page, stan, rok))
    assert "Awarie kontra eksploatacja" in napisy
    assert any(t.startswith("1 awaria za 1 000,00") for t in napisy)


def test_wykres_awarii_domyslnie_na_calej_historii(baza):
    d = pojazd()
    assert db.pobierz_zakres_wykresu(d["auto_id"], "awarie") == 0
    assert db.pobierz_zakres_wykresu(d["auto_id"], "wydatki") == db.ZAKRES_WYKRESU_DOMYSLNY
    db.zapisz_zakres_wykresu(d["auto_id"], "awarie", 12)
    assert db.pobierz_zakres_wykresu(d["auto_id"], "awarie") == 12


# ============================================================================
#  FORMULARZE
# ============================================================================

def test_formularz_wpisu_podpowiada_i_zapisuje_rodzaj(baza, bez_nawigacji):
    d = pojazd()
    stan = pomoce.stan_aplikacji(d["auto_id"], "Sypiący")

    widok = formularz_wpisu(stan, d["olej"])
    assert widok.rodzaj.wartosc == db.SERWIS_PLANOWE
    widok.e_p.value = "100500"
    widok.zapisz(None)
    assert jeden("SELECT rodzaj FROM historia ORDER BY id DESC LIMIT 1") == db.SERWIS_PLANOWE

    widok = formularz_wpisu(stan, d["alternator"])
    assert widok.rodzaj.wartosc is None
    dotknij(widok.rodzaj, "Awaria")
    assert widok.rodzaj.opis.value == utils.OPISY_RODZAJU[db.SERWIS_AWARIA]
    widok.e_p.value = "100600"
    widok.zapisz(None)
    h_id = jeden("SELECT MAX(id) FROM historia")
    assert jeden("SELECT rodzaj FROM historia WHERE id=?", (h_id,)) == db.SERWIS_AWARIA

    # Edycja trzyma zapisany; drugie dotknięcie zdejmuje wybór i jest zmianą.
    widok = formularz_wpisu(stan, d["alternator"], h_id)
    assert widok.rodzaj.wartosc == db.SERWIS_AWARIA and not widok._czy_zmieniono()
    dotknij(widok.rodzaj, "Awaria")
    assert widok.rodzaj.wartosc is None and widok._czy_zmieniono()
    widok.zapisz(None)
    assert jeden("SELECT rodzaj FROM historia WHERE id=?", (h_id,)) is None


def test_formularz_wizyty_podpowiada_do_pierwszego_dotkniecia(baza, bez_nawigacji):
    d = pojazd()
    stan = pomoce.stan_aplikacji(d["auto_id"], "Sypiący")

    widok = formularz_wizyty(stan)
    assert widok.rodzaj.wartosc is None
    zaznacz(widok, d["olej"])
    assert widok.rodzaj.wartosc == db.SERWIS_PLANOWE
    zaznacz(widok, d["alternator"])
    assert widok.rodzaj.wartosc is None, "podzespół bez interwału zdejmuje podpowiedź"
    dotknij(widok.rodzaj, "Awaria")
    zaznacz(widok, d["alternator"], False)
    assert widok.rodzaj.wartosc == db.SERWIS_AWARIA, "wybór użytkownika zostaje"
    widok.e_p.value = "100500"
    widok.koszt.e_robocizna.value = "300"
    widok.zapisz(None)
    w_id = jeden("SELECT MAX(id) FROM wizyty")
    assert jeden("SELECT rodzaj FROM wizyty WHERE id=?", (w_id,)) == db.SERWIS_AWARIA
    assert jeden("SELECT rodzaj FROM historia WHERE wizyta_id=?", (w_id,)) == db.SERWIS_AWARIA

    widok = formularz_wizyty(stan, w_id)
    assert widok.rodzaj.wartosc == db.SERWIS_AWARIA and not widok._czy_zmieniono()
    zaznacz(widok, d["rozrzad"])
    assert widok.rodzaj.wartosc == db.SERWIS_AWARIA, "edycja nie podpowiada"
    dotknij(widok.rodzaj, "Modernizacja")
    widok.zapisz(None)
    assert jeden("SELECT COUNT(*) FROM historia WHERE wizyta_id=? AND rodzaj='modernizacja'", (w_id,)) == 2

    stan.duplikuj_zrodlo_wizyta = w_id
    assert formularz_wizyty(stan).rodzaj.wartosc == db.SERWIS_MODERNIZACJA


def test_pole_rodzaju_przechodzi_audyty_drzewa(baza, bez_nawigacji):
    d = pojazd()
    stan = pomoce.stan_aplikacji(d["auto_id"], "Sypiący")
    for widok in (formularz_wizyty(stan), formularz_wpisu(stan, d["olej"])):
        kolumna = ft.Column([widok.rodzaj.kontrolka])
        assert audyty.znajdz_expand_bez_ograniczenia(kolumna) == []
        assert audyty.znajdz_expand_w_kontenerze(kolumna) == []
        assert audyty.znajdz_pogrubienia_na_drugim_planie(kolumna) == []


# ============================================================================
#  LISTY, ANALIZA, ARKUSZ, KOKPIT
# ============================================================================

def test_chip_i_filtr_rodzaju_na_listach(baza, bez_nawigacji):
    from views.history_view import HistoriaView, WizytyZbiorczeView

    d = pojazd()
    a = d["auto_id"]
    wizyta(a, 30, 800.0, db.SERWIS_AWARIA, [d["alternator"]])
    wizyta(a, 60, 500.0, db.SERWIS_PLANOWE, [d["olej"]])
    wizyta(a, 90, 300.0, None, [d["olej"]])
    stan = pomoce.stan_aplikacji(a, "Sypiący")

    widok = zbuduj(WizytyZbiorczeView, stan)
    karty = {k["kwota"]: pomoce.napisy(k["karta"]) for k in widok.wszystkie_karty}
    assert "Awaria" in karty[800.0]
    assert "Planowe" not in karty[500.0] and db.ETYKIETA_BEZ_RODZAJU not in karty[300.0]

    stan.filtry["wizyty_rodzaj"] = "Awaria"
    assert [k["kwota"] for k in zbuduj(WizytyZbiorczeView, stan).wszystkie_karty] == [800.0]
    stan.filtry["wizyty_rodzaj"] = db.ETYKIETA_BEZ_RODZAJU
    assert [k["kwota"] for k in zbuduj(WizytyZbiorczeView, stan).wszystkie_karty] == [300.0]

    stan.filtry["historia_rodzaj"] = "Planowe"
    assert len(zbuduj(HistoriaView, stan, d["olej"]).wszystkie_karty) == 1
    stan.filtry["historia_rodzaj"] = "Awaria"
    widok = zbuduj(HistoriaView, stan, d["alternator"])
    assert len(widok.wszystkie_karty) == 1 and "Awaria" in pomoce.napisy(widok.wszystkie_karty[0]["karta"])


def test_karta_w_analizie_i_zakladka_wykresy(baza, bez_nawigacji):
    d = pojazd()
    naprawy_przykladowe(d)
    a = d["auto_id"]
    strona = pomoce.zbuduj_strone()
    karta = utils.karta_awarii(strona.page, a, db.awarie_i_eksploatacja(a), 0, utils.ScenaWejscia())
    napisy = pomoce.napisy(karta)

    assert "57%" in napisy and "kosztu serwisu to awarie" in napisy
    for tekst in ("Planowe", "Awarie", "Modernizacje", db.ETYKIETA_BEZ_RODZAJU, "Oznacz",
                  "Średni odstęp między awariami (2)", f"co 240 dni · {utils.formatuj_dystans(6000, 0, 'km')}"):
        assert tekst in napisy, tekst
    assert any(t.startswith("1 naprawa bez rodzaju") for t in napisy)
    assert audyty.znajdz_pogrubienia_na_drugim_planie(karta) == []
    assert audyty.znajdz_expand_bez_ograniczenia(karta) == []
    assert audyty.znajdz_expand_w_kontenerze(karta) == []

    stan = pomoce.stan_aplikacji(a, "Sypiący")
    stan.zakladka, stan.stat_podzakladka = 3, 1
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(), stan)
    assert "Awarie kontra eksploatacja" in pomoce.napisy(widok)


def test_arkusz_oznacza_jednym_dotknieciem_i_sugerowane_hurtem(baza, monkeypatch):
    d = pojazd()
    a = d["auto_id"]
    w_olej = wizyta(a, 30, 400.0, None, [d["olej"]])
    w_alt = wizyta(a, 60, 900.0, None, [d["alternator"]])
    h_rozrzad = wpis(d["rozrzad"], 90, 1500.0)
    wyslane, odswiezone = [], []
    monkeypatch.setattr(utils.awarie, "otworz_dno", lambda page, bs: None)
    monkeypatch.setattr(utils.awarie, "zamknij_dno", lambda page, bs: None)
    monkeypatch.setattr(utils.awarie, "wypchnij_w_tle", lambda page, auto_id, powod="": wyslane.append(powod))

    bs = utils.pokaz_oznaczanie_napraw(pomoce.zbuduj_strone().page, a, po_zamknieciu=lambda: odswiezone.append(1))
    assert "Oznacz sugerowane jako planowe (2)" in pomoce.napisy(bs)

    wiersz = wiersz_arkusza(bs, dzien(60).strftime("%d.%m.%Y"))
    chip = next(k for k, napisy in klikalne(wiersz) if "Awaria" in napisy)
    chip.on_click(None)
    assert jeden("SELECT rodzaj FROM wizyty WHERE id=?", (w_alt,)) == db.SERWIS_AWARIA
    assert jeden("SELECT rodzaj FROM wizyty WHERE id=?", (w_olej,)) is None
    napisy = pomoce.napisy(bs)
    assert dzien(60).strftime("%d.%m.%Y") not in napisy, "oznaczony wiersz znika w miejscu"
    assert any(t.startswith("2 naprawy · dotknij rodzaj") for t in napisy)

    przycisk = next(k for k, napisy in klikalne(bs) if "Oznacz sugerowane jako planowe (2)" in napisy)
    przycisk.on_click(None)
    assert jeden("SELECT rodzaj FROM wizyty WHERE id=?", (w_olej,)) == db.SERWIS_PLANOWE
    assert jeden("SELECT rodzaj FROM historia WHERE wizyta_id=?", (w_olej,)) == db.SERWIS_PLANOWE
    assert jeden("SELECT rodzaj FROM historia WHERE id=?", (h_rozrzad,)) == db.SERWIS_PLANOWE
    assert "Wszystkie naprawy mają rodzaj" in pomoce.napisy(bs)

    next(k for k, napisy in klikalne(bs) if "Gotowe" in napisy).on_click(None)
    assert (wyslane, odswiezone) == (["rodzaj naprawy"], [1])


def test_kafelek_awarii_na_kokpicie(baza):
    d = pojazd()
    a = d["auto_id"]
    wizyta(a, 500, 1000.0, db.SERWIS_PLANOWE, [d["olej"]])
    wizyta(a, 450, 200.0, db.SERWIS_AWARIA, [d["alternator"]])
    wizyta(a, 400, 800.0, db.SERWIS_PLANOWE, [d["olej"]])
    wizyta(a, 200, 900.0, db.SERWIS_AWARIA, [d["alternator"]])
    wizyta(a, 100, 400.0, db.SERWIS_PLANOWE, [d["olej"]])
    wizyta(a, 50, 700.0, db.SERWIS_AWARIA, [d["alternator"]])
    stan = pomoce.stan_aplikacji(a, "Sypiący")
    stan.zakladka = 0
    db.zapisz_widgety_kokpitu(["awarie"], a)
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(), stan)
    napisy = pomoce.napisy(widok.kokpit_kontener)
    assert "Awarie w serwisie" in napisy and "rok wcześniej 10%" in napisy
