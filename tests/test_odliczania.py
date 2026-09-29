"""Ekran „Ile zostało do…” i jego kafelek (katalog: M-04).

Jedna lista odliczań: terminy dokumentów, gwarancja (data i limit przebiegu),
każdy podzespół z interwałem i najbliższy okrągły przebieg — każde z paskiem
i datą, od najbliższego. Pilnujemy trzech rzeczy:

1. **Liczby są te same, co gdzie indziej** — dni i status dokumentu z
   `terminy_pojazdu` (progi powiadomień), podzespół z `oblicz_stan_interwalu`
   (licznik „najpierw”), prognozy z tego samego średniego przebiegu.
2. **Pasek mówi, jaka część okresu minęła** — dokument: rok przed terminem,
   gwarancja: od pierwszej rejestracji albo zakupu (bez nich — bez paska),
   limit km gwarancji: od zera, podzespół: zużycie interwału, okrągły
   przebieg: od poprzedniej okrągłej liczby w jednostce z Ustawień.
3. **Kolejność i ekran** — po terminie na górze, dalej po dacie, bez daty na
   końcu; podgląd nie dostaje wierszy prowadzących do formularzy; sprzedane
   auto i auto bez danych mają własne stany; kafelek pokazuje trzy pierwsze.
"""

import sqlite3
from datetime import date, timedelta

import flet as ft
import pytest

import db
import pomoce
import utils

POLA_DZIECI = ("controls", "content", "items", "actions", "leading", "trailing", "title", "subtitle")


# ============================================================================
#  POMOCNIKI
# ============================================================================

def za_dni(dni):
    return (date.today() + timedelta(days=dni)).strftime("%d.%m.%Y")


def auto(nazwa="Odliczane", **pola):
    kolumny = {"nazwa": nazwa, "typ_paliwa": "Benzyna", "status": db.STATUS_POJAZDU_AKTYWNY,
               "rola_wspoldzielenia": db.ROLA_WLASCICIEL}
    kolumny.update(pola)
    with db.polacz_baze() as conn:
        kursor = conn.execute(
            f"INSERT INTO samochody ({', '.join(kolumny)}) VALUES ({', '.join('?' for _ in kolumny)})",
            list(kolumny.values()))
        return kursor.lastrowid


def odczyt(auto_id, dni_temu, przebieg):
    with db.polacz_baze() as conn:
        conn.execute("INSERT INTO odczyty_przebiegu (auto_id, data, przebieg, zrodlo) VALUES (?,?,?,?)",
                     (auto_id, za_dni(-dni_temu), przebieg, db.ZRODLO_ODCZYTU_DOMYSLNE))


def z_licznikiem(auto_id, przebieg=102400):
    """Dwa odczyty 60 dni od siebie, 2 400 km różnicy — średnio 40 km dziennie;
    ostatni dzisiejszy, na `przebieg`."""
    odczyt(auto_id, 60, przebieg - 2400)
    odczyt(auto_id, 0, przebieg)
    return auto_id


def podzespol(auto_id, nazwa="Olej silnikowy", interwal_km=None, interwal_miesiace=None,
              dni_temu=None, przebieg=None):
    with db.polacz_baze() as conn:
        kursor = conn.execute(
            "INSERT INTO zadania (auto_id, nazwa, interwal_km, interwal_miesiace, data, przebieg) "
            "VALUES (?,?,?,?,?,?)",
            (auto_id, nazwa, interwal_km, interwal_miesiace,
             za_dni(-dni_temu) if dni_temu is not None else None, przebieg))
        return kursor.lastrowid


def pozycja(pozycje, klucz):
    znalezione = [p for p in pozycje if p["klucz"] == klucz]
    assert znalezione, f"brak pozycji {klucz} wśród {[p['klucz'] for p in pozycje]}"
    return znalezione[0]


def _wszystkie(korzen, typ):
    znalezione = []

    def zejdz(kontrolka):
        if isinstance(kontrolka, typ):
            znalezione.append(kontrolka)
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


