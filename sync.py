"""
Współdzielenie pojazdu — synchronizacja z Supabase.

Reszta aplikacji działa dokładnie jak dotychczas: w 100% lokalnie i offline.
Ten moduł włącza się TYLKO dla pojazdu świadomie oznaczonego jako współdzielony.
Synchronizowane są wszystkie wpisy za pomocą uniwersalnej tabeli zdalne_rekordy.

Trzy rzeczy, o których warto wiedzieć przed czytaniem dalej:

1. ROLE. Pojazd ma u każdego uczestnika swoją rolę (patrz db/synchronizacja):
   właściciel i pełny dostęp robią wszystko, współautor dopisuje własne wpisy,
   a podgląd wyłącznie czyta — przy tej roli NIC z tego telefonu nie leci do
   chmury, łącznie z usunięciami. Blokada w interfejsie to wygoda; twardą
   granicę stawia wyzwalacz po stronie Supabase (patrz supabase/role_wspoldzielenia.sql).

2. DELTA. Pobieranie pyta o rekordy zmienione od ostatniego razu
   (`zaktualizowano >= znacznik_delty`), a nie o komplet 19 tabel za każdym
   razem. Gdyby kolumny znacznika nie było, moduł raz to zauważa i wraca do
   pełnego pobierania — bez błędu widocznego dla użytkownika.

3. JEDNA NARAZ. Dwa zapisy formularza pod rząd odpalały dwie synchronizacje
   równolegle i potrafiły się wyścignąć o `zdalny_hash`. Teraz wejście do
   synchronizuj_wszystko jest pod zamkiem (_ZAMEK_SYNC).
"""

import uuid as uuid_lib
import sqlite3
import json
import hashlib
import threading
from datetime import datetime
import db
import log

# Kolumna znacznika czasu w tabeli zdalne_rekordy. Jeśli w Twoim projekcie
# Supabase nazywa się inaczej, wystarczy zmienić TU — moduł i tak sam wykryje
# jej brak i przełączy się na pełne pobieranie.
KOLUMNA_ZNACZNIKA = "zaktualizowano"

# Zamek na całą synchronizację jednego urządzenia. Auto-synchronizacja po
# zapisie formularza leci przez page.run_task, więc dwa szybkie zapisy pod rząd
# uruchamiały dwa przebiegi naraz: obydwa czytały ten sam `zdalny_hash`, obydwa
# wypychały i jeden nadpisywał drugiemu wynik.
_ZAMEK_SYNC = threading.Lock()

# Czy serwer w ogóle zna kolumnę znacznika. None = jeszcze nie sprawdzone.
_delta_dostepna = None


class SynchronizacjaWToku(Exception):
    """Inna synchronizacja tego urządzenia właśnie trwa. Rzucane wyłącznie
    przy wywołaniu z `czekaj=False` — nie jest błędem, tylko informacją,
    że nie ma po co robić drugiego przebiegu równolegle."""

# --- UZUPEŁNIJ PO ZAŁOŻENIU PROJEKTU NA supabase.com (Project Settings -> API) ---
SUPABASE_URL = "https://ptnnejbuvymhrkouwsln.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InB0bm5lamJ1dnltaHJrb3V3c2xuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODc2NTg2NTQsImV4cCI6MjEwMzIzNDY1NH0.xfLcVeiNatGqFtBBnvSB2EOZoo9i_vodDqtF6XLC9iA"
# ----------------------------------------------------------------------------------

_klient_cache = None

def _pobierz_klient():
    global _klient_cache
    if _klient_cache is None:
        from supabase import create_client
        _klient_cache = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    return _klient_cache

def _upewnij_sesje():
    klient = _pobierz_klient()

    token = db.pobierz_ustawienie("supabase_access_token")
    refresh = db.pobierz_ustawienie("supabase_refresh_token")
    if token and refresh:
        try:
            wynik = klient.auth.set_session(access_token=token, refresh_token=refresh)
            sesja = wynik.session
            db.zapisz_ustawienie("supabase_access_token", sesja.access_token)
            db.zapisz_ustawienie("supabase_refresh_token", sesja.refresh_token)
            klient.postgrest.auth(token=sesja.access_token)
            return klient, sesja.user.id
        except Exception:
            log.polkniety("odtworzenie zapisanej sesji Supabase")

    wynik = klient.auth.sign_in_anonymously()
    sesja = wynik.session
    db.zapisz_ustawienie("supabase_access_token", sesja.access_token)
    db.zapisz_ustawienie("supabase_refresh_token", sesja.refresh_token)
    klient.postgrest.auth(token=sesja.access_token)
    return klient, sesja.user.id

def czy_udostepniony(auto_id):
    if not auto_id:
        return None, None
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT wspolny_pojazd_id, kod_zaproszenia FROM samochody WHERE id=?", (auto_id,))
        w = c.fetchone()
    return (w[0], w[1]) if w and w[0] else (None, None)

def _nowy_kod():
    return uuid_lib.uuid4().hex[:6].upper()


def utworz_udostepniony_pojazd(auto_id, nazwa):
    klient, uid = _upewnij_sesje()
    kod = _nowy_kod()

    wynik = klient.rpc("utworz_udostepniony_pojazd", {"p_nazwa": nazwa, "p_kod": kod}).execute()
    nowy_id = wynik.data 

    with db.polacz_baze() as conn:
        conn.execute(
            "UPDATE samochody SET wspolny_pojazd_id=?, kod_zaproszenia=?, rola_wspoldzielenia=? WHERE id=?",
            (nowy_id, kod, db.ROLA_WLASCICIEL, auto_id)
        )

    # Kody ról zakładamy od razu, ale ich brak nie może wywrócić udostępniania —
    # gdy w Supabase nie ma jeszcze tabeli kodów, pojazd i tak jest udostępniony
    # kodem pełnym, dokładnie jak przed wprowadzeniem ról.
    try:
        utworz_kody_rol(auto_id)
    except Exception:
        log.polkniety("zakładanie kodów ról przy udostępnianiu pojazdu")

    synchronizuj_wszystko(auto_id)
    return kod


def utworz_kody_rol(auto_id, odswiez=False):
    """Zakłada (albo odtwarza) dwa dodatkowe kody zaproszenia: dla współautora
    i dla podglądu. Kody są LOSOWE, a nie wyprowadzone z kodu pełnego —
    gdyby były jego wariantem („P-A1B2C3”), gość z podglądu odgadłby kod pełny
    w dwie sekundy i cała rola byłaby dekoracją.

    Wymaga funkcji `zarejestruj_kod_dostepu` po stronie Supabase (plik
    supabase/role_wspoldzielenia.sql). Bez niej rzuca wyjątkiem, a ekran
    Współdzielenia pokazuje, co trzeba dograć — kod pełny działa niezależnie.

    Zwraca {"wspolautor": kod, "podglad": kod}."""
    wspolny_id, kod_pelny = czy_udostepniony(auto_id)
    if not wspolny_id:
        raise ValueError("Ten pojazd nie jest współdzielony.")

    istniejace = db.kody_dostepu(auto_id)
    kody = {
        db.ROLA_WSPOLAUTOR: None if odswiez else istniejace.get("wspolautor"),
        db.ROLA_PODGLAD: None if odswiez else istniejace.get("podglad"),
    }
    if all(kody.values()):
        return {"wspolautor": kody[db.ROLA_WSPOLAUTOR], "podglad": kody[db.ROLA_PODGLAD]}

    klient, uid = _upewnij_sesje()
    for rola in (db.ROLA_WSPOLAUTOR, db.ROLA_PODGLAD):
        if kody[rola]:
            continue
        kod = _nowy_kod()
        klient.rpc("zarejestruj_kod_dostepu", {
            "p_pojazd_id": wspolny_id,
            "p_kod": kod,
            "p_kod_bazowy": kod_pelny,
            "p_rola": rola,
        }).execute()
        kody[rola] = kod

    db.zapisz_kody_dostepu(auto_id, kody[db.ROLA_WSPOLAUTOR], kody[db.ROLA_PODGLAD])
    return {"wspolautor": kody[db.ROLA_WSPOLAUTOR], "podglad": kody[db.ROLA_PODGLAD]}


