"""Zdrowie danych (N-08): nieścisłości z różnych ekranów w jednym miejscu.

1. sprawdzenia — licznik, wpisy z przyszłości, cena (ta sama reguła co formularz), ciąg „do
   pełna”, wpisy bez licznika, martwe pliki, duplikaty, rodzaj napraw, terminy i karta auta;
2. „To nie błąd” na tym telefonie (klucz z treścią wpisu), przegląd i dzwonek raz na kwartał;
3. martwe pliki do kosza wpisów z „Cofnij” i przywróceniem z Kosza;
4. ekran, kafelek, karta w Ustawieniach, odnośniki z kondycji i Historii przebiegu, router.
"""

import json
import os
from datetime import date, timedelta

import flet as ft
import pytest

import db
import pomoce
import utils
from date import na_iso


# ============================================================================
#  POMOCNIKI
# ============================================================================

def auto(nazwa="Octavia", typ="Benzyna", **pola):
    """Auto z kompletną kartą — bez danych nie ma czego zgłaszać."""
    kolumny = {"nazwa": nazwa, "typ_paliwa": typ, "status": db.STATUS_POJAZDU_AKTYWNY,
               "rola_wspoldzielenia": db.ROLA_WLASCICIEL, "vin": "TMBJJ7NE8L0123456", "nr_rej": "WE 12345",
               "pojemnosc_baku": "50", "pojemnosc_baterii": "13", "oc_data": "01.01.2030",
               "przeglad_data": "01.01.2030", **pola}
    with db.polacz_baze() as conn:
        return conn.execute(f"INSERT INTO samochody ({', '.join(kolumny)}) VALUES ({', '.join('?' * len(kolumny))})",
                            list(kolumny.values())).lastrowid


def dzien(dni):
    """DD.MM.RRRR sprzed `dni` dni (ujemne — w przyszłości)."""
    return (date.today() - timedelta(days=dni)).strftime("%d.%m.%Y")


def wstaw(do_tabeli, /, **pola):
    if "data" in pola and do_tabeli in db.TABELE_Z_DATA_ISO:
        pola["data_iso"] = na_iso(pola["data"])
    with db.polacz_baze() as conn:
        return conn.execute(f"INSERT INTO {do_tabeli} ({', '.join(pola)}) VALUES ({', '.join('?' * len(pola))})",
                            list(pola.values())).lastrowid


def tankowanie(a, dni, przebieg, litry=40.0, kwota=260.0, pelny=1, energia=db.ENERGIA_PALIWO, stacja="Orlen"):
    return wstaw("tankowania", auto_id=a, data=dzien(dni), przebieg=przebieg, litry=litry, kwota=kwota,
                 do_pelna=pelny, rodzaj_energii=energia, stacja=stacja)


def odczyt(a, dni, przebieg):
    return wstaw("odczyty_przebiegu", auto_id=a, data=dzien(dni), przebieg=przebieg)


def pozycje(a, rodzaj=None):
    return [p for p in db.zdrowie_danych(a)["pozycje"] if rodzaj in (None, p["rodzaj"])]


def plik(nazwa, tresc=b"PLIK"):
    return db.wzgledna_sciezka_zalacznika(pomoce._plik_zalacznika(db.FOLDER_ZALACZNIKI, nazwa, tresc))


def przyciski(korzen, napis):
    return [b for b in pomoce.kontrolki(korzen, ft.TextButton)
            if napis in (b.content, getattr(b.content, "value", None))]


def ekran(a, nazwa="Octavia"):
    from views.zdrowie_danych_view import ZdrowieDanychView

    strona = pomoce.zbuduj_strone()  # trzymana przez wołającego — inaczej sesja strony znika
    strona.page.on_route_change = lambda e: None
    return ZdrowieDanychView(strona.page, pomoce.stan_aplikacji(a, nazwa)), strona


@pytest.fixture
def komunikaty(monkeypatch):
    """Komunikaty i „Cofnij” bez strony z pętlą zdarzeń: [napis] albo [(napis, wynik usuwania)]."""
    zebrane = []
    for modul in (utils, utils.zdrowie_danych):
        monkeypatch.setattr(modul, "pokaz_komunikat", lambda page, tekst, *a, **k: zebrane.append(tekst))
    monkeypatch.setattr(utils, "pokaz_komunikat_cofnij", lambda page, tekst, wynik, **k: zebrane.append((tekst, wynik)))
    return zebrane


# ============================================================================
#  1. SPRAWDZENIA
# ============================================================================

