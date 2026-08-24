import sqlite3
import os
import shutil
import uuid
import time
from contextlib import contextmanager
from date import parsuj_date
from datetime import datetime, timedelta

try:
    from PIL import Image, ImageOps
except ImportError:
    Image = None
    ImageOps = None

STORAGE_PATH = os.environ.get("FLET_APP_STORAGE_DATA", "")
BAZA_DANYCH = os.path.join(STORAGE_PATH, 'flota_zadania.db')
FOLDER_ZALACZNIKI = os.path.join(STORAGE_PATH, "zalaczniki")
FOLDER_ODROCZONE = os.path.join(STORAGE_PATH, "zalaczniki_odroczone")

DOMYSLNE_ZADANIA = [
    "🛢️ Olej silnikowy i filtr", "💨 Filtr powietrza", "🌬️ Filtr kabinowy",
    "⚙️ Pasek / Łańcuch rozrządu", "🛞 Wymiana opon / Kół", "🛑 Klocki hamulcowe", "💿 Tarcze hamulcowe"
]
ROK_MIN = 1950
PROG_KM_POWIADOMIEN = 1500      
PROG_DNI_POWIADOMIEN = 30       
PROG_ILOSC_MAGAZYNU_DOMYSLNY = 1.0    

WALUTY = ["PLN", "EUR", "USD", "GBP", "CZK"]
JEDNOSTKI_SPALANIA = ["l/100km", "km/l", "mpg"]

PROGI_KM_OPCJE = [500, 1000, 1500, 2000, 3000, 5000]
PROGI_DNI_OPCJE = [7, 14, 30, 60, 90]

PRIORYTETY_DO_ZROBIENIA = ["Wysoki", "Średni", "Niski"]
KOLEJNOSC_PRIORYTETU = {"Wysoki": 1, "Średni": 2, "Niski": 3}

KOLORY_MOTYWU = ["Indygo", "Czerwony", "Zielony", "Niebieski", "Szary", "Pomarańczowy", "Fioletowy", "Różowy", "Żółty", "Limonkowy"]

KATEGORIE_MAGAZYNU = ["Płyny eksploatacyjne", "Oleje i smary", "Żarówki i bezpieczniki", "Filtry", "Akcesoria", "Inne"]
JEDNOSTKI_MAGAZYNU = ["szt", "l", "ml", "kg", "g"]

TABELE_Z_ZALACZNIKIEM = {"tankowania", "wizyty", "inne_koszty", "zdjecia_karoserii", "historia", "zestawy_opon", "magazyn_czesci"}

STREFY_KAROSERII = ["Przód", "Tył", "Bok lewy", "Bok prawy", "Wnętrze / Kokpit", "Uszkodzenie / Rysa", "Inne"]
TYPY_ZDJECIA = ["Brak", "Przed naprawą", "Po naprawie"]

OSIE_MONTAZU = ["Wszystkie", "Przód", "Tył"]

@contextmanager
def polacz_baze():
    conn = sqlite3.connect(BAZA_DANYCH)
    conn.execute('PRAGMA foreign_keys = ON;')
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    _upewnij_folder_zalacznikow()
    posprzataj_odroczone_zalaczniki()
    with polacz_baze() as conn:
        cursor = conn.cursor()
        
        # Tabela ustawień potrzebna na samym początku do sprawdzania wersji
        cursor.execute("CREATE TABLE IF NOT EXISTS ustawienia (klucz TEXT PRIMARY KEY, wartosc TEXT)")
        
        cursor.execute("SELECT wartosc FROM ustawienia WHERE klucz='schema_version'")
        w = cursor.fetchone()
        wersja = int(w[0]) if w else 0

        migracje = [
            # Wersja 1: Tworzenie podstawowych tabel (bez późniejszych kolumn)
            """
            CREATE TABLE IF NOT EXISTS samochody (id INTEGER PRIMARY KEY AUTOINCREMENT, nazwa TEXT UNIQUE NOT NULL);
            CREATE TABLE IF NOT EXISTS zadania (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, nazwa TEXT NOT NULL, data TEXT, przebieg INTEGER, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS wizyty (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, data TEXT NOT NULL, przebieg INTEGER NOT NULL, wykonawca TEXT, koszt_calkowity REAL NOT NULL DEFAULT 0.0, notatki TEXT, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS historia (id INTEGER PRIMARY KEY AUTOINCREMENT, wizyta_id INTEGER, zadanie_id INTEGER NOT NULL, data TEXT, przebieg INTEGER, kategoria TEXT, cena REAL DEFAULT 0.0, wykonawca TEXT, FOREIGN KEY (wizyta_id) REFERENCES wizyty(id) ON DELETE CASCADE, FOREIGN KEY (zadanie_id) REFERENCES zadania(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS tankowania (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, data TEXT NOT NULL, przebieg INTEGER NOT NULL, dystans REAL NOT NULL DEFAULT 0.0, litry REAL NOT NULL, kwota REAL NOT NULL, do_pelna INTEGER DEFAULT 1, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS inne_koszty (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, data TEXT NOT NULL, kategoria TEXT NOT NULL, nazwa TEXT, kwota REAL NOT NULL, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS zestawy_opon (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, sezon TEXT, rozmiar TEXT, marka_model TEXT, glebokosc_bieznika REAL, data_pomiaru TEXT, numer_dot TEXT, ilosc INTEGER DEFAULT 4, zamontowane INTEGER DEFAULT 0, data_zakupu TEXT, przebieg_zakupu INTEGER, notatki TEXT, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS do_zrobienia (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, tytul TEXT NOT NULL, opis TEXT, priorytet TEXT, szacowany_koszt REAL, termin TEXT, zadanie_id INTEGER, wykonane INTEGER DEFAULT 0, data_utworzenia TEXT, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE, FOREIGN KEY (zadanie_id) REFERENCES zadania(id) ON DELETE SET NULL);
            CREATE TABLE IF NOT EXISTS tagi (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, nazwa TEXT NOT NULL, kolor TEXT NOT NULL, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS magazyn_czesci (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, nazwa TEXT NOT NULL, kategoria TEXT, ilosc REAL NOT NULL DEFAULT 1, jednostka TEXT DEFAULT 'szt', cena REAL, data_zakupu TEXT, notatki TEXT, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS wizyta_czesci_magazynu (id INTEGER PRIMARY KEY AUTOINCREMENT, wizyta_id INTEGER NOT NULL, magazyn_id INTEGER NOT NULL, ilosc_uzyta REAL NOT NULL DEFAULT 1, FOREIGN KEY (wizyta_id) REFERENCES wizyty(id) ON DELETE CASCADE, FOREIGN KEY (magazyn_id) REFERENCES magazyn_czesci(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS zdjecia_karoserii (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, data TEXT NOT NULL, strefa TEXT NOT NULL, zalacznik TEXT NOT NULL, opis TEXT, przebieg INTEGER, typ_porownania TEXT, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE);
            """,
            
            # Wersja 2: Kolumny dodatkowe dla samochodow
            """
            ALTER TABLE samochody ADD COLUMN oc_data TEXT;
            ALTER TABLE samochody ADD COLUMN przeglad_data TEXT;
            ALTER TABLE samochody ADD COLUMN nr_rej TEXT;
            ALTER TABLE samochody ADD COLUMN vin TEXT;
            ALTER TABLE samochody ADD COLUMN rok_produkcji TEXT;
            ALTER TABLE samochody ADD COLUMN pojemnosc_silnika TEXT;
            ALTER TABLE samochody ADD COLUMN moc_silnika TEXT;
            ALTER TABLE samochody ADD COLUMN typ_paliwa TEXT;
            ALTER TABLE samochody ADD COLUMN skrzynia_biegow TEXT;
            ALTER TABLE samochody ADD COLUMN notatki TEXT;
            ALTER TABLE samochody ADD COLUMN wycieraczki_przod TEXT;
            ALTER TABLE samochody ADD COLUMN wycieraczki_tyl TEXT;
            ALTER TABLE samochody ADD COLUMN cisnienie_przod TEXT;
            ALTER TABLE samochody ADD COLUMN cisnienie_tyl TEXT;
            ALTER TABLE samochody ADD COLUMN olej_typ TEXT;
            ALTER TABLE samochody ADD COLUMN olej_pojemnosc TEXT;
            ALTER TABLE samochody ADD COLUMN akumulator TEXT;
            ALTER TABLE samochody ADD COLUMN zarowki_mijania TEXT;
            ALTER TABLE samochody ADD COLUMN zarowki_drogowe TEXT;
            ALTER TABLE samochody ADD COLUMN ac_data TEXT;
            ALTER TABLE samochody ADD COLUMN assistance_data TEXT;
            ALTER TABLE samochody ADD COLUMN gasnica_data TEXT;
            ALTER TABLE samochody ADD COLUMN apteczka_data TEXT;
            ALTER TABLE samochody ADD COLUMN zdjecie_glowne TEXT;
            """,
            
            # Wersja 3: Kolumny dla zadania
            """
            ALTER TABLE zadania ADD COLUMN interwal_km INTEGER;
            ALTER TABLE zadania ADD COLUMN interwal_miesiace INTEGER;
            """,
            
            # Wersja 4: Kolumny dla historia, tankowania, zestawy_opon
            """
            ALTER TABLE historia ADD COLUMN zalacznik TEXT;
            ALTER TABLE tankowania ADD COLUMN stacja TEXT;
            ALTER TABLE zestawy_opon ADD COLUMN cena REAL DEFAULT 0.0;
            """,

            # Wersja 5: Tagi i załączniki
            """
            ALTER TABLE tankowania ADD COLUMN tagi TEXT;
            ALTER TABLE tankowania ADD COLUMN zalacznik TEXT;
            ALTER TABLE wizyty ADD COLUMN tagi TEXT;
            ALTER TABLE wizyty ADD COLUMN zalacznik TEXT;
            ALTER TABLE inne_koszty ADD COLUMN tagi TEXT;
            ALTER TABLE inne_koszty ADD COLUMN zalacznik TEXT;
            """,
            
            # Wersja 6: Marka, model, generacja
            """
            ALTER TABLE samochody ADD COLUMN marka TEXT;
            ALTER TABLE samochody ADD COLUMN model TEXT;
            ALTER TABLE samochody ADD COLUMN generacja TEXT;
            """,

            # Wersja 7: Indeksy przyspieszające zapytania po auto_id i kluczach obcych
            """
            CREATE INDEX IF NOT EXISTS idx_zadania_auto ON zadania(auto_id);
            CREATE INDEX IF NOT EXISTS idx_wizyty_auto ON wizyty(auto_id);
            CREATE INDEX IF NOT EXISTS idx_tankowania_auto ON tankowania(auto_id);
            CREATE INDEX IF NOT EXISTS idx_inne_koszty_auto ON inne_koszty(auto_id);
            CREATE INDEX IF NOT EXISTS idx_zestawy_opon_auto ON zestawy_opon(auto_id);
            CREATE INDEX IF NOT EXISTS idx_do_zrobienia_auto ON do_zrobienia(auto_id);
            CREATE INDEX IF NOT EXISTS idx_tagi_auto ON tagi(auto_id);
            CREATE INDEX IF NOT EXISTS idx_magazyn_czesci_auto ON magazyn_czesci(auto_id);
            CREATE INDEX IF NOT EXISTS idx_zdjecia_karoserii_auto ON zdjecia_karoserii(auto_id);
            CREATE INDEX IF NOT EXISTS idx_historia_zadanie ON historia(zadanie_id);
            CREATE INDEX IF NOT EXISTS idx_historia_wizyta ON historia(wizyta_id);
            CREATE INDEX IF NOT EXISTS idx_do_zrobienia_zadanie ON do_zrobienia(zadanie_id);
            CREATE INDEX IF NOT EXISTS idx_wizyta_czesci_wizyta ON wizyta_czesci_magazynu(wizyta_id);
            CREATE INDEX IF NOT EXISTS idx_wizyta_czesci_magazyn ON wizyta_czesci_magazynu(magazyn_id);
            """,
            # Wersja 8: Jawna flaga „dotyczy opon” w podzespole — zastępuje zgadywanie
            # po nazwie (np. „opon”/„kół”), które gubiło się przy innych określeniach.
            """
            ALTER TABLE zadania ADD COLUMN dotyczy_opon INTEGER DEFAULT 0;
            """,

            # Wersja 9: Niezależne montowanie zestawu opon per oś (przód/tył) —
            # pozwala trzymać osobne, asymetryczne komplety jednocześnie.
            """
            ALTER TABLE zestawy_opon ADD COLUMN os_montazu TEXT DEFAULT 'Wszystkie';
            """,

            # Wersja 10: Załączniki dla opon i części w magazynie
            """
            ALTER TABLE zestawy_opon ADD COLUMN zalacznik TEXT;
            ALTER TABLE magazyn_czesci ADD COLUMN zalacznik TEXT;
            """,

            # Wersja 11: Indywidualny próg ostrzegania o niskim stanie per pozycja
            # magazynowa — zastępuje sztywny, wspólny dla wszystkich próg "<=1 szt.".
            """
            ALTER TABLE magazyn_czesci ADD COLUMN prog_ostrzezenia REAL DEFAULT 1;
            """
        ]

        for i in range(wersja, len(migracje)):
            for stmt in migracje[i].split(';'):
                stmt = stmt.strip()
                if stmt:
                    try:
                        cursor.execute(stmt)
                    except sqlite3.OperationalError as e:
                        # Przechwytujemy błędy, jeśli jakaś starsza baza dostała już te kolumny przez "PRAGMA table_info"
                        if "duplicate column name" not in str(e).lower():
                            raise e
                        print(f"[migracja {i+1}] Pominięto (kolumna już istnieje): {stmt.splitlines()[0][:80]}")

            # Jednorazowe uzupełnienie danych po dodaniu kolumny dotyczy_opon (wersja 8) —
            # dla istniejących podzespołów odtwarzamy dawne zachowanie na podstawie starej,
            # nazwowej heurystyki, żeby po aktualizacji nic nie „zniknęło”.
            if i == 7:
                cursor.execute("SELECT id, nazwa FROM zadania")
                for zid, znazwa in cursor.fetchall():
                    nazwa_l = (znazwa or "").lower()
                    if "opon" in nazwa_l or "kół" in nazwa_l or "kol" in nazwa_l:
                        cursor.execute("UPDATE zadania SET dotyczy_opon=1 WHERE id=?", (zid,))

            cursor.execute(
                "INSERT INTO ustawienia (klucz, wartosc) VALUES ('schema_version', ?) "
                "ON CONFLICT(klucz) DO UPDATE SET wartosc=excluded.wartosc", 
                (str(i + 1),)
            )

