"""Stacje paliw, trend cen i podział kosztów."""

from date import parsuj_date
from datetime import datetime

from .stale import KATEGORIA_INNE_DOMYSLNA, KATEGORIE_INNYCH_KOSZTOW
from .polaczenie import polacz_baze

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
# Trzy wiadra budżetu (paliwo / serwis / inne) odpowiadają na pytanie „na co
# idą pieniądze”, ale „inne” to worek, w którym mandat za prędkość leży obok
# winiety, myjni i wymiany dywaników. Rozbicie poniżej pozwala wyciągnąć
# z tego worka konkretną pozycję — przede wszystkim opłaty drogowe, bo one
# rosną z KILOMETRAMI, a nie z wiekiem auta, i mieszanie ich z resztą zaciera
# jedyny wniosek, jaki dałoby się z nich wyciągnąć.


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


def pobierz_koszty_miesieczne(auto_id, liczba_miesiecy=6) -> list[tuple[int, int, float]]:
    """Suma kosztów (paliwo + serwis + inne) dla ostatnich `liczba_miesiecy`
    miesięcy, włącznie z bieżącym — używane przez mini-wykres na dashboardzie
    startowym (patrz MainView._buduj_kokpit). Zwraca listę (rok, miesiac, suma)
    posortowaną chronologicznie rosnąco; miesiące bez wydatków mają sumę 0.0."""
    if not auto_id:
        return []

    dzisiaj = datetime.now()
    klucze = []
    for i in range(liczba_miesiecy - 1, -1, -1):
        m = dzisiaj.month - i
        y = dzisiaj.year
        while m <= 0:
            m += 12
            y -= 1
        klucze.append((y, m))

    sumy = {k: 0.0 for k in klucze}

    with polacz_baze() as conn:
        c = conn.cursor()
        wiersze = []
        c.execute("SELECT data, kwota FROM tankowania WHERE auto_id=?", (auto_id,))
        wiersze += c.fetchall()
        c.execute(
            "SELECT h.data, h.cena FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE z.auto_id=? AND h.wizyta_id IS NULL", (auto_id,)
        )
        wiersze += c.fetchall()
        c.execute("SELECT data, koszt_calkowity FROM wizyty WHERE auto_id=?", (auto_id,))
        wiersze += c.fetchall()
        c.execute("SELECT data, kwota FROM inne_koszty WHERE auto_id=?", (auto_id,))
        wiersze += c.fetchall()

    for data_str, kwota in wiersze:
        d = parsuj_date(data_str)
        if d == datetime.min.date():
            continue
        klucz = (d.year, d.month)
        if klucz in sumy:
            sumy[klucz] += float(kwota or 0.0)

    return [(y, m, sumy[(y, m)]) for (y, m) in klucze]


