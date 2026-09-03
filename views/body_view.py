import flet as ft
from datetime import datetime
import db
import utils

class KaroseriaView(ft.View, utils.ZaznaczanieGrupowe):
    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state

        appbar = utils.zbuduj_pasek_z_powrotem(page, "Rejestr karoserii", "/", ikona=ft.Icons.PHOTO_CAMERA)
        
        self.tryb_zaznaczania = False
        self.zaznaczone_id = set()
        self.tabela_cel = "zdjecia_karoserii"
        self.oryginalny_appbar = appbar
        self.karty_ref = {}
        self.uzyj_wirtualizacji = False

        elementy = []
        fab = utils.fab_animowany(ft.Icons.ADD, lambda e: utils.przejdz(self._page, "/karoseria/nowe"))

        # Pobieranie danych
        with db.polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT id, data, strefa, zalacznik, typ_porownania, opis FROM zdjecia_karoserii WHERE auto_id=? ORDER BY id DESC", (self.state.auto_id,))
            zdjecia = c.fetchall()

        if not zdjecia:
            elementy.append(utils.ekran_braku_danych(
                ikona=ft.Icons.PHOTO_CAMERA,
                tytul="Brak zdjęć karoserii",
                opis="Dodaj pierwsze zdjęcie, aby dokumentować stan auta, uszkodzenia i naprawy.",
                tekst_przycisku="Dodaj zdjęcie",
                on_click=lambda e: utils.przejdz(self._page, "/karoseria/nowe")
            ))
        else:
            filtr_strefa_ui = utils.przycisk_filtrowania_kategoria(self._page, self.state, "karoseria_strefa", zdjecia, 2, "Strefa auta")
            
            def filtruj_galerie(e):
                zapytanie = e.control.value.lower().strip()
                self.lista_kart.controls.clear()
                for k in self.wszystkie_karty:
                    if zapytanie in k["szukaj"]: self.lista_kart.controls.append(k["karta"])
                self.update()

            pole_szukaj = ft.TextField(hint_text="Szukaj (strefa, opis, typ)...", prefix_icon=ft.Icons.SEARCH, on_change=utils.z_opoznieniem(self._page, filtruj_galerie), **utils.styl_pola())
            
            elementy.append(ft.Row([ft.Text("Filtruj:", weight="bold", color=ft.Colors.ON_SURFACE_VARIANT), filtr_strefa_ui]))
            elementy.append(pole_szukaj)
            
            zdjecia = utils.filtruj_po_kategorii(zdjecia, self.state, "karoseria_strefa", 2)
            
            self.lista_kart = ft.GridView(
                height=utils.wysokosc_listy(self._page), max_extent=185, spacing=10, run_spacing=10,
                padding=0, child_aspect_ratio=0.72
            )
            self.wszystkie_karty = []
            self.uzyj_wirtualizacji = True

            def otworz_menu(zid, z_sciezka):
                def wykonaj():
                    wynik = db.usun_z_cofnieciem("zdjecia_karoserii", zid)
                    utils.przejdz(self._page, "/karoseria")
                    utils.pokaz_komunikat_cofnij(self._page, "Usunięto wpis z galerii.", wynik)

                utils.pokaz_menu_kontekstowe(self._page, "Opcje zdjęcia", [
                    {"ikona": ft.Icons.IMAGE, "tekst": "Pełny ekran", "akcja": lambda: utils.pokaz_podglad_zalacznika(self._page, z_sciezka, "Galeria")},
                    {"ikona": ft.Icons.COMPARE, "tekst": "Wybierz do porównania", "akcja": lambda: self.wymus_tryb_zaznaczania(zid)},
                    {"ikona": ft.Icons.EDIT, "tekst": "Edytuj wpis", "akcja": lambda: utils.przejdz(self._page, f"/karoseria/edytuj/{zid}")},
                    {"ikona": ft.Icons.DELETE, "tekst": "Usuń wpis", "akcja": lambda: utils.potwierdz(self._page, "Usunąć?", "Na pewno?", wykonaj), "kolor": ft.Colors.RED}
                ])

            for z in zdjecia:
                z_id, z_data, z_strefa, z_zal, z_typ, z_opis = z
                kolor_typu = ft.Colors.BLUE if z_typ == "Przed naprawą" else ft.Colors.GREEN if z_typ == "Po naprawie" else ft.Colors.ON_SURFACE_VARIANT
                
                karta, kontener = utils.karta_listy(
                    ft.Column([
                        ft.Image(src=utils.abs_zalacznik(z_zal), height=110, width=165, fit="cover", border_radius=8),
                        ft.Text(f"{z_data} • {z_strefa}", size=12, weight="bold", no_wrap=True),
                        ft.Text(str(z_typ) if z_typ != "Brak" else "Zwykłe", size=11, color=kolor_typu, weight="bold")
                    ], spacing=4),
                    tlo=ft.Colors.with_opacity(0.04, ft.Colors.ON_SURFACE),
                    page=self._page,
                )
                kontener.width = 165
                kontener.padding = 10

                self.karty_ref[z_id] = kontener
                self.podepnij_zdarzenia_grupowe(kontener, z_id, lambda zid=z_id, zal=z_zal: otworz_menu(zid, zal))

                self.wszystkie_karty.append({"karta": karta, "szukaj": f"{z_strefa} {z_opis} {z_typ} {z_data}".lower()})
                self.lista_kart.controls.append(karta)

            elementy.append(self.lista_kart)

        elementy.append(utils.dol_bezpieczny(10))

        super().__init__(
            route="/karoseria", padding=15,
            appbar=appbar, floating_action_button=fab,
            spacing=15,
            controls=elementy,          # lub self.elementy, w zależności jak masz w tym pliku
            scroll=ft.ScrollMode.AUTO,  # włączasz natywne przewijanie
        )
        
    # --- NOWE: Wymuszenie zaznaczania z menu kontekstowego zdjęcia ---
    def wymus_tryb_zaznaczania(self, element_id):
        self.tryb_zaznaczania = True
        self.zaznacz_odznacz(element_id, self.karty_ref[element_id])
        utils.pokaz_komunikat(self._page, "Zaznacz jeszcze jedno zdjęcie do porównania.", ft.Colors.PRIMARY)

    def aktualizuj_appbar_zaznaczania(self, dodatkowe_akcje=None):
        extra = [ft.IconButton(ft.Icons.EDIT, tooltip="Edytuj zaznaczone zbiorczo", on_click=self.edytuj_zaznaczone_zbiorczo)]
        if len(self.zaznaczone_id) == 2:
            extra.append(ft.IconButton(ft.Icons.COMPARE, tooltip="Porównaj zaznaczone", on_click=self.otworz_porownanie))
        super().aktualizuj_appbar_zaznaczania(dodatkowe_akcje=extra)

    def edytuj_zaznaczone_zbiorczo(self, e):
        ids = list(self.zaznaczone_id)
        ile = len(ids)
        BRAK_ZMIAN = "— Bez zmian —"

        e_strefa = ft.Dropdown(
            label="Strefa karoserii",
            options=[ft.DropdownOption(BRAK_ZMIAN)] + [ft.DropdownOption(s) for s in db.STREFY_KAROSERII],
            value=BRAK_ZMIAN,
            **utils.styl_dropdown()
        )
        e_typ = ft.Dropdown(
            label="Typ zdjęcia",
            options=[ft.DropdownOption(BRAK_ZMIAN)] + [ft.DropdownOption(t) for t in db.TYPY_ZDJECIA],
            value=BRAK_ZMIAN,
            **utils.styl_dropdown()
        )
        c_opis = ft.Checkbox(label="Zmień opis dla wszystkich zaznaczonych", value=False)
        e_opis = ft.TextField(label="Nowy opis", multiline=True, min_lines=2, max_lines=4, visible=False, **utils.styl_pola())

        def przelacz_opis(ev):
            e_opis.visible = c_opis.value
            e_opis.update()
        c_opis.on_change = przelacz_opis

        def zapisz(ev):
            strefa = e_strefa.value if e_strefa.value != BRAK_ZMIAN else None
            typ = e_typ.value if e_typ.value != BRAK_ZMIAN else None
            opis = e_opis.value if c_opis.value else None

            if strefa is None and typ is None and opis is None:
                utils.pokaz_komunikat(self._page, "Nie wybrano żadnej zmiany do zastosowania.", ft.Colors.ORANGE_700)
                return

            db.aktualizuj_wiele_zdjec_karoserii(ids, strefa=strefa, typ_porownania=typ, opis=opis)
            utils.zamknij_dialog(self._page, dlg)
            self.zakoncz_zaznaczanie()
            utils.przejdz(self._page, "/karoseria")
            utils.pokaz_komunikat(self._page, f"Zaktualizowano {ile} zdjęć.")

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([ft.Icon(ft.Icons.EDIT, color=ft.Colors.PRIMARY), ft.Text(f"Edycja zbiorcza ({ile})", weight="bold")], spacing=8),
            content=ft.Column([
                ft.Text("Zmień wybrane pola dla wszystkich zaznaczonych zdjęć naraz. Pozostaw „Bez zmian”, aby nie ruszać danego pola.", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                e_strefa,
                e_typ,
                c_opis,
                e_opis,
            ], tight=True, spacing=10, scroll=ft.ScrollMode.AUTO),
            actions=[
                ft.TextButton("Anuluj", on_click=lambda e2: utils.zamknij_dialog(self._page, dlg)),
                ft.ElevatedButton("Zapisz", on_click=zapisz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY)
            ],
            actions_alignment=ft.MainAxisAlignment.END
        )
        utils.otworz_dialog(self._page, dlg)

    def potwierdz_grupowe_usuwanie(self, e):
        ile = len(self.zaznaczone_id)
        
        def wykonaj():
            wynik = db.usun_wiele_z_cofnieciem(self.tabela_cel, list(self.zaznaczone_id))
            self.zakoncz_zaznaczanie()
            utils.przejdz(self._page, "/karoseria")
            utils.pokaz_komunikat_cofnij(self._page, f"Usunięto {ile} zdjęć.", wynik)
            
        utils.potwierdz(self._page, "Usuwanie grupowe", f"Czy na pewno usunąć {ile} zaznaczonych zdjęć?", wykonaj)

    def otworz_porownanie(self, e):
        ids = list(self.zaznaczone_id)
        with db.polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT data, strefa, zalacznik, opis FROM zdjecia_karoserii WHERE id IN (?, ?)", (ids[0], ids[1]))
            zdjecia = c.fetchall()

        if len(zdjecia) != 2: return

        # Starsze zdjęcie = "przed", nowsze = "po" (sortowanie po dacie)
        zdjecia.sort(key=lambda z: utils.parsuj_date(z[0]))
        (d_przed, s_przed, zal_przed, op_przed), (d_po, s_po, zal_po, op_po) = zdjecia

        SZER, WYS = 320, 420
        pozycja_startowa = SZER / 2

        obraz_po = ft.Image(src=utils.abs_zalacznik(zal_po), width=SZER, height=WYS, fit="cover")
        obraz_przed = ft.Image(src=utils.abs_zalacznik(zal_przed), width=SZER, height=WYS, fit="cover")

        # "Okienko ujawnienia": kontener o zmiennej szerokości = pozycja suwaka.
        # Obraz "przed" w środku ma PEŁNY rozmiar (SZER x WYS) i jest przypięty
        # (left=0, top=0) w Stacku — wystaje poza węższe okienko i zostaje
        # PRZYCIĘTY (nie przeskalowany) do widocznej części. Standardowa
        # technika sliderów porównawczych "przed/po".
        warstwa_przed = ft.Container(
            width=pozycja_startowa, height=WYS,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            content=ft.Stack([ft.Container(left=0, top=0, content=obraz_przed)]),
        )

        uchwyt_linia = ft.Container(width=3, height=WYS, bgcolor=ft.Colors.WHITE, left=pozycja_startowa - 1.5)
        uchwyt_kolko = ft.Container(
            width=36, height=36, border_radius=18, bgcolor=ft.Colors.WHITE,
            left=pozycja_startowa - 18, top=(WYS / 2) - 18, alignment=ft.Alignment.CENTER,
            shadow=ft.BoxShadow(blur_radius=8, color=ft.Colors.with_opacity(0.4, ft.Colors.BLACK)),
            content=ft.Icon(ft.Icons.COMPARE_ARROWS, color=ft.Colors.BLACK, size=18),
        )
        etykieta_przed = ft.Container(
            top=10, left=10, padding=ft.Padding(8, 4, 8, 4), border_radius=8,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
            content=ft.Text(f"PRZED • {d_przed}", size=11, weight="bold", color=ft.Colors.WHITE),
        )
        etykieta_po = ft.Container(
            top=10, right=10, padding=ft.Padding(8, 4, 8, 4), border_radius=8,
            bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
            content=ft.Text(f"PO • {d_po}", size=11, weight="bold", color=ft.Colors.WHITE),
        )

        obszar = ft.GestureDetector(
            content=ft.Stack([obraz_po, warstwa_przed, uchwyt_linia, uchwyt_kolko, etykieta_przed, etykieta_po], width=SZER, height=WYS),
            width=SZER, height=WYS,
        )

        def przesun(nowy_x):
            nowy_x = max(0.0, min(float(SZER), nowy_x))
            warstwa_przed.width = nowy_x
            uchwyt_linia.left = nowy_x - 1.5
            uchwyt_kolko.left = nowy_x - 18
            obszar.update()

        obszar.on_pan_update = lambda e2: przesun(e2.local_x)
        obszar.on_tap_down = lambda e2: przesun(e2.local_x)

        bits_podpisu = [f"{s_przed} → {s_po}" if s_przed != s_po else str(s_przed)]
        if op_przed: bits_podpisu.append(f"Przed: {op_przed}")
        if op_po: bits_podpisu.append(f"Po: {op_po}")

        dlg = ft.AlertDialog(
            title=ft.Row([
                ft.Icon(ft.Icons.COMPARE, color=ft.Colors.PRIMARY),
                ft.Text("Przeciągnij suwak, by porównać", weight="bold", size=15)
            ]),
            content=ft.Container(
                width=SZER,
                content=ft.Column([
                    ft.Container(
                        width=SZER, height=WYS, border_radius=12,
                        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                        content=obszar,
                    ),
                    ft.Text("  •  ".join(bits_podpisu), size=12, color=ft.Colors.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER),
                ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True)
            ),
            actions=[ft.TextButton("Zamknij", on_click=lambda e2: utils.zamknij_dialog(self._page, dlg))],
            content_padding=15
        )
        utils.otworz_dialog(self._page, dlg)
        self.zakoncz_zaznaczanie()

def _forma_zdjec(n):
    """Poprawna polska odmiana słowa 'zdjęcie' w zależności od liczby."""
    if n == 1:
        return "zdjęcie"
    ostatnia, dziesiatki = n % 10, n % 100
    if 2 <= ostatnia <= 4 and not (12 <= dziesiatki <= 14):
        return "zdjęcia"
    return "zdjęć"


class FormularzZdjecieKaroseriiView(ft.View):
    def __init__(self, page: ft.Page, state, wpis_id=None):
        self._page = page
        self.state = state
        self.wpis_id = wpis_id

        d_val = datetime.now().strftime("%d.%m.%Y")
        p_val = str(db.pobierz_aktualny_przebieg(self.state.auto_id) or "")
        strefa_val = db.STREFY_KAROSERII[0]
        typ_val = db.TYPY_ZDJECIA[0]
        opis_val = ""
        self.zalacznik_val = None

        if wpis_id:
            with db.polacz_baze() as conn:
                c = conn.cursor()
                c.execute("SELECT data, strefa, zalacznik, opis, przebieg, typ_porownania FROM zdjecia_karoserii WHERE id=?", (wpis_id,))
                w = c.fetchone()
                if w:
                    d_val, strefa_val, self.zalacznik_val = str(w[0]), str(w[1]), w[2]
                    opis_val, p_val, typ_val = str(w[3] or ""), str(w[4] or ""), str(w[5] or "Brak")

        # Edycja jednego, konkretnego zdjęcia -> pojedynczy załącznik.
        # Dodawanie nowych -> masowy wybór wielu zdjęć naraz; każde stanie się
        # osobnym wpisem w galerii ze wspólnymi metadanymi z formularza poniżej.
        if wpis_id:
            self.k_zalacznik, self.get_zalacznik = utils.komponent_zalacznika(page, self.zalacznik_val, tylko_zdjecie=True)
        else:
            self.k_zalacznik, self.get_wiele_zdjec = utils.komponent_wielu_nowych_zdjec(page)

        self.e_d = utils.pole_daty(page, "Data zrobienia zdjęcia", d_val)
        self.e_p = ft.TextField(label="Przebieg (km)", value=p_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola())

        self.e_strefa = ft.Dropdown(label="Strefa karoserii", options=[ft.DropdownOption(s) for s in db.STREFY_KAROSERII], value=strefa_val, **utils.styl_dropdown())
        self.e_typ = ft.Dropdown(label="Typ zdjęcia", options=[ft.DropdownOption(t) for t in db.TYPY_ZDJECIA], value=typ_val, **utils.styl_dropdown())
        self.e_opis = ft.TextField(label="Opis / Notatki", value=opis_val, multiline=True, min_lines=2, max_lines=4, **utils.styl_pola())

        self._stan_poczatkowy = self._migawka_formularza()
        appbar = utils.zbuduj_pasek_z_powrotem(
            page, "Edycja wpisu galerii" if wpis_id else "Nowe zdjęcia do rejestru", "/karoseria",
            on_save=self.zapisz, czy_zmieniono=self._czy_zmieniono
        )

        if wpis_id:
            k1 = utils.karta_formularza([self.k_zalacznik], "Wymagane zdjęcie", ft.Icons.ADD_A_PHOTO, domyslnie_otwarte=True)
            tytul_k2 = "Co widać na zdjęciu"
        else:
            opis_pomocy = ft.Text(
                "Zaznacz od razu kilka zdjęć — każde trafi jako osobny wpis w galerii, "
                "ze wspólną strefą/opisem/datą ustawionymi poniżej.",
                size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
            )
            k1 = utils.karta_formularza([opis_pomocy, self.k_zalacznik], "Zdjęcia", ft.Icons.ADD_A_PHOTO, domyslnie_otwarte=True)
            tytul_k2 = "Co widać na zdjęciach (wspólne dla wszystkich)"

        k2 = utils.karta_formularza([self.e_strefa, self.e_typ, self.e_opis], tytul_k2, ft.Icons.INFO_OUTLINE)
        k3 = utils.karta_formularza([self.e_d, self.e_p], "Kontekst", ft.Icons.SPEED)

        tekst_przycisku = "Zapisz zdjęcie" if wpis_id else "Zapisz zdjęcia"
        elementy = [k1, k2, k3, utils.przyciski_akcji(page, tekst_przycisku, self.zapisz, "/karoseria")]

        super().__init__(
            route=f"/karoseria/edytuj/{wpis_id}" if wpis_id else "/karoseria/nowe",
            padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO
        )

    def _migawka_formularza(self):
        podstawa = (self.e_d.value, self.e_p.value, self.e_strefa.value, self.e_typ.value, self.e_opis.value)
        if self.wpis_id:
            return podstawa
        return podstawa + (tuple(self.get_wiele_zdjec() or []),)

    def _czy_zmieniono(self):
        return self._migawka_formularza() != self._stan_poczatkowy

    def zapisz(self, e):
        for pole in (self.e_p, self.e_strefa, self.e_typ, self.e_opis): pole.error_text = None
        prz = utils.parsuj_int(self.e_p.value, 0)

        if self.wpis_id:
            wynik_komponentu = self.get_zalacznik()
            bedzie_zdjecie = (
                (wynik_komponentu is None and self.zalacznik_val) or
                (wynik_komponentu not in (None, ""))
            )
            if not bedzie_zdjecie:
                return utils.pokaz_komunikat(self._page, "Wymagane jest fizyczne zdjęcie!", ft.Colors.RED_700)

            przygotowany = db.przygotuj_nowy_zalacznik(wynik_komponentu)
            nowy_zalacznik = przygotowany if przygotowany is not None else self.zalacznik_val

            with db.polacz_baze() as conn:
                conn.execute(
                    "UPDATE zdjecia_karoserii SET data=?, strefa=?, zalacznik=?, opis=?, przebieg=?, typ_porownania=? WHERE id=?",
                    (self.e_d.value, self.e_strefa.value, nowy_zalacznik, self.e_opis.value, prz, self.e_typ.value, self.wpis_id)
                )
            db.zatwierdz_zalacznik(self.zalacznik_val, przygotowany)

            utils.przejdz(self._page, "/karoseria")
            utils.pokaz_komunikat(self._page, "Zapisano wpis w galerii!")
            return

        # --- Tryb masowego dodawania: jedno zdjęcie = jeden nowy wpis w galerii ---
        sciezki_zrodlowe = self.get_wiele_zdjec()
        if not sciezki_zrodlowe:
            return utils.pokaz_komunikat(self._page, "Wybierz co najmniej jedno zdjęcie!", ft.Colors.RED_700)

        przygotowane = []
        try:
            for sciezka in sciezki_zrodlowe:
                nowy = db.przygotuj_nowy_zalacznik(sciezka)
                if nowy:
                    przygotowane.append(nowy)

            if not przygotowane:
                return utils.pokaz_komunikat(self._page, "Nie udało się wczytać żadnego z wybranych zdjęć.", ft.Colors.RED_700)

            with db.polacz_baze() as conn:
                for zalacznik in przygotowane:
                    conn.execute(
                        "INSERT INTO zdjecia_karoserii (auto_id, data, strefa, zalacznik, opis, przebieg, typ_porownania) VALUES (?,?,?,?,?,?,?)",
                        (self.state.auto_id, self.e_d.value, self.e_strefa.value, zalacznik, self.e_opis.value, prz, self.e_typ.value)
                    )
        except Exception as ex:
            for zalacznik in przygotowane:
                db.anuluj_nowy_zalacznik(zalacznik)
            return utils.pokaz_komunikat(self._page, f"Błąd zapisu galerii: {ex}", ft.Colors.RED_700)

        utils.przejdz(self._page, "/karoseria")
        ile_wybranych, ile_zapisanych = len(sciezki_zrodlowe), len(przygotowane)
        if ile_zapisanych < ile_wybranych:
            utils.pokaz_komunikat(
                self._page,
                f"Zapisano {ile_zapisanych} z {ile_wybranych} zdjęć — część plików była niedostępna.",
                ft.Colors.ORANGE_700
            )
        else:
            utils.pokaz_komunikat(self._page, f"Dodano {ile_zapisanych} {_forma_zdjec(ile_zapisanych)} do galerii!")