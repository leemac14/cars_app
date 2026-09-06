"""Ścieżki, słowniki i stałe konfiguracyjne całej aplikacji."""

import os


STORAGE_PATH = os.environ.get("FLET_APP_STORAGE_DATA", "")

BAZA_DANYCH = os.path.join(STORAGE_PATH, 'flota_zadania.db')

FOLDER_ZALACZNIKI = os.path.join(STORAGE_PATH, "zalaczniki")

FOLDER_ODROCZONE = os.path.join(STORAGE_PATH, "zalaczniki_odroczone")

# Kosz na usunięte pojazdy: zdjęcia usuniętego auta czekają tu na przywrócenie
# albo na wygaśnięcie retencji. ŚWIADOMIE osobny folder od zalaczniki_odroczone —
# tamten czyści posprzataj_odroczone_zalaczniki() po godzinie, co zjadłoby kosz.
FOLDER_KOSZ = os.path.join(STORAGE_PATH, "kosz_zalaczniki")


# Nazwy podzespołów zakładanych nowemu pojazdowi. Bez emoji — ikonę dokłada
# interfejs, a sama nazwa trafia do bazy, do eksportu CSV/PDF i do wyszukiwarki,
# gdzie emoji tylko przeszkadzało (nie da się go wpisać, psuje sortowanie i nie
# ma glifu w czcionce raportu).
DOMYSLNE_ZADANIA = [
    "Olej silnikowy i filtr", "Filtr powietrza", "Filtr kabinowy",
    "Pasek / Łańcuch rozrządu", "Wymiana opon / Kół", "Klocki hamulcowe", "Tarcze hamulcowe"
]


PAKIETY_SERWISOWE = {
    "Przegląd olejowy": ["Olej silnikowy i filtr", "Filtr powietrza", "Filtr kabinowy"],
    "Sezonowa wymiana opon": ["Wymiana opon / Kół"],
    "Serwis hamulcowy (przód+tył)": ["Klocki hamulcowe", "Tarcze hamulcowe"],
    "Duży przegląd (rozrząd)": ["Pasek / Łańcuch rozrządu", "Olej silnikowy i filtr", "Filtr powietrza"],
}


ROK_MIN = 1900

PROG_KM_POWIADOMIEN = 1500      

PROG_DNI_POWIADOMIEN = 30       

PROG_ILOSC_MAGAZYNU_DOMYSLNY = 1.0    


WALUTY = ["PLN", "EUR", "USD", "GBP", "CZK"]

JEDNOSTKI_SPALANIA = ["l/100km", "km/l", "mpg"]

JEDNOSTKI_ZUZYCIA_EV = ["kWh/100km", "km/kWh"]


# Sylwetki nadwozia do odznaki pojazdu w selektorze. Ikony dobiera warstwa UI
# (utils.IKONY_NADWOZIA), bo db.py celowo nie zna Fleta.
TYPY_NADWOZIA = [
    "Hatchback", "Sedan", "Kombi", "SUV / Crossover",
    "Van / Minivan", "Coupe", "Kabriolet", "Pickup", "Dostawczy",
]


TYPY_PALIWA = ["Benzyna", "Diesel", "LPG", "Hybryda", "Hybryda plug-in", "Elektryczny"]


# Auta, które tankują WYŁĄCZNIE prąd.
TYPY_PALIWA_ELEKTRYCZNE = {"Elektryczny"}


# Auta z DWOMA źródłami naraz — jedyny przypadek, w którym pojedynczy wpis musi
# powiedzieć, czy to było tankowanie, czy ładowanie.
TYPY_PALIWA_DWUZRODLOWE = {"Hybryda plug-in"}


ENERGIA_PALIWO = "paliwo"

ENERGIA_PRAD = "prad"

RODZAJE_ENERGII = [ENERGIA_PALIWO, ENERGIA_PRAD]


# Wolne ładowanie (dom, praca) bywa kilka razy tańsze od szybkiego na trasie,
# więc średnią cenę za kWh liczymy dla każdego osobno.
TYPY_LADOWANIA = ["AC", "DC"]

OPISY_LADOWANIA = {"AC": "AC — wolne (dom / praca)", "DC": "DC — szybkie (trasa)"}


