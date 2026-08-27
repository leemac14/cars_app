"""
Współdzielenie pojazdu — synchronizacja z Supabase.

Reszta aplikacji działa dokładnie jak dotychczas: w 100% lokalnie i offline.
Ten moduł włącza się TYLKO dla pojazdu świadomie oznaczonego jako współdzielony.
Synchronizowane są wszystkie wpisy za pomocą uniwersalnej tabeli zdalne_rekordy.
"""

import uuid as uuid_lib
import sqlite3
import json
import hashlib
import db

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
            pass

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

def utworz_udostepniony_pojazd(auto_id, nazwa):
    klient, uid = _upewnij_sesje()
    kod = uuid_lib.uuid4().hex[:6].upper()

    wynik = klient.rpc("utworz_udostepniony_pojazd", {"p_nazwa": nazwa, "p_kod": kod}).execute()
    nowy_id = wynik.data 

    with db.polacz_baze() as conn:
        conn.execute(
            "UPDATE samochody SET wspolny_pojazd_id=?, kod_zaproszenia=? WHERE id=?",
            (nowy_id, kod, auto_id)
        )

    synchronizuj_wszystko(auto_id)
    return kod

def dolacz_po_kodzie(kod):
    klient, uid = _upewnij_sesje()
    wynik = klient.rpc("dolacz_do_pojazdu", {"p_kod": kod.strip().upper()}).execute()
    if not wynik.data:
        raise ValueError("Nieprawidłowy kod zaproszenia.")
        
    wspolny_id = wynik.data[0]["pojazd_id"]
    nazwa = wynik.data[0]["nazwa"]

    with db.polacz_baze() as conn:
        cur = conn.cursor()
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


# ==================== UNIWERSALNA SYNCHRONIZACJA ====================
KOLUMNY_POJAZDU = [
    "nazwa", "marka", "model", "generacja", "nr_rej", "vin", "rok_produkcji",
    "oc_data", "przeglad_data", "pojemnosc_silnika", "moc_silnika", "typ_paliwa",
    "skrzynia_biegow", "notatki", "wycieraczki_przod", "wycieraczki_tyl",
    "cisnienie_przod", "cisnienie_tyl", "olej_typ", "olej_pojemnosc", "akumulator",
    "zarowki_mijania", "zarowki_drogowe", "ac_data", "assistance_data",
    "gasnica_data", "apteczka_data",
]

KONFIGURACJA_SYNC = [
    {"tabela": "tagi", "kolumny": ["nazwa", "kolor"], "fk": {}},
    {"tabela": "tankowania", "kolumny": ["data", "przebieg", "dystans", "litry", "kwota", "do_pelna", "stacja", "tagi"], "fk": {}},
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
    {"tabela": "tankowania", "kolumny": ["data", "przebieg", "dystans", "litry", "kwota", "do_pelna", "stacja", "tagi", "dodane_przez"], "fk": {}},
    {"tabela": "zadania", "kolumny": ["nazwa", "interwal_km", "interwal_miesiace", "dotyczy_opon"], "fk": {}},
    {"tabela": "wizyty", "kolumny": ["data", "przebieg", "wykonawca", "koszt_calkowity", "notatki", "tagi", "dodane_przez"], "fk": {}},
    {"tabela": "historia", "kolumny": ["data", "przebieg", "kategoria", "cena", "wykonawca", "dodane_przez"], "fk": {"zadanie_id": "zadania", "wizyta_id": "wizyty"}},
    {"tabela": "magazyn_czesci", "kolumny": ["nazwa", "kategoria", "ilosc", "jednostka", "cena", "data_zakupu", "notatki", "prog_ostrzezenia"], "fk": {}},
    {"tabela": "zestawy_opon", "kolumny": ["sezon", "rozmiar", "marka_model", "glebokosc_bieznika", "data_pomiaru", "numer_dot", "ilosc", "zamontowane", "data_zakupu", "przebieg_zakupu", "cena", "notatki", "os_montazu"], "fk": {}},
    {"tabela": "inne_koszty", "kolumny": ["data", "kategoria", "nazwa", "kwota", "tagi", "dodane_przez"], "fk": {}},
]

