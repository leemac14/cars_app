"""Stacje paliw, trend cen i podział kosztów."""

import math
from date import na_iso, parsuj_date
from datetime import datetime
from typing import Any

from .stale import KATEGORIA_INNE_DOMYSLNA, KATEGORIE_INNYCH_KOSZTOW
from .polaczenie import polacz_baze
from .pomocnicze import _na_liczbe, bez_emoji
from .energia import domyslny_rodzaj_energii

KATEGORIE_BUDZETU = {
    "paliwo": "Paliwo i energia",
    "serwis": "Serwis",
    "inne": "Inne koszty",
    "razem": "Wszystko razem",
}


# Średnia długość miesiąca w dniach — prognozy przeliczają miesiące na dni,
# żeby niepełny miesiąc bieżący nie zaniżał wyniku.
DNI_W_MIESIACU = 30.44


def _wiersze_kosztow(conn, auto_id):
    """(data, kwota, kategoria) wszystkich kosztów pojazdu — jedno źródło dla
    budżetów, prognoz i podsumowania roku. Wizyta zbiorcza wchodzi jako CAŁOŚĆ,
    a należące do niej wpisy historii są pomijane, żeby ten sam koszt nie
    policzył się dwa razy (tak samo jak w eksporcie i na osi czasu)."""
    c = conn.cursor()
    wiersze = []
    c.execute("SELECT data, kwota FROM tankowania WHERE auto_id=?", (auto_id,))
    wiersze += [(d, k, "paliwo") for d, k in c.fetchall()]
    c.execute(
        "SELECT h.data, h.cena FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
        "WHERE z.auto_id=? AND h.wizyta_id IS NULL", (auto_id,)
    )
    wiersze += [(d, k, "serwis") for d, k in c.fetchall()]
    c.execute("SELECT data, koszt_calkowity FROM wizyty WHERE auto_id=?", (auto_id,))
    wiersze += [(d, k, "serwis") for d, k in c.fetchall()]
    c.execute("SELECT data, kwota FROM inne_koszty WHERE auto_id=?", (auto_id,))
    wiersze += [(d, k, "inne") for d, k in c.fetchall()]
    return wiersze


# ---------------------------------------------------------------------------
# Kategorie wewnątrz „Innych kosztów”
# ---------------------------------------------------------------------------
# Rozbicie worka „inne” — przede wszystkim opłaty drogowe, które rosną z KILOMETRAMI, a
# nie z wiekiem auta.


def etykieta_kategorii_innych(wartosc):
    """Kategoria wpisu w formie do pokazania. Puste pole (tak zapisywały wpisy
    przed wprowadzeniem słownika) czyta się jako „Ogólne”; wartość spoza
    słownika zostaje, jaka jest — może pochodzić z importu CSV albo ze starszej
    wersji i nie ma powodu jej gubić."""
    tekst = str(wartosc or "").strip()
    return tekst or KATEGORIA_INNE_DOMYSLNA


def pobierz_koszty_innych_wg_kategorii(auto_id, od_data=None, do_data=None) -> list[tuple[str, float, int]]:
    """[(kategoria, suma, liczba_wpisow)] posortowane malejąco po sumie.
    Kategorie bez ani jednego wpisu w okresie się nie pojawiają — pusta pozycja
    w rozbiciu tylko rozprasza."""
    if not auto_id:
        return []
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT data, kwota, kategoria FROM inne_koszty WHERE auto_id=?", (auto_id,))
        wiersze = c.fetchall()

    sumy, liczby = {}, {}
    for data_str, kwota, kategoria in wiersze:
        d = parsuj_date(data_str)
        if d == datetime.min.date():
            continue
        if (od_data and d < od_data) or (do_data and d > do_data):
            continue
        etykieta = etykieta_kategorii_innych(kategoria)
        sumy[etykieta] = sumy.get(etykieta, 0.0) + float(kwota or 0.0)
        liczby[etykieta] = liczby.get(etykieta, 0) + 1

    kolejnosc = {k: i for i, k in enumerate(KATEGORIE_INNYCH_KOSZTOW)}
    return sorted(
        ((k, v, liczby[k]) for k, v in sumy.items()),
        key=lambda p: (-p[1], kolejnosc.get(p[0], len(kolejnosc)), p[0]),
    )


