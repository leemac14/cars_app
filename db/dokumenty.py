"""Skarbiec dokumentów pojazdu (N-05): dowód, polisy, umowa kupna, gwarancje, instrukcja.
Pliki leżą w `zalaczniki` (tabela 'dokumenty_pojazdu'), opis i daty jadą do chmury bez plików.
Polisa, przegląd, assistance i gwarancja producenta dzielą datę z Kartą pojazdu."""

from datetime import datetime
from typing import Any

from date import na_iso, parsuj_date

from .stale import KLUCZ_PROGU_SKARBCA
from .polaczenie import polacz_baze
from .ustawienia import pobierz_moje_imie, pobierz_prog_dni_dokumentu


# (klucz, etykieta, kolumna `samochody` ze wspólną datą albo None). Etykiety rodzajów
# z kolumną — jak w TERMINY_DOKUMENTOW.
RODZAJE_DOKUMENTOW = [
    ("dowod", "Dowód rejestracyjny", None),
    ("oc", "Polisa OC", "oc_data"),
    ("ac", "Polisa AC", "ac_data"),
    ("assistance", "Assistance", "assistance_data"),
    ("przeglad", "Przegląd techniczny", "przeglad_data"),
    ("umowa", "Umowa kupna", None),
    ("gwarancja", "Gwarancja producenta", "gwarancja_data"),
    ("gwarancja_inna", "Inna gwarancja", None),
    ("instrukcja", "Instrukcja obsługi", None),
    ("ksiazka", "Książka serwisowa", None),
    ("inne", "Inny dokument", None),
]

ETYKIETY_DOKUMENTOW = {k: e for k, e, _ in RODZAJE_DOKUMENTOW}
KOLUMNY_DATY_DOKUMENTOW = {k: kol for k, _, kol in RODZAJE_DOKUMENTOW if kol}
_KOLEJNOSC_RODZAJOW = {k: i for i, (k, _, _) in enumerate(RODZAJE_DOKUMENTOW)}

_POLA = ("id", "auto_id", "rodzaj", "nazwa", "numer", "data_wystawienia", "data_waznosci", "notatki",
         "liczba_plikow", "dodane_przez", "zdalne_id")


def etykieta_dokumentu(rodzaj) -> str:
    return ETYKIETY_DOKUMENTOW.get(rodzaj) or str(rodzaj or "Dokument")


def _wiersze(conn, auto_id):
    return [dict(zip(_POLA, w)) for w in conn.execute(
        f"SELECT {', '.join(_POLA)} FROM dokumenty_pojazdu WHERE auto_id=?", (auto_id,)).fetchall()]


def _aktualne(dokumenty) -> dict[str, int]:
    """{rodzaj: id} dokumentu, który nosi datę z Karty pojazdu: najpóźniej ważny (własna data),
    przy remisie ostatnio dodany. Starsze tego rodzaju są archiwalne."""
    najlepsze = {}
    for d in dokumenty:
        if d["rodzaj"] not in KOLUMNY_DATY_DOKUMENTOW:
            continue
        klucz = (na_iso(d["data_waznosci"]) or "", d["id"])
        if d["rodzaj"] not in najlepsze or klucz > najlepsze[d["rodzaj"]]:
            najlepsze[d["rodzaj"]] = klucz
    return {r: k[1] for r, k in najlepsze.items()}


def _daty_karty(conn, auto_id) -> dict[str, str]:
    kolumny = sorted(set(KOLUMNY_DATY_DOKUMENTOW.values()))
    w = conn.execute(f"SELECT {', '.join(kolumny)} FROM samochody WHERE id=?", (auto_id,)).fetchone()
    return dict(zip(kolumny, w)) if w else {}


def pobierz_dokument(dokument_id) -> dict[str, Any] | None:
    if not dokument_id:
        return None
    with polacz_baze() as conn:
        w = conn.execute(f"SELECT {', '.join(_POLA)} FROM dokumenty_pojazdu WHERE id=?", (dokument_id,)).fetchone()
    return dict(zip(_POLA, w)) if w else None


def data_z_karty(auto_id, rodzaj) -> str | None:
    """Data z Karty pojazdu dla rodzaju z kolumną (podpowiedź w formularzu nowego dokumentu)."""
    kolumna = KOLUMNY_DATY_DOKUMENTOW.get(rodzaj)
    if not auto_id or not kolumna:
        return None
    with polacz_baze() as conn:
        return _daty_karty(conn, auto_id).get(kolumna) or None


