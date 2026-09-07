"""Motyw jasny/ciemny, tryb OLED, tła i cienie kart, margines bezpieczny."""

import colorsys
import db
import flet as ft

from .stale import MAPA_KOLOROW


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


def tlo_karty(page: ft.Page = None, poziom=1):
    """Automatycznie dobiera przezroczystość koloru ON_SURFACE.
    W trybie ciemnym podwaja opacity dla zachowania kontrastu.
    W wariancie czystej czerni schodzimy z powrotem do delikatnych wartości —
    na czarnym tle nawet 6% bieli to już wyraźnie widoczna powierzchnia, a cały
    sens trybu OLED polega na tym, żeby jak najwięcej pikseli zostało zgaszonych."""
    if czy_czysta_czern(page):
        return {
            1: ft.Colors.with_opacity(0.05, ft.Colors.ON_SURFACE),
            2: ft.Colors.with_opacity(0.09, ft.Colors.ON_SURFACE),
            3: ft.Colors.with_opacity(0.14, ft.Colors.ON_SURFACE),
        }.get(poziom, ft.Colors.TRANSPARENT)

    ciemny = _czy_ciemny(page)
    mnoznik = 2.0 if ciemny else 1.0

    if poziom == 1:   # Delikatne tło (karty w jasnym motywie — cień robi "unoszenie")
        return ft.Colors.with_opacity(0.03 * mnoznik, ft.Colors.ON_SURFACE)
    elif poziom == 2: # Średnie tło (pola formularza, karty w ciemnym motywie)
        return ft.Colors.with_opacity(0.08 * mnoznik, ft.Colors.ON_SURFACE)
    elif poziom == 3: # Najsilniejsze tło — dostępne do mocniejszych akcentów
        return ft.Colors.with_opacity(0.15 * mnoznik, ft.Colors.ON_SURFACE)
    return ft.Colors.TRANSPARENT


def cien_karty(page: ft.Page = None, poziom="md"):
    """Miękki, 'unoszący' cień w duchu Material 3 — WYŁĄCZNIE w trybie jasnym.
    W trybie ciemnym cień jest ledwo czytelny na ciemnym tle i tylko brudzi
    interfejs, dlatego zwracamy None — tam różnicujemy powierzchnie wyłącznie
    jaśniejszym `bgcolor` (patrz `powierzchnia_karty` niżej). Każdy poziom to
    dwie warstwy (blisko + rozlana), jak w prawdziwych cieniach Material 3."""
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


def powierzchnia_karty(page: ft.Page = None, cien="md"):
    """Gotowy zestaw {bgcolor, shadow} do rozpakowania (**) w Containerze
    karty/formularza. Jasny motyw: niemal przezroczyste tło + miękki cień
    (cień 'unosi' kartę). Ciemny motyw: cień wyłączony, więc tło podbijamy
    o jeden poziom mocniej (poziom=2), żeby granica karty była widoczna
    bez cienia. Wariant OLED: tło zostaje minimalne, a rolę krawędzi przejmuje
    cienka ramka (patrz obramowanie_karty)."""
    if czy_czysta_czern(page):
        return {"bgcolor": tlo_karty(page, poziom=1), "shadow": None,
                "border": obramowanie_karty(page)}
    if _czy_ciemny(page):
        return {"bgcolor": tlo_karty(page, poziom=2), "shadow": None, "border": None}
    return {"bgcolor": tlo_karty(page, poziom=1), "shadow": cien_karty(page, cien), "border": None}


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


# Ile miejsca zostawić POD treścią na pasek przewijania. Suwak Fleta rysuje się
# przy dolnej krawędzi przewijanego obszaru, więc bez tej rezerwy leży na
# kafelkach — a bez suwaka w ogóle nie widać, że pasek da się przesunąć, i myszą
# nie ma czego złapać (Flutter nie pozwala przeciągać zawartości kursorem).
MIEJSCE_NA_SUWAK = 16


def pasek_przewijany(kontrolki, spacing=10, miejsce_na_suwak=MIEJSCE_NA_SUWAK,
                     wyrownanie=ft.CrossAxisAlignment.CENTER):
    """Poziomy pasek z widocznym, chwytalnym suwakiem, który NIE nachodzi na treść.

    Wzorzec przeniesiony z ekranu porównania pojazdów, gdzie sprawdził się przy
    szerokich tabelach: treść siedzi w kontenerze z dolnym paddingiem WEWNĄTRZ
    przewijanego wiersza, więc suwak ląduje w tym marginesie, a nie na kaflach.

    Używać tylko tam, gdzie zawartość naprawdę musi jechać w bok (karuzela
    kokpitu, mapa cieplna). Paski filtrów i chipów lepiej ZAWIJAĆ — wtedy nie ma
    czego przewijać i nic nie ginie za krawędzią."""
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
    """Pasek filtrów / chipów, który zamiast jechać w bok ZAWIJA się do drugiej
    linijki. Filtry są małe i jest ich kilka — schowanie części z nich za
    niewidoczną krawędzią było jedynym powodem, dla którego ten pasek w ogóle
    musiał się przewijać."""
    if not kontrolki:
        return ft.Container()
    return ft.Row(kontrolki, spacing=spacing, run_spacing=run_spacing, wrap=True,
                  vertical_alignment=ft.CrossAxisAlignment.CENTER)


__all__ = [
    "MIEJSCE_NA_SUWAK",
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
    "powierzchnia_karty",
    "tlo_karty",
    "zastosuj_motywy",
    "zbuduj_motyw_ciemny",
]
