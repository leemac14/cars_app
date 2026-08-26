import sqlite3
import os
import shutil
import uuid
import time
import csv
import io
import zipfile
from contextlib import contextmanager
from date import parsuj_date
from datetime import datetime, timedelta

try:
    from PIL import Image, ImageOps
except ImportError:
    Image = None
    ImageOps = None

try:
    from fpdf import FPDF
except ImportError:
    FPDF = None

STORAGE_PATH = os.environ.get("FLET_APP_STORAGE_DATA", "")
BAZA_DANYCH = os.path.join(STORAGE_PATH, 'flota_zadania.db')
FOLDER_ZALACZNIKI = os.path.join(STORAGE_PATH, "zalaczniki")
FOLDER_ODROCZONE = os.path.join(STORAGE_PATH, "zalaczniki_odroczone")

DOMYSLNE_ZADANIA = [
    "🛢️ Olej silnikowy i filtr", "💨 Filtr powietrza", "🌬️ Filtr kabinowy",
    "⚙️ Pasek / Łańcuch rozrządu", "🛞 Wymiana opon / Kół", "🛑 Klocki hamulcowe", "💿 Tarcze hamulcowe"
]

PAKIETY_SERWISOWE = {
    "Przegląd olejowy": ["🛢️ Olej silnikowy i filtr", "💨 Filtr powietrza", "🌬️ Filtr kabinowy"],
    "Sezonowa wymiana opon": ["🛞 Wymiana opon / Kół"],
    "Serwis hamulcowy (przód+tył)": ["🛑 Klocki hamulcowe", "💿 Tarcze hamulcowe"],
    "Duży przegląd (rozrząd)": ["⚙️ Pasek / Łańcuch rozrządu", "🛢️ Olej silnikowy i filtr", "💨 Filtr powietrza"],
}

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
        
        # ================= DODAJ TEN BLOK =================
        # TWARDE WYMUSZENIE UTWORZENIA TABEL WARSZTATÓW I WYDATKÓW
        cursor.execute("CREATE TABLE IF NOT EXISTS warsztaty (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, nazwa TEXT NOT NULL, telefon TEXT, adres TEXT, notatki TEXT, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_warsztaty_auto ON warsztaty(auto_id)")
        
        cursor.execute("CREATE TABLE IF NOT EXISTS wydatki_cykliczne (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, nazwa TEXT NOT NULL, kwota REAL NOT NULL DEFAULT 0.0, okres_dni INTEGER NOT NULL DEFAULT 30, nastepna_data TEXT NOT NULL, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_wydatki_cykliczne_auto ON wydatki_cykliczne(auto_id)")
        # ==================================================
        
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
            """,

            # Wersja 12: Indywidualny kolor motywu interfejsu per pojazd — zamiast
            # jednego, globalnego koloru dla całej aplikacji. NULL = "użyj
            # domyślnego koloru z Ustawień".
            """
            ALTER TABLE samochody ADD COLUMN kolor_motywu TEXT;
            """,

            # Wersja 13: Szybkie odczyty przebiegu — lekki dziennik ręcznych
            # wpisów stanu licznika (np. z deski rozdzielczej), niezależny od
            # tankowań/wizyt/historii. Pozwala odświeżyć aktualny przebieg
            # bez dodawania "sztucznego" wpisu w innej tabeli.
            """
            CREATE TABLE IF NOT EXISTS odczyty_przebiegu (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, data TEXT NOT NULL, przebieg INTEGER NOT NULL, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE);
            CREATE INDEX IF NOT EXISTS idx_odczyty_przebiegu_auto ON odczyty_przebiegu(auto_id);
            """,

            # Wersja 14: Baza warsztatów per pojazd — pozwala wybierać wykonawcę
            # z listy zamiast wpisywać go ręcznie, plus telefon/adres do
            # szybkiego "zadzwoń"/"nawiguj" z poziomu wizyty.
            """
            CREATE TABLE IF NOT EXISTS warsztaty (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, nazwa TEXT NOT NULL, telefon TEXT, adres TEXT, notatki TEXT, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE);
            CREATE INDEX IF NOT EXISTS idx_warsztaty_auto ON warsztaty(auto_id);
            """,

            # Wersja 15: Wydatki cykliczne (raty, abonamenty, ubezpieczenia
            # ratalne) — osobny harmonogram, z automatycznym przesuwaniem
            # terminu po oznaczeniu jako zapłacone.
            """
            CREATE TABLE IF NOT EXISTS wydatki_cykliczne (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, nazwa TEXT NOT NULL, kwota REAL NOT NULL DEFAULT 0.0, okres_dni INTEGER NOT NULL DEFAULT 30, nastepna_data TEXT NOT NULL, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE);
            CREATE INDEX IF NOT EXISTS idx_wydatki_cykliczne_auto ON wydatki_cykliczne(auto_id);
            """,

            # Wersja 16: Współdzielenie pojazdu (Supabase) — patrz sync.py. Pola
            # NULL = pojazd/tankowanie czysto lokalne, zero zmian w zachowaniu.
            """
            ALTER TABLE samochody ADD COLUMN wspolny_pojazd_id TEXT;
            ALTER TABLE samochody ADD COLUMN kod_zaproszenia TEXT;
            ALTER TABLE tankowania ADD COLUMN zdalne_id TEXT;
            """,
            # Wersja 17: Własne pakiety serwisowe — użytkownik może zapisać
            # dowolny zestaw zaznaczonych podzespołów jako nazwany "pakiet",
            # obok wbudowanych z PAKIETY_SERWISOWE. Zapisywane per pojazd.
            """
            CREATE TABLE IF NOT EXISTS pakiety_serwisowe_wlasne (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, nazwa TEXT NOT NULL, pozycje TEXT NOT NULL, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE);
            CREATE INDEX IF NOT EXISTS idx_pakiety_wlasne_auto ON pakiety_serwisowe_wlasne(auto_id);
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

def pobierz_kolor_auta(auto_id):
    """Zwraca kolor motywu przypisany do KONKRETNEGO pojazdu. Jeśli auto nie ma
    ustawionego własnego koloru (albo żadne auto nie jest aktualnie wybrane),
    zwraca globalny kolor domyślny z Ustawień."""
    if auto_id:
        with polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT kolor_motywu FROM samochody WHERE id=?", (auto_id,))
            w = c.fetchone()
            if w and w[0] in KOLORY_MOTYWU:
                return w[0]
    return pobierz_kolor_motywu()

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
        wpisy = []

        # Zbieramy wszystkie przebiegi, nadając nowym ręcznym odczytom wyższy priorytet (2)
        c.execute("SELECT przebieg, data, 1 FROM tankowania WHERE auto_id = ?", (auto_id,))
        wpisy.extend(c.fetchall())
        
        c.execute("SELECT przebieg, data, 1 FROM wizyty WHERE auto_id = ?", (auto_id,))
        wpisy.extend(c.fetchall())
        
        c.execute("SELECT h.przebieg, h.data, 1 FROM historia h JOIN zadania z ON h.zadanie_id = z.id WHERE z.auto_id = ? AND h.wizyta_id IS NULL", (auto_id,))
        wpisy.extend(c.fetchall())
        
        c.execute("SELECT przebieg, data, 2 FROM odczyty_przebiegu WHERE auto_id = ?", (auto_id,))
        wpisy.extend(c.fetchall())

    parsed = []
    for prz, d_str, priorytet in wpisy:
        try:
            prz_val = int(prz)
            if prz_val > 0:
                parsed.append((parsuj_date(d_str), priorytet, prz_val))
        except (TypeError, ValueError):
            pass

    if not parsed: return 0
    
    # Sortujemy chronologicznie po dacie, potem po priorytecie, a na końcu po wartości
    parsed.sort(key=lambda x: (x[0], x[1], x[2]))
    return parsed[-1][2]

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

        wyklucz_sql = " AND id != ?" if (tabela == "odczyty_przebiegu" and wyklucz_id) else ""
        params = [auto_id] + ([wyklucz_id] if wyklucz_sql else [])
        c.execute(f"SELECT przebieg, data FROM odczyty_przebiegu WHERE auto_id=?{wyklucz_sql}", params)
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
        c.execute("SELECT data, przebieg FROM odczyty_przebiegu WHERE auto_id=?", (auto_id,))
        wiersze += c.fetchall()

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