def _hash_zawartosci(dane: dict) -> str:
    kanoniczny = json.dumps(dane, sort_keys=True, default=str, ensure_ascii=True)
    return hashlib.sha256(kanoniczny.encode("utf-8")).hexdigest()

def _wypchnij_nagrobki(klient):
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT id, tabela, zdalny_id FROM zdalne_nagrobki")
        nagrobki = c.fetchall()

    for nagrobek_id, tabela, zdalny_id in nagrobki:
        try:
            klient.rpc("usun_zdalny_rekord", {"p_id": zdalny_id}).execute()
            with db.polacz_baze() as conn:
                conn.execute("DELETE FROM zdalne_nagrobki WHERE id=?", (nagrobek_id,))
        except Exception:
            pass

def _wypchnij_tabele(klient, wspolny_id, auto_id, konfig):
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
                        continue
            # -------------------------------------------------------------------------
            
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

def _synchronizuj_info_pojazdu(klient, wspolny_id, auto_id):
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

    if hash_teraz != hash_ostatnio_zsynchronizowany:
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

    if tabela == "historia":
        zapytanie_znane = (
            "SELECT h.zdalne_id FROM historia h JOIN zadania z ON h.zadanie_id = z.id "
            "WHERE z.auto_id=? AND h.zdalne_id IS NOT NULL"
        )
    else:
        zapytanie_znane = f"SELECT zdalne_id FROM {tabela} WHERE auto_id=? AND zdalne_id IS NOT NULL"

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

        if tabela != "historia":
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

    db.przelicz_wszystkie_zadania(auto_id)
    return przywrocono

def synchronizuj_wszystko(auto_id):
    wspolny_id, _ = czy_udostepniony(auto_id)
    if not wspolny_id:
        return 0, 0

    # --- ZABEZPIECZENIE: Reset starszych tankowań wgranych starą metodą ---
    # Wymuszamy, by stare tankowania (mające ID ze starej tabeli Supabase) 
    # zostały uznane za nowe i wypchnięte do nowej tabeli zdalne_rekordy.
    if db.pobierz_ustawienie("migracja_tankowan_v4") != "1":
        with db.polacz_baze() as conn:
            conn.execute("UPDATE tankowania SET zdalne_id = NULL, zdalny_hash = NULL")
        db.zapisz_ustawienie("migracja_tankowan_v4", "1")
    # ----------------------------------------------------------------------

    klient, uid = _upewnij_sesje()
    _wypchnij_nagrobki(klient)

    wyslano = 0
    pobrano = 0

    w_info, p_info = _synchronizuj_info_pojazdu(klient, wspolny_id, auto_id)
    wyslano += w_info
    pobrano += p_info

    wyslano += sum(_wypchnij_tabele(klient, wspolny_id, auto_id, konfig) for konfig in KONFIGURACJA_SYNC)
    pobrano += sum(_pobierz_tabele(klient, wspolny_id, auto_id, konfig) for konfig in KONFIGURACJA_SYNC)

    db.przelicz_wszystkie_zadania(auto_id)

    return wyslano, pobrano

def odlacz_wspoldzielenie(auto_id):
    with db.polacz_baze() as conn:
        conn.execute(
            "UPDATE samochody SET wspolny_pojazd_id=NULL, kod_zaproszenia=NULL, "
            "info_zdalne_id=NULL, zdalny_hash_info=NULL WHERE id=?",
            (auto_id,)
        )
        for konfig in KONFIGURACJA_SYNC:
            tabela = konfig["tabela"]
            if tabela == "historia":
                conn.execute(
                    "UPDATE historia SET zdalne_id=NULL, zdalny_hash=NULL "
                    "WHERE zadanie_id IN (SELECT id FROM zadania WHERE auto_id=?)",
                    (auto_id,)
                )
            else:
                conn.execute(f"UPDATE {tabela} SET zdalne_id=NULL, zdalny_hash=NULL WHERE auto_id=?", (auto_id,))