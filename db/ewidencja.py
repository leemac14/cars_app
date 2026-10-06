"""Ewidencja przebiegu (N-01): przejazdy prywatne i służbowe, miesiąc w liczbach,
kilometrówka, licznik na granicach okresu i dane raportu.

Aplikacja znała stan licznika z kilku źródeł, ale nie wiedziała, PO CO były
kilometry. Przejazd to data, skąd, dokąd, cel, kilometry, rodzaj (służbowy albo
prywatny) i kierowca — wpisany ręcznie, z zapisanej trasy kalkulatora albo
powtórzony. Opcjonalny stan licznika po przejeździe jest jeszcze jednym źródłem
historii licznika (db/przebieg.py).

Okresem rozliczeniowym jest miesiąc: kilometry służbowe i prywatne, podział
kosztów miesiąca w tej samej proporcji, kwota kilometrówki (stawka × km
służbowe) i licznik na początek i koniec okresu — z niego „nieopisane km”, czyli
to, czego w ewidencji brakuje. Raport w trzech układach składa
`dane_raportu_ewidencji`, a rysuje db/raporty.py — liczby osobno od rysunku,
żeby test sprawdzał treść, a nie piksele.

Kilometry w bazie są zawsze w km i zawsze za CAŁY przejazd: „tam i z powrotem”
ma już podwojoną liczbę, więc suma miesiąca to zwykła suma kolumny. Ekran
pokazuje je w jednostce z Ustawień (km albo mi).
"""

import sqlite3
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Any

from date import na_iso, parsuj_date

from .stale import STATUS_POJAZDU_AKTYWNY, TRYBY_EWIDENCJI
from .polaczenie import polacz_baze
from .pomocnicze import (
    SEPARATOR_TYSIECY, _liczba_lub_none, klucz_nazwy, liczba_na_tekst, liczba_z_odmiana, normalizuj_nazwe,
)
from .daty import warunek_zakresu_dat
from .ustawienia import (
    pobierz_dane_osoby_ewidencji, pobierz_moje_imie, pobierz_ustawienia_ewidencji, pobierz_walute,
)
from .jednostki import dystans_z_km, jednostka_dystansu, tekst_dystansu
from .synchronizacja import czy_moge_dodawac
from .przebieg import dodaj_odczyt_przebiegu, pobierz_historie_przebiegu, pobierz_pelna_historie_przebiegu
from .koszty import koszty_w_okresie


RODZAJ_SLUZBOWY = "Służbowy"
RODZAJ_PRYWATNY = "Prywatny"

# Nazwy miesięcy do tytułów i zdań. Warstwa danych nie importuje interfejsu
# (utils/format.py ma swoje odmiany), a raport PDF powstaje właśnie tutaj.
MIESIACE_EWIDENCJI = ["styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec",
                      "lipiec", "sierpień", "wrzesień", "październik", "listopad", "grudzień"]
MIESIACE_EWIDENCJI_MIEJSCOWNIK = ["styczniu", "lutym", "marcu", "kwietniu", "maju", "czerwcu",
                                  "lipcu", "sierpniu", "wrześniu", "październiku", "listopadzie", "grudniu"]

# Układy raportu — te same klucze, co tryby ewidencji: tryb pojazdu podpowiada
# układ, ale wybrać da się każdy.
UKLADY_RAPORTU_EWIDENCJI = {
    "podzial": "Podział prywatne / służbowe",
    "vat": "Ewidencja do VAT",
    "kilometrowka": "Kilometrówka",
}

# Stawki za 1 km z rozporządzenia Ministra Infrastruktury z 25 marca 2002 r.
# w sprawie zwrotu kosztów używania do celów służbowych pojazdów niebędących
# własnością pracodawcy (Dz.U. nr 27, poz. 271), w brzmieniu od 17.01.2023.
# To stawki MAKSYMALNE — pracodawca może płacić mniej, dlatego w aplikacji
# tylko podpowiadają, a pole stawki zostaje do wpisania.
STAWKI_KILOMETROWKI = (
    ("Samochód do 900 cm³", 0.89),
    ("Samochód powyżej 900 cm³", 1.15),
    ("Motocykl", 0.69),
    ("Motorower", 0.42),
)
PROG_POJEMNOSCI_KILOMETROWKI = 900   # cm³ — granica dwóch stawek samochodu
STAWKA_MAKSYMALNA_SAMOCHODU = 1.15

# Przypomnienie o zamknięciu poprzedniego miesiąca stoi w dzwonku przez
# pierwsze dni nowego — wtedy rozlicza się kilometrówkę i potwierdza ewidencję.
DNI_PRZYPOMNIENIA_EWIDENCJI = 10

# Ile podpowiedzi (miejsc, celów, kierowców) z historii pokazuje formularz.
LIMIT_PODPOWIEDZI = 6


# ============================================================================
#  DROBNE
# ============================================================================

def koniec_miesiaca(rok, miesiac) -> date:
    return date(int(rok), int(miesiac), monthrange(int(rok), int(miesiac))[1])


def nazwa_miesiaca(rok, miesiac) -> str:
    """„październik 2026”."""
    return f"{MIESIACE_EWIDENCJI[int(miesiac) - 1]} {int(rok)}"


def opis_trasy(skad, dokad, powrot=False) -> str:
    """„Warszawa – Łódź”, przy powrocie „Warszawa – Łódź – Warszawa”. Brak
    jednej strony zostawia drugą; brak obu daje pusty napis."""
    skad, dokad = normalizuj_nazwe(skad), normalizuj_nazwe(dokad)
    if skad and dokad:
        return f"{skad} – {dokad} – {skad}" if powrot else f"{skad} – {dokad}"
    return skad or dokad


def miejsca_km(km, jednostka=None) -> int:
    """Ile miejsc po przecinku przy kilometrach przejazdu: zero dla pełnych,
    jedno, gdy ułamek naprawdę jest („12,5 km”, a w milach prawie zawsze)."""
    wartosc = dystans_z_km(km or 0, jednostka) or 0.0
    return 0 if abs(wartosc - round(wartosc)) < 0.05 else 1


def tekst_km_przejazdu(km, jednostka=None) -> str:
    """„84 km”, „12,5 km”, „52,2 mi”."""
    j = jednostka_dystansu(jednostka)
    return tekst_dystansu(km or 0, miejsca_km(km, j), j)