def teksty(kontrolka):
    return [t.value for t in _wszystkie(kontrolka, ft.Text) if isinstance(t.value, str)]


def ekran(auto_id, nazwa="Odliczane"):
    stan = pomoce.stan_aplikacji(auto_id, nazwa)
    return pomoce.zbuduj_widok(pomoce.klasy_widokow()["OdliczaniaView"], pomoce.zbuduj_strone(), stan)


def karty(widok):
    """Karty wierszy odliczań — kontenery z `karta_listy` (mają animację nacisku)."""
    return [k for k in _wszystkie(widok, ft.Container) if getattr(k, "animate_scale", None) is not None]


# ============================================================================
#  DOKUMENTY I GWARANCJA
# ============================================================================

def test_bez_pojazdu_i_bez_danych_nie_ma_czego_odliczac(baza):
    assert db.odliczania_pojazdu(None) == []
    assert db.odliczania_pojazdu(auto()) == []


def test_dokument_liczy_pasek_z_roku_przed_terminem(baza):
    auto_id = auto(oc_data=za_dni(100))
    oc = pozycja(db.odliczania_pojazdu(auto_id), "dokument:oc")

    termin = date.today() + timedelta(days=100)
    rok = (termin - termin.replace(year=termin.year - 1)).days
    assert oc["dni"] == 100 and oc["data"] == termin and not oc["prognoza"]
    assert oc["udzial"] == pytest.approx((rok - 100) / rok)
    assert oc["tytul"] == "Polisa OC" and oc["status"] == "ok"
    assert oc["trasa"] == f"/auto/edytuj/{auto_id}"


def test_status_dokumentu_idzie_za_progiem_powiadomienia(baza):
    """„Blisko” znaczy dokładnie to, co w dzwonku: termin w progu z Ustawień."""
    prog = db.pobierz_prog_dni_dokumentu("przeglad")
    auto_id = auto(przeglad_data=za_dni(prog), oc_data=za_dni(prog + 1))
    pozycje = db.odliczania_pojazdu(auto_id)
    assert pozycja(pozycje, "dokument:przeglad")["status"] == "blisko"
    assert pozycja(pozycje, "dokument:oc")["status"] == "ok"


def test_dokument_po_terminie_ma_pelny_pasek_i_stoi_na_gorze(baza):
    auto_id = auto(oc_data=za_dni(200), przeglad_data=za_dni(-5), ac_data=za_dni(-40))
    pozycje = db.odliczania_pojazdu(auto_id)

    assert [p["klucz"] for p in pozycje] == ["dokument:ac", "dokument:przeglad", "dokument:oc"]
    przeglad = pozycje[1]
    assert przeglad["status"] == "po_terminie" and przeglad["dni"] == -5 and przeglad["udzial"] == 1.0


def test_termin_dalej_niz_za_rok_ma_pusty_pasek(baza):
    """Pierwszy przegląd nowego auta bywa za trzy lata — okres roczny jeszcze się nie zaczął."""
    auto_id = auto(przeglad_data=za_dni(800))
    assert pozycja(db.odliczania_pojazdu(auto_id), "dokument:przeglad")["udzial"] == 0.0


def test_gwarancja_liczy_sie_od_pierwszej_rejestracji(baza):
    auto_id = auto(gwarancja_data=za_dni(365), data_pierwszej_rejestracji=za_dni(-730),
                   data_zakupu=za_dni(-100))
    gw = pozycja(db.odliczania_pojazdu(auto_id), "dokument:gwarancja")
    assert gw["poczatek_z"] == db.POCZATEK_REJESTRACJA
    assert gw["udzial"] == pytest.approx(730 / 1095)
    assert utils.podpis_odliczania(gw) == f"Liczona od pierwszej rejestracji: {za_dni(-730)}"


def test_gwarancja_bez_rejestracji_liczy_sie_od_zakupu(baza):
    auto_id = auto(gwarancja_data=za_dni(300), data_zakupu=za_dni(-300))
    gw = pozycja(db.odliczania_pojazdu(auto_id), "dokument:gwarancja")
    assert gw["poczatek_z"] == db.POCZATEK_ZAKUP and gw["udzial"] == pytest.approx(0.5)


