"""Pamięć wyników liczonych z bazy, ważna do najbliższej zmiany danych. Znacznik zmian
rośnie po każdym zatwierdzonym zapisie zmieniającym wiersz — podbija go `polacz_baze`;
wprost woła go tylko kod omijający `polacz_baze` (np. `init_db()` po wczytaniu kopii).
Jeden znacznik na całą bazę.

`z_pamieci(nazwa, auto_id, licz)` trzyma wynik ze znacznikiem i DNIEM; inny znacznik
albo dzień czyści całą pamięć. Tylko w pamięci procesu — nic nie trafia do bazy ani
kopii."""

import copy
import threading
from datetime import date

_znacznik = 0
_pamiec = {}
# (znacznik, dzień), dla którego policzono to, co leży w _pamiec.
_stan_pamieci = None
# Formularze i synchronizacja zapisują z wątków obsługi zdarzeń, a ekran może
# się w tym czasie budować na innym — podbicie znacznika i podmiana pamięci
# muszą być niepodzielne.
_zamek = threading.Lock()


def _dzien():
    """Osobna funkcja, żeby test mógł przestawić kalendarz bez ruszania zegara."""
    return date.today()


def znacznik_zmian_danych() -> int:
    """Numer ostatniej zmiany danych — rośnie po każdym zapisie (patrz wyżej)."""
    return _znacznik


def zanotuj_zmiane_danych():
    """Unieważnia wszystko, co policzono z bazy przed tą chwilą."""
    global _znacznik
    with _zamek:
        _znacznik += 1


def z_pamieci(nazwa, auto_id, licz):
    """Wynik `licz()` pod (nazwa, auto_id) do zmiany danych albo daty. Wołający dostaje
    KOPIĘ; wynik liczony w trakcie cudzego zapisu NIE trafia do pamięci."""
    global _stan_pamieci
    stan = (_znacznik, _dzien())
    klucz = (nazwa, auto_id)
    with _zamek:
        if _stan_pamieci == stan and klucz in _pamiec:
            return copy.deepcopy(_pamiec[klucz])

    wynik = licz()

    with _zamek:
        if (_znacznik, _dzien()) == stan:
            if _stan_pamieci != stan:
                _pamiec.clear()
                _stan_pamieci = stan
            _pamiec[klucz] = copy.deepcopy(wynik)
    return wynik


def w_pamieci(nazwa, auto_id) -> bool:
    """Czy wynik leży w pamięci i jest nadal ważny — bez liczenia go."""
    with _zamek:
        return _stan_pamieci == (_znacznik, _dzien()) and (nazwa, auto_id) in _pamiec


__all__ = [
    "w_pamieci",
    "z_pamieci",
    "zanotuj_zmiane_danych",
    "znacznik_zmian_danych",
]