def km_przejazdu(km_jednej_strony, powrot=False) -> float:
    """Kilometry CAŁEGO przejazdu do zapisu: przy „tam i z powrotem” dwa razy
    dystans w jedną stronę."""
    km = float(km_jednej_strony or 0)
    return km * 2 if powrot else km


def kwota_kilometrowki(km, stawka, jednostka=None) -> float:
    """Stawka za jednostkę dystansu × dystans, do grosza. Raport sumuje kwoty
    wierszy, więc kolumna kwot zawsze sumuje się do razem."""
    if not stawka:
        return 0.0
    return round((dystans_z_km(km or 0, jednostka) or 0.0) * float(stawka) + 1e-9, 2)


def _procent(czesc, calosc):
    return (czesc / calosc) if calosc else None


# ============================================================================
#  PRZEJAZDY — odczyt i zapis
# ============================================================================

_KOLUMNY = ("id, auto_id, data, data_iso, skad, dokad, cel, km, powrot, sluzbowy, kierowca, licznik, "
            "notatka, notatka_autor, notatka_data, dodane_przez")


def _przejazd(r) -> dict[str, Any]:
    km = float(r["km"] or 0)
    powrot = bool(r["powrot"])
    sluzbowy = bool(r["sluzbowy"])
    d = parsuj_date(r["data"])
    return {
        "id": r["id"], "auto_id": r["auto_id"],
        "data": str(r["data"] or ""),
        "data_obj": d if d != datetime.min.date() else None,
        "skad": str(r["skad"] or ""), "dokad": str(r["dokad"] or ""), "cel": str(r["cel"] or ""),
        "km": km, "km_jednej_strony": km / 2 if powrot else km, "powrot": powrot,
        "sluzbowy": sluzbowy, "rodzaj": RODZAJ_SLUZBOWY if sluzbowy else RODZAJ_PRYWATNY,
        "kierowca": str(r["kierowca"] or ""),
        "licznik": int(r["licznik"]) if r["licznik"] not in (None, "") else None,
        "notatka": r["notatka"], "notatka_autor": r["notatka_autor"], "notatka_data": r["notatka_data"],
        "dodane_przez": r["dodane_przez"],
        "trasa": opis_trasy(r["skad"], r["dokad"], powrot),
    }


def pobierz_przejazd(przejazd_id) -> dict[str, Any] | None:
    if not przejazd_id:
        return None
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        w = conn.execute(f"SELECT {_KOLUMNY} FROM przejazdy WHERE id=?", (przejazd_id,)).fetchone()
    return _przejazd(w) if w else None


def pobierz_przejazdy(auto_id, od_data=None, do_data=None) -> list[dict[str, Any]]:
    """Przejazdy pojazdu od najstarszego (data, potem kolejność wpisania) —
    w tej kolejności numeruje je raport. Zakres dat liczy SQLite po `data_iso`."""
    if not auto_id:
        return []
    warunek, parametry = warunek_zakresu_dat("data_iso", od_data, do_data)
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        wiersze = conn.execute(
            f"SELECT {_KOLUMNY} FROM przejazdy WHERE auto_id=?{warunek} ORDER BY data_iso, id",
            (auto_id, *parametry),
        ).fetchall()
    return [_przejazd(w) for w in wiersze]


def przejazdy_miesiaca(auto_id, rok, miesiac) -> list[dict[str, Any]]:
    return pobierz_przejazdy(auto_id, date(int(rok), int(miesiac), 1), koniec_miesiaca(rok, miesiac))


def czy_ma_przejazdy(auto_id) -> bool:
    if not auto_id:
        return False
    with polacz_baze() as conn:
        return bool(conn.execute("SELECT EXISTS(SELECT 1 FROM przejazdy WHERE auto_id=?)", (auto_id,)).fetchone()[0])


def miesiace_ewidencji(auto_id) -> list[tuple[int, int, int, float]]:
    """[(rok, miesiąc, liczba przejazdów, km)] od najnowszego — do skoku na
    miesiąc z wpisami."""
    if not auto_id:
        return []
    with polacz_baze() as conn:
        wiersze = conn.execute(
            "SELECT substr(data_iso, 1, 7), COUNT(*), COALESCE(SUM(km), 0) FROM przejazdy "
            "WHERE auto_id=? AND data_iso IS NOT NULL GROUP BY 1 ORDER BY 1 DESC", (auto_id,)
        ).fetchall()
    wynik = []
    for klucz, liczba, km in wiersze:
        try:
            rok, miesiac = (int(x) for x in str(klucz).split("-"))
        except ValueError:
            continue
        wynik.append((rok, miesiac, int(liczba), float(km or 0)))
    return wynik


def pierwszy_przejazd(auto_id) -> date | None:
    """Dzień rozpoczęcia ewidencji — najstarszy przejazd pojazdu."""
    if not auto_id:
        return None
    with polacz_baze() as conn:
        w = conn.execute("SELECT MIN(data_iso) FROM przejazdy WHERE auto_id=?", (auto_id,)).fetchone()
    d = parsuj_date(w[0]) if w and w[0] else datetime.min.date()
    return d if d != datetime.min.date() else None


def blad_przejazdu(dane) -> str | None:
    """Powód, dla którego przejazdu nie da się zapisać, albo None."""
    if parsuj_date(dane.get("data")) == datetime.min.date():
        return "Podaj datę przejazdu"
    try:
        km = float(dane.get("km") or 0)
    except (TypeError, ValueError):
        return "Podaj liczbę kilometrów"
    if km <= 0:
        return "Podaj liczbę kilometrów większą od zera"
    if not any(normalizuj_nazwe(dane.get(k)) for k in ("skad", "dokad", "cel")):
        return "Podaj trasę albo cel przejazdu"
    licznik = dane.get("licznik")
    if licznik not in (None, ""):
        try:
            if int(licznik) <= 0:
                return "Stan licznika musi być większy od zera"
        except (TypeError, ValueError):
            return "Stan licznika to liczba całkowita"
    return None


