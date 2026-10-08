"""Historia cen części, sklep i link przy pozycji magazynu (M-15).

Pozycja magazynu pamięta jeden zakup; dziennik `ceny_czesci` pamięta wszystkie.
Najłatwiej to zepsuć na granicach: poprawka ceny nie może dokładać punktu,
nowa data zakupu nie może kasować poprzedniego, a cena wpisana przed
aktualizacją (bez wiersza w dzienniku) nie może zniknąć przy pierwszej zmianie,
usunięciu ani scaleniu pozycji. Do tego dochodzą chmura i kosz — nowa tabela
i dwie nowe kolumny tabeli, która w chmurze już leży.
"""

import sqlite3
from datetime import date, datetime

import flet as ft
import pytest

import audyty
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
KONFIG_MAGAZYNU = next(k for k in sync.KONFIGURACJA_SYNC if k["tabela"] == "magazyn_czesci")
KONFIG_CEN = next(k for k in sync.KONFIGURACJA_SYNC if k["tabela"] == "ceny_czesci")
DZIS = datetime.now().strftime("%d.%m.%Y")


# ============================================================================
#  POMOCE
# ============================================================================

def jeden(sql, parametry=()):
    with db.polacz_baze() as conn:
        wiersz = conn.execute(sql, parametry).fetchone()
    return wiersz[0] if wiersz and len(wiersz) == 1 else wiersz


def pojazd(nazwa="Cenowy"):
    with db.polacz_baze() as conn:
        kursor = conn.execute(
            "INSERT INTO samochody (nazwa, typ_paliwa, status, rola_wspoldzielenia) VALUES (?,?,?,?)",
            (nazwa, "Benzyna", db.STATUS_POJAZDU_AKTYWNY, db.ROLA_WLASCICIEL),
        )
        return kursor.lastrowid


def pozycja(auto, nazwa="Filtr oleju", ilosc=1.0, cena_j=40.0, data="", sklep=None, link=None, jednostka="szt"):
    """Pozycja wpisana „przed aktualizacją” — prosto do tabeli, bez dziennika."""
    with db.polacz_baze() as conn:
        kursor = conn.execute(
            "INSERT INTO magazyn_czesci (auto_id, nazwa, kategoria, ilosc, jednostka, cena, cena_jednostkowa, "
            "data_zakupu, sklep, link) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (auto, nazwa, "Filtry", ilosc, jednostka, None if cena_j is None else round(cena_j * ilosc, 2),
             cena_j, data, sklep, link),
        )
        return kursor.lastrowid


def zakup(auto, nazwa, data, cena, jednostka="szt", ilosc=None, sklep=None):
    with db.polacz_baze() as conn:
        kursor = conn.execute(
            "INSERT INTO ceny_czesci (auto_id, nazwa, data, data_iso, cena_jednostkowa, jednostka, ilosc, sklep) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (auto, nazwa, data, na_iso(data), cena, jednostka, ilosc, sklep),
        )
        return kursor.lastrowid


def dziennik(auto):
    """Wiersze dziennika od najstarszego: (nazwa, data, cena, ilosc, sklep)."""
    with db.polacz_baze() as conn:
        return conn.execute(
            "SELECT nazwa, data, cena_jednostkowa, ilosc, sklep FROM ceny_czesci WHERE auto_id=? "
            "ORDER BY data_iso IS NOT NULL, data_iso, id", (auto,)
        ).fetchall()


def punkty(auto, nazwa="Filtr oleju"):
    return db.historia_cen_czesci(auto, nazwa)


def ceny(auto, nazwa="Filtr oleju"):
    return [(p["data"], p["cena"], p["obecna"]) for p in punkty(auto, nazwa)]


def teksty(korzen):
    """Wszystkie napisy z ZBUDOWANEGO drzewa kontrolek, razem z etykietami pól."""
    wynik, do_odwiedzenia = [], [korzen]
    while do_odwiedzenia:
        kontrolka = do_odwiedzenia.pop()
        # Napis przycisku siedzi we Flecie 0.86 w `content`.
        for pole in ("value", "label", "tooltip", "content"):
            wartosc = getattr(kontrolka, pole, None)
            if isinstance(wartosc, str) and wartosc.strip():
                wynik.append(wartosc)
        do_odwiedzenia.extend(dziecko for _, dziecko in audyty._dzieci(kontrolka))
        for pole in ("appbar", "floating_action_button", "title"):
            dziecko = getattr(kontrolka, pole, None)
            if isinstance(dziecko, ft.Control):
                do_odwiedzenia.append(dziecko)
        if isinstance(getattr(kontrolka, "actions", None), list):
            do_odwiedzenia.extend(a for a in kontrolka.actions if isinstance(a, ft.Control))
    return wynik


def kontrolki(korzen, typ):
    """Kontrolki danego typu w kolejności, w jakiej stoją na ekranie."""
    wynik, do_odwiedzenia = [], [korzen]
    while do_odwiedzenia:
        kontrolka = do_odwiedzenia.pop()
        if isinstance(kontrolka, typ):
            wynik.append(kontrolka)
        do_odwiedzenia.extend(reversed([dziecko for _, dziecko in audyty._dzieci(kontrolka)]))
    return wynik


def zbuduj(klasa, stan, *argumenty):
    strona = pomoce.zbuduj_strone()
    widok = klasa(strona.page, stan, *argumenty)
    widok._strona_testowa = strona
    return widok