def test_gwarancja_bez_poczatku_nie_dostaje_paska(baza):
    """Zgadnięta długość gwarancji kłamałaby bardziej niż brak paska. Data
    rejestracji PO końcu gwarancji to literówka, nie początek."""
    auto_id = auto(gwarancja_data=za_dni(300), data_pierwszej_rejestracji=za_dni(400))
    gw = pozycja(db.odliczania_pojazdu(auto_id), "dokument:gwarancja")
    assert gw["udzial"] is None and gw["poczatek"] is None
    assert "nie ma początku" in utils.podpis_odliczania(gw)

    widok = ekran(auto_id)
    assert _wszystkie(widok, ft.ProgressBar) == [], "pozycja bez początku okresu nie ma paska"


def test_limit_przebiegu_gwarancji(baza):
    auto_id = z_licznikiem(auto(gwarancja_przebieg=150000), przebieg=100000)
    gw = pozycja(db.odliczania_pojazdu(auto_id), "dokument:gwarancja_km")
    assert gw["zostalo_km"] == 50000 and gw["cel_km"] == 150000
    assert gw["udzial"] == pytest.approx(100000 / 150000)
    assert gw["dni"] == 1250 and gw["prognoza"]  # 50 000 km po 40 km dziennie
    assert gw["data"] == date.today() + timedelta(days=1250)
    assert gw["status"] == "ok"
    assert utils.tytul_odliczania(gw) == "Gwarancja — limit km"


def test_przekroczony_limit_gwarancji(baza):
    auto_id = z_licznikiem(auto(gwarancja_przebieg=100000), przebieg=102400)
    gw = pozycja(db.odliczania_pojazdu(auto_id), "dokument:gwarancja_km")
    assert gw["status"] == "po_terminie" and gw["zostalo_km"] == -2400 and gw["dni"] is None
    assert gw["udzial"] == 1.0
    assert utils.opis_odliczania(gw) == "przekroczono o 2 400 km"


def test_limit_gwarancji_bez_przebiegu_nie_odlicza(baza):
    """„Zostało 150 000 km” przy pustym liczniku byłoby liczbą z niczego."""
    auto_id = auto(gwarancja_przebieg=150000)
    assert db.odliczania_pojazdu(auto_id) == []


# ============================================================================
#  PODZESPOŁY
# ============================================================================

def test_podzespol_bierze_licznik_ktory_skonczy_sie_pierwszy(baza):
    """Te same liczby, co karta w Serwisie i dzwonek — z oblicz_stan_interwalu."""
    auto_id = z_licznikiem(auto())
    zid = podzespol(auto_id, interwal_km=15000, interwal_miesiace=12, dni_temu=300, przebieg=88000)
    olej = pozycja(db.odliczania_pojazdu(auto_id), f"podzespol:{zid}")

    with db.polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        wiersz = conn.execute("SELECT * FROM zadania WHERE id=?", (zid,)).fetchone()
    stan = db.oblicz_stan_interwalu(wiersz, 102400, db.oblicz_sredni_dzienny_przebieg(auto_id))
    assert stan["pierwsze"] == "km"
    assert olej["zostalo_km"] == stan["km"]["zostalo"] == 600
    assert olej["dni"] == stan["km"]["dni"] == 15 and olej["prognoza"]
    assert olej["udzial"] == pytest.approx(stan["km"]["zuzycie"])
    assert olej["drugi"] == stan["czas"]
    assert olej["status"] == "blisko"  # 600 km mieści się w progu km
    assert olej["trasa"] == f"/zadanie/edytuj/{zid}"
    assert utils.opis_odliczania(olej) == "zostało 600 km (ok. 15 dni)"
    assert utils.podpis_odliczania(olej).startswith("Termin dopiero")


