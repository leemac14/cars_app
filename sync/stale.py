"""Adres projektu Supabase, mapa tabel i etykiety — bez ani jednej instrukcji.

Ten moduł jest na samym dole pakietu, bo `KONFIGURACJA_SYNC` jest jedynym
opisem tego, CO w ogóle jedzie do chmury: dwadzieścia jeden tabel, ich klucze
i kolumny. Dołożenie tabeli do synchronizacji to wpis tutaj, a nie łatka
w pięciu miejscach — i dlatego `tests/test_schemat.py` porównuje ten słownik
wprost z `PRAGMA table_info`.
"""


# Kolumna znacznika czasu w tabeli zdalne_rekordy. Jeśli w Twoim projekcie
# Supabase nazywa się inaczej, wystarczy zmienić TU — moduł i tak sam wykryje
# jej brak i przełączy się na pełne pobieranie.
KOLUMNA_ZNACZNIKA = "zaktualizowano"


# --- UZUPEŁNIJ PO ZAŁOŻENIU PROJEKTU NA supabase.com (Project Settings -> API) ---
SUPABASE_URL = "https://ptnnejbuvymhrkouwsln.supabase.co"

SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InB0bm5lamJ1dnltaHJrb3V3c2xuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODc2NTg2NTQsImV4cCI6MjEwMzIzNDY1NH0.xfLcVeiNatGqFtBBnvSB2EOZoo9i_vodDqtF6XLC9iA"
# ----------------------------------------------------------------------------------


# Link zaproszenia carsapp://app/dolacz/<KOD> — w kodzie QR i w zaproszeniu
# wysłanym SMS-em. Schemat i host MUSZĄ być takie same jak w pyproject.toml
# ([tool.flet.android.deep_linking]) — inaczej Android nie skieruje linku do
# aplikacji. Oba małymi literami: Android porównuje je z rozróżnianiem wielkości.
# Flet podaje aplikacji samą ścieżkę, więc link trafia na trasę /dolacz/<KOD>.
SCHEMAT_LINKU = "carsapp"
HOST_LINKU = "app"
TRASA_DOLACZENIA = "dolacz"


class SynchronizacjaWToku(Exception):
    """Inna synchronizacja tego urządzenia właśnie trwa. Rzucane wyłącznie
    przy wywołaniu z `czekaj=False` — nie jest błędem, tylko informacją,
    że nie ma po co robić drugiego przebiegu równolegle."""


KOLUMNY_POJAZDU = [
    "nazwa", "marka", "model", "generacja", "nr_rej", "vin", "rok_produkcji",
    "oc_data", "przeglad_data", "pojemnosc_silnika", "moc_silnika", "typ_paliwa",
    "skrzynia_biegow", "nadwozie", "pojemnosc_baterii", "zasieg_ev", "pojemnosc_baku",
    "notatki", "wycieraczki_przod", "wycieraczki_tyl",
    "cisnienie_przod", "cisnienie_tyl", "olej_typ", "olej_pojemnosc", "akumulator",
    "zarowki_mijania", "zarowki_drogowe", "ac_data", "assistance_data",
    "gasnica_data", "apteczka_data", "wiadomosc_statusu",
    "gwarancja_data", "gwarancja_przebieg",
    # Dane z wersji 37 — zakup i wartość, ubezpieczenie, rozszerzona ściągawka,
    # pierwsza rejestracja. Wszystkie opisują POJAZD, więc przy współdzieleniu
    # muszą być widoczne po obu stronach; telefon do assistance przede wszystkim.
    "data_zakupu", "cena_zakupu", "przebieg_zakupu", "wartosc_szacowana",
    "ubezpieczyciel", "nr_polisy", "skladka_roczna", "telefon_assistance",
    "kod_lakieru", "rozmiar_opon", "rozmiar_felg", "rozstaw_srub",
    "moment_dokrecania", "typ_zlacza_ev", "data_pierwszej_rejestracji",
    # Sprzedaż auta musi dojść do drugiej strony: inaczej u współdzielącego
    # pojazd dalej stałby w garażu, choć fizycznie już go nie ma.
    "status", "data_sprzedazy", "cena_sprzedazy",
    # Notatka „najlepsza oferta OC/AC” (wersja 47) z datą ostatniej zmiany tekstu:
    # ubezpieczenie kupuje się wspólnie, więc porównanie ma być widać po obu stronach.
    "oferta_oc_ac", "oferta_oc_ac_data",
]