def uniewaznij_kody_rol(auto_id):
    """Wycofuje dotychczasowe kody ról i wystawia nowe — do użycia, gdy kod
    wyciekł albo ktoś ma przestać mieć dostęp. Uczestnicy, którzy już dołączyli,
    zostają: kod służy do wejścia, nie do trzymania dostępu."""
    wspolny_id, _ = czy_udostepniony(auto_id)
    if not wspolny_id:
        raise ValueError("Ten pojazd nie jest współdzielony.")
    klient, uid = _upewnij_sesje()
    stare = db.kody_dostepu(auto_id)
    for kod in (stare.get("wspolautor"), stare.get("podglad")):
        if kod:
            try:
                klient.rpc("wycofaj_kod_dostepu", {"p_kod": kod}).execute()
            except Exception:
                log.polkniety("wycofanie kodu dostępu w Supabase")
    with db.polacz_baze() as conn:
        conn.execute("UPDATE samochody SET kod_wspolautora=NULL, kod_podgladu=NULL WHERE id=?", (auto_id,))
    return utworz_kody_rol(auto_id, odswiez=True)

def _unikalna_nazwa_pojazdu(cur, nazwa_bazowa):
    """Zwraca nazwę pojazdu różną (bez rozróżniania wielkości liter) od już
    istniejących w tabeli samochody. Używane WYŁĄCZNIE przy dołączaniu do
    współdzielonego pojazdu kodem (patrz dolacz_po_kodzie) — przy kolizji
    nazwy zawsze dopisujemy odróżnik, zamiast kiedykolwiek próbować
    "dopasować się" pod istniejący, prywatny wiersz."""
    cur.execute("SELECT LOWER(nazwa) FROM samochody")
    zajete = {r[0] for r in cur.fetchall()}
    if nazwa_bazowa.lower() not in zajete:
        return nazwa_bazowa
    kandydat = f"{nazwa_bazowa} (współdzielony)"
    if kandydat.lower() not in zajete:
        return kandydat
    i = 2
    while f"{kandydat} {i}".lower() in zajete:
        i += 1
    return f"{kandydat} {i}"

def _dolacz_z_rola(klient, kod):
    """Zamienia wpisany kod na (pojazd_id, nazwa, rola).

    Najpierw pyta o kod ROLOWY (`dolacz_do_pojazdu_z_rola` — funkcja z pliku
    supabase/role_wspoldzielenia.sql). Gdy jej nie ma albo kod nie jest kodem
    roli, wraca do dotychczasowego `dolacz_do_pojazdu`, który zna wyłącznie kod
    pełny. Dzięki temu aplikacja po aktualizacji działa tak samo, zanim SQL
    zostanie wgrany — tylko role są wtedy niedostępne."""
    try:
        wynik = klient.rpc("dolacz_do_pojazdu_z_rola", {"p_kod": kod}).execute()
        if wynik.data:
            w = wynik.data[0]
            rola = (w.get("rola") or db.ROLA_PELNA).strip()
            return w["pojazd_id"], w["nazwa"], (rola if rola in db.ETYKIETY_ROL else db.ROLA_PELNA)
    except Exception:
        # Brak funkcji na serwerze albo to nie jest kod roli — próbujemy dalej.
        log.polkniety("dołączanie do pojazdu kodem roli")

    wynik = klient.rpc("dolacz_do_pojazdu", {"p_kod": kod}).execute()
    if not wynik.data:
        raise ValueError("Nieprawidłowy kod zaproszenia.")
    return wynik.data[0]["pojazd_id"], wynik.data[0]["nazwa"], db.ROLA_PELNA


def dolacz_po_kodzie(kod):
    klient, uid = _upewnij_sesje()
    kod = kod.strip().upper()
    wspolny_id, nazwa_zdalna, rola = _dolacz_z_rola(klient, kod)

    with db.polacz_baze() as conn:
        cur = conn.cursor()

        # WAŻNE — bezpieczeństwo danych: NIGDY nie dopasowujemy po nazwie do
        # istniejącego lokalnego pojazdu. Dwa różne auta o tej samej, popularnej
        # nazwie (np. dwie "Škoda Octavia" różnych osób) mogłyby się przez to
        # przypadkiem zlać w jeden wiersz — a zaraz potem synchronizuj_wszystko()
        # poniżej wypchnęłoby CAŁĄ dotychczasową, prywatną historię lokalnego
        # auta (tankowania, serwis, koszty...) do CUDZEGO współdzielonego
        # pojazdu. Dołączenie po kodzie zawsze tworzy NOWY wiersz; przy kolizji
        # nazwy dopisujemy odróżnik.
        cur.execute("SELECT COUNT(*) FROM samochody WHERE LOWER(nazwa)=LOWER(?)", (nazwa_zdalna,))
        kolizja_nazwy = cur.fetchone()[0] > 0
        nazwa = _unikalna_nazwa_pojazdu(cur, nazwa_zdalna) if kolizja_nazwy else nazwa_zdalna

        # Kod zaproszenia zapisujemy TYLKO przy pełnym dostępie. Kod roli nie
        # jest kodem pojazdu — gdyby wylądował w tej kolumnie, gość z podglądu
        # zobaczyłby go u siebie jako „kod do rozdawania” i rozesłał dalej
        # zaproszenie, którego nie ma prawa wystawiać.
        cur.execute(
            "INSERT INTO samochody (nazwa, wspolny_pojazd_id, kod_zaproszenia, rola_wspoldzielenia) VALUES (?,?,?,?)",
            (nazwa, wspolny_id, kod if rola in db.ROLE_Z_PELNYM_DOSTEPEM else None, rola)
        )
        nowy_auto_id = cur.lastrowid

    synchronizuj_wszystko(nowy_auto_id)
    return nowy_auto_id, nazwa, kolizja_nazwy, rola


# ==================== UNIWERSALNA SYNCHRONIZACJA ====================
KOLUMNY_POJAZDU = [
    "nazwa", "marka", "model", "generacja", "nr_rej", "vin", "rok_produkcji",
    "oc_data", "przeglad_data", "pojemnosc_silnika", "moc_silnika", "typ_paliwa",
    "skrzynia_biegow", "nadwozie", "pojemnosc_baterii", "zasieg_ev", "pojemnosc_baku",
    "notatki", "wycieraczki_przod", "wycieraczki_tyl",
    "cisnienie_przod", "cisnienie_tyl", "olej_typ", "olej_pojemnosc", "akumulator",
    "zarowki_mijania", "zarowki_drogowe", "ac_data", "assistance_data",
    "gasnica_data", "apteczka_data", "wiadomosc_statusu",
    "gwarancja_data", "gwarancja_przebieg",
    # Dane z wersji 37 — zakup i wartość, ubezpieczenie, rozszerzona ściągawka,
    # pierwsza rejestracja. Wszystkie opisują POJAZD, więc przy współdzieleniu
    # muszą być widoczne po obu stronach; telefon do assistance przede wszystkim.
    "data_zakupu", "cena_zakupu", "przebieg_zakupu", "wartosc_szacowana",
    "ubezpieczyciel", "nr_polisy", "skladka_roczna", "telefon_assistance",
    "kod_lakieru", "rozmiar_opon", "rozmiar_felg", "rozstaw_srub",
    "moment_dokrecania", "typ_zlacza_ev", "data_pierwszej_rejestracji",
    # Sprzedaż auta musi dojść do drugiej strony: inaczej u współdzielącego
    # pojazd dalej stałby w garażu, choć fizycznie już go nie ma.
    "status", "data_sprzedazy", "cena_sprzedazy",
]

