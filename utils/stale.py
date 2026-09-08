"""Paleta, tokeny wyglądu (odstępy, promienie, rozmiary) i mapy ikon."""

import flet as ft

# Skład liczby (zaokrąglenie, przecinek, separator) mieszka w warstwie danych,
# bo korzysta z niego też eksport i generator grafiki — a `db` nie ma prawa
# importować `utils`, więc wspólny rdzeń może leżeć tylko po tamtej stronie.
from db.pomocnicze import SEPARATOR_TYSIECY, liczba_na_tekst


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


# Kolor motywu pojazdu jako RGB — potrzebny poza Fletem, przy rysowaniu grafiki
# „Roku w pigułce” (Pillow nie rozumie ft.Colors). Wartości dobrane pod ciemne
# tło obrazka: te same barwy co w interfejsie, tylko w jaśniejszym wariancie,
# żeby nie ginęły na granacie.
RGB_KOLOROW_MOTYWU = {
    "Indygo": (129, 140, 248),
    "Czerwony": (248, 113, 113),
    "Zielony": (74, 222, 128),
    "Niebieski": (56, 189, 248),
    "Szary": (203, 213, 225),
    "Pomarańczowy": (251, 146, 60),
    "Fioletowy": (192, 132, 252),
    "Różowy": (244, 143, 177),
    "Żółty": (250, 204, 21),
    "Limonkowy": (163, 230, 53),
}


def rgb_koloru_motywu(nazwa_koloru):
    return RGB_KOLOROW_MOTYWU.get(str(nazwa_koloru or ""), (56, 189, 248))


def bezpieczna_nazwa_pliku(tekst, domyslna="pojazd"):
    """Nazwa pliku bez znaków, których nie zniesie żaden system plików. Ta sama
    zasada, co przy eksporcie danych — trzymamy ją tutaj, żeby korzystały z niej
    też widoki generujące własne pliki."""
    oczyszczone = "".join(z if z.isalnum() else "_" for z in str(tekst or ""))
    return oczyszczone.strip("_") or domyslna


def formatuj_liczba(wartosc, decimale=2):
    """Liczba na ekran: przecinek dziesiętny i spacja co trzy cyfry.

    Zaokrąglanie i skład tekstu robi `db.liczba_na_tekst` — to samo, z którego
    korzysta eksport i generator grafiki. Tutaj zostaje wyłącznie decyzja, co
    pokazać, gdy wartości nie ma: ZERO, bo pusty kafelek na kokpicie myli
    bardziej niż „0,00". Eksport w tej samej sytuacji zostawia pustą komórkę
    i to jest różnica zamierzona, nie przeoczenie."""
    tekst = liczba_na_tekst(wartosc, decimale, SEPARATOR_TYSIECY)
    if tekst is None:
        tekst = liczba_na_tekst(0, decimale, SEPARATOR_TYSIECY)
    return tekst


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
    "obserwacja": ft.Icons.INSIGHTS,
    "budzet": ft.Icons.SAVINGS,
    "zasieg_bak": ft.Icons.LOCAL_GAS_STATION,
    "prognoza_rok": ft.Icons.QUERY_STATS,
    "opony": ft.Icons.TIRE_REPAIR,
    "checklist": ft.Icons.FACT_CHECK,
    "oplaty_drogowe": ft.Icons.TOLL,
    "do_zrobienia": ft.Icons.CHECKLIST_RTL,
    "magazyn": ft.Icons.INVENTORY_2,
}


# Sezony zestawów opon (db.SEZONY_OPON). Ta sama para ikon obsługuje kartę
# zestawu w magazynie, kafelek kokpitu i komunikat po sezonowej zmianie, więc
# „Zimowe” wyglądają wszędzie tak samo.
IKONY_SEZONU_OPON = {
    "Letnie": ft.Icons.WB_SUNNY,
    "Zimowe": ft.Icons.AC_UNIT,
    "Całoroczne": ft.Icons.CALENDAR_MONTH,
}


KOLORY_SEZONU_OPON = {
    "Letnie": ft.Colors.AMBER_700,
    "Zimowe": ft.Colors.LIGHT_BLUE_700,
    "Całoroczne": ft.Colors.BLUE_GREY_600,
}


# Klucze ikon obserwacji przychodzą z db.obserwacje_analityczne — warstwa
# danych nie zna Fleta, więc mapowanie na konkretne ikony jest tutaj.
# Źródła stanu licznika (db.ZRODLA_PRZEBIEGU) — ikona i kolor. Ten sam zestaw
# obsługuje odznaki na kartach, punkty na wykresie i chipy w podsumowaniu, więc
# „tankowanie” wygląda wszędzie tak samo.
IKONY_ZRODEL_PRZEBIEGU = {
    "odczyt": ft.Icons.SPEED,
    "tankowanie": ft.Icons.LOCAL_GAS_STATION,
    "wizyta": ft.Icons.HOME_REPAIR_SERVICE,
    "serwis": ft.Icons.BUILD,
}