# Elektryk nie ma oleju ani filtra oleju, za to ma własne pozycje serwisowe.
# Bez tego każdy nowy elektryk startował z listą „Olej silnikowy i filtr”.
DOMYSLNE_ZADANIA_EV = [
    "Płyn hamulcowy", "Filtr kabinowy", "Płyn chłodzący baterii",
    "Wymiana opon / Kół", "Klocki hamulcowe", "Tarcze hamulcowe",
    "Przegląd układu wysokiego napięcia",
]


MAKS_BACKOFF_MINUT_SYNC = 60


# Retencja kosza: 0 = trzymaj bez limitu (czyszczenie wyłącznie ręczne).
DNI_KOSZA_OPCJE = [7, 30, 90, 0]

DNI_KOSZA_DOMYSLNIE = 30


PROGI_KM_OPCJE = [500, 1000, 1500, 2000, 3000, 5000]

PROGI_DNI_OPCJE = [7, 14, 30, 60, 90]


# Terminy dokumentów: (klucz ustawienia, kolumna w samochody, etykieta).
# Każdy ma WŁASNY próg powiadomień — o kończącym się OC chce się wiedzieć
# z innym wyprzedzeniem niż o dacie ważności apteczki. Brak własnego progu
# (klucz nieustawiony) = obowiązuje wspólny prog_dni_powiadomien.
TERMINY_DOKUMENTOW = [
    ("oc",         "oc_data",         "Polisa OC"),
    ("przeglad",   "przeglad_data",   "Przegląd techniczny"),
    ("ac",         "ac_data",         "Polisa AC"),
    ("assistance", "assistance_data", "Assistance"),
    ("gasnica",    "gasnica_data",    "Gaśnica"),
    ("apteczka",   "apteczka_data",   "Apteczka"),
    ("gwarancja",  "gwarancja_data",  "Gwarancja producenta"),
]

KLUCZE_TERMINOW = {k for k, _, _ in TERMINY_DOKUMENTOW}

PROGI_DNI_DOKUMENTU_OPCJE = [7, 14, 30, 60, 90, 180, 365]


PRIORYTETY_DO_ZROBIENIA = ["Wysoki", "Średni", "Niski"]

KOLEJNOSC_PRIORYTETU = {"Wysoki": 1, "Średni": 2, "Niski": 3}


KOLORY_MOTYWU = ["Indygo", "Czerwony", "Zielony", "Niebieski", "Szary", "Pomarańczowy", "Fioletowy", "Różowy", "Żółty", "Limonkowy"]


KATEGORIE_MAGAZYNU = ["Płyny eksploatacyjne", "Oleje i smary", "Żarówki i bezpieczniki", "Filtry", "Akcesoria", "Inne"]

JEDNOSTKI_MAGAZYNU = ["szt", "l", "ml", "kg", "g"]


TABELE_Z_ZALACZNIKIEM = {"tankowania", "wizyty", "inne_koszty", "zdjecia_karoserii", "historia", "zestawy_opon", "magazyn_czesci"}


# Stan licznika zapisuje się w aplikacji na cztery sposoby. Trzy z nich są
# „przy okazji” — nikt nie dodaje tankowania po to, żeby zanotować przebieg —
# ale dla historii licznika są tak samo wiarygodne jak odczyt wpisany wprost.
ZRODLA_PRZEBIEGU = {
    "odczyt": "Odczyt licznika",
    "tankowanie": "Tankowanie",
    "wizyta": "Wizyta w warsztacie",
    "serwis": "Wpis serwisowy",
}


# Podział WŁASNYCH odczytów (kolumna odczyty_przebiegu.zrodlo) — skąd dokładnie
# wziął się wpis, którego nie da się przypisać do kosztu.
ZRODLA_ODCZYTU = {
    "reczny": "Wpisany ręcznie",
    "kokpit": "Szybka aktualizacja",
    "pojazd": "Korekta w danych pojazdu",
    "import": "Import z pliku",
}

ZRODLO_ODCZYTU_DOMYSLNE = "reczny"