def suma_kategorii_innych(auto_id, kategoria, od_data=None, do_data=None):
    """Suma i liczba wpisów jednej kategorii — dla kafelka kokpitu."""
    for nazwa, suma, liczba in pobierz_koszty_innych_wg_kategorii(auto_id, od_data, do_data):
        if nazwa == kategoria:
            return {"kategoria": nazwa, "suma": suma, "liczba": liczba}
    return {"kategoria": kategoria, "suma": 0.0, "liczba": 0}


def koszty_w_okresie(auto_id, od_data=None, do_data=None):
    """Koszty pojazdu w przedziale dat (włącznie, oba końce opcjonalne),
    rozbite na kategorie budżetu. Zwraca komplet kluczy — także zerowych —
    więc wołający nie musi sprawdzać, czy coś w danej kategorii w ogóle było."""
    wynik = {k: 0.0 for k in KATEGORIE_BUDZETU}
    if not auto_id:
        return wynik

    with polacz_baze() as conn:
        wiersze = _wiersze_kosztow(conn, auto_id)

    for data_str, kwota, kategoria in wiersze:
        d = parsuj_date(data_str)
        if d == datetime.min.date():
            continue
        if od_data and d < od_data:
            continue
        if do_data and d > do_data:
            continue
        wartosc = float(kwota or 0.0)
        wynik[kategoria] += wartosc
        wynik["razem"] += wartosc
    return wynik


def siatka_miesiecy(liczba_miesiecy, dzisiaj=None):
    """Kolejne (rok, miesiac) od najstarszego do bieżącego WŁĄCZNIE.

    Jedna siatka dla kosztów i dla kilometrów — tylko dlatego obie listy da się
    zestawić pozycja w pozycję, bez dopasowywania po kluczu."""
    dzis = dzisiaj or datetime.now()
    klucze = []
    for i in range(liczba_miesiecy - 1, -1, -1):
        m, y = dzis.month - i, dzis.year
        while m <= 0:
            m += 12
            y -= 1
        klucze.append((y, m))
    return klucze


def pobierz_koszty_miesieczne_wg_kategorii(auto_id, liczba_miesiecy=6) -> list[tuple[int, int, dict[str, float]]]:
    """Koszty kolejnych miesięcy w ROZBICIU na kategorie: [(rok, miesiac, {paliwo,
    serwis, inne, razem})] rosnąco; miesiąc bez wydatków ma zera (ta sama siatka dla
    krzywych kategorii i razem na wykresie kosztu na 1000 km)."""
    if not auto_id:
        return []

    klucze = siatka_miesiecy(liczba_miesiecy)
    sumy = {k: {kat: 0.0 for kat in KATEGORIE_BUDZETU} for k in klucze}

    with polacz_baze() as conn:
        wiersze = _wiersze_kosztow(conn, auto_id)

    for data_str, kwota, kategoria in wiersze:
        d = parsuj_date(data_str)
        if d == datetime.min.date():
            continue
        klucz = (d.year, d.month)
        if klucz in sumy:
            wartosc = float(kwota or 0.0)
            sumy[klucz][kategoria] += wartosc
            sumy[klucz]["razem"] += wartosc

    return [(y, m, sumy[(y, m)]) for (y, m) in klucze]


def pobierz_koszty_miesieczne(auto_id, liczba_miesiecy=6) -> list[tuple[int, int, float]]:
    """Suma kosztów (paliwo + serwis + inne) z ostatnich `liczba_miesiecy` miesięcy z
    bieżącym: [(rok, miesiac, suma)] rosnąco, puste miesiące 0.0. Mini-wykres kokpitu."""
    return [(y, m, kwoty["razem"])
            for y, m, kwoty in pobierz_koszty_miesieczne_wg_kategorii(auto_id, liczba_miesiecy)]


