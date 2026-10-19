"""Dolewki płynów (N-12): płyn, ilość, przebieg, opcjonalnie z półki magazynu (stan maleje) i z kosztem
(powiązany Inny koszt w KATEGORIA_INNE_DOLEWKI). Zużycie l/1000 km w okresach między wymianami —
wymiany to wpisy podzespołów rozpoznanych po nazwie (`RODZAJE_PLYNOW`). Decyzje: claude/dolewki-plynow.md."""

import sqlite3
from datetime import datetime, timedelta
from statistics import median
from typing import Any

from date import na_iso, parsuj_date

from .stale import KATEGORIA_INNE_DOLEWKI, OCENA_OLEJU, OCENA_UKLADU, PLYN_OLEJ, RODZAJE_PLYNOW, TYPY_PALIWA_ELEKTRYCZNE
from .polaczenie import polacz_baze
from .pomocnicze import _na_liczbe, klucz_nazwy, liczba_na_tekst, liczba_z_odmiana, normalizuj_nazwe
from .ustawienia import pobierz_moje_imie
from .jednostki import na_jednostke_dystansu, slowo_dystansu, tekst_dystansu
from .synchronizacja import czy_moge_dodawac, czy_moge_zmieniac_rekord, usun_nagrobek, zarejestruj_nagrobek
from .zalaczniki import (
    odloz_zalaczniki_rekordow, przywroc_odlozone_zalaczniki, skasuj_odlozone_zalaczniki, usun_plik_zalacznika,
    usun_zalaczniki_rekordow,
)
from .przebieg import pobierz_aktualny_przebieg


MIN_KM_POMIARU = 1000             # krótszy pomiar to szum (dolewka „do kreski” tuż po wymianie)
PROG_ZUZYCIA_PODWYZSZONEGO = 0.15  # l/1000 km — do tylu mechanicy uznają zużycie za normę
PROG_ZUZYCIA_WYSOKIEGO = 0.5      # tyle dopuszcza instrukcja wielu aut, na co dzień to już nie norma
KROTNOSC_WZROSTU = 1.5
MIN_WZROST = 0.1                  # l/1000 km
DNI_UBYTKU_UKLADU = 365
DOLEWEK_UBYTKU_UKLADU = 2
MAKS_ILOSC_DOLEWKI = 30.0         # l — więcej to już nie dolewka, tylko pomyłka w polu
SZYBKIE_ILOSCI = (0.25, 0.5, 1.0)

STATUS_NORMA, STATUS_PODWYZSZONE, STATUS_WYSOKIE = "ok", "podwyzszone", "wysokie"

_BEZ_OGONKOW = str.maketrans("ąćęłńóśźż", "acelnoszz")


# ============================================================================
#  SŁOWNIK I TEKSTY
# ============================================================================

def nazwa_plynu(plyn) -> str:
    return RODZAJE_PLYNOW.get(plyn, {}).get("nazwa", "Płyn")


def tekst_litrow(litry) -> str:
    """„0,5 l”, „0,25 l”, „1 l” — bez zbędnych zer."""
    tekst = liczba_na_tekst(round(float(litry or 0), 2), 2) or "0"
    return f"{tekst.rstrip('0').rstrip(',') if ',' in tekst else tekst} l"


def tekst_zuzycia(na_1000_km, jednostka=None) -> str:
    """„0,18 l/1000 km” (albo na 1000 mi) — zużycie podane NA kilometr przeliczone na jednostkę."""
    wartosc = na_jednostke_dystansu(na_1000_km, jednostka)
    return f"{liczba_na_tekst(wartosc or 0, 2)} l/1000 {slowo_dystansu('skrot', jednostka)}"


def nazwa_kosztu_dolewki(plyn, ilosc, produkt=None) -> str:
    nazwa = f"Dolewka: {RODZAJE_PLYNOW.get(plyn, {}).get('w_zdaniu', 'płyn')} {tekst_litrow(ilosc)}"
    return f"{nazwa} ({produkt})" if produkt else nazwa


def ilosc_w_jednostce(litry, jednostka) -> float:
    """Litry dolewki w jednostce pozycji magazynu (l albo ml)."""
    return round(float(litry or 0) * (1000 if str(jednostka or "").strip().lower() == "ml" else 1), 3)


