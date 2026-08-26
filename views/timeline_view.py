import flet as ft
import db
import utils

IKONY_TIMELINE = {
    "Tankowanie": (ft.Icons.LOCAL_GAS_STATION, ft.Colors.BLUE_700),
    "Serwis": (ft.Icons.BUILD, ft.Colors.ORANGE_700),
    "Wizyta zbiorcza": (ft.Icons.HOME_REPAIR_SERVICE, ft.Colors.RED_700),
    "Inny koszt": (ft.Icons.RECEIPT_LONG, ft.Colors.GREEN_700),
    "Zdjęcie karoserii": (ft.Icons.PHOTO_CAMERA, ft.Colors.PURPLE_700),
    "Odczyt przebiegu": (ft.Icons.SPEED, ft.Colors.TEAL_700),
}


class TimelineView(ft.View):
    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state

        appbar = utils.zbuduj_pasek_z_powrotem(page, "🗓️ Dziennik życia auta", "/")
        elementy = []

        if not self.state.auto_id:
            super().__init__(
                route="/timeline", padding=15, spacing=15, appbar=appbar,
                controls=[utils.ekran_braku_danych(
                    ikona=ft.Icons.DIRECTIONS_CAR,
                    tytul="Brak wybranego pojazdu",
                    opis="Wybierz pojazd, aby zobaczyć jego chronologiczny dziennik zdarzeń.",
                    tekst_przycisku="Wróć na start",
                    on_click=lambda e: utils.przejdz(self._page, "/")
                )]
            )
            return

        zdarzenia = db.pobierz_dane_timeline(self.state.auto_id)

        if not zdarzenia:
            elementy.append(utils.ekran_braku_danych(
                ikona=ft.Icons.HISTORY,
                tytul="Brak zdarzeń",
                opis="Gdy dodasz tankowania, wpisy serwisowe, wizyty czy koszty, pojawią się tutaj w jednej chronologicznej osi czasu.",
                tekst_przycisku="Wróć na start",
                on_click=lambda e: utils.przejdz(self._page, "/")
            ))
        else:
            opcje_sort = [
                ("Data", "data", lambda x: (utils.parsuj_date(x[2]), str(x[0]))),
                ("Kwota", "kwota", lambda x: float(x[5] or 0)),
            ]

            sort_ui = utils.przycisk_sortowania(self._page, self.state, "timeline", opcje_sort)
            filtr_typ_ui = utils.przycisk_filtrowania_kategoria(self._page, self.state, "timeline_typ", zdarzenia, 1, "Typ")
            filtr_rok_ui = utils.przycisk_filtrowania_rok(self._page, self.state, "timeline_rok", zdarzenia, 2)
            filtr_mc_ui = utils.przycisk_filtrowania_miesiac(self._page, self.state, "timeline_mc", zdarzenia, 2)

            elementy.append(ft.Row([sort_ui, filtr_typ_ui, filtr_rok_ui, filtr_mc_ui], spacing=6, scroll=ft.ScrollMode.HIDDEN))

            def filtruj_timeline(e):
                zapytanie = e.control.value.lower().strip()
                self.lista_kart.controls.clear()
                for k in self.wszystkie_karty:
                    if zapytanie in k["szukaj"]:
                        self.lista_kart.controls.append(k["karta"])
                self.update()

            elementy.append(
                ft.TextField(
                    hint_text="Szukaj (typ, tytuł, opis, data)...",
                    prefix_icon=ft.Icons.SEARCH,
                    on_change=filtruj_timeline,
                    **utils.styl_pola()
                )
            )

            self.lista_kart = ft.ListView(spacing=15, padding=0, height=utils.wysokosc_listy(self._page), auto_scroll=False)
            self.wszystkie_karty = []
            self.uzyj_wirtualizacji = True

            po_filtrach = utils.filtruj_po_kategorii(zdarzenia, self.state, "timeline_typ", 1)
            po_filtrach = utils.filtruj_po_roku(po_filtrach, self.state, "timeline_rok", 2)
            po_filtrach = utils.filtruj_po_miesiacu(po_filtrach, self.state, "timeline_mc", 2)
            utils.posortuj_liste(po_filtrach, self.state, "timeline", opcje_sort)

            if not po_filtrach:
                elementy.append(ft.Row([ft.Text("Brak wyników dla tych filtrów.", color=ft.Colors.ON_SURFACE_VARIANT)], alignment=ft.MainAxisAlignment.CENTER))
            else:
                for z in po_filtrach:
                    karta = self._karta_zdarzenia(z)
                    _, typ, data, tytul, opis, kwota, zalacznik, _ = z
                    tekst_szukaj = f"{typ} {data} {tytul} {opis}".lower()
                    self.wszystkie_karty.append({"karta": karta, "szukaj": tekst_szukaj})
                    self.lista_kart.controls.append(karta)

            elementy.append(self.lista_kart)

        elementy.append(utils.dol_bezpieczny(10))

        super().__init__(
            route="/timeline",
            padding=15, spacing=15, scroll=ft.ScrollMode.AUTO,
            appbar=appbar, controls=elementy
        )

    def _karta_zdarzenia(self, z):
        _, typ, data, tytul, opis, kwota, zalacznik, trasa = z
        ikona, kolor = IKONY_TIMELINE.get(typ, (ft.Icons.EVENT_NOTE, ft.Colors.ON_SURFACE_VARIANT))

        znacznik_ikony = ft.Container(
            width=38, height=38, border_radius=19,
            bgcolor=ft.Colors.with_opacity(0.15, kolor),
            alignment=ft.Alignment.CENTER,
            content=ft.Icon(ikona, size=18, color=kolor)
        )

        naglowek_bits = [ft.Text(str(data), size=12, weight="bold", color=ft.Colors.ON_SURFACE_VARIANT)]
        if zalacznik:
            naglowek_bits.append(utils.wskaznik_zalacznika(self._page, zalacznik, typ))

        prawa_strona = [ft.Row(naglowek_bits, spacing=6)]
        if kwota is not None and kwota != 0:
            prawa_strona.append(ft.Text(f"-{utils.formatuj_liczba(kwota)} {utils.symbol_waluty()}", size=13, weight="bold", color=ft.Colors.RED_700))

        kontener = ft.Container(
            padding=15, border_radius=10,
            content=ft.Row([
                znacznik_ikony,
                ft.Column([
                    ft.Text(str(tytul), size=15, weight="bold", expand=True),
                    ft.Text(str(opis) if opis else typ, size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                ], spacing=3, expand=True),
                ft.Column(prawa_strona, spacing=4, horizontal_alignment=ft.CrossAxisAlignment.END),
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.START),
            on_click=(lambda e, t=trasa: utils.przejdz(self._page, t)) if trasa else None,
        )

        return ft.Card(elevation=1, content=kontener)