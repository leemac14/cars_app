MIESIACE_NAZWY = [
    "Styczeń", "Luty", "Marzec", "Kwiecień", "Maj", "Czerwiec", 
    "Lipiec", "Sierpień", "Wrzesień", "Październik", "Listopad", "Grudzień"
]

class AppState:
    def __init__(self):
        self.auto_id = None
        self.auto_nazwa = "Brak pojazdów"
        self.zakladka = 0
        self.stat_podzakladka = 0
        self.wybrane_zadanie_id = None
        self.duplikuj_zrodlo_tankowanie = None
        self.duplikuj_zrodlo_wpis = None
        self.duplikuj_zrodlo_koszt = None
        self.wybrane_zadanie_nazwa = ""
        self.powiadomienia_widziane = {}   # zamiast pojedynczej sygnatury
        self.magazyn_zakladka = 0  # 0 = Opony, 1 = Części i płyny
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