"""Powiadomienia: dwa liczniki interwału, jeden termin, „widziane” per powiadomienie.

Trzy zmiany, które pilnują się nawzajem:

1. **Oba liczniki zawsze.** Interwał „15 000 km albo 12 miesięcy” to dwa liczniki
   biegnące naraz. Karta podzespołu pokazywała je obok siebie bez słowa o tym,
   który skończy się pierwszy, a powiadomienie — tylko ten, który akurat wszedł
   w próg. „3 000 km zapasu” przy dwóch tygodniach do terminu znaczy co innego
   niż przy pół roku.
2. **Jeden termin wynikowy.** Podzespół zgłaszał się z dwóch niezależnych powodów
   sklejonych w jedno zdanie i datę składał z nich sam użytkownik.
3. **Widziane per powiadomienie.** Sygnatura całego zestawu zapalała odznakę na
   wszystkim przy zmianie jednego wpisu, a nowe powiadomienie wśród pięciu
   przeczytanych gasło tym samym kliknięciem co one.
"""

from datetime import date, timedelta

import flet as ft
import pytest

import db
import pomoce
import utils

DZIS = date(2026, 9, 15)


def zadanie(**pola):
    """Wiersz `zadania` bez niczego ustawionego — test dopisuje tylko to, o co pyta."""
    wiersz = {"interwal_km": None, "interwal_miesiace": None, "data": None,
              "przebieg": None, "prog_km": None, "prog_dni": None}
    wiersz.update(pola)
    return wiersz


def dni_temu(dni, dzis=DZIS):
    return (dzis - timedelta(days=dni)).strftime("%d.%m.%Y")


def stan(wiersz, przebieg, sredni=None, prog_km=1000, prog_dni=30):
    return db.oblicz_stan_interwalu(wiersz, przebieg, sredni, prog_km=prog_km, prog_dni=prog_dni, dzis=DZIS)


def teksty(kontrolka):
    """Wszystkie napisy z poddrzewa w kolejności czytania — w głąb, od lewej,
    więc etykieta nad wartością wypada przed nią."""
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


def kontrolki(kontrolka, klasa):
    znalezione = []
    do_odwiedzenia = [kontrolka]
    while do_odwiedzenia:
        biezaca = do_odwiedzenia.pop(0)
        if isinstance(biezaca, klasa):
            znalezione.append(biezaca)
        for nazwa in ("controls", "content", "title", "subtitle"):
            wartosc = getattr(biezaca, nazwa, None)
            if isinstance(wartosc, (list, tuple)):
                do_odwiedzenia.extend(w for w in wartosc if isinstance(w, ft.Control))
            elif isinstance(wartosc, ft.Control):
                do_odwiedzenia.append(wartosc)
    return znalezione


# ============================================================================
#  1. DWA LICZNIKI, JEDEN TERMIN — sama arytmetyka
# ============================================================================

def test_oba_liczniki_sa_liczone_takze_poza_progiem():
    """Czas daleko od progu nadal jest licznikiem — to on mówi, ile zapasu
    zostaje po kilometrach."""
    wynik = stan(zadanie(interwal_km=15000, interwal_miesiace=12, data=dni_temu(150), przebieg=100000),
                 przebieg=114360, sredni=30.0)

    assert wynik["km"]["zostalo"] == 640 and wynik["km"]["status"] == "pilne"
    assert wynik["czas"]["zostalo"] == 216 and wynik["czas"]["status"] == "ok"
    assert wynik["status"] == "pilne"


@pytest.mark.parametrize("przebieg, sredni, oczekiwane", [
    (114360, 30.0, "km"),     # 640 km przy 30 km/dzień to ~21 dni; czas: 216 dni
    (114360, 2.0, "czas"),    # te same 640 km przy 2 km/dzień to ~320 dni
])
def test_pierwszy_jest_licznik_z_wczesniejsza_prognoza(przebieg, sredni, oczekiwane):
    wynik = stan(zadanie(interwal_km=15000, interwal_miesiace=12, data=dni_temu(150), przebieg=100000),
                 przebieg=przebieg, sredni=sredni)

    assert wynik["pierwsze"] == oczekiwane


