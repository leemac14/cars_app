"""
Współdzielenie pojazdu — synchronizacja z Supabase.

Reszta aplikacji działa dokładnie jak dotychczas: w 100% lokalnie i offline.
Ten moduł włącza się TYLKO dla pojazdu świadomie oznaczonego jako współdzielony
(samochody.wspolny_pojazd_id IS NOT NULL). Synchronizowane są: tankowania (stara,
dedykowana tabela zdalne_tankowania) oraz reszta danych pojazdu — podzespoły,
historia serwisowa, wizyty zbiorcze, magazyn części, zestawy opon, inne koszty,
warsztaty, wydatki cykliczne, odczyty przebiegu i lista Do zrobienia (nowa,
uniwersalna tabela zdalne_rekordy — patrz KONFIGURACJA_SYNC).

NIE są i nie będą synchronizowane:
- Załączniki (zdjęcia, PDF-y) — zostają wyłącznie lokalne na każdym urządzeniu.
- Zdjęcia karoserii (zdjecia_karoserii) — bez samego pliku wpis jest bezużyteczny.
- Powiązanie zużytych części z magazynu z wizytą (wizyta_czesci_magazynu) —
  każde urządzenie samo rozlicza swój lokalny stan magazynowy.
- Edycje i usunięcia już zsynchronizowanych rekordów — synchronizowane są
  wyłącznie NOWE wpisy (insert-only, tak jak dotychczas dla tankowań).
"""
import uuid as uuid_lib
import sqlite3
import json
import hashlib
import db

# --- UZUPEŁNIJ PO ZAŁOŻENIU PROJEKTU NA supabase.com (Project Settings -> API) ---
SUPABASE_URL = "https://ptnnejbuvymhrkouwsln.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InB0bm5lamJ1dnltaHJrb3V3c2xuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODc2NTg2NTQsImV4cCI6MjEwMzIzNDY1NH0.xfLcVeiNatGqFtBBnvSB2EOZoo9i_vodDqtF6XLC9iA"
# Klucz "anon" jest bezpieczny w kodzie — realne bezpieczeństwo daje RLS w bazie.
# ----------------------------------------------------------------------------------

_klient_cache = None


def _pobierz_klient():
    global _klient_cache
    if _klient_cache is None:
        from supabase import create_client
        _klient_cache = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    return _klient_cache

def _upewnij_sesje():
    """Zwraca (klient, moje_uid). Loguje anonimowo przy pierwszym użyciu, trzyma
    sesję w 'ustawienia' (set_session sam odświeży access_token, jeśli wygasł),
    podpina token pod zapytania i zwraca własne uid — używane wprost przy
    insertach zamiast polegać na kolumnowym DEFAULT auth.uid()."""
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
            pass

    wynik = klient.auth.sign_in_anonymously()
    sesja = wynik.session
    db.zapisz_ustawienie("supabase_access_token", sesja.access_token)
    db.zapisz_ustawienie("supabase_refresh_token", sesja.refresh_token)
    klient.postgrest.auth(token=sesja.access_token)
    return klient, sesja.user.id

def czy_udostepniony(auto_id):
    """(wspolny_pojazd_id, kod_zaproszenia) albo (None, None). Bez sieci."""
    if not auto_id:
        return None, None
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT wspolny_pojazd_id, kod_zaproszenia FROM samochody WHERE id=?", (auto_id,))
        w = c.fetchone()
    return (w[0], w[1]) if w and w[0] else (None, None)


def utworz_udostepniony_pojazd(auto_id, nazwa):
    klient, uid = _upewnij_sesje()
    kod = uuid_lib.uuid4().hex[:6].upper()

    wynik = klient.rpc("utworz_udostepniony_pojazd", {"p_nazwa": nazwa, "p_kod": kod}).execute()
    nowy_id = wynik.data  # funkcja zwraca pojedynczy uuid, nie listę wierszy

    with db.polacz_baze() as conn:
        conn.execute(
            "UPDATE samochody SET wspolny_pojazd_id=?, kod_zaproszenia=? WHERE id=?",
            (nowy_id, kod, auto_id)
        )
    return kod


