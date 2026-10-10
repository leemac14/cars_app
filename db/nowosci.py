"""„Co nowego” — wydania aplikacji i to, które z nich ten telefon już pokazał; po
aktualizacji aplikacja raz otwiera niewidziane wydania (`main.py`,
`views/co_nowego_view.py`).
1. Wersja = data wydania `RRRR.M.D` (drugie tego dnia `RRRR.M.D.2`); najnowsze wydanie
JEST `WERSJA_APLIKACJI`, ta sama liczba w `pyproject.toml` (`[project] version`),
zgodności pilnuje `tests/test_co_nowego.py`. Nowa funkcja = NOWE wydanie na górze, nigdy
dopisek do istniejącego.
2. „Widziane” to jedna wersja w ustawieniach (`nowosci_widziane`), należy do urządzenia
(nie podmienia jej wczytanie kopii).
3. Telefon bez zapamiętanej wersji odgaduje ją ze schematu sprzed migracji
(`wersja_dla_schematu`); świeża instalacja nie pokazuje nic."""

from datetime import date

from .ustawienia import (
    czy_pokazywac_nowosci_po_aktualizacji,
    pobierz_widziana_wersje,
    zapisz_widziana_wersje,
)


# Wydania od NAJNOWSZEGO. Pozycja: `tytul`, `opis` (1–2 zdania językiem użytkownika, bez
# nazw z kodu i bez samotnego skrótu jednostki dystansu —
# tests/test_jednostka_dystansu.py), `ekran` (id z utils.nawigacja.EKRANY z trasą albo
# zakładką, nie akcja) i `ikona` (z ft.Icons; bez niej — ikona ekranu). Pozycja bez
# ekranu też jest kompletna.

