"""Haptyka telefonu: krótka wibracja przy zapisie, usuwaniu i przełączaniu."""

import inspect

import db
import flet as ft
import log

# Rodzaj zdarzenia → metoda usługi HapticFeedback.
WIBRACJE = {
    "wybor": "selection_click",      # zakładka, segment, gest notatki
    "zapis": "light_impact",         # zapis formularza
    "usuniecie": "medium_impact",    # usunięcie wpisu (z „Cofnij”)
}


def _na_telefonie(page) -> bool:
    return getattr(page, "platform", None) in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS)


def wibracja(page, rodzaj="wybor"):
    """Wibracja z `WIBRACJE` — tylko na telefonie i przy włączonym przełączniku w Ustawieniach.
    Usługę tworzy main.py (`page.haptyka`); bez niej powstaje przy pierwszym użyciu."""
    metoda = WIBRACJE.get(rodzaj)
    if metoda is None or page is None or not _na_telefonie(page):
        return
    try:
        if not db.czy_wibracje():
            return
    except Exception:
        log.polkniety("ustawienie wibracji")
        return

    async def _wibruj():
        try:
            usluga = getattr(page, "haptyka", None)
            if usluga is None:
                usluga = ft.HapticFeedback()
                page.services.append(usluga)
                page.haptyka = usluga
            await getattr(usluga, metoda)()
        except Exception:
            log.polkniety("wibracja")

    try:
        page.run_task(_wibruj)
    except Exception:
        log.polkniety("wibracja bez pętli zdarzeń")


def z_wibracja(page, akcja, rodzaj="zapis"):
    """Obsługa kliknięcia poprzedzona wibracją. Synchroniczna zostaje synchroniczna (testy
    i inne miejsca wołają `on_click` wprost)."""
    if akcja is None:
        return None
    if inspect.iscoroutinefunction(akcja):
        async def _klik_async(e):
            wibracja(page, rodzaj)
            return await akcja(e)
        return _klik_async

    def _klik(e):
        wibracja(page, rodzaj)
        return akcja(e)
    return _klik


__all__ = [
    "WIBRACJE",
    "wibracja",
    "z_wibracja",
]
