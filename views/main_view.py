import flet as ft
import flet_charts as fc
from datetime import datetime, timedelta
import sqlite3
import db
import utils
import asyncio
import sync

class MainView(ft.View, utils.ZaznaczanieGrupowe):
    def __init__(self, page: ft.Page, state, cb_export, cb_import, cb_theme):
        self._page = page
        self.state = state
        self.elementy = []
        self.fab = None

        appbar = utils.zbuduj_pasek_glowny(page, state, cb_export, cb_import, cb_theme)
        # --- ZMIENNE DLA GRUPOWEGO USUWANIA ---
        self.tryb_zaznaczania = False
        self.zaznaczone_id = set()
        self.tabela_cel = ""  # zapamięta z jakiej zakładki usuwamy (tankowania, inne_koszty, zadania)
        self.oryginalny_appbar = appbar
        self.karty_ref = {}   # Przechowuje referencje do kontenerów kart, by je podświetlać
        self.uzyj_wirtualizacji = False  # True gdy w tej zakładce renderujemy przewijaną listę kart
        # --------------------------------------
        navbar = ft.SafeArea(
            content=ft.NavigationBar(
                destinations=[
                    ft.NavigationBarDestination(icon=ft.Icons.BUILD_CIRCLE_OUTLINED, selected_icon=ft.Icons.BUILD_CIRCLE, label="Serwis"),
                    ft.NavigationBarDestination(icon=ft.Icons.LOCAL_GAS_STATION_OUTLINED, selected_icon=ft.Icons.LOCAL_GAS_STATION, label="Paliwo"),
                    ft.NavigationBarDestination(icon=ft.Icons.RECEIPT_LONG_OUTLINED, selected_icon=ft.Icons.RECEIPT_LONG, label="Inne"),
                    ft.NavigationBarDestination(icon=ft.Icons.PIE_CHART_OUTLINE, selected_icon=ft.Icons.PIE_CHART, label="Statystyki"),
                ],
                on_change=self.zmien_zakladke,
                selected_index=self.state.zakladka,
            ),
            avoid_intrusions_top=False,
        )

        if not self.state.auto_id:
            self.elementy.append(
                utils.ekran_braku_danych(
                    ikona=ft.Icons.DIRECTIONS_CAR,
                    tytul="Witaj w menedżerze!",
                    opis="Nie masz jeszcze dodanego żadnego pojazdu. Dodaj swój pierwszy pojazd, aby rozpocząć zarządzanie.",
                    tekst_przycisku="Dodaj pojazd",
                    on_click=lambda e: utils.przejdz(self._page, "/auto/nowy")
                )
            )
        else:
            self.buduj_naglowek_auta()
            if self.state.zakladka == 0: self.buduj_serwis()
            elif self.state.zakladka == 1: self.buduj_tankowania()
            elif self.state.zakladka == 2: self.buduj_inne()
            elif self.state.zakladka == 3: self.buduj_statystyki()

        self.elementy.append(utils.dol_bezpieczny(10))

        super().__init__(
            route="/",
            padding=15,
            spacing=15,                 # Zastępuje odstępy, które wcześniej robił wrapper
            appbar=appbar,
            navigation_bar=navbar,
            controls=self.elementy,     # Przekazujemy elementy bezpośrednio
            scroll=ft.ScrollMode.AUTO,  # Włączamy natywne przewijanie całej strony
            floating_action_button=self.fab
        )

    def zmien_zakladke(self, e):
        self.state.zakladka = int(e.control.selected_index)
        utils.przejdz(self._page, "/")

    async def _synchronizuj_teraz(self):
        try:
            wyslano, pobrano = await asyncio.to_thread(sync.synchronizuj_wszystko, self.state.auto_id)
            utils.przejdz(self._page, "/")
            utils.pokaz_komunikat(self._page, f"Wysłano {wyslano}, pobrano {pobrano} nowych rekordów.")
        except Exception as ex:
            utils.pokaz_komunikat(self._page, f"Błąd synchronizacji: {ex}", ft.Colors.RED_700)

    def _buduj_fab_szybkich_akcji(self):
        akcje = [
            (ft.Icons.LOCAL_GAS_STATION, "Tankowanie", lambda e: utils.przejdz(self._page, "/tankowanie/nowe")),
            (ft.Icons.RECEIPT_LONG, "Inny koszt", lambda e: utils.przejdz(self._page, "/inne/nowy")),
            (ft.Icons.HANDYMAN, "Podzespół", lambda e: utils.przejdz(self._page, "/zadanie/nowy")),
            (ft.Icons.HOME_REPAIR_SERVICE, "Wizyta w warsztacie", lambda e: utils.przejdz(self._page, "/wizyty/nowa")),
            (ft.Icons.CHECKLIST_RTL, "Do zrobienia", lambda e: utils.przejdz(self._page, "/do-zrobienia/nowe")),
        ]
        return utils.fab_speed_dial(self._page, akcje, tooltip="Szybkie dodawanie")

    # ================= KOKPIT / DASHBOARD STARTOWY (karuzela pozioma) =================
    def _buduj_kokpit(self):
        """Mini-dashboard nad listą podzespołów, złożony z widżetów wybranych przez
        użytkownika w Ustawieniach (patrz db.KOKPIT_WIDGETY / db.pobierz_widgety_kokpitu).
        Renderowany jako pozioma, przewijalna karuzela (ft.Row scroll=AUTO) z kafelkami
        o stałej szerokości — zamiast układu kolumnowego z parowaniem "połówek"."""
        wlaczone = db.pobierz_widgety_kokpitu()
        if not wlaczone:
            return ft.Container()

        SZER_KAFLA = 160

        # --- Dane wspólne, liczone tylko gdy faktycznie potrzebne przez wybrane widżety ---
        potrzebne_mc = {"koszt_miesiac", "wykres"} & set(wlaczone)
        dane_mc = db.pobierz_koszty_miesieczne(self.state.auto_id, 6) if potrzebne_mc else []

        potrzebne_porownanie = {"koszt_km", "spalanie"} & set(wlaczone)
        dane_porownanie = db.pobierz_dane_do_porownania(self.state.auto_id) if potrzebne_porownanie else None
        dane_porownanie = dane_porownanie or {}

        def idz_do_statystyk(podzakladka=0):
            def handler(e):
                self.state.zakladka = 3
                self.state.stat_podzakladka = podzakladka
                utils.przejdz(self._page, "/")
            return handler

        def idz_do_zakladki(idx):
            def handler(e):
                self.state.zakladka = idx
                utils.przejdz(self._page, "/")
            return handler

        def kafel_wartosci(ikona, kolor_ikony, etykieta, wartosc, on_click):
            return ft.Container(
                width=SZER_KAFLA, padding=15, border_radius=utils.RADIUS["lg"],
                bgcolor=utils.tlo_karty(self._page, poziom=1),
                ink=True, on_click=on_click,
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ikona, size=15, color=kolor_ikony),
                        ft.Text(etykieta, size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                    ], spacing=6),
                    ft.Text(wartosc, size=utils.FS["title"], weight="bold", no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                ], spacing=4),
            )

        def widget_koszt_miesiac():
            koszt_biezacy = dane_mc[-1][2] if dane_mc else 0.0
            koszt_poprzedni = dane_mc[-2][2] if len(dane_mc) >= 2 else None

            if koszt_poprzedni and koszt_poprzedni > 0:
                zmiana = ((koszt_biezacy - koszt_poprzedni) / koszt_poprzedni) * 100
                if zmiana > 5:
                    t_ikona, t_kolor = ft.Icons.TRENDING_UP, ft.Colors.RED_700
                    t_tekst = f"+{utils.formatuj_liczba(zmiana, 0)}%"
                elif zmiana < -5:
                    t_ikona, t_kolor = ft.Icons.TRENDING_DOWN, ft.Colors.GREEN_700
                    t_tekst = f"{utils.formatuj_liczba(zmiana, 0)}%"
                else:
                    t_ikona, t_kolor = ft.Icons.TRENDING_FLAT, ft.Colors.ON_SURFACE_VARIANT
                    t_tekst = "Podobnie"
            else:
                t_ikona, t_kolor = ft.Icons.INFO_OUTLINE, ft.Colors.ON_SURFACE_VARIANT
                t_tekst = "Brak danych"

            return ft.Container(
                width=SZER_KAFLA, padding=15, border_radius=utils.RADIUS["lg"],
                bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.PRIMARY),
                ink=True, on_click=idz_do_statystyk(0),
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET, size=15, color=ft.Colors.PRIMARY),
                        ft.Text("Koszt w mies.", size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                    ], spacing=6),
                    ft.Text(f"{utils.formatuj_liczba(koszt_biezacy)} {utils.symbol_waluty()}", size=utils.FS["title"], weight="bold", no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Row([
                        ft.Icon(t_ikona, size=13, color=t_kolor),
                        ft.Text(t_tekst, size=utils.FS["caption"], color=t_kolor, no_wrap=True),
                    ], spacing=4),
                ], spacing=4),
            )

        def widget_termin():
            powiadomienia = db.pobierz_powiadomienia(self.state.auto_id)
            if powiadomienia:
                p = powiadomienia[0]
                kolor_p = ft.Colors.RED_700 if p["status"] == "przeterminowane" else ft.Colors.ORANGE_700
                ikona_p = ft.Icons.WARNING if p["status"] == "przeterminowane" else ft.Icons.HOURGLASS_BOTTOM
                dodatek = f"  (+{len(powiadomienia) - 1})" if len(powiadomienia) > 1 else ""

                tresc = ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.EVENT, size=15, color=ft.Colors.PRIMARY),
                        ft.Text(f"Termin{dodatek}", size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                    ], spacing=6),
                    ft.Text(str(p["tytul"]), size=utils.FS["title"], weight="bold", no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Row([
                        ft.Icon(ikona_p, size=13, color=kolor_p),
                        ft.Text(p["opis"], size=utils.FS["caption"], color=kolor_p, no_wrap=True),
                    ], spacing=4),
                ], spacing=4)

                trasa_termin = p.get("trasa")
                on_klik = (lambda e, t=trasa_termin: utils.przejdz(self._page, t)) if trasa_termin \
                    else (lambda e: utils.pokaz_panel_powiadomien(self._page, self.state))
                tlo = ft.Colors.with_opacity(0.08, kolor_p)
            else:
                tresc = ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.EVENT_AVAILABLE, size=15, color=ft.Colors.GREEN_700),
                        ft.Text("Termin", size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                    ], spacing=6),
                    ft.Text("Na czas 🎉", size=utils.FS["title"], weight="bold", color=ft.Colors.GREEN_700),
                    ft.Text("Brak terminów", size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT),
                ], spacing=4)
                on_klik = None
                tlo = ft.Colors.with_opacity(0.08, ft.Colors.GREEN_700)

            return ft.Container(
                width=SZER_KAFLA, padding=15, border_radius=utils.RADIUS["lg"],
                bgcolor=tlo, ink=on_klik is not None, on_click=on_klik,
                content=tresc,
            )

        def widget_wykres():
            maks_mc = max((s for _, _, s in dane_mc), default=0)
            dzis = datetime.now()
            slupki = []
            for rok, mies, suma in dane_mc:
                wysokosc = max(4, int((suma / maks_mc) * 60)) if maks_mc > 0 else 4
                biezacy = (rok == dzis.year and mies == dzis.month)
                slupki.append(
                    ft.Column([
                        ft.Container(
                            width=20, height=wysokosc, border_radius=5,
                            bgcolor=ft.Colors.PRIMARY if biezacy else ft.Colors.with_opacity(0.35, ft.Colors.PRIMARY),
                            tooltip=f"{utils.MIESIACE_NAZWY[mies - 1]} {rok}: {utils.formatuj_liczba(suma)} {utils.symbol_waluty()}",
                            animate=ft.Animation(300, ft.AnimationCurve.EASE_OUT),
                        ),
                        ft.Text(f"{mies:02d}", size=10, weight="bold" if biezacy else "normal",
                                color=ft.Colors.PRIMARY if biezacy else ft.Colors.ON_SURFACE_VARIANT),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4)
                )

            return ft.Container(
                width=SZER_KAFLA + 100, padding=15, border_radius=utils.RADIUS["lg"],
                bgcolor=utils.tlo_karty(self._page, poziom=1),
                ink=True, on_click=idz_do_statystyk(1),
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.BAR_CHART, size=15, color=ft.Colors.PRIMARY),
                        ft.Text("Wydatki 6 mies.", size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT),
                    ], spacing=6),
                    ft.Row(slupki, alignment=ft.MainAxisAlignment.SPACE_EVENLY, vertical_alignment=ft.CrossAxisAlignment.END),
                ], spacing=10),
            )

        def widget_koszt_km():
            koszt_km = dane_porownanie.get("koszt_km")
            wartosc = f"{utils.formatuj_liczba(koszt_km, 2)} {utils.symbol_waluty()}/km" if koszt_km else "Brak danych"
            return kafel_wartosci(ft.Icons.ADD_ROAD, ft.Colors.PURPLE_700, "Koszt / km", wartosc, idz_do_statystyk(0))

        def widget_spalanie():
            spalanie = dane_porownanie.get("spalanie")
            wartosc = utils.formatuj_spalanie(spalanie) if spalanie else "Za mało danych"
            return kafel_wartosci(ft.Icons.LOCAL_GAS_STATION, ft.Colors.TEAL_700, "Śr. spalanie", wartosc, idz_do_zakladki(1))

        def widget_przebieg_dzienny():
            sredni = db.oblicz_sredni_dzienny_przebieg(self.state.auto_id)
            wartosc = f"{utils.formatuj_liczba(sredni, 1)} km/dzień" if sredni else "Brak danych"
            return kafel_wartosci(ft.Icons.TIMELAPSE, ft.Colors.BLUE_GREY_700, "Śr. dzienny", wartosc,
                                   lambda e: utils.przejdz(self._page, "/przebieg"))

        budowniczy = {
            "koszt_miesiac": widget_koszt_miesiac,
            "termin": widget_termin,
            "wykres": widget_wykres,
            "koszt_km": widget_koszt_km,
            "spalanie": widget_spalanie,
            "przebieg_dzienny": widget_przebieg_dzienny,
        }

        kafelki = [budowniczy[wid]() for wid in wlaczone if wid in budowniczy]
        if not kafelki:
            return ft.Container()

        return ft.Row(kafelki, spacing=10, scroll=ft.ScrollMode.AUTO)

    def potwierdz_grupowe_usuwanie(self, e):
        ile = len(self.zaznaczone_id)
        def wykonaj():
            if self.tabela_cel == "zadania":
                wynik = db.usun_wiele_zadan_z_cofnieciem(list(self.zaznaczone_id))
            else:
                wynik = db.usun_wiele_z_cofnieciem(self.tabela_cel, list(self.zaznaczone_id))

            self.zakoncz_zaznaczanie()
            utils.przejdz(self._page, "/")
            utils.pokaz_komunikat_cofnij(self._page, f"Pomyślnie usunięto {ile} elementów.", wynik)
        utils.potwierdz(self._page, "Usuwanie", f"Czy na pewno usunąć {ile} elementów?", wykonaj)

    # ================= KOMPAKTOWA KARTA POJAZDU =================
    def buduj_naglowek_auta(self):
        with db.polacz_baze() as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT id, nazwa FROM samochody ORDER BY nazwa")
            auta = c.fetchall()
            c.execute("SELECT nr_rej, zdjecie_glowne FROM samochody WHERE id=?", (self.state.auto_id,))
            w = c.fetchone()

        if not w: return

        aktualny_przebieg = db.pobierz_aktualny_przebieg(self.state.auto_id)

        idx = 0
        for i, a in enumerate(auta):
            if a[0] == self.state.auto_id:
                idx = i
                break

        poprzedni_id, poprzedni_nazwa = auta[(idx - 1) % len(auta)]
        nastepny_id, nastepny_nazwa = auta[(idx + 1) % len(auta)]

        def on_prev(e):
            self.state.auto_id = poprzedni_id
            self.state.auto_nazwa = str(poprzedni_nazwa)
            utils.przejdz(self._page, "/")

        def on_next(e):
            self.state.auto_id = nastepny_id
            self.state.auto_nazwa = str(nastepny_nazwa)
            utils.przejdz(self._page, "/")

        def pokaz_wybor_aut(e):
            bs = ft.BottomSheet(ft.Container())
            kafelki_aut = []

            def wybierz(aid, an):
                for kafel, k_aid in kafelki_aut:
                    if k_aid == aid:
                        kafel.leading.icon = ft.Icons.CHECK_CIRCLE
                        kafel.leading.color = ft.Colors.PRIMARY
                        kafel.title.weight = "bold"
                    else:
                        kafel.leading.icon = ft.Icons.DIRECTIONS_CAR
                        kafel.leading.color = ft.Colors.ON_SURFACE_VARIANT
                        kafel.title.weight = "normal"

                try:
                    self._page.update()
                except Exception:
                    pass

                self.state.auto_id = aid
                self.state.auto_nazwa = str(an)
                utils.zamknij_dno(self._page, bs)
                utils.przejdz(self._page, "/")

            def dodaj():
                utils.zamknij_dno(self._page, bs)
                utils.przejdz(self._page, "/auto/nowy")

            pozycje_aut = [
                ft.Text("Wybierz pojazd", weight="bold", size=18, color=ft.Colors.PRIMARY),
                ft.Divider(height=1)
            ]

            for a_id, a_nazwa in auta:
                zaznaczone = (a_id == self.state.auto_id)
                kafel = ft.ListTile(
                    leading=ft.Icon(
                        ft.Icons.CHECK_CIRCLE if zaznaczone else ft.Icons.DIRECTIONS_CAR,
                        color=ft.Colors.PRIMARY if zaznaczone else ft.Colors.ON_SURFACE_VARIANT
                    ),
                    title=ft.Text(str(a_nazwa), weight="bold" if zaznaczone else "normal"),
                    on_click=lambda ev, aid=a_id, an=a_nazwa: wybierz(aid, an)
                )
                kafelki_aut.append((kafel, a_id))
                pozycje_aut.append(kafel)

            pozycje_aut.append(ft.Divider(height=1))
            pozycje_aut.append(
                ft.ListTile(
                    leading=ft.Icon(ft.Icons.ADD, color=ft.Colors.GREEN),
                    title=ft.Text("Dodaj nowy pojazd", color=ft.Colors.GREEN),
                    on_click=lambda ev: dodaj()
                )
            )

            bs.content = ft.Container(
                padding=20,
                bgcolor=ft.Colors.SURFACE,
                content=ft.Column(pozycje_aut, tight=True, scroll=ft.ScrollMode.AUTO)
            )
            utils.otworz_dno(self._page, bs)

        def kolor_daty(d_str):
            if not d_str: return ft.Colors.ON_SURFACE_VARIANT, "Brak"
            try:
                d_obj = datetime.strptime(str(d_str), "%d.%m.%Y").date()
                roz = (d_obj - datetime.now().date()).days
                if roz < 0: return ft.Colors.RED_700, f"⚠️ {d_str}"
                elif roz <= 30: return ft.Colors.ORANGE_700, f"⏳ {d_str}"
                return ft.Colors.GREEN_700, f"✅ {d_str}"
            except Exception:
                return ft.Colors.ON_SURFACE_VARIANT, str(d_str)

        kondycja = db.oblicz_kondycje_pojazdu(self.state.auto_id)
        kolor_kond, ikona_kond, etykieta_kond = utils.wskaznik_kondycji(kondycja)

        # --- WSZYSTKO, CO ZNIKNĘŁO Z GŁÓWNEJ KARTY (OC, PT, VIN, Kondycja) —
        # dostępne teraz WYŁĄCZNIE po kliknięciu przycisku Info ---
        def pokaz_info_auta(e):
            with db.polacz_baze() as conn:
                conn.row_factory = sqlite3.Row
                c = conn.cursor()
                c.execute(
                    "SELECT nazwa, nr_rej, vin, rok_produkcji, pojemnosc_silnika, moc_silnika, "
                    "typ_paliwa, skrzynia_biegow, notatki, wycieraczki_przod, wycieraczki_tyl, "
                    "cisnienie_przod, cisnienie_tyl, olej_typ, olej_pojemnosc, akumulator, "
                    "zarowki_mijania, zarowki_drogowe, oc_data, przeglad_data, "
                    "ac_data, assistance_data, gasnica_data, apteczka_data, "
                    "marka, model, generacja "
                    "FROM samochody WHERE id=?",
                    (self.state.auto_id,)
                )
                w_info = c.fetchone()

            if not w_info: return

            def wiersz_info(ikona, etykieta, wartosc):
                return ft.Row([
                    ft.Icon(ikona, color=ft.Colors.ON_SURFACE_VARIANT, size=20),
                    ft.Text(f"{etykieta}:", weight="bold", size=14, color=ft.Colors.ON_SURFACE_VARIANT, width=110),
                    ft.Text(str(wartosc) if wartosc else "-", size=14, expand=True, color=ft.Colors.ON_SURFACE)
                ])

            def wiersz_termin(ikona, etykieta, data_str):
                kolor, tekst = kolor_daty(data_str)
                return ft.Row([
                    ft.Icon(ikona, color=kolor, size=20),
                    ft.Text(f"{etykieta}:", weight="bold", size=14, color=ft.Colors.ON_SURFACE_VARIANT, width=110),
                    ft.Text(tekst, size=14, weight="bold", color=kolor, expand=True)
                ])

            def polacz_wartosci(*wartosci):
                czesci = [str(x) for x in wartosci if x]
                return " / ".join(czesci) if czesci else None

            pojemnosc_tekst = f"{w_info['pojemnosc_silnika']} cm³" if w_info["pojemnosc_silnika"] else ""
            moc_tekst = f"{w_info['moc_silnika']} KM" if w_info["moc_silnika"] else ""
            wycieraczki_tekst = polacz_wartosci(w_info["wycieraczki_przod"], w_info["wycieraczki_tyl"])
            cisnienie_tekst = polacz_wartosci(w_info["cisnienie_przod"], w_info["cisnienie_tyl"])
            olej_tekst = ", ".join(x for x in (w_info["olej_typ"], w_info["olej_pojemnosc"]) if x) or None
            zarowki_tekst = polacz_wartosci(w_info["zarowki_mijania"], w_info["zarowki_drogowe"])

            bs_info = ft.BottomSheet(
                ft.Container(
                    padding=25,
                    bgcolor=ft.Colors.SURFACE,
                    border_radius=20,
                    content=ft.Column([
                        ft.Row([
                            ft.Icon(ft.Icons.INFO, size=28, color=ft.Colors.PRIMARY),
                            ft.Text("Specyfikacja pojazdu", weight="bold", size=20, color=ft.Colors.PRIMARY)
                        ], spacing=10),
                        ft.Container(
                            padding=ft.Padding(8, 4, 8, 4),
                            border_radius=14,
                            bgcolor=ft.Colors.with_opacity(0.13, kolor_kond),
                            content=ft.Row([
                                ft.Icon(ikona_kond, size=13, color=kolor_kond),
                                ft.Text(
                                    f"Kondycja: {kondycja if kondycja is not None else '-'}/100 ({etykieta_kond})",
                                    size=12, weight="bold", color=kolor_kond
                                )
                            ], spacing=5, tight=True)
                        ),
                        ft.Divider(height=15),
                        wiersz_info(ft.Icons.DIRECTIONS_CAR, "Marka", w_info["marka"]),
                        wiersz_info(ft.Icons.DIRECTIONS_CAR_FILLED, "Model", w_info["model"]),
                        wiersz_info(ft.Icons.STARS, "Generacja", w_info["generacja"]),
                        wiersz_info(ft.Icons.BADGE, "Rejestracja", w_info["nr_rej"]),
                        wiersz_info(ft.Icons.NUMBERS, "VIN", w_info["vin"]),
                        wiersz_info(ft.Icons.CALENDAR_TODAY, "Rocznik", w_info["rok_produkcji"]),

                        ft.Container(height=5),
                        wiersz_info(ft.Icons.LOCAL_GAS_STATION, "Paliwo", w_info["typ_paliwa"]),
                        wiersz_info(ft.Icons.SETTINGS_INPUT_COMPONENT, "Skrzynia", w_info["skrzynia_biegow"]),
                        wiersz_info(ft.Icons.SPEED, "Silnik", pojemnosc_tekst),
                        wiersz_info(ft.Icons.BOLT, "Moc silnika", moc_tekst),

                        ft.Divider(height=15),
                        ft.Text("🛡️ Ważne terminy", weight="bold", size=14, color=ft.Colors.ON_SURFACE_VARIANT),
                        wiersz_termin(ft.Icons.SHIELD, "Polisa OC", w_info["oc_data"]),
                        wiersz_termin(ft.Icons.FACT_CHECK, "Przegląd", w_info["przeglad_data"]),
                        wiersz_termin(ft.Icons.SHIELD, "Polisa AC", w_info["ac_data"]),
                        wiersz_termin(ft.Icons.SUPPORT_AGENT, "Assistance", w_info["assistance_data"]),
                        wiersz_termin(ft.Icons.LOCAL_FIRE_DEPARTMENT, "Gaśnica", w_info["gasnica_data"]),
                        wiersz_termin(ft.Icons.MEDICAL_SERVICES, "Apteczka", w_info["apteczka_data"]),

                        ft.Divider(height=15),
                        ft.Text("🛒 Ściągawka do sklepu", weight="bold", size=14, color=ft.Colors.ON_SURFACE_VARIANT),
                        wiersz_info(ft.Icons.WATER_DROP, "Wycieraczki", wycieraczki_tekst),
                        wiersz_info(ft.Icons.AIR, "Ciśnienie opon", cisnienie_tekst),
                        wiersz_info(ft.Icons.OPACITY, "Olej silnikowy", olej_tekst),
                        wiersz_info(ft.Icons.BATTERY_FULL, "Akumulator", w_info["akumulator"]),
                        wiersz_info(ft.Icons.LIGHTBULB, "Żarówki", zarowki_tekst),

                        ft.Divider(height=15),
                        ft.Text("Notatki:", weight="bold", size=14, color=ft.Colors.ON_SURFACE_VARIANT),
                        ft.Text(str(w_info["notatki"]) if w_info["notatki"] else "Brak dodatkowych notatek.", size=14, italic=not bool(w_info["notatki"]))
                    ], tight=True, spacing=8)
                )
            )
            utils.otworz_dno(self._page, bs_info)

        # --- SZYBKA AKTUALIZACJA PRZEBIEGU (bez sztucznego tankowania/wpisu) ---
        def pokaz_szybka_aktualizacja_przebiegu(e):
            pole_przebiegu = ft.TextField(
                label="Aktualny przebieg (km)",
                value=str(aktualny_przebieg) if aktualny_przebieg else "",
                hint_text="np. 152300",
                keyboard_type=ft.KeyboardType.NUMBER,
                autofocus=True,
                **utils.styl_pola()
            )

            def zapisz(e2):
                pole_przebiegu.error_text = None
                nowy = utils.parsuj_int(pole_przebiegu.value, None)
                if nowy is None or nowy <= 0:
                    pole_przebiegu.error_text = "Podaj poprawny przebieg"
                    self._page.update()
                    return

                if utils.sprawdz_podejrzany_przebieg(self._page, pole_przebiegu, self.state.auto_id, nowy, tabela="odczyty_przebiegu"):
                    return

                db.dodaj_odczyt_przebiegu(self.state.auto_id, nowy)
                utils.zamknij_dialog(self._page, dlg)
                utils.przejdz(self._page, "/")
                utils.pokaz_komunikat(self._page, "Zaktualizowano stan licznika!")

            def zobacz_historie(e2):
                utils.zamknij_dialog(self._page, dlg)
                utils.przejdz(self._page, "/przebieg")

            dlg = ft.AlertDialog(
                modal=True,
                title=ft.Row([ft.Icon(ft.Icons.SPEED, color=ft.Colors.PRIMARY), ft.Text("Aktualizacja przebiegu", weight="bold", size=16, expand=True)], spacing=8),
                content=ft.Column([
                    ft.Text(
                        "Wpisz aktualny stan licznika z deski rozdzielczej. To tylko odświeży stan km — nie tworzy tankowania ani wpisu serwisowego.",
                        size=12, color=ft.Colors.ON_SURFACE_VARIANT
                    ),
                    pole_przebiegu,
                    ft.Container(height=5),
                    ft.TextButton("📈 Przejdź do historii odczytów", on_click=zobacz_historie)
                ], tight=True, spacing=10),
                actions=[
                    ft.TextButton("Anuluj", on_click=lambda e2: utils.zamknij_dialog(self._page, dlg)),
                    ft.ElevatedButton("Zapisz", on_click=zapisz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY)
                ],
                actions_alignment=ft.MainAxisAlignment.END
            )
            utils.otworz_dialog(self._page, dlg)
        # ------------------------------------------------------

        # --- KOMPAKTOWY AWATAR (60x60) ZAMIAST DUŻEGO BANERA ---
        zdjecie_glowne = w["zdjecie_glowne"]
        if zdjecie_glowne:
            awatar = ft.Image(
                src=utils.abs_zalacznik(zdjecie_glowne), width=60, height=60,
                fit="cover", border_radius=utils.RADIUS["lg"],
            )
        else:
            awatar = ft.Container(
                width=60, height=60, border_radius=utils.RADIUS["lg"],
                bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.PRIMARY),
                alignment=ft.Alignment.CENTER,
                content=ft.Icon(ft.Icons.DIRECTIONS_CAR, size=28, color=ft.Colors.PRIMARY),
            )

        tytulowy_wiersz = ft.Container(
            content=ft.Row([
                ft.Text(
                    str(self.state.auto_nazwa), size=16, weight="bold", color=ft.Colors.PRIMARY,
                    no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS,
                ),
                ft.Icon(ft.Icons.ARROW_DROP_DOWN, color=ft.Colors.PRIMARY, size=18)
            ], spacing=0, tight=True),
            on_click=pokaz_wybor_aut,
            tooltip="Dotknij, aby wybrać z listy",
        )

        wiersz_rejestracja = ft.Row([
            ft.Icon(ft.Icons.BADGE, size=13, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Text(str(w["nr_rej"]) if w["nr_rej"] else "Brak rej.", size=13, weight="bold", color=ft.Colors.ON_SURFACE_VARIANT),
        ], spacing=4)

        wiersz_przebieg = ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.SPEED, size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Text(f"{utils.formatuj_liczba(aktualny_przebieg, 0)} km", size=13, weight="bold"),
                ft.Icon(ft.Icons.EDIT, size=11, color=ft.Colors.PRIMARY)
            ], spacing=5),
            on_click=pokaz_szybka_aktualizacja_przebiegu,
            on_long_press=lambda e: utils.przejdz(self._page, "/przebieg"),
            tooltip="Dotknij: aktualizuj  •  Przytrzymaj: historia odczytów",
        )

        kolumna_tekstowa = ft.Column([
            tytulowy_wiersz,
            wiersz_rejestracja,
            wiersz_przebieg,
        ], spacing=3, expand=True)

        przyciski_karty = ft.Column([
            ft.IconButton(
                icon=ft.Icons.INFO_OUTLINE, icon_size=20, icon_color=ft.Colors.PRIMARY,
                tooltip="Szczegóły pojazdu (OC, PT, VIN, kondycja...)", on_click=pokaz_info_auta,
                style=ft.ButtonStyle(padding=0), width=32, height=32,
            ),
            ft.IconButton(
                icon=ft.Icons.EDIT, icon_size=16, icon_color=ft.Colors.ON_SURFACE_VARIANT,
                tooltip="Edytuj pojazd",
                on_click=lambda e: utils.przejdz(self._page, f"/auto/edytuj/{self.state.auto_id}"),
                style=ft.ButtonStyle(padding=0), width=32, height=32,
            ),
        ], spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER)

        karta_auta = ft.Card(
            elevation=1,
            content=ft.Container(
                padding=12, border_radius=10,
                content=ft.Row([awatar, kolumna_tekstowa, przyciski_karty], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER)
            )
        )

        wiele_aut = len(auta) > 1

        wiersz_karty_z_nawigacja = ft.Row([
            ft.IconButton(
                icon=ft.Icons.CHEVRON_LEFT, icon_size=26, icon_color=ft.Colors.PRIMARY,
                tooltip="Poprzedni pojazd", on_click=on_prev, visible=wiele_aut,
                style=ft.ButtonStyle(padding=0),
            ),
            ft.Container(karta_auta, expand=True),
            ft.IconButton(
                icon=ft.Icons.CHEVRON_RIGHT, icon_size=26, icon_color=ft.Colors.PRIMARY,
                tooltip="Następny pojazd", on_click=on_next, visible=wiele_aut,
                style=ft.ButtonStyle(padding=0),
            ),
        ], spacing=2, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        self.elementy.append(wiersz_karty_z_nawigacja)

    # ================= SEKCJA SERWIS (nawigacja przeniesiona do menu ⋮) =================
    def buduj_serwis(self):
        wspolny_id, _ = sync.czy_udostepniony(self.state.auto_id)

        magazyn_cnt = 0
        do_zrobienia_cnt = 0
        try:
            with db.polacz_baze() as conn:
                c = conn.cursor()
                # Licznik ma sygnalizować NISKI STAN, a nie samą liczbę pozycji
                c.execute("SELECT COUNT(*) FROM magazyn_czesci WHERE auto_id=? AND ilosc <= COALESCE(prog_ostrzezenia, 1)", (self.state.auto_id,))
                magazyn_cnt = (c.fetchone() or [0])[0]

                c.execute("SELECT COUNT(*) FROM do_zrobienia WHERE auto_id=? AND wykonane=0", (self.state.auto_id,))
                do_zrobienia_cnt = (c.fetchone() or [0])[0]
        except Exception:
            pass

        # --- MENU "TRZECH KROPEK" — dawne kafelki nawigacyjne + odznaki liczników ---
        def pozycja_menu_nawigacji(ikona, etykieta, trasa, licznik=0):
            wiersz = [
                ft.Icon(ikona, size=18, color=ft.Colors.PRIMARY),
                ft.Text(etykieta, expand=True),
            ]
            if licznik > 0:
                wiersz.append(
                    ft.Container(
                        content=ft.Text(str(licznik) if licznik < 100 else "99+", size=10, weight="bold", color=ft.Colors.WHITE),
                        bgcolor=ft.Colors.RED_700, border_radius=9, padding=ft.Padding(6, 2, 6, 2),
                    )
                )
            return ft.PopupMenuItem(
                content=ft.Row(wiersz, spacing=8),
                on_click=lambda e, t=trasa: utils.przejdz(self._page, t)
            )

        menu_nawigacji = ft.PopupMenuButton(
            content=ft.Container(
                width=36, height=36, alignment=ft.Alignment.CENTER, border_radius=18,
                bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE),
                content=ft.Icon(ft.Icons.MORE_VERT, size=18, color=ft.Colors.ON_SURFACE_VARIANT),
            ),
            tooltip="Zadania, magazyn, wizyty, karoseria",
            items=[
                pozycja_menu_nawigacji(ft.Icons.CHECKLIST_RTL, "Zadania", "/do-zrobienia", do_zrobienia_cnt),
                pozycja_menu_nawigacji(ft.Icons.INVENTORY_2, "Magazyn", "/magazyn", magazyn_cnt),
                pozycja_menu_nawigacji(ft.Icons.HISTORY_EDU, "Wizyty", "/wizyty"),
                pozycja_menu_nawigacji(ft.Icons.PHOTO_CAMERA, "Karoseria", "/karoseria"),
            ]
        )

        naglowek_serwis = [ft.Text("🛠️ Serwis", size=20, weight="bold", color=ft.Colors.PRIMARY, expand=True)]
        if wspolny_id:
            naglowek_serwis.append(utils.przycisk_synchronizacji(self._page, self._synchronizuj_teraz))
        naglowek_serwis.append(menu_nawigacji)

        self.elementy.append(ft.Row(naglowek_serwis, vertical_alignment=ft.CrossAxisAlignment.CENTER))
        self.elementy.append(self._buduj_kokpit())

        akt_prz = int(db.pobierz_aktualny_przebieg(self.state.auto_id))
        prog_km = db.pobierz_prog_km()
        prog_dni = db.pobierz_prog_dni()

        sredni_dzienny = db.oblicz_sredni_dzienny_przebieg(self.state.auto_id)
        with db.polacz_baze() as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT * FROM zadania WHERE auto_id=?", (self.state.auto_id,))
            baza_lista = [dict(row) for row in c.fetchall()]

        # --- Wyraźne oddzielenie skrótów od właściwej listy podzespołów ---
        self.elementy.append(ft.Divider(height=20))

        if not baza_lista:
            self.elementy.append(utils.ekran_braku_danych(
                ikona=ft.Icons.HANDYMAN,
                tytul="Brak podzespołów",
                opis="Dodaj części (np. olej, filtry, rozrząd), aby śledzić wymiany i interwały.",
                tekst_przycisku="Dodaj część",
                on_click=lambda e: utils.przejdz(self._page, "/zadanie/nowy")
            ))
        else:
            self.tekst_licznik_zadan = ft.Text("", size=16, weight="bold", color=ft.Colors.PRIMARY)

            self.elementy.append(
                ft.Row([
                    ft.Icon(ft.Icons.HANDYMAN, color=ft.Colors.PRIMARY, size=20),
                    self.tekst_licznik_zadan,
                ], spacing=8)
            )

            opcje_sort = [
                ("Nazwa", "nazwa", lambda r: str(r.get('nazwa', '')).lower()),
                ("Ostatnia data", "data", lambda r: utils.parsuj_date(r.get('data'))),
                ("Przebieg", "przebieg", lambda r: int(r.get('przebieg') or 0)),
            ]

            sort_ui = utils.przycisk_sortowania(self._page, self.state, "zadania", opcje_sort)
            filtr_rok_ui = utils.przycisk_filtrowania_rok(self._page, self.state, "serwis_rok", baza_lista, "data")
            filtr_mc_ui = utils.przycisk_filtrowania_miesiac(self._page, self.state, "serwis_mc", baza_lista, "data")

            self.elementy.append(ft.Row([sort_ui, filtr_rok_ui, filtr_mc_ui], spacing=6, scroll=ft.ScrollMode.HIDDEN))

            def filtruj_zadania(e):
                zapytanie = e.control.value.lower().strip()
                self.lista_kart_serwis.controls.clear()
                for k in self.wszystkie_karty_serwis:
                    if zapytanie in k["szukaj"]:
                        self.lista_kart_serwis.controls.append(k["karta"])

                self.tekst_licznik_zadan.value = f"Śledzone podzespoły ({len(self.lista_kart_serwis.controls)})"
                self.update()

            self.elementy.append(
                ft.TextField(
                    hint_text="Szukaj podzespołu (np. olej, klocki, filtr)...",
                    prefix_icon=ft.Icons.SEARCH,
                    on_change=utils.z_opoznieniem(self._page, filtruj_zadania),
                    **utils.styl_pola()
                )
            )
            self.lista_kart_serwis = ft.ListView(spacing=15, padding=0, height=utils.wysokosc_listy(self._page), auto_scroll=False)
            self.uzyj_wirtualizacji = True
            self.wszystkie_karty_serwis = []

            po_filtrach = utils.filtruj_po_roku(baza_lista, self.state, "serwis_rok", "data")
            po_filtrach = utils.filtruj_po_miesiacu(po_filtrach, self.state, "serwis_mc", "data")
            utils.posortuj_liste(po_filtrach, self.state, "zadania", opcje_sort)

            self.tekst_licznik_zadan.value = f"Śledzone podzespoły ({len(po_filtrach)})"

            def pokaz_menu(zid, zn):
                self.state.wybrane_zadanie_id = zid
                self.state.wybrane_zadanie_nazwa = str(zn)

                def usun_zadanie(e):
                    utils.zamknij_dno(self._page, bs)
                    def wykonaj():
                        wynik = db.usun_zadanie_z_cofnieciem(zid)
                        utils.przejdz(self._page, "/")
                        utils.pokaz_komunikat_cofnij(self._page, "Usunięto podzespół.", wynik)
                    utils.potwierdz(self._page, "Usunąć?", "Na pewno usunąć ten podzespół?", wykonaj)

                bs = ft.BottomSheet(ft.Container(padding=20, bgcolor=ft.Colors.SURFACE, content=ft.Column([
                    ft.Text(str(zn), weight="bold", size=20, color=ft.Colors.PRIMARY), ft.Divider(),
                    ft.ListTile(leading=ft.Icon(ft.Icons.ADD_CIRCLE, color=ft.Colors.GREEN), title=ft.Text("Dodaj Wymianę", weight="bold"), on_click=lambda e: (utils.zamknij_dno(self._page, bs), utils.przejdz(self._page, f"/wpis/nowy/{zid}"))),
                    ft.ListTile(leading=ft.Icon(ft.Icons.HISTORY), title=ft.Text("Historia wymian"), on_click=lambda e: (utils.zamknij_dno(self._page, bs), utils.przejdz(self._page, f"/historia/{zid}"))),
                    ft.ListTile(leading=ft.Icon(ft.Icons.TIMER), title=ft.Text("Ustaw interwał przypomnień"), on_click=lambda e: (utils.zamknij_dno(self._page, bs), utils.przejdz(self._page, f"/interwal/{zid}"))),
                    ft.ListTile(leading=ft.Icon(ft.Icons.EDIT), title=ft.Text("Zmień nazwę"), on_click=lambda e: (utils.zamknij_dno(self._page, bs), utils.przejdz(self._page, f"/zadanie/edytuj/{zid}"))),
                    ft.ListTile(leading=ft.Icon(ft.Icons.DELETE, color=ft.Colors.RED), title=ft.Text("Usuń podzespół", color=ft.Colors.RED), on_click=usun_zadanie),
                ], tight=True)))
                utils.otworz_dno(self._page, bs)

            if not po_filtrach:
                self.elementy.append(ft.Row([ft.Text("Brak wyników dla tych filtrów.", color=ft.Colors.ON_SURFACE_VARIANT)], alignment=ft.MainAxisAlignment.CENTER))
            else:
                for z in po_filtrach:
                    kol, ico = ft.Colors.GREEN_700, ft.Icons.CHECK_CIRCLE  # domyślny status
                    stxt = []
                    if z.get('interwal_km') and z.get('przebieg'):
                        zost_km = (int(z.get('przebieg')) + int(z.get('interwal_km'))) - akt_prz
                        if zost_km < 0:
                            stxt.append(f"{utils.formatuj_liczba(abs(zost_km), 0)} km po!")
                            kol, ico = ft.Colors.RED_700, ft.Icons.WARNING
                        elif zost_km <= prog_km:
                            prognoza = utils.formatuj_prognoze_km(zost_km, sredni_dzienny)
                            stxt.append(prognoza or f"{utils.formatuj_liczba(zost_km, 0)} km")
                            kol, ico = ft.Colors.ORANGE_700, ft.Icons.HOURGLASS_BOTTOM
                        else:
                            prognoza = utils.formatuj_prognoze_km(zost_km, sredni_dzienny)
                            stxt.append(prognoza or f"{utils.formatuj_liczba(zost_km, 0)} km")

                    if z.get('interwal_miesiace') and z.get('data'):
                        d_w = utils.parsuj_date(z.get('data'))
                        if d_w != datetime.min.date():
                            zost_dni = (d_w + timedelta(days=int(float(z.get('interwal_miesiace'))*30.5)) - datetime.now().date()).days
                            if zost_dni < 0:
                                stxt.append(f"{abs(zost_dni)} dni po!")
                                kol, ico = ft.Colors.RED_700, ft.Icons.WARNING
                            elif zost_dni <= prog_dni:
                                stxt.append(f"{zost_dni} dni")
                                if kol != ft.Colors.RED_700: kol, ico = ft.Colors.ORANGE_700, ft.Icons.HOURGLASS_BOTTOM
                            else: stxt.append(f"~{zost_dni//30} m-cy")

                    if stxt: final_status = " | ".join(stxt)
                    else:
                        final_status = "Brak interwału" if not z.get('interwal_km') and not z.get('interwal_miesiace') else "Brak wpisów"
                        kol, ico = ft.Colors.ON_SURFACE_VARIANT, ft.Icons.INFO_OUTLINE

                    data_w = str(z.get('data')) if z.get('data') else '-'
                    prz_w = f"{utils.formatuj_liczba(int(z.get('przebieg')), 0)} km" if z.get('przebieg') else '-'

                    zid = z.get('id')
                    zn = z.get('nazwa')

                    karta_z, kontener = utils.karta_listy(
                        ft.Column([
                            ft.Row([ft.Text(str(zn), weight="bold", size=utils.FS["title"], expand=True), ft.Icon(ico, color=kol)]),
                            ft.Text(f"Wymieniono: {data_w} | Przy: {prz_w}", size=utils.FS["body"], color=ft.Colors.ON_SURFACE_VARIANT),
                            ft.Text(final_status, size=utils.FS["body_strong"], weight="bold", color=kol)
                        ]),
                        kolor_paska=kol,
                        page=self._page,
                    )

                    self.karty_ref[zid] = kontener
                    self.podepnij_zdarzenia_grupowe(kontener, zid, lambda zid=zid, zn=zn: pokaz_menu(zid, zn), "zadania")
                    tekst_szukaj = f"{zn} {data_w} {prz_w} {final_status}".lower()
                    self.wszystkie_karty_serwis.append({"karta": karta_z, "szukaj": tekst_szukaj})
                    self.lista_kart_serwis.controls.append(karta_z)

                self.elementy.append(self.lista_kart_serwis)

        self.fab = self._buduj_fab_szybkich_akcji()

    def buduj_tankowania(self):
        wspolny_id, _ = sync.czy_udostepniony(self.state.auto_id)
        naglowek_bits = [ft.Text("⛽ Historia Tankowań", size=20, weight="bold", color=ft.Colors.PRIMARY, expand=True)]
        if wspolny_id:
            naglowek_bits.append(utils.przycisk_synchronizacji(self._page, self._synchronizuj_teraz))
        self.elementy.append(ft.Row(naglowek_bits, vertical_alignment=ft.CrossAxisAlignment.CENTER))

        with db.polacz_baze() as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT * FROM tankowania WHERE auto_id=?", (self.state.auto_id,))
            baza_lista = [dict(row) for row in c.fetchall()]

        if not baza_lista:
            self.elementy.append(utils.ekran_braku_danych(
                ikona=ft.Icons.LOCAL_GAS_STATION,
                tytul="Brak tankowań",
                opis="Nie masz jeszcze historii paliwowej dla tego pojazdu.",
                tekst_przycisku="Dodaj pierwsze tankowanie",
                on_click=lambda e: utils.przejdz(self._page, "/tankowanie/nowe")
            ))
        else:
            baza_lista.sort(key=lambda x: int(x.get('przebieg') or 0))

            ostatni_pelny_idx = -1
            for i, t in enumerate(baza_lista):
                if i > 0:
                    prz_akt = int(t.get('przebieg') or 0)
                    prz_poprz = int(baza_lista[i-1].get('przebieg') or 0)
                    t['dystans'] = max(0, prz_akt - prz_poprz)
                else:
                    t['dystans'] = 0

                t['spalanie'] = None
                if t.get('do_pelna'):
                    if ostatni_pelny_idx != -1:
                        prz_akt = int(t.get('przebieg') or 0)
                        prz_ostatni_pelny = int(baza_lista[ostatni_pelny_idx].get('przebieg') or 0)
                        dystans_od_pelnego = prz_akt - prz_ostatni_pelny

                        litry_od_pelnego = sum(float(baza_lista[k].get('litry') or 0) for k in range(ostatni_pelny_idx + 1, i + 1))

                        if dystans_od_pelnego > 0:
                            t['spalanie'] = (litry_od_pelnego / dystans_od_pelnego) * 100
                    ostatni_pelny_idx = i

            opcje_sort = [
                ("Data", "data", lambda x: (utils.parsuj_date(x.get('data')), x.get('id', 0))),
                ("Przebieg", "przebieg", lambda x: int(x.get('przebieg') or 0)),
                ("Kwota", "kwota", lambda x: float(x.get('kwota') or 0)),
                ("Litry", "litry", lambda x: float(x.get('litry') or 0)),
            ]

            sort_ui = utils.przycisk_sortowania(self._page, self.state, "tankowania", opcje_sort)
            filtr_rok_ui = utils.przycisk_filtrowania_rok(self._page, self.state, "tankowania_rok", baza_lista, "data")
            filtr_mc_ui = utils.przycisk_filtrowania_miesiac(self._page, self.state, "tankowania_mc", baza_lista, "data")
            filtr_tag_ui = utils.przycisk_filtrowania_kategoria(self._page, self.state, "tankowania_tag", baza_lista, "tagi", "Tagi")

            self.elementy.append(ft.Row([sort_ui, filtr_rok_ui, filtr_mc_ui, filtr_tag_ui], spacing=6, scroll=ft.ScrollMode.HIDDEN))

            def filtruj_tankowania(e):
                zapytanie = e.control.value.lower().strip()
                self.lista_kart_tankowania.controls.clear()
                for k in self.wszystkie_karty_tankowania:
                    if zapytanie in k["szukaj"]:
                        self.lista_kart_tankowania.controls.append(k["karta"])
                self.update()

            self.elementy.append(
                ft.TextField(
                    hint_text="Szukaj tankowania (stacja, data, kwota, dystans)...",
                    prefix_icon=ft.Icons.SEARCH,
                    on_change=utils.z_opoznieniem(self._page, filtruj_tankowania),
                    **utils.styl_pola()
                )
            )
            self.lista_kart_tankowania = ft.ListView(spacing=15, padding=0, height=utils.wysokosc_listy(self._page), auto_scroll=False)
            self.uzyj_wirtualizacji = True
            self.wszystkie_karty_tankowania = []

            po_filtrach = utils.filtruj_po_roku(baza_lista, self.state, "tankowania_rok", "data")
            po_filtrach = utils.filtruj_po_miesiacu(po_filtrach, self.state, "tankowania_mc", "data")
            po_filtrach = utils.filtruj_po_kategorii(po_filtrach, self.state, "tankowania_tag", "tagi")
            utils.posortuj_liste(po_filtrach, self.state, "tankowania", opcje_sort)

            def otworz_menu_t(tid, zalacznik=None):
                def usun_tankowanie():
                    def wykonaj():
                        wynik = db.usun_z_cofnieciem("tankowania", tid)
                        utils.przejdz(self._page, "/")
                        utils.pokaz_komunikat_cofnij(self._page, "Usunięto tankowanie.", wynik)
                    utils.potwierdz(self._page, "Usunąć?", "Czy na pewno usunąć to tankowanie?", wykonaj)

                async def dodaj_zmien_zdj():
                    await utils.szybkie_dodanie_zdjecia(self._page, "tankowania", tid, zalacznik, lambda: utils.przejdz(self._page, "/"))

                pozycje = []
                if zalacznik:
                    pozycje.append({"ikona": ft.Icons.IMAGE, "tekst": "Pokaż zdjęcie", "akcja": lambda: utils.pokaz_podglad_zalacznika(self._page, zalacznik, "Tankowanie")})
                    pozycje.append({"ikona": ft.Icons.EDIT_DOCUMENT, "tekst": "Zmień zdjęcie", "akcja": dodaj_zmien_zdj})
                else:
                    pozycje.append({"ikona": ft.Icons.ADD_A_PHOTO, "tekst": "Dodaj zdjęcie (paragon)", "akcja": dodaj_zmien_zdj})

                pozycje.append({"ikona": ft.Icons.EDIT, "tekst": "Edytuj", "akcja": lambda: utils.przejdz(self._page, f"/tankowanie/edytuj/{tid}")})
                pozycje.append({"ikona": ft.Icons.DELETE, "tekst": "Usuń", "akcja": usun_tankowanie, "kolor": ft.Colors.RED})

                utils.pokaz_menu_kontekstowe(self._page, "Opcje tankowania", pozycje)

            if not po_filtrach:
                self.elementy.append(ft.Row([ft.Text("Brak wyników dla tych filtrów.", color=ft.Colors.ON_SURFACE_VARIANT)], alignment=ft.MainAxisAlignment.CENTER))
            else:
                for w in po_filtrach:
                    spalanie = w.get('spalanie')
                    sp_str = utils.formatuj_spalanie(spalanie)
                    kwota_val = float(w.get('kwota') or 0)
                    litry_val = float(w.get('litry') or 0)
                    cena_str = f"{utils.formatuj_liczba(kwota_val)}  {utils.symbol_waluty()}"
                    cena_litr_str = f"{utils.formatuj_liczba(kwota_val / litry_val, 2)} {utils.symbol_waluty()}/L" if litry_val > 0 else "-"
                    dystans_val = w.get('dystans') or 0

                    tid = w.get('id')
                    tresc_karty = [
                        ft.Row([
                            ft.Text(f"{w.get('data')} • {w.get('stacja')}" if w.get('stacja') else str(w.get('data')), weight="bold", color=ft.Colors.ON_SURFACE_VARIANT),
                            ft.Row([
                                utils.wskaznik_zalacznika(self._page, w.get('zalacznik'), "Tankowanie"),
                                ft.Icon(ft.Icons.LOCAL_GAS_STATION, size=14, color=ft.Colors.PRIMARY, tooltip="Do pełna") if w.get('do_pelna') else ft.Container(),
                                ft.Text(f"-{cena_str}", weight="bold", color=ft.Colors.RED_700)
                            ], spacing=4)
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Row([
                            ft.Column([ft.Text("Dystans", size=11, color=ft.Colors.ON_SURFACE_VARIANT), ft.Text(f"{dystans_val} km", weight="bold")]),
                            ft.Column([ft.Text("Spalanie", size=11, color=ft.Colors.ON_SURFACE_VARIANT), ft.Text(sp_str, weight="bold")]),
                            ft.Column([ft.Text("Cena/L", size=11, color=ft.Colors.ON_SURFACE_VARIANT), ft.Text(cena_litr_str, weight="bold")])
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                    ]
                    if w.get('tagi'):
                        tresc_karty.append(utils.wizualizacja_tagow(w.get('tagi'), self.state.auto_id))
                    if wspolny_id and w.get('dodane_przez'):
                        tresc_karty.append(utils.znacznik_dodane_przez(w.get('dodane_przez')))

                    kontener = ft.Container(padding=15, border_radius=10, ink=True, content=ft.Column(tresc_karty))

                    self.karty_ref[tid] = kontener
                    self.podepnij_zdarzenia_grupowe(kontener, tid, lambda id_el=tid, zal=w.get('zalacznik'): otworz_menu_t(id_el, zal), "tankowania")

                    karta_t = ft.Card(elevation=1, content=kontener)
                    tekst_szukaj = f"{w.get('data')} {w.get('stacja')} {cena_str} {dystans_val} {sp_str} {w.get('tagi')}".lower()
                    self.wszystkie_karty_tankowania.append({"karta": karta_t, "szukaj": tekst_szukaj})
                    self.lista_kart_tankowania.controls.append(karta_t)

                self.elementy.append(self.lista_kart_tankowania)

        self.fab = self._buduj_fab_szybkich_akcji()

    def buduj_inne(self):
        wspolny_id, _ = sync.czy_udostepniony(self.state.auto_id)
        naglowek_inne = [ft.Text("🎫 Inne Koszty", size=20, weight="bold", color=ft.Colors.PRIMARY, expand=True)]
        if wspolny_id:
            naglowek_inne.append(utils.przycisk_synchronizacji(self._page, self._synchronizuj_teraz))
        self.elementy.append(ft.Row(naglowek_inne, vertical_alignment=ft.CrossAxisAlignment.CENTER))

        with db.polacz_baze() as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT * FROM inne_koszty WHERE auto_id=?", (self.state.auto_id,))
            baza_lista = [dict(row) for row in c.fetchall()]

        if not baza_lista:
            self.elementy.append(utils.ekran_braku_danych(
                ikona=ft.Icons.RECEIPT_LONG,
                tytul="Brak kosztów",
                opis="Dodaj opłaty takie jak ubezpieczenie, myjnia, autostrady czy raty leasingu.",
                tekst_przycisku="Dodaj wydatek",
                on_click=lambda e: utils.przejdz(self._page, "/inne/nowy")
            ))
        else:
            opcje_sort = [
                ("Data", "data", lambda x: (utils.parsuj_date(x.get('data')), x.get('id', 0))),
                ("Kategoria", "kategoria", lambda x: str(x.get('kategoria') or "").lower()),
                ("Kwota", "kwota", lambda x: float(x.get('kwota') or 0)),
            ]

            sort_ui = utils.przycisk_sortowania(self._page, self.state, "inne", opcje_sort)
            filtr_rok_ui = utils.przycisk_filtrowania_rok(self._page, self.state, "inne_rok", baza_lista, "data")
            filtr_mc_ui = utils.przycisk_filtrowania_miesiac(self._page, self.state, "inne_mc", baza_lista, "data")
            filtr_kat_ui = utils.przycisk_filtrowania_kategoria(self._page, self.state, "inne_kat", baza_lista, "kategoria", "Kategoria")

            self.elementy.append(ft.Row([sort_ui, filtr_rok_ui, filtr_mc_ui, filtr_kat_ui], spacing=6, scroll=ft.ScrollMode.HIDDEN))

            def filtruj_inne(e):
                zapytanie = e.control.value.lower().strip()
                self.lista_kart_inne.controls.clear()
                for k in self.wszystkie_karty_inne:
                    if zapytanie in k["szukaj"]:
                        self.lista_kart_inne.controls.append(k["karta"])
                self.update()

            self.elementy.append(
                ft.TextField(
                    hint_text="Szukaj kosztu (opis, kategoria, kwota, data)...",
                    prefix_icon=ft.Icons.SEARCH,
                    on_change=utils.z_opoznieniem(self._page, filtruj_inne),
                    **utils.styl_pola()
                )
            )
            self.lista_kart_inne = ft.ListView(spacing=15, padding=0, height=utils.wysokosc_listy(self._page), auto_scroll=False)
            self.uzyj_wirtualizacji = True
            self.wszystkie_karty_inne = []

            po_filtrach = utils.filtruj_po_roku(baza_lista, self.state, "inne_rok", "data")
            po_filtrach = utils.filtruj_po_miesiacu(po_filtrach, self.state, "inne_mc", "data")
            po_filtrach = utils.filtruj_po_kategorii(po_filtrach, self.state, "inne_kat", "kategoria")
            utils.posortuj_liste(po_filtrach, self.state, "inne", opcje_sort)

            def otworz_menu_i(iid, zalacznik=None):
                def usun_koszt(e):
                    utils.zamknij_dno(self._page, bs)
                    def wykonaj():
                        wynik = db.usun_z_cofnieciem("inne_koszty", iid)
                        utils.przejdz(self._page, "/")
                        utils.pokaz_komunikat_cofnij(self._page, "Usunięto koszt.", wynik)
                    utils.potwierdz(self._page, "Usunąć?", "Czy na pewno usunąć ten koszt?", wykonaj)

                async def dodaj_zmien_zdj(ev):
                    utils.zamknij_dno(self._page, bs)
                    await utils.szybkie_dodanie_zdjecia(self._page, "inne_koszty", iid, zalacznik, lambda: utils.przejdz(self._page, "/"))

                pozycje = [ft.Text("Opcje kosztu", weight="bold", size=18)]
                if zalacznik:
                    pozycje.append(ft.ListTile(
                        leading=ft.Icon(ft.Icons.IMAGE),
                        title=ft.Text("Pokaż zdjęcie"),
                        on_click=lambda ev: (utils.zamknij_dno(self._page, bs), utils.pokaz_podglad_zalacznika(self._page, zalacznik, "Koszt"))
                    ))
                    pozycje.append(ft.ListTile(leading=ft.Icon(ft.Icons.EDIT_DOCUMENT), title=ft.Text("Zmień zdjęcie"), on_click=dodaj_zmien_zdj))
                else:
                    pozycje.append(ft.ListTile(leading=ft.Icon(ft.Icons.ADD_A_PHOTO), title=ft.Text("Dodaj zdjęcie (faktura/paragon)"), on_click=dodaj_zmien_zdj))

                pozycje.append(ft.ListTile(leading=ft.Icon(ft.Icons.EDIT), title=ft.Text("Edytuj koszt"), on_click=lambda ev: (utils.zamknij_dno(self._page, bs), utils.przejdz(self._page, f"/inne/edytuj/{iid}"))))
                pozycje.append(ft.ListTile(leading=ft.Icon(ft.Icons.DELETE, color=ft.Colors.RED), title=ft.Text("Usuń koszt", color=ft.Colors.RED), on_click=usun_koszt))

                bs = ft.BottomSheet(ft.Container(padding=20, bgcolor=ft.Colors.SURFACE, content=ft.Column(pozycje, tight=True)))
                utils.otworz_dno(self._page, bs)

            if not po_filtrach:
                self.elementy.append(ft.Row([ft.Text("Brak wyników dla tych filtrów.", color=ft.Colors.ON_SURFACE_VARIANT)], alignment=ft.MainAxisAlignment.CENTER))
            else:
                for w in po_filtrach:
                    cena_str = f"{utils.formatuj_liczba(float(w.get('kwota') or 0))}  {utils.symbol_waluty()}"
                    tagi_str = str(w.get('tagi') or w.get('kategoria') or "Brak tagów")
                    iid = w.get('id')
                    tresc_i = [
                        ft.Row([
                            ft.Text(str(w.get('data')), weight="bold", color=ft.Colors.ON_SURFACE_VARIANT),
                            ft.Row([
                                utils.wskaznik_zalacznika(self._page, w.get('zalacznik'), "Koszt"),
                                ft.Text(f"-{cena_str}", weight="bold", color=ft.Colors.RED_700)
                            ], spacing=6)
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Text(str(w.get('nazwa')) if w.get('nazwa') else "Brak opisu", size=16, weight="bold"),
                        utils.wizualizacja_tagow(w.get('tagi') or w.get('kategoria'), self.state.auto_id)
                    ]
                    if wspolny_id and w.get('dodane_przez'):
                        tresc_i.append(utils.znacznik_dodane_przez(w.get('dodane_przez')))
                    kontener = ft.Container(padding=15, border_radius=10, ink=True, content=ft.Column(tresc_i))

                    self.karty_ref[iid] = kontener
                    self.podepnij_zdarzenia_grupowe(kontener, iid, lambda id_el=iid, zal=w.get('zalacznik'): otworz_menu_i(id_el, zal), "inne_koszty")

                    karta_i = ft.Card(elevation=1, content=kontener)
                    tekst_szukaj = f"{w.get('data')} {w.get('nazwa')} {w.get('kategoria')} {cena_str}".lower()
                    self.wszystkie_karty_inne.append({"karta": karta_i, "szukaj": tekst_szukaj})
                    self.lista_kart_inne.controls.append(karta_i)

                self.elementy.append(self.lista_kart_inne)

        self.fab = self._buduj_fab_szybkich_akcji()

    def buduj_statystyki(self):
        with db.polacz_baze() as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT * FROM tankowania WHERE auto_id=?", (self.state.auto_id,))
            tankowania = [dict(row) for row in c.fetchall()]
            c.execute(
                "SELECT h.data, h.cena FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
                "WHERE z.auto_id=? AND h.wizyta_id IS NULL", (self.state.auto_id,)
            )
            wh = [dict(row) for row in c.fetchall()]
            c.execute("SELECT data, koszt_calkowity FROM wizyty WHERE auto_id=?", (self.state.auto_id,))
            ww = [dict(row) for row in c.fetchall()]
            c.execute("SELECT data, kwota FROM inne_koszty WHERE auto_id=?", (self.state.auto_id,))
            wi = [dict(row) for row in c.fetchall()]

        serw = sum(float(r['cena'] or 0.0) for r in wh) + sum(float(r['koszt_calkowity'] or 0.0) for r in ww)
        inn = sum(float(r['kwota'] or 0.0) for r in wi)

        tankowania.sort(key=lambda x: int(x.get('przebieg') or 0))

        pal = sum(float(t.get('kwota') or 0) for t in tankowania) if tankowania else 0.0
        litry = sum(float(t.get('litry') or 0) for t in tankowania) if tankowania else 0.0
        dystans = (int(tankowania[-1].get('przebieg') or 0) - int(tankowania[0].get('przebieg') or 0)) if len(tankowania) > 1 else 0

        spalanie = 0.0
        peln_idx = [i for i, t in enumerate(tankowania) if t.get('do_pelna')]
        if len(peln_idx) >= 2:
            p, o = peln_idx[0], peln_idx[-1]
            d_p = int(tankowania[o].get('przebieg') or 0) - int(tankowania[p].get('przebieg') or 0)
            l_p = sum(float(t.get('litry') or 0) for t in tankowania[p+1: o+1])
            if d_p > 0: spalanie = (l_p / d_p) * 100

        razem = pal + serw + inn
        koszt_km = (razem / dystans) if dystans > 0 else 0.0

        sredni_dzienny = db.oblicz_sredni_dzienny_przebieg(self.state.auto_id)
        sredni_dz_str = f"{utils.formatuj_liczba(sredni_dzienny, 1)} km/dzień" if sredni_dzienny else "Brak danych"

        def kafel(ikona, tytul, wartosc, kolor=ft.Colors.PRIMARY, expand=None):
            return ft.Card(
                elevation=1,
                expand=expand,
                content=ft.Container(
                    padding=15,
                    content=ft.Row([
                        ft.Container(
                            content=ft.Icon(ikona, color=kolor, size=22),
                            bgcolor=ft.Colors.with_opacity(0.13, kolor),
                            border_radius=10,
                            padding=8
                        ),
                        ft.Column([
                            ft.Text(tytul, size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                            ft.Text(wartosc, weight="bold", size=17)
                        ], spacing=2, expand=True)
                    ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)
                )
            )

        def zmien_podzakladke(idx):
            self.state.stat_podzakladka = idx
            utils.przejdz(self._page, "/")

        self.elementy.append(utils.segmented_control(
            self._page, [("Liczby", 0), ("Wykresy", 1), ("Tabele", 2)], self.state.stat_podzakladka, zmien_podzakladke
        ))

        if self.state.stat_podzakladka == 0:
            self.elementy.extend([
                ft.Text("📊 Podsumowanie Kosztów", size=20, weight="bold", color=ft.Colors.PRIMARY),
                kafel(ft.Icons.ATTACH_MONEY, "Całkowity koszt", f"{utils.formatuj_liczba(razem)}  {utils.symbol_waluty()}", ft.Colors.RED_700),
                ft.Row([
                    kafel(ft.Icons.LOCAL_GAS_STATION, "Na paliwo", f"{utils.formatuj_liczba(pal)}  {utils.symbol_waluty()}", ft.Colors.BLUE_700, expand=1),
                    kafel(ft.Icons.BUILD, "Na serwis", f"{utils.formatuj_liczba(serw)}  {utils.symbol_waluty()}", ft.Colors.ORANGE_700, expand=1),
                ], spacing=10),
                ft.Row([
                    kafel(ft.Icons.RECEIPT_LONG, "Inne koszty", f"{utils.formatuj_liczba(inn)}  {utils.symbol_waluty()}", ft.Colors.GREEN_700, expand=1),
                    kafel(ft.Icons.ADD_ROAD, "Koszt 1 km", f"{utils.formatuj_liczba(koszt_km)}  {utils.symbol_waluty()}/km", ft.Colors.PURPLE_700, expand=1),
                ], spacing=10),
                ft.Text("📈 Wskaźniki i Paliwo", size=20, weight="bold", color=ft.Colors.PRIMARY),
                ft.Row([
                    kafel(ft.Icons.SPEED, "Średnie spalanie", utils.formatuj_spalanie(spalanie) if spalanie > 0 else "Wymaga 2x do pełna", ft.Colors.TEAL_700, expand=1),
                    kafel(ft.Icons.ROUTE, "Zanotowany dystans", f"{utils.formatuj_liczba(dystans, 0)} km", ft.Colors.INDIGO_700, expand=1),
                ], spacing=10),
                ft.Row([
                    kafel(ft.Icons.TIMELAPSE, "Średnio dziennie", sredni_dz_str, ft.Colors.BLUE_GREY_700, expand=1),
                    kafel(ft.Icons.WATER_DROP, "Zatankowano", f"{utils.formatuj_liczba(litry)} L", ft.Colors.CYAN_700, expand=1),
                ], spacing=10),
            ])

        elif self.state.stat_podzakladka == 1:
            proc_pal = (pal / razem * 100) if razem > 0 else 0
            proc_ser = (serw / razem * 100) if razem > 0 else 0
            proc_inn = (inn / razem * 100) if razem > 0 else 0

            def segment_procentowy(ikona, tytul, kwota, procent, kolor):
                return ft.Column([
                    ft.Row([
                        ft.Row([
                            ft.Text(ikona, size=14),
                            ft.Text(tytul, weight="bold", size=13, color=ft.Colors.ON_SURFACE)
                        ], spacing=6),
                        ft.Text(
                            f"{utils.formatuj_liczba(kwota)} {utils.symbol_waluty()} ({utils.formatuj_liczba(procent, 0)}%)",
                            weight="bold", size=13, color=kolor
                        )
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.ProgressBar(
                        value=(procent / 100) if procent > 0 else 0,
                        color=kolor,
                        bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
                        height=8,
                        border_radius=4
                    )
                ], spacing=4)

            karta_struktury = ft.Card(
                elevation=1,
                content=ft.Container(
                    padding=15,
                    border_radius=10,
                    content=ft.Column([
                        segment_procentowy("⛽", "Paliwo", pal, proc_pal, ft.Colors.BLUE_700),
                        segment_procentowy("🛠️", "Serwis i Naprawy", serw, proc_ser, ft.Colors.RED_700),
                        segment_procentowy("🎫", "Inne Koszty", inn, proc_inn, ft.Colors.GREEN_700),
                    ], spacing=12)
                )
            )

            dzisiaj = datetime.now()
            miesiace_klucze, miesiace_etykiety = [], []
            for i in range(5, -1, -1):
                m = dzisiaj.month - i
                y = dzisiaj.year
                while m <= 0:
                    m += 12
                    y -= 1
                miesiace_klucze.append(f"{y}-{m:02d}")
                miesiace_etykiety.append(f"{m:02d}/{str(y)[2:]}")

            wartosci_mc = {k: 0.0 for k in miesiace_klucze}
            for lista_d in [
                [(t.get('data'), t.get('kwota')) for t in tankowania],
                [(r['data'], r['kwota']) for r in wi],
                [(r['data'], r['koszt_calkowity']) for r in ww],
                [(r['data'], r['cena']) for r in wh],
            ]:
                for d_str, kw in lista_d:
                    d = utils.parsuj_date(d_str)
                    if d != datetime.min.date():
                        mk = f"{d.year}-{d.month:02d}"
                        if mk in wartosci_mc:
                            wartosci_mc[mk] += float(kw or 0.0)

            max_val = max(wartosci_mc.values()) if wartosci_mc else 0
            suma_okresu = sum(wartosci_mc.values())
            wysokosc_max_slupka = 120
            biezacy_klucz = miesiace_klucze[-1]

            kolumny_wykresu = []
            for mk, etyk in zip(miesiace_klucze, miesiace_etykiety):
                val = wartosci_mc[mk]
                wysokosc = int((val / max_val) * wysokosc_max_slupka) if max_val > 0 and val > 0 else 4
                tekst_kwota = f"{int(round(val))}" if val > 0 else "-"
                czy_biezacy = (mk == biezacy_klucz)

                kolor_slupka = (
                    ft.Colors.PRIMARY if czy_biezacy else ft.Colors.with_opacity(0.5, ft.Colors.PRIMARY)
                ) if val > 0 else ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE)

                kolumna_slupka = ft.Column([
                    ft.Text(
                        tekst_kwota, size=10, weight="bold",
                        color=ft.Colors.PRIMARY if val > 0 else ft.Colors.ON_SURFACE_VARIANT
                    ),
                    ft.Container(
                        width=32,
                        height=max(6, wysokosc),
                        bgcolor=kolor_slupka,
                        border_radius=6,
                        tooltip=f"{etyk}: {utils.formatuj_liczba(val)} {utils.symbol_waluty()}" if val > 0 else None,
                        animate=ft.Animation(300, ft.AnimationCurve.EASE_OUT),
                    ),
                    ft.Text(
                        etyk, size=11,
                        weight="bold" if czy_biezacy else "normal",
                        color=ft.Colors.PRIMARY if czy_biezacy else ft.Colors.ON_SURFACE_VARIANT
                    )
                ], alignment=ft.MainAxisAlignment.END, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4)

                kolumny_wykresu.append(kolumna_slupka)

            karta_wykresu = ft.Card(
                elevation=1,
                content=ft.Container(
                    padding=15,
                    content=ft.Column([
                        ft.Row(
                            controls=kolumny_wykresu,
                            alignment=ft.MainAxisAlignment.SPACE_EVENLY,
                            vertical_alignment=ft.CrossAxisAlignment.END
                        ),
                        ft.Row(
                            controls=[
                                ft.Text(f"* wartości w {utils.symbol_waluty()}", size=10, italic=True, color=ft.Colors.ON_SURFACE_VARIANT)
                            ],
                            alignment=ft.MainAxisAlignment.END
                        )
                    ])
                )
            )

            segmenty_spalania = []
            pelne_idx_all = [i for i, t in enumerate(tankowania) if t.get('do_pelna')]
            for a, b in zip(pelne_idx_all, pelne_idx_all[1:]):
                prz_a = int(tankowania[a].get('przebieg') or 0)
                prz_b = int(tankowania[b].get('przebieg') or 0)
                dystans_seg = prz_b - prz_a
                litry_seg = sum(float(tankowania[k].get('litry') or 0) for k in range(a + 1, b + 1))
                if dystans_seg > 0:
                    segmenty_spalania.append((tankowania[b].get('data'), (litry_seg / dystans_seg) * 100))

            spalanie_wg_mc = {}
            for data_str, wartosc in segmenty_spalania:
                d = utils.parsuj_date(data_str)
                if d == datetime.min.date():
                    continue
                klucz = f"{d.year}-{d.month:02d}"
                spalanie_wg_mc.setdefault(klucz, []).append(wartosc)

            punkty_spalania = sorted(
                ((k, sum(v) / len(v)) for k, v in spalanie_wg_mc.items()),
                key=lambda p: p[0]
            )[-12:]

            if len(punkty_spalania) < 2:
                karta_trendu = ft.Card(
                    elevation=1,
                    content=ft.Container(
                        padding=15,
                        content=ft.Text(
                            "Za mało danych do wykresu trendu — potrzeba spalania policzonego z co najmniej "
                            "2 różnych miesięcy (min. 3 tankowania „do pełna”).",
                            size=13, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
                        )
                    )
                )
            else:
                wartosci_spalania = [w for _, w in punkty_spalania]
                min_val = min(wartosci_spalania)
                max_val_sp = max(wartosci_spalania)
                zapas = max((max_val_sp - min_val) * 0.15, 0.5)

                pierwsza_wart, ostatnia_wart = wartosci_spalania[0], wartosci_spalania[-1]
                zmiana_proc = ((ostatnia_wart - pierwsza_wart) / pierwsza_wart * 100) if pierwsza_wart > 0 else 0

                if zmiana_proc > 5:
                    znacznik_trendu = ft.Container(
                        padding=ft.Padding(10, 5, 10, 5), border_radius=20,
                        bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.RED_700),
                        content=ft.Text(f"📈 Rośnie o {utils.formatuj_liczba(zmiana_proc, 0)}%", size=12, weight="bold", color=ft.Colors.RED_700)
                    )
                elif zmiana_proc < -5:
                    znacznik_trendu = ft.Container(
                        padding=ft.Padding(10, 5, 10, 5), border_radius=20,
                        bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.GREEN_700),
                        content=ft.Text(f"📉 Spada o {utils.formatuj_liczba(abs(zmiana_proc), 0)}%", size=12, weight="bold", color=ft.Colors.GREEN_700)
                    )
                else:
                    znacznik_trendu = ft.Container(
                        padding=ft.Padding(10, 5, 10, 5), border_radius=20,
                        content=ft.Text("➖ Stabilne", size=12, weight="bold", color=ft.Colors.ON_SURFACE_VARIANT)
                    )

                krok_etykiet = 1 if len(punkty_spalania) <= 6 else 2
                etykiety_osi = []
                for i, (klucz, _) in enumerate(punkty_spalania):
                    if i % krok_etykiet != 0 and i != len(punkty_spalania) - 1:
                        continue
                    rok_i, mies_i = klucz.split("-")
                    etykiety_osi.append(
                        fc.ChartAxisLabel(
                            value=i,
                            label=ft.Text(f"{mies_i}/{rok_i[2:]}", size=9, color=ft.Colors.ON_SURFACE_VARIANT)
                        )
                    )

                wykres_liniowy = fc.LineChart(
                    data_series=[
                        fc.LineChartData(
                            points=[fc.LineChartDataPoint(i, w) for i, (_, w) in enumerate(punkty_spalania)],
                            stroke_width=3,
                            color=ft.Colors.TEAL_700,
                            curved=True,
                            rounded_stroke_cap=True,
                        )
                    ],
                    left_axis=fc.ChartAxis(label_size=32, title=ft.Text("L/100km", size=10), title_size=14),
                    bottom_axis=fc.ChartAxis(labels=etykiety_osi, label_size=24),
                    min_y=max(0, min_val - zapas),
                    max_y=max_val_sp + zapas,
                    min_x=0,
                    max_x=len(punkty_spalania) - 1,
                    expand=True,
                )

                karta_trendu = ft.Card(
                    elevation=1,
                    content=ft.Container(
                        padding=15,
                        content=ft.Column([
                            ft.Row([
                                ft.Text("Średnie spalanie w miesiącu", weight="bold", size=14, expand=True),
                                znacznik_trendu
                            ]),
                            ft.Container(height=200, content=wykres_liniowy),
                        ], spacing=10)
                    )
                )

            trend_paliwa = db.pobierz_trend_cen_paliwa(self.state.auto_id)

            cena_wg_mc = {}
            for data_str, cena in trend_paliwa["punkty"]:
                d = utils.parsuj_date(data_str)
                if d == datetime.min.date():
                    continue
                klucz = f"{d.year}-{d.month:02d}"
                cena_wg_mc.setdefault(klucz, []).append(cena)

            punkty_cen_mc = sorted(
                ((k, sum(v) / len(v)) for k, v in cena_wg_mc.items()),
                key=lambda p: p[0]
            )[-12:]

            if len(punkty_cen_mc) < 2:
                karta_cen = ft.Card(
                    elevation=1,
                    content=ft.Container(
                        padding=15,
                        content=ft.Text(
                            "Za mało danych do wykresu cen paliwa — potrzeba tankowań z co najmniej "
                            "2 różnych miesięcy.",
                            size=13, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
                        )
                    )
                )
            else:
                wartosci_cen = [w for _, w in punkty_cen_mc]
                min_c, max_c = min(wartosci_cen), max(wartosci_cen)
                zapas_c = max((max_c - min_c) * 0.15, 0.05)

                krok_etykiet_c = 1 if len(punkty_cen_mc) <= 6 else 2
                etykiety_osi_c = []
                for i, (klucz, _) in enumerate(punkty_cen_mc):
                    if i % krok_etykiet_c != 0 and i != len(punkty_cen_mc) - 1:
                        continue
                    rok_i, mies_i = klucz.split("-")
                    etykiety_osi_c.append(
                        fc.ChartAxisLabel(
                            value=i,
                            label=ft.Text(f"{mies_i}/{rok_i[2:]}", size=9, color=ft.Colors.ON_SURFACE_VARIANT)
                        )
                    )

                wykres_cen = fc.LineChart(
                    data_series=[
                        fc.LineChartData(
                            points=[fc.LineChartDataPoint(i, w) for i, (_, w) in enumerate(punkty_cen_mc)],
                            stroke_width=3,
                            color=ft.Colors.BLUE_700,
                            curved=True,
                            rounded_stroke_cap=True,
                        )
                    ],
                    left_axis=fc.ChartAxis(label_size=32, title=ft.Text(f"{utils.symbol_waluty()}/L", size=10), title_size=14),
                    bottom_axis=fc.ChartAxis(labels=etykiety_osi_c, label_size=24),
                    min_y=max(0, min_c - zapas_c),
                    max_y=max_c + zapas_c,
                    min_x=0,
                    max_x=len(punkty_cen_mc) - 1,
                    expand=True,
                )

                karta_cen = ft.Card(
                    elevation=1,
                    content=ft.Container(
                        padding=15,
                        content=ft.Column([
                            ft.Text("Średnia cena za litr w miesiącu", weight="bold", size=14),
                            ft.Container(height=200, content=wykres_cen),
                        ], spacing=10)
                    )
                )

            stacje_ranking = trend_paliwa["stacje"]
            if stacje_ranking:
                wiersze_stacji = []
                for i, s in enumerate(stacje_ranking[:5]):
                    czy_najtansza = (i == 0)
                    wiersze_stacji.append(
                        ft.Row([
                            ft.Row([
                                ft.Icon(ft.Icons.EMOJI_EVENTS if czy_najtansza else ft.Icons.LOCAL_GAS_STATION,
                                        size=16, color=ft.Colors.AMBER_700 if czy_najtansza else ft.Colors.ON_SURFACE_VARIANT),
                                ft.Text(s["nazwa"], weight="bold" if czy_najtansza else "normal", size=13),
                            ], spacing=6),
                            ft.Text(
                                f"{utils.formatuj_liczba(s['srednia_cena'], 2)} {utils.symbol_waluty()}/L  •  {s['liczba_tankowan']}x",
                                size=13, weight="bold" if czy_najtansza else "normal",
                                color=ft.Colors.GREEN_700 if czy_najtansza else ft.Colors.ON_SURFACE
                            )
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                    )

                karta_stacji = ft.Card(
                    elevation=1,
                    content=ft.Container(
                        padding=15,
                        content=ft.Column([
                            ft.Row([ft.Icon(ft.Icons.LOCAL_GAS_STATION, color=ft.Colors.PRIMARY),
                                    ft.Text("Ranking stacji (śr. cena/L)", weight="bold", size=14, expand=True)], spacing=8),
                            ft.Divider(height=10),
                            ft.Column(wiersze_stacji, spacing=10),
                        ])
                    )
                )
            else:
                karta_stacji = ft.Card(
                    elevation=1,
                    content=ft.Container(
                        padding=15,
                        content=ft.Text(
                            "Dodaj nazwę stacji przy tankowaniu, aby zobaczyć ranking najtańszych miejsc.",
                            size=13, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
                        )
                    )
                )

            self.elementy.extend([
                ft.Text("Struktura Kosztów", weight="bold", size=18, color=ft.Colors.PRIMARY),
                karta_struktury,
                ft.Divider(height=20),
                ft.Row([
                    ft.Text("Wydatki miesięczne (ostatnie 6 mies.)", weight="bold", size=18, color=ft.Colors.PRIMARY, expand=True),
                    ft.Text(f"Razem: {utils.formatuj_liczba(suma_okresu)}  {utils.symbol_waluty()}", weight="bold", size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                ]),
                karta_wykresu,
                ft.Divider(height=20),
                ft.Text("Trend spalania w czasie", weight="bold", size=18, color=ft.Colors.PRIMARY),
                karta_trendu,
                ft.Divider(height=20),
                ft.Text("Ceny paliwa i stacje", weight="bold", size=18, color=ft.Colors.PRIMARY),
                karta_cen,
                karta_stacji,
            ])

        elif self.state.stat_podzakladka == 2:
            zdarzenia = []
            for t in tankowania:
                zdarzenia.append((t.get('data'), float(t.get('kwota') or 0.0), 0.0, 0.0, float(t.get('litry') or 0.0)))
            for r in wh:
                zdarzenia.append((r['data'], 0.0, float(r['cena'] or 0.0), 0.0, 0.0))
            for r in ww:
                zdarzenia.append((r['data'], 0.0, float(r['koszt_calkowity'] or 0.0), 0.0, 0.0))
            for r in wi:
                zdarzenia.append((r['data'], 0.0, 0.0, float(r['kwota'] or 0.0), 0.0))

            mc_agr, rok_agr = {}, {}
            for data_str, pal_w, serw_w, inn_w, litry_w in zdarzenia:
                d = utils.parsuj_date(data_str)
                if d == datetime.min.date():
                    continue
                mk, rk = f"{d.year}-{d.month:02d}", str(d.year)
                for magazyn, klucz in ((mc_agr, mk), (rok_agr, rk)):
                    wpis = magazyn.setdefault(klucz, {"pal": 0.0, "serw": 0.0, "inn": 0.0, "litry": 0.0})
                    wpis["pal"] += pal_w
                    wpis["serw"] += serw_w
                    wpis["inn"] += inn_w
                    wpis["litry"] += litry_w

            def zbuduj_wiersze(agregat, czy_miesiac):
                wiersze = []
                for klucz, dane in agregat.items():
                    if czy_miesiac:
                        rok_i, mies_i = klucz.split("-")
                        etykieta = f"{utils.MIESIACE_NAZWY[int(mies_i) - 1]} {rok_i}"
                        rok_str = rok_i
                        pseudo_data = f"{rok_i}-{mies_i}-01"
                    else:
                        etykieta = klucz
                        rok_str = klucz
                        pseudo_data = f"{rok_str}-01-01"
                    razem_w = dane["pal"] + dane["serw"] + dane["inn"]
                    sr_cena_w = (dane["pal"] / dane["litry"]) if dane["litry"] > 0 else 0.0
                    wiersze.append((klucz, etykieta, rok_str, dane["pal"], dane["serw"], dane["inn"], razem_w, dane["litry"], sr_cena_w, pseudo_data))
                return wiersze

            wiersze_mc_wszystkie = zbuduj_wiersze(mc_agr, True)
            wiersze_rok_wszystkie = zbuduj_wiersze(rok_agr, False)

            def karta_okresu(w):
                _, etykieta, _, pal_w, serw_w, inn_w, razem_w, litry_w, sr_cena_w, _ = w
                bits = []
                if pal_w > 0: bits.append(f"⛽ {utils.formatuj_liczba(pal_w, 0)}")
                if serw_w > 0: bits.append(f"🛠️ {utils.formatuj_liczba(serw_w, 0)}")
                if inn_w > 0: bits.append(f"🎫 {utils.formatuj_liczba(inn_w, 0)}")
                opis = "  •  ".join(bits) if bits else "Brak wydatków"

                tresc = [
                    ft.Row([
                        ft.Text(etykieta, weight="bold", size=16, expand=True),
                        ft.Text(f"{utils.formatuj_liczba(razem_w)}  {utils.symbol_waluty()}", weight="bold", size=16, color=ft.Colors.RED_700)
                    ]),
                    ft.Text(opis, size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                ]
                if litry_w > 0:
                    tresc.append(ft.Text(
                        f"Zatankowano {utils.formatuj_liczba(litry_w, 1)} L  •  śr. {utils.formatuj_liczba(sr_cena_w)} {utils.symbol_waluty()}/l",
                        size=12, color=ft.Colors.PRIMARY
                    ))

                return ft.Card(elevation=1, content=ft.Container(padding=15, border_radius=10, content=ft.Column(tresc, spacing=4)))

            self.elementy.append(ft.Text("Zestawienie miesięczne", weight="bold", size=18, color=ft.Colors.PRIMARY))

            if not wiersze_mc_wszystkie:
                self.elementy.append(ft.Text("Brak danych do zestawienia. Dodaj tankowania, wpisy serwisowe lub inne koszty.", color=ft.Colors.ON_SURFACE_VARIANT))
            else:
                opcje_sort = [
                    ("Okres", "okres", lambda x: x[0]),
                    ("Koszt", "koszt", lambda x: x[6]),
                ]
                sort_ui = utils.przycisk_sortowania(self._page, self.state, "stat_miesiace", opcje_sort)
                filtr_rok_ui = utils.przycisk_filtrowania_rok(self._page, self.state, "stat_miesiace_rok", wiersze_mc_wszystkie, 9)
                filtr_mc_ui = utils.przycisk_filtrowania_miesiac(self._page, self.state, "stat_miesiace_mc", wiersze_mc_wszystkie, 9)

                self.elementy.append(
                    ft.Row([sort_ui, filtr_rok_ui, filtr_mc_ui], spacing=6, scroll=ft.ScrollMode.HIDDEN)
                )

                def filtruj_okresy(e):
                    zapytanie = e.control.value.lower().strip()
                    self.lista_kart_stat.controls.clear()
                    for k in self.wszystkie_karty_stat:
                        if zapytanie in k["szukaj"]:
                            self.lista_kart_stat.controls.append(k["karta"])
                    self.update()

                self.elementy.append(
                    ft.TextField(
                        hint_text="Szukaj okresu (np. 2026, Sierpień)...",
                        prefix_icon=ft.Icons.SEARCH,
                        on_change=utils.z_opoznieniem(self._page, filtruj_okresy),
                        **utils.styl_pola()
                    )
                )

                self.lista_kart_stat = ft.Column(spacing=15)
                self.wszystkie_karty_stat = []

                wiersze_mc_f = utils.filtruj_po_roku(wiersze_mc_wszystkie, self.state, "stat_miesiace_rok", 9)
                wiersze_mc_f = utils.filtruj_po_miesiacu(wiersze_mc_f, self.state, "stat_miesiace_mc", 9)
                utils.posortuj_liste(wiersze_mc_f, self.state, "stat_miesiace", opcje_sort)

                if not wiersze_mc_f:
                    self.elementy.append(ft.Row([ft.Text("Brak wyników dla tych filtrów.", color=ft.Colors.ON_SURFACE_VARIANT)], alignment=ft.MainAxisAlignment.CENTER))
                else:
                    for w in wiersze_mc_f:
                        karta = karta_okresu(w)
                        self.wszystkie_karty_stat.append({"karta": karta, "szukaj": w[1].lower()})
                        self.lista_kart_stat.controls.append(karta)
                    self.elementy.append(self.lista_kart_stat)

            self.elementy.append(ft.Divider(height=20))
            self.elementy.append(ft.Text("Zestawienie roczne", weight="bold", size=18, color=ft.Colors.PRIMARY))

            if not wiersze_rok_wszystkie:
                self.elementy.append(ft.Text("Brak danych rocznych.", color=ft.Colors.ON_SURFACE_VARIANT))
            else:
                opcje_sort_rok = [
                    ("Rok", "rok", lambda x: x[0]),
                    ("Koszt", "koszt", lambda x: x[6]),
                ]
                sort_ui_rok = utils.przycisk_sortowania(self._page, self.state, "stat_lata", opcje_sort_rok)
                self.elementy.append(ft.Row([sort_ui_rok], spacing=6, scroll=ft.ScrollMode.HIDDEN))

                utils.posortuj_liste(wiersze_rok_wszystkie, self.state, "stat_lata", opcje_sort_rok)
                self.elementy.append(ft.Column([karta_okresu(w) for w in wiersze_rok_wszystkie], spacing=15))