def test_kompletne_auto_bez_zastrzezen(baza):
    a = auto()
    for i, km in enumerate((100000, 100600, 101200)):
        tankowanie(a, 90 - i * 30, km)
    stan = db.zdrowie_danych(a)
    assert (stan["razem"], stan["pozycje"], stan["pominiete"]) == (0, [], [])
    assert stan["sprawdzone"] == list(db.SPRAWDZENIA_ZDROWIA)
    assert db.podsumowanie_zdrowia_danych(a) == {"razem": 0, "krytyczne": 0, "liczby": {}}
    assert db.zdrowie_danych(None)["razem"] == 0


def test_cofka_i_skok_licznika_prowadza_do_wpisu(baza):
    a = auto()
    for i in range(12):
        odczyt(a, 400 - i * 30, 100000 + i * 1000)
    odczyt(a, 60, 131000)                              # skok: 20 000 w dzień ponad zwykłe tempo
    t = tankowanie(a, 40, 130500)                      # cofka względem odczytu wyżej
    licznik = {p["anomalia"]: p for p in pozycje(a, "licznik")}
    assert set(licznik) == {"cofka", "skok"}
    cofka, skok = licznik["cofka"], licznik["skok"]
    assert (cofka["waga"], cofka["trasa"], skok["waga"], skok["trasa"]) == (
        "krytyczna", f"/tankowanie/edytuj/{t}", "ostrzezenie", "/przebieg")
    assert cofka["poprzedni"]["przebieg"] == 131000 and cofka["klucz"].startswith(f"licznik:tankowanie_{t}:130500:")
    assert "o 500 km mniej niż wpis wcześniej: 131 000 km (Odczyt licznika" in utils.opis_pozycji_zdrowia(cofka, "km")
    assert "dziennie" in utils.opis_pozycji_zdrowia(skok, "km")


def test_nietypowa_cena_jak_w_formularzu(baza):
    """Ta sama reguła, co ostrzeżenie w formularzu: każdy wpis wobec 10 najbliższych w czasie
    cen swojego źródła energii (bez siebie), także przy remisach dat i bez daty."""
    a = auto(typ="Hybryda plug-in")
    for i in range(14):
        tankowanie(a, 300 - i * 20, 100000 + i * 500, kwota=255.0 + i)
    literowka = tankowanie(a, 150, 103600, kwota=2600.0)         # 65 zł/L zamiast 6,50
    tankowanie(a, 150, 103650, litry=4.0, kwota=26.0)             # ten sam dzień, cena w normie
    for i in range(4):
        tankowanie(a, 200 - i * 30, 100100 + i * 400, litry=30.0, kwota=36.0, energia=db.ENERGIA_PRAD)
    bez_daty = wstaw("tankowania", auto_id=a, data="kiedyś", przebieg=0, litry=40.0, kwota=0.65, do_pelna=0,
                     rodzaj_energii=db.ENERGIA_PALIWO)

    (ceny_wysokie, ceny_niskie) = sorted(pozycje(a, "cena"), key=lambda p: -p["cena"])
    assert (ceny_wysokie["id"], ceny_wysokie["wyzsza"], round(ceny_wysokie["krotnosc"])) == (literowka, True, 10)
    assert (ceny_niskie["id"], ceny_niskie["wyzsza"]) == (bez_daty, False)
    opis = utils.opis_pozycji_zdrowia(ceny_wysokie)
    assert opis.startswith(f"65,00 {utils.symbol_waluty()}/L — ok. 10 razy więcej niż w tankowaniach obok")

    zgloszone = {p["id"] for p in pozycje(a, "cena")}
    with db.polacz_baze() as conn:
        wpisy = conn.execute("SELECT id, data, kwota, litry, rodzaj_energii FROM tankowania WHERE auto_id=?",
                             (a,)).fetchall()
    for tid, data, kwota, litry, energia in wpisy:
        z_formularza = db.nietypowa_cena(kwota / litry, db.ceny_jednostkowe_w_poblizu(
            a, data if na_iso(data) else None, energia, wyklucz_id=tid))
        assert (tid in zgloszone) == (z_formularza is not None), tid


