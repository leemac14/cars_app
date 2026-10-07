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


# Podzespoły zakładane nowemu pojazdowi — BAZA dla każdego napędu (dodatki w
# PODZESPOLY_NAPEDU). Bez emoji: nazwa trafia do bazy, eksportu i wyszukiwarki.
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

# Klucze zapisywane w Ustawieniach. „mpg” to galon USA (3,785 l) — tak było
# od początku, więc zapisane ustawienia się nie zmieniają; „mpg UK” liczy galon
# imperialny (4,546 l), który pokazują auta z Wielkiej Brytanii.
JEDNOSTKI_SPALANIA = ["l/100km", "km/l", "mpg", "mpg UK"]

JEDNOSTKI_ZUZYCIA_EV = ["kWh/100km", "km/kWh", "kWh/100mi", "mi/kWh"]

# Podpis w liście wyboru, gdy sam klucz nie wystarcza. Przy liczbie oba galony
# piszą samo „mpg” — kto wybrał brytyjski, wie, jakie mpg czyta.
OPISY_JEDNOSTEK_ZUZYCIA = {"mpg": "mpg (USA)", "mpg UK": "mpg (UK)"}

# Dystans: baza trzyma zawsze kilometry, mile są tylko na ekranie i w plikach
# (patrz db/jednostki.py).
JEDNOSTKI_DYSTANSU = ["km", "mi"]

# Mila międzynarodowa — dokładnie tyle kilometrów.
KM_W_MILI = 1.609344

# Jednostka w ZDANIU, nie przy liczbie: „limit km” czyta się „limit kilometrów”,
# a „limit mi” — jak „mój limit”. Przy liczbie i po „/” zostaje skrót.
NAZWY_JEDNOSTEK_DYSTANSU = {
    "km": {"skrot": "km", "dopelniacz": "km", "mianownik": "Kilometry", "biernik": "kilometr",
           "dopelniacz_lp": "kilometra", "dopelniacz_pelny": "kilometrów"},
    "mi": {"skrot": "mi", "dopelniacz": "mil", "mianownik": "Mile", "biernik": "milę",
           "dopelniacz_lp": "mili", "dopelniacz_pelny": "mil"},
}

# Podpowiedź w Ustawieniach: po przełączeniu dystansu jednostka zużycia
# przechodzi na naturalną parę (można ją jeszcze zmienić przed zapisem).
PARY_JEDNOSTEK_ZUZYCIA = {
    "mi": {"l/100km": "mpg", "km/l": "mpg", "kWh/100km": "kWh/100mi", "km/kWh": "mi/kWh"},
    "km": {"mpg": "l/100km", "mpg UK": "l/100km", "kWh/100mi": "kWh/100km", "mi/kWh": "km/kWh"},
}


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


# Podzespoły zależne od napędu: DOMYSLNE_ZADANIA plus dodatki minus braki. Klucze muszą
# pokrywać CAŁE TYPY_PALIWA (tests/test_podzespoly_napedu.py) — nowy typ paliwa wymusza
# decyzję; puste {} też nią jest (gaz = benzyna z instalacją, zwykła hybryda jak
# benzyna).
PODZESPOLY_NAPEDU = {
    "Benzyna": {},
    "Diesel": {"dodaj": ["Filtr paliwa", "Filtr cząstek stałych (DPF)", "Pasek osprzętu"]},
    "LPG": {"dodaj": ["Filtr fazy lotnej", "Reduktor LPG", "Legalizacja butli LPG"]},
    "Hybryda": {},
    "Hybryda plug-in": {"dodaj": ["Płyn chłodzący baterii", "Przegląd układu wysokiego napięcia"]},
    # Elektryk nie ma oleju, filtra powietrza ani rozrządu, za to ma własne
    # pozycje. Wcześniej stała tu osobna lista DOMYSLNE_ZADANIA_EV — ta sama
    # treść, tylko przepisana w całości i bez widocznego związku z bazą.
    "Elektryczny": {
        "usun": ["Olej silnikowy i filtr", "Filtr powietrza", "Pasek / Łańcuch rozrządu"],
        "dodaj": ["Płyn hamulcowy", "Płyn chłodzący baterii", "Przegląd układu wysokiego napięcia"],
    },
}


