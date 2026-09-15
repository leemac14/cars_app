"""Magazyn części: rozliczanie zużycia, zwroty i zestawy opon."""

import os
import shutil
import sqlite3
import uuid
from date import parsuj_date
from datetime import datetime
from typing import Any

from .stale import MIESIACE_ZIMOWE, SEZONY_PRZELACZALNE
from .polaczenie import polacz_baze
from .pomocnicze import _na_liczbe, bez_emoji
from .synchronizacja import czy_moge_zmieniac_rekord, usun_nagrobek, zarejestruj_nagrobek
from .zalaczniki import _upewnij_folder_odroczonych, usun_plik_zalacznika


# Zużycie części z magazynu ma dwa nośniki: wizytę zbiorczą i pojedynczy wpis
# serwisowy. Tabele są lustrzane, więc cała logika (pobranie, oddanie na stan,
# potrącenie) siedzi w jednym rdzeniu sparametryzowanym nazwą tabeli i kolumną
# wiążącą — zamiast dwóch kopii, które z czasem by się rozjechały.
POWIAZANIA_MAGAZYNU = {
    "wizyty": ("wizyta_czesci_magazynu", "wizyta_id"),
    "historia": ("historia_czesci_magazynu", "historia_id"),
}


def _pobierz_uzyte_czesci(zrodlo, rekord_id):
    tabela, kolumna = POWIAZANIA_MAGAZYNU[zrodlo]
    if not rekord_id:
        return []
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(f"SELECT magazyn_id, ilosc_uzyta FROM {tabela} WHERE {kolumna}=?", (rekord_id,))
        return c.fetchall()


def _przywroc_czesci(zrodlo, rekord_id, conn=None):
    """Oddaje do magazynu wykorzystane wcześniej części i usuwa powiązania.
    Zwraca listę zdalne_id usuniętych powiązań — WYWOŁUJĄCY musi je
    zarejestrować jako nagrobki (zarejestruj_nagrobek) DOPIERO PO
    zamknięciu/commicie bieżącej transakcji (conn). Rejestracja w środku
    otwartej transakcji otworzyłaby drugie połączenie do tego samego pliku
    SQLite i mogłaby zakleszczyć bazę."""
    tabela, kolumna = POWIAZANIA_MAGAZYNU[zrodlo]
    usuniete_zdalne_id = []

    def _wykonaj(c):
        cur = c.cursor()
        cur.execute(f"SELECT magazyn_id, ilosc_uzyta, zdalne_id FROM {tabela} WHERE {kolumna}=?", (rekord_id,))
        for magazyn_id, ilosc, zdalne_id in cur.fetchall():
            cur.execute("UPDATE magazyn_czesci SET ilosc = ilosc + ? WHERE id=?", (ilosc, magazyn_id))
            if zdalne_id:
                usuniete_zdalne_id.append(zdalne_id)
        cur.execute(f"DELETE FROM {tabela} WHERE {kolumna}=?", (rekord_id,))

    if conn is not None:
        _wykonaj(conn)
    else:
        with polacz_baze() as conn_local:
            _wykonaj(conn_local)

    return usuniete_zdalne_id


def _rozlicz_czesci(zrodlo, rekord_id, uzyte, conn=None):
    """Zapisuje zużycie i zdejmuje sztuki ze stanu. `uzyte` to pary
    (magazyn_id, ilosc) albo — już wycenione — trójki (magazyn_id, ilosc, koszt),
    patrz wycen_zuzycie. Para zapisuje zużycie bez kosztu, czyli „nie doliczone”."""
    tabela, kolumna = POWIAZANIA_MAGAZYNU[zrodlo]
    if not uzyte:
        return

    def _wykonaj(c):
        cur = c.cursor()
        for pozycja in uzyte:
            magazyn_id, ilosc = pozycja[0], pozycja[1]
            koszt = pozycja[2] if len(pozycja) > 2 else None
            if not ilosc or ilosc <= 0:
                continue
            cur.execute(
                f"INSERT INTO {tabela} ({kolumna}, magazyn_id, ilosc_uzyta, koszt) VALUES (?,?,?,?)",
                (rekord_id, magazyn_id, ilosc, koszt)
            )
            cur.execute("UPDATE magazyn_czesci SET ilosc = MAX(0, ilosc - ?) WHERE id=?", (ilosc, magazyn_id))

    if conn is not None:
        _wykonaj(conn)
    else:
        with polacz_baze() as conn_local:
            _wykonaj(conn_local)


