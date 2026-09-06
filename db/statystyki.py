"""Serie danych do wykresów i kondycja pojazdu."""

import sqlite3
from date import parsuj_date
from datetime import datetime

from .stale import ENERGIA_PALIWO, ENERGIA_PRAD, TYPY_LADOWANIA, TYPY_PALIWA_ELEKTRYCZNE
from .polaczenie import polacz_baze
from .pomocnicze import _liczba_lub_none, formatuj_liczba_eksport
from .energia import ETYKIETY_RODZAJU, czy_pojazd_dwuzrodlowy, domyslny_rodzaj_energii, etykiety_energii, rodzaje_energii_pojazdu
from .przebieg import pobierz_historie_przebiegu
from .koszty import pobierz_koszty_miesieczne
from .powiadomienia import pobierz_powiadomienia


# Ile punktów kondycji kosztuje każdy powód. Trzymane w jednym miejscu, bo te
# same wartości pokazuje teraz rozpiska („−15 pkt: przegląd przeterminowany”).
KARY_KONDYCJI = {
    "podzespol_przeterminowany": 15,
    "podzespol_pilny": 8,
    "bieznik_krytyczny": 20,   # poniżej 1,6 mm — minimum prawne
    "bieznik_niski": 10,       # poniżej 3 mm — zalecana wymiana
}


def pobierz_rozbicie_kondycji(auto_id):
    """Kondycja pojazdu wraz z ROZPISKĄ tego, co ją obniżyło. Sam wynik 0-100 nic
    nie podpowiada; lista powodów mówi wprost, co poprawić najpierw.

    Zwraca {"wynik": int|None, "powody": [{opis, szczegol, punkty, trasa, typ}]}
    posortowaną malejąco po odjętych punktach. Celowo NIE uwzględnia stanu
    magazynu, dokumentów (OC/przegląd) ani wydatków cyklicznych — kondycja
    dotyczy stanu technicznego auta, nie papierologii.

    Powiadomienia bierzemy z pomin_wyciszone=False: odłożenie przypomnienia
    („zrobię za dwa tygodnie”) nie naprawia auta, więc nie może podbijać wyniku.
    """
    if not auto_id:
        return {"wynik": None, "powody": []}

    wynik = 100
    powody = []

    for p in pobierz_powiadomienia(auto_id, pomin_wyciszone=False):
        # Ignorujemy wszystko, co nie jest bezpośrednio powiązane z podzespołami auta
        if p["typ"] != "podzespol":
            continue

        if p["status"] == "przeterminowane":
            kara = KARY_KONDYCJI["podzespol_przeterminowany"]
            etykieta = "przeterminowany"
        elif p["status"] == "pilne":
            kara = KARY_KONDYCJI["podzespol_pilny"]
            etykieta = "termin się zbliża"
        else:
            continue

        wynik -= kara
        powody.append({
            "typ": "podzespol",
            "opis": f"{p['tytul']} — {etykieta}",
            "szczegol": p.get("opis") or "",
            "punkty": kara,
            "trasa": p.get("trasa"),
        })

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT sezon, rozmiar, glebokosc_bieznika FROM zestawy_opon "
            "WHERE auto_id=? AND zamontowane=1",
            (auto_id,)
        )
        for r in c.fetchall():
            gl = r["glebokosc_bieznika"]
            if gl is None or str(gl).strip() == "":
                continue
            try:
                g = float(gl)
            except (TypeError, ValueError):
                continue

            if g < 1.6:
                kara = KARY_KONDYCJI["bieznik_krytyczny"]
                etykieta = "bieżnik poniżej minimum prawnego (1,6 mm)"
            elif g < 3.0:
                kara = KARY_KONDYCJI["bieznik_niski"]
                etykieta = "bieżnik poniżej 3 mm — zalecana wymiana"
            else:
                continue

            wynik -= kara
            nazwa_opon = f"Opony {r['sezon']}" if r["sezon"] else "Zamontowane opony"
            powody.append({
                "typ": "opony",
                "opis": f"{nazwa_opon} — {etykieta}",
                "szczegol": f"{formatuj_liczba_eksport(g, 1)} mm"
                            + (f" • {r['rozmiar']}" if r["rozmiar"] else ""),
                "punkty": kara,
                "trasa": "/magazyn",
            })

    powody.sort(key=lambda p: -p["punkty"])
    return {"wynik": max(0, min(100, int(round(wynik)))), "powody": powody}