def pobierz_koszt_miesiaca_do_dnia(auto_id, rok, miesiac, do_dnia):
    """Suma kosztów (paliwo + serwis + inne) dla danego miesiąca, ale TYLKO do
    dnia `do_dnia` włącznie. Używane do uczciwego porównania 'ile wydałem w tym
    miesiącu do dzisiaj' z analogicznym okresem poprzedniego miesiąca — zamiast
    mylącego porównania niepełnego bieżącego miesiąca z CAŁYM poprzednim
    (patrz MainView._buduj_kokpit -> widget_koszt_miesiac), które 2. dnia
    miesiąca niemal zawsze pokazywało fałszywe "📉 Spada o 95%"."""
    if not auto_id:
        return 0.0

    suma = 0.0
    with polacz_baze() as conn:
        c = conn.cursor()
        wiersze = []
        c.execute("SELECT data, kwota FROM tankowania WHERE auto_id=?", (auto_id,))
        wiersze += c.fetchall()
        c.execute(
            "SELECT h.data, h.cena FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE z.auto_id=? AND h.wizyta_id IS NULL", (auto_id,)
        )
        wiersze += c.fetchall()
        c.execute("SELECT data, koszt_calkowity FROM wizyty WHERE auto_id=?", (auto_id,))
        wiersze += c.fetchall()
        c.execute("SELECT data, kwota FROM inne_koszty WHERE auto_id=?", (auto_id,))
        wiersze += c.fetchall()

    for data_str, kwota in wiersze:
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
    """Słownik stacji budowany w locie z dotychczasowych tankowań pojazdu — bez
    osobnej tabeli, bo dane już są w 'tankowania'. Warianty zapisu tej samej
    stacji są scalane; jako kanoniczna wygrywa forma użyta najczęściej, a przy
    remisie ostatnio użyta. Zwraca listę nazw posortowaną malejąco po liczbie
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


def pobierz_trend_cen_paliwa(auto_id):
    """Cena za litr w czasie (do wykresu) oraz zestawienie średnich cen per
    stacja (do rankingu „najtańsza stacja, na której tankowałeś”). Uwzględnia
    tylko tankowania z dodatnią liczbą litrów; stacja jest opcjonalna — wpisy
    bez niej trafiają do 'punkty', ale nie do rankingu 'stacje'.
    Zwraca {"punkty": [(data, cena_za_litr), ...] posortowane chronologicznie,
    "stacje": [{"nazwa","srednia_cena","liczba_tankowan","ostatnia_cena","ostatnia_data"}, ...]
    posortowane rosnąco po średniej cenie, "najtansza": pierwszy element stacje albo None}."""
    if not auto_id:
        return {"punkty": [], "stacje": [], "najtansza": None}

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT data, kwota, litry, stacja FROM tankowania WHERE auto_id=? AND litry > 0",
            (auto_id,)
        )
        wiersze = c.fetchall()

        dane = []
    for data_str, kwota, litry, stacja in wiersze:
        litry_f = float(litry or 0)
        if litry_f <= 0:
            continue
        cena = float(kwota or 0) / litry_f
        d = parsuj_date(data_str)
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


def pobierz_podzial_kosztow(auto_id, rok, miesiac):
    """Zestawienie 'kto ile wydał / przejechał' dla współdzielonego pojazdu w
    danym miesiącu, na podstawie kolumny dodane_przez. Zwraca listę słowników
    posortowaną malejąco po sumie wydatków:
    [{"osoba", "paliwo", "serwis", "inne", "razem", "dystans_km", "tankowania"}, ...]
    Uwaga: dystans_km to suma pola 'dystans' z tankowań DODANYCH przez daną
    osobę w tym miesiącu — to przybliżenie ('kto tankował po ilu km'), nie
    dokładny pomiar tego, kto faktycznie siedział za kierownicą. Wpisy bez
    przypisanej osoby (sprzed tej funkcji) trafiają pod 'Nieprzypisane'."""
    if not auto_id:
        return []

    prefiks = f"{rok:04d}-{miesiac:02d}"
    osoby = {}

    def wpis(nazwa):
        nazwa = (nazwa or "Nieprzypisane").strip() or "Nieprzypisane"
        return osoby.setdefault(nazwa, {"osoba": nazwa, "paliwo": 0.0, "serwis": 0.0, "inne": 0.0, "dystans_km": 0.0, "tankowania": 0})

    with polacz_baze() as conn:
        c = conn.cursor()

        c.execute("SELECT data, kwota, dystans, dodane_przez FROM tankowania WHERE auto_id=?", (auto_id,))
        for data, kwota, dystans, osoba in c.fetchall():
            d = parsuj_date(data)
            if d == datetime.min.date() or f"{d.year:04d}-{d.month:02d}" != prefiks:
                continue
            w = wpis(osoba)
            w["paliwo"] += float(kwota or 0)
            w["dystans_km"] += float(dystans or 0)
            w["tankowania"] += 1

        c.execute(
            "SELECT h.data, h.cena, h.dodane_przez FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE z.auto_id=? AND h.wizyta_id IS NULL", (auto_id,)
        )
        for data, cena, osoba in c.fetchall():
            d = parsuj_date(data)
            if d == datetime.min.date() or f"{d.year:04d}-{d.month:02d}" != prefiks:
                continue
            wpis(osoba)["serwis"] += float(cena or 0)

        c.execute("SELECT data, koszt_calkowity, dodane_przez FROM wizyty WHERE auto_id=?", (auto_id,))
        for data, koszt, osoba in c.fetchall():
            d = parsuj_date(data)
            if d == datetime.min.date() or f"{d.year:04d}-{d.month:02d}" != prefiks:
                continue
            wpis(osoba)["serwis"] += float(koszt or 0)

        c.execute("SELECT data, kwota, dodane_przez FROM inne_koszty WHERE auto_id=?", (auto_id,))
        for data, kwota, osoba in c.fetchall():
            d = parsuj_date(data)
            if d == datetime.min.date() or f"{d.year:04d}-{d.month:02d}" != prefiks:
                continue
            wpis(osoba)["inne"] += float(kwota or 0)

    wynik = list(osoby.values())
    for w in wynik:
        w["razem"] = w["paliwo"] + w["serwis"] + w["inne"]
    wynik.sort(key=lambda w: w["razem"], reverse=True)
    return wynik


__all__ = [
    "DNI_W_MIESIACU",
    "KATEGORIE_BUDZETU",
    "_wiersze_kosztow",
    "etykieta_kategorii_innych",
    "klucz_stacji",
    "koszty_w_okresie",
    "pobierz_koszt_miesiaca_do_dnia",
    "pobierz_koszty_innych_wg_kategorii",
    "pobierz_koszty_miesieczne",
    "pobierz_podzial_kosztow",
    "pobierz_stacje_paliw",
    "pobierz_trend_cen_paliwa",
    "suma_kategorii_innych",
]
