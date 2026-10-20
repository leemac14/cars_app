"""Zdrowie danych (N-08): nieścisłości, które aplikacja wykrywa na różnych ekranach, w jednym
miejscu — pozycja ma klucz do „To nie błąd” i trasę do wpisu. Liczy `zdrowie_danych`, zdania
składa utils/zdrowie_danych.py; decyzje — archiwum `zdrowie-danych`."""

import os
import sqlite3
from datetime import date
from typing import Any

from date import parsuj_date

from .stale import (
    ENERGIA_PRAD, RODZAJE_PLYNOW, STATUS_POJAZDU_SPRZEDANY, TERMINY_DOKUMENTOW, TERMINY_WYMAGANE_W_KONDYCJI,
    TYPY_PALIWA_DWUZRODLOWE, TYPY_PALIWA_ELEKTRYCZNE, ZRODLA_ODCZYTU, ZRODLO_ODCZYTU_DOMYSLNE,
)
from .pamiec import z_pamieci
from .polaczenie import polacz_baze
from .ustawienia import pobierz_ustawienia_zdrowia, zapisz_ustawienia_zdrowia
from .synchronizacja import czy_tylko_podglad
from .energia import domyslny_rodzaj_energii
from .zalaczniki import _policz_pliki_dokumentu, pelna_sciezka_zalacznika, sciezka_pliku_zalacznika
from .dokumenty import etykieta_dokumentu
from .przebieg import pobierz_pelna_historie_przebiegu
from .nazwy import znajdz_duplikaty_nazw
from .kosz_wpisow import usun_do_kosza
from .koszty import CENY_ODNIESIENIA, nietypowa_cena
from .awarie import naprawy_bez_rodzaju


# Sekcje ekranu w tej kolejności: najpierw to, co psuje wszystkie liczby (licznik, daty,
# ceny), na końcu braki w opisie auta.
SPRAWDZENIA_ZDROWIA = {
    "licznik": "Cofki i skoki licznika",
    "przyszlosc": "Wpisy z przyszłości",
    "cena": "Nietypowe ceny",
    "do_pelna": "Ciąg bez „do pełna”",
    "bez_licznika": "Wpisy bez licznika",
    "pliki": "Martwe załączniki",
    "nazwy": "Duplikaty nazw",
    "rodzaj": "Naprawy bez rodzaju",
    "terminy": "Terminy bez daty",
    "pojazd": "Puste pola pojazdu",
}
# Karta auta — sprzedanemu jej braków nie wypominamy (jak kondycja).
SPRAWDZENIA_KARTY = ("terminy", "pojazd")

DNI_PRZEGLADU_DANYCH = 91  # dzwonek „raz na kwartał” od ostatniego otwarcia ekranu na tym telefonie
MIN_CIAGU_BEZ_PELNEGO = 2  # jak ostrzeżenie w formularzu tankowania
OKNO_SASIADOW_CENY = 15    # z tylu wpisów z każdej strony wybieramy CENY_ODNIESIENIA najbliższych w czasie

ETYKIETY_WPISOW = {
    "tankowania": "Tankowanie", "inne_koszty": "Inny koszt", "wizyty": "Wizyta", "historia": "Wpis serwisowy",
    "odczyty_przebiegu": "Odczyt licznika", "dolewki": "Dolewka", "przejazdy": "Przejazd",
    "zdjecia_karoserii": "Zdjęcie karoserii", "zestawy_opon": "Komplet opon", "magazyn_czesci": "Część z magazynu",
    "dokumenty_pojazdu": "Dokument", "szkice_wpisow": "Paragon do wpisania", "samochody": "Zdjęcie pojazdu",
}

TRASY_WPISOW = {
    "tankowania": "/tankowanie/edytuj/{id}", "inne_koszty": "/inne/edytuj/{id}", "wizyty": "/wizyty/edytuj/{id}",
    "historia": "/wpis/edytuj/{id}", "odczyty_przebiegu": "/przebieg", "dolewki": "/dolewki/edytuj/{id}",
    "przejazdy": "/ewidencja/edytuj/{id}", "zdjecia_karoserii": "/karoseria/edytuj/{id}",
    "zestawy_opon": "/magazyn/opony/edytuj/{id}", "magazyn_czesci": "/magazyn/czesci/edytuj/{id}",
    "dokumenty_pojazdu": "/dokumenty/edytuj/{id}", "szkice_wpisow": "/do-wpisania", "samochody": "/auto/edytuj/{id}",
}