def pobierz_ustawienie(klucz, domyslna=None):
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT wartosc FROM ustawienia WHERE klucz=?", (klucz,))
        w = c.fetchone()
        return w[0] if w else domyslna

def zapisz_ustawienie(klucz, wartosc):
    with polacz_baze() as conn:
        conn.execute(
            "INSERT INTO ustawienia (klucz, wartosc) VALUES (?, ?) "
            "ON CONFLICT(klucz) DO UPDATE SET wartosc=excluded.wartosc",
            (klucz, wartosc)
        )

def pobierz_walute():
    w = pobierz_ustawienie("waluta", "PLN")
    return w if w in WALUTY else "PLN"

def pobierz_jednostke_spalania():
    w = pobierz_ustawienie("jednostka_spalania", "l/100km")
    return w if w in JEDNOSTKI_SPALANIA else "l/100km"

def pobierz_kolor_motywu():
    w = pobierz_ustawienie("kolor_motywu", "Indygo")
    return w if w in KOLORY_MOTYWU else "Indygo"

def pobierz_prog_km():
    return int(pobierz_ustawienie("prog_km_powiadomien", str(PROG_KM_POWIADOMIEN)) or PROG_KM_POWIADOMIEN)

def pobierz_prog_dni():
    return int(pobierz_ustawienie("prog_dni_powiadomien", str(PROG_DNI_POWIADOMIEN)) or PROG_DNI_POWIADOMIEN)

def zainicjuj_domyslne_auto(state):
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT id, nazwa FROM samochody ORDER BY nazwa")
        auta = c.fetchall()
    if not auta:
        state.auto_id = None
        state.auto_nazwa = "Brak pojazdów"
        return
    aktualne_id = state.auto_id
    for a_id, a_nazwa in auta:
        if a_id == aktualne_id:
            state.auto_nazwa = str(a_nazwa)
            return
    state.auto_id = auta[0][0]
    state.auto_nazwa = str(auta[0][1])

def pobierz_aktualny_przebieg(auto_id):
    if not auto_id: return 0
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT MAX(przebieg) FROM tankowania WHERE auto_id = ?", (auto_id,))
        mt = int(c.fetchone()[0] or 0)
        c.execute("SELECT MAX(przebieg) FROM wizyty WHERE auto_id = ?", (auto_id,))
        mw = int(c.fetchone()[0] or 0)
        c.execute("SELECT MAX(h.przebieg) FROM historia h JOIN zadania z ON h.zadanie_id = z.id WHERE z.auto_id = ?", (auto_id,))
        mh = int(c.fetchone()[0] or 0)
        return max(mt, mw, mh)

