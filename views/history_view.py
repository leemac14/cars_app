import flet as ft
import db
import sync
import utils
from date import parsuj_date

class HistoriaView(ft.View, utils.ZaznaczanieGrupowe):
    def __init__(self, page: ft.Page, state, z_id):
        self._page = page
        self.state = state
        wspolny_id, _ = sync.czy_udostepniony(self.state.auto_id)
        
        with db.polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT nazwa, dotyczy_opon FROM zadania WHERE id=?", (z_id,))
            w = c.fetchone()
        z_nazwa = str(w[0]) if w else self.state.wybrane_zadanie_nazwa
        self.state.wybrane_zadanie_id = z_id
        self.state.wybrane_zadanie_nazwa = z_nazwa
        czy_opony = bool(w[1]) if w else False

        appbar = utils.zbuduj_pasek_z_powrotem(
            page, f"Historia: {z_nazwa}", "/",
            akcje_dodatkowe=[utils.przycisk_synchronizacji(page, utils.funkcja_szybkiej_synchronizacji(page, self.state.auto_id, f"/historia/{z_id}"))] if wspolny_id else None
        )
        fab = utils.fab_animowany(ft.Icons.ADD, lambda e: utils.przejdz(self._page, f"/wpis/nowy/{z_id}"))

        # --- ZMIENNE DLA GRUPOWEGO USUWANIA ---
        self.tryb_zaznaczania = False
        self.zaznaczone_id = set()
        self.oryginalny_appbar = appbar
        self.karty_ref = {}
        self.uzyj_wirtualizacji = False
        # --------------------------------------

        def tresc():
            # Historia podzespołu potrafi mieć kilkadziesiąt wpisów, każdy z kartą,
            # załącznikiem i notatką — budujemy ją dopiero tutaj, czyli już po tym,
            # jak zarys trafi na ekran.
            elementy = []
            with db.polacz_baze() as conn:
                c = conn.cursor()
                c.execute("SELECT h.id, h.data, h.przebieg, h.cena, h.wizyta_id, w.koszt_calkowity, h.kategoria, h.zalacznik, h.dodane_przez, h.zmodyfikowane_przez, h.data_modyfikacji, h.notatka, h.notatka_autor, h.notatka_data FROM historia h LEFT JOIN wizyty w ON h.wizyta_id=w.id WHERE h.zadanie_id=?", (z_id,))
                wpisy = c.fetchall()
            # Części z magazynu przy pojedynczych wpisach — ich koszt siedzi już
            # w cenie wpisu, a dopisek mówi, ile z niej przyszło z półki.
            zuzycie_wpisow = db.pobierz_zuzycie_rekordow("historia", [w[0] for w in wpisy if w[4] is None])

            if not wpisy:
                elementy.append(ft.Text("Brak wpisów w historii. Kliknij + aby dodać.", color=ft.Colors.ON_SURFACE_VARIANT))
            else:
                opcje_sort = [
                    ("Data", "data", lambda x: (parsuj_date(x[1]), x[0])),
                    ("Przebieg", "przebieg", lambda x: int(x[2] or 0)),
                    ("Cena", "cena", lambda x: float((x[5] if x[4] else x[3]) or 0))
                ]

                sort_ui = utils.przycisk_sortowania(self._page, self.state, "historia", opcje_sort)
                chipy_filtrow, wpisy_po_filtrach = utils.pasek_filtrow(
                    self._page, self.state, wpisy,
                    [("rok", "historia_rok", 1), ("miesiac", "historia_mc", 1)])

                elementy.append(ft.Row(controls=[sort_ui] + chipy_filtrow, scroll=ft.ScrollMode.ADAPTIVE, spacing=8))

                # --- POPRAWNA INICJALIZACJA WYSZUKIWARKI ---
                self.lista_kart = ft.ListView(spacing=15, padding=0, height=utils.wysokosc_listy(self._page), auto_scroll=False)
                utils.pamietaj_pozycje(self._page, self.state, self.lista_kart, "lista:historia")
                self.uzyj_wirtualizacji = True
                self.wszystkie_karty = []
                self.miesiace = utils.GrupyMiesiecy(
                    self._page, self.lista_kart, wysokosc_pozycji=190
                )

                def filtruj_historie(e):
                    zapytanie = e.control.value.lower().strip()
                    self.miesiace.ustaw(
                        [k for k in self.wszystkie_karty if zapytanie in k["szukaj"]],
                        grupuj=utils.czy_po_dacie(self.state, "historia"),
                    )
                    utils.dopasuj_wysokosc_listy(self.lista_kart, self._page, wysokosc_pozycji=190)
                    self.update()

                self.pole_wyszukiwarki = ft.TextField(
                    hint_text="Szukaj (np. przebieg, data, notatki)...",
                    prefix_icon=ft.Icons.SEARCH,
                    on_change=utils.z_opoznieniem(self._page, filtruj_historie),
                    **utils.styl_pola()
                )
                elementy.append(self.pole_wyszukiwarki)
                # -------------------------------------------

                # Filtrowanie i sortowanie listy wpisów
                wpisy = wpisy_po_filtrach
                utils.posortuj_liste(wpisy, self.state, "historia", opcje_sort)

                def otworz_menu_historii(h_id, w_id, zalacznik=None, notatka=None):
                    # Wpisu z wizyty zbiorczej nadal nie edytujemy stąd (dane trzyma
                    # wizyta), ale NOTATKĘ da się dopisać — jest własnością tego
                    # jednego wpisu, więc blokowanie jej tutaj byłoby sztuczne.
                    if w_id:
                        utils.pokaz_menu_kontekstowe(self._page, "Wpis z wizyty zbiorczej", [
                            utils.pozycja_menu_notatki(
                                self._page, "historia", h_id, notatka,
                                lambda: utils.przejdz(self._page, f"/historia/{z_id}"), "Notatka do wpisu"
                            ),
                            {"ikona": ft.Icons.OPEN_IN_NEW, "tekst": "Edytuj w „Wizyty zbiorcze”",
                             "akcja": lambda: utils.przejdz(self._page, "/wizyty")},
                        ])
                        return

                    def usun_wpis():
                        def wykonaj():
                            wynik = db.usun_z_cofnieciem("historia", h_id)
                            if wynik:
                                oryginalne_cofnij = wynik["cofnij"]
                                def nowe_cofnij():
                                    oryginalne_cofnij()
                                    db.aktualizuj_najnowszy_wpis(z_id)
                                wynik["cofnij"] = nowe_cofnij
                            db.aktualizuj_najnowszy_wpis(z_id)
                            utils.przejdz(self._page, f"/historia/{z_id}")
                            utils.pokaz_komunikat_cofnij(self._page, "Usunięto wpis.", wynik)
                        utils.potwierdz(self._page, "Usunąć?", "Czy na pewno usunąć ten wpis z historii?", wykonaj)

                    async def dodaj_zmien_zdj():
                        await utils.szybkie_dodanie_zdjecia(self._page, "historia", h_id, zalacznik, lambda: utils.przejdz(self._page, f"/historia/{z_id}"))

                    pozycje = []
                    if zalacznik:
                        pozycje.append({"ikona": ft.Icons.IMAGE, "tekst": "Pokaż zdjęcie", "czyta": True, "akcja": lambda: utils.pokaz_podglad_zalacznika(self._page, zalacznik, "Historia")})
                        pozycje.append({"ikona": ft.Icons.EDIT_DOCUMENT, "tekst": "Zmień zdjęcie", "akcja": dodaj_zmien_zdj})
                    else:
                        pozycje.append({"ikona": ft.Icons.ADD_A_PHOTO, "tekst": "Dodaj zdjęcie (paragon/faktura)", "akcja": dodaj_zmien_zdj})
                
                    pozycje.append(utils.pozycja_menu_notatki(
                        self._page, "historia", h_id, notatka,
                        lambda: utils.przejdz(self._page, f"/historia/{z_id}"), "Notatka do wpisu"
                    ))
                    pozycje.append({"ikona": ft.Icons.EDIT, "tekst": "Edytuj wpis", "akcja": lambda: utils.przejdz(self._page, f"/wpis/edytuj/{h_id}")})
                    pozycje.append({"ikona": ft.Icons.CONTENT_COPY, "tekst": "Duplikuj", "akcja": lambda: (setattr(self.state, "duplikuj_zrodlo_wpis", h_id), utils.przejdz(self._page, f"/wpis/nowy/{z_id}"))})
                    pozycje.append({"ikona": ft.Icons.DELETE, "tekst": "Usuń wpis", "akcja": usun_wpis, "kolor": utils.KOLOR_STATUS["destructive"]})

                    pozycje = utils.odsiej_akcje(self.state.auto_id, pozycje, "historia", h_id)
                    utils.pokaz_menu_kontekstowe(self._page, "Opcje wpisu", pozycje)

                for w in wpisy:
                    (h_id, data, prz, cena, w_id, w_koszt, kategoria, zalacznik, dodane_przez,
                     zmodyfikowane_przez, data_modyfikacji, notatka, notatka_autor, notatka_data) = w
                    jest_zbiorcza = w_id is not None
                    # Dla wpisów z wizyty zbiorczej pokazujemy koszt CAŁEJ wizyty (obejmuje
                    # też inne podzespoły) - dopisek zapobiega myleniu go z kosztem tej pozycji.
                    if jest_zbiorcza:
                        k_str = f"{utils.formatuj_liczba(float(w_koszt or 0))}  {utils.symbol_waluty()} (cała wizyta)"
                    else:
                        k_str = f"{utils.formatuj_liczba(float(cena or 0))}  {utils.symbol_waluty()}"
                    sub_tekst = f"Przebieg: {utils.formatuj_liczba(int(prz or 0), 0)} km  |  {'Wizyta Zbiorcza' if jest_zbiorcza else 'Pojedynczy wpis'}"
                    if czy_opony and kategoria: sub_tekst += f"\nOpony: {kategoria}"
                    opis_magazynu = utils.opis_zuzycia_z_magazynu(zuzycie_wpisow.get(h_id))

                    tresc_h = [
                        ft.Row([
                            ft.Text(str(data), weight="bold", size=16, expand=True), 
                            ft.Row([
                                utils.wskaznik_zalacznika(self._page, zalacznik, "Wpis historii"),
                                ft.Text(k_str, color=utils.KOLOR_STATUS["cost"], weight="bold")
                            ], spacing=6)
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Text(sub_tekst, size=13, color=ft.Colors.ON_SURFACE_VARIANT)
                    ]
                    if opis_magazynu:
                        tresc_h.append(ft.Text(opis_magazynu, size=13, color=ft.Colors.TEAL_700))
                    tresc_h.append(utils.podglad_notatki(
                        self._page, notatka, notatka_autor, notatka_data, "Notatka do wpisu",
                        on_edytuj=lambda rid=h_id: utils.szybka_notatka(
                            self._page, "historia", rid,
                            lambda: utils.przejdz(self._page, f"/historia/{z_id}"), "Notatka do wpisu"
                        ),
                        pokaz_podpis=bool(wspolny_id)
                    ))
                    if wspolny_id and (dodane_przez or zmodyfikowane_przez):
                        tresc_h.append(utils.znacznik_atrybucji(dodane_przez, zmodyfikowane_przez, data_modyfikacji))
                    karta, kontener = utils.karta_listy(
                        ft.Column(tresc_h, spacing=4),
                        kolor_paska=ft.Colors.RED_700 if jest_zbiorcza else ft.Colors.ORANGE_700,  # paleta: tożsamość — pasek karty mówi, jaki to wpis, nie w jakim jest stanie
                        page=self._page,
                    )

                    self.karty_ref[h_id] = kontener

                    def _on_click(e, hid=h_id, wid=w_id, kont=kontener, zal=zalacznik, nt=notatka):
                        if self.tryb_zaznaczania:
                            if wid:
                                utils.pokaz_komunikat(self._page, "Wpisów z Wizyty Zbiorczej nie można grupować stąd. Usuń całą wizytę.", utils.KOLOR_STATUS["warning"])
                            else:
                                self.zaznacz_odznacz(hid, kont)
                        else:
                            otworz_menu_historii(hid, wid, zal, nt)

                    def _on_long_press(e, hid=h_id, wid=w_id, kont=kontener):
                        if wid: return 
                        if not self.tryb_zaznaczania:
                            self.tryb_zaznaczania = True
                            self.zaznacz_odznacz(hid, kont)

                    kontener.on_click = _on_click
                    kontener.on_long_press = _on_long_press

                    tekst_szukaj = f"{data} {sub_tekst} {k_str} {opis_magazynu} {notatka or ''}".lower()
                    self.wszystkie_karty.append({
                        "karta": karta, "szukaj": tekst_szukaj, "data": data,
                        # Wpis z wizyty zbiorczej niesie koszt CAŁEJ wizyty — do
                        # sumy miesiąca bierzemy wyłącznie cenę tej pozycji,
                        # inaczej jedna wizyta liczyłaby się tyle razy, ile miała
                        # podzespołów.
                        "kwota": float(cena or 0),
                    })

                self.miesiace.ustaw(
                    self.wszystkie_karty,
                    grupuj=utils.czy_po_dacie(self.state, "historia"),
                )
                utils.dopasuj_wysokosc_listy(self.lista_kart, self._page, wysokosc_pozycji=190)
                elementy.append(self.miesiace.kontrolka)
                elementy.append(self.lista_kart)

            # To jest linijka poza blokiem else (już ją masz)
            elementy.append(utils.dol_bezpieczny(10))
            return ft.Column(elementy, spacing=15)


        super().__init__(
            route=f"/historia/{z_id}",
            padding=15,
            appbar=appbar,
            floating_action_button=fab,
            spacing=15,
            controls=[utils.zbuduj_etapami(
                page, utils.szkielet_ekranu(page, kafle=2, karty=4), tresc, widok=self,
            )],
            scroll=ft.ScrollMode.AUTO,  # natywne przewijanie
        )

    def potwierdz_grupowe_usuwanie(self, e):
        ile = len(self.zaznaczone_id)
        zadanie_id = self.state.wybrane_zadanie_id

        def wykonaj():
            wynik = db.usun_wiele_z_cofnieciem("historia", list(self.zaznaczone_id))
            if wynik:
                oryginalne_cofnij = wynik["cofnij"]
                def nowe_cofnij():
                    oryginalne_cofnij()
                    db.aktualizuj_najnowszy_wpis(zadanie_id)
                wynik["cofnij"] = nowe_cofnij

            db.aktualizuj_najnowszy_wpis(zadanie_id)
            self.zakoncz_zaznaczanie()
            utils.przejdz(self._page, f"/historia/{zadanie_id}")
            utils.pokaz_komunikat_cofnij(self._page, f"Usunięto {ile} wpisów z historii.", wynik)

        utils.potwierdz(self._page, "Usuwanie wpisów", f"Czy na pewno usunąć {ile} elementów z historii?", wykonaj)

class WizytyZbiorczeView(ft.View, utils.ZaznaczanieGrupowe):
    def _zwroc_pozycje_na_liste(self, wizyta_id):
        """Zdejmuje wybrane pozycje z wizyty i odkłada je z powrotem na listę
        Do zrobienia. Koszt każdej wraca jako szacowany i jest odejmowany od
        kosztu całkowitego wizyty — zostaje w niej tylko to, co zrobiono."""
        pozycje = db.pobierz_pozycje_wizyty(wizyta_id)
        if not pozycje:
            utils.pokaz_komunikat(self._page, "Ta wizyta nie ma pozycji do zwrotu.", ft.Colors.ON_SURFACE_VARIANT)
            return

        checkboxy = [
            ft.Checkbox(
                label=(f"{p['nazwa']}  ·  {utils.formatuj_liczba(p['cena'])} {utils.symbol_waluty()}"
                       if p["cena"] else p["nazwa"]),
                value=False, data=p["id"],
            )
            for p in pozycje
        ]
        blad = ft.Text("", color=utils.KOLOR_STATUS["error"], size=12, visible=False)

        def wykonaj(e):
            wybrane = [chk.data for chk in checkboxy if chk.value]
            if not wybrane:
                blad.value = "Zaznacz przynajmniej jedną pozycję."
                blad.visible = True
                self._page.update()
                return

            utils.zamknij_dialog(self._page, dlg)
            wynik = db.zwroc_pozycje_wizyty_do_zrobienia(wizyta_id, wybrane)
            if not wynik:
                utils.pokaz_komunikat(self._page, "Nie udało się zwrócić pozycji.", utils.KOLOR_STATUS["error"])
                return

            # Po cofnięciu przebudowujemy przeliczenia podzespołów — zwrot
            # zmienia daty ostatnich wymian tak samo, jak zmieniał je zapis wizyty.
            oryginalne_cofnij = wynik["cofnij"]
            def nowe_cofnij():
                oryginalne_cofnij()
                db.przelicz_wszystkie_zadania(self.state.auto_id)
            wynik["cofnij"] = nowe_cofnij

            utils.przejdz(self._page, "/wizyty")
            ile = wynik["liczba"]
            komunikat = (f"Zwrócono „{wynik['nazwy'][0]}” na listę Do zrobienia."
                         if ile == 1 else f"Zwrócono {ile} pozycje na listę Do zrobienia.")
            if wynik["kwota"]:
                komunikat += f" Koszt wizyty pomniejszony o {utils.formatuj_liczba(wynik['kwota'])} {utils.symbol_waluty()}."
            utils.pokaz_komunikat_cofnij(self._page, komunikat, wynik)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Zwrot na listę Do zrobienia", weight="bold"),
            content=ft.Column([
                ft.Text("Zaznacz pozycje, które wracają na listę — np. część zamówioną, "
                        "ale jeszcze niezamontowaną."),
                ft.Container(height=5),
                ft.Column(checkboxy, tight=True, spacing=0),
                blad,
                ft.Text(
                    "Zaznaczone pozycje znikną z tej wizyty, a ich koszt zostanie odjęty od "
                    "kosztu całkowitego. Wrócą na listę z ceną jako szacowanym kosztem.",
                    size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
                ),
            ], tight=True, scroll=ft.ScrollMode.AUTO),
            actions=[
                ft.TextButton("Anuluj", on_click=lambda e: utils.zamknij_dialog(self._page, dlg)),
                ft.TextButton("Zwróć", style=ft.ButtonStyle(color=ft.Colors.PRIMARY), on_click=wykonaj),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        utils.otworz_dialog(self._page, dlg)

    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state
        wspolny_id, _ = sync.czy_udostepniony(self.state.auto_id)

        appbar = utils.zbuduj_pasek_z_powrotem(
            page, "Wizyty Zbiorcze", "/",
            akcje_dodatkowe=[utils.przycisk_synchronizacji(page, utils.funkcja_szybkiej_synchronizacji(page, self.state.auto_id, "/wizyty"))] if wspolny_id else None
        )
        fab = utils.fab_animowany(ft.Icons.ADD, lambda e: utils.przejdz(self._page, "/wizyty/nowa"))

        # --- ZMIENNE DLA GRUPOWEGO USUWANIA ---
        self.tryb_zaznaczania = False
        self.zaznaczone_id = set()
        self.oryginalny_appbar = appbar
        self.karty_ref = {}
        self.uzyj_wirtualizacji = False
        # --------------------------------------

        elementy = []
        opcje_sort = [
            ("Data", "data", lambda x: (parsuj_date(x[1]), x[0])),
            ("Przebieg", "przebieg", lambda x: int(x[2] or 0)),
            ("Koszt", "koszt", lambda x: float(x[4] or 0))
        ]

        with db.polacz_baze() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT w.id, w.data, w.przebieg, w.wykonawca, w.koszt_calkowity, w.zalacznik, w.tagi,
                       GROUP_CONCAT(z.nazwa, ', ') as czesci, w.dodane_przez,
                       w.zmodyfikowane_przez, w.data_modyfikacji, w.notatki
                FROM wizyty w
                LEFT JOIN historia h ON h.wizyta_id = w.id
                LEFT JOIN zadania z ON h.zadanie_id = z.id
                WHERE w.auto_id = ?
                GROUP BY w.id
            """, (self.state.auto_id,))
            wizyty_lista = c.fetchall()

        # Zużyte części z magazynu osobnym zapytaniem — celowo NIE w tym samym
        # JOIN-ie co historia/zadania (patrz db.pobierz_zuzycie_rekordow). Razem
        # z nazwami idzie koszt, który jest już wliczony w koszt wizyty.
        zuzycie_wizyt = db.pobierz_zuzycie_rekordow("wizyty", [w[0] for w in wizyty_lista])

        sort_ui = utils.przycisk_sortowania(self._page, self.state, "wizyty", opcje_sort)
        spis_filtrow = [
            ("rok", "wizyty_rok", 1),
            ("miesiac", "wizyty_mc", 1),
            ("kategoria", "wizyty_wyk", 3, "Warsztat"),
            ("kategoria", "wizyty_tag", 6, "Tagi"),
        ]
        # Kolumna 8 zapytania to w.dodane_przez — filtr autorstwa pokazujemy
        # tylko przy pojeździe współdzielonym, tak jak na osi czasu i listach
        # tankowań oraz innych kosztów.
        if wspolny_id:
            spis_filtrow.append(("autor", "wizyty_autor", 8))

        chipy_filtrow, wizyty_po_filtrach = utils.pasek_filtrow(
            self._page, self.state, wizyty_lista, spis_filtrow)

        elementy.append(ft.Row(controls=[sort_ui] + chipy_filtrow, scroll=ft.ScrollMode.ADAPTIVE, spacing=8))

        wizyty_lista = wizyty_po_filtrach
        utils.posortuj_liste(wizyty_lista, self.state, "wizyty", opcje_sort)

        # --- 1. DODAJ TEN BLOK KODU (WYSZUKIWARKA) ---
        def filtruj_wizyty(e):
            zapytanie = e.control.value.lower().strip()
            self.miesiace.ustaw(
                [k for k in self.wszystkie_karty if zapytanie in k["szukaj"]],
                grupuj=utils.czy_po_dacie(self.state, "wizyty"),
            )
            utils.dopasuj_wysokosc_listy(self.lista_kart, self._page, wysokosc_pozycji=190)
            self.update()

        self.pole_wyszukiwarki = ft.TextField(
            hint_text="Szukaj (część, warsztat, data, koszt)...",
            prefix_icon=ft.Icons.SEARCH,
            on_change=utils.z_opoznieniem(self._page, filtruj_wizyty),
            **utils.styl_pola()
        )
        elementy.append(self.pole_wyszukiwarki)

        self.lista_kart = ft.ListView(spacing=15, padding=0, height=utils.wysokosc_listy(self._page), auto_scroll=False)
        utils.pamietaj_pozycje(self._page, self.state, self.lista_kart, "lista:wizyty")
        self.uzyj_wirtualizacji = True
        self.wszystkie_karty = []
        self.miesiace = utils.GrupyMiesiecy(
            self._page, self.lista_kart, wysokosc_pozycji=190
        )
        # ---------------------------------------------

        def otworz_menu_wiz(wid, zalacznik=None, notatka=None):
            def usun_wizyte():
                def wykonaj():
                    wynik = db.usun_wizyty_z_cofnieciem([wid])
                    if wynik:
                        oryginalne_cofnij = wynik["cofnij"]
                        def nowe_cofnij():
                            oryginalne_cofnij()
                            db.przelicz_wszystkie_zadania(self.state.auto_id)
                        wynik["cofnij"] = nowe_cofnij

                    db.przelicz_wszystkie_zadania(self.state.auto_id)
                    utils.przejdz(self._page, "/wizyty")
                    utils.pokaz_komunikat_cofnij(self._page, "Usunięto wizytę w warsztacie.", wynik)
                utils.potwierdz(self._page, "Usunąć?", "Czy na pewno usunąć tę wizytę zbiorczą?", wykonaj)

            async def dodaj_zmien_zdj():
                await utils.szybkie_dodanie_zdjecia(self._page, "wizyty", wid, zalacznik, lambda: utils.przejdz(self._page, "/wizyty"))

            pozycje = []
            if zalacznik:
                pozycje.append({"ikona": ft.Icons.IMAGE, "tekst": "Pokaż zdjęcie", "czyta": True, "akcja": lambda: utils.pokaz_podglad_zalacznika(self._page, zalacznik, "Wizyta")})
                pozycje.append({"ikona": ft.Icons.EDIT_DOCUMENT, "tekst": "Zmień zdjęcie", "akcja": dodaj_zmien_zdj})
            else:
                pozycje.append({"ikona": ft.Icons.ADD_A_PHOTO, "tekst": "Dodaj zdjęcie", "akcja": dodaj_zmien_zdj})
                
            pozycje.append(utils.pozycja_menu_notatki(
                self._page, "wizyty", wid, notatka,
                lambda: utils.przejdz(self._page, "/wizyty"), "Notatka do wizyty"
            ))
            pozycje.append({"ikona": ft.Icons.EDIT, "tekst": "Edytuj wizytę", "akcja": lambda: utils.przejdz(self._page, f"/wizyty/edytuj/{wid}")})
            pozycje.append({
                "ikona": ft.Icons.CONTENT_COPY,
                "tekst": "Duplikuj wizytę",
                "akcja": lambda: (
                    setattr(self.state, "duplikuj_zrodlo_wizyta", wid),
                    utils.przejdz(self._page, "/wizyty/nowa"),
                ),
            })
            # Droga powrotna do "Zamień na wizytę" z listy Do zrobienia: część
            # bywa zamówiona przy okazji wizyty, ale montowana dopiero później.
            if db.pobierz_pozycje_wizyty(wid):
                pozycje.append({
                    "ikona": ft.Icons.ASSIGNMENT_RETURN,
                    "tekst": "Zwróć pozycję na listę Do zrobienia",
                    "akcja": lambda: self._zwroc_pozycje_na_liste(wid),
                })
            pozycje.append({"ikona": ft.Icons.DELETE, "tekst": "Usuń wizytę", "akcja": usun_wizyte, "kolor": utils.KOLOR_STATUS["destructive"]})

            pozycje = utils.odsiej_akcje(self.state.auto_id, pozycje, "wizyty", wid)
            utils.pokaz_menu_kontekstowe(self._page, "Opcje wizyty", pozycje)

        if not wizyty_lista:
            elementy.append(ft.Row([ft.Text("Brak wizyt dla wybranych filtrów.", color=ft.Colors.ON_SURFACE_VARIANT)], alignment=ft.MainAxisAlignment.CENTER))
        else:
            mapa_tagow = {t[1]: t[2] for t in db.pobierz_tagi(self.state.auto_id)}
            for w in wizyty_lista:
                (w_id, data, prz, wyk, kosz, zalacznik, tagi, czesci, dodane_przez,
                 zmodyfikowane_przez, data_modyfikacji, notatka_wizyty) = w
                czesci = czesci or "Brak podpiętych części"
                opis_magazynu = utils.opis_zuzycia_z_magazynu(zuzycie_wizyt.get(w_id))

                tresc_karty = [
                    ft.Row([
                        ft.Text(str(data), weight="bold", size=16, expand=True),
                        ft.Row([
                            utils.wskaznik_zalacznika(self._page, zalacznik, "Wizyta"),
                            ft.Text(f"{utils.formatuj_liczba(float(kosz or 0))}  {utils.symbol_waluty()}", color=utils.KOLOR_STATUS["cost"], weight="bold")
                        ], spacing=6)
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Row([
                        ft.Icon(ft.Icons.SPEED, size=14, color=ft.Colors.ON_SURFACE_VARIANT),
                        ft.Text(f"{utils.formatuj_liczba(int(prz or 0), 0)} km", size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                    ], spacing=4),
                    ft.Text(f"Części: {czesci}", size=13, color=ft.Colors.PRIMARY),
                ]
                if opis_magazynu:
                    tresc_karty.append(ft.Text(opis_magazynu, size=13, color=ft.Colors.TEAL_700))
                if tagi:
                    tresc_karty.append(utils.wizualizacja_tagow(tagi, self.state.auto_id, mapa_tagow))
                # Wizyta ma pole „Notatki i uwagi” od zawsze, tylko nigdy nie było
                # widać go na liście — pokazujemy je tym samym komponentem, co
                # notatki pozostałych wpisów (tabela wizyty nie ma podpisu).
                tresc_karty.append(utils.podglad_notatki(
                    self._page, notatka_wizyty, tytul="Notatka do wizyty",
                    on_edytuj=lambda rid=w_id: utils.szybka_notatka(
                        self._page, "wizyty", rid,
                        lambda: utils.przejdz(self._page, "/wizyty"), "Notatka do wizyty"
                    )
                ))
                if wspolny_id and (dodane_przez or zmodyfikowane_przez):
                    tresc_karty.append(utils.znacznik_atrybucji(dodane_przez, zmodyfikowane_przez, data_modyfikacji))

                karta, kontener = utils.karta_listy(
                    ft.Column(tresc_karty, spacing=4),
                    kolor_paska=ft.Colors.RED_700,  # paleta: tożsamość — pasek karty mówi, jaki to wpis
                    page=self._page,
                )

                self.karty_ref[w_id] = kontener

                def _on_click(e, wid=w_id, zal=zalacznik, nt=notatka_wizyty):
                    if self.tryb_zaznaczania:
                        self.zaznacz_odznacz(wid, self.karty_ref[wid])
                    else:
                        otworz_menu_wiz(wid, zal, nt)

                def _on_long_press(e, wid=w_id):
                    if not self.tryb_zaznaczania:
                        self.tryb_zaznaczania = True
                        self.zaznacz_odznacz(wid, self.karty_ref[wid])

                kontener.on_click = _on_click
                kontener.on_long_press = _on_long_press

                magazyn_szukaj = opis_magazynu
                tekst_szukaj = f"{data} {wyk} {czesci} {kosz} {tagi} {magazyn_szukaj} {notatka_wizyty or ''}".lower()
                self.wszystkie_karty.append({
                    "karta": karta, "szukaj": tekst_szukaj,
                    "data": data, "kwota": float(kosz or 0),
                })

            self.miesiace.ustaw(
                self.wszystkie_karty,
                grupuj=utils.czy_po_dacie(self.state, "wizyty"),
            )
            # Lista dokładana TYLKO gdy są wizyty — pusty ListView ma stałą wysokość
            # i zostawiał pod komunikatem „Brak wizyt…” pół ekranu pustki.
            utils.dopasuj_wysokosc_listy(self.lista_kart, self._page, wysokosc_pozycji=190)
            elementy.append(self.miesiace.kontrolka)
            elementy.append(self.lista_kart)

        super().__init__(
            route="/wizyty",
            padding=15,
            appbar=appbar,
            floating_action_button=fab,
            spacing=15,
            controls=elementy,          # lub self.elementy, w zależności jak masz w tym pliku
            scroll=ft.ScrollMode.AUTO,  # włączasz natywne przewijanie
        )

    def potwierdz_grupowe_usuwanie(self, e):
        ile = len(self.zaznaczone_id)
        def wykonaj():
            wynik = db.usun_wizyty_z_cofnieciem(list(self.zaznaczone_id))
            if wynik:
                oryginalne_cofnij = wynik["cofnij"]
                def nowe_cofnij():
                    oryginalne_cofnij()
                    db.przelicz_wszystkie_zadania(self.state.auto_id)
                wynik["cofnij"] = nowe_cofnij

            db.przelicz_wszystkie_zadania(self.state.auto_id)
            self.zakoncz_zaznaczanie()
            utils.przejdz(self._page, "/wizyty")
            utils.pokaz_komunikat_cofnij(self._page, f"Usunięto {ile} wizyt w warsztacie.", wynik)
        utils.potwierdz(self._page, "Usuwanie", f"Czy na pewno usunąć {ile} wybranych wizyt?", wykonaj)