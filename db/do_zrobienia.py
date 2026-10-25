"""Do zrobienia: wykonanie z datą, licznikiem i faktycznym kosztem (wpis serwisowy albo Inny
koszt), dziennik zdarzeń pozycji, termin przebiegowy i przesuwanie terminu."""

import json
import sqlite3
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Any

from date import na_iso, parsuj_date
from .stale import KATEGORIA_INNE_DOMYSLNA, PRIORYTETY_DO_ZROBIENIA
from .polaczenie import polacz_baze
from .pomocnicze import _na_liczbe
from .ustawienia import pobierz_moje_imie
from .synchronizacja import czy_moge_dodawac, zarejestruj_nagrobek
from .notatki import przytnij_notatke
from .przebieg import pobierz_aktualny_przebieg, przelicz_wszystkie_zadania, szacuj_przebieg_w_dniu
from .kosz_wpisow import usun_do_kosza
from .awarie import domyslny_rodzaj_serwisu


ZDARZENIE_DODANO = "dodano"
ZDARZENIE_ZMIANA = "zmiana"
ZDARZENIE_TERMIN = "termin"
ZDARZENIE_WYKONANO = "wykonano"
ZDARZENIE_POPRAWKA = "poprawka"
ZDARZENIE_COFNIETO = "cofnieto"
ZDARZENIE_WIZYTA = "wizyta"
ZDARZENIE_ZWROT = "zwrot"

# Dziennik pozycji (`do_zrobienia_zdarzenia`): rodzaj -> etykieta. Szczegóły leżą w `dane`
# (JSON), napis składa ekran — liczby i jednostka dystansu idą za ustawieniami czytającego.
ETYKIETY_ZDARZEN_DO_ZROBIENIA = {
    ZDARZENIE_DODANO: "Dodano do listy",
    ZDARZENIE_ZMIANA: "Zmieniono",
    ZDARZENIE_TERMIN: "Nowy termin",
    ZDARZENIE_WYKONANO: "Wykonano",
    ZDARZENIE_POPRAWKA: "Poprawiono wykonanie",
    ZDARZENIE_COFNIETO: "Cofnięto wykonanie",
    ZDARZENIE_WIZYTA: "Zamieniono w wizytę",
    ZDARZENIE_ZWROT: "Wróciło z wizyty",
}

# Ile km przed terminem przebiegowym pozycja robi się pilna (jak próg interwału podzespołu).
PROG_PILNEGO_PRZEBIEGU = 1000

# Szybkie przesunięcia terminu: (etykieta, dni, miesiące); przebiegu — o tyle w jednostce dystansu.
PRZESUNIECIA_TERMINU = (("+1 tydzień", 7, 0), ("+2 tygodnie", 14, 0), ("+1 miesiąc", 0, 1), ("+3 miesiące", 0, 3))
PRZESUNIECIA_PRZEBIEGU = (1000, 5000)

# Pola, których zmianę notuje dziennik (termin osobno, jako ZDARZENIE_TERMIN).
_POLA_ZMIANY = ("tytul", "opis", "priorytet", "szacowany_koszt", "zadanie_id")

_SEZONY_OPON = ("Letnie", "Zimowe", "Całoroczne")
_BRAK = object()

_ZAPYTANIE = (
    "SELECT d.*, z.nazwa AS zadanie_nazwa, z.dotyczy_opon AS zadanie_opony, "
    "h.id AS h_id, h.data AS h_data, h.przebieg AS h_przebieg, h.cena AS h_cena, h.wizyta_id AS h_wizyta, "
    "k.id AS k_id, k.data AS k_data, k.kwota AS k_kwota, "
    "w.id AS w_id, w.data AS w_data, w.przebieg AS w_przebieg, w.wykonawca AS w_wykonawca "
    "FROM do_zrobienia d "
    "LEFT JOIN zadania z ON z.id = d.zadanie_id "
    "LEFT JOIN historia h ON h.id = d.historia_id "
    "LEFT JOIN inne_koszty k ON k.id = d.koszt_id "
    "LEFT JOIN wizyty w ON w.id = d.wizyta_id "
)


