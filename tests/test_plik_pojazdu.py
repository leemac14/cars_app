"""Plik pojazdu: zapis z wyborem sekcji, podgląd i wczytanie mechaniką kosza.

Pełny plik wraca w komplecie, ale bez tożsamości w chmurze; zestaw dla kupującego nie
wynosi prywatnych danych; obcy albo zepsuty plik nie wprowadza do bazy cudzych ścieżek
ani odwołań; nieudane zastąpienie oddaje poprzednie auto z kosza. Okna: sekcje i zestawy,
„zastąp albo dodaj”, cztery wejścia (szuflada, sprzedaż, Archiwum, „Wczytaj kopię”).
"""

import asyncio
import json
import os
import shutil
import sqlite3
import struct
import zipfile
from types import SimpleNamespace

import flet as ft
import pytest

import db
import log
import pomoce
import sync
import utils

# Wyciszone powiadomienia nie jadą z autem (jak w koszu), więc nie biorą udziału w porównaniu.
POMIJANE = pomoce.TABELE_POMIJANE_W_POROWNANIU | {"wyciszone_powiadomienia"}
KOLUMNY_CHMURY = set(db.KOLUMNY_SYNCHRONIZACJI_WPISU) | set(db.KOLUMNY_WSPOLDZIELENIA_POJAZDU)

# Kolumny karty pojazdu, które jadą w KAŻDYM pliku, także do kupującego. Nowa kolumna
# `samochody` trafia tu, do sekcji pliku (db.SEKCJE_PLIKU_POJAZDU) albo do kolumn współdzielenia.
JAWNE_KOLUMNY_POJAZDU = {
    "id", "nazwa", "marka", "model", "generacja", "rok_produkcji", "vin", "nr_rej", "data_pierwszej_rejestracji",
    "typ_paliwa", "pojemnosc_silnika", "moc_silnika", "skrzynia_biegow", "nadwozie", "pojemnosc_baku",
    "pojemnosc_baterii", "zasieg_ev", "typ_zlacza_ev", "kolor_motywu", "zdjecie_glowne", "notatki",
    "wiadomosc_statusu", "oc_data", "ac_data", "assistance_data", "telefon_assistance", "przeglad_data",
    "gasnica_data", "apteczka_data", "gwarancja_data", "gwarancja_przebieg", "wycieraczki_przod", "wycieraczki_tyl",
    "cisnienie_przod", "cisnienie_tyl", "olej_typ", "olej_pojemnosc", "akumulator", "zarowki_mijania",
    "zarowki_drogowe", "kod_lakieru", "rozmiar_opon", "rozmiar_felg", "rozstaw_srub", "moment_dokrecania",
}


def _zapisz(tmp_path, auto_id, sekcje=None, nazwa="pojazd.zip"):
    cel = str(tmp_path / nazwa)
    return cel, db.zapisz_plik_pojazdu(auto_id, cel, sekcje)


def _surowe(plik):
    with zipfile.ZipFile(plik) as zf:
        return zf.read(db.NAZWA_DANYCH_POJAZDU).decode("utf-8")


def _dane(plik):
    return json.loads(_surowe(plik))


def _przepakuj(plik, cel, zmien=None, dodaj=None):
    """Kopia archiwum z poprawionym pojazd.json (`zmien(dane)`) i dodatkowymi plikami."""
    dane = _dane(plik)
    if zmien:
        zmien(dane)
    with zipfile.ZipFile(plik) as zrodlo, zipfile.ZipFile(cel, "w") as zf:
        for info in zrodlo.infolist():
            if info.filename != db.NAZWA_DANYCH_POJAZDU:
                zf.writestr(info, zrodlo.read(info))
        zf.writestr(db.NAZWA_DANYCH_POJAZDU, json.dumps(dane, ensure_ascii=False))
        for nazwa, tresc in (dodaj or {}).items():
            zf.writestr(nazwa, tresc)
    return str(cel)


def _skasuj_pojazd(auto_id):
    """Jak przeniesienie na drugi telefon: auta, jego plików i ustawień tu nie ma."""
    pliki = [db.sciezka_pliku_zalacznika(s) for s in pomoce.odciski_zalacznikow()]
    with db.polacz_baze() as conn:
        conn.execute("DELETE FROM samochody WHERE id=?", (auto_id,))
    for plik in pliki:
        os.remove(plik)
    db.ustawienia._usun_ustawienia_pojazdu(auto_id)


def _logicznie():
    """Auta i wpisy tak, jak widzi je użytkownik: bez ID i kolumn chmury, odwołanie zastąpione treścią
    wiersza, na który wskazuje, ścieżka — sumą treści pliku. Wczytane auto dostaje świeże ID."""
    tabele = ["samochody", *db.KOSZ_TABELE_POTOMNE]
    with db.polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        wiersze = {t: {w["id"]: dict(w) for w in conn.execute(f"SELECT * FROM {t}")} for t in tabele}

    def tresc(tabela, id_wiersza):
        wiersz = wiersze[tabela].get(id_wiersza)
        if wiersz is None:
            return ("brak", tabela, id_wiersza)
        wynik = {}
        for kolumna, wartosc in wiersz.items():
            if kolumna == "id" or kolumna in KOLUMNY_CHMURY:
                continue
            if kolumna == "auto_id":
                wartosc = wiersze["samochody"][wartosc]["nazwa"]
            elif kolumna in db.KOSZ_KLUCZE_OBCE.get(tabela, {}) and wartosc is not None:
                wartosc = tresc(db.KOSZ_KLUCZE_OBCE[tabela][kolumna], wartosc)
            elif tabela == "zalaczniki" and kolumna == "rekord_id":
                wartosc = tresc(wiersz["tabela"], wartosc)
            elif kolumna in ("zdjecie_glowne", "zalacznik", "sciezka") and wartosc:
                wartosc = pomoce.suma_pliku(db.pelna_sciezka_zalacznika(wartosc))
            wynik[kolumna] = wartosc
        return tuple(sorted(wynik.items()))

    return {t: sorted((tresc(t, i) for i in wiersze[t]), key=repr) for t in tabele}