# Notatka wpisu jedzie do chmury razem z resztą jego pól (kolumny 'notatka',
# 'notatka_autor', 'notatka_data') — sens tej funkcji polega na tym, że uwagę
# zostawioną przy tankowaniu widzi też druga osoba korzystająca z auta.
KONFIGURACJA_SYNC = [
    {"tabela": "tagi", "kolumny": ["nazwa", "kolor"], "fk": {}},
    {"tabela": "tankowania", "kolumny": ["data", "przebieg", "dystans", "litry", "kwota", "do_pelna", "stacja", "tagi", "rodzaj_energii", "typ_ladowania", "notatka", "notatka_autor", "notatka_data", "dodane_przez", "zmodyfikowane_przez", "data_modyfikacji"], "fk": {}},
    {"tabela": "zadania", "kolumny": ["nazwa", "interwal_km", "interwal_miesiace", "dotyczy_opon", "prog_km", "prog_dni"], "fk": {}},
    {"tabela": "wizyty", "kolumny": ["data", "przebieg", "wykonawca", "koszt_calkowity", "notatki", "tagi", "dodane_przez", "zmodyfikowane_przez", "data_modyfikacji"], "fk": {}},
    {"tabela": "historia", "kolumny": ["data", "przebieg", "kategoria", "cena", "wykonawca", "notatka", "notatka_autor", "notatka_data", "dodane_przez", "zmodyfikowane_przez", "data_modyfikacji"], "fk": {"zadanie_id": "zadania", "wizyta_id": "wizyty"}},
    {"tabela": "magazyn_czesci", "kolumny": ["nazwa", "kategoria", "ilosc", "jednostka", "cena", "data_zakupu", "notatki", "prog_ostrzezenia"], "fk": {}},
    {"tabela": "wizyta_czesci_magazynu", "kolumny": ["ilosc_uzyta"], "fk": {"wizyta_id": "wizyty", "magazyn_id": "magazyn_czesci"}},
    {"tabela": "historia_czesci_magazynu", "kolumny": ["ilosc_uzyta"], "fk": {"historia_id": "historia", "magazyn_id": "magazyn_czesci"}},
    {"tabela": "zestawy_opon", "kolumny": ["sezon", "rozmiar", "marka_model", "glebokosc_bieznika", "data_pomiaru", "numer_dot", "ilosc", "zamontowane", "data_zakupu", "przebieg_zakupu", "cena", "notatki", "os_montazu"], "fk": {}},
    {"tabela": "inne_koszty", "kolumny": ["data", "kategoria", "nazwa", "kwota", "tagi", "notatka", "notatka_autor", "notatka_data", "dodane_przez", "zmodyfikowane_przez", "data_modyfikacji"], "fk": {}},
    {"tabela": "warsztaty", "kolumny": ["nazwa", "telefon", "adres", "notatki"], "fk": {}},
    {"tabela": "wydatki_cykliczne", "kolumny": ["nazwa", "kwota", "okres_dni", "nastepna_data", "czy_koszt", "typ"], "fk": {}},
    {"tabela": "odczyty_przebiegu", "kolumny": ["data", "przebieg", "zrodlo", "notatka", "notatka_autor", "notatka_data"], "fk": {}},
    {"tabela": "do_zrobienia", "kolumny": ["tytul", "opis", "priorytet", "szacowany_koszt", "termin", "wykonane", "data_utworzenia"], "fk": {"zadanie_id": "zadania"}},
    {"tabela": "pakiety_serwisowe_wlasne", "kolumny": ["nazwa", "pozycje"], "fk": {}},
    # Limit wydatków ustala się raz dla pojazdu, nie osobno w każdym telefonie —
    # inaczej dwie osoby patrzyłyby na dwa różne budżety tego samego auta.
    # 'klucz_scalania' jest tu konieczny: (kategoria, okres) ma w bazie UNIQUE,
    # więc rekord przychodzący z chmury musi umieć wejść w istniejący lokalny
    # wiersz zamiast rozbić się o indeks (patrz _pobierz_tabele).
    {"tabela": "budzety", "kolumny": ["kategoria", "okres", "kwota"], "fk": {},
     "klucz_scalania": ["kategoria", "okres"]},
    # Trasa „do teściów” jest cechą AUTA, nie telefonu — kto wsiądzie, ten ma
    # tę samą pozycję w kalkulatorze.
    {"tabela": "trasy_szablony", "kolumny": ["nazwa", "dystans", "powrot", "osoby", "oplaty", "notatki"], "fk": {}},
    # Checklista jedzie w komplecie: nagłówek plus pozycje. Stan odhaczenia też
    # — przy wspólnym aucie sens polega właśnie na tym, że druga osoba widzi,
    # co zostało już sprawdzone przed wyjazdem.
    {"tabela": "checklisty", "kolumny": ["nazwa", "opis", "ostatnie_uzycie"], "fk": {}},
    {"tabela": "checklisty_pozycje", "kolumny": ["tresc", "kolejnosc", "odhaczone"], "fk": {"checklista_id": "checklisty"}},
]

# Tabele bez własnej kolumny auto_id — do pojazdu dowiązane wyłącznie pośrednio,
# przez JOIN. Wcześniej każdy taki przypadek był osobnym if/elif powtórzonym
# w pięciu miejscach tego pliku; teraz jest jednym opisem, więc dołożenie kolejnej
# tabeli pośredniej to jeden wpis, a nie pięć łatek.
TABELE_POSREDNIE = {
    "historia": {
        "alias": "h",
        "join": "JOIN zadania z ON h.zadanie_id = z.id",
        "warunek": "z.auto_id=?",
        "reset_where": "zadanie_id IN (SELECT id FROM zadania WHERE auto_id=?)",
    },
    "wizyta_czesci_magazynu": {
        "alias": "wcm",
        "join": "JOIN wizyty w ON wcm.wizyta_id = w.id",
        "warunek": "w.auto_id=?",
        "reset_where": "wizyta_id IN (SELECT id FROM wizyty WHERE auto_id=?)",
    },
    "checklisty_pozycje": {
        "alias": "p",
        "join": "JOIN checklisty l ON p.checklista_id = l.id",
        "warunek": "l.auto_id=?",
        "reset_where": "checklista_id IN (SELECT id FROM checklisty WHERE auto_id=?)",
    },
    "historia_czesci_magazynu": {
        "alias": "hcm",
        "join": "JOIN historia h ON hcm.historia_id = h.id JOIN zadania z ON h.zadanie_id = z.id",
        "warunek": "z.auto_id=?",
        "reset_where": (
            "historia_id IN (SELECT h.id FROM historia h "
            "JOIN zadania z ON h.zadanie_id = z.id WHERE z.auto_id=?)"
        ),
    },
}

def _zapytanie_tabeli(tabela, pola="*", warunek_dodatkowy=None):
    """Buduje SELECT ograniczony do jednego pojazdu — dla tabel z auto_id wprost,
    dla pośrednich przez zdefiniowany JOIN. `pola` podaje się bez aliasu
    (np. "id, zdalne_id"); alias jest doklejany automatycznie."""
    opis = TABELE_POSREDNIE.get(tabela)
    if not opis:
        zapytanie = f"SELECT {pola} FROM {tabela} WHERE auto_id=?"
        if warunek_dodatkowy:
            zapytanie += f" AND {warunek_dodatkowy}"
        return zapytanie

    alias = opis["alias"]
    if pola.strip() == "*":
        wybor = f"{alias}.*"
    else:
        wybor = ", ".join(f"{alias}.{p.strip()}" for p in pola.split(","))
    zapytanie = f"SELECT {wybor} FROM {tabela} {alias} {opis['join']} WHERE {opis['warunek']}"
    if warunek_dodatkowy:
        zapytanie += f" AND {alias}.{warunek_dodatkowy}"
    return zapytanie