# `schemat` tylko przy wydaniach sprzed tego ekranu: NAJNIŻSZY schemat bazy, przy którym
# telefon ma CAŁE wydanie. Nowym niepotrzebny.
NOWOSCI = [
    {"wersja": "2026.10.11", "pozycje": [
        {"tytul": "Pojazd w jednym pliku", "ikona": "SAVE_ALT",
         "opis": "W menu bocznym, w grupie Garaż, zapiszesz auto razem ze zdjęciami do jednego pliku i wczytasz je "
                 "na innym telefonie — a gdy już tam jest, zastąpisz je albo dodasz obok. Przed zapisem wybierasz, "
                 "co trafi do pliku."},
        {"tytul": "Historia dla kupującego", "ikona": "SELL", "ekran": "archiwum",
         "opis": "Przy sprzedaży auta i w Archiwum zapiszesz plik bez rozliczeń, budżetów, ewidencji przejazdów, "
                 "cen i podpisów — kupujący wczyta u siebie serwis, tankowania, przebieg i zdjęcia."},
    ]},
    {"wersja": "2026.10.8.2", "pozycje": [
        {"tytul": "Dokumenty pojazdu", "ikona": "FOLDER_SHARED", "ekran": "dokumenty",
         "opis": "Skany dowodu, polisy, umowy kupna, gwarancji i instrukcji w jednym miejscu, z datą ważności. "
                 "Polisa i przegląd dzielą datę z Kartą pojazdu, a o pozostałych przypomni dzwonek."},
        {"tytul": "Kilka plików przy wpisie", "ikona": "ATTACH_FILE", "ekran": "wizyty",
         "opis": "Do wizyty, tankowania, kosztu, wymiany, opon i części dodasz naraz paragon, fakturę i zdjęcie "
                 "wymienionej części — każdy plik z rodzajem i opisem. Plakietka na liście mówi, ile ich jest."},
    ]},
    {"wersja": "2026.10.8", "pozycje": [
        {"tytul": "Co przede mną", "ikona": "EVENT_NOTE", "ekran": "co-przede-mna",
         "opis": "Cały plan auta w jednym kalendarzu na 30, 90 albo 365 dni: terminy dokumentów, wymiany "
                 "podzespołów, wydatki cykliczne, raty, zmiana opon i końce budżetów, z zaległymi na górze. "
                 "Każdy miesiąc ma prognozę wydatków — codzienne koszty ze średniej plus to, co w nim "
                 "zaplanowane."},
        {"tytul": "Najbliższy miesiąc na kokpicie", "ikona": "SPACE_DASHBOARD", "ekran": "kokpit",
         "opis": "Kafelek „Co przede mną” pokazuje, ile wyjdzie w ciągu 30 dni i co wypada najpierw — "
                 "dodasz go w układzie kafelków. Do pełnej listy prowadzą też dzwonek i „Ile zostało do…”."},
    ]},
    {"wersja": "2026.10.6", "pozycje": [
        {"tytul": "Ewidencja przebiegu", "ikona": "ALT_ROUTE", "ekran": "ewidencja",
         "opis": "Przejazdy z datą, trasą, celem i kierowcą, oznaczone jako służbowe albo prywatne — wpisane "
                 "ręcznie, z zapisanej trasy albo prosto z kalkulatora podróży. Miesiąc pokazuje podział kosztów, "
                 "kilometrówkę i nieopisane kilometry, a raport PDF zapiszesz w układzie do VAT albo do "
                 "rozliczenia z pracodawcą."},
        {"tytul": "Ewidencja z arkusza", "ikona": "UPLOAD_FILE", "ekran": "import",
         "opis": "Ewidencję prowadzoną dotąd w arkuszu wczytasz importem CSV — wybierz typ „Przejazdy”."},
    ]},
    {"wersja": "2026.10.5.3", "pozycje": [
        {"tytul": "Leasing i kredyt", "ikona": "ACCOUNT_BALANCE", "ekran": "raty",
         "opis": "Rata ma teraz koniec i sumę: ile zostało do spłaty, kiedy ostatnia rata, wykup oraz "
                 "odsetki zapłacone i do zapłaty — z pełnym harmonogramem. Ratę z wydatków cyklicznych "
                 "przestawisz opcją „Przestaw na raty”, a „do spłaty” widać też na kokpicie, na Karcie "
                 "pojazdu, w „Ile zostało do…” i w porównaniu aut."},
    ]},
    {"wersja": "2026.10.5.2", "pozycje": [
        {"tytul": "Zaproszenie kodem QR", "ikona": "QR_CODE_2", "ekran": "wspoldzielenie",
         "opis": "Przy każdym kodzie zaproszenia jest teraz ikona QR: drugi telefon skanuje go aparatem "
                 "i otwiera aplikację z wpisanym kodem — wystarczy dotknąć „Dołącz”. Zaproszenie wyślesz "
                 "też SMS-em, a otrzymany kod albo link wkleisz przyciskiem obok pola."},
    ]},
    {"wersja": "2026.10.5", "pozycje": [
        {"tytul": "Co nowego po aktualizacji", "ikona": "NEW_RELEASES", "ekran": "ustawienia",
         "opis": "Po każdej aktualizacji aplikacja raz pokazuje tę listę, a „Pokaż” prowadzi prosto "
                 "do nowej funkcji. Na stałe leży w menu bocznym (Aplikacja › Co nowego), a wersję "
                 "i wyłącznik otwierania samego znajdziesz w Ustawieniach › O aplikacji."},
    ]},
    {"wersja": "2026.10.4", "schemat": 48, "pozycje": [
        {"tytul": "Historia cen części", "ikona": "PRICE_CHANGE", "ekran": "magazyn",
         "opis": "Pozycja magazynu pamięta sklep, link do produktu i ceny z poprzednich zakupów — "
                 "widać je na karcie razem ze znacznikiem, o ile część podrożała. W menu pozycji: "
                 "„Kupiłem ponownie” i „Historia cen”."},
        {"tytul": "Sprawdź w CEPiK", "ikona": "MANAGE_SEARCH", "ekran": "pojazd",
         "opis": "Na Karcie pojazdu, pod VIN-em: ściągawka do rządowej Historii Pojazdu. Numer "
                 "rejestracyjny, VIN i datę pierwszej rejestracji kopiujesz po kolei, a stronę "
                 "otwiera jedno dotknięcie."},
    ]},
    {"wersja": "2026.10.3", "schemat": 47, "pozycje": [
        {"tytul": "Kopia zapasowa robi się sama", "ikona": "BACKUP", "ekran": "ustawienia",
         "opis": "Co tydzień aplikacja po cichu zapisuje kopię bazy razem ze zdjęciami (na telefonie "
                 "w Dokumentach) i trzyma pięć ostatnich. Rytm, folder i listę kopii ustawisz "
                 "w Ustawieniach › Kopia zapasowa."},
        {"tytul": "Podgląd kopii przed wczytaniem", "ikona": "PREVIEW", "ekran": "ustawienia",
         "opis": "Zanim kopia nadpisze dane, okno pokazuje jej datę, pojazdy, liczbę wpisów i zdjęć "
                 "oraz to, co przepadnie z obecnej bazy. Uszkodzony plik dostaje czerwone ostrzeżenie."},
        {"tytul": "Najlepsza oferta OC/AC", "ikona": "POLICY", "ekran": "pojazd",
         "opis": "Jedna notatka przy pojeździe na cenę i towarzystwo najlepszej znalezionej oferty. "
                 "Widać ją przy terminie polisy na Karcie pojazdu, w „Ile zostało do…” "
                 "i w przypomnieniu."},
    ]},
    {"wersja": "2026.10.1", "schemat": 47, "pozycje": [
        {"tytul": "Paragon na później", "ikona": "PHOTO_CAMERA", "ekran": "do-wpisania",
         "opis": "Zdjęcie paragonu jednym dotknięciem — kafel „Paragon” na kokpicie albo „Paragon "
                 "na później” pod przyciskiem dodawania. Trafia do kolejki „Do wpisania”, a wpis "
                 "uzupełnisz w wolnej chwili, z gotową datą i zdjęciem."},
        {"tytul": "Miesiąc w pigułce", "ikona": "CALENDAR_MONTH", "ekran": "miesiac",
         "opis": "Podsumowanie miesiąca: na co poszły pieniądze, wydatki dzień po dniu i porównanie "
                 "z poprzednim miesiącem — razem z grafiką do wysłania."},
    ]},
    {"wersja": "2026.9.30", "schemat": 46, "pozycje": [
        {"tytul": "Gwarancja na naprawę", "ikona": "VERIFIED_USER", "ekran": "wizyty",
         "opis": "Przy wizycie i wpisie serwisowym pola „Gwarancja do” i „do przebiegu” ze skrótami "
                 "(rok, dwa lata…). Ile gwarancji zostało, widać na karcie wpisu, na Karcie pojazdu "
                 "i w „Ile zostało do…”, a dzwonek przypomni przed jej końcem."},
        {"tytul": "Import z innych aplikacji", "ikona": "INPUT", "ekran": "import",
         "opis": "Plik z Fuelio, Drivvo, aCar albo Simply Auto aplikacja rozpoznaje sama i rozkłada "
                 "na tankowania, inne koszty i wizyty — wszystko jednym przyciskiem."},
    ]},
    {"wersja": "2026.9.29", "schemat": 45, "pozycje": [
        {"tytul": "Ile zostało do…", "ikona": "HOURGLASS_BOTTOM", "ekran": "ile-zostalo",
         "opis": "Jedna lista odliczań: OC, przegląd, gwarancja, każdy podzespół z interwałem "
                 "i najbliższy okrągły przebieg — od najbliższego, z paskiem i datą. Trzy pierwsze "
                 "mogą stać na kokpicie jako kafelek."},
        {"tytul": "Warsztaty", "ikona": "CAR_REPAIR", "ekran": "warsztaty",
         "opis": "Karta każdego warsztatu: telefon, adres, liczba wizyt i data ostatniej, a do tego "
                 "przyciski „Zadzwoń” i „Pokaż na mapie”."},
    ]},
    {"wersja": "2026.9.27", "schemat": 45, "pozycje": [
        {"tytul": "Cena za litr przy tankowaniu", "ikona": "LOCAL_GAS_STATION", "ekran": "paliwo",
         "opis": "Formularz tankowania ma trzecie pole: cenę za litr (przy prądzie — za kWh). Wpisz "
                 "dowolne dwa, trzecie policzy się samo, a nietypowa cena dostanie ostrzeżenie."},
    ]},
    {"wersja": "2026.9.26", "schemat": 44, "pozycje": [
        {"tytul": "Kilometry albo mile", "ikona": "STRAIGHTEN", "ekran": "ustawienia",
         "opis": "Przełącznik w Ustawieniach, obok jednostki spalania: ekrany, formularze, wykresy, "
                 "raport PDF i eksport liczą dystans w wybranej jednostce. Doszły też mpg (UK) "
                 "i kWh na 100 mil."},
        {"tytul": "Szybszy kokpit", "ikona": "BOLT",
         "opis": "Kafelki, kondycja i powiadomienia liczą się raz i czekają do najbliższego zapisu, "
                 "więc powrót na kokpit trwa ułamek tego, co wcześniej."},
    ]},
    {"wersja": "2026.9.25", "schemat": 44, "pozycje": [
        {"tytul": "Saldo i „Rozliczone”", "ikona": "ACCOUNT_BALANCE_WALLET", "ekran": "podzial",
         "opis": "Podział kosztów prowadzi rachunek wspólnego auta: saldo każdej osoby, kto komu ile "
                 "oddaje (najmniej przelewów) i „Rozliczone” z historią rozliczeń."},
        {"tytul": "Przypomnienie o stanie licznika", "ikona": "SPEED", "ekran": "przebieg",
         "opis": "Po miesiącu bez wpisu z przebiegiem dzwonek prosi o odczyt licznika — prognozy "
                 "i interwały liczą się wtedy ze świeżej liczby. Próg (albo „nie przypominaj”) "
                 "zmienisz w Ustawieniach."},
        {"tytul": "Tankowanie nie do pełna", "ikona": "INFO_OUTLINE", "ekran": "paliwo",
         "opis": "Formularz ostrzega, gdy kolejne tankowanie bez „do pełna” odsunie policzenie "
                 "spalania. Wskaźnik baku dolicza też dolewki."},
    ]},
    {"wersja": "2026.9.24", "schemat": 42, "pozycje": [
        {"tytul": "Robocizna osobno od części", "ikona": "HANDYMAN", "ekran": "wizyty",
         "opis": "Przy wizycie i wpisie serwisowym dwie kwoty zamiast jednej: robocizna i części. "
                 "W Analizie widać, czy drożej wychodzi warsztat, czy części."},
        {"tytul": "Kolorowe tagi", "ikona": "LABEL", "ekran": "inne",
         "opis": "Tagi mają pełny kolor na kartach tankowań, kosztów i wizyt, w filtrze "
                 "i w wyszukiwarce, a Inne koszty dostały filtr tagów."},
    ]},
    {"wersja": "2026.9.21", "schemat": 42, "pozycje": [
        {"tytul": "Wyszukiwarka rozumie daty i pola", "ikona": "SEARCH", "ekran": "szukaj",
         "opis": "Wpisz „marzec 2026”, „ostatnie 30 dni” albo „stacja:orlen >200” — warunki łączą "
                 "się ze sobą, a ostatnie wyszukiwania czekają pod polem."},
    ]},
    {"wersja": "2026.9.20", "schemat": 42, "pozycje": [
        {"tytul": "Kafelki akcji i układanie w siatce", "ikona": "DASHBOARD_CUSTOMIZE", "ekran": "kokpit",
         "opis": "Kafelki „Tankowanie”, „Stan licznika” i inne wpisy jednym dotknięciem. Układasz je "
                 "przeciąganiem wprost w siatce, a kafelki bez treści chowają się same."},
        {"tytul": "Nowe wykresy kosztów", "ikona": "SHOW_CHART", "ekran": "statystyki",
         "opis": "W Analizie › Wykresy: koszt narastający od zakupu, cena jazdy za każdy przejechany "
                 "tysiąc w czasie i rok do roku jako dwie krzywe na jednej osi."},
    ]},
    {"wersja": "2026.9.19", "schemat": 42, "pozycje": [
        {"tytul": "Zakres czasu nad wykresami", "ikona": "DATE_RANGE", "ekran": "statystyki",
         "opis": "Chipy „3 mies. / 6 mies. / Rok / Wszystko” nad wykresami — każdy wykres pamięta "
                 "swój zakres."},
        {"tytul": "Pełniejsza kondycja auta", "ikona": "HEALTH_AND_SAFETY", "ekran": "pojazd",
         "opis": "Kondycja liczy też terminy dokumentów, pilne usterki z „Do zrobienia” i braki "
                 "w danych, a rozpiska mówi, za co odjęto punkty."},
    ]},
    {"wersja": "2026.9.17", "schemat": 42, "pozycje": [
        {"tytul": "Budżet na ostatnie 30 dni", "ikona": "SAVINGS", "ekran": "budzet",
         "opis": "Obok limitu miesięcznego i rocznego — okno 30 dni wstecz od dziś: dwa tankowania "
                 "i przegląd na przełomie miesiąca liczą się razem."},
        {"tytul": "Podgląd bez zbędnych przycisków", "ikona": "VISIBILITY", "ekran": "wspoldzielenie",
         "opis": "Przy roli „podgląd” znikają przyciski, które i tak nie mogłyby niczego zmienić — "
                 "zamiast odbijać się komunikatem."},
        {"tytul": "Podzespoły pod rodzaj napędu", "ikona": "ELECTRIC_CAR", "ekran": "serwis",
         "opis": "Nowe auto dostaje listę podzespołów dopasowaną do napędu (LPG, diesel, hybryda, "
                 "elektryk), a zmiana paliwa podpowie brakujące pozycje."},
    ]},
    {"wersja": "2026.9.15", "schemat": 41, "pozycje": [
        {"tytul": "Części z magazynu w koszcie naprawy", "ikona": "INVENTORY_2", "ekran": "magazyn",
         "opis": "Część zużyta z magazynu przy wizycie albo wpisie dolicza się do kosztu — według "
                 "ceny za sztukę albo litr, tyle, ile zeszło z półki."},
        {"tytul": "Lista zostaje w miejscu", "ikona": "SWIPE_VERTICAL",
         "opis": "Zmiana sortowania, filtra albo powrót z wpisu nie przewijają już listy na samą górę."},
    ]},
    {"wersja": "2026.9.14", "schemat": 41, "pozycje": [
        {"tytul": "Płynniejsza aplikacja", "ikona": "ANIMATION", "ekran": "ustawienia",
         "opis": "Liczby na kokpicie doliczają do wartości, zakładki przechodzą jedna w drugą, a paski "
                 "wypełniają się od zera. Wszystko wyłącza jeden przełącznik: Ustawienia › Animacje "
                 "w aplikacji."},
        {"tytul": "Miesiące na długich listach", "ikona": "CALENDAR_VIEW_MONTH", "ekran": "paliwo",
         "opis": "Tankowania, koszty, wizyty i inne długie listy mają nagłówki miesięcy z liczbą "
                 "wpisów i kwotą, a pasek nad listą mówi, który miesiąc właśnie przewijasz."},
    ]},
    {"wersja": "2026.9.8", "schemat": 41, "pozycje": [
        {"tytul": "Wyślij log", "ikona": "BUG_REPORT", "ekran": "ustawienia",
         "opis": "Gdy coś nie działa: Ustawienia › Dziennik błędów › „Wyślij log”. Plik mówi, co "
                 "poszło nie tak — bez VIN-ów, numerów polis, telefonów i kwot."},
    ]},
    {"wersja": "2026.9.7", "schemat": 40, "pozycje": [
        {"tytul": "Role przy współdzieleniu", "ikona": "GROUP", "ekran": "wspoldzielenie",
         "opis": "Zapraszając domownika, wybierasz rolę: pełna, współautor (dopisuje swoje wpisy, "
                 "cudzych nie zmienia) albo podgląd (tylko ogląda). Każda rola ma osobny kod."},
        {"tytul": "Konflikty z wyborem wersji", "ikona": "MERGE_TYPE", "ekran": "wspoldzielenie",
         "opis": "Gdy ten sam wpis zmienicie na dwóch telefonach, okno konfliktu pozwala wybrać: "
                 "„Zostaw moją wersję” albo „Weź wersję z chmury”."},
        {"tytul": "Synchronizacja sama z siebie", "ikona": "CLOUD_SYNC", "ekran": "wspoldzielenie",
         "opis": "Zmiany drugiej osoby dociągają się same: przy starcie, po powrocie do aplikacji "
                 "i co kwadrans — rytm ustawisz na ekranie współdzielenia."},
        {"tytul": "Checklisty", "ikona": "FACT_CHECK", "ekran": "checklisty",
         "opis": "Listy kontrolne wielokrotnego użytku: odhaczasz przed wyjazdem, zerujesz po "
                 "powrocie. Na start gotowa lista dziesięciu punktów (Do zrobienia › Checklisty)."},
        {"tytul": "Archiwum sprzedanych aut", "ikona": "INVENTORY", "ekran": "archiwum",
         "opis": "„Sprzedaj pojazd” zamiast usuwania: auto znika z garażu, a cała historia zostaje "
                 "w archiwum — do podglądu, eksportu albo przywrócenia."},
        {"tytul": "Sezonowa zmiana opon", "ikona": "TIRE_REPAIR", "ekran": "opony",
         "opis": "Odhaczone przypomnienie o zmianie opon samo przestawia zamontowany komplet; "
                 "Magazyn › Opony mówi, co jest na aucie i kiedy następna zmiana."},
        {"tytul": "Mandaty i opłaty drogowe", "ikona": "TOLL", "ekran": "inne",
         "opis": "Osobna kategoria innych kosztów na winiety, autostrady i mandaty — w statystykach "
                 "widać, ile kosztuje sama jazda po płatnych drogach."},
        {"tytul": "Zapisane trasy w kalkulatorze", "ikona": "ALT_ROUTE", "ekran": "kalkulator",
         "opis": "Kalkulator podróży pamięta trasy („Do teściów”): dystans, powrót, liczbę osób "
                 "i opłaty. Spalanie i ceny paliwa biorą się z bieżących tankowań."},
    ]},
]

