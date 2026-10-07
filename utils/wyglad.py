"""Motyw jasny/ciemny, tryb OLED, tła i cienie kart, margines bezpieczny."""

import colorsys
import db
import flet as ft

from .stale import KOLOR_STATUS, MAPA_KOLOROW, RADIUS


def _czy_ciemny(page: ft.Page = None) -> bool:
    if page is None:
        return False
    try:
        if page.theme_mode == ft.ThemeMode.DARK:
            return True
        if page.theme_mode == ft.ThemeMode.LIGHT:
            return False
        return getattr(page, "platform_brightness", None) == ft.Brightness.DARK
    except Exception:
        return False


# Ustawienie czytane jest przy KAŻDEJ karcie na ekranie (tlo_karty), więc
# trzymamy je w pamięci zamiast odpytywać SQLite kilkadziesiąt razy na render.
# Unieważnia je zapis w Ustawieniach — patrz odswiez_cache_czerni().
_CACHE_CZERNI = {"wartosc": None}


def odswiez_cache_czerni():
    """Wołane po zapisaniu przełącznika „czysta czerń”, żeby kolejny render
    wziął nową wartość z bazy."""
    _CACHE_CZERNI["wartosc"] = None


def czy_czysta_czern(page: ft.Page = None) -> bool:
    """True, gdy jesteśmy w trybie ciemnym ORAZ użytkownik włączył w Ustawieniach
    wariant „czysta czerń (OLED)”. Sam przełącznik nie wystarczy — w trybie
    jasnym (albo systemowym, który akurat jest jasny) czerń nic nie zmienia."""
    if _CACHE_CZERNI["wartosc"] is None:
        try:
            _CACHE_CZERNI["wartosc"] = db.pobierz_czysta_czern()
        except Exception:
            _CACHE_CZERNI["wartosc"] = False
    return _czy_ciemny(page) and _CACHE_CZERNI["wartosc"]


# Drabinka powierzchni dla wariantu OLED. Materiał 3 rozróżnia elementy
# jasnością tła; przy czystej czerni ta drabinka startuje od #000000 i rośnie
# ledwie kilkoma stopniami szarości, żeby dialogi i menu nadal dało się odróżnić
# od tła, ale ekran pozostał w praktyce zgaszony.
POWIERZCHNIE_OLED = {
    "surface": "#000000",
    "surface_dim": "#000000",
    "surface_bright": "#1A1A1A",
    "surface_container_lowest": "#000000",
    "surface_container_low": "#0A0A0A",
    "surface_container": "#101010",
    "surface_container_high": "#161616",
    "surface_container_highest": "#1E1E1E",
}


def zbuduj_motyw_ciemny(kolor_seed):
    """Motyw ciemny dla zadanego koloru wiodącego. Przy włączonej „czystej
    czerni” podmieniamy wszystkie powierzchnie na czarne — reszta schematu
    (kolor wiodący, akcenty, kolory tekstu) nadal pochodzi z ziarna, więc
    aplikacja wygląda tak samo, tylko na czarnym tle."""
    if not db.pobierz_czysta_czern():
        return ft.Theme(color_scheme_seed=kolor_seed)

    return ft.Theme(
        color_scheme_seed=kolor_seed,
        color_scheme=ft.ColorScheme(**POWIERZCHNIE_OLED),
        scaffold_bgcolor=POWIERZCHNIE_OLED["surface"],
        card_bgcolor=POWIERZCHNIE_OLED["surface"],
        canvas_color=POWIERZCHNIE_OLED["surface"],
    )


# Nazwa koloru FAKTYCZNIE zastosowanego do interfejsu. Router (main.trasa_zmieniona)
# przebudowuje motyw dopiero wtedy, gdy kolor się zmienił — bez tego znacznika
# nie widziałby podglądu włączonego z Ustawień i porzucony (niezapisany) kolor
# zostawał na ekranie aż do zmiany pojazdu.
_OSTATNI_MOTYW = {"nazwa": None}


def ostatni_zastosowany_motyw():
    """Nazwa koloru ostatnio wgranego w page.theme — patrz zastosuj_motywy."""
    return _OSTATNI_MOTYW["nazwa"]


