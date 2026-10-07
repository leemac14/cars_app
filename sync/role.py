"""Rola uczestnika: kto może wypchnąć zmianę. Interfejs to wygoda,
`_wolno_wypchnac_zmiane` druga warstwa, wyzwalacz w Supabase
(supabase/role_wspoldzielenia.sql) trzecia."""

import db
import uuid as uuid_lib


def czy_udostepniony(auto_id):
    if not auto_id:
        return None, None
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT wspolny_pojazd_id, kod_zaproszenia FROM samochody WHERE id=?", (auto_id,))
        w = c.fetchone()
    return (w[0], w[1]) if w and w[0] else (None, None)


def _nowy_kod():
    return uuid_lib.uuid4().hex[:6].upper()


def _wolno_wypchnac_zmiane(auto_id, rola, tabela, wiersz):
    """Czy wolno wysłać ZMIANĘ istniejącego rekordu. Podgląd — nic; współautor — nie
    cudze, ale tylko w tabelach z `dodane_przez` (wspólne słowniki pojazdu są wolne)."""
    if rola == db.ROLA_PODGLAD:
        return False
    if rola != db.ROLA_WSPOLAUTOR:
        return True
    if tabela not in db.TABELE_Z_AUTOREM:
        return True
    klucze = wiersz.keys()
    autor = wiersz["dodane_przez"] if "dodane_przez" in klucze else None
    return db.czy_moge_zmieniac_wpis(auto_id, autor)


__all__ = [
    "_nowy_kod",
    "_wolno_wypchnac_zmiane",
    "czy_udostepniony",
]
