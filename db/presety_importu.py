"""Presety importu z innych aplikacji: Fuelio, Drivvo, aCar, Simply Auto. `TYPY_IMPORTU`
(import_csv) mówi, CO da się zaimportować; preset — JAK wygląda plik aplikacji (sekcje,
kolumny, formaty). Wynik to zwykłe tabele z gotowym mapowaniem, więc dalej działa ten
sam mechanizm co przy ręcznym dopasowaniu.

Czego plik nie mówi wprost, preset dopisuje jako kolumnę z opisem w nawiasie (data z
trzech kolumn, litry z galonów, „do pełna” z flagi, energia z kodu paliwa, kategoria z
numeru); liczby wyliczone z kropką, bez separatora tysięcy. Formaty:
claude/presety-importu.md."""

from collections import Counter
from datetime import date

from .pomocnicze import _parsuj_liczbe_csv, liczba_z_odmiana
from .import_csv import (
    TYPY_IMPORTU,
    _bez_ogonkow,
    _liczba_csv,
    _nazwa_ogolna,
    _normalizuj_naglowek,
    _parsuj_date_csv,
    _wzorzec_slow,
    czy_nazwa_serwisowa,
    rozpoznaj_kolejnosc_dat,
    rozpoznaj_separator_dziesietny,
    tabela_z_wierszy,
)


LITRY_W_GALONIE_US = 3.785411784
LITRY_W_GALONIE_UK = 4.54609

# Źródło energii w kolumnie wyliczonej — `_rozpoznaj_rodzaj_csv` czyta oba słowa.
_PRAD, _PALIWO = "prąd", "paliwo"

_WZORZEC_PRADU = _wzorzec_slow("electr", "eletr", "elektr", "kwh", "prad", "ladowan", "charg", "recarga", "ev=")

_TAK = {"1", "tak", "yes", "y", "true", "t", "prawda", "x", "si", "sim", "ja", "oui"}

_INNE_AUTA = "wpisy innych pojazdów z pliku"


# ==================== NARZĘDZIA ====================


def _w(wiersz, idx):
    """Komórka wiersza albo "" — dla brakującej kolumny i krótkiego wiersza."""
    if idx is None or idx >= len(wiersz):
        return ""
    return wiersz[idx]


def _tak(tekst):
    return _bez_ogonkow(_normalizuj_naglowek(tekst)) in _TAK


def _liczba_calkowita(tekst):
    liczba = _parsuj_liczbe_csv(tekst)
    return int(liczba) if liczba is not None else None


def _tekst_liczby(liczba):
    """Liczba wyliczona przez preset jako tekst z kropką dziesiętną i bez
    separatora tysięcy — `przygotuj_import_*` czyta ją bez zgadywania."""
    return "" if liczba is None else repr(round(float(liczba), 6))


def _pierwszy(*indeksy):
    """Pierwszy indeks, który nie jest None (0 to poprawna kolumna)."""
    return next((i for i in indeksy if i is not None), None)


def _kolumna(naglowki, *nazwy):
    """Indeks pierwszej kolumny o jednej z nazw (po normalizacji) albo None."""
    znormalizowane = [_normalizuj_naglowek(n) for n in naglowki]
    for nazwa in nazwy:
        klucz = _normalizuj_naglowek(nazwa)
        if klucz in znormalizowane:
            return znormalizowane.index(klucz)
    return None


def _kolumna_z(naglowki, warunek):
    """Indeks pierwszej kolumny, której znormalizowany nagłówek (bez ogonków)
    spełnia warunek — dla nagłówków z jednostką w nawiasie („Odo (km)”)
    i tłumaczonych („Posto”, „Estación”)."""
    for i, naglowek in enumerate(naglowki):
        if warunek(_bez_ogonkow(_normalizuj_naglowek(naglowek))):
            return i
    return None


def _zawiera(*rdzenie):
    return lambda naglowek: any(r in naglowek for r in rdzenie)


def _konwencja(wiersze, *indeksy):
    return rozpoznaj_separator_dziesietny(_w(w, i) for w in wiersze for i in indeksy if i is not None)


def _funkcja_daty(wiersze, idx, domyslna="dmy"):
    """Wiersz → data „DD.MM.RRRR” z kolumny `idx`. Kolejność dzień/miesiąc
    ustalana raz dla całej kolumny; nieczytelna data zostaje, jaka była —
    walidacja zgłosi ją z numerem wiersza. Bez kolumny daty — None, a pole
    dopasuje zwykły mechanizm po nazwach (`_czesc`)."""
    if idx is None:
        return None
    kolejnosc = rozpoznaj_kolejnosc_dat((_w(w, idx) for w in wiersze), domyslna)
    return lambda w: _parsuj_date_csv(_w(w, idx), kolejnosc) or _w(w, idx)


def _rodzaj_z_nazwy_paliwa(nazwa):
    """„prąd” dla paliwa, które jest energią elektryczną, „paliwo” dla każdego
    innego nazwanego, "" dla pustego — wtedy rozstrzyga domyślne źródło auta."""
    tekst = _bez_ogonkow(_normalizuj_naglowek(nazwa))
    if not tekst:
        return ""
    return _PRAD if _WZORZEC_PRADU.search(tekst) else _PALIWO


def _mnoznik_objetosci(jednostka):
    """Litry w jednostce objętości z pliku (aCar: „L”, „gal (US)”, „gal (UK)”)."""
    tekst = _bez_ogonkow(_normalizuj_naglowek(jednostka))
    if "gal" not in tekst:
        return 1.0
    return LITRY_W_GALONIE_UK if any(s in tekst for s in ("uk", "imp")) else LITRY_W_GALONIE_US


