"""Opony: wiek z kodu DOT, progi bieżnika zależne od sezonu, pomiary każdego koła, okresy montażu
kompletu (kilometry przejechane NA nim), tempo zużycia i prognoza, przechowalnia. Zmiana opon jako
zdarzenie (Serwis, koszt, przypomnienie, „Cofnij”) — db/zmiana_opon.py. Decyzje: archiwum `opony`."""

import re
import sqlite3
from datetime import date as date_cls, datetime, timedelta
from typing import Any

from date import na_iso, parsuj_date

from .stale import MIESIACE_ZIMOWE, SEZONY_OPON, SEZONY_PRZELACZALNE, TYP_CYKLICZNY_OPONY
from .pamiec import z_pamieci
from .polaczenie import polacz_baze
from .pomocnicze import _na_liczbe, liczba_na_tekst, liczba_z_odmiana
from .ustawienia import pobierz_moje_imie
from .jednostki import tekst_dystansu
from .synchronizacja import czy_moge_dodawac, czy_moge_zmieniac_rekord
from .przebieg import oblicz_sredni_dzienny_przebieg, pobierz_aktualny_przebieg, pobierz_historie_przebiegu
from .przebieg import szacuj_przebieg_w_dniu
from .magazyn import przelacz_zestaw_sezonowy
from .kosz_wpisow import usun_do_kosza


# Koła w kolejności pól formularza (jak na aucie widzianym z góry: przód na górze).
POZYCJE_KOL = ("lp", "pp", "lt", "pt")
SKROTY_KOL = {"lp": "LP", "pp": "PP", "lt": "LT", "pt": "PT"}
KOLA_OSI = {"Przód": ("lp", "pp"), "Tył": ("lt", "pt"), "Wszystkie": POZYCJE_KOL}

# 1,6 mm — minimum z rozporządzenia o warunkach technicznych pojazdów (§ 11); 3 i 4 mm — zalecenia
# producentów: letnie od 3 mm tracą na mokrym, zimowe i całoroczne poniżej 4 mm przestają trzymać zimą.
BIEZNIK_MINIMUM_PRAWNE = 1.6
PROGI_WYMIANY_BIEZNIKA = {"Letnie": 3.0, "Zimowe": 4.0, "Całoroczne": 4.0}
PROG_WYMIANY_DOMYSLNY = 3.0
# Bieżnik nowej opony — skala paska, dopóki komplet nie ma głębszego pomiaru.
BIEZNIK_NOWEJ_OPONY = {"Letnie": 8.0, "Zimowe": 9.0, "Całoroczne": 8.0}
MAKS_BIEZNIK = 15.0

# Wiek od daty produkcji z kodu DOT: od 5 lat kontrola co roku, najpóźniej po 10 latach wymiana.
WIEK_KONTROLI_OPON = 5
WIEK_WYMIANY_OPON = 10

STATUS_BIEZNIKA_OK, STATUS_BIEZNIKA_UWAGA, STATUS_BIEZNIKA_KRYTYCZNY = "ok", "uwaga", "krytyczny"
STATUS_WIEKU_OK, STATUS_WIEKU_KONTROLA, STATUS_WIEKU_WYMIANA = "ok", "kontrola", "wymiana"

MIN_KM_TEMPA = 1500        # km na komplecie między skrajnymi pomiarami — krócej to szum miarki
MIN_SPADEK_BIEZNIKA = 0.3  # mm — mniejszy spadek mieści się w dokładności pomiaru
ROZNICA_OSI_ZAMIANY = 1.0  # mm między osiami — czas zamienić przód z tyłem
MIN_KM_SEZONU = 300        # krótszy okres na aucie nie mówi, ile komplet robi w sezonie
MAKS_DNI_PROGNOZY = 3650

_GRUPA_DOT = re.compile(r"(?<!\d)\d{4}(?!\d)")


# ============================================================================
#  WIEK Z KODU DOT
# ============================================================================

def _dzien_tygodnia_produkcji(rok, tydzien):
    try:
        return date_cls.fromisocalendar(rok, tydzien, 1)
    except ValueError:
        return date_cls(rok, 1, 1) + timedelta(weeks=tydzien - 1)


def daty_produkcji(numer_dot, dzis=None) -> list[date_cls]:
    """Daty produkcji z pola DOT: grupa TTRR (tydzień, rok od 2000) — kilka kodów po przecinku
    („2321, 0222”) albo spacji, z pełnego kodu z literami („DOT 3X 4Y ABCD 2321”) tylko ostatnia
    grupa. Tydzień 1–53, rok nie z przyszłości; od najstarszej."""
    dzis = dzis or datetime.now().date()
    wynik = []
    for czesc in re.split(r"[,;/\n]+", str(numer_dot or "")):
        grupy = _GRUPA_DOT.findall(czesc)
        if re.search(r"[A-Za-z]", czesc):
            grupy = grupy[-1:]
        for grupa in grupy:
            tydzien, rok = int(grupa[:2]), 2000 + int(grupa[2:])
            if not 1 <= tydzien <= 53:
                continue
            dzien = _dzien_tygodnia_produkcji(rok, tydzien)
            if dzien <= dzis + timedelta(days=7):
                wynik.append(dzien)
    return sorted(set(wynik))


def _dodaj_lata(dzien, lata):
    try:
        return dzien.replace(year=dzien.year + lata)
    except ValueError:
        return dzien.replace(year=dzien.year + lata, day=28)


def wiek_opon(numer_dot, dzis=None) -> dict[str, Any] | None:
    """Wiek NAJSTARSZEJ opony kompletu: data, lata (float), miesiace (pełne), status
    („ok” / „kontrola” / „wymiana”), data_kontroli, data_wymiany, kodow. None bez kodu z datą."""
    dzis = dzis or datetime.now().date()
    daty = daty_produkcji(numer_dot, dzis)
    if not daty:
        return None
    najstarsza = daty[0]
    miesiace = max(0, (dzis.year - najstarsza.year) * 12 + dzis.month - najstarsza.month
                   - (1 if dzis.day < najstarsza.day else 0))
    lata = max(0.0, (dzis - najstarsza).days / 365.25)
    status = (STATUS_WIEKU_WYMIANA if lata >= WIEK_WYMIANY_OPON
              else STATUS_WIEKU_KONTROLA if lata >= WIEK_KONTROLI_OPON else STATUS_WIEKU_OK)
    return {"data": najstarsza, "lata": lata, "miesiace": miesiace, "status": status,
            "data_kontroli": _dodaj_lata(najstarsza, WIEK_KONTROLI_OPON),
            "data_wymiany": _dodaj_lata(najstarsza, WIEK_WYMIANY_OPON), "kodow": len(daty)}


