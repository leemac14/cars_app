"""Do zrobienia: wykonanie z datą, licznikiem i kosztem, wpis serwisowy albo Inny koszt,
cofnięcie (do kosza), wizyta z listy w Wykonanych, zwrot z wizyty, dziennik pozycji,
terminy (przesunięcie, przebieg), oś czasu, eksport, chmura i kosz."""

import json
from datetime import date

import pytest

import db
import pomoce
import sync
from date import na_iso
from pomoce import dzien, wstaw
from sync import konflikty as sync_konflikty
from sync import wysylanie as sync_wysylanie


def jeden(sql, parametry=()):
    with db.polacz_baze() as conn:
        w = conn.execute(sql, parametry).fetchone()
    return (w[0] if len(w) == 1 else tuple(w)) if w else None


def zdarzenia(pozycja_id):
    return [z["rodzaj"] for z in db.pobierz_zdarzenia_do_zrobienia(pozycja_id)]


@pytest.fixture
def auto(baza):
    """Auto z licznikiem (dziś 120 000, 30 dni temu 117 000) i podzespołem z interwałem."""
    db.zapisz_moje_imie("Kamil")
    a = wstaw("samochody", nazwa="Astra", typ_paliwa="Benzyna")
    wstaw("odczyty_przebiegu", auto_id=a, data=dzien(30), przebieg=117000)
    wstaw("odczyty_przebiegu", auto_id=a, data=dzien(0), przebieg=120000)
    olej = wstaw("zadania", auto_id=a, nazwa="Olej silnikowy", interwal_km=15000, interwal_miesiace=12)
    return {"auto_id": a, "olej": olej}


def pozycja(auto, tytul="Wymienić olej", zadanie=True, **pola):
    dane = {"tytul": tytul, "priorytet": "Wysoki", "szacowany_koszt": 300, **pola}
    if zadanie:
        dane["zadanie_id"] = auto["olej"]
    return db.zapisz_pozycje_do_zrobienia(auto["auto_id"], dane)


# ============================================================================
#  WYKONANIE
# ============================================================================

def test_wykonanie_z_podzespolem_dopisuje_wpis_serwisowy_z_dniem_wykonania(auto):
    p = pozycja(auto)
    wynik = db.oznacz_wykonane_do_zrobienia([p], {"data": dzien(10), "przebieg": 119000, "koszt": "280,50",
                                                   "notatka": "Castrol 5W-30", "powiazany": True})

    assert wynik["liczba"] == 1 and wynik["serwis"] == 1
    h = db.pozycja_do_zrobienia(p)["historia_id"]
    assert jeden("SELECT data, data_iso, przebieg, cena, notatka, dodane_przez, zadanie_id FROM historia WHERE id=?",
                 (h,)) == (dzien(10), na_iso(dzien(10)), 119000, 280.5, "Castrol 5W-30", "Kamil", auto["olej"])
    assert jeden("SELECT data FROM zadania WHERE id=?", (auto["olej"],)) == dzien(10), "interwał liczy się od nowa"
    wykonana = db.pobierz_pozycje_do_zrobienia(auto["auto_id"], wykonane=True)[0]
    assert (wykonana["data_wykonania"], wykonana["przebieg_wykonania"], wykonana["koszt_wykonania"],
            wykonana["notatka_wykonania"], wykonana["wykonane_przez"]) == (dzien(10), 119000, 280.5, "Castrol 5W-30", "Kamil")
    assert db.pobierz_pozycje_do_zrobienia(auto["auto_id"]) == []
    assert zdarzenia(p) == ["dodano", "wykonano"]


def test_wykonanie_bez_podzespolu_dopisuje_inny_koszt(auto):
    p = pozycja(auto, "Wymienić żarówkę", zadanie=False)
    db.oznacz_wykonane_do_zrobienia([p], {"data": dzien(2), "koszt": 35, "powiazany": True})

    k = db.pozycja_do_zrobienia(p)["koszt_id"]
    assert jeden("SELECT data, data_iso, nazwa, kwota, kategoria FROM inne_koszty WHERE id=?", (k,)) == \
        (dzien(2), na_iso(dzien(2)), "Wymienić żarówkę", 35.0, db.KATEGORIA_INNE_DOMYSLNA)


