"""Gesty na kartach list (W-07) i wibracje (unowocześnienie 16.10.2026): w lewo — usuń
z „Cofnij” do kosza, w prawo — notatka; haptyka tylko na telefonie i przy włączonym przełączniku."""

import asyncio
from types import SimpleNamespace

import flet as ft

import db
import pomoce
import utils


def _gest(karta, kierunek):
    """Przesunięcie karty: (potwierdzenia z Fleta, wynik on_dismiss albo None)."""
    potwierdzenia = []

    async def potwierdz(czy):
        potwierdzenia.append(czy)

    karta.confirm_dismiss = potwierdz
    zdarzenie = SimpleNamespace(direction=kierunek, control=karta)
    asyncio.run(karta.on_confirm_dismiss(zdarzenie))
    if potwierdzenia == [True] and karta.on_dismiss:
        karta.on_dismiss(zdarzenie)
    return potwierdzenia


def test_karta_bez_akcji_zostaje_bez_gestow():
    karta = ft.Card(content=ft.Text("x"))
    assert utils.gesty_karty(None, karta) is karta


def test_kierunki_i_tla_gestow():
    oba = utils.gesty_karty(None, ft.Card(), usun=lambda: None, notatka=lambda: None)
    assert oba.dismiss_direction == ft.DismissDirection.HORIZONTAL
    assert "Notatka" in pomoce.napisy(oba.background) and "Usuń" in pomoce.napisy(oba.secondary_background)

    tylko_usun = utils.gesty_karty(None, ft.Card(), usun=lambda: None)
    assert tylko_usun.dismiss_direction == ft.DismissDirection.END_TO_START
    assert "Usuń" in pomoce.napisy(tylko_usun.background) and tylko_usun.secondary_background is None

    tylko_notatka = utils.gesty_karty(None, ft.Card(), notatka=lambda: None)
    assert tylko_notatka.dismiss_direction == ft.DismissDirection.START_TO_END and tylko_notatka.on_dismiss is None


def test_w_lewo_usuwa_w_prawo_notatka_a_zaznaczanie_odbija():
    zdarzenia = []
    widok = SimpleNamespace(tryb_zaznaczania=False)
    karta = utils.gesty_karty(None, ft.Card(), widok=widok,
                              usun=lambda: zdarzenia.append("usun"), notatka=lambda: zdarzenia.append("notatka"))

    assert _gest(karta, ft.DismissDirection.END_TO_START) == [True] and zdarzenia == ["usun"]
    assert _gest(karta, ft.DismissDirection.START_TO_END) == [False] and zdarzenia == ["usun", "notatka"]

    widok.tryb_zaznaczania = True
    assert _gest(karta, ft.DismissDirection.END_TO_START) == [False]
    assert zdarzenia == ["usun", "notatka"], "w trybie zaznaczania gest niczego nie robi"


def _karty_tankowan(stan):
    stan.zakladka, stan.koszty_podzakladka = 2, 0
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(), stan)
    return widok, [k["karta"] for k in widok.wszystkie_karty_tankowania]


def test_tankowania_przesuniete_w_lewo_znikaja_z_cofnij(baza, monkeypatch):
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_historia")
    _widok, karty = _karty_tankowan(stan)
    assert karty and all(isinstance(k, ft.Dismissible) for k in karty)
    assert karty[0].dismiss_direction == ft.DismissDirection.HORIZONTAL

    komunikaty = []
    monkeypatch.setattr(utils, "przejdz", lambda page, trasa: None)
    monkeypatch.setattr(utils, "pokaz_komunikat_cofnij", lambda page, tekst, wynik, **k: komunikaty.append((tekst, wynik)))
    with db.polacz_baze() as conn:
        przed = conn.execute("SELECT COUNT(*) FROM tankowania WHERE auto_id=?", (stan.auto_id,)).fetchone()[0]

    assert _gest(karty[0], ft.DismissDirection.END_TO_START) == [True]
    with db.polacz_baze() as conn:
        po = conn.execute("SELECT COUNT(*) FROM tankowania WHERE auto_id=?", (stan.auto_id,)).fetchone()[0]
    assert po == przed - 1
    assert komunikaty and komunikaty[0][0] == "Usunięto tankowanie." and komunikaty[0][1]
    assert komunikaty[0][1]["w_koszu"] and db.liczba_wpisow_w_koszu() == 1, "gest odkłada wpis do kosza"

    komunikaty[0][1]["cofnij"]()
    with db.polacz_baze() as conn:
        assert conn.execute("SELECT COUNT(*) FROM tankowania WHERE auto_id=?", (stan.auto_id,)).fetchone()[0] == przed