def _teraz():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _dzis():
    return datetime.now().strftime("%d.%m.%Y")


def _calkowita(wartosc):
    liczba = _na_liczbe(wartosc)
    return int(round(liczba)) if liczba is not None and liczba > 0 else None


def _kwota(wartosc):
    liczba = _na_liczbe(wartosc)
    return round(liczba, 2) if liczba is not None and liczba > 0 else None


def _tekst(wartosc):
    return str(wartosc).strip() if wartosc not in (None, "") and str(wartosc).strip() else None


# ---------------------------------------------------------------- dziennik pozycji


def zanotuj_zdarzenie_do_zrobienia(conn, pozycja_id, rodzaj, dane=None, kto=None):
    """Wpis dziennika pozycji w transakcji `conn`; id wpisu. `kto` — imię z ustawień
    (pobierz_moje_imie przed otwarciem transakcji)."""
    return conn.execute(
        "INSERT INTO do_zrobienia_zdarzenia (pozycja_id, rodzaj, dane, moment, dodane_przez) VALUES (?,?,?,?,?)",
        (pozycja_id, rodzaj, json.dumps(dane or {}, ensure_ascii=False, default=str), _teraz(), kto or None),
    ).lastrowid


def pobierz_zdarzenia_do_zrobienia(pozycja_id) -> list[dict[str, Any]]:
    """Dziennik pozycji od najstarszego: rodzaj, dane (słownik), moment (ISO), dodane_przez."""
    if not pozycja_id:
        return []
    with polacz_baze() as conn:
        wiersze = conn.execute(
            "SELECT id, rodzaj, dane, moment, dodane_przez FROM do_zrobienia_zdarzenia "
            "WHERE pozycja_id=? ORDER BY moment, id", (pozycja_id,)).fetchall()
    wynik = []
    for z_id, rodzaj, dane, moment, kto in wiersze:
        try:
            szczegoly = json.loads(dane or "{}")
        except (TypeError, ValueError):
            szczegoly = {}
        wynik.append({"id": z_id, "rodzaj": str(rodzaj or ""), "dane": szczegoly if isinstance(szczegoly, dict) else {},
                      "moment": moment, "dodane_przez": kto})
    return wynik


# ---------------------------------------------------------------- terminy


def stan_terminu_przebiegowego(termin_km, start_km=None, aktualny_km=None) -> dict[str, Any] | None:
    """Ile zostało do terminu przebiegowego (km, ujemne po terminie), postęp 0–1 od licznika
    startowego (None, gdy go nie ma) i status jak przy interwałach; None bez terminu i licznika."""
    cel, teraz = _calkowita(termin_km), _calkowita(aktualny_km)
    if not cel or not teraz:
        return None
    start = _calkowita(start_km)
    zostalo = cel - teraz
    procent = None
    if start is not None and start < cel:
        procent = min(1.0, max(0.0, (teraz - start) / (cel - start)))
    status = "przeterminowane" if zostalo <= 0 else "pilne" if zostalo <= PROG_PILNEGO_PRZEBIEGU else "ok"
    return {"cel": cel, "zostalo": zostalo, "procent": procent, "status": status}


def termin_po_przesunieciu(termin, dni=0, miesiace=0, dzis=None) -> str:
    """Termin przesunięty o dni albo miesiące (koniec krótszego miesiąca przycina dzień) — od
    dawnego terminu, a gdy ten minął albo go nie ma, od dziś. DD.MM.RRRR."""
    dzis = dzis or date.today()
    podstawa = parsuj_date(termin)
    if podstawa == datetime.min.date() or podstawa < dzis:
        podstawa = dzis
    if miesiace:
        numer = podstawa.month - 1 + int(miesiace)
        rok, miesiac = podstawa.year + numer // 12, numer % 12 + 1
        podstawa = podstawa.replace(year=rok, month=miesiac, day=min(podstawa.day, monthrange(rok, miesiac)[1]))
    return (podstawa + timedelta(days=int(dni or 0))).strftime("%d.%m.%Y")


