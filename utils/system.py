"""Wyjście poza aplikację: schowek, dzwonienie, mapy i strony w przeglądarce."""

import flet as ft
import inspect
import urllib.parse

from .stale import KOLOR_STATUS
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
            pokaz_komunikat(page, "Nie udało się skopiować.", KOLOR_STATUS["error"])

    try:
        page.run_task(_zadanie)
    except Exception:
        pokaz_komunikat(page, "Nie udało się skopiować.", KOLOR_STATUS["error"])


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


def link_mapy(adres, platforma=None):
    """Adres zamieniony na link do map. Na Androidzie `geo:` — system sam
    proponuje aplikacje map (Mapy Google, Waze, OsmAnd) albo otwiera domyślną.
    Gdzie indziej (Windows, iOS, przeglądarka) `geo:` nie ma kto obsłużyć, więc
    idzie wyszukiwanie w Google Maps, które otworzy każda przeglądarka."""
    tekst = " ".join(str(adres or "").split())
    if not tekst:
        return ""
    zapytanie = urllib.parse.quote(tekst)
    if str(getattr(platforma, "value", platforma) or "").lower() == "android":
        return f"geo:0,0?q={zapytanie}"
    return f"https://www.google.com/maps/search/?api=1&query={zapytanie}"


def pokaz_na_mapie(page: ft.Page, adres):
    """Otwarcie adresu w mapach — do warsztatu się jedzie, a przepisywanie
    ulicy z jednej aplikacji do drugiej to ten sam kłopot, co cyfry numeru przy
    zadzwon(). Gdy mapy się nie otworzą, adres ląduje w schowku."""
    link = link_mapy(adres, getattr(page, "platform", None))
    if not link:
        return

    async def _zadanie():
        try:
            wynik = page.launch_url(link)
            if inspect.isawaitable(wynik):
                await wynik
        except Exception:
            kopiuj_do_schowka(page, adres, "Nie udało się otworzyć map — adres w schowku")

    try:
        page.run_task(_zadanie)
    except Exception:
        kopiuj_do_schowka(page, adres, "Adres skopiowany do schowka")


def otworz_strone(page: ft.Page, adres):
    """Strona w przeglądarce jako OSOBNEJ aplikacji. Domyślny tryb otwiera ją
    na Androidzie w karcie nad aplikacją — a z takiej karty nie da się wrócić
    tutaj po kolejną rzecz do skopiowania bez zamknięcia jej razem z tym, co
    już wpisano w formularz. Między osobnymi aplikacjami przełącza się tam
    i z powrotem bez strat. Gdy przeglądarka się nie otworzy, adres ląduje
    w schowku."""
    if not adres:
        return

    async def _zadanie():
        try:
            await ft.UrlLauncher().launch_url(adres, mode=ft.LaunchMode.EXTERNAL_APPLICATION)
        except Exception:
            kopiuj_do_schowka(page, adres, "Nie udało się otworzyć przeglądarki — adres w schowku")

    try:
        page.run_task(_zadanie)
    except Exception:
        kopiuj_do_schowka(page, adres, "Adres skopiowany do schowka")


__all__ = [
    "kopiuj_do_schowka",
    "link_mapy",
    "otworz_strone",
    "pokaz_na_mapie",
    "zadzwon",
]