def sprawdz_czy_przebieg_podejrzany(auto_id, nowy_przebieg, wyklucz_id=None, tabela=None, nowa_data_str=None):
    """Zwraca ostrzeżenie (str), jeśli nowy_przebieg jest wyraźnie niższy niż
    najwyższy dotychczas zapisany wpis dla tego auta, albo jeśli oznaczałby
    nierealnie duży dzienny przebieg względem ostatniego chronologicznie
    wpisu (np. literówka z brakującą lub dodatkową cyfrą). Sprawdza
    tankowania, wizyty oraz pojedyncze wpisy w historii (niepowiązane z
    wizytą zbiorczą — te powiązane odzwierciedla już przebieg samej wizyty)."""
    if not auto_id or not nowy_przebieg or nowy_przebieg <= 0:
        return None

    with polacz_baze() as conn:
        c = conn.cursor()
        wpisy = []

        wyklucz_sql = " AND id != ?" if (tabela == "tankowania" and wyklucz_id) else ""
        params = [auto_id] + ([wyklucz_id] if wyklucz_sql else [])
        c.execute(f"SELECT przebieg, data FROM tankowania WHERE auto_id=?{wyklucz_sql}", params)
        wpisy += c.fetchall()

        wyklucz_sql = " AND id != ?" if (tabela == "wizyty" and wyklucz_id) else ""
        params = [auto_id] + ([wyklucz_id] if wyklucz_sql else [])
        c.execute(f"SELECT przebieg, data FROM wizyty WHERE auto_id=?{wyklucz_sql}", params)
        wpisy += c.fetchall()

        wyklucz_sql = " AND h.id != ?" if (tabela == "historia" and wyklucz_id) else ""
        params = [auto_id] + ([wyklucz_id] if wyklucz_sql else [])
        c.execute(
            f"SELECT h.przebieg, h.data FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
            f"WHERE z.auto_id=? AND h.wizyta_id IS NULL{wyklucz_sql}", params
        )
        wpisy += c.fetchall()

    najwyzszy_dotychczas = None
    przebieg_ostatni, data_ostatniego = None, None

    for przebieg_raw, data_str in wpisy:
        przebieg = int(przebieg_raw or 0)
        najwyzszy_dotychczas = przebieg if najwyzszy_dotychczas is None else max(najwyzszy_dotychczas, przebieg)

        d = parsuj_date(data_str)
        if d != datetime.min.date() and (data_ostatniego is None or d > data_ostatniego):
            data_ostatniego, przebieg_ostatni = d, przebieg

    # 1) Przebieg niższy niż najwyższy dotychczas zapisany wpis (np. brakująca cyfra)
    if najwyzszy_dotychczas is not None and nowy_przebieg < najwyzszy_dotychczas:
        return (
            f"Uwaga: podany przebieg ({nowy_przebieg} km) jest niższy niż najwyższy dotychczas "
            f"zapisany wpis ({najwyzszy_dotychczas} km). Sprawdź, czy nie brakuje cyfry."
        )

    # 2) Nierealnie duży skok w górę względem ostatniego chronologicznie wpisu (np. dodatkowa cyfra)
    if przebieg_ostatni is not None and nowy_przebieg > przebieg_ostatni:
        nowa_data = parsuj_date(nowa_data_str) if nowa_data_str else datetime.now().date()
        if nowa_data == datetime.min.date():
            nowa_data = datetime.now().date()
            
        dni_od_ostatniego = max(1, (nowa_data - data_ostatniego).days)
        sredni_dzienny = oblicz_sredni_dzienny_przebieg(auto_id) or 150.0
        limit_dzienny = max(sredni_dzienny * 5, 500.0)
        implikowany_dzienny = (nowy_przebieg - przebieg_ostatni) / dni_od_ostatniego
        if implikowany_dzienny > limit_dzienny:
            return (
                f"Uwaga: od ostatniego wpisu ({przebieg_ostatni} km) minęło {dni_od_ostatniego} dni. "
                f"Wynikałoby to na ok. {int(implikowany_dzienny)} km/dzień. Sprawdź, czy nie ma dodatkowej cyfry w przebiegu."
            )

    return None

def oblicz_sredni_dzienny_przebieg(auto_id, min_dni=7):
    if not auto_id:
        return None

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT data, przebieg FROM tankowania WHERE auto_id=?", (auto_id,))
        wiersze = c.fetchall()

    punkty = [(parsuj_date(d), int(p)) for d, p in wiersze]
    punkty = [p for p in punkty if p[0] != datetime.min.date()]
    if len(punkty) < 2:
        return None

    punkty.sort(key=lambda p: p[0])
    pierwsza_data, pierwszy_przebieg = punkty[0]
    ostatnia_data, ostatni_przebieg = punkty[-1]

    dni_roznica = (ostatnia_data - pierwsza_data).days
    km_roznica = ostatni_przebieg - pierwszy_przebieg

    if dni_roznica < min_dni or km_roznica <= 0:
        return None

    return km_roznica / dni_roznica

def aktualizuj_najnowszy_wpis(zadanie_id):
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT data, przebieg FROM historia WHERE zadanie_id = ?", (zadanie_id,))
        wpisy = c.fetchall()
        if wpisy:
            wpisy.sort(key=lambda x: (parsuj_date(x[0]), int(x[1] or 0)), reverse=True)
            c.execute("UPDATE zadania SET data=?, przebieg=? WHERE id=?", (wpisy[0][0], int(wpisy[0][1] or 0), zadanie_id))
        else:
            c.execute("UPDATE zadania SET data=NULL, przebieg=NULL WHERE id=?", (zadanie_id,))

def przelicz_wszystkie_zadania(auto_id):
    if not auto_id: return
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT id FROM zadania WHERE auto_id = ?", (auto_id,))
        for r in c.fetchall():
            aktualizuj_najnowszy_wpis(r[0])

def pobierz_powiadomienia(auto_id, prog_km=None, prog_dni=None):
    if not auto_id:
        return []

    if prog_km is None: prog_km = pobierz_prog_km()
    if prog_dni is None: prog_dni = pobierz_prog_dni()

    wyniki = []
    dzis = datetime.now().date()
    aktualny_przebieg = pobierz_aktualny_przebieg(auto_id) or 0
    sredni_dzienny_przebieg = oblicz_sredni_dzienny_przebieg(auto_id)

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute(
            "SELECT id, nazwa, data, przebieg, interwal_km, interwal_miesiace FROM zadania "
            "WHERE auto_id=? AND (interwal_km IS NOT NULL OR interwal_miesiace IS NOT NULL)",
            (auto_id,)
        )
        for z in c.fetchall():
            powody, status_zadania = [], None

            if z["interwal_km"] and z["przebieg"] and aktualny_przebieg:
                zost_km = (int(z["przebieg"]) + int(z["interwal_km"])) - aktualny_przebieg
                if zost_km <= prog_km:
                    s = "przeterminowane" if zost_km < 0 else "pilne"
                    if zost_km < 0:
                        powody.append(f"Przekroczono o {abs(zost_km)} km")
                    else:
                        import utils
                        prognoza = utils.formatuj_prognoze_km(zost_km, sredni_dzienny_przebieg)
                        powody.append(f"Zostało {prognoza}")
                    status_zadania = s

            if z["interwal_miesiace"] and z["data"]:
                d_w = parsuj_date(z["data"])
                if d_w != datetime.min.date():
                    termin = d_w + timedelta(days=int(float(z["interwal_miesiace"]) * 30.5))
                    zost_dni = (termin - dzis).days
                    if zost_dni <= prog_dni:
                        s = "przeterminowane" if zost_dni < 0 else "pilne"
                        powody.append(f"Przekroczono o {abs(zost_dni)} dni" if zost_dni < 0 else f"Zostało {zost_dni} dni")
                        if status_zadania != "przeterminowane":
                            status_zadania = s

            if powody:
                wyniki.append({
                    "typ": "podzespol", "tytul": z["nazwa"], "opis": " • ".join(powody),
                    "status": status_zadania, "trasa": f"/zadanie/edytuj/{z['id']}",
                })

        c.execute(
            "SELECT oc_data, przeglad_data, ac_data, assistance_data, gasnica_data, apteczka_data "
            "FROM samochody WHERE id=?", (auto_id,)
        )
        w = c.fetchone()
        if w:
            terminy_dokumentow = (
                ("Polisa OC", w["oc_data"]),
                ("Przegląd techniczny", w["przeglad_data"]),
                ("Polisa AC", w["ac_data"]),
                ("Assistance", w["assistance_data"]),
                ("Gaśnica", w["gasnica_data"]),
                ("Apteczka", w["apteczka_data"]),
            )
            for etykieta, txt in terminy_dokumentow:
                if not txt:
                    continue
                d_w = parsuj_date(txt)
                if d_w == datetime.min.date():
                    continue
                zost_dni = (d_w - dzis).days
                if zost_dni <= prog_dni:
                    s = "przeterminowane" if zost_dni < 0 else "pilne"
                    opis = f"Przekroczono o {abs(zost_dni)} dni" if zost_dni < 0 else f"Zostało {zost_dni} dni"
                    wyniki.append({
                        "typ": "dokument", "tytul": etykieta, "opis": opis,
                        "status": s, "trasa": f"/auto/edytuj/{auto_id}",
                    })

        # Niski stan magazynu (części i płyny) — indywidualny próg per pozycja,
        # z fallbackiem na wspólną wartość domyślną dla starszych wpisów bez własnego progu.
        import utils
        c.execute(
            "SELECT nazwa, ilosc, jednostka, prog_ostrzezenia FROM magazyn_czesci WHERE auto_id=?",
            (auto_id,)
        )
        for m in c.fetchall():
            prog_wlasny = m["prog_ostrzezenia"]
            prog_magazynu = float(prog_wlasny) if prog_wlasny is not None else PROG_ILOSC_MAGAZYNU_DOMYSLNY
            ilosc_m = float(m["ilosc"] or 0)
            if ilosc_m <= prog_magazynu:
                s = "przeterminowane" if ilosc_m <= 0 else "pilne"
                jednostka_m = m["jednostka"] or "szt"
                opis = "Brak na stanie" if ilosc_m <= 0 else f"Zostało {utils.formatuj_liczba(ilosc_m, 2)} {jednostka_m}"
                wyniki.append({
                    "typ": "magazyn", "tytul": m["nazwa"], "opis": opis,
                    "status": s, "trasa": "/magazyn",
                })

    kolejnosc = {"przeterminowane": 0, "pilne": 1}
    wyniki.sort(key=lambda w: kolejnosc.get(w["status"], 2))
    return wyniki

