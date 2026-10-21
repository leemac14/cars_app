"""Szablony wpisów (M-02): nazwany wzór kosztu albo tankowania z menu „+”.

Koszt z kwotą zapisuje się jednym dotknięciem (dziś, z „Cofnij”), reszta otwiera wypełniony
formularz. Szablon jest cechą auta (sync, kosz, plik pojazdu), licznik użyć — telefonu."""

import asyncio
import json
from datetime import datetime

import flet as ft

import db
import pomoce
import sync
import utils
from date import na_iso


def _dzis():
    return datetime.now().strftime("%d.%m.%Y")


def _strona():
    strona = pomoce.zbuduj_strone()
    strona.page.on_route_change = lambda e: None
    return strona


def _wycisz(monkeypatch, komunikaty=None, zapisy=None):
    """Strona testowa nie pokaże paska ani okna — zbieramy, co by pokazała."""
    komunikaty = [] if komunikaty is None else komunikaty
    monkeypatch.setattr(utils.szablony, "pokaz_komunikat", lambda page, tekst, *a, **k: komunikaty.append(tekst))
    monkeypatch.setattr(utils.szablony, "wypchnij_w_tle", lambda *a, **k: None)
    if zapisy is not None:
        monkeypatch.setattr(utils.szablony, "_komunikat_zapisu",
                            lambda page, tekst, cofnij, sekundy=5: zapisy.append((tekst, cofnij)))
    return komunikaty


def test_koszt_z_kwota_zapisuje_sie_od_razu_a_cofniecie_omija_kosz(baza):
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    auto = stan.auto_id
    db.zapisz_moje_imie("Kamil")
    sid = db.zapisz_szablon(auto, db.SZABLON_KOSZT, "Myjnia ręczna",
                            {"kategoria": "Myjnia i kosmetyka", "kwota": "45", "tagi": "Trasa",
                             "notatka": "Program premium"})["id"]
    koszt_id = db.zapisz_koszt_z_szablonu(auto, sid)
    with db.polacz_baze() as conn:
        w = conn.execute("SELECT data, data_iso, kategoria, nazwa, kwota, tagi, dodane_przez, notatka, notatka_autor "
                         "FROM inne_koszty WHERE id=?", (koszt_id,)).fetchone()
    assert tuple(w) == (_dzis(), na_iso(_dzis()), "Myjnia i kosmetyka", "Myjnia ręczna", 45.0, "Trasa", "Kamil",
                        "Program premium", "Kamil")
    assert db.pobierz_szablon(sid)["uzycia"] == 1

    # Wysłany już koszt zostawia nagrobek, ale nie trafia do kosza — istniał kilka sekund.
    with db.polacz_baze() as conn:
        conn.execute("UPDATE inne_koszty SET zdalne_id='z-szablonu' WHERE id=?", (koszt_id,))
    w_koszu = len(db.pobierz_kosz_wpisow())
    assert db.cofnij_koszt_z_szablonu(koszt_id)
    with db.polacz_baze() as conn:
        assert conn.execute("SELECT COUNT(*) FROM inne_koszty WHERE id=?", (koszt_id,)).fetchone()[0] == 0
    assert len(db.pobierz_kosz_wpisow()) == w_koszu
    assert "z-szablonu" in {n[2] for n in db.pobierz_nagrobki(auto)}
    assert not db.cofnij_koszt_z_szablonu(koszt_id)


def test_szablon_bez_kwoty_albo_tankowania_nie_zapisuje_sie_sam(baza):
    auto = pomoce.utworz_pojazd("A")["auto_id"]
    bez_kwoty = db.zapisz_szablon(auto, db.SZABLON_KOSZT, "Parking lotnisko", {"kwota": ""})["id"]
    tank = db.zapisz_szablon(auto, db.SZABLON_TANKOWANIE, "Orlen", {"stacja": "Orlen"})["id"]
    for sid in (bez_kwoty, tank):
        assert not db.czy_szablon_od_razu(db.pobierz_szablon(sid))
        assert db.zapisz_koszt_z_szablonu(auto, sid) is None
    # Szablon cudzego auta nie zapisze kosztu w bieżącym.
    inne = pomoce.utworz_pojazd("B")["auto_id"]
    assert db.zapisz_koszt_z_szablonu(inne, db.pobierz_szablony(auto, db.SZABLON_KOSZT)[0]["id"]) is None


