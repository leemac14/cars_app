"""Wyjście poza aplikację: schowek i dzwonienie."""

import flet as ft
import inspect

from .dialogi import pokaz_komunikat


def kopiuj_do_schowka(page: ft.Page, wartosc, komunikat="Skopiowano do schowka"):
    """Kopiowanie odporne na wersję Fleta: nowe API (usługa Clipboard) jest
    asynchroniczne, starsze miało metodę na stronie. VIN czy numer polisy
    przepisuje się z ekranu wyjątkowo źle, więc ta droga musi po prostu działać."""
    tekst = str(wartosc or "").strip()
    if not tekst:
        return

    metoda_synchroniczna = getattr(page, "set_clipboard", None)
    if callable(metoda_synchroniczna):
        try:
            metoda_synchroniczna(tekst)
            pokaz_komunikat(page, komunikat)
            return
        except Exception:
            pass

    async def _zadanie():
        try:
            schowek = getattr(page, "_schowek", None)
            if schowek is None:
                schowek = ft.Clipboard()
                if hasattr(page, "services"):
                    page.services.append(schowek)
                else:
                    page.overlay.append(schowek)
                page._schowek = schowek
            await schowek.set(tekst)
            pokaz_komunikat(page, komunikat)
        except Exception:
            pokaz_komunikat(page, "Nie udało się skopiować.", ft.Colors.RED_700)

    try:
        page.run_task(_zadanie)
    except Exception:
        pokaz_komunikat(page, "Nie udało się skopiować.", ft.Colors.RED_700)


def zadzwon(page: ft.Page, numer):
    """Wybranie numeru z aplikacji. Telefon do assistance ma sens tylko wtedy,
    gdy da się go użyć jednym dotknięciem — przepisywanie cyfr z ekranu na
    poboczu, po stłuczce, jest dokładnie tym, czego chcemy uniknąć."""
    czysty = "".join(z for z in str(numer or "") if z.isdigit() or z == "+")
    if not czysty:
        return

    async def _zadanie():
        try:
            wynik = page.launch_url(f"tel:{czysty}")
            if inspect.isawaitable(wynik):
                await wynik
        except Exception:
            kopiuj_do_schowka(page, numer, "Nie udało się zadzwonić — numer w schowku")

    try:
        page.run_task(_zadanie)
    except Exception:
        kopiuj_do_schowka(page, numer, "Numer skopiowany do schowka")


__all__ = [
    "kopiuj_do_schowka",
    "zadzwon",
]
