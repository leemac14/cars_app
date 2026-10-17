"""Waga pisma jako hierarchia: pogrubienie znaczy „wartość albo nagłówek”.
- `etykieta` — NAZWA wartości: zwykła waga, przygaszony kolor, mały stopień;
- `wartosc` — sama LICZBA: pogrubiona, pełny kolor;
- `podpis` — reszta drugiego planu (data, stacja, notatka).
Zasada (`tests/test_typografia.py`): pogrubienie NIE chodzi w parze z
ON_SURFACE_VARIANT."""

import flet as ft

from .stale import FS

# Jedna nazwa na kolor drugiego planu — żeby reguła „przygaszone znaczy
# drugi plan” miała jedno miejsce, a nie piętnaście powtórzeń w widokach.
KOLOR_DRUGIEGO_PLANU = ft.Colors.ON_SURFACE_VARIANT

# Skala tekstu z Ustawień (W-10). Flet nie ma skali tekstu dla całej strony, więc mnożnik
# dostaje KAŻDY ft.Text z jawnym rozmiarem w chwili utworzenia (ft.Text.init niżej); napisy
# bez rozmiaru biorą go z motywu (utils.zbuduj_motyw → text_theme).
SKALA_TEKSTU = {"mnoznik": 1.0}


def ustaw_skale_tekstu(mnoznik):
    """Mnożnik dla napisów tworzonych od tej chwili — ekran przebudowuje router."""
    SKALA_TEKSTU["mnoznik"] = float(mnoznik or 1.0)


def rozmiar_tekstu(rozmiar):
    """Rozmiar w skali z Ustawień — dla miejsc poza ft.Text (TextStyle, `text_size` pól)."""
    if isinstance(rozmiar, bool) or not isinstance(rozmiar, (int, float)):
        return rozmiar
    return rozmiar if SKALA_TEKSTU["mnoznik"] == 1.0 else round(rozmiar * SKALA_TEKSTU["mnoznik"], 1)


def _init_tekstu_ze_skala(self):
    _INIT_TEKSTU(self)
    self.size = rozmiar_tekstu(self.size)


if not getattr(ft.Text.init, "_ze_skala", False):
    _INIT_TEKSTU = ft.Text.init
    _init_tekstu_ze_skala._ze_skala = True
    ft.Text.init = _init_tekstu_ze_skala


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
    """Etykieta nad wartością — para zbudowana w jednym miejscu, żeby się nie
    rozjechała. `nadpisania` idą do wartości."""
    return ft.Column([etykieta(nazwa), wartosc(tresc, **nadpisania)], spacing=odstep)


__all__ = [
    "KOLOR_DRUGIEGO_PLANU",
    "SKALA_TEKSTU",
    "etykieta",
    "podpis",
    "pole",
    "rozmiar_tekstu",
    "ustaw_skale_tekstu",
    "wartosc",
]