def pobierz_dane_do_porownania(auto_id):
    """Zbiorcze dane pojazdu (specyfikacja, koszty, przebieg, spalanie, serwis)
    wykorzystywane przez ekran porównania pojazdów. Zwraca None, jeśli auto nie istnieje."""
    if not auto_id:
        return None

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT nazwa, nr_rej, rok_produkcji, pojemnosc_silnika, moc_silnika, "
            "typ_paliwa, skrzynia_biegow, oc_data, przeglad_data, ac_data, assistance_data, "
            "zdjecie_glowne FROM samochody WHERE id=?",
            (auto_id,)
        )
        w = c.fetchone()
        if not w:
            return None
        dane = dict(w)

        c.execute("SELECT COALESCE(SUM(kwota),0) FROM tankowania WHERE auto_id=?", (auto_id,))
        dane["koszt_paliwo"] = float(c.fetchone()[0] or 0.0)

        c.execute(
            "SELECT COALESCE(SUM(h.cena),0) FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE z.auto_id=? AND h.wizyta_id IS NULL", (auto_id,)
        )
        koszt_historia = float(c.fetchone()[0] or 0.0)
        c.execute("SELECT COALESCE(SUM(koszt_calkowity),0) FROM wizyty WHERE auto_id=?", (auto_id,))
        koszt_wizyty = float(c.fetchone()[0] or 0.0)
        dane["koszt_serwis"] = koszt_historia + koszt_wizyty

        c.execute("SELECT COALESCE(SUM(kwota),0) FROM inne_koszty WHERE auto_id=?", (auto_id,))
        dane["koszt_inne"] = float(c.fetchone()[0] or 0.0)

        dane["koszt_razem"] = dane["koszt_paliwo"] + dane["koszt_serwis"] + dane["koszt_inne"]

        c.execute("SELECT przebieg, litry, do_pelna FROM tankowania WHERE auto_id=? ORDER BY przebieg", (auto_id,))
        tankowania = c.fetchall()

        c.execute("SELECT COUNT(*) FROM historia h JOIN zadania z ON h.zadanie_id=z.id WHERE z.auto_id=?", (auto_id,))
        dane["liczba_wpisow_historii"] = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM wizyty WHERE auto_id=?", (auto_id,))
        dane["liczba_wizyt"] = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM do_zrobienia WHERE auto_id=? AND wykonane=0", (auto_id,))
        dane["do_zrobienia_aktywne"] = c.fetchone()[0]
        c.execute(
            "SELECT COUNT(*) FROM magazyn_czesci WHERE auto_id=? AND ilosc <= COALESCE(prog_ostrzezenia, 1)",
            (auto_id,)
        )
        dane["magazyn_niski_stan"] = c.fetchone()[0]

    dane["aktualny_przebieg"] = pobierz_aktualny_przebieg(auto_id)
    dane["sredni_dzienny"] = oblicz_sredni_dzienny_przebieg(auto_id)

    dystans = 0
    if len(tankowania) >= 2:
        dystans = max(0, int(tankowania[-1]["przebieg"] or 0) - int(tankowania[0]["przebieg"] or 0))
    dane["koszt_km"] = (dane["koszt_razem"] / dystans) if dystans > 0 else None

    spalanie = None
    peln_idx = [i for i, t in enumerate(tankowania) if t["do_pelna"]]
    if len(peln_idx) >= 2:
        p, o = peln_idx[0], peln_idx[-1]
        d_p = int(tankowania[o]["przebieg"] or 0) - int(tankowania[p]["przebieg"] or 0)
        l_p = sum(float(tankowania[k]["litry"] or 0) for k in range(p + 1, o + 1))
        if d_p > 0:
            spalanie = (l_p / d_p) * 100
    dane["spalanie"] = spalanie

    powiadomienia = pobierz_powiadomienia(auto_id)
    dane["przeterminowane"] = sum(1 for p in powiadomienia if p["status"] == "przeterminowane")
    dane["pilne"] = sum(1 for p in powiadomienia if p["status"] == "pilne")

    return dane

def oznacz_zamontowany_zestaw(auto_id, zestaw_id, os_montazu="Wszystkie"):
    """Montuje zestaw opon na wskazanej osi. Zestaw montowany na całym aucie
    ('Wszystkie') wyklucza wszystkie pozostałe. Zestaw montowany na pojedynczej
    osi koliduje TYLKO z innym zestawem zajmującym tę samą oś (albo z zestawem
    'Wszystkie') — dzięki temu można mieć osobny, asymetryczny komplet
    jednocześnie z przodu i z tyłu."""
    if os_montazu not in OSIE_MONTAZU:
        os_montazu = "Wszystkie"

    with polacz_baze() as conn:
        if os_montazu == "Wszystkie":
            conn.execute("UPDATE zestawy_opon SET zamontowane=0, os_montazu='Wszystkie' WHERE auto_id=?", (auto_id,))
        else:
            conn.execute(
                "UPDATE zestawy_opon SET zamontowane=0 WHERE auto_id=? AND (os_montazu=? OR os_montazu='Wszystkie')",
                (auto_id, os_montazu)
            )
        conn.execute("UPDATE zestawy_opon SET zamontowane=1, os_montazu=? WHERE id=?", (os_montazu, zestaw_id))

def usun_z_cofnieciem(tabela, rekord_id):
    """Usuwa pojedynczy rekord i zwraca callback cofnij() przywracający go z tymi
    samymi wartościami (i tym samym id, o ile nic go w międzyczasie nie zajęło).
    Dla tabel z załącznikiem plik NIE jest fizycznie kasowany od razu — zostaje
    przeniesiony do folderu tymczasowego i wraca na miejsce przy cofnięciu, albo
    zostaje skasowany dopiero wywołaniem usun_odroczony_zalacznik()."""
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(f"PRAGMA table_info({tabela})")
        kolumny = [r["name"] for r in c.fetchall()]

        c.execute(f"SELECT * FROM {tabela} WHERE id=?", (rekord_id,))
        wiersz = c.fetchone()
        if not wiersz:
            return None
        dane = {k: wiersz[k] for k in kolumny}

    sciezka_tymczasowa = None
    if tabela in TABELE_Z_ZALACZNIKIEM:
        oryginalna = dane.get("zalacznik")
        if oryginalna and os.path.exists(oryginalna):
            folder_tmp = _upewnij_folder_odroczonych()
            sciezka_tymczasowa = os.path.join(folder_tmp, os.path.basename(oryginalna))
            try:
                shutil.move(oryginalna, sciezka_tymczasowa)
            except Exception:
                sciezka_tymczasowa = None

    with polacz_baze() as conn:
        conn.execute(f"DELETE FROM {tabela} WHERE id=?", (rekord_id,))

    stan = {"cofniete": False, "trwale_usuniete": False}

    def cofnij():
        if stan["cofniete"] or stan["trwale_usuniete"]:
            return
        stan["cofniete"] = True

        if sciezka_tymczasowa and os.path.exists(sciezka_tymczasowa):
            try:
                shutil.move(sciezka_tymczasowa, dane["zalacznik"])
            except Exception:
                pass

        kolumny_bez_id = [k for k in kolumny if k != "id"]
        wartosci = tuple(dane[k] for k in kolumny_bez_id)
        placeholders = ",".join("?" for _ in kolumny_bez_id)
        nazwy = ",".join(kolumny_bez_id)

        with polacz_baze() as conn:
            conn.execute(f"INSERT INTO {tabela} ({nazwy}) VALUES ({placeholders})", wartosci)

    def finalizuj_usuniecie():
        """Wywołać po upłynięciu okna na cofnięcie — kasuje fizycznie odłożony plik."""
        if stan["cofniete"]:
            return
        stan["trwale_usuniete"] = True
        if sciezka_tymczasowa:
            usun_plik_zalacznika(sciezka_tymczasowa)

    return {"cofnij": cofnij, "finalizuj": finalizuj_usuniecie, "dane": dane}

