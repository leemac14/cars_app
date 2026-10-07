"""Oś przyszłości „Co przede mną” (katalog: N-02).

Jedna chronologiczna lista tego, co pojazd ma przed sobą w oknie 30, 90 albo
365 dni: terminy dokumentów, wymiany podzespołów (także kolejne, zakładając
wymianę w terminie), każde wystąpienie wydatku cyklicznego, płatności rat,
sezonowa zmiana opon (z przypomnienia albo z kalendarza), końce budżetów
i prognoza kosztu każdego miesiąca. Pilnujemy pięciu rzeczy:

1. **Te same liczby, co gdzie indziej** — dokumenty, gwarancje i pierwsza
   wymiana podzespołu prosto z odliczań; status wpisu cyklicznego tym samym
   progiem, co dzwonek.
2. **Okno i zaległe** — pozycja po końcu okna wypada, zaległa stoi na górze
   zawsze; skończona gwarancja nie jest zaległa.
3. **Powtórzenia** — wpis co miesiąc stoi tyle razy, ile razy wypada; po
   zaległym następne liczą się od dziś; kolejne wymiany co krótszy z interwałów,
   a bez średniego przebiegu kilometrów nie zgadujemy.
4. **Prognoza** — bieżące to średnia z pełnych miesięcy BEZ tego, co stoi na
   osi z kwotą (wpisy cykliczne, wymiany podzespołów z interwałem), a suma
   miesięcy to prognoza okna.
5. **Ekran, kafelek i wejścia** — karta na pozycję, przełącznik okna pamięta
   wybór, podgląd nie prowadzi do formularzy, link z dzwonka i z odliczań.
"""

from datetime import date, timedelta

import flet as ft
import pytest

import db
import pomoce
import utils
from date import na_iso

POLA_DZIECI = ("controls", "content", "items", "actions", "leading", "trailing", "title", "subtitle")


# ============================================================================
#  POMOCNIKI
# ============================================================================

def za_dni(dni, od=None):
    return ((od or date.today()) + timedelta(days=dni)).strftime("%d.%m.%Y")


def auto(nazwa="Planowane", **pola):
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
        conn.execute("INSERT INTO odczyty_przebiegu (auto_id, data, data_iso, przebieg, zrodlo) VALUES (?,?,?,?,?)",
                     (auto_id, za_dni(-dni_temu), na_iso(za_dni(-dni_temu)), przebieg,
                      db.ZRODLO_ODCZYTU_DOMYSLNE))


def z_licznikiem(auto_id, przebieg=102400):
    """Dwa odczyty 60 dni od siebie, 2 400 km różnicy — średnio 40 km dziennie."""
    odczyt(auto_id, 60, przebieg - 2400)
    odczyt(auto_id, 0, przebieg)
    return auto_id


def podzespol(auto_id, nazwa="Olej silnikowy", interwal_km=None, interwal_miesiace=None,
              dni_temu=None, przebieg=None):
    with db.polacz_baze() as conn:
        data = za_dni(-dni_temu) if dni_temu is not None else None
        kursor = conn.execute(
            "INSERT INTO zadania (auto_id, nazwa, interwal_km, interwal_miesiace, data, data_iso, przebieg) "
            "VALUES (?,?,?,?,?,?,?)",
            (auto_id, nazwa, interwal_km, interwal_miesiace, data, na_iso(data), przebieg))
        return kursor.lastrowid


def wymiana(zadanie_id, dzien, cena):
    data = dzien.strftime("%d.%m.%Y")
    with db.polacz_baze() as conn:
        conn.execute("INSERT INTO historia (zadanie_id, data, data_iso, cena) VALUES (?,?,?,?)",
                     (zadanie_id, data, na_iso(data), cena))


def tankowanie(auto_id, dzien, kwota):
    data = dzien.strftime("%d.%m.%Y")
    with db.polacz_baze() as conn:
        conn.execute("INSERT INTO tankowania (auto_id, data, data_iso, przebieg, litry, kwota) VALUES (?,?,?,?,?,?)",
                     (auto_id, data, na_iso(data), 1000, 30.0, kwota))


