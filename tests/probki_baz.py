"""Próbki baz — po jednej dla każdej wersji schematu.

Do tej pory migracje testowało się na kopii prawdziwej `flota_zadania.db`, której
w repozytorium nie ma i być nie może: siedzą w niej VIN-y, numery polis i telefony.
Skutek był podwójny — nikt poza autorem nie mógł uruchomić najważniejszego testu
w projekcie, a autor nie mógł go uruchomić na maszynie bez tej kopii.

Próbki to ZAMROŻONE ZRZUTY SQL, po jednym na wersję schematu, z wygenerowanymi
danymi. Trzy rzeczy, które dają, a czego nie daje odtwarzanie drabinki z kodu:

1. Są plikami, nie wynikiem uruchomienia kodu. Poprawiona wstecz migracja zmienia
   drabinkę, ale NIE zmienia próbki — i wtedy test porównuje bazę zbudowaną
   wczorajszym kodem ze schematem zbudowanym dzisiejszym. Dokładnie ta różnica,
   której na własnym komputerze nie widać.
2. Niosą DANE, nie tylko schemat. Migracje 8, 33, 38, 39 i 40 uzupełniają
   istniejące wiersze — bez wierszy nie ma czego uzupełniać i te bloki nigdy się
   nie wykonują.
3. Są w repozytorium, więc CI i każda inna maszyna robią to samo, co autor.

Format to zrzut SQL, a nie plik .db: tekst zamiast bajtów, więc diff coś znaczy,
a plik nie puchnie w historii gita (13 kB tekstu zamiast 344 kB binariów).
Wierność sprawdzona — `iterdump` odtwarza schemat po `ALTER TABLE ADD COLUMN`
co do kolumny i co do indeksu.

UCZCIWA UWAGA: próbki wygenerowane dzisiaj odtwarzają drabinkę TAKĄ, JAKA JEST
DZISIAJ. Nie są zapisem archeologicznym tego, co naprawdę wyszło do ludzi rok
temu. Od dziś jednak są punktem odniesienia, którego nie da się zmienić przy
okazji — a o to w tym chodzi.

Odświeżenie po dopisaniu migracji (razem z zamkiem na odciskach):

    python tests/test_migracje.py --zapisz
"""

import ast
import json
import pathlib
import sqlite3
import sys
from datetime import datetime

sys.path[:0] = [str(pathlib.Path(__file__).resolve().parent), str(pathlib.Path(__file__).resolve().parents[1])]

KATALOG_PROBEK = pathlib.Path(__file__).resolve().parent / "probki"

# Tabele pomijane przy zasiewaniu danych.
BEZ_ZASIEWU = {
    "ustawienia",       # trzyma schema_version — zasiew by go nadpisał
    "sqlite_sequence",
}


# ============================================================================
#  DRABINKA Z PLIKU ŹRÓDŁOWEGO
# ============================================================================

def wczytaj_drabinke(plik_migracji=None):
    """Lista bloków SQL w tej postaci, w jakiej wykonuje je init_db().

    `migracje` jest zmienną LOKALNĄ wewnątrz init_db(), więc nie da się jej
    zaimportować — czytamy AST. Kopia listy w teście rozjechałaby się przy
    pierwszej zmianie i przestała cokolwiek sprawdzać."""
    import db

    plik = pathlib.Path(plik_migracji or db.migracje.__file__)
    drzewo = ast.parse(plik.read_text(encoding="utf-8"))
    funkcja = next(w for w in drzewo.body if isinstance(w, ast.FunctionDef) and w.name == "init_db")
    for wezel in ast.walk(funkcja):
        if isinstance(wezel, ast.Assign):
            for cel in wezel.targets:
                if isinstance(cel, ast.Name) and cel.id == "migracje":
                    return ast.literal_eval(wezel.value)
    raise AssertionError("W init_db() nie ma już listy `migracje` — testy migracji wymagają aktualizacji.")


