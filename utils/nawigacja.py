"""Rejestr ekranów, szuflada, skróty i paski nawigacji."""

import db
import flet as ft
import inspect

from .stale import FS, RADIUS
from .format import bez_ogonkow
from .wyglad import dol_bezpieczny, pasek_przewijany, pasek_zawijany, tlo_karty
from .dialogi import otworz_dialog, otworz_dno, pokaz_komunikat, pokaz_menu_grupowane, przejdz, zamknij_dialog, zamknij_dno
from .zalaczniki import abs_zalacznik
from .pojazd import ikona_nadwozia, sprzedaj_auto, usun_auto
from .powiadomienia import pokaz_panel_wydatkow_cyklicznych, przycisk_dzwonka


# ==================== REJESTR EKRANÓW I NAWIGACJA BOCZNA ====================
# Aplikacja urosła do kilkudziesięciu ekranów i największym problemem przestało
# być „czy da się to zrobić”, a stało się „gdzie to było”. Rok w pigułce dało
# się otworzyć z menu ⋮ i z kafelka w statystykach, historię przebiegu z karty
# pojazdu i z dialogu przebiegu — czyli za każdym razem skądinąd.
#
# Dlatego jest JEDEN spis ekranów. Napędza on wszystko naraz:
#   • szufladę boczną (utils.zbuduj_szuflade),
#   • kafelki skrótów na Kokpicie i paski sekcji w zakładkach,
#   • wyszukiwarkę, która od teraz znajduje nie tylko wpisy, ale i ekrany,
#   • statystykę „ostatnio używane” (db.zanotuj_uzycie_ekranu).
# Dodanie ekranu w jednym miejscu wystawia go od razu we wszystkich czterech.

GRUPY_EKRANOW = [
    # „Start” to grupa jednoelementowa i celowo bez nagłówka w szufladzie —
    # Kokpit jest punktem wyjścia, a nie jedną z pozycji w kategorii.
    {"id": "start",     "tytul": "Start",            "ikona": ft.Icons.SPACE_DASHBOARD, "kolor": ft.Colors.PRIMARY},
    {"id": "pojazd",    "tytul": "Pojazd",           "ikona": ft.Icons.DIRECTIONS_CAR, "kolor": ft.Colors.INDIGO_400},
    {"id": "serwis",    "tytul": "Serwis i zadania", "ikona": ft.Icons.BUILD_CIRCLE,   "kolor": ft.Colors.ORANGE_700},
    {"id": "koszty",    "tytul": "Koszty",           "ikona": ft.Icons.PAYMENTS,       "kolor": ft.Colors.GREEN_700},
    {"id": "analiza",   "tytul": "Analiza",          "ikona": ft.Icons.INSIGHTS,       "kolor": ft.Colors.PURPLE_400},
    {"id": "garaz",     "tytul": "Garaż i osoby",    "ikona": ft.Icons.GARAGE,         "kolor": ft.Colors.TEAL_600},
    {"id": "dane",      "tytul": "Dane i kopie",     "ikona": ft.Icons.FOLDER_COPY,    "kolor": ft.Colors.BLUE_GREY_500},
    {"id": "aplikacja", "tytul": "Aplikacja",        "ikona": ft.Icons.TUNE,           "kolor": ft.Colors.BLUE_GREY_500},
]


GRUPY_WG_ID = {g["id"]: g for g in GRUPY_EKRANOW}


