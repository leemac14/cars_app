"""Import danych z plików CSV."""

import csv
import io
import re
import unicodedata
import zipfile
from date import na_iso, parsuj_date
from datetime import datetime

from .stale import (ENERGIA_PALIWO, ENERGIA_PRAD, KATEGORIA_INNE_DOMYSLNA, KATEGORIA_INNE_DROGOWE,
                    KATEGORIE_INNYCH_KOSZTOW)
from .polaczenie import polacz_baze
from .pomocnicze import _parsuj_liczbe_csv, formatuj_liczba_eksport
from .ustawienia import pobierz_moje_imie
from .jednostki import dystans_na_km, tekst_dystansu
from .energia import ETYKIETY_RODZAJU, domyslny_rodzaj_energii
from .notatki import przytnij_notatke
from .nazwy import klucz_nazwy, normalizuj_nazwe
from .rejestry import WARSZTAT_BEZ_NAZWY
from .ewidencja import opis_trasy, tekst_km_przejazdu


# ==================== IMPORT CSV (TANKOWANIA) ====================

POLA_IMPORTU_TANKOWAN = {
    "data": ("Data", True),
    "przebieg": ("Licznik (km)", False),
    "dystans": ("Dystans (km)", False),
    "litry": ("Litry / kWh", True),
    "kwota": ("Kwota", True),
    "stacja": ("Stacja / punkt ładowania", False),
    "do_pelna": ("Do pełna", False),
    # Kolumna sensowna tylko przy hybrydzie plug-in: bez niej cały plik trafia
    # do domyślnego źródła pojazdu, czyli zachowuje się jak dotąd.
    "rodzaj_energii": ("Źródło (paliwo / prąd)", False),
    # Krótka notatka przy wpisie (limit jak w formularzu, MAKS_DLUGOSC_NOTATKI).
    "notatka": ("Notatka", False),
}


# Wspólne dla wszystkich typów — „Notes (optional)” z Fuelio łapie „note”.
_ALIASY_NOTATKI = ["notatka", "notatki", "uwagi", "komentarz", "notes", "note", "comment", "comments",
                   "remarks", "observacoes", "observações", "notas"]


_ALIASY_IMPORTU = {
    "data": ["data", "date", "data tankowania", "dzien", "dzień", "datum"],
    "przebieg": ["przebieg", "licznik", "odometer", "odo", "mileage", "km", "stan licznika", "przebieg (km)",
                 "przebieg (mi)"],
    "dystans": ["dystans", "distance", "trip", "przejechano", "dystans (km)", "dystans (mi)"],
    "litry": ["litry", "liters", "litres", "ilosc", "ilość", "volume", "quantity", "kwh", "energia", "paliwo"],
    "kwota": ["kwota", "koszt", "cena", "cost", "total", "total cost", "price", "wartosc", "wartość"],
    "stacja": ["stacja", "station", "punkt ladowania", "punkt ładowania", "miejsce", "fuel station", "sprzedawca"],
    "do_pelna": ["do pelna", "do pełna", "full", "pelny bak", "pełny bak", "full tank", "tankowanie do pelna"],
    "rodzaj_energii": ["rodzaj", "zrodlo", "źródło", "energia", "typ", "paliwo/prad", "fuel type"],
    "notatka": _ALIASY_NOTATKI,
}


def _normalizuj_naglowek(tekst):
    return " ".join(str(tekst or "").strip().lower().replace("_", " ").split())


# Kolejność prób przy datach dwuznacznych (05/03/2024). Europejska jest
# domyślna; amerykańską wybiera `rozpoznaj_kolejnosc_dat`, gdy kolumna sama to
# zdradza, albo preset aplikacji, która tak zapisuje (aCar).
_WZORCE_DAT = {
    "dmy": ("%d.%m.%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d.%m.%y", "%d/%m/%y"),
    "mdy": ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m.%d.%Y", "%Y/%m/%d", "%m/%d/%y", "%m.%d.%y"),
}

_DATA_Z_DNIEM_I_MIESIACEM = re.compile(r"\s*(\d{1,2})[./-](\d{1,2})[./-]\d{2,4}(?!\d)")


def _parsuj_date_csv(tekst, kolejnosc="dmy"):
    """Zwraca datę w formacie aplikacji ('DD.MM.YYYY') albo None. Formaty
    dwuznaczne (dd/mm vs mm/dd) rozstrzyga `kolejnosc` — domyślnie po
    europejsku, dd/mm/yyyy."""
    s = str(tekst or "").strip()
    if not s:
        return None
    s = s.split("T")[0].strip()
    if " " in s and len(s.split(" ")[0]) >= 6:
        s = s.split(" ")[0]
    for wzorzec in _WZORCE_DAT.get(kolejnosc, _WZORCE_DAT["dmy"]):
        try:
            return datetime.strptime(s, wzorzec).strftime("%d.%m.%Y")
        except ValueError:
            continue
    return None


def rozpoznaj_kolejnosc_dat(wartosci, domyslna="dmy") -> str:
    """„dmy” albo „mdy” dla całej kolumny dat. Rozstrzyga każda data, w której
    jedna z dwóch pierwszych liczb przekracza 12 — 25/03 to dzień i miesiąc,
    03/25 miesiąc i dzień. Kolumna bez takiej daty (albo z datami w obu
    układach naraz) zostaje przy `domyslna`."""
    dzien_pierwszy = miesiac_pierwszy = False
    for wartosc in wartosci:
        dopasowanie = _DATA_Z_DNIEM_I_MIESIACEM.match(str(wartosc or ""))
        if not dopasowanie:
            continue
        pierwsza, druga = int(dopasowanie.group(1)), int(dopasowanie.group(2))
        if pierwsza > 12 >= druga:
            dzien_pierwszy = True
        elif druga > 12 >= pierwsza:
            miesiac_pierwszy = True
    if dzien_pierwszy != miesiac_pierwszy:
        return "dmy" if dzien_pierwszy else "mdy"
    return domyslna


def _rozpoznaj_rodzaj_csv(tekst, auto_id):
    """Rozpoznaje źródło energii z kolumny pliku — po polsku i po angielsku.
    Nierozpoznane albo puste = domyślne źródło pojazdu, więc pliki bez tej
    kolumny (czyli praktycznie wszystkie) importują się jak dotąd."""
    znormalizowany = _normalizuj_naglowek(tekst)
    if not znormalizowany:
        return domyslny_rodzaj_energii(auto_id)
    if any(slowo in znormalizowany for slowo in ("prad", "prąd", "electric", "kwh", "ladow", "ładow", "charge", "ev")):
        return ENERGIA_PRAD
    if any(slowo in znormalizowany for slowo in ("paliw", "fuel", "benzyn", "diesel", "petrol", "gas", "lpg", "tankow")):
        return ENERGIA_PALIWO
    return domyslny_rodzaj_energii(auto_id)


def _prawda_csv(tekst):
    return _normalizuj_naglowek(tekst) in ("1", "tak", "yes", "true", "y", "t", "prawda", "x",
                                           "sí", "si", "sim", "ja")


