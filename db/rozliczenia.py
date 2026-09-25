"""Saldo współdzielonego auta: kto ile zapłacił, kto komu ile jest winien
i rozliczenia, które to saldo zerują.

Saldo liczy się ZAWSZE z całej podpisanej historii, a rozliczenie jest
migawką, nie datą odcięcia: zapamiętuje, ile każda osoba miała na plusie albo
na minusie w chwili „Rozliczone”, i dokładnie tę kwotę się potem odejmuje.
Data rozliczenia dzieli historię na okresy tylko po to, żeby każdy okres
dzielił się po równo między osoby, które wtedy dzieliły auto — lista tych
osób zostaje zapisana w rozliczeniu, więc późniejszy nowy domownik nie
dostaje rachunku za zamknięte okresy.

Skutek, dla którego to tak wygląda: wpis sprzed rozliczenia dopisany,
poprawiony albo usunięty po nim — zapomniana myjnia, literówka w kwocie,
tankowanie, które z drugiego telefonu doszło dzień później — nie przepada,
tylko pojawia się w bieżącym saldzie jako korekta. Przy dacie odcięcia
zniknąłby z rachunku bez śladu.

Kwoty liczą się w groszach (int): suma sald ma wynosić dokładnie zero, a po
rozliczeniu saldo ma być zerowe co do grosza, nie 0,0000001.
"""

import json
import uuid
from bisect import bisect_left
from datetime import date, datetime
from typing import Any

from date import parsuj_date

from .stale import MAKS_DLUGOSC_NOTATKI
from .polaczenie import polacz_baze
from .pomocnicze import _na_liczbe
from .ustawienia import pobierz_moje_imie
from .synchronizacja import czy_moge_dodawac
from .koszty import _wydatki_z_autorem, klucz_osoby, nazwa_osoby
from .usuwanie import usun_z_cofnieciem


# Data rozliczenia w tej samej postaci, co daty wpisów — pole daty i sortowanie
# list czytają jedną i drugą tak samo.
FORMAT_DATY_ROZLICZENIA = "%d.%m.%Y"


def _grosze(kwota):
    return int(round((_na_liczbe(kwota) or 0.0) * 100))


def _zl(grosze):
    return round(grosze / 100, 2)


def _z_json(tekst, domyslna):
    """Wartość kolumny JSON albo `domyslna`. Kolumnę mógł zapisać ktoś inny
    (drugi telefon, kopia zapasowa), więc nie ufamy ani składni, ani kształtowi."""
    try:
        wartosc = json.loads(tekst) if tekst else domyslna
    except (TypeError, ValueError):
        return domyslna
    return wartosc if isinstance(wartosc, type(domyslna)) else domyslna


def _dopisz_wariant(warianty, nazwa, waga=1):
    nazwa = " ".join(str(nazwa or "").split())
    klucz = klucz_osoby(nazwa)
    if klucz:
        grupa = warianty.setdefault(klucz, {})
        grupa[nazwa] = grupa.get(nazwa, 0) + waga
    return klucz


# ============================================================================
#  ODCZYT
# ============================================================================

def _wydatki(conn, auto_id, warianty):
    """(podpisane, niepodpisane): [(data, grosze, klucz)] i [(data, grosze)].

    Wpis bez podpisu (sprzed imion w Ustawieniach) nie wchodzi do salda: nie
    wiadomo, kto zapłacił, a podzielony bez płatnika zrobiłby wszystkich
    dłużnikami nikogo."""
    podpisane, niepodpisane = [], []
    for data, kwota, _kategoria, autor, _dystans in _wydatki_z_autorem(conn, auto_id):
        d = parsuj_date(data)
        klucz = _dopisz_wariant(warianty, autor)
        if klucz:
            podpisane.append((d, _grosze(kwota), klucz))
        else:
            niepodpisane.append((d, _grosze(kwota)))
    return podpisane, niepodpisane