def _hash_zawartosci(dane: dict) -> str:
    """Odcisk treści rekordu. Klucze zaczynające się od podkreślnika są POMIJANE:
    to pola dokładane przez serwer (dziś `_autor_uid` — identyfikator autora
    stemplowany przez wyzwalacz ról), których aplikacja nie zna i nie wysyła.
    Bez tego wyłączenia każdy rekord po stronie serwera miałby inny hash niż
    ten sam rekord policzony lokalnie i KAŻDA zmiana zgłaszałaby się jako
    konflikt edycji z dwóch urządzeń."""
    istotne = {k: v for k, v in (dane or {}).items() if not str(k).startswith("_")}
    kanoniczny = json.dumps(istotne, sort_keys=True, default=str, ensure_ascii=True)
    return hashlib.sha256(kanoniczny.encode("utf-8")).hexdigest()

def _paczki(elementy, rozmiar=100):
    """PostgREST przekazuje filtr `in` w adresie URL, więc lista kilkuset
    identyfikatorów potrafi przekroczyć limit długości. Dzielimy na porcje."""
    elementy = list(elementy)
    for i in range(0, len(elementy), rozmiar):
        yield elementy[i:i + rozmiar]


def _wypchnij_nagrobki(klient, auto_id=None):
    """Wysyła zaległe usunięcia. Dwie zmiany względem poprzedniej wersji:

    - leci tylko to, co należy do TEGO pojazdu (albo nie ma przypisania —
      nagrobki sprzed migracji 40), zamiast wszystkiego, co jest w tabeli;
    - nieudana próba zwiększa licznik zamiast znikać w `except: pass`. Nagrobek
      odrzucany przez serwer w nieskończoność (bo nie mam prawa kasować tego
      rekordu) przestaje po kilku próbach obciążać każdą synchronizację."""
    for nagrobek_id, tabela, zdalny_id in db.pobierz_nagrobki(auto_id):
        try:
            klient.rpc("usun_zdalny_rekord", {"p_id": zdalny_id}).execute()
            db.usun_nagrobek_po_id(nagrobek_id)
        except Exception:
            db.zwieksz_proby_nagrobka(nagrobek_id)

# Konflikty wykryte podczas bieżącej synchronizacji — rekordy nadpisane mimo że
# zmieniły się niezależnie po obu stronach (edycja z dwóch urządzeń offline).
# Czyszczone na starcie każdego synchronizuj_wszystko().
_konflikty_biezacej_synchronizacji = []

# Zmiany, których serwer nie przyjąłby, bo dotyczą cudzych wpisów, a mam rolę
# współautora. Nie wysyłamy ich w ogóle i cofamy lokalnie do wersji z chmury —
# inaczej telefon w nieskończoność pokazywałby zmianę, o której nikt inny nie wie.
_odrzucone_biezacej_synchronizacji = []

ETYKIETY_TABEL_SYNC = {
    "tankowania": "Tankowanie",
    "historia": "Wpis serwisowy",
    "wizyty": "Wizyta w warsztacie",
    "zadania": "Podzespół",
    "magazyn_czesci": "Pozycja magazynu",
    "wizyta_czesci_magazynu": "Zużycie części",
    "historia_czesci_magazynu": "Zużycie części przy wpisie",
    "zestawy_opon": "Zestaw opon",
    "inne_koszty": "Inny koszt",
    "warsztaty": "Warsztat",
    "wydatki_cykliczne": "Wydatek cykliczny",
    "odczyty_przebiegu": "Odczyt licznika",
    "do_zrobienia": "Zadanie do zrobienia",
    "tagi": "Tag",
    "pakiety_serwisowe_wlasne": "Własny pakiet serwisowy",
    "budzety": "Limit budżetu",
    "trasy_szablony": "Zapisana trasa",
    "checklisty": "Checklista",
    "checklisty_pozycje": "Pozycja checklisty",
    "info_pojazdu": "Dane pojazdu",
}

def _opis_rekordu(tabela, dane):
    """Krótki, ludzki opis konfliktowego rekordu — żeby komunikat mówił CO zostało
    nadpisane, a nie tylko ile rzeczy. Buduje się wyłącznie z pól, które i tak
    lecą do chmury (patrz KONFIGURACJA_SYNC), więc nie wymaga dobicia do bazy."""
    dane = dane or {}

    def pole(*nazwy):
        for n in nazwy:
            w = dane.get(n)
            if w not in (None, ""):
                return str(w)
        return ""

    czesci = []
    data_txt = pole("data", "termin", "nastepna_data", "data_zakupu")
    if data_txt:
        czesci.append(data_txt)

    nazwa_txt = pole("nazwa", "tytul", "stacja", "wykonawca", "sezon")
    if nazwa_txt:
        czesci.append(nazwa_txt)

    kwota = dane.get("kwota", dane.get("cena", dane.get("koszt_calkowity", dane.get("szacowany_koszt"))))
    if kwota not in (None, ""):
        try:
            czesci.append(f"{float(kwota):.2f}")
        except (TypeError, ValueError):
            pass

    if not czesci:
        przebieg = pole("przebieg")
        if przebieg:
            czesci.append(f"{przebieg} km")

    etykieta = ETYKIETY_TABEL_SYNC.get(tabela, tabela)
    return f"{etykieta}: {' • '.join(czesci)}" if czesci else etykieta

def _zarejestruj_konflikt(tabela, dane=None, zdalne_id=None, dane_zdalne=None):
    """`dane_zdalne` to wersja, którą właśnie nadpisujemy. Trzymamy ją, bo bez
    niej przycisk „Weź wersję z chmury” nie miałby czego przywrócić — chwilę po
    wykryciu konfliktu tamtej wersji już na serwerze nie ma."""
    _konflikty_biezacej_synchronizacji.append({
        "tabela": tabela,
        "etykieta": ETYKIETY_TABEL_SYNC.get(tabela, tabela),
        "opis": _opis_rekordu(tabela, dane),
        "opis_zdalny": _opis_rekordu(tabela, dane_zdalne) if dane_zdalne else "",
        "zdalne_id": zdalne_id,
        "dane_zdalne": dane_zdalne,
    })


def _zarejestruj_odrzucenie(tabela, dane=None, zdalne_id=None):
    _odrzucone_biezacej_synchronizacji.append({
        "tabela": tabela,
        "etykieta": ETYKIETY_TABEL_SYNC.get(tabela, tabela),
        "opis": _opis_rekordu(tabela, dane),
        "zdalne_id": zdalne_id,
    })


def pobierz_konflikty_ostatniej_synchronizacji():
    """Lista nadpisanych rekordów z ostatniej synchronizacji:
    [{"tabela","etykieta","opis","opis_zdalny","zdalne_id","dane_zdalne"}, ...].
    Pusta lista = brak konfliktów."""
    return list(_konflikty_biezacej_synchronizacji)


def pobierz_odrzucone_ostatniej_synchronizacji():
    """Zmiany cofnięte, bo dotyczyły cudzych wpisów przy roli współautora."""
    return list(_odrzucone_biezacej_synchronizacji)

def _wolno_wypchnac_zmiane(auto_id, rola, tabela, wiersz):
    """Czy wolno mi wysłać ZMIANĘ istniejącego rekordu.

    Podgląd nie wysyła nic. Współautor nie rusza cudzych wpisów — ale tylko
    w tabelach, w których „czyj to wpis” w ogóle ma sens (te z kolumną
    `dodane_przez`). Podzespoły, tagi, warsztaty czy magazyn to wspólny
    słownik pojazdu: zablokowanie ich odebrałoby współautorowi możliwość
    dopisania przebiegu do podzespołu, który sam wcześniej założył."""
    if rola == db.ROLA_PODGLAD:
        return False
    if rola != db.ROLA_WSPOLAUTOR:
        return True
    if tabela not in db.TABELE_Z_AUTOREM:
        return True
    klucze = wiersz.keys()
    autor = wiersz["dodane_przez"] if "dodane_przez" in klucze else None
    return db.czy_moge_zmieniac_wpis(auto_id, autor)


