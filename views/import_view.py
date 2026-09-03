import flet as ft
import asyncio
import os
import db
import utils


class ImportCSVView(ft.View):
    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state
        self.naglowki = []
        self.wiersze = []
        self.dropdowny = {}
        self.gotowe = []

        appbar = utils.zbuduj_pasek_z_powrotem(page, "Import z pliku CSV", "/", ikona=ft.Icons.FILE_DOWNLOAD)

        if not self.state.auto_id:
            super().__init__(
                route="/import", padding=15, spacing=15, appbar=appbar,
                controls=[utils.ekran_braku_danych(
                    ikona=ft.Icons.DIRECTIONS_CAR,
                    tytul="Brak wybranego pojazdu",
                    opis="Wybierz pojazd, do którego mają trafić importowane wpisy.",
                    tekst_przycisku="Wróć na start",
                    on_click=lambda e: utils.przejdz(self._page, "/")
                )]
            )
            return

        self.elektryczny = db.czy_pojazd_elektryczny(self.state.auto_id)
        self.etykiety = db.etykiety_paliwa(self.elektryczny)

        # Import obsługuje kilka rodzajów wpisów; różnią się tylko zestawem
        # kolumn i walidacją, więc widok jest jeden, a typ wybiera się na górze.
        self.typ_importu = "tankowania"
        self.e_typ = ft.Dropdown(
            label="Co importujesz?",
            options=[ft.DropdownOption(key=k, text=v["etykieta"]) for k, v in db.TYPY_IMPORTU.items()],
            value=self.typ_importu,
            on_select=self._zmien_typ,
            **utils.styl_dropdown()
        )
        self.t_opis_typu = ft.Text(
            db.TYPY_IMPORTU[self.typ_importu]["opis"],
            size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
        )

        self.t_plik = ft.Text("Nie wybrano jeszcze pliku.", size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        self.btn_plik = ft.ElevatedButton(
            "Wybierz plik CSV",
            on_click=lambda e: self._page.run_task(self._wybierz_plik),
            bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12), padding=15),
            width=float("inf")
        )

        self.kolumna_mapowania = ft.Column([], spacing=10, visible=False)
        self.kolumna_podgladu = ft.Column([], spacing=6, visible=False)

        self.btn_importuj = ft.ElevatedButton(
            "Importuj",
            on_click=self._importuj,
            bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12), padding=15),
            width=float("inf"), visible=False, disabled=True
        )

        k1 = utils.karta_formularza(
            [
                self.e_typ,
                self.t_opis_typu,
                ft.Divider(height=1),
                ft.Text(
                    "Wczytaj historię z arkusza albo z innej aplikacji. Obsługiwane są separatory "
                    "';', ',' i tabulator oraz kodowania UTF-8 / Windows-1250. Pierwszy wiersz "
                    "musi zawierać nagłówki kolumn.",
                    size=12, color=ft.Colors.ON_SURFACE_VARIANT
                ),
                self.btn_plik,
                self.t_plik,
            ],
            "Plik źródłowy", ft.Icons.UPLOAD_FILE, domyslnie_otwarte=True
        )
        k2 = utils.karta_formularza([self.kolumna_mapowania], "Dopasowanie kolumn", ft.Icons.SWAP_HORIZ, domyslnie_otwarte=True)
        k3 = utils.karta_formularza([self.kolumna_podgladu], "Podgląd", ft.Icons.PREVIEW, domyslnie_otwarte=True)

        super().__init__(
            route="/import", padding=15, spacing=15, appbar=appbar,
            controls=[k1, k2, k3, self.btn_importuj, utils.dol_bezpieczny(30)],
            scroll=ft.ScrollMode.AUTO
        )

    async def _wybierz_plik(self):
        try:
            wynik = await self._page.zalacznik_picker.pick_files(
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["csv", "txt", "tsv"],
                allow_multiple=False
            )
        except Exception as ex:
            utils.pokaz_komunikat(self._page, f"Nie udało się otworzyć menedżera plików: {ex}", ft.Colors.RED_700)
            return

        pliki = getattr(wynik, "files", wynik) if wynik is not None else None
        if not isinstance(pliki, list) or not pliki:
            return
        sciezka = getattr(pliki[0], "path", None)
        if not sciezka:
            utils.pokaz_komunikat(self._page, "Brak dostępu do pliku (uprawnienia telefonu).", ft.Colors.RED_700)
            return

        try:
            self.naglowki, self.wiersze = await asyncio.to_thread(db.wczytaj_plik_csv, sciezka)
        except Exception as ex:
            utils.pokaz_komunikat(self._page, f"Nie udało się wczytać pliku: {ex}", ft.Colors.RED_700)
            return

        self.t_plik.value = f"{os.path.basename(sciezka)} — {len(self.wiersze)} wierszy, {len(self.naglowki)} kolumn"
        self._zbuduj_mapowanie()
        self._odswiez_podglad()

    def _konfiguracja(self):
        return db.TYPY_IMPORTU[self.typ_importu]

    def _zmien_typ(self, e):
        """Zmiana typu unieważnia dopasowanie kolumn i podgląd — nagłówki pliku
        zostają, ale pola docelowe są już zupełnie inne."""
        self.typ_importu = self.e_typ.value or "tankowania"
        self.t_opis_typu.value = self._konfiguracja()["opis"]
        self.gotowe = []
        if self.naglowki:
            self._zbuduj_mapowanie()
            self._odswiez_podglad()
        else:
            self.kolumna_mapowania.visible = False
            self.kolumna_podgladu.visible = False
            self.btn_importuj.visible = False
        self._page.update()

    def _zbuduj_mapowanie(self):
        konfig = self._konfiguracja()
        mapowanie = konfig["dopasuj"](self.naglowki)
        opcje = [ft.DropdownOption(key="", text="— nie importuj —")]
        opcje += [ft.DropdownOption(key=str(i), text=h or f"Kolumna {i + 1}") for i, h in enumerate(self.naglowki)]

        # UWAGA: ft.Dropdown we Flecie 0.86 nie zna `on_change` — reaguje na
        # `on_select`. Wcześniejsza wersja tego ekranu przekazywała on_change
        # w konstruktorze, więc wybór pliku CSV kończył się TypeError i mapowanie
        # kolumn w ogóle się nie budowało.
        self.dropdowny = {}
        self.kolumna_mapowania.controls.clear()
        for pole, (etykieta, wymagane) in konfig["pola"].items():
            if pole == "litry" and self.elektryczny:
                etykieta = "Energia (kWh)"
            if pole == "stacja":
                etykieta = self.etykiety["punkt"]
            dd = ft.Dropdown(
                label=f"{etykieta}{' *' if wymagane else ''}",
                options=list(opcje),
                value=str(mapowanie[pole]) if mapowanie.get(pole) is not None else "",
                on_select=self._odswiez_podglad,
                **utils.styl_dropdown()
            )
            self.dropdowny[pole] = dd
            self.kolumna_mapowania.controls.append(dd)

        self.kolumna_mapowania.visible = True
        self._page.update()

    def _biezace_mapowanie(self):
        wynik = {}
        for pole, dd in self.dropdowny.items():
            wynik[pole] = int(dd.value) if (dd.value or "") != "" else None
        return wynik

    def _odswiez_podglad(self, e=None):
        if not self.wiersze:
            return
        raport = self._konfiguracja()["przygotuj"](
            self.state.auto_id, self.naglowki, self.wiersze, self._biezace_mapowanie()
        )
        self.gotowe = raport["gotowe"]

        tresc = [
            ft.Row([
                ft.Icon(ft.Icons.CHECK_CIRCLE, size=16, color=ft.Colors.GREEN_700),
                ft.Text(f"Do dodania: {len(self.gotowe)}", size=13, weight="bold"),
            ], spacing=6),
            ft.Row([
                ft.Icon(ft.Icons.CONTENT_COPY, size=16, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Text(f"Pominięte duplikaty: {raport['duplikaty']}", size=13),
            ], spacing=6),
            ft.Row([
                ft.Icon(ft.Icons.ERROR_OUTLINE, size=16,
                        color=ft.Colors.RED_700 if raport["bledy"] else ft.Colors.ON_SURFACE_VARIANT),
                ft.Text(f"Wiersze z błędami: {len(raport['bledy'])}", size=13),
            ], spacing=6),
        ]

        for nr, powod in raport["bledy"][:5]:
            tresc.append(ft.Text(f"• wiersz {nr}: {powod}", size=11, color=ft.Colors.RED_700))
        if len(raport["bledy"]) > 5:
            tresc.append(ft.Text(f"…i {len(raport['bledy']) - 5} kolejnych", size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT))

        if self.gotowe:
            tresc.append(ft.Divider(height=10))
            tresc.append(ft.Text("Pierwsze wpisy do zaimportowania:", size=12, weight="bold"))
            buduj_opis = self._konfiguracja()["podglad"]
            for g in self.gotowe[:3]:
                tresc.append(ft.Text(buduj_opis(g, self.etykiety["jednostka"]),
                                     size=11, color=ft.Colors.ON_SURFACE_VARIANT))

        self.kolumna_podgladu.controls = tresc
        self.kolumna_podgladu.visible = True
        self.btn_importuj.visible = True
        self.btn_importuj.disabled = not self.gotowe
        self.btn_importuj.text = f"Importuj {len(self.gotowe)} wpisów" if self.gotowe else "Importuj"
        self._page.update()

    def _importuj(self, e):
        if not self.gotowe:
            return

        def wykonaj():
            async def _zrob():
                dlg = utils.pokaz_ladowanie(self._page, "Importowanie wpisów...")
                try:
                    ile = await asyncio.to_thread(self._konfiguracja()["zapisz"], self.state.auto_id, self.gotowe)
                    utils.ukryj_ladowanie(self._page, dlg)
                    utils.wypchnij_w_tle(self._page, self.state.auto_id, "import CSV")
                    utils.przejdz(self._page, "/")
                    utils.pokaz_komunikat(self._page, f"Zaimportowano {ile} wpisów.")
                except Exception as ex:
                    utils.ukryj_ladowanie(self._page, dlg)
                    utils.pokaz_komunikat(self._page, f"Błąd importu: {ex}", ft.Colors.RED_700)
            self._page.run_task(_zrob)

        utils.potwierdz(
            self._page,
            "Zaimportować wpisy?",
            f"Do pojazdu „{self.state.auto_nazwa}” zostanie dodanych {len(self.gotowe)} wpisów "
            f"({self._konfiguracja()['etykieta'].lower()}). "
            f"Duplikaty są już odfiltrowane. Operacji nie da się cofnąć jednym kliknięciem "
            f"— w razie czego zrób najpierw kopię bazy.",
            wykonaj,
            tekst_potwierdzenia="Importuj"
        )
