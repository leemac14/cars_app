"""Terminy w kalendarzu telefonu (N-03): słowa wpisów pliku .ics, wysyłka systemowym
„Udostępnij” (page.zapisz_bajty_pliku — jak grafika „Rok w pigułce”), wybór aut przy kilku
aktywnych i podpowiedź po zmianie terminów. Plik, alarmy i porównanie liczy db/kalendarz.py."""

import asyncio
from datetime import datetime

import flet as ft

import db

from .stale import FS, KOLOR_STATUS, RADIUS, bezpieczna_nazwa_pliku, formatuj_liczba
from .format import formatuj_dni, symbol_waluty
from .typografia import podpis
from .wyglad import tlo_stanu
from .dialogi import pokaz_komunikat, pokaz_menu_kontekstowe
from .przyszlosc import co_ile_osi, kwota_osi, tytul_pozycji_osi


NAZWA_APLIKACJI = "Flota Mobile"

OPIS_KALENDARZA = ("Polisy, przegląd i inne dokumenty, wymiany z datą, a do tego raty i wydatki cykliczne "
                   "na rok do przodu — każdy termin z przypomnieniem w progu z Ustawień i dzień wcześniej. "
                   "Kalendarz telefonu przypomni też wtedy, gdy aplikacja jest zamknięta.")


# ============================================================================
#  SŁOWA WPISU
# ============================================================================

def tytul_wpisu_kalendarza(termin):
    """Nazwa wpisu bez pojazdu: „Polisa OC — koniec ważności”, „Wymiana: Olej silnikowy”,
    „Leasing: rata 13 z 48”, „Abonament GPS”, „Zmiana opon” (seria na przemian)."""
    p = termin["pozycja"]
    rodzaj, tytul = p["rodzaj"], tytul_pozycji_osi(p)
    if rodzaj == "opony":
        return "Zmiana opon"
    if rodzaj in ("dokument", "skarbiec"):
        return f"{tytul} — koniec ważności"
    if rodzaj == "podzespol":
        return f"Wymiana: {tytul}"
    if rodzaj == "gwarancja_naprawy":
        gwarancja = (p["zrodlo"] or {}).get("gwarancja") or {}
        return f"Koniec gwarancji: {gwarancja.get('nazwa') or tytul}"
    if rodzaj == "rata" and p["platnosc"]:
        return f"{tytul}: {p['platnosc']}"
    return tytul


def _zdanie(czesci):
    tekst = ", ".join(c for c in czesci if c)
    return f"{tekst[:1].upper()}{tekst[1:]}." if tekst else ""


def opis_wpisu_kalendarza(termin, pojazd, dzis):
    """Treść wpisu: co to za termin, pojazd i skąd plik (stan na dzień wysyłki)."""
    p, najpozniej = termin["pozycja"], termin["najpozniej"]
    rodzaj = p["rodzaj"]
    linie = []
    if rodzaj in ("dokument", "skarbiec"):
        linie.append("Ostatni dzień ważności.")
        oferta = (p["zrodlo"] or {}).get("opis_oferty")
        if oferta:
            linie.append(oferta)
    elif rodzaj == "podzespol":
        linie.append("Najpóźniej według czasu — kilometry mogą skończyć się wcześniej." if najpozniej
                     else "Termin wymiany według interwału czasu.")
        if p["kwota"]:
            linie.append(f"Ostatnia wymiana: {formatuj_liczba(p['kwota'])} {symbol_waluty()}.")
    elif rodzaj == "gwarancja_naprawy":
        linie.append("Ostatni dzień gwarancji naprawy — limit kilometrów może skończyć się wcześniej."
                     if najpozniej else "Ostatni dzień gwarancji naprawy.")
    elif rodzaj == "opony":
        zmiany = ", ".join(f"na {str(w['sezon'] or '').lower()} {w['data']:%d.%m.%Y}"
                           for w in termin["wystapienia"][:4])
        linie.append(f"Kolejne zmiany: {zmiany}.")
    else:
        powtarza = None
        if termin["okres_dni"] and not p["platnosc"]:
            powtarza = f"powtarza się {co_ile_osi(termin['okres_dni'])}"
        zdanie = _zdanie([f"kwota {kwota_osi(p)}" if p["kwota"] else None, powtarza])
        if zdanie:
            linie.append(zdanie)
    nazwa, numer = str(pojazd.get("nazwa") or "").strip(), str(pojazd.get("nr_rej") or "").strip()
    linie.append(f"Pojazd: {nazwa} ({numer})." if numer else f"Pojazd: {nazwa}.")
    linie.append(f"Z aplikacji {NAZWA_APLIKACJI}, stan na {dzis:%d.%m.%Y}. Po zmianie terminu "
                 "w aplikacji wyślij plik do kalendarza jeszcze raz.")
    return "\n".join(linie)