def _wypchnij_tabele(klient, wspolny_id, auto_id, konfig, rola=None):
    """Wysyła nowe i zmienione wiersze jednej tabeli.

    Zwraca (ile_wyslano, [zdalne_id do cofnięcia]) — druga lista to zmiany
    odrzucone przez rolę współautora, które trzeba przywrócić z chmury."""
    tabela = konfig["tabela"]
    kolumny = konfig["kolumny"]
    fk = konfig["fk"]
    rola = rola or db.ROLA_WLASCICIEL
    wyslano = 0
    do_cofniecia = []

    if rola == db.ROLA_PODGLAD:
        return 0, []

    def zbuduj_dane(wiersz):
        dane = {nazwa: wiersz[nazwa] for nazwa in kolumny}
        for pole_fk, tabela_fk in fk.items():
            wartosc_fk = wiersz[pole_fk]
            zdalne_fk = None
            if wartosc_fk:
                with db.polacz_baze() as conn:
                    c = conn.cursor()
                    c.execute(f"SELECT zdalne_id FROM {tabela_fk} WHERE id=?", (wartosc_fk,))
                    w = c.fetchone()
                    zdalne_fk = w[0] if w else None
            dane[f"{pole_fk}_zdalne"] = zdalne_fk
        return dane

    zapytanie_nowe = _zapytanie_tabeli(tabela, "*", "zdalne_id IS NULL")

    with db.polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(zapytanie_nowe, (auto_id,))
        do_wyslania = c.fetchall()

    # Nowy wiersz jest z definicji mój — powstał na tym telefonie — więc rola
    # współautora go nie dotyczy. Ograniczenie zaczyna działać dopiero przy
    # zmianie czegoś, co już w chmurze jest.
    for wiersz in do_wyslania:
        dane = zbuduj_dane(wiersz)
        wynik = klient.rpc("dodaj_zdalny_rekord", {
            "p_pojazd_id": wspolny_id, "p_tabela": tabela, "p_dane": dane
        }).execute()
        nowe_zdalne_id = wynik.data
        nowy_hash = _hash_zawartosci(dane)
        with db.polacz_baze() as conn:
            conn.execute(f"UPDATE {tabela} SET zdalne_id=?, zdalny_hash=? WHERE id=?", (nowe_zdalne_id, nowy_hash, wiersz["id"]))
        wyslano += 1

    zapytanie_istniejace = _zapytanie_tabeli(tabela, "*", "zdalne_id IS NOT NULL")

    with db.polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(zapytanie_istniejace, (auto_id,))
        istniejace = c.fetchall()

    # Najpierw ustalamy, co się w ogóle zmieniło. Dopiero dla TYCH rekordów
    # dopytujemy serwer o aktualną treść — wcześniej leciał komplet wierszy
    # tabeli przy każdej synchronizacji, tylko po to, żeby porównać hasze
    # kilku zmienionych.
    zmienione = []
    for wiersz in istniejace:
        dane = zbuduj_dane(wiersz)
        nowy_hash = _hash_zawartosci(dane)
        if nowy_hash == wiersz["zdalny_hash"]:
            continue  # nic się nie zmieniło
        if not _wolno_wypchnac_zmiane(auto_id, rola, tabela, wiersz):
            # Zmiana w cudzym wpisie. Nie wysyłamy jej i kasujemy zapamiętany
            # hash, żeby najbliższe pobranie nadpisało lokalny wiersz wersją
            # z chmury — inaczej telefon w nieskończoność pokazywałby zmianę,
            # o której nikt poza nim nie wie.
            with db.polacz_baze() as conn:
                conn.execute(f"UPDATE {tabela} SET zdalny_hash='' WHERE id=?", (wiersz["id"],))
            _zarejestruj_odrzucenie(tabela, dane=dane, zdalne_id=wiersz["zdalne_id"])
            do_cofniecia.append(wiersz["zdalne_id"])
            continue
        zmienione.append((wiersz, dane, nowy_hash))

    if not zmienione:
        return wyslano, do_cofniecia

    zdalne_teraz = {}
    identyfikatory = [w["zdalne_id"] for w, _, _ in zmienione]
    for paczka in _paczki(identyfikatory):
        wynik_zdalne = klient.table("zdalne_rekordy").select("id,dane").in_("id", paczka).execute()
        for r in wynik_zdalne.data or []:
            zdalne_teraz[r["id"]] = r.get("dane") or {}

    for wiersz, dane, nowy_hash in zmienione:
        dane_zdalne = zdalne_teraz.get(wiersz["zdalne_id"])
        if dane_zdalne is not None:
            hash_zdalny_teraz = _hash_zawartosci(dane_zdalne)
            if hash_zdalny_teraz != wiersz["zdalny_hash"]:
                # Zdalna wersja zmieniła się niezależnie od naszej ostatniej
                # synchronizacji — ktoś edytował ten sam rekord na innym
                # urządzeniu offline. Zaraz go nadpiszemy, więc zapamiętujemy
                # tamtą treść, żeby dało się ją jeszcze odzyskać.
                _zarejestruj_konflikt(tabela, dane=dane, zdalne_id=wiersz["zdalne_id"], dane_zdalne=dane_zdalne)

        klient.rpc("aktualizuj_zdalny_rekord", {"p_id": wiersz["zdalne_id"], "p_dane": dane}).execute()
        with db.polacz_baze() as conn:
            conn.execute(f"UPDATE {tabela} SET zdalny_hash=? WHERE id=?", (nowy_hash, wiersz["id"]))
        wyslano += 1

    return wyslano, do_cofniecia


def _delta_wlaczona():
    global _delta_dostepna
    if _delta_dostepna is None:
        _delta_dostepna = db.pobierz_ustawienie("sync_delta_niedostepna") != "1"
    return _delta_dostepna


def _wylacz_delte():
    """Serwer nie zna kolumny znacznika — zapamiętujemy to na stałe, żeby nie
    ponawiać nieudanego zapytania przy każdej tabeli i każdej synchronizacji."""
    global _delta_dostepna
    _delta_dostepna = False
    try:
        db.zapisz_ustawienie("sync_delta_niedostepna", "1")
    except Exception:
        log.polkniety("zapamiętanie braku synchronizacji przyrostowej")


def _pobierz_rekordy(klient, wspolny_id, tabela, znacznik=None, tylko_id=None):
    """Rekordy jednej tabeli z chmury. Przy podanym znaczniku pobiera tylko to,
    co zmieniło się od ostatniego razu — z porównaniem `>=`, a nie `>`, żeby
    rekord zapisany w tej samej sekundzie co poprzedni odczyt nie wypadł
    z synchronizacji na zawsze. Ponowne przetworzenie znanego rekordu nic nie
    kosztuje: hasze się zgadzają i pętla go pomija."""
    if tylko_id is not None:
        rekordy = []
        for paczka in _paczki(list(tylko_id)):
            wynik = klient.table("zdalne_rekordy").select("*").in_("id", paczka).execute()
            rekordy.extend(wynik.data or [])
        return rekordy

    def zapytanie_bazowe():
        return klient.table("zdalne_rekordy").select("*").eq("pojazd_id", wspolny_id).eq("tabela", tabela)

    if znacznik and _delta_wlaczona():
        try:
            return zapytanie_bazowe().gte(KOLUMNA_ZNACZNIKA, znacznik).execute().data or []
        except Exception:
            _wylacz_delte()

    return zapytanie_bazowe().execute().data or []