def test_ciag_bez_do_pelna_przed_pierwszym_i_otwarty(baza):
    a = auto()
    przed = [tankowanie(a, 200, 100000, pelny=0), tankowanie(a, 190, 100300, pelny=0)]
    tankowanie(a, 180, 100700)
    tankowanie(a, 170, 101000, pelny=0)
    tankowanie(a, 160, 101300, pelny=0)                # środek historii — liczy się dłuższym odcinkiem
    tankowanie(a, 150, 101700)
    otwarty = [tankowanie(a, 20, 102100, pelny=0), tankowanie(a, 10, 102300, pelny=1, kwota=258.0)]
    with db.polacz_baze() as conn:                       # pełny bak bez licznika nie zamyka odcinka
        conn.execute("UPDATE tankowania SET przebieg=0 WHERE id=?", (otwarty[1],))

    ciagi = {p["polozenie"]: p for p in pozycje(a, "do_pelna")}
    assert set(ciagi) == {"przed_pierwszym", "otwarty"}
    assert [w["id"] for w in ciagi["przed_pierwszym"]["wpisy"]] == przed
    assert [w["id"] for w in ciagi["otwarty"]["wpisy"]] == otwarty
    assert (ciagi["otwarty"]["km"], ciagi["otwarty"]["bez_licznika"]) == (400, 1)
    assert ciagi["otwarty"]["trasa"] == f"/tankowanie/edytuj/{otwarty[1]}"
    assert utils.tytul_pozycji_zdrowia(ciagi["otwarty"]) == "2 tankowania z rzędu bez „do pełna”"
    tekst = utils.opis_pozycji_zdrowia(ciagi["otwarty"], "km")
    assert tekst.startswith(f"Zużycie za 400 km od {dzien(150)} policzy się dopiero po tankowaniu do pełna")
    assert tekst.endswith("Pełny bak bez stanu licznika nie zamyka odcinka.")

    tankowanie(a, 1, 102600)                             # pełny bak zamyka ciąg
    assert {p["polozenie"] for p in pozycje(a, "do_pelna")} == {"przed_pierwszym"}


def test_wpisy_z_przyszlosci_i_bez_licznika(baza):
    a = auto()
    jutro = tankowanie(a, -40, 100500)
    inny = wstaw("inne_koszty", auto_id=a, data=dzien(-400), kategoria="Ogólne", nazwa="Winieta", kwota=50.0)
    d = db.zapisz_dolewke(a, {"data": dzien(-3), "przebieg": 100600, "ilosc": 0.5, "plyn": db.PLYN_OLEJ, "koszt": 30})
    wstaw("do_zrobienia", auto_id=a, tytul="Umówić przegląd", termin=dzien(-30), wykonane=0)
    zadanie = wstaw("zadania", auto_id=a, nazwa="Klocki hamulcowe")
    wpis = wstaw("historia", zadanie_id=zadanie, data=dzien(5), cena=200.0)
    bez = tankowanie(a, 7, 0)

    przyszle = {(p["tabela"], p["id"]): p for p in pozycje(a, "przyszlosc")}
    assert set(przyszle) == {("tankowania", jutro), ("inne_koszty", inny), ("dolewki", d)}, "koszt dolewki należy do niej"
    assert przyszle[("inne_koszty", inny)]["trasa"] == f"/inne/edytuj/{inny}"
    bez_licznika = {(p["tabela"], p["id"]): p for p in pozycje(a, "bez_licznika")}
    assert set(bez_licznika) == {("historia", wpis), ("tankowania", bez)}
    assert utils.tytul_pozycji_zdrowia(bez_licznika[("historia", wpis)]) == "Wpis serwisowy · Klocki hamulcowe"
    assert bez_licznika[("historia", wpis)]["trasa"] == f"/wpis/edytuj/{wpis}"

    prad = auto("Elektryk", typ="Elektryczny")
    tankowanie(prad, 3, 0, energia=None)
    (ladowanie,) = pozycje(prad, "bez_licznika")
    assert ladowanie["etykieta"] == "Ładowanie"