def zapisz_przejazd(auto_id, dane, przejazd_id=None) -> int | None:
    """Nowy przejazd albo poprawka istniejącego. `dane`: data (DD.MM.RRRR),
    skad, dokad, cel, km (CAŁY przejazd, w km), powrot, sluzbowy, kierowca,
    licznik (km po przejeździe albo None). Zwraca id albo None, gdy dane są
    niepełne (`blad_przejazdu`) albo poprawiany przejazd zniknął.

    Autor (`dodane_przez`) to imię z Ustawień i nie zmienia się przy edycji —
    współautor poprawia swoje przejazdy po podpisie, nie po kierowcy."""
    if not auto_id or blad_przejazdu(dane):
        return None
    data = str(dane["data"]).strip()
    licznik = dane.get("licznik")
    wartosci = (
        data, na_iso(data),
        normalizuj_nazwe(dane.get("skad")) or None,
        normalizuj_nazwe(dane.get("dokad")) or None,
        normalizuj_nazwe(dane.get("cel")) or None,
        round(float(dane["km"]), 2),
        1 if dane.get("powrot") else 0,
        1 if dane.get("sluzbowy", True) else 0,
        normalizuj_nazwe(dane.get("kierowca")) or None,
        int(licznik) if licznik not in (None, "") else None,
    )
    with polacz_baze() as conn:
        if przejazd_id:
            kursor = conn.execute(
                "UPDATE przejazdy SET data=?, data_iso=?, skad=?, dokad=?, cel=?, km=?, powrot=?, sluzbowy=?, "
                "kierowca=?, licznik=? WHERE id=? AND auto_id=?", wartosci + (przejazd_id, auto_id),
            )
            return przejazd_id if kursor.rowcount else None
        kursor = conn.execute(
            "INSERT INTO przejazdy (auto_id, data, data_iso, skad, dokad, cel, km, powrot, sluzbowy, kierowca, "
            "licznik, dodane_przez) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (auto_id,) + wartosci + (pobierz_moje_imie(),),
        )
        return kursor.lastrowid


def ustaw_rodzaj_przejazdu(przejazd_id, sluzbowy) -> bool:
    """Szybka zmiana służbowy ↔ prywatny z menu karty."""
    if not przejazd_id:
        return False
    with polacz_baze() as conn:
        return bool(conn.execute("UPDATE przejazdy SET sluzbowy=? WHERE id=?",
                                 (1 if sluzbowy else 0, przejazd_id)).rowcount)


# ============================================================================
#  PODPOWIEDZI Z HISTORII
# ============================================================================

def podpowiedzi_przejazdow(auto_id, limit=LIMIT_PODPOWIEDZI) -> dict[str, list[str]]:
    """Najczęstsze miejsca (skąd i dokąd razem), cele i kierowcy pojazdu — po
    `klucz_nazwy`, więc „Biuro” i „biuro ” to jedno miejsce. Przy remisie
    wygrywa świeższe; pisownia z ostatniego użycia."""
    wynik = {"miejsca": [], "cele": [], "kierowcy": []}
    if not auto_id:
        return wynik
    with polacz_baze() as conn:
        wiersze = conn.execute(
            "SELECT skad, dokad, cel, kierowca FROM przejazdy WHERE auto_id=? ORDER BY data_iso, id", (auto_id,)
        ).fetchall()

    def zlicz(wartosci):
        licznik, pisownia, ostatnio = {}, {}, {}
        for i, wartosc in enumerate(wartosci):
            tekst = normalizuj_nazwe(wartosc)
            klucz = klucz_nazwy(tekst)
            if not klucz:
                continue
            licznik[klucz] = licznik.get(klucz, 0) + 1
            pisownia[klucz] = tekst
            ostatnio[klucz] = i
        kolejnosc = sorted(licznik, key=lambda k: (-licznik[k], -ostatnio[k]))
        return [pisownia[k] for k in kolejnosc[:limit]]

    miejsca = []
    for skad, dokad, _, _ in wiersze:
        miejsca += [skad, dokad]
    wynik["miejsca"] = zlicz(miejsca)
    wynik["cele"] = zlicz(w[2] for w in wiersze)
    wynik["kierowcy"] = zlicz(w[3] for w in wiersze)
    return wynik


def ostatni_przejazd_trasy(auto_id, skad, dokad, wyklucz_id=None) -> dict[str, Any] | None:
    """Ostatni przejazd tą samą trasą — w którąkolwiek stronę, bo z Łodzi do
    Warszawy jest tyle samo, co z Warszawy do Łodzi. Formularz podpowiada
    z niego kilometry."""
    a, b = klucz_nazwy(skad), klucz_nazwy(dokad)
    if not auto_id or not a or not b:
        return None
    for p in reversed(pobierz_przejazdy(auto_id)):
        if p["id"] == wyklucz_id:
            continue
        if {klucz_nazwy(p["skad"]), klucz_nazwy(p["dokad"])} == {a, b}:
            return {"km_jednej_strony": p["km_jednej_strony"], "powrot": p["powrot"], "km": p["km"],
                    "data": p["data"]}
    return None


def poprzedni_stan_licznika(auto_id, data_str, licznik=None, wyklucz_id=None) -> dict[str, Any] | None:
    """Ostatni znany stan licznika z dnia przejazdu albo wcześniej — z niego
    formularz liczy kilometry, gdy wpisany jest stan po przejeździe. Przy
    podanym `licznik` tylko odczyty nie wyższe od niego (dwa przejazdy tego
    samego dnia: drugi liczy od pierwszego). Sam poprawiany przejazd się nie liczy."""
    d = parsuj_date(data_str)
    if not auto_id or d == datetime.min.date():
        return None
    kandydaci = [
        w for w in pobierz_pelna_historie_przebiegu(auto_id)
        if w["data_obj"] <= d
        and not (w["zrodlo"] == "przejazd" and w["id"] == wyklucz_id)
        and (licznik is None or w["przebieg"] <= int(licznik))
    ]
    if not kandydaci:
        return None
    w = max(kandydaci, key=lambda x: (x["data_obj"], x["przebieg"]))
    return {"przebieg": w["przebieg"], "data": w["data"], "data_obj": w["data_obj"],
            "etykieta": w["etykieta_zrodla"], "opis": w["opis"]}


# ============================================================================
#  LICZNIK NA GRANICACH OKRESU I NIEOPISANE KILOMETRY
# ============================================================================
# Licznik mówi, ILE przejechano, ewidencja — PO CO. Różnica to „nieopisane
# km”. Odczyt na początek okresu to ostatni znany stan sprzed miesiąca (stan
# „na koniec poprzedniego okresu”), na koniec — ostatni w miesiącu. Odczyty
# rzadko leżą na samych granicach, więc porównujemy z przejazdami z TEGO SAMEGO
# okna: po dniu odczytu początkowego, do dnia odczytu końcowego włącznie
# (odczyt traktujemy jako zrobiony wieczorem). Przejazd ze stanem licznika jest
# sam takim odczytem — jego kilometry są przed nim, więc liczą się do okna,
# które na nim się kończy.