# Wersja aplikacji = najnowsze wydanie z listy (patrz pkt 1 na górze).
WERSJA_APLIKACJI = NOWOSCI[0]["wersja"]

# Wersja starsza od każdego wydania: „pokaż wszystko”.
WERSJA_ZEROWA = "0"


def klucz_wersji(wersja) -> tuple[int, ...]:
    """„2026.10.5” -> (2026, 10, 5) — do porównań. Drugie wydanie tego samego
    dnia („2026.10.5.2”) wypada po pierwszym, bo krótsza krotka o tym samym
    początku jest mniejsza. Tekst spoza wzoru daje (0,), czyli wersję starszą
    od każdego wydania: lepiej pokazać za dużo, niż schować nowość."""
    try:
        liczby = tuple(int(czesc) for czesc in str(wersja or "").strip().split("."))
    except ValueError:
        return (0,)
    return liczby or (0,)


def data_wydania(wersja):
    """Dzień wydania odczytany z numeru wersji albo None, gdy numer nie jest datą."""
    liczby = klucz_wersji(wersja)
    if len(liczby) < 3:
        return None
    try:
        return date(liczby[0], liczby[1], liczby[2])
    except ValueError:
        return None


def wydania_po(wersja) -> list[dict]:
    """Wydania nowsze od podanej wersji, od najnowszego. None i pusty tekst
    znaczą „nic jeszcze nie widziano” — wtedy wszystkie."""
    granica = klucz_wersji(wersja)
    return [wydanie for wydanie in NOWOSCI if klucz_wersji(wydanie["wersja"]) > granica]