# ---------------------------------------------------------------- odczyt


def _pozycja(r, aktualny_km=None):
    """Wiersz zapytania -> słownik. Wykonanie z powiązanym wpisem bierze datę, licznik i kwotę
    z niego (poprawione w Serwisie czy Kosztach zgadza się tu samo); bez wpisu — własne kolumny."""
    serwis, koszt, wizyta = r["h_id"] is not None, r["k_id"] is not None, r["w_id"] is not None
    zrobione = bool(r["wykonane"])
    if serwis:
        data_w, przebieg_w, koszt_w = r["h_data"], r["h_przebieg"], r["h_cena"]
    elif koszt:
        data_w, przebieg_w, koszt_w = r["k_data"], r["przebieg_wykonania"], r["k_kwota"]
    elif wizyta:
        data_w, przebieg_w, koszt_w = r["w_data"], r["w_przebieg"], r["koszt_wykonania"]
    else:
        data_w, przebieg_w, koszt_w = r["data_wykonania"], r["przebieg_wykonania"], r["koszt_wykonania"]
    return {
        "id": r["id"], "auto_id": r["auto_id"], "tytul": str(r["tytul"] or ""), "opis": r["opis"] or "",
        "priorytet": r["priorytet"] or "Średni", "szacowany_koszt": r["szacowany_koszt"],
        "termin": r["termin"] or "", "zadanie_id": r["zadanie_id"], "zadanie_nazwa": r["zadanie_nazwa"],
        "zadanie_opony": bool(r["zadanie_opony"]), "wykonane": zrobione, "data_utworzenia": r["data_utworzenia"],
        "termin_przebieg": r["termin_przebieg"], "przebieg_startowy": r["przebieg_startowy"],
        "stan_przebiegu": None if zrobione else stan_terminu_przebiegowego(
            r["termin_przebieg"], r["przebieg_startowy"], aktualny_km),
        "data_wykonania": (data_w or r["data_wykonania"]) if zrobione else None,
        "przebieg_wykonania": (przebieg_w or r["przebieg_wykonania"]) if zrobione else None,
        "koszt_wykonania": koszt_w if zrobione else None,
        "notatka_wykonania": r["notatka_wykonania"] if zrobione else None,
        "wykonane_przez": r["wykonane_przez"] if zrobione else None,
        "historia_id": r["h_id"], "koszt_id": r["k_id"], "wizyta_id": r["w_id"],
        "w_wizycie": wizyta or r["h_wizyta"] is not None,
        "wizyta_data": r["w_data"], "wizyta_wykonawca": r["w_wykonawca"],
    }


def pobierz_pozycje_do_zrobienia(auto_id, wykonane=False) -> list[dict[str, Any]]:
    """Aktywne (albo wykonane) pozycje pojazdu jako słowniki — z nazwą podzespołu, stanem
    terminu przebiegowego (aktywne) i wykonaniem (wykonane)."""
    if not auto_id:
        return []
    aktualny = None if wykonane else pobierz_aktualny_przebieg(auto_id)
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        wiersze = conn.execute(_ZAPYTANIE + "WHERE d.auto_id=? AND d.wykonane=? ORDER BY d.id",
                               (auto_id, 1 if wykonane else 0)).fetchall()
    return [_pozycja(w, aktualny) for w in wiersze]


def pozycja_do_zrobienia(pozycja_id) -> dict[str, Any] | None:
    """Jedna pozycja jak w pobierz_pozycje_do_zrobienia; None, gdy jej nie ma."""
    if not pozycja_id:
        return None
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        w = conn.execute(_ZAPYTANIE + "WHERE d.id=?", (pozycja_id,)).fetchone()
    if not w:
        return None
    return _pozycja(w, None if w["wykonane"] else pobierz_aktualny_przebieg(w["auto_id"]))


# ---------------------------------------------------------------- zapis pozycji


def _rozne(a, b):
    return (a if a not in ("", None) else None) != (b if b not in ("", None) else None)