def _punkty_licznika(auto_id):
    punkty = []
    for data_str, przebieg in pobierz_historie_przebiegu(auto_id):
        d = parsuj_date(data_str)
        if d != datetime.min.date():
            punkty.append((d, int(przebieg)))
    return punkty


def _suma_km(auto_id, od_data, do_data) -> float:
    """Kilometry przejazdów w [od_data, do_data] — po `data_iso` w SQL."""
    warunek, parametry = warunek_zakresu_dat("data_iso", od_data, do_data)
    with polacz_baze() as conn:
        w = conn.execute(f"SELECT COALESCE(SUM(km), 0) FROM przejazdy WHERE auto_id=?{warunek}",
                         (auto_id, *parametry)).fetchone()
    return float(w[0] or 0)


def licznik_okresu(auto_id, od_data, do_data, punkty=None) -> dict[str, Any]:
    """Stan licznika na początek i koniec okresu i porównanie z ewidencją.

    Klucze: `start`, `data_start`, `start_przed` (odczyt sprzed okresu — tak,
    jak powinno być), `koniec`, `data_koniec`, `koniec_na_ostatni_dzien`,
    `km` (koniec − start; None bez dwóch odczytów), `opisane_km` (przejazdy
    z okna odczytów), `nieopisane_km` (km − opisane; ujemne = w ewidencji
    więcej niż na liczniku), `cofka` (licznik niższy na końcu)."""
    punkty = _punkty_licznika(auto_id) if punkty is None else punkty
    przed = [p for p in punkty if p[0] < od_data]
    w_okresie = [p for p in punkty if od_data <= p[0] <= do_data]

    start = przed[-1] if przed else (w_okresie[0] if w_okresie else None)
    koniec = w_okresie[-1] if w_okresie else None
    if start is not None and koniec is not None and koniec[0] <= start[0]:
        koniec = None  # jedyny odczyt okresu jest jego początkiem
    wynik = {
        "start": start[1] if start else None, "data_start": start[0] if start else None,
        "start_przed": bool(przed),
        "koniec": koniec[1] if koniec else None, "data_koniec": koniec[0] if koniec else None,
        "koniec_na_ostatni_dzien": bool(koniec and koniec[0] == do_data),
        "km": None, "opisane_km": None, "nieopisane_km": None, "cofka": False,
    }
    if start is None or koniec is None:
        return wynik
    km = koniec[1] - start[1]
    if km < 0:
        wynik["cofka"] = True
        return wynik
    opisane = _suma_km(auto_id, start[0] + timedelta(days=1), koniec[0])
    wynik.update({"km": km, "opisane_km": opisane, "nieopisane_km": round(km - opisane, 1)})
    return wynik


def stan_na_koniec_miesiaca(auto_id, rok, miesiac, dzis=None) -> dict[str, Any]:
    """Co wiadomo o liczniku na ostatni dzień miesiąca — dla „Zamknij miesiąc”.

    `zamkniety` — jest odczyt (z dowolnego źródła) z ostatniego dnia.
    `podpowiedz` — ostatni odczyt w miesiącu (albo sprzed niego) plus przejazdy
    wpisane po nim: przy kompletnej ewidencji to dokładnie stan na koniec.
    `mozna_zamknac` — miesiąc już się skończył albo trwa jego ostatni dzień."""
    dzis = dzis or datetime.now().date()
    koniec = koniec_miesiaca(rok, miesiac)
    punkty = [p for p in _punkty_licznika(auto_id) if p[0] <= koniec]
    ostatni = punkty[-1] if punkty else None
    wynik = {
        "koniec": koniec, "zamkniety": bool(ostatni and ostatni[0] == koniec),
        "mozna_zamknac": koniec <= dzis,
        "odczyt": ostatni[1] if ostatni else None, "data_odczytu": ostatni[0] if ostatni else None,
        "km_po_odczycie": 0.0, "podpowiedz": None,
    }
    if ostatni:
        po = _suma_km(auto_id, ostatni[0] + timedelta(days=1), koniec) if ostatni[0] < koniec else 0.0
        wynik["km_po_odczycie"] = po
        wynik["podpowiedz"] = int(round(ostatni[1] + po))
    return wynik


def zamknij_miesiac_ewidencji(auto_id, rok, miesiac, przebieg) -> bool:
    """Zapisuje stan licznika na ostatni dzień miesiąca jako odczyt ze źródła
    „ewidencja” (ten sam dzień nadpisuje odczyt, nie dubluje go). To on jest
    „stanem na koniec okresu” w ewidencji do VAT i początkiem następnego."""
    try:
        przebieg = int(przebieg)
    except (TypeError, ValueError):
        return False
    if not auto_id or przebieg <= 0:
        return False
    dodaj_odczyt_przebiegu(auto_id, przebieg, koniec_miesiaca(rok, miesiac).strftime("%d.%m.%Y"),
                           zrodlo="ewidencja")
    return True


# ============================================================================
#  KILOMETRÓWKA
# ============================================================================

def pojemnosc_silnika_cm3(tekst) -> int | None:
    """Pojemność z pola tekstowego pojazdu: „1598”, „1598 cm3”, „1.6”, „1,6 l”
    → cm³. Liczba poniżej 20 to litry."""
    wartosc = _liczba_lub_none(tekst)
    if not wartosc:
        return None
    return int(round(wartosc * 1000)) if wartosc < 20 else int(round(wartosc))


def _dane_pojazdu(auto_id) -> dict[str, Any]:
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        w = conn.execute("SELECT nazwa, marka, model, nr_rej, pojemnosc_silnika, typ_paliwa, status "
                         "FROM samochody WHERE id=?", (auto_id,)).fetchone()
    return dict(w) if w else {}


def domyslna_stawka_kilometrowki(auto_id) -> float | None:
    """Stawka maksymalna z rozporządzenia według pojemności silnika — tylko
    przy złotówkach i kilometrach, bo to stawka w zł za km. Bez pojemności
    (choćby elektryk) brak podpowiedzi: zgadnięta stawka byłaby kwotą z sufitu."""
    if pobierz_walute() != "PLN" or jednostka_dystansu() != "km":
        return None
    cm3 = pojemnosc_silnika_cm3(_dane_pojazdu(auto_id).get("pojemnosc_silnika"))
    if not cm3:
        return None
    return STAWKI_KILOMETROWKI[0][1] if cm3 <= PROG_POJEMNOSCI_KILOMETROWKI else STAWKI_KILOMETROWKI[1][1]


