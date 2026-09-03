import flet as ft
import flet_charts as fc
from datetime import datetime, date, timedelta, timezone
import re
import colorsys
import db
import os
import asyncio
import urllib.parse
import inspect
from state import MIESIACE_NAZWY
from date import parsuj_date
import sync

FILTR_CALKOWITY = None
FILTR_DZIESIETNY = None

MAPA_KOLOROW = {
    "Indygo": ft.Colors.INDIGO,
    "Czerwony": ft.Colors.RED,
    "Zielony": ft.Colors.GREEN,
    "Niebieski": ft.Colors.BLUE,
    "Szary": ft.Colors.GREY_500,
    "Pomarańczowy": ft.Colors.ORANGE,
    "Fioletowy": ft.Colors.PURPLE,
    "Różowy": ft.Colors.PINK_200,
    "Żółty": ft.Colors.YELLOW,
    "Limonkowy": ft.Colors.LIME,
}

def formatuj_liczba(wartosc, decimale=2):
    try:
        wartosc = float(wartosc)
    except (TypeError, ValueError):
        wartosc = 0.0
    if decimale > 0:
        tekst = f"{wartosc:,.{decimale}f}"
        czesc_calk, _, czesc_dziesiet = tekst.partition(".")
        return f"{czesc_calk.replace(',', ' ')},{czesc_dziesiet}"
    else:
        return f"{int(round(wartosc)):,}".replace(",", " ")

# ============== DESIGN TOKENS ==============
RADIUS = {"xs": 8, "sm": 10, "md": 12, "lg": 20, "xl": 28, "pill": 999}
SPACING = {"xs": 4, "sm": 8, "md": 16, "lg": 20, "xl": 32}
FS = {
    "caption": 11, "label": 12, "body": 13, "body_strong": 14,
    "title": 16, "heading": 18, "display": 22,
}
KOLOR_STATUS = {
    "critical": ft.Colors.RED_700,
    "warning": ft.Colors.ORANGE_700,
    "ok": ft.Colors.GREEN_700,
    "neutral": ft.Colors.ON_SURFACE_VARIANT,
}

# ============== JEDNA RODZINA IKON (Material) ==============
# W interfejsie nie używamy emoji — wyłącznie ft.Icons, żeby oznaczenia miały
# jeden ciężar, jedną grubość kreski i podążały za kolorem motywu (emoji zawsze
# zostaje w swojej palecie i w trybie ciemnym „krzyczy”). Warstwa danych (db.py)
# nie zna Fleta, więc zwraca KLUCZE, a poniższe mapy tłumaczą je na ikony.

IKONY_KOKPITU = {
    "koszt_miesiac": ft.Icons.ACCOUNT_BALANCE_WALLET,
    "termin": ft.Icons.EVENT,
    "wykres": ft.Icons.BAR_CHART,
    "koszt_km": ft.Icons.ADD_ROAD,
    "spalanie": ft.Icons.LOCAL_GAS_STATION,
    "przebieg_dzienny": ft.Icons.TIMELAPSE,
    "ostatnia_aktywnosc": ft.Icons.HISTORY,
    "kondycja": ft.Icons.MONITOR_HEART,
    "zasieg_ev": ft.Icons.BATTERY_CHARGING_FULL,
}

IKONY_AKTYWNOSCI = {
    "tankowanie": ft.Icons.LOCAL_GAS_STATION,
    "ladowanie": ft.Icons.EV_STATION,
    "serwis": ft.Icons.BUILD,
    "wizyta": ft.Icons.HOME_REPAIR_SERVICE,
    "inny_koszt": ft.Icons.RECEIPT_LONG,
}

IKONY_EKSPORTU = {
    "tankowania": ft.Icons.LOCAL_GAS_STATION,
    "historia": ft.Icons.BUILD,
    "zadania": ft.Icons.HANDYMAN,
    "wizyty": ft.Icons.HOME_REPAIR_SERVICE,
    "inne_koszty": ft.Icons.RECEIPT_LONG,
    "wydatki_cykliczne": ft.Icons.AUTORENEW,
    "magazyn_czesci": ft.Icons.INVENTORY_2,
    "zestawy_opon": ft.Icons.TIRE_REPAIR,
    "do_zrobienia": ft.Icons.CHECKLIST,
    "warsztaty": ft.Icons.BUSINESS,
    "odczyty_przebiegu": ft.Icons.STRAIGHTEN,
    "tagi": ft.Icons.LABEL,
}

# Trzy „wiadra” kosztów — ten sam zestaw ikon na wykresach, w podziale kosztów
# i w porównaniu pojazdów, żeby paliwo zawsze wyglądało tak samo.
IKONY_KATEGORII_KOSZTOW = {
    "paliwo": ft.Icons.LOCAL_GAS_STATION,
    "serwis": ft.Icons.BUILD,
    "inne": ft.Icons.RECEIPT_LONG,
}

def ikona_z_mapy(mapa, klucz, domyslna=ft.Icons.CIRCLE_OUTLINED):
    """Bezpieczne wyszukanie ikony po kluczu z warstwy danych."""
    return mapa.get(str(klucz or ""), domyslna)


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


def zastosuj_motywy(page: ft.Page, nazwa_koloru):
    """Jedno miejsce ustawiające page.theme i page.dark_theme — wcześniej ta sama
    para przypisań powtarzała się w main.py (start, import bazy, zmiana pojazdu)
    i w Ustawieniach, przez co wariant OLED trzeba by dokładać w czterech
    miejscach. Zwraca użyte ziarno koloru."""
    kolor_seed = MAPA_KOLOROW.get(nazwa_koloru, ft.Colors.INDIGO)
    page.theme = ft.Theme(color_scheme_seed=kolor_seed)
    page.dark_theme = zbuduj_motyw_ciemny(kolor_seed)
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

def parsuj_int(wartosc, domyslna=0):
    if wartosc is None: return domyslna
    tekst = str(wartosc).strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    if not tekst: return domyslna
    try:
        return int(round(float(tekst)))
    except (ValueError, TypeError):
        dopasowanie = re.search(r"-?\d+", tekst)
        return int(dopasowanie.group()) if dopasowanie else domyslna

def parsuj_float(wartosc, domyslna=0.0):
    if wartosc is None: return domyslna
    tekst = str(wartosc).strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    if not tekst: return domyslna
    try:
        return float(tekst)
    except (ValueError, TypeError):
        dopasowanie = re.search(r"-?\d+(\.\d+)?", tekst)
        return float(dopasowanie.group()) if dopasowanie else domyslna

def pokaz_komunikat(page: ft.Page, wiadomosc, kolor=ft.Colors.GREEN_700):
    snack = ft.SnackBar(ft.Text(str(wiadomosc)), bgcolor=kolor)
    if hasattr(page, "open"):
        page.open(snack)
    else:
        page.overlay.append(snack)
        snack.open = True
        page.update()

def pokaz_komunikat_cofnij(page: ft.Page, wiadomosc, wynik_usuwania, sekundy=5):
    """wynik_usuwania to słownik zwrócony przez db.usun_z_cofnieciem()."""
    if not wynik_usuwania:
        return pokaz_komunikat(page, wiadomosc, ft.Colors.RED_700)

    def po_cofnieciu(e):
        wynik_usuwania["cofnij"]()
        przejdz(page, page.route)

    snack = ft.SnackBar(
        content=ft.Text(str(wiadomosc)),
        action="Cofnij",
        on_action=po_cofnieciu,
        duration=sekundy * 1000,
    )
    if hasattr(page, "open"):
        page.open(snack)
    else:
        page.overlay.append(snack)
        snack.open = True
        page.update()

    async def _finalizuj_po_czasie():
        await asyncio.sleep(sekundy + 0.5)
        wynik_usuwania["finalizuj"]()

    page.run_task(_finalizuj_po_czasie)

def z_opoznieniem(page: ft.Page, funkcja, opoznienie=0.25):
    """Owija handler on_change pola wyszukiwania tak, by faktyczne wywołanie
    funkcja(e) nastąpiło dopiero po 'opoznienie' sekundach ciszy od ostatniego
    wciśnięcia klawisza — zapobiega przeliczaniu filtra (albo, w /szukaj,
    zapytania do bazy) przy KAŻDYM pojedynczym znaku, gdy lista ma setki wpisów.
    Użycie: on_change=utils.z_opoznieniem(self._page, moja_funkcja_filtrujaca)"""
    stan = {"licznik": 0}

    def on_change(e):
        stan["licznik"] += 1
        numer_wywolania = stan["licznik"]

        async def _po_ciszy():
            await asyncio.sleep(opoznienie)
            if stan["licznik"] == numer_wywolania:
                funkcja(e)

        page.run_task(_po_ciszy)

    return on_change

def otworz_dialog(page: ft.Page, kontrolka):
    if hasattr(page, "open"): page.open(kontrolka)
    elif hasattr(page, "show_dialog"): page.show_dialog(kontrolka)
    else:
        page.overlay.append(kontrolka)
        kontrolka.open = True
        page.update()

def zamknij_dialog(page: ft.Page, kontrolka):
    if hasattr(page, "close"): page.close(kontrolka)
    elif hasattr(page, "pop_dialog"): page.pop_dialog()
    else:
        kontrolka.open = False
        if kontrolka in page.overlay: page.overlay.remove(kontrolka)
        page.update()

def pokaz_ladowanie(page: ft.Page, tekst="Wczytywanie..."):
    """Blokujący, niezamykalny dialog ze spinnerem — używać w parze z
    ukryj_ladowanie() wokół operacji trwających dłużej niż mgnienie oka
    (np. synchronizacja z chmurą), żeby ekran nie wyglądał na zawieszony."""
    dlg = ft.AlertDialog(
        modal=True,
        content_padding=ft.Padding(25, 20, 25, 20),
        content=ft.Row([
            ft.ProgressRing(width=20, height=20, stroke_width=3, color=ft.Colors.PRIMARY),
            ft.Text(tekst, size=14),
        ], spacing=15, tight=True),
    )
    otworz_dialog(page, dlg)
    return dlg

def ukryj_ladowanie(page: ft.Page, dlg):
    if dlg is not None:
        zamknij_dialog(page, dlg)

def _moment_ostatniej_synchronizacji():
    zapis = db.pobierz_ustawienie("ostatnia_synchronizacja")
    if not zapis:
        return None
    try:
        return datetime.strptime(zapis, "%d.%m.%Y %H:%M")
    except ValueError:
        return None

def tekst_ostatniej_synchronizacji(krotki=True):
    """Względny opis czasu ostatniej udanej synchronizacji (zapisywanej lokalnie
    przez sync.synchronizuj_wszystko).

    Domyślnie forma KRÓTKA — sam czas, bez słowa „Zsynchronizowano” (przycisk
    tuż nad etykietą i tak mówi, o co chodzi) i bez dopisku o kolejce offline.
    Ten dopisek potrafił urosnąć do „Zsynchronizowano 15.08.2026 14:32 • 3
    pojazdy czekają na wysłanie zmian” i rozpychał wiersz nagłówka, w którym
    obok stoją inne przyciski; zaległości pokazuje teraz kropka na przycisku
    (patrz przycisk_synchronizacji). Forma pełna została do tooltipów.
    """
    moment = _moment_ostatniej_synchronizacji()
    if not moment:
        return "Nigdy" if krotki else "Nigdy nie synchronizowano"

    sekundy = max(0, (datetime.now() - moment).total_seconds())
    dzis = datetime.now().date()

    if sekundy < 60:
        czas = "przed chwilą"
    elif sekundy < 3600:
        czas = f"{int(sekundy // 60)} min temu"
    elif moment.date() == dzis:
        czas = f"{int(sekundy // 3600)} godz. temu"
    elif moment.date() == (dzis - timedelta(days=1)):
        czas = f"wczoraj {moment.strftime('%H:%M')}"
    elif moment.year == dzis.year:
        czas = moment.strftime("%d.%m")
    else:
        czas = moment.strftime("%d.%m.%y")

    if krotki:
        return czas

    pelny = f"Zsynchronizowano {czas}"
    zalegle = db.opis_oczekujacej_synchronizacji()
    return f"{pelny} • {zalegle}" if zalegle else pelny

def wypchnij_w_tle(page: ft.Page, auto_id, powod="zapis"):
    """Zastępuje dawne `try: ... except Exception: pass` przy auto-synchronizacji
    po zapisie. Różnica: nieudana próba (brak sieci) nie znika — ląduje w kolejce
    kolejka_sync i zostanie ponowiona przy następnym zapisie albo starcie aplikacji.
    Dla pojazdu niewspółdzielonego nie robi nic."""
    if not auto_id:
        return
    try:
        wspolny_id, _ = sync.czy_udostepniony(auto_id)
    except Exception:
        return
    if not wspolny_id:
        return

    async def _zadanie():
        await asyncio.to_thread(sync.synchronizuj_w_tle, auto_id, powod)
        await asyncio.to_thread(sync.przetworz_kolejke_sync)

    page.run_task(_zadanie)

def podsumowanie_konfliktow(konflikty, maks_nazw=2):
    """Jednozdaniowe streszczenie konfliktów do snackbara — z nazwami pierwszych
    rekordów zamiast samej liczby."""
    if not konflikty:
        return ""
    nazwy = [k["opis"] for k in konflikty[:maks_nazw]]
    reszta = len(konflikty) - len(nazwy)
    tekst = ", ".join(nazwy)
    if reszta > 0:
        tekst += f" i {reszta} inn." if reszta > 1 else " i 1 inny"
    return f"Edycja z dwóch urządzeń — nadpisano: {tekst}. Zachowano wersję z tego telefonu."

def pokaz_dialog_konfliktow(page: ft.Page, konflikty):
    """Pełna lista nadpisanych rekordów z ostatniej synchronizacji."""
    if not konflikty:
        return
    wiersze = [
        ft.Row([
            ft.Icon(ft.Icons.MERGE_TYPE, size=16, color=ft.Colors.AMBER_700),
            ft.Text(k["opis"], size=13, expand=True),
        ], spacing=8)
        for k in konflikty
    ]
    dlg = ft.AlertDialog(
        title=ft.Row([
            ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=ft.Colors.AMBER_700),
            ft.Text("Edycja z dwóch urządzeń", weight="bold", expand=True),
        ], spacing=8),
        content=ft.Column(
            [ft.Text(
                "Te rekordy zmieniły się równolegle na innym urządzeniu. Zachowano wersję "
                "z tego telefonu — sprawdź, czy nie trzeba czegoś poprawić ręcznie.",
                size=12, color=ft.Colors.ON_SURFACE_VARIANT
            ), ft.Divider(height=10)] + wiersze,
            tight=True, spacing=6, scroll=ft.ScrollMode.AUTO
        ),
        actions=[ft.TextButton("Rozumiem", on_click=lambda e: zamknij_dialog(page, dlg))]
    )
    otworz_dialog(page, dlg)

def funkcja_szybkiej_synchronizacji(page: ft.Page, auto_id, trasa_powrotu):
    """Zwraca gotowy async callback do użycia z przycisk_synchronizacji() —
    synchronizuje dany pojazd i odświeża podaną trasę. Skraca boilerplate
    powtarzany w wielu widokach (pierwowzór: MainView._synchronizuj_teraz)."""
    async def _synchronizuj():
        try:
            wyslano, pobrano = await asyncio.to_thread(sync.synchronizuj_wszystko, auto_id)
            await asyncio.to_thread(sync.przetworz_kolejke_sync)
            przejdz(page, trasa_powrotu)
            konflikty = sync.pobierz_konflikty_ostatniej_synchronizacji()
            if konflikty:
                pokaz_komunikat(page, podsumowanie_konfliktow(konflikty), ft.Colors.AMBER_700)
                pokaz_dialog_konfliktow(page, konflikty)
            else:
                pokaz_komunikat(page, f"Wysłano {wyslano}, pobrano {pobrano} nowych rekordów.")
        except Exception as ex:
            db.zakolejkuj_synchronizacje(auto_id, "reczna", str(ex))
            pokaz_komunikat(
                page,
                f"Błąd synchronizacji: {ex}. Zmiany zostały zakolejkowane i spróbujemy ponownie automatycznie.",
                ft.Colors.RED_700
            )
    return _synchronizuj

def przycisk_synchronizacji(page: ft.Page, funkcja_sync, tekst="Synchronizuj", pokaz_czas=True):
    """Spójny, dobrze widoczny przycisk szybkiej synchronizacji z chmurą — do użycia
    w nagłówkach zakładek przy współdzielonych pojazdach. Zawsze pokazuje pełnoekranowy
    dialog ładowania na czas operacji (patrz pokaz_ladowanie), w przeciwieństwie do
    poprzednich, ledwo widocznych samych ikonek.
    funkcja_sync: async callback bez argumentów wykonujący faktyczną synchronizację
    (zwykle cienki wrapper na sync.synchronizuj_wszystko, patrz też
    funkcja_szybkiej_synchronizacji) — sam odpowiada za komunikaty o sukcesie/błędzie.
    pokaz_czas: dokleja pod przyciskiem małą etykietę 'Zsynchronizowano X temu'."""
    # Szerokość CAŁEGO bloku jest z góry ograniczona: przycisk z podpisem stoi
    # w tym samym wierszu co tytuł sekcji i inne akcje, więc rozciągliwy tekst
    # potrafił zepchnąć sąsiadów poza ekran.
    SZEROKOSC = 132

    def _opis_tooltipa():
        # Forma pełna sama dokleja informację o kolejce offline, jeśli coś w niej
        # jest — to tutaj, a nie pod przyciskiem, jest na nią miejsce.
        return f"Synchronizuj z partnerem\n{tekst_ostatniej_synchronizacji(krotki=False)}"

    etykieta_czasu = ft.Text(
        tekst_ostatniej_synchronizacji(), size=10, color=ft.Colors.ON_SURFACE_VARIANT,
        no_wrap=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
        text_align=ft.TextAlign.CENTER,
    )
    # Kropka zamiast zdania „3 pojazdy czekają na wysłanie zmian” — ta sama
    # informacja, zero wpływu na szerokość. Szczegóły siedzą w tooltipie.
    kropka_zalegle = ft.Container(
        width=7, height=7, border_radius=RADIUS["pill"], bgcolor=ft.Colors.ORANGE_700,
        visible=bool(db.opis_oczekujacej_synchronizacji()),
    )

    def _odswiez_opisy():
        etykieta_czasu.value = tekst_ostatniej_synchronizacji()
        kropka_zalegle.visible = bool(db.opis_oczekujacej_synchronizacji())
        przycisk.tooltip = _opis_tooltipa()

    def _klik(e):
        async def _zrob():
            dlg = pokaz_ladowanie(page, "Synchronizowanie danych...")
            try:
                await funkcja_sync()
            finally:
                ukryj_ladowanie(page, dlg)
                _odswiez_opisy()
                try:
                    page.update()
                except Exception:
                    pass
        page.run_task(_zrob)

    przycisk = ft.Container(
        height=36,
        padding=ft.Padding(12, 0, 12, 0),
        border_radius=RADIUS["pill"],
        bgcolor=ft.Colors.with_opacity(0.14, ft.Colors.PRIMARY),
        ink=True,
        alignment=ft.Alignment.CENTER,
        tooltip=_opis_tooltipa(),
        on_click=_klik,
        content=ft.Row([
            ft.Icon(ft.Icons.SYNC, size=16, color=ft.Colors.PRIMARY),
            ft.Text(tekst, size=12, weight="bold", color=ft.Colors.PRIMARY, no_wrap=True),
            kropka_zalegle,
        ], spacing=6, tight=True)
    )

    if not pokaz_czas:
        return przycisk

    return ft.Container(
        width=SZEROKOSC,
        content=ft.Column(
            [przycisk, etykieta_czasu],
            spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True
        ),
    )

