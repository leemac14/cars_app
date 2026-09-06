"""Zgodność z wersjami Fleta — pola kontrolek, które zmieniały nazwy."""

import dataclasses


# ==================== ZGODNOŚĆ Z WERSJAMI FLETA ====================
# Kontrolki Fleta to dataclassy BEZ __slots__, więc `pole.cokolwiek = x` nigdy
# nie rzuca wyjątku — zwyczajnie dokleja nowy, nikomu niepotrzebny atrybut.
# Skutek: po zmianie nazwy pola między wersjami kod dalej „działa”, tylko efekt
# przestaje być widoczny (komunikat błędu się nie pokazuje, ikona się nie
# przełącza, napis na przycisku zostaje stary). Poniższe funkcje wybierają
# nazwę pola na podstawie DEFINICJI klasy, więc trafiają zawsze.

_CACHE_POL = {}


def _nazwa_pola(kontrolka, *kandydaci):
    """Pierwsza z podanych nazw, która naprawdę istnieje w klasie kontrolki."""
    klucz = (type(kontrolka), kandydaci)
    if klucz not in _CACHE_POL:
        try:
            pola = {f.name for f in dataclasses.fields(type(kontrolka))}
        except TypeError:
            pola = set()
        _CACHE_POL[klucz] = next((k for k in kandydaci if k in pola), kandydaci[-1])
    return _CACHE_POL[klucz]


def ustaw_blad(kontrolka, komunikat=None):
    """Komunikat błędu pod polem. TextField/Checkbox mają `error`, Dropdown
    `error_text` — a we wcześniejszych wersjach Fleta wszystkie miały
    `error_text`. Podaj None (albo nic), żeby błąd wyczyścić."""
    setattr(kontrolka, _nazwa_pola(kontrolka, "error_text", "error"), komunikat or None)


def blad_kontrolki(kontrolka):
    """Aktualny komunikat błędu kontrolki albo None."""
    return getattr(kontrolka, _nazwa_pola(kontrolka, "error_text", "error"), None)


def ustaw_ikone(kontrolka, ikona):
    """Podmiana ikony już zbudowanej kontrolki (`icon`, wcześniej `name`)."""
    setattr(kontrolka, _nazwa_pola(kontrolka, "icon", "name"), ikona)


def ustaw_tekst_przycisku(przycisk, tekst):
    """Napis na przycisku (`text`, w nowszych wersjach `content`)."""
    setattr(przycisk, _nazwa_pola(przycisk, "text", "content"), tekst)


__all__ = [
    "_CACHE_POL",
    "_nazwa_pola",
    "blad_kontrolki",
    "ustaw_blad",
    "ustaw_ikone",
    "ustaw_tekst_przycisku",
]