# Klucze pozycji:
#   id        — stały identyfikator (trafia do bazy: skróty, ostatnio używane)
#   trasa     — dokąd prowadzi; brak trasy oznacza zakładkę główną albo akcję
#   zakladka / podzakladka — ekran mieszkający w zakładce ekranu głównego
#   akcja     — nazwa akcji wymagającej kontekstu (eksport bazy, motyw, ...)
#   slowa     — dodatkowe słowa, po których ekran ma być do znalezienia
EKRANY = [
    {"id": "kokpit", "tytul": "Kokpit", "opis": "Skróty, widżety i stan pojazdu",
     "ikona": ft.Icons.SPACE_DASHBOARD, "grupa": "start", "zakladka": 0,
     "slowa": ["start", "pulpit", "dashboard", "ekran główny", "widżety"]},
    {"id": "pojazd", "tytul": "Karta pojazdu", "opis": "Terminy, wartość, ubezpieczenie, ściągawka",
     "ikona": ft.Icons.BADGE, "grupa": "pojazd", "trasa": "/pojazd",
     "slowa": ["oc", "ac", "przegląd", "polisa", "vin", "dane techniczne", "assistance", "tablica", "ubezpieczenie"]},
    {"id": "przebieg", "tytul": "Historia przebiegu", "opis": "Wszystkie odczyty licznika i ich źródła",
     "ikona": ft.Icons.SPEED, "grupa": "pojazd", "trasa": "/przebieg",
     "slowa": ["licznik", "kilometry", "km", "odczyt", "stan licznika", "przebiegi"]},
    {"id": "karoseria", "tytul": "Karoseria", "opis": "Zdjęcia lakieru, rys i uszkodzeń",
     "ikona": ft.Icons.PHOTO_CAMERA, "grupa": "pojazd", "trasa": "/karoseria",
     "slowa": ["lakier", "rysy", "wgniecenia", "zdjęcia", "szkody", "blacharka"]},
    {"id": "timeline", "tytul": "Dziennik życia auta", "opis": "Oś czasu wszystkich zdarzeń",
     "ikona": ft.Icons.TIMELINE, "grupa": "pojazd", "trasa": "/timeline",
     "slowa": ["oś czasu", "kronika", "historia", "zdarzenia", "chronologia"]},

    {"id": "serwis", "tytul": "Podzespoły i interwały", "opis": "Olej, filtry, rozrząd — co i kiedy wymienić",
     "ikona": ft.Icons.HANDYMAN, "grupa": "serwis", "zakladka": 1,
     "slowa": ["części", "wymiana", "interwał", "olej", "filtr", "rozrząd", "klocki", "serwis"]},
    {"id": "wizyty", "tytul": "Wizyty w warsztacie", "opis": "Zbiorcze naprawy i przeglądy",
     "ikona": ft.Icons.HOME_REPAIR_SERVICE, "grupa": "serwis", "trasa": "/wizyty",
     "slowa": ["warsztat", "mechanik", "naprawa", "przegląd", "wizyta"]},
    {"id": "do-zrobienia", "tytul": "Do zrobienia", "opis": "Lista rzeczy do załatwienia w aucie",
     "ikona": ft.Icons.CHECKLIST_RTL, "grupa": "serwis", "trasa": "/do-zrobienia",
     "stan": {"do_zrobienia_podzakladka": 0},
     "slowa": ["todo", "zadania", "lista", "plan", "przypomnienia"]},
    # Checklisty i opony mieszkają w PODZAKŁADKACH innych ekranów, więc bez
    # własnego wpisu nie dało się do nich trafić ani z szuflady, ani
    # z wyszukiwarki — a to osobne rzeczy, nie warianty tego samego widoku.
    {"id": "checklisty", "tytul": "Checklisty", "opis": "Listy kontrolne odhaczane przed wyjazdem",
     "ikona": ft.Icons.FACT_CHECK, "grupa": "serwis", "trasa": "/do-zrobienia",
     "stan": {"do_zrobienia_podzakladka": 1},
     "slowa": ["checklista", "przed trasą", "przed wyjazdem", "lista kontrolna", "sprawdzić"]},
    # Magazyn stoi przy serwisie, a nie przy pojeździe: części schodzą z półki
    # na wizytach (patrz tabela wizyta_czesci_magazynu), więc myśli się o nim
    # razem z naprawami, a nie razem z dokumentami auta.
    {"id": "magazyn", "tytul": "Magazyn", "opis": "Opony, części i płyny na półce",
     "ikona": ft.Icons.INVENTORY_2, "grupa": "serwis", "trasa": "/magazyn",
     "stan": {"magazyn_zakladka": 1},
     "slowa": ["części", "płyny", "olej", "zapas", "półka", "stan magazynowy"]},
    {"id": "opony", "tytul": "Opony", "opis": "Zestawy, bieżnik i sezonowa zmiana",
     "ikona": ft.Icons.TIRE_REPAIR, "grupa": "serwis", "trasa": "/magazyn",
     "stan": {"magazyn_zakladka": 0},
     "slowa": ["opony", "koła", "zimowe", "letnie", "bieżnik", "felgi", "sezon", "wymiana opon"]},

    {"id": "paliwo", "tytul": "Tankowania", "opis": "Paliwo, prąd i spalanie",
     "ikona": ft.Icons.LOCAL_GAS_STATION, "grupa": "koszty", "zakladka": 2, "podzakladka": 0,
     "slowa": ["paliwo", "benzyna", "diesel", "lpg", "prąd", "ładowanie", "stacja", "spalanie", "litry"]},
    {"id": "inne", "tytul": "Inne koszty", "opis": "Myjnia, autostrady, parkingi, opłaty",
     "ikona": ft.Icons.RECEIPT_LONG, "grupa": "koszty", "zakladka": 2, "podzakladka": 1,
     "slowa": ["opłaty", "myjnia", "autostrada", "parking", "mandat", "ubezpieczenie", "wydatki"]},
    {"id": "budzet", "tytul": "Budżet pojazdu", "opis": "Limity na paliwo, serwis i wszystko razem",
     "ikona": ft.Icons.SAVINGS, "grupa": "koszty", "trasa": "/budzet",
     "slowa": ["limit", "budżet", "oszczędzanie", "próg", "wydatki miesięczne"]},
    {"id": "podzial", "tytul": "Podział kosztów", "opis": "Kto ile wydał na wspólne auto",
     "ikona": ft.Icons.CALCULATE, "grupa": "koszty", "trasa": "/podzial",
     "slowa": ["rozliczenie", "wspólne", "składka", "kto płacił", "dzielenie"]},
    {"id": "kalkulator", "tytul": "Kalkulator podróży", "opis": "Policz koszt trasy przed wyjazdem",
     "ikona": ft.Icons.MAP, "grupa": "koszty", "trasa": "/kalkulator",
     "slowa": ["trasa", "wyjazd", "podróż", "ile spali", "koszt przejazdu"]},

    {"id": "statystyki", "tytul": "Statystyki", "opis": "Liczby, wykresy, obserwacje i tabele",
     "ikona": ft.Icons.PIE_CHART, "grupa": "analiza", "zakladka": 3,
     "slowa": ["wykres", "średnie", "podsumowanie", "liczby", "tabele", "analiza", "trend", "obserwacje"]},
    {"id": "rok", "tytul": "Rok w pigułce", "opis": "Podsumowanie roku i grafika do wysłania",
     "ikona": ft.Icons.AUTO_AWESOME, "grupa": "analiza", "trasa": "/rok",
     "slowa": ["podsumowanie roku", "rok", "wrapped", "grafika", "roczne", "raport roczny"]},
    {"id": "porownanie", "tytul": "Porównaj pojazdy", "opis": "Koszty i spalanie obok siebie",
     "ikona": ft.Icons.COMPARE_ARROWS, "grupa": "analiza", "trasa": "/porownanie",
     "slowa": ["porównanie", "które auto", "zestawienie", "werdykt", "radar"]},

    {"id": "auto-nowy", "tytul": "Dodaj pojazd", "opis": "Nowe auto w garażu",
     "ikona": ft.Icons.ADD_CIRCLE_OUTLINE, "grupa": "garaz", "trasa": "/auto/nowy",
     "kolor": ft.Colors.GREEN_700, "wymaga_pojazdu": False,
     "slowa": ["nowe auto", "dodaj samochód", "garaż"]},
    {"id": "auto-edytuj", "tytul": "Edytuj dane pojazdu", "opis": "Zmień nazwę, zdjęcie, terminy i dane techniczne",
     "ikona": ft.Icons.EDIT_NOTE, "grupa": "garaz", "akcja": "edytuj_pojazd",
     "slowa": ["edycja", "zmień dane", "popraw", "nazwa auta", "zdjęcie auta"]},
    {"id": "wspoldzielenie", "tytul": "Współdziel pojazd", "opis": "Zaproś domownika i synchronizuj dane",
     "ikona": ft.Icons.PEOPLE, "grupa": "garaz", "trasa": "/wspoldzielenie",
     "slowa": ["udostępnij", "rodzina", "partner", "synchronizacja", "chmura", "wspólne auto"]},
    {"id": "archiwum", "tytul": "Archiwum pojazdów", "opis": "Sprzedane auta z pełną historią",
     "ikona": ft.Icons.INVENTORY, "grupa": "garaz", "trasa": "/archiwum", "wymaga_pojazdu": False,
     "slowa": ["sprzedane", "archiwum", "byłe auta", "poprzedni samochód", "historia sprzedanych"]},
    {"id": "kosz", "tytul": "Kosz", "opis": "Przywróć usunięty pojazd z historią",
     "ikona": ft.Icons.DELETE_SWEEP, "grupa": "garaz", "trasa": "/kosz", "wymaga_pojazdu": False,
     "slowa": ["usunięte", "przywróć", "odzyskaj", "kosz"]},
    {"id": "auto-sprzedaj", "tytul": "Sprzedaj pojazd", "opis": "Auto znika z garażu, historia zostaje",
     "ikona": ft.Icons.SELL, "grupa": "garaz", "akcja": "sprzedaj_pojazd",
     "slowa": ["sprzedaż", "sprzedane", "zbyłem", "oddałem auto", "archiwizuj"]},
    {"id": "auto-usun", "tytul": "Usuń pojazd", "opis": "Bieżące auto trafi do kosza",
     "ikona": ft.Icons.DELETE_OUTLINE, "grupa": "garaz", "akcja": "usun_pojazd",
     "kolor": ft.Colors.RED_700, "slowa": ["skasuj auto", "wyrzuć pojazd"]},

    {"id": "kopia", "tytul": "Kopia zapasowa bazy", "opis": "Zapisz całą bazę razem ze zdjęciami",
     "ikona": ft.Icons.BACKUP, "grupa": "dane", "akcja": "kopia", "wymaga_pojazdu": False,
     "slowa": ["backup", "zapisz bazę", "archiwum", "kopia"]},
    {"id": "wczytaj", "tytul": "Wczytaj kopię bazy", "opis": "Podmienia WSZYSTKIE dane w aplikacji",
     "ikona": ft.Icons.SETTINGS_BACKUP_RESTORE, "grupa": "dane", "akcja": "wczytaj",
     "kolor": ft.Colors.ORANGE_800, "wymaga_pojazdu": False,
     "slowa": ["przywróć bazę", "restore", "odtwórz", "wgraj kopię"]},
    {"id": "eksport", "tytul": "Eksport danych (CSV/PDF)", "opis": "Raport z wybranego okresu do wysłania",
     "ikona": ft.Icons.SUMMARIZE, "grupa": "dane", "trasa": "/eksport",
     "slowa": ["csv", "pdf", "raport", "wyślij", "arkusz", "excel"]},
    {"id": "import", "tytul": "Import z pliku CSV", "opis": "Tankowania, koszty i odczyty z arkusza",
     "ikona": ft.Icons.INPUT, "grupa": "dane", "trasa": "/import",
     "slowa": ["wczytaj csv", "arkusz", "excel", "migracja", "przenieś dane"]},

    {"id": "cykliczne", "tytul": "Wydatki cykliczne", "opis": "Raty, abonamenty, powtarzalne czynności",
     "ikona": ft.Icons.AUTORENEW, "grupa": "aplikacja", "akcja": "cykliczne",
     "slowa": ["abonament", "rata", "co miesiąc", "powtarzalne", "przypomnienie"]},
    {"id": "szukaj", "tytul": "Szukaj we wszystkim", "opis": "Wpisy, notatki, kwoty i ekrany",
     "ikona": ft.Icons.SEARCH, "grupa": "aplikacja", "trasa": "/szukaj",
     "slowa": ["wyszukiwarka", "znajdź", "szukaj"]},
    {"id": "ustawienia", "tytul": "Ustawienia", "opis": "Waluta, progi powiadomień, kokpit, kosz",
     "ikona": ft.Icons.SETTINGS, "grupa": "aplikacja", "trasa": "/ustawienia", "wymaga_pojazdu": False,
     "slowa": ["konfiguracja", "opcje", "waluta", "progi", "powiadomienia", "preferencje"]},
    {"id": "motyw", "tytul": "Motyw aplikacji", "opis": "Jasny, ciemny albo według telefonu",
     "ikona": ft.Icons.BRIGHTNESS_AUTO, "grupa": "aplikacja", "akcja": "motyw", "wymaga_pojazdu": False,
     "slowa": ["ciemny", "jasny", "tryb nocny", "wygląd", "kolory"]},
]


