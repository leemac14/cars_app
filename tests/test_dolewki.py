"""Dolewki płynów (N-12): wpis „dolewka” i zużycie l/1000 km między wymianami.

1. rachunek — okresy od wymiany do wymiany, pomiar do ostatniej dolewki, okres bez dolewek,
   start od pierwszej dolewki, ocena i „rośnie”, rozpoznanie podzespołów po nazwie;
2. zapis — półka magazynu (l i ml, za mało na stanie), powiązany Inny koszt, edycja i usuwanie
   z cofnięciem, usunięcie kosztu albo pozycji magazynu z cofnięciem, scalanie pozycji;
3. dolewka jako źródło licznika, oś czasu, wyszukiwarka, eksport, chmura, kosz i plik dla kupującego;
4. dzwonek, odznaka, kafelek, ekran, formularz, router i pasek w formularzu kosztu.
"""

import sqlite3
from datetime import date, timedelta

import flet as ft
import pytest

import db
import pomoce
import sync
import utils
from date import na_iso
from db import plik_pojazdu as db_plik
from sync import pobieranie as sync_pobieranie
from sync import wysylanie as sync_wysylanie

KONFIG = {k["tabela"]: k for k in sync.KONFIGURACJA_SYNC}


# ============================================================================
#  POMOCNIKI
# ============================================================================

def auto(nazwa="Octavia", typ="Benzyna", **pola):
    kolumny = {"nazwa": nazwa, "typ_paliwa": typ, "status": db.STATUS_POJAZDU_AKTYWNY,
               "rola_wspoldzielenia": db.ROLA_WLASCICIEL, "olej_typ": "5W-30", **pola}
    with db.polacz_baze() as conn:
        return conn.execute(f"INSERT INTO samochody ({', '.join(kolumny)}) VALUES ({', '.join('?' * len(kolumny))})",
                            list(kolumny.values())).lastrowid


def zadanie(auto_id, nazwa="Olej silnikowy i filtr", wymiany=()):
    """Podzespół z wymianami [(data, przebieg)] w historii."""
    with db.polacz_baze() as conn:
        zid = conn.execute("INSERT INTO zadania (auto_id, nazwa, interwal_km) VALUES (?,?,?)",
                           (auto_id, nazwa, 15000)).lastrowid
        for data, przebieg in wymiany:
            conn.execute("INSERT INTO historia (zadanie_id, data, data_iso, przebieg, cena) VALUES (?,?,?,?,?)",
                         (zid, data, na_iso(data), przebieg, 0))
    return zid


def dolewka(auto_id, data, przebieg, ilosc=0.5, plyn=db.PLYN_OLEJ, **pola):
    return db.zapisz_dolewke(auto_id, {"data": data, "przebieg": przebieg, "ilosc": ilosc, "plyn": plyn, **pola})


def pozycja(auto_id, nazwa="Castrol 5W-30", ilosc=4.0, jednostka="l", cena=50.0, kategoria="Oleje i smary"):
    with db.polacz_baze() as conn:
        return conn.execute("INSERT INTO magazyn_czesci (auto_id, nazwa, kategoria, ilosc, jednostka, cena_jednostkowa) "
                            "VALUES (?,?,?,?,?,?)", (auto_id, nazwa, kategoria, ilosc, jednostka, cena)).lastrowid


def jeden(zapytanie, *parametry):
    with db.polacz_baze() as conn:
        return conn.execute(zapytanie, parametry).fetchone()


def stan(magazyn_id):
    return jeden("SELECT ilosc FROM magazyn_czesci WHERE id=?", magazyn_id)[0]


def przed(dni):
    return (date.today() - timedelta(days=dni)).strftime("%d.%m.%Y")


def rosnace(a):
    """Olej: 1 l na 10 000 km w zamkniętym okresie, potem 1 l na 4 000 km — zużycie rośnie."""
    zadanie(a, wymiany=[("01.01.2025", 100000), ("01.01.2026", 115000)])
    for data, km in (("01.04.2025", 105000), ("01.08.2025", 110000), ("01.03.2026", 117000), ("01.05.2026", 119000)):
        dolewka(a, data, km)