POLA_POJAZDU_ZDROWIA = {
    "vin": "VIN", "nr_rej": "numer rejestracyjny", "typ_paliwa": "rodzaj paliwa",
    "pojemnosc_baku": "pojemność baku", "pojemnosc_baterii": "pojemność baterii",
}

# Wpisy ZDARZEŃ: (SELECT id, data, data_iso, opis, rodzaj energii … WHERE auto_id=?, alias). Plany
# (do zrobienia, cykliczne, ważność dokumentów) mają przyszłe daty z natury — ich tu nie ma.
# Koszt dolewki należy do niej (db/dolewki.py), więc liczy się raz, przy dolewce.
_ZDARZENIA = {
    "tankowania": ("SELECT t.id, t.data, t.data_iso, t.stacja, t.rodzaj_energii FROM tankowania t "
                   "WHERE t.auto_id=?", "t"),
    "inne_koszty": ("SELECT k.id, k.data, k.data_iso, COALESCE(NULLIF(TRIM(k.nazwa), ''), k.kategoria), NULL "
                    "FROM inne_koszty k WHERE k.auto_id=? AND k.id NOT IN "
                    "(SELECT koszt_id FROM dolewki WHERE koszt_id IS NOT NULL)", "k"),
    "wizyty": ("SELECT w.id, w.data, w.data_iso, w.wykonawca, NULL FROM wizyty w WHERE w.auto_id=?", "w"),
    "historia": ("SELECT h.id, h.data, h.data_iso, z.nazwa, NULL FROM historia h JOIN zadania z ON z.id = h.zadanie_id "
                 "WHERE z.auto_id=? AND h.wizyta_id IS NULL", "h"),
    "odczyty_przebiegu": ("SELECT o.id, o.data, o.data_iso, o.zrodlo, NULL FROM odczyty_przebiegu o "
                          "WHERE o.auto_id=?", "o"),
    "dolewki": ("SELECT d.id, d.data, d.data_iso, d.plyn, NULL FROM dolewki d WHERE d.auto_id=?", "d"),
    "przejazdy": ("SELECT p.id, p.data, p.data_iso, CASE WHEN TRIM(COALESCE(p.skad, '')) <> '' "
                  "AND TRIM(COALESCE(p.dokad, '')) <> '' THEN TRIM(p.skad) || ' – ' || TRIM(p.dokad) "
                  "ELSE p.cel END, NULL FROM przejazdy p WHERE p.auto_id=?", "p"),
    "zdjecia_karoserii": ("SELECT z.id, z.data, z.data_iso, z.strefa, NULL FROM zdjecia_karoserii z "
                          "WHERE z.auto_id=?", "z"),
}
TABELE_BEZ_LICZNIKA = ("tankowania", "wizyty", "historia", "dolewki")

# Rodzic martwego pliku: id, data, data_iso, opis, rodzaj dokumentu (tylko skarbiec).
_RODZICE_PLIKOW = {
    "tankowania": "SELECT id, data, data_iso, stacja, NULL FROM tankowania WHERE id IN ({})",
    "inne_koszty": "SELECT id, data, data_iso, COALESCE(NULLIF(TRIM(nazwa), ''), kategoria), NULL FROM inne_koszty "
                   "WHERE id IN ({})",
    "wizyty": "SELECT id, data, data_iso, wykonawca, NULL FROM wizyty WHERE id IN ({})",
    "historia": "SELECT h.id, h.data, h.data_iso, z.nazwa, NULL FROM historia h JOIN zadania z ON z.id = h.zadanie_id "
                "WHERE h.id IN ({})",
    "zestawy_opon": "SELECT id, NULL, NULL, TRIM(COALESCE(sezon, '') || ' ' || COALESCE(rozmiar, '')), NULL "
                    "FROM zestawy_opon WHERE id IN ({})",
    "magazyn_czesci": "SELECT id, NULL, NULL, nazwa, NULL FROM magazyn_czesci WHERE id IN ({})",
    "dokumenty_pojazdu": "SELECT id, NULL, NULL, NULLIF(TRIM(nazwa), ''), rodzaj FROM dokumenty_pojazdu WHERE id IN ({})",
    "zdjecia_karoserii": "SELECT id, data, data_iso, strefa, NULL FROM zdjecia_karoserii WHERE id IN ({})",
    "szkice_wpisow": "SELECT id, data, data_iso, opis, NULL FROM szkice_wpisow WHERE id IN ({})",
}