# --- Wizyta zbiorcza (nazwy zachowane, bo używa ich formularz wizyty) ---
def pobierz_uzyte_czesci_wizyty(wizyta_id) -> list[tuple[int, float]]:
    return _pobierz_uzyte_czesci("wizyty", wizyta_id)


def przywroc_czesci_wizyty(wizyta_id, conn=None):
    return _przywroc_czesci("wizyty", wizyta_id, conn)


def rozlicz_czesci_z_magazynu(wizyta_id, uzyte, conn=None):
    return _rozlicz_czesci("wizyty", wizyta_id, uzyte, conn)


# --- Pojedynczy wpis serwisowy (poza wizytą) ---
def pobierz_uzyte_czesci_wpisu(historia_id) -> list[tuple[int, float]]:
    return _pobierz_uzyte_czesci("historia", historia_id)


def przywroc_czesci_wpisu(historia_id, conn=None):
    return _przywroc_czesci("historia", historia_id, conn)


def rozlicz_czesci_z_magazynu_wpisu(historia_id, uzyte, conn=None):
    return _rozlicz_czesci("historia", historia_id, uzyte, conn)


# ============================================================================
#  KOSZT ZUŻYCIA
# ============================================================================
# Część z magazynu jest kupiona wcześniej, ale jej koszt „wydarza się” dopiero
# wtedy, gdy ląduje w aucie. Dlatego doliczamy go przy ZUŻYCIU, nie przy
# zakupie — i zapisujemy wprost w `historia.cena` albo `wizyty.koszt_calkowity`.
# Statystyki, budżety, eksport i raporty czytają te dwie kolumny w kilkunastu
# miejscach; każde z nich widzi pełny koszt serwisu bez jednej poprawki.
#
# Ile z tej kwoty przyszło z magazynu, pamięta powiązanie zużycia (kolumna
# `koszt`). Formularz odejmuje to przy edycji, żeby w polu kosztu stała sama
# usługa — inaczej każdy kolejny zapis doliczałby części od nowa.


def cena_jednostkowa_z_zakupu(koszt_zakupu, ilosc) -> float | None:
    """Cena jednej sztuki (litra, grama) z tego, ile zapłacono za całą ilość.
    None, gdy nie da się jej uczciwie policzyć — zero sztuk nie znaczy „darmo”."""
    koszt, ile = _na_liczbe(koszt_zakupu), _na_liczbe(ilosc)
    if koszt is None or ile is None or koszt < 0 or ile <= 0:
        return None
    return round(koszt / ile, 4)


def pobierz_czesci_do_zuzycia(auto_id) -> list[dict[str, Any]]:
    """Pozycje magazynu do wyboru w formularzu wpisu i wizyty — razem z ceną za
    jednostkę, bo formularz pokazuje koszt zużycia, zanim cokolwiek zapisze."""
    if not auto_id:
        return []
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT id, nazwa, ilosc, jednostka, cena_jednostkowa FROM magazyn_czesci "
            "WHERE auto_id=? ORDER BY nazwa",
            (auto_id,)
        )
        return [
            {"id": r["id"], "nazwa": str(r["nazwa"] or ""), "ilosc": _na_liczbe(r["ilosc"]) or 0.0,
             "jednostka": str(r["jednostka"] or "szt"), "cena_jednostkowa": _na_liczbe(r["cena_jednostkowa"])}
            for r in c.fetchall()
        ]


def pobierz_zuzycie_czesci(zrodlo, rekord_id) -> dict[int, dict[str, Any]]:
    """Co rekord (wizyta albo pojedynczy wpis) już zdjął z magazynu:
    {magazyn_id: {"ilosc": float, "koszt": float | None}}.

    `koszt` None znaczy, że to zużycie NIE jest doliczone do kosztu rekordu:
    zapisała je starsza wersja aplikacji albo pozycja nie miała ceny."""
    tabela, kolumna = POWIAZANIA_MAGAZYNU[zrodlo]
    if not rekord_id:
        return {}
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(f"SELECT magazyn_id, ilosc_uzyta, koszt FROM {tabela} WHERE {kolumna}=?", (rekord_id,))
        wiersze = c.fetchall()

    wynik = {}
    for magazyn_id, ilosc, koszt in wiersze:
        pozycja = wynik.setdefault(magazyn_id, {"ilosc": 0.0, "koszt": None})
        pozycja["ilosc"] += _na_liczbe(ilosc) or 0.0
        if _na_liczbe(koszt) is not None:
            pozycja["koszt"] = round((pozycja["koszt"] or 0.0) + _na_liczbe(koszt), 2)
    return wynik