def usun_wiele_z_cofnieciem(tabela, ids_list):
    """Grupowe usuwanie z możliwością cofnięcia. Zwraca callback cofnij() i finalizuj()."""
    if not ids_list:
        return None

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(f"PRAGMA table_info({tabela})")
        kolumny = [r["name"] for r in c.fetchall()]

        placeholders = ",".join("?" for _ in ids_list)
        c.execute(f"SELECT * FROM {tabela} WHERE id IN ({placeholders})", tuple(ids_list))
        wiersze = c.fetchall()

        if not wiersze:
            return None
        dane_lista = [{k: w[k] for k in kolumny} for w in wiersze]

    sciezki_tymczasowe = []
    if tabela in TABELE_Z_ZALACZNIKIEM:
        folder_tmp = _upewnij_folder_odroczonych()
        for dane in dane_lista:
            oryginalna = dane.get("zalacznik")
            if oryginalna and os.path.exists(oryginalna):
                # Unikalny prefiks, by pliki o tej samej nazwie się nie nadpisały przy usuwaniu wielu
                sciezka_tmp = os.path.join(folder_tmp, f"bulk_{uuid.uuid4().hex}_{os.path.basename(oryginalna)}")
                try:
                    shutil.move(oryginalna, sciezka_tmp)
                    sciezki_tymczasowe.append((sciezka_tmp, oryginalna))
                except Exception:
                    pass

    with polacz_baze() as conn:
        conn.execute(f"DELETE FROM {tabela} WHERE id IN ({placeholders})", tuple(ids_list))

    stan = {"cofniete": False, "trwale_usuniete": False}

    def cofnij():
        if stan["cofniete"] or stan["trwale_usuniete"]:
            return
        stan["cofniete"] = True

        for tmp, oryg in sciezki_tymczasowe:
            if os.path.exists(tmp):
                try:
                    shutil.move(tmp, oryg)
                except Exception:
                    pass

        kolumny_bez_id = [k for k in kolumny if k != "id"]
        placeholders_ins = ",".join("?" for _ in kolumny_bez_id)
        nazwy = ",".join(kolumny_bez_id)

        with polacz_baze() as conn:
            for dane in dane_lista:
                wartosci = tuple(dane[k] for k in kolumny_bez_id)
                conn.execute(f"INSERT INTO {tabela} ({nazwy}) VALUES ({placeholders_ins})", wartosci)

    def finalizuj_usuniecie():
        if stan["cofniete"]:
            return
        stan["trwale_usuniete"] = True
        for tmp, _ in sciezki_tymczasowe:
            usun_plik_zalacznika(tmp)

    return {"cofnij": cofnij, "finalizuj": finalizuj_usuniecie}

def _upewnij_folder_odroczonych():
    os.makedirs(FOLDER_ODROCZONE, exist_ok=True)
    return FOLDER_ODROCZONE

def posprzataj_odroczone_zalaczniki(starsze_niz_sekundy=3600):
    """Usuwa pliki z folderu odroczonego, które zalegają dłużej niż określony czas."""
    folder = _upewnij_folder_odroczonych()
    try:
        obecny_czas = time.time()
        for nazwa_pliku in os.listdir(folder):
            sciezka = os.path.join(folder, nazwa_pliku)
            if os.path.isfile(sciezka):
                czas_modyfikacji = os.path.getmtime(sciezka)
                # Jeśli plik leży dłużej niż godzina (nagłe zamknięcie aplikacji)
                if (obecny_czas - czas_modyfikacji) > starsze_niz_sekundy:
                    try:
                        os.remove(sciezka)
                    except Exception:
                        pass
    except Exception:
        pass

def przelacz_wykonane_do_zrobienia(pozycja_id, status):
    with polacz_baze() as conn:
        conn.execute("UPDATE do_zrobienia SET wykonane=? WHERE id=?", (1 if status else 0, pozycja_id))

def utworz_wizyte_z_do_zrobienia(auto_id, ids_list, utworz_podzespoly=False):
    """Zwraca (wizyta_id, duplikaty, wynik_cofniecia). wynik_cofniecia to słownik
    {"cofnij": fn, "finalizuj": fn} analogiczny do pozostałych operacji usuwających —
    pozwala pokazać snackbar z możliwością cofnięcia całej operacji."""
    if not ids_list: return None, [], None
    dzis = datetime.now().strftime("%d.%m.%Y")
    prz = pobierz_aktualny_przebieg(auto_id) or 0
    duplikaty = []
    nowo_utworzone_zadania_ids = []

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("PRAGMA table_info(do_zrobienia)")
        kol_dz = [r["name"] for r in cur.fetchall()]

        placeholders = ",".join("?" for _ in ids_list)
        cur.execute(f"SELECT * FROM do_zrobienia WHERE id IN ({placeholders})", tuple(ids_list))
        do_zrobienia_dane = [{k: w[k] for k in kol_dz} for w in cur.fetchall()]
        pozycje = [(d["tytul"], d["szacowany_koszt"], d["zadanie_id"]) for d in do_zrobienia_dane]

        suma_kosztow = sum((p[1] or 0.0) for p in pozycje)
        tytuly = [p[0] for p in pozycje]
        notatki = "Utworzono z listy: " + ", ".join(tytuly)

        cur.execute("INSERT INTO wizyty (auto_id, data, przebieg, wykonawca, koszt_calkowity, notatki) VALUES (?,?,?,?,?,?)",
                    (auto_id, dzis, prz, "", suma_kosztow, notatki))
        wizyta_id = cur.lastrowid

        for tytul, koszt, zadanie_id in pozycje:
            czy_opony = False
            if not zadanie_id and utworz_podzespoly:
                cur.execute("SELECT id, nazwa, dotyczy_opon FROM zadania WHERE auto_id=? AND LOWER(nazwa)=LOWER(?)", (auto_id, tytul.strip()))
                istniejacy = cur.fetchone()

                if istniejacy:
                    zadanie_id = istniejacy["id"]
                    czy_opony = bool(istniejacy["dotyczy_opon"])
                    duplikaty.append(istniejacy["nazwa"])
                else:
                    czy_opony = 1 if "opon" in tytul.lower() or "kół" in tytul.lower() else 0
                    cur.execute("INSERT INTO zadania (auto_id, nazwa, dotyczy_opon) VALUES (?,?,?)", (auto_id, tytul.strip(), czy_opony))
                    zadanie_id = cur.lastrowid
                    nowo_utworzone_zadania_ids.append(zadanie_id)
            elif zadanie_id:
                cur.execute("SELECT dotyczy_opon FROM zadania WHERE id=?", (zadanie_id,))
                w = cur.fetchone()
                if w: czy_opony = bool(w["dotyczy_opon"])

            if zadanie_id:
                kat = "Letnie" if czy_opony else None
                cur.execute("INSERT INTO historia (wizyta_id, zadanie_id, data, przebieg, cena, wykonawca, kategoria) VALUES (?,?,?,?,?,?,?)",
                            (wizyta_id, zadanie_id, dzis, prz, koszt or 0.0, "", kat))

        cur.execute(f"DELETE FROM do_zrobienia WHERE id IN ({placeholders})", tuple(ids_list))

    przelicz_wszystkie_zadania(auto_id)

    stan = {"cofniete": False}

    def cofnij():
        if stan["cofniete"]:
            return
        stan["cofniete"] = True
        with polacz_baze() as conn:
            conn.execute("DELETE FROM wizyty WHERE id=?", (wizyta_id,))  # kaskadowo skasuje wpisy historii tej wizyty
            if nowo_utworzone_zadania_ids:
                p_z = ",".join("?" for _ in nowo_utworzone_zadania_ids)
                conn.execute(f"DELETE FROM zadania WHERE id IN ({p_z})", tuple(nowo_utworzone_zadania_ids))
            if do_zrobienia_dane:
                kol_bez_id = [k for k in kol_dz if k != "id"]
                p_ins = ",".join("?" for _ in kol_bez_id)
                n_ins = ",".join(kol_bez_id)
                for d in do_zrobienia_dane:
                    conn.execute(f"INSERT INTO do_zrobienia ({n_ins}) VALUES ({p_ins})", tuple(d[k] for k in kol_bez_id))
        przelicz_wszystkie_zadania(auto_id)

    return wizyta_id, duplikaty, {"cofnij": cofnij, "finalizuj": lambda: None}

def pobierz_tagi(auto_id):
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT id, nazwa, kolor FROM tagi WHERE auto_id=?", (auto_id,))
        return c.fetchall()

def dodaj_tag(auto_id, nazwa, kolor):
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT id FROM tagi WHERE auto_id=? AND LOWER(nazwa)=LOWER(?)", (auto_id, nazwa))
        w = c.fetchone()
        if w: return w[0]
        c.execute("INSERT INTO tagi (auto_id, nazwa, kolor) VALUES (?, ?, ?)", (auto_id, nazwa, kolor))
        return c.lastrowid