def stawka_kilometrowki(auto_id) -> float | None:
    """Stawka z ustawień ewidencji pojazdu, a bez niej podpowiedź z pojemności."""
    return pobierz_ustawienia_ewidencji(auto_id).get("stawka") or domyslna_stawka_kilometrowki(auto_id)


def stawka_ponad_limit(auto_id, stawka) -> float | None:
    """Limit z rozporządzenia, jeśli stawka go przekracza (tylko zł i km)."""
    if not stawka or pobierz_walute() != "PLN" or jednostka_dystansu() != "km":
        return None
    cm3 = pojemnosc_silnika_cm3(_dane_pojazdu(auto_id).get("pojemnosc_silnika"))
    limit = (STAWKI_KILOMETROWKI[0][1] if cm3 and cm3 <= PROG_POJEMNOSCI_KILOMETROWKI
             else STAWKA_MAKSYMALNA_SAMOCHODU)
    return limit if float(stawka) > limit + 1e-9 else None


# ============================================================================
#  MIESIĄC W EWIDENCJI
# ============================================================================

def _braki(przejazdy):
    """Ile przejazdów nie ma tego, czego wymaga ewidencja: celu, trasy, kierowcy."""
    return {
        "bez_celu": sum(1 for p in przejazdy if not p["cel"]),
        "bez_trasy": sum(1 for p in przejazdy if not (p["skad"] and p["dokad"])),
        "bez_kierowcy": sum(1 for p in przejazdy if not p["kierowca"]),
    }


def podsumowanie_ewidencji(auto_id, rok, miesiac, dzis=None, z_kosztami=True) -> dict[str, Any]:
    """Miesiąc ewidencji w liczbach — ekran, kafelek, przypomnienie i raport.

    Kilometry: `km`, `km_sluzbowe`, `km_prywatne`, `udzial_sluzbowy` (0–1,
    None bez przejazdów). Koszty miesiąca (`koszty`: paliwo, serwis, inne,
    razem) dzielone w proporcji kilometrów (`koszty_sluzbowe`,
    `koszty_prywatne`) — nieopisane km do podziału NIE wchodzą, ekran mówi
    o nich osobno. `kilometrowka`: stawka, km i kwota (suma kwot przejazdów).
    `licznik`: patrz `licznik_okresu`. `rok_do_dzis`: kilometry od stycznia do
    końca tego miesiąca."""
    dzis = dzis or datetime.now().date()
    rok, miesiac = int(rok), int(miesiac)
    od, do = date(rok, miesiac, 1), koniec_miesiaca(rok, miesiac)
    ustawienia = pobierz_ustawienia_ewidencji(auto_id)
    j = jednostka_dystansu()

    przejazdy = pobierz_przejazdy(auto_id, od, do)
    sluzbowe = [p for p in przejazdy if p["sluzbowy"]]
    km = sum(p["km"] for p in przejazdy)
    km_sluzbowe = sum(p["km"] for p in sluzbowe)
    udzial = _procent(km_sluzbowe, km)

    # Stawka wpisana w ustawieniach ewidencji; podpowiedź z pojemności silnika
    # tylko wtedy, gdy auto jest rozliczane kilometrówką — przy podziale kosztów
    # czy ewidencji do VAT kwota „z rozporządzenia” byłaby liczbą z sufitu.
    stawka = ustawienia["stawka"] or (domyslna_stawka_kilometrowki(auto_id)
                                      if ustawienia["tryb"] == "kilometrowka" else None)
    kwota = round(sum(kwota_kilometrowki(p["km"], stawka, j) for p in sluzbowe), 2) if stawka else None

    kierowcy = {}
    for p in przejazdy:
        if p["kierowca"]:
            klucz = klucz_nazwy(p["kierowca"])
            nazwa, suma = kierowcy.get(klucz, (p["kierowca"], 0.0))
            kierowcy[klucz] = (nazwa, suma + p["km"])

    wynik = {
        "rok": rok, "miesiac": miesiac, "od": od, "do": do,
        "nazwa": nazwa_miesiaca(rok, miesiac),
        "w_toku": od <= dzis <= do, "przyszly": od > dzis, "zakonczony": do < dzis,
        "tryb": ustawienia["tryb"],
        "przejazdy": przejazdy, "liczba": len(przejazdy),
        "liczba_sluzbowych": len(sluzbowe), "liczba_prywatnych": len(przejazdy) - len(sluzbowe),
        "km": km, "km_sluzbowe": km_sluzbowe, "km_prywatne": km - km_sluzbowe,
        "udzial_sluzbowy": udzial,
        "kierowcy": sorted(kierowcy.values(), key=lambda kv: -kv[1]),
        "kilometrowka": {"stawka": stawka, "km": km_sluzbowe, "kwota": kwota,
                         "ponad_limit": stawka_ponad_limit(auto_id, stawka)},
        "braki": _braki(przejazdy),
        "licznik": licznik_okresu(auto_id, od, min(do, dzis) if od <= dzis else do),
        "koszty": None, "koszty_sluzbowe": None, "koszty_prywatne": None,
    }
    if z_kosztami:
        koszty = koszty_w_okresie(auto_id, od, do)
        wynik["koszty"] = koszty
        if udzial is not None:
            wynik["koszty_sluzbowe"] = round(koszty["razem"] * udzial, 2)
            wynik["koszty_prywatne"] = round(koszty["razem"] - wynik["koszty_sluzbowe"], 2)

    km_roku = pobierz_przejazdy(auto_id, date(rok, 1, 1), do)
    km_r = sum(p["km"] for p in km_roku)
    km_r_sl = sum(p["km"] for p in km_roku if p["sluzbowy"])
    wynik["rok_do_dzis"] = {"km": km_r, "km_sluzbowe": km_r_sl, "udzial_sluzbowy": _procent(km_r_sl, km_r),
                            "liczba": len(km_roku)}
    return wynik


# Czego wymaga każdy układ: VAT — celu, trasy i kierowcy; kilometrówka — celu
# i trasy (kierowcą jest osoba z nagłówka); podział — celu.
WYMAGANE_POLA_UKLADU = {
    "vat": ("bez_celu", "bez_trasy", "bez_kierowcy"),
    "kilometrowka": ("bez_celu", "bez_trasy"),
    "podzial": ("bez_celu",),
}