def test_podzespol_czasowy_i_przeterminowany(baza):
    auto_id = auto()
    czasowy = podzespol(auto_id, "Płyn hamulcowy", interwal_miesiace=24, dni_temu=100)
    stary = podzespol(auto_id, "Filtr kabinowy", interwal_miesiace=12, dni_temu=400)
    pozycje = db.odliczania_pojazdu(auto_id)

    plyn = pozycja(pozycje, f"podzespol:{czasowy}")
    koniec = date.today() - timedelta(days=100) + timedelta(days=int(24 * db.DNI_W_MIESIACU_INTERWALU))
    assert plyn["data"] == koniec and plyn["dni"] == (koniec - date.today()).days
    assert plyn["zostalo_km"] is None and not plyn["prognoza"] and plyn["status"] == "ok"

    filtr = pozycja(pozycje, f"podzespol:{stary}")
    assert filtr["status"] == "po_terminie" and filtr["udzial"] == 1.0
    assert pozycje[0]["klucz"] == f"podzespol:{stary}"


def test_podzespol_bez_pierwszej_wymiany_nie_trafia_na_liste(baza):
    """Bez daty i przebiegu wymiany nie ma licznika — Serwis mówi wtedy „Brak wpisów”."""
    auto_id = z_licznikiem(auto())
    podzespol(auto_id, interwal_km=15000)
    assert [p["rodzaj"] for p in db.odliczania_pojazdu(auto_id)] == ["przebieg"]


def test_kilometry_bez_sredniej_sortuja_sie_po_drugim_liczniku(baza):
    """Bez średniego przebiegu licznik km nie ma daty. Termin czasowy jest wtedy
    granicą, której podzespół nie przekroczy — lepsze miejsce niż koniec listy."""
    auto_id = auto(oc_data=za_dni(300))
    odczyt(auto_id, 0, 100000)  # jeden odczyt: jest przebieg, nie ma średniej
    zid = podzespol(auto_id, interwal_km=15000, interwal_miesiace=12, dni_temu=250, przebieg=89000)
    pozycje = db.odliczania_pojazdu(auto_id)

    olej = pozycja(pozycje, f"podzespol:{zid}")
    assert olej["dni"] is None and olej["data"] is None
    assert olej["dni_sortowania"] == olej["drugi"]["dni"]
    assert [p["klucz"] for p in pozycje][:2] == [f"podzespol:{zid}", "dokument:oc"]
    assert pozycje[-1]["rodzaj"] == "przebieg", "okrągły przebieg bez średniej nie ma daty"


# ============================================================================
#  OKRĄGŁY PRZEBIEG
# ============================================================================

def test_okragly_przebieg_co_dziesiec_tysiecy_km(baza):
    auto_id = z_licznikiem(auto())
    cel = pozycja(db.odliczania_pojazdu(auto_id), "przebieg")
    assert cel["cel_km"] == 110000 and cel["od_km"] == 100000 and cel["zostalo_km"] == 7600
    assert cel["udzial"] == pytest.approx(0.24)
    assert cel["dni"] == 190 and cel["prognoza"] and cel["status"] == db.STATUS_INFORMACJI
    assert cel["trasa"] == "/przebieg"
    assert utils.tytul_odliczania(cel) == "110 000 km na liczniku"


def test_okragly_przebieg_w_milach_jest_okragly_w_milach(baza):
    db.zapisz_jednostke_dystansu("mi")
    auto_id = z_licznikiem(auto())
    cel = pozycja(db.odliczania_pojazdu(auto_id), "przebieg")
    w_milach = 102400 / db.KM_W_MILI
    assert cel["cel_km"] == pytest.approx(70000 * db.KM_W_MILI)
    assert cel["udzial"] == pytest.approx((w_milach - 60000) / 10000)
    assert utils.tytul_odliczania(cel) == "70 000 mi na liczniku"
    # 6 372 mi — czasownik idzie za liczbą na ekranie („zostały”), nie za kilometrami.
    assert utils.opis_odliczania(cel).startswith(f"zostały {utils.formatuj_liczba(70000 - w_milach, 0)} mi")