def _zastosuj_rekord(konfig, rekord, auto_id, znane):
    """Wgrywa JEDEN rekord z chmury do lokalnej bazy. Wspólne jądro pobierania,
    cofania odrzuconych zmian i przycisku „Weź wersję z chmury”.
    Zwraca 1, jeśli coś faktycznie zmieniło się lokalnie."""
    tabela = konfig["tabela"]
    kolumny = konfig["kolumny"]
    fk = konfig["fk"]

    zdalne_id = rekord["id"]
    lokalny = znane.get(zdalne_id)

    if rekord.get("usuniete"):
        if lokalny:
            with db.polacz_baze() as conn:
                conn.execute(f"DELETE FROM {tabela} WHERE id=?", (lokalny["id"],))
            return 1
        return 0

    dane = rekord["dane"] or {}
    nowy_hash = _hash_zawartosci(dane)

    # Bierzemy WYŁĄCZNIE pola, które faktycznie są w zdalnym rekordzie.
    # Klucza brakuje tylko wtedy, gdy rekord wypchnęła STARSZA wersja
    # aplikacji, nieznająca tej kolumny — a wtedy `dane.get()` zwracałoby
    # None i wyczyściłoby wartość lokalnie. Przy notatkach oznaczałoby to
    # ciche skasowanie ręcznie wpisanego tekstu tylko dlatego, że druga
    # osoba nie zaktualizowała jeszcze aplikacji. Celowe wyczyszczenie pola
    # po drugiej stronie wygląda inaczej — klucz JEST, tylko z null — więc
    # nadal się propaguje.
    wartosci = {nazwa: dane.get(nazwa) for nazwa in kolumny if nazwa in dane}
    for pole_fk, tabela_fk in fk.items():
        zdalny_fk = dane.get(f"{pole_fk}_zdalne")
        lokalny_fk = None
        if zdalny_fk:
            with db.polacz_baze() as conn:
                c = conn.cursor()
                c.execute(f"SELECT id FROM {tabela_fk} WHERE zdalne_id=?", (zdalny_fk,))
                w = c.fetchone()
                lokalny_fk = w[0] if w else None
        wartosci[pole_fk] = lokalny_fk

    if lokalny is None:
        # --- Zabezpieczenie przed dublowaniem przy migracji starszych tankowań ---
        if tabela == "tankowania":
            with db.polacz_baze() as conn:
                c = conn.cursor()
                c.execute(
                    "SELECT id FROM tankowania WHERE auto_id=? AND data=? AND przebieg=? AND kwota=?",
                    (auto_id, wartosci.get("data"), wartosci.get("przebieg"), wartosci.get("kwota"))
                )
                istniejacy = c.fetchone()
                if istniejacy:
                    conn.execute(
                        "UPDATE tankowania SET zdalne_id=?, zdalny_hash=? WHERE id=?",
                        (zdalne_id, nowy_hash, istniejacy[0])
                    )
                    znane[zdalne_id] = {"id": istniejacy[0], "hash": nowy_hash}
                    return 0
        # -------------------------------------------------------------------------

        # Tabele z naturalnym kluczem (dziś: budżety, z UNIQUE na
        # kategoria+okres) nie mogą po prostu wstawić rekordu z chmury —
        # trafiłyby w istniejący lokalny wiersz i wywróciły synchronizację
        # na indeksie. Zamiast tego PRZEJMUJEMY ten wiersz: nadpisujemy jego
        # wartości i przypinamy do niego zdalne id.
        klucz_scalania = konfig.get("klucz_scalania")
        if klucz_scalania and all(k in wartosci for k in klucz_scalania):
            warunki = " AND ".join(f"{k}=?" for k in klucz_scalania)
            parametry = tuple(wartosci[k] for k in klucz_scalania)
            with db.polacz_baze() as conn:
                c = conn.cursor()
                c.execute(
                    f"SELECT id FROM {tabela} WHERE auto_id=? AND {warunki}",
                    (auto_id,) + parametry
                )
                istniejacy = c.fetchone()
                if istniejacy:
                    przypisania_s = "".join(f"{k}=?," for k in wartosci)
                    conn.execute(
                        f"UPDATE {tabela} SET {przypisania_s} zdalne_id=?, zdalny_hash=? WHERE id=?",
                        tuple(wartosci.values()) + (zdalne_id, nowy_hash, istniejacy[0])
                    )
                    znane[zdalne_id] = {"id": istniejacy[0], "hash": nowy_hash}
                    return 1

        if tabela not in TABELE_POSREDNIE:
            wartosci["auto_id"] = auto_id
        wartosci["zdalne_id"] = zdalne_id
        wartosci["zdalny_hash"] = nowy_hash
        nazwy_kolumn = ",".join(wartosci.keys())
        znaki_zapytania = ",".join("?" for _ in wartosci)
        with db.polacz_baze() as conn:
            c = conn.cursor()
            c.execute(f"INSERT INTO {tabela} ({nazwy_kolumn}) VALUES ({znaki_zapytania})", tuple(wartosci.values()))
            znane[zdalne_id] = {"id": c.lastrowid, "hash": nowy_hash}
        return 1

    if nowy_hash != lokalny["hash"]:
        # Pusty słownik wartości (rekord bez żadnego znanego pola) dałby
        # składniowo błędne "SET , zdalny_hash=?" — wtedy odświeżamy sam hash.
        przypisania = "".join(f"{nazwa}=?," for nazwa in wartosci.keys())
        with db.polacz_baze() as conn:
            conn.execute(f"UPDATE {tabela} SET {przypisania} zdalny_hash=? WHERE id=?",
                         tuple(wartosci.values()) + (nowy_hash, lokalny["id"]))
        lokalny["hash"] = nowy_hash
        return 1

    return 0


def _pobierz_tabele(klient, wspolny_id, auto_id, konfig, znacznik=None, tylko_id=None):
    """Zwraca (ile_zmian, najwyzszy_znacznik_z_pobranych)."""
    tabela = konfig["tabela"]
    pobrano = 0
    najwyzszy = None

    zapytanie_znane = _zapytanie_tabeli(tabela, "id, zdalne_id, zdalny_hash", "zdalne_id IS NOT NULL")

    with db.polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(zapytanie_znane, (auto_id,))
        znane = {r["zdalne_id"]: {"id": r["id"], "hash": r["zdalny_hash"]} for r in c.fetchall()}

    for rekord in _pobierz_rekordy(klient, wspolny_id, tabela, znacznik, tylko_id):
        znacznik_rekordu = rekord.get(KOLUMNA_ZNACZNIKA)
        if znacznik_rekordu and (najwyzszy is None or str(znacznik_rekordu) > str(najwyzszy)):
            najwyzszy = znacznik_rekordu
        pobrano += _zastosuj_rekord(konfig, rekord, auto_id, znane)

    return pobrano, najwyzszy