def oblicz_kondycje_pojazdu(auto_id):
    """Sam wskaźnik 0-100 (100 = wzorowo) — cienkie opakowanie na
    pobierz_rozbicie_kondycji, dla miejsc, którym wystarczy liczba."""
    return pobierz_rozbicie_kondycji(auto_id)["wynik"]


def pobierz_serie_spalania(auto_id, limit=12, rodzaj=None):
    """Spalanie liczone ODCINKAMI między kolejnymi tankowaniami „do pełna” —
    dokładnie ta sama metoda, co wykres trendu w Statystykach, tylko bez
    uśredniania po miesiącach (jeden punkt = jeden odcinek między pełnymi
    bakami). Używane przez sparkline przy kafelku „Śr. spalanie” w kokpicie.
    Zwraca listę (data_tankowania_konczacego_odcinek, l/100km) chronologicznie,
    przyciętą do ostatnich `limit` punktów (limit=None → wszystkie).

    `rodzaj` zawęża liczenie do jednego źródła energii. Przy hybrydzie plug-in
    to konieczność: mieszanie litrów z kilowatogodzinami w jednym odcinku dałoby
    liczbę bez żadnego znaczenia. Brak `rodzaju` = wszystkie wpisy (auta
    jednoźródłowe, gdzie nie ma czego mieszać)."""
    if not auto_id:
        return []

    with polacz_baze() as conn:
        c = conn.cursor()
        if rodzaj:
            # COALESCE, bo wpisy sprzed migracji 33 mają rodzaj_energii NULL
            # — traktujemy je zgodnie z typem pojazdu, tak jak backfill.
            c.execute(
                "SELECT data, przebieg, litry, do_pelna FROM tankowania "
                "WHERE auto_id=? AND COALESCE(rodzaj_energii, ?) = ?",
                (auto_id, domyslny_rodzaj_energii(auto_id), rodzaj)
            )
        else:
            c.execute(
                "SELECT data, przebieg, litry, do_pelna FROM tankowania WHERE auto_id=?",
                (auto_id,)
            )
        wiersze = c.fetchall()

    # Sortujemy po dacie, a przy remisie po przebiegu — tak jak reszta aplikacji,
    # żeby dwa tankowania tego samego dnia nie dały ujemnego dystansu.
    tankowania = sorted(
        ((parsuj_date(r[0]), r[0], int(r[1] or 0), float(r[2] or 0), bool(r[3])) for r in wiersze),
        key=lambda t: (t[0], t[2])
    )

    pelne = [i for i, t in enumerate(tankowania) if t[4]]
    seria = []
    for a, b in zip(pelne, pelne[1:]):
        dystans = tankowania[b][2] - tankowania[a][2]
        litry = sum(tankowania[k][3] for k in range(a + 1, b + 1))
        if dystans > 0 and litry > 0:
            seria.append((tankowania[b][1], (litry / dystans) * 100))

    if limit and len(seria) > limit:
        return seria[-limit:]
    return seria


def pobierz_serie_dziennego_przebiegu(auto_id, limit=12, min_dni=7):
    """Średni przebieg dzienny w kolejnych odcinkach czasu — punkty do sparkline
    przy kafelku „Śr. dzienny” w kokpicie. Odcinki sklejamy tak, aby każdy miał
    co najmniej `min_dni` dni; bez tego dwa odczyty licznika z sąsiednich dni
    dawałyby skok w rodzaju „400 km/dzień” i wykres pokazywałby szum zamiast
    tempa jazdy. Zwraca [(data_konca_odcinka, km_na_dzien)] chronologicznie."""
    if not auto_id:
        return []

    punkty = pobierz_historie_przebiegu(auto_id)
    if len(punkty) < 2:
        return []

    seria = []
    baza_data = parsuj_date(punkty[0][0])
    baza_przebieg = punkty[0][1]

    for data_str, przebieg in punkty[1:]:
        d = parsuj_date(data_str)
        dni = (d - baza_data).days
        km = przebieg - baza_przebieg
        if dni < min_dni:
            continue                      # za krótki odcinek — zbieramy dalej
        if km > 0:
            seria.append((data_str, km / dni))
        baza_data, baza_przebieg = d, przebieg

    if limit and len(seria) > limit:
        return seria[-limit:]
    return seria


