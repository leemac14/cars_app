"""Drabinka migracji: każda stara baza musi dojść do bieżącego schematu.

Najważniejszy test w tym katalogu. Wyłapuje błąd, którego nie widać w żadnym
uruchomieniu aplikacji na WŁASNYM komputerze: dopisanie kolumny do starej
migracji zamiast nowej. Świeża baza dostaje wtedy kolumnę, baza zaktualizowana
z poprzedniej wersji — nie. Objawia się dopiero u kogoś, kto miał aplikację
wcześniej, i wygląda jak „u mnie działa".

Sprawdzamy to z trzech stron, bo każda łapie co innego:

1. **Drabinka odtworzona z kodu** — baza w każdej wersji po init_db() ma dojść
   do tego samego schematu, co świeża. Łapie migrację, która nie jest
   powtarzalna albo psuje się przy starcie z konkretnej wersji.
2. **Zamek na odciskach** — skrót każdej WYDANEJ migracji. Łapie poprawianie
   przeszłości, którego punkt 1 z definicji nie widzi (obie ścieżki przechodzą
   przez ten sam, zmieniony kod).
3. **Próbki baz** (`tests/probki/`) — zamrożone zrzuty SQL z danymi, po jednym na
   wersję. Łapie to samo co punkt 2, ale na DANYCH, i pozwala uruchomić ten test
   komukolwiek, bez kopii prawdziwej `flota_zadania.db`.

Czwarta część pliku pilnuje drugiej strony tej samej zasady „tylko w przód":
kopii zapasowej z NOWSZEJ wersji aplikacji nie wolno wczytać, bo migracji w tył
nie ma.
"""

import pathlib
import shutil
import sqlite3
import sys
import zipfile

sys.path[:0] = [str(pathlib.Path(__file__).resolve().parent), str(pathlib.Path(__file__).resolve().parents[1])]

import pytest  # noqa: E402

import db  # noqa: E402
import pomoce  # noqa: E402
import probki_baz  # noqa: E402


DRABINKA = probki_baz.wczytaj_drabinke()
PROBKI = probki_baz.probki()

PLIK_ODCISKOW = pathlib.Path(__file__).with_name("odciski_migracji.txt")


def wersja_bazy():
    return int(db.pobierz_ustawienie("schema_version", "0"))


# `ustawienia` to magazyn klucz-wartość aplikacji, nie dane użytkownika: init_db()
# dopisuje tam schema_version, znacznik naprawy ścieżek i przeliczoną podzakładkę.
# Wzrost liczby wierszy jest tam normalny, więc przy porównaniu „przed i po" wypada.
TABELE_POZA_LICZENIEM = {"ustawienia"}


def liczby_wierszy():
    liczby = {}
    with db.polacz_baze() as conn:
        c = conn.cursor()
        for tabela in pomoce.nazwy_tabel(TABELE_POZA_LICZENIEM):
            c.execute(f"SELECT COUNT(*) FROM {tabela}")
            liczby[tabela] = c.fetchone()[0]
    return liczby


# ============================================================== 1. DRABINKA


def test_numer_wersji_zgadza_sie_z_dlugoscia_drabinki(baza):
    """Dopisana migracja bez podbitego numeru = migracja, która nigdy nie ruszy."""
    assert wersja_bazy() == len(DRABINKA)


@pytest.mark.parametrize("wersja_startowa", range(len(DRABINKA) + 1))
def test_kazda_stara_baza_dochodzi_do_biezacego_schematu(magazyn, schemat_wzorcowy, wersja_startowa):
    """Baza w dowolnej wersji po init_db() ma DOKŁADNIE ten sam schemat, co świeża."""
    probki_baz.zbuduj_baze_w_wersji(db.BAZA_DANYCH, wersja_startowa, DRABINKA)

    db.init_db()

    assert wersja_bazy() == len(DRABINKA)
    assert pomoce.klucze_obce_spojne() == []
    porownaj_schematy(pomoce.zrzut_schematu(), schemat_wzorcowy, f"awans z wersji {wersja_startowa}")


