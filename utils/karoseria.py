"""Rejestr karoserii na ekranie: kafel zdjęcia, sekcje galerii, mapa stref na sylwetce auta,
pasek par „przed / po”, porównanie przeciąganiem i przeglądarka zdjęć. Dane:
db/karoseria.py; ekrany: views/body_view.py, obchód aparatem — views/obchod_view.py."""

import flet as ft

import db
import log

from .stale import FS, KOLOR_STATUS, RADIUS, SPACING
from .format import formatuj_dystans, jednostka_dystansu
from .typografia import podpis, wartosc
from .wyglad import pasek_przewijany, pasek_zawijany, powierzchnia, tlo_karty
from .miesiace import klucz_miesiaca, nazwa_miesiaca
from .dialogi import otworz_dialog, zamknij_dialog
from .zalaczniki import abs_zalacznik, udostepnij_pliki

# Siatka galerii: 2 kafle w rzędzie na telefonie, 3–6 na szerszych ekranach.
KOLUMNY_GALERII = {"xs": 6, "sm": 4, "md": 3, "xl": 2}
# Kafel dekoduje zdjęcie zmniejszone do tylu pikseli szerokości (pamięć przy dużej galerii).
SZEROKOSC_MINIATURY = 480
# Szybkość przesunięcia palcem (px/s), od której przeglądarka przechodzi do sąsiedniego zdjęcia.
PROG_PRZESUNIECIA = 650

_KROTKIE_TYPY = {db.TYP_ZDJECIA_PRZED: "Przed", db.TYP_ZDJECIA_PO: "Po"}
IKONY_TYPU_ZDJECIA = {db.TYP_ZDJECIA_PRZED: ft.Icons.CAR_CRASH, db.TYP_ZDJECIA_PO: ft.Icons.VERIFIED}
IKONY_STREF_KAROSERII = {
    "Wnętrze / Kokpit": ft.Icons.AIRLINE_SEAT_RECLINE_NORMAL,
    "Uszkodzenie / Rysa": ft.Icons.CAR_CRASH,
    "Inne": ft.Icons.PHOTO_LIBRARY,
}


def kolor_typu_zdjecia(typ):
    """Przed naprawą — uszkodzenie wymaga uwagi (warning), po naprawie — w porządku (ok)."""
    return {db.TYP_ZDJECIA_PRZED: KOLOR_STATUS["warning"], db.TYP_ZDJECIA_PO: KOLOR_STATUS["ok"]}.get(typ)