def pobierz_przebieg_miesieczny(auto_id, liczba_miesiecy=6):
    """Kilometry przejechane w kolejnych miesiącach — liczone z tych samych
    źródeł, co pobierz_historie_przebiegu(). Zwraca [(rok, miesiac, km)] w tej
    samej siatce miesięcy, co pobierz_koszty_miesieczne(), więc obie listy da
    się zestawić pozycja w pozycję. Miesiąc bez odczytu dostaje km = 0."""
    if not auto_id:
        return []

    punkty = pobierz_historie_przebiegu(auto_id)
    if len(punkty) < 2:
        return []

    # Najwyższy stan licznika zanotowany w danym miesiącu.
    wg_miesiaca = {}
    for data_str, przebieg in punkty:
        d = parsuj_date(data_str)
        klucz = (d.year, d.month)
        if klucz not in wg_miesiaca or przebieg > wg_miesiaca[klucz]:
            wg_miesiaca[klucz] = przebieg

    dzisiaj = datetime.now()
    klucze = []
    for i in range(liczba_miesiecy - 1, -1, -1):
        m, y = dzisiaj.month - i, dzisiaj.year
        while m <= 0:
            m += 12
            y -= 1
        klucze.append((y, m))

    def stan_na_koniec(klucz):
        """Ostatni znany stan licznika NIE PÓŹNIEJ niż koniec danego miesiąca —
        dzięki temu miesiąc bez odczytu nie generuje ujemnego dystansu."""
        wczesniejsze = [wg_miesiaca[k] for k in wg_miesiaca if k <= klucz]
        return max(wczesniejsze) if wczesniejsze else None

    wynik = []
    for y, m in klucze:
        poprz_m, poprz_y = (m - 1, y) if m > 1 else (12, y - 1)
        koniec = stan_na_koniec((y, m))
        poczatek = stan_na_koniec((poprz_y, poprz_m))
        km = (koniec - poczatek) if (koniec is not None and poczatek is not None) else 0
        wynik.append((y, m, max(0, km)))
    return wynik


def pobierz_serie_kosztu_km(auto_id, liczba_miesiecy=6):
    """Koszt eksploatacji na kilometr w kolejnych miesiącach — punkty do
    sparkline przy kafelku „Koszt / km”. Miesiące bez przejechanych kilometrów
    są pomijane (dzielenie przez zero, a i tak nic nie mówią o koszcie jazdy).
    Zwraca [(rok, miesiac, koszt_na_km)] chronologicznie."""
    if not auto_id:
        return []

    koszty = pobierz_koszty_miesieczne(auto_id, liczba_miesiecy)
    kilometry = pobierz_przebieg_miesieczny(auto_id, liczba_miesiecy)
    if not koszty or not kilometry:
        return []

    km_wg_klucza = {(y, m): km for y, m, km in kilometry}
    seria = []
    for rok, mies, suma in koszty:
        km = km_wg_klucza.get((rok, mies), 0)
        if km > 0:
            seria.append((rok, mies, suma / km))
    return seria