def test_bez_sredniej_rozstrzyga_zuzyta_czesc_interwalu():
    """Bez średniego przebiegu nie ma daty dla kilometrów — porównanie zużytych
    części interwału to wtedy ta sama prognoza, tylko tempem jazdy od wymiany."""
    wiersz = zadanie(interwal_km=15000, interwal_miesiace=12, data=dni_temu(300), przebieg=100000)

    km_dalej = stan(wiersz, przebieg=110000)      # 67% kilometrów, 82% czasu
    km_blizej = stan(wiersz, przebieg=114500)     # 97% kilometrów, 82% czasu

    assert km_dalej["km"]["dni"] is None
    assert km_dalej["pierwsze"] == "czas"
    assert km_blizej["pierwsze"] == "km"


def test_licznik_po_terminie_jest_pierwszy():
    wiersz = zadanie(interwal_km=15000, interwal_miesiace=12, data=dni_temu(100), przebieg=100000)

    wynik = stan(wiersz, przebieg=116200, sredni=50.0)

    assert wynik["pierwsze"] == "km"
    assert wynik["status"] == "przeterminowane"
    assert wynik["czas"]["status"] == "ok"


def test_status_to_najgorszy_z_licznikow_nawet_gdy_pierwszy_jest_spokojny():
    """Kilometry skończą się pierwsze, ale jeszcze poza swoim progiem — a czas już
    wszedł w swoje okno. Termin, który przyjdzie wcześniej, nie może zasłaniać
    tego, o którym użytkownik kazał sobie przypomnieć z wyprzedzeniem."""
    wiersz = zadanie(interwal_km=15000, interwal_miesiace=12, data=dni_temu(320), przebieg=100000)

    wynik = stan(wiersz, przebieg=113000, sredni=50.0, prog_km=1000, prog_dni=60)

    assert wynik["pierwsze"] == "km"          # 2 000 km przy 50 km/dzień to 40 dni, czas: 46 dni
    assert wynik["km"]["status"] == "ok"
    assert wynik["czas"]["status"] == "pilne"
    assert wynik["status"] == "pilne"


def test_prog_wlasny_podzespolu_wygrywa_z_domyslnym():
    wiersz = zadanie(interwal_km=30000, przebieg=100000, prog_km=5000)

    assert stan(wiersz, przebieg=126500, prog_km=1000)["status"] == "pilne"
    assert stan(zadanie(interwal_km=30000, przebieg=100000), przebieg=126500, prog_km=1000)["status"] == "ok"


def test_bez_danych_nie_ma_licznikow():
    wynik = stan(zadanie(interwal_km=15000, interwal_miesiace=12), przebieg=120000, sredni=40.0)

    assert wynik == {"km": None, "czas": None, "pierwsze": None, "status": None}


def test_zdania_mowia_co_przyjdzie_pierwsze(baza):
    wynik = stan(zadanie(interwal_km=15000, interwal_miesiace=12, data=dni_temu(346), przebieg=100000),
                 przebieg=112000, sredni=10.0)

    linie = utils.linie_opisu_interwalu(wynik)

    assert linie[0].startswith("Zostało 20 dni")
    assert linie[1].startswith("Limit km dopiero za 3 000 km")
    assert utils.polacz_linie_opisu(linie).startswith("Zostało 20 dni (") and " • limit km dopiero" in utils.polacz_linie_opisu(linie)


@pytest.mark.parametrize("dni, oczekiwane", [
    (1, "Został 1 dzień"),
    (3, "Zostały 3 dni"),
    (12, "Zostało 12 dni"),
    (22, "Zostały 22 dni"),
])
def test_zdanie_o_czasie_zgadza_sie_z_liczba(dni, oczekiwane):
    wynik = stan(zadanie(interwal_miesiace=12, data=dni_temu(366 - dni)), przebieg=0)

    assert utils.linie_opisu_interwalu(wynik)[0].startswith(oczekiwane)


# ============================================================================
#  2. POWIADOMIENIE Z BAZY — jedno na podzespół
# ============================================================================

