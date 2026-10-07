"""Kolumna `data_iso` (RRRR-MM-DD, migracja 44) — sortowalna kopia `data` (DD.MM.RRRR:
tę widzi użytkownik, synchronizacja i eksport); indeks (auto_id, data_iso). Wartość
zawsze `date.na_iso(data)`. Kto zapisuje `data`, zapisuje też `data_iso`:
- jawny SQL — w tym samym INSERT/UPDATE (audyt `tests/test_data_iso.py`);
- wiersz jako słownik (chmura, kosz) — `uzupelnij_date_iso`;
- kopia całego wiersza — `data_iso` jedzie z `data`.
Bez wyzwalaczy SQLite — z nimi budowa ekranu głównego (~50 połączeń) trwała ponad 2×
dłużej."""

from date import na_iso

from .stale import TABELE_Z_DATA_ISO


def uzupelnij_date_iso(tabela, wiersz) -> None:
    """Dopisuje `data_iso` do słownika kolumn, który zaraz trafi do INSERT albo
    UPDATE. Słownik bez `data` zostaje bez zmian: zapis, który nie rusza daty,
    zostawia w bazie starą, wciąż zgodną wartość."""
    if tabela in TABELE_Z_DATA_ISO and "data" in wiersz:
        wiersz["data_iso"] = na_iso(wiersz["data"])


def przelicz_daty_iso(conn, tabele=TABELE_Z_DATA_ISO) -> int:
    """Wylicza `data_iso` od nowa w całych tabelach — tak migracja 44 wypełnia
    kolumnę wstecz. Pisze tylko wiersze, w których wartość faktycznie się
    zmienia, i zwraca ich liczbę."""
    zmienione = 0
    for tabela in tabele:
        poprawki = []
        for id_, data, obecna in conn.execute(f"SELECT id, data, data_iso FROM {tabela}").fetchall():
            nowa = na_iso(data)
            if nowa != obecna:
                poprawki.append((nowa, id_))
        if poprawki:
            conn.executemany(f"UPDATE {tabela} SET data_iso=? WHERE id=?", poprawki)
            zmienione += len(poprawki)
    return zmienione


def warunek_zakresu_dat(kolumna, od_data=None, do_data=None) -> tuple[str, list]:
    """Dopisek do WHERE: `kolumna` (RRRR-MM-DD) w [od_data, do_data] włącznie, granice
    mogą być None; zwraca (" AND …", parametry). Bez granic — ("", []) i wpis bez daty
    zostaje; z granicą — wypada (NULL)."""
    warunek, parametry = "", []
    if od_data:
        warunek += f" AND {kolumna} >= ?"
        parametry.append(od_data.isoformat()[:10])
    if do_data:
        warunek += f" AND {kolumna} <= ?"
        parametry.append(do_data.isoformat()[:10])
    return warunek, parametry


__all__ = [
    "przelicz_daty_iso",
    "uzupelnij_date_iso",
    "warunek_zakresu_dat",
]