def otworz_dno(page: ft.Page, bottom_sheet):
    """Automatycznie zabezpiecza dolne menu przed zasłonięciem przez przyciski systemowe telefonu."""
    if hasattr(bottom_sheet, "content") and bottom_sheet.content:
        kontener = bottom_sheet.content
        if isinstance(kontener, ft.Container):
            # Jeśli w kontenerze jest kolumna elementów, włączamy scroll i doklejamy margines
            if isinstance(kontener.content, ft.Column):
                kontener.content.scroll = ft.ScrollMode.AUTO
                if not any(isinstance(c, ft.SafeArea) for c in kontener.content.controls):
                    kontener.content.controls.append(dol_bezpieczny(20))
            elif not isinstance(kontener.content, ft.SafeArea):
                kontener.content = ft.SafeArea(
                    content=kontener.content,
                    avoid_intrusions_top=False
                )
        elif not isinstance(bottom_sheet.content, ft.SafeArea):
            bottom_sheet.content = ft.SafeArea(
                content=bottom_sheet.content,
                avoid_intrusions_top=False
            )
            
    otworz_dialog(page, bottom_sheet)

def zamknij_dno(page: ft.Page, bottom_sheet):
    zamknij_dialog(page, bottom_sheet)

def pokaz_menu_kontekstowe(page: ft.Page, tytul: str, pozycje: list):
    """
    Tworzy i wyświetla ujednolicone menu kontekstowe (BottomSheet).
    Automatycznie zamyka menu przed wykonaniem podpiętej akcji (wspiera sync i async).
    """
    bs = ft.BottomSheet(ft.Container(padding=20, bgcolor=ft.Colors.SURFACE))

    def opakuj_akcje(akcja_docelowa):
        async def wrapper(e):
            zamknij_dno(page, bs)
            if akcja_docelowa:
                res = akcja_docelowa()
                # Używamy asyncio zamiast inspect
                import asyncio
                if asyncio.iscoroutine(res):
                    await res
        return wrapper

    elementy_menu = [
        ft.Text(tytul, weight="bold", size=18, color=ft.Colors.PRIMARY),
        ft.Divider()
    ]

    for poz in pozycje:
        ikona = poz.get("ikona")
        tekst = poz.get("tekst")
        akcja = poz.get("akcja")
        kolor = poz.get("kolor")
        
        elementy_menu.append(
            ft.ListTile(
                leading=ft.Icon(ikona, color=kolor) if ikona else None,
                title=ft.Text(tekst, color=kolor),
                on_click=opakuj_akcje(akcja)
            )
        )

    bs.content.content = ft.Column(elementy_menu, tight=True)
    otworz_dno(page, bs)

