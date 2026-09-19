"""Kondycja pojazdu: co ją obniża i dlaczego wynik nadal cokolwiek znaczy.

Kondycja liczyła wyłącznie podzespoły i bieżnik, więc auto z przeterminowanym
OC potrafiło mieć 100/100 — a polisa po terminie to poważniejszy problem niż
filtr kabinowy. Po dołożeniu dokumentów, zaległych usterek, nieścisłości
licznika i braków w danych CAŁA tabela kar musiała zostać przeważona: inaczej
każde starsze auto siadałoby na zero i wskaźnik przestałby różnicować
cokolwiek. Te testy pilnują obu stron tej zmiany naraz — że nowe powody
faktycznie bolą i że stare przestały boleć za mocno.
"""

import itertools
from datetime import date, timedelta

import flet as ft
import pytest

import db
import pomoce
import utils

_numer = itertools.count(1)


def za_dni(dni):
    return (date.today() + timedelta(days=dni)).strftime("%d.%m.%Y")


def dni_temu(dni):
    return za_dni(-dni)


def pojazd(z_licznikiem=True, **pola):
    """Auto bez ani jednego problemu: ważne OC i przegląd, świeży licznik, zero
    podzespołów. Punkt odniesienia 100/100 — każdy test psuje dokładnie jedno."""
    kolumny = {
        "nazwa": f"Testowy {next(_numer)}", "typ_paliwa": "Benzyna",
        "status": db.STATUS_POJAZDU_AKTYWNY, "rola_wspoldzielenia": db.ROLA_WLASCICIEL,
        "oc_data": za_dni(200), "przeglad_data": za_dni(200),
    }
    kolumny.update(pola)
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            f"INSERT INTO samochody ({', '.join(kolumny)}) "
            f"VALUES ({', '.join('?' for _ in kolumny)})",
            list(kolumny.values())
        )
        auto_id = c.lastrowid
    if z_licznikiem:
        odczyty(auto_id, (30, 99000), (0, 100000))
    return auto_id


def odczyty(auto_id, *pary):
    with db.polacz_baze() as conn:
        for dni, przebieg in pary:
            conn.execute(
                "INSERT INTO odczyty_przebiegu (auto_id, data, przebieg, zrodlo) VALUES (?,?,?,?)",
                (auto_id, dni_temu(dni), przebieg, db.ZRODLO_ODCZYTU_DOMYSLNE)
            )


def podzespol_po_terminie(auto_id, nazwa="Filtr kabinowy"):
    with db.polacz_baze() as conn:
        conn.execute(
            "INSERT INTO zadania (auto_id, nazwa, data, interwal_miesiace) VALUES (?,?,?,?)",
            (auto_id, nazwa, dni_temu(400), 12)
        )


def usterka(auto_id, tytul, priorytet, termin, wykonane=0):
    with db.polacz_baze() as conn:
        conn.execute(
            "INSERT INTO do_zrobienia (auto_id, tytul, priorytet, termin, wykonane) VALUES (?,?,?,?,?)",
            (auto_id, tytul, priorytet, termin, wykonane)
        )


def wynik(auto_id):
    return db.oblicz_kondycje_pojazdu(auto_id)


def powody(auto_id, kategoria):
    return [p for p in db.pobierz_rozbicie_kondycji(auto_id)["powody"]
            if p["kategoria"] == kategoria]


def teksty(kontrolka):
    """Wszystkie napisy z poddrzewa w kolejności czytania."""
    zebrane = []

    def zejdz(biezaca):
        if isinstance(biezaca, ft.Text) and biezaca.value:
            zebrane.append(str(biezaca.value))
        for nazwa in ("title", "subtitle", "controls", "content"):
            wartosc = getattr(biezaca, nazwa, None)
            if isinstance(wartosc, (list, tuple)):
                for dziecko in wartosc:
                    if isinstance(dziecko, ft.Control):
                        zejdz(dziecko)
            elif isinstance(wartosc, ft.Control):
                zejdz(wartosc)

    zejdz(kontrolka)
    return zebrane