# Krótka notatka przy pojedynczym wpisie. Wartość to nazwa kolumny z TREŚCIĄ:
# wpisy, które takiego pola nie miały, dostały w migracji 34 własne 'notatka',
# a tam gdzie pole opisowe istnieje od dawna (wizyta, zadanie do zrobienia,
# magazyn, opony, warsztat) używamy JEGO — dokładanie drugiego pola na to samo
# rozjechałoby dane, które użytkownik już wpisał.
POLA_NOTATKI = {
    "tankowania": "notatka",
    "historia": "notatka",
    "inne_koszty": "notatka",
    "odczyty_przebiegu": "notatka",
    "wizyty": "notatki",
    "do_zrobienia": "opis",
    "magazyn_czesci": "notatki",
    "zestawy_opon": "notatki",
    "warsztaty": "notatki",
}


# Tabele, w których notatka ma WŁASNY podpis (notatka_autor + notatka_data).
# Przy współdzielonym pojeździe uwagę dopisuje zwykle ktoś inny niż autor wpisu
# i długo po jego dodaniu, więc dodane_przez/zmodyfikowane_przez tego nie oddaje.
TABELE_NOTATKI_Z_PODPISEM = {"tankowania", "historia", "inne_koszty", "odczyty_przebiegu"}


# Notatka ma być KRÓTKA — jedno zdanie kontekstu, nie dziennik. Limit trzyma
# karty na listach w ryzach i jest wspólny dla formularza i szybkiej edycji.
MAKS_DLUGOSC_NOTATKI = 200


STREFY_KAROSERII = ["Przód", "Tył", "Bok lewy", "Bok prawy", "Wnętrze / Kokpit", "Uszkodzenie / Rysa", "Inne"]

TYPY_ZDJECIA = ["Brak", "Przed naprawą", "Po naprawie"]


OSIE_MONTAZU = ["Wszystkie", "Przód", "Tył"]


KOLEJNOSC_TRYBOW_MOTYWU = ["jasny", "ciemny", "system"]


__all__ = [
    "BAZA_DANYCH",
    "DNI_KOSZA_DOMYSLNIE",
    "DNI_KOSZA_OPCJE",
    "DOMYSLNE_ZADANIA",
    "DOMYSLNE_ZADANIA_EV",
    "ENERGIA_PALIWO",
    "ENERGIA_PRAD",
    "FOLDER_KOSZ",
    "FOLDER_ODROCZONE",
    "FOLDER_ZALACZNIKI",
    "JEDNOSTKI_MAGAZYNU",
    "JEDNOSTKI_SPALANIA",
    "JEDNOSTKI_ZUZYCIA_EV",
    "KATEGORIE_MAGAZYNU",
    "KLUCZE_TERMINOW",
    "KOLEJNOSC_PRIORYTETU",
    "KOLEJNOSC_TRYBOW_MOTYWU",
    "KOLORY_MOTYWU",
    "MAKS_BACKOFF_MINUT_SYNC",
    "MAKS_DLUGOSC_NOTATKI",
    "OPISY_LADOWANIA",
    "OSIE_MONTAZU",
    "PAKIETY_SERWISOWE",
    "POLA_NOTATKI",
    "PRIORYTETY_DO_ZROBIENIA",
    "PROGI_DNI_DOKUMENTU_OPCJE",
    "PROGI_DNI_OPCJE",
    "PROGI_KM_OPCJE",
    "PROG_DNI_POWIADOMIEN",
    "PROG_ILOSC_MAGAZYNU_DOMYSLNY",
    "PROG_KM_POWIADOMIEN",
    "RODZAJE_ENERGII",
    "ROK_MIN",
    "STORAGE_PATH",
    "STREFY_KAROSERII",
    "TABELE_NOTATKI_Z_PODPISEM",
    "TABELE_Z_ZALACZNIKIEM",
    "TERMINY_DOKUMENTOW",
    "TYPY_LADOWANIA",
    "TYPY_NADWOZIA",
    "TYPY_PALIWA",
    "TYPY_PALIWA_DWUZRODLOWE",
    "TYPY_PALIWA_ELEKTRYCZNE",
    "TYPY_ZDJECIA",
    "WALUTY",
    "ZRODLA_ODCZYTU",
    "ZRODLA_PRZEBIEGU",
    "ZRODLO_ODCZYTU_DOMYSLNE",
]
