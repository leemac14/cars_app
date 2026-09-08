"""Tworzenie schematu bazy i drabinka migracji (init_db)."""

import os
import pathlib
import sqlite3
import tempfile
import zipfile

import log

from .stale import BAZA_DANYCH
from .polaczenie import polacz_baze
from .ustawienia import pobierz_ustawienie, zapisz_ustawienie
from .zalaczniki import _upewnij_folder_zalacznikow, napraw_sciezki_zalacznikow, posprzataj_odroczone_zalaczniki
from .kosz import posprzataj_kosz


# Najwyższy numer migracji, jaki zna ta wersja aplikacji. Wypełnia go init_db()
# — patrz wersja_schematu_aplikacji() na dole pliku.
WERSJA_SCHEMATU = None


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
            """,
            # Wersja 36: skąd wziął się odczyt licznika. Historia odczytów
            # pokazuje teraz WSZYSTKIE znane stany licznika — także te, które
            # aplikacja zebrała sama przy tankowaniu, wizycie i wpisie serwisowym
            # (te wynikają z samych tabel, bez nowych kolumn). Ta kolumna
            # rozstrzyga tylko wewnętrzny podział własnych odczytów: wpisany
            # ręcznie w historii, szybka aktualizacja z kokpitu, korekta przy
            # danych pojazdu czy import z pliku. NULL = wpis sprzed tej wersji,
            # traktowany jako ręczny — czyli dokładnie tym, czym wtedy był.
            """
            ALTER TABLE odczyty_przebiegu ADD COLUMN zrodlo TEXT;
            """,
            # Wersja 37: dane pojazdu, których dotąd nie było gdzie trzymać, a
            # których szuka się w konkretnych, powtarzalnych sytuacjach:
            # (a) ZAKUP I WARTOŚĆ — dopiero cena zakupu i dzisiejsza wartość
            #     domykają rachunek posiadania: samo paliwo i serwis pomijają
            #     największy koszt auta, czyli utratę wartości;
            # (b) UBEZPIECZENIE I POMOC — po stłuczce szuka się numeru polisy
            #     i telefonu do assistance, zwykle w emocjach i cudzym aucie;
            # (c) ŚCIĄGAWKA — kod lakieru przy zaprawce, rozmiar opon i felg
            #     przy zakupie, moment dokręcania i rozstaw śrub przy zmianie kół;
            # (d) PIERWSZA REJESTRACJA — z niej liczy się WIEK auta i roczny
            #     przebieg; sam rocznik potrafi się różnić od rejestracji o rok.
            # Wszystko jako kolumny pojazdu, bo to opis JEGO tożsamości i wszystko
            # leci do partnera tą samą drogą co reszta danych auta.
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
            # Wersja 39: pięć rzeczy, których dotąd nie było gdzie zapisać.
            #
            # (a) `wydatki_cykliczne.typ` — sezonowa zmiana opon przestaje być
            #     zwykłym wpisem w kalendarzu. Wpis typu 'opony' w chwili
            #     wykonania przestawia zamontowany komplet w magazynie opon
            #     (patrz przelacz_zestaw_sezonowy), czyli robi to, po co się go
            #     zakłada. Domyślne 'wydatek' zostawia wszystkie istniejące
            #     wpisy dokładnie tam, gdzie były.
            #
            # (b) `trasy_szablony` — trasa „Do teściów” liczona co miesiąc od
            #     nowa to za każdym razem te same 180 km wpisywane ręcznie.
            #     Szablon trzyma komplet parametrów kalkulatora poza ceną
            #     paliwa i spalaniem, bo TE mają się brać z aktualnych danych.
            #
            # (c) `checklisty` + `checklisty_pozycje` — lista wielokrotnego
            #     użytku, odhaczana przed wyjazdem i zerowana po powrocie.
            #     Osobno od `do_zrobienia`, gdzie pozycja znika po wykonaniu.
            #     Stan ptaszka siedzi w pozycji, bo to stan BIEŻĄCEGO przejścia.
            #
            # (d) `samochody.status` + data i cena sprzedaży — sprzedane auto
            #     znika z garażu, ale historia zostaje do wglądu i eksportu.
            #     Kolumna z DEFAULT 'aktywny' oznacza, że żadne z dziesiątek
            #     istniejących zapytań nie wymaga dopisania filtra — filtrują
            #     tylko cztery miejsca, które wypisują listę pojazdów.
            #     Cena sprzedaży domyka rachunek posiadania: to ona, a nie
            #     szacunek, mówi ile auto naprawdę kosztowało.
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
            # Wersja 40: role przy współdzieleniu pojazdu. Do tej pory kod
            # zaproszenia dawał dokładnie jedno uprawnienie — wszystko. Kto
            # dostał kod, mógł też skasować cudze tankowanie sprzed roku, a
            # jedyną granicą było zaufanie.
            #
            # (a) `rola_wspoldzielenia` mówi, czym JEST dla mnie ten pojazd:
            #     'wlasciciel' (ja go udostępniłem), 'pelna' (dołączyłem
            #     kodem pełnym — zachowanie dotychczasowe), 'wspolautor'
            #     (dopisuję swoje wpisy, cudzych nie ruszam) albo 'podglad'
            #     (tylko czytam; aplikacja nigdy nic nie wysyła). Domyślne
            #     'wlasciciel' zostawia wszystkie istniejące pojazdy dokładnie
            #     z tymi prawami, które miały do tej pory.
            #
            # (b) `kod_wspolautora` / `kod_podgladu` — dwa dodatkowe, NIEZALEŻNE
            #     kody zaproszenia trzymane u właściciela. Celowo losowe, a nie
            #     wyprowadzone z kodu głównego: gdyby były jego wariantem, gość
            #     z kodu podglądu odgadłby kod pełny i cała rola byłaby ozdobą.
            #
            # (c) `znacznik_delty` — najwyższy `zaktualizowano` pobrany
            #     z serwera. Bez niego każda synchronizacja ściągała komplet
            #     rekordów ze wszystkich tabel, za każdym razem, po komórce.
            #
            # (d) `zdalne_nagrobki.auto_id` + `proby` — nagrobek wiedział tylko
            #     CO usunąć, nie z którego pojazdu, więc przy synchronizacji
            #     auta A leciały też skasowania z auta B (w tym z pojazdu, do
            #     którego mam wyłącznie podgląd). `proby` zamyka drugą dziurę:
            #     nagrobek odrzucany przez serwer w nieskończoność (bo nie mam
            #     do niego prawa) próbował się wysłać przy każdej synchronizacji.
            """
            ALTER TABLE samochody ADD COLUMN rola_wspoldzielenia TEXT DEFAULT 'wlasciciel';
            ALTER TABLE samochody ADD COLUMN kod_wspolautora TEXT;
            ALTER TABLE samochody ADD COLUMN kod_podgladu TEXT;
            ALTER TABLE samochody ADD COLUMN znacznik_delty TEXT;

            ALTER TABLE zdalne_nagrobki ADD COLUMN auto_id INTEGER;
            ALTER TABLE zdalne_nagrobki ADD COLUMN proby INTEGER NOT NULL DEFAULT 0;
            CREATE INDEX IF NOT EXISTS idx_zdalne_nagrobki_auto ON zdalne_nagrobki(auto_id);
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

    # Jednorazowa naprawa ścieżek załączników przeniesionych z innego urządzenia.
    # Wczytanie kopii woła to samo wprost, przy KAŻDYM imporcie (patrz
    # main.wykonaj_import) — ten blok jest dla baz, które przyjechały z telefonu,
    # zanim naprawa w ogóle powstała, i mają w sobie ścieżki
    # /data/user/0/<pakiet>/files/data/zalaczniki/... wskazujące donikąd.
    if pobierz_ustawienie("naprawa_sciezek_zalacznikow_v1") != "1":
        try:
            napraw_sciezki_zalacznikow()
        except Exception:
            # Brak zdjęć nie może uniemożliwić uruchomienia aplikacji.
            log.polkniety("jednorazowa naprawa ścieżek załączników")
        zapisz_ustawienie("naprawa_sciezek_zalacznikow_v1", "1")