def pobierz_koszt_miesiaca_do_dnia(auto_id, rok, miesiac, do_dnia):
    """Suma kosztów miesiąca TYLKO do dnia `do_dnia` włącznie — do uczciwego porównania
    z tym samym okresem poprzedniego miesiąca (niepełny miesiąc kontra CAŁY dawał
    fałszywe „spada o 95%”)."""
    if not auto_id:
        return 0.0

    suma = 0.0
    with polacz_baze() as conn:
        wiersze = _wiersze_kosztow(conn, auto_id)

    for data_str, kwota, _kategoria in wiersze:
        d = parsuj_date(data_str)
        if d == datetime.min.date():
            continue
        if d.year == rok and d.month == miesiac and d.day <= do_dnia:
            suma += float(kwota or 0.0)

    return suma


def klucz_stacji(nazwa):
    """Klucz porównawczy nazw stacji — bez wielkości liter, bez nadmiarowych
    spacji i bez końcowej interpunkcji. Dzięki temu 'Orlen', 'orlen  ' i
    'ORLEN.' to jedna i ta sama stacja w rankingu cen i w podpowiedziach."""
    tekst = " ".join((nazwa or "").split()).lower()
    return tekst.strip(" .,;:-")


def pobierz_stacje_paliw(auto_id) -> list[str]:
    """Słownik stacji z dotychczasowych tankowań (bez osobnej tabeli). Warianty zapisu
    scalane — wygrywa najczęstsza forma, przy remisie ostatnia. Malejąco po liczbie
    tankowań, przy remisie alfabetycznie."""
    if not auto_id:
        return []

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT stacja, data FROM tankowania "
            "WHERE auto_id=? AND stacja IS NOT NULL AND TRIM(stacja) <> ''",
            (auto_id,)
        )
        wiersze = c.fetchall()

    grupy = {}
    for stacja, data_str in wiersze:
        nazwa = " ".join((stacja or "").split())
        klucz = klucz_stacji(nazwa)
        if not klucz:
            continue
        d = parsuj_date(data_str)
        grupa = grupy.setdefault(klucz, {"licznik": 0, "warianty": {}})
        grupa["licznik"] += 1
        wariant = grupa["warianty"].setdefault(nazwa, {"ile": 0, "ostatnia": datetime.min.date()})
        wariant["ile"] += 1
        if d > wariant["ostatnia"]:
            wariant["ostatnia"] = d

    wynik = []
    for grupa in grupy.values():
        kanoniczna = max(
            grupa["warianty"].items(),
            key=lambda kv: (kv[1]["ile"], kv[1]["ostatnia"], kv[0])
        )[0]
        wynik.append((kanoniczna, grupa["licznik"]))

    wynik.sort(key=lambda x: (-x[1], x[0].lower()))
    return [nazwa for nazwa, _ in wynik]