# ============================================================================
#  1. DOKUMENTY — powód całej zmiany
# ============================================================================

def test_zdrowe_auto_ma_komplet_punktow(baza):
    assert wynik(pojazd()) == 100


def test_przeterminowane_oc_nie_daje_juz_setki(baza):
    auto_id = pojazd(oc_data=dni_temu(12))

    (powod,) = powody(auto_id, "dokument")
    assert powod["opis"] == "Polisa OC — po terminie"
    assert powod["szczegol"] == "Przekroczono o 12 dni"
    assert powod["waga"] == "krytyczna"
    assert powod["trasa"] == f"/auto/edytuj/{auto_id}"
    assert wynik(auto_id) == 100 - db.KARY_KONDYCJI["dokument_krytyczny_przeterminowany"]


def test_polisa_bije_mocniej_niz_filtr(baza):
    """Zdanie, od którego zaczęła się zmiana: przeterminowana polisa to
    poważniejszy problem niż przeterminowany filtr kabinowy."""
    z_polisa = pojazd(oc_data=dni_temu(1))
    z_filtrem = pojazd()
    podzespol_po_terminie(z_filtrem)

    assert wynik(z_polisa) < wynik(z_filtrem) < 100


def test_oc_i_przeglad_razem_to_pilna_reakcja(baza):
    auto_id = pojazd(oc_data=dni_temu(30), przeglad_data=dni_temu(5))

    assert wynik(auto_id) == 40
    assert utils.wskaznik_kondycji(wynik(auto_id))[2] == "Wymaga pilnej reakcji"


def test_zblizajacy_sie_termin_kosztuje_mniej_niz_przekroczony(baza):
    auto_id = pojazd(oc_data=za_dni(10))

    (powod,) = powody(auto_id, "dokument")
    assert powod["opis"] == "Polisa OC — termin się zbliża"
    assert wynik(auto_id) == 100 - db.KARY_KONDYCJI["dokument_krytyczny_pilny"]


def test_daleki_termin_nie_rusza_wyniku(baza):
    assert wynik(pojazd(oc_data=za_dni(db.HORYZONT_TERMINU_KONDYCJI + 1))) == 100


def test_prog_powiadomien_nie_zmienia_kondycji(baza):
    """Próg z ustawień decyduje, kiedy przypomnieć, a nie jak ocenić auto.
    Inaczej porównanie pojazdów porównywałoby ustawienia, a nie samochody."""
    auto_id = pojazd(oc_data=za_dni(120))
    db.zapisz_prog_dni_dokumentu("oc", 180)

    assert [p["klucz"] for p in db.pobierz_powiadomienia(auto_id) if p["typ"] == "dokument"]
    assert wynik(auto_id) == 100


def test_koniec_gwarancji_nie_jest_usterka(baza):
    """Gwarancja kiedyś się kończy i nie da się z tym nic zrobić — kara byłaby
    karą za upływ czasu."""
    assert wynik(pojazd(gwarancja_data=dni_temu(60))) == 100


def test_waga_dokumentu_rosnie_z_konsekwencjami(baza):
    apteczka = pojazd(apteczka_data=dni_temu(10))
    ac = pojazd(ac_data=dni_temu(10))
    oc = pojazd(oc_data=dni_temu(10))

    assert 100 > wynik(apteczka) > wynik(ac) > wynik(oc)


# ============================================================================
#  2. PRZEWAŻENIE — sufity grup
# ============================================================================

def test_sufit_grupy_ratuje_wynik_starego_auta(baza):
    """Sześć zaległych podzespołów to nie to samo, co brak OC i łyse opony —
    bez sufitu każde auto z długą listą serwisową byłoby tak samo czerwone."""
    auto_id = pojazd()
    for i in range(6):
        podzespol_po_terminie(auto_id, nazwa=f"Podzespół {i}")

    rozbicie = db.pobierz_rozbicie_kondycji(auto_id)
    grupa = rozbicie["grupy"]["podzespol"]

    assert len(rozbicie["powody"]) == 6
    assert grupa["surowe"] == 6 * db.KARY_KONDYCJI["podzespol_przeterminowany"]
    assert grupa["punkty"] == db.SUFITY_KONDYCJI["podzespol"]
    assert grupa["przyciete"] is True
    assert rozbicie["wynik"] == 100 - db.SUFITY_KONDYCJI["podzespol"]


