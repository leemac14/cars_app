"""Rola uczestnika: kto ma prawo wypchnąć zmianę, a kto tylko czyta.

Trzy krótkie funkcje, ale to one stoją przed wszystkimi zapisami do chmury,
więc mieszkają nisko w pakiecie i nie zależą od niczego poza `db`.

Blokada w interfejsie jest wygodą, a `_wolno_wypchnac_zmiane` drugą warstwą;
twardą granicę stawia wyzwalacz po stronie Supabase
(patrz supabase/role_wspoldzielenia.sql). Warstwy są trzy, bo błąd w tym
miejscu oznacza nadpisanie cudzych danych.
"""

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
    """Czy wolno mi wysłać ZMIANĘ istniejącego rekordu.

    Podgląd nie wysyła nic. Współautor nie rusza cudzych wpisów — ale tylko
    w tabelach, w których „czyj to wpis” w ogóle ma sens (te z kolumną
    `dodane_przez`). Podzespoły, tagi, warsztaty czy magazyn to wspólny
    słownik pojazdu: zablokowanie ich odebrałoby współautorowi możliwość
    dopisania przebiegu do podzespołu, który sam wcześniej założył."""
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
