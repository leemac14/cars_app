"""Jedno miejsce, w którym otwiera się połączenie z bazą."""

import sqlite3
from contextlib import contextmanager

from .stale import BAZA_DANYCH


@contextmanager
def polacz_baze():
    conn = sqlite3.connect(BAZA_DANYCH)
    conn.execute('PRAGMA foreign_keys = ON;')
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


__all__ = [
    "polacz_baze",
]