def pojazd_z_przebiegiem(nazwa="Licznik", dni_miedzy=100, km_miedzy=4000, przebieg_dzis=114000):
    """Pojazd bez żadnych innych wpisów: dwa odczyty licznika dają znaną średnią
    (40 km/dzień przy wartościach domyślnych) i znany przebieg dzisiaj."""
    dzis = date.today()
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO samochody (nazwa, typ_paliwa, status, rola_wspoldzielenia) VALUES (?,?,?,?)",
                  (nazwa, "Benzyna", db.STATUS_POJAZDU_AKTYWNY, db.ROLA_WLASCICIEL))
        auto_id = c.lastrowid
        for dni, przebieg in ((dni_miedzy, przebieg_dzis - km_miedzy), (0, przebieg_dzis)):
            c.execute("INSERT INTO odczyty_przebiegu (auto_id, data, przebieg, zrodlo) VALUES (?,?,?,?)",
                      (auto_id, dni_temu(dni, dzis), przebieg, db.ZRODLO_ODCZYTU_DOMYSLNE))
    return auto_id


def dodaj_podzespol(auto_id, nazwa, **pola):
    kolumny = ["auto_id", "nazwa"] + list(pola)
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute(f"INSERT INTO zadania ({', '.join(kolumny)}) VALUES ({', '.join('?' for _ in kolumny)})",
                  [auto_id, nazwa] + list(pola.values()))
        return c.lastrowid


def test_podzespol_zglasza_sie_raz_z_licznikiem_pierwszym_na_gorze(baza):
    """Oba liczniki w swoich progach — kiedyś dwa powody w jednym zdaniu, dziś
    jeden termin: najpierw czas (20 dni), potem kilometry (1 000 km ≈ 25 dni)."""
    auto_id = pojazd_z_przebiegiem()
    zid = dodaj_podzespol(auto_id, "Olej", interwal_km=15000, interwal_miesiace=12,
                          przebieg=100000, data=dni_temu(346, date.today()))

    wlasne = [p for p in db.pobierz_powiadomienia(auto_id, prog_km=1000, prog_dni=30)
              if p["klucz"] == f"podzespol:{zid}"]

    assert len(wlasne) == 1
    powiadomienie = wlasne[0]
    assert powiadomienie["status"] == "pilne"
    assert len(powiadomienie["linie_opisu"]) == 2
    assert powiadomienie["linie_opisu"][0].startswith("Zostało 20 dni")
    assert powiadomienie["linie_opisu"][1].startswith("Limit km dopiero za 1 000 km")
    assert powiadomienie["opis"] == utils.polacz_linie_opisu(powiadomienie["linie_opisu"])


def test_licznik_spoza_progu_stoi_w_powiadomieniu(baza):
    """Kilometry w progu, czas daleko — powiadomienie i tak mówi, ile zostaje czasu."""
    auto_id = pojazd_z_przebiegiem()
    dodaj_podzespol(auto_id, "Rozrząd", interwal_km=15000, interwal_miesiace=48,
                    przebieg=99500, data=dni_temu(200, date.today()))

    (powiadomienie,) = [p for p in db.pobierz_powiadomienia(auto_id, prog_km=1000, prog_dni=30)
                        if p["typ"] == "podzespol"]

    assert powiadomienie["linie_opisu"][0].startswith("Zostało 500 km (")
    assert powiadomienie["linie_opisu"][1].startswith("Termin dopiero ")


def test_spokojny_podzespol_nie_zglasza_sie(baza):
    auto_id = pojazd_z_przebiegiem()
    dodaj_podzespol(auto_id, "Klocki", interwal_km=60000, interwal_miesiace=48,
                    przebieg=110000, data=dni_temu(100, date.today()))

    assert [p for p in db.pobierz_powiadomienia(auto_id) if p["typ"] == "podzespol"] == []


def test_zakladka_serwis_i_powiadomienie_licza_to_samo(baza):
    """Karta czyta wiersz jako słownik, powiadomienie jako sqlite3.Row — oba mają
    dać ten sam stan, bo liczy go jedna funkcja."""
    import sqlite3

    auto_id = pojazd_z_przebiegiem()
    zid = dodaj_podzespol(auto_id, "Olej", interwal_km=15000, interwal_miesiace=12,
                          przebieg=100000, data=dni_temu(346, date.today()))
    with db.polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        wiersz = conn.execute("SELECT * FROM zadania WHERE id=?", (zid,)).fetchone()

    argumenty = (db.pobierz_aktualny_przebieg(auto_id), db.oblicz_sredni_dzienny_przebieg(auto_id))
    assert db.oblicz_stan_interwalu(wiersz, *argumenty) == db.oblicz_stan_interwalu(dict(wiersz), *argumenty)


