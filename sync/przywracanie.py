"""Odtworzenie lokalnej bazy z chmury — po reinstalacji albo na nowym telefonie.

To NIE jest synchronizacja: nie ma tu porównywania hashy ani rozstrzygania
konfliktów, bo nie ma z czym porównywać. Chmura jest jedynym źródłem prawdy,
a lokalne dane pojazdu są nadpisywane. Dlatego osobny moduł — żeby nikt nie
wywołał tego przez pomyłkę zamiast zwykłego przebiegu.
"""

import db

from .stale import KONFIGURACJA_SYNC, TABELE_POSREDNIE
from .polaczenie import _upewnij_sesje
from .role import czy_udostepniony
from .pomocnicze import _hash_zawartosci, _zapytanie_tabeli


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


__all__ = [
    "_przywroc_tabele",
    "przywroc_z_chmury",
]