def _kiedy_alarmu(dni):
    return "jutro" if dni == 1 else f"za {formatuj_dni(dni)}"


def wpisy_kalendarza(auto_ids, teraz=None):
    """Wpisy dla db.generuj_ics i to, co trzeba zapamiętać po wysyłce:
    {"wpisy", "terminy": {auto_id: terminy}, "nazwy": {auto_id: nazwa}}."""
    teraz = teraz or datetime.now()
    dzis = teraz.date()
    znacznik = db.znacznik_kalendarza()
    wynik = {"wpisy": [], "terminy": {}, "nazwy": {}}
    for auto_id in auto_ids:
        pojazd = db.pobierz_dane_pojazdu(auto_id) or {}
        nazwa = str(pojazd.get("nazwa") or "Pojazd").strip()
        terminy = db.terminy_kalendarza(auto_id, dzis=dzis)
        wynik["terminy"][auto_id], wynik["nazwy"][auto_id] = terminy, nazwa
        for t in terminy:
            tytul = f"{tytul_wpisu_kalendarza(t)} · {nazwa}"
            wynik["wpisy"].append({
                "uid": db.uid_terminu(znacznik, auto_id, t["grupa"]),
                "data": t["data"], "tytul": tytul, "opis": opis_wpisu_kalendarza(t, pojazd, dzis),
                "powtorz": (t["okres_dni"], len(t["wystapienia"])) if t["okres_dni"] else None,
                "alarmy": [(dni, f"{tytul}: {_kiedy_alarmu(dni)}")
                           for dni in db.alarmy_terminu(t["data"], t["prog_dni"], teraz)],
            })
    wynik["wpisy"].sort(key=lambda w: (w["data"], w["tytul"]))
    return wynik


# ============================================================================
#  WYSYŁKA
# ============================================================================

async def wyslij_do_kalendarza(page: ft.Page, auto_ids, po_wyslaniu=None):
    """Plik .ics z terminami `auto_ids` przez page.zapisz_bajty_pliku. Po udanym
    „Udostępnij” (albo zapisie na komputerze) zapamiętuje wysyłkę i woła `po_wyslaniu`."""
    zapisywacz = getattr(page, "zapisz_bajty_pliku", None)
    if zapisywacz is None:
        pokaz_komunikat(page, "Zapis pliku jest niedostępny w tej wersji aplikacji.", KOLOR_STATUS["error"])
        return False
    teraz = datetime.now()
    paczka = await asyncio.to_thread(wpisy_kalendarza, list(auto_ids), teraz)
    wpisy = paczka["wpisy"]
    if not wpisy:
        pokaz_komunikat(page, "Na najbliższy rok nie ma terminów z datą — uzupełnij daty polis i przeglądu "
                        "albo dodaj wydatki cykliczne.", KOLOR_STATUS["warning"])
        return False
    if len(paczka["nazwy"]) == 1:
        (nazwa,) = paczka["nazwy"].values()
        nazwa_kalendarza, nazwa_pliku = f"Terminy — {nazwa}", f"terminy_{bezpieczna_nazwa_pliku(nazwa)}.ics"
    else:
        nazwa_kalendarza, nazwa_pliku = "Terminy pojazdów", "terminy_pojazdow.ics"
    numer = db.numer_wysylki_kalendarza()
    dane = db.generuj_ics(wpisy, nazwa_kalendarza, teraz=teraz, numer=numer)
    if not await zapisywacz(nazwa_pliku, dane):
        return False
    db.zapamietaj_wysylke_kalendarza(paczka["terminy"], numer, dzis=teraz.date())
    pokaz_komunikat(page, f"W pliku {db.liczba_z_odmiana(len(wpisy), 'termin', 'terminy', 'terminów')} "
                          "— otwórz go w kalendarzu telefonu.")
    if po_wyslaniu:
        po_wyslaniu()
    return True