EKRANY_WG_ID = {e["id"]: e for e in EKRANY}


# (zakładka, podzakładka) -> id ekranu. Dzięki temu szuflada potrafi podświetlić
# miejsce, w którym użytkownik właśnie stoi, także wtedy, gdy adres to zwykłe "/".
EKRAN_ZAKLADKI = {}

for _e in EKRANY:
    if _e.get("zakladka") is not None:
        EKRAN_ZAKLADKI[(int(_e["zakladka"]), int(_e.get("podzakladka") or 0))] = _e["id"]


# Pierwszy segment adresu -> id ekranu. Adresy wieloczłonowe (np. /auto/nowy)
# są pomijane: to formularze, a nie miejsca, do których się wraca.
EKRANY_WG_SEGMENTU = {}

for _e in EKRANY:
    _trasa = _e.get("trasa")
    if not _trasa:
        continue
    _segmenty = [s for s in _trasa.split("/") if s]
    if len(_segmenty) == 1:
        EKRANY_WG_SEGMENTU.setdefault(_segmenty[0], _e["id"])


# Ekrany rozpoznawane po adresie ORAZ po stanie (Checklisty = /do-zrobienia
# z podzakładką 1). Bez tego „Ostatnio” zapisywałoby zawsze pozycję nadrzędną.
EKRANY_ZE_STANEM = [e for e in EKRANY if e.get("stan") and e.get("trasa")]


def _ekran_po_stanie(segment, state):
    """Wariant ekranu pasujący do BIEŻĄCEGO stanu — albo None, jeśli żaden."""
    for ekran in EKRANY_ZE_STANEM:
        segmenty_e = [s for s in ekran["trasa"].split("/") if s]
        if len(segmenty_e) != 1 or segmenty_e[0] != segment:
            continue
        if all(getattr(state, pole, None) == wartosc for pole, wartosc in ekran["stan"].items()):
            return ekran["id"]
    return None


