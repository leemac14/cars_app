"""Krótkie notatki przypinane do pojedynczych wpisów."""

import sqlite3
from datetime import datetime

from .stale import MAKS_DLUGOSC_NOTATKI, POLA_NOTATKI, TABELE_NOTATKI_Z_PODPISEM
from .polaczenie import polacz_baze
from .ustawienia import pobierz_moje_imie


# Tabele bez własnej kolumny auto_id — pojazd wyznacza dopiero JOIN.
_ZAPYTANIA_AUTO_ID = {
    "historia": "SELECT z.auto_id FROM historia h JOIN zadania z ON h.zadanie_id = z.id WHERE h.id=?",
}


def auto_id_rekordu(tabela, rekord_id):
    """Pojazd, do którego należy pojedynczy rekord. Potrzebne przy zapisie
    notatki poza formularzem (z menu wpisu), gdzie nie mamy pod ręką stanu
    aplikacji, a trzeba wypchnąć zmianę do właściwego współdzielonego auta."""
    if not rekord_id:
        return None
    zapytanie = _ZAPYTANIA_AUTO_ID.get(tabela, f"SELECT auto_id FROM {tabela} WHERE id=?")
    with polacz_baze() as conn:
        c = conn.cursor()
        try:
            c.execute(zapytanie, (rekord_id,))
        except sqlite3.OperationalError:
            return None
        w = c.fetchone()
    return w[0] if w else None


def przytnij_notatke(tresc):
    """Jedno miejsce na normalizację treści notatki — formularz i szybka edycja
    muszą przycinać tak samo, inaczej limit da się obejść jedną z dróg."""
    return (tresc or "").strip()[:MAKS_DLUGOSC_NOTATKI]


def pobierz_notatke(tabela, rekord_id):
    """(treść, autor, data) notatki wpisu. Autor i data są puste dla tabel,
    które notatkę trzymają w starym polu opisowym bez podpisu."""
    kolumna = POLA_NOTATKI.get(tabela)
    if not kolumna or not rekord_id:
        return "", None, None
    z_podpisem = tabela in TABELE_NOTATKI_Z_PODPISEM
    pola = f"{kolumna}, notatka_autor, notatka_data" if z_podpisem else kolumna
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(f"SELECT {pola} FROM {tabela} WHERE id=?", (rekord_id,))
        w = c.fetchone()
    if not w:
        return "", None, None
    return (str(w[0] or ""), w[1], w[2]) if z_podpisem else (str(w[0] or ""), None, None)


def zapisz_notatke(tabela, rekord_id, tresc):
    """Zapisuje krótką notatkę POJEDYNCZEGO wpisu i zwraca auto_id pojazdu —
    wołający wypycha nim zmianę w tle (utils.wypchnij_w_tle), dzięki czemu
    notatka dociera do wszystkich współdzielących ten pojazd.
    Pusta treść kasuje notatkę RAZEM z podpisem: sam autor bez tekstu
    zostawiałby na karcie „Kasia • 04.09.2026” bez żadnej uwagi."""
    kolumna = POLA_NOTATKI.get(tabela)
    if not kolumna or not rekord_id:
        raise ValueError(f"Wpisy z tabeli '{tabela}' nie mają notatki.")

    tekst = przytnij_notatke(tresc)
    with polacz_baze() as conn:
        if tabela in TABELE_NOTATKI_Z_PODPISEM:
            conn.execute(
                f"UPDATE {tabela} SET {kolumna}=?, notatka_autor=?, notatka_data=? WHERE id=?",
                (tekst or None,
                 pobierz_moje_imie() if tekst else None,
                 datetime.now().strftime("%d.%m.%Y %H:%M") if tekst else None,
                 rekord_id)
            )
        else:
            conn.execute(f"UPDATE {tabela} SET {kolumna}=? WHERE id=?", (tekst or None, rekord_id))
    return auto_id_rekordu(tabela, rekord_id)


__all__ = [
    "_ZAPYTANIA_AUTO_ID",
    "auto_id_rekordu",
    "pobierz_notatke",
    "przytnij_notatke",
    "zapisz_notatke",
]
