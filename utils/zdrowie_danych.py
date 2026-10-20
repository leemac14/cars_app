"""Zdrowie danych (N-08): zdania i klocki ekranu `/zdrowie-danych` (views/zdrowie_danych_view.py),
kafelka kokpitu, karty w Ustawieniach i odnośnika z kondycji. Liczy db/zdrowie_danych.py."""

from datetime import date

import flet as ft

import db

from .stale import FS, KOLOR_STATUS, RADIUS, SPACING, formatuj_liczba
from .format import formatuj_dni, formatuj_dystans, symbol_waluty
from .typografia import podpis, wartosc
from .wyglad import pasek_zawijany, powierzchnia, tlo_karty
from .dialogi import pokaz_komunikat, potwierdz

IKONY_ZDROWIA = {
    "licznik": ft.Icons.SPEED,
    "przyszlosc": ft.Icons.EVENT_BUSY,
    "cena": ft.Icons.PRICE_CHANGE,
    "do_pelna": ft.Icons.LOCAL_GAS_STATION,
    "bez_licznika": ft.Icons.TIMER_OFF,
    "pliki": ft.Icons.BROKEN_IMAGE,
    "nazwy": ft.Icons.MERGE_TYPE,
    "rodzaj": ft.Icons.PLAYLIST_ADD_CHECK,
    "terminy": ft.Icons.EDIT_CALENDAR,
    "pojazd": ft.Icons.DIRECTIONS_CAR,
}

KOLORY_WAGI_ZDROWIA = {
    "krytyczna": KOLOR_STATUS["critical"],
    "ostrzezenie": KOLOR_STATUS["warning"],
    "info": KOLOR_STATUS["info"],
}

POZYCJI_W_SEKCJI_ZDROWIA = 5  # dłuższa sekcja rozwija się „Pokaż wszystkie”
WPISOW_CIAGU_NA_KARCIE = 6    # daty tankowań ciągu „do pełna” jako przyciski


def dzien_zdrowia(iso, data=None):
    """DD.MM.RRRR z `data_iso` (wpisy z importu bywają zapisane inaczej); bez niej — `data`."""
    try:
        return date.fromisoformat(iso).strftime("%d.%m.%Y")
    except (TypeError, ValueError):
        return str(data or "")


def kolor_zdrowia(stan):
    """Kolor kafelka i nagłówka z wyniku db.zdrowie_danych / db.podsumowanie_zdrowia_danych."""
    if stan.get("krytyczne"):
        return KOLOR_STATUS["critical"]
    return KOLOR_STATUS["warning"] if stan.get("razem") else KOLOR_STATUS["ok"]


def sklad_zdrowia_danych(liczby, ile=2):
    """„cofki i skoki licznika: 2 · martwe załączniki: 4” — największe sekcje, przy remisie w kolejności ekranu."""
    kolejnosc = list(db.SPRAWDZENIA_ZDROWIA)
    najwieksze = sorted(liczby.items(), key=lambda kv: (-kv[1], kolejnosc.index(kv[0])))[:ile]
    return " · ".join(f"{db.SPRAWDZENIA_ZDROWIA[r].lower()}: {n}" for r, n in najwieksze)


def liczba_do_sprawdzenia(razem):
    return f"{formatuj_liczba(razem, 0)} do sprawdzenia"