def _stan():
    return pomoce.zrzut_danych(POMIJANE), pomoce.odciski_zalacznikow(), sorted(os.listdir(db.FOLDER_ZALACZNIKI))


def _ile(sql, *parametry):
    with db.polacz_baze() as conn:
        return conn.execute(sql, parametry).fetchone()[0]


def _ustaw_pojazd(auto_id, **kolumny):
    with db.polacz_baze() as conn:
        conn.execute(f"UPDATE samochody SET {', '.join(f'{k}=?' for k in kolumny)} WHERE id=?",
                     (*kolumny.values(), auto_id))


# ==================================================================== zapis i wczytanie

def test_pelny_plik_wraca_w_komplecie_bez_tozsamosci_w_chmurze(baza, tmp_path):
    ident = pomoce.utworz_pojazd("Pierwszy", wspolny=True)
    auto_id = ident["auto_id"]
    _ustaw_pojazd(auto_id, kod_wspolautora="KOD-WSPOLAUTORA", kod_podgladu="KOD-PODGLADU",
                  kod_zaproszenia="KOD-ZAPROSZENIA", rola_wspoldzielenia=db.ROLA_WSPOLAUTOR)
    przed, ustawienia = _logicznie(), db.ustawienia._pobierz_ustawienia_pojazdu(auto_id)

    plik, wynik = _zapisz(tmp_path, auto_id)
    assert (wynik["nazwa"], wynik["pliki"], wynik["brakujace"]) == ("Pierwszy", 9, 0)

    surowe = _surowe(plik)
    for sekret in ("wspolny-1", "info-zdalne-1", "KOD-WSPOLAUTORA", "KOD-PODGLADU", "KOD-ZAPROSZENIA",
                   "zad-1", "tank-1", "hist-1", "poz-1", "dok-1"):
        assert sekret not in surowe, sekret

    _skasuj_pojazd(auto_id)
    wczytane = db.wczytaj_plik_pojazdu(plik)

    assert (wczytane["nazwa"], wczytane["kosz_id"]) == ("Pierwszy", None)
    assert wczytane["auto_id"] > auto_id, "ID zwolnione w tej bazie nie wraca do cudzych danych"
    assert _logicznie() == przed
    assert db.ustawienia._pobierz_ustawienia_pojazdu(wczytane["auto_id"]) == ustawienia
    assert pomoce.klucze_obce_spojne() == []
    assert None not in pomoce.odciski_zalacznikow().values()
    with db.polacz_baze() as conn:
        assert conn.execute("SELECT wspolny_pojazd_id, info_zdalne_id, kod_wspolautora, rola_wspoldzielenia "
                            "FROM samochody").fetchone() == (None, None, None, db.ROLA_WLASCICIEL)
        for tabela in db.KOSZ_TABELE_SYNCHRONIZOWANE:
            assert conn.execute(f"SELECT COUNT(*) FROM {tabela} WHERE zdalne_id IS NOT NULL").fetchone()[0] == 0


def test_kolumny_wspoldzielenia_pokrywaja_odlaczenie_od_chmury(baza):
    """Co zeruje `odlacz_wspoldzielenie`, tego plik nie może nieść."""
    auto_id = pomoce.utworz_pojazd("Wspólny", wspolny=True)["auto_id"]
    _ustaw_pojazd(auto_id, kod_zaproszenia="A", kod_wspolautora="B", kod_podgladu="C", znacznik_delty="D",
                  zdalny_hash_info="E", rola_wspoldzielenia=db.ROLA_PODGLAD)

    def wiersz():
        with db.polacz_baze() as conn:
            conn.row_factory = sqlite3.Row
            return dict(conn.execute("SELECT * FROM samochody WHERE id=?", (auto_id,)).fetchone())

    przed = wiersz()
    sync.odlacz_wspoldzielenie(auto_id)
    zmienione = {k for k, v in wiersz().items() if przed[k] != v}

    assert zmienione and zmienione <= set(db.KOLUMNY_WSPOLDZIELENIA_POJAZDU)


def test_zestaw_dla_kupujacego_nie_wynosi_prywatnych_danych(baza, tmp_path):
    auto_id = pomoce.utworz_pojazd("Sprzedawany")["auto_id"]
    _ustaw_pojazd(auto_id, cena_zakupu=41000, data_zakupu="01.03.2021", nr_polisy="POL/123", skladka_roczna=1800,
                  status=db.STATUS_POJAZDU_SPRZEDANY, data_sprzedazy="01.10.2026", cena_sprzedazy=35000)
    with db.polacz_baze() as conn:
        conn.execute("INSERT INTO dokumenty_pojazdu (auto_id, rodzaj, numer) VALUES (?, 'ksiazka', 'KS-1')", (auto_id,))

    plik, _ = _zapisz(tmp_path, auto_id, db.sekcje_zestawu(db.ZESTAW_DLA_KUPUJACEGO))
    dane = _dane(plik)
    tabele = dane["migawka"]["tabele"]

    for tabela in ("inne_koszty", "wydatki_cykliczne", "budzety", "rozliczenia", "przejazdy", "trasy_szablony",
                   "szkice_wpisow"):
        assert tabele[tabela]["wiersze"] == [], tabela
    for tabela in ("historia", "wizyty", "tankowania", "odczyty_przebiegu", "zdjecia_karoserii", "magazyn_czesci",
                   "historia_czesci_magazynu", "warsztaty", "do_zrobienia"):
        assert tabele[tabela]["wiersze"], tabela
    assert [d["rodzaj"] for d in tabele["dokumenty_pojazdu"]["wiersze"]] == ["ksiazka"]
    assert dane["migawka"]["ustawienia"] == {}
    surowe = _surowe(plik)
    for prywatne in ("Kamil", "Ola", "POL/123", "41000", "35000", "Teściowie"):
        assert prywatne not in surowe, prywatne
    with zipfile.ZipFile(plik) as zf:
        tresci = {zf.read(n) for n in zf.namelist() if n.startswith("pliki/")}
    assert b"DOWOD" not in tresci and b"SZKIC" not in tresci
    assert {b"KAROSERIA", b"WIZYTA", b"FAKTURA", b"GLOWNE-Sprzedawany"} <= tresci

    wczytane = db.wczytaj_plik_pojazdu(plik)
    assert (wczytane["nazwa"], wczytane["status"]) == ("Sprzedawany (2)", db.STATUS_POJAZDU_AKTYWNY), \
        "bez sekcji „Zakup” auto wczytuje się jako jeżdżące"
    with db.polacz_baze() as conn:
        assert conn.execute("SELECT cena_zakupu, nr_polisy, data_sprzedazy, cena_sprzedazy FROM samochody WHERE id=?",
                            (wczytane["auto_id"],)).fetchone() == (None, None, None, None)
    assert pomoce.klucze_obce_spojne() == []


