"""Kolejka wysyłki do chmury, nagrobki usuniętych rekordów i role współdzielenia."""

from datetime import datetime, timedelta

from .stale import MAKS_BACKOFF_MINUT_SYNC
from .polaczenie import polacz_baze
from .ustawienia import pobierz_moje_imie

# ============================ ROLE WSPÓŁDZIELENIA ============================
# Rola opisuje, czym ten pojazd jest DLA MNIE — jest cechą lokalnego wiersza
# w `samochody`, nie cechą pojazdu w chmurze. Ten sam samochód jest
# 'wlasciciel' u siebie i 'podglad' u teścia.
ROLA_WLASCICIEL = "wlasciciel"   # udostępniłem ten pojazd
ROLA_PELNA = "pelna"             # dołączyłem kodem pełnym — prawa jak właściciel
ROLA_WSPOLAUTOR = "wspolautor"   # dopisuję swoje wpisy, cudzych nie ruszam
ROLA_PODGLAD = "podglad"         # tylko czytam; aplikacja nigdy nic nie wysyła

ROLE_Z_PELNYM_DOSTEPEM = (ROLA_WLASCICIEL, ROLA_PELNA)

ETYKIETY_ROL = {
    ROLA_WLASCICIEL: "Właściciel",
    ROLA_PELNA: "Pełny dostęp",
    ROLA_WSPOLAUTOR: "Współautor",
    ROLA_PODGLAD: "Tylko podgląd",
}

OPISY_ROL = {
    ROLA_WLASCICIEL: "Ty udostępniłeś ten pojazd. Możesz wszystko, łącznie z rozłączeniem go z chmury.",
    ROLA_PELNA: "Pełne prawa: dodajesz, edytujesz i kasujesz wszystkie wpisy — także cudze.",
    ROLA_WSPOLAUTOR: "Dopisujesz własne tankowania i wpisy oraz poprawiasz to, co sam dodałeś. Cudzych wpisów nie zmienisz ani nie skasujesz.",
    ROLA_PODGLAD: "Widzisz całą historię pojazdu, ale niczego nie zmieniasz. Nic z tego telefonu nie trafia do chmury.",
}

# Tabele, w których wpis ma podpis autora (kolumna `dodane_przez`). Tylko dla
# nich ma sens pytanie „czyj to wpis” — reszta to słowniki wspólne dla pojazdu
# (podzespoły, tagi, warsztaty, magazyn), gdzie własność pojedynczego wiersza
# nic nie znaczy.
TABELE_Z_AUTOREM = ("tankowania", "wizyty", "historia", "inne_koszty")


def rola_pojazdu(auto_id):
    """Rola zalogowanego telefonu przy tym pojeździe. Pojazd niewspółdzielony
    i pojazd sprzed migracji ról to zawsze 'wlasciciel' — czyli dokładnie te
    prawa, które aplikacja miała, zanim role w ogóle powstały."""
    if not auto_id:
        return ROLA_WLASCICIEL
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT rola_wspoldzielenia FROM samochody WHERE id=?", (auto_id,))
        w = c.fetchone()
    rola = (w[0] or "").strip() if w else ""
    return rola if rola in ETYKIETY_ROL else ROLA_WLASCICIEL


def ustaw_role_pojazdu(auto_id, rola):
    if not auto_id or rola not in ETYKIETY_ROL:
        return
    with polacz_baze() as conn:
        conn.execute("UPDATE samochody SET rola_wspoldzielenia=? WHERE id=?", (rola, auto_id))


def czy_tylko_podglad(auto_id):
    """Czy ten pojazd jest u mnie w trybie „tylko podgląd”. Jedno pytanie, które
    zadaje cały interfejs, zanim pokaże jakikolwiek przycisk zmieniający dane."""
    return rola_pojazdu(auto_id) == ROLA_PODGLAD


def czy_moge_dodawac(auto_id):
    """Nowy wpis wolno dopisać każdemu poza podglądem — także współautorowi,
    bo po to się go zaprasza."""
    return rola_pojazdu(auto_id) != ROLA_PODGLAD


def czy_moge_zmieniac_wpis(auto_id, autor=None):
    """Czy wolno mi edytować/skasować KONKRETNY wpis. `autor` to zawartość
    kolumny `dodane_przez`.

    Współautor rusza wyłącznie to, co sam podpisał. Wpis bez podpisu (sprzed
    wprowadzenia imion albo dodany przez kogoś, kto imienia nie ustawił) jest
    dla współautora cudzy — świadomie, bo alternatywą jest oddanie mu całej
    historii sprzed jego dołączenia."""
    rola = rola_pojazdu(auto_id)
    if rola == ROLA_PODGLAD:
        return False
    if rola != ROLA_WSPOLAUTOR:
        return True
    moje = (pobierz_moje_imie() or "").strip().casefold()
    czyj = (autor or "").strip().casefold()
    return bool(czyj) and czyj == moje


