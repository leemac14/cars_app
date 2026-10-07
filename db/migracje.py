"""Tworzenie schematu bazy i drabinka migracji (init_db)."""

import os
import pathlib
import sqlite3
import tempfile
import zipfile

import log

from .stale import BAZA_DANYCH
from .pamiec import zanotuj_zmiane_danych
from .polaczenie import polacz_baze
from .daty import przelicz_daty_iso
from .ustawienia import pobierz_ustawienie, zapisz_ustawienie
from .zalaczniki import _upewnij_folder_zalacznikow, napraw_sciezki_zalacznikow, posprzataj_odroczone_zalaczniki
from .kosz import posprzataj_kosz


# Najwyższy numer migracji, jaki zna ta wersja aplikacji. Wypełnia go init_db()
# — patrz wersja_schematu_aplikacji() na dole pliku.
WERSJA_SCHEMATU = None

# Tabele z `data_iso` na stan wersji 44 — ZAMROŻONE: baza migrowana od zera nie ma
# jeszcze w tym miejscu tabel z późniejszych wersji (np. szkice, 46).
_TABELE_DATY_ISO_WERSJI_44 = (
    "tankowania", "inne_koszty", "wizyty", "historia",
    "odczyty_przebiegu", "rozliczenia", "zdjecia_karoserii", "zadania",
)