def porownaj_schematy(otrzymany, wzorcowy, opis):
    for tabela in sorted(set(wzorcowy) | set(otrzymany)):
        assert tabela in otrzymany, f"{opis}: brakuje tabeli {tabela}"
        assert tabela in wzorcowy, f"{opis}: została nadmiarowa tabela {tabela}"
        assert otrzymany[tabela] == wzorcowy[tabela], (
            f"{opis}: tabela {tabela} wygląda inaczej niż w świeżej bazie"
        )


def test_init_db_jest_powtarzalne(baza):
    """Drugie uruchomienie aplikacji nie ma prawa niczego zmienić."""
    schemat_przed = pomoce.zrzut_schematu()
    dane_przed = pomoce.zrzut_danych()

    db.init_db()

    assert pomoce.zrzut_schematu() == schemat_przed
    assert pomoce.zrzut_danych() == dane_przed
    assert wersja_bazy() == len(DRABINKA)


def test_baza_bez_wpisu_o_wersji_przechodzi_cala_drabinke(magazyn):
    """Baza sprzed wprowadzenia `schema_version` startuje od zera, nie wybucha."""
    conn = sqlite3.connect(db.BAZA_DANYCH)
    conn.execute("CREATE TABLE ustawienia (klucz TEXT PRIMARY KEY, wartosc TEXT)")
    conn.commit()
    conn.close()

    db.init_db()

    assert wersja_bazy() == len(DRABINKA)
    assert "samochody" in pomoce.zrzut_schematu()


# ================================================== 2. ZAMEK NA ODCISKACH


def odcisk(blok):
    import hashlib

    return hashlib.sha256(blok.encode("utf-8")).hexdigest()[:16]


def _zapisane_odciski():
    if not PLIK_ODCISKOW.exists():
        return []
    wiersze = []
    for wiersz in PLIK_ODCISKOW.read_text(encoding="utf-8").splitlines():
        wiersz = wiersz.strip()
        if wiersz and not wiersz.startswith("#"):
            numer, suma = wiersz.split()
            wiersze.append((int(numer), suma))
    return wiersze


def _tresc_pliku_odciskow():
    naglowek = (
        "# Odciski wydanych migracji. Plik jest zamkiem, nie kopią schematu.\n"
        "#\n"
        "# Migracja, która raz poszła do ludzi, jest u nich WYKONANA — zmiana jej\n"
        "# treści nie zmienia niczego w ich bazie, a zmienia wszystko w bazie\n"
        "# założonej od zera. Tak powstaje różnica, której nie widać na własnym\n"
        "# komputerze: świeża instalacja dostaje kolumnę, zaktualizowana nie.\n"
        "#\n"
        "# Nową migrację dopisuje się NA KOŃCU drabinki i tutaj:\n"
        "#     python tests/test_migracje.py --zapisz\n"
        "# Zmiana odcisku istniejącego wiersza to sygnał, że ktoś poprawił\n"
        "# przeszłość — i musi to potwierdzić świadomie.\n"
    )
    # Istniejące wiersze przepisujemy WERBATIM, dopisujemy tylko nowe migracje.
    # Gdyby --zapisz przeliczał komplet, zamek dałoby się otworzyć tym samym
    # poleceniem, którym dopisuje się nową migrację — czyli przy okazji.
    zapisane = _zapisane_odciski()
    wiersze = "".join(f"{numer:02d} {suma}\n" for numer, suma in zapisane)
    wiersze += "".join(
        f"{i + 1:02d} {odcisk(DRABINKA[i])}\n" for i in range(len(zapisane), len(DRABINKA))
    )
    return naglowek + wiersze


