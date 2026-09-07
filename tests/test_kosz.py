"""Kosz pojazdów — round-trip bit w bit i wszystko, co się przy nim psuje.

Scenariusze przepisane wprost z akapitu „Weryfikacja" notatki
`claude/kosz-pojazdow.md`, żeby przestały być jednorazowe:
pełny round-trip, wymuszona kolizja ID i nazwy, nagrobki dopiero przy trwałym
kasowaniu, retencja, sieroty w folderze kosza.

„Bit w bit" znaczy tu: każdy wiersz każdej tabeli z każdą wartością plus suma
kontrolna każdego pliku wskazywanego przez bazę. Bajty pliku .db porównywać nie
ma sensu — zależą od układu stron SQLite, nie od danych.
"""

import json
import os
import sqlite3
from datetime import datetime, timedelta

import db
import pomoce


# Wyciszone powiadomienia świadomie NIE jadą do kosza (patrz test na dole),
# więc nie biorą udziału w porównaniu „przed/po".
POMIJANE = pomoce.TABELE_POMIJANE_W_POROWNANIU | {"wyciszone_powiadomienia"}


def stan_bazy():
    return pomoce.zrzut_danych(POMIJANE), pomoce.odciski_zalacznikow()


def pliki_w_koszu():
    folder = db.FOLDER_KOSZ
    return sorted(os.listdir(folder)) if os.path.isdir(folder) else []


# ------------------------------------------------------------- round-trip


def test_round_trip_jednego_pojazdu_jest_bit_w_bit(baza):
    pomoce.utworz_pojazd("Pierwszy")
    dane_przed, zalaczniki_przed = stan_bazy()
    schemat_przed = pomoce.zrzut_schematu()

    wynik = db.usun_auto_do_kosza(1)
    assert wynik and wynik["kosz_id"]
    assert db.liczba_w_koszu() == 1
    with db.polacz_baze() as conn:
        assert conn.execute("SELECT COUNT(*) FROM samochody").fetchone()[0] == 0

    przywrocone = db.przywroc_auto_z_kosza(wynik["kosz_id"])

    assert przywrocone == 1, "wolne ID musi wrócić 1:1"
    assert db.liczba_w_koszu() == 0
    assert pomoce.zrzut_schematu() == schemat_przed
    assert stan_bazy() == (dane_przed, zalaczniki_przed)
    assert pomoce.klucze_obce_spojne() == []
    assert pliki_w_koszu() == [], "folder kosza ma zostać pusty po przywróceniu"


def test_round_trip_nie_rusza_drugiego_pojazdu(baza):
    pomoce.utworz_pojazd("Pierwszy")
    pomoce.utworz_pojazd("Drugi")
    dane_przed, zalaczniki_przed = stan_bazy()

    wynik = db.usun_auto_do_kosza(1)
    with db.polacz_baze() as conn:
        c = conn.cursor()
        assert c.execute("SELECT nazwa FROM samochody").fetchall() == [("Drugi",)]
        # Kaskada nie ma prawa zabrać wpisów cudzego auta.
        assert c.execute("SELECT COUNT(*) FROM tankowania").fetchone()[0] == 1

    db.przywroc_auto_z_kosza(wynik["kosz_id"])
    assert stan_bazy() == (dane_przed, zalaczniki_przed)


def test_cofniecie_ze_snackbara_przywraca_od_razu(baza):
    pomoce.utworz_pojazd("Pierwszy")
    dane_przed, zalaczniki_przed = stan_bazy()

    wynik = db.usun_auto_do_kosza(1)
    wynik["cofnij"]()

    assert wynik["cofniete"] is True
    assert wynik["przywrocone_id"] == 1
    assert db.liczba_w_koszu() == 0
    assert stan_bazy() == (dane_przed, zalaczniki_przed)

    # Drugie kliknięcie „Cofnij" (podwójny tap) nie może przywrócić auta dwa razy.
    wynik["cofnij"]()
    with db.polacz_baze() as conn:
        assert conn.execute("SELECT COUNT(*) FROM samochody").fetchone()[0] == 1


