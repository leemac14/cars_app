import flet as ft

import db
import log
import utils


class WykresView(ft.View):
    """Jeden wykres Analizy (/wykres/<klucz>): pytanie i „jak czytać”, przełączniki, karta
    i odnośnik do następnego. Treść składa utils/wykresy_analizy.py."""

    def __init__(self, page: ft.Page, state, klucz=None):
        self._page = page
        self.state = state
        self.wpis = utils.wykres_analizy(klucz)
        self.klucz = self.wpis["klucz"]
        self.trasa = f"/wykres/{self.klucz}"
        self.prad = bool(state.auto_id) and db.domyslny_rodzaj_energii(state.auto_id) == db.ENERGIA_PRAD

        appbar = utils.zbuduj_pasek_z_powrotem(page, utils.tekst_wykresu(self.wpis, "nazwa", self.prad), "/",
                                               ikona=self.wpis["ikona"])
        if not self.state.auto_id:
            super().__init__(
                route=self.trasa, padding=15, spacing=15, appbar=appbar,
                controls=[utils.ekran_braku_danych(
                    ikona=ft.Icons.DIRECTIONS_CAR,
                    tytul="Brak wybranego pojazdu",
                    opis="Dodaj pojazd, a wykresy policzą się z jego tankowań, serwisu i innych kosztów.",
                    tekst_przycisku="Dodaj pojazd",
                    on_click=lambda e: utils.przejdz(self._page, "/auto/nowy"),
                )],
            )
            return

        self.tresc = ft.Column(spacing=15)

        def zbuduj():
            self._przelicz()
            return self.tresc

        super().__init__(
            route=self.trasa, padding=15, appbar=appbar,
            controls=[utils.zbuduj_etapami(
                page, utils.szkielet_ekranu(page, wykres=True, karty=1, linie=2), zbuduj, widok=self,
            )],
            scroll=ft.ScrollMode.AUTO,
        )

    def _przelicz(self):
        # Paski udziałów napełniają się kaskadą raz na uruchomienie (jak na reszcie Analizy).
        scena = utils.ScenaWejscia(
            wlaczona=db.czy_animacje_interfejsu()
            and utils.pierwsze_pokazanie(self.state, f"wykres:{self.klucz}", self.state.auto_id),
            kaskada=True,
        )
        self.tresc.controls = (
            [utils.wstep_wykresu(self._page, self.wpis, self.prad)]
            + utils.tresc_wykresu(self._page, self.state, self.klucz, scena)
            + [utils.karta_nastepnego(self._page, self.klucz, self.prad), utils.dol_bezpieczny(10)]
        )
        scena.uruchom(self._page)

    def odswiez_w_miejscu(self):
        """Zakres, okno albo rok zmienione chipem (utils.odswiez_ekran): wykres liczy się od nowa,
        ekran zostaje w miejscu."""
        if not self.state.auto_id:
            return
        self._przelicz()
        try:
            self.update()
        except Exception:
            log.polkniety("odświeżenie ekranu wykresu w miejscu")