def usun_tag_ze_slownika(auto_id, tag_id, nazwa):
    """Usuwa tag z bazy i wymazuje jego nazwę z rekordów tekstowych we wszystkich tabelach."""
    with polacz_baze() as conn:
        conn.execute("DELETE FROM tagi WHERE id=?", (tag_id,))
        
        for tabela in ["tankowania", "wizyty", "inne_koszty"]:
            c = conn.cursor()
            c.execute(f"SELECT id, tagi FROM {tabela} WHERE auto_id=? AND tagi LIKE ?", (auto_id, f'%{nazwa}%'))
            for r_id, tagi_str in c.fetchall():
                if not tagi_str: continue
                tagi_lista = [t.strip() for t in tagi_str.split(",") if t.strip()]
                if nazwa in tagi_lista:
                    tagi_lista.remove(nazwa)
                    nowe_tagi = ",".join(tagi_lista)
                    conn.execute(f"UPDATE {tabela} SET tagi=? WHERE id=?", (nowe_tagi, r_id))

def edytuj_tag_w_slowniku(auto_id, tag_id, stara_nazwa, nowa_nazwa, nowy_kolor):
    """Aktualizuje nazwę/kolor taga i kaskadowo podmienia ją w tekstowych wpisach rekordu."""
    with polacz_baze() as conn:
        conn.execute("UPDATE tagi SET nazwa=?, kolor=? WHERE id=?", (nowa_nazwa, nowy_kolor, tag_id))
        
        if stara_nazwa != nowa_nazwa:
            for tabela in ["tankowania", "wizyty", "inne_koszty"]:
                c = conn.cursor()
                c.execute(f"SELECT id, tagi FROM {tabela} WHERE auto_id=? AND tagi LIKE ?", (auto_id, f'%{stara_nazwa}%'))
                for r_id, tagi_str in c.fetchall():
                    if not tagi_str: continue
                    tagi_lista = [t.strip() for t in tagi_str.split(",") if t.strip()]
                    if stara_nazwa in tagi_lista:
                        idx = tagi_lista.index(stara_nazwa)
                        tagi_lista[idx] = nowa_nazwa
                        nowe_tagi = ",".join(tagi_lista)
                        conn.execute(f"UPDATE {tabela} SET tagi=? WHERE id=?", (nowe_tagi, r_id))

def pobierz_uzyte_czesci_wizyty(wizyta_id):
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT magazyn_id, ilosc_uzyta FROM wizyta_czesci_magazynu WHERE wizyta_id=?", (wizyta_id,))
        return c.fetchall()

def przywroc_czesci_wizyty(wizyta_id, conn=None):
    def _wykonaj(c):
        cur = c.cursor()
        cur.execute("SELECT magazyn_id, ilosc_uzyta FROM wizyta_czesci_magazynu WHERE wizyta_id=?", (wizyta_id,))
        for magazyn_id, ilosc in cur.fetchall():
            cur.execute("UPDATE magazyn_czesci SET ilosc = ilosc + ? WHERE id=?", (ilosc, magazyn_id))
        cur.execute("DELETE FROM wizyta_czesci_magazynu WHERE wizyta_id=?", (wizyta_id,))

    if conn is not None:
        _wykonaj(conn)
    else:
        with polacz_baze() as conn_local:
            _wykonaj(conn_local)

def rozlicz_czesci_z_magazynu(wizyta_id, uzyte, conn=None):
    if not uzyte:
        return
    def _wykonaj(c):
        cur = c.cursor()
        for magazyn_id, ilosc in uzyte:
            if not ilosc or ilosc <= 0:
                continue
            cur.execute(
                "INSERT INTO wizyta_czesci_magazynu (wizyta_id, magazyn_id, ilosc_uzyta) VALUES (?,?,?)",
                (wizyta_id, magazyn_id, ilosc)
            )
            cur.execute("UPDATE magazyn_czesci SET ilosc = MAX(0, ilosc - ?) WHERE id=?", (ilosc, magazyn_id))

    if conn is not None:
        _wykonaj(conn)
    else:
        with polacz_baze() as conn_local:
            _wykonaj(conn_local)

def usun_czesc_magazynu_z_cofnieciem(czesc_id):
    """Usuwa pozycję magazynową wraz z powiązanymi wpisami zużycia w wizytach
    (wizyta_czesci_magazynu), które SQLite skasowałoby cicho przez CASCADE.
    Zachowuje oryginalne ID pozycji."""
    if not czesc_id:
        return None

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("PRAGMA table_info(magazyn_czesci)")
        kol_m = [r["name"] for r in c.fetchall()]
        c.execute("SELECT * FROM magazyn_czesci WHERE id=?", (czesc_id,))
        w = c.fetchone()
        if not w:
            return None
        dane_czesc = {k: w[k] for k in kol_m}

        c.execute("PRAGMA table_info(wizyta_czesci_magazynu)")
        kol_w = [r["name"] for r in c.fetchall()]
        c.execute("SELECT * FROM wizyta_czesci_magazynu WHERE magazyn_id=?", (czesc_id,))
        uzycia_dane = [{k: r[k] for k in kol_w} for r in c.fetchall()]

    sciezka_tymczasowa = None
    oryginalna = dane_czesc.get("zalacznik")
    if oryginalna and os.path.exists(oryginalna):
        folder_tmp = _upewnij_folder_odroczonych()
        sciezka_tymczasowa = os.path.join(folder_tmp, f"magazyn_{uuid.uuid4().hex}_{os.path.basename(oryginalna)}")
        try:
            shutil.move(oryginalna, sciezka_tymczasowa)
        except Exception:
            sciezka_tymczasowa = None

    with polacz_baze() as conn:
        conn.execute("DELETE FROM magazyn_czesci WHERE id=?", (czesc_id,))

    stan = {"cofniete": False, "trwale_usuniete": False}

    def cofnij():
        if stan["cofniete"] or stan["trwale_usuniete"]:
            return
        stan["cofniete"] = True
        
        if sciezka_tymczasowa and os.path.exists(sciezka_tymczasowa):
            try:
                shutil.move(sciezka_tymczasowa, oryginalna)
            except Exception:
                pass
                
        with polacz_baze() as conn:
            n_m, p_m = ",".join(kol_m), ",".join("?" for _ in kol_m)
            conn.execute(f"INSERT INTO magazyn_czesci ({n_m}) VALUES ({p_m})", tuple(dane_czesc[k] for k in kol_m))
            if uzycia_dane:
                n_w, p_w = ",".join(kol_w), ",".join("?" for _ in kol_w)
                for d in uzycia_dane:
                    conn.execute(f"INSERT INTO wizyta_czesci_magazynu ({n_w}) VALUES ({p_w})", tuple(d[k] for k in kol_w))

    def finalizuj_usuniecie():
        if stan["cofniete"]:
            return
        stan["trwale_usuniete"] = True
        if sciezka_tymczasowa:
            usun_plik_zalacznika(sciezka_tymczasowa)

    return {"cofnij": cofnij, "finalizuj": finalizuj_usuniecie}


def usun_wiele_czesci_magazynu_z_cofnieciem(ids_list):
    wyniki = [w for w in (usun_czesc_magazynu_z_cofnieciem(cid) for cid in ids_list) if w]
    if not wyniki:
        return None

    stan = {"cofniete": False, "trwale_usuniete": False}

    def cofnij():
        if stan["cofniete"] or stan["trwale_usuniete"]:
            return
        stan["cofniete"] = True
        for w in wyniki:
            w["cofnij"]()

    def finalizuj_usuniecie():
        if stan["cofniete"]:
            return
        stan["trwale_usuniete"] = True
        for w in wyniki:
            w["finalizuj"]()

    return {"cofnij": cofnij, "finalizuj": finalizuj_usuniecie}

def _upewnij_folder_zalacznikow():
    os.makedirs(FOLDER_ZALACZNIKI, exist_ok=True)
    return FOLDER_ZALACZNIKI