def test_martwe_pliki_brak_i_przeniesiony(baza):
    a = auto(zdjecie_glowne="zalaczniki/nie_ma_zdjecia.jpg")
    t = tankowanie(a, 10, 100000)
    plik("jest.jpg")
    plik("inny_folder.jpg")
    dok = wstaw("dokumenty_pojazdu", auto_id=a, rodzaj="dowod", liczba_plikow=1)
    for tabela, rekord_id, sciezka, typ in (
            ("tankowania", t, "zalaczniki/jest.jpg", "paragon"),
            ("tankowania", t, "zalaczniki/zgubiony.jpg", "faktura"),
            ("tankowania", t, "/data/user/0/inny.telefon/files/data/zalaczniki/inny_folder.jpg", "zdjecie"),
            ("dokumenty_pojazdu", dok, "zalaczniki/skan.pdf", db.TYP_PLIKU_DOKUMENTU)):
        wstaw("zalaczniki", auto_id=a, tabela=tabela, rekord_id=rekord_id, sciezka=sciezka, typ=typ)
    wstaw("zdjecia_karoserii", auto_id=a, data=dzien(3), strefa="Przód", zalacznik="zalaczniki/rysa.jpg")

    martwe = {p["nazwa_pliku"]: p for p in pozycje(a, "pliki")}
    assert set(martwe) == {"nie_ma_zdjecia.jpg", "zgubiony.jpg", "inny_folder.jpg", "skan.pdf", "rysa.jpg"}
    assert martwe["inny_folder.jpg"]["stan"] == "przeniesiony" and martwe["zgubiony.jpg"]["stan"] == "brak"
    assert martwe["nie_ma_zdjecia.jpg"]["trasa"] == f"/auto/edytuj/{a}" and not martwe["nie_ma_zdjecia.jpg"]["usuwalny"]
    assert martwe["skan.pdf"]["trasa"] == f"/dokumenty/edytuj/{dok}" and martwe["skan.pdf"]["opis"] == db.etykieta_dokumentu("dowod")
    assert utils.tytul_pozycji_zdrowia(martwe["zgubiony.jpg"]) == "Faktura · Tankowanie · Orlen"

    assert db.napraw_sciezki_zalacznikow()[0] == 1   # „Odszukaj pliki”
    assert "inny_folder.jpg" not in {p["nazwa_pliku"] for p in pozycje(a, "pliki")}

    os.remove(os.path.join(db.FOLDER_ZALACZNIKI, "jest.jpg"))
    db.zanotuj_zmiane_danych()                           # plik znika poza bazą — pamięć tego nie widzi
    assert "jest.jpg" in {p["nazwa_pliku"] for p in pozycje(a, "pliki")}


def test_duplikaty_naprawy_bez_rodzaju_terminy_i_karta_auta(baza):
    a = auto(vin="", pojemnosc_baku=None, oc_data="", przeglad_data="32.13.2026")
    wstaw("magazyn_czesci", auto_id=a, nazwa="Filtr oleju", ilosc=1)
    wstaw("magazyn_czesci", auto_id=a, nazwa="filtr Oleju ", ilosc=2)
    zadanie = wstaw("zadania", auto_id=a, nazwa="Olej silnikowy", interwal_km=15000)
    wstaw("historia", zadanie_id=zadanie, data=dzien(30), przebieg=100000, cena=300.0)
    wstaw("wizyty", auto_id=a, data=dzien(20), przebieg=100200, koszt_calkowity=500.0)

    (nazwy,) = pozycje(a, "nazwy")
    assert nazwy["grupa"]["tabela"] == "magazyn_czesci" and nazwy["klucz"].endswith(":2")
    (naprawy,) = pozycje(a, "rodzaj")
    assert (naprawy["liczba"], naprawy["kwota"], naprawy["z_podpowiedzia"]) == (2, 800.0, 1)
    assert utils.tytul_pozycji_zdrowia(naprawy) == "2 naprawy bez rodzaju"
    terminy = {p["termin"]: p for p in pozycje(a, "terminy")}
    assert set(terminy) == {"oc", "przeglad"} and terminy["przeglad"]["nieczytelna"]
    assert utils.tytul_pozycji_zdrowia(terminy["oc"]) == "Polisa OC — brak daty"
    (karta,) = pozycje(a, "pojazd")
    assert (karta["pola"], karta["trasa"]) == (["VIN", "pojemność baku"], f"/auto/edytuj/{a}")

    elektryk = auto("Elektryk", typ="Elektryczny", pojemnosc_baku=None, pojemnosc_baterii="")
    assert pozycje(elektryk, "pojazd")[0]["pola"] == ["pojemność baterii"]

    with db.polacz_baze() as conn:
        conn.execute("UPDATE samochody SET status=? WHERE id=?", (db.STATUS_POJAZDU_SPRZEDANY, a))
    stan = db.zdrowie_danych(a)
    assert not {"terminy", "pojazd"} & set(stan["liczby"]) and "terminy" not in stan["sprawdzone"]
    assert {"nazwy", "rodzaj"} <= set(stan["liczby"]), "historia sprzedanego dalej się liczy"


# ============================================================================
#  2. „TO NIE BŁĄD”, PRZEGLĄD I DZWONEK
# ============================================================================