def zastosuj_motywy(page: ft.Page, nazwa_koloru):
    """Jedno miejsce ustawiające page.theme i page.dark_theme — wcześniej ta sama
    para przypisań powtarzała się w main.py (start, import bazy, zmiana pojazdu)
    i w Ustawieniach, przez co wariant OLED trzeba by dokładać w czterech
    miejscach. Zwraca użyte ziarno koloru."""
    kolor_seed = MAPA_KOLOROW.get(nazwa_koloru, ft.Colors.INDIGO)
    page.theme = ft.Theme(color_scheme_seed=kolor_seed)
    page.dark_theme = zbuduj_motyw_ciemny(kolor_seed)
    _OSTATNI_MOTYW["nazwa"] = nazwa_koloru
    return kolor_seed


# Drabinka powierzchni: (jasny, ciemny). Górny stopień NIE jest podwojony tak
# jak dwa niższe — w ciemności różnica jasności rośnie szybciej niż w świetle,
# więc 30% bieli nie czytałoby się jako „karta wyżej", tylko jako jasny
# prostokąt. Dwa niższe stopnie zostają dokładnie takie, jakie były.
DRABINKA_POWIERZCHNI = {
    1: (0.03, 0.06),   # karta na tle ekranu (jasny motyw — unosi ją cień)
    2: (0.08, 0.16),   # pole formularza, karta w ciemnym motywie, blok w karcie
    3: (0.15, 0.24),   # najwyższy stopień — karta, na którą trzeba spojrzeć pierwszą
}

DRABINKA_OLED = {1: 0.05, 2: 0.09, 3: 0.14}

NAJWYZSZY_POZIOM = 3


def tlo_karty(page: ft.Page = None, poziom=1):
    """Tło powierzchni na zadanym stopniu drabinki. W czystej czerni drabinka zaczyna od
    niemal czerni i rośnie ledwie kilkoma stopniami (OLED: jak najwięcej zgaszonych
    pikseli)."""
    if czy_czysta_czern(page):
        udzial = DRABINKA_OLED.get(poziom)
    else:
        stopien = DRABINKA_POWIERZCHNI.get(poziom)
        udzial = None if stopien is None else stopien[1 if _czy_ciemny(page) else 0]
    if udzial is None:
        return ft.Colors.TRANSPARENT
    return ft.Colors.with_opacity(udzial, ft.Colors.ON_SURFACE)


# Powierzchnia w stanie bierze ten sam szczebel drabinki, tylko w kolorze stanu
# zamiast neutralnej szarości. To jeden mechanizm, a nie drugi: kafel po terminie
# nie dostaje „szarości wyżej ORAZ czerwieni" — dostaje ten sam stopień wyżej,
# wyrażony barwą, która i tak już mówi, co się dzieje.
UDZIAL_TLA_STANU = {"jasny": 0.08, "ciemny": 0.14, "oled": 0.10}


def tlo_stanu(page: ft.Page = None, stan=None):
    """Tło powierzchni, która ma coś do powiedzenia o swoim stanie."""
    kolor = KOLOR_STATUS.get(stan)
    if kolor is None:
        return ft.Colors.TRANSPARENT
    if czy_czysta_czern(page):
        udzial = UDZIAL_TLA_STANU["oled"]
    else:
        udzial = UDZIAL_TLA_STANU["ciemny" if _czy_ciemny(page) else "jasny"]
    return ft.Colors.with_opacity(udzial, kolor)


def cien_karty(page: ft.Page = None, poziom="md"):
    """Cień Material 3 (dwie warstwy) — WYŁĄCZNIE w jasnym motywie; w ciemnym None, a
    powierzchnie różnicuje jaśniejszy `bgcolor` (`powierzchnia`)."""
    if _czy_ciemny(page):
        return None
    warstwy = {
        "sm": [  # lekkie karty na listach — jeden, ciasny cień
            ft.BoxShadow(blur_radius=6, spread_radius=0, offset=ft.Offset(0, 1),
                         color=ft.Colors.with_opacity(0.05, ft.Colors.BLACK)),
        ],
        "md": [  # karty formularzy
            ft.BoxShadow(blur_radius=3, spread_radius=0, offset=ft.Offset(0, 1),
                         color=ft.Colors.with_opacity(0.04, ft.Colors.BLACK)),
            ft.BoxShadow(blur_radius=20, spread_radius=-6, offset=ft.Offset(0, 8),
                         color=ft.Colors.with_opacity(0.08, ft.Colors.BLACK)),
        ],
        "lg": [  # modale / bottom sheety
            ft.BoxShadow(blur_radius=4, spread_radius=0, offset=ft.Offset(0, 2),
                         color=ft.Colors.with_opacity(0.05, ft.Colors.BLACK)),
            ft.BoxShadow(blur_radius=28, spread_radius=-8, offset=ft.Offset(0, 14),
                         color=ft.Colors.with_opacity(0.12, ft.Colors.BLACK)),
        ],
    }
    return warstwy.get(poziom, warstwy["md"])


