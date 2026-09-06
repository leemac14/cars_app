"""Drobne funkcje pomocnicze bez zależności — parsowanie i formatowanie liczb."""

import re


# Podzespoły założone przez STARSZE wersje aplikacji mają emoji w nazwie
# ("🛢️ Olej silnikowy i filtr"). Nie ruszamy tych rekordów — zamiast migracji
# bazy porównujemy nazwy po normalizacji, dzięki czemu pakiety serwisowe
# trafiają zarówno w stare, jak i w nowe wpisy.
_WZORZEC_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\u2190-\u21FF\u2300-\u27BF\u2B00-\u2BFF\uFE0F\u200D]"
)


def bez_emoji(tekst):
    """Nazwa oczyszczona z emoji i nadmiarowych spacji — do PORÓWNYWANIA nazw,
    nigdy do zapisu (nie przepisujemy użytkownikowi jego własnych wpisów)."""
    return re.sub(r"\s+", " ", _WZORZEC_EMOJI.sub("", str(tekst or ""))).strip()


def _liczba_lub_none(tekst):
    """Pola specyfikacji są tekstowe (użytkownik wpisuje '52 kWh' albo '52,5'),
    więc wyciągamy z nich liczbę tak samo pobłażliwie, jak import CSV."""
    wartosc = _parsuj_liczbe_csv(tekst)
    return wartosc if (wartosc and wartosc > 0) else None


def parsuj_int_bezpiecznie(wartosc, domyslna=0):
    try:
        return int(wartosc)
    except (TypeError, ValueError):
        return domyslna


def formatuj_liczba_eksport(wartosc, decimale=2):
    """Prosty format liczbowy do plików eksportu (przecinek jako separator dziesiętny,
    zgodnie z polskim Excelem, bez separatora tysięcy)."""
    if wartosc is None or wartosc == "":
        return ""
    try:
        wartosc = float(wartosc)
    except (TypeError, ValueError):
        return str(wartosc)
    if decimale > 0:
        return f"{wartosc:.{decimale}f}".replace(".", ",")
    return str(int(round(wartosc)))


def _parsuj_liczbe_csv(tekst):
    """Odporny parser liczby z arkusza: '1 234,56', '1,234.56', '12.5', '12,5',
    '45,20 zł'. Zwraca float albo None. Celowo bez regexpów — pojedyncze przejście
    po znakach jest tu czytelniejsze i szybsze niż wzorzec."""
    if tekst is None:
        return None
    s = str(tekst).replace("\u00a0", " ").strip()
    if not s:
        return None
    s = "".join(znak for znak in s if znak in "0123456789,.-")
    if not s or s in ("-", ".", ",", "-.", "-,"):
        return None
    if "," in s and "." in s:
        # O roli separatora decyduje ten, który stoi bliżej końca.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


__all__ = [
    "_WZORZEC_EMOJI",
    "_liczba_lub_none",
    "_parsuj_liczbe_csv",
    "bez_emoji",
    "formatuj_liczba_eksport",
    "parsuj_int_bezpiecznie",
]