def test_to_nie_blad_na_tym_telefonie_i_wraca_po_zmianie_wpisu(baza):
    a = auto()
    for i in range(6):
        tankowanie(a, 100 - i * 10, 100000 + i * 500)
    t = tankowanie(a, 5, 103100, kwota=2600.0)
    (cena,) = pozycje(a, "cena")
    db.pomin_w_zdrowiu_danych(a, [cena["klucz"]])
    stan = db.zdrowie_danych(a)
    assert (stan["razem"], [p["klucz"] for p in stan["pominiete"]]) == (0, [cena["klucz"]])
    assert db.ustawienia._klucz_zdrowia_danych in db.USTAWIENIA_PER_POJAZD

    with db.polacz_baze() as conn:                       # poprawka, która dalej się nie zgadza
        conn.execute("UPDATE tankowania SET kwota=2500 WHERE id=?", (t,))
    assert [p["id"] for p in pozycje(a, "cena")] == [t], "zmieniony wpis wraca do sprawdzenia"

    with db.polacz_baze() as conn:
        conn.execute("UPDATE tankowania SET kwota=262 WHERE id=?", (t,))
    db.pomin_w_zdrowiu_danych(a, [])                     # zapis sprząta klucze, których nikt nie wykrywa
    assert db.pobierz_ustawienia_zdrowia(a)["pominiete"] == []

    with db.polacz_baze() as conn:
        conn.execute("UPDATE tankowania SET kwota=2600 WHERE id=?", (t,))
    db.pomin_w_zdrowiu_danych(a, [cena["klucz"]])
    db.przywroc_w_zdrowiu_danych(a, [cena["klucz"]])
    assert db.zdrowie_danych(a)["razem"] == 1

    db.zapisz_ustawienie(db.ustawienia._klucz_zdrowia_danych(a), "{zepsute")
    assert db.pobierz_ustawienia_zdrowia(a) == {"pominiete": [], "przejrzane": None}
    db.zapisz_ustawienie(db.ustawienia._klucz_zdrowia_danych(a), json.dumps({"pominiete": "x", "przejrzane": 5}))
    assert db.pobierz_ustawienia_zdrowia(a) == {"pominiete": [], "przejrzane": None}


def test_dzwonek_raz_na_kwartal_od_przegladu(baza):
    """Kwartał liczy się od ostatniego otwarcia ekranu; ekran nigdy nieotwierany nie dzwoni
    (po aktualizacji dzwoniłoby naraz każde auto z pustym VIN-em)."""
    a = auto(vin="")
    dzis = date.today()
    assert db.przeglad_danych_nalezny(a) is None and db.zdrowie_danych(a)["razem"] == 1

    db.zanotuj_przeglad_danych(a)
    assert db.pobierz_ustawienia_zdrowia(a)["przejrzane"] == dzis.isoformat()
    assert db.przeglad_danych_nalezny(a) is None
    db.zanotuj_przeglad_danych(a, dzis - timedelta(days=db.DNI_PRZEGLADU_DANYCH - 1))
    assert not [p for p in db.pobierz_powiadomienia(a) if p["typ"] == "zdrowie"]
    db.zanotuj_przeglad_danych(a, dzis - timedelta(days=db.DNI_PRZEGLADU_DANYCH))
    nalezny = db.przeglad_danych_nalezny(a)
    assert (nalezny["razem"], nalezny["dni"]) == (1, db.DNI_PRZEGLADU_DANYCH)
    (p,) = [p for p in db.pobierz_powiadomienia(a) if p["typ"] == "zdrowie"]
    assert (p["trasa"], p["status"], p["klucz"]) == (
        "/zdrowie-danych", "pilne", f"zdrowie:{(dzis - timedelta(days=db.DNI_PRZEGLADU_DANYCH)).isoformat()}")
    assert p["opis"] == f"1 rzecz do sprawdzenia — ostatni przegląd {db.DNI_PRZEGLADU_DANYCH} dni temu"
    assert "zdrowie" in db.TYPY_POWIADOMIEN_O_DANYCH

    db.odloz_powiadomienie(a, db.klucz_drzemki(p), 7)
    assert not [p for p in db.pobierz_powiadomienia(a) if p["typ"] == "zdrowie"]
    db.zanotuj_przeglad_danych(a)                        # otwarcie ekranu zaczyna nowy cykl
    assert db.przeglad_danych_nalezny(a) is None

    czyste = auto("Czyste")
    db.zanotuj_przeglad_danych(czyste, dzis - timedelta(days=200))
    assert db.przeglad_danych_nalezny(czyste) is None, "nie ma czego sprawdzić"
    with db.polacz_baze() as conn:
        conn.execute("UPDATE samochody SET rola_wspoldzielenia=? WHERE id=?", (db.ROLA_PODGLAD, a))
        conn.execute("DELETE FROM wyciszone_powiadomienia")
    db.zanotuj_przeglad_danych(a, dzis - timedelta(days=200))
    assert db.przeglad_danych_nalezny(a) and not [p for p in db.pobierz_powiadomienia(a) if p["typ"] == "zdrowie"], \
        "podgląd nic nie poprawi"
    assert "rodzaj" not in db.zdrowie_danych(a)["sprawdzone"]


