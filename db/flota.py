"""Flota (N-07): wszystkie auta naraz. Wydatki miesiąca i roku do dziś — każdego auta i razem,
z tym samym okresem rok wcześniej (wszystkie auta, także sprzedane); auto sprzedane w tym roku
dolicza swój rok. Terminy z osi przyszłości każdego aktywnego auta złożone w jedną oś (kształt
`os_przyszlosci`, pozycja niesie `pojazd`) i kondycja z największą karą. Pilne (odznaka „flota”,
kafelek) z okna OKNO_PILNYCH_FLOTY — próg dokumentu sięga roku."""

import sqlite3
from datetime import datetime
from typing import Any

from date import parsuj_date

from .stale import STATUS_POJAZDU_AKTYWNY, STATUS_POJAZDU_SPRZEDANY
from .pamiec import z_pamieci
from .polaczenie import polacz_baze
from .ustawienia import OKNA_PRZYSZLOSCI, pobierz_okno_przyszlosci
from .synchronizacja import czy_tylko_podglad
from .koszty import KATEGORIE_BUDZETU, _wiersze_kosztow
from .statystyki import pobierz_rozbicie_kondycji
from .pojazd import WARUNEK_AKTYWNE
from .nawigacja import LICZNIKI_DALSZYCH_MODULOW
from .os_przyszlosci import _klucz_kolejnosci, os_przyszlosci


OKNO_PILNYCH_FLOTY = max(OKNA_PRZYSZLOSCI)

# Miesiąc porównany z tym samym miesiącem rok wcześniej dopiero od tego dnia — wcześniej
# jedno tankowanie robi „+400%” (jak „Koszt w mies.” na kokpicie).
DZIEN_POROWNANIA_MIESIACA = 7

# Koniec budżetu stoi na osi, ale to nie termin do załatwienia.
RODZAJE_POZA_PILNYMI = ("budzet",)

OKRESY_FLOTY = ("miesiac", "rok", "miesiac_rok_temu", "rok_rok_temu")

_POLA_AUTA = "id, nazwa, nr_rej, marka, model, nadwozie, kolor_motywu, zdjecie_glowne"


def auta_floty() -> list[dict[str, Any]]:
    """Aktywne auta (te z „Wybierz pojazd”) alfabetycznie, z polami tożsamości."""
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        wiersze = conn.execute(f"SELECT {_POLA_AUTA} FROM samochody WHERE {WARUNEK_AKTYWNE} ORDER BY nazwa").fetchall()
    return [dict(w) for w in wiersze]


# ============================================================================
#  WYDATKI
# ============================================================================

def _rok_wczesniej(dzien):
    try:
        return dzien.replace(year=dzien.year - 1)
    except ValueError:  # 29 lutego
        return dzien.replace(year=dzien.year - 1, day=28)


def okresy_floty(dzis) -> dict[str, tuple[Any, Any]]:
    """(od, do) okresów OKRESY_FLOTY: miesiąc i rok do dziś oraz te same dni rok wcześniej."""
    rok_temu = _rok_wczesniej(dzis)
    return {
        "miesiac": (dzis.replace(day=1), dzis),
        "rok": (dzis.replace(month=1, day=1), dzis),
        "miesiac_rok_temu": (rok_temu.replace(day=1), rok_temu),
        "rok_rok_temu": (rok_temu.replace(month=1, day=1), rok_temu),
    }


def _pusty_rachunek():
    return {k: 0.0 for k in KATEGORIE_BUDZETU}


def _dodaj(do, rachunek):
    for k in KATEGORIE_BUDZETU:
        do[k] += rachunek[k]


def _sumy_okresow(conn, auto_id, okresy):
    """{okres: {paliwo, serwis, inne, razem}} jednego auta — jedno przejście po jego kosztach
    (wizyta zbiorcza w całości, jak w całej aplikacji)."""
    sumy = {nazwa: _pusty_rachunek() for nazwa in okresy}
    for data_str, kwota, kategoria in _wiersze_kosztow(conn, auto_id):
        dzien = parsuj_date(data_str)
        if dzien == datetime.min.date():
            continue
        wartosc = float(kwota or 0.0)
        for nazwa, (od, do) in okresy.items():
            if od <= dzien <= do:
                sumy[nazwa][kategoria] += wartosc
                sumy[nazwa]["razem"] += wartosc
    return sumy


def koszty_floty(dzis=None) -> dict[str, Any]:
    """Wydatki floty do dziś: auta {auto_id: {miesiac, rok}} (aktywne i sprzedane w tym roku
    z wydatkiem w tym roku), sprzedane [{id, nazwa, data_sprzedazy, rok}], razem {okres: rachunek}
    (okresy rok wcześniej ze WSZYSTKICH aut), najdrozsze {id, nazwa, kwota, udzial, sprzedane}
    albo None (mniej niż dwa auta albo zero wydatków), okresy, dzis."""
    if dzis is None:
        return z_pamieci("flota:koszty", None, lambda: _policz_koszty_floty(datetime.now().date()))
    return _policz_koszty_floty(dzis)


