import flet as ft
import db
import utils

IKONY_WYSZUKIWANIA = {
    "Tankowanie": (ft.Icons.LOCAL_GAS_STATION, ft.Colors.BLUE_700),
    "Serwis": (ft.Icons.BUILD, ft.Colors.ORANGE_700),
    "Wizyta zbiorcza": (ft.Icons.HOME_REPAIR_SERVICE, ft.Colors.RED_700),
    "Inny koszt": (ft.Icons.RECEIPT_LONG, ft.Colors.GREEN_700),
    "Do zrobienia": (ft.Icons.CHECKLIST_RTL, ft.Colors.PURPLE_700),
    "Magazyn": (ft.Icons.INVENTORY_2, ft.Colors.TEAL_700),
    "Opony": (ft.Icons.TIRE_REPAIR, ft.Colors.INDIGO_700),
}


class SzukajView(ft.View):
    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state

        appbar = utils.zbuduj_pasek_z_powrotem(page, "🔎 Szukaj we wszystkim", "/")

        if not self.state.auto_id:
            super().__init__(
                route="/szukaj", padding=15, spacing=15, appbar=appbar,
                controls=[utils.ekran_braku_danych(
                    ikona=ft.Icons.DIRECTIONS_CAR,
                    tytul="Brak wybranego pojazdu",
                    opis="Wybierz pojazd, aby móc przeszukać jego dane.",
                    tekst_przycisku="Wróć na start",
                    on_click=lambda e: utils.przejdz(self._page, "/")
                )]
            )
            return

        self.pole_wyszukiwarki = ft.TextField(
            hint_text="Szukaj (stacja, część, warsztat, opis, data)...",
            prefix_icon=ft.Icons.SEARCH,
            autofocus=True,
            on_change=utils.z_opoznieniem(self._page, self._wyszukaj),
            **utils.styl_pola()
        )

        self.tekst_pomocniczy = ft.Text(
            "Wpisz min. 2 znaki, aby przeszukać tankowania, serwis, wizyty, "
            "inne koszty i listę Do zrobienia bieżącego pojazdu.",
            size=13, color=ft.Colors.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER
        )
        self.kontener_pomocniczy = ft.Container(
            padding=ft.Padding.symmetric(vertical=20),
            content=self.tekst_pomocniczy,
            alignment=ft.Alignment.CENTER,
        )

        self.lista_wynikow = ft.ListView(
            spacing=12, padding=0, height=utils.wysokosc_listy(self._page), auto_scroll=False
        )

        elementy = [self.pole_wyszukiwarki, self.kontener_pomocniczy, self.lista_wynikow]

        super().__init__(
            route="/szukaj", padding=15, spacing=15, appbar=appbar,
            controls=elementy, scroll=ft.ScrollMode.AUTO
        )

    def _karta_wyniku(self, w):
        ikona, kolor = IKONY_WYSZUKIWANIA.get(w["typ"], (ft.Icons.EVENT_NOTE, ft.Colors.ON_SURFACE_VARIANT))

        return ft.Card(
            elevation=1,
            content=ft.Container(
                padding=15, border_radius=10,
                on_click=lambda e, trasa=w["trasa"]: utils.przejdz(self._page, trasa),
                content=ft.Row([
                    ft.Container(
                        width=36, height=36, border_radius=18,
                        bgcolor=ft.Colors.with_opacity(0.15, kolor),
                        alignment=ft.Alignment.CENTER,
                        content=ft.Icon(ikona, size=16, color=kolor)
                    ),
                    ft.Column([
                        ft.Row([
                            ft.Text(w["typ"], size=11, weight="bold", color=kolor),
                            ft.Text(str(w["data"]) if w["data"] else "", size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Text(w["tytul"], size=15, weight="bold"),
                        ft.Text(w["opis"], size=12, color=ft.Colors.ON_SURFACE_VARIANT) if w["opis"] else ft.Container(),
                    ], spacing=3, expand=True),
                ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.START)
            )
        )

    def _wyszukaj(self, e):
        zapytanie = (self.pole_wyszukiwarki.value or "").strip()
        self.lista_wynikow.controls.clear()

        if len(zapytanie) < 2:
            self.tekst_pomocniczy.value = (
                "Wpisz min. 2 znaki, aby przeszukać tankowania, serwis, wizyty, "
                "inne koszty i listę Do zrobienia bieżącego pojazdu."
            )
            self.kontener_pomocniczy.visible = True
            self.update()
            return

        wyniki = db.globalne_wyszukiwanie(self.state.auto_id, zapytanie)

        if not wyniki:
            self.tekst_pomocniczy.value = f"Brak wyników dla „{zapytanie}”."
            self.kontener_pomocniczy.visible = True
        else:
            self.kontener_pomocniczy.visible = False
            for w in wyniki:
                self.lista_wynikow.controls.append(self._karta_wyniku(w))

        self.update()