def test_wydane_migracje_nie_zmieniaja_sie_wstecz():
    zapisane = _zapisane_odciski()
    assert zapisane, (
        f"brak {PLIK_ODCISKOW.name} — załóż go poleceniem: python tests/test_migracje.py --zapisz"
    )
    assert len(DRABINKA) >= len(zapisane), (
        f"drabinka skurczyła się z {len(zapisane)} do {len(DRABINKA)} migracji — "
        "usunięta migracja nigdy nie wykona się u kogoś, kto jej jeszcze nie miał"
    )

    zmienione = [numer for numer, suma in zapisane if odcisk(DRABINKA[numer - 1]) != suma]
    assert zmienione == [], (
        f"migracje {zmienione} zostały zmienione po wydaniu. Baza założona od zera dostanie "
        "coś innego niż baza zaktualizowana. Poprawkę dopisz jako NOWĄ migrację na końcu "
        "drabinki; jeśli zmiana jest świadoma, odśwież zamek: python tests/test_migracje.py --zapisz"
    )

    assert len(DRABINKA) == len(zapisane), (
        f"drabinka ma {len(DRABINKA)} migracji, a zamek zna {len(zapisane)}. "
        "Odśwież go: python tests/test_migracje.py --zapisz"
    )


# ========================================================== 3. PRÓBKI BAZ


def test_probki_pokrywaja_cala_drabinke():
    assert PROBKI, (
        f"brak próbek w {probki_baz.KATALOG_PROBEK.name}/ — wygeneruj je: "
        "python tests/test_migracje.py --zapisz"
    )
    wersje = [probki_baz.wersja_probki(p) for p in PROBKI]
    assert wersje == list(range(len(DRABINKA) + 1)), (
        f"próbki pokrywają wersje {wersje[0]}–{wersje[-1]}, a drabinka ma {len(DRABINKA)} migracji. "
        "Odśwież je: python tests/test_migracje.py --zapisz"
    )


@pytest.mark.parametrize("probka", PROBKI, ids=[p.stem for p in PROBKI])
def test_probka_awansuje_do_biezacego_schematu(magazyn, schemat_wzorcowy, probka):
    """Zamrożona baza z danymi po init_db() ma mieć schemat świeżej — i nie zgubić
    ani jednego wiersza."""
    wersja = probki_baz.wersja_probki(probka)
    probki_baz.odtworz_z_probki(probka, db.BAZA_DANYCH)

    assert wersja_bazy() == wersja, "próbka nie zgadza się z własną nazwą"
    liczby_przed = liczby_wierszy()

    db.init_db()

    assert wersja_bazy() == len(DRABINKA)
    assert pomoce.klucze_obce_spojne() == []
    porownaj_schematy(pomoce.zrzut_schematu(), schemat_wzorcowy, f"próbka {probka.stem}")

    liczby_po = liczby_wierszy()
    for tabela, ile in liczby_przed.items():
        assert liczby_po.get(tabela, 0) == ile, (
            f"{probka.stem}: tabela {tabela} miała {ile} wierszy, po migracji ma {liczby_po.get(tabela, 0)}"
        )