def _jednostka_dystansu(tekst):
    """„km”, „mi” albo None z opisu jednostki w pliku („mi”, „miles”, „km”)."""
    tekst = _bez_ogonkow(_normalizuj_naglowek(tekst))
    if tekst in ("km", "kilometer", "kilometers", "kilometre", "kilometres", "kilometry"):
        return "km"
    if tekst in ("mi", "m", "mile", "miles", "mil"):
        return "mi"
    return None


def _uwaga_o_pominietych_tankowaniach(wynik, dane, idx):
    """Fuelio, aCar i Simply Auto mają flagę „pominięte wcześniejsze
    tankowanie”. Ta aplikacja jej nie zna, więc spalanie liczone przez taką
    lukę wyjdzie zaniżone — mówimy o tym, zamiast udawać, że się zgadza."""
    ile = sum(1 for w in dane if _tak(_w(w, idx)))
    if idx is not None and ile:
        wynik["uwagi"].append(
            f"Pominięte wcześniejsze tankowanie zaznaczone przy {liczba_z_odmiana(ile, 'wpisie', 'wpisach', 'wpisach')}"
            " — aplikacja tego nie zapisuje, więc spalanie na tych odcinkach może wyjść zaniżone.")


def _nowy_wynik(aplikacja):
    return {
        "aplikacja": aplikacja,
        "czesci": [],
        "pominiete": Counter(),
        "jednostka": None,
        "pojazdy": [],
        "pojazd": None,
        "nazwa_pojazdu": None,
        "uwagi": [],
    }


def _czesc(wynik, typ, zrodlo, naglowki, wiersze, numery, kolumny, wyliczone=()):
    """Dokłada część pliku gotową dla `TYPY_IMPORTU[typ]`. kolumny: {pole: indeks w
    `naglowki` albo None}; wyliczone: [(pole, nagłówek, funkcja(wiersz) -> str)]
    dopisywane na końcu wiersza. Brak kolumny wymaganej → dopasowanie po nazwach
    nagłówków i uwaga dla człowieka."""
    if not wiersze:
        return
    naglowki = list(naglowki)
    wiersze = [list(w) + [""] * max(0, len(naglowki) - len(w)) for w in wiersze]
    mapowanie = {pole: idx for pole, idx in kolumny.items() if idx is not None}
    for pole, naglowek, funkcja in wyliczone:
        if funkcja is None:
            continue
        wartosci = [funkcja(w) for w in wiersze]
        naglowki.append(naglowek)
        for wiersz, wartosc in zip(wiersze, wartosci):
            wiersz.append(wartosc)
        mapowanie[pole] = len(naglowki) - 1

    konfig = TYPY_IMPORTU[typ]
    brakujace = [p for p, (_, wymagane) in konfig["pola"].items() if wymagane and p not in mapowanie]
    if brakujace:
        z_nazw = konfig["dopasuj"](naglowki)
        for pole, idx in z_nazw.items():
            if pole not in mapowanie and idx is not None and idx not in mapowanie.values():
                mapowanie[pole] = idx
        wynik["uwagi"].append(f"{konfig['etykieta']}: układ kolumn inny niż znany — część kolumn dopasowana "
                              "po nazwach. Sprawdź dopasowanie.")

    wynik["czesci"].append({
        "typ": typ,
        "zrodlo": zrodlo,
        "naglowki": naglowki,
        "wiersze": wiersze,
        "numery": list(numery),
        "mapowanie": mapowanie,
    })


def _odfiltruj(wynik, wiersze, numery, powod):
    """(wiersze, numery) bez tych, dla których `powod(wiersz)` zwraca powód —
    te liczą się w pominiętych (preset pokazuje, czego i dlaczego nie bierze)."""
    zostaja, ich_numery = [], []
    for wiersz, nr in zip(wiersze, numery):
        przyczyna = powod(wiersz)
        if przyczyna:
            wynik["pominiete"][przyczyna] += 1
        else:
            zostaja.append(wiersz)
            ich_numery.append(nr)
    return zostaja, ich_numery


def _podziel(wiersze, numery, warunek):
    """Dwie pary (wiersze, numery): spełniające warunek i reszta."""
    tak, nie = ([], []), ([], [])
    for wiersz, nr in zip(wiersze, numery):
        cel = tak if warunek(wiersz) else nie
        cel[0].append(wiersz)
        cel[1].append(nr)
    return tak, nie


def _wybierz_pojazd(wynik, wartosci, pojazd, etykieta):
    """Plik z kilkoma pojazdami (aCar, Simply Auto): lista do wyboru, od
    najczęstszego, i klucz wybranego — podanego albo tego z największą
    liczbą wpisów. Zwraca klucz albo None, gdy pojazd jest jeden lub żaden."""
    liczniki = Counter(v for v in wartosci if v)
    if len(liczniki) < 2:
        return None
    wynik["pojazdy"] = [(klucz, etykieta(klucz), ile) for klucz, ile in liczniki.most_common()]
    wynik["pojazd"] = pojazd if pojazd in liczniki else liczniki.most_common(1)[0][0]
    return wynik["pojazd"]


# ==================== SEKCJE ====================


def _znacznik_krzyzykowy(wiersz):
    """„## Log”, „##Refuelling”, „#Reabastecimiento” → „log”, „refuelling”…
    Pierwsza komórka zaczyna się od „#”, reszta wiersza jest pusta."""
    if not wiersz or not wiersz[0].startswith("#") or any(k.strip() for k in wiersz[1:]):
        return None
    return _bez_ogonkow(_normalizuj_naglowek(wiersz[0].lstrip("#")))