def koszt_doliczony(zuzycie) -> float:
    """Ile z kosztu rekordu przyszło z magazynu — suma zapamiętanych kosztów
    zużycia (wynik pobierz_zuzycie_czesci)."""
    return round(sum(p["koszt"] for p in (zuzycie or {}).values() if p.get("koszt") is not None), 2)


def cena_zuzycia(magazyn_id, ceny_jednostkowe, poprzednie=None) -> float | None:
    """Po jakiej cenie liczyć jednostkę tej pozycji w tym rekordzie.

    Pozycja, którą rekord już miał Z KOSZTEM, liczy się po tamtej cenie —
    poprawienie daty w wizycie sprzed roku nie może przepisać jej kosztu po
    dzisiejszej cenie oleju. Pozostałe biorą bieżącą cenę z magazynu."""
    poprzednia = (poprzednie or {}).get(magazyn_id) or {}
    ilosc = _na_liczbe(poprzednia.get("ilosc")) or 0.0
    if poprzednia.get("koszt") is not None and ilosc > 0:
        return float(poprzednia["koszt"]) / ilosc
    return _na_liczbe((ceny_jednostkowe or {}).get(magazyn_id))


def wycen_zuzycie(uzyte, ceny_jednostkowe, poprzednie=None) -> list[tuple[int, float, float | None]]:
    """[(magazyn_id, ilosc)] -> [(magazyn_id, ilosc, koszt)].

    Koszt None = pozycja bez ceny: zużycie zapisze się i zejdzie ze stanu, ale
    nic nie doliczy. Taki rekord dopłaci się sam przy najbliższej edycji, jeśli
    pozycja zdąży dostać cenę."""
    wynik = []
    for magazyn_id, ilosc in uzyte or []:
        ilosc = _na_liczbe(ilosc) or 0.0
        if ilosc <= 0:
            continue
        cena = cena_zuzycia(magazyn_id, ceny_jednostkowe, poprzednie)
        wynik.append((magazyn_id, ilosc, round(ilosc * cena, 2) if cena is not None else None))
    return wynik


def suma_kosztu_zuzycia(wycenione) -> float:
    """Łączny koszt wycenionego zużycia (wynik wycen_zuzycie)."""
    return round(sum(pozycja[2] for pozycja in (wycenione or []) if pozycja[2] is not None), 2)


def srednia_cena_jednostkowa(pozycje) -> float | None:
    """Cena za jednostkę po zsypaniu kilku pozycji w jedną — średnia ważona stanem.

    `pozycje` to [(ilosc, cena_jednostkowa)], pierwsza jest pozycją docelową.
    Pozycje bez ceny nie zaniżają średniej: nie wiadomo, ile były warte, więc
    nie udajemy, że nic. Gdy żadna nie ma nic na stanie, wygrywa pierwsza znana."""
    znane = []
    for ilosc, cena in pozycje or []:
        cena = _na_liczbe(cena)
        if cena is not None:
            znane.append((max(0.0, _na_liczbe(ilosc) or 0.0), cena))
    if not znane:
        return None
    waga = sum(ilosc for ilosc, _ in znane)
    if waga <= 0:
        return round(znane[0][1], 4)
    return round(sum(ilosc * cena for ilosc, cena in znane) / waga, 4)


def pobierz_zuzycie_rekordow(zrodlo, rekord_ids) -> dict[int, dict[str, Any]]:
    """Zużycie z magazynu dla kart na listach wizyt i wpisów:
    {rekord_id: {"pozycje": [{"nazwa", "ilosc", "jednostka", "koszt"}], "koszt": float}}.

    Jedno zapytanie na całą listę zamiast jednego na kartę. Celowo osobno od
    zapytania o same wizyty — JOIN z podzespołami i częściami naraz zdublowałby
    wiersze przy wizycie, która ma po kilka jednych i drugich."""
    tabela, kolumna = POWIAZANIA_MAGAZYNU[zrodlo]
    identyfikatory = [i for i in dict.fromkeys(rekord_ids or []) if i]
    wynik = {}
    if not identyfikatory:
        return wynik

    with polacz_baze() as conn:
        c = conn.cursor()
        for poczatek in range(0, len(identyfikatory), 500):
            paczka = identyfikatory[poczatek:poczatek + 500]
            znaki = ",".join("?" for _ in paczka)
            c.execute(
                f"SELECT x.{kolumna}, m.nazwa, x.ilosc_uzyta, m.jednostka, x.koszt FROM {tabela} x "
                f"JOIN magazyn_czesci m ON m.id = x.magazyn_id "
                f"WHERE x.{kolumna} IN ({znaki}) ORDER BY m.nazwa",
                tuple(paczka)
            )
            for rekord_id, nazwa, ilosc, jednostka, koszt in c.fetchall():
                pozycja = wynik.setdefault(rekord_id, {"pozycje": [], "koszt": 0.0})
                koszt = _na_liczbe(koszt)
                pozycja["pozycje"].append({
                    "nazwa": str(nazwa or ""), "ilosc": _na_liczbe(ilosc) or 0.0,
                    "jednostka": str(jednostka or "szt"), "koszt": koszt,
                })
                if koszt is not None:
                    pozycja["koszt"] = round(pozycja["koszt"] + koszt, 2)
    return wynik