def wersja_dla_schematu(schemat):
    """Najnowsze wydanie, które telefon ze schematem `schemat` ma na pewno w całości,
    albo None (schemat starszy od wszystkich). W razie wątpliwości lepiej pokazać coś
    drugi raz niż schować."""
    try:
        schemat = int(schemat)
    except (TypeError, ValueError):
        return None
    for wydanie in NOWOSCI:
        prog = wydanie.get("schemat")
        if prog is not None and prog <= schemat:
            return wydanie["wersja"]
    return None


def przygotuj_nowosci_po_starcie(schemat_przed):
    """Raz przy starcie, po migracjach: telefon bez zapamiętanej wersji dostaje ją
    teraz; zwraca wersję, od której liczą się nowości. `schemat_przed` (czytany w
    `main.py` przed `init_db()`): 0 — świeża instalacja, None — nieczytelny (pokaż
    wszystko), liczba — odgadnij (`wersja_dla_schematu`)."""
    zapisana = pobierz_widziana_wersje()
    if zapisana is not None:
        return zapisana
    if schemat_przed == 0:
        wersja = WERSJA_APLIKACJI
    elif schemat_przed is None:
        wersja = WERSJA_ZEROWA
    else:
        wersja = wersja_dla_schematu(schemat_przed) or WERSJA_ZEROWA
    zapisz_widziana_wersje(wersja)
    return wersja


