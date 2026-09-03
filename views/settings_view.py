import flet as ft
import db
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
            ft.Text("Domyślny kolor aplikacji", size=13, weight="bold", color=ft.Colors.ON_SURFACE_VARIANT),
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
            [self.e_waluta, self.e_jednostka, paleta_sekcja, ft.Divider(height=1), czern_sekcja],
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
            ] + [self.dropdowny_terminow[k] for k, _, _ in db.TERMINY_DOKUMENTOW],
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

        # Checkbox nie przyjmuje ikony, więc doklejamy ją obok — dzięki temu lista
        # w Ustawieniach używa dokładnie tych samych oznaczeń, co kafelki kokpitu.
        self.checkboxy_kokpitu = [
            ft.Checkbox(label=etykieta, value=(klucz in widgety_wlaczone), data=klucz)
            for klucz, etykieta in db.KOKPIT_WIDGETY.items()
        ]
        wiersze_kokpitu = [
            ft.Row([
                ft.Icon(utils.ikona_z_mapy(utils.IKONY_KOKPITU, chk.data), size=18, color=ft.Colors.PRIMARY),
                chk,
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)
            for chk in self.checkboxy_kokpitu
        ]

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
                    "Wybierz, które szybkie statystyki mają się pokazywać na górze ekranu głównego "
                    "(zakładka Serwis). Kolejność ustawisz przeciąganiem — przytrzymaj kafelek na "
                    "kokpicie albo dotknij ikony uchwytu na końcu karuzeli. Świeżo włączone pozycje "
                    "dopisują się na końcu i nie ruszają Twojego układu.",
                    size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
                ),
                ft.Text(
                    "Kokpit jest osobny dla każdego pojazdu. Dopóki nie zmienisz go przy konkretnym "
                    "aucie, korzysta ono ze wspólnego układu i podąża za jego zmianami.",
                    size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
                ),
            ] + wiersze_kokpitu + [self.btn_kokpit_wspolny],
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
                        color=ft.Colors.ORANGE_800 if liczba_duplikatow else ft.Colors.GREEN_700,
                    ),
                    ft.Text(
                        (f"Wykryto {liczba_duplikatow} grupę wariantów" if liczba_duplikatow == 1
                         else f"Wykryto {liczba_duplikatow} grupy wariantów" if liczba_duplikatow
                         else "Brak duplikatów w tym pojeździe"),
                        size=12,
                        color=ft.Colors.ORANGE_800 if liczba_duplikatow else ft.Colors.ON_SURFACE_VARIANT,
                        expand=True,
                    ),
                ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.OutlinedButton("Przejrzyj i scal", icon=ft.Icons.MERGE_TYPE, on_click=self._okno_duplikatow),
            ],
            "Duplikaty nazw", ft.Icons.MERGE_TYPE, domyslnie_otwarte=bool(liczba_duplikatow), page=page
        )

        elementy = [k1, k2, k3, k_kokpit, k_kosz, k_duplikaty, info, utils.przyciski_akcji(page, "Zapisz ustawienia", self.zapisz, "/")]

        super().__init__(
            route="/ustawienia",
            padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO
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
                    ft.Colors.GREEN_700,
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
                    ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINE, size=40, color=ft.Colors.GREEN_700),
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
                    zawartosc.append(ft.Text(grupa["etykieta"].upper(), size=utils.FS["caption"],
                                             weight="bold", color=ft.Colors.ON_SURFACE_VARIANT))

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

                powierzchnia = utils.powierzchnia_karty(self._page, "sm")
                zawartosc.append(ft.Container(
                    padding=14,
                    border_radius=utils.RADIUS["md"],
                    bgcolor=powierzchnia["bgcolor"],
                    border=powierzchnia["border"],
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
                ft.Colors.GREEN_700,
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
                tuple(self.dropdowny_terminow[k].value for k, _, _ in db.TERMINY_DOKUMENTOW),
                [chk.data for chk in self.checkboxy_kokpitu if chk.value])

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
        db.zapisz_moje_imie(self.e_moje_imie.value)
        
        # --- Zapis i odświeżenie wybranego koloru ---
        db.zapisz_ustawienie("kolor_motywu", self.wybrany_kolor)
        utils.zastosuj_motywy(self._page, self.wybrany_kolor)
        self._page.update()
        # --------------------------------------------
        # Checkboxy niosą tylko ZESTAW włączonych widżetów; kolejność należy do
        # kokpitu (użytkownik układa ją przeciąganiem), więc scalamy oba źródła
        # zamiast nadpisywać układ kolejnością checkboxów.
        zaznaczone = [chk.data for chk in self.checkboxy_kokpitu if chk.value]
        # Zapis idzie na AKTYWNY pojazd — a przy braku pojazdów na układ wspólny.
        db.zapisz_widgety_kokpitu(
            db.scal_widgety_kokpitu(zaznaczone, self.kokpit_auto_id), self.kokpit_auto_id
        )

        utils.przejdz(self._page, "/")
        utils.pokaz_komunikat(self._page, "Zapisano ustawienia!")