def pobierz_historie_przebiegu(auto_id):
    """Chronologiczna historia stanu licznika złożona ze wszystkich źródeł
    (tankowania, wizyty, historia bez wizyty, ręczne odczyty) — do wykresu
    przebiegu w paszporcie pojazdu. Dla każdej daty zostaje zapisany najwyższy
    zanotowany tego dnia przebieg; wynik jest posortowany chronologicznie.
    Zwraca listę krotek (data_str, przebieg_int)."""
    if not auto_id:
        return []

    with polacz_baze() as conn:
        c = conn.cursor()
        wpisy = []
        c.execute("SELECT data, przebieg FROM tankowania WHERE auto_id=?", (auto_id,))
        wpisy += c.fetchall()
        c.execute("SELECT data, przebieg FROM wizyty WHERE auto_id=?", (auto_id,))
        wpisy += c.fetchall()
        c.execute(
            "SELECT h.data, h.przebieg FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE z.auto_id=? AND h.wizyta_id IS NULL", (auto_id,)
        )
        wpisy += c.fetchall()
        c.execute("SELECT data, przebieg FROM odczyty_przebiegu WHERE auto_id=?", (auto_id,))
        wpisy += c.fetchall()

    wg_daty = {}
    for data_str, prz in wpisy:
        d = parsuj_date(data_str)
        if d == datetime.min.date():
            continue
        try:
            prz_i = int(prz or 0)
        except (TypeError, ValueError):
            continue
        if prz_i <= 0:
            continue
        if d not in wg_daty or prz_i > wg_daty[d][1]:
            wg_daty[d] = (data_str, prz_i)

    return [wg_daty[d] for d in sorted(wg_daty.keys())]

def dodaj_odczyt_przebiegu(auto_id, przebieg, data_str=None):
    """Zapisuje szybki, ręczny odczyt licznika (np. z deski rozdzielczej) w osobnym
    dzienniku — bez tworzenia sztucznego tankowania czy wpisu serwisowego tylko po
    to, by odświeżyć aktualny przebieg. Jeśli w danym dniu istnieje już odczyt,
    aktualizuje go zamiast duplikować."""
    if not auto_id or not przebieg or przebieg <= 0:
        return
    if not data_str:
        data_str = datetime.now().strftime("%d.%m.%Y")

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT id FROM odczyty_przebiegu WHERE auto_id=? AND data=?", (auto_id, data_str))
        w = c.fetchone()
        if w:
            conn.execute("UPDATE odczyty_przebiegu SET przebieg=? WHERE id=?", (przebieg, w[0]))
        else:
            conn.execute("INSERT INTO odczyty_przebiegu (auto_id, data, przebieg) VALUES (?,?,?)", (auto_id, data_str, przebieg))

def aktualizuj_odczyt_przebiegu(odczyt_id, przebieg, data_str):
    """Edycja konkretnego, istniejącego odczytu (z poziomu listy historii) —
    aktualizuje po ID, bez logiki upsert po dacie użytej w dodaj_odczyt_przebiegu."""
    with polacz_baze() as conn:
        conn.execute("UPDATE odczyty_przebiegu SET przebieg=?, data=? WHERE id=?", (przebieg, data_str, odczyt_id))

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
        # Wydatki cykliczne (raty, abonamenty, ubezpieczenia ratalne) — termin
        # liczy się jak dla dokumentów, ale akcją jest "Zapłacone", nie przejście
        # do formularza (stąd "trasa": None).
        c.execute(
            "SELECT id, nazwa, nastepna_data, okres_dni FROM wydatki_cykliczne WHERE auto_id=?",
            (auto_id,)
        )
        for wc in c.fetchall():
            d_wc = parsuj_date(wc["nastepna_data"])
            if d_wc == datetime.min.date():
                continue
            zost_dni = (d_wc - dzis).days
            # Próg dla wydatków cyklicznych jest dodatkowo ograniczony częścią
            # ich WŁASNEGO okresu — inaczej pozycja płatna np. co 30 dni przy
            # globalnym progu powiadomień 30 dni byłaby "pilna" przez CAŁY
            # cykl, a kliknięcie "Zapłacone" (przesuwające termin o okres_dni)
            # od razu wracałoby jako to samo powiadomienie.
            wlasny_prog = max(1, int(wc["okres_dni"] or 30) // 3)
            prog_efektywny = min(prog_dni, wlasny_prog)
            if zost_dni <= prog_efektywny:
                s = "przeterminowane" if zost_dni < 0 else "pilne"
                opis = f"Przekroczono o {abs(zost_dni)} dni" if zost_dni < 0 else f"Zostało {zost_dni} dni"
                wyniki.append({
                    "typ": "cykliczny", "tytul": wc["nazwa"], "opis": opis,
                    "status": s, "trasa": None, "wydatek_id": wc["id"],
                })

        kolejnosc = {"przeterminowane": 0, "pilne": 1}

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

def oblicz_kondycje_pojazdu(auto_id):
    """Wskaźnik kondycji pojazdu 0-100 (100 = wzorowo). Odejmuje punkty za
    przeterminowane/pilne podzespoły i płytki bieżnik aktualnie zamontowanych opon.
    Celowo NIE uwzględnia stanu magazynu, dokumentów (OC/przegląd)
    ani wydatków cyklicznych."""
    if not auto_id:
        return None

    wynik = 100
    for p in pobierz_powiadomienia(auto_id):
        # Ignorujemy wszystko co nie jest bezpośrednio powiązane z podzespołami auta
        if p["typ"] != "podzespol":
            continue
            
        if p["status"] == "przeterminowane":
            wynik -= 15
        elif p["status"] == "pilne":
            wynik -= 8

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT glebokosc_bieznika FROM zestawy_opon WHERE auto_id=? AND zamontowane=1",
            (auto_id,)
        )
        for (gl,) in c.fetchall():
            if gl is None or str(gl).strip() == "":
                continue
            try:
                g = float(gl)
            except (TypeError, ValueError):
                continue
            if g < 1.6:
                wynik -= 20
            elif g < 3.0:
                wynik -= 10

    return max(0, min(100, int(round(wynik))))

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