def formularz(auto, czesc_id=None):
    from views.garage_view import FormularzCzesciView
    return zbuduj(FormularzCzesciView, pomoce.stan_aplikacji(auto, "Cenowy"), czesc_id)


def podmien(monkeypatch, nazwa, wartosc):
    """`from .modul import x` kopiuje wiązanie — podmieniamy w pakiecie i w module."""
    for modul in (utils, utils.ceny_czesci):
        monkeypatch.setattr(modul, nazwa, wartosc, raising=False)


@pytest.fixture
def bez_nawigacji(monkeypatch):
    komunikaty = []
    podmien(monkeypatch, "przejdz", lambda page, trasa: None)
    podmien(monkeypatch, "pokaz_komunikat", lambda page, tekst, *a, **k: komunikaty.append(tekst))
    podmien(monkeypatch, "wypchnij_w_tle", lambda *a, **k: None)
    return komunikaty


# ============================================================================
#  1. DZIENNIK ZAKUPÓW Z FORMULARZA POZYCJI
# ============================================================================

def test_nowa_pozycja_zapisuje_zakup_ze_sklepem_i_linkiem(baza, bez_nawigacji):
    auto = pojazd()
    pozycja(auto, "Olej 5W-30", sklep="Inter Cars", jednostka="l")
    widok = formularz(auto)
    assert widok.e_data.value == DZIS, "nowa pozycja to zwykle zakup sprzed chwili"

    widok.e_nazwa.value = "Filtr oleju"
    widok.e_ilosc.value = "2"
    widok.e_cena.value = "80"
    widok.e_sklep.value = "inter  cars"
    widok.e_link.value = "intercars.pl/filtr-w712"
    widok.zapisz(None)

    assert jeden("SELECT cena_jednostkowa, sklep, link FROM magazyn_czesci WHERE nazwa='Filtr oleju'") == (
        40.0, "Inter Cars", "https://intercars.pl/filtr-w712")
    assert dziennik(auto) == [("Filtr oleju", DZIS, 40.0, 2.0, "Inter Cars")]


def test_ta_sama_data_poprawia_a_nowa_data_dopisuje_zakup(baza, bez_nawigacji):
    auto = pojazd()
    widok = formularz(auto)
    widok.e_nazwa.value = "Filtr oleju"
    widok.e_ilosc.value = "2"
    widok.e_cena_jedn.value = "40"
    widok.e_data.value = "12.03.2025"
    widok.zapisz(None)
    czesc = jeden("SELECT id FROM magazyn_czesci WHERE auto_id=?", (auto,))

    # Literówka w cenie: ta sama data zakupu to ten sam zakup.
    widok = formularz(auto, czesc)
    widok.e_cena_jedn.value = "42"
    widok.zapisz(None)
    assert dziennik(auto) == [("Filtr oleju", "12.03.2025", 42.0, 2.0, None)]

    # Dokupione przez edycję: nowa data, stan 2 → 3, nowa cena.
    widok = formularz(auto, czesc)
    widok.e_data.value = "20.09.2026"
    widok.e_ilosc.value = "3"
    widok.e_cena_jedn.value = "45"
    widok.zapisz(None)
    assert dziennik(auto) == [
        ("Filtr oleju", "12.03.2025", 42.0, 2.0, None),
        ("Filtr oleju", "20.09.2026", 45.0, 1.0, None),
    ], "poprzedni zakup zostaje, a kupiono tyle, o ile urósł stan"
    assert ceny(auto) == [("12.03.2025", 42.0, False), ("20.09.2026", 45.0, True)]


def test_cena_sprzed_aktualizacji_trafia_do_historii_przy_pierwszej_zmianie(baza, bez_nawigacji):
    auto = pojazd()
    czesc = pozycja(auto, ilosc=1.0, cena_j=30.0, data="05.01.2024")
    assert dziennik(auto) == []
    assert [(p["id"], p["cena"], p["obecna"]) for p in punkty(auto)] == [(None, 30.0, True)], \
        "bieżąca cena pozycji liczy się w locie, bez przepisywania do dziennika"

    widok = formularz(auto, czesc)
    widok.e_data.value = "01.09.2026"
    widok.e_ilosc.value = "2"
    widok.e_cena_jedn.value = "45"
    widok.zapisz(None)

    assert dziennik(auto) == [
        ("Filtr oleju", "05.01.2024", 30.0, None, None),
        ("Filtr oleju", "01.09.2026", 45.0, 1.0, None),
    ]


def test_skasowana_cena_tez_zostaje_w_historii(baza, bez_nawigacji):
    auto = pojazd()
    czesc = pozycja(auto, cena_j=30.0, data="05.01.2024")
    widok = formularz(auto, czesc)
    widok.e_cena.value = ""
    widok.e_cena_jedn.value = ""
    widok.zapisz(None)

    assert dziennik(auto) == [("Filtr oleju", "05.01.2024", 30.0, None, None)]
    assert ceny(auto) == [("05.01.2024", 30.0, False)]


