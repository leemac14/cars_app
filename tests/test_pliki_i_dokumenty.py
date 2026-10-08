"""Wiele plików na wpis i skarbiec dokumentów (N-05): migracja 51, kosz, cofanie,
formularz, sieroty, synchronizacja i daty dokumentów wspólne z Kartą pojazdu."""

import json
import os
from datetime import date, timedelta

import db
import pomoce
import probki_baz
import sync
import utils
from sync import pobieranie as sync_pobieranie


def _plik(nazwa, tresc=b"PLIK"):
    sciezka = os.path.join(db.FOLDER_ODROCZONE, nazwa)
    os.makedirs(db.FOLDER_ODROCZONE, exist_ok=True)
    with open(sciezka, "wb") as f:
        f.write(tresc)
    return sciezka


def _data(dni):
    return (date.today() + timedelta(days=dni)).strftime("%d.%m.%Y")


def _zapisz_dokument(auto_id, dokument_id=None, **pola):
    with db.polacz_baze() as conn:
        return db.zapisz_dokument(conn, auto_id, {"rodzaj": "inne", **pola}, dokument_id)


# ======================================================= migracja i kosz

def test_migracja_51_przenosi_pojedynczy_zalacznik_i_zeruje_kolumne(magazyn):
    probka = next(p for p in probki_baz.probki() if probki_baz.wersja_probki(p) == 50)
    probki_baz.odtworz_z_probki(probka, db.BAZA_DANYCH)
    with db.polacz_baze() as conn:
        przed = {t: conn.execute(f"SELECT id, zalacznik FROM {t} WHERE TRIM(COALESCE(zalacznik, '')) <> ''").fetchall()
                 for t in db.TABELE_DAWNEGO_ZALACZNIKA}
    assert all(przed.values()), "próbka 50 ma nieść załącznik w każdej tabeli wpisów"

    db.init_db()

    with db.polacz_baze() as conn:
        for tabela, wiersze in przed.items():
            assert conn.execute(f"SELECT COUNT(*) FROM {tabela} WHERE zalacznik IS NOT NULL").fetchone()[0] == 0
            for rekord_id, sciezka in wiersze:
                assert pomoce.pliki_wpisu(tabela, rekord_id) == [(sciezka, db.typ_dla_pliku(sciezka), None)]
        auta_historii = conn.execute(
            "SELECT zad.auto_id, zal.auto_id FROM zalaczniki zal JOIN historia his ON his.id = zal.rekord_id "
            "JOIN zadania zad ON zad.id = his.zadanie_id WHERE zal.tabela='historia'").fetchall()
    assert auta_historii and all(a == b for a, b in auta_historii), "historia bierze pojazd z podzespołu"


def test_kosz_przemapowuje_pliki_na_nowe_id_wpisu(baza):
    zid = pomoce.utworz_pojazd("Kosz")
    pliki_przed = pomoce.pliki_wpisu("wizyty", zid["wizyta"])
    wynik = db.usun_auto_do_kosza(zid["auto_id"])
    # Id wizyty zajęte w międzyczasie (np. po wczytaniu kopii) — wraca pod nowym.
    with db.polacz_baze() as conn:
        inne = conn.execute("INSERT INTO samochody (nazwa) VALUES ('Inny')").lastrowid
        conn.execute("INSERT INTO wizyty (id, auto_id, data, przebieg) VALUES (?,?,?,?)",
                     (zid["wizyta"], inne, "01.01.2026", 1000))

    auto_id = db.przywroc_auto_z_kosza(wynik["kosz_id"])

    with db.polacz_baze() as conn:
        nowa_wizyta = conn.execute("SELECT id FROM wizyty WHERE auto_id=?", (auto_id,)).fetchone()[0]
    assert nowa_wizyta != zid["wizyta"]
    assert [(t, o) for _, t, o in pomoce.pliki_wpisu("wizyty", nowa_wizyta)] == [(t, o) for _, t, o in pliki_przed]
    assert pomoce.pliki_wpisu("wizyty", zid["wizyta"]) == [], "obca wizyta pod starym id nie dostaje plików"
    assert all(os.path.exists(db.sciezka_pliku_zalacznika(s)) for s, _, _ in pomoce.pliki_wpisu("wizyty", nowa_wizyta))