_TYSIACE_PRZECINKIEM = re.compile(r"-?\d{1,3}(,\d{3})+")
_TYSIACE_KROPKA = re.compile(r"-?\d{1,3}(\.\d{3})+")


def rozpoznaj_separator_dziesietny(wartosci) -> str | None:
    """Separator dziesiętny całego pliku: „.”, „,” albo None. Głosują tylko liczby
    jednoznaczne („1,234.56”, „45,67”, „1.234.567”); głosy za oboma → None i ocena
    liczba po liczbie (`_parsuj_liczbe_csv`)."""
    glosy = set()
    for wartosc in wartosci:
        s = "".join(znak for znak in str(wartosc or "") if znak in "0123456789,.-")
        if not any(znak.isdigit() for znak in s):
            continue
        if "," in s and "." in s:
            glosy.add("," if s.rfind(",") > s.rfind(".") else ".")
        elif s.count(".") > 1 or s.count(",") > 1:
            glosy.add("," if s.count(".") > 1 else ".")
        elif "." in s and not _TYSIACE_KROPKA.fullmatch(s):
            glosy.add(".")
        elif "," in s and not _TYSIACE_PRZECINKIEM.fullmatch(s):
            glosy.add(",")
    return glosy.pop() if len(glosy) == 1 else None


def _liczba_csv(tekst, dziesietny=None):
    """`_parsuj_liczbe_csv` ze znaną konwencją pliku: separator tysięcy wypada
    przed parsowaniem, więc „12,345” w pliku z kropką dziesiętną to 12345,
    a nie 12,345. Bez konwencji — dotychczasowa ocena liczba po liczbie."""
    if tekst is None:
        return None
    s = str(tekst)
    if dziesietny == ".":
        s = s.replace(",", "")
    elif dziesietny == ",":
        s = s.replace(".", "")
    return _parsuj_liczbe_csv(s)


def _konwencja_liczb(wiersze, mapowanie, pola):
    return rozpoznaj_separator_dziesietny(
        _wartosc_z_wiersza(wiersz, mapowanie, pole) for wiersz in wiersze for pole in pola)


def _kolejnosc_dat(wiersze, mapowanie, domyslna="dmy"):
    return rozpoznaj_kolejnosc_dat((_wartosc_z_wiersza(w, mapowanie, "data") for w in wiersze), domyslna)


def _tekst_pliku(sciezka):
    """Treść pliku jako tekst z ujednoliconymi końcami linii. Archiwum ZIP
    (tak Fuelio trzyma kopie na Dysku Google: vehicle-1-sync.csv.zip) otwieramy
    i bierzemy z niego plik CSV — Fuel_Log.csv, jeśli jest (Simply Auto),
    inaczej pierwszy z brzegu."""
    if zipfile.is_zipfile(sciezka):
        with zipfile.ZipFile(sciezka) as archiwum:
            nazwy = sorted((n for n in archiwum.namelist() if n.lower().endswith((".csv", ".tsv", ".txt"))),
                           key=lambda n: ("fuel_log" not in n.lower(), n))
            if not nazwy:
                raise ValueError("W archiwum ZIP nie ma pliku CSV.")
            bajty = archiwum.read(nazwy[0])
    else:
        with open(sciezka, "rb") as f:
            bajty = f.read()

    surowe = None
    for kodowanie in ("utf-8-sig", "cp1250", "latin-1"):
        try:
            surowe = bajty.decode(kodowanie)
            break
        except UnicodeDecodeError:
            continue
    if surowe is None:
        raise ValueError("Nie udało się odczytać pliku — nieznane kodowanie znaków.")
    # Eksporty z iPhone'a (Drivvo) kończą linie samym CR.
    return surowe.replace("\r\n", "\n").replace("\r", "\n")


def _separator_pliku(surowe):
    """Separator z pierwszej linii, a gdy ta go nie ma — z kolejnych. Pliki
    z sekcjami zaczynają się od samego znacznika („## Vehicle” w Fuelio,
    „##Refuelling” w Drivvo), który o separatorze nic nie mówi."""
    linie = [linia for linia in surowe.split("\n") if linia.strip()][:30]
    kandydaci = (";", ",", "\t")
    separator = max(kandydaci, key=linie[0].count)
    if linie[0].count(separator) == 0:
        separator = max(kandydaci, key=lambda s: sum(linia.count(s) for linia in linie))
        if not any(linia.count(separator) for linia in linie):
            separator = ";"
    return separator


def wczytaj_wiersze_csv(sciezka) -> list[list[str]]:
    """Wszystkie niepuste wiersze pliku jako listy komórek, bez wyrównywania
    do nagłówka — surowiec dla presetów aplikacji, których pliki mają kilka
    sekcji z własnymi nagłówkami. Odporne na kodowanie (UTF-8 z BOM, CP1250,
    Latin-1), separator (';', ',', tabulator), końce linii i ZIP."""
    surowe = _tekst_pliku(sciezka)
    if not surowe.strip():
        raise ValueError("Plik jest pusty.")
    czytnik = csv.reader(io.StringIO(surowe), delimiter=_separator_pliku(surowe))
    wiersze = [[str(k).strip() for k in w] for w in czytnik if any((k or "").strip() for k in w)]
    if not wiersze:
        raise ValueError("Plik nie zawiera żadnych danych.")
    return wiersze


def tabela_z_wierszy(wiersze) -> tuple[list[str], list[list[str]]]:
    """(naglowki, wiersze): pierwszy wiersz to nagłówki, reszta wyrównana do
    ich liczby — ucięta albo dopełniona pustymi komórkami."""
    if not wiersze:
        return [], []
    naglowki = [str(k).strip() for k in wiersze[0]]
    szerokosc = len(naglowki)
    return naglowki, [list(w[:szerokosc]) + [""] * max(0, szerokosc - len(w)) for w in wiersze[1:]]


def wczytaj_plik_csv(sciezka) -> tuple[list[str], list[list[str]]]:
    """Czyta plik CSV/TSV (jak `wczytaj_wiersze_csv`) jako jedną tabelę.
    Zwraca (naglowki, wiersze) — wiersze to listy stringów wyrównane do
    długości nagłówka."""
    return tabela_z_wierszy(wczytaj_wiersze_csv(sciezka))


# Słowa w nagłówku kolumny licznika/dystansu, które mówią wprost o jednostce.
# „mileage” celowo nie — po angielsku to po prostu „przebieg”, także w km.
_SLOWA_MIL = {"mi", "mil", "mile", "miles"}
_SLOWA_KM = {"km", "kilometry", "kilometers", "kilometres"}