def test_wykonanie_bez_powiazania_zostaje_przy_pozycji(auto):
    p = pozycja(auto)
    db.oznacz_wykonane_do_zrobienia([p], {"data": dzien(1), "przebieg": 119900, "koszt": 300, "powiazany": False})

    w = db.pozycja_do_zrobienia(p)
    assert (w["wykonane"], w["historia_id"], w["koszt_id"], w["koszt_wykonania"]) == (True, None, None, 300.0)
    assert jeden("SELECT COUNT(*) FROM historia") == 0 and jeden("SELECT COUNT(*) FROM inne_koszty") == 0


def test_wpis_serwisowy_bez_licznika_bierze_licznik_z_historii(auto):
    p = pozycja(auto)
    db.oznacz_wykonane_do_zrobienia([p], {"data": dzien(15), "powiazany": True})

    assert jeden("SELECT przebieg FROM historia") == 118500, "połowa drogi między odczytami"


def test_poprawka_przenosi_date_do_tego_samego_wpisu(auto):
    p = pozycja(auto)
    db.oznacz_wykonane_do_zrobienia([p], {"data": dzien(10), "przebieg": 119000, "koszt": 280, "powiazany": True})
    db.oznacz_wykonane_do_zrobienia([p], {"data": dzien(12), "przebieg": 118800, "koszt": 290, "powiazany": True})

    assert jeden("SELECT COUNT(*), data, przebieg, cena FROM historia") == (1, dzien(12), 118800, 290.0)
    assert zdarzenia(p) == ["dodano", "wykonano", "poprawka"]


def test_poprawka_bez_powiazania_odklada_wpis_do_kosza(auto):
    p = pozycja(auto)
    db.oznacz_wykonane_do_zrobienia([p], {"data": dzien(10), "przebieg": 119000, "powiazany": True})
    db.oznacz_wykonane_do_zrobienia([p], {"data": dzien(10), "przebieg": 119000, "powiazany": False})

    assert jeden("SELECT COUNT(*) FROM historia") == 0
    assert jeden("SELECT tabela FROM kosz_wpisy") == "historia"
    assert db.pozycja_do_zrobienia(p)["historia_id"] is None


def test_cofniecie_wykonania_wraca_na_liste_a_wpis_do_kosza(auto):
    p = pozycja(auto)
    db.oznacz_wykonane_do_zrobienia([p], {"data": dzien(10), "przebieg": 119000, "powiazany": True})

    wynik = db.cofnij_wykonanie_do_zrobienia(p)

    assert wynik == {"do_kosza": 1, "wizyta": False}
    w = db.pozycja_do_zrobienia(p)
    assert (w["wykonane"], w["data_wykonania"], w["historia_id"]) == (False, None, None)
    assert jeden("SELECT COUNT(*) FROM historia") == 0 and jeden("SELECT COUNT(*) FROM kosz_wpisy") == 1
    assert zdarzenia(p) == ["dodano", "wykonano", "cofnieto"]
    # Wpis wraca z kosza sam — bez przyklejania z powrotem do aktywnej pozycji.
    db.przywroc_wpis_z_kosza(jeden("SELECT id FROM kosz_wpisy"))
    assert jeden("SELECT COUNT(*) FROM historia") == 1 and db.pozycja_do_zrobienia(p)["historia_id"] is None


def test_grupowe_wykonanie_bierze_szacunek_kazdej_pozycji(auto):
    olej = pozycja(auto, szacowany_koszt=300)
    myjnia = pozycja(auto, "Umyć auto", zadanie=False, szacowany_koszt=40)
    bez_kosztu = pozycja(auto, "Dokręcić listwę", zadanie=False, szacowany_koszt=None)

    wynik = db.oznacz_wykonane_do_zrobienia([olej, myjnia, bez_kosztu],
                                            {"data": dzien(0), "przebieg": 120000, "powiazany": True})

    assert (wynik["liczba"], wynik["serwis"], wynik["koszty"]) == (3, 1, 1)
    assert jeden("SELECT cena FROM historia") == 300.0 and jeden("SELECT nazwa, kwota FROM inne_koszty") == ("Umyć auto", 40.0)