def _sekcje(wiersze, znacznik):
    """{nazwa: (oryginalny znacznik, nagłówki, wiersze, numery)} — wiersze
    między znacznikiem a następnym, pierwszy z nich to nagłówek sekcji.
    Numery to pozycje w pliku liczone od 1, do komunikatów o błędach."""
    surowe = {}
    biezaca = None
    for nr, wiersz in enumerate(wiersze, start=1):
        nazwa = znacznik(wiersz)
        if nazwa is not None:
            # Powtórzony znacznik zaczyna nową sekcję, a nie dokleja do starej
            # drugiego nagłówka jako wiersza danych.
            klucz = nazwa if nazwa not in surowe else f"{nazwa} ({nr})"
            biezaca = surowe[klucz] = (" ".join(k for k in wiersz if k.strip()), [], [])
            continue
        if biezaca is not None:
            biezaca[1].append(wiersz)
            biezaca[2].append(nr)

    sekcje = {}
    for nazwa, (oryginal, zawartosc, numery) in surowe.items():
        naglowki, dane = tabela_z_wierszy(zawartosc)
        sekcje[nazwa] = (oryginal, naglowki, dane, numery[1:])
    return sekcje


_PUSTA_SEKCJA = ("", [], [], [])


# ==================== FUELIO ====================
# Kopia CSV (Fuelio/backup-csv, na Dysku Google vehicle-N-sync.csv.zip): „## Vehicle”
# (jednostki, format daty, zbiorniki), „## Log” (tankowania), „## CostCategories” + „##
# Costs”, dalej m.in. „## FavStations”, „## Category”.


def _to_fuelio(wiersze):
    znaczniki = {_znacznik_krzyzykowy(w) for w in wiersze}
    return "log" in znaczniki and bool({"vehicle", "costs", "costcategories"} & znaczniki)


def _kolejnosc_z_wzorca_javy(wzorzec):
    """Fuelio zapisuje format daty wpisów w nagłówku pojazdu („yyyy-MM-dd”,
    „dd.MM.yyyy”, „MM/dd/yyyy”). W Javie „M” to miesiąc, a „m” minuty."""
    return "mdy" if str(wzorzec or "").strip().startswith("M") else "dmy"


def _rozbierz_fuelio(wiersze, pojazd=None):
    wynik = _nowy_wynik("fuelio")
    sekcje = _sekcje(wiersze, _znacznik_krzyzykowy)

    _, naglowki_p, dane_p, _ = sekcje.get("vehicle", _PUSTA_SEKCJA)
    auto = dict(zip((_normalizuj_naglowek(n) for n in naglowki_p), dane_p[0])) if dane_p else {}
    wynik["nazwa_pojazdu"] = auto.get("name") or None
    wynik["jednostka"] = {"0": "km", "1": "mi"}.get(str(auto.get("distunit", "")).strip())
    kolejnosc = _kolejnosc_z_wzorca_javy(auto.get("importcsvdateformat"))

    _fuelio_tankowania(wynik, sekcje, auto, kolejnosc)
    _fuelio_koszty(wynik, sekcje, kolejnosc)

    for nazwa, (oryginal, _, dane, _) in sekcje.items():
        if "trip" in nazwa and dane:
            wynik["uwagi"].append(f"Trasy z sekcji „{oryginal}” nie są importowane.")
    return wynik


def _fuelio_tankowania(wynik, sekcje, auto, kolejnosc):
    oryginal, naglowki, dane, numery = sekcje.get("log", _PUSTA_SEKCJA)
    if not dane:
        return

    i_data = _kolumna(naglowki, "data", "date")
    i_odo = _kolumna_z(naglowki, lambda n: n.startswith("odo"))
    i_ilosc = _kolumna_z(naglowki, lambda n: n.startswith("fuel") and "(" in n)
    i_pelne = _kolumna(naglowki, "full")
    i_cena = _kolumna_z(naglowki, lambda n: n.startswith("price"))
    i_miasto = _kolumna_z(naglowki, lambda n: n.startswith("city"))
    i_notatki = _kolumna_z(naglowki, lambda n: n.startswith("notes"))
    i_zbiornik = _kolumna(naglowki, "tanknumber")
    i_paliwo = _kolumna(naglowki, "fueltype")
    i_cena_jedn = _kolumna(naglowki, "volumeprice")

    if wynik["jednostka"] is None and i_odo is not None:
        naglowek = _normalizuj_naglowek(naglowki[i_odo])
        wynik["jednostka"] = "mi" if "(mi" in naglowek else ("km" if "(km" in naglowek else None)

    dziesietny = _konwencja(dane, i_odo, i_ilosc, i_cena, i_cena_jedn)
    typy_zbiornikow = {"1": _liczba_calkowita(auto.get("tank1type")), "2": _liczba_calkowita(auto.get("tank2type"))}
    jednostki_paliwa = {"1": str(auto.get("fuelunit", "0")).strip(), "2": str(auto.get("fuelunittank2", "0")).strip()}
    mnozniki = {"1": LITRY_W_GALONIE_US, "2": LITRY_W_GALONIE_UK}

    def zbiornik(w):
        return _w(w, i_zbiornik).strip() or "1"

    def czy_prad(w):
        # Kody paliw Fuelio: 100 benzyna, 200 diesel, 300 etanol, 400 LPG,
        # 500 CNG, 600 prąd (601 AC, 602 DC), 700 flex. Wpis bez kodu bierze
        # rodzaj zbiornika, do którego tankowano.
        kod = _liczba_calkowita(_w(w, i_paliwo))
        if kod is not None and kod > 0:
            return 600 <= kod < 700
        typ = typy_zbiornikow.get(zbiornik(w))
        return typ is not None and 600 <= typ < 700

    def mnoznik(w):
        return 1.0 if czy_prad(w) else mnozniki.get(jednostki_paliwa.get(zbiornik(w), "0"), 1.0)

    def litry(w):
        ilosc = _liczba_csv(_w(w, i_ilosc), dziesietny)
        return _w(w, i_ilosc) if ilosc is None else _tekst_liczby(ilosc * mnoznik(w))

    def kwota(w):
        cena = _liczba_csv(_w(w, i_cena), dziesietny)
        if cena is not None and cena > 0:
            return _tekst_liczby(cena)
        ilosc = _liczba_csv(_w(w, i_ilosc), dziesietny)
        za_jednostke = _liczba_csv(_w(w, i_cena_jedn), dziesietny)
        return _tekst_liczby(ilosc * za_jednostke) if ilosc and za_jednostke else _w(w, i_cena)

    wyliczone = [("data", "Data (DD.MM.RRRR)", _funkcja_daty(dane, i_data, kolejnosc))]
    if any(mnoznik(w) != 1.0 for w in dane):
        wyliczone.append(("litry", "Ilość (z galonów na litry)", litry))
        wynik["uwagi"].append("Ilość paliwa w galonach — przeliczona na litry.")
    if any((_liczba_csv(_w(w, i_cena), dziesietny) or 0) <= 0 for w in dane):
        wyliczone.append(("kwota", "Kwota (albo ilość × cena za jednostkę)", kwota))
    elektryczne = any(czy_prad(w) for w in dane)
    if elektryczne:
        wyliczone.append(("rodzaj_energii", "Źródło (z kodu paliwa)", lambda w: _PRAD if czy_prad(w) else _PALIWO))
    _uwaga_o_pominietych_tankowaniach(wynik, dane, _kolumna(naglowki, "missed"))
    zbiorniki_paliwa = {zbiornik(w) for w in dane if not czy_prad(w)}
    if len(zbiorniki_paliwa) > 1:
        wynik["uwagi"].append("Auto ma w Fuelio dwa zbiorniki paliwa (np. benzyna i LPG) — tankowania obu "
                              "trafią do jednej historii paliwa.")

    _czesc(wynik, "tankowania", f"sekcja „{oryginal}”", naglowki, dane, numery, {
        "przebieg": i_odo, "litry": i_ilosc, "kwota": i_cena, "do_pelna": i_pelne,
        "stacja": i_miasto, "notatka": i_notatki,
    }, wyliczone)


