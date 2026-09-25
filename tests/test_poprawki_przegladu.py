"""Poprawki z przeglądu kodu — każda z testem, który pilnuje, żeby błąd nie wrócił.

Sekcje odpowiadają znaleziskom: sprawdzanie podejrzanego przebiegu, rozdzielenie
paliwa i prądu, tagi, odmiana przez liczbę, parsowanie liczb, rok w pigułce,
edycja wizyty i drobniejsze rzeczy z warstwy danych.
"""

from datetime import date, timedelta

import pytest

import db
import utils


def dni_temu(dni):
    return (date.today() - timedelta(days=dni)).strftime("%d.%m.%Y")


def auto(nazwa="Przegląd", typ_paliwa="Benzyna", **pola):
    kolumny = {"nazwa": nazwa, "typ_paliwa": typ_paliwa, "status": db.STATUS_POJAZDU_AKTYWNY,
               "rola_wspoldzielenia": db.ROLA_WLASCICIEL}
    kolumny.update(pola)
    with db.polacz_baze() as conn:
        kursor = conn.execute(
            f"INSERT INTO samochody ({', '.join(kolumny)}) VALUES ({', '.join('?' for _ in kolumny)})",
            list(kolumny.values()))
        return kursor.lastrowid


def tankowanie(auto_id, dni, przebieg, litry=40.0, kwota=240.0, pelny=1, rodzaj=db.ENERGIA_PALIWO,
               stacja=None):
    with db.polacz_baze() as conn:
        return conn.execute(
            "INSERT INTO tankowania (auto_id, data, przebieg, dystans, litry, kwota, do_pelna, stacja, "
            "rodzaj_energii) VALUES (?,?,?,?,?,?,?,?,?)",
            (auto_id, dni_temu(dni), przebieg, 0, litry, kwota, pelny, stacja, rodzaj)).lastrowid


def odczyt(auto_id, dni, przebieg):
    with db.polacz_baze() as conn:
        conn.execute("INSERT INTO odczyty_przebiegu (auto_id, data, przebieg, zrodlo) VALUES (?,?,?,?)",
                     (auto_id, dni_temu(dni), przebieg, db.ZRODLO_ODCZYTU_DOMYSLNE))


# ------------------------------------------------------- podejrzany przebieg


def test_wpis_bez_przebiegu_nie_udaje_ostatniego_stanu_licznika(baza):
    """Tankowanie z importu bez licznika (przebieg 0) z najnowszą datą robiło za
    „ostatni wpis” — i każdy normalny przebieg wyglądał przy nim na skok
    o cały licznik w jeden dzień."""
    a = auto()
    odczyt(a, 30, 100000)
    tankowanie(a, 2, 0)
    assert db.sprawdz_czy_przebieg_podejrzany(a, 100900, nowa_data_str=dni_temu(0)) is None


def test_wpis_wsteczny_nie_jest_porownywany_z_pozniejszymi(baza):
    """Paragon sprzed miesiąca dopisany dziś ma legalnie niższy licznik niż
    wczorajsze tankowanie."""
    a = auto()
    odczyt(a, 60, 100000)
    odczyt(a, 1, 102000)
    assert db.sprawdz_czy_przebieg_podejrzany(a, 101000, nowa_data_str=dni_temu(30)) is None


def test_wpis_wsteczny_wyzszy_niz_pozniejszy_ostrzega(baza):
    a = auto()
    odczyt(a, 60, 100000)
    odczyt(a, 1, 102000)
    ostrzezenie = db.sprawdz_czy_przebieg_podejrzany(a, 105000, nowa_data_str=dni_temu(30))
    assert ostrzezenie and "późniejszą" in ostrzezenie


def test_nizszy_od_wczesniejszego_i_skok_dalej_ostrzegaja(baza):
    a = auto()
    odczyt(a, 60, 100000)
    odczyt(a, 30, 101200)
    assert "niższy" in db.sprawdz_czy_przebieg_podejrzany(a, 10120, nowa_data_str=dni_temu(0))
    skok = db.sprawdz_czy_przebieg_podejrzany(a, 1012000, nowa_data_str=dni_temu(0))
    assert skok and "dodatkowej cyfry" in skok and "minęło 30 dni" in skok


def test_skok_po_jednym_dniu_odmienia_sie(baza):
    a = auto()
    odczyt(a, 60, 100000)
    odczyt(a, 1, 101200)
    assert "minął 1 dzień" in db.sprawdz_czy_przebieg_podejrzany(a, 181200, nowa_data_str=dni_temu(0))


