"""Awarie kontra eksploatacja w interfejsie: pole rodzaju naprawy w formularzach, chip na
kartach, karta w Analizie (paski, odstępy, słupki w czasie) i arkusz oznaczania napraw bez
rodzaju. Dane liczy db.awarie_i_eksploatacja."""

import flet as ft

import db
import log

from .stale import FS, IKONY_RODZAJU_SERWISU, KOLORY_RODZAJU_SERWISU, RADIUS, SPACING, formatuj_liczba
from .format import formatuj_dni, formatuj_dystans, jednostka_dystansu, symbol_waluty
from .typografia import KOLOR_DRUGIEGO_PLANU, etykieta, podpis, wartosc
from .wyglad import dol_bezpieczny, pasek_zawijany, powierzchnia, tlo_toru
from .dialogi import otworz_dno, zamknij_dno
from .sync_ui import wypchnij_w_tle
from .wykresy import _kropka_legendy, okresy_slupkow, znacznik_trendu
from .komponenty import nota_o_liczeniu, segmented_control

# Podpisy pasków i legendy — w liczbie mnogiej, bo zbierają wiele napraw.
ETYKIETY_SERII = {
    db.SERWIS_PLANOWE: "Planowe",
    db.SERWIS_AWARIA: "Awarie",
    db.SERWIS_MODERNIZACJA: "Modernizacje",
    None: db.ETYKIETA_BEZ_RODZAJU,
}

# Kolejność segmentów słupka od dołu: awarie przy osi, żeby dało się je porównać między okresami.
KOLEJNOSC_SEGMENTOW = (db.SERWIS_AWARIA, db.SERWIS_PLANOWE, db.SERWIS_MODERNIZACJA, None)

OPISY_RODZAJU = {
    None: "Bez rodzaju naprawa nie trafi ani do awarii, ani do planowych.",
    db.SERWIS_PLANOWE: "Przegląd albo wymiana w terminie.",
    db.SERWIS_AWARIA: "Coś się zepsuło — liczy się do udziału awarii w koszcie serwisu.",
    db.SERWIS_MODERNIZACJA: "Ulepszenie, nie naprawa — hak, nagłośnienie, instalacja LPG.",
}

MAKS_W_ARKUSZU = 40
WYSOKOSC_SLUPKA = 110


class PoleRodzajuSerwisu:
    """Rodzaj naprawy w formularzu wpisu i wizyty; drugie dotknięcie zdejmuje wybór.
    `podpowiedz(rodzaj)` zmienia wartość tylko, dopóki użytkownik jej nie ruszył."""

    def __init__(self, page: ft.Page, rodzaj=None):
        self._page = page
        self.wartosc = db.rodzaj_serwisu(rodzaj)
        self.dotkniety = False
        self.przelacznik = ft.Container(content=self._zbuduj())
        self.opis = podpis(OPISY_RODZAJU[self.wartosc])
        self.kontrolka = ft.Column([etykieta("Rodzaj naprawy"), self.przelacznik, self.opis], spacing=6)

    def _zbuduj(self):
        opcje = [(db.ETYKIETY_RODZAJU_SERWISU[r], r) for r in db.RODZAJE_SERWISU]
        return segmented_control(self._page, opcje, self.wartosc, self._wybierz)

    def _wybierz(self, rodzaj):
        self.dotkniety = True
        self.wartosc = None if rodzaj == self.wartosc else rodzaj
        self._odswiez()

    def podpowiedz(self, rodzaj):
        rodzaj = db.rodzaj_serwisu(rodzaj)
        if not self.dotkniety and rodzaj != self.wartosc:
            self.wartosc = rodzaj
            self._odswiez()

    def _odswiez(self):
        self.przelacznik.content = self._zbuduj()
        self.opis.value = OPISY_RODZAJU[self.wartosc]
        try:
            self.kontrolka.update()
        except RuntimeError:
            log.polkniety("odświeżenie pola rodzaju naprawy")

    def migawka(self):
        return self.wartosc


