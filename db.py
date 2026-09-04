import sqlite3
import os
import re
import shutil
import uuid
import time
import csv
import io
import json
import zipfile
from contextlib import contextmanager
from date import parsuj_date
# 'date as date_cls', a nie 'date' — w projekcie jest własny moduł date.py
# (from date import parsuj_date wyżej) i goła nazwa myliłaby jedno z drugim.
from datetime import datetime, timedelta, date as date_cls

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
# Kosz na usunięte pojazdy: zdjęcia usuniętego auta czekają tu na przywrócenie
# albo na wygaśnięcie retencji. ŚWIADOMIE osobny folder od zalaczniki_odroczone —
# tamten czyści posprzataj_odroczone_zalaczniki() po godzinie, co zjadłoby kosz.
FOLDER_KOSZ = os.path.join(STORAGE_PATH, "kosz_zalaczniki")

# Nazwy podzespołów zakładanych nowemu pojazdowi. Bez emoji — ikonę dokłada
# interfejs, a sama nazwa trafia do bazy, do eksportu CSV/PDF i do wyszukiwarki,
# gdzie emoji tylko przeszkadzało (nie da się go wpisać, psuje sortowanie i nie
# ma glifu w czcionce raportu).
DOMYSLNE_ZADANIA = [
    "Olej silnikowy i filtr", "Filtr powietrza", "Filtr kabinowy",
    "Pasek / Łańcuch rozrządu", "Wymiana opon / Kół", "Klocki hamulcowe", "Tarcze hamulcowe"
]

PAKIETY_SERWISOWE = {
    "Przegląd olejowy": ["Olej silnikowy i filtr", "Filtr powietrza", "Filtr kabinowy"],
    "Sezonowa wymiana opon": ["Wymiana opon / Kół"],
    "Serwis hamulcowy (przód+tył)": ["Klocki hamulcowe", "Tarcze hamulcowe"],
    "Duży przegląd (rozrząd)": ["Pasek / Łańcuch rozrządu", "Olej silnikowy i filtr", "Filtr powietrza"],
}

# Podzespoły założone przez STARSZE wersje aplikacji mają emoji w nazwie
# ("🛢️ Olej silnikowy i filtr"). Nie ruszamy tych rekordów — zamiast migracji
# bazy porównujemy nazwy po normalizacji, dzięki czemu pakiety serwisowe
# trafiają zarówno w stare, jak i w nowe wpisy.
_WZORZEC_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\u2190-\u21FF\u2300-\u27BF\u2B00-\u2BFF\uFE0F\u200D]"
)

def bez_emoji(tekst):
    """Nazwa oczyszczona z emoji i nadmiarowych spacji — do PORÓWNYWANIA nazw,
    nigdy do zapisu (nie przepisujemy użytkownikowi jego własnych wpisów)."""
    return re.sub(r"\s+", " ", _WZORZEC_EMOJI.sub("", str(tekst or ""))).strip()

ROK_MIN = 1900
PROG_KM_POWIADOMIEN = 1500      
PROG_DNI_POWIADOMIEN = 30       
PROG_ILOSC_MAGAZYNU_DOMYSLNY = 1.0    

WALUTY = ["PLN", "EUR", "USD", "GBP", "CZK"]
JEDNOSTKI_SPALANIA = ["l/100km", "km/l", "mpg"]
JEDNOSTKI_ZUZYCIA_EV = ["kWh/100km", "km/kWh"]

# Sylwetki nadwozia do odznaki pojazdu w selektorze. Ikony dobiera warstwa UI
# (utils.IKONY_NADWOZIA), bo db.py celowo nie zna Fleta.
TYPY_NADWOZIA = [
    "Hatchback", "Sedan", "Kombi", "SUV / Crossover",
    "Van / Minivan", "Coupe", "Kabriolet", "Pickup", "Dostawczy",
]

TYPY_PALIWA = ["Benzyna", "Diesel", "LPG", "Hybryda", "Hybryda plug-in", "Elektryczny"]

# Auta, które tankują WYŁĄCZNIE prąd.
TYPY_PALIWA_ELEKTRYCZNE = {"Elektryczny"}

# Auta z DWOMA źródłami naraz — jedyny przypadek, w którym pojedynczy wpis musi
# powiedzieć, czy to było tankowanie, czy ładowanie.
TYPY_PALIWA_DWUZRODLOWE = {"Hybryda plug-in"}

ENERGIA_PALIWO = "paliwo"
ENERGIA_PRAD = "prad"
RODZAJE_ENERGII = [ENERGIA_PALIWO, ENERGIA_PRAD]

# Wolne ładowanie (dom, praca) bywa kilka razy tańsze od szybkiego na trasie,
# więc średnią cenę za kWh liczymy dla każdego osobno.
TYPY_LADOWANIA = ["AC", "DC"]
OPISY_LADOWANIA = {"AC": "AC — wolne (dom / praca)", "DC": "DC — szybkie (trasa)"}

# Elektryk nie ma oleju ani filtra oleju, za to ma własne pozycje serwisowe.
# Bez tego każdy nowy elektryk startował z listą „Olej silnikowy i filtr”.
DOMYSLNE_ZADANIA_EV = [
    "Płyn hamulcowy", "Filtr kabinowy", "Płyn chłodzący baterii",
    "Wymiana opon / Kół", "Klocki hamulcowe", "Tarcze hamulcowe",
    "Przegląd układu wysokiego napięcia",
]

MAKS_BACKOFF_MINUT_SYNC = 60

# Retencja kosza: 0 = trzymaj bez limitu (czyszczenie wyłącznie ręczne).
DNI_KOSZA_OPCJE = [7, 30, 90, 0]
DNI_KOSZA_DOMYSLNIE = 30

PROGI_KM_OPCJE = [500, 1000, 1500, 2000, 3000, 5000]
PROGI_DNI_OPCJE = [7, 14, 30, 60, 90]

# Terminy dokumentów: (klucz ustawienia, kolumna w samochody, etykieta).
# Każdy ma WŁASNY próg powiadomień — o kończącym się OC chce się wiedzieć
# z innym wyprzedzeniem niż o dacie ważności apteczki. Brak własnego progu
# (klucz nieustawiony) = obowiązuje wspólny prog_dni_powiadomien.
TERMINY_DOKUMENTOW = [
    ("oc",         "oc_data",         "Polisa OC"),
    ("przeglad",   "przeglad_data",   "Przegląd techniczny"),
    ("ac",         "ac_data",         "Polisa AC"),
    ("assistance", "assistance_data", "Assistance"),
    ("gasnica",    "gasnica_data",    "Gaśnica"),
    ("apteczka",   "apteczka_data",   "Apteczka"),
    ("gwarancja",  "gwarancja_data",  "Gwarancja producenta"),
]
KLUCZE_TERMINOW = {k for k, _, _ in TERMINY_DOKUMENTOW}
PROGI_DNI_DOKUMENTU_OPCJE = [7, 14, 30, 60, 90, 180, 365]

PRIORYTETY_DO_ZROBIENIA = ["Wysoki", "Średni", "Niski"]
KOLEJNOSC_PRIORYTETU = {"Wysoki": 1, "Średni": 2, "Niski": 3}

KOLORY_MOTYWU = ["Indygo", "Czerwony", "Zielony", "Niebieski", "Szary", "Pomarańczowy", "Fioletowy", "Różowy", "Żółty", "Limonkowy"]

KATEGORIE_MAGAZYNU = ["Płyny eksploatacyjne", "Oleje i smary", "Żarówki i bezpieczniki", "Filtry", "Akcesoria", "Inne"]
JEDNOSTKI_MAGAZYNU = ["szt", "l", "ml", "kg", "g"]

TABELE_Z_ZALACZNIKIEM = {"tankowania", "wizyty", "inne_koszty", "zdjecia_karoserii", "historia", "zestawy_opon", "magazyn_czesci"}

# Krótka notatka przy pojedynczym wpisie. Wartość to nazwa kolumny z TREŚCIĄ:
# wpisy, które takiego pola nie miały, dostały w migracji 34 własne 'notatka',
# a tam gdzie pole opisowe istnieje od dawna (wizyta, zadanie do zrobienia,
# magazyn, opony, warsztat) używamy JEGO — dokładanie drugiego pola na to samo
# rozjechałoby dane, które użytkownik już wpisał.
POLA_NOTATKI = {
    "tankowania": "notatka",
    "historia": "notatka",
    "inne_koszty": "notatka",
    "odczyty_przebiegu": "notatka",
    "wizyty": "notatki",
    "do_zrobienia": "opis",
    "magazyn_czesci": "notatki",
    "zestawy_opon": "notatki",
    "warsztaty": "notatki",
}

# Tabele, w których notatka ma WŁASNY podpis (notatka_autor + notatka_data).
# Przy współdzielonym pojeździe uwagę dopisuje zwykle ktoś inny niż autor wpisu
# i długo po jego dodaniu, więc dodane_przez/zmodyfikowane_przez tego nie oddaje.
TABELE_NOTATKI_Z_PODPISEM = {"tankowania", "historia", "inne_koszty", "odczyty_przebiegu"}

# Notatka ma być KRÓTKA — jedno zdanie kontekstu, nie dziennik. Limit trzyma
# karty na listach w ryzach i jest wspólny dla formularza i szybkiej edycji.
MAKS_DLUGOSC_NOTATKI = 200

STREFY_KAROSERII = ["Przód", "Tył", "Bok lewy", "Bok prawy", "Wnętrze / Kokpit", "Uszkodzenie / Rysa", "Inne"]
TYPY_ZDJECIA = ["Brak", "Przed naprawą", "Po naprawie"]

OSIE_MONTAZU = ["Wszystkie", "Przód", "Tył"]