def _policz_koszty_floty(dzis):
    okresy = okresy_floty(dzis)
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        auta = [dict(w) for w in conn.execute(
            "SELECT id, nazwa, status, data_sprzedazy FROM samochody ORDER BY nazwa").fetchall()]
        sumy = {a["id"]: _sumy_okresow(conn, a["id"], okresy) for a in auta}

    liczone, sprzedane = [], []
    for a in auta:
        rachunek = sumy[a["id"]]
        if str(a["status"] or STATUS_POJAZDU_AKTYWNY) != STATUS_POJAZDU_SPRZEDANY:
            liczone.append(a)
        elif parsuj_date(a["data_sprzedazy"]).year == dzis.year and rachunek["rok"]["razem"] > 0:
            liczone.append(a)
            sprzedane.append({"id": a["id"], "nazwa": a["nazwa"], "data_sprzedazy": a["data_sprzedazy"],
                              "rok": rachunek["rok"]["razem"]})

    razem = {nazwa: _pusty_rachunek() for nazwa in okresy}
    for a in liczone:
        for nazwa in ("miesiac", "rok"):
            _dodaj(razem[nazwa], sumy[a["id"]][nazwa])
    for a in auta:
        for nazwa in ("miesiac_rok_temu", "rok_rok_temu"):
            _dodaj(razem[nazwa], sumy[a["id"]][nazwa])

    najdrozsze = None
    rok_floty = razem["rok"]["razem"]
    if len(liczone) >= 2 and rok_floty > 0:
        a = max(liczone, key=lambda x: sumy[x["id"]]["rok"]["razem"])
        kwota = sumy[a["id"]]["rok"]["razem"]
        najdrozsze = {"id": a["id"], "nazwa": a["nazwa"], "kwota": kwota, "udzial": kwota / rok_floty,
                      "sprzedane": any(s["id"] == a["id"] for s in sprzedane)}

    return {
        "dzis": dzis, "okresy": okresy,
        "auta": {a["id"]: {"miesiac": sumy[a["id"]]["miesiac"], "rok": sumy[a["id"]]["rok"]} for a in liczone},
        "sprzedane": sprzedane, "razem": razem, "najdrozsze": najdrozsze,
    }


def zmiana_rok_do_roku(teraz, wczesniej) -> float | None:
    """Zmiana w procentach wobec tego samego okresu rok wcześniej; None bez podstawy."""
    if not wczesniej or wczesniej <= 0:
        return None
    return (teraz - wczesniej) / wczesniej * 100


# ============================================================================
#  TERMINY
# ============================================================================

def _os_pojazdu(auto_id, dni, dzis=None):
    if dzis is None:
        return z_pamieci(f"flota:os:{dni}", auto_id, lambda: os_przyszlosci(auto_id, dni=dni))
    return os_przyszlosci(auto_id, dni=dni, dzis=dzis)


def czy_pilna(pozycja) -> bool:
    """Po terminie albo w progu przypomnienia — to, co oś barwi na czerwono i pomarańczowo."""
    if pozycja["rodzaj"] in RODZAJE_POZA_PILNYMI:
        return False
    return bool(pozycja["zalegla"]) or pozycja["status"] in ("po_terminie", "blisko")


def pilne_floty(dzis=None) -> dict[int, dict[str, int]]:
    """{auto_id: {pilne, zalegle}} aktywnych aut — pozycje osi z okna OKNO_PILNYCH_FLOTY."""
    if dzis is None:
        return z_pamieci("flota:pilne", None, lambda: _policz_pilne_floty(None))
    return _policz_pilne_floty(dzis)


def _policz_pilne_floty(dzis):
    wynik = {}
    for a in auta_floty():
        os_dane = _os_pojazdu(a["id"], OKNO_PILNYCH_FLOTY, dzis)
        pilne = [p for p in os_dane["pozycje"] + os_dane["bez_daty"] if czy_pilna(p)]
        wynik[a["id"]] = {
            "pilne": len(pilne),
            "zalegle": sum(1 for p in pilne if p["zalegla"] or p["status"] == "po_terminie"),
        }
    return wynik


def liczba_pilnych_floty() -> int:
    """Odznaka „flota”: pilne terminy wszystkich aut; przy jednym aucie zero (ma dzwonek) —
    i bez liczenia osi, bo odznaki liczą się przy każdej budowie ekranu głównego po zapisie."""
    if len(auta_floty()) < 2:
        return 0
    return sum(v["pilne"] for v in pilne_floty().values())


LICZNIKI_DALSZYCH_MODULOW["flota"] = lambda auto_id: liczba_pilnych_floty()


def _suma(wartosci):
    """Suma liczb; None, gdy żadna nie jest liczbą (prognoza bez średniej)."""
    liczby = [w for w in wartosci if w is not None]
    return sum(liczby) if liczby else None