def test_grupa_w_limicie_nie_jest_przycinana(baza):
    auto_id = pojazd()
    podzespol_po_terminie(auto_id)

    grupa = db.pobierz_rozbicie_kondycji(auto_id)["grupy"]["podzespol"]
    assert grupa["przyciete"] is False
    assert grupa["punkty"] == grupa["surowe"]


def test_odjete_zgadza_sie_z_wynikiem(baza):
    auto_id = pojazd(oc_data=dni_temu(3))
    podzespol_po_terminie(auto_id)

    rozbicie = db.pobierz_rozbicie_kondycji(auto_id)
    assert rozbicie["odjete"] == 100 - rozbicie["wynik"]


def test_bez_pojazdu_rozpiska_jest_pusta(baza):
    assert db.pobierz_rozbicie_kondycji(None) == {
        "wynik": None, "odjete": 0, "powody": [], "grupy": {},
    }


# ============================================================================
#  3. LICZNIK I DANE
# ============================================================================

def test_cofka_licznika_obniza_kondycje(baza):
    auto_id = pojazd(z_licznikiem=False)
    odczyty(auto_id, (60, 100000), (30, 101000), (0, 100500))

    (powod,) = powody(auto_id, "licznik")
    assert powod["opis"] == "Historia licznika — 1 nieścisłość"
    assert powod["trasa"] == "/przebieg"
    assert wynik(auto_id) == 100 - db.KARY_KONDYCJI["anomalia_licznika"]


def test_niescislosci_nie_zjadaja_calej_skali(baza):
    """Licznik pełen cofek to jeden problem — brak zaufania do przebiegu —
    a nie dwadzieścia osobnych kar."""
    auto_id = pojazd(z_licznikiem=False)
    odczyty(auto_id, *[(400 - i * 20, 105000 if i % 2 == 0 else 100000) for i in range(20)])

    (powod,) = powody(auto_id, "licznik")
    assert powod["punkty"] == db.SUFITY_KONDYCJI["licznik"]


@pytest.mark.parametrize("dni, klucz", [
    (30, None),
    (db.DNI_CISZY_W_DANYCH + 5, "cisza_w_danych"),
    (db.DNI_DLUGIEJ_CISZY_W_DANYCH + 5, "cisza_w_danych_dluga"),
])
def test_cisza_w_danych_ma_dwa_progi(baza, dni, klucz):
    auto_id = pojazd(z_licznikiem=False)
    odczyty(auto_id, (dni + 20, 100000), (dni, 100500))

    kary = [p["punkty"] for p in powody(auto_id, "dane")]
    assert kary == ([] if klucz is None else [db.KARY_KONDYCJI[klucz]])


def test_cisza_mowi_kiedy_byl_ostatni_wpis(baza):
    auto_id = pojazd(z_licznikiem=False)
    odczyty(auto_id, (420, 100000), (400, 100500))

    (powod,) = powody(auto_id, "dane")
    assert powod["opis"] == "Brak nowych danych od 400 dni"
    assert powod["szczegol"].startswith(f"Ostatni wpis: {dni_temu(400)}")


def test_brak_terminow_to_luka_w_danych_a_nie_porzadek(baza):
    """Puste pole nie znaczy „wszystko gra” — znaczy, że nikt nie wie."""
    auto_id = pojazd(oc_data=None, przeglad_data=None)

    assert [p["opis"] for p in powody(auto_id, "dane")] == [
        "Polisa OC — brak wpisanej daty",
        "Przegląd techniczny — brak wpisanej daty",
    ]
    assert wynik(auto_id) == 100 - 2 * db.KARY_KONDYCJI["brak_terminu_dokumentu"]