def koszt(auto_id, dzien, kwota, kategoria, nazwa):
    data = dzien.strftime("%d.%m.%Y")
    with db.polacz_baze() as conn:
        conn.execute("INSERT INTO inne_koszty (auto_id, data, data_iso, kategoria, nazwa, kwota) VALUES (?,?,?,?,?,?)",
                     (auto_id, data, na_iso(data), kategoria, nazwa, kwota))


def zestaw_opon(auto_id, sezon, zamontowany=False):
    with db.polacz_baze() as conn:
        conn.execute("INSERT INTO zestawy_opon (auto_id, sezon, zamontowane) VALUES (?,?,?)",
                     (auto_id, sezon, int(zamontowany)))


def rodzaju(os_dane, rodzaj):
    return [p for p in os_dane["pozycje"] if p["rodzaj"] == rodzaj]


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


def ekran(auto_id, nazwa="Planowane", widok="PrzyszloscView"):
    stan = pomoce.stan_aplikacji(auto_id, nazwa)
    return pomoce.zbuduj_widok(pomoce.klasy_widokow()[widok], pomoce.zbuduj_strone(), stan)


def karty(korzen):
    """Karty pozycji — kontenery z `karta_listy` (mają animację nacisku)."""
    return [k for k in _wszystkie(korzen, ft.Container) if getattr(k, "animate_scale", None) is not None]


def poczatek_miesiaca(przesuniecie=0):
    dzis = date.today()
    return db.dodaj_miesiace(date(dzis.year, dzis.month, 1), przesuniecie)


# ============================================================================
#  DOKUMENTY, OKNO I ZALEGŁE
# ============================================================================

def test_bez_pojazdu_i_dla_sprzedanego_os_jest_pusta(baza):
    assert db.os_przyszlosci(None)["pozycje"] == []
    auto_id = auto(oc_data=za_dni(10), status=db.STATUS_POJAZDU_SPRZEDANY)
    os_dane = db.os_przyszlosci(auto_id)
    assert os_dane["pozycje"] == [] and os_dane["miesiace"] == []
    assert os_dane["dni"] == db.OKNO_PRZYSZLOSCI_DOMYSLNE


def test_okno_tnie_terminy_a_zalegle_stoja_na_gorze(baza):
    auto_id = auto(oc_data=za_dni(10), przeglad_data=za_dni(200), ac_data=za_dni(-5),
                   gwarancja_data=za_dni(-30))

    w90 = db.os_przyszlosci(auto_id, dni=90)
    assert [p["klucz"] for p in w90["pozycje"]] == ["dokument:ac", "dokument:oc"]
    ac, oc = w90["pozycje"]
    assert ac["zalegla"] and ac["dni"] == -5 and ac["status"] == "po_terminie"
    # Dni i status te same, co w „Ile zostało do…”.
    z_odliczan = {o["klucz"]: o for o in db.odliczania_pojazdu(auto_id)}
    assert (oc["dni"], oc["status"]) == (z_odliczan["dokument:oc"]["dni"], z_odliczan["dokument:oc"]["status"])

    w365 = [p["klucz"] for p in db.os_przyszlosci(auto_id, dni=365)["pozycje"]]
    assert w365 == ["dokument:ac", "dokument:oc", "dokument:przeglad"]
    assert "dokument:gwarancja" not in w365, "skończona gwarancja to nie sprawa do załatwienia"


def test_dziwne_okno_wraca_do_domyslnego(baza):
    auto_id = auto(oc_data=za_dni(10))
    assert db.os_przyszlosci(auto_id, dni=0)["dni"] == db.OKNO_PRZYSZLOSCI_DOMYSLNE
    os_dane = db.os_przyszlosci(auto_id, dni=30)
    assert os_dane["do"] == date.today() + timedelta(days=30)


# ============================================================================
#  PODZESPOŁY
# ============================================================================

