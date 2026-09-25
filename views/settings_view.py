import flet as ft
import db
import log
import utils


class UstawieniaView(ft.View):
    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state

        waluta_val = db.pobierz_walute()
        jednostka_val = db.pobierz_jednostke_spalania()
        prog_km_val = db.pobierz_prog_km()
        prog_dni_val = db.pobierz_prog_dni()
        moje_imie_val = db.pobierz_moje_imie()
        # Kokpit ustawiamy dla AKTYWNEGO pojazdu. Auto bez własnego układu
        # pokazuje tu wspólny — i dopiero zapis odpina je od niego.
        self.kokpit_auto_id = state.auto_id
        widgety_wlaczone = set(db.pobierz_widgety_kokpitu(self.kokpit_auto_id))
        self.kokpit_wlasny = db.czy_kokpit_wlasny(self.kokpit_auto_id)

        self.e_waluta = ft.Dropdown(
            label="Waluta",
            options=[ft.DropdownOption(key=w, text=w) for w in db.WALUTY],
            value=waluta_val,
            **utils.styl_dropdown()
        )

        self.e_jednostka = ft.Dropdown(
            label="Jednostka spalania",
            options=[ft.DropdownOption(key=j, text=j) for j in db.JEDNOSTKI_SPALANIA],
            value=jednostka_val,
            **utils.styl_dropdown()
        )

        self.e_jednostka_ev = ft.Dropdown(
            label="Jednostka zużycia (pojazdy elektryczne)",
            options=[ft.DropdownOption(key=j, text=j) for j in db.JEDNOSTKI_ZUZYCIA_EV],
            value=db.pobierz_jednostke_zuzycia_ev(),
            **utils.styl_dropdown()
        )

        self.e_prog_km = ft.Dropdown(
            label="Powiadamiaj o wymianie na tyle km przed",
            options=[ft.DropdownOption(key=str(k), text=f"{k} km") for k in db.PROGI_KM_OPCJE],
            value=str(prog_km_val) if prog_km_val in db.PROGI_KM_OPCJE else str(db.PROGI_KM_OPCJE[2]),
            **utils.styl_dropdown()
        )

        # Każdy termin ma własny dropdown z „Jak domyślny” na pierwszym miejscu.
        # Pusty klucz = brak własnego progu, czyli obowiązuje ten z pola wyżej —
        # dzięki temu nieruszone terminy zachowują się dokładnie jak przedtem.
        def opis_progu(d):
            if d == 30: return "1 miesiąc"
            if d == 60: return "2 miesiące"
            if d == 90: return "3 miesiące"
            if d == 180: return "Pół roku"
            if d == 365: return "Rok"
            return f"{d} dni"

        self.dropdowny_terminow = {}
        for klucz, _kolumna, etykieta in db.TERMINY_DOKUMENTOW:
            self.dropdowny_terminow[klucz] = ft.Dropdown(
                label=etykieta,
                options=(
                    [ft.DropdownOption(key="", text="Jak domyślny (powyżej)")]
                    + [ft.DropdownOption(key=str(d), text=opis_progu(d)) for d in db.PROGI_DNI_DOKUMENTU_OPCJE]
                ),
                value=db.pobierz_wlasny_prog_dni_dokumentu(klucz),
                **utils.styl_dropdown()
            )

        # Retencja kosza: 0 to świadomie "nigdy" — pojazdy leżą w koszu do skutku.
        opcje_kosza_tekst = {7: "7 dni", 30: "30 dni", 90: "90 dni", 0: "Nigdy — czyszczę ręcznie"}
        dni_kosza_val = db.pobierz_dni_kosza()
        self.e_dni_kosza = ft.Dropdown(
            label="Trzymaj usunięte pojazdy w koszu przez",
            options=[ft.DropdownOption(key=str(d), text=opcje_kosza_tekst.get(d, f"{d} dni")) for d in db.DNI_KOSZA_OPCJE],
            value=str(dni_kosza_val),
            **utils.styl_dropdown()
        )

        opcje_dni_tekst = {7: "7 dni", 14: "14 dni", 30: "1 miesiąc", 60: "60 dni", 90: "90 dni"}
        self.e_prog_dni = ft.Dropdown(
            label="Powiadamiaj o dokumentach i terminach na tyle dni przed",
            options=[ft.DropdownOption(key=str(d), text=opcje_dni_tekst.get(d, f"{d} dni")) for d in db.PROGI_DNI_OPCJE],
            value=str(prog_dni_val) if prog_dni_val in db.PROGI_DNI_OPCJE else str(db.PROGI_DNI_OPCJE[2]),
            **utils.styl_dropdown()
        )

        # Przypomnienie o odczycie licznika: po ilu dniach bez ŻADNEGO wpisu
        # z przebiegiem dzwonek o niego prosi (i znowu po każdym takim okresie).
        opcje_licznika_tekst = {14: "Po 14 dniach", 30: "Po miesiącu (30 dni)",
                                60: "Po 2 miesiącach (60 dni)", 0: "Nie przypominaj"}
        self.e_przypomnienie_licznika = ft.Dropdown(
            label="Przypominaj o odczycie licznika",
            options=[ft.DropdownOption(key=str(d), text=opcje_licznika_tekst.get(d, f"{d} dni"))
                     for d in db.DNI_PRZYPOMNIENIA_O_ODCZYCIE_OPCJE],
            value=str(db.pobierz_dni_przypomnienia_o_odczycie()),
            **utils.styl_dropdown()
        )

        # --- PALETA KOLORÓW ---
        self.wybrany_kolor = db.pobierz_kolor_motywu()
        self.wiersz_kolorow = ft.Row(wrap=True, spacing=10)

        # Parametr 'aktualizuj' blokuje błędy Fleta podczas inicjalizacji widoku
        def odswiez_palete(aktualizuj=False):
            self.wiersz_kolorow.controls.clear()
            for nazwa in db.KOLORY_MOTYWU:
                kolor_hex = utils.MAPA_KOLOROW.get(nazwa, ft.Colors.INDIGO)
                zaznaczony = (self.wybrany_kolor == nazwa)
                
                self.wiersz_kolorow.controls.append(
                    ft.Container(
                        width=45, height=45,
                        bgcolor=kolor_hex,
                        shape=ft.BoxShape.CIRCLE,
                        # POPRAWKA: ft.Colors.TRANSPARENT z dużej litery
                        border=ft.Border.all(3, ft.Colors.ON_SURFACE if zaznaczony else ft.Colors.TRANSPARENT),
                        content=ft.Icon(ft.Icons.CHECK, color=ft.Colors.WHITE, size=24) if zaznaczony else None,
                        tooltip=nazwa,
                        on_click=lambda e, n=nazwa: zmien_kolor(n)
                    )
                )
            # Zaktualizuj kontrolkę tylko podczas ręcznego klikania
            if aktualizuj:
                self.wiersz_kolorow.update()

        def zmien_kolor(nazwa):
            self.wybrany_kolor = nazwa
            utils.zastosuj_motywy(self._page, nazwa)
            self._page.update()
            
            odswiez_palete(aktualizuj=True)

        # Inicjujemy paletę, ale nie odświeżamy jej jeszcze "na siłę" w UI
        odswiez_palete(aktualizuj=False)

        paleta_sekcja = ft.Column([
            utils.etykieta("Domyślny kolor aplikacji", size=13),
            ft.Text("Używany, gdy brak wybranego pojazdu oraz dla pojazdów bez własnego koloru (ustawisz go w edycji pojazdu).", size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT),
            self.wiersz_kolorow
        ], spacing=8)
        # -----------------------

        # --- CZYSTA CZERŃ (OLED) ---
        # Przełącznik zapisuje się od razu, tak samo jak przełączanie
        # jasny/ciemny z menu ⋮ — efekt widać natychmiast, więc trzymanie go
        # w "niezapisanych zmianach" formularza tylko myliłoby.
        def przelacz_czern(e):
            db.zapisz_czysta_czern(bool(self.e_czysta_czern.value))
            utils.odswiez_cache_czerni()
            utils.zastosuj_motywy(self._page, self.wybrany_kolor)
            self._page.update()

        self.e_czysta_czern = ft.Switch(
            label="Czysta czerń (OLED)",
            value=db.pobierz_czysta_czern(),
            on_change=przelacz_czern,
        )

        # --- ANIMACJE W APLIKACJI ---
        # Zapis od razu, jak przy czerni: efekt widać dopiero na kolejnym
        # ekranie, więc trzymanie tego w „niezapisanych zmianach” formularza
        # tylko odsuwałoby sprawdzenie.
        def przelacz_animacje(e):
            db.zapisz_animacje_interfejsu(bool(self.e_animacje.value))
            # Znacznik „dla tego pojazdu już grało” zerujemy, żeby świeżo
            # włączone odliczanie pokazało się zaraz po powrocie — bez czekania
            # na restart aplikacji albo zmianę auta.
            self.state.kokpit_animacja_dla = None

        self.e_animacje = ft.Switch(
            label="Animacje w aplikacji",
            value=db.czy_animacje_interfejsu(),
            on_change=przelacz_animacje,
        )

        animacje_sekcja = ft.Column([
            self.e_animacje,
            ft.Text(
                "Dwa efekty pod jednym przełącznikiem. Przy wejściu na kokpit liczby, słupki "
                "i wskaźniki doliczają do swoich wartości — pół sekundy, raz na wejście (przy "
                "starcie aplikacji i po zmianie pojazdu, nie przy każdym powrocie). Zakładki "
                "i podzakładki przechodzą jedna w drugą zamiast przeskakiwać.",
                size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
            ),
        ], spacing=4)

        # --- CHOWANIE PUSTYCH KAFELKÓW ---
        # Zapis od razu, jak przy animacjach: skutek widać na kokpicie, więc
        # trzymanie tego w „niezapisanych zmianach” formularza tylko odsuwałoby
        # sprawdzenie.
        def przelacz_puste_kafelki(e):
            db.zapisz_chowanie_pustych_kafelkow(bool(self.e_puste_kafelki.value))

        self.e_puste_kafelki = ft.Switch(
            label="Chowaj puste kafelki",
            value=db.czy_chowac_puste_kafelki(),
            on_change=przelacz_puste_kafelki,
        )

        puste_kafelki_sekcja = ft.Column([
            self.e_puste_kafelki,
            ft.Text(
                "Kafelki kokpitu, które nie mają nic do powiedzenia, znikają zamiast pokazywać "
                "myślnik: budżet bez ustawionego limitu, zasięg EV w aucie spalinowym, checklista, "
                "której nie ma, pusty magazyn, opony, których nie ma w garażu. Wracają same, gdy "
                "pojawi się treść. Kafelki czekające na dane („za mało danych”) zostają widoczne.",
                size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
            ),
        ], spacing=4)

        # --- HISTORIA WYSZUKIWAŃ ---
        def przelacz_historie_wyszukiwan(e):
            wlaczone = bool(self.e_historia_wyszukiwan.value)
            db.zapisz_zapamietywanie_wyszukiwan(wlaczone)
            if not wlaczone:
                # Wyłączenie ma znaczyć „nie chcę tej listy”, a nie „schowaj ją
                # do czasu, aż przełącznik wróci”.
                db.wyczysc_ostatnie_wyszukiwania()

        self.e_historia_wyszukiwan = ft.Switch(
            label="Zapamiętuj ostatnie wyszukiwania",
            value=db.czy_zapamietywac_wyszukiwania(),
            on_change=przelacz_historie_wyszukiwan,
        )

        historia_wyszukiwan_sekcja = ft.Column([
            self.e_historia_wyszukiwan,
            ft.Text(
                "Pod polem wyszukiwarki stoją chipy z ostatnimi frazami — jak sekcja „Ostatnio” "
                "w szufladzie. Fraza trafia tam, gdy otworzysz z niej wynik albo ekran, oraz gdy "
                "zapytanie było rozpoznanym filtrem z wynikami („marzec 2026”). Pojedynczy chip "
                "kasuje długie przytrzymanie, całą listę przycisk „Wyczyść”. Wyłączenie przełącznika "
                "kasuje zapamiętane frazy.",
                size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
            ),
        ], spacing=4)

        czern_sekcja = ft.Column([
            self.e_czysta_czern,
            ft.Text(
                "W trybie ciemnym zamienia ciemne szarości na czystą czerń. Na ekranach OLED "
                "czarny piksel jest po prostu zgaszony, więc obraz ma większy kontrast i mniej "
                "zużywa baterię. Działa też wtedy, gdy tryb „systemowy” sam przełączy telefon na ciemny.",
                size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
            ),
        ], spacing=4)

        appbar = utils.zbuduj_pasek_z_powrotem(
            page, "Ustawienia aplikacji", "/", on_save=self.zapisz,
            czy_zmieniono=self._czy_zmieniono, ikona=ft.Icons.SETTINGS
        )

        k1 = utils.karta_formularza(
            [self.e_waluta, self.e_jednostka, paleta_sekcja, ft.Divider(height=1), czern_sekcja,
             ft.Divider(height=1), animacje_sekcja, ft.Divider(height=1), puste_kafelki_sekcja,
             ft.Divider(height=1), historia_wyszukiwan_sekcja],
            "Wyświetlanie i wygląd", ft.Icons.TUNE, domyslnie_otwarte=True, page=page
        )
        k2 = utils.karta_formularza(
            [
                self.e_prog_km,
                self.e_prog_dni,
                ft.Text(
                    "Próg dni powyżej obowiązuje podzespoły z interwałem czasowym oraz każdy termin, "
                    "któremu nie ustawisz własnego wyprzedzenia poniżej.",
                    size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
                ),
                ft.Divider(height=1),
                ft.Text(
                    "Wyprzedzenie osobno dla każdego terminu — o kończącym się OC zwykle chce się "
                    "wiedzieć dużo wcześniej niż o dacie ważności apteczki.",
                    size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
                ),
            ] + [self.dropdowny_terminow[k] for k, _, _ in db.TERMINY_DOKUMENTOW] + [
                ft.Divider(height=1),
                self.e_przypomnienie_licznika,
                ft.Text(
                    "Interwały, zasięg na baku i zużycie opon liczą się z ostatniego znanego przebiegu. "
                    "Gdy przez tyle dni nie pojawi się żaden wpis z przebiegiem (tankowanie, wizyta, "
                    "serwis, odczyt), dzwonek poprosi o stan licznika — i znowu po każdym takim okresie.",
                    size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
                ),
            ],
            "Progi powiadomień", ft.Icons.NOTIFICATIONS_ACTIVE, domyslnie_otwarte=True, page=page
        )

        self.e_moje_imie = ft.TextField(
            label="Twoje imię / nazwa",
            value=moje_imie_val,
            hint_text="np. Kamil, Tata, Telefon Ani",
            **utils.styl_pola()
        )

        k3 = utils.karta_formularza(
            [self.e_moje_imie, ft.Text(
                "Widoczne przy wpisach (tankowania, serwis, koszty) we współdzielonych pojazdach — "
                "tak inni domownicy widzą, kto co dodał, a ekran „Podział kosztów” wie, kogo do czego przypisać.",
                size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
            )],
            "Twoja atrybucja przy współdzieleniu", ft.Icons.PERSON, domyslnie_otwarte=True, page=page
        )

        # Dwadzieścia checkboxów w Ustawieniach ustawiało WIDOCZNOŚĆ, a kolejność
        # układało się dwa ekrany dalej, na kokpicie — czyli jedna decyzja
        # rozdzielona na dwa miejsca. Teraz jedno i drugie robi się tam, gdzie
        # kafelki widać; tutaj zostaje droga na skróty.
        def ulozenie_kafelkow(e):
            self.state.zakladka = 0
            self.state.kokpit_otworz_ukladanie = True
            utils.przejdz(self._page, "/")

        btn_ulozenie = ft.FilledTonalButton(
            "Ułóż kafelki kokpitu",
            icon=ft.Icons.DASHBOARD_CUSTOMIZE,
            on_click=ulozenie_kafelkow,
        )
        licznik_kafelkow = ft.Text(
            f"Na kokpicie: {len(widgety_wlaczone)} z {len(db.KOKPIT_WIDGETY)} kafelków.",
            size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT,
        )

        k_kosz = utils.karta_formularza(
            [
                self.e_dni_kosza,
                ft.Text(
                    "Usunięty pojazd nie znika od razu — trafia do kosza razem z historią, "
                    "tankowaniami i zdjęciami, skąd wraca jednym kliknięciem. Kosz otworzysz "
                    "z menu ⋮ na ekranie głównym. Po upływie tego czasu pozycje kasują się "
                    "same przy starcie aplikacji; przy ustawieniu „Nigdy” czyścisz kosz sam.",
                    size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
                ),
            ],
            "Kosz na usunięte pojazdy", ft.Icons.DELETE_SWEEP, domyslnie_otwarte=True, page=page
        )

        self._stan_poczatkowy = self._migawka_formularza()

        naglowek_kokpitu = []
        if self.kokpit_auto_id:
            naglowek_kokpitu.append(ft.Container(
                padding=ft.Padding(10, 8, 10, 8),
                border_radius=utils.RADIUS["sm"],
                bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.PRIMARY),
                content=ft.Row([
                    ft.Icon(ft.Icons.DIRECTIONS_CAR, size=16, color=ft.Colors.PRIMARY),
                    ft.Text(
                        (f"Układ własny pojazdu „{state.auto_nazwa}”"
                         if self.kokpit_wlasny else
                         f"„{state.auto_nazwa}” korzysta ze wspólnego układu"),
                        size=12, weight="bold", color=ft.Colors.PRIMARY, expand=True
                    ),
                ], spacing=6)
            ))

        # Odpięcie od wspólnego układu jest odwracalne — ten przycisk kasuje
        # własny układ pojazdu, więc auto znów podąża za wspólnym.
        self.btn_kokpit_wspolny = ft.TextButton(
            "Wróć do wspólnego układu",
            icon=ft.Icons.SETTINGS_BACKUP_RESTORE,
            visible=bool(self.kokpit_auto_id) and self.kokpit_wlasny,
            on_click=self._przywroc_kokpit_wspolny,
        )

        k_kokpit = utils.karta_formularza(
            naglowek_kokpitu + [
                ft.Text(
                    "Kafelki układa się wprost na kokpicie: przytrzymaj dowolny kafelek (albo użyj "
                    "przycisku niżej), a potem przeciągnij go tam, gdzie ma stanąć. Krzyżyk zdejmuje "
                    "kafelek z kokpitu, „Dodaj kafelek” na końcu siatki przywraca zdjęte — razem "
                    "z kafelkami akcji, które od razu dodają tankowanie albo zapisują stan licznika.",
                    size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
                ),
                ft.Text(
                    "Kokpit jest osobny dla każdego pojazdu. Dopóki nie zmienisz go przy konkretnym "
                    "aucie, korzysta ono ze wspólnego układu i podąża za jego zmianami.",
                    size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
                ),
            ] + [licznik_kafelkow, btn_ulozenie, self.btn_kokpit_wspolny],
            "Kokpit ekranu głównego", ft.Icons.DASHBOARD_CUSTOMIZE, domyslnie_otwarte=True, page=page
        )

        info = ft.Container(
            padding=15,
            border_radius=10,
            bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.PRIMARY),
            content=ft.Row([
                ft.Icon(ft.Icons.INFO_OUTLINE, color=ft.Colors.PRIMARY, size=18),
                ft.Text(
                    "Zmiana waluty nie przelicza kwot — zmienia tylko wyświetlany symbol.",
                    size=12, color=ft.Colors.ON_SURFACE_VARIANT, expand=True
                )
            ], spacing=8)
        )

        liczba_duplikatow = len(db.znajdz_duplikaty_nazw(state.auto_id))
        k_duplikaty = utils.karta_formularza(
            [
                ft.Text(
                    "„Filtr oleju”, „filtr Oleju” i „filtr oleju ” to dla aplikacji jedna nazwa — "
                    "nowe wpisy same trafiają w istniejącą pisownię. To narzędzie sprząta po tym, "
                    "co zdążyło się już zdublować: w magazynie, tagach, warsztatach i podzespołach.",
                    size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
                ),
                ft.Row([
                    ft.Icon(
                        ft.Icons.WARNING_AMBER if liczba_duplikatow else ft.Icons.CHECK_CIRCLE_OUTLINE,
                        size=18,
                        color=utils.KOLOR_STATUS["warning"] if liczba_duplikatow else utils.KOLOR_STATUS["ok"],
                    ),
                    ft.Text(
                        (f"Wykryto {liczba_duplikatow} grupę wariantów" if liczba_duplikatow == 1
                         else f"Wykryto {liczba_duplikatow} grupy wariantów" if liczba_duplikatow
                         else "Brak duplikatów w tym pojeździe"),
                        size=12,
                        color=utils.KOLOR_STATUS["warning"] if liczba_duplikatow else ft.Colors.ON_SURFACE_VARIANT,
                        expand=True,
                    ),
                ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.OutlinedButton("Przejrzyj i scal", icon=ft.Icons.MERGE_TYPE, on_click=self._okno_duplikatow),
            ],
            "Duplikaty nazw", ft.Icons.MERGE_TYPE, domyslnie_otwarte=bool(liczba_duplikatow), page=page
        )

        # --- DZIENNIK BŁĘDÓW ---
        # Karta jest domyślnie zwinięta, dopóki w logu nie ma ani jednego błędu.
        # Sekcja diagnostyczna, która sama się otwiera przy każdym wejściu do
        # Ustawień, uczy oko, żeby ją pomijać — a wtedy nie zadziała w dniu,
        # w którym będzie potrzebna.
        #
        # Ikonę podaje się pozycyjnie: pole nazywa się `icon` albo `name`
        # zależnie od wersji Fleta, a podmienia je potem utils.ustaw_ikone.
        self.ikona_logu = ft.Icon(ft.Icons.HISTORY, size=18)
        self.opis_logu = ft.Text(size=12, color=ft.Colors.ON_SURFACE_VARIANT, expand=True)
        self.opis_ostatniego_bledu = ft.Text(
            size=11, italic=True, color=utils.KOLOR_STATUS["warning"], visible=False
        )
        dane_logu = self._odswiez_stan_logu(aktualizuj=False)

        k_log = utils.karta_formularza(
            [
                ft.Text(
                    "Aplikacja w dziesiątkach miejsc świadomie idzie dalej mimo błędu — inaczej "
                    "jedna nieodświeżona kontrolka potrafiłaby zabić cały ekran. Log zapisuje, "
                    "co przy tym zostało połknięte, razem z nazwą otwartego wtedy ekranu. To on "
                    "zamienia „u mnie nie działa” w informację, z którą da się cokolwiek zrobić.",
                    size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
                ),
                ft.Row([self.ikona_logu, self.opis_logu], spacing=6,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
                self.opis_ostatniego_bledu,
                ft.Row([
                    ft.FilledTonalButton("Wyślij log", icon=ft.Icons.SHARE, on_click=self._wyslij_log),
                    ft.OutlinedButton("Podgląd", icon=ft.Icons.VISIBILITY_OUTLINED,
                                      on_click=self._podglad_logu),
                    ft.TextButton("Wyczyść", icon=ft.Icons.DELETE_OUTLINE,
                                  style=ft.ButtonStyle(color=utils.KOLOR_STATUS["destructive"]),
                                  on_click=self._wyczysc_log),
                ], wrap=True, spacing=8, run_spacing=8),
                ft.Text(
                    "Wysyłany plik ma nagłówek z wersją Fleta, platformą i wersją schematu bazy — "
                    "czyli tym, o co przy każdym zgłoszeniu trzeba dopytywać osobno. Nie ma w nim "
                    "VIN-ów, numerów polis, telefonów ani kwot.",
                    size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
                ),
            ],
            "Dziennik błędów", ft.Icons.BUG_REPORT,
            domyslnie_otwarte=bool(dane_logu["bledy"]), page=page
        )

        elementy = [k1, k2, k3, k_kokpit, k_kosz, k_duplikaty, k_log, info, utils.przyciski_akcji(page, "Zapisz ustawienia", self.zapisz, "/")]

        super().__init__(
            route="/ustawienia",
            padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO
        )

    # ================= DZIENNIK BŁĘDÓW =================

    def _naglowek_logu(self):
        """Kontekst dokładany do wysyłanego pliku. Wersja Fleta i wersja schematu
        to pierwsze dwa pytania przy każdym zgłoszeniu — niech przyjadą razem
        z logiem, zamiast być przedmiotem osobnej wymiany wiadomości."""
        dane = {
            "Flet": utils.wersja_fleta(),
            "Platforma": str(getattr(self._page, "platform", "?")),
        }
        try:
            dane["Wersja schematu"] = str(db.pobierz_ustawienie("schema_version", "?"))
            dane["Pojazdy"] = str(len(db.pobierz_pojazdy(tylko_aktywne=False) or []))
        except Exception:
            log.polkniety("odczyt danych do nagłówka logu")
        return dane

    def _odswiez_stan_logu(self, aktualizuj=True):
        """Jedno miejsce, w którym karta bierze swój stan — wołane przy budowie
        widoku i po wyczyszczeniu logu."""
        dane = log.podsumowanie()

        if not dane["wpisy"]:
            utils.ustaw_ikone(self.ikona_logu, ft.Icons.CHECK_CIRCLE_OUTLINE)
            self.ikona_logu.color = utils.KOLOR_STATUS["ok"]
            self.opis_logu.value = "Log jest pusty — nic się jeszcze nie zapisało."
        else:
            ma_bledy = bool(dane["bledy"])
            utils.ustaw_ikone(self.ikona_logu, ft.Icons.BUG_REPORT if ma_bledy else ft.Icons.HISTORY)
            self.ikona_logu.color = utils.KOLOR_STATUS["error"] if ma_bledy else ft.Colors.ON_SURFACE_VARIANT
            self.opis_logu.value = (
                f"{dane['wpisy']} {log.odmien(dane['wpisy'], 'wpis', 'wpisy', 'wpisów')} · "
                f"{dane['bledy']} {log.odmien(dane['bledy'], 'błąd', 'błędy', 'błędów')}, "
                f"{dane['ostrzezenia']} {log.odmien(dane['ostrzezenia'], 'ostrzeżenie', 'ostrzeżenia', 'ostrzeżeń')} · "
                f"{log.formatuj_rozmiar(dane['rozmiar'])}"
            )

        ostatni = dane["ostatni_blad"]
        self.opis_ostatniego_bledu.value = f"Ostatni błąd: {ostatni[0]} — {ostatni[1][:100]}" if ostatni else ""
        self.opis_ostatniego_bledu.visible = bool(ostatni)

        if aktualizuj:
            try:
                self._page.update()
            except Exception:
                log.polkniety("odświeżenie karty dziennika błędów")
        return dane

    def _podglad_logu(self, e=None):
        """Ostatnie wpisy w arkuszu dolnym. Podgląd jest tu warunkiem wysyłki,
        nie ozdobą: nikt nie wysyła pliku, którego nie widział na oczy."""
        tekst = log.ostatnie_linie(200).strip() or "Log jest pusty."
        plaszczyzna = utils.powierzchnia(self._page, "blok")

        bs = ft.BottomSheet(ft.Container(padding=ft.Padding(16, 16, 16, 8), bgcolor=ft.Colors.SURFACE))
        bs.content.content = ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.BUG_REPORT, size=22, color=ft.Colors.PRIMARY),
                ft.Column([
                    ft.Text("Dziennik błędów", weight="bold", size=18, color=ft.Colors.PRIMARY),
                    ft.Text("Ostatnie wpisy, od najstarszego", size=utils.FS["caption"],
                            color=ft.Colors.ON_SURFACE_VARIANT),
                ], spacing=0, tight=True, expand=True),
                ft.IconButton(
                    icon=ft.Icons.CONTENT_COPY, icon_size=20, tooltip="Kopiuj do schowka",
                    on_click=lambda e, t=tekst: utils.kopiuj_do_schowka(self._page, t, "Log skopiowany"),
                ),
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Divider(height=14),
            ft.Container(
                padding=10,
                **plaszczyzna,
                content=ft.Column(
                    [ft.Text(tekst, size=10, font_family="monospace",
                             color=ft.Colors.ON_SURFACE_VARIANT)],
                    scroll=ft.ScrollMode.AUTO, height=320, spacing=0,
                ),
            ),
        ], tight=True, spacing=8)
        utils.otworz_dno(self._page, bs)

    async def _wyslij_log(self, e=None):
        """Nagłówek diagnostyczny plus cała treść logu, wysłane tą samą drogą co
        eksport danych: na telefonie systemowe „Udostępnij”, na komputerze okno
        zapisu pliku. Mechanizm siedzi w main.py i jest już przetestowany na
        CSV, PDF-ie i grafice „Rok w pigułce”."""
        zapisywacz = getattr(self._page, "zapisz_bajty_pliku", None)
        if zapisywacz is None:
            utils.pokaz_komunikat(self._page, "Zapis pliku jest niedostępny w tej wersji aplikacji.",
                                  utils.KOLOR_STATUS["error"])
            return

        try:
            raport = log.zbierz_raport(self._naglowek_logu())
        except Exception as ex:
            log.blad("nie udało się zebrać raportu z logu")
            utils.pokaz_komunikat(self._page, f"Nie udało się przygotować logu: {ex}", utils.KOLOR_STATUS["error"])
            return

        await zapisywacz(log.nazwa_pliku_raportu(), raport.encode("utf-8"))

    def _wyczysc_log(self, e=None):
        def wykonaj():
            log.wyczysc()
            log.zapisz("Dziennik wyczyszczony z Ustawień")
            self._odswiez_stan_logu()
            utils.pokaz_komunikat(self._page, "Dziennik błędów wyczyszczony.")

        utils.potwierdz(
            self._page, "Wyczyścić dziennik?",
            "Zapisane błędy przepadną — także te, których jeszcze nikt nie widział. "
            "Nowe wpisy zapisują się dalej.",
            wykonaj, tekst_potwierdzenia="Wyczyść",
        )

    def _okno_duplikatow(self, e=None):
        """Panel z wykrytymi wariantami tej samej nazwy. Nic nie dzieje się samo —
        scalenie każdej grupy trzeba potwierdzić, a wpis zwycięski jest widoczny
        przed kliknięciem, żeby żadna nazwa nie zniknęła bez wiedzy użytkownika."""
        grupy = db.znajdz_duplikaty_nazw(self.state.auto_id)

        bs = ft.BottomSheet(ft.Container(padding=ft.Padding(16, 16, 16, 8), bgcolor=ft.Colors.SURFACE))

        def zamknij():
            utils.zamknij_dno(self._page, bs)

        def scal(grupa):
            docelowy_id, docelowa_nazwa, _ = grupa["kanoniczna"]
            zrodla = [w[0] for w in grupa["warianty"] if w[0] != docelowy_id]

            def wykonaj():
                ile = db.scal_duplikaty_nazw(self.state.auto_id, grupa["tabela"], docelowy_id, zrodla)
                utils.pokaz_komunikat(
                    self._page,
                    f"Scalono {ile} {'wariant' if ile == 1 else 'warianty'} w „{docelowa_nazwa}”.",
                    utils.KOLOR_STATUS["ok"],
                )
                self._okno_duplikatow()

            znikajace = ", ".join(f"„{w[1]}”" for w in grupa["warianty"] if w[0] != docelowy_id)
            dopisek = (" Sztuki z duplikatów zostaną doliczone do stanu pozycji docelowej."
                       if grupa["tabela"] == "magazyn_czesci" else "")
            zamknij()
            utils.potwierdz(
                self._page, "Scalić warianty?",
                f"{znikajace} zniknie, a wszystkie powiązania przejdą na „{docelowa_nazwa}”.{dopisek} "
                "Tej operacji nie da się cofnąć.",
                wykonaj, tekst_potwierdzenia="Scal",
            )

        zawartosc = [
            ft.Row([
                ft.Icon(ft.Icons.MERGE_TYPE, size=22, color=ft.Colors.PRIMARY),
                ft.Column([
                    ft.Text("Scal duplikaty nazw", weight="bold", size=18, color=ft.Colors.PRIMARY),
                    ft.Text(f"Pojazd: {self.state.auto_nazwa}", size=utils.FS["caption"],
                            color=ft.Colors.ON_SURFACE_VARIANT),
                ], spacing=0, tight=True, expand=True),
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Divider(height=14),
        ]

        if not grupy:
            zawartosc.append(ft.Container(
                padding=ft.Padding(12, 18, 12, 18),
                alignment=ft.Alignment.CENTER,
                content=ft.Column([
                    ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINE, size=40, color=utils.KOLOR_STATUS["ok"]),
                    ft.Text("Nie znaleziono duplikatów", weight="bold"),
                    ft.Text("Żadna nazwa nie występuje w tym pojeździe w dwóch wariantach zapisu.",
                            size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
                            text_align=ft.TextAlign.CENTER),
                ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            ))
        else:
            zawartosc.append(ft.Text(
                f"Znaleziono {len(grupy)} {'grupę' if len(grupy) == 1 else 'grupy'} wariantów tej samej "
                "nazwy. Zwycięska pisownia to ta użyta najczęściej.",
                size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
            ))
            poprzednia_etykieta = None
            for grupa in grupy:
                if grupa["etykieta"] != poprzednia_etykieta:
                    poprzednia_etykieta = grupa["etykieta"]
                    zawartosc.append(ft.Container(height=4))
                    # Wersaliki same w sobie są już wyróżnieniem — pogrubienie
                    # na dokładkę robiło z podpisu grupy rzecz ważniejszą niż
                    # nazwy, które pod nim stoją.
                    zawartosc.append(utils.etykieta(grupa["etykieta"].upper()))

                docelowy_id = grupa["kanoniczna"][0]
                wiersze = []
                for w_id, w_nazwa, w_uzycia in grupa["warianty"]:
                    zwyciezca = (w_id == docelowy_id)
                    opis_uzyc = f"{w_uzycia} uż." if w_uzycia else "nieużywany"
                    wiersze.append(ft.Row([
                        ft.Icon(ft.Icons.STAR if zwyciezca else ft.Icons.ARROW_RIGHT_ALT,
                                size=14, color=ft.Colors.PRIMARY if zwyciezca else ft.Colors.ON_SURFACE_VARIANT),
                        ft.Text(f"„{w_nazwa}”", size=utils.FS["label"],
                                weight="bold" if zwyciezca else "normal",
                                color=ft.Colors.ON_SURFACE if zwyciezca else ft.Colors.ON_SURFACE_VARIANT,
                                expand=True),
                        ft.Text(opis_uzyc, size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT),
                    ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER))

                zawartosc.append(ft.Container(
                    padding=14,
                    **utils.powierzchnia(self._page, "blok"),
                    content=ft.Column(wiersze + [
                        ft.Row([
                            ft.FilledTonalButton("Scal w jedną", icon=ft.Icons.MERGE_TYPE,
                                                 on_click=lambda e, g=grupa: scal(g)),
                        ], alignment=ft.MainAxisAlignment.END),
                    ], spacing=8),
                ))

        bs.content.content = ft.Column(zawartosc, tight=True, spacing=8)
        utils.otworz_dno(self._page, bs)

    def _przywroc_kokpit_wspolny(self, e):
        """Kasuje własny układ pojazdu i przeładowuje ekran, żeby checkboxy
        pokazały to, co auto właśnie odziedziczyło ze wspólnego układu."""
        def wykonaj():
            db.przywroc_kokpit_wspolny(self.kokpit_auto_id)
            utils.przejdz(self._page, "/ustawienia")
            utils.pokaz_komunikat(
                self._page,
                f"„{self.state.auto_nazwa}” korzysta znów ze wspólnego kokpitu.",
                utils.KOLOR_STATUS["ok"],
            )

        utils.potwierdz(
            self._page,
            "Wrócić do wspólnego układu?",
            f"Własny kokpit pojazdu „{self.state.auto_nazwa}” zostanie skasowany, a auto "
            "wróci do układu wspólnego dla całego garażu. Niezapisane zmiany w tym "
            "formularzu przepadną.",
            wykonaj,
            tekst_potwierdzenia="Wróć do wspólnego",
        )

    def _migawka_formularza(self):
        return (self.e_waluta.value, self.e_jednostka.value, self.e_jednostka_ev.value, self.e_prog_km.value, self.e_prog_dni.value,
                self.e_dni_kosza.value, self.e_moje_imie.value, self.wybrany_kolor,
                self.e_przypomnienie_licznika.value,
                tuple(self.dropdowny_terminow[k].value for k, _, _ in db.TERMINY_DOKUMENTOW))

    def _czy_zmieniono(self):
        return self._migawka_formularza() != self._stan_poczatkowy

    def zapisz(self, e):
        db.zapisz_ustawienie("waluta", self.e_waluta.value)
        db.zapisz_ustawienie("jednostka_spalania", self.e_jednostka.value)
        db.zapisz_ustawienie("jednostka_zuzycia_ev", self.e_jednostka_ev.value)
        db.zapisz_ustawienie("prog_km_powiadomien", self.e_prog_km.value)
        db.zapisz_ustawienie("prog_dni_powiadomien", self.e_prog_dni.value)
        for klucz, _kolumna, _etykieta in db.TERMINY_DOKUMENTOW:
            db.zapisz_prog_dni_dokumentu(klucz, self.dropdowny_terminow[klucz].value)
        db.zapisz_dni_kosza(self.e_dni_kosza.value)
        db.zapisz_dni_przypomnienia_o_odczycie(self.e_przypomnienie_licznika.value)
        db.zapisz_moje_imie(self.e_moje_imie.value)
        
        # --- Zapis i odświeżenie wybranego koloru ---
        db.zapisz_ustawienie("kolor_motywu", self.wybrany_kolor)
        utils.zastosuj_motywy(self._page, self.wybrany_kolor)
        self._page.update()
        # Układ kokpitu NIE przechodzi przez ten formularz: kafelki zapisują się
        # w chwili przestawienia, na kokpicie.

        utils.przejdz(self._page, "/")
        utils.pokaz_komunikat(self._page, "Zapisano ustawienia!")