def _zdejmij_powiazania_czesci_wpisow(historia_ids):
    """Przed skasowaniem wpisów serwisowych oddaje ich części na stan magazynu
    i zwraca zdjęte wiersze powiązań. CASCADE i tak skasowałby te powiązania —
    ale zrobiłby to CICHO, zostawiając sztuki „zużyte” w nieistniejącym już
    wpisie. Zwrócone wiersze pozwalają odtworzyć stan przy cofnięciu."""
    if not historia_ids:
        return []
    placeholders = ",".join("?" for _ in historia_ids)
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("PRAGMA table_info(historia_czesci_magazynu)")
        kolumny = [r["name"] for r in c.fetchall()]
        c.execute(
            f"SELECT * FROM historia_czesci_magazynu WHERE historia_id IN ({placeholders})",
            tuple(historia_ids)
        )
        wiersze = [{k: w[k] for k in kolumny} for w in c.fetchall()]
        if wiersze:
            for w in wiersze:
                c.execute("UPDATE magazyn_czesci SET ilosc = ilosc + ? WHERE id=?",
                          (w["ilosc_uzyta"], w["magazyn_id"]))
            c.execute(
                f"DELETE FROM historia_czesci_magazynu WHERE historia_id IN ({placeholders})",
                tuple(historia_ids)
            )
    return wiersze


def _przywroc_powiazania_czesci_wpisow(wiersze, mapa_historia=None):
    """Odwrotność _zdejmij_...: wstawia powiązania z powrotem (z oryginalnymi ID,
    o ile wolne) i ponownie potrąca sztuki ze stanu magazynu.

    mapa_historia przemapowuje historia_id: ścieżki cofania wstawiają wpis
    serwisowy BEZ oryginalnego id (patrz kolumny_bez_id), więc po przywróceniu
    zwykle ma on nowe ID i powiązanie wskazywałoby w próżnię."""
    if not wiersze:
        return
    mapa_historia = mapa_historia or {}
    with polacz_baze() as conn:
        c = conn.cursor()
        for w in wiersze:
            dane = dict(w)
            dane["historia_id"] = mapa_historia.get(dane.get("historia_id"), dane.get("historia_id"))
            c.execute("SELECT 1 FROM historia WHERE id=?", (dane["historia_id"],))
            if c.fetchone() is None:
                # Wpis nie wrócił (albo wrócił pod nieznanym ID) — powiązania nie
                # da się odtworzyć, a sztuki zostały już oddane na stan magazynu.
                continue
            stare_id = dane.get("id")
            if stare_id is not None:
                c.execute("SELECT 1 FROM historia_czesci_magazynu WHERE id=?", (stare_id,))
                if c.fetchone() is not None:
                    dane.pop("id", None)
            nazwy = list(dane.keys())
            c.execute(
                f"INSERT INTO historia_czesci_magazynu ({','.join(nazwy)}) "
                f"VALUES ({','.join('?' * len(nazwy))})",
                tuple(dane[k] for k in nazwy)
            )
            c.execute("UPDATE magazyn_czesci SET ilosc = MAX(0, ilosc - ?) WHERE id=?",
                      (dane["ilosc_uzyta"], dane["magazyn_id"]))


