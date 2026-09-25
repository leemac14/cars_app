"""Pakiety `db`, `utils` i `sync` scalają swoje moduły gwiazdkowym importem —
i obie pułapki tego zapisu milczą.

1. Dwa moduły wystawiające tę samą nazwę: wygrywa ten importowany PÓŹNIEJ,
   bez ostrzeżenia. Tak `db._na_liczbe` (parser z `pomocnicze`, rozumiejący
   „45,20 zł”, nan i inf) był po cichu podmieniany węższą funkcją
   z `wyszukiwanie` o tej samej nazwie.
2. Nazwa przypisywana przez `global` i wystawiona w `__all__`: pakiet dostaje
   KOPIĘ wiązania z chwili importu. Tak `db.WERSJA_SCHEMATU` zostawało na
   zawsze None, choć `init_db()` ją ustawiało.

Test dla `sync` ma własny, szerszy plik (test_sync_pakiet.py); tutaj te dwie
reguły sprawdzamy dla wszystkich trzech pakietów naraz.
"""

import ast
import pathlib

import pytest

import db
import sync
import utils


PAKIETY = [db, utils, sync]


def _moduly(pakiet):
    katalog = pathlib.Path(pakiet.__file__).resolve().parent
    for plik in sorted(katalog.glob("*.py")):
        if plik.stem != "__init__":
            yield plik, getattr(pakiet, plik.stem)


@pytest.mark.parametrize("pakiet", PAKIETY, ids=lambda p: p.__name__)
def test_zadna_nazwa_nie_jest_wystawiana_dwa_razy(pakiet):
    wlasciciele = {}
    for _plik, modul in _moduly(pakiet):
        for nazwa in getattr(modul, "__all__", []):
            wlasciciele.setdefault(nazwa, []).append(modul.__name__)
    podwojne = {n: m for n, m in wlasciciele.items() if len(m) > 1}
    assert podwojne == {}, (
        "ta sama nazwa w __all__ kilku modułów — w pakiecie zostaje tylko "
        f"ostatnia z nich: {podwojne}"
    )


@pytest.mark.parametrize("pakiet", PAKIETY, ids=lambda p: p.__name__)
def test_nazwa_przypisywana_przez_global_nie_jest_wystawiana(pakiet):
    zle = []
    for plik, modul in _moduly(pakiet):
        drzewo = ast.parse(plik.read_text(encoding="utf-8"))
        globalne = {n for w in ast.walk(drzewo) if isinstance(w, ast.Global) for n in w.names}
        zle += [f"{modul.__name__}.{n}" for n in globalne if n in getattr(modul, "__all__", [])]
    assert zle == [], (
        "nazwa przypisywana przez `global` jest w __all__, więc pakiet trzyma "
        f"jej zamrożoną kopię: {zle}"
    )