def test_wygasniecie_snackbara_zostawia_pojazd_w_koszu(baza):
    """Cała różnica względem dawnego, nieodwracalnego usuwania."""
    pomoce.utworz_pojazd("Pierwszy")
    wynik = db.usun_auto_do_kosza(1)

    wynik["finalizuj"]()

    assert db.liczba_w_koszu() == 1
    assert db.pobierz_kosz()[0]["nazwa"] == "Pierwszy"


# ------------------------------------------------------------ kolizje ID


def _zwolnij_identyfikatory():
    """Odtwarza bazę po wczytaniu kopii zapasowej.

    Tabele mają AUTOINCREMENT, więc w JEDNEJ bazie skasowane ID nigdy nie wraca —
    kolizja jest możliwa dopiero wtedy, gdy kosz przyjechał z innego pliku bazy,
    w którym liczniki startowały od zera. Wyczyszczenie sqlite_sequence daje
    dokładnie ten stan."""
    with db.polacz_baze() as conn:
        conn.execute("DELETE FROM sqlite_sequence")


def test_kolizja_wszystkich_id_i_nazwy_przemapowuje_klucze_obce(baza):
    """Najtrudniejszy przypadek: po usunięciu wszystkie ID zajmuje inne auto.

    Odtwarza sytuację po wczytaniu kopii zapasowej. Przywracany pojazd musi
    dostać świeże ID w każdej tabeli, a wszystkie odwołania — zostać przepięte."""
    zrodlo = pomoce.utworz_pojazd("Pierwszy")
    wynik = db.usun_auto_do_kosza(zrodlo["auto_id"])
    _zwolnij_identyfikatory()

    # Auto-zapychacz zajmuje ID 1 w samochodach i we WSZYSTKICH tabelach potomnych.
    zapychacz = pomoce.utworz_pojazd("Pierwszy")
    assert zapychacz["auto_id"] == 1, "zapychacz musi wejść dokładnie w zwolnione ID"

    przywrocone = db.przywroc_auto_z_kosza(wynik["kosz_id"])

    assert przywrocone != zapychacz["auto_id"]
    assert pomoce.klucze_obce_spojne() == []

    with db.polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # samochody.nazwa jest UNIQUE — przywrócone auto dostaje dopisek.
        c.execute("SELECT nazwa FROM samochody WHERE id=?", (przywrocone,))
        assert c.fetchone()["nazwa"] == "Pierwszy (2)"

        # Historia przywróconego auta wisi na JEGO podzespole i JEGO wizycie.
        c.execute(
            "SELECT h.id, h.zadanie_id, h.wizyta_id FROM historia h "
            "JOIN zadania z ON h.zadanie_id = z.id WHERE z.auto_id=?",
            (przywrocone,),
        )
        wiersze = c.fetchall()
        assert len(wiersze) == 1
        wpis = wiersze[0]

        c.execute("SELECT auto_id FROM zadania WHERE id=?", (wpis["zadanie_id"],))
        assert c.fetchone()["auto_id"] == przywrocone
        c.execute("SELECT auto_id FROM wizyty WHERE id=?", (wpis["wizyta_id"],))
        assert c.fetchone()["auto_id"] == przywrocone

        # Zużycie części przy wpisie serwisowym — dwa poziomy pośrednictwa.
        c.execute("SELECT historia_id, magazyn_id FROM historia_czesci_magazynu WHERE historia_id=?", (wpis["id"],))
        zuzycie = c.fetchone()
        assert zuzycie is not None
        c.execute("SELECT auto_id FROM magazyn_czesci WHERE id=?", (zuzycie["magazyn_id"],))
        assert c.fetchone()["auto_id"] == przywrocone

        # Pozycja checklisty musi trafić do checklisty przywróconego auta.
        c.execute(
            "SELECT l.auto_id FROM checklisty_pozycje p JOIN checklisty l ON p.checklista_id = l.id "
            "WHERE l.auto_id=?",
            (przywrocone,),
        )
        assert c.fetchone()["auto_id"] == przywrocone

        # Zadanie do zrobienia trzyma się podzespołu, nie cudzego o tym samym ID.
        c.execute("SELECT zadanie_id FROM do_zrobienia WHERE auto_id=?", (przywrocone,))
        z_id = c.fetchone()["zadanie_id"]
        c.execute("SELECT auto_id FROM zadania WHERE id=?", (z_id,))
        assert c.fetchone()["auto_id"] == przywrocone

        # Zapychacz stoi nietknięty.
        c.execute("SELECT COUNT(*) FROM tankowania WHERE auto_id=?", (zapychacz["auto_id"],))
        assert c.fetchone()[0] == 1