def _fuelio_koszty(wynik, sekcje, kolejnosc):
    oryginal, naglowki, dane, numery = sekcje.get("costs", _PUSTA_SEKCJA)
    if not dane:
        return

    _, naglowki_k, dane_k, _ = sekcje.get("costcategories", _PUSTA_SEKCJA)
    i_id, i_nazwa_k = _kolumna(naglowki_k, "costtypeid"), _kolumna(naglowki_k, "name")
    kategorie = {_w(w, i_id).strip(): _w(w, i_nazwa_k).strip() for w in dane_k}

    i_tytul = _kolumna(naglowki, "costtitle", "title")
    i_data = _kolumna(naglowki, "date", "data")
    i_odo = _kolumna(naglowki, "odo")
    i_typ = _kolumna(naglowki, "costtypeid")
    i_notatki = _kolumna(naglowki, "notes")
    i_koszt = _kolumna(naglowki, "cost")
    i_szablon = _kolumna(naglowki, "istemplate")
    i_przychod = _kolumna(naglowki, "isincome")
    i_przyp_data = _kolumna(naglowki, "reminddate")
    i_przyp_odo = _kolumna(naglowki, "remindodo")
    dziesietny = _konwencja(dane, i_koszt, i_odo)

    def powod(w):
        if _tak(_w(w, i_szablon)):
            return "szablony kosztów"
        if _tak(_w(w, i_przychod)):
            return "przychody"
        koszt = _liczba_csv(_w(w, i_koszt), dziesietny) or 0
        przypomnienie = _w(w, i_przyp_data).strip() or (_liczba_csv(_w(w, i_przyp_odo)) or 0) > 0
        if koszt <= 0 and przypomnienie:
            return "przypomnienia bez kwoty"
        return None

    dane, numery = _odfiltruj(wynik, dane, numery, powod)

    def kategoria(w):
        return kategorie.get(_w(w, i_typ).strip(), "")

    def tytul(w):
        return _w(w, i_tytul).strip() or kategoria(w)

    def serwis(w):
        # Numery 1 i 2 to domyślne „Service” i „Maintenance” — w każdym języku
        # interfejsu te same, nazwy już nie. Kategoria własna decyduje nazwą,
        # a ogólna („Other”) albo pusta oddaje głos tytułowi kosztu.
        if _w(w, i_typ).strip() in ("1", "2"):
            return True
        nazwa = kategoria(w)
        if nazwa and not _nazwa_ogolna(nazwa):
            return czy_nazwa_serwisowa(nazwa)
        return czy_nazwa_serwisowa(_w(w, i_tytul))

    (serwisowe, numery_s), (reszta, numery_r) = _podziel(dane, numery, serwis)
    data = _funkcja_daty(dane, i_data, kolejnosc)

    _czesc(wynik, "inne_koszty", f"sekcja „{oryginal}”, bez serwisu", naglowki, reszta, numery_r, {
        "kwota": i_koszt, "notatka": i_notatki,
    }, [
        ("data", "Data (DD.MM.RRRR)", data),
        ("nazwa", "Nazwa (tytuł albo kategoria)", tytul),
        ("kategoria", "Kategoria (z numeru)", kategoria),
    ])
    _czesc(wynik, "wizyty", f"sekcja „{oryginal}”, kategorie serwisowe", naglowki, serwisowe, numery_s, {
        "przebieg": i_odo, "kwota": i_koszt, "notatka": i_notatki,
    }, [
        ("data", "Data (DD.MM.RRRR)", data),
        ("opis", "Zakres prac (tytuł albo kategoria)", tytul),
    ])