def test_podglad_nie_odhaczy(auto, monkeypatch):
    p = pozycja(auto)
    monkeypatch.setattr(db.do_zrobienia, "czy_moge_dodawac", lambda auto_id: False)
    assert db.oznacz_wykonane_do_zrobienia([p], {"data": dzien(0)}) is None
    assert db.pozycja_do_zrobienia(p)["wykonane"] is False


# ============================================================================
#  WIZYTA Z LISTY I ZWROT
# ============================================================================

def test_wizyta_z_listy_zostawia_pozycje_w_wykonanych_z_odnosnikiem(auto):
    olej = pozycja(auto)
    luzna = pozycja(auto, "Wymienić wycieraczki", zadanie=False, szacowany_koszt=60)

    w_id, _, cofniecie = db.utworz_wizyte_z_do_zrobienia(auto["auto_id"], [olej, luzna])

    po = {p["id"]: p for p in db.pobierz_pozycje_do_zrobienia(auto["auto_id"], wykonane=True)}
    assert set(po) == {olej, luzna}
    assert po[olej]["wizyta_id"] == w_id and po[olej]["historia_id"] == jeden("SELECT id FROM historia")
    assert po[luzna]["wizyta_id"] == w_id and po[luzna]["historia_id"] is None
    assert po[olej]["w_wizycie"] and po[luzna]["data_wykonania"] == date.today().strftime("%d.%m.%Y")
    assert zdarzenia(olej)[-1] == "wizyta"

    cofniecie["cofnij"]()

    assert {p["id"] for p in db.pobierz_pozycje_do_zrobienia(auto["auto_id"])} == {olej, luzna}
    assert db.pozycja_do_zrobienia(olej)["wizyta_id"] is None and zdarzenia(olej) == ["dodano"]


def test_zwrot_z_wizyty_wznawia_te_sama_pozycje(auto):
    p = pozycja(auto)
    w_id, _, _ = db.utworz_wizyte_z_do_zrobienia(auto["auto_id"], [p])
    h_id = jeden("SELECT id FROM historia")
    with db.polacz_baze() as conn:
        conn.execute("UPDATE historia SET cena=320 WHERE id=?", (h_id,))

    wynik = db.zwroc_pozycje_wizyty_do_zrobienia(w_id, [h_id])

    assert jeden("SELECT COUNT(*) FROM do_zrobienia") == 1, "bez drugiej pozycji o tym samym tytule"
    w = db.pozycja_do_zrobienia(p)
    assert (w["wykonane"], w["wizyta_id"], w["szacowany_koszt"]) == (False, None, 320.0)
    assert zdarzenia(p)[-1] == "zwrot"

    wynik["cofnij"]()

    w = db.pozycja_do_zrobienia(p)
    assert (w["wykonane"], w["wizyta_id"], w["historia_id"]) == (True, w_id, h_id)
    assert zdarzenia(p)[-1] == "wizyta"


# ============================================================================
#  DZIENNIK I TERMINY
# ============================================================================

def test_edycja_notuje_termin_i_zmiane_pol(auto):
    p = pozycja(auto, termin="10.11.2026")
    db.zapisz_pozycje_do_zrobienia(auto["auto_id"], {"tytul": "Wymienić olej", "priorytet": "Niski",
                                                     "szacowany_koszt": 300, "zadanie_id": auto["olej"],
                                                     "termin": "17.11.2026"}, p)
    db.zapisz_pozycje_do_zrobienia(auto["auto_id"], {"tytul": "Wymienić olej", "priorytet": "Niski",
                                                     "szacowany_koszt": "300,00", "zadanie_id": auto["olej"],
                                                     "termin": "17.11.2026"}, p)

    wpisy = db.pobierz_zdarzenia_do_zrobienia(p)
    assert [z["rodzaj"] for z in wpisy] == ["dodano", "termin", "zmiana"], "drugi zapis bez zmian nic nie dopisuje"
    assert wpisy[1]["dane"] == {"termin": ["10.11.2026", "17.11.2026"]}
    assert wpisy[2]["dane"] == {"pola": ["priorytet"], "priorytet": ["Wysoki", "Niski"]}
    assert wpisy[2]["dodane_przez"] == "Kamil"


