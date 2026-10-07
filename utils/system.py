"""Wyjście poza aplikację: schowek, dzwonienie, mapy, strony w przeglądarce,
systemowe „Udostępnij” i jasność ekranu."""

import flet as ft
import inspect
import urllib.parse

import log

from .stale import KOLOR_STATUS
from .dialogi import pokaz_komunikat


def _na_telefonie(page: ft.Page) -> bool:
    return getattr(page, "platform", None) in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS)


def _usluga(page: ft.Page, atrybut, klasa):
    """Jedna instancja usługi Fleta na stronę, trzymana na `page`. Usługa bez
    silnej referencji wypada z rejestru strony, a w połowie wywołania nie ma jej
    już kto odebrać."""
    usluga = getattr(page, atrybut, None)
    if usluga is None:
        usluga = klasa()
        if hasattr(page, "services"):
            page.services.append(usluga)
        else:
            page.overlay.append(usluga)
        setattr(page, atrybut, usluga)
    return usluga


async def odczytaj_schowek(page: ft.Page):
    """Tekst ze schowka albo pusty napis. Wołać tylko na wyraźne „Wklej”:
    Android 12+ przy każdym odczycie pokazuje dymek „wklejono ze schowka”."""
    try:
        return (await _usluga(page, "_schowek", ft.Clipboard).get()) or ""
    except Exception:
        log.polkniety("odczyt schowka")
        return ""


def udostepnij_tekst(page: ft.Page, tekst, temat=None, komunikat_awaryjny="Skopiowano do schowka"):
    """Systemowe „Udostępnij” na telefonie (SMS, komunikator, e-mail). Na
    komputerze arkusza nie ma — tam, i gdy się nie otworzy, tekst idzie do
    schowka z `komunikat_awaryjny`."""
    if not _na_telefonie(page):
        kopiuj_do_schowka(page, tekst, komunikat_awaryjny)
        return

    async def _zadanie():
        try:
            usluga = getattr(page, "share_service", None) or _usluga(page, "_udostepnianie", ft.Share)
            await usluga.share_text(tekst, subject=temat)
        except Exception:
            log.polkniety("udostępnienie tekstu przez system")
            kopiuj_do_schowka(page, tekst, komunikat_awaryjny)

    page.run_task(_zadanie)


def ustaw_jasnosc_kodu(page: ft.Page, pelna):
    """Jasność aplikacji na maksimum na czas pokazywania kodu do zeskanowania
    (aparat drugiego telefonu łapie go szybciej, także w słońcu); `pelna=False`
    oddaje ją systemowi. Tylko na telefonie — na komputerze wtyczka
    przestawiałaby jasność monitora."""
    if not _na_telefonie(page):
        return

    async def _zadanie():
        try:
            jasnosc = _usluga(page, "_jasnosc", ft.ScreenBrightness)
            if pelna:
                await jasnosc.set_application_screen_brightness(1.0)
            else:
                await jasnosc.reset_application_screen_brightness()
        except Exception:
            log.polkniety("jasność ekranu przy kodzie do zeskanowania")

    page.run_task(_zadanie)


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
    """Strona w przeglądarce jako OSOBNA aplikacja (domyślnie Android otwiera kartę nad
    aplikacją, a jej zamknięcie zabiera wpisany formularz). Gdy się nie otworzy — adres
    do schowka."""
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
    "odczytaj_schowek",
    "otworz_strone",
    "pokaz_na_mapie",
    "udostepnij_tekst",
    "ustaw_jasnosc_kodu",
    "zadzwon",
]