KOLEJNOSC_TRYBOW_MOTYWU = ["jasny", "ciemny", "system"]

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
            """,
            # Wersja 18: Kolumny zdalne_id — rozszerzenie współdzielenia pojazdu
            # (patrz sync.py) na resztę danych, nie tylko tankowania. NULL = rekord
            # czysto lokalny / jeszcze niezsynchronizowany, zero zmian w zachowaniu.
            """
            ALTER TABLE zadania ADD COLUMN zdalne_id TEXT;
            ALTER TABLE historia ADD COLUMN zdalne_id TEXT;
            ALTER TABLE wizyty ADD COLUMN zdalne_id TEXT;
            ALTER TABLE magazyn_czesci ADD COLUMN zdalne_id TEXT;
            ALTER TABLE zestawy_opon ADD COLUMN zdalne_id TEXT;
            ALTER TABLE inne_koszty ADD COLUMN zdalne_id TEXT;
            ALTER TABLE do_zrobienia ADD COLUMN zdalne_id TEXT;
            ALTER TABLE warsztaty ADD COLUMN zdalne_id TEXT;
            ALTER TABLE wydatki_cykliczne ADD COLUMN zdalne_id TEXT;
            ALTER TABLE odczyty_przebiegu ADD COLUMN zdalne_id TEXT;
            """,
            # Wersja 19: Wsparcie synchronizacji EDYCJI i USUNIĘĆ (nie tylko nowych
            # wpisów). zdalny_hash pamięta hash treści ostatnio zsynchronizowanej z
            # serwerem — różnica przy kolejnej synchronizacji oznacza lokalną edycję
            # do wypchnięcia. zdalne_nagrobki to lokalna kolejka "do usunięcia na
            # serwerze przy najbliższej okazji": rekord znika z lokalnej bazy od razu
            # (jak dotychczas), a jego zdalny odpowiednik trzeba jeszcze osobno
            # oznaczyć jako usunięty. Bez auto_id — kasowanie po zdalnym ID nie jest
            # przywiązane do konkretnego pojazdu.
            """
            ALTER TABLE tankowania ADD COLUMN zdalny_hash TEXT;
            ALTER TABLE zadania ADD COLUMN zdalny_hash TEXT;
            ALTER TABLE historia ADD COLUMN zdalny_hash TEXT;
            ALTER TABLE wizyty ADD COLUMN zdalny_hash TEXT;
            ALTER TABLE magazyn_czesci ADD COLUMN zdalny_hash TEXT;
            ALTER TABLE zestawy_opon ADD COLUMN zdalny_hash TEXT;
            ALTER TABLE inne_koszty ADD COLUMN zdalny_hash TEXT;
            ALTER TABLE do_zrobienia ADD COLUMN zdalny_hash TEXT;
            ALTER TABLE warsztaty ADD COLUMN zdalny_hash TEXT;
            ALTER TABLE wydatki_cykliczne ADD COLUMN zdalny_hash TEXT;
            ALTER TABLE odczyty_przebiegu ADD COLUMN zdalny_hash TEXT;
            CREATE TABLE IF NOT EXISTS zdalne_nagrobki (id INTEGER PRIMARY KEY AUTOINCREMENT, tabela TEXT NOT NULL, zdalny_id TEXT NOT NULL);
            """,
            # Wersja 20: Synchronizacja danych opisowych pojazdu (patrz sync.py:
            # KOLUMNY_POJAZDU / _synchronizuj_info_pojazdu) oraz słownika tagów
            # (nazwa+kolor) — kolejne elementy współdzielenia pojazdu, dotąd
            # pomijane przez sync mimo że były wymieniane jako "synchronizowane".
            """
            ALTER TABLE samochody ADD COLUMN info_zdalne_id TEXT;
            ALTER TABLE samochody ADD COLUMN zdalny_hash_info TEXT;
            ALTER TABLE tagi ADD COLUMN zdalne_id TEXT;
            ALTER TABLE tagi ADD COLUMN zdalny_hash TEXT;
            """,
            # Wersja 21: Atrybucja wpisów przy współdzielonych pojazdach — kto
            # dodał dany wpis (tankowanie/serwis/wizytę/koszt). Wypełniane samą
            # nazwą ustawioną lokalnie w Ustawieniach (patrz pobierz_moje_imie),
            # bo anonymous auth w Supabase nie niesie żadnej nazwy użytkownika.
            # Puste dla wpisów sprzed tej wersji.
            """
            ALTER TABLE tankowania ADD COLUMN dodane_przez TEXT;
            ALTER TABLE historia ADD COLUMN dodane_przez TEXT;
            ALTER TABLE wizyty ADD COLUMN dodane_przez TEXT;
            ALTER TABLE inne_koszty ADD COLUMN dodane_przez TEXT;
            """,
            # Wersja 22: Indeksy pod synchronizację (sync.py) — _wypchnij_tabele/
            # _pobierz_tabele robią WHERE auto_id=? AND zdalne_id IS NULL/NOT NULL
            # na każdej tabeli przy KAŻDEJ synchronizacji; bez indeksu to pełne
            # skanowanie tabeli, co przy dużej historii zacznie zauważalnie
            # spowalniać sync. idx_historia_zdalne osobno, bo historia nie ma
            # kolumny auto_id (jest tylko przez zadanie_id/wizyta_id).
            """
            CREATE INDEX IF NOT EXISTS idx_tankowania_auto_zdalne ON tankowania(auto_id, zdalne_id);
            CREATE INDEX IF NOT EXISTS idx_zadania_auto_zdalne ON zadania(auto_id, zdalne_id);
            CREATE INDEX IF NOT EXISTS idx_wizyty_auto_zdalne ON wizyty(auto_id, zdalne_id);
            CREATE INDEX IF NOT EXISTS idx_magazyn_czesci_auto_zdalne ON magazyn_czesci(auto_id, zdalne_id);
            CREATE INDEX IF NOT EXISTS idx_zestawy_opon_auto_zdalne ON zestawy_opon(auto_id, zdalne_id);
            CREATE INDEX IF NOT EXISTS idx_inne_koszty_auto_zdalne ON inne_koszty(auto_id, zdalne_id);
            CREATE INDEX IF NOT EXISTS idx_do_zrobienia_auto_zdalne ON do_zrobienia(auto_id, zdalne_id);
            CREATE INDEX IF NOT EXISTS idx_warsztaty_auto_zdalne ON warsztaty(auto_id, zdalne_id);
            CREATE INDEX IF NOT EXISTS idx_wydatki_cykliczne_auto_zdalne ON wydatki_cykliczne(auto_id, zdalne_id);
            CREATE INDEX IF NOT EXISTS idx_odczyty_przebiegu_auto_zdalne ON odczyty_przebiegu(auto_id, zdalne_id);
            CREATE INDEX IF NOT EXISTS idx_tagi_auto_zdalne ON tagi(auto_id, zdalne_id);
            CREATE INDEX IF NOT EXISTS idx_historia_zdalne ON historia(zdalne_id);
            """,
            # Wersja 23: Log aktywności — kto i kiedy ostatnio EDYTOWAŁ wpis (w
            # odróżnieniu od dodane_przez, które mówi tylko kto go UTWORZYŁ).
            # Wypełniane wyłącznie w blokach UPDATE formularzy edycji (patrz
            # forms_view.py) — puste dla wpisów, które nigdy nie były edytowane.
            """
            ALTER TABLE tankowania ADD COLUMN zmodyfikowane_przez TEXT;
            ALTER TABLE tankowania ADD COLUMN data_modyfikacji TEXT;
            ALTER TABLE historia ADD COLUMN zmodyfikowane_przez TEXT;
            ALTER TABLE historia ADD COLUMN data_modyfikacji TEXT;
            ALTER TABLE wizyty ADD COLUMN zmodyfikowane_przez TEXT;
            ALTER TABLE wizyty ADD COLUMN data_modyfikacji TEXT;
            ALTER TABLE inne_koszty ADD COLUMN zmodyfikowane_przez TEXT;
            ALTER TABLE inne_koszty ADD COLUMN data_modyfikacji TEXT;
            """,
            # Wersja 24: Szybki status/wiadomość pojazdu — jedna wspólna notatka
            # widoczna dla domowników korzystających z auta (np. "Zatankowany do
            # pełna"), edytowana z kompaktowej karty pojazdu na ekranie głównym
            # (patrz main_view.py: buduj_naglowek_auta).
            """
            ALTER TABLE samochody ADD COLUMN wiadomosc_statusu TEXT;
            """,
            # Wersja 25: Synchronizacja zużycia części z magazynu podczas wizyt
            # (wizyta_czesci_magazynu) — dotąd tabela była celowo pomijana przez
            # sync (patrz KONFIGURACJA_SYNC w sync.py), więc przy współdzielonym
            # pojeździe zużycie części dodane offline na jednym urządzeniu nie
            # pojawiało się na drugim. Bez auto_id, tak jak historia — dowiązanie
            # do pojazdu tylko pośrednio przez wizyta_id -> wizyty.auto_id.
            """
            ALTER TABLE wizyta_czesci_magazynu ADD COLUMN zdalne_id TEXT;
            ALTER TABLE wizyta_czesci_magazynu ADD COLUMN zdalny_hash TEXT;
            CREATE INDEX IF NOT EXISTS idx_wizyta_czesci_magazynu_zdalne ON wizyta_czesci_magazynu(zdalne_id);
            """,
            # Wersja 26: (a) indywidualne progi powiadomień per podzespół —
            # analogicznie do prog_ostrzezenia w magazyn_czesci. NULL = użyj
            # globalnych prog_km_powiadomien / prog_dni_powiadomien z Ustawień,
            # więc dla istniejących wpisów nic się nie zmienia. (b) kolumny
            # synchronizacji dla własnych pakietów serwisowych — bez nich partner
            # przy współdzielonym pojeździe nie widział Twoich pakietów.
            """
            ALTER TABLE zadania ADD COLUMN prog_km INTEGER;
            ALTER TABLE zadania ADD COLUMN prog_dni INTEGER;
            ALTER TABLE pakiety_serwisowe_wlasne ADD COLUMN zdalne_id TEXT;
            ALTER TABLE pakiety_serwisowe_wlasne ADD COLUMN zdalny_hash TEXT;
            CREATE INDEX IF NOT EXISTS idx_pakiety_wlasne_auto_zdalne ON pakiety_serwisowe_wlasne(auto_id, zdalne_id);
            """,
            # Wersja 27: (a) gwarancja pojazdu — dokładnie ten sam wzorzec co
            # AC/Assistance/gaśnica/apteczka, plus opcjonalny limit kilometrowy;
            # (b) kolejka offline dla auto-synchronizacji — dotąd brak sieci przy
            # zapisie kończył się cichym `except: pass` bez ponowienia. UNIQUE na
            # auto_id, bo sync i tak działa na całym pojeździe naraz.
            """
            ALTER TABLE samochody ADD COLUMN gwarancja_data TEXT;
            ALTER TABLE samochody ADD COLUMN gwarancja_przebieg INTEGER;
            CREATE TABLE IF NOT EXISTS kolejka_sync (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, powod TEXT, proby INTEGER NOT NULL DEFAULT 0, ostatnia_proba TEXT, nastepna_proba TEXT, ostatni_blad TEXT);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_kolejka_sync_auto ON kolejka_sync(auto_id);
            """,
            # Wersja 28: Cykliczne przypomnienia bez kosztu — wydatki_cykliczne
            # może teraz reprezentować też zwykłe przypomnienie (np. "co miesiąc
            # sprawdź ciśnienie w oponach"), bez wymuszania kwoty. czy_koszt=1
            # (domyślnie, zgodnie z dotychczasowym zachowaniem) to klasyczny
            # wydatek cykliczny — zaznaczenie "Zapłacone" dopisuje kwotę do
            # inne_koszty. czy_koszt=0 to samo przypomnienie — zaznaczenie
            # "Wykonano" tylko przesuwa termin, bez wpisu kosztu.
            """
            ALTER TABLE wydatki_cykliczne ADD COLUMN czy_koszt INTEGER NOT NULL DEFAULT 1;
            """,
            # Wersja 29: Kosz na usunięte pojazdy. Usunięcie auta nie kasuje już
            # danych — zrzuca cały pojazd (tabela samochody + wszystkie tabele
            # potomne, łącznie z historią i wizytami) do JSON-a w kolumnie
            # 'migawka', a fizyczne zdjęcia przenosi do FOLDER_KOSZ. 'pliki' to
            # mapa [ścieżka_w_koszu, ścieżka_oryginalna] potrzebna przy powrocie.
            # Nagrobki synchronizacji CELOWO nie powstają przy przenoszeniu do
            # kosza (patrz usun_auto_do_kosza) — dopóki auto siedzi w koszu, na
            # serwerze i u współdzielących nadal istnieje; nagrobki rejestruje
            # dopiero trwałe skasowanie. 'schemat_wersja' pozwala przy
            # przywracaniu rozpoznać migawkę zrobioną na starszym schemacie
            # bazy — kolumny, których już nie ma, są wtedy pomijane.
            """
            CREATE TABLE IF NOT EXISTS kosz_pojazdy (id INTEGER PRIMARY KEY AUTOINCREMENT, nazwa TEXT NOT NULL, data_usuniecia TEXT NOT NULL, migawka TEXT NOT NULL, pliki TEXT, liczba_wpisow INTEGER NOT NULL DEFAULT 0, rozmiar_plikow INTEGER NOT NULL DEFAULT 0, schemat_wersja INTEGER);
            CREATE INDEX IF NOT EXISTS idx_kosz_data ON kosz_pojazdy(data_usuniecia);
            """,
            # Wersja 30: zużycie części z magazynu przy POJEDYNCZYM wpisie
            # serwisowym, a nie tylko przy wizycie zbiorczej. Osobna tabela,
            # bo wizyta_czesci_magazynu.wizyta_id jest NOT NULL i dowiązane do
            # tabeli wizyt — wpis poza wizytą nie ma czego tam wskazać.
            # Struktura celowo lustrzana (ilosc_uzyta + kolumny synchronizacji),
            # więc cała obsługa w sync.py i w koszu jest tym samym kodem.
            """
            CREATE TABLE IF NOT EXISTS historia_czesci_magazynu (id INTEGER PRIMARY KEY AUTOINCREMENT, historia_id INTEGER NOT NULL, magazyn_id INTEGER NOT NULL, ilosc_uzyta REAL NOT NULL DEFAULT 1, zdalne_id TEXT, zdalny_hash TEXT, FOREIGN KEY (historia_id) REFERENCES historia(id) ON DELETE CASCADE, FOREIGN KEY (magazyn_id) REFERENCES magazyn_czesci(id) ON DELETE CASCADE);
            CREATE INDEX IF NOT EXISTS idx_historia_czesci_historia ON historia_czesci_magazynu(historia_id);
            CREATE INDEX IF NOT EXISTS idx_historia_czesci_magazyn ON historia_czesci_magazynu(magazyn_id);
            CREATE INDEX IF NOT EXISTS idx_historia_czesci_zdalne ON historia_czesci_magazynu(zdalne_id);
            """,
            # Wersja 31: odkładanie („drzemka”) pojedynczego powiadomienia.
            # „Wiem o przeglądzie, zrobię go za dwa tygodnie” — wyciszenie JEDNEGO
            # przypomnienia bez oznaczania czegokolwiek jako wykonane. Klucz to
            # stabilny identyfikator powiadomienia (patrz _klucz_powiadomienia),
            # a nie treść, bo opis zmienia się z każdym dniem („Zostało 12 dni”).
            # Świadomie NIE synchronizujemy tej tabeli ani nie zabieramy jej do
            # kosza: drzemka jest krótkotrwała, osobista i dotyczy tego urządzenia.
            """
            CREATE TABLE IF NOT EXISTS wyciszone_powiadomienia (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, klucz TEXT NOT NULL, do_dnia TEXT NOT NULL, tytul TEXT, utworzono TEXT, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_wyciszone_klucz ON wyciszone_powiadomienia(auto_id, klucz);
            """,
            # Wersja 32: typ nadwozia. Do tej pory każdy pojazd w selektorze
            # wyglądał identycznie (ta sama ikona samochodu), więc przy kilku
            # autach w garażu rozróżniało się je dopiero po przeczytaniu nazwy.
            # Sylwetka nadwozia na krążku w kolorze przypisanym do auta daje
            # rozpoznanie jednym spojrzeniem. Puste = ogólna ikona, jak dotąd.
            """
            ALTER TABLE samochody ADD COLUMN nadwozie TEXT;
            """,
            # Wersja 33: osobne śledzenie paliwa i prądu. Hybryda plug-in zużywa
            # OBA źródła, a dotąd wpis mógł być tylko jednym z nich — trzeba było
            # wybrać, którą stronę się liczy. Teraz każdy wpis w 'tankowania'
            # deklaruje 'rodzaj_energii' ('paliwo' albo 'prad'), więc zużycie,
            # koszty i wykresy da się policzyć dla każdej strony niezależnie.
            # 'typ_ladowania' (AC/DC) rozdziela wolne ładowanie w domu od drogiego
            # szybkiego na trasie. Bateria i deklarowany zasięg zasilają szacunek
            # realnego zasięgu z RZECZYWISTEGO zużycia użytkownika.
            """
            ALTER TABLE tankowania ADD COLUMN rodzaj_energii TEXT;
            ALTER TABLE tankowania ADD COLUMN typ_ladowania TEXT;
            ALTER TABLE samochody ADD COLUMN pojemnosc_baterii TEXT;
            ALTER TABLE samochody ADD COLUMN zasieg_ev TEXT;
            CREATE INDEX IF NOT EXISTS idx_tankowania_auto_rodzaj ON tankowania(auto_id, rodzaj_energii);
            """,
            # Wersja 34: krótka notatka przy POJEDYNCZYM wpisie. Do tej pory
            # kontekst („tankowanie po zjeździe z autostrady”, „olej dolany, nie
            # wymiana”) nie miał się gdzie zapisać — zostawały tagi, czyli
            # słownik wspólny dla całego pojazdu, albo nazwa kosztu, która trafia
            # na wykresy. Notatka jest wolnym tekstem JEDNEGO wpisu i nigdzie się
            # nie agreguje.
            # Kolumny osobne, a nie jedna wspólna tabela notatek: cała reszta
            # aplikacji (synchronizacja z KONFIGURACJA_SYNC, kosz, cofanie
            # usunięcia przez PRAGMA table_info, eksport) działa na kolumnach
            # rekordu i dostaje notatkę za darmo — tabela obok wymagałaby łatki
            # w każdym z tych miejsc.
            # 'notatka_autor' i 'notatka_data' są niezależne od
            # dodane_przez/zmodyfikowane_przez, bo uwagę przy współdzielonym
            # pojeździe zwykle dopisuje KTO INNY niż autor wpisu, i to długo po
            # jego dodaniu. Wizyty (notatki), zadania do zrobienia (opis),
            # magazyn, opony i warsztaty mają swoje pole opisu od dawna —
            # tam dokładamy tylko wspólną prezentację, bez nowych kolumn.
            """
            ALTER TABLE tankowania ADD COLUMN notatka TEXT;
            ALTER TABLE tankowania ADD COLUMN notatka_autor TEXT;
            ALTER TABLE tankowania ADD COLUMN notatka_data TEXT;
            ALTER TABLE historia ADD COLUMN notatka TEXT;
            ALTER TABLE historia ADD COLUMN notatka_autor TEXT;
            ALTER TABLE historia ADD COLUMN notatka_data TEXT;
            ALTER TABLE inne_koszty ADD COLUMN notatka TEXT;
            ALTER TABLE inne_koszty ADD COLUMN notatka_autor TEXT;
            ALTER TABLE inne_koszty ADD COLUMN notatka_data TEXT;
            ALTER TABLE odczyty_przebiegu ADD COLUMN notatka TEXT;
            ALTER TABLE odczyty_przebiegu ADD COLUMN notatka_autor TEXT;
            ALTER TABLE odczyty_przebiegu ADD COLUMN notatka_data TEXT;
            """,
            # Wersja 35: analiza i prognozy. (a) 'pojemnosc_baku' domyka komplet
            # danych o zbiornikach — bateria była od wersji 33, bak dopiero teraz;
            # bez niego nie da się policzyć zasięgu auta spalinowego, a to
            # najczęściej zadawane pytanie przed dłuższą trasą. Pole TEKSTOWE,
            # jak reszta specyfikacji ('55 l', '55,5'), czytane przez
            # _liczba_lub_none. (b) Tabela budżetów: limit wydatków per pojazd,
            # osobno na paliwo, serwis, inne i wszystko razem, w wersji
            # miesięcznej albo rocznej. UNIQUE na (auto_id, kategoria, okres),
            # bo dwa limity na to samo nie mają sensu — zapis jest upsertem.
            # Kolumny synchronizacji, bo przy współdzielonym aucie limit ustala
            # się raz dla obu osób; inaczej każdy patrzyłby na inny budżet.
            """
            ALTER TABLE samochody ADD COLUMN pojemnosc_baku TEXT;
            CREATE TABLE IF NOT EXISTS budzety (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, kategoria TEXT NOT NULL, okres TEXT NOT NULL, kwota REAL NOT NULL DEFAULT 0, zdalne_id TEXT, zdalny_hash TEXT, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_budzety_klucz ON budzety(auto_id, kategoria, okres);
            CREATE INDEX IF NOT EXISTS idx_budzety_zdalne ON budzety(zdalne_id);
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
            # Istniejące wpisy nie mają jeszcze rodzaju energii — wypełniamy go
            # według typu paliwa POJAZDU, bo do tej pory auto mogło mieć tylko
            # jedno źródło. Dzięki temu żadna statystyka nie zaczyna od zera.
            if i == 32:
                cursor.execute(
                    "UPDATE tankowania SET rodzaj_energii = CASE WHEN auto_id IN "
                    "(SELECT id FROM samochody WHERE typ_paliwa='Elektryczny') THEN 'prad' ELSE 'paliwo' END "
                    "WHERE rodzaj_energii IS NULL"
                )

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

    # Dopiero PO migracjach — tabela kosza musi już istnieć. Poza tym wygasłe
    # pozycje kasujemy raz, przy starcie aplikacji, a nie przy każdym wejściu na
    # ekran kosza: retencja liczona jest w dniach, więc częściej nie ma sensu.
    posprzataj_kosz()

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

def usun_ustawienie(klucz):
    """Kasuje klucz, przez co ustawienie wraca do wartości domyślnej. Używane
    tam, gdzie „brak wpisu” znaczy coś innego niż pusty string — np. próg dni
    dla konkretnego terminu (wtedy obowiązuje globalny) albo układ kokpitu
    pojazdu (wtedy dziedziczy wspólny)."""
    with polacz_baze() as conn:
        conn.execute("DELETE FROM ustawienia WHERE klucz=?", (klucz,))

def pobierz_tryb_motywu():
    """Zwraca 'jasny' / 'ciemny' / 'system'. Jeśli nowy klucz nie był jeszcze
    zapisany, migruje w locie ze starego booleanowego 'tryb_ciemny'."""
    w = pobierz_ustawienie("tryb_motywu")
    if w in KOLEJNOSC_TRYBOW_MOTYWU:
        return w
    return "ciemny" if pobierz_ustawienie("tryb_ciemny", "0") == "1" else "jasny"

def zapisz_tryb_motywu(tryb):
    if tryb in KOLEJNOSC_TRYBOW_MOTYWU:
        zapisz_ustawienie("tryb_motywu", tryb)

def pobierz_czysta_czern():
    """Czy tryb ciemny ma używać czystej czerni (#000000) zamiast ciemnych
    szarości. Osobne ustawienie, a nie czwarty tryb motywu — dzięki temu działa
    też wtedy, gdy tryb „system” sam przełączy telefon na ciemny. Na ekranach
    OLED czarny piksel jest po prostu zgaszony, więc to realnie mniej prądu."""
    return pobierz_ustawienie("czysta_czern", "0") == "1"

def zapisz_czysta_czern(wlaczona):
    zapisz_ustawienie("czysta_czern", "1" if wlaczona else "0")

def pobierz_walute():
    w = pobierz_ustawienie("waluta", "PLN")
    return w if w in WALUTY else "PLN"

def pobierz_jednostke_spalania():
    w = pobierz_ustawienie("jednostka_spalania", "l/100km")
    return w if w in JEDNOSTKI_SPALANIA else "l/100km"

def pobierz_jednostke_zuzycia_ev():
    w = pobierz_ustawienie("jednostka_zuzycia_ev", "kWh/100km")
    return w if w in JEDNOSTKI_ZUZYCIA_EV else "kWh/100km"


def przelicz_zuzycie(wartosc_na_100km, elektryczny=False):
    """(wartość w jednostce wybranej w Ustawieniach, nazwa jednostki). Wejściem
    ZAWSZE jest zużycie na 100 km — dokładnie to, co liczy reszta aplikacji.
    Jedno miejsce na to przeliczenie, bo korzysta z niego i interfejs
    (utils.formatuj_spalanie), i teksty obserwacji budowane tutaj, w db.
    Uwaga na kierunek: przy km/l i mpg WIĘKSZA liczba znaczy MNIEJSZE zużycie,
    więc żaden tekst nie może wnioskować o trendzie z samej tej wartości."""
    jednostka = pobierz_jednostke_zuzycia_ev() if elektryczny else pobierz_jednostke_spalania()
    try:
        val = float(wartosc_na_100km)
    except (TypeError, ValueError):
        return None, jednostka
    if val <= 0:
        return None, jednostka
    if jednostka in ("km/l", "km/kWh"):
        return 100.0 / val, jednostka
    if jednostka == "mpg":
        return 235.214583 / val, jednostka
    return val, jednostka


def formatuj_zuzycie_tekst(wartosc_na_100km, elektryczny=False, decimale=1):
    """Zużycie jako gotowy tekst z jednostką — wersja dla warstwy danych
    (teksty obserwacji, eksport). Interfejs używa utils.formatuj_spalanie,
    które formatuje liczbę po swojemu, ale przelicza tym samym kodem."""
    wynik, jednostka = przelicz_zuzycie(wartosc_na_100km, elektryczny)
    if wynik is None:
        return f"- {jednostka}"
    return f"{formatuj_liczba_eksport(wynik, decimale)} {jednostka}"


def czy_pojazd_elektryczny(auto_id):
    """True tylko dla auta jeżdżącego WYŁĄCZNIE na prąd. Hybryda plug-in tu NIE
    wchodzi — ona ma oba źródła i o etykietach decyduje rodzaj konkretnego wpisu
    (patrz rodzaje_energii_pojazdu / etykiety_energii)."""
    if not auto_id:
        return False
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT typ_paliwa FROM samochody WHERE id=?", (auto_id,))
        w = c.fetchone()
    return bool(w) and str(w[0] or "") in TYPY_PALIWA_ELEKTRYCZNE


def etykiety_paliwa(elektryczny=False):
    """Wszystkie etykiety i jednostki zależne od typu napędu w jednym miejscu.
    Zero zmian w schemacie bazy — kolumny 'litry' i 'stacja' zostają te same,
    zmienia się tylko to, jak je nazywamy w interfejsie."""
    if elektryczny:
        return {
            "jednostka": "kWh",
            "ilosc": "Naładowano (kWh)",
            "punkt": "Punkt ładowania",
            "punkt_opcjonalnie": "Punkt ładowania (opcjonalnie)",
            "punkt_hint": "np. Orlen Charge, GreenWay, garaż",
            "punkt_recznie": "Wpisz nazwę punktu ładowania",
            "do_pelna": "Naładowano do pełna (wymagane do zużycia)",
            "cena_jednostkowa": "Cena/kWh",
            "zuzycie": "Średnie zużycie",
            "naglowek_listy": "Historia ładowań",
            "ikona_listy": "ladowanie",
            "zdarzenie": "ładowanie",
            "suma_ilosci": "Naładowano",
            "brak_pelnych": "Wymaga 2x do pełna",
        }
    return {
        "jednostka": "L",
        "ilosc": "Zatankowano (Litry)",
        "punkt": "Stacja paliw",
        "punkt_opcjonalnie": "Stacja paliw (opcjonalnie)",
        "punkt_hint": "np. Orlen, Shell, BP",
        "punkt_recznie": "Wpisz nazwę stacji",
        "do_pelna": "Zatankowano do pełna (wymagane do spalania)",
        "cena_jednostkowa": "Cena/L",
        "zuzycie": "Średnie spalanie",
        "naglowek_listy": "Historia tankowań",
        "ikona_listy": "tankowanie",
        "zdarzenie": "tankowanie",
        "suma_ilosci": "Zatankowano",
        "brak_pelnych": "Wymaga 2x do pełna",
    }

def pobierz_typ_paliwa(auto_id):
    if not auto_id:
        return ""
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT typ_paliwa FROM samochody WHERE id=?", (auto_id,))
        w = c.fetchone()
    return str((w or [""])[0] or "")


def czy_pojazd_dwuzrodlowy(auto_id):
    """True dla hybrydy plug-in — jedynego napędu, który realnie tankuje OBA
    źródła i wymaga, żeby pojedynczy wpis powiedział, którego dotyczy."""
    return pobierz_typ_paliwa(auto_id) in TYPY_PALIWA_DWUZRODLOWE


def rodzaje_energii_pojazdu(auto_id):
    """Które źródła energii ma sens pokazywać dla tego auta.
    Elektryk → sam prąd, plug-in → oba, reszta → samo paliwo."""
    typ = pobierz_typ_paliwa(auto_id)
    if typ in TYPY_PALIWA_DWUZRODLOWE:
        return list(RODZAJE_ENERGII)
    if typ in TYPY_PALIWA_ELEKTRYCZNE:
        return [ENERGIA_PRAD]
    return [ENERGIA_PALIWO]


def domyslny_rodzaj_energii(auto_id):
    """Rodzaj podstawiany nowemu wpisowi, zanim użytkownik cokolwiek przełączy."""
    return rodzaje_energii_pojazdu(auto_id)[0]


def normalizuj_rodzaj_energii(wartosc, auto_id=None):
    """Stare wpisy (sprzed migracji 33) i dane z importu mogą nie mieć rodzaju —
    wtedy decyduje typ pojazdu."""
    tekst = str(wartosc or "").strip().lower()
    if tekst in RODZAJE_ENERGII:
        return tekst
    return domyslny_rodzaj_energii(auto_id) if auto_id else ENERGIA_PALIWO


def etykiety_energii(rodzaj):
    """Etykiety zależne od RODZAJU WPISU, a nie od typu pojazdu — przy hybrydzie
    plug-in jedno auto ma i tankowania, i ładowania, więc nazwy muszą podążać za
    konkretnym wpisem. etykiety_paliwa() zostaje jako cieńsza nakładka na to."""
    return etykiety_paliwa(rodzaj == ENERGIA_PRAD)


ETYKIETY_RODZAJU = {
    ENERGIA_PALIWO: "Paliwo",
    ENERGIA_PRAD: "Prąd",
}


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

def pobierz_prog_dni_dokumentu(klucz):
    """Próg powiadomień (w dniach) dla KONKRETNEGO terminu — OC, przeglądu,
    apteczki itd. Brak własnego ustawienia oznacza „jak domyślny” i zwraca
    wspólny prog_dni_powiadomien, więc nieruszane terminy zachowują się jak
    przed rozbiciem progów."""
    if klucz not in KLUCZE_TERMINOW:
        return pobierz_prog_dni()
    zapisane = pobierz_ustawienie(f"prog_dni_{klucz}")
    if zapisane in (None, ""):
        return pobierz_prog_dni()
    try:
        wartosc = int(zapisane)
    except (TypeError, ValueError):
        return pobierz_prog_dni()
    return wartosc if wartosc > 0 else pobierz_prog_dni()

def zapisz_prog_dni_dokumentu(klucz, wartosc):
    """Pusta wartość KASUJE własny próg — termin wraca pod wspólny domyślny."""
    if klucz not in KLUCZE_TERMINOW:
        return
    tekst = str(wartosc or "").strip()
    if not tekst:
        usun_ustawienie(f"prog_dni_{klucz}")
        return
    zapisz_ustawienie(f"prog_dni_{klucz}", tekst)

def pobierz_wlasny_prog_dni_dokumentu(klucz):
    """Surowa wartość do formularza Ustawień: "" gdy termin idzie za domyślnym."""
    zapisane = pobierz_ustawienie(f"prog_dni_{klucz}")
    return str(zapisane) if zapisane not in (None, "") else ""

def pobierz_moje_imie():
    """Lokalna nazwa/imię tego użytkownika/urządzenia — dopisywana jako
    'dodane_przez' przy nowych wpisach kosztowych, żeby przy współdzielonym
    pojeździe było widać, kto co dodał. Domyślnie 'Kierowca', dopóki nie
    zostanie ustawiona w Ustawieniach."""
    return pobierz_ustawienie("moje_imie", "Kierowca") or "Kierowca"

def zapisz_moje_imie(imie):
    zapisz_ustawienie("moje_imie", (imie or "").strip() or "Kierowca")

def zakolejkuj_synchronizacje(auto_id, powod=None, blad=None):
    """Zapamiętuje, że auto-synchronizacja tego pojazdu się nie udała (zwykle brak
    sieci). Kolejny wpis dla tego samego pojazdu tylko zwiększa licznik prób i
    odsuwa termin ponowienia (backoff 2, 4, 8, ... minut, maks. godzina) —
    stąd UNIQUE INDEX na auto_id."""
    if not auto_id:
        return
    teraz = datetime.now()
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT proby FROM kolejka_sync WHERE auto_id=?", (auto_id,))
        w = c.fetchone()
        proby = int(w[0] or 0) + 1 if w else 1
        opoznienie = min(2 ** proby, MAKS_BACKOFF_MINUT_SYNC)
        nastepna = (teraz + timedelta(minutes=opoznienie)).strftime("%Y-%m-%d %H:%M:%S")
        if w:
            conn.execute(
                "UPDATE kolejka_sync SET proby=?, ostatnia_proba=?, nastepna_proba=?, ostatni_blad=? WHERE auto_id=?",
                (proby, teraz.strftime("%Y-%m-%d %H:%M:%S"), nastepna, (blad or "")[:300], auto_id)
            )
        else:
            conn.execute(
                "INSERT INTO kolejka_sync (auto_id, powod, proby, ostatnia_proba, nastepna_proba, ostatni_blad) "
                "VALUES (?,?,?,?,?,?)",
                (auto_id, powod or "", proby, teraz.strftime("%Y-%m-%d %H:%M:%S"), nastepna, (blad or "")[:300])
            )

def usun_z_kolejki_sync(auto_id):
    if not auto_id:
        return
    with polacz_baze() as conn:
        conn.execute("DELETE FROM kolejka_sync WHERE auto_id=?", (auto_id,))

def pobierz_kolejke_sync(limit=5, tylko_wymagalne=True):
    """Zwraca [(auto_id, powod, proby)] zaległych synchronizacji. Domyślnie tylko
    te, których czas ponowienia (nastepna_proba) już minął — format ISO, żeby
    porównanie tekstowe było poprawne chronologicznie."""
    teraz = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with polacz_baze() as conn:
        c = conn.cursor()
        if tylko_wymagalne:
            c.execute(
                "SELECT auto_id, powod, proby FROM kolejka_sync "
                "WHERE nastepna_proba IS NULL OR nastepna_proba <= ? "
                "ORDER BY nastepna_proba LIMIT ?", (teraz, limit)
            )
        else:
            c.execute("SELECT auto_id, powod, proby FROM kolejka_sync ORDER BY nastepna_proba LIMIT ?", (limit,))
        return [(r[0], r[1], int(r[2] or 0)) for r in c.fetchall()]

def liczba_oczekujacych_synchronizacji():
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM kolejka_sync")
        return int((c.fetchone() or [0])[0])

def czy_auto_oczekuje_synchronizacji(auto_id):
    """Czy KONKRETNY pojazd ma niewysłane zmiany czekające w kolejce. Używane
    przez wskaźnik przy nazwie pojazdu na ekranie głównym — do tej pory ten stan
    dało się zobaczyć dopiero po wejściu w ekran Współdzielenia."""
    if not auto_id:
        return False
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM kolejka_sync WHERE auto_id=?", (auto_id,))
        return int((c.fetchone() or [0])[0]) > 0

def opis_oczekujacej_synchronizacji():
    """Krótki tekst do wyświetlenia pod przyciskiem synchronizacji — albo pusty
    string, jeśli nic nie czeka w kolejce."""
    ile = liczba_oczekujacych_synchronizacji()
    if not ile:
        return ""
    if ile == 1:
        return "1 pojazd czeka na wysłanie zmian"
    return f"{ile} pojazdy czekają na wysłanie zmian"

# Same podpisy — ikony dobiera warstwa UI (utils.IKONY_KOKPITU), bo db.py
# celowo nie zna Fleta (korzysta z niego też eksport PDF i synchronizacja).
KOKPIT_WIDGETY = {
    "koszt_miesiac": "Koszt w tym miesiącu",
    "termin": "Najbliższy termin",
    "wykres": "Wykres wydatków (6 mies.)",
    "koszt_km": "Koszt eksploatacji / km",
    "spalanie": "Średnie spalanie",
    "przebieg_dzienny": "Średni przebieg dzienny",
    "ostatnia_aktywnosc": "Ostatnia aktywność",
    "kondycja": "Kondycja pojazdu",
    "zasieg_ev": "Realny zasięg na prądzie",
    "obserwacja": "Obserwacja dnia",
    "budzet": "Budżet",
    "zasieg_bak": "Zasięg na baku",
    "prognoza_rok": "Prognoza roczna",
}
KOKPIT_WIDGETY_DOMYSLNE = ["koszt_miesiac", "termin", "wykres"]

# Kokpit ustawia się osobno dla każdego pojazdu — auto służbowe i prywatne
# rzadko potrzebują tych samych kafelków. Klucz per auto to "kokpit_widgety_<id>";
# dopóki go nie ma, pojazd DZIEDZICZY wspólny układ spod "kokpit_widgety".
# Dzięki temu aktualizacja nie ruszyła nikomu kokpitu, a auto bez własnego
# układu podąża za zmianami wspólnego.
def _klucz_kokpitu(auto_id=None):
    return f"kokpit_widgety_{int(auto_id)}" if auto_id else "kokpit_widgety"

def czy_kokpit_wlasny(auto_id):
    """Czy pojazd ma WŁASNY układ kokpitu, czy dziedziczy wspólny."""
    return bool(auto_id) and pobierz_ustawienie(_klucz_kokpitu(auto_id)) is not None

def przywroc_kokpit_wspolny(auto_id):
    """Odpina pojazd od własnego układu — od tej chwili znowu dziedziczy wspólny."""
    if auto_id:
        usun_ustawienie(_klucz_kokpitu(auto_id))

def _odczytaj_kolejnosc_kokpitu(zapisane):
    kolejnosc, widziane = [], set()
    for w in zapisane.split(","):
        w = w.strip()
        if w in KOKPIT_WIDGETY and w not in widziane:
            widziane.add(w)
            kolejnosc.append(w)
    return kolejnosc

def pobierz_widgety_kokpitu(auto_id=None):
    """Zwraca listę ID widżetów kokpitu wybranych przez użytkownika (patrz
    MainView._buduj_kokpit) — W KOLEJNOŚCI, W JAKIEJ ZOSTAŁY ZAPISANE, bo tę
    kolejność użytkownik ustawia sam, przeciągając kafelki w trybie edycji
    kokpitu. Najpierw szuka układu WŁASNEGO dla pojazdu, potem wspólnego, a na
    końcu wraca do trzech podstawowych widżetów."""
    zapisane = pobierz_ustawienie(_klucz_kokpitu(auto_id)) if auto_id else None
    if zapisane is None:
        zapisane = pobierz_ustawienie("kokpit_widgety")
    if zapisane is None:
        return list(KOKPIT_WIDGETY_DOMYSLNE)
    return _odczytaj_kolejnosc_kokpitu(zapisane)

def zapisz_widgety_kokpitu(lista_id, auto_id=None):
    """Zapisuje ZESTAW oraz KOLEJNOŚĆ widżetów kokpitu — lista wchodzi tu już
    ułożona tak, jak ma wyglądać karuzela. Duplikaty i nieznane ID odpadają.
    Z auto_id zapis odpina pojazd od wspólnego układu; bez niego zmienia układ
    wspólny (i tym samym wszystkie auta, które nadal go dziedziczą)."""
    poprawne, widziane = [], set()
    for w in lista_id:
        if w in KOKPIT_WIDGETY and w not in widziane:
            widziane.add(w)
            poprawne.append(w)
    zapisz_ustawienie(_klucz_kokpitu(auto_id), ",".join(poprawne))

def scal_widgety_kokpitu(zaznaczone, auto_id=None):
    """Łączy nowy ZESTAW włączonych widżetów (np. z checkboxów w Ustawieniach)
    z już zapisaną KOLEJNOŚCIĄ: to, co użytkownik ułożył, zostaje na swoim
    miejscu, a świeżo włączone pozycje dopisują się na końcu (w kolejności
    KOKPIT_WIDGETY). Dzięki temu zaznaczenie checkboxa nie kasuje układu."""
    zaznaczone = set(zaznaczone)
    wynik = [w for w in pobierz_widgety_kokpitu(auto_id) if w in zaznaczone]
    wynik += [w for w in KOKPIT_WIDGETY if w in zaznaczone and w not in wynik]
    return wynik

# Ustawienia przywiązane do KONKRETNEGO pojazdu — przenoszone razem z nim do
# kosza i z powrotem (ID po przywróceniu może się zmienić, patrz
# przywroc_auto_z_kosza), żeby nie zostawały w bazie jako sieroty.
USTAWIENIA_PER_POJAZD = [_klucz_kokpitu]

def _pobierz_ustawienia_pojazdu(auto_id):
    dane = {}
    for buduj_klucz in USTAWIENIA_PER_POJAZD:
        klucz = buduj_klucz(auto_id)
        wartosc = pobierz_ustawienie(klucz)
        if wartosc is not None:
            dane[buduj_klucz.__name__] = wartosc
    return dane

def _usun_ustawienia_pojazdu(auto_id):
    for buduj_klucz in USTAWIENIA_PER_POJAZD:
        usun_ustawienie(buduj_klucz(auto_id))

def _przywroc_ustawienia_pojazdu(auto_id, dane):
    for buduj_klucz in USTAWIENIA_PER_POJAZD:
        wartosc = (dane or {}).get(buduj_klucz.__name__)
        if wartosc is not None:
            zapisz_ustawienie(buduj_klucz(auto_id), wartosc)

def _sparsuj_datetime(tekst):
    """Parsuje string w formacie 'DD.MM.YYYY' lub 'DD.MM.YYYY HH:MM' na obiekt
    datetime — pomocnicze dla pobierz_ostatnia_aktywnosc(), żeby móc sortować
    na wspólnej osi dodania (bez godziny — nigdy nie była zapisywana) i edycje
    (z dokładną godziną, patrz data_modyfikacji)."""
    if not tekst:
        return None
    for wzorzec in ("%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return datetime.strptime(str(tekst).strip(), wzorzec)
        except ValueError:
            continue
    return None

def pobierz_ostatnia_aktywnosc(auto_id, limit=5):
    """Zwraca listę ostatnich zdarzeń (dodań i edycji) z tankowań, serwisu,
    wizyt i innych kosztów — dla widżetu 'Ostatnia aktywność' w kokpicie
    (patrz MainView._buduj_kokpit). Każde zdarzenie to krotka:
    (opis, kto, kiedy_tekst, kiedy_sort, ikona, trasa). Dodanie i edycja tego
    samego wpisu mogą pojawić się jako dwa osobne zdarzenia.
    `ikona` to KLUCZ ("tankowanie" / "serwis" / "wizyta" / "inny_koszt"), który
    warstwa UI tłumaczy na ft.Icons przez utils.IKONY_AKTYWNOSCI."""
    if not auto_id:
        return []

    zdarzenia = []

    def _dodaj(dana_data, dodane_przez, zmodyfikowane_przez, data_modyfikacji, opis, ikona, trasa):
        if dodane_przez:
            kiedy_sort = _sparsuj_datetime(dana_data)
            if kiedy_sort:
                zdarzenia.append((f"Dodano: {opis}", dodane_przez, str(dana_data), kiedy_sort, ikona, trasa))
        if zmodyfikowane_przez and data_modyfikacji:
            kiedy_sort = _sparsuj_datetime(data_modyfikacji)
            if kiedy_sort:
                zdarzenia.append((f"Edytowano: {opis}", zmodyfikowane_przez, str(data_modyfikacji), kiedy_sort, ikona, trasa))

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute(
            "SELECT id, data, stacja, dodane_przez, zmodyfikowane_przez, data_modyfikacji "
            "FROM tankowania WHERE auto_id=?", (auto_id,)
        )
        for r in c.fetchall():
            opis = "Tankowanie" + (f" • {r['stacja']}" if r["stacja"] else "")
            _dodaj(r["data"], r["dodane_przez"], r["zmodyfikowane_przez"], r["data_modyfikacji"],
                   opis, "tankowanie", f"/tankowanie/edytuj/{r['id']}")

        c.execute(
            "SELECT h.id, h.data, z.nazwa, h.dodane_przez, h.zmodyfikowane_przez, h.data_modyfikacji "
            "FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE z.auto_id=? AND h.wizyta_id IS NULL", (auto_id,)
        )
        for r in c.fetchall():
            _dodaj(r["data"], r["dodane_przez"], r["zmodyfikowane_przez"], r["data_modyfikacji"],
                   str(r["nazwa"]), "serwis", f"/wpis/edytuj/{r['id']}")

        c.execute(
            "SELECT id, data, wykonawca, dodane_przez, zmodyfikowane_przez, data_modyfikacji "
            "FROM wizyty WHERE auto_id=?", (auto_id,)
        )
        for r in c.fetchall():
            opis = "Wizyta w warsztacie" + (f" • {r['wykonawca']}" if r["wykonawca"] else "")
            _dodaj(r["data"], r["dodane_przez"], r["zmodyfikowane_przez"], r["data_modyfikacji"],
                   opis, "wizyta", f"/wizyty/edytuj/{r['id']}")

        c.execute(
            "SELECT id, data, nazwa, dodane_przez, zmodyfikowane_przez, data_modyfikacji "
            "FROM inne_koszty WHERE auto_id=?", (auto_id,)
        )
        for r in c.fetchall():
            _dodaj(r["data"], r["dodane_przez"], r["zmodyfikowane_przez"], r["data_modyfikacji"],
                   str(r["nazwa"] or "Inny koszt"), "inny_koszt", f"/inne/edytuj/{r['id']}")

    zdarzenia.sort(key=lambda z: z[3], reverse=True)
    return zdarzenia[:limit]

LICZBA_ZAKLADEK_GLOWNYCH = 4   # Serwis, Paliwo, Inne, Statystyki

def zapamietaj_ostatnia_pozycje(auto_id, zakladka):
    """Zapamiętuje, na czym użytkownik skończył — pojazd i zakładkę główną.
    Wywoływane przy każdej nawigacji (patrz main.trasa_zmieniona), ale tylko
    wtedy, gdy coś się faktycznie zmieniło."""
    if auto_id:
        zapisz_ustawienie("ostatni_pojazd", str(int(auto_id)))
    zapisz_ustawienie("ostatnia_zakladka", str(int(zakladka or 0)))

def pobierz_ostatnia_zakladke():
    try:
        z = int(pobierz_ustawienie("ostatnia_zakladka", "0") or 0)
    except (TypeError, ValueError):
        return 0
    return z if 0 <= z < LICZBA_ZAKLADEK_GLOWNYCH else 0

def pobierz_ostatni_pojazd():
    try:
        return int(pobierz_ustawienie("ostatni_pojazd", "") or 0) or None
    except (TypeError, ValueError):
        return None

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
    # Brak dopasowania to albo świeży start aplikacji, albo zniknięcie
    # dotychczasowego auta. W pierwszym przypadku wracamy tam, gdzie użytkownik
    # skończył ostatnim razem — pierwsze auto alfabetycznie zostaje dopiero
    # awaryjnym wyborem, gdy zapamiętanego pojazdu już nie ma.
    ostatni = pobierz_ostatni_pojazd()
    if ostatni:
        for a_id, a_nazwa in auta:
            if a_id == ostatni:
                state.auto_id = a_id
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

def sprawdz_czy_tankowanie_duplikat(auto_id, data_str, przebieg, kwota, wyklucz_id=None):
    """Zwraca ostrzeżenie (str), jeśli dla tego pojazdu istnieje już tankowanie
    z DOKŁADNIE tą samą datą, przebiegiem i kwotą — częsty efekt podwójnego
    zapisu tego samego wpisu (np. dubel kliknięcia „Zapisz”). Analogicznie do
    sprawdz_czy_przebieg_podejrzany: nie blokuje zapisu samodzielnie, tylko
    sygnalizuje możliwy duplikat do potwierdzenia przez użytkownika."""
    if not auto_id or not data_str:
        return None

    with polacz_baze() as conn:
        c = conn.cursor()
        wyklucz_sql = " AND id != ?" if wyklucz_id else ""
        params = [auto_id, data_str, int(przebieg or 0), float(kwota or 0)]
        if wyklucz_id:
            params.append(wyklucz_id)
        c.execute(
            f"SELECT id FROM tankowania WHERE auto_id=? AND data=? AND przebieg=? AND kwota=?{wyklucz_sql}",
            params
        )
        istnieje = c.fetchone()

    if istnieje:
        import utils
        return (
            f"Uwaga: masz już zapisane tankowanie z {data_str}, przebiegiem "
            f"{utils.formatuj_liczba(przebieg, 0)} km i kwotą {utils.formatuj_liczba(kwota, 2)} "
            f"{pobierz_walute()}. Czy to nie duplikat?"
        )
    return None

def sprawdz_czy_koszt_duplikat(auto_id, data_str, nazwa, kwota, wyklucz_id=None):
    """Zwraca ostrzeżenie (str), jeśli dla tego pojazdu istnieje już inny koszt
    z DOKŁADNIE tą samą datą, opisem i kwotą — częsty efekt podwójnego zapisu
    tego samego wpisu (np. dubel kliknięcia „Zapisz”). Analogicznie do
    sprawdz_czy_tankowanie_duplikat: nie blokuje zapisu samodzielnie, tylko
    sygnalizuje możliwy duplikat do potwierdzenia przez użytkownika."""
    if not auto_id or not data_str:
        return None

    with polacz_baze() as conn:
        c = conn.cursor()
        wyklucz_sql = " AND id != ?" if wyklucz_id else ""
        params = [auto_id, data_str, (nazwa or "").strip(), float(kwota or 0)]
        if wyklucz_id:
            params.append(wyklucz_id)
        c.execute(
            f"SELECT id FROM inne_koszty WHERE auto_id=? AND data=? AND nazwa=? AND kwota=?{wyklucz_sql}",
            params
        )
        istnieje = c.fetchone()

    if istnieje:
        import utils
        return (
            f"Uwaga: masz już zapisany koszt „{nazwa}” z {data_str} na kwotę "
            f"{utils.formatuj_liczba(kwota, 2)} {pobierz_walute()}. Czy to nie duplikat?"
        )
    return None

def oblicz_sredni_dzienny_przebieg(auto_id, min_dni=7):
    """Średni przebieg dzienny liczony na podstawie WSZYSTKICH źródeł przebiegu —
    dokładnie tych samych, których używa pobierz_historie_przebiegu() (wykres
    przebiegu w paszporcie PDF): tankowania, wizyty, pojedyncze wpisy historii
    i ręczne odczyty. Wcześniej ta funkcja liczyła TYLKO z tankowań i odczytów
    ręcznych — ktoś logujący wyłącznie wizyty serwisowe (bez tankowań w
    aplikacji) zawsze dostawał None, a przez to znikały mu prognozy terminów
    ("Zostanie ok. X dni") w powiadomieniach i na kartach podzespołów."""
    if not auto_id:
        return None

    punkty = pobierz_historie_przebiegu(auto_id)
    if len(punkty) < 2:
        return None

    pierwsza_data = parsuj_date(punkty[0][0])
    ostatnia_data = parsuj_date(punkty[-1][0])
    pierwszy_przebieg = punkty[0][1]
    ostatni_przebieg = punkty[-1][1]

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

def dodaj_odczyt_przebiegu(auto_id, przebieg, data_str=None, notatka=None):
    """Zapisuje szybki, ręczny odczyt licznika (np. z deski rozdzielczej) w osobnym
    dzienniku — bez tworzenia sztucznego tankowania czy wpisu serwisowego tylko po
    to, by odświeżyć aktualny przebieg. Jeśli w danym dniu istnieje już odczyt,
    aktualizuje go zamiast duplikować. Zwraca True, jeśli nadpisano istniejący
    wpis z tego dnia, False, jeśli dodano zupełnie nowy."""
    if not auto_id or not przebieg or przebieg <= 0:
        return False
    if not data_str:
        data_str = datetime.now().strftime("%d.%m.%Y")

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT id FROM odczyty_przebiegu WHERE auto_id=? AND data=?", (auto_id, data_str))
        w = c.fetchone()
        if w:
            conn.execute("UPDATE odczyty_przebiegu SET przebieg=? WHERE id=?", (przebieg, w[0]))
            rekord_id, nadpisano = w[0], True
        else:
            kursor = conn.execute("INSERT INTO odczyty_przebiegu (auto_id, data, przebieg) VALUES (?,?,?)", (auto_id, data_str, przebieg))
            rekord_id, nadpisano = kursor.lastrowid, False

    # Notatka POZA transakcją powyżej — zapisz_notatke otwiera własne połączenie
    # i w środku otwartej transakcji potrafi zakleszczyć bazę (ten sam powód, co
    # przy nagrobkach w formularzu wpisu).
    # Pustej notatki celowo NIE zapisujemy: to ścieżka DODAWANIA, a przy trafieniu
    # w istniejący odczyt z tego samego dnia wyczyściłaby notatkę, której formularz
    # dodawania nawet nie pokazał. Kasowanie notatki idzie osobną drogą — przez
    # edycję odczytu albo pozycję „Notatka” w jego menu.
    if przytnij_notatke(notatka):
        zapisz_notatke("odczyty_przebiegu", rekord_id, notatka)
    return nadpisano

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

def pobierz_powiadomienia(auto_id, prog_km=None, prog_dni=None, pomin_wyciszone=True):
    """Każde powiadomienie niesie 'klucz' — stabilny identyfikator (typ + ID
    źródła), po którym rozpoznajemy je między odświeżeniami. Treść się do tego
    nie nadaje, bo opis zmienia się z każdym dniem („Zostało 12 dni”).
    pomin_wyciszone=False zwraca komplet, łącznie z odłożonymi — potrzebne
    panelowi powiadomień do sekcji „Odkładane”."""
    if not auto_id:
        return []

    if prog_km is None: prog_km = pobierz_prog_km()
    prog_dni_wymuszony = prog_dni is not None
    if prog_dni is None: prog_dni = pobierz_prog_dni()

    wyniki = []
    dzis = datetime.now().date()
    aktualny_przebieg = pobierz_aktualny_przebieg(auto_id) or 0
    sredni_dzienny_przebieg = oblicz_sredni_dzienny_przebieg(auto_id)

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute(
            "SELECT id, nazwa, data, przebieg, interwal_km, interwal_miesiace, prog_km, prog_dni FROM zadania "
            "WHERE auto_id=? AND (interwal_km IS NOT NULL OR interwal_miesiace IS NOT NULL)",
            (auto_id,)
        )
        for z in c.fetchall():
            powody, status_zadania = [], None
            prog_km_z = int(z["prog_km"]) if z["prog_km"] else prog_km
            prog_dni_z = int(z["prog_dni"]) if z["prog_dni"] else prog_dni

            if z["interwal_km"] and z["przebieg"] and aktualny_przebieg:
                zost_km = (int(z["przebieg"]) + int(z["interwal_km"])) - aktualny_przebieg
                if zost_km <= prog_km_z:
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
                    if zost_dni <= prog_dni_z:
                        s = "przeterminowane" if zost_dni < 0 else "pilne"
                        powody.append(f"Przekroczono o {abs(zost_dni)} dni" if zost_dni < 0 else f"Zostało {zost_dni} dni")
                        if status_zadania != "przeterminowane":
                            status_zadania = s

            if powody:
                wyniki.append({
                    "typ": "podzespol", "tytul": z["nazwa"], "opis": " • ".join(powody),
                    "status": status_zadania, "trasa": f"/zadanie/edytuj/{z['id']}",
                    "klucz": f"podzespol:{z['id']}",
                })

        kolumny_terminow = ", ".join(kol for _, kol, _ in TERMINY_DOKUMENTOW)
        c.execute(
            f"SELECT {kolumny_terminow}, gwarancja_przebieg FROM samochody WHERE id=?",
            (auto_id,)
        )
        w = c.fetchone()
        if w:
            # Każdy termin ma własny próg wyprzedzenia (Ustawienia → „Progi
            # powiadomień”); nieruszony termin dziedziczy wspólny prog_dni.
            # prog_dni podany jawnie w wywołaniu nadal wygrywa ze wszystkim —
            # służy do podglądu „co by było, gdyby” bez ruszania ustawień.
            for klucz, kolumna, etykieta in TERMINY_DOKUMENTOW:
                txt = w[kolumna]
                if not txt:
                    continue
                d_w = parsuj_date(txt)
                if d_w == datetime.min.date():
                    continue
                prog_terminu = prog_dni if prog_dni_wymuszony else pobierz_prog_dni_dokumentu(klucz)
                zost_dni = (d_w - dzis).days
                if zost_dni <= prog_terminu:
                    s = "przeterminowane" if zost_dni < 0 else "pilne"
                    opis = f"Przekroczono o {abs(zost_dni)} dni" if zost_dni < 0 else f"Zostało {zost_dni} dni"
                    wyniki.append({
                        "typ": "dokument", "tytul": etykieta, "opis": opis,
                        "status": s, "trasa": f"/auto/edytuj/{auto_id}",
                        "klucz": f"dokument:{klucz}",
                    })

            # Gwarancja ma dwa niezależne limity — datę i przebieg. Kilometry
            # potrafią się skończyć długo przed datą, więc liczymy je osobno.
            limit_km = w["gwarancja_przebieg"]
            if limit_km:
                zost_km_gw = int(limit_km) - aktualny_przebieg
                if zost_km_gw <= prog_km:
                    s = "przeterminowane" if zost_km_gw < 0 else "pilne"
                    opis = (f"Przekroczono limit o {abs(zost_km_gw)} km" if zost_km_gw < 0
                            else f"Zostało {zost_km_gw} km do końca gwarancji")
                    wyniki.append({
                        "typ": "dokument", "tytul": "Gwarancja (limit km)", "opis": opis,
                        "status": s, "trasa": f"/auto/edytuj/{auto_id}",
                        "klucz": "dokument:gwarancja_km",
                    })
        # Wydatki cykliczne (raty, abonamenty, ubezpieczenia ratalne) — termin
        # liczy się jak dla dokumentów, ale akcją jest "Zapłacone", nie przejście
        # do formularza (stąd "trasa": None).
        c.execute(
            "SELECT id, nazwa, nastepna_data, okres_dni, czy_koszt FROM wydatki_cykliczne WHERE auto_id=?",
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
                    "czy_koszt": bool(wc["czy_koszt"]),
                    "klucz": f"cykliczny:{wc['id']}",
                })

        # Niski stan magazynu (części i płyny) — indywidualny próg per pozycja,
        # z fallbackiem na wspólną wartość domyślną dla starszych wpisów bez własnego progu.
        import utils
        c.execute(
            "SELECT id, nazwa, ilosc, jednostka, prog_ostrzezenia FROM magazyn_czesci WHERE auto_id=?",
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
                    "klucz": f"magazyn:{m['id']}",
                })

    kolejnosc = {"przeterminowane": 0, "pilne": 1}

    wyniki.sort(key=lambda w: kolejnosc.get(w["status"], 2))

    if pomin_wyciszone:
        wyciszone = pobierz_wyciszone_klucze(auto_id)
        wyniki = [w for w in wyniki if w.get("klucz") not in wyciszone]
    return wyniki

# ============================================================================
#  ODKŁADANIE POWIADOMIEŃ („drzemka”)
# ============================================================================
# „Wiem o przeglądzie, zrobię go za dwa tygodnie” — wyciszenie JEDNEGO
# przypomnienia na wybraną liczbę dni, bez oznaczania czegokolwiek jako wykonane
# i bez ruszania samego terminu. Po upływie dni powiadomienie wraca samo.

DNI_ODLOZENIA_OPCJE = [3, 7, 14, 30]


def odloz_powiadomienie(auto_id, klucz, dni, tytul=None):
    """Wycisza powiadomienie o danym kluczu na `dni` dni. Ponowne odłożenie tego
    samego powiadomienia nadpisuje termin (stąd UNIQUE na auto_id+klucz)."""
    if not auto_id or not klucz:
        return None
    try:
        dni = max(1, int(dni))
    except (TypeError, ValueError):
        dni = 7
    do_dnia = (datetime.now().date() + timedelta(days=dni)).strftime("%Y-%m-%d")
    with polacz_baze() as conn:
        conn.execute(
            "INSERT INTO wyciszone_powiadomienia (auto_id, klucz, do_dnia, tytul, utworzono) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(auto_id, klucz) DO UPDATE SET do_dnia=excluded.do_dnia, "
            "tytul=excluded.tytul, utworzono=excluded.utworzono",
            (auto_id, klucz, do_dnia, tytul, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
    return do_dnia


def przywroc_powiadomienie(auto_id, klucz):
    """Zdejmuje drzemkę — powiadomienie wraca na listę od razu."""
    if not auto_id or not klucz:
        return
    with polacz_baze() as conn:
        conn.execute("DELETE FROM wyciszone_powiadomienia WHERE auto_id=? AND klucz=?", (auto_id, klucz))


def _posprzataj_wygasle_wyciszenia(conn, auto_id):
    """Kasuje drzemki, których termin już minął — dzięki temu tabela nie rośnie,
    a powiadomienie wraca bez żadnej dodatkowej logiki."""
    conn.execute(
        "DELETE FROM wyciszone_powiadomienia WHERE auto_id=? AND do_dnia <= ?",
        (auto_id, datetime.now().date().strftime("%Y-%m-%d"))
    )


def pobierz_wyciszone_klucze(auto_id):
    """Zbiór kluczy powiadomień AKTUALNIE odłożonych (drzemka jeszcze trwa)."""
    if not auto_id:
        return set()
    with polacz_baze() as conn:
        c = conn.cursor()
        try:
            _posprzataj_wygasle_wyciszenia(conn, auto_id)
            c.execute("SELECT klucz FROM wyciszone_powiadomienia WHERE auto_id=?", (auto_id,))
        except sqlite3.OperationalError:
            return set()
        return {r[0] for r in c.fetchall()}


def pobierz_odlozone_powiadomienia(auto_id):
    """Lista odłożonych powiadomień do sekcji „Odkładane” w panelu:
    [{klucz, tytul, do_dnia, data_tekst, dni_do_powrotu}] posortowana po dacie
    powrotu. Tytuł bierzemy z żywego powiadomienia, jeśli nadal istnieje —
    a z zapamiętanego, gdy powód wyciszenia zdążył sam zniknąć."""
    if not auto_id:
        return []

    with polacz_baze() as conn:
        c = conn.cursor()
        try:
            _posprzataj_wygasle_wyciszenia(conn, auto_id)
            c.execute(
                "SELECT klucz, do_dnia, tytul FROM wyciszone_powiadomienia "
                "WHERE auto_id=? ORDER BY do_dnia",
                (auto_id,)
            )
        except sqlite3.OperationalError:
            return []
        wiersze = c.fetchall()

    if not wiersze:
        return []

    zywe = {p.get("klucz"): p for p in pobierz_powiadomienia(auto_id, pomin_wyciszone=False)}
    dzis = datetime.now().date()
    pozycje = []
    for klucz, do_dnia, tytul in wiersze:
        try:
            data_obj = datetime.strptime(str(do_dnia), "%Y-%m-%d").date()
        except (TypeError, ValueError):
            continue
        zrodlo = zywe.get(klucz)
        pozycje.append({
            "klucz": klucz,
            "tytul": (zrodlo or {}).get("tytul") or tytul or "Powiadomienie",
            "opis": (zrodlo or {}).get("opis") or "",
            "status": (zrodlo or {}).get("status"),
            "trasa": (zrodlo or {}).get("trasa"),
            "do_dnia": do_dnia,
            "data_tekst": data_obj.strftime("%d.%m.%Y"),
            "dni_do_powrotu": max(0, (data_obj - dzis).days),
            "nadal_aktualne": zrodlo is not None,
        })
    return pozycje


# Ile punktów kondycji kosztuje każdy powód. Trzymane w jednym miejscu, bo te
# same wartości pokazuje teraz rozpiska („−15 pkt: przegląd przeterminowany”).
KARY_KONDYCJI = {
    "podzespol_przeterminowany": 15,
    "podzespol_pilny": 8,
    "bieznik_krytyczny": 20,   # poniżej 1,6 mm — minimum prawne
    "bieznik_niski": 10,       # poniżej 3 mm — zalecana wymiana
}


def pobierz_rozbicie_kondycji(auto_id):
    """Kondycja pojazdu wraz z ROZPISKĄ tego, co ją obniżyło. Sam wynik 0-100 nic
    nie podpowiada; lista powodów mówi wprost, co poprawić najpierw.

    Zwraca {"wynik": int|None, "powody": [{opis, szczegol, punkty, trasa, typ}]}
    posortowaną malejąco po odjętych punktach. Celowo NIE uwzględnia stanu
    magazynu, dokumentów (OC/przegląd) ani wydatków cyklicznych — kondycja
    dotyczy stanu technicznego auta, nie papierologii.

    Powiadomienia bierzemy z pomin_wyciszone=False: odłożenie przypomnienia
    („zrobię za dwa tygodnie”) nie naprawia auta, więc nie może podbijać wyniku.
    """
    if not auto_id:
        return {"wynik": None, "powody": []}

    wynik = 100
    powody = []

    for p in pobierz_powiadomienia(auto_id, pomin_wyciszone=False):
        # Ignorujemy wszystko, co nie jest bezpośrednio powiązane z podzespołami auta
        if p["typ"] != "podzespol":
            continue

        if p["status"] == "przeterminowane":
            kara = KARY_KONDYCJI["podzespol_przeterminowany"]
            etykieta = "przeterminowany"
        elif p["status"] == "pilne":
            kara = KARY_KONDYCJI["podzespol_pilny"]
            etykieta = "termin się zbliża"
        else:
            continue

        wynik -= kara
        powody.append({
            "typ": "podzespol",
            "opis": f"{p['tytul']} — {etykieta}",
            "szczegol": p.get("opis") or "",
            "punkty": kara,
            "trasa": p.get("trasa"),
        })

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT sezon, rozmiar, glebokosc_bieznika FROM zestawy_opon "
            "WHERE auto_id=? AND zamontowane=1",
            (auto_id,)
        )
        for r in c.fetchall():
            gl = r["glebokosc_bieznika"]
            if gl is None or str(gl).strip() == "":
                continue
            try:
                g = float(gl)
            except (TypeError, ValueError):
                continue

            if g < 1.6:
                kara = KARY_KONDYCJI["bieznik_krytyczny"]
                etykieta = "bieżnik poniżej minimum prawnego (1,6 mm)"
            elif g < 3.0:
                kara = KARY_KONDYCJI["bieznik_niski"]
                etykieta = "bieżnik poniżej 3 mm — zalecana wymiana"
            else:
                continue

            wynik -= kara
            nazwa_opon = f"Opony {r['sezon']}" if r["sezon"] else "Zamontowane opony"
            powody.append({
                "typ": "opony",
                "opis": f"{nazwa_opon} — {etykieta}",
                "szczegol": f"{formatuj_liczba_eksport(g, 1)} mm"
                            + (f" • {r['rozmiar']}" if r["rozmiar"] else ""),
                "punkty": kara,
                "trasa": "/magazyn",
            })

    powody.sort(key=lambda p: -p["punkty"])
    return {"wynik": max(0, min(100, int(round(wynik)))), "powody": powody}


def oblicz_kondycje_pojazdu(auto_id):
    """Sam wskaźnik 0-100 (100 = wzorowo) — cienkie opakowanie na
    pobierz_rozbicie_kondycji, dla miejsc, którym wystarczy liczba."""
    return pobierz_rozbicie_kondycji(auto_id)["wynik"]

def pobierz_serie_spalania(auto_id, limit=12, rodzaj=None):
    """Spalanie liczone ODCINKAMI między kolejnymi tankowaniami „do pełna” —
    dokładnie ta sama metoda, co wykres trendu w Statystykach, tylko bez
    uśredniania po miesiącach (jeden punkt = jeden odcinek między pełnymi
    bakami). Używane przez sparkline przy kafelku „Śr. spalanie” w kokpicie.
    Zwraca listę (data_tankowania_konczacego_odcinek, l/100km) chronologicznie,
    przyciętą do ostatnich `limit` punktów (limit=None → wszystkie).

    `rodzaj` zawęża liczenie do jednego źródła energii. Przy hybrydzie plug-in
    to konieczność: mieszanie litrów z kilowatogodzinami w jednym odcinku dałoby
    liczbę bez żadnego znaczenia. Brak `rodzaju` = wszystkie wpisy (auta
    jednoźródłowe, gdzie nie ma czego mieszać)."""
    if not auto_id:
        return []

    with polacz_baze() as conn:
        c = conn.cursor()
        if rodzaj:
            # COALESCE, bo wpisy sprzed migracji 33 mają rodzaj_energii NULL
            # — traktujemy je zgodnie z typem pojazdu, tak jak backfill.
            c.execute(
                "SELECT data, przebieg, litry, do_pelna FROM tankowania "
                "WHERE auto_id=? AND COALESCE(rodzaj_energii, ?) = ?",
                (auto_id, domyslny_rodzaj_energii(auto_id), rodzaj)
            )
        else:
            c.execute(
                "SELECT data, przebieg, litry, do_pelna FROM tankowania WHERE auto_id=?",
                (auto_id,)
            )
        wiersze = c.fetchall()

    # Sortujemy po dacie, a przy remisie po przebiegu — tak jak reszta aplikacji,
    # żeby dwa tankowania tego samego dnia nie dały ujemnego dystansu.
    tankowania = sorted(
        ((parsuj_date(r[0]), r[0], int(r[1] or 0), float(r[2] or 0), bool(r[3])) for r in wiersze),
        key=lambda t: (t[0], t[2])
    )

    pelne = [i for i, t in enumerate(tankowania) if t[4]]
    seria = []
    for a, b in zip(pelne, pelne[1:]):
        dystans = tankowania[b][2] - tankowania[a][2]
        litry = sum(tankowania[k][3] for k in range(a + 1, b + 1))
        if dystans > 0 and litry > 0:
            seria.append((tankowania[b][1], (litry / dystans) * 100))

    if limit and len(seria) > limit:
        return seria[-limit:]
    return seria

def pobierz_serie_dziennego_przebiegu(auto_id, limit=12, min_dni=7):
    """Średni przebieg dzienny w kolejnych odcinkach czasu — punkty do sparkline
    przy kafelku „Śr. dzienny” w kokpicie. Odcinki sklejamy tak, aby każdy miał
    co najmniej `min_dni` dni; bez tego dwa odczyty licznika z sąsiednich dni
    dawałyby skok w rodzaju „400 km/dzień” i wykres pokazywałby szum zamiast
    tempa jazdy. Zwraca [(data_konca_odcinka, km_na_dzien)] chronologicznie."""
    if not auto_id:
        return []

    punkty = pobierz_historie_przebiegu(auto_id)
    if len(punkty) < 2:
        return []

    seria = []
    baza_data = parsuj_date(punkty[0][0])
    baza_przebieg = punkty[0][1]

    for data_str, przebieg in punkty[1:]:
        d = parsuj_date(data_str)
        dni = (d - baza_data).days
        km = przebieg - baza_przebieg
        if dni < min_dni:
            continue                      # za krótki odcinek — zbieramy dalej
        if km > 0:
            seria.append((data_str, km / dni))
        baza_data, baza_przebieg = d, przebieg

    if limit and len(seria) > limit:
        return seria[-limit:]
    return seria

def pobierz_przebieg_miesieczny(auto_id, liczba_miesiecy=6):
    """Kilometry przejechane w kolejnych miesiącach — liczone z tych samych
    źródeł, co pobierz_historie_przebiegu(). Zwraca [(rok, miesiac, km)] w tej
    samej siatce miesięcy, co pobierz_koszty_miesieczne(), więc obie listy da
    się zestawić pozycja w pozycję. Miesiąc bez odczytu dostaje km = 0."""
    if not auto_id:
        return []

    punkty = pobierz_historie_przebiegu(auto_id)
    if len(punkty) < 2:
        return []

    # Najwyższy stan licznika zanotowany w danym miesiącu.
    wg_miesiaca = {}
    for data_str, przebieg in punkty:
        d = parsuj_date(data_str)
        klucz = (d.year, d.month)
        if klucz not in wg_miesiaca or przebieg > wg_miesiaca[klucz]:
            wg_miesiaca[klucz] = przebieg

    dzisiaj = datetime.now()
    klucze = []
    for i in range(liczba_miesiecy - 1, -1, -1):
        m, y = dzisiaj.month - i, dzisiaj.year
        while m <= 0:
            m += 12
            y -= 1
        klucze.append((y, m))

    def stan_na_koniec(klucz):
        """Ostatni znany stan licznika NIE PÓŹNIEJ niż koniec danego miesiąca —
        dzięki temu miesiąc bez odczytu nie generuje ujemnego dystansu."""
        wczesniejsze = [wg_miesiaca[k] for k in wg_miesiaca if k <= klucz]
        return max(wczesniejsze) if wczesniejsze else None

    wynik = []
    for y, m in klucze:
        poprz_m, poprz_y = (m - 1, y) if m > 1 else (12, y - 1)
        koniec = stan_na_koniec((y, m))
        poczatek = stan_na_koniec((poprz_y, poprz_m))
        km = (koniec - poczatek) if (koniec is not None and poczatek is not None) else 0
        wynik.append((y, m, max(0, km)))
    return wynik

def pobierz_serie_kosztu_km(auto_id, liczba_miesiecy=6):
    """Koszt eksploatacji na kilometr w kolejnych miesiącach — punkty do
    sparkline przy kafelku „Koszt / km”. Miesiące bez przejechanych kilometrów
    są pomijane (dzielenie przez zero, a i tak nic nie mówią o koszcie jazdy).
    Zwraca [(rok, miesiac, koszt_na_km)] chronologicznie."""
    if not auto_id:
        return []

    koszty = pobierz_koszty_miesieczne(auto_id, liczba_miesiecy)
    kilometry = pobierz_przebieg_miesieczny(auto_id, liczba_miesiecy)
    if not koszty or not kilometry:
        return []

    km_wg_klucza = {(y, m): km for y, m, km in kilometry}
    seria = []
    for rok, mies, suma in koszty:
        km = km_wg_klucza.get((rok, mies), 0)
        if km > 0:
            seria.append((rok, mies, suma / km))
    return seria

def pobierz_statystyki_energii(auto_id):
    """Zużycie i koszty rozbite NA KAŻDE ŹRÓDŁO ENERGII osobno.

    Przy hybrydzie plug-in jedna uśredniona liczba nie mówi nic sensownego —
    dopiero „6,1 l/100km na paliwie i 18,4 kWh/100km na prądzie” pozwala ocenić,
    ile daje ładowanie zamiast tankowania. Auta jednoźródłowe dostają jedną
    sekcję i wyglądają dokładnie jak dotąd.

    Zwraca listę słowników (w kolejności rodzajow_energii_pojazdu):
    {rodzaj, etykieta, jednostka, ilosc, koszt, liczba_wpisow, zuzycie,
     dystans, koszt_km, cena_jednostkowa, ceny_ladowania}
    gdzie 'zuzycie' jest w jednostce właściwej dla źródła (l/100km albo
    kWh/100km), a 'dystans' to suma odcinków między pełnymi tankowaniami TEGO
    źródła — czyli baza, na której zużycie faktycznie policzono.
    """
    if not auto_id:
        return []

    domyslny = domyslny_rodzaj_energii(auto_id)
    wyniki = []

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        for rodzaj in rodzaje_energii_pojazdu(auto_id):
            c.execute(
                "SELECT data, przebieg, litry, kwota, do_pelna, typ_ladowania FROM tankowania "
                "WHERE auto_id=? AND COALESCE(rodzaj_energii, ?) = ?",
                (auto_id, domyslny, rodzaj)
            )
            wiersze = c.fetchall()

            ilosc = sum(float(r["litry"] or 0) for r in wiersze)
            koszt = sum(float(r["kwota"] or 0) for r in wiersze)

            # Dystans i zużycie liczymy tą samą metodą, co pobierz_serie_spalania:
            # wyłącznie odcinki zamknięte dwoma tankowaniami „do pełna”.
            posortowane = sorted(
                ((parsuj_date(r["data"]), int(r["przebieg"] or 0), float(r["litry"] or 0), bool(r["do_pelna"]))
                 for r in wiersze),
                key=lambda t: (t[0], t[1])
            )
            pelne = [i for i, t in enumerate(posortowane) if t[3]]
            dystans_licz, ilosc_licz = 0.0, 0.0
            for a, b in zip(pelne, pelne[1:]):
                odcinek = posortowane[b][1] - posortowane[a][1]
                zuzyte = sum(posortowane[k][2] for k in range(a + 1, b + 1))
                if odcinek > 0 and zuzyte > 0:
                    dystans_licz += odcinek
                    ilosc_licz += zuzyte

            zuzycie = (ilosc_licz / dystans_licz * 100) if dystans_licz > 0 else 0.0
            koszt_km = (koszt / dystans_licz) if dystans_licz > 0 else 0.0

            # Średnia cena za jednostkę — dla prądu dodatkowo w rozbiciu AC/DC,
            # bo szybkie ładowanie na trasie potrafi być kilka razy droższe.
            cena_jednostkowa = (koszt / ilosc) if ilosc > 0 else 0.0
            ceny_ladowania = {}
            if rodzaj == ENERGIA_PRAD:
                for typ in TYPY_LADOWANIA:
                    pasujace = [r for r in wiersze if str(r["typ_ladowania"] or "").upper() == typ]
                    suma_kwh = sum(float(r["litry"] or 0) for r in pasujace)
                    suma_kosztu = sum(float(r["kwota"] or 0) for r in pasujace)
                    if suma_kwh > 0:
                        ceny_ladowania[typ] = {
                            "cena": suma_kosztu / suma_kwh,
                            "ilosc": suma_kwh,
                            "koszt": suma_kosztu,
                            "liczba": len(pasujace),
                        }

            etykiety = etykiety_energii(rodzaj)
            # Przy dwóch źródłach zużycie jest liczone po CAŁYM przebiegu (tak
            # samo podaje je WLTP dla plug-inów) — nie po kilometrach
            # przejechanych na tym jednym źródle, bo tych nie da się wydzielić.
            wyniki.append({
                "rodzaj": rodzaj,
                "etykieta": ETYKIETY_RODZAJU[rodzaj],
                "jednostka": etykiety["jednostka"],
                "etykiety": etykiety,
                "ilosc": ilosc,
                "koszt": koszt,
                "liczba_wpisow": len(wiersze),
                "zuzycie": zuzycie,
                "dystans": dystans_licz,
                "koszt_km": koszt_km,
                "cena_jednostkowa": cena_jednostkowa,
                "ceny_ladowania": ceny_ladowania,
                "laczony_cykl": len(rodzaje_energii_pojazdu(auto_id)) > 1,
            })

    return wyniki


def pobierz_udzial_energii(auto_id):
    """Jak rozkłada się WYDATEK na energię między paliwo a prąd — sens ma
    wyłącznie przy hybrydzie plug-in.

    Świadomie liczymy udział KOSZTU, a nie kilometrów. Mając wyłącznie licznik
    i ilości zatankowanej energii NIE DA SIĘ rozdzielić, ile kilometrów auto
    przejechało na prądzie, a ile na paliwie — obie strony dzielą ten sam
    przebieg. Udział kosztu jest policzalny, uczciwy i odpowiada na właściwe
    pytanie: ile realnie oszczędza ładowanie zamiast tankowania.
    """
    if not czy_pojazd_dwuzrodlowy(auto_id):
        return None
    statystyki = {s["rodzaj"]: s for s in pobierz_statystyki_energii(auto_id)}
    koszt_prad = statystyki.get(ENERGIA_PRAD, {}).get("koszt", 0.0)
    koszt_paliwo = statystyki.get(ENERGIA_PALIWO, {}).get("koszt", 0.0)
    razem = koszt_prad + koszt_paliwo
    if razem <= 0:
        return None
    return {
        "procent_prad": koszt_prad / razem * 100,
        "procent_paliwo": koszt_paliwo / razem * 100,
        "koszt_prad": koszt_prad,
        "koszt_paliwo": koszt_paliwo,
        "razem": razem,
    }


def pobierz_zasieg_ev(auto_id):
    """Szacowany REALNY zasięg na prądzie: pojemność baterii podzielona przez
    Twoje faktyczne zużycie. Katalogowy zasięg (WLTP) podajemy obok do porównania,
    bo w praktyce prawie zawsze jest wyższy od osiąganego.

    Zwraca None, gdy nie ma pojemności baterii albo policzonego zużycia."""
    if not auto_id:
        return None

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT pojemnosc_baterii, zasieg_ev, typ_paliwa FROM samochody WHERE id=?", (auto_id,))
        w = c.fetchone()
    if not w:
        return None

    typ = str(w["typ_paliwa"] or "")
    # WYŁĄCZNIE czysty elektryk. Przy hybrydzie plug-in „kWh/100km” liczy się po
    # CAŁYM przebiegu — także po kilometrach przejechanych na paliwie — więc
    # bateria podzielona przez tę wartość dałaby zasięg kilkukrotnie zawyżony.
    if typ not in TYPY_PALIWA_ELEKTRYCZNE:
        return None

    pojemnosc = _liczba_lub_none(w["pojemnosc_baterii"])
    deklarowany = _liczba_lub_none(w["zasieg_ev"])

    zuzycie = 0.0
    for s in pobierz_statystyki_energii(auto_id):
        if s["rodzaj"] == ENERGIA_PRAD:
            zuzycie = s["zuzycie"]
            break

    szacowany = None
    if pojemnosc and zuzycie > 0:
        # kWh / (kWh/100km) * 100 = km
        szacowany = pojemnosc / zuzycie * 100

    if szacowany is None and deklarowany is None:
        return None

    return {
        "pojemnosc": pojemnosc,
        "deklarowany": deklarowany,
        "szacowany": szacowany,
        "zuzycie": zuzycie,
        # Ile procent katalogowego zasięgu faktycznie osiągasz — liczba, której
        # nie da się wyczytać z żadnej broszury.
        "procent_deklarowanego": (szacowany / deklarowany * 100)
                                  if (szacowany and deklarowany and deklarowany > 0) else None,
    }



# ==================== ANALIZA, PROGNOZY I BUDŻETY ====================
# Ta sekcja odpowiada na pytania, na które sama tabela liczb nie odpowiada:
# czy jest lepiej czy gorzej, ile to będzie kosztować do końca roku i czy zdążę
# przed własnym limitem. Wszystko liczone z danych, które użytkownik już wpisał —
# żadnych nowych obowiązków przy dodawaniu wpisu.
# db.py nie zna Fleta (korzysta z niego też eksport PDF i synchronizacja), więc
# obserwacje wracają stąd z KLUCZEM ikony i tonem, a nie z gotową kontrolką.

KATEGORIE_BUDZETU = {
    "paliwo": "Paliwo i energia",
    "serwis": "Serwis",
    "inne": "Inne koszty",
    "razem": "Wszystko razem",
}
OKRESY_BUDZETU = {"miesiac": "Miesięcznie", "rok": "Rocznie"}

# Od ilu procent limitu budżet przestaje być „w normie”. 80% wybrane świadomie:
# przy 90% na reakcję jest już zwykle za późno.
PROG_UWAGI_BUDZETU = 0.80

# Zmiana spalania poniżej tego progu to szum (inna stacja, inaczej dolany „pełny”
# bak, jedna trasa autostradą), a nie trend — nie ma o czym informować.
PROG_ISTOTNOSCI_TRENDU = 5.0

# Średnia długość miesiąca w dniach — prognozy przeliczają miesiące na dni,
# żeby niepełny miesiąc bieżący nie zaniżał wyniku.
DNI_W_MIESIACU = 30.44

# Dystanse do porównań w „Roku w pigułce”. Cel jest jeden: zamienić 18 000 km
# w coś, co da się sobie wyobrazić.
_DYSTANSE_ODNIESIENIA = [
    (40075, "okrążenie Ziemi wzdłuż równika"),
    (10000, "przejazd z Polski do Indii"),
    (3000, "przejazd z Warszawy do Lizbony"),
    (1600, "przejazd z Warszawy do Paryża"),
    (600, "przejazd z Warszawy do Berlina"),
    (300, "przejazd z Warszawy do Krakowa"),
]


def _wiersze_kosztow(conn, auto_id):
    """(data, kwota, kategoria) wszystkich kosztów pojazdu — jedno źródło dla
    budżetów, prognoz i podsumowania roku. Wizyta zbiorcza wchodzi jako CAŁOŚĆ,
    a należące do niej wpisy historii są pomijane, żeby ten sam koszt nie
    policzył się dwa razy (tak samo jak w eksporcie i na osi czasu)."""
    c = conn.cursor()
    wiersze = []
    c.execute("SELECT data, kwota FROM tankowania WHERE auto_id=?", (auto_id,))
    wiersze += [(d, k, "paliwo") for d, k in c.fetchall()]
    c.execute(
        "SELECT h.data, h.cena FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
        "WHERE z.auto_id=? AND h.wizyta_id IS NULL", (auto_id,)
    )
    wiersze += [(d, k, "serwis") for d, k in c.fetchall()]
    c.execute("SELECT data, koszt_calkowity FROM wizyty WHERE auto_id=?", (auto_id,))
    wiersze += [(d, k, "serwis") for d, k in c.fetchall()]
    c.execute("SELECT data, kwota FROM inne_koszty WHERE auto_id=?", (auto_id,))
    wiersze += [(d, k, "inne") for d, k in c.fetchall()]
    return wiersze


def koszty_w_okresie(auto_id, od_data=None, do_data=None):
    """Koszty pojazdu w przedziale dat (włącznie, oba końce opcjonalne),
    rozbite na kategorie budżetu. Zwraca komplet kluczy — także zerowych —
    więc wołający nie musi sprawdzać, czy coś w danej kategorii w ogóle było."""
    wynik = {k: 0.0 for k in KATEGORIE_BUDZETU}
    if not auto_id:
        return wynik

    with polacz_baze() as conn:
        wiersze = _wiersze_kosztow(conn, auto_id)

    for data_str, kwota, kategoria in wiersze:
        d = parsuj_date(data_str)
        if d == datetime.min.date():
            continue
        if od_data and d < od_data:
            continue
        if do_data and d > do_data:
            continue
        wartosc = float(kwota or 0.0)
        wynik[kategoria] += wartosc
        wynik["razem"] += wartosc
    return wynik


# -------------------- BUDŻETY --------------------

def pobierz_budzety(auto_id):
    """Ustawione limity pojazdu: [{kategoria, okres, kwota}] w stałej kolejności
    (kategorie jak w KATEGORIE_BUDZETU, miesięczne przed rocznymi)."""
    if not auto_id:
        return []
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT kategoria, okres, kwota FROM budzety WHERE auto_id=? AND kwota > 0", (auto_id,))
        wiersze = c.fetchall()

    kolejnosc_kat = list(KATEGORIE_BUDZETU)
    kolejnosc_okr = list(OKRESY_BUDZETU)
    budzety = [
        {"kategoria": k, "okres": o, "kwota": float(kw or 0)}
        for k, o, kw in wiersze
        if k in KATEGORIE_BUDZETU and o in OKRESY_BUDZETU
    ]
    budzety.sort(key=lambda b: (kolejnosc_okr.index(b["okres"]), kolejnosc_kat.index(b["kategoria"])))
    return budzety


def zapisz_budzet(auto_id, kategoria, okres, kwota):
    """Ustawia albo kasuje limit (kwota <= 0 = brak limitu). Upsert po
    (auto_id, kategoria, okres) — ten sam limit nie może istnieć dwa razy."""
    if not auto_id or kategoria not in KATEGORIE_BUDZETU or okres not in OKRESY_BUDZETU:
        return False
    try:
        wartosc = float(kwota or 0)
    except (TypeError, ValueError):
        wartosc = 0.0

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT id FROM budzety WHERE auto_id=? AND kategoria=? AND okres=?", (auto_id, kategoria, okres))
        w = c.fetchone()
        if wartosc <= 0:
            if w:
                # Nagrobek, żeby skasowany limit zniknął też u współdzielących —
                # bez tego wróciłby przy najbliższej synchronizacji.
                c.execute("SELECT zdalne_id FROM budzety WHERE id=?", (w[0],))
                zdalne = c.fetchone()
                conn.execute("DELETE FROM budzety WHERE id=?", (w[0],))
                if zdalne and zdalne[0]:
                    zarejestruj_nagrobek("budzety", zdalne[0])
            return True
        if w:
            conn.execute("UPDATE budzety SET kwota=? WHERE id=?", (wartosc, w[0]))
        else:
            conn.execute(
                "INSERT INTO budzety (auto_id, kategoria, okres, kwota) VALUES (?,?,?,?)",
                (auto_id, kategoria, okres, wartosc)
            )
    return True


def _granice_okresu(okres, dzis=None):
    """(początek, koniec, dni_okresu, dni_minione) bieżącego miesiąca albo roku.
    'dni_minione' liczy dzisiejszy dzień jako miniony — inaczej pierwszego dnia
    okresu tempo wydatków dzieliłoby przez zero."""
    dzis = dzis or datetime.now().date()
    if okres == "rok":
        poczatek = date_cls(dzis.year, 1, 1)
        koniec = date_cls(dzis.year, 12, 31)
    else:
        poczatek = date_cls(dzis.year, dzis.month, 1)
        if dzis.month == 12:
            koniec = date_cls(dzis.year, 12, 31)
        else:
            koniec = date_cls(dzis.year, dzis.month + 1, 1) - timedelta(days=1)
    dni_okresu = (koniec - poczatek).days + 1
    dni_minione = max(1, (dzis - poczatek).days + 1)
    return poczatek, koniec, dni_okresu, dni_minione


def stan_budzetow(auto_id, dzis=None):
    """Stan wykorzystania każdego ustawionego limitu. Dla każdego zwraca m.in.:
    wydano, limit, procent, pozostalo, tempo (prognoza całego okresu przy
    dotychczasowym tempie), status ('ok' / 'uwaga' / 'przekroczony') oraz
    'dzien_przekroczenia' — datę, na którą wypada wyczerpanie limitu, jeśli
    tempo się utrzyma. To ostatnie jest sednem: ostrzeżenie ma przyjść ZANIM
    limit padnie, a nie w dniu, w którym już nic się nie da zrobić."""
    budzety = pobierz_budzety(auto_id)
    if not budzety:
        return []

    dzis = dzis or datetime.now().date()
    cache_kosztow = {}
    wynik = []

    for b in budzety:
        poczatek, koniec, dni_okresu, dni_minione = _granice_okresu(b["okres"], dzis)
        if b["okres"] not in cache_kosztow:
            cache_kosztow[b["okres"]] = koszty_w_okresie(auto_id, poczatek, dzis)
        wydano = cache_kosztow[b["okres"]][b["kategoria"]]
        limit = b["kwota"]

        procent = (wydano / limit * 100) if limit > 0 else 0.0
        na_dzien = wydano / dni_minione
        tempo = na_dzien * dni_okresu

        if wydano > limit:
            status = "przekroczony"
        elif procent >= PROG_UWAGI_BUDZETU * 100 or tempo > limit:
            status = "uwaga"
        else:
            status = "ok"

        dzien_przekroczenia = None
        if status != "przekroczony" and na_dzien > 0 and limit > 0:
            dni_do_limitu = limit / na_dzien
            if dni_do_limitu <= dni_okresu:
                kandydat = poczatek + timedelta(days=int(dni_do_limitu))
                if kandydat > dzis:
                    dzien_przekroczenia = kandydat

        wynik.append({
            "kategoria": b["kategoria"],
            "etykieta_kategorii": KATEGORIE_BUDZETU[b["kategoria"]],
            "okres": b["okres"],
            "etykieta_okresu": OKRESY_BUDZETU[b["okres"]],
            "limit": limit,
            "wydano": wydano,
            "pozostalo": limit - wydano,
            "procent": procent,
            "tempo": tempo,
            "status": status,
            "dni_okresu": dni_okresu,
            "dni_minione": min(dni_minione, dni_okresu),
            "dni_pozostalo": max(0, (koniec - dzis).days),
            "dzien_przekroczenia": dzien_przekroczenia.strftime("%d.%m.%Y") if dzien_przekroczenia else None,
            "poczatek": poczatek,
            "koniec": koniec,
        })

    # Najpierw to, co się pali: przekroczone, potem ostrzeżenia, potem reszta.
    waga_statusu = {"przekroczony": 0, "uwaga": 1, "ok": 2}
    wynik.sort(key=lambda b: (waga_statusu[b["status"]], -b["procent"]))
    return wynik



# -------------------- TREND ZUŻYCIA --------------------

def analizuj_trend_spalania(auto_id, rodzaj=None, ostatnie=3, tlo=6):
    """Porównuje zużycie z OSTATNICH odcinków ze średnią z odcinków
    wcześniejszych i mówi, czy auto zaczęło palić więcej.

    Odcinek = trasa między dwoma tankowaniami „do pełna” (patrz
    pobierz_serie_spalania), bo tylko tam ilość paliwa odpowiada przejechanym
    kilometrom. Świadomie NIE porównujemy „miesiąc do miesiąca”: przy dwóch
    tankowaniach na miesiąc taki podział daje skoki rzędu 20%, które są
    wyłącznie efektem tego, gdzie wypadła granica kalendarza.

    Zwraca None, dopóki nie ma czym porównywać (min. `ostatnie` + 2 odcinki) —
    lepiej nie powiedzieć nic, niż ogłosić trend z dwóch pomiarów."""
    if not auto_id:
        return None

    rodzaj = rodzaj or domyslny_rodzaj_energii(auto_id)
    seria = pobierz_serie_spalania(auto_id, limit=None, rodzaj=rodzaj)
    if len(seria) < ostatnie + 2:
        return None

    wartosci = [w for _, w in seria]
    ostatnie_w = wartosci[-ostatnie:]
    wczesniejsze = wartosci[max(0, len(wartosci) - ostatnie - tlo):-ostatnie]
    if not wczesniejsze:
        return None

    sr_ostatnie = sum(ostatnie_w) / len(ostatnie_w)
    sr_wczesniej = sum(wczesniejsze) / len(wczesniejsze)
    if sr_wczesniej <= 0:
        return None

    zmiana = (sr_ostatnie - sr_wczesniej) / sr_wczesniej * 100
    if abs(zmiana) < PROG_ISTOTNOSCI_TRENDU:
        kierunek = "stabilnie"
    elif zmiana > 0:
        kierunek = "wzrost"
    else:
        kierunek = "spadek"

    najstarsza = parsuj_date(seria[max(0, len(seria) - ostatnie - tlo)][0])
    najnowsza = parsuj_date(seria[-1][0])
    dni_okna = (najnowsza - najstarsza).days if najnowsza > najstarsza else 0

    return {
        "rodzaj": rodzaj,
        "srednia_ostatnia": sr_ostatnie,
        "srednia_wczesniej": sr_wczesniej,
        "zmiana_proc": zmiana,
        "kierunek": kierunek,
        "odcinkow_ostatnio": len(ostatnie_w),
        "odcinkow_wczesniej": len(wczesniejsze),
        "dni_okna": dni_okna,
        "data_ostatniego": seria[-1][0],
        # Różnica w koszcie na 100 km — sam procent nie mówi, czy to problem
        # wart reakcji, czy pół złotówki.
        "roznica_na_100km": sr_ostatnie - sr_wczesniej,
    }


def koszt_trendu_rocznie(auto_id, trend):
    """Ile kosztuje (albo oszczędza) zmiana zużycia z analizuj_trend_spalania,
    przeliczona na rok przy dotychczasowym przebiegu rocznym i ostatniej znanej
    cenie jednostkowej. Procent robi wrażenie, ale dopiero złotówki na rok
    odpowiadają na pytanie, czy warto jechać do mechanika."""
    if not trend or trend["kierunek"] == "stabilnie":
        return None

    sredni_dzienny = oblicz_sredni_dzienny_przebieg(auto_id)
    if not sredni_dzienny:
        return None

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT kwota, litry FROM tankowania "
            "WHERE auto_id=? AND COALESCE(rodzaj_energii, ?) = ? AND litry > 0 "
            "ORDER BY id DESC LIMIT 5",
            (auto_id, domyslny_rodzaj_energii(auto_id), trend["rodzaj"])
        )
        ostatnie = c.fetchall()
    if not ostatnie:
        return None

    litry_razem = sum(float(r[1] or 0) for r in ostatnie)
    if litry_razem <= 0:
        return None
    cena_jedn = sum(float(r[0] or 0) for r in ostatnie) / litry_razem

    km_rocznie = sredni_dzienny * 365
    roznica_jednostek = trend["roznica_na_100km"] / 100 * km_rocznie
    return roznica_jednostek * cena_jedn


# -------------------- ZASIĘG NA BAKU --------------------

def pobierz_zasieg_na_baku(auto_id):
    """Zasięg auta spalinowego: ile przejedzie na PEŁNYM baku i ile zostało
    od ostatniego tankowania do pełna.

    Ta druga liczba jest szacunkiem z licznika, nie odczytem z pływaka: bierzemy
    kilometry przejechane od ostatniego pełnego baku i mnożymy przez rzeczywiste
    zużycie. Dlatego zwracamy też 'pewnosc' i 'dni_od_tankowania' — im starsze
    tankowanie, tym większa szansa, że po drodze ktoś dolał paliwa bez wpisu.

    Zwraca None, gdy nie podano pojemności baku albo nie da się policzyć
    zużycia (mniej niż dwa tankowania „do pełna”)."""
    if not auto_id:
        return None

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT pojemnosc_baku FROM samochody WHERE id=?", (auto_id,))
        w = c.fetchone()
    pojemnosc = _liczba_lub_none(w[0]) if w else None
    if not pojemnosc:
        return None

    rodzaj = ENERGIA_PALIWO
    if rodzaj not in rodzaje_energii_pojazdu(auto_id):
        return None

    seria = pobierz_serie_spalania(auto_id, limit=5, rodzaj=rodzaj)
    if not seria:
        return None
    spalanie = sum(w for _, w in seria) / len(seria)
    if spalanie <= 0:
        return None

    zasieg_pelny = pojemnosc / spalanie * 100

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT data, przebieg FROM tankowania "
            "WHERE auto_id=? AND COALESCE(rodzaj_energii, ?) = ? AND do_pelna=1",
            (auto_id, domyslny_rodzaj_energii(auto_id), rodzaj)
        )
        pelne = c.fetchall()

    wynik = {
        "pojemnosc": pojemnosc,
        "spalanie": spalanie,
        "zasieg_pelny": zasieg_pelny,
        "odcinkow": len(seria),
        "przejechane": None,
        "pozostalo_jednostek": None,
        "zasieg_pozostaly": None,
        "procent_baku": None,
        "data_tankowania": None,
        "dni_od_tankowania": None,
        "pewnosc": "brak",
    }

    if not pelne:
        return wynik

    # Ostatnie tankowanie do pełna: po dacie, przy remisie po przebiegu — ta sama
    # kolejność co wszędzie indziej, żeby dwa tankowania jednego dnia nie dały
    # ujemnego dystansu.
    ostatnie = max(pelne, key=lambda r: (parsuj_date(r[0]), int(r[1] or 0)))
    data_tank = parsuj_date(ostatnie[0])
    przebieg_tank = int(ostatnie[1] or 0)
    aktualny = pobierz_aktualny_przebieg(auto_id) or 0

    przejechane = aktualny - przebieg_tank
    if przejechane < 0:
        return wynik

    zuzyte = przejechane * spalanie / 100
    pozostalo = pojemnosc - zuzyte
    dni = (datetime.now().date() - data_tank).days if data_tank != datetime.min.date() else None

    wynik.update({
        "przejechane": przejechane,
        "pozostalo_jednostek": max(0.0, pozostalo),
        "zasieg_pozostaly": max(0.0, pozostalo / spalanie * 100),
        "procent_baku": max(0.0, min(100.0, pozostalo / pojemnosc * 100)),
        "data_tankowania": ostatnie[0],
        "dni_od_tankowania": dni,
        # Szacunek starzeje się szybko: po dwóch tygodniach od tankowania szansa,
        # że ktoś dolał paliwa bez wpisu, jest już spora.
        "pewnosc": "niska" if (dni is None or dni > 21) else ("srednia" if dni > 7 else "wysoka"),
    })
    return wynik