# ------------------------------------------------------- paliwo kontra prąd


def plug_in_z_wpisami():
    """Plug-in: tankowania na Orlenie po ~6 zł/l i ładowania w garażu po ~1 zł/kWh."""
    a = auto("Plug-in", "Hybryda plug-in")
    for dni, przebieg in ((90, 10000), (60, 10600), (30, 11200)):
        tankowanie(a, dni, przebieg, litry=40, kwota=240, stacja="Orlen")
        tankowanie(a, dni - 5, przebieg + 100, litry=10, kwota=10, stacja="Garaż", rodzaj=db.ENERGIA_PRAD)
    return a


def test_trend_cen_plug_ina_nie_miesza_litrow_z_kwh(baza):
    a = plug_in_z_wpisami()
    paliwo = db.pobierz_trend_cen_paliwa(a)
    assert [s["nazwa"] for s in paliwo["stacje"]] == ["Orlen"]
    assert all(cena == pytest.approx(6.0) for _, cena in paliwo["punkty"])
    prad = db.pobierz_trend_cen_paliwa(a, rodzaj=db.ENERGIA_PRAD)
    assert [s["nazwa"] for s in prad["stacje"]] == ["Garaż"]


def test_obserwacja_stacji_nie_porownuje_ladowarki_ze_stacja_paliw(baza):
    a = plug_in_z_wpisami()
    assert not [o for o in db.obserwacje_analityczne(a) if o["klucz"] == "stacje_ceny"]


def test_porownanie_nie_daje_elektrykowi_spalania_w_litrach(baza):
    a = auto("Elektryk", "Elektryczny")
    for dni, przebieg in ((90, 1000), (60, 2000), (30, 3000)):
        tankowanie(a, dni, przebieg, litry=160, kwota=200, rodzaj=db.ENERGIA_PRAD)
    assert db.pobierz_dane_do_porownania(a)["spalanie"] is None


def test_wpis_bez_licznika_nie_psuje_dystansu_ani_spalania(baza):
    a = auto()
    tankowanie(a, 90, 100000)
    tankowanie(a, 60, 0, litry=30, pelny=0)          # import z samym dystansem
    tankowanie(a, 30, 101000, litry=30)
    tankowanie(a, 10, 0, litry=5)                     # „pełny”, ale bez licznika
    tankowanie(a, 5, 101500, litry=25)
    porownanie = db.pobierz_dane_do_porownania(a)
    assert porownanie["koszt_km"] == pytest.approx(porownanie["koszt_razem"] / 1500)
    assert [round(w, 1) for _, w in db.pobierz_serie_spalania(a, limit=None)] == [6.0, 6.0]
    podsumowanie = db.oblicz_podsumowanie_okresu(a)
    assert podsumowanie["dystans"] == 1500


def test_elektryk_ma_zuzycie_w_kwh_w_roku_w_pigulce_i_w_pdf(baza):
    a = auto("Elektryk", "Elektryczny")
    for dni, przebieg in ((40, 1000), (25, 1500), (10, 2000)):
        tankowanie(a, dni, przebieg, litry=80, kwota=100, rodzaj=db.ENERGIA_PRAD)
    rok = db.podsumowanie_roku(a, (date.today() - timedelta(days=10)).year)
    assert rok["zuzycie_elektryczne"] is True
    assert db.oblicz_podsumowanie_okresu(a)["zuzycie_elektryczne"] is True


def test_ladowanie_na_osi_czasu_ma_kwh(baza):
    a = plug_in_z_wpisami()
    ladowania = [z for z in db.pobierz_dane_timeline(a) if z[3].startswith("Ładowanie")]
    assert ladowania and all(" kWh" in z[4] and "L •" not in z[4] for z in ladowania)
    assert any("10 100 km" in z[4] for z in ladowania), "przebieg ze spacją tysięcy"


# ------------------------------------------------------------------- tagi


def koszt_z_tagami(auto_id, tagi):
    with db.polacz_baze() as conn:
        return conn.execute(
            "INSERT INTO inne_koszty (auto_id, data, kategoria, nazwa, kwota, tagi) VALUES (?,?,?,?,?,?)",
            (auto_id, dni_temu(1), db.KATEGORIA_INNE_DOMYSLNA, "Koszt", 10.0, tagi)).lastrowid


def tagi_kosztu(koszt_id):
    with db.polacz_baze() as conn:
        return conn.execute("SELECT tagi FROM inne_koszty WHERE id=?", (koszt_id,)).fetchone()[0]