def zapisz_zalacznik(sciezka_zrodlowa):
    if not sciezka_zrodlowa or not os.path.exists(sciezka_zrodlowa):
        return None
    folder = _upewnij_folder_zalacznikow()
    rozszerzenie = os.path.splitext(sciezka_zrodlowa)[1].lower()

    # Jeśli to PDF, kopiujemy 1:1, bez zmiany rozszerzenia
    if rozszerzenie == ".pdf":
        nazwa = f"{uuid.uuid4().hex}.pdf"
        docelowa = os.path.join(folder, nazwa)
        shutil.copyfile(sciezka_zrodlowa, docelowa)
        return docelowa

    # Domyślnie traktujemy jako obraz – wymuszamy .jpg dla mniejszego rozmiaru
    nazwa = f"{uuid.uuid4().hex}.jpg"
    docelowa = os.path.join(folder, nazwa)
    
    if Image is not None:
        try:
            with Image.open(sciezka_zrodlowa) as img:
                # Korekta orientacji na podstawie tagu EXIF — zdjęcia z telefonu
                # (zwłaszcza robione z aparatem trzymanym pionowo) mają "surowe"
                # piksele obrócone, a poprawną orientację niesie wyłącznie tag
                # EXIF Orientation. PIL go NIE stosuje automatycznie przy zapisie,
                # więc bez tej korekty zapisany JPEG zostaje trwale "położony".
                img = ImageOps.exif_transpose(img)

                # Usunięcie kanału alfa (przezroczystości), aby bezpiecznie zapisać do JPEG
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                
                # Zmniejszenie rozdzielczości, jeśli zdjęcie jest za szerokie
                max_szerokosc = 1600
                if img.width > max_szerokosc:
                    proporcja = max_szerokosc / float(img.width)
                    nowa_wysokosc = int(float(img.height) * float(proporcja))
                    img = img.resize((max_szerokosc, nowa_wysokosc), Image.Resampling.LANCZOS)
                
                img.save(docelowa, "JPEG", quality=85)
            return docelowa
        except Exception:
            pass # W razie problemów z PIL przejdzie do fallbacka poniżej

    # Fallback, jeśli obraz nie dał się skompresować lub brak biblioteki
    shutil.copyfile(sciezka_zrodlowa, docelowa)
    return docelowa

def usun_plik_zalacznika(sciezka_wzgledna):
    if not sciezka_wzgledna:
        return
    try:
        if os.path.exists(sciezka_wzgledna):
            os.remove(sciezka_wzgledna)
    except Exception:
        pass

def finalizuj_zalacznik(stara_sciezka, wynik_komponentu):
    if wynik_komponentu is None:
        return stara_sciezka
    if wynik_komponentu == "":
        usun_plik_zalacznika(stara_sciezka)
        return None
    usun_plik_zalacznika(stara_sciezka)
    return zapisz_zalacznik(wynik_komponentu)

# Dwuetapowy, bezpieczny zapis załącznika: "przygotuj" (zapisz nowy plik, NIE ruszaj
# starego) + "zatwierdź" (dopiero po udanym zapisie do bazy kasuje stary plik).
# Błąd zapisu do bazy nie kasuje już poprawnego, starego załącznika.
def przygotuj_nowy_zalacznik(wynik_komponentu):
    if wynik_komponentu is None:
        return None
    if wynik_komponentu == "":
        return ""
    return zapisz_zalacznik(wynik_komponentu)

def zatwierdz_zalacznik(stara_sciezka, przygotowany):
    if przygotowany is None:
        return stara_sciezka
    usun_plik_zalacznika(stara_sciezka)
    return przygotowany or None

def anuluj_nowy_zalacznik(przygotowany):
    if przygotowany:
        usun_plik_zalacznika(przygotowany)

def zalacznik_rekordu(tabela, rekord_id):
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(f"SELECT zalacznik FROM {tabela} WHERE id=?", (rekord_id,))
        w = c.fetchone()
        return w[0] if w else None

def usun_wizyty_z_cofnieciem(ids_list):
    """Grupowe (lub pojedyncze) usuwanie wizyt zbiorczych z pełnym cofaniem, w tym magazynu."""
    if not ids_list:
        return None

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        placeholders = ",".join("?" for _ in ids_list)

        # 1. Pobieramy wizyty
        c.execute(f"PRAGMA table_info(wizyty)")
        kolumny_wizyty = [r["name"] for r in c.fetchall()]
        c.execute(f"SELECT * FROM wizyty WHERE id IN ({placeholders})", tuple(ids_list))
        wizyty_dane = [{k: w[k] for k in kolumny_wizyty} for w in c.fetchall()]

        # 2. Pobieramy powiązaną historię
        c.execute(f"PRAGMA table_info(historia)")
        kolumny_historia = [r["name"] for r in c.fetchall()]
        c.execute(f"SELECT * FROM historia WHERE wizyta_id IN ({placeholders})", tuple(ids_list))
        historia_dane = [{k: w[k] for k in kolumny_historia} for w in c.fetchall()]

        # 3. Pobieramy użyte części
        c.execute(f"PRAGMA table_info(wizyta_czesci_magazynu)")
        kolumny_czesci = [r["name"] for r in c.fetchall()]
        c.execute(f"SELECT * FROM wizyta_czesci_magazynu WHERE wizyta_id IN ({placeholders})", tuple(ids_list))
        czesci_dane = [{k: w[k] for k in kolumny_czesci} for w in c.fetchall()]

    if not wizyty_dane:
        return None

    # Bezpieczne chowanie załączników z wizyt
    sciezki_tymczasowe = []
    folder_tmp = _upewnij_folder_odroczonych()
    for dane in wizyty_dane:
        oryginalna = dane.get("zalacznik")
        if oryginalna and os.path.exists(oryginalna):
            sciezka_tmp = os.path.join(folder_tmp, f"wizyta_{uuid.uuid4().hex}_{os.path.basename(oryginalna)}")
            try:
                shutil.move(oryginalna, sciezka_tmp)
                sciezki_tymczasowe.append((sciezka_tmp, oryginalna))
            except Exception:
                pass

    # Faktyczne operacje kasowania (oddajemy też części do magazynu!)
    with polacz_baze() as conn:
        for wid in ids_list:
            przywroc_czesci_wizyty(wid, conn=conn)
        conn.execute(f"DELETE FROM historia WHERE wizyta_id IN ({placeholders})", tuple(ids_list))
        conn.execute(f"DELETE FROM wizyty WHERE id IN ({placeholders})", tuple(ids_list))

    stan = {"cofniete": False, "trwale_usuniete": False}

    def cofnij():
        if stan["cofniete"] or stan["trwale_usuniete"]: return
        stan["cofniete"] = True

        for tmp, oryg in sciezki_tymczasowe:
            if os.path.exists(tmp):
                try: shutil.move(tmp, oryg)
                except Exception: pass

        with polacz_baze() as conn:
            if wizyty_dane:
                p_w = ",".join("?" for _ in kolumny_wizyty)
                n_w = ",".join(kolumny_wizyty)
                for d in wizyty_dane:
                    conn.execute(f"INSERT INTO wizyty ({n_w}) VALUES ({p_w})", tuple(d[k] for k in kolumny_wizyty))
            
            if historia_dane:
                p_h = ",".join("?" for _ in kolumny_historia)
                n_h = ",".join(kolumny_historia)
                for d in historia_dane:
                    conn.execute(f"INSERT INTO historia ({n_h}) VALUES ({p_h})", tuple(d[k] for k in kolumny_historia))

            if czesci_dane:
                p_c = ",".join("?" for _ in kolumny_czesci)
                n_c = ",".join(kolumny_czesci)
                for d in czesci_dane:
                    conn.execute(f"INSERT INTO wizyta_czesci_magazynu ({n_c}) VALUES ({p_c})", tuple(d[k] for k in kolumny_czesci))
                    # Ponownie potrącamy części ze stanu magazynu
                    conn.execute("UPDATE magazyn_czesci SET ilosc = MAX(0, ilosc - ?) WHERE id=?", (d["ilosc_uzyta"], d["magazyn_id"]))

    def finalizuj_usuniecie():
        if stan["cofniete"]: return
        stan["trwale_usuniete"] = True
        for tmp, _ in sciezki_tymczasowe:
            usun_plik_zalacznika(tmp)

    return {"cofnij": cofnij, "finalizuj": finalizuj_usuniecie}

