"""Przypomnienie o odczycie licznika (katalog: U-20).

Interwały podzespołów, zasięg na baku i zużycie opon liczą się z JEDNEJ liczby —
ostatniego znanego przebiegu. Miesiąc bez żadnego wpisu, który ją niesie
(tankowanie, wizyta, wpis serwisowy, odczyt), to miesiąc, o który wszystkie te
prognozy są w tyle. Tu pilnujemy konsekwencji tej jednej liczby:

1. **Dzwonek** prosi o stan licznika po progu z Ustawień (domyślnie 30 dni)
   i znowu po każdym takim okresie ciszy — a drzemka trwa tyle, ile wybrano.
2. **Nagłówek auta, zakładka Serwis i Historia licznika** mówią „sprzed N dni”
   tam, gdzie się tę liczbę czyta.
3. Porównanie pojazdów i kondycja przypomnienia NIE liczą: mówi o danych,
   nie o aucie.
"""

from datetime import date, timedelta

import flet as ft
import pytest

import db
import pomoce
import utils


def dni_temu(dni):
    return (date.today() - timedelta(days=dni)).strftime("%d.%m.%Y")


def iso_dni_temu(dni):
    return (date.today() - timedelta(days=dni)).isoformat()


def auto(nazwa="Licznik", **pola):
    kolumny = {"nazwa": nazwa, "typ_paliwa": "Benzyna", "status": db.STATUS_POJAZDU_AKTYWNY,
               "rola_wspoldzielenia": db.ROLA_WLASCICIEL}
    kolumny.update(pola)
    with db.polacz_baze() as conn:
        kursor = conn.execute(
            f"INSERT INTO samochody ({', '.join(kolumny)}) VALUES ({', '.join('?' for _ in kolumny)})",
            list(kolumny.values()))
        return kursor.lastrowid


def odczyt(auto_id, dni, przebieg):
    with db.polacz_baze() as conn:
        conn.execute("INSERT INTO odczyty_przebiegu (auto_id, data, przebieg, zrodlo) VALUES (?,?,?,?)",
                     (auto_id, dni_temu(dni), przebieg, db.ZRODLO_ODCZYTU_DOMYSLNE))


def auto_z_licznikiem(dni_od_ostatniego, nazwa="Licznik", **pola):
    """Dwa odczyty 60 dni od siebie i 2 400 km różnicy — średnio 40 km/dzień;
    ostatni sprzed `dni_od_ostatniego` dni, na 102 400 km."""
    auto_id = auto(nazwa, **pola)
    odczyt(auto_id, dni_od_ostatniego + 60, 100000)
    odczyt(auto_id, dni_od_ostatniego, 102400)
    return auto_id


def przypomnienia(auto_id, **argumenty):
    return [p for p in db.pobierz_powiadomienia(auto_id, **argumenty) if p["typ"] == "licznik"]


def kontrolki(kontrolka, klasa=ft.Control):
    """Całe poddrzewo — także pasek aplikacji, kafle list i kawałki wierszy."""
    znalezione, do_odwiedzenia, widziane = [], [kontrolka], set()
    while do_odwiedzenia:
        biezaca = do_odwiedzenia.pop(0)
        if id(biezaca) in widziane:
            continue
        widziane.add(id(biezaca))
        if isinstance(biezaca, klasa):
            znalezione.append(biezaca)
        for nazwa in ("controls", "content", "title", "subtitle", "leading", "trailing", "actions", "appbar"):
            wartosc = getattr(biezaca, nazwa, None)
            if isinstance(wartosc, (list, tuple)):
                do_odwiedzenia.extend(w for w in wartosc if isinstance(w, ft.Control))
            elif isinstance(wartosc, ft.Control):
                do_odwiedzenia.append(wartosc)
    return znalezione


def napisy(kontrolka):
    return [str(t.value) for t in kontrolki(kontrolka, ft.Text) if t.value]


def napisy_przyciskow(kontrolka):
    return [str(p.content) for p in kontrolki(kontrolka, ft.TextButton) if isinstance(p.content, str)]