def rozpoznaj_jednostke_pliku(naglowki, mapowanie) -> str | None:
    """„mi” albo „km”, jeśli nagłówek kolumny licznika albo dystansu mówi to
    wprost („Przebieg (mi)”, „Odometer (km)”, „Distance miles”); None, gdy
    milczy — wtedy o jednostce pliku decyduje człowiek (domyślnie ta z Ustawień)."""
    for pole in ("przebieg", "dystans"):
        idx = (mapowanie or {}).get(pole)
        if idx is None or idx >= len(naglowki):
            continue
        slowa = set(re.findall(r"[^\W\d_]+", _normalizuj_naglowek(naglowki[idx])))
        if slowa & _SLOWA_MIL:
            return "mi"
        if slowa & _SLOWA_KM:
            return "km"
    return None


def dopasuj_kolumny_tankowan(naglowki):
    """Automatyczne zgadywanie, która kolumna pliku odpowiada któremu polu.
    Zwraca {pole: indeks_kolumny lub None} — użytkownik może to potem poprawić.
    Ten sam mechanizm, co przy pozostałych typach importu (_dopasuj_kolumny)."""
    return _dopasuj_kolumny(naglowki, POLA_IMPORTU_TANKOWAN, _ALIASY_IMPORTU)


def _numery(numery_wierszy, wiersze):
    """Numery wierszy do komunikatów o błędach: podane przez preset (pozycja
    w pliku z sekcjami) albo liczone od 2 — pierwszy wiersz to nagłówek."""
    return numery_wierszy if numery_wierszy is not None else range(2, len(wiersze) + 2)


def przygotuj_import_tankowan(auto_id, naglowki, wiersze, mapowanie, jednostka_pliku="km", numery_wierszy=None):
    """Waliduje wiersze wg mapowania i wykrywa duplikaty z bazą (data + przebieg +
    kwota, jak dedup sync); licznik i dystans z `jednostka_pliku` do km. Nic nie
    zapisuje. Zwraca {"gotowe": [...], "duplikaty": n, "bledy": [(nr, powod)]}."""
    gotowe, bledy = [], []
    duplikaty = 0

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT data, przebieg, kwota FROM tankowania WHERE auto_id=?", (auto_id,))
        istniejace = {(str(d or ""), int(p or 0), round(float(k or 0), 2)) for d, p, k in c.fetchall()}

    def wartosc(wiersz, pole):
        return _wartosc_z_wiersza(wiersz, mapowanie, pole)

    kolejnosc = _kolejnosc_dat(wiersze, mapowanie)
    dziesietny = _konwencja_liczb(wiersze, mapowanie, ("przebieg", "dystans", "litry", "kwota"))

    def liczba(wiersz, pole):
        return _liczba_csv(wartosc(wiersz, pole), dziesietny)

    for nr, wiersz in zip(_numery(numery_wierszy, wiersze), wiersze):
        data_txt = _parsuj_date_csv(wartosc(wiersz, "data"), kolejnosc)
        if not data_txt:
            bledy.append((nr, "nieczytelna albo pusta data"))
            continue

        litry = liczba(wiersz, "litry")
        kwota = liczba(wiersz, "kwota")
        if litry is None or litry <= 0:
            bledy.append((nr, "brak lub zerowa ilość paliwa/energii"))
            continue
        if kwota is None or kwota <= 0:
            bledy.append((nr, "brak lub zerowa kwota"))
            continue

        przebieg = liczba(wiersz, "przebieg")
        dystans = liczba(wiersz, "dystans")
        przebieg_i = dystans_na_km(przebieg, jednostka_pliku, calkowity=True) if przebieg and przebieg > 0 else 0
        dystans_f = dystans_na_km(dystans, jednostka_pliku) if dystans and dystans > 0 else 0.0
        if przebieg_i <= 0 and dystans_f <= 0:
            bledy.append((nr, "brak przebiegu i dystansu — nie da się umiejscowić wpisu"))
            continue

        klucz = (data_txt, przebieg_i, round(kwota, 2))
        if klucz in istniejace:
            duplikaty += 1
            continue
        istniejace.add(klucz)

        idx_pelna = mapowanie.get("do_pelna")
        do_pelna = 1 if (idx_pelna is None or _prawda_csv(wartosc(wiersz, "do_pelna"))) else 0

        gotowe.append({
            "data": data_txt,
            "przebieg": przebieg_i,
            "dystans": dystans_f,
            "litry": float(litry),
            "kwota": float(kwota),
            "do_pelna": do_pelna,
            "stacja": " ".join(str(wartosc(wiersz, "stacja") or "").split()),
            "rodzaj_energii": _rozpoznaj_rodzaj_csv(wartosc(wiersz, "rodzaj_energii"), auto_id),
            "notatka": przytnij_notatke(wartosc(wiersz, "notatka")),
        })

    gotowe.sort(key=lambda g: (parsuj_date(g["data"]), g["przebieg"]))
    return {"gotowe": gotowe, "duplikaty": duplikaty, "bledy": bledy}


def zaimportuj_tankowania(auto_id, gotowe):
    """Wstawia przygotowane wcześniej wiersze. Zwraca liczbę dodanych wpisów.
    Nie dotyka zdalne_id — nowe wpisy pójdą do chmury przy najbliższym syncu."""
    if not auto_id or not gotowe:
        return 0
    kto = pobierz_moje_imie()
    with polacz_baze() as conn:
        for g in gotowe:
            conn.execute(
                "INSERT INTO tankowania (auto_id, data, data_iso, przebieg, dystans, litry, kwota, do_pelna, stacja, "
                "rodzaj_energii, dodane_przez, notatka, notatka_autor, notatka_data) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (auto_id, g["data"], na_iso(g["data"]), g["przebieg"], g["dystans"], g["litry"],
                 g["kwota"], g["do_pelna"], g["stacja"] or None,
                 g.get("rodzaj_energii") or domyslny_rodzaj_energii(auto_id), kto, *_notatka_z_podpisem(g, kto))
            )
    return len(gotowe)


def _notatka_z_podpisem(g, kto):
    """(treść, autor, data) notatki importowanego wpisu. Podpis jak przy
    notatce dopisanej w aplikacji — imię z Ustawień i chwila zapisu; pusta
    notatka nie zostawia samego podpisu."""
    notatka = g.get("notatka") or None
    if not notatka:
        return None, None, None
    return notatka, kto, datetime.now().strftime("%d.%m.%Y %H:%M")


# ==================== IMPORT CSV — POZOSTAŁE TYPY ====================
# Ten sam mechanizm, co dla tankowań (wczytanie pliku, dopasowanie kolumn,
# walidacja, deduplikacja), tylko sparametryzowany typem wpisu. Dzięki temu
# dołożenie kolejnego typu to jeden wpis w TYPY_IMPORTU, a nie kopia widoku.

POLA_IMPORTU_INNYCH_KOSZTOW = {
    "data": ("Data", True),
    "nazwa": ("Opis / nazwa", True),
    "kwota": ("Kwota", True),
    # Kategoria z pliku trafia do kategorii aplikacji, jeśli ją rozpoznamy
    # (kategoria_z_nazwy), a jeśli nie — zostaje przy wpisie jako tag.
    "kategoria": ("Kategoria", False),
    "tagi": ("Tagi", False),
    "notatka": ("Notatka", False),
}