def test_podzespol_z_kolejnymi_wymianami_po_cenie_ostatniej(baza):
    """Interwał 3 miesiące (91 dni), wymiana 30 dni temu: termin za 61 dni,
    kolejne co 91 dni — zakładając wymianę w terminie."""
    auto_id = auto()
    zadanie = podzespol(auto_id, "Filtr kabinowy", interwal_miesiace=3, dni_temu=30)
    wymiana(zadanie, date.today() - timedelta(days=120), 90.0)
    wymiana(zadanie, date.today() - timedelta(days=30), 120.0)

    wymiany = rodzaju(db.os_przyszlosci(auto_id, dni=365), "podzespol")
    assert [p["dni"] for p in wymiany] == [61, 152, 243, 334]
    assert [p["zakladana"] for p in wymiany] == [False, True, True, True]
    assert all(p["kwota"] == 120.0 and p["szacunek"] for p in wymiany), "cena OSTATNIEJ wymiany"
    assert [p["dni"] for p in rodzaju(db.os_przyszlosci(auto_id, dni=90), "podzespol")] == [61]


def test_zalegla_wymiana_a_kolejne_od_dzis(baza):
    auto_id = auto()
    podzespol(auto_id, "Płyn hamulcowy", interwal_miesiace=3, dni_temu=100)

    wymiany = rodzaju(db.os_przyszlosci(auto_id, dni=365), "podzespol")
    assert wymiany[0]["zalegla"] and wymiany[0]["dni"] == -9
    assert [p["dni"] for p in wymiany[1:]] == [91, 182, 273, 364]


def test_kilometry_przez_sredni_przebieg_i_krotszy_interwal(baza):
    """40 km dziennie: z 3 600 km zostanie 90 dni, a kolejne 6 000 km to 150 dni."""
    auto_id = z_licznikiem(auto())
    podzespol(auto_id, "Olej silnikowy", interwal_km=6000, dni_temu=30, przebieg=100000)
    podzespol(auto_id, "Olej przekładniowy", interwal_km=60000, interwal_miesiace=4, dni_temu=60, przebieg=100000)

    os_dane = db.os_przyszlosci(auto_id, dni=365)
    olej = [p for p in rodzaju(os_dane, "podzespol") if p["tytul"] == "Olej silnikowy"]
    assert [p["dni"] for p in olej] == [90, 240]
    assert olej[0]["prognoza"] and olej[1]["zakladana"]
    # Czas (122 dni) kończy się przed kilometrami (1 500 dni): co 122 dni.
    przekladnia = [p["dni"] for p in rodzaju(os_dane, "podzespol") if p["tytul"] == "Olej przekładniowy"]
    assert przekladnia == [62, 184, 306]


def test_kilometry_bez_sredniej_najpozniej_albo_bez_daty(baza):
    """Jeden odczyt licznika — średniej nie ma. Kilometry, które zjadły więcej
    niż czas, nie mają daty, ale czas daje granicę („najpóźniej”); same
    kilometry trafiają do „bez daty”. Kolejnych wymian wtedy nie zgadujemy."""
    auto_id = auto()
    odczyt(auto_id, 0, 102400)
    rozrzad = podzespol(auto_id, "Pasek zębaty", interwal_km=60000, interwal_miesiace=24,
                        dni_temu=400, przebieg=50000)
    klocki = podzespol(auto_id, "Klocki", interwal_km=40000, dni_temu=400, przebieg=90000)

    os_dane = db.os_przyszlosci(auto_id, dni=365)
    (pasek,) = rodzaju(os_dane, "podzespol")
    assert pasek["klucz"] == f"podzespol:{rozrzad}"
    assert pasek["najpozniej"] and not pasek["prognoza"] and pasek["dni"] == 332
    assert [p["klucz"] for p in os_dane["bez_daty"]] == [f"podzespol:{klocki}"]
    assert "najpóźniej za 332 dni" in utils.opis_pozycji_osi(pasek)


# ============================================================================
#  WYDATKI CYKLICZNE, RATY, OPONY, BUDŻETY
# ============================================================================