@pytest.mark.parametrize("sekcje, sa, nie_ma", [
    (["czesci"], {"magazyn_czesci", "ceny_czesci"},
     {"historia", "wizyty", "wizyta_czesci_magazynu", "historia_czesci_magazynu"}),
    (["serwis"], {"zadania", "historia", "wizyty"},
     {"magazyn_czesci", "wizyta_czesci_magazynu", "historia_czesci_magazynu", "do_zrobienia"}),
])
def test_sekcja_bez_drugiej_strony_gubi_tylko_powiazania(baza, tmp_path, sekcje, sa, nie_ma):
    auto_id = pomoce.utworz_pojazd("Pierwszy")["auto_id"]

    plik, _ = _zapisz(tmp_path, auto_id, sekcje)
    tabele = _dane(plik)["migawka"]["tabele"]

    assert all(tabele[t]["wiersze"] for t in sa) and not any(tabele[t]["wiersze"] for t in nie_ma)
    db.wczytaj_plik_pojazdu(plik)
    assert pomoce.klucze_obce_spojne() == []


def test_do_zrobienia_bez_serwisu_traci_tylko_odwolanie_do_podzespolu(baza, tmp_path):
    auto_id = pomoce.utworz_pojazd("Pierwszy")["auto_id"]

    plik, _ = _zapisz(tmp_path, auto_id, ["do_zrobienia"])

    wiersz = _dane(plik)["migawka"]["tabele"]["do_zrobienia"]["wiersze"][0]
    assert (wiersz["tytul"], wiersz["zadanie_id"]) == ("Umówić przegląd", None)


def test_dodanie_obok_dostaje_nowe_id_nazwe_i_wlasne_pliki(baza, tmp_path):
    zrodlo = pomoce.utworz_pojazd("Pierwszy")
    plik, _ = _zapisz(tmp_path, zrodlo["auto_id"])

    wczytane = db.wczytaj_plik_pojazdu(plik)

    assert wczytane["nazwa"] == "Pierwszy (2)" and wczytane["auto_id"] != zrodlo["auto_id"]
    assert pomoce.klucze_obce_spojne() == []
    with db.polacz_baze() as conn:
        c = conn.cursor()
        assert sorted(a for (a,) in c.execute(
            "SELECT z.auto_id FROM historia h JOIN zadania z ON z.id = h.zadanie_id")) == sorted(
            [zrodlo["auto_id"], wczytane["auto_id"]]), "każdy wpis serwisowy przy podzespole swojego auta"
        for tabela in ("tankowania", "wizyty", "magazyn_czesci", "dokumenty_pojazdu"):
            pary = c.execute(f"SELECT z.auto_id, t.auto_id FROM zalaczniki z JOIN {tabela} t ON t.id = z.rekord_id "
                             "WHERE z.tabela = ?", (tabela,)).fetchall()
            assert pary and all(a == b for a, b in pary), tabela
    odciski = pomoce.odciski_zalacznikow()
    assert len(odciski) == 18 and None not in odciski.values(), "dziewięć plików każdego auta, osobno"


def test_zastapienie_odklada_obecne_auto_do_kosza(baza, tmp_path):
    auto_id = pomoce.utworz_pojazd("Octavia")["auto_id"]
    _ustaw_pojazd(auto_id, vin="TMBJJ7NE8L0123456", nr_rej="WA 12345")
    plik, _ = _zapisz(tmp_path, auto_id)

    ten_sam = db.podglad_pliku_pojazdu(plik)["ten_sam"]
    assert (ten_sam["id"], ten_sam["nazwa"], ten_sam["po_czym"], ten_sam["wspolny"]) == \
        (auto_id, "Octavia", "VIN", False)

    wczytane = db.wczytaj_plik_pojazdu(plik, auto_id)

    assert wczytane["nazwa"] == "Octavia" and wczytane["kosz_id"]
    assert _ile("SELECT COUNT(*) FROM samochody") == 1 and db.liczba_w_koszu() == 1
    assert pomoce.klucze_obce_spojne() == [] and None not in pomoce.odciski_zalacznikow().values()
    przywrocone = db.przywroc_auto_z_kosza(wczytane["kosz_id"])
    assert _ile("SELECT nazwa FROM samochody WHERE id=?", przywrocone) == "Octavia (2)"


def test_to_samo_auto_po_numerze_tylko_gdy_vin_nie_przeczy(baza, tmp_path):
    auto_id = pomoce.utworz_pojazd("Stare")["auto_id"]
    _ustaw_pojazd(auto_id, nr_rej="WA 12345")
    plik, _ = _zapisz(tmp_path, auto_id)
    _ustaw_pojazd(auto_id, nr_rej="wa-12345")

    assert db.podglad_pliku_pojazdu(plik)["ten_sam"]["po_czym"] == "numer rejestracyjny"

    _ustaw_pojazd(auto_id, vin="AAAAAAAAAAAAAAAAA")
    inny_vin = _przepakuj(plik, tmp_path / "inny.zip",
                          lambda d: d["migawka"]["auto"]["wiersz"].update(vin="BBBBBBBBBBBBBBBBB"))
    assert db.podglad_pliku_pojazdu(inny_vin)["ten_sam"] is None, "ta sama tablica, inny VIN — inne auto"
    bez_danych = _przepakuj(plik, tmp_path / "bez.zip", lambda d: d["migawka"]["auto"]["wiersz"].update(nr_rej="  "))
    assert db.podglad_pliku_pojazdu(bez_danych)["ten_sam"] is None


