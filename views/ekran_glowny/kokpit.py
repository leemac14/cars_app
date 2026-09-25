"""Kokpit: kafelki wybrane przez użytkownika w siatce, tryb układania i skróty."""

import calendar
import db
import flet as ft
import sync
import utils
from datetime import datetime
from state import MIESIACE_NAZWY


# Ile miejsca potrzebuje kafelek kokpitu. Kiedyś była to jego NARYSOWANA
# szerokość w karuzeli; dziś budowniczy nadal deklarują nią swoje potrzeby,
# a siatka zamienia deklarację na rozmiar komórki (patrz _kokpit_siatka).
SZER_KAFLA = 160
# Powyżej tego progu kafelek dostaje w siatce dwie komórki zamiast jednej.
PROG_KAFLA_2X1 = SZER_KAFLA + 40

# Wysokość „iskry” (mini-wykresu) na kafelku. Jedna dla wszystkich, bo kafelki
# z iskrą stoją w siatce obok siebie — różnica dwóch pikseli robiła z równego
# rzędu schodki.
WYS_ISKRY = 30

# Dwa rozmiary kafelka w dwunastokolumnowej siatce ResponsiveRow: 1×1 i 2×1.
# Telefon dzieli wiersz na dwie komórki, tablet na trzy, szeroki ekran na cztery.
KOL_KAFLA_1X1 = {"xs": 6, "sm": 4, "md": 3}
KOL_KAFLA_2X1 = {"xs": 12, "sm": 8, "md": 6}


