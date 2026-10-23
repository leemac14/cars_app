"""Terminy do kalendarza telefonu (N-03): plik iCalendar (RFC 5545) z osi przyszłości. Idą
terminy i płatności: dokumenty i skarbiec, wymiany i gwarancje napraw z datą w kalendarzu (przy
kilometrach „najpóźniej” z licznika czasu) na OKNO_TERMINOW_KALENDARZA — odnowiona polisa ma datę
za ponad rok — oraz raty, wydatki cykliczne i zmiana opon z przypomnienia na OKNO_KALENDARZA.
Prognozy kilometrów, zakładane wymiany, podpowiedzi i budżety zostają w aplikacji. Wpis
całodniowy, alarmy o GODZINA_ALARMU: w progu terminu (tym, który barwi go na osi) i dzień
wcześniej. Wpis cykliczny to JEDNO wydarzenie z RRULE (co okres_dni, tyle razy, ile wypada
w oknie); UID bez daty — kalendarz, który zna UID, przy ponownym imporcie podmienia wpis albo
całą serię zamiast dublować. Słowa: utils/kalendarz.py.

Podpowiedź „terminy zmieniły się” porównuje GRUPY (termin albo cały wpis cykliczny) z tym, co ten
telefon wysłał: inna data (seria — przesunięta o więcej niż TOLERANCJA_SERII_DNI) albo nowa grupa
przed końcem jej okna w wysłanym pliku. Zniknięcie (zapłacone, usunięte) podpowiedzi nie zapala."""

import secrets
from datetime import date as date_cls, datetime, time, timedelta, timezone
from typing import Any

from .stale import NAZWA_APLIKACJI
from .ustawienia import (
    KLUCZ_ZNACZNIKA_KALENDARZA, pobierz_eksport_kalendarza, pobierz_prog_dni, pobierz_ustawienie,
    zapisz_eksport_kalendarza, zapisz_ustawienie,
)
from .pojazd import pobierz_pojazdy
from .os_przyszlosci import KOLEJNOSC_RODZAJOW, _granica, os_przyszlosci


# Płatności i wpisy cykliczne — rok do przodu; terminy jednorazowe dalej, żeby polisa
# odnowiona przed końcem starej (nowa data za ponad rok) trafiła do pliku od razu.
OKNO_KALENDARZA = 365
OKNO_TERMINOW_KALENDARZA = 730

# Alarmy dzwonią o tej godzinie (wpis jest całodniowy).
GODZINA_ALARMU = 9

# Tyle dni przed końcem okna wysłanego pliku ekran podpowiada wysłanie nowego.
DNI_ZAPASU_KALENDARZA = 30

# Przesunięcie serii (zapłacone kilka dni wcześniej albo później), które jeszcze nie
# rozjeżdża kalendarza z aplikacją.
TOLERANCJA_SERII_DNI = 3

RODZAJE_KALENDARZA = ("dokument", "skarbiec", "rata", "cykliczny", "opony", "podzespol", "gwarancja_naprawy")

# Grupy liczone w krótszym oknie (płatności i serie) — po przedrostku klucza osi.
PRZEDROSTKI_PLATNOSCI = ("cykliczny:", "rata:")

PRODID_KALENDARZA = f"-//{NAZWA_APLIKACJI}//Terminy pojazdu//PL"
# Bez zmian przy zmianie nazwy: inna domena = inne UID, a kalendarz zdublowałby terminy.
DOMENA_UID = "cars-app"

_PRZEDROSTEK_SERII = "cykliczny:"
_MAKS_OKTETOW_LINII = 75


# ============================================================================
#  TERMINY
# ============================================================================

def _seria(klucz):
    """Grupa wpisu cyklicznego („cykliczny:<id>”) albo None dla terminu jednorazowego."""
    klucz = str(klucz or "")
    if klucz.startswith(_PRZEDROSTEK_SERII) and klucz.count(":") >= 2:
        return klucz.rsplit(":", 1)[0]
    return None


def okno_grupy(grupa) -> int:
    """Okno, w którym grupa trafia do pliku: płatności i serie krócej, terminy dalej."""
    return OKNO_KALENDARZA if str(grupa).startswith(PRZEDROSTKI_PLATNOSCI) else OKNO_TERMINOW_KALENDARZA