def test_wydatek_cykliczny_przy_kazdym_wystapieniu(baza):
    auto_id = auto()
    db.dodaj_wydatek_cykliczny(auto_id, "Abonament GPS", 49.0, 30, za_dni(5))

    abonament = rodzaju(db.os_przyszlosci(auto_id, dni=90), "cykliczny")
    assert [p["dni"] for p in abonament] == [5, 35, 65]
    # Próg dzwonka: wspólne 30 dni przycięte do trzeciej części okresu (10 dni).
    assert [p["status"] for p in abonament] == ["blisko", "ok", "ok"]
    assert all(p["kwota"] == 49.0 and not p["szacunek"] for p in abonament)
    assert utils.opis_pozycji_osi(abonament[0]) == "za 5 dni · co miesiąc"
    assert len(rodzaju(db.os_przyszlosci(auto_id, dni=365), "cykliczny")) == 13


def test_zalegly_wydatek_a_nastepne_od_dzis(baza):
    auto_id = auto()
    db.dodaj_wydatek_cykliczny(auto_id, "Garaż", 200.0, 30, za_dni(-3))
    db.dodaj_wydatek_cykliczny(auto_id, "Ciśnienie w kołach", 0.0, 30, za_dni(2), czy_koszt=0)

    os_dane = db.os_przyszlosci(auto_id, dni=90)
    garaz = [p for p in rodzaju(os_dane, "cykliczny") if p["tytul"] == "Garaż"]
    assert [p["dni"] for p in garaz] == [-3, 30, 60, 90]
    assert garaz[0]["zalegla"] and os_dane["pozycje"][0] is garaz[0]
    assert os_dane["podsumowanie"]["kwota_zalegla"] == 200.0
    cisnienie = [p for p in rodzaju(os_dane, "cykliczny") if p["tytul"] == "Ciśnienie w kołach"]
    assert cisnienie[0]["kwota"] is None and cisnienie[0]["ikona"] == "przypomnienie"


def test_raty_platnosc_po_platnosci_bez_podwojnego_wpisu(baza):
    auto_id = auto()
    pierwsza = db.dodaj_miesiace(date.today(), -2)
    db.zapisz_umowe_raty(auto_id, {
        "typ": db.TYP_CYKLICZNY_LEASING, "nazwa": "Leasing Testu", "kwota": 1200, "liczba_rat": 6,
        "zaplacone_platnosci": 1, "data_pierwszej_raty": pierwsza.strftime("%d.%m.%Y"), "wykup": 15000,
    })

    os_dane = db.os_przyszlosci(auto_id, dni=365)
    raty = rodzaju(os_dane, "rata")
    assert [p["platnosc"] for p in raty] == ["rata 2 z 6", "rata 3 z 6", "rata 4 z 6", "rata 5 z 6",
                                             "rata 6 z 6", "wykup"]
    assert raty[0]["zalegla"] and raty[0]["kwota"] == 1200 and raty[-1]["kwota"] == 15000
    assert {p["tytul"] for p in raty} == {"Leasing Testu"} and {p["trasa"] for p in raty} == {"/raty"}
    assert rodzaju(os_dane, "cykliczny") == [], "umowa z harmonogramem nie wraca jako zwykły wpis"


def test_zmiana_opon_z_przypomnienia_na_przemian(baza):
    auto_id = auto()
    zestaw_opon(auto_id, "Letnie", zamontowany=True)
    zestaw_opon(auto_id, "Zimowe")
    db.dodaj_przypomnienie_o_oponach(auto_id, za_dni(20))

    opony = rodzaju(db.os_przyszlosci(auto_id, dni=365), "opony")
    assert [(p["dni"], p["tytul"]) for p in opony] == [(20, "Zmiana opon na zimowe"), (202, "Zmiana opon na letnie")]
    assert not any(p["sugestia"] for p in opony) and {p["akcja"] for p in opony} == {"cykliczne"}


