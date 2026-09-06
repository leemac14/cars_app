"""Kolejka wysyłki do chmury i nagrobki usuniętych rekordów."""

from datetime import datetime, timedelta

from .stale import MAKS_BACKOFF_MINUT_SYNC
from .polaczenie import polacz_baze


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


__all__ = [
    "czy_auto_oczekuje_synchronizacji",
    "liczba_oczekujacych_synchronizacji",
    "opis_oczekujacej_synchronizacji",
    "pobierz_kolejke_sync",
    "usun_nagrobek",
    "usun_z_kolejki_sync",
    "zakolejkuj_synchronizacje",
    "zarejestruj_nagrobek",
]