def _pola_pozycji(w):
    """Pola pozycji w postaci, w jakiej zapisuje je zapisz_pozycje_do_zrobienia — porównanie ze
    starym wierszem nie widzi zmiany tam, gdzie jest tylko inny zapis pustki („”, 0, NULL)."""
    return {
        "tytul": _tekst(w.get("tytul")), "opis": _tekst(w.get("opis")),
        "priorytet": w.get("priorytet") if w.get("priorytet") in PRIORYTETY_DO_ZROBIENIA else "Średni",
        "szacowany_koszt": _kwota(w.get("szacowany_koszt")), "termin": _tekst(w.get("termin")),
        "zadanie_id": _calkowita(w.get("zadanie_id")), "termin_przebieg": _calkowita(w.get("termin_przebieg")),
    }


def _nazwa_zadania(c, zadanie_id):
    if not zadanie_id:
        return None
    w = c.execute("SELECT nazwa FROM zadania WHERE id=?", (zadanie_id,)).fetchone()
    return w[0] if w else None


def zapisz_pozycje_do_zrobienia(auto_id, dane, pozycja_id=None):
    """Nowa albo poprawiona pozycja; id albo None (pusty tytuł, brak prawa, pozycji nie ma).
    `dane`: tytul, opis, priorytet, szacowany_koszt, termin, zadanie_id, termin_przebieg (km).
    Dziennik dostaje dodanie, zmianę terminu albo zmianę pozostałych pól."""
    nowe = _pola_pozycji(dane)
    if not auto_id or not nowe["tytul"] or not czy_moge_dodawac(auto_id):
        return None
    ja = pobierz_moje_imie() or None
    aktualny = (pobierz_aktualny_przebieg(auto_id) or None) if nowe["termin_przebieg"] else None

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        if not pozycja_id:
            pozycja_id = c.execute(
                "INSERT INTO do_zrobienia (auto_id, tytul, opis, priorytet, szacowany_koszt, termin, zadanie_id, "
                "termin_przebieg, przebieg_startowy, wykonane, data_utworzenia) VALUES (?,?,?,?,?,?,?,?,?,0,?)",
                (auto_id, nowe["tytul"], nowe["opis"], nowe["priorytet"], nowe["szacowany_koszt"], nowe["termin"],
                 nowe["zadanie_id"], nowe["termin_przebieg"], aktualny, _dzis())).lastrowid
            zanotuj_zdarzenie_do_zrobienia(conn, pozycja_id, ZDARZENIE_DODANO, {}, ja)
            return pozycja_id

        wiersz = c.execute("SELECT * FROM do_zrobienia WHERE id=? AND auto_id=?", (pozycja_id, auto_id)).fetchone()
        if not wiersz:
            return None
        stary = _pola_pozycji(dict(wiersz))
        start = (wiersz["przebieg_startowy"] or aktualny) if nowe["termin_przebieg"] else None
        c.execute("UPDATE do_zrobienia SET tytul=?, opis=?, priorytet=?, szacowany_koszt=?, termin=?, zadanie_id=?, "
                  "termin_przebieg=?, przebieg_startowy=? WHERE id=?",
                  (nowe["tytul"], nowe["opis"], nowe["priorytet"], nowe["szacowany_koszt"], nowe["termin"],
                   nowe["zadanie_id"], nowe["termin_przebieg"], start, pozycja_id))

        terminy = {p: [stary[p], nowe[p]] for p in ("termin", "termin_przebieg") if stary[p] != nowe[p]}
        if terminy:
            zanotuj_zdarzenie_do_zrobienia(conn, pozycja_id, ZDARZENIE_TERMIN, terminy, ja)
        pola = [p for p in _POLA_ZMIANY if stary[p] != nowe[p]]
        if pola:
            zmiana = {"pola": pola}
            for p in ("tytul", "priorytet", "szacowany_koszt"):
                if p in pola:
                    zmiana[p] = [stary[p], nowe[p]]
            if "zadanie_id" in pola:
                zmiana["zadanie"] = [_nazwa_zadania(c, stary["zadanie_id"]), _nazwa_zadania(c, nowe["zadanie_id"])]
            zanotuj_zdarzenie_do_zrobienia(conn, pozycja_id, ZDARZENIE_ZMIANA, zmiana, ja)
    return pozycja_id