@pytest.mark.parametrize("probka", PROBKI, ids=[p.stem for p in PROBKI])
def test_probka_przechodzi_migracje_uzupelniajace_dane(magazyn, probka):
    """Pięć migracji nie zmienia schematu, tylko UZUPEŁNIA istniejące wiersze.
    Bez danych w próbce wykonują się na zerze wierszy i niczego nie dowodzą."""
    wersja = probki_baz.wersja_probki(probka)
    probki_baz.odtworz_z_probki(probka, db.BAZA_DANYCH)

    db.init_db()

    with db.polacz_baze() as conn:
        c = conn.cursor()

        if wersja >= 1:
            # Migracja 8: podzespół z „opon" w nazwie dostaje dotyczy_opon=1.
            c.execute("SELECT dotyczy_opon FROM zadania WHERE nazwa='Wymiana opon / Kół'")
            w = c.fetchone()
            assert w is not None, f"{probka.stem}: zniknął podzespół opon"
            assert w[0] == 1, f"{probka.stem}: dotyczy_opon nie zostało uzupełnione"

            # Migracja 33: rodzaj energii z typu paliwa POJAZDU.
            c.execute("SELECT COUNT(*) FROM tankowania WHERE rodzaj_energii IS NULL")
            assert c.fetchone()[0] == 0, f"{probka.stem}: tankowania bez rodzaju energii"
            c.execute(
                "SELECT COUNT(*) FROM tankowania WHERE rodzaj_energii<>? AND auto_id IN "
                "(SELECT id FROM samochody WHERE typ_paliwa='Elektryczny')", (db.ENERGIA_PRAD,)
            )
            assert c.fetchone()[0] == 0, f"{probka.stem}: elektryk ma tankowania oznaczone jako paliwo"

            # Migracje 39 i 40: status i rola nie mogą zostać puste.
            c.execute("SELECT COUNT(*) FROM samochody WHERE status IS NULL OR TRIM(status)=''")
            assert c.fetchone()[0] == 0, f"{probka.stem}: pojazd bez statusu"
            c.execute("SELECT COUNT(*) FROM samochody WHERE rola_wspoldzielenia IS NULL OR TRIM(rola_wspoldzielenia)=''")
            assert c.fetchone()[0] == 0, f"{probka.stem}: pojazd bez roli"
            c.execute("SELECT COUNT(*) FROM wydatki_cykliczne WHERE typ IS NULL OR TRIM(typ)=''")
            assert c.fetchone()[0] == 0, f"{probka.stem}: wydatek cykliczny bez rodzaju"

    if wersja <= 37:
        # Migracja 38: układ zakładek zmienił ZNACZENIE numerów. Kto skończył na
        # dawnym „Paliwie" (2), ma trafić na Koszty z podzakładką Tankowania.
        assert db.pobierz_ustawienie("ostatnia_zakladka") == "2"
        assert db.pobierz_ustawienie("ostatnia_podzakladka_kosztow") == "1"


def test_probki_niosa_dane(magazyn):
    """Próbka bez wierszy przechodziłaby wszystkie testy i nie sprawdzała niczego."""
    najnowsza = PROBKI[-1]
    probki_baz.odtworz_z_probki(najnowsza, db.BAZA_DANYCH)

    liczby = liczby_wierszy()
    puste = [t for t, ile in liczby.items() if ile == 0]

    assert not puste, f"{najnowsza.stem}: tabele bez ani jednego wiersza: {', '.join(sorted(puste))}"


def test_probka_zerowa_to_pusta_instalacja(magazyn, schemat_wzorcowy):
    """Wersja 0 to ktoś, kto instaluje aplikację dzisiaj po raz pierwszy."""
    probki_baz.odtworz_z_probki(probki_baz.KATALOG_PROBEK / probki_baz.nazwa_probki(0), db.BAZA_DANYCH)

    db.init_db()

    assert wersja_bazy() == len(DRABINKA)
    porownaj_schematy(pomoce.zrzut_schematu(), schemat_wzorcowy, "próbka 00")




# ================================= 4. WERSJA SCHEMATU PRZY WCZYTYWANIU KOPII
# Migracje idą tylko w przód, więc kopia z NOWSZEJ wersji aplikacji nie ma jak
# się cofnąć. Wgrana zostawiłaby bazę z kolumnami, o których ten kod nie wie:
# nowe pola przestałyby się wypełniać i nie jechałyby do chmury — a nic by się
# przy tym nie wywaliło, więc nikt by się nie zorientował.


def _kopia_z_wersja(katalog, numer, nazwa="kopia.db"):
    """Kopia bieżącej bazy z podmienionym numerem schematu."""
    sciezka = katalog / nazwa
    shutil.copyfile(db.BAZA_DANYCH, sciezka)
    polaczenie = sqlite3.connect(sciezka)
    polaczenie.execute("UPDATE ustawienia SET wartosc=? WHERE klucz='schema_version'", (str(numer),))
    polaczenie.commit()
    polaczenie.close()
    return sciezka