def test_kolizja_nazwy_numeruje_dalej_niz_dwa(baza):
    pomoce.utworz_pojazd("Pierwszy")
    wynik = db.usun_auto_do_kosza(1)
    pomoce.utworz_pojazd("Pierwszy")
    pomoce.utworz_pojazd("Pierwszy (2)")

    przywrocone = db.przywroc_auto_z_kosza(wynik["kosz_id"])

    with db.polacz_baze() as conn:
        assert conn.execute("SELECT nazwa FROM samochody WHERE id=?", (przywrocone,)).fetchone()[0] == "Pierwszy (3)"


def test_ustawienia_pojazdu_jada_do_kosza_i_wracaja(baza):
    """Własny układ kokpitu nie może zostać w bazie jako sierota ani przepaść."""
    pomoce.utworz_pojazd("Pierwszy")
    klucz_przed = db.ustawienia._klucz_kokpitu(1)
    assert db.pobierz_ustawienie(klucz_przed) == "przebieg,paliwo,terminy"

    wynik = db.usun_auto_do_kosza(1)
    assert db.pobierz_ustawienie(klucz_przed) is None, "ustawienie zostało w bazie jako sierota"

    przywrocone = db.przywroc_auto_z_kosza(wynik["kosz_id"])
    assert db.pobierz_ustawienie(db.ustawienia._klucz_kokpitu(przywrocone)) == "przebieg,paliwo,terminy"


# ---------------------------------------------------------------- pliki


def test_zdjecia_ida_do_kosza_i_wracaja_bez_zmiany_tresci(baza):
    pomoce.utworz_pojazd("Pierwszy")
    odciski_przed = pomoce.odciski_zalacznikow()
    assert odciski_przed and all(suma is not None for suma in odciski_przed.values())

    wynik = db.usun_auto_do_kosza(1)

    # Pliki zniknęły z folderu załączników i siedzą w koszu.
    for sciezka in odciski_przed:
        assert not os.path.exists(sciezka)
    assert len(pliki_w_koszu()) == len(odciski_przed)

    db.przywroc_auto_z_kosza(wynik["kosz_id"])

    assert pomoce.odciski_zalacznikow() == odciski_przed
    assert pliki_w_koszu() == []


def test_zajeta_sciezka_pliku_daje_nowa_nazwe_i_podmieniony_odsylacz(baza):
    """Po imporcie kopii w folderze może już leżeć plik o tej samej nazwie."""
    pomoce.utworz_pojazd("Pierwszy")
    with db.polacz_baze() as conn:
        stara_sciezka = conn.execute("SELECT zalacznik FROM tankowania WHERE id=1").fetchone()[0]

    wynik = db.usun_auto_do_kosza(1)

    # Ktoś zajmuje dokładnie tę ścieżkę INNĄ treścią.
    with open(stara_sciezka, "wb") as plik:
        plik.write(b"CUDZY-PLIK")

    db.przywroc_auto_z_kosza(wynik["kosz_id"])

    with db.polacz_baze() as conn:
        nowa_sciezka = conn.execute("SELECT zalacznik FROM tankowania WHERE auto_id=1").fetchone()[0]

    assert nowa_sciezka != stara_sciezka
    assert os.path.exists(nowa_sciezka)
    with open(nowa_sciezka, "rb") as plik:
        assert plik.read() == b"PARAGON", "przywrócony ma być plik z kosza, nie ten, który zajął ścieżkę"
    with open(stara_sciezka, "rb") as plik:
        assert plik.read() == b"CUDZY-PLIK", "cudzy plik nie może zostać nadpisany"