# -------------------- PROGNOZA KOSZTÓW --------------------

def prognoza_kosztow(auto_id, dzis=None, miesiecy_bazowych=6):
    """Ekstrapolacja wydatków do końca roku ze średniej z OSTATNICH PEŁNYCH
    miesięcy. Bieżący miesiąc jest z podstawy wykluczony — 3. dnia miesiąca
    zaniżałby średnią o dwie trzecie, a to właśnie na początku miesiąca ktoś
    najczęściej zagląda w prognozę.

    Zwraca None, gdy nie ma ani jednego pełnego miesiąca z wydatkami: prognoza
    z jednego tankowania to nie prognoza, tylko losowa liczba."""
    if not auto_id:
        return None

    dzis = dzis or datetime.now().date()
    koniec_roku = date_cls(dzis.year, 12, 31)

    # Pełne miesiące wstecz, licząc od miesiąca poprzedzającego bieżący.
    okresy = []
    rok, miesiac = dzis.year, dzis.month
    for _ in range(miesiecy_bazowych):
        miesiac -= 1
        if miesiac == 0:
            miesiac, rok = 12, rok - 1
        okresy.append((rok, miesiac))

    with polacz_baze() as conn:
        wiersze = _wiersze_kosztow(conn, auto_id)

    sumy_miesiecy = {o: 0.0 for o in okresy}
    wydano_w_roku = 0.0
    wydano_kategorie = {k: 0.0 for k in KATEGORIE_BUDZETU}
    poprzedni_rok_suma = 0.0
    najstarsza_data = None

    for data_str, kwota, kategoria in wiersze:
        d = parsuj_date(data_str)
        if d == datetime.min.date():
            continue
        wartosc = float(kwota or 0.0)
        if najstarsza_data is None or d < najstarsza_data:
            najstarsza_data = d
        klucz = (d.year, d.month)
        if klucz in sumy_miesiecy:
            sumy_miesiecy[klucz] += wartosc
        if d.year == dzis.year and d <= dzis:
            wydano_w_roku += wartosc
            wydano_kategorie[kategoria] += wartosc
            wydano_kategorie["razem"] += wartosc
        elif d.year == dzis.year - 1:
            poprzedni_rok_suma += wartosc

    # Miesiące SPRZED pierwszego wpisu nie są „miesiącem bez wydatków” — to
    # miesiące, w których aplikacja nie znała jeszcze tego auta. Wliczenie ich
    # jako zer rozcieńczyłoby średnią do zera.
    pelne_miesiace = [
        suma for (r, m), suma in sumy_miesiecy.items()
        if najstarsza_data is not None and (r, m) >= (najstarsza_data.year, najstarsza_data.month)
    ]
    if not pelne_miesiace or sum(pelne_miesiace) <= 0:
        return None

    srednia_miesieczna = sum(pelne_miesiace) / len(pelne_miesiace)
    dni_pozostalo = max(0, (koniec_roku - dzis).days)
    prognoza_do_konca = srednia_miesieczna / DNI_W_MIESIACU * dni_pozostalo
    prognoza_calego_roku = wydano_w_roku + prognoza_do_konca

    if len(pelne_miesiace) >= 4:
        pewnosc = "wysoka"
    elif len(pelne_miesiace) >= 2:
        pewnosc = "srednia"
    else:
        pewnosc = "niska"

    return {
        "srednia_miesieczna": srednia_miesieczna,
        "miesiecy_bazowych": len(pelne_miesiace),
        "wydano_w_roku": wydano_w_roku,
        "wydano_kategorie": wydano_kategorie,
        "prognoza_do_konca": prognoza_do_konca,
        "prognoza_calego_roku": prognoza_calego_roku,
        "dni_pozostalo": dni_pozostalo,
        "rok": dzis.year,
        "poprzedni_rok": poprzedni_rok_suma if poprzedni_rok_suma > 0 else None,
        "zmiana_rdr": (
            (prognoza_calego_roku - poprzedni_rok_suma) / poprzedni_rok_suma * 100
            if poprzedni_rok_suma > 0 else None
        ),
        "pewnosc": pewnosc,
    }



