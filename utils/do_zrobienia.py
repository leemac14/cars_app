"""Do zrobienia na ekranie: okno „Wykonano”, przesuwanie terminu, termin przebiegowy na
karcie, szczegóły pozycji i opis wpisów jej dziennika."""

from datetime import datetime

import flet as ft

import db

from .stale import FS, KOLOR_STATUS, SPACING, formatuj_liczba
from .format import formatuj_dystans, jednostka_dystansu, kolor_i_tekst_terminu, parsuj_float, symbol_waluty
from .typografia import etykieta, podpis, pole
from .dialogi import otworz_dialog, pokaz_komunikat, pokaz_menu_kontekstowe, zamknij_dialog
from .zgodnosc import ustaw_blad
from .sync_ui import zablokowane
from .formularze import na_cala_szerokosc, pole_daty, pole_wyboru, sprawdz_podejrzany_przebieg, styl_pola
from .magazyn import liczba_do_pola
from .wykresy import ROLA_STATUSU_INTERWALU, pasek_postepu


# Wpis dziennika: rodzaj -> (ikona, rola w KOLOR_STATUS).
IKONY_ZDARZEN_DO_ZROBIENIA = {
    db.ZDARZENIE_DODANO: (ft.Icons.ADD_CIRCLE_OUTLINE, "neutral"),
    db.ZDARZENIE_ZMIANA: (ft.Icons.EDIT_NOTE, "neutral"),
    db.ZDARZENIE_TERMIN: (ft.Icons.EVENT_REPEAT, "info"),
    db.ZDARZENIE_WYKONANO: (ft.Icons.CHECK_CIRCLE, "ok"),
    db.ZDARZENIE_POPRAWKA: (ft.Icons.EDIT_CALENDAR, "ok"),
    db.ZDARZENIE_COFNIETO: (ft.Icons.UNDO, "warning"),
    db.ZDARZENIE_WIZYTA: (ft.Icons.HOME_REPAIR_SERVICE, "info"),
    db.ZDARZENIE_ZWROT: (ft.Icons.ASSIGNMENT_RETURN, "warning"),
}

KOLORY_PRIORYTETU = {"Wysoki": "critical", "Średni": "warning", "Niski": "info"}

_NAZWY_POL = {"tytul": "nazwa", "opis": "szczegóły", "priorytet": "priorytet", "szacowany_koszt": "szacunek",
              "zadanie_id": "podzespół"}


def _kwota(kwota):
    return f"{formatuj_liczba(float(kwota))} {symbol_waluty()}" if kwota else "—"


def kolor_priorytetu(priorytet):
    return KOLOR_STATUS[KOLORY_PRIORYTETU.get(priorytet, "neutral")]


def chip_priorytetu(priorytet):
    kolor = kolor_priorytetu(priorytet)
    return ft.Container(
        padding=ft.Padding(8, 4, 8, 4), border_radius=20, bgcolor=ft.Colors.with_opacity(0.15, kolor),
        content=ft.Text(str(priorytet), size=FS["caption"], weight="bold", color=kolor),
    )


def tekst_wykonania(pozycja, j=None):
    """„12.10.2026 · 123 456 km · 280,00 zł” — dzień, licznik i koszt wykonania."""
    czesci = [pozycja.get("data_wykonania") or "data nieznana"]
    if pozycja.get("przebieg_wykonania"):
        czesci.append(formatuj_dystans(pozycja["przebieg_wykonania"], 0, j))
    if pozycja.get("koszt_wykonania"):
        czesci.append(_kwota(pozycja["koszt_wykonania"]))
    return " · ".join(czesci)