def pobierz_trend_cen_paliwa(auto_id, od_data=None, rodzaj=None):
    """Cena jednostkowa w czasie i ranking stacji po średniej cenie. Tylko tankowania z
    dodatnią ilością; wpis bez stacji idzie do 'punkty', nie do 'stacje'. `rodzaj` —
    jedno źródło energii (domyślnie podstawowe; plug-in mieszałby litry z kWh).
    `od_data` tnie OBA wyniki. Zwraca {"punkty": [(data, cena)], "stacje": [{nazwa,
    srednia_cena, liczba_tankowan, ostatnia_cena, ostatnia_data}] rosnąco po średniej,
    "najtansza": pierwsza albo None}."""
    if not auto_id:
        return {"punkty": [], "stacje": [], "najtansza": None}

    domyslny = domyslny_rodzaj_energii(auto_id)
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT data, kwota, litry, stacja FROM tankowania "
            "WHERE auto_id=? AND litry > 0 AND COALESCE(rodzaj_energii, ?) = ?",
            (auto_id, domyslny, rodzaj or domyslny)
        )
        wiersze = c.fetchall()

    dane = []
    for data_str, kwota, litry, stacja in wiersze:
        litry_f = float(litry or 0)
        if litry_f <= 0:
            continue
        cena = float(kwota or 0) / litry_f
        d = parsuj_date(data_str)
        if od_data and (d == datetime.min.date() or d < od_data):
            continue
        dane.append((d, data_str, cena, " ".join((stacja or "").split())))
    dane.sort(key=lambda x: x[0])  # chronologicznie po sparsowanej dacie, nie tekście

    punkty = []
    wg_stacji = {}
    for d, data_str, cena, stacja in dane:
        punkty.append((data_str, cena))
        # Grupujemy po kluczu znormalizowanym, nie po dosłownej pisowni —
        # inaczej 'Orlen' i 'orlen' to dwie osobne pozycje w rankingu.
        klucz = klucz_stacji(stacja)
        if not klucz:
            continue
        wpis = wg_stacji.setdefault(klucz, {
            "nazwa": stacja, "suma_cen": 0.0, "liczba_tankowan": 0,
            "ostatnia_cena": None, "ostatnia_data": None,
            "_ostatnia_data_obj": None, "_warianty": {},
        })
        wpis["_warianty"][stacja] = wpis["_warianty"].get(stacja, 0) + 1
        wpis["suma_cen"] += cena
        wpis["liczba_tankowan"] += 1
        if wpis["_ostatnia_data_obj"] is None or d >= wpis["_ostatnia_data_obj"]:
            wpis["_ostatnia_data_obj"] = d
            wpis["ostatnia_cena"] = cena
            wpis["ostatnia_data"] = data_str

    stacje = []
    for wpis in wg_stacji.values():
        wpis["srednia_cena"] = wpis["suma_cen"] / wpis["liczba_tankowan"]
        # Do wyświetlenia bierzemy najczęściej używaną pisownię z grupy.
        wpis["nazwa"] = max(wpis["_warianty"].items(), key=lambda kv: (kv[1], kv[0]))[0]
        del wpis["suma_cen"], wpis["_ostatnia_data_obj"], wpis["_warianty"]
        stacje.append(wpis)
    stacje.sort(key=lambda s: s["srednia_cena"])

    return {"punkty": punkty, "stacje": stacje, "najtansza": stacje[0] if stacje else None}


# ---------------------------------------------------------------------------
# Nietypowa cena w formularzu tankowania
# ---------------------------------------------------------------------------
# Cena za litr to iloraz kwoty i ilości, więc literówka robi z niej liczbę 10× za dużą
# lub za małą. Porównanie z NAJBLIŻSZĄ ceną odniesienia, nie z medianą (LPG obok
# benzyny, garaż obok szybkiej ładowarki); próg trzykrotny łapie błędy rzędu wielkości.
PROG_NIETYPOWEJ_CENY = 3.0
# Ile wpisów z okolicy daty tankowania bierze udział w porównaniu.
CENY_ODNIESIENIA = 10


def ceny_jednostkowe_w_poblizu(auto_id, data_str=None, rodzaj=None, wyklucz_id=None,
                               ile=CENY_ODNIESIENIA) -> list[float]:
    """Ceny jednostkowe z `ile` wpisów tego samego źródła energii najbliższych w czasie
    `data_str` (wstecz i w przód); bez daty — najnowsze. Tylko dodatnia ilość i kwota;
    `wyklucz_id` — edytowany wpis."""
    if not auto_id:
        return []
    domyslny = domyslny_rodzaj_energii(auto_id)
    parametry = [auto_id, domyslny, rodzaj or domyslny]
    wyklucz_sql = ""
    if wyklucz_id:
        wyklucz_sql = " AND id != ?"
        parametry.append(wyklucz_id)
    iso = na_iso(data_str) if data_str else None
    if iso:
        kolejnosc = "data_iso IS NULL, ABS(julianday(data_iso) - julianday(?)), id DESC"
        parametry.append(iso)
    else:
        kolejnosc = "data_iso IS NULL, data_iso DESC, id DESC"
    parametry.append(int(ile))
    with polacz_baze() as conn:
        wiersze = conn.execute(
            "SELECT kwota, litry FROM tankowania "
            "WHERE auto_id=? AND litry > 0 AND kwota > 0 AND COALESCE(rodzaj_energii, ?) = ?"
            f"{wyklucz_sql} ORDER BY {kolejnosc} LIMIT ?",
            parametry,
        ).fetchall()
    ceny = []
    for kwota, litry in wiersze:
        kwota_f, litry_f = _na_liczbe(kwota), _na_liczbe(litry)
        if kwota_f and litry_f and kwota_f > 0 and litry_f > 0:
            ceny.append(kwota_f / litry_f)
    return ceny