def _trasa(tabela, rekord_id):
    wzor = TRASY_WPISOW.get(tabela)
    return wzor.format(id=rekord_id) if wzor else None


def _dzien(iso):
    try:
        return date.fromisoformat(iso) if iso else None
    except (TypeError, ValueError):
        return None


def _numer_dnia(iso):
    dzien = _dzien(iso)
    return dzien.toordinal() if dzien else None


def _liczba(wartosc):
    try:
        return float(wartosc or 0)
    except (TypeError, ValueError):
        return 0.0


def _pozycja(rodzaj, klucz, waga, data_iso=None, data=None, trasa=None, **pola):
    return {"rodzaj": rodzaj, "klucz": klucz, "waga": waga, "data": data, "data_iso": data_iso, "trasa": trasa, **pola}


# ---------------------------------------------------------------- sprawdzenia


def _pozycje_licznika(auto_id):
    """Cofki i skoki z historii licznika (ta sama lista, co ekran „Historia przebiegu”)."""
    wpisy = pobierz_pelna_historie_przebiegu(auto_id)
    po_kluczu = {w["klucz"]: w for w in wpisy}
    wynik = []
    for w in wpisy:
        if not w.get("anomalia"):
            continue
        iso = w["data_obj"].isoformat()
        poprzedni = po_kluczu.get(w.get("poprzedni_klucz"))
        wynik.append(_pozycja(
            "licznik", f"licznik:{w['klucz']}:{w['przebieg']}:{iso}",
            "krytyczna" if w["anomalia"] == "cofka" else "ostrzezenie", iso, w["data"], w.get("trasa") or "/przebieg",
            anomalia=w["anomalia"], zrodlo=w["zrodlo"], etykieta=w["etykieta_zrodla"], opis=w["opis"],
            przebieg=w["przebieg"], dystans=w["dystans"], dni=w["dni"], srednia_dzienna=w["srednia_dzienna"],
            poprzedni={"data_iso": poprzedni["data_obj"].isoformat(), "przebieg": poprzedni["przebieg"],
                       "etykieta": poprzedni["etykieta_zrodla"]} if poprzedni else None,
        ))
    return wynik


def _odniesienia_ceny(z_data, i, bez_daty):
    """CENY_ODNIESIENIA najbliższych w czasie wpisów (bez `i`) — kolejność jak w
    ceny_jednostkowe_w_poblizu: odległość w dniach, przy remisie nowsze id."""
    t = z_data[i]
    sasiedzi = z_data[max(0, i - OKNO_SASIADOW_CENY):i] + z_data[i + 1:i + 1 + OKNO_SASIADOW_CENY]
    sasiedzi.sort(key=lambda s: (abs(s["dzien"] - t["dzien"]), -s["id"]))
    wybrane = sasiedzi[:CENY_ODNIESIENIA]
    return wybrane + bez_daty[:CENY_ODNIESIENIA - len(wybrane)]


def _pozycje_cen(tankowania):
    """Cena jednostkowa ≥ 3× od każdej z 10 najbliższych w czasie cen tego samego źródła — reguła
    formularza (db.nietypowa_cena) przyłożona do każdego zapisanego wpisu."""
    wynik = []
    wg_energii = {}
    for t in tankowania:
        if t["litry"] > 0 and t["kwota"] > 0:
            wg_energii.setdefault(t["energia"], []).append(dict(t, cena=t["kwota"] / t["litry"]))
    for energia, grupa in wg_energii.items():
        z_data = sorted((t for t in grupa if t["dzien"] is not None), key=lambda t: (t["dzien"], t["id"]))
        bez_daty = sorted((t for t in grupa if t["dzien"] is None), key=lambda t: -t["id"])
        najnowsze = sorted(z_data, key=lambda t: (-t["dzien"], -t["id"]))
        for i, t in enumerate(z_data + bez_daty):
            if i < len(z_data):
                odniesienia = _odniesienia_ceny(z_data, i, bez_daty)
            else:
                odniesienia = [s for s in najnowsze + bez_daty if s["id"] != t["id"]][:CENY_ODNIESIENIA]
            odstaje = nietypowa_cena(t["cena"], [s["cena"] for s in odniesienia])
            if not odstaje:
                continue
            wynik.append(_pozycja(
                "cena", f"cena:{t['id']}:{round(t['cena'], 4)}", "ostrzezenie", t["data_iso"], t["data"],
                _trasa("tankowania", t["id"]), id=t["id"], energia=energia, stacja=t["stacja"],
                litry=t["litry"], kwota=t["kwota"], **odstaje,
            ))
    return wynik