def globalne_wyszukiwanie(auto_id, zapytanie):
    """Przeszukuje jednocześnie tankowania, historię serwisową, wizyty zbiorcze,
    inne koszty oraz listę Do zrobienia BIEŻĄCEGO pojazdu. Używane przez widok
    /szukaj — jedną wspólną wyszukiwarkę dostępną z paska głównego, w odróżnieniu
    od lokalnych pól filtruj_* działających tylko na już wczytanej liście.
    Zwraca listę słowników {typ, tytul, opis, data, trasa}, posortowaną malejąco
    po dacie (nierozpoznane daty lądują na końcu)."""
    if not auto_id or not zapytanie or not zapytanie.strip():
        return []

    q = f"%{zapytanie.strip()}%"
    wyniki = []

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute(
            "SELECT id, data, przebieg, stacja, tagi FROM tankowania "
            "WHERE auto_id=? AND (stacja LIKE ? OR tagi LIKE ? OR data LIKE ?)",
            (auto_id, q, q, q)
        )
        for r in c.fetchall():
            opis = f"{int(r['przebieg'] or 0)} km" + (f" • {r['stacja']}" if r["stacja"] else "")
            wyniki.append({
                "typ": "Tankowanie", "tytul": r["stacja"] or "Tankowanie", "opis": opis,
                "data": r["data"], "trasa": f"/tankowanie/edytuj/{r['id']}",
            })

        c.execute(
            "SELECT h.id, h.data, h.przebieg, h.wykonawca, h.kategoria, z.nazwa "
            "FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE z.auto_id=? AND h.wizyta_id IS NULL AND "
            "(z.nazwa LIKE ? OR h.wykonawca LIKE ? OR h.kategoria LIKE ? OR h.data LIKE ?)",
            (auto_id, q, q, q, q)
        )
        for r in c.fetchall():
            opis = f"{int(r['przebieg'] or 0)} km" + (f" • {r['wykonawca']}" if r["wykonawca"] else "")
            wyniki.append({
                "typ": "Serwis", "tytul": str(r["nazwa"]), "opis": opis,
                "data": r["data"], "trasa": f"/wpis/edytuj/{r['id']}",
            })

        c.execute(
            "SELECT w.id, w.data, w.wykonawca, w.notatki, w.tagi, "
            "GROUP_CONCAT(z.nazwa, ', ') as czesci "
            "FROM wizyty w LEFT JOIN historia h ON h.wizyta_id=w.id LEFT JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE w.auto_id=? GROUP BY w.id "
            "HAVING (w.wykonawca LIKE ? OR w.notatki LIKE ? OR w.tagi LIKE ? OR w.data LIKE ? OR czesci LIKE ?)",
            (auto_id, q, q, q, q, q)
        )
        for r in c.fetchall():
            opis = str(r["czesci"] or "Brak podpiętych części") + (f" • {r['wykonawca']}" if r["wykonawca"] else "")
            wyniki.append({
                "typ": "Wizyta zbiorcza", "tytul": "Wizyta w warsztacie", "opis": opis,
                "data": r["data"], "trasa": f"/wizyty/edytuj/{r['id']}",
            })

        c.execute(
            "SELECT id, data, nazwa, kategoria, tagi FROM inne_koszty "
            "WHERE auto_id=? AND (nazwa LIKE ? OR kategoria LIKE ? OR tagi LIKE ? OR data LIKE ?)",
            (auto_id, q, q, q, q)
        )
        for r in c.fetchall():
            opis = str(r["kategoria"] or r["tagi"] or "Inny koszt")
            wyniki.append({
                "typ": "Inny koszt", "tytul": str(r["nazwa"] or "Koszt"), "opis": opis,
                "data": r["data"], "trasa": f"/inne/edytuj/{r['id']}",
            })

        c.execute(
            "SELECT id, tytul, opis, priorytet, termin FROM do_zrobienia "
            "WHERE auto_id=? AND (tytul LIKE ? OR opis LIKE ? OR priorytet LIKE ?)",
            (auto_id, q, q, q)
        )
        for r in c.fetchall():
            wyniki.append({
                "typ": "Do zrobienia", "tytul": str(r["tytul"]), "opis": str(r["opis"] or r["priorytet"] or ""),
                "data": r["termin"] or "", "trasa": f"/do-zrobienia/edytuj/{r['id']}",
            })

        # NOWE: Magazyn (części i płyny) — było obiecane w podpowiedzi wyszukiwarki
        # ("część"), ale dotąd nieprzeszukiwane.
        c.execute(
            "SELECT id, nazwa, kategoria, ilosc, jednostka FROM magazyn_czesci "
            "WHERE auto_id=? AND (nazwa LIKE ? OR kategoria LIKE ?)",
            (auto_id, q, q)
        )
        for r in c.fetchall():
            opis = f"{formatuj_liczba_eksport(r['ilosc'], 2)} {r['jednostka'] or 'szt'}" + (f" • {r['kategoria']}" if r["kategoria"] else "")
            wyniki.append({
                "typ": "Magazyn", "tytul": str(r["nazwa"]), "opis": opis,
                "data": "", "trasa": "/magazyn",
            })

        # NOWE: Zestawy opon
        c.execute(
            "SELECT id, sezon, rozmiar, marka_model, numer_dot FROM zestawy_opon "
            "WHERE auto_id=? AND (sezon LIKE ? OR rozmiar LIKE ? OR marka_model LIKE ? OR numer_dot LIKE ?)",
            (auto_id, q, q, q, q)
        )
        for r in c.fetchall():
            opis = str(r["rozmiar"] or "") + (f" • {r['marka_model']}" if r["marka_model"] else "")
            wyniki.append({
                "typ": "Opony", "tytul": f"Zestaw: {r['sezon']}", "opis": opis,
                "data": "", "trasa": "/magazyn",
            })

    wyniki.sort(key=lambda w: parsuj_date(w["data"]), reverse=True)
    return wyniki

def pobierz_dane_timeline(auto_id):
    """Zbiorcza, chronologiczna lista zdarzeń pojazdu ze wszystkich modułów
    (tankowania, historia serwisowa, wizyty zbiorcze, inne koszty, galeria
    karoserii, odczyty przebiegu) — używana przez widok /timeline ("dziennik
    życia auta"). Wpisy historii powiązane z wizytą zbiorczą są pomijane
    (reprezentuje je already sama wizyta), analogicznie do eksportu danych.
    Zwraca listę krotek: (id_timeline, typ, data, tytul, opis, kwota, zalacznik, trasa)."""
    if not auto_id:
        return []

    zdarzenia = []

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute(
            "SELECT id, data, przebieg, litry, kwota, stacja, do_pelna, zalacznik "
            "FROM tankowania WHERE auto_id=?", (auto_id,)
        )
        for r in c.fetchall():
            opis = f"{formatuj_liczba_eksport(r['litry'], 1)} L" + (f" • {r['stacja']}" if r['stacja'] else "")
            opis += f" • {int(r['przebieg'] or 0)} km"
            zdarzenia.append((
                f"tankowanie_{r['id']}", "Tankowanie", r["data"],
                "Tankowanie" + (" (do pełna)" if r["do_pelna"] else ""), opis,
                float(r["kwota"] or 0), r["zalacznik"], f"/tankowanie/edytuj/{r['id']}"
            ))

        c.execute(
            "SELECT h.id, h.data, h.przebieg, h.cena, h.wykonawca, z.nazwa, h.zalacznik "
            "FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE z.auto_id=? AND h.wizyta_id IS NULL", (auto_id,)
        )
        for r in c.fetchall():
            opis = f"{int(r['przebieg'] or 0)} km" + (f" • {r['wykonawca']}" if r["wykonawca"] else "")
            zdarzenia.append((
                f"historia_{r['id']}", "Serwis", r["data"],
                str(r["nazwa"]), opis,
                float(r["cena"] or 0), r["zalacznik"], f"/wpis/edytuj/{r['id']}"
            ))

        c.execute(
            "SELECT w.id, w.data, w.przebieg, w.wykonawca, w.koszt_calkowity, w.zalacznik, "
            "GROUP_CONCAT(z.nazwa, ', ') as czesci "
            "FROM wizyty w LEFT JOIN historia h ON h.wizyta_id=w.id LEFT JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE w.auto_id=? GROUP BY w.id", (auto_id,)
        )
        for r in c.fetchall():
            opis = str(r["czesci"] or "Brak podpiętych części") + (f" • {r['wykonawca']}" if r["wykonawca"] else "")
            zdarzenia.append((
                f"wizyta_{r['id']}", "Wizyta zbiorcza", r["data"],
                "Wizyta w warsztacie", opis,
                float(r["koszt_calkowity"] or 0), r["zalacznik"], f"/wizyty/edytuj/{r['id']}"
            ))

        c.execute("SELECT id, data, nazwa, kategoria, kwota, zalacznik FROM inne_koszty WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            zdarzenia.append((
                f"inne_{r['id']}", "Inny koszt", r["data"],
                str(r["nazwa"] or "Koszt"), str(r["kategoria"] or ""),
                float(r["kwota"] or 0), r["zalacznik"], f"/inne/edytuj/{r['id']}"
            ))

        c.execute("SELECT id, data, strefa, typ_porownania, opis, zalacznik FROM zdjecia_karoserii WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            opis = str(r["typ_porownania"]) if r["typ_porownania"] and r["typ_porownania"] != "Brak" else (r["opis"] or "")
            zdarzenia.append((
                f"zdjecie_{r['id']}", "Zdjęcie karoserii", r["data"],
                f"Zdjęcie: {r['strefa']}", opis,
                None, r["zalacznik"], f"/karoseria/edytuj/{r['id']}"
            ))

        c.execute("SELECT id, data, przebieg FROM odczyty_przebiegu WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            zdarzenia.append((
                f"odczyt_{r['id']}", "Odczyt przebiegu", r["data"],
                "Odczyt licznika", f"{int(r['przebieg'] or 0)} km",
                None, None, "/przebieg"
            ))

    return zdarzenia

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

