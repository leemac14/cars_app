"""Jedno miejsce, w którym otwiera się połączenie z bazą — i przez to jedno
miejsce, które wie, że dane się zmieniły (patrz db/pamiec.py)."""

import sqlite3
from contextlib import contextmanager

from .stale import BAZA_DANYCH
from .pamiec import zanotuj_zmiane_danych


@contextmanager
def polacz_baze(zmienia_dane=True):
    """Połączenie zatwierdzane przy wyjściu z bloku, wycofywane przy wyjątku.

    Zapis, który zmienił choć jeden wiersz, podbija znacznik zmian danych, więc
    policzone wcześniej metryki (kokpit, nagłówek, odznaki) same wiedzą, że są
    nieaktualne. `zmienia_dane=False` mówi: ten zapis to wyłącznie pamięć
    interfejsu — „ostatnio używane ekrany”, pozycja startowa — i nie rusza
    żadnej liczby na ekranie. Router zapisuje je przy KAŻDYM przejściu, więc
    bez tego wyjątku pamięć metryk czyściłaby się przed każdym powrotem na
    kokpit."""
    conn = sqlite3.connect(BAZA_DANYCH)
    conn.execute('PRAGMA foreign_keys = ON;')
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        # `total_changes` liczy wiersze zmienione przez INSERT, UPDATE i DELETE
        # tego połączenia — UPDATE, który nic nie trafił, nie unieważnia
        # niczego. Wycofany zapis też podbija znacznik: pamięć policzy się raz
        # więcej, niż trzeba, ale nigdy nie zostanie przy starych liczbach.
        zmienione = zmienia_dane and conn.total_changes > 0
        conn.close()
        # Podbicie PO zatwierdzeniu, nigdy przed: kto zobaczy nowy znacznik,
        # musi już widzieć nowe dane — inaczej zapamiętałby stare liczby pod
        # nowym kluczem i trzymał je aż do następnego zapisu.
        if zmienione:
            zanotuj_zmiane_danych()


__all__ = [
    "polacz_baze",
]