def dolacz_po_kodzie(kod):
    """Dołącza do cudzego pojazdu po kodzie. TWORZY nowy lokalny wpis
    w 'samochody' (nie trzeba wcześniej ręcznie dodawać auta) i od razu ściąga
    jego dotychczasowe tankowania. Zwraca (nowy_auto_id, nazwa)."""
    klient, uid = _upewnij_sesje()
    wynik = klient.rpc("dolacz_do_pojazdu", {"p_kod": kod.strip().upper()}).execute()
    if not wynik.data:
        raise ValueError("Nieprawidłowy kod zaproszenia.")
        
    wspolny_id = wynik.data[0]["pojazd_id"]
    nazwa = wynik.data[0]["nazwa"]

    with db.polacz_baze() as conn:
        cur = conn.cursor()
        # Sprawdzamy czy auto o tej nazwie już u nas lokalnie istnieje
        cur.execute("SELECT id FROM samochody WHERE LOWER(nazwa)=LOWER(?)", (nazwa,))
        istniejace = cur.fetchone()

        if istniejace:
            nowy_auto_id = istniejace[0]
            cur.execute(
                "UPDATE samochody SET wspolny_pojazd_id=?, kod_zaproszenia=? WHERE id=?",
                (wspolny_id, kod.strip().upper(), nowy_auto_id)
            )
        else:
            cur.execute(
                "INSERT INTO samochody (nazwa, wspolny_pojazd_id, kod_zaproszenia) VALUES (?,?,?)",
                (nazwa, wspolny_id, kod.strip().upper())
            )
            nowy_auto_id = cur.lastrowid

    synchronizuj_wszystko(nowy_auto_id)
    return nowy_auto_id, nazwa