def zbuduj_baze_w_wersji(sciezka, wersja, drabinka):
    """Odtwarza bazę taką, jaką aplikacja miała w wersji schematu `wersja`.

    Powtarza semantykę pętli z init_db(): podział bloku po średnikach i
    przełknięcie „duplicate column name". Poza drabinką odtwarza trzy tabele
    zakładane w init_db() PRZED nią (ustawienia, warsztaty, wydatki_cykliczne) —
    realna stara instalacja też je miała, a bez nich późniejsze ALTER-y nie
    miałyby na czym pracować.

    Świadomie pomija jednorazowe uzupełnienia danych (bloki `if i == …`): to
    init_db() ma je wykonać po drodze, a testy próbek właśnie tego pilnują."""
    conn = sqlite3.connect(sciezka)
    kursor = conn.cursor()
    kursor.execute("CREATE TABLE IF NOT EXISTS ustawienia (klucz TEXT PRIMARY KEY, wartosc TEXT)")
    kursor.execute(
        "CREATE TABLE IF NOT EXISTS warsztaty (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, "
        "nazwa TEXT NOT NULL, telefon TEXT, adres TEXT, notatki TEXT, "
        "FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE)"
    )
    kursor.execute("CREATE INDEX IF NOT EXISTS idx_warsztaty_auto ON warsztaty(auto_id)")
    kursor.execute(
        "CREATE TABLE IF NOT EXISTS wydatki_cykliczne (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, "
        "nazwa TEXT NOT NULL, kwota REAL NOT NULL DEFAULT 0.0, okres_dni INTEGER NOT NULL DEFAULT 30, "
        "nastepna_data TEXT NOT NULL, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE)"
    )
    kursor.execute("CREATE INDEX IF NOT EXISTS idx_wydatki_cykliczne_auto ON wydatki_cykliczne(auto_id)")

    for blok in drabinka[:wersja]:
        for polecenie in blok.split(";"):
            polecenie = polecenie.strip()
            if not polecenie:
                continue
            try:
                kursor.execute(polecenie)
            except sqlite3.OperationalError as blad:
                if "duplicate column name" not in str(blad).lower():
                    raise

    if wersja:
        kursor.execute(
            "INSERT INTO ustawienia (klucz, wartosc) VALUES ('schema_version', ?) "
            "ON CONFLICT(klucz) DO UPDATE SET wartosc=excluded.wartosc",
            (str(wersja),),
        )
    conn.commit()
    conn.close()


# ============================================================================
#  ZASIEW DANYCH
# ============================================================================
# Zasiew jest STEROWANY SCHEMATEM, a nie listą wpisaną tutaj: chodzi po
# PRAGM-ach, ustala kolejność po kluczach obcych i wypełnia kolumny według ich
# nazw i typów. Dzięki temu tabela dołożona jutrzejszą migracją dostaje dane bez
# dopisywania czegokolwiek w tym pliku.


def _tabele(conn):
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    return [t for (t,) in c.fetchall() if not t.startswith("sqlite_") and t not in BEZ_ZASIEWU]


def _kolumny(conn, tabela):
    c = conn.cursor()
    c.execute(f"PRAGMA table_info({tabela})")
    return [{"nazwa": r[1], "typ": (r[2] or "").upper(), "nn": bool(r[3]), "domyslna": r[4], "pk": bool(r[5])}
            for r in c.fetchall()]


def _klucze_obce(conn, tabela):
    c = conn.cursor()
    c.execute(f"PRAGMA foreign_key_list({tabela})")
    return {r[3]: r[2] for r in c.fetchall()}  # kolumna -> tabela docelowa


def _kolejnosc_zasiewu(conn):
    """Rodzic przed dzieckiem. Tabela, której rodzic w tej wersji jeszcze nie
    istnieje (np. warsztaty w wersji 0), wypada z zasiewu."""
    istniejace = set(_tabele(conn))
    zaleznosci = {t: set(_klucze_obce(conn, t).values()) for t in istniejace}
    ulozone, zostalo = [], dict(zaleznosci)
    while zostalo:
        gotowe = [t for t, rodzice in zostalo.items() if not (rodzice & set(zostalo)) ]
        gotowe = [t for t in gotowe if (zaleznosci[t] - istniejace) == set()]
        if not gotowe:
            break  # cykl albo brakujący rodzic — reszta wypada
        for t in sorted(gotowe):
            ulozone.append(t)
            del zostalo[t]
    return ulozone