def test_stan_na_okraglej_liczbie_celuje_w_nastepna(baza):
    auto_id = z_licznikiem(auto(), przebieg=110000)
    cel = pozycja(db.odliczania_pojazdu(auto_id), "przebieg")
    assert cel["cel_km"] == 120000 and cel["udzial"] == 0.0


# ============================================================================
#  KOLEJNOŚĆ I SPRZEDAŻ
# ============================================================================

def test_kolejnosc_od_najblizszego(baza):
    auto_id = z_licznikiem(auto(oc_data=za_dni(100), przeglad_data=za_dni(-3), gasnica_data=za_dni(400)))
    zid = podzespol(auto_id, interwal_km=15000, dni_temu=30, przebieg=88000)
    klucze = [p["klucz"] for p in db.odliczania_pojazdu(auto_id)]
    assert klucze == ["dokument:przeglad", f"podzespol:{zid}", "dokument:oc", "przebieg", "dokument:gasnica"]


def test_sprzedane_auto_nie_ma_odliczan(baza):
    auto_id = z_licznikiem(auto(oc_data=za_dni(100)))
    db.oznacz_pojazd_sprzedany(auto_id, za_dni(-1), 20000.0)
    assert db.odliczania_pojazdu(auto_id) == []
    assert "Auto jest sprzedane" in teksty(ekran(auto_id))


# ============================================================================
#  SŁOWA
# ============================================================================

@pytest.mark.parametrize("dni, oczekiwany", [
    (-5, "5 dni po terminie"), (-1, "1 dzień po terminie"), (0, "dzisiaj"), (1, "jutro"),
    (12, "za 12 dni"), (143, "za 143 dni (~5 mies.)"), (1100, "za 1 100 dni (~3 lata)"),
])
def test_opis_terminu_w_dniach(baza, dni, oczekiwany):
    assert utils.opis_odliczania({"dni": dni}) == oczekiwany


@pytest.mark.parametrize("pola, oczekiwany", [
    ({"dni": 12}, "za 12 dni"), ({"dni": 143}, "za ~5 mies."), ({"dni": 0}, "dziś"),
    ({"dni": -3}, "3 dni po terminie"), ({"dni": 40, "prognoza": True}, "za ok. 40 dni"),
    ({"dni": 800}, "za ~2 lata"), ({"zostalo_km": 3200}, "3 200 km"),
    ({"zostalo_km": -10}, "ponad limit"), ({}, ""),
])
def test_krotki_opis_na_kafelek(baza, pola, oczekiwany):
    assert utils.krotki_opis_odliczania(pola) == oczekiwany


def test_opis_kilometrow_z_prognoza(baza):
    assert utils.opis_odliczania({"zostalo_km": 3200, "dni": 80}) == "zostało 3 200 km (~3 mies.)"
    assert utils.opis_odliczania({"zostalo_km": 1, "dni": 0}) == "został 1 km (dziś)"
    assert utils.opis_odliczania({"zostalo_km": 3200}) == "zostało 3 200 km"
    assert utils.data_odliczania({"data": date(2027, 2, 14), "prognoza": True}) == "ok. 14.02.2027"
    assert utils.data_odliczania({"data": None}) == ""


def test_stan_listy_mowi_ile_goni(baza):
    assert utils.stan_odliczan([{"status": "ok"}, {"status": "info"}]) is None
    assert utils.stan_odliczan([{"status": "po_terminie"}, {"status": "blisko"}, {"status": "blisko"}]) == \
        "1 pozycja po terminie · 2 pozycje blisko terminu"


# ============================================================================
#  EKRAN
# ============================================================================