def opis_terminu_przebiegowego(pozycja, j=None):
    """(lewa, prawa, kolor) terminu przebiegowego: „Przy 150 000 km”, „zostało 2 300 km” albo
    „po terminie o 300 km”; None bez terminu."""
    cel = pozycja.get("termin_przebieg")
    if not cel:
        return None
    stan = pozycja.get("stan_przebiegu")
    lewa = f"Przy {formatuj_dystans(cel, 0, j)}"
    if not stan:
        return lewa, "", KOLOR_STATUS["neutral"]
    kolor = KOLOR_STATUS[ROLA_STATUSU_INTERWALU.get(stan["status"], "ok")]
    if stan["zostalo"] > 0:
        return lewa, f"zostało {formatuj_dystans(stan['zostalo'], 0, j)}", kolor
    return lewa, f"po terminie o {formatuj_dystans(-stan['zostalo'], 0, j)}", kolor


def termin_przebiegowy_karty(pozycja, j=None):
    """Pasek do terminu przebiegowego (od licznika przy planowaniu); bez licznika startowego
    sam napis. None bez terminu."""
    opis = opis_terminu_przebiegowego(pozycja, j)
    if not opis:
        return None
    lewa, prawa, kolor = opis
    stan = pozycja.get("stan_przebiegu") or {}
    if stan.get("procent") is None:
        return ft.Row([ft.Icon(ft.Icons.SPEED, size=14, color=kolor),
                       ft.Text(" · ".join(x for x in (lewa, prawa) if x), size=FS["label"], color=kolor,
                               expand=True, max_lines=2)], spacing=SPACING["xs"])
    return pasek_postepu(lewa, prawa, stan["procent"], kolor, wysokosc=6)


# ---------------------------------------------------------------- dziennik pozycji


def _przy(km, j=None):
    return f"przy {formatuj_dystans(km, 0, j)}" if km else "bez przebiegu"


def opis_zdarzenia_do_zrobienia(zdarzenie, j=None):
    """Treść wpisu dziennika z jego `dane` — w walucie i jednostce dystansu czytającego."""
    rodzaj, d = zdarzenie.get("rodzaj"), zdarzenie.get("dane") or {}
    if rodzaj in (db.ZDARZENIE_WYKONANO, db.ZDARZENIE_POPRAWKA):
        czesci = [d.get("data"), formatuj_dystans(d["przebieg"], 0, j) if d.get("przebieg") else None,
                  _kwota(d["koszt"]) if d.get("koszt") else None,
                  "wpis w serwisie" if d.get("serwis") else None, "w Innych kosztach" if d.get("inny_koszt") else None]
        tekst = " · ".join(c for c in czesci if c)
        return f"{tekst} — „{d['notatka']}”" if d.get("notatka") else tekst
    if rodzaj == db.ZDARZENIE_TERMIN:
        czesci = []
        if isinstance(d.get("termin"), list) and len(d["termin"]) == 2:
            czesci.append(f"{d['termin'][0] or 'bez terminu'} → {d['termin'][1] or 'bez terminu'}")
        if isinstance(d.get("termin_przebieg"), list) and len(d["termin_przebieg"]) == 2:
            czesci.append(f"{_przy(d['termin_przebieg'][0], j)} → {_przy(d['termin_przebieg'][1], j)}")
        return " · ".join(czesci)
    if rodzaj == db.ZDARZENIE_ZMIANA:
        czesci = []
        for nazwa in d.get("pola") or []:
            stara_nowa = d.get("zadanie" if nazwa == "zadanie_id" else nazwa)
            if nazwa == "priorytet" and isinstance(stara_nowa, list):
                czesci.append(f"priorytet {stara_nowa[0] or '—'} → {stara_nowa[1] or '—'}")
            elif nazwa == "szacowany_koszt" and isinstance(stara_nowa, list):
                czesci.append(f"szacunek {_kwota(stara_nowa[0])} → {_kwota(stara_nowa[1])}")
            elif nazwa == "zadanie_id" and isinstance(stara_nowa, list):
                czesci.append(f"podzespół {stara_nowa[0] or '—'} → {stara_nowa[1] or '—'}")
            else:
                czesci.append(_NAZWY_POL.get(nazwa, str(nazwa)))
        return " · ".join(czesci)
    if rodzaj == db.ZDARZENIE_COFNIETO:
        return f"było wykonane {d['data']}" if d.get("data") else ""
    if rodzaj == db.ZDARZENIE_WIZYTA:
        return f"wizyta z {d['data']}" if d.get("data") else ""
    if rodzaj == db.ZDARZENIE_ZWROT:
        return " · ".join(x for x in (f"z wizyty z {d['data']}" if d.get("data") else None, d.get("wykonawca")) if x)
    return ""