# Interwał podpowiadany automatycznie — ŚWIADOMIE tylko CZASOWY i tylko tam, gdzie nie
# zależy od modelu (km zostawiamy użytkownikowi). Legalizacja butli LPG to prawdziwy
# TERMIN: dziesięć lat od badania.
DOMYSLNE_INTERWALY_MIESIACE = {
    "Legalizacja butli LPG": 120,
    "Płyn hamulcowy": 24,
    "Filtr kabinowy": 12,
}


MAKS_BACKOFF_MINUT_SYNC = 60


# Retencja kosza: 0 = trzymaj bez limitu (czyszczenie wyłącznie ręczne).
DNI_KOSZA_OPCJE = [7, 30, 90, 0]

DNI_KOSZA_DOMYSLNIE = 30


PROGI_KM_OPCJE = [500, 1000, 1500, 2000, 3000, 5000]

# Te same progi dla kogoś, kto liczy w milach — okrągłe mile, nie przeliczone
# kilometry („932 mi” nikt by nie wybrał). Zapis i tak idzie w km.
PROGI_MIL_OPCJE = [300, 500, 1000, 1500, 2000, 3000]

PROGI_DNI_OPCJE = [7, 14, 30, 60, 90]

# Po ilu dniach bez ŻADNEGO wpisu niosącego przebieg (tankowanie, wizyta, wpis
# serwisowy, odczyt) licznik uznajemy za nieświeży i dzwonek o niego prosi —
# a potem znowu po każdym takim samym okresie ciszy. 0 = nie przypominaj.
DNI_PRZYPOMNIENIA_O_ODCZYCIE = 30
DNI_PRZYPOMNIENIA_O_ODCZYCIE_OPCJE = [14, 30, 60, 0]


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

# Notatka „najlepsza oferta OC/AC”: kolumna `oferta_oc_ac` + `oferta_oc_ac_data`
# (ostatnia zmiana tekstu). Wspólna dla OC i AC, zostaje po odnowieniu polisy.
ETYKIETA_OFERTY_OC_AC = "Najlepsza oferta OC/AC"
KLUCZE_TERMINOW_Z_OFERTA = ("oc", "ac")
MAKS_DLUGOSC_OFERTY_OC_AC = 300

PROGI_DNI_DOKUMENTU_OPCJE = [7, 14, 30, 60, 90, 180, 365]


# Rodzaj wpisu cyklicznego (wydatki_cykliczne.typ): „wydatek” — rata, abonament albo
# czynność (rozróżnia czy_koszt); „opony” — wykonanie przestawia zamontowany komplet.
TYP_CYKLICZNY_WYDATEK = "wydatek"

TYP_CYKLICZNY_OPONY = "opony"

# Rata leasingu albo kredytu (M-22): wpis niesie UMOWĘ (kolumny z migracji 49),
# „Zapłacone” płaci KOLEJNĄ ratę harmonogramu i po ostatniej kończy wpis (db/raty.py).
# Starsza wersja aplikacji traktuje te rodzaje jak zwykły wydatek
# (rejestry._poprawny_typ).
TYP_CYKLICZNY_LEASING = "leasing"

TYP_CYKLICZNY_KREDYT = "kredyt"

TYPY_RAT = (TYP_CYKLICZNY_LEASING, TYP_CYKLICZNY_KREDYT)

# Nowe rodzaje NA KOŃCU — zasiew próbek baz (tests/probki_baz.py) bierze
# wartości od początku listy, więc odciski starszych migracji się nie zmieniają.
TYPY_CYKLICZNE = [TYP_CYKLICZNY_WYDATEK, TYP_CYKLICZNY_OPONY, TYP_CYKLICZNY_LEASING, TYP_CYKLICZNY_KREDYT]

# Raty równe (annuitetowe) — ta sama kwota co miesiąc; malejące — stała część kapitałowa
# + odsetki od salda, tylko przy kredycie i z oprocentowaniem.
RATY_ROWNE = "rowne"