def _pozycje_ciagu(tankowania):
    """Ciągi tankowań bez pełnego baku z licznikiem, których spalanie się nie policzyło: przed
    pierwszym takim bakiem (litry przepadają) i po ostatnim (czekają). Środek historii liczy się
    jednym dłuższym odcinkiem — to nie błąd. Kolejność jak w pobierz_serie_spalania."""
    wynik = []
    wg_energii = {}
    for t in tankowania:
        wg_energii.setdefault(t["energia"], []).append(t)
    for energia, grupa in wg_energii.items():
        kolejne = sorted(grupa, key=lambda t: (parsuj_date(t["data"]), t["przebieg"]))
        zamyka = [t["do_pelna"] and t["przebieg"] > 0 for t in kolejne]
        if True in zamyka:
            pierwszy, ostatni = zamyka.index(True), len(zamyka) - 1 - zamyka[::-1].index(True)
            ciagi = [("przed_pierwszym", kolejne[:pierwszy], None), ("otwarty", kolejne[ostatni + 1:], kolejne[ostatni])]
        else:
            ciagi = [("przed_pierwszym", kolejne, None)]
        for polozenie, wpisy, pelny in ciagi:
            if len(wpisy) < MIN_CIAGU_BEZ_PELNEGO:
                continue
            start, koniec = wpisy[0], wpisy[-1]
            najdalej = max(t["przebieg"] for t in wpisy)
            wynik.append(_pozycja(
                "do_pelna", f"do_pelna:{energia}:{start['id']}:{start['data_iso'] or ''}", "info",
                koniec["data_iso"], koniec["data"], _trasa("tankowania", koniec["id"]),
                energia=energia, polozenie=polozenie, liczba=len(wpisy),
                pelny_data_iso=pelny["data_iso"] if pelny else None,
                km=najdalej - pelny["przebieg"] if pelny and najdalej > pelny["przebieg"] else None,
                bez_licznika=sum(1 for t in wpisy if t["do_pelna"] and t["przebieg"] <= 0),
                wpisy=[{"id": t["id"], "data": t["data"], "data_iso": t["data_iso"],
                        "trasa": _trasa("tankowania", t["id"])} for t in wpisy],
            ))
    return wynik


def _opis_zdarzenia(tabela, opis):
    if tabela == "odczyty_przebiegu":
        return ZRODLA_ODCZYTU.get(opis or ZRODLO_ODCZYTU_DOMYSLNE, ZRODLA_ODCZYTU[ZRODLO_ODCZYTU_DOMYSLNE])
    if tabela == "dolewki":
        return (RODZAJE_PLYNOW.get(opis) or {}).get("nazwa")
    return str(opis or "").strip() or None


def _pozycje_zdarzen(conn, auto_id, rodzaj, tabele, warunek, parametry, domyslna_energia):
    """Pozycje „przyszlosc” albo „bez_licznika”: wpisy zdarzeń spełniające `warunek` (z {a} = alias)."""
    wynik = []
    for tabela in tabele:
        zapytanie, alias = _ZDARZENIA[tabela]
        for rid, data, data_iso, opis, energia in conn.execute(
                f"{zapytanie} AND {warunek.format(a=alias)}", (auto_id, *parametry)).fetchall():
            etykieta = ETYKIETY_WPISOW[tabela]
            if tabela == "tankowania" and (energia or domyslna_energia) == ENERGIA_PRAD:
                etykieta = "Ładowanie"
            wynik.append(_pozycja(
                rodzaj, f"{rodzaj}:{tabela}:{rid}:{data_iso or ''}", "ostrzezenie" if rodzaj == "przyszlosc" else "info",
                data_iso, data, _trasa(tabela, rid), tabela=tabela, id=rid, etykieta=etykieta,
                opis=_opis_zdarzenia(tabela, opis),
            ))
    return wynik