def terminy_kalendarza(auto_id, dzis=None) -> list[dict[str, Any]]:
    """Terminy pojazdu do kalendarza od najbliższego, jeden na grupę: grupa, data (pierwsze
    wystąpienie), najpozniej, prog_dni, okres_dni (seria, inaczej None), pozycja osi,
    wystapienia (pozycje serii w oknie; termin jednorazowy — on sam) i po_zaleglym (seria
    liczona od dziś za niezapłaconym wystąpieniem — jej daty płyną z dniem)."""
    dzis = dzis or datetime.now().date()
    os_dane = os_przyszlosci(auto_id, dni=OKNO_TERMINOW_KALENDARZA, dzis=dzis)
    prog_domyslny = pobierz_prog_dni()
    zalegle_serie = {_seria(p["klucz"]) for p in os_dane["pozycje"] if p["zalegla"]}
    wynik, serie = [], {}
    for p in os_dane["pozycje"]:
        if p["zalegla"] or p["zakladana"] or p["sugestia"] or p["rodzaj"] not in RODZAJE_KALENDARZA:
            continue
        data, najpozniej = p["data"], p["najpozniej"]
        if p["prognoza"] and not najpozniej:
            # Data z kilometrów jedzie z tempem jazdy, a wpis w kalendarzu stoi — zostaje
            # granica z licznika czasu (podzespół, gwarancja naprawy) albo nic.
            data = _granica(p["zrodlo"]) if p["zrodlo"] else None
            najpozniej = data is not None
        seria = _seria(p["klucz"])
        grupa = seria or p["klucz"]
        if data is None or data < dzis or (data - dzis).days > okno_grupy(grupa):
            continue
        if grupa in serie:
            serie[grupa]["wystapienia"].append(p)
            continue
        termin = {
            "grupa": grupa, "data": data, "najpozniej": najpozniej, "prog_dni": p["prog_dni"] or prog_domyslny,
            "okres_dni": (int(p["okres_dni"] or 0) or None) if seria else None, "pozycja": p, "wystapienia": [p],
            "po_zaleglym": bool(seria) and seria in zalegle_serie,
        }
        if seria:
            serie[grupa] = termin
        wynik.append(termin)
    wynik.sort(key=lambda t: (t["data"], KOLEJNOSC_RODZAJOW.get(t["pozycja"]["rodzaj"], 9),
                              str(t["pozycja"]["tytul"] or "")))
    return wynik


def znacznik_kalendarza() -> str:
    """Losowy znacznik TEJ bazy w UID — dwie osoby z osobnymi bazami w jednym kalendarzu
    nie nadpiszą sobie wpisów. Zakładany przy pierwszej wysyłce."""
    znacznik = str(pobierz_ustawienie(KLUCZ_ZNACZNIKA_KALENDARZA, "") or "").strip()
    if not znacznik:
        znacznik = secrets.token_hex(4)
        zapisz_ustawienie(KLUCZ_ZNACZNIKA_KALENDARZA, znacznik)
    return znacznik


def uid_terminu(znacznik, auto_id, grupa) -> str:
    """„<znacznik>-<auto>-dokument-oc@cars-app”, „…-cykliczny-5@cars-app”."""
    trzon = "-".join([str(znacznik), str(auto_id), str(grupa)])
    return "".join(z if z.isascii() and (z.isalnum() or z == "-") else "-" for z in trzon) + f"@{DOMENA_UID}"


def alarmy_terminu(data, prog_dni, teraz=None) -> list[int]:
    """Ile dni przed terminem dzwonią alarmy: próg i dzień wcześniej, od najdalszego. Alarm,
    którego chwila już minęła, wypada (kalendarz pokazałby go od razu jako przegapiony)."""
    teraz = teraz or datetime.now()
    try:
        prog = max(1, int(prog_dni or 1))
    except (TypeError, ValueError):
        prog = 1
    return [dni for dni in sorted({prog, 1}, reverse=True)
            if datetime.combine(data - timedelta(days=dni), time(GODZINA_ALARMU)) > teraz]