def zdania_ewidencji(podsumowanie, uklad=None) -> list[tuple[str, str]]:
    """Ostrzeżenia miesiąca jako (poziom, zdanie): „warning” albo „info”.
    Te same zdania stoją na ekranie (dla trybu pojazdu) i pod tabelą raportu
    (dla wybranego układu)."""
    p = podsumowanie
    uklad = uklad if uklad in UKLADY_RAPORTU_EWIDENCJI else p["tryb"]
    zdania = []
    j = jednostka_dystansu()
    if uklad == "vat" and p["liczba_prywatnych"]:
        zdania.append(("warning", (
            f"W tym miesiącu są przejazdy prywatne: {p['liczba_prywatnych']} "
            f"({tekst_km_przejazdu(p['km_prywatne'], j)}). Ewidencja do pełnego odliczenia VAT dotyczy auta "
            "używanego wyłącznie do działalności — sprawdź te wpisy.")))
    przejazdy = [x for x in p["przejazdy"] if x["sluzbowy"]] if uklad == "kilometrowka" else p["przejazdy"]
    braki = _braki(przejazdy)
    for klucz, slowo in (("bez_celu", "celu wyjazdu"), ("bez_trasy", "trasy (skąd – dokąd)"),
                         ("bez_kierowcy", "kierowcy")):
        if braki[klucz] and klucz in WYMAGANE_POLA_UKLADU[uklad]:
            zdania.append(("warning", f"{liczba_z_odmiana(braki[klucz], 'przejazd', 'przejazdy', 'przejazdów')} "
                                      f"bez {slowo}."))
    # Przy kilometrówce auto jest prywatne: kilometry spoza ewidencji to zwykłe
    # jazdy prywatne, a nie brak. Liczą się przy podziale kosztów i przy VAT.
    licznik = p["licznik"]
    reszta = licznik["nieopisane_km"]
    sprawdz_licznik = uklad != "kilometrowka"
    if sprawdz_licznik and licznik["cofka"]:
        zdania.append(("warning", "Licznik na koniec okresu jest niższy niż na początku — sprawdź odczyty "
                                  "w Historii licznika."))
    elif sprawdz_licznik and reszta is not None and p["liczba"] and reszta >= 1:
        zdania.append(("warning", f"Licznik pokazuje o {tekst_km_przejazdu(reszta, j)} więcej, niż opisuje "
                                  "ewidencja — dopisz brakujące przejazdy."))
    elif sprawdz_licznik and reszta is not None and p["liczba"] and reszta <= -1:
        zdania.append(("warning", f"W ewidencji jest o {tekst_km_przejazdu(-reszta, j)} więcej, niż pokazuje "
                                  "licznik — sprawdź kilometry przejazdów albo odczyty."))
    if uklad == "kilometrowka":
        kilometrowka = p["kilometrowka"]
        if not kilometrowka["stawka"]:
            zdania.append(("info", "Ustaw stawkę za kilometr, a policzę kwotę kilometrówki."))
        elif kilometrowka["ponad_limit"]:
            zdania.append(("warning", (
                f"Stawka {liczba_na_tekst(kilometrowka['stawka'], 2)} PLN jest wyższa niż maksymalna "
                f"z rozporządzenia ({liczba_na_tekst(kilometrowka['ponad_limit'], 2)} PLN za km).")))
    return zdania


# ============================================================================
#  KAFELEK KOKPITU I PRZYPOMNIENIE
# ============================================================================

def kafel_ewidencji(auto_id, dzis=None) -> dict[str, Any] | None:
    """Bieżący miesiąc na kafelek kokpitu. None — auto bez ani jednego
    przejazdu (kafelek „nie dotyczy”, chowany)."""
    if not czy_ma_przejazdy(auto_id):
        return None
    dzis = dzis or datetime.now().date()
    p = podsumowanie_ewidencji(auto_id, dzis.year, dzis.month, dzis=dzis, z_kosztami=False)
    return {
        "rok": p["rok"], "miesiac": p["miesiac"], "tryb": p["tryb"],
        "liczba": p["liczba"], "km": p["km"], "km_sluzbowe": p["km_sluzbowe"],
        "udzial_sluzbowy": p["udzial_sluzbowy"], "kwota": p["kilometrowka"]["kwota"],
        "nieopisane_km": p["licznik"]["nieopisane_km"],
    }


def przypomnienie_ewidencji(auto_id, dzis=None) -> dict[str, Any] | None:
    """Poprzedni miesiąc czeka na zamknięcie: ma przejazdy, a nie ma stanu
    licznika z ostatniego dnia. Tylko w pierwszych DNI_PRZYPOMNIENIA_EWIDENCJI
    dniach miesiąca, tylko auto w użyciu i tylko dla roli, która może dopisać
    odczyt."""
    dzis = dzis or datetime.now().date()
    if not auto_id or dzis.day > DNI_PRZYPOMNIENIA_EWIDENCJI or not czy_moge_dodawac(auto_id):
        return None
    with polacz_baze() as conn:
        w = conn.execute("SELECT status FROM samochody WHERE id=?", (auto_id,)).fetchone()
    if not w or str(w[0] or STATUS_POJAZDU_AKTYWNY) != STATUS_POJAZDU_AKTYWNY:
        return None
    ostatni_dzien = dzis.replace(day=1) - timedelta(days=1)
    rok, miesiac = ostatni_dzien.year, ostatni_dzien.month
    przejazdy = przejazdy_miesiaca(auto_id, rok, miesiac)
    if not przejazdy:
        return None
    if stan_na_koniec_miesiaca(auto_id, rok, miesiac, dzis=dzis)["zamkniety"]:
        return None
    return {"rok": rok, "miesiac": miesiac, "liczba": len(przejazdy),
            "km": sum(p["km"] for p in przejazdy), "koniec": ostatni_dzien,
            "klucz": f"ewidencja:{rok:04d}-{miesiac:02d}"}


# ============================================================================
#  RAPORT MIESIĘCZNY — treść (rysuje db/raporty.py)
# ============================================================================

def _tekst_licznika(wartosc, data_odczytu, j, wymagany_dzien=None):
    if wartosc is None:
        return "brak odczytu"
    tekst = tekst_dystansu(wartosc, 0, j)
    if data_odczytu and data_odczytu != wymagany_dzien:
        tekst += f" (odczyt z {data_odczytu.strftime('%d.%m.%Y')})"
    return tekst


