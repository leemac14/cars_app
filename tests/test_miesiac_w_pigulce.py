"""„Miesiąc w pigułce” — dane, grafika i ekran.

Grafika miesiąca to ten sam rysownik, co grafika roku (`_narysuj_pigulke`),
z innym zestawem liczb, a dane obu liczy wspólny `_rachunek_okresu`. Testy
pilnują tego, co jest WŁASNE miesiącowi — słupków dni, porównań, miesiąca
w toku, domyślnego miesiąca, tras ekranu — oraz tego, że rok i miesiąc liczą
to samo z tych samych wpisów. I jednego twardego warunku dla obu grafik:
żaden napis nie wychodzi poza kadr.
"""

import io
from datetime import date, datetime

import flet as ft
import pytest
from PIL import Image, ImageDraw

import db
import pomoce
import utils
from date import na_iso
from views.miesiac_view import MiesiacWPigulceView
from views.rok_view import RokWPigulceView


class _Zegar(datetime):
    """`datetime` z zamrożonym „teraz” — miesiąc w toku zależy od dnia."""
    teraz = datetime(2026, 10, 15, 12, 0)

    @classmethod
    def now(cls, tz=None):
        return cls.teraz


@pytest.fixture
def dzis(monkeypatch):
    def ustaw(dzien):
        _Zegar.teraz = datetime(dzien.year, dzien.month, dzien.day, 12, 0)
        monkeypatch.setattr(db.analiza, "datetime", _Zegar)
    return ustaw


def _auto(nazwa="Miesięczny"):
    with db.polacz_baze() as conn:
        return conn.execute(
            "INSERT INTO samochody (nazwa, typ_paliwa, status, rola_wspoldzielenia) VALUES (?,?,?,?)",
            (nazwa, "Benzyna", db.STATUS_POJAZDU_AKTYWNY, db.ROLA_WLASCICIEL)).lastrowid


def _txt(dzien):
    return dzien.strftime("%d.%m.%Y")


def _tankowanie(auto_id, dzien, kwota, przebieg, stacja="Orlen"):
    with db.polacz_baze() as conn:
        conn.execute(
            "INSERT INTO tankowania (auto_id, data, data_iso, przebieg, litry, kwota, do_pelna, stacja, "
            "rodzaj_energii) VALUES (?,?,?,?,?,?,?,?,?)",
            (auto_id, _txt(dzien), na_iso(_txt(dzien)), przebieg, 40.0, kwota, 1, stacja, db.ENERGIA_PALIWO))


def _koszt(auto_id, dzien, kwota, nazwa="Myjnia"):
    with db.polacz_baze() as conn:
        conn.execute(
            "INSERT INTO inne_koszty (auto_id, data, data_iso, kategoria, nazwa, kwota) VALUES (?,?,?,?,?,?)",
            (auto_id, _txt(dzien), na_iso(_txt(dzien)), db.KATEGORIA_INNE_DOMYSLNA, nazwa, kwota))