def opis_sekcji_zdrowia(rodzaj, j=None):
    """Po co ta sekcja — jedno zdanie pod nagłówkiem."""
    opisy = {
        "licznik": "Licznik, który się cofa albo skacze, psuje spalanie, interwały i koszt przejazdu — "
                   "popraw wpis, który się nie zgadza.",
        "przyszlosc": "Data po dzisiejszej to zwykle literówka w roku — taki wpis wypada z bieżących "
                      "zestawień i miesza w historii.",
        "cena": f"Cena co najmniej {formatuj_liczba(db.PROG_NIETYPOWEJ_CENY, 0)} razy inna niż we wpisach "
                "obok — zwykle przecinek w litrach albo w kwocie.",
        "do_pelna": "Spalanie liczy się od pełnego baku do pełnego baku — te wpisy jeszcze się do niego "
                    "nie wliczyły.",
        "bez_licznika": "Wpis bez stanu licznika wypada z historii przebiegu, interwałów i spalania.",
        "pliki": "Wpis pamięta plik, którego nie ma na tym telefonie — zwykle po wczytaniu kopii albo "
                 "przeniesieniu danych.",
        "nazwy": "Ta sama nazwa zapisana na kilka sposobów rozbija historię na osobne pozycje.",
        "rodzaj": "Bez rodzaju Analiza nie odróżni awarii od planowej eksploatacji.",
        "terminy": "Bez daty nie ma przypomnienia ani oceny terminu w kondycji.",
        "pojazd": "Z tych pól korzystają zasięg na baku, sprawdzenie w CEPiK i plik pojazdu.",
    }
    return opisy.get(rodzaj, "")


def _za_jednostke(energia):
    return f"{symbol_waluty()}/{db.etykiety_energii(energia)['jednostka']}"


def _cena(wartosc_ceny):
    # Groszowa cena z literówki („0,004 zł/L”) nie może udawać zera.
    return formatuj_liczba(wartosc_ceny, 2 if wartosc_ceny >= 0.1 else 3)


def _wpisy_energii(energia, formy_paliwa, formy_pradu):
    return formy_pradu if energia == db.ENERGIA_PRAD else formy_paliwa


def tytul_pozycji_zdrowia(p):
    """Pierwsza linia karty: czego dotyczy pozycja."""
    rodzaj = p["rodzaj"]
    if rodzaj in ("licznik", "przyszlosc", "bez_licznika"):
        return " · ".join(x for x in (p["etykieta"], p.get("opis")) if x)
    if rodzaj == "cena":
        nazwa = _wpisy_energii(p["energia"], "Tankowanie", "Ładowanie")
        return " · ".join(x for x in (nazwa, p.get("stacja")) if x)
    if rodzaj == "do_pelna":
        formy = _wpisy_energii(p["energia"], ("tankowanie", "tankowania", "tankowań"),
                               ("ładowanie", "ładowania", "ładowań"))
        return f"{db.liczba_z_odmiana(p['liczba'], *formy)} z rzędu bez „do pełna”"
    if rodzaj == "pliki":
        typ = db.RODZAJE_ZALACZNIKOW.get(p.get("typ")) if p["zrodlo"] == "zalaczniki" else None
        return " · ".join(x for x in (typ, p["etykieta"], p.get("opis")) if x)
    if rodzaj == "nazwy":
        return f"{p['grupa']['etykieta']}: „{p['grupa']['kanoniczna'][1]}”"
    if rodzaj == "rodzaj":
        return f"{db.liczba_z_odmiana(p['liczba'], 'naprawa', 'naprawy', 'napraw')} bez rodzaju"
    if rodzaj == "terminy":
        return f"{p['etykieta']} — {'nieczytelna data' if p.get('nieczytelna') else 'brak daty'}"
    if rodzaj == "pojazd":
        return "Brak: " + ", ".join(p["pola"])
    return db.SPRAWDZENIA_ZDROWIA.get(rodzaj, "")


def _opis_licznika(p, j):
    poprzedni = p.get("poprzedni")
    skad = (f"{formatuj_dystans(poprzedni['przebieg'], 0, j)} ({poprzedni['etykieta']}, "
            f"{dzien_zdrowia(poprzedni['data_iso'])})") if poprzedni else ""
    teraz = formatuj_dystans(p["przebieg"], 0, j)
    if p["anomalia"] == "cofka":
        return f"{teraz} — o {formatuj_dystans(-(p['dystans'] or 0), 0, j)} mniej niż wpis wcześniej: {skad}."
    dni = max(1, p.get("dni") or 0)
    return (f"{teraz} — {formatuj_dystans(p['dystans'] or 0, 0, j)} w {formatuj_dni(dni)}, czyli "
            f"{formatuj_dystans(p.get('srednia_dzienna') or 0, 0, j)} dziennie; wcześniej {skad}.")