RATY_MALEJACE = "malejace"

RODZAJE_RAT = (RATY_ROWNE, RATY_MALEJACE)

# 50 lat to już nie umowa na samochód, tylko literówka w liczbie rat.
MAKS_LICZBA_RAT = 600


# Sezonowa zmiana opon wypada dwa razy w roku.
OKRES_ZMIANY_OPON_DNI = 182


# Checklista przedwyjazdowa zakładana na życzenie jednym kliknięciem. Kolejność
# jest kolejnością obchodzenia auta: najpierw to, co widać z zewnątrz, potem
# płyny pod maską, na końcu papiery i wyposażenie w bagażniku.
CHECKLISTA_PRZEDWYJAZDOWA = (
    "Przed dłuższą trasą",
    [
        "Ciśnienie i stan opon (także zapasowe)",
        "Poziom oleju silnikowego",
        "Płyn do spryskiwaczy",
        "Płyn chłodniczy",
        "Płyn hamulcowy",
        "Światła — mijania, drogowe, stop, kierunkowskazy",
        "Wycieraczki",
        "Paliwo / naładowana bateria",
        "Dokumenty: dowód, OC, prawo jazdy",
        "Apteczka, trójkąt, kamizelka",
    ],
)


PRIORYTETY_DO_ZROBIENIA = ["Wysoki", "Średni", "Niski"]

KOLEJNOSC_PRIORYTETU = {"Wysoki": 1, "Średni": 2, "Niski": 3}


KOLORY_MOTYWU = ["Indygo", "Czerwony", "Zielony", "Niebieski", "Szary", "Pomarańczowy", "Fioletowy", "Różowy", "Żółty", "Limonkowy"]


# Kategorie „Innych kosztów”. W bazie (inne_koszty.kategoria) leży ETYKIETA, nie klucz
# (jak „Cykliczne”) — stare wpisy bez migracji, filtr i wyszukiwarka czytają tekst.
# Opłaty drogowe osobno, bo to koszt wymuszony trasą.
KATEGORIA_INNE_DOMYSLNA = "Ogólne"

KATEGORIA_INNE_DROGOWE = "Mandaty i opłaty drogowe"

KATEGORIE_INNYCH_KOSZTOW = [
    KATEGORIA_INNE_DOMYSLNA,
    KATEGORIA_INNE_DROGOWE,
    "Ubezpieczenie",
    "Myjnia i kosmetyka",
    "Parking i garaż",
    "Wyposażenie i akcesoria",
    "Opłaty urzędowe",
    "Cykliczne",
]


KATEGORIE_MAGAZYNU = ["Płyny eksploatacyjne", "Oleje i smary", "Żarówki i bezpieczniki", "Filtry", "Akcesoria", "Inne"]

JEDNOSTKI_MAGAZYNU = ["szt", "l", "ml", "kg", "g"]


TABELE_Z_ZALACZNIKIEM = {"tankowania", "wizyty", "inne_koszty", "zdjecia_karoserii", "historia", "zestawy_opon", "magazyn_czesci",
                         "szkice_wpisow"}


# Tabele z `data_iso` (RRRR-MM-DD, migracja 44) obok `data` (DD.MM.RRRR). Wartość zawsze
# `date.na_iso(data)`, przy KAŻDYM zapisie daty: jawnie w SQL albo `uzupelnij_date_iso`
# (wiersz jako słownik).
TABELE_Z_DATA_ISO = (
    "tankowania", "inne_koszty", "wizyty", "historia",
    "odczyty_przebiegu", "rozliczenia", "zdjecia_karoserii", "zadania",
    "szkice_wpisow", "ceny_czesci", "przejazdy",
)


# Pięć źródeł stanu licznika; cztery „przy okazji”, ale dla historii tak samo
# wiarygodne. Przejazd z ewidencji tylko z wpisanym licznikiem (przejazdy.licznik — stan
# PO przejeździe).
ZRODLA_PRZEBIEGU = {
    "odczyt": "Odczyt licznika",
    "tankowanie": "Tankowanie",
    "wizyta": "Wizyta w warsztacie",
    "serwis": "Wpis serwisowy",
    "przejazd": "Przejazd z ewidencji",
}