# -------------------- ROK W PIGUŁCE --------------------

def _porownanie_dystansu(km):
    """Zamienia przebieg w obraz („to prawie okrążenie Ziemi”). Bierzemy
    największy dystans odniesienia, który mieści się w przejechanym — tak, żeby
    porównanie zawsze brzmiało jak osiągnięcie, a nie jak wymówka."""
    if not km or km <= 0:
        return None
    for dystans, opis in _DYSTANSE_ODNIESIENIA:
        if km >= dystans:
            razy = km / dystans
            if razy >= 1.9:
                return f"{opis} — {formatuj_liczba_eksport(razy, 1)} raza"
            return f"prawie {opis}"
    return None


def podsumowanie_roku(auto_id, rok=None):
    """Wszystko, co da się powiedzieć o jednym roku pojazdu: przejechane
    kilometry, koszty w rozbiciu, najdroższy i najtańszy miesiąc, ulubiona
    stacja, największy pojedynczy wydatek, średnie zużycie i porównanie z rokiem
    poprzednim. Podstawa ekranu „Rok w pigułce” i generowanej z niego grafiki.

    Zwraca None dla roku bez ani jednego wpisu — pusty ekran z sześcioma zerami
    nie jest podsumowaniem."""
    if not auto_id:
        return None
    rok = int(rok or datetime.now().year)
    poczatek, koniec = date_cls(rok, 1, 1), date_cls(rok, 12, 31)
    dzis = datetime.now().date()
    granica = min(koniec, dzis) if rok == dzis.year else koniec

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        wiersze_kosztow = _wiersze_kosztow(conn, auto_id)
        c.execute(
            "SELECT data, przebieg, litry, kwota, stacja, do_pelna, rodzaj_energii "
            "FROM tankowania WHERE auto_id=?", (auto_id,)
        )
        tankowania = [dict(r) for r in c.fetchall()]
        c.execute("SELECT data, nazwa, kwota FROM inne_koszty WHERE auto_id=?", (auto_id,))
        inne = [dict(r) for r in c.fetchall()]
        c.execute(
            "SELECT h.data, h.cena, z.nazwa FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE z.auto_id=? AND h.wizyta_id IS NULL", (auto_id,)
        )
        serwis_wpisy = [dict(r) for r in c.fetchall()]
        c.execute("SELECT data, koszt_calkowity, wykonawca FROM wizyty WHERE auto_id=?", (auto_id,))
        wizyty_wpisy = [dict(r) for r in c.fetchall()]

    # --- koszty roku i rozkład na miesiące ---
    kategorie = {k: 0.0 for k in KATEGORIE_BUDZETU}
    miesiace = {m: 0.0 for m in range(1, 13)}
    miesiace_z_danymi = set()
    for data_str, kwota, kategoria in wiersze_kosztow:
        d = parsuj_date(data_str)
        if d == datetime.min.date() or d.year != rok or d > granica:
            continue
        wartosc = float(kwota or 0.0)
        kategorie[kategoria] += wartosc
        kategorie["razem"] += wartosc
        miesiace[d.month] += wartosc
        miesiace_z_danymi.add(d.month)

    if not miesiace_z_danymi:
        return None

    aktywne = {m: miesiace[m] for m in sorted(miesiace_z_danymi)}
    najdrozszy = max(aktywne.items(), key=lambda kv: kv[1])
    najtanszy = min(aktywne.items(), key=lambda kv: kv[1])

    # --- kilometry ---
    historia_prz = pobierz_historie_przebiegu(auto_id)
    przed_rokiem, w_roku = None, []
    for data_str, prz in historia_prz:
        d = parsuj_date(data_str)
        if d == datetime.min.date():
            continue
        if d < poczatek:
            przed_rokiem = prz
        elif d <= granica:
            w_roku.append(prz)
    # Punkt startowy to ostatni odczyt SPRZED roku, jeśli istnieje — inaczej
    # styczniowy przebieg policzyłby się jako „przejechane od zera”.
    start = przed_rokiem if przed_rokiem is not None else (min(w_roku) if w_roku else None)
    koniec_prz = max(w_roku) if w_roku else None
    km = (koniec_prz - start) if (start is not None and koniec_prz is not None and koniec_prz > start) else 0

    # --- tankowania roku ---
    tank_roku = []
    for t in tankowania:
        d = parsuj_date(t.get("data"))
        if d != datetime.min.date() and d.year == rok and d <= granica:
            tank_roku.append(t)

    litry = sum(float(t.get("litry") or 0) for t in tank_roku
                if (t.get("rodzaj_energii") or ENERGIA_PALIWO) == ENERGIA_PALIWO)
    kwh = sum(float(t.get("litry") or 0) for t in tank_roku
              if t.get("rodzaj_energii") == ENERGIA_PRAD)

    # Ulubiona stacja — po liczbie tankowań, z kanoniczną pisownią z grupy.
    grupy_stacji = {}
    for t in tank_roku:
        nazwa = " ".join(str(t.get("stacja") or "").split())
        klucz = klucz_stacji(nazwa)
        if not klucz:
            continue
        grupa = grupy_stacji.setdefault(klucz, {"ile": 0, "kwota": 0.0, "warianty": {}})
        grupa["ile"] += 1
        grupa["kwota"] += float(t.get("kwota") or 0)
        grupa["warianty"][nazwa] = grupa["warianty"].get(nazwa, 0) + 1
    ulubiona = None
    if grupy_stacji:
        klucz_top = max(grupy_stacji.items(), key=lambda kv: (kv[1]["ile"], kv[1]["kwota"]))
        ulubiona = {
            "nazwa": max(klucz_top[1]["warianty"].items(), key=lambda kv: (kv[1], kv[0]))[0],
            "liczba": klucz_top[1]["ile"],
            "kwota": klucz_top[1]["kwota"],
        }

    # --- średnie zużycie roku: odcinki zamknięte W TYM roku ---
    seria = pobierz_serie_spalania(auto_id, limit=None, rodzaj=domyslny_rodzaj_energii(auto_id))
    zuzycie_roku = [w for data_str, w in seria
                    if parsuj_date(data_str) != datetime.min.date()
                    and parsuj_date(data_str).year == rok]
    srednie_zuzycie = (sum(zuzycie_roku) / len(zuzycie_roku)) if zuzycie_roku else None

    # --- największy pojedynczy wydatek ---
    kandydaci = []
    for w in inne:
        kandydaci.append((w.get("data"), float(w.get("kwota") or 0), str(w.get("nazwa") or "Inny koszt")))
    for w in serwis_wpisy:
        kandydaci.append((w.get("data"), float(w.get("cena") or 0), str(w.get("nazwa") or "Serwis")))
    for w in wizyty_wpisy:
        kandydaci.append((w.get("data"), float(w.get("koszt_calkowity") or 0),
                          f"Wizyta: {w.get('wykonawca') or 'warsztat'}"))
    for t in tank_roku:
        kandydaci.append((t.get("data"), float(t.get("kwota") or 0),
                          f"Tankowanie: {t.get('stacja') or 'stacja nieznana'}"))
    kandydaci = [k for k in kandydaci
                 if parsuj_date(k[0]) != datetime.min.date()
                 and parsuj_date(k[0]).year == rok and parsuj_date(k[0]) <= granica and k[1] > 0]
    najwiekszy = max(kandydaci, key=lambda k: k[1]) if kandydaci else None

    # --- porównanie z poprzednim rokiem ---
    poprzedni = 0.0
    for data_str, kwota, _kat in wiersze_kosztow:
        d = parsuj_date(data_str)
        if d != datetime.min.date() and d.year == rok - 1:
            poprzedni += float(kwota or 0.0)

    return {
        "rok": rok,
        "niepelny": rok == dzis.year,
        "km": km,
        "koszty": kategorie,
        "koszt_km": (kategorie["razem"] / km) if km > 0 else None,
        "miesiace": miesiace,
        "najdrozszy_miesiac": {"miesiac": najdrozszy[0], "kwota": najdrozszy[1]},
        "najtanszy_miesiac": {"miesiac": najtanszy[0], "kwota": najtanszy[1]},
        "liczba_tankowan": len(tank_roku),
        "litry": litry,
        "kwh": kwh,
        "ulubiona_stacja": ulubiona,
        "srednie_zuzycie": srednie_zuzycie,
        "liczba_wizyt": len([w for w in wizyty_wpisy
                             if parsuj_date(w.get("data")) != datetime.min.date()
                             and parsuj_date(w.get("data")).year == rok]),
        "liczba_wpisow_serwisu": len([w for w in serwis_wpisy
                                      if parsuj_date(w.get("data")) != datetime.min.date()
                                      and parsuj_date(w.get("data")).year == rok]),
        "najwiekszy_wydatek": ({"data": najwiekszy[0], "kwota": najwiekszy[1], "opis": najwiekszy[2]}
                               if najwiekszy else None),
        "poprzedni_rok": poprzedni if poprzedni > 0 else None,
        "zmiana_rdr": ((kategorie["razem"] - poprzedni) / poprzedni * 100) if poprzedni > 0 else None,
        "porownanie_dystansu": _porownanie_dystansu(km),
        "sredni_koszt_miesiaca": (kategorie["razem"] / len(miesiace_z_danymi)) if miesiace_z_danymi else 0.0,
    }


def lata_z_danymi(auto_id):
    """Lata, w których pojazd ma jakikolwiek wpis — malejąco. Selektor roku w
    „Roku w pigułce” pokazuje tylko te, dla których jest co pokazywać."""
    if not auto_id:
        return []
    with polacz_baze() as conn:
        wiersze = _wiersze_kosztow(conn, auto_id)
    lata = set()
    for data_str, _kwota, _kat in wiersze:
        d = parsuj_date(data_str)
        if d != datetime.min.date():
            lata.add(d.year)
    return sorted(lata, reverse=True)



# -------------------- SILNIK OBSERWACJI --------------------
# Jedno miejsce, w którym liczby zamieniają się w zdania. Każda reguła zwraca
# obserwację z WAGĄ; kokpit bierze najważniejszą, zakładka Analiza wszystkie.
# Reguła, która nie ma nic sensownego do powiedzenia, nie zwraca nic — cisza
# jest lepsza niż „wszystko w normie” powtarzane przy każdym uruchomieniu.

def _obserwacja(klucz, ton, ikona, tytul, tekst, waga, trasa=None):
    return {"klucz": klucz, "ton": ton, "ikona": ikona, "tytul": tytul,
            "tekst": tekst, "waga": waga, "trasa": trasa}


def _kwota_txt(wartosc, decimale=0):
    return f"{formatuj_liczba_eksport(wartosc, decimale)} {pobierz_walute()}"


def obserwacje_analityczne(auto_id, limit=None):
    """Lista automatycznych spostrzeżeń o pojeździe, posortowana malejąco po
    ważności. Każde ma 'ton' ('zly' / 'uwaga' / 'dobry' / 'neutralny'), klucz
    ikony i — gdy jest dokąd pójść — trasę do odpowiedniego ekranu."""
    if not auto_id:
        return []

    obserwacje = []
    dzis = datetime.now().date()

    # 1. Budżety — najpilniejsze, bo dotyczą pieniędzy, które właśnie wyciekają.
    for b in stan_budzetow(auto_id, dzis):
        etykieta = f"{b['etykieta_kategorii'].lower()} ({b['etykieta_okresu'].lower()})"
        if b["status"] == "przekroczony":
            obserwacje.append(_obserwacja(
                f"budzet_{b['kategoria']}_{b['okres']}", "zly", "budzet",
                "Budżet przekroczony",
                f"Limit na {etykieta} przekroczony o {_kwota_txt(abs(b['pozostalo']))} "
                f"({formatuj_liczba_eksport(b['procent'], 0)}% limitu).",
                100, "/budzet",
            ))
        elif b["status"] == "uwaga":
            if b["dzien_przekroczenia"]:
                tekst = (f"Przy obecnym tempie limit na {etykieta} skończy się "
                         f"{b['dzien_przekroczenia']} — {b['dni_pozostalo']} dni przed końcem okresu.")
            else:
                tekst = (f"Wykorzystane {formatuj_liczba_eksport(b['procent'], 0)}% limitu na {etykieta}, "
                         f"zostało {_kwota_txt(b['pozostalo'])}.")
            obserwacje.append(_obserwacja(
                f"budzet_{b['kategoria']}_{b['okres']}", "uwaga", "budzet",
                "Budżet pod presją", tekst, 90, "/budzet",
            ))

    # 2. Zasięg na baku — jedyna obserwacja, która może uratować przed pchaniem auta.
    bak = pobierz_zasieg_na_baku(auto_id)
    if bak and bak.get("zasieg_pozostaly") is not None and bak["pewnosc"] in ("wysoka", "srednia"):
        if bak["zasieg_pozostaly"] < 80:
            obserwacje.append(_obserwacja(
                "bak_niski", "uwaga", "bak", "Czas zatankować",
                f"Szacunkowo zostało około {formatuj_liczba_eksport(bak['zasieg_pozostaly'], 0)} km "
                f"({formatuj_liczba_eksport(bak['procent_baku'], 0)}% baku).",
                85, "/tankowanie/nowe",
            ))

    # 3. Trend zużycia — to, o co pyta się najczęściej po zatankowaniu.
    trend = analizuj_trend_spalania(auto_id)
    if trend and trend["kierunek"] != "stabilnie":
        czy_prad = trend["rodzaj"] == ENERGIA_PRAD
        # Wartości podajemy w jednostce użytkownika, ale KIERUNEK opisujemy
        # słowem („zużycie wyższe”), a nie porównaniem liczb: przy km/l i mpg
        # rosnące zużycie oznacza MALEJĄCĄ liczbę i „o 14% więcej” byłoby
        # wprost sprzeczne z tym, co widać na kafelku.
        teraz = formatuj_zuzycie_tekst(trend["srednia_ostatnia"], czy_prad)
        wczesniej = formatuj_zuzycie_tekst(trend["srednia_wczesniej"], czy_prad)
        procent = formatuj_liczba_eksport(abs(trend["zmiana_proc"]), 0)
        rocznie = koszt_trendu_rocznie(auto_id, trend)
        ogon = (f" To około {_kwota_txt(abs(rocznie))} rocznie."
                if rocznie and abs(rocznie) >= 50 else "")
        if trend["kierunek"] == "wzrost":
            obserwacje.append(_obserwacja(
                "trend_spalania", "uwaga", "spalanie", "Zużycie w górę",
                f"Ostatnie {trend['odcinkow_ostatnio']} odcinki: {teraz} wobec {wczesniej} "
                f"wcześniej — zużycie wyższe o {procent}%.{ogon}",
                80, "/",
            ))
        else:
            obserwacje.append(_obserwacja(
                "trend_spalania", "dobry", "spalanie", "Zużycie w dół",
                f"Ostatnie {trend['odcinkow_ostatnio']} odcinki: {teraz} wobec {wczesniej} "
                f"wcześniej — zużycie niższe o {procent}%.{ogon}",
                60, "/",
            ))

    # 4. Prognoza roczna i zestawienie z poprzednim rokiem.
    prognoza = prognoza_kosztow(auto_id, dzis)
    if prognoza and prognoza["dni_pozostalo"] > 14:
        obserwacje.append(_obserwacja(
            "prognoza_rok", "neutralny", "prognoza", "Prognoza do końca roku",
            f"Przy obecnym tempie do końca roku dojdzie jeszcze około "
            f"{_kwota_txt(prognoza['prognoza_do_konca'])} — cały {prognoza['rok']} zamknie się "
            f"kwotą około {_kwota_txt(prognoza['prognoza_calego_roku'])}.",
            55, "/rok",
        ))
    if prognoza and prognoza.get("zmiana_rdr") is not None and abs(prognoza["zmiana_rdr"]) >= 10:
        w_gore = prognoza["zmiana_rdr"] > 0
        obserwacje.append(_obserwacja(
            "prognoza_rdr", "uwaga" if w_gore else "dobry", "prognoza",
            "Rok do roku",
            f"Ten rok zapowiada się {'drożej' if w_gore else 'taniej'} od poprzedniego o "
            f"{formatuj_liczba_eksport(abs(prognoza['zmiana_rdr']), 0)}% "
            f"({_kwota_txt(prognoza['poprzedni_rok'])} → {_kwota_txt(prognoza['prognoza_calego_roku'])}).",
            50, "/rok",
        ))

    # 5. Bieżący miesiąc na tle średniej — porównujemy TEMPO, nie kwoty, bo
    #    5. dnia miesiąca każda kwota będzie niższa od średniej.
    if prognoza and prognoza["srednia_miesieczna"] > 0:
        poczatek_mc = date_cls(dzis.year, dzis.month, 1)
        wydano_mc = koszty_w_okresie(auto_id, poczatek_mc, dzis)["razem"]
        dni_minione = (dzis - poczatek_mc).days + 1
        tempo_mc = wydano_mc / dni_minione * DNI_W_MIESIACU
        odchylenie = (tempo_mc - prognoza["srednia_miesieczna"]) / prognoza["srednia_miesieczna"] * 100
        if dni_minione >= 7 and abs(odchylenie) >= 25:
            drozej = odchylenie > 0
            obserwacje.append(_obserwacja(
                "tempo_miesiaca", "uwaga" if drozej else "dobry", "miesiac",
                "Ten miesiąc odstaje",
                f"Do dziś {_kwota_txt(wydano_mc)}; w tym tempie miesiąc skończy się kwotą około "
                f"{_kwota_txt(tempo_mc)}, czyli o {formatuj_liczba_eksport(abs(odchylenie), 0)}% "
                f"{'więcej' if drozej else 'mniej'} niż zwykle.",
                45,
            ))

    # 6. Ceny paliwa: gdzie tankujesz drożej, niż musisz.
    ceny = pobierz_trend_cen_paliwa(auto_id)
    stacje = [st for st in ceny.get("stacje", []) if st["liczba_tankowan"] >= 2]
    if len(stacje) >= 2:
        najtansza, najdrozsza = stacje[0], stacje[-1]
        roznica = najdrozsza["srednia_cena"] - najtansza["srednia_cena"]
        if najtansza["srednia_cena"] > 0 and roznica / najtansza["srednia_cena"] >= 0.04:
            litry_rocznie = 0.0
            seria = pobierz_serie_spalania(auto_id, limit=5, rodzaj=ENERGIA_PALIWO)
            sredni_dzienny = oblicz_sredni_dzienny_przebieg(auto_id)
            if seria and sredni_dzienny:
                spalanie = sum(w for _, w in seria) / len(seria)
                litry_rocznie = spalanie / 100 * sredni_dzienny * 365
            oszczednosc = roznica * litry_rocznie
            ogon = (f" Tankując zawsze tam, zaoszczędziłbyś około {_kwota_txt(oszczednosc)} rocznie."
                    if oszczednosc >= 50 else "")
            obserwacje.append(_obserwacja(
                "stacje_ceny", "neutralny", "stacja", "Różnice między stacjami",
                f"„{najtansza['nazwa']}” wychodzi średnio o "
                f"{formatuj_liczba_eksport(roznica, 2)} {pobierz_walute()} na jednostce taniej niż "
                f"„{najdrozsza['nazwa']}”.{ogon}",
                40,
            ))

    # 7. Cisza w danych — statystyki są tyle warte, ile kompletność wpisów.
    ostatnie_daty = []
    with polacz_baze() as conn:
        for data_str, _kwota, _kat in _wiersze_kosztow(conn, auto_id):
            d = parsuj_date(data_str)
            if d != datetime.min.date():
                ostatnie_daty.append(d)
    if ostatnie_daty:
        dni_ciszy = (dzis - max(ostatnie_daty)).days
        if dni_ciszy >= 45:
            obserwacje.append(_obserwacja(
                "cisza", "neutralny", "cisza", "Dawno nic nie dopisałeś",
                f"Ostatni wpis kosztowy ma {dni_ciszy} dni. Im więcej luk, tym mniej warte "
                f"są wszystkie liczby powyżej.",
                35,
            ))

    obserwacje.sort(key=lambda o: -o["waga"])
    return obserwacje[:limit] if limit else obserwacje


def _liczba_lub_none(tekst):
    """Pola specyfikacji są tekstowe (użytkownik wpisuje '52 kWh' albo '52,5'),
    więc wyciągamy z nich liczbę tak samo pobłażliwie, jak import CSV."""
    wartosc = _parsuj_liczbe_csv(tekst)
    return wartosc if (wartosc and wartosc > 0) else None


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
    # Wskaźnik 0-100 (ten sam, co kafelek „Kondycja” w kokpicie) — jedna z osi
    # radaru w porównaniu pojazdów.
    dane["kondycja"] = oblicz_kondycje_pojazdu(auto_id)

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

def pobierz_koszty_miesieczne(auto_id, liczba_miesiecy=6):
    """Suma kosztów (paliwo + serwis + inne) dla ostatnich `liczba_miesiecy`
    miesięcy, włącznie z bieżącym — używane przez mini-wykres na dashboardzie
    startowym (patrz MainView._buduj_kokpit). Zwraca listę (rok, miesiac, suma)
    posortowaną chronologicznie rosnąco; miesiące bez wydatków mają sumę 0.0."""
    if not auto_id:
        return []

    dzisiaj = datetime.now()
    klucze = []
    for i in range(liczba_miesiecy - 1, -1, -1):
        m = dzisiaj.month - i
        y = dzisiaj.year
        while m <= 0:
            m += 12
            y -= 1
        klucze.append((y, m))

    sumy = {k: 0.0 for k in klucze}

    with polacz_baze() as conn:
        c = conn.cursor()
        wiersze = []
        c.execute("SELECT data, kwota FROM tankowania WHERE auto_id=?", (auto_id,))
        wiersze += c.fetchall()
        c.execute(
            "SELECT h.data, h.cena FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE z.auto_id=? AND h.wizyta_id IS NULL", (auto_id,)
        )
        wiersze += c.fetchall()
        c.execute("SELECT data, koszt_calkowity FROM wizyty WHERE auto_id=?", (auto_id,))
        wiersze += c.fetchall()
        c.execute("SELECT data, kwota FROM inne_koszty WHERE auto_id=?", (auto_id,))
        wiersze += c.fetchall()

    for data_str, kwota in wiersze:
        d = parsuj_date(data_str)
        if d == datetime.min.date():
            continue
        klucz = (d.year, d.month)
        if klucz in sumy:
            sumy[klucz] += float(kwota or 0.0)

    return [(y, m, sumy[(y, m)]) for (y, m) in klucze]

def pobierz_koszt_miesiaca_do_dnia(auto_id, rok, miesiac, do_dnia):
    """Suma kosztów (paliwo + serwis + inne) dla danego miesiąca, ale TYLKO do
    dnia `do_dnia` włącznie. Używane do uczciwego porównania 'ile wydałem w tym
    miesiącu do dzisiaj' z analogicznym okresem poprzedniego miesiąca — zamiast
    mylącego porównania niepełnego bieżącego miesiąca z CAŁYM poprzednim
    (patrz MainView._buduj_kokpit -> widget_koszt_miesiac), które 2. dnia
    miesiąca niemal zawsze pokazywało fałszywe "📉 Spada o 95%"."""
    if not auto_id:
        return 0.0

    suma = 0.0
    with polacz_baze() as conn:
        c = conn.cursor()
        wiersze = []
        c.execute("SELECT data, kwota FROM tankowania WHERE auto_id=?", (auto_id,))
        wiersze += c.fetchall()
        c.execute(
            "SELECT h.data, h.cena FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE z.auto_id=? AND h.wizyta_id IS NULL", (auto_id,)
        )
        wiersze += c.fetchall()
        c.execute("SELECT data, koszt_calkowity FROM wizyty WHERE auto_id=?", (auto_id,))
        wiersze += c.fetchall()
        c.execute("SELECT data, kwota FROM inne_koszty WHERE auto_id=?", (auto_id,))
        wiersze += c.fetchall()

    for data_str, kwota in wiersze:
        d = parsuj_date(data_str)
        if d == datetime.min.date():
            continue
        if d.year == rok and d.month == miesiac and d.day <= do_dnia:
            suma += float(kwota or 0.0)

    return suma

def klucz_stacji(nazwa):
    """Klucz porównawczy nazw stacji — bez wielkości liter, bez nadmiarowych
    spacji i bez końcowej interpunkcji. Dzięki temu 'Orlen', 'orlen  ' i
    'ORLEN.' to jedna i ta sama stacja w rankingu cen i w podpowiedziach."""
    tekst = " ".join((nazwa or "").split()).lower()
    return tekst.strip(" .,;:-")