def _rozliczenia(conn, auto_id, warianty=None):
    """Wszystkie rozliczenia pojazdu w kolejności dat, z flagą `liczy_sie`.

    Dwa rozliczenia z tym samym poprzednikiem powstały niezależnie — zwykle
    dwie osoby kliknęły „Rozliczone” każda u siebie, zanim telefony się
    wymieniły danymi. Liczy się tylko pierwsze zapisane; drugie wyzerowałoby
    to samo saldo jeszcze raz i odwróciło je na drugą stronę."""
    warianty = warianty if warianty is not None else {}
    c = conn.cursor()
    c.execute(
        "SELECT id, data, uczestnicy, salda, przelewy, notatka, klucz, poprzednie, dodane_przez, "
        "data_utworzenia FROM rozliczenia WHERE auto_id=?", (auto_id,)
    )
    lista = []
    for (id_, data, uczestnicy, salda, przelewy, notatka, klucz, poprzednie,
         autor, utworzono) in c.fetchall():
        salda_k = {}
        for osoba, kwota in _z_json(salda, {}).items():
            k = _dopisz_wariant(warianty, osoba)
            if k:
                salda_k[k] = salda_k.get(k, 0) + int(round(_na_liczbe(kwota) or 0))
        uczestnicy_k = set()
        for osoba in _z_json(uczestnicy, []):
            k = _dopisz_wariant(warianty, osoba)
            if k:
                uczestnicy_k.add(k)
        lista_przelewow = []
        for p in _z_json(przelewy, []):
            if isinstance(p, dict) and p.get("od") and p.get("do"):
                lista_przelewow.append({"od": str(p["od"]), "do": str(p["do"]),
                                        "kwota": _zl(int(round(_na_liczbe(p.get("kwota")) or 0)))})
        lista.append({
            "id": id_, "data": parsuj_date(data), "data_tekst": data,
            "uczestnicy": uczestnicy_k, "salda": salda_k, "przelewy": lista_przelewow,
            "notatka": notatka, "dodane_przez": autor,
            # Wiersz spoza aplikacji (import, zasiew testowy) może nie mieć klucza —
            # dostaje zastępczy, żeby nie udawać drugiego „pierwszego” rozliczenia.
            "klucz": klucz or f"lokalne-{id_}", "poprzednie": poprzednie or "",
            "utworzono": utworzono or "",
        })

    rownolegle = set()
    widziani_poprzednicy = set()
    for r in sorted(lista, key=lambda r: (r["utworzono"], r["klucz"], r["id"])):
        if r["poprzednie"] in widziani_poprzednicy:
            rownolegle.add(r["id"])
        widziani_poprzednicy.add(r["poprzednie"])
    for r in lista:
        r["liczy_sie"] = r["id"] not in rownolegle

    lista.sort(key=lambda r: (r["data"], r["utworzono"], r["klucz"], r["id"]))
    return lista


# ============================================================================
#  RACHUNEK
# ============================================================================

def _podziel(grosze, klucze):
    """Kwota po równo między osoby, co do grosza. Reszta z dzielenia idzie do
    pierwszych w kolejności alfabetycznej — ta sama na każdym telefonie, więc
    oba liczą identyczne saldo."""
    klucze = sorted(klucze)
    if not klucze:
        return {}
    baza, reszta = divmod(grosze, len(klucze))
    return {k: baza + (1 if i < reszta else 0) for i, k in enumerate(klucze)}


def _policz_okres(pozycje, uczestnicy, saldo):
    """Dopisuje do `saldo` jeden okres: każdy dostaje to, co zapłacił, i oddaje
    swoją równą część. Zwraca (zaplacil, przypada) tego okresu."""
    zaplacil = {}
    for grosze, klucz in pozycje:
        zaplacil[klucz] = zaplacil.get(klucz, 0) + grosze
    # Okres bez zapisanych uczestników (uszkodzona migawka) dzieli się między
    # tych, którzy w nim płacili — inaczej suma sald przestałaby być zerem.
    przypada = _podziel(sum(zaplacil.values()), uczestnicy or set(zaplacil))
    for klucz, grosze in zaplacil.items():
        saldo[klucz] = saldo.get(klucz, 0) + grosze
    for klucz, grosze in przypada.items():
        saldo[klucz] = saldo.get(klucz, 0) - grosze
    return zaplacil, przypada