def _czysta_nazwa(tekst):
    return klucz_nazwy(tekst).translate(_BEZ_OGONKOW)


# ============================================================================
#  ODCZYT
# ============================================================================

_ZAPYTANIE = (
    "SELECT d.*, m.nazwa AS magazyn_nazwa, m.jednostka AS magazyn_jednostka, k.kwota AS koszt "
    "FROM dolewki d LEFT JOIN magazyn_czesci m ON m.id = d.magazyn_id LEFT JOIN inne_koszty k ON k.id = d.koszt_id "
)


def _dolewka(r) -> dict[str, Any]:
    d = dict(r)
    data = parsuj_date(d["data"])
    d["data_obj"] = None if data == datetime.min.date() else data
    d["przebieg"] = int(d["przebieg"] or 0)
    d["ilosc"] = float(d["ilosc"] or 0)
    d["koszt"] = _na_liczbe(d["koszt"])
    return d


def pobierz_dolewke(dolewka_id) -> dict[str, Any] | None:
    if not dolewka_id:
        return None
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        w = conn.execute(_ZAPYTANIE + "WHERE d.id=?", (dolewka_id,)).fetchone()
    return _dolewka(w) if w else None


def pobierz_dolewki(auto_id, plyn=None) -> list[dict[str, Any]]:
    """Dolewki pojazdu (jednego płynu albo wszystkie) od najstarszej: data, potem licznik."""
    if not auto_id:
        return []
    warunek, parametry = ("WHERE d.auto_id=? AND d.plyn=? ", (auto_id, plyn)) if plyn else ("WHERE d.auto_id=? ", (auto_id,))
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        wiersze = conn.execute(_ZAPYTANIE + warunek + "ORDER BY d.data_iso, d.przebieg, d.id", parametry).fetchall()
    return [_dolewka(w) for w in wiersze]


def dolewka_kosztu(koszt_id) -> dict[str, Any] | None:
    """Dolewka, do której należy ten Inny koszt (formularz kosztu odsyła do niej) — albo None."""
    if not koszt_id:
        return None
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        w = conn.execute(_ZAPYTANIE + "WHERE d.koszt_id=? ORDER BY d.id LIMIT 1", (koszt_id,)).fetchone()
    return _dolewka(w) if w else None


def plyny_pojazdu(auto_id) -> list[str]:
    """Płyny do wyboru: olej nie dla elektryka, AdBlue tylko dla diesla — chyba że auto już ma ich dolewki."""
    if not auto_id:
        return list(RODZAJE_PLYNOW)
    with polacz_baze() as conn:
        w = conn.execute("SELECT typ_paliwa FROM samochody WHERE id=?", (auto_id,)).fetchone()
        uzyte = {r[0] for r in conn.execute("SELECT DISTINCT plyn FROM dolewki WHERE auto_id=?", (auto_id,))}
    typ = str((w[0] if w else "") or "")
    wynik = []
    for plyn, opis in RODZAJE_PLYNOW.items():
        pasuje = not (opis.get("bez_elektryka") and typ in TYPY_PALIWA_ELEKTRYCZNE) and \
            not (opis.get("tylko_diesel") and typ != "Diesel")
        if pasuje or plyn in uzyte:
            wynik.append(plyn)
    return wynik


def pozycje_magazynu_dla_plynu(auto_id, plyn) -> list[dict[str, Any]]:
    """Pozycje magazynu w litrach albo mililitrach — najpierw z kategorii płynu, potem reszta, po nazwie."""
    if not auto_id:
        return []
    kategoria = RODZAJE_PLYNOW.get(plyn, {}).get("magazyn")
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        wiersze = conn.execute(
            "SELECT id, nazwa, kategoria, ilosc, jednostka, cena_jednostkowa FROM magazyn_czesci "
            "WHERE auto_id=? AND LOWER(TRIM(COALESCE(jednostka, ''))) IN ('l', 'ml')", (auto_id,)).fetchall()
    pozycje = [{"id": r["id"], "nazwa": str(r["nazwa"] or ""), "kategoria": r["kategoria"],
                "ilosc": _na_liczbe(r["ilosc"]) or 0.0, "jednostka": str(r["jednostka"] or "l").strip().lower(),
                "cena_jednostkowa": _na_liczbe(r["cena_jednostkowa"])} for r in wiersze]
    pozycje.sort(key=lambda p: (p["kategoria"] != kategoria, p["nazwa"].lower()))
    return pozycje