KOLORY_ZRODEL_PRZEBIEGU = {
    "odczyt": ft.Colors.BLUE_GREY_700,
    "tankowanie": ft.Colors.BLUE_700,
    "wizyta": ft.Colors.RED_700,
    "serwis": ft.Colors.ORANGE_700,
}


# Ikony podźródeł WŁASNYCH odczytów (db.ZRODLA_ODCZYTU) — dopowiadają, skąd
# wziął się wpis, którego nie da się przypisać do kosztu.
IKONY_PODZRODEL_ODCZYTU = {
    "reczny": ft.Icons.EDIT,
    "kokpit": ft.Icons.BOLT,
    "pojazd": ft.Icons.DIRECTIONS_CAR,
    "import": ft.Icons.INPUT,
}


IKONY_OBSERWACJI = {
    "budzet": ft.Icons.SAVINGS,
    "bak": ft.Icons.LOCAL_GAS_STATION,
    "spalanie": ft.Icons.SPEED,
    "prognoza": ft.Icons.QUERY_STATS,
    "miesiac": ft.Icons.CALENDAR_MONTH,
    "stacja": ft.Icons.STORE,
    "cisza": ft.Icons.NOTIFICATIONS_PAUSED,
}


# Ton obserwacji → kolor. „uwaga” to bursztyn, nie czerwień: czerwony rezerwujemy
# dla rzeczy, które już się wydarzyły (przekroczony budżet), żeby ostrzeżenie
# nie krzyczało tak samo jak fakt.
KOLORY_TONU = {
    "zly": ft.Colors.RED_700,
    "uwaga": ft.Colors.ORANGE_700,
    "dobry": ft.Colors.GREEN_700,
    "neutralny": ft.Colors.BLUE_GREY_700,
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


# Kategorie WEWNĄTRZ „Innych kosztów” (db.KATEGORIE_INNYCH_KOSZTOW). Klucz to
# etykieta, bo taka wartość leży w bazie. Kategoria spoza słownika (import CSV,
# wpis ze starszej wersji) dostaje domyślny paragon — nie znika i nie psuje listy.
IKONY_KATEGORII_INNYCH = {
    "Ogólne": ft.Icons.RECEIPT_LONG,
    "Mandaty i opłaty drogowe": ft.Icons.TOLL,
    "Ubezpieczenie": ft.Icons.SHIELD,
    "Myjnia i kosmetyka": ft.Icons.LOCAL_CAR_WASH,
    "Parking i garaż": ft.Icons.LOCAL_PARKING,
    "Wyposażenie i akcesoria": ft.Icons.SHOPPING_BAG,
    "Opłaty urzędowe": ft.Icons.ACCOUNT_BALANCE,
    "Cykliczne": ft.Icons.AUTORENEW,
}


KOLORY_KATEGORII_INNYCH = {
    "Ogólne": ft.Colors.BLUE_GREY_600,
    "Mandaty i opłaty drogowe": ft.Colors.DEEP_ORANGE_700,
    "Ubezpieczenie": ft.Colors.INDIGO_400,
    "Myjnia i kosmetyka": ft.Colors.CYAN_700,
    "Parking i garaż": ft.Colors.BLUE_GREY_500,
    "Wyposażenie i akcesoria": ft.Colors.TEAL_600,
    "Opłaty urzędowe": ft.Colors.BROWN_500,
    "Cykliczne": ft.Colors.PURPLE_300,
}


def ikona_kategorii_innych(kategoria):
    return IKONY_KATEGORII_INNYCH.get(str(kategoria or "").strip() or "Ogólne", ft.Icons.RECEIPT_LONG)


def kolor_kategorii_innych(kategoria):
    return KOLORY_KATEGORII_INNYCH.get(str(kategoria or "").strip() or "Ogólne", ft.Colors.BLUE_GREY_600)


def ikona_z_mapy(mapa, klucz, domyslna=ft.Icons.CIRCLE_OUTLINED):
    """Bezpieczne wyszukanie ikony po kluczu z warstwy danych."""
    return mapa.get(str(klucz or ""), domyslna)


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


__all__ = [
    "FS",
    "IKONY_AKTYWNOSCI",
    "IKONY_EKSPORTU",
    "IKONY_KATEGORII_INNYCH",
    "IKONY_KATEGORII_KOSZTOW",
    "IKONY_KOKPITU",
    "IKONY_NADWOZIA",
    "IKONY_OBSERWACJI",
    "IKONY_PODZRODEL_ODCZYTU",
    "IKONY_SEZONU_OPON",
    "IKONY_ZRODEL_PRZEBIEGU",
    "KOLORY_KATEGORII_INNYCH",
    "KOLORY_SEZONU_OPON",
    "KOLORY_TONU",
    "KOLORY_ZRODEL_PRZEBIEGU",
    "KOLOR_STATUS",
    "MAPA_KOLOROW",
    "RADIUS",
    "RGB_KOLOROW_MOTYWU",
    "SPACING",
    "bezpieczna_nazwa_pliku",
    "formatuj_liczba",
    "ikona_kategorii_innych",
    "ikona_z_mapy",
    "kolor_kategorii_innych",
    "rgb_koloru_motywu",
]