def test_ceny_bez_daty_stara_na_poczatku_biezaca_na_koncu(baza, bez_nawigacji):
    auto = pojazd()
    czesc = pozycja(auto, cena_j=25.0, data="")
    widok = formularz(auto, czesc)
    widok.e_data.value = "01.09.2026"
    widok.e_cena_jedn.value = "30"
    widok.zapisz(None)
    assert ceny(auto) == [("", 25.0, False), ("01.09.2026", 30.0, True)], "stara cena bez daty to „kiedyś”"

    auto2 = pojazd("Drugi")
    pozycja(auto2, cena_j=50.0, data="")
    zakup(auto2, "Filtr oleju", "12.01.2025", 40.0)
    assert ceny(auto2) == [("12.01.2025", 40.0, False), ("", 50.0, True)], "bieżąca cena bez daty to „teraz”"
    zmiana = db.zmiana_ceny(punkty(auto2))
    assert zmiana["proc"] == 25.0 and zmiana["od"]["data"] == "12.01.2025"


def test_zmiana_nazwy_zabiera_historie_chyba_ze_stara_nazwa_zostaje(baza, bez_nawigacji):
    auto = pojazd()
    czesc = pozycja(auto, cena_j=45.0, data="01.09.2026")
    zakup(auto, "filtr oleju", "12.01.2024", 30.0)
    widok = formularz(auto, czesc)
    widok.e_nazwa.value = "Filtr oleju Mann W712"
    widok.zapisz(None)
    assert [n for n, *_ in dziennik(auto)] == ["Filtr oleju Mann W712", "Filtr oleju Mann W712"]
    assert punkty(auto, "Filtr oleju") == []
    assert [p["cena"] for p in punkty(auto, "filtr oleju mann w712")] == [30.0, 45.0]

    auto2 = pojazd("Drugi")
    czesc2 = pozycja(auto2, cena_j=45.0, data="01.09.2026")
    pozycja(auto2, "Filtr oleju", ilosc=0.0, cena_j=None)
    zakup(auto2, "Filtr oleju", "12.01.2024", 30.0)
    widok = formularz(auto2, czesc2)
    widok.e_nazwa.value = "Filtr powietrza"
    widok.zapisz(None)
    assert ("Filtr oleju", "12.01.2024", 30.0, None, None) in dziennik(auto2), \
        "historia zostaje przy pozycji, która wciąż nosi starą nazwę"


# ============================================================================
#  2. „KUPIŁEM PONOWNIE”, „DOPISZ CENĘ”, USUWANIE I SCALANIE
# ============================================================================

def test_kup_ponownie_dolicza_stan_i_bierze_ostatnia_cene(baza):
    auto = pojazd()
    pozycja(auto, "Akumulator", sklep="Inter Cars", cena_j=None)
    czesc = pozycja(auto, "Olej 5W-30", ilosc=1.0, cena_j=30.0, data="01.03.2026", sklep="Allegro", jednostka="l")

    wynik = db.kup_ponownie(czesc, 5, 35, "inter cars", "02.10.2026")

    assert wynik == {"auto_id": auto, "stan": 6.0, "dodano": 5.0}
    assert jeden("SELECT ilosc, cena, cena_jednostkowa, data_zakupu, sklep FROM magazyn_czesci WHERE id=?", (czesc,)) == (
        6.0, 175.0, 35.0, "02.10.2026", "Inter Cars"), "ostatnia cena, nie średnia ważona z tym, co zostało"
    assert dziennik(auto) == [
        ("Olej 5W-30", "01.03.2026", 30.0, None, "Allegro"),
        ("Olej 5W-30", "02.10.2026", 35.0, 5.0, "Inter Cars"),
    ]

    # Drugi zakup tego samego dnia: jeden punkt, ilość razem, sklep bez zmian.
    db.kup_ponownie(czesc, 1, 36, None, "02.10.2026")
    assert jeden("SELECT ilosc, cena_jednostkowa, sklep FROM magazyn_czesci WHERE id=?", (czesc,)) == (7.0, 36.0, "Inter Cars")
    assert dziennik(auto)[-1] == ("Olej 5W-30", "02.10.2026", 36.0, 6.0, "Inter Cars")
    assert len(dziennik(auto)) == 2


def test_kup_ponownie_odmawia_zlych_danych_i_podgladowi(baza):
    auto = pojazd()
    czesc = pozycja(auto, cena_j=30.0, data="01.03.2026")
    assert db.kup_ponownie(czesc, 0, 35) is None
    assert db.kup_ponownie(czesc, 1, 0) is None
    assert db.kup_ponownie(None, 1, 35) is None
    db.ustaw_role_pojazdu(auto, db.ROLA_PODGLAD)
    assert db.kup_ponownie(czesc, 1, 35) is None
    assert jeden("SELECT ilosc FROM magazyn_czesci WHERE id=?", (czesc,)) == 1.0
    assert dziennik(auto) == []


def test_dopisana_cena_wymaga_daty_a_ten_sam_dzien_ja_poprawia(baza):
    auto = pojazd()
    pozycja(auto, "Akumulator", sklep="Allegro", cena_j=None)
    assert db.dopisz_cene_czesci(auto, "Filtr oleju", "", 30) is None
    assert db.dopisz_cene_czesci(auto, "Filtr oleju", "12.01.2024", 0) is None

    pierwszy = db.dopisz_cene_czesci(auto, "Filtr oleju", "12.01.2024", 30, "szt", "allegro", 2)
    drugi = db.dopisz_cene_czesci(auto, "filtr oleju", "12.01.2024", 31)
    assert pierwszy == drugi
    assert dziennik(auto) == [("filtr oleju", "12.01.2024", 31.0, 2.0, None)]

    db.ustaw_role_pojazdu(auto, db.ROLA_PODGLAD)
    assert db.dopisz_cene_czesci(auto, "Filtr oleju", "12.01.2025", 33) is None


