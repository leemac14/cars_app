"""Ściągnięcie zmian z chmury i wpisanie ich lokalnie — kierunek „stamtąd tu".

`_zastosuj_rekord` jest lustrzanym odbiciem `_wypchnij_tabele` i ma ten sam
ciężar gatunkowy: to on decyduje, czy przyjęta wersja nadpisze lokalną.
Osobny moduł od wysyłania, bo obie strony wolno czytać niezależnie —
przy błędzie synchronizacji pierwsze pytanie brzmi „w którą stronę".
"""

import db
import sqlite3

from .stale import KOLUMNA_ZNACZNIKA, KOLUMNY_POJAZDU, TABELE_POSREDNIE
from .delta import _delta_wlaczona, _wylacz_delte
from .pomocnicze import _hash_zawartosci, _paczki, _zapytanie_tabeli


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


__all__ = [
    "_pobierz_rekordy",
    "_pobierz_tabele",
    "_synchronizuj_info_pojazdu",
    "_zastosuj_rekord",
]