def _pozycje_rodzaju(auto_id):
    """Naprawy bez rodzaju jedną pozycją — oznacza się je w arkuszu, nie po jednej. Nowa naprawa
    bez rodzaju zmienia klucz, więc „To nie błąd” jej nie przykryje."""
    naprawy = naprawy_bez_rodzaju(auto_id)
    if not naprawy:
        return []
    najnowsza = naprawy[0]
    return [_pozycja(
        "rodzaj", f"rodzaj:{len(naprawy)}:{najnowsza['data_iso'] or ''}", "info", najnowsza["data_iso"],
        najnowsza["data"], liczba=len(naprawy), z_podpowiedzia=sum(1 for n in naprawy if n["sugestia"]),
        kwota=sum(n["kwota"] for n in naprawy),
    )]


def _sciezki_plikow(conn, auto_id, auto):
    """[(źródło, id wiersza, tabela rodzica, id rodzica, ścieżka z bazy, typ)] — wszystkie pliki auta."""
    sciezki = []
    if str(auto["zdjecie_glowne"] or "").strip():
        sciezki.append(("samochody", auto_id, "samochody", auto_id, auto["zdjecie_glowne"], "zdjecie"))
    for rid, tabela, rekord_id, sciezka, typ in conn.execute(
            "SELECT id, tabela, rekord_id, sciezka, typ FROM zalaczniki WHERE auto_id=? ORDER BY id", (auto_id,)):
        sciezki.append(("zalaczniki", rid, tabela, rekord_id, sciezka, typ))
    for tabela, typ in (("zdjecia_karoserii", "zdjecie"), ("szkice_wpisow", "paragon")):
        for rid, sciezka in conn.execute(
                f"SELECT id, zalacznik FROM {tabela} WHERE auto_id=? AND COALESCE(TRIM(zalacznik), '') <> '' "
                "ORDER BY id", (auto_id,)):
            sciezki.append((tabela, rid, tabela, rid, sciezka, typ))
    return sciezki


def _rodzice(conn, pary):
    """{(tabela, id): (data, data_iso, opis)} dla martwych plików."""
    wg_tabeli = {}
    for tabela, rekord_id in pary:
        wg_tabeli.setdefault(tabela, set()).add(rekord_id)
    wynik = {}
    for tabela, ids in wg_tabeli.items():
        zapytanie = _RODZICE_PLIKOW.get(tabela)
        if not zapytanie:
            continue
        ids = sorted(ids)
        for rid, data, data_iso, opis, rodzaj_dokumentu in conn.execute(
                zapytanie.format(",".join("?" * len(ids))), ids).fetchall():
            if tabela == "dokumenty_pojazdu" and not opis:
                opis = etykieta_dokumentu(rodzaj_dokumentu)
            wynik[(tabela, rid)] = (data, data_iso, str(opis or "").strip() or None)
    return wynik


def _pozycje_plikow(conn, auto_id, auto):
    """Pliki, których nie ma pod zapisaną ścieżką: „przeniesiony” (jest pod tą samą nazwą w folderze
    załączników albo kosza — naprawi go db.napraw_sciezki_zalacznikow) albo „brak”."""
    martwe = []
    for zrodlo, rid, tabela, rekord_id, sciezka, typ in _sciezki_plikow(conn, auto_id, auto):
        if os.path.exists(pelna_sciezka_zalacznika(sciezka) or ""):
            continue
        tutejsza = sciezka_pliku_zalacznika(sciezka)
        martwe.append((zrodlo, rid, tabela, rekord_id, sciezka, typ,
                       "przeniesiony" if tutejsza and os.path.exists(tutejsza) else "brak"))
    rodzice = _rodzice(conn, {(m[2], m[3]) for m in martwe if m[0] != "samochody"})
    wynik = []
    for zrodlo, rid, tabela, rekord_id, sciezka, typ, stan in martwe:
        rodzic = rodzice.get((tabela, rekord_id))
        data, data_iso, opis = rodzic or (None, None, None)
        wynik.append(_pozycja(
            "pliki", f"plik:{zrodlo}:{rid}:{sciezka}", "ostrzezenie" if stan == "brak" else "info", data_iso, data,
            _trasa(tabela, rekord_id) if rodzic or zrodlo == "samochody" else None,
            zrodlo=zrodlo, id=rid, tabela=tabela, rekord_id=rekord_id, typ=typ, stan=stan,
            nazwa_pliku=os.path.basename(str(sciezka).replace("\\", "/")), etykieta=ETYKIETY_WPISOW.get(tabela, "Wpis"),
            opis=opis, usuwalny=zrodlo != "samochody",
        ))
    return wynik