def test_nieudane_wczytanie_oddaje_zastapione_auto_i_sprzata_pliki(baza, tmp_path, monkeypatch):
    auto_id = pomoce.utworz_pojazd("Pierwszy")["auto_id"]
    plik, _ = _zapisz(tmp_path, auto_id)
    przed = _stan()

    def awaria(conn, migawka, podmiana=None, nowe_id=False):
        raise sqlite3.IntegrityError("awaria testowa")

    monkeypatch.setattr(db.plik_pojazdu, "odtworz_pojazd", awaria)
    with pytest.raises(sqlite3.IntegrityError):
        db.wczytaj_plik_pojazdu(plik, auto_id)

    assert _stan() == przed, "zastępowane auto wraca z kosza, wypakowane pliki znikają"
    assert db.liczba_w_koszu() == 0


def test_podglad_opisuje_plik_i_niczego_nie_zmienia(baza, tmp_path):
    auto_id = pomoce.utworz_pojazd("Pierwszy")["auto_id"]
    plik, wynik = _zapisz(tmp_path, auto_id)
    przed = _stan()

    podglad = db.podglad_pliku_pojazdu(plik)

    assert _stan() == przed
    assert (podglad["rodzaj"], podglad["blad"], podglad["nazwa"], podglad["opis_auta"]) == \
        ("pojazd", None, "Pierwszy", "Marka Model")
    assert (podglad["wpisy"], podglad["pliki"], podglad["uwagi"], podglad["ten_sam"]) == \
        (wynik["wpisy"], 9, [], None)
    assert podglad["rozmiar"] > 0 and podglad["utworzono"] and podglad["aplikacja"] == db.WERSJA_APLIKACJI
    puste = {"dokumenty_techniczne", "zakup", "polisa"}
    assert [s["id"] for s in podglad["sekcje"]] == [s["id"] for s in db.SEKCJE_PLIKU_POJAZDU if s["id"] not in puste]


def test_okno_zapisu_widzi_tylko_sekcje_z_danymi(baza):
    with db.polacz_baze() as conn:
        auto_id = conn.execute("INSERT INTO samochody (nazwa) VALUES ('Goły')").lastrowid
        conn.execute("INSERT INTO tankowania (auto_id, data, przebieg, litry, kwota) VALUES (?, '01.02.2026', 1000, 30, "
                     "200)", (auto_id,))
    pelny = pomoce.utworz_pojazd("Pełny")["auto_id"]

    zawartosc = db.zawartosc_pojazdu(auto_id)

    assert zawartosc["nazwa"] == "Goły"
    assert [(s["id"], s["podsumowanie"]) for s in zawartosc["sekcje"]] == [("tankowania", "1 wpis")]
    podpisy = {s["id"]: s["podsumowanie"] for s in db.zawartosc_pojazdu(pelny)["sekcje"]}["podpisy"]
    assert podpisy == "Kamil"
    assert db.zawartosc_pojazdu(99999) is None


def test_brakujace_zdjecie_jedzie_bez_pliku(baza, tmp_path):
    auto_id = pomoce.utworz_pojazd("Pierwszy")["auto_id"]
    for nazwa in ("Pierwszy_glowne.jpg", "Pierwszy_karoseria.jpg"):
        os.remove(os.path.join(db.FOLDER_ZALACZNIKI, nazwa))

    plik, wynik = _zapisz(tmp_path, auto_id)
    assert (wynik["pliki"], wynik["brakujace"]) == (7, 2)
    assert db.podglad_pliku_pojazdu(plik)["uwagi"] == []

    wczytane = db.wczytaj_plik_pojazdu(plik)

    assert wczytane["pominiete"] == 2
    assert _ile("SELECT zdjecie_glowne FROM samochody WHERE id=?", wczytane["auto_id"]) is None
    assert _ile("SELECT COUNT(*) FROM zdjecia_karoserii WHERE auto_id=?", wczytane["auto_id"]) == 0, \
        "zdjęcie karoserii bez pliku nie istnieje"


# ==================================================================== obcy i zepsuty plik

def test_rozpoznaje_rodzaj_archiwum(baza, tmp_path):
    auto_id = pomoce.utworz_pojazd("Pierwszy")["auto_id"]
    plik, _ = _zapisz(tmp_path, auto_id)
    kopia = str(tmp_path / "kopia.zip")
    db.zapisz_archiwum_kopii(kopia)
    gola_baza = str(tmp_path / "baza.db")
    shutil.copyfile(db.BAZA_DANYCH, gola_baza)
    obcy = str(tmp_path / "obcy.zip")
    with zipfile.ZipFile(obcy, "w") as zf:
        zf.writestr("notatka.txt", "x")
    tekst = tmp_path / "notatka.txt"
    tekst.write_text("nie archiwum", encoding="utf-8")

    assert [db.rodzaj_archiwum(p) for p in (plik, kopia, gola_baza, obcy, str(tekst), None, str(tmp_path / "brak"))] \
        == ["pojazd", "kopia", "kopia", None, None, None, None]
    podglad = db.podglad_pliku_pojazdu(kopia)
    assert podglad["rodzaj"] == "kopia" and podglad["blad"]
    assert db.podglad_pliku_pojazdu(str(tmp_path / "brak"))["blad"] == "Nie można odczytać wybranego pliku."
    with pytest.raises(db.BladPlikuPojazdu, match="nie jest plik pojazdu"):
        db.wczytaj_plik_pojazdu(kopia)