def zbuduj(nazwa_klasy, auto_id, zakladka=None):
    stan = pomoce.stan_aplikacji(auto_id, "Licznik")
    if zakladka is not None:
        stan.zakladka = zakladka
    return pomoce.zbuduj_widok(pomoce.klasy_widokow()[nazwa_klasy], pomoce.zbuduj_strone(), stan)


# ============================================================================
#  1. KIEDY DZWONEK PROSI O STAN LICZNIKA
# ============================================================================

@pytest.mark.parametrize("dni, jest", [(0, False), (29, False), (30, True), (45, True)])
def test_przypomnienie_od_progu(baza, dni, jest):
    assert bool(przypomnienia(auto_z_licznikiem(dni))) is jest


def test_przypomnienie_ma_klucz_okresu_i_klucz_cyklu(baza):
    (p,) = przypomnienia(auto_z_licznikiem(45))

    assert (p["tytul"], p["status"], p["trasa"]) == ("Odczyt licznika", "pilne", "/przebieg")
    assert p["klucz"] == f"licznik:{iso_dni_temu(45)}:1"
    assert db.klucz_drzemki(p) == f"licznik:{iso_dni_temu(45)}"


@pytest.mark.parametrize("zrodlo", ["tankowanie", "wizyta", "serwis", "odczyt"])
def test_kazdy_wpis_z_przebiegiem_konczy_cisze(baza, zrodlo):
    """Kto tankuje co tydzień, ma aktualny licznik — przypomnienie nie może
    wołać tylko dlatego, że nikt nie wpisał osobnego odczytu."""
    auto_id = auto_z_licznikiem(90)
    data = dni_temu(3)
    with db.polacz_baze() as conn:
        if zrodlo == "tankowanie":
            conn.execute("INSERT INTO tankowania (auto_id, data, przebieg, litry, kwota) VALUES (?,?,?,?,?)",
                         (auto_id, data, 103000, 40.0, 250.0))
        elif zrodlo == "wizyta":
            conn.execute("INSERT INTO wizyty (auto_id, data, przebieg, wykonawca) VALUES (?,?,?,?)",
                         (auto_id, data, 103000, "Warsztat"))
        elif zrodlo == "serwis":
            zadanie = conn.execute("INSERT INTO zadania (auto_id, nazwa) VALUES (?,?)", (auto_id, "Olej")).lastrowid
            conn.execute("INSERT INTO historia (zadanie_id, data, przebieg) VALUES (?,?,?)",
                         (zadanie, data, 103000))
        else:
            conn.execute("INSERT INTO odczyty_przebiegu (auto_id, data, przebieg) VALUES (?,?,?)",
                         (auto_id, data, 103000))

    assert przypomnienia(auto_id) == []
    assert db.swiezosc_licznika(auto_id)["dni"] == 3


def test_cisza_liczona_z_tego_samego_wpisu_co_historia_licznika(baza):
    auto_id = auto_z_licznikiem(50)
    with db.polacz_baze() as conn:
        conn.execute("INSERT INTO wizyty (auto_id, data, przebieg, wykonawca) VALUES (?,?,?,?)",
                     (auto_id, dni_temu(41), 102900, "Warsztat"))

    assert db.swiezosc_licznika(auto_id)["dni"] == 41
    assert db.podsumowanie_historii_przebiegu(auto_id)["dni_od_ostatniego"] == 41


def test_auto_bez_przebiegu_dostaje_przypomnienie_od_razu(baza):
    (p,) = przypomnienia(auto("Nowe"))

    assert p["klucz"] == db.klucz_drzemki(p) == "licznik:brak"
    assert p["linie_opisu"][0] == "Brak jakiegokolwiek stanu licznika"


