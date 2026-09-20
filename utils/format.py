"""Formatowanie i parsowanie: liczby, daty, spalanie, odmiana rzeczowników."""

import db
import flet as ft
import re
from date import parsuj_date
from datetime import date, datetime, timedelta

from .stale import KOLOR_STATUS, formatuj_liczba


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

# Miejscownik — do zdań „w maju”, „w grudniu”. Dopełniacz („w maja”) brzmi jak
# błąd literowy, a aplikacja jest po polsku od pierwszej etykiety.
MIESIACE_MIEJSCOWNIK = [
    "styczniu", "lutym", "marcu", "kwietniu", "maju", "czerwcu",
    "lipcu", "sierpniu", "wrześniu", "październiku", "listopadzie", "grudniu"
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


def _opis_prognozy_dni(dni):
    if dni <= 0:
        return "dziś"
    if dni == 1:
        return "jutro"
    return f"ok. {dni} dni"


def formatuj_prognoze_km(zostalo_km, sredni_dzienny_przebieg):
    tekst_km = f"{formatuj_liczba(zostalo_km, 0)} km"

    dni, data = oblicz_prognoze_terminu(zostalo_km, sredni_dzienny_przebieg)
    if dni is None:
        return tekst_km

    return f"{tekst_km} ({_opis_prognozy_dni(dni)} - {formatuj_date_pl(data)})"


def formatuj_dni(n):
    """„1 dzień”, „2 dni”, „1 234 dni” — liczba dni z jednostką w dobrej formie."""
    return f"{formatuj_liczba(n, 0)} {'dzień' if abs(n) == 1 else 'dni'}"


def formatuj_okres(dni):
    """Odległość w czasie do pokazania na karcie: dni do dwóch miesięcy, dalej
    miesiące. „143 dni” trzeba przeliczać w głowie, „~5 mies.” już nie."""
    dni = abs(int(dni))
    if dni == 0:
        return "dziś"
    if dni <= 60:
        return formatuj_dni(dni)
    return f"~{formatuj_liczba(round(dni / db.DNI_W_MIESIACU_INTERWALU), 0)} mies."


# ---------------------------------------------------------------------------
#  Interwał podzespołu słowami (liczby liczy db.oblicz_stan_interwalu)
# ---------------------------------------------------------------------------

def _zostalo(liczba, reszta):
    """Czasownik zgodny z liczbą: „Został 1 dzień”, „Zostały 3 dni”, „Zostało 640 km”."""
    return f"{_odmiana_liczby(abs(liczba), 'Został', 'Zostały', 'Zostało')} {reszta}"


def _zdanie_pierwszego_licznika(licznik):
    """Pełne zdanie o liczniku, który skończy się pierwszy — z datą, bo to
    właśnie ona jest terminem wynikowym całego podzespołu."""
    zostalo = licznik["zostalo"]
    if licznik["rodzaj"] == "km":
        if zostalo < 0:
            return f"Przekroczono o {formatuj_liczba(-zostalo, 0)} km"
        tekst = _zostalo(zostalo, f"{formatuj_liczba(zostalo, 0)} km")
        if licznik.get("dni") is not None and licznik.get("data"):
            tekst += f" ({_opis_prognozy_dni(licznik['dni'])} - {formatuj_date_pl(licznik['data'])})"
        return tekst
    if zostalo < 0:
        return f"Przekroczono o {formatuj_dni(-zostalo)}"
    if zostalo == 0:
        return f"Termin mija dziś ({formatuj_date_pl(licznik['data'])})"
    return _zostalo(zostalo, f"{formatuj_dni(zostalo)} ({formatuj_date_pl(licznik['data'])})")


def _zdanie_drugiego_licznika(licznik):
    """Krótsze zdanie o liczniku, który przyjdzie później. „Dopiero” jest tu
    całym znacznikiem kolejności — mówi, że to nie on wyznacza termin."""
    zostalo = licznik["zostalo"]
    if licznik["rodzaj"] == "km":
        if zostalo < 0:
            return f"Limit km też przekroczony (o {formatuj_liczba(-zostalo, 0)} km)"
        tekst = f"Limit km dopiero za {formatuj_liczba(zostalo, 0)} km"
        if licznik.get("data"):
            tekst += f" (ok. {formatuj_date_pl(licznik['data'])})"
        return tekst
    if zostalo < 0:
        return f"Termin też minął ({formatuj_date_pl(licznik['data'])})"
    return f"Termin dopiero {formatuj_date_pl(licznik['data'])}"


def linie_opisu_interwalu(stan):
    """[zdanie o liczniku, który przyjdzie pierwszy, zdanie o drugim]. Drugiego
    nie ma, gdy interwał ma jeden licznik; pusta lista — gdy nie ma żadnego."""
    pierwsze = (stan or {}).get("pierwsze")
    if not pierwsze:
        return []
    drugie = "czas" if pierwsze == "km" else "km"
    linie = [_zdanie_pierwszego_licznika(stan[pierwsze])]
    if stan.get(drugie):
        linie.append(_zdanie_drugiego_licznika(stan[drugie]))
    return linie


def polacz_linie_opisu(linie):
    """Linie opisu jako jedno zdanie — dla miejsc, które mają na tekst jedną
    linijkę (kafel „Termin” na kokpicie, rozpiska kondycji)."""
    if not linie:
        return ""
    return " • ".join([linie[0]] + [linia[:1].lower() + linia[1:] for linia in linie[1:]])


def opis_licznika_na_karte(licznik):
    """(wartość, podpis) licznika do kolumny na karcie podzespołu. Wartość jest
    krótka, bo stoi obok drugiej; datę niesie podpis."""
    zostalo = licznik["zostalo"]
    if licznik["rodzaj"] == "km":
        wartosc = f"{formatuj_liczba(abs(zostalo), 0)} km"
        if zostalo < 0:
            return wartosc, "ponad limit"
        if licznik.get("data"):
            return wartosc, f"ok. {licznik['data'].strftime('%d.%m.%Y')}"
        return wartosc, f"z {formatuj_liczba(licznik['interwal'], 0)} km"
    if zostalo < 0:
        return formatuj_okres(zostalo), "po terminie"
    return formatuj_okres(zostalo), f"do {licznik['data'].strftime('%d.%m.%Y')}"


def kolor_i_tekst_terminu(termin_str):
    if not termin_str:
        return KOLOR_STATUS["neutral"], ""
        
    d_obj = parsuj_date(termin_str)
    if d_obj == datetime.min.date():
        return ft.Colors.ON_SURFACE_VARIANT, termin_str
        
    dzis = datetime.now().date()
    roznica = (d_obj - dzis).days
    
    if roznica < 0:
        return KOLOR_STATUS["critical"], f"Po terminie ({abs(roznica)} dni)"
    elif roznica == 0:
        return KOLOR_STATUS["critical"], "Na dzisiaj!"
    elif roznica == 1:
        return KOLOR_STATUS["warning"], "Na jutro"
    elif roznica <= 7:
        return KOLOR_STATUS["warning"], f"Za {roznica} dni"
    else:
        return KOLOR_STATUS["ok"], str(termin_str)


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
    "MIESIACE_MIEJSCOWNIK",
    "_MAPA_OGONKOW",
    "_odmiana_liczby",
    "bez_ogonkow",
    "formatuj_date_pl",
    "formatuj_dni",
    "formatuj_okres",
    "formatuj_prognoze_km",
    "formatuj_spalanie",
    "kolor_i_tekst_terminu",
    "linie_opisu_interwalu",
    "oblicz_prognoze_terminu",
    "opis_licznika_na_karte",
    "parsuj_float",
    "parsuj_int",
    "polacz_linie_opisu",
    "symbol_waluty",
]