def nietypowa_cena(cena, ceny_odniesienia, prog=PROG_NIETYPOWEJ_CENY) -> dict[str, Any] | None:
    """Cena odstająca co najmniej `prog` razy od KAŻDEJ ceny odniesienia
    (ceny_jednostkowe_w_poblizu) albo None. Wynik: {cena, odniesienie (najbliższa),
    krotnosc (≥ prog), wyzsza}."""
    cena = _na_liczbe(cena)
    odniesienia = [c for c in map(_na_liczbe, ceny_odniesienia or []) if c and c > 0]
    if not cena or cena <= 0 or not odniesienia:
        return None
    najblizsza = min(odniesienia, key=lambda c: abs(math.log(cena / c)))
    krotnosc = max(cena / najblizsza, najblizsza / cena)
    if krotnosc < prog:
        return None
    return {"cena": cena, "odniesienie": najblizsza, "krotnosc": krotnosc, "wyzsza": cena > najblizsza}


# ---------------------------------------------------------------------------
# Kto płacił: wydatki z podpisem autora
# ---------------------------------------------------------------------------
# Zestawienie miesiąca i saldo (db/rozliczenia.py) czytają wydatki z tego samego źródła,
# żeby się nie rozjechały.

BEZ_PODPISU = "Nieprzypisane"


def klucz_osoby(nazwa):
    """Podpis autora sprowadzony do postaci, po której się grupuje: bez
    wielkości liter i nadmiarowych spacji. „Kamil” i „kamil ” to ta sama
    osoba — podpis wpisuje się ręcznie w Ustawieniach, więc bywa różny na
    dwóch telefonach albo po poprawce. Pusty podpis daje pusty klucz."""
    return " ".join(str(nazwa or "").split()).casefold()


def nazwa_osoby(warianty):
    """Pisownia do pokazania: najczęstsza z grupy (przy remisie — późniejsza
    alfabetycznie, tak samo jak nazwy stacji)."""
    return max(warianty.items(), key=lambda kv: (kv[1], kv[0]))[0]


def _wydatki_z_autorem(conn, auto_id):
    """[(data, kwota, kategoria, dodane_przez, dystans)] — wszystkie wydatki
    pojazdu z podpisem autora. Wizyta zbiorcza wchodzi jako całość, a jej
    wpisy historii są pomijane (tak samo jak w `_wiersze_kosztow`); dystans ma
    tylko tankowanie."""
    c = conn.cursor()
    wiersze = []
    c.execute("SELECT data, kwota, dodane_przez, dystans FROM tankowania WHERE auto_id=?", (auto_id,))
    wiersze += [(d, k, "paliwo", o, dy) for d, k, o, dy in c.fetchall()]
    c.execute(
        "SELECT h.data, h.cena, h.dodane_przez FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
        "WHERE z.auto_id=? AND h.wizyta_id IS NULL", (auto_id,)
    )
    wiersze += [(d, k, "serwis", o, 0) for d, k, o in c.fetchall()]
    c.execute("SELECT data, koszt_calkowity, dodane_przez FROM wizyty WHERE auto_id=?", (auto_id,))
    wiersze += [(d, k, "serwis", o, 0) for d, k, o in c.fetchall()]
    c.execute("SELECT data, kwota, dodane_przez FROM inne_koszty WHERE auto_id=?", (auto_id,))
    wiersze += [(d, k, "inne", o, 0) for d, k, o in c.fetchall()]
    return wiersze