def usun_auto_z_cofnieciem(auto_id):
    """Kompleksowe usunięcie pojazdu wraz z całą jego kaskadową historią i opcją cofnięcia."""
    if not auto_id: return None

    # Tabela kolejności ma znaczenie przy odtwarzaniu ze względu na klucze obce!
    tabele_poziom_1 = [
        "zadania", "wizyty", "magazyn_czesci", 
        "tagi", "tankowania", "inne_koszty", 
        "zestawy_opon", "zdjecia_karoserii"
    ]
    tabele_poziom_2 = ["do_zrobienia"] # Zależy od zadania
    tabele_poziom_3 = ["historia", "wizyta_czesci_magazynu"] # Zależą od zadań i wizyt

    dane_auta = {}
    wszystkie_dane = {}
    sciezki_tymczasowe = []
    folder_tmp = _upewnij_folder_odroczonych()

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # 1. Zrzut tabeli głównej (samochody)
        c.execute("PRAGMA table_info(samochody)")
        kol_a = [r["name"] for r in c.fetchall()]
        c.execute("SELECT * FROM samochody WHERE id=?", (auto_id,))
        w_auto = c.fetchone()
        if not w_auto: return None
        dane_auta = {k: w_auto[k] for k in kol_a}

        # Zabezpieczenie zdjęcia profilowego auta
        if dane_auta.get("zdjecie_glowne") and os.path.exists(dane_auta["zdjecie_glowne"]):
            tmp = os.path.join(folder_tmp, f"auto_{uuid.uuid4().hex}_{os.path.basename(dane_auta['zdjecie_glowne'])}")
            try:
                shutil.move(dane_auta["zdjecie_glowne"], tmp)
                sciezki_tymczasowe.append((tmp, dane_auta["zdjecie_glowne"]))
            except Exception: pass

        # Funkcja pomocnicza do zrzutu wszystkich tabel potomnych
        def pobierz_tabelke(tab, pole_auto="auto_id", uzyj_join=None):
            c.execute(f"PRAGMA table_info({tab})")
            kol = [r["name"] for r in c.fetchall()]
            if uzyj_join:
                c.execute(uzyj_join, (auto_id,))
            else:
                c.execute(f"SELECT * FROM {tab} WHERE {pole_auto}=?", (auto_id,))
            wiersze = c.fetchall()
            wszystkie_dane[tab] = {"kolumny": kol, "wiersze": [{k: w[k] for k in kol} for w in wiersze]}

            # Chowanie powiązanych załączników
            if tab in TABELE_Z_ZALACZNIKIEM:
                for d in wszystkie_dane[tab]["wiersze"]:
                    zal = d.get("zalacznik")
                    if zal and os.path.exists(zal):
                        tmp = os.path.join(folder_tmp, f"z_{uuid.uuid4().hex}_{os.path.basename(zal)}")
                        try:
                            shutil.move(zal, tmp)
                            sciezki_tymczasowe.append((tmp, zal))
                        except Exception: pass

        # 2. Zrzut pozostałych tabel z odpowiednimi połączeniami
        for t in tabele_poziom_1 + tabele_poziom_2:
            pobierz_tabelke(t)
            
        pobierz_tabelke("historia", uzyj_join="SELECT h.* FROM historia h JOIN zadania z ON h.zadanie_id = z.id WHERE z.auto_id=?")
        pobierz_tabelke("wizyta_czesci_magazynu", uzyj_join="SELECT wcm.* FROM wizyta_czesci_magazynu wcm JOIN wizyty w ON wcm.wizyta_id = w.id WHERE w.auto_id=?")

    # Kaskadowe usunięcie pojazdu wyczyści bazę!
    with polacz_baze() as conn:
        conn.execute("DELETE FROM samochody WHERE id=?", (auto_id,))

    stan = {"cofniete": False, "trwale_usuniete": False}

    def cofnij():
        if stan["cofniete"] or stan["trwale_usuniete"]: return
        stan["cofniete"] = True

        # Przywracanie fizycznych zdjęć
        for tmp, oryg in sciezki_tymczasowe:
            if os.path.exists(tmp):
                try: shutil.move(tmp, oryg)
                except Exception: pass

        with polacz_baze() as conn:
            def wstaw_dane(tabela):
                if tabela in wszystkie_dane and wszystkie_dane[tabela]["wiersze"]:
                    kol = wszystkie_dane[tabela]["kolumny"]
                    p_t = ",".join("?" for _ in kol)
                    n_t = ",".join(kol)
                    # Przywracamy dbając o to, by rekordy odzyskały swoje oryginalne ID!
                    for d in wszystkie_dane[tabela]["wiersze"]:
                        conn.execute(f"INSERT INTO {tabela} ({n_t}) VALUES ({p_t})", tuple(d[k] for k in kol))

            # Przywracamy kaskadowo, od "rodziców" do najniższych powiązań
            kol_a = list(dane_auta.keys())
            p_a = ",".join("?" for _ in kol_a)
            n_a = ",".join(kol_a)
            conn.execute(f"INSERT INTO samochody ({n_a}) VALUES ({p_a})", tuple(dane_auta[k] for k in kol_a))

            for t in tabele_poziom_1: wstaw_dane(t)
            for t in tabele_poziom_2: wstaw_dane(t)
            for t in tabele_poziom_3: wstaw_dane(t)

    def finalizuj_usuniecie():
        if stan["cofniete"]: return
        stan["trwale_usuniete"] = True
        for tmp, _ in sciezki_tymczasowe:
            usun_plik_zalacznika(tmp)

    return {"cofnij": cofnij, "finalizuj": finalizuj_usuniecie}

def usun_zadanie_z_cofnieciem(zadanie_id):
    """Usuwa podzespół (zadanie) wraz z całą jego kaskadową historią,
    załącznikami i powiązaniami z opcją pełnego cofnięcia."""
    if not zadanie_id:
        return None

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # 1. Pobieramy dane usuwanego zadania
        c.execute("PRAGMA table_info(zadania)")
        kol_z = [r["name"] for r in c.fetchall()]
        c.execute("SELECT * FROM zadania WHERE id=?", (zadanie_id,))
        w_zad = c.fetchone()
        if not w_zad:
            return None
        dane_zad = {k: w_zad[k] for k in kol_z}

        # 2. Pobieramy powiązaną historię (która zniknie przez CASCADE)
        c.execute("PRAGMA table_info(historia)")
        kol_h = [r["name"] for r in c.fetchall()]
        c.execute("SELECT * FROM historia WHERE zadanie_id=?", (zadanie_id,))
        historia_dane = [{k: w[k] for k in kol_h} for w in c.fetchall()]

        # 3. Zapamiętujemy wpisy 'do_zrobienia' (klucz obcy ustawi im zadanie_id na NULL)
        c.execute("SELECT id FROM do_zrobienia WHERE zadanie_id=?", (zadanie_id,))
        do_zrobienia_ids = [r["id"] for r in c.fetchall()]

    # 4. Zabezpieczamy fizyczne pliki załączników powiązane z historią tego zadania
    sciezki_tymczasowe = []
    folder_tmp = _upewnij_folder_odroczonych()
    for d in historia_dane:
        zal = d.get("zalacznik")
        if zal and os.path.exists(zal):
            tmp = os.path.join(folder_tmp, f"h_{uuid.uuid4().hex}_{os.path.basename(zal)}")
            try:
                shutil.move(zal, tmp)
                sciezki_tymczasowe.append((tmp, zal))
            except Exception:
                pass

    # 5. Usunięcie zadania (SQLite CASCADE automatycznie wyczyści powiązaną historię)
    with polacz_baze() as conn:
        conn.execute("DELETE FROM zadania WHERE id=?", (zadanie_id,))

    stan = {"cofniete": False, "trwale_usuniete": False}

    def cofnij():
        if stan["cofniete"] or stan["trwale_usuniete"]:
            return
        stan["cofniete"] = True

        # Przywrócenie plików na dysk
        for tmp, oryg in sciezki_tymczasowe:
            if os.path.exists(tmp):
                try:
                    shutil.move(tmp, oryg)
                except Exception:
                    pass

        # Przywrócenie rekordów w bazie danych z zachowaniem ich oryginalnych ID
        with polacz_baze() as conn:
            # 1. Przywrócenie zadania
            p_z = ",".join("?" for _ in kol_z)
            n_z = ",".join(kol_z)
            conn.execute(f"INSERT INTO zadania ({n_z}) VALUES ({p_z})", tuple(dane_zad[k] for k in kol_z))

            # 2. Przywrócenie wpisów historii
            if historia_dane:
                p_h = ",".join("?" for _ in kol_h)
                n_h = ",".join(kol_h)
                for d in historia_dane:
                    conn.execute(f"INSERT INTO historia ({n_h}) VALUES ({p_h})", tuple(d[k] for k in kol_h))

            # 3. Ponowne podpięcie ID zadania do pozycji 'do_zrobienia'
            if do_zrobienia_ids:
                placeholders = ",".join("?" for _ in do_zrobienia_ids)
                conn.execute(
                    f"UPDATE do_zrobienia SET zadanie_id=? WHERE id IN ({placeholders})",
                    (zadanie_id, *do_zrobienia_ids)
                )

    def finalizuj_usuniecie():
        if stan["cofniete"]:
            return
        stan["trwale_usuniete"] = True
        for tmp, _ in sciezki_tymczasowe:
            usun_plik_zalacznika(tmp)

    return {"cofnij": cofnij, "finalizuj": finalizuj_usuniecie, "dane": dane_zad}

def usun_wiele_zadan_z_cofnieciem(ids_list):
    """Bulk-owy wrapper na usun_zadanie_z_cofnieciem — każdy podzespół usuwa
    pełną, kaskadowo bezpieczną ścieżką (z historią i załącznikami), łącząc
    wyniki w jeden wspólny callback cofnij()/finalizuj()."""
    wyniki = [w for w in (usun_zadanie_z_cofnieciem(zid) for zid in ids_list) if w]
    if not wyniki:
        return None

    stan = {"cofniete": False, "trwale_usuniete": False}

    def cofnij():
        if stan["cofniete"] or stan["trwale_usuniete"]:
            return
        stan["cofniete"] = True
        for w in wyniki:
            w["cofnij"]()

    def finalizuj_usuniecie():
        if stan["cofniete"]:
            return
        stan["trwale_usuniete"] = True
        for w in wyniki:
            w["finalizuj"]()

    return {"cofnij": cofnij, "finalizuj": finalizuj_usuniecie}