# Podział WŁASNYCH odczytów (kolumna odczyty_przebiegu.zrodlo) — skąd dokładnie
# wziął się wpis, którego nie da się przypisać do kosztu.
ZRODLA_ODCZYTU = {
    "reczny": "Wpisany ręcznie",
    "kokpit": "Szybka aktualizacja",
    "pojazd": "Korekta w danych pojazdu",
    "import": "Import z pliku",
    # Stan na ostatni dzień miesiąca zapisany przy „Zamknij miesiąc”
    # w ewidencji przebiegu — tego wymaga ewidencja do VAT.
    "ewidencja": "Koniec miesiąca w ewidencji",
}

ZRODLO_ODCZYTU_DOMYSLNE = "reczny"


# Notatka przy wpisie: wartość to kolumna z TREŚCIĄ — 'notatka' z migracji 34 albo
# istniejące pole opisu (wizyta, zadanie, magazyn, opony, warsztat).
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
    "przejazdy": "notatka",
}


# Tabele, w których notatka ma WŁASNY podpis (notatka_autor + notatka_data).
# Przy współdzielonym pojeździe uwagę dopisuje zwykle ktoś inny niż autor wpisu
# i długo po jego dodaniu, więc dodane_przez/zmodyfikowane_przez tego nie oddaje.
TABELE_NOTATKI_Z_PODPISEM = {"tankowania", "historia", "inne_koszty", "odczyty_przebiegu", "przejazdy"}


# Notatka ma być KRÓTKA — jedno zdanie kontekstu, nie dziennik. Limit trzyma
# karty na listach w ryzach i jest wspólny dla formularza i szybkiej edycji.
MAKS_DLUGOSC_NOTATKI = 200


STREFY_KAROSERII = ["Przód", "Tył", "Bok lewy", "Bok prawy", "Wnętrze / Kokpit", "Uszkodzenie / Rysa", "Inne"]

TYPY_ZDJECIA = ["Brak", "Przed naprawą", "Po naprawie"]


OSIE_MONTAZU = ["Wszystkie", "Przód", "Tył"]


# Sezony zestawów opon. Mieszkały dotąd wyłącznie w views/garage_view.py, ale od
# kiedy przypomnienie o sezonowej zmianie samo przełącza zamontowany komplet
# (patrz przelacz_zestaw_sezonowy), potrzebuje ich także warstwa danych.
SEZONY_OPON = ["Letnie", "Zimowe", "Całoroczne"]


# Tylko te dwa sezony da się wymieniać między sobą — „Całoroczne” z definicji
# nie mają pary, więc nie biorą udziału w automatycznym przełączaniu.
SEZONY_PRZELACZALNE = ("Letnie", "Zimowe")


# Miesiące (1-12), w których domyślnie jeździ się na zimówkach. Używane tylko
# wtedy, gdy nie ma zamontowanego zestawu i nie ma z czego wywnioskować kierunku
# zmiany — w Polsce zmiana wypada mniej więcej w okolicach października i marca.
MIESIACE_ZIMOWE = {11, 12, 1, 2, 3}


# Status pojazdu (samochody.status). Sprzedane NIE jest usuwane ani w koszu: znika z
# przełącznika i showroomu, historia zostaje (Archiwum). Domyślnie „aktywny”; filtrują
# tylko miejsca wypisujące garaż.
STATUS_POJAZDU_AKTYWNY = "aktywny"

STATUS_POJAZDU_SPRZEDANY = "sprzedany"


KOLEJNOSC_TRYBOW_MOTYWU = ["jasny", "ciemny", "system"]


# Ewidencja przebiegu (N-01): PO CO się ją prowadzi — decyduje o kolejności ekranu i
# proponowanym układzie raportu. Ustawienie pojazdu NA TYM telefonie (db/ustawienia.py,
# _klucz_ewidencji).
TRYBY_EWIDENCJI = {
    "podzial": "Podział prywatne / służbowe",
    "kilometrowka": "Kilometrówka — auto prywatne w pracy",
    "vat": "Auto firmowe — odliczenie 100% VAT",
}