def usun_czesc_magazynu_z_cofnieciem(czesc_id):
    """Usuwa pozycję magazynową wraz z powiązanymi wpisami zużycia — zarówno
    w wizytach (wizyta_czesci_magazynu), jak i w pojedynczych wpisach serwisowych
    (historia_czesci_magazynu) — które SQLite skasowałoby cicho przez CASCADE.
    Zachowuje oryginalne ID pozycji."""
    if not czesc_id:
        return None

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("PRAGMA table_info(magazyn_czesci)")
        kol_m = [r["name"] for r in c.fetchall()]
        c.execute("SELECT * FROM magazyn_czesci WHERE id=?", (czesc_id,))
        w = c.fetchone()
        if not w:
            return None
        dane_czesc = {k: w[k] for k in kol_m}

        # Magazyn to wspólny inwentarz pojazdu, więc współautora nie ogranicza —
        # ale gość z rolą „tylko podgląd” nie ma prawa go czyścić (patrz
        # db/synchronizacja.czy_moge_zmieniac_rekord).
        try:
            if dane_czesc.get("auto_id") and not czy_moge_zmieniac_rekord(
                dane_czesc["auto_id"], "magazyn_czesci", None
            ):
                return None
        except Exception:
            pass

        c.execute("PRAGMA table_info(wizyta_czesci_magazynu)")
        kol_w = [r["name"] for r in c.fetchall()]
        c.execute("SELECT * FROM wizyta_czesci_magazynu WHERE magazyn_id=?", (czesc_id,))
        uzycia_dane = [{k: r[k] for k in kol_w} for r in c.fetchall()]

        c.execute("PRAGMA table_info(historia_czesci_magazynu)")
        kol_hw = [r["name"] for r in c.fetchall()]
        c.execute("SELECT * FROM historia_czesci_magazynu WHERE magazyn_id=?", (czesc_id,))
        uzycia_wpisow = [{k: r[k] for k in kol_hw} for r in c.fetchall()]

    sciezka_tymczasowa = None
    oryginalna = dane_czesc.get("zalacznik")
    if oryginalna and os.path.exists(oryginalna):
        folder_tmp = _upewnij_folder_odroczonych()
        sciezka_tymczasowa = os.path.join(folder_tmp, f"magazyn_{uuid.uuid4().hex}_{os.path.basename(oryginalna)}")
        try:
            shutil.move(oryginalna, sciezka_tymczasowa)
        except Exception:
            sciezka_tymczasowa = None

    with polacz_baze() as conn:
        conn.execute("DELETE FROM magazyn_czesci WHERE id=?", (czesc_id,))

    zdalny_id_czesci = dane_czesc.get("zdalne_id")
    if zdalny_id_czesci:
        zarejestruj_nagrobek("magazyn_czesci", zdalny_id_czesci)

    zdalne_id_uzycia = [d.get("zdalne_id") for d in uzycia_dane if d.get("zdalne_id")]
    for zid in zdalne_id_uzycia:
        zarejestruj_nagrobek("wizyta_czesci_magazynu", zid)

    zdalne_id_uzycia_wpisow = [d.get("zdalne_id") for d in uzycia_wpisow if d.get("zdalne_id")]
    for zid in zdalne_id_uzycia_wpisow:
        zarejestruj_nagrobek("historia_czesci_magazynu", zid)

    stan = {"cofniete": False, "trwale_usuniete": False}

    def cofnij():
        if stan["cofniete"] or stan["trwale_usuniete"]:
            return
        stan["cofniete"] = True

        if zdalny_id_czesci:
            usun_nagrobek(zdalny_id_czesci)
        for zid in zdalne_id_uzycia + zdalne_id_uzycia_wpisow:
            usun_nagrobek(zid)
        
        if sciezka_tymczasowa and os.path.exists(sciezka_tymczasowa):
            try:
                shutil.move(sciezka_tymczasowa, oryginalna)
            except Exception:
                pass
                
        with polacz_baze() as conn:
            n_m, p_m = ",".join(kol_m), ",".join("?" for _ in kol_m)
            conn.execute(f"INSERT INTO magazyn_czesci ({n_m}) VALUES ({p_m})", tuple(dane_czesc[k] for k in kol_m))
            if uzycia_dane:
                n_w, p_w = ",".join(kol_w), ",".join("?" for _ in kol_w)
                for d in uzycia_dane:
                    conn.execute(f"INSERT INTO wizyta_czesci_magazynu ({n_w}) VALUES ({p_w})", tuple(d[k] for k in kol_w))
            if uzycia_wpisow:
                n_hw, p_hw = ",".join(kol_hw), ",".join("?" for _ in kol_hw)
                for d in uzycia_wpisow:
                    conn.execute(f"INSERT INTO historia_czesci_magazynu ({n_hw}) VALUES ({p_hw})", tuple(d[k] for k in kol_hw))

    def finalizuj_usuniecie():
        if stan["cofniete"]:
            return
        stan["trwale_usuniete"] = True
        if sciezka_tymczasowa:
            usun_plik_zalacznika(sciezka_tymczasowa)

    return {"cofnij": cofnij, "finalizuj": finalizuj_usuniecie}