def _opis_ciagu(p, j):
    prad = p["energia"] == db.ENERGIA_PRAD
    if p["polozenie"] == "przed_pierwszym":
        tekst = (f"Przed pierwszym {'ładowaniem' if prad else 'tankowaniem'} do pełna ze stanem licznika — "
                 "ich ilość nie wejdzie do zużycia. Jeśli któreś było do pełna, zaznacz to w nim.")
    else:
        odcinek = ""
        if p.get("km"):
            odcinek += f" za {formatuj_dystans(p['km'], 0, j)}"
        if p.get("pelny_data_iso"):
            odcinek += f" od {dzien_zdrowia(p['pelny_data_iso'])}"
        tekst = (f"Zużycie{odcinek} policzy się dopiero po {'ładowaniu' if prad else 'tankowaniu'} do pełna — "
                 "jeśli któreś z nich było do pełna, zaznacz to w nim.")
    if p.get("bez_licznika"):
        tekst += " Pełny bak bez stanu licznika nie zamyka odcinka."
    return tekst


def opis_pozycji_zdrowia(p, j=None):
    """Druga linia karty: co jest nie tak i co z tym zrobić."""
    rodzaj = p["rodzaj"]
    if rodzaj == "licznik":
        return _opis_licznika(p, j)
    if rodzaj == "przyszlosc":
        return "Data późniejsza niż dzisiejsza — sprawdź rok i dzień."
    if rodzaj == "cena":
        za = _za_jednostke(p["energia"])
        obok = _wpisy_energii(p["energia"], "tankowaniach", "ładowaniach")
        return (f"{_cena(p['cena'])} {za} — ok. {formatuj_liczba(p['krotnosc'], 0)} razy "
                f"{'więcej' if p['wyzsza'] else 'mniej'} niż w {obok} obok (najbliżej {_cena(p['odniesienie'])} {za}). "
                "Sprawdź ilość i kwotę.")
    if rodzaj == "do_pelna":
        return _opis_ciagu(p, j)
    if rodzaj == "bez_licznika":
        skutek = {
            "tankowania": "nie wchodzi do spalania ani historii licznika",
            "dolewki": "nie wchodzi do zużycia płynu",
        }.get(p["tabela"], "nie przesuwa interwałów podzespołów")
        return f"Bez stanu licznika — {skutek}."
    if rodzaj == "pliki":
        if p["stan"] == "przeniesiony":
            return f"Plik „{p['nazwa_pliku']}” leży w innym folderze — „Odszukaj pliki” poprawi ścieżkę."
        return f"Na tym telefonie nie ma pliku „{p['nazwa_pliku']}”."
    if rodzaj == "nazwy":
        warianty = ", ".join(
            f"„{nazwa}” ({f'{uzycia} uż.' if uzycia else 'nieużywany'})" for _id, nazwa, uzycia in p["grupa"]["warianty"])
        return f"Warianty: {warianty}. Zostanie najczęściej użyty."
    if rodzaj == "rodzaj":
        tekst = f"Razem {formatuj_liczba(p['kwota'])} {symbol_waluty()}"
        if p.get("z_podpowiedzia"):
            tekst += f", {formatuj_liczba(p['z_podpowiedzia'], 0)} z podpowiedzią „planowe”"
        return tekst + " — oznaczysz je w jednym arkuszu."
    if rodzaj == "terminy":
        return "Wpisz datę w danych pojazdu."
    if rodzaj == "pojazd":
        return "Uzupełnij w danych pojazdu."
    return ""