def synchronizuj_tankowania(auto_id):
    """Synchronizuje tankowania: nowe wiersze, edycje (wykrywane hashem
    zawartości) i usunięcia — analogicznie do synchronizuj_reszte_pojazdu(), ale
    przez starszą, dedykowaną tabelę Supabase 'zdalne_tankowania'."""
    wspolny_id, _ = czy_udostepniony(auto_id)
    if not wspolny_id:
        return 0, 0

    klient, uid = _upewnij_sesje()
    _wypchnij_nagrobki(klient)
    wyslano = 0

    kolumny_tankowania = ["data", "przebieg", "dystans", "litry", "kwota", "do_pelna", "stacja", "tagi"]

    def zbuduj_dane(wiersz):
        return {k: wiersz[k] for k in kolumny_tankowania}

    # 1. Nowe wiersze
    with db.polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM tankowania WHERE auto_id=? AND zdalne_id IS NULL", (auto_id,))
        do_wyslania = c.fetchall()

    for wiersz in do_wyslania:
        wynik = klient.rpc("dodaj_zdalne_tankowanie", {
            "p_pojazd_id": wspolny_id, "p_data": wiersz["data"], "p_przebieg": wiersz["przebieg"],
            "p_dystans": wiersz["dystans"], "p_litry": wiersz["litry"], "p_kwota": wiersz["kwota"],
            "p_do_pelna": bool(wiersz["do_pelna"]), "p_stacja": wiersz["stacja"], "p_tagi": wiersz["tagi"],
        }).execute()
        nowe_zdalne_id = wynik.data
        nowy_hash = _hash_zawartosci(zbuduj_dane(wiersz))
        with db.polacz_baze() as conn:
            conn.execute("UPDATE tankowania SET zdalne_id=?, zdalny_hash=? WHERE id=?", (nowe_zdalne_id, nowy_hash, wiersz["id"]))
        wyslano += 1

    # 2. Edytowane wiersze (już wcześniej zsynchronizowane, zmienione lokalnie)
    with db.polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM tankowania WHERE auto_id=? AND zdalne_id IS NOT NULL", (auto_id,))
        istniejace = c.fetchall()

    for wiersz in istniejace:
        dane = zbuduj_dane(wiersz)
        nowy_hash = _hash_zawartosci(dane)
        if nowy_hash == wiersz["zdalny_hash"]:
            continue

        klient.rpc("aktualizuj_zdalne_tankowanie", {
            "p_id": wiersz["zdalne_id"], "p_data": dane["data"], "p_przebieg": dane["przebieg"],
            "p_dystans": dane["dystans"], "p_litry": dane["litry"], "p_kwota": dane["kwota"],
            "p_do_pelna": bool(dane["do_pelna"]), "p_stacja": dane["stacja"], "p_tagi": dane["tagi"],
        }).execute()
        with db.polacz_baze() as conn:
            conn.execute("UPDATE tankowania SET zdalny_hash=? WHERE id=?", (nowy_hash, wiersz["id"]))
        wyslano += 1

    # 3. Pobieranie: nowe, zmienione i usunięte na serwerze
    with db.polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT id, zdalne_id, zdalny_hash FROM tankowania WHERE auto_id=? AND zdalne_id IS NOT NULL", (auto_id,))
        znane = {r["zdalne_id"]: {"id": r["id"], "hash": r["zdalny_hash"]} for r in c.fetchall()}

    wynik = klient.table("zdalne_tankowania").select("*").eq("pojazd_id", wspolny_id).execute()
    pobrano = 0
    for w in wynik.data:
        lokalny = znane.get(w["id"])

        if w.get("usuniete"):
            if lokalny:
                with db.polacz_baze() as conn:
                    conn.execute("DELETE FROM tankowania WHERE id=?", (lokalny["id"],))
            continue

        dane = {
            "data": w["data"], "przebieg": w["przebieg"], "dystans": w["dystans"] or 0.0,
            "litry": w["litry"], "kwota": w["kwota"], "do_pelna": 1 if w["do_pelna"] else 0,
            "stacja": w["stacja"], "tagi": w["tagi"],
        }
        nowy_hash = _hash_zawartosci(dane)

        if lokalny is None:
            with db.polacz_baze() as conn:
                conn.execute(
                    "INSERT INTO tankowania (auto_id, data, przebieg, dystans, litry, kwota, do_pelna, stacja, tagi, zdalne_id, zdalny_hash) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (auto_id, dane["data"], dane["przebieg"], dane["dystans"], dane["litry"], dane["kwota"],
                     dane["do_pelna"], dane["stacja"], dane["tagi"], w["id"], nowy_hash)
                )
            pobrano += 1
        elif nowy_hash != lokalny["hash"]:
            with db.polacz_baze() as conn:
                conn.execute(
                    "UPDATE tankowania SET data=?, przebieg=?, dystans=?, litry=?, kwota=?, do_pelna=?, stacja=?, tagi=?, zdalny_hash=? WHERE id=?",
                    (dane["data"], dane["przebieg"], dane["dystans"], dane["litry"], dane["kwota"],
                     dane["do_pelna"], dane["stacja"], dane["tagi"], nowy_hash, lokalny["id"])
                )
            pobrano += 1

    return wyslano, pobrano