POLA_IMPORTU_WIZYT = {
    "data": ("Data", True),
    "przebieg": ("Licznik (km)", False),
    "kwota": ("Koszt", True),
    "opis": ("Zakres prac", False),
    "warsztat": ("Warsztat", False),
    "notatka": ("Notatka", False),
}


POLA_IMPORTU_ODCZYTOW = {
    "data": ("Data", True),
    "przebieg": ("Stan licznika (km)", True),
}


_ALIASY_IMPORTU_INNYCH = {
    "data": ["data", "date", "dzien", "dzień", "datum", "data wydatku"],
    "nazwa": ["nazwa", "opis", "description", "tytul", "tytuł", "name", "usluga", "usługa", "pozycja", "co"],
    "kwota": ["kwota", "koszt", "cena", "cost", "total", "price", "wartosc", "wartość", "suma"],
    "kategoria": ["kategoria", "category", "typ", "rodzaj", "typ wydatku", "rodzaj wydatku", "expense type"],
    "tagi": ["tagi", "tag", "tags", "etykiety", "grupa"],
    "notatka": _ALIASY_NOTATKI,
}


_ALIASY_IMPORTU_WIZYT = {
    "data": ["data", "date", "dzien", "dzień", "datum", "data wizyty", "data serwisu"],
    "przebieg": ["przebieg", "licznik", "odometer", "odo", "mileage", "km", "stan licznika", "przebieg (km)",
                 "przebieg (mi)"],
    "kwota": ["kwota", "koszt", "koszt całkowity", "koszt calkowity", "cena", "cost", "total", "total cost",
              "price", "wartosc", "wartość", "suma"],
    "opis": ["zakres prac", "opis", "czynnosci", "czynności", "uslugi", "usługi", "naprawa", "services",
             "description", "tytul", "tytuł"],
    "warsztat": ["warsztat", "wykonawca", "mechanik", "workshop", "service center"],
    "notatka": _ALIASY_NOTATKI,
}


_ALIASY_IMPORTU_ODCZYTOW = {
    "data": ["data", "date", "dzien", "dzień", "datum", "data odczytu"],
    "przebieg": ["przebieg", "licznik", "odometer", "odo", "mileage", "km", "stan licznika", "przebieg (km)",
                 "przebieg (mi)"],
}


def _dopasuj_kolumny(naglowki, pola, aliasy):
    """Automatyczne zgadywanie, która kolumna pliku odpowiada któremu polu.
    Najpierw szukamy trafień DOKŁADNYCH, dopiero potem częściowych — inaczej
    „data odczytu” potrafiła zająć kolumnę przeznaczoną na „data”."""
    znormalizowane = [_normalizuj_naglowek(h) for h in naglowki]
    mapowanie = {pole: None for pole in pola}
    zajete = set()

    for pole in pola:
        lista_aliasow = aliasy.get(pole, [])
        for dokladne in (True, False):
            for i, h in enumerate(znormalizowane):
                if i in zajete or not h:
                    continue
                trafienie = (h in lista_aliasow) if dokladne else any(a in h for a in lista_aliasow)
                if trafienie:
                    mapowanie[pole] = i
                    zajete.add(i)
                    break
            if mapowanie[pole] is not None:
                break
    return mapowanie


def _wartosc_z_wiersza(wiersz, mapowanie, pole):
    idx = mapowanie.get(pole)
    if idx is None or idx >= len(wiersz):
        return ""
    return wiersz[idx]


def dopasuj_kolumny_innych_kosztow(naglowki):
    return _dopasuj_kolumny(naglowki, POLA_IMPORTU_INNYCH_KOSZTOW, _ALIASY_IMPORTU_INNYCH)


def dopasuj_kolumny_odczytow(naglowki):
    return _dopasuj_kolumny(naglowki, POLA_IMPORTU_ODCZYTOW, _ALIASY_IMPORTU_ODCZYTOW)


def dopasuj_kolumny_wizyt(naglowki):
    return _dopasuj_kolumny(naglowki, POLA_IMPORTU_WIZYT, _ALIASY_IMPORTU_WIZYT)


def przygotuj_import_innych_kosztow(auto_id, naglowki, wiersze, mapowanie, jednostka_pliku="km",
                                   numery_wierszy=None):
    """Waliduje wiersze i odsiewa duplikaty względem tego, co już jest w bazie
    (ta sama data + nazwa + kwota). Kategorię aplikacji rozpoznaje z kolumny
    kategorii albo tagów (`kategoria_z_nazwy`); kategoria z pliku, której
    aplikacja nie zna, zostaje przy wpisie jako tag. Nic nie zapisuje."""
    gotowe, bledy = [], []
    duplikaty = 0

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT data, nazwa, kwota FROM inne_koszty WHERE auto_id=?", (auto_id,))
        istniejace = {
            (str(d or ""), klucz_nazwy(n), round(float(k or 0), 2))
            for d, n, k in c.fetchall()
        }

    kolejnosc = _kolejnosc_dat(wiersze, mapowanie)
    dziesietny = _konwencja_liczb(wiersze, mapowanie, ("kwota",))

    for nr, wiersz in zip(_numery(numery_wierszy, wiersze), wiersze):
        data_txt = _parsuj_date_csv(_wartosc_z_wiersza(wiersz, mapowanie, "data"), kolejnosc)
        if not data_txt:
            bledy.append((nr, "nieczytelna albo pusta data"))
            continue

        nazwa = normalizuj_nazwe(_wartosc_z_wiersza(wiersz, mapowanie, "nazwa"))
        if not nazwa:
            bledy.append((nr, "brak opisu / nazwy wydatku"))
            continue

        kwota = _liczba_csv(_wartosc_z_wiersza(wiersz, mapowanie, "kwota"), dziesietny)
        if kwota is None or kwota <= 0:
            bledy.append((nr, "brak lub zerowa kwota"))
            continue

        klucz = (data_txt, klucz_nazwy(nazwa), round(kwota, 2))
        if klucz in istniejace:
            duplikaty += 1
            continue
        istniejace.add(klucz)

        tagi = normalizuj_nazwe(_wartosc_z_wiersza(wiersz, mapowanie, "tagi"))
        z_pliku = normalizuj_nazwe(_wartosc_z_wiersza(wiersz, mapowanie, "kategoria"))
        rozpoznana = kategoria_z_nazwy(z_pliku)
        if z_pliku and not rozpoznana and not _nazwa_ogolna(z_pliku):
            tagi = _dolacz_tag(tagi, z_pliku)

        gotowe.append({
            "data": data_txt,
            "nazwa": nazwa,
            "kwota": float(kwota),
            "kategoria": rozpoznana or kategoria_z_nazwy(tagi) or KATEGORIA_INNE_DOMYSLNA,
            "tagi": tagi,
            "notatka": przytnij_notatke(_wartosc_z_wiersza(wiersz, mapowanie, "notatka")),
        })

    gotowe.sort(key=lambda g: (parsuj_date(g["data"]), g["nazwa"]))
    return {"gotowe": gotowe, "duplikaty": duplikaty, "bledy": bledy}


