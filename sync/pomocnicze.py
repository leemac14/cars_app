"""Trzy narzędzia, których używa i wysyłanie, i pobieranie, i przywracanie.

`_zapytanie_tabeli` jest tu najważniejsze: zamienia opis tabeli na SQL razem
z JOIN-em dla tabel pośrednich. Wcześniej ten sam if/elif był powtórzony
w pięciu miejscach pliku.
"""

import hashlib
import json

from .stale import TABELE_POSREDNIE


def _zapytanie_tabeli(tabela, pola="*", warunek_dodatkowy=None):
    """Buduje SELECT ograniczony do jednego pojazdu — dla tabel z auto_id wprost,
    dla pośrednich przez zdefiniowany JOIN. `pola` podaje się bez aliasu
    (np. "id, zdalne_id"); alias jest doklejany automatycznie."""
    opis = TABELE_POSREDNIE.get(tabela)
    if not opis:
        zapytanie = f"SELECT {pola} FROM {tabela} WHERE auto_id=?"
        if warunek_dodatkowy:
            zapytanie += f" AND {warunek_dodatkowy}"
        return zapytanie

    alias = opis["alias"]
    if pola.strip() == "*":
        wybor = f"{alias}.*"
    else:
        wybor = ", ".join(f"{alias}.{p.strip()}" for p in pola.split(","))
    zapytanie = f"SELECT {wybor} FROM {tabela} {alias} {opis['join']} WHERE {opis['warunek']}"
    if warunek_dodatkowy:
        zapytanie += f" AND {alias}.{warunek_dodatkowy}"
    return zapytanie


def _hash_zawartosci(dane: dict) -> str:
    """Odcisk treści rekordu. Klucze z podkreślnikiem POMIJANE — to pola serwera
    (`_autor_uid` z wyzwalacza ról); inaczej każdy rekord wyglądałby na konflikt."""
    istotne = {k: v for k, v in (dane or {}).items() if not str(k).startswith("_")}
    kanoniczny = json.dumps(istotne, sort_keys=True, default=str, ensure_ascii=True)
    return hashlib.sha256(kanoniczny.encode("utf-8")).hexdigest()


def _hash_rekordu(dane: dict, konfig=None) -> str:
    """Odcisk do porównań synchronizacji: bez kolumn `pochodne` konfiguracji — liczy je każdy
    telefon z innych danych (stan magazynu ze stanu wyjściowego i zużycia), więc ich zmiana nie
    jest zmianą rekordu."""
    pochodne = (konfig or {}).get("pochodne") or {}
    return _hash_zawartosci({k: v for k, v in (dane or {}).items() if k not in pochodne})


def _uzupelnij_zrodla_pochodnych(dane_zdalne: dict, dane_lokalne: dict, pochodne) -> dict:
    """Rekord ze starszej wersji nie ma kolumny, z której liczy się pochodna (stanu
    wyjściowego) — do porównania z odciskiem bierzemy tę lokalną: tylko jej brak nie znaczy,
    że ktoś zmienił rekord."""
    uzupelnione = dict(dane_zdalne or {})
    for zrodlo in (pochodne or {}).values():
        if uzupelnione.get(zrodlo) is None:
            uzupelnione[zrodlo] = (dane_lokalne or {}).get(zrodlo)
    return uzupelnione


def _rozne_pochodne(dane_lokalne: dict, dane_zdalne: dict, pochodne) -> bool:
    """Czy pochodne (liczby) różnią się między telefonem a chmurą — z tolerancją na zapis 2 i 2.0."""
    for kolumna in pochodne or {}:
        lokalna, zdalna = (dane_lokalne or {}).get(kolumna), (dane_zdalne or {}).get(kolumna)
        if isinstance(lokalna, (int, float)) and isinstance(zdalna, (int, float)):
            if abs(float(lokalna) - float(zdalna)) > 1e-9:
                return True
        elif lokalna != zdalna:
            return True
    return False


def _paczki(elementy, rozmiar=100):
    """PostgREST przekazuje filtr `in` w adresie URL, więc lista kilkuset
    identyfikatorów potrafi przekroczyć limit długości. Dzielimy na porcje."""
    elementy = list(elementy)
    for i in range(0, len(elementy), rozmiar):
        yield elementy[i:i + rozmiar]


__all__ = [
    "_hash_rekordu",
    "_hash_zawartosci",
    "_paczki",
    "_rozne_pochodne",
    "_uzupelnij_zrodla_pochodnych",
    "_zapytanie_tabeli",
]
