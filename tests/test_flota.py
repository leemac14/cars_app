"""Flota (N-07): wszystkie auta naraz — wydatki miesiąca i roku z tym samym okresem rok wcześniej
(sprzedane w tym roku w sumie, sprzedane dawniej tylko w porównaniu), terminy osi przyszłości aut
na jednej liście, kondycja z największą karą, odznaka, kafelek, ekran i wejścia."""

import asyncio
from datetime import date

import flet as ft
import pytest

import audyty
import db
import pomoce
import utils


DZIS = date(2026, 10, 22)


# ============================================================================
#  POMOCNIKI
# ============================================================================

def auto(nazwa, **pola):
    """Aktywne auto z OC i przeglądem za ponad rok — terminy tylko te, które test poda."""
    return pomoce.wstaw("samochody", **{
        "nazwa": nazwa, "typ_paliwa": "Benzyna", "status": db.STATUS_POJAZDU_AKTYWNY,
        "rola_wspoldzielenia": db.ROLA_WLASCICIEL, "oc_data": pomoce.dzien(-400),
        "przeglad_data": pomoce.dzien(-400), **pola})


def koszt(a, data, kwota):
    return pomoce.wstaw("inne_koszty", auto_id=a, data=data, kategoria="Ogólne", nazwa="Myjnia", kwota=kwota)


def tankowanie(a, data, kwota):
    return pomoce.wstaw("tankowania", auto_id=a, data=data, przebieg=1000, litry=40.0, kwota=kwota, do_pelna=1)


def wizyta(a, data, kwota):
    return pomoce.wstaw("wizyty", auto_id=a, data=data, przebieg=1000, koszt_calkowity=kwota)


def garaz():
    """Dwa auta w garażu i Golf sprzedany w tym roku (1 stycznia — test nie zależy od dnia
    uruchomienia): Corolla z zaległym OC i przeglądem w progu, Astra spokojna, Golf najdroższy."""
    corolla = auto("Corolla", nr_rej="WX 12345", oc_data=pomoce.dzien(5), przeglad_data=pomoce.dzien(-10))
    astra = auto("Astra")
    golf = auto("Golf")
    nowy_rok = date(date.today().year, 1, 1).strftime("%d.%m.%Y")
    koszt(corolla, pomoce.dzien(0), 300.0)
    tankowanie(astra, pomoce.dzien(0), 200.0)
    koszt(golf, nowy_rok, 9000.0)
    db.oznacz_pojazd_sprzedany(golf, nowy_rok, 1.0)
    return corolla, astra, golf


def stan(auto_id=None, nazwa="Brak pojazdów"):
    return pomoce.stan_aplikacji(auto_id, nazwa)


def ekran(stan_aplikacji):
    from views.flota_view import FlotaView

    strona = pomoce.zbuduj_strone()  # trzymana przez wołającego — inaczej sesja strony znika
    strona.page.on_route_change = lambda e: None
    return pomoce.zbuduj_widok(FlotaView, strona, stan_aplikacji), strona


@pytest.fixture
def bez_animacji_nacisniecia(monkeypatch):
    """Karty ekranu woła się wprost: efekt naciśnięcia potrzebuje strony z pętlą zdarzeń."""
    monkeypatch.setattr(utils, "z_efektem_nacisniecia", lambda kontener, funkcja: funkcja)


def klikalne(korzen, napis):
    """Najmniejszy klikalny kontener z tym napisem."""
    trafione = [k for k in pomoce.kontrolki(korzen, ft.Container) if k.on_click and napis in pomoce.napisy(k)]
    assert trafione, f"nic klikalnego z napisem {napis!r}"
    return min(trafione, key=pomoce.policz_kontrolki)


def karta_auta(widok, nazwa):
    (karta,) = [k for k in pomoce.kontrolki(widok, ft.Container)
                if k.on_click and nazwa in pomoce.napisy(k) and "w tym roku" in pomoce.napisy(k)]
    return karta


# ============================================================================
#  1. WYDATKI
# ============================================================================