def test_zmiana_nazwy_tagu_trafia_w_kazda_pisownie_i_nie_dubluje(baza):
    """„Łódź” w słowniku, „ŁÓDŹ” we wpisie: LIKE w SQLite nie zna wielkości
    polskich liter, a porównanie znak w znak — w ogóle innej pisowni."""
    a = auto()
    tag_id = db.dodaj_tag(a, "Łódź", "Niebieski")
    db.dodaj_tag(a, "Trasa", "Zielony")
    k1 = koszt_z_tagami(a, "ŁÓDŹ,Myjnia")
    k2 = koszt_z_tagami(a, "łódź, Trasa, Wyjazd")
    assert db.edytuj_tag_w_slowniku(a, tag_id, "Łódź", "Wyjazd", "Czerwony") is True
    assert tagi_kosztu(k1) == "Wyjazd,Myjnia"
    assert tagi_kosztu(k2) == "Wyjazd,Trasa", "bez podwójnego „Wyjazd”"


def test_zmiana_nazwy_na_inny_istniejacy_tag_jest_odrzucana(baza):
    a = auto()
    tag_id = db.dodaj_tag(a, "Myjnia", "Niebieski")
    db.dodaj_tag(a, "Trasa", "Zielony")
    assert db.edytuj_tag_w_slowniku(a, tag_id, "Myjnia", " trasa ", "Niebieski") is False
    assert sorted(n for _, n, _ in db.pobierz_tagi(a)) == ["Myjnia", "Trasa"]
    assert db.edytuj_tag_w_slowniku(a, tag_id, "Myjnia", "MYJNIA", "Niebieski") is True


def test_usuniecie_tagu_wymazuje_kazda_pisownie(baza):
    a = auto()
    tag_id = db.dodaj_tag(a, "Ubezpieczenie", "Niebieski")
    k1 = koszt_z_tagami(a, "UBEZPIECZENIE,Ub")
    k2 = koszt_z_tagami(a, "ubezpieczenie")
    db.usun_tag_ze_slownika(a, tag_id, "Ubezpieczenie")
    assert tagi_kosztu(k1) == "Ub", "element listy, nie fragment tekstu"
    assert tagi_kosztu(k2) is None


def test_edytor_tagow_zachowuje_kolejnosc(baza, monkeypatch):
    """`",".join(set)` układał tagi przy każdym zapisie inaczej — zapis bez
    zmian zmieniał tekst wpisu i synchronizacja wysyłała go od nowa."""
    import pomoce
    a = auto()
    for nazwa in ("Zeta", "Alfa", "Myjnia", "Trasa"):
        db.dodaj_tag(a, nazwa, "Niebieski")
    stan = pomoce.stan_aplikacji(a, "Przegląd")
    _kontener, pobierz = utils.komponent_tagow(pomoce.zbuduj_strone(), stan, "Trasa,Zeta,myjnia")
    assert pobierz() == "Trasa,Zeta,Myjnia"


# ------------------------------------------------------- rok w pigułce


@pytest.mark.parametrize("km, oczekiwane", [
    (650, "więcej niż przejazd z Warszawy do Berlina"),
    (1500, "prawie przejazd z Warszawy do Paryża"),
    (1250, "przejazd z Warszawy do Berlina — 2,1 raza"),
    (280, "prawie przejazd z Warszawy do Krakowa"),
    (100, None),
])
def test_porownanie_dystansu_mowi_prawie_tylko_gdy_brakuje(km, oczekiwane):
    assert db._porownanie_dystansu(km) == oczekiwane


def test_rok_w_toku_porownuje_sie_z_tym_samym_okresem(baza):
    """We wrześniu cały poprzedni rok zawsze był „droższy” — brakowało mu
    tylko jesieni, której ten rok jeszcze nie miał."""
    a = auto()
    dzis = date.today()
    teraz = dzis.replace(day=1)
    rok_temu = teraz.replace(year=teraz.year - 1)
    with db.polacz_baze() as conn:
        for d, kwota in ((teraz, 300.0), (rok_temu, 300.0), (date(dzis.year - 1, 12, 31), 5000.0)):
            conn.execute("INSERT INTO inne_koszty (auto_id, data, kategoria, nazwa, kwota) VALUES (?,?,?,?,?)",
                         (a, d.strftime("%d.%m.%Y"), db.KATEGORIA_INNE_DOMYSLNA, "Koszt", kwota))
    rok = db.podsumowanie_roku(a, dzis.year)
    if dzis.month == 12 and dzis.day == 31:
        pytest.skip("31 grudnia oba okresy są pełnymi latami")
    assert rok["poprzedni_rok"] == 300.0
    assert rok["zmiana_rdr"] == pytest.approx(0.0)