def kiedy_zdarzenie(zdarzenie):
    """„25.10.2026, 21:30 · Kamil” — moment zapisu i kto."""
    try:
        moment = datetime.strptime(str(zdarzenie.get("moment")), "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y, %H:%M")
    except (TypeError, ValueError):
        moment = str(zdarzenie.get("moment") or "")
    return " · ".join(x for x in (moment, zdarzenie.get("dodane_przez")) if x)


def wiersz_zdarzenia_do_zrobienia(zdarzenie, j=None):
    rodzaj = zdarzenie.get("rodzaj")
    ikona, rola = IKONY_ZDARZEN_DO_ZROBIENIA.get(rodzaj, (ft.Icons.CIRCLE_OUTLINED, "neutral"))
    tresc = [ft.Text(db.ETYKIETY_ZDARZEN_DO_ZROBIENIA.get(rodzaj, str(rodzaj)), size=FS["body"],
                     weight=ft.FontWeight.W_500)]
    opis = opis_zdarzenia_do_zrobienia(zdarzenie, j)
    if opis:
        tresc.append(podpis(opis, max_lines=3))
    tresc.append(etykieta(kiedy_zdarzenie(zdarzenie)))
    return ft.Row([ft.Icon(ikona, size=18, color=KOLOR_STATUS[rola]), ft.Column(tresc, spacing=1, expand=True)],
                  spacing=SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.START)


def szczegoly_pozycji_do_zrobienia(pozycja, wspolny=False, j=None):
    """Kontrolki arkusza pozycji nad akcjami: priorytet i stan, opis, terminy, szacunek,
    podzespół, wykonanie."""
    zrobione = pozycja["wykonane"]
    stan = (ft.Icons.TASK_ALT, "Wykonane", KOLOR_STATUS["ok"]) if zrobione else \
        (ft.Icons.RADIO_BUTTON_UNCHECKED, "Do zrobienia", KOLOR_STATUS["neutral"])
    elementy = [ft.Row([chip_priorytetu(pozycja["priorytet"]), ft.Icon(stan[0], size=16, color=stan[2]),
                        ft.Text(stan[1], size=FS["label"], color=stan[2])], spacing=SPACING["sm"],
                       vertical_alignment=ft.CrossAxisAlignment.CENTER)]
    if pozycja["opis"]:
        elementy.append(ft.Text(pozycja["opis"], size=FS["body"]))

    kolor_term, tekst_term = kolor_i_tekst_terminu(pozycja["termin"]) if pozycja["termin"] else (None, None)
    pary = []
    if not zrobione:
        pary.append(("Termin", tekst_term or "bez terminu", kolor_term if tekst_term else None))
    if pozycja["szacowany_koszt"]:
        pary.append(("Szacunek", f"~{_kwota(pozycja['szacowany_koszt'])}", None))
    if pozycja["zadanie_nazwa"]:
        pary.append(("Podzespół", pozycja["zadanie_nazwa"], None))
    if pozycja["data_utworzenia"]:
        pary.append(("Dodano", pozycja["data_utworzenia"], None))
    for i in range(0, len(pary), 2):
        elementy.append(ft.Row([ft.Container(pole(n, t, color=k), expand=True) for n, t, k in pary[i:i + 2]],
                               spacing=SPACING["md"], vertical_alignment=ft.CrossAxisAlignment.START))
    przebieg = None if zrobione else termin_przebiegowy_karty(pozycja, j)
    if przebieg:
        elementy.append(przebieg)

    if zrobione:
        elementy.append(pole("Wykonano", tekst_wykonania(pozycja, j)))
        if pozycja["notatka_wykonania"]:
            elementy.append(ft.Text(f"„{pozycja['notatka_wykonania']}”", size=FS["body"], italic=True))
        powiazania = []
        if pozycja["wizyta_id"]:
            powiazania.append((ft.Icons.HOME_REPAIR_SERVICE, f"W wizycie z {pozycja['wizyta_data']}"))
        elif pozycja["historia_id"]:
            powiazania.append((ft.Icons.BUILD, "Dopisane do serwisu"))
        if pozycja["koszt_id"]:
            powiazania.append((ft.Icons.RECEIPT_LONG, "W Innych kosztach"))
        if wspolny and pozycja["wykonane_przez"]:
            powiazania.append((ft.Icons.PERSON, f"Odhaczył(a): {pozycja['wykonane_przez']}"))
        for ikona, tekst in powiazania:
            elementy.append(ft.Row([ft.Icon(ikona, size=16, color=ft.Colors.ON_SURFACE_VARIANT),
                                    podpis(tekst, expand=True, max_lines=2)], spacing=SPACING["sm"]))
    return elementy