# ==================== WARSZTATY ====================

def pobierz_warsztaty(auto_id):
    if not auto_id:
        return []
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT id, nazwa, telefon, adres, notatki FROM warsztaty WHERE auto_id=? ORDER BY nazwa", (auto_id,))
        return c.fetchall()

def dodaj_warsztat(auto_id, nazwa, telefon=None, adres=None, notatki=None):
    """Dodaje warsztat per pojazd. Jeśli warsztat o tej samej nazwie (bez
    uwzględniania wielkości liter) już istnieje, zwraca jego id zamiast
    tworzyć duplikat — analogicznie do dodaj_tag()."""
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT id FROM warsztaty WHERE auto_id=? AND LOWER(nazwa)=LOWER(?)", (auto_id, nazwa))
        w = c.fetchone()
        if w:
            return w[0]
        c.execute(
            "INSERT INTO warsztaty (auto_id, nazwa, telefon, adres, notatki) VALUES (?,?,?,?,?)",
            (auto_id, nazwa, telefon or None, adres or None, notatki or None)
        )
        return c.lastrowid

def edytuj_warsztat(warsztat_id, nazwa, telefon=None, adres=None, notatki=None):
    with polacz_baze() as conn:
        conn.execute(
            "UPDATE warsztaty SET nazwa=?, telefon=?, adres=?, notatki=? WHERE id=?",
            (nazwa, telefon or None, adres or None, notatki or None, warsztat_id)
        )

def usun_warsztat(warsztat_id):
    with polacz_baze() as conn:
        conn.execute("DELETE FROM warsztaty WHERE id=?", (warsztat_id,))

# ==================== WYDATKI CYKLICZNE ====================

def pobierz_wydatki_cykliczne(auto_id):
    if not auto_id:
        return []
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, nazwa, kwota, okres_dni, nastepna_data FROM wydatki_cykliczne WHERE auto_id=? ORDER BY nastepna_data",
            (auto_id,)
        )
        return c.fetchall()

def dodaj_wydatek_cykliczny(auto_id, nazwa, kwota, okres_dni, nastepna_data):
    with polacz_baze() as conn:
        conn.execute(
            "INSERT INTO wydatki_cykliczne (auto_id, nazwa, kwota, okres_dni, nastepna_data) VALUES (?,?,?,?,?)",
            (auto_id, nazwa, kwota, okres_dni, nastepna_data)
        )

def edytuj_wydatek_cykliczny(wydatek_id, nazwa, kwota, okres_dni, nastepna_data):
    with polacz_baze() as conn:
        conn.execute(
            "UPDATE wydatki_cykliczne SET nazwa=?, kwota=?, okres_dni=?, nastepna_data=? WHERE id=?",
            (nazwa, kwota, okres_dni, nastepna_data, wydatek_id)
        )

def usun_wydatek_cykliczny(wydatek_id):
    with polacz_baze() as conn:
        conn.execute("DELETE FROM wydatki_cykliczne WHERE id=?", (wydatek_id,))

def oznacz_zaplacony_wydatek_cykliczny(wydatek_id, auto_id):
    """Tworzy wpis w inne_koszty na podstawie wydatku cyklicznego i przesuwa jego
    następny termin płatności o okres_dni od DZISIAJ (nie od starej daty — dzięki
    temu spóźniona płatność nie generuje serii zaległych powiadomień pod rząd)."""
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT nazwa, kwota, okres_dni FROM wydatki_cykliczne WHERE id=?", (wydatek_id,))
        w = c.fetchone()
        if not w:
            return
        nazwa, kwota, okres_dni = w
        dzis = datetime.now()
        conn.execute(
            "INSERT INTO inne_koszty (auto_id, data, kategoria, nazwa, kwota) VALUES (?,?,?,?,?)",
            (auto_id, dzis.strftime("%d.%m.%Y"), "Cykliczne", nazwa, kwota)
        )
        nowa_data = (dzis + timedelta(days=int(okres_dni or 30))).strftime("%d.%m.%Y")
        conn.execute("UPDATE wydatki_cykliczne SET nastepna_data=? WHERE id=?", (nowa_data, wydatek_id))

# ==================== WŁASNE PAKIETY SERWISOWE ====================

def pobierz_pakiety_wlasne(auto_id):
    """Zwraca listę (id, nazwa, [lista_pozycji]) własnych pakietów użytkownika
    dla danego pojazdu, obok wbudowanych PAKIETY_SERWISOWE."""
    if not auto_id:
        return []
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT id, nazwa, pozycje FROM pakiety_serwisowe_wlasne WHERE auto_id=? ORDER BY nazwa", (auto_id,))
        return [
            (p_id, nazwa, [p.strip() for p in (pozycje or "").split(",") if p.strip()])
            for p_id, nazwa, pozycje in c.fetchall()
        ]

def dodaj_pakiet_wlasny(auto_id, nazwa, pozycje_lista):
    with polacz_baze() as conn:
        conn.execute(
            "INSERT INTO pakiety_serwisowe_wlasne (auto_id, nazwa, pozycje) VALUES (?,?,?)",
            (auto_id, nazwa, ",".join(pozycje_lista))
        )

def usun_pakiet_wlasny(pakiet_id):
    with polacz_baze() as conn:
        conn.execute("DELETE FROM pakiety_serwisowe_wlasne WHERE id=?", (pakiet_id,))

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
        "zestawy_opon", "zdjecia_karoserii", "odczyty_przebiegu",
        "warsztaty", "wydatki_cykliczne", "pakiety_serwisowe_wlasne"
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

# ==================== EKSPORT DANYCH (CSV / PDF) ====================

KATEGORIE_EKSPORTU = {
    "tankowania": "⛽ Tankowania",
    "historia": "🔧 Historia serwisowa",
    "wizyty": "🛠️ Wizyty zbiorcze (warsztat)",
    "inne_koszty": "🎫 Inne koszty",
    "magazyn_czesci": "📦 Magazyn części i płynów",
    "zestawy_opon": "🛞 Zestawy opon",
    "do_zrobienia": "✅ Lista Do zrobienia",
}

FOLDER_ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
CZCIONKA_PDF_REGULAR = os.path.join(FOLDER_ASSETS, "DejaVuSans.ttf")
CZCIONKA_PDF_BOLD = os.path.join(FOLDER_ASSETS, "DejaVuSans-Bold.ttf")

# Fallback dla PDF, gdy brak czcionki Unicode w assets/ — usuwa polskie znaki
# diakrytyczne zamiast wywalać wyjątek przy renderowaniu podstawowymi fontami PDF.
_MAPA_TRANSLITERACJI_PL = str.maketrans({
    "ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n", "ó": "o", "ś": "s", "ź": "z", "ż": "z",
    "Ą": "A", "Ć": "C", "Ę": "E", "Ł": "L", "Ń": "N", "Ó": "O", "Ś": "S", "Ź": "Z", "Ż": "Z",
})