@pytest.mark.parametrize("termin, dni, miesiace, wynik", [
    ("20.11.2026", 7, 0, "27.11.2026"),
    ("01.10.2026", 7, 0, "01.11.2026"),   # po terminie — od dziś
    ("", 0, 1, "25.11.2026"),
    ("31.01.2027", 0, 1, "28.02.2027"),
])
def test_termin_po_przesunieciu(termin, dni, miesiace, wynik):
    assert db.termin_po_przesunieciu(termin, dni, miesiace, dzis=date(2026, 10, 25)) == wynik


def test_przesuniecie_terminu_trafia_do_dziennika(auto):
    p = pozycja(auto, termin="10.11.2026")

    assert db.przesun_termin_do_zrobienia(p, termin="17.11.2026") is True
    assert db.przesun_termin_do_zrobienia(p, termin="17.11.2026") is False

    assert db.pozycja_do_zrobienia(p)["termin"] == "17.11.2026"
    assert db.pobierz_zdarzenia_do_zrobienia(p)[-1]["dane"] == {"termin": ["10.11.2026", "17.11.2026"]}


def test_termin_przebiegowy_liczy_od_licznika_przy_planowaniu(auto):
    p = pozycja(auto, termin_przebieg=121000)

    w = db.pozycja_do_zrobienia(p)
    assert w["przebieg_startowy"] == 120000
    assert w["stan_przebiegu"] == {"cel": 121000, "zostalo": 1000, "procent": 0.0, "status": "pilne"}

    db.przesun_termin_do_zrobienia(p, termin_przebieg=125000)
    assert db.pozycja_do_zrobienia(p)["stan_przebiegu"]["status"] == "ok"


@pytest.mark.parametrize("cel, start, teraz, status, procent", [
    (130000, 120000, 125000, "ok", 0.5),
    (130000, 120000, 129500, "pilne", 0.95),
    (130000, 120000, 131000, "przeterminowane", 1.0),
    (130000, None, 125000, "ok", None),
])
def test_stan_terminu_przebiegowego(cel, start, teraz, status, procent):
    stan = db.stan_terminu_przebiegowego(cel, start, teraz)
    assert (stan["status"], stan["procent"], stan["zostalo"]) == (status, procent, cel - teraz)


def test_zalegly_przebieg_liczy_sie_jako_po_terminie_i_w_kondycji(auto):
    pozycja(auto, termin_przebieg=119000)

    assert db.podsumowanie_do_zrobienia(auto["auto_id"])["po_terminie"] == 1
    powody = [p["opis"] for p in db.pobierz_rozbicie_kondycji(auto["auto_id"])["powody"]]
    assert "Wymienić olej — zaległa usterka" in powody


def test_szacuj_przebieg_w_dniu(auto):
    a = auto["auto_id"]
    assert db.szacuj_przebieg_w_dniu(a, dzien(30)) == 117000
    assert db.szacuj_przebieg_w_dniu(a, dzien(10)) == 119000
    assert db.szacuj_przebieg_w_dniu(a, dzien(-5)) == 120000, "po ostatnim — ostatni znany"
    assert db.szacuj_przebieg_w_dniu(a, dzien(40)) is None, "przed pierwszym nie wiadomo"


# ============================================================================
#  OŚ CZASU, EKSPORT
# ============================================================================