# ============================================================================
#  1. RACHUNEK
# ============================================================================

def test_zuzycie_miedzy_wymianami_do_ostatniej_dolewki(baza):
    a = auto()
    rosnace(a)
    z = db.zuzycie_plynu(a, db.PLYN_OLEJ)
    zamkniety, biezacy = z["okresy"]
    assert (zamkniety["od_przebieg"], zamkniety["do_przebieg"], zamkniety["litry"], zamkniety["km_pomiaru"],
            zamkniety["na_1000"]) == (100000, 115000, 1.0, 10000, 0.1)
    assert (biezacy["trwa"], biezacy["km_pomiaru"], biezacy["na_1000"]) == (True, 4000, 0.25)
    assert (z["na_1000"], z["z_biezacego"], z["poprzednio"], z["rosnie"], z["status"]) == \
        (0.25, True, 0.1, True, db.STATUS_PODWYZSZONE)
    assert z["zadania"] == ["Olej silnikowy i filtr"]
    (s,) = db.sygnaly_plynow(a)
    assert (s["tytul"], s["klucz"], s["trasa"]) == ("Zużycie oleju rośnie", "plyn:olej:rosnie:115000", "/dolewki/olej")
    assert "0,10 l/1000 km" in s["opis"] and "0,25 l/1000 km" in s["opis"]


def test_okres_bez_dolewek_to_zero_a_biezacy_bez_pomiaru(baza):
    a = auto()
    zadanie(a, wymiany=[("01.01.2024", 85000), ("01.01.2025", 100000), ("01.01.2026", 115000), ("01.06.2026", 130000)])
    dolewka(a, "01.04.2025", 105000)
    db.dodaj_odczyt_przebiegu(a, 131000, "01.07.2026")
    z = db.zuzycie_plynu(a, db.PLYN_OLEJ)
    # Wymiana sprzed pierwszej dolewki nie robi okresu „bez dolewek” — wtedy jeszcze nikt ich nie zapisywał.
    assert [o["od_przebieg"] for o in z["okresy"]] == [100000, 115000, 130000]
    pierwszy, bez_dolewek, biezacy = z["okresy"]
    assert pierwszy["na_1000"] == 0.1 and (bez_dolewek["na_1000"], bez_dolewek["km_pomiaru"]) == (0.0, 15000)
    assert biezacy["na_1000"] is None and biezacy["km_okresu"] == 1000
    assert (z["na_1000"], z["z_biezacego"], z["poprzednio"], z["status"]) == (0.0, False, 0.1, db.STATUS_NORMA)
    assert db.opis_okresu(bez_dolewek) == "bez dolewek na 15 000 km"


def test_bez_podzespolu_okres_od_pierwszej_dolewki(baza):
    a = auto()
    for data, km, litry in (("01.01.2026", 50000, 1.0), ("01.02.2026", 52000, 0.4), ("01.03.2026", 54000, 0.4)):
        dolewka(a, data, km, litry)
    (okres,) = db.zuzycie_plynu(a, db.PLYN_OLEJ)["okresy"]
    assert (okres["od_dolewki"], okres["od_przebieg"], okres["litry"], okres["litry_wszystkie"], okres["na_1000"]) == \
        (True, 50000, 0.8, 1.8, 0.2)


def test_dolewki_tuz_po_wymianie_licza_caly_zamkniety_okres(baza):
    a = auto()
    zadanie(a, wymiany=[("01.01.2025", 100000), ("01.01.2026", 115000)])
    dolewka(a, "02.01.2025", 100200, 0.3)
    zamkniety, biezacy = db.zuzycie_plynu(a, db.PLYN_OLEJ)["okresy"]
    assert (zamkniety["km_pomiaru"], zamkniety["na_1000"]) == (15000, 0.02)
    assert biezacy["dolewki"] == [] and biezacy["na_1000"] is None