def test_wersja_aplikacji_zgadza_sie_z_drabinka(baza):
    """Numer zapamiętany przez init_db() kontra drabinka odczytana z AST.

    Bez tego sprawdzenia dopisana migracja przesuwałaby drabinkę, a odmowa
    wczytania kopii dalej porównywałaby się do starej liczby."""
    assert db.wersja_schematu_aplikacji() == len(DRABINKA)


def test_wersja_pliku_czytana_bez_dotykania_pliku(baza, tmp_path):
    """Sprawdzany plik nie ma prawa się zmienić — otwieramy go tylko do odczytu."""
    kopia = _kopia_z_wersja(tmp_path, len(DRABINKA))
    przed = (kopia.stat().st_size, kopia.read_bytes())

    assert db.wersja_schematu_pliku(kopia) == len(DRABINKA)

    assert (kopia.stat().st_size, kopia.read_bytes()) == przed
    assert not (tmp_path / "kopia.db-journal").exists()
    assert not (tmp_path / "kopia.db-wal").exists()


def test_kopia_z_nowszym_schematem_jest_odrzucana(baza, tmp_path):
    kopia = _kopia_z_wersja(tmp_path, len(DRABINKA) + 1)

    wolno, powod = db.sprawdz_kopie_przed_wczytaniem(kopia)

    assert wolno is False
    assert str(len(DRABINKA) + 1) in powod and str(len(DRABINKA)) in powod, (
        "komunikat ma podać OBIE wersje — inaczej nie wiadomo, czego brakuje"
    )


def test_kopia_z_tym_samym_schematem_przechodzi(baza, tmp_path):
    assert db.sprawdz_kopie_przed_wczytaniem(_kopia_z_wersja(tmp_path, len(DRABINKA))) == (True, "")


@pytest.mark.parametrize("wersja", [0, 1, 20])
def test_kopia_starsza_przechodzi_bez_slowa(baza, tmp_path, wersja):
    """Dociągnięcie starej kopii drabinką to normalna, przewidziana droga —
    ostrzeżenie w tym miejscu byłoby szumem."""
    kopia = _kopia_z_wersja(tmp_path, wersja, nazwa=f"stara_{wersja}.db")

    assert db.sprawdz_kopie_przed_wczytaniem(kopia) == (True, "")


def test_nieczytelna_wersja_nie_blokuje(baza, tmp_path):
    """Plik, który nie jest bazą, i baza bez tabeli ustawień. Diagnostyka nie ma
    prawa zablokować importu — od zgłaszania niesprawnego pliku jest sam import,
    razem z przywróceniem kopii bezpieczeństwa."""
    smiec = tmp_path / "smiec.txt"
    smiec.write_text("to nie jest baza danych", encoding="utf-8")

    pusta = tmp_path / "pusta.db"
    polaczenie = sqlite3.connect(pusta)
    polaczenie.execute("CREATE TABLE cokolwiek (id INTEGER)")
    polaczenie.commit()
    polaczenie.close()

    assert db.wersja_schematu_pliku(smiec) is None
    assert db.wersja_schematu_pliku(pusta) is None
    assert db.wersja_schematu_pliku(tmp_path / "nie-ma-mnie.db") is None
    assert db.sprawdz_kopie_przed_wczytaniem(smiec) == (True, "")
    assert db.sprawdz_kopie_przed_wczytaniem(pusta) == (True, "")


def _archiwum_kopii(katalog, sciezka_bazy, nazwa="kopia_baza.zip"):
    """Archiwum w formacie kopii zapasowej: baza w korzeniu plus folder zdjęć."""
    archiwum = katalog / nazwa
    with zipfile.ZipFile(archiwum, "w") as zf:
        zf.write(sciezka_bazy, arcname=pathlib.Path(db.BAZA_DANYCH).name)
        zf.writestr("zalaczniki/zdjecie.jpg", b"UDAJE-ZDJECIE" * 100)
    return archiwum