def _policz(podpisane, aktywne, moje=None, do_dnia=None):
    """Saldo w groszach z całej historii minus migawki rozliczeń.

    `aktywne` — rozliczenia, które się liczą, w kolejności dat. `do_dnia` liczy
    tak, jakby okres otwarty kończył się tego dnia: z tego powstaje migawka
    nowego rozliczenia (wpis z późniejszą datą zostaje w nowym saldzie).

    Uczestnicy okresu otwartego: uczestnicy ostatniego rozliczenia, każdy, kto
    w tym okresie płacił, i ja — o ile przy tym aucie w ogóle coś dopisuję.
    Ten, kto nic jeszcze nie zapłacił, też ponosi swoją część; bez tego jedna
    osoba płacąca za wszystko wychodziłaby „kwita”. Płacący liczą się z CAŁEGO
    okresu, także zza `do_dnia`: Ola, która pierwszy raz tankowała wczoraj,
    dzieli auto także w rozliczeniu z datą sprzed tygodnia."""
    granice = [r["data"] for r in aktywne]
    okresy = [[] for _ in range(len(granice) + 1)]
    placacy_otwartego = set()
    for d, grosze, klucz in podpisane:
        okres = bisect_left(granice, d)
        if okres == len(granice):
            placacy_otwartego.add(klucz)
        if do_dnia is not None and d > do_dnia:
            continue
        okresy[okres].append((grosze, klucz))

    saldo = {}
    for i, r in enumerate(aktywne):
        _policz_okres(okresy[i], r["uczestnicy"], saldo)
        for klucz, grosze in r["salda"].items():
            saldo[klucz] = saldo.get(klucz, 0) - grosze

    uczestnicy = set(aktywne[-1]["uczestnicy"]) if aktywne else set()
    uczestnicy |= placacy_otwartego
    if moje:
        uczestnicy.add(moje)
    zaplacil, przypada = _policz_okres(okresy[-1], uczestnicy, saldo)
    return {
        "saldo": saldo, "zaplacil": zaplacil, "przypada": przypada,
        "uczestnicy": sorted(uczestnicy), "suma": sum(zaplacil.values()),
        "od_dnia": granice[-1] if granice else None,
    }


def _przelewy(saldo):
    """[(kto_oddaje, komu, grosze)] — najmniej przelewów, jakie da się ułożyć
    zachłannie: największy dług spłaca największą nadwyżkę. Przy dwóch osobach
    to zawsze jeden przelew, przy trzech najwyżej dwa."""
    winni = sorted(([-g, k] for k, g in saldo.items() if g < 0), key=lambda p: (-p[0], p[1]))
    wierzyciele = sorted(([g, k] for k, g in saldo.items() if g > 0), key=lambda p: (-p[0], p[1]))
    wynik = []
    i = j = 0
    while i < len(winni) and j < len(wierzyciele):
        kwota = min(winni[i][0], wierzyciele[j][0])
        if kwota > 0:
            wynik.append((winni[i][1], wierzyciele[j][1], kwota))
        winni[i][0] -= kwota
        wierzyciele[j][0] -= kwota
        if winni[i][0] <= 0:
            i += 1
        if wierzyciele[j][0] <= 0:
            j += 1
    return wynik


def _moje(auto_id, warianty):
    """Mój klucz — jeśli przy tym aucie w ogóle coś dopisuję (podgląd nie
    dzieli kosztów, tylko je ogląda)."""
    if not czy_moge_dodawac(auto_id):
        return None
    return _dopisz_wariant(warianty, pobierz_moje_imie(), waga=0) or None


def _nazwa(warianty, klucz):
    """Pisownia osoby do pokazania. Imię z Ustawień ma wagę zero, więc
    przegrywa z pisownią z wpisów, a wygrywa tylko wtedy, gdy wpisów brak."""
    grupa = warianty.get(klucz)
    return nazwa_osoby(grupa) if grupa else klucz


def _stan(conn, auto_id, do_dnia=None):
    warianty = {}
    podpisane, niepodpisane = _wydatki(conn, auto_id, warianty)
    wszystkie = _rozliczenia(conn, auto_id, warianty)
    aktywne = [r for r in wszystkie if r["liczy_sie"]]
    moje = _moje(auto_id, warianty)
    wynik = _policz(podpisane, aktywne, moje, do_dnia)
    return wynik, warianty, niepodpisane, aktywne