# ============================================================================
#  WERSJA SCHEMATU PRZY WCZYTYWANIU KOPII
# ============================================================================
# Migracje idą tylko w przód. Kopia zrobiona na telefonie z nowszą wersją
# aplikacji, wczytana na komputerze ze starszą, to cicha katastrofa: baza ma
# kolumny, o których ten kod nie wie, więc nowe pola przestają się wypełniać
# i nie jadą do chmury — a nic się przy tym nie wywala. Numer wersji jest
# w bazie od zawsze; wystarczy go przeczytać PRZED nadpisaniem.


def wersja_schematu_aplikacji() -> int:
    """Najwyższy numer schematu, jaki zna TA wersja aplikacji.

    Ustawiany przez `init_db()`, bo `migracje` jest zmienną lokalną w jego
    wnętrzu i nie da się jej zaimportować (patrz `tests/test_migracje.py`, które
    czyta ją z AST). Zanim `init_db()` pójdzie choć raz, zostaje odczyt z bazy;
    zero znaczy „nie wiadomo" i wtedy nic nie blokujemy."""
    if WERSJA_SCHEMATU is not None:
        return WERSJA_SCHEMATU
    zapisana = str(pobierz_ustawienie("schema_version", "") or "").strip()
    return int(zapisana) if zapisana.isdigit() else 0


def wersja_schematu_pliku(sciezka) -> int | None:
    """Numer schematu bazy leżącej w PLIKU — bez otwierania jej jako bieżącej.

    Otwieramy w trybie tylko do odczytu: plik, który dopiero sprawdzamy, nie ma
    prawa się przy tym zmienić ani powstać. None znaczy „nie do odczytania" —
    bardzo stara kopia bez tabeli ustawień, plik, który nie jest bazą SQLite,
    albo brak dostępu. To rozróżnienie jest istotne: przy zerze migracje puszczą
    całą drabinkę, a przy „nie wiem" nie wolno zakładać niczego."""
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
    """(czy wolno wczytać, powód odmowy). Powód jest pusty, gdy wolno.

    Kopia STARSZA przechodzi bez słowa — dociągnięcie jej drabinką migracji to
    normalna, przewidziana droga. Blokujemy wyłącznie kopię NOWSZĄ, bo tej nie
    da się cofnąć: migracji w tył nie ma i nigdy nie będzie.

    Nieczytelnego pliku też nie blokujemy: od zgłaszania uszkodzonej kopii jest
    sam import, razem z przywróceniem bazy sprzed próby. Diagnostyka nie ma
    prawa zamknąć drogi, której nie potrafi ocenić."""
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



__all__ = [
    "WERSJA_SCHEMATU",
    "init_db",
    "sprawdz_kopie_przed_wczytaniem",
    "wersja_schematu_aplikacji",
    "wersja_schematu_kopii",
    "wersja_schematu_pliku",
]