def _wizyta_z_pozycja(auto_id, dzien, kwota, cena_pozycji, przebieg):
    """Wizyta zbiorcza z jedną pozycją historii — liczy się RAZ, kwotą wizyty."""
    with db.polacz_baze() as conn:
        zadanie = conn.execute("INSERT INTO zadania (auto_id, nazwa) VALUES (?,?)", (auto_id, "Olej")).lastrowid
        wizyta = conn.execute(
            "INSERT INTO wizyty (auto_id, data, data_iso, przebieg, wykonawca, koszt_calkowity) "
            "VALUES (?,?,?,?,?,?)",
            (auto_id, _txt(dzien), na_iso(_txt(dzien)), przebieg, "Serwis ASO", kwota)).lastrowid
        conn.execute(
            "INSERT INTO historia (zadanie_id, wizyta_id, data, data_iso, przebieg, kategoria, cena, wykonawca) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (zadanie, wizyta, _txt(dzien), na_iso(_txt(dzien)), przebieg, "Serwis", cena_pozycji, "Serwis ASO"))


def _pazdziernik_w_toku(dzis):
    """15.10.2026: październik w toku, pełny wrzesień i październik rok wcześniej."""
    dzis(date(2026, 10, 15))
    a = _auto()
    _tankowanie(a, date(2026, 10, 2), 200.0, 10000)
    _wizyta_z_pozycja(a, date(2026, 10, 11), 900.0, 700.0, 10300)
    _koszt(a, date(2026, 10, 20), 5000.0)            # po dzisiejszym dniu — nie wchodzi
    _koszt(a, date(2026, 9, 5), 300.0)
    _koszt(a, date(2026, 9, 25), 4000.0)             # po 15. — poza porównaniem z wrześniem
    _koszt(a, date(2025, 10, 15), 500.0)
    return a


# ================================================================== dane

def test_miesiac_liczy_swoje_dni_a_wizyte_raz(baza, dzis):
    dzis(date(2026, 3, 15))
    a = _auto()
    _tankowanie(a, date(2025, 10, 3), 200.0, 10000)
    _tankowanie(a, date(2025, 10, 20), 250.0, 10600, stacja="BP")
    _tankowanie(a, date(2025, 11, 2), 180.0, 11000)
    _koszt(a, date(2025, 10, 20), 40.0)
    _wizyta_z_pozycja(a, date(2025, 10, 11), 900.0, 700.0, 10300)
    _koszt(a, date(2025, 9, 30), 999.0)

    d = db.podsumowanie_miesiaca(a, 2025, 10)

    assert d["koszty"] == {"paliwo": 450.0, "serwis": 900.0, "inne": 40.0, "razem": 1390.0}
    assert len(d["dni"]) == 31 and d["dni"][20] == 290.0 and d["dni"][11] == 900.0 and d["dni"][1] == 0.0
    assert d["najdrozszy_dzien"] == {"dzien": 11, "kwota": 900.0}
    assert d["dni_z_wpisami"] == 3
    assert (d["liczba_tankowan"], d["liczba_wizyt"], d["liczba_wpisow_serwisu"]) == (2, 1, 0)
    assert d["km"] == 600
    assert d["ulubiona_stacja"] == {"nazwa": "BP", "liczba": 1, "kwota": 250.0}
    assert d["najwiekszy_wydatek"] == {"data": "11.10.2025", "kwota": 900.0, "opis": "Wizyta: Serwis ASO"}
    assert d["niepelny"] is False and d["do"] == "31.10.2025"
    assert d["sredni_koszt_dnia"] == pytest.approx(1390.0 / 31)
    assert db.podsumowanie_miesiaca(a, 2025, 8) is None


def test_porownania_zamknietego_miesiaca(baza, dzis):
    """Styczeń porównuje się z grudniem POPRZEDNIEGO roku i ze styczniem rok wcześniej."""
    dzis(date(2026, 3, 15))
    a = _auto()
    _koszt(a, date(2026, 1, 10), 300.0)
    _koszt(a, date(2025, 12, 31), 200.0)
    _koszt(a, date(2025, 1, 5), 600.0)

    d = db.podsumowanie_miesiaca(a, 2026, 1)

    assert d["poprzedni_miesiac"] == {"rok": 2025, "miesiac": 12, "kwota": 200.0, "do": "31.12.2025", "zmiana": 50.0}
    assert d["rok_temu"] == {"rok": 2025, "miesiac": 1, "kwota": 600.0, "do": "31.01.2025", "zmiana": -50.0}
    assert db.opis_porownania_miesiaca(d["poprzedni_miesiac"], 2026, False) == "Względem grudnia 2025"
    assert db.opis_porownania_miesiaca(d["rok_temu"], 2026, False) == "Względem stycznia 2025"


def test_miesiac_w_toku_porownuje_te_same_dni(baza, dzis):
    """Połowa października kontra CAŁY wrzesień zawsze wychodziłaby „taniej”."""
    a = _pazdziernik_w_toku(dzis)

    d = db.podsumowanie_miesiaca(a, 2026, 10)

    assert d["niepelny"] is True and d["do"] == "15.10.2026"
    assert d["koszty"]["razem"] == 1100.0
    assert d["sredni_koszt_dnia"] == pytest.approx(1100.0 / 15)
    assert d["poprzedni_miesiac"]["kwota"] == 300.0 and d["poprzedni_miesiac"]["do"] == "15.09.2026"
    assert d["rok_temu"]["kwota"] == 500.0 and d["rok_temu"]["zmiana"] == pytest.approx(120.0)
    assert db.opis_porownania_miesiaca(d["poprzedni_miesiac"], 2026, True) == "Względem września (do 15.09)"


def test_dzien_spoza_krotszego_miesiaca_konczy_porownanie_na_jego_koncu(baza, dzis):
    dzis(date(2026, 3, 31))
    a = _auto()
    _koszt(a, date(2026, 3, 1), 10.0)
    _koszt(a, date(2026, 2, 28), 30.0)

    d = db.podsumowanie_miesiaca(a, 2026, 3)

    assert d["poprzedni_miesiac"]["do"] == "28.02.2026" and d["poprzedni_miesiac"]["kwota"] == 30.0


def test_rok_to_suma_swoich_miesiecy(baza):
    """Ta sama maszyneria dla obu: słupek miesiąca w roku i „Wydane łącznie”
    w pigułce tego miesiąca to ta sama liczba."""
    ids = pomoce.utworz_pojazd("Pełny")
    pomoce.dosyp_dane(ids["auto_id"], dni_wstecz=420)
    a = ids["auto_id"]

    for rok in db.lata_z_danymi(a):
        r = db.podsumowanie_roku(a, rok)
        miesiace = [db.podsumowanie_miesiaca(a, rok, m) for m in range(1, 13)]
        for m, mc in enumerate(miesiace, start=1):
            assert (mc["koszty"]["razem"] if mc else 0.0) == pytest.approx(r["miesiace"][m])
        assert sum(mc["liczba_tankowan"] for mc in miesiace if mc) == r["liczba_tankowan"]


def test_lista_miesiecy_i_domyslny_ostatni_pelny(baza):
    a = _auto()
    for dzien in (date(2026, 9, 3), date(2026, 7, 1), date(2026, 10, 1), date(2026, 9, 30)):
        _koszt(a, dzien, 10.0)
    with db.polacz_baze() as conn:  # wpis bez czytelnej daty nie tworzy miesiąca
        conn.execute("INSERT INTO inne_koszty (auto_id, data, kategoria, nazwa, kwota) VALUES (?,?,?,?,?)",
                     (a, "kiedyś", db.KATEGORIA_INNE_DOMYSLNA, "Coś", 5.0))
        db.przelicz_daty_iso(conn)

    miesiace = db.miesiace_z_danymi(a)

    assert miesiace == [(2026, 10), (2026, 9), (2026, 7)]
    pierwszy = date(2026, 10, 1)
    assert db.wybierz_miesiac_pigulki(miesiace, dzis=pierwszy) == (2026, 9)
    assert db.wybierz_miesiac_pigulki(miesiace, 2026, 7, dzis=pierwszy) == (2026, 7)
    assert db.wybierz_miesiac_pigulki(miesiace, 2026, 8, dzis=pierwszy) == (2026, 9), "pusty sierpień"
    assert db.wybierz_miesiac_pigulki([(2026, 10)], dzis=pierwszy) == (2026, 10)
    assert db.wybierz_miesiac_pigulki([(2027, 1), (2026, 12)], dzis=pierwszy) == (2026, 12)
    assert db.wybierz_miesiac_pigulki([], dzis=pierwszy) is None


def test_podpisy_dni_ustepuja_szczytowi():
    def podpisane(liczba_dni, szczyt):
        return [i for i, napis in enumerate(db.podpisy_dni_miesiaca(liczba_dni, szczyt), start=1) if napis]

    assert podpisane(31, 11) == [1, 5, 11, 15, 20, 25, 30]
    assert podpisane(28, 28) == [1, 5, 10, 15, 20, 25, 28]
    assert podpisane(30, 3) == [1, 3, 5, 10, 15, 20, 25, 30]


# ================================================================ grafika

def test_grafika_miesiaca_to_rysownik_roku_z_innym_zestawem_liczb(baza, dzis, monkeypatch):
    a = _pazdziernik_w_toku(dzis)
    plany = []
    monkeypatch.setattr(db.raporty, "_narysuj_pigulke", lambda **plan: plany.append(plan) or b"")

    db.generuj_grafike_roku("Auto", db.podsumowanie_roku(a, 2026))
    db.generuj_grafike_miesiaca("Auto", db.podsumowanie_miesiaca(a, 2026, 10))

    rok, miesiac = plany
    assert (rok["naglowek"], rok["tytul"], len(rok["wykres"]["wartosci"])) == ("ROK W PIGUŁCE", "2026", 12)
    assert (miesiac["naglowek"], miesiac["tytul"]) == ("MIESIĄC W PIGUŁCE", "Październik")
    assert miesiac["plakietki"] == ["2026", "w toku"]
    assert len(miesiac["wykres"]["wartosci"]) == 31 and miesiac["wykres"]["szczyt"] == 10
    assert miesiac["wykres"]["etykiety"][10] == "11" and miesiac["wykres"]["etykiety"][9] is None
    assert [etykieta for etykieta, _ in miesiac["fakty"]] == [
        "Najdroższy dzień", "Największy wydatek", "Ulubiona stacja",
        "Względem września (do 15.09)", "Względem października 2025 (do 15.10)",
    ]
    assert miesiac["fakty"][0][1] == "11 paź • 900 PLN"
    assert miesiac["fakty"][3][1] == "+267%"
    assert [podpis for _, _, podpis in miesiac["kafle"]][1:3] == ["~73 PLN dziennie", "1 tankowanie w miesiącu"]


DLUGA_NAZWA = "Bardzo długa nazwa auta, która w żadnym wypadku nie mieści się w jednym wierszu kadru"
DLUGA_STACJA = "Stacja Paliw Orlen nr 4521 przy obwodnicy Wielkiego Miasta Wojewódzkiego"


def _wspolne_skrajne():
    return {
        "km": 123456, "koszty": {"razem": 98765.43, "paliwo": 5e4, "serwis": 4e4, "inne": 8765.43},
        "koszt_km": 0.8, "porownanie_dystansu": "okrążenie Ziemi wzdłuż równika — 3,1 raza",
        "zuzycie_elektryczne": False, "srednie_zuzycie": 7.43, "litry": 9876.5, "kwh": 0,
        "liczba_tankowan": 131, "ulubiona_stacja": {"nazwa": DLUGA_STACJA, "liczba": 47, "kwota": 1.0},
        "najwiekszy_wydatek": {"opis": "Wymiana rozrządu z pompą wody, napinaczem i paskiem wielorowkowym",
                               "kwota": 4321.0, "data": "01.02.2025"},
    }


def _rok_skrajny():
    return {
        **_wspolne_skrajne(), "rok": 2026, "niepelny": True, "sredni_koszt_miesiaca": 8230.45,
        "miesiace": {m: m * 977.0 for m in range(1, 13)},
        "najdrozszy_miesiac": {"miesiac": 12, "kwota": 11724.0}, "zmiana_rdr": 123.4, "poprzedni_do": "15.10.2025",
    }


def _miesiac_skrajny():
    dni = {d: 0.0 for d in range(1, 32)}
    dni.update({1: 99999.0, 11: 123456.78, 31: 5.0})
    porownanie = {"rok": 2025, "miesiac": 10, "kwota": 1.0, "do": "15.10.2025", "zmiana": 12345678.9}
    return {
        **_wspolne_skrajne(), "rok": 2026, "miesiac": 10, "niepelny": True, "do": "15.10.2026",
        "dni": dni, "najdrozszy_dzien": {"dzien": 11, "kwota": 123456.78}, "sredni_koszt_dnia": 6584.36,
        "poprzedni_miesiac": dict(porownanie, rok=2026, miesiac=9, do="15.09.2026"), "rok_temu": porownanie,
    }


@pytest.mark.parametrize("rodzaj", ["rok", "miesiac"])
def test_napisy_grafiki_nie_wychodza_poza_kadr(baza, monkeypatch, rodzaj):
    """Obrazek idzie na czat, nie do poprawek: każdy napis — z kaflami, słupkami
    i wierszami faktów przy skrajnych długościach — mieści się w marginesach."""
    napisy = []
    oryginal = ImageDraw.ImageDraw.text

    def text(self, xy, tekst, *args, **kwargs):
        napisy.append((tekst, self.textbbox(xy, tekst, font=kwargs.get("font"))))
        return oryginal(self, xy, tekst, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", text)

    png = (db.generuj_grafike_roku(DLUGA_NAZWA, _rok_skrajny()) if rodzaj == "rok"
           else db.generuj_grafike_miesiaca(DLUGA_NAZWA, _miesiac_skrajny()))

    assert Image.open(io.BytesIO(png)).size == (1080, 1440)
    assert len(napisy) > 20
    margines = 72 - 2
    poza = [(tekst, ramka) for tekst, ramka in napisy
            if ramka[0] < margines or ramka[2] > 1080 - margines or ramka[1] < 0 or ramka[3] > 1440]
    assert poza == []


# ================================================================== ekran

def _kontrolki(korzen):
    zebrane, do_odwiedzenia = [], [korzen]
    while do_odwiedzenia:
        biezaca = do_odwiedzenia.pop()
        zebrane.append(biezaca)
        for pole in ("controls", "content", "appbar", "leading"):
            wartosc = getattr(biezaca, pole, None)
            if isinstance(wartosc, (list, tuple)):
                do_odwiedzenia.extend(w for w in wartosc if isinstance(w, ft.Control))
            elif isinstance(wartosc, ft.Control):
                do_odwiedzenia.append(wartosc)
    return zebrane


def _teksty(korzen):
    return [str(k.value) for k in _kontrolki(korzen) if isinstance(k, ft.Text) and k.value]


def _przejscia(monkeypatch):
    trasy = []
    for modul in (utils, utils.nawigacja, utils.dialogi):
        monkeypatch.setattr(modul, "przejdz", lambda page, trasa: trasy.append(trasa), raising=False)
    return trasy


def test_ekran_miesiaca_pokazuje_dni_werdykt_i_porownania(baza, dzis):
    a = _pazdziernik_w_toku(dzis)
    stan = pomoce.stan_aplikacji(a, "Miesięczny")
    strona = pomoce.zbuduj_strone()

    domyslny = MiesiacWPigulceView(strona.page, stan)
    widok = MiesiacWPigulceView(strona.page, stan, 2026, 10)

    assert domyslny.route == "/miesiac/2026/9", "ostatni PEŁNY miesiąc z wpisami"
    teksty = _teksty(widok)
    for oczekiwany in ("Październik 2026", "Październik", "2026 • Miesięczny", "miesiąc w toku",
                       "Dzień po dniu", "Werdykt miesiąca", "Najdroższy dzień",
                       "Względem września (do 15.09)", "Względem października 2025 (do 15.10)", "11"):
        assert oczekiwany in teksty, oczekiwany
    assert f"Drożej o 267% (300,00 {utils.symbol_waluty()})" in teksty


def test_strzalki_chodza_po_miesiacach_z_wpisami(baza, dzis, monkeypatch):
    dzis(date(2026, 10, 15))
    a = _auto()
    for dzien in (date(2026, 9, 3), date(2026, 6, 1), date(2026, 3, 1)):
        _koszt(a, dzien, 10.0)
    stan = pomoce.stan_aplikacji(a, "Miesięczny")
    trasy = _przejscia(monkeypatch)

    widok = MiesiacWPigulceView(pomoce.zbuduj_strone().page, stan, 2026, 6, z_roku=True)
    strzalki = [k for k in _kontrolki(widok) if isinstance(k, ft.IconButton) and k.icon in
                (ft.Icons.CHEVRON_LEFT, ft.Icons.CHEVRON_RIGHT)]
    for strzalka in sorted(strzalki, key=lambda k: k.icon != ft.Icons.CHEVRON_LEFT):
        strzalka.on_click(None)
    widok.appbar.leading.on_click(None)

    assert widok.route == "/rok/2026/6"
    assert trasy == ["/rok/2026/3", "/rok/2026/9", "/rok/2026"], "po miesiącach z wpisami, powrót do roku"


def test_slupek_roku_otwiera_miesiac_na_roku(baza, dzis, monkeypatch):
    dzis(date(2026, 10, 15))
    a = _auto()
    for dzien in (date(2025, 2, 3), date(2025, 7, 1)):
        _koszt(a, dzien, 10.0)
    stan = pomoce.stan_aplikacji(a, "Miesięczny")
    trasy = _przejscia(monkeypatch)

    widok = RokWPigulceView(pomoce.zbuduj_strone().page, stan, 2025)
    slupki = [k for k in _kontrolki(widok)
              if isinstance(k, ft.Container) and k.on_click and isinstance(k.content, ft.Column)
              and any(isinstance(t, ft.Text) and t.value in ("lut", "lip") for t in k.content.controls)]
    for slupek in slupki:
        slupek.on_click(None)

    assert sorted(trasy) == ["/rok/2025/2", "/rok/2025/7"], "tylko miesiące z wydatkami"


def test_router_kladzie_miesiac_na_roku(baza, dzis, monkeypatch):
    """`/rok/2025/7` to rok i miesiąc w stosie — systemowe „wstecz” zdejmuje
    miesiąc i odsłania rok. `/miesiac/…` stoi wprost na ekranie głównym."""
    dzis(date(2026, 10, 15))
    a = _auto()
    _koszt(a, date(2025, 7, 1), 10.0)
    monkeypatch.setattr(ft, "run", lambda *args, **kwargs: None)
    import log
    import main

    # main() zakłada plik logu z hakami wyjątków i zapamiętuje motyw — oba
    # globalne, więc nie mogą przeżyć tego testu.
    monkeypatch.setattr(log, "wlacz", lambda: True)
    monkeypatch.setitem(utils.wyglad._OSTATNI_MOTYW, "nazwa", utils.wyglad._OSTATNI_MOTYW["nazwa"])
    strona = pomoce.zbuduj_strone()
    page = strona.page
    monkeypatch.setattr(type(page), "run_task", lambda self, *args, **kwargs: None)
    main.main(page)

    utils.przejdz(page, "/rok/2025/7")
    assert [type(w).__name__ for w in page.views] == ["MainView", "RokWPigulceView", "MiesiacWPigulceView"]
    assert page.views[-1].route == "/rok/2025/7"

    utils.przejdz(page, "/miesiac/2025/7")
    assert [type(w).__name__ for w in page.views] == ["MainView", "MiesiacWPigulceView"]
    assert main._cel_trasy(["miesiac", "2025", "7"])[0] is False
