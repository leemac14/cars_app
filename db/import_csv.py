"""Import danych z plików CSV."""

import csv
import io
from date import parsuj_date
from datetime import datetime

from .stale import ENERGIA_PALIWO, ENERGIA_PRAD
from .polaczenie import polacz_baze
from .pomocnicze import _parsuj_liczbe_csv
from .ustawienia import pobierz_moje_imie
from .energia import ETYKIETY_RODZAJU, domyslny_rodzaj_energii
from .nazwy import klucz_nazwy, normalizuj_nazwe


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
}


_ALIASY_IMPORTU = {
    "data": ["data", "date", "data tankowania", "dzien", "dzień", "datum"],
    "przebieg": ["przebieg", "licznik", "odometer", "odo", "mileage", "km", "stan licznika", "przebieg (km)"],
    "dystans": ["dystans", "distance", "trip", "przejechano", "dystans (km)"],
    "litry": ["litry", "liters", "litres", "ilosc", "ilość", "volume", "quantity", "kwh", "energia", "paliwo"],
    "kwota": ["kwota", "koszt", "cena", "cost", "total", "total cost", "price", "wartosc", "wartość"],
    "stacja": ["stacja", "station", "punkt ladowania", "punkt ładowania", "miejsce", "fuel station", "sprzedawca"],
    "do_pelna": ["do pelna", "do pełna", "full", "pelny bak", "pełny bak", "full tank", "tankowanie do pelna"],
    "rodzaj_energii": ["rodzaj", "zrodlo", "źródło", "energia", "typ", "paliwo/prad", "fuel type"],
}


def _normalizuj_naglowek(tekst):
    return " ".join(str(tekst or "").strip().lower().replace("_", " ").split())


def _parsuj_date_csv(tekst):
    """Zwraca datę w formacie aplikacji ('DD.MM.YYYY') albo None. Formaty
    dwuznaczne (dd/mm vs mm/dd) rozstrzygamy po europejsku — dd/mm/yyyy."""
    s = str(tekst or "").strip()
    if not s:
        return None
    s = s.split("T")[0].strip()
    if " " in s and len(s.split(" ")[0]) >= 6:
        s = s.split(" ")[0]
    for wzorzec in ("%d.%m.%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d.%m.%y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, wzorzec).strftime("%d.%m.%Y")
        except ValueError:
            continue
    return None


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
    return _normalizuj_naglowek(tekst) in ("1", "tak", "yes", "true", "y", "t", "prawda", "x")


def wczytaj_plik_csv(sciezka):
    """Czyta plik CSV/TSV odporny na kodowanie (UTF-8 z BOM, CP1250, Latin-1)
    i separator (';', ',', tabulator). Zwraca (naglowki, wiersze) — wiersze to
    listy stringów wyrównane do długości nagłówka."""
    surowe = None
    for kodowanie in ("utf-8-sig", "cp1250", "latin-1"):
        try:
            with open(sciezka, "r", encoding=kodowanie, newline="") as f:
                surowe = f.read()
            break
        except UnicodeDecodeError:
            continue
    if surowe is None:
        raise ValueError("Nie udało się odczytać pliku — nieznane kodowanie znaków.")

    if not surowe.strip():
        raise ValueError("Plik jest pusty.")

    pierwsza_linia = surowe.splitlines()[0]
    separator = max((";", ",", "\t"), key=pierwsza_linia.count)
    if pierwsza_linia.count(separator) == 0:
        separator = ";"

    czytnik = csv.reader(io.StringIO(surowe), delimiter=separator)
    wszystkie = [w for w in czytnik if any((k or "").strip() for k in w)]
    if not wszystkie:
        raise ValueError("Plik nie zawiera żadnych danych.")

    naglowki = [str(k).strip() for k in wszystkie[0]]
    szerokosc = len(naglowki)
    wiersze = []
    for w in wszystkie[1:]:
        w = list(w[:szerokosc]) + [""] * max(0, szerokosc - len(w))
        wiersze.append([str(k).strip() for k in w])
    return naglowki, wiersze


def dopasuj_kolumny_tankowan(naglowki):
    """Automatyczne zgadywanie, która kolumna pliku odpowiada któremu polu.
    Zwraca {pole: indeks_kolumny lub None} — użytkownik może to potem poprawić."""
    znormalizowane = [_normalizuj_naglowek(h) for h in naglowki]
    mapowanie = {pole: None for pole in POLA_IMPORTU_TANKOWAN}
    zajete = set()

    for pole, aliasy in _ALIASY_IMPORTU.items():
        for dokladne in (True, False):
            for i, h in enumerate(znormalizowane):
                if i in zajete or not h:
                    continue
                trafienie = (h in aliasy) if dokladne else any(a in h for a in aliasy)
                if trafienie:
                    mapowanie[pole] = i
                    zajete.add(i)
                    break
            if mapowanie[pole] is not None:
                break
    return mapowanie


def przygotuj_import_tankowan(auto_id, naglowki, wiersze, mapowanie):
    """Waliduje wiersze wg mapowania kolumn i wykrywa duplikaty względem tego,
    co JUŻ jest w bazie (ta sama data + przebieg + kwota, jak w dedupie sync).
    Nic nie zapisuje. Zwraca {"gotowe": [...], "duplikaty": n, "bledy": [(nr, powod)]}."""
    gotowe, bledy = [], []
    duplikaty = 0

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT data, przebieg, kwota FROM tankowania WHERE auto_id=?", (auto_id,))
        istniejace = {(str(d or ""), int(p or 0), round(float(k or 0), 2)) for d, p, k in c.fetchall()}

    def wartosc(wiersz, pole):
        idx = mapowanie.get(pole)
        if idx is None or idx >= len(wiersz):
            return ""
        return wiersz[idx]

    for nr, wiersz in enumerate(wiersze, start=2):  # +1 za nagłówek, +1 bo numerujemy od 1
        data_txt = _parsuj_date_csv(wartosc(wiersz, "data"))
        if not data_txt:
            bledy.append((nr, "nieczytelna albo pusta data"))
            continue

        litry = _parsuj_liczbe_csv(wartosc(wiersz, "litry"))
        kwota = _parsuj_liczbe_csv(wartosc(wiersz, "kwota"))
        if litry is None or litry <= 0:
            bledy.append((nr, "brak lub zerowa ilość paliwa/energii"))
            continue
        if kwota is None or kwota <= 0:
            bledy.append((nr, "brak lub zerowa kwota"))
            continue

        przebieg = _parsuj_liczbe_csv(wartosc(wiersz, "przebieg"))
        dystans = _parsuj_liczbe_csv(wartosc(wiersz, "dystans"))
        przebieg_i = int(przebieg) if przebieg and przebieg > 0 else 0
        dystans_f = float(dystans) if dystans and dystans > 0 else 0.0
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
                "INSERT INTO tankowania (auto_id, data, przebieg, dystans, litry, kwota, do_pelna, stacja, "
                "rodzaj_energii, dodane_przez) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (auto_id, g["data"], g["przebieg"], g["dystans"], g["litry"],
                 g["kwota"], g["do_pelna"], g["stacja"] or None,
                 g.get("rodzaj_energii") or domyslny_rodzaj_energii(auto_id), kto)
            )
    return len(gotowe)