def _synchronizuj_info_pojazdu(klient, wspolny_id, auto_id, rola=None):
    """Karta pojazdu (marka, VIN, polisa, wiadomość statusu...) jako jeden rekord.

    Współautor MOŻE ją zmieniać — to wspólny dowód rejestracyjny auta, a mieszka
    w nim m.in. wiadomość statusu („zatankowany do pełna”), czyli dokładnie to,
    po co zaprasza się drugą osobę. Podgląd wyłącznie czyta: nie zakłada rekordu
    i nigdy nie wysyła swojej wersji."""
    rola = rola or db.ROLA_WLASCICIEL
    tylko_czytam = (rola == db.ROLA_PODGLAD)
    with db.polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(f"SELECT {', '.join(KOLUMNY_POJAZDU)}, info_zdalne_id, zdalny_hash_info FROM samochody WHERE id=?", (auto_id,))
        w = c.fetchone()
    if not w:
        return 0, 0

    dane_lokalne = {k: w[k] for k in KOLUMNY_POJAZDU}
    info_zdalne_id = w["info_zdalne_id"]
    hash_ostatnio_zsynchronizowany = w["zdalny_hash_info"]
    hash_teraz = _hash_zawartosci(dane_lokalne)

    if info_zdalne_id:
        wynik = klient.table("zdalne_rekordy").select("*").eq("id", info_zdalne_id).execute()
    else:
        wynik = klient.table("zdalne_rekordy").select("*").eq("pojazd_id", wspolny_id).eq("tabela", "info_pojazdu").execute()
    rekord_zdalny = wynik.data[0] if wynik.data else None

    if rekord_zdalny is None:
        if tylko_czytam:
            return 0, 0
        wynik = klient.rpc("dodaj_zdalny_rekord", {"p_pojazd_id": wspolny_id, "p_tabela": "info_pojazdu", "p_dane": dane_lokalne}).execute()
        with db.polacz_baze() as conn:
            conn.execute("UPDATE samochody SET info_zdalne_id=?, zdalny_hash_info=? WHERE id=?", (wynik.data, hash_teraz, auto_id))
        return 1, 0

    info_zdalne_id = rekord_zdalny["id"]
    dane_zdalne = {k: (rekord_zdalny.get("dane") or {}).get(k) for k in KOLUMNY_POJAZDU}
    hash_zdalny = _hash_zawartosci(dane_zdalne)

    if hash_zdalny == hash_teraz:
        if not w["info_zdalne_id"] or hash_ostatnio_zsynchronizowany != hash_teraz:
            with db.polacz_baze() as conn:
                conn.execute("UPDATE samochody SET info_zdalne_id=?, zdalny_hash_info=? WHERE id=?", (info_zdalne_id, hash_teraz, auto_id))
        return 0, 0

    if hash_teraz != hash_ostatnio_zsynchronizowany and not tylko_czytam:
        klient.rpc("aktualizuj_zdalny_rekord", {"p_id": info_zdalne_id, "p_dane": dane_lokalne}).execute()
        with db.polacz_baze() as conn:
            conn.execute("UPDATE samochody SET info_zdalne_id=?, zdalny_hash_info=? WHERE id=?", (info_zdalne_id, hash_teraz, auto_id))
        return 1, 0

    przypisania = ",".join(f"{k}=?" for k in KOLUMNY_POJAZDU)
    with db.polacz_baze() as conn:
        conn.execute(
            f"UPDATE samochody SET {przypisania}, info_zdalne_id=?, zdalny_hash_info=? WHERE id=?",
            tuple(dane_zdalne[k] for k in KOLUMNY_POJAZDU) + (info_zdalne_id, hash_zdalny, auto_id)
        )
    return 0, 1

def _przywroc_tabele(klient, wspolny_id, auto_id, konfig):
    tabela = konfig["tabela"]
    kolumny = konfig["kolumny"]
    fk = konfig["fk"]
    przywrocono = 0

    zapytanie_znane = _zapytanie_tabeli(tabela, "zdalne_id", "zdalne_id IS NOT NULL")

    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute(zapytanie_znane, (auto_id,))
        znane = {r[0] for r in c.fetchall()}

    wynik = klient.table("zdalne_rekordy").select("*").eq("pojazd_id", wspolny_id).eq("tabela", tabela).eq("usuniete", False).execute()

    for rekord in wynik.data:
        zdalne_id = rekord["id"]
        if zdalne_id in znane:
            continue

        dane = rekord["dane"] or {}
        nowy_hash = _hash_zawartosci(dane)

        wartosci = {nazwa: dane.get(nazwa) for nazwa in kolumny}
        for pole_fk, tabela_fk in fk.items():
            zdalny_fk = dane.get(f"{pole_fk}_zdalne")
            lokalny_fk = None
            if zdalny_fk:
                with db.polacz_baze() as conn:
                    c = conn.cursor()
                    c.execute(f"SELECT id FROM {tabela_fk} WHERE zdalne_id=?", (zdalny_fk,))
                    w = c.fetchone()
                    lokalny_fk = w[0] if w else None
            wartosci[pole_fk] = lokalny_fk

        if tabela not in TABELE_POSREDNIE:
            wartosci["auto_id"] = auto_id
        wartosci["zdalne_id"] = zdalne_id
        wartosci["zdalny_hash"] = nowy_hash

        nazwy_kolumn = ",".join(wartosci.keys())
        znaki_zapytania = ",".join("?" for _ in wartosci)
        with db.polacz_baze() as conn:
            conn.execute(f"INSERT INTO {tabela} ({nazwy_kolumn}) VALUES ({znaki_zapytania})", tuple(wartosci.values()))
        with db.polacz_baze() as conn:
            conn.execute("DELETE FROM zdalne_nagrobki WHERE zdalny_id=?", (zdalne_id,))
        przywrocono += 1

    return przywrocono

def przywroc_z_chmury(auto_id):
    wspolny_id, _ = czy_udostepniony(auto_id)
    if not wspolny_id:
        return 0

    klient, uid = _upewnij_sesje()
    przywrocono = 0

    for konfig in KONFIGURACJA_SYNC:
        przywrocono += _przywroc_tabele(klient, wspolny_id, auto_id, konfig)

    # Po ręcznym przywracaniu znacznik delty przestaje być wiarygodny: dopiero
    # co wstawiliśmy lokalnie rekordy starsze niż on, a ich powiązania (FK po
    # zdalnych id) mogą dowiązywać się do rzeczy, których jeszcze nie mamy.
    # Następna synchronizacja ma przejść wszystko.
    db.wyczysc_znacznik_delty(auto_id)
    db.przelicz_wszystkie_zadania(auto_id)
    return przywrocono

def synchronizuj_wszystko(auto_id, pelne=False, czekaj=True):
    """Jedna synchronizacja pojazdu. `pelne=True` ignoruje znacznik delty
    i ściąga komplet („Pobierz wszystko od nowa”).

    Cały przebieg jest pod zamkiem: auto-synchronizacja po zapisie formularza
    leci przez page.run_task, więc dwa szybkie zapisy pod rząd uruchamiały dwa
    przebiegi naraz — obydwa czytały ten sam `zdalny_hash`, obydwa wypychały
    i jeden nadpisywał drugiemu wynik. Wywołanie z `czekaj=False` (tło) po
    prostu odpuszcza, gdy inna synchronizacja właśnie trwa; ręczne czeka."""
    wspolny_id, _ = czy_udostepniony(auto_id)
    if not wspolny_id:
        return 0, 0

    nabyty = _ZAMEK_SYNC.acquire(timeout=180) if czekaj else _ZAMEK_SYNC.acquire(blocking=False)
    if not nabyty:
        raise SynchronizacjaWToku("Inna synchronizacja właśnie trwa.")
    try:
        return _synchronizuj_pod_zamkiem(auto_id, wspolny_id, pelne)
    finally:
        _ZAMEK_SYNC.release()


def pelna_synchronizacja(auto_id):
    """Pomija deltę i przechodzi całą chmurę od zera — ratunek, gdy lokalna baza
    rozjechała się z serwerem (np. po przywróceniu kopii zapasowej)."""
    db.wyczysc_znacznik_delty(auto_id)
    return synchronizuj_wszystko(auto_id, pelne=True)