def _wartosci_dziedzinowe():
    """Kolumny słownikowe dostają PRAWDZIWE wartości ze stałych aplikacji.

    Zasiew wypełniony napisami „tankowania-rodzaj_energii-1" byłby technicznie
    poprawny, ale nieczytelny w diffie i bezużyteczny przy sprawdzaniu migracji
    uzupełniających dane — a to one są tu najciekawsze."""
    import db

    return {
        "rodzaj_energii": db.RODZAJE_ENERGII,
        "typ_ladowania": db.TYPY_LADOWANIA,
        "typ_paliwa": db.TYPY_PALIWA,
        "nadwozie": db.TYPY_NADWOZIA,
        "status": [db.STATUS_POJAZDU_AKTYWNY],
        "rola_wspoldzielenia": [db.ROLA_WLASCICIEL],
        "typ": db.TYPY_CYKLICZNE,
        "priorytet": db.PRIORYTETY_DO_ZROBIENIA,
        "sezon": db.SEZONY_OPON,
        "os_montazu": db.OSIE_MONTAZU,
        "strefa": db.STREFY_KAROSERII,
        "typ_porownania": db.TYPY_ZDJECIA,
        "jednostka": db.JEDNOSTKI_MAGAZYNU,
        "zrodlo": list(db.ZRODLA_ODCZYTU),
        "okres": ["miesiac", "rok"],
    }


def _wartosc(tabela, kolumna, typ, numer, slownikowe):
    nazwa = kolumna["nazwa"]
    opcje = slownikowe.get(nazwa)
    if opcje:
        return opcje[(numer - 1) % len(opcje)]
    if nazwa == "kategoria" and tabela == "inne_koszty":
        import db
        return db.KATEGORIE_INNYCH_KOSZTOW[(numer - 1) % len(db.KATEGORIE_INNYCH_KOSZTOW)]
    if nazwa == "kategoria" and tabela == "magazyn_czesci":
        import db
        return db.KATEGORIE_MAGAZYNU[(numer - 1) % len(db.KATEGORIE_MAGAZYNU)]
    if "data" in nazwa or nazwa.endswith("_od") or nazwa.endswith("_do"):
        return f"20{20 + numer % 5:02d}-0{1 + numer % 8}-1{numer % 9}"
    if nazwa in ("przebieg", "przebieg_zakupu"):
        return 50000 + numer * 1500
    if typ.startswith("INT"):
        return numer
    if typ.startswith("REAL") or typ.startswith("NUM") or typ.startswith("FLOA") or typ.startswith("DOUB"):
        return round(10.0 * numer + 0.5, 2)
    return f"{tabela}-{nazwa}-{numer}"