def test_sprzedane_i_podglad_nie_dostaja_prosby(baza):
    sprzedane = auto_z_licznikiem(45, "Sprzedane", status=db.STATUS_POJAZDU_SPRZEDANY)
    podglad = auto_z_licznikiem(45, "Cudze", rola_wspoldzielenia=db.ROLA_PODGLAD)

    assert przypomnienia(sprzedane) == [] and przypomnienia(podglad) == []
    assert db.swiezosc_licznika(sprzedane)["nieswiezy"] is False
    assert db.swiezosc_licznika(podglad)["nieswiezy"] is True, "podgląd widzi ostrzeżenie, tylko o nic go nie prosimy"


@pytest.mark.parametrize("ustawienie, dni, jest", [(0, 400, False), (14, 20, True), (60, 45, False)])
def test_prog_z_ustawien(baza, ustawienie, dni, jest):
    db.zapisz_dni_przypomnienia_o_odczycie(ustawienie)

    assert bool(przypomnienia(auto_z_licznikiem(dni))) is jest


@pytest.mark.parametrize("zapisane", ["45", "abc", ""])
def test_ustawienie_spoza_listy_wraca_do_miesiaca(baza, zapisane):
    db.zapisz_ustawienie("dni_przypomnienia_o_odczycie", zapisane)

    assert db.pobierz_dni_przypomnienia_o_odczycie() == db.DNI_PRZYPOMNIENIA_O_ODCZYCIE == 30


def test_opis_mowi_od_kiedy_z_czego_i_ile_moglo_przybyc(baza):
    (p,) = przypomnienia(auto_z_licznikiem(40))
    pierwsza, druga = p["linie_opisu"]

    assert pierwsza == "Brak nowego przebiegu od 40 dni"
    assert druga == (f"Prognozy liczą z {utils.formatuj_liczba(102400, 0)} km ({dni_temu(40)})"
                     f" — mogło przybyć ok. {utils.formatuj_liczba(1600, 0)} km")
    assert p["opis"] == utils.polacz_linie_opisu(p["linie_opisu"])


def test_zdanie_stoi_na_liczbie_z_ktorej_licza_prognozy(baza):
    """Tego samego dnia ręczny odczyt wygrywa z tankowaniem — to z niego liczą
    się interwały, więc to on stoi w zdaniu, a nie wyższa liczba z paragonu."""
    auto_id = auto_z_licznikiem(40)
    with db.polacz_baze() as conn:
        conn.execute("INSERT INTO tankowania (auto_id, data, przebieg, litry, kwota) VALUES (?,?,?,?,?)",
                     (auto_id, dni_temu(40), 102450, 40.0, 250.0))

    assert db.swiezosc_licznika(auto_id)["przebieg"] == db.pobierz_aktualny_przebieg(auto_id) == 102400


def test_przypomnienie_stoi_za_prawdziwymi_terminami(baza):
    """Kafel „Termin” pokazuje pierwsze powiadomienie — polisa za pięć dni ma
    stać nad licznikiem."""
    auto_id = auto_z_licznikiem(45, oc_data=(date.today() + timedelta(days=5)).strftime("%d.%m.%Y"))

    assert [p["typ"] for p in db.pobierz_powiadomienia(auto_id)] == ["dokument", "licznik"]


# ============================================================================
#  2. OKRESY CISZY I DRZEMKA
# ============================================================================
# Przestawienie progu w Ustawieniach to najprostsza granica okresu bez cofania
# zegara: 45 dni przy progu 30 to okres 1, przy progu 14 — okres 3.

@pytest.mark.parametrize("dni, okres", [(29, 0), (30, 1), (59, 1), (60, 2), (95, 3)])
def test_okres_ciszy(baza, dni, okres):
    auto_id = auto_z_licznikiem(0)

    assert db.swiezosc_licznika(auto_id, dzis=date.today() + timedelta(days=dni))["okres"] == okres


def test_kolejny_okres_ciszy_zapala_odznake_znowu(baza):
    auto_id = auto_z_licznikiem(45)
    db.oznacz_powiadomienia_jako_widziane(auto_id, db.pobierz_powiadomienia(auto_id))
    assert db.niewidziane_powiadomienia(db.pobierz_powiadomienia(auto_id),
                                        db.pobierz_widziane_powiadomienia(auto_id)) == []

    db.zapisz_dni_przypomnienia_o_odczycie(14)
    teraz = db.pobierz_powiadomienia(auto_id)

    assert [p["klucz"] for p in teraz] == [f"licznik:{iso_dni_temu(45)}:3"]
    assert db.niewidziane_powiadomienia(teraz, db.pobierz_widziane_powiadomienia(auto_id)) == teraz