def init_db():
    """Foldery i schemat bazy — wyłącznie to, bez czego nie da się narysować
    pierwszego ekranu.

    Sprzątanie (kosz, odroczone załączniki, jednorazowa naprawa ścieżek)
    przeniosło się do `porzadki_startowe()`, bo pierwszy piksel na nie nie czeka
    — patrz komentarz przy tamtej funkcji."""
    _upewnij_folder_zalacznikow()
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
            # Wersja 19: synchronizacja EDYCJI i USUNIĘĆ. zdalny_hash — hash treści
            # ostatnio zsynchronizowanej (różnica = edycja do wypchnięcia);
            # zdalne_nagrobki — kolejka usunięć do wysłania na serwer, bez auto_id.
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
            # Wersja 21: kto dodał wpis — nazwa z Ustawień (pobierz_moje_imie), bo
            # anonimowe logowanie Supabase nie niesie nazwy. Puste dla starszych wpisów.
            """
            ALTER TABLE tankowania ADD COLUMN dodane_przez TEXT;
            ALTER TABLE historia ADD COLUMN dodane_przez TEXT;
            ALTER TABLE wizyty ADD COLUMN dodane_przez TEXT;
            ALTER TABLE inne_koszty ADD COLUMN dodane_przez TEXT;
            """,
            # Wersja 22: indeksy pod synchronizację (WHERE auto_id=? AND zdalne_id IS
            # [NOT] NULL); idx_historia_zdalne osobno, bo historia nie ma auto_id.
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
            # views/formularze) — puste dla wpisów, które nigdy nie były edytowane.
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
            # (patrz views/ekran_glowny/naglowek_auta.py).
            """
            ALTER TABLE samochody ADD COLUMN wiadomosc_statusu TEXT;
            """,
            # Wersja 25: synchronizacja wizyta_czesci_magazynu; bez auto_id, jak
            # historia (pojazd przez wizyta_id).
            """
            ALTER TABLE wizyta_czesci_magazynu ADD COLUMN zdalne_id TEXT;
            ALTER TABLE wizyta_czesci_magazynu ADD COLUMN zdalny_hash TEXT;
            CREATE INDEX IF NOT EXISTS idx_wizyta_czesci_magazynu_zdalne ON wizyta_czesci_magazynu(zdalne_id);
            """,
            # Wersja 26: (a) progi powiadomień per podzespół (NULL = globalne z
            # Ustawień); (b) kolumny synchronizacji własnych pakietów serwisowych.
            """
            ALTER TABLE zadania ADD COLUMN prog_km INTEGER;
            ALTER TABLE zadania ADD COLUMN prog_dni INTEGER;
            ALTER TABLE pakiety_serwisowe_wlasne ADD COLUMN zdalne_id TEXT;
            ALTER TABLE pakiety_serwisowe_wlasne ADD COLUMN zdalny_hash TEXT;
            CREATE INDEX IF NOT EXISTS idx_pakiety_wlasne_auto_zdalne ON pakiety_serwisowe_wlasne(auto_id, zdalne_id);
            """,
            # Wersja 27: (a) gwarancja pojazdu (wzorzec AC/Assistance + limit km); (b)
            # kolejka offline auto-synchronizacji, UNIQUE na auto_id.
            """
            ALTER TABLE samochody ADD COLUMN gwarancja_data TEXT;
            ALTER TABLE samochody ADD COLUMN gwarancja_przebieg INTEGER;
            CREATE TABLE IF NOT EXISTS kolejka_sync (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, powod TEXT, proby INTEGER NOT NULL DEFAULT 0, ostatnia_proba TEXT, nastepna_proba TEXT, ostatni_blad TEXT);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_kolejka_sync_auto ON kolejka_sync(auto_id);
            """,
            # Wersja 28: cykliczne przypomnienia bez kosztu. czy_koszt=1 (domyślnie) —
            # „Zapłacone” dopisuje koszt; czy_koszt=0 — „Wykonano” tylko przesuwa
            # termin.
            """
            ALTER TABLE wydatki_cykliczne ADD COLUMN czy_koszt INTEGER NOT NULL DEFAULT 1;
            """,
            # Wersja 29: kosz na usunięte pojazdy — cały pojazd jako JSON w 'migawka',
            # zdjęcia w FOLDER_KOSZ, 'pliki' = mapa [ścieżka_w_koszu, oryginalna].
            # Nagrobki CELOWO dopiero przy trwałym skasowaniu. 'schemat_wersja' pozwala
            # pominąć przy przywracaniu kolumny, których już nie ma.
            """
            CREATE TABLE IF NOT EXISTS kosz_pojazdy (id INTEGER PRIMARY KEY AUTOINCREMENT, nazwa TEXT NOT NULL, data_usuniecia TEXT NOT NULL, migawka TEXT NOT NULL, pliki TEXT, liczba_wpisow INTEGER NOT NULL DEFAULT 0, rozmiar_plikow INTEGER NOT NULL DEFAULT 0, schemat_wersja INTEGER);
            CREATE INDEX IF NOT EXISTS idx_kosz_data ON kosz_pojazdy(data_usuniecia);
            """,
            # Wersja 30: zużycie części przy POJEDYNCZYM wpisie serwisowym — osobna
            # tabela (wizyta_id jest NOT NULL), lustrzana do wizyta_czesci_magazynu,
            # więc sync i kosz to ten sam kod.
            """
            CREATE TABLE IF NOT EXISTS historia_czesci_magazynu (id INTEGER PRIMARY KEY AUTOINCREMENT, historia_id INTEGER NOT NULL, magazyn_id INTEGER NOT NULL, ilosc_uzyta REAL NOT NULL DEFAULT 1, zdalne_id TEXT, zdalny_hash TEXT, FOREIGN KEY (historia_id) REFERENCES historia(id) ON DELETE CASCADE, FOREIGN KEY (magazyn_id) REFERENCES magazyn_czesci(id) ON DELETE CASCADE);
            CREATE INDEX IF NOT EXISTS idx_historia_czesci_historia ON historia_czesci_magazynu(historia_id);
            CREATE INDEX IF NOT EXISTS idx_historia_czesci_magazyn ON historia_czesci_magazynu(magazyn_id);
            CREATE INDEX IF NOT EXISTS idx_historia_czesci_zdalne ON historia_czesci_magazynu(zdalne_id);
            """,
            # Wersja 31: drzemka pojedynczego powiadomienia. Klucz = stabilny
            # identyfikator (_klucz_powiadomienia), nie treść. Świadomie bez
            # synchronizacji i kosza — sprawa tego urządzenia.
            """
            CREATE TABLE IF NOT EXISTS wyciszone_powiadomienia (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, klucz TEXT NOT NULL, do_dnia TEXT NOT NULL, tytul TEXT, utworzono TEXT, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_wyciszone_klucz ON wyciszone_powiadomienia(auto_id, klucz);
            """,
            # Wersja 32: typ nadwozia — sylwetka na krążku w selektorze pojazdów; puste
            # = ogólna ikona.
            """
            ALTER TABLE samochody ADD COLUMN nadwozie TEXT;
            """,
            # Wersja 33: paliwo i prąd osobno. 'rodzaj_energii' ('paliwo'/'prad') przy
            # każdym wpisie 'tankowania', 'typ_ladowania' (AC/DC); bateria i deklarowany
            # zasięg do szacunku realnego zasięgu.
            """
            ALTER TABLE tankowania ADD COLUMN rodzaj_energii TEXT;
            ALTER TABLE tankowania ADD COLUMN typ_ladowania TEXT;
            ALTER TABLE samochody ADD COLUMN pojemnosc_baterii TEXT;
            ALTER TABLE samochody ADD COLUMN zasieg_ev TEXT;
            CREATE INDEX IF NOT EXISTS idx_tankowania_auto_rodzaj ON tankowania(auto_id, rodzaj_energii);
            """,
            # Wersja 34: notatka przy POJEDYNCZYM wpisie, wolny tekst, nigdzie się nie
            # agreguje. Kolumny w rekordzie, nie osobna tabela — sync, kosz, cofanie i
            # eksport dostają ją za darmo. 'notatka_autor' i 'notatka_data' niezależne
            # od autora wpisu (uwagę dopisuje zwykle ktoś inny). Wizyty, zadania,
            # magazyn, opony i warsztaty mają własne pole opisu.
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
            # Wersja 35: (a) 'pojemnosc_baku' — TEKST jak reszta specyfikacji, czytany
            # przez _liczba_lub_none; (b) budżety: limit per pojazd, kategoria
            # (paliwo/serwis/inne/razem) i okres; UNIQUE (auto_id, kategoria, okres) —
            # zapis to upsert; synchronizowane.
            """
            ALTER TABLE samochody ADD COLUMN pojemnosc_baku TEXT;
            CREATE TABLE IF NOT EXISTS budzety (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, kategoria TEXT NOT NULL, okres TEXT NOT NULL, kwota REAL NOT NULL DEFAULT 0, zdalne_id TEXT, zdalny_hash TEXT, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_budzety_klucz ON budzety(auto_id, kategoria, okres);
            CREATE INDEX IF NOT EXISTS idx_budzety_zdalne ON budzety(zdalne_id);
            """,
            # Wersja 36: źródło własnego odczytu licznika (ręczny, kokpit, korekta przy
            # danych pojazdu, import). NULL = sprzed wersji, traktowany jako ręczny.
            """
            ALTER TABLE odczyty_przebiegu ADD COLUMN zrodlo TEXT;
            """,
            # Wersja 37: dane pojazdu — (a) zakup i wartość (rachunek posiadania), (b)
            # ubezpieczenie i assistance, (c) ściągawka (kod lakieru, rozmiary, moment
            # dokręcania), (d) pierwsza rejestracja (z niej wiek i roczny przebieg).
            # Kolumny pojazdu, jadą do partnera jak reszta.
            """
            ALTER TABLE samochody ADD COLUMN data_zakupu TEXT;
            ALTER TABLE samochody ADD COLUMN cena_zakupu REAL;
            ALTER TABLE samochody ADD COLUMN przebieg_zakupu INTEGER;
            ALTER TABLE samochody ADD COLUMN wartosc_szacowana REAL;
            ALTER TABLE samochody ADD COLUMN ubezpieczyciel TEXT;
            ALTER TABLE samochody ADD COLUMN nr_polisy TEXT;
            ALTER TABLE samochody ADD COLUMN skladka_roczna REAL;
            ALTER TABLE samochody ADD COLUMN telefon_assistance TEXT;
            ALTER TABLE samochody ADD COLUMN kod_lakieru TEXT;
            ALTER TABLE samochody ADD COLUMN rozmiar_opon TEXT;
            ALTER TABLE samochody ADD COLUMN rozmiar_felg TEXT;
            ALTER TABLE samochody ADD COLUMN rozstaw_srub TEXT;
            ALTER TABLE samochody ADD COLUMN moment_dokrecania TEXT;
            ALTER TABLE samochody ADD COLUMN typ_zlacza_ev TEXT;
            ALTER TABLE samochody ADD COLUMN data_pierwszej_rejestracji TEXT;
            """,
            # Wersja 38: pamięć nawigacji. Aplikacja urosła do kilkudziesięciu
            # ekranów i o tym, co pokazać na skróty, ma decydować to, z czego
            # użytkownik faktycznie korzysta, a nie kolejność w kodzie.
            # `przypiety` to ręczny wybór na Kokpit, `licznik`/`ostatnio` —
            # automatyczna lista „Ostatnio używane”.
            """
            CREATE TABLE IF NOT EXISTS ekrany_uzycie (ekran_id TEXT PRIMARY KEY, licznik INTEGER NOT NULL DEFAULT 0, ostatnio TEXT, przypiety INTEGER NOT NULL DEFAULT 0, kolejnosc INTEGER NOT NULL DEFAULT 0);
            """,
            # Wersja 39:
            # (a) `wydatki_cykliczne.typ` — wpis 'opony' po wykonaniu przestawia komplet
            # w magazynie (przelacz_zestaw_sezonowy); domyślne 'wydatek'.
            # (b) `trasy_szablony` — parametry kalkulatora bez ceny paliwa i spalania
            # (te zawsze aktualne).
            # (c) `checklisty` + `checklisty_pozycje` — wielokrotnego użytku; stan
            # ptaszka w pozycji.
            # (d) `samochody.status` z DEFAULT 'aktywny' + data i cena sprzedaży —
            # filtrują tylko miejsca wypisujące listę pojazdów.
            """
            ALTER TABLE wydatki_cykliczne ADD COLUMN typ TEXT DEFAULT 'wydatek';

            CREATE TABLE IF NOT EXISTS trasy_szablony (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, nazwa TEXT NOT NULL, dystans REAL NOT NULL DEFAULT 0, powrot INTEGER NOT NULL DEFAULT 0, osoby INTEGER NOT NULL DEFAULT 1, oplaty REAL NOT NULL DEFAULT 0, notatki TEXT, zdalne_id TEXT, zdalny_hash TEXT, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE);
            CREATE INDEX IF NOT EXISTS idx_trasy_szablony_auto ON trasy_szablony(auto_id);
            CREATE INDEX IF NOT EXISTS idx_trasy_szablony_auto_zdalne ON trasy_szablony(auto_id, zdalne_id);

            CREATE TABLE IF NOT EXISTS checklisty (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, nazwa TEXT NOT NULL, opis TEXT, ostatnie_uzycie TEXT, zdalne_id TEXT, zdalny_hash TEXT, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE);
            CREATE INDEX IF NOT EXISTS idx_checklisty_auto ON checklisty(auto_id);
            CREATE INDEX IF NOT EXISTS idx_checklisty_auto_zdalne ON checklisty(auto_id, zdalne_id);

            CREATE TABLE IF NOT EXISTS checklisty_pozycje (id INTEGER PRIMARY KEY AUTOINCREMENT, checklista_id INTEGER NOT NULL, tresc TEXT NOT NULL, kolejnosc INTEGER NOT NULL DEFAULT 0, odhaczone INTEGER NOT NULL DEFAULT 0, zdalne_id TEXT, zdalny_hash TEXT, FOREIGN KEY (checklista_id) REFERENCES checklisty(id) ON DELETE CASCADE);
            CREATE INDEX IF NOT EXISTS idx_checklisty_pozycje_lista ON checklisty_pozycje(checklista_id);

            ALTER TABLE samochody ADD COLUMN status TEXT DEFAULT 'aktywny';
            ALTER TABLE samochody ADD COLUMN data_sprzedazy TEXT;
            ALTER TABLE samochody ADD COLUMN cena_sprzedazy REAL;
            """,
            # Wersja 40: role przy współdzieleniu.
            # (a) `rola_wspoldzielenia`: 'wlasciciel' (domyślnie), 'pelna', 'wspolautor'
            # (swoje wpisy), 'podglad' (nic nie wysyła).
            # (b) `kod_wspolautora` / `kod_podgladu` — NIEZALEŻNE losowe kody u
            # właściciela (wariant kodu głównego dałoby się odgadnąć).
            # (c) `znacznik_delty` — najwyższy `zaktualizowano` z serwera (bez niego
            # każda synchronizacja ściągała wszystko).
            # (d) `zdalne_nagrobki.auto_id` + `proby` — nagrobki tylko z
            # synchronizowanego auta; odrzucany przez serwer nie próbuje w
            # nieskończoność.
            """
            ALTER TABLE samochody ADD COLUMN rola_wspoldzielenia TEXT DEFAULT 'wlasciciel';
            ALTER TABLE samochody ADD COLUMN kod_wspolautora TEXT;
            ALTER TABLE samochody ADD COLUMN kod_podgladu TEXT;
            ALTER TABLE samochody ADD COLUMN znacznik_delty TEXT;

            ALTER TABLE zdalne_nagrobki ADD COLUMN auto_id INTEGER;
            ALTER TABLE zdalne_nagrobki ADD COLUMN proby INTEGER NOT NULL DEFAULT 0;
            CREATE INDEX IF NOT EXISTS idx_zdalne_nagrobki_auto ON zdalne_nagrobki(auto_id);
            """,
            # Wersja 41: koszt części z magazynu doliczany do serwisu.
            # (a) `magazyn_czesci.cena_jednostkowa` — osobno od `cena` (koszt CAŁEGO
            # zakupu), bo starsza wersja na drugim telefonie dalej czyta `cena` po
            # staremu.
            # (b) `koszt` przy zużyciu — ile z kosztu rekordu przyszło z magazynu,
            # zamrożone w chwili zapisu; NULL = „nie doliczone” (stare zużycia, wstecz
            # nic się nie dolicza).
            """
            ALTER TABLE magazyn_czesci ADD COLUMN cena_jednostkowa REAL;
            ALTER TABLE wizyta_czesci_magazynu ADD COLUMN koszt REAL;
            ALTER TABLE historia_czesci_magazynu ADD COLUMN koszt REAL;
            """,
            # Wersja 42: robocizna osobno (wizyta i pojedynczy wpis); NULL = bez
            # podziału. Części nie mają kolumny — to reszta po robociźnie i magazynie,
            # więc zawsze się sumuje (trzecia kwota rozjeżdżałaby się po edycjach
            # starszą wersją, zwrotach i usunięciach).
            """
            ALTER TABLE wizyty ADD COLUMN koszt_robocizny REAL;
            ALTER TABLE historia ADD COLUMN koszt_robocizny REAL;
            """,
            # Wersja 43: rozliczenia współdzielonego auta. Rozliczenie to migawka, NIE
            # data odcięcia: `salda` (grosze), `uczestnicy`, `przelewy`. Saldo = cała
            # podpisana historia minus migawki, więc późniejsza zmiana starego wpisu
            # trafia do bieżącego salda. `klucz` i `poprzednie` tworzą łańcuch — dwa
            # „Rozliczone” z tym samym poprzednikiem liczą się raz.
            """
            CREATE TABLE IF NOT EXISTS rozliczenia (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, data TEXT NOT NULL, uczestnicy TEXT NOT NULL DEFAULT '[]', salda TEXT NOT NULL DEFAULT '{}', przelewy TEXT NOT NULL DEFAULT '[]', notatka TEXT, klucz TEXT, poprzednie TEXT, dodane_przez TEXT, data_utworzenia TEXT, zdalne_id TEXT, zdalny_hash TEXT, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE);
            CREATE INDEX IF NOT EXISTS idx_rozliczenia_auto ON rozliczenia(auto_id);
            CREATE INDEX IF NOT EXISTS idx_rozliczenia_auto_zdalne ON rozliczenia(auto_id, zdalne_id);
            """,
            # Wersja 44: `data_iso` (RRRR-MM-DD) obok `data` (DD.MM.RRRR) — zakresy i
            # sortowanie w SQL. Indeks historii przez podzespół (brak auto_id).
            # Istniejące wiersze wypełnia blok `if i == 43` niżej, późniejsze zapisy —
            # kod (db/daty.py).
            """
            ALTER TABLE tankowania ADD COLUMN data_iso TEXT;
            ALTER TABLE inne_koszty ADD COLUMN data_iso TEXT;
            ALTER TABLE wizyty ADD COLUMN data_iso TEXT;
            ALTER TABLE historia ADD COLUMN data_iso TEXT;
            ALTER TABLE odczyty_przebiegu ADD COLUMN data_iso TEXT;
            ALTER TABLE rozliczenia ADD COLUMN data_iso TEXT;
            ALTER TABLE zdjecia_karoserii ADD COLUMN data_iso TEXT;
            ALTER TABLE zadania ADD COLUMN data_iso TEXT;
            CREATE INDEX IF NOT EXISTS idx_tankowania_auto_data_iso ON tankowania(auto_id, data_iso);
            CREATE INDEX IF NOT EXISTS idx_inne_koszty_auto_data_iso ON inne_koszty(auto_id, data_iso);
            CREATE INDEX IF NOT EXISTS idx_wizyty_auto_data_iso ON wizyty(auto_id, data_iso);
            CREATE INDEX IF NOT EXISTS idx_historia_zadanie_data_iso ON historia(zadanie_id, data_iso);
            CREATE INDEX IF NOT EXISTS idx_odczyty_przebiegu_auto_data_iso ON odczyty_przebiegu(auto_id, data_iso);
            CREATE INDEX IF NOT EXISTS idx_rozliczenia_auto_data_iso ON rozliczenia(auto_id, data_iso);
            CREATE INDEX IF NOT EXISTS idx_zdjecia_karoserii_auto_data_iso ON zdjecia_karoserii(auto_id, data_iso);
            CREATE INDEX IF NOT EXISTS idx_zadania_auto_data_iso ON zadania(auto_id, data_iso);
            """,
            # Wersja 45: gwarancja naprawy — data końca (DD.MM.RRRR) i licznik w km;
            # obowiązuje to, co skończy się pierwsze, NULL w obu = bez gwarancji. Liczy
            # się gwarancja WPISU (też pozycji wizyty); para kolumn wizyty to „gwarancja
            # wspólna” formularza — przechodzi na pozycje, które ją mają, a pozycja z
            # wyjątkiem zostaje przy swojej.
            """
            ALTER TABLE historia ADD COLUMN gwarancja_data TEXT;
            ALTER TABLE historia ADD COLUMN gwarancja_przebieg INTEGER;
            ALTER TABLE wizyty ADD COLUMN gwarancja_data TEXT;
            ALTER TABLE wizyty ADD COLUMN gwarancja_przebieg INTEGER;
            """,
            # Wersja 46: kolejka „do wpisania” (M-08) — szkic to OSOBNA tabela (wpis bez
            # kwot rozjechałby statystyki, eksport i sync); `rodzaj`, `przebieg` (km),
            # `opis` opcjonalne. Tabela lokalna — zdjęcia nie jadą do chmury (N-06).
            """
            CREATE TABLE IF NOT EXISTS szkice_wpisow (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, data TEXT NOT NULL, data_iso TEXT, godzina TEXT, zalacznik TEXT, rodzaj TEXT, przebieg INTEGER, opis TEXT, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE);
            CREATE INDEX IF NOT EXISTS idx_szkice_wpisow_auto_data_iso ON szkice_wpisow(auto_id, data_iso);
            """,
            # Wersja 47: notatka „najlepsza oferta OC/AC” — tekst pojazdu (cena i
            # towarzystwo) + data ostatniej zmiany (dd.mm.rrrr). Kolumny pojazdu, jadą w
            # KOLUMNY_POJAZDU; NULL = brak notatki.
            """
            ALTER TABLE samochody ADD COLUMN oferta_oc_ac TEXT;
            ALTER TABLE samochody ADD COLUMN oferta_oc_ac_data TEXT;
            """,
            # Wersja 48: historia cen części (M-15). `ceny_czesci` — dziennik zakupów
            # pojazdu (nazwa, data, cena za jednostkę, ilość, sklep), grupowany po
            # klucz_nazwy, bez klucza obcego (przeżywa usuniętą pozycję); pusta `data` =
            # zakup bez daty. Bieżące ceny magazynu NIE są przepisywane — liczą się w
            # locie (db/ceny_czesci.py), inaczej dwa telefony zdublowałyby zakupy. Sklep
            # i link należą do pozycji.
            """
            ALTER TABLE magazyn_czesci ADD COLUMN sklep TEXT;
            ALTER TABLE magazyn_czesci ADD COLUMN link TEXT;
            CREATE TABLE IF NOT EXISTS ceny_czesci (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, nazwa TEXT NOT NULL, data TEXT NOT NULL DEFAULT '', data_iso TEXT, cena_jednostkowa REAL NOT NULL, jednostka TEXT DEFAULT 'szt', ilosc REAL, sklep TEXT, zdalne_id TEXT, zdalny_hash TEXT, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE);
            CREATE INDEX IF NOT EXISTS idx_ceny_czesci_auto_data_iso ON ceny_czesci(auto_id, data_iso);
            CREATE INDEX IF NOT EXISTS idx_ceny_czesci_auto_zdalne ON ceny_czesci(auto_id, zdalne_id);
            """,
            # Wersja 49: harmonogram leasingu i kredytu (M-22). Umowa w TYM SAMYM
            # wierszu `wydatki_cykliczne` (rodzaj 'leasing'/'kredyt').
            # `zaplacone_platnosci` — zapłacone pozycje harmonogramu (raty, potem wykup
            # lub balon); `oprocentowanie` (roczne, %) tylko przy ratach z
            # oprocentowania i malejących. Daty dd.mm.rrrr; w zwykłych wpisach wszystko
            # NULL.
            """
            ALTER TABLE wydatki_cykliczne ADD COLUMN liczba_rat INTEGER;
            ALTER TABLE wydatki_cykliczne ADD COLUMN zaplacone_platnosci INTEGER;
            ALTER TABLE wydatki_cykliczne ADD COLUMN data_pierwszej_raty TEXT;
            ALTER TABLE wydatki_cykliczne ADD COLUMN kwota_finansowania REAL;
            ALTER TABLE wydatki_cykliczne ADD COLUMN oplata_wstepna REAL;
            ALTER TABLE wydatki_cykliczne ADD COLUMN wykup REAL;
            ALTER TABLE wydatki_cykliczne ADD COLUMN oprocentowanie REAL;
            ALTER TABLE wydatki_cykliczne ADD COLUMN rodzaj_rat TEXT;
            """,
            # Wersja 50: ewidencja przebiegu (N-01). Przejazd: data, skąd, dokąd, cel,
            # km (CAŁY przejazd), służbowy/prywatny, kierowca (tekst); `licznik` (km,
            # opcjonalny) — stan po przejeździe, źródło historii licznika; notatka z
            # podpisem. Trasy kalkulatora dostają skąd, dokąd, cel i rodzaj (NULL w
            # starych = nie dotyczy).
            """
            CREATE TABLE IF NOT EXISTS przejazdy (id INTEGER PRIMARY KEY AUTOINCREMENT, auto_id INTEGER NOT NULL, data TEXT NOT NULL, data_iso TEXT, skad TEXT, dokad TEXT, cel TEXT, km REAL NOT NULL DEFAULT 0, powrot INTEGER NOT NULL DEFAULT 0, sluzbowy INTEGER NOT NULL DEFAULT 1, kierowca TEXT, licznik INTEGER, notatka TEXT, notatka_autor TEXT, notatka_data TEXT, dodane_przez TEXT, zdalne_id TEXT, zdalny_hash TEXT, FOREIGN KEY (auto_id) REFERENCES samochody(id) ON DELETE CASCADE);
            CREATE INDEX IF NOT EXISTS idx_przejazdy_auto_data_iso ON przejazdy(auto_id, data_iso);
            CREATE INDEX IF NOT EXISTS idx_przejazdy_auto_zdalne ON przejazdy(auto_id, zdalne_id);
            ALTER TABLE trasy_szablony ADD COLUMN skad TEXT;
            ALTER TABLE trasy_szablony ADD COLUMN dokad TEXT;
            ALTER TABLE trasy_szablony ADD COLUMN cel TEXT;
            ALTER TABLE trasy_szablony ADD COLUMN sluzbowy INTEGER;
            """
        ]

        # Zapamiętane dla wersja_schematu_aplikacji(): `migracje` jest zmienną
        # lokalną, więc poza tym miejscem nikt tej liczby nie zobaczy. Ustawiamy
        # ją PRZED pętlą, bo przy bazie już aktualnej pętla nie wykona ani obrotu.
        global WERSJA_SCHEMATU
        WERSJA_SCHEMATU = len(migracje)

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

            # Jednorazowo po wersji 8: dotyczy_opon dla istniejących podzespołów ze
            # starej heurystyki nazw; rodzaj energii starych wpisów z typu paliwa
            # POJAZDU.
            if i == 32:
                cursor.execute(
                    "UPDATE tankowania SET rodzaj_energii = CASE WHEN auto_id IN "
                    "(SELECT id FROM samochody WHERE typ_paliwa='Elektryczny') THEN 'prad' ELSE 'paliwo' END "
                    "WHERE rodzaj_energii IS NULL"
                )

            # Układ zakładek zmienił się z „Serwis / Paliwo / Inne / Statystyki”
            # na „Kokpit / Serwis / Koszty / Analiza”. Bez przeliczenia ktoś, kto
            # skończył na Paliwie, dostałby po aktualizacji Serwis — numer został
            # ten sam, ale znaczy już co innego.
            if i == 37:
                MAPA_ZAKLADEK = {"0": "1", "1": "2", "2": "2", "3": "3"}
                cursor.execute("SELECT wartosc FROM ustawienia WHERE klucz='ostatnia_zakladka'")
                w_zak = cursor.fetchone()
                if w_zak:
                    stara = str(w_zak[0] or "0").strip()
                    cursor.execute(
                        "INSERT INTO ustawienia (klucz, wartosc) VALUES ('ostatnia_zakladka', ?) "
                        "ON CONFLICT(klucz) DO UPDATE SET wartosc=excluded.wartosc",
                        (MAPA_ZAKLADEK.get(stara, "0"),)
                    )
                    if stara == "2":
                        cursor.execute(
                            "INSERT INTO ustawienia (klucz, wartosc) VALUES ('ostatnia_podzakladka_kosztow', '1') "
                            "ON CONFLICT(klucz) DO UPDATE SET wartosc=excluded.wartosc"
                        )

            # Kolumna status dodana ALTER-em ma DEFAULT, ale istniejące wiersze
            # zostają z NULL-em w części wersji SQLite. NULL w statusie znaczyłby
            # „pojazd bez przynależności”, więc dopisujemy go wprost — tak samo
            # jak rodzaj energii w migracji 33.
            if i == 38:
                cursor.execute("UPDATE samochody SET status='aktywny' WHERE status IS NULL OR TRIM(status)=''")
                cursor.execute("UPDATE wydatki_cykliczne SET typ='wydatek' WHERE typ IS NULL OR TRIM(typ)=''")

            # Kolumna roli dostała DEFAULT, ale w części wersji SQLite
            # istniejące wiersze zostają z NULL-em — a NULL w roli znaczyłby
            # „nie wiadomo, co wolno”. Wszystko, co już jest w bazie, powstało
            # przed rolami i miało prawa pełne, więc dopisujemy je wprost.
            if i == 39:
                cursor.execute(
                    "UPDATE samochody SET rola_wspoldzielenia='wlasciciel' "
                    "WHERE rola_wspoldzielenia IS NULL OR TRIM(rola_wspoldzielenia)=''"
                )

            # Cena za jednostkę istniejących pozycji: kupiona ilość = stan na półce PLUS
            # wszystko, co z niej zeszło. Funkcja danych z chmury, więc drugi telefon
            # policzy to samo; bez ilości cena zostaje pusta.
            if i == 40:
                cursor.execute(
                    "SELECT m.id, m.cena, COALESCE(m.ilosc, 0)"
                    " + COALESCE((SELECT SUM(ilosc_uzyta) FROM wizyta_czesci_magazynu WHERE magazyn_id = m.id), 0)"
                    " + COALESCE((SELECT SUM(ilosc_uzyta) FROM historia_czesci_magazynu WHERE magazyn_id = m.id), 0)"
                    " FROM magazyn_czesci m WHERE m.cena IS NOT NULL AND m.cena_jednostkowa IS NULL"
                )
                for czesc_id, cena, kupiona in cursor.fetchall():
                    liczby = all(isinstance(x, (int, float)) for x in (cena, kupiona))
                    if liczby and kupiona > 0 and cena >= 0:
                        cursor.execute(
                            "UPDATE magazyn_czesci SET cena_jednostkowa=? WHERE id=?",
                            (round(cena / kupiona, 4), czesc_id)
                        )

            # `data_iso` dla istniejących wierszy — tą samą funkcją co każdy zapis;
            # nieczytelna data zostaje NULL (lista też jej nie widzi).
            if i == 43:
                przelicz_daty_iso(conn, tabele=_TABELE_DATY_ISO_WERSJI_44)

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

    # Plik bazy mógł właśnie zostać podmieniony w całości — wczytanie kopii
    # zapasowej kopiuje go z pominięciem polacz_baze, a kopia już zmigrowana nie
    # zapisze tu ani jednego wiersza. To, co policzono ze starego pliku (metryki
    # kokpitu, odznaki), musi więc zniknąć z pamięci wprost.
    zanotuj_zmiane_danych()