# ============================================================================
#  PLIK .ICS
# ============================================================================

def _tekst(wartosc):
    """Wartość TEXT (RFC 5545): ukośnik, średnik, przecinek i nowa linia ze znakiem ucieczki."""
    tekst = str(wartosc or "").replace("\r\n", "\n").replace("\r", "\n")
    return tekst.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _zawin(linia):
    """Linia złożona do 75 oktetów (kontynuacja od spacji), bez cięcia znaku UTF-8."""
    czesci, biezaca, dlugosc, limit = [], [], 0, _MAKS_OKTETOW_LINII
    for znak in linia:
        oktety = len(znak.encode("utf-8"))
        if dlugosc + oktety > limit:
            czesci.append("".join(biezaca))
            biezaca, dlugosc, limit = [], 0, _MAKS_OKTETOW_LINII - 1
        biezaca.append(znak)
        dlugosc += oktety
    czesci.append("".join(biezaca))
    return "\r\n ".join(czesci)


def _wyzwalacz(dni):
    """Alarm `dni` dni przed wpisem całodniowym o GODZINA_ALARMU: „-P29DT15H”, „-PT15H”."""
    godziny = 24 - GODZINA_ALARMU
    return f"-P{dni - 1}DT{godziny}H" if dni > 1 else f"-PT{godziny}H"


def generuj_ics(wpisy, nazwa_kalendarza, teraz=None, numer=1) -> bytes:
    """Plik .ics (UTF-8, CRLF). Wpis: uid, data, tytul, opis, alarmy [(dni przed, tekst)],
    opcjonalnie powtorz (co ile dni, ile razy). SEQUENCE = numer wysyłki — kalendarz, który
    porównuje wersje wpisu, weźmie nowszą."""
    teraz = teraz or datetime.now()
    znacznik_czasu = teraz.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    linie = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID_KALENDARZA}", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", f"X-WR-CALNAME:{_tekst(nazwa_kalendarza)}"]
    for wpis in wpisy:
        dzien = wpis["data"]
        linie += [
            "BEGIN:VEVENT", f"UID:{wpis['uid']}", f"DTSTAMP:{znacznik_czasu}", f"SEQUENCE:{int(numer)}",
            f"DTSTART;VALUE=DATE:{dzien:%Y%m%d}", f"DTEND;VALUE=DATE:{dzien + timedelta(days=1):%Y%m%d}",
        ]
        okres, razy = wpis.get("powtorz") or (0, 1)
        if okres and razy > 1:
            linie.append(f"RRULE:FREQ=DAILY;INTERVAL={int(okres)};COUNT={int(razy)}")
        linie.append(f"SUMMARY:{_tekst(wpis['tytul'])}")
        if wpis.get("opis"):
            linie.append(f"DESCRIPTION:{_tekst(wpis['opis'])}")
        linie.append("TRANSP:TRANSPARENT")
        for dni, tekst in wpis.get("alarmy") or ():
            linie += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_tekst(tekst)}",
                      f"TRIGGER:{_wyzwalacz(dni)}", "END:VALARM"]
        linie.append("END:VEVENT")
    linie.append("END:VCALENDAR")
    return "".join(_zawin(linia) + "\r\n" for linia in linie).encode("utf-8")


# ============================================================================
#  CO POSZŁO DO KALENDARZA I PODPOWIEDŹ
# ============================================================================

def _grupy(terminy):
    """{grupa: (data pierwszego wystąpienia, okres serii albo 0)}."""
    grupy = {}
    for t in terminy:
        grupy.setdefault(t["grupa"], (t["data"], int(t["okres_dni"] or 0)))
    return grupy


def numer_wysylki_kalendarza() -> int:
    """Numer następnej wysyłki (SEQUENCE wpisów)."""
    return pobierz_eksport_kalendarza()["numer"] + 1


