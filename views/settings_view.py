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
            
            nowy_kolor_hex = utils.MAPA_KOLOROW.get(nazwa, ft.Colors.INDIGO)
            self._page.theme = ft.Theme(color_scheme_seed=nowy_kolor_hex)
            self._page.dark_theme = ft.Theme(color_scheme_seed=nowy_kolor_hex)
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

        appbar = utils.zbuduj_pasek_z_powrotem(page, "⚙️ Ustawienia aplikacji", "/", on_save=self.zapisz)

        k1 = utils.karta_formularza(
            [self.e_waluta, self.e_jednostka, paleta_sekcja],
            "Wyświetlanie i wygląd", ft.Icons.TUNE, domyslnie_otwarte=True
        )
        k2 = utils.karta_formularza(
            [self.e_prog_km, self.e_prog_dni, ft.Text("Ten sam próg dotyczy teraz też AC, Assistance, gaśnicy i apteczki.", size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT)],
            "Progi powiadomień", ft.Icons.NOTIFICATIONS_ACTIVE, domyslnie_otwarte=True
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
            "Twoja atrybucja przy współdzieleniu", ft.Icons.PERSON, domyslnie_otwarte=True
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

        elementy = [k1, k2, k3, info, utils.przyciski_akcji(page, "✅ Zapisz ustawienia", self.zapisz, "/")]

        super().__init__(
            route="/ustawienia",
            padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO
        )

    def zapisz(self, e):
        db.zapisz_ustawienie("waluta", self.e_waluta.value)
        db.zapisz_ustawienie("jednostka_spalania", self.e_jednostka.value)
        db.zapisz_ustawienie("prog_km_powiadomien", self.e_prog_km.value)
        db.zapisz_ustawienie("prog_dni_powiadomien", self.e_prog_dni.value)
        db.zapisz_moje_imie(self.e_moje_imie.value)
        
        # --- Zapis i odświeżenie wybranego koloru ---
        db.zapisz_ustawienie("kolor_motywu", self.wybrany_kolor)
        
        nowy_kolor = utils.MAPA_KOLOROW.get(self.wybrany_kolor, ft.Colors.INDIGO)
        self._page.theme = ft.Theme(color_scheme_seed=nowy_kolor)
        self._page.dark_theme = ft.Theme(color_scheme_seed=nowy_kolor)
        self._page.update()
        # --------------------------------------------

        utils.przejdz(self._page, "/")
        utils.pokaz_komunikat(self._page, "Zapisano ustawienia!")