def usun_wiele_czesci_magazynu_z_cofnieciem(ids_list):
    wyniki = [w for w in (usun_czesc_magazynu_z_cofnieciem(cid) for cid in ids_list) if w]
    if not wyniki:
        return None

    stan = {"cofniete": False, "trwale_usuniete": False}

    def cofnij():
        if stan["cofniete"] or stan["trwale_usuniete"]:
            return
        stan["cofniete"] = True
        for w in wyniki:
            w["cofnij"]()

    def finalizuj_usuniecie():
        if stan["cofniete"]:
            return
        stan["trwale_usuniete"] = True
        for w in wyniki:
            w["finalizuj"]()

    return {"cofnij": cofnij, "finalizuj": finalizuj_usuniecie}


def pobierz_stan_magazynu(auto_id):
    """Ile pozycji leży na półce i ile z nich zeszło poniżej własnego progu —
    jedna liczba, po którą sięga kafelek kokpitu i podsumowania."""
    if not auto_id:
        return {"razem": 0, "niski": 0, "nazwy_niskich": []}
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT nazwa, ilosc, jednostka, prog_ostrzezenia FROM magazyn_czesci WHERE auto_id=?",
            (auto_id,)
        )
        wiersze = c.fetchall()

    niskie = []
    for nazwa, ilosc, jednostka, prog in wiersze:
        try:
            prog_efektywny = float(prog) if prog is not None else 1.0
        except (TypeError, ValueError):
            prog_efektywny = 1.0
        if float(ilosc or 0) <= prog_efektywny:
            niskie.append(str(nazwa or ""))
    return {"razem": len(wiersze), "niski": len(niskie), "nazwy_niskich": niskie}


def pobierz_wartosc_magazynu(auto_id) -> dict[str, Any]:
    """Ile jest wart magazyn: suma stan × cena za jednostkę po pozycjach na stanie.

    `bez_ceny` liczy pozycje na stanie, których nie da się wycenić — bez tej
    liczby suma udawałaby kompletną, a to akurat ta kwota, którą łatwo wziąć
    za pewnik."""
    wynik = {"wartosc": 0.0, "na_stanie": 0, "bez_ceny": 0}
    if not auto_id:
        return wynik
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT ilosc, cena_jednostkowa FROM magazyn_czesci WHERE auto_id=?", (auto_id,))
        wiersze = c.fetchall()

    for ilosc, cena in wiersze:
        ilosc = _na_liczbe(ilosc) or 0.0
        if ilosc <= 0:
            continue
        wynik["na_stanie"] += 1
        cena = _na_liczbe(cena)
        if cena is None:
            wynik["bez_ceny"] += 1
        else:
            wynik["wartosc"] += ilosc * cena
    wynik["wartosc"] = round(wynik["wartosc"], 2)
    return wynik


def pobierz_podsumowanie_zuzycia(auto_id) -> dict[int, dict[str, Any]]:
    """{magazyn_id: {"liczba", "ilosc", "koszt", "ostatnio"}} dla całego magazynu.

    Jedno zapytanie na pojazd, żeby karta pozycji na liście nie pytała bazy sama
    za siebie. `koszt` sumuje wyłącznie zużycia doliczone do serwisu."""
    if not auto_id:
        return {}
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT wcm.magazyn_id, wcm.ilosc_uzyta, wcm.koszt, w.data "
            "FROM wizyta_czesci_magazynu wcm "
            "JOIN wizyty w ON w.id = wcm.wizyta_id "
            "JOIN magazyn_czesci m ON m.id = wcm.magazyn_id WHERE m.auto_id=? "
            "UNION ALL "
            "SELECT hcm.magazyn_id, hcm.ilosc_uzyta, hcm.koszt, h.data "
            "FROM historia_czesci_magazynu hcm "
            "JOIN historia h ON h.id = hcm.historia_id "
            "JOIN magazyn_czesci m ON m.id = hcm.magazyn_id WHERE m.auto_id=?",
            (auto_id, auto_id)
        )
        wiersze = c.fetchall()

    wynik = {}
    for magazyn_id, ilosc, koszt, data in wiersze:
        pozycja = wynik.setdefault(magazyn_id, {"liczba": 0, "ilosc": 0.0, "koszt": 0.0, "ostatnio": None})
        pozycja["liczba"] += 1
        pozycja["ilosc"] += _na_liczbe(ilosc) or 0.0
        pozycja["koszt"] = round(pozycja["koszt"] + (_na_liczbe(koszt) or 0.0), 2)
        if data and (pozycja["ostatnio"] is None or parsuj_date(data) > parsuj_date(pozycja["ostatnio"])):
            pozycja["ostatnio"] = str(data)
    return wynik