def test_usuniecie_zakupu_z_cofnieciem(baza):
    auto = pojazd()
    zakup_id = zakup(auto, "Filtr oleju", "12.01.2024", 30.0)
    wynik = db.usun_wiele_z_cofnieciem("ceny_czesci", [zakup_id])
    assert dziennik(auto) == []
    wynik["cofnij"]()
    assert dziennik(auto) == [("Filtr oleju", "12.01.2024", 30.0, None, None)]


def test_usunieta_pozycja_zostawia_swoja_cene(baza):
    auto = pojazd()
    czesc = pozycja(auto, cena_j=30.0, data="05.01.2024")
    wynik = db.usun_czesc_magazynu_z_cofnieciem(czesc)

    assert jeden("SELECT COUNT(*) FROM magazyn_czesci WHERE auto_id=?", (auto,)) == 0
    assert ceny(auto) == [("05.01.2024", 30.0, False)]

    wynik["cofnij"]()
    assert ceny(auto) == [("05.01.2024", 30.0, True)], "przywrócona pozycja przykrywa ten sam zakup, bez dubla"
    assert [p["id"] is not None for p in punkty(auto)] == [True]


def test_scalanie_duplikatow_zachowuje_oba_zakupy_i_sklep(baza):
    auto = pojazd()
    docelowa = pozycja(auto, "Filtr oleju", ilosc=1.0, cena_j=30.0, data="05.01.2024")
    duplikat = pozycja(auto, "filtr oleju ", ilosc=1.0, cena_j=36.0, data="01.06.2025",
                       sklep="Allegro", link="https://allegro.pl/filtr")

    assert db.scal_duplikaty_nazw(auto, "magazyn_czesci", docelowa, [duplikat]) == 1

    assert [(d, c) for _, d, c, *_ in dziennik(auto)] == [("05.01.2024", 30.0), ("01.06.2025", 36.0)]
    assert jeden("SELECT sklep, link, cena_jednostkowa FROM magazyn_czesci WHERE id=?", (docelowa,)) == (
        "Allegro", "https://allegro.pl/filtr", 33.0)


# ============================================================================
#  3. RACHUNEK: ZMIANA, NAJTAŃSZY, POPRZEDNIE, PODWYŻKI, OBSERWACJA
# ============================================================================

def _punkt(data, cena, jednostka="szt", obecna=False, magazyn_id=None, sklep=None, id_=None):
    return {"id": id_, "ids": [id_] if id_ else [], "nazwa": "Filtr", "data": data, "data_iso": na_iso(data),
            "cena": cena, "jednostka": jednostka, "ilosc": None, "sklep": sklep,
            "obecna": obecna, "magazyn_id": magazyn_id}


def test_zmiana_ceny_najtanszy_i_poprzednie():
    lista = [_punkt("12.01.2024", 30.0, sklep="Allegro"), _punkt("03.03.2025", 38.0, "l"),
             _punkt("05.05.2025", 28.0, sklep="Auto Partner"), _punkt("01.09.2026", 45.0, obecna=True, magazyn_id=7)]

    zmiana = db.zmiana_ceny(lista)
    assert (zmiana["od"]["data"], zmiana["do"]["data"], zmiana["proc"]) == ("12.01.2024", "01.09.2026", 50.0)
    assert db.najtanszy_zakup(lista)["sklep"] == "Auto Partner", "porównuje tylko tę samą jednostkę"
    assert [p["data"] for p in db.poprzednie_zakupy(lista, 7)] == ["05.05.2025", "03.03.2025", "12.01.2024"]
    assert [p["data"] for p in db.poprzednie_zakupy(lista)][0] == "01.09.2026", "bez pozycji — wszystkie"
    assert db.zmiana_ceny(lista[:1]) is None
    assert db.zmiana_ceny([_punkt("", 30.0), _punkt("01.09.2026", 45.0)]) is None, "stara cena bez daty nie ma „kiedy”"
    assert db.najtanszy_zakup(lista[3:]) is None


@pytest.mark.parametrize("od, do, oczekiwany", [
    ("12.01.2024", "01.09.2026", "ponad 2 lata wcześniej"),
    ("12.01.2024", "12.01.2026", "2 lata wcześniej"),
    ("12.01.2025", "12.01.2026", "rok wcześniej"),
    ("12.01.2025", "20.06.2026", "ponad rok wcześniej"),
    ("12.01.2026", "12.04.2026", "3 miesiące wcześniej"),
    ("12.01.2026", "15.02.2026", "miesiąc wcześniej"),
    ("12.01.2026", "20.01.2026", "8 dni wcześniej"),
    ("12.01.2026", "13.01.2026", "dzień wcześniej"),
])
def test_odstep_zakupow_slownie(od, do, oczekiwany):
    assert db.odstep_zakupow(_punkt(od, 1.0), _punkt(do, 1.0)) == oczekiwany