@pytest.mark.parametrize("zepsuj, powod", [
    (lambda d: d.update(rodzaj="kopia_czegos"), "nie jest plik pojazdu"),
    (lambda d: d.update(format=db.FORMAT_PLIKU_POJAZDU + 1), "nowsza wersja"),
    (lambda d: d["migawka"]["auto"].update(wiersz={}), "uszkodzony"),
    (lambda d: d["migawka"]["tabele"]["tankowania"]["wiersze"][0].update(kwota=[1, 2]), "uszkodzony"),
    (lambda d: d["migawka"]["tabele"]["tankowania"]["wiersze"][0].update(id="1"), "uszkodzony"),
    (lambda d: d["migawka"].update(ustawienia={"_klucz_kokpitu": 5}), "uszkodzony"),
    (lambda d: d.update(pliki=[["pliki/0001.jpg"]]), "uszkodzony"),
], ids=["obcy_rodzaj", "nowszy_format", "puste_auto", "lista_w_kolumnie", "id_tekstem", "ustawienie_liczba",
        "zla_lista_plikow"])
def test_zepsuty_plik_dostaje_powod_i_niczego_nie_zmienia(baza, tmp_path, zepsuj, powod):
    auto_id = pomoce.utworz_pojazd("Pierwszy")["auto_id"]
    plik = _przepakuj(_zapisz(tmp_path, auto_id)[0], tmp_path / "zepsuty.zip", zepsuj)
    przed = _stan()

    assert powod in db.podglad_pliku_pojazdu(plik)["blad"]
    with pytest.raises(db.BladPlikuPojazdu, match=powod):
        db.wczytaj_plik_pojazdu(plik)
    assert _stan() == przed


def test_smieci_zamiast_danych_i_uszkodzone_zdjecie(baza, tmp_path):
    auto_id = pomoce.utworz_pojazd("Pierwszy")["auto_id"]
    plik, _ = _zapisz(tmp_path, auto_id)
    smieci = str(tmp_path / "smieci.zip")
    with zipfile.ZipFile(smieci, "w") as zf:
        zf.writestr(db.NAZWA_DANYCH_POJAZDU, b"{to nie json")
    assert "uszkodzony" in db.podglad_pliku_pojazdu(smieci)["blad"]

    # Bajt w środku zdjęcia: CRC wykrywa to dopiero przy wypakowaniu, w połowie pracy.
    with zipfile.ZipFile(plik) as zf:
        info = zf.getinfo("pliki/0003.jpg")
    with open(plik, "r+b") as surowy:
        surowy.seek(info.header_offset + 26)
        dlugosc_nazwy, dlugosc_dodatkow = struct.unpack("<HH", surowy.read(4))
        surowy.seek(info.header_offset + 30 + dlugosc_nazwy + dlugosc_dodatkow)
        bajt = surowy.read(1)
        surowy.seek(-1, os.SEEK_CUR)
        surowy.write(bytes([bajt[0] ^ 0xFF]))
    przed = _stan()

    with pytest.raises(db.BladPlikuPojazdu, match="uszkodzony"):
        db.wczytaj_plik_pojazdu(plik)
    assert _stan() == przed, "żadnego pół pojazdu ani pół plików"


def test_obce_sciezki_i_osierocone_odwolania_nie_trafiaja_do_bazy(baza, tmp_path):
    zrodlo = pomoce.utworz_pojazd("Pierwszy")
    plik, _ = _zapisz(tmp_path, zrodlo["auto_id"])

    def zmien(dane):
        migawka, tabele = dane["migawka"], dane["migawka"]["tabele"]
        migawka["auto"]["wiersz"]["zdjecie_glowne"] = "C:/Windows/system32/obce.jpg"
        wzor = dict(tabele["zalaczniki"]["wiersze"][0])
        tabele["zalaczniki"]["wiersze"] += [
            {**wzor, "id": 990, "tabela": "tankowania", "rekord_id": 99999},
            {**wzor, "id": 991, "tabela": "tankowania", "rekord_id": zrodlo["tankowanie"],
             "sciezka": "../../poza_folderem.jpg"},
            {**wzor, "id": 992, "tabela": "samochody", "rekord_id": zrodlo["auto_id"]},
        ]
        tabele["historia"]["wiersze"].append({**tabele["historia"]["wiersze"][0], "id": 993, "zadanie_id": 99999})
        tabele["do_zrobienia"]["wiersze"][0]["zadanie_id"] = 99999
        dane["pliki"][1][0] = "../../ucieczka.jpg"

    obcy = _przepakuj(plik, tmp_path / "obcy.zip", zmien, dodaj={"../../ucieczka.jpg": b"UCIECZKA"})
    wczytane = db.wczytaj_plik_pojazdu(obcy)
    nowe = wczytane["auto_id"]

    assert pomoce.klucze_obce_spojne() == []
    with db.polacz_baze() as conn:
        sciezki = [s for (s,) in conn.execute("SELECT sciezka FROM zalaczniki WHERE auto_id=?", (nowe,))]
        zdjecie = conn.execute("SELECT zdjecie_glowne FROM samochody WHERE id=?", (nowe,)).fetchone()[0]
    assert len(sciezki) == 6 and all(s.startswith("zalaczniki/") for s in sciezki)
    assert zdjecie is None, "zdjęcie spoza pliku znika zamiast wskazywać obcy dysk"
    assert _ile("SELECT COUNT(*) FROM historia h JOIN zadania z ON z.id = h.zadanie_id WHERE z.auto_id=?", nowe) == 1
    assert _ile("SELECT zadanie_id FROM do_zrobienia WHERE auto_id=?", nowe) is None
    assert not list(tmp_path.rglob("ucieczka.jpg")) and not list(tmp_path.rglob("poza_folderem.jpg"))
    karoseria = _ile("SELECT zalacznik FROM zdjecia_karoserii WHERE auto_id=?", nowe)
    assert karoseria.startswith("zalaczniki/"), "plik spod obcej nazwy w archiwum ląduje pod nową nazwą"
    with open(db.pelna_sciezka_zalacznika(karoseria), "rb") as wypakowany:
        assert wypakowany.read() == b"UCIECZKA"