def formatuj_liczba_eksport(wartosc, decimale=2):
    """Prosty format liczbowy do plików eksportu (przecinek jako separator dziesiętny,
    zgodnie z polskim Excelem, bez separatora tysięcy)."""
    if wartosc is None or wartosc == "":
        return ""
    try:
        wartosc = float(wartosc)
    except (TypeError, ValueError):
        return str(wartosc)
    if decimale > 0:
        return f"{wartosc:.{decimale}f}".replace(".", ",")
    return str(int(round(wartosc)))


def _data_w_zakresie(data_str, od_data, do_data):
    if not od_data and not do_data:
        return True
    d = parsuj_date(data_str)
    if d == datetime.min.date():
        return False
    if od_data and d < od_data:
        return False
    if do_data and d > do_data:
        return False
    return True


def pobierz_dane_eksportu(auto_id, kategorie, od_data=None, do_data=None):
    """
    Zbiera dane pojazdu do eksportu wg wybranych kategorii (klucze z KATEGORIE_EKSPORTU),
    opcjonalnie przycięte do zakresu [od_data, do_data] (obiekty date, oba mogą być None).
    Magazyn, zestawy opon i lista Do zrobienia to "stany aktualne" — eksportują się zawsze
    w całości, niezależnie od zakresu dat.
    Zwraca {klucz_kategorii: (naglowki: list[str], wiersze: list[list])}.
    """
    wynik = {}
    if not auto_id or not kategorie:
        return wynik

    with polacz_baze() as conn:
        c = conn.cursor()

        if "tankowania" in kategorie:
            c.execute(
                "SELECT data, przebieg, dystans, litry, kwota, do_pelna, stacja, tagi "
                "FROM tankowania WHERE auto_id=? ORDER BY data", (auto_id,)
            )
            wiersze = []
            for data, prz, dys, lit, kwo, pelna, stacja, tagi in c.fetchall():
                if _data_w_zakresie(data, od_data, do_data):
                    wiersze.append([
                        data, int(prz or 0), formatuj_liczba_eksport(dys), formatuj_liczba_eksport(lit),
                        formatuj_liczba_eksport(kwo), "Tak" if pelna else "Nie", stacja or "", tagi or ""
                    ])
            wynik["tankowania"] = (
                ["Data", "Przebieg (km)", "Dystans (km)", "Litry", "Kwota", "Do pełna", "Stacja", "Tagi"], wiersze
            )

        if "historia" in kategorie:
            c.execute(
                "SELECT h.data, z.nazwa, h.przebieg, h.cena, h.wykonawca, h.kategoria "
                "FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
                "WHERE z.auto_id=? AND h.wizyta_id IS NULL ORDER BY h.data", (auto_id,)
            )
            wiersze = []
            for data, nazwa, prz, cena, wyk, kat in c.fetchall():
                if _data_w_zakresie(data, od_data, do_data):
                    wiersze.append([data, nazwa, int(prz or 0), formatuj_liczba_eksport(cena), wyk or "", kat or ""])
            wynik["historia"] = (["Data", "Podzespół", "Przebieg (km)", "Koszt", "Wykonawca", "Kategoria"], wiersze)

        if "wizyty" in kategorie:
            c.execute(
                "SELECT w.data, w.przebieg, w.wykonawca, w.koszt_calkowity, w.notatki, w.tagi, "
                "GROUP_CONCAT(z.nazwa, ', ') FROM wizyty w "
                "LEFT JOIN historia h ON h.wizyta_id = w.id "
                "LEFT JOIN zadania z ON h.zadanie_id = z.id "
                "WHERE w.auto_id=? GROUP BY w.id ORDER BY w.data", (auto_id,)
            )
            wiersze = []
            for data, prz, wyk, kosz, notatki, tagi, czesci in c.fetchall():
                if _data_w_zakresie(data, od_data, do_data):
                    wiersze.append([
                        data, int(prz or 0), wyk or "", formatuj_liczba_eksport(kosz),
                        czesci or "", tagi or "", notatki or ""
                    ])
            wynik["wizyty"] = (
                ["Data", "Przebieg (km)", "Warsztat", "Koszt", "Podzespoły", "Tagi", "Notatki"], wiersze
            )

        if "inne_koszty" in kategorie:
            c.execute("SELECT data, nazwa, kategoria, kwota, tagi FROM inne_koszty WHERE auto_id=? ORDER BY data", (auto_id,))
            wiersze = []
            for data, nazwa, kat, kwota, tagi in c.fetchall():
                if _data_w_zakresie(data, od_data, do_data):
                    wiersze.append([data, nazwa or "", kat or "", formatuj_liczba_eksport(kwota), tagi or ""])
            wynik["inne_koszty"] = (["Data", "Opis", "Kategoria", "Kwota", "Tagi"], wiersze)

        if "magazyn_czesci" in kategorie:
            c.execute(
                "SELECT nazwa, kategoria, ilosc, jednostka, cena, data_zakupu "
                "FROM magazyn_czesci WHERE auto_id=? ORDER BY nazwa", (auto_id,)
            )
            wiersze = [
                [nazwa, kat or "", formatuj_liczba_eksport(ilosc, 2), jedn or "szt", formatuj_liczba_eksport(cena), dz or ""]
                for nazwa, kat, ilosc, jedn, cena, dz in c.fetchall()
            ]
            wynik["magazyn_czesci"] = (["Nazwa", "Kategoria", "Ilość", "Jednostka", "Cena", "Data zakupu"], wiersze)

        if "zestawy_opon" in kategorie:
            c.execute(
                "SELECT sezon, rozmiar, marka_model, glebokosc_bieznika, ilosc, zamontowane, os_montazu, cena "
                "FROM zestawy_opon WHERE auto_id=? ORDER BY sezon", (auto_id,)
            )
            wiersze = []
            for sezon, rozmiar, marka, gl, il, zam, os_m, cena in c.fetchall():
                stan = f"Na aucie ({os_m})" if zam else "W magazynie"
                wiersze.append([sezon or "", rozmiar or "", marka or "", formatuj_liczba_eksport(gl, 1), il or 4, stan, formatuj_liczba_eksport(cena)])
            wynik["zestawy_opon"] = (["Sezon", "Rozmiar", "Marka/model", "Bieżnik (mm)", "Ilość", "Stan", "Cena"], wiersze)

        if "do_zrobienia" in kategorie:
            c.execute(
                "SELECT tytul, priorytet, szacowany_koszt, termin, wykonane FROM do_zrobienia "
                "WHERE auto_id=? ORDER BY priorytet", (auto_id,)
            )
            wiersze = [
                [tyt, pr or "", formatuj_liczba_eksport(koszt), term or "", "Tak" if wyk else "Nie"]
                for tyt, pr, koszt, term, wyk in c.fetchall()
            ]
            wynik["do_zrobienia"] = (["Tytuł", "Priorytet", "Szac. koszt", "Termin", "Wykonane"], wiersze)

    return wynik


