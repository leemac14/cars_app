"""Jednostka dystansu — kilometry albo mile — w jednym miejscu.

Baza trzyma KAŻDY przebieg, dystans, interwał, próg i zasięg w kilometrach:
tak liczy reszta aplikacji (zużycie na 100 km, prognozy, powiadomienia) i tak
jedzie do chmury. Mile istnieją wyłącznie na styku z człowiekiem — przy
pokazywaniu liczby i przy jej wpisywaniu. Przełączenie jednostki nie zmienia
więc niczego w danych, a współdzielone auto każdy widzi we własnej jednostce.

Trzy rodzaje wielkości, trzy drogi:
  • dystans (licznik, zasięg, interwał) — `dystans_z_km` na ekran,
    `dystans_na_km` z pola formularza do bazy;
  • wielkość NA dystans (koszt 1 km, koszt / 1000 km) — `na_jednostke_dystansu`:
    mila jest dłuższa, więc koszt mili jest WIĘKSZY (mnożymy, nie dzielimy);
  • zużycie (l/100km, mpg, kWh/100mi…) — osobno, `energia.przelicz_zuzycie`.

Jednostkę można podać jawnie (`jednostka=`) — lista stu wpisów pyta wtedy
Ustawienia raz, a nie przy każdym wierszu.
"""

import re

from .pomocnicze import SEPARATOR_TYSIECY, _na_liczbe, liczba_na_tekst
from .stale import KM_W_MILI, NAZWY_JEDNOSTEK_DYSTANSU, PROGI_KM_OPCJE, PROGI_MIL_OPCJE
from .ustawienia import pobierz_jednostke_dystansu

# „km” jako osobne słowo — nie część „km/l”, „/100km” ani „kWh/100km”.
_SAMO_KM = re.compile(r"(?<![\w/])km(?![\w/])")


def jednostka_dystansu(jednostka=None) -> str:
    """„km” albo „mi” — podana jawnie wygrywa z Ustawieniami."""
    return jednostka if jednostka in NAZWY_JEDNOSTEK_DYSTANSU else pobierz_jednostke_dystansu()


def slowo_dystansu(forma="dopelniacz", jednostka=None) -> str:
    """Jednostka w zdaniu: „limit km” / „limit mil” (dopelniacz), nagłówek
    „Kilometry” / „Mile” (mianownik), „na kilometr” / „na milę” (biernik),
    „koszt kilometra” / „koszt mili” (dopelniacz_lp), „co ile kilometrów” /
    „co ile mil” (dopelniacz_pelny), skrót „km” / „mi” (skrot)."""
    return NAZWY_JEDNOSTEK_DYSTANSU[jednostka_dystansu(jednostka)][forma]


def etykieta_z_dystansem(tekst, jednostka=None) -> str:
    """Stała etykieta zapisana z „km” (nazwa kafelka kokpitu, nagłówek
    porównania) w jednostce z Ustawień: „Koszt / 1000 km” → „Koszt / 1000 mi”.
    Rusza tylko samodzielne „km” — „km/l” i „kWh/100km” to jednostki zużycia."""
    j = jednostka_dystansu(jednostka)
    tekst = str(tekst)
    return tekst if j == "km" else _SAMO_KM.sub(j, tekst)


def dystans_z_km(km, jednostka=None) -> float | None:
    """Kilometry z bazy → liczba w jednostce z Ustawień, do pokazania.
    Nie zaokrągla — to robi dopiero skład tekstu."""
    wartosc = _na_liczbe(km)
    if wartosc is None:
        return None
    return wartosc / KM_W_MILI if jednostka_dystansu(jednostka) == "mi" else wartosc


