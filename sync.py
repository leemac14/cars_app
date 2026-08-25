"""
Współdzielenie pojazdu — synchronizacja z Supabase.

Reszta aplikacji działa dokładnie jak dotychczas: w 100% lokalnie i offline.
Ten moduł włącza się TYLKO dla pojazdu świadomie oznaczonego jako współdzielony
(samochody.wspolny_pojazd_id IS NOT NULL). Synchronizowane są wyłącznie
TANKOWANIA — historia, magazyn, wizyty, karoseria i załączniki zostają lokalne.
"""
import uuid as uuid_lib
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
    """Loguje anonimowo przy pierwszym użyciu (bez maila/hasła). Sesję trzyma
    w tabeli 'ustawienia', żeby tożsamość — a więc dostęp do współdzielonych
    pojazdów — przetrwała restart aplikacji."""
    klient = _pobierz_klient()

    token = db.pobierz_ustawienie("supabase_access_token")
    refresh = db.pobierz_ustawienie("supabase_refresh_token")
    if token and refresh:
        try:
            klient.auth.set_session(access_token=token, refresh_token=refresh)
            return klient
        except Exception:
            pass  # sesja wygasła/nieprawidłowa — logujemy się od nowa poniżej

    wynik = klient.auth.sign_in_anonymously()
    sesja = wynik.session
    db.zapisz_ustawienie("supabase_access_token", sesja.access_token)
    db.zapisz_ustawienie("supabase_refresh_token", sesja.refresh_token)
    return klient


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
    """Oznacza LOKALNY pojazd jako współdzielony: tworzy wiersz w Supabase
    i generuje kod zaproszenia. Zwraca kod (str)."""
    klient = _upewnij_sesje()
    kod = uuid_lib.uuid4().hex[:6].upper()

    wynik = klient.table("udostepnione_pojazdy").insert({
        "nazwa": nazwa, "kod_zaproszenia": kod
    }).execute()
    nowy_id = wynik.data[0]["id"]

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
    klient = _upewnij_sesje()
    wynik = klient.rpc("dolacz_do_pojazdu", {"p_kod": kod.strip().upper()}).execute()
    if not wynik.data:
        raise ValueError("Nieprawidłowy kod zaproszenia.")
    wspolny_id = wynik.data[0]["pojazd_id"]
    nazwa = wynik.data[0]["nazwa"]

    with db.polacz_baze() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO samochody (nazwa, wspolny_pojazd_id, kod_zaproszenia) VALUES (?,?,?)",
            (nazwa, wspolny_id, kod.strip().upper())
        )
        nowy_auto_id = cur.lastrowid

    synchronizuj_tankowania(nowy_auto_id)
    return nowy_auto_id, nazwa


def synchronizuj_tankowania(auto_id):
    """Wypycha lokalne, jeszcze niewysłane tankowania, po czym ściąga te
    dodane przez współlaczników. Zwraca (wyslano, pobrano). Bez efektu
    (0, 0), jeśli pojazd nie jest współdzielony — bezpieczne do wywołania
    zawsze, nawet dla lokalnych aut."""
    wspolny_id, _ = czy_udostepniony(auto_id)
    if not wspolny_id:
        return 0, 0

    klient = _upewnij_sesje()
    wyslano = 0

    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, data, przebieg, dystans, litry, kwota, do_pelna, stacja, tagi "
            "FROM tankowania WHERE auto_id=? AND zdalne_id IS NULL", (auto_id,)
        )
        do_wyslania = c.fetchall()

    for lokalny_id, data, przebieg, dystans, litry, kwota, do_pelna, stacja, tagi in do_wyslania:
        wynik = klient.table("zdalne_tankowania").insert({
            "pojazd_id": wspolny_id, "data": data, "przebieg": przebieg,
            "dystans": dystans, "litry": litry, "kwota": kwota,
            "do_pelna": bool(do_pelna), "stacja": stacja, "tagi": tagi,
        }).execute()
        nowe_zdalne_id = wynik.data[0]["id"]
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