def oblicz_podsumowanie_okresu(auto_id, od_data=None, do_data=None):
    """Zbiorcze koszty i wskaźniki (jak w porównaniu pojazdów), przycięte do okresu —
    używane w nagłówku raportu PDF."""
    if not auto_id:
        return None

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT data, kwota, litry, przebieg, do_pelna FROM tankowania WHERE auto_id=?", (auto_id,))
        tankowania = [r for r in c.fetchall() if _data_w_zakresie(r[0], od_data, do_data)]

        c.execute(
            "SELECT h.data, h.cena FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE z.auto_id=? AND h.wizyta_id IS NULL", (auto_id,)
        )
        historia = [r for r in c.fetchall() if _data_w_zakresie(r[0], od_data, do_data)]

        c.execute("SELECT data, koszt_calkowity FROM wizyty WHERE auto_id=?", (auto_id,))
        wizyty = [r for r in c.fetchall() if _data_w_zakresie(r[0], od_data, do_data)]

        c.execute("SELECT data, kwota FROM inne_koszty WHERE auto_id=?", (auto_id,))
        inne = [r for r in c.fetchall() if _data_w_zakresie(r[0], od_data, do_data)]

    koszt_paliwo = sum(float(t[1] or 0) for t in tankowania)
    koszt_serwis = sum(float(h[1] or 0) for h in historia) + sum(float(w[1] or 0) for w in wizyty)
    koszt_inne = sum(float(i[1] or 0) for i in inne)
    razem = koszt_paliwo + koszt_serwis + koszt_inne

    tank_sort = sorted(tankowania, key=lambda t: int(t[3] or 0))
    dystans = 0
    if len(tank_sort) >= 2:
        dystans = max(0, int(tank_sort[-1][3] or 0) - int(tank_sort[0][3] or 0))
    koszt_km = (razem / dystans) if dystans > 0 else None

    spalanie = None
    peln_idx = [i for i, t in enumerate(tank_sort) if t[4]]
    if len(peln_idx) >= 2:
        p, o = peln_idx[0], peln_idx[-1]
        d_p = int(tank_sort[o][3] or 0) - int(tank_sort[p][3] or 0)
        l_p = sum(float(tank_sort[k][2] or 0) for k in range(p + 1, o + 1))
        if d_p > 0:
            spalanie = (l_p / d_p) * 100

    return {
        "koszt_paliwo": koszt_paliwo, "koszt_serwis": koszt_serwis, "koszt_inne": koszt_inne,
        "razem": razem, "dystans": dystans, "koszt_km": koszt_km, "spalanie": spalanie,
        "waluta": pobierz_walute(),
    }


def generuj_csv(naglowki, wiersze):
    """Bajty pliku CSV (BOM UTF-8, separator ';') — ';' i przecinek dziesiętny
    (patrz formatuj_liczba_eksport) pasują do polskiego Excela."""
    bufor = io.StringIO()
    writer = csv.writer(bufor, delimiter=';', lineterminator='\r\n')
    writer.writerow(naglowki)
    for w in wiersze:
        writer.writerow(w)
    return ('\ufeff' + bufor.getvalue()).encode('utf-8')


def generuj_eksport_csv(dane_eksportu):
    """
    dane_eksportu: {klucz: (naglowki, wiersze)} z pobierz_dane_eksportu().
    1 kategoria -> (bajty, 'csv'). Więcej -> każda kategoria jako osobny .csv
    w archiwum ZIP -> (bajty, 'zip').
    """
    klucze = list(dane_eksportu.keys())
    if len(klucze) == 1:
        naglowki, wiersze = dane_eksportu[klucze[0]]
        return generuj_csv(naglowki, wiersze), "csv"

    bufor = io.BytesIO()
    with zipfile.ZipFile(bufor, "w", zipfile.ZIP_DEFLATED) as zf:
        for klucz, (naglowki, wiersze) in dane_eksportu.items():
            zf.writestr(f"{klucz}.csv", generuj_csv(naglowki, wiersze))
    bufor.seek(0)
    return bufor.read(), "zip"


class _RaportPDF(FPDF if FPDF is not None else object):
    """Wrapper na FPDF z automatycznym doborem czcionki: jeśli w assets/ jest
    DejaVuSans(.ttf/-Bold.ttf), używa jej (pełne wsparcie polskich znaków).
    W przeciwnym razie używa wbudowanej Helvetiki i transliteruje diakrytyki (metoda t()).
    orientation: "L" (poziomo, domyślnie — pasuje do szerokich tabel w zwykłym
    raporcie) albo "P" (pionowo — używane przez tryb paszportu pojazdu)."""
    def __init__(self, orientation="L"):
        super().__init__(orientation=orientation, unit="mm", format="A4")
        self.set_auto_page_break(auto=True, margin=15)
        self.uzywa_utf8 = False
        self.czcionka = "Helvetica"
        if os.path.exists(CZCIONKA_PDF_REGULAR):
            try:
                self.add_font("DejaVu", "", CZCIONKA_PDF_REGULAR)
                self.add_font("DejaVu", "B", CZCIONKA_PDF_BOLD if os.path.exists(CZCIONKA_PDF_BOLD) else CZCIONKA_PDF_REGULAR)
                self.czcionka = "DejaVu"
                self.uzywa_utf8 = True
            except Exception:
                self.czcionka = "Helvetica"

    def t(self, tekst):
        import re
        tekst = "" if tekst is None else str(tekst)
        
        # 1. Zamieniamy typograficzne ozdobniki z aplikacji na zwykłe odpowiedniki ASCII
        zamienniki = {
            '•': '-', '▲': '^', '—': '-', '–': '-', '„': '"', '”': '"', '…': '...'
        }
        for znak, zamiennik in zamienniki.items():
            tekst = tekst.replace(znak, zamiennik)
            
        # 2. TWARDE CZYSZCZENIE: Zostawiamy TYLKO znaki podstawowe i rozszerzone łacińskie (w tym polskie ogonki).
        # To wycina absolutnie wszystkie emoji, chińskie znaczki czy niewidzialne błędy formatowania.
        tekst = re.sub(r'[^\u0000-\u017F]', '', tekst)
        
        # 3. Jeśli nie załadowało czcionki DejaVu, "spłaszczamy" polskie znaki do zwykłych
        if not self.uzywa_utf8:
            tekst = tekst.translate(_MAPA_TRANSLITERACJI_PL)
            tekst = tekst.encode('latin-1', 'replace').decode('latin-1')
            
        return tekst