# ==================== SYNCHRONIZACJA RESZTY POJAZDU ====================
# Uniwersalny mechanizm dla WSZYSTKICH operacji (dodanie/edycja/usunięcie),
# korzystający z jednej wspólnej tabeli Supabase "zdalne_rekordy". Kolejność
# listy MA ZNACZENIE: tabele z kluczami obcymi (fk) muszą być zsynchronizowane
# PO tabelach, do których się odwołują.
KONFIGURACJA_SYNC = [
    {"tabela": "zadania", "kolumny": ["nazwa", "interwal_km", "interwal_miesiace", "dotyczy_opon"], "fk": {}},
    {"tabela": "wizyty", "kolumny": ["data", "przebieg", "wykonawca", "koszt_calkowity", "notatki", "tagi"], "fk": {}},
    {"tabela": "historia", "kolumny": ["data", "przebieg", "kategoria", "cena", "wykonawca"], "fk": {"zadanie_id": "zadania", "wizyta_id": "wizyty"}},
    {"tabela": "magazyn_czesci", "kolumny": ["nazwa", "kategoria", "ilosc", "jednostka", "cena", "data_zakupu", "notatki", "prog_ostrzezenia"], "fk": {}},
    {"tabela": "zestawy_opon", "kolumny": ["sezon", "rozmiar", "marka_model", "glebokosc_bieznika", "data_pomiaru", "numer_dot", "ilosc", "zamontowane", "data_zakupu", "przebieg_zakupu", "cena", "notatki", "os_montazu"], "fk": {}},
    {"tabela": "inne_koszty", "kolumny": ["data", "kategoria", "nazwa", "kwota", "tagi"], "fk": {}},
    {"tabela": "warsztaty", "kolumny": ["nazwa", "telefon", "adres", "notatki"], "fk": {}},
    {"tabela": "wydatki_cykliczne", "kolumny": ["nazwa", "kwota", "okres_dni", "nastepna_data"], "fk": {}},
    {"tabela": "odczyty_przebiegu", "kolumny": ["data", "przebieg"], "fk": {}},
    {"tabela": "do_zrobienia", "kolumny": ["tytul", "opis", "priorytet", "szacowany_koszt", "termin", "wykonane", "data_utworzenia"], "fk": {"zadanie_id": "zadania"}},
]


def _hash_zawartosci(dane: dict) -> str:
    """Stabilny hash zawartości rekordu (niezależny od kolejności kluczy) —
    używany do wykrywania, czy wiersz zmienił się od ostatniej synchronizacji."""
    kanoniczny = json.dumps(dane, sort_keys=True, default=str, ensure_ascii=True)
    return hashlib.sha256(kanoniczny.encode("utf-8")).hexdigest()


def _wypchnij_nagrobki(klient):
    """Wypycha WSZYSTKIE oczekujące lokalne usunięcia (niezależnie od pojazdu —
    kasowanie po zdalnym ID nie wymaga kontekstu konkretnego pojazdu) i czyści
    lokalne nagrobki po udanym wypchnięciu. Błąd pojedynczego nagrobka (np. brak
    sieci) zostawia go w kolejce do kolejnej próby, nie przerywa reszty."""
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT id, tabela, zdalny_id FROM zdalne_nagrobki")
        nagrobki = c.fetchall()

    for nagrobek_id, tabela, zdalny_id in nagrobki:
        try:
            if tabela == "tankowania":
                klient.rpc("usun_zdalne_tankowanie", {"p_id": zdalny_id}).execute()
            else:
                klient.rpc("usun_zdalny_rekord", {"p_id": zdalny_id}).execute()
            with db.polacz_baze() as conn:
                conn.execute("DELETE FROM zdalne_nagrobki WHERE id=?", (nagrobek_id,))
        except Exception:
            pass