def test_drzemka_trwa_mimo_nowego_okresu(baza):
    auto_id = auto_z_licznikiem(45)
    (p,) = przypomnienia(auto_id)
    db.odloz_powiadomienie(auto_id, db.klucz_drzemki(p), 30, p["tytul"])

    db.zapisz_dni_przypomnienia_o_odczycie(14)

    assert przypomnienia(auto_id) == []
    assert przypomnienia(auto_id, pomin_wyciszone=False)
    (odlozone,) = db.pobierz_odlozone_powiadomienia(auto_id)
    assert odlozone["nadal_aktualne"] and odlozone["tytul"] == "Odczyt licznika"


def test_nowy_wpis_zaczyna_cykl_bez_starej_drzemki(baza):
    """Drzemka dotyczyła ciszy po TAMTYM wpisie. Nowy wpis, po którym znowu
    minął miesiąc, to już nowa sprawa — nie może jej przykryć stara drzemka."""
    auto_id = auto_z_licznikiem(100)
    (p,) = przypomnienia(auto_id)
    db.odloz_powiadomienie(auto_id, db.klucz_drzemki(p), 90, p["tytul"])
    assert przypomnienia(auto_id) == []

    odczyt(auto_id, 35, 104000)

    (nowe,) = przypomnienia(auto_id)
    assert nowe["klucz"] == f"licznik:{iso_dni_temu(35)}:1"
    (stare,) = db.pobierz_odlozone_powiadomienia(auto_id)
    assert not stare["nadal_aktualne"]


# ============================================================================
#  3. CZEGO PRZYPOMNIENIE NIE RUSZA
# ============================================================================

def test_porownanie_i_kondycja_nie_licza_przypomnienia(baza):
    auto_id = auto_z_licznikiem(45)
    assert przypomnienia(auto_id)

    dane = db.pobierz_dane_do_porownania(auto_id)
    assert (dane["pilne"], dane["przeterminowane"]) == (0, 0)

    z_przypomnieniem = db.pobierz_rozbicie_kondycji(auto_id)
    db.zapisz_dni_przypomnienia_o_odczycie(0)
    assert db.pobierz_rozbicie_kondycji(auto_id) == z_przypomnieniem


# ============================================================================
#  4. EKRANY
# ============================================================================

def test_panel_wpisuje_stan_i_odklada_pod_kluczem_cyklu(baza, monkeypatch):
    auto_id = auto_z_licznikiem(45)
    arkusze, okna, znaczniki = [], [], []
    monkeypatch.setattr(utils.powiadomienia, "otworz_dno", lambda strona, arkusz: arkusze.append(arkusz))
    monkeypatch.setattr(utils.powiadomienia, "dialog_odczytu_przebiegu",
                        lambda strona, a, po_zapisie=None: okna.append((a, po_zapisie)))
    monkeypatch.setattr(utils.powiadomienia, "znacznik_wykonania",
                        lambda strona, tekst="Gotowe", po_zakonczeniu=None, pauza=0.7:
                        znaczniki.append(tekst) or ft.Text(tekst))
    monkeypatch.setattr(utils.powiadomienia, "przejdz", lambda *a, **k: None)
    monkeypatch.setattr(utils.powiadomienia, "pokaz_komunikat", lambda *a, **k: None)

    utils.pokaz_panel_powiadomien(pomoce.zbuduj_strone().page, pomoce.stan_aplikacji(auto_id))

    (kafel,) = [k for k in kontrolki(arkusze[0].content.content, ft.ListTile)
                if k.title is not None and "Odczyt licznika" in napisy(k.title)]
    wpisz, drzemka = kafel.trailing.controls
    assert wpisz.content == "Wpisz stan"
    assert kafel.leading.icon == ft.Icons.SPEED

    wpisz.on_click(None)
    ((dla_auta, po_zapisie),) = okna
    assert dla_auta == auto_id
    po_zapisie()
    assert znaczniki == ["Zapisano"] and kafel.trailing.value == "Zapisano"

    drzemka.items[0].on_click(None)
    assert db.pobierz_wyciszone_klucze(auto_id) == {f"licznik:{iso_dni_temu(45)}"}


