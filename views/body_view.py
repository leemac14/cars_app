import flet as ft
from datetime import datetime
import db
import utils

class KaroseriaView(ft.View, utils.ZaznaczanieGrupowe):
    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state

        appbar = utils.zbuduj_pasek_z_powrotem(page, "📸 Rejestr Karoserii", "/")
        
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

            pole_szukaj = ft.TextField(hint_text="Szukaj (strefa, opis, typ)...", prefix_icon=ft.Icons.SEARCH, on_change=filtruj_galerie, **utils.styl_pola())
            
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
                
                kontener = ft.Container(
                    width=165, padding=10, border_radius=12,
                    bgcolor=ft.Colors.with_opacity(0.04, ft.Colors.ON_SURFACE),
                    content=ft.Column([
                        ft.Image(src=utils.abs_zalacznik(z_zal), height=110, width=165, fit="cover", border_radius=8),
                        ft.Text(f"{z_data} • {z_strefa}", size=12, weight="bold", no_wrap=True),
                        ft.Text(str(z_typ) if z_typ != "Brak" else "Zwykłe", size=11, color=kolor_typu, weight="bold")
                    ], spacing=4)
                )
                self.karty_ref[z_id] = kontener
                self.podepnij_zdarzenia_grupowe(kontener, z_id, lambda zid=z_id, zal=z_zal: otworz_menu(zid, zal))
                
                self.wszystkie_karty.append({"karta": kontener, "szukaj": f"{z_strefa} {z_opis} {z_typ} {z_data}".lower()})
                self.lista_kart.controls.append(kontener)

            elementy.append(self.lista_kart)

        elementy.append(utils.dol_bezpieczny(10))

        super().__init__(
            route="/karoseria", padding=15, spacing=15,
            scroll=ft.ScrollMode.AUTO,
            appbar=appbar, floating_action_button=fab, controls=elementy
        )

    # --- NOWE: Wymuszenie zaznaczania z menu kontekstowego zdjęcia ---
    def wymus_tryb_zaznaczania(self, element_id):
        self.tryb_zaznaczania = True
        self.zaznacz_odznacz(element_id, self.karty_ref[element_id])
        utils.pokaz_komunikat(self._page, "Zaznacz jeszcze jedno zdjęcie do porównania.", ft.Colors.PRIMARY)

    def aktualizuj_appbar_zaznaczania(self, dodatkowe_akcje=None):
        extra = []
        if len(self.zaznaczone_id) == 2:
            extra.append(ft.IconButton(ft.Icons.COMPARE, tooltip="Porównaj zaznaczone", on_click=self.otworz_porownanie))
        super().aktualizuj_appbar_zaznaczania(dodatkowe_akcje=extra)

    def potwierdz_grupowe_usuwanie(self, e):
        ile = len(self.zaznaczone_id)
        
        def wykonaj():
            wynik = db.usun_wiele_z_cofnieciem(self.tabela_cel, list(self.zaznaczone_id))
            self.zakoncz_zaznaczanie()
            utils.przejdz(self._page, "/karoseria")
            utils.pokaz_komunikat_cofnij(self._page, f"Usunięto {ile} zdjęć.", wynik)
            
        utils.potwierdz(self._page, "Usuwanie grupowe", f"Czy na pewno usunąć {ile} zaznaczonych zdjęć?", wykonaj)

    # --- NOWE: Porównanie w locie w ładnym oknie dialogowym ---
    def otworz_porownanie(self, e):
        ids = list(self.zaznaczone_id)
        with db.polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT data, strefa, zalacznik, opis FROM zdjecia_karoserii WHERE id IN (?, ?)", (ids[0], ids[1]))
            zdjecia = c.fetchall()
            
        if len(zdjecia) != 2: return
        
        # Sortujemy starsze na górę, nowsze na dół na podstawie daty
        zdjecia.sort(key=lambda z: utils.parsuj_date(z[0]))
        z1, z2 = zdjecia

        def zbuduj_obraz(z):
            d_val, s_val, zal_val, op_val = z
            return ft.Column([
                ft.Text(f"{d_val} • {s_val}", weight="bold", size=14, color=ft.Colors.PRIMARY),
                ft.Image(src=utils.abs_zalacznik(zal_val), fit="contain", border_radius=8, expand=True),
                ft.Text(str(op_val) if op_val else "Brak opisu", size=12, color=ft.Colors.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER)
            ], expand=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER)

        dlg = ft.AlertDialog(
            title=ft.Row([
                ft.Icon(ft.Icons.COMPARE, color=ft.Colors.PRIMARY),
                ft.Text("Porównanie", weight="bold")
            ]),
            content=ft.Container(
                width=350, height=600,
                content=ft.Column([
                    zbuduj_obraz(z1),
                    ft.Divider(height=20, color=ft.Colors.with_opacity(0.5, ft.Colors.PRIMARY)),
                    zbuduj_obraz(z2)
                ], spacing=10)
            ),
            actions=[ft.TextButton("Zamknij", on_click=lambda e: utils.zamknij_dialog(self._page, dlg))],
            content_padding=15
        )
        utils.otworz_dialog(self._page, dlg)
        self.zakoncz_zaznaczanie()

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

        self.k_zalacznik, self.get_zalacznik = utils.komponent_zalacznika(page, self.zalacznik_val)
        self.e_d = utils.pole_daty(page, "Data zrobienia zdjęcia", d_val)
        self.e_p = ft.TextField(label="Przebieg (km)", value=p_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola())
        
        self.e_strefa = ft.Dropdown(label="Strefa karoserii", options=[ft.DropdownOption(s) for s in db.STREFY_KAROSERII], value=strefa_val, **utils.styl_dropdown())
        self.e_typ = ft.Dropdown(label="Typ zdjęcia", options=[ft.DropdownOption(t) for t in db.TYPY_ZDJECIA], value=typ_val, **utils.styl_dropdown())
        self.e_opis = ft.TextField(label="Opis / Notatki", value=opis_val, multiline=True, min_lines=2, max_lines=4, **utils.styl_pola())

        appbar = utils.zbuduj_pasek_z_powrotem(page, "Edycja wpisu galerii" if wpis_id else "Nowe zdjęcie do rejestru", "/karoseria", on_save=self.zapisz)

        k1 = utils.karta_formularza([self.k_zalacznik], "Wymagane zdjęcie", ft.Icons.ADD_A_PHOTO)
        k2 = utils.karta_formularza([self.e_strefa, self.e_typ, self.e_opis], "Co widać na zdjęciu", ft.Icons.INFO_OUTLINE)
        k3 = utils.karta_formularza([self.e_d, self.e_p], "Kontekst", ft.Icons.SPEED)

        elementy = [k1, k2, k3, utils.przyciski_akcji(page, "✅ Zapisz zdjęcie", self.zapisz, "/karoseria")]

        super().__init__(
            route=f"/karoseria/edytuj/{wpis_id}" if wpis_id else "/karoseria/nowe",
            padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO
        )

    def zapisz(self, e):
        for pole in (self.e_p, self.e_strefa, self.e_typ, self.e_opis): pole.error_text = None

        wynik_komponentu = self.get_zalacznik()
        bedzie_zdjecie = (
            (wynik_komponentu is None and self.zalacznik_val) or  # nic nie zmieniono, zostaje stare
            (wynik_komponentu not in (None, ""))                   # wybrano nowe
        )
        if not bedzie_zdjecie:
            return utils.pokaz_komunikat(self._page, "Wymagane jest fizyczne zdjęcie!", ft.Colors.RED_700)

        przygotowany = db.przygotuj_nowy_zalacznik(wynik_komponentu)
        nowy_zalacznik = przygotowany if przygotowany is not None else self.zalacznik_val

        prz = utils.parsuj_int(self.e_p.value, 0)

        with db.polacz_baze() as conn:
            if self.wpis_id:
                conn.execute(
                    "UPDATE zdjecia_karoserii SET data=?, strefa=?, zalacznik=?, opis=?, przebieg=?, typ_porownania=? WHERE id=?", 
                    (self.e_d.value, self.e_strefa.value, nowy_zalacznik, self.e_opis.value, prz, self.e_typ.value, self.wpis_id)
                )
            else:
                conn.execute(
                    "INSERT INTO zdjecia_karoserii (auto_id, data, strefa, zalacznik, opis, przebieg, typ_porownania) VALUES (?,?,?,?,?,?,?)", 
                    (self.state.auto_id, self.e_d.value, self.e_strefa.value, nowy_zalacznik, self.e_opis.value, prz, self.e_typ.value)
                )

        db.zatwierdz_zalacznik(self.zalacznik_val, przygotowany)

        utils.przejdz(self._page, "/karoseria")
        utils.pokaz_komunikat(self._page, "Zapisano wpis w galerii!")