def _kwota_tekstem(wartosc, waluta):
    return f"{liczba_na_tekst(wartosc or 0, 2, SEPARATOR_TYSIECY)} {waluta}"


def _liczba_km(km, j):
    """Kilometry do komórki tabeli — bez jednostki (stoi w nagłówku kolumny)."""
    return liczba_na_tekst(dystans_z_km(km or 0, j), miejsca_km(km, j), SEPARATOR_TYSIECY)


def _procent_tekstem(udzial):
    return f"{liczba_na_tekst((udzial or 0) * 100, 0)}%"


def dane_raportu_ewidencji(auto_id, rok, miesiac, uklad=None, dzis=None) -> dict[str, Any]:
    """Treść raportu miesiąca w wybranym układzie — wszystko jako gotowe napisy.

    • „vat” — ewidencja przebiegu w układzie z art. 86a ust. 7 ustawy o VAT:
      numer rejestracyjny, okres, początek ewidencji, stan licznika na początek
      i koniec okresu, kolejne numery wpisów, data, cel, trasa, kilometry,
      kierowca, suma kilometrów i miejsce na potwierdzenie podatnika.
    • „kilometrowka” — tylko przejazdy służbowe, ze stawką i kwotą przy każdym;
      dane osoby i pojazdu (z pojemnością silnika), podpisy osoby i pracodawcy.
    • „podzial” — wszystkie przejazdy z rodzajem, podział kilometrów i kosztów
      miesiąca.

    Zwraca {uklad, tytul, podtytul, naglowek: [(etykieta, wartość)], kolumny:
    [(nagłówek, szerokość względna, wyrównanie „L”/„R”/„C”)], wiersze, razem
    (wiersz sumy albo None), podsumowanie: [(etykieta, wartość)], uwagi, podpisy,
    nazwa_pliku}."""
    p = podsumowanie_ewidencji(auto_id, rok, miesiac, dzis=dzis)
    uklad = uklad if uklad in UKLADY_RAPORTU_EWIDENCJI else p["tryb"]
    j = jednostka_dystansu()
    waluta = pobierz_walute()
    pojazd = _dane_pojazdu(auto_id)
    osoba = pobierz_dane_osoby_ewidencji()
    imie = pobierz_moje_imie()
    if not osoba["osoba"] and imie and imie != "Kierowca":
        osoba["osoba"] = imie
    nazwa_auta = pojazd.get("nazwa") or "Pojazd"
    marka_model = " ".join(x for x in (pojazd.get("marka"), pojazd.get("model")) if x)
    okres = f"{p['od'].strftime('%d.%m.%Y')} – {p['do'].strftime('%d.%m.%Y')}"

    def km_tekst(km):
        return _liczba_km(km, j)

    kol_km = f"Liczba {j}" if j == "km" else f"Dystans ({j})"
    licznik = p["licznik"]
    poprzedni_koniec = p["od"] - timedelta(days=1)

    naglowek = [("Pojazd", f"{nazwa_auta}" + (f" ({marka_model})" if marka_model and marka_model != nazwa_auta else "")),
                ("Numer rejestracyjny", pojazd.get("nr_rej") or "—"),
                ("Okres rozliczeniowy", okres)]
    podsumowanie, uwagi, podpisy = [], [], []
    przejazdy = p["przejazdy"]
    razem = None

    if uklad == "kilometrowka":
        przejazdy = [x for x in przejazdy if x["sluzbowy"]]
        stawka = stawka_kilometrowki(auto_id)
        cm3 = pojemnosc_silnika_cm3(pojazd.get("pojemnosc_silnika"))
        naglowek = ([("Osoba używająca pojazdu", osoba["osoba"] or "……………………………………"),
                     ("Adres zamieszkania", osoba["adres"] or "……………………………………")]
                    + ([("Pracodawca", osoba["pracodawca"])] if osoba["pracodawca"] else [])
                    + naglowek[:2]
                    + [("Pojemność silnika", f"{liczba_na_tekst(cm3, 0, ' ')} cm³" if cm3 else "—"),
                       naglowek[2],
                       (f"Stawka za 1 {j}", _kwota_tekstem(stawka, waluta) if stawka else "nie ustawiona")])
        kolumny = [("Lp.", 6, "C"), ("Data", 13, "C"), ("Cel wyjazdu", 30, "L"),
                   ("Opis trasy (skąd – dokąd)", 37, "L"), (kol_km, 10, "R"), ("Stawka", 10, "R"),
                   (f"Kwota ({waluta})", 14, "R")]
        wiersze, suma_kwot = [], 0.0
        for i, x in enumerate(przejazdy, 1):
            kwota = kwota_kilometrowki(x["km"], stawka, j) if stawka else None
            suma_kwot += kwota or 0.0
            wiersze.append([str(i), x["data"], x["cel"], x["trasa"], km_tekst(x["km"]),
                            liczba_na_tekst(stawka, 2) if stawka else "",
                            liczba_na_tekst(kwota, 2, SEPARATOR_TYSIECY) if stawka else ""])
        suma_km = sum(x["km"] for x in przejazdy)
        razem = ["", "", "Razem", "", km_tekst(suma_km), "",
                 liczba_na_tekst(round(suma_kwot, 2), 2, SEPARATOR_TYSIECY) if stawka else ""]
        podsumowanie = [(f"Przejechane służbowo ({j})", km_tekst(suma_km)),
                        ("Kwota do zwrotu", _kwota_tekstem(round(suma_kwot, 2), waluta) if stawka else "—")]
        p = {**p, "kilometrowka": {**p["kilometrowka"], "stawka": stawka,
                                   "ponad_limit": stawka_ponad_limit(auto_id, stawka)}}
        podpisy = ["Podpis osoby używającej pojazdu", "Data, podpis i pieczęć pracodawcy"]
        tytul = "Ewidencja przebiegu pojazdu — kilometrówka"

    elif uklad == "vat":
        poczatek = pierwszy_przejazd(auto_id)
        naglowek += [
            ("Ewidencja prowadzona od", poczatek.strftime("%d.%m.%Y") if poczatek else "—"),
            ("Stan licznika na początek okresu",
             _tekst_licznika(licznik["start"], licznik["data_start"], j, poprzedni_koniec)),
            ("Stan licznika na koniec okresu",
             _tekst_licznika(licznik["koniec"], licznik["data_koniec"], j, p["do"])),
        ]
        kolumny = [("Lp.", 6, "C"), ("Data", 13, "C"), ("Cel wyjazdu", 29, "L"),
                   ("Opis trasy (skąd – dokąd)", 34, "L"), (kol_km, 10, "R"),
                   ("Kierowca (imię i nazwisko)", 24, "L")]
        wiersze = [[str(i), x["data"], x["cel"], x["trasa"], km_tekst(x["km"]), x["kierowca"]]
                   for i, x in enumerate(przejazdy, 1)]
        razem = ["", "", "Razem", "", km_tekst(p["km"]), ""]
        podsumowanie = [(f"Liczba przejechanych {j} w okresie", km_tekst(p["km"]))]
        if licznik["km"] is not None:
            podsumowanie.append((f"Według licznika ({licznik['data_start'].strftime('%d.%m')}"
                                 f" – {licznik['data_koniec'].strftime('%d.%m')})", f"{km_tekst(licznik['km'])} {j}"))
        if not licznik["koniec_na_ostatni_dzien"]:
            uwagi.append("Brak stanu licznika z ostatniego dnia okresu — zapisz go w aplikacji przyciskiem "
                         "„Zamknij miesiąc”.")
        podpisy = ["Potwierdzam zgodność wpisów — data i podpis podatnika"]
        tytul = "Ewidencja przebiegu pojazdu"

    else:
        uklad = "podzial"
        kolumny = [("Lp.", 6, "C"), ("Data", 13, "C"), ("Cel", 26, "L"), ("Trasa (skąd – dokąd)", 31, "L"),
                   (kol_km, 10, "R"), ("Rodzaj", 12, "C"), ("Kierowca", 20, "L")]
        wiersze = [[str(i), x["data"], x["cel"], x["trasa"], km_tekst(x["km"]), x["rodzaj"].lower(), x["kierowca"]]
                   for i, x in enumerate(przejazdy, 1)]
        razem = ["", "", "Razem", "", km_tekst(p["km"]), "", ""]
        udzial = p["udzial_sluzbowy"]
        proc = _procent_tekstem
        podsumowanie = [
            ("Służbowe", f"{km_tekst(p['km_sluzbowe'])} {j} ({proc(udzial)})" if udzial is not None else "—"),
            ("Prywatne", f"{km_tekst(p['km_prywatne'])} {j} ({proc(1 - udzial)})" if udzial is not None else "—"),
            ("Razem", f"{km_tekst(p['km'])} {j}"),
        ]
        koszty = p["koszty"] or {}
        if koszty.get("razem"):
            podsumowanie.append(("Koszty miesiąca",
                                 f"{_kwota_tekstem(koszty['razem'], waluta)} (paliwo "
                                 f"{_kwota_tekstem(koszty.get('paliwo'), waluta)}, serwis "
                                 f"{_kwota_tekstem(koszty.get('serwis'), waluta)}, inne "
                                 f"{_kwota_tekstem(koszty.get('inne'), waluta)})"))
            if p["koszty_sluzbowe"] is not None:
                podsumowanie += [(f"Część służbowa ({proc(udzial)})", _kwota_tekstem(p["koszty_sluzbowe"], waluta)),
                                 (f"Część prywatna ({proc(1 - udzial)})", _kwota_tekstem(p["koszty_prywatne"], waluta))]
        if p["kilometrowka"]["stawka"] and p["km_sluzbowe"]:
            podsumowanie.append(("Kilometrówka", f"{_kwota_tekstem(p['kilometrowka']['kwota'], waluta)} "
                                                 f"({liczba_na_tekst(p['kilometrowka']['stawka'], 2)} {waluta}/{j})"))
        podpisy = ["Data i podpis"]
        tytul = "Ewidencja przebiegu — podział prywatne / służbowe"

    if licznik["nieopisane_km"] is not None and uklad != "kilometrowka":
        podsumowanie.append(("Nieopisane (licznik a ewidencja)", f"{km_tekst(licznik['nieopisane_km'])} {j}"))
    for poziom, zdanie in zdania_ewidencji(p, uklad):
        if poziom == "warning" and zdanie not in uwagi:
            uwagi.append(zdanie)

    return {
        "uklad": uklad, "tytul": tytul,
        "podtytul": f"{nazwa_miesiaca(rok, miesiac).capitalize()} • {nazwa_auta}",
        "naglowek": naglowek, "kolumny": kolumny, "wiersze": wiersze, "razem": razem if wiersze else None,
        "podsumowanie": podsumowanie, "uwagi": uwagi, "podpisy": podpisy,
        "nazwa_pliku": f"ewidencja_{uklad}_{int(rok):04d}-{int(miesiac):02d}",
        "liczba_przejazdow": len(przejazdy),
    }