def _narysuj_wykres_liniowy(pdf, punkty, x, y, w, h):
    """Prosty wykres liniowy narysowany prymitywami fpdf2 (bez matplotlib).
    punkty: lista (etykieta_x: str, wartosc: float), posortowana chronologicznie."""
    if len(punkty) < 2:
        pdf.set_font(pdf.czcionka, "", 10)
        pdf.set_text_color(140, 140, 140)
        pdf.set_xy(x, y + h / 2 - 4)
        pdf.cell(w, 8, pdf.t("Za mało danych do wykresu przebiegu."), align="C")
        pdf.set_text_color(0, 0, 0)
        return

    wartosci = [p[1] for p in punkty]
    min_v, max_v = min(wartosci), max(wartosci)
    if max_v == min_v:
        max_v = min_v + 1

    pdf.set_draw_color(210, 210, 210)
    pdf.set_line_width(0.2)
    pdf.rect(x, y, w, h)
    for i in range(1, 4):
        yy = y + h * i / 4
        pdf.line(x, yy, x + w, yy)

    pdf.set_font(pdf.czcionka, "", 7)
    pdf.set_text_color(120, 120, 120)
    for wart, frakcja in ((max_v, 0.0), ((max_v + min_v) / 2, 0.5), (min_v, 1.0)):
        pdf.set_xy(x - 22, y + h * frakcja - 2.5)
        pdf.cell(20, 5, pdf.t(f"{int(wart):,}".replace(",", " ")), align="R")

    n = len(punkty)

    def punkt_na_xy(i, wartosc):
        px = x + (w * i / (n - 1))
        py = y + h - ((wartosc - min_v) / (max_v - min_v)) * h
        return px, py

    pdf.set_draw_color(30, 100, 220)
    pdf.set_line_width(0.6)
    for i in range(n - 1):
        x1, y1 = punkt_na_xy(i, wartosci[i])
        x2, y2 = punkt_na_xy(i + 1, wartosci[i + 1])
        pdf.line(x1, y1, x2, y2)

    pdf.set_fill_color(30, 100, 220)
    for i in range(n):
        px, py = punkt_na_xy(i, wartosci[i])
        pdf.ellipse(px - 0.8, py - 0.8, 1.6, 1.6, style="F")

    pdf.set_font(pdf.czcionka, "", 7)
    for i in sorted(set([0, n // 2, n - 1])):
        px, _ = punkt_na_xy(i, wartosci[i])
        pdf.set_xy(px - 15, y + h + 2)
        pdf.cell(30, 5, pdf.t(str(punkty[i][0])[:5]), align="C")

    pdf.set_text_color(0, 0, 0)


def _rysuj_strone_tytulowa_paszportu(pdf, auto_nazwa, zdjecie_glowne, specyfikacja, terminy):
    """Strona tytułowa 'Cyfrowego paszportu pojazdu': zdjęcie, nazwa, specyfikacja
    w dwóch kolumnach oraz ważne terminy kolorowane jak w reszcie aplikacji.
    Używane wyłącznie przez generuj_pdf_raportu(tryb_paszportu=True)."""
    if zdjecie_glowne and os.path.exists(zdjecie_glowne):
        try:
            szer_strony = pdf.w - pdf.l_margin - pdf.r_margin
            szer_zdj = min(120, szer_strony)
            pdf.image(zdjecie_glowne, x=pdf.l_margin + (szer_strony - szer_zdj) / 2, y=pdf.get_y(), w=szer_zdj)
            pdf.set_y(pdf.get_y() + szer_zdj * 0.62 + 6)
        except Exception:
            pass

    pdf.set_font(pdf.czcionka, "B", 22)
    pdf.cell(0, 14, pdf.t(str(auto_nazwa or "Pojazd")), ln=1, align="C")

    pdf.set_font(pdf.czcionka, "", 10)
    pdf.set_text_color(110, 110, 110)
    pdf.cell(0, 7, pdf.t(f"Cyfrowy paszport pojazdu • wygenerowano {datetime.now().strftime('%d.%m.%Y %H:%M')}"), ln=1, align="C")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(6)

    if specyfikacja:
        pdf.set_font(pdf.czcionka, "B", 13)
        pdf.cell(0, 9, pdf.t("Specyfikacja pojazdu"), ln=1)
        pdf.set_draw_color(200, 200, 200)
        pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 180, pdf.get_y())
        pdf.ln(3)

        szer_kolumny = (pdf.w - pdf.l_margin - pdf.r_margin) / 2
        for i in range(0, len(specyfikacja), 2):
            para = specyfikacja[i:i + 2]
            y_wiersza = pdf.get_y()
            for j, (etyk, wart) in enumerate(para):
                pdf.set_xy(pdf.l_margin + j * szer_kolumny, y_wiersza)
                pdf.set_font(pdf.czcionka, "B", 10)
                pdf.cell(38, 7, pdf.t(f"{etyk}:"))
                pdf.set_font(pdf.czcionka, "", 10)
                pdf.cell(szer_kolumny - 38, 7, pdf.t(str(wart)))
            pdf.set_y(y_wiersza + 7)
        pdf.ln(4)

    if terminy:
        pdf.set_font(pdf.czcionka, "B", 13)
        pdf.cell(0, 9, pdf.t("Ważne terminy"), ln=1)
        pdf.set_draw_color(200, 200, 200)
        pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 180, pdf.get_y())
        pdf.ln(3)

        for etykieta, data_str in terminy:
            if not data_str:
                continue
            d_obj = parsuj_date(data_str)
            if d_obj == datetime.min.date():
                kolor, tekst = (120, 120, 120), str(data_str)
            else:
                roz = (d_obj - datetime.now().date()).days
                if roz < 0:
                    kolor, tekst = (200, 40, 40), f"{data_str}  (po terminie)"
                elif roz <= 30:
                    kolor, tekst = (210, 130, 20), f"{data_str}  (zbliża się)"
                else:
                    kolor, tekst = (40, 150, 70), str(data_str)
            pdf.set_font(pdf.czcionka, "B", 10)
            pdf.set_text_color(0, 0, 0)
            pdf.cell(45, 7, pdf.t(f"{etykieta}:"))
            pdf.set_font(pdf.czcionka, "", 10)
            pdf.set_text_color(*kolor)
            pdf.cell(0, 7, pdf.t(tekst), ln=1)
            pdf.set_text_color(0, 0, 0)
        pdf.ln(6)

    pdf.add_page()


def _rysuj_galerie_karoserii(pdf, zdjecia_karoserii):
    """Siatka zdjęć karoserii (3 na wiersz) z podpisami data/strefa, doklejana
    na końcu paszportu. zdjecia_karoserii: lista krotek (data, strefa, zalacznik, opis)."""
    pdf.add_page()
    pdf.set_font(pdf.czcionka, "B", 16)
    pdf.cell(0, 12, pdf.t("Zdjęcia karoserii"), ln=1)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 180, pdf.get_y())
    pdf.ln(4)

    szer_zdj, wys_zdj, odstep, na_wiersz = 55, 42, 8, 3
    x_start = pdf.l_margin
    y_wiersza = pdf.get_y()

    for i, (data_z, strefa_z, zalacznik_z, opis_z) in enumerate(zdjecia_karoserii):
        kol = i % na_wiersz
        if kol == 0:
            if pdf.get_y() > pdf.h - (wys_zdj + 24):
                pdf.add_page()
            y_wiersza = pdf.get_y()

        x = x_start + kol * (szer_zdj + odstep)
        if zalacznik_z and os.path.exists(zalacznik_z):
            try:
                pdf.image(zalacznik_z, x=x, y=y_wiersza, w=szer_zdj, h=wys_zdj)
            except Exception:
                pdf.set_xy(x, y_wiersza)
                pdf.set_font(pdf.czcionka, "", 8)
                pdf.cell(szer_zdj, wys_zdj, pdf.t("Błąd wczytania"), border=1, align="C")
        else:
            pdf.set_xy(x, y_wiersza)
            pdf.set_font(pdf.czcionka, "", 8)
            pdf.cell(szer_zdj, wys_zdj, pdf.t("Brak zdjęcia"), border=1, align="C")

        pdf.set_xy(x, y_wiersza + wys_zdj + 1)
        pdf.set_font(pdf.czcionka, "", 8)
        pdf.cell(szer_zdj, 5, pdf.t(f"{data_z} • {strefa_z}"[:32]), align="C")

        if kol == na_wiersz - 1 or i == len(zdjecia_karoserii) - 1:
            pdf.set_y(y_wiersza + wys_zdj + 9)