def zaimportuj_inne_koszty(auto_id, gotowe):
    if not auto_id or not gotowe:
        return 0
    kto = pobierz_moje_imie()
    with polacz_baze() as conn:
        for g in gotowe:
            conn.execute(
                "INSERT INTO inne_koszty (auto_id, data, data_iso, kategoria, nazwa, kwota, tagi, dodane_przez, "
                "notatka, notatka_autor, notatka_data) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                # Kategoria rozpoznana z pliku (przygotuj_import_innych_kosztow);
                # bez żadnej wskazówki — „Ogólne”, jak w formularzu.
                (auto_id, g["data"], na_iso(g["data"]), g.get("kategoria") or KATEGORIA_INNE_DOMYSLNA, g["nazwa"],
                 g["kwota"], g["tagi"] or None, kto, *_notatka_z_podpisem(g, kto))
            )
    return len(gotowe)


def przygotuj_import_odczytow(auto_id, naglowki, wiersze, mapowanie, jednostka_pliku="km", numery_wierszy=None):
    """Odczyty licznika: duplikatem jest ta sama data + ten sam przebieg.
    Dodatkowo odsiewamy wiersze z przebiegiem <= 0, bo taki odczyt nic nie wnosi,
    a psuje wyliczenia średniego dziennego przebiegu. Licznik z pliku
    w `jednostka_pliku` trafia do bazy w km."""
    gotowe, bledy = [], []
    duplikaty = 0

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT data, przebieg FROM odczyty_przebiegu WHERE auto_id=?", (auto_id,))
        istniejace = {(str(d or ""), int(p or 0)) for d, p in c.fetchall()}

    kolejnosc = _kolejnosc_dat(wiersze, mapowanie)
    dziesietny = _konwencja_liczb(wiersze, mapowanie, ("przebieg",))

    for nr, wiersz in zip(_numery(numery_wierszy, wiersze), wiersze):
        data_txt = _parsuj_date_csv(_wartosc_z_wiersza(wiersz, mapowanie, "data"), kolejnosc)
        if not data_txt:
            bledy.append((nr, "nieczytelna albo pusta data"))
            continue

        przebieg = _liczba_csv(_wartosc_z_wiersza(wiersz, mapowanie, "przebieg"), dziesietny)
        if przebieg is None or przebieg <= 0:
            bledy.append((nr, "brak lub zerowy stan licznika"))
            continue

        przebieg_km = dystans_na_km(przebieg, jednostka_pliku, calkowity=True)
        klucz = (data_txt, przebieg_km)
        if klucz in istniejace:
            duplikaty += 1
            continue
        istniejace.add(klucz)

        gotowe.append({"data": data_txt, "przebieg": przebieg_km})

    gotowe.sort(key=lambda g: (parsuj_date(g["data"]), g["przebieg"]))
    return {"gotowe": gotowe, "duplikaty": duplikaty, "bledy": bledy}


def zaimportuj_odczyty(auto_id, gotowe):
    if not auto_id or not gotowe:
        return 0
    with polacz_baze() as conn:
        for g in gotowe:
            conn.execute(
                "INSERT INTO odczyty_przebiegu (auto_id, data, data_iso, przebieg, zrodlo) VALUES (?,?,?,?,?)",
                (auto_id, g["data"], na_iso(g["data"]), g["przebieg"], "import")
            )
    return len(gotowe)


def przygotuj_import_wizyt(auto_id, naglowki, wiersze, mapowanie, jednostka_pliku="km", numery_wierszy=None):
    """Wizyty z pliku bez pozycji z listy zadań: zakres prac do notatek, koszt w całości
    do „serwis”; duplikat = data + przebieg + koszt. Brak licznika → 0 („nie wiadomo”,
    pomijane przez historię licznika). Zerowy koszt przechodzi tylko z opisem prac. Nic
    nie zapisuje."""
    gotowe, bledy = [], []
    duplikaty = 0

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT data, przebieg, koszt_calkowity FROM wizyty WHERE auto_id=?", (auto_id,))
        istniejace = {(str(d or ""), int(p or 0), round(float(k or 0), 2)) for d, p, k in c.fetchall()}

    kolejnosc = _kolejnosc_dat(wiersze, mapowanie)
    dziesietny = _konwencja_liczb(wiersze, mapowanie, ("przebieg", "kwota"))

    for nr, wiersz in zip(_numery(numery_wierszy, wiersze), wiersze):
        data_txt = _parsuj_date_csv(_wartosc_z_wiersza(wiersz, mapowanie, "data"), kolejnosc)
        if not data_txt:
            bledy.append((nr, "nieczytelna albo pusta data"))
            continue

        opis = normalizuj_nazwe(_wartosc_z_wiersza(wiersz, mapowanie, "opis"))
        kwota = _liczba_csv(_wartosc_z_wiersza(wiersz, mapowanie, "kwota"), dziesietny)
        if kwota is None or kwota < 0:
            bledy.append((nr, "brak kosztu wizyty"))
            continue
        if kwota == 0 and not opis:
            bledy.append((nr, "zerowy koszt i brak opisu prac"))
            continue

        przebieg = _liczba_csv(_wartosc_z_wiersza(wiersz, mapowanie, "przebieg"), dziesietny)
        przebieg_km = dystans_na_km(przebieg, jednostka_pliku, calkowity=True) if przebieg and przebieg > 0 else 0

        klucz = (data_txt, przebieg_km, round(kwota, 2))
        if klucz in istniejace:
            duplikaty += 1
            continue
        istniejace.add(klucz)

        gotowe.append({
            "data": data_txt,
            "przebieg": przebieg_km,
            "kwota": float(kwota),
            "opis": opis,
            "warsztat": normalizuj_nazwe(_wartosc_z_wiersza(wiersz, mapowanie, "warsztat")),
            "notatka": str(_wartosc_z_wiersza(wiersz, mapowanie, "notatka") or "").strip(),
        })

    gotowe.sort(key=lambda g: (parsuj_date(g["data"]), g["przebieg"]))
    return {"gotowe": gotowe, "duplikaty": duplikaty, "bledy": bledy}


def zaimportuj_wizyty(auto_id, gotowe):
    """Wstawia wizyty bez pozycji. Warsztat bez nazwy zapisujemy tak jak
    formularz („Warsztat”, WARSZTAT_BEZ_NAZWY), żeby karta warsztatów i filtr
    po wykonawcy widziały jedną wspólną pozycję zamiast pustych."""
    if not auto_id or not gotowe:
        return 0
    kto = pobierz_moje_imie()
    with polacz_baze() as conn:
        for g in gotowe:
            notatki = "\n".join(t for t in (g.get("opis"), g.get("notatka")) if t) or None
            conn.execute(
                "INSERT INTO wizyty (auto_id, data, data_iso, przebieg, wykonawca, koszt_calkowity, notatki, "
                "dodane_przez) VALUES (?,?,?,?,?,?,?,?)",
                (auto_id, g["data"], na_iso(g["data"]), g["przebieg"], g.get("warsztat") or WARSZTAT_BEZ_NAZWY,
                 g["kwota"], notatki, kto)
            )
    return len(gotowe)