def test_podpowiedz_opon_z_kalendarza(baza):
    auto_id = auto()
    zestaw_opon(auto_id, "Letnie", zamontowany=True)
    zestaw_opon(auto_id, "Zimowe")

    opony = rodzaju(db.os_przyszlosci(auto_id, dni=365, dzis=date(2026, 10, 7)), "opony")
    assert [(p["data"], p["sezon"], p["status"]) for p in opony] == [
        (date(2026, 11, 1), "Zimowe", "info"), (date(2027, 4, 1), "Letnie", "info")]
    assert all(p["sugestia"] and p["akcja"] == "opony" for p in opony)
    assert utils.opis_pozycji_osi(opony[0]).endswith("przypomnienie nie jest ustawione")

    # Letnie na aucie w grudniu: zmiana spóźniona, stoi na dziś w kolorze uwagi.
    (spozniona,) = rodzaju(db.os_przyszlosci(auto_id, dni=30, dzis=date(2026, 12, 10)), "opony")
    assert (spozniona["dni"], spozniona["status"]) == (0, "blisko")
    assert "sezon zimowy już trwa" in utils.opis_pozycji_osi(spozniona)

    db.dodaj_przypomnienie_o_oponach(auto_id, "01.11.2026")
    opony = rodzaju(db.os_przyszlosci(auto_id, dni=365, dzis=date(2026, 10, 7)), "opony")
    assert opony and not any(p["sugestia"] for p in opony), "z przypomnieniem podpowiedź znika"


def test_podpowiedz_opon_tylko_przy_komplecie_na_oba_sezony(baza):
    auto_id = auto()
    zestaw_opon(auto_id, "Letnie", zamontowany=True)
    zestaw_opon(auto_id, "Całoroczne")
    assert rodzaju(db.os_przyszlosci(auto_id, dni=365), "opony") == []


def test_budzet_konczy_okres_w_oknie(baza):
    auto_id = auto()
    db.zapisz_budzet(auto_id, "paliwo", "miesiac", 1000)
    db.zapisz_budzet(auto_id, "razem", "rok", 20000)
    db.zapisz_budzet(auto_id, "serwis", "30dni", 500)
    tankowanie(auto_id, date.today(), 950)

    budzety = {p["klucz"]: p for p in rodzaju(db.os_przyszlosci(auto_id, dni=365), "budzet")}
    assert set(budzety) == {"budzet:paliwo:miesiac", "budzet:razem:rok"}, "okno ruchome końca nie ma"
    paliwo = budzety["budzet:paliwo:miesiac"]
    assert paliwo["data"] == poczatek_miesiaca(1) - timedelta(days=1)
    assert paliwo["status"] == "blisko" and paliwo["trasa"] == "/budzet"
    assert utils.opis_pozycji_osi(paliwo).startswith(f"koniec miesiąca · zostało 50 z 1 000 {utils.symbol_waluty()}")
    assert budzety["budzet:razem:rok"]["data"] == date(date.today().year, 12, 31)


# ============================================================================
#  PROGNOZA
# ============================================================================

def test_prognoza_bez_podwojnego_liczenia(baza):
    """Trzy pełne miesiące: paliwo, myjnia i naprawa spoza interwałów wchodzą
    do średniej; abonament („Cykliczne”), zapłacona zmiana opon (nazwa wpisu
    cyklicznego) i wymiana podzespołu z interwałem — nie, bo ich przyszłe
    kwoty stoją na osi."""
    auto_id = auto()
    dni = [poczatek_miesiaca(-m) + timedelta(days=14) for m in (1, 2, 3)]
    for dzien in dni:
        tankowanie(auto_id, dzien, 600)
    koszt(auto_id, dni[0], 40, "Myjnia i kosmetyka", "Myjnia")
    koszt(auto_id, dni[0], 50, "Cykliczne", "Abonament GPS")
    koszt(auto_id, dni[1], 120, db.KATEGORIA_INNE_DOMYSLNA, "Sezonowa zmiana opon")
    db.dodaj_przypomnienie_o_oponach(auto_id, za_dni(400), kwota=120)
    olej = podzespol(auto_id, "Olej", interwal_miesiace=12, dni_temu=40)
    wymiana(olej, dni[0], 400)
    wydech = podzespol(auto_id, "Naprawa wydechu")
    wymiana(wydech, dni[1], 300)

    os_dane = db.os_przyszlosci(auto_id, dni=365)
    assert os_dane["miesiecy_bazowych"] == 3
    srednia = (3 * 600 + 40 + 300) / 3
    assert os_dane["srednia_miesieczna"] == pytest.approx(srednia)
    pelny = next(m for m in os_dane["miesiace"] if m["pelny"] and not m["zaplanowane"])
    assert pelny["biezace"] == pytest.approx(srednia) and pelny["razem"] == pytest.approx(srednia)