def zapamietaj_wysylke_kalendarza(terminy_pojazdow, numer, dzis=None):
    """Po udanym „Udostępnij”: per pojazd dzień, koniec okna i grupy z pierwszą datą.
    Pojazdy, których już nie ma, wypadają z zapisu."""
    dzis = dzis or datetime.now().date()
    stan = pobierz_eksport_kalendarza()
    pojazdy = dict(stan["pojazdy"])
    for auto_id, terminy in terminy_pojazdow.items():
        pojazdy[str(auto_id)] = {
            "dzien": dzis.isoformat(), "do": (dzis + timedelta(days=OKNO_KALENDARZA)).isoformat(),
            "grupy": {g: [d.isoformat(), o] for g, (d, o) in _grupy(terminy).items()},
        }
    istniejace = {str(i) for i, _ in pobierz_pojazdy(tylko_aktywne=False)}
    zapisz_eksport_kalendarza({
        "numer": max(int(numer), stan["numer"]),
        "pojazdy": {k: v for k, v in pojazdy.items() if k in istniejace},
    })


def _data(tekst):
    try:
        return date_cls.fromisoformat(str(tekst))
    except (TypeError, ValueError):
        return None


def _wyslana(wartosc):
    """(data, okres) grupy z zapisu albo (None, 0), gdy zapis nieczytelny."""
    if not isinstance(wartosc, (list, tuple)) or not wartosc:
        return None, 0
    try:
        okres = int(wartosc[1]) if len(wartosc) > 1 else 0
    except (TypeError, ValueError):
        okres = 0
    return _data(wartosc[0]), okres


def _zmienione_grupy(wyslane, obecne, wyslano):
    """Ile grup rozjechało się z kalendarzem (patrz docstring modułu)."""
    zmienione = 0
    for grupa, (data, okres) in obecne.items():
        dawna, dawny_okres = _wyslana(wyslane.get(grupa))
        if dawna is None:
            zmienione += int((data - wyslano).days <= okno_grupy(grupa))
        elif okres != dawny_okres:
            zmienione += 1
        elif okres:
            przesuniecie = (data - dawna).days % okres
            zmienione += int(min(przesuniecie, okres - przesuniecie) > TOLERANCJA_SERII_DNI)
        else:
            zmienione += int(data != dawna)
    return zmienione


def stan_kalendarza(auto_id, dzis=None) -> dict[str, Any] | None:
    """Podpowiedź na „Co przede mną”: None, gdy pojazdu nie wysyłano albo nie ma czego mówić;
    inaczej wyslano, do (koniec okna płatności w pliku), zmienione (liczba grup) i konczy_sie
    (płatności i serie dobiegają końca okna)."""
    wyslane = pobierz_eksport_kalendarza()["pojazdy"].get(str(auto_id))
    if not isinstance(wyslane, dict) or not isinstance(wyslane.get("grupy"), dict):
        return None
    wyslano, do = _data(wyslane.get("dzien")), _data(wyslane.get("do"))
    if wyslano is None or do is None:
        return None
    dzis = dzis or datetime.now().date()
    obecne = _grupy(t for t in terminy_kalendarza(auto_id, dzis) if not t["po_zaleglym"])
    if not obecne:
        return None
    zmienione = _zmienione_grupy(wyslane["grupy"], obecne, wyslano)
    konczy_sie = ((do - dzis).days <= DNI_ZAPASU_KALENDARZA
                  and any(okno_grupy(g) == OKNO_KALENDARZA for g in obecne))
    if not zmienione and not konczy_sie:
        return None
    return {"wyslano": wyslano, "do": do, "zmienione": zmienione, "konczy_sie": konczy_sie}


__all__ = [
    "DNI_ZAPASU_KALENDARZA",
    "DOMENA_UID",
    "GODZINA_ALARMU",
    "OKNO_KALENDARZA",
    "OKNO_TERMINOW_KALENDARZA",
    "PRODID_KALENDARZA",
    "PRZEDROSTKI_PLATNOSCI",
    "RODZAJE_KALENDARZA",
    "TOLERANCJA_SERII_DNI",
    "alarmy_terminu",
    "generuj_ics",
    "numer_wysylki_kalendarza",
    "okno_grupy",
    "stan_kalendarza",
    "terminy_kalendarza",
    "uid_terminu",
    "zapamietaj_wysylke_kalendarza",
    "znacznik_kalendarza",
]