def chip_rodzaju_serwisu(rodzaj, planowe=False):
    """Chip rodzaju na karcie wpisu albo wizyty. Planowa naprawa (zwykły przypadek) i brak
    rodzaju — None, chyba że `planowe`."""
    rodzaj = db.rodzaj_serwisu(rodzaj)
    if rodzaj is None or (rodzaj == db.SERWIS_PLANOWE and not planowe):
        return None
    kolor = KOLORY_RODZAJU_SERWISU[rodzaj]
    return ft.Container(
        padding=ft.Padding(8, 2, 10, 2), border_radius=RADIUS["pill"],
        bgcolor=ft.Colors.with_opacity(0.12, kolor),
        content=ft.Row([
            ft.Icon(IKONY_RODZAJU_SERWISU[rodzaj], size=13, color=kolor),
            ft.Text(db.ETYKIETY_RODZAJU_SERWISU[rodzaj], size=FS["caption"], weight="bold", color=kolor),
        ], spacing=4, tight=True),
    )


def paski_rodzajow(page: ft.Page, dane, scena=None):
    """Koszt serwisu wg rodzaju — trzy paski zawsze, „Bez rodzaju” tylko z kosztem albo
    naprawą. `dane` z db.awarie_i_eksploatacja."""
    w = symbol_waluty()
    wiersze = []
    for rodzaj in (*db.RODZAJE_SERWISU, None):
        grupa = dane["rodzaje"][rodzaj]
        if rodzaj is None and not grupa["liczba"]:
            continue
        kolor = KOLORY_RODZAJU_SERWISU[rodzaj]
        procent = grupa["udzial"] or 0.0
        tor = ft.ProgressBar(value=procent / 100 if procent > 0 else 0, color=kolor,
                             bgcolor=tlo_toru(page), height=6, border_radius=3)
        if scena is not None:
            scena.nastepny_wiersz()
            tor = scena.wskaznik(tor)
        wiersze.append(ft.Column([
            ft.Row([
                ft.Row([
                    ft.Icon(IKONY_RODZAJU_SERWISU[rodzaj], size=15, color=kolor),
                    ft.Text(ETYKIETY_SERII[rodzaj], weight="bold", size=13, color=ft.Colors.ON_SURFACE,
                            no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS, expand=True),
                ], spacing=6, expand=True),
                ft.Text(f"{formatuj_liczba(grupa['kwota'])} {w} ({formatuj_liczba(procent, 0)}%)",
                        weight="bold", size=13, color=kolor, no_wrap=True),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            tor,
        ], spacing=3))
    return wiersze


def _dni(n):
    return formatuj_dni(round(n))


def _blok_odstepow(dane):
    """Średni odstęp między awariami (dni i licznik), dwa ostatnie odstępy kontra wcześniejsze
    i ostatnia awaria."""
    if not dane["awarie"]:
        return [podpis("Żadnej awarii w tym okresie.")]
    ostatnia = dane["ostatnia_awaria"].strftime("%d.%m.%Y")
    temu = "dziś" if dane["dni_od_awarii"] == 0 else f"{_dni(dane['dni_od_awarii'])} temu"
    if dane["awarie"] == 1:
        return [podpis(f"Jedna awaria: {ostatnia} ({temu}). Odstęp policzy się od drugiej.")]

    tekst = f"co {_dni(dane['odstep_dni'])}"
    if dane["odstep_km"]:
        tekst += f" · {formatuj_dystans(dane['odstep_km'], 0, jednostka_dystansu())}"
    elementy = [ft.Row([
        ft.Icon(ft.Icons.TIMELAPSE, size=18, color=KOLORY_RODZAJU_SERWISU[db.SERWIS_AWARIA]),
        ft.Column([etykieta(f"Średni odstęp między awariami ({dane['awarie']})"), wartosc(tekst)],
                  spacing=1, tight=True, expand=True),
    ], spacing=10)]
    if dane["odstep_ostatnich_dni"] is not None and dane["odstep_wczesniej_dni"]:
        zmiana = (dane["odstep_ostatnich_dni"] - dane["odstep_wczesniej_dni"]) / dane["odstep_wczesniej_dni"] * 100
        elementy.append(ft.Row([
            podpis(f"Dwa ostatnie odstępy: co {_dni(dane['odstep_ostatnich_dni'])}, "
                   f"wcześniej co {_dni(dane['odstep_wczesniej_dni'])}", expand=True),
            znacznik_trendu(zmiana, prog=10, wzrost_zly=False),
        ], spacing=8))
    elementy.append(podpis(f"Ostatnia awaria: {ostatnia} ({temu})"))
    return elementy


def _segment(kolor, wysokosc, szerokosc):
    return ft.Container(width=szerokosc, height=wysokosc, bgcolor=kolor)


def wykres_awarii(page: ft.Page, dane, zakres, dzisiaj=None):
    """Słupki kosztu serwisu w czasie, każdy złożony z rodzajów (awarie przy osi), nad słupkiem
    liczba awarii. Siatka okresów jak w „Wydatkach w czasie” (utils.okresy_slupkow). None bez
    napraw z datą."""
    naprawy = dane["naprawy"]
    if not naprawy:
        return None
    w = symbol_waluty()
    okresy = okresy_slupkow(zakres, min(d[:7] for d, _k, _r in naprawy), dzisiaj)
    okres_miesiaca = {mk: i for i, (_e, klucze) in enumerate(okresy) for mk in klucze}
    sumy = [{r: 0.0 for r in KOLEJNOSC_SEGMENTOW} for _ in okresy]
    dni_awarii = [set() for _ in okresy]
    for data_iso, kwota, rodzaj in naprawy:
        i = okres_miesiaca.get(data_iso[:7])
        if i is None:
            continue
        sumy[i][rodzaj] += kwota
        if rodzaj == db.SERWIS_AWARIA:
            dni_awarii[i].add(data_iso)

    najwiecej = max((sum(s.values()) for s in sumy), default=0.0)
    ile = len(okresy)
    szerokosc = 32 if ile <= 6 else 26 if ile <= 9 else 18
    rozmiar_etykiety = 11 if ile <= 6 else 10 if ile <= 9 else 9
    kolumny = []
    for i, (etyk, _klucze) in enumerate(okresy):
        razem = sum(sumy[i].values())
        if razem > 0 and najwiecej > 0:
            segmenty = [
                _segment(KOLORY_RODZAJU_SERWISU[r], max(2, int(sumy[i][r] / najwiecej * WYSOKOSC_SLUPKA)), szerokosc)
                for r in reversed(KOLEJNOSC_SEGMENTOW) if sumy[i][r] > 0
            ]
            opis = "; ".join(f"{ETYKIETY_SERII[r].lower()} {formatuj_liczba(sumy[i][r])} {w}"
                             for r in KOLEJNOSC_SEGMENTOW if sumy[i][r] > 0)
        else:
            segmenty = [_segment(ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE), 4, szerokosc)]
            opis = "bez napraw"
        awarii = len(dni_awarii[i])
        kolumny.append(ft.Column([
            ft.Text(f"{awarii}×" if awarii else "", size=rozmiar_etykiety, weight="bold",
                    color=KOLORY_RODZAJU_SERWISU[db.SERWIS_AWARIA]),
            ft.Container(
                content=ft.Column(segmenty, spacing=0, tight=True),
                border_radius=4, clip_behavior=ft.ClipBehavior.HARD_EDGE,
                tooltip=f"{etyk}: {opis}",
            ),
            # Kwartał („4kw/25”) i gęsta siatka łamią podpis na dwie linijki — inaczej
            # ostatnia kolumna wychodzi poza kartę na wąskim telefonie.
            ft.Text(etyk.replace("/", "\n") if ile > 9 or len(etyk) > 5 else etyk, size=rozmiar_etykiety,
                    text_align=ft.TextAlign.CENTER, color=ft.Colors.ON_SURFACE_VARIANT),
        ], alignment=ft.MainAxisAlignment.END, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4))

    obecne = [r for r in KOLEJNOSC_SEGMENTOW if any(s[r] > 0 for s in sumy)]
    return ft.Column([
        ft.Row(kolumny, alignment=ft.MainAxisAlignment.SPACE_EVENLY, vertical_alignment=ft.CrossAxisAlignment.END),
        pasek_zawijany([_kropka_legendy(KOLORY_RODZAJU_SERWISU[r], ETYKIETY_SERII[r]) for r in obecne],
                       spacing=12, run_spacing=4),
    ], spacing=10)


def karta_awarii(page: ft.Page, auto_id, dane, zakres, scena=None, po_zmianie=None):
    """Karta Analizy „Awarie kontra eksploatacja”: udział awarii w koszcie serwisu, paski
    rodzajów, odstępy, słupki w czasie i wejście do oznaczania napraw bez rodzaju."""
    w = symbol_waluty()
    kolor_awarii = KOLORY_RODZAJU_SERWISU[db.SERWIS_AWARIA]
    wiersze = []
    if not dane["naprawy"] and not dane["razem"]:
        wiersze.append(ft.Text("Brak napraw w wybranym okresie.", size=FS["body"], italic=True,
                               color=KOLOR_DRUGIEGO_PLANU))
    else:
        udzial = dane["udzial_awarii"]
        awarie = dane["rodzaje"][db.SERWIS_AWARIA]["kwota"]
        wiersze.append(ft.Row([
            ft.Text(f"{formatuj_liczba(udzial, 0)}%" if udzial is not None else "—",
                    size=FS["display"], weight="bold", color=kolor_awarii),
            ft.Column([
                ft.Text("kosztu serwisu to awarie", size=FS["body"], color=ft.Colors.ON_SURFACE),
                podpis(f"{formatuj_liczba(awarie)} {w} z {formatuj_liczba(dane['razem'])} {w}"),
            ], spacing=0, tight=True, expand=True),
        ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER))
        wiersze.extend(paski_rodzajow(page, dane, scena))
        wiersze.extend(_blok_odstepow(dane))
        wykres = wykres_awarii(page, dane, zakres)
        if wykres is not None:
            wiersze.append(wykres)

    if dane["nieoznaczone"]:
        n = dane["nieoznaczone"]
        tekst = (f"{db.liczba_z_odmiana(n, 'naprawa', 'naprawy', 'napraw')} bez rodzaju — "
                 "oznacz je, a udział awarii obejmie cały serwis.")
        rzad = [podpis(tekst, expand=True)]
        if not db.czy_tylko_podglad(auto_id):
            rzad.append(ft.OutlinedButton(
                "Oznacz", icon=ft.Icons.PLAYLIST_ADD_CHECK,
                on_click=lambda e: pokaz_oznaczanie_napraw(page, auto_id, po_zmianie),
            ))
        wiersze.append(ft.Row(rzad, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER))

    wiersze.append(nota_o_liczeniu(
        page, "Jak liczone",
        "Udział to koszt napraw oznaczonych jako awaria w całym koszcie serwisu z okresu — wizyty "
        "i pojedyncze wpisy, pozycja wizyty liczy się razem z wizytą. Kilka napraw jednego dnia "
        "to jedna awaria; odstęp to średnia przerwa między kolejnymi awariami. Sama suma serwisu "
        "rośnie też wtedy, gdy po prostu jeździsz więcej — rosnący udział awarii już nie.",
    ))
    return ft.Container(
        padding=SPACING["lg"],
        **powierzchnia(page, "karta", cien="md"),
        content=ft.Column(wiersze, spacing=12),
    )


def _chip_wyboru(rodzaj, sugerowany, on_click):
    kolor = KOLORY_RODZAJU_SERWISU[rodzaj]
    return ft.Container(
        padding=ft.Padding(10, 5, 12, 5), border_radius=RADIUS["pill"], ink=True, on_click=on_click,
        bgcolor=ft.Colors.with_opacity(0.14, kolor) if sugerowany else None,
        border=ft.Border.all(1, kolor if sugerowany else ft.Colors.OUTLINE_VARIANT),
        tooltip="Podpowiedź: każdy podzespół ma interwał" if sugerowany else None,
        content=ft.Row([
            ft.Icon(IKONY_RODZAJU_SERWISU[rodzaj], size=15, color=kolor),
            ft.Text(db.ETYKIETY_RODZAJU_SERWISU[rodzaj], size=FS["label"], color=ft.Colors.ON_SURFACE),
        ], spacing=5, tight=True),
    )


def pokaz_oznaczanie_napraw(page: ft.Page, auto_id, po_zamknieciu=None):
    """Arkusz „Naprawy bez rodzaju”: od najnowszej, rodzaj jednym dotknięciem (zapis od razu,
    wiersz znika w miejscu), „Oznacz sugerowane” dla napraw podzespołów z interwałem. Po
    zamknięciu, gdy coś zmieniono — wysyłka do chmury i `po_zamknieciu`."""
    stan = {"zmiany": 0, "zamkniety": False, "naprawy": []}
    bs = ft.BottomSheet(ft.Container(padding=ft.Padding(16, 16, 16, 8), bgcolor=ft.Colors.SURFACE))
    lista = ft.Column(spacing=SPACING["sm"])
    naglowek = podpis("")
    przycisk_sugerowanych = ft.OutlinedButton(icon=ft.Icons.DONE_ALL)

    def po_zamknieciu_arkusza(e=None):
        if stan["zamkniety"]:
            return
        stan["zamkniety"] = True
        if stan["zmiany"]:
            wypchnij_w_tle(page, auto_id, "rodzaj naprawy")
            if po_zamknieciu:
                po_zamknieciu()

    bs.on_dismiss = po_zamknieciu_arkusza

    def zamknij(e=None):
        zamknij_dno(page, bs)
        po_zamknieciu_arkusza()

    def odswiez():
        try:
            bs.update()
        except RuntimeError:
            log.polkniety("odświeżenie arkusza napraw bez rodzaju")

    def sugerowane():
        return [(n["tabela"], n["id"]) for n in stan["naprawy"] if n["sugestia"] == db.SERWIS_PLANOWE]

    def opisz_stan():
        ile = len(stan["naprawy"])
        naglowek.value = (f"{db.liczba_z_odmiana(ile, 'naprawa', 'naprawy', 'napraw')} · dotknij rodzaj, "
                          "zapisuje się od razu" if ile else "Wszystkie naprawy mają rodzaj")
        przycisk_sugerowanych.content = f"Oznacz sugerowane jako planowe ({len(sugerowane())})"
        przycisk_sugerowanych.visible = bool(sugerowane())

    def ustaw_jeden(naprawa, rodzaj, kontrolka):
        stan["zmiany"] += db.ustaw_rodzaj_napraw(auto_id, [(naprawa["tabela"], naprawa["id"])], rodzaj)
        stan["naprawy"] = [n for n in stan["naprawy"] if n is not naprawa]
        if kontrolka in lista.controls:
            lista.controls.remove(kontrolka)
        if not lista.controls:
            wczytaj()
        opisz_stan()
        odswiez()

    def ustaw_sugerowane(e=None):
        stan["zmiany"] += db.ustaw_rodzaj_napraw(auto_id, sugerowane(), db.SERWIS_PLANOWE)
        wczytaj()
        opisz_stan()
        odswiez()

    def wiersz(n):
        opis = " · ".join(x for x in (n["opis"] or "Wizyta bez podzespołów", n["wykonawca"]) if x)
        kontrolka = ft.Container(padding=ft.Padding(12, 8, 12, 10), **powierzchnia(page, "blok"))
        kontrolka.content = ft.Column([
            ft.Row([
                ft.Text(n["data"], size=FS["body"], weight="w500", expand=True),
                wartosc(f"{formatuj_liczba(n['kwota'])} {symbol_waluty()}", size=FS["body"]),
            ], spacing=8),
            podpis(opis, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
            pasek_zawijany([
                _chip_wyboru(r, r == n["sugestia"], lambda e, r=r: ustaw_jeden(n, r, kontrolka))
                for r in db.RODZAJE_SERWISU
            ], spacing=6, run_spacing=6),
        ], spacing=6)
        return kontrolka

    def wczytaj():
        stan["naprawy"] = db.naprawy_bez_rodzaju(auto_id)
        lista.controls = [wiersz(n) for n in stan["naprawy"][:MAKS_W_ARKUSZU]]
        if len(stan["naprawy"]) > MAKS_W_ARKUSZU:
            lista.controls.append(podpis(f"Pokazano {MAKS_W_ARKUSZU} najnowszych z {len(stan['naprawy'])} — "
                                         "starsze pojawią się po oznaczeniu tych."))

    przycisk_sugerowanych.on_click = ustaw_sugerowane
    wczytaj()
    opisz_stan()
    bs.content.content = ft.Column([
        ft.Row([
            ft.Icon(ft.Icons.PLAYLIST_ADD_CHECK, size=22, color=ft.Colors.PRIMARY),
            ft.Column([
                ft.Text("Naprawy bez rodzaju", weight="bold", size=FS["heading"], color=ft.Colors.PRIMARY),
                naglowek,
            ], spacing=0, tight=True, expand=True),
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ft.Divider(height=14),
        przycisk_sugerowanych,
        lista,
        ft.Row([ft.TextButton("Gotowe", on_click=zamknij)], alignment=ft.MainAxisAlignment.END),
        dol_bezpieczny(20),
    ], tight=True, spacing=SPACING["sm"], scroll=ft.ScrollMode.AUTO)
    otworz_dno(page, bs)
    return bs


__all__ = [
    "ETYKIETY_SERII",
    "KOLEJNOSC_SEGMENTOW",
    "MAKS_W_ARKUSZU",
    "OPISY_RODZAJU",
    "PoleRodzajuSerwisu",
    "WYSOKOSC_SLUPKA",
    "_blok_odstepow",
    "_chip_wyboru",
    "_dni",
    "_segment",
    "chip_rodzaju_serwisu",
    "karta_awarii",
    "paski_rodzajow",
    "pokaz_oznaczanie_napraw",
    "wykres_awarii",
]