def zanotuj_ekran_dla_trasy(state, segmenty):
    """Jedno miejsce, w którym zapisuje się „byłem tu”. Woła je router (patrz
    main.trasa_zmieniona), więc historia jest kompletna niezależnie od tego,
    czy ekran otwarto z szuflady, z kafelka, czy z linku wewnątrz innego ekranu."""
    try:
        if segmenty:
            ekran_id = _ekran_po_stanie(segmenty[0], state) or EKRANY_WG_SEGMENTU.get(segmenty[0])
        else:
            ekran_id = EKRAN_ZAKLADKI.get(
                (int(getattr(state, "zakladka", 0) or 0),
                 int(getattr(state, "koszty_podzakladka", 0) or 0))
            )
        if ekran_id:
            db.zanotuj_uzycie_ekranu(ekran_id)
    except Exception:
        pass


def kolor_ekranu(ekran):
    """Kolor pozycji: własny, a jak go nie ma — kolor grupy. Dzięki temu ta sama
    rzecz ma ten sam kolor w szufladzie, w skrótach i w wynikach wyszukiwania."""
    if not ekran:
        return ft.Colors.PRIMARY
    if ekran.get("kolor"):
        return ekran["kolor"]
    return (GRUPY_WG_ID.get(ekran.get("grupa"), {}) or {}).get("kolor") or ft.Colors.PRIMARY


def ekrany_grupy(grupa_id, akcje=None, ma_pojazd=True):
    """Pozycje jednej grupy, już odsiane: bez ekranów wymagających pojazdu, gdy
    go nie ma, i bez akcji, dla których wołający nie dostarczył obsługi."""
    wynik = []
    for ekran in EKRANY:
        if ekran.get("grupa") != grupa_id:
            continue
        if ekran.get("wymaga_pojazdu", True) and not ma_pojazd:
            continue
        if ekran.get("akcja") and not (akcje or {}).get(ekran["akcja"]):
            continue
        wynik.append(ekran)
    return wynik


def uruchom_akcje(page: ft.Page, obsluga):
    """Wywołuje akcję z rejestru ekranów niezależnie od tego, czy jest zwykłą
    funkcją, czy asynchroniczną.

    `akcje_nawigacji` owija wszystko w lambdy (`lambda: cb_export(None)`), więc
    po samej lambdzie nie widać, że pod spodem siedzi `async def`. Wywołanie
    zwracało wtedy korutynę, której nikt nie awaitował — kopia zapasowa i
    wczytanie bazy po cichu nie robiły NIC, a jedynym śladem było
    „RuntimeWarning: coroutine ... was never awaited” w konsoli.

    page.run_task wymaga prawdziwego `async def` (sprawdza
    `asyncio.iscoroutinefunction`), więc gotowej korutyny nie da się mu podać
    wprost — musi ją opakować osobna funkcja."""
    wynik = obsluga()
    if not inspect.isawaitable(wynik):
        return

    async def _dokoncz():
        try:
            await wynik
        except Exception as ex:
            pokaz_komunikat(page, f"Nie udało się wykonać akcji: {ex}", ft.Colors.RED_700)

    page.run_task(_dokoncz)


def otworz_ekran(page: ft.Page, state, ekran, akcje=None):
    """Wejście na ekran z rejestru — po jego identyfikatorze albo po całym wpisie.
    Historię „ostatnio używanych” prowadzi router (zanotuj_ekran_dla_trasy), bo
    ekran można otworzyć także zwykłym odnośnikiem; tu zapisujemy tylko AKCJE,
    których w adresie nie widać."""
    if isinstance(ekran, str):
        ekran = EKRANY_WG_ID.get(ekran)
    if not ekran:
        return

    if ekran.get("akcja"):
        db.zanotuj_uzycie_ekranu(ekran["id"])
        obsluga = (akcje or {}).get(ekran["akcja"])
        if obsluga:
            uruchom_akcje(page, obsluga)
        return

    # Ekrany mieszkające w PODZAKŁADCE innego widoku (Checklisty, Opony) niosą
    # w rejestrze pola stanu, które trzeba ustawić przed nawigacją. Dzięki temu
    # jeden wpis w EKRANY wystarczy, żeby taka pozycja działała w szufladzie,
    # w skrótach, w „Ostatnio” i w wyszukiwarce naraz.
    for pole, wartosc in (ekran.get("stan") or {}).items():
        try:
            setattr(state, pole, wartosc)
        except Exception:
            pass

    if ekran.get("zakladka") is not None:
        state.zakladka = int(ekran["zakladka"])
        if ekran.get("podzakladka") is not None:
            state.koszty_podzakladka = int(ekran["podzakladka"])
            db.zapamietaj_podzakladke_kosztow(state.koszty_podzakladka)
        przejdz(page, "/")
        return

    if ekran.get("trasa"):
        przejdz(page, ekran["trasa"])


def _tekst_do_szukania(ekran):
    czesci = [ekran.get("tytul", ""), ekran.get("opis", "")] + list(ekran.get("slowa") or [])
    return bez_ogonkow(" ".join(czesci).lower())


def znajdz_ekrany(fraza, akcje=None, ma_pojazd=True, limit=6):
    """Dopasowanie ekranów do frazy z wyszukiwarki. Trafienie w TYTUŁ waży więcej
    niż w opis czy słowa pomocnicze — kto wpisuje „rok”, szuka Roku w pigułce, a
    nie każdego ekranu, który ma gdzieś słowo „roczny”."""
    fraza = bez_ogonkow((fraza or "").strip().lower())
    if not fraza:
        return []

    trafienia = []
    for ekran in EKRANY:
        if ekran.get("wymaga_pojazdu", True) and not ma_pojazd:
            continue
        if ekran.get("akcja") and not (akcje or {}).get(ekran["akcja"]):
            continue

        tytul = bez_ogonkow(ekran.get("tytul", "").lower())
        if tytul.startswith(fraza):
            waga = 0
        elif fraza in tytul:
            waga = 1
        elif fraza in _tekst_do_szukania(ekran):
            waga = 2
        else:
            continue
        trafienia.append((waga, ekran))

    trafienia.sort(key=lambda p: (p[0], p[1]["tytul"]))
    return [e for _, e in trafienia[:limit]]


def _akcja_pozycji(po_kliknieciu, ekran):
    """Handler pozycji szuflady MUSI być korutyną, bo najpierw trzeba poczekać na
    zasunięcie panelu, a dopiero potem przełączyć ekran. Zwykła lambda zwracająca
    korutynę zostałaby po cichu porzucona — panel zostałby otwarty nad nowym
    ekranem, a nikt nie zobaczyłby żadnego błędu."""
    async def klik(e):
        await po_kliknieciu(ekran)
    return klik