def historia_pozycji_do_zrobienia(pozycja, zdarzenia, j=None):
    """Kontrolki pod akcjami arkusza: nagłówek i wpisy dziennika od najstarszego. Pozycja sprzed
    dziennika dostaje sam wpis o dodaniu z datą."""
    if not zdarzenia and pozycja.get("data_utworzenia"):
        zdarzenia = [{"rodzaj": db.ZDARZENIE_DODANO, "dane": {}, "moment": pozycja["data_utworzenia"]}]
    if not zdarzenia:
        return []
    return [ft.Text("Historia pozycji", size=FS["body_strong"], weight="bold")] + \
        [wiersz_zdarzenia_do_zrobienia(z, j) for z in zdarzenia]


# ---------------------------------------------------------------- okna


def komunikat_wykonania(wynik, poprawka=False):
    if poprawka:
        tekst = "Zapisano poprawione wykonanie."
    elif (wynik or {}).get("liczba", 0) > 1:
        tekst = f"Oznaczono jako wykonane: {wynik['liczba']}."
    else:
        tekst = "Oznaczono jako wykonane."
    if (wynik or {}).get("serwis"):
        tekst += " Wpis jest w historii serwisowej."
    if (wynik or {}).get("koszty"):
        tekst += " Koszt dopisano do Innych kosztów."
    if (wynik or {}).get("do_kosza"):
        tekst += " Poprzedni wpis trafił do kosza."
    return tekst