# ============================================================================
#  ZAPIS I USUWANIE
# ============================================================================

def blad_dolewki(dane) -> str | None:
    """Treść błędu albo None: płyn ze słownika, data, przebieg > 0, ilość w (0, MAKS_ILOSC_DOLEWKI]."""
    if dane.get("plyn") not in RODZAJE_PLYNOW:
        return "Wybierz płyn"
    if parsuj_date(dane.get("data")) == datetime.min.date():
        return "Podaj datę"
    ilosc = _na_liczbe(dane.get("ilosc"))
    if ilosc is None or ilosc <= 0:
        return "Podaj ilość"
    if ilosc > MAKS_ILOSC_DOLEWKI:
        return "Za dużo jak na dolewkę"
    if (_na_liczbe(dane.get("przebieg")) or 0) <= 0:
        return "Podaj przebieg"
    return None


def zapisz_dolewke(auto_id, dane, dolewka_id=None) -> int | None:
    """Nowa albo poprawiana dolewka; id albo None (błąd danych, brak prawa, wpis zniknął). `dane`: data,
    przebieg (km), plyn, ilosc (l), produkt, magazyn_id, koszt (None = bez kosztu). Jedna transakcja:
    zwrot poprzedniego zdjęcia ze stanu, nowe (najwyżej tyle, ile leży), powiązany Inny koszt."""
    if not auto_id or blad_dolewki(dane):
        return None
    stary = None
    if dolewka_id:
        with polacz_baze() as conn:
            conn.row_factory = sqlite3.Row
            stary = conn.execute("SELECT * FROM dolewki WHERE id=? AND auto_id=?", (dolewka_id, auto_id)).fetchone()
        if not stary or not czy_moge_zmieniac_rekord(auto_id, "dolewki", stary["dodane_przez"]):
            return None
    elif not czy_moge_dodawac(auto_id):
        return None

    data = str(dane["data"]).strip()
    plyn, ilosc = dane["plyn"], round(float(_na_liczbe(dane["ilosc"])), 3)
    przebieg = int(_na_liczbe(dane["przebieg"]))
    produkt = normalizuj_nazwe(dane.get("produkt")) or None
    magazyn_id = dane.get("magazyn_id") or None
    koszt = _na_liczbe(dane.get("koszt"))
    koszt = round(koszt, 2) if koszt and koszt > 0 else None
    ja, teraz = pobierz_moje_imie(), datetime.now().strftime("%d.%m.%Y %H:%M")
    nagrobek_kosztu, pliki_kosztu = None, []

    with polacz_baze() as conn:
        c = conn.cursor()
        if stary and stary["magazyn_id"] and stary["ilosc_magazynu"]:
            c.execute("UPDATE magazyn_czesci SET ilosc = ilosc + ? WHERE id=?", (stary["ilosc_magazynu"], stary["magazyn_id"]))
        ilosc_magazynu = None
        if magazyn_id:
            pozycja = c.execute("SELECT ilosc, jednostka FROM magazyn_czesci WHERE id=? AND auto_id=?",
                                (magazyn_id, auto_id)).fetchone()
            if pozycja:
                ilosc_magazynu = round(min(ilosc_w_jednostce(ilosc, pozycja[1]), max(0.0, float(pozycja[0] or 0))), 3)
                c.execute("UPDATE magazyn_czesci SET ilosc = MAX(0, ilosc - ?) WHERE id=?", (ilosc_magazynu, magazyn_id))
            else:
                magazyn_id = None

        koszt_id = stary["koszt_id"] if stary else None
        if koszt_id and not c.execute("SELECT 1 FROM inne_koszty WHERE id=?", (koszt_id,)).fetchone():
            koszt_id = None
        nazwa = nazwa_kosztu_dolewki(plyn, ilosc, produkt)
        if koszt and koszt_id:
            c.execute("UPDATE inne_koszty SET data=?, data_iso=?, kategoria=?, nazwa=?, kwota=?, zmodyfikowane_przez=?, "
                      "data_modyfikacji=? WHERE id=?",
                      (data, na_iso(data), KATEGORIA_INNE_DOLEWKI, nazwa, koszt, ja, teraz, koszt_id))
        elif koszt:
            koszt_id = c.execute(
                "INSERT INTO inne_koszty (auto_id, data, data_iso, kategoria, nazwa, kwota, dodane_przez) "
                "VALUES (?,?,?,?,?,?,?)", (auto_id, data, na_iso(data), KATEGORIA_INNE_DOLEWKI, nazwa, koszt, ja)).lastrowid
        elif koszt_id:
            nagrobek_kosztu = c.execute("SELECT zdalne_id FROM inne_koszty WHERE id=?", (koszt_id,)).fetchone()[0]
            pliki_kosztu = usun_zalaczniki_rekordow(conn, "inne_koszty", [koszt_id])
            c.execute("DELETE FROM inne_koszty WHERE id=?", (koszt_id,))
            koszt_id = None

        wartosci = (data, na_iso(data), przebieg, plyn, ilosc, produkt, magazyn_id, ilosc_magazynu, koszt_id)
        if stary:
            c.execute("UPDATE dolewki SET data=?, data_iso=?, przebieg=?, plyn=?, ilosc=?, produkt=?, magazyn_id=?, "
                      "ilosc_magazynu=?, koszt_id=?, zmodyfikowane_przez=?, data_modyfikacji=? WHERE id=?",
                      wartosci + (ja, teraz, dolewka_id))
            wynik = dolewka_id
        else:
            wynik = c.execute(
                "INSERT INTO dolewki (auto_id, data, data_iso, przebieg, plyn, ilosc, produkt, magazyn_id, ilosc_magazynu, "
                "koszt_id, dodane_przez) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (auto_id,) + wartosci + (ja,)).lastrowid

    # Nagrobek otwiera własne połączenie — dopiero po zatwierdzeniu transakcji.
    if nagrobek_kosztu:
        zarejestruj_nagrobek("inne_koszty", nagrobek_kosztu, auto_id)
    for sciezka in pliki_kosztu:
        usun_plik_zalacznika(sciezka)
    return wynik


def _wstaw(conn, tabela, wiersz):
    nazwy = [k for k in wiersz if k != "id"]
    return conn.execute(f"INSERT INTO {tabela} ({','.join(nazwy)}) VALUES ({','.join('?' * len(nazwy))})",
                        tuple(wiersz[k] for k in nazwy)).lastrowid


def usun_dolewke_z_cofnieciem(dolewka_id) -> dict[str, Any] | None:
    """Usuwa dolewkę z jej kosztem, oddaje litry na półkę. {"cofnij", "finalizuj", "dane"} jak
    usun_z_cofnieciem — cofnięcie wstawia oba wiersze od nowa (nowe id, ten sam `zdalne_id`)."""
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        w = conn.execute("SELECT * FROM dolewki WHERE id=?", (dolewka_id,)).fetchone() if dolewka_id else None
        if not w:
            return None
        dane = dict(w)
        wk = conn.execute("SELECT * FROM inne_koszty WHERE id=?", (dane["koszt_id"],)).fetchone() if dane["koszt_id"] else None
        koszt = dict(wk) if wk else None
    if not czy_moge_zmieniac_rekord(dane["auto_id"], "dolewki", dane.get("dodane_przez")):
        return None

    pliki = odloz_zalaczniki_rekordow("inne_koszty", [koszt["id"]]) if koszt else {}
    with polacz_baze() as conn:
        if dane["magazyn_id"] and dane["ilosc_magazynu"]:
            conn.execute("UPDATE magazyn_czesci SET ilosc = ilosc + ? WHERE id=?", (dane["ilosc_magazynu"], dane["magazyn_id"]))
        conn.execute("DELETE FROM dolewki WHERE id=?", (dolewka_id,))
        if koszt:
            conn.execute("DELETE FROM inne_koszty WHERE id=?", (koszt["id"],))
    zdalne = [(t, r["zdalne_id"]) for t, r in (("dolewki", dane), ("inne_koszty", koszt)) if r and r.get("zdalne_id")]
    for tabela, zdalne_id in zdalne:
        zarejestruj_nagrobek(tabela, zdalne_id, dane["auto_id"])

    stan = {"cofniete": False, "trwale": False}

    def cofnij():
        if stan["cofniete"] or stan["trwale"]:
            return
        stan["cofniete"] = True
        for _tabela, zdalne_id in zdalne:
            usun_nagrobek(zdalne_id)
        wiersz = dict(dane)
        with polacz_baze() as conn:
            wiersz["koszt_id"] = _wstaw(conn, "inne_koszty", koszt) if koszt else None
            if wiersz["magazyn_id"] and not conn.execute("SELECT 1 FROM magazyn_czesci WHERE id=?",
                                                         (wiersz["magazyn_id"],)).fetchone():
                wiersz["magazyn_id"] = None
            _wstaw(conn, "dolewki", wiersz)
            if wiersz["magazyn_id"] and wiersz["ilosc_magazynu"]:
                conn.execute("UPDATE magazyn_czesci SET ilosc = MAX(0, ilosc - ?) WHERE id=?",
                             (wiersz["ilosc_magazynu"], wiersz["magazyn_id"]))
        if koszt:
            przywroc_odlozone_zalaczniki(pliki, {koszt["id"]: wiersz["koszt_id"]})

    def finalizuj():
        if stan["cofniete"]:
            return
        stan["trwale"] = True
        if pliki:
            skasuj_odlozone_zalaczniki(pliki)

    return {"cofnij": cofnij, "finalizuj": finalizuj, "dane": dane}


def powiazania_kosztow_dolewek(koszt_ids) -> dict[int, list[int]]:
    """{koszt_id: [id dolewek]} — zbierane przed usunięciem Innych kosztów (ON DELETE SET NULL), żeby
    cofnięcie, które wstawia koszt pod nowym id, dowiązało dolewki z powrotem."""
    ids = [i for i in koszt_ids or [] if i is not None]
    if not ids:
        return {}
    with polacz_baze() as conn:
        wiersze = conn.execute(f"SELECT koszt_id, id FROM dolewki WHERE koszt_id IN ({','.join('?' * len(ids))})",
                               tuple(ids)).fetchall()
    wynik = {}
    for koszt_id, dolewka_id in wiersze:
        wynik.setdefault(koszt_id, []).append(dolewka_id)
    return wynik


def przywroc_powiazania_kosztow(powiazania, mapa_id) -> None:
    """Odwrotność powiazania_kosztow_dolewek: `mapa_id` {stare id kosztu: nowe}."""
    if not powiazania:
        return
    with polacz_baze() as conn:
        for stary, dolewki in powiazania.items():
            nowy = (mapa_id or {}).get(stary)
            if nowy:
                conn.execute(f"UPDATE dolewki SET koszt_id=? WHERE koszt_id IS NULL AND id IN ({','.join('?' * len(dolewki))})",
                             (nowy, *dolewki))


# ============================================================================
#  ZUŻYCIE MIĘDZY WYMIANAMI
# ============================================================================

def _pasuje(nazwa, opis):
    tekst = _czysta_nazwa(nazwa)
    return any(c in tekst for c in opis.get("wymiana") or ()) and not any(c in tekst for c in opis.get("bez") or ())


def _dane_wymian(auto_id):
    """{zadanie_id: {"nazwa", "punkty": [(przebieg, data)]}} — wymiany z historii; podzespół bez historii
    z własnym licznikiem (stary zapis) daje jeden punkt."""
    with polacz_baze() as conn:
        wiersze = conn.execute(
            "SELECT z.id, z.nazwa, z.data, z.przebieg, h.data, h.przebieg FROM zadania z "
            "LEFT JOIN historia h ON h.zadanie_id = z.id WHERE z.auto_id=?", (auto_id,)).fetchall()
    zadania = {}
    for zid, nazwa, z_data, z_przebieg, h_data, h_przebieg in wiersze:
        z = zadania.setdefault(zid, {"nazwa": str(nazwa or ""), "punkty": [], "wlasny": (z_przebieg, z_data)})
        if int(h_przebieg or 0) > 0:
            z["punkty"].append((int(h_przebieg), h_data))
    for z in zadania.values():
        if not z["punkty"] and int(z["wlasny"][0] or 0) > 0:
            z["punkty"].append((int(z["wlasny"][0]), z["wlasny"][1]))
    return zadania


def zadania_wymiany(plyn, zadania) -> list[int]:
    """Id podzespołów, których wymiany wyznaczają okresy płynu (`_dane_wymian`)."""
    opis = RODZAJE_PLYNOW.get(plyn, {})
    pasujace = [zid for zid, z in zadania.items() if _pasuje(z["nazwa"], opis)]
    pierwsze = [zid for zid in pasujace if any(c in _czysta_nazwa(zadania[zid]["nazwa"]) for c in opis.get("pierwszenstwo") or ())]
    return sorted(pierwsze or pasujace, key=lambda zid: zadania[zid]["nazwa"].lower())


def _okresy(dolewki, punkty, akt):
    """Okresy od wymiany do wymiany; pierwszy zaczyna się ostatnią wymianą przed pierwszą dolewką
    (wcześniejszych nie było jak mierzyć), a bez niej — pierwszą dolewką, której litry są wtedy tylko
    punktem odniesienia. Pomiar trwa do OSTATNIEJ dolewki okresu: kilometrów po niej nikt nie zmierzył."""
    z_licznikiem = sorted((d for d in dolewki if d["przebieg"] > 0), key=lambda d: (d["przebieg"], d["data_iso"] or "", d["id"]))
    if not z_licznikiem:
        return []
    pierwsza = z_licznikiem[0]["przebieg"]
    przed = [p for p in punkty if p[0] <= pierwsza]
    starty = ([przed[-1]] if przed else [None]) + [p for p in punkty if p[0] > pierwsza]
    wynik = []
    for i, start in enumerate(starty):
        koniec = starty[i + 1] if i + 1 < len(starty) else None
        km_od = start[0] if start else pierwsza
        km_do = koniec[0] if koniec else None
        w_okresie = [d for d in z_licznikiem if d["przebieg"] >= km_od and (km_do is None or d["przebieg"] < km_do)]
        liczone = w_okresie[1:] if start is None else w_okresie
        km_okresu = max(0, (km_do if km_do is not None else max(akt, km_od)) - km_od)
        km_pomiaru = liczone[-1]["przebieg"] - km_od if liczone else None
        if koniec is not None and (km_pomiaru is None or km_pomiaru < MIN_KM_POMIARU):
            # Zamknięty okres bez dolewek albo z dolewkami tuż po wymianie — reszta przejechana bez dolewania.
            km_pomiaru = km_okresu
        litry = round(sum(d["ilosc"] for d in liczone), 3)
        na_1000 = round(litry / km_pomiaru * 1000, 3) if km_pomiaru and km_pomiaru >= MIN_KM_POMIARU else None
        wynik.append({
            "od_przebieg": km_od, "od_data": start[1] if start else w_okresie[0]["data"], "od_dolewki": start is None,
            "do_przebieg": km_do, "do_data": koniec[1] if koniec else None, "trwa": koniec is None,
            "dolewki": w_okresie, "litry": litry, "litry_wszystkie": round(sum(d["ilosc"] for d in w_okresie), 3),
            "km_okresu": km_okresu, "km_pomiaru": km_pomiaru, "na_1000": na_1000,
        })
    return wynik


def status_zuzycia(na_1000) -> str | None:
    """Ocena zużycia oleju (l/1000 km): STATUS_NORMA, STATUS_PODWYZSZONE, STATUS_WYSOKIE albo None."""
    if na_1000 is None:
        return None
    if na_1000 >= PROG_ZUZYCIA_WYSOKIEGO:
        return STATUS_WYSOKIE
    return STATUS_PODWYZSZONE if na_1000 >= PROG_ZUZYCIA_PODWYZSZONEGO else STATUS_NORMA


def _zuzycie(plyn, dolewki, zadania, akt, dzis):
    opis = RODZAJE_PLYNOW[plyn]
    ids = zadania_wymiany(plyn, zadania) if opis.get("wymiana") else []
    punkty = sorted({p[0]: p for zid in ids for p in zadania[zid]["punkty"]}.values())
    okresy = _okresy(dolewki, punkty, akt)
    mierzalne = [o for o in okresy if o["na_1000"] is not None]
    biezacy = okresy[-1] if okresy and okresy[-1]["trwa"] else None
    teraz = mierzalne[-1] if mierzalne else None
    wczesniej = [o["na_1000"] for o in mierzalne[:-1]]
    poprzednio = round(median(wczesniej), 3) if wczesniej else None
    na_1000 = teraz["na_1000"] if teraz else None
    ocena = opis.get("ocena")
    rosnie = (ocena == OCENA_OLEJU and na_1000 is not None and poprzednio is not None
              and na_1000 >= poprzednio * KROTNOSC_WZROSTU and na_1000 - poprzednio >= MIN_WZROST
              and na_1000 >= PROG_ZUZYCIA_PODWYZSZONEGO)
    od_roku = (dzis - timedelta(days=DNI_UBYTKU_UKLADU))
    w_roku = sum(1 for d in dolewki if d["data_obj"] and d["data_obj"] >= od_roku)
    return {
        "plyn": plyn, "nazwa": opis["nazwa"], "ocena": ocena, "zadania": [zadania[z]["nazwa"] for z in ids],
        "zadania_id": ids, "okresy": okresy, "biezacy": biezacy, "na_1000": na_1000,
        "z_biezacego": teraz is not None and teraz is biezacy, "poprzednio": poprzednio, "rosnie": rosnie,
        "status": status_zuzycia(na_1000) if ocena == OCENA_OLEJU else None,
        "dolewek_w_roku": w_roku, "ubytek": ocena == OCENA_UKLADU and w_roku >= DOLEWEK_UBYTKU_UKLADU,
        "liczba": len(dolewki), "litry_razem": round(sum(d["ilosc"] for d in dolewki), 3),
        "ostatnia": dolewki[-1] if dolewki else None,
        "bez_przebiegu": [d for d in dolewki if d["przebieg"] <= 0],
    }


def zuzycie_plynow(auto_id, dzis=None) -> dict[str, dict[str, Any]]:
    """{płyn: zużycie} dla płynów z co najmniej jedną dolewką. Zużycie: okresy (od najstarszego), bieżący
    okres, `na_1000` (l/1000 km z ostatniego zmierzonego okresu), `poprzednio` (mediana wcześniejszych),
    `rosnie`, `status` (olej), `ubytek` (układ zamknięty), podzespoły wymian."""
    if not auto_id:
        return {}
    dolewki = pobierz_dolewki(auto_id)
    if not dolewki:
        return {}
    dzis = dzis or datetime.now().date()
    zadania = _dane_wymian(auto_id)
    akt = max([int(pobierz_aktualny_przebieg(auto_id) or 0)] + [d["przebieg"] for d in dolewki])
    wynik = {}
    for plyn in RODZAJE_PLYNOW:
        wlasne = [d for d in dolewki if d["plyn"] == plyn]
        if wlasne:
            wynik[plyn] = _zuzycie(plyn, wlasne, zadania, akt, dzis)
    return wynik


def zuzycie_plynu(auto_id, plyn, dzis=None) -> dict[str, Any] | None:
    return zuzycie_plynow(auto_id, dzis).get(plyn)


def sygnaly_plynow(auto_id, dzis=None, zuzycie=None) -> list[dict[str, Any]]:
    """Przypomnienia w dzwonku: olej — wysokie albo rosnące zużycie, układ zamknięty — powtarzające się
    dolewki w ostatnim roku. Klucz oleju niesie początek okresu, więc po wymianie sygnał startuje od nowa."""
    wynik = []
    for plyn, z in (zuzycie if zuzycie is not None else zuzycie_plynow(auto_id, dzis)).items():
        opis = RODZAJE_PLYNOW[plyn]
        if z["ocena"] == OCENA_OLEJU and z["na_1000"] is not None and (z["status"] == STATUS_WYSOKIE or z["rosnie"]):
            start = z["biezacy"]["od_przebieg"] if z["biezacy"] else 0
            if z["rosnie"]:
                rodzaj, tytul = "rosnie", "Zużycie oleju rośnie"
                opis_s = (f"{tekst_zuzycia(z['poprzednio'])} we wcześniejszych okresach, teraz "
                          f"{tekst_zuzycia(z['na_1000'])} — to najwcześniejszy sygnał zużycia silnika.")
            else:
                rodzaj, tytul = "wysokie", "Wysokie zużycie oleju"
                opis_s = (f"{tekst_zuzycia(z['na_1000'])} — za normę uchodzi do ok. "
                          f"{tekst_zuzycia(PROG_ZUZYCIA_PODWYZSZONEGO)}. Warto sprawdzić silnik.")
            wynik.append({"typ": "plyn", "plyn": plyn, "tytul": tytul, "opis": opis_s, "status": "pilne",
                          "trasa": f"/dolewki/{plyn}", "klucz": f"plyn:{plyn}:{rodzaj}:{start}"})
        elif z["ubytek"]:
            wynik.append({
                "typ": "plyn", "plyn": plyn, "tytul": f"Ubywa: {opis['w_zdaniu']}",
                "opis": (f"{liczba_z_odmiana(z['dolewek_w_roku'], 'dolewka', 'dolewki', 'dolewek')} w ostatnim roku — "
                         f"w zamkniętym układzie nie powinno go ubywać. {opis.get('porada', '')}").strip(),
                "status": "pilne", "trasa": f"/dolewki/{plyn}", "klucz": f"plyn:{plyn}:ubytek",
            })
    return wynik


def kafel_zuzycia_oleju(auto_id) -> dict[str, Any] | None:
    """Kafelek „Zużycie oleju”: None — nie dotyczy (elektryk bez dolewek oleju), {"brak": True} — bez
    dolewek, inaczej zużycie oleju z `zuzycie_plynow`."""
    if PLYN_OLEJ not in plyny_pojazdu(auto_id):
        return None
    z = zuzycie_plynu(auto_id, PLYN_OLEJ)
    return z if z else {"brak": True}


def zuzycie_przy_zadaniach(auto_id, zuzycie=None) -> dict[int, dict[str, Any]]:
    """{zadanie_id: zużycie płynu} dla podzespołów, których wymiany wyznaczają okresy (karta w Serwisie)."""
    wynik = {}
    for z in (zuzycie if zuzycie is not None else zuzycie_plynow(auto_id)).values():
        for zid in z["zadania_id"]:
            wynik.setdefault(zid, z)
    return wynik


def opis_okresu(okres, jednostka=None) -> str:
    """„dolano 0,8 l na 4 200 km” — litry liczone do zużycia i kilometry okresu."""
    km = tekst_dystansu(okres["km_okresu"] or 0, 0, jednostka)
    if not okres["dolewki"]:
        return f"bez dolewek na {km}"
    return f"dolano {tekst_litrow(okres['litry_wszystkie'])} na {km}"


__all__ = [
    "DNI_UBYTKU_UKLADU",
    "DOLEWEK_UBYTKU_UKLADU",
    "KROTNOSC_WZROSTU",
    "MAKS_ILOSC_DOLEWKI",
    "MIN_KM_POMIARU",
    "MIN_WZROST",
    "PROG_ZUZYCIA_PODWYZSZONEGO",
    "PROG_ZUZYCIA_WYSOKIEGO",
    "STATUS_NORMA",
    "STATUS_PODWYZSZONE",
    "STATUS_WYSOKIE",
    "SZYBKIE_ILOSCI",
    "blad_dolewki",
    "dolewka_kosztu",
    "ilosc_w_jednostce",
    "kafel_zuzycia_oleju",
    "nazwa_kosztu_dolewki",
    "nazwa_plynu",
    "opis_okresu",
    "plyny_pojazdu",
    "pobierz_dolewke",
    "pobierz_dolewki",
    "powiazania_kosztow_dolewek",
    "pozycje_magazynu_dla_plynu",
    "przywroc_powiazania_kosztow",
    "status_zuzycia",
    "sygnaly_plynow",
    "tekst_litrow",
    "tekst_zuzycia",
    "usun_dolewke_z_cofnieciem",
    "zadania_wymiany",
    "zapisz_dolewke",
    "zuzycie_plynow",
    "zuzycie_plynu",
    "zuzycie_przy_zadaniach",
]