# ============================================================================
#  3. KARTA PODZESPOŁU — oba liczniki obok siebie
# ============================================================================

def test_karta_ma_oba_liczniki_i_znacznik_przy_pierwszym(baza):
    wynik = stan(zadanie(interwal_km=15000, interwal_miesiace=12, data=dni_temu(150), przebieg=100000),
                 przebieg=114360, sredni=30.0)

    wiersz = utils.liczniki_interwalu(wynik)
    kolumna_km, kolumna_czasu = wiersz.controls

    assert teksty(kolumna_km)[:3] == ["Kilometry", "najpierw", "640 km"]
    assert "najpierw" not in teksty(kolumna_czasu)
    assert teksty(kolumna_czasu)[:2] == ["Czas", "~7 mies."]
    assert len(kontrolki(wiersz, ft.ProgressBar)) == 2, "każdy licznik ma własny pasek zużycia"


def test_kolejnosc_kolumn_jest_stala_a_znacznik_wedruje(baza):
    """Kilometry zawsze z lewej — na liście kart oko ma wiedzieć, gdzie czego
    szukać. O kolejności terminów mówi znacznik, nie miejsce."""
    wynik = stan(zadanie(interwal_km=15000, interwal_miesiace=12, data=dni_temu(346), przebieg=100000),
                 przebieg=112000, sredni=10.0)

    kolumna_km, kolumna_czasu = utils.liczniki_interwalu(wynik).controls

    assert teksty(kolumna_km)[0] == "Kilometry" and "najpierw" not in teksty(kolumna_km)
    assert teksty(kolumna_czasu)[:2] == ["Czas", "najpierw"]


def test_jeden_licznik_nie_ma_znacznika(baza):
    wynik = stan(zadanie(interwal_km=15000, przebieg=100000), przebieg=114700, sredni=25.0)

    wiersz = utils.liczniki_interwalu(wynik)

    assert len(wiersz.controls) == 1
    assert "najpierw" not in teksty(wiersz)


def test_bez_licznikow_nie_ma_wiersza():
    assert utils.liczniki_interwalu(stan(zadanie(interwal_km=15000), przebieg=100000)) is None


def test_zakladka_serwis_rysuje_oba_liczniki(baza):
    auto_id = pojazd_z_przebiegiem()
    dodaj_podzespol(auto_id, "Olej", interwal_km=15000, interwal_miesiace=12,
                    przebieg=100000, data=dni_temu(346, date.today()))
    dodaj_podzespol(auto_id, "Wycieraczki")
    stan_aplikacji = pomoce.stan_aplikacji(auto_id, "Licznik")
    stan_aplikacji.zakladka = 1

    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(), stan_aplikacji)
    napisy = teksty(widok.lista_kart_serwis)

    assert napisy.count("najpierw") == 1
    assert "Kilometry" in napisy and "Czas" in napisy
    assert "Brak interwału" in napisy, "podzespół bez interwału nadal mówi, czego mu brakuje"


# ============================================================================
#  4. WIDZIANE — per powiadomienie, zapisane w bazie
# ============================================================================

def powiadomienie(klucz, status="pilne", opis="Zostało 12 dni", typ="dokument"):
    return {"typ": typ, "tytul": klucz, "opis": opis, "status": status, "klucz": klucz}


def test_zmiana_tresci_nie_robi_z_powiadomienia_nowego(baza):
    auto_id = pojazd_z_przebiegiem()
    db.oznacz_powiadomienia_jako_widziane(auto_id, [powiadomienie("dokument:oc", opis="Zostało 12 dni")])

    jutro = [powiadomienie("dokument:oc", opis="Zostało 11 dni")]

    assert db.niewidziane_powiadomienia(jutro, db.pobierz_widziane_powiadomienia(auto_id)) == []


def test_nowe_wsrod_widzianych_jest_jedynym_nowym(baza):
    auto_id = pojazd_z_przebiegiem()
    znane = [powiadomienie(f"podzespol:{i}") for i in range(5)]
    db.oznacz_powiadomienia_jako_widziane(auto_id, znane)

    nowe = db.niewidziane_powiadomienia(
        znane + [powiadomienie("dokument:przeglad", status="przeterminowane")],
        db.pobierz_widziane_powiadomienia(auto_id),
    )

    assert [p["klucz"] for p in nowe] == ["dokument:przeglad"]