def test_brak_nieobowiazkowego_terminu_nie_jest_karany(baza):
    """AC i assistance to wybór właściciela, a nie obowiązek."""
    assert wynik(pojazd(ac_data=None, assistance_data=None)) == 100


def test_brak_historii_licznika_widac_w_rozpisce(baza):
    auto_id = pojazd(z_licznikiem=False)

    (powod,) = powody(auto_id, "dane")
    assert powod["opis"] == "Brak jakiegokolwiek stanu licznika"
    assert wynik(auto_id) == 100 - db.KARY_KONDYCJI["brak_historii_licznika"]


def test_sprzedane_auto_nie_dostaje_kar_za_cisze_i_braki(baza):
    """Po sprzedaży nikt już nic nie wpisuje — to normalne, nie zaniedbanie."""
    auto_id = pojazd(z_licznikiem=False, oc_data=None, przeglad_data=None,
                     status=db.STATUS_POJAZDU_SPRZEDANY)

    assert powody(auto_id, "dane") == []
    assert wynik(auto_id) == 100


# ============================================================================
#  4. USTERKI I DRZEMKA
# ============================================================================

def test_zalegla_usterka_obniza_kondycje(baza):
    auto_id = pojazd()
    usterka(auto_id, "Stuka zawieszenie", db.PRIORYTET_USTERKI, dni_temu(14))

    (powod,) = powody(auto_id, "usterka")
    assert powod["opis"] == "Stuka zawieszenie — zaległa usterka"
    assert powod["trasa"] == "/do-zrobienia"
    assert wynik(auto_id) == 100 - db.KARY_KONDYCJI["usterka_po_terminie"]


@pytest.mark.parametrize("priorytet, dni, wykonane", [
    ("Niski", -14, 0),
    ("Średni", -14, 0),
    ("Wysoki", 14, 0),
    ("Wysoki", -14, 1),
    ("Wysoki", None, 0),
])
def test_plany_i_drobiazgi_nie_sa_usterkami(baza, priorytet, dni, wykonane):
    auto_id = pojazd()
    usterka(auto_id, "Umyć auto", priorytet, za_dni(dni) if dni is not None else None, wykonane)

    assert powody(auto_id, "usterka") == []
    assert wynik(auto_id) == 100


def test_odlozenie_przypomnienia_nie_naprawia_auta(baza):
    auto_id = pojazd()
    podzespol_po_terminie(auto_id)
    przed = wynik(auto_id)

    for p in db.pobierz_powiadomienia(auto_id):
        db.odloz_powiadomienie(auto_id, p["klucz"], 30)

    assert db.pobierz_powiadomienia(auto_id) == []
    assert wynik(auto_id) == przed < 100


# ============================================================================
#  5. ROZPISKA W INTERFEJSIE
# ============================================================================

def test_panel_pokazuje_dokument_i_przyznaje_sie_do_sufitu(baza, monkeypatch):
    auto_id = pojazd(oc_data=dni_temu(9))
    for i in range(6):
        podzespol_po_terminie(auto_id, nazwa=f"Podzespół {i}")

    otwarte = []
    monkeypatch.setattr(utils.pojazd, "otworz_dno", lambda strona, arkusz: otwarte.append(arkusz))
    utils.pokaz_panel_kondycji(pomoce.zbuduj_strone().page, pomoce.stan_aplikacji(auto_id))

    napisy = teksty(otwarte[0].content.content)
    assert "Polisa OC — po terminie" in napisy
    assert any(t.startswith("Odjęto łącznie 60 pkt") for t in napisy)
    assert any("Sufit grupy ograniczył karę" in t and "Podzespoły: −30 zamiast −60" in t
               for t in napisy)


def test_panel_zdrowego_auta_nie_straszy(baza, monkeypatch):
    auto_id = pojazd()

    otwarte = []
    monkeypatch.setattr(utils.pojazd, "otworz_dno", lambda strona, arkusz: otwarte.append(arkusz))
    utils.pokaz_panel_kondycji(pomoce.zbuduj_strone().page, pomoce.stan_aplikacji(auto_id))

    assert "Nic nie obniża kondycji" in teksty(otwarte[0].content.content)