__all__ = [
    "DNI_PRZYPOMNIENIA_EWIDENCJI",
    "LIMIT_PODPOWIEDZI",
    "MIESIACE_EWIDENCJI",
    "MIESIACE_EWIDENCJI_MIEJSCOWNIK",
    "PROG_POJEMNOSCI_KILOMETROWKI",
    "RODZAJ_PRYWATNY",
    "RODZAJ_SLUZBOWY",
    "STAWKA_MAKSYMALNA_SAMOCHODU",
    "STAWKI_KILOMETROWKI",
    "UKLADY_RAPORTU_EWIDENCJI",
    "WYMAGANE_POLA_UKLADU",
    "blad_przejazdu",
    "czy_ma_przejazdy",
    "dane_raportu_ewidencji",
    "domyslna_stawka_kilometrowki",
    "kafel_ewidencji",
    "km_przejazdu",
    "koniec_miesiaca",
    "kwota_kilometrowki",
    "licznik_okresu",
    "miejsca_km",
    "miesiace_ewidencji",
    "nazwa_miesiaca",
    "opis_trasy",
    "ostatni_przejazd_trasy",
    "pierwszy_przejazd",
    "pobierz_przejazd",
    "pobierz_przejazdy",
    "podpowiedzi_przejazdow",
    "podsumowanie_ewidencji",
    "pojemnosc_silnika_cm3",
    "poprzedni_stan_licznika",
    "przejazdy_miesiaca",
    "przypomnienie_ewidencji",
    "stan_na_koniec_miesiaca",
    "stawka_kilometrowki",
    "stawka_ponad_limit",
    "tekst_km_przejazdu",
    "ustaw_rodzaj_przejazdu",
    "zamknij_miesiac_ewidencji",
    "zapisz_przejazd",
    "zdania_ewidencji",
]