def _pozycje_nazw(auto_id):
    """Grupy wariantów tej samej nazwy (db.znajdz_duplikaty_nazw); nowy wariant zmienia klucz."""
    return [_pozycja("nazwy", f"nazwy:{g['tabela']}:{g['klucz']}:{len(g['warianty'])}", "info", grupa=g)
            for g in znajdz_duplikaty_nazw(auto_id)]


def _pozycje_terminow(auto_id, auto):
    """OC i przegląd bez czytelnej daty — ta sama reguła, co kondycja (brak_terminu_dokumentu)."""
    wynik = []
    for klucz, kolumna, etykieta in TERMINY_DOKUMENTOW:
        tekst = str(auto[kolumna] or "").strip()
        if klucz in TERMINY_WYMAGANE_W_KONDYCJI and (not tekst or parsuj_date(tekst) == date.min):
            wynik.append(_pozycja("terminy", f"termin:{klucz}", "ostrzezenie", trasa=_trasa("samochody", auto_id),
                                  termin=klucz, etykieta=etykieta, nieczytelna=bool(tekst)))
    return wynik


def _pozycje_pojazdu(auto_id, auto):
    """Puste pola Karty, z których korzystają inne ekrany; pojemność baku albo baterii wg napędu."""
    typ = str(auto["typ_paliwa"] or "").strip()
    pola = ["vin", "nr_rej", "typ_paliwa"]
    if typ in TYPY_PALIWA_ELEKTRYCZNE:
        pola.append("pojemnosc_baterii")
    elif typ in TYPY_PALIWA_DWUZRODLOWE:
        pola += ["pojemnosc_baku", "pojemnosc_baterii"]
    else:
        pola.append("pojemnosc_baku")
    puste = [p for p in pola if not str(auto[p] or "").strip()]
    if not puste:
        return []
    return [_pozycja("pojazd", "pojazd:" + ",".join(puste), "info", trasa=_trasa("samochody", auto_id),
                     pola=[POLA_POJAZDU_ZDROWIA[p] for p in puste])]


def _policz_zdrowie_danych(auto_id):
    domyslna_energia = domyslny_rodzaj_energii(auto_id)
    dzis = date.today().isoformat()
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        auto = conn.execute("SELECT * FROM samochody WHERE id=?", (auto_id,)).fetchone()
        if not auto:
            return {"pozycje": [], "sprawdzone": []}
        tankowania = [{
            "id": r["id"], "data": r["data"], "data_iso": r["data_iso"], "dzien": _numer_dnia(r["data_iso"]),
            "przebieg": int(r["przebieg"] or 0), "litry": _liczba(r["litry"]), "kwota": _liczba(r["kwota"]),
            "do_pelna": bool(r["do_pelna"]), "stacja": r["stacja"], "energia": r["rodzaj_energii"] or domyslna_energia,
        } for r in conn.execute("SELECT id, data, data_iso, przebieg, litry, kwota, do_pelna, stacja, rodzaj_energii "
                                "FROM tankowania WHERE auto_id=?", (auto_id,))]
        conn.row_factory = None
        pozycje = (
            _pozycje_zdarzen(conn, auto_id, "przyszlosc", tuple(_ZDARZENIA), "{a}.data_iso > ?", (dzis,),
                             domyslna_energia)
            + _pozycje_zdarzen(conn, auto_id, "bez_licznika", TABELE_BEZ_LICZNIKA,
                               "COALESCE({a}.przebieg, 0) <= 0", (), domyslna_energia)
            + _pozycje_plikow(conn, auto_id, auto)
        )
    sprzedany = str(auto["status"] or "") == STATUS_POJAZDU_SPRZEDANY
    pozycje += _pozycje_licznika(auto_id) + _pozycje_cen(tankowania) + _pozycje_ciagu(tankowania)
    pozycje += _pozycje_nazw(auto_id) + _pozycje_rodzaju(auto_id)
    if not sprzedany:
        pozycje += _pozycje_terminow(auto_id, auto) + _pozycje_pojazdu(auto_id, auto)

    kolejnosc = {r: i for i, r in enumerate(SPRAWDZENIA_ZDROWIA)}
    pozycje.sort(key=lambda p: p["data_iso"] or "", reverse=True)
    pozycje.sort(key=lambda p: kolejnosc[p["rodzaj"]])
    # Rola „podgląd” nie oznaczy rodzaju napraw (naprawy_bez_rodzaju zwraca jej pustą listę),
    # więc ta sekcja nie udaje dla niej „bez zastrzeżeń”.
    pomin = set(SPRAWDZENIA_KARTY if sprzedany else ()) | ({"rodzaj"} if czy_tylko_podglad(auto_id) else set())
    return {"pozycje": pozycje, "sprawdzone": [r for r in SPRAWDZENIA_ZDROWIA if r not in pomin]}


