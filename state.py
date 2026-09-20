MIESIACE_NAZWY = [
    "Styczeń", "Luty", "Marzec", "Kwiecień", "Maj", "Czerwiec", 
    "Lipiec", "Sierpień", "Wrzesień", "Październik", "Listopad", "Grudzień"
]

class AppState:
    def __init__(self):
        self.auto_id = None
        self.auto_nazwa = "Brak pojazdów"
        self.zakladka = 0            # 0 Kokpit, 1 Serwis, 2 Koszty, 3 Analiza
        self.koszty_podzakladka = 0  # 0 Tankowania, 1 Inne koszty
        self.stat_podzakladka = 0
        # Wykres „rok do roku": wybór roku, wielkości i postaci krzywej. Stan
        # widoku, nie ustawienie — po zamknięciu aplikacji wraca do bieżącego
        # roku i kosztów razem, tak jak zakładki wyżej.
        self.rdr_rok = None            # None = najnowszy rok z danymi
        self.rdr_wielkosc = "razem"    # klucz z db.WIELKOSCI_RDR
        self.rdr_narastajaco = True
        self.wybrane_zadanie_id = None
        self.duplikuj_zrodlo_tankowanie = None
        self.duplikuj_zrodlo_wpis = None
        self.duplikuj_zrodlo_koszt = None
        # Cykliczny, identyczny przegląd w warsztacie robi się raz na jakiś czas
        # z tą samą listą części — duplikat wizyty oszczędza odklikiwanie ich
        # od zera. Kopiuje wszystko poza datą, załącznikiem i zużyciem magazynu.
        self.duplikuj_zrodlo_wizyta = None
        self.wybrane_zadanie_nazwa = ""
        # „Widziane” w dzwonku nie mieszka już w stanie: liczy się osobno dla
        # każdego powiadomienia i jest zapisywane w bazie, per pojazd (patrz
        # db.powiadomienia) — inaczej każdy zimny start telefonu zapalałby
        # odznakę na wszystkim od nowa.
        # Pojazd, dla którego odliczanie liczb na kokpicie już zagrało. Kokpit
        # przebudowuje się przy każdej zmianie zakładki i po wyjściu z dowolnego
        # ekranu — bez tego znacznika animacja wejścia grałaby kilkanaście razy
        # na sesję i z powitania zrobiłaby się zwłoka przy odczycie.
        self.kokpit_animacja_dla = None
        # Ustawienia → „Ułóż kafelki kokpitu” tylko przełącza ekran; tryb
        # układania włącza sam kokpit, gdy zobaczy tę flagę (i od razu ją gasi).
        self.kokpit_otworz_ukladanie = False
        # Ekrany, na których animacja wejścia już zagrała: klucz ekranu -> pojazd.
        # Paski terminów i budżetów wypełniają się RAZ na uruchomienie aplikacji
        # (patrz utils.pierwsze_pokazanie) — przy dziesiątym wejściu na kartę
        # pojazdu ten sam ruch byłby już tylko zwłoką przed odczytem.
        self.animacje_pokazane = {}
        # Gdzie stał pasek przewijania na danym ekranie: klucz miejsca -> piksele.
        # Router przebudowuje cały stos widoków przy każdej zmianie sortowania,
        # filtra i po każdej akcji na wpisie — bez tej pamięci lista wracała za
        # każdym razem na samą górę (patrz utils.pozycja).
        self.pozycje_przewijania = {}
        self.magazyn_zakladka = 0  # 0 = Opony, 1 = Części i płyny
        self.do_zrobienia_podzakladka = 0  # 0 = Do zrobienia, 1 = Checklisty
        self.porownanie_wybrane = []
        self.porownanie_piata_os = None  # klucz opcjonalnej 5. osi radaru porównania (None = wyłączona, patrz porownanie_view.OSIE_OPCJONALNE_RADARU)

        # --- SORTOWANIE ---
        # Klucz = nazwa listy, wartość = (pole, malejaco).
        # Nowa lista NIE wymaga nowego atrybutu klasy — utils.przycisk_sortowania()
        # sam dopisze sensowną wartość domyślną, jeśli klucza tu jeszcze nie ma.
        self.sort = {
            "zadania": ("nazwa", False),
            "tankowania": ("data", True),
            "inne": ("data", True),
            "historia": ("data", True),
            "wizyty": ("data", True),
            "do_zrobienia": ("priorytet", False),
            "stat_miesiace": ("okres", True),
            "stat_lata": ("rok", True),
            "magazyn_czesci": ("nazwa", False),
            "timeline": ("data", True),
        }

        # --- FILTRY ---
        # Klucz = nazwa filtra, wartość = aktualnie wybrana opcja.
        # Domyślną wartością jest zawsze "Wszystko" (patrz utils._zbuduj_popup_filtra),
        # więc tu wystarczy wypisać tylko wyjątki od tej reguły.
        self.filtry = {
            "do_zrobienia_status": "Aktywne",
        }