"""Stan pozycji magazynu = stan wyjściowy (`ilosc_bazowa`, jedzie do chmury) minus zużycie
ze wszystkich telefonów (wpisy, wizyty, dolewki). Zużycie nie zmienia rekordu pozycji, więc
dwa telefony bez sieci nie nadpiszą sobie stanu; korekta i zakup zmieniają stan wyjściowy
(wygrywa ostatni). `ilosc` to pochodna — zostaje w wierszu dla list, filtrów, progów
i starszych wersji aplikacji. Stan wyjściowy NULL (rekord ze starszej wersji, migawka
sprzed migracji 55) = „policz z bieżącej `ilosc`”: ilosc + zużycie."""

import hashlib
import json
from itertools import combinations

from .polaczenie import polacz_baze
from .pomocnicze import _na_liczbe


# Zużycie z magazynu: tabela → kolumna ilości (w jednostce pozycji).
ZUZYCIE_MAGAZYNU = {
    "historia_czesci_magazynu": "ilosc_uzyta",
    "wizyta_czesci_magazynu": "ilosc_uzyta",
    "dolewki": "ilosc_magazynu",
}


def _zaokraglij(wartosc):
    return round(float(wartosc), 4)


def zuzycie_pozycji(conn, magazyn_ids=None) -> dict[int, float]:
    """{pozycja: suma zużycia ze wszystkich nośników}; bez `magazyn_ids` — wszystkie."""
    wynik = {}
    for tabela, kolumna in ZUZYCIE_MAGAZYNU.items():
        zapytanie = f"SELECT magazyn_id, {kolumna} FROM {tabela} WHERE magazyn_id IS NOT NULL"
        parametry = ()
        if magazyn_ids is not None:
            ids = sorted({i for i in magazyn_ids if i})
            if not ids:
                return {}
            zapytanie += f" AND magazyn_id IN ({','.join('?' * len(ids))})"
            parametry = tuple(ids)
        for magazyn_id, ilosc in conn.execute(zapytanie, parametry).fetchall():
            wynik[magazyn_id] = wynik.get(magazyn_id, 0.0) + (_na_liczbe(ilosc) or 0.0)
    return wynik


def _pozycje(conn, magazyn_ids=None, auto_id=None):
    zapytanie, parametry = "SELECT id, ilosc, ilosc_bazowa FROM magazyn_czesci", ()
    if magazyn_ids is not None:
        ids = sorted({i for i in magazyn_ids if i})
        if not ids:
            return []
        zapytanie += f" WHERE id IN ({','.join('?' * len(ids))})"
        parametry = tuple(ids)
    elif auto_id is not None:
        zapytanie += " WHERE auto_id=?"
        parametry = (auto_id,)
    return conn.execute(zapytanie, parametry).fetchall()


def _przelicz(conn, magazyn_ids=None, auto_id=None):
    zuzycie = zuzycie_pozycji(conn, magazyn_ids)
    zmienione = 0
    for magazyn_id, ilosc, baza in _pozycje(conn, magazyn_ids, auto_id):
        uzyte = zuzycie.get(magazyn_id, 0.0)
        if _na_liczbe(baza) is None:
            baza = _zaokraglij((_na_liczbe(ilosc) or 0.0) + uzyte)
            conn.execute("UPDATE magazyn_czesci SET ilosc_bazowa=? WHERE id=?", (baza, magazyn_id))
        stan = max(0.0, _zaokraglij(_na_liczbe(baza) - uzyte))
        if _na_liczbe(ilosc) is None or abs(_na_liczbe(ilosc) - stan) > 1e-9 or not isinstance(ilosc, (int, float)):
            conn.execute("UPDATE magazyn_czesci SET ilosc=? WHERE id=?", (stan, magazyn_id))
            zmienione += 1
    return zmienione


def przelicz_stan_magazynu(conn=None, magazyn_ids=None, auto_id=None):
    """`ilosc` = max(0, stan wyjściowy − zużycie) dla podanych pozycji, pozycji pojazdu albo
    wszystkich; brakujący stan wyjściowy liczy się z bieżącej `ilosc`. Wołać PO każdej zmianie
    zużycia i po wgraniu danych z zewnątrz (chmura, kosz, plik pojazdu). Zwraca liczbę
    pozycji, którym zmienił się stan."""
    if conn is not None:
        return _przelicz(conn, magazyn_ids, auto_id)
    with polacz_baze() as polaczenie:
        return _przelicz(polaczenie, magazyn_ids, auto_id)


def zapewnij_stan_wyjsciowy(conn, magazyn_ids=None):
    """Przed zmianą zużycia: pozycja bez stanu wyjściowego dostaje go z bieżącego stanu —
    inaczej przeliczenie PO zmianie wzięłoby za punkt wyjścia stan już po niej. Bez
    `magazyn_ids` — wszystkie pozycje."""
    zuzycie = zuzycie_pozycji(conn, magazyn_ids)
    for magazyn_id, ilosc, baza in _pozycje(conn, magazyn_ids):
        if _na_liczbe(baza) is None:
            conn.execute("UPDATE magazyn_czesci SET ilosc_bazowa=? WHERE id=?",
                         (_zaokraglij((_na_liczbe(ilosc) or 0.0) + zuzycie.get(magazyn_id, 0.0)), magazyn_id))