def _wiersz_szuflady(ekran, liczniki, aktywny, po_kliknieciu):
    """Pojedyncza pozycja w szufladzie. Aktywny ekran dostaje wypełnioną pigułkę
    zamiast samego pogrubienia — w pionowej liście dwudziestu wierszy pogrubienie
    jest za słabym sygnałem, żeby dało się je złapać kątem oka."""
    kolor = kolor_ekranu(ekran)
    licznik = (liczniki or {}).get(ekran["id"])

    tresc = [
        ft.Icon(ekran["ikona"], size=20, color=kolor if aktywny else ft.Colors.ON_SURFACE_VARIANT),
        ft.Text(
            ekran["tytul"], size=FS["body"], expand=True, no_wrap=True,
            overflow=ft.TextOverflow.ELLIPSIS,
            weight="bold" if aktywny else "w500",
            color=kolor if aktywny else ft.Colors.ON_SURFACE,
        ),
    ]
    if licznik:
        tresc.append(ft.Container(
            padding=ft.Padding(7, 1, 7, 1), border_radius=RADIUS["pill"],
            bgcolor=ft.Colors.with_opacity(0.18, ft.Colors.ORANGE_700),
            content=ft.Text(str(licznik) if licznik < 100 else "99+", size=10,
                            weight="bold", color=ft.Colors.ORANGE_800),
        ))

    return ft.Container(
        padding=ft.Padding(12, 9, 12, 9), border_radius=RADIUS["pill"], ink=True,
        bgcolor=ft.Colors.with_opacity(0.13, kolor) if aktywny else None,
        tooltip=ekran.get("opis"),
        on_click=_akcja_pozycji(po_kliknieciu, ekran),
        content=ft.Row(tresc, spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER),
    )