def autor_wpisu(tabela, rekord_id):
    """Zawartość `dodane_przez` pojedynczego wpisu. None, gdy tabela nie ma
    podpisu autora albo rekordu już nie ma — obie sytuacje znaczą to samo:
    nie da się powiedzieć, czyj to wpis."""
    if not rekord_id or tabela not in TABELE_Z_AUTOREM:
        return None
    with polacz_baze() as conn:
        c = conn.cursor()
        try:
            c.execute(f"SELECT dodane_przez FROM {tabela} WHERE id=?", (rekord_id,))
        except Exception:
            return None
        w = c.fetchone()
    return w[0] if w else None


def czy_moge_zmieniac_rekord(auto_id, tabela, autor=None):
    """Uprawnienie do zmiany rekordu, gdy autora już znamy — z rozstrzygnięciem,
    czy w danej tabeli pytanie „czyj to wpis” w ogóle ma sens. Podzespoły, opony,
    magazyn czy zdjęcia karoserii to wspólny inwentarz pojazdu; tam ograniczenie
    współautora nie działa, bo odcięłoby go od rzeczy, które sam zakłada."""
    rola = rola_pojazdu(auto_id)
    if rola == ROLA_PODGLAD:
        return False
    if rola != ROLA_WSPOLAUTOR:
        return True
    if tabela not in TABELE_Z_AUTOREM:
        return True
    return czy_moge_zmieniac_wpis(auto_id, autor)


def czy_moge_edytowac_w_tabeli(auto_id, tabela, rekord_id):
    """To samo pytanie, gdy mamy tylko id rekordu — autora dobija sobie sam."""
    return czy_moge_zmieniac_rekord(auto_id, tabela, autor_wpisu(tabela, rekord_id))


def czy_moge_usuwac_pojazd(auto_id):
    """Rozłączenie pojazdu z chmury i skasowanie go z garażu zostaje przy
    właścicielu i pełnym dostępie."""
    return rola_pojazdu(auto_id) in ROLE_Z_PELNYM_DOSTEPEM


# ---------------------------- KODY ZAPROSZEŃ ----------------------------
def kody_dostepu(auto_id):
    """Trzy kody pojazdu widziane u właściciela: pełny (istniejący od zawsze),
    współautora i podglądu. Braki to None — kody ról powstają dopiero przy
    pierwszym wejściu na ekran Współdzielenia po aktualizacji."""
    if not auto_id:
        return {"pelny": None, "wspolautor": None, "podglad": None}
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT kod_zaproszenia, kod_wspolautora, kod_podgladu FROM samochody WHERE id=?",
            (auto_id,)
        )
        w = c.fetchone()
    if not w:
        return {"pelny": None, "wspolautor": None, "podglad": None}
    return {"pelny": w[0], "wspolautor": w[1], "podglad": w[2]}


def zapisz_kody_dostepu(auto_id, kod_wspolautora=None, kod_podgladu=None):
    if not auto_id:
        return
    with polacz_baze() as conn:
        if kod_wspolautora:
            conn.execute("UPDATE samochody SET kod_wspolautora=? WHERE id=?", (kod_wspolautora, auto_id))
        if kod_podgladu:
            conn.execute("UPDATE samochody SET kod_podgladu=? WHERE id=?", (kod_podgladu, auto_id))


# ------------------------ ZNACZNIK SYNCHRONIZACJI DELTA ------------------------
def znacznik_delty(auto_id):
    """Najwyższy `zaktualizowano`, jaki widzieliśmy przy pobieraniu z chmury.
    None = jeszcze nic nie pobraliśmy, więc następne pobranie musi być pełne."""
    if not auto_id:
        return None
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT znacznik_delty FROM samochody WHERE id=?", (auto_id,))
        w = c.fetchone()
    return (w[0] or None) if w else None


def zapisz_znacznik_delty(auto_id, znacznik):
    if not auto_id:
        return
    with polacz_baze() as conn:
        conn.execute("UPDATE samochody SET znacznik_delty=? WHERE id=?", (znacznik, auto_id))


def wyczysc_znacznik_delty(auto_id):
    """Wymusza pełne pobranie przy najbliższej synchronizacji — używane przez
    „Pobierz wszystko od nowa” i po zmianie roli."""
    zapisz_znacznik_delty(auto_id, None)


# ============================ KOLEJKA WYSYŁKI ============================
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


def pobierz_kolejke_sync(limit=5, tylko_wymagalne=True) -> list[tuple[int, str, int]]:
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