def test_miesiac_i_rok_do_dzis_z_tym_samym_okresem_rok_wczesniej(baza):
    a, b = auto("Corolla"), auto("Astra")
    sprzedany_teraz, sprzedany_dawno = auto("Golf"), auto("Polonez")
    koszt(a, "05.10.2026", 100.0)
    tankowanie(a, "22.10.2026", 50.0)
    wizyta(a, "10.03.2026", 1000.0)
    koszt(a, "23.10.2026", 777.0)                       # jutro — poza „do dziś”
    tankowanie(b, "01.10.2026", 200.0)
    tankowanie(b, "15.01.2026", 300.0)
    koszt(b, "20.10.2025", 40.0)                        # ten sam miesiąc rok wcześniej
    koszt(b, "25.10.2025", 999.0)                       # rok wcześniej, ale po dzisiejszym dniu
    koszt(sprzedany_teraz, "20.02.2026", 400.0)
    koszt(sprzedany_dawno, "10.10.2025", 60.0)
    koszt(sprzedany_dawno, "02.02.2026", 5.0)           # wpis po sprzedaży — auto spoza roku nie liczy się
    db.oznacz_pojazd_sprzedany(sprzedany_teraz, "01.03.2026", 1.0)
    db.oznacz_pojazd_sprzedany(sprzedany_dawno, "30.12.2025", 1.0)

    k = db.koszty_floty(DZIS)
    assert set(k["auta"]) == {a, b, sprzedany_teraz}
    assert k["auta"][a]["miesiac"]["razem"] == 150.0 and k["auta"][a]["rok"]["razem"] == 1150.0
    assert k["auta"][a]["rok"]["serwis"] == 1000.0 and k["auta"][a]["rok"]["paliwo"] == 50.0
    assert k["razem"]["miesiac"]["razem"] == 350.0
    assert k["razem"]["rok"]["razem"] == 1150.0 + 500.0 + 400.0
    assert k["razem"]["miesiac_rok_temu"]["razem"] == 100.0, "Polonez i Astra rok temu, bez 25.10.2025"
    assert k["razem"]["rok_rok_temu"]["razem"] == 100.0
    assert [s["nazwa"] for s in k["sprzedane"]] == ["Golf"] and k["sprzedane"][0]["rok"] == 400.0
    assert k["najdrozsze"]["id"] == a and k["najdrozsze"]["udzial"] == pytest.approx(1150.0 / 2050.0)
    assert db.zmiana_rok_do_roku(150.0, 100.0) == pytest.approx(50.0) and db.zmiana_rok_do_roku(5.0, 0) is None


def test_okresy_przy_29_lutego_i_najdrozsze_dopiero_przy_dwoch_autach(baza):
    okresy = db.okresy_floty(date(2028, 2, 29))
    assert okresy["miesiac_rok_temu"] == (date(2027, 2, 1), date(2027, 2, 28))
    assert okresy["rok_rok_temu"] == (date(2027, 1, 1), date(2027, 2, 28))

    a = auto("Corolla")
    koszt(a, "01.10.2026", 100.0)
    assert db.koszty_floty(DZIS)["najdrozsze"] is None, "jedno auto nie jest „najdroższe”"


# ============================================================================
#  2. TERMINY, KONDYCJA, PILNE
# ============================================================================

def test_terminy_wszystkich_aut_jak_w_co_przede_mna(baza):
    corolla, astra, golf = garaz()
    dane = db.dane_floty(90)
    os_floty = dane["os"]
    pierwsza = os_floty["pozycje"][0]
    assert pierwsza["zalegla"] and pierwsza["pojazd"]["nazwa"] == "Corolla" and pierwsza["klucz"] == "dokument:oc"
    for auto_id in (corolla, astra):
        swoje = {p["klucz"] for p in os_floty["pozycje"] if p["pojazd"]["id"] == auto_id}
        assert swoje == {p["klucz"] for p in db.os_przyszlosci(auto_id, dni=90)["pozycje"]}
    assert golf not in {p["pojazd"]["id"] for p in os_floty["pozycje"]}, "sprzedane bez terminów"
    zaplanowane = [p for p in os_floty["pozycje"] if not p["zalegla"]]
    assert [p["data"] for p in zaplanowane] == sorted(p["data"] for p in zaplanowane)
    assert sum(m["liczba"] for m in os_floty["miesiace"]) == len(zaplanowane)
    assert os_floty["podsumowanie"]["zalegle"] == 1

    assert db.pilne_floty() == {corolla: {"pilne": 2, "zalegle": 1}, astra: {"pilne": 0, "zalegle": 0}}
    assert not db.czy_pilna({"rodzaj": "budzet", "zalegla": False, "status": "po_terminie"})
    assert not db.czy_pilna({"rodzaj": "przebieg", "zalegla": False, "status": "info"})
    assert db.czy_pilna({"rodzaj": "cykliczny", "zalegla": False, "status": "blisko"})


def test_auta_z_kondycja_udzialem_i_rola(baza):
    corolla, astra, _golf = garaz()
    with db.polacz_baze() as conn:
        conn.execute("UPDATE samochody SET rola_wspoldzielenia=? WHERE id=?", (db.ROLA_PODGLAD, astra))
    auta = {a["nazwa"]: a for a in db.dane_floty()["auta"]}
    assert list(auta) == ["Astra", "Corolla"], "jak w „Wybierz pojazd”: aktywne, alfabetycznie"
    c = auta["Corolla"]
    assert c["kondycja"] == db.oblicz_kondycje_pojazdu(corolla)
    assert c["powod"]["opis"] == db.pobierz_rozbicie_kondycji(corolla)["powody"][0]["opis"]
    assert c["powod"]["waga"] == "krytyczna" and (c["pilne"], c["zalegle"]) == (2, 1)
    assert auta["Astra"]["podglad"] and not c["podglad"]
    assert c["udzial"] == pytest.approx(300.0 / 9500.0) and c["najdrozsze"] is False, "Golf wydał najwięcej"