def test_dziennik_zycia_auta_pokazuje_wykonane_bez_wpisu(auto):
    bez_wpisu = pozycja(auto, "Dokręcić listwę", zadanie=False)
    z_wpisem = pozycja(auto)
    db.oznacz_wykonane_do_zrobienia([bez_wpisu], {"data": dzien(3), "przebieg": 119700, "powiazany": False})
    db.oznacz_wykonane_do_zrobienia([z_wpisem], {"data": dzien(2), "przebieg": 119800, "powiazany": True})

    wykonane = [z for z in db.pobierz_dane_timeline(auto["auto_id"]) if z[1] == "Zadanie wykonane"]

    assert [(z[2], z[3], z[5], z[7]) for z in wykonane] == [(dzien(3), "Dokręcić listwę", None, "/do-zrobienia/wykonane")]
    assert any(z[1] == "Serwis" for z in db.pobierz_dane_timeline(auto["auto_id"])), "z wpisem — jako wpis serwisowy"


def test_eksport_niesie_wykonanie_z_kwota_z_wpisu(auto):
    p = pozycja(auto)
    pozycja(auto, "Kupić dywaniki", zadanie=False, termin_przebieg=125000)
    db.oznacz_wykonane_do_zrobienia([p], {"data": dzien(5), "przebieg": 119500, "koszt": 280, "powiazany": True})
    with db.polacz_baze() as conn:
        conn.execute("UPDATE historia SET cena=310")

    naglowki, wiersze = db.pobierz_dane_eksportu(auto["auto_id"], ["do_zrobienia"])["do_zrobienia"]

    assert naglowki[5:] == ["Wykonano", "Przebieg (km)", "Koszt", "Notatka"]
    assert wiersze[0][0] == "Kupić dywaniki" and wiersze[0][4] == 125000 and wiersze[0][5] == ""
    assert wiersze[1][5:8] == [dzien(5), 119500, "310,00"]


# ============================================================================
#  CHMURA I KOSZ
# ============================================================================

KONFIG = next(k for k in sync.KONFIGURACJA_SYNC if k["tabela"] == "do_zrobienia")
KONFIG_ZDARZEN = next(k for k in sync.KONFIGURACJA_SYNC if k["tabela"] == "do_zrobienia_zdarzenia")


def wypchnij(auto_id, konfig, chmura):
    sync_konflikty._konflikty_biezacej_synchronizacji.clear()
    return sync_wysylanie._wypchnij_tabele(chmura, "wspolny", auto_id, konfig, db.ROLA_WLASCICIEL)[0]


def test_pozycja_sprzed_aktualizacji_nie_jedzie_drugi_raz(auto):
    """Pozycja wysłana starszą wersją (bez kolumn wykonania i odwołań) po aktualizacji jest
    taka sama — inaczej cała lista jechałaby od nowa z konfliktem przy każdej pozycji."""
    p = pozycja(auto)
    stary = {"tabela": "do_zrobienia", "fk": {"zadanie_id": "zadania"},
             "kolumny": ["tytul", "opis", "priorytet", "szacowany_koszt", "termin", "wykonane", "data_utworzenia"]}
    chmura = pomoce.ChmuraWPamieci()
    assert wypchnij(auto["auto_id"], stary, chmura) == 1

    assert wypchnij(auto["auto_id"], KONFIG, chmura) == 0

    db.oznacz_wykonane_do_zrobienia([p], {"data": dzien(1), "przebieg": 119900, "powiazany": False})
    assert wypchnij(auto["auto_id"], KONFIG, chmura) == 1
    (dane,) = chmura.rekordy.values()
    assert (dane["wykonane"], dane["data_wykonania"], dane["przebieg_wykonania"]) == (1, dzien(1), 119900)


def test_dziennik_jedzie_do_chmury_za_pozycja(auto):
    p = pozycja(auto)
    chmura = pomoce.ChmuraWPamieci()
    wypchnij(auto["auto_id"], KONFIG, chmura)

    assert wypchnij(auto["auto_id"], KONFIG_ZDARZEN, chmura) == 1
    zdarzenie = next(d for d in chmura.rekordy.values() if "rodzaj" in d)
    assert zdarzenie["rodzaj"] == "dodano" and zdarzenie["pozycja_id_zdalne"] == jeden(
        "SELECT zdalne_id FROM do_zrobienia WHERE id=?", (p,))
    assert json.loads(zdarzenie["dane"]) == {}