def porzadki_startowe() -> tuple[int, int]:
    """Sprzątanie po pierwszym renderze (wątek w tle w `main.py`): kasowanie odroczonych
    załączników, wygasłego kosza i jednorazowa naprawa ścieżek; zwraca (dopasowane,
    brakujące) z naprawy. Osobno od `init_db()`, bo ten chodzi też przy wczytywaniu
    kopii."""
    posprzataj_odroczone_zalaczniki()

    # Tabela kosza musi już istnieć, więc dopiero po migracjach. Wygasłe pozycje
    # kasujemy raz przy starcie, a nie przy każdym wejściu na ekran kosza:
    # retencja liczona jest w dniach, więc częściej nie ma sensu.
    posprzataj_kosz()

    # Jednorazowa naprawa ścieżek załączników z innego urządzenia
    # (/data/user/0/<pakiet>/files/...) — dla baz sprzed tej naprawy; wczytanie kopii
    # woła ją przy KAŻDYM imporcie (main.wykonaj_import).
    if pobierz_ustawienie("naprawa_sciezek_zalacznikow_v1") == "1":
        return 0, 0

    naprawione = brakujace = 0
    try:
        naprawione, brakujace = napraw_sciezki_zalacznikow()
    except Exception:
        # Brak zdjęć nie może uniemożliwić uruchomienia aplikacji.
        log.polkniety("jednorazowa naprawa ścieżek załączników")
    zapisz_ustawienie("naprawa_sciezek_zalacznikow_v1", "1")
    return naprawione, brakujace




