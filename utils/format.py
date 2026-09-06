"""Formatowanie i parsowanie: liczby, daty, spalanie, odmiana rzeczowników."""

import db
import flet as ft
import re
from date import parsuj_date
from datetime import date, datetime, timedelta

from .stale import formatuj_liczba


def parsuj_int(wartosc, domyslna=0):
    if wartosc is None: return domyslna
    tekst = str(wartosc).strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    if not tekst: return domyslna
    try:
        return int(round(float(tekst)))
    except (ValueError, TypeError):
        dopasowanie = re.search(r"-?\d+", tekst)
        return int(dopasowanie.group()) if dopasowanie else domyslna


def parsuj_float(wartosc, domyslna=0.0):
    if wartosc is None: return domyslna
    tekst = str(wartosc).strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    if not tekst: return domyslna
    try:
        return float(tekst)
    except (ValueError, TypeError):
        dopasowanie = re.search(r"-?\d+(\.\d+)?", tekst)
        return float(dopasowanie.group()) if dopasowanie else domyslna


_MAPA_OGONKOW = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")


def bez_ogonkow(tekst):
    """Porównywanie w wyszukiwarce ma działać niezależnie od ogonków: kto pisze
    w biegu „budzet” albo „przeglad”, ma dostać to samo, co po pełnym zapisie."""
    return str(tekst or "").translate(_MAPA_OGONKOW)


def formatuj_spalanie(wartosc_na_100km, decimale=1, elektryczny=False):
    """Formatuje zużycie w jednostce z Ustawień. Wejściem ZAWSZE jest zużycie
    na 100 km (l/100km albo kWh/100km) — dokładnie to, co liczy reszta aplikacji;
    przeliczenie na km/l, mpg czy km/kWh robimy dopiero tutaj."""
    # Samo przeliczenie siedzi w db.przelicz_zuzycie — korzystają z niego też
    # teksty obserwacji budowane po stronie danych. Tutaj zostaje wyłącznie
    # formatowanie liczby (spacje i przecinek dziesiętny).
    wynik, jednostka = db.przelicz_zuzycie(wartosc_na_100km, elektryczny)
    if wynik is None:
        return f"- {jednostka}"
    return f"{formatuj_liczba(wynik, decimale)} {jednostka}"


def symbol_waluty():
    return db.pobierz_walute()


MIESIACE_DOPELNIACZ = [
    "stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca",
    "lipca", "sierpnia", "września", "października", "listopada", "grudnia"
]


def formatuj_date_pl(d):
    tekst = f"{d.day} {MIESIACE_DOPELNIACZ[d.month - 1]}"
    if d.year != datetime.now().year:
        tekst += f" {d.year}"
    return tekst


def oblicz_prognoze_terminu(zostalo_km, sredni_dzienny_przebieg):
    if not sredni_dzienny_przebieg or sredni_dzienny_przebieg <= 0:
        return None, None
    if zostalo_km is None or zostalo_km < 0:
        return None, None

    dni = int(round(zostalo_km / sredni_dzienny_przebieg))
    return dni, date.today() + timedelta(days=dni)


def formatuj_prognoze_km(zostalo_km, sredni_dzienny_przebieg):
    tekst_km = f"{formatuj_liczba(zostalo_km, 0)} km"

    dni, data = oblicz_prognoze_terminu(zostalo_km, sredni_dzienny_przebieg)
    if dni is None:
        return tekst_km

    if dni <= 0:
        opis_dni = "dziś"
    elif dni == 1:
        opis_dni = "jutro"
    else:
        opis_dni = f"ok. {dni} dni"

    return f"{tekst_km} ({opis_dni} - {formatuj_date_pl(data)})"


def kolor_i_tekst_terminu(termin_str):
    if not termin_str:
        return ft.Colors.ON_SURFACE_VARIANT, ""
        
    d_obj = parsuj_date(termin_str)
    if d_obj == datetime.min.date():
        return ft.Colors.ON_SURFACE_VARIANT, termin_str
        
    dzis = datetime.now().date()
    roznica = (d_obj - dzis).days
    
    if roznica < 0:
        return ft.Colors.RED_700, f"Po terminie ({abs(roznica)} dni)"
    elif roznica == 0:
        return ft.Colors.RED_700, "Na dzisiaj!"
    elif roznica == 1:
        return ft.Colors.ORANGE_700, "Na jutro"
    elif roznica <= 7:
        return ft.Colors.ORANGE_700, f"Za {roznica} dni"
    else:
        return ft.Colors.GREEN_700, str(termin_str)


def _odmiana_liczby(n, forma_1, forma_2_4, forma_pozostale):
    """Generyczna polska odmiana liczebnikowa: 1 -> forma_1, 2-4 (poza
    nastolatkami 12-14) -> forma_2_4, pozostałe -> forma_pozostale."""
    if n == 1:
        return forma_1
    ostatnia, dziesiatki = n % 10, n % 100
    if 2 <= ostatnia <= 4 and not (12 <= dziesiatki <= 14):
        return forma_2_4
    return forma_pozostale


__all__ = [
    "MIESIACE_DOPELNIACZ",
    "_MAPA_OGONKOW",
    "_odmiana_liczby",
    "bez_ogonkow",
    "formatuj_date_pl",
    "formatuj_prognoze_km",
    "formatuj_spalanie",
    "kolor_i_tekst_terminu",
    "oblicz_prognoze_terminu",
    "parsuj_float",
    "parsuj_int",
    "symbol_waluty",
]
