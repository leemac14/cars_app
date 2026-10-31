"""Formularz wizyty w warsztacie wraz z pozycjami i częściami."""

import db
import flet as ft
import log
import utils
from date import na_iso
from datetime import datetime


# Pole szukania nad podzespołami — od tylu pozycji; krótszą listę widać od razu.
PROG_SZUKANIA_PODZESPOLOW = 8


class FormularzWizytyView(ft.View):
    def __init__(self, page: ft.Page, state, w_id=None, szkic_id=None):
        self._page = page
        self.state = state
        self.w_id = w_id

        d_val, wyk_val, not_val, podpiete = datetime.now().strftime("%d.%m.%Y"), "", "", set()
        # Licznik w km, jak w bazie; pole pokazuje go w jednostce z Ustawień.
        self.p_km = db.pobierz_aktualny_przebieg(self.state.auto_id) or None
        tagi_val = ""
        kat_val = "Letnie"
        ceny_zrodla = {}  # zadanie_id -> cena pozycji z edytowanej wizyty albo źródła duplikatu
        koszt_zrodla, robocizna_zrodla = None, None
        rodzaj_zrodla = None
        # Gwarancja wspólna wizyty siedzi w `wizyty` i przechodzi na pozycje,
        # które ją mają. Pozycja z inną to wyjątek ustawiony przy niej samej
        # (historia podzespołu → „Gwarancja tej pozycji”) — zapis wizyty go nie rusza.
        gwarancje_pozycji = []
        gwarancja_zrodla = (None, None)

        # Duplikat wizyty: ten sam wzorzec, co przy tankowaniu, wpisie i koszcie —
        # źródło zużywamy jednorazowo, żeby powrót do formularza nie skopiował
        # wizyty po raz drugi.
        duplikuj_id = getattr(state, "duplikuj_zrodlo_wizyta", None) if not w_id else None
        state.duplikuj_zrodlo_wizyta = None
        # Szkic z kolejki „do wpisania” (utils/szkice.py) — faktura z warsztatu.
        self.szkic = utils.szkic_do_formularza(state, szkic_id, w_id)
        if self.szkic:
            duplikuj_id = None
        zrodlo_id = w_id or duplikuj_id

        if zrodlo_id:
            with db.polacz_baze() as conn:
                c = conn.cursor()
                c.execute("SELECT data, przebieg, wykonawca, koszt_calkowity, notatki, tagi, koszt_robocizny, gwarancja_data, gwarancja_przebieg, rodzaj FROM wizyty WHERE id=?", (zrodlo_id,))
                w = c.fetchone()
                if w:
                    d_val, wyk_val, not_val = str(w[0] or ""), str(w[2] or ""), str(w[4] or "")
                    self.p_km = w[1] or None
                    koszt_zrodla, robocizna_zrodla = float(w[3] or 0.0), w[6]
                    tagi_val = str(w[5] or "")
                    rodzaj_zrodla = db.rodzaj_serwisu(w[9])
                c.execute("SELECT zadanie_id, kategoria, gwarancja_data, gwarancja_przebieg, cena FROM historia WHERE wizyta_id=? ORDER BY id", (zrodlo_id,))
                dane_h = c.fetchall()
                podpiete = {r[0] for r in dane_h}
                for r in dane_h:
                    if r[1]: kat_val = str(r[1])
                    if r[4]:
                        ceny_zrodla.setdefault(r[0], float(r[4]))
                gwarancje_pozycji = [db.klucz_gwarancji(r[2], r[3]) for r in dane_h]
                if w:
                    gwarancja_zrodla = db.klucz_gwarancji(w[7], w[8])
        self._gwarancja_wizyty = gwarancja_zrodla if w_id else (None, None)
        rozne_gwarancje = any(g != self._gwarancja_wizyty for g in gwarancje_pozycji) if w_id else False
        gwarancja = {"koniec": self._gwarancja_wizyty[0], "limit_km": self._gwarancja_wizyty[1],
                     "miesiace": None, "dystans_km": None}

        if duplikuj_id:
            # Data i przebieg opisują TAMTĄ wizytę, a paragon należy do niej —
            # kopiujemy wzorzec naprawy, nie zdarzenie. Zużycie magazynu również
            # nie jest przenoszone: stan mógł się zmienić, a ciche potrącenie
            # sztuk przy zapisie byłoby niespodzianką.
            d_val = datetime.now().strftime("%d.%m.%Y")
            p_zrodla = self.p_km
            self.p_km = db.pobierz_aktualny_przebieg(self.state.auto_id) or None
            # Gwarancja duplikatu: ten sam OKRES od dzisiejszej wizyty, nie stara data.
            gwarancja = db.przesun_gwarancje(*gwarancja_zrodla, w[0] if w else None, p_zrodla, d_val, self.p_km)

        if self.szkic:
            # Data migawki, zdjęcie jako załącznik, licznik (jeśli wpisany po
            # zdjęciu — inaczej zostaje bieżący) i opis jako notatka wizyty.
            d_val = self.szkic["data"]
            not_val = self.szkic["opis"] or ""
            if self.szkic["przebieg"]:
                self.p_km = self.szkic["przebieg"]

        # Części z magazynu doliczają się do kosztu wizyty, więc w polach kosztu
        # stoi sam rachunek warsztatu: od zapisanego kosztu odejmujemy to, co
        # doliczył magazyn — przy edycji tej wizyty i przy duplikacie innej.
        self.zuzycie = utils.ZuzycieMagazynu(page, self.state.auto_id, "wizyty", w_id)
        doliczone = 0.0
        if zrodlo_id:
            doliczone = (self.zuzycie.koszt_doliczony if w_id
                         else db.koszt_doliczony(db.pobierz_zuzycie_czesci("wizyty", duplikuj_id)))

        # Data i licznik wizyty niosą za sobą gwarancję ustawioną skrótem
        # („2 lata”, „+20 tys. km”) — patrz utils.PolaGwarancji.
        self.e_d = utils.pole_daty(page, "Data odebrania z warsztatu", d_val,
                                   po_zmianie=lambda: self.gwarancja.przy_zmianie_wymiany())
        self.e_p = ft.TextField(label=f"Przebieg podczas wizyty ({utils.jednostka_dystansu()})", value=db.wartosc_pola_dystansu(self.p_km), keyboard_type=ft.KeyboardType.NUMBER,
                                on_change=lambda e: self.gwarancja.przy_zmianie_wymiany(), **utils.styl_pola(page=page))
        self.gwarancja = utils.PolaGwarancji(
            page, gwarancja["koniec"], gwarancja["limit_km"],
            data_wymiany=lambda: self.e_d.value, przebieg_wymiany=self._przebieg_km,
            miesiace=gwarancja["miesiace"], dystans_km=gwarancja["dystans_km"],
            uwagi=(
                "Obejmuje wszystkie zaznaczone podzespoły. Inną dla jednej pozycji ustawisz "
                "w historii tego podzespołu: menu wpisu → „Gwarancja tej pozycji”.",
                "Część pozycji tej wizyty ma własną gwarancję — zapis wizyty jej nie zmieni."
                if rozne_gwarancje else None,
            ),
        )
        self.k_wykonawca, self.get_wykonawca = utils.komponent_wyboru_warsztatu(page, state, wyk_val)
        # Rodzaj wizyty przechodzi na jej pozycje. Edycja i duplikat z rodzajem trzymają
        # zapisany; nowa wizyta bierze podpowiedź z zaznaczonych podzespołów, dopóki
        # użytkownik nie wybierze sam.
        self.rodzaj = utils.PoleRodzajuSerwisu(page, rodzaj_zrodla if (w_id or rodzaj_zrodla)
                                               else db.domyslny_rodzaj_serwisu(podpiete))
        self.rodzaj.dotkniety = bool(w_id or rodzaj_zrodla)
        # Rachunek warsztatu osobno za robociznę i za części — albo jedną kwotą,
        # gdy rachunek podziału nie ma. Duplikat przenosi też podział.
        self.koszt = utils.KosztNaprawy(page, self.zuzycie, koszt_zrodla, robocizna_zrodla, doliczone)
        self.e_n = ft.TextField(label="Notatki i uwagi", value=not_val, multiline=True, min_lines=2, max_lines=4, **utils.styl_pola(page=page))
        # Paragon, faktura, zdjęcie wymienionej części; duplikat zaczyna bez plików.
        self.pliki = utils.PolaZalacznikow(page, "wizyty", w_id, szkic=self.szkic, auto_id=state.auto_id)
        self.k_tagi, self.get_tagi = utils.komponent_tagow(page, state, tagi_val)
        self.blad_czesci = ft.Text("", color=utils.KOLOR_STATUS["error"], size=13)
        # Wizyta bez podzespołu (diagnostyka, przegląd) zapisuje się drugim „Zapisz”.
        self._bez_pozycji_potwierdzone = False
        self.ceny_pozycji = {}    # zadanie_id -> pole „Cena tej pozycji”
        self.wiersze_czesci = {}  # zadanie_id -> wiersz: checkbox + pole ceny (widoczne po zaznaczeniu)
        self._ceny_poczatkowe = {}

        self.chk_czesci = []
        self.zadania_opon_ids = set()
        
        def odswiez_widocznosc_opon(e=None):
            if not self.rodzaj.dotkniety:
                self.rodzaj.podpowiedz(db.domyslny_rodzaj_serwisu([chk.data for chk in self.chk_czesci if chk.value]))
            czy_zaznaczono_opony = any(chk.value for chk in self.chk_czesci if chk.data in self.zadania_opon_ids)
            self.e_kat_wizyty.visible = czy_zaznaczono_opony
            self._po_zmianie_zaznaczenia()
            self._przerysuj(self.sekcja_czesci, "odświeżenie podzespołów wizyty")

        self._odswiez_widocznosc_opon = odswiez_widocznosc_opon

        with db.polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT id, nazwa, dotyczy_opon FROM zadania WHERE auto_id=? ORDER BY nazwa", (self.state.auto_id,))
            for z_i, z_n, z_opon in c.fetchall():
                chk = ft.Checkbox(label=str(z_n), value=(z_i in podpiete), data=z_i, on_change=odswiez_widocznosc_opon)
                self.chk_czesci.append(chk)
                self._dodaj_pole_ceny(chk, ceny_zrodla.get(z_i))
                if z_opon:
                    self.zadania_opon_ids.add(z_i)

        self.btn_pakiety = self._zbuduj_przycisk_pakietow()

        czy_na_start_opony = any(z_i in podpiete for z_i in self.zadania_opon_ids)
                    
        self.e_kat_wizyty = ft.Dropdown(
            label="Rodzaj opon",
            options=[ft.DropdownOption(key=k, text=k) for k in ("Letnie", "Zimowe", "Całoroczne")],
            value=kat_val,
            visible=czy_na_start_opony,
            **utils.styl_dropdown()
        )

        self._stan_poczatkowy = self._migawka_formularza()
        # Formularz ze szkicu wraca do kolejki — i przy anulowaniu, i po zapisie.
        self.powrot = "/do-wpisania" if self.szkic else "/wizyty"
        appbar = utils.zbuduj_pasek_z_powrotem(page, "Edycja wizyty" if w_id else "Nowa wizyta", self.powrot, on_save=self.zapisz, czy_zmieniono=self._czy_zmieniono)
        
        k1 = utils.karta_formularza(
            [self.rodzaj.kontrolka, self.e_d, self.e_p, self.k_wykonawca, *self.koszt.kontrolki(), self.e_n, ft.Text("Przypisane tagi:", size=13, weight="bold"), self.k_tagi],
            "Ogólne informacje", ft.Icons.HOME_REPAIR_SERVICE, domyslnie_otwarte=True, page=page
        )
        k1b = utils.karta_formularza([self.pliki.kontrolka], "Pliki (paragon, faktura, zdjęcie części)", ft.Icons.ATTACH_FILE,
                                     domyslnie_otwarte=bool(self.pliki.pozycje))
        self.sekcja_czesci = self._zbuduj_sekcje_czesci()
        k2 = utils.karta_formularza([self.sekcja_czesci], "Wymienione podzespoły", ft.Icons.CHECKLIST,
                                    domyslnie_otwarte=True, page=page)
        k_gwarancja = utils.karta_formularza(
            self.gwarancja.kontrolki(), "Gwarancja na naprawę", ft.Icons.GPP_GOOD,
            domyslnie_otwarte=bool(gwarancja["koniec"] or gwarancja["limit_km"]), page=page,
        )
        elementy = [k1, k1b, k2, k_gwarancja]
        if self.szkic:
            elementy.insert(0, utils.pasek_szkicu(page, self.szkic))

        if duplikuj_id:
            # Bez tego nie wiadomo, czemu lista części jest już odklikana, a pole
            # magazynu puste — a to akurat najłatwiej przeoczyć przy zapisie.
            elementy.insert(0, ft.Container(
                padding=ft.Padding(12, 10, 12, 10),
                border_radius=utils.RADIUS["sm"],
                bgcolor=ft.Colors.with_opacity(0.10, ft.Colors.PRIMARY),
                content=ft.Row([
                    ft.Icon(ft.Icons.CONTENT_COPY, size=16, color=ft.Colors.PRIMARY),
                    ft.Text(
                        "Duplikat wizyty: przeniesiono warsztat, koszt naprawy (bez części z magazynu), "
                        "notatki, tagi, rodzaj, zaznaczone podzespoły i okres gwarancji. Data i przebieg są "
                        "dzisiejsze, a zużycie z magazynu zaznacz ponownie — stan mógł się zmienić.",
                        size=11, color=ft.Colors.ON_SURFACE_VARIANT, expand=True,
                    ),
                ], spacing=8),
            ))

        k3 = self.zuzycie.karta()
        if k3:
            elementy.append(k3)

        elementy.append(utils.przyciski_akcji(page, "Zapisz wizytę", self.zapisz, self.powrot))

        super().__init__(
            route=(f"/wizyty/edytuj/{w_id}" if w_id
                   else utils.trasa_uzupelnienia("wizyta", self.szkic["id"]) if self.szkic
                   else "/wizyty/nowa"),
            padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO
        )

    # ================= PAKIETY SERWISOWE =================
    # Panel od dołu: karty pakietów ze składem jako chipy i przyciskami akcji; edytor
    # pokazuje WSZYSTKIE podzespoły pojazdu z checkboxami.

    def _zbuduj_przycisk_pakietow(self):
        return ft.Container(
            padding=ft.Padding(12, 9, 12, 9),
            border_radius=utils.RADIUS["md"],
            bgcolor=ft.Colors.with_opacity(0.10, ft.Colors.PRIMARY),
            ink=True,
            on_click=lambda e: self._okno_pakietow(),
            tooltip="Zaznacz od razu kilka podzespołów naraz",
            content=ft.Row([
                ft.Icon(ft.Icons.TUNE, size=18, color=ft.Colors.TEAL_700),
                ft.Column([
                    ft.Text("Pakiety serwisowe", weight="bold", size=utils.FS["body"], color=ft.Colors.TEAL_700),
                    ft.Text(self._podpis_przycisku_pakietow(), size=utils.FS["caption"],
                            color=ft.Colors.ON_SURFACE_VARIANT),
                ], spacing=0, tight=True, expand=True),
                ft.Icon(ft.Icons.CHEVRON_RIGHT, size=18, color=ft.Colors.ON_SURFACE_VARIANT),
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )

    def _podpis_przycisku_pakietow(self):
        wlasne = len(db.pobierz_pakiety_wlasne(self.state.auto_id))
        gotowe = len(db.pakiety_dla_pojazdu(self.state.auto_id))
        if not wlasne:
            return f"{gotowe} gotowych — zaznacz kilka podzespołów naraz"
        wlasne_opis = db.liczba_z_odmiana(wlasne, "własny", "własne", "własnych")
        return f"{gotowe} gotowych + {wlasne_opis}"

    def _odswiez_przycisk_pakietow(self):
        """Podpis przycisku niesie liczbę własnych pakietów, więc po każdym
        dodaniu/usunięciu trzeba go przerysować."""
        try:
            self.btn_pakiety.content.controls[1].controls[1].value = self._podpis_przycisku_pakietow()
            self.btn_pakiety.update()
        except Exception:
            pass

    def _chipy_skladu(self, pozycje):
        """Skład pakietu jako osobne chipy zamiast sklejonego 'a, b, c' —
        przy sześciu pozycjach jedna linijka tekstu była nie do przeczytania."""
        if not pozycje:
            return ft.Text("Pusty pakiet", size=utils.FS["caption"], italic=True,
                           color=ft.Colors.ON_SURFACE_VARIANT)
        # Podzespoły, których pojazd nie ma, oznaczamy wyblakłym chipem — od razu
        # widać, dlaczego pakiet zaznaczy mniej pozycji, niż obiecuje.
        posiadane = {db.bez_emoji(chk.label) for chk in self.chk_czesci}
        chipy = []
        for nazwa in pozycje:
            jest = db.bez_emoji(nazwa) in posiadane
            chipy.append(ft.Container(
                padding=ft.Padding(9, 4, 9, 4),
                border_radius=utils.RADIUS["pill"],
                bgcolor=ft.Colors.with_opacity(0.12 if jest else 0.05, ft.Colors.PRIMARY if jest else ft.Colors.ON_SURFACE),
                content=ft.Row([
                    ft.Icon(ft.Icons.CHECK if jest else ft.Icons.REMOVE, size=11,
                            color=ft.Colors.PRIMARY if jest else ft.Colors.ON_SURFACE_VARIANT),
                    ft.Text(str(nazwa), size=utils.FS["caption"],
                            color=ft.Colors.ON_SURFACE if jest else ft.Colors.ON_SURFACE_VARIANT),
                ], spacing=4, tight=True),
            ))
        return ft.Row(chipy, wrap=True, spacing=6, run_spacing=6)

    def _karta_pakietu(self, nazwa, pozycje, akcje):
        # Karta pakietu leży w arkuszu na dole, a nie na tle ekranu — blok.
        return ft.Container(
            padding=14,
            **utils.powierzchnia(self._page, "blok"),
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.BOOKMARK, size=16, color=ft.Colors.TEAL_700),
                    ft.Text(nazwa, weight="bold", size=utils.FS["body_strong"], expand=True),
                    ft.Text(f"{len(pozycje)} poz.", size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT),
                ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                self._chipy_skladu(pozycje),
                ft.Row(akcje, spacing=4, alignment=ft.MainAxisAlignment.END, wrap=True),
            ], spacing=10),
        )

    def _okno_pakietow(self):
        """Panel pakietów: własne u góry (bo to po nie sięga się najczęściej),
        gotowe niżej. Każda karta ma własne przyciski, więc żadna akcja nie
        wymaga już wchodzenia w osobne 'okno zarządzania'."""
        bs = ft.BottomSheet(ft.Container(padding=ft.Padding(16, 16, 16, 8), bgcolor=ft.Colors.SURFACE))

        def zamknij():
            utils.zamknij_dno(self._page, bs)

        def zastosuj(nazwa, pozycje):
            zamknij()
            self._zastosuj_pakiet(nazwa, pozycje)

        def edytuj(p_id, nazwa, pozycje):
            zamknij()
            self._okno_edytora_pakietu(p_id, nazwa, pozycje)

        def usun(p_id, nazwa):
            def wykonaj():
                db.usun_pakiet_wlasny(p_id)
                self._odswiez_przycisk_pakietow()
                utils.pokaz_komunikat(self._page, f"Usunięto pakiet „{nazwa}”.")
                self._okno_pakietow()
            zamknij()
            utils.potwierdz(self._page, "Usunąć pakiet?",
                            f"Pakiet „{nazwa}” zniknie z listy. Sama historia serwisowa i podzespoły zostają nietknięte.",
                            wykonaj)

        def przycisk_zastosuj(nazwa, pozycje):
            return ft.FilledTonalButton("Zastosuj", icon=ft.Icons.PLAYLIST_ADD_CHECK,
                                        on_click=lambda e, n=nazwa, p=pozycje: zastosuj(n, p))

        zawartosc = [
            ft.Row([
                ft.Icon(ft.Icons.TUNE, size=22, color=ft.Colors.PRIMARY),
                ft.Column([
                    ft.Text("Pakiety serwisowe", weight="bold", size=18, color=ft.Colors.PRIMARY),
                    ft.Text("Zaznaczają kilka podzespołów naraz w tej wizycie",
                            size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT),
                ], spacing=0, tight=True, expand=True),
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Divider(height=14),
        ]

        zaznaczone_teraz = [chk.label for chk in self.chk_czesci if chk.value]
        zawartosc.append(
            ft.Row([
                ft.OutlinedButton(
                    "Nowy pakiet", icon=ft.Icons.ADD,
                    on_click=lambda e: (zamknij(), self._okno_edytora_pakietu(None, "", zaznaczone_teraz)),
                ),
                ft.Text(
                    f"startuje z {len(zaznaczone_teraz)} zaznaczonymi" if zaznaczone_teraz else "startuje pusty",
                    size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT, expand=True,
                ),
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        )

        pakiety_wlasne = db.pobierz_pakiety_wlasne(self.state.auto_id)
        zawartosc.append(ft.Container(height=6))
        zawartosc.append(utils.etykieta("TWOJE PAKIETY"))
        if pakiety_wlasne:
            for p_id, nazwa, pozycje in pakiety_wlasne:
                zawartosc.append(self._karta_pakietu(nazwa, pozycje, [
                    ft.TextButton("Edytuj", icon=ft.Icons.EDIT,
                                  on_click=lambda e, i=p_id, n=nazwa, p=pozycje: edytuj(i, n, p)),
                    ft.TextButton("Usuń", icon=ft.Icons.DELETE,
                                  style=ft.ButtonStyle(color=utils.KOLOR_STATUS["destructive"]),
                                  on_click=lambda e, i=p_id, n=nazwa: usun(i, n)),
                    przycisk_zastosuj(nazwa, pozycje),
                ]))
        else:
            zawartosc.append(ft.Container(
                padding=ft.Padding(12, 14, 12, 14),
                **utils.powierzchnia(self._page, "blok"),
                content=ft.Text(
                    "Nie masz jeszcze własnych pakietów. Ułóż taki, jaki naprawdę robisz "
                    "u swojego mechanika — „Nowy pakiet” powyżej.",
                    size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
                ),
            ))

        # Gotowe zestawy przefiltrowane przez podzespoły TEGO pojazdu: zestaw
        # obiecujący olej autu elektrycznemu jest gorszy od braku zestawu,
        # a pakiet z rozrządem w aucie bez rozrządu zaznacza połowę siebie.
        pakiety_gotowe = db.pakiety_dla_pojazdu(self.state.auto_id)
        zawartosc.append(ft.Container(height=10))
        zawartosc.append(utils.etykieta("GOTOWE ZESTAWY"))
        if pakiety_gotowe:
            for nazwa, pozycje in pakiety_gotowe:
                zawartosc.append(self._karta_pakietu(nazwa, list(pozycje), [przycisk_zastosuj(nazwa, list(pozycje))]))
        else:
            zawartosc.append(ft.Container(
                padding=ft.Padding(12, 14, 12, 14),
                **utils.powierzchnia(self._page, "blok"),
                content=ft.Text(
                    "Żaden wbudowany zestaw nie pasuje do podzespołów tego pojazdu — "
                    "ułóż własny z tego, co naprawdę mu robisz.",
                    size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
                ),
            ))

        bs.content.content = ft.Column(zawartosc, tight=True, spacing=10)
        utils.otworz_dno(self._page, bs)

    def _okno_edytora_pakietu(self, p_id, nazwa, pozycje):
        """Edytor pakietu z PEŁNĄ listą podzespołów pojazdu. Wcześniej skład dało
        się podmienić tylko przez checkbox „zastąp obecnym zaznaczeniem”, czyli
        trzeba było wyjść, poklikać listę wizyty i wrócić."""
        pozycje = list(pozycje or [])
        wybrane_norm = {db.bez_emoji(x) for x in pozycje}

        e_nazwa = ft.TextField(
            label="Nazwa pakietu", value=nazwa or "",
            hint_text="np. Przegląd zimowy u Marka", **utils.styl_pola()
        )
        licznik = ft.Text("", size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT)
        checkboxy = []

        def przelicz(e=None):
            ile = sum(1 for chk in checkboxy if chk.value)
            licznik.value = f"Wybrano {ile} z {db.liczba_z_odmiana(len(checkboxy), 'podzespołu', 'podzespołów', 'podzespołów')}"
            try:
                licznik.update()
            except Exception:
                pass

        for chk_zrodlowy in self.chk_czesci:
            checkboxy.append(ft.Checkbox(
                label=chk_zrodlowy.label,
                value=db.bez_emoji(chk_zrodlowy.label) in wybrane_norm,
                on_change=przelicz,
            ))
        przelicz()

        # Pozycje pakietu, których ten pojazd nie ma na liście podzespołów —
        # zachowujemy je przy zapisie, żeby edycja nazwy nie okroiła składu
        # pakietu współdzielonego z innym autem.
        posiadane_norm = {db.bez_emoji(chk.label) for chk in self.chk_czesci}
        nieobecne = [x for x in pozycje if db.bez_emoji(x) not in posiadane_norm]

        def zaznacz_wszystkie(wartosc):
            def handler(e):
                for chk in checkboxy:
                    chk.value = wartosc
                przelicz()
                try:
                    lista_kontener.update()
                except Exception:
                    pass
            return handler

        lista_kontener = ft.Column(checkboxy, spacing=0, tight=True) if checkboxy else ft.Text(
            "Ten pojazd nie ma jeszcze żadnych podzespołów — dodaj je w zakładce Serwis.",
            size=utils.FS["caption"], italic=True, color=ft.Colors.ON_SURFACE_VARIANT,
        )

        bs = ft.BottomSheet(ft.Container(padding=ft.Padding(16, 16, 16, 8), bgcolor=ft.Colors.SURFACE))

        def zapisz(e):
            utils.ustaw_blad(e_nazwa)
            nowa_nazwa = (e_nazwa.value or "").strip()
            if not nowa_nazwa:
                utils.ustaw_blad(e_nazwa, "Podaj nazwę")
                e_nazwa.update()
                return
            nowe_pozycje = [chk.label for chk in checkboxy if chk.value] + nieobecne
            if not nowe_pozycje:
                utils.ustaw_blad(e_nazwa, "Zaznacz choć jeden podzespół")
                e_nazwa.update()
                return

            if p_id:
                db.aktualizuj_pakiet_wlasny(p_id, nowa_nazwa, nowe_pozycje)
            else:
                db.dodaj_pakiet_wlasny(self.state.auto_id, nowa_nazwa, nowe_pozycje)

            utils.zamknij_dno(self._page, bs)
            self._odswiez_przycisk_pakietow()
            utils.pokaz_komunikat(self._page, f"Zapisano pakiet „{nowa_nazwa}”.")
            self._okno_pakietow()

        naglowek = ft.Row([
            ft.Icon(ft.Icons.BOOKMARK_ADD if not p_id else ft.Icons.EDIT, size=22, color=ft.Colors.PRIMARY),
            ft.Text("Nowy pakiet" if not p_id else "Edycja pakietu",
                    weight="bold", size=18, color=ft.Colors.PRIMARY, expand=True),
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        pasek_zaznaczania = ft.Row([
            ft.Text("Skład pakietu", weight="bold", size=utils.FS["body"], expand=True),
            ft.TextButton("Wszystkie", on_click=zaznacz_wszystkie(True)),
            ft.TextButton("Żadne", on_click=zaznacz_wszystkie(False)),
        ], spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        tresc = [naglowek, ft.Divider(height=14), e_nazwa, ft.Container(height=4), pasek_zaznaczania, licznik]
        if nieobecne:
            tresc.append(ft.Text(
                "Pakiet zawiera też pozycje spoza listy tego pojazdu "
                f"({', '.join(nieobecne)}) — zostaną zachowane.",
                size=utils.FS["caption"], italic=True, color=ft.Colors.ON_SURFACE_VARIANT,
            ))
        tresc.append(lista_kontener)
        tresc.append(ft.Row([
            ft.TextButton("Anuluj", on_click=lambda e: utils.zamknij_dno(self._page, bs)),
            ft.Button("Zapisz pakiet", icon=ft.Icons.CHECK, on_click=zapisz,
                              bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY),
        ], spacing=8, alignment=ft.MainAxisAlignment.END))

        bs.content.content = ft.Column(tresc, tight=True, spacing=8)
        utils.otworz_dno(self._page, bs)

    def _zastosuj_pakiet(self, nazwa_pakietu, pozycje_pakietu):
        # Odznacz to, co zaznaczył POPRZEDNIO zastosowany pakiet, a nie jest
        # częścią nowego — inaczej przełączanie między pakietami zostawiało
        # "resztki" zaznaczeń z wcześniejszego wyboru.
        poprzednie = getattr(self, "_ostatni_pakiet_pozycje", [])
        # Podzespoły założone starszą wersją aplikacji mają emoji w nazwie
        # ("🛢️ Olej silnikowy i filtr"), a definicje pakietów już nie — dlatego
        # porównujemy nazwy po normalizacji (db.bez_emoji), a nie znak w znak.
        cel = {db.bez_emoji(x) for x in pozycje_pakietu}
        poprzednie_norm = {db.bez_emoji(x) for x in poprzednie}
        for chk in self.chk_czesci:
            nazwa_norm = db.bez_emoji(chk.label)
            if nazwa_norm in cel:
                chk.value = True
            elif nazwa_norm in poprzednie_norm:
                chk.value = False

        # Zaznaczone wskakują na górę listy (panel pakietów jest już zamknięty, nic nie ucieka spod palca).
        self._uloz_czesci()
        # WAŻNE: jedna aktualizacja kolumny zamiast chk.update() w pętli (pojedyncze
        # gubiły zmiany). Przerysowanie po zamknięciu panelu w strażniku — wyjątek z
        # niezamontowanej kontrolki nie może przerwać akcji.
        try:
            self.kolumna_czesci.update()
        except Exception:
            pass

        self._ostatni_pakiet_pozycje = list(pozycje_pakietu)
        try:
            self._odswiez_widocznosc_opon()
        except Exception:
            pass

        dopasowane = sum(1 for chk in self.chk_czesci if db.bez_emoji(chk.label) in cel)
        if dopasowane:
            utils.pokaz_komunikat(self._page, f"Zastosowano pakiet „{nazwa_pakietu}” ({dopasowane}/{len(pozycje_pakietu)} pozycji).")
        else:
            utils.pokaz_komunikat(self._page, "Żadna pozycja z pakietu nie pasuje do Twoich podzespołów — dodaj je najpierw w sekcji Serwis.", utils.KOLOR_STATUS["warning"])

    # ================= PODZESPOŁY: SZUKANIE I CENY POZYCJI =================

    def _dodaj_pole_ceny(self, chk, cena):
        """Pole „Cena tej pozycji” pod podzespołem — widoczne, gdy jest zaznaczony."""
        pole = ft.TextField(
            label="Cena tej pozycji", suffix=utils.symbol_waluty(),
            value=utils.liczba_do_pola(cena) if cena else "", keyboard_type=ft.KeyboardType.NUMBER,
            width=190, on_change=lambda e: self._odswiez_sume_pozycji(), **utils.styl_pola(page=self._page),
        )
        self.ceny_pozycji[chk.data] = pole
        self._ceny_poczatkowe[chk.data] = pole.value
        self.wiersze_czesci[chk.data] = ft.Column([
            chk, ft.Container(pole, padding=ft.Padding(40, 0, 0, 6), visible=bool(chk.value)),
        ], spacing=0, tight=True)

    def _zbuduj_sekcje_czesci(self):
        """Pakiety, licznik, szukajka (od PROG_SZUKANIA_PODZESPOLOW pozycji), wiersze, suma cen,
        błąd i rodzaj opon — jedna kolumna odświeżana jednym update()."""
        self.licznik_czesci = utils.podpis("")
        self.suma_pozycji = utils.podpis("", visible=False)
        self.szukaj_czesci = ft.TextField(hint_text="Szukaj podzespołu", prefix_icon=ft.Icons.SEARCH,
                                          on_change=lambda e: self._szukaj_czesci(), **utils.styl_pola(page=self._page))
        self.kolumna_czesci = ft.Column(spacing=2)
        self._uloz_czesci()
        self._po_zmianie_zaznaczenia()
        elementy = [self.btn_pakiety, self.licznik_czesci]
        if len(self.chk_czesci) >= PROG_SZUKANIA_PODZESPOLOW:
            elementy.append(utils.na_cala_szerokosc(self.szukaj_czesci))
        elementy += [self.kolumna_czesci, self.suma_pozycji, self.blad_czesci, self.e_kat_wizyty]
        return ft.Column(elementy, spacing=utils.SPACING["sm"])

    def _uloz_czesci(self):
        """Zaznaczone na górze i zawsze widoczne, reszta po nazwie i według szukanego słowa.
        Przy samym zaznaczaniu kolejność stoi — wiersz nie ucieka spod palca."""
        fraza = utils.bez_ogonkow((self.szukaj_czesci.value or "").strip()).lower()
        zaznaczone = [c for c in self.chk_czesci if c.value]
        reszta = [c for c in self.chk_czesci if not c.value]
        for chk in self.chk_czesci:
            self.wiersze_czesci[chk.data].visible = bool(
                chk.value or not fraza or fraza in utils.bez_ogonkow(str(chk.label)).lower())
        self.kolumna_czesci.controls = [self.wiersze_czesci[c.data] for c in zaznaczone + reszta]

    @staticmethod
    def _przerysuj(kontrolka, opis):
        """update() formularza zbudowanego bez strony (testy) nie przerywa akcji."""
        try:
            kontrolka.update()
        except RuntimeError:
            log.polkniety(opis)

    def _szukaj_czesci(self):
        self._uloz_czesci()
        self._przerysuj(self.kolumna_czesci, "szukanie podzespołu wizyty")

    def _po_zmianie_zaznaczenia(self):
        """Pole ceny przy zaznaczonych, licznik i suma cen; zmiana zaznaczenia zdejmuje
        potwierdzenie zapisu bez podzespołów."""
        for chk in self.chk_czesci:
            self.wiersze_czesci[chk.data].controls[1].visible = bool(chk.value)
        ile = sum(1 for c in self.chk_czesci if c.value)
        self.licznik_czesci.value = (f"Zaznaczone: {ile} z {len(self.chk_czesci)}" if self.chk_czesci
                                     else "Pojazd nie ma jeszcze podzespołów — dodasz je w zakładce Serwis.")
        self._bez_pozycji_potwierdzone = False
        if ile:
            self.blad_czesci.value = ""
        self._odswiez_sume_pozycji(aktualizuj=False)

    def _odswiez_sume_pozycji(self, aktualizuj=True):
        suma = sum(utils.parsuj_float(self.ceny_pozycji[c.data].value, 0.0) or 0.0
                   for c in self.chk_czesci if c.value)
        self.suma_pozycji.value = f"Ceny pozycji razem: {utils.formatuj_liczba(suma)} {utils.symbol_waluty()}"
        self.suma_pozycji.visible = suma > 0
        if aktualizuj:
            self._przerysuj(self.suma_pozycji, "suma cen pozycji wizyty")

    def _ceny_pozycji(self, wybrane):
        """({zadanie_id: cena albo None przy pustym polu}, błędy pól) zaznaczonych pozycji."""
        ceny, bledy = {}, []
        for zid in wybrane:
            pole = self.ceny_pozycji[zid]
            utils.ustaw_blad(pole)
            tekst = (pole.value or "").strip()
            cena = utils.parsuj_float(tekst, None) if tekst else None
            if tekst and (cena is None or cena < 0):
                bledy.append((pole, "Błędna kwota"))
                continue
            ceny[zid] = round(cena, 2) if cena is not None else None
        return ceny, bledy

    def _migawka_formularza(self):
        return (
            self.e_d.value, self.e_p.value, self.get_wykonawca(), self.koszt.migawka(), self.e_n.value,
            self.get_tagi(), self.e_kat_wizyty.value,
            tuple((chk.value, (self.ceny_pozycji[chk.data].value or "").strip() if chk.value else "")
                  for chk in self.chk_czesci),
            self.zuzycie.migawka(), self.gwarancja.migawka(), self.pliki.migawka(), self.rodzaj.migawka(),
        )

    def _przebieg_km(self):
        """Licznik wizyty w km albo None (puste albo błędne pole)."""
        wartosc = utils.parsuj_int(self.e_p.value, None)
        if wartosc is None or wartosc <= 0:
            return None
        return db.dystans_na_km(wartosc, calkowity=True, km_przy_otwarciu=self.p_km)

    def _czy_zmieniono(self):
        return self._migawka_formularza() != self._stan_poczatkowy

    def zapisz(self, e):
        utils.ustaw_blad(self.e_p)
        # Pole w jednostce z Ustawień, baza w km; nieruszone pole wraca bez przeliczania.
        prz = db.dystans_na_km(utils.parsuj_int(self.e_p.value, 0), calkowity=True, km_przy_otwarciu=self.p_km)
        kos, robocizna, bledy_kosztu = self.koszt.sprawdz()
        gw_koniec, gw_limit, bledy_gwarancji = self.gwarancja.sprawdz()
        bledy = []
        if not (self.e_p.value or "").strip(): bledy.append((self.e_p, "Wymagane"))
        bledy += bledy_kosztu + bledy_gwarancji
        
        wybrane = [chk.data for chk in self.chk_czesci if chk.value]
        ceny, bledy_cen = self._ceny_pozycji(wybrane)
        bledy += bledy_cen

        # Zużycie przychodzi już wycenione — ten sam koszt trafia do powiązania
        # i do kosztu całkowitego wizyty.
        nowe_uzyte, blad_magazynu = self.zuzycie.sprawdz()
        koszt_czesci = db.suma_kosztu_zuzycia(nowe_uzyte)
        koszt_razem = round(kos + koszt_czesci, 2)
        # Cena pozycji to część rachunku wizyty — razem nie mogą go przekroczyć.
        suma_cen = round(sum(c or 0.0 for c in ceny.values()), 2)
        if not bledy_cen and suma_cen > koszt_razem + 0.005:
            pierwsza = next(zid for zid in wybrane if ceny.get(zid))
            waluta = utils.symbol_waluty()
            bledy.append((self.ceny_pozycji[pierwsza],
                          f"Pozycje razem {utils.formatuj_liczba(suma_cen)} {waluta} — więcej niż koszt wizyty "
                          f"({utils.formatuj_liczba(koszt_razem)} {waluta})"))

        # Wizyta bez podzespołu (diagnostyka, przegląd) przechodzi drugim „Zapisz”.
        bez_pozycji = not wybrane and not self._bez_pozycji_potwierdzone
        self.blad_czesci.color = utils.KOLOR_STATUS["warning"]
        self.blad_czesci.value = ("Nie zaznaczono podzespołu — wizyta nie przestawi licznika żadnej wymiany."
                                  if bez_pozycji else "")

        if bledy or blad_magazynu or bez_pozycji:
            self._page.update()
            if bledy:
                utils.pokaz_bledy_formularza(self._page, bledy)
            elif blad_magazynu:
                utils.pokaz_komunikat(self._page, "Sprawdź ilości wykorzystanych części z magazynu.", utils.KOLOR_STATUS["error"])
            else:
                self._bez_pozycji_potwierdzone = True
                utils.pokaz_komunikat(self._page, "Nie zaznaczono żadnego podzespołu. Dotknij „Zapisz” ponownie, "
                                                  "aby zapisać wizytę bez nich.", utils.KOLOR_STATUS["warning"])
            return

        if utils.sprawdz_podejrzany_przebieg(self._page, self.e_p, self.state.auto_id, prz, wyklucz_id=self.w_id, tabela="wizyty", nowa_data_str=self.e_d.value):
            return

        # ZAPIS NOWEGO WARSZTATU
        wyk = self.get_wykonawca() or "Warsztat"
        if wyk and wyk != "Warsztat":
            db.dodaj_warsztat(self.state.auto_id, wyk)
            
        wybrane_tagi = self.get_tagi()
        rodzaj = self.rodzaj.wartosc

        zdalne_id_historii_do_nagrobka = []
        zdalne_id_czesci_do_nagrobka = []
        wpis_opon = None  # nowa wizyta z wymianą opon i rodzajem opon zakłada ten komplet (niżej)

        with self.pliki.zapis(), db.polacz_baze() as conn:
            cur = conn.cursor()
            if self.w_id:
                cur.execute("SELECT dodane_przez FROM wizyty WHERE id=?", (self.w_id,))
                w_osoba = cur.fetchone()
                osoba_wizyty = (w_osoba[0] if w_osoba and w_osoba[0] else None) or db.pobierz_moje_imie()
                nowa_gwarancja = db.klucz_gwarancji(gw_koniec, gw_limit)
                cur.execute("UPDATE wizyty SET data=?, data_iso=?, przebieg=?, wykonawca=?, koszt_calkowity=?, koszt_robocizny=?, notatki=?, tagi=?, gwarancja_data=?, gwarancja_przebieg=?, rodzaj=?, zmodyfikowane_przez=?, data_modyfikacji=? WHERE id=?", (self.e_d.value, na_iso(self.e_d.value), prz, wyk, koszt_razem, robocizna, self.e_n.value, wybrane_tagi, *nowa_gwarancja, rodzaj, db.pobierz_moje_imie(), datetime.now().strftime("%d.%m.%Y %H:%M"), self.w_id))

                # Zostające pozycje POPRAWIAMY w miejscu (UPDATE), nie kasujemy —
                # skasowanie gubiło cenę z Do zrobienia, notatkę i załącznik, a w
                # chmurze robiło nagrobki i nowe rekordy. Nagrobek tylko dla
                # odznaczonych (po commicie). Gwarancja: pozycje przy dotychczasowej
                # wspólnej dostają nową, pozycje z własną (wyjątek) — nie.
                cur.execute("SELECT id, zadanie_id, zdalne_id, gwarancja_data, gwarancja_przebieg FROM historia WHERE wizyta_id=? ORDER BY id", (self.w_id,))
                zostaja = set()
                for h_id, zid, zdalne_id, gw_data_poz, gw_km_poz in cur.fetchall():
                    if zid in wybrane and zid not in zostaja:
                        kat = self.e_kat_wizyty.value if zid in self.zadania_opon_ids else None
                        gwarancja_poz = db.klucz_gwarancji(gw_data_poz, gw_km_poz)
                        if gwarancja_poz == self._gwarancja_wizyty:
                            gwarancja_poz = nowa_gwarancja
                        cur.execute("UPDATE historia SET data=?, data_iso=?, przebieg=?, wykonawca=?, kategoria=?, gwarancja_data=?, gwarancja_przebieg=?, rodzaj=? WHERE id=?",
                                    (self.e_d.value, na_iso(self.e_d.value), prz, wyk, kat, *gwarancja_poz, rodzaj, h_id))
                        # Cenę ruszamy tylko po zmianie pola — zapisana (np. z Do zrobienia) zostaje co do grosza.
                        if (self.ceny_pozycji[zid].value or "").strip() != self._ceny_poczatkowe[zid]:
                            cur.execute("UPDATE historia SET cena=? WHERE id=?", (ceny.get(zid) or 0.0, h_id))
                        zostaja.add(zid)
                        continue
                    if zdalne_id:
                        zdalne_id_historii_do_nagrobka.append(zdalne_id)
                    cur.execute("DELETE FROM historia WHERE id=?", (h_id,))
                for zid in wybrane:
                    if zid in zostaja:
                        continue
                    kat = self.e_kat_wizyty.value if zid in self.zadania_opon_ids else None
                    cur.execute("INSERT INTO historia (wizyta_id, zadanie_id, data, data_iso, przebieg, cena, wykonawca, kategoria, gwarancja_data, gwarancja_przebieg, rodzaj, dodane_przez) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (self.w_id, zid, self.e_d.value, na_iso(self.e_d.value), prz, ceny.get(zid) or 0.0, wyk, kat, *nowa_gwarancja, rodzaj, osoba_wizyty))
                wizyta_id = self.w_id
                zdalne_id_czesci_do_nagrobka = db.przywroc_czesci_wizyty(wizyta_id, conn=conn)
            else:
                osoba_wizyty = db.pobierz_moje_imie()
                nowa_gwarancja = db.klucz_gwarancji(gw_koniec, gw_limit)
                cur.execute("INSERT INTO wizyty (auto_id, data, data_iso, przebieg, wykonawca, koszt_calkowity, koszt_robocizny, notatki, tagi, gwarancja_data, gwarancja_przebieg, rodzaj, dodane_przez) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (self.state.auto_id, self.e_d.value, na_iso(self.e_d.value), prz, wyk, koszt_razem, robocizna, self.e_n.value, wybrane_tagi, *nowa_gwarancja, rodzaj, osoba_wizyty))
                wizyta_id = cur.lastrowid
                # Wpis i koniec szkicu razem albo wcale — zdjęcie ma już nowy wpis.
                if self.szkic:
                    db.zamknij_szkic(self.szkic["id"], conn=conn)
                for zid in wybrane: 
                    kat = self.e_kat_wizyty.value if zid in self.zadania_opon_ids else None
                    cur.execute("INSERT INTO historia (wizyta_id, zadanie_id, data, data_iso, przebieg, cena, wykonawca, kategoria, gwarancja_data, gwarancja_przebieg, rodzaj, dodane_przez) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (wizyta_id, zid, self.e_d.value, na_iso(self.e_d.value), prz, ceny.get(zid) or 0.0, wyk, kat, *nowa_gwarancja, rodzaj, osoba_wizyty))
                    if kat and wpis_opon is None:
                        wpis_opon = (cur.lastrowid, kat)
 
            db.rozlicz_czesci_z_magazynu(wizyta_id, nowe_uzyte, conn=conn)
            self.pliki.zapisz_w(conn, wizyta_id, self.state.auto_id)

        # WAŻNE: rejestrujemy nagrobki dopiero PO zamknięciu/commicie transakcji
        # `conn` powyżej — zarejestruj_nagrobek() otwiera własne połączenie do
        # SQLite i wywołane w środku otwartej transakcji mogłoby zakleszczyć bazę.
        for zid in zdalne_id_historii_do_nagrobka:
            db.zarejestruj_nagrobek("historia", zid)
        for zid in zdalne_id_czesci_do_nagrobka:
            db.zarejestruj_nagrobek("wizyta_czesci_magazynu", zid)

        db.przelicz_wszystkie_zadania(self.state.auto_id)
        zmiana_opon = db.zamontuj_po_wymianie(self.state.auto_id, wpis_opon[1], self.e_d.value, prz,
                                              wpis_opon[0]) if wpis_opon else None
        utils.wypchnij_w_tle(self._page, self.state.auto_id, "wizyta")
        utils.przejdz(self._page, utils.trasa_po_zapisie_szkicu(self.state.auto_id, "/wizyty") if self.szkic else "/wizyty")
        dopisek = utils.dopisek_kolejki(self.state.auto_id) if self.szkic else ""
        if zmiana_opon and zmiana_opon.get("ok"):
            dopisek = f" Założono opony {zmiana_opon['na'].lower()} z magazynu.{dopisek}"
        if koszt_czesci > 0:
            utils.pokaz_komunikat(self._page, f"Zapisano wizytę! Doliczono części z magazynu: {utils.formatuj_liczba(koszt_czesci)} {utils.symbol_waluty()}.{dopisek}")
        else:
            utils.pokaz_komunikat(self._page, f"Zapisano wizytę!{dopisek}")


__all__ = [
    "FormularzWizytyView",
    "PROG_SZUKANIA_PODZESPOLOW",
]