def test_stara_migawka_kosza_z_kolumna_zalacznik_wraca_jako_plik_wpisu(baza):
    zid = pomoce.utworz_pojazd("Stary kosz")
    wynik = db.usun_auto_do_kosza(zid["auto_id"])
    # Migawka sprzed wersji 51: plik w kolumnie wpisu, bez tabeli `zalaczniki`.
    with db.polacz_baze() as conn:
        migawka = json.loads(conn.execute("SELECT migawka FROM kosz_pojazdy WHERE id=?",
                                          (wynik["kosz_id"],)).fetchone()[0])
        pierwszy = {}
        for z in migawka["tabele"].pop("zalaczniki")["wiersze"]:
            if z["tabela"] in db.TABELE_DAWNEGO_ZALACZNIKA:
                pierwszy.setdefault((z["tabela"], z["rekord_id"]), z["sciezka"])
        for (tabela, rekord_id), sciezka in pierwszy.items():
            for wiersz in migawka["tabele"][tabela]["wiersze"]:
                if wiersz["id"] == rekord_id:
                    wiersz["zalacznik"] = sciezka
        conn.execute("UPDATE kosz_pojazdy SET migawka=? WHERE id=?", (json.dumps(migawka), wynik["kosz_id"]))

    db.przywroc_auto_z_kosza(wynik["kosz_id"])

    with db.polacz_baze() as conn:
        assert conn.execute("SELECT COUNT(*) FROM tankowania WHERE zalacznik IS NOT NULL").fetchone()[0] == 0
    for (tabela, rekord_id), sciezka in pierwszy.items():
        assert [p[0] for p in pomoce.pliki_wpisu(tabela, rekord_id)] == [sciezka]
        assert os.path.exists(db.sciezka_pliku_zalacznika(sciezka))


# ======================================================= cofanie, sieroty, synchronizacja

def test_usuniecie_wizyty_odklada_wszystkie_pliki_i_oddaje_je_w_kolejnosci(baza):
    zid = pomoce.utworz_pojazd("Cofana")
    przed = pomoce.pliki_wpisu("wizyty", zid["wizyta"])
    assert len(przed) == 2

    wynik = db.usun_wizyty_z_cofnieciem([zid["wizyta"]])
    assert not any(os.path.exists(db.pelna_sciezka_zalacznika(s)) for s, _, _ in przed)
    wynik["cofnij"]()
    assert pomoce.pliki_wpisu("wizyty", zid["wizyta"]) == przed
    assert all(os.path.exists(db.pelna_sciezka_zalacznika(s)) for s, _, _ in przed)

    wynik = db.usun_wizyty_z_cofnieciem([zid["wizyta"]])
    wynik["finalizuj"]()
    assert not any(os.path.exists(db.sciezka_pliku_zalacznika(s)) for s, _, _ in przed)


def test_sieroty_znikaja_przy_starcie_a_wspolny_plik_zostaje(baza):
    zid = pomoce.utworz_pojazd("Sieroty")
    (sciezka, _, _), = pomoce.pliki_wpisu("tankowania", zid["tankowanie"])
    db.dodaj_zalaczniki("inne_koszty", zid["inny_koszt"], [_plik("winieta.jpg")])
    (wspolna, _, _), = pomoce.pliki_wpisu("inne_koszty", zid["inny_koszt"])
    with db.polacz_baze() as conn:
        # Ten sam plik wskazuje też zdjęcie karoserii — nie wolno go skasować.
        conn.execute("UPDATE zdjecia_karoserii SET zalacznik=? WHERE auto_id=?", (wspolna, zid["auto_id"]))
        conn.execute("DELETE FROM tankowania WHERE id=?", (zid["tankowanie"],))
        conn.execute("DELETE FROM inne_koszty WHERE id=?", (zid["inny_koszt"],))

    assert db.posprzataj_osierocone_zalaczniki() == 2
    assert pomoce.pliki_wpisu("tankowania", zid["tankowanie"]) == []
    assert not os.path.exists(db.pelna_sciezka_zalacznika(sciezka))
    assert os.path.exists(db.pelna_sciezka_zalacznika(wspolna))
    assert len(pomoce.pliki_wpisu("wizyty", zid["wizyta"])) == 2, "pliki istniejących wpisów zostają"