def test_pogorszenie_statusu_robi_nowe_a_poprawa_nie(baza):
    auto_id = pojazd_z_przebiegiem()
    db.oznacz_powiadomienia_jako_widziane(auto_id, [powiadomienie("podzespol:1", "pilne"),
                                                    powiadomienie("podzespol:2", "przeterminowane")])
    widziane = db.pobierz_widziane_powiadomienia(auto_id)

    nowe = db.niewidziane_powiadomienia([powiadomienie("podzespol:1", "przeterminowane"),
                                         powiadomienie("podzespol:2", "pilne")], widziane)

    assert [p["klucz"] for p in nowe] == ["podzespol:1"]


def test_powod_ktory_zniknal_wraca_jako_nowy(baza):
    """Wymiana zapisana, polisa odnowiona, drzemka — obejrzenie idzie w niepamięć,
    bo kiedy powód wróci, to już jest inna sprawa niż ta sprzed miesięcy."""
    auto_id = pojazd_z_przebiegiem()
    db.oznacz_powiadomienia_jako_widziane(auto_id, [powiadomienie("dokument:oc"), powiadomienie("magazyn:3")])

    assert db.przytnij_widziane_powiadomienia(auto_id, [powiadomienie("magazyn:3")]) == {"magazyn:3": "pilne"}
    assert db.pobierz_widziane_powiadomienia(auto_id) == {"magazyn:3": "pilne"}, "przycięcie ma być zapisane"
    assert [p["klucz"] for p in db.niewidziane_powiadomienia(
        [powiadomienie("dokument:oc"), powiadomienie("magazyn:3")],
        db.pobierz_widziane_powiadomienia(auto_id),
    )] == ["dokument:oc"]


def test_oznaczenie_zwraca_to_co_bylo_nowe(baza):
    auto_id = pojazd_z_przebiegiem()
    db.oznacz_powiadomienia_jako_widziane(auto_id, [powiadomienie("dokument:oc")])

    nowe = db.oznacz_powiadomienia_jako_widziane(auto_id, [powiadomienie("dokument:oc"), powiadomienie("cykliczny:7")])

    assert nowe == {"cykliczny:7"}
    assert db.oznacz_powiadomienia_jako_widziane(auto_id, [powiadomienie("dokument:oc"), powiadomienie("cykliczny:7")]) == set()


def test_widziane_osobno_dla_kazdego_pojazdu(baza):
    """Klucz „dokument:oc” jest ten sam w każdym aucie — obejrzenie jednego nie
    może zgasić drugiego."""
    pierwszy = pojazd_z_przebiegiem("Pierwszy")
    drugi = pojazd_z_przebiegiem("Drugi")
    db.oznacz_powiadomienia_jako_widziane(pierwszy, [powiadomienie("dokument:oc")])

    assert db.pobierz_widziane_powiadomienia(drugi) == {}


def test_uszkodzony_zapis_nie_blokuje_dzwonka(baza):
    auto_id = pojazd_z_przebiegiem()
    db.zapisz_ustawienie(db.ustawienia._klucz_widzianych_powiadomien(auto_id), "{to nie jest json")

    assert db.pobierz_widziane_powiadomienia(auto_id) == {}
    assert len(db.niewidziane_powiadomienia([powiadomienie("dokument:oc")], {})) == 1


def test_widziane_jada_z_pojazdem_do_kosza_i_wracaja(baza):
    pomoce.utworz_pojazd("Pierwszy")
    db.oznacz_powiadomienia_jako_widziane(1, [powiadomienie("dokument:oc")])
    klucz_przed = db.ustawienia._klucz_widzianych_powiadomien(1)

    wynik = db.usun_auto_do_kosza(1)
    assert db.pobierz_ustawienie(klucz_przed) is None, "obejrzenia zostały w bazie jako sierota"

    przywrocone = db.przywroc_auto_z_kosza(wynik["kosz_id"])
    assert db.pobierz_widziane_powiadomienia(przywrocone) == {"dokument:oc": "pilne"}


# ============================================================================
#  5. DZWONEK I PANEL
# ============================================================================

