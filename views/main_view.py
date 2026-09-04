import flet as ft
import flet_charts as fc
from datetime import datetime, timedelta
import calendar
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
        self.kokpit_edycja = False       # True = kafelki kokpitu można przeciągać (patrz _buduj_kokpit)
        self.kokpit_kontener = None      # kontener przełączany między karuzelą a trybem układania
        self._kokpit_budowniczy = {}     # id widżetu -> funkcja budująca kafelek
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
            await asyncio.to_thread(sync.przetworz_kolejke_sync)
            utils.przejdz(self._page, "/")
            konflikty = sync.pobierz_konflikty_ostatniej_synchronizacji()
            if konflikty:
                utils.pokaz_komunikat(self._page, utils.podsumowanie_konfliktow(konflikty), ft.Colors.AMBER_700)
                utils.pokaz_dialog_konfliktow(self._page, konflikty)
            else:
                utils.pokaz_komunikat(self._page, f"Wysłano {wyslano}, pobrano {pobrano} nowych rekordów.")
        except Exception as ex:
            db.zakolejkuj_synchronizacje(self.state.auto_id, "reczna", str(ex))
            utils.pokaz_komunikat(
                self._page,
                f"Błąd synchronizacji: {ex}. Zmiany zostały zakolejkowane i spróbujemy ponownie automatycznie.",
                ft.Colors.RED_700
            )

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
        o stałej szerokości — zamiast układu kolumnowego z parowaniem "połówek".

        Układ jest WŁASNOŚCIĄ POJAZDU: auto służbowe może mieć inne kafelki niż
        prywatne. Pojazd bez własnego układu dziedziczy wspólny (patrz
        db.pobierz_widgety_kokpitu)."""
        wlaczone = db.pobierz_widgety_kokpitu(self.state.auto_id)
        if not wlaczone:
            return ft.Container()

        SZER_KAFLA = 160
        dzisiaj = datetime.now()

        # --- Dane wspólne, liczone tylko gdy faktycznie potrzebne przez wybrane widżety ---
        potrzebne_mc = {"koszt_miesiac", "wykres"} & set(wlaczone)
        dane_mc = db.pobierz_koszty_miesieczne(self.state.auto_id, 6) if potrzebne_mc else []

        potrzebne_porownanie = {"koszt_km", "spalanie"} & set(wlaczone)
        dane_porownanie = db.pobierz_dane_do_porownania(self.state.auto_id) if potrzebne_porownanie else None
        dane_porownanie = dane_porownanie or {}

        # Punkty do sparkline przy „Śr. spalanie” — ta sama metoda liczenia, co
        # wykres trendu w Statystykach, tylko per odcinek między pełnymi bakami.
        # Przy hybrydzie plug-in kafelek „Śr. spalanie” pokazuje stronę PALIWOWĄ
        # (dla elektryka — prądową): mieszanie litrów z kWh w jednej serii dałoby
        # liczbę bez znaczenia. Pełne rozbicie jest w Statystykach.
        rodzaj_kokpitu = db.domyslny_rodzaj_energii(self.state.auto_id)
        seria_spalania = db.pobierz_serie_spalania(self.state.auto_id, 12, rodzaj=rodzaj_kokpitu) if "spalanie" in wlaczone else []
        # Iskra przy pozostałych kafelkach liczbowych — kokpit ma wtedy jeden,
        # spójny język: liczba mówi „ile”, iskra mówi „w którą stronę”.
        seria_przebiegu = db.pobierz_serie_dziennego_przebiegu(self.state.auto_id, 12) if "przebieg_dzienny" in wlaczone else []
        seria_koszt_km = db.pobierz_serie_kosztu_km(self.state.auto_id, 6) if "koszt_km" in wlaczone else []

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

        def kafel_z_iskra(ikona, kolor_ikony, etykieta, wartosc, seria, on_click,
                          wzrost_zly=True, podpis_stopki=None):
            """Kafelek liczbowy wzbogacony o mini-wykres i chip trendu — dokładnie
            ten sam układ, który sprawdził się przy „Śr. spalanie”. Przy mniej niż
            dwóch punktach nie ma czego rysować, więc wracamy do wersji „gołej”,
            zamiast udawać trend z jednego pomiaru."""
            iskra = utils.sparkline(seria, kolor_ikony, wysokosc=30)
            if iskra is None:
                return kafel_wartosci(ikona, kolor_ikony, etykieta, wartosc, on_click)

            pierwsza, ostatnia = seria[0], seria[-1]
            zmiana = ((ostatnia - pierwsza) / pierwsza * 100) if pierwsza > 0 else None

            stopka = ft.Row([
                utils.znacznik_trendu(zmiana, wzrost_zly=wzrost_zly),
                ft.Text(
                    podpis_stopki or f"{len(seria)} ost. pomiarów",
                    size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
                    no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS, expand=True,
                    text_align=ft.TextAlign.END,
                ),
            ], spacing=6)

            return ft.Container(
                width=SZER_KAFLA + 60, padding=15, border_radius=utils.RADIUS["lg"],
                bgcolor=utils.tlo_karty(self._page, poziom=1),
                ink=True, on_click=on_click,
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ikona, size=15, color=kolor_ikony),
                        ft.Text(etykieta, size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                    ], spacing=6),
                    ft.Text(wartosc, size=utils.FS["title"], weight="bold", no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                    iskra,
                    stopka,
                ], spacing=6),
            )

        def widget_koszt_miesiac():
            koszt_biezacy = dane_mc[-1][2] if dane_mc else 0.0
            dzien_dzisiaj = dzisiaj.day

            # W pierwszym tygodniu miesiąca nawet uczciwe porównanie dzień-do-dnia
            # jest zbyt szumiące (1 tankowanie 2. dnia potrafi dać "+900%") — nie
            # pokazujemy wtedy żadnej strzałki trendu, tylko neutralny stan.
            if dzien_dzisiaj < 7 or not dane_mc:
                t_ikona, t_kolor = ft.Icons.INFO_OUTLINE, ft.Colors.ON_SURFACE_VARIANT
                t_tekst = "Za wcześnie na trend"
            else:
                rok_poprz, mies_poprz = dzisiaj.year, dzisiaj.month - 1
                if mies_poprz <= 0:
                    mies_poprz += 12
                    rok_poprz -= 1
                dni_w_poprz_miesiacu = calendar.monthrange(rok_poprz, mies_poprz)[1]
                # Zabezpieczenie na 31. dzień miesiąca porównywanego z krótszym
                # poprzednim miesiącem (np. 31 marca -> luty ma max 28/29 dni).
                do_dnia = min(dzien_dzisiaj, dni_w_poprz_miesiacu)

                koszt_poprzedni_do_dnia = db.pobierz_koszt_miesiaca_do_dnia(
                    self.state.auto_id, rok_poprz, mies_poprz, do_dnia
                )

                if koszt_poprzedni_do_dnia > 0:
                    zmiana = ((koszt_biezacy - koszt_poprzedni_do_dnia) / koszt_poprzedni_do_dnia) * 100
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

            # Iskra z sum miesięcznych: sześć słupków z kafelka „Wydatki 6 mies.”
            # w formie linii, żeby kwota od razu miała tło historyczne.
            iskra_mc = utils.sparkline([s for _, _, s in dane_mc], ft.Colors.PRIMARY, wysokosc=28)

            zawartosc = [
                ft.Row([
                    ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET, size=15, color=ft.Colors.PRIMARY),
                    ft.Text("Koszt w mies.", size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                ], spacing=6),
                ft.Text(f"{utils.formatuj_liczba(koszt_biezacy)} {utils.symbol_waluty()}", size=utils.FS["title"], weight="bold", no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
            ]
            if iskra_mc is not None:
                zawartosc.append(iskra_mc)
            zawartosc.append(
                ft.Row([
                    ft.Icon(t_ikona, size=13, color=t_kolor),
                    ft.Text(t_tekst, size=utils.FS["caption"], color=t_kolor, no_wrap=True),
                ], spacing=4)
            )

            return ft.Container(
                width=SZER_KAFLA + (60 if iskra_mc is not None else 0),
                padding=15, border_radius=utils.RADIUS["lg"],
                bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.PRIMARY),
                ink=True, on_click=idz_do_statystyk(0),
                content=ft.Column(zawartosc, spacing=6),
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
                    ft.Text("Na czas", size=utils.FS["title"], weight="bold", color=ft.Colors.GREEN_700),
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
            # Liczba jest z całego życia auta, iskra pokazuje ostatnie miesiące —
            # dopiero razem widać, czy jazda ostatnio drożeje, czy tanieje.
            return kafel_z_iskra(
                ft.Icons.ADD_ROAD, ft.Colors.PURPLE_700, "Koszt / km", wartosc,
                [v for _, _, v in seria_koszt_km], idz_do_statystyk(0),
                wzrost_zly=True, podpis_stopki=f"{len(seria_koszt_km)} ost. mies.",
            )

        def widget_spalanie():
            czy_prad_kokpit = rodzaj_kokpitu == db.ENERGIA_PRAD
            wartosci_serii = [w for _, w in seria_spalania]
            # Średnia z odcinków TEGO źródła, a nie ogólna z porównania —
            # przy plug-inie tamta mieszała oba światy.
            spalanie = (sum(wartosci_serii) / len(wartosci_serii)) if wartosci_serii else dane_porownanie.get("spalanie")
            wartosc = utils.formatuj_spalanie(spalanie, elektryczny=czy_prad_kokpit) if spalanie else "Za mało danych"
            etykieta = "Śr. zużycie" if czy_prad_kokpit else "Śr. spalanie"
            return kafel_z_iskra(
                ft.Icons.EV_STATION if czy_prad_kokpit else ft.Icons.LOCAL_GAS_STATION,
                ft.Colors.TEAL_700, etykieta, wartosc,
                wartosci_serii, idz_do_zakladki(1),
                wzrost_zly=True, podpis_stopki=f"{len(wartosci_serii)} ost. odcinków",
            )

        def widget_zasieg_ev():
            """Katalogowy zasięg jest z broszury, ten liczymy z Twojego
            rzeczywistego zużycia — i to on mówi, czy dojedziesz."""
            zasieg = db.pobierz_zasieg_ev(self.state.auto_id)
            if not zasieg or not zasieg["szacowany"]:
                wartosc, stopka = "Brak danych", "Uzupełnij baterię i naładuj do pełna"
            else:
                wartosc = f"{utils.formatuj_liczba(zasieg['szacowany'], 0)} km"
                if zasieg["procent_deklarowanego"]:
                    stopka = f"{utils.formatuj_liczba(zasieg['procent_deklarowanego'], 0)}% katalogowego"
                elif zasieg["pojemnosc"]:
                    stopka = f"z {utils.formatuj_liczba(zasieg['pojemnosc'], 0)} kWh"
                else:
                    stopka = "z Twojego zużycia"
            # Własny kafelek zamiast kafel_wartosci, bo potrzebna jest trzecia
            # linijka: „ile procent katalogowego” to sedno tej liczby.
            return ft.Container(
                width=SZER_KAFLA, padding=15, border_radius=utils.RADIUS["lg"],
                bgcolor=utils.tlo_karty(self._page, poziom=1),
                ink=True, on_click=idz_do_statystyk(0),
                tooltip="Realny zasięg policzony z Twojego zużycia",
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.BATTERY_CHARGING_FULL, size=15, color=ft.Colors.GREEN_700),
                        ft.Text("Zasięg EV", size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                    ], spacing=6),
                    ft.Text(wartosc, size=utils.FS["title"], weight="bold", no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(stopka, size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
                            no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                ], spacing=4),
            )

        def widget_przebieg_dzienny():
            sredni = db.oblicz_sredni_dzienny_przebieg(self.state.auto_id)
            wartosc = f"{utils.formatuj_liczba(sredni, 1)} km/dzień" if sredni else "Brak danych"
            wartosci_serii = [w for _, w in seria_przebiegu]
            # Więcej kilometrów to nie „gorzej” — stąd wzrost_zly=False, inaczej
            # aktywniejszy miesiąc dostawałby czerwoną strzałkę jak rosnący koszt.
            return kafel_z_iskra(
                ft.Icons.TIMELAPSE, ft.Colors.BLUE_GREY_700, "Śr. dzienny", wartosc,
                wartosci_serii, lambda e: utils.przejdz(self._page, "/przebieg"),
                wzrost_zly=False, podpis_stopki=f"{len(wartosci_serii)} ost. odcinków",
            )

        def widget_ostatnia_aktywnosc():
            zdarzenia = db.pobierz_ostatnia_aktywnosc(self.state.auto_id, limit=3)
            if not zdarzenia:
                return ft.Container()

            wiersze = []
            for opis, kto, kiedy_tekst, _, ikona, trasa in zdarzenia:
                wiersze.append(
                    ft.Row([
                        ft.Icon(utils.ikona_z_mapy(utils.IKONY_AKTYWNOSCI, ikona), size=15,
                                color=ft.Colors.ON_SURFACE_VARIANT),
                        ft.Column([
                            ft.Text(opis, size=11, weight="bold", no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                            ft.Text(f"{kto} • {kiedy_tekst}", size=10, color=ft.Colors.ON_SURFACE_VARIANT, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                        ], spacing=0, expand=True, tight=True),
                    ], spacing=6)
                )

            return ft.Container(
                width=SZER_KAFLA + 90, padding=15, border_radius=utils.RADIUS["lg"],
                bgcolor=utils.tlo_karty(self._page, poziom=1),
                ink=True, on_click=lambda e: utils.przejdz(self._page, "/timeline"),
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.HISTORY, size=15, color=ft.Colors.PRIMARY),
                        ft.Text("Ostatnia aktywność", size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT),
                    ], spacing=6),
                    ft.Column(wiersze, spacing=6),
                ], spacing=10),
            )

        def widget_kondycja():
            kondycja = db.oblicz_kondycje_pojazdu(self.state.auto_id)
            _, _, etykieta_kond = utils.wskaznik_kondycji(kondycja)
            kolor_gauge = utils.kolor_kondycji_plynny(kondycja)

            # Zamiast samego „82/100”: pierścień wypełniony proporcjonalnie do
            # wyniku i płynnie barwiony od czerwieni do zieleni. Ocena jest wtedy
            # czytelna z odległości, bez czytania liczby — a liczba i tak zostaje
            # w środku dla tych, którzy chcą dokładną wartość.
            return ft.Container(
                width=SZER_KAFLA, padding=15, border_radius=utils.RADIUS["lg"],
                bgcolor=utils.tlo_karty(self._page, poziom=1),
                # Klik prowadzi teraz do ROZPISKI, a nie do magazynu: sam wynik
                # nie mówi, co go obniżyło, i to jest pierwsze pytanie po jego
                # zobaczeniu.
                ink=True, on_click=lambda e: utils.pokaz_panel_kondycji(self._page, self.state),
                tooltip=f"Kondycja pojazdu: {etykieta_kond} — dotknij, aby zobaczyć rozpiskę",
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.MONITOR_HEART, size=15, color=kolor_gauge),
                        ft.Text("Kondycja", size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                    ], spacing=6),
                    ft.Row([utils.gauge_kondycji(kondycja, rozmiar=76, grubosc=8)],
                           alignment=ft.MainAxisAlignment.CENTER),
                    ft.Text(etykieta_kond, size=utils.FS["caption"], color=kolor_gauge,
                            no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS,
                            text_align=ft.TextAlign.CENTER),
                ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            )

        def widget_obserwacja():
            """Najważniejsze spostrzeżenie o pojeździe — jedno zdanie zamiast
            kolejnej liczby. Kokpit ma ograniczoną uwagę, więc bierzemy tylko
            pozycję z najwyższą wagą; pełna lista jest w Statystykach → Analiza."""
            obserwacje = db.obserwacje_analityczne(self.state.auto_id, limit=1)
            if not obserwacje:
                return kafel_wartosci(
                    ft.Icons.INSIGHTS, ft.Colors.BLUE_GREY_700, "Obserwacja",
                    "Brak sygnałów", idz_do_statystyk(3),
                )
            o = obserwacje[0]
            kolor = utils.KOLORY_TONU.get(o["ton"], ft.Colors.BLUE_GREY_700)
            return ft.Container(
                width=SZER_KAFLA + 80, padding=15, border_radius=utils.RADIUS["lg"],
                bgcolor=utils.tlo_karty(self._page, poziom=1),
                border=ft.Border.only(left=ft.BorderSide(3, kolor)),
                ink=True, on_click=idz_do_statystyk(3),
                tooltip=o["tekst"],
                content=ft.Column([
                    ft.Row([
                        ft.Icon(utils.ikona_z_mapy(utils.IKONY_OBSERWACJI, o["ikona"], ft.Icons.INSIGHTS),
                                size=15, color=kolor),
                        ft.Text(o["tytul"], size=utils.FS["caption"], color=kolor, weight="bold",
                                expand=True, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                    ], spacing=6),
                    ft.Text(o["tekst"], size=utils.FS["body"], color=ft.Colors.ON_SURFACE,
                            max_lines=4, overflow=ft.TextOverflow.ELLIPSIS),
                ], spacing=6),
            )

        def widget_budzet():
            """Pasek najbardziej zagrożonego limitu. stan_budzetow sortuje po
            pilności, więc pierwszy element to dokładnie ten, o którym trzeba
            wiedzieć — wszystkie paski naraz byłyby w kokpicie ścianą tekstu."""
            stany = db.stan_budzetow(self.state.auto_id)
            if not stany:
                return kafel_wartosci(
                    ft.Icons.SAVINGS, ft.Colors.BLUE_GREY_700, "Budżet",
                    "Nie ustawiono", lambda e: utils.przejdz(self._page, "/budzet"),
                )
            stan = stany[0]
            return ft.Container(
                width=SZER_KAFLA + 80, padding=15, border_radius=utils.RADIUS["lg"],
                bgcolor=utils.tlo_karty(self._page, poziom=1),
                ink=True, on_click=lambda e: utils.przejdz(self._page, "/budzet"),
                tooltip=f"Budżet {stan['etykieta_okresu'].lower()} — dotknij, aby zmienić limity",
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.SAVINGS, size=15, color=ft.Colors.PRIMARY),
                        ft.Text(f"Budżet • {stan['etykieta_okresu'].lower()}", size=utils.FS["caption"],
                                color=ft.Colors.ON_SURFACE_VARIANT, expand=True,
                                no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                    ], spacing=6),
                    utils.pasek_budzetu(self._page, stan),
                ], spacing=8),
            )

        def widget_zasieg_bak():
            dane = db.pobierz_zasieg_na_baku(self.state.auto_id)
            if not dane:
                return kafel_wartosci(
                    ft.Icons.LOCAL_GAS_STATION, ft.Colors.BLUE_GREY_700, "Zasięg na baku",
                    "Podaj pojemność", lambda e: utils.przejdz(self._page, f"/auto/edytuj/{self.state.auto_id}"),
                )
            return ft.Container(
                width=SZER_KAFLA + 80, padding=15, border_radius=utils.RADIUS["lg"],
                bgcolor=utils.tlo_karty(self._page, poziom=1),
                ink=True, on_click=idz_do_statystyk(3),
                tooltip="Szacunek z licznika i Twojego zużycia — nie z czujnika w aucie",
                content=utils.wskaznik_baku(self._page, dane, kompaktowy=True),
            )

        def widget_prognoza_rok():
            prognoza = db.prognoza_kosztow(self.state.auto_id)
            if not prognoza:
                return kafel_wartosci(
                    ft.Icons.QUERY_STATS, ft.Colors.BLUE_GREY_700, "Prognoza roczna",
                    "Za mało danych", idz_do_statystyk(3),
                )
            wartosc = f"{utils.formatuj_liczba(prognoza['prognoza_calego_roku'], 0)} {utils.symbol_waluty()}"
            stopka = (f"do końca roku jeszcze "
                      f"{utils.formatuj_liczba(prognoza['prognoza_do_konca'], 0)} {utils.symbol_waluty()}")
            return ft.Container(
                width=SZER_KAFLA + 60, padding=15, border_radius=utils.RADIUS["lg"],
                bgcolor=utils.tlo_karty(self._page, poziom=1),
                ink=True, on_click=lambda e: utils.przejdz(self._page, "/rok"),
                tooltip=f"Ekstrapolacja ze średniej z {prognoza['miesiecy_bazowych']} pełnych miesięcy",
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.QUERY_STATS, size=15, color=ft.Colors.DEEP_PURPLE_700),
                        ft.Text(f"Prognoza {prognoza['rok']}", size=utils.FS["caption"],
                                color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                    ], spacing=6),
                    ft.Text(wartosc, size=utils.FS["title"], weight="bold",
                            no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(stopka, size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
                            no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                ], spacing=4),
            )

        self._kokpit_budowniczy = {
            "koszt_miesiac": widget_koszt_miesiac,
            "termin": widget_termin,
            "wykres": widget_wykres,
            "koszt_km": widget_koszt_km,
            "spalanie": widget_spalanie,
            "przebieg_dzienny": widget_przebieg_dzienny,
            "ostatnia_aktywnosc": widget_ostatnia_aktywnosc,
            "kondycja": widget_kondycja,
            "zasieg_ev": widget_zasieg_ev,
            "obserwacja": widget_obserwacja,
            "budzet": widget_budzet,
            "zasieg_bak": widget_zasieg_bak,
            "prognoza_rok": widget_prognoza_rok,
        }

        self.kokpit_kontener = ft.Container(content=self._zawartosc_kokpitu())
        return self.kokpit_kontener

    # ----- Przełączanie kokpitu: karuzela <-> układanie kafelków -----
    def _zawartosc_kokpitu(self):
        """Zawartość kontenera kokpitu zależna od trybu. Kolejność bierzemy za
        każdym razem z bazy, więc po przeciągnięciu kafelka wystarczy odświeżyć
        sam kontener — bez przebudowy całego ekranu i utraty pozycji scrolla."""
        wlaczone = [w for w in db.pobierz_widgety_kokpitu(self.state.auto_id) if w in self._kokpit_budowniczy]
        if not wlaczone:
            return ft.Container()
        if self.kokpit_edycja:
            return self._kokpit_ukladanie(wlaczone)
        return self._kokpit_karuzela(wlaczone)

    def _odswiez_kokpit(self):
        if not self.kokpit_kontener:
            return
        self.kokpit_kontener.content = self._zawartosc_kokpitu()
        try:
            self.kokpit_kontener.update()
        except Exception:
            # Kontener jeszcze nie jest w drzewie strony (np. tuż po zbudowaniu
            # widoku) — przy najbliższym renderze i tak pokaże aktualny stan.
            pass

    def _ustaw_tryb_ukladania(self, wlaczony):
        self.kokpit_edycja = bool(wlaczony)
        self._odswiez_kokpit()

    def _kokpit_karuzela(self, wlaczone):
        """Normalny tryb: pozioma karuzela kafelków. Długie przytrzymanie
        dowolnego kafelka (albo przycisk „Ułóż”) wchodzi w tryb układania."""
        kafelki = []
        for wid in wlaczone:
            kafel = self._kokpit_budowniczy[wid]()
            # Wszystkie widżety zwracają ft.Container, więc uchwyt long-press
            # dopinamy z zewnątrz zamiast powtarzać go w każdym budowniczym.
            try:
                kafel.on_long_press = lambda e: self._ustaw_tryb_ukladania(True)
            except Exception:
                pass
            kafelki.append(kafel)

        if not kafelki:
            return ft.Container()

        przycisk_ukladania = ft.Container(
            width=44, height=44, border_radius=22,
            bgcolor=utils.tlo_karty(self._page, poziom=1),
            alignment=ft.Alignment.CENTER,
            tooltip="Ułóż kafelki (możesz też przytrzymać kafelek)",
            ink=True, on_click=lambda e: self._ustaw_tryb_ukladania(True),
            content=ft.Icon(ft.Icons.DRAG_INDICATOR, size=18, color=ft.Colors.ON_SURFACE_VARIANT),
        )

        return ft.Row(
            kafelki + [przycisk_ukladania],
            spacing=10, scroll=ft.ScrollMode.AUTO,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _kokpit_ukladanie(self, wlaczone):
        """Tryb układania: kafelki zamieniają się w przeciągalne „klocki”
        (ft.ReorderableListView w poziomie). Skróconą formę wybrano celowo —
        pełne kafelki mają różne szerokości i wysokości, więc podczas
        przeciągania skakałyby, a klocki dają stabilny, czytelny cel."""
        etykiety = db.KOKPIT_WIDGETY

        klocki, numery = [], []
        for i, wid in enumerate(wlaczone):
            podpis = str(etykiety.get(wid, wid))
            # Etykiety w KOKPIT_WIDGETY to już sam tekst — ikonę dobieramy z tego
            # samego rejestru, z którego korzystają kafelki kokpitu i Ustawienia.
            ikona_klocka = utils.ikona_z_mapy(utils.IKONY_KOKPITU, wid)

            numer = ft.Text(f"{i + 1}.", size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT)
            numery.append(numer)

            klocek = ft.Container(
                width=150, padding=ft.Padding(12, 10, 12, 10),
                border_radius=utils.RADIUS["md"],
                bgcolor=utils.tlo_karty(self._page, poziom=2),
                border=ft.Border.all(1, ft.Colors.with_opacity(0.25, ft.Colors.PRIMARY)),
                content=ft.Row([
                    ft.Icon(ikona_klocka, size=18, color=ft.Colors.PRIMARY),
                    ft.Column([
                        numer,
                        ft.Text(podpis, size=utils.FS["label"], weight="bold", no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                    ], spacing=0, expand=True, tight=True),
                    ft.Icon(ft.Icons.DRAG_INDICATOR, size=16, color=ft.Colors.ON_SURFACE_VARIANT),
                ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            )
            # Cały klocek jest uchwytem — na telefonie celowanie w samą ikonkę
            # uchwytu byłoby męczące.
            klocki.append(ft.Container(
                padding=ft.Padding.only(right=10),
                content=ft.ReorderableDragHandle(content=klocek, mouse_cursor=ft.MouseCursor.GRAB),
            ))

        kolejnosc = list(wlaczone)

        def przestaw(e):
            """ReorderableListView NIE przestawia swoich `controls` sam — robimy
            to my, tak samo jak listę ID i numerki na klockach. Przestawiamy
            w miejscu (zamiast przebudowywać panel), bo ta lista właśnie
            obsłużyła zdarzenie i podmiana jej pod sobą potrafi zerwać animację
            upuszczenia."""
            stary, nowy = e.old_index, e.new_index
            if stary is None or nowy is None or stary == nowy:
                return
            if not (0 <= stary < len(kolejnosc)) or not (0 <= nowy < len(kolejnosc)):
                return

            kolejnosc.insert(nowy, kolejnosc.pop(stary))
            lista.controls.insert(nowy, lista.controls.pop(stary))
            numery.insert(nowy, numery.pop(stary))
            for i, n in enumerate(numery):
                n.value = f"{i + 1}."

            # Przeciągnięcie kafelka układa kokpit TEGO auta — i tym samym
            # odpina je od wspólnego układu.
            db.zapisz_widgety_kokpitu(kolejnosc, self.state.auto_id)
            try:
                lista.update()
            except Exception:
                pass

        lista = ft.ReorderableListView(
            controls=klocki,
            horizontal=True,
            show_default_drag_handles=False,
            on_reorder=przestaw,
            padding=0,
        )

        naglowek = ft.Row([
            ft.Icon(ft.Icons.DRAG_INDICATOR, size=16, color=ft.Colors.PRIMARY),
            ft.Text("Przeciągnij, aby ułożyć kafelki", size=utils.FS["label"], weight="bold", color=ft.Colors.PRIMARY, expand=True),
            ft.TextButton(
                "Gotowe", icon=ft.Icons.CHECK,
                on_click=lambda e: self._ustaw_tryb_ukladania(False),
            ),
        ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        return ft.Container(
            padding=ft.Padding(12, 10, 12, 12),
            border_radius=utils.RADIUS["lg"],
            bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.PRIMARY),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.25, ft.Colors.PRIMARY)),
            content=ft.Column([
                naglowek,
                ft.Container(height=64, content=lista),
                ft.Text(
                    "Które kafelki są widoczne, wybierzesz w Ustawieniach → Kokpit ekranu głównego.",
                    size=utils.FS["caption"], italic=True, color=ft.Colors.ON_SURFACE_VARIANT,
                ),
            ], spacing=8),
        )

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
            c.execute("SELECT nr_rej, zdjecie_glowne, wiadomosc_statusu FROM samochody WHERE id=?", (self.state.auto_id,))
            w = c.fetchone()

        if not w: return

        wiadomosc_statusu = w["wiadomosc_statusu"]
        aktualny_przebieg = db.pobierz_aktualny_przebieg(self.state.auto_id)

        # Komplet danych pojazdu liczony RAZ: kafel pokazuje teraz także wiek,
        # tablicę i najbliższy termin, a każde z osobnego zapytania robiłoby
        # z jednej karty cztery odpytania bazy przy każdym wejściu na ekran.
        dane_pojazdu = db.pobierz_dane_pojazdu(self.state.auto_id) or {}
        metryki_pojazdu = db.pobierz_metryki_pojazdu(self.state.auto_id, dane_pojazdu) or {}
        najblizszy_termin = db.najblizszy_termin_pojazdu(self.state.auto_id, dane_pojazdu)

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
            """Showroom zamiast listy plików: siatka kart ze zdjęciami pojazdów.
            Auto rozpoznaje się po miniaturze szybciej, niż po przeczytaniu
            nazwy w wierszu listy — przy kilku pojazdach wybór to jedno
            spojrzenie, a nie skanowanie tekstu."""
            with db.polacz_baze() as conn:
                conn.row_factory = sqlite3.Row
                c = conn.cursor()
                c.execute(
                    "SELECT id, nazwa, nr_rej, zdjecie_glowne, nadwozie, kolor_motywu, marka, model "
                    "FROM samochody ORDER BY nazwa"
                )
                auta_siatki = c.fetchall()

            bs = ft.BottomSheet(ft.Container())
            karty_aut = {}  # id -> (ramka, odznaka)

            # Dwie kolumny na telefonie, trzy na szerokim ekranie. Miniatura musi
            # zostać na tyle duża, żeby dało się rozpoznać auto bez czytania nazwy.
            try:
                szer_ekranu = self._page.width or getattr(self._page.window, "width", None) or 400
            except Exception:
                szer_ekranu = 400
            KOLUMNY = 3 if szer_ekranu >= 620 else 2
            SZER_KARTY = max(128, int((szer_ekranu - 2 * 20 - (KOLUMNY - 1) * 10) / KOLUMNY))
            WYS_ZDJECIA = int(SZER_KARTY * 0.62)

            def wybierz(aid, an):
                for k_aid, (ramka, odznaka) in karty_aut.items():
                    zazn = (k_aid == aid)
                    ramka.border = ft.Border.all(2, ft.Colors.PRIMARY if zazn else ft.Colors.TRANSPARENT)
                    odznaka.visible = zazn

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

            def zastepcze_zdjecie(a=None):
                """Pojazd bez zdjęcia (albo ze zdjęciem, którego nie ma już na
                dysku) nie może wypaść z siatki — dostaje kafelek z sylwetką
                nadwozia w kolorze przypisanym do TEGO auta, więc karta zachowuje
                ten sam rozmiar i rytm, a auta nadal różnią się od siebie."""
                kolor = utils.MAPA_KOLOROW.get((a["kolor_motywu"] if a is not None else None) or "", ft.Colors.PRIMARY)
                nadwozie = a["nadwozie"] if a is not None else None
                return ft.Container(
                    width=SZER_KARTY, height=WYS_ZDJECIA,
                    bgcolor=ft.Colors.with_opacity(0.10, kolor),
                    alignment=ft.Alignment.CENTER,
                    content=ft.Icon(
                        utils.ikona_nadwozia(nadwozie), size=42,
                        color=ft.Colors.with_opacity(0.60, kolor)
                    ),
                )

            def karta_auta(a):
                a_id, a_nazwa = a["id"], a["nazwa"]
                zaznaczone = (a_id == self.state.auto_id)

                ma_zdjecie = bool(a["zdjecie_glowne"])
                if ma_zdjecie:
                    miniatura = ft.Image(
                        src=utils.abs_zalacznik(a["zdjecie_glowne"]),
                        width=SZER_KARTY, height=WYS_ZDJECIA, fit="cover",
                        error_content=zastepcze_zdjecie(a),
                    )
                else:
                    miniatura = zastepcze_zdjecie(a)

                odznaka = ft.Container(
                    top=6, right=6, visible=zaznaczone,
                    width=24, height=24, border_radius=12,
                    bgcolor=ft.Colors.PRIMARY, alignment=ft.Alignment.CENTER,
                    content=ft.Icon(ft.Icons.CHECK, size=15, color=ft.Colors.ON_PRIMARY),
                )

                # Przy zdjęciu sylwetka schodzi do rogu jako mała plakietka —
                # zdjęcie i tak rozpoznaje auto, ale kolor odznaki utrzymuje
                # ten sam „klucz” wizualny na całej liście.
                plakietka = ft.Container(
                    bottom=6, left=6, visible=ma_zdjecie,
                    content=utils.odznaka_pojazdu(a, rozmiar=26),
                )

                ramka = ft.Container(
                    width=SZER_KARTY,
                    border_radius=utils.RADIUS["md"],
                    border=ft.Border.all(2, ft.Colors.PRIMARY if zaznaczone else ft.Colors.TRANSPARENT),
                    bgcolor=utils.tlo_karty(self._page, poziom=2),
                    clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                    tooltip=str(a_nazwa),
                    on_click=lambda ev, aid=a_id, an=a_nazwa: wybierz(aid, an),
                    content=ft.Column([
                        ft.Stack([miniatura, plakietka, odznaka], width=SZER_KARTY, height=WYS_ZDJECIA),
                        ft.Container(
                            padding=ft.Padding(8, 6, 8, 8),
                            content=ft.Column([
                                ft.Text(
                                    str(a_nazwa), size=utils.FS["body_strong"], weight="bold",
                                    no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS,
                                    color=ft.Colors.PRIMARY if zaznaczone else ft.Colors.ON_SURFACE,
                                ),
                                # Ta sama tablica, co na kaflu głównym — w showroomie
                                # to ona (a nie nazwa) najszybciej rozstrzyga, które
                                # z dwóch podobnych aut jest które.
                                utils.tablica_rejestracyjna(a["nr_rej"], wysokosc=20)
                                if a["nr_rej"] else ft.Text(
                                    "Brak rejestracji",
                                    size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
                                    no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                            ], spacing=1, tight=True),
                        ),
                    ], spacing=0, tight=True),
                )

                karty_aut[a_id] = (ramka, odznaka)
                return ramka

            # Dokładanie auta to kolejne miejsce w showroomie, a nie pozycja
            # w menu — dlatego kafelek "Dodaj" ma wymiary karty pojazdu.
            kafel_dodaj = ft.Container(
                width=SZER_KARTY,
                border_radius=utils.RADIUS["md"],
                border=ft.Border.all(2, ft.Colors.with_opacity(0.35, ft.Colors.GREEN)),
                bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.GREEN),
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                tooltip="Dodaj nowy pojazd",
                on_click=lambda ev: dodaj(),
                content=ft.Column([
                    ft.Container(
                        width=SZER_KARTY, height=WYS_ZDJECIA, alignment=ft.Alignment.CENTER,
                        content=ft.Icon(ft.Icons.ADD_CIRCLE_OUTLINE, size=34, color=ft.Colors.GREEN),
                    ),
                    ft.Container(
                        padding=ft.Padding(8, 6, 8, 8),
                        content=ft.Text(
                            "Dodaj pojazd", size=utils.FS["body_strong"], weight="bold",
                            color=ft.Colors.GREEN, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                    ),
                ], spacing=0, tight=True),
            )

            siatka = ft.Row(
                [karta_auta(a) for a in auta_siatki] + [kafel_dodaj],
                wrap=True, spacing=10, run_spacing=10,
            )

            bs.content = ft.Container(
                padding=20,
                bgcolor=ft.Colors.SURFACE,
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.GARAGE, color=ft.Colors.PRIMARY, size=22),
                        ft.Text("Wybierz pojazd", weight="bold", size=18, color=ft.Colors.PRIMARY, expand=True),
                        ft.Text(
                            f"{len(auta_siatki)} w garażu",
                            size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
                        ),
                    ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    ft.Divider(height=1),
                    siatka,
                ], tight=True, spacing=12, scroll=ft.ScrollMode.AUTO)
            )
            utils.otworz_dno(self._page, bs)

        kondycja = db.oblicz_kondycje_pojazdu(self.state.auto_id)
        kolor_kond, ikona_kond, etykieta_kond = utils.wskaznik_kondycji(kondycja)

        # Dawny bottom-sheet „Specyfikacja pojazdu” zastąpił pełny ekran /pojazd.
        # Przy komplecie danych (terminy, zakup, ubezpieczenie, ściągawka) panel
        # wysuwany rozciągał się na trzy ekrany przewijania, nie dawał się
        # przeszukać ani skopiować, a przycisk wstecz zamykał go zamiast cofać.
        def pokaz_info_auta(e):
            utils.przejdz(self._page, "/pojazd")

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

                db.dodaj_odczyt_przebiegu(self.state.auto_id, nowy, zrodlo="kokpit")
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
                    ft.TextButton("Przejdź do historii odczytów", icon=ft.Icons.SHOW_CHART, on_click=zobacz_historie)
                ], tight=True, spacing=10),
                actions=[
                    ft.TextButton("Anuluj", on_click=lambda e2: utils.zamknij_dialog(self._page, dlg)),
                    ft.ElevatedButton("Zapisz", on_click=zapisz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY)
                ],
                actions_alignment=ft.MainAxisAlignment.END
            )
            utils.otworz_dialog(self._page, dlg)
        # ------------------------------------------------------

        # --- KOMPAKTOWY AWATAR (60x60) Z PIERŚCIENIEM KONDYCJI ---
        WYM_AWATARA, WYM_PIERSCIENIA = 60, 68
        zdjecie_glowne = w["zdjecie_glowne"]
        if zdjecie_glowne:
            tresc_awatara = ft.Image(
                src=utils.abs_zalacznik(zdjecie_glowne), width=WYM_AWATARA, height=WYM_AWATARA,
                fit="cover", border_radius=utils.RADIUS["lg"],
            )
        else:
            tresc_awatara = ft.Container(
                width=WYM_AWATARA, height=WYM_AWATARA, border_radius=utils.RADIUS["lg"],
                bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.PRIMARY),
                alignment=ft.Alignment.CENTER,
                content=ft.Icon(ft.Icons.DIRECTIONS_CAR, size=28, color=ft.Colors.PRIMARY),
            )

        # NOWE: wartość i kolor identyczne jak w bottom-sheecie (pokaz_info_auta) —
        # tylko teraz widoczne od razu, bez klikania w "Info".
        wartosc_pierscienia = (max(0, min(100, kondycja)) / 100) if kondycja is not None else 0.0
        # Ten sam płynny kolor, co na kołowym wskaźniku w kokpicie — pierścień
        # przy awatarze i kafelek „Kondycja” nie mogą pokazywać dwóch różnych barw
        # dla tej samej liczby.
        kolor_pierscienia = utils.kolor_kondycji_plynny(kondycja)
        awatar = ft.Container(
            width=WYM_PIERSCIENIA, height=WYM_PIERSCIENIA,
            tooltip=f"Kondycja: {kondycja if kondycja is not None else '-'}/100 ({etykieta_kond})",
            on_click=pokaz_info_auta,
            content=ft.Stack([
                ft.ProgressRing(
                    value=wartosc_pierscienia, width=WYM_PIERSCIENIA, height=WYM_PIERSCIENIA,
                    stroke_width=4, color=kolor_pierscienia, stroke_cap=ft.StrokeCap.ROUND,
                    bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
                ),
                ft.Container(tresc_awatara, width=WYM_PIERSCIENIA, height=WYM_PIERSCIENIA, alignment=ft.Alignment.CENTER),
            ], width=WYM_PIERSCIENIA, height=WYM_PIERSCIENIA),
        )

        tytulowy_wiersz = ft.Row([
            ft.Container(
                content=ft.Row([
                    ft.Text(
                        str(self.state.auto_nazwa), size=16, weight="bold", color=ft.Colors.PRIMARY,
                        no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    ft.Icon(ft.Icons.ARROW_DROP_DOWN, color=ft.Colors.PRIMARY, size=18)
                ], spacing=0, tight=True),
                on_click=pokaz_wybor_aut,
                tooltip="Dotknij, aby wybrać z listy",
            ),
            # Chmurka pojawia się tylko przy niewysłanych zmianach tego pojazdu —
            # wcześniej trzeba było wejść w ekran Współdzielenia, żeby to zobaczyć.
            utils.wskaznik_synchronizacji(self._page, self.state.auto_id),
        ], spacing=0, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        # Rejestracja rysowana jak prawdziwa tablica. To po niej rozpoznaje się
        # auto w świecie poza aplikacją (parking, warsztat, ubezpieczyciel),
        # a jako szary tekst obok innych szarych tekstów po prostu ginęła.
        if w["nr_rej"]:
            wiersz_rejestracja = ft.Row([
                utils.tablica_rejestracyjna(
                    w["nr_rej"], wysokosc=26,
                    on_click=lambda e: utils.kopiuj_do_schowka(
                        self._page, w["nr_rej"], "Skopiowano numer rejestracyjny"),
                ),
            ], spacing=6, tight=True)
        else:
            wiersz_rejestracja = ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.BADGE, size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Text("Dodaj numer rejestracyjny", size=12, italic=True,
                            color=ft.Colors.ON_SURFACE_VARIANT),
                ], spacing=4),
                on_click=lambda e: utils.przejdz(self._page, f"/auto/edytuj/{self.state.auto_id}"),
                tooltip="Dotknij, aby uzupełnić dane pojazdu",
            )

        def pokaz_edycja_statusu(e):
            pole_status = ft.TextField(
                label="Status / wiadomość dla domowników",
                value=str(wiadomosc_statusu) if wiadomosc_statusu else "",
                hint_text="np. Zatankowany do pełna, Odebrałem z myjni",
                multiline=True,
                max_lines=3,
                autofocus=True,
                **utils.styl_pola()
            )

            def zapisz(e2):
                nowa_wiadomosc = (pole_status.value or "").strip()

                with db.polacz_baze() as conn:
                    conn.execute("UPDATE samochody SET wiadomosc_statusu=? WHERE id=?", (nowa_wiadomosc or None, self.state.auto_id))

                utils.zamknij_dialog(self._page, dlg)

                # Ciche wypchnięcie do chmury w tle, jeśli pojazd jest współdzielony —
                # analogicznie do zapisu tankowania (forms_view.py): partner nie musi
                # ręcznie klikać "Synchronizuj", żeby zobaczyć nowy status.
                utils.wypchnij_w_tle(self._page, self.state.auto_id, "status")

                utils.przejdz(self._page, "/")
                utils.pokaz_komunikat(self._page, "Zaktualizowano status pojazdu!")

            dlg = ft.AlertDialog(
                modal=True,
                title=ft.Row([ft.Icon(ft.Icons.CHAT_BUBBLE_OUTLINE, color=ft.Colors.PRIMARY), ft.Text("Status pojazdu", weight="bold", size=16, expand=True)], spacing=8),
                content=ft.Column([
                    ft.Text("Krótka wiadomość widoczna dla wszystkich domowników korzystających z tego pojazdu.", size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                    pole_status,
                ], tight=True, spacing=10),
                actions=[
                    ft.TextButton("Anuluj", on_click=lambda e2: utils.zamknij_dialog(self._page, dlg)),
                    ft.ElevatedButton("Zapisz", on_click=zapisz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY),
                ],
            )
            utils.otworz_dialog(self._page, dlg)

        # Przebieg z wiekiem obok siebie: dopiero razem mówią, czy 135 tys. km
        # to dużo. Wiek jest tylko dopiskiem — dotknięcie nadal aktualizuje licznik.
        metryki_bity = [
            ft.Icon(ft.Icons.SPEED, size=13, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Text(f"{utils.formatuj_liczba(aktualny_przebieg, 0)} km", size=13, weight="bold"),
            ft.Icon(ft.Icons.EDIT, size=11, color=ft.Colors.PRIMARY),
        ]
        if metryki_pojazdu.get("wiek_lat"):
            metryki_bity.append(ft.Text(
                f"•  {utils.formatuj_liczba(metryki_pojazdu['wiek_lat'], 1)} lat",
                size=12, color=ft.Colors.ON_SURFACE_VARIANT))
        if metryki_pojazdu.get("przebieg_roczny"):
            metryki_bity.append(ft.Text(
                f"•  {utils.formatuj_liczba(metryki_pojazdu['przebieg_roczny'], 0)} km/rok",
                size=12, color=ft.Colors.ON_SURFACE_VARIANT,
                no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS))

        wiersz_przebieg = ft.Container(
            content=ft.Row(metryki_bity, spacing=5),
            on_click=pokaz_szybka_aktualizacja_przebiegu,
            on_long_press=lambda e: utils.przejdz(self._page, "/przebieg"),
            tooltip="Dotknij: aktualizuj  •  Przytrzymaj: historia licznika",
        )

        # Najbliższy termin WPROST na kaflu. Dotąd data OC czy przeglądu była
        # schowana pod przyciskiem „i” — czyli widziało ją się dopiero wtedy,
        # gdy się jej szukało, a nie wtedy, gdy zaczynała gonić.
        if najblizszy_termin:
            kolor_terminu = utils.KOLORY_STATUSU_TERMINU.get(
                najblizszy_termin["status"], ft.Colors.ON_SURFACE_VARIANT)
            wiersz_termin_kafla = ft.Container(
                padding=ft.Padding(8, 5, 8, 5),
                border_radius=utils.RADIUS["sm"],
                bgcolor=ft.Colors.with_opacity(
                    0.13 if najblizszy_termin["status"] != "ok" else 0.07, kolor_terminu),
                on_click=lambda e: utils.przejdz(self._page, "/pojazd"),
                tooltip="Wszystkie terminy pojazdu",
                content=ft.Row([
                    ft.Icon(utils.ikona_z_mapy(utils.IKONY_STATUSU_TERMINU,
                                               najblizszy_termin["status"], ft.Icons.EVENT),
                            size=13, color=kolor_terminu),
                    ft.Text(
                        f"{najblizszy_termin['etykieta']} — "
                        f"{utils.opis_dni_terminu(najblizszy_termin['dni'])}",
                        size=12, weight="bold", color=kolor_terminu, expand=True,
                        no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(najblizszy_termin["data"], size=11, color=kolor_terminu),
                ], spacing=5),
            )
        else:
            wiersz_termin_kafla = ft.Container(width=0, height=0)

        wiersz_status = ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.CHAT_BUBBLE_OUTLINE, size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Text(
                    str(wiadomosc_statusu) if wiadomosc_statusu else "Dodaj status dla domowników...",
                    size=13,
                    italic=not bool(wiadomosc_statusu),
                    color=ft.Colors.ON_SURFACE if wiadomosc_statusu else ft.Colors.ON_SURFACE_VARIANT,
                    no_wrap=True,
                    overflow=ft.TextOverflow.ELLIPSIS,
                    expand=True,
                ),
            ], spacing=5),
            on_click=pokaz_edycja_statusu,
            tooltip="Dotknij, aby ustawić status dla domowników",
        )

        kolumna_tekstowa = ft.Column([
            tytulowy_wiersz,
            wiersz_rejestracja,
            wiersz_przebieg,
            wiersz_status,
        ], spacing=4, expand=True)

        przyciski_karty = ft.Column([
            ft.IconButton(
                icon=ft.Icons.INFO_OUTLINE, icon_size=20, icon_color=ft.Colors.PRIMARY,
                tooltip="Karta pojazdu: terminy, wartość, ubezpieczenie, ściągawka",
                on_click=pokaz_info_auta,
                style=ft.ButtonStyle(padding=0), width=32, height=32,
            ),
            ft.IconButton(
                icon=ft.Icons.EDIT, icon_size=16, icon_color=ft.Colors.ON_SURFACE_VARIANT,
                tooltip="Edytuj pojazd",
                on_click=lambda e: utils.przejdz(self._page, f"/auto/edytuj/{self.state.auto_id}"),
                style=ft.ButtonStyle(padding=0), width=32, height=32,
            ),
        ], spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER)

        # --- TŁO KARTY: rozmyte zdjęcie pojazdu zamiast płaskiego koloru ---
        # Zdjęcie idzie pod treść mocno rozmyte i przykryte gradientem w kolorze
        # powierzchni. Karta ma nieść „to jest MOJE auto" barwą i kształtem
        # widocznym kątem oka, a nie czytelnym obrazkiem — pod nazwą, rejestracją
        # i statusem musi zostać tło o przewidywalnym kontraście, niezależnie od
        # tego, czy zdjęcie jest jasne, ciemne czy kontrastowe.
        PROMIEN_KARTY = 12  # zgodny z domyślnym kształtem ft.Card (RoundedRectangleBorder 12)

        tresc_karty = ft.Container(
            padding=12, border_radius=PROMIEN_KARTY,
            content=ft.Column([
                ft.Row([awatar, kolumna_tekstowa, przyciski_karty], spacing=12,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
                wiersz_termin_kafla,
            ], spacing=8),
        )

        if zdjecie_glowne:
            wnetrze_karty = ft.Stack([
                # Warstwa 1 — zdjęcie wypełniające całą kartę (kadrowane, nie skalowane).
                ft.Container(
                    left=0, top=0, right=0, bottom=0,
                    border_radius=PROMIEN_KARTY,
                    image=ft.DecorationImage(
                        src=utils.abs_zalacznik(zdjecie_glowne),
                        fit=ft.BoxFit.COVER,
                        alignment=ft.Alignment.CENTER,
                    ),
                ),
                # Warstwa 2 — rozmycie tego, co pod spodem, plus gradient w kolorze
                # motywu. Gradient jest lżejszy w lewym górnym rogu (przy awatarze),
                # a gęstnieje w stronę wiersza statusu, czyli tam, gdzie tekstu
                # jest najwięcej.
                ft.Container(
                    left=0, top=0, right=0, bottom=0,
                    border_radius=PROMIEN_KARTY,
                    blur=ft.Blur(18, 18),
                    gradient=ft.LinearGradient(
                        begin=ft.Alignment.TOP_LEFT,
                        end=ft.Alignment.BOTTOM_RIGHT,
                        colors=[
                            ft.Colors.with_opacity(0.74, ft.Colors.SURFACE),
                            ft.Colors.with_opacity(0.93, ft.Colors.SURFACE),
                        ],
                    ),
                ),
                tresc_karty,
            ])
        else:
            wnetrze_karty = tresc_karty

        karta_auta = ft.Card(
            elevation=1,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            content=wnetrze_karty,
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

        naglowek_serwis = utils.tytul_sekcji(ft.Icons.BUILD_CIRCLE, "Serwis")
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
                    procent_km = None
                    procent_dni = None
                    prog_km_z = int(z.get('prog_km') or prog_km)
                    prog_dni_z = int(z.get('prog_dni') or prog_dni)
                    if z.get('interwal_km') and z.get('przebieg'):
                        interwal_km = int(z.get('interwal_km'))
                        zost_km = (int(z.get('przebieg')) + interwal_km) - akt_prz
                        procent_km = (interwal_km - zost_km) / interwal_km if interwal_km > 0 else None
                        if zost_km < 0:
                            stxt.append(f"{utils.formatuj_liczba(abs(zost_km), 0)} km po!")
                            kol, ico = ft.Colors.RED_700, ft.Icons.WARNING
                        elif zost_km <= prog_km_z:
                            prognoza = utils.formatuj_prognoze_km(zost_km, sredni_dzienny)
                            stxt.append(prognoza or f"{utils.formatuj_liczba(zost_km, 0)} km")
                            kol, ico = ft.Colors.ORANGE_700, ft.Icons.HOURGLASS_BOTTOM
                        else:
                            prognoza = utils.formatuj_prognoze_km(zost_km, sredni_dzienny)
                            stxt.append(prognoza or f"{utils.formatuj_liczba(zost_km, 0)} km")

                    if z.get('interwal_miesiace') and z.get('data'):
                        d_w = utils.parsuj_date(z.get('data'))
                        if d_w != datetime.min.date():
                            interwal_dni = int(float(z.get('interwal_miesiace')) * 30.5)
                            zost_dni = (d_w + timedelta(days=interwal_dni) - datetime.now().date()).days
                            procent_dni = (interwal_dni - zost_dni) / interwal_dni if interwal_dni > 0 else None
                            if zost_dni < 0:
                                stxt.append(f"{abs(zost_dni)} dni po!")
                                kol, ico = ft.Colors.RED_700, ft.Icons.WARNING
                            elif zost_dni <= prog_dni_z:
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

                    # Jeśli podzespół ma zarówno interwał km, jak i miesięczny,
                    # pasek pokazuje ten, który jest BLIŻEJ przekroczenia (wyższy
                    # procent zużycia) — to ten sam interwał, który decyduje
                    # o kolorze/pilności karty wyliczonym wyżej.
                    kandydaci_procent = [p for p in (procent_km, procent_dni) if p is not None]
                    procent_do_paska = max(kandydaci_procent) if kandydaci_procent else None

                    wiersz_statusu = (
                        utils.pasek_postepu(final_status, f"{int(max(0.0, min(1.0, procent_do_paska)) * 100)}%", procent_do_paska, kol)
                        if procent_do_paska is not None
                        else ft.Text(final_status, size=utils.FS["body_strong"], weight="bold", color=kol)
                    )
                    karta_z, kontener = utils.karta_listy(
                        ft.Column([
                            ft.Row([ft.Text(str(zn), weight="bold", size=utils.FS["title"], expand=True), ft.Icon(ico, color=kol)]),
                            ft.Text(f"Wymieniono: {data_w} | Przy: {prz_w}", size=utils.FS["body"], color=ft.Colors.ON_SURFACE_VARIANT),
                            wiersz_statusu
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
        elektryczny = db.czy_pojazd_elektryczny(self.state.auto_id)
        etykiety = db.etykiety_paliwa(elektryczny)
        naglowek_bits = utils.tytul_sekcji(
            utils.ikona_z_mapy(utils.IKONY_AKTYWNOSCI, etykiety.get("ikona_listy", "tankowanie")),
            etykiety["naglowek_listy"],
        )
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

            # Rodzaj energii normalizujemy raz: wpisy sprzed migracji 33 mają
            # NULL i biorą domyślny dla pojazdu.
            domyslny_rodzaj = db.domyslny_rodzaj_energii(self.state.auto_id)
            for t in baza_lista:
                t['rodzaj'] = str(t.get('rodzaj_energii') or domyslny_rodzaj)

            # Zużycie liczymy OSOBNO w obrębie każdego źródła — przy hybrydzie
            # plug-in odcinek „od pełnego baku do pełnego baku” nie ma nic
            # wspólnego z ładowaniami, które wypadły pomiędzy nimi.
            ostatni_pelny = {}
            poprzedni_przebieg = {}
            for i, t in enumerate(baza_lista):
                rodzaj = t['rodzaj']
                prz_akt = int(t.get('przebieg') or 0)

                poprz = poprzedni_przebieg.get(rodzaj)
                t['dystans'] = max(0, prz_akt - poprz) if poprz is not None else 0
                poprzedni_przebieg[rodzaj] = prz_akt

                t['spalanie'] = None
                if t.get('do_pelna'):
                    idx_poprzedniego = ostatni_pelny.get(rodzaj)
                    if idx_poprzedniego is not None:
                        prz_ostatni_pelny = int(baza_lista[idx_poprzedniego].get('przebieg') or 0)
                        dystans_od_pelnego = prz_akt - prz_ostatni_pelny
                        ilosc_od_pelnego = sum(
                            float(baza_lista[k].get('litry') or 0)
                            for k in range(idx_poprzedniego + 1, i + 1)
                            if baza_lista[k]['rodzaj'] == rodzaj
                        )
                        if dystans_od_pelnego > 0:
                            t['spalanie'] = (ilosc_od_pelnego / dystans_od_pelnego) * 100
                    ostatni_pelny[rodzaj] = i

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

            # „Kto to dodał” ma sens dopiero przy pojeździe współdzielonym —
            # przy jednym użytkowniku każdy wpis jest jego i filtr byłby szumem.
            filtry_ui = [sort_ui, filtr_rok_ui, filtr_mc_ui, filtr_tag_ui]
            # Przy hybrydzie plug-in lista miesza tankowania z ładowaniami —
            # bez filtra nie da się obejrzeć samej jednej strony.
            if len(db.rodzaje_energii_pojazdu(self.state.auto_id)) > 1:
                filtry_ui.insert(1, utils.przycisk_filtrowania_kategoria(
                    self._page, self.state, "tankowania_rodzaj",
                    [{"rodzaj_opis": db.ETYKIETY_RODZAJU[t['rodzaj']]} for t in baza_lista],
                    "rodzaj_opis", "Źródło"
                ))
            if wspolny_id:
                filtry_ui.append(
                    utils.przycisk_filtrowania_autora(self._page, self.state, "tankowania_autor", baza_lista, "dodane_przez")
                )

            self.elementy.append(ft.Row(filtry_ui, spacing=6, scroll=ft.ScrollMode.HIDDEN))

            def filtruj_tankowania(e):
                zapytanie = e.control.value.lower().strip()
                self.lista_kart_tankowania.controls.clear()
                for k in self.wszystkie_karty_tankowania:
                    if zapytanie in k["szukaj"]:
                        self.lista_kart_tankowania.controls.append(k["karta"])
                self.update()

            self.elementy.append(
                ft.TextField(
                    hint_text="Szukaj tankowania (stacja, data, kwota, dystans, notatka)...",
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
            if len(db.rodzaje_energii_pojazdu(self.state.auto_id)) > 1:
                for t in po_filtrach:
                    t["rodzaj_opis"] = db.ETYKIETY_RODZAJU[t["rodzaj"]]
                po_filtrach = utils.filtruj_po_kategorii(po_filtrach, self.state, "tankowania_rodzaj", "rodzaj_opis")
            if wspolny_id:
                po_filtrach = utils.filtruj_po_autorze(po_filtrach, self.state, "tankowania_autor", "dodane_przez")
            utils.posortuj_liste(po_filtrach, self.state, "tankowania", opcje_sort)

            def otworz_menu_t(tid, zalacznik=None, notatka=None):
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

                pozycje.append(utils.pozycja_menu_notatki(
                    self._page, "tankowania", tid, notatka,
                    lambda: utils.przejdz(self._page, "/"), "Notatka do tankowania"
                ))
                pozycje.append({"ikona": ft.Icons.EDIT, "tekst": "Edytuj", "akcja": lambda: utils.przejdz(self._page, f"/tankowanie/edytuj/{tid}")})
                pozycje.append({"ikona": ft.Icons.CONTENT_COPY, "tekst": "Duplikuj", "akcja": lambda: (setattr(self.state, "duplikuj_zrodlo_tankowanie", tid), utils.przejdz(self._page, "/tankowanie/nowe"))})
                pozycje.append({"ikona": ft.Icons.DELETE, "tekst": "Usuń", "akcja": usun_tankowanie, "kolor": ft.Colors.RED})

                utils.pokaz_menu_kontekstowe(self._page, "Opcje tankowania", pozycje)

            if not po_filtrach:
                self.elementy.append(ft.Row([ft.Text("Brak wyników dla tych filtrów.", color=ft.Colors.ON_SURFACE_VARIANT)], alignment=ft.MainAxisAlignment.CENTER))
            else:
                mapa_tagow = {t[1]: t[2] for t in db.pobierz_tagi(self.state.auto_id)}
                dwuzrodlowy_lista = len(db.rodzaje_energii_pojazdu(self.state.auto_id)) > 1
                for w in po_filtrach:
                    # Etykiety idą za RODZAJEM WPISU, nie za typem pojazdu —
                    # w jednej liście plug-ina stoją obok siebie litry i kWh.
                    rodzaj_w = w.get('rodzaj') or db.ENERGIA_PALIWO
                    czy_prad_w = rodzaj_w == db.ENERGIA_PRAD
                    etykiety_w = db.etykiety_energii(rodzaj_w)
                    spalanie = w.get('spalanie')
                    sp_str = utils.formatuj_spalanie(spalanie, elektryczny=czy_prad_w)
                    kwota_val = float(w.get('kwota') or 0)
                    litry_val = float(w.get('litry') or 0)
                    cena_str = f"{utils.formatuj_liczba(kwota_val)}  {utils.symbol_waluty()}"
                    cena_litr_str = f"{utils.formatuj_liczba(kwota_val / litry_val, 2)} {utils.symbol_waluty()}/{etykiety_w['jednostka']}" if litry_val > 0 else "-"
                    dystans_val = w.get('dystans') or 0

                    tid = w.get('id')
                    tresc_karty = [
                        ft.Row([
                            ft.Text(f"{w.get('data')} • {w.get('stacja')}" if w.get('stacja') else str(w.get('data')), weight="bold", color=ft.Colors.ON_SURFACE_VARIANT),
                            ft.Row([
                                # Odznaka źródła tylko przy plug-inie — przy aucie
                                # jednoźródłowym byłaby tą samą etykietą przy każdym wpisie.
                                ft.Container(
                                    padding=ft.Padding(6, 1, 6, 1),
                                    border_radius=utils.RADIUS["pill"],
                                    bgcolor=ft.Colors.with_opacity(0.14, ft.Colors.GREEN if czy_prad_w else ft.Colors.BLUE),
                                    content=ft.Row([
                                        ft.Icon(ft.Icons.EV_STATION if czy_prad_w else ft.Icons.LOCAL_GAS_STATION,
                                                size=11, color=ft.Colors.GREEN_800 if czy_prad_w else ft.Colors.BLUE_800),
                                        ft.Text(db.ETYKIETY_RODZAJU[rodzaj_w] + (f" · {w.get('typ_ladowania')}" if czy_prad_w and w.get('typ_ladowania') else ""),
                                                size=10, weight="bold",
                                                color=ft.Colors.GREEN_800 if czy_prad_w else ft.Colors.BLUE_800),
                                    ], spacing=3, tight=True),
                                ) if dwuzrodlowy_lista else ft.Container(),
                                utils.wskaznik_zalacznika(self._page, w.get('zalacznik'), "Tankowanie"),
                                ft.Icon(ft.Icons.EV_STATION if czy_prad_w else ft.Icons.LOCAL_GAS_STATION, size=14, color=ft.Colors.PRIMARY, tooltip="Do pełna") if w.get('do_pelna') else ft.Container(),
                                ft.Text(f"-{cena_str}", weight="bold", color=ft.Colors.RED_700)
                            ], spacing=4)
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Row([
                            ft.Column([ft.Text("Dystans", size=11, color=ft.Colors.ON_SURFACE_VARIANT), ft.Text(f"{dystans_val} km", weight="bold")]),
                            ft.Column([ft.Text(etykiety_w["zuzycie"], size=11, color=ft.Colors.ON_SURFACE_VARIANT), ft.Text(sp_str, weight="bold")]),
                            ft.Column([ft.Text(etykiety_w["cena_jednostkowa"], size=11, color=ft.Colors.ON_SURFACE_VARIANT), ft.Text(cena_litr_str, weight="bold")]),
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                    ]
                    if w.get('tagi'):
                        tresc_karty.append(utils.wizualizacja_tagow(w.get('tagi'), self.state.auto_id, mapa_tagow))
                    tresc_karty.append(utils.podglad_notatki(
                        self._page, w.get('notatka'), w.get('notatka_autor'), w.get('notatka_data'),
                        "Notatka do tankowania",
                        on_edytuj=lambda rid=tid: utils.szybka_notatka(
                            self._page, "tankowania", rid,
                            lambda: utils.przejdz(self._page, "/"), "Notatka do tankowania"
                        ),
                        pokaz_podpis=bool(wspolny_id)
                    ))
                    if wspolny_id and (w.get('dodane_przez') or w.get('zmodyfikowane_przez')):
                        tresc_karty.append(utils.znacznik_atrybucji(w.get('dodane_przez'), w.get('zmodyfikowane_przez'), w.get('data_modyfikacji')))

                    kontener = ft.Container(padding=15, border_radius=10, ink=True, content=ft.Column(tresc_karty))

                    self.karty_ref[tid] = kontener
                    self.podepnij_zdarzenia_grupowe(kontener, tid, lambda id_el=tid, zal=w.get('zalacznik'), nt=w.get('notatka'): otworz_menu_t(id_el, zal, nt), "tankowania")

                    karta_t = ft.Card(elevation=1, content=kontener)
                    tekst_szukaj = f"{w.get('data')} {w.get('stacja')} {cena_str} {dystans_val} {sp_str} {w.get('tagi')} {db.ETYKIETY_RODZAJU[rodzaj_w]} {w.get('typ_ladowania') or ''} {w.get('notatka') or ''}".lower()
                    self.wszystkie_karty_tankowania.append({"karta": karta_t, "szukaj": tekst_szukaj})
                    self.lista_kart_tankowania.controls.append(karta_t)

                self.elementy.append(self.lista_kart_tankowania)

        self.fab = self._buduj_fab_szybkich_akcji()

    def buduj_inne(self):
        wspolny_id, _ = sync.czy_udostepniony(self.state.auto_id)
        naglowek_inne = utils.tytul_sekcji(ft.Icons.RECEIPT_LONG, "Inne koszty")
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

            filtry_ui = [sort_ui, filtr_rok_ui, filtr_mc_ui, filtr_kat_ui]
            if wspolny_id:
                filtry_ui.append(
                    utils.przycisk_filtrowania_autora(self._page, self.state, "inne_autor", baza_lista, "dodane_przez")
                )

            self.elementy.append(ft.Row(filtry_ui, spacing=6, scroll=ft.ScrollMode.HIDDEN))

            def filtruj_inne(e):
                zapytanie = e.control.value.lower().strip()
                self.lista_kart_inne.controls.clear()
                for k in self.wszystkie_karty_inne:
                    if zapytanie in k["szukaj"]:
                        self.lista_kart_inne.controls.append(k["karta"])
                self.update()

            self.elementy.append(
                ft.TextField(
                    hint_text="Szukaj kosztu (opis, kategoria, kwota, data, notatka)...",
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
            if wspolny_id:
                po_filtrach = utils.filtruj_po_autorze(po_filtrach, self.state, "inne_autor", "dodane_przez")
            utils.posortuj_liste(po_filtrach, self.state, "inne", opcje_sort)

            def otworz_menu_i(iid, zalacznik=None, notatka=None):
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

                poz_notatka = utils.pozycja_menu_notatki(
                    self._page, "inne_koszty", iid, notatka,
                    lambda: utils.przejdz(self._page, "/"), "Notatka do kosztu"
                )
                pozycje.append(ft.ListTile(
                    leading=ft.Icon(poz_notatka["ikona"]),
                    title=ft.Text(poz_notatka["tekst"]),
                    on_click=lambda ev: (utils.zamknij_dno(self._page, bs), poz_notatka["akcja"]())
                ))
                pozycje.append(ft.ListTile(leading=ft.Icon(ft.Icons.EDIT), title=ft.Text("Edytuj koszt"), on_click=lambda ev: (utils.zamknij_dno(self._page, bs), utils.przejdz(self._page, f"/inne/edytuj/{iid}"))))
                pozycje.append(ft.ListTile(leading=ft.Icon(ft.Icons.CONTENT_COPY), title=ft.Text("Duplikuj"), on_click=lambda ev: (utils.zamknij_dno(self._page, bs), setattr(self.state, "duplikuj_zrodlo_koszt", iid), utils.przejdz(self._page, "/inne/nowy"))))
                pozycje.append(ft.ListTile(leading=ft.Icon(ft.Icons.DELETE, color=ft.Colors.RED), title=ft.Text("Usuń koszt", color=ft.Colors.RED), on_click=usun_koszt))

                bs = ft.BottomSheet(ft.Container(padding=20, bgcolor=ft.Colors.SURFACE, content=ft.Column(pozycje, tight=True)))
                utils.otworz_dno(self._page, bs)

            if not po_filtrach:
                self.elementy.append(ft.Row([ft.Text("Brak wyników dla tych filtrów.", color=ft.Colors.ON_SURFACE_VARIANT)], alignment=ft.MainAxisAlignment.CENTER))
            else:
                mapa_tagow = {t[1]: t[2] for t in db.pobierz_tagi(self.state.auto_id)}
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
                        utils.wizualizacja_tagow(w.get('tagi') or w.get('kategoria'), self.state.auto_id, mapa_tagow)
                    ]
                    tresc_i.append(utils.podglad_notatki(
                        self._page, w.get('notatka'), w.get('notatka_autor'), w.get('notatka_data'),
                        "Notatka do kosztu",
                        on_edytuj=lambda rid=iid: utils.szybka_notatka(
                            self._page, "inne_koszty", rid,
                            lambda: utils.przejdz(self._page, "/"), "Notatka do kosztu"
                        ),
                        pokaz_podpis=bool(wspolny_id)
                    ))
                    if wspolny_id and (w.get('dodane_przez') or w.get('zmodyfikowane_przez')):
                        tresc_i.append(utils.znacznik_atrybucji(w.get('dodane_przez'), w.get('zmodyfikowane_przez'), w.get('data_modyfikacji')))
                    kontener = ft.Container(padding=15, border_radius=10, ink=True, content=ft.Column(tresc_i))

                    self.karty_ref[iid] = kontener
                    self.podepnij_zdarzenia_grupowe(kontener, iid, lambda id_el=iid, zal=w.get('zalacznik'), nt=w.get('notatka'): otworz_menu_i(id_el, zal, nt), "inne_koszty")

                    karta_i = ft.Card(elevation=1, content=kontener)
                    tekst_szukaj = f"{w.get('data')} {w.get('nazwa')} {w.get('kategoria')} {cena_str} {w.get('notatka') or ''}".lower()
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
            # „Analiza” stoi trzecia, ale dostaje indeks 3, a nie 2: numery
            # podzakładek siedzą w zapamiętanym stanie użytkownika i przesunięcie
            # ich otworzyłoby komuś Tabele zamiast Wykresów po aktualizacji.
            self._page,
            [("Liczby", 0), ("Wykresy", 1), ("Analiza", 3), ("Tabele", 2)],
            self.state.stat_podzakladka, zmien_podzakladke
        ))

        if self.state.stat_podzakladka == 0:
            elektryczny = db.czy_pojazd_elektryczny(self.state.auto_id)
            etykiety = db.etykiety_paliwa(elektryczny)
            statystyki_energii = db.pobierz_statystyki_energii(self.state.auto_id)
            dwuzrodlowy = len(statystyki_energii) > 1

            self.elementy.extend([
                ft.Row(utils.tytul_sekcji(ft.Icons.PIE_CHART, "Podsumowanie kosztów"), spacing=8),
                kafel(ft.Icons.ATTACH_MONEY, "Całkowity koszt", f"{utils.formatuj_liczba(razem)}  {utils.symbol_waluty()}", ft.Colors.RED_700),
                ft.Row([
                    kafel(ft.Icons.LOCAL_GAS_STATION, "Na energię" if dwuzrodlowy else "Na paliwo",
                          f"{utils.formatuj_liczba(pal)}  {utils.symbol_waluty()}", ft.Colors.BLUE_700, expand=1),
                    kafel(ft.Icons.BUILD, "Na serwis", f"{utils.formatuj_liczba(serw)}  {utils.symbol_waluty()}", ft.Colors.ORANGE_700, expand=1),
                ], spacing=10),
                ft.Row([
                    kafel(ft.Icons.RECEIPT_LONG, "Inne koszty", f"{utils.formatuj_liczba(inn)}  {utils.symbol_waluty()}", ft.Colors.GREEN_700, expand=1),
                    kafel(ft.Icons.ADD_ROAD, "Koszt 1 km", f"{utils.formatuj_liczba(koszt_km)}  {utils.symbol_waluty()}/km", ft.Colors.PURPLE_700, expand=1),
                ], spacing=10),
            ])

            # Przy hybrydzie plug-in KAŻDE źródło dostaje własną sekcję. Jedna
            # uśredniona liczba nie mówiłaby nic: litrów nie da się dodać do
            # kilowatogodzin. Auto jednoźródłowe ma dokładnie jedną sekcję i
            # wygląda tak, jak dotąd.
            for stat in statystyki_energii:
                czy_prad = stat["rodzaj"] == db.ENERGIA_PRAD
                etyk = stat["etykiety"]
                tytul_sekcji = (f"Wskaźniki — {stat['etykieta'].lower()}"
                                if dwuzrodlowy else "Wskaźniki i paliwo")
                ikona_sekcji = ft.Icons.EV_STATION if czy_prad else ft.Icons.INSIGHTS

                self.elementy.append(ft.Row(utils.tytul_sekcji(ikona_sekcji, tytul_sekcji), spacing=8))
                self.elementy.append(ft.Row([
                    kafel(ft.Icons.SPEED, etyk["zuzycie"],
                          utils.formatuj_spalanie(stat["zuzycie"], elektryczny=czy_prad)
                          if stat["zuzycie"] > 0 else etyk["brak_pelnych"],
                          ft.Colors.TEAL_700, expand=1),
                    kafel(ft.Icons.WATER_DROP if not czy_prad else ft.Icons.BOLT, etyk["suma_ilosci"],
                          f"{utils.formatuj_liczba(stat['ilosc'])} {stat['jednostka']}",
                          ft.Colors.CYAN_700, expand=1),
                ], spacing=10))
                self.elementy.append(ft.Row([
                    kafel(ft.Icons.PAYMENTS, etyk["cena_jednostkowa"],
                          f"{utils.formatuj_liczba(stat['cena_jednostkowa'])} {utils.symbol_waluty()}"
                          if stat["cena_jednostkowa"] > 0 else "—",
                          ft.Colors.AMBER_800, expand=1),
                    # Koszt na km liczony osobno pokazuje wprost, ile daje
                    # ładowanie zamiast tankowania.
                    kafel(ft.Icons.ADD_ROAD, f"Koszt 1 km ({stat['etykieta'].lower()})",
                          f"{utils.formatuj_liczba(stat['koszt_km'])} {utils.symbol_waluty()}/km"
                          if stat["koszt_km"] > 0 else "—",
                          ft.Colors.PURPLE_700, expand=1),
                ], spacing=10))

                # Rozbicie AC/DC — szybkie ładowanie na trasie potrafi być
                # kilka razy droższe niż wolne w domu.
                if czy_prad and stat["ceny_ladowania"]:
                    self.elementy.append(ft.Row([
                        kafel(
                            ft.Icons.POWER if typ == "AC" else ft.Icons.FLASH_ON,
                            f"Cena/kWh — {typ}",
                            f"{utils.formatuj_liczba(dane['cena'])} {utils.symbol_waluty()}",
                            ft.Colors.LIGHT_GREEN_800 if typ == "AC" else ft.Colors.DEEP_ORANGE_700,
                            expand=1,
                        )
                        for typ, dane in sorted(stat["ceny_ladowania"].items())
                    ], spacing=10))

            udzial = db.pobierz_udzial_energii(self.state.auto_id)
            if udzial:
                self.elementy.append(ft.Row(utils.tytul_sekcji(ft.Icons.PIE_CHART_OUTLINE, "Wydatek na energię"), spacing=8))
                self.elementy.append(ft.Row([
                    kafel(ft.Icons.EV_STATION, "Wydatek na prąd",
                          f"{utils.formatuj_liczba(udzial['procent_prad'], 0)}%",
                          ft.Colors.LIGHT_GREEN_800, expand=1),
                    kafel(ft.Icons.LOCAL_GAS_STATION, "Wydatek na paliwo",
                          f"{utils.formatuj_liczba(udzial['procent_paliwo'], 0)}%",
                          ft.Colors.BLUE_700, expand=1),
                ], spacing=10))

            if dwuzrodlowy:
                # Bez tej noty łatwo odczytać „1,9 kWh/100km” jako zużycie w trybie
                # elektrycznym, a to zużycie rozłożone na CAŁY przebieg.
                self.elementy.append(ft.Container(
                    padding=ft.Padding(12, 10, 12, 10),
                    border_radius=utils.RADIUS["sm"],
                    bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.PRIMARY),
                    content=ft.Row([
                        ft.Icon(ft.Icons.INFO_OUTLINE, size=16, color=ft.Colors.PRIMARY),
                        ft.Text(
                            "Przy hybrydzie plug-in oba zużycia liczą się po CAŁYM przebiegu "
                            "(tak samo podaje je WLTP) — z samego licznika nie da się wydzielić, "
                            "ile kilometrów przejechałeś na prądzie, a ile na paliwie. "
                            "Koszty na km można za to dodać: razem dają pełny koszt energii.",
                            size=11, color=ft.Colors.ON_SURFACE_VARIANT, expand=True,
                        ),
                    ], spacing=8),
                ))

            zasieg = db.pobierz_zasieg_ev(self.state.auto_id)
            if zasieg and zasieg["szacowany"]:
                podpis = f"{utils.formatuj_liczba(zasieg['szacowany'], 0)} km"
                if zasieg["procent_deklarowanego"]:
                    podpis += f" ({utils.formatuj_liczba(zasieg['procent_deklarowanego'], 0)}% katalogowego)"
                self.elementy.append(ft.Row([
                    kafel(ft.Icons.BATTERY_CHARGING_FULL, "Realny zasięg na prądzie", podpis,
                          ft.Colors.GREEN_700),
                ], spacing=10))

            self.elementy.extend([
                ft.Row(utils.tytul_sekcji(ft.Icons.INSIGHTS, "Przebieg"), spacing=8),
                ft.Row([
                    kafel(ft.Icons.ROUTE, "Zanotowany dystans", f"{utils.formatuj_liczba(dystans, 0)} km", ft.Colors.INDIGO_700, expand=1),
                    kafel(ft.Icons.TIMELAPSE, "Średnio dziennie", sredni_dz_str, ft.Colors.BLUE_GREY_700, expand=1),
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
                            ft.Icon(ikona, size=15, color=kolor),
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

            karta_struktury = ft.Container(
                border_radius=utils.RADIUS["lg"], padding=utils.SPACING["lg"],
                **utils.powierzchnia_karty(self._page, "md"),
                content=ft.Column([
                    segment_procentowy(utils.IKONY_KATEGORII_KOSZTOW["paliwo"], "Paliwo", pal, proc_pal, ft.Colors.BLUE_700),
                    segment_procentowy(utils.IKONY_KATEGORII_KOSZTOW["serwis"], "Serwis", serw, proc_ser, ft.Colors.ORANGE_700),
                    segment_procentowy(utils.IKONY_KATEGORII_KOSZTOW["inne"], "Inne", inn, proc_inn, ft.Colors.GREEN_700),
                ], spacing=12)
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

                def chip_trendu(ikona, tekst, kolor, tlo=True):
                    return ft.Container(
                        padding=ft.Padding(10, 5, 10, 5), border_radius=20,
                        bgcolor=ft.Colors.with_opacity(0.15, kolor) if tlo else None,
                        content=ft.Row([
                            ft.Icon(ikona, size=14, color=kolor),
                            ft.Text(tekst, size=12, weight="bold", color=kolor),
                        ], spacing=5, tight=True),
                    )

                if zmiana_proc > 5:
                    znacznik_trendu = chip_trendu(
                        ft.Icons.TRENDING_UP,
                        f"Rośnie o {utils.formatuj_liczba(zmiana_proc, 0)}%", ft.Colors.RED_700)
                elif zmiana_proc < -5:
                    znacznik_trendu = chip_trendu(
                        ft.Icons.TRENDING_DOWN,
                        f"Spada o {utils.formatuj_liczba(abs(zmiana_proc), 0)}%", ft.Colors.GREEN_700)
                else:
                    znacznik_trendu = chip_trendu(
                        ft.Icons.TRENDING_FLAT, "Stabilne", ft.Colors.ON_SURFACE_VARIANT, tlo=False)

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

        elif self.state.stat_podzakladka == 3:
            # ================= ANALIZA I PROGNOZY =================
            # Zakładka odpowiada na pytania, a nie wypisuje liczby: co się zmienia,
            # ile to będzie kosztować i czy mieszczę się w tym, co sobie założyłem.
            obserwacje = db.obserwacje_analityczne(self.state.auto_id)
            trend = db.analizuj_trend_spalania(self.state.auto_id)
            bak = db.pobierz_zasieg_na_baku(self.state.auto_id)
            prognoza = db.prognoza_kosztow(self.state.auto_id)
            stany_budzetow = db.stan_budzetow(self.state.auto_id)

            self.elementy.append(ft.Row(utils.tytul_sekcji(ft.Icons.INSIGHTS, "Co widać w danych"), spacing=8))
            if obserwacje:
                for o in obserwacje:
                    self.elementy.append(utils.karta_obserwacji(self._page, o))
            else:
                self.elementy.append(ft.Container(
                    padding=utils.SPACING["md"], border_radius=utils.RADIUS["lg"],
                    bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.PRIMARY),
                    content=ft.Row([
                        ft.Icon(ft.Icons.INFO_OUTLINE, size=16, color=ft.Colors.PRIMARY),
                        ft.Text(
                            "Na razie nic nie odstaje od normy. Obserwacje pojawiają się same, "
                            "gdy zużycie, koszty albo budżet zaczynają odbiegać od Twojej średniej.",
                            size=utils.FS["body"], color=ft.Colors.ON_SURFACE_VARIANT, expand=True,
                        ),
                    ], spacing=8),
                ))

            # --- Trend zużycia ---
            if trend:
                czy_prad_tr = trend["rodzaj"] == db.ENERGIA_PRAD
                kolor_tr = (ft.Colors.RED_700 if trend["kierunek"] == "wzrost"
                            else ft.Colors.GREEN_700 if trend["kierunek"] == "spadek"
                            else ft.Colors.BLUE_GREY_700)
                opis_kierunku = {
                    "wzrost": "Zużycie rośnie",
                    "spadek": "Zużycie spada",
                    "stabilnie": "Zużycie bez zmian",
                }[trend["kierunek"]]
                rocznie = db.koszt_trendu_rocznie(self.state.auto_id, trend)

                wiersze_trendu = [
                    ft.Row([
                        ft.Column([
                            ft.Text("Ostatnie odcinki", size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT),
                            ft.Text(utils.formatuj_spalanie(trend["srednia_ostatnia"], elektryczny=czy_prad_tr),
                                    weight="bold", size=utils.FS["title"], color=kolor_tr),
                            ft.Text(f"{trend['odcinkow_ostatnio']} pomiary", size=utils.FS["caption"],
                                    color=ft.Colors.ON_SURFACE_VARIANT),
                        ], spacing=2, expand=True),
                        ft.Icon(ft.Icons.ARROW_FORWARD, size=18, color=ft.Colors.ON_SURFACE_VARIANT),
                        ft.Column([
                            ft.Text("Wcześniej", size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT),
                            ft.Text(utils.formatuj_spalanie(trend["srednia_wczesniej"], elektryczny=czy_prad_tr),
                                    weight="bold", size=utils.FS["title"]),
                            ft.Text(f"{trend['odcinkow_wczesniej']} pomiarów", size=utils.FS["caption"],
                                    color=ft.Colors.ON_SURFACE_VARIANT),
                        ], spacing=2, expand=True, horizontal_alignment=ft.CrossAxisAlignment.END),
                    ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
                    ft.Row([
                        ft.Container(
                            padding=ft.Padding(10, 4, 10, 4), border_radius=utils.RADIUS["pill"],
                            bgcolor=ft.Colors.with_opacity(0.15, kolor_tr),
                            content=ft.Row([
                                ft.Icon(ft.Icons.TRENDING_UP if trend["kierunek"] == "wzrost"
                                        else ft.Icons.TRENDING_DOWN if trend["kierunek"] == "spadek"
                                        else ft.Icons.TRENDING_FLAT, size=14, color=kolor_tr),
                                ft.Text(f"{opis_kierunku} o {utils.formatuj_liczba(abs(trend['zmiana_proc']), 0)}%",
                                        size=utils.FS["label"], weight="bold", color=kolor_tr),
                            ], spacing=5, tight=True),
                        ),
                    ]),
                ]
                if rocznie and abs(rocznie) >= 20:
                    wiersze_trendu.append(ft.Text(
                        (f"Przy dotychczasowym przebiegu rocznym to około "
                         f"{utils.formatuj_liczba(abs(rocznie))} {utils.symbol_waluty()} "
                         f"{'więcej' if rocznie > 0 else 'mniej'} w skali roku."),
                        size=utils.FS["body"], color=ft.Colors.ON_SURFACE_VARIANT,
                    ))
                wiersze_trendu.append(ft.Text(
                    f"Porównanie {trend['odcinkow_ostatnio']} ostatnich odcinków „do pełna” "
                    f"ze średnią {trend['odcinkow_wczesniej']} wcześniejszych"
                    + (f" (okno {trend['dni_okna']} dni)." if trend["dni_okna"] else "."),
                    size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
                ))
                self.elementy.append(utils.karta_analizy(
                    self._page, "Trend zużycia", ft.Icons.SPEED, wiersze_trendu, kolor_tr))
            else:
                self.elementy.append(utils.karta_analizy(
                    self._page, "Trend zużycia", ft.Icons.SPEED,
                    [ft.Text("Za mało odcinków, żeby mówić o trendzie — potrzeba co najmniej "
                             "pięciu tankowań „do pełna”. Do tego czasu wolę nie zgadywać.",
                             size=utils.FS["body"], color=ft.Colors.ON_SURFACE_VARIANT)],
                ))

            # --- Zasięg na baku ---
            if bak:
                self.elementy.append(utils.karta_analizy(
                    self._page, "Zasięg na baku", ft.Icons.LOCAL_GAS_STATION,
                    [utils.wskaznik_baku(self._page, bak)], ft.Colors.TEAL_700))
            elif db.ENERGIA_PALIWO in db.rodzaje_energii_pojazdu(self.state.auto_id):
                self.elementy.append(utils.karta_analizy(
                    self._page, "Zasięg na baku", ft.Icons.LOCAL_GAS_STATION,
                    [
                        ft.Text("Podaj pojemność baku w danych pojazdu, a policzę zasięg "
                                "z Twojego rzeczywistego zużycia — łącznie z tym, ile zostało "
                                "od ostatniego tankowania do pełna.",
                                size=utils.FS["body"], color=ft.Colors.ON_SURFACE_VARIANT),
                        ft.FilledTonalButton(
                            "Uzupełnij pojemność baku", icon=ft.Icons.EDIT,
                            on_click=lambda e: utils.przejdz(self._page, f"/auto/edytuj/{self.state.auto_id}"),
                        ),
                    ], ft.Colors.TEAL_700))

            # --- Prognoza ---
            if prognoza:
                wiersze_prognozy = [
                    ft.Row([
                        kafel(ft.Icons.CALENDAR_MONTH, "Średnio na miesiąc",
                              f"{utils.formatuj_liczba(prognoza['srednia_miesieczna'])} {utils.symbol_waluty()}",
                              ft.Colors.BLUE_700, expand=1),
                        kafel(ft.Icons.HOURGLASS_BOTTOM, "Zostało do końca roku",
                              f"{utils.formatuj_liczba(prognoza['prognoza_do_konca'])} {utils.symbol_waluty()}",
                              ft.Colors.ORANGE_700, expand=1),
                    ], spacing=10),
                    kafel(ft.Icons.QUERY_STATS, f"Cały {prognoza['rok']} — prognoza",
                          f"{utils.formatuj_liczba(prognoza['prognoza_calego_roku'])} {utils.symbol_waluty()}",
                          ft.Colors.DEEP_PURPLE_700),
                ]
                if prognoza.get("zmiana_rdr") is not None:
                    w_gore = prognoza["zmiana_rdr"] > 0
                    wiersze_prognozy.append(ft.Row([
                        ft.Icon(ft.Icons.TRENDING_UP if w_gore else ft.Icons.TRENDING_DOWN, size=16,
                                color=ft.Colors.RED_700 if w_gore else ft.Colors.GREEN_700),
                        ft.Text(
                            f"{'Drożej' if w_gore else 'Taniej'} od {prognoza['rok'] - 1} roku o "
                            f"{utils.formatuj_liczba(abs(prognoza['zmiana_rdr']), 0)}% "
                            f"({utils.formatuj_liczba(prognoza['poprzedni_rok'])} {utils.symbol_waluty()})",
                            size=utils.FS["body"], color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                    ], spacing=6))
                wiersze_prognozy.append(ft.Text(
                    f"Ekstrapolacja ze średniej z {prognoza['miesiecy_bazowych']} pełnych miesięcy. "
                    f"Bieżący miesiąc nie wchodzi do podstawy, żeby jego niepełność nie zaniżała wyniku. "
                    f"Do końca roku zostało {prognoza['dni_pozostalo']} dni.",
                    size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
                ))
                wiersze_prognozy.append(ft.FilledTonalButton(
                    "Zobacz rok w pigułce", icon=ft.Icons.AUTO_AWESOME,
                    on_click=lambda e: utils.przejdz(self._page, "/rok"),
                ))
                self.elementy.append(utils.karta_analizy(
                    self._page, "Prognoza kosztów", ft.Icons.QUERY_STATS,
                    wiersze_prognozy, ft.Colors.DEEP_PURPLE_700))

            # --- Budżety ---
            zawartosc_budzetu = []
            if stany_budzetow:
                for stan in stany_budzetow:
                    zawartosc_budzetu.append(utils.pasek_budzetu(self._page, stan))
                    zawartosc_budzetu.append(ft.Divider(height=8, color=ft.Colors.TRANSPARENT))
                zawartosc_budzetu.append(ft.FilledTonalButton(
                    "Zmień limity", icon=ft.Icons.TUNE,
                    on_click=lambda e: utils.przejdz(self._page, "/budzet"),
                ))
            else:
                zawartosc_budzetu = [
                    ft.Text("Ustaw limit na paliwo, serwis albo wszystko razem, a kokpit "
                            "ostrzeże Cię, zanim go przekroczysz — nie dopiero po fakcie.",
                            size=utils.FS["body"], color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.FilledTonalButton(
                        "Ustaw budżet", icon=ft.Icons.SAVINGS,
                        on_click=lambda e: utils.przejdz(self._page, "/budzet"),
                    ),
                ]
            self.elementy.append(utils.karta_analizy(
                self._page, "Budżety", ft.Icons.SAVINGS, zawartosc_budzetu, ft.Colors.GREEN_700))

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
                pary = [
                    (utils.IKONY_KATEGORII_KOSZTOW["paliwo"], utils.formatuj_liczba(pal_w, 0)) if pal_w > 0 else None,
                    (utils.IKONY_KATEGORII_KOSZTOW["serwis"], utils.formatuj_liczba(serw_w, 0)) if serw_w > 0 else None,
                    (utils.IKONY_KATEGORII_KOSZTOW["inne"], utils.formatuj_liczba(inn_w, 0)) if inn_w > 0 else None,
                ]
                opis = utils.chipy_kwot(pary) or ft.Text(
                    "Brak wydatków", size=13, color=ft.Colors.ON_SURFACE_VARIANT)

                tresc = [
                    ft.Row([
                        ft.Text(etykieta, weight="bold", size=16, expand=True),
                        ft.Text(f"{utils.formatuj_liczba(razem_w)}  {utils.symbol_waluty()}", weight="bold", size=16, color=ft.Colors.RED_700)
                    ]),
                    opis,
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