def _naglowek_grupy_szuflady(grupa, liczba=None, zwinieta=False, on_click=None, ikona=None):
    """Nagłówek sekcji szuflady. Z `on_click` staje się przełącznikiem zwijania:
    dostaje strzałkę, licznik pozycji i ikonę grupy, żeby po zwinięciu dało się
    poznać, co siedzi w środku, bez rozwijania."""
    tresc = []
    if ikona:
        tresc.append(ft.Icon(ikona, size=15, color=ft.Colors.with_opacity(0.7, ft.Colors.ON_SURFACE_VARIANT)))
    tresc.append(ft.Text(
        grupa["tytul"].upper(), size=10, weight="bold", expand=True,
        no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS,
        color=ft.Colors.with_opacity(0.7, ft.Colors.ON_SURFACE_VARIANT),
    ))
    if liczba:
        tresc.append(ft.Text(str(liczba), size=10, weight="bold",
                             color=ft.Colors.with_opacity(0.55, ft.Colors.ON_SURFACE_VARIANT)))
    if on_click:
        tresc.append(ft.Icon(
            ft.Icons.KEYBOARD_ARROW_DOWN if zwinieta else ft.Icons.KEYBOARD_ARROW_UP,
            size=16, color=ft.Colors.with_opacity(0.7, ft.Colors.ON_SURFACE_VARIANT),
        ))

    return ft.Container(
        padding=ft.Padding(14, 12, 10, 6),
        border_radius=RADIUS["sm"],
        ink=bool(on_click),
        on_click=(lambda e: on_click()) if on_click else None,
        tooltip="Zwiń / rozwiń sekcję" if on_click else None,
        content=ft.Row(tresc, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
    )


def zbuduj_szuflade(page: ft.Page, state, akcje=None, aktywny_ekran=None, on_pojazdy=None, widok=None):
    """Boczna szuflada — GŁÓWNA mapa aplikacji. Cztery zakładki na dole zostają
    dla rzeczy robionych codziennie; szuflada odpowiada na pytanie „gdzie to
    było”, bo pokazuje WSZYSTKIE ekrany naraz, pogrupowane i zawsze w tej samej
    kolejności. Sekcje są rozwinięte DOMYŚLNIE — szukając czegoś raz na miesiąc
    chce się przewinąć wzrokiem, a nie zgadywać, w której zwiniętej sekcji to
    siedzi. Ale przy kilkunastu ekranach lista zrobiła się dłuższa niż ekran, więc
    każdą sekcję da się zwinąć dotknięciem nagłówka, a wybór jest zapamiętywany
    (klucz `szuflada_zwiniete`). Zwinięty nagłówek niesie ikonę grupy i licznik
    pozycji, żeby dało się poznać, co w środku.

    `widok` to widok, w którym szuflada zamieszka — potrzebny do jej zasunięcia.
    Podaje go wołający, bo w chwili budowania widok nie jest jeszcze wpięty
    w page.views i nie da się go stamtąd odczytać."""
    akcje = akcje or {}
    ma_pojazd = bool(state.auto_id)
    liczniki = db.liczniki_nawigacji(state.auto_id) if ma_pojazd else {}

    # Szufladę tworzymy PUSTĄ i wypełniamy w odbuduj(): zwinięcie sekcji podmienia
    # jej zawartość w miejscu, bez przeładowania całego ekranu i bez zamykania
    # panelu, w którym użytkownik właśnie szuka.
    szuflada = ft.NavigationDrawer(
        controls=[],
        bgcolor=ft.Colors.SURFACE,
        tile_padding=ft.Padding(4, 0, 4, 0),
    )
    grupa_aktywnego = (EKRANY_WG_ID.get(aktywny_ekran) or {}).get("grupa")

    async def przejdz_do(ekran):
        # Najpierw zasuwamy panel, DOPIERO potem przełączamy ekran. Odwrotna
        # kolejność zostawia szufladę wysuniętą nad świeżo zbudowanym widokiem,
        # bo zamknięcie trafia już w kontrolkę, której nie ma w drzewie.
        await _zamknij_szuflade(widok)
        otworz_ekran(page, state, ekran, akcje)

    def wiersz(ekran):
        return _wiersz_szuflady(
            ekran, liczniki,
            aktywny=(ekran["id"] == aktywny_ekran), po_kliknieciu=przejdz_do,
        )

    def przelacz(grupa_id):
        db.przelacz_grupe_szuflady(grupa_id)
        odbuduj()

    def odbuduj():
        zwiniete = set(db.pobierz_zwiniete_grupy_szuflady())
        elementy = [_naglowek_szuflady(page, state, on_pojazdy, widok)]

        # Kokpit stoi zaraz pod nagłówkiem, przed wszystkim innym — to punkt
        # powrotu, a nie jedna z pozycji którejś kategorii.
        elementy.extend(wiersz(e) for e in ekrany_grupy("start", akcje, ma_pojazd))

        if ma_pojazd:
            # Zakładki są odległe o jedno dotknięcie dolnego paska, więc trzymanie
            # ich w „Ostatnio” tylko zapychałoby miejsce ekranom, które NAPRAWDĘ
            # trudno znaleźć.
            ostatnie = [
                EKRANY_WG_ID[eid] for eid in db.pobierz_ostatnie_ekrany(8)
                if eid in EKRANY_WG_ID
                and EKRANY_WG_ID[eid]["id"] != aktywny_ekran
                and EKRANY_WG_ID[eid].get("zakladka") is None
            ][:4]
            ostatnie = [e for e in ostatnie if not (e.get("akcja") and not akcje.get(e["akcja"]))]
            if len(ostatnie) >= 2:
                zwinieta_ost = "ostatnio" in zwiniete
                elementy.append(_naglowek_grupy_szuflady(
                    {"tytul": "Ostatnio"}, liczba=len(ostatnie), zwinieta=zwinieta_ost,
                    on_click=lambda: przelacz("ostatnio"), ikona=ft.Icons.HISTORY,
                ))
                if not zwinieta_ost:
                    # Chipy ZAWIJAJĄ się do drugiej linijki zamiast jechać w bok:
                    # cztery pozycje i tak nie mieściły się w szerokości szuflady,
                    # a przewijania w poziomie nie było jak zauważyć — brakowało
                    # suwaka, a myszą nie da się przeciągnąć zawartości.
                    elementy.append(ft.Container(
                        padding=ft.Padding(12, 0, 12, 4),
                        content=pasek_zawijany(
                            [_chip_ekranu(e, przejdz_do) for e in ostatnie], spacing=6),
                    ))

        for grupa in GRUPY_EKRANOW:
            if grupa["id"] == "start":
                continue   # narysowany wyżej, bez nagłówka
            pozycje = ekrany_grupy(grupa["id"], akcje, ma_pojazd)
            if not pozycje:
                continue
            # Grupa z aktualnie otwartym ekranem zostaje rozwinięta ZAWSZE —
            # zwinięta sekcja z podświetloną pozycją w środku byłaby jedynym
            # miejscem, w którym szuflada gubi odpowiedź na „gdzie ja jestem”.
            zwinieta = grupa["id"] in zwiniete and grupa["id"] != grupa_aktywnego
            elementy.append(_naglowek_grupy_szuflady(
                grupa, liczba=len(pozycje), zwinieta=zwinieta,
                on_click=lambda gid=grupa["id"]: przelacz(gid), ikona=grupa.get("ikona"),
            ))
            if not zwinieta:
                elementy.extend(wiersz(ekran) for ekran in pozycje)

        elementy.append(dol_bezpieczny(16))

        szuflada.controls = elementy
        try:
            szuflada.update()
        except Exception:
            # Szuflada nie jest jeszcze w drzewie strony (pierwsze budowanie) —
            # przy otwarciu i tak pokaże aktualny stan.
            pass

    odbuduj()
    return szuflada


def _chip_ekranu(ekran, po_kliknieciu):
    kolor = kolor_ekranu(ekran)
    return ft.Container(
        padding=ft.Padding(10, 6, 12, 6), border_radius=RADIUS["pill"], ink=True,
        bgcolor=ft.Colors.with_opacity(0.10, kolor),
        on_click=_akcja_pozycji(po_kliknieciu, ekran),
        content=ft.Row([
            ft.Icon(ekran["ikona"], size=14, color=kolor),
            ft.Text(ekran["tytul"], size=FS["caption"], weight="w500", color=kolor, no_wrap=True),
        ], spacing=6, tight=True),
    )


async def _zamknij_szuflade(widok):
    """Zasuwa szufladę KONKRETNEGO widoku — tego, w którym ją otwarto. Sięganie
    po page.views[-1] w tym momencie trafiałoby czasem w widok już podmieniony
    przez nawigację."""
    try:
        if widok is not None and getattr(widok, "drawer", None) is not None:
            await widok.close_drawer()
    except Exception:
        pass


def _naglowek_szuflady(page: ft.Page, state, on_pojazdy=None, widok=None):
    """Nagłówek pokazuje, CZYJE dane się właśnie ogląda. Bez tego szuflada
    otwarta na drugim aucie wyglądałaby identycznie jak na pierwszym, a większość
    pozycji dotyczy konkretnego pojazdu."""
    dane = db.pobierz_dane_pojazdu(state.auto_id) if state.auto_id else None
    dane = dane or {}
    zdjecie = dane.get("zdjecie_glowne")

    if zdjecie:
        miniatura = ft.Image(src=abs_zalacznik(zdjecie), width=44, height=44,
                             fit="cover", border_radius=RADIUS["md"])
    else:
        miniatura = ft.Container(
            width=44, height=44, border_radius=RADIUS["md"],
            bgcolor=ft.Colors.with_opacity(0.14, ft.Colors.PRIMARY),
            alignment=ft.Alignment.CENTER,
            content=ft.Icon(ikona_nadwozia(dane.get("nadwozie")), size=22, color=ft.Colors.PRIMARY),
        )

    podpis = dane.get("nr_rej") or " ".join(
        str(dane.get(k) or "") for k in ("marka", "model")
    ).strip() or "Brak danych pojazdu"

    async def klik(e):
        await _zamknij_szuflade(widok)
        if on_pojazdy:
            on_pojazdy()

    return ft.Container(
        padding=ft.Padding(16, 20, 16, 12), ink=bool(on_pojazdy), on_click=klik if on_pojazdy else None,
        content=ft.Row([
            miniatura,
            ft.Column([
                ft.Text(str(state.auto_nazwa or "Brak pojazdów"), size=FS["body"], weight="bold",
                        no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(podpis, size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
                        no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
            ], spacing=1, tight=True, expand=True),
            ft.Icon(ft.Icons.SWAP_HORIZ, size=20, color=ft.Colors.PRIMARY) if on_pojazdy else ft.Container(),
        ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
    )


def pokaz_nawigacje_awaryjna(page: ft.Page, state, akcje=None):
    """Zapasowa postać szuflady: to samo drzewo ekranów, ale jako rozwijane menu
    od dołu (patrz pokaz_menu_grupowane)."""
    akcje = akcje or {}
    ma_pojazd = bool(state.auto_id)
    liczniki = db.liczniki_nawigacji(state.auto_id) if ma_pojazd else {}

    grupy = []
    for grupa in GRUPY_EKRANOW:
        pozycje = []
        for ekran in ekrany_grupy(grupa["id"], akcje, ma_pojazd):
            pozycje.append({
                "ikona": ekran["ikona"], "tekst": ekran["tytul"], "opis": ekran.get("opis"),
                "kolor": ekran.get("kolor"), "odznaka": liczniki.get(ekran["id"]),
                "akcja": (lambda ek=ekran: otworz_ekran(page, state, ek, akcje)),
            })
        grupy.append({"tytul": grupa["tytul"], "ikona": grupa["ikona"],
                      "otwarta": grupa["id"] == "pojazd", "pozycje": pozycje})

    pokaz_menu_grupowane(page, "Nawigacja", grupy,
                         podtytul=state.auto_nazwa if state.auto_id else "Brak pojazdów")


def kafel_skrotu(page: ft.Page, state, ekran, akcje=None, liczniki=None, szerokosc=None, col=None):
    """Kafelek w siatce skrótów na Kokpicie.

    `col` podaje się przy układzie ResponsiveRow — wtedy szerokość wylicza Flet
    z faktycznej szerokości okna, a nie my z wartości zgadniętej przed pierwszym
    pomiarem ekranu (patrz MiksinKokpitu._buduj_skroty)."""
    kolor = kolor_ekranu(ekran)
    licznik = (liczniki or {}).get(ekran["id"])

    ikona = ft.Container(
        width=38, height=38, border_radius=RADIUS["md"], alignment=ft.Alignment.CENTER,
        bgcolor=ft.Colors.with_opacity(0.14, kolor),
        content=ft.Icon(ekran["ikona"], size=20, color=kolor),
    )
    warstwy = [ikona]
    if licznik:
        warstwy.append(ft.Container(
            right=0, top=0, padding=ft.Padding(5, 1, 5, 1), border_radius=RADIUS["pill"],
            bgcolor=ft.Colors.RED_700,
            content=ft.Text(str(licznik) if licznik < 100 else "99+", size=9,
                            weight="bold", color=ft.Colors.WHITE),
        ))

    return ft.Container(
        width=szerokosc, col=col,
        padding=ft.Padding(10, 12, 10, 12), border_radius=RADIUS["lg"],
        bgcolor=tlo_karty(page, poziom=1), ink=True, tooltip=ekran.get("opis"),
        on_click=lambda e, ek=ekran: otworz_ekran(page, state, ek, akcje),
        content=ft.Column([
            ft.Stack(warstwy, width=38, height=38),
            ft.Text(ekran["tytul"], size=FS["caption"], weight="w500",
                    max_lines=2, text_align=ft.TextAlign.CENTER,
                    overflow=ft.TextOverflow.ELLIPSIS),
        ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True),
    )


def karta_sekcji(page: ft.Page, state, ekran, akcje=None, liczniki=None, szerokosc=190):
    """Szeroka karta „wejście do sekcji” — używana na paskach nad listami
    (Serwis, Analiza). W odróżnieniu od kafelka skrótu niesie też opis, bo stoi
    tam, gdzie trzeba wyjaśnić, co jest w środku."""
    kolor = kolor_ekranu(ekran)
    licznik = (liczniki or {}).get(ekran["id"])

    naglowek = [
        ft.Container(
            width=30, height=30, border_radius=RADIUS["sm"], alignment=ft.Alignment.CENTER,
            bgcolor=ft.Colors.with_opacity(0.14, kolor),
            content=ft.Icon(ekran["ikona"], size=17, color=kolor),
        ),
        ft.Text(ekran["tytul"], size=FS["label"], weight="bold", expand=True,
                no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
    ]
    if licznik:
        naglowek.append(ft.Container(
            padding=ft.Padding(6, 1, 6, 1), border_radius=RADIUS["pill"], bgcolor=ft.Colors.RED_700,
            content=ft.Text(str(licznik) if licznik < 100 else "99+", size=9,
                            weight="bold", color=ft.Colors.WHITE),
        ))

    return ft.Container(
        width=szerokosc, padding=ft.Padding(12, 12, 12, 12), border_radius=RADIUS["lg"],
        bgcolor=tlo_karty(page, poziom=1), ink=True,
        on_click=lambda e, ek=ekran: otworz_ekran(page, state, ek, akcje),
        content=ft.Column([
            ft.Row(naglowek, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Text(ekran.get("opis") or "", size=FS["caption"],
                    color=ft.Colors.ON_SURFACE_VARIANT, max_lines=2),
        ], spacing=8, tight=True),
    )


def pasek_sekcji(page: ft.Page, state, identyfikatory, akcje=None, liczniki=None, szerokosc=190):
    """Wstęga kart sekcji. PRZEWIJA się w bok — przy szerokości karty (190 px)
    na telefonie i tak mieści się najwyżej jedna w rzędzie, więc zawijanie
    (wrap) zamieniało pasek w kolumnę pojedynczych kart zamiast rzędu obok
    siebie. Ten sam wzorzec co karuzela kokpitu (pasek_przewijany)."""
    karty = [
        karta_sekcji(page, state, EKRANY_WG_ID[eid], akcje, liczniki, szerokosc)
        for eid in identyfikatory if eid in EKRANY_WG_ID
    ]
    if not karty:
        return ft.Container()
    return pasek_przewijany(karty, spacing=10)


def pokaz_edytor_skrotow(page: ft.Page, state, po_zapisie=None):
    """Wybór kafelków na Kokpicie. Świadomie NIE jest to przeciąganie: skróty
    dobiera się raz na kilka miesięcy, a lista z zaznaczeniami jest czytelna od
    razu i działa tak samo dobrze jednym kciukiem."""
    wybrane = list(db.pobierz_przypiete_ekrany())
    dostepne = [e for e in EKRANY if not e.get("akcja") and e["id"] != "kokpit"]

    licznik_txt = ft.Text("", size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT)
    bs = ft.BottomSheet(ft.Container(padding=ft.Padding(16, 16, 16, 8), bgcolor=ft.Colors.SURFACE))

    def odswiez_licznik():
        licznik_txt.value = f"Wybrano {len(wybrane)} z {db.MAKS_PRZYPIETYCH}"
        try:
            page.update()
        except Exception:
            pass

    def przelacz(ekran, pole):
        if ekran["id"] in wybrane:
            wybrane.remove(ekran["id"])
            pole.value = False
        elif len(wybrane) >= db.MAKS_PRZYPIETYCH:
            pole.value = False
            pokaz_komunikat(page, f"Skróty mieszczą {db.MAKS_PRZYPIETYCH} pozycji — odznacz coś najpierw.",
                            ft.Colors.AMBER_700)
        else:
            wybrane.append(ekran["id"])
            pole.value = True
        odswiez_licznik()

    wiersze = []
    for grupa in GRUPY_EKRANOW:
        pozycje = [e for e in dostepne if e.get("grupa") == grupa["id"]]
        if not pozycje:
            continue
        wiersze.append(ft.Container(
            padding=ft.Padding(4, 10, 4, 2),
            content=ft.Text(grupa["tytul"].upper(), size=10, weight="bold",
                            color=ft.Colors.ON_SURFACE_VARIANT),
        ))
        for ekran in pozycje:
            pole = ft.Checkbox(value=ekran["id"] in wybrane)
            pole.on_change = lambda e, ek=ekran, p=pole: przelacz(ek, p)
            wiersze.append(ft.Row([
                pole,
                ft.Icon(ekran["ikona"], size=18, color=kolor_ekranu(ekran)),
                ft.Text(ekran["tytul"], size=FS["body"], expand=True),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER))

    def zapisz(e):
        db.ustaw_przypiete_ekrany(wybrane)
        zamknij_dno(page, bs)
        pokaz_komunikat(page, "Zapisano skróty na Kokpicie.")
        if po_zapisie:
            po_zapisie()

    def domyslne(e):
        db.przywroc_domyslne_skroty()
        zamknij_dno(page, bs)
        pokaz_komunikat(page, "Przywrócono domyślne skróty.")
        if po_zapisie:
            po_zapisie()

    odswiez_licznik()
    bs.content.content = ft.Column([
        ft.Row([
            ft.Icon(ft.Icons.DASHBOARD_CUSTOMIZE, size=20, color=ft.Colors.PRIMARY),
            ft.Column([
                ft.Text("Skróty na Kokpicie", weight="bold", size=18, color=ft.Colors.PRIMARY),
                licznik_txt,
            ], spacing=0, tight=True, expand=True),
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ft.Divider(height=12),
        ft.Column(wiersze, spacing=2, tight=True),
        ft.Divider(height=12),
        ft.Row([
            ft.TextButton("Domyślne", icon=ft.Icons.RESTART_ALT, on_click=domyslne),
            ft.Container(expand=True),
            ft.TextButton("Anuluj", on_click=lambda e: zamknij_dno(page, bs)),
            ft.FilledButton("Zapisz", icon=ft.Icons.CHECK, on_click=zapisz),
        ], spacing=8),
    ], tight=True, spacing=0)
    otworz_dno(page, bs)


def akcje_nawigacji(page: ft.Page, state, cb_export=None, cb_import=None, cb_theme=None):
    """Obsługa pozycji rejestru, które nie są zwykłym przejściem pod adres —
    kopia bazy, motyw, usunięcie pojazdu. Wołający, który tych rzeczy nie może
    wykonać (np. ekran wyszukiwania), po prostu ich nie przekazuje i znikają
    z listy zamiast prowadzić donikąd."""
    akcje = {
        "usun_pojazd": (lambda: usun_auto(page, state)) if state.auto_id else None,
        "sprzedaj_pojazd": (lambda: sprzedaj_auto(page, state)) if state.auto_id else None,
        "cykliczne": (lambda: pokaz_panel_wydatkow_cyklicznych(page, state)) if state.auto_id else None,
        "edytuj_pojazd": (lambda: przejdz(page, f"/auto/edytuj/{state.auto_id}")) if state.auto_id else None,
    }
    if cb_export:
        akcje["kopia"] = lambda: cb_export(None)
    if cb_import:
        akcje["wczytaj"] = lambda: cb_import(None)
    if cb_theme:
        akcje["motyw"] = lambda: cb_theme(None)
    return {k: v for k, v in akcje.items() if v}


def zbuduj_pasek_glowny(page: ft.Page, state, cb_export, cb_import, cb_theme, on_menu=None):
    """Pasek górny ekranu głównego. Menu ⋮ zniknęło: kilkanaście pozycji ukrytych
    pod trzema kropkami w prawym rogu było najgorszym możliwym miejscem na MAPĘ
    aplikacji. Zastąpił je hamburger po lewej, który wysuwa szufladę z pełnym,
    pogrupowanym spisem ekranów (patrz utils.EKRANY i zbuduj_szuflade)."""

    def awaryjne_menu(e):
        pokaz_nawigacje_awaryjna(page, state, akcje_nawigacji(page, state, cb_export, cb_import, cb_theme))

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
        leading=ft.IconButton(
            icon=ft.Icons.MENU,
            icon_size=22,
            tooltip="Nawigacja — wszystkie ekrany",
            on_click=on_menu or awaryjne_menu,
        ),
        actions=[
            ft.IconButton(
                icon=ft.Icons.SEARCH,
                icon_size=20,
                tooltip="Szukaj wpisów i ekranów",
                on_click=lambda e: przejdz(page, "/szukaj"),
                width=36, height=36,
                style=ft.ButtonStyle(padding=0),
            ),
            przycisk_dzwonka(page, state),
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


__all__ = [
    "EKRANY",
    "EKRANY_WG_ID",
    "EKRANY_WG_SEGMENTU",
    "EKRAN_ZAKLADKI",
    "GRUPY_EKRANOW",
    "GRUPY_WG_ID",
    "_akcja_pozycji",
    "_chip_ekranu",
    "_naglowek_grupy_szuflady",
    "_naglowek_szuflady",
    "_tekst_do_szukania",
    "_wiersz_szuflady",
    "_zamknij_szuflade",
    "akcje_nawigacji",
    "ekrany_grupy",
    "kafel_skrotu",
    "karta_sekcji",
    "kolor_ekranu",
    "otworz_ekran",
    "uruchom_akcje",
    "pasek_sekcji",
    "pokaz_edytor_skrotow",
    "pokaz_nawigacje_awaryjna",
    "zanotuj_ekran_dla_trasy",
    "zbuduj_pasek_glowny",
    "zbuduj_pasek_z_powrotem",
    "zbuduj_szuflade",
    "znajdz_ekrany",
]
