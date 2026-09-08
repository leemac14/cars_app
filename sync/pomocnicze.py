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
    """Odcisk treści rekordu. Klucze zaczynające się od podkreślnika są POMIJANE:
    to pola dokładane przez serwer (dziś `_autor_uid` — identyfikator autora
    stemplowany przez wyzwalacz ról), których aplikacja nie zna i nie wysyła.
    Bez tego wyłączenia każdy rekord po stronie serwera miałby inny hash niż
    ten sam rekord policzony lokalnie i KAŻDA zmiana zgłaszałaby się jako
    konflikt edycji z dwóch urządzeń."""
    istotne = {k: v for k, v in (dane or {}).items() if not str(k).startswith("_")}
    kanoniczny = json.dumps(istotne, sort_keys=True, default=str, ensure_ascii=True)
    return hashlib.sha256(kanoniczny.encode("utf-8")).hexdigest()


def _paczki(elementy, rozmiar=100):
    """PostgREST przekazuje filtr `in` w adresie URL, więc lista kilkuset
    identyfikatorów potrafi przekroczyć limit długości. Dzielimy na porcje."""
    elementy = list(elementy)
    for i in range(0, len(elementy), rozmiar):
        yield elementy[i:i + rozmiar]


__all__ = [
    "_hash_zawartosci",
    "_paczki",
    "_zapytanie_tabeli",
]
