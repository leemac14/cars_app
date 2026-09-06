"""Formularz wizyty w warsztacie wraz z pozycjami i częściami."""

import db
import flet as ft
import utils
from datetime import datetime


class FormularzWizytyView(ft.View):
    def __init__(self, page: ft.Page, state, w_id=None):
        self._page = page
        self.state = state
        self.w_id = w_id

        d_val, p_val, wyk_val, kosz_val, not_val, podpiete = datetime.now().strftime("%d.%m.%Y"), str(db.pobierz_aktualny_przebieg(self.state.auto_id) or ""), "", "", "", set()
        self.zalacznik_val = None
        tagi_val = ""
        kat_val = "Letnie"

        # Duplikat wizyty: ten sam wzorzec, co przy tankowaniu, wpisie i koszcie —
        # źródło zużywamy jednorazowo, żeby powrót do formularza nie skopiował
        # wizyty po raz drugi.
        duplikuj_id = getattr(state, "duplikuj_zrodlo_wizyta", None) if not w_id else None
        state.duplikuj_zrodlo_wizyta = None
        zrodlo_id = w_id or duplikuj_id

        if zrodlo_id:
            with db.polacz_baze() as conn:
                c = conn.cursor()
                c.execute("SELECT data, przebieg, wykonawca, koszt_calkowity, notatki, zalacznik, tagi FROM wizyty WHERE id=?", (zrodlo_id,))
                w = c.fetchone()
                if w: 
                    d_val, p_val, wyk_val, kosz_val, not_val = str(w[0] or ""), str(w[1] or ""), str(w[2] or ""), str(w[3] or ""), str(w[4] or "")
                    self.zalacznik_val = w[5]
                    tagi_val = str(w[6] or "")
                c.execute("SELECT zadanie_id, kategoria FROM historia WHERE wizyta_id=?", (zrodlo_id,))
                dane_h = c.fetchall()
                podpiete = {r[0] for r in dane_h}
                for r in dane_h:
                    if r[1]: kat_val = str(r[1])

        if duplikuj_id:
            # Data i przebieg opisują TAMTĄ wizytę, a paragon należy do niej —
            # kopiujemy wzorzec naprawy, nie zdarzenie. Zużycie magazynu również
            # nie jest przenoszone: stan mógł się zmienić, a ciche potrącenie
            # sztuk przy zapisie byłoby niespodzianką.
            d_val = datetime.now().strftime("%d.%m.%Y")
            p_val = str(db.pobierz_aktualny_przebieg(self.state.auto_id) or "")
            self.zalacznik_val = None

        self.e_d = utils.pole_daty(page, "Data odebrania z warsztatu", d_val)
        self.e_p = ft.TextField(label="Przebieg podczas wizyty (km)", value=p_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))
        self.k_wykonawca, self.get_wykonawca = utils.komponent_wyboru_warsztatu(page, state, wyk_val)
        self.e_k = ft.TextField(label=f"Całkowity koszt naprawy ({utils.symbol_waluty()})", value=kosz_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))
        self.e_n = ft.TextField(label="Notatki i uwagi", value=not_val, multiline=True, min_lines=2, max_lines=4, **utils.styl_pola(page=page))
        self.k_zalacznik, self.get_zalacznik = utils.komponent_zalacznika(page, self.zalacznik_val)
        self.k_tagi, self.get_tagi = utils.komponent_tagow(page, state, tagi_val)
        self.blad_czesci = ft.Text("", color=ft.Colors.RED_700, size=13)

        self.chk_czesci = []
        self.zadania_opon_ids = set()
        
        def odswiez_widocznosc_opon(e=None):
            czy_zaznaczono_opony = any(chk.value for chk in self.chk_czesci if chk.data in self.zadania_opon_ids)
            self.e_kat_wizyty.visible = czy_zaznaczono_opony
            self.e_kat_wizyty.update()

        self._odswiez_widocznosc_opon = odswiez_widocznosc_opon

        with db.polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT id, nazwa, dotyczy_opon FROM zadania WHERE auto_id=? ORDER BY nazwa", (self.state.auto_id,))
            for z_i, z_n, z_opon in c.fetchall():
                chk = ft.Checkbox(label=str(z_n), value=(z_i in podpiete), data=z_i, on_change=odswiez_widocznosc_opon)
                self.chk_czesci.append(chk)
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

        poprzednio_uzyte = dict(db.pobierz_uzyte_czesci_wizyty(w_id)) if w_id else {}
        with db.polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT id, nazwa, ilosc, jednostka FROM magazyn_czesci WHERE auto_id=? ORDER BY nazwa", (self.state.auto_id,))
            wszystkie_czesci_magazynu = c.fetchall()

        self.magazyn_kontrolki = []
        wiersze_magazynu = []
        for m_id, m_nazwa, m_ilosc, m_jedn in wszystkie_czesci_magazynu:
            juz_uzyto = float(poprzednio_uzyte.get(m_id, 0) or 0)
            dostepna = float(m_ilosc or 0) + juz_uzyto
            if dostepna <= 0:
                continue

            zaznaczone = m_id in poprzednio_uzyte
            pole_ilosc = ft.TextField(
                value=utils.formatuj_liczba(juz_uzyto, 2) if zaznaczone else "1",
                width=90, visible=zaznaczone,
                keyboard_type=ft.KeyboardType.NUMBER,
                **utils.styl_pola(page=page)
            )

            def _przelacz(e, pole=pole_ilosc):
                pole.visible = e.control.value
                pole.update()

            chk = ft.Checkbox(
                label=f"{m_nazwa} (dost.: {utils.formatuj_liczba(dostepna, 2)} {m_jedn or 'szt'})",
                value=zaznaczone, data=m_id, on_change=_przelacz
            )

            self.magazyn_kontrolki.append((chk, pole_ilosc, {"id": m_id, "dostepna": dostepna}))
            wiersze_magazynu.append(ft.Row([chk, pole_ilosc], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER))

        self.magazyn_lista_kontener = ft.Column(wiersze_magazynu, spacing=8, visible=bool(poprzednio_uzyte))

        def _przelacz_magazyn(e):
            self.magazyn_lista_kontener.visible = e.control.value
            self.magazyn_lista_kontener.update()

        self.c_uzyj_magazynu = ft.Checkbox(
            label="Wykorzystaj własne części z magazynu",
            value=bool(poprzednio_uzyte),
            on_change=_przelacz_magazyn
        )

        self._stan_poczatkowy = self._migawka_formularza()
        appbar = utils.zbuduj_pasek_z_powrotem(page, "Edycja wizyty" if w_id else "Nowa wizyta zbiorcza", "/wizyty", on_save=self.zapisz, czy_zmieniono=self._czy_zmieniono)
        
        k1 = utils.karta_formularza(
            [self.e_d, self.e_p, self.k_wykonawca, self.e_k, self.e_n, ft.Text("Przypisane tagi:", size=13, weight="bold"), self.k_tagi],
            "Ogólne informacje", ft.Icons.HOME_REPAIR_SERVICE, domyslnie_otwarte=True, page=page
        )
        k1b = utils.karta_formularza([self.k_zalacznik], "Załącznik (paragon / zdjęcie)", ft.Icons.ATTACH_FILE)
        self.kolumna_czesci = ft.Column(self.chk_czesci, spacing=2)
        k2 = utils.karta_formularza([self.btn_pakiety, self.kolumna_czesci, self.blad_czesci, self.e_kat_wizyty], "Zaznacz wymienione podzespoły", ft.Icons.CHECKLIST)
        elementy = [k1, k1b, k2]

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
                        "Duplikat wizyty: przeniesiono warsztat, koszt, notatki, tagi i zaznaczone "
                        "podzespoły. Data i przebieg są dzisiejsze, a zużycie z magazynu zaznacz "
                        "ponownie — stan mógł się zmienić.",
                        size=11, color=ft.Colors.ON_SURFACE_VARIANT, expand=True,
                    ),
                ], spacing=8),
            ))

        if self.magazyn_kontrolki:
            k3 = utils.karta_formularza(
                [self.c_uzyj_magazynu, self.magazyn_lista_kontener],
                "Magazyn części", ft.Icons.INVENTORY_2
            )
            elementy.append(k3)

        elementy.append(utils.przyciski_akcji(page, "Zapisz wizytę", self.zapisz, "/wizyty"))

        super().__init__(
            route=f"/wizyty/edytuj/{w_id}" if w_id else "/wizyty/nowa",
            padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO
        )

    # ================= PAKIETY SERWISOWE =================
    # Dawniej: PopupMenuButton z pozycjami po dwie linijki i dwa ciasne
    # AlertDialogi (lista + edycja), w których skład pakietu był tylko sklejonym
    # tekstem, a podmiana składu wymagała sztuczki „zastąp obecnym zaznaczeniem”.
    # Teraz: panel od dołu na pełną szerokość — karty pakietów ze składem jako
    # chipy i osobnymi przyciskami akcji, a edytor pokazuje WSZYSTKIE podzespoły
    # pojazdu z checkboxami, więc skład układa się wprost.

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
        gotowe = len(db.PAKIETY_SERWISOWE)
        if not wlasne:
            return f"{gotowe} gotowych — zaznacz kilka podzespołów naraz"
        wlasne_opis = "1 własny" if wlasne == 1 else f"{wlasne} własne" if wlasne < 5 else f"{wlasne} własnych"
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
        powierzchnia = utils.powierzchnia_karty(self._page, "sm")
        return ft.Container(
            padding=14,
            border_radius=utils.RADIUS["md"],
            bgcolor=powierzchnia["bgcolor"],
            border=powierzchnia["border"],
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
        zawartosc.append(ft.Text("TWOJE PAKIETY", size=utils.FS["caption"], weight="bold",
                                 color=ft.Colors.ON_SURFACE_VARIANT))
        if pakiety_wlasne:
            for p_id, nazwa, pozycje in pakiety_wlasne:
                zawartosc.append(self._karta_pakietu(nazwa, pozycje, [
                    ft.TextButton("Edytuj", icon=ft.Icons.EDIT,
                                  on_click=lambda e, i=p_id, n=nazwa, p=pozycje: edytuj(i, n, p)),
                    ft.TextButton("Usuń", icon=ft.Icons.DELETE,
                                  style=ft.ButtonStyle(color=ft.Colors.RED_700),
                                  on_click=lambda e, i=p_id, n=nazwa: usun(i, n)),
                    przycisk_zastosuj(nazwa, pozycje),
                ]))
        else:
            zawartosc.append(ft.Container(
                padding=ft.Padding(12, 14, 12, 14),
                border_radius=utils.RADIUS["md"],
                bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.ON_SURFACE),
                content=ft.Text(
                    "Nie masz jeszcze własnych pakietów. Ułóż taki, jaki naprawdę robisz "
                    "u swojego mechanika — „Nowy pakiet” powyżej.",
                    size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
                ),
            ))

        zawartosc.append(ft.Container(height=10))
        zawartosc.append(ft.Text("GOTOWE ZESTAWY", size=utils.FS["caption"], weight="bold",
                                 color=ft.Colors.ON_SURFACE_VARIANT))
        for nazwa, pozycje in db.PAKIETY_SERWISOWE.items():
            zawartosc.append(self._karta_pakietu(nazwa, list(pozycje), [przycisk_zastosuj(nazwa, list(pozycje))]))

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
            licznik.value = f"Wybrano {ile} z {len(checkboxy)} podzespołów"
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
            ft.ElevatedButton("Zapisz pakiet", icon=ft.Icons.CHECK, on_click=zapisz,
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

        # WAŻNE: jedna zbiorcza aktualizacja całej kolumny zamiast osobnego
        # chk.update() w pętli — pojedyncze wywołania potrafiły "zgubić" zmianę
        # pierwszej checkboksy na liście przy szybkich, wielokrotnych update().
        # Pakiet stosujemy teraz zaraz po zamknięciu panelu dolnego, więc
        # przerysowanie owijamy strażnikiem — wartości checkboxów są już
        # ustawione i tak, a wyjątek z niezamontowanej kontrolki nie ma prawa
        # przerwać całej akcji.
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
            utils.pokaz_komunikat(self._page, "Żadna pozycja z pakietu nie pasuje do Twoich podzespołów — dodaj je najpierw w sekcji Serwis.", ft.Colors.ORANGE_700)

    def _migawka_formularza(self):
        return (
            self.e_d.value, self.e_p.value, self.get_wykonawca(), self.e_k.value, self.e_n.value,
            self.get_tagi(), self.e_kat_wizyty.value,
            tuple(chk.value for chk in self.chk_czesci),
            self.c_uzyj_magazynu.value,
            tuple((chk.value, pole.value) for chk, pole, _ in self.magazyn_kontrolki),
        )

    def _czy_zmieniono(self):
        return self._migawka_formularza() != self._stan_poczatkowy

    def zapisz(self, e):
        utils.ustaw_blad(self.e_p)
        utils.ustaw_blad(self.e_k)
        prz, kos = utils.parsuj_int(self.e_p.value, 0), utils.parsuj_float(self.e_k.value, 0.0)
        bledy = []
        if not (self.e_p.value or "").strip(): bledy.append((self.e_p, "Wymagane"))
        if kos < 0: bledy.append((self.e_k, "Koszt nie może być ujemny"))
        
        wybrane = [chk.data for chk in self.chk_czesci if chk.value]
        self.blad_czesci.value = "Zaznacz co najmniej jedną część!" if not wybrane else ""

        nowe_uzyte = []
        for chk, pole_ilosc, poz in self.magazyn_kontrolki:
            utils.ustaw_blad(pole_ilosc)
            if self.c_uzyj_magazynu.value and chk.value:
                ilosc = utils.parsuj_float(pole_ilosc.value, None)
                if ilosc is None or ilosc <= 0 or ilosc > poz["dostepna"] + 1e-9:
                    utils.ustaw_blad(pole_ilosc, f"Maks. {utils.formatuj_liczba(poz['dostepna'], 2)}")
                else:
                    nowe_uzyte.append((poz["id"], ilosc))

        blad_magazynu = any(utils.blad_kontrolki(pole) for _, pole, _ in self.magazyn_kontrolki)

        if bledy or self.blad_czesci.value or blad_magazynu:
            self._page.update()
            if bledy:
                utils.pokaz_bledy_formularza(self._page, bledy)
            elif blad_magazynu:
                utils.pokaz_komunikat(self._page, "Sprawdź ilości wykorzystanych części z magazynu.", ft.Colors.RED_700)
            elif self.blad_czesci.value:
                utils.pokaz_komunikat(self._page, "Zaznacz co najmniej jedną część z listy!", ft.Colors.RED_700)
            return

        if utils.sprawdz_podejrzany_przebieg(self._page, self.e_p, self.state.auto_id, prz, wyklucz_id=self.w_id, tabela="wizyty", nowa_data_str=self.e_d.value):
            return

        # ZAPIS NOWEGO WARSZTATU
        wyk = self.get_wykonawca() or "Warsztat"
        if wyk and wyk != "Warsztat":
            db.dodaj_warsztat(self.state.auto_id, wyk)
            
        wybrane_tagi = self.get_tagi()
        przygotowany = db.przygotuj_nowy_zalacznik(self.get_zalacznik())
        nowy_zalacznik = przygotowany if przygotowany is not None else self.zalacznik_val

        zdalne_id_historii_do_nagrobka = []
        zdalne_id_czesci_do_nagrobka = []

        with db.polacz_baze() as conn:
            cur = conn.cursor()
            if self.w_id:
                cur.execute("SELECT dodane_przez FROM wizyty WHERE id=?", (self.w_id,))
                w_osoba = cur.fetchone()
                osoba_wizyty = (w_osoba[0] if w_osoba and w_osoba[0] else None) or db.pobierz_moje_imie()
                cur.execute("UPDATE wizyty SET data=?, przebieg=?, wykonawca=?, koszt_calkowity=?, notatki=?, zalacznik=?, tagi=?, zmodyfikowane_przez=?, data_modyfikacji=? WHERE id=?", (self.e_d.value, prz, wyk, kos, self.e_n.value, nowy_zalacznik, wybrane_tagi, db.pobierz_moje_imie(), datetime.now().strftime("%d.%m.%Y %H:%M"), self.w_id))

                # Zapamiętujemy zdalne_id usuwanych wpisów historii — DELETE+INSERT
                # niżej to z punktu widzenia sync'a "usunięcie starych + utworzenie
                # nowych", więc stare zdalne_id muszą dostać nagrobek (rejestrujemy
                # go dopiero po commicie tej transakcji, patrz niżej).
                cur.execute("SELECT zdalne_id FROM historia WHERE wizyta_id=? AND zdalne_id IS NOT NULL", (self.w_id,))
                zdalne_id_historii_do_nagrobka = [r[0] for r in cur.fetchall()]

                cur.execute("DELETE FROM historia WHERE wizyta_id=?", (self.w_id,))
                for zid in wybrane: 
                    kat = self.e_kat_wizyty.value if zid in self.zadania_opon_ids else None
                    cur.execute("INSERT INTO historia (wizyta_id, zadanie_id, data, przebieg, cena, wykonawca, kategoria, dodane_przez) VALUES (?,?,?,?,0,?,?,?)", (self.w_id, zid, self.e_d.value, prz, wyk, kat, osoba_wizyty))
                wizyta_id = self.w_id
                zdalne_id_czesci_do_nagrobka = db.przywroc_czesci_wizyty(wizyta_id, conn=conn)
            else:
                osoba_wizyty = db.pobierz_moje_imie()
                cur.execute("INSERT INTO wizyty (auto_id, data, przebieg, wykonawca, koszt_calkowity, notatki, zalacznik, tagi, dodane_przez) VALUES (?,?,?,?,?,?,?,?,?)", (self.state.auto_id, self.e_d.value, prz, wyk, kos, self.e_n.value, nowy_zalacznik, wybrane_tagi, osoba_wizyty))
                wizyta_id = cur.lastrowid
                for zid in wybrane: 
                    kat = self.e_kat_wizyty.value if zid in self.zadania_opon_ids else None
                    cur.execute("INSERT INTO historia (wizyta_id, zadanie_id, data, przebieg, cena, wykonawca, kategoria, dodane_przez) VALUES (?,?,?,?,0,?,?,?)", (wizyta_id, zid, self.e_d.value, prz, wyk, kat, osoba_wizyty))
 
            db.rozlicz_czesci_z_magazynu(wizyta_id, nowe_uzyte, conn=conn)
        db.zatwierdz_zalacznik(self.zalacznik_val, przygotowany)

        # WAŻNE: rejestrujemy nagrobki dopiero PO zamknięciu/commicie transakcji
        # `conn` powyżej — zarejestruj_nagrobek() otwiera własne połączenie do
        # SQLite i wywołane w środku otwartej transakcji mogłoby zakleszczyć bazę.
        for zid in zdalne_id_historii_do_nagrobka:
            db.zarejestruj_nagrobek("historia", zid)
        for zid in zdalne_id_czesci_do_nagrobka:
            db.zarejestruj_nagrobek("wizyta_czesci_magazynu", zid)

        db.przelicz_wszystkie_zadania(self.state.auto_id)
        utils.wypchnij_w_tle(self._page, self.state.auto_id, "wizyta")
        utils.przejdz(self._page, "/wizyty")
        utils.pokaz_komunikat(self._page, "Zapisano wizytę!")


__all__ = [
    "FormularzWizytyView",
]
