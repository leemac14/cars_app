"""Wyszukiwanie globalne, w tym zapytania kwotowe."""

import re
import sqlite3
from datetime import date as Data, datetime, timedelta

from date import parsuj_date

from .polaczenie import polacz_baze
from .pomocnicze import formatuj_liczba_eksport
from .ustawienia import pobierz_walute


# Zapytanie kwotowe rozpoznajemy WPROST w polu wyszukiwarki — bez dodatkowych
# kontrolek, tak jak „>1000” czy „200-500” pisze się w arkuszu kalkulacyjnym.
# Sam tekst dalej działa jak dotąd; kwota to tylko dodatkowa ścieżka.
_WZORZEC_ZAKRESU = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(?:-|–|—|\.\.|do)\s*(\d+(?:[.,]\d+)?)$")

_WZORZEC_POROWNANIA = re.compile(r"^(>=|<=|>|<|od|do)\s*(\d+(?:[.,]\d+)?)$", re.IGNORECASE)

_WZORZEC_LICZBY = re.compile(r"^(\d+(?:[.,]\d+)?)$")


# Tolerancja dla „szukam kwoty około tyle”: paragon rzadko pamięta się co do
# grosza, więc samo „450” łapie 441–459 zamiast wyłącznie równych 450.
TOLERANCJA_KWOTY = 0.02