# ============================== NAGROBKI ==============================
# Ile razy próbujemy wypchnąć jedno usunięcie, zanim uznamy je za nie do
# wysłania. Nagrobek odrzucany przez serwer (bo nie mam prawa kasować tego
# rekordu) wracał dotąd przy KAŻDEJ synchronizacji, w nieskończoność.
MAKS_PROB_NAGROBKA = 5


def zarejestruj_nagrobek(tabela, zdalny_id, auto_id=None):
    """Zapamiętuje lokalnie, że wiersz o danym zdalne_id (z tabeli 'tabela') został
    usunięty na tym urządzeniu — sam rekord znika z lokalnej bazy od razu (jak
    dotychczas), ale info o usunięciu trzeba jeszcze wypchnąć na serwer przy
    najbliższej synchronizacji (patrz sync._wypchnij_nagrobki).

    `auto_id` jest opcjonalne: NULL znaczy „nie wiadomo, z którego pojazdu”
    i taki nagrobek leci przy synchronizacji dowolnego auta, dokładnie jak
    przed wprowadzeniem ról."""
    if not zdalny_id:
        return
    with polacz_baze() as conn:
        conn.execute(
            "INSERT INTO zdalne_nagrobki (tabela, zdalny_id, auto_id) VALUES (?,?,?)",
            (tabela, zdalny_id, auto_id)
        )


def usun_nagrobek(zdalny_id):
    """Kasuje nagrobek — wywoływane, gdy usunięcie zostaje cofnięte (Undo), żeby
    NIE propagowało się na serwer."""
    if not zdalny_id:
        return
    with polacz_baze() as conn:
        conn.execute("DELETE FROM zdalne_nagrobki WHERE zdalny_id=?", (zdalny_id,))


def pobierz_nagrobki(auto_id=None) -> list[tuple[int, str, str]]:
    """Nagrobki do wysłania przy synchronizacji danego pojazdu: jego własne plus
    te bez przypisania (starsze, sprzed migracji 40). Pomija te, które serwer
    odrzucił już MAKS_PROB_NAGROBKA razy."""
    with polacz_baze() as conn:
        c = conn.cursor()
        if auto_id:
            c.execute(
                "SELECT id, tabela, zdalny_id FROM zdalne_nagrobki "
                "WHERE (auto_id IS NULL OR auto_id=?) AND COALESCE(proby,0) < ?",
                (auto_id, MAKS_PROB_NAGROBKA)
            )
        else:
            c.execute(
                "SELECT id, tabela, zdalny_id FROM zdalne_nagrobki WHERE COALESCE(proby,0) < ?",
                (MAKS_PROB_NAGROBKA,)
            )
        return [(r[0], r[1], r[2]) for r in c.fetchall()]


def usun_nagrobek_po_id(nagrobek_id):
    with polacz_baze() as conn:
        conn.execute("DELETE FROM zdalne_nagrobki WHERE id=?", (nagrobek_id,))


def zwieksz_proby_nagrobka(nagrobek_id):
    """Nieudana próba wysłania. Po MAKS_PROB_NAGROBKA nagrobek przestaje być
    brany pod uwagę — zostaje w bazie jako ślad, ale nie blokuje już każdej
    kolejnej synchronizacji."""
    with polacz_baze() as conn:
        conn.execute(
            "UPDATE zdalne_nagrobki SET proby=COALESCE(proby,0)+1 WHERE id=?",
            (nagrobek_id,)
        )


__all__ = [
    "ETYKIETY_ROL",
    "MAKS_PROB_NAGROBKA",
    "OPISY_ROL",
    "ROLA_PELNA",
    "ROLA_PODGLAD",
    "ROLA_WLASCICIEL",
    "ROLA_WSPOLAUTOR",
    "ROLE_Z_PELNYM_DOSTEPEM",
    "TABELE_Z_AUTOREM",
    "autor_wpisu",
    "czy_auto_oczekuje_synchronizacji",
    "czy_moge_dodawac",
    "czy_moge_edytowac_w_tabeli",
    "czy_moge_zmieniac_rekord",
    "czy_moge_usuwac_pojazd",
    "czy_moge_zmieniac_wpis",
    "czy_tylko_podglad",
    "kody_dostepu",
    "liczba_oczekujacych_synchronizacji",
    "opis_oczekujacej_synchronizacji",
    "pobierz_kolejke_sync",
    "pobierz_nagrobki",
    "rola_pojazdu",
    "ustaw_role_pojazdu",
    "usun_nagrobek",
    "usun_nagrobek_po_id",
    "usun_z_kolejki_sync",
    "wyczysc_znacznik_delty",
    "zakolejkuj_synchronizacje",
    "zapisz_kody_dostepu",
    "zapisz_znacznik_delty",
    "zarejestruj_nagrobek",
    "znacznik_delty",
    "zwieksz_proby_nagrobka",
]
