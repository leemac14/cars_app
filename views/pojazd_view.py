import flet as ft

import db
import sync
import utils


class PojazdView(ft.View):
    """Pełna karta pojazdu. Zastępuje wysuwany panel „Specyfikacja”, który przy
    komplecie danych rozciągał się na trzy ekrany przewijania i nie dawał się
    ani przeszukać, ani skopiować.

    Układ idzie za tym, PO CO się tu wchodzi: najpierw tożsamość (to auto, ta
    tablica), potem liczby opisujące je jako całość, potem terminy — jedyna
    rzecz z tego ekranu, która potrafi kosztować mandat. Dalej rachunek
    posiadania, dane techniczne, ubezpieczenie i ściągawka do sklepu."""

    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state

        appbar = utils.zbuduj_pasek_z_powrotem(
            page, "Dane pojazdu", "/", ikona=ft.Icons.DIRECTIONS_CAR,
            akcje_dodatkowe=[
                ft.IconButton(
                    ft.Icons.EDIT, icon_color=ft.Colors.PRIMARY, tooltip="Edytuj dane pojazdu",
                    on_click=lambda e: utils.przejdz(self._page, f"/auto/edytuj/{self.state.auto_id}"),
                )
            ] if state.auto_id else None,
        )

        if not self.state.auto_id:
            super().__init__(
                route="/pojazd", padding=15, spacing=15, appbar=appbar,
                controls=[utils.ekran_braku_danych(
                    ikona=ft.Icons.DIRECTIONS_CAR,
                    tytul="Brak wybranego pojazdu",
                    opis="Dodaj pojazd, aby zobaczyć jego pełną kartę.",
                    tekst_przycisku="Dodaj pojazd",
                    on_click=lambda e: utils.przejdz(self._page, "/auto/nowy")
                )]
            )
            return

        self.dane = db.pobierz_dane_pojazdu(self.state.auto_id) or {}
        self.metryki = db.pobierz_metryki_pojazdu(self.state.auto_id, self.dane) or {}
        self.terminy = db.terminy_pojazdu(self.state.auto_id, self.dane)
        self.wspolny_id, _ = sync.czy_udostepniony(self.state.auto_id)

        elementy = [
            self._hero(),
            self._metryki(),
            self._terminy(),
            self._zakup_i_wartosc(),
            self._specyfikacja(),
            self._ubezpieczenie(),
            self._sciagawka(),
            self._notatki(),
            self._akcje(),
            utils.dol_bezpieczny(10),
        ]

        super().__init__(
            route="/pojazd", padding=15, spacing=15, appbar=appbar,
            controls=[utils.z_odswiezaniem(page, elementy)],
        )

    # ================= HERO =================

    def _hero(self):
        d = self.dane
        kolor = utils.MAPA_KOLOROW.get(d.get("kolor_motywu") or "", ft.Colors.PRIMARY)

        podtytul = " • ".join(str(x) for x in [
            d.get("rok_produkcji"), d.get("typ_paliwa"), d.get("skrzynia_biegow"),
        ] if x)

        naglowek = ft.Column([
            ft.Text(str(d.get("nazwa") or "Pojazd"), size=22, weight="bold",
                    no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
            ft.Text(podtytul, size=utils.FS["body"], color=ft.Colors.ON_SURFACE_VARIANT,
                    no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS, visible=bool(podtytul)),
            ft.Container(height=4),
            utils.tablica_rejestracyjna(
                d.get("nr_rej"), wysokosc=34,
                on_click=lambda e: utils.kopiuj_do_schowka(
                    self._page, d.get("nr_rej"), "Skopiowano numer rejestracyjny"),
            ),
        ], spacing=2, expand=True)

        sylwetka = ft.Container(
            width=78, height=78, border_radius=utils.RADIUS["lg"],
            bgcolor=ft.Colors.with_opacity(0.12, kolor),
            alignment=ft.Alignment.CENTER,
            content=ft.Icon(utils.ikona_nadwozia(d.get("nadwozie")), size=40,
                            color=ft.Colors.with_opacity(0.75, kolor)),
        )
        if d.get("zdjecie_glowne"):
            miniatura = ft.Container(
                width=78, height=78, border_radius=utils.RADIUS["lg"],
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                content=ft.Image(src=utils.abs_zalacznik(d["zdjecie_glowne"]),
                                 width=78, height=78, fit="cover",
                                 error_content=sylwetka),
            )
        else:
            miniatura = sylwetka

        tresc = [ft.Row([miniatura, naglowek], spacing=utils.SPACING["md"],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER)]

        if self.wspolny_id:
            tresc.append(ft.Row([
                ft.Icon(ft.Icons.GROUPS, size=14, color=ft.Colors.TEAL_700),
                ft.Text("Pojazd współdzielony — te dane widzi też druga osoba",
                        size=utils.FS["caption"], color=ft.Colors.TEAL_700, expand=True),
            ], spacing=6))

        return ft.Container(
            padding=utils.SPACING["lg"], border_radius=utils.RADIUS["lg"],
            **utils.powierzchnia_karty(self._page, "md"),
            content=ft.Column(tresc, spacing=utils.SPACING["sm"]),
        )

    # ================= METRYKI =================

    def _metryki(self):
        m = self.metryki

        def kafel(ikona, etykieta, wartosc, podpis=None, kolor=ft.Colors.PRIMARY, on_click=None):
            return ft.Container(
                expand=1, padding=utils.SPACING["md"], border_radius=utils.RADIUS["lg"],
                bgcolor=utils.tlo_karty(self._page, poziom=1),
                ink=bool(on_click), on_click=on_click,
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ikona, size=15, color=kolor),
                        ft.Text(etykieta, size=utils.FS["caption"],
                                color=ft.Colors.ON_SURFACE_VARIANT, expand=True,
                                no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                    ], spacing=6),
                    ft.Text(wartosc, size=utils.FS["title"], weight="bold",
                            no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(podpis or "", size=utils.FS["caption"],
                            color=ft.Colors.ON_SURFACE_VARIANT, visible=bool(podpis),
                            no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                ], spacing=3),
            )

        wiek = (f"{utils.formatuj_liczba(m['wiek_lat'], 1)} lat"
                if m.get("wiek_lat") else "—")
        podpis_wieku = ("od pierwszej rejestracji" if m.get("zrodlo_wieku") == "rejestracja"
                        else "z rocznika" if m.get("zrodlo_wieku") else "podaj rocznik")

        if m.get("intensywnosc"):
            procent = m["intensywnosc"]
            podpis_tempa = (f"{utils.formatuj_liczba(procent, 0)}% typowych "
                            f"{utils.formatuj_liczba(db.NORMA_PRZEBIEGU_ROCZNEGO, 0)} km/rok")
            kolor_tempa = (ft.Colors.ORANGE_700 if procent > 150
                           else ft.Colors.GREEN_700 if procent < 70 else ft.Colors.PRIMARY)
        else:
            podpis_tempa, kolor_tempa = "za mało danych", ft.Colors.ON_SURFACE_VARIANT

        kondycja = m.get("kondycja")
        _, ikona_kond, etykieta_kond = utils.wskaznik_kondycji(kondycja)

        return ft.Column([
            ft.Row([
                kafel(ft.Icons.SPEED, "Przebieg",
                      f"{utils.formatuj_liczba(m.get('przebieg') or 0, 0)} km",
                      "dotknij: historia licznika", ft.Colors.PRIMARY,
                      lambda e: utils.przejdz(self._page, "/przebieg")),
                kafel(ft.Icons.CAKE, "Wiek", wiek, podpis_wieku, ft.Colors.BLUE_GREY_700),
            ], spacing=10),
            ft.Row([
                kafel(ft.Icons.SPEED_OUTLINED, "Rocznie",
                      f"{utils.formatuj_liczba(m['przebieg_roczny'], 0)} km"
                      if m.get("przebieg_roczny") else "—",
                      podpis_tempa, kolor_tempa),
                ft.Container(
                    expand=1, padding=utils.SPACING["md"], border_radius=utils.RADIUS["lg"],
                    bgcolor=utils.tlo_karty(self._page, poziom=1),
                    ink=True, on_click=lambda e: utils.pokaz_panel_kondycji(self._page, self.state),
                    tooltip="Zobacz, co obniża kondycję",
                    content=ft.Row([
                        utils.gauge_kondycji(kondycja, rozmiar=54, grubosc=6),
                        ft.Column([
                            ft.Text("Kondycja", size=utils.FS["caption"],
                                    color=ft.Colors.ON_SURFACE_VARIANT),
                            ft.Text(etykieta_kond, size=utils.FS["body_strong"], weight="bold",
                                    no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                        ], spacing=2, expand=True),
                    ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ),
            ], spacing=10),
        ], spacing=10)

    # ================= TERMINY =================

    def _terminy(self):
        if not self.terminy:
            return utils.karta_analizy(
                self._page, "Terminy i dokumenty", ft.Icons.SHIELD,
                [ft.Text("Nie masz jeszcze wpisanych żadnych dat — OC, przeglądu, AC ani "
                         "assistance. To one napędzają powiadomienia i kondycję pojazdu.",
                         size=utils.FS["body"], color=ft.Colors.ON_SURFACE_VARIANT),
                 ft.FilledTonalButton("Uzupełnij daty", icon=ft.Icons.EVENT,
                                      on_click=lambda e: utils.przejdz(
                                          self._page, f"/auto/edytuj/{self.state.auto_id}"))],
            )

        wiersze = []
        for t in self.terminy:
            wiersze.append(utils.pasek_terminu(self._page, t))
        gw_km = self.dane.get("gwarancja_przebieg")
        if gw_km:
            zostalo = int(gw_km) - (self.metryki.get("przebieg") or 0)
            wiersze.append(ft.Row([
                ft.Icon(ft.Icons.VERIFIED_USER, size=15, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Text(
                    f"Gwarancja do {utils.formatuj_liczba(gw_km, 0)} km — "
                    + (f"zostało {utils.formatuj_liczba(zostalo, 0)} km" if zostalo > 0
                       else "limit kilometrów już przekroczony"),
                    size=utils.FS["caption"],
                    color=ft.Colors.ON_SURFACE_VARIANT if zostalo > 0 else ft.Colors.RED_700,
                    expand=True),
            ], spacing=6))

        return utils.karta_analizy(self._page, "Terminy i dokumenty", ft.Icons.SHIELD, wiersze)

    # ================= ZAKUP I WARTOŚĆ =================

    def _zakup_i_wartosc(self):
        m = self.metryki
        waluta = utils.symbol_waluty()

        if not m.get("cena_zakupu") and not m.get("data_zakupu"):
            return utils.karta_analizy(
                self._page, "Zakup i wartość", ft.Icons.SELL,
                [ft.Text(
                    "Podaj datę i cenę zakupu oraz dzisiejszą szacowaną wartość, a policzę "
                    "pełny koszt posiadania — razem z utratą wartości, czyli największym "
                    "kosztem auta, którego nie widać w żadnym wpisie.",
                    size=utils.FS["body"], color=ft.Colors.ON_SURFACE_VARIANT),
                 ft.FilledTonalButton("Uzupełnij dane zakupu", icon=ft.Icons.SELL,
                                      on_click=lambda e: utils.przejdz(
                                          self._page, f"/auto/edytuj/{self.state.auto_id}"))],
                ft.Colors.AMBER_800,
            )

        wiersze = []
        if m.get("data_zakupu"):
            opis = [f"kupione {m['data_zakupu']}"]
            if m.get("lata_posiadania"):
                opis.append(f"masz je {utils.formatuj_liczba(m['lata_posiadania'], 1)} roku")
            if m.get("km_u_ciebie"):
                opis.append(f"przejechałeś {utils.formatuj_liczba(m['km_u_ciebie'], 0)} km")
            wiersze.append(ft.Text(" • ".join(opis), size=utils.FS["body"],
                                   color=ft.Colors.ON_SURFACE_VARIANT))

        def wiersz_kwoty(etykieta, wartosc, kolor=ft.Colors.ON_SURFACE, sufiks=None):
            return ft.Row([
                ft.Text(etykieta, size=utils.FS["body"], color=ft.Colors.ON_SURFACE_VARIANT,
                        expand=True),
                ft.Text(wartosc, size=utils.FS["body_strong"], weight="bold", color=kolor),
                ft.Text(sufiks or "", size=utils.FS["caption"],
                        color=ft.Colors.ON_SURFACE_VARIANT, visible=bool(sufiks)),
            ], spacing=6)

        if m.get("cena_zakupu"):
            wiersze.append(wiersz_kwoty("Cena zakupu",
                                        f"{utils.formatuj_liczba(m['cena_zakupu'])} {waluta}"))
        if m.get("wartosc_szacowana") is not None:
            wiersze.append(wiersz_kwoty(
                "Wartość dziś", f"{utils.formatuj_liczba(m['wartosc_szacowana'])} {waluta}",
                sufiks=(f"{utils.formatuj_liczba(m['procent_wartosci'], 0)}% ceny"
                        if m.get("procent_wartosci") else None)))
        if m.get("utrata_wartosci") is not None:
            wiersze.append(wiersz_kwoty(
                "Utrata wartości", f"{utils.formatuj_liczba(m['utrata_wartosci'])} {waluta}",
                ft.Colors.RED_700,
                sufiks=(f"{utils.formatuj_liczba(m['utrata_rocznie'])} {waluta}/rok"
                        if m.get("utrata_rocznie") else None)))
        wiersze.append(wiersz_kwoty(
            "Wydatki na eksploatację", f"{utils.formatuj_liczba(m['wydatki_od_zakupu'])} {waluta}",
            sufiks="od zakupu" if m.get("data_zakupu") else "łącznie"))

        wiersze.append(ft.Divider(height=10))
        wiersze.append(wiersz_kwoty(
            "Koszt posiadania łącznie", f"{utils.formatuj_liczba(m['koszt_calkowity'])} {waluta}",
            ft.Colors.PRIMARY))
        if m.get("koszt_km_pelny"):
            wiersze.append(wiersz_kwoty(
                "Pełny koszt kilometra",
                f"{utils.formatuj_liczba(m['koszt_km_pelny'], 2)} {waluta}/km", ft.Colors.PRIMARY))
        if m.get("koszt_miesieczny"):
            wiersze.append(wiersz_kwoty(
                "Miesięcznie", f"{utils.formatuj_liczba(m['koszt_miesieczny'])} {waluta}",
                ft.Colors.PRIMARY))

        if m.get("koszt_km_pelny") and m.get("utrata_na_km"):
            wiersze.append(ft.Row([
                ft.Icon(ft.Icons.INFO_OUTLINE, size=14, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Text(
                    f"Z każdego kilometra {utils.formatuj_liczba(m['utrata_na_km'], 2)} {waluta} "
                    f"to sama utrata wartości — koszt, którego nie widać przy tankowaniu.",
                    size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
            ], spacing=6))

        return utils.karta_analizy(self._page, "Zakup i wartość", ft.Icons.SELL,
                                   wiersze, ft.Colors.AMBER_800)

    # ================= SPECYFIKACJA =================

    def _specyfikacja(self):
        d = self.dane
        w = lambda *a, **k: utils.wiersz_danych(self._page, *a, **k)

        wiersze = [
            w(ft.Icons.NUMBERS, "VIN", d.get("vin"), kopiowalne=True),
            w(ft.Icons.EVENT_AVAILABLE, "Pierwsza rejestracja", d.get("data_pierwszej_rejestracji")),
            w(ft.Icons.SPEED, "Pojemność silnika",
              f"{d['pojemnosc_silnika']} cm³" if d.get("pojemnosc_silnika") else None),
            w(ft.Icons.BOLT, "Moc", f"{d['moc_silnika']} KM" if d.get("moc_silnika") else None),
            w(ft.Icons.SETTINGS_INPUT_COMPONENT, "Skrzynia biegów", d.get("skrzynia_biegow")),
            w(ft.Icons.DIRECTIONS_CAR, "Nadwozie", d.get("nadwozie")),
        ]
        if d.get("pojemnosc_baku"):
            wiersze.append(w(ft.Icons.LOCAL_GAS_STATION, "Pojemność baku", f"{d['pojemnosc_baku']} l"))
        if d.get("pojemnosc_baterii"):
            wiersze.append(w(ft.Icons.BATTERY_CHARGING_FULL, "Bateria", f"{d['pojemnosc_baterii']} kWh"))
        if d.get("zasieg_ev"):
            wiersze.append(w(ft.Icons.ROUTE, "Zasięg katalogowy", f"{d['zasieg_ev']} km"))
        if d.get("typ_zlacza_ev"):
            wiersze.append(w(ft.Icons.EV_STATION, "Złącze ładowania", d.get("typ_zlacza_ev")))

        return utils.karta_analizy(self._page, "Specyfikacja", ft.Icons.SETTINGS,
                                   wiersze, ft.Colors.BLUE_GREY_700)

    # ================= UBEZPIECZENIE =================

    def _ubezpieczenie(self):
        d = self.dane
        w = lambda *a, **k: utils.wiersz_danych(self._page, *a, **k)

        if not any(d.get(k) for k in ("ubezpieczyciel", "nr_polisy", "telefon_assistance", "skladka_roczna")):
            return utils.karta_analizy(
                self._page, "Ubezpieczenie i pomoc", ft.Icons.SUPPORT_AGENT,
                [ft.Text("Numer polisy i telefon do assistance to dane, których szuka się "
                         "w najgorszym możliwym momencie. Wpisz je raz, a będą pod ręką "
                         "— także dla drugiej osoby, jeśli auto jest współdzielone.",
                         size=utils.FS["body"], color=ft.Colors.ON_SURFACE_VARIANT),
                 ft.FilledTonalButton("Uzupełnij ubezpieczenie", icon=ft.Icons.SHIELD,
                                      on_click=lambda e: utils.przejdz(
                                          self._page, f"/auto/edytuj/{self.state.auto_id}"))],
                ft.Colors.TEAL_700,
            )

        wiersze = [
            w(ft.Icons.BUSINESS, "Ubezpieczyciel", d.get("ubezpieczyciel")),
            w(ft.Icons.DESCRIPTION, "Numer polisy", d.get("nr_polisy"), kopiowalne=True),
        ]
        if d.get("skladka_roczna"):
            wiersze.append(w(ft.Icons.PAYMENTS, "Składka roczna",
                             f"{utils.formatuj_liczba(d['skladka_roczna'])} {utils.symbol_waluty()}"))
        wiersze.append(w(ft.Icons.SUPPORT_AGENT, "Telefon do assistance",
                         d.get("telefon_assistance"), telefon=True, kopiowalne=True))

        return utils.karta_analizy(self._page, "Ubezpieczenie i pomoc", ft.Icons.SUPPORT_AGENT,
                                   wiersze, ft.Colors.TEAL_700)

    # ================= ŚCIĄGAWKA =================

    def _sciagawka(self):
        d = self.dane
        w = lambda *a, **k: utils.wiersz_danych(self._page, *a, **k)

        def polacz(*wartosci):
            czesci = [str(x) for x in wartosci if x]
            return " / ".join(czesci) if czesci else None

        wiersze = [
            w(ft.Icons.WATER_DROP, "Wycieraczki (przód / tył)",
              polacz(d.get("wycieraczki_przod"), d.get("wycieraczki_tyl"))),
            w(ft.Icons.AIR, "Ciśnienie opon (przód / tył)",
              polacz(d.get("cisnienie_przod"), d.get("cisnienie_tyl"))),
            w(ft.Icons.OPACITY, "Olej silnikowy",
              polacz(d.get("olej_typ"), d.get("olej_pojemnosc"))),
            w(ft.Icons.BATTERY_FULL, "Akumulator", d.get("akumulator")),
            w(ft.Icons.LIGHTBULB, "Żarówki (mijania / drogowe)",
              polacz(d.get("zarowki_mijania"), d.get("zarowki_drogowe"))),
            w(ft.Icons.FORMAT_PAINT, "Kod lakieru", d.get("kod_lakieru"), kopiowalne=True,
              podpowiedz="przyda się przy zaprawce i lakierowaniu"),
            w(ft.Icons.TIRE_REPAIR, "Rozmiar opon", d.get("rozmiar_opon"), kopiowalne=True),
            w(ft.Icons.ALBUM, "Felgi", d.get("rozmiar_felg")),
            w(ft.Icons.SETTINGS, "Rozstaw śrub", d.get("rozstaw_srub")),
            w(ft.Icons.BUILD_CIRCLE, "Moment dokręcania kół", d.get("moment_dokrecania"),
              podpowiedz="sprawdź po 50 km od wymiany kół"),
        ]

        return utils.karta_analizy(self._page, "Ściągawka do sklepu i warsztatu",
                                   ft.Icons.SHOPPING_CART, wiersze, ft.Colors.ORANGE_700)

    # ================= NOTATKI =================

    def _notatki(self):
        tekst = str(self.dane.get("notatki") or "").strip()
        return utils.karta_analizy(
            self._page, "Notatki o pojeździe", ft.Icons.NOTES,
            [ft.Text(tekst if tekst else "Brak notatek. Miejsce na to, co nie mieści się "
                                        "w żadnym polu — historia auta, znane usterki, ustalenia z warsztatem.",
                     size=utils.FS["body"], italic=not bool(tekst),
                     color=ft.Colors.ON_SURFACE if tekst else ft.Colors.ON_SURFACE_VARIANT,
                     selectable=bool(tekst))],
            ft.Colors.BLUE_GREY_700,
        )

    # ================= AKCJE =================

    def _akcje(self):
        return ft.Column([
            ft.FilledButton("Edytuj dane pojazdu", icon=ft.Icons.EDIT, height=46, width=10000,
                            on_click=lambda e: utils.przejdz(
                                self._page, f"/auto/edytuj/{self.state.auto_id}")),
            ft.Row([
                ft.FilledTonalButton("Paszport PDF", icon=ft.Icons.PICTURE_AS_PDF, expand=True,
                                     on_click=lambda e: utils.przejdz(self._page, "/eksport")),
                ft.FilledTonalButton("Rok w pigułce", icon=ft.Icons.AUTO_AWESOME, expand=True,
                                     on_click=lambda e: utils.przejdz(self._page, "/rok")),
            ], spacing=10),
        ], spacing=10)