# ==================== IMPORT CSV — PRZEJAZDY (EWIDENCJA PRZEBIEGU) ====================
# Ewidencja prowadzona dotąd w arkuszu: data, skąd, dokąd (albo jedna kolumna
# „opis trasy”), cel, kilometry, rodzaj i kierowca. Kilometry z pliku to CAŁY
# przejazd — tak liczy go ewidencja w aplikacji.

# Kolejność ma znaczenie przy zgadywaniu kolumn: „Opis trasy (skąd – dokąd)”
# musi zająć swoją kolumnę, zanim „Skąd” dopasuje się do niej częściowo.
POLA_IMPORTU_PRZEJAZDOW = {
    "data": ("Data", True),
    "km": ("Dystans (km)", True),
    # Jedna kolumna „Warszawa – Łódź” zamiast dwóch; „A – B – A” to powrót.
    "trasa": ("Opis trasy (skąd – dokąd)", False),
    "skad": ("Skąd", False),
    "dokad": ("Dokąd", False),
    "cel": ("Cel wyjazdu", False),
    "rodzaj": ("Rodzaj (służbowy / prywatny)", False),
    "kierowca": ("Kierowca", False),
    "licznik": ("Licznik po przejeździe (km)", False),
    "notatka": ("Notatka", False),
}

_ALIASY_IMPORTU_PRZEJAZDOW = {
    "data": ["data", "date", "dzien", "dzień", "datum", "data wyjazdu", "data przejazdu"],
    "km": ["km", "kilometry", "liczba km", "dystans", "distance", "przejechane km", "liczba kilometrow",
           "liczba kilometrów", "liczba przejechanych km", "dystans (km)", "dystans (mi)", "mileage", "trip"],
    "skad": ["skad", "skąd", "miejsce wyjazdu", "wyjazd z", "from", "origin", "start"],
    "dokad": ["dokad", "dokąd", "miejsce docelowe", "destination"],
    "trasa": ["trasa", "opis trasy", "opis trasy (skad - dokad)", "opis trasy (skąd - dokąd)", "route"],
    "cel": ["cel", "cel wyjazdu", "cel podrozy", "cel podróży", "purpose", "powod", "powód", "opis"],
    "rodzaj": ["rodzaj", "rodzaj przejazdu", "typ", "type", "sluzbowy/prywatny", "służbowy/prywatny",
               "business/private", "kategoria"],
    "kierowca": ["kierowca", "driver", "kierujacy", "kierujący", "imie i nazwisko", "imię i nazwisko", "osoba"],
    "licznik": ["licznik", "stan licznika", "licznik po", "stan licznika po", "odometer", "przebieg"],
    "notatka": _ALIASY_NOTATKI,
}

_ROZDZIEL_TRASE = re.compile(r"\s*(?:->|→|—|–|>)\s*|\s+-\s+")


def dopasuj_kolumny_przejazdow(naglowki):
    return _dopasuj_kolumny(naglowki, POLA_IMPORTU_PRZEJAZDOW, _ALIASY_IMPORTU_PRZEJAZDOW)


def _trasa_csv(tekst):
    """„Warszawa – Łódź” → (Warszawa, Łódź, False); „A – B – A” → (A, B, True)."""
    czesci = [normalizuj_nazwe(c) for c in _ROZDZIEL_TRASE.split(str(tekst or "")) if normalizuj_nazwe(c)]
    if not czesci:
        return "", "", False
    if len(czesci) == 1:
        return "", czesci[0], False
    powrot = len(czesci) >= 3 and klucz_nazwy(czesci[0]) == klucz_nazwy(czesci[-1])
    return czesci[0], czesci[-2] if powrot else czesci[-1], powrot


def _rodzaj_przejazdu_csv(tekst):
    """True — służbowy, False — prywatny, None — nie wiadomo (wtedy służbowy:
    arkusz ewidencji prowadzi się zwykle dla jazd służbowych)."""
    t = _bez_ogonkow(_normalizuj_naglowek(tekst))
    if not t:
        return None
    if any(s in t for s in ("pryw", "private", "personal", "osobist")) or t in ("p", "nie", "no", "0"):
        return False
    if any(s in t for s in ("sluzb", "business", "firm", "work", "delegac")) or t in ("s", "tak", "yes", "1"):
        return True
    return None


def przygotuj_import_przejazdow(auto_id, naglowki, wiersze, mapowanie, jednostka_pliku="km", numery_wierszy=None):
    """Przejazdy z arkusza. Duplikatem jest ten sam dzień, ta sama trasa
    (bez wielkości liter i spacji) i te same kilometry. Kilometry i licznik
    w `jednostka_pliku` trafiają do bazy w km."""
    gotowe, bledy = [], []
    duplikaty = 0

    with polacz_baze() as conn:
        istniejace = {
            (str(d or ""), klucz_nazwy(s), klucz_nazwy(k), round(float(km or 0), 1))
            for d, s, k, km in conn.execute(
                "SELECT data, skad, dokad, km FROM przejazdy WHERE auto_id=?", (auto_id,)).fetchall()
        }

    kolejnosc = _kolejnosc_dat(wiersze, mapowanie)
    dziesietny = _konwencja_liczb(wiersze, mapowanie, ("km", "licznik"))

    for nr, wiersz in zip(_numery(numery_wierszy, wiersze), wiersze):
        data_txt = _parsuj_date_csv(_wartosc_z_wiersza(wiersz, mapowanie, "data"), kolejnosc)
        if not data_txt:
            bledy.append((nr, "nieczytelna albo pusta data"))
            continue

        km = _liczba_csv(_wartosc_z_wiersza(wiersz, mapowanie, "km"), dziesietny)
        if km is None or km <= 0:
            bledy.append((nr, "brak lub zerowy dystans"))
            continue
        km = round(dystans_na_km(km, jednostka_pliku), 2)

        skad = normalizuj_nazwe(_wartosc_z_wiersza(wiersz, mapowanie, "skad"))
        dokad = normalizuj_nazwe(_wartosc_z_wiersza(wiersz, mapowanie, "dokad"))
        powrot = False
        if not skad and not dokad:
            skad, dokad, powrot = _trasa_csv(_wartosc_z_wiersza(wiersz, mapowanie, "trasa"))
        cel = normalizuj_nazwe(_wartosc_z_wiersza(wiersz, mapowanie, "cel"))
        if not (skad or dokad or cel):
            bledy.append((nr, "brak trasy i celu przejazdu"))
            continue

        licznik = _liczba_csv(_wartosc_z_wiersza(wiersz, mapowanie, "licznik"), dziesietny)
        licznik_km = dystans_na_km(licznik, jednostka_pliku, calkowity=True) if licznik and licznik > 0 else None

        klucz = (data_txt, klucz_nazwy(skad), klucz_nazwy(dokad), round(km, 1))
        if klucz in istniejace:
            duplikaty += 1
            continue
        istniejace.add(klucz)

        sluzbowy = _rodzaj_przejazdu_csv(_wartosc_z_wiersza(wiersz, mapowanie, "rodzaj"))
        gotowe.append({
            "data": data_txt, "skad": skad, "dokad": dokad, "powrot": powrot, "cel": cel, "km": km,
            "sluzbowy": True if sluzbowy is None else sluzbowy,
            "kierowca": normalizuj_nazwe(_wartosc_z_wiersza(wiersz, mapowanie, "kierowca")),
            "licznik": licznik_km,
            "notatka": przytnij_notatke(_wartosc_z_wiersza(wiersz, mapowanie, "notatka")) or "",
        })

    gotowe.sort(key=lambda g: parsuj_date(g["data"]))
    return {"gotowe": gotowe, "duplikaty": duplikaty, "bledy": bledy}