def pokaz_menu_grupowane(page: ft.Page, tytul: str, grupy: list, podtytul: str = None):
    """Menu z pozycjami POGRUPOWANYMI w rozwijane sekcje (BottomSheet).

    Płaskie menu z kilkunastoma pozycjami zmusza do czytania wszystkiego, żeby
    znaleźć jedną rzecz — a przy okazji stawia obok siebie sąsiadów, którzy nic
    wspólnego nie mają (kalkulator trasy i dziennik pojazdu). Tu widać kilka
    nagłówków; szczegóły pokazują się dopiero po rozwinięciu sekcji.

    grupy: lista słowników
        {"tytul": str, "ikona": ikona Material, "otwarta": bool,
         "pozycje": [{"ikona", "tekst", "opis", "akcja", "kolor", "odznaka"}]}
    Grupa bez pozycji jest pomijana, więc wołający może budować listę warunkowo
    (np. sekcja współdzielenia tylko dla pojazdu udostępnionego).
    """
    bs = ft.BottomSheet(ft.Container(padding=ft.Padding(16, 16, 16, 8), bgcolor=ft.Colors.SURFACE))

    def opakuj_akcje(akcja_docelowa):
        async def wrapper(e):
            zamknij_dno(page, bs)
            if akcja_docelowa:
                wynik = akcja_docelowa()
                import asyncio
                if asyncio.iscoroutine(wynik):
                    await wynik
        return wrapper

    def zbuduj_pozycje(poz):
        kolor = poz.get("kolor") or ft.Colors.ON_SURFACE
        opis = poz.get("opis")
        odznaka = poz.get("odznaka")

        tytul_wiersza = [ft.Text(poz.get("tekst", ""), size=FS["body"], color=kolor, weight="w500")]
        if odznaka:
            tytul_wiersza.append(ft.Container(
                padding=ft.Padding(7, 1, 7, 1),
                border_radius=RADIUS["pill"],
                bgcolor=ft.Colors.with_opacity(0.18, ft.Colors.ORANGE_700),
                content=ft.Text(str(odznaka), size=10, weight="bold", color=ft.Colors.ORANGE_800),
            ))

        tresc = [ft.Row(tytul_wiersza, spacing=6, tight=True)]
        if opis:
            tresc.append(ft.Text(opis, size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT))

        return ft.Container(
            padding=ft.Padding(10, 10, 10, 10),
            border_radius=RADIUS["sm"],
            ink=True,
            on_click=opakuj_akcje(poz.get("akcja")),
            content=ft.Row([
                ft.Icon(poz.get("ikona"), size=20, color=poz.get("kolor") or ft.Colors.PRIMARY),
                ft.Column(tresc, spacing=1, tight=True, expand=True),
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )

    sekcje = []
    for grupa in grupy:
        pozycje = [p for p in (grupa.get("pozycje") or []) if p]
        if not pozycje:
            continue

        cialo = ft.Container(
            padding=ft.Padding(0, 0, 0, 6),
            visible=bool(grupa.get("otwarta")),
            content=ft.Column([zbuduj_pozycje(p) for p in pozycje], spacing=2, tight=True),
        )
        strzalka = ft.Icon(
            ft.Icons.KEYBOARD_ARROW_UP if cialo.visible else ft.Icons.KEYBOARD_ARROW_DOWN,
            size=20, color=ft.Colors.ON_SURFACE_VARIANT,
        )

        def przelacz(e, cialo=cialo, strzalka=strzalka):
            cialo.visible = not cialo.visible
            strzalka.name = ft.Icons.KEYBOARD_ARROW_UP if cialo.visible else ft.Icons.KEYBOARD_ARROW_DOWN
            try:
                page.update()
            except Exception:
                pass

        naglowek = ft.Container(
            padding=ft.Padding(10, 12, 10, 12),
            border_radius=RADIUS["sm"],
            ink=True,
            on_click=przelacz,
            content=ft.Row([
                ft.Icon(grupa.get("ikona"), size=20, color=ft.Colors.PRIMARY),
                ft.Text(grupa.get("tytul", ""), size=FS["body"], weight="bold", expand=True),
                ft.Text(str(len(pozycje)), size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT),
                strzalka,
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )
        sekcje.append(ft.Column([naglowek, cialo], spacing=0, tight=True))

    naglowek_menu = [ft.Text(tytul, weight="bold", size=18, color=ft.Colors.PRIMARY)]
    if podtytul:
        naglowek_menu.append(ft.Text(podtytul, size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT))

    bs.content.content = ft.Column(
        [ft.Column(naglowek_menu, spacing=0, tight=True), ft.Divider(height=12)] + sekcje,
        tight=True, spacing=0,
    )
    otworz_dno(page, bs)

def potwierdz(page: ft.Page, tytul, tresc, po_potwierdzeniu, tekst_potwierdzenia="Usuń"):
    dlg = ft.AlertDialog(
        modal=True, title=ft.Text(tytul, weight="bold"), content=ft.Text(tresc),
        shape=ft.RoundedRectangleBorder(radius=RADIUS["lg"]),
    )
    def anuluj(e):
        zamknij_dialog(page, dlg)
    def zatwierdz(e):
        zamknij_dialog(page, dlg)
        po_potwierdzeniu()
    
    dlg.actions = [
        ft.TextButton("Anuluj", on_click=anuluj),
        ft.TextButton(tekst_potwierdzenia, style=ft.ButtonStyle(color=ft.Colors.RED_700), on_click=zatwierdz),
    ]
    dlg.actions_alignment = ft.MainAxisAlignment.END
    otworz_dialog(page, dlg)

def przejdz(page: ft.Page, trasa: str):
    page.route = trasa
    page.on_route_change(None)

def pole_daty(page: ft.Page, label, wartosc_poczatkowa=None):
    pole = ft.TextField(
        label=label, 
        value=str(wartosc_poczatkowa) if wartosc_poczatkowa else "",
        read_only=True, 
        hint_text="Wybierz datę",
        **styl_pola()
    )

    def otworz(e):
        try:
            data_pocz = datetime.strptime(pole.value, "%d.%m.%Y") if pole.value else datetime.now()
        except Exception:
            data_pocz = datetime.now()

        def po_wyborze(e2):
            if e2.control.value:
                val = e2.control.value

                # 1. Obsługa formatu tekstowego ISO
                if isinstance(val, str):
                    try:
                        val = datetime.fromisoformat(val.replace("Z", "+00:00"))
                    except Exception:
                        pass

                # 2. Przeliczenie ze strefy UTC na lokalną
                if isinstance(val, datetime):
                    if val.tzinfo is not None:
                        val = val.astimezone()
                    elif val.hour != 0:
                        val = val.replace(tzinfo=timezone.utc).astimezone()
                    
                    pole.value = val.strftime("%d.%m.%Y")
                elif isinstance(val, date):
                    pole.value = val.strftime("%d.%m.%Y")
                else:
                    pole.value = str(val)

                pole.error_text = None
                page.update()

        picker = ft.DatePicker(
            value=data_pocz, 
            first_date=datetime(1990, 1, 1), 
            last_date=datetime(2100, 12, 31),
            on_change=po_wyborze, 
            cancel_text="Anuluj", 
            confirm_text="Wybierz", 
            help_text=label
        )
        otworz_dialog(page, picker)

    pole.suffix = ft.IconButton(
        icon=ft.Icons.CALENDAR_MONTH, 
        tooltip="Wybierz datę", 
        on_click=otworz, 
        icon_size=20
    )
    return pole

def pokaz_bledy_formularza(page: ft.Page, bledy):
    for kontrolka, komunikat in bledy:
        kontrolka.error_text = komunikat
    page.update()
    pokaz_komunikat(page, "Popraw zaznaczone pola formularza.", ft.Colors.RED_700)

def sprawdz_podejrzany_przebieg(page: ft.Page, pole_przebiegu: ft.TextField, auto_id, nowy_przebieg, wyklucz_id=None, tabela=None, nowa_data_str=None):
    """
    Wspólna logika 'niski przebieg — potwierdź ponownie' używana przy zapisie
    tankowań i wpisów historii. Pamięta DOKŁADNĄ wartość, która została już
    potwierdzona (nie tylko fakt, że jakieś ostrzeżenie się kiedyś pojawiło),
    więc zmiana na INNĄ podejrzaną wartość ponownie wymusi potwierdzenie.

    Zwraca True, jeśli zapis należy przerwać (pokazano świeże ostrzeżenie).
    Zwraca False, jeśli można kontynuować zapis.
    """
    ostrzezenie = db.sprawdz_czy_przebieg_podejrzany(auto_id, nowy_przebieg, wyklucz_id=wyklucz_id, tabela=tabela, nowa_data_str=nowa_data_str)

    if ostrzezenie and getattr(pole_przebiegu, "_potwierdzona_wartosc", None) != nowy_przebieg:
        pole_przebiegu._potwierdzona_wartosc = nowy_przebieg
        pole_przebiegu.error_text = "Niski przebieg — kliknij Zapisz ponownie, aby potwierdzić"
        page.update()
        pokaz_komunikat(page, ostrzezenie, ft.Colors.ORANGE_700)
        return True

    pole_przebiegu._potwierdzona_wartosc = None
    return False

def sprawdz_duplikat_tankowania(page: ft.Page, pole_kwoty: ft.TextField, auto_id, data_str, przebieg, kwota, wyklucz_id=None):
    """Analogicznie do sprawdz_podejrzany_przebieg — ostrzega, jeśli identyczne
    tankowanie (data+przebieg+kwota) już istnieje, zamiast cicho zapisać
    potencjalny duplikat. Zwraca True, jeśli zapis należy przerwać."""
    klucz = (data_str, przebieg, kwota)
    ostrzezenie = db.sprawdz_czy_tankowanie_duplikat(auto_id, data_str, przebieg, kwota, wyklucz_id=wyklucz_id)

    if ostrzezenie and getattr(pole_kwoty, "_duplikat_potwierdzony", None) != klucz:
        pole_kwoty._duplikat_potwierdzony = klucz
        pole_kwoty.error_text = "Możliwy duplikat — kliknij Zapisz ponownie, aby potwierdzić"
        page.update()
        pokaz_komunikat(page, ostrzezenie, ft.Colors.ORANGE_700)
        return True

    pole_kwoty._duplikat_potwierdzony = None
    return False

def sprawdz_duplikat_kosztu(page: ft.Page, pole_kwoty: ft.TextField, auto_id, data_str, nazwa, kwota, wyklucz_id=None):
    """Analogicznie do sprawdz_duplikat_tankowania — ostrzega, jeśli identyczny
    koszt (data+nazwa+kwota) już istnieje, zamiast cicho zapisać potencjalny
    duplikat. Zwraca True, jeśli zapis należy przerwać."""
    klucz = (data_str, nazwa, kwota)
    ostrzezenie = db.sprawdz_czy_koszt_duplikat(auto_id, data_str, nazwa, kwota, wyklucz_id=wyklucz_id)

    if ostrzezenie and getattr(pole_kwoty, "_duplikat_potwierdzony", None) != klucz:
        pole_kwoty._duplikat_potwierdzony = klucz
        pole_kwoty.error_text = "Możliwy duplikat — kliknij Zapisz ponownie, aby potwierdzić"
        page.update()
        pokaz_komunikat(page, ostrzezenie, ft.Colors.ORANGE_700)
        return True

    pole_kwoty._duplikat_potwierdzony = None
    return False

def przycisk_sortowania(page: ft.Page, state, klucz_stanu, opcje):
    pole_akt, malejaco_akt = state.sort.setdefault(klucz_stanu, (opcje[0][1], False))
    
    def zmien_pole(pole):
        _, mal = state.sort[klucz_stanu]
        state.sort[klucz_stanu] = (pole, mal)
        przejdz(page, page.route)
        
    def zmien_kierunek(e):
        pole, mal = state.sort[klucz_stanu]
        state.sort[klucz_stanu] = (pole, not mal)
        przejdz(page, page.route)

    etykieta_akt = next((et for et, p, _ in opcje if p == pole_akt), str(pole_akt))

    elementy_menu = []
    for etykieta, pole, _ in opcje:
        zaznaczone = (pole == pole_akt)
        elementy_menu.append(
            ft.PopupMenuItem(
                content=ft.Row([
                    ft.Icon(ft.Icons.CHECK, size=16, color=ft.Colors.PRIMARY, visible=zaznaczone),
                    ft.Text(etykieta, weight="bold" if zaznaczone else "normal")
                ]),
                on_click=lambda e, p=pole: zmien_pole(p)
            )
        )

    popup = ft.PopupMenuButton(
        items=elementy_menu,
        content=ft.Row([
            ft.Icon(ft.Icons.SORT_ROUNDED, size=14, color=ft.Colors.PRIMARY),  # Mniejsza ikona
            ft.Text(etykieta_akt, size=11, weight="bold", color=ft.Colors.PRIMARY),  # Mniejszy tekst
        ], spacing=2),
        tooltip="Wybierz pole sortowania"
    )

    return ft.Container(
        height=36,  # <-- SZTYWNA WYSOKOŚĆ
        bgcolor=ft.Colors.with_opacity(0.1, ft.Colors.PRIMARY),
        border_radius=18,
        padding=ft.Padding(12, 0, 12, 0),
        alignment=ft.Alignment.CENTER,
        content=ft.Row([
            popup,
            ft.Container(width=1, height=16, bgcolor=ft.Colors.with_opacity(0.2, ft.Colors.PRIMARY)),
            ft.IconButton(
                icon=ft.Icons.ARROW_DOWNWARD_ROUNDED if malejaco_akt else ft.Icons.ARROW_UPWARD_ROUNDED,
                icon_size=16,
                icon_color=ft.Colors.PRIMARY,
                tooltip="Zmień kierunek sortowania",
                on_click=zmien_kierunek,
                width=24,
                height=24,
                style=ft.ButtonStyle(padding=0)
            )
        ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    )

def posortuj_liste(lista, state, klucz_stanu, opcje):
    pole_akt, malejaco = state.sort.get(klucz_stanu, (opcje[0][1], False))
    for _, pole, fn in opcje:
        if pole == pole_akt:
            lista.sort(key=fn, reverse=malejaco)
            break
    return lista

def usun_auto(page: ft.Page, state):
    if not state.auto_id: return
    nazwa = state.auto_nazwa
    auto_id = state.auto_id

    def wykonaj():
        # Pojazd trafia do kosza — nic nie jest kasowane z dysku.
        wynik = db.usun_auto_do_kosza(auto_id)

        if wynik:
            oryg_cofnij = wynik["cofnij"]
            def nowe_cofnij():
                oryg_cofnij()
                # Przywrócenie mogło nadać pojazdowi nowe ID (gdyby stare zdążył
                # zająć inny wpis), więc bierzemy to, które faktycznie wróciło.
                nowe_id = wynik.get("przywrocone_id")
                if nowe_id:
                    state.auto_id = nowe_id
                    db.zainicjuj_domyslne_auto(state)
                przejdz(page, "/")
            wynik["cofnij"] = nowe_cofnij

        state.auto_id = None
        db.zainicjuj_domyslne_auto(state)
        przejdz(page, "/")
        pokaz_komunikat_cofnij(page, f"Pojazd „{nazwa}” przeniesiony do kosza.", wynik)

    dni = db.pobierz_dni_kosza()
    okres = f"przez {dni} dni" if dni else "bez limitu czasu"
    potwierdz(
        page, "Usunąć pojazd?",
        f"„{nazwa}” trafi do kosza wraz z całą historią serwisową i zdjęciami. "
        f"Będzie tam czekał {okres} — do tego czasu przywrócisz go jednym kliknięciem.",
        wykonaj,
        tekst_potwierdzenia="Przenieś do kosza",
    )

def _sygnatura_powiadomien(powiadomienia):
    return frozenset((p["typ"], p["tytul"], p["status"]) for p in powiadomienia)

def przycisk_dzwonka(page: ft.Page, state) -> ft.Control:
    powiadomienia = db.pobierz_powiadomienia(state.auto_id)
    liczba = len(powiadomienia)
    sygnatura = _sygnatura_powiadomien(powiadomienia)
    widziana = state.powiadomienia_widziane.get(state.auto_id)
    juz_widziane = liczba > 0 and sygnatura == widziana
    ma_przeterminowane = any(p["status"] == "przeterminowane" for p in powiadomienia)

    if liczba == 0 or juz_widziane:
        kolor_ikony = ft.Colors.ON_SURFACE
    elif ma_przeterminowane:
        kolor_ikony = ft.Colors.RED_700
    else:
        kolor_ikony = ft.Colors.ORANGE_700

    ikona = ft.IconButton(
        icon=ft.Icons.NOTIFICATIONS_ROUNDED if liczba else ft.Icons.NOTIFICATIONS_OUTLINED,
        icon_color=kolor_ikony,
        icon_size=20,
        tooltip=f"{liczba} powiadomień" if liczba else "Brak powiadomień",
        width=36, height=36,
        style=ft.ButtonStyle(padding=0),
    )

    if liczba == 0:
        ikona.on_click = lambda e: pokaz_panel_powiadomien(page, state)
        return ikona

    odznaka = ft.Container(
        content=ft.Text(str(liczba) if liczba < 10 else "9+", size=9, color=ft.Colors.WHITE, weight="bold"),
        width=14, height=14, border_radius=7, bgcolor=ft.Colors.RED_700,
        alignment=ft.Alignment.CENTER,
    )
    odznaka_pozycja = ft.Container(odznaka, right=0, top=0, visible=not juz_widziane)

    def po_kliknieciu(e):
        state.powiadomienia_widziane[state.auto_id] = sygnatura
        ikona.icon_color = ft.Colors.ON_SURFACE
        odznaka_pozycja.visible = False
        page.update()
        pokaz_panel_powiadomien(page, state)

    ikona.on_click = po_kliknieciu

    return ft.Stack([ikona, odznaka_pozycja], width=36, height=36)

def pokaz_panel_powiadomien(page: ft.Page, state):
    bs = ft.BottomSheet(ft.Container())

    def idz_do(trasa):
        def handler(e):
            zamknij_dno(page, bs)
            przejdz(page, trasa)
        return handler

    def zaplac_cykliczny(wydatek_id, czy_koszt=True, kafelek=None):
        def handler(e):
            db.oznacz_zaplacony_wydatek_cykliczny(wydatek_id, state.auto_id)
            komunikat = "Zapisano płatność i przesunięto termin." if czy_koszt else "Oznaczono jako wykonane i przesunięto termin."

            def dokoncz():
                pokaz_komunikat(page, komunikat)
                przejdz(page, page.route)  # odświeża dzwonek/badge w tle; panel zostaje otwarty
                odswiez()

            if kafelek is None:
                dokoncz()
                return

            # Przycisk zamienia się w ptaszka, który „wskakuje” na swoje miejsce,
            # i dopiero po tej chwili lista się przebudowuje — inaczej wiersz
            # znikał w tej samej klatce, w której użytkownik go dotknął.
            kafelek.trailing = znacznik_wykonania(
                page,
                "Zapłacone" if czy_koszt else "Wykonano",
                po_zakonczeniu=dokoncz,
            )
            try:
                page.update()
            except Exception:
                pass
        return handler

    def odloz(powiadomienie, dni):
        """Wycisza JEDNO powiadomienie na wybraną liczbę dni. Nie oznacza niczego
        jako wykonane i nie rusza terminu — po prostu znika z listy do czasu."""
        db.odloz_powiadomienie(state.auto_id, powiadomienie.get("klucz"), dni, powiadomienie.get("tytul"))
        pokaz_komunikat(page, f"Odłożono „{powiadomienie['tytul']}” na {dni} dni.")
        przejdz(page, page.route)   # odświeża licznik przy dzwonku w tle
        odswiez()

    def okno_wlasnej_liczby_dni(powiadomienie):
        e_dni = ft.TextField(label="Za ile dni przypomnieć?", value="14",
                             keyboard_type=ft.KeyboardType.NUMBER, **styl_pola())

        def zapisz(e):
            dni = parsuj_int(e_dni.value, 0)
            if dni < 1:
                e_dni.error_text = "Podaj liczbę dni (min. 1)"
                e_dni.update()
                return
            zamknij_dialog(page, dlg)
            odloz(powiadomienie, dni)

        dlg = ft.AlertDialog(
            title=ft.Text("Odłóż przypomnienie", weight="bold"),
            content=ft.Column([
                ft.Text(powiadomienie["tytul"], weight="bold"),
                ft.Text("Wróci na listę po tylu dniach. Termin i status pozostają bez zmian.",
                        size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                e_dni,
            ], tight=True, spacing=10),
            actions=[
                ft.TextButton("Anuluj", on_click=lambda e: zamknij_dialog(page, dlg)),
                ft.ElevatedButton("Odłóż", on_click=zapisz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY),
            ],
        )
        otworz_dialog(page, dlg)

    def przycisk_odlozenia(powiadomienie):
        if not powiadomienie.get("klucz"):
            return None
        pozycje_menu = [
            ft.PopupMenuItem(
                content=ft.Row([ft.Icon(ft.Icons.SNOOZE, size=16, color=ft.Colors.PRIMARY),
                                ft.Text(f"Za {d} dni")], spacing=6),
                on_click=lambda e, dni=d, p=powiadomienie: odloz(p, dni),
            )
            for d in db.DNI_ODLOZENIA_OPCJE
        ]
        pozycje_menu.append(ft.PopupMenuItem(
            content=ft.Row([ft.Icon(ft.Icons.EDIT_CALENDAR, size=16, color=ft.Colors.PRIMARY),
                            ft.Text("Własna liczba dni")], spacing=6),
            on_click=lambda e, p=powiadomienie: okno_wlasnej_liczby_dni(p),
        ))
        return ft.PopupMenuButton(
            items=pozycje_menu,
            tooltip="Odłóż to przypomnienie",
            content=ft.Container(
                width=36, height=36, alignment=ft.Alignment.CENTER,
                content=ft.Icon(ft.Icons.SNOOZE, size=18, color=ft.Colors.ON_SURFACE_VARIANT),
            ),
        )

    def sekcja_odlozonych():
        odlozone = db.pobierz_odlozone_powiadomienia(state.auto_id)
        if not odlozone:
            return []

        wiersze = ft.Column([], spacing=0, tight=True, visible=False)
        strzalka = ft.Icon(ft.Icons.KEYBOARD_ARROW_DOWN, size=20, color=ft.Colors.ON_SURFACE_VARIANT)

        for o in odlozone:
            podtytul = f"Wróci {o['data_tekst']}"
            if o["dni_do_powrotu"] == 0:
                podtytul = "Wróci jutro"
            elif o["dni_do_powrotu"] == 1:
                podtytul = "Wróci za 1 dzień"
            elif o["dni_do_powrotu"] > 1:
                podtytul = f"Wróci za {o['dni_do_powrotu']} dni ({o['data_tekst']})"
            if not o["nadal_aktualne"]:
                podtytul += " • powód już nieaktualny"

            wiersze.controls.append(ft.ListTile(
                leading=ft.Icon(ft.Icons.SNOOZE, color=ft.Colors.ON_SURFACE_VARIANT),
                title=ft.Text(o["tytul"], color=ft.Colors.ON_SURFACE_VARIANT),
                subtitle=ft.Text(podtytul, size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                trailing=ft.TextButton(
                    "Przywróć",
                    on_click=lambda e, k=o["klucz"]: (
                        db.przywroc_powiadomienie(state.auto_id, k),
                        przejdz(page, page.route),
                        odswiez(),
                    ),
                ),
            ))

        def przelacz(e):
            wiersze.visible = not wiersze.visible
            strzalka.name = ft.Icons.KEYBOARD_ARROW_UP if wiersze.visible else ft.Icons.KEYBOARD_ARROW_DOWN
            try:
                page.update()
            except Exception:
                pass

        naglowek = ft.Container(
            padding=ft.Padding(12, 10, 12, 10),
            border_radius=RADIUS["sm"],
            ink=True, on_click=przelacz,
            content=ft.Row([
                ft.Icon(ft.Icons.SNOOZE, size=18, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Text(f"Odkładane ({len(odlozone)})", weight="bold",
                        color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                strzalka,
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )
        return [ft.Divider(height=8), naglowek, wiersze]

    def odswiez():
        powiadomienia = db.pobierz_powiadomienia(state.auto_id)
        pozycje = [
            ft.Row([
                ft.Icon(ft.Icons.NOTIFICATIONS_ROUNDED, color=ft.Colors.PRIMARY),
                ft.Text("Powiadomienia", weight="bold", size=18, color=ft.Colors.PRIMARY)
            ], spacing=8),
            ft.Divider(height=1),
        ]

        if not powiadomienia:
            pozycje.append(ft.Container(
                padding=ft.Padding.symmetric(vertical=20),
                content=ft.Row([
                    ft.Icon(ft.Icons.TASK_ALT, size=18, color=KOLOR_STATUS["ok"]),
                    ft.Text("Brak zbliżających się terminów", italic=True, color=ft.Colors.ON_SURFACE_VARIANT),
                ], spacing=8)
            ))
        else:
            for p in powiadomienia:
                kolor = ft.Colors.RED_700 if p["status"] == "przeterminowane" else ft.Colors.ORANGE_700
                ikona = ft.Icons.WARNING if p["status"] == "przeterminowane" else ft.Icons.HOURGLASS_BOTTOM
                if p["typ"] == "cykliczny":
                    czy_koszt_p = p.get("czy_koszt", True)
                    kafelek = ft.ListTile(
                        leading=ft.Icon(ikona, color=kolor),
                        title=ft.Text(p["tytul"], weight="bold"),
                        subtitle=ft.Text(p["opis"], color=kolor, size=13),
                    )
                    akcje = [ft.TextButton(
                        "Zapłacone" if czy_koszt_p else "Wykonano",
                        icon=ft.Icons.CHECK,
                        on_click=zaplac_cykliczny(p["wydatek_id"], czy_koszt_p, kafelek),
                    )]
                    drzemka = przycisk_odlozenia(p)
                    if drzemka:
                        akcje.append(drzemka)
                    kafelek.trailing = ft.Row(akcje, spacing=0, tight=True)
                    pozycje.append(kafelek)
                else:
                    pozycje.append(ft.ListTile(
                        leading=ft.Icon(ikona, color=kolor),
                        title=ft.Text(p["tytul"], weight="bold"),
                        subtitle=ft.Text(p["opis"], color=kolor, size=13),
                        trailing=przycisk_odlozenia(p),
                        on_click=idz_do(p["trasa"]),
                    ))

        # Odłożone trzymamy w zwijanej sekcji na dole: nie zaśmiecają listy,
        # ale nie znikają bez śladu — widać datę powrotu i można ją cofnąć.
        pozycje.extend(sekcja_odlozonych())

        bs.content = ft.Container(
            padding=20,
            bgcolor=ft.Colors.SURFACE,
            content=ft.Column(pozycje, tight=True, spacing=4, scroll=ft.ScrollMode.AUTO)
        )
        try:
            page.update()
        except Exception:
            pass

    odswiez()
    otworz_dno(page, bs)

def pokaz_panel_wydatkow_cyklicznych(page: ft.Page, state):
    """Lekki panel (BottomSheet) do zarządzania wydatkami cyklicznymi pojazdu
    (raty, abonamenty, ubezpieczenia ratalne) ORAZ zwykłymi przypomnieniami
    cyklicznymi bez kosztu (np. "co miesiąc sprawdź ciśnienie w oponach") —
    bez osobnej trasy, analogicznie do pokaz_panel_powiadomien()."""
    bs = ft.BottomSheet(ft.Container())

    def odswiez():
        wpisy = db.pobierz_wydatki_cykliczne(state.auto_id)
        pozycje = [
            ft.Row([
                ft.Icon(ft.Icons.AUTORENEW, color=ft.Colors.PRIMARY),
                ft.Text("Wydatki cykliczne i przypomnienia", weight="bold", size=18, color=ft.Colors.PRIMARY)
            ], spacing=8),
            ft.Divider(height=1),
        ]

        if not wpisy:
            pozycje.append(ft.Container(
                padding=ft.Padding.symmetric(vertical=15),
                content=ft.Text("Brak zapisanych wydatków cyklicznych ani przypomnień.", italic=True, color=ft.Colors.ON_SURFACE_VARIANT)
            ))
        else:
            for w_id, nazwa, kwota, okres_dni, nastepna_data, czy_koszt in wpisy:
                kolor, tekst_daty = kolor_i_tekst_terminu(nastepna_data)
                czy_koszt = bool(czy_koszt)
                podtytul = (
                    f"{formatuj_liczba(kwota)} {symbol_waluty()} • co {okres_dni} dni • {tekst_daty or nastepna_data}"
                    if czy_koszt else
                    f"Przypomnienie • co {okres_dni} dni • {tekst_daty or nastepna_data}"
                )
                pozycje.append(ft.ListTile(
                    leading=ft.Icon(ft.Icons.AUTORENEW if czy_koszt else ft.Icons.NOTIFICATIONS_ACTIVE, color=kolor),
                    title=ft.Text(str(nazwa), weight="bold"),
                    subtitle=ft.Text(podtytul, size=12, color=kolor),
                    trailing=ft.PopupMenuButton(items=[
                        ft.PopupMenuItem(
                            content=ft.Row([ft.Icon(ft.Icons.CHECK_CIRCLE, color=ft.Colors.GREEN, size=18), ft.Text("Zapłacone" if czy_koszt else "Wykonano")]),
                            on_click=lambda e, wid=w_id, ck=czy_koszt: zaplac(wid, ck)
                        ),
                        ft.PopupMenuItem(
                            content=ft.Row([ft.Icon(ft.Icons.EDIT, size=18), ft.Text("Edytuj")]),
                            on_click=lambda e, w=(w_id, nazwa, kwota, okres_dni, nastepna_data, czy_koszt): formularz(w)
                        ),
                        ft.PopupMenuItem(
                            content=ft.Row([ft.Icon(ft.Icons.DELETE, color=ft.Colors.RED, size=18), ft.Text("Usuń")]),
                            on_click=lambda e, wid=w_id: usun(wid)
                        ),
                    ])
                ))

        pozycje.append(ft.Divider(height=1))
        pozycje.append(ft.TextButton("Dodaj wydatek / przypomnienie", icon=ft.Icons.ADD, on_click=lambda e: formularz(None)))

        bs.content = ft.Container(
            padding=20, bgcolor=ft.Colors.SURFACE,
            content=ft.Column(pozycje, tight=True, spacing=4, scroll=ft.ScrollMode.AUTO)
        )
        try:
            page.update()
        except Exception:
            pass

    def zaplac(wydatek_id, czy_koszt=True):
        db.oznacz_zaplacony_wydatek_cykliczny(wydatek_id, state.auto_id)
        komunikat = "Zapisano płatność i przesunięto termin." if czy_koszt else "Oznaczono jako wykonane i przesunięto termin."
        pokaz_komunikat(page, komunikat)
        odswiez()

    def usun(wydatek_id):
        def wykonaj():
            db.usun_wydatek_cykliczny(wydatek_id)
            odswiez()
            pokaz_komunikat(page, "Usunięto wpis.")
        potwierdz(page, "Usunąć?", "Czy na pewno usunąć ten wpis?", wykonaj)

    def formularz(istniejacy):
        edycja = istniejacy is not None
        w_id, nazwa_val, kwota_val, okres_val, data_val, czy_koszt_val = (
            istniejacy if istniejacy is not None
            else (None, "", "", 30, datetime.now().strftime("%d.%m.%Y"), 1)
        )

        e_nazwa = ft.TextField(label="Nazwa (np. Rata leasingu, Sprawdź ciśnienie w oponach)", value=str(nazwa_val), **styl_pola())
        e_kwota = ft.TextField(label=f"Kwota ({symbol_waluty()})", value=str(kwota_val) if kwota_val else "", keyboard_type=ft.KeyboardType.NUMBER, **styl_pola())
        e_tylko_przypomnienie = ft.Switch(label="Tylko przypomnienie (bez kwoty)", value=not bool(czy_koszt_val))
        e_kwota.visible = not e_tylko_przypomnienie.value

        def przelacz_typ(e):
            e_kwota.visible = not e_tylko_przypomnienie.value
            if not e_kwota.visible:
                e_kwota.error_text = None
            page.update()
        e_tylko_przypomnienie.on_change = przelacz_typ

        e_okres = ft.Dropdown(
            label="Powtarzaj co",
            options=[
                ft.DropdownOption(key="30", text="Miesiąc (30 dni)"),
                ft.DropdownOption(key="90", text="Kwartał (90 dni)"),
                ft.DropdownOption(key="180", text="Pół roku (180 dni)"),
                ft.DropdownOption(key="365", text="Rok (365 dni)"),
            ],
            value=str(okres_val) if str(okres_val) in ("30", "90", "180", "365") else "30",
            **styl_dropdown()
        )
        e_data = pole_daty(page, "Następny termin", str(data_val))

        def zapisz(e):
            e_nazwa.error_text = None
            e_kwota.error_text = None
            n = (e_nazwa.value or "").strip()
            czy_koszt = not e_tylko_przypomnienie.value
            kw = parsuj_float(e_kwota.value, None) if czy_koszt else 0.0
            bledy = []
            if not n: bledy.append((e_nazwa, "Podaj nazwę"))
            if czy_koszt and (kw is None or kw <= 0): bledy.append((e_kwota, "Podaj poprawną kwotę"))
            if bledy:
                for kontrolka, komunikat in bledy: kontrolka.error_text = komunikat
                page.update()
                return
            okres_dni = parsuj_int(e_okres.value, 30)
            if edycja:
                db.edytuj_wydatek_cykliczny(w_id, n, kw or 0.0, okres_dni, e_data.value, czy_koszt)
            else:
                db.dodaj_wydatek_cykliczny(state.auto_id, n, kw or 0.0, okres_dni, e_data.value, czy_koszt)
            zamknij_dialog(page, dlg)
            odswiez()

        dlg = ft.AlertDialog(
            title=ft.Text("Edytuj wpis" if edycja else "Nowy wydatek cykliczny / przypomnienie", weight="bold"),
            content=ft.Column([e_nazwa, e_tylko_przypomnienie, e_kwota, e_okres, e_data], tight=True, spacing=10),
            actions=[
                ft.TextButton("Anuluj", on_click=lambda e: zamknij_dialog(page, dlg)),
                ft.ElevatedButton("Zapisz", on_click=zapisz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY)
            ]
        )
        otworz_dialog(page, dlg)

    odswiez()
    otworz_dno(page, bs)

def zbuduj_pasek_glowny(page: ft.Page, state, cb_export, cb_import, cb_theme):
    """Pasek górny ekranu głównego. Menu ⋮ nie jest już płaską listą kilkunastu
    pozycji (w której kalkulator trasy sąsiadował z dziennikiem pojazdu, a import
    bazy z eksportem CSV) — otwiera panel z rozwijanymi sekcjami pogrupowanymi
    po tym, CO SIĘ ROBI: garaż, współdzielenie, narzędzia, dane, aplikacja."""

    IKONY_TRYBU_MOTYWU = {"jasny": ft.Icons.LIGHT_MODE, "ciemny": ft.Icons.DARK_MODE, "system": ft.Icons.BRIGHTNESS_AUTO}
    ETYKIETY_TRYBU_MOTYWU = {"jasny": "Przełącz na tryb jasny", "ciemny": "Przełącz na tryb ciemny", "system": "Przełącz na tryb systemowy"}
    OPISY_TRYBU_MOTYWU = {
        "jasny": "Zawsze jasne tło",
        "ciemny": "Zawsze ciemne tło",
        "system": "Podąża za ustawieniem telefonu",
    }

    def otworz_menu(e):
        obecny_tryb = db.pobierz_tryb_motywu()
        nastepny_tryb = db.KOLEJNOSC_TRYBOW_MOTYWU[(db.KOLEJNOSC_TRYBOW_MOTYWU.index(obecny_tryb) + 1) % 3]
        w_koszu = db.liczba_w_koszu()

        pojazdy = [
            {"ikona": ft.Icons.ADD_CIRCLE_OUTLINE, "kolor": ft.Colors.GREEN_700,
             "tekst": "Dodaj nowy pojazd", "opis": "Nowe auto w garażu",
             "akcja": lambda: przejdz(page, "/auto/nowy")},
        ]
        if state.auto_id:
            pojazdy.append(
                {"ikona": ft.Icons.DELETE_OUTLINE, "kolor": ft.Colors.RED_700,
                 "tekst": "Usuń pojazd", "opis": f"„{state.auto_nazwa}” trafi do kosza",
                 "akcja": lambda: usun_auto(page, state)}
            )
        pojazdy.append(
            {"ikona": ft.Icons.DELETE_SWEEP, "tekst": "Kosz",
             "opis": "Przywróć usunięty pojazd z historią i zdjęciami",
             "odznaka": w_koszu or None,
             "akcja": lambda: przejdz(page, "/kosz")}
        )
        pojazdy.append(
            {"ikona": ft.Icons.COMPARE_ARROWS, "tekst": "Porównaj pojazdy",
             "opis": "Koszty i spalanie obok siebie",
             "akcja": lambda: przejdz(page, "/porownanie")}
        )

        wspoldzielenie = [
            {"ikona": ft.Icons.PEOPLE, "tekst": "Współdziel pojazd",
             "opis": "Zaproś domownika i synchronizuj dane",
             "akcja": lambda: przejdz(page, "/wspoldzielenie")},
            {"ikona": ft.Icons.CALCULATE, "tekst": "Podział kosztów",
             "opis": "Kto ile wydał na wspólne auto",
             "akcja": lambda: przejdz(page, "/podzial")},
        ]

        narzedzia = [
            {"ikona": ft.Icons.MAP, "tekst": "Kalkulator podróży",
             "opis": "Policz koszt trasy przed wyjazdem",
             "akcja": lambda: przejdz(page, "/kalkulator")},
            {"ikona": ft.Icons.TIMELINE, "tekst": "Dziennik życia auta",
             "opis": "Oś czasu wszystkich zdarzeń",
             "akcja": lambda: przejdz(page, "/timeline")},
            {"ikona": ft.Icons.AUTORENEW, "tekst": "Wydatki cykliczne i przypomnienia",
             "opis": "Raty, abonamenty, powtarzalne czynności",
             "akcja": lambda: pokaz_panel_wydatkow_cyklicznych(page, state)},
        ]

        dane = [
            {"ikona": ft.Icons.BACKUP, "tekst": "Kopia zapasowa bazy",
             "opis": "Zapisz całą bazę razem ze zdjęciami",
             "akcja": lambda: cb_export(None)},
            {"ikona": ft.Icons.SETTINGS_BACKUP_RESTORE, "kolor": ft.Colors.ORANGE_800,
             "tekst": "Wczytaj kopię bazy", "opis": "Podmienia WSZYSTKIE dane w aplikacji",
             "akcja": lambda: cb_import(None)},
            {"ikona": ft.Icons.SUMMARIZE, "tekst": "Eksport danych (CSV/PDF)",
             "opis": "Raport z wybranego okresu do wysłania",
             "akcja": lambda: przejdz(page, "/eksport")},
            {"ikona": ft.Icons.INPUT, "tekst": "Import z pliku CSV",
             "opis": "Tankowania, inne koszty albo odczyty licznika z arkusza",
             "akcja": lambda: przejdz(page, "/import")},
        ]

        aplikacja = [
            {"ikona": ft.Icons.SETTINGS, "tekst": "Ustawienia",
             "opis": "Waluta, progi powiadomień, kokpit, kosz",
             "akcja": lambda: przejdz(page, "/ustawienia")},
            {"ikona": IKONY_TRYBU_MOTYWU[nastepny_tryb], "tekst": ETYKIETY_TRYBU_MOTYWU[nastepny_tryb],
             "opis": OPISY_TRYBU_MOTYWU[nastepny_tryb],
             "akcja": lambda: cb_theme(None)},
        ]

        pokaz_menu_grupowane(
            page, "Menu główne",
            [
                # Garaż otwarty od razu — to po niego sięga się najczęściej.
                {"tytul": "Pojazdy", "ikona": ft.Icons.GARAGE, "otwarta": True, "pozycje": pojazdy},
                {"tytul": "Współdzielenie", "ikona": ft.Icons.GROUPS, "pozycje": wspoldzielenie},
                {"tytul": "Narzędzia", "ikona": ft.Icons.HANDYMAN, "pozycje": narzedzia},
                {"tytul": "Dane i kopie", "ikona": ft.Icons.FOLDER_COPY, "pozycje": dane},
                {"tytul": "Aplikacja", "ikona": ft.Icons.TUNE, "pozycje": aplikacja},
            ],
            podtytul=state.auto_nazwa if state.auto_id else "Brak pojazdów",
        )

    nowoczesny_naglowek = ft.Row([
        ft.Container(
            content=ft.Icon(ft.Icons.DIRECTIONS_CAR, size=18, color=ft.Colors.PRIMARY),
            bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.PRIMARY),
            border_radius=8,
            padding=5
        ),
        ft.Column([
            ft.Text("Menedżer Samochodowy", size=9, weight="bold", color=ft.Colors.PRIMARY, no_wrap=True),
            ft.Text("APLIKACJA KAMILA", weight="bold", size=14, no_wrap=True)
        ], spacing=0)
    ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    return ft.AppBar(
        title=nowoczesny_naglowek,
        center_title=False, 
        bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.PRIMARY),
        actions=[
            ft.IconButton(
                icon=ft.Icons.SEARCH,
                icon_size=20,
                tooltip="Szukaj we wszystkim",
                on_click=lambda e: przejdz(page, "/szukaj"),
                width=36, height=36,
                style=ft.ButtonStyle(padding=0),
            ),
            przycisk_dzwonka(page, state),
            ft.IconButton(
                icon=ft.Icons.MORE_VERT,
                icon_size=20,
                icon_color=ft.Colors.ON_SURFACE_VARIANT,
                tooltip="Menu główne",
                on_click=otworz_menu,
                width=36, height=36,
                style=ft.ButtonStyle(padding=0),
            ),
        ]
    )

def zbuduj_pasek_z_powrotem(page: ft.Page, tytul, trasa_powrotu, on_save=None, akcje_dodatkowe=None, czy_zmieniono=None, ikona=None):
    """`ikona` zastąpiła emoji doklejane wcześniej do tytułu ekranu — ikona
    Material dziedziczy kolor motywu i ma ten sam ciężar, co reszta oznaczeń."""
    def wroc(e):
        if czy_zmieniono and czy_zmieniono():
            def wykonaj(e2):
                zamknij_dialog(page, dlg)
                przejdz(page, trasa_powrotu)
            dlg = ft.AlertDialog(
                title=ft.Text("Niezapisane zmiany"),
                content=ft.Text("Masz niezapisane zmiany w formularzu. Wyjść bez zapisywania?"),
                actions=[
                    ft.TextButton("Anuluj", on_click=lambda e2: zamknij_dialog(page, dlg)),
                    ft.TextButton("Wyjdź bez zapisywania", on_click=wykonaj, style=ft.ButtonStyle(color=ft.Colors.RED)),
                ]
            )
            otworz_dialog(page, dlg)
        else:
            przejdz(page, trasa_powrotu)

    actions = []
    if on_save:
        actions.append(
            ft.IconButton(
                icon=ft.Icons.SAVE,
                icon_color=ft.Colors.PRIMARY,
                tooltip="Zapisz formularz",
                on_click=on_save
            )
        )
        actions.append(
            ft.PopupMenuButton(
                items=[
                    ft.PopupMenuItem(
                        content=ft.Row([
                            ft.Icon(ft.Icons.SAVE, color=ft.Colors.PRIMARY, size=20), 
                            ft.Text("Zapisz")
                        ]), 
                        on_click=on_save
                    ),
                    ft.PopupMenuItem(
                        content=ft.Row([
                            ft.Icon(ft.Icons.CANCEL, color=ft.Colors.RED, size=20), 
                            ft.Text("Anuluj i wróć")
                        ]), 
                        on_click=wroc
                    )
                ],
                tooltip="Opcje formularza"
            )
        )
    if akcje_dodatkowe:
        actions.extend(akcje_dodatkowe)

    etykieta = ft.Text(tytul, weight="bold", size=18, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS)
    tytul_kontrolka = etykieta if not ikona else ft.Row([
        ft.Icon(ikona, size=20, color=ft.Colors.PRIMARY),
        etykieta,
    ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER, tight=True)

    return ft.AppBar(
        title=tytul_kontrolka,
        center_title=False,
        bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.PRIMARY),
        leading=ft.IconButton(
            icon=ft.Icons.ARROW_BACK,
            on_click=wroc
        ),
        actions=actions
    )

def _zbuduj_popup_filtra(page: ft.Page, state, klucz_stanu, opcje, etykieta, ikona_aktywna, ikona_nieaktywna):
    """Generyczna metoda budująca przycisk filtra z menu rozwijanym."""
    aktualny_filtr = state.filtry.setdefault(klucz_stanu, "Wszystko")
    if aktualny_filtr not in opcje:
        aktualny_filtr = "Wszystko"
        state.filtry[klucz_stanu] = aktualny_filtr

    def zmien_filtr(wartosc):
        state.filtry[klucz_stanu] = wartosc
        przejdz(page, page.route)

    elementy_menu = []
    for o in opcje:
        zaznaczone = (o == aktualny_filtr)
        elementy_menu.append(
            ft.PopupMenuItem(
                content=ft.Row([
                    ft.Icon(ft.Icons.CHECK, size=16, color=ft.Colors.PRIMARY, visible=zaznaczone),
                    ft.Text(o, weight="bold" if zaznaczone else "normal")
                ]),
                on_click=lambda e, val=o: zmien_filtr(val)
            )
        )

    jest_aktywny = (aktualny_filtr != "Wszystko")
    kolor_glowny = ft.Colors.PRIMARY if jest_aktywny else ft.Colors.ON_SURFACE_VARIANT
    kolor_tla = ft.Colors.with_opacity(0.15, ft.Colors.PRIMARY) if jest_aktywny else ft.Colors.with_opacity(0.06, ft.Colors.ON_SURFACE)

    pokazywany_tekst = aktualny_filtr if jest_aktywny else etykieta
    if len(pokazywany_tekst) > 9:
        pokazywany_tekst = pokazywany_tekst[:7] + ".."

    popup = ft.PopupMenuButton(
        items=elementy_menu,
        content=ft.Row([
            ft.Icon(ikona_aktywna if jest_aktywny else ikona_nieaktywna, size=13, color=kolor_glowny),
            ft.Text(pokazywany_tekst, size=11, weight="bold", color=kolor_glowny),
        ], spacing=2),
        tooltip=f"Filtruj po: {etykieta}"
    )

    return ft.Container(
        height=36,  # <-- SZTYWNA WYSOKOŚĆ
        bgcolor=kolor_tla, 
        border_radius=18, 
        padding=ft.Padding(12, 0, 12, 0),
        alignment=ft.Alignment.CENTER,
        content=popup
    )

def przycisk_filtrowania_rok(page: ft.Page, state, klucz_stanu, lista_danych, index_daty):
    lata = set()
    for w in lista_danych:
        try:
            data_str = w[index_daty]
            d = parsuj_date(data_str)
            if d != datetime.min.date():
                lata.add(str(d.year))
        except Exception:
            pass
    
    opcje = ["Wszystko"] + sorted(list(lata), reverse=True)
    return _zbuduj_popup_filtra(
        page, state, klucz_stanu, opcje, "Rok",
        ft.Icons.FILTER_ALT_ROUNDED, ft.Icons.FILTER_ALT_OUTLINED
    )


def przycisk_filtrowania_kategoria(page: ft.Page, state, klucz_stanu, lista_danych, index_pola, etykieta="Tagi"):
    wartosci = set()
    for w in lista_danych:
        try:
            wartosc = str(w[index_pola] or "").strip()
            if wartosc and wartosc != "None":
                for tag in wartosc.split(","):
                    if tag.strip(): wartosci.add(tag.strip())
        except Exception:
            pass
    
    opcje = ["Wszystko"] + sorted(list(wartosci))
    return _zbuduj_popup_filtra(
        page, state, klucz_stanu, opcje, etykieta,
        ft.Icons.LABEL_ROUNDED, ft.Icons.LABEL_OUTLINE
    )


# Filtr autorstwa przy pojazdach współdzielonych: „kto to dodał”. Wpisy sprzed
# wprowadzenia kolumny dodane_przez (i te bez autora, jak odczyty licznika)
# lądują pod wspólną etykietą — inaczej filtr udawałby, że ich nie ma.
FILTR_AUTOR_MOJE = "Tylko moje"
FILTR_AUTOR_BEZ = "Bez autora"


def _autor_rekordu(rekord, pole):
    try:
        return " ".join(str(rekord[pole] or "").split())
    except Exception:
        return ""


def przycisk_filtrowania_autora(page: ft.Page, state, klucz_stanu, lista_danych, pole):
    """Filtr „Autor” obok Typ/Rok/Miesiąc. Opcje: Wszystko · Tylko moje ·
    każda osoba, która cokolwiek dodała. Przy dwóch domownikach działa jak
    przełącznik „tylko moje”, przy trzech od razu widać też konkretną osobę."""
    moje = db.pobierz_moje_imie()
    autorzy, sa_bez_autora = set(), False
    for w in lista_danych:
        autor = _autor_rekordu(w, pole)
        if autor:
            autorzy.add(autor)
        else:
            sa_bez_autora = True

    opcje = ["Wszystko", FILTR_AUTOR_MOJE]
    opcje += sorted(a for a in autorzy if a != moje)
    if sa_bez_autora:
        opcje.append(FILTR_AUTOR_BEZ)

    return _zbuduj_popup_filtra(
        page, state, klucz_stanu, opcje, "Autor",
        ft.Icons.PERSON, ft.Icons.PERSON_OUTLINE
    )


def filtruj_po_autorze(lista_danych, state, klucz_stanu, pole):
    filtr = state.filtry.get(klucz_stanu, "Wszystko")
    if filtr == "Wszystko":
        return lista_danych

    moje = db.pobierz_moje_imie()
    wynik = []
    for w in lista_danych:
        autor = _autor_rekordu(w, pole)
        if filtr == FILTR_AUTOR_MOJE:
            pasuje = bool(autor) and autor == moje
        elif filtr == FILTR_AUTOR_BEZ:
            pasuje = not autor
        else:
            pasuje = autor == filtr
        if pasuje:
            wynik.append(w)
    return wynik


def przycisk_filtrowania_miesiac(page: ft.Page, state, klucz_stanu, lista_danych, index_daty):
    miesiace_nr = set()
    for w in lista_danych:
        try:
            data_str = w[index_daty]
            d = parsuj_date(data_str)
            if d != datetime.min.date():
                miesiace_nr.add(d.month)
        except Exception:
            pass
    
    opcje = ["Wszystko"] + [MIESIACE_NAZWY[m - 1] for m in sorted(list(miesiace_nr))]
    return _zbuduj_popup_filtra(
        page, state, klucz_stanu, opcje, "Miesiąc",
        ft.Icons.DATE_RANGE_ROUNDED, ft.Icons.DATE_RANGE_OUTLINED
    )

def filtruj_po_roku(lista_danych, state, klucz_stanu, index_daty):
    filtr = state.filtry.get(klucz_stanu, "Wszystko")
    if filtr == "Wszystko":
        return lista_danych
    
    wynik = []
    for w in lista_danych:
        try:
            data_str = w[index_daty]
            d = parsuj_date(data_str)
            if d != datetime.min.date() and str(d.year) == filtr:
                wynik.append(w)
        except Exception:
            pass
    return wynik

def filtruj_po_kategorii(lista_danych, state, klucz_stanu, index_pola):
    filtr = state.filtry.get(klucz_stanu, "Wszystko")
    if filtr == "Wszystko":
        return lista_danych
    
    wynik = []
    for w in lista_danych:
        try:
            wartosc = str(w[index_pola] or "").strip()
            tagi_w_rekordzie = [t.strip() for t in wartosc.split(",")]
            if filtr in tagi_w_rekordzie:
                wynik.append(w)
        except Exception:
            pass
    return wynik

def filtruj_po_miesiacu(lista_danych, state, klucz_stanu, index_daty):
    filtr = state.filtry.get(klucz_stanu, "Wszystko")
    if filtr == "Wszystko":
        return lista_danych
    
    idx_miesiaca = MIESIACE_NAZWY.index(filtr) + 1
    wynik = []
    for w in lista_danych:
        try:
            data_str = w[index_daty]
            d = parsuj_date(data_str)
            if d != datetime.min.date() and d.month == idx_miesiaca:
                wynik.append(w)
        except Exception:
            pass
    return wynik

def ekran_braku_danych(ikona, tytul, opis, tekst_przycisku, on_click):
    return ft.Container(
        padding=30,
        content=ft.Column([
            ft.Container(height=10),
            ft.Row([
                ft.Container(
                    width=104, height=104, border_radius=52,
                    alignment=ft.Alignment.CENTER,
                    gradient=ft.RadialGradient(colors=[
                        ft.Colors.with_opacity(0.22, ft.Colors.PRIMARY),
                        ft.Colors.with_opacity(0.0, ft.Colors.PRIMARY),
                    ]),
                    content=ft.Icon(ikona, size=46, color=ft.Colors.PRIMARY),
                )
            ], alignment=ft.MainAxisAlignment.CENTER),
            ft.Container(height=10),
            ft.Row([
                ft.Text(tytul, size=FS["heading"], weight="bold", color=ft.Colors.ON_SURFACE)
            ], alignment=ft.MainAxisAlignment.CENTER),
            ft.Row([
                ft.Text(opis, size=FS["body"], color=ft.Colors.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER)
            ], alignment=ft.MainAxisAlignment.CENTER),
            ft.Container(height=15),
            ft.Row([
                ft.ElevatedButton(
                    content=ft.Row([
                        ft.Icon(ft.Icons.ADD, size=18, color=ft.Colors.ON_PRIMARY),
                        ft.Text(tekst_przycisku, color=ft.Colors.ON_PRIMARY, weight="bold")
                    ], tight=True, spacing=6),
                    bgcolor=ft.Colors.PRIMARY,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=RADIUS["md"]), padding=ft.Padding(20, 14, 20, 14)),
                    on_click=on_click
                )
            ], alignment=ft.MainAxisAlignment.CENTER),
            ft.Container(height=20)
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)
    )

def styl_pola(page: ft.Page = None):
    return {
        "border_radius": RADIUS["md"],
        "border_color": ft.Colors.TRANSPARENT,   # ramka niewidoczna...
        "border_width": 1.5,
        "focused_border_color": ft.Colors.PRIMARY,  # ...i pojawia się tylko na focus
        "focused_border_width": 2,
        "content_padding": ft.Padding(16, 14, 16, 14),  # 16 poziomo / 14 pionowo — pole ~52-56px
        "filled": True,
        "bgcolor": tlo_karty(page, poziom=2),
    }

def styl_dropdown(page: ft.Page = None):
    return {
        "border_radius": RADIUS["md"],
        "border_color": ft.Colors.TRANSPARENT,
        "border_width": 1.5,
        "focused_border_color": ft.Colors.PRIMARY,
        "focused_border_width": 2,
        "content_padding": ft.Padding(16, 14, 16, 14),
        "filled": True,
        "fill_color": tlo_karty(page, poziom=2),  # UWAGA: nie "bgcolor" — patrz niżej
        "text_size": 15,
    }

def wysokosc_listy(page: ft.Page, udzial=0.5, minimalna=260):
    """Sugerowana wysokość (px) dla zwirtualizowanej listy/siatki (ListView/GridView)
    osadzonej w przewijanym widoku. Używamy jej zamiast `expand=True`, bo gdy nad listą
    jest dużo stałych elementów (nagłówek auta, skróty, pasek sortowania, wyszukiwarka),
    `expand` potrafi skurczyć się do zera na mniejszych telefonach i lista znika
    całkowicie. Dzięki stałej wysokości lista ZAWSZE jest widoczna i przewija się sama,
    a resztę strony (nagłówek itp.) przewija się nad nią jak zwykłą stronę."""
    try:
        wys_ekranu = page.height or getattr(page.window, "height", None) or 800
    except Exception:
        wys_ekranu = 800
    return max(minimalna, int(wys_ekranu * udzial))

def karta_formularza(zawartosc, tytul=None, ikona=None, domyslnie_otwarte=False, page: ft.Page = None):
    import flet as ft
    powierzchnia = powierzchnia_karty(page, "md")

    if not tytul:
        return ft.Container(
            padding=SPACING["lg"], border_radius=RADIUS["lg"],
            bgcolor=powierzchnia["bgcolor"], shadow=powierzchnia["shadow"],
            border=powierzchnia["border"],
            content=ft.Column(zawartosc, spacing=SPACING["md"])
        )

    cialo = ft.Container(
        padding=ft.Padding(SPACING["lg"], 0, SPACING["lg"], SPACING["lg"]),
        visible=domyslnie_otwarte,
        content=ft.Column(zawartosc, spacing=SPACING["md"])
    )

    ikona_strzalki = ft.Icon(
        ft.Icons.KEYBOARD_ARROW_UP if domyslnie_otwarte else ft.Icons.KEYBOARD_ARROW_DOWN,
        color=ft.Colors.PRIMARY
    )

    def przelacz_rozwijanie(e):
        cialo.visible = not cialo.visible
        ikona_strzalki.name = ft.Icons.KEYBOARD_ARROW_UP if cialo.visible else ft.Icons.KEYBOARD_ARROW_DOWN
        e.control.page.update()

    naglowek = ft.Container(
        padding=ft.Padding(SPACING["lg"], SPACING["md"], SPACING["lg"], SPACING["md"]),
        on_click=przelacz_rozwijanie,
        content=ft.Row([
            ft.Icon(ikona, color=ft.Colors.PRIMARY, size=20) if ikona else ft.Container(),
            ft.Text(tytul, weight="bold", size=FS["title"], color=ft.Colors.ON_SURFACE, expand=True),
            ikona_strzalki
        ], spacing=10)
    )

    return ft.Container(
        border_radius=RADIUS["lg"],
        bgcolor=powierzchnia["bgcolor"], shadow=powierzchnia["shadow"],
        border=powierzchnia["border"],
        content=ft.Column([naglowek, cialo], spacing=0)
    )

def przyciski_akcji(page: ft.Page, tekst_zapisu, on_zapisz, trasa_anuluj, ikona_zapisu=ft.Icons.CHECK):
    btn_zapisz = ft.ElevatedButton(
        tekst_zapisu,
        icon=ikona_zapisu,
        on_click=on_zapisz, 
        bgcolor=ft.Colors.PRIMARY, 
        color=ft.Colors.ON_PRIMARY, 
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=RADIUS["md"]), padding=15),
        width=float("inf")
    )
    btn_anuluj = ft.OutlinedButton(
        "Anuluj",
        icon=ft.Icons.CLOSE,
        on_click=lambda e: przejdz(page, trasa_anuluj), 
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=RADIUS["md"]), padding=15),
        width=float("inf")
    )
    return ft.Column([ft.Divider(height=10, color="transparent"), btn_zapisz, btn_anuluj, dol_bezpieczny(30)], spacing=10)

def dol_bezpieczny(wysokosc=20):
    return ft.SafeArea(
        content=ft.Container(height=wysokosc),
        avoid_intrusions_top=False,
    )

def formatuj_spalanie(wartosc_na_100km, decimale=1, elektryczny=False):
    """Formatuje zużycie w jednostce z Ustawień. Wejściem ZAWSZE jest zużycie
    na 100 km (l/100km albo kWh/100km) — dokładnie to, co liczy reszta aplikacji;
    przeliczenie na km/l, mpg czy km/kWh robimy dopiero tutaj."""
    jednostka = db.pobierz_jednostke_zuzycia_ev() if elektryczny else db.pobierz_jednostke_spalania()
    try:
        val = float(wartosc_na_100km)
    except (TypeError, ValueError):
        return f"- {jednostka}"
    if val <= 0:
        return f"- {jednostka}"

    if jednostka in ("km/l", "km/kWh"):
        wynik = 100.0 / val
    elif jednostka == "mpg":
        wynik = 235.214583 / val
    else:
        wynik = val

    return f"{formatuj_liczba(wynik, decimale)} {jednostka}"

def symbol_waluty():
    return db.pobierz_walute()

MIESIACE_DOPELNIACZ = [
    "stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca",
    "lipca", "sierpnia", "września", "października", "listopada", "grudnia"
]

def formatuj_date_pl(d):
    tekst = f"{d.day} {MIESIACE_DOPELNIACZ[d.month - 1]}"
    if d.year != datetime.now().year:
        tekst += f" {d.year}"
    return tekst

def oblicz_prognoze_terminu(zostalo_km, sredni_dzienny_przebieg):
    if not sredni_dzienny_przebieg or sredni_dzienny_przebieg <= 0:
        return None, None
    if zostalo_km is None or zostalo_km < 0:
        return None, None

    dni = int(round(zostalo_km / sredni_dzienny_przebieg))
    return dni, date.today() + timedelta(days=dni)

def formatuj_prognoze_km(zostalo_km, sredni_dzienny_przebieg):
    tekst_km = f"{formatuj_liczba(zostalo_km, 0)} km"

    dni, data = oblicz_prognoze_terminu(zostalo_km, sredni_dzienny_przebieg)
    if dni is None:
        return tekst_km

    if dni <= 0:
        opis_dni = "dziś"
    elif dni == 1:
        opis_dni = "jutro"
    else:
        opis_dni = f"ok. {dni} dni"

    return f"{tekst_km} ({opis_dni} - {formatuj_date_pl(data)})"

def kolor_i_tekst_terminu(termin_str):
    if not termin_str:
        return ft.Colors.ON_SURFACE_VARIANT, ""
        
    d_obj = parsuj_date(termin_str)
    if d_obj == datetime.min.date():
        return ft.Colors.ON_SURFACE_VARIANT, termin_str
        
    dzis = datetime.now().date()
    roznica = (d_obj - dzis).days
    
    if roznica < 0:
        return ft.Colors.RED_700, f"Po terminie ({abs(roznica)} dni)"
    elif roznica == 0:
        return ft.Colors.RED_700, "Na dzisiaj!"
    elif roznica == 1:
        return ft.Colors.ORANGE_700, "Na jutro"
    elif roznica <= 7:
        return ft.Colors.ORANGE_700, f"Za {roznica} dni"
    else:
        return ft.Colors.GREEN_700, str(termin_str)

def komponent_wyboru_koloru(page: ft.Page, aktualny_kolor=None, etykieta_brak="Domyślny (jak w Ustawieniach)"):
    """Wiersz kółek do wyboru koloru motywu interfejsu, z dodatkową pozycją
    'Brak' (użyje wtedy globalnego koloru domyślnego). Zwraca (kontener,
    pobierz_wynik), gdzie pobierz_wynik() zwraca nazwę koloru z db.KOLORY_MOTYWU
    albo None."""
    stan = {"wybrany": aktualny_kolor if aktualny_kolor in db.KOLORY_MOTYWU else None}
    wiersz = ft.Row(wrap=True, spacing=10)

    def wybierz(nazwa):
        stan["wybrany"] = nazwa
        odswiez()

    def odswiez():
        wiersz.controls.clear()

        zaznaczony_brak = stan["wybrany"] is None
        wiersz.controls.append(
            ft.Container(
                width=45, height=45, shape=ft.BoxShape.CIRCLE,
                bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE),
                border=ft.Border.all(3, ft.Colors.ON_SURFACE if zaznaczony_brak else ft.Colors.TRANSPARENT),
                alignment=ft.Alignment.CENTER,
                content=ft.Icon(ft.Icons.BLOCK, size=20, color=ft.Colors.ON_SURFACE_VARIANT),
                tooltip=etykieta_brak,
                on_click=lambda e: wybierz(None)
            )
        )

        for nazwa in db.KOLORY_MOTYWU:
            kolor_hex = MAPA_KOLOROW.get(nazwa, ft.Colors.INDIGO)
            zaznaczony = (stan["wybrany"] == nazwa)
            wiersz.controls.append(
                ft.Container(
                    width=45, height=45, bgcolor=kolor_hex, shape=ft.BoxShape.CIRCLE,
                    border=ft.Border.all(3, ft.Colors.ON_SURFACE if zaznaczony else ft.Colors.TRANSPARENT),
                    content=ft.Icon(ft.Icons.CHECK, color=ft.Colors.WHITE, size=24) if zaznaczony else None,
                    tooltip=nazwa,
                    on_click=lambda e, n=nazwa: wybierz(n)
                )
            )

        try:
            wiersz.update()
        except Exception:
            pass

    odswiez()
    return wiersz, lambda: stan["wybrany"]

def komponent_tagow(page: ft.Page, state, aktualne_tagi_str):
    wybrane = set([t.strip() for t in (aktualne_tagi_str or "").split(",") if t.strip()])
    kontener_tagow = ft.Row(wrap=True, spacing=8)
    
    def odswiez_tagi():
        kontener_tagow.controls.clear()
        wszystkie = db.pobierz_tagi(state.auto_id)
        
        for t_id, nazwa, kolor in wszystkie:
            zaznaczony = nazwa in wybrane
            kolor_hex = MAPA_KOLOROW.get(kolor, ft.Colors.BLUE)
            
            # --- DODANE: Funkcja do edycji i trwałego usuwania taga z bazy ---
            def stworz_akcje_opcji(tid, tn, aktualny_kolor):
                def akcja(e):
                    e_nazwa = ft.TextField(label="Nazwa tagu", value=tn, **styl_pola())
                    e_kolor = ft.Dropdown(
                        label="Kolor tagu", 
                        options=[ft.DropdownOption(k) for k in MAPA_KOLOROW.keys()],
                        value=aktualny_kolor,
                        **styl_dropdown()
                    )
                    
                    def zapisz_zmiany(e_btn):
                        e_nazwa.error_text = None
                        nowa_nazwa = (e_nazwa.value or "").strip()
                        
                        if "," in nowa_nazwa:
                            e_nazwa.error_text = "Nazwa nie może zawierać przecinków"
                            e_nazwa.update()
                            return

                        if nowa_nazwa:
                            db.edytuj_tag_w_slowniku(state.auto_id, tid, tn, nowa_nazwa, e_kolor.value)
                            if tn in wybrane:
                                wybrane.remove(tn)
                                wybrane.add(nowa_nazwa)
                            zamknij_dialog(page, dlg)
                            odswiez_tagi()
                            
                    def usun_tag(e_btn):
                        def wykonaj():
                            db.usun_tag_ze_slownika(state.auto_id, tid, tn)
                            if tn in wybrane: wybrane.remove(tn)
                            odswiez_tagi()
                        zamknij_dialog(page, dlg)
                        potwierdz(page, "Usuń tag", f"Usunąć '{tn}'? Zniknie ze wszystkich historycznych wpisów.", wykonaj)

                    dlg = ft.AlertDialog(
                        title=ft.Text(f"Opcje tagu: {tn}", weight="bold"),
                        content=ft.Column([e_nazwa, e_kolor], tight=True, spacing=10),
                        actions=[
                            ft.TextButton("Usuń", style=ft.ButtonStyle(color=ft.Colors.RED_700), on_click=usun_tag),
                            ft.TextButton("Anuluj", on_click=lambda e: zamknij_dialog(page, dlg)),
                            ft.ElevatedButton("Zapisz", on_click=zapisz_zmiany, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY)
                        ]
                    )
                    otworz_dialog(page, dlg)
                return akcja

            chip = ft.Container(
                content=ft.Text(nazwa, size=FS["label"], color=ft.Colors.WHITE if zaznaczony else kolor_hex, weight="bold"),
                padding=ft.Padding(12, 6, 12, 6),
                border_radius=RADIUS["pill"],
                bgcolor=kolor_hex if zaznaczony else ft.Colors.with_opacity(0.12, kolor_hex),
                on_click=lambda e, n=nazwa: przelacz_tag(n),
                on_long_press=stworz_akcje_opcji(t_id, nazwa, kolor),
                tooltip="Kliknij: Zaznacz | Przytrzymaj: Edytuj / Usuń"
            )
            kontener_tagow.controls.append(chip)
            
        btn_dodaj = ft.Container(
            content=ft.Row([ft.Icon(ft.Icons.ADD, size=14, color=ft.Colors.ON_SURFACE_VARIANT), ft.Text("Nowy", size=FS["label"], color=ft.Colors.ON_SURFACE_VARIANT)], spacing=4),
            padding=ft.Padding(12, 6, 12, 6),
            border_radius=RADIUS["pill"],
            bgcolor=tlo_karty(page, poziom=2),
            on_click=lambda e: okno_nowego_tagu()
        )
        kontener_tagow.controls.append(btn_dodaj)
        try:
            kontener_tagow.update()
        except Exception:
            pass
        
    def przelacz_tag(nazwa):
        if nazwa in wybrane:
            wybrane.remove(nazwa)
        else:
            wybrane.add(nazwa)
        odswiez_tagi()
        
    def okno_nowego_tagu():
        e_nazwa = ft.TextField(label="Nazwa tagu", **styl_pola())
        e_kolor = ft.Dropdown(
            label="Kolor tagu", 
            options=[ft.DropdownOption(k) for k in MAPA_KOLOROW.keys()],
            value="Niebieski",
            **styl_dropdown()
        )
        def zapisz_nowy(e):
            e_nazwa.error_text = None
            n = (e_nazwa.value or "").strip()
            
            if "," in n:
                e_nazwa.error_text = "Nazwa nie może zawierać przecinków"
                e_nazwa.update()
                return

            if n:
                db.dodaj_tag(state.auto_id, n, e_kolor.value)
                wybrane.add(n)
                zamknij_dialog(page, dlg)
                odswiez_tagi()
                
        dlg = ft.AlertDialog(
            title=ft.Text("Utwórz nowy tag", weight="bold"),
            content=ft.Column([e_nazwa, e_kolor], tight=True, spacing=10),
            actions=[
                ft.TextButton("Anuluj", on_click=lambda e: zamknij_dialog(page, dlg)),
                ft.ElevatedButton("Dodaj", on_click=zapisz_nowy, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY)
            ]
        )
        otworz_dialog(page, dlg)
        
    odswiez_tagi()
    return kontener_tagow, lambda: ",".join(wybrane)

def wizualizacja_tagow(tagi_str, auto_id, mapa_kolorow=None):
    if not tagi_str or str(tagi_str).strip() == "None":
        return ft.Container()

    wszystkie_kolory = mapa_kolorow if mapa_kolorow is not None else {t[1]: t[2] for t in db.pobierz_tagi(auto_id)}
    tagi_lista = [t.strip() for t in str(tagi_str).split(",") if t.strip()]
    
    chipy = []
    for t in tagi_lista:
        kolor_nazwa = wszystkie_kolory.get(t, "Niebieski")
        kolor_hex = MAPA_KOLOROW.get(kolor_nazwa, ft.Colors.BLUE)
        
        chipy.append(
            ft.Container(
                content=ft.Text(t, size=FS["caption"], weight="bold", color=kolor_hex),
                padding=ft.Padding(8, 3, 8, 3),
                border_radius=RADIUS["pill"],
                bgcolor=ft.Colors.with_opacity(0.12, kolor_hex),
            )
        )
    return ft.Row(chipy, wrap=True, spacing=4)

def znacznik_atrybucji(dodane_przez, zmodyfikowane_przez=None, data_modyfikacji=None):
    """Dyskretny 'chip' pokazujący kto dodał wpis i — jeśli był edytowany —
    kto i kiedy go ostatnio zmienił. Używany tylko przy współdzielonych
    pojazdach, gdzie mogła to zrobić inna osoba."""
    if not dodane_przez and not zmodyfikowane_przez:
        return ft.Container()

    fragmenty = []
    if dodane_przez:
        fragmenty.append(f"Dodano: {dodane_przez}")
    if zmodyfikowane_przez:
        data_txt = f" ({data_modyfikacji})" if data_modyfikacji else ""
        fragmenty.append(f"Edytowano: {zmodyfikowane_przez}{data_txt}")

    return ft.Container(
        content=ft.Row([
            ft.Icon(ft.Icons.PERSON_OUTLINE, size=12, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Text(" | ".join(fragmenty), size=11, color=ft.Colors.ON_SURFACE_VARIANT),
        ], spacing=4),
    )

def znacznik_dodane_przez(nazwa):
    """Mały, dyskretny 'chip' pokazujący kto dodał wpis — używany tylko przy
    współdzielonych pojazdach, gdzie mogła to zrobić inna osoba."""
    if not nazwa:
        return ft.Container(width=0, height=0)
    return ft.Container(
        padding=ft.Padding(6, 2, 6, 2),
        border_radius=6,
        bgcolor=ft.Colors.with_opacity(0.10, ft.Colors.TEAL_700),
        content=ft.Row([
            ft.Icon(ft.Icons.PERSON, size=10, color=ft.Colors.TEAL_700),
            ft.Text(str(nazwa), size=10, weight="bold", color=ft.Colors.TEAL_700)
        ], spacing=3, tight=True)
    )

def komponent_wyboru_warsztatu(page: ft.Page, state, aktualna_nazwa=""):
    stan = {"telefon": None, "adres": None}
    cache_warsztatow = {"dane": None}

    def wpisy_warsztatow():
        # Cache w obrębie życia tego komponentu — lista warsztatów nie
        # zmienia się, dopóki formularz jest otwarty, więc wystarczy jeden SELECT.
        if cache_warsztatow["dane"] is None:
            cache_warsztatow["dane"] = db.pobierz_warsztaty(state.auto_id)
        return cache_warsztatow["dane"]

    warsztaty = wpisy_warsztatow()
    pasujacy_start = next((w for w in warsztaty if w[1] == aktualna_nazwa), None) if aktualna_nazwa else None
    
    # Tryb ręczny włączony tylko gdy wczytujemy wpis, którego nie ma w bazie
    pokaz_reczne = bool(aktualna_nazwa and not pasujacy_start)

    def zbuduj_opcje():
        opcje = [ft.DropdownOption(key="", text="— Brak przypisanego —")]
        for w_id, w_nazwa, w_tel, w_adr, w_not in wpisy_warsztatow():
            opcje.append(ft.DropdownOption(key=w_nazwa, text=w_nazwa))
        return opcje

    e_dropdown = ft.Dropdown(
        label="Warsztat / Wykonawca",
        options=zbuduj_opcje(),
        value=aktualna_nazwa if pasujacy_start else "",
        visible=not pokaz_reczne,
        expand=True,
        **styl_dropdown()
    )

    e_recznie = ft.TextField(
        label="Wpisz nazwę (zapisze się automatycznie)",
        value=aktualna_nazwa if pokaz_reczne else "",
        visible=pokaz_reczne,
        expand=True,
        **styl_pola()
    )

    btn_zmien_tryb = ft.IconButton(
        icon=ft.Icons.LIST if pokaz_reczne else ft.Icons.EDIT,
        tooltip="Wybierz warsztat z bazy" if pokaz_reczne else "Wpisz nową nazwę ręcznie",
        icon_color=ft.Colors.PRIMARY
    )

    wiersz_glowne = ft.Row([e_dropdown, e_recznie, btn_zmien_tryb], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=10)

    btn_dzwon = ft.OutlinedButton("Zadzwoń", icon=ft.Icons.PHONE, visible=False)
    btn_nawiguj = ft.OutlinedButton("Nawiguj", icon=ft.Icons.NAVIGATION, visible=False)
    wiersz_akcji = ft.Row([btn_dzwon, btn_nawiguj], spacing=8, visible=False)

    async def zadzwon(e):
        if stan["telefon"]: await page.launch_url(f"tel:{stan['telefon']}")

    async def nawiguj(e):
        if stan["adres"]: await page.launch_url(f"geo:0,0?q={urllib.parse.quote(stan['adres'])}")

    btn_dzwon.on_click = zadzwon
    btn_nawiguj.on_click = nawiguj

    def odswiez_akcje():
        btn_dzwon.visible = bool(stan["telefon"] and e_dropdown.visible)
        btn_nawiguj.visible = bool(stan["adres"] and e_dropdown.visible)
        wiersz_akcji.visible = btn_dzwon.visible or btn_nawiguj.visible
        try: wiersz_akcji.update()
        except Exception: pass

    def przelacz_tryb(e):
        na_reczne = not e_recznie.visible
        if na_reczne:
            e_dropdown.visible = False
            e_dropdown.value = ""
            e_recznie.visible = True
            btn_zmien_tryb.icon = ft.Icons.LIST
            btn_zmien_tryb.tooltip = "Wybierz z bazy"
        else:
            e_recznie.visible = False
            e_recznie.value = ""
            e_dropdown.visible = True
            btn_zmien_tryb.icon = ft.Icons.EDIT
            btn_zmien_tryb.tooltip = "Wpisz ręcznie"
            e_dropdown.value = ""
            stan["telefon"], stan["adres"] = None, None

        odswiez_akcje()
        try: wiersz_glowne.update()
        except Exception: pass
        
    btn_zmien_tryb.on_click = przelacz_tryb

    def ustaw_z_bazy(nazwa):
        pasujacy = next((w for w in wpisy_warsztatow() if w[1] == nazwa), None)
        if pasujacy:
            stan["telefon"], stan["adres"] = pasujacy[2], pasujacy[3]
        else:
            stan["telefon"], stan["adres"] = None, None
        
        e_dropdown.options = zbuduj_opcje()
        e_dropdown.value = nazwa if pasujacy else ""
        odswiez_akcje()
        try: e_dropdown.update()
        except Exception: pass

    def po_zmianie(e):
        wart = e_dropdown.value
        if wart == "":
            stan["telefon"], stan["adres"] = None, None
            odswiez_akcje()
            try: e_dropdown.update()
            except Exception: pass
        else:
            ustaw_z_bazy(wart)

    e_dropdown.on_change = po_zmianie
    
    if pasujacy_start and not pokaz_reczne:
        stan["telefon"], stan["adres"] = pasujacy_start[2], pasujacy_start[3]
        odswiez_akcje()

    kontener = ft.Column([wiersz_glowne, wiersz_akcji], spacing=4)

    def pobierz_wynik():
        if e_recznie.visible:
            return (e_recznie.value or "").strip()
        wart = e_dropdown.value
        if wart in ("", None):
            return ""
        return wart

    return kontener, pobierz_wynik

def komponent_wyboru_stacji(page: ft.Page, state, aktualna_nazwa="", elektryczny=False):
    """Wybór stacji paliw z listy tych, na których już tankowałeś (słownik
    budowany w locie z tabeli 'tankowania' — patrz db.pobierz_stacje_paliw),
    z możliwością przełączenia na ręczne wpisanie nowej nazwy. Ten sam wzorzec
    co komponent_wyboru_warsztatu. Dzięki temu 'Orlen', 'orlen' i 'ORLEN'
    nie rozjeżdżają rankingu cen (db.pobierz_trend_cen_paliwa).
    Zwraca (kontener, pobierz_wartosc, ustaw_wartosc)."""
    etyk = db.etykiety_paliwa(elektryczny)
    cache_stacji = {"dane": None}

    def nazwy_stacji():
        # Cache w obrębie życia komponentu — lista nie zmienia się, dopóki
        # formularz jest otwarty, więc wystarczy jeden SELECT.
        if cache_stacji["dane"] is None:
            cache_stacji["dane"] = db.pobierz_stacje_paliw(state.auto_id)
        return cache_stacji["dane"]

    biezaca = " ".join((aktualna_nazwa or "").split())
    pasuje_start = biezaca in nazwy_stacji()

    # Tryb ręczny: wpis spoza słownika ALBO brak jakiejkolwiek zapisanej stacji
    # (pierwsze tankowanie — pusty dropdown byłby ślepą uliczką).
    pokaz_reczne = bool(biezaca and not pasuje_start) or not nazwy_stacji()

    def zbuduj_opcje():
        opcje = [ft.DropdownOption(key="", text="— Nie podano —")]
        for nazwa in nazwy_stacji():
            opcje.append(ft.DropdownOption(key=nazwa, text=nazwa))
        return opcje

    e_dropdown = ft.Dropdown(
        label=etyk["punkt_opcjonalnie"],
        options=zbuduj_opcje(),
        value=biezaca if pasuje_start else "",
        visible=not pokaz_reczne,
        expand=True,
        **styl_dropdown()
    )

    e_recznie = ft.TextField(
        label=etyk["punkt_recznie"],
        hint_text=etyk["punkt_hint"],
        value=biezaca if pokaz_reczne else "",
        visible=pokaz_reczne,
        expand=True,
        **styl_pola()
    )

    btn_zmien_tryb = ft.IconButton(
        icon=ft.Icons.LIST if pokaz_reczne else ft.Icons.EDIT,
        tooltip=f"Wybierz {etyk['punkt'].lower()} z listy" if pokaz_reczne else "Wpisz nową nazwę ręcznie",
        icon_color=ft.Colors.PRIMARY
    )

    wiersz = ft.Row(
        [e_dropdown, e_recznie, btn_zmien_tryb],
        vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=10
    )

    def _tryb_listy():
        e_dropdown.visible = True
        e_recznie.visible = False
        btn_zmien_tryb.icon = ft.Icons.EDIT
        btn_zmien_tryb.tooltip = "Wpisz nową stację ręcznie"

    def _tryb_reczny():
        e_dropdown.visible = False
        e_recznie.visible = True
        btn_zmien_tryb.icon = ft.Icons.LIST
        btn_zmien_tryb.tooltip = "Wybierz stację z listy"

    def przelacz_tryb(e):
        if e_recznie.visible:
            wpisana = " ".join((e_recznie.value or "").split())
            e_dropdown.options = zbuduj_opcje()
            e_dropdown.value = wpisana if wpisana in nazwy_stacji() else ""
            _tryb_listy()
        else:
            e_recznie.value = e_dropdown.value or ""
            _tryb_reczny()
        try:
            wiersz.update()
        except Exception:
            pass

    btn_zmien_tryb.on_click = przelacz_tryb

    def dopasuj_do_slownika(tekst):
        """Zwraca istniejącą pisownię stacji, jeśli wpisany tekst to tylko inny
        wariant zapisu ('orlen' -> 'Orlen'). W przeciwnym razie zwraca tekst."""
        czysty = " ".join((tekst or "").split())
        if not czysty:
            return ""
        klucz = db.klucz_stacji(czysty)
        for nazwa in nazwy_stacji():
            if db.klucz_stacji(nazwa) == klucz:
                return nazwa
        return czysty

    def pobierz_wartosc():
        if e_recznie.visible:
            return dopasuj_do_slownika(e_recznie.value)
        return e_dropdown.value or ""

    def ustaw_wartosc(nazwa):
        """Wpisanie wartości z zewnątrz (np. rozpoznanej z paragonu przez OCR)."""
        dopasowana = dopasuj_do_slownika(nazwa)
        if dopasowana and dopasowana in nazwy_stacji():
            e_dropdown.options = zbuduj_opcje()
            e_dropdown.value = dopasowana
            e_recznie.value = ""
            _tryb_listy()
        else:
            e_recznie.value = dopasowana
            _tryb_reczny()
        try:
            wiersz.update()
        except Exception:
            pass

    return wiersz, pobierz_wartosc, ustaw_wartosc

def abs_zalacznik(sciezka_wzgledna):
    if not sciezka_wzgledna:
        return None
    return os.path.abspath(sciezka_wzgledna)

def komponent_zalacznika(page: ft.Page, sciezka_zapisana=None, tylko_zdjecie=False):
    """tylko_zdjecie=True wymusza pojedynczy plik (zdjęcie profilowe pojazdu,
    pojedyncze zdjęcie w galerii karoserii) — bez wielokrotnego wyboru.
    Domyślnie (False) pozwala zaznaczyć od razu kilka zdjęć naraz — zostaną
    automatycznie połączone w jeden wielostronicowy PDF (np. kilka stron
    faktury/paragonu)."""
    stan = {"nowa_sciezka": None, "usuniete": False}
    obsluzono = {"wartosc": False}  # zabezpiecza przed podwójnym zadziałaniem on_result + await

    def zawartosc_podgladu(sciezka):
        if sciezka:
            if sciezka.lower().endswith(".pdf"):
                return ft.Icon(ft.Icons.PICTURE_AS_PDF, size=32, color=ft.Colors.RED_700)
            return ft.Image(src=sciezka, width=56, height=56, fit="cover", border_radius=10)
        return ft.Icon(ft.Icons.IMAGE_OUTLINED, size=26, color=ft.Colors.ON_SURFACE_VARIANT)

    ramka_podgladu = ft.Container(
        width=56, height=56, border_radius=10, alignment=ft.Alignment.CENTER,
        bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.ON_SURFACE),
        content=zawartosc_podgladu(abs_zalacznik(sciezka_zapisana))
    )
    tekst_nazwy = ft.Text(
        os.path.basename(sciezka_zapisana) if sciezka_zapisana else "Brak załącznika",
        size=13, color=ft.Colors.ON_SURFACE_VARIANT, expand=True
    )
    btn_usun = ft.IconButton(
        icon=ft.Icons.DELETE_OUTLINE, icon_color=ft.Colors.RED_700,
        tooltip="Usuń załącznik", visible=bool(sciezka_zapisana)
    )

    def odswiez(sciezka_podgladu, etykieta, pokazuj_usun):
        ramka_podgladu.content = zawartosc_podgladu(sciezka_podgladu)
        tekst_nazwy.value = etykieta
        btn_usun.visible = pokazuj_usun
        try:
            page.update()
        except Exception:
            pass

    def _obsluz_wybrane(pliki):
        """Wspólna logika dla on_result i ścieżki await — działa i dla 1, i dla wielu plików."""
        if not pliki:
            return
        sciezki = [p.path for p in pliki if getattr(p, "path", None)]
        if not sciezki:
            pokaz_komunikat(page, "Brak dostępu do ścieżki (Uprawnienia telefonu).", ft.Colors.RED_700)
            return

        if len(sciezki) == 1:
            stan["nowa_sciezka"] = sciezki[0]
            stan["usuniete"] = False
            odswiez(sciezki[0], os.path.basename(sciezki[0]), True)
            return

        if any(s.lower().endswith(".pdf") for s in sciezki):
            pokaz_komunikat(page, "Można połączyć wiele zdjęć w jeden PDF, ale nie plik PDF razem ze zdjęciami — wybierz same zdjęcia.", ft.Colors.ORANGE_700)
            return

        polaczony = db.polacz_zdjecia_w_pdf(sciezki)
        if not polaczony:
            pokaz_komunikat(page, "Nie udało się połączyć wybranych zdjęć w PDF.", ft.Colors.RED_700)
            return

        stan["nowa_sciezka"] = polaczony
        stan["usuniete"] = False
        odswiez(polaczony, f"{len(sciezki)} zdjęć połączonych w PDF", True)

    def po_wyborze(e):
        if obsluzono["wartosc"]:
            return
        obsluzono["wartosc"] = True
        _obsluz_wybrane(getattr(e, "files", None))

    async def wybierz(e):
        obsluzono["wartosc"] = False
        page.zalacznik_picker.on_result = po_wyborze
        page.zalacznik_picker.update()

        try:
            wynik = await page.zalacznik_picker.pick_files(
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["jpg", "jpeg", "png", "webp", "pdf"],
                allow_multiple=not tylko_zdjecie
            )
            if wynik is not None and not obsluzono["wartosc"]:
                obsluzono["wartosc"] = True
                pliki = getattr(wynik, "files", wynik)
                _obsluz_wybrane(pliki if isinstance(pliki, list) else None)
        except Exception as ex:
            pokaz_komunikat(page, f"Błąd wczytywania pliku: {ex}", ft.Colors.RED_700)

    def usun(e):
        stan["nowa_sciezka"] = None
        stan["usuniete"] = True
        odswiez(None, "Brak załącznika", False)

    btn_usun.on_click = usun

    wiersz = ft.Row([ramka_podgladu, tekst_nazwy, btn_usun], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=10)
    etykieta_przycisku = (
        "Dodaj / zmień załącznik (zdjęcie, PDF)" if tylko_zdjecie
        else "Dodaj / zmień załącznik (możesz zaznaczyć kilka zdjęć naraz)"
    )
    btn_wybierz = ft.TextButton(etykieta_przycisku, icon=ft.Icons.ATTACH_FILE, on_click=wybierz)

    kontener = ft.Column([wiersz, btn_wybierz], spacing=8)

    def pobierz_wynik():
        if stan["usuniete"]:
            return ""
        if stan["nowa_sciezka"]:
            return stan["nowa_sciezka"]
        return None

    return kontener, pobierz_wynik

def komponent_wielu_nowych_zdjec(page: ft.Page):
    """Widget do MASOWEGO dodawania nowych zdjęć (np. galeria karoserii): pozwala
    zaznaczyć od razu kilka plików i dobierać kolejne w kilku turach (nowe pliki
    dopisują się do listy, nie zastępują jej). Zwraca (kontrolka, pobierz_wynik),
    gdzie pobierz_wynik() to lista ścieżek źródłowych — jeszcze niezapisanych
    do trwałego magazynu (kopiowanie robi się dopiero przy zapisie formularza)."""
    stan = {"pliki": []}
    obsluzono = {"wartosc": False}
    lista_podgladow = ft.Column(spacing=8)
    licznik = ft.Text("Nie wybrano jeszcze żadnego zdjęcia.", size=12, color=ft.Colors.ON_SURFACE_VARIANT)

    def usun(sciezka):
        stan["pliki"] = [s for s in stan["pliki"] if s != sciezka]
        odswiez()

    def odswiez():
        lista_podgladow.controls.clear()
        for sciezka in stan["pliki"]:
            lista_podgladow.controls.append(
                ft.Row([
                    ft.Container(
                        width=52, height=52, border_radius=8,
                        content=ft.Image(src=sciezka, width=52, height=52, fit="cover", border_radius=8),
                    ),
                    ft.Text(os.path.basename(sciezka), size=12, color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                    ft.IconButton(icon=ft.Icons.CLOSE, icon_size=18, icon_color=ft.Colors.RED_700, on_click=lambda e, s=sciezka: usun(s)),
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=10)
            )
        n = len(stan["pliki"])
        licznik.value = "Nie wybrano jeszcze żadnego zdjęcia." if n == 0 else f"Wybrano zdjęć: {n}"
        try:
            lista_podgladow.update()
            licznik.update()
        except Exception:
            pass

    def dodaj_pliki(pliki):
        if not pliki:
            return
        rozszerzenia = (".jpg", ".jpeg", ".png", ".webp")
        nowe = [p.path for p in pliki if getattr(p, "path", None) and p.path.lower().endswith(rozszerzenia)]
        pominieto_pdf = any(getattr(p, "path", "").lower().endswith(".pdf") for p in pliki if getattr(p, "path", None))

        if nowe:
            for s in nowe:
                if s not in stan["pliki"]:
                    stan["pliki"].append(s)
            odswiez()
        if pominieto_pdf:
            pokaz_komunikat(page, "Pliki PDF pominięto — galeria karoserii przyjmuje tylko zdjęcia.", ft.Colors.ORANGE_700)
        elif not nowe:
            pokaz_komunikat(page, "Brak dostępu do wybranych plików (uprawnienia).", ft.Colors.RED_700)

    def po_wyborze(e):
        obsluzono["wartosc"] = True
        dodaj_pliki(getattr(e, "files", None))

    async def wybierz(e):
        obsluzono["wartosc"] = False
        page.zalacznik_picker.on_result = po_wyborze
        page.zalacznik_picker.update()
        try:
            wynik = await page.zalacznik_picker.pick_files(
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["jpg", "jpeg", "png", "webp"],
                allow_multiple=True,
            )
            if wynik is not None and not obsluzono["wartosc"]:
                dodaj_pliki(getattr(wynik, "files", wynik))
        except Exception as ex:
            pokaz_komunikat(page, f"Błąd wczytywania plików: {ex}", ft.Colors.RED_700)

    btn_dodaj = ft.TextButton("Wybierz zdjęcia (można zaznaczyć od razu kilka)", icon=ft.Icons.PHOTO_CAMERA, on_click=wybierz)
    kontener = ft.Column([btn_dodaj, licznik, lista_podgladow], spacing=8)
    return kontener, lambda: list(stan["pliki"])

def pokaz_podglad_zalacznika(page: ft.Page, sciezka_wzgledna, tytul="Załącznik"):
    if not sciezka_wzgledna:
        return
        
    abs_path = abs_zalacznik(sciezka_wzgledna)
    
        # 1. Obsługa plików PDF — używamy systemowego arkusza udostępniania (Share)
    # zamiast page.launch_url() na surowe URI "file://", bo Android
    # (FileUriExposedException) i iOS (piaskownica aplikacji) coraz częściej
    # trwale blokują taki bezpośredni dostęp do lokalnego pliku.
    if abs_path.lower().endswith(".pdf"):
        async def otworz_pdf():
            serwis = getattr(page, "share_service", None)
            if serwis is not None:
                try:
                    if hasattr(serwis, "share_files_async"):
                        await serwis.share_files_async([abs_path])
                    else:
                        wynik = serwis.share_files([abs_path])
                        if asyncio.iscoroutine(wynik):
                            await wynik
                    return
                except Exception:
                    pass

            # Fallback dla środowisk bez usługi Share (np. desktop)
            try:
                import pathlib
                await page.launch_url(pathlib.Path(abs_path).as_uri())
            except Exception:
                pokaz_komunikat(page, "Nie można otworzyć pliku PDF na tym urządzeniu.", ft.Colors.RED_700)

        page.run_task(otworz_pdf)
        return
        
    # 2. Pełnoekranowy podgląd zdjęcia z możliwością przybliżania (pinch-to-zoom)
    import flet as ft
    img = ft.Image(src=abs_path, fit="contain") 
    
    viewer = ft.InteractiveViewer(
        min_scale=1.0, 
        max_scale=5.0, 
        boundary_margin=ft.Margin.all(0),
        content=img
    )
    
    # Tworzymy dialog na pełen ekran
    dlg = ft.AlertDialog(
        content_padding=0,
        inset_padding=0,
        title_padding=0,
        actions_padding=0,
        bgcolor=ft.Colors.BLACK,
        content=ft.Container(
            width=10000,
            height=10000,
            content=ft.Stack([
                ft.Container(content=viewer, alignment=ft.Alignment.CENTER, expand=True),
                # Zgrabny, "pływający" przycisk zamknięcia w rogu
                ft.Container(
                    content=ft.IconButton(
                        icon=ft.Icons.CLOSE, 
                        icon_color=ft.Colors.WHITE, 
                        icon_size=30,
                        bgcolor=ft.Colors.with_opacity(0.3, ft.Colors.BLACK),
                        on_click=lambda e: zamknij_dialog(page, dlg)
                    ),
                    top=20, 
                    right=20
                )
            ])
        )
    )
    otworz_dialog(page, dlg)

def wskaznik_zalacznika(page: ft.Page, sciezka_wzgledna, tytul="Załącznik"):
    if not sciezka_wzgledna:
        return ft.Container(width=0, height=0)
        
    czy_pdf = sciezka_wzgledna.lower().endswith(".pdf")
    ikona = ft.Icons.PICTURE_AS_PDF if czy_pdf else ft.Icons.IMAGE
    kolor = ft.Colors.RED_700 if czy_pdf else ft.Colors.PRIMARY
    
    return ft.Container(
        width=28, height=28, border_radius=8,
        bgcolor=ft.Colors.with_opacity(0.12, kolor),
        alignment=ft.Alignment.CENTER,
        tooltip="Pokaż załącznik",
        content=ft.Icon(ikona, size=15, color=kolor),
        on_click=lambda e: pokaz_podglad_zalacznika(page, sciezka_wzgledna, tytul),
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


# Punkty kontrolne skali kondycji (odcienie Material 700).
_SKALA_KONDYCJI = [
    (0, (211, 47, 47)),     # RED_700    — wymaga pilnej reakcji
    (50, (245, 124, 0)),    # ORANGE_700 — wymaga uwagi
    (100, (46, 125, 50)),   # GREEN_700  — bardzo dobra
]


def kolor_kondycji_plynny(wynik):
    """Kolor wskaźnika kondycji jako PŁYNNE przejście czerwień → bursztyn →
    zieleń, zamiast trzech skokowych progów. Na kołowym wskaźniku widać dzięki
    temu różnicę między 79 a 81 punktami — przy progach obie wartości wyglądały
    identycznie po jednej i drugiej stronie granicy."""
    if wynik is None:
        return ft.Colors.ON_SURFACE_VARIANT
    try:
        w = max(0.0, min(100.0, float(wynik)))
    except (TypeError, ValueError):
        return ft.Colors.ON_SURFACE_VARIANT

    for (x0, c0), (x1, c1) in zip(_SKALA_KONDYCJI, _SKALA_KONDYCJI[1:]):
        if w <= x1:
            r, g, b = _mieszaj_kolory(c0, c1, (w - x0) / (x1 - x0))
            return f"#{r:02X}{g:02X}{b:02X}"
    r, g, b = _SKALA_KONDYCJI[-1][1]
    return f"#{r:02X}{g:02X}{b:02X}"


def gauge_kondycji(wynik, rozmiar=72, grubosc=7, rozmiar_liczby=None, pokaz_max=True):
    """Kołowy wskaźnik kondycji (0-100) — pierścień wypełniony proporcjonalnie do
    wyniku, w kolorze płynnie przechodzącym od czerwieni do zieleni, z liczbą
    w środku. Zastępuje sam tekst „82/100”: wypełnienie i barwa niosą ocenę,
    więc kafelek da się odczytać jednym spojrzeniem, bez czytania liczby."""
    kolor = kolor_kondycji_plynny(wynik)
    rozmiar_liczby = rozmiar_liczby or max(14, int(rozmiar * 0.30))

    try:
        czysty = max(0, min(100, int(round(float(wynik))))) if wynik is not None else None
    except (TypeError, ValueError):
        czysty = None

    srodek = [
        ft.Text(
            str(czysty) if czysty is not None else "—",
            size=rozmiar_liczby, weight="bold", color=kolor, no_wrap=True,
        )
    ]
    if pokaz_max and czysty is not None:
        srodek.append(ft.Text("/100", size=max(8, int(rozmiar_liczby * 0.42)),
                              color=ft.Colors.ON_SURFACE_VARIANT))

    return ft.Stack([
        ft.ProgressRing(
            value=(czysty / 100) if czysty is not None else 0.0,
            width=rozmiar, height=rozmiar, stroke_width=grubosc,
            color=kolor, stroke_cap=ft.StrokeCap.ROUND,
            bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
        ),
        ft.Container(
            width=rozmiar, height=rozmiar, alignment=ft.Alignment.CENTER,
            content=ft.Column(srodek, spacing=0, tight=True,
                              horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        ),
    ], width=rozmiar, height=rozmiar)


def tytul_sekcji(ikona, tekst, kolor=None, rozmiar=20):
    """Ikona + tytuł sekcji jako gotowa PARA kontrolek do wstawienia w ft.Row.
    Zwraca listę, bo nagłówki sekcji doklejają sobie z prawej filtry, liczniki
    i przyciski akcji."""
    kolor = kolor or ft.Colors.PRIMARY
    return [
        ft.Icon(ikona, size=rozmiar, color=kolor),
        ft.Text(tekst, size=rozmiar, weight="bold", color=kolor, expand=True),
    ]


def chipy_kwot(pary, rozmiar=12, kolor=None, odstep=8):
    """Wiersz „ikona + kwota” dla kilku kategorii naraz — zamiennik dawnych
    sklejek typu "⛽ 320 • 🛠️ 140". Każda para to (ikona, tekst); puste pary
    (None) są pomijane. Zwraca None, jeśli nie ma czego pokazać."""
    kolor = kolor or ft.Colors.ON_SURFACE_VARIANT
    kontrolki = []
    for para in pary:
        if not para:
            continue
        ikona, tekst = para
        kontrolki.append(ft.Row([
            ft.Icon(ikona, size=rozmiar + 1, color=kolor),
            ft.Text(str(tekst), size=rozmiar, color=kolor, no_wrap=True),
        ], spacing=3, tight=True))
    if not kontrolki:
        return None
    return ft.Row(kontrolki, spacing=odstep, tight=True, wrap=True)


def wskaznik_synchronizacji(page: ft.Page, auto_id, rozmiar=15):
    """Mała chmurka przy nazwie pojazdu, widoczna TYLKO wtedy, gdy ten pojazd ma
    w kolejce niewysłane zmiany. Wcześniej ten stan dało się zobaczyć dopiero po
    wejściu w ekran Współdzielenia — teraz jest widoczny od razu na starcie,
    a dotknięcie prowadzi prosto tam, gdzie można to naprawić."""
    try:
        oczekuje = db.czy_auto_oczekuje_synchronizacji(auto_id)
    except Exception:
        oczekuje = False
    if not oczekuje:
        # Zerowy kontener zamiast None — dzięki temu wywołujący może wstawić go
        # w Row bez sprawdzania i układ nie skacze przy przełączaniu pojazdów.
        return ft.Container(width=0, height=0)

    return ft.Container(
        padding=ft.Padding.only(left=4),
        tooltip="Są zmiany niewysłane do chmury — dotknij, aby zsynchronizować",
        on_click=lambda e: przejdz(page, "/wspoldzielenie"),
        content=ft.Icon(ft.Icons.CLOUD_UPLOAD_OUTLINED, size=rozmiar, color=KOLOR_STATUS["warning"]),
    )


def znacznik_wykonania(page: ft.Page, tekst="Gotowe", po_zakonczeniu=None, pauza=0.7):
    """Krótki „moment satysfakcji” wstawiany W MIEJSCE przycisku po oznaczeniu
    czegoś jako załatwione: ptaszek wskakuje ze skalą i przygasza się w miejsce
    napisu. Po `pauza` sekundach woła `po_zakonczeniu` (zwykle odświeżenie
    listy), więc animacja zdąży się pokazać, zanim wiersz zniknie."""
    pudelko = ft.Container(
        padding=ft.Padding.symmetric(horizontal=8, vertical=4),
        scale=0.5, opacity=0.0,
        animate_scale=ft.Animation(280, ft.AnimationCurve.EASE_OUT_BACK),
        animate_opacity=ft.Animation(180, ft.AnimationCurve.EASE_OUT),
        content=ft.Row([
            ft.Icon(ft.Icons.CHECK_CIRCLE, size=18, color=KOLOR_STATUS["ok"]),
            ft.Text(tekst, size=FS["label"], weight="bold", color=KOLOR_STATUS["ok"], no_wrap=True),
        ], spacing=5, tight=True),
    )

    async def _odegraj():
        # Jedna klatka zwłoki: gdyby stan docelowy ustawić od razu, Flet wysłałby
        # do klienta wyłącznie wartość końcową i animacja nie miałaby z czego wyjść.
        await asyncio.sleep(0.03)
        pudelko.scale = 1.0
        pudelko.opacity = 1.0
        try:
            page.update()
        except Exception:
            pass
        if po_zakonczeniu:
            await asyncio.sleep(pauza)
            try:
                po_zakonczeniu()
            except Exception:
                pass

    page.run_task(_odegraj)
    return pudelko


# Sylwetki nadwozia. Material nie ma osobnej ikony dla każdego typu, więc
# dobieramy najbliższe kształtem — chodzi o odróżnienie aut od siebie, nie
# o katalog techniczny.
IKONY_NADWOZIA = {
    "Hatchback": ft.Icons.DIRECTIONS_CAR,
    "Sedan": ft.Icons.TIME_TO_LEAVE,
    "Kombi": ft.Icons.DIRECTIONS_CAR_FILLED,
    "SUV / Crossover": ft.Icons.CAR_RENTAL,
    "Van / Minivan": ft.Icons.AIRPORT_SHUTTLE,
    "Coupe": ft.Icons.SPORTS_SCORE,
    "Kabriolet": ft.Icons.NO_CRASH,
    "Pickup": ft.Icons.LOCAL_SHIPPING,
    "Dostawczy": ft.Icons.LOCAL_SHIPPING,
}


def ikona_nadwozia(nadwozie):
    return ikona_z_mapy(IKONY_NADWOZIA, nadwozie, ft.Icons.DIRECTIONS_CAR)


def odznaka_pojazdu(auto, rozmiar=40, kolor_nazwa=None):
    """Krążek z sylwetką nadwozia w kolorze przypisanym do TEGO pojazdu.

    Do tej pory każde auto w selektorze wyglądało identycznie i rozróżniało się
    je dopiero po przeczytaniu nazwy. Sylwetka plus własny kolor dają rozpoznanie
    jednym spojrzeniem, a gdy typ nadwozia nie jest uzupełniony, zostaje ogólna
    ikona samochodu — czyli dokładnie to, co było.

    `auto` to wiersz/słownik z kolumnami 'nadwozie' i (opcjonalnie) 'kolor_motywu'.
    """
    def pole(nazwa):
        try:
            return auto[nazwa]
        except Exception:
            return None

    nadwozie = pole("nadwozie")
    kolor = MAPA_KOLOROW.get(kolor_nazwa or pole("kolor_motywu") or "", None)
    if kolor is None:
        kolor = ft.Colors.PRIMARY

    return ft.Container(
        width=rozmiar, height=rozmiar, border_radius=rozmiar // 2,
        bgcolor=ft.Colors.with_opacity(0.16, kolor),
        border=ft.Border.all(2, ft.Colors.with_opacity(0.45, kolor)),
        alignment=ft.Alignment.CENTER,
        tooltip=str(nadwozie) if nadwozie else None,
        content=ft.Icon(ikona_nadwozia(nadwozie), size=int(rozmiar * 0.5), color=kolor),
    )


def wskaznik_kondycji(wynik):
    """Zwraca (kolor, ikona, etykieta) dla wskaźnika kondycji pojazdu (0-100)."""
    if wynik is None:
        return ft.Colors.ON_SURFACE_VARIANT, ft.Icons.HELP_OUTLINE, "Brak danych"
    if wynik >= 80:
        return ft.Colors.GREEN_700, ft.Icons.FAVORITE, "Bardzo dobra"
    if wynik >= 50:
        return ft.Colors.ORANGE_700, ft.Icons.FAVORITE_BORDER, "Wymaga uwagi"
    return ft.Colors.RED_700, ft.Icons.HEART_BROKEN, "Wymaga pilnej reakcji"

def pokaz_panel_kondycji(page: ft.Page, state):
    """Rozpiska tego, co obniża kondycję pojazdu. Sam wynik 0-100 nie mówi, CO
    poprawić — tu każdy minus ma powód, liczbę punktów i prowadzi tam, gdzie da
    się z nim coś zrobić."""
    rozbicie = db.pobierz_rozbicie_kondycji(state.auto_id)
    wynik = rozbicie["wynik"]
    powody = rozbicie["powody"]
    kolor, ikona, etykieta = wskaznik_kondycji(wynik)

    bs = ft.BottomSheet(ft.Container(padding=ft.Padding(16, 16, 16, 8), bgcolor=ft.Colors.SURFACE))

    def idz_do(trasa):
        def handler(e):
            zamknij_dno(page, bs)
            przejdz(page, trasa)
        return handler

    naglowek = ft.Row([
        ft.Icon(ikona, size=26, color=kolor),
        ft.Column([
            ft.Text("Kondycja pojazdu", weight="bold", size=18, color=ft.Colors.PRIMARY),
            ft.Text(f"{wynik if wynik is not None else '-'}/100 · {etykieta}",
                    size=FS["label"], weight="bold", color=kolor),
        ], spacing=0, tight=True, expand=True),
    ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    # Pasek wyniku: 100 punktów startowych, z których odjęto to, co niżej.
    pasek = ft.Container(
        height=8, border_radius=RADIUS["pill"],
        bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
        content=ft.Row([
            ft.Container(
                expand=max(1, wynik or 0), height=8,
                border_radius=RADIUS["pill"],
                bgcolor=kolor_kondycji_plynny(wynik) if wynik is not None else ft.Colors.ON_SURFACE_VARIANT,
            ),
            ft.Container(expand=max(1, 100 - (wynik or 0))),
        ], spacing=0),
    )

    zawartosc = [naglowek, ft.Container(height=4), pasek, ft.Divider(height=14)]

    if not powody:
        zawartosc.append(ft.Container(
            padding=ft.Padding(12, 18, 12, 18),
            alignment=ft.Alignment.CENTER,
            content=ft.Column([
                ft.Icon(ft.Icons.TASK_ALT, size=40, color=KOLOR_STATUS["ok"]),
                ft.Text("Nic nie obniża kondycji", weight="bold"),
                ft.Text("Żaden podzespół nie jest przeterminowany, a bieżnik zamontowanych "
                        "opon mieści się w normie.",
                        size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
                        text_align=ft.TextAlign.CENTER),
            ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        ))
    else:
        suma = sum(p["punkty"] for p in powody)
        zawartosc.append(ft.Text(
            f"Odjęto łącznie {suma} pkt · {len(powody)} "
            + ("powód" if len(powody) == 1 else "powody" if len(powody) < 5 else "powodów"),
            size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
        ))

        IKONY_POWODU = {"podzespol": ft.Icons.HANDYMAN, "opony": ft.Icons.TIRE_REPAIR}
        for p in powody:
            # Największe minusy pierwsze (sortuje db), więc czerwień u góry to
            # jednocześnie „zajmij się tym najpierw”.
            kolor_kary = ft.Colors.RED_700 if p["punkty"] >= 15 else ft.Colors.ORANGE_800
            tresc = [ft.Text(p["opis"], size=FS["label"], weight="bold")]
            if p["szczegol"]:
                tresc.append(ft.Text(p["szczegol"], size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT))

            powierzchnia = powierzchnia_karty(page, "sm")
            zawartosc.append(ft.Container(
                padding=ft.Padding(12, 12, 12, 12),
                border_radius=RADIUS["md"],
                bgcolor=powierzchnia["bgcolor"],
                border=powierzchnia["border"],
                ink=bool(p["trasa"]),
                on_click=idz_do(p["trasa"]) if p["trasa"] else None,
                content=ft.Row([
                    ft.Container(
                        padding=ft.Padding(8, 4, 8, 4),
                        border_radius=RADIUS["sm"],
                        bgcolor=ft.Colors.with_opacity(0.14, kolor_kary),
                        content=ft.Text(f"−{p['punkty']} pkt", size=FS["caption"],
                                        weight="bold", color=kolor_kary),
                    ),
                    ft.Icon(ikona_z_mapy(IKONY_POWODU, p["typ"], ft.Icons.WARNING_AMBER),
                            size=18, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Column(tresc, spacing=1, tight=True, expand=True),
                    ft.Icon(ft.Icons.CHEVRON_RIGHT, size=18,
                            color=ft.Colors.ON_SURFACE_VARIANT, visible=bool(p["trasa"])),
                ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ))

        zawartosc.append(ft.Text(
            "Kondycja liczy tylko stan techniczny: podzespoły z przekroczonym interwałem "
            "i bieżnik zamontowanych opon. Dokumenty, magazyn i wydatki cykliczne jej nie ruszają.",
            size=FS["caption"], italic=True, color=ft.Colors.ON_SURFACE_VARIANT,
        ))

    bs.content.content = ft.Column(zawartosc, tight=True, spacing=8)
    otworz_dno(page, bs)


async def szybkie_dodanie_zdjecia(page: ft.Page, tabela: str, rekord_id: int, stara_sciezka, po_zapisie_callback):
    obsluzone = {"wartosc": False}

    def zapisz_wybrany_plik(plik):
        if obsluzone["wartosc"]:
            return
        obsluzone["wartosc"] = True
        nowy = db.zapisz_zalacznik(plik.path)
        db.usun_plik_zalacznika(stara_sciezka)
        with db.polacz_baze() as conn:
            conn.execute(f"UPDATE {tabela} SET zalacznik=? WHERE id=?", (nowy, rekord_id))
        pokaz_komunikat(page, "Zapisano zdjęcie!")
        po_zapisie_callback()

    def po_wyborze(e):
        pliki = getattr(e, "files", None)
        if pliki and len(pliki) > 0:
            plik = pliki[0]
            if getattr(plik, "path", None):
                zapisz_wybrany_plik(plik)
            else:
                pokaz_komunikat(page, "Brak dostępu do pliku (uprawnienia).", ft.Colors.RED_700)

    page.zalacznik_picker.on_result = po_wyborze
    page.zalacznik_picker.update() 
    
    try:
        wynik = await page.zalacznik_picker.pick_files(
            file_type=ft.FilePickerFileType.CUSTOM, 
            allowed_extensions=["jpg", "jpeg", "png", "webp", "pdf"],
            allow_multiple=False
        )
        
        if wynik is not None:
            pliki = getattr(wynik, "files", wynik)
            if isinstance(pliki, list) and len(pliki) > 0:
                plik = pliki[0]
                if getattr(plik, "path", None):
                    zapisz_wybrany_plik(plik)
                else:
                    pokaz_komunikat(page, "Brak dostępu do pliku (uprawnienia).", ft.Colors.RED_700)
    except Exception as ex:
        pokaz_komunikat(page, f"Błąd wczytywania: {ex}", ft.Colors.RED_700)

def karta_listy(tresc, kolor_paska=None, tlo=None, page=None):
    """Standardowa karta pozycji na liście, opcjonalnie z kolorowym paskiem
    statusu/priorytetu po lewej stronie. Zwraca (karta, kontener) — dokładnie
    jak dotychczas, karta.content nadal wskazuje na to samo, więc istniejące
    triki typu `karta.content.opacity = ...` działają bez zmian.
    Kontener ma już gotową (ale nieaktywną) animację naciśnięcia —
    zobacz `z_efektem_nacisniecia` niżej."""
    powierzchnia = powierzchnia_karty(page, "sm")
    tlo_finalne = tlo if tlo is not None else powierzchnia["bgcolor"]

    kontener = ft.Container(
        padding=SPACING["md"], ink=True,
        border_radius=0 if kolor_paska else RADIUS["lg"],
        bgcolor=tlo_finalne,
        expand=True if kolor_paska else None,
        scale=1.0,
        animate_scale=ft.Animation(120, ft.AnimationCurve.EASE_OUT),
        content=tresc if isinstance(tresc, ft.Control) else ft.Column(tresc, spacing=SPACING["xs"]),
    )

    if not kolor_paska:
        karta = ft.Container(
            border_radius=RADIUS["lg"],
            shadow=powierzchnia["shadow"],
            border=powierzchnia["border"],
            content=kontener,
        )
        return karta, kontener

    karta = ft.Container(
        border_radius=RADIUS["lg"], clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        shadow=powierzchnia["shadow"],
        border=powierzchnia["border"],
        content=ft.Row([ft.Container(width=4, bgcolor=kolor_paska), kontener], spacing=0),
    )
    return karta, kontener

def sparkline(wartosci, kolor=None, wysokosc=30, szerokosc=None, wypelnienie=True,
              grubosc=2, punkty_koncowe=True):
    """Mini-wykres liniowy bez osi, siatki i etykiet — „iskra” pokazująca sam
    kształt trendu obok liczby (patrz kafelek „Śr. spalanie” w kokpicie).

    `wartosci`: lista liczb w kolejności chronologicznej. Przy mniej niż 2
    sensownych punktach zwraca None — wywołujący sam decyduje, co pokazać
    zamiast wykresu. Skala Y jest dociskana do zakresu danych (z niewielkim
    zapasem), bo w sparkline liczy się różnica między punktami, a nie odległość
    od zera."""
    liczby = []
    for w in (wartosci or []):
        try:
            liczby.append(float(w))
        except (TypeError, ValueError):
            continue
    if len(liczby) < 2:
        return None

    kolor = kolor or ft.Colors.PRIMARY
    minimum, maksimum = min(liczby), max(liczby)
    # Płaska seria (same identyczne wartości) dałaby zerową wysokość wykresu —
    # wymuszamy wtedy minimalny zapas, żeby linia wylądowała pośrodku.
    zapas = max((maksimum - minimum) * 0.20, abs(maksimum) * 0.02, 0.1)

    def pusta_os():
        # Każde gniazdo osi musi dostać WŁASNĄ instancję — jednej kontrolki Flet
        # nie da się wpiąć w kilka miejsc drzewa naraz.
        return fc.ChartAxis(show_labels=False, label_size=0, title_size=0)

    return ft.Container(
        height=wysokosc, width=szerokosc,
        content=fc.LineChart(
            data_series=[
                fc.LineChartData(
                    points=[fc.LineChartDataPoint(i, w) for i, w in enumerate(liczby)],
                    stroke_width=grubosc,
                    color=kolor,
                    curved=True,
                    rounded_stroke_cap=True,
                    point=False,
                    below_line_bgcolor=ft.Colors.with_opacity(0.15, kolor) if wypelnienie else None,
                )
            ],
            left_axis=pusta_os(), right_axis=pusta_os(),
            top_axis=pusta_os(), bottom_axis=pusta_os(),
            min_x=0, max_x=len(liczby) - 1,
            min_y=minimum - zapas, max_y=maksimum + zapas,
            interactive=False,
            expand=True,
        ),
    )


def znacznik_trendu(zmiana_proc, prog=5, wzrost_zly=True, rozmiar=11):
    """Mały „chip” trendu: strzałka + procent zmiany. `wzrost_zly=True` znaczy,
    że rosnąca wartość jest zła (koszty, spalanie) i dostaje kolor czerwony.
    Zwraca ft.Row gotowy do wstawienia pod wartością na kafelku."""
    try:
        zmiana = float(zmiana_proc)
    except (TypeError, ValueError):
        return ft.Row([
            ft.Icon(ft.Icons.TRENDING_FLAT, size=13, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Text("Brak trendu", size=rozmiar, color=ft.Colors.ON_SURFACE_VARIANT, no_wrap=True),
        ], spacing=4)

    if zmiana > prog:
        ikona = ft.Icons.TRENDING_UP
        kolor = KOLOR_STATUS["critical"] if wzrost_zly else KOLOR_STATUS["ok"]
        tekst = f"+{formatuj_liczba(zmiana, 0)}%"
    elif zmiana < -prog:
        ikona = ft.Icons.TRENDING_DOWN
        kolor = KOLOR_STATUS["ok"] if wzrost_zly else KOLOR_STATUS["critical"]
        tekst = f"{formatuj_liczba(zmiana, 0)}%"
    else:
        ikona, kolor, tekst = ft.Icons.TRENDING_FLAT, KOLOR_STATUS["neutral"], "Stabilnie"

    return ft.Row([
        ft.Icon(ikona, size=13, color=kolor),
        ft.Text(tekst, size=rozmiar, color=kolor, no_wrap=True),
    ], spacing=4)


def pasek_postepu(etykieta_lewa, etykieta_prawa, procent, kolor, wysokosc=8):
    """Wspólny 'wiersz postępu': etykieta + wartość nad kolorowym ProgressBar.
    procent: 0.0-1.0 (spoza zakresu jest przycinane). Wydzielone z _pasek_porownania
    (porownanie_view.py) — używane tam i na kartach zadań serwisowych (buduj_serwis)."""
    return ft.Column([
        ft.Row([
            ft.Text(etykieta_lewa, size=12, weight="bold", expand=True, no_wrap=True),
            ft.Text(etykieta_prawa, size=12, weight="bold", color=kolor)
        ]),
        ft.ProgressBar(value=max(0.03, min(1.0, procent)), color=kolor,
                       bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE), height=wysokosc, border_radius=4)
    ], spacing=4)

def _odmiana_liczby(n, forma_1, forma_2_4, forma_pozostale):
    """Generyczna polska odmiana liczebnikowa: 1 -> forma_1, 2-4 (poza
    nastolatkami 12-14) -> forma_2_4, pozostałe -> forma_pozostale."""
    if n == 1:
        return forma_1
    ostatnia, dziesiatki = n % 10, n % 100
    if 2 <= ostatnia <= 4 and not (12 <= dziesiatki <= 14):
        return forma_2_4
    return forma_pozostale


def heatmapa_aktywnosci(page: ft.Page, daty_zdarzen, tygodnie=53):
    """Heatmapa aktywności w stylu GitHub 'contributions': siatka kwadracików
    (kolumna = tydzień, wiersz = dzień tygodnia) pokazująca, w które dni z
    ostatniego roku pojawiło się jakiekolwiek zdarzenie w dzienniku auta.
    `daty_zdarzen`: dowolna iterowalna surowych dat tekstowych (DD.MM.YYYY);
    kilka zdarzeń tego samego dnia jest sumowanych. Używane przez /timeline."""
    liczba_wg_dnia = {}
    for data_str in daty_zdarzen:
        d = parsuj_date(data_str)
        if d == datetime.min.date():
            continue
        liczba_wg_dnia[d] = liczba_wg_dnia.get(d, 0) + 1

    dzis = datetime.now().date()
    koniec = dzis + timedelta(days=(6 - dzis.weekday()))  # zaokrąglenie w górę do niedzieli
    poczatek = koniec - timedelta(days=tygodnie * 7 - 1)
    maks = max(liczba_wg_dnia.values(), default=0)

    def kolor_dnia(n):
        if n <= 0:
            return ft.Colors.with_opacity(0.06, ft.Colors.ON_SURFACE)
        if maks <= 1:
            return ft.Colors.with_opacity(0.85, ft.Colors.PRIMARY)
        udzial = n / maks
        poziom = 0.30 if udzial <= 0.25 else 0.55 if udzial <= 0.5 else 0.75 if udzial <= 0.75 else 0.95
        return ft.Colors.with_opacity(poziom, ft.Colors.PRIMARY)

    WYM = 11
    kursor = poczatek
    poprzedni_miesiac = None
    kolumny_tygodni = []
    aktywne_dni = 0

    for _ in range(tygodnie):
        if kursor.month != poprzedni_miesiac:
            naglowek = ft.Container(height=14, content=ft.Text(MIESIACE_NAZWY[kursor.month - 1][:3], size=10, color=ft.Colors.ON_SURFACE_VARIANT))
            poprzedni_miesiac = kursor.month
        else:
            naglowek = ft.Container(height=14)

        komorki = [naglowek]
        for _ in range(7):
            if kursor > dzis:
                komorki.append(ft.Container(width=WYM, height=WYM))
            else:
                n = liczba_wg_dnia.get(kursor, 0)
                if n:
                    aktywne_dni += 1
                komorki.append(ft.Container(
                    width=WYM, height=WYM, border_radius=3, bgcolor=kolor_dnia(n),
                    tooltip=f"{kursor.strftime('%d.%m.%Y')}: {n} {_odmiana_liczby(n, 'wpis', 'wpisy', 'wpisów')}" if n else kursor.strftime("%d.%m.%Y"),
                ))
            kursor += timedelta(days=1)

        kolumny_tygodni.append(ft.Column(komorki, spacing=3))

    # Odwracamy kolejność kolumn — najnowszy tydzień ma być widoczny od razu
    # (po lewej), bez przewijania w prawo, żeby go zobaczyć.
    siatka = ft.Row(list(reversed(kolumny_tygodni)), spacing=3, scroll=ft.ScrollMode.AUTO)

    def kw_legendy(poziom, kolor_bazowy=None):
        return ft.Container(width=WYM, height=WYM, border_radius=3, bgcolor=ft.Colors.with_opacity(poziom, kolor_bazowy or ft.Colors.PRIMARY))

    legenda = ft.Row([
        ft.Text("Mniej", size=10, color=ft.Colors.ON_SURFACE_VARIANT),
        kw_legendy(0.06, ft.Colors.ON_SURFACE), kw_legendy(0.30), kw_legendy(0.55), kw_legendy(0.75), kw_legendy(0.95),
        ft.Text("Więcej", size=10, color=ft.Colors.ON_SURFACE_VARIANT),
    ], spacing=4)

    opis = f"Najnowszy tydzień po lewej • {aktywne_dni} {_odmiana_liczby(aktywne_dni, 'aktywny dzień', 'aktywne dni', 'aktywnych dni')} w ciągu ostatniego roku."

    return karta_formularza(
        [siatka, legenda, ft.Text(opis, size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT)],
        "Aktywność w ciągu roku", ft.Icons.CALENDAR_MONTH, domyslnie_otwarte=True, page=page
    )

def z_efektem_nacisniecia(kontener: ft.Container, funkcja):
    """Owija istniejący handler (on_click / on_long_press) tym samym efektem
    'naciśnięcia' co `fab_animowany` — karta na chwilę się zmniejsza i wraca.
    `kontener` musi pochodzić z `karta_listy` (ma już scale/animate_scale).
    W widoku, zamiast:
        kontener.on_click = _on_click
    użyj:
        kontener.on_click = utils.z_efektem_nacisniecia(kontener, _on_click)"""
    async def wrapper(e):
        kontener.scale = 0.97
        kontener.update()
        await asyncio.sleep(0.08)
        kontener.scale = 1.0
        kontener.update()
        wynik = funkcja(e)
        if asyncio.iscoroutine(wynik):
            await wynik
    return wrapper

def z_odswiezaniem(page: ft.Page, kontrolki: list, funkcja_odswiez=None):
    """Owija kontrolki widoku w przewijaną kolumnę z przyciskiem odświeżania.
    
    Zwraca gotową kontrolkę — do użycia jako JEDYNY element w super().__init__(
    controls=[...]), bez ustawiania scroll= na samym Widoku.
    """
    spinner = ft.ProgressRing(visible=False, width=18, height=18, stroke_width=2)
    btn_odswiez = ft.IconButton(
        icon=ft.Icons.REFRESH,
        tooltip="Odśwież widok",
        icon_size=20,
    )

    async def _wykonaj_odswiezenie(e):
        spinner.visible = True
        btn_odswiez.disabled = True
        page.update()

        try:
            handler = funkcja_odswiez or (lambda ev: przejdz(page, page.route))
            if inspect.iscoroutinefunction(handler):
                await handler(e)
            else:
                handler(e)
        finally:
            spinner.visible = False
            btn_odswiez.disabled = False
            page.update()

    btn_odswiez.on_click = _wykonaj_odswiezenie

    pasek_gora = ft.Row(
        controls=[spinner, btn_odswiez],
        alignment=ft.MainAxisAlignment.END,
    )

    return ft.Column(
        controls=[pasek_gora, *kontrolki],
        spacing=15,
        scroll=ft.ScrollMode.ALWAYS,
        expand=True,
    )

def segmented_control(page: ft.Page, opcje, aktywny_idx, on_zmiana):
    """Animowany zamiennik powtarzanego wzorca 'btn_zakladki' — segmenty
    przełączają się płynną animacją koloru i skali zamiast twardego przeskoku.
    opcje: lista (etykieta, indeks) albo (etykieta, indeks, ikona) — ikona jest
    opcjonalna i pojawia się przed podpisem. on_zmiana(nowy_idx) wywoływane po
    kliknięciu."""
    segmenty = []
    for opcja in opcje:
        etykieta, idx = opcja[0], opcja[1]
        ikona = opcja[2] if len(opcja) > 2 else None
        aktywny = (idx == aktywny_idx)
        kolor_tresci = ft.Colors.ON_PRIMARY if aktywny else ft.Colors.ON_SURFACE_VARIANT
        podpis = ft.Text(etykieta, size=FS["label"], weight="bold", color=kolor_tresci)
        tresc = podpis if not ikona else ft.Row(
            [ft.Icon(ikona, size=16, color=kolor_tresci), podpis],
            spacing=6, tight=True, alignment=ft.MainAxisAlignment.CENTER,
        )
        segmenty.append(
            ft.Container(
                expand=True, height=36, alignment=ft.Alignment.CENTER,
                border_radius=RADIUS["pill"], ink=True,
                bgcolor=ft.Colors.PRIMARY if aktywny else ft.Colors.TRANSPARENT,
                animate=ft.Animation(220, ft.AnimationCurve.EASE_OUT),
                animate_scale=ft.Animation(220, ft.AnimationCurve.EASE_OUT),
                scale=1.0 if aktywny else 0.96,
                on_click=lambda e, i=idx: on_zmiana(i),
                content=tresc,
            )
        )
    return ft.Container(
        padding=4, border_radius=RADIUS["pill"], bgcolor=tlo_karty(page, poziom=2),
        content=ft.Row(segmenty, spacing=4),
    )

def fab_speed_dial(page: ft.Page, akcje, ikona_glowna=ft.Icons.ADD, tooltip="Szybkie akcje"):
    """FAB „rozwijany” (speed-dial): dotknięcie głównego przycisku odsłania
    pionowy stos mniejszych przycisków z opisanymi szybkimi akcjami, zamiast
    pojedynczego przejścia do jednego formularza. `akcje`: lista krotek
    (ikona, etykieta, on_click) — on_click przyjmuje `e` jak zwykły on_click,
    może być sync albo async. Menu zamyka się automatycznie po wybraniu
    dowolnej akcji albo ponownym dotknięciu głównego przycisku."""
    stan = {"otwarte": False}
    kontener_akcji = ft.Column(spacing=10, horizontal_alignment=ft.CrossAxisAlignment.END, visible=False)

    fab_glowny = ft.FloatingActionButton(
        icon=ikona_glowna, bgcolor=ft.Colors.PRIMARY, foreground_color=ft.Colors.ON_PRIMARY, tooltip=tooltip,
    )

    def odswiez():
        kontener_akcji.visible = stan["otwarte"]
        fab_glowny.icon = ft.Icons.CLOSE if stan["otwarte"] else ikona_glowna
        fab_glowny.bgcolor = ft.Colors.ON_SURFACE_VARIANT if stan["otwarte"] else ft.Colors.PRIMARY
        try:
            page.update()
        except Exception:
            pass

    def zamknij():
        stan["otwarte"] = False
        odswiez()

    def przelacz(e):
        stan["otwarte"] = not stan["otwarte"]
        odswiez()

    fab_glowny.on_click = przelacz

    def opakuj_akcje(akcja):
        async def wrapper(e):
            zamknij()
            wynik = akcja(e)
            if asyncio.iscoroutine(wynik):
                await wynik
        return wrapper

    wiersze = []
    for ikona, etykieta, akcja in akcje:
        wiersze.append(
            ft.Row([
                ft.Container(
                    padding=ft.Padding(10, 6, 10, 6), border_radius=8,
                    bgcolor=ft.Colors.SURFACE,
                    shadow=ft.BoxShadow(blur_radius=4, color=ft.Colors.with_opacity(0.25, ft.Colors.BLACK)),
                    content=ft.Text(etykieta, size=12, weight="bold")
                ),
                ft.FloatingActionButton(
                    icon=ikona, mini=True, bgcolor=ft.Colors.SURFACE, foreground_color=ft.Colors.PRIMARY,
                    on_click=opakuj_akcje(akcja)
                )
            ], alignment=ft.MainAxisAlignment.END, vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=10)
        )

    kontener_akcji.controls = wiersze
    return ft.Column([kontener_akcji, fab_glowny], horizontal_alignment=ft.CrossAxisAlignment.END, spacing=10, tight=True)

def fab_animowany(icon, on_click, tooltip=None):
    """FloatingActionButton z 'namacalnym' feedbackiem dotyku — lekkie
    zmniejszenie (scale) przy naciśnięciu i płynny powrót."""
    fab = ft.FloatingActionButton(
        icon=icon, bgcolor=ft.Colors.PRIMARY, foreground_color=ft.Colors.ON_PRIMARY,
        tooltip=tooltip, scale=1.0,
        animate_scale=ft.Animation(120, ft.AnimationCurve.EASE_OUT),
    )

    async def _obsluz_klik(e):
        fab.scale = 0.88
        fab.update()
        await asyncio.sleep(0.09)
        fab.scale = 1.0
        fab.update()
        if on_click:
            wynik = on_click(e)
            if asyncio.iscoroutine(wynik):
                await wynik

    fab.on_click = _obsluz_klik
    return fab

class ZaznaczanieGrupowe:
    """Mixin: obsługa zaznaczania wielu kart + appbar trybu zaznaczania.
    Klasa używająca mixinu musi ustawić self.oryginalny_appbar i self.karty_ref
    oraz zaimplementować własne potwierdz_grupowe_usuwanie (bo logika usuwania
    i ewentualne przeliczenia różnią się w zależności od widoku)."""

    def dostosuj_wysokosc_listy(self):
        """Metoda wywoływana przy zdarzeniu on_resized ekranu.
        Dynamicznie przelicza wysokość dla wszystkich list wirtualizowanych w widoku."""
        if not getattr(self, "uzyj_wirtualizacji", False):
            return
            
        try:
            # Flet View ma domyślnie właściwość .page, ale wspieramy też Twoje self._page
            strona = getattr(self, "page", None) or getattr(self, "_page", None)
            if not strona: return
            
            nowa_wysokosc = wysokosc_listy(strona)
            
            # Magia Pythona: dynamicznie szukamy atrybutów, które nazwałeś jako 'lista_kart...'
            for nazwa_atrybutu in dir(self):
                if nazwa_atrybutu.startswith("lista_kart"):
                    lista = getattr(self, nazwa_atrybutu)
                    if hasattr(lista, "height") and lista.height != nowa_wysokosc:
                        lista.height = nowa_wysokosc
                        lista.update()
        except Exception:
            pass

    def zakoncz_zaznaczanie(self, e=None):
        self.tryb_zaznaczania = False
        self.zaznaczone_id.clear()
        self.appbar = self.oryginalny_appbar
        for kontener in self.karty_ref.values():
            kontener.bgcolor = None
            kontener.border = None
        self.update()

    def aktualizuj_appbar_zaznaczania(self, dodatkowe_akcje=None):
        akcje = list(dodatkowe_akcje or [])
        akcje.append(ft.IconButton(ft.Icons.DELETE, icon_color=ft.Colors.RED_700, tooltip="Usuń zaznaczone", on_click=self.potwierdz_grupowe_usuwanie))
        akcje.append(ft.Container(width=10))
        self.appbar = ft.AppBar(
            leading=ft.IconButton(ft.Icons.CLOSE, on_click=self.zakoncz_zaznaczanie),
            title=ft.Text(f"Zaznaczono: {len(self.zaznaczone_id)}", weight="bold"),
            bgcolor=ft.Colors.with_opacity(0.2, ft.Colors.PRIMARY),
            actions=akcje
        )
        self.update()

    def zaznacz_odznacz(self, element_id, kontener):
        if element_id in self.zaznaczone_id:
            self.zaznaczone_id.remove(element_id)
            kontener.bgcolor = None
            kontener.border = None
        else:
            self.zaznaczone_id.add(element_id)
            kontener.bgcolor = ft.Colors.with_opacity(0.15, ft.Colors.PRIMARY)
            kontener.border = ft.Border.all(2, ft.Colors.PRIMARY)

        if not self.zaznaczone_id:
            self.zakoncz_zaznaczanie()
        else:
            self.aktualizuj_appbar_zaznaczania()

    def podepnij_zdarzenia_grupowe(self, kontener, element_id, callback_pojedynczy, tabela=None):
        def _on_click(e):
            if self.tryb_zaznaczania:
                if tabela is None or getattr(self, "tabela_cel", tabela) == tabela:
                    self.zaznacz_odznacz(element_id, kontener)
            else:
                callback_pojedynczy()

        def _on_long_press(e):
            if not self.tryb_zaznaczania:
                self.tryb_zaznaczania = True
                if tabela is not None:
                    self.tabela_cel = tabela
                self.zaznacz_odznacz(element_id, kontener)

        kontener.on_click = _on_click
        kontener.on_long_press = _on_long_press