def test_plik_z_nowszej_wersji_ostrzega_i_pomija_nieznane(baza, tmp_path):
    auto_id = pomoce.utworz_pojazd("Pierwszy")["auto_id"]
    plik, _ = _zapisz(tmp_path, auto_id)

    def zmien(dane):
        dane["schemat"] = db.wersja_schematu_aplikacji() + 1
        dane["migawka"]["tabele"]["tankowania"]["wiersze"][0]["kolumna_z_przyszlosci"] = "x"
        dane["migawka"]["tabele"]["tabela_z_przyszlosci"] = {"kolumny": ["id"], "wiersze": [{"id": 1}]}

    nowszy = _przepakuj(plik, tmp_path / "nowszy.zip", zmien)
    uwagi = db.podglad_pliku_pojazdu(nowszy)["uwagi"]
    assert len(uwagi) == 1 and "nowsza wersja aplikacji" in uwagi[0]

    wczytane = db.wczytaj_plik_pojazdu(nowszy)
    assert _ile("SELECT COUNT(*) FROM tankowania WHERE auto_id=?", wczytane["auto_id"]) == 1


# ==================================================================== decyzje o kolumnach

def test_kazda_tabela_kosza_ma_sekcje_pliku():
    w_sekcjach = {t for s in db.SEKCJE_PLIKU_POJAZDU for t in s.get("tabele", ())}
    assert set(db.KOSZ_TABELE_POTOMNE) == w_sekcjach | set(db.TABELE_ZAWSZE_W_PLIKU), \
        "nowa tabela kosza: do sekcji w db.SEKCJE_PLIKU_POJAZDU albo świadomie do TABELE_ZAWSZE_W_PLIKU"
    assert not w_sekcjach & set(db.TABELE_ZAWSZE_W_PLIKU)


def test_kazda_kolumna_karty_pojazdu_ma_decyzje(baza):
    w_sekcjach = {k for s in db.SEKCJE_PLIKU_POJAZDU for k in s.get("kolumny_pojazdu", ())}
    assert set(pomoce.kolumny("samochody")) == JAWNE_KOLUMNY_POJAZDU | w_sekcjach | set(db.KOLUMNY_WSPOLDZIELENIA_POJAZDU), \
        "nowa kolumna `samochody`: JAWNE_KOLUMNY_POJAZDU (jedzie i do kupującego), sekcja pliku albo współdzielenie"


def test_podpisy_osob_obejmuja_kazda_kolumne_z_osoba_u_kupujacego(baza):
    podpisy = next(s for s in db.SEKCJE_PLIKU_POJAZDU if s["id"] == "podpisy")["kolumny_wpisow"]
    tabele = {t for s in db.SEKCJE_PLIKU_POJAZDU if s["dla_kupujacego"] for t in s.get("tabele", ())}
    for tabela in tabele | set(db.TABELE_ZAWSZE_W_PLIKU):
        for kolumna in pomoce.kolumny(tabela):
            if kolumna.endswith(("_przez", "_autor")) or kolumna in ("kierowca", "uczestnicy"):
                assert kolumna in podpisy, f"{tabela}.{kolumna}"


def test_zestawy_sekcji():
    wszystkie = [s["id"] for s in db.SEKCJE_PLIKU_POJAZDU]
    assert db.sekcje_zestawu(db.ZESTAW_PELNY) == wszystkie and len(set(wszystkie)) == len(wszystkie)
    assert db.sekcje_zestawu(db.ZESTAW_DLA_KUPUJACEGO) == [s["id"] for s in db.SEKCJE_PLIKU_POJAZDU
                                                           if s["dla_kupujacego"]]


# ==================================================================== okna

@pytest.fixture
def okna(monkeypatch):
    """Okna, komunikaty i przejścia z utils/plik_pojazdu.py i utils/kopie.py — zbierane zamiast pokazywane."""
    zebrane = SimpleNamespace(otwarte=[], komunikaty=[], ostrzezenia=[], trasy=[])
    for modul in (utils.plik_pojazdu, utils.kopie):
        monkeypatch.setattr(modul, "otworz_dialog", lambda page, dlg: zebrane.otwarte.append(dlg))
        monkeypatch.setattr(modul, "zamknij_dialog", lambda page, dlg: None)
        monkeypatch.setattr(modul, "pokaz_ladowanie", lambda page, tekst="": "okno-ladowania")
        monkeypatch.setattr(modul, "ukryj_ladowanie", lambda page, dlg: None)
        monkeypatch.setattr(modul, "pokaz_komunikat", lambda page, tekst, *a, **k: zebrane.komunikaty.append(tekst))
        monkeypatch.setattr(modul, "pokaz_ostrzezenie",
                            lambda page, tytul, tresc, **k: zebrane.ostrzezenia.append((tytul, tresc)))
    monkeypatch.setattr(utils.plik_pojazdu, "przejdz", lambda page, trasa: zebrane.trasy.append(trasa))
    return zebrane


@pytest.fixture
def zadania(monkeypatch):
    zebrane = []
    monkeypatch.setattr(ft.Page, "run_task", lambda self, f, *a, **k: zebrane.append(f))
    return zebrane


def _uruchom(zadania, nazwa):
    asyncio.run([f for f in zadania if getattr(f, "__name__", "") == nazwa][-1]())


def _kontrolki(korzen, typ):
    wynik, do_odwiedzenia = [], [korzen]
    while do_odwiedzenia:
        k = do_odwiedzenia.pop(0)
        if isinstance(k, typ):
            wynik.append(k)
        for pole in ("controls", "content", "title", "actions"):
            dziecko = getattr(k, pole, None)
            if isinstance(dziecko, (list, tuple)):
                do_odwiedzenia.extend(d for d in dziecko if isinstance(d, ft.Control))
            elif isinstance(dziecko, ft.Control):
                do_odwiedzenia.append(dziecko)
    return wynik