# ---------------------------------------------------------------- wynik i „To nie błąd”


def _surowe(auto_id):
    return z_pamieci("zdrowie_danych", auto_id, lambda: _policz_zdrowie_danych(auto_id))


def zdrowie_danych(auto_id) -> dict[str, Any]:
    """{pozycje (do sprawdzenia, w kolejności sekcji, w sekcji od najnowszej), pominiete („To nie
    błąd” na tym telefonie), liczby {rodzaj: ile}, razem, krytyczne, sprawdzone (rodzaje, które
    dotyczą auta), przejrzane (RRRR-MM-DD albo None)}. Pozycja: rodzaj, klucz, waga, data,
    data_iso, trasa i pola swojego rodzaju."""
    wynik = {"pozycje": [], "pominiete": [], "liczby": {}, "razem": 0, "krytyczne": 0, "sprawdzone": [],
             "przejrzane": None}
    if not auto_id:
        return wynik
    surowe = _surowe(auto_id)
    ustawienia = pobierz_ustawienia_zdrowia(auto_id)
    pominiete = set(ustawienia["pominiete"])
    for p in surowe["pozycje"]:
        (wynik["pominiete"] if p["klucz"] in pominiete else wynik["pozycje"]).append(p)
    for p in wynik["pozycje"]:
        wynik["liczby"][p["rodzaj"]] = wynik["liczby"].get(p["rodzaj"], 0) + 1
    wynik.update(razem=len(wynik["pozycje"]), krytyczne=sum(1 for p in wynik["pozycje"] if p["waga"] == "krytyczna"),
                 sprawdzone=surowe["sprawdzone"], przejrzane=ustawienia["przejrzane"])
    return wynik


def podsumowanie_zdrowia_danych(auto_id) -> dict[str, Any]:
    """Liczby do kafelka, Ustawień i kondycji: {razem, krytyczne, liczby {rodzaj: ile}}."""
    stan = zdrowie_danych(auto_id)
    return {"razem": stan["razem"], "krytyczne": stan["krytyczne"], "liczby": stan["liczby"]}


def _zmien_pominiete(auto_id, dodaj=(), zdejmij=()):
    """Dopisuje i zdejmuje klucze „To nie błąd”; klucze, których nikt już nie wykrywa, wypadają."""
    if not auto_id:
        return
    obecne = {p["klucz"] for p in _surowe(auto_id)["pozycje"]}
    ustawienia = pobierz_ustawienia_zdrowia(auto_id)
    klucze = (set(ustawienia["pominiete"]) | set(dodaj)) - set(zdejmij)
    zapisz_ustawienia_zdrowia(auto_id, [k for k in klucze if k in obecne], ustawienia["przejrzane"])


def pomin_w_zdrowiu_danych(auto_id, klucze):
    """„To nie błąd”: pozycje przestają się liczyć na tym telefonie (zostają w sekcji ukrytych)."""
    _zmien_pominiete(auto_id, dodaj=klucze)


def przywroc_w_zdrowiu_danych(auto_id, klucze):
    _zmien_pominiete(auto_id, zdejmij=klucze)


def zanotuj_przeglad_danych(auto_id, dzis=None):
    """Otwarty ekran = dane przejrzane: dzwonek milknie na DNI_PRZEGLADU_DANYCH dni. Zapis raz na dzień."""
    if not auto_id:
        return
    dzien = (dzis or date.today()).isoformat()
    ustawienia = pobierz_ustawienia_zdrowia(auto_id)
    if ustawienia["przejrzane"] != dzien:
        zapisz_ustawienia_zdrowia(auto_id, ustawienia["pominiete"], dzien)