def _wypchnij_tabele(klient, wspolny_id, auto_id, konfig):
    """Wypycha NOWE lokalne wiersze (insert) oraz aktualizuje na serwerze te,
    które zmieniły się lokalnie od ostatniej synchronizacji (wykryte przez
    porównanie hasha zawartości — zdalny_hash)."""
    tabela = konfig["tabela"]
    kolumny = konfig["kolumny"]
    fk = konfig["fk"]
    wyslano = 0

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

    # 1. Nowe wiersze
    # UWAGA: tabela "historia" nie ma własnej kolumny auto_id — pojazd wynika
    # pośrednio z zadanie_id -> zadania.auto_id, więc wymaga osobnego zapytania z JOIN-em.
    if tabela == "historia":
        zapytanie_nowe = (
            "SELECT h.* FROM historia h JOIN zadania z ON h.zadanie_id = z.id "
            "WHERE z.auto_id=? AND h.zdalne_id IS NULL"
        )
    else:
        zapytanie_nowe = f"SELECT * FROM {tabela} WHERE auto_id=? AND zdalne_id IS NULL"

    with db.polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(zapytanie_nowe, (auto_id,))
        do_wyslania = c.fetchall()

    print(f"[DIAG-SYNC] {tabela}: znaleziono {len(do_wyslania)} nowych wierszy do wyslania")  # TYMCZASOWE

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

    # 2. Wiersze już zsynchronizowane, zmienione lokalnie od ostatniego razu
    if tabela == "historia":
        zapytanie_istniejace = (
            "SELECT h.* FROM historia h JOIN zadania z ON h.zadanie_id = z.id "
            "WHERE z.auto_id=? AND h.zdalne_id IS NOT NULL"
        )
    else:
        zapytanie_istniejace = f"SELECT * FROM {tabela} WHERE auto_id=? AND zdalne_id IS NOT NULL"

    with db.polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(zapytanie_istniejace, (auto_id,))
        istniejace = c.fetchall()

    for wiersz in istniejace:
        dane = zbuduj_dane(wiersz)
        nowy_hash = _hash_zawartosci(dane)
        if nowy_hash == wiersz["zdalny_hash"]:
            continue  # nic się nie zmieniło

        klient.rpc("aktualizuj_zdalny_rekord", {"p_id": wiersz["zdalne_id"], "p_dane": dane}).execute()
        with db.polacz_baze() as conn:
            conn.execute(f"UPDATE {tabela} SET zdalny_hash=? WHERE id=?", (nowy_hash, wiersz["id"]))
        wyslano += 1

    return wyslano


def _pobierz_tabele(klient, wspolny_id, auto_id, konfig):
    """Ściąga nowe wiersze, aktualizuje lokalnie te zmienione na serwerze i
    kasuje te oznaczone jako usunięte (usuniete=true)."""
    tabela = konfig["tabela"]
    kolumny = konfig["kolumny"]
    fk = konfig["fk"]
    pobrano = 0

    if tabela == "historia":
        zapytanie_znane = (
            "SELECT h.id, h.zdalne_id, h.zdalny_hash FROM historia h "
            "JOIN zadania z ON h.zadanie_id = z.id "
            "WHERE z.auto_id=? AND h.zdalne_id IS NOT NULL"
        )
    else:
        zapytanie_znane = f"SELECT id, zdalne_id, zdalny_hash FROM {tabela} WHERE auto_id=? AND zdalne_id IS NOT NULL"

    with db.polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(zapytanie_znane, (auto_id,))
        znane = {r["zdalne_id"]: {"id": r["id"], "hash": r["zdalny_hash"]} for r in c.fetchall()}

    wynik = klient.table("zdalne_rekordy").select("*").eq("pojazd_id", wspolny_id).eq("tabela", tabela).execute()

    for rekord in wynik.data:
        zdalne_id = rekord["id"]
        lokalny = znane.get(zdalne_id)

        if rekord.get("usuniete"):
            if lokalny:
                with db.polacz_baze() as conn:
                    conn.execute(f"DELETE FROM {tabela} WHERE id=?", (lokalny["id"],))
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

        if lokalny is None:
            # historia nie ma kolumny auto_id — pojazd wynika z zadanie_id (patrz wyżej)
            if tabela != "historia":
                wartosci["auto_id"] = auto_id
            wartosci["zdalne_id"] = zdalne_id
            wartosci["zdalny_hash"] = nowy_hash
            nazwy_kolumn = ",".join(wartosci.keys())
            znaki_zapytania = ",".join("?" for _ in wartosci)
            with db.polacz_baze() as conn:
                conn.execute(f"INSERT INTO {tabela} ({nazwy_kolumn}) VALUES ({znaki_zapytania})", tuple(wartosci.values()))
            pobrano += 1
        elif nowy_hash != lokalny["hash"]:
            przypisania = ",".join(f"{nazwa}=?" for nazwa in wartosci.keys())
            with db.polacz_baze() as conn:
                conn.execute(f"UPDATE {tabela} SET {przypisania}, zdalny_hash=? WHERE id=?",
                             tuple(wartosci.values()) + (nowy_hash, lokalny["id"]))
            pobrano += 1

    return pobrano