# ==================== IMPORT CSV — POZOSTAŁE TYPY ====================
# Ten sam mechanizm, co dla tankowań (wczytanie pliku, dopasowanie kolumn,
# walidacja, deduplikacja), tylko sparametryzowany typem wpisu. Dzięki temu
# dołożenie kolejnego typu to jeden wpis w TYPY_IMPORTU, a nie kopia widoku.

POLA_IMPORTU_INNYCH_KOSZTOW = {
    "data": ("Data", True),
    "nazwa": ("Opis / nazwa", True),
    "kwota": ("Kwota", True),
    "tagi": ("Tagi / kategoria", False),
}


POLA_IMPORTU_ODCZYTOW = {
    "data": ("Data", True),
    "przebieg": ("Stan licznika (km)", True),
}


_ALIASY_IMPORTU_INNYCH = {
    "data": ["data", "date", "dzien", "dzień", "datum", "data wydatku"],
    "nazwa": ["nazwa", "opis", "description", "tytul", "tytuł", "name", "usluga", "usługa", "pozycja", "co"],
    "kwota": ["kwota", "koszt", "cena", "cost", "total", "price", "wartosc", "wartość", "suma"],
    "tagi": ["tagi", "tag", "kategoria", "category", "typ", "rodzaj", "grupa"],
}


