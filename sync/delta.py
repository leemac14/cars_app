"""Pobieranie przyrostowe — pytamy o to, co zmieniło się od ostatniego razu.

Jedna decyzja na całą aplikację: czy serwer zna kolumnę znacznika. Gdy nie zna,
`_wylacz_delte` zapamiętuje to raz i pakiet po cichu wraca do pełnego
pobierania — użytkownik nie widzi błędu, bo z jego punktu widzenia nic się
nie stało.

`_delta_dostepna` jest ŚWIADOMIE nieujęte w `__all__` — patrz komentarz niżej.
"""

import db
import log


# Czy serwer w ogóle zna kolumnę znacznika. None = jeszcze nie sprawdzone.
# Poza `__all__` ŚWIADOMIE: `_wylacz_delte` PRZYPISUJE tę nazwę na nowo
# (`global`), więc re-eksport zamroziłby kopię z chwili importu. Listy
# konfliktów wolno re-eksportować, bo tamte są mutowane w miejscu.
_delta_dostepna = None


def _delta_wlaczona():
    global _delta_dostepna
    if _delta_dostepna is None:
        _delta_dostepna = db.pobierz_ustawienie("sync_delta_niedostepna") != "1"
    return _delta_dostepna


def _wylacz_delte():
    """Serwer nie zna kolumny znacznika — zapamiętujemy to na stałe, żeby nie
    ponawiać nieudanego zapytania przy każdej tabeli i każdej synchronizacji."""
    global _delta_dostepna
    _delta_dostepna = False
    try:
        db.zapisz_ustawienie("sync_delta_niedostepna", "1")
    except Exception:
        log.polkniety("zapamiętanie braku synchronizacji przyrostowej")


__all__ = [
    "_delta_wlaczona",
    "_wylacz_delte",
]