def _na_liczbe(tekst):
    try:
        return float(str(tekst).replace("\xa0", "").replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def parsuj_zapytanie_kwotowe(zapytanie) -> tuple[float | None, float | None, str] | None:
    """Rozpoznaje zapytanie o kwotę i zwraca (min, max, opis) albo None.

    Obsługiwane formy: „450” (±2%), „>1000”, „>=1000”, „<50”, „<=50”,
    „200-500” (też z półpauzą, „..” i słowem „do”), „od 200”, „do 500”.
    """
    tekst = " ".join(str(zapytanie or "").split())
    if not tekst:
        return None

    dopasowanie = _WZORZEC_ZAKRESU.match(tekst)
    if dopasowanie:
        a, b = _na_liczbe(dopasowanie.group(1)), _na_liczbe(dopasowanie.group(2))
        if a is None or b is None:
            return None
        dolna, gorna = min(a, b), max(a, b)
        return (dolna, gorna, f"kwota od {formatuj_liczba_eksport(dolna, 2)} do {formatuj_liczba_eksport(gorna, 2)}")

    dopasowanie = _WZORZEC_POROWNANIA.match(tekst)
    if dopasowanie:
        operator = dopasowanie.group(1).lower()
        wartosc = _na_liczbe(dopasowanie.group(2))
        if wartosc is None:
            return None
        if operator in (">", ">=", "od"):
            return (wartosc, None, f"kwota od {formatuj_liczba_eksport(wartosc, 2)}")
        return (None, wartosc, f"kwota do {formatuj_liczba_eksport(wartosc, 2)}")

    dopasowanie = _WZORZEC_LICZBY.match(tekst)
    if dopasowanie:
        wartosc = _na_liczbe(dopasowanie.group(1))
        if wartosc is None:
            return None
        margines = max(wartosc * TOLERANCJA_KWOTY, 0.5)
        return (wartosc - margines, wartosc + margines,
                f"kwota około {formatuj_liczba_eksport(wartosc, 2)}")

    return None


# ============================================================================
#  Zapytania datowe i operatory pól
# ============================================================================
# `parsuj_zapytanie_kwotowe` pokazało, że najtańsza wyszukiwarka to ta bez
# dodatkowych kontrolek: wzorzec rozpoznawany WPROST w polu tekstowym, a gdy nic
# nie pasuje — cichy powrót do szukania tekstowego. Ten sam schemat obsługuje
# teraz daty („marzec 2026”, „ostatni tydzień”) i pola („stacja:orlen”).
#
# Zasada, której trzymają się wszystkie wzorce: rozpoznajemy tylko to, co NIE
# może być zwykłym słowem z danych. Dlatego lista form miesiąca jest zamknięta
# („listwa” zaczyna się od „lis”, ale listopadem nie jest), nazwa spoza mapy
# POLA_WYSZUKIWANIA zostaje zwykłym tekstem, a sama liczba jest kwotą wyłącznie
# wtedy, gdy stanowi CAŁE zapytanie — „opony 205” dalej szuka tekstu.

_BEZ_OGONKOW = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")

_NAZWY_MIESIECY = (
    "styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec",
    "lipiec", "sierpień", "wrzesień", "październik", "listopad", "grudzień",
)

# Mianownik, dopełniacz, miejscownik i skrót — formy, w których miesiąc naprawdę
# bywa wpisywany. Zapis bez ogonków, bo porównujemy po `_uprosc`.
_MIESIACE_FORMY = {
    1: ("styczen", "stycznia", "styczniu", "sty"),
    2: ("luty", "lutego", "lutym", "lut"),
    3: ("marzec", "marca", "marcu", "mar"),
    4: ("kwiecien", "kwietnia", "kwietniu", "kwi"),
    5: ("maj", "maja", "maju"),
    6: ("czerwiec", "czerwca", "czerwcu", "cze"),
    7: ("lipiec", "lipca", "lipcu", "lip"),
    8: ("sierpien", "sierpnia", "sierpniu", "sie"),
    9: ("wrzesien", "wrzesnia", "wrzesniu", "wrz"),
    10: ("pazdziernik", "pazdziernika", "pazdzierniku", "paz"),
    11: ("listopad", "listopada", "listopadzie", "lis"),
    12: ("grudzien", "grudnia", "grudniu", "gru"),
}

_MIESIACE = {forma: numer for numer, formy in _MIESIACE_FORMY.items() for forma in formy}

# Skróty działają tylko z rokiem („lis 2026”). Samo „lis” albo „sie” to za
# często zwykłe słowo, żeby na jego widok przełączać wyszukiwarkę w tryb daty.
_SKROTY_MIESIECY = {"sty", "lut", "mar", "kwi", "cze", "lip", "sie", "wrz", "paz", "lis", "gru"}

# Alias -> pole. Nazwa spoza tej mapy NIE jest operatorem, więc „http://x” albo
# „rozmiar:225” bez obsługi zostaje zwykłym tekstem zamiast szukać pustki.
POLA_WYSZUKIWANIA = {
    "stacja": "stacja", "stacje": "stacja", "stacji": "stacja",
    "tag": "tag", "tagi": "tag", "tagu": "tag",
    "kategoria": "kategoria", "kategorie": "kategoria", "kategorii": "kategoria", "kat": "kategoria",
    "warsztat": "warsztat", "warsztaty": "warsztat", "wykonawca": "warsztat", "mechanik": "warsztat",
    "notatka": "notatka", "notatki": "notatka", "uwaga": "notatka", "uwagi": "notatka",
    "typ": "typ", "rodzaj": "typ",
    "nazwa": "nazwa", "tytul": "nazwa",
    "opis": "opis",
    "priorytet": "priorytet",
    "sezon": "sezon",
    "jednostka": "jednostka",
}

# Podpowiedzi pod polem wyszukiwarki. Trzymane przy parserze, bo to JEDYNE
# miejsce, które wie, co naprawdę jest rozpoznawane — rozjechana ściągawka
# obiecuje składnię, której nie ma.
PRZYKLADY_SKLADNI = (
    ("marzec 2026", "miesiąc"),
    ("ostatni tydzień", "7 dni"),
    ("stacja:", "stacja"),
    ("tag:", "tag"),
    ("kategoria:", "kategoria"),
    ("typ:", "rodzaj wpisu"),
    (">1000", "kwota"),
)

_WZORZEC_POLA = re.compile(
    r"(?<![^\s])([A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]{2,}):\s*(\"[^\"]+\"|'[^']+'|\S+)"
)

_WZORZEC_DNIA = re.compile(r"^(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})$")
_WZORZEC_DNIA_ODWROTNIE = re.compile(r"^(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})$")
_WZORZEC_MIESIACA = re.compile(r"^(\d{1,2})[.\-/](\d{4})$")
_WZORZEC_MIESIACA_ODWROTNIE = re.compile(r"^(\d{4})[.\-/](\d{1,2})$")
# Rok potrzebuje słowa „rok” — sam „2026” zostaje kwotą, bo w tej aplikacji
# równie dobrze bywa ceną naprawy. Dwukropek („rok:2026”) wolno, żeby zapis
# wyglądał jak pozostałe operatory.
_WZORZEC_ROKU = re.compile(r"^(?:rok|roku|r)\.?\s*:?\s*(\d{4})$|^(\d{4})\s*(?:rok|roku|r)\.?$")
_WZORZEC_OSTATNICH = re.compile(r"^ostatni(?:e|ch|ego|m)?\s+(\d{1,3})\s+([a-z]+)$")
_WZORZEC_OD = re.compile(r"^(?:od|po)\s+(.+)$")
_WZORZEC_DO = re.compile(r"^(?:do|przed)\s+(.+)$")

# Rozdzielacze zakresu dat. „-” jest ostatnie, bo bywa też w samej dacie
# („01-03-2026”) — próbujemy nim dzielić dopiero, gdy nic innego nie pasowało.
_ROZDZIELACZE_ZAKRESU = ("..", "—", "–", " do ", "-")

# Ile słów może zająć jedno polecenie: „ostatnie 12 miesięcy” to trzy,
# „01.01.2026 - 31.03.2026” po rozdzieleniu spacjami też.
_MAKS_SLOW_POLECENIA = 4


def _uprosc(tekst):
    """Małe litery bez polskich znaków — „Opłaty” i „oplaty” to jedno słowo."""
    return str(tekst or "").translate(_BEZ_OGONKOW).casefold().strip()


def _dzis():
    return datetime.now().date()


def _tekst_daty(d):
    return d.strftime("%d.%m.%Y")


def _bezpieczna_data(rok, miesiac, dzien):
    """Data albo None — „31.02.2026” ma wrócić do szukania tekstowego."""
    try:
        return Data(rok, miesiac, dzien)
    except ValueError:
        return None


def _koniec_miesiaca(rok, miesiac):
    if miesiac == 12:
        return Data(rok, 12, 31)
    return Data(rok, miesiac + 1, 1) - timedelta(days=1)


def _wczesniej_o_miesiace(d, ile):
    """Ta sama data `ile` miesięcy wcześniej; 31 marca minus miesiąc to 28 lutego."""
    rok, miesiac = d.year, d.month - ile
    while miesiac <= 0:
        miesiac += 12
        rok -= 1
    return Data(rok, miesiac, min(d.day, _koniec_miesiaca(rok, miesiac).day))


def _zakres_miesiaca(rok, miesiac):
    return (Data(rok, miesiac, 1), _koniec_miesiaca(rok, miesiac),
            f"{_NAZWY_MIESIECY[miesiac - 1]} {rok}")


def _zakres_roku(rok):
    return (Data(rok, 1, 1), Data(rok, 12, 31), f"rok {rok}")


def _numer_miesiaca(slowo, dozwolone_skroty):
    numer = _MIESIACE.get(slowo)
    if numer is None:
        return None
    if not dozwolone_skroty and slowo in _SKROTY_MIESIECY:
        return None
    return numer


def _punkt_daty(tekst):
    """Pojedynczy punkt na osi czasu jako (początek, koniec, opis).

    Punktem jest dzień, miesiąc albo rok — „01.03.2026”, „marzec 2026”, „2026”
    z dopiskiem „rok”. Koniec jest ostatnim dniem tego okresu, więc zakres
    „styczeń - marzec” obejmuje cały marzec, a nie tylko pierwszy dzień."""
    tekst = _uprosc(tekst)
    if not tekst:
        return None

    dopasowanie = _WZORZEC_DNIA.match(tekst) or _WZORZEC_DNIA_ODWROTNIE.match(tekst)
    if dopasowanie:
        liczby = [int(x) for x in dopasowanie.groups()]
        rok, miesiac, dzien = (liczby[2], liczby[1], liczby[0]) if len(str(liczby[0])) <= 2 else liczby
        d = _bezpieczna_data(rok, miesiac, dzien)
        return (d, d, _tekst_daty(d)) if d else None

    dopasowanie = _WZORZEC_MIESIACA.match(tekst)
    if dopasowanie:
        miesiac, rok = int(dopasowanie.group(1)), int(dopasowanie.group(2))
        return _zakres_miesiaca(rok, miesiac) if 1 <= miesiac <= 12 else None

    dopasowanie = _WZORZEC_MIESIACA_ODWROTNIE.match(tekst)
    if dopasowanie:
        rok, miesiac = int(dopasowanie.group(1)), int(dopasowanie.group(2))
        return _zakres_miesiaca(rok, miesiac) if 1 <= miesiac <= 12 else None

    dopasowanie = _WZORZEC_ROKU.match(tekst)
    if dopasowanie:
        return _zakres_roku(int(dopasowanie.group(1) or dopasowanie.group(2)))

    slowa = tekst.split()
    if len(slowa) == 2 and slowa[1].isdigit() and len(slowa[1]) == 4:
        numer = _numer_miesiaca(slowa[0], dozwolone_skroty=True)
        if numer:
            return _zakres_miesiaca(int(slowa[1]), numer)
    if len(slowa) == 1:
        numer = _numer_miesiaca(slowa[0], dozwolone_skroty=False)
        if numer:
            # Sam „marzec” to ostatni marzec, który już był: w listopadzie
            # pytanie o marzec dotyczy tego roku, w styczniu — poprzedniego.
            dzis = _dzis()
            return _zakres_miesiaca(dzis.year if numer <= dzis.month else dzis.year - 1, numer)
    return None


def _zakres_wzgledny(tekst):
    """„ostatni tydzień”, „ten miesiąc”, „zeszły rok” — okna liczone od dziś.

    „ostatni X” to okno kończące się DZIŚ (ostatnie 30 dni), „zeszły X” to
    poprzedni pełny okres kalendarzowy. Pasek trybu pokazuje, co wyszło."""
    dzis = _dzis()

    if tekst in ("dzis", "dzisiaj"):
        return (dzis, dzis, "dzisiaj")
    if tekst == "wczoraj":
        d = dzis - timedelta(days=1)
        return (d, d, "wczoraj")
    if tekst == "przedwczoraj":
        d = dzis - timedelta(days=2)
        return (d, d, "przedwczoraj")

    if tekst in ("ten tydzien", "biezacy tydzien", "w tym tygodniu"):
        return (dzis - timedelta(days=dzis.weekday()), dzis, "ten tydzień")
    if tekst in ("ten miesiac", "biezacy miesiac", "w tym miesiacu"):
        return (dzis.replace(day=1), dzis, "ten miesiąc")
    if tekst in ("ten rok", "biezacy rok", "w tym roku"):
        return (Data(dzis.year, 1, 1), dzis, "ten rok")

    if tekst in ("ostatni tydzien", "ostatnim tygodniu", "ostatniego tygodnia"):
        return (dzis - timedelta(days=6), dzis, "ostatnie 7 dni")
    if tekst in ("ostatni miesiac", "ostatnim miesiacu", "ostatniego miesiaca"):
        return (dzis - timedelta(days=29), dzis, "ostatnie 30 dni")
    if tekst in ("ostatni kwartal", "ostatnim kwartale"):
        return (dzis - timedelta(days=89), dzis, "ostatnie 90 dni")
    if tekst in ("ostatni rok", "ostatnim roku", "ostatniego roku"):
        return (_wczesniej_o_miesiace(dzis, 12) + timedelta(days=1), dzis, "ostatnie 12 mies.")

    if tekst in ("zeszly tydzien", "poprzedni tydzien", "ubiegly tydzien"):
        koniec = dzis - timedelta(days=dzis.weekday() + 1)
        return (koniec - timedelta(days=6), koniec, "zeszły tydzień")
    if tekst in ("zeszly miesiac", "poprzedni miesiac", "ubiegly miesiac"):
        koniec = dzis.replace(day=1) - timedelta(days=1)
        return _zakres_miesiaca(koniec.year, koniec.month)
    if tekst in ("zeszly rok", "poprzedni rok", "ubiegly rok"):
        return _zakres_roku(dzis.year - 1)

    dopasowanie = _WZORZEC_OSTATNICH.match(tekst)
    if dopasowanie:
        ile, jednostka = int(dopasowanie.group(1)), dopasowanie.group(2)
        if ile < 1:
            return None
        if jednostka.startswith(("dni", "dzien", "dnia")):
            return (dzis - timedelta(days=ile - 1), dzis, f"ostatnie {ile} dni")
        if jednostka.startswith("tygod"):
            return (dzis - timedelta(days=ile * 7 - 1), dzis, f"ostatnie {ile} tyg.")
        if jednostka.startswith("miesi"):
            return (_wczesniej_o_miesiace(dzis, ile) + timedelta(days=1), dzis,
                    f"ostatnie {ile} mies.")
        if jednostka.startswith(("lat", "lata", "rok")):
            return (_wczesniej_o_miesiace(dzis, ile * 12) + timedelta(days=1), dzis,
                    f"ostatnie {ile * 12} mies.")
    return None


def _zakres_z_dwoch_punktow(tekst):
    """„01.01.2026-31.03.2026”, „styczeń .. marzec 2026”."""
    for rozdzielacz in _ROZDZIELACZE_ZAKRESU:
        if rozdzielacz not in tekst:
            continue
        czesci = tekst.split(rozdzielacz)
        for podzial in range(1, len(czesci)):
            lewy = _punkt_daty(rozdzielacz.join(czesci[:podzial]))
            prawy = _punkt_daty(rozdzielacz.join(czesci[podzial:]))
            if lewy and prawy:
                poczatek, koniec = min(lewy[0], prawy[0]), max(lewy[1], prawy[1])
                return (poczatek, koniec, f"od {_tekst_daty(poczatek)} do {_tekst_daty(koniec)}")
    return None


def parsuj_zapytanie_datowe(zapytanie) -> tuple[Data | None, Data | None, str] | None:
    """Rozpoznaje zapytanie o datę i zwraca (od, do, opis) albo None.

    Obsługiwane formy: „marzec 2026”, „marca 2026”, „mar 2026”, sam „marzec”,
    „03.2026”, „2026-03”, „rok 2026”, „01.03.2026”, „od 01.03.2026”,
    „do 31.03.2026”, „01.01.2026-31.03.2026”, „dziś”, „wczoraj”, „ten
    tydzień/miesiąc/rok”, „ostatni tydzień/miesiąc/kwartał/rok”, „ostatnie N
    dni/tygodni/miesięcy/lat”, „zeszły tydzień/miesiąc/rok”.

    Sam czterocyfrowy rok BEZ słowa „rok” zostaje kwotą — „2026” w tej
    aplikacji równie dobrze bywa ceną naprawy."""
    tekst = _uprosc(" ".join(str(zapytanie or "").split()))
    if not tekst:
        return None

    wzgledny = _zakres_wzgledny(tekst)
    if wzgledny:
        return wzgledny

    punkt = _punkt_daty(tekst)
    if punkt:
        return punkt

    dopasowanie = _WZORZEC_OD.match(tekst)
    if dopasowanie:
        punkt = _punkt_daty(dopasowanie.group(1))
        if punkt:
            return (punkt[0], None, f"od {_tekst_daty(punkt[0])}")

    dopasowanie = _WZORZEC_DO.match(tekst)
    if dopasowanie:
        punkt = _punkt_daty(dopasowanie.group(1))
        if punkt:
            return (None, punkt[1], f"do {_tekst_daty(punkt[1])}")

    return _zakres_z_dwoch_punktow(tekst)


def _wytnij_pola(tekst):
    """Zwraca (lista (pole, szukana wartość), tekst bez rozpoznanych operatorów)."""
    pola = []

    def zamien(dopasowanie):
        pole = POLA_WYSZUKIWANIA.get(_uprosc(dopasowanie.group(1)))
        wartosc = _uprosc(dopasowanie.group(2).strip("\"'"))
        if not pole or not wartosc:
            return dopasowanie.group(0)
        pola.append((pole, wartosc))
        return " "

    reszta = _WZORZEC_POLA.sub(zamien, tekst)
    return pola, " ".join(reszta.split())


def _wytnij_polecenie(slowa, rozpoznaj):
    """Wycina z zapytania NAJDŁUŻSZY fragment, który `rozpoznaj` umie odczytać.

    Dzięki temu „olej marzec 2026” rozpada się na filtr daty i słowo „olej”,
    a „marzec 2026” nie zatrzymuje się na samym „marzec”."""
    for dlugosc in range(min(_MAKS_SLOW_POLECENIA, len(slowa)), 0, -1):
        for poczatek in range(0, len(slowa) - dlugosc + 1):
            rozpoznane = rozpoznaj(" ".join(slowa[poczatek:poczatek + dlugosc]))
            if rozpoznane:
                return rozpoznane, slowa[:poczatek] + slowa[poczatek + dlugosc:]
    return None, slowa


def _kwota_jawna(fragment):
    """Kwota rozpoznana tylko wtedy, gdy ma operator albo zakres.

    Sama liczba w zapytaniu złożonym zostaje tekstem: „opony 205” to rozmiar,
    a nie 205 zł. Samą liczbą jako kwotą zajmuje się `parsuj_zapytanie`, gdy
    stanowi CAŁE zapytanie."""
    if _WZORZEC_LICZBY.match(fragment.strip()):
        return None
    return parsuj_zapytanie_kwotowe(fragment)


def _opis_filtrow(pola, data, kwota, tekst):
    czesci = []
    if tekst:
        czesci.append(f"„{tekst}”")
    czesci.extend(f"{pole}: {wartosc}" for pole, wartosc in pola)
    if data:
        czesci.append(data[2])
    if kwota:
        czesci.append(kwota[2])
    return " · ".join(czesci)


def parsuj_zapytanie(zapytanie) -> dict | None:
    """Rozkłada zapytanie na filtry albo zwraca None, gdy nie ma czego rozkładać.

    Wynik: {pola, data, kwota, tekst, opis}. `pola` to lista (pole, wartość),
    `data` i `kwota` to krotki z parserów, `tekst` to reszta do szukania
    tekstowego. None znaczy „zwykłe zapytanie tekstowe” — wołający ma wtedy
    robić dokładnie to, co robił dotąd.

    Filtry się SUMUJĄ: „stacja:orlen marzec 2026 >200” to trzy warunki naraz.
    Kwota jest ostatnia w opisie, bo pasek trybu dopisuje za nią walutę."""
    tekst = " ".join(str(zapytanie or "").split())
    if not tekst:
        return None

    pola, reszta = _wytnij_pola(tekst)

    slowa = reszta.split()
    data, slowa = _wytnij_polecenie(slowa, parsuj_zapytanie_datowe)

    # Całe zapytanie jest kwotą — ścieżka sprzed zapytań datowych, nietknięta.
    # Data ma pierwszeństwo, bo „03.2026” to marzec, a nie 3,20 zł; sama liczba
    # („450”, „200-500”) i tak nie przejdzie przez parser dat.
    if not pola and not data:
        sama_kwota = parsuj_zapytanie_kwotowe(reszta)
        if sama_kwota:
            return {"pola": [], "data": None, "kwota": sama_kwota, "tekst": "",
                    "opis": _opis_filtrow([], None, sama_kwota, "")}

    kwota, slowa = _wytnij_polecenie(slowa, _kwota_jawna)
    reszta = " ".join(slowa)

    if not pola and not data and not kwota:
        return None
    return {"pola": pola, "data": data, "kwota": kwota, "tekst": reszta,
            "opis": _opis_filtrow(pola, data, kwota, reszta)}


def _w_zakresie(wartosc, dolna, gorna):
    if wartosc is None:
        return False
    try:
        wartosc = float(wartosc)
    except (TypeError, ValueError):
        return False
    if dolna is not None and wartosc < dolna - 1e-9:
        return False
    if gorna is not None and wartosc > gorna + 1e-9:
        return False
    return True


def wyszukiwanie_po_kwocie(auto_id, dolna, gorna):
    """Przeszukuje WSZYSTKIE kwoty pojazdu: tankowania, wpisy serwisowe, wizyty,
    inne koszty, ceny w magazynie i oponach, szacunki z listy Do zrobienia oraz
    wydatki cykliczne. Zwraca ten sam kształt wyników, co globalne_wyszukiwanie."""
    if not auto_id or (dolna is None and gorna is None):
        return []

    waluta = pobierz_walute()
    wyniki = []

    def dodaj(typ, tytul, kwota, opis, data, trasa, **extra):
        if not _w_zakresie(kwota, dolna, gorna):
            return
        pelny_opis = f"{formatuj_liczba_eksport(kwota, 2)} {waluta}"
        if opis:
            pelny_opis += f" • {opis}"
        wpis = {"typ": typ, "tytul": tytul, "opis": pelny_opis, "data": data or "", "trasa": trasa}
        wpis.update(extra)
        wyniki.append(wpis)

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("SELECT id, data, kwota, litry, stacja FROM tankowania WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            opis = f"{formatuj_liczba_eksport(r['litry'], 1)} L"
            if r["stacja"]:
                opis += f" • {r['stacja']}"
            dodaj("Tankowanie", r["stacja"] or "Tankowanie", r["kwota"], opis,
                  r["data"], f"/tankowanie/edytuj/{r['id']}")

        c.execute(
            "SELECT h.id, h.data, h.cena, h.wykonawca, z.nazwa FROM historia h "
            "JOIN zadania z ON h.zadanie_id=z.id WHERE z.auto_id=? AND h.wizyta_id IS NULL",
            (auto_id,)
        )
        for r in c.fetchall():
            dodaj("Serwis", str(r["nazwa"]), r["cena"], r["wykonawca"] or "",
                  r["data"], f"/wpis/edytuj/{r['id']}")

        c.execute(
            "SELECT w.id, w.data, w.koszt_calkowity, w.wykonawca, "
            "GROUP_CONCAT(z.nazwa, ', ') AS czesci FROM wizyty w "
            "LEFT JOIN historia h ON h.wizyta_id=w.id LEFT JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE w.auto_id=? GROUP BY w.id",
            (auto_id,)
        )
        for r in c.fetchall():
            opis = str(r["czesci"] or "Brak podpiętych części")
            if r["wykonawca"]:
                opis += f" • {r['wykonawca']}"
            dodaj("Wizyta zbiorcza", "Wizyta w warsztacie", r["koszt_calkowity"], opis,
                  r["data"], f"/wizyty/edytuj/{r['id']}")

        c.execute("SELECT id, data, nazwa, kwota, kategoria, tagi FROM inne_koszty WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            dodaj("Inny koszt", str(r["nazwa"] or "Koszt"), r["kwota"],
                  str(r["kategoria"] or r["tagi"] or ""), r["data"], f"/inne/edytuj/{r['id']}")

        c.execute("SELECT id, nazwa, cena, ilosc, jednostka FROM magazyn_czesci WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            dodaj("Magazyn", str(r["nazwa"]), r["cena"],
                  f"{formatuj_liczba_eksport(r['ilosc'], 2)} {r['jednostka'] or 'szt'}", "", "/magazyn")

        c.execute("SELECT id, sezon, rozmiar, marka_model, cena, data_zakupu FROM zestawy_opon WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            opis = str(r["rozmiar"] or "")
            if r["marka_model"]:
                opis += f" • {r['marka_model']}" if opis else str(r["marka_model"])
            dodaj("Opony", f"Zestaw: {r['sezon']}", r["cena"], opis, r["data_zakupu"], "/magazyn")

        c.execute("SELECT id, tytul, szacowany_koszt, termin, priorytet FROM do_zrobienia WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            dodaj("Do zrobienia", str(r["tytul"]), r["szacowany_koszt"],
                  f"szacunek • {r['priorytet'] or 'bez priorytetu'}",
                  r["termin"], f"/do-zrobienia/edytuj/{r['id']}")

        c.execute("SELECT id, nazwa, kwota, okres_dni, nastepna_data, czy_koszt FROM wydatki_cykliczne WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            if not r["czy_koszt"]:
                continue
            dodaj("Wydatek cykliczny", str(r["nazwa"]), r["kwota"],
                  f"co {int(r['okres_dni'] or 0)} dni", r["nastepna_data"], "__wydatki_cykliczne__")

    wyniki.sort(key=lambda w: parsuj_date(w["data"]), reverse=True)
    return wyniki


def skrot_notatki(tekst, maks=60):
    """Notatka w jednej linii wyniku wyszukiwania — bez tego długa uwaga
    rozpychałaby kartę wyniku i zasłaniała resztę opisu."""
    tekst = " ".join(str(tekst or "").split())
    if not tekst:
        return ""
    return tekst if len(tekst) <= maks else tekst[:maks - 1].rstrip() + "…"


def _wpis(typ, tytul, podpis, data, trasa, kwota=None, tekst_dodatkowy="", **pola):
    """Jeden rekord dla wyszukiwania po filtrach: część jawna (ta sama, co
    zawsze) plus pola, po których wolno filtrować, i tekst do szukania.

    `podpis` to widoczny opis wyniku — nazwa `opis` jest zajęta przez POLE
    o tej nazwie (`opis:` w zapytaniu). `tekst_dodatkowy` wchodzi tylko do
    szukania tekstowego: pozycje checklisty czy numer DOT opony nie mieszczą
    się na karcie wyniku, ale szuka się po nich jak najbardziej."""
    pola = {klucz: str(wartosc or "") for klucz, wartosc in pola.items()}
    pola.setdefault("nazwa", str(tytul or ""))
    pola["typ"] = typ
    return {
        "typ": typ, "tytul": str(tytul or ""), "opis": str(podpis or ""),
        "data": data or "", "trasa": trasa,
        "_kwota": kwota, "_pola": pola,
        "_tekst": " ".join(x for x in [str(tytul or ""), str(podpis or ""), str(data or ""),
                                       str(tekst_dodatkowy or ""), *pola.values()] if x),
    }


def _wszystkie_wpisy(auto_id):
    """WSZYSTKIE dane pojazdu jako jednolite rekordy — bez filtrowania w SQL.

    Zapytanie z filtrami („stacja:orlen marzec 2026 >200”) porównuje kilka
    warunków naraz, a każdy dotyczy innej kolumny w innej tabeli. Złożenie tego
    w SQL to trzynaście zapytań z doklejanym WHERE; pobranie wszystkiego raz
    i przefiltrowanie w Pythonie kosztuje przy danych jednego auta tyle samo,
    a warunki dają się dowolnie łączyć. Szukanie po samym tekście dalej idzie
    przez LIKE — tam SQL odsiewa od razu i nie ma czego zmieniać."""
    wpisy = []

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("SELECT id, data, przebieg, kwota, litry, stacja, tagi, notatka "
                  "FROM tankowania WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            opis = f"{int(r['przebieg'] or 0)} km" + (f" • {r['stacja']}" if r["stacja"] else "")
            if r["notatka"]:
                opis += f" • {skrot_notatki(r['notatka'])}"
            wpisy.append(_wpis("Tankowanie", r["stacja"] or "Tankowanie", opis, r["data"],
                               f"/tankowanie/edytuj/{r['id']}", kwota=r["kwota"],
                               stacja=r["stacja"], tag=r["tagi"], notatka=r["notatka"]))

        c.execute("SELECT h.id, h.data, h.przebieg, h.cena, h.wykonawca, h.kategoria, h.notatka, "
                  "z.nazwa FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
                  "WHERE z.auto_id=? AND h.wizyta_id IS NULL", (auto_id,))
        for r in c.fetchall():
            opis = f"{int(r['przebieg'] or 0)} km" + (f" • {r['wykonawca']}" if r["wykonawca"] else "")
            if r["notatka"]:
                opis += f" • {skrot_notatki(r['notatka'])}"
            wpisy.append(_wpis("Serwis", r["nazwa"], opis, r["data"], f"/wpis/edytuj/{r['id']}",
                               kwota=r["cena"], kategoria=r["kategoria"], warsztat=r["wykonawca"],
                               notatka=r["notatka"]))

        c.execute("SELECT w.id, w.data, w.wykonawca, w.koszt_calkowity, w.notatki, w.tagi, "
                  "GROUP_CONCAT(z.nazwa, ', ') AS czesci FROM wizyty w "
                  "LEFT JOIN historia h ON h.wizyta_id=w.id LEFT JOIN zadania z ON h.zadanie_id=z.id "
                  "WHERE w.auto_id=? GROUP BY w.id", (auto_id,))
        for r in c.fetchall():
            opis = str(r["czesci"] or "Brak podpiętych części") + (f" • {r['wykonawca']}" if r["wykonawca"] else "")
            wpisy.append(_wpis("Wizyta zbiorcza", "Wizyta w warsztacie", opis, r["data"],
                               f"/wizyty/edytuj/{r['id']}", kwota=r["koszt_calkowity"],
                               warsztat=r["wykonawca"], tag=r["tagi"], notatka=r["notatki"],
                               nazwa=f"Wizyta w warsztacie {r['czesci'] or ''}"))

        c.execute("SELECT id, data, nazwa, kwota, kategoria, tagi, notatka FROM inne_koszty "
                  "WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            opis = str(r["kategoria"] or r["tagi"] or "Inny koszt")
            if r["notatka"]:
                opis += f" • {skrot_notatki(r['notatka'])}"
            wpisy.append(_wpis("Inny koszt", r["nazwa"] or "Koszt", opis, r["data"],
                               f"/inne/edytuj/{r['id']}", kwota=r["kwota"],
                               kategoria=r["kategoria"], tag=r["tagi"], notatka=r["notatka"]))

        c.execute("SELECT id, tytul, opis, priorytet, szacowany_koszt, termin "
                  "FROM do_zrobienia WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            wpisy.append(_wpis("Do zrobienia", r["tytul"], r["opis"] or r["priorytet"] or "",
                               r["termin"], f"/do-zrobienia/edytuj/{r['id']}",
                               kwota=r["szacowany_koszt"], opis=r["opis"],
                               priorytet=r["priorytet"]))

        c.execute("SELECT id, data, przebieg, notatka FROM odczyty_przebiegu WHERE auto_id=?",
                  (auto_id,))
        for r in c.fetchall():
            wpisy.append(_wpis("Odczyt licznika",
                               f"{formatuj_liczba_eksport(r['przebieg'] or 0, 0)} km",
                               skrot_notatki(r["notatka"]), r["data"], "/przebieg",
                               notatka=r["notatka"]))

        c.execute("SELECT id, nazwa, kategoria, ilosc, jednostka, cena, data_zakupu, notatki "
                  "FROM magazyn_czesci WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            opis = f"{formatuj_liczba_eksport(r['ilosc'], 2)} {r['jednostka'] or 'szt'}"
            if r["kategoria"]:
                opis += f" • {r['kategoria']}"
            wpisy.append(_wpis("Magazyn", r["nazwa"], opis, r["data_zakupu"], "/magazyn",
                               kwota=r["cena"], kategoria=r["kategoria"],
                               jednostka=r["jednostka"], notatka=r["notatki"]))

        c.execute("SELECT id, sezon, rozmiar, marka_model, numer_dot, cena, data_zakupu, notatki "
                  "FROM zestawy_opon WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            opis = str(r["rozmiar"] or "") + (f" • {r['marka_model']}" if r["marka_model"] else "")
            wpisy.append(_wpis("Opony", f"Zestaw: {r['sezon']}", opis, r["data_zakupu"], "/magazyn",
                               kwota=r["cena"], sezon=r["sezon"], notatka=r["notatki"],
                               tekst_dodatkowy=r["numer_dot"],
                               nazwa=f"{r['rozmiar'] or ''} {r['marka_model'] or ''}"))

        c.execute("SELECT id, nazwa, telefon, adres, notatki FROM warsztaty WHERE auto_id=?",
                  (auto_id,))
        for r in c.fetchall():
            opis = str(r["adres"] or "") + (f" • {r['telefon']}" if r["telefon"] else "")
            wpisy.append(_wpis("Warsztat", r["nazwa"], opis or "Brak telefonu / adresu", "",
                               "/wizyty", warsztat=r["nazwa"], notatka=r["notatki"]))

        c.execute("SELECT id, nazwa, kwota, okres_dni, nastepna_data, czy_koszt "
                  "FROM wydatki_cykliczne WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            if r["czy_koszt"]:
                opis = f"co {int(r['okres_dni'] or 0)} dni"
            else:
                opis = f"Przypomnienie • co {int(r['okres_dni'] or 0)} dni"
            wpisy.append(_wpis("Wydatek cykliczny", r["nazwa"], opis, r["nastepna_data"],
                               "__wydatki_cykliczne__",
                               kwota=r["kwota"] if r["czy_koszt"] else None))

        c.execute("SELECT id, nazwa, dystans, powrot, osoby, notatki FROM trasy_szablony "
                  "WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            opis = f"{formatuj_liczba_eksport(r['dystans'], 0)} km"
            if r["powrot"]:
                opis += " • tam i z powrotem"
            opis += f" • {int(r['osoby'] or 1)} os."
            wpisy.append(_wpis("Zapisana trasa", r["nazwa"], opis, "", "/kalkulator",
                               notatka=r["notatki"]))

        c.execute("SELECT l.id, l.nazwa, l.opis, l.ostatnie_uzycie, "
                  "       (SELECT COUNT(*) FROM checklisty_pozycje p WHERE p.checklista_id = l.id) AS razem, "
                  "       (SELECT COUNT(*) FROM checklisty_pozycje p WHERE p.checklista_id = l.id AND p.odhaczone=1) AS zrobione, "
                  "       (SELECT GROUP_CONCAT(p.tresc, ', ') FROM checklisty_pozycje p WHERE p.checklista_id = l.id) AS pozycje "
                  "FROM checklisty l WHERE l.auto_id=?", (auto_id,))
        for r in c.fetchall():
            wpisy.append(_wpis("Checklista", r["nazwa"],
                               f"odhaczone {int(r['zrobione'] or 0)} z {int(r['razem'] or 0)}",
                               r["ostatnie_uzycie"], "__checklisty__",
                               opis=r["opis"], tekst_dodatkowy=r["pozycje"]))

        c.execute("SELECT id, nazwa, interwal_km, interwal_miesiace FROM zadania WHERE auto_id=?",
                  (auto_id,))
        for r in c.fetchall():
            czesci = []
            if r["interwal_km"]:
                czesci.append(f"co {int(r['interwal_km'])} km")
            if r["interwal_miesiace"]:
                czesci.append(f"co {int(r['interwal_miesiace'])} mies.")
            wpisy.append(_wpis("Podzespół", r["nazwa"],
                               " • ".join(czesci) if czesci else "Brak ustawionego interwału",
                               "", f"/historia/{r['id']}"))

    return wpisy


def _pasuje_do_filtrow(wpis, filtr):
    if filtr["kwota"] and not _w_zakresie(wpis["_kwota"], filtr["kwota"][0], filtr["kwota"][1]):
        return False

    if filtr["data"]:
        data = parsuj_date(wpis["data"])
        # Rekord bez czytelnej daty (warsztat, zapisana trasa) nie może trafić
        # w żaden zakres — inaczej „marzec 2026” pokazywałby całą książkę adresową.
        if data.year <= 1:
            return False
        if filtr["data"][0] and data < filtr["data"][0]:
            return False
        if filtr["data"][1] and data > filtr["data"][1]:
            return False

    for pole, wartosc in filtr["pola"]:
        if wartosc not in _uprosc(wpis["_pola"].get(pole, "")):
            return False

    if filtr["tekst"]:
        cel = _uprosc(wpis["_tekst"])
        if not all(slowo in cel for slowo in _uprosc(filtr["tekst"]).split()):
            return False

    return True


def wyszukiwanie_zaawansowane(auto_id, filtr):
    """Wyniki dla zapytania z filtrami z `parsuj_zapytanie`.

    Zwraca ten sam kształt, co `globalne_wyszukiwanie` — {typ, tytul, opis,
    data, trasa} — z dopisaną kwotą w opisie tam, gdzie wpis jakąś ma."""
    if not auto_id or not filtr:
        return []

    waluta = pobierz_walute()
    wyniki = []

    for wpis in _wszystkie_wpisy(auto_id):
        if not _pasuje_do_filtrow(wpis, filtr):
            continue
        opis = wpis["opis"]
        if wpis["_kwota"] is not None:
            kwota = f"{formatuj_liczba_eksport(wpis['_kwota'], 2)} {waluta}"
            opis = f"{opis} • {kwota}" if opis else kwota
        wyniki.append({"typ": wpis["typ"], "tytul": wpis["tytul"], "opis": opis,
                       "data": wpis["data"], "trasa": wpis["trasa"]})

    wyniki.sort(key=lambda w: parsuj_date(w["data"]), reverse=True)
    return wyniki


def globalne_wyszukiwanie(auto_id, zapytanie):
    """Przeszukuje jednocześnie tankowania, historię serwisową, wizyty zbiorcze,
    inne koszty, notatki wpisów oraz listę Do zrobienia BIEŻĄCEGO pojazdu. Używane przez widok
    /szukaj — jedną wspólną wyszukiwarkę dostępną z paska głównego, w odróżnieniu
    od lokalnych pól filtruj_* działających tylko na już wczytanej liście.
    Zwraca listę słowników {typ, tytul, opis, data, trasa}, posortowaną malejąco
    po dacie (nierozpoznane daty lądują na końcu)."""
    if not auto_id or not zapytanie or not zapytanie.strip():
        return []

    # Zapytanie z rozpoznanym filtrem („450”, „>1000”, „marzec 2026”,
    # „stacja:orlen”) idzie zupełnie inną ścieżką: porównujemy liczby, daty
    # i konkretne pola, a nie tekst. Bez tego „450” trafiało tylko tam, gdzie
    # ten ciąg przypadkiem był w dacie albo nazwie. Sama kwota zostaje przy
    # swojej dotychczasowej ścieżce — jej wyniki pokazują kwotę na pierwszym
    # miejscu opisu i tak mają zostać.
    filtr = parsuj_zapytanie(zapytanie)
    if filtr:
        if filtr["kwota"] and not filtr["pola"] and not filtr["data"] and not filtr["tekst"]:
            return wyszukiwanie_po_kwocie(auto_id, filtr["kwota"][0], filtr["kwota"][1])
        return wyszukiwanie_zaawansowane(auto_id, filtr)

    q = f"%{zapytanie.strip()}%"
    wyniki = []

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute(
            "SELECT id, data, przebieg, stacja, tagi, notatka FROM tankowania "
            "WHERE auto_id=? AND (stacja LIKE ? OR tagi LIKE ? OR data LIKE ? OR notatka LIKE ?)",
            (auto_id, q, q, q, q)
        )
        for r in c.fetchall():
            opis = f"{int(r['przebieg'] or 0)} km" + (f" • {r['stacja']}" if r["stacja"] else "")
            if r["notatka"]:
                opis += f" • {skrot_notatki(r['notatka'])}"
            wyniki.append({
                "typ": "Tankowanie", "tytul": r["stacja"] or "Tankowanie", "opis": opis,
                "data": r["data"], "trasa": f"/tankowanie/edytuj/{r['id']}",
            })

        c.execute(
            "SELECT h.id, h.data, h.przebieg, h.wykonawca, h.kategoria, h.notatka, z.nazwa "
            "FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE z.auto_id=? AND h.wizyta_id IS NULL AND "
            "(z.nazwa LIKE ? OR h.wykonawca LIKE ? OR h.kategoria LIKE ? OR h.data LIKE ? OR h.notatka LIKE ?)",
            (auto_id, q, q, q, q, q)
        )
        for r in c.fetchall():
            opis = f"{int(r['przebieg'] or 0)} km" + (f" • {r['wykonawca']}" if r["wykonawca"] else "")
            if r["notatka"]:
                opis += f" • {skrot_notatki(r['notatka'])}"
            wyniki.append({
                "typ": "Serwis", "tytul": str(r["nazwa"]), "opis": opis,
                "data": r["data"], "trasa": f"/wpis/edytuj/{r['id']}",
            })

        # Podzespoły jako samodzielna kategoria: świeżo dodany podzespół BEZ
        # historii wymiany nie wypadłby z JOIN-a powyżej. Jedno zapytanie na
        # tabelę — drugie, dopisane obok, dublowało każdy trafiony podzespół.
        c.execute(
            "SELECT id, nazwa, interwal_km, interwal_miesiace FROM zadania "
            "WHERE auto_id=? AND nazwa LIKE ?",
            (auto_id, q)
        )
        for r in c.fetchall():
            bits = []
            if r["interwal_km"]:
                bits.append(f"co {int(r['interwal_km'])} km")
            if r["interwal_miesiace"]:
                bits.append(f"co {int(r['interwal_miesiace'])} mies.")
            opis = " • ".join(bits) if bits else "Brak ustawionego interwału"
            wyniki.append({
                "typ": "Podzespół", "tytul": str(r["nazwa"]), "opis": opis,
                "data": "", "trasa": f"/historia/{r['id']}",
            })

        c.execute(
            "SELECT w.id, w.data, w.wykonawca, w.notatki, w.tagi, "
            "GROUP_CONCAT(z.nazwa, ', ') as czesci "
            "FROM wizyty w LEFT JOIN historia h ON h.wizyta_id=w.id LEFT JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE w.auto_id=? GROUP BY w.id "
            "HAVING (w.wykonawca LIKE ? OR w.notatki LIKE ? OR w.tagi LIKE ? OR w.data LIKE ? OR czesci LIKE ?)",
            (auto_id, q, q, q, q, q)
        )
        for r in c.fetchall():
            opis = str(r["czesci"] or "Brak podpiętych części") + (f" • {r['wykonawca']}" if r["wykonawca"] else "")
            wyniki.append({
                "typ": "Wizyta zbiorcza", "tytul": "Wizyta w warsztacie", "opis": opis,
                "data": r["data"], "trasa": f"/wizyty/edytuj/{r['id']}",
            })

        c.execute(
            "SELECT id, data, nazwa, kategoria, tagi, notatka FROM inne_koszty "
            "WHERE auto_id=? AND (nazwa LIKE ? OR kategoria LIKE ? OR tagi LIKE ? OR data LIKE ? OR notatka LIKE ?)",
            (auto_id, q, q, q, q, q)
        )
        for r in c.fetchall():
            opis = str(r["kategoria"] or r["tagi"] or "Inny koszt")
            if r["notatka"]:
                opis += f" • {skrot_notatki(r['notatka'])}"
            wyniki.append({
                "typ": "Inny koszt", "tytul": str(r["nazwa"] or "Koszt"), "opis": opis,
                "data": r["data"], "trasa": f"/inne/edytuj/{r['id']}",
            })

        c.execute(
            "SELECT id, tytul, opis, priorytet, termin FROM do_zrobienia "
            "WHERE auto_id=? AND (tytul LIKE ? OR opis LIKE ? OR priorytet LIKE ?)",
            (auto_id, q, q, q)
        )
        for r in c.fetchall():
            wyniki.append({
                "typ": "Do zrobienia", "tytul": str(r["tytul"]), "opis": str(r["opis"] or r["priorytet"] or ""),
                "data": r["termin"] or "", "trasa": f"/do-zrobienia/edytuj/{r['id']}",
            })

        # Odczyty licznika trafiają do wyników WYŁĄCZNIE przez notatkę: sam
        # „12.03.2026 • 145 000 km” nie niesie treści, po której ktoś szuka,
        # ale zostawiona przy nim uwaga („licznik po wymianie zegarów”) — owszem.
        c.execute(
            "SELECT id, data, przebieg, notatka FROM odczyty_przebiegu "
            "WHERE auto_id=? AND notatka LIKE ?",
            (auto_id, q)
        )
        for r in c.fetchall():
            wyniki.append({
                "typ": "Odczyt licznika",
                "tytul": f"{formatuj_liczba_eksport(r['przebieg'] or 0, 0)} km",
                "opis": skrot_notatki(r["notatka"]),
                "data": r["data"], "trasa": "/przebieg",
            })

        # NOWE: Magazyn (części i płyny) — było obiecane w podpowiedzi wyszukiwarki
        # ("część"), ale dotąd nieprzeszukiwane.
        c.execute(
            "SELECT id, nazwa, kategoria, ilosc, jednostka FROM magazyn_czesci "
            "WHERE auto_id=? AND (nazwa LIKE ? OR kategoria LIKE ?)",
            (auto_id, q, q)
        )
        for r in c.fetchall():
            opis = f"{formatuj_liczba_eksport(r['ilosc'], 2)} {r['jednostka'] or 'szt'}" + (f" • {r['kategoria']}" if r["kategoria"] else "")
            wyniki.append({
                "typ": "Magazyn", "tytul": str(r["nazwa"]), "opis": opis,
                "data": "", "trasa": "/magazyn",
            })

        # NOWE: Zestawy opon
        c.execute(
            "SELECT id, sezon, rozmiar, marka_model, numer_dot FROM zestawy_opon "
            "WHERE auto_id=? AND (sezon LIKE ? OR rozmiar LIKE ? OR marka_model LIKE ? OR numer_dot LIKE ?)",
            (auto_id, q, q, q, q)
        )
        for r in c.fetchall():
            opis = str(r["rozmiar"] or "") + (f" • {r['marka_model']}" if r["marka_model"] else "")
            wyniki.append({
                "typ": "Opony", "tytul": f"Zestaw: {r['sezon']}", "opis": opis,
                "data": "", "trasa": "/magazyn",
            })

        # NOWE: Warsztaty
        c.execute(
            "SELECT id, nazwa, telefon, adres, notatki FROM warsztaty "
            "WHERE auto_id=? AND (nazwa LIKE ? OR telefon LIKE ? OR adres LIKE ? OR notatki LIKE ?)",
            (auto_id, q, q, q, q)
        )
        for r in c.fetchall():
            opis = str(r["adres"] or "") + (f" • {r['telefon']}" if r["telefon"] else "")
            wyniki.append({
                "typ": "Warsztat", "tytul": str(r["nazwa"]), "opis": opis or "Brak telefonu / adresu",
                "data": "", "trasa": "/wizyty",
            })

        # NOWE: Wydatki cykliczne
        c.execute(
            "SELECT id, nazwa, kwota, okres_dni, nastepna_data, czy_koszt FROM wydatki_cykliczne "
            "WHERE auto_id=? AND nazwa LIKE ?",
            (auto_id, q)
        )
        for r in c.fetchall():
            if r["czy_koszt"]:
                opis = f"{formatuj_liczba_eksport(r['kwota'], 2)} {pobierz_walute()} • co {int(r['okres_dni'] or 0)} dni"
            else:
                opis = f"Przypomnienie • co {int(r['okres_dni'] or 0)} dni"
            wyniki.append({
                "typ": "Wydatek cykliczny", "tytul": str(r["nazwa"]), "opis": opis,
                "data": r["nastepna_data"] or "", "trasa": "__wydatki_cykliczne__",
            })

        # Zapisane trasy kalkulatora i checklisty — szuka się ich po nazwie
        # („teściów”, „przed zimą”), a bez tego były jedynymi danymi pojazdu
        # niewidocznymi dla wyszukiwarki.
        c.execute(
            "SELECT id, nazwa, dystans, powrot, osoby FROM trasy_szablony "
            "WHERE auto_id=? AND (nazwa LIKE ? OR notatki LIKE ?)",
            (auto_id, q, q)
        )
        for r in c.fetchall():
            opis = f"{formatuj_liczba_eksport(r['dystans'], 0)} km"
            if r["powrot"]:
                opis += " • tam i z powrotem"
            opis += f" • {int(r['osoby'] or 1)} os."
            wyniki.append({
                "typ": "Zapisana trasa", "tytul": str(r["nazwa"]), "opis": opis,
                "data": "", "trasa": "/kalkulator",
            })

        c.execute(
            "SELECT l.id, l.nazwa, l.ostatnie_uzycie, "
            "       (SELECT COUNT(*) FROM checklisty_pozycje p WHERE p.checklista_id = l.id) AS razem, "
            "       (SELECT COUNT(*) FROM checklisty_pozycje p WHERE p.checklista_id = l.id AND p.odhaczone=1) AS zrobione "
            "FROM checklisty l WHERE l.auto_id=? AND (l.nazwa LIKE ? OR l.opis LIKE ? OR EXISTS "
            "   (SELECT 1 FROM checklisty_pozycje p WHERE p.checklista_id = l.id AND p.tresc LIKE ?))",
            (auto_id, q, q, q)
        )
        for r in c.fetchall():
            wyniki.append({
                "typ": "Checklista", "tytul": str(r["nazwa"]),
                "opis": f"odhaczone {int(r['zrobione'] or 0)} z {int(r['razem'] or 0)}",
                "data": r["ostatnie_uzycie"] or "", "trasa": "__checklisty__",
            })

    wyniki.sort(key=lambda w: parsuj_date(w["data"]), reverse=True)

    return wyniki


__all__ = [
    "POLA_WYSZUKIWANIA",
    "PRZYKLADY_SKLADNI",
    "TOLERANCJA_KWOTY",
    "_BEZ_OGONKOW",
    "_MAKS_SLOW_POLECENIA",
    "_MIESIACE",
    "_MIESIACE_FORMY",
    "_NAZWY_MIESIECY",
    "_ROZDZIELACZE_ZAKRESU",
    "_SKROTY_MIESIECY",
    "_WZORZEC_DNIA",
    "_WZORZEC_DNIA_ODWROTNIE",
    "_WZORZEC_DO",
    "_WZORZEC_LICZBY",
    "_WZORZEC_MIESIACA",
    "_WZORZEC_MIESIACA_ODWROTNIE",
    "_WZORZEC_OD",
    "_WZORZEC_OSTATNICH",
    "_WZORZEC_POLA",
    "_WZORZEC_POROWNANIA",
    "_WZORZEC_ROKU",
    "_WZORZEC_ZAKRESU",
    "_bezpieczna_data",
    "_dzis",
    "_koniec_miesiaca",
    "_kwota_jawna",
    "_na_liczbe",
    "_numer_miesiaca",
    "_opis_filtrow",
    "_pasuje_do_filtrow",
    "_punkt_daty",
    "_tekst_daty",
    "_uprosc",
    "_w_zakresie",
    "_wczesniej_o_miesiace",
    "_wpis",
    "_wszystkie_wpisy",
    "_wytnij_pola",
    "_wytnij_polecenie",
    "_zakres_miesiaca",
    "_zakres_roku",
    "_zakres_wzgledny",
    "_zakres_z_dwoch_punktow",
    "globalne_wyszukiwanie",
    "parsuj_zapytanie",
    "parsuj_zapytanie_datowe",
    "parsuj_zapytanie_kwotowe",
    "skrot_notatki",
    "wyszukiwanie_po_kwocie",
    "wyszukiwanie_zaawansowane",
]