class MiksinKokpitu:
    """Kokpit: kafelki wybrane przez użytkownika w siatce, tryb układania i skróty."""

    # ================= KOKPIT / DASHBOARD STARTOWY (siatka kafelków) =================
    def _buduj_kokpit(self):
        """Mini-dashboard nad listą podzespołów, złożony z widżetów wybranych przez
        użytkownika w Ustawieniach (patrz db.KOKPIT_WIDGETY / db.pobierz_widgety_kokpitu).
        Renderowany jako siatka (ft.ResponsiveRow) z kafelkami w dwóch rozmiarach
        — 1×1 i 2×1 — zamiast poziomej karuzeli, która chowała część kafelków za
        krawędzią ekranu (patrz _kokpit_siatka).

        Układ jest WŁASNOŚCIĄ POJAZDU: auto służbowe może mieć inne kafelki niż
        prywatne. Pojazd bez własnego układu dziedziczy wspólny (patrz
        db.pobierz_widgety_kokpitu)."""
        # Odliczanie liczb przy wejściu na kokpit. Scenę dobiera i uruchamia
        # MainView._nowa_scena_zakladki — tu tylko z niej korzystamy. JEDNA na całą
        # przebudowę, żeby wszystkie kafelki ruszyły w tej samej chwili i stanęły
        # razem; osobny timer na kafelek dałby osiemnaście animacji
        # rozjeżdżających się w czasie. Scena wyłączona oddaje kontrolki od razu
        # w stanie docelowym, więc poniżej nie ma ani jednego „jeśli animacje
        # włączone”.
        scena = self._scena_zakladki or utils.ScenaWejscia(wlaczona=False)

        wlaczone = db.pobierz_widgety_kokpitu(self.state.auto_id)
        if not wlaczone:
            return ft.Container()

        dzisiaj = datetime.now()
        # Rola przy tym pojeździe — czytana RAZ na przebudowę, bo pyta o nią
        # sześć kafelków akcji naraz.
        tylko_podglad = db.czy_tylko_podglad(self.state.auto_id)

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
        # Krzywa narastająca to przejście po WSZYSTKICH wpisach kosztowych auta,
        # więc liczymy ją wyłącznie, gdy kafelek naprawdę stoi na kokpicie.
        dane_skumulowane = db.koszt_skumulowany(
            self.state.auto_id, z_cena_zakupu=db.czy_skumulowany_z_cena_zakupu()
        ) if "skumulowany" in wlaczone else {}
        dane_1000km = db.koszt_na_1000km(
            self.state.auto_id, db.pobierz_okno_kroczace(self.state.auto_id)
        ) if "koszt_1000km" in wlaczone else {}

        def idz_do_statystyk(podzakladka=0):
            def handler(e):
                self.state.stat_podzakladka = podzakladka
                # Analiza jest zakładką TEGO ekranu, więc przełączamy ją u siebie
                # — z takim samym przejściem, jak przy dotknięciu dolnego paska.
                self.przelacz_zakladke(3)
            return handler

        def idz_do_kosztow(podzakladka=0):
            """Numer zakładki zmienił się przy przebudowie nawigacji — kafelki
            kokpitu wołają teraz ekran po nazwie z rejestru, więc następna zmiana
            układu nie zostawi tu martwego odnośnika."""
            def handler(e):
                utils.otworz_ekran(self._page, self.state,
                                   "inne" if podzakladka else "paliwo", self.akcje_nawigacji,
                                   widok=self)
            return handler

        def styl_wartosci(**nadpisania):
            pola = dict(size=utils.FS["title"], weight="bold", no_wrap=True,
                        overflow=ft.TextOverflow.ELLIPSIS)
            pola.update(nadpisania)
            return pola

        def tekst_wartosci(wartosc, **nadpisania):
            """Główna wartość kafelka w jednym stylu. `wartosc` bywa gotowym
            napisem („Brak danych”, nazwa terminu), a bywa kontrolką z animacji
            wejścia — kafelek przekazuje jedno i drugie dalej bez zaglądania
            do środka."""
            if isinstance(wartosc, ft.Control):
                return wartosc
            return ft.Text(wartosc, **styl_wartosci(**nadpisania))

        def liczba_kafelka(wartosc, formatuj, zastepnik="Brak danych", **nadpisania):
            """Liczba, która przy wejściu dolicza do swojej wartości. Brak
            liczby to `zastepnik` — kafelek bez danych nie ma czego animować
            i nie udaje, że ma zero."""
            if wartosc is None:
                return ft.Text(zastepnik, **styl_wartosci(**nadpisania))
            return scena.liczba(wartosc, formatuj, **styl_wartosci(**nadpisania))

        def kafel_wartosci(ikona, kolor_ikony, etykieta, wartosc, on_click):
            return ft.Container(
                width=SZER_KAFLA, padding=15,
                **utils.powierzchnia(self._page, "kafel"),
                ink=True, on_click=on_click,
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ikona, size=15, color=kolor_ikony),
                        utils.etykieta(etykieta, expand=True),
                    ], spacing=6),
                    tekst_wartosci(wartosc),
                ], spacing=4),
            )

        def kafel_pusty(ikona, kolor_ikony, etykieta, wartosc, on_click):
            """Kafelek, który nie ma o czym mówić: przy włączonym chowaniu znika
            z siatki (None), przy wyłączonym wygląda dokładnie jak dotąd.

            Chowanie obejmuje WYŁĄCZNIE pustkę typu „nie dotyczy / nieustawione”:
            budżet bez limitu, opony, których nie ma w garażu. Kafelek, który
            tylko czeka na dane („Za mało danych”), zostaje — jego pustka sama
            się skończy, a do tego czasu jest zaproszeniem do wpisania czegoś,
            a nie szumem."""
            if self._chowaj_puste:
                return None
            return kafel_wartosci(ikona, kolor_ikony, etykieta, wartosc, on_click)

        def stopka_iskry(podpis, chip=None):
            """Dolny wiersz kafelka z iskrą: chip trendu po lewej, krótki podpis
            po prawej. Jeden układ na wszystkie takie kafelki — wcześniej każdy
            składał go u siebie i rozmiar tekstu, wyrównanie oraz odstęp
            rozjeżdżały się między „Kosztem w mies.”, „Kosztem / 1000 km”
            i resztą."""
            wiersz = [chip] if chip is not None else []
            wiersz.append(ft.Text(
                podpis, size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
                no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS, expand=True,
                text_align=ft.TextAlign.END if chip is not None else ft.TextAlign.START,
            ))
            return ft.Row(wiersz, spacing=6)

        def kafel_z_iskra(ikona, kolor_ikony, etykieta, wartosc, seria, on_click,
                          wzrost_zly=True, podpis_stopki=None):
            """Kafelek liczbowy wzbogacony o mini-wykres i chip trendu — dokładnie
            ten sam układ, który sprawdził się przy „Śr. spalanie”. Przy mniej niż
            dwóch punktach nie ma czego rysować, więc wracamy do wersji „gołej”,
            zamiast udawać trend z jednego pomiaru."""
            iskra = utils.sparkline(seria, kolor_ikony, wysokosc=WYS_ISKRY)
            if iskra is None:
                return kafel_wartosci(ikona, kolor_ikony, etykieta, wartosc, on_click)

            pierwsza, ostatnia = seria[0], seria[-1]
            zmiana = ((ostatnia - pierwsza) / pierwsza * 100) if pierwsza > 0 else None

            stopka = stopka_iskry(
                podpis_stopki or f"{len(seria)} ost. pomiarów",
                chip=utils.znacznik_trendu(zmiana, wzrost_zly=wzrost_zly,
                                           rozmiar=utils.FS["caption"]),
            )

            return ft.Container(
                width=SZER_KAFLA + 60, padding=15,
                **utils.powierzchnia(self._page, "kafel"),
                ink=True, on_click=on_click,
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ikona, size=15, color=kolor_ikony),
                        utils.etykieta(etykieta, expand=True),
                    ], spacing=6),
                    tekst_wartosci(wartosc),
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
                zmiana_mc, bez_trendu = None, "Za wcześnie na trend"
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

                # Liczenie i kolorowanie chipa oddane do utils.znacznik_trendu:
                # ten sam próg 5% i ta sama paleta, co na pozostałych kafelkach
                # z iskrą. Tutaj zostaje wyłącznie to, co jest tu wyjątkowe —
                # porównanie dzień-do-dnia z poprzednim miesiącem.
                if koszt_poprzedni_do_dnia > 0:
                    zmiana_mc = ((koszt_biezacy - koszt_poprzedni_do_dnia)
                                 / koszt_poprzedni_do_dnia) * 100
                    bez_trendu = None
                else:
                    zmiana_mc, bez_trendu = None, "Brak porównania"

            # Iskra z sum miesięcznych: sześć słupków z kafelka „Wydatki 6 mies.”
            # w formie linii, żeby kwota od razu miała tło historyczne.
            iskra_mc = utils.sparkline([s for _, _, s in dane_mc], ft.Colors.PRIMARY,
                                       wysokosc=WYS_ISKRY)

            zawartosc = [
                ft.Row([
                    ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET, size=15, color=ft.Colors.PRIMARY),
                    utils.etykieta("Koszt w mies.", expand=True),
                ], spacing=6),
                liczba_kafelka(koszt_biezacy,
                               lambda v: f"{utils.formatuj_liczba(v)} {utils.symbol_waluty()}"),
            ]
            if iskra_mc is not None:
                zawartosc.append(iskra_mc)
            zawartosc.append(stopka_iskry(
                f"{len(dane_mc)} ost. mies." if iskra_mc is not None else "",
                chip=utils.znacznik_trendu(
                    zmiana_mc, wzrost_zly=True, rozmiar=utils.FS["caption"],
                    tekst_bez_trendu=bez_trendu, ikona_bez_trendu=ft.Icons.INFO_OUTLINE,
                ),
            ))

            return ft.Container(
                width=SZER_KAFLA + (60 if iskra_mc is not None else 0),
                padding=15,
                # Barwienie na PRIMARY robiło z tego kafelka najgłośniejszy na
                # kokpicie, nie mając nic do powiedzenia o stanie. Barwa zostaje
                # dla kafli, które naprawdę czegoś chcą.
                **utils.powierzchnia(self._page, "kafel"),
                ink=True, on_click=idz_do_statystyk(0),
                content=ft.Column(zawartosc, spacing=6),
            )

        def widget_termin():
            powiadomienia = db.pobierz_powiadomienia(self.state.auto_id)
            if powiadomienia:
                p = powiadomienia[0]
                kolor_p = utils.KOLOR_STATUS["critical"] if p["status"] == "przeterminowane" else utils.KOLOR_STATUS["warning"]
                ikona_p = ft.Icons.WARNING if p["status"] == "przeterminowane" else ft.Icons.HOURGLASS_BOTTOM
                dodatek = f"  (+{len(powiadomienia) - 1})" if len(powiadomienia) > 1 else ""

                tresc = ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.EVENT, size=15, color=ft.Colors.PRIMARY),
                        utils.etykieta(f"Termin{dodatek}", expand=True),
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
                stan_kafla = utils.stan_z_koloru(kolor_p)
            else:
                tresc = ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.EVENT_AVAILABLE, size=15, color=utils.KOLOR_STATUS["ok"]),
                        utils.etykieta("Termin", expand=True),
                    ], spacing=6),
                    ft.Text("Na czas", size=utils.FS["title"], weight="bold", color=utils.KOLOR_STATUS["ok"]),
                    ft.Text("Brak terminów", size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT),
                ], spacing=4)
                on_klik = None
                # „Na czas" barwione na zielono krzyczało tak samo głośno jak
                # termin po terminie. Brak powodu do działania nie jest powodem
                # do wyróżnienia — zieleń została w ikonie i w napisie.
                stan_kafla = None

            return ft.Container(
                width=SZER_KAFLA, padding=15,
                **utils.powierzchnia(self._page, "kafel", stan=stan_kafla),
                ink=on_klik is not None, on_click=on_klik,
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
                        # Słupek wyrasta od dołu przy wejściu na kokpit. Wysokość
                        # to jedyna właściwość z tej czwórki, którą Flet potrafi
                        # animować SAM (Container.animate) — więc tu klatek nie
                        # liczy Python, tylko Flutter.
                        scena.wysokosc(ft.Container(
                            width=20, height=wysokosc, border_radius=5,
                            bgcolor=ft.Colors.PRIMARY if biezacy else ft.Colors.with_opacity(0.35, ft.Colors.PRIMARY),
                            tooltip=f"{MIESIACE_NAZWY[mies - 1]} {rok}: {utils.formatuj_liczba(suma)} {utils.symbol_waluty()}",
                            animate=ft.Animation(300, ft.AnimationCurve.EASE_OUT),
                        ), wysokosc, od=4),
                        ft.Text(f"{mies:02d}", size=10, weight="bold" if biezacy else "normal",
                                color=ft.Colors.PRIMARY if biezacy else ft.Colors.ON_SURFACE_VARIANT),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4)
                )

            return ft.Container(
                width=SZER_KAFLA + 100, padding=15,
                **utils.powierzchnia(self._page, "kafel"),
                ink=True, on_click=idz_do_statystyk(1),
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.BAR_CHART, size=15, color=ft.Colors.PRIMARY),
                        ft.Text("Wydatki 6 mies.", size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT),
                    ], spacing=6),
                    ft.Row(slupki, alignment=ft.MainAxisAlignment.SPACE_EVENLY, vertical_alignment=ft.CrossAxisAlignment.END),
                ], spacing=10),
            )

        def widget_skumulowany():
            """Suma narastająca jednym rzutem oka.

            Bez chipa trendu — inaczej niż przy pozostałych kafelkach z iskrą.
            Krzywa narastająca rośnie ZAWSZE, więc „rośnie o 12%" nie niosłoby
            tu żadnej informacji; stopka mówi zamiast tego, od kiedy liczy się
            rachunek i ile wychodzi na dzień."""
            iskra = utils.sparkline(dane_skumulowane.get("iskra") or [],
                                    ft.Colors.PRIMARY, wysokosc=WYS_ISKRY)
            if iskra is None:
                return kafel_wartosci(
                    ft.Icons.STACKED_LINE_CHART, ft.Colors.PRIMARY, "Koszt skumulowany",
                    "Za mało danych", idz_do_statystyk(1),
                )

            stopka = []
            if dane_skumulowane.get("start"):
                stopka.append(("od zakupu " if dane_skumulowane.get("czy_od_zakupu") else "od ")
                              + dane_skumulowane["start"].strftime("%m.%Y"))
            if dane_skumulowane.get("koszt_dzien"):
                stopka.append(f"{utils.formatuj_liczba(dane_skumulowane['koszt_dzien'])} "
                              f"{utils.symbol_waluty()}/dzień")

            return ft.Container(
                width=SZER_KAFLA + 60, padding=15,
                **utils.powierzchnia(self._page, "kafel"),
                ink=True, on_click=idz_do_statystyk(1),
                tooltip="Suma wszystkiego, co to auto kosztowało — dotknij, aby zobaczyć krzywą",
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.STACKED_LINE_CHART, size=15, color=ft.Colors.PRIMARY),
                        utils.etykieta("Koszt skumulowany", expand=True),
                    ], spacing=6),
                    tekst_wartosci(liczba_kafelka(
                        dane_skumulowane.get("suma") or None,
                        lambda v: f"{utils.formatuj_liczba(v, 0)} {utils.symbol_waluty()}",
                    )),
                    iskra,
                    stopka_iskry(" · ".join(stopka)),
                ], spacing=6),
            )

        def widget_koszt_1000km():
            """Cena jazdy w oknie kroczącym — ta liczba mówi „sprzedaj”.

            Chip trendu bierze zmianę ROK DO ROKU, a nie początek kontra koniec
            iskry: przy dziesięcioletniej historii ta druga porównywałaby dzisiaj
            z czasami, których nikt już nie pamięta."""
            iskra = utils.sparkline(dane_1000km.get("iskra") or [], ft.Colors.PRIMARY,
                                    wysokosc=WYS_ISKRY)
            if iskra is None or not dane_1000km.get("biezacy"):
                return kafel_wartosci(
                    ft.Icons.AUTO_GRAPH, ft.Colors.BLUE_GREY_700, "Koszt / 1000 km",
                    "Za mało danych", idz_do_statystyk(1),
                )

            stopka_tekst = f"okno {dane_1000km['okno']} mies."
            srednia = dane_1000km.get("srednia_zyciowa")
            if srednia:
                stopka_tekst += (f" • średnio {utils.formatuj_liczba(srednia, 0)} "
                                 f"{utils.symbol_waluty()}")
            chip_rdr = (utils.znacznik_trendu(dane_1000km["zmiana_rdr"], wzrost_zly=True,
                                              rozmiar=utils.FS["caption"])
                        if dane_1000km.get("zmiana_rdr") is not None else None)

            return ft.Container(
                width=SZER_KAFLA + 60, padding=15,
                **utils.powierzchnia(self._page, "kafel"),
                ink=True, on_click=idz_do_statystyk(1),
                tooltip="Cena jazdy w oknie kroczącym — dotknij, aby zobaczyć krzywą",
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.AUTO_GRAPH, size=15, color=ft.Colors.PRIMARY),
                        utils.etykieta("Koszt / 1000 km", expand=True),
                    ], spacing=6),
                    tekst_wartosci(liczba_kafelka(
                        dane_1000km.get("biezacy"),
                        lambda v: f"{utils.formatuj_liczba(v, 0)} {utils.symbol_waluty()}",
                    )),
                    iskra,
                    stopka_iskry(stopka_tekst, chip=chip_rdr),
                ], spacing=6),
            )

        def widget_koszt_km():
            koszt_km = dane_porownanie.get("koszt_km")
            wartosc = liczba_kafelka(
                koszt_km or None,
                lambda v: f"{utils.formatuj_liczba(v, 2)} {utils.symbol_waluty()}/km",
            )
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
            # Odliczamy liczbę JUŻ przeliczoną na jednostkę z Ustawień. Przy km/l
            # i mpg mniejsze zużycie znaczy WIĘKSZĄ liczbę, więc animowanie
            # l/100km jechałoby na ekranie w drugą stronę, a start od zera byłby
            # dzieleniem przez zero (patrz db.przelicz_zuzycie).
            zuzycie, jednostka_zuzycia = db.przelicz_zuzycie(spalanie, czy_prad_kokpit)
            wartosc = liczba_kafelka(
                zuzycie,
                lambda v: f"{utils.formatuj_liczba(v, 1)} {jednostka_zuzycia}",
                zastepnik="Za mało danych",
            )
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
                # W aucie spalinowym ten kafelek nie będzie miał danych NIGDY.
                if self._chowaj_puste:
                    return None
                wartosc, stopka = "Brak danych", "Uzupełnij baterię i naładuj do pełna"
            else:
                wartosc = liczba_kafelka(zasieg["szacowany"],
                                         lambda v: f"{utils.formatuj_liczba(v, 0)} km")
                if zasieg["procent_deklarowanego"]:
                    stopka = f"{utils.formatuj_liczba(zasieg['procent_deklarowanego'], 0)}% katalogowego"
                elif zasieg["pojemnosc"]:
                    stopka = f"z {utils.formatuj_liczba(zasieg['pojemnosc'], 0)} kWh"
                else:
                    stopka = "z Twojego zużycia"
            # Własny kafelek zamiast kafel_wartosci, bo potrzebna jest trzecia
            # linijka: „ile procent katalogowego” to sedno tej liczby.
            return ft.Container(
                width=SZER_KAFLA, padding=15,
                **utils.powierzchnia(self._page, "kafel"),
                ink=True, on_click=idz_do_statystyk(0),
                tooltip="Realny zasięg policzony z Twojego zużycia",
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.BATTERY_CHARGING_FULL, size=15, color=ft.Colors.GREEN_700),  # paleta: tożsamość — akcent kafla
                        utils.etykieta("Zasięg EV", expand=True),
                    ], spacing=6),
                    tekst_wartosci(wartosc),
                    ft.Text(stopka, size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
                            no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                ], spacing=4),
            )

        def widget_przebieg_dzienny():
            sredni = db.oblicz_sredni_dzienny_przebieg(self.state.auto_id)
            wartosc = liczba_kafelka(sredni or None,
                                     lambda v: f"{utils.formatuj_liczba(v, 1)} km/dzień")
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
                            ft.Text(opis, size=11, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                            ft.Text(f"{kto} • {kiedy_tekst}", size=10, color=ft.Colors.ON_SURFACE_VARIANT, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                        ], spacing=0, expand=True, tight=True),
                    ], spacing=6)
                )

            return ft.Container(
                width=SZER_KAFLA + 90, padding=15,
                **utils.powierzchnia(self._page, "kafel"),
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
            kolor_kond, _, etykieta_kond = utils.wskaznik_kondycji(kondycja)
            kolor_gauge = utils.kolor_kondycji_plynny(kondycja)

            # Zamiast samego „82/100”: pierścień wypełniony proporcjonalnie do
            # wyniku i płynnie barwiony od czerwieni do zieleni. Ocena jest wtedy
            # czytelna z odległości, bez czytania liczby — a liczba i tak zostaje
            # w środku dla tych, którzy chcą dokładną wartość.
            return ft.Container(
                width=SZER_KAFLA, padding=15,
                **utils.powierzchnia(self._page, "kafel", stan=utils.stan_z_koloru(kolor_kond)),
                # Klik prowadzi teraz do ROZPISKI, a nie do magazynu: sam wynik
                # nie mówi, co go obniżyło, i to jest pierwsze pytanie po jego
                # zobaczeniu.
                ink=True, on_click=lambda e: utils.pokaz_panel_kondycji(self._page, self.state),
                tooltip=f"Kondycja pojazdu: {etykieta_kond} — dotknij, aby zobaczyć rozpiskę",
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.MONITOR_HEART, size=15, color=kolor_gauge),
                        utils.etykieta("Kondycja", expand=True),
                    ], spacing=6),
                    ft.Row([utils.gauge_kondycji(kondycja, rozmiar=76, grubosc=8, scena=scena)],
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
            stan_obs = utils.stan_z_koloru(kolor)
            plaszczyzna = utils.powierzchnia(self._page, "kafel", stan=stan_obs)
            # Obserwacja w stanie jest już zabarwiona — pasek po lewej powtarzałby
            # to samo trzeci raz (po tytule i po tle). Obserwacja spokojna paska
            # potrzebuje, bo inaczej nie ma po czym jej poznać.
            if stan_obs is None:
                plaszczyzna["border"] = ft.Border.only(left=ft.BorderSide(3, kolor))
            return ft.Container(
                width=SZER_KAFLA + 80, padding=15,
                **plaszczyzna,
                ink=True, on_click=idz_do_statystyk(3),
                tooltip=o["tekst"],
                content=ft.Column([
                    ft.Row([
                        ft.Icon(utils.ikona_z_mapy(utils.IKONY_OBSERWACJI, o["ikona"], ft.Icons.INSIGHTS),
                                size=15, color=kolor),
                        ft.Text(o["tytul"], size=utils.FS["caption"], color=kolor,
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
                return kafel_pusty(
                    ft.Icons.SAVINGS, ft.Colors.BLUE_GREY_700, "Budżet",
                    "Nie ustawiono", lambda e: utils.przejdz(self._page, "/budzet"),
                )
            stan = stany[0]
            stan_budzetu = {"przekroczony": "critical", "uwaga": "warning"}.get(stan.get("status"))
            return ft.Container(
                width=SZER_KAFLA + 80, padding=15,
                **utils.powierzchnia(self._page, "kafel", stan=stan_budzetu),
                ink=True, on_click=lambda e: utils.przejdz(self._page, "/budzet"),
                tooltip=f"Budżet: {stan['etykieta_okresu'].lower()} — dotknij, aby zmienić limity",
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.SAVINGS, size=15, color=ft.Colors.PRIMARY),
                        ft.Text(f"Budżet • {stan['etykieta_okresu'].lower()}", size=utils.FS["caption"],
                                color=ft.Colors.ON_SURFACE_VARIANT, expand=True,
                                no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                    ], spacing=6),
                    utils.pasek_budzetu(self._page, stan, scena=scena),
                ], spacing=8),
            )

        def widget_zasieg_bak():
            dane = db.pobierz_zasieg_na_baku(self.state.auto_id)
            if not dane:
                return kafel_pusty(
                    ft.Icons.LOCAL_GAS_STATION, ft.Colors.BLUE_GREY_700, "Zasięg na baku",
                    "Podaj pojemność", lambda e: utils.przejdz(self._page, f"/auto/edytuj/{self.state.auto_id}"),
                )
            return ft.Container(
                width=SZER_KAFLA + 80, padding=15,
                **utils.powierzchnia(self._page, "kafel"),
                ink=True, on_click=idz_do_statystyk(3),
                tooltip="Szacunek z licznika i Twojego zużycia — nie z czujnika w aucie",
                content=utils.wskaznik_baku(self._page, dane, kompaktowy=True, scena=scena),
            )

        def widget_prognoza_rok():
            prognoza = db.prognoza_kosztow(self.state.auto_id)
            if not prognoza:
                return kafel_wartosci(
                    ft.Icons.QUERY_STATS, ft.Colors.BLUE_GREY_700, "Prognoza roczna",
                    "Za mało danych", idz_do_statystyk(3),
                )
            wartosc = liczba_kafelka(
                prognoza["prognoza_calego_roku"],
                lambda v: f"{utils.formatuj_liczba(v, 0)} {utils.symbol_waluty()}",
            )
            stopka = (f"do końca roku jeszcze "
                      f"{utils.formatuj_liczba(prognoza['prognoza_do_konca'], 0)} {utils.symbol_waluty()}")
            return ft.Container(
                width=SZER_KAFLA + 60, padding=15,
                **utils.powierzchnia(self._page, "kafel"),
                ink=True, on_click=lambda e: utils.przejdz(self._page, "/rok"),
                tooltip=f"Ekstrapolacja ze średniej z {prognoza['miesiecy_bazowych']} pełnych miesięcy",
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.QUERY_STATS, size=15, color=ft.Colors.DEEP_PURPLE_700),
                        ft.Text(f"Prognoza {prognoza['rok']}", size=utils.FS["caption"],
                                color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                    ], spacing=6),
                    tekst_wartosci(wartosc),
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
                return kafel_pusty(
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
            stan_opon = None
            if bieznik is not None:
                # 1,6 mm to minimum prawne, 3 mm — próg, przy którym opona
                # przestaje sensownie odprowadzać wodę.
                kolor_bieznika = (utils.KOLOR_STATUS["critical"] if bieznik < 1.6
                                  else utils.KOLOR_STATUS["warning"] if bieznik < 3 else utils.KOLOR_STATUS["ok"])
                stan_opon = utils.stan_z_koloru(kolor_bieznika)
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
                    utils.etykieta("Opony", expand=True),
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
                width=SZER_KAFLA + 40, padding=15,
                **utils.powierzchnia(self._page, "kafel", stan=stan_opon),
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
                return kafel_pusty(
                    ft.Icons.FACT_CHECK, ft.Colors.BLUE_GREY_700, "Checklista",
                    "Brak listy", lambda e: utils.przejdz(self._page, "/do-zrobienia"),
                )

            kolor = utils.KOLOR_STATUS["ok"] if stan["gotowa"] else ft.Colors.PRIMARY
            stopka = ("wszystko sprawdzone" if stan["gotowa"]
                      else f"zostało {stan['razem'] - stan['zrobione']} do sprawdzenia")

            def otworz(e):
                self.state.do_zrobienia_podzakladka = 1
                utils.przejdz(self._page, "/do-zrobienia")

            return ft.Container(
                width=SZER_KAFLA + 40, padding=15,
                **utils.powierzchnia(self._page, "kafel"),
                ink=True, on_click=otworz,
                tooltip=stan["nazwa"],
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.FACT_CHECK, size=15, color=kolor),
                        ft.Text("Przed trasą", size=utils.FS["caption"],
                                color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                    ], spacing=6),
                    liczba_kafelka(stan["zrobione"],
                                   lambda v: f"{utils.formatuj_liczba(v, 0)} / {stan['razem']}"),
                    scena.wskaznik(ft.ProgressBar(
                        value=(stan["zrobione"] / stan["razem"]) if stan["razem"] else 0,
                        color=kolor, bgcolor=utils.tlo_toru(self._page),
                        height=6, border_radius=3,
                    )),
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
            # Zero wpisów to nie „0 zł opłat”, tylko auto, które takich kosztów
            # nie prowadzi — kwota zero nie jest tu informacją.
            if self._chowaj_puste and not stan["liczba"]:
                return None
            wartosc = liczba_kafelka(
                stan["suma"],
                lambda v: f"{utils.formatuj_liczba(v, 0)} {utils.symbol_waluty()}",
            )
            stopka = (f"{db.liczba_z_odmiana(stan['liczba'], 'wpis', 'wpisy', 'wpisów')} w {dzisiaj.year}" if stan["liczba"]
                      else f"brak wpisów w {dzisiaj.year}")
            return ft.Container(
                width=SZER_KAFLA + 20, padding=15,
                **utils.powierzchnia(self._page, "kafel"),
                ink=True, on_click=idz_do_kosztow(1),
                tooltip="Suma kategorii „Mandaty i opłaty drogowe” od początku roku",
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.TOLL, size=15, color=ft.Colors.DEEP_ORANGE_700),  # paleta: tożsamość — akcent kafla
                        ft.Text("Opłaty drogowe", size=utils.FS["caption"],
                                color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                    ], spacing=6),
                    tekst_wartosci(wartosc),
                    ft.Text(stopka, size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
                            no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                ], spacing=4),
            )

        def widget_do_zrobienia():
            stan = db.podsumowanie_do_zrobienia(self.state.auto_id)
            if not stan or not stan["otwarte"]:
                return kafel_wartosci(
                    ft.Icons.CHECKLIST_RTL, ft.Colors.GREEN_700, "Do zrobienia",  # paleta: tożsamość — akcent kafla
                    "Nic nie czeka", lambda e: utils.przejdz(self._page, "/do-zrobienia"),
                )

            kolor = utils.KOLOR_STATUS["critical"] if stan["po_terminie"] else ft.Colors.PRIMARY
            if stan["najblizsze"]:
                dni = stan["najblizsze"]["dni"]
                if dni < 0:
                    opis = f"{stan['najblizsze']['tytul']} — {utils.formatuj_dni(abs(dni))} po terminie"
                elif dni == 0:
                    opis = f"{stan['najblizsze']['tytul']} — dziś"
                else:
                    opis = f"{stan['najblizsze']['tytul']} — za {utils.formatuj_dni(dni)}"
            else:
                opis = "bez terminów"

            return ft.Container(
                width=SZER_KAFLA + 60, padding=15,
                **utils.powierzchnia(self._page, "kafel", stan=utils.stan_z_koloru(kolor)),
                ink=True, on_click=lambda e: utils.przejdz(self._page, "/do-zrobienia"),
                tooltip="Otwarte pozycje z listy Do zrobienia",
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.CHECKLIST_RTL, size=15, color=kolor),
                        ft.Text("Do zrobienia", size=utils.FS["caption"],
                                color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                    ], spacing=6),
                    ft.Row([
                        liczba_kafelka(stan["otwarte"], lambda v: utils.formatuj_liczba(v, 0)),
                        ft.Text(f"• {stan['po_terminie']} po terminie" if stan["po_terminie"] else "",
                                size=utils.FS["caption"], color=utils.KOLOR_STATUS["critical"], no_wrap=True),
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
                return kafel_pusty(
                    ft.Icons.INVENTORY_2, ft.Colors.BLUE_GREY_700, "Magazyn",
                    "Pusty", idz_do_czesci,
                )
            niski = stan["niski"]
            kolor = utils.KOLOR_STATUS["warning"] if niski else utils.KOLOR_STATUS["ok"]
            stopka = (", ".join(stan["nazwy_niskich"][:2]) if niski
                      else f"{db.liczba_z_odmiana(stan['razem'], 'pozycja', 'pozycje', 'pozycji')} na stanie")
            return ft.Container(
                width=SZER_KAFLA + 40, padding=15,
                **utils.powierzchnia(self._page, "kafel", stan=utils.stan_z_koloru(kolor)),
                ink=True, on_click=idz_do_czesci,
                tooltip="Pozycje magazynu poniżej własnego progu ostrzegawczego",
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.INVENTORY_2, size=15, color=kolor),
                        ft.Text("Magazyn", size=utils.FS["caption"],
                                color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                    ], spacing=6),
                    liczba_kafelka(niski or None,
                                   lambda v: f"{utils.formatuj_liczba(v, 0)} do uzupełnienia",
                                   zastepnik="Stan w porządku"),
                    ft.Text(stopka, size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
                            no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                ], spacing=4),
            )

        # ================= KAFELKI AKCJI =================
        # Kokpit odpowiadał dotąd wyłącznie na pytanie „co się dzieje”. Dwie
        # najczęstsze czynności w aplikacji — tankowanie i stan licznika —
        # siedziały pod FAB-em w rogu, czyli o dwa dotknięcia dalej niż ekran,
        # na którym i tak się jest.
        def kafel_akcji(ikona, tytul, on_click, podpowiedz=None):
            """Kafelek-przycisk: zamiast liczby ma czynność. Rola „podgląd” nie
            dostaje go wcale (None) — przycisk, który zawsze odmawia, jest gorszy
            od jego braku (ta sama zasada, co przy chowaniu akcji w menu wpisu)."""
            if tylko_podglad:
                return None
            return ft.Container(
                width=SZER_KAFLA, padding=15,
                **utils.powierzchnia(self._page, "kafel"),
                ink=True, on_click=on_click,
                tooltip=podpowiedz or tytul,
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.ADD_CIRCLE_OUTLINE, size=15, color=ft.Colors.PRIMARY),
                        utils.etykieta("Szybka akcja", expand=True),
                    ], spacing=6),
                    ft.Row([
                        ft.Icon(ikona, size=17, color=ft.Colors.PRIMARY),
                        ft.Text(tytul, size=utils.FS["title"], weight="bold", no_wrap=True,
                                overflow=ft.TextOverflow.ELLIPSIS, expand=True),
                    ], spacing=6),
                ], spacing=4),
            )

        def widget_akcja_tankowanie():
            return kafel_akcji(ft.Icons.LOCAL_GAS_STATION, "Tankowanie",
                               lambda e: utils.przejdz(self._page, "/tankowanie/nowe"),
                               "Nowy wpis tankowania")

        def widget_akcja_licznik():
            """Jedyna akcja, której nie ma pod FAB-em — i jedyna, która nie
            wymaga zmiany ekranu: okno z jednym polem zapisuje odczyt i wraca
            na kokpit z policzonymi na nowo kafelkami."""
            def otworz(e):
                utils.dialog_odczytu_przebiegu(
                    self._page, self.state.auto_id,
                    po_zapisie=lambda: utils.odswiez_ekran(self._page),
                )
            return kafel_akcji(ft.Icons.SPEED, "Stan licznika", otworz,
                               "Zapisz dzisiejszy stan licznika bez schodzenia z kokpitu")

        def widget_akcja_inny_koszt():
            return kafel_akcji(ft.Icons.RECEIPT_LONG, "Inny koszt",
                               lambda e: utils.przejdz(self._page, "/inne/nowy"),
                               "Nowy wpis w Inne koszty")

        def widget_akcja_wizyta():
            return kafel_akcji(ft.Icons.HOME_REPAIR_SERVICE, "Wizyta",
                               lambda e: utils.przejdz(self._page, "/wizyty/nowa"),
                               "Nowa wizyta w warsztacie")

        def widget_akcja_podzespol():
            return kafel_akcji(ft.Icons.HANDYMAN, "Podzespół",
                               lambda e: utils.przejdz(self._page, "/zadanie/nowy"),
                               "Nowy podzespół do pilnowania")

        def widget_akcja_do_zrobienia():
            return kafel_akcji(ft.Icons.CHECKLIST_RTL, "Do zrobienia",
                               lambda e: utils.przejdz(self._page, "/do-zrobienia/nowe"),
                               "Nowa pozycja na liście Do zrobienia")

        self._kokpit_budowniczy = {
            "koszt_miesiac": widget_koszt_miesiac,
            "termin": widget_termin,
            "wykres": widget_wykres,
            "skumulowany": widget_skumulowany,
            "koszt_1000km": widget_koszt_1000km,
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
            "akcja_tankowanie": widget_akcja_tankowanie,
            "akcja_licznik": widget_akcja_licznik,
            "akcja_inny_koszt": widget_akcja_inny_koszt,
            "akcja_wizyta": widget_akcja_wizyta,
            "akcja_podzespol": widget_akcja_podzespol,
            "akcja_do_zrobienia": widget_akcja_do_zrobienia,
        }

        # Ustawienia → „Ułóż kafelki kokpitu” tylko przełączają ekran; tryb
        # układania włącza się tutaj i od razu gasi flagę, żeby następne wejście
        # na kokpit było już zwykłe.
        if getattr(self.state, "kokpit_otworz_ukladanie", False):
            self.state.kokpit_otworz_ukladanie = False
            self.kokpit_edycja = True

        self.kokpit_kontener = ft.Container(content=self._zawartosc_kokpitu())
        return self.kokpit_kontener

    # ----- Przełączanie kokpitu: siatka <-> układanie kafelków -----
    def _zawartosc_kokpitu(self):
        """Zawartość kontenera kokpitu zależna od trybu. Kolejność bierzemy za
        każdym razem z bazy, więc po przeciągnięciu kafelka wystarczy odświeżyć
        sam kontener — bez przebudowy całego ekranu i utraty pozycji scrolla."""
        wlaczone = [w for w in db.pobierz_widgety_kokpitu(self.state.auto_id) if w in self._kokpit_budowniczy]
        # Pusty kokpit w trybie układania musi mimo wszystko pokazać pasek
        # i komórkę „Dodaj kafelek” — inaczej kto zdjął wszystko, nie ma jak wrócić.
        if not wlaczone and not self.kokpit_edycja:
            return ft.Container()
        # Czytane przy KAŻDEJ przebudowie, a nie raz przy tworzeniu budowniczych:
        # przycisk „Pokaż puste” w zachęcie zmienia ustawienie i od razu odświeża
        # kokpit, a flaga zamrożona w domknięciu zostawiłaby go pustym aż do
        # ponownego wejścia na ekran.
        self._chowaj_puste = db.czy_chowac_puste_kafelki()
        if self.kokpit_edycja:
            # Pasek nad siatką zamiast osobnego panelu z klockami: kafelki
            # zostają na swoich miejscach, więc układa się je tam, gdzie się je
            # widzi, i od razu widać, co z czym sąsiaduje.
            return ft.Column([self._kokpit_pasek_edycji(), self._kokpit_siatka(wlaczone)], spacing=10)
        return self._kokpit_siatka(wlaczone)

    def _odswiez_kokpit(self):
        if not self.kokpit_kontener:
            return
        # Przebudowa w locie (tryb układania, nowa kolejność po przeciągnięciu)
        # to NIE jest wejście na ekran — kafelki mają się pojawić od razu ze
        # swoimi wartościami, a nie odliczać od zera po każdym przesunięciu.
        if self._scena_zakladki:
            self._scena_zakladki.wygas()
        self.kokpit_kontener.content = self._zawartosc_kokpitu()
        try:
            self.kokpit_kontener.update()
        except Exception:
            # Kontener jeszcze nie jest w drzewie strony (np. tuż po zbudowaniu
            # widoku) — przy najbliższym renderze i tak pokaże aktualny stan.
            pass

    def _czy_animowac_kokpit(self):
        """Odliczanie gra przy starcie aplikacji i po zmianie pojazdu — nie przy
        każdym powrocie na kokpit.

        Ekran startowy przebudowuje się przy KAŻDEJ zmianie zakładki i po wyjściu
        z dowolnego ekranu. Animowanie za każdym razem zamieniłoby ruch „na
        powitanie” w zwłokę przy odczycie już za dziesiątym przejściem tam
        i z powrotem — a kokpit jest ekranem, na który się wraca, nie takim,
        który się ogląda."""
        if self.kokpit_edycja or not self.state.auto_id:
            return False
        if not db.czy_animacje_interfejsu():
            return False
        return getattr(self.state, "kokpit_animacja_dla", None) != self.state.auto_id

    def _ustaw_tryb_ukladania(self, wlaczony):
        self.kokpit_edycja = bool(wlaczony)
        self._odswiez_kokpit()

    def _kokpit_siatka(self, wlaczone):
        """Normalny tryb: siatka kafelków. Długie przytrzymanie dowolnego kafelka
        (albo kafelek „Ułóż”) wchodzi w tryb układania.

        Siatka zamiast poziomej karuzeli. Karuzela chowała część kafelków za
        krawędzią ekranu, a Flutter nie przewija zawartości myszą — stąd brał się
        wymuszony, zawsze widoczny suwak, który mówił tylko tyle, że coś tam
        jeszcze jest. Siatka pokazuje wszystkie kafelki naraz i zamienia ruch
        w bok na zwykłe przewijanie ekranu w dół.

        Szerokość komórki liczy Flet, a nie my — z dokładnie tego powodu, co
        w siatce skrótów (patrz _buduj_skroty): przy PIERWSZYM uruchomieniu
        aplikacji `page.width` nie jest jeszcze znane, więc dzielenie szerokości
        ekranu w Pythonie dawało jeden kafelek w wierszu aż do zmiany rozmiaru okna.

        Rozmiar kafelka bierze się z szerokości, którą budowniczy sam sobie
        zadeklarował: kafelek z iskrą, słupkami albo dłuższym tekstem prosił
        o więcej niż SZER_KAFLA i dostaje 2×1, pozostałe 1×1. Nowy widżet nie
        musi się więc dopisywać do żadnej listy rozmiarów, a kafelek, który bywa
        i z iskrą, i bez niej („Wydatki tego miesiąca”), zmienia rozmiar razem
        ze swoją zawartością."""
        kafelki = []
        self._kokpit_puste = []
        for wid in wlaczone:
            kafel = self._kokpit_budowniczy[wid]()
            # None znaczy „nie mam nic do powiedzenia” (patrz kafel_pusty).
            # Zapamiętujemy które, bo tryb układania pokazuje je przygaszone —
            # inaczej kafelek schowany wyglądałby jak wyłączony.
            if kafel is None:
                self._kokpit_puste.append(wid)
                # W układaniu kafelek schowany musi być widoczny: inaczej nie da
                # się go przestawić ani zdjąć, a w liście wyglądałby na wyłączony.
                if not self.kokpit_edycja:
                    continue
                kafel = self._kafel_schowany(wid)
            # Deklarowana szerokość zostaje tylko miarą potrzeb — o tym, ile
            # kafelek naprawdę zajmie, decyduje komórka siatki.
            potrzebna = getattr(kafel, "width", None) or SZER_KAFLA
            kafel.width = None
            kol = KOL_KAFLA_2X1 if potrzebna > PROG_KAFLA_2X1 else KOL_KAFLA_1X1
            if self.kokpit_edycja:
                kafelki.append(self._komorka_edycji(wid, kafel, kol))
                continue
            kafel.col = kol
            # Wszystkie widżety zwracają ft.Container, więc uchwyt long-press
            # dopinamy z zewnątrz zamiast powtarzać go w każdym budowniczym.
            try:
                kafel.on_long_press = lambda e: self._ustaw_tryb_ukladania(True)
            except Exception:
                pass
            kafelki.append(kafel)

        if not kafelki and not self.kokpit_edycja:
            return self._kokpit_zacheta()

        # Ostatnia komórka siatki, a nie okrągły guzik doklejony za karuzelą:
        # siatka nie ma „końca”, za którym dałoby się coś doczepić, a kafelek
        # w rytmie pozostałych czyta się jak część kokpitu. W układaniu ta sama
        # komórka służy do dokładania kafelków zdjętych krzyżykiem.
        if self.kokpit_edycja:
            kafelki.append(ft.Container(
                col=KOL_KAFLA_1X1, padding=15,
                border_radius=utils.RADIUS["lg"],
                border=ft.Border.all(1, ft.Colors.with_opacity(0.4, ft.Colors.PRIMARY)),
                ink=True, on_click=self._menu_dodawania_kafelka,
                tooltip="Dodaj kafelek na kokpit",
                content=ft.Row([
                    ft.Icon(ft.Icons.ADD, size=16, color=ft.Colors.PRIMARY),
                    ft.Text("Dodaj kafelek", size=utils.FS["label"], weight="bold",
                            color=ft.Colors.PRIMARY, no_wrap=True, expand=True,
                            overflow=ft.TextOverflow.ELLIPSIS),
                ], spacing=6),
            ))
        else:
            kafelki.append(ft.Container(
                col=KOL_KAFLA_1X1, padding=15,
                **utils.powierzchnia(self._page, "kafel"),
                ink=True, on_click=lambda e: self._ustaw_tryb_ukladania(True),
                tooltip="Ułóż kafelki (możesz też przytrzymać kafelek)",
                content=ft.Row([
                    ft.Icon(ft.Icons.DRAG_INDICATOR, size=15, color=ft.Colors.ON_SURFACE_VARIANT),
                    utils.etykieta("Ułóż kafelki", expand=True),
                ], spacing=6),
            ))

        return ft.ResponsiveRow(kafelki, spacing=10, run_spacing=10)

    def _kokpit_zacheta(self):
        """Wszystkie włączone kafelki akurat milczą — nowe auto, w którym nic
        jeszcze nie zostało wpisane. Sama pusta siatka wyglądałaby na awarię,
        więc kokpit mówi wprost, co się stało, i daje dwie drogi wyjścia:
        ułożyć kafelki albo z powrotem pokazać te puste."""
        def pokaz_puste(e):
            db.zapisz_chowanie_pustych_kafelkow(False)
            self._odswiez_kokpit()

        return utils.karta_analizy(
            self._page, "Kokpit ożyje po pierwszych wpisach", ft.Icons.DASHBOARD_CUSTOMIZE,
            [
                ft.Text(
                    "Kafelki, które nie mają jeszcze nic do powiedzenia, chowają się same. "
                    "Dodaj tankowanie albo stan licznika — wrócą razem z danymi.",
                    size=utils.FS["body"], color=ft.Colors.ON_SURFACE_VARIANT,
                ),
                ft.Row([
                    ft.TextButton("Ułóż kafelki", icon=ft.Icons.DRAG_INDICATOR,
                                  on_click=lambda e: self._ustaw_tryb_ukladania(True)),
                    ft.TextButton("Pokaż puste", icon=ft.Icons.VISIBILITY,
                                  on_click=pokaz_puste),
                ], spacing=utils.SPACING["sm"], wrap=True),
            ],
        )

    # ----- Układanie kafelków WPROST w siatce -----
    def _kokpit_pasek_edycji(self):
        """Pasek nad siatką w trybie układania. Zastąpił panel z poziomym paskiem
        klocków: klocki były abstrakcyjne (nie było widać, jak siatka wygląda),
        przeciągało się je w bok przez dwadzieścia pozycji, a widoczność kafelków
        ustawiało się zupełnie gdzie indziej — w Ustawieniach."""
        return ft.Container(
            padding=ft.Padding(12, 10, 12, 10),
            border_radius=utils.RADIUS["lg"],
            bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.PRIMARY),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.25, ft.Colors.PRIMARY)),
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.DASHBOARD_CUSTOMIZE, size=16, color=ft.Colors.PRIMARY),
                    ft.Text("Układasz kafelki", size=utils.FS["label"], weight="bold",
                            color=ft.Colors.PRIMARY, expand=True),
                    ft.TextButton("Gotowe", icon=ft.Icons.CHECK,
                                  on_click=lambda e: self._ustaw_tryb_ukladania(False)),
                ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Text(
                    "Przeciągnij kafelek na miejsce, w którym ma stanąć. Krzyżyk zdejmuje go "
                    "z kokpitu, a „Dodaj kafelek” na końcu siatki przywraca zdjęte.",
                    size=utils.FS["caption"], italic=True, color=ft.Colors.ON_SURFACE_VARIANT,
                ),
            ], spacing=6),
        )

    def _kafel_schowany(self, wid):
        """Zastępnik kafelka, który akurat nic nie pokazuje (patrz kafel_pusty).
        Widoczny WYŁĄCZNIE w układaniu — po to, żeby dało się go przesunąć albo
        zdjąć, zamiast szukać, czemu go nie ma."""
        return ft.Container(
            width=SZER_KAFLA, padding=15, opacity=0.55,
            **utils.powierzchnia(self._page, "kafel"),
            content=ft.Column([
                ft.Row([
                    ft.Icon(utils.ikona_z_mapy(utils.IKONY_KOKPITU, wid), size=15,
                            color=ft.Colors.ON_SURFACE_VARIANT),
                    utils.etykieta(str(db.KOKPIT_WIDGETY.get(wid, wid)), expand=True),
                ], spacing=6),
                ft.Text("teraz pusty", size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT),
            ], spacing=4),
        )

    def _komorka_edycji(self, wid, kafel, kol):
        """Kafelek w trybie układania: ten sam kafelek, tylko bez własnego
        kliknięcia, z krzyżykiem w rogu i owinięty w parę Draggable + DragTarget.
        Przeciąganie odbywa się w siatce, więc cel jest tam, gdzie się patrzy."""
        kafel.on_click = None
        kafel.on_long_press = None
        kafel.ink = False
        kafel.tooltip = None

        nazwa = str(db.KOKPIT_WIDGETY.get(wid, wid))
        krzyzyk = ft.Container(
            top=2, right=2, padding=3, border_radius=utils.RADIUS["sm"],
            bgcolor=utils.tlo_karty(self._page, poziom=3),
            ink=True, on_click=lambda e, w=wid: self._usun_kafelek(w),
            tooltip=f"Zdejmij z kokpitu: {nazwa}",
            content=ft.Icon(ft.Icons.CLOSE, size=15, color=utils.KOLOR_STATUS["critical"]),
        )

        # To, co „leci za palcem”: pełny kafelek byłby w locie ścianą tekstu,
        # a pigułka z ikoną i nazwą mówi dokładnie tyle, ile trzeba.
        podglad = ft.Container(
            padding=ft.Padding(10, 8, 10, 8), border_radius=utils.RADIUS["md"],
            bgcolor=utils.tlo_karty(self._page, poziom=2),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.4, ft.Colors.PRIMARY)),
            content=ft.Row([
                ft.Icon(utils.ikona_z_mapy(utils.IKONY_KOKPITU, wid), size=16, color=ft.Colors.PRIMARY),
                ft.Text(nazwa, size=utils.FS["label"], weight="bold", no_wrap=True),
            ], spacing=6, tight=True),
        )

        return ft.DragTarget(
            group="kokpit", col=kol, data=wid,
            on_accept=lambda e, cel=wid: self._przenies_kafelek(self._zrodlo_przeciagania(e), cel),
            content=ft.Draggable(
                group="kokpit", data=wid,
                content=ft.Stack([kafel, krzyzyk]),
                content_feedback=podglad,
                content_when_dragging=ft.Container(
                    height=72, border_radius=utils.RADIUS["lg"],
                    bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.PRIMARY),
                    border=ft.Border.all(1, ft.Colors.with_opacity(0.3, ft.Colors.PRIMARY)),
                ),
            ),
        )

    def _zrodlo_przeciagania(self, e):
        """Który kafelek jest przeciągany. Flet rozwiązuje `src` z identyfikatora
        kontrolki przez stronę, więc poza działającą stroną potrafi go nie być —
        stąd getattr zamiast `e.src.data` wprost."""
        return getattr(getattr(e, "src", None), "data", None)

    def _uklad_kokpitu(self):
        return [w for w in db.pobierz_widgety_kokpitu(self.state.auto_id)
                if w in self._kokpit_budowniczy]

    def _zapisz_uklad(self, kolejnosc):
        """Każda zmiana układu należy do TEGO pojazdu — i tym samym odpina go od
        układu wspólnego (patrz db.zapisz_widgety_kokpitu)."""
        db.zapisz_widgety_kokpitu(kolejnosc, self.state.auto_id)
        self._odswiez_kokpit()

    def _przenies_kafelek(self, zrodlo, cel):
        """Upuszczenie kafelka na inny: źródło wskakuje na miejsce celu, reszta
        przesuwa się o jedno. Zamiana miejscami byłaby prostsza w kodzie, ale przy
        układaniu siatki człowiek myśli „chcę go tutaj”, a nie „zamień te dwa”."""
        kolejnosc = self._uklad_kokpitu()
        if not zrodlo or not cel or zrodlo == cel:
            return
        if zrodlo not in kolejnosc or cel not in kolejnosc:
            return
        # Indeks celu bierzemy PRZED wyjęciem źródła z listy. Liczony po
        # wyjęciu cofa cel o jedno przy ruchu w prawo i kafelek ląduje przed nim
        # zamiast na jego miejscu — czyli nie tam, gdzie palec go postawił.
        i_cel = kolejnosc.index(cel)
        kolejnosc.remove(zrodlo)
        kolejnosc.insert(i_cel, zrodlo)
        self._zapisz_uklad(kolejnosc)

    def _usun_kafelek(self, wid):
        kolejnosc = [w for w in db.pobierz_widgety_kokpitu(self.state.auto_id) if w != wid]
        self._zapisz_uklad(kolejnosc)
        utils.pokaz_komunikat(
            self._page, f"Zdjęto z kokpitu: {db.KOKPIT_WIDGETY.get(wid, wid)}")

    def _dodaj_kafelek(self, wid):
        kolejnosc = list(db.pobierz_widgety_kokpitu(self.state.auto_id))
        if wid not in kolejnosc:
            kolejnosc.append(wid)
        self._zapisz_uklad(kolejnosc)

    def _menu_dodawania_kafelka(self, e=None):
        """Lista kafelków, których na kokpicie nie ma. Zastąpiła dwadzieścia
        checkboxów w Ustawieniach: widoczność i kolejność to jedna decyzja
        i jedno miejsce."""
        wlaczone = set(db.pobierz_widgety_kokpitu(self.state.auto_id))
        dostepne = [w for w in db.KOKPIT_WIDGETY
                    if w not in wlaczone and w in self._kokpit_budowniczy]
        if not dostepne:
            utils.pokaz_komunikat(self._page, "Wszystkie kafelki są już na kokpicie.")
            return
        pozycje = [{
            "ikona": utils.ikona_z_mapy(utils.IKONY_KOKPITU, wid),
            "tekst": str(db.KOKPIT_WIDGETY[wid]),
            "akcja": (lambda w=wid: self._dodaj_kafelek(w)),
        } for wid in dostepne]
        utils.pokaz_menu_kontekstowe(self._page, "Dodaj kafelek", pozycje)

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