def generuj_pdf_raportu(auto_nazwa, kategorie_dane, okres_opis, podsumowanie=None,
                         tryb_paszportu=False, zdjecie_glowne=None, specyfikacja=None,
                         terminy=None, punkty_przebiegu=None, zdjecia_karoserii=None):
    """
    kategorie_dane: {klucz: (naglowki, wiersze)} — jak z pobierz_dane_eksportu().
    podsumowanie: opcjonalny słownik z oblicz_podsumowanie_okresu() do nagłówka raportu.
    tryb_paszportu: gdy True, zamiast prostego 3-liniowego nagłówka renderuje pełną
    stronę tytułową (zdjęcie, nazwa, specyfikacja, ważne terminy) i — jeśli podano —
    wykres przebiegu w czasie oraz galerię zdjęć karoserii na końcu. Używane przez
    generuj_pdf_paszportu() do zbudowania "Cyfrowego paszportu pojazdu". Pozostałe
    nowe parametry mają znaczenie tylko w tym trybie.
    Zwraca bajty pliku PDF. Rzuca RuntimeError, jeśli fpdf2 nie jest zainstalowane.
    """
    if FPDF is None:
        raise RuntimeError("Biblioteka 'fpdf2' nie jest zainstalowana — eksport do PDF jest niedostępny. Zainstaluj: pip install fpdf2")

    pdf = _RaportPDF(orientation="P" if tryb_paszportu else "L")
    pdf.add_page()

    if tryb_paszportu:
        _rysuj_strone_tytulowa_paszportu(pdf, auto_nazwa, zdjecie_glowne, specyfikacja or [], terminy or [])
    else:
        pdf.set_font(pdf.czcionka, "B", 18)
        pdf.cell(0, 12, pdf.t(f"Raport pojazdu: {auto_nazwa}"), ln=1)

        pdf.set_font(pdf.czcionka, "", 11)
        pdf.set_text_color(110, 110, 110)
        pdf.cell(0, 7, pdf.t(f"Okres: {okres_opis}"), ln=1)
        pdf.cell(0, 7, pdf.t(f"Wygenerowano: {datetime.now().strftime('%d.%m.%Y %H:%M')}"), ln=1)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(4)

    if podsumowanie:
        waluta = podsumowanie.get("waluta", "PLN")
        pdf.set_font(pdf.czcionka, "B", 13)
        pdf.cell(0, 9, pdf.t("Podsumowanie kosztów"), ln=1)
        pdf.set_draw_color(200, 200, 200)
        pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 180, pdf.get_y())
        pdf.ln(3)

        for etyk, wart in (("Paliwo", podsumowanie["koszt_paliwo"]), ("Serwis", podsumowanie["koszt_serwis"]),
                           ("Inne koszty", podsumowanie["koszt_inne"]), ("RAZEM", podsumowanie["razem"])):
            pdf.set_font(pdf.czcionka, "B" if etyk == "RAZEM" else "", 11)
            pdf.cell(60, 7, pdf.t(etyk))
            pdf.cell(0, 7, pdf.t(f"{formatuj_liczba_eksport(wart)} {waluta}"), ln=1)

        if podsumowanie.get("dystans"):
            pdf.set_font(pdf.czcionka, "", 11)
            pdf.cell(0, 7, pdf.t(f"Przejechany dystans: {formatuj_liczba_eksport(podsumowanie['dystans'], 0)} km"), ln=1)
        if podsumowanie.get("koszt_km"):
            pdf.cell(0, 7, pdf.t(f"Koszt eksploatacji: {formatuj_liczba_eksport(podsumowanie['koszt_km'], 2)} {waluta}/km"), ln=1)
        if podsumowanie.get("spalanie"):
            pdf.cell(0, 7, pdf.t(f"Średnie spalanie: {formatuj_liczba_eksport(podsumowanie['spalanie'], 1)} l/100km"), ln=1)
        pdf.ln(6)

    if tryb_paszportu and punkty_przebiegu:
        if pdf.get_y() > pdf.h - 80:
            pdf.add_page()
        pdf.set_font(pdf.czcionka, "B", 13)
        pdf.cell(0, 9, pdf.t("Przebieg w czasie"), ln=1)
        pdf.set_draw_color(200, 200, 200)
        pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 180, pdf.get_y())
        pdf.ln(6)
        _narysuj_wykres_liniowy(pdf, punkty_przebiegu, pdf.l_margin + 24, pdf.get_y(), pdf.w - pdf.l_margin - pdf.r_margin - 26, 55)
        pdf.set_y(pdf.get_y() + 55 + 14)

    for klucz, (naglowki, wiersze) in kategorie_dane.items():
        tytul = KATEGORIE_EKSPORTU.get(klucz, klucz)
        pdf.set_font(pdf.czcionka, "B", 13)
        pdf.cell(0, 9, pdf.t(f"{tytul} ({len(wiersze)})"), ln=1)
        pdf.set_draw_color(200, 200, 200)
        pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 180, pdf.get_y())
        pdf.ln(2)

        if not wiersze:
            pdf.set_font(pdf.czcionka, "", 10)
            pdf.set_text_color(140, 140, 140)
            pdf.cell(0, 7, pdf.t("Brak danych w wybranym zakresie."), ln=1)
            pdf.set_text_color(0, 0, 0)
            pdf.ln(4)
            continue

        szer_strony = pdf.w - pdf.l_margin - pdf.r_margin
        szer_kol = szer_strony / len(naglowki)
        maks_znakow = max(4, int(szer_kol / 1.8))

        def naglowek_tabeli():
            pdf.set_font(pdf.czcionka, "B", 8.5)
            pdf.set_fill_color(230, 230, 230)
            for h in naglowki:
                pdf.cell(szer_kol, 7, pdf.t(h), border=1, fill=True)
            pdf.ln()
            pdf.set_font(pdf.czcionka, "", 8)

        naglowek_tabeli()
        for w in wiersze:
            if pdf.get_y() > pdf.h - 20:
                pdf.add_page()
                naglowek_tabeli()
            for wartosc in w:
                tekst = pdf.t(wartosc)
                if len(tekst) > maks_znakow:
                    # Zmiana: używamy trzech zwykłych kropek ASCII zamiast znaku Unicode
                    tekst = tekst[:maks_znakow - 3] + "..."
                pdf.cell(szer_kol, 6, tekst, border=1)
            pdf.ln()
        pdf.ln(5)

    if tryb_paszportu and zdjecia_karoserii:
        _rysuj_galerie_karoserii(pdf, zdjecia_karoserii)

    return bytes(pdf.output())

def pobierz_dane_paszportu(auto_id):
    """Zbiera dane do wzbogacenia raportu PDF o 'paszport pojazdu': zdjęcie
    profilowe, specyfikację, ważne terminy, historię przebiegu (do wykresu)
    i zdjęcia karoserii (do galerii na końcu). Używane przez
    eksportuj_dane_zaawansowane() w main.py, gdy w ekranie eksportu zaznaczono
    'Dołącz pełny paszport pojazdu'. Zwraca słownik kwargs gotowy do
    rozpakowania w generuj_pdf_raportu(tryb_paszportu=True, **wynik)."""
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT nazwa, marka, model, generacja, nr_rej, vin, rok_produkcji, "
            "pojemnosc_silnika, moc_silnika, typ_paliwa, skrzynia_biegow, "
            "oc_data, przeglad_data, ac_data, assistance_data, zdjecie_glowne "
            "FROM samochody WHERE id=?", (auto_id,)
        )
        auto = c.fetchone()
        if not auto:
            return {}

        c.execute(
            "SELECT data, strefa, zalacznik, opis FROM zdjecia_karoserii "
            "WHERE auto_id=? ORDER BY data", (auto_id,)
        )
        zdjecia_karoserii = c.fetchall()

    aktualny_przebieg = pobierz_aktualny_przebieg(auto_id)

    specyfikacja = [
        (e, w) for e, w in (
            ("Marka", auto["marka"]), ("Model", auto["model"]), ("Generacja", auto["generacja"]),
            ("Nr rej.", auto["nr_rej"]), ("VIN", auto["vin"]), ("Rocznik", auto["rok_produkcji"]),
            ("Silnik", f"{auto['pojemnosc_silnika']} cm³" if auto["pojemnosc_silnika"] else None),
            ("Moc", f"{auto['moc_silnika']} KM" if auto["moc_silnika"] else None),
            ("Paliwo", auto["typ_paliwa"]), ("Skrzynia", auto["skrzynia_biegow"]),
            ("Aktualny przebieg", f"{formatuj_liczba_eksport(aktualny_przebieg, 0)} km" if aktualny_przebieg else None),
        ) if w
    ]

    terminy = [
        ("Polisa OC", auto["oc_data"]), ("Przegląd techniczny", auto["przeglad_data"]),
        ("Polisa AC", auto["ac_data"]), ("Assistance", auto["assistance_data"]),
    ]

    return {
        "zdjecie_glowne": auto["zdjecie_glowne"],
        "specyfikacja": specyfikacja,
        "terminy": terminy,
        "punkty_przebiegu": pobierz_historie_przebiegu(auto_id),
        "zdjecia_karoserii": zdjecia_karoserii,
    }