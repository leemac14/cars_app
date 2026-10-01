import asyncio

import flet as ft

import db
import log
import utils


class MigawkaView(ft.View):
    """„Paragon na później” (M-08) — aparat z jednym dużym spustem.

    Zdjęcie od razu staje się szkicem w kolejce „Do wpisania” (data i godzina
    z chwili migawki). Pod podglądem pojawia się wtedy panel z trzema polami na
    zapas — rodzaj, licznik, krótki opis — ale nic w nim nie jest wymagane:
    kto nie ma czasu, chowa telefon, a szkic i tak czeka.

    Aparat to flet-camera (Android, iOS). Na komputerze kontrolka nie działa,
    więc ekran proponuje wybór zdjęć z dysku — tą samą drogą, co „Z galerii”."""

    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state
        self.aparat = None
        self._gotowy = False
        self._zajety = False
        self.zrobione = 0
        self.pola = None
        self.szkic_id = None

        appbar = utils.zbuduj_pasek_z_powrotem(
            page, "Paragon na później", "/", ikona=ft.Icons.PHOTO_CAMERA,
            akcje_dodatkowe=[ft.IconButton(
                icon=ft.Icons.PENDING_ACTIONS, tooltip="Kolejka „Do wpisania”",
                on_click=lambda e: utils.przejdz(self._page, "/do-wpisania"),
            )],
        )

        if not state.auto_id:
            tresc = utils.ekran_braku_danych(
                ikona=ft.Icons.DIRECTIONS_CAR, tytul="Brak wybranego pojazdu",
                opis="Szkic paragonu należy do auta — dodaj pojazd, a potem zrób zdjęcie.",
                tekst_przycisku="Dodaj pojazd",
                on_click=lambda e: utils.przejdz(self._page, "/auto/nowy"),
            )
        elif utils.aparat_dostepny(page):
            import flet_camera as fc
            self._fc = fc
            self.aparat = fc.Camera(preview_enabled=True)
            tresc = self._uklad_aparatu()
        else:
            tresc = self._bez_aparatu()

        super().__init__(route="/paragon", padding=0, spacing=0, appbar=appbar, controls=[tresc])

    # ================= UKŁAD =================

    def _uklad_aparatu(self):
        self.komunikat = ft.Text("Uruchamiam aparat…", size=utils.FS["label"], color=ft.Colors.WHITE)
        # Stos jest dzieckiem kolumny (tam `expand` ma sens — w Container.content
        # nie, patrz audyt expand w kontenerze). Wizjer wypełnia stos przez
        # pozycjonowanie, a wyrównanie do środka zostawia podglądowi jego własne
        # proporcje: CameraPreview to AspectRatio, a ciasne wymiary by je rozciągnęły.
        podglad = ft.Stack([
            ft.Container(content=self.aparat, alignment=ft.Alignment.CENTER, bgcolor=ft.Colors.BLACK,
                         left=0, top=0, right=0, bottom=0),
            ft.Container(content=self.komunikat, left=16, right=16, bottom=12),
        ], expand=True)

        self.spust = ft.Container(
            width=76, height=76, border_radius=38, alignment=ft.Alignment.CENTER, ink=True,
            bgcolor=ft.Colors.PRIMARY, border=ft.Border.all(4, ft.Colors.ON_PRIMARY),
            tooltip="Zrób zdjęcie paragonu", on_click=self._migawka,
            content=ft.Icon(ft.Icons.RECEIPT_LONG, size=30, color=ft.Colors.ON_PRIMARY),
        )
        self.licznik_zdjec = utils.podpis("")
        self.pasek_spustu = ft.Container(
            padding=ft.Padding(24, 14, 24, 18),
            content=ft.Row([
                ft.IconButton(icon=ft.Icons.PHOTO_LIBRARY, tooltip="Z galerii (kilka naraz)",
                              on_click=lambda e: utils.wybierz_z_galerii(
                                  self._page, self.state, po_dodaniu=self._po_galerii)),
                self.spust,
                ft.Container(width=48, alignment=ft.Alignment.CENTER, content=self.licznik_zdjec),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )
        self.panel = ft.Container(visible=False, padding=ft.Padding(16, 12, 16, 16))
        return ft.Column([podglad, self.pasek_spustu, self.panel], spacing=0, expand=True)

    def _bez_aparatu(self):
        return ft.Container(
            padding=15,
            content=utils.ekran_braku_danych(
                ikona=ft.Icons.ADD_A_PHOTO,
                tytul="Aparat działa na telefonie",
                opis="Tutaj dodasz paragon z pliku: każde zdjęcie stanie się szkicem z datą "
                     "zdjęcia i poczeka w kolejce „Do wpisania”.",
                tekst_przycisku="Wybierz zdjęcia",
                on_click=lambda e: utils.wybierz_z_galerii(
                    self._page, self.state, po_dodaniu=lambda: utils.przejdz(self._page, "/do-wpisania")),
            ),
        )

    def _po_galerii(self):
        utils.przejdz(self._page, "/do-wpisania")

    # ================= APARAT =================

    def did_mount(self):
        super().did_mount()
        if self.aparat is not None:
            self._page.run_task(self._uruchom_aparat)

    async def _uruchom_aparat(self):
        try:
            aparaty = await self.aparat.get_available_cameras()
            tylny = next((a for a in aparaty if a.lens_direction == self._fc.CameraLensDirection.BACK),
                         aparaty[0] if aparaty else None)
            if tylny is None:
                raise RuntimeError("telefon nie zgłasza żadnego aparatu")
            # 1080p: paragon ma być czytelny wieczorem, a zapis i tak zmniejsza
            # zdjęcie do 1600 px szerokości (db.zapisz_zalacznik). Bez dźwięku —
            # robimy zdjęcia, a mikrofon wymagałby drugiego uprawnienia.
            await self.aparat.initialize(tylny, self._fc.ResolutionPreset.VERY_HIGH, enable_audio=False)
        except Exception as ex:
            log.blad("uruchomienie aparatu", ex)
            self._pokaz_blad_aparatu()
            return
        self._gotowy = True
        self.komunikat.value = "Paragon w kadrze — i spust"
        self._odswiez()

    def _pokaz_blad_aparatu(self):
        self.komunikat.value = ("Aparat niedostępny. Zezwól aplikacji na aparat w ustawieniach "
                                "telefonu albo dodaj zdjęcie z galerii (ikona po lewej).")
        self._odswiez()

    async def _migawka(self, e):
        if self._zajety or not self._gotowy:
            return
        self._zajety = True
        self.spust.opacity = 0.5
        self._odswiez()
        try:
            dane = await self.aparat.take_picture()
            # Obrót wg EXIF i zmniejszenie zdjęcia to praca dla Pillow — poza
            # wątkiem interfejsu, żeby spust nie zamarzał na pół sekundy.
            szkic_id = await asyncio.to_thread(db.dodaj_szkic_z_bajtow, self.state.auto_id, dane)
        except Exception as ex:
            log.blad("zdjęcie paragonu", ex)
            utils.pokaz_komunikat(self._page, f"Nie udało się zapisać zdjęcia: {ex}", utils.KOLOR_STATUS["error"])
            szkic_id = None
        finally:
            self._zajety = False
            self.spust.opacity = 1.0
        if szkic_id:
            self.zrobione += 1
            self._pokaz_panel(szkic_id)
        self._odswiez()

    # ================= PANEL PO ZDJĘCIU =================

    def _pokaz_panel(self, szkic_id):
        self.szkic_id = szkic_id
        self.pola = utils.PolaSzkicu(self._page, self.state.auto_id)
        w_kolejce = db.podsumowanie_szkicow(self.state.auto_id)["liczba"]
        self.licznik_zdjec.value = f"+{self.zrobione}"
        self.panel.content = ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.CHECK_CIRCLE, size=20, color=utils.KOLOR_STATUS["ok"]),
                utils.wartosc("Zapisane w kolejce", size=utils.FS["body_strong"]),
            ], spacing=8),
            utils.podpis(f"Do wpisania: {db.liczba_z_odmiana(w_kolejce, 'paragon', 'paragony', 'paragonów')}. "
                         "Możesz od razu dopisać, co to było — albo po prostu schować telefon."),
            *self.pola.kontrolki(),
            ft.Row([
                ft.TextButton("Następny paragon", icon=ft.Icons.ADD_A_PHOTO, on_click=self._nastepny),
                ft.Button("Gotowe", icon=ft.Icons.CHECK, on_click=self._gotowe),
            ], alignment=ft.MainAxisAlignment.END, spacing=8),
        ], spacing=utils.SPACING["sm"], tight=True)
        self.panel.visible = True
        self.pasek_spustu.visible = False

    def _zapisz_pola(self):
        if self.szkic_id and self.pola:
            self.pola.zapisz(self.szkic_id)

    def _nastepny(self, e):
        self._zapisz_pola()
        self.szkic_id = None
        self.panel.visible = False
        self.pasek_spustu.visible = True
        self._odswiez()

    def _gotowe(self, e):
        self._zapisz_pola()
        ile = db.podsumowanie_szkicow(self.state.auto_id)["liczba"]
        utils.przejdz(self._page, "/")
        utils.pokaz_komunikat(
            self._page,
            f"Paragon czeka w kolejce · do wpisania: {db.liczba_z_odmiana(ile, 'paragon', 'paragony', 'paragonów')}",
        )

    def _odswiez(self):
        try:
            self._page.update()
        except RuntimeError:
            log.polkniety("odświeżenie ekranu aparatu")