def przesun_termin_do_zrobienia(pozycja_id, termin=_BRAK, termin_przebieg=_BRAK):
    """Nowy termin (DD.MM.RRRR) albo termin przebiegowy (km) aktywnej pozycji z wpisem
    w dzienniku; podany None czyści termin. True, gdy coś się zmieniło."""
    pozycja = pozycja_do_zrobienia(pozycja_id)
    if not pozycja or pozycja["wykonane"] or not czy_moge_dodawac(pozycja["auto_id"]):
        return False
    zmiany = {}
    if termin is not _BRAK and _rozne(pozycja["termin"], _tekst(termin)):
        zmiany["termin"] = [pozycja["termin"] or None, _tekst(termin)]
    if termin_przebieg is not _BRAK and _rozne(pozycja["termin_przebieg"], _calkowita(termin_przebieg)):
        zmiany["termin_przebieg"] = [pozycja["termin_przebieg"], _calkowita(termin_przebieg)]
    if not zmiany:
        return False
    ja = pobierz_moje_imie() or None
    start = pozycja["przebieg_startowy"]
    if "termin_przebieg" in zmiany and zmiany["termin_przebieg"][1] and not start:
        start = pobierz_aktualny_przebieg(pozycja["auto_id"]) or None
    with polacz_baze() as conn:
        for pole, (_, nowa) in zmiany.items():
            conn.execute(f"UPDATE do_zrobienia SET {pole}=? WHERE id=?", (nowa, pozycja_id))
        if "termin_przebieg" in zmiany:
            conn.execute("UPDATE do_zrobienia SET przebieg_startowy=? WHERE id=?",
                         (start if zmiany["termin_przebieg"][1] else None, pozycja_id))
        zanotuj_zdarzenie_do_zrobienia(conn, pozycja_id, ZDARZENIE_TERMIN, zmiany, ja)
    return True


# ---------------------------------------------------------------- wykonanie


def _istnieje(c, tabela, rekord_id):
    return bool(rekord_id) and c.execute(f"SELECT 1 FROM {tabela} WHERE id=?", (rekord_id,)).fetchone() is not None


def _sezon_opon(c, auto_id):
    w = c.execute("SELECT sezon FROM zestawy_opon WHERE auto_id=? AND zamontowane=1 ORDER BY id LIMIT 1",
                  (auto_id,)).fetchone()
    return w[0] if w and w[0] in _SEZONY_OPON else None