def test_obserwacja_czesci_drozeja(baza):
    auto = pojazd()
    W = utils.symbol_waluty()
    pozycja(auto, "Filtr oleju", cena_j=45.0, data="01.09.2026")
    zakup(auto, "Filtr oleju", "12.01.2024", 30.0)
    pozycja(auto, "Olej 5W-30", cena_j=36.6, data="01.09.2026", jednostka="l")
    zakup(auto, "Olej 5W-30", "01.09.2025", 30.0, "l")
    pozycja(auto, "Żarówka H7", cena_j=21.0, data="01.09.2026")
    zakup(auto, "Żarówka H7", "01.09.2025", 20.0)
    zakup(auto, "Pióro wycieraczki", "01.09.2024", 30.0)
    zakup(auto, "Pióro wycieraczki", "01.09.2026", 60.0)

    podwyzki = db.podwyzki_cen_czesci(auto)
    assert [(p["nazwa"], p["proc"]) for p in podwyzki] == [("Filtr oleju", 50.0), ("Olej 5W-30", 22.0)], \
        "+5% to nie podwyżka, a części, której już nie ma w magazynie, nie ma po co liczyć"

    obserwacja = next(o for o in db.obserwacje_analityczne(auto) if o["klucz"] == "czesci_drozeja")
    assert obserwacja["tekst"] == (
        f"„Filtr oleju”: ostatnio 45,00 {W}/szt — o 50% więcej niż przy zakupie 12.01.2024 "
        f"(30,00 {W}/szt), ponad 2 lata wcześniej. Podrożały też: „Olej 5W-30” (+22%).")
    assert (obserwacja["tytul"], obserwacja["trasa"], obserwacja["ikona"]) == ("Części drożeją", "/magazyn", "czesci")


def test_bez_podwyzki_bez_obserwacji(baza):
    auto = pojazd()
    pozycja(auto, cena_j=31.0, data="01.09.2026")
    zakup(auto, "Filtr oleju", "12.01.2024", 30.0)
    assert all(o["klucz"] != "czesci_drozeja" for o in db.obserwacje_analityczne(auto))


# ============================================================================
#  4. SKLEP I LINK
# ============================================================================

def test_link_normalizacja_walidacja_i_domena():
    assert db.normalizuj_link("  allegro.pl/oferta/123 ") == "https://allegro.pl/oferta/123"
    assert db.normalizuj_link("http://x.pl") == "http://x.pl"
    assert db.normalizuj_link("   ") is None
    assert db.blad_linku("") is None
    assert db.blad_linku("intercars.com.pl/filtr") is None
    assert db.blad_linku("filtr oleju") == "Adres strony nie może zawierać spacji"
    assert db.blad_linku("filtr") == "To nie wygląda na adres strony"
    assert db.blad_linku("ftp://pliki.pl/x") == "Adres strony zaczyna się od http:// albo https://"
    assert db.blad_linku("https://[nawias") == "To nie wygląda na adres strony"
    assert db.domena_linku("https://www.intercars.com.pl/x?y=1") == "intercars.com.pl"


def test_sklepy_od_najczestszego_i_dopasowanie_pisowni(baza):
    auto = pojazd()
    pozycja(auto, "A", sklep="Inter Cars", cena_j=None)
    pozycja(auto, "B", sklep="inter cars", cena_j=None)
    pozycja(auto, "C", sklep="Allegro", cena_j=None)
    zakup(auto, "D", "01.01.2025", 10.0, sklep="Inter Cars")
    zakup(auto, "E", "01.01.2025", 10.0, sklep="Auto Partner")
    zakup(auto, "F", "01.01.2025", 10.0, sklep="Auto Partner")

    assert db.sklepy_czesci(auto) == ["Inter Cars", "Auto Partner", "Allegro"]
    assert db.dopasuj_sklep(auto, " INTER  cars ") == "Inter Cars"
    assert db.dopasuj_sklep(auto, "Nowy sklep") == "Nowy sklep"
    assert db.dopasuj_sklep(auto, "  ") is None


def test_wyszukiwarka_znajduje_czesc_po_sklepie(baza):
    auto = pojazd()
    pozycja(auto, "Filtr oleju", sklep="Inter Cars")
    pozycja(auto, "Olej 5W-30", sklep="Allegro", jednostka="l")

    assert [w["tytul"] for w in db.globalne_wyszukiwanie(auto, "inter cars")] == ["Filtr oleju"]
    assert [w["tytul"] for w in db.globalne_wyszukiwanie(auto, "sklep:allegro")] == ["Olej 5W-30"]


def test_eksport_magazynu_ma_sklep_i_link(baza):
    auto = pojazd()
    pozycja(auto, "Filtr oleju", sklep="Inter Cars", link="https://intercars.pl/f")
    naglowki, wiersze = db.pobierz_dane_eksportu(auto, ["magazyn_czesci"])["magazyn_czesci"]
    assert naglowki[-2:] == ["Sklep", "Link"]
    assert wiersze[0][-2:] == ["Inter Cars", "https://intercars.pl/f"]


# ============================================================================
#  5. EKRANY: KARTA, MENU, ARKUSZ, OKNA, FORMULARZ
# ============================================================================

@pytest.fixture
def magazyn_z_historia(baza):
    auto = pojazd()
    czesc = pozycja(auto, "Filtr oleju", ilosc=2.0, cena_j=45.0, data="01.09.2026",
                    sklep="Inter Cars", link="https://intercars.pl/filtr")
    zakup(auto, "Filtr oleju", "12.01.2024", 30.0, ilosc=2.0)
    zakup(auto, "Filtr oleju", "03.03.2025", 38.0, ilosc=1.0, sklep="Allegro")
    return {"auto_id": auto, "czesc": czesc,
            "dane": {"id": czesc, "nazwa": "Filtr oleju", "jednostka": "szt",
                     "sklep": "Inter Cars", "link": "https://intercars.pl/filtr"}}