def pobierz_historie_zuzycia(czesc_id) -> list[dict[str, Any]]:
    """Gdzie ta pozycja zeszła z magazynu — wizyty i pojedyncze wpisy razem, od
    najnowszego. Każdy element: {"zrodlo", "rekord_id", "data", "tytul",
    "opis", "ilosc", "koszt", "trasa"}; `trasa` prowadzi do edycji rekordu."""
    if not czesc_id:
        return []
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT w.id AS rekord_id, w.data, w.wykonawca, wcm.ilosc_uzyta, wcm.koszt, "
            "(SELECT GROUP_CONCAT(z.nazwa, ', ') FROM historia h JOIN zadania z ON z.id = h.zadanie_id "
            " WHERE h.wizyta_id = w.id) AS podzespoly "
            "FROM wizyta_czesci_magazynu wcm JOIN wizyty w ON w.id = wcm.wizyta_id "
            "WHERE wcm.magazyn_id=?",
            (czesc_id,)
        )
        wizyty = c.fetchall()
        c.execute(
            "SELECT h.id AS rekord_id, h.wizyta_id, h.data, h.wykonawca, hcm.ilosc_uzyta, hcm.koszt, "
            "z.nazwa AS podzespol "
            "FROM historia_czesci_magazynu hcm JOIN historia h ON h.id = hcm.historia_id "
            "JOIN zadania z ON z.id = h.zadanie_id "
            "WHERE hcm.magazyn_id=?",
            (czesc_id,)
        )
        wpisy = c.fetchall()

    wynik = []
    for r in wizyty:
        wynik.append({
            "zrodlo": "wizyty", "rekord_id": r["rekord_id"], "data": str(r["data"] or ""),
            "tytul": bez_emoji(r["podzespoly"]) or "Wizyta w warsztacie",
            "opis": "Wizyta w warsztacie" + (f" • {r['wykonawca']}" if r["wykonawca"] else ""),
            "ilosc": _na_liczbe(r["ilosc_uzyta"]) or 0.0, "koszt": _na_liczbe(r["koszt"]),
            "trasa": f"/wizyty/edytuj/{r['rekord_id']}",
        })
    for r in wpisy:
        trasa = f"/wizyty/edytuj/{r['wizyta_id']}" if r["wizyta_id"] else f"/wpis/edytuj/{r['rekord_id']}"
        wynik.append({
            "zrodlo": "historia", "rekord_id": r["rekord_id"], "data": str(r["data"] or ""),
            "tytul": bez_emoji(r["podzespol"]) or "Wpis serwisowy",
            "opis": "Wpis serwisowy" + (f" • {r['wykonawca']}" if r["wykonawca"] else ""),
            "ilosc": _na_liczbe(r["ilosc_uzyta"]) or 0.0, "koszt": _na_liczbe(r["koszt"]),
            "trasa": trasa,
        })
    wynik.sort(key=lambda w: (parsuj_date(w["data"]), w["rekord_id"]), reverse=True)
    return wynik


# ============================================================================
#  SEZONOWA ZMIANA OPON
# ============================================================================
# Zmiana opon to jedyne cykliczne przypomnienie, którego wykonanie ZMIENIA STAN
# w bazie: po niej na aucie stoi drugi komplet. Dopóki było zwykłym wpisem
# w kalendarzu, magazyn opon i tak trzeba było poprawić ręcznie w drugim
# miejscu — a że nikt tego nie robił, aplikacja przez pół roku twierdziła, że
# auto jeździ na zimówkach w lipcu.


def _docelowy_sezon(zamontowany_sezon, dzis=None):
    """Na co zmieniamy. Kierunek bierzemy z tego, co JEST na aucie — to jedyna
    pewna informacja. Dopiero gdy nic nie jest zamontowane (albo stoją opony
    całoroczne, które nie mają pary), decyduje kalendarz."""
    if zamontowany_sezon in SEZONY_PRZELACZALNE:
        return "Letnie" if zamontowany_sezon == "Zimowe" else "Zimowe"
    miesiac = (dzis or datetime.now()).month
    return "Zimowe" if miesiac in MIESIACE_ZIMOWE else "Letnie"