# ============================================================================
#  INTERFEJS
# ============================================================================

def saldo_rozliczen(auto_id, do_dnia=None) -> dict[str, Any]:
    """Saldo pojazdu na dziś — albo takie, jakie wyzeruje rozliczenie z datą
    `do_dnia` (podgląd w oknie „Rozliczone”).

    {"osoby": [{"klucz", "osoba", "zaplacil", "przypada", "korekta", "saldo"}],
     "przelewy": [{"od", "do", "kwota"}], "od_dnia": date | None,
     "suma", "na_osobe", "uczestnikow", "bez_podpisu", "kwota_bez_podpisu",
     "korekty", "rozliczen"}

    `zaplacil` i `przypada` dotyczą okresu od ostatniego rozliczenia;
    `korekta` to reszta salda — zmiany we wpisach z okresów już zamkniętych.
    Saldo dodatnie: tej osobie inni oddają; ujemne: ta osoba oddaje. Kwoty
    w złotych."""
    pusty = {"osoby": [], "przelewy": [], "od_dnia": None, "suma": 0.0, "na_osobe": 0.0,
             "uczestnikow": 0, "bez_podpisu": 0, "kwota_bez_podpisu": 0.0,
             "korekty": False, "rozliczen": 0}
    if not auto_id:
        return pusty
    with polacz_baze() as conn:
        wynik, warianty, niepodpisane, aktywne = _stan(conn, auto_id, do_dnia)

    saldo = wynik["saldo"]
    klucze = set(wynik["uczestnicy"]) | {k for k, g in saldo.items() if g} | set(wynik["zaplacil"])
    osoby = []
    for klucz in klucze:
        zaplacil = wynik["zaplacil"].get(klucz, 0)
        przypada = wynik["przypada"].get(klucz, 0)
        s = saldo.get(klucz, 0)
        osoby.append({
            "klucz": klucz, "osoba": _nazwa(warianty, klucz),
            "zaplacil": _zl(zaplacil), "przypada": _zl(przypada),
            "korekta": _zl(s - (zaplacil - przypada)), "saldo": _zl(s),
        })
    osoby.sort(key=lambda o: (-o["saldo"], o["osoba"].casefold()))

    od_dnia = wynik["od_dnia"]
    bez_podpisu = [g for d, g in niepodpisane
                   if (od_dnia is None or d > od_dnia) and (do_dnia is None or d <= do_dnia)]
    uczestnikow = len(wynik["uczestnicy"])
    return {
        "osoby": osoby,
        "przelewy": [{"od": _nazwa(warianty, a), "do": _nazwa(warianty, b), "kwota": _zl(g)}
                     for a, b, g in _przelewy(saldo)],
        "od_dnia": od_dnia,
        "suma": _zl(wynik["suma"]),
        "na_osobe": _zl(wynik["suma"] / uczestnikow) if uczestnikow else 0.0,
        "uczestnikow": uczestnikow,
        "bez_podpisu": len(bez_podpisu),
        "kwota_bez_podpisu": _zl(sum(bez_podpisu)),
        "korekty": any(o["korekta"] for o in osoby),
        "rozliczen": len(aktywne),
    }


def pobierz_rozliczenia(auto_id) -> list[dict[str, Any]]:
    """Historia rozliczeń, najnowsze na górze:
    [{"id", "data", "przelewy": [{"od", "do", "kwota"}], "notatka",
      "dodane_przez", "liczy_sie", "do_cofniecia"}].

    Cofnąć można tylko ostatnie liczące się rozliczenie — wcześniejsze są
    podstawą późniejszych — oraz każde równoległe, które i tak się nie liczy."""
    if not auto_id:
        return []
    with polacz_baze() as conn:
        lista = _rozliczenia(conn, auto_id)
    aktywne = [r for r in lista if r["liczy_sie"]]
    ostatnie = aktywne[-1]["id"] if aktywne else None
    wynik = []
    for r in reversed(lista):
        wynik.append({
            "id": r["id"], "data": r["data_tekst"], "przelewy": r["przelewy"],
            "notatka": r["notatka"], "dodane_przez": r["dodane_przez"],
            "liczy_sie": r["liczy_sie"],
            "do_cofniecia": (not r["liczy_sie"]) or r["id"] == ostatnie,
        })
    return wynik