def test_podzespoly_wymian_po_nazwie():
    zadania = {i: {"nazwa": n} for i, n in enumerate([
        "Olej silnikowy i filtr", "Filtr oleju", "Olej w skrzyni biegów", "Płyn hamulcowy", "Klocki hamulcowe",
        "Płyn chłodniczy", "Czynnik chłodniczy klimatyzacji", "Wymiana płynu hamulcowego DOT4"], start=1)}
    assert db.zadania_wymiany(db.PLYN_OLEJ, zadania) == [1]
    assert db.zadania_wymiany(db.PLYN_OLEJ, {k: v for k, v in zadania.items() if k != 1}) == [2]
    assert db.zadania_wymiany("hamulcowy", zadania) == [4, 8]
    assert db.zadania_wymiany("chlodniczy", zadania) == [6]
    assert db.zadania_wymiany("adblue", zadania) == []


def test_plyny_zaleza_od_napedu(baza):
    assert "adblue" in db.plyny_pojazdu(auto("Diesel", "Diesel"))
    assert db.plyny_pojazdu(auto("Benzyna")) == ["olej", "chlodniczy", "hamulcowy", "spryskiwacze"]
    ev = auto("Elektryk", "Elektryczny")
    assert db.plyny_pojazdu(ev) == ["chlodniczy", "hamulcowy", "spryskiwacze"]
    assert db.kafel_zuzycia_oleju(ev) is None
    dolewka(ev, "01.03.2026", 10000)
    assert db.PLYN_OLEJ in db.plyny_pojazdu(ev)


def test_progi_oceny_oleju():
    assert [db.status_zuzycia(x) for x in (None, 0.1, 0.15, 0.49, 0.5)] == \
        [None, db.STATUS_NORMA, db.STATUS_PODWYZSZONE, db.STATUS_PODWYZSZONE, db.STATUS_WYSOKIE]
    assert db.tekst_litrow(0.5) == "0,5 l" and db.tekst_litrow(1) == "1 l" and db.tekst_litrow(0.25) == "0,25 l"


# ============================================================================
#  2. ZAPIS, PÓŁKA I KOSZT
# ============================================================================

def test_dolewka_z_polki_zdejmuje_stan_i_zaklada_koszt(baza):
    a = auto()
    m = pozycja(a)
    d_id = dolewka(a, "10.03.2026", 120000, 0.5, magazyn_id=m, koszt=25, produkt="Castrol 5W-30")
    assert stan(m) == 3.5
    d = db.pobierz_dolewke(d_id)
    assert (d["ilosc_magazynu"], d["koszt"], d["magazyn_nazwa"]) == (0.5, 25.0, "Castrol 5W-30")
    assert jeden("SELECT kategoria, nazwa, kwota, data_iso FROM inne_koszty WHERE id=?", d["koszt_id"]) == \
        (db.KATEGORIA_INNE_DOLEWKI, "Dolewka: olej silnikowy 0,5 l (Castrol 5W-30)", 25.0, "2026-03-10")
    assert db.koszty_w_okresie(a)["inne"] == 25.0

    dolewka_ed = {"data": "10.03.2026", "przebieg": 120000, "ilosc": 1.0, "plyn": db.PLYN_OLEJ, "magazyn_id": m, "koszt": 50}
    assert db.zapisz_dolewke(a, dolewka_ed, d_id) == d_id
    assert stan(m) == 3.0 and jeden("SELECT kwota FROM inne_koszty WHERE id=?", d["koszt_id"]) == (50.0,)
    # Bez kosztu powiązany wpis znika, spoza magazynu — litry wracają na półkę.
    assert db.zapisz_dolewke(a, {**dolewka_ed, "koszt": None, "magazyn_id": None}, d_id) == d_id
    assert stan(m) == 4.0 and jeden("SELECT COUNT(*) FROM inne_koszty") == (0,)
    assert db.pobierz_dolewke(d_id)["koszt_id"] is None