# ============================================================================
#  3. ODZNAKA I KAFELEK
# ============================================================================

def test_odznaka_szuflady_i_kafelek_kokpitu(baza):
    corolla = auto("Corolla", oc_data=pomoce.dzien(5))
    assert "flota" not in db.liczniki_nawigacji(corolla), "jedno auto ma dzwonek"
    assert db.kafel_floty(corolla) is None

    astra = auto("Astra", przeglad_data=pomoce.dzien(-10))
    tankowanie(astra, pomoce.dzien(0), 120.0)
    assert db.liczniki_nawigacji(corolla)["flota"] == 2 == db.liczba_pilnych_floty()
    assert db.kafel_floty(corolla) == {"liczba_aut": 2, "miesiac": 120.0, "pilne_innych": 1, "zalegle_innych": 0}
    assert db.kafel_floty(astra)["zalegle_innych"] == 1
    assert db.metryki_kokpitu(astra, ["flota"])["flota"] == db.kafel_floty(astra)

    db.zapisz_widgety_kokpitu(["flota"], astra)
    strona = pomoce.zbuduj_strone()
    strona.page.on_route_change = lambda e: None
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], strona, stan(astra, "Astra"))
    kafel = klikalne(widok.kokpit_kontener, "Flota · 2 auta")
    assert "Pozostałe auta: 1 pilny termin · 1 po terminie" in pomoce.napisy(kafel)
    assert kafel.bgcolor == utils.powierzchnia(strona.page, "kafel", stan="critical")["bgcolor"], \
        "zaległy termin innego auta podnosi kafel"
    kafel.on_click(None)
    assert strona.page.route == "/flota"


# ============================================================================
#  4. EKRAN
# ============================================================================

def test_ekran_wydatki_auta_terminy_i_audyty(baza):
    corolla, astra, _golf = garaz()
    strona = pomoce.zbuduj_strone()
    strona.page.width = audyty.SZEROKOSC_TELEFONU
    from views.flota_view import FlotaView
    widok = pomoce.zbuduj_widok(FlotaView, strona, stan(astra, "Astra"))
    napisy = pomoce.napisy(widok)
    for napis in ("Wydatki wszystkich aut do dziś", "Najdroższe auto w tym roku", "Terminy wszystkich aut",
                  "Zaległe", "Polisa OC", "Corolla", "Astra", "2 pilne terminy · 1 po terminie"):
        assert napis in napisy, napis
    assert any(n.startswith("W sumie roku także sprzedane w tym roku: Golf") for n in napisy)
    assert any(n.startswith("Golf — ") for n in napisy), "najdroższe w roku bywa sprzedane"

    znaleziska = (audyty.znajdz_uciete_napisy(widok) + audyty.znajdz_expand_bez_ograniczenia(widok)
                  + audyty.znajdz_expand_w_kontenerze(widok) + audyty.znajdz_rozciagliwe_chipy(widok)
                  + audyty.znajdz_plaskie_powierzchnie(widok, strona.page))
    assert znaleziska == [], "\n".join(str(z) for z in znaleziska)
    assert audyty.znajdz_pogrubienia_na_drugim_planie(widok) == []


def test_dotkniecie_auta_terminu_i_kondycji_wybiera_to_auto(baza, monkeypatch, bez_animacji_nacisniecia):
    corolla, astra, _golf = garaz()
    stan_ekranu = stan(astra, "Astra")
    stan_ekranu.zakladka = 2
    widok, strona = ekran(stan_ekranu)

    karta_auta(widok, "Corolla").on_click(None)
    assert (stan_ekranu.auto_id, stan_ekranu.auto_nazwa, stan_ekranu.zakladka) == (corolla, "Corolla", 0)
    assert strona.page.route == "/"

    stan_ekranu.auto_id, stan_ekranu.auto_nazwa = astra, "Astra"
    klikalne(widok, "Polisa OC").on_click(None)
    assert stan_ekranu.auto_id == corolla and strona.page.route == f"/auto/edytuj/{corolla}"

    otwarte = []
    monkeypatch.setattr(utils.pojazd, "otworz_dno", lambda page, bs: otwarte.append(bs))
    monkeypatch.setattr(utils.pojazd, "zamknij_dno", lambda page, bs: None)
    stan_ekranu.auto_id, stan_ekranu.auto_nazwa = astra, "Astra"
    (pierscien,) = [k for k in pomoce.kontrolki(karta_auta(widok, "Corolla"), ft.Container)
                    if k.on_click and str(k.tooltip or "").startswith("Kondycja")]
    pierscien.on_click(None)
    assert "Kondycja: Corolla" in pomoce.napisy(otwarte[0]) and stan_ekranu.auto_id == astra, \
        "samo oglądanie rozpiski nie zmienia auta"
    klikalne(otwarte[0], "Polisa OC — po terminie").on_click(None)
    assert stan_ekranu.auto_id == corolla and strona.page.route == f"/auto/edytuj/{corolla}"


