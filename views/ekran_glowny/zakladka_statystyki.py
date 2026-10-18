"""Zakładka Statystyki: liczby, wykresy, obserwacje i tabele."""

import db
import flet as ft
import sqlite3
import utils
from date import parsuj_date
from datetime import datetime
from state import MIESIACE_NAZWY


class MiksinZakladkiStatystyki:
    """Zakładka Statystyki: liczby, wykresy, obserwacje i tabele."""

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
        # Dystans z samych liczników — wpis bez przebiegu (import z samym
        # dystansem) stał na początku posortowanej listy z zerem i robił
        # z całego licznika auta „przejechane”, zaniżając koszt kilometra.
        liczniki = [int(t.get('przebieg') or 0) for t in tankowania if int(t.get('przebieg') or 0) > 0]
        dystans = (max(liczniki) - min(liczniki)) if len(liczniki) > 1 else 0

        razem = pal + serw + inn
        koszt_km = (razem / dystans) if dystans > 0 else 0.0

        sredni_dzienny = db.oblicz_sredni_dzienny_przebieg(self.state.auto_id)
        # Liczby wyżej są w km (tak liczy baza); na ekran idą w jednostce z Ustawień.
        j = utils.jednostka_dystansu()
        sredni_dz_str = (f"{utils.formatuj_dystans(sredni_dzienny, 1, j)}/dzień"
                         if sredni_dzienny else "Brak danych")

        def kafel(ikona, tytul, wartosc, kolor=ft.Colors.PRIMARY, expand=None):
            # Ikona nad wartością, nie obok: w połówce ekranu obok ikony zostawało
            # ~74 dp i „Zatankowano” łamało się w środku słowa.
            return utils.kafel_liczby(self._page, ikona, tytul, wartosc, kolor, expand)

        # Rok w pigułce, budżet, historia przebiegu i porównanie pojazdów to
        # wszystko „patrzenie na dane” — ale każde mieszkało gdzie indziej
        # (menu ⋮, karta pojazdu, dialog przebiegu). Tutaj mają wspólne wejście,
        # w zakładce, do której i tak wchodzi się po odpowiedzi na pytanie
        # „jak to wygląda”.
        self.elementy.append(ft.Row(
            utils.tytul_sekcji(ft.Icons.INSIGHTS, "Analiza"),
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ))
        self.elementy.append(utils.pasek_sekcji(
            self._page, self.state,
            ["rok", "budzet", "przebieg", "porownanie", "timeline"],
            self.akcje_nawigacji, self.liczniki_nawigacji,
        ))

        def zmien_podzakladke(idx):
            self.state.stat_podzakladka = idx
            utils.przejdz(self._page, "/")

        self.elementy.append(utils.segmented_control(
            # Podzakładka „Obserwacje” (cała zakładka to Analiza). Stoi trzecia, ale ma
            # indeks 3, nie 2: numery podzakładek siedzą w zapamiętanym stanie —
            # przesunięcie otworzyłoby komuś inną podzakładkę.
            self._page,
            [("Liczby", 0), ("Wykresy", 1), ("Obserwacje", 3), ("Tabele", 2)],
            self.state.stat_podzakladka, zmien_podzakladke
        ))

        if self.state.stat_podzakladka == 0:
            statystyki_energii = db.pobierz_statystyki_energii(self.state.auto_id)
            dwuzrodlowy = len(statystyki_energii) > 1

            self.elementy.extend([
                utils.naglowek_analizy(ft.Icons.PIE_CHART, "Podsumowanie kosztów"),
                kafel(ft.Icons.ATTACH_MONEY, "Całkowity koszt", f"{utils.formatuj_liczba(razem)} {utils.symbol_waluty()}", ft.Colors.RED_700),  # paleta: tożsamość — kolor kategorii kosztu
                ft.Row([
                    kafel(ft.Icons.LOCAL_GAS_STATION, "Na energię" if dwuzrodlowy else "Na paliwo",
                          f"{utils.formatuj_liczba(pal)} {utils.symbol_waluty()}", ft.Colors.BLUE_700, expand=1),
                    kafel(ft.Icons.BUILD, "Na serwis", f"{utils.formatuj_liczba(serw)} {utils.symbol_waluty()}", ft.Colors.ORANGE_700, expand=1),  # paleta: tożsamość — kolor kategorii kosztu
                ], spacing=10),
                ft.Row([
                    kafel(ft.Icons.RECEIPT_LONG, "Inne koszty", f"{utils.formatuj_liczba(inn)} {utils.symbol_waluty()}", ft.Colors.GREEN_700, expand=1),  # paleta: tożsamość — kolor kategorii kosztu
                    kafel(ft.Icons.ADD_ROAD, f"Koszt 1 {j}",
                          utils.formatuj_na_dystans(koszt_km, f"{utils.symbol_waluty()}/", 2, j),
                          ft.Colors.PURPLE_700, expand=1),
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

                self.elementy.append(utils.naglowek_analizy(ikona_sekcji, tytul_sekcji))
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
                          ft.Colors.AMBER_800, expand=1),  # paleta: tożsamość — akcent kafla
                    # Koszt na km liczony osobno pokazuje wprost, ile daje
                    # ładowanie zamiast tankowania.
                    kafel(ft.Icons.ADD_ROAD, f"Koszt 1 {j} ({stat['etykieta'].lower()})",
                          utils.formatuj_na_dystans(stat['koszt_km'], f"{utils.symbol_waluty()}/", 2, j)
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
                            ft.Colors.LIGHT_GREEN_800 if typ == "AC" else ft.Colors.DEEP_ORANGE_700,  # paleta: tożsamość — kolor typu polisy
                            expand=1,
                        )
                        for typ, dane in sorted(stat["ceny_ladowania"].items())
                    ], spacing=10))

            udzial = db.pobierz_udzial_energii(self.state.auto_id)
            if udzial:
                self.elementy.append(utils.naglowek_analizy(ft.Icons.PIE_CHART_OUTLINE, "Wydatek na energię"))
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
                            f"Koszty na {j} można za to dodać: razem dają pełny koszt energii.",
                            size=11, color=ft.Colors.ON_SURFACE_VARIANT, expand=True,
                        ),
                    ], spacing=8),
                ))

            zasieg = db.pobierz_zasieg_ev(self.state.auto_id)
            if zasieg and zasieg["szacowany"]:
                podpis = utils.formatuj_dystans(zasieg['szacowany'], 0, j)
                if zasieg["procent_deklarowanego"]:
                    podpis += f" ({utils.formatuj_liczba(zasieg['procent_deklarowanego'], 0)}% katalogowego)"
                self.elementy.append(ft.Row([
                    kafel(ft.Icons.BATTERY_CHARGING_FULL, "Realny zasięg na prądzie", podpis,
                          ft.Colors.GREEN_700),  # paleta: tożsamość — kolor kategorii kosztu
                ], spacing=10))

            self.elementy.extend([
                utils.naglowek_analizy(ft.Icons.INSIGHTS, "Przebieg"),
                ft.Row([
                    kafel(ft.Icons.ROUTE, "Zanotowany dystans", utils.formatuj_dystans(dystans, 0, j), ft.Colors.INDIGO_700, expand=1),
                    kafel(ft.Icons.TIMELAPSE, "Średnio dziennie", sredni_dz_str, ft.Colors.BLUE_GREY_700, expand=1),
                ], spacing=10),
            ])

        elif self.state.stat_podzakladka == 1:
            # Spis pytań zamiast dziesięciu wykresów jeden pod drugim: wiersz odpowiada liczbą
            # i zdaniem, cały wykres z zakresem otwiera się osobno (/wykres/<klucz>).
            self.elementy.extend(utils.spis_wykresow(self._page, self.state, self._scena_zakladki))

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
                kolor_tr = (utils.KOLOR_STATUS["critical"] if trend["kierunek"] == "wzrost"
                            else utils.KOLOR_STATUS["ok"] if trend["kierunek"] == "spadek"
                            else ft.Colors.BLUE_GREY_700)
                # Pigułka opisuje SUROWĄ zmianę — te same dwie liczby, co obok —
                # a kolor bierze się z kierunku po odjęciu sezonu. Dzięki temu
                # listopadowy skok nadal widać, ale nie świeci już na czerwono.
                zmiana_tr = trend["zmiana_proc"]
                istotna_tr = abs(zmiana_tr) >= db.PROG_ISTOTNOSCI_TRENDU
                opis_kierunku = ("Zużycie bez większych zmian" if not istotna_tr
                                 else "Zużycie rośnie" if zmiana_tr > 0 else "Zużycie spada")
                tekst_pigulki = (f"{opis_kierunku} o {utils.formatuj_liczba(abs(zmiana_tr), 0)}%"
                                 if istotna_tr else opis_kierunku)
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
                                ft.Icon(ft.Icons.TRENDING_UP if istotna_tr and zmiana_tr > 0
                                        else ft.Icons.TRENDING_DOWN if istotna_tr
                                        else ft.Icons.TRENDING_FLAT, size=14, color=kolor_tr),
                                ft.Text(tekst_pigulki,
                                        size=utils.FS["label"], weight="bold", color=kolor_tr),
                            ], spacing=5, tight=True),
                        ),
                    ]),
                ]
                opis_sezonu = db.opis_sezonowosci_trendu(trend)
                if opis_sezonu:
                    wiersze_trendu.append(ft.Text(
                        opis_sezonu, size=utils.FS["body"], color=ft.Colors.ON_SURFACE_VARIANT,
                    ))
                if trend.get("rdr_proc") is not None:
                    rdr = trend["rdr_proc"]
                    rok_temu = utils.formatuj_spalanie(trend["srednia_rok_temu"],
                                                       elektryczny=czy_prad_tr)
                    opis_rdr = ("zużycie praktycznie takie samo" if abs(rdr) < 1
                                else f"zużycie {'wyższe' if rdr > 0 else 'niższe'} "
                                     f"o {utils.formatuj_liczba(abs(rdr), 0)}%")
                    wiersze_trendu.append(ft.Text(
                        f"Wobec tego samego okresu rok temu ({rok_temu}): {opis_rdr}.",
                        size=utils.FS["body"], color=ft.Colors.ON_SURFACE_VARIANT,
                    ))
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
                    + (f" (okno {utils.formatuj_dni(trend['dni_okna'])})." if trend["dni_okna"] else ".")
                    + (" Sezon policzony z tego samego odcinka kalendarza w poprzednich "
                       "latach; kolor i obserwacje biorą się ze zmiany po jego odjęciu."
                       if trend.get("sezon_proc") is not None else ""),
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
                              ft.Colors.ORANGE_700, expand=1),  # paleta: tożsamość — kolor kategorii kosztu
                    ], spacing=10),
                    kafel(ft.Icons.QUERY_STATS, f"Cały {prognoza['rok']} — prognoza",
                          f"{utils.formatuj_liczba(prognoza['prognoza_calego_roku'])} {utils.symbol_waluty()}",
                          ft.Colors.DEEP_PURPLE_700),
                ]
                if prognoza.get("zmiana_rdr") is not None:
                    w_gore = prognoza["zmiana_rdr"] > 0
                    wiersze_prognozy.append(ft.Row([
                        ft.Icon(ft.Icons.TRENDING_UP if w_gore else ft.Icons.TRENDING_DOWN, size=16,
                                color=utils.KOLOR_STATUS["critical"] if w_gore else utils.KOLOR_STATUS["ok"]),
                        ft.Text(
                            f"{'Drożej' if w_gore else 'Taniej'} od {prognoza['rok'] - 1} roku o "
                            f"{utils.formatuj_liczba(abs(prognoza['zmiana_rdr']), 0)}% "
                            f"({utils.formatuj_liczba(prognoza['poprzedni_rok'])} {utils.symbol_waluty()})",
                            size=utils.FS["body"], color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                    ], spacing=6))
                wiersze_prognozy.append(ft.Text(
                    f"Ekstrapolacja ze średniej z "
                    f"{db.liczba_z_odmiana(prognoza['miesiecy_bazowych'], 'pełnego miesiąca', 'pełnych miesięcy', 'pełnych miesięcy')}. "
                    f"Bieżący miesiąc nie wchodzi do podstawy, żeby jego niepełność nie zaniżała wyniku. "
                    f"Do końca roku {db.odmien(prognoza['dni_pozostalo'], 'został', 'zostały', 'zostało')} "
                    f"{utils.formatuj_dni(prognoza['dni_pozostalo'])}.",
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
                self._page, "Budżety", ft.Icons.SAVINGS, zawartosc_budzetu, ft.Colors.GREEN_700))  # paleta: tożsamość — akcent sekcji

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
                d = parsuj_date(data_str)
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
                        etykieta = f"{MIESIACE_NAZWY[int(mies_i) - 1]} {rok_i}"
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
                        ft.Text(f"{utils.formatuj_liczba(razem_w)} {utils.symbol_waluty()}", weight="bold", size=16, color=utils.KOLOR_STATUS["cost"])
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
                chipy_filtrow, statystyki_po_filtrach = utils.pasek_filtrow(
                    self._page, self.state, wiersze_mc_wszystkie,
                    [("rok", "stat_miesiace_rok", 9), ("miesiac", "stat_miesiace_mc", 9)])

                self.elementy.append(
                    ft.Row(
                        controls=[sort_ui] + chipy_filtrow,
                        scroll=ft.ScrollMode.ADAPTIVE,
                        spacing=8
                    )
                )

                def filtruj_okresy(e):
                    zapytanie = e.control.value.lower().strip()
                    self.lista_kart_stat.controls.clear()
                    for k in self.wszystkie_karty_stat:
                        if zapytanie in k["szukaj"]:
                            self.lista_kart_stat.controls.append(k["karta"])
                    utils.dopasuj_wysokosc_listy(self.lista_kart_stat, self._page, wysokosc_pozycji=150)
                    self.update()

                self.elementy.append(utils.na_cala_szerokosc(
                    ft.TextField(
                        hint_text="Szukaj okresu (np. 2026)",
                        prefix_icon=ft.Icons.SEARCH,
                        on_change=utils.z_opoznieniem(self._page, filtruj_okresy),
                        **utils.styl_pola()
                    )
                ))

                self.lista_kart_stat = ft.ListView(spacing=utils.odstep_listy(), padding=0, height=utils.wysokosc_listy(self._page), auto_scroll=False)
                utils.pamietaj_pozycje(self._page, self.state, self.lista_kart_stat, "lista:statystyki")
                self.wszystkie_karty_stat = []

                wiersze_mc_f = statystyki_po_filtrach
                utils.posortuj_liste(wiersze_mc_f, self.state, "stat_miesiace", opcje_sort)

                if not wiersze_mc_f:
                    self.elementy.append(ft.Row([ft.Text("Brak wyników dla tych filtrów.", color=ft.Colors.ON_SURFACE_VARIANT)], alignment=ft.MainAxisAlignment.CENTER))
                else:
                    for w in wiersze_mc_f:
                        karta = karta_okresu(w)
                        self.wszystkie_karty_stat.append({"karta": karta, "szukaj": w[1].lower()})
                        self.lista_kart_stat.controls.append(karta)
                    utils.dopasuj_wysokosc_listy(self.lista_kart_stat, self._page, wysokosc_pozycji=150)
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
                self.elementy.append(
                    ft.Row(
                        controls=[sort_ui_rok],
                        scroll=ft.ScrollMode.ADAPTIVE,
                        spacing=8
                    )
                )

                utils.posortuj_liste(wiersze_rok_wszystkie, self.state, "stat_lata", opcje_sort_rok)
                self.elementy.append(ft.Column([karta_okresu(w) for w in wiersze_rok_wszystkie], spacing=15))