# ------------------------------------------------------- edycja wizyty


def test_edycja_wizyty_poprawia_pozycje_zamiast_zakladac_je_od_nowa(baza, monkeypatch):
    """Zapis wizyty kasował jej pozycje i zakładał nowe z ceną 0: ginęła cena
    pozycji z listy Do zrobienia (od niej zależy zwrot pozycji z wizyty),
    a każda poprawka daty robiła z całej wizyty nagrobki i nowe rekordy w chmurze."""
    import pomoce
    from views.formularze import FormularzWizytyView
    monkeypatch.setattr(utils, "przejdz", lambda page, trasa: None)
    monkeypatch.setattr(utils, "pokaz_komunikat", lambda *a, **k: None)
    monkeypatch.setattr(utils, "wypchnij_w_tle", lambda *a, **k: None)

    a = auto()
    with db.polacz_baze() as conn:
        olej = conn.execute("INSERT INTO zadania (auto_id, nazwa) VALUES (?, 'Olej')", (a,)).lastrowid
        klocki = conn.execute("INSERT INTO zadania (auto_id, nazwa) VALUES (?, 'Klocki')", (a,)).lastrowid
        filtr = conn.execute("INSERT INTO zadania (auto_id, nazwa) VALUES (?, 'Filtr')", (a,)).lastrowid
        w_id = conn.execute(
            "INSERT INTO wizyty (auto_id, data, przebieg, wykonawca, koszt_calkowity) VALUES (?,?,?,?,?)",
            (a, dni_temu(10), 120000, "AutoFix", 500.0)).lastrowid
        h_olej = conn.execute(
            "INSERT INTO historia (wizyta_id, zadanie_id, data, przebieg, cena, wykonawca, zdalne_id) "
            "VALUES (?,?,?,?,?,?,?)", (w_id, olej, dni_temu(10), 120000, 300.0, "AutoFix", "zdalny-olej")).lastrowid
        conn.execute(
            "INSERT INTO historia (wizyta_id, zadanie_id, data, przebieg, cena, wykonawca, zdalne_id) "
            "VALUES (?,?,?,?,?,?,?)", (w_id, klocki, dni_temu(10), 120000, 200.0, "AutoFix", "zdalne-klocki"))

    strona = pomoce.zbuduj_strone()
    widok = FormularzWizytyView(strona.page, pomoce.stan_aplikacji(a, "Przegląd"), w_id)
    widok.e_d.value = dni_temu(9)
    for chk in widok.chk_czesci:
        chk.value = chk.data in (olej, filtr)          # klocki odznaczone, filtr dodany
    widok.zapisz(None)

    with db.polacz_baze() as conn:
        pozycje = conn.execute(
            "SELECT id, zadanie_id, cena, data, zdalne_id FROM historia WHERE wizyta_id=? ORDER BY zadanie_id",
            (w_id,)).fetchall()
        nagrobki = [r[0] for r in conn.execute("SELECT zdalny_id FROM zdalne_nagrobki").fetchall()]
    assert pozycje[0] == (h_olej, olej, 300.0, dni_temu(9), "zdalny-olej")
    assert [(p[1], p[2]) for p in pozycje[1:]] == [(filtr, 0.0)]
    assert nagrobki == ["zdalne-klocki"]


# ------------------------------------------------ odmiana, liczby, ustawienia


@pytest.mark.parametrize("n, oczekiwane", [
    (1, "Został 1 dzień"), (3, "Zostały 3 dni"), (5, "Zostało 5 dni"), (22, "Zostały 22 dni"),
    (0, "Termin mija dziś"), (-1, "Przekroczono o 1 dzień"), (-12, "Przekroczono o 12 dni"),
])
def test_opis_terminu_dni(n, oczekiwane):
    assert db.opis_terminu_dni(n) == oczekiwane


def test_odmiana_jest_jedna_dla_ekranu_i_danych():
    for n in range(0, 130):
        assert utils._odmiana_liczby(n, "a", "b", "c") == db.odmien(n, "a", "b", "c")
    assert db.liczba_z_odmiana(1234, "wpis", "wpisy", "wpisów") == "1 234 wpisy"
    assert db.liczba_z_odmiana(1235, "wpis", "wpisy", "wpisów") == "1 235 wpisów"


def test_powiadomienie_o_dokumencie_odmienia_dni(baza):
    a = auto(oc_data=(date.today() + timedelta(days=1)).strftime("%d.%m.%Y"))
    oc = next(p for p in db.pobierz_powiadomienia(a) if p["klucz"] == "dokument:oc")
    assert oc["opis"] == "Został 1 dzień"