def zaimportuj_przejazdy(auto_id, gotowe):
    if not auto_id or not gotowe:
        return 0
    kto = pobierz_moje_imie()
    with polacz_baze() as conn:
        for g in gotowe:
            notatka, autor, data_notatki = _notatka_z_podpisem(g, kto)
            conn.execute(
                "INSERT INTO przejazdy (auto_id, data, data_iso, skad, dokad, cel, km, powrot, sluzbowy, kierowca, "
                "licznik, notatka, notatka_autor, notatka_data, dodane_przez) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (auto_id, g["data"], na_iso(g["data"]), g["skad"] or None, g["dokad"] or None, g["cel"] or None,
                 g["km"], 1 if g["powrot"] else 0, 1 if g["sluzbowy"] else 0, g["kierowca"] or None,
                 g["licznik"], notatka, autor, data_notatki, kto)
            )
    return len(gotowe)


# ==================== KATEGORIE Z NAZW ====================
# Słowniki kosztów innych aplikacji (Fuelio, Drivvo, aCar) → kategorie „Innych kosztów”
# po słowach-kluczach w kilku językach.

_KATEGORIA_URZEDOWA = "Opłaty urzędowe"


def _bez_ogonkow(tekst):
    """„Opłaty” → „oplaty”: słowa-klucze porównujemy bez znaków diakrytycznych,
    bo pliki z innych aplikacji bywają różne („ł” nie rozkłada się w NFKD)."""
    rozlozone = unicodedata.normalize("NFKD", str(tekst or "").lower().replace("ł", "l"))
    return "".join(znak for znak in rozlozone if not unicodedata.combining(znak))


def _wzorzec_slow(*slowa):
    """Rdzenie dopasowywane od początku słowa („park” łapie „parking”, ale nie
    „spark plug”); rdzeń zakończony „=” musi być całym słowem („mot=” to
    brytyjski przegląd, nie „motor”)."""
    czesci = []
    for slowo in slowa:
        cale = slowo.endswith("=")
        czesci.append(r"(?<![a-z0-9])" + re.escape(slowo.rstrip("=")) + (r"(?![a-z0-9])" if cale else ""))
    return re.compile("|".join(czesci))


# Kolejność ma znaczenie: „parking fine” to mandat, a nie parking.
_WZORCE_KATEGORII = [
    (KATEGORIA_INNE_DROGOWE, _wzorzec_slow(
        "toll", "autostrad", "winiet", "vignet", "vinet", "pedag", "peaje", "maut", "oplata drog",
        "oplaty drog", "e-toll", "etoll", "viatoll", "przejazd", "ticket", "fine", "mandat", "multa",
        "strafzettel", "bussgeld", "fotoradar")),
    ("Ubezpieczenie", _wzorzec_slow("insur", "ubezpiecz", "seguro", "versicher", "assur", "polis", "oc=", "ac=")),
    ("Myjnia i kosmetyka", _wzorzec_slow(
        "wash", "myjni", "mycie", "lavag", "lavad", "wasch", "kosmet", "detailing", "wosk", "wax", "clean",
        "odkurz", "czyszcz", "polerow")),
    ("Parking i garaż", _wzorzec_slow("park", "garaz", "garage", "estacionam", "aparcam", "postoj")),
    ("Wyposażenie i akcesoria", _wzorzec_slow(
        "accessor", "akcesor", "wyposaz", "tuning", "acessor", "zubehor", "equipment", "gadzet", "dywanik")),
    (_KATEGORIA_URZEDOWA, _wzorzec_slow(
        "registr", "rejestr", "tax=", "taxes=", "podat", "urzad", "urzed", "licenc", "licens", "ipva=",
        "dpvat=", "impuest", "steuer", "przeglad techn", "badanie techn", "inspection", "vistoria", "itv=",
        "tuv=", "mot=", "homolog")),
]

_WZORZEC_SERWISU = _wzorzec_slow(
    "serwis", "servi", "maint", "konserw", "napraw", "repair", "repar", "manuten", "mantenim", "wartung",
    "werkstat", "warsztat", "mechani", "przeglad", "olej", "oil", "opon", "tire", "tyre", "hamul", "brake",
    "rozrzad", "filtr", "filter", "wymian")

# Nazwy, które niczego nie mówią — nie zostają przy wpisie jako tag.
_NAZWY_OGOLNE = {"inne", "ogolne", "other", "others", "misc", "miscellaneous", "general", "outros", "otros",
                 "sonstiges", "expense", "expenses", "wydatek", "wydatki", "koszt", "koszty", "gasto", "gastos",
                 "despesa", "despesas"}


def kategoria_z_nazwy(tekst) -> str | None:
    """Kategoria „Innych kosztów” rozpoznana z nazwy z pliku: najpierw
    dokładna nazwa kategorii tej aplikacji, potem słowa-klucze po polsku,
    angielsku, portugalsku, hiszpańsku i niemiecku. None, gdy nic nie pasuje
    — wtedy decyduje wołający (zwykle „Ogólne”)."""
    klucz = klucz_nazwy(tekst)
    if not klucz:
        return None
    for kategoria in KATEGORIE_INNYCH_KOSZTOW:
        if klucz_nazwy(kategoria) == klucz:
            return kategoria
    plaski = _bez_ogonkow(klucz)
    for kategoria, wzorzec in _WZORCE_KATEGORII:
        if wzorzec.search(plaski):
            return kategoria
    return None


def czy_nazwa_serwisowa(tekst) -> bool:
    """Czy koszt o tej nazwie (kategoria w Fuelio, typ w innej aplikacji) to
    wizyta serwisowa. Przegląd techniczny i podobne — nie: to opłata
    urzędowa, a nie praca przy aucie."""
    plaski = _bez_ogonkow(klucz_nazwy(tekst))
    if not plaski or kategoria_z_nazwy(tekst) == _KATEGORIA_URZEDOWA:
        return False
    return bool(_WZORZEC_SERWISU.search(plaski))


