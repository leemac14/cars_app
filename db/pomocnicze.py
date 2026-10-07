"""Drobne funkcje pomocnicze, zależne tylko od stałych — parsowanie i formatowanie
liczb, klucz porównawczy nazw oraz zdanie o notatce „najlepsza oferta OC/AC”."""

import math
import re

from .stale import ETYKIETA_OFERTY_OC_AC


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


# Jak klucz_stacji, ale szerzej: „Filtr oleju”, „filtr Oleju” i „filtr oleju ” to jedna
# nazwa (magazyn, tagi, warsztaty, podzespoły). Klucz WYŁĄCZNIE do porównań — w bazie
# zostaje pisownia użytkownika. Tutaj, a nie w `nazwy`, bo używa go też analiza
# (ładowana przed `nazwy`).
def klucz_nazwy(tekst):
    """Klucz porównawczy nazwy: bez emoji, bez wielkości liter, ze scalonymi
    białymi znakami i bez interpunkcji na brzegach."""
    czysty = bez_emoji(tekst)
    return " ".join(czysty.split()).lower().strip(" .,;:-_/")


def normalizuj_nazwe(tekst):
    """Pisownia gotowa do ZAPISU: scalone spacje i obcięte brzegi. Nie zmienia
    wielkości liter ani treści — użytkownik ma prawo do swojej pisowni, chodzi
    tylko o to, żeby „filtr oleju ” i „filtr  oleju” nie były różnymi wpisami."""
    return " ".join(str(tekst or "").split()).strip()


def _liczba_lub_none(tekst):
    """Pola specyfikacji są tekstowe (użytkownik wpisuje '52 kWh' albo '52,5'),
    więc wyciągamy z nich liczbę tak samo pobłażliwie, jak import CSV."""
    wartosc = _parsuj_liczbe_csv(tekst)
    return wartosc if (wartosc and wartosc > 0) else None


def _dodatnia(wartosc):
    """Liczba całkowita > 0 albo None — puste pole i zero znaczą „nie ustawiono”."""
    try:
        liczba = int(float(wartosc))
    except (TypeError, ValueError):
        return None
    return liczba if liczba > 0 else None


def parsuj_int_bezpiecznie(wartosc, domyslna=0):
    try:
        return int(wartosc)
    except (TypeError, ValueError):
        return domyslna


# Separator tysięcy używany na ekranie. W eksporcie go NIE ma — polski Excel
# rozumie przecinek dziesiętny, ale spacja w liczbie robi z niej tekst.
SEPARATOR_TYSIECY = " "


def _na_liczbe(wartosc):
    """float albo None („to nie liczba”). Przyjmuje też polskie teksty ('1 234,56',
    '45,20 zł') tym samym parserem co import CSV; co pokazać przy None, decyduje
    wołający."""
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
    """JEDYNE miejsce, w którym liczba zamienia się w tekst (zaokrąglenie, przecinek,
    separator tysięcy). None, gdy wejście nie jest liczbą (`_na_liczbe`)."""
    liczba = _na_liczbe(wartosc)
    if liczba is None:
        return None
    # „-0,00” po zaokrągleniu drobnego minusa (saldo rozliczeń, różnica
    # dwóch kwot) to zero — minus przed nim tylko myli.
    if round(liczba, max(decimale, 0)) == 0:
        liczba = 0.0

    tekst = f"{liczba:,.{decimale}f}" if decimale > 0 else f"{round(liczba):,}"
    calosc, _, ulamek = tekst.partition(".")
    calosc = calosc.replace(",", separator_tysiecy)
    return f"{calosc},{ulamek}" if ulamek else calosc


def formatuj_liczba_eksport(wartosc, decimale=2):
    """Liczba do pliku eksportu: przecinek, bez separatora tysięcy. Brak wartości →
    PUSTA komórka, nie zero; tekst nieliczbowy przechodzi bez zmian."""
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



def odmien(liczba, jeden, dwa, wiele):
    """Polska odmiana przez liczbę: 1 wpis, 2 wpisy, 5 wpisów, 12 wpisów, 22 wpisy.

    Jedno miejsce dla warstwy danych i interfejsu (`utils._odmiana_liczby` woła
    właśnie tę funkcję). Świadoma kopia żyje w `log.odmien` — log nie importuje
    niczego z projektu, więc tamtej nie da się usunąć."""
    liczba = abs(parsuj_int_bezpiecznie(liczba, 0))
    if liczba == 1:
        return jeden
    if 2 <= liczba % 10 <= 4 and not 12 <= liczba % 100 <= 14:
        return dwa
    return wiele


def liczba_z_odmiana(liczba, jeden, dwa, wiele):
    """„1 wpis”, „3 wpisy”, „1 234 wpisów” — liczba ze spacją co trzy cyfry
    i rzeczownikiem w formie zgodnej z tą liczbą."""
    return f"{liczba_na_tekst(liczba, 0, SEPARATOR_TYSIECY) or liczba} {odmien(liczba, jeden, dwa, wiele)}"


def opis_terminu_dni(zostalo):
    """Termin w dniach jako zdanie: „Został 1 dzień”, „Zostały 3 dni”,
    „Zostało 12 dni”, „Termin mija dziś”, „Przekroczono o 1 dzień”.

    Wspólne dla powiadomień i kondycji — obie mówią o tych samych terminach
    i nie mogą się różnić jednym „dni” przy jedynce."""
    zostalo = parsuj_int_bezpiecznie(zostalo, 0)
    if zostalo < 0:
        return f"Przekroczono o {liczba_z_odmiana(-zostalo, 'dzień', 'dni', 'dni')}"
    if zostalo == 0:
        return "Termin mija dziś"
    return f"{odmien(zostalo, 'Został', 'Zostały', 'Zostało')} {liczba_z_odmiana(zostalo, 'dzień', 'dni', 'dni')}"


def oferta_w_jednej_linii(tekst, limit=140):
    """Notatka o ofercie w jednej linii, do miejsc bez miejsca na kilka wierszy
    (powiadomienie, wiersz odliczania, kafel): puste linie znikają, kolejne są
    sklejone „ · ”, nadmiar — ucięty wielokropkiem. Pełny tekst zostaje na
    Karcie pojazdu i w formularzu."""
    linie = (" ".join(linia.split()) for linia in str(tekst or "").splitlines())
    jedna = " · ".join(linia for linia in linie if linia)
    if limit and len(jedna) > limit:
        jedna = jedna[:limit - 1].rstrip() + "…"
    return jedna


def zdanie_oferty_oc_ac(tekst, data=None):
    """„Najlepsza oferta OC/AC: Warta 1 240 zł · zapisano 03.10.2026” albo ""
    przy pustej notatce. Jedno zdanie dla wszystkich miejsc, które pokazują
    notatkę obok terminu, żeby żadne nie mówiło jej po swojemu; data zapisu
    mówi, czy to porównanie z tego roku, czy zeszłoroczne."""
    jedna = oferta_w_jednej_linii(tekst)
    if not jedna:
        return ""
    zdanie = f"{ETYKIETA_OFERTY_OC_AC}: {jedna}"
    return f"{zdanie} · zapisano {data}" if data else zdanie


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
    "klucz_nazwy",
    "liczba_na_tekst",
    "liczba_z_odmiana",
    "normalizuj_nazwe",
    "odmien",
    "oferta_w_jednej_linii",
    "opis_terminu_dni",
    "parsuj_int_bezpiecznie",
    "zdanie_oferty_oc_ac",
]