def test_okno_zapisu_przelacza_zestawy_i_zapisuje_wybrane_sekcje(baza, tmp_path, okna, zadania, monkeypatch):
    auto_id = pomoce.utworz_pojazd("Pierwszy")["auto_id"]
    strona = pomoce.zbuduj_strone()
    oddane = []

    async def oddaj(page, sciezka, nazwa_pliku):
        shutil.copyfile(sciezka, tmp_path / "oddany.zip")
        oddane.append(nazwa_pliku)
        return True

    monkeypatch.setattr(utils.plik_pojazdu, "_oddaj_plik", oddaj)
    monkeypatch.setattr(utils.plik_pojazdu, "_nowy_folder_tymczasowy", lambda: str(tmp_path))

    utils.zapisz_pojazd_do_pliku(strona.page, auto_id)
    _uruchom(zadania, "_otworz_okno")
    dlg = okna.otwarte[-1]
    napisy = pomoce.napisy(dlg)
    assert "Zapisz „Pierwszy” do pliku" in napisy and "Rozliczenia między osobami" in napisy
    assert "Dokumenty techniczne" not in napisy, "sekcja bez danych nie ma przełącznika"
    przelaczniki = _kontrolki(dlg, ft.Switch)
    assert przelaczniki and all(p.value for p in przelaczniki), "z szuflady startuje zestaw pełny"

    segment = next(k for k in _kontrolki(dlg, ft.Container) if k.on_click and "Dla kupującego" in pomoce.napisy(k))
    segment.on_click(None)
    widoczne = {s["id"] for s in db.zawartosc_pojazdu(auto_id)["sekcje"]}
    assert sum(p.value for p in przelaczniki) == len(widoczne & set(db.sekcje_zestawu(db.ZESTAW_DLA_KUPUJACEGO)))

    inne = przelaczniki[[s["id"] for s in db.zawartosc_pojazdu(auto_id)["sekcje"]].index("inne_koszty")]
    inne.value = True
    inne.on_change(None)
    dlg.actions[1].on_click(None)
    _uruchom(zadania, "_zapisz")

    assert oddane and oddane[0].startswith("pojazd_Pierwszy_") and oddane[0].endswith(".zip")
    dane = _dane(tmp_path / "oddany.zip")
    kupujacy = set(db.sekcje_zestawu(db.ZESTAW_DLA_KUPUJACEGO)) | {"inne_koszty"}
    assert dane["sekcje"] == [s for s in db.sekcje_zestawu(db.ZESTAW_PELNY) if s in widoczne and s in kupujacy]
    assert dane["migawka"]["tabele"]["inne_koszty"]["wiersze"] and not dane["migawka"]["tabele"]["rozliczenia"]["wiersze"]
    assert okna.komunikaty[-1].startswith("Zapisano „Pierwszy”:")


def test_podglad_pyta_zastap_czy_dodaj_i_przelacza_na_wczytane_auto(baza, tmp_path, okna, zadania):
    auto_id = pomoce.utworz_pojazd("Octavia")["auto_id"]
    _ustaw_pojazd(auto_id, vin="TMBJJ7NE8L0123456")
    plik, _ = _zapisz(tmp_path, auto_id)
    strona = pomoce.zbuduj_strone()
    stan = pomoce.stan_aplikacji(auto_id, "Octavia")

    utils.zapytaj_o_wczytanie_pojazdu(strona.page, stan, plik)
    _uruchom(zadania, "_sprawdz")
    dlg = okna.otwarte[-1]
    napisy = pomoce.napisy(dlg)

    assert "Wczytać pojazd?" in napisy and "W aplikacji jest już „Octavia” — ten sam VIN." in napisy
    assert [a.content for a in dlg.actions] == ["Anuluj", "Dodaj obok", "Zastąp"]
    assert _ile("SELECT COUNT(*) FROM samochody") == 1, "do decyzji nic się nie dzieje"

    dlg.actions[2].on_click(None)
    _uruchom(zadania, "_wczytaj")

    assert db.liczba_w_koszu() == 1 and stan.auto_id != auto_id and stan.auto_nazwa == "Octavia"
    assert okna.trasy == ["/"]
    assert okna.komunikaty[-1] == "Wczytano pojazd „Octavia”. Poprzedni jest w koszu."


def test_sprzedane_auto_z_pliku_trafia_do_archiwum(baza, tmp_path, okna, zadania):
    auto_id = pomoce.utworz_pojazd("Sprzedany")["auto_id"]
    _ustaw_pojazd(auto_id, status=db.STATUS_POJAZDU_SPRZEDANY)
    plik, _ = _zapisz(tmp_path, auto_id)
    stan = pomoce.stan_aplikacji(None)
    strona = pomoce.zbuduj_strone()

    utils.zapytaj_o_wczytanie_pojazdu(strona.page, stan, plik)
    _uruchom(zadania, "_sprawdz")
    assert "W pliku auto jest sprzedane — trafi do Archiwum pojazdów." in pomoce.napisy(okna.otwarte[-1])
    okna.otwarte[-1].actions[1].on_click(None)
    _uruchom(zadania, "_wczytaj")

    assert okna.trasy == ["/archiwum"] and "Archiwum" in okna.komunikaty[-1]


def test_zly_plik_w_oknie_wczytania_dostaje_ostrzezenie(baza, tmp_path, okna, zadania):
    obcy = str(tmp_path / "obcy.zip")
    with zipfile.ZipFile(obcy, "w") as zf:
        zf.writestr("x.txt", "x")
    strona = pomoce.zbuduj_strone()

    utils.zapytaj_o_wczytanie_pojazdu(strona.page, pomoce.stan_aplikacji(None), obcy)
    _uruchom(zadania, "_sprawdz")
    utils.zapytaj_o_wczytanie_pojazdu(strona.page, pomoce.stan_aplikacji(None), str(tmp_path / "brak.zip"))

    assert okna.ostrzezenia == [("Nie da się wczytać pojazdu", "To nie jest plik pojazdu z tej aplikacji.")]
    assert okna.komunikaty == ["Nie można odczytać wybranego pliku."] and not okna.otwarte


