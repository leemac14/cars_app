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
import db
import sqlite3

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
    """Wypycha lokalne, jeszcze niewysłane tankowania, po czym ściąga te
    dodane przez współlaczników. Zwraca (wyslano, pobrano). Bez efektu
    (0, 0), jeśli pojazd nie jest współdzielony — bezpieczne do wywołania
    zawsze, nawet dla lokalnych aut."""
    wspolny_id, _ = czy_udostepniony(auto_id)
    if not wspolny_id:
        return 0, 0

    klient, uid = _upewnij_sesje()
    wyslano = 0

    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, data, przebieg, dystans, litry, kwota, do_pelna, stacja, tagi "
            "FROM tankowania WHERE auto_id=? AND zdalne_id IS NULL", (auto_id,)
        )
        do_wyslania = c.fetchall()

    for lokalny_id, data, przebieg, dystans, litry, kwota, do_pelna, stacja, tagi in do_wyslania:
        wynik = klient.rpc("dodaj_zdalne_tankowanie", {
            "p_pojazd_id": wspolny_id, "p_data": data, "p_przebieg": przebieg,
            "p_dystans": dystans, "p_litry": litry, "p_kwota": kwota,
            "p_do_pelna": bool(do_pelna), "p_stacja": stacja, "p_tagi": tagi,
        }).execute()
        nowe_zdalne_id = wynik.data
        with db.polacz_baze() as conn:
            conn.execute("UPDATE tankowania SET zdalne_id=? WHERE id=?", (nowe_zdalne_id, lokalny_id))
        wyslano += 1

    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT zdalne_id FROM tankowania WHERE auto_id=? AND zdalne_id IS NOT NULL", (auto_id,))
        znane = {r[0] for r in c.fetchall()}

    wynik = klient.table("zdalne_tankowania").select("*").eq("pojazd_id", wspolny_id).eq("usuniete", False).execute()
    pobrano = 0
    for w in wynik.data:
        if w["id"] in znane:
            continue
        with db.polacz_baze() as conn:
            conn.execute(
                "INSERT INTO tankowania (auto_id, data, przebieg, dystans, litry, kwota, do_pelna, stacja, tagi, zdalne_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (auto_id, w["data"], w["przebieg"], w["dystans"] or 0.0, w["litry"], w["kwota"],
                 1 if w["do_pelna"] else 0, w["stacja"], w["tagi"], w["id"])
            )
        pobrano += 1

    return wyslano, pobrano

# ==================== SYNCHRONIZACJA RESZTY POJAZDU ====================
# Uniwersalny mechanizm insert-only, korzystający z JEDNEJ wspólnej tabeli
# Supabase "zdalne_rekordy" (zamiast osobnej tabeli per typ danych, jak przy
# tankowaniach). Kolejność listy MA ZNACZENIE: tabele z kluczami obcymi (fk)
# muszą być zsynchronizowane PO tabelach, do których się odwołują.
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


def _wypchnij_tabele(klient, wspolny_id, auto_id, konfig):
    """Wypycha nowe (jeszcze niezsynchronizowane) lokalne wiersze jednej tabeli
    do uniwersalnej tabeli zdalne_rekordy. Klucze obce (fk) są zamieniane na
    zdalne_id powiązanego rekordu i zapisywane w JSON pod kluczem '<pole>_zdalne'."""
    tabela = konfig["tabela"]
    kolumny = konfig["kolumny"]
    fk = konfig["fk"]
    wyslano = 0

    with db.polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(f"SELECT * FROM {tabela} WHERE auto_id=? AND zdalne_id IS NULL", (auto_id,))
        do_wyslania = c.fetchall()

    for wiersz in do_wyslania:
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

        wynik = klient.rpc("dodaj_zdalny_rekord", {
            "p_pojazd_id": wspolny_id, "p_tabela": tabela, "p_dane": dane
        }).execute()
        nowe_zdalne_id = wynik.data

        with db.polacz_baze() as conn:
            conn.execute(f"UPDATE {tabela} SET zdalne_id=? WHERE id=?", (nowe_zdalne_id, wiersz["id"]))
        wyslano += 1

    return wyslano


def _pobierz_tabele(klient, wspolny_id, auto_id, konfig):
    """Ściąga z tabeli zdalne_rekordy wpisy jednej tabeli, których jeszcze nie ma
    lokalnie (po zdalne_id), i wstawia je do lokalnej bazy. Klucze obce (fk) są
    odtwarzane przez odnalezienie lokalnego wiersza o pasującym zdalne_id."""
    tabela = konfig["tabela"]
    kolumny = konfig["kolumny"]
    fk = konfig["fk"]
    pobrano = 0

    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute(f"SELECT zdalne_id FROM {tabela} WHERE auto_id=? AND zdalne_id IS NOT NULL", (auto_id,))
        znane = {r[0] for r in c.fetchall()}

    wynik = klient.table("zdalne_rekordy").select("*").eq("pojazd_id", wspolny_id).eq("tabela", tabela).eq("usuniete", False).execute()

    for rekord in wynik.data:
        if rekord["id"] in znane:
            continue
        dane = rekord["dane"] or {}

        wartosci = {"auto_id": auto_id, "zdalne_id": rekord["id"]}
        wartosci.update({nazwa: dane.get(nazwa) for nazwa in kolumny})

        for pole_fk, tabela_fk in fk.items():
            zdalne_fk = dane.get(f"{pole_fk}_zdalne")
            lokalny_fk = None
            if zdalne_fk:
                with db.polacz_baze() as conn:
                    c = conn.cursor()
                    c.execute(f"SELECT id FROM {tabela_fk} WHERE zdalne_id=?", (zdalne_fk,))
                    w = c.fetchone()
                    lokalny_fk = w[0] if w else None
            wartosci[pole_fk] = lokalny_fk

        nazwy_kolumn = ",".join(wartosci.keys())
        znaki_zapytania = ",".join("?" for _ in wartosci)
        with db.polacz_baze() as conn:
            conn.execute(f"INSERT INTO {tabela} ({nazwy_kolumn}) VALUES ({znaki_zapytania})", tuple(wartosci.values()))
        pobrano += 1

    return pobrano


def synchronizuj_reszte_pojazdu(auto_id):
    """Synchronizuje WSZYSTKIE dane pojazdu oprócz tankowań (patrz KONFIGURACJA_SYNC)
    — najpierw wypychanie wszystkich tabel w kolejności zależności FK, potem
    ściąganie wszystkich tabel w tej samej kolejności. Bez efektu (0, 0), jeśli
    pojazd nie jest współdzielony. Zwraca (wyslano, pobrano)."""
    wspolny_id, _ = czy_udostepniony(auto_id)
    if not wspolny_id:
        return 0, 0

    klient, uid = _upewnij_sesje()

    wyslano = sum(_wypchnij_tabele(klient, wspolny_id, auto_id, konfig) for konfig in KONFIGURACJA_SYNC)
    pobrano = sum(_pobierz_tabele(klient, wspolny_id, auto_id, konfig) for konfig in KONFIGURACJA_SYNC)

    # Wpisy historii mogły zmienić najnowszą datę/przebieg podzespołów
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
        conn.execute("UPDATE tankowania SET zdalne_id=NULL WHERE auto_id=?", (auto_id,))
        for konfig in KONFIGURACJA_SYNC:
            conn.execute(f"UPDATE {konfig['tabela']} SET zdalne_id=NULL WHERE auto_id=?", (auto_id,))