def pobierz_podzial_kosztow(auto_id, rok, miesiac):
    """Kto ile wydał i przejechał we współdzielonym pojeździe w miesiącu (po
    `dodane_przez`): [{osoba, paliwo, serwis, inne, razem, dystans_km, tankowania}]
    malejąco po sumie. dystans_km to przybliżenie — suma 'dystans' z tankowań danej
    osoby. Wpisy bez osoby → „Nieprzypisane”; podpisy porównuje `klucz_osoby`."""
    if not auto_id:
        return []

    osoby = {}
    warianty = {}

    with polacz_baze() as conn:
        wydatki = _wydatki_z_autorem(conn, auto_id)

    for data, kwota, kategoria, autor, dystans in wydatki:
        d = parsuj_date(data)
        if d == datetime.min.date() or (d.year, d.month) != (rok, miesiac):
            continue
        klucz = klucz_osoby(autor)
        nazwa = " ".join(str(autor or "").split()) or BEZ_PODPISU
        warianty.setdefault(klucz, {}).setdefault(nazwa, 0)
        warianty[klucz][nazwa] += 1
        w = osoby.setdefault(klucz, {"paliwo": 0.0, "serwis": 0.0, "inne": 0.0,
                                     "dystans_km": 0.0, "tankowania": 0})
        w[kategoria] += float(_na_liczbe(kwota) or 0)
        if kategoria == "paliwo":
            w["dystans_km"] += float(_na_liczbe(dystans) or 0)
            w["tankowania"] += 1

    wynik = []
    for klucz, w in osoby.items():
        w["osoba"] = nazwa_osoby(warianty[klucz]) if klucz else BEZ_PODPISU
        w["razem"] = w["paliwo"] + w["serwis"] + w["inne"]
        wynik.append(w)
    wynik.sort(key=lambda w: w["razem"], reverse=True)
    return wynik


# ---------------------------------------------------------------------------
# Robocizna i części
# ---------------------------------------------------------------------------
# W bazie koszt całkowity i robocizna (NULL = bez podziału); części z magazynu zna
# `koszt` przy zużyciu, części na rachunku to reszta — rozbicie sumuje się zawsze
# (migracja 42).

def rozbicie_kosztu(koszt, robocizna=None, z_magazynu=0.0) -> dict[str, Any]:
    """Koszt wizyty albo wpisu rozbity na robociznę, części na rachunku i części z
    magazynu. Części na rachunku to RESZTA, więc suma zgadza się zawsze (koszt zmieniony
    starszą wersją, zwrot pozycji; koszt usuniętej pozycji magazynu liczy się jako
    część). Robocizna None = „bez podziału”, chyba że poza magazynem nie ma czego
    dzielić."""
    razem = max(0.0, round(_na_liczbe(koszt) or 0.0, 2))
    magazyn = min(razem, max(0.0, round(_na_liczbe(z_magazynu) or 0.0, 2)))
    rachunek = round(razem - magazyn, 2)
    rob = _na_liczbe(robocizna)
    wynik = {"razem": razem, "z_magazynu": magazyn, "rachunek": rachunek,
             "robocizna": None, "czesci": None, "podzielony": False}
    if rob is None and rachunek > 0:
        return wynik
    rob = round(min(max(0.0, rob or 0.0), rachunek), 2)
    wynik.update(robocizna=rob, czesci=round(rachunek - rob, 2), podzielony=True)
    return wynik


def _w_okresie(data_str, od_data=None, do_data=None):
    d = parsuj_date(data_str)
    return d != datetime.min.date() and not (od_data and d < od_data) and not (do_data and d > do_data)