def test_podglad_okno_kalendarz_i_puste_stany(baza, monkeypatch, bez_animacji_nacisniecia):
    corolla, astra, _golf = garaz()
    with db.polacz_baze() as conn:
        conn.execute("UPDATE samochody SET rola_wspoldzielenia=? WHERE id=?", (db.ROLA_PODGLAD, corolla))
    widok, strona = ekran(stan(astra, "Astra"))
    klikalne(widok, "Polisa OC").on_click(None)
    assert strona.page.route == "/pojazd", "podgląd dostaje Kartę pojazdu zamiast formularza"

    widok._zmien_okno(365)
    assert db.pobierz_okno_przyszlosci() == 365 and widok.dni == 365
    assert any(n.startswith("Następne 365 dni") for n in pomoce.napisy(widok))

    wyslane = []

    async def do_kalendarza(page, identyfikatory, po_wyslaniu=None):
        wyslane.append(identyfikatory)

    monkeypatch.setattr(utils, "wyslij_do_kalendarza", do_kalendarza)
    monkeypatch.setattr(type(strona.page), "run_task", lambda self, f, *a: asyncio.run(f(*a)))
    (przycisk,) = [b for b in pomoce.kontrolki(widok, ft.IconButton) if b.tooltip == "Terminy wszystkich aut do kalendarza"]
    przycisk.on_click(None)
    assert wyslane == [[astra, corolla]]

    db.oznacz_pojazd_sprzedany(astra, pomoce.dzien(1), 1.0)
    jedno, _s1 = ekran(stan(corolla, "Corolla"))
    assert any("Drugie auto doda sumy" in n for n in pomoce.napisy(jedno))
    db.oznacz_pojazd_sprzedany(corolla, pomoce.dzien(1), 1.0)
    pusty, _s2 = ekran(stan(corolla, "Corolla"))
    assert "Garaż jest pusty" in pomoce.napisy(pusty)


# ============================================================================
#  5. WEJŚCIA
# ============================================================================

def test_router_szuflada_wybor_pojazdu_i_co_nowego(baza, monkeypatch):
    monkeypatch.setattr(ft, "run", lambda *args, **kwargs: None)
    import log
    import main

    monkeypatch.setattr(log, "wlacz", lambda: True)
    monkeypatch.setitem(utils.wyglad._OSTATNI_MOTYW, "nazwa", utils.wyglad._OSTATNI_MOTYW["nazwa"])
    corolla, astra = pomoce.utworz_pojazd("Corolla")["auto_id"], pomoce.utworz_pojazd("Astra")["auto_id"]
    db.zapisz_widziana_wersje(db.WERSJA_APLIKACJI)
    strona = pomoce.zbuduj_strone()
    page = strona.page
    monkeypatch.setattr(type(page), "run_task", lambda self, *args, **kwargs: None)
    main.main(page)
    utils.przejdz(page, "/flota")
    assert [type(w).__name__ for w in page.views] == ["MainView", "FlotaView"]
    assert main._cel_trasy(["flota"])[0] is False

    assert [e["id"] for e in utils.znajdz_ekrany("flota")][:1] == ["flota"]
    assert "flota" in [e["id"] for e in utils.znajdz_ekrany("wszystkie auta")]
    assert utils.EKRANY_WG_ID["flota"]["grupa"] == "garaz"
    (wydanie,) = [w for w in db.NOWOSCI if w["wersja"] == "2026.10.22.2"]
    assert wydanie["pozycje"][0]["ekran"] == "flota"

    otwarte = []
    monkeypatch.setattr(utils, "otworz_dno", lambda page, bs: otwarte.append(bs))
    monkeypatch.setattr(utils, "zamknij_dno", lambda page, bs: None)
    utils.przejdz(page, "/")
    (zdjecie,) = [k for k in pomoce.kontrolki(page.views[0], ft.Container) if k.tooltip == "Dotknij, aby wybrać z listy"]
    zdjecie.on_click(None)
    (flota,) = [b for b in pomoce.kontrolki(otwarte[-1], ft.TextButton) if b.content == "Cała flota"]
    flota.on_click(None)
    assert page.route == "/flota" and corolla and astra