def obramowanie_karty(page: ft.Page = None):
    """Delikatna ramka używana WYŁĄCZNIE w wariancie czystej czerni. Bez cienia
    (tryb ciemny) i bez rozjaśnionego tła (tryb OLED) karta nie miałaby żadnej
    krawędzi — hairline 1px na 12% ON_SURFACE wystarczy, żeby oko zobaczyło
    granicę, a piksele nadal pozostają praktycznie czarne."""
    if not czy_czysta_czern(page):
        return None
    return ft.Border.all(1, ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE))


# Powierzchnię opisują DWIE rzeczy: rola (czym prostokąt JEST) i stan (jak głośno mówi).
# Role:
# - „karta” — na tle ekranu; jasny: tło + cień, ciemny: tło o stopień mocniejsze, OLED:
#   minimalne tło + cienka ramka;
# - „kafel” — w siatce (kokpit): tło BEZ cienia;
# - „blok” — WEWNĄTRZ karty: tło o stopień wyżej od rodzica, bez cienia i ramki,
#   mniejszy promień.
ROLE_POWIERZCHNI = ("karta", "kafel", "blok")

# Stany (klucze z KOLOR_STATUS), które SAME podnoszą powierzchnię o stopień — kafel
# wymagający reakcji wystaje z siatki.
STANY_PODNOSZACE = frozenset({"critical", "warning"})


def poziom_karty(page: ft.Page = None):
    """Stopień, na którym leży ZWYKŁA karta.

    W trybie ciemnym o jeden wyżej, bo tam nie ma cienia i to tło musi zrobić
    krawędź. W wariancie OLED z powrotem na dole — krawędź robi ramka, a piksele
    mają zostać zgaszone."""
    if czy_czysta_czern(page):
        return 1
    return 2 if _czy_ciemny(page) else 1


def powierzchnia(page: ft.Page = None, rola="karta", stan=None, cien="sm",
                 poziom_rodzica=None):
    """{bgcolor, shadow, border, border_radius} do rozpakowania (**) w Containerze; rola
    decyduje o wszystkich czterech naraz. `poziom_rodzica` TYLKO dla bloku w karcie
    podniesionej stanem."""
    baza = poziom_karty(page)
    podniesiony = stan in STANY_PODNOSZACE

    if rola == "blok":
        poziom = min(NAJWYZSZY_POZIOM, (poziom_rodzica or baza) + 1)
        return {
            "bgcolor": tlo_stanu(page, stan) if podniesiony else tlo_karty(page, poziom=poziom),
            "shadow": None, "border": None, "border_radius": RADIUS["sm"],
        }

    if rola == "kafel":
        cienie = None
    else:
        cienie = cien_karty(page, "md" if (podniesiony and cien == "sm") else cien)

    return {
        "bgcolor": tlo_stanu(page, stan) if podniesiony else tlo_karty(page, poziom=baza),
        "shadow": cienie,
        "border": obramowanie_karty(page),
        "border_radius": RADIUS["lg"],
    }


# Tło toru paska postępu — JEDNA wartość dla pasków budżetu, terminu i checklisty.
UDZIAL_TLA_TORU = 0.12


def tlo_toru(page: ft.Page = None):
    """Tło toru, po którym jedzie wypełnienie paska postępu."""
    return ft.Colors.with_opacity(UDZIAL_TLA_TORU, ft.Colors.ON_SURFACE)


# Tło neutralnej odznaki („rok w toku", autor wpisu, kółko pod ikoną). Też jedna
# wartość: pigułka jest pigułką niezależnie od ekranu, a chodziła w 0,10 i 0,14.
UDZIAL_TLA_ODZNAKI = 0.10


def tlo_odznaki(page: ft.Page = None):
    """Tło odznaki bez stanu. Odznaka ze stanem bierze `tlo_stanu`."""
    return ft.Colors.with_opacity(UDZIAL_TLA_ODZNAKI, ft.Colors.ON_SURFACE)