def pobierz_stan_opon(auto_id):
    """Co stoi na aucie i co czeka w piwnicy — jedno źródło dla kafelka kokpitu
    i dla samego przełączania. Zwraca None, gdy pojazd nie ma ani jednego
    zestawu (wtedy nie ma o czym mówić)."""
    if not auto_id:
        return None
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, sezon, rozmiar, marka_model, glebokosc_bieznika, zamontowane, os_montazu "
            "FROM zestawy_opon WHERE auto_id=? ORDER BY zamontowane DESC, id",
            (auto_id,)
        )
        wiersze = c.fetchall()
    if not wiersze:
        return None

    zestawy = [
        {"id": w[0], "sezon": str(w[1] or ""), "rozmiar": str(w[2] or ""),
         "marka_model": str(w[3] or ""), "bieznik": w[4],
         "zamontowany": bool(w[5]), "os": str(w[6] or "Wszystkie")}
        for w in wiersze
    ]
    zamontowane = [z for z in zestawy if z["zamontowany"]]
    biezniki = [float(z["bieznik"]) for z in zamontowane if z["bieznik"] not in (None, "")]
    sezon_teraz = zamontowane[0]["sezon"] if zamontowane else None
    docelowy = _docelowy_sezon(sezon_teraz)
    czeka = [z for z in zestawy if not z["zamontowany"] and z["sezon"] == docelowy]

    return {
        "zestawy": zestawy,
        "zamontowane": zamontowane,
        "sezon": sezon_teraz,
        "bieznik": min(biezniki) if biezniki else None,
        "docelowy_sezon": docelowy,
        "kandydaci": czeka,
        "ma_para": bool(czeka),
    }


def przelacz_zestaw_sezonowy(auto_id, docelowy_sezon=None):
    """Zdejmuje obecny komplet i montuje ten z drugiego sezonu.

    Zwraca słownik z opisem tego, co się stało (`ok`, `z`, `na`, `powod`) —
    interfejs musi umieć powiedzieć „zmieniono z Zimowych na Letnie” ALBO
    „nie ma czego zamontować”, a nie tylko cicho przesunąć termin.

    Kandydatów rozstrzygamy po najgrubszym bieżniku: jeśli ktoś trzyma dwa
    komplety letnich, na auto ma trafić ten lepszy, a nie ten z niższym ID.
    """
    stan = pobierz_stan_opon(auto_id)
    if not stan:
        return {"ok": False, "powod": "brak_zestawow"}

    docelowy = docelowy_sezon or stan["docelowy_sezon"]
    kandydaci = [z for z in stan["zestawy"] if not z["zamontowany"] and z["sezon"] == docelowy]
    if not kandydaci:
        return {"ok": False, "powod": "brak_kompletu", "docelowy_sezon": docelowy,
                "z": stan["sezon"]}

    def waga(z):
        try:
            return -float(z["bieznik"])
        except (TypeError, ValueError):
            return 0.0

    nowy = sorted(kandydaci, key=lambda z: (waga(z), z["id"]))[0]

    with polacz_baze() as conn:
        conn.execute("UPDATE zestawy_opon SET zamontowane=0 WHERE auto_id=?", (auto_id,))
        conn.execute(
            "UPDATE zestawy_opon SET zamontowane=1, os_montazu='Wszystkie' WHERE id=?",
            (nowy["id"],)
        )

    return {
        "ok": True,
        "z": stan["sezon"],
        "na": nowy["sezon"],
        "zestaw_id": nowy["id"],
        "opis_zestawu": " ".join(x for x in (nowy["marka_model"], nowy["rozmiar"]) if x),
        "bieznik": nowy["bieznik"],
    }


__all__ = [
    "POWIAZANIA_MAGAZYNU",
    "_docelowy_sezon",
    "_pobierz_uzyte_czesci",
    "_przywroc_czesci",
    "_przywroc_powiazania_czesci_wpisow",
    "_rozlicz_czesci",
    "_zdejmij_powiazania_czesci_wpisow",
    "cena_jednostkowa_z_zakupu",
    "cena_zuzycia",
    "koszt_doliczony",
    "pobierz_czesci_do_zuzycia",
    "pobierz_historie_zuzycia",
    "pobierz_podsumowanie_zuzycia",
    "pobierz_stan_magazynu",
    "pobierz_stan_opon",
    "pobierz_uzyte_czesci_wizyty",
    "pobierz_uzyte_czesci_wpisu",
    "pobierz_wartosc_magazynu",
    "pobierz_zuzycie_czesci",
    "pobierz_zuzycie_rekordow",
    "przelacz_zestaw_sezonowy",
    "przywroc_czesci_wizyty",
    "przywroc_czesci_wpisu",
    "rozlicz_czesci_z_magazynu",
    "rozlicz_czesci_z_magazynu_wpisu",
    "srednia_cena_jednostkowa",
    "suma_kosztu_zuzycia",
    "usun_czesc_magazynu_z_cofnieciem",
    "usun_wiele_czesci_magazynu_z_cofnieciem",
    "wycen_zuzycie",
]