def synchronizuj_reszte_pojazdu(auto_id):
    """Synchronizuje WSZYSTKIE dane pojazdu oprócz tankowań: nowe wiersze, edycje
    i usunięcia (patrz KONFIGURACJA_SYNC). Bez efektu (0, 0), jeśli pojazd nie
    jest współdzielony. Zwraca (wyslano, pobrano)."""
    wspolny_id, _ = czy_udostepniony(auto_id)
    print(f"[DIAG-SYNC] auto_id={auto_id} wspolny_id={wspolny_id}")  # TYMCZASOWE
    if not wspolny_id:
        return 0, 0

    klient, uid = _upewnij_sesje()
    _wypchnij_nagrobki(klient)

    wyslano = sum(_wypchnij_tabele(klient, wspolny_id, auto_id, konfig) for konfig in KONFIGURACJA_SYNC)
    pobrano = sum(_pobierz_tabele(klient, wspolny_id, auto_id, konfig) for konfig in KONFIGURACJA_SYNC)

    db.przelicz_wszystkie_zadania(auto_id)

    return wyslano, pobrano

def synchronizuj_wszystko(auto_id):
    """Pełna synchronizacja współdzielonego pojazdu: tankowania (stara, dedykowana
    ścieżka przez zdalne_tankowania) + reszta danych pojazdu (nowa, uniwersalna
    ścieżka przez zdalne_rekordy — patrz synchronizuj_reszte_pojazdu). Widoki
    powinny wywoływać TĘ funkcję zamiast synchronizuj_tankowania() bezpośrednio."""
    wyslano_t, pobrano_t = synchronizuj_tankowania(auto_id)
    wyslano_r, pobrano_r = synchronizuj_reszte_pojazdu(auto_id)
    return wyslano_t + wyslano_r, pobrano_t + pobrano_r

def odlacz_wspoldzielenie(auto_id):
    """Rozłącza lokalny pojazd z chmurą. Pojazd wraca do trybu 100% offline,
    a wszystkie dotychczas pobrane dane zostają zachowane lokalnie. Czyścimy
    zdalne_id na wszystkich zsynchronizowanych tabelach, żeby ponowne
    udostępnienie tego auta zaczęło od nowa (analogicznie jak dla tankowań)."""
    with db.polacz_baze() as conn:
        conn.execute(
            "UPDATE samochody SET wspolny_pojazd_id=NULL, kod_zaproszenia=NULL WHERE id=?",
            (auto_id,)
        )
        conn.execute("UPDATE tankowania SET zdalne_id=NULL, zdalny_hash=NULL WHERE auto_id=?", (auto_id,))
        for konfig in KONFIGURACJA_SYNC:
            tabela = konfig["tabela"]
            # UWAGA: "historia" nie ma własnej kolumny auto_id — pojazd wynika
            # pośrednio z zadanie_id -> zadania.auto_id, stąd osobna ścieżka z podzapytaniem.
            if tabela == "historia":
                conn.execute(
                    "UPDATE historia SET zdalne_id=NULL, zdalny_hash=NULL "
                    "WHERE zadanie_id IN (SELECT id FROM zadania WHERE auto_id=?)",
                    (auto_id,)
                )
            else:
                conn.execute(f"UPDATE {tabela} SET zdalne_id=NULL, zdalny_hash=NULL WHERE auto_id=?", (auto_id,))