def _nazwa_ogolna(tekst):
    return _bez_ogonkow(klucz_nazwy(tekst)) in _NAZWY_OGOLNE


def _dolacz_tag(tagi, nowy):
    """Lista tagów wpisu (tekst „A,B”) z dopisanym `nowy`, o ile go jeszcze
    nie ma — porównanie po `klucz_nazwy`, jak w całym słowniku tagów."""
    elementy = [t.strip() for t in str(tagi or "").split(",") if t.strip()]
    if nowy and all(klucz_nazwy(t) != klucz_nazwy(nowy) for t in elementy):
        elementy.append(nowy)
    return ",".join(elementy)


# Rejestr typów importu: opisuje wszystko, czego potrzebuje widok /import.
# `podglad` buduje jednolinijkowy opis gotowego wpisu do sekcji podglądu.
TYPY_IMPORTU = {
    "tankowania": {
        "etykieta": "Tankowania",
        "opis": "Data, licznik, litry/kWh i kwota — historia z innej aplikacji tankowań.",
        "pola": POLA_IMPORTU_TANKOWAN,
        "dopasuj": dopasuj_kolumny_tankowan,
        "przygotuj": przygotuj_import_tankowan,
        "zapisz": zaimportuj_tankowania,
        "z_dystansem": True,
        "podglad": lambda g, jednostka: (
            f"{g['data']} • {tekst_dystansu(g['przebieg'])} • {formatuj_liczba_eksport(g['litry'])} "
            f"{'kWh' if g.get('rodzaj_energii') == ENERGIA_PRAD else jednostka} • {formatuj_liczba_eksport(g['kwota'])}"
            + (f" • {g['stacja']}" if g.get("stacja") else "")
            + (f" • {ETYKIETY_RODZAJU.get(g.get('rodzaj_energii'), '')}" if g.get("rodzaj_energii") else "")
        ),
    },
    "inne_koszty": {
        "etykieta": "Inne koszty",
        "opis": "Ubezpieczenie, myjnia, autostrady, raty — data, opis i kwota.",
        "pola": POLA_IMPORTU_INNYCH_KOSZTOW,
        "dopasuj": dopasuj_kolumny_innych_kosztow,
        "przygotuj": przygotuj_import_innych_kosztow,
        "zapisz": zaimportuj_inne_koszty,
        "podglad": lambda g, jednostka: (
            f"{g['data']} • {g['nazwa']} • {formatuj_liczba_eksport(g['kwota'])}"
            + (f" • {g['kategoria']}" if g.get("kategoria") not in (None, "", KATEGORIA_INNE_DOMYSLNA) else "")
            + (f" • {g['tagi']}" if g.get("tagi") else "")
        ),
    },
    "wizyty": {
        "etykieta": "Wizyty serwisowe",
        "opis": "Serwis i naprawy — data, licznik, koszt i zakres prac. Trafiają do historii wizyt.",
        "pola": POLA_IMPORTU_WIZYT,
        "dopasuj": dopasuj_kolumny_wizyt,
        "przygotuj": przygotuj_import_wizyt,
        "zapisz": zaimportuj_wizyty,
        "z_dystansem": True,
        "podglad": lambda g, jednostka: " • ".join(
            [g["data"]]
            + ([tekst_dystansu(g["przebieg"])] if g.get("przebieg") else [])
            + ([g["opis"]] if g.get("opis") else [])
            + [formatuj_liczba_eksport(g["kwota"])]
            + ([g["warsztat"]] if g.get("warsztat") else [])
        ),
    },
    "odczyty": {
        "etykieta": "Odczyty licznika",
        "opis": "Sam stan licznika w czasie — przydatne, gdy tankowania prowadzisz gdzie indziej.",
        "pola": POLA_IMPORTU_ODCZYTOW,
        "dopasuj": dopasuj_kolumny_odczytow,
        "przygotuj": przygotuj_import_odczytow,
        "zapisz": zaimportuj_odczyty,
        "z_dystansem": True,
        "podglad": lambda g, jednostka: f"{g['data']} • {tekst_dystansu(g['przebieg'])}",
    },
    "przejazdy": {
        "etykieta": "Przejazdy (ewidencja przebiegu)",
        "opis": "Ewidencja z arkusza — data, skąd, dokąd albo opis trasy, cel, kilometry, rodzaj i kierowca.",
        "pola": POLA_IMPORTU_PRZEJAZDOW,
        "dopasuj": dopasuj_kolumny_przejazdow,
        "przygotuj": przygotuj_import_przejazdow,
        "zapisz": zaimportuj_przejazdy,
        "z_dystansem": True,
        "podglad": lambda g, jednostka: " • ".join(
            [g["data"]]
            + ([opis_trasy(g["skad"], g["dokad"], g["powrot"])] if g["skad"] or g["dokad"] else [])
            + ([g["cel"]] if g.get("cel") else [])
            + [tekst_km_przejazdu(g["km"]), "służbowy" if g["sluzbowy"] else "prywatny"]
            + ([g["kierowca"]] if g.get("kierowca") else [])
        ),
    },
}


__all__ = [
    "POLA_IMPORTU_INNYCH_KOSZTOW",
    "POLA_IMPORTU_ODCZYTOW",
    "POLA_IMPORTU_PRZEJAZDOW",
    "POLA_IMPORTU_TANKOWAN",
    "POLA_IMPORTU_WIZYT",
    "TYPY_IMPORTU",
    "_ALIASY_IMPORTU",
    "_ALIASY_IMPORTU_INNYCH",
    "_ALIASY_IMPORTU_ODCZYTOW",
    "_ALIASY_IMPORTU_PRZEJAZDOW",
    "_ALIASY_IMPORTU_WIZYT",
    "_ALIASY_NOTATKI",
    "_bez_ogonkow",
    "_dolacz_tag",
    "_dopasuj_kolumny",
    "_liczba_csv",
    "_normalizuj_naglowek",
    "_parsuj_date_csv",
    "_prawda_csv",
    "_rozpoznaj_rodzaj_csv",
    "_wartosc_z_wiersza",
    "czy_nazwa_serwisowa",
    "dopasuj_kolumny_innych_kosztow",
    "dopasuj_kolumny_odczytow",
    "dopasuj_kolumny_przejazdow",
    "dopasuj_kolumny_tankowan",
    "dopasuj_kolumny_wizyt",
    "kategoria_z_nazwy",
    "przygotuj_import_innych_kosztow",
    "przygotuj_import_odczytow",
    "przygotuj_import_przejazdow",
    "przygotuj_import_tankowan",
    "przygotuj_import_wizyt",
    "rozpoznaj_jednostke_pliku",
    "rozpoznaj_kolejnosc_dat",
    "rozpoznaj_separator_dziesietny",
    "tabela_z_wierszy",
    "wczytaj_plik_csv",
    "wczytaj_wiersze_csv",
    "zaimportuj_inne_koszty",
    "zaimportuj_odczyty",
    "zaimportuj_przejazdy",
    "zaimportuj_tankowania",
    "zaimportuj_wizyty",
]