# Kolumny pojazdu dołożone do synchronizacji, kiedy w chmurze były już rekordy
# `info_pojazdu` — odpowiednik `dopisane` z KONFIGURACJA_SYNC dla karty pojazdu.
# Dopóki są puste, karta liczy się tak, jakby ich nie było: hash zapamiętany przed
# aktualizacją powstał bez tych kluczy. Bez tej tolerancji telefon po aktualizacji
# widziałby w KAŻDYM współdzielonym aucie „zmianę lokalną” i wysłałby swoją kartę
# nad tą, którą druga osoba zdążyła zmienić (status, daty) — albo nad notatką
# wpisaną na jej telefonie, zaktualizowanym wcześniej. Nowa kolumna dokładana do
# KOLUMNY_POJAZDU po wdrożeniu synchronizacji trafia też tutaj, tak samo jak
# `dopisane` przy tabelach.
KOLUMNY_POJAZDU_DOPISANE = ["oferta_oc_ac", "oferta_oc_ac_data"]


# Notatka wpisu jedzie do chmury razem z resztą jego pól (kolumny 'notatka',
# 'notatka_autor', 'notatka_data') — sens tej funkcji polega na tym, że uwagę
# zostawioną przy tankowaniu widzi też druga osoba korzystająca z auta.
KONFIGURACJA_SYNC = [
    {"tabela": "tagi", "kolumny": ["nazwa", "kolor"], "fk": {}},
    {"tabela": "tankowania", "kolumny": ["data", "przebieg", "dystans", "litry", "kwota", "do_pelna", "stacja", "tagi", "rodzaj_energii", "typ_ladowania", "notatka", "notatka_autor", "notatka_data", "dodane_przez", "zmodyfikowane_przez", "data_modyfikacji"], "fk": {}},
    {"tabela": "zadania", "kolumny": ["nazwa", "interwal_km", "interwal_miesiace", "dotyczy_opon", "prog_km", "prog_dni"], "fk": {}},
    # `dopisane` — kolumny dołożone do synchronizacji, kiedy w chmurze były już
    # rekordy. Dopóki są puste, rekord liczy się tak, jakby kolumny nie było:
    # inaczej nowy klucz zmieniałby hash KAŻDEGO wiersza, telefon po
    # aktualizacji wysyłałby całą tabelę od nowa, a drugi telefon zgłaszałby
    # przy każdym wierszu konflikt z wersją, którą właśnie wysłał pierwszy.
    {"tabela": "wizyty", "kolumny": ["data", "przebieg", "wykonawca", "koszt_calkowity", "koszt_robocizny", "notatki", "tagi", "dodane_przez", "zmodyfikowane_przez", "data_modyfikacji", "gwarancja_data", "gwarancja_przebieg"], "fk": {},
     "dopisane": ["koszt_robocizny", "gwarancja_data", "gwarancja_przebieg"]},
    # Gwarancja naprawy jedzie do drugiej osoby: to ona stoi z autem
    # w warsztacie, kiedy klocki zaczną piszczeć drugi raz.
    {"tabela": "historia", "kolumny": ["data", "przebieg", "kategoria", "cena", "koszt_robocizny", "wykonawca", "notatka", "notatka_autor", "notatka_data", "dodane_przez", "zmodyfikowane_przez", "data_modyfikacji", "gwarancja_data", "gwarancja_przebieg"], "fk": {"zadanie_id": "zadania", "wizyta_id": "wizyty"},
     "dopisane": ["koszt_robocizny", "gwarancja_data", "gwarancja_przebieg"]},
    # Koszt zużycia jedzie razem z ilością: to on mówi drugiej osobie, ile
    # z kosztu wizyty przyszło z magazynu — bez niego jej edycja tej wizyty
    # doliczyłaby części drugi raz.
    # Sklep i link do produktu (wersja 48) dołożone, kiedy pozycje magazynu
    # leżały już w chmurze — stąd `dopisane`.
    {"tabela": "magazyn_czesci", "kolumny": ["nazwa", "kategoria", "ilosc", "jednostka", "cena", "cena_jednostkowa", "data_zakupu", "notatki", "prog_ostrzezenia", "sklep", "link"], "fk": {},
     "dopisane": ["sklep", "link"]},
    # Historia cen części jest cechą AUTA: filtr kupiony przez drugą osobę
    # podnosi albo obniża tę samą krzywą. Bez klucza obcego do pozycji —
    # zakup ma przeżyć zużytą i usuniętą pozycję; łączy je nazwa (klucz_nazwy).
    {"tabela": "ceny_czesci", "kolumny": ["nazwa", "data", "cena_jednostkowa", "jednostka", "ilosc", "sklep"], "fk": {}},
    {"tabela": "wizyta_czesci_magazynu", "kolumny": ["ilosc_uzyta", "koszt"], "fk": {"wizyta_id": "wizyty", "magazyn_id": "magazyn_czesci"}},
    {"tabela": "historia_czesci_magazynu", "kolumny": ["ilosc_uzyta", "koszt"], "fk": {"historia_id": "historia", "magazyn_id": "magazyn_czesci"}},
    {"tabela": "zestawy_opon", "kolumny": ["sezon", "rozmiar", "marka_model", "glebokosc_bieznika", "data_pomiaru", "numer_dot", "ilosc", "zamontowane", "data_zakupu", "przebieg_zakupu", "cena", "notatki", "os_montazu"], "fk": {}},
    {"tabela": "inne_koszty", "kolumny": ["data", "kategoria", "nazwa", "kwota", "tagi", "notatka", "notatka_autor", "notatka_data", "dodane_przez", "zmodyfikowane_przez", "data_modyfikacji"], "fk": {}},
    {"tabela": "warsztaty", "kolumny": ["nazwa", "telefon", "adres", "notatki"], "fk": {}},
    # Umowa raty (wersja 49) jedzie razem z wpisem: rata zapłacona na jednym
    # telefonie przesuwa harmonogram także na drugim, a „ile zostało do spłaty”
    # ma być jedną liczbą dla obu osób. Kolumny dołożone, kiedy wpisy cykliczne
    # leżały już w chmurze — stąd `dopisane`.
    {"tabela": "wydatki_cykliczne", "kolumny": ["nazwa", "kwota", "okres_dni", "nastepna_data", "czy_koszt", "typ",
                                                "liczba_rat", "zaplacone_platnosci", "data_pierwszej_raty",
                                                "kwota_finansowania", "oplata_wstepna", "wykup", "oprocentowanie",
                                                "rodzaj_rat"], "fk": {},
     "dopisane": ["liczba_rat", "zaplacone_platnosci", "data_pierwszej_raty", "kwota_finansowania",
                  "oplata_wstepna", "wykup", "oprocentowanie", "rodzaj_rat"]},
    {"tabela": "odczyty_przebiegu", "kolumny": ["data", "przebieg", "zrodlo", "notatka", "notatka_autor", "notatka_data"], "fk": {}},
    {"tabela": "do_zrobienia", "kolumny": ["tytul", "opis", "priorytet", "szacowany_koszt", "termin", "wykonane", "data_utworzenia"], "fk": {"zadanie_id": "zadania"}},
    {"tabela": "pakiety_serwisowe_wlasne", "kolumny": ["nazwa", "pozycje"], "fk": {}},
    # Limit wydatków ustala się raz dla pojazdu, nie osobno w każdym telefonie —
    # inaczej dwie osoby patrzyłyby na dwa różne budżety tego samego auta.
    # 'klucz_scalania' jest tu konieczny: (kategoria, okres) ma w bazie UNIQUE,
    # więc rekord przychodzący z chmury musi umieć wejść w istniejący lokalny
    # wiersz zamiast rozbić się o indeks (patrz _pobierz_tabele).
    {"tabela": "budzety", "kolumny": ["kategoria", "okres", "kwota"], "fk": {},
     "klucz_scalania": ["kategoria", "okres"]},
    # Trasa „do teściów” jest cechą AUTA, nie telefonu — kto wsiądzie, ten ma
    # tę samą pozycję w kalkulatorze. Skąd, dokąd, cel i rodzaj (wersja 50)
    # robią z niej wzór przejazdu w ewidencji; dołożone, kiedy trasy leżały
    # już w chmurze — stąd `dopisane`.
    {"tabela": "trasy_szablony", "kolumny": ["nazwa", "dystans", "powrot", "osoby", "oplaty", "notatki",
                                             "skad", "dokad", "cel", "sluzbowy"], "fk": {},
     "dopisane": ["skad", "dokad", "cel", "sluzbowy"]},
    # Ewidencja przebiegu jest wspólna dla auta: druga osoba dopisuje swoje
    # przejazdy (kierowca), a raport miesiąca ma być jeden dla obojga.
    {"tabela": "przejazdy", "kolumny": ["data", "skad", "dokad", "cel", "km", "powrot", "sluzbowy", "kierowca",
                                        "licznik", "notatka", "notatka_autor", "notatka_data", "dodane_przez"],
     "fk": {}},
    # Checklista jedzie w komplecie: nagłówek plus pozycje. Stan odhaczenia też
    # — przy wspólnym aucie sens polega właśnie na tym, że druga osoba widzi,
    # co zostało już sprawdzone przed wyjazdem.
    {"tabela": "checklisty", "kolumny": ["nazwa", "opis", "ostatnie_uzycie"], "fk": {}},
    {"tabela": "checklisty_pozycje", "kolumny": ["tresc", "kolejnosc", "odhaczone"], "fk": {"checklista_id": "checklisty"}},
    # Saldo jest wspólne, więc „Rozliczone” kliknięte na jednym telefonie musi
    # wyzerować je także na drugim. Rozliczenie się nie zmienia (najwyżej się je
    # cofa), a migawka sald jedzie w całości — z niej drugi telefon liczy to samo
    # saldo, nawet jeśli część wpisów dostanie dopiero przy następnej wymianie.
    {"tabela": "rozliczenia", "kolumny": ["data", "uczestnicy", "salda", "przelewy", "notatka", "klucz", "poprzednie", "dodane_przez", "data_utworzenia"], "fk": {}},
]