def test_mililitry_i_za_malo_na_polce(baza):
    a = auto()
    m = pozycja(a, "Płyn hamulcowy DOT4", 300, "ml", 0.05, "Płyny eksploatacyjne")
    assert [p["id"] for p in db.pozycje_magazynu_dla_plynu(a, "hamulcowy")] == [m]
    d_id = dolewka(a, "10.03.2026", 120000, 0.5, plyn="hamulcowy", magazyn_id=m)
    assert stan(m) == 0 and db.pobierz_dolewke(d_id)["ilosc_magazynu"] == 300
    db.usun_dolewke_z_cofnieciem(d_id)
    assert stan(m) == 300


def test_usuniecie_dolewki_z_cofnieciem(baza):
    a = auto()
    m = pozycja(a)
    d_id = dolewka(a, "10.03.2026", 120000, 0.5, magazyn_id=m, koszt=25)
    k_id = db.pobierz_dolewke(d_id)["koszt_id"]
    with db.polacz_baze() as conn:
        conn.execute("UPDATE dolewki SET zdalne_id='dol-1' WHERE id=?", (d_id,))
        conn.execute("UPDATE inne_koszty SET zdalne_id='koszt-1' WHERE id=?", (k_id,))

    wynik = db.usun_dolewke_z_cofnieciem(d_id)
    assert db.pobierz_dolewki(a) == [] and stan(m) == 4.0 and jeden("SELECT COUNT(*) FROM inne_koszty") == (0,)
    assert {n[2] for n in db.pobierz_nagrobki(a)} >= {"dol-1", "koszt-1"}

    wynik["cofnij"]()
    (d,) = db.pobierz_dolewki(a)
    assert (d["koszt"], d["magazyn_id"], d["zdalne_id"], stan(m)) == (25.0, m, "dol-1", 3.5)
    assert jeden("SELECT zdalne_id FROM inne_koszty WHERE id=?", d["koszt_id"]) == ("koszt-1",)
    assert not {"dol-1", "koszt-1"} & {n[2] for n in db.pobierz_nagrobki(a)}


@pytest.mark.parametrize("grupowo", [False, True])
def test_usuniecie_kosztu_z_listy_i_cofniecie_dowiazuje_dolewke(baza, grupowo):
    a = auto()
    d_id = dolewka(a, "10.03.2026", 120000, 0.5, koszt=30)
    k_id = db.pobierz_dolewke(d_id)["koszt_id"]
    wynik = db.usun_wiele_z_cofnieciem("inne_koszty", [k_id]) if grupowo else db.usun_z_cofnieciem("inne_koszty", k_id)
    assert db.pobierz_dolewke(d_id)["koszt_id"] is None
    wynik["cofnij"]()
    d = db.pobierz_dolewke(d_id)
    assert d["koszt_id"] == k_id and d["koszt"] == 30.0, "koszt wraca z kosza pod wolnym id i dolewka go dostaje"


def test_pozycja_magazynu_usunieta_scalona_i_w_historii_zuzycia(baza):
    a = auto()
    m = pozycja(a)
    d_id = dolewka(a, "10.03.2026", 120000, 0.5, magazyn_id=m, koszt=25)
    (wpis,) = db.pobierz_historie_zuzycia(m)
    assert (wpis["zrodlo"], wpis["ilosc"], wpis["koszt"], wpis["trasa"]) == ("dolewki", 0.5, 25.0, f"/dolewki/edytuj/{d_id}")
    assert db.pobierz_podsumowanie_zuzycia(a)[m]["liczba"] == 1

    wynik = db.usun_czesc_magazynu_z_cofnieciem(m)
    assert db.pobierz_dolewke(d_id)["magazyn_id"] is None
    wynik["cofnij"]()
    assert db.pobierz_dolewke(d_id)["magazyn_id"] == m

    m2 = pozycja(a, "castrol 5w-30", 1.0)
    db.scal_duplikaty_nazw(a, "magazyn_czesci", m2, [m])
    assert db.pobierz_dolewke(d_id)["magazyn_id"] == m2