def odznaka_typu_zdjecia(typ, krotka=False):
    """Pigułka „Przed naprawą” / „Po naprawie”; zwykłe zdjęcie — None."""
    kolor = kolor_typu_zdjecia(typ)
    if kolor is None:
        return None
    napis = _KROTKIE_TYPY[typ] if krotka else db.ETYKIETY_TYPOW_ZDJECIA[typ]
    return ft.Container(
        padding=ft.Padding(7, 3, 9, 3), border_radius=RADIUS["pill"], bgcolor=kolor,
        content=ft.Row([
            ft.Icon(IKONY_TYPU_ZDJECIA[typ], size=13, color=ft.Colors.WHITE),
            ft.Text(napis, size=FS["caption"], weight=ft.FontWeight.W_600, color=ft.Colors.WHITE),
        ], spacing=4, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
    )


def _brak_pliku(ciemne_tlo=False):
    kolor = ft.Colors.with_opacity(0.7, ft.Colors.WHITE) if ciemne_tlo else ft.Colors.ON_SURFACE_VARIANT
    return ft.Container(alignment=ft.Alignment.CENTER, content=ft.Column([
        ft.Icon(ft.Icons.HIDE_IMAGE, size=28, color=kolor),
        ft.Text("Brak pliku zdjęcia", size=FS["caption"], color=kolor, text_align=ft.TextAlign.CENTER),
    ], spacing=4, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER))


def _przyciemnienie(od_dolu=True, mocno=0.72):
    kolory = [ft.Colors.with_opacity(0, ft.Colors.BLACK), ft.Colors.with_opacity(mocno, ft.Colors.BLACK)]
    return ft.LinearGradient(begin=ft.Alignment.TOP_CENTER, end=ft.Alignment.BOTTOM_CENTER,
                             colors=kolory if od_dolu else kolory[::-1])


def _miniatura(zdjecie, szerokosc_cache=SZEROKOSC_MINIATURY):
    sciezka = abs_zalacznik(zdjecie.get("zalacznik"))
    if not sciezka:
        return _brak_pliku()
    return ft.Image(src=sciezka, fit=ft.BoxFit.COVER, cache_width=szerokosc_cache, gapless_playback=True,
                    error_content=_brak_pliku(),
                    semantics_label=f"Zdjęcie karoserii: {zdjecie['strefa']}, {zdjecie['data']}")


def _szerokosc_strony(page):
    try:
        return float(page.width or 0) or 400.0
    except (AttributeError, TypeError, ValueError):
        return 400.0


def _wysokosc_strony(page):
    try:
        return float(page.height or 0) or 800.0
    except (AttributeError, TypeError, ValueError):
        return 800.0


# ---------------------------------------------------------------------------
#  Galeria: kafel i sekcje
# ---------------------------------------------------------------------------

def kafel_zdjecia_karoserii(page, zdjecie, on_menu=None):
    """Kwadratowy kafel: zdjęcie na całą powierzchnię, strefa i data na przyciemnieniu u dołu,
    rodzaj w rogu. Zwraca (kafel, nakładka) — nakładka łapie dotknięcia i pokazuje
    zaznaczenie (`ZaznaczanieGrupowe`), ⋮ leży nad nią."""
    warstwy = [
        ft.Container(left=0, top=0, right=0, bottom=0, content=_miniatura(zdjecie)),
        ft.Container(
            left=0, right=0, bottom=0, padding=ft.Padding(10, 24, 10, 8), gradient=_przyciemnienie(),
            content=ft.Column([
                ft.Text(zdjecie["strefa"], size=FS["body_strong"], weight="bold", color=ft.Colors.WHITE,
                        max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(zdjecie["data"], size=FS["caption"], color=ft.Colors.with_opacity(0.88, ft.Colors.WHITE)),
            ], spacing=0, tight=True),
        ),
    ]
    odznaka = odznaka_typu_zdjecia(zdjecie["typ"], krotka=True)
    if odznaka is not None:
        warstwy.append(ft.Container(left=8, top=8, content=odznaka))
    nakladka = ft.Container(left=0, top=0, right=0, bottom=0, ink=True, border_radius=RADIUS["lg"])
    warstwy.append(nakladka)
    if on_menu is not None:
        warstwy.append(ft.Container(right=2, top=2, content=ft.IconButton(
            icon=ft.Icons.MORE_VERT, icon_color=ft.Colors.WHITE, icon_size=20,
            bgcolor=ft.Colors.with_opacity(0.32, ft.Colors.BLACK), tooltip="Opcje zdjęcia",
            on_click=lambda e: on_menu(),
        )))
    kafel = ft.Container(
        aspect_ratio=1, border_radius=RADIUS["lg"], clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        bgcolor=tlo_karty(page, poziom=2), col=KOLUMNY_GALERII, content=ft.Stack(warstwy),
    )
    return kafel, nakladka


def sekcje_galerii(zdjecia, po_dacie=True):
    """[(tytuł, podpis, [zdjęcia])] w kolejności listy: miesiące, gdy lista idzie po dacie,
    inaczej strefy. Zdjęcie bez czytelnej daty trafia do sekcji „Bez daty”."""
    sekcje, indeks = [], {}
    for z in zdjecia:
        if po_dacie:
            klucz = klucz_miesiaca(z["data"])
            tytul = nazwa_miesiaca(klucz) if klucz else "Bez daty"
        else:
            klucz = tytul = z["strefa"]
        if klucz not in indeks:
            indeks[klucz] = len(sekcje)
            sekcje.append((tytul, []))
        sekcje[indeks[klucz]][1].append(z)
    return [(tytul, db.liczba_z_odmiana(len(lista), "zdjęcie", "zdjęcia", "zdjęć"), lista)
            for tytul, lista in sekcje]


def sekcja_galerii(tytul, opis, kafle):
    """Nagłówek sekcji (miesiąc albo strefa) i siatka jej kafli."""
    return ft.Column([
        ft.Row([
            wartosc(tytul, size=FS["title"]),
            podpis(opis),
        ], spacing=SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ft.ResponsiveRow(kafle, spacing=SPACING["sm"], run_spacing=SPACING["sm"]),
    ], spacing=SPACING["sm"])


# ---------------------------------------------------------------------------
#  Mapa karoserii
# ---------------------------------------------------------------------------

def _kolor_czesci(podsumowanie, strefa, aktywna):
    """Wybrana strefa — pełny kolor, ze zdjęciami — przygaszony, bez zdjęć — kolor nadwozia."""
    if strefa == aktywna:
        return ft.Colors.PRIMARY
    if (podsumowanie.get(strefa) or {}).get("liczba"):
        return ft.Colors.with_opacity(0.5, ft.Colors.PRIMARY)
    return None


def _sylwetka(page, podsumowanie, aktywna):
    """Auto z góry, przodem do góry: maska, boki, dach (wnętrze) i bagażnik w kolorze swojej
    strefy; szczeliny między panelami i szyby w kolorze nadwozia i szkła."""
    def panel(strefa, **uklad):
        return ft.Container(bgcolor=_kolor_czesci(podsumowanie, strefa, aktywna), **uklad)

    szyba = ft.Colors.with_opacity(0.55, ft.Colors.BLACK)
    opona = ft.Colors.with_opacity(0.6, ft.Colors.ON_SURFACE)
    kola = [ft.Container(width=10, height=30, border_radius=4, bgcolor=opona, **pozycja)
            for pozycja in ({"left": 1, "top": 30}, {"right": 1, "top": 30},
                            {"left": 1, "top": 124}, {"right": 1, "top": 124})]
    lusterka = [ft.Container(width=8, height=7, border_radius=3, bgcolor=opona, top=56, **bok)
                for bok in ({"left": 0}, {"right": 0})]
    nadwozie = ft.Container(
        left=6, top=4, width=92, height=176, clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        border_radius=ft.BorderRadius.only(top_left=34, top_right=34, bottom_left=24, bottom_right=24),
        bgcolor=ft.Colors.with_opacity(0.22, ft.Colors.ON_SURFACE),
        content=ft.Stack([
            panel("Przód", left=0, top=0, right=0, height=44),
            panel("Bok lewy", left=0, top=46, width=10, height=93),
            panel("Bok prawy", right=0, top=46, width=10, height=93),
            panel("Wnętrze / Kokpit", left=12, top=70, right=12, height=54, border_radius=6),
            panel("Tył", left=0, bottom=0, right=0, height=35),
            ft.Container(left=12, top=47, right=12, height=20, bgcolor=szyba,
                         border_radius=ft.BorderRadius.only(top_left=10, top_right=10, bottom_left=3, bottom_right=3)),
            ft.Container(left=13, top=127, right=13, height=11, border_radius=3, bgcolor=szyba),
        ]),
    )
    return ft.Semantics(exclude_semantics=True, content=ft.Stack(kola + lusterka + [nadwozie], width=104, height=184))


def _styl_strefy(page, wybrana, ile):
    if wybrana:
        return {"bgcolor": ft.Colors.PRIMARY, "border_radius": RADIUS["sm"]}
    if ile:
        return powierzchnia(page, "blok")
    return {"border": ft.Border.all(1, ft.Colors.with_opacity(0.18, ft.Colors.ON_SURFACE)),
            "border_radius": RADIUS["sm"]}


def _pole_strefy(page, strefa, dane, aktywna, on_strefa, **wymiary):
    """Strefa przy sylwetce: nazwa, liczba zdjęć i data ostatniego; bez zdjęć — sama ramka."""
    ile, ostatnia = dane["liczba"], dane["ostatnia"]
    wybrana = strefa == aktywna
    glowny = ft.Colors.ON_PRIMARY if wybrana else None
    drugi = ft.Colors.with_opacity(0.85, ft.Colors.ON_PRIMARY) if wybrana else ft.Colors.ON_SURFACE_VARIANT
    linie = [
        ft.Text(strefa, size=FS["label"], weight="bold", color=glowny),
        ft.Text(db.liczba_z_odmiana(ile, "zdjęcie", "zdjęcia", "zdjęć") if ile else "brak zdjęć",
                size=FS["caption"], color=drugi),
    ]
    if ostatnia:
        linie.append(ft.Text(ostatnia, size=FS["caption"], color=drugi))
    return ft.Container(
        padding=ft.Padding(8, 6, 8, 6), ink=True, tooltip=f"Pokaż zdjęcia: {strefa}",
        on_click=(lambda e: on_strefa(strefa)) if on_strefa else None,
        content=ft.Column(linie, spacing=0, tight=True), **wymiary, **_styl_strefy(page, wybrana, ile),
    )


def _pigulka_strefy(page, strefa, dane, aktywna, on_strefa):
    ile = dane["liczba"]
    wybrana = strefa == aktywna
    kolor = ft.Colors.ON_PRIMARY if wybrana else None
    styl = _styl_strefy(page, wybrana, ile)
    styl["border_radius"] = RADIUS["pill"]
    return ft.Container(
        padding=ft.Padding(10, 6, 12, 6), ink=True, tooltip=f"Pokaż zdjęcia: {strefa}",
        on_click=(lambda e: on_strefa(strefa)) if on_strefa else None, **styl,
        content=ft.Row([
            ft.Icon(IKONY_STREF_KAROSERII.get(strefa, ft.Icons.PHOTO_CAMERA), size=16,
                    color=kolor or ft.Colors.PRIMARY),
            ft.Text(strefa, size=FS["label"], weight="bold", color=kolor),
            ft.Text(str(ile) if ile else "brak", size=FS["caption"],
                    color=ft.Colors.with_opacity(0.85, ft.Colors.ON_PRIMARY) if wybrana else ft.Colors.ON_SURFACE_VARIANT),
        ], spacing=6, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
    )


def mapa_karoserii(page, podsumowanie, aktywna=None, on_strefa=None, moge_dodawac=True):
    """Karta „Mapa karoserii”: sylwetka auta z góry, przy każdej stronie liczba zdjęć i data
    ostatniego; pozostałe strefy jako pigułki. `on_strefa(strefa)` — dotknięcie strefy."""
    def pole(strefa, **wymiary):
        return _pole_strefy(page, strefa, podsumowanie[strefa], aktywna, on_strefa, **wymiary)

    pokryte = [s for s in db.STREFY_OBCHODU if podsumowanie[s]["liczba"]]
    brakuje = [s for s in db.STREFY_OBCHODU if not podsumowanie[s]["liczba"]]
    if aktywna and aktywna in podsumowanie:
        wskazowka = f"Pokazuję tylko: {aktywna}. Dotknij jej jeszcze raz, żeby wrócić do wszystkich zdjęć."
    elif brakuje and moge_dodawac:
        wskazowka = (f"Bez zdjęć: {', '.join(brakuje)} — dotknij strefy, żeby je dodać. "
                     "Strefa ze zdjęciami zawęża galerię.")
    elif brakuje:
        wskazowka = f"Bez zdjęć: {', '.join(brakuje)}. Dotknij strefy, żeby zobaczyć tylko jej zdjęcia."
    else:
        wskazowka = "Każda strona auta ma zdjęcie. Dotknij strefy, żeby zobaczyć tylko jej zdjęcia."

    pozostale = [s for s in podsumowanie if s not in ("Przód", "Tył", "Bok lewy", "Bok prawy")]
    return ft.Container(
        padding=SPACING["md"], **powierzchnia(page, "karta"),
        content=ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.DIRECTIONS_CAR, size=20, color=ft.Colors.PRIMARY),
                wartosc("Mapa karoserii", expand=True),
                podpis(f"{len(pokryte)} z {len(db.STREFY_OBCHODU)} stref"),
            ], spacing=SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row([ft.Container(expand=True), pole("Przód", width=104), ft.Container(expand=True)],
                   spacing=SPACING["sm"]),
            ft.Row([pole("Bok lewy", expand=True), _sylwetka(page, podsumowanie, aktywna),
                    pole("Bok prawy", expand=True)],
                   spacing=SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row([ft.Container(expand=True), pole("Tył", width=104), ft.Container(expand=True)],
                   spacing=SPACING["sm"]),
            pasek_zawijany([_pigulka_strefy(page, s, podsumowanie[s], aktywna, on_strefa) for s in pozostale],
                           spacing=SPACING["sm"], run_spacing=SPACING["sm"]),
            podpis(wskazowka),
        ], spacing=SPACING["sm"], horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
    )


# ---------------------------------------------------------------------------
#  Pary „przed / po” i porównanie
# ---------------------------------------------------------------------------

def _kafel_pary(page, para, on_para):
    szer, wys = 220, 132
    pol = szer / 2
    nakladka = ft.Container(left=0, top=0, right=0, bottom=0, ink=True, border_radius=RADIUS["lg"],
                            tooltip=f"Porównaj: {para['strefa']}", on_click=lambda e: on_para(para))
    return ft.Container(
        width=szer, height=wys, border_radius=RADIUS["lg"], clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        bgcolor=tlo_karty(page, poziom=2),
        content=ft.Stack([
            ft.Container(left=0, top=0, width=pol, height=wys, content=_miniatura(para["przed"], 360)),
            ft.Container(right=0, top=0, width=pol, height=wys, content=_miniatura(para["po"], 360)),
            ft.Container(left=pol - 1, top=0, width=2, height=wys, bgcolor=ft.Colors.WHITE),
            ft.Container(left=pol - 14, top=wys / 2 - 24, width=28, height=28, border_radius=14,
                         bgcolor=ft.Colors.WHITE, alignment=ft.Alignment.CENTER,
                         content=ft.Icon(ft.Icons.COMPARE_ARROWS, size=16, color=ft.Colors.BLACK)),
            ft.Container(left=6, top=6, content=odznaka_typu_zdjecia(db.TYP_ZDJECIA_PRZED, krotka=True)),
            ft.Container(right=6, top=6, content=odznaka_typu_zdjecia(db.TYP_ZDJECIA_PO, krotka=True)),
            ft.Container(
                left=0, right=0, bottom=0, padding=ft.Padding(10, 18, 10, 6), gradient=_przyciemnienie(),
                content=ft.Column([
                    ft.Text(para["strefa"], size=FS["label"], weight="bold", color=ft.Colors.WHITE),
                    ft.Text(f"{para['przed']['data']} – {para['po']['data']}", size=FS["caption"],
                            color=ft.Colors.with_opacity(0.88, ft.Colors.WHITE)),
                ], spacing=0, tight=True),
            ),
            nakladka,
        ]),
    )


def pasek_par_przed_po(page, pary, on_para):
    """Naprawy z kompletem zdjęć: pół „przed”, pół „po”; dotknięcie otwiera porównanie."""
    return ft.Column([
        ft.Row([
            ft.Icon(ft.Icons.COMPARE, size=20, color=ft.Colors.PRIMARY),
            wartosc("Przed i po naprawie", expand=True),
            podpis(db.liczba_z_odmiana(len(pary), "naprawa", "naprawy", "napraw")),
        ], spacing=SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        pasek_przewijany([_kafel_pary(page, p, on_para) for p in pary], spacing=SPACING["sm"]),
    ], spacing=SPACING["sm"])


def _obraz_porownania(zdjecie, szer, wys):
    sciezka = abs_zalacznik(zdjecie.get("zalacznik"))
    if not sciezka:
        return ft.Container(width=szer, height=wys, bgcolor=ft.Colors.BLACK, content=_brak_pliku(ciemne_tlo=True))
    return ft.Image(src=sciezka, width=szer, height=wys, fit=ft.BoxFit.COVER, gapless_playback=True,
                    error_content=_brak_pliku(ciemne_tlo=True))


def _etykieta_porownania(tekst, **pozycja):
    return ft.Container(
        padding=ft.Padding(8, 4, 8, 4), border_radius=RADIUS["xs"],
        bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK), **pozycja,
        content=ft.Text(tekst, size=FS["caption"], weight="bold", color=ft.Colors.WHITE),
    )


def porownaj_zdjecia_karoserii(page, przed, po):
    """Okno porównania: „po” pod spodem, „przed” odsłaniane przeciąganiem palcem po zdjęciu
    (albo suwakiem). Starsze zdjęcie zawsze jako „przed”. Zwraca okno."""
    if (po.get("porzadek", 0), po.get("id", 0)) < (przed.get("porzadek", 0), przed.get("id", 0)):
        przed, po = po, przed
    szer = int(max(240, min(_szerokosc_strony(page) - 48, 560)))
    wys = int(max(220, min(szer * 4 / 3, _wysokosc_strony(page) * 0.58)))
    start = szer / 2

    warstwa_przed = ft.Container(
        left=0, top=0, width=start, height=wys, clip_behavior=ft.ClipBehavior.HARD_EDGE,
        content=ft.Stack([ft.Container(left=0, top=0, content=_obraz_porownania(przed, szer, wys))]),
    )
    linia = ft.Container(left=start - 1.5, top=0, width=3, height=wys, bgcolor=ft.Colors.WHITE)
    uchwyt = ft.Container(
        left=start - 20, top=wys / 2 - 20, width=40, height=40, border_radius=20, bgcolor=ft.Colors.WHITE,
        alignment=ft.Alignment.CENTER,
        shadow=ft.BoxShadow(blur_radius=8, color=ft.Colors.with_opacity(0.4, ft.Colors.BLACK)),
        content=ft.Icon(ft.Icons.COMPARE_ARROWS, size=20, color=ft.Colors.BLACK),
    )
    obszar = ft.Stack([
        ft.Container(left=0, top=0, content=_obraz_porownania(po, szer, wys)),
        warstwa_przed, linia, uchwyt,
        _etykieta_porownania(f"PRZED · {przed['data']}", left=10, top=10),
        _etykieta_porownania(f"PO · {po['data']}", right=10, top=10),
    ], width=szer, height=wys)
    suwak = ft.Slider(min=0, max=szer, value=start, active_color=ft.Colors.PRIMARY)

    def przesun(x, od_suwaka=False):
        x = max(0.0, min(float(szer), float(x)))
        warstwa_przed.width = x
        linia.left = x - 1.5
        uchwyt.left = x - 20
        suwak.value = x
        try:
            obszar.update()
            if not od_suwaka:
                suwak.update()
        except RuntimeError:
            log.polkniety("przesunięcie linii porównania karoserii")

    def pozycja(e):
        miejsce = getattr(e, "local_position", None)
        if miejsce is not None:
            przesun(miejsce.x)

    suwak.on_change = lambda e: przesun(e.control.value, od_suwaka=True)
    gest = ft.GestureDetector(content=obszar, drag_interval=16, on_horizontal_drag_update=pozycja,
                              on_tap_down=pozycja)

    tytul = przed["strefa"] if przed["strefa"] == po["strefa"] else f"{przed['strefa']} / {po['strefa']}"
    opisy = [podpis(f"{nazwa}: {z['opis']}") for nazwa, z in (("Przed", przed), ("Po", po)) if z.get("opis")]
    dlg = ft.AlertDialog(
        inset_padding=ft.Padding(12, 24, 12, 24), content_padding=ft.Padding(12, 16, 12, 0),
        content=ft.Column([
            ft.Row([ft.Icon(ft.Icons.COMPARE, size=20, color=ft.Colors.PRIMARY),
                    wartosc(tytul, size=FS["title"], expand=True)],
                   spacing=SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Container(width=szer, height=wys, border_radius=RADIUS["md"], clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                         content=gest),
            suwak,
            podpis("Przeciągnij palcem po zdjęciu albo suwakiem: z lewej „przed”, z prawej „po”."),
            *opisy,
        ], spacing=SPACING["sm"], tight=True),
        actions=[ft.TextButton("Zamknij", on_click=lambda e: zamknij_dialog(page, dlg))],
    )
    otworz_dialog(page, dlg)
    return dlg


# ---------------------------------------------------------------------------
#  Przeglądarka zdjęć
# ---------------------------------------------------------------------------

class PrzegladarkaKaroserii:
    """Zdjęcia galerii na pełnym ekranie: przybliżanie palcami, strzałki i przesunięcie do
    sąsiednich, opis, przebieg i akcje. `on_menu(zdjecie, przegladarka)` — menu ⋮;
    `pary` — {id zdjęcia: para} z `db.pary_przed_po`."""

    def __init__(self, page, zdjecia, indeks=0, on_menu=None, pary=None):
        self._page = page
        self.zdjecia = list(zdjecia)
        self.indeks = max(0, min(int(indeks or 0), len(self.zdjecia) - 1))
        self.on_menu = on_menu
        self.pary = pary or {}
        self.j = jednostka_dystansu()
        self._palce = 1

        biel = ft.Colors.WHITE
        self.licznik = ft.Text("", size=FS["body_strong"], weight="bold", color=biel, expand=True)
        self.obszar = ft.Container(left=0, top=0, right=0, bottom=0)
        self.odznaka = ft.Container()
        self.strefa = ft.Text("", size=FS["heading"], weight="bold", color=biel, max_lines=2,
                              overflow=ft.TextOverflow.ELLIPSIS)
        self.szczegoly = ft.Text("", size=FS["label"], color=ft.Colors.with_opacity(0.85, biel))
        self.opis = ft.Text("", size=FS["body"], color=biel, max_lines=4, overflow=ft.TextOverflow.ELLIPSIS)
        self.przycisk_pary = ft.Button(content="Porównaj przed i po", icon=ft.Icons.COMPARE,
                                       on_click=lambda e: self.porownaj())
        self.w_lewo = self._strzalka(ft.Icons.CHEVRON_LEFT, "Poprzednie zdjęcie", self.poprzednie, left=4)
        self.w_prawo = self._strzalka(ft.Icons.CHEVRON_RIGHT, "Następne zdjęcie", self.nastepne, right=4)

        gora = [ft.IconButton(icon=ft.Icons.CLOSE, icon_color=biel, tooltip="Zamknij", on_click=lambda e: self.zamknij()),
                self.licznik,
                ft.IconButton(icon=ft.Icons.SHARE, icon_color=biel, tooltip="Udostępnij zdjęcie",
                              on_click=self._udostepnij)]
        if on_menu is not None:
            gora.append(ft.IconButton(icon=ft.Icons.MORE_VERT, icon_color=biel, tooltip="Opcje zdjęcia",
                                      on_click=lambda e: self.on_menu(self.biezace, self)))
        self.dialog = ft.AlertDialog(
            content_padding=0, inset_padding=0, title_padding=0, actions_padding=0, bgcolor=ft.Colors.BLACK,
            shape=ft.RoundedRectangleBorder(radius=0),
            content=ft.Container(width=10000, height=10000, content=ft.Stack([
                self.obszar,
                ft.Container(left=0, top=0, right=0, padding=ft.Padding(4, 4, 4, 28),
                             gradient=_przyciemnienie(od_dolu=False, mocno=0.65),
                             content=ft.Row(gora, spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER)),
                self.w_lewo,
                self.w_prawo,
                ft.Container(left=0, right=0, bottom=0, padding=ft.Padding(16, 36, 16, 20), gradient=_przyciemnienie(),
                             content=ft.Column([self.odznaka, self.strefa, self.szczegoly, self.opis,
                                                self.przycisk_pary], spacing=6, tight=True)),
            ])),
        )
        self._pokaz()

    @property
    def biezace(self):
        return self.zdjecia[self.indeks]

    @staticmethod
    def _strzalka(ikona, opis, funkcja, **bok):
        return ft.Container(top=0, bottom=0, width=56, alignment=ft.Alignment.CENTER, **bok, content=ft.IconButton(
            icon=ikona, icon_color=ft.Colors.WHITE, icon_size=30, tooltip=opis,
            bgcolor=ft.Colors.with_opacity(0.35, ft.Colors.BLACK), on_click=lambda e: funkcja(),
        ))

    def _obraz(self, z):
        sciezka = abs_zalacznik(z.get("zalacznik"))
        if not sciezka:
            return _brak_pliku(ciemne_tlo=True)
        return ft.InteractiveViewer(
            min_scale=1.0, max_scale=5.0, boundary_margin=ft.Margin.all(0),
            on_interaction_start=self._poczatek_gestu, on_interaction_end=self._koniec_gestu,
            content=ft.Image(src=sciezka, fit=ft.BoxFit.CONTAIN, gapless_playback=True,
                             error_content=_brak_pliku(ciemne_tlo=True),
                             semantics_label=f"Zdjęcie karoserii: {z['strefa']}, {z['data']}"),
        )

    def _pokaz(self):
        z = self.biezace
        self._palce = 1
        self.obszar.content = self._obraz(z)
        self.licznik.value = f"{self.indeks + 1} z {len(self.zdjecia)}"
        odznaka = odznaka_typu_zdjecia(z["typ"])
        self.odznaka.content, self.odznaka.visible = odznaka, odznaka is not None
        self.strefa.value = z["strefa"]
        czesci = [z["data"]] if z["data"] else []
        if z.get("przebieg"):
            czesci.append(formatuj_dystans(z["przebieg"], 0, self.j))
        self.szczegoly.value = " · ".join(czesci)
        self.opis.value, self.opis.visible = z["opis"], bool(z["opis"])
        self.przycisk_pary.visible = z["id"] in self.pary
        self.w_lewo.visible = self.indeks > 0
        self.w_prawo.visible = self.indeks < len(self.zdjecia) - 1

    def _odswiez(self):
        try:
            self.dialog.update()
        except RuntimeError:
            log.polkniety("odświeżenie przeglądarki zdjęć karoserii")

    def przejdz_do(self, indeks):
        if 0 <= indeks < len(self.zdjecia) and indeks != self.indeks:
            self.indeks = indeks
            self._pokaz()
            self._odswiez()

    def poprzednie(self):
        self.przejdz_do(self.indeks - 1)

    def nastepne(self):
        self.przejdz_do(self.indeks + 1)

    def _poczatek_gestu(self, e):
        # Dwa palce to przybliżanie — przesunięcie po powiększonym zdjęciu nie zmienia zdjęcia.
        self._palce = max(self._palce, int(getattr(e, "pointer_count", 1) or 1))

    def _koniec_gestu(self, e):
        if self._palce > 1:
            return
        predkosc = getattr(e, "velocity", None)
        vx, vy = float(getattr(predkosc, "x", 0) or 0), float(getattr(predkosc, "y", 0) or 0)
        if abs(vx) >= PROG_PRZESUNIECIA and abs(vx) > 1.5 * abs(vy):
            if vx < 0:
                self.nastepne()
            else:
                self.poprzednie()

    async def _udostepnij(self, e):
        sciezka = abs_zalacznik(self.biezace.get("zalacznik"))
        await udostepnij_pliki(self._page, [sciezka] if sciezka else [])

    def porownaj(self):
        para = self.pary.get(self.biezace["id"])
        if para:
            porownaj_zdjecia_karoserii(self._page, para["przed"], para["po"])

    def otworz(self):
        otworz_dialog(self._page, self.dialog)
        return self

    def zamknij(self):
        zamknij_dialog(self._page, self.dialog)


def pokaz_przegladarke_karoserii(page, zdjecia, indeks=0, on_menu=None, pary=None):
    """Otwiera przeglądarkę na zdjęciu `indeks` listy (w kolejności galerii)."""
    if not zdjecia:
        return None
    return PrzegladarkaKaroserii(page, zdjecia, indeks, on_menu=on_menu, pary=pary).otworz()


# ---------------------------------------------------------------------------
#  Formularz: pojedynczy wybór w chipach
# ---------------------------------------------------------------------------

class WyborChipami:
    """Jedna opcja z kilku jako chipy w zawijanym wierszu. `value` jak w polu formularza,
    `kontrolka` do ułożenia; `etykiety` — napis na chipie dla wartości z bazy."""

    def __init__(self, opcje, wartosc_poczatkowa, etykiety=None, ikony=None, on_zmiana=None):
        self.value = wartosc_poczatkowa if wartosc_poczatkowa in opcje else opcje[0]
        self.on_zmiana = on_zmiana
        self.chipy = {}
        for opcja in opcje:
            ikona = (ikony or {}).get(opcja)
            self.chipy[opcja] = ft.Chip(
                label=ft.Text((etykiety or {}).get(opcja, opcja)),
                leading=ft.Icon(ikona, size=18) if ikona else None,
                selected=opcja == self.value, show_checkmark=ikona is None,
                on_select=lambda e, o=opcja: self.wybierz(o),
            )
        self.kontrolka = pasek_zawijany(list(self.chipy.values()), spacing=SPACING["sm"], run_spacing=SPACING["xs"])

    def wybierz(self, opcja):
        # Dotknięcie wybranego chipa go nie gasi — zawsze jedna opcja jest wybrana.
        self.value = opcja
        for klucz, chip in self.chipy.items():
            chip.selected = klucz == opcja
        try:
            self.kontrolka.update()
        except RuntimeError:
            log.polkniety("odświeżenie wyboru w chipach")
        if self.on_zmiana:
            self.on_zmiana(opcja)


__all__ = [
    "IKONY_STREF_KAROSERII",
    "IKONY_TYPU_ZDJECIA",
    "KOLUMNY_GALERII",
    "PROG_PRZESUNIECIA",
    "PrzegladarkaKaroserii",
    "SZEROKOSC_MINIATURY",
    "WyborChipami",
    "kafel_zdjecia_karoserii",
    "kolor_typu_zdjecia",
    "mapa_karoserii",
    "odznaka_typu_zdjecia",
    "pasek_par_przed_po",
    "pokaz_przegladarke_karoserii",
    "porownaj_zdjecia_karoserii",
    "sekcja_galerii",
    "sekcje_galerii",
]