# ============================================================================
# WERSJA SCHEMATU PRZY WCZYTYWANIU KOPII
# ============================================================================
# Migracje idą tylko w przód: kopia z nowszej wersji aplikacji wczytana w starszej po
# cichu gubi nowe kolumny. Wersję czytamy PRZED nadpisaniem.


def wersja_schematu_aplikacji() -> int:
    """Najwyższy numer schematu, jaki zna TA wersja aplikacji. Ustawia go `init_db()`
    (`migracje` jest lokalna — `tests/test_migracje.py` czyta ją z AST); wcześniej
    odczyt z bazy, zero = „nie wiadomo” (nic nie blokujemy)."""
    if WERSJA_SCHEMATU is not None:
        return WERSJA_SCHEMATU
    zapisana = str(pobierz_ustawienie("schema_version", "") or "").strip()
    return int(zapisana) if zapisana.isdigit() else 0


def wersja_schematu_pliku(sciezka) -> int | None:
    """Numer schematu bazy w PLIKU, otwartej tylko do odczytu. None = nie do odczytania
    (stara kopia bez ustawień, nie SQLite, brak dostępu) — co innego niż zero, przy
    którym migracje puszczą całą drabinkę."""
    try:
        adres = pathlib.Path(sciezka).resolve().as_uri() + "?mode=ro"
        polaczenie = sqlite3.connect(adres, uri=True)
    except (sqlite3.Error, ValueError, OSError):
        return None

    try:
        kursor = polaczenie.cursor()
        kursor.execute("SELECT wartosc FROM ustawienia WHERE klucz='schema_version'")
        wiersz = kursor.fetchone()
    except sqlite3.Error:
        return None
    finally:
        polaczenie.close()

    zapisana = str(wiersz[0] if wiersz else "").strip()
    return int(zapisana) if zapisana.isdigit() else None