# ============================================================================
#  3. MARTWE PLIKI DO KOSZA
# ============================================================================

def _martwe_pliki():
    a = auto(zdjecie_glowne="zalaczniki/nie_ma_zdjecia.jpg")
    t = tankowanie(a, 10, 100000)
    dok = wstaw("dokumenty_pojazdu", auto_id=a, rodzaj="dowod", liczba_plikow=2)
    zywy = wstaw("zalaczniki", auto_id=a, tabela="dokumenty_pojazdu", rekord_id=dok, sciezka=plik("jest.pdf"), typ="dokument")
    martwe = [wstaw("zalaczniki", auto_id=a, tabela=tabela, rekord_id=rid, sciezka=f"zalaczniki/{nazwa}", typ="paragon")
              for tabela, rid, nazwa in (("tankowania", t, "a.jpg"), ("dokumenty_pojazdu", dok, "b.pdf"))]
    karoseria = wstaw("zdjecia_karoserii", auto_id=a, data=dzien(3), strefa="Tył", zalacznik="zalaczniki/rysa.jpg")
    return a, dok, zywy, martwe, karoseria


def _wiersze(zapytanie, *parametry):
    with db.polacz_baze() as conn:
        return conn.execute(zapytanie, parametry).fetchall()


def test_martwe_pliki_ida_do_kosza_i_wracaja_z_cofnij(baza):
    a, dok, zywy, martwe, karoseria = _martwe_pliki()
    w_koszu = db.liczba_wpisow_w_koszu()

    wynik = db.usun_martwe_pliki(pozycje(a, "pliki"))
    assert wynik["liczba"] == 3 and wynik["w_koszu"]
    assert [r[0] for r in _wiersze("SELECT id FROM zalaczniki WHERE auto_id=?", a)] == [zywy]
    assert _wiersze("SELECT COUNT(*) FROM zdjecia_karoserii WHERE id=?", karoseria) == [(0,)]
    assert _wiersze("SELECT liczba_plikow FROM dokumenty_pojazdu WHERE id=?", dok) == [(1,)]
    assert _wiersze("SELECT zdjecie_glowne FROM samochody WHERE id=?", a) == [("zalaczniki/nie_ma_zdjecia.jpg",)], \
        "zdjęcie pojazdu to pole Karty — nie do kosza"
    assert db.liczba_wpisow_w_koszu() == w_koszu + 2
    assert [p["zrodlo"] for p in pozycje(a, "pliki")] == ["samochody"]

    wynik["cofnij"]()
    assert sorted(r[0] for r in _wiersze("SELECT id FROM zalaczniki WHERE auto_id=?", a)) == sorted([zywy] + martwe)
    assert _wiersze("SELECT COUNT(*) FROM zdjecia_karoserii WHERE id=?", karoseria) == [(1,)]
    assert _wiersze("SELECT liczba_plikow FROM dokumenty_pojazdu WHERE id=?", dok) == [(2,)]
    assert db.liczba_wpisow_w_koszu() == w_koszu and len(pozycje(a, "pliki")) == 4


def test_martwy_plik_z_kosza_wraca_z_ekranu_kosza_z_opisem(baza):
    from views.kosz_view import _opis_wpisu

    a, dok, zywy, martwe, karoseria = _martwe_pliki()
    pliki = [p for p in pozycje(a, "pliki") if p["zrodlo"] == "zalaczniki" and p["tabela"] == "tankowania"]
    wynik = db.usun_martwe_pliki(pliki)
    (pozycja,) = [p for p in db.pobierz_kosz_wpisow() if p["tabela"] == "zalaczniki"]
    assert _opis_wpisu(pozycja, "km") == (ft.Icons.BROKEN_IMAGE, "Plik wpisu", ["a.jpg", "Tankowanie"])
    assert db.przywroc_wpis_z_kosza(wynik["kosz_id"])["ok"]
    assert martwe[0] in [r[0] for r in _wiersze("SELECT id FROM zalaczniki WHERE auto_id=?", a)]

    db.usun_martwe_pliki([p for p in pozycje(a, "pliki") if p["zrodlo"] == "zalaczniki"])
    (dwa,) = [p for p in db.pobierz_kosz_wpisow() if p["tabela"] == "zalaczniki"]
    assert _opis_wpisu(dwa, "km")[1] == "2 pliki wpisów"