# Tabele bez własnej kolumny auto_id — do pojazdu dowiązane wyłącznie pośrednio,
# przez JOIN. Wcześniej każdy taki przypadek był osobnym if/elif powtórzonym
# w pięciu miejscach tego pliku; teraz jest jednym opisem, więc dołożenie kolejnej
# tabeli pośredniej to jeden wpis, a nie pięć łatek.
TABELE_POSREDNIE = {
    "historia": {
        "alias": "h",
        "join": "JOIN zadania z ON h.zadanie_id = z.id",
        "warunek": "z.auto_id=?",
        "reset_where": "zadanie_id IN (SELECT id FROM zadania WHERE auto_id=?)",
    },
    "wizyta_czesci_magazynu": {
        "alias": "wcm",
        "join": "JOIN wizyty w ON wcm.wizyta_id = w.id",
        "warunek": "w.auto_id=?",
        "reset_where": "wizyta_id IN (SELECT id FROM wizyty WHERE auto_id=?)",
    },
    "checklisty_pozycje": {
        "alias": "p",
        "join": "JOIN checklisty l ON p.checklista_id = l.id",
        "warunek": "l.auto_id=?",
        "reset_where": "checklista_id IN (SELECT id FROM checklisty WHERE auto_id=?)",
    },
    "historia_czesci_magazynu": {
        "alias": "hcm",
        "join": "JOIN historia h ON hcm.historia_id = h.id JOIN zadania z ON h.zadanie_id = z.id",
        "warunek": "z.auto_id=?",
        "reset_where": (
            "historia_id IN (SELECT h.id FROM historia h "
            "JOIN zadania z ON h.zadanie_id = z.id WHERE z.auto_id=?)"
        ),
    },
}