def test_naglowek_mowi_sprzed_ilu_dni(baza):
    stary = zbuduj("MainView", auto_z_licznikiem(45))
    swiezy = zbuduj("MainView", auto_z_licznikiem(2, "Świeży"))

    kawalki = [k for t in kontrolki(stary, ft.Text) for k in (t.spans or [])]
    (dopisek,) = [k for k in kawalki if k.text == "sprzed 45 dni"]
    assert dopisek.style.color == utils.KOLOR_STATUS["warning"]
    assert not [k for t in kontrolki(swiezy, ft.Text) for k in (t.spans or []) if "sprzed" in str(k.text)]


def dodaj_podzespol(auto_id, **pola):
    kolumny = ["auto_id", "nazwa"] + list(pola)
    with db.polacz_baze() as conn:
        conn.execute(f"INSERT INTO zadania ({', '.join(kolumny)}) VALUES ({', '.join('?' for _ in kolumny)})",
                     [auto_id, "Olej"] + list(pola.values()))


@pytest.mark.parametrize("rola, przycisk", [(db.ROLA_WLASCICIEL, True), (db.ROLA_PODGLAD, False)])
def test_zakladka_serwis_ostrzega_nad_kartami(baza, rola, przycisk):
    auto_id = auto_z_licznikiem(45, rola_wspoldzielenia=rola)
    dodaj_podzespol(auto_id, interwal_km=15000, przebieg=100000, data=dni_temu(100))

    widok = zbuduj("MainView", auto_id, zakladka=1)

    assert "Prognozy km liczone z licznika sprzed 45 dni" in napisy(widok)
    assert ("Wpisz stan" in napisy_przyciskow(widok)) is przycisk


def test_zakladka_serwis_bez_interwalow_km_milczy(baza):
    auto_id = auto_z_licznikiem(45)
    dodaj_podzespol(auto_id, interwal_miesiace=12, data=dni_temu(100))

    assert not [n for n in napisy(zbuduj("MainView", auto_id, zakladka=1)) if n.startswith("Prognozy km")]


def test_historia_licznika_ma_pasek_z_przyciskiem(baza):
    stary = zbuduj("OdczytyPrzebieguView", auto_z_licznikiem(45))
    swiezy = zbuduj("OdczytyPrzebieguView", auto_z_licznikiem(2, "Świeży"))

    assert "Czas na odczyt — prognozy km liczą z licznika sprzed 45 dni" in napisy(stary)
    assert "Dodaj odczyt" in napisy_przyciskow(stary)
    assert not [n for n in napisy(swiezy) if n.startswith("Czas na odczyt")]


def test_ustawienia_zapisuja_prog_przypomnienia(baza, monkeypatch):
    monkeypatch.setattr(utils, "przejdz", lambda *a, **k: None)
    monkeypatch.setattr(utils, "pokaz_komunikat", lambda *a, **k: None)
    monkeypatch.setattr(utils, "zastosuj_motywy", lambda *a, **k: None)
    # Strona trzymana w zmiennej: zapis woła page.update(), a sesja testowej
    # strony żyje tylko tak długo, jak jej właściciel.
    strona = pomoce.zbuduj_strone()
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["UstawieniaView"], strona,
                                pomoce.stan_aplikacji(auto_z_licznikiem(2), "Licznik"))
    assert widok.e_przypomnienie_licznika.value == "30"

    widok.e_przypomnienie_licznika.value = "60"
    assert widok._czy_zmieniono()
    widok.zapisz(None)

    assert db.pobierz_dni_przypomnienia_o_odczycie() == 60