def blad_daty_rozliczenia(auto_id, data_str):
    """Opis błędu daty albo None. Rozliczenie zamyka okres, więc nie może
    wypaść przed poprzednim ani w przyszłości."""
    d = parsuj_date(data_str)
    if d == datetime.min.date():
        return "Podaj datę rozliczenia"
    if d > date.today():
        return "Data rozliczenia nie może być z przyszłości"
    if auto_id:
        with polacz_baze() as conn:
            aktywne = [r for r in _rozliczenia(conn, auto_id) if r["liczy_sie"]]
        if aktywne and d < aktywne[-1]["data"]:
            return ("Ostatnie rozliczenie jest z "
                    f"{aktywne[-1]['data'].strftime(FORMAT_DATY_ROZLICZENIA)} — nowe nie może być wcześniejsze")
    return None


def zapisz_rozliczenie(auto_id, data_str=None, notatka=None):
    """„Rozliczone”: zeruje saldo wpisów do dnia `data_str` włącznie (domyślnie
    dziś) i zapisuje, kto komu ile oddał. Zwraca id rozliczenia albo None, gdy
    data jest zła albo rola nie pozwala niczego dopisywać."""
    if not auto_id or not czy_moge_dodawac(auto_id):
        return None
    data_str = data_str or date.today().strftime(FORMAT_DATY_ROZLICZENIA)
    if blad_daty_rozliczenia(auto_id, data_str):
        return None
    d = parsuj_date(data_str)
    autor = pobierz_moje_imie()

    with polacz_baze() as conn:
        wynik, warianty, _niepodpisane, aktywne = _stan(conn, auto_id, do_dnia=d)
        saldo = wynik["saldo"]
        uczestnicy = set(wynik["uczestnicy"])
        salda = {_nazwa(warianty, k): g for k, g in saldo.items() if g or k in uczestnicy}
        for k in uczestnicy:
            salda.setdefault(_nazwa(warianty, k), 0)
        przelewy = [{"od": _nazwa(warianty, a), "do": _nazwa(warianty, b), "kwota": g}
                    for a, b, g in _przelewy(saldo)]
        tekst_notatki = " ".join(str(notatka or "").split())[:MAKS_DLUGOSC_NOTATKI] or None
        c = conn.cursor()
        c.execute(
            "INSERT INTO rozliczenia (auto_id, data, uczestnicy, salda, przelewy, notatka, klucz, "
            "poprzednie, dodane_przez, data_utworzenia) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (auto_id, d.strftime(FORMAT_DATY_ROZLICZENIA),
             json.dumps(sorted(_nazwa(warianty, k) for k in uczestnicy), ensure_ascii=False),
             json.dumps(salda, ensure_ascii=False, sort_keys=True),
             json.dumps(przelewy, ensure_ascii=False),
             tekst_notatki, uuid.uuid4().hex,
             aktywne[-1]["klucz"] if aktywne else None,
             autor, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        return c.lastrowid


def cofnij_rozliczenie(auto_id, rozliczenie_id):
    """Usuwa rozliczenie z możliwością cofnięcia (wynik `usun_z_cofnieciem`)
    — ale tylko ostatnie liczące się albo równoległe. None, gdy w międzyczasie
    doszło nowsze (np. z drugiego telefonu) albo rola na to nie pozwala."""
    dozwolone = {r["id"] for r in pobierz_rozliczenia(auto_id) if r["do_cofniecia"]}
    if rozliczenie_id not in dozwolone:
        return None
    return usun_z_cofnieciem("rozliczenia", rozliczenie_id)


__all__ = [
    "FORMAT_DATY_ROZLICZENIA",
    "blad_daty_rozliczenia",
    "cofnij_rozliczenie",
    "pobierz_rozliczenia",
    "saldo_rozliczen",
    "zapisz_rozliczenie",
]