def wyslij_terminy_do_kalendarza(page: ft.Page, state, po_wyslaniu=None):
    """„Dodaj terminy do kalendarza”: przy jednym aktywnym aucie od razu, przy kilku —
    arkusz „tylko to” albo „wszystkie aktywne”."""
    aktywne = db.pobierz_pojazdy(tylko_aktywne=True)
    if not aktywne:
        pokaz_komunikat(page, "Nie ma aktywnego pojazdu, którego terminy można wysłać.", KOLOR_STATUS["warning"])
        return
    wszystkie = [auto_id for auto_id, _ in aktywne]
    biezacy = next((nazwa for auto_id, nazwa in aktywne if auto_id == state.auto_id), None)
    if len(aktywne) == 1 or biezacy is None:
        async def _wyslij():
            await wyslij_do_kalendarza(page, wszystkie if biezacy is None else [state.auto_id], po_wyslaniu)
        page.run_task(_wyslij)
        return
    pokaz_menu_kontekstowe(page, "Do kalendarza telefonu", [
        {"ikona": ft.Icons.DIRECTIONS_CAR, "tekst": f"Tylko {biezacy}",
         "akcja": lambda: wyslij_do_kalendarza(page, [state.auto_id], po_wyslaniu)},
        {"ikona": ft.Icons.GARAGE, "tekst": f"Wszystkie aktywne ({len(aktywne)})",
         "akcja": lambda: wyslij_do_kalendarza(page, wszystkie, po_wyslaniu)},
    ])


# ============================================================================
#  KONTROLKI
# ============================================================================

def karta_kalendarza(on_click):
    """Wejście na dole „Co przede mną”: przycisk i zdanie o tym, co pójdzie do kalendarza."""
    return ft.Column([
        ft.FilledTonalButton("Dodaj terminy do kalendarza", icon=ft.Icons.EVENT_AVAILABLE,
                             on_click=on_click, width=10000, height=48),
        podpis(OPIS_KALENDARZA),
    ], spacing=6)


def baner_kalendarza(page: ft.Page, stan, on_click):
    """Pasek nad osią po wysyłce: terminy rozjechały się z kalendarzem albo plik dobiega
    końca okna. None, gdy db.stan_kalendarza nie ma nic do powiedzenia."""
    if not stan:
        return None
    if stan["zmienione"]:
        zmiany = db.liczba_z_odmiana(stan["zmienione"], "zmiana", "zmiany", "zmian")
        tresc = (f"Od wysłania do kalendarza ({stan['wyslano']:%d.%m.%Y}) terminy się zmieniły — {zmiany}. "
                 "Wyślij plik jeszcze raz.")
    else:
        tresc = f"Kalendarz ma terminy tylko do {stan['do']:%d.%m.%Y} — wyślij plik na kolejny rok."
    kolor = KOLOR_STATUS["info"]
    return ft.Container(
        padding=ft.Padding(12, 4, 4, 4), border_radius=RADIUS["sm"], bgcolor=tlo_stanu(page, "info"),
        content=ft.Row([
            ft.Icon(ft.Icons.EVENT_REPEAT, size=18, color=kolor),
            ft.Text(tresc, size=FS["caption"], color=kolor, expand=True),
            ft.TextButton("Wyślij", icon=ft.Icons.IOS_SHARE, on_click=on_click),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
    )


__all__ = [
    "NAZWA_APLIKACJI",
    "OPIS_KALENDARZA",
    "baner_kalendarza",
    "karta_kalendarza",
    "opis_wpisu_kalendarza",
    "tytul_wpisu_kalendarza",
    "wpisy_kalendarza",
    "wyslij_do_kalendarza",
    "wyslij_terminy_do_kalendarza",
]