# ==================== DRIVVO ====================
# Eksport CSV (Pro): sekcje „##Vehicle”, „##Refuelling”, „##Expense”, „##Service” (po
# hiszpańsku „#Reabastecimiento”, „#Servicio”). Nagłówki i wartości są tłumaczone, więc
# kolumny bierzemy z POZYCJI (jak konwerter FuelioImport) i sprawdzamy, czy są tam daty
# i liczby.

_SEKCJE_DRIVVO = {
    "tankowania": {"refuelling", "refueling", "reabastecimiento", "reabastecimientos", "abastecimento",
                   "abastecimentos", "tankowanie", "tankowania"},
    "inne_koszty": {"expense", "expenses", "gasto", "gastos", "despesa", "despesas", "wydatek", "wydatki"},
    "wizyty": {"service", "services", "servicio", "servicios", "servico", "servicos", "serwis"},
}
_PRZYCHODY_DRIVVO = {"income", "incomes", "ingreso", "ingresos", "receita", "receitas", "przychod", "przychody"}
_TRASY_DRIVVO = {"route", "routes", "ruta", "rutas", "rota", "rotas", "trasa", "trasy"}


def _to_drivvo(wiersze):
    znaczniki = {_znacznik_krzyzykowy(w) for w in wiersze}
    znane = set().union(*_SEKCJE_DRIVVO.values())
    return bool(znaczniki & znane) and not _to_fuelio(wiersze)


def _sekcja_drivvo(sekcje, nazwy):
    return next((s for nazwa, s in sekcje.items() if nazwa in nazwy), _PUSTA_SEKCJA)


def _pozycje_pasuja(dane, i_data, i_liczba):
    """Czy pod pozycjami z konwertera leżą data i liczba — w co najmniej
    połowie wierszy. Jeśli nie, układ jest inny i kolumny dopasujemy po nazwach."""
    if not dane:
        return False
    trafienia = sum(1 for w in dane if _parsuj_date_csv(_w(w, i_data), "dmy") or _parsuj_date_csv(_w(w, i_data), "mdy"))
    liczby = sum(1 for w in dane if _parsuj_liczbe_csv(_w(w, i_liczba)) is not None)
    return trafienia * 2 >= len(dane) and liczby * 2 >= len(dane)


def _kolumna_notatek(naglowki):
    return _kolumna_z(naglowki, _zawiera("note", "nota", "observ", "notatk", "uwag", "coment", "comment"))


def _rozbierz_drivvo(wiersze, pojazd=None):
    wynik = _nowy_wynik("drivvo")
    sekcje = _sekcje(wiersze, _znacznik_krzyzykowy)

    _, naglowki_p, dane_p, _ = sekcje.get("vehicle", _PUSTA_SEKCJA)
    if dane_p:
        wynik["nazwa_pojazdu"] = " ".join(k for k in dane_p[0][:2] if k.strip()) or None

    # Tankowania: 0 licznik, 1 data, 2 paliwo, 3 cena za jednostkę,
    # 4 kwota, 5 ilość, 6 „do pełna”; notatki z nagłówka albo pozycja 18.
    oryginal, naglowki, dane, numery = _sekcja_drivvo(sekcje, _SEKCJE_DRIVVO["tankowania"])
    if dane:
        if _pozycje_pasuja(dane, 1, 0):
            i_notatki = _pierwszy(_kolumna_notatek(naglowki), 18 if len(naglowki) > 18 else None)
            i_stacja = _kolumna_z(naglowki, _zawiera("station", "posto", "estacion", "gasolinera", "stacj"))
            wyliczone = [("data", "Data (DD.MM.RRRR)", _funkcja_daty(dane, 1))]
            if len(naglowki) > 6:
                wyliczone.append(("do_pelna", "Do pełna (1 / 0)", lambda w: "1" if _tak(_w(w, 6)) else "0"))
            if any(_rodzaj_z_nazwy_paliwa(_w(w, 2)) == _PRAD for w in dane):
                wyliczone.append(("rodzaj_energii", "Źródło (z nazwy paliwa)",
                                  lambda w: _rodzaj_z_nazwy_paliwa(_w(w, 2))))
            kolumny = {"przebieg": 0, "kwota": 4, "litry": 5, "stacja": i_stacja, "notatka": i_notatki}
        else:
            wyliczone, kolumny = [], {}
        _czesc(wynik, "tankowania", f"sekcja „{oryginal}”", naglowki, dane, numery, kolumny, wyliczone)

    # Wydatki: 0 licznik, 1 data, 2 kwota, 3 rodzaj wydatku, 6 notatki.
    oryginal, naglowki, dane, numery = _sekcja_drivvo(sekcje, _SEKCJE_DRIVVO["inne_koszty"])
    if dane:
        if _pozycje_pasuja(dane, 1, 2):
            i_notatki = _pierwszy(_kolumna_notatek(naglowki), 6 if len(naglowki) > 6 else None)
            kolumny = {"kwota": 2, "nazwa": 3, "kategoria": 3, "notatka": i_notatki}
            wyliczone = [("data", "Data (DD.MM.RRRR)", _funkcja_daty(dane, 1))]
        else:
            wyliczone, kolumny = [], {}
        _czesc(wynik, "inne_koszty", f"sekcja „{oryginal}”", naglowki, dane, numery, kolumny, wyliczone)

    # Serwis: 0 licznik, 1 data, 2 kwota, 3 rodzaj usługi, 5 notatki.
    oryginal, naglowki, dane, numery = _sekcja_drivvo(sekcje, _SEKCJE_DRIVVO["wizyty"])
    if dane:
        if _pozycje_pasuja(dane, 1, 2):
            i_notatki = _pierwszy(_kolumna_notatek(naglowki), 5 if len(naglowki) > 5 else None)
            i_warsztat = _kolumna_z(naglowki, _zawiera("workshop", "oficina", "taller", "warsztat", "place", "local"))
            kolumny = {"przebieg": 0, "kwota": 2, "opis": 3, "warsztat": i_warsztat, "notatka": i_notatki}
            wyliczone = [("data", "Data (DD.MM.RRRR)", _funkcja_daty(dane, 1))]
        else:
            wyliczone, kolumny = [], {}
        _czesc(wynik, "wizyty", f"sekcja „{oryginal}”", naglowki, dane, numery, kolumny, wyliczone)

    for nazwa, (oryginal, _, dane, _) in sekcje.items():
        if nazwa in _PRZYCHODY_DRIVVO and dane:
            wynik["pominiete"]["przychody"] += len(dane)
        elif nazwa in _TRASY_DRIVVO and dane:
            wynik["uwagi"].append(f"Trasy z sekcji „{oryginal}” nie są importowane.")
    return wynik