def niewidziane_wydania() -> list[dict]:
    """Wydania, których ten telefon jeszcze nie pokazał, od najnowszego.

    Bez zapamiętanej wersji — pusto: start ustawia ją zawsze, więc jej brak
    znaczy bazę, przez którą start nie przeszedł (testy, baza dopiero co
    założona), a tam nie ma komu niczego zgłaszać."""
    widziana = pobierz_widziana_wersje()
    if widziana is None:
        return []
    return wydania_po(widziana)


def liczba_niewidzianych_wydan():
    """Odznaka przy „Co nowego” w szufladzie."""
    return len(niewidziane_wydania())


def czy_pokazac_nowosci_po_starcie():
    """Czy start ma otworzyć „Co nowego”: jest co pokazać, a przełącznik
    w Ustawieniach na to pozwala."""
    return bool(niewidziane_wydania()) and czy_pokazywac_nowosci_po_aktualizacji()


def oznacz_nowosci_jako_widziane():
    """Ekran został otwarty — wszystko do bieżącej wersji jest widziane.
    Zapamiętana wersja nigdy się nie cofa: telefon, który miał już nowszą
    aplikację i wrócił do starszej, nie zobaczy po powrocie tych samych
    nowości jeszcze raz."""
    widziana = pobierz_widziana_wersje()
    if widziana is None or klucz_wersji(widziana) < klucz_wersji(WERSJA_APLIKACJI):
        zapisz_widziana_wersje(WERSJA_APLIKACJI)


__all__ = [
    "NOWOSCI",
    "WERSJA_APLIKACJI",
    "WERSJA_ZEROWA",
    "czy_pokazac_nowosci_po_starcie",
    "data_wydania",
    "klucz_wersji",
    "liczba_niewidzianych_wydan",
    "niewidziane_wydania",
    "oznacz_nowosci_jako_widziane",
    "przygotuj_nowosci_po_starcie",
    "wersja_dla_schematu",
    "wydania_po",
]