def zasiej_dane(sciezka, wierszy=2):
    """Wstawia po kilka wierszy do każdej tabeli plus punkty zaczepienia dla
    migracji uzupełniających dane."""
    import db

    conn = sqlite3.connect(sciezka)
    conn.execute("PRAGMA foreign_keys = ON;")
    c = conn.cursor()
    wstawione = {}
    slownikowe = _wartosci_dziedzinowe()

    for tabela in _kolejnosc_zasiewu(conn):
        kolumny = _kolumny(conn, tabela)
        obce = _klucze_obce(conn, tabela)
        for numer in range(1, wierszy + 1):
            dane = {}
            for kolumna in kolumny:
                nazwa = kolumna["nazwa"]
                if kolumna["pk"] and kolumna["typ"].startswith("INT"):
                    continue
                if nazwa in obce:
                    rodzice = wstawione.get(obce[nazwa], [])
                    if rodzice:
                        dane[nazwa] = rodzice[(numer - 1) % len(rodzice)]
                    elif kolumna["nn"]:
                        dane = None
                        break
                    continue
                if not kolumna["nn"] and kolumna["domyslna"] is not None and numer % 2 == 0:
                    continue  # część wierszy zostaje na wartościach domyślnych
                dane[nazwa] = _wartosc(tabela, kolumna, kolumna["typ"], numer, slownikowe)
            if dane is None or not dane:
                break
            if tabela == "samochody":
                dane["nazwa"] = f"Pojazd {numer}"
            if tabela == "kosz_pojazdy":
                # Poprawna migawka i DZISIEJSZA data: init_db woła posprzataj_kosz(),
                # a wpis starszy niż retencja zniknąłby przed pierwszą asercją.
                dane["migawka"] = json.dumps({"wersja": 1, "auto": {"kolumny": [], "wiersz": {}}, "tabele": {}})
                dane["pliki"] = "[]"
                dane["data_usuniecia"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            nazwy = list(dane)
            try:
                c.execute(
                    f"INSERT INTO {tabela} ({','.join(nazwy)}) VALUES ({','.join('?' * len(nazwy))})",
                    tuple(dane[k] for k in nazwy),
                )
            except sqlite3.Error:
                break  # tabela nie do zasiania w tej wersji — nie szkodzi
            wstawione.setdefault(tabela, []).append(c.lastrowid)

    _punkty_zaczepienia(conn)
    conn.commit()
    conn.close()


def _punkty_zaczepienia(conn):
    """Stan, na którym migracje uzupełniające dane mają CO zrobić.

    Bez tego blok `if i == 32` (rodzaj energii) czy `if i == 7` (dotyczy_opon)
    wykonuje się na zerze wierszy i test niczego nie dowodzi.

    Świadomie NIE zerujemy tu `status`, `rola_wspoldzielenia` ani `typ`: każda
    z tych kolumn jest dodawana i uzupełniana przez TĘ SAMĄ migrację, więc próbka,
    w której kolumna już istnieje, ma z definicji wartość domyślną, a nie NULL.
    Podłożenie NULL-a udawałoby stan, którego w prawdziwej bazie nie ma."""
    import db

    c = conn.cursor()

    def kolumny(tabela):
        try:
            c.execute(f"PRAGMA table_info({tabela})")
        except sqlite3.Error:
            return set()
        return {r[1] for r in c.fetchall()}

    if kolumny("zadania"):
        # Migracja 8 rozpoznaje podzespoły opon po NAZWIE — musi być co rozpoznać.
        c.execute("SELECT id FROM zadania ORDER BY id LIMIT 1")
        w = c.fetchone()
        if w:
            c.execute("UPDATE zadania SET nazwa='Wymiana opon / Kół' WHERE id=?", (w[0],))
            if "dotyczy_opon" in kolumny("zadania"):
                c.execute("UPDATE zadania SET dotyczy_opon=1 WHERE id=?", (w[0],))
                c.execute("UPDATE zadania SET dotyczy_opon=0 WHERE id<>?", (w[0],))

    kol_auta = kolumny("samochody")
    if "typ_paliwa" in kol_auta:
        # Pierwszy pojazd elektryczny, drugi spalinowy — migracja 33 rozdziela
        # rodzaj energii właśnie po typie paliwa POJAZDU.
        c.execute("SELECT id FROM samochody ORDER BY id")
        for i, auto_id in enumerate(r[0] for r in c.fetchall()):
            c.execute("UPDATE samochody SET typ_paliwa=? WHERE id=?",
                      ("Elektryczny" if i == 0 else "Benzyna", auto_id))

    if "rodzaj_energii" in kolumny("tankowania"):
        # Próbka z wersji, w której kolumna JUŻ jest, ma nieść wynik migracji,
        # a nie losową wartość słownikową.
        c.execute(
            "UPDATE tankowania SET rodzaj_energii = CASE WHEN auto_id IN "
            "(SELECT id FROM samochody WHERE typ_paliwa='Elektryczny') THEN ? ELSE ? END",
            (db.ENERGIA_PRAD, db.ENERGIA_PALIWO),
        )

    # Migracja 38: zapamiętana zakładka „2" (dawne Paliwo) ma zostać przeliczona
    # na Koszty plus podzakładkę Tankowania.
    c.execute(
        "INSERT INTO ustawienia (klucz, wartosc) VALUES ('ostatnia_zakladka', '2') "
        "ON CONFLICT(klucz) DO UPDATE SET wartosc=excluded.wartosc"
    )


# ============================================================================
#  ZAPIS I ODCZYT PRÓBEK
# ============================================================================

def nazwa_probki(wersja):
    return f"schemat_{wersja:02d}.sql"


def probki(katalog=None):
    katalog = pathlib.Path(katalog or KATALOG_PROBEK)
    if not katalog.is_dir():
        return []
    return sorted(katalog.glob("schemat_*.sql"))


def wersja_probki(plik):
    return int(pathlib.Path(plik).stem.split("_")[1])


def odtworz_z_probki(plik, sciezka_docelowa):
    """Buduje bazę SQLite ze zrzutu SQL."""
    conn = sqlite3.connect(sciezka_docelowa)
    conn.executescript(pathlib.Path(plik).read_text(encoding="utf-8"))
    conn.commit()
    conn.close()
    return sciezka_docelowa


def _zrzut(sciezka):
    conn = sqlite3.connect(sciezka)
    try:
        return "\n".join(conn.iterdump()) + "\n"
    finally:
        conn.close()


def zapisz_probki(katalog=None, drabinka=None):
    """DOPISUJE próbki brakujących wersji. Istniejących nie rusza.

    To jest cała wartość tego pliku i najłatwiejsza rzecz do zepsucia.
    Gdyby `--zapisz` przepisywał komplet, wystarczyłoby poprawić starą migrację
    i odświeżyć wzorce — próbka zbudowałaby się poprawionym kodem, wszystko
    zrobiłoby się zielone, a różnica między świeżą a zaktualizowaną bazą
    zostałaby u ludzi.

    Próbka raz zapisana jest więc niezmienna. Świadome przepisanie historii
    wymaga skasowania plików ręcznie — czyli czynności, której nie da się zrobić
    przy okazji."""
    import tempfile

    katalog = pathlib.Path(katalog or KATALOG_PROBEK)
    katalog.mkdir(parents=True, exist_ok=True)
    drabinka = drabinka if drabinka is not None else wczytaj_drabinke()

    dopisane = []
    with tempfile.TemporaryDirectory() as tymczasowy:
        for wersja in range(len(drabinka) + 1):
            cel = katalog / nazwa_probki(wersja)
            if cel.exists():
                continue
            robocza = pathlib.Path(tymczasowy) / f"w{wersja}.db"
            zbuduj_baze_w_wersji(str(robocza), wersja, drabinka)
            zasiej_dane(str(robocza))
            naglowek = (
                f"-- Próbka bazy w wersji schematu {wersja}. PLIK ZAMROŻONY.\n"
                "--\n"
                "-- `python tests/test_migracje.py --zapisz` DOPISUJE tylko brakujące wersje\n"
                "-- i nigdy nie nadpisuje istniejących. Ten plik jest punktem odniesienia,\n"
                "-- nie kodem: gdyby dało się go odświeżyć razem z poprawioną migracją,\n"
                "-- przestałby cokolwiek udowadniać.\n"
            )
            cel.write_text(naglowek + _zrzut(str(robocza)), encoding="utf-8")
            dopisane.append(wersja)

    return dopisane


if __name__ == "__main__":
    import os
    import tempfile

    os.environ.setdefault("FLET_APP_STORAGE_DATA", tempfile.mkdtemp(prefix="probki_"))
    ile = zapisz_probki()
    print(f"Zapisano {ile} próbek w {KATALOG_PROBEK}")