# ============================================================================
#  NORMALIZACJA NAZW
# ============================================================================
# Ten sam mechanizm, co klucz_stacji dla stacji paliw, tylko zastosowany szerzej:
# „Filtr oleju”, „filtr Oleju” i „filtr oleju ” to jedna nazwa, a nie trzy
# osobne pozycje w magazynie, w tagach, wśród warsztatów i podzespołów.
# Klucz służy WYŁĄCZNIE do porównywania — w bazie zostaje pisownia użytkownika.

# Nazwy porównujemy po zdjęciu emoji: podzespoły założone starszymi wersjami
# aplikacji mają je w nazwie („🛢️ Olej silnikowy i filtr”), a te same wpisy
# dodane dziś już nie.
def klucz_nazwy(tekst):
    """Klucz porównawczy nazwy: bez emoji, bez wielkości liter, ze scalonymi
    białymi znakami i bez interpunkcji na brzegach."""
    czysty = bez_emoji(tekst)
    return " ".join(czysty.split()).lower().strip(" .,;:-_/")


def normalizuj_nazwe(tekst):
    """Pisownia gotowa do ZAPISU: scalone spacje i obcięte brzegi. Nie zmienia
    wielkości liter ani treści — użytkownik ma prawo do swojej pisowni, chodzi
    tylko o to, żeby „filtr oleju ” i „filtr  oleju” nie były różnymi wpisami."""
    return " ".join(str(tekst or "").split()).strip()


# Gdzie normalizacja obowiązuje: tabela -> (kolumna z nazwą, etykieta dla UI).
# Kolejność steruje kolejnością sekcji w narzędziu scalania duplikatów.
POLA_NAZW_DO_NORMALIZACJI = [
    ("magazyn_czesci", "nazwa", "Części i płyny w magazynie"),
    ("tagi", "nazwa", "Tagi (kategorie kosztów)"),
    ("warsztaty", "nazwa", "Warsztaty"),
    ("zadania", "nazwa", "Podzespoły"),
]


def dopasuj_istniejaca_nazwe(auto_id, tabela, nazwa):
    """Jeśli podana nazwa to tylko inny wariant zapisu czegoś, co już istnieje
    dla tego pojazdu, zwraca ISTNIEJĄCĄ pisownię — dokładnie tak, jak
    dopasuj_do_slownika robi to dla stacji paliw. W przeciwnym razie zwraca
    nazwę po samej normalizacji białych znaków."""
    kolumna = next((k for t, k, _ in POLA_NAZW_DO_NORMALIZACJI if t == tabela), None)
    czysta = normalizuj_nazwe(nazwa)
    if not czysta or not auto_id or not kolumna:
        return czysta

    klucz = klucz_nazwy(czysta)
    if not klucz:
        return czysta

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(f"SELECT {kolumna} FROM {tabela} WHERE auto_id=?", (auto_id,))
        for (istniejaca,) in c.fetchall():
            if klucz_nazwy(istniejaca) == klucz:
                return str(istniejaca)
    return czysta


def znajdz_duplikaty_nazw(auto_id):
    """Grupy nazw, które po normalizacji są tym samym, a w bazie siedzą jako
    osobne wiersze. Zwraca listę słowników gotowych do pokazania w Ustawieniach:
    {tabela, etykieta, klucz, kanoniczna, warianty:[(id, nazwa, ile_uzyc)]}.
    Kanoniczna to wariant użyty najczęściej — przy remisie ten o najniższym ID
    (czyli najstarszy), żeby wynik był powtarzalny."""
    if not auto_id:
        return []

    # Ile razy dana pozycja jest faktycznie używana — po tym wybieramy zwycięzcę
    # scalania i to pokazujemy użytkownikowi przy każdym wariancie.
    zapytania_uzyc = {
        "magazyn_czesci": (
            "SELECT magazyn_id, COUNT(*) FROM ("
            " SELECT magazyn_id FROM wizyta_czesci_magazynu"
            " UNION ALL SELECT magazyn_id FROM historia_czesci_magazynu"
            ") GROUP BY magazyn_id"
        ),
        "zadania": "SELECT zadanie_id, COUNT(*) FROM historia GROUP BY zadanie_id",
    }

    grupy = []
    with polacz_baze() as conn:
        c = conn.cursor()
        for tabela, kolumna, etykieta in POLA_NAZW_DO_NORMALIZACJI:
            uzycia = {}
            if tabela in zapytania_uzyc:
                c.execute(zapytania_uzyc[tabela])
                uzycia = {r[0]: int(r[1] or 0) for r in c.fetchall()}

            c.execute(f"SELECT id, {kolumna} FROM {tabela} WHERE auto_id=? ORDER BY id", (auto_id,))
            wiersze = c.fetchall()

            wg_klucza = {}
            for wiersz_id, nazwa in wiersze:
                klucz = klucz_nazwy(nazwa)
                if not klucz:
                    continue
                wg_klucza.setdefault(klucz, []).append(
                    (wiersz_id, str(nazwa or ""), uzycia.get(wiersz_id, 0))
                )

            for klucz, warianty in wg_klucza.items():
                if len(warianty) < 2:
                    continue
                kanoniczny = max(warianty, key=lambda w: (w[2], -w[0]))
                grupy.append({
                    "tabela": tabela,
                    "kolumna": kolumna,
                    "etykieta": etykieta,
                    "klucz": klucz,
                    "kanoniczna": kanoniczny,
                    "warianty": sorted(warianty, key=lambda w: (-w[2], w[0])),
                })
    return grupy


# Dokąd przepisać powiązania przy scalaniu: tabela nazw -> [(tabela, kolumna)].
PRZEPIECIA_PRZY_SCALANIU = {
    "magazyn_czesci": [("wizyta_czesci_magazynu", "magazyn_id"), ("historia_czesci_magazynu", "magazyn_id")],
    "zadania": [("historia", "zadanie_id"), ("do_zrobienia", "zadanie_id")],
    "warsztaty": [],
    "tagi": [],
}


def scal_duplikaty_nazw(auto_id, tabela, id_docelowy, ids_zrodlowe):
    """Zlewa warianty w jeden wpis: przepina powiązania na wpis docelowy,
    a same duplikaty kasuje. Zwraca liczbę scalonych pozycji.

    Magazyn ma dodatkowo stan ilościowy — sztuki z duplikatów DOLICZAMY do
    pozycji docelowej, bo fizycznie leżą w tym samym pudełku, tylko były
    zapisane pod dwiema pisowniami. Tagi i warsztaty żyją w polach tekstowych
    innych tabel, więc tam podmieniamy nazwę zamiast ID."""
    ids_zrodlowe = [i for i in (ids_zrodlowe or []) if i and i != id_docelowy]
    if not auto_id or not tabela or not id_docelowy or not ids_zrodlowe:
        return 0

    kolumna = next((k for t, k, _ in POLA_NAZW_DO_NORMALIZACJI if t == tabela), None)
    if not kolumna:
        return 0

    placeholders = ",".join("?" for _ in ids_zrodlowe)
    zdalne_do_nagrobka = []

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(f"SELECT {kolumna} FROM {tabela} WHERE id=?", (id_docelowy,))
        w = c.fetchone()
        if not w:
            return 0
        nazwa_docelowa = str(w[0] or "")

        c.execute(f"SELECT id, {kolumna}, zdalne_id FROM {tabela} WHERE id IN ({placeholders})", tuple(ids_zrodlowe))
        znikajace = c.fetchall()
        zdalne_do_nagrobka = [r[2] for r in znikajace if r[2]]

        if tabela == "magazyn_czesci":
            c.execute(
                f"SELECT COALESCE(SUM(ilosc), 0) FROM magazyn_czesci WHERE id IN ({placeholders})",
                tuple(ids_zrodlowe)
            )
            suma = float((c.fetchone() or [0])[0] or 0)
            if suma:
                c.execute("UPDATE magazyn_czesci SET ilosc = ilosc + ? WHERE id=?", (suma, id_docelowy))

        for tab_powiazana, kol_powiazana in PRZEPIECIA_PRZY_SCALANIU.get(tabela, []):
            c.execute(
                f"UPDATE {tab_powiazana} SET {kol_powiazana}=? WHERE {kol_powiazana} IN ({placeholders})",
                (id_docelowy, *ids_zrodlowe)
            )

        # Tagi i warsztaty są w innych tabelach zapisane NAZWĄ, nie kluczem obcym.
        if tabela == "tagi":
            for _, stara_nazwa, _ in znikajace:
                _podmien_tag_w_tekstach(c, auto_id, stara_nazwa, nazwa_docelowa)
        elif tabela == "warsztaty":
            for _, stara_nazwa, _ in znikajace:
                for tab in ("wizyty", "historia"):
                    if tab == "historia":
                        c.execute(
                            "UPDATE historia SET wykonawca=? WHERE wykonawca=? AND zadanie_id IN "
                            "(SELECT id FROM zadania WHERE auto_id=?)",
                            (nazwa_docelowa, stara_nazwa, auto_id)
                        )
                    else:
                        c.execute(
                            "UPDATE wizyty SET wykonawca=? WHERE wykonawca=? AND auto_id=?",
                            (nazwa_docelowa, stara_nazwa, auto_id)
                        )

        c.execute(f"DELETE FROM {tabela} WHERE id IN ({placeholders})", tuple(ids_zrodlowe))

    for zid in zdalne_do_nagrobka:
        zarejestruj_nagrobek(tabela, zid)

    if tabela == "zadania":
        przelicz_wszystkie_zadania(auto_id)

    return len(ids_zrodlowe)


def _podmien_tag_w_tekstach(c, auto_id, stara_nazwa, nowa_nazwa):
    """Tagi trzymane są jako lista rozdzielona przecinkami w kolumnie 'tagi'.
    Podmieniamy element listy, nie fragment tekstu — inaczej tag „UB” zjadłby
    kawałek nazwy „UBEZPIECZENIE”."""
    for tabela in ("tankowania", "wizyty", "inne_koszty"):
        c.execute(f"SELECT id, tagi FROM {tabela} WHERE auto_id=? AND tagi IS NOT NULL AND tagi <> ''", (auto_id,))
        for wiersz_id, tekst in c.fetchall():
            elementy = [t.strip() for t in str(tekst or "").split(",") if t.strip()]
            zmienione, widziane = [], set()
            for element in elementy:
                docelowy = nowa_nazwa if element == stara_nazwa else element
                if docelowy not in widziane:
                    widziane.add(docelowy)
                    zmienione.append(docelowy)
            nowy_tekst = ", ".join(zmienione)
            if nowy_tekst != tekst:
                c.execute(f"UPDATE {tabela} SET tagi=? WHERE id=?", (nowy_tekst, wiersz_id))


def pobierz_stacje_paliw(auto_id):
    """Słownik stacji budowany w locie z dotychczasowych tankowań pojazdu — bez
    osobnej tabeli, bo dane już są w 'tankowania'. Warianty zapisu tej samej
    stacji są scalane; jako kanoniczna wygrywa forma użyta najczęściej, a przy
    remisie ostatnio użyta. Zwraca listę nazw posortowaną malejąco po liczbie
    tankowań, przy remisie alfabetycznie."""
    if not auto_id:
        return []

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT stacja, data FROM tankowania "
            "WHERE auto_id=? AND stacja IS NOT NULL AND TRIM(stacja) <> ''",
            (auto_id,)
        )
        wiersze = c.fetchall()

    grupy = {}
    for stacja, data_str in wiersze:
        nazwa = " ".join((stacja or "").split())
        klucz = klucz_stacji(nazwa)
        if not klucz:
            continue
        d = parsuj_date(data_str)
        grupa = grupy.setdefault(klucz, {"licznik": 0, "warianty": {}})
        grupa["licznik"] += 1
        wariant = grupa["warianty"].setdefault(nazwa, {"ile": 0, "ostatnia": datetime.min.date()})
        wariant["ile"] += 1
        if d > wariant["ostatnia"]:
            wariant["ostatnia"] = d

    wynik = []
    for grupa in grupy.values():
        kanoniczna = max(
            grupa["warianty"].items(),
            key=lambda kv: (kv[1]["ile"], kv[1]["ostatnia"], kv[0])
        )[0]
        wynik.append((kanoniczna, grupa["licznik"]))

    wynik.sort(key=lambda x: (-x[1], x[0].lower()))
    return [nazwa for nazwa, _ in wynik]

def pobierz_trend_cen_paliwa(auto_id):
    """Cena za litr w czasie (do wykresu) oraz zestawienie średnich cen per
    stacja (do rankingu „najtańsza stacja, na której tankowałeś”). Uwzględnia
    tylko tankowania z dodatnią liczbą litrów; stacja jest opcjonalna — wpisy
    bez niej trafiają do 'punkty', ale nie do rankingu 'stacje'.
    Zwraca {"punkty": [(data, cena_za_litr), ...] posortowane chronologicznie,
    "stacje": [{"nazwa","srednia_cena","liczba_tankowan","ostatnia_cena","ostatnia_data"}, ...]
    posortowane rosnąco po średniej cenie, "najtansza": pierwszy element stacje albo None}."""
    if not auto_id:
        return {"punkty": [], "stacje": [], "najtansza": None}

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT data, kwota, litry, stacja FROM tankowania WHERE auto_id=? AND litry > 0",
            (auto_id,)
        )
        wiersze = c.fetchall()

        dane = []
    for data_str, kwota, litry, stacja in wiersze:
        litry_f = float(litry or 0)
        if litry_f <= 0:
            continue
        cena = float(kwota or 0) / litry_f
        d = parsuj_date(data_str)
        dane.append((d, data_str, cena, " ".join((stacja or "").split())))
    dane.sort(key=lambda x: x[0])  # chronologicznie po sparsowanej dacie, nie tekście

    punkty = []
    wg_stacji = {}
    for d, data_str, cena, stacja in dane:
        punkty.append((data_str, cena))
        # Grupujemy po kluczu znormalizowanym, nie po dosłownej pisowni —
        # inaczej 'Orlen' i 'orlen' to dwie osobne pozycje w rankingu.
        klucz = klucz_stacji(stacja)
        if not klucz:
            continue
        wpis = wg_stacji.setdefault(klucz, {
            "nazwa": stacja, "suma_cen": 0.0, "liczba_tankowan": 0,
            "ostatnia_cena": None, "ostatnia_data": None,
            "_ostatnia_data_obj": None, "_warianty": {},
        })
        wpis["_warianty"][stacja] = wpis["_warianty"].get(stacja, 0) + 1
        wpis["suma_cen"] += cena
        wpis["liczba_tankowan"] += 1
        if wpis["_ostatnia_data_obj"] is None or d >= wpis["_ostatnia_data_obj"]:
            wpis["_ostatnia_data_obj"] = d
            wpis["ostatnia_cena"] = cena
            wpis["ostatnia_data"] = data_str

    stacje = []
    for wpis in wg_stacji.values():
        wpis["srednia_cena"] = wpis["suma_cen"] / wpis["liczba_tankowan"]
        # Do wyświetlenia bierzemy najczęściej używaną pisownię z grupy.
        wpis["nazwa"] = max(wpis["_warianty"].items(), key=lambda kv: (kv[1], kv[0]))[0]
        del wpis["suma_cen"], wpis["_ostatnia_data_obj"], wpis["_warianty"]
        stacje.append(wpis)
    stacje.sort(key=lambda s: s["srednia_cena"])

    return {"punkty": punkty, "stacje": stacje, "najtansza": stacje[0] if stacje else None}

def pobierz_podzial_kosztow(auto_id, rok, miesiac):
    """Zestawienie 'kto ile wydał / przejechał' dla współdzielonego pojazdu w
    danym miesiącu, na podstawie kolumny dodane_przez. Zwraca listę słowników
    posortowaną malejąco po sumie wydatków:
    [{"osoba", "paliwo", "serwis", "inne", "razem", "dystans_km", "tankowania"}, ...]
    Uwaga: dystans_km to suma pola 'dystans' z tankowań DODANYCH przez daną
    osobę w tym miesiącu — to przybliżenie ('kto tankował po ilu km'), nie
    dokładny pomiar tego, kto faktycznie siedział za kierownicą. Wpisy bez
    przypisanej osoby (sprzed tej funkcji) trafiają pod 'Nieprzypisane'."""
    if not auto_id:
        return []

    prefiks = f"{rok:04d}-{miesiac:02d}"
    osoby = {}

    def wpis(nazwa):
        nazwa = (nazwa or "Nieprzypisane").strip() or "Nieprzypisane"
        return osoby.setdefault(nazwa, {"osoba": nazwa, "paliwo": 0.0, "serwis": 0.0, "inne": 0.0, "dystans_km": 0.0, "tankowania": 0})

    with polacz_baze() as conn:
        c = conn.cursor()

        c.execute("SELECT data, kwota, dystans, dodane_przez FROM tankowania WHERE auto_id=?", (auto_id,))
        for data, kwota, dystans, osoba in c.fetchall():
            d = parsuj_date(data)
            if d == datetime.min.date() or f"{d.year:04d}-{d.month:02d}" != prefiks:
                continue
            w = wpis(osoba)
            w["paliwo"] += float(kwota or 0)
            w["dystans_km"] += float(dystans or 0)
            w["tankowania"] += 1

        c.execute(
            "SELECT h.data, h.cena, h.dodane_przez FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE z.auto_id=? AND h.wizyta_id IS NULL", (auto_id,)
        )
        for data, cena, osoba in c.fetchall():
            d = parsuj_date(data)
            if d == datetime.min.date() or f"{d.year:04d}-{d.month:02d}" != prefiks:
                continue
            wpis(osoba)["serwis"] += float(cena or 0)

        c.execute("SELECT data, koszt_calkowity, dodane_przez FROM wizyty WHERE auto_id=?", (auto_id,))
        for data, koszt, osoba in c.fetchall():
            d = parsuj_date(data)
            if d == datetime.min.date() or f"{d.year:04d}-{d.month:02d}" != prefiks:
                continue
            wpis(osoba)["serwis"] += float(koszt or 0)

        c.execute("SELECT data, kwota, dodane_przez FROM inne_koszty WHERE auto_id=?", (auto_id,))
        for data, kwota, osoba in c.fetchall():
            d = parsuj_date(data)
            if d == datetime.min.date() or f"{d.year:04d}-{d.month:02d}" != prefiks:
                continue
            wpis(osoba)["inne"] += float(kwota or 0)

    wynik = list(osoby.values())
    for w in wynik:
        w["razem"] = w["paliwo"] + w["serwis"] + w["inne"]
    wynik.sort(key=lambda w: w["razem"], reverse=True)
    return wynik

# Zapytanie kwotowe rozpoznajemy WPROST w polu wyszukiwarki — bez dodatkowych
# kontrolek, tak jak „>1000” czy „200-500” pisze się w arkuszu kalkulacyjnym.
# Sam tekst dalej działa jak dotąd; kwota to tylko dodatkowa ścieżka.
_WZORZEC_ZAKRESU = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(?:-|–|—|\.\.|do)\s*(\d+(?:[.,]\d+)?)$")
_WZORZEC_POROWNANIA = re.compile(r"^(>=|<=|>|<|od|do)\s*(\d+(?:[.,]\d+)?)$", re.IGNORECASE)
_WZORZEC_LICZBY = re.compile(r"^(\d+(?:[.,]\d+)?)$")

# Tolerancja dla „szukam kwoty około tyle”: paragon rzadko pamięta się co do
# grosza, więc samo „450” łapie 441–459 zamiast wyłącznie równych 450.
TOLERANCJA_KWOTY = 0.02