def pobierz_statystyki_energii(auto_id):
    """Zużycie i koszty rozbite NA KAŻDE ŹRÓDŁO ENERGII osobno.

    Przy hybrydzie plug-in jedna uśredniona liczba nie mówi nic sensownego —
    dopiero „6,1 l/100km na paliwie i 18,4 kWh/100km na prądzie” pozwala ocenić,
    ile daje ładowanie zamiast tankowania. Auta jednoźródłowe dostają jedną
    sekcję i wyglądają dokładnie jak dotąd.

    Zwraca listę słowników (w kolejności rodzajow_energii_pojazdu):
    {rodzaj, etykieta, jednostka, ilosc, koszt, liczba_wpisow, zuzycie,
     dystans, koszt_km, cena_jednostkowa, ceny_ladowania}
    gdzie 'zuzycie' jest w jednostce właściwej dla źródła (l/100km albo
    kWh/100km), a 'dystans' to suma odcinków między pełnymi tankowaniami TEGO
    źródła — czyli baza, na której zużycie faktycznie policzono.
    """
    if not auto_id:
        return []

    domyslny = domyslny_rodzaj_energii(auto_id)
    wyniki = []

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        for rodzaj in rodzaje_energii_pojazdu(auto_id):
            c.execute(
                "SELECT data, przebieg, litry, kwota, do_pelna, typ_ladowania FROM tankowania "
                "WHERE auto_id=? AND COALESCE(rodzaj_energii, ?) = ?",
                (auto_id, domyslny, rodzaj)
            )
            wiersze = c.fetchall()

            ilosc = sum(float(r["litry"] or 0) for r in wiersze)
            koszt = sum(float(r["kwota"] or 0) for r in wiersze)

            # Dystans i zużycie liczymy tą samą metodą, co pobierz_serie_spalania:
            # wyłącznie odcinki zamknięte dwoma tankowaniami „do pełna”.
            posortowane = sorted(
                ((parsuj_date(r["data"]), int(r["przebieg"] or 0), float(r["litry"] or 0), bool(r["do_pelna"]))
                 for r in wiersze),
                key=lambda t: (t[0], t[1])
            )
            pelne = [i for i, t in enumerate(posortowane) if t[3]]
            dystans_licz, ilosc_licz = 0.0, 0.0
            for a, b in zip(pelne, pelne[1:]):
                odcinek = posortowane[b][1] - posortowane[a][1]
                zuzyte = sum(posortowane[k][2] for k in range(a + 1, b + 1))
                if odcinek > 0 and zuzyte > 0:
                    dystans_licz += odcinek
                    ilosc_licz += zuzyte

            zuzycie = (ilosc_licz / dystans_licz * 100) if dystans_licz > 0 else 0.0
            koszt_km = (koszt / dystans_licz) if dystans_licz > 0 else 0.0

            # Średnia cena za jednostkę — dla prądu dodatkowo w rozbiciu AC/DC,
            # bo szybkie ładowanie na trasie potrafi być kilka razy droższe.
            cena_jednostkowa = (koszt / ilosc) if ilosc > 0 else 0.0
            ceny_ladowania = {}
            if rodzaj == ENERGIA_PRAD:
                for typ in TYPY_LADOWANIA:
                    pasujace = [r for r in wiersze if str(r["typ_ladowania"] or "").upper() == typ]
                    suma_kwh = sum(float(r["litry"] or 0) for r in pasujace)
                    suma_kosztu = sum(float(r["kwota"] or 0) for r in pasujace)
                    if suma_kwh > 0:
                        ceny_ladowania[typ] = {
                            "cena": suma_kosztu / suma_kwh,
                            "ilosc": suma_kwh,
                            "koszt": suma_kosztu,
                            "liczba": len(pasujace),
                        }

            etykiety = etykiety_energii(rodzaj)
            # Przy dwóch źródłach zużycie jest liczone po CAŁYM przebiegu (tak
            # samo podaje je WLTP dla plug-inów) — nie po kilometrach
            # przejechanych na tym jednym źródle, bo tych nie da się wydzielić.
            wyniki.append({
                "rodzaj": rodzaj,
                "etykieta": ETYKIETY_RODZAJU[rodzaj],
                "jednostka": etykiety["jednostka"],
                "etykiety": etykiety,
                "ilosc": ilosc,
                "koszt": koszt,
                "liczba_wpisow": len(wiersze),
                "zuzycie": zuzycie,
                "dystans": dystans_licz,
                "koszt_km": koszt_km,
                "cena_jednostkowa": cena_jednostkowa,
                "ceny_ladowania": ceny_ladowania,
                "laczony_cykl": len(rodzaje_energii_pojazdu(auto_id)) > 1,
            })

    return wyniki