def okno_wykonania(page: ft.Page, auto_id, pozycje, po_zapisie=None):
    """Okno „Wykonano” dla jednej albo kilku pozycji (słowniki z db.pobierz_pozycje_do_zrobienia):
    data (dziś), licznik z historii licznika na ten dzień, faktyczny koszt (jedna pozycja),
    notatka, dopisanie do serwisu albo Innych kosztów. Wykonana pozycja — poprawka.
    `po_zapisie(wynik, poprawka)` po udanym zapisie."""
    pozycje = [p for p in pozycje or [] if p]
    if not pozycje or zablokowane(page, auto_id):
        return None
    jedna = pozycje[0] if len(pozycje) == 1 else None
    poprawka = bool(jedna and jedna["wykonane"])
    j = jednostka_dystansu()
    data_pocz = (jedna["data_wykonania"] if poprawka else None) or datetime.now().strftime("%d.%m.%Y")
    km_pocz = (jedna["przebieg_wykonania"] if poprawka else None) or \
        db.szacuj_przebieg_w_dniu(auto_id, data_pocz) or db.pobierz_aktualny_przebieg(auto_id) or None
    stan = {"licznik_recznie": poprawka and bool(km_pocz)}

    e_przebieg = ft.TextField(label=f"Stan licznika ({j})", value=db.wartosc_pola_dystansu(km_pocz) if km_pocz else "",
                              keyboard_type=ft.KeyboardType.NUMBER, **styl_pola())
    e_przebieg.on_change = lambda e: stan.update(licznik_recznie=True)

    def po_zmianie_daty():
        # Licznik podpowiada się na wybrany dzień — dopóki nikt go nie wpisał sam.
        km = None if stan["licznik_recznie"] else db.szacuj_przebieg_w_dniu(auto_id, e_data.value)
        if km:
            e_przebieg.value = db.wartosc_pola_dystansu(km)

    e_data = pole_daty(page, "Data wykonania", data_pocz, po_zmianie=po_zmianie_daty, podpowiedz="Wybierz")
    pola = [na_cala_szerokosc(e_data), na_cala_szerokosc(e_przebieg)]
    e_koszt = None
    if jedna:
        koszt_pocz = jedna["koszt_wykonania"] if poprawka else jedna["szacowany_koszt"]
        e_koszt = ft.TextField(label=f"Faktyczny koszt ({symbol_waluty()})",
                               value=liczba_do_pola(koszt_pocz) if koszt_pocz else "",
                               keyboard_type=ft.KeyboardType.NUMBER, **styl_pola())
        pola.append(na_cala_szerokosc(e_koszt))
    e_notatka = ft.TextField(label="Notatka (opcjonalnie)", value=(jedna["notatka_wykonania"] if poprawka else "") or "",
                             multiline=True, min_lines=1, max_lines=3, max_length=db.MAKS_DLUGOSC_NOTATKI,
                             **styl_pola())
    pola.append(na_cala_szerokosc(e_notatka))

    z_podzespolem = any(p["zadanie_id"] for p in pozycje)
    if jedna and jedna["zadanie_id"]:
        tekst_chk = f"Dopisz do serwisu: {jedna['zadanie_nazwa'] or 'podzespół'}"
        wartosc_chk = bool(jedna["historia_id"]) if poprawka else True
    elif jedna:
        tekst_chk = "Dopisz koszt do Innych kosztów"
        wartosc_chk = bool(jedna["koszt_id"]) if poprawka else True
    else:
        tekst_chk = "Dopisz do serwisu i Innych kosztów (koszt to szacunek)"
        wartosc_chk = True
    chk = ft.Checkbox(label=tekst_chk, value=wartosc_chk)
    pola.append(pole_wyboru(chk))
    if z_podzespolem:
        pola.append(podpis("Wpis serwisowy liczy interwał podzespołu od tego dnia i licznika.", max_lines=3))

    def zapisz(e):
        for kontrolka in (e_data, e_przebieg, e_koszt):
            if kontrolka:
                ustaw_blad(kontrolka)
        data = (e_data.value or "").strip()
        bledy = [] if data else [(e_data, "Wybierz dzień wykonania")]
        km = None
        if (e_przebieg.value or "").strip():
            km = db.dystans_na_km(e_przebieg.value, calkowity=True, km_przy_otwarciu=km_pocz)
            if not km or km <= 0:
                bledy.append((e_przebieg, "Podaj poprawny stan licznika"))
        serwis = bool(chk.value) and z_podzespolem
        if serwis and not km and not bledy:
            bledy.append((e_przebieg, "Wpis serwisowy potrzebuje stanu licznika"))
        koszt = None
        if e_koszt and (e_koszt.value or "").strip():
            koszt = parsuj_float(e_koszt.value, None)
            if koszt is None or koszt < 0:
                bledy.append((e_koszt, "Podaj poprawny koszt"))
        if bledy:
            for kontrolka, komunikat in bledy:
                ustaw_blad(kontrolka, komunikat)
            page.update()
            return
        if serwis and sprawdz_podejrzany_przebieg(page, e_przebieg, auto_id, km,
                                                  wyklucz_id=jedna["historia_id"] if poprawka else None,
                                                  tabela="historia", nowa_data_str=data):
            return
        wynik = db.oznacz_wykonane_do_zrobienia([p["id"] for p in pozycje], {
            "data": data, "przebieg": km, "koszt": koszt, "notatka": e_notatka.value, "powiazany": bool(chk.value)})
        zamknij_dialog(page, dlg)
        if not wynik:
            pokaz_komunikat(page, "Nie zapisano wykonania: pozycji już nie ma albo nie masz do niej uprawnień.",
                            KOLOR_STATUS["error"])
            return
        if po_zapisie:
            po_zapisie(wynik, poprawka)

    tytul = "Popraw wykonanie" if poprawka else (
        "Wykonano" if jedna else f"Wykonano: {db.liczba_z_odmiana(len(pozycje), 'pozycja', 'pozycje', 'pozycji')}")
    dlg = ft.AlertDialog(
        modal=True, scrollable=True,
        title=ft.Text(tytul, weight="bold"),
        content=ft.Column([podpis(jedna["tytul"], max_lines=2)] + pola if jedna else pola,
                          tight=True, spacing=SPACING["sm"]),
        actions=[
            ft.TextButton("Anuluj", on_click=lambda e: zamknij_dialog(page, dlg)),
            ft.Button("Zapisz", on_click=zapisz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    otworz_dialog(page, dlg)
    return dlg


def okno_przesuniecia_terminu(page: ft.Page, pozycja, po_zmianie=None):
    """Menu „Przesuń termin”: o tydzień, dwa, miesiąc albo trzy (od dawnego terminu, a gdy
    minął — od dziś), wybrany dzień; przy terminie przebiegowym także o 1 000 i 5 000 w jednostce
    dystansu. `po_zmianie()` po zapisie."""
    if not pozycja or zablokowane(page, pozycja["auto_id"]):
        return

    def ustaw(**zmiana):
        if db.przesun_termin_do_zrobienia(pozycja["id"], **zmiana) and po_zmianie:
            po_zmianie()

    def wybierz_dzien():
        e_termin = pole_daty(page, "Nowy termin", pozycja["termin"] or None, podpowiedz="Wybierz")

        def zapisz(e):
            zamknij_dialog(page, dlg)
            ustaw(termin=e_termin.value)

        dlg = ft.AlertDialog(
            modal=True, title=ft.Text("Nowy termin", weight="bold"),
            content=ft.Column([na_cala_szerokosc(e_termin)], tight=True),
            actions=[ft.TextButton("Anuluj", on_click=lambda e: zamknij_dialog(page, dlg)),
                     ft.Button("Zapisz", on_click=zapisz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY)],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        otworz_dialog(page, dlg)

    pozycje = []
    for nazwa, dni, miesiace in db.PRZESUNIECIA_TERMINU:
        nowy = db.termin_po_przesunieciu(pozycja["termin"], dni, miesiace)
        pozycje.append({"ikona": ft.Icons.EVENT_REPEAT, "tekst": f"{nazwa} — {nowy}",
                        "akcja": lambda n=nowy: ustaw(termin=n)})
    pozycje.append({"ikona": ft.Icons.CALENDAR_MONTH, "tekst": "Wybierz dzień…", "akcja": wybierz_dzien})
    if pozycja["termin_przebieg"]:
        for krok in db.PRZESUNIECIA_PRZEBIEGU:
            km = int(pozycja["termin_przebieg"] + db.dystans_na_km(krok))
            pozycje.append({"ikona": ft.Icons.SPEED,
                            "tekst": f"+{formatuj_dystans(db.dystans_na_km(krok))} — {_przy(km)}",
                            "akcja": lambda k=km: ustaw(termin_przebieg=k)})
    pokaz_menu_kontekstowe(page, "Przesuń termin", pozycje)


__all__ = [
    "IKONY_ZDARZEN_DO_ZROBIENIA",
    "KOLORY_PRIORYTETU",
    "chip_priorytetu",
    "historia_pozycji_do_zrobienia",
    "kiedy_zdarzenie",
    "kolor_priorytetu",
    "komunikat_wykonania",
    "okno_przesuniecia_terminu",
    "okno_wykonania",
    "opis_terminu_przebiegowego",
    "opis_zdarzenia_do_zrobienia",
    "szczegoly_pozycji_do_zrobienia",
    "tekst_wykonania",
    "termin_przebiegowy_karty",
    "wiersz_zdarzenia_do_zrobienia",
]