def test_ta_sama_nazwa_nadpisuje_a_poprawka_na_zajeta_odmawia(baza):
    auto = pomoce.utworz_pojazd("A")["auto_id"]   # ma już szablon „Myjnia”
    wynik = db.zapisz_szablon(auto, db.SZABLON_KOSZT, " myjnia ", {"kwota": 50})
    assert wynik["ok"] and not wynik["nowy"]
    koszty = db.pobierz_szablony(auto, db.SZABLON_KOSZT)
    assert [(s["nazwa"], s["dane"]["kwota"], s["dane"]["nazwa"]) for s in koszty] == [("myjnia", 50.0, "myjnia")]

    a2 = db.zapisz_szablon(auto, db.SZABLON_KOSZT, "Autostrada A2", {"kwota": 39})
    assert a2["ok"] and a2["nowy"]
    odmowa = db.zapisz_szablon(auto, db.SZABLON_KOSZT, "MYJNIA", {"kwota": 39}, szablon_id=a2["id"])
    assert not odmowa["ok"] and odmowa["powod"]
    # Inny rodzaj to inna przestrzeń nazw; pusta nazwa i nieznany rodzaj odpadają.
    assert db.zapisz_szablon(auto, db.SZABLON_TANKOWANIE, "Myjnia", {})["nowy"]
    assert not db.zapisz_szablon(auto, db.SZABLON_KOSZT, "  ", {})["ok"]
    assert not db.zapisz_szablon(auto, "wizyta", "Przegląd", {})["ok"]


def test_dane_sa_stale_wiec_sam_zapis_nie_rusza_synchronizacji(baza):
    auto = pomoce.utworz_pojazd("A")["auto_id"]
    sid = db.zapisz_szablon(auto, db.SZABLON_TANKOWANIE, "Orlen",
                            {"tagi": "Trasa", "stacja": "Orlen", "do_pelna": 1, "obce_pole": "x"})["id"]
    with db.polacz_baze() as conn:
        tekst = conn.execute("SELECT dane FROM szablony_wpisow WHERE id=?", (sid,)).fetchone()[0]
    db.zapisz_szablon(auto, db.SZABLON_TANKOWANIE, "Orlen",
                      {"do_pelna": True, "stacja": "Orlen", "tagi": "Trasa"}, szablon_id=sid)
    with db.polacz_baze() as conn:
        assert conn.execute("SELECT dane FROM szablony_wpisow WHERE id=?", (sid,)).fetchone()[0] == tekst
    assert set(json.loads(tekst)) == set(db.POLA_SZABLONU[db.SZABLON_TANKOWANIE])

    konfig = next(k for k in sync.KONFIGURACJA_SYNC if k["tabela"] == "szablony_wpisow")
    with db.polacz_baze() as conn:
        conn.row_factory = None
        przed = dict(zip(konfig["kolumny"], conn.execute(
            f"SELECT {', '.join(konfig['kolumny'])} FROM szablony_wpisow WHERE id=?", (sid,)).fetchone()))
    db.zanotuj_uzycie_szablonu(sid)
    with db.polacz_baze() as conn:
        po = dict(zip(konfig["kolumny"], conn.execute(
            f"SELECT {', '.join(konfig['kolumny'])} FROM szablony_wpisow WHERE id=?", (sid,)).fetchone()))
    assert przed == po and db.pobierz_szablon(sid)["uzycia"] == 1