TRYB_EWIDENCJI_DOMYSLNY = "podzial"


__all__ = [
    "TRYBY_EWIDENCJI",
    "TRYB_EWIDENCJI_DOMYSLNY",
    "BAZA_DANYCH",
    "CHECKLISTA_PRZEDWYJAZDOWA",
    "DNI_KOSZA_DOMYSLNIE",
    "DNI_KOSZA_OPCJE",
    "DNI_PRZYPOMNIENIA_O_ODCZYCIE",
    "DNI_PRZYPOMNIENIA_O_ODCZYCIE_OPCJE",
    "DOMYSLNE_INTERWALY_MIESIACE",
    "DOMYSLNE_ZADANIA",
    "ENERGIA_PALIWO",
    "ENERGIA_PRAD",
    "ETYKIETA_OFERTY_OC_AC",
    "FOLDER_KOSZ",
    "FOLDER_ODROCZONE",
    "FOLDER_ZALACZNIKI",
    "JEDNOSTKI_MAGAZYNU",
    "JEDNOSTKI_SPALANIA",
    "JEDNOSTKI_ZUZYCIA_EV",
    "KATEGORIA_INNE_DOMYSLNA",
    "KATEGORIA_INNE_DROGOWE",
    "KATEGORIE_INNYCH_KOSZTOW",
    "KATEGORIE_MAGAZYNU",
    "KLUCZE_TERMINOW",
    "KLUCZE_TERMINOW_Z_OFERTA",
    "KOLEJNOSC_PRIORYTETU",
    "KOLEJNOSC_TRYBOW_MOTYWU",
    "KOLORY_MOTYWU",
    "MAKS_BACKOFF_MINUT_SYNC",
    "MAKS_DLUGOSC_NOTATKI",
    "MAKS_DLUGOSC_OFERTY_OC_AC",
    "MIESIACE_ZIMOWE",
    "OKRES_ZMIANY_OPON_DNI",
    "OPISY_LADOWANIA",
    "OSIE_MONTAZU",
    "PAKIETY_SERWISOWE",
    "PODZESPOLY_NAPEDU",
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
    "SEZONY_OPON",
    "SEZONY_PRZELACZALNE",
    "STATUS_POJAZDU_AKTYWNY",
    "STATUS_POJAZDU_SPRZEDANY",
    "STORAGE_PATH",
    "STREFY_KAROSERII",
    "TABELE_NOTATKI_Z_PODPISEM",
    "TABELE_Z_DATA_ISO",
    "TABELE_Z_ZALACZNIKIEM",
    "TERMINY_DOKUMENTOW",
    "TYPY_LADOWANIA",
    "TYPY_NADWOZIA",
    "TYPY_PALIWA",
    "TYPY_PALIWA_DWUZRODLOWE",
    "TYPY_PALIWA_ELEKTRYCZNE",
    "TYPY_CYKLICZNE",
    "TYPY_RAT",
    "TYPY_ZDJECIA",
    "TYP_CYKLICZNY_KREDYT",
    "TYP_CYKLICZNY_LEASING",
    "TYP_CYKLICZNY_OPONY",
    "TYP_CYKLICZNY_WYDATEK",
    "MAKS_LICZBA_RAT",
    "RATY_MALEJACE",
    "RATY_ROWNE",
    "RODZAJE_RAT",
    "WALUTY",
    "ZRODLA_ODCZYTU",
    "ZRODLA_PRZEBIEGU",
    "ZRODLO_ODCZYTU_DOMYSLNE",
    "JEDNOSTKI_DYSTANSU",
    "KM_W_MILI",
    "NAZWY_JEDNOSTEK_DYSTANSU",
    "OPISY_JEDNOSTEK_ZUZYCIA",
    "PARY_JEDNOSTEK_ZUZYCIA",
    "PROGI_MIL_OPCJE",
]