_ALIASY_IMPORTU_ODCZYTOW = {
    "data": ["data", "date", "dzien", "dzień", "datum", "data odczytu"],
    "przebieg": ["przebieg", "licznik", "odometer", "odo", "mileage", "km", "stan licznika", "przebieg (km)"],
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


def przygotuj_import_innych_kosztow(auto_id, naglowki, wiersze, mapowanie):
    """Waliduje wiersze i odsiewa duplikaty względem tego, co już jest w bazie
    (ta sama data + nazwa + kwota). Nic nie zapisuje."""
    gotowe, bledy = [], []
    duplikaty = 0

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT data, nazwa, kwota FROM inne_koszty WHERE auto_id=?", (auto_id,))
        istniejace = {
            (str(d or ""), klucz_nazwy(n), round(float(k or 0), 2))
            for d, n, k in c.fetchall()
        }

    for nr, wiersz in enumerate(wiersze, start=2):
        data_txt = _parsuj_date_csv(_wartosc_z_wiersza(wiersz, mapowanie, "data"))
        if not data_txt:
            bledy.append((nr, "nieczytelna albo pusta data"))
            continue

        nazwa = normalizuj_nazwe(_wartosc_z_wiersza(wiersz, mapowanie, "nazwa"))
        if not nazwa:
            bledy.append((nr, "brak opisu / nazwy wydatku"))
            continue

        kwota = _parsuj_liczbe_csv(_wartosc_z_wiersza(wiersz, mapowanie, "kwota"))
        if kwota is None or kwota <= 0:
            bledy.append((nr, "brak lub zerowa kwota"))
            continue

        klucz = (data_txt, klucz_nazwy(nazwa), round(kwota, 2))
        if klucz in istniejace:
            duplikaty += 1
            continue
        istniejace.add(klucz)

        gotowe.append({
            "data": data_txt,
            "nazwa": nazwa,
            "kwota": float(kwota),
            "tagi": normalizuj_nazwe(_wartosc_z_wiersza(wiersz, mapowanie, "tagi")),
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
                "INSERT INTO inne_koszty (auto_id, data, kategoria, nazwa, kwota, tagi, dodane_przez) "
                "VALUES (?,?,?,?,?,?,?)",
                (auto_id, g["data"], "", g["nazwa"], g["kwota"], g["tagi"] or None, kto)
            )
    return len(gotowe)


def przygotuj_import_odczytow(auto_id, naglowki, wiersze, mapowanie):
    """Odczyty licznika: duplikatem jest ta sama data + ten sam przebieg.
    Dodatkowo odsiewamy wiersze z przebiegiem <= 0, bo taki odczyt nic nie wnosi,
    a psuje wyliczenia średniego dziennego przebiegu."""
    gotowe, bledy = [], []
    duplikaty = 0

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT data, przebieg FROM odczyty_przebiegu WHERE auto_id=?", (auto_id,))
        istniejace = {(str(d or ""), int(p or 0)) for d, p in c.fetchall()}

    for nr, wiersz in enumerate(wiersze, start=2):
        data_txt = _parsuj_date_csv(_wartosc_z_wiersza(wiersz, mapowanie, "data"))
        if not data_txt:
            bledy.append((nr, "nieczytelna albo pusta data"))
            continue

        przebieg = _parsuj_liczbe_csv(_wartosc_z_wiersza(wiersz, mapowanie, "przebieg"))
        if przebieg is None or przebieg <= 0:
            bledy.append((nr, "brak lub zerowy stan licznika"))
            continue

        klucz = (data_txt, int(przebieg))
        if klucz in istniejace:
            duplikaty += 1
            continue
        istniejace.add(klucz)

        gotowe.append({"data": data_txt, "przebieg": int(przebieg)})

    gotowe.sort(key=lambda g: (parsuj_date(g["data"]), g["przebieg"]))
    return {"gotowe": gotowe, "duplikaty": duplikaty, "bledy": bledy}


def zaimportuj_odczyty(auto_id, gotowe):
    if not auto_id or not gotowe:
        return 0
    with polacz_baze() as conn:
        for g in gotowe:
            conn.execute(
                "INSERT INTO odczyty_przebiegu (auto_id, data, przebieg, zrodlo) VALUES (?,?,?,?)",
                (auto_id, g["data"], g["przebieg"], "import")
            )
    return len(gotowe)


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
        "podglad": lambda g, jednostka: (
            f"{g['data']} • {g['przebieg']} km • {g['litry']:.2f} "
            f"{'kWh' if g.get('rodzaj_energii') == ENERGIA_PRAD else jednostka} • {g['kwota']:.2f}"
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
            f"{g['data']} • {g['nazwa']} • {g['kwota']:.2f}"
            + (f" • {g['tagi']}" if g.get("tagi") else "")
        ),
    },
    "odczyty": {
        "etykieta": "Odczyty licznika",
        "opis": "Sam stan licznika w czasie — przydatne, gdy tankowania prowadzisz gdzie indziej.",
        "pola": POLA_IMPORTU_ODCZYTOW,
        "dopasuj": dopasuj_kolumny_odczytow,
        "przygotuj": przygotuj_import_odczytow,
        "zapisz": zaimportuj_odczyty,
        "podglad": lambda g, jednostka: f"{g['data']} • {g['przebieg']} km",
    },
}


__all__ = [
    "POLA_IMPORTU_INNYCH_KOSZTOW",
    "POLA_IMPORTU_ODCZYTOW",
    "POLA_IMPORTU_TANKOWAN",
    "TYPY_IMPORTU",
    "_ALIASY_IMPORTU",
    "_ALIASY_IMPORTU_INNYCH",
    "_ALIASY_IMPORTU_ODCZYTOW",
    "_dopasuj_kolumny",
    "_normalizuj_naglowek",
    "_parsuj_date_csv",
    "_prawda_csv",
    "_rozpoznaj_rodzaj_csv",
    "_wartosc_z_wiersza",
    "dopasuj_kolumny_innych_kosztow",
    "dopasuj_kolumny_odczytow",
    "dopasuj_kolumny_tankowan",
    "przygotuj_import_innych_kosztow",
    "przygotuj_import_odczytow",
    "przygotuj_import_tankowan",
    "wczytaj_plik_csv",
    "zaimportuj_inne_koszty",
    "zaimportuj_odczyty",
    "zaimportuj_tankowania",
]