def test_usunieta_pozycja_wraca_z_kosza_z_dziennikiem(auto):
    p = pozycja(auto, termin="10.11.2026")
    db.przesun_termin_do_zrobienia(p, termin="17.11.2026")

    wynik = db.usun_z_cofnieciem("do_zrobienia", p)
    assert jeden("SELECT COUNT(*) FROM do_zrobienia_zdarzenia") == 0
    wynik["cofnij"]()

    assert zdarzenia(p) == ["dodano", "termin"]


def test_wpis_serwisowy_z_kosza_wraca_do_wykonanej_pozycji(auto):
    p = pozycja(auto)
    db.oznacz_wykonane_do_zrobienia([p], {"data": dzien(4), "przebieg": 119600, "powiazany": True})
    h = db.pozycja_do_zrobienia(p)["historia_id"]

    wynik = db.usun_z_cofnieciem("historia", h)
    assert db.pozycja_do_zrobienia(p)["historia_id"] is None
    assert db.pozycja_do_zrobienia(p)["data_wykonania"] == dzien(4), "wykonanie zostaje z własnych kolumn"
    wynik["cofnij"]()

    assert db.pozycja_do_zrobienia(p)["historia_id"] == h


def test_kosz_przemapowuje_odwolania_pozycji_przy_zajetych_id(baza):
    """Jak test_kosz: po wczytaniu kopii ID zajmuje inne auto — odwołania pozycji do wpisu,
    kosztu i wizyty mają wskazać wiersze PRZYWRÓCONEGO auta, a dziennik — jego pozycję."""
    zrodlo = pomoce.utworz_pojazd("Pierwszy")
    wynik = db.usun_auto_do_kosza(zrodlo["auto_id"])
    with db.polacz_baze() as conn:
        conn.execute("DELETE FROM sqlite_sequence")
    pomoce.utworz_pojazd("Pierwszy")

    przywrocone = db.przywroc_auto_z_kosza(wynik["kosz_id"])

    assert pomoce.klucze_obce_spojne() == []
    d_id, h_id, k_id, w_id = jeden("SELECT id, historia_id, koszt_id, wizyta_id FROM do_zrobienia WHERE auto_id=?",
                                   (przywrocone,))
    assert jeden("SELECT z.auto_id FROM historia h JOIN zadania z ON z.id = h.zadanie_id WHERE h.id=?", (h_id,)) == przywrocone
    assert jeden("SELECT auto_id FROM inne_koszty WHERE id=?", (k_id,)) == przywrocone
    assert jeden("SELECT auto_id FROM wizyty WHERE id=?", (w_id,)) == przywrocone
    assert jeden("SELECT COUNT(*) FROM do_zrobienia_zdarzenia WHERE pozycja_id=?", (d_id,)) == 1
    assert jeden("SELECT COUNT(*) FROM do_zrobienia_zdarzenia") == 2


# ============================================================================
#  EKRAN
# ============================================================================

import sys
from types import SimpleNamespace

import flet as ft

import audyty
import utils
from views.todo_view import DO_ZROBIENIA, WYKONANE


@pytest.fixture
def ekran(monkeypatch):
    """Okna, komunikaty i przejścia zbierane zamiast pokazywane (strona testowa ich nie pokaże)."""
    zebrane = SimpleNamespace(okna=[], komunikaty=[], trasy=[])
    monkeypatch.setattr(ft.Page, "show_dialog", lambda self, okno: zebrane.okna.append(okno))
    monkeypatch.setattr(ft.Page, "pop_dialog", lambda self: None)
    podmiany = {"pokaz_komunikat": lambda page, tekst, *a, **k: zebrane.komunikaty.append(tekst),
                "pokaz_komunikat_cofnij": lambda page, tekst, *a, **k: zebrane.komunikaty.append(tekst),
                "przejdz": lambda page, trasa: zebrane.trasy.append(trasa),
                "wypchnij_w_tle": lambda *a, **k: None}
    for nazwa_modulu, modul in list(sys.modules.items()):
        if modul is not None and nazwa_modulu.split(".")[0] in ("utils", "views"):
            for nazwa, wartosc in podmiany.items():
                if hasattr(modul, nazwa):
                    monkeypatch.setattr(modul, nazwa, wartosc)
    return zebrane