def test_wpis_usuniety_na_drugim_telefonie_zabiera_swoje_pliki(baza):
    zid = pomoce.utworz_pojazd("Zdalny", wspolny=True)
    (sciezka, _, _), = pomoce.pliki_wpisu("tankowania", zid["tankowanie"])
    konfig = next(k for k in sync.KONFIGURACJA_SYNC if k["tabela"] == "tankowania")

    znane = {"tank-1": {"id": zid["tankowanie"], "hash": None}}
    assert sync_pobieranie._zastosuj_rekord(konfig, {"id": "tank-1", "usuniete": True}, zid["auto_id"], znane) == 1

    assert pomoce.pliki_wpisu("tankowania", zid["tankowanie"]) == []
    assert not os.path.exists(db.pelna_sciezka_zalacznika(sciezka))


def test_dokument_jedzie_do_chmury_bez_plikow_z_ich_liczba(baza):
    konfig = next(k for k in sync.KONFIGURACJA_SYNC if k["tabela"] == "dokumenty_pojazdu")
    assert "liczba_plikow" in konfig["kolumny"] and "data_waznosci" in konfig["kolumny"]
    assert "dokumenty_pojazdu" in db.KOSZ_TABELE_SYNCHRONIZOWANE
    zid = pomoce.utworz_pojazd("Liczony")
    assert db.dodaj_zalaczniki("dokumenty_pojazdu", zid["dokument"], [_plik("strona2.jpg")]) == 1
    assert db.pobierz_dokument(zid["dokument"])["liczba_plikow"] == 2


# ======================================================= formularz i szybkie dodanie

def test_pola_zalacznikow_kopiuja_porzadkuja_i_sprzataja(baza):
    zid = pomoce.utworz_pojazd("Formularz")
    strona = pomoce.zbuduj_strone()
    stare = pomoce.pliki_wpisu("wizyty", zid["wizyta"])
    pola = utils.PolaZalacznikow(strona.page, "wizyty", zid["wizyta"])
    pola.dodaj_pliki([_plik("czesc.png"), _plik("faktura2.pdf")])
    assert [p["typ"] for p in pola.pozycje] == ["paragon", "faktura", "zdjecie", "faktura"]
    pola._usun(0)          # paragon znika z dysku dopiero po zapisie
    pola._przesun(1)       # zdjęcie części przed fakturą z warsztatu
    pola.pozycje[0]["typ"], pola.pozycje[0]["opis"] = "zdjecie_czesci", "Stary filtr"

    with pola.zapis(), db.polacz_baze() as conn:
        pola.zapisz_w(conn, zid["wizyta"], zid["auto_id"])

    po = pomoce.pliki_wpisu("wizyty", zid["wizyta"])
    assert [(t, o) for _, t, o in po] == [("zdjecie_czesci", "Stary filtr"), ("faktura", "Strona 1"), ("faktura", None)]
    assert all(s.startswith("zalaczniki/") and os.path.exists(db.pelna_sciezka_zalacznika(s)) for s, _, _ in po)
    assert not os.path.exists(db.pelna_sciezka_zalacznika(stare[0][0]))

    # Błąd w transakcji: nowe kopie znikają, baza zostaje bez zmian.
    pola = utils.PolaZalacznikow(strona.page, "wizyty", zid["wizyta"])
    pola.dodaj_pliki([_plik("nieudany.jpg")])
    przed = set(os.listdir(db.FOLDER_ZALACZNIKI))
    try:
        with pola.zapis(), db.polacz_baze() as conn:
            pola.zapisz_w(conn, zid["wizyta"], zid["auto_id"])
            raise RuntimeError("zapis przerwany")
    except RuntimeError:
        pass
    assert set(os.listdir(db.FOLDER_ZALACZNIKI)) == przed
    assert pomoce.pliki_wpisu("wizyty", zid["wizyta"]) == po


def test_szybkie_dodanie_dopisuje_na_koniec_z_podpowiedzia_rodzaju(baza):
    zid = pomoce.utworz_pojazd("Szybki")
    assert db.dodaj_zalaczniki("tankowania", zid["tankowanie"], [_plik("a.jpg"), _plik("b.pdf")]) == 2
    assert [t for _, t, _ in pomoce.pliki_wpisu("tankowania", zid["tankowanie"])] == ["paragon", "zdjecie", "faktura"]
    assert db.dodaj_zalaczniki("tankowania", 999999, [_plik("c.jpg")]) == 0
    assert db.dodaj_zalaczniki("samochody", zid["auto_id"], [_plik("d.jpg")]) == 0


# ======================================================= skarbiec dokumentów