# ------------------------------------------------------------- nagrobki


def test_usuniecie_do_kosza_nie_rejestruje_nagrobkow(baza):
    """Dopóki auto siedzi w koszu, u współdzielących nadal istnieje."""
    pomoce.utworz_pojazd("Wspolny", wspolny=True)

    db.usun_auto_do_kosza(1)

    assert db.pobierz_nagrobki() == []


def test_trwale_kasowanie_rejestruje_nagrobki_dla_wpisow_z_chmury(baza):
    pomoce.utworz_pojazd("Wspolny", wspolny=True)
    wynik = db.usun_auto_do_kosza(1)

    nazwa = db.usun_z_kosza_trwale(wynik["kosz_id"])

    assert nazwa == "Wspolny"
    assert db.liczba_w_koszu() == 0

    nagrobki = {(tabela, zdalny) for _, tabela, zdalny in db.pobierz_nagrobki()}
    tabele_z_nagrobkiem = {tabela for tabela, _ in nagrobki}

    # Dane opisowe pojazdu mają własny zdalny odpowiednik.
    assert ("info_pojazdu", "info-zdalne-1") in nagrobki
    # Każda synchronizowana tabela z wpisem musi zgłosić usunięcie na serwer.
    for tabela in db.KOSZ_TABELE_SYNCHRONIZOWANE:
        assert tabela in tabele_z_nagrobkiem, f"brak nagrobka dla {tabela} — wpis zostanie u współdzielących na zawsze"
    # Zdjęcia karoserii nie jadą do chmury, więc nagrobka mieć nie mogą.
    assert "zdjecia_karoserii" not in tabele_z_nagrobkiem


def test_trwale_kasowanie_usuwa_pliki_z_dysku(baza):
    pomoce.utworz_pojazd("Pierwszy")
    wynik = db.usun_auto_do_kosza(1)
    assert pliki_w_koszu()

    db.usun_z_kosza_trwale(wynik["kosz_id"])

    assert pliki_w_koszu() == []


def test_oproznienie_kosza_kasuje_wszystkie_pozycje(baza):
    pomoce.utworz_pojazd("Pierwszy")
    pomoce.utworz_pojazd("Drugi")
    db.usun_auto_do_kosza(1)
    db.usun_auto_do_kosza(2)
    assert db.liczba_w_koszu() == 2

    assert db.oproznij_kosz() == 2

    assert db.liczba_w_koszu() == 0
    assert pliki_w_koszu() == []


# ------------------------------------------------------ retencja i sieroty


def _cofnij_date_usuniecia(kosz_id, dni):
    data = (datetime.now() - timedelta(days=dni)).strftime("%Y-%m-%d %H:%M:%S")
    with db.polacz_baze() as conn:
        conn.execute("UPDATE kosz_pojazdy SET data_usuniecia=? WHERE id=?", (data, kosz_id))


def test_retencja_kasuje_pozycje_starsze_niz_ustawiona(baza):
    pomoce.utworz_pojazd("Stary")
    pomoce.utworz_pojazd("Swiezy")
    db.zapisz_dni_kosza(7)

    stary = db.usun_auto_do_kosza(1)["kosz_id"]
    swiezy = db.usun_auto_do_kosza(2)["kosz_id"]
    _cofnij_date_usuniecia(stary, 8)

    assert db.posprzataj_kosz() == 1

    pozostale = [p["id"] for p in db.pobierz_kosz()]
    assert pozostale == [swiezy]


def test_retencja_nigdy_niczego_nie_kasuje(baza):
    pomoce.utworz_pojazd("Stary")
    db.zapisz_dni_kosza(0)
    kosz_id = db.usun_auto_do_kosza(1)["kosz_id"]
    _cofnij_date_usuniecia(kosz_id, 4000)

    assert db.posprzataj_kosz() == 0
    assert db.liczba_w_koszu() == 1
    assert db.pobierz_kosz()[0]["dni_do_usuniecia"] is None