def test_opis_kolejki_synchronizacji_odmienia_sie(baza, monkeypatch):
    for ile, tekst in ((1, "1 pojazd czeka"), (3, "3 pojazdy czekają"), (5, "5 pojazdów czeka")):
        monkeypatch.setattr(db.synchronizacja, "liczba_oczekujacych_synchronizacji", lambda ile=ile: ile)
        assert db.opis_oczekujacej_synchronizacji().startswith(tekst)


@pytest.mark.parametrize("tekst, liczba, calkowita", [
    ("1.234,56 zł", 1234.56, 1235), ("1 234,56", 1234.56, 1235), ("12,5", 12.5, 12),
    ("150.000", 150.0, 150000), ("inf", None, None), ("nan", None, None), ("", None, None),
])
def test_parsowanie_liczb_z_formularza(tekst, liczba, calkowita):
    assert utils.parsuj_float(tekst, None) == liczba
    assert utils.parsuj_int(tekst, None) == calkowita


def test_bez_minusa_przed_zerem():
    assert db.liczba_na_tekst(-0.001) == "0,00"
    assert utils.formatuj_liczba(-0.4, 0) == "0"
    assert db.liczba_na_tekst(-0.006) == "-0,01"


def test_smiec_w_progach_nie_wywraca_powiadomien(baza):
    db.zapisz_ustawienie("prog_km_powiadomien", "abc")
    db.zapisz_ustawienie("prog_dni_powiadomien", "")
    assert db.pobierz_prog_km() == db.PROG_KM_POWIADOMIEN
    assert db.pobierz_prog_dni() == db.PROG_DNI_POWIADOMIEN
    db.pobierz_powiadomienia(auto())  # gołe int() rzucało tu ValueError


def test_zakres_wykresu_spoza_listy_wraca_do_domyslnego(baza):
    a = auto()
    db.zapisz_ustawienie(db._klucz_zakresow_wykresow(a), "wydatki=24")
    assert db.pobierz_zakres_wykresu(a, "wydatki") == db.ZAKRES_WYKRESU_DOMYSLNY


def test_db_na_liczbe_to_parser_z_pomocniczych():
    """Gwiazdkowy import podmieniał go węższą funkcją z wyszukiwarki."""
    assert db._na_liczbe("45,20 zł") == 45.2
    assert db._na_liczbe("nan") is None


# ------------------------------------------------------- pliki i raporty


def test_czcionki_pdf_szukane_w_assets_projektu():
    """Po rozbiciu db.py na pakiet katalog liczył się od db/, więc czcionki
    z assets/ w korzeniu (tam, gdzie pakuje je Flet) przestały być widoczne."""
    import pathlib
    korzen = pathlib.Path(db.__file__).resolve().parents[1]
    assert pathlib.Path(db.eksport.FOLDER_ASSETS).resolve() in (korzen / "assets", korzen / "db" / "assets")
    if not (korzen / "db" / "assets" / "DejaVuSans.ttf").exists():
        assert pathlib.Path(db.eksport.FOLDER_ASSETS).resolve() == korzen / "assets"


@pytest.mark.parametrize("tryb", ["LA", "I;16", "CMYK", "RGBA", "P"])
def test_obraz_w_nietypowym_trybie_zapisuje_sie_jako_prawdziwy_jpeg(baza, tmp_path, tryb):
    from PIL import Image
    zrodlo = tmp_path / f"obraz_{tryb.replace(';', '')}.{'jpg' if tryb == 'CMYK' else 'png'}"
    Image.new(tryb, (20, 10)).save(zrodlo)
    zapisana = db.zapisz_zalacznik(str(zrodlo))
    with Image.open(db.sciezka_pliku_zalacznika(zapisana)) as wynik:
        assert wynik.format == "JPEG"


def test_zdjecia_laczone_w_pdf_nie_zostaja_otwarte(baza, tmp_path):
    from PIL import Image
    sciezki = []
    for i in range(2):
        sciezka = tmp_path / f"strona{i}.png"
        Image.new("RGB", (30, 40), (i * 100, 0, 0)).save(sciezka)
        sciezki.append(str(sciezka))
    pdf = db.polacz_zdjecia_w_pdf(sciezki)
    assert pdf and open(pdf, "rb").read(4) == b"%PDF"
    for sciezka in sciezki:
        import os
        os.remove(sciezka)  # na Windows otwarty uchwyt zablokowałby usunięcie