def _na_liczbe(tekst):
    try:
        return float(str(tekst).replace("\xa0", "").replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def parsuj_zapytanie_kwotowe(zapytanie):
    """Rozpoznaje zapytanie o kwotę i zwraca (min, max, opis) albo None.

    Obsługiwane formy: „450” (±2%), „>1000”, „>=1000”, „<50”, „<=50”,
    „200-500” (też z półpauzą, „..” i słowem „do”), „od 200”, „do 500”.
    """
    tekst = " ".join(str(zapytanie or "").split())
    if not tekst:
        return None

    dopasowanie = _WZORZEC_ZAKRESU.match(tekst)
    if dopasowanie:
        a, b = _na_liczbe(dopasowanie.group(1)), _na_liczbe(dopasowanie.group(2))
        if a is None or b is None:
            return None
        dolna, gorna = min(a, b), max(a, b)
        return (dolna, gorna, f"kwota od {formatuj_liczba_eksport(dolna, 2)} do {formatuj_liczba_eksport(gorna, 2)}")

    dopasowanie = _WZORZEC_POROWNANIA.match(tekst)
    if dopasowanie:
        operator = dopasowanie.group(1).lower()
        wartosc = _na_liczbe(dopasowanie.group(2))
        if wartosc is None:
            return None
        if operator in (">", ">=", "od"):
            return (wartosc, None, f"kwota od {formatuj_liczba_eksport(wartosc, 2)}")
        return (None, wartosc, f"kwota do {formatuj_liczba_eksport(wartosc, 2)}")

    dopasowanie = _WZORZEC_LICZBY.match(tekst)
    if dopasowanie:
        wartosc = _na_liczbe(dopasowanie.group(1))
        if wartosc is None:
            return None
        margines = max(wartosc * TOLERANCJA_KWOTY, 0.5)
        return (wartosc - margines, wartosc + margines,
                f"kwota około {formatuj_liczba_eksport(wartosc, 2)}")

    return None


def _w_zakresie(wartosc, dolna, gorna):
    if wartosc is None:
        return False
    try:
        wartosc = float(wartosc)
    except (TypeError, ValueError):
        return False
    if dolna is not None and wartosc < dolna - 1e-9:
        return False
    if gorna is not None and wartosc > gorna + 1e-9:
        return False
    return True


def wyszukiwanie_po_kwocie(auto_id, dolna, gorna):
    """Przeszukuje WSZYSTKIE kwoty pojazdu: tankowania, wpisy serwisowe, wizyty,
    inne koszty, ceny w magazynie i oponach, szacunki z listy Do zrobienia oraz
    wydatki cykliczne. Zwraca ten sam kształt wyników, co globalne_wyszukiwanie."""
    if not auto_id or (dolna is None and gorna is None):
        return []

    waluta = pobierz_walute()
    wyniki = []

    def dodaj(typ, tytul, kwota, opis, data, trasa, **extra):
        if not _w_zakresie(kwota, dolna, gorna):
            return
        pelny_opis = f"{formatuj_liczba_eksport(kwota, 2)} {waluta}"
        if opis:
            pelny_opis += f" • {opis}"
        wpis = {"typ": typ, "tytul": tytul, "opis": pelny_opis, "data": data or "", "trasa": trasa}
        wpis.update(extra)
        wyniki.append(wpis)

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("SELECT id, data, kwota, litry, stacja FROM tankowania WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            opis = f"{formatuj_liczba_eksport(r['litry'], 1)} L"
            if r["stacja"]:
                opis += f" • {r['stacja']}"
            dodaj("Tankowanie", r["stacja"] or "Tankowanie", r["kwota"], opis,
                  r["data"], f"/tankowanie/edytuj/{r['id']}")

        c.execute(
            "SELECT h.id, h.data, h.cena, h.wykonawca, z.nazwa FROM historia h "
            "JOIN zadania z ON h.zadanie_id=z.id WHERE z.auto_id=? AND h.wizyta_id IS NULL",
            (auto_id,)
        )
        for r in c.fetchall():
            dodaj("Serwis", str(r["nazwa"]), r["cena"], r["wykonawca"] or "",
                  r["data"], f"/wpis/edytuj/{r['id']}")

        c.execute(
            "SELECT w.id, w.data, w.koszt_calkowity, w.wykonawca, "
            "GROUP_CONCAT(z.nazwa, ', ') AS czesci FROM wizyty w "
            "LEFT JOIN historia h ON h.wizyta_id=w.id LEFT JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE w.auto_id=? GROUP BY w.id",
            (auto_id,)
        )
        for r in c.fetchall():
            opis = str(r["czesci"] or "Brak podpiętych części")
            if r["wykonawca"]:
                opis += f" • {r['wykonawca']}"
            dodaj("Wizyta zbiorcza", "Wizyta w warsztacie", r["koszt_calkowity"], opis,
                  r["data"], f"/wizyty/edytuj/{r['id']}")

        c.execute("SELECT id, data, nazwa, kwota, kategoria, tagi FROM inne_koszty WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            dodaj("Inny koszt", str(r["nazwa"] or "Koszt"), r["kwota"],
                  str(r["kategoria"] or r["tagi"] or ""), r["data"], f"/inne/edytuj/{r['id']}")

        c.execute("SELECT id, nazwa, cena, ilosc, jednostka FROM magazyn_czesci WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            dodaj("Magazyn", str(r["nazwa"]), r["cena"],
                  f"{formatuj_liczba_eksport(r['ilosc'], 2)} {r['jednostka'] or 'szt'}", "", "/magazyn")

        c.execute("SELECT id, sezon, rozmiar, marka_model, cena, data_zakupu FROM zestawy_opon WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            opis = str(r["rozmiar"] or "")
            if r["marka_model"]:
                opis += f" • {r['marka_model']}" if opis else str(r["marka_model"])
            dodaj("Opony", f"Zestaw: {r['sezon']}", r["cena"], opis, r["data_zakupu"], "/magazyn")

        c.execute("SELECT id, tytul, szacowany_koszt, termin, priorytet FROM do_zrobienia WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            dodaj("Do zrobienia", str(r["tytul"]), r["szacowany_koszt"],
                  f"szacunek • {r['priorytet'] or 'bez priorytetu'}",
                  r["termin"], f"/do-zrobienia/edytuj/{r['id']}")

        c.execute("SELECT id, nazwa, kwota, okres_dni, nastepna_data, czy_koszt FROM wydatki_cykliczne WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            if not r["czy_koszt"]:
                continue
            dodaj("Wydatek cykliczny", str(r["nazwa"]), r["kwota"],
                  f"co {int(r['okres_dni'] or 0)} dni", r["nastepna_data"], "__wydatki_cykliczne__")

    wyniki.sort(key=lambda w: parsuj_date(w["data"]), reverse=True)
    return wyniki


def skrot_notatki(tekst, maks=60):
    """Notatka w jednej linii wyniku wyszukiwania — bez tego długa uwaga
    rozpychałaby kartę wyniku i zasłaniała resztę opisu."""
    tekst = " ".join(str(tekst or "").split())
    if not tekst:
        return ""
    return tekst if len(tekst) <= maks else tekst[:maks - 1].rstrip() + "…"

def globalne_wyszukiwanie(auto_id, zapytanie):
    """Przeszukuje jednocześnie tankowania, historię serwisową, wizyty zbiorcze,
    inne koszty, notatki wpisów oraz listę Do zrobienia BIEŻĄCEGO pojazdu. Używane przez widok
    /szukaj — jedną wspólną wyszukiwarkę dostępną z paska głównego, w odróżnieniu
    od lokalnych pól filtruj_* działających tylko na już wczytanej liście.
    Zwraca listę słowników {typ, tytul, opis, data, trasa}, posortowaną malejąco
    po dacie (nierozpoznane daty lądują na końcu)."""
    if not auto_id or not zapytanie or not zapytanie.strip():
        return []

    # Zapytanie wyglądające na kwotę („450”, „>1000”, „200-500”) idzie zupełnie
    # inną ścieżką: porównujemy liczby, a nie tekst. Bez tego „450” trafiało
    # tylko tam, gdzie ten ciąg przypadkiem był w dacie albo nazwie.
    zakres = parsuj_zapytanie_kwotowe(zapytanie)
    if zakres:
        return wyszukiwanie_po_kwocie(auto_id, zakres[0], zakres[1])

    q = f"%{zapytanie.strip()}%"
    wyniki = []

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute(
            "SELECT id, data, przebieg, stacja, tagi, notatka FROM tankowania "
            "WHERE auto_id=? AND (stacja LIKE ? OR tagi LIKE ? OR data LIKE ? OR notatka LIKE ?)",
            (auto_id, q, q, q, q)
        )
        for r in c.fetchall():
            opis = f"{int(r['przebieg'] or 0)} km" + (f" • {r['stacja']}" if r["stacja"] else "")
            if r["notatka"]:
                opis += f" • {skrot_notatki(r['notatka'])}"
            wyniki.append({
                "typ": "Tankowanie", "tytul": r["stacja"] or "Tankowanie", "opis": opis,
                "data": r["data"], "trasa": f"/tankowanie/edytuj/{r['id']}",
            })

        c.execute(
            "SELECT h.id, h.data, h.przebieg, h.wykonawca, h.kategoria, h.notatka, z.nazwa "
            "FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE z.auto_id=? AND h.wizyta_id IS NULL AND "
            "(z.nazwa LIKE ? OR h.wykonawca LIKE ? OR h.kategoria LIKE ? OR h.data LIKE ? OR h.notatka LIKE ?)",
            (auto_id, q, q, q, q, q)
        )
        for r in c.fetchall():
            opis = f"{int(r['przebieg'] or 0)} km" + (f" • {r['wykonawca']}" if r["wykonawca"] else "")
            if r["notatka"]:
                opis += f" • {skrot_notatki(r['notatka'])}"
            wyniki.append({
                "typ": "Serwis", "tytul": str(r["nazwa"]), "opis": opis,
                "data": r["data"], "trasa": f"/wpis/edytuj/{r['id']}",
            })

        c.execute(
            "SELECT id, nazwa, interwal_km, interwal_miesiace FROM zadania "
            "WHERE auto_id=? AND nazwa LIKE ?",
            (auto_id, q)
        )
        for r in c.fetchall():
            bits = []
            if r["interwal_km"]:
                bits.append(f"co {int(r['interwal_km'])} km")
            if r["interwal_miesiace"]:
                bits.append(f"co {int(r['interwal_miesiace'])} mies.")
            opis = " • ".join(bits) if bits else "Brak ustawionego interwału"
            wyniki.append({
                "typ": "Podzespół", "tytul": str(r["nazwa"]), "opis": opis,
                "data": "", "trasa": f"/historia/{r['id']}",
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
            "SELECT id, data, nazwa, kategoria, tagi, notatka FROM inne_koszty "
            "WHERE auto_id=? AND (nazwa LIKE ? OR kategoria LIKE ? OR tagi LIKE ? OR data LIKE ? OR notatka LIKE ?)",
            (auto_id, q, q, q, q, q)
        )
        for r in c.fetchall():
            opis = str(r["kategoria"] or r["tagi"] or "Inny koszt")
            if r["notatka"]:
                opis += f" • {skrot_notatki(r['notatka'])}"
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

        # Odczyty licznika trafiają do wyników WYŁĄCZNIE przez notatkę: sam
        # „12.03.2026 • 145 000 km” nie niesie treści, po której ktoś szuka,
        # ale zostawiona przy nim uwaga („licznik po wymianie zegarów”) — owszem.
        c.execute(
            "SELECT id, data, przebieg, notatka FROM odczyty_przebiegu "
            "WHERE auto_id=? AND notatka LIKE ?",
            (auto_id, q)
        )
        for r in c.fetchall():
            wyniki.append({
                "typ": "Odczyt licznika",
                "tytul": f"{formatuj_liczba_eksport(r['przebieg'] or 0, 0)} km",
                "opis": skrot_notatki(r["notatka"]),
                "data": r["data"], "trasa": "/przebieg",
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

        # NOWE: Warsztaty
        c.execute(
            "SELECT id, nazwa, telefon, adres, notatki FROM warsztaty "
            "WHERE auto_id=? AND (nazwa LIKE ? OR telefon LIKE ? OR adres LIKE ? OR notatki LIKE ?)",
            (auto_id, q, q, q, q)
        )
        for r in c.fetchall():
            opis = str(r["adres"] or "") + (f" • {r['telefon']}" if r["telefon"] else "")
            wyniki.append({
                "typ": "Warsztat", "tytul": str(r["nazwa"]), "opis": opis or "Brak telefonu / adresu",
                "data": "", "trasa": "/wizyty",
            })

        # NOWE: Wydatki cykliczne
        c.execute(
            "SELECT id, nazwa, kwota, okres_dni, nastepna_data, czy_koszt FROM wydatki_cykliczne "
            "WHERE auto_id=? AND nazwa LIKE ?",
            (auto_id, q)
        )
        for r in c.fetchall():
            if r["czy_koszt"]:
                opis = f"{formatuj_liczba_eksport(r['kwota'], 2)} {pobierz_walute()} • co {int(r['okres_dni'] or 0)} dni"
            else:
                opis = f"Przypomnienie • co {int(r['okres_dni'] or 0)} dni"
            wyniki.append({
                "typ": "Wydatek cykliczny", "tytul": str(r["nazwa"]), "opis": opis,
                "data": r["nastepna_data"] or "", "trasa": "__wydatki_cykliczne__",
            })

        # NOWE: Podzespoły — samodzielna kategoria, bo świeżo dodany podzespół bez
        # ŻADNEJ historii wymiany (powyższy JOIN wymaga wpisu w historii) był dotąd
        # całkowicie niewidoczny dla wyszukiwarki.
        c.execute(
            "SELECT id, nazwa FROM zadania WHERE auto_id=? AND nazwa LIKE ?",
            (auto_id, q)
        )
        for r in c.fetchall():
            wyniki.append({
                "typ": "Podzespół", "tytul": str(r["nazwa"]), "opis": "Śledzony podzespół",
                "data": "", "trasa": f"/historia/{r['id']}",
            })

    wyniki.sort(key=lambda w: parsuj_date(w["data"]), reverse=True)

    return wyniki

def pobierz_dane_timeline(auto_id):
    """Zbiorcza, chronologiczna lista zdarzeń pojazdu ze wszystkich modułów
    (tankowania, historia serwisowa, wizyty zbiorcze, inne koszty, galeria
    karoserii, odczyty przebiegu) — używana przez widok /timeline ("dziennik
    życia auta"). Wpisy historii powiązane z wizytą zbiorczą są pomijane
    (reprezentuje je already sama wizyta), analogicznie do eksportu danych.
    Zwraca listę krotek: (id_timeline, typ, data, tytul, opis, kwota, zalacznik,
    trasa, dodane_przez, notatka). 'dodane_przez' zasila filtr autorstwa przy
    pojeździe współdzielonym; zdjęcia karoserii nie mają tej kolumny, więc trafia
    tam None. 'notatka' to krótka uwaga wpisu — dziennik życia auta bez niej
    gubiłby dokładnie ten kontekst, po który się do niego wraca."""
    if not auto_id:
        return []

    zdarzenia = []

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute(
            "SELECT id, data, przebieg, litry, kwota, stacja, do_pelna, zalacznik, dodane_przez, notatka "
            "FROM tankowania WHERE auto_id=?", (auto_id,)
        )
        for r in c.fetchall():
            opis = f"{formatuj_liczba_eksport(r['litry'], 1)} L" + (f" • {r['stacja']}" if r['stacja'] else "")
            opis += f" • {int(r['przebieg'] or 0)} km"
            zdarzenia.append((
                f"tankowanie_{r['id']}", "Tankowanie", r["data"],
                "Tankowanie" + (" (do pełna)" if r["do_pelna"] else ""), opis,
                float(r["kwota"] or 0), r["zalacznik"], f"/tankowanie/edytuj/{r['id']}",
                r["dodane_przez"], r["notatka"],
            ))

        c.execute(
            "SELECT h.id, h.data, h.przebieg, h.cena, h.wykonawca, z.nazwa, h.zalacznik, h.dodane_przez, h.notatka "
            "FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE z.auto_id=? AND h.wizyta_id IS NULL", (auto_id,)
        )
        for r in c.fetchall():
            opis = f"{int(r['przebieg'] or 0)} km" + (f" • {r['wykonawca']}" if r["wykonawca"] else "")
            zdarzenia.append((
                f"historia_{r['id']}", "Serwis", r["data"],
                str(r["nazwa"]), opis,
                float(r["cena"] or 0), r["zalacznik"], f"/wpis/edytuj/{r['id']}",
                r["dodane_przez"], r["notatka"],
            ))

        c.execute(
            "SELECT w.id, w.data, w.przebieg, w.wykonawca, w.koszt_calkowity, w.zalacznik, w.dodane_przez, w.notatki, "
            "GROUP_CONCAT(z.nazwa, ', ') as czesci "
            "FROM wizyty w LEFT JOIN historia h ON h.wizyta_id=w.id LEFT JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE w.auto_id=? GROUP BY w.id", (auto_id,)
        )
        for r in c.fetchall():
            opis = str(r["czesci"] or "Brak podpiętych części") + (f" • {r['wykonawca']}" if r["wykonawca"] else "")
            zdarzenia.append((
                f"wizyta_{r['id']}", "Wizyta zbiorcza", r["data"],
                "Wizyta w warsztacie", opis,
                float(r["koszt_calkowity"] or 0), r["zalacznik"], f"/wizyty/edytuj/{r['id']}",
                r["dodane_przez"], r["notatki"],
            ))

        c.execute("SELECT id, data, nazwa, kategoria, kwota, zalacznik, dodane_przez, notatka FROM inne_koszty WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            zdarzenia.append((
                f"inne_{r['id']}", "Inny koszt", r["data"],
                str(r["nazwa"] or "Koszt"), str(r["kategoria"] or ""),
                float(r["kwota"] or 0), r["zalacznik"], f"/inne/edytuj/{r['id']}",
                r["dodane_przez"], r["notatka"],
            ))

        c.execute("SELECT id, data, strefa, typ_porownania, opis, zalacznik FROM zdjecia_karoserii WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            opis = str(r["typ_porownania"]) if r["typ_porownania"] and r["typ_porownania"] != "Brak" else (r["opis"] or "")
            zdarzenia.append((
                f"zdjecie_{r['id']}", "Zdjęcie karoserii", r["data"],
                f"Zdjęcie: {r['strefa']}", opis,
                None, r["zalacznik"], f"/karoseria/edytuj/{r['id']}", None, r["opis"],
            ))

        c.execute("SELECT id, data, przebieg, notatka FROM odczyty_przebiegu WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            zdarzenia.append((
                f"odczyt_{r['id']}", "Odczyt przebiegu", r["data"],
                "Odczyt licznika", f"{int(r['przebieg'] or 0)} km",
                None, None, "/przebieg", None, r["notatka"],
            ))

    return zdarzenia

def aktualizuj_wiele_zdjec_karoserii(ids_list, strefa=None, typ_porownania=None, opis=None):
    """Masowa edycja wspólnych pól (strefa / typ zdjęcia / opis) dla wielu zdjęć
    karoserii naraz — używane przez zbiorczą edycję zaznaczonych zdjęć w galerii.
    Pole pozostawione jako None NIE jest zmieniane (stąd pusty opis trzeba
    przekazać jako pusty string, jeśli faktycznie ma zostać wyczyszczony)."""
    if not ids_list:
        return 0

    przypisania, wartosci = [], []
    if strefa is not None:
        przypisania.append("strefa=?")
        wartosci.append(strefa)
    if typ_porownania is not None:
        przypisania.append("typ_porownania=?")
        wartosci.append(typ_porownania)
    if opis is not None:
        przypisania.append("opis=?")
        wartosci.append(opis)

    if not przypisania:
        return 0

    placeholders = ",".join("?" for _ in ids_list)
    with polacz_baze() as conn:
        conn.execute(
            f"UPDATE zdjecia_karoserii SET {', '.join(przypisania)} WHERE id IN ({placeholders})",
            tuple(wartosci) + tuple(ids_list)
        )
    return len(ids_list)

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

def zarejestruj_nagrobek(tabela, zdalny_id):
    """Zapamiętuje lokalnie, że wiersz o danym zdalne_id (z tabeli 'tabela') został
    usunięty na tym urządzeniu — sam rekord znika z lokalnej bazy od razu (jak
    dotychczas), ale info o usunięciu trzeba jeszcze wypchnąć na serwer przy
    najbliższej synchronizacji (patrz sync._wypchnij_nagrobki)."""
    if not zdalny_id:
        return
    with polacz_baze() as conn:
        conn.execute("INSERT INTO zdalne_nagrobki (tabela, zdalny_id) VALUES (?,?)", (tabela, zdalny_id))

def usun_nagrobek(zdalny_id):
    """Kasuje nagrobek — wywoływane, gdy usunięcie zostaje cofnięte (Undo), żeby
    NIE propagowało się na serwer."""
    if not zdalny_id:
        return
    with polacz_baze() as conn:
        conn.execute("DELETE FROM zdalne_nagrobki WHERE zdalny_id=?", (zdalny_id,))

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

    zdalny_id_usuniety = dane.get("zdalne_id")

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

    # Wpis serwisowy może mieć podpięte części z magazynu — oddajemy je na stan,
    # zanim CASCADE skasuje powiązania (patrz _zdejmij_powiazania_czesci_wpisow).
    czesci_wpisu = _zdejmij_powiazania_czesci_wpisow([rekord_id]) if tabela == "historia" else []

    with polacz_baze() as conn:
        conn.execute(f"DELETE FROM {tabela} WHERE id=?", (rekord_id,))

    if zdalny_id_usuniety:
        zarejestruj_nagrobek(tabela, zdalny_id_usuniety)
    for w in czesci_wpisu:
        if w.get("zdalne_id"):
            zarejestruj_nagrobek("historia_czesci_magazynu", w["zdalne_id"])

    stan = {"cofniete": False, "trwale_usuniete": False}

    def cofnij():
        if stan["cofniete"] or stan["trwale_usuniete"]:
            return
        stan["cofniete"] = True

        if zdalny_id_usuniety:
            usun_nagrobek(zdalny_id_usuniety)
        for w in czesci_wpisu:
            if w.get("zdalne_id"):
                usun_nagrobek(w["zdalne_id"])

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
            kursor = conn.cursor()
            kursor.execute(f"INSERT INTO {tabela} ({nazwy}) VALUES ({placeholders})", wartosci)
            nowe_id = kursor.lastrowid
        _przywroc_powiazania_czesci_wpisow(czesci_wpisu, {rekord_id: nowe_id})

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

    zdalne_id_usuniete = [d.get("zdalne_id") for d in dane_lista if d.get("zdalne_id")]

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

    # Jak przy usuwaniu pojedynczego wpisu — części wracają na stan magazynu,
    # zamiast zniknąć cicho razem z powiązaniem skasowanym przez CASCADE.
    czesci_wpisow = _zdejmij_powiazania_czesci_wpisow(ids_list) if tabela == "historia" else []

    with polacz_baze() as conn:
        conn.execute(f"DELETE FROM {tabela} WHERE id IN ({placeholders})", tuple(ids_list))

    for zid in zdalne_id_usuniete:
        zarejestruj_nagrobek(tabela, zid)
    for w in czesci_wpisow:
        if w.get("zdalne_id"):
            zarejestruj_nagrobek("historia_czesci_magazynu", w["zdalne_id"])

    stan = {"cofniete": False, "trwale_usuniete": False}

    def cofnij():
        if stan["cofniete"] or stan["trwale_usuniete"]:
            return
        stan["cofniete"] = True

        for zid in zdalne_id_usuniete:
            usun_nagrobek(zid)
        for w in czesci_wpisow:
            if w.get("zdalne_id"):
                usun_nagrobek(w["zdalne_id"])

        for tmp, oryg in sciezki_tymczasowe:
            if os.path.exists(tmp):
                try:
                    shutil.move(tmp, oryg)
                except Exception:
                    pass

        kolumny_bez_id = [k for k in kolumny if k != "id"]
        placeholders_ins = ",".join("?" for _ in kolumny_bez_id)
        nazwy = ",".join(kolumny_bez_id)

        mapa_id = {}
        with polacz_baze() as conn:
            kursor = conn.cursor()
            for dane in dane_lista:
                wartosci = tuple(dane[k] for k in kolumny_bez_id)
                kursor.execute(f"INSERT INTO {tabela} ({nazwy}) VALUES ({placeholders_ins})", wartosci)
                if dane.get("id") is not None:
                    mapa_id[dane["id"]] = kursor.lastrowid
        _przywroc_powiazania_czesci_wpisow(czesci_wpisow, mapa_id)

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

def _upewnij_folder_kosza():
    os.makedirs(FOLDER_KOSZ, exist_ok=True)
    return FOLDER_KOSZ

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

        cur.execute("INSERT INTO wizyty (auto_id, data, przebieg, wykonawca, koszt_calkowity, notatki, dodane_przez) VALUES (?,?,?,?,?,?,?)",
                    (auto_id, dzis, prz, "", suma_kosztow, notatki, pobierz_moje_imie()))
        wizyta_id = cur.lastrowid

        for tytul, koszt, zadanie_id in pozycje:
            czy_opony = False
            if not zadanie_id and utworz_podzespoly:
                # Dopasowanie po klucz_nazwy, więc „Filtr oleju” z listy trafia
                # w istniejący „🛢️ filtr oleju” zamiast zakładać drugi podzespół.
                klucz_tytulu = klucz_nazwy(tytul)
                cur.execute("SELECT id, nazwa, dotyczy_opon FROM zadania WHERE auto_id=?", (auto_id,))
                istniejacy = next((r for r in cur.fetchall() if klucz_nazwy(r["nazwa"]) == klucz_tytulu), None)

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
                cur.execute("INSERT INTO historia (wizyta_id, zadanie_id, data, przebieg, cena, wykonawca, kategoria, dodane_przez) VALUES (?,?,?,?,?,?,?,?)",
                            (wizyta_id, zadanie_id, dzis, prz, koszt or 0.0, "", kat, pobierz_moje_imie()))

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

def pobierz_pozycje_wizyty(wizyta_id):
    """Pozycje wizyty nadające się do zwrotu na listę Do zrobienia — czyli wpisy
    historii podpięte pod tę wizytę, razem z nazwą podzespołu i ceną."""
    if not wizyta_id:
        return []
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT h.id, h.cena, h.zadanie_id, z.nazwa "
            "FROM historia h JOIN zadania z ON h.zadanie_id = z.id "
            "WHERE h.wizyta_id=? ORDER BY z.nazwa",
            (wizyta_id,)
        )
        return [
            {"id": r["id"], "nazwa": str(r["nazwa"] or "Pozycja"),
             "cena": float(r["cena"] or 0.0), "zadanie_id": r["zadanie_id"]}
            for r in c.fetchall()
        ]

def zwroc_pozycje_wizyty_do_zrobienia(wizyta_id, historia_ids):
    """Zdejmuje wskazane pozycje z wizyty i odkłada je z powrotem na listę
    Do zrobienia — droga powrotna do utworz_wizyte_z_do_zrobienia, potrzebna
    gdy część została zamówiona, ale nie zamontowana przy tej samej okazji.

    Cena pozycji wraca jako szacowany koszt i jest ODEJMOWANA od kosztu
    całkowitego wizyty — w wizycie zostaje tylko to, co faktycznie zrobiono.
    Zwraca słownik zgodny z utils.pokaz_komunikat_cofnij, wzbogacony o "liczba"
    i "nazwy" zwróconych pozycji.
    """
    if not wizyta_id or not historia_ids:
        return None

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("SELECT auto_id, data, wykonawca, koszt_calkowity FROM wizyty WHERE id=?", (wizyta_id,))
        wiz = c.fetchone()
        if not wiz:
            return None
        auto_id = wiz["auto_id"]
        koszt_przed = float(wiz["koszt_calkowity"] or 0.0)

        c.execute("PRAGMA table_info(historia)")
        kolumny_historii = [r["name"] for r in c.fetchall()]

        placeholders = ",".join("?" for _ in historia_ids)
        c.execute(
            f"SELECT h.*, z.nazwa AS nazwa_zadania FROM historia h "
            f"JOIN zadania z ON h.zadanie_id = z.id "
            f"WHERE h.wizyta_id=? AND h.id IN ({placeholders})",
            (wizyta_id, *historia_ids)
        )
        wiersze = c.fetchall()
        if not wiersze:
            return None

        historia_dane = [{k: r[k] for k in kolumny_historii} for r in wiersze]
        nazwy = [str(r["nazwa_zadania"] or "Pozycja") for r in wiersze]

    suma_zwrocona = sum(float(d.get("cena") or 0.0) for d in historia_dane)
    dzis = datetime.now().strftime("%d.%m.%Y")
    opis_zrodla = f"Zwrócone z wizyty z {wiz['data']}"
    if wiz["wykonawca"]:
        opis_zrodla += f" ({wiz['wykonawca']})"

    # Załączniki (paragony) zdejmowanych wpisów historii chowamy tak jak przy
    # każdym innym usuwaniu z opcją cofnięcia — do_zrobienia nie ma kolumny na
    # załącznik, więc plik czeka w folderze odroczonym na ewentualne cofnięcie.
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

    # Zwracana pozycja znika z historii, więc jej części wracają na stan magazynu.
    czesci_wpisow = _zdejmij_powiazania_czesci_wpisow([d["id"] for d in historia_dane])

    nowe_do_zrobienia_ids = []
    with polacz_baze() as conn:
        c = conn.cursor()
        for d, nazwa in zip(historia_dane, nazwy):
            c.execute(
                "INSERT INTO do_zrobienia (auto_id, tytul, opis, priorytet, szacowany_koszt, "
                "zadanie_id, wykonane, data_utworzenia) VALUES (?,?,?,?,?,?,0,?)",
                (auto_id, nazwa, opis_zrodla, "Średni", float(d.get("cena") or 0.0),
                 d.get("zadanie_id"), dzis)
            )
            nowe_do_zrobienia_ids.append(c.lastrowid)

        c.execute(f"DELETE FROM historia WHERE id IN ({placeholders})", tuple(historia_ids))
        c.execute(
            "UPDATE wizyty SET koszt_calkowity = MAX(0, koszt_calkowity - ?) WHERE id=?",
            (suma_zwrocona, wizyta_id)
        )

    zdalne_id_historii = [d.get("zdalne_id") for d in historia_dane if d.get("zdalne_id")]
    for zid in zdalne_id_historii:
        zarejestruj_nagrobek("historia", zid)
    for w in czesci_wpisow:
        if w.get("zdalne_id"):
            zarejestruj_nagrobek("historia_czesci_magazynu", w["zdalne_id"])

    przelicz_wszystkie_zadania(auto_id)

    stan = {"cofniete": False, "sfinalizowane": False}

    def cofnij():
        if stan["cofniete"] or stan["sfinalizowane"]:
            return
        stan["cofniete"] = True

        for zid in zdalne_id_historii:
            usun_nagrobek(zid)
        for w in czesci_wpisow:
            if w.get("zdalne_id"):
                usun_nagrobek(w["zdalne_id"])
        for tmp, oryg in sciezki_tymczasowe:
            if os.path.exists(tmp):
                try:
                    shutil.move(tmp, oryg)
                except Exception:
                    pass

        with polacz_baze() as conn:
            if nowe_do_zrobienia_ids:
                p_dz = ",".join("?" for _ in nowe_do_zrobienia_ids)
                conn.execute(f"DELETE FROM do_zrobienia WHERE id IN ({p_dz})", tuple(nowe_do_zrobienia_ids))
            nazwy_kol = ",".join(kolumny_historii)
            znaki = ",".join("?" for _ in kolumny_historii)
            for d in historia_dane:
                conn.execute(f"INSERT INTO historia ({nazwy_kol}) VALUES ({znaki})",
                             tuple(d[k] for k in kolumny_historii))
            # Koszt całkowity wraca do wartości sprzed zwrotu, a nie przez
            # dodanie sumy — MAX(0, ...) przy odejmowaniu mogło ją przyciąć.
            conn.execute("UPDATE wizyty SET koszt_calkowity=? WHERE id=?", (koszt_przed, wizyta_id))
        # Wpisy historii wracają tu z oryginalnymi ID (kolumny_historii zawierają id)
        _przywroc_powiazania_czesci_wpisow(czesci_wpisow)
        przelicz_wszystkie_zadania(auto_id)

    def finalizuj():
        if stan["cofniete"]:
            return
        stan["sfinalizowane"] = True
        for tmp, _ in sciezki_tymczasowe:
            usun_plik_zalacznika(tmp)

    return {
        "cofnij": cofnij, "finalizuj": finalizuj,
        "liczba": len(historia_dane), "nazwy": nazwy,
        "kwota": suma_zwrocona, "auto_id": auto_id,
    }

def pobierz_tagi(auto_id):
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT id, nazwa, kolor FROM tagi WHERE auto_id=?", (auto_id,))
        return c.fetchall()

def dodaj_tag(auto_id, nazwa, kolor):
    """Dopasowanie po klucz_nazwy, nie po LOWER(nazwa) — dzięki temu „Filtr oleju”,
    „filtr Oleju” i „filtr  oleju ” trafiają w ten sam tag, a nie zakładają trzech."""
    nazwa = normalizuj_nazwe(nazwa)
    if not nazwa:
        return None
    klucz = klucz_nazwy(nazwa)
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT id, nazwa FROM tagi WHERE auto_id=?", (auto_id,))
        for tag_id, istniejaca in c.fetchall():
            if klucz_nazwy(istniejaca) == klucz:
                return tag_id
        c.execute("INSERT INTO tagi (auto_id, nazwa, kolor) VALUES (?, ?, ?)", (auto_id, nazwa, kolor))
        return c.lastrowid

def usun_tag_ze_slownika(auto_id, tag_id, nazwa):
    """Usuwa tag z bazy i wymazuje jego nazwę z rekordów tekstowych we wszystkich tabelach."""
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT zdalne_id FROM tagi WHERE id=?", (tag_id,))
        w = c.fetchone()
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

    if w and w[0]:
        zarejestruj_nagrobek("tagi", w[0])

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
    """Dodaje warsztat per pojazd. Jeśli warsztat o tej samej nazwie (po
    normalizacji: bez wielkości liter, emoji i nadmiarowych spacji) już istnieje,
    zwraca jego id zamiast tworzyć duplikat — analogicznie do dodaj_tag()."""
    nazwa = normalizuj_nazwe(nazwa)
    if not nazwa:
        return None
    klucz = klucz_nazwy(nazwa)
    with polacz_baze() as conn:
        c = conn.cursor()
        # Porównanie po klucz_nazwy zamiast LOWER(nazwa): łapie też spację na
        # końcu i podwójną w środku, na których stare porównanie się wykładało.
        c.execute("SELECT id, nazwa FROM warsztaty WHERE auto_id=?", (auto_id,))
        for w_id, istniejaca in c.fetchall():
            if klucz_nazwy(istniejaca) == klucz:
                return w_id
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
        c = conn.cursor()
        c.execute("SELECT zdalne_id FROM warsztaty WHERE id=?", (warsztat_id,))
        w = c.fetchone()
        conn.execute("DELETE FROM warsztaty WHERE id=?", (warsztat_id,))
    if w and w[0]:
        zarejestruj_nagrobek("warsztaty", w[0])

# ==================== WYDATKI CYKLICZNE ====================

def pobierz_wydatki_cykliczne(auto_id):
    if not auto_id:
        return []
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, nazwa, kwota, okres_dni, nastepna_data, czy_koszt FROM wydatki_cykliczne WHERE auto_id=?",
            (auto_id,)
        )
        wpisy = c.fetchall()
    wpisy.sort(key=lambda w: parsuj_date(w[4]))
    return wpisy

def dodaj_wydatek_cykliczny(auto_id, nazwa, kwota, okres_dni, nastepna_data, czy_koszt=1):
    with polacz_baze() as conn:
        conn.execute(
            "INSERT INTO wydatki_cykliczne (auto_id, nazwa, kwota, okres_dni, nastepna_data, czy_koszt) VALUES (?,?,?,?,?,?)",
            (auto_id, nazwa, kwota, okres_dni, nastepna_data, int(bool(czy_koszt)))
        )

def edytuj_wydatek_cykliczny(wydatek_id, nazwa, kwota, okres_dni, nastepna_data, czy_koszt=1):
    with polacz_baze() as conn:
        conn.execute(
            "UPDATE wydatki_cykliczne SET nazwa=?, kwota=?, okres_dni=?, nastepna_data=?, czy_koszt=? WHERE id=?",
            (nazwa, kwota, okres_dni, nastepna_data, int(bool(czy_koszt)), wydatek_id)
        )

def usun_wydatek_cykliczny(wydatek_id):
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT zdalne_id FROM wydatki_cykliczne WHERE id=?", (wydatek_id,))
        w = c.fetchone()
        conn.execute("DELETE FROM wydatki_cykliczne WHERE id=?", (wydatek_id,))
    if w and w[0]:
        zarejestruj_nagrobek("wydatki_cykliczne", w[0])

def oznacz_zaplacony_wydatek_cykliczny(wydatek_id, auto_id):
    """Dla klasycznego wydatku (czy_koszt=1) tworzy wpis w inne_koszty na podstawie
    wydatku cyklicznego, tak jak dotychczas. Dla samego przypomnienia bez kosztu
    (czy_koszt=0, np. "co miesiąc sprawdź ciśnienie w oponach") NIE dopisuje nic
    do inne_koszty — tylko odnotowuje wykonanie. W obu przypadkach przesuwa
    następny termin o okres_dni od DZISIAJ (nie od starej daty — dzięki temu
    spóźniona pozycja nie generuje serii zaległych powiadomień pod rząd)."""
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT nazwa, kwota, okres_dni, czy_koszt FROM wydatki_cykliczne WHERE id=?", (wydatek_id,))
        w = c.fetchone()
        if not w:
            return
        nazwa, kwota, okres_dni, czy_koszt = w
        dzis = datetime.now()
        if czy_koszt:
            conn.execute(
                "INSERT INTO inne_koszty (auto_id, data, kategoria, nazwa, kwota, dodane_przez) VALUES (?,?,?,?,?,?)",
                (auto_id, dzis.strftime("%d.%m.%Y"), "Cykliczne", nazwa, kwota, pobierz_moje_imie())
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

def aktualizuj_pakiet_wlasny(pakiet_id, nazwa, pozycje_lista):
    """Zmiana nazwy i/lub składu istniejącego własnego pakietu. Nie ruszamy
    zdalny_hash — sync sam wykryje różnicę treści i wypchnie edycję."""
    with polacz_baze() as conn:
        conn.execute(
            "UPDATE pakiety_serwisowe_wlasne SET nazwa=?, pozycje=? WHERE id=?",
            (nazwa, ",".join(pozycje_lista), pakiet_id)
        )

def usun_pakiet_wlasny(pakiet_id):
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT zdalne_id FROM pakiety_serwisowe_wlasne WHERE id=?", (pakiet_id,))
        w = c.fetchone()
        zdalne = w[0] if w else None
        conn.execute("DELETE FROM pakiety_serwisowe_wlasne WHERE id=?", (pakiet_id,))
    # Nagrobek POZA blokiem with — otwiera własne połączenie do tego samego pliku.
    if zdalne:
        zarejestruj_nagrobek("pakiety_serwisowe_wlasne", zdalne)

# Zużycie części z magazynu ma dwa nośniki: wizytę zbiorczą i pojedynczy wpis
# serwisowy. Tabele są lustrzane, więc cała logika (pobranie, oddanie na stan,
# potrącenie) siedzi w jednym rdzeniu sparametryzowanym nazwą tabeli i kolumną
# wiążącą — zamiast dwóch kopii, które z czasem by się rozjechały.
POWIAZANIA_MAGAZYNU = {
    "wizyty": ("wizyta_czesci_magazynu", "wizyta_id"),
    "historia": ("historia_czesci_magazynu", "historia_id"),
}

def _pobierz_uzyte_czesci(zrodlo, rekord_id):
    tabela, kolumna = POWIAZANIA_MAGAZYNU[zrodlo]
    if not rekord_id:
        return []
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(f"SELECT magazyn_id, ilosc_uzyta FROM {tabela} WHERE {kolumna}=?", (rekord_id,))
        return c.fetchall()

def _przywroc_czesci(zrodlo, rekord_id, conn=None):
    """Oddaje do magazynu wykorzystane wcześniej części i usuwa powiązania.
    Zwraca listę zdalne_id usuniętych powiązań — WYWOŁUJĄCY musi je
    zarejestrować jako nagrobki (zarejestruj_nagrobek) DOPIERO PO
    zamknięciu/commicie bieżącej transakcji (conn). Rejestracja w środku
    otwartej transakcji otworzyłaby drugie połączenie do tego samego pliku
    SQLite i mogłaby zakleszczyć bazę."""
    tabela, kolumna = POWIAZANIA_MAGAZYNU[zrodlo]
    usuniete_zdalne_id = []

    def _wykonaj(c):
        cur = c.cursor()
        cur.execute(f"SELECT magazyn_id, ilosc_uzyta, zdalne_id FROM {tabela} WHERE {kolumna}=?", (rekord_id,))
        for magazyn_id, ilosc, zdalne_id in cur.fetchall():
            cur.execute("UPDATE magazyn_czesci SET ilosc = ilosc + ? WHERE id=?", (ilosc, magazyn_id))
            if zdalne_id:
                usuniete_zdalne_id.append(zdalne_id)
        cur.execute(f"DELETE FROM {tabela} WHERE {kolumna}=?", (rekord_id,))

    if conn is not None:
        _wykonaj(conn)
    else:
        with polacz_baze() as conn_local:
            _wykonaj(conn_local)

    return usuniete_zdalne_id

def _rozlicz_czesci(zrodlo, rekord_id, uzyte, conn=None):
    tabela, kolumna = POWIAZANIA_MAGAZYNU[zrodlo]
    if not uzyte:
        return

    def _wykonaj(c):
        cur = c.cursor()
        for magazyn_id, ilosc in uzyte:
            if not ilosc or ilosc <= 0:
                continue
            cur.execute(
                f"INSERT INTO {tabela} ({kolumna}, magazyn_id, ilosc_uzyta) VALUES (?,?,?)",
                (rekord_id, magazyn_id, ilosc)
            )
            cur.execute("UPDATE magazyn_czesci SET ilosc = MAX(0, ilosc - ?) WHERE id=?", (ilosc, magazyn_id))

    if conn is not None:
        _wykonaj(conn)
    else:
        with polacz_baze() as conn_local:
            _wykonaj(conn_local)

# --- Wizyta zbiorcza (nazwy zachowane, bo używa ich formularz wizyty) ---
def pobierz_uzyte_czesci_wizyty(wizyta_id):
    return _pobierz_uzyte_czesci("wizyty", wizyta_id)

def przywroc_czesci_wizyty(wizyta_id, conn=None):
    return _przywroc_czesci("wizyty", wizyta_id, conn)

def rozlicz_czesci_z_magazynu(wizyta_id, uzyte, conn=None):
    return _rozlicz_czesci("wizyty", wizyta_id, uzyte, conn)

# --- Pojedynczy wpis serwisowy (poza wizytą) ---
def pobierz_uzyte_czesci_wpisu(historia_id):
    return _pobierz_uzyte_czesci("historia", historia_id)

def przywroc_czesci_wpisu(historia_id, conn=None):
    return _przywroc_czesci("historia", historia_id, conn)

def rozlicz_czesci_z_magazynu_wpisu(historia_id, uzyte, conn=None):
    return _rozlicz_czesci("historia", historia_id, uzyte, conn)

def _zdejmij_powiazania_czesci_wpisow(historia_ids):
    """Przed skasowaniem wpisów serwisowych oddaje ich części na stan magazynu
    i zwraca zdjęte wiersze powiązań. CASCADE i tak skasowałby te powiązania —
    ale zrobiłby to CICHO, zostawiając sztuki „zużyte” w nieistniejącym już
    wpisie. Zwrócone wiersze pozwalają odtworzyć stan przy cofnięciu."""
    if not historia_ids:
        return []
    placeholders = ",".join("?" for _ in historia_ids)
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("PRAGMA table_info(historia_czesci_magazynu)")
        kolumny = [r["name"] for r in c.fetchall()]
        c.execute(
            f"SELECT * FROM historia_czesci_magazynu WHERE historia_id IN ({placeholders})",
            tuple(historia_ids)
        )
        wiersze = [{k: w[k] for k in kolumny} for w in c.fetchall()]
        if wiersze:
            for w in wiersze:
                c.execute("UPDATE magazyn_czesci SET ilosc = ilosc + ? WHERE id=?",
                          (w["ilosc_uzyta"], w["magazyn_id"]))
            c.execute(
                f"DELETE FROM historia_czesci_magazynu WHERE historia_id IN ({placeholders})",
                tuple(historia_ids)
            )
    return wiersze

def _przywroc_powiazania_czesci_wpisow(wiersze, mapa_historia=None):
    """Odwrotność _zdejmij_...: wstawia powiązania z powrotem (z oryginalnymi ID,
    o ile wolne) i ponownie potrąca sztuki ze stanu magazynu.

    mapa_historia przemapowuje historia_id: ścieżki cofania wstawiają wpis
    serwisowy BEZ oryginalnego id (patrz kolumny_bez_id), więc po przywróceniu
    zwykle ma on nowe ID i powiązanie wskazywałoby w próżnię."""
    if not wiersze:
        return
    mapa_historia = mapa_historia or {}
    with polacz_baze() as conn:
        c = conn.cursor()
        for w in wiersze:
            dane = dict(w)
            dane["historia_id"] = mapa_historia.get(dane.get("historia_id"), dane.get("historia_id"))
            c.execute("SELECT 1 FROM historia WHERE id=?", (dane["historia_id"],))
            if c.fetchone() is None:
                # Wpis nie wrócił (albo wrócił pod nieznanym ID) — powiązania nie
                # da się odtworzyć, a sztuki zostały już oddane na stan magazynu.
                continue
            stare_id = dane.get("id")
            if stare_id is not None:
                c.execute("SELECT 1 FROM historia_czesci_magazynu WHERE id=?", (stare_id,))
                if c.fetchone() is not None:
                    dane.pop("id", None)
            nazwy = list(dane.keys())
            c.execute(
                f"INSERT INTO historia_czesci_magazynu ({','.join(nazwy)}) "
                f"VALUES ({','.join('?' * len(nazwy))})",
                tuple(dane[k] for k in nazwy)
            )
            c.execute("UPDATE magazyn_czesci SET ilosc = MAX(0, ilosc - ?) WHERE id=?",
                      (dane["ilosc_uzyta"], dane["magazyn_id"]))

def usun_czesc_magazynu_z_cofnieciem(czesc_id):
    """Usuwa pozycję magazynową wraz z powiązanymi wpisami zużycia — zarówno
    w wizytach (wizyta_czesci_magazynu), jak i w pojedynczych wpisach serwisowych
    (historia_czesci_magazynu) — które SQLite skasowałoby cicho przez CASCADE.
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

        c.execute("PRAGMA table_info(historia_czesci_magazynu)")
        kol_hw = [r["name"] for r in c.fetchall()]
        c.execute("SELECT * FROM historia_czesci_magazynu WHERE magazyn_id=?", (czesc_id,))
        uzycia_wpisow = [{k: r[k] for k in kol_hw} for r in c.fetchall()]

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

    zdalny_id_czesci = dane_czesc.get("zdalne_id")
    if zdalny_id_czesci:
        zarejestruj_nagrobek("magazyn_czesci", zdalny_id_czesci)

    zdalne_id_uzycia = [d.get("zdalne_id") for d in uzycia_dane if d.get("zdalne_id")]
    for zid in zdalne_id_uzycia:
        zarejestruj_nagrobek("wizyta_czesci_magazynu", zid)

    zdalne_id_uzycia_wpisow = [d.get("zdalne_id") for d in uzycia_wpisow if d.get("zdalne_id")]
    for zid in zdalne_id_uzycia_wpisow:
        zarejestruj_nagrobek("historia_czesci_magazynu", zid)

    stan = {"cofniete": False, "trwale_usuniete": False}

    def cofnij():
        if stan["cofniete"] or stan["trwale_usuniete"]:
            return
        stan["cofniete"] = True

        if zdalny_id_czesci:
            usun_nagrobek(zdalny_id_czesci)
        for zid in zdalne_id_uzycia + zdalne_id_uzycia_wpisow:
            usun_nagrobek(zid)
        
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
            if uzycia_wpisow:
                n_hw, p_hw = ",".join(kol_hw), ",".join("?" for _ in kol_hw)
                for d in uzycia_wpisow:
                    conn.execute(f"INSERT INTO historia_czesci_magazynu ({n_hw}) VALUES ({p_hw})", tuple(d[k] for k in kol_hw))

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

def polacz_zdjecia_w_pdf(sciezki_zdjec):
    """Łączy kilka zdjęć w jeden wielostronicowy plik PDF (jedno zdjęcie = jedna
    strona), zapisany jako plik tymczasowy w FOLDER_ODROCZONE — sprzątany
    automatycznie po godzinie przez posprzataj_odroczone_zalaczniki, gdyby coś
    poszło nie tak i plik nie trafił finalnie do bazy. Koryguje orientację EXIF
    tak samo jak zapisz_zalacznik(). Zwraca ścieżkę do PDF-a albo None, jeśli się
    nie uda (brak Pillow albo któregoś z plików źródłowych)."""
    if Image is None or not sciezki_zdjec:
        return None

    obrazy = []
    try:
        for sciezka in sciezki_zdjec:
            if not os.path.exists(sciezka):
                continue
            img = Image.open(sciezka)
            img = ImageOps.exif_transpose(img)
            if img.mode != "RGB":
                img = img.convert("RGB")
            obrazy.append(img)

        if not obrazy:
            return None

        folder_tmp = _upewnij_folder_odroczonych()
        docelowa = os.path.join(folder_tmp, f"polaczone_{uuid.uuid4().hex}.pdf")
        pierwszy, reszta = obrazy[0], obrazy[1:]
        pierwszy.save(docelowa, "PDF", save_all=True, append_images=reszta)
        return docelowa
    except Exception:
        return None
    finally:
        for img in obrazy:
            try:
                img.close()
            except Exception:
                pass

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

# Tabele bez własnej kolumny auto_id — pojazd wyznacza dopiero JOIN.
_ZAPYTANIA_AUTO_ID = {
    "historia": "SELECT z.auto_id FROM historia h JOIN zadania z ON h.zadanie_id = z.id WHERE h.id=?",
}

def auto_id_rekordu(tabela, rekord_id):
    """Pojazd, do którego należy pojedynczy rekord. Potrzebne przy zapisie
    notatki poza formularzem (z menu wpisu), gdzie nie mamy pod ręką stanu
    aplikacji, a trzeba wypchnąć zmianę do właściwego współdzielonego auta."""
    if not rekord_id:
        return None
    zapytanie = _ZAPYTANIA_AUTO_ID.get(tabela, f"SELECT auto_id FROM {tabela} WHERE id=?")
    with polacz_baze() as conn:
        c = conn.cursor()
        try:
            c.execute(zapytanie, (rekord_id,))
        except sqlite3.OperationalError:
            return None
        w = c.fetchone()
    return w[0] if w else None

def przytnij_notatke(tresc):
    """Jedno miejsce na normalizację treści notatki — formularz i szybka edycja
    muszą przycinać tak samo, inaczej limit da się obejść jedną z dróg."""
    return (tresc or "").strip()[:MAKS_DLUGOSC_NOTATKI]

def pobierz_notatke(tabela, rekord_id):
    """(treść, autor, data) notatki wpisu. Autor i data są puste dla tabel,
    które notatkę trzymają w starym polu opisowym bez podpisu."""
    kolumna = POLA_NOTATKI.get(tabela)
    if not kolumna or not rekord_id:
        return "", None, None
    z_podpisem = tabela in TABELE_NOTATKI_Z_PODPISEM
    pola = f"{kolumna}, notatka_autor, notatka_data" if z_podpisem else kolumna
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(f"SELECT {pola} FROM {tabela} WHERE id=?", (rekord_id,))
        w = c.fetchone()
    if not w:
        return "", None, None
    return (str(w[0] or ""), w[1], w[2]) if z_podpisem else (str(w[0] or ""), None, None)

def zapisz_notatke(tabela, rekord_id, tresc):
    """Zapisuje krótką notatkę POJEDYNCZEGO wpisu i zwraca auto_id pojazdu —
    wołający wypycha nim zmianę w tle (utils.wypchnij_w_tle), dzięki czemu
    notatka dociera do wszystkich współdzielących ten pojazd.
    Pusta treść kasuje notatkę RAZEM z podpisem: sam autor bez tekstu
    zostawiałby na karcie „Kasia • 04.09.2026” bez żadnej uwagi."""
    kolumna = POLA_NOTATKI.get(tabela)
    if not kolumna or not rekord_id:
        raise ValueError(f"Wpisy z tabeli '{tabela}' nie mają notatki.")

    tekst = przytnij_notatke(tresc)
    with polacz_baze() as conn:
        if tabela in TABELE_NOTATKI_Z_PODPISEM:
            conn.execute(
                f"UPDATE {tabela} SET {kolumna}=?, notatka_autor=?, notatka_data=? WHERE id=?",
                (tekst or None,
                 pobierz_moje_imie() if tekst else None,
                 datetime.now().strftime("%d.%m.%Y %H:%M") if tekst else None,
                 rekord_id)
            )
        else:
            conn.execute(f"UPDATE {tabela} SET {kolumna}=? WHERE id=?", (tekst or None, rekord_id))
    return auto_id_rekordu(tabela, rekord_id)

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

    zdalne_id_wizyt = [d.get("zdalne_id") for d in wizyty_dane if d.get("zdalne_id")]
    zdalne_id_historii = [d.get("zdalne_id") for d in historia_dane if d.get("zdalne_id")]
    zdalne_id_czesci = [d.get("zdalne_id") for d in czesci_dane if d.get("zdalne_id")]
    for zid in zdalne_id_wizyt:
        zarejestruj_nagrobek("wizyty", zid)
    for zid in zdalne_id_historii:
        zarejestruj_nagrobek("historia", zid)
    for zid in zdalne_id_czesci:
        zarejestruj_nagrobek("wizyta_czesci_magazynu", zid)

    stan = {"cofniete": False, "trwale_usuniete": False}

    def cofnij():
        if stan["cofniete"] or stan["trwale_usuniete"]: return
        stan["cofniete"] = True

        for zid in zdalne_id_wizyt:
            usun_nagrobek(zid)
        for zid in zdalne_id_historii:
            usun_nagrobek(zid)
        for zid in zdalne_id_czesci:
            usun_nagrobek(zid)

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

# ============================================================================
#  KOSZ NA USUNIĘTE POJAZDY
# ============================================================================
# Usunięcie auta nie kasuje już danych: cały pojazd (tabela samochody + wszystkie
# tabele potomne) trafia jako migawka JSON do kosz_pojazdy, a fizyczne zdjęcia do
# FOLDER_KOSZ. Snackbar "Cofnij" przywraca od razu; bez cofnięcia pojazd czeka w
# koszu do ręcznego przywrócenia albo do wygaśnięcia retencji (patrz
# pobierz_dni_kosza / posprzataj_kosz).

# Kolejność MA ZNACZENIE przy odtwarzaniu — klucz obcy wymaga, żeby rodzic
# istniał wcześniej: historia zależy od zadań i wizyt, wizyta_czesci_magazynu od
# wizyt i magazynu, do_zrobienia od zadań.
KOSZ_TABELE_POTOMNE = [
    "zadania", "wizyty", "magazyn_czesci", "tagi", "tankowania",
    "inne_koszty", "zestawy_opon", "zdjecia_karoserii", "odczyty_przebiegu",
    "warsztaty", "wydatki_cykliczne", "pakiety_serwisowe_wlasne",
    "do_zrobienia", "historia", "wizyta_czesci_magazynu", "historia_czesci_magazynu",
    "budzety",
]

# Tabele bez kolumny auto_id — z pojazdem związane wyłącznie pośrednio.
KOSZ_TABELE_BEZ_AUTO_ID = {"historia", "wizyta_czesci_magazynu", "historia_czesci_magazynu"}

KOSZ_ZAPYTANIA_POSREDNIE = {
    "historia": "SELECT h.* FROM historia h JOIN zadania z ON h.zadanie_id = z.id WHERE z.auto_id=?",
    "wizyta_czesci_magazynu": "SELECT wcm.* FROM wizyta_czesci_magazynu wcm JOIN wizyty w ON wcm.wizyta_id = w.id WHERE w.auto_id=?",
    "historia_czesci_magazynu": (
        "SELECT hcm.* FROM historia_czesci_magazynu hcm "
        "JOIN historia h ON hcm.historia_id = h.id "
        "JOIN zadania z ON h.zadanie_id = z.id WHERE z.auto_id=?"
    ),
}

# Odwołania do przemapowania, gdy przywracany rekord NIE odzyska oryginalnego ID
# (bo w międzyczasie zajął je inny wpis — np. po imporcie bazy). Bez tego
# historia wróciłaby podpięta pod cudzy podzespół.
KOSZ_KLUCZE_OBCE = {
    "do_zrobienia": {"zadanie_id": "zadania"},
    "historia": {"zadanie_id": "zadania", "wizyta_id": "wizyty"},
    "wizyta_czesci_magazynu": {"wizyta_id": "wizyty", "magazyn_id": "magazyn_czesci"},
    "historia_czesci_magazynu": {"historia_id": "historia", "magazyn_id": "magazyn_czesci"},
}

# Tabele, których zdalne odpowiedniki trzeba oznaczyć jako usunięte na serwerze.
# CELOWO używane dopiero przy TRWAŁYM kasowaniu z kosza — dopóki auto siedzi w
# koszu, u współdzielących nadal istnieje.
KOSZ_TABELE_SYNCHRONIZOWANE = [
    "zadania", "wizyty", "magazyn_czesci", "tankowania", "inne_koszty",
    "zestawy_opon", "odczyty_przebiegu", "warsztaty", "wydatki_cykliczne",
    "do_zrobienia", "historia", "tagi", "wizyta_czesci_magazynu",
    "historia_czesci_magazynu", "pakiety_serwisowe_wlasne",
]

# Tabele liczone do "ile wpisów przepadnie" pokazywanego przy pozycji kosza.
# Tagi, warsztaty czy pakiety to konfiguracja, nie historia — nie zawyżamy nimi
# liczby, którą użytkownik czyta jako "tyle mojej pracy tu leży".
KOSZ_TABELE_LICZONE = [
    "tankowania", "historia", "wizyty", "inne_koszty", "zestawy_opon",
    "magazyn_czesci", "zdjecia_karoserii", "odczyty_przebiegu", "do_zrobienia",
]


def pobierz_dni_kosza():
    """Ile dni pojazd leży w koszu, zanim zniknie na dobre. 0 = bez limitu."""
    try:
        w = int(pobierz_ustawienie("dni_kosza", str(DNI_KOSZA_DOMYSLNIE)))
    except (TypeError, ValueError):
        return DNI_KOSZA_DOMYSLNIE
    return w if w in DNI_KOSZA_OPCJE else DNI_KOSZA_DOMYSLNIE


def zapisz_dni_kosza(dni):
    zapisz_ustawienie("dni_kosza", str(parsuj_int_bezpiecznie(dni, DNI_KOSZA_DOMYSLNIE)))


def parsuj_int_bezpiecznie(wartosc, domyslna=0):
    try:
        return int(wartosc)
    except (TypeError, ValueError):
        return domyslna


def _zrzut_tabeli_pojazdu(c, tabela, auto_id):
    c.execute(f"PRAGMA table_info({tabela})")
    kolumny = [r["name"] for r in c.fetchall()]
    c.execute(KOSZ_ZAPYTANIA_POSREDNIE.get(tabela, f"SELECT * FROM {tabela} WHERE auto_id=?"), (auto_id,))
    return {"kolumny": kolumny, "wiersze": [{k: w[k] for k in kolumny} for w in c.fetchall()]}


def usun_auto_do_kosza(auto_id):
    """Przenosi pojazd wraz z całą historią i zdjęciami do kosza.

    Zwraca słownik zgodny z utils.pokaz_komunikat_cofnij: "cofnij" przywraca auto
    natychmiast i zdejmuje je z kosza, a "finalizuj" (wywoływane po wygaśnięciu
    snackbara) NIE kasuje już niczego — pojazd zostaje w koszu. Dodatkowo
    "przywrocone_id" niesie ID pojazdu po cofnięciu (nie musi być tym samym, co
    przed usunięciem), żeby interfejs mógł wrócić na właściwe auto.
    """
    if not auto_id:
        return None

    folder = _upewnij_folder_kosza()
    tabele = {}

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("PRAGMA table_info(samochody)")
        kol_auta = [r["name"] for r in c.fetchall()]
        c.execute("SELECT * FROM samochody WHERE id=?", (auto_id,))
        w_auto = c.fetchone()
        if not w_auto:
            return None
        dane_auta = {k: w_auto[k] for k in kol_auta}

        for tab in KOSZ_TABELE_POTOMNE:
            tabele[tab] = _zrzut_tabeli_pojazdu(c, tab, auto_id)

    nazwa = str(dane_auta.get("nazwa") or "Pojazd")
    pliki = []

    # Zdjęcia wędrują do folderu kosza pod losowymi nazwami; oryginalna ścieżka
    # zostaje zapamiętana, żeby przywrócenie odtworzyło te same odsyłacze w bazie.
    def schowaj(sciezka, prefiks):
        if not sciezka or not os.path.exists(sciezka):
            return
        cel = os.path.join(folder, f"{prefiks}_{uuid.uuid4().hex}_{os.path.basename(sciezka)}")
        try:
            shutil.move(sciezka, cel)
            pliki.append([cel, sciezka])
        except Exception:
            pass

    schowaj(dane_auta.get("zdjecie_glowne"), "auto")
    for tab in KOSZ_TABELE_POTOMNE:
        if tab in TABELE_Z_ZALACZNIKIEM:
            for wiersz in tabele[tab]["wiersze"]:
                schowaj(wiersz.get("zalacznik"), "z")

    # Kaskada SQLite wyczyści wszystkie tabele potomne
    with polacz_baze() as conn:
        conn.execute("DELETE FROM samochody WHERE id=?", (auto_id,))

    # Zaległa auto-synchronizacja tego pojazdu nie ma już czego wypchnąć —
    # zostawiona w kolejce zapętlałaby próby na nieistniejącym aucie.
    usun_z_kolejki_sync(auto_id)

    liczba_wpisow = sum(len(tabele.get(t, {}).get("wiersze", [])) for t in KOSZ_TABELE_LICZONE)
    rozmiar = 0
    for para in pliki:
        try:
            rozmiar += os.path.getsize(para[0])
        except Exception:
            pass

    # Ustawienia przywiązane do tego auta (np. własny układ kokpitu) jadą razem
    # z nim — inaczej zostałyby w bazie jako sieroty, a po przywróceniu pod nowym
    # ID pojazd i tak by ich nie znalazł.
    ustawienia_auta = _pobierz_ustawienia_pojazdu(auto_id)
    _usun_ustawienia_pojazdu(auto_id)

    migawka = {
        "wersja": 1,
        "auto": {"kolumny": kol_auta, "wiersz": dane_auta},
        "tabele": tabele,
        "ustawienia": ustawienia_auta,
    }

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO kosz_pojazdy (nazwa, data_usuniecia, migawka, pliki, liczba_wpisow, rozmiar_plikow, schemat_wersja) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                nazwa,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                json.dumps(migawka, ensure_ascii=False, default=str),
                json.dumps(pliki, ensure_ascii=False),
                liczba_wpisow,
                rozmiar,
                parsuj_int_bezpiecznie(pobierz_ustawienie("schema_version", "0"), 0),
            )
        )
        kosz_id = c.lastrowid

    wynik = {"kosz_id": kosz_id, "przywrocone_id": None, "cofniete": False}

    def cofnij():
        if wynik["cofniete"]:
            return
        wynik["cofniete"] = True
        wynik["przywrocone_id"] = przywroc_auto_z_kosza(kosz_id)

    def finalizuj():
        # Świadomie pusto: wygaśnięcie snackbara ZOSTAWIA pojazd w koszu.
        # To jest cała różnica względem dawnego, nieodwracalnego usuwania.
        return

    wynik["cofnij"] = cofnij
    wynik["finalizuj"] = finalizuj
    return wynik


def pobierz_kosz():
    """Pozycje kosza, najświeższe u góry. 'dni_do_usuniecia' to None przy
    retencji bez limitu, a 0 oznacza 'zniknie przy najbliższym starcie'."""
    dni_retencji = pobierz_dni_kosza()
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        try:
            c.execute(
                "SELECT id, nazwa, data_usuniecia, liczba_wpisow, rozmiar_plikow "
                "FROM kosz_pojazdy ORDER BY data_usuniecia DESC, id DESC"
            )
        except sqlite3.OperationalError:
            return []
        wiersze = c.fetchall()

    teraz = datetime.now()
    pozycje = []
    for w in wiersze:
        usunieto = None
        try:
            usunieto = datetime.strptime(str(w["data_usuniecia"]), "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            pass
        if dni_retencji and usunieto:
            zostalo = dni_retencji - (teraz - usunieto).days
            dni_do_usuniecia = max(0, zostalo)
        else:
            dni_do_usuniecia = None
        pozycje.append({
            "id": w["id"],
            "nazwa": str(w["nazwa"] or "Pojazd"),
            "data_usuniecia": usunieto,
            "data_tekst": usunieto.strftime("%d.%m.%Y %H:%M") if usunieto else "—",
            "liczba_wpisow": int(w["liczba_wpisow"] or 0),
            "rozmiar_plikow": int(w["rozmiar_plikow"] or 0),
            "dni_do_usuniecia": dni_do_usuniecia,
        })
    return pozycje


def liczba_w_koszu():
    with polacz_baze() as conn:
        c = conn.cursor()
        try:
            c.execute("SELECT COUNT(*) FROM kosz_pojazdy")
        except sqlite3.OperationalError:
            return 0
        return int((c.fetchone() or [0])[0])


def przywroc_auto_z_kosza(kosz_id):
    """Przywraca pojazd z kosza. Zwraca ID przywróconego auta albo None.

    ID rekordów odzyskujemy 1:1, kiedy tylko są wolne. Gdy któreś zdążył zająć
    nowy wpis, rekord dostaje świeże ID, a wszystkie odwołania do niego są
    przemapowane (KOSZ_KLUCZE_OBCE). Kolumn, których nie ma już w bieżącym
    schemacie (migawka ze starszej wersji aplikacji), po prostu nie wstawiamy.
    """
    if not kosz_id:
        return None

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM kosz_pojazdy WHERE id=?", (kosz_id,))
        w = c.fetchone()
        if not w:
            return None
        try:
            migawka = json.loads(w["migawka"])
            pliki = json.loads(w["pliki"] or "[]")
        except (TypeError, ValueError):
            return None

    dane_auta = dict((migawka.get("auto") or {}).get("wiersz") or {})
    if not dane_auta:
        return None
    tabele = migawka.get("tabele") or {}

    # Zdjęcia wracają na swoje stare ścieżki. Gdy któraś jest już zajęta, plik
    # dostaje nową nazwę, a odwołanie w bazie jest podmieniane.
    podmiana = {}
    for para in pliki:
        try:
            zrodlo, oryginal = para[0], para[1]
        except (IndexError, TypeError):
            continue
        if not zrodlo or not os.path.exists(zrodlo):
            continue
        cel = oryginal
        if os.path.exists(cel):
            trzon, rozszerzenie = os.path.splitext(oryginal)
            cel = f"{trzon}_{uuid.uuid4().hex[:8]}{rozszerzenie}"
        try:
            katalog = os.path.dirname(cel)
            if katalog:
                os.makedirs(katalog, exist_ok=True)
            shutil.move(zrodlo, cel)
            if cel != oryginal:
                podmiana[oryginal] = cel
        except Exception:
            pass

    if dane_auta.get("zdjecie_glowne") in podmiana:
        dane_auta["zdjecie_glowne"] = podmiana[dane_auta["zdjecie_glowne"]]

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        def kolumny_tabeli(tab):
            c.execute(f"PRAGMA table_info({tab})")
            return {r["name"] for r in c.fetchall()}

        def id_wolne(tab, wartosc):
            if wartosc is None:
                return False
            c.execute(f"SELECT 1 FROM {tab} WHERE id=?", (wartosc,))
            return c.fetchone() is None

        # samochody.nazwa jest UNIQUE — jeśli w międzyczasie powstało auto o tej
        # samej nazwie, przywracane dostaje dopisek zamiast wywalić całą operację.
        nazwa_bazowa = str(dane_auta.get("nazwa") or "Pojazd")
        nazwa = nazwa_bazowa
        licznik = 2
        while True:
            c.execute("SELECT 1 FROM samochody WHERE nazwa=?", (nazwa,))
            if c.fetchone() is None:
                break
            nazwa = f"{nazwa_bazowa} ({licznik})"
            licznik += 1
        dane_auta["nazwa"] = nazwa

        kol_samochody = kolumny_tabeli("samochody")
        rekord = {k: v for k, v in dane_auta.items() if k in kol_samochody}
        if not id_wolne("samochody", rekord.get("id")):
            rekord.pop("id", None)
        nazwy_kolumn = list(rekord.keys())
        c.execute(
            f"INSERT INTO samochody ({','.join(nazwy_kolumn)}) VALUES ({','.join('?' * len(nazwy_kolumn))})",
            tuple(rekord[k] for k in nazwy_kolumn)
        )
        nowe_auto_id = c.lastrowid

        mapy = {}
        for tab in KOSZ_TABELE_POTOMNE:
            mapy[tab] = {}
            wiersze = (tabele.get(tab) or {}).get("wiersze") or []
            if not wiersze:
                continue
            kolumny = kolumny_tabeli(tab)
            for zrodlowy in wiersze:
                dane = {k: v for k, v in zrodlowy.items() if k in kolumny}
                if not dane:
                    continue
                stare_id = dane.get("id")
                if tab not in KOSZ_TABELE_BEZ_AUTO_ID and "auto_id" in kolumny:
                    dane["auto_id"] = nowe_auto_id
                for kolumna, rodzic in KOSZ_KLUCZE_OBCE.get(tab, {}).items():
                    if dane.get(kolumna) is not None:
                        dane[kolumna] = mapy.get(rodzic, {}).get(dane[kolumna], dane[kolumna])
                if dane.get("zalacznik") in podmiana:
                    dane["zalacznik"] = podmiana[dane["zalacznik"]]
                if not id_wolne(tab, stare_id):
                    dane.pop("id", None)
                nazwy_kolumn = list(dane.keys())
                c.execute(
                    f"INSERT INTO {tab} ({','.join(nazwy_kolumn)}) VALUES ({','.join('?' * len(nazwy_kolumn))})",
                    tuple(dane[k] for k in nazwy_kolumn)
                )
                if stare_id is not None:
                    mapy[tab][stare_id] = c.lastrowid

        c.execute("DELETE FROM kosz_pojazdy WHERE id=?", (kosz_id,))

    _przywroc_ustawienia_pojazdu(nowe_auto_id, migawka.get("ustawienia"))

    # Pojazd współdzielony wraca też do kolejki synchronizacji — przywrócenie
    # mogło zmienić lokalne ID, a serwer musi zobaczyć aktualny stan.
    if dane_auta.get("wspolny_pojazd_id"):
        try:
            zakolejkuj_synchronizacje(nowe_auto_id, "Przywrócenie pojazdu z kosza")
        except Exception:
            pass

    return nowe_auto_id


def usun_z_kosza_trwale(kosz_id):
    """Kasuje pozycję kosza bezpowrotnie: zdjęcia z dysku plus nagrobki, żeby
    usunięcie dotarło przy najbliższej synchronizacji także na serwer i do
    współdzielących. Zwraca nazwę usuniętego pojazdu albo None."""
    if not kosz_id:
        return None

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM kosz_pojazdy WHERE id=?", (kosz_id,))
        w = c.fetchone()
        if not w:
            return None
        nazwa = str(w["nazwa"] or "Pojazd")
        try:
            migawka = json.loads(w["migawka"])
            pliki = json.loads(w["pliki"] or "[]")
        except (TypeError, ValueError):
            migawka, pliki = {}, []

    dane_auta = (migawka.get("auto") or {}).get("wiersz") or {}
    tabele = migawka.get("tabele") or {}

    for tab in KOSZ_TABELE_SYNCHRONIZOWANE:
        for wiersz in (tabele.get(tab) or {}).get("wiersze") or []:
            zdalne = wiersz.get("zdalne_id")
            if zdalne:
                zarejestruj_nagrobek(tab, zdalne)

    # Dane opisowe pojazdu mają własny zdalny odpowiednik (sync._synchronizuj_info_pojazdu)
    if dane_auta.get("info_zdalne_id"):
        zarejestruj_nagrobek("info_pojazdu", dane_auta["info_zdalne_id"])

    for para in pliki:
        try:
            usun_plik_zalacznika(para[0])
        except (IndexError, TypeError):
            pass

    with polacz_baze() as conn:
        conn.execute("DELETE FROM kosz_pojazdy WHERE id=?", (kosz_id,))

    return nazwa


def oproznij_kosz():
    """Trwale kasuje wszystkie pozycje kosza. Zwraca liczbę usuniętych pojazdów."""
    with polacz_baze() as conn:
        c = conn.cursor()
        try:
            c.execute("SELECT id FROM kosz_pojazdy")
        except sqlite3.OperationalError:
            return 0
        identyfikatory = [r[0] for r in c.fetchall()]

    usuniete = 0
    for kosz_id in identyfikatory:
        if usun_z_kosza_trwale(kosz_id):
            usuniete += 1
    return usuniete


def posprzataj_kosz():
    """Kasuje pozycje kosza starsze niż ustawiona retencja. Wywoływane raz, przy
    starcie aplikacji (init_db). Retencja 0 = trzymaj bez limitu."""
    # Sieroty po nagłym zamknięciu aplikacji sprzątamy ZAWSZE — także przy
    # retencji "nigdy", która wyłącza tylko kasowanie samych pozycji kosza.
    _posprzataj_osierocone_pliki_kosza()

    dni = pobierz_dni_kosza()
    if not dni:
        return 0

    granica = (datetime.now() - timedelta(days=dni)).strftime("%Y-%m-%d %H:%M:%S")
    with polacz_baze() as conn:
        c = conn.cursor()
        try:
            c.execute("SELECT id FROM kosz_pojazdy WHERE data_usuniecia <= ?", (granica,))
        except sqlite3.OperationalError:
            return 0
        identyfikatory = [r[0] for r in c.fetchall()]

    usuniete = 0
    for kosz_id in identyfikatory:
        try:
            if usun_z_kosza_trwale(kosz_id):
                usuniete += 1
        except Exception:
            pass

    return usuniete


def _posprzataj_osierocone_pliki_kosza():
    folder = _upewnij_folder_kosza()
    uzywane = set()
    with polacz_baze() as conn:
        c = conn.cursor()
        try:
            c.execute("SELECT pliki FROM kosz_pojazdy")
        except sqlite3.OperationalError:
            return
        for (surowe,) in c.fetchall():
            try:
                for para in json.loads(surowe or "[]"):
                    uzywane.add(os.path.normcase(os.path.abspath(para[0])))
            except (TypeError, ValueError, IndexError):
                continue
    try:
        for nazwa_pliku in os.listdir(folder):
            sciezka = os.path.join(folder, nazwa_pliku)
            if os.path.isfile(sciezka) and os.path.normcase(os.path.abspath(sciezka)) not in uzywane:
                try:
                    os.remove(sciezka)
                except Exception:
                    pass
    except Exception:
        pass


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

    # 5. Części z magazynu użyte w tych wpisach wracają na stan — CASCADE
    # skasowałby powiązania po cichu, zostawiając sztuki „zużyte” w nieistniejącym
    # już podzespole.
    czesci_wpisow = _zdejmij_powiazania_czesci_wpisow([d["id"] for d in historia_dane])

    # 6. Usunięcie zadania (SQLite CASCADE automatycznie wyczyści powiązaną historię)
    with polacz_baze() as conn:
        conn.execute("DELETE FROM zadania WHERE id=?", (zadanie_id,))

    zdalny_id_zadania = dane_zad.get("zdalne_id")
    zdalne_id_historii = [d.get("zdalne_id") for d in historia_dane if d.get("zdalne_id")]
    if zdalny_id_zadania:
        zarejestruj_nagrobek("zadania", zdalny_id_zadania)
    for zid in zdalne_id_historii:
        zarejestruj_nagrobek("historia", zid)
    for w in czesci_wpisow:
        if w.get("zdalne_id"):
            zarejestruj_nagrobek("historia_czesci_magazynu", w["zdalne_id"])

    stan = {"cofniete": False, "trwale_usuniete": False}

    def cofnij():
        if stan["cofniete"] or stan["trwale_usuniete"]:
            return
        stan["cofniete"] = True

        if zdalny_id_zadania:
            usun_nagrobek(zdalny_id_zadania)
        for zid in zdalne_id_historii:
            usun_nagrobek(zid)
        for w in czesci_wpisow:
            if w.get("zdalne_id"):
                usun_nagrobek(w["zdalne_id"])

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

        # 4. Wpisy historii wróciły z ORYGINALNYMI ID, więc powiązania z magazynem
        # wstawiamy bez przemapowania; sztuki znów schodzą ze stanu.
        _przywroc_powiazania_czesci_wpisow(czesci_wpisow)

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

# Podpisy trafiają zarówno do checkboxów na ekranie eksportu, jak i do nagłówków
# sekcji w PDF — a czcionka raportu (DejaVu) nie ma glifów emoji i rysowała w ich
# miejscu puste prostokąty. Ikony dokłada UI z utils.IKONY_EKSPORTU.
KATEGORIE_EKSPORTU = {
    "tankowania": "Tankowania",
    "historia": "Historia serwisowa",
    "zadania": "Podzespoły i interwały",
    "wizyty": "Wizyty zbiorcze (warsztat)",
    "inne_koszty": "Inne koszty",
    "wydatki_cykliczne": "Wydatki cykliczne i przypomnienia",
    "magazyn_czesci": "Magazyn części i płynów",
    "zestawy_opon": "Zestawy opon",
    "do_zrobienia": "Lista Do zrobienia",
    "warsztaty": "Baza warsztatów",
    "odczyty_przebiegu": "Odczyty licznika",
    "tagi": "Tagi",
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
    Magazyn, zestawy opon, lista Do zrobienia, definicje podzespołów (zadania),
    wydatki cykliczne, warsztaty i tagi to "stany aktualne" — eksportują się zawsze
    w całości, niezależnie od zakresu dat. Zakresowi podlegają tylko tankowania,
    historia, wizyty, inne koszty i odczyty przebiegu.
    """
    wynik = {}
    if not auto_id or not kategorie:
        return wynik

    with polacz_baze() as conn:
        c = conn.cursor()

        if "tankowania" in kategorie:
            c.execute(
                "SELECT data, przebieg, dystans, litry, kwota, do_pelna, stacja, tagi, notatka "
                "FROM tankowania WHERE auto_id=?", (auto_id,)
            )
            wiersze = []
            for data, prz, dys, lit, kwo, pelna, stacja, tagi, notatka in c.fetchall():
                if _data_w_zakresie(data, od_data, do_data):
                    wiersze.append([
                        data, int(prz or 0), formatuj_liczba_eksport(dys), formatuj_liczba_eksport(lit),
                        formatuj_liczba_eksport(kwo), "Tak" if pelna else "Nie", stacja or "", tagi or "",
                        notatka or ""
                    ])
            wiersze.sort(key=lambda w: parsuj_date(w[0]))
            wynik["tankowania"] = (
                ["Data", "Przebieg (km)", "Dystans (km)", "Litry", "Kwota", "Do pełna", "Stacja", "Tagi", "Notatka"], wiersze
            )

        if "historia" in kategorie:
            c.execute(
                "SELECT h.data, z.nazwa, h.przebieg, h.cena, h.wykonawca, h.kategoria, h.notatka "
                "FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
                "WHERE z.auto_id=? AND h.wizyta_id IS NULL", (auto_id,)
            )
            wiersze = []
            for data, nazwa, prz, cena, wyk, kat, notatka in c.fetchall():
                if _data_w_zakresie(data, od_data, do_data):
                    wiersze.append([data, nazwa, int(prz or 0), formatuj_liczba_eksport(cena), wyk or "", kat or "", notatka or ""])
            wiersze.sort(key=lambda w: parsuj_date(w[0]))
            wynik["historia"] = (["Data", "Podzespół", "Przebieg (km)", "Koszt", "Wykonawca", "Kategoria", "Notatka"], wiersze)

        if "wizyty" in kategorie:
            c.execute(
                "SELECT w.data, w.przebieg, w.wykonawca, w.koszt_calkowity, w.notatki, w.tagi, "
                "GROUP_CONCAT(z.nazwa, ', ') FROM wizyty w "
                "LEFT JOIN historia h ON h.wizyta_id = w.id "
                "LEFT JOIN zadania z ON h.zadanie_id = z.id "
                "WHERE w.auto_id=? GROUP BY w.id", (auto_id,)
            )
            wiersze = []
            for data, prz, wyk, kosz, notatki, tagi, czesci in c.fetchall():
                if _data_w_zakresie(data, od_data, do_data):
                    wiersze.append([
                        data, int(prz or 0), wyk or "", formatuj_liczba_eksport(kosz),
                        czesci or "", tagi or "", notatki or ""
                    ])
            wiersze.sort(key=lambda w: parsuj_date(w[0]))
            wynik["wizyty"] = (
                ["Data", "Przebieg (km)", "Warsztat", "Koszt", "Podzespoły", "Tagi", "Notatki"], wiersze
            )

        if "inne_koszty" in kategorie:
            c.execute("SELECT data, nazwa, kategoria, kwota, tagi, notatka FROM inne_koszty WHERE auto_id=?", (auto_id,))
            wiersze = []
            for data, nazwa, kat, kwota, tagi, notatka in c.fetchall():
                if _data_w_zakresie(data, od_data, do_data):
                    wiersze.append([data, nazwa or "", kat or "", formatuj_liczba_eksport(kwota), tagi or "", notatka or ""])
            wiersze.sort(key=lambda w: parsuj_date(w[0]))
            wynik["inne_koszty"] = (["Data", "Opis", "Kategoria", "Kwota", "Tagi", "Notatka"], wiersze)

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

        if "zadania" in kategorie:
            c.execute(
                "SELECT nazwa, interwal_km, interwal_miesiace, data, przebieg, prog_km, prog_dni, dotyczy_opon "
                "FROM zadania WHERE auto_id=? ORDER BY nazwa", (auto_id,)
            )
            dom_km, dom_dni = pobierz_prog_km(), pobierz_prog_dni()
            wiersze = []
            for nazwa, ik, im, data_o, prz_o, p_km, p_dni, opony in c.fetchall():
                wiersze.append([
                    nazwa or "",
                    f"{int(ik)} km" if ik else "",
                    f"{formatuj_liczba_eksport(im, 0)} mies." if im else "",
                    data_o or "",
                    int(prz_o or 0) if prz_o else "",
                    f"{int(p_km)} km" if p_km else f"{dom_km} km (domyślny)",
                    f"{int(p_dni)} dni" if p_dni else f"{dom_dni} dni (domyślny)",
                    "Tak" if opony else "Nie",
                ])
            wynik["zadania"] = (
                ["Podzespół", "Interwał km", "Interwał czasowy", "Ostatnia wymiana",
                 "Przebieg ost. wymiany", "Próg (km)", "Próg (dni)", "Dotyczy opon"],
                wiersze
            )

        if "wydatki_cykliczne" in kategorie:
            c.execute(
                "SELECT nazwa, kwota, okres_dni, nastepna_data, czy_koszt FROM wydatki_cykliczne "
                "WHERE auto_id=? ORDER BY nazwa", (auto_id,)
            )
            wiersze = [
                [n or "", formatuj_liczba_eksport(kw) if ck else "", int(okr or 0), nd or "", "Koszt" if ck else "Przypomnienie"]
                for n, kw, okr, nd, ck in c.fetchall()
            ]
            wynik["wydatki_cykliczne"] = (["Nazwa", "Kwota", "Co ile dni", "Następna płatność", "Typ"], wiersze)

        if "warsztaty" in kategorie:
            c.execute(
                "SELECT nazwa, telefon, adres, notatki FROM warsztaty WHERE auto_id=? ORDER BY nazwa",
                (auto_id,)
            )
            wiersze = [[n or "", tel or "", adr or "", nt or ""] for n, tel, adr, nt in c.fetchall()]
            wynik["warsztaty"] = (["Nazwa", "Telefon", "Adres", "Notatki"], wiersze)

        if "odczyty_przebiegu" in kategorie:
            c.execute("SELECT data, przebieg, notatka FROM odczyty_przebiegu WHERE auto_id=?", (auto_id,))
            wiersze = [
                [data, int(prz or 0), notatka or ""] for data, prz, notatka in c.fetchall()
                if _data_w_zakresie(data, od_data, do_data)
            ]
            wiersze.sort(key=lambda w: parsuj_date(w[0]))
            wynik["odczyty_przebiegu"] = (["Data", "Przebieg (km)", "Notatka"], wiersze)

        if "tagi" in kategorie:
            c.execute("SELECT nazwa, kolor FROM tagi WHERE auto_id=? ORDER BY nazwa", (auto_id,))
            wiersze = [[n or "", k or ""] for n, k in c.fetchall()]
            wynik["tagi"] = (["Nazwa", "Kolor"], wiersze)

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


# ==================== GRAFIKA „ROK W PIGUŁCE” ====================
# Podsumowanie roku jako obrazek do wysłania — ta sama treść, co na ekranie,
# tylko w formie, którą da się wrzucić na czat. Rysowane Pillow (jest już
# w projekcie dla miniatur zdjęć), bez żadnej nowej zależności.

MIESIACE_SKROT = ["sty", "lut", "mar", "kwi", "maj", "cze",
                  "lip", "sie", "wrz", "paź", "lis", "gru"]

# Kandydaci na czcionkę, w kolejności od najlepszego. Assets projektu wygrywają,
# potem typowe czcionki systemowe (Windows / Android / Linux), a gdy nie ma nic —
# wbudowana czcionka Pillow, przy której transliterujemy polskie znaki (dokładnie
# ta sama zasada, co w eksporcie PDF).
_CZCIONKI_KANDYDACI = [
    ("assets", "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
    ("C:/Windows/Fonts", "segoeui.ttf", "segoeuib.ttf"),
    ("C:/Windows/Fonts", "arial.ttf", "arialbd.ttf"),
    ("/system/fonts", "Roboto-Regular.ttf", "Roboto-Bold.ttf"),
    ("/system/fonts", "NotoSans-Regular.ttf", "NotoSans-Bold.ttf"),
    ("/usr/share/fonts/truetype/dejavu", "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
]


def _znajdz_czcionki_grafiki():
    """(ścieżka_regular, ścieżka_bold) albo (None, None), gdy nic nie znaleziono."""
    kandydaci = [(FOLDER_ASSETS, "DejaVuSans.ttf", "DejaVuSans-Bold.ttf")]
    kandydaci += [(folder, reg, bold) for folder, reg, bold in _CZCIONKI_KANDYDACI[1:]]
    for folder, reg, bold in kandydaci:
        sciezka_reg = os.path.join(folder, reg)
        if os.path.exists(sciezka_reg):
            sciezka_bold = os.path.join(folder, bold)
            return sciezka_reg, (sciezka_bold if os.path.exists(sciezka_bold) else sciezka_reg)
    return None, None


def generuj_grafike_roku(auto_nazwa, dane, akcent=(56, 189, 248)):
    """PNG 1080×1440 z podsumowaniem roku. `dane` to wynik podsumowanie_roku().
    Zwraca bajty pliku albo rzuca RuntimeError, gdy Pillow jest niedostępne."""
    if Image is None:
        raise RuntimeError("Biblioteka Pillow nie jest zainstalowana — grafika jest niedostępna.")
    from PIL import ImageDraw, ImageFont

    # 1080×1440 (3:4) — mieści komplet faktów bez ściskania, a przy tym jest
    # standardowym pionowym kadrem, który nie zostanie przycięty na czacie.
    SZER, WYS = 1080, 1440
    TLO_GORA, TLO_DOL = (15, 23, 42), (30, 41, 59)
    BIALY, PRZYGASZONY = (248, 250, 252), (148, 163, 184)

    reg_path, bold_path = _znajdz_czcionki_grafiki()

    def czcionka(rozmiar, pogrubiona=False):
        sciezka = bold_path if pogrubiona else reg_path
        if sciezka:
            try:
                return ImageFont.truetype(sciezka, rozmiar)
            except Exception:
                pass
        try:
            return ImageFont.load_default(size=rozmiar)
        except TypeError:
            # Bardzo stare Pillow: load_default() bez rozmiaru, bitmapowa.
            return ImageFont.load_default()

    # Bez własnej czcionki nie mamy pewności co do polskich znaków — wtedy
    # transliterujemy, zamiast rysować puste prostokąty.
    transliteruj = reg_path is None

    def t(tekst):
        tekst = "" if tekst is None else str(tekst)
        tekst = tekst.replace("•", "-").replace("…", "...").replace("≈", "~")
        return tekst.translate(_MAPA_TRANSLITERACJI_PL) if transliteruj else tekst

    obraz = Image.new("RGB", (SZER, WYS), TLO_GORA)
    rysuj = ImageDraw.Draw(obraz)

    # Pionowy gradient tła — jedna linia na wiersz pikseli.
    for y in range(WYS):
        udzial = y / WYS
        rysuj.line(
            [(0, y), (SZER, y)],
            fill=tuple(int(TLO_GORA[i] + (TLO_DOL[i] - TLO_GORA[i]) * udzial) for i in range(3)),
        )
    # Delikatna poświata w rogu, żeby tło nie było płaskie.
    rysuj.ellipse([SZER - 420, -260, SZER + 200, 360],
                  fill=tuple(min(255, int(TLO_GORA[i] + (akcent[i] - TLO_GORA[i]) * 0.16)) for i in range(3)))

    MARGINES = 72
    SZER_UZYTECZNA = SZER - 2 * MARGINES

    def zmiesc(tresc, maks_szer, rozmiar, pogrubiony=False, min_rozmiar=16):
        """Dobiera rozmiar czcionki tak, żeby tekst zmieścił się w zadanej
        szerokości; gdy nawet minimalny nie wystarcza, ucina z wielokropkiem.
        Bez tego długa nazwa auta albo „przejazd z Warszawy do Lizbony — 2,1 raza”
        wychodziły poza kadr — a obrazek ma iść na czat, nie do poprawek."""
        tresc = t(tresc)
        while rozmiar > min_rozmiar:
            if rysuj.textlength(tresc, font=czcionka(rozmiar, pogrubiony)) <= maks_szer:
                return tresc, rozmiar
            rozmiar -= 2
        f = czcionka(rozmiar, pogrubiony)
        while tresc and rysuj.textlength(tresc + "...", font=f) > maks_szer:
            tresc = tresc[:-1]
        return (tresc + "...") if tresc else "", rozmiar

    def tekst(xy, tresc, rozmiar, kolor=BIALY, pogrubiony=False, prawy=False, maks_szer=None):
        tresc = t(tresc)
        if maks_szer:
            tresc, rozmiar = zmiesc(tresc, maks_szer, rozmiar, pogrubiony)
        f = czcionka(rozmiar, pogrubiony)
        x, y_t = xy
        if prawy:
            x -= rysuj.textlength(tresc, font=f)
        rysuj.text((x, y_t), tresc, font=f, fill=kolor)
        return y_t + rozmiar

    y = 78
    tekst((MARGINES, y), "ROK W PIGUŁCE", 30, akcent, True, maks_szer=SZER_UZYTECZNA)
    y += 46
    tekst((MARGINES, y), auto_nazwa, 46, BIALY, True, maks_szer=SZER_UZYTECZNA)
    y += 70

    # Rok i dopisek o niepełnym roku jako OSOBNE elementy: sklejone w jeden napis
    # nie mieściły się w kadrze, a sam rok ma być tym, co widać z miniatury.
    tekst((MARGINES, y), str(dane["rok"]), 132, BIALY, True)
    if dane.get("niepelny"):
        f_rok = czcionka(132, True)
        x_pill = MARGINES + rysuj.textlength(str(dane["rok"]), font=f_rok) + 24
        rysuj.rounded_rectangle([x_pill, y + 46, x_pill + 234, y + 100], radius=27, fill=(51, 65, 85))
        tekst((x_pill + 22, y + 58), "rok w toku", 26, PRZYGASZONY, True)
    y += 176

    waluta = pobierz_walute()

    def kafelek(x, y_kafla, szer, etykieta, wartosc, podpis=None):
        WYS_KAFLA = 172
        rysuj.rounded_rectangle([x, y_kafla, x + szer, y_kafla + WYS_KAFLA], radius=26,
                                fill=(24, 34, 54), outline=(51, 65, 85), width=2)
        wnetrze = szer - 56
        tekst((x + 28, y_kafla + 26), etykieta, 24, PRZYGASZONY, maks_szer=wnetrze)
        tekst((x + 28, y_kafla + 62), wartosc, 52, BIALY, True, maks_szer=wnetrze)
        if podpis:
            tekst((x + 28, y_kafla + 126), podpis, 22, PRZYGASZONY, maks_szer=wnetrze)
        return y_kafla + WYS_KAFLA

    szer_kafla = (SZER_UZYTECZNA - 24) // 2
    kafelek(MARGINES, y, szer_kafla, "Przejechane", f"{formatuj_liczba_eksport(dane['km'], 0)} km",
            dane.get("porownanie_dystansu"))
    kafelek(MARGINES + szer_kafla + 24, y, szer_kafla, "Wydane łącznie",
            f"{formatuj_liczba_eksport(dane['koszty']['razem'], 0)} {waluta}",
            f"~{formatuj_liczba_eksport(dane['sredni_koszt_miesiaca'], 0)} {waluta} na miesiąc")
    y += 196

    koszt_km = f"{formatuj_liczba_eksport(dane['koszt_km'], 2)} {waluta}" if dane.get("koszt_km") else "—"
    zuzycie = formatuj_zuzycie_tekst(dane["srednie_zuzycie"]) if dane.get("srednie_zuzycie") else "—"
    kafelek(MARGINES, y, szer_kafla, "Koszt kilometra", koszt_km,
            f"{dane['liczba_tankowan']} tankowań w roku")
    kafelek(MARGINES + szer_kafla + 24, y, szer_kafla, "Średnie zużycie", zuzycie,
            f"{formatuj_liczba_eksport(dane['litry'], 0)} l zatankowane" if dane.get("litry") else None)
    y += 214

    # --- rytm roku: koszty miesiąc po miesiącu ---
    maks = max(dane["miesiace"].values()) if dane["miesiace"] else 0
    if maks > 0:
        tekst((MARGINES, y), "KOSZTY MIESIĄC PO MIESIĄCU", 24, PRZYGASZONY, True)
        y += 44
        WYS_WYKRESU = 150
        szer_kolumny = SZER_UZYTECZNA / 12
        for m in range(1, 13):
            wartosc = dane["miesiace"][m]
            wysokosc = int(WYS_WYKRESU * (wartosc / maks)) if wartosc > 0 else 3
            x0 = MARGINES + (m - 1) * szer_kolumny + 6
            x1 = MARGINES + m * szer_kolumny - 6
            gora = y + WYS_WYKRESU - wysokosc
            czy_szczyt = (m == dane["najdrozszy_miesiac"]["miesiac"])
            rysuj.rounded_rectangle([x0, gora, x1, y + WYS_WYKRESU], radius=8,
                                    fill=akcent if czy_szczyt else (51, 65, 85))
            f_m = czcionka(20, czy_szczyt)
            etykieta_m = t(MIESIACE_SKROT[m - 1])
            szer_et = rysuj.textlength(etykieta_m, font=f_m)
            rysuj.text(((x0 + x1) / 2 - szer_et / 2, y + WYS_WYKRESU + 12), etykieta_m,
                       font=f_m, fill=akcent if czy_szczyt else PRZYGASZONY)
        y += WYS_WYKRESU + 56

    # --- wiersze faktów: tyle, ile zmieści się nad stopką ---
    STOPKA_Y = WYS - 74
    WYS_WIERSZA = 66

    fakty = []
    najdrozszy = dane["najdrozszy_miesiac"]
    fakty.append(("Najdroższy miesiąc",
                  f"{MIESIACE_SKROT[najdrozszy['miesiac'] - 1]} • "
                  f"{formatuj_liczba_eksport(najdrozszy['kwota'], 0)} {waluta}"))
    if dane.get("ulubiona_stacja"):
        st = dane["ulubiona_stacja"]
        fakty.append(("Ulubiona stacja", f"{st['nazwa']} • {st['liczba']}x"))
    if dane.get("najwiekszy_wydatek"):
        nw = dane["najwiekszy_wydatek"]
        fakty.append(("Największy wydatek",
                      f"{nw['opis']} • {formatuj_liczba_eksport(nw['kwota'], 0)} {waluta}"))
    if dane.get("zmiana_rdr") is not None:
        znak = "+" if dane["zmiana_rdr"] > 0 else ""
        fakty.append((f"Względem {dane['rok'] - 1}",
                      f"{znak}{formatuj_liczba_eksport(dane['zmiana_rdr'], 0)}%"))

    for etykieta, wartosc in fakty:
        if y + WYS_WIERSZA > STOPKA_Y - 20:
            break
        tekst((MARGINES, y), etykieta, 26, PRZYGASZONY, maks_szer=SZER_UZYTECZNA * 0.45)
        tekst((SZER - MARGINES, y - 2), wartosc, 28, BIALY, True, prawy=True,
              maks_szer=SZER_UZYTECZNA * 0.5)
        rysuj.line([(MARGINES, y + 44), (SZER - MARGINES, y + 44)], fill=(45, 58, 80), width=2)
        y += WYS_WIERSZA

    tekst((MARGINES, STOPKA_Y), f"Flota Mobile • {datetime.now().strftime('%d.%m.%Y')}", 22, (100, 116, 139))

    bufor = io.BytesIO()
    obraz.save(bufor, format="PNG", optimize=True)
    return bufor.getvalue()


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
        # Notatki wpisów pomijamy w PDF: tabela dzieli szerokość strony PO RÓWNO
        # między kolumny i przycina zawartość, więc kolumna wolnego tekstu byłaby
        # nieczytelna („Tankowanie po...”), a przy okazji zwęziłaby wszystkie
        # pozostałe. W CSV, gdzie szerokość nie ogranicza niczego, notatki są.
        if "Notatka" in naglowki:
            i_not = naglowki.index("Notatka")
            naglowki = [h for j, h in enumerate(naglowki) if j != i_not]
            wiersze = [[k for j, k in enumerate(w) if j != i_not] for w in wiersze]

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
            "oc_data, przeglad_data, ac_data, assistance_data, gwarancja_data, gwarancja_przebieg, "
            "zdjecie_glowne "
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
            ("Gwarancja do", f"{formatuj_liczba_eksport(auto['gwarancja_przebieg'], 0)} km" if auto["gwarancja_przebieg"] else None),
            ("Aktualny przebieg", f"{formatuj_liczba_eksport(aktualny_przebieg, 0)} km" if aktualny_przebieg else None),
        ) if w
    ]

    terminy = [
        ("Polisa OC", auto["oc_data"]), ("Przegląd techniczny", auto["przeglad_data"]),
        ("Polisa AC", auto["ac_data"]), ("Assistance", auto["assistance_data"]),
        ("Gwarancja producenta", auto["gwarancja_data"]),
    ]

    return {
        "zdjecie_glowne": auto["zdjecie_glowne"],
        "specyfikacja": specyfikacja,
        "terminy": terminy,
        "punkty_przebiegu": pobierz_historie_przebiegu(auto_id),
        "zdjecia_karoserii": zdjecia_karoserii,
    }

# ==================== IMPORT CSV (TANKOWANIA) ====================

POLA_IMPORTU_TANKOWAN = {
    "data": ("Data", True),
    "przebieg": ("Licznik (km)", False),
    "dystans": ("Dystans (km)", False),
    "litry": ("Litry / kWh", True),
    "kwota": ("Kwota", True),
    "stacja": ("Stacja / punkt ładowania", False),
    "do_pelna": ("Do pełna", False),
    # Kolumna sensowna tylko przy hybrydzie plug-in: bez niej cały plik trafia
    # do domyślnego źródła pojazdu, czyli zachowuje się jak dotąd.
    "rodzaj_energii": ("Źródło (paliwo / prąd)", False),
}

_ALIASY_IMPORTU = {
    "data": ["data", "date", "data tankowania", "dzien", "dzień", "datum"],
    "przebieg": ["przebieg", "licznik", "odometer", "odo", "mileage", "km", "stan licznika", "przebieg (km)"],
    "dystans": ["dystans", "distance", "trip", "przejechano", "dystans (km)"],
    "litry": ["litry", "liters", "litres", "ilosc", "ilość", "volume", "quantity", "kwh", "energia", "paliwo"],
    "kwota": ["kwota", "koszt", "cena", "cost", "total", "total cost", "price", "wartosc", "wartość"],
    "stacja": ["stacja", "station", "punkt ladowania", "punkt ładowania", "miejsce", "fuel station", "sprzedawca"],
    "do_pelna": ["do pelna", "do pełna", "full", "pelny bak", "pełny bak", "full tank", "tankowanie do pelna"],
    "rodzaj_energii": ["rodzaj", "zrodlo", "źródło", "energia", "typ", "paliwo/prad", "fuel type"],
}


def _normalizuj_naglowek(tekst):
    return " ".join(str(tekst or "").strip().lower().replace("_", " ").split())


def _parsuj_liczbe_csv(tekst):
    """Odporny parser liczby z arkusza: '1 234,56', '1,234.56', '12.5', '12,5',
    '45,20 zł'. Zwraca float albo None. Bez regexpów — db.py nie importuje 're'
    globalnie."""
    if tekst is None:
        return None
    s = str(tekst).replace("\u00a0", " ").strip()
    if not s:
        return None
    s = "".join(znak for znak in s if znak in "0123456789,.-")
    if not s or s in ("-", ".", ",", "-.", "-,"):
        return None
    if "," in s and "." in s:
        # O roli separatora decyduje ten, który stoi bliżej końca.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _parsuj_date_csv(tekst):
    """Zwraca datę w formacie aplikacji ('DD.MM.YYYY') albo None. Formaty
    dwuznaczne (dd/mm vs mm/dd) rozstrzygamy po europejsku — dd/mm/yyyy."""
    s = str(tekst or "").strip()
    if not s:
        return None
    s = s.split("T")[0].strip()
    if " " in s and len(s.split(" ")[0]) >= 6:
        s = s.split(" ")[0]
    for wzorzec in ("%d.%m.%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d.%m.%y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, wzorzec).strftime("%d.%m.%Y")
        except ValueError:
            continue
    return None


def _rozpoznaj_rodzaj_csv(tekst, auto_id):
    """Rozpoznaje źródło energii z kolumny pliku — po polsku i po angielsku.
    Nierozpoznane albo puste = domyślne źródło pojazdu, więc pliki bez tej
    kolumny (czyli praktycznie wszystkie) importują się jak dotąd."""
    znormalizowany = _normalizuj_naglowek(tekst)
    if not znormalizowany:
        return domyslny_rodzaj_energii(auto_id)
    if any(slowo in znormalizowany for slowo in ("prad", "prąd", "electric", "kwh", "ladow", "ładow", "charge", "ev")):
        return ENERGIA_PRAD
    if any(slowo in znormalizowany for slowo in ("paliw", "fuel", "benzyn", "diesel", "petrol", "gas", "lpg", "tankow")):
        return ENERGIA_PALIWO
    return domyslny_rodzaj_energii(auto_id)


def _prawda_csv(tekst):
    return _normalizuj_naglowek(tekst) in ("1", "tak", "yes", "true", "y", "t", "prawda", "x")


def wczytaj_plik_csv(sciezka):
    """Czyta plik CSV/TSV odporny na kodowanie (UTF-8 z BOM, CP1250, Latin-1)
    i separator (';', ',', tabulator). Zwraca (naglowki, wiersze) — wiersze to
    listy stringów wyrównane do długości nagłówka."""
    surowe = None
    for kodowanie in ("utf-8-sig", "cp1250", "latin-1"):
        try:
            with open(sciezka, "r", encoding=kodowanie, newline="") as f:
                surowe = f.read()
            break
        except UnicodeDecodeError:
            continue
    if surowe is None:
        raise ValueError("Nie udało się odczytać pliku — nieznane kodowanie znaków.")

    if not surowe.strip():
        raise ValueError("Plik jest pusty.")

    pierwsza_linia = surowe.splitlines()[0]
    separator = max((";", ",", "\t"), key=pierwsza_linia.count)
    if pierwsza_linia.count(separator) == 0:
        separator = ";"

    czytnik = csv.reader(io.StringIO(surowe), delimiter=separator)
    wszystkie = [w for w in czytnik if any((k or "").strip() for k in w)]
    if not wszystkie:
        raise ValueError("Plik nie zawiera żadnych danych.")

    naglowki = [str(k).strip() for k in wszystkie[0]]
    szerokosc = len(naglowki)
    wiersze = []
    for w in wszystkie[1:]:
        w = list(w[:szerokosc]) + [""] * max(0, szerokosc - len(w))
        wiersze.append([str(k).strip() for k in w])
    return naglowki, wiersze


def dopasuj_kolumny_tankowan(naglowki):
    """Automatyczne zgadywanie, która kolumna pliku odpowiada któremu polu.
    Zwraca {pole: indeks_kolumny lub None} — użytkownik może to potem poprawić."""
    znormalizowane = [_normalizuj_naglowek(h) for h in naglowki]
    mapowanie = {pole: None for pole in POLA_IMPORTU_TANKOWAN}
    zajete = set()

    for pole, aliasy in _ALIASY_IMPORTU.items():
        for dokladne in (True, False):
            for i, h in enumerate(znormalizowane):
                if i in zajete or not h:
                    continue
                trafienie = (h in aliasy) if dokladne else any(a in h for a in aliasy)
                if trafienie:
                    mapowanie[pole] = i
                    zajete.add(i)
                    break
            if mapowanie[pole] is not None:
                break
    return mapowanie


def przygotuj_import_tankowan(auto_id, naglowki, wiersze, mapowanie):
    """Waliduje wiersze wg mapowania kolumn i wykrywa duplikaty względem tego,
    co JUŻ jest w bazie (ta sama data + przebieg + kwota, jak w dedupie sync).
    Nic nie zapisuje. Zwraca {"gotowe": [...], "duplikaty": n, "bledy": [(nr, powod)]}."""
    gotowe, bledy = [], []
    duplikaty = 0

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT data, przebieg, kwota FROM tankowania WHERE auto_id=?", (auto_id,))
        istniejace = {(str(d or ""), int(p or 0), round(float(k or 0), 2)) for d, p, k in c.fetchall()}

    def wartosc(wiersz, pole):
        idx = mapowanie.get(pole)
        if idx is None or idx >= len(wiersz):
            return ""
        return wiersz[idx]

    for nr, wiersz in enumerate(wiersze, start=2):  # +1 za nagłówek, +1 bo numerujemy od 1
        data_txt = _parsuj_date_csv(wartosc(wiersz, "data"))
        if not data_txt:
            bledy.append((nr, "nieczytelna albo pusta data"))
            continue

        litry = _parsuj_liczbe_csv(wartosc(wiersz, "litry"))
        kwota = _parsuj_liczbe_csv(wartosc(wiersz, "kwota"))
        if litry is None or litry <= 0:
            bledy.append((nr, "brak lub zerowa ilość paliwa/energii"))
            continue
        if kwota is None or kwota <= 0:
            bledy.append((nr, "brak lub zerowa kwota"))
            continue

        przebieg = _parsuj_liczbe_csv(wartosc(wiersz, "przebieg"))
        dystans = _parsuj_liczbe_csv(wartosc(wiersz, "dystans"))
        przebieg_i = int(przebieg) if przebieg and przebieg > 0 else 0
        dystans_f = float(dystans) if dystans and dystans > 0 else 0.0
        if przebieg_i <= 0 and dystans_f <= 0:
            bledy.append((nr, "brak przebiegu i dystansu — nie da się umiejscowić wpisu"))
            continue

        klucz = (data_txt, przebieg_i, round(kwota, 2))
        if klucz in istniejace:
            duplikaty += 1
            continue
        istniejace.add(klucz)

        idx_pelna = mapowanie.get("do_pelna")
        do_pelna = 1 if (idx_pelna is None or _prawda_csv(wartosc(wiersz, "do_pelna"))) else 0

        gotowe.append({
            "data": data_txt,
            "przebieg": przebieg_i,
            "dystans": dystans_f,
            "litry": float(litry),
            "kwota": float(kwota),
            "do_pelna": do_pelna,
            "stacja": " ".join(str(wartosc(wiersz, "stacja") or "").split()),
            "rodzaj_energii": _rozpoznaj_rodzaj_csv(wartosc(wiersz, "rodzaj_energii"), auto_id),
        })

    gotowe.sort(key=lambda g: (parsuj_date(g["data"]), g["przebieg"]))
    return {"gotowe": gotowe, "duplikaty": duplikaty, "bledy": bledy}


def zaimportuj_tankowania(auto_id, gotowe):
    """Wstawia przygotowane wcześniej wiersze. Zwraca liczbę dodanych wpisów.
    Nie dotyka zdalne_id — nowe wpisy pójdą do chmury przy najbliższym syncu."""
    if not auto_id or not gotowe:
        return 0
    kto = pobierz_moje_imie()
    with polacz_baze() as conn:
        for g in gotowe:
            conn.execute(
                "INSERT INTO tankowania (auto_id, data, przebieg, dystans, litry, kwota, do_pelna, stacja, "
                "rodzaj_energii, dodane_przez) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (auto_id, g["data"], g["przebieg"], g["dystans"], g["litry"],
                 g["kwota"], g["do_pelna"], g["stacja"] or None,
                 g.get("rodzaj_energii") or domyslny_rodzaj_energii(auto_id), kto)
            )
    return len(gotowe)


# ==================== IMPORT CSV — POZOSTAŁE TYPY ====================
# Ten sam mechanizm, co dla tankowań (wczytanie pliku, dopasowanie kolumn,
# walidacja, deduplikacja), tylko sparametryzowany typem wpisu. Dzięki temu
# dołożenie kolejnego typu to jeden wpis w TYPY_IMPORTU, a nie kopia widoku.

POLA_IMPORTU_INNYCH_KOSZTOW = {
    "data": ("Data", True),
    "nazwa": ("Opis / nazwa", True),
    "kwota": ("Kwota", True),
    "tagi": ("Tagi / kategoria", False),
}

POLA_IMPORTU_ODCZYTOW = {
    "data": ("Data", True),
    "przebieg": ("Stan licznika (km)", True),
}

_ALIASY_IMPORTU_INNYCH = {
    "data": ["data", "date", "dzien", "dzień", "datum", "data wydatku"],
    "nazwa": ["nazwa", "opis", "description", "tytul", "tytuł", "name", "usluga", "usługa", "pozycja", "co"],
    "kwota": ["kwota", "koszt", "cena", "cost", "total", "price", "wartosc", "wartość", "suma"],
    "tagi": ["tagi", "tag", "kategoria", "category", "typ", "rodzaj", "grupa"],
}

_ALIASY_IMPORTU_ODCZYTOW = {
    "data": ["data", "date", "dzien", "dzień", "datum", "data odczytu"],
    "przebieg": ["przebieg", "licznik", "odometer", "odo", "mileage", "km", "stan licznika", "przebieg (km)"],
}


def _dopasuj_kolumny(naglowki, pola, aliasy):
    """Automatyczne zgadywanie, która kolumna pliku odpowiada któremu polu.
    Najpierw szukamy trafień DOKŁADNYCH, dopiero potem częściowych — inaczej
    „data odczytu” potrafiła zająć kolumnę przeznaczoną na „data”."""
    znormalizowane = [_normalizuj_naglowek(h) for h in naglowki]
    mapowanie = {pole: None for pole in pola}
    zajete = set()

    for pole in pola:
        lista_aliasow = aliasy.get(pole, [])
        for dokladne in (True, False):
            for i, h in enumerate(znormalizowane):
                if i in zajete or not h:
                    continue
                trafienie = (h in lista_aliasow) if dokladne else any(a in h for a in lista_aliasow)
                if trafienie:
                    mapowanie[pole] = i
                    zajete.add(i)
                    break
            if mapowanie[pole] is not None:
                break
    return mapowanie


def _wartosc_z_wiersza(wiersz, mapowanie, pole):
    idx = mapowanie.get(pole)
    if idx is None or idx >= len(wiersz):
        return ""
    return wiersz[idx]


def dopasuj_kolumny_innych_kosztow(naglowki):
    return _dopasuj_kolumny(naglowki, POLA_IMPORTU_INNYCH_KOSZTOW, _ALIASY_IMPORTU_INNYCH)


def dopasuj_kolumny_odczytow(naglowki):
    return _dopasuj_kolumny(naglowki, POLA_IMPORTU_ODCZYTOW, _ALIASY_IMPORTU_ODCZYTOW)


def przygotuj_import_innych_kosztow(auto_id, naglowki, wiersze, mapowanie):
    """Waliduje wiersze i odsiewa duplikaty względem tego, co już jest w bazie
    (ta sama data + nazwa + kwota). Nic nie zapisuje."""
    gotowe, bledy = [], []
    duplikaty = 0

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT data, nazwa, kwota FROM inne_koszty WHERE auto_id=?", (auto_id,))
        istniejace = {
            (str(d or ""), klucz_nazwy(n), round(float(k or 0), 2))
            for d, n, k in c.fetchall()
        }

    for nr, wiersz in enumerate(wiersze, start=2):
        data_txt = _parsuj_date_csv(_wartosc_z_wiersza(wiersz, mapowanie, "data"))
        if not data_txt:
            bledy.append((nr, "nieczytelna albo pusta data"))
            continue

        nazwa = normalizuj_nazwe(_wartosc_z_wiersza(wiersz, mapowanie, "nazwa"))
        if not nazwa:
            bledy.append((nr, "brak opisu / nazwy wydatku"))
            continue

        kwota = _parsuj_liczbe_csv(_wartosc_z_wiersza(wiersz, mapowanie, "kwota"))
        if kwota is None or kwota <= 0:
            bledy.append((nr, "brak lub zerowa kwota"))
            continue

        klucz = (data_txt, klucz_nazwy(nazwa), round(kwota, 2))
        if klucz in istniejace:
            duplikaty += 1
            continue
        istniejace.add(klucz)

        gotowe.append({
            "data": data_txt,
            "nazwa": nazwa,
            "kwota": float(kwota),
            "tagi": normalizuj_nazwe(_wartosc_z_wiersza(wiersz, mapowanie, "tagi")),
        })

    gotowe.sort(key=lambda g: (parsuj_date(g["data"]), g["nazwa"]))
    return {"gotowe": gotowe, "duplikaty": duplikaty, "bledy": bledy}


def zaimportuj_inne_koszty(auto_id, gotowe):
    if not auto_id or not gotowe:
        return 0
    kto = pobierz_moje_imie()
    with polacz_baze() as conn:
        for g in gotowe:
            conn.execute(
                "INSERT INTO inne_koszty (auto_id, data, kategoria, nazwa, kwota, tagi, dodane_przez) "
                "VALUES (?,?,?,?,?,?,?)",
                (auto_id, g["data"], "", g["nazwa"], g["kwota"], g["tagi"] or None, kto)
            )
    return len(gotowe)


def przygotuj_import_odczytow(auto_id, naglowki, wiersze, mapowanie):
    """Odczyty licznika: duplikatem jest ta sama data + ten sam przebieg.
    Dodatkowo odsiewamy wiersze z przebiegiem <= 0, bo taki odczyt nic nie wnosi,
    a psuje wyliczenia średniego dziennego przebiegu."""
    gotowe, bledy = [], []
    duplikaty = 0

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT data, przebieg FROM odczyty_przebiegu WHERE auto_id=?", (auto_id,))
        istniejace = {(str(d or ""), int(p or 0)) for d, p in c.fetchall()}

    for nr, wiersz in enumerate(wiersze, start=2):
        data_txt = _parsuj_date_csv(_wartosc_z_wiersza(wiersz, mapowanie, "data"))
        if not data_txt:
            bledy.append((nr, "nieczytelna albo pusta data"))
            continue

        przebieg = _parsuj_liczbe_csv(_wartosc_z_wiersza(wiersz, mapowanie, "przebieg"))
        if przebieg is None or przebieg <= 0:
            bledy.append((nr, "brak lub zerowy stan licznika"))
            continue

        klucz = (data_txt, int(przebieg))
        if klucz in istniejace:
            duplikaty += 1
            continue
        istniejace.add(klucz)

        gotowe.append({"data": data_txt, "przebieg": int(przebieg)})

    gotowe.sort(key=lambda g: (parsuj_date(g["data"]), g["przebieg"]))
    return {"gotowe": gotowe, "duplikaty": duplikaty, "bledy": bledy}


def zaimportuj_odczyty(auto_id, gotowe):
    if not auto_id or not gotowe:
        return 0
    with polacz_baze() as conn:
        for g in gotowe:
            conn.execute(
                "INSERT INTO odczyty_przebiegu (auto_id, data, przebieg) VALUES (?,?,?)",
                (auto_id, g["data"], g["przebieg"])
            )
    return len(gotowe)


# Rejestr typów importu: opisuje wszystko, czego potrzebuje widok /import.
# `podglad` buduje jednolinijkowy opis gotowego wpisu do sekcji podglądu.
TYPY_IMPORTU = {
    "tankowania": {
        "etykieta": "Tankowania",
        "opis": "Data, licznik, litry/kWh i kwota — historia z innej aplikacji tankowań.",
        "pola": POLA_IMPORTU_TANKOWAN,
        "dopasuj": dopasuj_kolumny_tankowan,
        "przygotuj": przygotuj_import_tankowan,
        "zapisz": zaimportuj_tankowania,
        "podglad": lambda g, jednostka: (
            f"{g['data']} • {g['przebieg']} km • {g['litry']:.2f} "
            f"{'kWh' if g.get('rodzaj_energii') == ENERGIA_PRAD else jednostka} • {g['kwota']:.2f}"
            + (f" • {g['stacja']}" if g.get("stacja") else "")
            + (f" • {ETYKIETY_RODZAJU.get(g.get('rodzaj_energii'), '')}" if g.get("rodzaj_energii") else "")
        ),
    },
    "inne_koszty": {
        "etykieta": "Inne koszty",
        "opis": "Ubezpieczenie, myjnia, autostrady, raty — data, opis i kwota.",
        "pola": POLA_IMPORTU_INNYCH_KOSZTOW,
        "dopasuj": dopasuj_kolumny_innych_kosztow,
        "przygotuj": przygotuj_import_innych_kosztow,
        "zapisz": zaimportuj_inne_koszty,
        "podglad": lambda g, jednostka: (
            f"{g['data']} • {g['nazwa']} • {g['kwota']:.2f}"
            + (f" • {g['tagi']}" if g.get("tagi") else "")
        ),
    },
    "odczyty": {
        "etykieta": "Odczyty licznika",
        "opis": "Sam stan licznika w czasie — przydatne, gdy tankowania prowadzisz gdzie indziej.",
        "pola": POLA_IMPORTU_ODCZYTOW,
        "dopasuj": dopasuj_kolumny_odczytow,
        "przygotuj": przygotuj_import_odczytow,
        "zapisz": zaimportuj_odczyty,
        "podglad": lambda g, jednostka: f"{g['data']} • {g['przebieg']} km",
    },
}