def test_wersja_czytana_wprost_z_archiwum(baza, tmp_path):
    """Kopia zapasowa to ZIP, więc to jest droga, którą przechodzi każdy import."""
    kopia = _kopia_z_wersja(tmp_path, len(DRABINKA) + 3, nazwa="w_srodku.db")

    archiwum = _archiwum_kopii(tmp_path, kopia)

    assert db.wersja_schematu_kopii(archiwum) == len(DRABINKA) + 3
    wolno, powod = db.sprawdz_kopie_przed_wczytaniem(archiwum)
    assert wolno is False and str(len(DRABINKA) + 3) in powod


def test_archiwum_starsze_i_rowne_przechodzi(baza, tmp_path):
    stare = _archiwum_kopii(tmp_path, _kopia_z_wersja(tmp_path, 12, nazwa="s.db"), "stare.zip")
    rowne = _archiwum_kopii(tmp_path, _kopia_z_wersja(tmp_path, len(DRABINKA), nazwa="r.db"), "rowne.zip")

    assert db.sprawdz_kopie_przed_wczytaniem(stare) == (True, "")
    assert db.sprawdz_kopie_przed_wczytaniem(rowne) == (True, "")


def test_uszkodzone_archiwum_nie_blokuje(baza, tmp_path):
    """Zepsutego pliku nie ocenia diagnostyka, tylko sam import — razem
    z przywróceniem bazy sprzed próby."""
    zepsute = tmp_path / "zepsute.zip"
    zepsute.write_bytes(b"PK\x03\x04 a dalej same smieci, nie archiwum")

    bez_bazy = tmp_path / "bez_bazy.zip"
    with zipfile.ZipFile(bez_bazy, "w") as zf:
        zf.writestr("czytaj_to.txt", "archiwum bez bazy danych")

    assert db.wersja_schematu_kopii(zepsute) is None
    assert db.wersja_schematu_kopii(bez_bazy) is None
    assert db.sprawdz_kopie_przed_wczytaniem(zepsute) == (True, "")
    assert db.sprawdz_kopie_przed_wczytaniem(bez_bazy) == (True, "")


def test_wersja_pliku_odroznia_zero_od_nieznanej(baza, tmp_path):
    """Zero znaczy „przed pierwszą migracją" i puszcza całą drabinkę. None znaczy
    „nie wiem" i nie pozwala zakładać niczego. Zlanie ich w jedno kasowałoby
    różnicę między pustą instalacją a plikiem nie do odczytania."""
    zerowa = _kopia_z_wersja(tmp_path, 0, nazwa="zerowa.db")

    assert db.wersja_schematu_pliku(zerowa) == 0
    assert db.wersja_schematu_pliku(tmp_path / "nie-ma.db") is None



if __name__ == "__main__":
    import os
    import tempfile

    os.environ.setdefault("FLET_APP_STORAGE_DATA", tempfile.mkdtemp(prefix="wzorce_"))

    # newline="\n" jawnie: projekt jest na LF (patrz .gitattributes oraz
    # tests/test_konce_linii.py), a domyślny newline dałby na Windowsie CRLF
    # i pokazał cały plik jako zmieniony.
    bylo = len(_zapisane_odciski())
    PLIK_ODCISKOW.write_text(_tresc_pliku_odciskow(), encoding="utf-8", newline="\n")
    print(f"{PLIK_ODCISKOW.name}: dopisano {len(DRABINKA) - bylo} migracji (razem {len(DRABINKA)}).")

    dopisane = probki_baz.zapisz_probki(drabinka=DRABINKA)
    if dopisane:
        print(f"Próbki: dopisano wersje {', '.join(str(w) for w in dopisane)}.")
    else:
        print("Próbki: komplet, nic nie trzeba było dopisywać.")
    print("Istniejące wzorce zostały nietknięte — to celowe.")