def _synchronizuj_pod_zamkiem(auto_id, wspolny_id, pelne=False):
    # --- ZABEZPIECZENIE: Reset starszych tankowań wgranych starą metodą ---
    # Wymuszamy, by stare tankowania (mające ID ze starej tabeli Supabase) 
    # zostały uznane za nowe i wypchnięte do nowej tabeli zdalne_rekordy.
    if db.pobierz_ustawienie("migracja_tankowan_v4") != "1":
        with db.polacz_baze() as conn:
            conn.execute("UPDATE tankowania SET zdalne_id = NULL, zdalny_hash = NULL")
        db.zapisz_ustawienie("migracja_tankowan_v4", "1")
    # ----------------------------------------------------------------------

    klient, uid = _upewnij_sesje()
    rola = db.rola_pojazdu(auto_id)
    _konflikty_biezacej_synchronizacji.clear()
    _odrzucone_biezacej_synchronizacji.clear()

    # Znacznik delty: pobieramy tylko to, co zmieniło się od ostatniego razu.
    # Pusty znacznik (pierwsza synchronizacja, świeżo dołączony pojazd, żądanie
    # pełnego pobrania) oznacza przejście całej chmury, tak jak dotąd.
    znacznik = None if pelne else db.znacznik_delty(auto_id)

    wyslano = 0
    pobrano = 0
    do_cofniecia = {}

    if rola != db.ROLA_PODGLAD:
        _wypchnij_nagrobki(klient, auto_id)

    w_info, p_info = _synchronizuj_info_pojazdu(klient, wspolny_id, auto_id, rola)
    wyslano += w_info
    pobrano += p_info

    for konfig in KONFIGURACJA_SYNC:
        ile, cofnij = _wypchnij_tabele(klient, wspolny_id, auto_id, konfig, rola)
        wyslano += ile
        if cofnij:
            do_cofniecia[konfig["tabela"]] = cofnij

    najwyzszy_znacznik = None
    for konfig in KONFIGURACJA_SYNC:
        ile, znacznik_tabeli = _pobierz_tabele(klient, wspolny_id, auto_id, konfig, znacznik)
        pobrano += ile
        if znacznik_tabeli and (najwyzszy_znacznik is None or str(znacznik_tabeli) > str(najwyzszy_znacznik)):
            najwyzszy_znacznik = znacznik_tabeli

    # Zmiany odrzucone przez rolę współautora cofamy do wersji z chmury. Robimy
    # to osobnym, celowanym zapytaniem, bo przy synchronizacji przyrostowej te
    # rekordy nie zmieniły się zdalnie i w deltę by nie weszły.
    for konfig in KONFIGURACJA_SYNC:
        identyfikatory = do_cofniecia.get(konfig["tabela"])
        if identyfikatory:
            ile, _ = _pobierz_tabele(klient, wspolny_id, auto_id, konfig, tylko_id=identyfikatory)
            pobrano += ile

    if najwyzszy_znacznik:
        db.zapisz_znacznik_delty(auto_id, najwyzszy_znacznik)

    db.przelicz_wszystkie_zadania(auto_id)
    db.zapisz_ustawienie("ostatnia_synchronizacja", datetime.now().strftime("%d.%m.%Y %H:%M"))
    # Udana synchronizacja zamyka sprawę także dla kolejki. Wcześniej wpis
    # kasował się wyłącznie w synchronizuj_w_tle i przetworz_kolejke_sync, więc
    # po ręcznym „Synchronizuj teraz” pomarańczowa kropka „czeka na wysłanie”
    # potrafiła wisieć aż do końca backoffu — nawet godzinę po tym, jak
    # wszystko już poszło.
    db.usun_z_kolejki_sync(auto_id)

    return wyslano, pobrano


def przyjmij_wersje_z_chmury(auto_id, konflikty):
    """Cofa nadpisanie wykryte przy konflikcie: wpisuje lokalnie wersje
    zapamiętane w chwili wykrycia i odsyła je do chmury, żeby obie strony
    znów mówiły to samo. Zwraca liczbę przywróconych rekordów."""
    wspolny_id, _ = czy_udostepniony(auto_id)
    if not wspolny_id:
        return 0

    po_tabelach = {}
    for k in konflikty or []:
        if k.get("dane_zdalne") is None or not k.get("zdalne_id"):
            continue
        po_tabelach.setdefault(k.get("tabela"), []).append(k)
    if not po_tabelach:
        return 0

    klient, uid = _upewnij_sesje()
    przyjeto = 0

    for konfig in KONFIGURACJA_SYNC:
        pozycje = po_tabelach.get(konfig["tabela"])
        if not pozycje:
            continue

        zapytanie_znane = _zapytanie_tabeli(konfig["tabela"], "id, zdalne_id, zdalny_hash", "zdalne_id IS NOT NULL")
        with db.polacz_baze() as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute(zapytanie_znane, (auto_id,))
            znane = {r["zdalne_id"]: {"id": r["id"], "hash": r["zdalny_hash"]} for r in c.fetchall()}

        for k in pozycje:
            rekord = {"id": k["zdalne_id"], "dane": k["dane_zdalne"], "usuniete": False}
            przyjeto += _zastosuj_rekord(konfig, rekord, auto_id, znane)
            klient.rpc("aktualizuj_zdalny_rekord", {"p_id": k["zdalne_id"], "p_dane": k["dane_zdalne"]}).execute()

    db.przelicz_wszystkie_zadania(auto_id)
    return przyjeto

def odlacz_wspoldzielenie(auto_id):
    with db.polacz_baze() as conn:
        # Razem ze współdzieleniem znikają rola i kody — pojazd wraca do stanu
        # w pełni offline, w którym „wszystko wolno”, a nie do trybu podglądu
        # bez chmury, w którym nie dałoby się już nic dopisać.
        conn.execute(
            "UPDATE samochody SET wspolny_pojazd_id=NULL, kod_zaproszenia=NULL, "
            "info_zdalne_id=NULL, zdalny_hash_info=NULL, znacznik_delty=NULL, "
            "kod_wspolautora=NULL, kod_podgladu=NULL, rola_wspoldzielenia=? WHERE id=?",
            (db.ROLA_WLASCICIEL, auto_id)
        )
        for konfig in KONFIGURACJA_SYNC:
            tabela = konfig["tabela"]
            opis_posredni = TABELE_POSREDNIE.get(tabela)
            warunek = opis_posredni["reset_where"] if opis_posredni else "auto_id=?"
            conn.execute(
                f"UPDATE {tabela} SET zdalne_id=NULL, zdalny_hash=NULL WHERE {warunek}",
                (auto_id,)
            )

def synchronizuj_w_tle(auto_id, powod="zapis"):
    """Cicha synchronizacja po zapisie formularza. NIE rzuca wyjątków, ale — w
    przeciwieństwie do dawnego `except: pass` — nieudana próba trafia do kolejki
    (kolejka_sync) i zostanie automatycznie ponowiona. Zwraca (czy_udane, blad)."""
    wspolny_id, _ = czy_udostepniony(auto_id)
    if not wspolny_id:
        return True, None
    try:
        # czekaj=False: gdy inna synchronizacja właśnie trwa, ta odpuszcza
        # zamiast wyścigać się z nią o `zdalny_hash`. Zapis nie ginie — pojazd
        # ląduje w kolejce i zostanie dociągnięty przy ponowieniu.
        synchronizuj_wszystko(auto_id, czekaj=False)
        db.usun_z_kolejki_sync(auto_id)
        return True, None
    except SynchronizacjaWToku:
        db.zakolejkuj_synchronizacje(auto_id, powod, "Inna synchronizacja w toku")
        return False, None
    except Exception as ex:
        db.zakolejkuj_synchronizacje(auto_id, powod, str(ex))
        return False, str(ex)

def przetworz_kolejke_sync(limit=5):
    """Ponawia zaległe synchronizacje, których termin ponowienia już minął.
    Wołane przy starcie aplikacji i przy każdym kolejnym zapisie — nie rzuca
    wyjątków, kolejny nieudany strzał tylko odsuwa termin (backoff w db).
    Zwraca liczbę pojazdów zsynchronizowanych z zaległości."""
    udane = 0
    for auto_id, _powod, _proby in db.pobierz_kolejke_sync(limit=limit):
        wspolny_id, _ = czy_udostepniony(auto_id)
        if not wspolny_id:
            db.usun_z_kolejki_sync(auto_id)  # pojazd odłączony od chmury — kolejka bezprzedmiotowa
            continue
        try:
            # Tu czekamy na zamek: to już jest ponowienie, więc odpuszczenie
            # oznaczałoby kolejne odsunięcie terminu zamiast wykonania roboty.
            synchronizuj_wszystko(auto_id)
            db.usun_z_kolejki_sync(auto_id)
            udane += 1
        except SynchronizacjaWToku:
            continue  # zostaje w kolejce na następne podejście, bez backoffu
        except Exception as ex:
            db.zakolejkuj_synchronizacje(auto_id, "ponowienie", str(ex))
    return udane