def test_karta_pozycji_mowi_ile_czesc_kosztowala_wczesniej(magazyn_z_historia, bez_nawigacji):
    from views.garage_view import MagazynView

    W = utils.symbol_waluty()
    stan = pomoce.stan_aplikacji(magazyn_z_historia["auto_id"], "Cenowy")
    stan.magazyn_zakladka = 1
    widok = zbuduj(MagazynView, stan)
    napisy = teksty(widok)

    assert f"Wcześniej: 38,00 {W} (03.2025) · 30,00 {W} (01.2024)" in napisy
    assert "+50%" in napisy and "od 01.2024" in napisy
    assert "Inter Cars" in napisy and "Otwórz stronę produktu" in napisy
    assert audyty.znajdz_expand_bez_ograniczenia(widok) == []
    assert audyty.znajdz_rozciagliwe_chipy(widok) == []
    assert audyty.znajdz_plaskie_powierzchnie(widok, widok._strona_testowa.page) == []
    assert audyty.znajdz_pogrubienia_na_drugim_planie(widok) == []


def test_menu_pozycji_historia_cen_kupilem_ponownie_i_link(magazyn_z_historia, bez_nawigacji, monkeypatch):
    from views.garage_view import MagazynView

    d = magazyn_z_historia
    stan = pomoce.stan_aplikacji(d["auto_id"], "Cenowy")
    stan.magazyn_zakladka = 1
    widok = zbuduj(MagazynView, stan)
    menu = []
    monkeypatch.setattr(utils, "pokaz_menu_kontekstowe", lambda page, tytul, pozycje: menu.append(pozycje))

    widok._pokaz_menu_czesci(d["czesc"], "Filtr oleju", None, "szt", False, "Inter Cars", d["dane"]["link"])
    assert [p["tekst"] for p in menu[-1]][:5] == [
        "Dodaj plik (zdjęcie, PDF)", "Kupiłem ponownie", "Historia cen", "Otwórz stronę produktu", "Kopiuj link"]

    db.ustaw_role_pojazdu(d["auto_id"], db.ROLA_PODGLAD)
    widok._pokaz_menu_czesci(d["czesc"], "Filtr oleju", None, "szt", False, "Inter Cars", d["dane"]["link"])
    teksty_podgladu = [p["tekst"] for p in menu[-1]]
    assert "Kupiłem ponownie" not in teksty_podgladu
    assert {"Historia cen", "Otwórz stronę produktu", "Kopiuj link"} <= set(teksty_podgladu)


def test_arkusz_historii_cen_z_usuwaniem_i_cofnieciem(magazyn_z_historia, bez_nawigacji, monkeypatch):
    d = magazyn_z_historia
    W = utils.symbol_waluty()
    arkusze, cofniecia = [], []
    podmien(monkeypatch, "otworz_dno", lambda page, arkusz: arkusze.append(arkusz))
    podmien(monkeypatch, "zamknij_dno", lambda page, arkusz: None)
    podmien(monkeypatch, "pokaz_komunikat_cofnij", lambda page, tekst, wynik, **k: cofniecia.append((tekst, wynik)))
    strona = pomoce.zbuduj_strone()
    odswiezone = []

    utils.pokaz_historie_cen(strona.page, d["auto_id"], d["dane"], po_zmianie=lambda: odswiezone.append(1))
    napisy = teksty(arkusze[-1])

    assert "Historia cen: Filtr oleju" in napisy
    assert "3 zakupy · od 01.2024" in napisy
    assert "Cena teraz" in napisy and "cena teraz" in napisy
    assert f"45,00 {W}/szt" in napisy and "+18%" in napisy and "+27%" in napisy
    assert f"Najtaniej: 30,00 {W}/szt (12.01.2024)" in napisy
    assert f"1 szt za 38,00 {W} · Allegro" in napisy
    assert "Dopisz cenę" in napisy and "Strona produktu" in napisy
    assert audyty.znajdz_pogrubienia_na_drugim_planie(arkusze[-1]) == []
    assert audyty.znajdz_expand_bez_ograniczenia(arkusze[-1]) == []

    kosze = [b for b in kontrolki(arkusze[-1], ft.IconButton) if b.tooltip == "Usuń tę cenę z historii"]
    assert len(kosze) == 2, "bieżącą cenę poprawia się w edycji pozycji, nie tutaj"
    kosze[0].on_click(None)
    assert len(dziennik(d["auto_id"])) == 1 and odswiezone == [1]
    tekst, wynik = cofniecia[-1]
    assert tekst == "Usunięto cenę z 03.03.2025."
    wynik["cofnij"]()
    assert len(dziennik(d["auto_id"])) == 2

    db.ustaw_role_pojazdu(d["auto_id"], db.ROLA_PODGLAD)
    utils.pokaz_historie_cen(strona.page, d["auto_id"], d["dane"])
    assert [b for b in kontrolki(arkusze[-1], ft.IconButton) if b.tooltip == "Usuń tę cenę z historii"] == []
    assert "Dopisz cenę" not in teksty(arkusze[-1])