def oznacz_wykonane_do_zrobienia(pozycja_ids, dane) -> dict[str, Any] | None:
    """Odhacza pozycje (albo poprawia wykonanie odhaczonej): `dane` — data, przebieg (km), koszt,
    notatka, powiazany. Z `powiazany` pozycja z podzespołem dopisuje wpis serwisowy (interwał
    liczy się od nowa), bez podzespołu — przy koszcie Inny koszt. Kilka pozycji naraz: koszt
    każdej to jej szacunek. Wynik {liczba, serwis, koszty, do_kosza} albo None."""
    ids = [i for i in (pozycja_ids or []) if i]
    data = _tekst(dane.get("data")) or _dzis()
    if not ids or parsuj_date(data) == datetime.min.date():
        return None
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        wiersze = conn.execute(_ZAPYTANIE + f"WHERE d.id IN ({','.join('?' * len(ids))}) ORDER BY d.id",
                               tuple(ids)).fetchall()
    if not wiersze:
        return None
    auto_id = wiersze[0]["auto_id"]
    wiersze = [w for w in wiersze if w["auto_id"] == auto_id]
    if not czy_moge_dodawac(auto_id):
        return None

    jeden = len(wiersze) == 1
    przebieg = _calkowita(dane.get("przebieg"))
    notatka = przytnij_notatke(dane.get("notatka")) or None
    powiazany = bool(dane.get("powiazany", True))
    ja = pobierz_moje_imie() or None
    podpis = datetime.now().strftime("%d.%m.%Y %H:%M")
    # Wpis serwisowy bez licznika liczyłby interwał od zera — wtedy licznik z historii.
    przebieg_serwisu = przebieg or szacuj_przebieg_w_dniu(auto_id, data) or pobierz_aktualny_przebieg(auto_id) or 0
    do_kosza = {"historia": [], "inne_koszty": []}
    wynik = {"liczba": 0, "serwis": 0, "koszty": 0, "do_kosza": 0}

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        sezon = _sezon_opon(c, auto_id)
        for r in wiersze:
            poprawka = bool(r["wykonane"])
            if poprawka and (r["w_id"] is not None or r["h_wizyta"] is not None):
                continue  # wykonanie z wizyty poprawia się w wizycie
            koszt = _kwota(dane.get("koszt")) if jeden else _kwota(r["szacowany_koszt"])
            hid = r["h_id"]
            kid = r["k_id"]
            if powiazany and r["zadanie_id"]:
                if hid:
                    c.execute("UPDATE historia SET data=?, data_iso=?, przebieg=?, cena=?, zmodyfikowane_przez=?, "
                              "data_modyfikacji=? WHERE id=?",
                              (data, na_iso(data), przebieg_serwisu, koszt or 0.0, ja, podpis, hid))
                else:
                    rodzaj = domyslny_rodzaj_serwisu([r["zadanie_id"]], conn=conn)
                    hid = c.execute(
                        "INSERT INTO historia (wizyta_id, zadanie_id, data, data_iso, przebieg, cena, wykonawca, "
                        "kategoria, rodzaj, dodane_przez, notatka, notatka_autor, notatka_data) "
                        "VALUES (NULL,?,?,?,?,?,'',?,?,?,?,?,?)",
                        (r["zadanie_id"], data, na_iso(data), przebieg_serwisu, koszt or 0.0,
                         sezon if r["zadanie_opony"] else None, rodzaj, ja, notatka,
                         ja if notatka else None, podpis if notatka else None)).lastrowid
                wynik["serwis"] += 1
            elif hid:
                do_kosza["historia"].append(hid)
                hid = None
            if powiazany and not r["zadanie_id"] and koszt:
                if kid:
                    c.execute("UPDATE inne_koszty SET data=?, data_iso=?, nazwa=?, kwota=?, zmodyfikowane_przez=?, "
                              "data_modyfikacji=? WHERE id=?", (data, na_iso(data), r["tytul"], koszt, ja, podpis, kid))
                else:
                    kid = c.execute(
                        "INSERT INTO inne_koszty (auto_id, data, data_iso, kategoria, nazwa, kwota, dodane_przez, "
                        "notatka, notatka_autor, notatka_data) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (auto_id, data, na_iso(data), KATEGORIA_INNE_DOMYSLNA, r["tytul"], koszt, ja, notatka,
                         ja if notatka else None, podpis if notatka else None)).lastrowid
                wynik["koszty"] += 1
            elif kid:
                do_kosza["inne_koszty"].append(kid)
                kid = None
            c.execute("UPDATE do_zrobienia SET wykonane=1, data_wykonania=?, przebieg_wykonania=?, koszt_wykonania=?, "
                      "notatka_wykonania=?, wykonane_przez=?, historia_id=?, koszt_id=? WHERE id=?",
                      (data, przebieg, koszt, notatka, (r["wykonane_przez"] if poprawka else None) or ja,
                       hid, kid, r["id"]))
            zanotuj_zdarzenie_do_zrobienia(
                conn, r["id"], ZDARZENIE_POPRAWKA if poprawka else ZDARZENIE_WYKONANO,
                {"data": data, "przebieg": przebieg, "koszt": koszt, "notatka": notatka,
                 "serwis": bool(hid), "inny_koszt": bool(kid)}, ja)
            wynik["liczba"] += 1

    # Powiązanie zdjęte wyżej, więc kosz nie zapamięta odwołania z pozycji.
    for tabela, rekordy in do_kosza.items():
        if rekordy and usun_do_kosza(tabela, rekordy):
            wynik["do_kosza"] += len(rekordy)
    if wynik["serwis"] or do_kosza["historia"]:
        przelicz_wszystkie_zadania(auto_id)
    return wynik if wynik["liczba"] else None