def karta_podsumowania_zdrowia(page, stan):
    """Ile rzeczy czeka i z których sprawdzeń; czysto — zielony znak i liczba sprawdzeń."""
    kolor = kolor_zdrowia(stan)
    if stan["razem"]:
        wiersze = [
            ft.Row([ft.Icon(ft.Icons.HEALTH_AND_SAFETY, size=16, color=kolor),
                    podpis("Do sprawdzenia w tym pojeździe", expand=True)], spacing=6),
            ft.Text(liczba_do_sprawdzenia(stan["razem"]), size=FS["display"], weight="bold", color=kolor),
            podpis(sklad_zdrowia_danych(stan["liczby"], ile=3)),
        ]
    else:
        wiersze = [
            ft.Row([ft.Icon(ft.Icons.TASK_ALT, size=16, color=kolor),
                    podpis("Wszystko się zgadza", expand=True)], spacing=6),
            ft.Text("Dane bez zastrzeżeń", size=FS["display"], weight="bold"),
            podpis(f"Sprawdzono {db.liczba_z_odmiana(len(stan['sprawdzone']), 'obszar', 'obszary', 'obszarów')} "
                   "— nic do poprawy."),
        ]
    if stan["pominiete"]:
        wiersze.append(podpis(f"Oznaczone jako „To nie błąd”: {formatuj_liczba(len(stan['pominiete']), 0)} "
                              "— na dole ekranu."))
    return ft.Container(padding=SPACING["md"], **powierzchnia(page, "karta", stan=None),
                        content=ft.Column(wiersze, spacing=SPACING["xs"]))