def _rekordy_napraw(conn, auto_id):
    """Naprawy pojazdu — wizyty i pojedyncze wpisy serwisowe — z rozbiciem
    kosztu, warsztatem i podzespołami. Wpis należący do wizyty nie jest osobną
    naprawą: jego koszt niesie wizyta (ta sama zasada co w `_wiersze_kosztow`).
    Zwraca (rekordy, {zadanie_id: nazwa})."""
    c = conn.cursor()
    c.execute("SELECT id, nazwa FROM zadania WHERE auto_id=?", (auto_id,))
    nazwy = {z_id: str(nazwa or "").strip() for z_id, nazwa in c.fetchall()}

    rekordy = []
    c.execute(
        "SELECT w.id, w.data, w.koszt_calkowity, w.koszt_robocizny, w.wykonawca, "
        "(SELECT SUM(x.koszt) FROM wizyta_czesci_magazynu x WHERE x.wizyta_id = w.id), "
        "(SELECT GROUP_CONCAT(h.zadanie_id) FROM historia h WHERE h.wizyta_id = w.id) "
        "FROM wizyty w WHERE w.auto_id=?", (auto_id,)
    )
    for w_id, data, koszt, robocizna, wykonawca, magazyn, zadania in c.fetchall():
        rekordy.append({
            "zrodlo": "wizyty", "id": w_id, "data": data, "wykonawca": wykonawca,
            "zadania": {int(z) for z in str(zadania or "").split(",") if z.strip()},
            **rozbicie_kosztu(koszt, robocizna, magazyn),
        })
    c.execute(
        "SELECT h.id, h.data, h.cena, h.koszt_robocizny, h.wykonawca, "
        "(SELECT SUM(x.koszt) FROM historia_czesci_magazynu x WHERE x.historia_id = h.id), h.zadanie_id "
        "FROM historia h JOIN zadania z ON h.zadanie_id = z.id "
        "WHERE z.auto_id=? AND h.wizyta_id IS NULL", (auto_id,)
    )
    for h_id, data, cena, robocizna, wykonawca, magazyn, zadanie_id in c.fetchall():
        rekordy.append({
            "zrodlo": "historia", "id": h_id, "data": data, "wykonawca": wykonawca,
            "zadania": {zadanie_id},
            **rozbicie_kosztu(cena, robocizna, magazyn),
        })
    return rekordy, nazwy


def pobierz_rozbicie_napraw(auto_id, od_data=None, do_data=None) -> dict[str, Any]:
    """Robocizna, części na rachunku i z magazynu w naprawach z okresu, plus warsztaty.
    Sumy tylko z napraw z podziałem; bez podziału liczone osobno (`bez_podzialu`,
    `kwota_bez_podzialu`). Warsztaty: naprawy z rachunkiem; średnia robocizna na
    naprawę, udział w samym rachunku (bez magazynu); najdroższa robocizna na górze."""
    wynik = {"robocizna": 0.0, "czesci": 0.0, "z_magazynu": 0.0, "razem": 0.0, "napraw": 0,
             "bez_podzialu": 0, "kwota_bez_podzialu": 0.0, "warsztaty": []}
    if not auto_id:
        return wynik
    with polacz_baze() as conn:
        rekordy, _ = _rekordy_napraw(conn, auto_id)

    warsztaty = {}
    for r in rekordy:
        if r["razem"] <= 0 or not _w_okresie(r["data"], od_data, do_data):
            continue
        if not r["podzielony"]:
            wynik["bez_podzialu"] += 1
            wynik["kwota_bez_podzialu"] += r["razem"]
            continue
        wynik["napraw"] += 1
        for klucz in ("robocizna", "czesci", "z_magazynu"):
            wynik[klucz] += r[klucz]
        if r["rachunek"] <= 0:
            continue
        nazwa = " ".join(str(r["wykonawca"] or "").split()) or "Warsztat"
        grupa = warsztaty.setdefault(klucz_stacji(bez_emoji(nazwa)) or nazwa.lower(),
                                     {"warianty": {}, "napraw": 0, "robocizna": 0.0, "czesci": 0.0})
        grupa["warianty"][nazwa] = grupa["warianty"].get(nazwa, 0) + 1
        grupa["napraw"] += 1
        grupa["robocizna"] += r["robocizna"]
        grupa["czesci"] += r["czesci"]

    for klucz in ("robocizna", "czesci", "z_magazynu", "kwota_bez_podzialu"):
        wynik[klucz] = round(wynik[klucz], 2)
    wynik["razem"] = round(wynik["robocizna"] + wynik["czesci"] + wynik["z_magazynu"], 2)

    for grupa in warsztaty.values():
        rachunek = grupa["robocizna"] + grupa["czesci"]
        wynik["warsztaty"].append({
            "nazwa": max(grupa["warianty"].items(), key=lambda kv: (kv[1], kv[0]))[0],
            "napraw": grupa["napraw"],
            "robocizna": round(grupa["robocizna"], 2),
            "czesci": round(grupa["czesci"], 2),
            "srednia_robocizna": round(grupa["robocizna"] / grupa["napraw"], 2),
            "udzial_robocizny": round(grupa["robocizna"] / rachunek * 100, 1) if rachunek > 0 else 0.0,
        })
    wynik["warsztaty"].sort(key=lambda w: (-w["srednia_robocizna"], w["nazwa"]))
    return wynik