def ustaw_stan_magazynu(conn, magazyn_id, stan):
    """Korekta stanu z formularza: na półce ma być `stan` → stan wyjściowy = stan + zużycie.
    Stan równy bieżącemu nie rusza stanu wyjściowego (zapis samej nazwy nie jest korektą)."""
    stan = max(0.0, _na_liczbe(stan) or 0.0)
    wiersz = conn.execute("SELECT ilosc, ilosc_bazowa FROM magazyn_czesci WHERE id=?", (magazyn_id,)).fetchone()
    if not wiersz:
        return
    if _na_liczbe(wiersz[1]) is not None and _na_liczbe(wiersz[0]) is not None \
            and abs(_na_liczbe(wiersz[0]) - stan) <= 1e-9:
        return
    uzyte = zuzycie_pozycji(conn, [magazyn_id]).get(magazyn_id, 0.0)
    conn.execute("UPDATE magazyn_czesci SET ilosc_bazowa=?, ilosc=? WHERE id=?",
                 (_zaokraglij(stan + uzyte), _zaokraglij(stan), magazyn_id))


def dodaj_do_stanu_magazynu(conn, magazyn_id, ile):
    """Zakup: stan wyjściowy rośnie o `ile` (zużycie zostaje, jak było). Zwraca nowy stan."""
    zapewnij_stan_wyjsciowy(conn, [magazyn_id])
    conn.execute("UPDATE magazyn_czesci SET ilosc_bazowa=ROUND(ilosc_bazowa + ?, 4) WHERE id=?",
                 (_na_liczbe(ile) or 0.0, magazyn_id))
    _przelicz(conn, [magazyn_id])
    wiersz = conn.execute("SELECT ilosc FROM magazyn_czesci WHERE id=?", (magazyn_id,)).fetchone()
    return _na_liczbe(wiersz[0]) if wiersz else None


# ---------------------------------------------------------------- migracja 55
# Odcisk rekordu dokładnie jak `sync._hash_zawartosci` (db nie importuje sync; test
# porównuje obie funkcje). Kolumny chmury zamrożone na wersję 55 — tak migracja
# rozpoznaje rekord niezmieniony od ostatniej synchronizacji.
_KOLUMNY_CHMURY_DO_54 = ("nazwa", "kategoria", "ilosc", "jednostka", "cena", "cena_jednostkowa", "data_zakupu",
                         "notatki", "prog_ostrzezenia", "sklep", "link")
_DOPISANE_DO_54 = ("sklep", "link")


def _odcisk_jak_w_chmurze(dane):
    istotne = {k: v for k, v in (dane or {}).items() if not str(k).startswith("_")}
    kanoniczny = json.dumps(istotne, sort_keys=True, default=str, ensure_ascii=True)
    return hashlib.sha256(kanoniczny.encode("utf-8")).hexdigest()


def _odciski_z_tolerancja(dane, dopisane):
    """Odcisk pełny i bez każdego zestawu PUSTYCH dopisanych kolumn (jak `_zgodny_z_zapamietanym`)."""
    odciski = {_odcisk_jak_w_chmurze(dane)}
    puste = [k for k in dopisane if k in dane and dane[k] is None]
    for ile in range(1, len(puste) + 1):
        for pominiete in combinations(puste, ile):
            odciski.add(_odcisk_jak_w_chmurze({k: v for k, v in dane.items() if k not in pominiete}))
    return odciski


def zainicjuj_stan_wyjsciowy(conn):
    """Migracja 55: stan wyjściowy = stan na półce + całe zużycie (stan się nie zmienia). Rekord
    zsynchronizowany i od tamtej pory niezmieniony dostaje odcisk w nowej postaci (bez pochodnej
    `ilosc`, ze stanem wyjściowym) — pierwsza synchronizacja po aktualizacji nie wysyła wtedy
    całego magazynu nad zmianami drugiej osoby. Starsza wersja, która pobrała już rekord ze
    stanem wyjściowym, zapamiętała odcisk z nim — to też „niezmieniony”."""
    zapewnij_stan_wyjsciowy(conn)
    kolumny = ", ".join(_KOLUMNY_CHMURY_DO_54)
    wiersze = conn.execute(
        f"SELECT id, zdalny_hash, ilosc_bazowa, {kolumny} FROM magazyn_czesci "
        "WHERE zdalne_id IS NOT NULL AND zdalny_hash IS NOT NULL").fetchall()
    for magazyn_id, zapamietany, baza, *wartosci in wiersze:
        dawne = dict(zip(_KOLUMNY_CHMURY_DO_54, wartosci))
        kandydaci = _odciski_z_tolerancja(dawne, _DOPISANE_DO_54) | \
            _odciski_z_tolerancja(dict(dawne, ilosc_bazowa=baza), _DOPISANE_DO_54)
        if zapamietany in kandydaci:
            nowe = {k: v for k, v in dawne.items() if k != "ilosc"}
            nowe["ilosc_bazowa"] = baza
            conn.execute("UPDATE magazyn_czesci SET zdalny_hash=? WHERE id=?",
                         (_odcisk_jak_w_chmurze(nowe), magazyn_id))


__all__ = [
    "ZUZYCIE_MAGAZYNU",
    "dodaj_do_stanu_magazynu",
    "przelicz_stan_magazynu",
    "ustaw_stan_magazynu",
    "zainicjuj_stan_wyjsciowy",
    "zapewnij_stan_wyjsciowy",
    "zuzycie_pozycji",
]