def test_okno_kupilem_ponownie(magazyn_z_historia, bez_nawigacji, monkeypatch):
    d = magazyn_z_historia
    W = utils.symbol_waluty()
    podmien(monkeypatch, "zamknij_dialog", lambda page, dlg: None)
    strona = pomoce.zbuduj_strone()
    okno = utils.OknoKupilemPonownie(strona.page, d["auto_id"], d["dane"])
    napisy = teksty(okno.dlg)

    assert (f"Ostatnio 45,00 {W}/szt · 01.09.2026 · Inter Cars · najtaniej 30,00 {W}/szt (01.2024)") in napisy
    assert okno.e_ilosc.value == "1", "domyślnie tyle, ile kupiono ostatnim razem"
    assert okno.sklep.value == "Inter Cars" and okno.e_data.value == DZIS
    assert "Sprawdź cenę na stronie produktu" in napisy
    assert audyty.znajdz_expand_bez_ograniczenia(okno.dlg.content) == []

    okno.e_ilosc.value = ""
    okno.zapisz(None)
    assert utils.blad_kontrolki(okno.e_ilosc) == "Podaj, ile kupiono"

    okno.e_ilosc.value = "2"
    okno.e_koszt.value = "92"
    okno._przelicz("koszt")
    assert okno.e_cena.value == "46"
    okno.zapisz(None)
    assert jeden("SELECT ilosc, cena_jednostkowa, data_zakupu FROM magazyn_czesci WHERE id=?", (d["czesc"],)) == (
        4.0, 46.0, DZIS)
    assert bez_nawigacji[-1] == "Dodano 2 szt — na stanie 4 szt."


def test_okno_dopisania_ceny(magazyn_z_historia, bez_nawigacji, monkeypatch):
    d = magazyn_z_historia
    okna = []
    podmien(monkeypatch, "otworz_dialog", lambda page, dlg: okna.append(dlg))
    podmien(monkeypatch, "zamknij_dialog", lambda page, dlg: None)
    strona = pomoce.zbuduj_strone()
    po_zapisie = []

    dlg = utils.dialog_dopisania_ceny(strona.page, d["auto_id"], "Filtr oleju", "szt", lambda: po_zapisie.append(1))
    pola = [k for k in kontrolki(dlg.content, ft.TextField)]
    data, cena = next(p for p in pola if p.label == "Data zakupu*"), next(p for p in pola if p.label.startswith("Cena za 1 szt"))

    cena.value = "28"
    dlg.actions[1].on_click(None)
    assert utils.blad_kontrolki(data) == "Podaj datę zakupu" and po_zapisie == []

    data.value = "05.05.2023"
    dlg.actions[1].on_click(None)
    assert po_zapisie == [1]
    assert dziennik(d["auto_id"])[0] == ("Filtr oleju", "05.05.2023", 28.0, None, None)


def test_formularz_podpowiada_poprzednia_cene_przy_nazwie(magazyn_z_historia, bez_nawigacji):
    d = magazyn_z_historia
    W = utils.symbol_waluty()

    widok = formularz(d["auto_id"])
    assert widok.t_poprzednio.visible is False
    widok.e_nazwa.value = "  filtr OLEJU"
    widok._pokaz_poprzednie_ceny()
    assert widok.t_poprzednio.visible is True
    assert widok.t_poprzednio.value == (
        f"Ostatnio 45,00 {W}/szt · 01.09.2026 · Inter Cars · najtaniej 30,00 {W}/szt (01.2024)")
    widok.e_nazwa.value = "Żarówka H7"
    widok._pokaz_poprzednie_ceny()
    assert widok.t_poprzednio.visible is False

    # Przy edycji — zakupy SPRZED bieżącego, a pod datą zakupu zasada nowego zakupu.
    widok = formularz(d["auto_id"], d["czesc"])
    assert widok.t_poprzednio.value == f"Ostatnio 38,00 {W}/szt · 03.03.2025 · Allegro · najtaniej 30,00 {W}/szt (01.2024)"
    assert any(n.startswith("Inna data zakupu niż dotąd to nowy zakup") for n in teksty(widok))
    assert (widok.e_sklep.value, widok.e_link.value) == ("Inter Cars", "https://intercars.pl/filtr")
    assert audyty.znajdz_expand_bez_ograniczenia(widok) == []
    assert audyty.znajdz_rozciagliwe_chipy(widok) == []

    widok.e_link.value = "nie link"
    widok.zapisz(None)
    assert utils.blad_kontrolki(widok.e_link) == "Adres strony nie może zawierać spacji"


# ============================================================================
#  6. MIGRACJA, CHMURA, KOSZ
# ============================================================================

def test_migracja_48_niczego_nie_przepisuje_do_dziennika(magazyn):
    probki_baz.zbuduj_baze_w_wersji(db.BAZA_DANYCH, 47, DRABINKA)
    conn = sqlite3.connect(db.BAZA_DANYCH)
    c = conn.cursor()
    c.execute("INSERT INTO samochody (nazwa, typ_paliwa) VALUES ('Stary', 'Benzyna')")
    auto = c.lastrowid
    c.execute("INSERT INTO magazyn_czesci (auto_id, nazwa, ilosc, jednostka, cena, cena_jednostkowa, data_zakupu) "
              "VALUES (?, 'Filtr oleju', 2, 'szt', 60, 30, '05.01.2024')", (auto,))
    conn.commit()
    conn.close()

    db.init_db()

    assert {"sklep", "link"} <= set(pomoce.kolumny("magazyn_czesci"))
    assert jeden("SELECT sklep, link FROM magazyn_czesci") == (None, None)
    assert jeden("SELECT COUNT(*) FROM ceny_czesci") == 0, \
        "dwa telefony wpisałyby te same zakupy dwa razy — ceny pozycji liczą się w locie"
    assert ceny(auto) == [("05.01.2024", 30.0, True)]