def porownaj_czesci_wlasne(auto_id, od_data=None, do_data=None) -> list[dict[str, Any]]:
    """Części tego samego podzespołu z warsztatu kontra z własnego magazynu:
    [{zadanie_id, nazwa, z_warsztatu, ile_z_warsztatu, wlasne, ile_wlasnych, roznica}],
    największa różnica na górze. Tylko naprawy JEDNEGO podzespołu; z warsztatu = nic z
    magazynu, własne = nic na rachunku, mieszane pomijane. Kwoty średnie; podzespół
    dopiero z obiema stronami."""
    if not auto_id:
        return []
    with polacz_baze() as conn:
        rekordy, nazwy = _rekordy_napraw(conn, auto_id)

    grupy = {}
    for r in rekordy:
        if len(r["zadania"]) != 1 or not r["podzielony"] or not _w_okresie(r["data"], od_data, do_data):
            continue
        if r["robocizna"] > 0 and r["czesci"] > 0 and r["z_magazynu"] == 0:
            strona, kwota = "z_warsztatu", r["czesci"]
        elif r["z_magazynu"] > 0 and r["czesci"] == 0:
            strona, kwota = "wlasne", r["z_magazynu"]
        else:
            continue
        zadanie_id = next(iter(r["zadania"]))
        grupa = grupy.setdefault(zadanie_id, {"z_warsztatu": [], "wlasne": []})
        grupa[strona].append(kwota)

    wynik = []
    for zadanie_id, grupa in grupy.items():
        if not grupa["z_warsztatu"] or not grupa["wlasne"]:
            continue
        z_warsztatu = round(sum(grupa["z_warsztatu"]) / len(grupa["z_warsztatu"]), 2)
        wlasne = round(sum(grupa["wlasne"]) / len(grupa["wlasne"]), 2)
        wynik.append({
            "zadanie_id": zadanie_id, "nazwa": nazwy.get(zadanie_id) or "Podzespół",
            "z_warsztatu": z_warsztatu, "ile_z_warsztatu": len(grupa["z_warsztatu"]),
            "wlasne": wlasne, "ile_wlasnych": len(grupa["wlasne"]),
            "roznica": round(z_warsztatu - wlasne, 2),
        })
    wynik.sort(key=lambda p: (-abs(p["roznica"]), p["nazwa"]))
    return wynik


__all__ = [
    "CENY_ODNIESIENIA",
    "DNI_W_MIESIACU",
    "KATEGORIE_BUDZETU",
    "BEZ_PODPISU",
    "PROG_NIETYPOWEJ_CENY",
    "_rekordy_napraw",
    "_w_okresie",
    "_wiersze_kosztow",
    "_wydatki_z_autorem",
    "ceny_jednostkowe_w_poblizu",
    "etykieta_kategorii_innych",
    "klucz_osoby",
    "klucz_stacji",
    "koszty_w_okresie",
    "pobierz_koszt_miesiaca_do_dnia",
    "pobierz_koszty_innych_wg_kategorii",
    "pobierz_koszty_miesieczne",
    "pobierz_koszty_miesieczne_wg_kategorii",
    "pobierz_podzial_kosztow",
    "pobierz_rozbicie_napraw",
    "porownaj_czesci_wlasne",
    "rozbicie_kosztu",
    "siatka_miesiecy",
    "pobierz_stacje_paliw",
    "pobierz_trend_cen_paliwa",
    "nazwa_osoby",
    "nietypowa_cena",
    "suma_kategorii_innych",
]
