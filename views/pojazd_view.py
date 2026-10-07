import flet as ft

import db
import sync
import utils


class PojazdView(ft.View):
    """Pełna karta pojazdu w kolejności „po co się wchodzi”: tożsamość, liczby
    całościowe, terminy, rachunek posiadania, dane techniczne, ubezpieczenie, ściągawka."""

    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state
        self.j = utils.jednostka_dystansu()  # km albo mi — raz na ekran

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

        # Paski terminów wypełniają się przy wejściu od zera, kaskadą — dopiero
        # ruch pokazuje, GDZIE każdy z nich się zatrzymał. Raz na uruchomienie
        # aplikacji: przy dziesiątym wejściu ta sama animacja byłaby już tylko
        # zwłoką przed odczytem.
        self.scena = utils.ScenaWejscia(
            wlaczona=db.czy_animacje_interfejsu()
            and utils.pierwsze_pokazanie(state, "pojazd", state.auto_id),
            kaskada=True,
        )

        self.dane = db.pobierz_dane_pojazdu(self.state.auto_id) or {}
        self.metryki = db.pobierz_metryki_pojazdu(self.state.auto_id, self.dane) or {}
        self.terminy = db.terminy_pojazdu(self.state.auto_id, self.dane)
        self.wspolny_id, _ = sync.czy_udostepniony(self.state.auto_id)
        # Podgląd czyta notatkę o ofercie OC/AC, ale nie ma jak jej zmienić.
        self.podglad = db.czy_tylko_podglad(self.state.auto_id)
        self.oferta = db.oferta_oc_ac_pojazdu(self.dane)

        super().__init__(
            route="/pojazd", padding=15, spacing=15, appbar=appbar,
            controls=self._elementy(),
            scroll=ft.ScrollMode.AUTO,
        )
        self.scena.uruchom(page)

    def _elementy(self):
        elementy = [
            self._hero(),
            self._metryki(),
            self._terminy(),
            self._gwarancje_napraw(),
            self._zakup_i_wartosc(),
            self._leasing_i_kredyt(),
            self._specyfikacja(),
            self._ubezpieczenie(),
            self._sciagawka(),
            self._notatki(),
            self._akcje(),
            utils.dol_bezpieczny(10),
        ]
        return [e for e in elementy if e is not None]

    def odswiez_w_miejscu(self):
        """Przelicza kartę po zmianie, którą zrobiono bez wychodzenia z ekranu
        (dziś: notatka „najlepsza oferta OC/AC” z okienka). Ten sam widok, więc
        pozycja przewijania zostaje; paski nie grają od nowa, bo to nie jest
        wejście na ekran."""
        self.dane = db.pobierz_dane_pojazdu(self.state.auto_id) or {}
        self.oferta = db.oferta_oc_ac_pojazdu(self.dane)
        self.terminy = db.terminy_pojazdu(self.state.auto_id, self.dane)
        self.scena = utils.ScenaWejscia(wlaczona=False, kaskada=True)
        self.controls = self._elementy()
        self.update()

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
            padding=utils.SPACING["lg"],
            **utils.powierzchnia(self._page, "karta", cien="md"),
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
                            f"{utils.formatuj_dystans(db.NORMA_PRZEBIEGU_ROCZNEGO, 0, self.j)}/rok")
            kolor_tempa = (utils.KOLOR_STATUS["warning"] if procent > 150
                           else utils.KOLOR_STATUS["ok"] if procent < 70 else ft.Colors.PRIMARY)
        else:
            podpis_tempa, kolor_tempa = "za mało danych", ft.Colors.ON_SURFACE_VARIANT

        kondycja = m.get("kondycja")
        _, ikona_kond, etykieta_kond = utils.wskaznik_kondycji(kondycja)

        return ft.Column([
            ft.Row([
                kafel(ft.Icons.SPEED, "Przebieg",
                      utils.formatuj_dystans(m.get('przebieg') or 0, 0, self.j),
                      "dotknij: historia licznika", ft.Colors.PRIMARY,
                      lambda e: utils.przejdz(self._page, "/przebieg")),
                kafel(ft.Icons.CAKE, "Wiek", wiek, podpis_wieku, ft.Colors.BLUE_GREY_700),
            ], spacing=10),
            ft.Row([
                kafel(ft.Icons.SPEED_OUTLINED, "Rocznie",
                      utils.formatuj_dystans(m['przebieg_roczny'], 0, self.j)
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
            zawartosc = [
                ft.Text("Nie masz jeszcze wpisanych żadnych dat — OC, przeglądu, AC ani "
                        "assistance. To one napędzają powiadomienia i kondycję pojazdu.",
                        size=utils.FS["body"], color=ft.Colors.ON_SURFACE_VARIANT),
                ft.FilledTonalButton("Uzupełnij daty", icon=ft.Icons.EVENT,
                                     on_click=lambda e: utils.przejdz(
                                         self._page, f"/auto/edytuj/{self.state.auto_id}")),
            ]
            # Zapisana wcześniej notatka nie znika razem z datami polis.
            wiersz_oferty = self._wiersz_oferty(jest_polisa=False)
            if wiersz_oferty is not None:
                zawartosc.append(wiersz_oferty)
            return utils.karta_analizy(self._page, "Terminy i dokumenty", ft.Icons.SHIELD, zawartosc)

        wiersze = []
        oferta_postawiona = False
        for t in self.terminy:
            wiersze.append(utils.pasek_terminu(self._page, t, scena=self.scena))
            # Notatka „najlepsza oferta OC/AC” stoi tuż pod pierwszym terminem
            # polisy (OC albo AC — którego dotyczy bliższa data), nie na końcu
            # karty: ma być widać razem z terminem, przy którym się ją czyta.
            if not oferta_postawiona and t["klucz"] in db.KLUCZE_TERMINOW_Z_OFERTA:
                oferta_postawiona = True
                wiersz_oferty = self._wiersz_oferty(jest_polisa=True)
                if wiersz_oferty is not None:
                    wiersze.append(wiersz_oferty)
        if not oferta_postawiona:
            wiersz_oferty = self._wiersz_oferty(jest_polisa=False)
            if wiersz_oferty is not None:
                wiersze.append(wiersz_oferty)
        gw_km = self.dane.get("gwarancja_przebieg")
        if gw_km:
            zostalo = int(gw_km) - (self.metryki.get("przebieg") or 0)
            wiersze.append(ft.Row([
                ft.Icon(ft.Icons.VERIFIED_USER, size=15, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Text(
                    f"Gwarancja do {utils.formatuj_dystans(gw_km, 0, self.j)} — "
                    + (f"zostało {utils.formatuj_dystans(zostalo, 0, self.j)}" if zostalo > 0
                       else f"limit {db.slowo_dystansu('dopelniacz_pelny', self.j)} już przekroczony"),
                    size=utils.FS["caption"],
                    color=ft.Colors.ON_SURFACE_VARIANT if zostalo > 0 else utils.KOLOR_STATUS["critical"],
                    expand=True),
            ], spacing=6))

        return utils.karta_analizy(self._page, "Terminy i dokumenty", ft.Icons.SHIELD, wiersze)

    # ================= NAJLEPSZA OFERTA OC/AC =================

    def _wiersz_oferty(self, jest_polisa):
        """Notatka „najlepsza oferta OC/AC” albo None. Z notatką — wiersz danych
        (kopiowanie, data) i ołówek do szybkiej zmiany; bez niej zachęta tylko przy
        polisie z terminem i tylko dla mogących zapisać."""
        mozna_zmieniac = not self.podglad
        if self.oferta:
            wiersz = utils.wiersz_danych(
                self._page, ft.Icons.REQUEST_QUOTE, db.ETYKIETA_OFERTY_OC_AC, self.oferta["tekst"],
                kopiowalne=True,
                podpowiedz=f"Zapisano {self.oferta['data']}" if self.oferta["data"] else None)
            if mozna_zmieniac:
                wiersz.controls.append(ft.IconButton(
                    ft.Icons.EDIT, icon_size=16, icon_color=ft.Colors.ON_SURFACE_VARIANT,
                    tooltip="Zmień notatkę", on_click=self._edytuj_oferte,
                    style=ft.ButtonStyle(padding=0), width=34, height=34))
            return wiersz
        if mozna_zmieniac and jest_polisa:
            return ft.Container(
                ink=True, on_click=self._edytuj_oferte, border_radius=utils.RADIUS["sm"],
                tooltip="Zapisz cenę i towarzystwo najlepszej oferty",
                padding=ft.Padding.symmetric(vertical=utils.SPACING["xs"]),
                content=ft.Row([
                    ft.Icon(ft.Icons.REQUEST_QUOTE, size=18, color=ft.Colors.ON_SURFACE_VARIANT),
                    utils.etykieta("Zapisz najlepszą ofertę OC/AC", expand=True),
                    ft.Icon(ft.Icons.ADD, size=16, color=ft.Colors.ON_SURFACE_VARIANT),
                ], spacing=utils.SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            )
        return None

    def _edytuj_oferte(self, e=None):
        """Okienko do zmiany notatki. Zapis idzie przez db.zapisz_oferte_oc_ac
        (data zapisu zmienia się tylko razem z tekstem), potem cicho do chmury,
        jeśli auto jest współdzielone — druga osoba nie czeka na ręczną
        synchronizację — i odświeżenie karty w miejscu."""
        pole = ft.TextField(
            label=db.ETYKIETA_OFERTY_OC_AC, value=self.oferta["tekst"] if self.oferta else "",
            hint_text="np. Warta — 1 240 zł (OC + AC)", multiline=True, min_lines=2, max_lines=5,
            max_length=db.MAKS_DLUGOSC_OFERTY_OC_AC, autofocus=True, **utils.styl_pola(page=self._page))

        def zapisz(e2):
            zmieniono = db.zapisz_oferte_oc_ac(self.state.auto_id, pole.value)
            utils.zamknij_dialog(self._page, dlg)
            if not zmieniono:
                return
            utils.wypchnij_w_tle(self._page, self.state.auto_id, "oferta")
            utils.odswiez_ekran(self._page)
            utils.pokaz_komunikat(self._page, "Zapisano notatkę o ofercie OC/AC")

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.REQUEST_QUOTE, color=ft.Colors.PRIMARY),
                ft.Text(db.ETYKIETA_OFERTY_OC_AC, weight="bold", size=16, expand=True),
            ], spacing=8),
            content=ft.Column([
                utils.etykieta("Cena i towarzystwo najlepszej oferty, jaką udało się znaleźć. "
                               "Zostaje po odnowieniu polisy — za rok będzie punktem wyjścia."),
                pole,
            ], tight=True, spacing=10),
            actions=[
                ft.TextButton("Anuluj", on_click=lambda e2: utils.zamknij_dialog(self._page, dlg)),
                ft.Button("Zapisz", on_click=zapisz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY),
            ],
        )
        utils.otworz_dialog(self._page, dlg)

    # ================= GWARANCJE NAPRAW =================

    def _gwarancje_napraw(self):
        """Trwające gwarancje na części — obok gwarancji całego auta z terminów.
        Z ostatniej wymiany każdego podzespołu, od kończącej się najwcześniej;
        dotknięcie prowadzi do historii podzespołu. Bez żadnej — bez sekcji:
        pusta karta tylko odsuwałaby resztę w dół."""
        gwarancje = db.gwarancje_pojazdu(self.state.auto_id)
        if not gwarancje:
            return None
        wiersze = [
            utils.pozycja_gwarancji(
                g, self.j, on_click=lambda e, zid=g["zadanie_id"]: utils.przejdz(self._page, f"/historia/{zid}"))
            for g in gwarancje
        ]
        return utils.karta_analizy(self._page, "Gwarancje na naprawy", ft.Icons.GPP_GOOD, wiersze)

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
                ft.Colors.AMBER_800,  # paleta: tożsamość — akcent sekcji
            )

        wiersze = []
        if m.get("data_zakupu"):
            opis = [f"kupione {m['data_zakupu']}"]
            if m.get("lata_posiadania"):
                opis.append(f"{'miałeś' if m.get('zamkniete_na') else 'masz'} je "
                            f"{utils.formatuj_liczba(m['lata_posiadania'], 1)} roku")
            if m.get("km_u_ciebie"):
                opis.append(f"przejechałeś {utils.formatuj_dystans(m['km_u_ciebie'], 0, self.j)}")
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
                "Cena sprzedaży" if m.get("zamkniete_na") else "Wartość dziś",
                f"{utils.formatuj_liczba(m['wartosc_szacowana'])} {waluta}",
                sufiks=(f"{utils.formatuj_liczba(m['procent_wartosci'], 0)}% ceny"
                        if m.get("procent_wartosci") else None)))
        if m.get("utrata_wartosci") is not None:
            wiersze.append(wiersz_kwoty(
                "Utrata wartości", f"{utils.formatuj_liczba(m['utrata_wartosci'])} {waluta}",
                utils.KOLOR_STATUS["cost"],
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
                f"Pełny koszt {db.slowo_dystansu('dopelniacz_lp', self.j)}",
                utils.formatuj_na_dystans(m['koszt_km_pelny'], f"{waluta}/", 2, self.j), ft.Colors.PRIMARY))
        if m.get("koszt_miesieczny"):
            wiersze.append(wiersz_kwoty(
                "Miesięcznie", f"{utils.formatuj_liczba(m['koszt_miesieczny'])} {waluta}",
                ft.Colors.PRIMARY))

        if m.get("zamkniete_na"):
            wiersze.append(ft.Row([
                ft.Icon(ft.Icons.LOCK_CLOCK, size=14, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Text(
                    f"Rachunek zamknięty {m['zamkniete_na']} — po sprzedaży wydatki i czas "
                    "posiadania przestają rosnąć, więc te liczby już się nie zmienią.",
                    size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
            ], spacing=6))

        if m.get("koszt_km_pelny") and m.get("utrata_na_km"):
            wiersze.append(ft.Row([
                ft.Icon(ft.Icons.INFO_OUTLINE, size=14, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Text(
                    f"{'Z każdego kilometra' if self.j == 'km' else 'Z każdej mili'} "
                    f"{utils.formatuj_liczba(db.na_jednostke_dystansu(m['utrata_na_km'], self.j), 2)} {waluta} "
                    f"to sama utrata wartości — koszt, którego nie widać przy tankowaniu.",
                    size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
            ], spacing=6))

        return utils.karta_analizy(self._page, "Zakup i wartość", ft.Icons.SELL,
                                   wiersze, ft.Colors.AMBER_800)  # paleta: tożsamość — akcent sekcji

    # ================= LEASING I KREDYT =================

    def _leasing_i_kredyt(self):
        """Umowy rat w jednej karcie (db.podsumowanie_rat): do spłaty, kapitał, odsetki,
        ostatnia rata. Auto bez umowy tej karty nie ma."""
        stan = db.podsumowanie_rat(self.state.auto_id)
        if not stan:
            return None
        waluta = utils.symbol_waluty()

        def kwota(wartosc):
            return f"{utils.formatuj_liczba(wartosc)} {waluta}"

        def wiersz(etykieta, wartosc, kolor=None, sufiks=None):
            tresc = [
                ft.Text(etykieta, size=utils.FS["body"], color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                ft.Text(wartosc, size=utils.FS["body_strong"], weight="bold", color=kolor or ft.Colors.ON_SURFACE),
            ]
            if sufiks:
                tresc.append(ft.Text(sufiks, size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT))
            return ft.Row(tresc, spacing=6)

        def notka(ikona, tekst, kolor=ft.Colors.ON_SURFACE_VARIANT):
            return ft.Row([
                ft.Icon(ikona, size=14, color=kolor),
                ft.Text(tekst, size=utils.FS["caption"], color=kolor, expand=True),
            ], spacing=6)

        wiersze = []
        if not stan["trwajace"]:
            if stan["niekompletne"]:
                wiersze.append(notka(ft.Icons.EDIT_NOTE, "Umowa czeka na uzupełnienie — bez liczby rat i terminu "
                                     "pierwszej raty nie ma harmonogramu.", utils.KOLOR_STATUS["warning"]))
            else:
                wiersze.append(notka(ft.Icons.TASK_ALT, "Wszystkie raty i wykup zapłacone — auto nie ma już "
                                     "długu.", utils.KOLOR_STATUS["ok"]))
        else:
            zostalo = stan["liczba_rat"] - stan["zaplacone_raty"]
            wiersze.append(wiersz("Do spłaty", kwota(stan["do_splaty"]), ft.Colors.PRIMARY,
                                  sufiks=f"{db.liczba_z_odmiana(zostalo, 'rata', 'raty', 'rat')}"
                                         f"{' i wykup' if self._czy_wykup(stan) else ''}"))
            if stan["kapital_do_splaty"] is not None:
                wiersze.append(wiersz("Kapitał do spłaty", kwota(stan["kapital_do_splaty"])))
                wiersze.append(wiersz("Odsetki do zapłaty", kwota(stan["odsetki_do_zaplaty"]),
                                      utils.KOLOR_STATUS["cost"]))
            wiersze.append(wiersz("Ostatnia rata", stan["data_konca"].strftime("%d.%m.%Y")))
            if stan["po_terminie"]:
                wiersze.append(notka(ft.Icons.ERROR_OUTLINE,
                                     f"{db.liczba_z_odmiana(stan['po_terminie'], 'płatność', 'płatności', 'płatności')} "
                                     "po terminie — odhacz je w harmonogramie.", utils.KOLOR_STATUS["critical"]))
            wartosc = None if self.metryki.get("zamkniete_na") else self.metryki.get("wartosc_szacowana")
            if wartosc is not None and stan["kapital_do_splaty"] is not None:
                po_splacie = wartosc - stan["kapital_do_splaty"]
                wiersze.append(ft.Divider(height=10))
                wiersze.append(wiersz("Wartość dziś minus kapitał", kwota(po_splacie),
                                      utils.KOLOR_STATUS["ok" if po_splacie >= 0 else "critical"]))
                wiersze.append(notka(ft.Icons.INFO_OUTLINE,
                                     "Tyle zostaje po sprzedaży auta i spłacie umowy (bez opłat za wcześniejszą "
                                     "spłatę) — z tym idzie się po następne auto."))
            elif stan["kapital_do_splaty"] is not None:
                wiersze.append(notka(ft.Icons.INFO_OUTLINE,
                                     "Wpisz dzisiejszą wartość auta, a policzę, ile zostanie po sprzedaży "
                                     "i spłacie umowy."))
        wiersze.append(ft.TextButton("Harmonogram rat", icon=ft.Icons.TABLE_ROWS,
                                     on_click=lambda e: utils.przejdz(self._page, "/raty")))
        return utils.karta_analizy(self._page, "Leasing i kredyt", ft.Icons.ACCOUNT_BALANCE, wiersze)

    @staticmethod
    def _czy_wykup(stan):
        """Czy któraś trwająca umowa ma jeszcze niezapłacony wykup."""
        return any(u["harmonogram"]["wykup"] and not u["harmonogram"]["wykup_zaplacony"]
                   and not u["harmonogram"]["zakonczona"] for u in stan["umowy"])

    # ================= SPECYFIKACJA =================

    def _specyfikacja(self):
        d = self.dane
        w = lambda *a, **k: utils.wiersz_danych(self._page, *a, **k)

        wiersze = [
            w(ft.Icons.NUMBERS, "VIN", d.get("vin"), kopiowalne=True),
            w(ft.Icons.EVENT_AVAILABLE, "Pierwsza rejestracja", d.get("data_pierwszej_rejestracji"),
              kopiowalne=True),
            self._przycisk_cepik(),
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
            # Zasięg to pole tekstowe w km („380 (WLTP)”): w milach pokazujemy
            # przeliczoną liczbę, a tekst bez liczby — tak, jak go wpisano.
            liczba = db._liczba_lub_none(d["zasieg_ev"])
            wiersze.append(w(ft.Icons.ROUTE, "Zasięg katalogowy",
                             f"{d['zasieg_ev']} km" if self.j == "km" or not liczba
                             else utils.formatuj_dystans(liczba, 0, self.j)))
        if d.get("typ_zlacza_ev"):
            wiersze.append(w(ft.Icons.EV_STATION, "Złącze ładowania", d.get("typ_zlacza_ev")))

        return utils.karta_analizy(self._page, "Specyfikacja", ft.Icons.SETTINGS,
                                   wiersze, ft.Colors.BLUE_GREY_700)

    # ================= SPRAWDŹ W CEPiK =================

    def _przycisk_cepik(self):
        """Pod VIN-em i datą pierwszej rejestracji, bo z nich (i z tablicy)
        korzysta. Stoi także przy brakach — okienko powie, czego brakuje.
        Podpis obok przycisku, a na wąskim ekranie pod nim — adres w jednym
        kawałku, bez łamania w pół słowa."""
        return ft.Row([
            ft.FilledTonalButton("Sprawdź w CEPiK", icon=ft.Icons.MANAGE_SEARCH,
                                 on_click=self._sprawdz_w_cepik),
            utils.podpis("historiapojazdu.gov.pl, bezpłatnie"),
        ], wrap=True, spacing=utils.SPACING["sm"], run_spacing=utils.SPACING["xs"],
            vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def _sprawdz_w_cepik(self, e=None):
        """Okienko-ściągawka do Historii Pojazdu: trzy wartości w kolejności formularza,
        dotknięcie kopiuje, następna wyróżniona; zostaje otwarte pod przeglądarką. Przy
        komplecie numer rejestracyjny od razu do schowka i otwarcie strony; przy braku
        strona się nie otwiera."""
        pola = db.pola_historii_pojazdu(self.dane)
        skopiowane = set()
        lista = ft.Column(spacing=utils.SPACING["xs"], tight=True)

        def nastepne():
            return next((p["klucz"] for p in pola if p["wartosc"] and p["klucz"] not in skopiowane), None)

        def zbuduj_liste():
            kolejne = nastepne()
            lista.controls = [self._wiersz_cepik(nr, p, p["klucz"] in skopiowane, p["klucz"] == kolejne, kopiuj)
                              for nr, p in enumerate(pola, start=1)]

        def kopiuj(pole, odswiez=True):
            utils.kopiuj_do_schowka(self._page, pole["wartosc"], f"Skopiowano: {pole['etykieta']}")
            skopiowane.add(pole["klucz"])
            zbuduj_liste()
            if odswiez:
                lista.update()

        def otworz(e2=None):
            kolejne = nastepne()
            if kolejne:
                kopiuj(next(p for p in pola if p["klucz"] == kolejne))
            utils.otworz_strone(self._page, db.ADRES_HISTORII_POJAZDU)

        def uzupelnij(e2=None):
            utils.zamknij_dialog(self._page, dlg)
            utils.przejdz(self._page, f"/auto/edytuj/{self.state.auto_id}")

        komplet = all(p["wartosc"] for p in pola)
        if komplet:
            kopiuj(pola[0], odswiez=False)
        else:
            zbuduj_liste()

        tresc = [
            utils.etykieta("Historia Pojazdu prosi o te trzy dane, w tej kolejności. "
                           "Dotknij wiersza, żeby skopiować, i wklej w przeglądarce."),
            lista,
        ]
        if not komplet:
            brak = [utils.podpis("Bez kompletu strona nie znajdzie auta.", expand=True)]
            if not self.podglad:
                brak.append(ft.TextButton("Uzupełnij", icon=ft.Icons.EDIT, on_click=uzupelnij))
            tresc.append(ft.Row(brak, spacing=utils.SPACING["sm"],
                                vertical_alignment=ft.CrossAxisAlignment.CENTER))
        if getattr(self._page, "platform", None) == ft.PagePlatform.ANDROID:
            tresc.append(utils.podpis("Tu wracaj przełączaniem aplikacji: „Wstecz” w przeglądarce "
                                      "zwykle zamyka kartę razem z tym, co już wpisano."))

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.MANAGE_SEARCH, color=ft.Colors.PRIMARY),
                ft.Text("Sprawdź w CEPiK", weight="bold", size=utils.FS["title"], expand=True),
            ], spacing=utils.SPACING["sm"]),
            content=ft.Column(tresc, tight=True, spacing=utils.SPACING["sm"]),
            actions=[
                ft.TextButton("Zamknij", on_click=lambda e2: utils.zamknij_dialog(self._page, dlg)),
                ft.Button("Otwórz stronę", icon=ft.Icons.OPEN_IN_NEW, on_click=otworz,
                          bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY),
            ],
        )
        utils.otworz_dialog(self._page, dlg)
        if komplet:
            utils.otworz_strone(self._page, db.ADRES_HISTORII_POJAZDU)

    def _wiersz_cepik(self, numer, pole, skopiowane, nastepne, kopiuj):
        """Wiersz okienka: numer pola w formularzu, etykieta, wartość. Ramką
        wyróżniony ten, który trzeba skopiować teraz; skopiowany dostaje
        ptaszek, brakujący — myślnik i nie reaguje na dotknięcie."""
        wartosc = pole["wartosc"]
        if wartosc:
            kolumna = [utils.etykieta(pole["etykieta"]), utils.wartosc(wartosc)]
            koniec = [ft.Icon(ft.Icons.CHECK_CIRCLE if skopiowane else ft.Icons.COPY, size=18,
                              color=utils.KOLOR_STATUS["ok"] if skopiowane
                              else ft.Colors.PRIMARY if nastepne else ft.Colors.ON_SURFACE_VARIANT)]
        else:
            kolumna = [utils.etykieta(pole["etykieta"]),
                       ft.Text("—", size=utils.FS["body_strong"], color=ft.Colors.ON_SURFACE_VARIANT),
                       utils.podpis("brak w danych pojazdu")]
            koniec = []

        znak = ft.Container(
            width=24, height=24, border_radius=utils.RADIUS["pill"], alignment=ft.Alignment.CENTER,
            bgcolor=ft.Colors.PRIMARY if nastepne else ft.Colors.with_opacity(0.10, ft.Colors.ON_SURFACE),
            content=ft.Text(str(numer), size=utils.FS["label"],
                            color=ft.Colors.ON_PRIMARY if nastepne else ft.Colors.ON_SURFACE),
        )
        return ft.Container(
            data=pole["klucz"],
            ink=bool(wartosc), on_click=(lambda e: kopiuj(pole)) if wartosc else None,
            tooltip=f"Kopiuj: {pole['etykieta']}" if wartosc else None,
            border_radius=utils.RADIUS["sm"],
            padding=ft.Padding.symmetric(horizontal=utils.SPACING["sm"], vertical=utils.SPACING["xs"]),
            bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.PRIMARY) if nastepne else None,
            border=ft.Border.all(1, ft.Colors.PRIMARY if nastepne else ft.Colors.TRANSPARENT),
            content=ft.Row([znak, ft.Column(kolumna, spacing=0, expand=True)] + koniec,
                           spacing=utils.SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )

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
              podpowiedz=f"sprawdź po {'50 km' if self.j == 'km' else '30 mi'} od wymiany kół"),
        ]

        return utils.karta_analizy(self._page, "Ściągawka do sklepu i warsztatu",
                                   ft.Icons.SHOPPING_CART, wiersze, ft.Colors.ORANGE_700)  # paleta: tożsamość — akcent sekcji

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