def test_szablon_z_wpisu_bierze_to_co_sie_powtarza(baza):
    ids = pomoce.utworz_pojazd("A")
    koszt = db.dane_szablonu_z_wpisu(db.SZABLON_KOSZT, ids["inny_koszt"])
    assert (koszt["kategoria"], koszt["nazwa"], koszt["kwota"]) == (db.KATEGORIA_INNE_DROGOWE, "Winieta", 120.0)
    tank = db.dane_szablonu_z_wpisu(db.SZABLON_TANKOWANIE, ids["tankowanie"])
    assert tank == {"stacja": "Orlen", "rodzaj_energii": db.ENERGIA_PALIWO, "typ_ladowania": None,
                    "do_pelna": True, "tagi": None, "notatka": "Pełny bak przed trasą"}
    assert db.proponowana_nazwa_szablonu(db.SZABLON_KOSZT, koszt) == "Winieta"
    assert db.proponowana_nazwa_szablonu(db.SZABLON_TANKOWANIE, tank) == "Orlen"
    assert db.dane_szablonu_z_wpisu(db.SZABLON_KOSZT, 999999) is None


def test_menu_plus_ma_trzy_najczestsze_szablony_i_reszte_pod_szablonami(baza):
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_danymi")   # „Myjnia” użyta 2 razy
    auto = stan.auto_id
    for nazwa, uzycia in (("Parking", 5), ("Autostrada", 3), ("Bramki", 1), ("Rzadki", 0)):
        sid = db.zapisz_szablon(auto, db.SZABLON_KOSZT, nazwa, {"kwota": 10})["id"]
        for _ in range(uzycia):
            db.zanotuj_uzycie_szablonu(sid)
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(), stan)
    stos = widok.floating_action_button.controls[0]
    rzad = stos.controls[0]
    waluta = utils.symbol_waluty()
    assert [pomoce.napisy(c)[0] for c in rzad.controls] == [
        f"Parking · 10 {waluta}", f"Autostrada · 10 {waluta}", f"Myjnia · 40 {waluta}", "Szablony…"]
    assert all(c.bgcolor == ft.Colors.SECONDARY_CONTAINER for c in rzad.controls)
    assert "Tankowanie" in pomoce.napisy(stos)

    bez = pomoce.utworz_pojazd("Bez szablonów")["auto_id"]
    with db.polacz_baze() as conn:
        conn.execute("DELETE FROM szablony_wpisow WHERE auto_id=?", (bez,))
    stan.auto_id = bez
    assert utils.szybkie_szablony(pomoce.zbuduj_strone().page, stan) == []


def test_podglad_nie_dostaje_szablonow(baza):
    stan, ids = pomoce.przygotuj_scenariusz("wspoldzielony_podglad")
    strona = pomoce.zbuduj_strone()
    assert utils.szybkie_szablony(strona.page, stan) == []
    assert utils.pozycja_menu_szablonu(strona.page, stan, db.SZABLON_KOSZT, ids["inny_koszt"]) is None


def test_dotkniecie_zapisuje_koszt_a_drugie_tego_dnia_pyta(baza, monkeypatch):
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    strona = _strona()
    zapisy, pytania = [], []
    _wycisz(monkeypatch, zapisy=zapisy)
    monkeypatch.setattr(utils.szablony, "potwierdz",
                        lambda page, tytul, tresc, tak, **k: pytania.append((tytul, tresc, tak)))
    szablon = db.pobierz_szablony(stan.auto_id)[0]

    asyncio.run(utils.fab_speed_dial(strona.page, [], szybkie=utils.szybkie_szablony(strona.page, stan))
                .controls[0].controls[0].controls[0].on_click(None))
    assert [t for t, _ in zapisy] == [f"Zapisano: Myjnia · 40 {utils.symbol_waluty()}."]
    with db.polacz_baze() as conn:
        ile = lambda: conn.execute("SELECT COUNT(*) FROM inne_koszty WHERE auto_id=? AND nazwa='Myjnia' AND data=?",
                                   (stan.auto_id, _dzis())).fetchone()[0]
        assert ile() == 1

        utils.uzyj_szablonu(strona.page, stan, szablon)
        assert len(pytania) == 1 and "Myjnia" in pytania[0][1] and ile() == 1
        pytania[0][2]()
        assert ile() == 2

        zapisy[-1][1]()   # „Cofnij”
        assert ile() == 1