def tekst_wieku(wiek) -> str | None:
    """„8 mies.”, „3 lata”, „11 lat” — None bez wieku."""
    if not wiek:
        return None
    if wiek["miesiace"] < 12:
        return f"{max(1, wiek['miesiace'])} mies."
    return liczba_z_odmiana(wiek["miesiace"] // 12, "rok", "lata", "lat")


# ============================================================================
#  BIEŻNIK: PROGI I TEKSTY
# ============================================================================

def prog_wymiany(sezon) -> float:
    return PROGI_WYMIANY_BIEZNIKA.get(str(sezon or ""), PROG_WYMIANY_DOMYSLNY)


def status_bieznika(mm, sezon) -> str | None:
    """„krytyczny” poniżej minimum prawnego, „uwaga” poniżej zalecanego dla sezonu, inaczej „ok”."""
    mm = _na_liczbe(mm)
    if mm is None:
        return None
    if mm < BIEZNIK_MINIMUM_PRAWNE:
        return STATUS_BIEZNIKA_KRYTYCZNY
    return STATUS_BIEZNIKA_UWAGA if mm < prog_wymiany(sezon) else STATUS_BIEZNIKA_OK


def udzial_bieznika(mm, sezon, nowy=None) -> float | None:
    """Jaka część bieżnika do zużycia zostaje (0–1): od minimum prawnego do bieżnika nowej opony
    albo najgłębszego pomiaru kompletu."""
    mm = _na_liczbe(mm)
    if mm is None:
        return None
    gora = max(_na_liczbe(nowy) or 0.0, BIEZNIK_NOWEJ_OPONY.get(str(sezon or ""), 8.0))
    return max(0.0, min(1.0, (mm - BIEZNIK_MINIMUM_PRAWNE) / max(0.1, gora - BIEZNIK_MINIMUM_PRAWNE)))


def tekst_bieznika(mm) -> str | None:
    """„6,6 mm”, „4 mm” — None bez pomiaru."""
    tekst = liczba_na_tekst(mm, 1)
    if tekst is None:
        return None
    return f"{tekst[:-2] if tekst.endswith(',0') else tekst} mm"


def wartosci_kol(pomiar) -> dict[str, float]:
    """{pozycja: mm} kół z pomiarem (słownik wiersza albo wynik pobierz_pomiary)."""
    wynik = {}
    for kolo in POZYCJE_KOL:
        mm = _na_liczbe((pomiar or {}).get(kolo))
        if mm is not None:
            wynik[kolo] = mm
    return wynik


def najplytszy_bieznik(pomiar) -> float | None:
    kola = wartosci_kol(pomiar)
    return min(kola.values()) if kola else None


def roznica_osi(pomiar) -> float | None:
    """Średnia przodu minus średnia tyłu (mm) — ujemna: przód płytszy. None bez obu osi."""
    kola = wartosci_kol(pomiar)
    przod = [kola[k] for k in KOLA_OSI["Przód"] if k in kola]
    tyl = [kola[k] for k in KOLA_OSI["Tył"] if k in kola]
    if not przod or not tyl:
        return None
    return sum(przod) / len(przod) - sum(tyl) / len(tyl)


# ============================================================================
#  POMIARY
# ============================================================================

def _pomiar(r) -> dict[str, Any]:
    pomiar = dict(r)
    pomiar["kola"] = wartosci_kol(pomiar)
    pomiar["min"] = min(pomiar["kola"].values()) if pomiar["kola"] else None
    pomiar["max"] = max(pomiar["kola"].values()) if pomiar["kola"] else None
    pomiar["dawny"] = False
    return pomiar


def pobierz_pomiary(auto_id, zestaw_id=None) -> list[dict[str, Any]]:
    """Pomiary bieżnika pojazdu (albo kompletu) od najstarszego."""
    if not auto_id:
        return []
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        zapytanie = "SELECT * FROM pomiary_bieznika WHERE auto_id=?"
        argumenty = [auto_id]
        if zestaw_id:
            zapytanie += " AND zestaw_id=?"
            argumenty.append(zestaw_id)
        wiersze = conn.execute(zapytanie + " ORDER BY data_iso, id", argumenty).fetchall()
    return [_pomiar(r) for r in wiersze]


def pobierz_pomiar(pomiar_id) -> dict[str, Any] | None:
    if not pomiar_id:
        return None
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        r = conn.execute("SELECT * FROM pomiary_bieznika WHERE id=?", (pomiar_id,)).fetchone()
    return _pomiar(r) if r else None


def _dawny_pomiar(zestaw, pomiary):
    """Bieżnik zapisany w samym komplecie (sprzed pomiarów albo ze starszej wersji aplikacji na drugim
    telefonie) jako pomiar wszystkich kół — tylko bez pomiarów albo gdy jest od nich nowszy."""
    mm = _na_liczbe(zestaw.get("glebokosc_bieznika"))
    if mm is None:
        return None
    dzien = parsuj_date(zestaw.get("data_pomiaru"))
    znana = dzien != datetime.min.date()
    if pomiary:
        ostatni = parsuj_date(pomiary[-1]["data"])
        if not znana or dzien <= ostatni:
            return None
    pomiar = {"id": None, "zestaw_id": zestaw["id"], "data": zestaw.get("data_pomiaru") if znana else None,
              "data_iso": dzien.isoformat() if znana else None, "przebieg": None, "uwagi": None,
              "dodane_przez": None, **{k: mm for k in POZYCJE_KOL}}
    pomiar = _pomiar(pomiar)
    pomiar["dawny"] = True
    return pomiar


def blad_pomiaru(dane) -> str | None:
    """Treść błędu albo None: dzień, choć jedno koło, każde w 0–15 mm."""
    if parsuj_date(dane.get("data")) == datetime.min.date():
        return "Wybierz dzień pomiaru"
    kola = [dane.get(k) for k in POZYCJE_KOL if str(dane.get(k) if dane.get(k) is not None else "").strip()]
    if not kola:
        return "Wpisz bieżnik choć jednego koła"
    for wartosc in kola:
        mm = _na_liczbe(wartosc)
        if mm is None or mm < 0 or mm > MAKS_BIEZNIK:
            return "Bieżnik to od 0 do 15 mm"
    return None


def _odswiez_bieznik_kompletu(conn, zestaw_id):
    """Najpłytsze koło i dzień ostatniego pomiaru w samym komplecie — to czytają starsze wersje
    aplikacji i drugi telefon sprzed aktualizacji. Bez pomiarów — puste."""
    r = conn.execute("SELECT * FROM pomiary_bieznika WHERE zestaw_id=? ORDER BY data_iso DESC, id DESC LIMIT 1",
                     (zestaw_id,)).fetchone()
    if r:
        kola = [r[k] for k in POZYCJE_KOL if r[k] is not None]
        conn.execute("UPDATE zestawy_opon SET glebokosc_bieznika=?, data_pomiaru=? WHERE id=?",
                     (min(kola) if kola else None, r["data"], zestaw_id))
    else:
        conn.execute("UPDATE zestawy_opon SET glebokosc_bieznika=NULL, data_pomiaru=NULL WHERE id=?", (zestaw_id,))


def zapisz_pomiar(auto_id, zestaw_id, dane, pomiar_id=None) -> int | None:
    """Nowy albo poprawiany pomiar; id albo None (błąd danych, brak prawa, brak kompletu). `dane`:
    data, przebieg (km albo None), lp, pp, lt, pt (mm albo puste), uwagi. Bieżnik zapisany dotąd tylko
    w komplecie (z datą) zostaje przy pierwszym pomiarze jego najstarszym pomiarem."""
    if not auto_id or blad_pomiaru(dane):
        return None
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        zestaw = conn.execute("SELECT * FROM zestawy_opon WHERE id=? AND auto_id=?", (zestaw_id, auto_id)).fetchone()
        stary = conn.execute("SELECT * FROM pomiary_bieznika WHERE id=? AND auto_id=?",
                             (pomiar_id, auto_id)).fetchone() if pomiar_id else None
    if not zestaw or (pomiar_id and not stary):
        return None
    if stary and not czy_moge_zmieniac_rekord(auto_id, "pomiary_bieznika", stary["dodane_przez"]):
        return None
    if not stary and not czy_moge_dodawac(auto_id):
        return None

    data = str(dane["data"]).strip()
    kola = [round(_na_liczbe(dane.get(k)), 1) if _na_liczbe(dane.get(k)) is not None else None for k in POZYCJE_KOL]
    przebieg = _na_liczbe(dane.get("przebieg"))
    przebieg = int(przebieg) if przebieg and przebieg > 0 else None
    uwagi = str(dane.get("uwagi") or "").strip() or None
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        if stary:
            c.execute("UPDATE pomiary_bieznika SET data=?, data_iso=?, przebieg=?, lp=?, pp=?, lt=?, pt=?, uwagi=? "
                      "WHERE id=?", (data, na_iso(data), przebieg, *kola, uwagi, pomiar_id))
            wynik = pomiar_id
        else:
            if not c.execute("SELECT 1 FROM pomiary_bieznika WHERE zestaw_id=?", (zestaw_id,)).fetchone():
                dawny = _dawny_pomiar(dict(zestaw), [])
                if dawny and dawny["data"] and parsuj_date(dawny["data"]) < parsuj_date(data):
                    c.execute("INSERT INTO pomiary_bieznika (auto_id, zestaw_id, data, data_iso, lp, pp, lt, pt, "
                              "dodane_przez) VALUES (?,?,?,?,?,?,?,?,?)",
                              (auto_id, zestaw_id, dawny["data"], na_iso(dawny["data"]),
                               *[dawny[k] for k in POZYCJE_KOL], pobierz_moje_imie()))
            wynik = c.execute(
                "INSERT INTO pomiary_bieznika (auto_id, zestaw_id, data, data_iso, przebieg, lp, pp, lt, pt, uwagi, "
                "dodane_przez) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (auto_id, zestaw_id, data, na_iso(data), przebieg, *kola, uwagi, pobierz_moje_imie())).lastrowid
        _odswiez_bieznik_kompletu(conn, zestaw_id)
    return wynik


def usun_pomiar_z_cofnieciem(pomiar_id) -> dict[str, Any] | None:
    """Pomiar do kosza wpisów (wynik jak usun_z_cofnieciem); bieżnik kompletu wraca do poprzedniego."""
    pomiar = pobierz_pomiar(pomiar_id)
    if not pomiar:
        return None
    wynik = usun_do_kosza("pomiary_bieznika", [pomiar_id])
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        _odswiez_bieznik_kompletu(conn, pomiar["zestaw_id"])
    return wynik


# ============================================================================
#  OKRESY MONTAŻU
# ============================================================================

def pobierz_montaze(auto_id, zestaw_id=None) -> list[dict[str, Any]]:
    """Okresy montażu (od najstarszego); `data_zdjecia` NULL — komplet jest na aucie."""
    if not auto_id:
        return []
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        zapytanie = "SELECT * FROM montaze_opon WHERE auto_id=?"
        argumenty = [auto_id]
        if zestaw_id:
            zapytanie += " AND zestaw_id=?"
            argumenty.append(zestaw_id)
        return [dict(r) for r in conn.execute(zapytanie + " ORDER BY data_iso, id", argumenty).fetchall()]


def flagi_montazu(conn, auto_id) -> dict[int, str]:
    """{id kompletu: oś} zamontowanych kompletów pojazdu."""
    return {r[0]: str(r[1] or "Wszystkie") for r in conn.execute(
        "SELECT id, os_montazu FROM zestawy_opon WHERE auto_id=? AND zamontowane=1", (auto_id,)).fetchall()}


def zapisz_okresy_montazu(conn, auto_id, przed, po, data, przebieg=None, otwieraj=True) -> dict[str, list[int]]:
    """Dziennik montażu po zmianie flag `przed` → `po` ({id: oś}): zamyka otwarte okresy kompletów
    zdjętych albo przełożonych na inną oś (i te bez flagi — ślad zmiany z innego telefonu), otwiera
    okres dla założonych. Zwraca {"zamkniete", "otwarte"} (id okresów)."""
    data = str(data).strip()
    zmienione = {z for z in set(przed) | set(po) if przed.get(z) != po.get(z)}
    zamkniete, otwarte = [], []
    for r in conn.execute("SELECT id, zestaw_id FROM montaze_opon WHERE auto_id=? AND data_zdjecia IS NULL",
                          (auto_id,)).fetchall():
        if r[1] in zmienione or r[1] not in po:
            conn.execute("UPDATE montaze_opon SET data_zdjecia=?, przebieg_zdjecia=? WHERE id=?",
                         (data, przebieg, r[0]))
            zamkniete.append(r[0])
    if otwieraj:
        ja = pobierz_moje_imie()
        for zestaw_id in sorted(z for z in zmienione if z in po):
            otwarte.append(conn.execute(
                "INSERT INTO montaze_opon (auto_id, zestaw_id, os_montazu, data, data_iso, przebieg, dodane_przez) "
                "VALUES (?,?,?,?,?,?,?)", (auto_id, zestaw_id, po[zestaw_id], data, na_iso(data), przebieg, ja)).lastrowid)
    return {"zamkniete": zamkniete, "otwarte": otwarte}


def przelacz_komplet_sezonowy(auto_id, docelowy_sezon=None) -> dict[str, Any]:
    """przelacz_zestaw_sezonowy z dziennikiem montażu (dziś, licznik z historii) — droga bez okna
    zmiany: „Wykonano” przypomnienia przy braku drugiego kompletu i starsze wywołania."""
    with polacz_baze() as conn:
        przed = flagi_montazu(conn, auto_id)
    wynik = przelacz_zestaw_sezonowy(auto_id, docelowy_sezon)
    if wynik.get("ok"):
        data = datetime.now().strftime("%d.%m.%Y")
        przebieg = szacuj_przebieg_w_dniu(auto_id, data) or pobierz_aktualny_przebieg(auto_id) or None
        with polacz_baze() as conn:
            zapisz_okresy_montazu(conn, auto_id, przed, flagi_montazu(conn, auto_id), data, przebieg)
    return wynik


def wpisy_zmian_opon(auto_id) -> list[dict[str, Any]]:
    """Wpisy serwisowe podzespołów opon z rodzajem opon (sezonem założonych) — od najstarszego."""
    if not auto_id:
        return []
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        wiersze = conn.execute(
            "SELECT h.id, h.data, h.data_iso, h.przebieg, h.kategoria, h.cena, h.wykonawca FROM historia h "
            "JOIN zadania z ON h.zadanie_id = z.id WHERE z.auto_id=? AND z.dotyczy_opon=1 "
            f"AND h.kategoria IN ({','.join('?' * len(SEZONY_OPON))}) ORDER BY h.data_iso, h.id",
            (auto_id, *SEZONY_OPON)).fetchall()
    return [dict(r) for r in wiersze if parsuj_date(r["data"]) != datetime.min.date()]


def propozycja_poczatku_montazu(auto_id, zestaw_id, dzis=None) -> dict[str, Any]:
    """Od kiedy komplet stoi na aucie: ostatnia zmiana opon jego sezonu z Serwisu (dzień, licznik,
    wpis), inaczej pusta propozycja."""
    dzis = dzis or datetime.now().date()
    with polacz_baze() as conn:
        w = conn.execute("SELECT sezon FROM zestawy_opon WHERE id=? AND auto_id=?", (zestaw_id, auto_id)).fetchone()
    sezon = str(w[0] or "") if w else ""
    pasujace = [h for h in wpisy_zmian_opon(auto_id) if h["kategoria"] == sezon and parsuj_date(h["data"]) <= dzis]
    if not pasujace:
        return {"data": None, "przebieg": None, "historia_id": None}
    h = pasujace[-1]
    return {"data": parsuj_date(h["data"]).strftime("%d.%m.%Y"), "przebieg": int(h["przebieg"] or 0) or None,
            "historia_id": h["id"]}


def ustaw_poczatek_montazu(auto_id, zestaw_id, data, przebieg=None, historia_id=None) -> int | None:
    """Otwiera okres zamontowanego kompletu, który go nie ma (komplet sprzed dziennika albo zmiana
    z innego telefonu); stare otwarte okresy zdjętych kompletów zamyka tym dniem. Id okresu albo None."""
    if not auto_id or not czy_moge_dodawac(auto_id) or parsuj_date(data) == datetime.min.date():
        return None
    data = str(data).strip()
    przebieg = int(_na_liczbe(przebieg)) if _na_liczbe(przebieg) else None
    with polacz_baze() as conn:
        flagi = flagi_montazu(conn, auto_id)
        if zestaw_id not in flagi or conn.execute(
                "SELECT 1 FROM montaze_opon WHERE zestaw_id=? AND data_zdjecia IS NULL", (zestaw_id,)).fetchone():
            return None
        for r in conn.execute("SELECT id, zestaw_id FROM montaze_opon WHERE auto_id=? AND data_zdjecia IS NULL",
                              (auto_id,)).fetchall():
            if r[1] not in flagi:
                conn.execute("UPDATE montaze_opon SET data_zdjecia=?, przebieg_zdjecia=? WHERE id=?",
                             (data, przebieg, r[0]))
        return conn.execute(
            "INSERT INTO montaze_opon (auto_id, zestaw_id, os_montazu, data, data_iso, przebieg, historia_id, "
            "dodane_przez) VALUES (?,?,?,?,?,?,?,?)",
            (auto_id, zestaw_id, flagi[zestaw_id], data, na_iso(data), przebieg, historia_id,
             pobierz_moje_imie())).lastrowid


def blad_okresu(dane, otwarty=False) -> str | None:
    poczatek = parsuj_date(dane.get("data"))
    if poczatek == datetime.min.date():
        return "Wybierz dzień założenia"
    if otwarty:
        return None
    koniec = parsuj_date(dane.get("data_zdjecia"))
    if koniec == datetime.min.date():
        return "Wybierz dzień zdjęcia"
    if koniec < poczatek:
        return "Zdjęcie nie może być przed założeniem"
    km_od, km_do = _na_liczbe(dane.get("przebieg")), _na_liczbe(dane.get("przebieg_zdjecia"))
    if km_od and km_do and km_do < km_od:
        return "Licznik przy zdjęciu mniejszy niż przy założeniu"
    return None


def zapisz_okres_montazu(montaz_id, dane) -> bool:
    """Poprawka okresu: dzień i licznik założenia, przy zdjętym też zdjęcia."""
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        m = conn.execute("SELECT * FROM montaze_opon WHERE id=?", (montaz_id,)).fetchone()
    otwarty = bool(m) and m["data_zdjecia"] is None
    if not m or not czy_moge_dodawac(m["auto_id"]) or blad_okresu(dane, otwarty):
        return False

    def km(wartosc):
        liczba = _na_liczbe(wartosc)
        return int(liczba) if liczba and liczba > 0 else None

    data = str(dane["data"]).strip()
    with polacz_baze() as conn:
        if otwarty:
            conn.execute("UPDATE montaze_opon SET data=?, data_iso=?, przebieg=? WHERE id=?",
                         (data, na_iso(data), km(dane.get("przebieg")), montaz_id))
        else:
            conn.execute("UPDATE montaze_opon SET data=?, data_iso=?, przebieg=?, data_zdjecia=?, przebieg_zdjecia=? "
                         "WHERE id=?", (data, na_iso(data), km(dane.get("przebieg")),
                                        str(dane["data_zdjecia"]).strip(), km(dane.get("przebieg_zdjecia")), montaz_id))
    return True


def usun_okres_z_cofnieciem(montaz_id) -> dict[str, Any] | None:
    with polacz_baze() as conn:
        w = conn.execute("SELECT auto_id FROM montaze_opon WHERE id=?", (montaz_id,)).fetchone() if montaz_id else None
    if not w or not czy_moge_dodawac(w[0]):
        return None
    return usun_do_kosza("montaze_opon", [montaz_id])


def odtworz_sezony_z_serwisu(auto_id, dzis=None) -> int:
    """Okresy montażu z wpisów zmiany opon w Serwisie — tylko auto bez dziennika i tylko sezony
    z jednym kompletem. Okres trwa do następnej zmiany; ostatni zostaje otwarty, jeśli jego komplet
    jest na aucie. Zwraca liczbę zapisanych okresów."""
    dzis = dzis or datetime.now().date()
    if not auto_id or not czy_moge_dodawac(auto_id):
        return 0
    wpisy = [h for h in wpisy_zmian_opon(auto_id) if parsuj_date(h["data"]) <= dzis]
    ja = pobierz_moje_imie()
    zapisane = 0
    with polacz_baze() as conn:
        if conn.execute("SELECT 1 FROM montaze_opon WHERE auto_id=?", (auto_id,)).fetchone():
            return 0
        komplety = {}
        for r in conn.execute("SELECT id, sezon FROM zestawy_opon WHERE auto_id=?", (auto_id,)).fetchall():
            komplety.setdefault(str(r[1] or ""), []).append(r[0])
        jedyne = {sezon: ids[0] for sezon, ids in komplety.items() if len(ids) == 1}
        flagi = flagi_montazu(conn, auto_id)
        # Ta sama pora roku dwa razy z rzędu (np. naprawa po przebiciu) to dalej ten sam okres.
        zmiany = [h for i, h in enumerate(wpisy) if i == 0 or h["kategoria"] != wpisy[i - 1]["kategoria"]]
        for i, h in enumerate(zmiany):
            zestaw_id = jedyne.get(h["kategoria"])
            if not zestaw_id:
                continue
            nastepna = zmiany[i + 1] if i + 1 < len(zmiany) else None
            if nastepna is None and zestaw_id not in flagi:
                continue
            data = parsuj_date(h["data"]).strftime("%d.%m.%Y")
            koniec = parsuj_date(nastepna["data"]).strftime("%d.%m.%Y") if nastepna else None
            conn.execute(
                "INSERT INTO montaze_opon (auto_id, zestaw_id, os_montazu, data, data_iso, przebieg, data_zdjecia, "
                "przebieg_zdjecia, historia_id, dodane_przez) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (auto_id, zestaw_id, flagi.get(zestaw_id, "Wszystkie") if nastepna is None else "Wszystkie",
                 data, na_iso(data), int(h["przebieg"] or 0) or None, koniec,
                 (int(nastepna["przebieg"] or 0) or None) if nastepna else None, h["id"], ja))
            zapisane += 1
    return zapisane


# ============================================================================
#  KILOMETRY NA KOMPLECIE I PROGNOZA
# ============================================================================

class _Licznik:
    """Stan licznika w dniu z historii licznika (jedno pobranie na przeliczenie)."""

    def __init__(self, auto_id):
        self.auto_id = auto_id
        self.punkty = pobierz_historie_przebiegu(auto_id)
        self.teraz = pobierz_aktualny_przebieg(auto_id) or None

    def w_dniu(self, dzien):
        if not isinstance(dzien, date_cls):
            dzien = parsuj_date(dzien)
        if dzien == datetime.min.date():
            return None
        return szacuj_przebieg_w_dniu(self.auto_id, dzien.strftime("%d.%m.%Y"), punkty=self.punkty)


def _km_okresu(m, licznik, do_dnia=None, przebieg_w_dniu=None):
    """Kilometry okresu (do `do_dnia`, jeśli wypada w środku). None przy nieznanym liczniku."""
    poczatek = parsuj_date(m["data"])
    if do_dnia is not None and do_dnia < poczatek:
        return 0
    start = _na_liczbe(m["przebieg"]) or licznik.w_dniu(poczatek)
    zdjety = parsuj_date(m["data_zdjecia"]) if m["data_zdjecia"] else None
    if zdjety and (do_dnia is None or do_dnia >= zdjety):
        koniec = _na_liczbe(m["przebieg_zdjecia"]) or licznik.w_dniu(zdjety)
    elif do_dnia is not None:
        koniec = przebieg_w_dniu or licznik.w_dniu(do_dnia)
    else:
        koniec = licznik.teraz
    if not start or not koniec:
        return None
    return max(0, int(koniec - start))


def _km_na_komplecie(montaze, licznik, do_dnia=None, przebieg_w_dniu=None):
    """(km, pełne) — suma okresów; pełne=False, gdy któregoś okresu nie dało się policzyć."""
    suma, pelne = 0, True
    for m in montaze:
        km = _km_okresu(m, licznik, do_dnia, przebieg_w_dniu)
        if km is None:
            pelne = False
        else:
            suma += km
    return suma, pelne


def tempo_zuzycia(punkty) -> float | None:
    """mm na 1000 km z par (km na komplecie, najpłytsze koło) — prosta najmniejszych kwadratów. None
    przy rozstępie krótszym niż MIN_KM_TEMPA, spadku mniejszym niż MIN_SPADEK_BIEZNIKA albo bez spadku."""
    punkty = [(float(km), float(mm)) for km, mm in punkty if km is not None and mm is not None]
    if len(punkty) < 2:
        return None
    kms = [p[0] for p in punkty]
    if max(kms) - min(kms) < MIN_KM_TEMPA:
        return None
    pierwszy, ostatni = min(punkty), max(punkty)
    if pierwszy[1] - ostatni[1] < MIN_SPADEK_BIEZNIKA:
        return None
    sr_km = sum(kms) / len(kms)
    sr_mm = sum(p[1] for p in punkty) / len(punkty)
    licznik = sum((km - sr_km) * (mm - sr_mm) for km, mm in punkty)
    mianownik = sum((km - sr_km) ** 2 for km in kms)
    if mianownik <= 0 or licznik >= 0:
        return None
    return -licznik / mianownik * 1000


def _miesiace_sezonu(sezon):
    if sezon == "Zimowe":
        return set(MIESIACE_ZIMOWE)
    if sezon == "Letnie":
        return set(range(1, 13)) - set(MIESIACE_ZIMOWE)
    return set(range(1, 13))


def _dni_sezonu_w_roku(sezon):
    miesiace = _miesiace_sezonu(sezon)
    return sum(1 for d in range(365) if (date_cls(2025, 1, 1) + timedelta(days=d)).month in miesiace)


def _data_prognozy(zostalo_km, sredni_dzienny, sezon, zamontowany, sezonowy, koniec_montazu, dzis):
    """Dzień, w którym komplet przejedzie `zostalo_km`: na aucie do końca bieżącego montażu, potem
    w swoich miesiącach (sezonowy z parą) albo cały czas (bez pary). Komplet bez pary w magazynie — None."""
    if not sredni_dzienny or sredni_dzienny <= 0:
        return None
    if not zamontowany and not sezonowy:
        return None
    miesiace = _miesiace_sezonu(sezon) if sezonowy else set(range(1, 13))
    suma = 0.0
    for przesuniecie in range(1, MAKS_DNI_PROGNOZY + 1):
        dzien = dzis + timedelta(days=przesuniecie)
        if zamontowany and (koniec_montazu is None or dzien < koniec_montazu):
            jezdzi = True
        else:
            jezdzi = dzien.month in miesiace and (sezonowy or zamontowany)
        if jezdzi:
            suma += sredni_dzienny
            if suma >= zostalo_km:
                return dzien
    return None


def _prognoza(komplet, punkty, km_teraz, sredni_dzienny, sezonowy, koniec_montazu, dzis):
    """Tempo, szacowany bieżnik dziś, kilometry i sezony do progu wymiany, dzień — albo None bez tempa."""
    tempo = tempo_zuzycia(punkty)
    ostatni = komplet["ostatni_pomiar"]
    if tempo is None or not ostatni or ostatni["min"] is None:
        return None
    km_pomiaru = punkty[-1][0] if punkty else None
    przejechane = max(0, (km_teraz or 0) - (km_pomiaru or 0)) if km_teraz is not None and km_pomiaru is not None else 0
    teraz_mm = max(0.0, ostatni["min"] - tempo * przejechane / 1000)
    cel = prog_wymiany(komplet["sezon"])
    if teraz_mm <= cel:
        cel = BIEZNIK_MINIMUM_PRAWNE
    zostalo = max(0, int(round((teraz_mm - cel) / tempo * 1000))) if teraz_mm > cel else 0
    km_sezonu = komplet["km_sezonu"]
    if km_sezonu is None and sezonowy and sredni_dzienny:
        km_sezonu = sredni_dzienny * _dni_sezonu_w_roku(komplet["sezon"])
    return {
        "tempo": tempo, "teraz_mm": teraz_mm, "cel_mm": cel, "zostalo_km": zostalo,
        "ponizej_zalecanego": cel == BIEZNIK_MINIMUM_PRAWNE,
        "sezonow": zostalo / km_sezonu if sezonowy and km_sezonu else None,
        "data": _data_prognozy(zostalo, sredni_dzienny, komplet["sezon"], komplet["zamontowany"], sezonowy,
                               koniec_montazu, dzis) if zostalo else dzis,
    }


def tekst_sezonow(sezonow) -> str | None:
    """„mniej niż sezon”, „ok. 1 sezon”, „ok. 2 sezony”, „ok. 3,5 sezonu” — None bez liczby."""
    if sezonow is None:
        return None
    if sezonow < 0.75:
        return "mniej niż sezon"
    polowki = round(sezonow * 2) / 2
    if polowki != int(polowki):
        return f"ok. {liczba_na_tekst(polowki, 1)} sezonu"
    return "ok. " + liczba_z_odmiana(int(polowki), "sezon", "sezony", "sezonów")


def _termin_zmiany(auto_id):
    """Dzień z przypomnienia o sezonowej zmianie opon albo None."""
    with polacz_baze() as conn:
        daty = [parsuj_date(r[0]) for r in conn.execute(
            "SELECT nastepna_data FROM wydatki_cykliczne WHERE auto_id=? AND typ=?", (auto_id, TYP_CYKLICZNY_OPONY))]
    daty = [d for d in daty if d != datetime.min.date()]
    return min(daty) if daty else None


_KOLUMNY_KOMPLETU = ("id, sezon, rozmiar, marka_model, glebokosc_bieznika, data_pomiaru, numer_dot, ilosc, zamontowane, "
                     "os_montazu, data_zakupu, przebieg_zakupu, cena, notatki, miejsce, numer_kwitu, "
                     "oplata_przechowania, na_felgach, felgi")


def _puste_dane_opon():
    return {"komplety": [], "zamontowane": [], "termin_zmiany": None, "brak_poczatku": [],
            "do_odtworzenia": 0, "sredni_dzienny": None, "jest_dziennik": False}


def _koniec_sezonu(sezon, dzis):
    """Pierwszy dzień po najbliższym (albo trwającym) sezonie kompletu — wtedy zwykle się go zdejmuje."""
    miesiace = _miesiace_sezonu(sezon)
    dzien = dzis
    for _ in range(400):
        if dzien.month in miesiace:
            break
        dzien += timedelta(days=1)
    for _ in range(400):
        if dzien.month not in miesiace:
            return dzien
        dzien += timedelta(days=1)
    return None


def _policz_dane_opon(auto_id, dzis):
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        wiersze = [dict(r) for r in conn.execute(
            f"SELECT {_KOLUMNY_KOMPLETU} FROM zestawy_opon WHERE auto_id=?", (auto_id,)).fetchall()]
    if not wiersze:
        return _puste_dane_opon()

    pomiary, montaze = pobierz_pomiary(auto_id), pobierz_montaze(auto_id)
    licznik = _Licznik(auto_id)
    sredni_dzienny = oblicz_sredni_dzienny_przebieg(auto_id, punkty=licznik.punkty)
    termin = _termin_zmiany(auto_id)
    sezony = {str(w["sezon"] or "") for w in wiersze}
    para = all(s in sezony for s in SEZONY_PRZELACZALNE)

    komplety = []
    for w in wiersze:
        sezon = str(w["sezon"] or "")
        k = {**w, "sezon": sezon, "zamontowany": bool(w["zamontowane"]), "os": str(w["os_montazu"] or "Wszystkie")}
        k["pomiary"] = [p for p in pomiary if p["zestaw_id"] == w["id"]]
        dawny = _dawny_pomiar(w, k["pomiary"])
        if dawny:
            k["pomiary"] = k["pomiary"] + [dawny]
        k["ostatni_pomiar"] = k["pomiary"][-1] if k["pomiary"] else None
        k["bieznik"] = k["ostatni_pomiar"]["min"] if k["ostatni_pomiar"] else None
        k["status_bieznika"] = status_bieznika(k["bieznik"], sezon)
        k["prog_wymiany"] = prog_wymiany(sezon)
        najglebszy = max((p["max"] for p in k["pomiary"] if p["max"] is not None), default=None)
        k["udzial"] = udzial_bieznika(k["bieznik"], sezon, najglebszy)
        k["roznica_osi"] = roznica_osi(k["ostatni_pomiar"]) if k["ostatni_pomiar"] else None
        k["wiek"] = wiek_opon(w["numer_dot"], dzis)

        k["montaze"] = [m for m in montaze if m["zestaw_id"] == w["id"]]
        k["otwarty"] = next((m for m in reversed(k["montaze"]) if m["data_zdjecia"] is None), None)
        if k["otwarty"] and not k["zamontowany"]:
            k["otwarty"] = None  # ślad zmiany z innego telefonu: komplet zdjęto bez dziennika
        for m in k["montaze"]:
            m["trwa"] = m is k["otwarty"]
            m["km"] = _km_okresu(m, licznik) if m["data_zdjecia"] or m["trwa"] else None
        liczone = [m for m in k["montaze"] if m["data_zdjecia"] is not None or m is k["otwarty"]]
        k["km"], k["km_pelne"] = _km_na_komplecie(liczone, licznik) if liczone else (None, True)
        k["km_biezacy"] = _km_okresu(k["otwarty"], licznik) if k["otwarty"] else None
        sezony_km = [km for km in (_km_okresu(m, licznik) for m in k["montaze"] if m["data_zdjecia"])
                     if km is not None and km >= MIN_KM_SEZONU]
        k["km_sezonu"] = sum(sezony_km) / len(sezony_km) if sezony_km else None
        cena = _na_liczbe(w["cena"])
        k["koszt_1000"] = cena / k["km"] * 1000 if cena and cena > 0 and k["km"] and k["km"] >= 1000 else None

        # Kilometry kompletu w dniu pomiaru: z okresów montażu, a zamontowany bez dziennika (opony
        # całoroczne, komplet sprzed aktualizacji) — sam licznik auta; liczy się tylko różnica.
        punkty = []
        for p in k["pomiary"]:
            if not p["data"] or p["min"] is None:
                continue
            dzien, km_pomiaru = parsuj_date(p["data"]), _na_liczbe(p["przebieg"])
            if liczone:
                km = _km_na_komplecie(liczone, licznik, dzien, km_pomiaru)[0]
            elif k["zamontowany"]:
                km = km_pomiaru or licznik.w_dniu(dzien)
            else:
                km = None
            if km is not None:
                punkty.append((km, p["min"]))
        km_teraz = k["km"] if liczone else (licznik.teraz if k["zamontowany"] else None)
        sezonowy = sezon in SEZONY_PRZELACZALNE and para
        koniec_montazu = None
        if sezonowy and k["zamontowany"]:
            koniec_montazu = termin if termin and termin > dzis else _koniec_sezonu(sezon, dzis)
        k["prognoza"] = _prognoza(k, punkty, km_teraz, sredni_dzienny, sezonowy, koniec_montazu, dzis)
        komplety.append(k)

    kolejnosc = {s: i for i, s in enumerate(SEZONY_OPON)}
    komplety.sort(key=lambda k: (not k["zamontowany"], k["os"] != "Wszystkie", kolejnosc.get(k["sezon"], 9), k["id"]))
    zamontowane = [k for k in komplety if k["zamontowany"]]
    brak_poczatku = [k["id"] for k in zamontowane if not k["otwarty"]]
    do_odtworzenia = len(wpisy_zmian_opon(auto_id)) if not montaze else 0
    return {"komplety": komplety, "zamontowane": zamontowane, "termin_zmiany": termin,
            "brak_poczatku": brak_poczatku, "do_odtworzenia": do_odtworzenia,
            "sredni_dzienny": sredni_dzienny, "jest_dziennik": bool(montaze)}


def dane_opon(auto_id, dzis=None) -> dict[str, Any]:
    """Wszystko o oponach pojazdu jednym przejściem — zakładka, ekran kompletu, kafelek, dzwonek,
    kondycja i oś: komplety (zamontowane najpierw) z pomiarami, okresami, km, wiekiem i prognozą;
    zamontowane, termin_zmiany, brak_poczatku (zamontowane bez okresu), do_odtworzenia (zmiany
    w Serwisie, gdy dziennika brak), sredni_dzienny, jest_dziennik."""
    if not auto_id:
        return _puste_dane_opon()
    if dzis is not None:
        return _policz_dane_opon(auto_id, dzis)
    return z_pamieci("opony", auto_id, lambda: _policz_dane_opon(auto_id, datetime.now().date()))


def komplet_opon(auto_id, zestaw_id, dzis=None) -> dict[str, Any] | None:
    return next((k for k in dane_opon(auto_id, dzis)["komplety"] if k["id"] == zestaw_id), None)


# ============================================================================
#  SYGNAŁY: DZWONEK, KONDYCJA, OŚ PRZYSZŁOŚCI
# ============================================================================

def _nazwa_kompletu(k):
    return f"Opony {k['sezon'].lower()}" if k["sezon"] else "Opony"


def sygnaly_opon(auto_id, dzis=None, dane=None) -> list[dict[str, Any]]:
    """Powiadomienia o zamontowanych kompletach: bieżnik poniżej zalecanego dla sezonu (pilne) albo
    minimum prawnego (po terminie) i opony po 10 latach od produkcji."""
    dane = dane or dane_opon(auto_id, dzis)
    wynik = []
    for k in dane["zamontowane"]:
        trasa = f"/magazyn/opony/{k['id']}"
        if k["status_bieznika"] in (STATUS_BIEZNIKA_UWAGA, STATUS_BIEZNIKA_KRYTYCZNY):
            krytyczny = k["status_bieznika"] == STATUS_BIEZNIKA_KRYTYCZNY
            opis = (f"Poniżej minimum prawnego ({tekst_bieznika(BIEZNIK_MINIMUM_PRAWNE)}) — do wymiany"
                    if krytyczny else f"Poniżej zalecanych {tekst_bieznika(k['prog_wymiany'])} — zaplanuj wymianę")
            wynik.append({"typ": "opony", "tytul": f"{_nazwa_kompletu(k)}: bieżnik {tekst_bieznika(k['bieznik'])}",
                          "opis": opis, "status": "przeterminowane" if krytyczny else "pilne", "trasa": trasa,
                          "klucz": f"opony:bieznik:{k['id']}"})
        if k["wiek"] and k["wiek"]["status"] == STATUS_WIEKU_WYMIANA:
            wynik.append({"typ": "opony", "tytul": f"{_nazwa_kompletu(k)}: {tekst_wieku(k['wiek'])} od produkcji",
                          "opis": f"Producenci zalecają wymianę najpóźniej po {WIEK_WYMIANY_OPON} latach",
                          "status": "przeterminowane", "trasa": trasa, "klucz": f"opony:wiek:{k['id']}"})
    return wynik


def powody_kondycji_opon(auto_id, dane=None) -> list[dict[str, Any]]:
    """Kary kondycji za zamontowane opony: klucz (KARY_KONDYCJI), opis, szczegol, waga, trasa."""
    dane = dane or dane_opon(auto_id)
    wynik = []
    for k in dane["zamontowane"]:
        trasa = f"/magazyn/opony/{k['id']}"
        szczegol = " • ".join(x for x in (tekst_bieznika(k["bieznik"]), k["rozmiar"]) if x)
        if k["status_bieznika"] == STATUS_BIEZNIKA_KRYTYCZNY:
            wynik.append({"klucz": "bieznik_krytyczny", "waga": "krytyczna", "trasa": trasa, "szczegol": szczegol,
                          "opis": f"{_nazwa_kompletu(k)} — bieżnik poniżej minimum prawnego "
                                  f"({tekst_bieznika(BIEZNIK_MINIMUM_PRAWNE)})"})
        elif k["status_bieznika"] == STATUS_BIEZNIKA_UWAGA:
            wynik.append({"klucz": "bieznik_niski", "waga": "ostrzezenie", "trasa": trasa, "szczegol": szczegol,
                          "opis": f"{_nazwa_kompletu(k)} — bieżnik poniżej {tekst_bieznika(k['prog_wymiany'])}, "
                                  "zalecana wymiana"})
        wiek = k["wiek"]
        if wiek and wiek["status"] != STATUS_WIEKU_OK:
            wymiana = wiek["status"] == STATUS_WIEKU_WYMIANA
            wynik.append({"klucz": "opony_wiek_wymiana" if wymiana else "opony_wiek_kontrola",
                          "waga": "krytyczna" if wymiana else "ostrzezenie", "trasa": trasa,
                          "szczegol": f"Produkcja {wiek['data']:%m.%Y} (kod DOT)",
                          "opis": f"{_nazwa_kompletu(k)} — {tekst_wieku(wiek)} od produkcji, "
                                  + ("do wymiany" if wymiana else "sprawdzaj co roku")})
    return wynik


def terminy_opon(auto_id, dzis, koniec, dane=None) -> list[dict[str, Any]]:
    """Terminy osi przyszłości: koniec bieżnika z prognozy (szacunek) i granica wieku (10 lat od
    produkcji) — pola jak pozycja osi (rodzaj, klucz, tytul, data, prognoza, sezon, trasa)."""
    dane = dane or dane_opon(auto_id, None if dzis == datetime.now().date() else dzis)
    wynik = []
    for k in dane["komplety"]:
        trasa = f"/magazyn/opony/{k['id']}"
        prognoza = k["prognoza"]
        if prognoza and prognoza["zostalo_km"] > 0 and prognoza["data"] and dzis <= prognoza["data"] <= koniec:
            wynik.append({"rodzaj": "opony_bieznik", "klucz": f"opony:bieznik:{k['id']}", "data": prognoza["data"],
                          "tytul": f"{_nazwa_kompletu(k)}: bieżnik {tekst_bieznika(prognoza['cel_mm'])}",
                          "prognoza": True, "sezon": k["sezon"], "trasa": trasa, "zestaw_id": k["id"],
                          "zostalo_km": zaokraglij_km_prognozy(prognoza["zostalo_km"])})
        wiek = k["wiek"]
        if wiek and dzis <= wiek["data_wymiany"] <= koniec:
            wynik.append({"rodzaj": "opony_wiek", "klucz": f"opony:wiek:{k['id']}", "data": wiek["data_wymiany"],
                          "tytul": f"{_nazwa_kompletu(k)}: {WIEK_WYMIANY_OPON} lat od produkcji",
                          "prognoza": False, "sezon": k["sezon"], "trasa": trasa, "zestaw_id": k["id"],
                          "zostalo_km": None})
    return wynik


def opis_prognozy(prognoza, jednostka=None) -> str | None:
    """„do 4 mm ok. 7 000 km (ok. 2 sezony)” albo „poniżej 4 mm — do 1,6 mm ok. 900 km”."""
    if not prognoza:
        return None
    cel = tekst_bieznika(prognoza["cel_mm"])
    if prognoza["zostalo_km"] <= 0:
        return f"bieżnik szacunkowo już {cel}"
    tekst = f"do {cel} ok. {tekst_dystansu(zaokraglij_km_prognozy(prognoza['zostalo_km']), 0, jednostka)}"
    sezony = tekst_sezonow(prognoza["sezonow"])
    if sezony:
        tekst += f" ({sezony})"
    return tekst


def zaokraglij_km_prognozy(km):
    """Prognoza to szacunek — do setek poniżej 10 000 km, wyżej do tysięcy."""
    return int(round(km, -2 if km < 10000 else -3))


__all__ = [
    "BIEZNIK_MINIMUM_PRAWNE",
    "BIEZNIK_NOWEJ_OPONY",
    "KOLA_OSI",
    "MAKS_BIEZNIK",
    "MIN_KM_TEMPA",
    "MIN_SPADEK_BIEZNIKA",
    "POZYCJE_KOL",
    "PROGI_WYMIANY_BIEZNIKA",
    "ROZNICA_OSI_ZAMIANY",
    "SKROTY_KOL",
    "STATUS_BIEZNIKA_KRYTYCZNY",
    "STATUS_BIEZNIKA_OK",
    "STATUS_BIEZNIKA_UWAGA",
    "STATUS_WIEKU_KONTROLA",
    "STATUS_WIEKU_OK",
    "STATUS_WIEKU_WYMIANA",
    "WIEK_KONTROLI_OPON",
    "WIEK_WYMIANY_OPON",
    "blad_okresu",
    "blad_pomiaru",
    "dane_opon",
    "daty_produkcji",
    "flagi_montazu",
    "komplet_opon",
    "najplytszy_bieznik",
    "odtworz_sezony_z_serwisu",
    "opis_prognozy",
    "pobierz_montaze",
    "pobierz_pomiar",
    "pobierz_pomiary",
    "powody_kondycji_opon",
    "prog_wymiany",
    "propozycja_poczatku_montazu",
    "przelacz_komplet_sezonowy",
    "roznica_osi",
    "status_bieznika",
    "sygnaly_opon",
    "tekst_bieznika",
    "tekst_sezonow",
    "tekst_wieku",
    "tempo_zuzycia",
    "terminy_opon",
    "udzial_bieznika",
    "ustaw_poczatek_montazu",
    "usun_okres_z_cofnieciem",
    "usun_pomiar_z_cofnieciem",
    "wartosci_kol",
    "wiek_opon",
    "wpisy_zmian_opon",
    "zaokraglij_km_prognozy",
    "zapisz_okres_montazu",
    "zapisz_okresy_montazu",
    "zapisz_pomiar",
]