def zbuduj(auto, podzakladka=DO_ZROBIENIA):
    stan = pomoce.stan_aplikacji(auto["auto_id"], "Astra")
    stan.do_zrobienia_podzakladka = podzakladka
    strona = pomoce.zbuduj_strone()
    strona.page.width = audyty.SZEROKOSC_TELEFONU
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["DoZrobieniaView"], strona, stan)
    strona.page.views.append(widok)
    return strona, widok


def kontrolki(korzen, typ):
    wynik, kolejka = [], [korzen]
    while kolejka:
        k = kolejka.pop(0)
        if isinstance(k, typ):
            wynik.append(k)
        kolejka.extend(d for _, d in audyty._dzieci(k))
    return wynik


def zapisz_okno(okno):
    next(b for b in kontrolki(okno, ft.Button) if b.content == "Zapisz").on_click(None)


def test_lista_ma_podsumowanie_i_termin_przebiegowy(auto, ekran):
    pozycja(auto, termin_przebieg=120500)
    pozycja(auto, "Umyć auto", zadanie=False, termin=dzien(3))

    strona, widok = zbuduj(auto)
    teksty = pomoce.napisy(widok)

    assert {"Aktywne", "Po terminie", "Szacunek"} <= set(teksty)
    assert "zostało 500 km" in teksty and "Przy 120 500 km" in teksty
    assert audyty.znajdz_uciete_napisy(widok) == []


def test_wykonane_maja_wlasna_podzakladke(auto, ekran):
    p = pozycja(auto)
    db.oznacz_wykonane_do_zrobienia([p], {"data": dzien(3), "przebieg": 119700, "koszt": 250,
                                          "notatka": "Castrol", "powiazany": True})
    pozycja(auto, "Kupić dywaniki", zadanie=False)

    strona, widok = zbuduj(auto, WYKONANE)
    teksty = pomoce.napisy(widok)

    assert "Wymienić olej" in teksty and "Kupić dywaniki" not in teksty
    assert f"{dzien(3)} · 119 700 km · 250,00 {utils.symbol_waluty()}" in teksty and "w serwisie" in teksty
    assert widok.floating_action_button is None and "Wykonane" in pomoce.napisy(widok.appbar)
    assert isinstance(widok.miesiace, utils.GrupyMiesiecy)
    for audyt in (audyty.znajdz_uciete_napisy, audyty.znajdz_expand_bez_ograniczenia, audyty.znajdz_rozciagliwe_chipy):
        assert audyt(widok) == [], audyt.__name__

    widok._przelacz_podzakladke(DO_ZROBIENIA)
    assert "Wymienić olej" not in pomoce.napisy(widok.przelacznik.kontrolka), "wykonane nie szarzeją na liście"


def test_szczegoly_pokazuja_historie_i_akcje(auto, ekran):
    p = pozycja(auto, termin="10.11.2026")
    db.przesun_termin_do_zrobienia(p, termin="17.11.2026")
    strona, widok = zbuduj(auto)

    widok._pokaz_szczegoly(p)

    (arkusz,) = ekran.okna
    teksty = pomoce.napisy(arkusz)
    assert {"Historia pozycji", "Dodano do listy", "Nowy termin", "10.11.2026 → 17.11.2026"} <= set(teksty)
    assert {"Oznacz jako wykonane", "Przesuń termin", "Utwórz wizytę w warsztacie"} <= set(teksty)
    assert audyty.znajdz_uciete_napisy(arkusz) == []