def test_szablon_bez_kwoty_wypelnia_nowy_koszt_raz(baza, monkeypatch):
    stan, ids = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    strona = _strona()
    _wycisz(monkeypatch)
    sid = db.zapisz_szablon(stan.auto_id, db.SZABLON_KOSZT, "Parking lotnisko",
                            {"kategoria": "Parking i garaż", "tagi": "Trasa", "notatka": "Strefa P3"})["id"]
    utils.uzyj_szablonu(strona.page, stan, db.pobierz_szablon(sid))
    assert strona.page.route == "/inne/nowy" and stan.szablon_wpisu["id"] == sid
    assert db.pobierz_szablon(sid)["uzycia"] == 1

    klasy = pomoce.klasy_widokow()
    widok = pomoce.zbuduj_widok(klasy["FormularzInneView"], strona, stan)
    assert (widok.e_d.value, widok.e_kat.value, widok.e_o.value, widok.e_kw.value, widok.get_tagi(),
            widok.k_notatka.value) == (_dzis(), "Parking i garaż", "Parking lotnisko", "", "Trasa", "Strefa P3")
    assert stan.szablon_wpisu is None
    # Zużyty: kolejny nowy koszt jest pusty, a edycja nie bierze szablonu nawet wtedy, gdy czeka.
    assert pomoce.zbuduj_widok(klasy["FormularzInneView"], strona, stan).e_o.value == ""
    stan.szablon_wpisu = {"id": sid, "auto_id": stan.auto_id, "rodzaj": db.SZABLON_KOSZT,
                          "dane": {"nazwa": "Obcy"}}
    edycja = pomoce.zbuduj_widok(klasy["FormularzInneView"], strona, stan, ids)
    assert edycja.e_o.value == "Winieta" and stan.szablon_wpisu is None


def test_szablon_tankowania_wypelnia_stacje_i_zostawia_licznik(baza, monkeypatch):
    stan, ids = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    strona = _strona()
    _wycisz(monkeypatch)
    dane = db.dane_szablonu_z_wpisu(db.SZABLON_TANKOWANIE, ids["tankowanie"])
    dane.update({"do_pelna": False, "tagi": "Trasa"})
    sid = db.zapisz_szablon(stan.auto_id, db.SZABLON_TANKOWANIE, "Orlen bez pełnego", dane)["id"]
    utils.uzyj_szablonu(strona.page, stan, db.pobierz_szablon(sid))
    assert strona.page.route == "/tankowanie/nowe"

    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["FormularzTankowanieView"], strona, stan)
    assert (widok.get_stacja(), widok.c_pel.value, widok.get_tagi(), widok.k_notatka.value) == (
        "Orlen", False, "Trasa", "Pełny bak przed trasą")
    assert (widok.e_d.value, widok.e_p.value, widok.e_l.value, widok.e_k.value) == (_dzis(), "", "", "")


def test_zapisz_jako_szablon_z_menu_kosztu(baza, monkeypatch):
    stan, ids = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    strona = _strona()
    komunikaty = _wycisz(monkeypatch)
    okna = []
    monkeypatch.setattr(utils.szablony, "otworz_dialog", lambda page, okno: okna.append(okno))
    monkeypatch.setattr(utils.szablony, "zamknij_dialog", lambda page, okno: None)

    pozycja = utils.pozycja_menu_szablonu(strona.page, stan, db.SZABLON_KOSZT, ids["inny_koszt"])
    assert pozycja["tekst"] == "Zapisz jako szablon" and pozycja["czyta"]
    pozycja["akcja"]()
    pola = [c for c in okna[0].content.content.controls if isinstance(c, ft.TextField)]
    assert [p.value for p in pola] == ["Winieta", "120"]
    pola[1].value = "abc"
    okna[0].actions[1].on_click(None)
    assert pola[1].error and not [s for s in db.pobierz_szablony(stan.auto_id) if s["nazwa"] == "Winieta"]

    pola[1].value = ""
    okna[0].actions[1].on_click(None)
    szablon = next(s for s in db.pobierz_szablony(stan.auto_id) if s["nazwa"] == "Winieta")
    assert szablon["dane"]["kwota"] is None and szablon["dane"]["kategoria"] == db.KATEGORIA_INNE_DROGOWE
    assert komunikaty[-1] == "Szablon „Winieta” czeka w menu „+”."