def test_okno_sprzedazy_proponuje_plik_dla_kupujacego(baza, monkeypatch):
    auto_id = pomoce.utworz_pojazd("Sprzedawany")["auto_id"]
    strona = pomoce.zbuduj_strone()
    otwarte = []
    monkeypatch.setattr(utils.pojazd, "otworz_dialog", lambda page, dlg: otwarte.append(dlg))
    monkeypatch.setattr(utils.pojazd, "zamknij_dialog", lambda page, dlg: None)
    monkeypatch.setattr(utils.pojazd, "przejdz", lambda page, trasa: None)
    monkeypatch.setattr(utils.pojazd, "pokaz_komunikat_cofnij", lambda *a, **k: None)
    wywolane = []

    utils.sprzedaj_auto(strona.page, pomoce.stan_aplikacji(auto_id, "Sprzedawany"))
    assert "Zapisz plik dla kupującego" not in pomoce.napisy(otwarte[-1]), "bez wołającego nie ma propozycji"

    utils.sprzedaj_auto(strona.page, pomoce.stan_aplikacji(auto_id, "Sprzedawany"), plik_dla_kupujacego=wywolane.append)
    dlg = otwarte[-1]
    _kontrolki(dlg, ft.Checkbox)[0].value = True
    dlg.actions[1].on_click(None)

    assert wywolane == [auto_id]
    assert _ile("SELECT status FROM samochody WHERE id=?", auto_id) == db.STATUS_POJAZDU_SPRZEDANY


def test_szuflada_i_archiwum_prowadza_do_pliku_pojazdu(baza, monkeypatch):
    import views.archiwum_view

    auto_id = pomoce.utworz_pojazd("Archiwalny")["auto_id"]
    strona = pomoce.zbuduj_strone()
    zapisy, sprzedaze = [], []
    monkeypatch.setattr(utils.nawigacja, "zapisz_pojazd_do_pliku", lambda page, a, *z: zapisy.append((a, *z)))
    monkeypatch.setattr(utils.nawigacja, "sprzedaj_auto", lambda page, state, **k: sprzedaze.append(k))

    akcje = utils.akcje_nawigacji(strona.page, pomoce.stan_aplikacji(auto_id, "Archiwalny"))
    assert {e["akcja"] for e in utils.EKRANY if e["id"] in ("auto-do-pliku", "auto-z-pliku")} <= set(akcje)
    assert "zapisz_pojazd" not in utils.akcje_nawigacji(strona.page, pomoce.stan_aplikacji(None))
    assert "wczytaj_pojazd" in utils.akcje_nawigacji(strona.page, pomoce.stan_aplikacji(None))
    akcje["zapisz_pojazd"]()
    akcje["sprzedaj_pojazd"]()
    sprzedaze[0]["plik_dla_kupujacego"](auto_id)
    assert zapisy == [(auto_id,), (auto_id, db.ZESTAW_DLA_KUPUJACEGO)]

    db.oznacz_pojazd_sprzedany(auto_id, "01.10.2026", None)
    pozycje, z_archiwum = [], []
    monkeypatch.setattr(utils, "pokaz_menu_kontekstowe", lambda page, tytul, p: pozycje.extend(p))
    monkeypatch.setattr(utils, "zapisz_pojazd_do_pliku", lambda page, a, *z: z_archiwum.append(a))
    widok = views.archiwum_view.ArchiwumView(strona.page, pomoce.stan_aplikacji(None))
    widok._menu({"id": auto_id, "nazwa": "Archiwalny"})
    next(p for p in pozycje if p["tekst"] == "Zapisz pojazd do pliku")["akcja"]()
    assert z_archiwum == [auto_id]


# ==================================================================== „Wczytaj kopię” rozpoznaje plik pojazdu

@pytest.fixture
def aplikacja(baza, monkeypatch, zadania):
    """main.main() na stronie testowej (jak w test_manifest_kopii.py)."""
    monkeypatch.setattr(ft, "run", lambda *args, **kwargs: None)
    import main

    monkeypatch.setattr(log, "wlacz", lambda: True)
    monkeypatch.setitem(utils.wyglad._OSTATNI_MOTYW, "nazwa", utils.wyglad._OSTATNI_MOTYW["nazwa"])
    strona = pomoce.zbuduj_strone()
    ident = pomoce.utworz_pojazd("W aplikacji")
    main.main(strona.page)
    return SimpleNamespace(strona=strona, page=strona.page, auto_id=ident["auto_id"])


def _wybierz_plik(monkeypatch, plik):
    async def wybierz(self, *args, **kwargs):
        return [SimpleNamespace(path=str(plik))]

    monkeypatch.setattr(ft.FilePicker, "pick_files", wybierz)


def test_wczytaj_kopie_z_menu_przekazuje_plik_pojazdu_i_odwrotnie(aplikacja, okna, zadania, tmp_path, monkeypatch):
    plik, _ = _zapisz(tmp_path, aplikacja.auto_id)
    kopia = str(tmp_path / "kopia.zip")
    db.zapisz_archiwum_kopii(kopia)
    akcje = aplikacja.page.views[0].akcje_nawigacji

    _wybierz_plik(monkeypatch, plik)
    asyncio.run(akcje["wczytaj"]())
    _uruchom(zadania, "_sprawdz")
    assert "Wczytać pojazd?" in pomoce.napisy(okna.otwarte[-1]), "plik pojazdu z „Wczytaj kopię bazy”"

    _wybierz_plik(monkeypatch, kopia)
    akcje["wczytaj_pojazd"]()
    _uruchom(zadania, "_wybierz")
    _uruchom(zadania, "_sprawdz")
    _uruchom(zadania, "_przygotuj")
    assert "Wczytać tę kopię?" in pomoce.napisy(okna.otwarte[-1]), "kopia bazy z „Wczytaj pojazd z pliku”"
