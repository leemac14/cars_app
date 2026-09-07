"""Zakładka Statystyki: liczby, wykresy, obserwacje i tabele."""

import db
import flet as ft
import flet_charts as fc
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
        dystans = (int(tankowania[-1].get('przebieg') or 0) - int(tankowania[0].get('przebieg') or 0)) if len(tankowania) > 1 else 0

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
            # Podzakładka nazywa się „Obserwacje”, a nie „Analiza” — od kiedy
            # cała zakładka nosi nazwę Analiza, dwie „Analizy” jedna w drugiej
            # mówiłyby użytkownikowi dokładnie tyle, co nic.
            # „Obserwacje” stoją trzecie, ale dostają indeks 3, a nie 2: numery
            # podzakładek siedzą w zapamiętanym stanie użytkownika i przesunięcie
            # ich otworzyłoby komuś Tabele zamiast Wykresów po aktualizacji.
            self._page,
            [("Liczby", 0), ("Wykresy", 1), ("Obserwacje", 3), ("Tabele", 2)],
            self.state.stat_podzakladka, zmien_podzakladke
        ))

        if self.state.stat_podzakladka == 0:
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
                            ft.Text(tytul, weight="bold", size=13, color=ft.Colors.ON_SURFACE,
                                    expand=True, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS)
                        ], spacing=6, expand=True),
                        ft.Text(
                            f"{utils.formatuj_liczba(kwota)} {utils.symbol_waluty()} ({utils.formatuj_liczba(procent, 0)}%)",
                            weight="bold", size=13, color=kolor, no_wrap=True,
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

            # ----- Rozbicie „Innych kosztów” na kategorie -----
            # Trzy paski wyżej mówią, ile poszło na „inne”. Samo w sobie to
            # bezużyteczna liczba: w tym worku leży mandat obok myjni i polisy.
            # Dopiero rozbicie pokazuje, czy „inne” rosną od opłat drogowych
            # (czyli od jeżdżenia), czy od czegoś zupełnie innego.
            rozbicie_innych = db.pobierz_koszty_innych_wg_kategorii(self.state.auto_id)
            if rozbicie_innych:
                wiersze_kategorii = []
                for nazwa_kat, suma_kat, liczba_kat in rozbicie_innych:
                    procent_kat = (suma_kat / inn * 100) if inn > 0 else 0
                    wiersze_kategorii.append(ft.Column([
                        ft.Row([
                            ft.Row([
                                ft.Icon(utils.ikona_kategorii_innych(nazwa_kat), size=15,
                                        color=utils.kolor_kategorii_innych(nazwa_kat)),
                                ft.Text(nazwa_kat, weight="bold", size=13, color=ft.Colors.ON_SURFACE,
                                        no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS, expand=True),
                            ], spacing=6, expand=True),
                            ft.Text(
                                f"{utils.formatuj_liczba(suma_kat)} {utils.symbol_waluty()} ({utils.formatuj_liczba(procent_kat, 0)}%)",
                                weight="bold", size=13, color=utils.kolor_kategorii_innych(nazwa_kat), no_wrap=True
                            ),
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.ProgressBar(
                            value=(procent_kat / 100) if procent_kat > 0 else 0,
                            color=utils.kolor_kategorii_innych(nazwa_kat),
                            bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
                            height=6, border_radius=3,
                        ),
                        ft.Text(f"{liczba_kat} {'wpis' if liczba_kat == 1 else 'wpisy/-ów'}",
                                size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT),
                    ], spacing=3))
                karta_kategorii_innych = ft.Container(
                    border_radius=utils.RADIUS["lg"], padding=utils.SPACING["lg"],
                    **utils.powierzchnia_karty(self._page, "md"),
                    content=ft.Column(wiersze_kategorii, spacing=12),
                )
            else:
                karta_kategorii_innych = ft.Container(
                    border_radius=utils.RADIUS["lg"], padding=utils.SPACING["lg"],
                    **utils.powierzchnia_karty(self._page, "md"),
                    content=ft.Text("Brak innych kosztów w historii pojazdu.", size=13, italic=True,
                                    color=ft.Colors.ON_SURFACE_VARIANT),
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
                    d = parsuj_date(d_str)
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
                d = parsuj_date(data_str)
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
                d = parsuj_date(data_str)
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
                                ft.Text(s["nazwa"], weight="bold" if czy_najtansza else "normal", size=13,
                                        expand=True, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                            ], spacing=6, expand=True),
                            ft.Text(
                                f"{utils.formatuj_liczba(s['srednia_cena'], 2)} {utils.symbol_waluty()}/L  •  {s['liczba_tankowan']}x",
                                size=13, weight="bold" if czy_najtansza else "normal", no_wrap=True,
                                color=ft.Colors.GREEN_700 if czy_najtansza else ft.Colors.ON_SURFACE,
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
                    ft.Text("Inne koszty wg kategorii", weight="bold", size=18, color=ft.Colors.PRIMARY, expand=True),
                    ft.Text(f"Razem: {utils.formatuj_liczba(inn)}  {utils.symbol_waluty()}", weight="bold",
                            size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                ]),
                karta_kategorii_innych,
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
                    utils.pasek_zawijany([sort_ui, filtr_rok_ui, filtr_mc_ui])
                )

                def filtruj_okresy(e):
                    zapytanie = e.control.value.lower().strip()
                    self.lista_kart_stat.controls.clear()
                    for k in self.wszystkie_karty_stat:
                        if zapytanie in k["szukaj"]:
                            self.lista_kart_stat.controls.append(k["karta"])
                    utils.dopasuj_wysokosc_listy(self.lista_kart_stat, self._page, wysokosc_pozycji=150)
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
                self.elementy.append(utils.pasek_zawijany([sort_ui_rok]))

                utils.posortuj_liste(wiersze_rok_wszystkie, self.state, "stat_lata", opcje_sort_rok)
                self.elementy.append(ft.Column([karta_okresu(w) for w in wiersze_rok_wszystkie], spacing=15))
