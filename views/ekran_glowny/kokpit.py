"""Kokpit: kafelki wybrane przez użytkownika, karuzela/układanie i siatka skrótów."""

import calendar
import db
import flet as ft
import sync
import utils
from datetime import datetime
from state import MIESIACE_NAZWY


class MiksinKokpitu:
    """Kokpit: kafelki wybrane przez użytkownika, karuzela/układanie i siatka skrótów."""

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

        def idz_do_kosztow(podzakladka=0):
            """Numer zakładki zmienił się przy przebudowie nawigacji — kafelki
            kokpitu wołają teraz ekran po nazwie z rejestru, więc następna zmiana
            układu nie zostawi tu martwego odnośnika."""
            def handler(e):
                utils.otworz_ekran(self._page, self.state,
                                   "inne" if podzakladka else "paliwo", self.akcje_nawigacji)
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
                    ft.Text(t_tekst, size=utils.FS["caption"], color=t_kolor, no_wrap=True, expand=True),
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
                        ft.Text(p["opis"], size=utils.FS["caption"], color=kolor_p, no_wrap=True, expand=True),
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
                            tooltip=f"{MIESIACE_NAZWY[mies - 1]} {rok}: {utils.formatuj_liczba(suma)} {utils.symbol_waluty()}",
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
                wartosci_serii, idz_do_kosztow(0),
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
            pozycję z najwyższą wagą; pełna lista jest w Analiza → Obserwacje."""
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

        def widget_opony():
            """Co stoi na aucie i kiedy zmiana. Dotąd tę informację trzymał
            wyłącznie ekran Magazynu, więc przez pół roku nikt do niej nie
            zaglądał — a to jedyna rzecz w aucie, która zmienia się w kalendarzu
            i której zaniedbanie widać od razu na hamowaniu."""
            def idz_do_opon(e):
                # Magazyn ma dwie podzakładki — kafelek ma otwierać TĘ z oponami,
                # a nie tę, którą użytkownik oglądał ostatnio.
                self.state.magazyn_zakladka = 0
                utils.przejdz(self._page, "/magazyn")

            stan = db.pobierz_stan_opon(self.state.auto_id)
            if not stan:
                return kafel_wartosci(
                    ft.Icons.TIRE_REPAIR, ft.Colors.BLUE_GREY_700, "Opony",
                    "Brak zestawów", idz_do_opon,
                )

            sezon = stan["sezon"]
            kolor_sezonu = utils.KOLORY_SEZONU_OPON.get(sezon or "", ft.Colors.BLUE_GREY_700)
            ikona_sezonu = utils.IKONY_SEZONU_OPON.get(sezon or "", ft.Icons.TIRE_REPAIR)

            # Termin bierzemy z przypomnienia typu „opony”, jeśli takie istnieje —
            # to ono jest w tej aplikacji źródłem prawdy o dacie zmiany.
            terminy = [w for w in db.pobierz_wydatki_cykliczne(self.state.auto_id)
                       if w[6] == db.TYP_CYKLICZNY_OPONY]
            stopka = None
            if terminy:
                _, tekst_terminu = utils.kolor_i_tekst_terminu(terminy[0][4])
                stopka = f"Zmiana: {tekst_terminu or terminy[0][4]}"
            elif stan["docelowy_sezon"]:
                stopka = f"Następne: {stan['docelowy_sezon'].lower()}"

            bieznik = stan["bieznik"]
            if bieznik is not None:
                # 1,6 mm to minimum prawne, 3 mm — próg, przy którym opona
                # przestaje sensownie odprowadzać wodę.
                kolor_bieznika = (ft.Colors.RED_700 if bieznik < 1.6
                                  else ft.Colors.ORANGE_700 if bieznik < 3 else ft.Colors.GREEN_700)
                wiersz_bieznika = ft.Row([
                    ft.Icon(ft.Icons.STRAIGHTEN, size=13, color=kolor_bieznika),
                    ft.Text(f"bieżnik {utils.formatuj_liczba(bieznik, 1)} mm", size=utils.FS["caption"],
                            color=kolor_bieznika, no_wrap=True, expand=True),
                ], spacing=4)
            else:
                wiersz_bieznika = ft.Text("bieżnik niezmierzony", size=utils.FS["caption"],
                                          color=ft.Colors.ON_SURFACE_VARIANT, no_wrap=True)

            tresc = [
                ft.Row([
                    ft.Icon(ft.Icons.TIRE_REPAIR, size=15, color=kolor_sezonu),
                    ft.Text("Opony", size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                ], spacing=6),
                ft.Row([
                    ft.Icon(ikona_sezonu, size=17, color=kolor_sezonu),
                    ft.Text(sezon or "Nic nie zamontowane", size=utils.FS["title"], weight="bold",
                            no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS, expand=True),
                ], spacing=6),
                wiersz_bieznika,
            ]
            if stopka:
                tresc.append(ft.Text(stopka, size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
                                     no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS))

            return ft.Container(
                width=SZER_KAFLA + 40, padding=15, border_radius=utils.RADIUS["lg"],
                bgcolor=utils.tlo_karty(self._page, poziom=1),
                ink=True, on_click=idz_do_opon,
                tooltip="Zamontowany zestaw i najbliższa sezonowa zmiana",
                content=ft.Column(tresc, spacing=4),
            )

        def widget_checklist():
            """Postęp listy przedwyjazdowej. Kafelek ma sens dokładnie wtedy,
            kiedy lista jest ZACZĘTA, ale nie skończona — dlatego podsumowanie
            wybiera właśnie taką (patrz db.podsumowanie_checklist)."""
            stan = db.podsumowanie_checklist(self.state.auto_id)
            if not stan:
                return kafel_wartosci(
                    ft.Icons.FACT_CHECK, ft.Colors.BLUE_GREY_700, "Checklista",
                    "Brak listy", lambda e: utils.przejdz(self._page, "/do-zrobienia"),
                )

            kolor = ft.Colors.GREEN_700 if stan["gotowa"] else ft.Colors.PRIMARY
            stopka = ("wszystko sprawdzone" if stan["gotowa"]
                      else f"zostało {stan['razem'] - stan['zrobione']} do sprawdzenia")

            def otworz(e):
                self.state.do_zrobienia_podzakladka = 1
                utils.przejdz(self._page, "/do-zrobienia")

            return ft.Container(
                width=SZER_KAFLA + 40, padding=15, border_radius=utils.RADIUS["lg"],
                bgcolor=utils.tlo_karty(self._page, poziom=1),
                ink=True, on_click=otworz,
                tooltip=stan["nazwa"],
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.FACT_CHECK, size=15, color=kolor),
                        ft.Text("Przed trasą", size=utils.FS["caption"],
                                color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                    ], spacing=6),
                    ft.Text(f"{stan['zrobione']} / {stan['razem']}", size=utils.FS["title"], weight="bold"),
                    ft.ProgressBar(
                        value=(stan["zrobione"] / stan["razem"]) if stan["razem"] else 0,
                        color=kolor, bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
                        height=6, border_radius=3,
                    ),
                    ft.Text(stopka, size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
                            no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                ], spacing=6),
            )

        def widget_oplaty_drogowe():
            """Winiety, przejazdy i mandaty od początku roku. Osobno od reszty
            „innych kosztów”, bo ta pozycja rośnie z KILOMETRAMI, a nie z wiekiem
            auta — i tylko wtedy da się zauważyć, że tanie paliwo na trasie
            zjadła bramka."""
            poczatek_roku = dzisiaj.replace(month=1, day=1).date()
            stan = db.suma_kategorii_innych(
                self.state.auto_id, db.KATEGORIA_INNE_DROGOWE, poczatek_roku, dzisiaj.date()
            )
            wartosc = f"{utils.formatuj_liczba(stan['suma'], 0)} {utils.symbol_waluty()}"
            stopka = (f"{stan['liczba']} wpisów w {dzisiaj.year}" if stan["liczba"]
                      else f"brak wpisów w {dzisiaj.year}")
            return ft.Container(
                width=SZER_KAFLA + 20, padding=15, border_radius=utils.RADIUS["lg"],
                bgcolor=utils.tlo_karty(self._page, poziom=1),
                ink=True, on_click=idz_do_kosztow(1),
                tooltip="Suma kategorii „Mandaty i opłaty drogowe” od początku roku",
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.TOLL, size=15, color=ft.Colors.DEEP_ORANGE_700),
                        ft.Text("Opłaty drogowe", size=utils.FS["caption"],
                                color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                    ], spacing=6),
                    ft.Text(wartosc, size=utils.FS["title"], weight="bold",
                            no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(stopka, size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
                            no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                ], spacing=4),
            )

        def widget_do_zrobienia():
            stan = db.podsumowanie_do_zrobienia(self.state.auto_id)
            if not stan or not stan["otwarte"]:
                return kafel_wartosci(
                    ft.Icons.CHECKLIST_RTL, ft.Colors.GREEN_700, "Do zrobienia",
                    "Nic nie czeka", lambda e: utils.przejdz(self._page, "/do-zrobienia"),
                )

            kolor = ft.Colors.RED_700 if stan["po_terminie"] else ft.Colors.PRIMARY
            if stan["najblizsze"]:
                dni = stan["najblizsze"]["dni"]
                if dni < 0:
                    opis = f"{stan['najblizsze']['tytul']} — {abs(dni)} dni po terminie"
                elif dni == 0:
                    opis = f"{stan['najblizsze']['tytul']} — dziś"
                else:
                    opis = f"{stan['najblizsze']['tytul']} — za {dni} dni"
            else:
                opis = "bez terminów"

            return ft.Container(
                width=SZER_KAFLA + 60, padding=15, border_radius=utils.RADIUS["lg"],
                bgcolor=utils.tlo_karty(self._page, poziom=1),
                ink=True, on_click=lambda e: utils.przejdz(self._page, "/do-zrobienia"),
                tooltip="Otwarte pozycje z listy Do zrobienia",
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.CHECKLIST_RTL, size=15, color=kolor),
                        ft.Text("Do zrobienia", size=utils.FS["caption"],
                                color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                    ], spacing=6),
                    ft.Row([
                        ft.Text(str(stan["otwarte"]), size=utils.FS["title"], weight="bold"),
                        ft.Text(f"• {stan['po_terminie']} po terminie" if stan["po_terminie"] else "",
                                size=utils.FS["caption"], color=ft.Colors.RED_700, no_wrap=True),
                    ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.END),
                    ft.Text(opis, size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
                            no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                ], spacing=4),
            )

        def widget_magazyn():
            def idz_do_czesci(e):
                self.state.magazyn_zakladka = 1
                utils.przejdz(self._page, "/magazyn")

            stan = db.pobierz_stan_magazynu(self.state.auto_id)
            if not stan["razem"]:
                return kafel_wartosci(
                    ft.Icons.INVENTORY_2, ft.Colors.BLUE_GREY_700, "Magazyn",
                    "Pusty", idz_do_czesci,
                )
            niski = stan["niski"]
            kolor = ft.Colors.ORANGE_700 if niski else ft.Colors.GREEN_700
            stopka = (", ".join(stan["nazwy_niskich"][:2]) if niski
                      else f"{stan['razem']} pozycji na stanie")
            return ft.Container(
                width=SZER_KAFLA + 40, padding=15, border_radius=utils.RADIUS["lg"],
                bgcolor=utils.tlo_karty(self._page, poziom=1),
                ink=True, on_click=idz_do_czesci,
                tooltip="Pozycje magazynu poniżej własnego progu ostrzegawczego",
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.INVENTORY_2, size=15, color=kolor),
                        ft.Text("Magazyn", size=utils.FS["caption"],
                                color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                    ], spacing=6),
                    ft.Text(f"{niski} do uzupełnienia" if niski else "Stan w porządku",
                            size=utils.FS["title"], weight="bold",
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
            "opony": widget_opony,
            "checklist": widget_checklist,
            "oplaty_drogowe": widget_oplaty_drogowe,
            "do_zrobienia": widget_do_zrobienia,
            "magazyn": widget_magazyn,
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

        # Suwak ZAWSZE widoczny i z własnym marginesem pod kafelkami: przy
        # ukrytym pasku nic nie mówiło, że karuzela ma ciąg dalszy, a myszą nie
        # dało się jej przeciągnąć (Flutter nie przewija zawartości kursorem).
        return utils.pasek_przewijany(kafelki + [przycisk_ukladania], spacing=10)

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

    # ================= KOKPIT — ZAKŁADKA STARTOWA =================
    def buduj_kokpit_ekran(self):
        """Ekran startowy dostał wreszcie własną zakładkę. Wcześniej widżety
        kokpitu doklejały się nad listę podzespołów w Serwisie — przez co
        pierwsze, co się widziało po uruchomieniu aplikacji, było pomieszaniem
        „jak jest” z „co zrobić”, a żeby dojść do listy części trzeba było
        przewinąć cały dashboard.

        Kokpit odpowiada tylko na jedno pytanie: co się teraz dzieje z autem.
        Nad nim kafel pojazdu z terminami, pod nim skróty do ekranów, które
        użytkownik sam sobie wybrał."""
        naglowek = utils.tytul_sekcji(ft.Icons.SPACE_DASHBOARD, "Kokpit")
        wspolny_id, _ = sync.czy_udostepniony(self.state.auto_id)
        if wspolny_id:
            naglowek.append(utils.przycisk_synchronizacji(self._page, self._synchronizuj_teraz))
        naglowek.append(
            ft.IconButton(
                icon=ft.Icons.TUNE, icon_size=18, tooltip="Które kafelki pokazywać",
                on_click=lambda e: utils.przejdz(self._page, "/ustawienia"),
                width=36, height=36, style=ft.ButtonStyle(padding=0),
            )
        )
        self.elementy.append(ft.Row(naglowek, vertical_alignment=ft.CrossAxisAlignment.CENTER))

        self.elementy.append(self._buduj_kokpit())
        if not db.pobierz_widgety_kokpitu(self.state.auto_id):
            # Pusty kokpit bez słowa wyjaśnienia wyglądałby jak zepsuty ekran,
            # a nie jak ekran czekający na wybór kafelków.
            self.elementy.append(ft.Container(
                padding=utils.SPACING["md"], border_radius=utils.RADIUS["lg"],
                bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.PRIMARY),
                content=ft.Row([
                    ft.Icon(ft.Icons.WIDGETS, size=20, color=ft.Colors.PRIMARY),
                    ft.Text(
                        "Kokpit nie ma włączonych kafelków. Wybierz je w Ustawieniach → "
                        "Kokpit ekranu głównego, a znajdą się tutaj.",
                        size=utils.FS["body"], color=ft.Colors.ON_SURFACE_VARIANT, expand=True,
                    ),
                ], spacing=utils.SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ))

        self.elementy.append(self._buduj_skroty())
        # Kokpit jest ekranem startowym, a najczęstsza czynność w aplikacji to
        # dopisanie tankowania — przycisk szybkiego dodawania musi tu być.
        self.fab = self._buduj_fab_szybkich_akcji()

    def _buduj_skroty(self):
        """Siatka skrótów. Sedno problemu, od którego zaczęła się przebudowa
        nawigacji, brzmiało: „Rok w pigułce da się otworzyć z paru miejsc, ale
        nigdy nie pamiętam, z których”. Odpowiedź jest taka, że ekran używany raz
        na jakiś czas musi mieć STAŁE miejsce wybrane przez użytkownika — a nie
        być rozsiany po menu kontekstowych."""
        przypiete = [
            utils.EKRANY_WG_ID[eid] for eid in db.pobierz_przypiete_ekrany()
            if eid in utils.EKRANY_WG_ID
        ]

        naglowek = ft.Row([
            ft.Icon(ft.Icons.BOOKMARK, size=17, color=ft.Colors.PRIMARY),
            ft.Text("Skróty", size=utils.FS["label"], weight="bold",
                    color=ft.Colors.PRIMARY, expand=True),
            ft.TextButton(
                "Wybierz", icon=ft.Icons.DASHBOARD_CUSTOMIZE,
                on_click=lambda e: utils.pokaz_edytor_skrotow(
                    self._page, self.state, po_zapisie=lambda: utils.przejdz(self._page, "/")
                ),
            ),
        ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        if not przypiete:
            tresc = ft.Container(
                padding=utils.SPACING["md"], border_radius=utils.RADIUS["lg"],
                bgcolor=utils.tlo_karty(self._page, poziom=1),
                content=ft.Text(
                    "Brak skrótów. Dotknij „Wybierz” i przypnij ekrany, do których "
                    "wracasz najczęściej — pełna lista jest zawsze w menu bocznym.",
                    size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
                ),
            )
        else:
            # Siatka, a nie karuzela: skróty mają być widoczne WSZYSTKIE naraz,
            # inaczej znowu trzeba by szukać — tym razem przewijaniem w bok.
            #
            # Szerokość kafelka liczy Flet, a nie my. Poprzednia wersja dzieliła
            # zgadniętą szerokość ekranu przez liczbę kolumn — a przy PIERWSZYM
            # uruchomieniu aplikacji page.width nie jest jeszcze znane i kafelki
            # wychodziły tak szerokie, że mieścił się jeden w wierszu. Dopiero
            # zmiana rozmiaru okna przebudowywała widok poprawnie.
            #
            # ResponsiveRow rozdziela 12 kolumn wg RZECZYWISTEJ szerokości:
            # col=4 → trzy kafelki w rzędzie na telefonie, cztery na tablecie,
            # sześć na szerokim ekranie. Nic tu nie zależy od pomiaru w Pythonie.
            tresc = ft.ResponsiveRow(
                [
                    utils.kafel_skrotu(self._page, self.state, ekran, self.akcje_nawigacji,
                                       self.liczniki_nawigacji,
                                       col={"xs": 4, "sm": 3, "md": 2})
                    for ekran in przypiete
                ],
                spacing=10, run_spacing=10,
            )

        return ft.Column([naglowek, tresc], spacing=8)