def przeglad_danych_nalezny(auto_id, dzis=None) -> dict[str, Any] | None:
    """Dzwonek „Zdrowie danych”: {razem, przejrzane (data), dni} albo None. Kwartał liczy się od
    ostatniego otwarcia ekranu na tym telefonie; ekran nigdy nieotwierany nie dzwoni (po
    aktualizacji każde auto z pustym VIN-em dzwoniłoby naraz — o ekranie mówi „Co nowego”).
    Sprawdzenia liczą się dopiero, gdy termin minął."""
    if not auto_id:
        return None
    dzis = dzis or date.today()
    przejrzane = _dzien(pobierz_ustawienia_zdrowia(auto_id)["przejrzane"])
    if not przejrzane or (dzis - przejrzane).days < DNI_PRZEGLADU_DANYCH:
        return None
    razem = zdrowie_danych(auto_id)["razem"]
    if not razem:
        return None
    return {"razem": razem, "przejrzane": przejrzane, "dni": (dzis - przejrzane).days}


# ---------------------------------------------------------------- naprawy


def _przelicz_pliki_dokumentow(dokumenty):
    if not dokumenty:
        return
    with polacz_baze() as conn:
        for rekord_id in sorted(dokumenty):
            _policz_pliki_dokumentu(conn, "dokumenty_pojazdu", rekord_id)


def usun_martwe_pliki(pozycje) -> dict[str, Any] | None:
    """Martwe pliki (pozycje „pliki”) do kosza wpisów: wiersze `zalaczniki`, zdjęcia karoserii
    i szkice — zdjęcie pojazdu nie (to pole Karty). Wynik jak db.usun_do_kosza plus `liczba`;
    „cofnij” cofa całość, dokument skarbca przelicza `liczba_plikow` w obie strony."""
    wg_zrodla, dokumenty = {}, set()
    for p in pozycje or ():
        if p.get("rodzaj") != "pliki" or not p.get("usuwalny"):
            continue
        wg_zrodla.setdefault(p["zrodlo"], []).append(p["id"])
        if p["zrodlo"] == "zalaczniki" and p["tabela"] == "dokumenty_pojazdu":
            dokumenty.add(p["rekord_id"])
    wyniki = [w for w in (usun_do_kosza(zrodlo, ids) for zrodlo, ids in wg_zrodla.items()) if w]
    if not wyniki:
        return None
    _przelicz_pliki_dokumentow(dokumenty)
    stan = {"cofniete": False}

    def cofnij():
        if stan["cofniete"]:
            return None
        stan["cofniete"] = True
        odpowiedzi = [w["cofnij"]() for w in wyniki]
        _przelicz_pliki_dokumentow(dokumenty)
        nieudane = [o for o in odpowiedzi if not o or not o.get("ok")]
        return nieudane[0] if nieudane else odpowiedzi[0]

    def finalizuj():
        for w in wyniki:
            w["finalizuj"]()

    pominiete = sum(w.get("pominiete") or 0 for w in wyniki)
    return {**wyniki[0], "cofnij": cofnij, "finalizuj": finalizuj, "pominiete": pominiete,
            "kosz_ids": [k for w in wyniki for k in w.get("kosz_ids") or []],
            "liczba": sum(len(ids) for ids in wg_zrodla.values()) - pominiete}


__all__ = [
    "DNI_PRZEGLADU_DANYCH",
    "ETYKIETY_WPISOW",
    "MIN_CIAGU_BEZ_PELNEGO",
    "OKNO_SASIADOW_CENY",
    "POLA_POJAZDU_ZDROWIA",
    "SPRAWDZENIA_KARTY",
    "SPRAWDZENIA_ZDROWIA",
    "TABELE_BEZ_LICZNIKA",
    "TRASY_WPISOW",
    "podsumowanie_zdrowia_danych",
    "pomin_w_zdrowiu_danych",
    "przeglad_danych_nalezny",
    "przywroc_w_zdrowiu_danych",
    "usun_martwe_pliki",
    "zanotuj_przeglad_danych",
    "zdrowie_danych",
]