def test_sieroty_w_folderze_kosza_znikaja_takze_przy_retencji_nigdy(baza):
    """Pliki po nagłym zamknięciu aplikacji — bez migawki, więc bez właściciela."""
    pomoce.utworz_pojazd("Pierwszy")
    db.zapisz_dni_kosza(0)
    db.usun_auto_do_kosza(1)
    uzywane = pliki_w_koszu()

    sierota = os.path.join(db.FOLDER_KOSZ, "sierota.jpg")
    with open(sierota, "wb") as plik:
        plik.write(b"SIEROTA")

    db.posprzataj_kosz()

    assert not os.path.exists(sierota)
    assert pliki_w_koszu() == uzywane, "pliki należące do pozycji kosza mają zostać nietknięte"


def test_opis_pozycji_kosza_liczy_tylko_historie_nie_konfiguracje(baza):
    """„Tyle mojej pracy tu leży" — tagi i warsztaty nie zawyżają tej liczby."""
    pomoce.utworz_pojazd("Pierwszy")
    db.usun_auto_do_kosza(1)

    pozycja = db.pobierz_kosz()[0]

    assert pozycja["liczba_wpisow"] == len(db.KOSZ_TABELE_LICZONE)
    assert pozycja["rozmiar_plikow"] > 0
    assert pozycja["data_usuniecia"] is not None


def test_migawka_zapamietuje_wersje_schematu(baza):
    """Pozwala rozpoznać zrzut ze starszej wersji aplikacji."""
    pomoce.utworz_pojazd("Pierwszy")
    kosz_id = db.usun_auto_do_kosza(1)["kosz_id"]

    with db.polacz_baze() as conn:
        wersja, migawka = conn.execute(
            "SELECT schemat_wersja, migawka FROM kosz_pojazdy WHERE id=?", (kosz_id,)
        ).fetchone()

    assert wersja == int(db.pobierz_ustawienie("schema_version"))
    assert json.loads(migawka)["wersja"] == 1


def test_migawka_ze_starszego_schematu_wraca_bez_nieznanych_kolumn(baza):
    """Kolumny, których dziś już nie ma, mają zostać po cichu pominięte."""
    pomoce.utworz_pojazd("Pierwszy")
    kosz_id = db.usun_auto_do_kosza(1)["kosz_id"]

    with db.polacz_baze() as conn:
        surowa = conn.execute("SELECT migawka FROM kosz_pojazdy WHERE id=?", (kosz_id,)).fetchone()[0]
        migawka = json.loads(surowa)
        migawka["auto"]["wiersz"]["kolumna_ktorej_juz_nie_ma"] = "cokolwiek"
        for wiersz in migawka["tabele"]["tankowania"]["wiersze"]:
            wiersz["kolumna_ktorej_juz_nie_ma"] = "cokolwiek"
        conn.execute("UPDATE kosz_pojazdy SET migawka=? WHERE id=?", (json.dumps(migawka), kosz_id))

    przywrocone = db.przywroc_auto_z_kosza(kosz_id)

    assert przywrocone is not None
    with db.polacz_baze() as conn:
        assert conn.execute("SELECT COUNT(*) FROM tankowania WHERE auto_id=?", (przywrocone,)).fetchone()[0] == 1


def test_wyciszone_powiadomienia_nie_wracaja_z_kosza(baza):
    """Świadome pominięcie: wyciszenie jest tymczasowe i przywiązane do chwili,
    a nie do pojazdu. Tabela celowo NIE jest w KOSZ_TABELE_POTOMNE — gdyby
    kiedyś miała wracać, dopisanie jej tam zmieni wynik tego testu."""
    pomoce.utworz_pojazd("Pierwszy")
    wynik = db.usun_auto_do_kosza(1)
    przywrocone = db.przywroc_auto_z_kosza(wynik["kosz_id"])

    with db.polacz_baze() as conn:
        liczba = conn.execute(
            "SELECT COUNT(*) FROM wyciszone_powiadomienia WHERE auto_id=?", (przywrocone,)
        ).fetchone()[0]
    assert liczba == 0