# ==================== aCar ====================
# Sekcje nazwane w osobnym wierszu („Fill-Up Records”, „Service Records”, „Expense
# Records”, „Vehicles”, „Trip Records”), w każdej kolumna „Vehicle” (kilka aut w pliku).
# Daty MM/DD/RRRR, liczby „12,345” i „$45.67”, jednostki w kolumnach obok.

_SEKCJE_ACAR = {
    "fill-up records": "tankowania", "fillup records": "tankowania", "fill up records": "tankowania",
    "service records": "wizyty", "expense records": "inne_koszty",
    "trip records": None, "vehicles": None, "metadata": None,
}


def _znacznik_acar(wiersz):
    niepuste = [k for k in wiersz if k.strip()]
    if len(niepuste) != 1:
        return None
    nazwa = _normalizuj_naglowek(niepuste[0].strip(" :#"))
    return nazwa if nazwa in _SEKCJE_ACAR else None


def _to_acar(wiersze):
    if any(_SEKCJE_ACAR.get(_znacznik_acar(w) or "") for w in wiersze):
        return True
    return any({"odometer reading", "partial fill-up?"} <= {_normalizuj_naglowek(k) for k in w} for w in wiersze)


def _sekcje_acar(wiersze):
    """{typ importu: (oryginał, nagłówki, wiersze, numery)}. Plik bez nazw
    sekcji (eksport jednej listy) rozpoznajemy po kolumnach nagłówka."""
    sekcje = {}
    for nazwa, sekcja in _sekcje(wiersze, _znacznik_acar).items():
        typ = _SEKCJE_ACAR.get(nazwa.split(" (")[0])
        if typ and typ not in sekcje:
            sekcje[typ] = sekcja
    if not sekcje:
        naglowki, dane = tabela_z_wierszy(wiersze)
        kolumny = {_normalizuj_naglowek(n) for n in naglowki}
        typ = ("tankowania" if {"volume", "partial fill-up?"} & kolumny
               else "wizyty" if "services" in kolumny else "inne_koszty" if "expenses" in kolumny else None)
        if typ:
            sekcje[typ] = ("", naglowki, dane, list(range(2, len(dane) + 2)))
    return sekcje


