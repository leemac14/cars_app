import flet as ft
import db
import utils

class KalkulatorTrasyView(ft.View):
    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state

        appbar = utils.zbuduj_pasek_z_powrotem(page, "🗺️ Kalkulator Podróży", "/")

        if not self.state.auto_id:
            super().__init__(
                route="/kalkulator", padding=15, spacing=15, appbar=appbar,
                controls=[utils.ekran_braku_danych(
                    ikona=ft.Icons.DIRECTIONS_CAR,
                    tytul="Brak wybranego pojazdu",
                    opis="Wybierz pojazd, aby obliczyć koszty trasy.",
                    tekst_przycisku="Wróć na start",
                    on_click=lambda e: utils.przejdz(self._page, "/")
                )]
            )
            return

        # Pobieranie danych domyślnych z bazy (spalanie i ostatnia cena paliwa)
        spalanie_domyslne = 0.0
        cena_paliwa_domyslna = 0.0

        with db.polacz_baze() as conn:
            c = conn.cursor()
            # Obliczenie średniego spalania
            c.execute("SELECT przebieg, litry, do_pelna FROM tankowania WHERE auto_id=? ORDER BY przebieg", (self.state.auto_id,))
            tankowania = c.fetchall()
            peln_idx = [i for i, t in enumerate(tankowania) if t[2]]
            if len(peln_idx) >= 2:
                p, o = peln_idx[0], peln_idx[-1]
                d_p = int(tankowania[o][0] or 0) - int(tankowania[p][0] or 0)
                l_p = sum(float(tankowania[k][1] or 0) for k in range(p + 1, o + 1))
                if d_p > 0:
                    spalanie_domyslne = (l_p / d_p) * 100

            # Ostatnia cena paliwa z najnowszego tankowania — sortujemy w Pythonie po
            c.execute("SELECT kwota, litry, data, id FROM tankowania WHERE auto_id=? AND litry > 0", (self.state.auto_id,))
            wszystkie_z_cena = c.fetchall()
            if wszystkie_z_cena:
                ost_tank = max(wszystkie_z_cena, key=lambda t: (utils.parsuj_date(t[2]), t[3]))
                kwota = float(ost_tank[0] or 0)
                litry = float(ost_tank[1] or 1)
                cena_paliwa_domyslna = kwota / litry

        # Pola tekstowe (podpięte pod event on_change dla wyliczeń w locie)
        self.e_dystans = ft.TextField(label="Planowany dystans (km)", keyboard_type=ft.KeyboardType.NUMBER, on_change=self.przelicz, **utils.styl_pola())
        self.e_osoby = ft.TextField(label="Liczba pasażerów", value="1", keyboard_type=ft.KeyboardType.NUMBER, on_change=self.przelicz, **utils.styl_pola())
        
        self.e_spalanie = ft.TextField(
            label="Średnie spalanie (l/100km)", 
            value=utils.formatuj_liczba(spalanie_domyslne, 1) if spalanie_domyslne > 0 else "", 
            keyboard_type=ft.KeyboardType.NUMBER, on_change=self.przelicz, **utils.styl_pola()
        )
        self.e_cena = ft.TextField(
            label=f"Cena paliwa za litr ({utils.symbol_waluty()})", 
            value=utils.formatuj_liczba(cena_paliwa_domyslna, 2) if cena_paliwa_domyslna > 0 else "", 
            keyboard_type=ft.KeyboardType.NUMBER, on_change=self.przelicz, **utils.styl_pola()
        )
        self.e_dodatkowe = ft.TextField(label=f"Opłaty (autostrady, winiety) ({utils.symbol_waluty()})", value="0", keyboard_type=ft.KeyboardType.NUMBER, on_change=self.przelicz, **utils.styl_pola())

        # Dynamiczne teksty wyników
        self.t_koszt_paliwa = ft.Text("0.00", size=24, weight="bold", color=ft.Colors.PRIMARY)
        self.t_koszt_calkowity = ft.Text("0.00", size=24, weight="bold", color=ft.Colors.RED_700)
        self.t_koszt_osoba = ft.Text("0.00", size=24, weight="bold", color=ft.Colors.GREEN_700)
        self.t_litry = ft.Text("0.0 L", size=14, color=ft.Colors.ON_SURFACE_VARIANT)

        # Karty interfejsu
        k1 = utils.karta_formularza(
            [self.e_dystans, self.e_osoby],
            "Trasa i ekipa", ft.Icons.ROUTE, domyslnie_otwarte=True
        )
        
        k2 = utils.karta_formularza(
            [self.e_spalanie, self.e_cena, self.e_dodatkowe,
             ft.Text("Wartości spalania i ceny zostały pobrane automatycznie z ostatnich tankowań. Możesz je dowolnie modyfikować.", size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT)],
            "Parametry pojazdu i opłaty", ft.Icons.TUNE, domyslnie_otwarte=True
        )

        def kafel_wyniku(ikona, tytul, kontrolka_wartosci, podtytul=None):
            kolumna = [ft.Text(tytul, size=12, color=ft.Colors.ON_SURFACE_VARIANT), kontrolka_wartosci]
            if podtytul:
                kolumna.append(podtytul)
            return ft.Container(
                padding=15, border_radius=10, bgcolor=ft.Colors.with_opacity(0.04, ft.Colors.ON_SURFACE),
                content=ft.Row([
                    ft.Icon(ikona, size=30, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Column(kolumna, spacing=2)
                ], spacing=15, vertical_alignment=ft.CrossAxisAlignment.CENTER)
            )

        k3 = ft.Container(
            padding=20, border_radius=16, bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.PRIMARY),
            content=ft.Column([
                ft.Row([ft.Icon(ft.Icons.CALCULATE, color=ft.Colors.PRIMARY), ft.Text("Podsumowanie kosztów", weight="bold", size=16, color=ft.Colors.PRIMARY)], spacing=8),
                ft.Divider(height=10),
                kafel_wyniku(ft.Icons.LOCAL_GAS_STATION, "Samo paliwo", self.t_koszt_paliwa, self.t_litry),
                kafel_wyniku(ft.Icons.ACCOUNT_BALANCE_WALLET, "Całkowity koszt trasy", self.t_koszt_calkowity),
                kafel_wyniku(ft.Icons.PEOPLE, "Koszt na osobę (zrzutka)", self.t_koszt_osoba),
            ], spacing=10)
        )

        elementy = [k1, k2, k3, utils.dol_bezpieczny(30)]

        super().__init__(
            route="/kalkulator", padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO
        )

    def _pobierz_float(self, kontrolka):
        return utils.parsuj_float(kontrolka.value, 0.0)

    def przelicz(self, e):
        dystans = self._pobierz_float(self.e_dystans)
        osoby = int(utils.parsuj_float(self.e_osoby.value, 1.0))
        if osoby < 1: osoby = 1
        
        spalanie = self._pobierz_float(self.e_spalanie)
        cena = self._pobierz_float(self.e_cena)
        dodatkowe = self._pobierz_float(self.e_dodatkowe)

        potrzebne_litry = (dystans / 100.0) * spalanie
        koszt_paliwa = potrzebne_litry * cena
        koszt_calkowity = koszt_paliwa + dodatkowe
        koszt_osoba = koszt_calkowity / osoby

        waluta = utils.symbol_waluty()
        self.t_koszt_paliwa.value = f"{utils.formatuj_liczba(koszt_paliwa, 2)} {waluta}"
        self.t_koszt_calkowity.value = f"{utils.formatuj_liczba(koszt_calkowity, 2)} {waluta}"
        self.t_koszt_osoba.value = f"{utils.formatuj_liczba(koszt_osoba, 2)} {waluta}"
        self.t_litry.value = f"Potrzebne paliwo: {utils.formatuj_liczba(potrzebne_litry, 1)} L"
        
        self._page.update()