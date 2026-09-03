import flet as ft
import db
import sync
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

        wspolny_id, _ = sync.czy_udostepniony(state.auto_id)
        appbar = utils.zbuduj_pasek_z_powrotem(
            page, "Dziennik życia auta", "/", ikona=ft.Icons.CALENDAR_MONTH,
            akcje_dodatkowe=[utils.przycisk_synchronizacji(page, utils.funkcja_szybkiej_synchronizacji(page, state.auto_id, "/timeline"))] if wspolny_id else None
        )
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
            elementy.append(utils.heatmapa_aktywnosci(self._page, [z[2] for z in zdarzenia]))

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
                widoczne = [k for k in self.wszystkie_karty if zapytanie in k["szukaj"]]
                for k in widoczne:
                    self.lista_kart.controls.append(k["karta"])
                # Oś musi się urywać na PIERWSZYM i OSTATNIM widocznym zdarzeniu,
                # a nie na pierwszym/ostatnim w ogóle — inaczej po wyszukaniu
                # linia wystaje w pustkę nad i pod listą.
                self._popraw_koncowki_osi(widoczne)
                self.update()

            elementy.append(
                ft.TextField(
                    hint_text="Szukaj (typ, tytuł, opis, data)...",
                    prefix_icon=ft.Icons.SEARCH,
                    on_change=utils.z_opoznieniem(self._page, filtruj_timeline),
                    **utils.styl_pola()
                )
            )

            # spacing=0 celowo: odstęp między kartami robi teraz dolny padding
            # WEWNĄTRZ wiersza osi, dzięki czemu pionowa linia biegnie przez
            # przerwę i łączy kolejne zdarzenia zamiast się urywać.
            self.lista_kart = ft.ListView(spacing=0, padding=0, height=utils.wysokosc_listy(self._page), auto_scroll=False)
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
                    wiersz = self._wiersz_osi_czasu(z)
                    _, typ, data, tytul, opis, kwota, zalacznik, _ = z
                    tekst_szukaj = f"{typ} {data} {tytul} {opis}".lower()
                    wiersz["szukaj"] = tekst_szukaj
                    self.wszystkie_karty.append(wiersz)
                    self.lista_kart.controls.append(wiersz["karta"])
                self._popraw_koncowki_osi(self.wszystkie_karty)

            elementy.append(self.lista_kart)

        elementy.append(utils.dol_bezpieczny(10))

        super().__init__(
            route="/timeline",
            padding=15,
            appbar=appbar, controls=[utils.z_odswiezaniem(page, elementy)]
        )

    # ================= OŚ CZASU =================
    def _kolor_linii(self):
        """Delikatna szara pionowa nitka osi — na tyle widoczna, żeby łączyła
        kropki, na tyle stonowana, żeby nie konkurowała z kartami."""
        return ft.Colors.with_opacity(0.22, ft.Colors.ON_SURFACE)

    def _popraw_koncowki_osi(self, widoczne_wiersze):
        """Oś nie ma wystawać poza pierwsze i ostatnie WIDOCZNE zdarzenie:
        górny odcinek pierwszego i dolny odcinek ostatniego wiersza robimy
        przezroczyste. Reszta wierszy dostaje linię z powrotem (lista bywa
        filtrowana wyszukiwarką w locie)."""
        kolor = self._kolor_linii()
        for i, w in enumerate(widoczne_wiersze):
            w["gora"].bgcolor = ft.Colors.TRANSPARENT if i == 0 else kolor
            w["dol"].bgcolor = ft.Colors.TRANSPARENT if i == len(widoczne_wiersze) - 1 else kolor

    def _wiersz_osi_czasu(self, z):
        """Jeden przystanek na osi: pionowa linia + kropka z ikoną po lewej,
        karta zdarzenia po prawej.

        Linia i kropka są POZYCJONOWANE w ft.Stack, a nie rozciągane w Row —
        i to jest tu sedno. Element listy dostaje od ListView nieograniczoną
        wysokość, więc `CrossAxisAlignment.STRETCH` albo `expand=True` na
        pionowej kresce kazałyby jej wypełnić nieskończoność i cały widok
        przestawał się renderować. W Stacku rozmiar wyznacza sam wiersz (jedyne
        dziecko niepozycjonowane), a kreska `dol` (top=… + bottom=0) dociąga się
        do jego dołu — razem z odstępem pod kartą, dzięki czemu oś jest ciągła
        między zdarzeniami.

        Zwraca dict z kontrolką i referencjami do obu odcinków linii, bo
        wyszukiwarka musi móc później poprawić końcówki osi."""
        _, typ, data, tytul, opis, kwota, zalacznik, trasa = z
        ikona, kolor = IKONY_TIMELINE.get(typ, (ft.Icons.EVENT_NOTE, ft.Colors.ON_SURFACE_VARIANT))
        kolor_linii = self._kolor_linii()

        SZER_SZYNY = 34      # szerokość lewej kolumny zarezerwowanej na oś
        SRODEK_X = 15        # lewa krawędź 2-pikselowej kreski (środek kropki = 16)
        GORA_KROPKI = 8      # ile linii nad kropką
        WYM_KROPKI = 28
        DOL_KROPKI = GORA_KROPKI + WYM_KROPKI
        ODSTEP = 10          # przerwa do następnej karty — linia biegnie przez nią

        odcinek_gorny = ft.Container(
            left=SRODEK_X, top=0, width=2, height=GORA_KROPKI, bgcolor=kolor_linii,
        )
        odcinek_dolny = ft.Container(
            left=SRODEK_X, top=DOL_KROPKI, bottom=0, width=2, bgcolor=kolor_linii,
        )

        kropka = ft.Container(
            left=SRODEK_X - (WYM_KROPKI - 2) // 2, top=GORA_KROPKI,
            width=WYM_KROPKI, height=WYM_KROPKI, border_radius=WYM_KROPKI // 2,
            bgcolor=ft.Colors.with_opacity(0.15, kolor),
            border=ft.Border.all(2, ft.Colors.with_opacity(0.55, kolor)),
            alignment=ft.Alignment.CENTER,
            content=ft.Icon(ikona, size=15, color=kolor),
            tooltip=typ,
        )

        naglowek_bits = [ft.Text(str(data), size=12, weight="bold", color=ft.Colors.ON_SURFACE_VARIANT)]
        if zalacznik:
            naglowek_bits.append(utils.wskaznik_zalacznika(self._page, zalacznik, typ))

        prawa_strona = [ft.Row(naglowek_bits, spacing=6)]
        if kwota is not None and kwota != 0:
            prawa_strona.append(ft.Text(f"-{utils.formatuj_liczba(kwota)} {utils.symbol_waluty()}", size=13, weight="bold", color=ft.Colors.RED_700))

        kontener = ft.Container(
            padding=14, border_radius=10,
            content=ft.Row([
                ft.Column([
                    ft.Text(str(tytul), size=15, weight="bold", expand=True),
                    ft.Text(str(opis) if opis else typ, size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                ], spacing=3, expand=True),
                ft.Column(prawa_strona, spacing=4, horizontal_alignment=ft.CrossAxisAlignment.END),
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.START),
            on_click=(lambda e, t=trasa: utils.przejdz(self._page, t)) if trasa else None,
        )

        karta = ft.Card(elevation=1, content=kontener)

        wiersz = ft.Row(
            [
                # Lewy padding rezerwuje pas na oś (sama oś siedzi w Stacku),
                # dolny robi odstęp do następnej karty — należy do wiersza, więc
                # odcinek `dol` przechodzi przez niego i łączy zdarzenia.
                ft.Container(
                    content=karta, expand=True,
                    padding=ft.Padding.only(left=SZER_SZYNY, bottom=ODSTEP),
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

        # Kolejność ma znaczenie: kreski pod spodem, potem wiersz (to on nadaje
        # Stackowi wysokość), a kropka na samej górze, żeby przykryła oś.
        stos = ft.Stack([odcinek_gorny, odcinek_dolny, wiersz, kropka], clip_behavior=ft.ClipBehavior.NONE)

        return {"karta": stos, "gora": odcinek_gorny, "dol": odcinek_dolny}