def test_suma_miesiecy_to_prognoza_okna(baza):
    auto_id = auto()
    tankowanie(auto_id, poczatek_miesiaca(-1) + timedelta(days=3), 900)
    tankowanie(auto_id, date.today(), 100)
    db.dodaj_wydatek_cykliczny(auto_id, "Abonament GPS", 49.0, 30, za_dni(5))
    db.dodaj_wydatek_cykliczny(auto_id, "Garaż", 200.0, 30, za_dni(-3))

    os_dane = db.os_przyszlosci(auto_id, dni=90)
    miesiace, p = os_dane["miesiace"], os_dane["podsumowanie"]
    assert miesiace[0]["od"] == date.today() and miesiace[0]["biezacy"]
    assert miesiace[-1]["do"] == date.today() + timedelta(days=90)
    assert [m["od"] for m in miesiace[1:]] == [date(m["rok"], m["miesiac"], 1) for m in miesiace[1:]]
    assert p["razem"] == pytest.approx(sum(m["razem"] for m in miesiace) + p["kwota_zalegla"])
    assert p["zaplanowane"] == pytest.approx(49.0 * 3 + 200.0 * 3)
    # Kawałek miesiąca dostaje bieżące proporcjonalnie do dni.
    pierwszy = miesiace[0]
    dni_miesiaca = (poczatek_miesiaca(1) - poczatek_miesiaca(0)).days
    assert pierwszy["biezace"] == pytest.approx(900 * ((pierwszy["do"] - pierwszy["od"]).days + 1) / dni_miesiaca)
    assert pierwszy["wydano"] == pytest.approx(100)


def test_bez_pelnego_miesiaca_nie_ma_biezacych(baza):
    auto_id = auto()
    tankowanie(auto_id, date.today(), 300)
    db.dodaj_wydatek_cykliczny(auto_id, "Abonament GPS", 49.0, 30, za_dni(5))

    os_dane = db.os_przyszlosci(auto_id, dni=30)
    assert os_dane["srednia_miesieczna"] is None and os_dane["podsumowanie"]["biezace"] is None
    assert utils.razem_osi(os_dane["podsumowanie"]) == f"49 {utils.symbol_waluty()}", "bez średniej — bez „~”"


def test_okno_pamieta_wybor_bez_uniewazniania_pamieci(baza):
    assert db.pobierz_okno_przyszlosci() == db.OKNO_PRZYSZLOSCI_DOMYSLNE == 90
    db.zapisz_okno_przyszlosci(365)
    assert db.pobierz_okno_przyszlosci() == 365
    db.zapisz_okno_przyszlosci(17)
    assert db.pobierz_okno_przyszlosci() == 90
    db.zapisz_ustawienie(db.KLUCZ_OKNA_PRZYSZLOSCI, "rok")
    assert db.pobierz_okno_przyszlosci() == 90
    assert db.ustawienie_interfejsu(db.KLUCZ_OKNA_PRZYSZLOSCI), "wybór okna to pamięć interfejsu"


# ============================================================================
#  SŁOWA
# ============================================================================

@pytest.mark.parametrize("dni, prognoza, oczekiwany", [
    (-3, False, "3 dni po terminie"), (0, False, "dzisiaj"), (1, False, "jutro"),
    (12, False, "za 12 dni"), (40, True, "za ok. 40 dni"), (143, False, "za 143 dni (~5 mies.)"),
])
def test_kiedy(baza, dni, prognoza, oczekiwany):
    assert utils.kiedy_osi(dni, prognoza) == oczekiwany


@pytest.mark.parametrize("okres, oczekiwany", [
    (30, "co miesiąc"), (182, "co pół roku"), (7, "co tydzień"), (45, "co 45 dni"),
])
def test_co_ile(okres, oczekiwany):
    assert utils.co_ile_osi(okres) == oczekiwany


# ============================================================================
#  EKRAN
# ============================================================================