def pobierz_udzial_energii(auto_id):
    """Jak rozkłada się WYDATEK na energię między paliwo a prąd — sens ma
    wyłącznie przy hybrydzie plug-in.

    Świadomie liczymy udział KOSZTU, a nie kilometrów. Mając wyłącznie licznik
    i ilości zatankowanej energii NIE DA SIĘ rozdzielić, ile kilometrów auto
    przejechało na prądzie, a ile na paliwie — obie strony dzielą ten sam
    przebieg. Udział kosztu jest policzalny, uczciwy i odpowiada na właściwe
    pytanie: ile realnie oszczędza ładowanie zamiast tankowania.
    """
    if not czy_pojazd_dwuzrodlowy(auto_id):
        return None
    statystyki = {s["rodzaj"]: s for s in pobierz_statystyki_energii(auto_id)}
    koszt_prad = statystyki.get(ENERGIA_PRAD, {}).get("koszt", 0.0)
    koszt_paliwo = statystyki.get(ENERGIA_PALIWO, {}).get("koszt", 0.0)
    razem = koszt_prad + koszt_paliwo
    if razem <= 0:
        return None
    return {
        "procent_prad": koszt_prad / razem * 100,
        "procent_paliwo": koszt_paliwo / razem * 100,
        "koszt_prad": koszt_prad,
        "koszt_paliwo": koszt_paliwo,
        "razem": razem,
    }


def pobierz_zasieg_ev(auto_id):
    """Szacowany REALNY zasięg na prądzie: pojemność baterii podzielona przez
    Twoje faktyczne zużycie. Katalogowy zasięg (WLTP) podajemy obok do porównania,
    bo w praktyce prawie zawsze jest wyższy od osiąganego.

    Zwraca None, gdy nie ma pojemności baterii albo policzonego zużycia."""
    if not auto_id:
        return None

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT pojemnosc_baterii, zasieg_ev, typ_paliwa FROM samochody WHERE id=?", (auto_id,))
        w = c.fetchone()
    if not w:
        return None

    typ = str(w["typ_paliwa"] or "")
    # WYŁĄCZNIE czysty elektryk. Przy hybrydzie plug-in „kWh/100km” liczy się po
    # CAŁYM przebiegu — także po kilometrach przejechanych na paliwie — więc
    # bateria podzielona przez tę wartość dałaby zasięg kilkukrotnie zawyżony.
    if typ not in TYPY_PALIWA_ELEKTRYCZNE:
        return None

    pojemnosc = _liczba_lub_none(w["pojemnosc_baterii"])
    deklarowany = _liczba_lub_none(w["zasieg_ev"])

    zuzycie = 0.0
    for s in pobierz_statystyki_energii(auto_id):
        if s["rodzaj"] == ENERGIA_PRAD:
            zuzycie = s["zuzycie"]
            break

    szacowany = None
    if pojemnosc and zuzycie > 0:
        # kWh / (kWh/100km) * 100 = km
        szacowany = pojemnosc / zuzycie * 100

    if szacowany is None and deklarowany is None:
        return None

    return {
        "pojemnosc": pojemnosc,
        "deklarowany": deklarowany,
        "szacowany": szacowany,
        "zuzycie": zuzycie,
        # Ile procent katalogowego zasięgu faktycznie osiągasz — liczba, której
        # nie da się wyczytać z żadnej broszury.
        "procent_deklarowanego": (szacowany / deklarowany * 100)
                                  if (szacowany and deklarowany and deklarowany > 0) else None,
    }


__all__ = [
    "KARY_KONDYCJI",
    "oblicz_kondycje_pojazdu",
    "pobierz_przebieg_miesieczny",
    "pobierz_rozbicie_kondycji",
    "pobierz_serie_dziennego_przebiegu",
    "pobierz_serie_kosztu_km",
    "pobierz_serie_spalania",
    "pobierz_statystyki_energii",
    "pobierz_udzial_energii",
    "pobierz_zasieg_ev",
]