# ============================================================================
#  3. LICZNIK, OŚ CZASU, WYSZUKIWARKA, EKSPORT, CHMURA, KOSZ
# ============================================================================

def test_dolewka_jest_zrodlem_licznika(baza):
    a = auto()
    d_id = dolewka(a, "10.03.2026", 150000)
    assert db.pobierz_aktualny_przebieg(a) == 150000
    (w,) = [w for w in db.pobierz_pelna_historie_przebiegu(a) if w["zrodlo"] == "dolewka"]
    assert (w["opis"], w["trasa"], w["etykieta_zrodla"]) == ("Olej silnikowy", f"/dolewki/edytuj/{d_id}", "Dolewka płynu")
    assert db.sprawdz_czy_przebieg_podejrzany(a, 140000, nowa_data_str="11.03.2026")
    assert db.sprawdz_czy_przebieg_podejrzany(a, 140000, wyklucz_id=d_id, tabela="dolewki",
                                              nowa_data_str="11.03.2026") is None


def test_os_czasu_wyszukiwarka_i_eksport(baza):
    a = auto()
    dolewka(a, "10.03.2026", 150000, 0.5, koszt=25, produkt="Castrol Edge")
    zdarzenia = db.pobierz_dane_timeline(a)
    assert [(z[1], z[3], z[5]) for z in zdarzenia] == [("Dolewka", "Dolewka: olej silnikowy", 25.0)]
    assert [w["typ"] for w in db.globalne_wyszukiwanie(a, "castrol")] == ["Dolewka"]
    assert "Dolewka" in [w["typ"] for w in db.globalne_wyszukiwanie(a, "olej")]
    naglowki, wiersze = db.pobierz_dane_eksportu(a, ["dolewki"])["dolewki"]
    assert dict(zip(naglowki, wiersze[0])) == {
        "Data": "10.03.2026", "Przebieg (km)": 150000, "Płyn": "Olej silnikowy", "Ilość (l)": "0,50",
        "Produkt": "Castrol Edge", "Z magazynu": "", "Koszt": "25,00", "Notatka": ""}


def test_dolewka_z_kosztem_i_polka_jedzie_na_drugi_telefon(baza):
    a = auto()
    m = pozycja(a)
    dolewka(a, "10.03.2026", 150000, 0.5, magazyn_id=m, koszt=25)
    chmura = pomoce.ChmuraWPamieci()
    for tabela in ("magazyn_czesci", "inne_koszty", "dolewki"):
        assert sync_wysylanie._wypchnij_tabele(chmura, "wspolny", a, KONFIG[tabela], db.ROLA_WLASCICIEL)[0] == 1
    wyslana = next(d for d in chmura.rekordy.values() if "plyn" in d)
    assert wyslana["koszt_id_zdalne"] and wyslana["magazyn_id_zdalne"] and "data_iso" not in wyslana

    # Drugi telefon to druga baza — tu ten sam plik, więc pojazd A znika, zanim B dostanie rekordy.
    with db.polacz_baze() as conn:
        conn.execute("DELETE FROM samochody WHERE id=?", (a,))
    b = auto("Drugi telefon")
    for zdalne_id, dane in chmura.rekordy.items():
        tabela = "dolewki" if "plyn" in dane else "inne_koszty" if "kwota" in dane else "magazyn_czesci"
        if tabela != "dolewki":
            sync_pobieranie._zastosuj_rekord(KONFIG[tabela], {"id": zdalne_id, "dane": dane}, b, {})
    zdalne_dolewki = next(z for z, d in chmura.rekordy.items() if "plyn" in d)
    assert sync_pobieranie._zastosuj_rekord(KONFIG["dolewki"], {"id": zdalne_dolewki, "dane": wyslana}, b, {}) == 1
    (d,) = db.pobierz_dolewki(b)
    assert (d["koszt"], d["magazyn_nazwa"], d["data_iso"]) == (25.0, "Castrol 5W-30", "2026-03-10")