def _scal_osie(osie, dni, dzis):
    """Jedna oś z osi aut: pozycje z `pojazd`, kolejność jak na osi auta (remis — nazwa auta),
    miesiące i podsumowanie zsumowane."""
    wynik = os_przyszlosci(None, dni=dni, dzis=dzis)
    if not osie:
        return wynik
    pozycje, bez_daty, miesiace = [], [], {}
    for pojazd, os_dane in osie:
        for p in os_dane["pozycje"]:
            p["pojazd"] = pojazd
            pozycje.append(p)
        for p in os_dane["bez_daty"]:
            p["pojazd"] = pojazd
            bez_daty.append(p)
        for m in os_dane["miesiace"]:
            klucz = (m["rok"], m["miesiac"])
            if klucz not in miesiace:
                miesiace[klucz] = dict(m)
                continue
            suma = miesiace[klucz]
            for pole in ("zaplanowane", "razem", "liczba"):
                suma[pole] += m[pole]
            for pole in ("biezace", "wydano"):
                suma[pole] = _suma([suma[pole], m[pole]])
    pozycje.sort(key=lambda p: (*_klucz_kolejnosci(p), str(p["pojazd"]["nazwa"])))

    podsumowania = [os_dane["podsumowanie"] for _, os_dane in osie]
    wynik.update(
        pozycje=pozycje, bez_daty=bez_daty, miesiace=[miesiace[k] for k in sorted(miesiace)],
        srednia_miesieczna=_suma(o["srednia_miesieczna"] for _, o in osie),
        miesiecy_bazowych=max(o["miesiecy_bazowych"] for _, o in osie),
        podsumowanie={
            **{pole: sum(p[pole] for p in podsumowania)
               for pole in ("liczba", "zalegle", "kwota_zalegla", "zaplanowane", "razem")},
            "biezace": _suma(p["biezace"] for p in podsumowania),
        },
    )
    return wynik


# ============================================================================
#  EKRAN I KAFELEK
# ============================================================================

def dane_floty(dni=None, dzis=None) -> dict[str, Any]:
    """Ekran floty: auta (aktywne alfabetycznie; tożsamość, podglad, kondycja, powod — największa
    kara {opis, waga, punkty} albo None, pilne, zalegle, miesiac, rok, udzial w roku floty,
    najdrozsze), koszty (koszty_floty), os (oś floty w oknie `dni`, domyślnie okno „Co przede mną”),
    pilne (suma)."""
    dni = dni or pobierz_okno_przyszlosci()
    auta = auta_floty()
    koszty = koszty_floty(dzis)
    pilne = pilne_floty(dzis)
    rok_floty = koszty["razem"]["rok"]["razem"]
    najdrozsze = (koszty["najdrozsze"] or {}).get("id")
    osie = []
    for a in auta:
        rozbicie = pobierz_rozbicie_kondycji(a["id"])
        powod = rozbicie["powody"][0] if rozbicie["powody"] else None
        wydatki = koszty["auta"].get(a["id"]) or {"miesiac": _pusty_rachunek(), "rok": _pusty_rachunek()}
        stan = pilne.get(a["id"]) or {"pilne": 0, "zalegle": 0}
        a.update(
            podglad=czy_tylko_podglad(a["id"]), kondycja=rozbicie["wynik"],
            powod={k: powod[k] for k in ("opis", "waga", "punkty")} if powod else None,
            pilne=stan["pilne"], zalegle=stan["zalegle"],
            miesiac=wydatki["miesiac"]["razem"], rok=wydatki["rok"]["razem"],
            udzial=wydatki["rok"]["razem"] / rok_floty if rok_floty > 0 else 0.0,
            najdrozsze=a["id"] == najdrozsze,
        )
        pojazd = {k: a[k] for k in ("id", "nazwa", "nadwozie", "kolor_motywu", "podglad")}
        osie.append((pojazd, _os_pojazdu(a["id"], dni, dzis)))
    return {"auta": auta, "koszty": koszty, "os": _scal_osie(osie, dni, dzis),
            "pilne": sum(a["pilne"] for a in auta)}


def kafel_floty(auto_id) -> dict[str, Any] | None:
    """Kafelek „Flota”: liczba_aut, miesiac (wydatki floty), pilne_innych i zalegle_innych — terminy
    POZOSTAŁYCH aut (swoje ma dzwonek). None przy jednym aucie: nie dotyczy."""
    if len(auta_floty()) < 2:
        return None
    pilne = pilne_floty()
    inne = [v for aid, v in pilne.items() if aid != auto_id]
    return {
        "liczba_aut": len(pilne),
        "miesiac": koszty_floty()["razem"]["miesiac"]["razem"],
        "pilne_innych": sum(v["pilne"] for v in inne),
        "zalegle_innych": sum(v["zalegle"] for v in inne),
    }


__all__ = [
    "DZIEN_POROWNANIA_MIESIACA",
    "OKNO_PILNYCH_FLOTY",
    "OKRESY_FLOTY",
    "RODZAJE_POZA_PILNYMI",
    "auta_floty",
    "czy_pilna",
    "dane_floty",
    "kafel_floty",
    "koszty_floty",
    "liczba_pilnych_floty",
    "okresy_floty",
    "pilne_floty",
    "zmiana_rok_do_roku",
]