def cofnij_wykonanie_do_zrobienia(pozycja_id) -> dict[str, Any] | None:
    """Pozycja wraca na listę; wpis serwisowy albo Inny koszt z jej wykonania idzie do kosza
    wpisów. Pozycji z wizyty nie rusza wizyty (zwrot pozycji z wizyty robi
    zwroc_pozycje_wizyty_do_zrobienia). Wynik {do_kosza, wizyta} albo None."""
    pozycja = pozycja_do_zrobienia(pozycja_id)
    if not pozycja or not pozycja["wykonane"] or not czy_moge_dodawac(pozycja["auto_id"]):
        return None
    ja = pobierz_moje_imie() or None
    wlasne = [] if pozycja["w_wizycie"] else [(t, i) for t, i in (("historia", pozycja["historia_id"]),
                                                                    ("inne_koszty", pozycja["koszt_id"])) if i]
    with polacz_baze() as conn:
        conn.execute("UPDATE do_zrobienia SET wykonane=0, data_wykonania=NULL, przebieg_wykonania=NULL, "
                     "koszt_wykonania=NULL, notatka_wykonania=NULL, wykonane_przez=NULL, historia_id=NULL, "
                     "koszt_id=NULL, wizyta_id=NULL WHERE id=?", (pozycja_id,))
        zanotuj_zdarzenie_do_zrobienia(conn, pozycja_id, ZDARZENIE_COFNIETO,
                                       {"data": pozycja["data_wykonania"]}, ja)
    usuniete = 0
    for tabela, rekord_id in wlasne:
        if usun_do_kosza(tabela, [rekord_id]):
            usuniete += 1
    if any(t == "historia" for t, _ in wlasne):
        przelicz_wszystkie_zadania(pozycja["auto_id"])
    return {"do_kosza": usuniete, "wizyta": bool(pozycja["wizyta_id"])}


def usun_zdarzenia_do_zrobienia(ids, auto_id=None):
    """Kasuje wpisy dziennika (cofnięcie operacji, która je dopisała); wysłane do chmury
    dostają nagrobek."""
    ids = [i for i in ids or [] if i]
    if not ids:
        return
    with polacz_baze() as conn:
        znaki = ",".join("?" * len(ids))
        zdalne = [w[0] for w in conn.execute(
            f"SELECT zdalne_id FROM do_zrobienia_zdarzenia WHERE id IN ({znaki}) AND zdalne_id IS NOT NULL",
            tuple(ids)).fetchall()]
        conn.execute(f"DELETE FROM do_zrobienia_zdarzenia WHERE id IN ({znaki})", tuple(ids))
    for z in zdalne:
        zarejestruj_nagrobek("do_zrobienia_zdarzenia", z, auto_id)


__all__ = [
    "ETYKIETY_ZDARZEN_DO_ZROBIENIA",
    "PROG_PILNEGO_PRZEBIEGU",
    "PRZESUNIECIA_PRZEBIEGU",
    "PRZESUNIECIA_TERMINU",
    "ZDARZENIE_COFNIETO",
    "ZDARZENIE_DODANO",
    "ZDARZENIE_POPRAWKA",
    "ZDARZENIE_TERMIN",
    "ZDARZENIE_WIZYTA",
    "ZDARZENIE_WYKONANO",
    "ZDARZENIE_ZMIANA",
    "ZDARZENIE_ZWROT",
    "cofnij_wykonanie_do_zrobienia",
    "oznacz_wykonane_do_zrobienia",
    "pobierz_pozycje_do_zrobienia",
    "pobierz_zdarzenia_do_zrobienia",
    "pozycja_do_zrobienia",
    "przesun_termin_do_zrobienia",
    "stan_terminu_przebiegowego",
    "termin_po_przesunieciu",
    "usun_zdarzenia_do_zrobienia",
    "zanotuj_zdarzenie_do_zrobienia",
    "zapisz_pozycje_do_zrobienia",
]