def test_podglad_nie_usunie_martwych_plikow(baza):
    a, *_ = _martwe_pliki()
    with db.polacz_baze() as conn:
        conn.execute("UPDATE samochody SET rola_wspoldzielenia=? WHERE id=?", (db.ROLA_PODGLAD, a))
    assert db.usun_martwe_pliki(pozycje(a, "pliki")) is None
    assert len(pozycje(a, "pliki")) == 4


# ============================================================================
#  4. EKRAN, KAFELEK, USTAWIENIA, ODNOŚNIKI
# ============================================================================

def _auto_z_problemami():
    a = auto(vin="")
    for i in range(6):
        tankowanie(a, 100 - i * 10, 100000 + i * 500)
    t = tankowanie(a, 5, 103100, kwota=2600.0)
    wstaw("magazyn_czesci", auto_id=a, nazwa="Filtr oleju", ilosc=1)
    wstaw("magazyn_czesci", auto_id=a, nazwa="filtr Oleju ", ilosc=2)
    wstaw("zalaczniki", auto_id=a, tabela="tankowania", rekord_id=t, sciezka="zalaczniki/zgubiony.jpg", typ="paragon")
    return a, t


def test_ekran_sekcje_przyciski_i_to_nie_blad(baza, komunikaty):
    a, t = _auto_z_problemami()
    widok, strona = ekran(a)
    page = strona.page
    teksty = pomoce.napisy(widok)
    assert {"4 do sprawdzenia", "Nietypowe ceny", "Duplikaty nazw", "Martwe załączniki",
            "Puste pola pojazdu", "Bez zastrzeżeń", "Jak sprawdzamy"} <= set(teksty)
    assert db.pobierz_ustawienia_zdrowia(a)["przejrzane"] == date.today().isoformat(), "otwarcie = przegląd"
    assert len(przyciski(widok, "To nie błąd")) == 4
    assert {"Otwórz wpis", "Scal", "Uzupełnij", "Usuń", "Odszukaj pliki"} <= {
        b.content for b in pomoce.kontrolki(widok, ft.TextButton)}

    (otworz,) = przyciski(widok, "Otwórz wpis")[:1]
    otworz.on_click(None)
    assert page.route == f"/tankowanie/edytuj/{t}"

    przyciski(widok, "To nie błąd")[0].on_click(None)
    assert db.zdrowie_danych(a)["razem"] == 3 and "To nie błąd (1)" in pomoce.napisy(widok)
    przyciski(widok, "Przywróć")[0].on_click(None)
    assert db.zdrowie_danych(a)["razem"] == 4 and not przyciski(widok, "Przywróć")

    przyciski(widok, "Odszukaj pliki")[0].on_click(None)
    assert komunikaty[-1] == "Żadnego z brakujących plików nie ma na tym telefonie."
    przyciski(widok, "Usuń")[0].on_click(None)
    assert not pozycje(a, "pliki") and not przyciski(widok, "Usuń") and "3 do sprawdzenia" in pomoce.napisy(widok)
    tekst, wynik = komunikaty[-1]
    assert tekst == "Usunięto z wpisów 1 martwy plik." and wynik["w_koszu"]


def test_scal_i_oznacz_z_ekranu(baza, monkeypatch, komunikaty):
    a, _t = _auto_z_problemami()
    zadanie = wstaw("zadania", auto_id=a, nazwa="Alternator")
    wstaw("historia", zadanie_id=zadanie, data=dzien(30), przebieg=100000, cena=900.0)
    widok, _strona = ekran(a)
    monkeypatch.setattr(utils.zdrowie_danych, "potwierdz", lambda page, tytul, tresc, wykonaj, **k: wykonaj())
    przyciski(widok, "Scal")[0].on_click(None)
    assert not pozycje(a, "nazwy") and komunikaty[-1] == "Scalono 1 wariant w „Filtr oleju”."
    assert not przyciski(widok, "Scal")

    otwarte = []
    monkeypatch.setattr(utils, "pokaz_oznaczanie_napraw", lambda page, auto_id, po_zamknieciu=None: otwarte.append(auto_id))
    przyciski(widok, "Oznacz")[0].on_click(None)
    assert otwarte == [a]


def test_ekran_przy_podgladzie_czystym_aucie_i_bez_pojazdu(baza):
    a, _t = _auto_z_problemami()
    with db.polacz_baze() as conn:
        conn.execute("UPDATE samochody SET rola_wspoldzielenia=? WHERE id=?", (db.ROLA_PODGLAD, a))
    widok, _strona = ekran(a)
    napisy = {b.content for b in pomoce.kontrolki(widok, ft.TextButton)}
    assert "To nie błąd" in napisy and not napisy & {"Otwórz wpis", "Scal", "Usuń", "Odszukaj pliki", "Uzupełnij"}

    czysty, _strona_czystego = ekran(auto("Czyste"), "Czyste")
    assert "Dane bez zastrzeżeń" in pomoce.napisy(czysty)
    pusty, _strona_pustego = ekran(None, "Brak pojazdów")
    assert "Brak wybranego pojazdu" in pomoce.napisy(pusty)