def stan_z_koloru(kolor):
    """Stan podnoszący odczytany z koloru, którym element już się posługuje — kolor
    treści i powierzchni nie mogą się rozjechać."""
    for nazwa in STANY_PODNOSZACE:
        if kolor == KOLOR_STATUS.get(nazwa):
            return nazwa
    return None


def dol_bezpieczny(wysokosc=20):
    return ft.SafeArea(
        content=ft.Container(height=wysokosc),
        avoid_intrusions_top=False,
    )


def _mieszaj_kolory(kolor_a, kolor_b, udzial):
    """Interpolacja dwóch kolorów RGB przez przestrzeń HSV. Mieszanie wprost na
    kanałach RGB prowadzi w połowie drogi z pomarańczy do zieleni przez brudną
    oliwkę (kanał czerwony spada, zielony jeszcze nie urósł) — w HSV kręcimy
    odcieniem, więc każdy punkt skali zostaje nasycony."""
    udzial = max(0.0, min(1.0, udzial))
    h1, s1, v1 = colorsys.rgb_to_hsv(*[k / 255 for k in kolor_a])
    h2, s2, v2 = colorsys.rgb_to_hsv(*[k / 255 for k in kolor_b])
    h = h1 + (h2 - h1) * udzial
    s = s1 + (s2 - s1) * udzial
    v = v1 + (v2 - v1) * udzial
    return tuple(int(round(k * 255)) for k in colorsys.hsv_to_rgb(h, s, v))


# Rezerwa POD treścią na suwak przewijania — inaczej leży na kafelkach (a bez suwaka
# myszą nie da się przewinąć).
MIEJSCE_NA_SUWAK = 16


def pasek_przewijany(kontrolki, spacing=10, miejsce_na_suwak=MIEJSCE_NA_SUWAK,
                     wyrownanie=ft.CrossAxisAlignment.CENTER):
    """Poziomy pasek z chwytalnym suwakiem, który NIE nachodzi na treść (padding
    wewnątrz przewijanego wiersza). Tylko dla treści, która musi jechać w bok (mapa
    cieplna, karty sekcji); kokpit to siatka (ResponsiveRow)."""
    if not kontrolki:
        return ft.Container()
    return ft.Row(
        [ft.Container(
            content=ft.Row(kontrolki, spacing=spacing, vertical_alignment=wyrownanie),
            padding=ft.Padding.only(bottom=miejsce_na_suwak),
        )],
        scroll=ft.ScrollMode.ALWAYS,
    )


def pasek_zawijany(kontrolki, spacing=6, run_spacing=6):
    """Pasek kontrolek ZAWIJANY do następnej linijki — dla kontrolek z własną
    szerokością (przyciski z tekstem, chipy ekranów w szufladzie). NIE dla chipów
    filtrów i sortowania: `Wrap` daje dziecku pełną szerokość, a chip na
    `PopupMenuButton` bierze wszystko (każdy filtr w osobnej linii). Paski filtrów:
    `ft.Row(controls=…, scroll=ft.ScrollMode.ADAPTIVE, spacing=8)`."""
    if not kontrolki:
        return ft.Container()
    return ft.Row(kontrolki, spacing=spacing, run_spacing=run_spacing, wrap=True,
                  vertical_alignment=ft.CrossAxisAlignment.CENTER)


__all__ = [
    "DRABINKA_OLED",
    "DRABINKA_POWIERZCHNI",
    "MIEJSCE_NA_SUWAK",
    "NAJWYZSZY_POZIOM",
    "ROLE_POWIERZCHNI",
    "STANY_PODNOSZACE",
    "UDZIAL_TLA_STANU",
    "UDZIAL_TLA_ODZNAKI",
    "UDZIAL_TLA_TORU",
    "POWIERZCHNIE_OLED",
    "_CACHE_CZERNI",
    "_OSTATNI_MOTYW",
    "_czy_ciemny",
    "_mieszaj_kolory",
    "cien_karty",
    "czy_czysta_czern",
    "dol_bezpieczny",
    "obramowanie_karty",
    "odswiez_cache_czerni",
    "ostatni_zastosowany_motyw",
    "pasek_przewijany",
    "pasek_zawijany",
    "poziom_karty",
    "powierzchnia",
    "stan_z_koloru",
    "tlo_karty",
    "tlo_odznaki",
    "tlo_stanu",
    "tlo_toru",
    "zastosuj_motywy",
    "zbuduj_motyw_ciemny",
]