def _rozbierz_acar(wiersze, pojazd=None):
    wynik = _nowy_wynik("acar")
    sekcje = _sekcje_acar(wiersze)

    wartosci_pojazdow = []
    for _, naglowki, dane, _ in sekcje.values():
        i_poj = _kolumna(naglowki, "vehicle")
        wartosci_pojazdow += [_w(w, i_poj).strip() for w in dane]
    wybrany = _wybierz_pojazd(wynik, wartosci_pojazdow, pojazd, lambda klucz: klucz)
    wynik["nazwa_pojazdu"] = wybrany or next((v for v in wartosci_pojazdow if v), None)

    def dla_pojazdu(naglowki, dane, numery):
        i_poj = _kolumna(naglowki, "vehicle")
        if wybrany is None or i_poj is None:
            return dane, numery
        return _odfiltruj(wynik, dane, numery, lambda w: None if _w(w, i_poj).strip() == wybrany else _INNE_AUTA)

    oryginal, naglowki, dane, numery = sekcje.get("tankowania", _PUSTA_SEKCJA)
    dane, numery = dla_pojazdu(naglowki, dane, numery)
    if dane:
        i_data = _kolumna(naglowki, "date")
        i_odo = _kolumna(naglowki, "odometer reading", "odometer")
        i_dystans_j = _kolumna(naglowki, "distance unit")
        i_ilosc = _kolumna(naglowki, "volume")
        i_objetosc_j = _kolumna(naglowki, "volume unit")
        i_kwota = _kolumna(naglowki, "total cost")
        i_czesciowe = _kolumna(naglowki, "partial fill-up?", "partial fill-up", "partial")
        i_paliwo = _kolumna(naglowki, "fuel type")
        i_marka = _kolumna(naglowki, "fuel brand")
        i_adres = _kolumna(naglowki, "fueling station address", "fuel station", "station")
        i_notatki = _kolumna(naglowki, "notes")

        jednostki = Counter(_jednostka_dystansu(_w(w, i_dystans_j)) for w in dane)
        jednostki.pop(None, None)
        if jednostki:
            wynik["jednostka"] = jednostki.most_common(1)[0][0]

        dziesietny = _konwencja(dane, i_odo, i_ilosc, i_kwota)

        def litry(w):
            ilosc = _liczba_csv(_w(w, i_ilosc), dziesietny)
            return _w(w, i_ilosc) if ilosc is None else _tekst_liczby(ilosc * _mnoznik_objetosci(_w(w, i_objetosc_j)))

        wyliczone = [
            ("data", "Data (DD.MM.RRRR)", _funkcja_daty(dane, i_data, "mdy")),
            ("stacja", "Stacja (marka albo adres)", lambda w: _w(w, i_marka).strip() or _w(w, i_adres).strip()),
        ]
        if i_czesciowe is not None:
            wyliczone.append(("do_pelna", "Do pełna (odwrotność „Partial”)",
                              lambda w: "0" if _tak(_w(w, i_czesciowe)) else "1"))
        _uwaga_o_pominietych_tankowaniach(
            wynik, dane, _kolumna(naglowki, "previously missed fill-ups?", "previously missed fill-ups"))
        if any(_mnoznik_objetosci(_w(w, i_objetosc_j)) != 1.0 for w in dane):
            wyliczone.append(("litry", "Ilość (z galonów na litry)", litry))
            wynik["uwagi"].append("Ilość paliwa w galonach — przeliczona na litry.")
        if any(_rodzaj_z_nazwy_paliwa(_w(w, i_paliwo)) == _PRAD for w in dane):
            wyliczone.append(("rodzaj_energii", "Źródło (z rodzaju paliwa)",
                              lambda w: _rodzaj_z_nazwy_paliwa(_w(w, i_paliwo))))
        _czesc(wynik, "tankowania", f"sekcja „{oryginal}”" if oryginal else "tabela tankowań", naglowki, dane,
               numery, {"przebieg": i_odo, "litry": i_ilosc, "kwota": i_kwota, "notatka": i_notatki}, wyliczone)

    oryginal, naglowki, dane, numery = sekcje.get("wizyty", _PUSTA_SEKCJA)
    dane, numery = dla_pojazdu(naglowki, dane, numery)
    if dane:
        _czesc(wynik, "wizyty", f"sekcja „{oryginal}”" if oryginal else "tabela serwisu", naglowki, dane, numery, {
            "przebieg": _kolumna(naglowki, "odometer reading", "odometer"),
            "kwota": _kolumna(naglowki, "total cost", "cost"),
            "opis": _kolumna(naglowki, "services", "service", "service types", "description"),
            "warsztat": _kolumna(naglowki, "service center name", "service center", "place"),
            "notatka": _kolumna(naglowki, "notes"),
        }, [("data", "Data (DD.MM.RRRR)", _funkcja_daty(dane, _kolumna(naglowki, "date"), "mdy"))])

    oryginal, naglowki, dane, numery = sekcje.get("inne_koszty", _PUSTA_SEKCJA)
    dane, numery = dla_pojazdu(naglowki, dane, numery)
    if dane:
        i_nazwa = _kolumna(naglowki, "expenses", "expense", "expense types", "description")
        _czesc(wynik, "inne_koszty", f"sekcja „{oryginal}”" if oryginal else "tabela wydatków", naglowki, dane,
               numery, {
                   "kwota": _kolumna(naglowki, "total cost", "cost"),
                   "nazwa": i_nazwa, "kategoria": i_nazwa,
                   "notatka": _kolumna(naglowki, "notes"),
               }, [("data", "Data (DD.MM.RRRR)", _funkcja_daty(dane, _kolumna(naglowki, "date"), "mdy"))])
    return wynik


# ==================== SIMPLY AUTO ====================
# Fuel_Log.csv: jedna tabela dla pojazdów („Vehicle ID”) i rodzajów („Record Type”: 0
# tankowanie, 1 serwis, 2 wydatek), data w Day / Month / Year, „Partial Tank” = 1 przy
# niepełnym, opis w „Record Desc”.


def _to_simply_auto(wiersze):
    naglowki = {_normalizuj_naglowek(k) for k in (wiersze[0] if wiersze else [])}
    return {"record type", "vehicle id"} <= naglowki and bool({"partial tank", "qty", "record desc"} & naglowki)