def dystans_na_km(wartosc, jednostka=None, calkowity=False, km_przy_otwarciu=None) -> float | int | None:
    """Liczba wpisana przez człowieka (w jednostce z Ustawień) → kilometry do bazy.

    `calkowity=True` dla kolumn INTEGER (licznik, interwał, próg, limit
    gwarancji). Zaokrąglamy DOPIERO po przeliczeniu, a mila jest dłuższa od
    kilometra, więc całkowita liczba mil wraca na ekran bez zmian:
    round(round(m · 1,609344) / 1,609344) == m dla każdego całkowitego m.

    W drugą stronę tak nie jest: 19 868 km to 12 345 mi, a 12 345 mi to już
    19 867 km. `km_przy_otwarciu` (wartość, którą formularz pokazał w polu)
    wraca bez zmian, jeśli człowiek jej nie ruszył — inaczej poprawka ceny
    tankowania przesuwałaby licznik o kilometr, a nowy wpis z podpowiedzianym
    aktualnym licznikiem dostawałby ostrzeżenie „niższy niż najwyższy”."""
    liczba = _na_liczbe(wartosc)
    if liczba is None:
        return None
    j = jednostka_dystansu(jednostka)
    pierwotny = _na_liczbe(km_przy_otwarciu)
    if pierwotny is not None:
        pokazany = dystans_z_km(pierwotny, j)
        miejsca = 0 if calkowity else 2
        if round(pokazany, miejsca) == round(liczba, miejsca):
            return int(round(pierwotny)) if calkowity else pierwotny
    km = liczba * KM_W_MILI if j == "mi" else liczba
    return int(round(km)) if calkowity else km


def na_jednostke_dystansu(wartosc_na_km, jednostka=None) -> float | None:
    """Wielkość liczona NA kilometr (koszt 1 km, koszt / 1000 km) → na milę."""
    wartosc = _na_liczbe(wartosc_na_km)
    if wartosc is None:
        return None
    return wartosc * KM_W_MILI if jednostka_dystansu(jednostka) == "mi" else wartosc


def tekst_dystansu(km, decimale=0, jednostka=None) -> str:
    """„12 345 km” / „7 671 mi” — ze spacją co trzy cyfry, jak na ekranie.
    Brak wartości daje zero, tak samo jak utils.formatuj_liczba."""
    j = jednostka_dystansu(jednostka)
    liczba = liczba_na_tekst(dystans_z_km(km, j), decimale, SEPARATOR_TYSIECY)
    if liczba is None:
        liczba = liczba_na_tekst(0, decimale, SEPARATOR_TYSIECY)
    return f"{liczba} {j}"


def wartosc_pola_dystansu(km, jednostka=None, decimale=0) -> str:
    """Tekst do wstawienia w pole formularza przy edycji: „” dla braku,
    liczba bez separatora tysięcy — tak, jak człowiek by ją wpisał. Ułamek
    (do `decimale` miejsc) tylko wtedy, gdy naprawdę jest: „450”, nie „450,0”."""
    wartosc = dystans_z_km(km, jednostka)
    if wartosc is None:
        return ""
    if decimale <= 0 or float(round(wartosc, decimale)).is_integer():
        return str(int(round(wartosc)))
    return liczba_na_tekst(wartosc, decimale) or ""


def opcje_progow_km(jednostka=None, obecny_km=None) -> list[tuple[int, str]]:
    """Progi ostrzegania do listy wyboru: (próg w km do zapisu, podpis).

    W milach okrągłe mile, przeliczone na km dopiero w kluczu. Próg zapisany
    wcześniej, którego nie ma na liście (np. 1500 km oglądane w milach), trafia
    na nią jako dodatkowa opcja — otwarcie formularza nie może go po cichu zmienić."""
    j = jednostka_dystansu(jednostka)
    progi = PROGI_MIL_OPCJE if j == "mi" else PROGI_KM_OPCJE
    opcje = [(dystans_na_km(p, j, calkowity=True), f"{liczba_na_tekst(p, 0, SEPARATOR_TYSIECY)} {j}")
             for p in progi]
    obecny = _na_liczbe(obecny_km)
    if obecny is not None and obecny > 0 and int(round(obecny)) not in {km for km, _ in opcje}:
        opcje.append((int(round(obecny)), tekst_dystansu(obecny, 0, j)))
        opcje.sort(key=lambda o: o[0])
    return opcje


def najblizszy_prog_km(km, jednostka=None) -> int | None:
    """Próg z listy dla danej jednostki najbliższy podanemu — po przełączeniu
    jednostki w Ustawieniach „1500 km” staje się okrągłym „1 000 mi”."""
    wartosc = _na_liczbe(km)
    if wartosc is None:
        return None
    return min((k for k, _ in opcje_progow_km(jednostka)), key=lambda k: abs(k - wartosc))


__all__ = [
    "dystans_na_km",
    "dystans_z_km",
    "etykieta_z_dystansem",
    "jednostka_dystansu",
    "na_jednostke_dystansu",
    "najblizszy_prog_km",
    "opcje_progow_km",
    "slowo_dystansu",
    "tekst_dystansu",
    "wartosc_pola_dystansu",
]