def test_ekran_ma_karte_na_kazda_pozycje_i_naglowki_miesiecy(baza):
    auto_id = auto(oc_data=za_dni(10), ac_data=za_dni(-5))
    db.dodaj_wydatek_cykliczny(auto_id, "Abonament GPS", 49.0, 30, za_dni(5))

    widok = ekran(auto_id)
    os_dane = widok.os
    assert len(karty(widok.lista)) == len(os_dane["pozycje"]) + len(os_dane["bez_daty"]) == 5
    assert all(k.on_click is not None for k in karty(widok.lista))
    tresc = teksty(widok)
    assert "Zaległe" in tresc and "Polisa AC" in tresc and "Abonament GPS" in tresc
    assert utils.opis_okna_osi(os_dane) in tresc and utils.liczba_pozycji_osi(os_dane["podsumowanie"]) in tresc
    for miesiac in os_dane["miesiace"]:
        assert utils.nazwa_miesiaca_osi(miesiac) in tresc
    assert "Jak liczona jest prognoza" in tresc


def test_przelacznik_okna_przelicza_i_pamieta(baza):
    auto_id = auto(oc_data=za_dni(10), przeglad_data=za_dni(200))

    widok = ekran(auto_id)
    assert widok.dni == 90 and len(karty(widok.lista)) == 1
    widok._zmien_okno(365)
    assert db.pobierz_okno_przyszlosci() == 365 and len(karty(widok.lista)) == 2
    assert "Następne 365 dni" in " ".join(teksty(widok.lista))
    assert ekran(auto_id).dni == 365, "następne wejście pamięta okno"


def test_podglad_nie_prowadzi_do_formularzy(baza):
    auto_id = z_licznikiem(auto(oc_data=za_dni(10)))
    podzespol(auto_id, interwal_miesiace=3, dni_temu=30)
    db.dodaj_wydatek_cykliczny(auto_id, "Abonament GPS", 49.0, 30, za_dni(5))
    db.ustaw_role_pojazdu(auto_id, db.ROLA_PODGLAD)

    widok = ekran(auto_id)
    dzialania = {p["rodzaj"]: (widok._trasa(p), widok._obsluga(p) is not None) for p in widok.os["pozycje"]}
    assert dzialania["dokument"] == ("/pojazd", True)
    assert dzialania["podzespol"] == (None, False)
    assert dzialania["cykliczny"][1] is False


def test_panel_wydatkow_po_zamknieciu_przelicza_os(baza, monkeypatch):
    """Wpis cykliczny otwiera panel wydatków; „Zapłacone” przesuwa w nim termin,
    a trasa pod arkuszem się nie zmienia — oś liczy się od nowa przy zamknięciu."""
    auto_id = auto()
    db.dodaj_wydatek_cykliczny(auto_id, "Abonament GPS", 49.0, 30, za_dni(5))
    widok = ekran(auto_id)
    otwarte = []
    monkeypatch.setattr(utils.powiadomienia, "otworz_dno", lambda strona, arkusz: otwarte.append(arkusz))

    widok._obsluga(rodzaju(widok.os, "cykliczny")[0])(None)
    (arkusz,) = otwarte
    db.oznacz_zaplacony_wydatek_cykliczny(db.pobierz_wydatki_cykliczne(auto_id)[0][0], auto_id)
    arkusz.on_dismiss(None)

    assert [p["dni"] for p in rodzaju(widok.os, "cykliczny")] == [30, 60, 90]


def test_pusty_ekran_zaprasza_do_uzupelnienia(baza):
    auto_id = auto()
    tresc = teksty(ekran(auto_id))
    assert "Nic tu jeszcze nie wypada" in tresc and "Uzupełnij daty" in tresc

    db.ustaw_role_pojazdu(auto_id, db.ROLA_PODGLAD)
    tresc = teksty(ekran(auto_id))
    assert "Nic tu jeszcze nie wypada" in tresc and "Uzupełnij daty" not in tresc

    assert "Auto jest sprzedane" in teksty(ekran(auto("Sprzedane", status=db.STATUS_POJAZDU_SPRZEDANY), "Sprzedane"))