def _rozbierz_simply_auto(wiersze, pojazd=None):
    wynik = _nowy_wynik("simply_auto")
    naglowki, dane = tabela_z_wierszy(wiersze)
    numery = list(range(2, len(dane) + 2))

    i_poj = _kolumna(naglowki, "vehicle id")
    i_typ = _kolumna(naglowki, "record type")
    i_odo = _kolumna(naglowki, "odometer", "odo")
    i_ilosc = _kolumna(naglowki, "qty", "quantity")
    i_czesciowe = _kolumna(naglowki, "partial tank", "partial")
    i_kwota = _kolumna(naglowki, "total cost", "cost")
    i_dystans = _kolumna(naglowki, "distance traveled", "distance travelled", "distance")
    i_marka = _kolumna(naglowki, "fuel brand")
    i_stacja = _kolumna(naglowki, "filling station", "station")
    i_notatki = _kolumna(naglowki, "notes")
    i_opis = _kolumna(naglowki, "record desc", "record description", "description")
    i_dzien, i_miesiac, i_rok = (_kolumna(naglowki, "day"), _kolumna(naglowki, "month"),
                                 _kolumna(naglowki, "year"))

    wybrany = _wybierz_pojazd(wynik, [_w(w, i_poj).strip() for w in dane], pojazd,
                              lambda klucz: f"Pojazd „{klucz}”")
    if wybrany is not None:
        dane, numery = _odfiltruj(wynik, dane, numery,
                                  lambda w: None if _w(w, i_poj).strip() == wybrany else _INNE_AUTA)

    # Miesiąc: aplikacja na Androidzie mogła zapisać go od zera (styczeń = 0).
    # Zero w kolumnie rozstrzyga; bez niego — zwykła numeracja od 1.
    miesiace = {_liczba_calkowita(_w(w, i_miesiac)) for w in dane}
    przesuniecie = 1 if 0 in miesiace else 0
    if przesuniecie:
        wynik["uwagi"].append("Miesiące w pliku liczone od zera — przesunięte o jeden.")

    def data(w):
        d, m, r = (_liczba_calkowita(_w(w, i_dzien)), _liczba_calkowita(_w(w, i_miesiac)),
                   _liczba_calkowita(_w(w, i_rok)))
        if None in (d, m, r):
            return ""
        try:
            return date(r + 2000 if r < 100 else r, m + przesuniecie, d).strftime("%d.%m.%Y")
        except ValueError:
            return f"{_w(w, i_dzien)}.{_w(w, i_miesiac)}.{_w(w, i_rok)}"

    rodzaje = {0: "tankowania", 1: "wizyty", 2: "inne_koszty"}

    def powod(w):
        return None if _liczba_calkowita(_w(w, i_typ)) in rodzaje else "wpisy nieznanego rodzaju"

    dane, numery = _odfiltruj(wynik, dane, numery, powod)
    grupy = {typ: ([], []) for typ in rodzaje.values()}
    for wiersz, nr in zip(dane, numery):
        grupa = grupy[rodzaje[_liczba_calkowita(_w(wiersz, i_typ))]]
        grupa[0].append(wiersz)
        grupa[1].append(nr)

    kolumna_daty = ("data", "Data (z Day / Month / Year)", data)
    _uwaga_o_pominietych_tankowaniach(wynik, grupy["tankowania"][0], _kolumna(naglowki, "missed fill up", "missed"))
    _czesc(wynik, "tankowania", "wiersze z „Record Type” 0", naglowki, *grupy["tankowania"], {
        "przebieg": i_odo, "dystans": i_dystans, "litry": i_ilosc, "kwota": i_kwota, "notatka": i_notatki,
    }, [
        kolumna_daty,
        ("do_pelna", "Do pełna (odwrotność „Partial Tank”)", lambda w: "0" if _tak(_w(w, i_czesciowe)) else "1"),
        ("stacja", "Stacja (stacja albo marka)", lambda w: _w(w, i_stacja).strip() or _w(w, i_marka).strip()),
    ])
    _czesc(wynik, "wizyty", "wiersze z „Record Type” 1", naglowki, *grupy["wizyty"], {
        "przebieg": i_odo, "kwota": i_kwota, "opis": i_opis, "warsztat": i_stacja, "notatka": i_notatki,
    }, [kolumna_daty])
    _czesc(wynik, "inne_koszty", "wiersze z „Record Type” 2", naglowki, *grupy["inne_koszty"], {
        "kwota": i_kwota, "nazwa": i_opis, "kategoria": i_opis, "notatka": i_notatki,
    }, [kolumna_daty])
    return wynik


# ==================== REJESTR ====================
# Kolejność ma znaczenie przy rozpoznawaniu: Fuelio przed Drivvo (oba mają
# znaczniki z „#”), reszta rozpoznaje się po własnych nazwach.

PRESETY_IMPORTU = {
    "fuelio": {
        "etykieta": "Fuelio",
        "opis": "Kopia CSV z Fuelio — plik pojazdu z folderu Fuelio/backup-csv (także z Dysku Google albo "
                "Dropboxa, może być spakowany w ZIP). Tankowania z sekcji „## Log”, koszty i serwis z „## Costs”; "
                "jednostki i format daty z nagłówka pliku.",
        "rozpoznaj": _to_fuelio,
        "rozbierz": _rozbierz_fuelio,
    },
    "drivvo": {
        "etykieta": "Drivvo",
        "opis": "Eksport CSV z Drivvo (wersja Pro). Tankowania z sekcji „##Refuelling”, wydatki z „##Expense”, "
                "serwis z „##Service”.",
        "rozpoznaj": _to_drivvo,
        "rozbierz": _rozbierz_drivvo,
    },
    "acar": {
        "etykieta": "aCar",
        "opis": "Eksport rekordów CSV z aCar: „Fill-Up Records”, „Service Records” i „Expense Records”. Galony "
                "przeliczamy na litry, a z pliku z kilkoma autami wybierzesz jedno. Pełnej kopii .abp nie czytamy.",
        "rozpoznaj": _to_acar,
        "rozbierz": _rozbierz_acar,
    },
    "simply_auto": {
        "etykieta": "Simply Auto",
        "opis": "Plik Fuel_Log.csv z kopii Simply Auto (folder na Dysku Google albo logi CSV z e-maila; może być "
                "cały ZIP). Jeden plik ma tankowania, serwis i wydatki wszystkich aut — wybierzesz, które przenieść.",
        "rozpoznaj": _to_simply_auto,
        "rozbierz": _rozbierz_simply_auto,
    },
}


def rozpoznaj_aplikacje(wiersze) -> str | None:
    """Klucz presetu, z którego aplikacji pochodzi plik, albo None — wtedy
    zostaje ręczne dopasowanie kolumn."""
    for klucz, preset in PRESETY_IMPORTU.items():
        if preset["rozpoznaj"](wiersze):
            return klucz
    return None


def rozbierz_plik_importu(aplikacja, wiersze, pojazd=None) -> dict:
    """Plik aplikacji (surowe wiersze z `wczytaj_wiersze_csv`) rozłożony na części do
    importu: {"czesci": [{typ, zrodlo, naglowki, wiersze, numery, mapowanie}],
    "pominiete": [(powód, liczba)], "jednostka": "km"|"mi"|None, "pojazdy": [(klucz,
    etykieta, liczba)], "pojazd", "nazwa_pojazdu", "uwagi"}. Przy kilku autach części
    mają wpisy wybranego (`pojazd` albo najczęstszego)."""
    wynik = PRESETY_IMPORTU[aplikacja]["rozbierz"](wiersze, pojazd)
    wynik["pominiete"] = wynik["pominiete"].most_common()
    return wynik


__all__ = [
    "LITRY_W_GALONIE_UK",
    "LITRY_W_GALONIE_US",
    "PRESETY_IMPORTU",
    "rozbierz_plik_importu",
    "rozpoznaj_aplikacje",
]