def pojazd_z_trzema_powiadomieniami():
    """Trzy terminy dokumentów w progu — klucze znane z góry, treść bez znaczenia."""
    auto_id = pojazd_z_przebiegiem("Dokumenty")
    dzis = date.today()
    with db.polacz_baze() as conn:
        conn.execute("UPDATE samochody SET oc_data=?, przeglad_data=?, ac_data=? WHERE id=?",
                     [(dzis + timedelta(days=d)).strftime("%d.%m.%Y") for d in (3, 5, 7)] + [auto_id])
    return auto_id


def odznaka_dzwonka(dzwonek):
    """(widoczna, napis) — albo (False, None) dla dzwonka bez powiadomień."""
    if not isinstance(dzwonek, ft.Stack):
        return False, None
    pozycja = dzwonek.controls[1]
    return bool(pozycja.visible), pozycja.content.content.value


def test_dzwonek_liczy_tylko_nowe(baza):
    auto_id = pojazd_z_trzema_powiadomieniami()
    powiadomienia = db.pobierz_powiadomienia(auto_id)
    assert len(powiadomienia) == 3
    db.oznacz_powiadomienia_jako_widziane(auto_id, powiadomienia[:2])

    dzwonek = utils.przycisk_dzwonka(pomoce.zbuduj_strone().page, pomoce.stan_aplikacji(auto_id))

    assert odznaka_dzwonka(dzwonek) == (True, "1")
    assert dzwonek.controls[0].tooltip == "3 powiadomienia, w tym 1 nowe"


def test_obejrzane_nie_zapalaja_dzwonka_po_ponownym_uruchomieniu(baza):
    """Świeży AppState to zimny start aplikacji — obejrzenie ma przetrwać."""
    auto_id = pojazd_z_trzema_powiadomieniami()
    db.oznacz_powiadomienia_jako_widziane(auto_id, db.pobierz_powiadomienia(auto_id))

    dzwonek = utils.przycisk_dzwonka(pomoce.zbuduj_strone().page, pomoce.stan_aplikacji(auto_id))

    assert odznaka_dzwonka(dzwonek) == (False, "0")
    assert dzwonek.controls[0].icon_color == ft.Colors.ON_SURFACE


def test_panel_zapisuje_obejrzenie_i_oznacza_nowe(baza, monkeypatch):
    auto_id = pojazd_z_trzema_powiadomieniami()
    powiadomienia = db.pobierz_powiadomienia(auto_id)
    db.oznacz_powiadomienia_jako_widziane(auto_id, powiadomienia[:2])
    nowy_tytul = powiadomienia[2]["tytul"]

    otwarte = []
    monkeypatch.setattr(utils.powiadomienia, "otworz_dno", lambda strona, arkusz: otwarte.append(arkusz))
    utils.pokaz_panel_powiadomien(pomoce.zbuduj_strone().page, pomoce.stan_aplikacji(auto_id))

    (arkusz,) = otwarte
    kafle = [k for k in kontrolki(arkusz.content.content, ft.ListTile) if k.title is not None]
    z_pigulka = [k for k in kafle if "nowe" in teksty(k.title)]

    assert [teksty(k.title)[0] for k in z_pigulka] == [nowy_tytul]
    assert db.niewidziane_powiadomienia(powiadomienia, db.pobierz_widziane_powiadomienia(auto_id)) == []


def test_panel_stawia_liczniki_podzespolu_w_dwoch_wierszach(baza, monkeypatch):
    auto_id = pojazd_z_przebiegiem()
    dodaj_podzespol(auto_id, "Olej", interwal_km=15000, interwal_miesiace=12,
                    przebieg=100000, data=dni_temu(346, date.today()))

    otwarte = []
    monkeypatch.setattr(utils.powiadomienia, "otworz_dno", lambda strona, arkusz: otwarte.append(arkusz))
    utils.pokaz_panel_powiadomien(pomoce.zbuduj_strone().page, pomoce.stan_aplikacji(auto_id))

    (kafel,) = [k for k in kontrolki(otwarte[0].content.content, ft.ListTile)
                if k.title is not None and "Olej" in teksty(k.title)]
    pierwszy, drugi = teksty(kafel.subtitle)

    assert pierwszy.startswith("Zostało 20 dni")
    assert drugi.startswith("Limit km dopiero")
