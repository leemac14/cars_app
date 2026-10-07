import flet as ft

import db
import utils


class DoWpisaniaView(ft.View):
    """„Do wpisania” (M-08) — kolejka paragonów od najstarszego. Przycisk rodzaju
    otwiera formularz z datą, zdjęciem i podglądem paragonu; po zapisie szkic znika, a
    formularz wraca tutaj, dopóki coś czeka. Dane: db/szkice.py; pola, miniatury,
    migawka: utils/szkice.py."""

    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state

        appbar = utils.zbuduj_pasek_z_powrotem(page, "Do wpisania", "/", ikona=ft.Icons.PENDING_ACTIONS)

        if not state.auto_id:
            super().__init__(
                route="/do-wpisania", padding=15, spacing=15, appbar=appbar,
                controls=[utils.ekran_braku_danych(
                    ikona=ft.Icons.DIRECTIONS_CAR, tytul="Brak wybranego pojazdu",
                    opis="Dodaj pojazd, a paragony sfotografowane przy dystrybutorze poczekają tu na wpisanie.",
                    tekst_przycisku="Dodaj pojazd",
                    on_click=lambda e: utils.przejdz(self._page, "/auto/nowy"),
                )],
            )
            return

        self.aparat = utils.aparat_dostepny(page)
        self.moge_dodawac = db.czy_moge_dodawac(state.auto_id)
        # Przenieść wolno tylko tam, gdzie da się potem wpisać — nie do auta „tylko podgląd”.
        self.inne_pojazdy = [(aid, nazwa) for aid, nazwa in db.pobierz_pojazdy()
                             if aid != state.auto_id and db.czy_moge_dodawac(aid)]
        szkice = db.pobierz_szkice(state.auto_id)

        elementy = []
        if not szkice:
            elementy.append(self._pusto())
        else:
            elementy.append(self._naglowek(len(szkice)))
            elementy.extend(self._karta(s) for s in szkice)
        elementy.append(utils.dol_bezpieczny(80))  # miejsce pod FAB-em

        fab = None
        if self.moge_dodawac:
            fab = utils.fab_animowany(
                ft.Icons.PHOTO_CAMERA if self.aparat else ft.Icons.ADD_PHOTO_ALTERNATE,
                lambda e: utils.otworz_migawke(self._page, self.state),
                tooltip="Zrób zdjęcie paragonu" if self.aparat else "Dodaj zdjęcia paragonów",
            )
        super().__init__(
            route="/do-wpisania", padding=15, spacing=10, appbar=appbar,
            floating_action_button=fab, controls=elementy, scroll=ft.ScrollMode.AUTO,
        )

    # ================= AKCJE =================

    def _odswiez(self):
        utils.odswiez_ekran(self._page)

    def _z_galerii(self, e=None):
        utils.wybierz_z_galerii(self._page, self.state, po_dodaniu=self._odswiez)

    def _wpisz(self, szkic, rodzaj):
        utils.przejdz(self._page, utils.trasa_uzupelnienia(rodzaj, szkic["id"]))

    def _usun(self, szkic):
        def wykonaj():
            # Zdjęcie idzie do folderu odroczonych i wraca przy „Cofnij” —
            # ogólny mechanizm usuwania, jak przy każdym wpisie z załącznikiem.
            wynik = db.usun_z_cofnieciem(db.TABELA_SZKICOW, szkic["id"])
            self._odswiez()
            utils.pokaz_komunikat_cofnij(self._page, f"Usunięto paragon z {szkic['data']}.", wynik)

        utils.potwierdz(self._page, "Usunąć szkic?",
                        "Zdjęcie paragonu zniknie razem ze szkicem — nic nie zostanie wpisane.", wykonaj)

    def _przenies(self, szkic):
        def na(auto_id, nazwa):
            def handler(e):
                utils.zamknij_dialog(self._page, dlg)
                if db.przenies_szkic(szkic["id"], auto_id):
                    self._odswiez()
                    utils.pokaz_komunikat(self._page, f"Przeniesiono paragon do: {nazwa}")
            return handler

        dlg = ft.AlertDialog(
            title=ft.Text("Do którego pojazdu?", size=utils.FS["heading"], weight="bold"),
            content=ft.Column([
                ft.ListTile(leading=ft.Icon(ft.Icons.DIRECTIONS_CAR), title=ft.Text(nazwa), on_click=na(aid, nazwa))
                for aid, nazwa in self.inne_pojazdy
            ], tight=True, spacing=0),
            actions=[ft.TextButton("Anuluj", on_click=lambda e: utils.zamknij_dialog(self._page, dlg))],
        )
        utils.otworz_dialog(self._page, dlg)

    def _menu(self, szkic):
        auto_id = self.state.auto_id
        pozycje = []
        if self.moge_dodawac:
            for rodzaj in db.RODZAJE_SZKICU:
                etykieta = utils.etykieta_rodzaju_szkicu(rodzaj, auto_id).lower()
                pozycje.append({"ikona": utils.IKONY_RODZAJU_SZKICU[rodzaj], "tekst": f"Wpisz jako: {etykieta}",
                                "akcja": lambda r=rodzaj: self._wpisz(szkic, r)})
        if szkic.get("zalacznik"):
            pozycje.append({"ikona": ft.Icons.ZOOM_IN, "tekst": "Powiększ zdjęcie", "czyta": True,
                            "akcja": lambda: utils.pokaz_podglad_zalacznika(self._page, szkic["zalacznik"], "Paragon")})
        pozycje.append({"ikona": ft.Icons.EDIT_NOTE, "tekst": "Rodzaj, licznik i opis",
                        "akcja": lambda: utils.dialog_opisu_szkicu(self._page, auto_id, szkic, po_zapisie=self._odswiez)})
        if self.inne_pojazdy:
            pozycje.append({"ikona": ft.Icons.DRIVE_FILE_MOVE, "tekst": "Przenieś do innego pojazdu",
                            "akcja": lambda: self._przenies(szkic)})
        pozycje.append({"ikona": ft.Icons.DELETE, "tekst": "Usuń szkic",
                        "kolor": utils.KOLOR_STATUS["destructive"], "akcja": lambda: self._usun(szkic)})
        utils.pokaz_menu_kontekstowe(self._page, f"Paragon z {szkic['data']}", pozycje)

    # ================= STANY I KARTY =================

    def _pusto(self):
        opis = ("Przy dystrybutorze nie ma czasu na formularz — zrób zdjęcie paragonu z kokpitu albo "
                "z przycisku „+”. Szkic z datą poczeka tutaj, aż znajdziesz chwilę, żeby go wpisać.")
        if not self.moge_dodawac:
            return ft.Container(
                padding=30,
                content=ft.Column([
                    ft.Icon(ft.Icons.PENDING_ACTIONS, size=46, color=ft.Colors.PRIMARY),
                    ft.Text("Nic nie czeka na wpisanie", size=utils.FS["heading"], weight="bold"),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
            )
        return ft.Column([
            utils.ekran_braku_danych(
                ikona=ft.Icons.PENDING_ACTIONS,
                tytul="Nic nie czeka na wpisanie",
                opis=opis,
                tekst_przycisku="Zrób zdjęcie" if self.aparat else "Wybierz zdjęcia",
                on_click=lambda e: utils.otworz_migawke(self._page, self.state),
            ),
            ft.Row([ft.TextButton("Zdjęcia z galerii", icon=ft.Icons.PHOTO_LIBRARY, on_click=self._z_galerii)],
                   alignment=ft.MainAxisAlignment.CENTER),
        ], spacing=0, tight=True)

    def _naglowek(self, ile):
        wiersz = [
            ft.Icon(ft.Icons.PENDING_ACTIONS, size=16, color=ft.Colors.PRIMARY),
            utils.etykieta(f"{db.liczba_z_odmiana(ile, 'paragon', 'paragony', 'paragonów')} · od najstarszego",
                           expand=True),
        ]
        if self.moge_dodawac:
            wiersz.append(ft.TextButton("Z galerii", icon=ft.Icons.PHOTO_LIBRARY, on_click=self._z_galerii))
        return ft.Row(wiersz, spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def _przyciski(self, szkic):
        """Przycisk rodzaju wybranego po migawce jest pełny, pozostałe — tekstowe.
        Bez wybranego rodzaju wszystkie trzy są równorzędne."""
        auto_id = self.state.auto_id
        przyciski = []
        for rodzaj in db.RODZAJE_SZKICU:
            etykieta = utils.etykieta_rodzaju_szkicu(rodzaj, auto_id, krotka=True)
            ikona = utils.IKONY_RODZAJU_SZKICU[rodzaj]
            akcja = (lambda e, r=rodzaj: self._wpisz(szkic, r))
            if rodzaj == szkic.get("rodzaj"):
                przyciski.insert(0, ft.Button(etykieta, icon=ikona, on_click=akcja))
            else:
                przyciski.append(ft.TextButton(etykieta, icon=ikona, on_click=akcja))
        return ft.Row(przyciski, spacing=4, wrap=True, run_spacing=0)

    def _karta(self, szkic):
        auto_id = self.state.auto_id
        kiedy = szkic["data"] + (f" · {szkic['godzina']}" if szkic.get("godzina") else "")
        stary = szkic["dni"] >= db.DNI_PRZYPOMNIENIA_SZKICU
        opis = utils.opis_szkicu(szkic, auto_id)
        info = [
            utils.wartosc(kiedy, size=utils.FS["body_strong"]),
            utils.podpis(utils.wiek_szkicu(szkic["dni"]),
                         color=utils.KOLOR_STATUS["warning"] if stary else ft.Colors.ON_SURFACE_VARIANT),
        ]
        if opis:
            info.append(utils.podpis(opis, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS))
        tresc = [
            ft.Row([
                utils.miniatura_szkicu(self._page, szkic, 72),
                ft.Column(info, spacing=2, tight=True, expand=True),
                ft.IconButton(icon=ft.Icons.MORE_VERT, tooltip="Więcej", on_click=lambda e: self._menu(szkic)),
            ], spacing=utils.SPACING["md"], vertical_alignment=ft.CrossAxisAlignment.START),
        ]
        if self.moge_dodawac:
            tresc.append(self._przyciski(szkic))
        karta_ui, kontener = utils.karta_listy(ft.Column(tresc, spacing=utils.SPACING["sm"]), page=self._page)
        kontener.on_click = utils.z_efektem_nacisniecia(kontener, lambda e: self._menu(szkic))
        return karta_ui