def test_zmiana_nazwy_tagu_poprawia_szablony(baza):
    ids = pomoce.utworz_pojazd("A")
    assert db.edytuj_tag_w_slowniku(ids["auto_id"], ids["tag"], "Trasa", "Wyjazd", "#00FF00")
    assert db.pobierz_szablon(ids["szablon"])["dane"]["tagi"] == "Wyjazd"


def test_usuniety_szablon_czeka_w_koszu(baza):
    ids = pomoce.utworz_pojazd("A")
    wynik = db.usun_z_cofnieciem("szablony_wpisow", ids["szablon"])
    assert wynik["w_koszu"] and db.pobierz_szablon(ids["szablon"]) is None
    pozycja = next(p for p in db.pobierz_kosz_wpisow() if p["tabela"] == "szablony_wpisow")
    import views.kosz_view as kosz_view
    assert kosz_view._opis_wpisu(pozycja, "km") == (ft.Icons.BOOKMARK, "Myjnia", ["Szablon kosztu"])
    wynik["cofnij"]()
    assert db.pobierz_szablon(ids["szablon"])["nazwa"] == "Myjnia"


def test_arkusz_szablonow_listuje_zmienia_i_usuwa(baza, monkeypatch):
    import audyty

    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    strona = _strona()
    _wycisz(monkeypatch)
    arkusze, menu, cofniecia = [], [], []
    monkeypatch.setattr(utils.szablony, "otworz_dno", lambda page, bs: arkusze.append(bs))
    monkeypatch.setattr(utils.szablony, "zamknij_dno", lambda page, bs: None)
    monkeypatch.setattr(utils.szablony, "pokaz_menu_kontekstowe",
                        lambda page, tytul, pozycje: menu.append((tytul, pozycje)))
    monkeypatch.setattr(utils.szablony, "pokaz_komunikat_cofnij",
                        lambda page, tekst, wynik, *a, **k: cofniecia.append((tekst, wynik)))

    bs = utils.pokaz_szablony(strona.page, stan)
    teksty = pomoce.napisy(bs)
    assert "Myjnia" in teksty and f"Myjnia i kosmetyka · 40 {utils.symbol_waluty()} · tagi: Trasa" in teksty
    assert not audyty.znajdz_uciete_napisy(bs.content)
    assert not pomoce.bledy_kontrolek(bs)

    next(iter(pomoce.kontrolki(bs, ft.IconButton))).on_click(None)
    tytul, pozycje = menu[0]
    assert tytul == "Myjnia" and [p["tekst"] for p in pozycje] == ["Zmień nazwę i kwotę", "Usuń szablon"]
    pozycje[1]["akcja"]()
    assert cofniecia[0][0] == "Usunięto szablon „Myjnia”." and db.pobierz_szablony(stan.auto_id) == []

    pusty = utils.pokaz_szablony(strona.page, stan)
    assert "Ten pojazd nie ma jeszcze szablonów." in pomoce.napisy(pusty)


def test_rzad_szablonow_w_menu_miesci_sie_na_waskim_telefonie(baza):
    import audyty

    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    db.zapisz_szablon(stan.auto_id, db.SZABLON_KOSZT, "Autostrada A2 Konin – Poznań", {"kwota": 39.5})
    strona = pomoce.zbuduj_strone()
    menu = utils.fab_speed_dial(strona.page, [], szybkie=utils.szybkie_szablony(strona.page, stan))
    rzad = menu.controls[0].controls[0]
    assert f"Autostrada A2 Konin –… · 39,50 {utils.symbol_waluty()}" in pomoce.napisy(rzad)
    assert not audyty.znajdz_uciete_napisy(rzad)
    assert not audyty.znajdz_rozciagliwe_chipy(rzad)