def test_aktualna_polisa_dzieli_date_z_karta_a_starsza_jest_archiwalna(baza):
    auto_id = pomoce.utworz_pojazd("Polisa", z_zalacznikami=False)["auto_id"]
    stara = _zapisz_dokument(auto_id, rodzaj="oc", nazwa="PZU", data_waznosci=_data(-30))
    assert db.pobierz_dane_pojazdu(auto_id)["oc_data"] == _data(-30)
    nowa = _zapisz_dokument(auto_id, rodzaj="oc", nazwa="Warta", data_waznosci=_data(335))
    archiwum = _zapisz_dokument(auto_id, rodzaj="oc", nazwa="Link4", data_waznosci=_data(-400))

    assert db.pobierz_dane_pojazdu(auto_id)["oc_data"] == _data(335), "starsza polisa nie nadpisuje Karty"
    dokumenty = {d["id"]: d for d in db.dokumenty_pojazdu(auto_id)}
    assert dokumenty[nowa]["z_karty"] and not dokumenty[nowa]["archiwalny"]
    assert dokumenty[stara]["archiwalny"] and dokumenty[archiwum]["archiwalny"]
    assert dokumenty[stara]["waznosc"] == _data(-30) and dokumenty[stara]["status"] is None

    # Zmiana daty na Karcie pojazdu (formularz pojazdu, druga osoba) — aktualna polisa ją pokazuje.
    with db.polacz_baze() as conn:
        conn.execute("UPDATE samochody SET oc_data=? WHERE id=?", (_data(500), auto_id))
    assert {d["id"]: d["waznosc"] for d in db.dokumenty_pojazdu(auto_id)}[nowa] == _data(500)
    assert not [p for p in db.pobierz_powiadomienia(auto_id) if p["klucz"].startswith("skarbiec:")], \
        "polisa przypomina przez Kartę pojazdu, nie drugi raz przez skarbiec"


def test_dokument_z_wlasna_data_przypomina_w_dzwonku_odliczaniach_i_na_osi(baza):
    auto_id = pomoce.utworz_pojazd("Gwarancja", z_zalacznikami=False)["auto_id"]
    db.zapisz_prog_dni_dokumentu(db.KLUCZ_PROGU_SKARBCA, "30")
    blisko = _zapisz_dokument(auto_id, rodzaj="gwarancja_inna", nazwa="Akumulator", data_waznosci=_data(10),
                              data_wystawienia=_data(-355))
    daleko = _zapisz_dokument(auto_id, rodzaj="inne", nazwa="Winieta", data_waznosci=_data(90))

    powiadomienia = {p["klucz"]: p for p in db.pobierz_powiadomienia(auto_id)}
    assert powiadomienia[f"skarbiec:{blisko}"]["tytul"] == "Inna gwarancja: Akumulator"
    assert powiadomienia[f"skarbiec:{blisko}"]["trasa"] == "/dokumenty"
    assert f"skarbiec:{daleko}" not in powiadomienia

    odliczania = {o["klucz"]: o for o in db.odliczania_pojazdu(auto_id)}
    assert odliczania[f"skarbiec:{blisko}"]["status"] == "blisko"
    assert 0.9 < odliczania[f"skarbiec:{blisko}"]["udzial"] < 1.0, "pasek liczy od wystawienia"
    assert odliczania[f"skarbiec:{daleko}"]["status"] == "ok"
    assert f"skarbiec:{blisko}" in {p["klucz"] for p in db.os_przyszlosci(auto_id, 30)["pozycje"]}


def test_formularz_dokumentu_zapisuje_strony_i_date_karty(baza):
    auto_id = pomoce.utworz_pojazd("Formularz dokumentu", z_zalacznikami=False)["auto_id"]
    strona = pomoce.zbuduj_strone()
    strona.page.on_route_change = lambda e: None
    from views.formularze import FormularzDokumentuView

    widok = FormularzDokumentuView(strona.page, pomoce.stan_aplikacji(auto_id, "Formularz dokumentu"), None, "przeglad")
    widok.e_do.value = _data(200)
    widok.pliki.dodaj_pliki([_plik("przeglad.jpg")])
    widok.zapisz(None)

    dokument = next(d for d in db.dokumenty_pojazdu(auto_id) if d["rodzaj"] == "przeglad")
    assert (dokument["rodzaj"], dokument["z_karty"], dokument["liczba_plikow"]) == ("przeglad", True, 1)
    assert db.pobierz_dane_pojazdu(auto_id)["przeglad_data"] == _data(200)
    assert [t for _, t, _ in pomoce.pliki_wpisu("dokumenty_pojazdu", dokument["id"])] == [db.TYP_PLIKU_DOKUMENTU]
