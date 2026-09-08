"""Dane dla widoku osi czasu."""

import sqlite3

from .polaczenie import polacz_baze
from .pomocnicze import formatuj_liczba_eksport


def pobierz_dane_timeline(auto_id) -> list[tuple[str, str, str, str, str, float | None, str | None, str, str | None, str | None]]:
    """Zbiorcza, chronologiczna lista zdarzeń pojazdu ze wszystkich modułów
    (tankowania, historia serwisowa, wizyty zbiorcze, inne koszty, galeria
    karoserii, odczyty przebiegu) — używana przez widok /timeline ("dziennik
    życia auta"). Wpisy historii powiązane z wizytą zbiorczą są pomijane
    (reprezentuje je already sama wizyta), analogicznie do eksportu danych.
    Zwraca listę krotek: (id_timeline, typ, data, tytul, opis, kwota, zalacznik,
    trasa, dodane_przez, notatka). 'dodane_przez' zasila filtr autorstwa przy
    pojeździe współdzielonym; zdjęcia karoserii nie mają tej kolumny, więc trafia
    tam None. 'notatka' to krótka uwaga wpisu — dziennik życia auta bez niej
    gubiłby dokładnie ten kontekst, po który się do niego wraca."""
    if not auto_id:
        return []

    zdarzenia = []

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute(
            "SELECT id, data, przebieg, litry, kwota, stacja, do_pelna, zalacznik, dodane_przez, notatka "
            "FROM tankowania WHERE auto_id=?", (auto_id,)
        )
        for r in c.fetchall():
            opis = f"{formatuj_liczba_eksport(r['litry'], 1)} L" + (f" • {r['stacja']}" if r['stacja'] else "")
            opis += f" • {int(r['przebieg'] or 0)} km"
            zdarzenia.append((
                f"tankowanie_{r['id']}", "Tankowanie", r["data"],
                "Tankowanie" + (" (do pełna)" if r["do_pelna"] else ""), opis,
                float(r["kwota"] or 0), r["zalacznik"], f"/tankowanie/edytuj/{r['id']}",
                r["dodane_przez"], r["notatka"],
            ))

        c.execute(
            "SELECT h.id, h.data, h.przebieg, h.cena, h.wykonawca, z.nazwa, h.zalacznik, h.dodane_przez, h.notatka "
            "FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE z.auto_id=? AND h.wizyta_id IS NULL", (auto_id,)
        )
        for r in c.fetchall():
            opis = f"{int(r['przebieg'] or 0)} km" + (f" • {r['wykonawca']}" if r["wykonawca"] else "")
            zdarzenia.append((
                f"historia_{r['id']}", "Serwis", r["data"],
                str(r["nazwa"]), opis,
                float(r["cena"] or 0), r["zalacznik"], f"/wpis/edytuj/{r['id']}",
                r["dodane_przez"], r["notatka"],
            ))

        c.execute(
            "SELECT w.id, w.data, w.przebieg, w.wykonawca, w.koszt_calkowity, w.zalacznik, w.dodane_przez, w.notatki, "
            "GROUP_CONCAT(z.nazwa, ', ') as czesci "
            "FROM wizyty w LEFT JOIN historia h ON h.wizyta_id=w.id LEFT JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE w.auto_id=? GROUP BY w.id", (auto_id,)
        )
        for r in c.fetchall():
            opis = str(r["czesci"] or "Brak podpiętych części") + (f" • {r['wykonawca']}" if r["wykonawca"] else "")
            zdarzenia.append((
                f"wizyta_{r['id']}", "Wizyta zbiorcza", r["data"],
                "Wizyta w warsztacie", opis,
                float(r["koszt_calkowity"] or 0), r["zalacznik"], f"/wizyty/edytuj/{r['id']}",
                r["dodane_przez"], r["notatki"],
            ))

        c.execute("SELECT id, data, nazwa, kategoria, kwota, zalacznik, dodane_przez, notatka FROM inne_koszty WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            zdarzenia.append((
                f"inne_{r['id']}", "Inny koszt", r["data"],
                str(r["nazwa"] or "Koszt"), str(r["kategoria"] or ""),
                float(r["kwota"] or 0), r["zalacznik"], f"/inne/edytuj/{r['id']}",
                r["dodane_przez"], r["notatka"],
            ))

        c.execute("SELECT id, data, strefa, typ_porownania, opis, zalacznik FROM zdjecia_karoserii WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            opis = str(r["typ_porownania"]) if r["typ_porownania"] and r["typ_porownania"] != "Brak" else (r["opis"] or "")
            zdarzenia.append((
                f"zdjecie_{r['id']}", "Zdjęcie karoserii", r["data"],
                f"Zdjęcie: {r['strefa']}", opis,
                None, r["zalacznik"], f"/karoseria/edytuj/{r['id']}", None, r["opis"],
            ))

        c.execute("SELECT id, data, przebieg, notatka FROM odczyty_przebiegu WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            zdarzenia.append((
                f"odczyt_{r['id']}", "Odczyt przebiegu", r["data"],
                "Odczyt licznika", f"{int(r['przebieg'] or 0)} km",
                None, None, "/przebieg", None, r["notatka"],
            ))

    return zdarzenia


__all__ = [
    "pobierz_dane_timeline",
]
