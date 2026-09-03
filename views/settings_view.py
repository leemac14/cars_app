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
        widgety_wlaczone = set(db.pobierz_widgety_kokpitu())

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
            [self.e_prog_km, self.e_prog_dni, ft.Text("Ten sam próg dotyczy teraz też AC, Assistance, gaśnicy i apteczki.", size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT)],
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

        self._stan_poczatkowy = self._migawka_formularza()

        k_kokpit = utils.karta_formularza(
            [
                ft.Text(
                    "Wybierz, które szybkie statystyki mają się pokazywać na górze ekranu głównego "
                    "(zakładka Serwis). Kolejność ustawisz przeciąganiem — przytrzymaj kafelek na "
                    "kokpicie albo dotknij ikony uchwytu na końcu karuzeli. Świeżo włączone pozycje "
                    "dopisują się na końcu i nie ruszają Twojego układu.",
                    size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
                ),
            ] + wiersze_kokpitu,
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

        elementy = [k1, k2, k3, k_kokpit, info, utils.przyciski_akcji(page, "Zapisz ustawienia", self.zapisz, "/")]

        super().__init__(
            route="/ustawienia",
            padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO
        )

    def _migawka_formularza(self):
        return (self.e_waluta.value, self.e_jednostka.value, self.e_jednostka_ev.value, self.e_prog_km.value, self.e_prog_dni.value,
                self.e_moje_imie.value, self.wybrany_kolor, [chk.data for chk in self.checkboxy_kokpitu if chk.value])

    def _czy_zmieniono(self):
        return self._migawka_formularza() != self._stan_poczatkowy

    def zapisz(self, e):
        db.zapisz_ustawienie("waluta", self.e_waluta.value)
        db.zapisz_ustawienie("jednostka_spalania", self.e_jednostka.value)
        db.zapisz_ustawienie("jednostka_zuzycia_ev", self.e_jednostka_ev.value)
        db.zapisz_ustawienie("prog_km_powiadomien", self.e_prog_km.value)
        db.zapisz_ustawienie("prog_dni_powiadomien", self.e_prog_dni.value)
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
        db.zapisz_widgety_kokpitu(db.scal_widgety_kokpitu(zaznaczone))

        utils.przejdz(self._page, "/")
        utils.pokaz_komunikat(self._page, "Zapisano ustawienia!")