def dokumenty_pojazdu(auto_id, dzis=None) -> list[dict[str, Any]]:
    """Dokumenty od najpilniejszego. Poza polami tabeli: `tytul` (nazwa albo rodzaj), `tytul_pelny`
    (rodzaj z nazwą — dzwonek i odliczania), `etykieta`, `waznosc` (data do
    pokazania), `z_karty` (data z Karty pojazdu — przypomina o niej Karta), `archiwalny` (starsza
    polisa itp.), `dni`, `prog`, `status` ('po_terminie'/'blisko'/'ok'/None), `przypomina`."""
    if not auto_id:
        return []
    dzis = dzis or datetime.now().date()
    with polacz_baze() as conn:
        dokumenty = _wiersze(conn, auto_id)
        karta = _daty_karty(conn, auto_id) if dokumenty else {}
    aktualne = _aktualne(dokumenty)
    for d in dokumenty:
        kolumna = KOLUMNY_DATY_DOKUMENTOW.get(d["rodzaj"])
        d["archiwalny"] = bool(kolumna) and aktualne.get(d["rodzaj"]) != d["id"]
        z_karty = bool(kolumna) and not d["archiwalny"] and bool(karta.get(kolumna))
        d["z_karty"] = z_karty
        d["waznosc"] = karta[kolumna] if z_karty else (d["data_waznosci"] or None)
        d["etykieta"] = etykieta_dokumentu(d["rodzaj"])
        nazwa = (d["nazwa"] or "").strip()
        d["tytul"] = nazwa or d["etykieta"]
        d["tytul_pelny"] = f"{d['etykieta']}: {nazwa}" if nazwa else d["etykieta"]
        d["prog"] = pobierz_prog_dni_dokumentu(d["rodzaj"] if kolumna else KLUCZ_PROGU_SKARBCA)
        koniec = parsuj_date(d["waznosc"]) if d["waznosc"] else None
        if koniec is None or koniec == datetime.min.date():
            d["dni"], d["status"] = None, None
        else:
            d["dni"] = (koniec - dzis).days
            d["status"] = (None if d["archiwalny"] else "po_terminie" if d["dni"] < 0
                           else "blisko" if d["dni"] <= d["prog"] else "ok")
        d["przypomina"] = d["dni"] is not None and not d["archiwalny"] and not z_karty
    dokumenty.sort(key=lambda d: (d["archiwalny"], d["dni"] is None, d["dni"] or 0,
                                  _KOLEJNOSC_RODZAJOW.get(d["rodzaj"], 99), d["tytul"].lower(), d["id"]))
    return dokumenty


def terminy_skarbca(auto_id, dzis=None) -> list[dict[str, Any]]:
    """Dokumenty z własną datą, o których przypomina skarbiec (data z Karty ma swoje przypomnienia)."""
    return [d for d in dokumenty_pojazdu(auto_id, dzis) if d["przypomina"]]


def zapisz_dokument(conn, auto_id, pola, dokument_id=None) -> int:
    """Zapis w transakcji formularza; zwraca id. Dokument, który po zapisie jest aktualnym
    swojego rodzaju, przepisuje datę ważności na Kartę pojazdu — pusta jej nie kasuje."""
    rodzaj = pola["rodzaj"]
    wartosci = tuple((str(pola.get(k) or "").strip() or None)
                     for k in ("nazwa", "numer", "data_wystawienia", "data_waznosci", "notatki"))
    if dokument_id:
        conn.execute("UPDATE dokumenty_pojazdu SET rodzaj=?, nazwa=?, numer=?, data_wystawienia=?, "
                     "data_waznosci=?, notatki=? WHERE id=?", (rodzaj, *wartosci, dokument_id))
    else:
        dokument_id = conn.execute(
            "INSERT INTO dokumenty_pojazdu (auto_id, rodzaj, nazwa, numer, data_wystawienia, data_waznosci, "
            "notatki, dodane_przez) VALUES (?,?,?,?,?,?,?,?)",
            (auto_id, rodzaj, *wartosci, pobierz_moje_imie())).lastrowid
    kolumna = KOLUMNY_DATY_DOKUMENTOW.get(rodzaj)
    data = wartosci[3]
    if kolumna and data and _aktualne(_wiersze(conn, auto_id)).get(rodzaj) == dokument_id:
        conn.execute(f"UPDATE samochody SET {kolumna}=? WHERE id=?", (data, auto_id))
    return dokument_id


def podsumowanie_dokumentow(auto_id) -> dict[str, int]:
    """Do wejścia z Karty pojazdu: ile dokumentów i ile z nich po terminie albo blisko końca."""
    dokumenty = [d for d in dokumenty_pojazdu(auto_id) if not d["archiwalny"]]
    return {
        "liczba": len(dokumenty),
        "pilne": sum(1 for d in dokumenty if d["status"] in ("po_terminie", "blisko")),
    }


__all__ = [
    "ETYKIETY_DOKUMENTOW",
    "KOLUMNY_DATY_DOKUMENTOW",
    "RODZAJE_DOKUMENTOW",
    "data_z_karty",
    "dokumenty_pojazdu",
    "etykieta_dokumentu",
    "pobierz_dokument",
    "podsumowanie_dokumentow",
    "terminy_skarbca",
    "zapisz_dokument",
]
