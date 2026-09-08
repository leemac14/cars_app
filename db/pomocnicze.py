"""Drobne funkcje pomocnicze bez zależności — parsowanie i formatowanie liczb."""

import math
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


# Separator tysięcy używany na ekranie. W eksporcie go NIE ma — polski Excel
# rozumie przecinek dziesiętny, ale spacja w liczbie robi z niej tekst.
SEPARATOR_TYSIECY = " "


def _na_liczbe(wartosc):
    """float albo None. Przyjmuje liczby i teksty zapisane po polsku ('1 234,56',
    '45,20 zł') — tym samym parserem, co import CSV, żeby jedna wartość nie
    czytała się różnie zależnie od tego, kto ją formatuje.

    None znaczy „to nie jest liczba". Decyzję, co wtedy pokazać, podejmuje
    wołający: ekran woli zero, eksport — pustą komórkę."""
    if isinstance(wartosc, bool):
        return float(wartosc)
    if isinstance(wartosc, (int, float)):
        liczba = float(wartosc)
    else:
        liczba = _parsuj_liczbe_csv(wartosc)
        if liczba is None:
            return None
    # nan i inf to nie są liczby do pokazania: `f"{nan:,.2f}"` daje „nan", a po
    # doklejeniu przecinka dziesiętnego — „nan,".
    return liczba if math.isfinite(liczba) else None


def liczba_na_tekst(wartosc, decimale=2, separator_tysiecy=""):
    """JEDYNE miejsce, w którym liczba zamienia się w tekst.

    Zaokrąglenie, przecinek dziesiętny i separator tysięcy siedzą tu raz —
    wcześniej ekran, eksport i generator grafiki miały po własnej kopii tych
    trzech linijek. Zaokrąglenia akurat się zgadzały, ale zgadzały się
    przypadkiem: nic ich nie trzymało razem.

    Zwraca None, gdy wejście nie jest liczbą (patrz `_na_liczbe`)."""
    liczba = _na_liczbe(wartosc)
    if liczba is None:
        return None

    tekst = f"{liczba:,.{decimale}f}" if decimale > 0 else f"{round(liczba):,}"
    calosc, _, ulamek = tekst.partition(".")
    calosc = calosc.replace(",", separator_tysiecy)
    return f"{calosc},{ulamek}" if ulamek else calosc


def formatuj_liczba_eksport(wartosc, decimale=2):
    """Liczba do pliku eksportu: przecinek dziesiętny, bez separatora tysięcy.

    Brak wartości daje PUSTĄ komórkę, nie zero — w arkuszu to są dwie różne
    rzeczy, a suma kolumny z dopisanymi zerami kłamie o średniej. Tekst, który
    nie jest liczbą, przechodzi bez zmian: w eksporcie bywają kolumny opisowe."""
    if wartosc is None or wartosc == "":
        return ""
    tekst = liczba_na_tekst(wartosc, decimale)
    if tekst is not None:
        return tekst
    # Tekst, który liczbą nie jest, przechodzi bez zmian. Liczba nie do
    # pokazania (nan, inf) daje pustą komórkę — „nan" w arkuszu nie znaczy nic.
    return wartosc if isinstance(wartosc, str) else ""


def formatuj_rozmiar(bajty):
    """Rozmiar w bajtach po ludzku: „512 B", „48,2 kB", „3,1 MB".

    Ta sama zasada co przy liczbach — jedno miejsce zamiast trzech. Świadomy
    wyjątek: `log.formatuj_rozmiar` ma własną kopię, bo `log.py` nie importuje
    niczego z projektu. Zgodność obu pilnuje test."""
    bajty = parsuj_int_bezpiecznie(bajty, 0)
    if bajty < 1024:
        return f"{bajty} B"
    if bajty < 1024 * 1024:
        return f"{liczba_na_tekst(bajty / 1024, 1)} kB"
    return f"{liczba_na_tekst(bajty / (1024 * 1024), 1)} MB"



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
    "SEPARATOR_TYSIECY",
    "_WZORZEC_EMOJI",
    "_liczba_lub_none",
    "_na_liczbe",
    "_parsuj_liczbe_csv",
    "bez_emoji",
    "formatuj_liczba_eksport",
    "formatuj_rozmiar",
    "liczba_na_tekst",
    "parsuj_int_bezpiecznie",
]