ETYKIETY_TABEL_SYNC = {
    "tankowania": "Tankowanie",
    "historia": "Wpis serwisowy",
    "wizyty": "Wizyta w warsztacie",
    "zadania": "Podzespół",
    "magazyn_czesci": "Pozycja magazynu",
    "ceny_czesci": "Cena części",
    "wizyta_czesci_magazynu": "Zużycie części",
    "historia_czesci_magazynu": "Zużycie części przy wpisie",
    "zestawy_opon": "Zestaw opon",
    "inne_koszty": "Inny koszt",
    "warsztaty": "Warsztat",
    "wydatki_cykliczne": "Wydatek cykliczny",
    "odczyty_przebiegu": "Odczyt licznika",
    "do_zrobienia": "Zadanie do zrobienia",
    "tagi": "Tag",
    "pakiety_serwisowe_wlasne": "Własny pakiet serwisowy",
    "budzety": "Limit budżetu",
    "trasy_szablony": "Zapisana trasa",
    "przejazdy": "Przejazd",
    "checklisty": "Checklista",
    "checklisty_pozycje": "Pozycja checklisty",
    "rozliczenia": "Rozliczenie",
    "info_pojazdu": "Dane pojazdu",
}


__all__ = [
    "ETYKIETY_TABEL_SYNC",
    "HOST_LINKU",
    "KOLUMNA_ZNACZNIKA",
    "KOLUMNY_POJAZDU",
    "KOLUMNY_POJAZDU_DOPISANE",
    "KONFIGURACJA_SYNC",
    "SCHEMAT_LINKU",
    "SUPABASE_ANON_KEY",
    "SUPABASE_URL",
    "SynchronizacjaWToku",
    "TABELE_POSREDNIE",
    "TRASA_DOLACZENIA",
]