def test_kafelek_kokpitu_i_karta_w_ustawieniach(baza):
    a, _t = _auto_z_problemami()
    assert db.METRYKI_KAFELKOW["zdrowie_danych"] == ("zdrowie_danych",) and "zdrowie_danych" in utils.IKONY_KOKPITU
    assert db.metryki_kokpitu(a, ["zdrowie_danych"])["zdrowie_danych"]["razem"] == 4

    stan = pomoce.stan_aplikacji(a, "Octavia")
    stan.zakladka = 0
    db.zapisz_widgety_kokpitu(["zdrowie_danych"], a)
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(), stan)
    kafel = pomoce.napisy(widok.kokpit_kontener)
    assert {"Zdrowie danych", "4 do sprawdzenia"} <= set(kafel)

    strona = pomoce.zbuduj_strone()
    strona.page.on_route_change = lambda e: None
    ustawienia = pomoce.zbuduj_widok(pomoce.klasy_widokow()["UstawieniaView"], strona, stan)
    assert "4 do sprawdzenia" in pomoce.napisy(ustawienia) and "Duplikaty nazw" not in pomoce.napisy(ustawienia)
    (przycisk,) = [b for b in pomoce.kontrolki(ustawienia, ft.OutlinedButton) if b.content == "Otwórz Zdrowie danych"]
    przycisk.on_click(None)
    assert strona.page.route == "/zdrowie-danych"


def test_odnosniki_z_kondycji_i_historii_przebiegu(baza, monkeypatch):
    a = auto()
    odczyt(a, 60, 100000)
    odczyt(a, 30, 101000)
    odczyt(a, 1, 100500)
    otwarte = []
    monkeypatch.setattr(utils.pojazd, "otworz_dno", lambda page, bs: otwarte.append(bs))
    strona = pomoce.zbuduj_strone()
    strona.page.on_route_change = lambda e: None
    utils.pokaz_panel_kondycji(strona.page, pomoce.stan_aplikacji(a, "Octavia"))
    (odnosnik,) = [k for k in pomoce.kontrolki(otwarte[0], ft.Container)
                   if k.on_click and "Zdrowie danych — 1 do sprawdzenia" in pomoce.napisy(k)]
    monkeypatch.setattr(utils.pojazd, "zamknij_dno", lambda page, bs: None)
    odnosnik.on_click(None)
    assert strona.page.route == "/zdrowie-danych"

    from views.przebieg_view import OdczytyPrzebieguView

    strona = pomoce.zbuduj_strone()
    strona.page.on_route_change = lambda e: None
    widok = OdczytyPrzebieguView(strona.page, pomoce.stan_aplikacji(a, "Octavia"))
    (baner,) = [k for k in pomoce.kontrolki(widok, ft.Container)
                if k.on_click and any("w Zdrowiu danych" in n for n in pomoce.napisy(k))]
    baner.on_click(None)
    assert strona.page.route == "/zdrowie-danych"


def test_router_szuflada_i_co_nowego(baza, monkeypatch):
    monkeypatch.setattr(ft, "run", lambda *args, **kwargs: None)
    import log
    import main

    monkeypatch.setattr(log, "wlacz", lambda: True)
    monkeypatch.setitem(utils.wyglad._OSTATNI_MOTYW, "nazwa", utils.wyglad._OSTATNI_MOTYW["nazwa"])
    a = auto()
    db.zapisz_widziana_wersje(db.WERSJA_APLIKACJI)
    strona = pomoce.zbuduj_strone()
    page = strona.page
    monkeypatch.setattr(type(page), "run_task", lambda self, *args, **kwargs: None)
    main.main(page)
    utils.przejdz(page, "/zdrowie-danych")
    assert [type(w).__name__ for w in page.views] == ["MainView", "ZdrowieDanychView"]
    assert main._cel_trasy(["zdrowie-danych"])[0] is False and a

    assert [e["id"] for e in utils.znajdz_ekrany("zdrowie danych")][:1] == ["zdrowie-danych"]
    assert "zdrowie-danych" in [e["id"] for e in utils.znajdz_ekrany("martwe pliki")]
    (wydanie,) = [w for w in db.NOWOSCI if w["wersja"] == "2026.10.20.2"]
    assert wydanie["pozycje"][0]["ekran"] == "zdrowie-danych"