def wersja_schematu_kopii(sciezka) -> int | None:
    """Numer schematu kopii zapasowej — pliku `.db` albo archiwum `.zip`.

    Z archiwum wypakowujemy SAM plik bazy: zdjęcia potrafią ważyć dziesiątki
    megabajtów, a do odczytania jednej liczby są niepotrzebne."""
    if not str(sciezka).lower().endswith(".zip"):
        return wersja_schematu_pliku(sciezka)

    nazwa_bazy = os.path.basename(BAZA_DANYCH)
    try:
        with zipfile.ZipFile(sciezka, "r") as archiwum:
            if nazwa_bazy not in archiwum.namelist():
                return None
            with tempfile.TemporaryDirectory() as katalog:
                archiwum.extract(nazwa_bazy, katalog)
                return wersja_schematu_pliku(os.path.join(katalog, nazwa_bazy))
    except (zipfile.BadZipFile, OSError, ValueError):
        return None


def sprawdz_kopie_przed_wczytaniem(sciezka) -> tuple[bool, str]:
    """(czy wolno wczytać, powód odmowy); pusty powód = wolno. Blokujemy WYŁĄCZNIE kopię
    NOWSZĄ (migracji w tył nie ma); starsza przechodzi, a nieczytelną zgłosi sam import."""
    try:
        wersja_pliku = wersja_schematu_kopii(sciezka)
    except Exception:
        log.polkniety("odczyt wersji schematu z wybranej kopii")
        return True, ""

    wersja_aplikacji = wersja_schematu_aplikacji()

    if wersja_pliku is None or not wersja_aplikacji:
        return True, ""

    if wersja_pliku > wersja_aplikacji:
        return False, (
            f"Ta kopia pochodzi z nowszej wersji aplikacji — ma schemat bazy "
            f"{wersja_pliku}, a ta aplikacja zna {wersja_aplikacji}. Wczytanie "
            "zostawiłoby bazę z polami, o których ten kod nie wie: przestałyby "
            "się wypełniać i nie jechałyby do chmury, a nic by tego nie zgłosiło. "
            "Zaktualizuj aplikację i spróbuj ponownie."
        )

    return True, ""



# `WERSJA_SCHEMATU` ŚWIADOMIE poza `__all__`: init_db() przypisuje ją na nowo
# przez `global`, więc kopia w `db` zamarzłaby na None (ta sama pułapka, którą
# opisuje tests/test_sync_pakiet.py). Z zewnątrz czyta się ją przez
# wersja_schematu_aplikacji().
__all__ = [
    "init_db",
    "porzadki_startowe",
    "sprawdz_kopie_przed_wczytaniem",
    "wersja_schematu_aplikacji",
    "wersja_schematu_kopii",
    "wersja_schematu_pliku",
]