def naglowek_sekcji_zdrowia(page, rodzaj, liczba, j=None, akcje=None):
    """Nagłówek sekcji: ikona, nazwa sprawdzenia, liczba pozycji, po co to sprawdzać i przyciski sekcji."""
    elementy = [
        ft.Row([
            ft.Icon(IKONY_ZDROWIA.get(rodzaj, ft.Icons.HELP_OUTLINE), size=18, color=ft.Colors.PRIMARY),
            ft.Text(db.SPRAWDZENIA_ZDROWIA[rodzaj], size=FS["label"], weight="bold", color=ft.Colors.PRIMARY,
                    expand=True, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
            wartosc(formatuj_liczba(liczba, 0)),
        ], spacing=SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ft.Text(opis_sekcji_zdrowia(rodzaj, j), size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT),
    ]
    if akcje:
        elementy.append(ft.Row(akcje, wrap=True, spacing=SPACING["xs"], run_spacing=0,
                               alignment=ft.MainAxisAlignment.END))
    return ft.Container(
        padding=ft.Padding(SPACING["md"], SPACING["sm"], SPACING["md"], SPACING["sm"]),
        border_radius=RADIUS["sm"], bgcolor=tlo_karty(page, poziom=2),
        content=ft.Column(elementy, spacing=SPACING["xs"]),
    )


def chip_wpisu_zdrowia(tekst, on_click=None):
    """Data wpisu ciągu jako mały przycisk — dotknięcie otwiera wpis."""
    return ft.Container(
        padding=ft.Padding(10, 4, 10, 4), border_radius=RADIUS["pill"],
        bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.PRIMARY), ink=bool(on_click), on_click=on_click,
        content=ft.Row([ft.Text(tekst, size=FS["caption"], color=ft.Colors.PRIMARY)], tight=True, spacing=4),
    )


def karta_czystych_sprawdzen(page, rodzaje):
    """Sprawdzenia bez zastrzeżeń — żeby było widać, co jeszcze przejrzano."""
    chipy = [ft.Container(
        padding=ft.Padding(0, 2, 10, 2),
        content=ft.Row([ft.Icon(ft.Icons.CHECK, size=14, color=KOLOR_STATUS["ok"]),
                        ft.Text(db.SPRAWDZENIA_ZDROWIA[r], size=FS["caption"])], tight=True, spacing=4),
    ) for r in rodzaje]
    return ft.Container(
        padding=SPACING["md"], **powierzchnia(page, "blok"),
        content=ft.Column([podpis("Bez zastrzeżeń"), pasek_zawijany(chipy)], spacing=SPACING["sm"]),
    )


def potwierdz_scalenie_duplikatow(page, auto_id, grupa, po_scaleniu=None):
    """Scalenie jednej grupy wariantów nazwy (dawniej okno w Ustawieniach). Nic nie dzieje się samo —
    zwycięzca (najczęściej użyty) stoi w pytaniu, zanim cokolwiek zniknie."""
    docelowy_id, docelowa_nazwa, _ = grupa["kanoniczna"]
    zrodla = [w[0] for w in grupa["warianty"] if w[0] != docelowy_id]
    znikajace = ", ".join(f"„{w[1]}”" for w in grupa["warianty"] if w[0] != docelowy_id)
    dopisek = (" Sztuki z duplikatów zostaną doliczone do stanu pozycji docelowej."
               if grupa["tabela"] == "magazyn_czesci" else "")

    def wykonaj():
        ile = db.scal_duplikaty_nazw(auto_id, grupa["tabela"], docelowy_id, zrodla)
        pokaz_komunikat(page, f"Scalono {db.liczba_z_odmiana(ile, 'wariant', 'warianty', 'wariantów')} "
                              f"w „{docelowa_nazwa}”.", KOLOR_STATUS["ok"])
        if po_scaleniu:
            po_scaleniu()

    potwierdz(
        page, "Scalić warianty?",
        f"{znikajace} zniknie, a wszystkie powiązania przejdą na „{docelowa_nazwa}”.{dopisek} "
        "Tej operacji nie da się cofnąć.",
        wykonaj, tekst_potwierdzenia="Scal",
    )


def nota_zdrowia_danych(j=None):
    """Treść karty „Jak sprawdzamy” pod listą."""
    return (
        f"Licznik: cofka to stan niższy niż we wpisie wcześniej, skok — średnio ponad "
        f"{formatuj_dystans(db.MIN_SKOK_PRZEBIEGU_NA_DZIEN, 0, j)} dziennie i ponad "
        f"{formatuj_liczba(db.KROTNOSC_SKOKU_PRZEBIEGU, 0)} razy więcej niż zwykle. Cena: co najmniej "
        f"{formatuj_liczba(db.PROG_NIETYPOWEJ_CENY, 0)} razy inna niż każda z "
        f"{formatuj_liczba(db.CENY_ODNIESIENIA, 0)} najbliższych w czasie cen tego samego paliwa albo prądu — "
        "jak ostrzeżenie w formularzu. „Do pełna”: co najmniej dwa wpisy z rzędu bez pełnego baku ze stanem "
        "licznika, przed pierwszym takim bakiem albo po ostatnim; w środku historii zużycie liczy się "
        "dłuższym odcinkiem. Pliki: ścieżka zapisana we wpisie, a pliku nie ma na tym telefonie. Terminy: "
        "polisa OC i przegląd. „To nie błąd” działa na tym telefonie, a poprawiony wpis wraca do sprawdzenia, "
        "jeśli nadal się nie zgadza; kondycja i Historia przebiegu liczą nieścisłości licznika bez tych "
        f"oznaczeń. Dzwonek przypomina o przeglądzie po {formatuj_dni(db.DNI_PRZEGLADU_DANYCH)} od ostatniego "
        "otwarcia tego ekranu."
    )


__all__ = [
    "IKONY_ZDROWIA",
    "KOLORY_WAGI_ZDROWIA",
    "POZYCJI_W_SEKCJI_ZDROWIA",
    "WPISOW_CIAGU_NA_KARCIE",
    "chip_wpisu_zdrowia",
    "dzien_zdrowia",
    "karta_czystych_sprawdzen",
    "karta_podsumowania_zdrowia",
    "kolor_zdrowia",
    "liczba_do_sprawdzenia",
    "naglowek_sekcji_zdrowia",
    "nota_zdrowia_danych",
    "opis_pozycji_zdrowia",
    "opis_sekcji_zdrowia",
    "potwierdz_scalenie_duplikatow",
    "sklad_zdrowia_danych",
    "tytul_pozycji_zdrowia",
]
