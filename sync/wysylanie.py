"""Wypchnięcie jednej tabeli do chmury — kierunek „stąd tam".

Najgęstsza funkcja w całym pakiecie i jedyna, która rozstrzyga konflikt:
gdy rekord zmienił się po obu stronach, ktoś musi przegrać. Dlatego wygrany
jest wybierany jawnie, a przegrany trafia na listę konfliktów zamiast zniknąć.
"""

import db
import sqlite3
from itertools import combinations

from .role import _wolno_wypchnac_zmiane
from .konflikty import _zarejestruj_konflikt, _zarejestruj_odrzucenie
from .pomocnicze import (
    _hash_rekordu, _hash_zawartosci, _paczki, _rozne_pochodne, _uzupelnij_zrodla_pochodnych, _zapytanie_tabeli,
)


def _zgodny_z_zapamietanym(dane, zapamietany, dopisane=(), pochodne=()):
    """Czy treść rekordu to wciąż to, co zapamiętał `zdalny_hash`. Pusta kolumna z
    `dopisane` nie zmienia rekordu (hash sprzed dopisania był bez niej). Hash bywa
    „pomiędzy” wersjami, więc próbujemy bez KAŻDEGO zestawu pustych dopisanych kolumn;
    fałszywej zgodności to nie daje. Przy `pochodne` odcisk jest bez nich (`_hash_rekordu`),
    a odcisk sprzed ich wydzielenia — z nimi; pasuje każdy."""
    dane = dane or {}
    warianty = [dane]
    if pochodne:
        warianty.insert(0, {k: v for k, v in dane.items() if k not in pochodne})
    for wariant in warianty:
        if _hash_zawartosci(wariant) == zapamietany:
            return True
        puste = [k for k in wariant if k in dopisane and wariant[k] is None]
        for ile in range(len(puste), 0, -1):
            for pominiete in combinations(puste, ile):
                bez_pustych = {k: v for k, v in wariant.items() if k not in pominiete}
                if _hash_zawartosci(bez_pustych) == zapamietany:
                    return True
    return False


def _zdalny_bez_zmian(dane_zdalne, dane_lokalne, zapamietany, dopisane, pochodne):
    """Czy rekord w chmurze to wciąż ten z ostatniej synchronizacji. Rekord ze starszej wersji
    nie niesie źródła pochodnej (stanu wyjściowego) — porównujemy go także z lokalnym."""
    if _zgodny_z_zapamietanym(dane_zdalne, zapamietany, dopisane, pochodne):
        return True
    return bool(pochodne) and _zgodny_z_zapamietanym(
        _uzupelnij_zrodla_pochodnych(dane_zdalne, dane_lokalne, pochodne), zapamietany, dopisane, pochodne)


def _wypchnij_tabele(klient, wspolny_id, auto_id, konfig, rola=None):
    """Wysyła nowe i zmienione wiersze jednej tabeli.

    Zwraca (ile_wyslano, [zdalne_id do cofnięcia]) — druga lista to zmiany
    odrzucone przez rolę współautora, które trzeba przywrócić z chmury."""
    tabela = konfig["tabela"]
    kolumny = konfig["kolumny"]
    fk = konfig["fk"]
    dopisane = frozenset(konfig.get("dopisane") or ())
    pochodne = konfig.get("pochodne") or {}
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
        nowy_hash = _hash_rekordu(dane, konfig)
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
    bez_zmian = []  # tylko przy `pochodne`: może trzeba wysłać samą pochodną
    for wiersz in istniejace:
        dane = zbuduj_dane(wiersz)
        nowy_hash = _hash_rekordu(dane, konfig)
        if _zgodny_z_zapamietanym(dane, wiersz["zdalny_hash"], dopisane, pochodne):
            if pochodne:
                bez_zmian.append((wiersz, dane))
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

    if not zmienione and not bez_zmian:
        return wyslano, do_cofniecia

    zdalne_teraz = {}
    identyfikatory = [w["zdalne_id"] for w, _, _ in zmienione] + [w["zdalne_id"] for w, _ in bez_zmian]
    for paczka in _paczki(identyfikatory):
        wynik_zdalne = klient.table("zdalne_rekordy").select("id,dane").in_("id", paczka).execute()
        for r in wynik_zdalne.data or []:
            zdalne_teraz[r["id"]] = r.get("dane") or {}

    for wiersz, dane, nowy_hash in zmienione:
        dane_zdalne = zdalne_teraz.get(wiersz["zdalne_id"])
        if dane_zdalne is not None:
            if not _zdalny_bez_zmian(dane_zdalne, dane, wiersz["zdalny_hash"], dopisane, pochodne):
                # Zdalna wersja zmieniła się niezależnie od naszej ostatniej
                # synchronizacji — ktoś edytował ten sam rekord na innym
                # urządzeniu offline. Zaraz go nadpiszemy, więc zapamiętujemy
                # tamtą treść, żeby dało się ją jeszcze odzyskać.
                _zarejestruj_konflikt(tabela, dane=dane, zdalne_id=wiersz["zdalne_id"], dane_zdalne=dane_zdalne)

        klient.rpc("aktualizuj_zdalny_rekord", {"p_id": wiersz["zdalne_id"], "p_dane": dane}).execute()
        with db.polacz_baze() as conn:
            conn.execute(f"UPDATE {tabela} SET zdalny_hash=? WHERE id=?", (nowy_hash, wiersz["id"]))
        wyslano += 1

    # Same pochodne (stan magazynu po zużyciu): starsza wersja czyta je wprost z chmury. Bez
    # konfliktu i tylko wtedy, gdy reszta rekordu w chmurze jest jak przy ostatniej
    # synchronizacji — zmianę drugiej osoby najpierw przyniesie pobranie.
    for wiersz, dane in bez_zmian:
        dane_zdalne = zdalne_teraz.get(wiersz["zdalne_id"])
        if dane_zdalne is None or not _rozne_pochodne(dane, dane_zdalne, pochodne):
            continue
        if not _zdalny_bez_zmian(dane_zdalne, dane, wiersz["zdalny_hash"], dopisane, pochodne):
            continue
        if not _wolno_wypchnac_zmiane(auto_id, rola, tabela, wiersz):
            continue
        klient.rpc("aktualizuj_zdalny_rekord", {"p_id": wiersz["zdalne_id"], "p_dane": dane}).execute()
        with db.polacz_baze() as conn:
            conn.execute(f"UPDATE {tabela} SET zdalny_hash=? WHERE id=?", (_hash_rekordu(dane, konfig), wiersz["id"]))

    return wyslano, do_cofniecia


__all__ = [
    "_wypchnij_tabele",
    "_zdalny_bez_zmian",
    "_zgodny_z_zapamietanym",
]
