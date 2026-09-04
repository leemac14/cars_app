import flet as ft
from datetime import datetime
import db
import sync
import utils

class OdczytyPrzebieguView(ft.View, utils.ZaznaczanieGrupowe):
    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state

        wspolny_id, _ = sync.czy_udostepniony(state.auto_id)
        appbar = utils.zbuduj_pasek_z_powrotem(
            page, "Historia odczytów przebiegu", "/", ikona=ft.Icons.SHOW_CHART,
            akcje_dodatkowe=[utils.przycisk_synchronizacji(page, utils.funkcja_szybkiej_synchronizacji(page, state.auto_id, "/przebieg"))] if wspolny_id else None
        )
        fab = utils.fab_animowany(ft.Icons.ADD, lambda e: self._dialog_odczytu())

        # --- ZMIENNE DLA GRUPOWEGO USUWANIA ---
        self.tryb_zaznaczania = False
        self.zaznaczone_id = set()
        self.tabela_cel = "odczyty_przebiegu"
        self.oryginalny_appbar = appbar
        self.karty_ref = {}
        self.uzyj_wirtualizacji = False
        # ----------------------------------------

        elementy = []

        with db.polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT id, data, przebieg, notatka, notatka_autor, notatka_data FROM odczyty_przebiegu WHERE auto_id=?", (self.state.auto_id,))
            baza_lista = c.fetchall()

        if not baza_lista:
            elementy.append(utils.ekran_braku_danych(
                ikona=ft.Icons.SPEED,
                tytul="Brak zapisanych odczytów",
                opis="Dodawaj tu szybkie odczyty stanu licznika z deski rozdzielczej, bez tworzenia tankowania czy wpisu serwisowego.",
                tekst_przycisku="Dodaj odczyt",
                on_click=lambda e: self._dialog_odczytu()
            ))
        else:
            # Dystans od poprzedniego (chronologicznie) odczytu — dodatkowy kontekst na karcie
            chronologicznie = sorted(baza_lista, key=lambda x: (utils.parsuj_date(x[1]), int(x[2] or 0)))
            dystans_wg_id = {}
            poprzedni = None
            for wid, data_w, prz_w, *_ in chronologicznie:
                prz_i = int(prz_w or 0)
                dystans_wg_id[wid] = (prz_i - poprzedni) if poprzedni is not None else None
                poprzedni = prz_i

            opcje_sort = [
                ("Data", "data", lambda x: (utils.parsuj_date(x[1]), x[0])),
                ("Przebieg", "przebieg", lambda x: int(x[2] or 0)),
            ]

            sort_ui = utils.przycisk_sortowania(self._page, self.state, "odczyty_przebiegu", opcje_sort)
            filtr_rok_ui = utils.przycisk_filtrowania_rok(self._page, self.state, "odczyty_rok", baza_lista, 1)
            filtr_mc_ui = utils.przycisk_filtrowania_miesiac(self._page, self.state, "odczyty_mc", baza_lista, 1)

            elementy.append(ft.Row([sort_ui, filtr_rok_ui, filtr_mc_ui], spacing=6, scroll=ft.ScrollMode.HIDDEN))

            def filtruj_odczyty(e):
                zapytanie = e.control.value.lower().strip()
                self.lista_kart.controls.clear()
                for k in self.wszystkie_karty:
                    if zapytanie in k["szukaj"]:
                        self.lista_kart.controls.append(k["karta"])
                self.update()

            elementy.append(
                ft.TextField(
                    hint_text="Szukaj odczytu (data, przebieg, notatka)...",
                    prefix_icon=ft.Icons.SEARCH,
                    on_change=utils.z_opoznieniem(self._page, filtruj_odczyty),
                    **utils.styl_pola()
                )
            )

            self.lista_kart = ft.ListView(spacing=15, padding=0, height=utils.wysokosc_listy(self._page), auto_scroll=False)
            self.wszystkie_karty = []
            self.uzyj_wirtualizacji = True

            po_filtrach = utils.filtruj_po_roku(baza_lista, self.state, "odczyty_rok", 1)
            po_filtrach = utils.filtruj_po_miesiacu(po_filtrach, self.state, "odczyty_mc", 1)
            utils.posortuj_liste(po_filtrach, self.state, "odczyty_przebiegu", opcje_sort)

            def otworz_menu(rekord):
                wid, data_w, prz_w = rekord[0], rekord[1], rekord[2]
                notatka_w = rekord[3] if len(rekord) > 3 else None

                def usun():
                    def wykonaj():
                        wynik = db.usun_z_cofnieciem("odczyty_przebiegu", wid)
                        utils.przejdz(self._page, "/przebieg")
                        utils.pokaz_komunikat_cofnij(self._page, "Usunięto odczyt.", wynik)
                    utils.potwierdz(self._page, "Usunąć?", "Czy na pewno usunąć ten odczyt przebiegu?", wykonaj)

                utils.pokaz_menu_kontekstowe(self._page, f"Odczyt: {data_w}", [
                    {"ikona": ft.Icons.EDIT, "tekst": "Edytuj", "akcja": lambda: self._dialog_odczytu(rekord)},
                    utils.pozycja_menu_notatki(
                        self._page, "odczyty_przebiegu", wid, notatka_w,
                        lambda: utils.przejdz(self._page, "/przebieg"), "Notatka do odczytu"
                    ),
                    {"ikona": ft.Icons.DELETE, "tekst": "Usuń", "akcja": usun, "kolor": ft.Colors.RED},
                ])

            if not po_filtrach:
                elementy.append(ft.Row([ft.Text("Brak wyników dla tych filtrów.", color=ft.Colors.ON_SURFACE_VARIANT)], alignment=ft.MainAxisAlignment.CENTER))
            else:
                for w in po_filtrach:
                    wid, data_w, prz_w = w[0], w[1], w[2]
                    notatka_w = w[3] if len(w) > 3 else None
                    notatka_autor_w = w[4] if len(w) > 4 else None
                    notatka_data_w = w[5] if len(w) > 5 else None
                    dystans = dystans_wg_id.get(wid)

                    tresc = [
                        ft.Row([
                            ft.Text(str(data_w), weight="bold", size=16),
                            ft.Text(f"{utils.formatuj_liczba(int(prz_w or 0), 0)} km", weight="bold", size=16, color=ft.Colors.PRIMARY)
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                    ]
                    if dystans is not None:
                        if dystans >= 0:
                            tresc.append(ft.Row([
                                ft.Icon(ft.Icons.ARROW_UPWARD, size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                                ft.Text(f"{utils.formatuj_liczba(dystans, 0)} km od poprzedniego odczytu", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                            ], spacing=4))
                        else:
                            tresc.append(ft.Row([
                                ft.Icon(ft.Icons.WARNING, size=13, color=ft.Colors.RED_700),
                                ft.Text(f"Przebieg niższy o {utils.formatuj_liczba(abs(dystans), 0)} km — sprawdź wpis", size=12, color=ft.Colors.RED_700, expand=True),
                            ], spacing=4))

                    tresc.append(utils.podglad_notatki(
                        self._page, notatka_w, notatka_autor_w, notatka_data_w, "Notatka do odczytu",
                        on_edytuj=lambda rid=wid: utils.szybka_notatka(
                            self._page, "odczyty_przebiegu", rid,
                            lambda: utils.przejdz(self._page, "/przebieg"), "Notatka do odczytu"
                        )
                    ))

                    kontener = ft.Container(padding=15, border_radius=10, ink=True, content=ft.Column(tresc, spacing=4))

                    self.karty_ref[wid] = kontener
                    self.podepnij_zdarzenia_grupowe(kontener, wid, lambda rek=w: otworz_menu(rek))

                    karta = ft.Card(elevation=1, content=kontener)
                    tekst_szukaj = f"{data_w} {prz_w} {notatka_w or ''}".lower()
                    self.wszystkie_karty.append({"karta": karta, "szukaj": tekst_szukaj})
                    self.lista_kart.controls.append(karta)

            elementy.append(self.lista_kart)

        elementy.append(utils.dol_bezpieczny(10))

        super().__init__(
            route="/przebieg",
            padding=15,
            appbar=appbar, floating_action_button=fab,
            controls=[utils.z_odswiezaniem(page, elementy)]
        )

    def potwierdz_grupowe_usuwanie(self, e):
        ile = len(self.zaznaczone_id)
        def wykonaj():
            wynik = db.usun_wiele_z_cofnieciem(self.tabela_cel, list(self.zaznaczone_id))
            self.zakoncz_zaznaczanie()
            utils.przejdz(self._page, "/przebieg")
            utils.pokaz_komunikat_cofnij(self._page, f"Usunięto {ile} odczytów.", wynik)
        utils.potwierdz(self._page, "Usuwanie", f"Czy na pewno usunąć {ile} zaznaczonych odczytów?", wykonaj)

    def _dialog_odczytu(self, odczyt=None):
        """odczyt: None (dodawanie nowego) lub krotka (id, data, przebieg, notatka...) do edycji."""
        edycja = odczyt is not None
        domyslna_data = odczyt[1] if edycja else datetime.now().strftime("%d.%m.%Y")
        domyslny_przebieg = str(odczyt[2]) if edycja else str(db.pobierz_aktualny_przebieg(self.state.auto_id) or "")
        notatka_bazowa = str((odczyt[3] if edycja and len(odczyt) > 3 else "") or "")

        e_data = utils.pole_daty(self._page, "Data odczytu", domyslna_data)
        e_notatka = utils.pole_notatki(notatka_bazowa, self._page)
        e_przebieg = ft.TextField(
            label="Przebieg (km)", value=domyslny_przebieg,
            keyboard_type=ft.KeyboardType.NUMBER, autofocus=not edycja,
            **utils.styl_pola()
        )

        def zapisz(e):
            e_przebieg.error_text = None
            nowy = utils.parsuj_int(e_przebieg.value, None)
            if nowy is None or nowy <= 0:
                e_przebieg.error_text = "Podaj poprawny przebieg"
                self._page.update()
                return

            wyklucz = odczyt[0] if edycja else None
            if utils.sprawdz_podejrzany_przebieg(self._page, e_przebieg, self.state.auto_id, nowy, wyklucz_id=wyklucz, tabela="odczyty_przebiegu", nowa_data_str=e_data.value):
                return

            utils.zamknij_dialog(self._page, dlg)
            if edycja:
                db.aktualizuj_odczyt_przebiegu(odczyt[0], nowy, e_data.value)
                utils.zapisz_notatke_z_formularza("odczyty_przebiegu", odczyt[0], e_notatka.value, notatka_bazowa)
                utils.pokaz_komunikat(self._page, "Zapisano zmiany!")
            else:
                nadpisano = db.dodaj_odczyt_przebiegu(self.state.auto_id, nowy, e_data.value, e_notatka.value)
                utils.pokaz_komunikat(self._page, "Zaktualizowano odczyt z tego dnia!" if nadpisano else "Dodano odczyt przebiegu!")
            utils.wypchnij_w_tle(self._page, self.state.auto_id, "odczyt przebiegu")
            utils.przejdz(self._page, "/przebieg")

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([ft.Icon(ft.Icons.SPEED, color=ft.Colors.PRIMARY), ft.Text("Edycja odczytu" if edycja else "Nowy odczyt", weight="bold")], spacing=8),
            content=ft.Column([
                e_data,
                e_przebieg,
                e_notatka,
                ft.Text(
                    "Jeśli dla wybranej daty istnieje już odczyt, zostanie zaktualizowany.",
                    size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT, visible=not edycja
                )
            ], tight=True, spacing=10),
            actions=[
                ft.TextButton("Anuluj", on_click=lambda e: utils.zamknij_dialog(self._page, dlg)),
                ft.ElevatedButton("Zapisz", on_click=zapisz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY)
            ],
            actions_alignment=ft.MainAxisAlignment.END
        )
        utils.otworz_dialog(self._page, dlg)