def test_ekran_ma_karte_na_kazde_odliczanie(baza):
    auto_id = z_licznikiem(auto(oc_data=za_dni(10), gwarancja_data=za_dni(300), data_zakupu=za_dni(-300)))
    podzespol(auto_id, interwal_km=15000, dni_temu=30, przebieg=88000)
    pozycje = db.odliczania_pojazdu(auto_id)

    widok = ekran(auto_id)
    wiersze = karty(widok)
    assert len(wiersze) == len(pozycje) == 4
    assert all(k.on_click is not None for k in wiersze)
    tresc = teksty(widok)
    assert "4 odliczania od najbliższego" in tresc
    assert "· 2 pozycje blisko terminu" in tresc  # OC za 10 dni i olej w progu km
    assert "Polisa OC" in tresc and "110 000 km na liczniku" in tresc
    assert len(_wszystkie(widok, ft.ProgressBar)) == 4


def test_podglad_nie_prowadzi_do_formularzy(baza):
    """Rola „tylko podgląd”: dokument otwiera Kartę pojazdu, podzespół nic,
    okrągły przebieg dalej Historię licznika."""
    auto_id = z_licznikiem(auto(oc_data=za_dni(10)))
    podzespol(auto_id, interwal_km=15000, dni_temu=30, przebieg=88000)
    db.ustaw_role_pojazdu(auto_id, db.ROLA_PODGLAD)

    widok = ekran(auto_id)
    trasy = {p["rodzaj"]: widok._trasa(p) for p in widok.pozycje}
    assert trasy == {"dokument": "/pojazd", "podzespol": None, "przebieg": "/przebieg"}
    assert sum(1 for k in karty(widok) if k.on_click is None) == 1


def test_pusty_ekran_zaprasza_do_uzupelnienia(baza):
    auto_id = auto()
    tresc = teksty(ekran(auto_id))
    assert "Nic tu jeszcze nie odlicza" in tresc and "Uzupełnij daty" in tresc

    db.ustaw_role_pojazdu(auto_id, db.ROLA_PODGLAD)
    tresc = teksty(ekran(auto_id))
    assert "Nic tu jeszcze nie odlicza" in tresc and "Uzupełnij daty" not in tresc


def test_ekran_jest_w_szufladzie_i_wyszukiwarce(baza):
    wpis = utils.EKRANY_WG_ID["ile-zostalo"]
    assert wpis["trasa"] == "/ile-zostalo" and wpis["grupa"] == "pojazd"
    for fraza in ("ile zostało", "odliczanie", "kamień milowy"):
        assert "ile-zostalo" in [e["id"] for e in utils.znajdz_ekrany(fraza)]


# ============================================================================
#  KAFELEK KOKPITU
# ============================================================================

def kokpit(auto_id, nazwa="Odliczane"):
    stan = pomoce.stan_aplikacji(auto_id, nazwa)
    stan.zakladka = 0
    db.zapisz_widgety_kokpitu(["ile_zostalo"], auto_id)
    return pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(), stan)


def test_kafelek_pokazuje_trzy_najblizsze(baza):
    auto_id = z_licznikiem(auto(oc_data=za_dni(10), przeglad_data=za_dni(-2), ac_data=za_dni(200)))
    podzespol(auto_id, interwal_km=15000, dni_temu=30, przebieg=88000)

    tresc = teksty(kokpit(auto_id).kokpit_kontener)
    assert "Ile zostało do…  (+2)" in tresc
    assert "Przegląd techniczny" in tresc and "2 dni po terminie" in tresc
    assert tresc.index("Przegląd techniczny") < tresc.index("Polisa OC") < tresc.index("Olej silnikowy")
    assert "za 10 dni" in tresc and "za ok. 15 dni" in tresc
    assert "Polisa AC" not in tresc and "110 000 km na liczniku" not in tresc, \
        "czwarta i piąta pozycja zostają na ekranie"


def test_pusty_kafelek_chowa_sie(baza):
    """Bez żadnej daty, interwału i przebiegu kafelek nie ma o czym mówić."""
    widok = kokpit(auto())
    assert "ile_zostalo" in widok._kokpit_puste

    db.zapisz_chowanie_pustych_kafelkow(False)
    assert "Brak terminów" in teksty(kokpit(auto("Drugie")).kokpit_kontener)