def test_gest_w_prawo_otwiera_notatke_tego_wpisu(baza, monkeypatch):
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_historia")
    _widok, karty = _karty_tankowan(stan)
    otwarte = []
    monkeypatch.setattr(utils, "szybka_notatka", lambda page, tabela, rid, *a, **k: otwarte.append((tabela, rid)))

    assert _gest(karty[0], ft.DismissDirection.START_TO_END) == [False]
    assert otwarte and otwarte[0][0] == "tankowania"


def test_podglad_nie_dostaje_gestow(baza):
    stan, _ = pomoce.przygotuj_scenariusz("wspoldzielony_podglad")
    _widok, karty = _karty_tankowan(stan)
    assert karty and not any(isinstance(k, ft.Dismissible) for k in karty)


def test_wpis_z_wizyty_zbiorczej_ma_tylko_notatke(baza):
    stan, ids = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    with db.polacz_baze() as conn:
        conn.execute("INSERT INTO historia (zadanie_id, wizyta_id, data, przebieg, kategoria, cena) VALUES (?,?,?,?,?,?)",
                     (ids["zadanie"], None, "2026-03-01", 104000, "Serwis", 99.0))
        db.przelicz_daty_iso(conn)
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["HistoriaView"], pomoce.zbuduj_strone(), stan,
                                {"zadanie": ids["zadanie"]})
    kierunki = sorted(k["karta"].dismiss_direction.value for k in widok.wszystkie_karty)
    assert kierunki == sorted([ft.DismissDirection.HORIZONTAL.value, ft.DismissDirection.START_TO_END.value])


# ============================================================================
#  WIBRACJE
# ============================================================================

class _Haptyka:
    def __init__(self):
        self.wywolania = []

    def __getattr__(self, nazwa):
        async def metoda():
            self.wywolania.append(nazwa)
        return metoda


def _telefon(monkeypatch):
    """Strona Androida z atrapą haptyki; zadania `run_task` czekają w `page.zadania`."""
    strona = pomoce.zbuduj_strone()
    strona.page.strona = strona  # bez referencji sesja strony testowej znika
    strona.page.platform = ft.PagePlatform.ANDROID
    strona.page.haptyka = _Haptyka()
    strona.page.zadania = []
    monkeypatch.setattr(type(strona.page), "run_task", lambda self, f, *a, **k: self.zadania.append(f))
    return strona.page


def _wibracje(page):
    while page.zadania:
        asyncio.run(page.zadania.pop(0)())
    return page.haptyka.wywolania


def test_wibracja_tylko_na_telefonie_i_przy_wlaczonym_przelaczniku(baza, monkeypatch):
    utils.wibracja(pomoce.zbuduj_strone().page, "zapis")  # komputer: nic się nie dzieje

    page = _telefon(monkeypatch)
    utils.wibracja(page, "usuniecie")
    utils.wibracja(page, "nieznany")
    assert _wibracje(page) == ["medium_impact"]

    db.zapisz_wibracje(False)
    utils.wibracja(page, "zapis")
    assert _wibracje(page) == ["medium_impact"]


def test_z_wibracja_zostawia_obsluge_synchroniczna(baza, monkeypatch):
    page = _telefon(monkeypatch)
    klik = utils.z_wibracja(page, lambda e: "zapisano", "zapis")
    assert klik(None) == "zapisano" and _wibracje(page) == ["light_impact"]

    async def zapisz_async(e):
        return "async"

    assert asyncio.run(utils.z_wibracja(page, zapisz_async)(None)) == "async"
    assert _wibracje(page) == ["light_impact", "light_impact"]
    assert utils.z_wibracja(page, None) is None


def test_segment_i_usuniecie_wibruja(baza, monkeypatch):
    page = _telefon(monkeypatch)
    wybrane = []
    przelacznik = utils.segmented_control(page, [("A", 0), ("B", 1)], 0, wybrane.append)
    segmenty = przelacznik.content.controls
    segmenty[0].on_click(None)
    segmenty[1].on_click(None)
    assert wybrane == [0, 1] and _wibracje(page) == ["selection_click"], "ten sam segment nie wibruje"

    utils.pokaz_komunikat_cofnij(page, "Usunięto.", {"cofnij": lambda: None, "finalizuj": lambda: None}, sekundy=0)
    assert _wibracje(page)[-1] == "medium_impact"
