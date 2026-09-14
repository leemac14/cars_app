"""Waga pisma jako hierarchia: pogrubienie znaczy „wartość albo nagłówek”.

`weight="bold"` bywało w tym projekcie domyślną wagą etykiet. Kiedy wszystko
jest ważne, nic nie jest — a najbardziej boli to na kaflach kokpitu i kartach
list, gdzie w małej przestrzeni stoi po pięć elementów i oko nie ma się o co
zaczepić.

Trzy role, trzy funkcje:

* `etykieta` — NAZWA wartości („Dystans”, „Spalanie”). Zwykła waga, przygaszony
  kolor, mały stopień. Nazwa ma się czytać dopiero wtedy, kiedy oko już znalazło
  liczbę i pyta, czego dotyczy.
* `wartosc` — sama LICZBA („412 km”). Pogrubiona, w zwykłym kolorze tekstu. To
  jedyne miejsce w karcie, które ma przyciągać wzrok pierwsze.
* `podpis` — reszta drugiego planu: data, stacja, notatka pod treścią. Wygląda
  jak etykieta, ale nie stoi nad żadną liczbą.

Zasada, której pilnuje `tests/test_typografia.py`: **pogrubienie nie chodzi
w parze z ON_SURFACE_VARIANT**. Przygaszony kolor mówi „drugi plan”,
pogrubienie mówi „pierwszy” — postawione razem znoszą się i zostaje sam szum.
Nagłówki i wartości zostają pogrubione, ale w pełnym kolorze tekstu; etykiety
zostają przygaszone, ale zwykłą wagą.
"""

import flet as ft

from .stale import FS

# Jedna nazwa na kolor drugiego planu — żeby reguła „przygaszone znaczy
# drugi plan” miała jedno miejsce, a nie piętnaście powtórzeń w widokach.
KOLOR_DRUGIEGO_PLANU = ft.Colors.ON_SURFACE_VARIANT


def _tekst(tekst, pola, nadpisania):
    """Wspólny składak: domyślne pola ustępują temu, co poda wywołujący.

    Gotowa kontrolka przechodzi bez zmian — liczba z animacji wejścia przychodzi
    jako `ft.Text` zbudowany przez scenę, a wywołujący nie powinien musieć
    rozróżniać tych dwóch przypadków."""
    if isinstance(tekst, ft.Control):
        return tekst
    pola.update(nadpisania)
    return ft.Text(tekst, **pola)


def etykieta(tekst, **nadpisania):
    """Nazwa wartości: mała, przygaszona, zwykłej wagi."""
    return _tekst(tekst, dict(size=FS["caption"], color=KOLOR_DRUGIEGO_PLANU), nadpisania)


def wartosc(tekst, **nadpisania):
    """Liczba albo stan, którego dotyczy etykieta: pogrubiona, w kolorze tekstu.

    Bez `color` z rozmysłem — wartość dostaje kolor tylko wtedy, gdy kolor coś
    znaczy (czerwień wydatku, zieleń terminu w porządku). Domyślnie wystarczy
    jej waga."""
    return _tekst(tekst, dict(size=FS["body_strong"], weight="bold"), nadpisania)


def podpis(tekst, **nadpisania):
    """Drugi plan, który nie jest niczyją etykietą: data, źródło, notatka."""
    return _tekst(tekst, dict(size=FS["label"], color=KOLOR_DRUGIEGO_PLANU), nadpisania)


def pole(nazwa, tresc, odstep=2, **nadpisania):
    """Etykieta nad wartością — najczęstsza para w kartach list.

    Istnieje nie dla skrócenia zapisu, tylko dlatego, że para zbudowana w jednym
    miejscu nie rozjedzie się przy dopisywaniu kolejnej kolumny obok. Tu reguła
    przestaje być umową, a staje się konstrukcją. `nadpisania` idą do wartości —
    etykieta nie ma czego nadpisywać."""
    return ft.Column([etykieta(nazwa), wartosc(tresc, **nadpisania)], spacing=odstep)


__all__ = [
    "KOLOR_DRUGIEGO_PLANU",
    "etykieta",
    "podpis",
    "pole",
    "wartosc",
]