def test_kosz_i_plik_dla_kupujacego(baza):
    p = pomoce.utworz_pojazd("Z dolewką")
    m = pozycja(p["auto_id"])
    dolewka(p["auto_id"], "10.03.2026", 101500, 0.5, magazyn_id=m, koszt=25)
    # Zajęte id przy przywracaniu: wiersze dostają nowe, a odwołania dolewek idą za nimi.
    obcy = auto("Obcy")
    with db.polacz_baze() as conn:
        for tabela in ("magazyn_czesci", "inne_koszty"):
            conn.execute(f"INSERT INTO {tabela} (auto_id, nazwa, ilosc) VALUES (?,?,?)" if tabela == "magazyn_czesci"
                         else f"INSERT INTO {tabela} (auto_id, data, kategoria, nazwa, kwota) VALUES (?,?,?,?,?)",
                         (obcy, "Obca", 1) if tabela == "magazyn_czesci" else (obcy, "01.01.2026", "Ogólne", "Obcy", 1))
    wynik = db.usun_auto_do_kosza(p["auto_id"])
    with db.polacz_baze() as conn:
        conn.execute("UPDATE magazyn_czesci SET id=id+1000 WHERE auto_id=?", (obcy,))
    nowe = db.przywroc_auto_z_kosza(wynik["kosz_id"])
    pierwsza, druga = db.pobierz_dolewki(nowe)
    assert (pierwsza["magazyn_nazwa"], pierwsza["koszt"], pierwsza["notatka"]) == ("Filtr oleju", None, "Przed trasą")
    assert (druga["magazyn_nazwa"], druga["koszt"]) == ("Castrol 5W-30", 25.0)

    migawka = db.zrzut_pojazdu(nowe)
    db_plik._wytnij_sekcje(migawka, db_plik.sekcje_zestawu(db_plik.ZESTAW_DLA_KUPUJACEGO))
    db_plik._uporzadkuj_powiazania(migawka)
    assert [(w["koszt_id"], w["magazyn_id"] is not None) for w in migawka["tabele"]["dolewki"]["wiersze"]] == \
        [(None, True), (None, True)]


# ============================================================================
#  4. DZWONEK, KAFELEK, EKRANY
# ============================================================================

def test_dzwonek_odznaka_i_sprzedane_auto(baza):
    a = auto()
    rosnace(a)
    assert [p["tytul"] for p in db.pobierz_powiadomienia(a) if p["typ"] == "plyn"] == ["Zużycie oleju rośnie"]
    assert db.liczniki_nawigacji(a)["dolewki"] == 1
    with db.polacz_baze() as conn:
        conn.execute("UPDATE samochody SET status=? WHERE id=?", (db.STATUS_POJAZDU_SPRZEDANY, a))
    assert not [p for p in db.pobierz_powiadomienia(a) if p["typ"] == "plyn"]


def test_ubytek_w_ukladzie_zamknietym(baza):
    a = auto()
    dolewka(a, przed(200), 120000, 0.3, plyn="chlodniczy")
    assert not db.sygnaly_plynow(a)
    dolewka(a, przed(20), 124000, 0.3, plyn="chlodniczy")
    (s,) = db.sygnaly_plynow(a)
    assert s["tytul"] == "Ubywa: płyn chłodniczy" and s["opis"].startswith("2 dolewki w ostatnim roku")


def test_kafelek_i_linijka_podzespolu(baza):
    a = auto()
    assert db.kafel_zuzycia_oleju(a) == {"brak": True}
    rosnace(a)
    kafel = db.kafel_zuzycia_oleju(a)
    assert kafel["na_1000"] == 0.25 and utils.kolor_zuzycia(kafel) == utils.KOLOR_STATUS["warning"]
    (zid,) = db.zuzycie_przy_zadaniach(a)
    wiersz = utils.wiersz_zuzycia_podzespolu(db.zuzycie_przy_zadaniach(a)[zid])
    assert wiersz.controls[1].value == "Od wymiany dolano 1 l na 4 000 km · 0,25 l/1000 km"


