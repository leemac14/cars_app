import flet as ft
import db
import sync
import utils

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

        elementy = []
        with db.polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT h.id, h.data, h.przebieg, h.cena, h.wizyta_id, w.koszt_calkowity, h.kategoria, h.zalacznik, h.dodane_przez, h.zmodyfikowane_przez, h.data_modyfikacji FROM historia h LEFT JOIN wizyty w ON h.wizyta_id=w.id WHERE h.zadanie_id=?", (z_id,))
            wpisy = c.fetchall()

        if not wpisy:
            elementy.append(ft.Text("Brak wpisów w historii. Kliknij + aby dodać.", color=ft.Colors.ON_SURFACE_VARIANT))
        else:
            opcje_sort = [
                ("Data", "data", lambda x: (utils.parsuj_date(x[1]), x[0])),
                ("Przebieg", "przebieg", lambda x: int(x[2] or 0)),
                ("Cena", "cena", lambda x: float((x[5] if x[4] else x[3]) or 0))
            ]

            sort_ui = utils.przycisk_sortowania(self._page, self.state, "historia", opcje_sort)
            filtr_rok_ui = utils.przycisk_filtrowania_rok(self._page, self.state, "historia_rok", wpisy, 1)
            filtr_mc_ui = utils.przycisk_filtrowania_miesiac(self._page, self.state, "historia_mc", wpisy, 1)

            elementy.append(ft.Row([sort_ui, filtr_rok_ui, filtr_mc_ui], spacing=6, scroll=ft.ScrollMode.HIDDEN))

            # --- POPRAWNA INICJALIZACJA WYSZUKIWARKI ---
            self.lista_kart = ft.ListView(spacing=15, padding=0, height=utils.wysokosc_listy(self._page), auto_scroll=False)
            self.uzyj_wirtualizacji = True
            self.wszystkie_karty = []

            def filtruj_historie(e):
                zapytanie = e.control.value.lower().strip()
                self.lista_kart.controls.clear()
                for k in self.wszystkie_karty:
                    if zapytanie in k["szukaj"]:
                        self.lista_kart.controls.append(k["karta"])
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
            wpisy = utils.filtruj_po_roku(wpisy, self.state, "historia_rok", 1)
            wpisy = utils.filtruj_po_miesiacu(wpisy, self.state, "historia_mc", 1)
            utils.posortuj_liste(wpisy, self.state, "historia", opcje_sort)

            def otworz_menu_historii(h_id, w_id, zalacznik=None):
                if w_id:
                    utils.pokaz_komunikat(self._page, "Wpis to część wizyty zbiorczej. Otwórz 'Wizyty Zbiorcze', aby go edytować.", ft.Colors.ORANGE_700)
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
                    pozycje.append({"ikona": ft.Icons.IMAGE, "tekst": "Pokaż zdjęcie", "akcja": lambda: utils.pokaz_podglad_zalacznika(self._page, zalacznik, "Historia")})
                    pozycje.append({"ikona": ft.Icons.EDIT_DOCUMENT, "tekst": "Zmień zdjęcie", "akcja": dodaj_zmien_zdj})
                else:
                    pozycje.append({"ikona": ft.Icons.ADD_A_PHOTO, "tekst": "Dodaj zdjęcie (paragon/faktura)", "akcja": dodaj_zmien_zdj})
                
                pozycje.append({"ikona": ft.Icons.EDIT, "tekst": "Edytuj wpis", "akcja": lambda: utils.przejdz(self._page, f"/wpis/edytuj/{h_id}")})
                pozycje.append({"ikona": ft.Icons.DELETE, "tekst": "Usuń wpis", "akcja": usun_wpis, "kolor": ft.Colors.RED})

                utils.pokaz_menu_kontekstowe(self._page, "Opcje wpisu", pozycje)

            for w in wpisy:
                h_id, data, prz, cena, w_id, w_koszt, kategoria, zalacznik, dodane_przez, zmodyfikowane_przez, data_modyfikacji = w
                jest_zbiorcza = w_id is not None
                # Dla wpisów z wizyty zbiorczej pokazujemy koszt CAŁEJ wizyty (obejmuje
                # też inne podzespoły) - dopisek zapobiega myleniu go z kosztem tej pozycji.
                if jest_zbiorcza:
                    k_str = f"{utils.formatuj_liczba(float(w_koszt or 0))}  {utils.symbol_waluty()} (cała wizyta)"
                else:
                    k_str = f"{utils.formatuj_liczba(float(cena or 0))}  {utils.symbol_waluty()}"
                sub_tekst = f"Przebieg: {utils.formatuj_liczba(int(prz or 0), 0)} km  |  {'Wizyta Zbiorcza' if jest_zbiorcza else 'Pojedynczy wpis'}"
                if czy_opony and kategoria: sub_tekst += f"\nOpony: {kategoria}"

                tresc_h = [
                    ft.Row([
                        ft.Text(str(data), weight="bold", size=16), 
                        ft.Row([
                            utils.wskaznik_zalacznika(self._page, zalacznik, "Wpis historii"),
                            ft.Text(k_str, color=ft.Colors.RED_700, weight="bold")
                        ], spacing=6)
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Text(sub_tekst, size=13, color=ft.Colors.ON_SURFACE_VARIANT)
                ]
                if wspolny_id and (dodane_przez or zmodyfikowane_przez):
                    tresc_h.append(utils.znacznik_atrybucji(dodane_przez, zmodyfikowane_przez, data_modyfikacji))
                karta, kontener = utils.karta_listy(
                    ft.Column(tresc_h, spacing=4),
                    kolor_paska=ft.Colors.RED_700 if jest_zbiorcza else ft.Colors.ORANGE_700,
                    page=self._page,
                )

                self.karty_ref[h_id] = kontener

                def _on_click(e, hid=h_id, wid=w_id, kont=kontener, zal=zalacznik):
                    if self.tryb_zaznaczania:
                        if wid:
                            utils.pokaz_komunikat(self._page, "Wpisów z Wizyty Zbiorczej nie można grupować stąd. Usuń całą wizytę.", ft.Colors.ORANGE_700)
                        else:
                            self.zaznacz_odznacz(hid, kont)
                    else:
                        otworz_menu_historii(hid, wid, zal)

                def _on_long_press(e, hid=h_id, wid=w_id, kont=kontener):
                    if wid: return 
                    if not self.tryb_zaznaczania:
                        self.tryb_zaznaczania = True
                        self.zaznacz_odznacz(hid, kont)

                kontener.on_click = _on_click
                kontener.on_long_press = _on_long_press

                tekst_szukaj = f"{data} {sub_tekst} {k_str}".lower()
                self.wszystkie_karty.append({"karta": karta, "szukaj": tekst_szukaj})
                self.lista_kart.controls.append(karta)

            elementy.append(self.lista_kart)

        # To jest linijka poza blokiem else (już ją masz)
        elementy.append(utils.dol_bezpieczny(10))

        super().__init__(
            route=f"/historia/{z_id}",
            padding=15,
            appbar=appbar,
            floating_action_button=fab,
            spacing=15,
            controls=elementy,          # lub self.elementy, w zależności jak masz w tym pliku
            scroll=ft.ScrollMode.AUTO,  # włączasz natywne przewijanie
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
            ("Data", "data", lambda x: (utils.parsuj_date(x[1]), x[0])),
            ("Przebieg", "przebieg", lambda x: int(x[2] or 0)),
            ("Koszt", "koszt", lambda x: float(x[4] or 0))
        ]

        with db.polacz_baze() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT w.id, w.data, w.przebieg, w.wykonawca, w.koszt_calkowity, w.zalacznik, w.tagi,
                       GROUP_CONCAT(z.nazwa, ', ') as czesci, w.dodane_przez,
                       w.zmodyfikowane_przez, w.data_modyfikacji
                FROM wizyty w
                LEFT JOIN historia h ON h.wizyta_id = w.id
                LEFT JOIN zadania z ON h.zadanie_id = z.id
                WHERE w.auto_id = ?
                GROUP BY w.id
            """, (self.state.auto_id,))
            wizyty_lista = c.fetchall()

            # Osobne zapytanie o zużyte części z magazynu — celowo NIE w tym samym
            # JOIN-ie co historia/zadania, żeby uniknąć krzyżowego zdublowania wierszy
            # (i tym samym duplikatów w GROUP_CONCAT) przy wizytach z >1 podzespołem
            # ORAZ >1 zużytą częścią jednocześnie.
            c.execute("""
                SELECT wcm.wizyta_id, mc.nazwa, wcm.ilosc_uzyta, mc.jednostka
                FROM wizyta_czesci_magazynu wcm
                JOIN magazyn_czesci mc ON wcm.magazyn_id = mc.id
                JOIN wizyty w ON wcm.wizyta_id = w.id
                WHERE w.auto_id = ?
            """, (self.state.auto_id,))
            czesci_magazynu_wg_wizyty = {}
            for wiz_id, m_nazwa, m_ilosc, m_jedn in c.fetchall():
                opis = f"{m_nazwa} ({utils.formatuj_liczba(m_ilosc, 2)} {m_jedn or 'szt'})"
                czesci_magazynu_wg_wizyty.setdefault(wiz_id, []).append(opis)

        sort_ui = utils.przycisk_sortowania(self._page, self.state, "wizyty", opcje_sort)
        filtr_rok_ui = utils.przycisk_filtrowania_rok(self._page, self.state, "wizyty_rok", wizyty_lista, 1)
        filtr_mc_ui = utils.przycisk_filtrowania_miesiac(self._page, self.state, "wizyty_mc", wizyty_lista, 1)
        filtr_wyk_ui = utils.przycisk_filtrowania_kategoria(self._page, self.state, "wizyty_wyk", wizyty_lista, 3, "Warsztat")
        filtr_tag_ui = utils.przycisk_filtrowania_kategoria(self._page, self.state, "wizyty_tag", wizyty_lista, 6, "Tagi")

        elementy.append(ft.Row([sort_ui, filtr_rok_ui, filtr_mc_ui, filtr_wyk_ui, filtr_tag_ui], spacing=6, scroll=ft.ScrollMode.HIDDEN))

        wizyty_lista = utils.filtruj_po_roku(wizyty_lista, self.state, "wizyty_rok", 1)
        wizyty_lista = utils.filtruj_po_miesiacu(wizyty_lista, self.state, "wizyty_mc", 1)
        wizyty_lista = utils.filtruj_po_kategorii(wizyty_lista, self.state, "wizyty_wyk", 3)
        wizyty_lista = utils.filtruj_po_kategorii(wizyty_lista, self.state, "wizyty_tag", 6)
        utils.posortuj_liste(wizyty_lista, self.state, "wizyty", opcje_sort)

        # --- 1. DODAJ TEN BLOK KODU (WYSZUKIWARKA) ---
        def filtruj_wizyty(e):
            zapytanie = e.control.value.lower().strip()
            self.lista_kart.controls.clear()
            for k in self.wszystkie_karty:
                if zapytanie in k["szukaj"]:
                    self.lista_kart.controls.append(k["karta"])
            self.update()

        self.pole_wyszukiwarki = ft.TextField(
            hint_text="Szukaj (część, warsztat, data, koszt)...",
            prefix_icon=ft.Icons.SEARCH,
            on_change=utils.z_opoznieniem(self._page, filtruj_wizyty),
            **utils.styl_pola()
        )
        elementy.append(self.pole_wyszukiwarki)

        self.lista_kart = ft.ListView(spacing=15, padding=0, height=utils.wysokosc_listy(self._page), auto_scroll=False)
        self.uzyj_wirtualizacji = True
        self.wszystkie_karty = []
        # ---------------------------------------------

        def otworz_menu_wiz(wid, zalacznik=None):
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
                pozycje.append({"ikona": ft.Icons.IMAGE, "tekst": "Pokaż zdjęcie", "akcja": lambda: utils.pokaz_podglad_zalacznika(self._page, zalacznik, "Wizyta")})
                pozycje.append({"ikona": ft.Icons.EDIT_DOCUMENT, "tekst": "Zmień zdjęcie", "akcja": dodaj_zmien_zdj})
            else:
                pozycje.append({"ikona": ft.Icons.ADD_A_PHOTO, "tekst": "Dodaj zdjęcie", "akcja": dodaj_zmien_zdj})
                
            pozycje.append({"ikona": ft.Icons.EDIT, "tekst": "Edytuj wizytę", "akcja": lambda: utils.przejdz(self._page, f"/wizyty/edytuj/{wid}")})
            pozycje.append({"ikona": ft.Icons.DELETE, "tekst": "Usuń wizytę", "akcja": usun_wizyte, "kolor": ft.Colors.RED})

            utils.pokaz_menu_kontekstowe(self._page, "Opcje wizyty", pozycje)

        if not wizyty_lista:
            elementy.append(ft.Row([ft.Text("Brak wizyt dla wybranych filtrów.", color=ft.Colors.ON_SURFACE_VARIANT)], alignment=ft.MainAxisAlignment.CENTER))
        else:
            mapa_tagow = {t[1]: t[2] for t in db.pobierz_tagi(self.state.auto_id)}
            for w in wizyty_lista:
                w_id, data, prz, wyk, kosz, zalacznik, tagi, czesci, dodane_przez, zmodyfikowane_przez, data_modyfikacji = w
                czesci = czesci or "Brak podpiętych części"
                czesci_magazynowe = czesci_magazynu_wg_wizyty.get(w_id)

                tresc_karty = [
                    ft.Row([
                        ft.Text(str(data), weight="bold", size=16),
                        ft.Row([
                            utils.wskaznik_zalacznika(self._page, zalacznik, "Wizyta"),
                            ft.Text(f"{utils.formatuj_liczba(float(kosz or 0))}  {utils.symbol_waluty()}", color=ft.Colors.RED_700, weight="bold")
                        ], spacing=6)
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Row([
                        ft.Icon(ft.Icons.SPEED, size=14, color=ft.Colors.ON_SURFACE_VARIANT),
                        ft.Text(f"{utils.formatuj_liczba(int(prz or 0), 0)} km", size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT),
                    ], spacing=4),
                    ft.Text(f"Części: {czesci}", size=13, color=ft.Colors.PRIMARY),
                ]
                if czesci_magazynowe:
                    tresc_karty.append(ft.Text(f"Z magazynu: {', '.join(czesci_magazynowe)}", size=13, color=ft.Colors.TEAL_700))
                if tagi:
                    tresc_karty.append(utils.wizualizacja_tagow(tagi, self.state.auto_id, mapa_tagow))
                if wspolny_id and (dodane_przez or zmodyfikowane_przez):
                    tresc_karty.append(utils.znacznik_atrybucji(dodane_przez, zmodyfikowane_przez, data_modyfikacji))

                karta, kontener = utils.karta_listy(
                    ft.Column(tresc_karty, spacing=4),
                    kolor_paska=ft.Colors.RED_700,
                    page=self._page,
                )

                self.karty_ref[w_id] = kontener

                def _on_click(e, wid=w_id, zal=zalacznik):
                    if self.tryb_zaznaczania:
                        self.zaznacz_odznacz(wid, self.karty_ref[wid])
                    else:
                        otworz_menu_wiz(wid, zal)

                def _on_long_press(e, wid=w_id):
                    if not self.tryb_zaznaczania:
                        self.tryb_zaznaczania = True
                        self.zaznacz_odznacz(wid, self.karty_ref[wid])

                kontener.on_click = _on_click
                kontener.on_long_press = _on_long_press

                magazyn_szukaj = " ".join(czesci_magazynowe) if czesci_magazynowe else ""
                tekst_szukaj = f"{data} {wyk} {czesci} {kosz} {tagi} {magazyn_szukaj}".lower()
                self.wszystkie_karty.append({"karta": karta, "szukaj": tekst_szukaj})
                self.lista_kart.controls.append(karta)

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