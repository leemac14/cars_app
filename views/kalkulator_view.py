import flet as ft
import db
import utils
from date import parsuj_date

class KalkulatorTrasyView(ft.View):
    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state

        appbar = utils.zbuduj_pasek_z_powrotem(page, "Kalkulator podróży", "/", ikona=ft.Icons.MAP)

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
                ost_tank = max(wszystkie_z_cena, key=lambda t: (parsuj_date(t[2]), t[3]))
                kwota = float(ost_tank[0] or 0)
                litry = float(ost_tank[1] or 1)
                cena_paliwa_domyslna = kwota / litry

        # Pola tekstowe (podpięte pod event on_change dla wyliczeń w locie)
        self.e_dystans = ft.TextField(label="Planowany dystans w jedną stronę (km)", keyboard_type=ft.KeyboardType.NUMBER, on_change=self.przelicz, **utils.styl_pola())
        self.c_powrot = ft.Checkbox(label="Podróż w obie strony (×2 dystans)", value=False, on_change=self.przelicz)
        self.e_osoby = ft.TextField(
            label="Liczba osób dzielących koszt (z kierowcą)",
            value="1", keyboard_type=ft.KeyboardType.NUMBER, on_change=self.przelicz, **utils.styl_pola()
        )
        
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

        # --- Zapisane trasy ---
        # Trasy się powtarzają: „do teściów” to zawsze te same 180 km, ta sama
        # ekipa i ta sama winieta. Szablon zapamiętuje WYŁĄCZNIE te parametry —
        # spalanie i cena paliwa zostają wyliczone z aktualnych tankowań, żeby
        # trasa zapisana rok temu nie liczyła po zeszłorocznych cenach.
        self.rzad_tras = ft.Row(spacing=6, run_spacing=6, wrap=True,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self.karta_tras = ft.Container(
            padding=utils.SPACING["md"], border_radius=utils.RADIUS["lg"],
            bgcolor=utils.tlo_karty(page, poziom=1),
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.BOOKMARKS, size=16, color=ft.Colors.PRIMARY),
                    ft.Text("Zapisane trasy", weight="bold", size=13, color=ft.Colors.PRIMARY, expand=True),
                    ft.TextButton("Zapisz obecną", icon=ft.Icons.BOOKMARK_ADD, on_click=lambda e: self._okno_zapisu()),
                ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                self.rzad_tras,
            ], spacing=8),
        )
        self._odswiez_trasy()

        # Dynamiczne teksty wyników
        self.t_koszt_paliwa = ft.Text("0.00", size=24, weight="bold", color=ft.Colors.PRIMARY)
        self.t_koszt_calkowity = ft.Text("0.00", size=24, weight="bold", color=ft.Colors.RED_700)
        self.t_koszt_osoba = ft.Text("0.00", size=24, weight="bold", color=ft.Colors.GREEN_700)
        self.t_litry = ft.Text("0.0 L", size=14, color=ft.Colors.ON_SURFACE_VARIANT)

        # Karty interfejsu
        k1 = utils.karta_formularza(
            [self.e_dystans, self.c_powrot, self.e_osoby],
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

        elementy = [self.karta_tras, k1, k2, k3, utils.dol_bezpieczny(30)]

        super().__init__(
            route="/kalkulator", padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO
        )

    # ==================== ZAPISANE TRASY ====================

    def _odswiez_trasy(self):
        """Przebudowuje pasek chipów. Wołane po każdym zapisie i usunięciu —
        lista trzymana w bazie, nie w polu klasy, żeby nie rozjechała się
        z rzeczywistością po powrocie z innego ekranu."""
        trasy = db.pobierz_trasy_szablony(self.state.auto_id)
        self.rzad_tras.controls.clear()

        if not trasy:
            self.rzad_tras.controls.append(ft.Text(
                "Ustaw trasę poniżej i dotknij „Zapisz obecną”, żeby nie przeliczać jej za każdym razem.",
                size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT,
            ))
        else:
            for t in trasy:
                self.rzad_tras.controls.append(self._chip_trasy(t))
        try:
            self.karta_tras.update()
        except Exception:
            # Kontener nie jest jeszcze w drzewie strony (budowa widoku) —
            # pierwszy render i tak pokaże aktualny stan.
            pass

    def _chip_trasy(self, trasa):
        opis = f"{utils.formatuj_liczba(trasa['dystans'], 0)} km"
        if trasa["powrot"]:
            opis += " ×2"
        return ft.Container(
            padding=ft.Padding(12, 7, 12, 7), border_radius=utils.RADIUS["pill"],
            bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.PRIMARY), ink=True,
            tooltip="Dotknij, aby wczytać • przytrzymaj, aby zarządzać",
            on_click=lambda e, t=trasa: self._wczytaj_trase(t),
            on_long_press=lambda e, t=trasa: self._menu_trasy(t),
            content=ft.Row([
                ft.Icon(ft.Icons.ROUTE, size=15, color=ft.Colors.PRIMARY),
                ft.Text(trasa["nazwa"], size=13, weight="bold", color=ft.Colors.PRIMARY, no_wrap=True),
                ft.Text(opis, size=11, color=ft.Colors.ON_SURFACE_VARIANT, no_wrap=True),
            ], spacing=6, tight=True),
        )

    def _wczytaj_trase(self, trasa):
        self.e_dystans.value = utils.formatuj_liczba(trasa["dystans"], 0)
        self.c_powrot.value = bool(trasa["powrot"])
        self.e_osoby.value = str(trasa["osoby"])
        self.e_dodatkowe.value = utils.formatuj_liczba(trasa["oplaty"], 2)
        self.przelicz(None)
        utils.pokaz_komunikat(self._page, f"Wczytano trasę „{trasa['nazwa']}”.")

    def _okno_zapisu(self, trasa=None):
        """Jeden dialog do zapisu nowej trasy i do zmiany nazwy istniejącej.
        Zapisujemy stan pól z ekranu, a nie przekazane wartości — użytkownik
        mógł je poprawić tuż przed kliknięciem."""
        e_nazwa = ft.TextField(
            label="Nazwa trasy (np. Do teściów)",
            value=str(trasa["nazwa"]) if trasa else "",
            **utils.styl_pola()
        )
        dystans = self._pobierz_float(self.e_dystans)
        podsumowanie = ft.Text(
            f"Zapamiętam: {utils.formatuj_liczba(dystans, 0)} km"
            + (" (tam i z powrotem)" if self.c_powrot.value else "")
            + f" • {int(utils.parsuj_float(self.e_osoby.value, 1.0)) or 1} os."
            + f" • opłaty {utils.formatuj_liczba(self._pobierz_float(self.e_dodatkowe), 2)} {utils.symbol_waluty()}",
            size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT,
        )

        def zapisz(e):
            utils.ustaw_blad(e_nazwa)
            nazwa = (e_nazwa.value or "").strip()
            if not nazwa:
                utils.ustaw_blad(e_nazwa, "Podaj nazwę trasy")
                self._page.update()
                return
            if dystans <= 0:
                utils.ustaw_blad(e_nazwa, "Najpierw podaj dystans trasy")
                self._page.update()
                return
            db.zapisz_trase_szablon(
                self.state.auto_id, nazwa, dystans,
                powrot=self.c_powrot.value,
                osoby=int(utils.parsuj_float(self.e_osoby.value, 1.0)) or 1,
                oplaty=self._pobierz_float(self.e_dodatkowe),
                trasa_id=trasa["id"] if trasa else None,
            )
            utils.zamknij_dialog(self._page, dlg)
            self._odswiez_trasy()
            utils.pokaz_komunikat(self._page, f"Zapisano trasę „{nazwa}”.")

        dlg = ft.AlertDialog(
            title=ft.Text("Zaktualizuj trasę" if trasa else "Zapisz trasę", weight="bold"),
            content=ft.Column([e_nazwa, podsumowanie], tight=True, spacing=10),
            actions=[
                ft.TextButton("Anuluj", on_click=lambda e: utils.zamknij_dialog(self._page, dlg)),
                ft.ElevatedButton("Zapisz", on_click=zapisz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY),
            ],
        )
        utils.otworz_dialog(self._page, dlg)

    def _menu_trasy(self, trasa):
        def usun():
            db.usun_trase_szablon(trasa["id"])
            self._odswiez_trasy()
            utils.pokaz_komunikat(self._page, f"Usunięto trasę „{trasa['nazwa']}”.")

        utils.pokaz_menu_kontekstowe(self._page, f"Trasa: {trasa['nazwa']}", [
            {"ikona": ft.Icons.PLAY_ARROW, "tekst": "Wczytaj do kalkulatora",
             "akcja": lambda: self._wczytaj_trase(trasa)},
            {"ikona": ft.Icons.SAVE_AS, "tekst": "Nadpisz obecnymi wartościami",
             "opis": "Zapisze dystans, powrót, liczbę osób i opłaty z ekranu",
             "akcja": lambda: self._okno_zapisu(trasa)},
            {"ikona": ft.Icons.DELETE, "tekst": "Usuń trasę", "kolor": ft.Colors.RED,
             "akcja": lambda: utils.potwierdz(
                 self._page, "Usunąć trasę?",
                 f"Czy na pewno usunąć zapisaną trasę „{trasa['nazwa']}”?", usun)},
        ])

    def _pobierz_float(self, kontrolka):
        return utils.parsuj_float(kontrolka.value, 0.0)

    def przelicz(self, e):
        dystans_wpisany = self._pobierz_float(self.e_dystans)
        dystans = dystans_wpisany * 2 if self.c_powrot.value else dystans_wpisany

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

        opis_trasy = f" • trasa {utils.formatuj_liczba(dystans, 0)} km" if dystans > 0 else ""
        if self.c_powrot.value and dystans > 0:
            opis_trasy += " (tam i z powrotem)"
        self.t_litry.value = f"Potrzebne paliwo: {utils.formatuj_liczba(potrzebne_litry, 1)} L{opis_trasy}"

        self._page.update()