def test_okno_wykonania_zapisuje_dzien_licznik_i_koszt(auto, ekran):
    p = pozycja(auto)
    strona, widok = zbuduj(auto)

    widok._odhacz(SimpleNamespace(control=ft.Checkbox(value=True)), p)

    (okno,) = ekran.okna
    assert audyty.znajdz_uciete_napisy(okno) == []
    pola = {k.label: k for k in kontrolki(okno, ft.TextField)}
    assert pola["Stan licznika (km)"].value == "120000", "licznik na dziś z historii licznika"
    pola["Data wykonania"].value = dzien(2)
    pola["Stan licznika (km)"].value = "119 800"
    pola[f"Faktyczny koszt ({utils.symbol_waluty()})"].value = "275,50"
    pola["Notatka (opcjonalnie)"].value = "Filtr Mann"
    zapisz_okno(okno)

    w = db.pozycja_do_zrobienia(p)
    assert (w["data_wykonania"], w["przebieg_wykonania"], w["koszt_wykonania"], w["notatka_wykonania"]) == \
        (dzien(2), 119800, 275.5, "Filtr Mann")
    assert ekran.trasy[-1] == "/do-zrobienia" and "historii serwisowej" in ekran.komunikaty[-1]


def test_wpis_serwisowy_wymaga_licznika(auto, ekran):
    p = pozycja(auto)
    strona, widok = zbuduj(auto)
    widok._okno_wykonania([db.pozycja_do_zrobienia(p)])
    (okno,) = ekran.okna
    pola = {k.label: k for k in kontrolki(okno, ft.TextField)}
    pola["Stan licznika (km)"].value = ""

    zapisz_okno(okno)

    assert db.pozycja_do_zrobienia(p)["wykonane"] is False
    assert pola["Stan licznika (km)"].error


def test_grupowe_odhaczenie_z_paska_zaznaczania(auto, ekran):
    a = pozycja(auto)
    b = pozycja(auto, "Umyć auto", zadanie=False, szacowany_koszt=40)
    strona, widok = zbuduj(auto)
    widok.tryb_zaznaczania, widok.zaznaczone_id = True, {a, b}

    widok.oznacz_zaznaczone_jako_wykonane(None)

    (okno,) = ekran.okna
    assert "Wykonano: 2 pozycje" in pomoce.napisy(okno)
    zapisz_okno(okno)
    assert {p["id"] for p in db.pobierz_pozycje_do_zrobienia(auto["auto_id"], wykonane=True)} == {a, b}
    assert widok.tryb_zaznaczania is False


def test_przesuniecie_z_menu_pokazuje_nowe_daty(auto, ekran):
    p = pozycja(auto, termin=dzien(-10), termin_przebieg=125000)
    utils.okno_przesuniecia_terminu(pomoce.zbuduj_strone().page, db.pozycja_do_zrobienia(p))

    (menu,) = ekran.okna
    teksty = pomoce.napisy(menu)
    assert f"+1 tydzień — {dzien(-17)}" in teksty and "+1 000 km — przy 126 000 km" in teksty


def test_trasa_z_dziennika_auta_otwiera_wykonane(auto, monkeypatch):
    monkeypatch.setattr(ft, "run", lambda *a, **k: None)
    import log
    import main

    monkeypatch.setattr(log, "wlacz", lambda: True)
    monkeypatch.setitem(utils.wyglad._OSTATNI_MOTYW, "nazwa", utils.wyglad._OSTATNI_MOTYW["nazwa"])
    db.zapisz_widziana_wersje(db.WERSJA_APLIKACJI)
    strona = pomoce.zbuduj_strone()
    page = strona.page
    monkeypatch.setattr(type(page), "run_task", lambda self, *a, **k: None)
    main.main(page)

    utils.przejdz(page, "/do-zrobienia/wykonane")

    assert type(page.views[-1]).__name__ == "DoZrobieniaView" and page.views[-1]._podzakladka() == WYKONANE