def test_ekran_dolewek(baza):
    a = auto()
    rosnace(a)
    from views.dolewki_view import DolewkiView

    strona = pomoce.zbuduj_strone()
    widok = DolewkiView(strona.page, pomoce.stan_aplikacji(a, "Octavia"), "olej")
    teksty = pomoce.napisy(widok)
    assert {"Olej silnikowy", "0,25 l/1000 km", "Rośnie", "Bieżący okres · od 01.01.2026"} <= set(teksty)
    assert "Wcześniejsze okresy: 0,10 l/1000 km" in teksty and widok.plyn == "olej"
    pusty = DolewkiView(strona.page, pomoce.stan_aplikacji(a, "Octavia"), "adblue")
    assert "Brak dolewek" in pomoce.napisy(pusty)


@pytest.fixture
def ciche_komunikaty(monkeypatch):
    zebrane = []
    monkeypatch.setattr(utils, "pokaz_komunikat", lambda page, tekst, *a, **k: zebrane.append(tekst))
    return zebrane


def test_formularz_dolewki_z_polki(baza, ciche_komunikaty):
    from views.formularze import FormularzDolewkiView

    a = auto()
    m = pozycja(a)
    strona = pomoce.zbuduj_strone()
    strona.page.on_route_change = lambda e: None
    stan_app = pomoce.stan_aplikacji(a, "Octavia")
    f = FormularzDolewkiView(strona.page, stan_app, None, plyn="olej")
    assert f.e_produkt.value == "5W-30"
    f.e_przebieg.value = "120000"
    f._ustaw_ilosc(0.5)
    f.e_magazyn.value = str(m)
    f._zmiana_pozycji()
    assert (f.e_koszt.value, f.e_produkt.value) == ("25", "Castrol 5W-30")
    f.zapisz(None)
    (d,) = db.pobierz_dolewki(a)
    assert (d["ilosc"], d["koszt"], d["produkt"], stan(m)) == (0.5, 25.0, "Castrol 5W-30", 3.5)
    assert ciche_komunikaty[-1].startswith("Zapisano dolewkę 0,5 l")

    # Edycja tej samej pozycji liczy po cenie z poprzedniego zapisu, nie po dzisiejszej.
    with db.polacz_baze() as conn:
        conn.execute("UPDATE magazyn_czesci SET cena_jednostkowa=80 WHERE id=?", (m,))
    e = FormularzDolewkiView(strona.page, stan_app, d["id"])
    assert e._dostepne(e._pozycja()) == 4.0
    e._ustaw_ilosc(1)
    assert e.e_koszt.value == "50"
    e.zapisz(None)
    assert (stan(m), db.pobierz_dolewke(d["id"])["koszt"]) == (3.0, 50.0)


def test_router_i_pasek_w_formularzu_kosztu(baza, monkeypatch):
    monkeypatch.setattr(ft, "run", lambda *a, **k: None)
    import main
    from views.formularze import FormularzInneView

    assert main._cel_trasy(["dolewki", "nowa", "olej"]) == (True, True, None, None)
    assert main._cel_trasy(["dolewki", "edytuj", "7"]) == (True, False, "dolewki", 7)
    assert main._cel_trasy(["dolewki", "olej"]) == (False, False, None, None)

    a = auto()
    d_id = dolewka(a, "10.03.2026", 120000, 0.5, koszt=30)
    strona = pomoce.zbuduj_strone()
    widok = FormularzInneView(strona.page, pomoce.stan_aplikacji(a, "Octavia"), db.pobierz_dolewke(d_id)["koszt_id"])
    assert any(t.startswith("Koszt dolewki z 10.03.2026 (olej silnikowy 0,5 l)") for t in pomoce.napisy(widok))
