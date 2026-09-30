import flet as ft
import asyncio
import os
import db
import utils


# Opis źródła „arkusz” — przy pliku z aplikacji z listy opis daje jej preset.
OPIS_ARKUSZA = ("Dowolny plik CSV z nagłówkami w pierwszym wierszu, także z aplikacji spoza listy — "
                "kolumny dopasujesz niżej.")


class ImportCSVView(ft.View):
    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state
        # Plik jako jedna tabela (arkusz, ręczne dopasowanie kolumn)…
        self.naglowki = []
        self.wiersze = []
        # …i jako surowe wiersze z sekcjami, które rozkłada preset aplikacji.
        self.wiersze_pliku = None
        self.nazwa_pliku = ""
        self.zrodlo = "arkusz"
        self._rozpoznana = None
        self.pojazd_w_pliku = None
        self.rozbior = None
        # Części importu: jedna przy arkuszu, po jednej na rodzaj wpisów przy
        # pliku z aplikacji. `dropdowny` to kolumny pierwszej części (przy
        # arkuszu — jedynej), `gotowe` to wpisy wszystkich włączonych części.
        self.czesci = []
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

        # Plik z innej aplikacji: preset zna jej układ (sekcje, kolumny,
        # formaty), więc zamiast klikać kolumny wybiera się aplikację. Plik
        # sam ją zdradza, więc po wczytaniu wybór ustawia się automatycznie.
        self.e_zrodlo = ft.Dropdown(
            label="Skąd jest plik?",
            options=[ft.DropdownOption(key="arkusz", text="Arkusz albo inna aplikacja")]
            + [ft.DropdownOption(key=k, text=v["etykieta"]) for k, v in db.PRESETY_IMPORTU.items()],
            value=self.zrodlo,
            on_select=self._zmien_zrodlo,
            **utils.styl_dropdown()
        )
        self.t_opis_zrodla = ft.Text(OPIS_ARKUSZA, size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT)

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
        # Plik z kilkoma autami (aCar, Simply Auto) — do tego w aplikacji
        # trafiają wpisy jednego z nich.
        self.e_pojazd = ft.Dropdown(
            label="Pojazd w pliku", options=[], visible=False,
            on_select=self._zmien_pojazd, **utils.styl_dropdown()
        )

        # Licznik i dystans z pliku: km albo mile. Nagłówek z „(mi)” / „(km)”
        # rozstrzyga sam, inaczej przyjmujemy jednostkę z Ustawień — i zawsze
        # można przełączyć. Do bazy wpisy trafiają w km.
        self.jednostka_pliku = utils.jednostka_dystansu()
        self._jednostka_rozpoznana = False
        self._jednostka_recznie = False
        self.przelacznik_jednostki_pliku = ft.Container(width=124)
        self.t_jednostka_pliku = ft.Text("", size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT)
        self.wiersz_jednostki_pliku = ft.Column([
            ft.Row([
                ft.Text("Licznik i dystans w pliku", size=13, expand=True),
                self.przelacznik_jednostki_pliku,
            ], spacing=utils.SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            self.t_jednostka_pliku,
        ], spacing=4)

        self.kolumna_mapowania = ft.Column([], spacing=10, visible=False)
        self.kolumna_podgladu = ft.Column([], spacing=6, visible=False)

        self.btn_importuj = ft.ElevatedButton(
            "Importuj",
            on_click=self._importuj,
            bgcolor=ft.Colors.GREEN_700, color=ft.Colors.WHITE,  # paleta: tożsamość — zielony przycisk akcji, nie stan
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12), padding=15),
            width=float("inf"), visible=False, disabled=True
        )

        self.t_info_arkusza = ft.Text(
            "Obsługiwane są separatory ';', ',' i tabulator oraz kodowania UTF-8 / Windows-1250. "
            "Pierwszy wiersz musi zawierać nagłówki kolumn.",
            size=12, color=ft.Colors.ON_SURFACE_VARIANT
        )
        k1 = utils.karta_formularza(
            [
                self.e_zrodlo,
                self.t_opis_zrodla,
                self.e_typ,
                self.t_opis_typu,
                ft.Divider(height=1),
                self.t_info_arkusza,
                self.btn_plik,
                self.t_plik,
                self.e_pojazd,
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
                allowed_extensions=["csv", "txt", "tsv", "zip"],
                allow_multiple=False
            )
        except Exception as ex:
            utils.pokaz_komunikat(self._page, f"Nie udało się otworzyć menedżera plików: {ex}", utils.KOLOR_STATUS["error"])
            return

        pliki = getattr(wynik, "files", wynik) if wynik is not None else None
        if not isinstance(pliki, list) or not pliki:
            return
        sciezka = getattr(pliki[0], "path", None)
        if not sciezka:
            utils.pokaz_komunikat(self._page, "Brak dostępu do pliku (uprawnienia telefonu).", utils.KOLOR_STATUS["error"])
            return

        try:
            wiersze = await asyncio.to_thread(db.wczytaj_wiersze_csv, sciezka)
        except Exception as ex:
            utils.pokaz_komunikat(self._page, f"Nie udało się wczytać pliku: {ex}", utils.KOLOR_STATUS["error"])
            return

        self._po_wczytaniu(os.path.basename(sciezka), wiersze)

    def _po_wczytaniu(self, nazwa, wiersze):
        """Plik wczytany: zapamiętuje go w obu postaciach i rozpoznaje
        aplikację. Rozpoznana ustawia się sama — wybór na liście przydaje się
        tylko wtedy, gdy plik nie zdradza, skąd jest."""
        self.wiersze_pliku = wiersze
        self.nazwa_pliku = nazwa
        self.naglowki, self.wiersze = db.tabela_z_wierszy(wiersze)
        self.pojazd_w_pliku = None
        self._rozpoznana = db.rozpoznaj_aplikacje(wiersze)
        if self._rozpoznana:
            self.zrodlo = self.e_zrodlo.value = self._rozpoznana
        self._odswiez_opisy()
        self._zbuduj_mapowanie()
        self._odswiez_podglad()

    def _preset(self):
        return db.PRESETY_IMPORTU.get(self.zrodlo)

    def _odswiez_opisy(self):
        """Opis źródła, napis na przycisku i to, co ma sens tylko przy arkuszu."""
        preset = self._preset()
        self.t_opis_zrodla.value = preset["opis"] if preset else OPIS_ARKUSZA
        for kontrolka in (self.e_typ, self.t_opis_typu, self.t_info_arkusza):
            kontrolka.visible = preset is None
        utils.ustaw_tekst_przycisku(self.btn_plik, f"Wybierz plik z {preset['etykieta']}" if preset else "Wybierz plik CSV")

    def _odswiez_opis_pliku(self):
        if self.wiersze_pliku is None:
            return
        preset = self._preset()
        if preset is None:
            self.t_plik.value = f"{self.nazwa_pliku} — {len(self.wiersze)} wierszy, {len(self.naglowki)} kolumn"
            return
        opis = f"{self.nazwa_pliku} — plik z {preset['etykieta']}"
        nazwa_auta = (self.rozbior or {}).get("nazwa_pojazdu")
        if nazwa_auta:
            opis += f", pojazd „{nazwa_auta}”"
        if self._rozpoznana == self.zrodlo:
            opis += " (rozpoznany po zawartości)"
        self.t_plik.value = opis

    def _zmien_zrodlo(self, e):
        """Inna aplikacja albo arkusz: ten sam plik czytany od nowa innym
        sposobem — dopasowanie i podgląd liczą się od zera."""
        self.zrodlo = self.e_zrodlo.value or "arkusz"
        self.pojazd_w_pliku = None
        self._odswiez_opisy()
        self._przebuduj()

    def _zmien_typ(self, e):
        """Zmiana typu unieważnia dopasowanie kolumn i podgląd — nagłówki pliku
        zostają, ale pola docelowe są już zupełnie inne."""
        self.typ_importu = self.e_typ.value or "tankowania"
        self.t_opis_typu.value = db.TYPY_IMPORTU[self.typ_importu]["opis"]
        self.gotowe = []
        self._przebuduj()

    def _zmien_pojazd(self, e):
        self.pojazd_w_pliku = self.e_pojazd.value or None
        self._przebuduj()

    def _przebuduj(self):
        if self.wiersze_pliku is not None or self.naglowki:
            self._zbuduj_mapowanie()
            self._odswiez_podglad()
        else:
            self.kolumna_mapowania.visible = False
            self.kolumna_podgladu.visible = False
            self.btn_importuj.visible = False
        self._page.update()

    def _ustal_jednostke_pliku(self):
        """Jednostka licznika w pliku: z presetu (Fuelio i aCar ją zapisują),
        z nagłówka kolumny licznika albo dystansu, a gdy plik milczy — z Ustawień."""
        rozpoznana = (self.rozbior or {}).get("jednostka")
        for czesc in self.czesci:
            if rozpoznana is None and db.TYPY_IMPORTU[czesc["typ"]].get("z_dystansem"):
                rozpoznana = db.rozpoznaj_jednostke_pliku(czesc["naglowki"], self._biezace_mapowanie(czesc))
        self._jednostka_rozpoznana = rozpoznana is not None
        self.jednostka_pliku = rozpoznana or utils.jednostka_dystansu()

    def _odswiez_jednostke_pliku(self):
        """Przełącznik, podpis pod nim i etykiety pól licznika/dystansu."""
        self.przelacznik_jednostki_pliku.content = utils.segmented_control(
            self._page, [(j, i) for i, j in enumerate(db.JEDNOSTKI_DYSTANSU)],
            db.JEDNOSTKI_DYSTANSU.index(self.jednostka_pliku), self._zmien_jednostke_pliku,
        )
        if self._jednostka_recznie:
            self.t_jednostka_pliku.value = "Wybrane ręcznie. W aplikacji wpisy i tak trafią do bazy w km."
        elif self._jednostka_rozpoznana:
            self.t_jednostka_pliku.value = "Rozpoznane z pliku." if self._preset() else "Rozpoznane z nagłówka kolumny."
        else:
            self.t_jednostka_pliku.value = (f"{'Plik' if self._preset() else 'Nagłówek'} nie mówi, w czym jest "
                                            "licznik — przyjęto jednostkę z Ustawień. Przełącz, jeśli plik jest "
                                            "w innej.")
        for czesc in self.czesci:
            pola = db.TYPY_IMPORTU[czesc["typ"]]["pola"]
            for pole in ("przebieg", "dystans"):
                if pole in czesc.get("dropdowny", {}) and pole in pola:
                    etykieta, wymagane = pola[pole]
                    czesc["dropdowny"][pole].label = (f"{db.etykieta_z_dystansem(etykieta, self.jednostka_pliku)}"
                                                      f"{' *' if wymagane else ''}")

    def _zmien_jednostke_pliku(self, idx):
        self.jednostka_pliku = db.JEDNOSTKI_DYSTANSU[idx]
        self._jednostka_recznie = True
        self._odswiez_jednostke_pliku()
        self._odswiez_podglad()

    def _zbuduj_czesci(self):
        """Części importu z bieżącego pliku: rozbiór presetu aplikacji albo
        jedna tabela arkusza z typem wybranym na górze."""
        self.rozbior = None
        preset = self._preset()
        if preset is not None and self.wiersze_pliku is not None:
            try:
                self.rozbior = db.rozbierz_plik_importu(self.zrodlo, self.wiersze_pliku, pojazd=self.pojazd_w_pliku)
            except Exception as ex:
                utils.pokaz_komunikat(self._page, f"Nie udało się odczytać pliku jako eksportu z "
                                                  f"{preset['etykieta']}: {ex}", utils.KOLOR_STATUS["error"])
                self.czesci = []
                return
            self.czesci = [dict(c, wlaczona=True) for c in self.rozbior["czesci"]]
            return
        konfig = db.TYPY_IMPORTU[self.typ_importu]
        self.czesci = [{
            "typ": self.typ_importu, "zrodlo": "", "naglowki": self.naglowki, "wiersze": self.wiersze,
            "numery": None, "mapowanie": konfig["dopasuj"](self.naglowki), "wlaczona": True,
        }]

    def _zbuduj_mapowanie(self):
        self._zbuduj_czesci()
        self._jednostka_recznie = False
        preset = self._preset()
        grupy = []
        for czesc in self.czesci:
            czesc["dropdowny"] = self._dropdowny_czesci(czesc)
            grupy.append(self._grupa_mapowania(czesc) if preset
                         else ft.Column(list(czesc["dropdowny"].values()), spacing=10))
        self.dropdowny = self.czesci[0]["dropdowny"] if self.czesci else {}
        self._ustal_jednostke_pliku()

        self.kolumna_mapowania.controls.clear()
        if preset and self.czesci:
            self.kolumna_mapowania.controls.append(utils.podpis(
                f"Kolumny ustawione według układu pliku z {preset['etykieta']}. Rozwiń rodzaj wpisów, "
                "żeby sprawdzić albo poprawić dopasowanie."))
        if any(db.TYPY_IMPORTU[c["typ"]].get("z_dystansem") for c in self.czesci):
            self.kolumna_mapowania.controls.append(self.wiersz_jednostki_pliku)
            self._odswiez_jednostke_pliku()
        self.kolumna_mapowania.controls.extend(grupy)
        self.kolumna_mapowania.visible = bool(self.czesci)

        pojazdy = (self.rozbior or {}).get("pojazdy") or []
        self.e_pojazd.options = [
            ft.DropdownOption(key=klucz, text=f"{etykieta} — {db.liczba_z_odmiana(ile, 'wpis', 'wpisy', 'wpisów')}")
            for klucz, etykieta, ile in pojazdy
        ]
        self.e_pojazd.value = (self.rozbior or {}).get("pojazd")
        self.e_pojazd.visible = len(pojazdy) > 1
        self._odswiez_opis_pliku()
        self._page.update()

    def _dropdowny_czesci(self, czesc):
        konfig = db.TYPY_IMPORTU[czesc["typ"]]
        mapowanie = czesc["mapowanie"]
        opcje = [ft.DropdownOption(key="", text="— nie importuj —")]
        opcje += [ft.DropdownOption(key=str(i), text=h or f"Kolumna {i + 1}") for i, h in enumerate(czesc["naglowki"])]

        # UWAGA: ft.Dropdown we Flecie 0.86 nie zna `on_change` — reaguje na
        # `on_select`. Wcześniejsza wersja tego ekranu przekazywała on_change
        # w konstruktorze, więc wybór pliku CSV kończył się TypeError i mapowanie
        # kolumn w ogóle się nie budowało.
        dropdowny = {}
        for pole, (etykieta, wymagane) in konfig["pola"].items():
            if pole == "litry" and self.elektryczny:
                etykieta = "Energia (kWh)"
            if pole == "stacja":
                etykieta = self.etykiety["punkt"]
            dropdowny[pole] = ft.Dropdown(
                label=f"{etykieta}{' *' if wymagane else ''}",
                options=list(opcje),
                value=str(mapowanie[pole]) if mapowanie.get(pole) is not None else "",
                on_select=self._odswiez_podglad,
                **utils.styl_dropdown()
            )
        return dropdowny

    def _grupa_mapowania(self, czesc):
        """Kolumny jednego rodzaju wpisów, zwinięte — przy pliku z aplikacji
        ustawia je preset, a rozwija się je tylko po to, żeby sprawdzić."""
        konfig = db.TYPY_IMPORTU[czesc["typ"]]
        cialo = ft.Column(list(czesc["dropdowny"].values()), spacing=10, visible=False)
        strzalka = ft.Icon(ft.Icons.KEYBOARD_ARROW_DOWN, size=20, color=ft.Colors.PRIMARY)

        def przelacz(e):
            cialo.visible = not cialo.visible
            utils.ustaw_ikone(strzalka, ft.Icons.KEYBOARD_ARROW_UP if cialo.visible else ft.Icons.KEYBOARD_ARROW_DOWN)
            self._page.update()

        wierszy = db.liczba_z_odmiana(len(czesc["wiersze"]), "wiersz", "wiersze", "wierszy")
        naglowek = ft.Container(
            on_click=przelacz,
            padding=ft.Padding(0, utils.SPACING["xs"], 0, utils.SPACING["xs"]),
            content=ft.Row([
                ft.Column([utils.wartosc(konfig["etykieta"]), utils.podpis(f"{czesc['zrodlo']} · {wierszy}")],
                          spacing=2, expand=True),
                strzalka,
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )
        return ft.Column([naglowek, cialo], spacing=6)

    def _biezace_mapowanie(self, czesc):
        dropdowny = czesc.get("dropdowny")
        if not dropdowny:
            return dict(czesc["mapowanie"])
        return {pole: int(dd.value) if (dd.value or "") != "" else None for pole, dd in dropdowny.items()}

    def _odswiez_podglad(self, e=None):
        if not self.wiersze and self.wiersze_pliku is None:
            return
        # Inna kolumna licznika może mieć inny nagłówek — dopóki człowiek sam
        # nie wybrał jednostki, rozpoznajemy ją od nowa.
        if e is not None and not self._jednostka_recznie and any(
                db.TYPY_IMPORTU[c["typ"]].get("z_dystansem") for c in self.czesci):
            self._ustal_jednostke_pliku()
            self._odswiez_jednostke_pliku()

        for czesc in self.czesci:
            czesc["raport"] = db.TYPY_IMPORTU[czesc["typ"]]["przygotuj"](
                self.state.auto_id, czesc["naglowki"], czesc["wiersze"], self._biezace_mapowanie(czesc),
                jednostka_pliku=self.jednostka_pliku, numery_wierszy=czesc["numery"],
            )
        self.gotowe = [g for c in self.czesci if c["wlaczona"] for g in c["raport"]["gotowe"]]

        if self._preset() is None:
            tresc = self._podglad_arkusza(self.czesci[0]) if self.czesci else []
        else:
            tresc = self._podglad_pliku()

        self.kolumna_podgladu.controls = tresc
        self.kolumna_podgladu.visible = True
        self.btn_importuj.visible = bool(self.czesci)
        self.btn_importuj.disabled = not self.gotowe
        utils.ustaw_tekst_przycisku(
            self.btn_importuj,
            f"Importuj {db.liczba_z_odmiana(len(self.gotowe), 'wpis', 'wpisy', 'wpisów')}" if self.gotowe else "Importuj")
        self._page.update()

    def _podglad_arkusza(self, czesc):
        raport = czesc["raport"]
        tresc = [
            ft.Row([
                ft.Icon(ft.Icons.CHECK_CIRCLE, size=16, color=utils.KOLOR_STATUS["ok"]),
                ft.Text(f"Do dodania: {len(raport['gotowe'])}", size=13, weight="bold", expand=True),
            ], spacing=6),
            ft.Row([
                ft.Icon(ft.Icons.CONTENT_COPY, size=16, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Text(f"Pominięte duplikaty: {raport['duplikaty']}", size=13, expand=True),
            ], spacing=6),
            ft.Row([
                ft.Icon(ft.Icons.ERROR_OUTLINE, size=16,
                        color=utils.KOLOR_STATUS["error"] if raport["bledy"] else ft.Colors.ON_SURFACE_VARIANT),
                ft.Text(f"Wiersze z błędami: {len(raport['bledy'])}", size=13, expand=True),
            ], spacing=6),
        ]
        tresc += self._bledy(raport["bledy"], 5)
        if raport["gotowe"]:
            tresc.append(ft.Divider(height=10))
            tresc.append(ft.Text("Pierwsze wpisy do zaimportowania:", size=12, weight="bold"))
            tresc += self._pierwsze_wpisy(czesc)
        return tresc

    def _podglad_pliku(self):
        """Plik z aplikacji: każdy rodzaj wpisów osobno, z przełącznikiem, a pod
        spodem to, czego z pliku nie bierzemy — pominięte wiersze i uwagi."""
        preset = self._preset()
        if not self.czesci:
            return [ft.Text(
                f"W pliku nie ma tankowań, wydatków ani serwisu w układzie {preset['etykieta']}. Sprawdź, "
                "czy to właściwy plik, albo wybierz „Arkusz albo inna aplikacja” i dopasuj kolumny sam.",
                size=12, color=utils.KOLOR_STATUS["error"])]
        tresc = []
        for numer, czesc in enumerate(self.czesci):
            if numer:
                tresc.append(ft.Divider(height=10))
            tresc += self._podglad_czesci(czesc)
        pominiete = self.rozbior["pominiete"]
        if pominiete or self.rozbior["uwagi"]:
            tresc.append(ft.Divider(height=10))
        if pominiete:
            tresc.append(utils.podpis(
                "Pominięte w pliku: " + ", ".join(f"{powod} ({ile})" for powod, ile in pominiete) + "."))
        tresc += [utils.podpis(uwaga) for uwaga in self.rozbior["uwagi"]]
        return tresc

    def _podglad_czesci(self, czesc):
        konfig = db.TYPY_IMPORTU[czesc["typ"]]
        raport = czesc["raport"]
        gotowe = raport["gotowe"]
        tresc = [
            ft.Switch(
                label=f"{konfig['etykieta']}: {db.liczba_z_odmiana(len(gotowe), 'nowy wpis', 'nowe wpisy', 'nowych wpisów')}",
                value=czesc["wlaczona"] and bool(gotowe),
                disabled=not gotowe,
                on_change=lambda e, c=czesc: self._przelacz_czesc(c, bool(e.control.value)),
            ),
            utils.podpis(f"{czesc['zrodlo']} · pominięte duplikaty: {raport['duplikaty']} · "
                         f"wiersze z błędami: {len(raport['bledy'])}"),
        ]
        tresc += self._bledy(raport["bledy"], 3)
        if gotowe and czesc["wlaczona"]:
            tresc += self._pierwsze_wpisy(czesc)
        return tresc

    def _bledy(self, bledy, ile):
        tresc = [ft.Text(f"• wiersz {nr}: {powod}", size=11, color=utils.KOLOR_STATUS["error"])
                 for nr, powod in bledy[:ile]]
        if len(bledy) > ile:
            tresc.append(ft.Text(f"…i {len(bledy) - ile} kolejnych", size=11, italic=True,
                                 color=ft.Colors.ON_SURFACE_VARIANT))
        return tresc

    def _pierwsze_wpisy(self, czesc):
        buduj_opis = db.TYPY_IMPORTU[czesc["typ"]]["podglad"]
        return [ft.Text(buduj_opis(g, self.etykiety["jednostka"]), size=11, color=ft.Colors.ON_SURFACE_VARIANT)
                for g in czesc["raport"]["gotowe"][:3]]

    def _przelacz_czesc(self, czesc, wlaczona):
        czesc["wlaczona"] = wlaczona
        self._odswiez_podglad()

    def _wybrane_czesci(self):
        return [c for c in self.czesci if c["wlaczona"] and (c.get("raport") or {}).get("gotowe")]

    def _zapisz_czesci(self):
        """Zapis wszystkich włączonych części — każdej funkcją jej typu
        z TYPY_IMPORTU. Zwraca {typ: liczba dodanych wpisów}."""
        return {c["typ"]: db.TYPY_IMPORTU[c["typ"]]["zapisz"](self.state.auto_id, c["raport"]["gotowe"])
                for c in self._wybrane_czesci()}

    def _importuj(self, e):
        wybrane = self._wybrane_czesci()
        if not wybrane:
            return
        sklad = ", ".join(f"{db.TYPY_IMPORTU[c['typ']]['etykieta'].lower()}: {len(c['raport']['gotowe'])}"
                          for c in wybrane)

        def wykonaj():
            async def _zrob():
                dlg = utils.pokaz_ladowanie(self._page, "Importowanie wpisów...")
                try:
                    ile = await asyncio.to_thread(self._zapisz_czesci)
                    utils.ukryj_ladowanie(self._page, dlg)
                    utils.wypchnij_w_tle(self._page, self.state.auto_id, "import CSV")
                    utils.przejdz(self._page, "/")
                    razem = db.liczba_z_odmiana(sum(ile.values()), "wpis", "wpisy", "wpisów")
                    utils.pokaz_komunikat(self._page, f"Zaimportowano {razem}" + (f" ({sklad})." if len(ile) > 1 else "."))
                except Exception as ex:
                    utils.ukryj_ladowanie(self._page, dlg)
                    utils.pokaz_komunikat(self._page, f"Błąd importu: {ex}", utils.KOLOR_STATUS["error"])
            self._page.run_task(_zrob)

        utils.potwierdz(
            self._page,
            "Zaimportować wpisy?",
            f"Do pojazdu „{self.state.auto_nazwa}” trafi "
            f"{db.liczba_z_odmiana(len(self.gotowe), 'nowy wpis', 'nowe wpisy', 'nowych wpisów')} "
            f"({sklad}). "
            f"Duplikaty są już odfiltrowane. Operacji nie da się cofnąć jednym kliknięciem "
            f"— w razie czego zrób najpierw kopię bazy.",
            wykonaj,
            tekst_potwierdzenia="Importuj"
        )