def test_ekran_jest_w_szufladzie_i_wyszukiwarce(baza):
    wpis = utils.EKRANY_WG_ID["co-przede-mna"]
    assert wpis["trasa"] == "/co-przede-mna" and wpis["grupa"] == "pojazd"
    for fraza in ("co przede", "urlop", "terminarz", "do przodu"):
        assert "co-przede-mna" in [e["id"] for e in utils.znajdz_ekrany(fraza)], fraza


# ============================================================================
#  WEJŚCIA: KAFELEK, „ILE ZOSTAŁO DO…” I DZWONEK
# ============================================================================

def kokpit(auto_id, nazwa="Planowane"):
    stan = pomoce.stan_aplikacji(auto_id, nazwa)
    stan.zakladka = 0
    db.zapisz_widgety_kokpitu(["przede_mna"], auto_id)
    return pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(), stan)


def test_kafelek_pokazuje_najblizszy_miesiac(baza):
    auto_id = auto(oc_data=za_dni(10), przeglad_data=za_dni(-2), ac_data=za_dni(200))
    db.dodaj_wydatek_cykliczny(auto_id, "Abonament GPS", 49.0, 30, za_dni(5))

    tresc = teksty(kokpit(auto_id).kokpit_kontener)
    os_dane = db.os_przyszlosci(auto_id, dni=db.OKNO_KAFELKA_PRZYSZLOSCI)
    assert "Co przede mną · 30 dni" in tresc
    assert utils.razem_osi(os_dane["podsumowanie"]) in tresc
    assert "3 pozycje · 1 zaległa" in tresc
    assert tresc.index("Przegląd techniczny") < tresc.index("Abonament GPS") < tresc.index("Polisa OC")
    assert "Polisa AC" not in tresc, "poza miesiącem"


def test_same_terminy_bez_kwot_nie_udaja_zera(baza):
    """Sam termin OC i za mało wpisów na średnią: ani ekran, ani kafelek nie
    mówią „0 zł” — polisa ma cenę, tylko jeszcze jej nie znamy."""
    auto_id = auto(oc_data=za_dni(10))
    zero = f"0 {utils.symbol_waluty()}"

    ekran_tresc = teksty(ekran(auto_id))
    assert utils.BEZ_KWOT_OSI in ekran_tresc and zero not in ekran_tresc

    kafel = teksty(kokpit(auto_id).kokpit_kontener)
    assert "1 pozycja" in kafel and "bez kwot do zsumowania" in kafel and zero not in kafel


def test_pusty_kafelek_chowa_sie(baza):
    widok = kokpit(auto())
    assert "przede_mna" in widok._kokpit_puste

    db.zapisz_chowanie_pustych_kafelkow(False)
    assert "Nic w najbliższym miesiącu" in teksty(kokpit(auto("Drugie"), "Drugie").kokpit_kontener)


def test_ile_zostalo_prowadzi_do_osi(baza, monkeypatch):
    auto_id = auto(oc_data=za_dni(10))
    widok = ekran(auto_id, widok="OdliczaniaView")
    (przycisk,) = [b for b in _wszystkie(widok, ft.TextButton) if b.content == "Cały rok do przodu"]

    trasy = []
    monkeypatch.setattr(utils, "przejdz", lambda strona, trasa: trasy.append(trasa))
    przycisk.on_click(None)
    assert trasy == ["/co-przede-mna"]


def test_dzwonek_prowadzi_do_osi(baza, monkeypatch):
    auto_id = auto(oc_data=za_dni(3))
    otwarte, trasy = [], []
    monkeypatch.setattr(utils.powiadomienia, "otworz_dno", lambda strona, arkusz: otwarte.append(arkusz))
    monkeypatch.setattr(utils.powiadomienia, "zamknij_dno", lambda strona, arkusz: None)
    monkeypatch.setattr(utils.powiadomienia, "przejdz", lambda strona, trasa: trasy.append(trasa))
    utils.pokaz_panel_powiadomien(pomoce.zbuduj_strone().page, pomoce.stan_aplikacji(auto_id))

    (arkusz,) = otwarte
    (przycisk,) = [b for b in _wszystkie(arkusz.content.content, ft.TextButton) if b.content == "Co przede mną"]
    przycisk.on_click(None)
    assert trasy == ["/co-przede-mna"]