def test_sklep_i_link_jada_do_chmury_jako_dopisane_a_ceny_jako_tabela():
    for kolumna in ("sklep", "link"):
        assert kolumna in KONFIG_MAGAZYNU["kolumny"] and kolumna in KONFIG_MAGAZYNU["dopisane"]
    assert KONFIG_CEN["kolumny"] == ["nazwa", "data", "cena_jednostkowa", "jednostka", "ilosc", "sklep"]
    assert KONFIG_CEN["fk"] == {} and not KONFIG_CEN.get("dopisane")
    assert "ceny_czesci" in db.KOSZ_TABELE_SYNCHRONIZOWANE and "ceny_czesci" in db.TABELE_Z_DATA_ISO


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


def test_pierwsza_synchronizacja_po_aktualizacji_nie_wysyla_magazynu(baza):
    """Pozycja zsynchronizowana starszą wersją: hash i chmura bez kluczy sklepu
    i linku. Puste nowe kolumny to nie zmiana — dopiero wpisany sklep jedzie."""
    auto = pojazd()
    czesc = pozycja(auto, cena_j=30.0, data="05.01.2024")
    with db.polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        wiersz = conn.execute("SELECT * FROM magazyn_czesci WHERE id=?", (czesc,)).fetchone()
    stare = {k: wiersz[k] for k in KONFIG_MAGAZYNU["kolumny"] if k not in ("sklep", "link")}
    with db.polacz_baze() as conn:
        conn.execute("UPDATE magazyn_czesci SET zdalne_id='mag-A', zdalny_hash=? WHERE id=?",
                     (sync_wysylanie._hash_zawartosci(stare), czesc))
    sync_konflikty._konflikty_biezacej_synchronizacji.clear()
    chmura = ChmuraWPamieci({"mag-A": stare})

    assert sync_wysylanie._wypchnij_tabele(chmura, "wspolny", auto, KONFIG_MAGAZYNU, db.ROLA_WLASCICIEL)[0] == 0

    with db.polacz_baze() as conn:
        conn.execute("UPDATE magazyn_czesci SET sklep='Inter Cars' WHERE id=?", (czesc,))
    assert sync_wysylanie._wypchnij_tabele(chmura, "wspolny", auto, KONFIG_MAGAZYNU, db.ROLA_WLASCICIEL)[0] == 1
    assert chmura.rekordy["mag-A"]["sklep"] == "Inter Cars"
    assert sync_konflikty._konflikty_biezacej_synchronizacji == []

    # Bez tolerancji pustych dopisanych kolumn poleciałby po aktualizacji cały magazyn.
    with db.polacz_baze() as conn:
        conn.execute("UPDATE magazyn_czesci SET sklep=NULL, zdalny_hash=? WHERE id=?",
                     (sync_wysylanie._hash_zawartosci(stare), czesc))
    kopia = ChmuraWPamieci({"mag-A": stare})
    assert sync_wysylanie._wypchnij_tabele(kopia, "wspolny", auto, {**KONFIG_MAGAZYNU, "dopisane": []},
                                           db.ROLA_WLASCICIEL)[0] == 1


def test_zakupy_jada_do_chmury_i_wracaja_z_data_iso(baza):
    auto = pojazd()
    zakup(auto, "Filtr oleju", "12.01.2024", 30.0, ilosc=2.0, sklep="Allegro")
    chmura = ChmuraWPamieci()

    assert sync_wysylanie._wypchnij_tabele(chmura, "wspolny", auto, KONFIG_CEN, db.ROLA_WLASCICIEL)[0] == 1
    (wyslany,) = chmura.rekordy.values()
    assert wyslany == {"nazwa": "Filtr oleju", "data": "12.01.2024", "cena_jednostkowa": 30.0,
                       "jednostka": "szt", "ilosc": 2.0, "sklep": "Allegro"}

    drugie = pojazd("Drugi telefon")
    rekord = {"id": "cena-B", "dane": {**wyslany, "data": "03.03.2025", "cena_jednostkowa": 38.0}}
    assert sync_pobieranie._zastosuj_rekord(KONFIG_CEN, rekord, drugie, {}) == 1
    assert jeden("SELECT data_iso, cena_jednostkowa FROM ceny_czesci WHERE zdalne_id='cena-B'") == ("2025-03-03", 38.0)
    assert ceny(drugie) == [("03.03.2025", 38.0, False)]


def test_kosz_przenosi_historie_cen_i_sklep(baza):
    ids = pomoce.utworz_pojazd("Do kosza")
    przed = dziennik(ids["auto_id"])
    assert przed == [("Filtr oleju", "12.01.2025", 15.0, 2.0, "Allegro")]

    wynik = db.usun_auto_do_kosza(ids["auto_id"])
    assert jeden("SELECT COUNT(*) FROM ceny_czesci") == 0
    db.przywroc_auto_z_kosza(wynik["kosz_id"])

    assert dziennik(ids["auto_id"]) == przed
    assert jeden("SELECT data_iso FROM ceny_czesci WHERE auto_id=?", (ids["auto_id"],)) == "2025-01-12"
    assert jeden("SELECT sklep, link FROM magazyn_czesci WHERE id=?", (ids["magazyn"],)) == (
        "Inter Cars", "https://example.com/filtr-oleju")
