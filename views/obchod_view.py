"""Obchód auta aparatem: strefa po strefie (przód, bok prawy, tył, bok lewy, wnętrze) z
podpowiedzią, gdzie stanąć; każde zdjęcie od razu trafia do rejestru karoserii z dzisiejszą
datą i licznikiem. Aparat to flet-camera (Android, iOS) — na komputerze formularz z plikami."""

import asyncio

import flet as ft

import db
import log
import utils

WSKAZOWKI_STREF = {
    "Przód": "Stań kilka kroków przed autem — cały zderzak i reflektory w kadrze.",
    "Bok prawy": "Prawy bok w całości, od przedniego do tylnego koła.",
    "Tył": "Tył z tablicą i całym zderzakiem.",
    "Bok lewy": "Lewy bok w całości, od tylnego do przedniego koła.",
    "Wnętrze / Kokpit": "Fotele, kierownica i deska — przez otwarte drzwi kierowcy.",
    "Uszkodzenie / Rysa": "Podejdź blisko: rysa albo wgniecenie na środku kadru.",
    "Inne": "Wszystko, co jeszcze warto zachować: felgi, szyby, bagażnik.",
}


class ObchodKaroseriiView(ft.View):
    """Po zdjęciu strefy z obchodu aparat sam przechodzi do następnej; strefę zmienia też
    dotknięcie chipa. „Gotowe” wraca do galerii."""

    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state
        self.aparat = None
        self._gotowy = False
        self._zajety = False
        self.zrobione = {}
        self.strefa = db.STREFY_OBCHODU[0]
        self.przebieg = db.pobierz_aktualny_przebieg(state.auto_id) if state.auto_id else None

        appbar = utils.zbuduj_pasek_z_powrotem(page, "Obchód auta", "/karoseria", ikona=ft.Icons.THREESIXTY)
        if not state.auto_id:
            tresc = ft.Container(padding=15, content=utils.ekran_braku_danych(
                ikona=ft.Icons.DIRECTIONS_CAR, tytul="Brak wybranego pojazdu",
                opis="Zdjęcia karoserii należą do auta — dodaj pojazd, a potem obejdź go z aparatem.",
                tekst_przycisku="Dodaj pojazd", on_click=lambda e: utils.przejdz(self._page, "/auto/nowy"),
            ))
        elif utils.aparat_dostepny(page):
            import flet_camera as fc
            self._fc = fc
            self.aparat = fc.Camera(preview_enabled=True)
            tresc = self._uklad_aparatu()
        else:
            tresc = self._bez_aparatu()

        super().__init__(route="/karoseria/obchod", padding=0, spacing=0, appbar=appbar, controls=[tresc])

    # ================= UKŁAD =================

    def _uklad_aparatu(self):
        biel = ft.Colors.WHITE
        self.komunikat = ft.Text("Uruchamiam aparat…", size=utils.FS["label"], color=biel)
        self.krok = ft.Text("", size=utils.FS["body_strong"], weight="bold", color=biel)
        self.wskazowka = ft.Text("", size=utils.FS["label"], color=ft.Colors.with_opacity(0.9, biel))
        # Wizjer wypełnia stos przez pozycjonowanie, a wyrównanie do środka zostawia podglądowi
        # jego proporcje (jak w views/migawka_view.py).
        podglad = ft.Stack([
            ft.Container(content=self.aparat, alignment=ft.Alignment.CENTER, bgcolor=ft.Colors.BLACK,
                         left=0, top=0, right=0, bottom=0),
            ft.Container(left=12, right=12, top=12, padding=ft.Padding(12, 8, 12, 8), border_radius=utils.RADIUS["md"],
                         bgcolor=ft.Colors.with_opacity(0.55, ft.Colors.BLACK),
                         content=ft.Column([self.krok, self.wskazowka], spacing=2, tight=True)),
            ft.Container(content=self.komunikat, left=16, right=16, bottom=12),
        ], expand=True)

        self.pasek_stref = ft.Row(scroll=ft.ScrollMode.ADAPTIVE, spacing=utils.SPACING["sm"])
        self.spust = ft.Container(
            width=76, height=76, border_radius=38, alignment=ft.Alignment.CENTER, ink=True,
            bgcolor=ft.Colors.PRIMARY, border=ft.Border.all(4, ft.Colors.ON_PRIMARY),
            tooltip="Zrób zdjęcie strefy", on_click=self._migawka,
            content=ft.Icon(ft.Icons.PHOTO_CAMERA, size=30, color=ft.Colors.ON_PRIMARY),
        )
        self.licznik = utils.podpis("Zdjęcia zapisują się od razu w galerii.")
        dol = ft.Container(padding=ft.Padding(16, 10, 16, 16), content=ft.Column([
            self.pasek_stref,
            ft.Row([
                ft.IconButton(icon=ft.Icons.PHOTO_LIBRARY, tooltip="Dodaj zdjęcia z galerii",
                              on_click=lambda e: utils.przejdz(self._page, "/karoseria/nowe")),
                self.spust,
                ft.TextButton("Gotowe", icon=ft.Icons.CHECK, on_click=self._gotowe),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            self.licznik,
        ], spacing=utils.SPACING["sm"], tight=True))
        self._ustaw_strefe(self.strefa, odswiez=False)
        return ft.Column([podglad, dol], spacing=0, expand=True)

    def _chip_strefy(self, strefa):
        wybrana = strefa == self.strefa
        ile = self.zrobione.get(strefa, 0)
        kolor = ft.Colors.ON_PRIMARY if wybrana else None
        tresc = [ft.Text(strefa, size=utils.FS["label"], weight="bold" if wybrana else "normal", color=kolor)]
        if ile:
            tresc.insert(0, ft.Icon(ft.Icons.CHECK_CIRCLE, size=16, color=kolor or utils.KOLOR_STATUS["ok"]))
            tresc.append(ft.Text(str(ile), size=utils.FS["caption"], color=kolor or ft.Colors.ON_SURFACE_VARIANT))
        return ft.Container(
            padding=ft.Padding(12, 8, 12, 8), border_radius=utils.RADIUS["pill"], ink=True,
            bgcolor=ft.Colors.PRIMARY if wybrana else utils.tlo_odznaki(self._page),
            on_click=lambda e: self._ustaw_strefe(strefa),
            content=ft.Row(tresc, spacing=4, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )

    def _ustaw_strefe(self, strefa, odswiez=True):
        self.strefa = strefa
        if strefa in db.STREFY_OBCHODU:
            self.krok.value = f"Krok {db.STREFY_OBCHODU.index(strefa) + 1} z {len(db.STREFY_OBCHODU)} · {strefa}"
        else:
            self.krok.value = strefa
        self.wskazowka.value = WSKAZOWKI_STREF.get(strefa, "")
        # Chipy w kolejności obchodu, pozostałe strefy za nimi.
        kolejnosc = list(db.STREFY_OBCHODU) + [s for s in db.STREFY_KAROSERII if s not in db.STREFY_OBCHODU]
        self.pasek_stref.controls = [self._chip_strefy(s) for s in kolejnosc]
        if odswiez:
            self._odswiez()

    def _bez_aparatu(self):
        return ft.Container(padding=15, content=utils.ekran_braku_danych(
            ikona=ft.Icons.THREESIXTY,
            tytul="Aparat działa na telefonie",
            opis="Obchód robi zdjęcia aparatem w aplikacji, strefa po strefie. Tutaj dodasz zdjęcia "
                 "z dysku, a strefę wybierzesz w formularzu.",
            tekst_przycisku="Wybierz zdjęcia",
            on_click=lambda e: utils.przejdz(self._page, "/karoseria/nowe"),
        ))

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
            # Zapis i tak zmniejsza zdjęcie do 1600 px szerokości (db.zapisz_zalacznik); bez dźwięku.
            await self.aparat.initialize(tylny, self._fc.ResolutionPreset.VERY_HIGH, enable_audio=False)
        except Exception as ex:
            log.blad("uruchomienie aparatu do obchodu karoserii", ex)
            self.komunikat.value = ("Aparat niedostępny. Zezwól aplikacji na aparat w ustawieniach telefonu "
                                    "albo dodaj zdjęcia z galerii (ikona po lewej).")
            self._odswiez()
            return
        self._gotowy = True
        self.komunikat.value = "Strefa w kadrze — i spust"
        self._odswiez()

    async def _migawka(self, e):
        if self._zajety or not self._gotowy:
            return
        self._zajety = True
        self.spust.opacity = 0.5
        self._odswiez()
        strefa = self.strefa
        try:
            dane = await self.aparat.take_picture()
            # Obrót wg EXIF i zmniejszenie zdjęcia to praca dla Pillow — poza wątkiem interfejsu.
            zdjecie_id = await asyncio.to_thread(
                db.dodaj_zdjecie_karoserii_z_bajtow, self.state.auto_id, dane, strefa, None, self.przebieg)
        except Exception as ex:
            log.blad("zdjęcie w obchodzie karoserii", ex)
            utils.pokaz_komunikat(self._page, f"Nie udało się zapisać zdjęcia: {ex}", utils.KOLOR_STATUS["error"])
            zdjecie_id = None
        finally:
            self._zajety = False
            self.spust.opacity = 1.0
        if zdjecie_id:
            self._po_zdjeciu(strefa)
        self._odswiez()

    def _po_zdjeciu(self, strefa):
        """Licznik strefy w górę i — w obchodzie — następna strefa; po komplecie podpowiedź „Gotowe”."""
        self.zrobione[strefa] = self.zrobione.get(strefa, 0) + 1
        utils.wibracja(self._page, "zapis")
        ile = sum(self.zrobione.values())
        self.licznik.value = f"Zapisane w galerii: {db.liczba_z_odmiana(ile, 'zdjęcie', 'zdjęcia', 'zdjęć')}"
        brakuje = [s for s in db.STREFY_OBCHODU if not self.zrobione.get(s)]
        if strefa in db.STREFY_OBCHODU and strefa != db.STREFY_OBCHODU[-1]:
            nastepna = db.STREFY_OBCHODU[db.STREFY_OBCHODU.index(strefa) + 1]
            self.komunikat.value = f"Zapisano: {strefa}. Teraz: {nastepna}."
            self._ustaw_strefe(nastepna, odswiez=False)
            return
        self.komunikat.value = (f"Zapisano: {strefa}. Brakuje jeszcze: {', '.join(brakuje)}." if brakuje
                                else f"Zapisano: {strefa}. Obchód kompletny — dotknij „Gotowe”.")
        self._ustaw_strefe(strefa, odswiez=False)

    def _gotowe(self, e):
        ile = sum(self.zrobione.values())
        utils.przejdz(self._page, "/karoseria")
        if ile:
            utils.pokaz_komunikat(self._page, f"Obchód w galerii: {db.liczba_z_odmiana(ile, 'zdjęcie', 'zdjęcia', 'zdjęć')}.")

    def _odswiez(self):
        try:
            self._page.update()
        except RuntimeError:
            log.polkniety("odświeżenie ekranu obchodu karoserii")


__all__ = [
    "ObchodKaroseriiView",
    "WSKAZOWKI_STREF",
]
