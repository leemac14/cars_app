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
        self.przewijana_tresc = utils.PrzewijanaTresc()
        # --------------------------------------

        def tresc():
            # Historia podzespołu potrafi mieć kilkadziesiąt wpisów, każdy z kartą,
            # załącznikiem i notatką — budujemy ją dopiero tutaj, czyli już po tym,
            # jak zarys trafi na ekran.
            elementy = []
            with db.polacz_baze() as conn:
                c = conn.cursor()
                c.execute("SELECT h.id, h.data, h.przebieg, h.cena, h.wizyta_id, w.koszt_calkowity, h.kategoria, NULL, h.dodane_przez, h.zmodyfikowane_przez, h.data_modyfikacji, h.notatka, h.notatka_autor, h.notatka_data, h.koszt_robocizny, h.rodzaj FROM historia h LEFT JOIN wizyty w ON h.wizyta_id=w.id WHERE h.zadanie_id=?", (z_id,))
                wpisy = c.fetchall()
            # Części z magazynu przy pojedynczych wpisach — ich koszt siedzi już
            # w cenie wpisu, a dopisek mówi, ile z niej przyszło z półki.
            zuzycie_wpisow = db.pobierz_zuzycie_rekordow("historia", [w[0] for w in wpisy if w[4] is None])
            # Robocizna i części tylko przy pojedynczym wpisie: pozycja wizyty
            # nie ma własnego kosztu — rozbicie niesie cała wizyta. Ostatnia
            # kolumna krotki to wartość filtra „Podział” (pusta przy wizycie).
            rozbicia = {w[0]: db.rozbicie_kosztu(w[3], w[14], (zuzycie_wpisow.get(w[0]) or {}).get("koszt"))
                        for w in wpisy if w[4] is None}
            # Gwarancje napraw po identyfikatorze wpisu — także te, które minęły,
            # i te, po których część wymieniono jeszcze raz (db.gwarancje_wpisow).
            gwarancje = db.gwarancje_wpisow(z_id)
            # Wpisy zapisane z pozycji Do zrobienia — ślad na karcie i droga do Wykonanych.
            z_listy = db.pozycje_do_zrobienia_wpisow(z_id)
            # Pole 7 — lista plików wpisu (db.zalaczniki_pojazdu), jednym zapytaniem.
            pliki_wpisow = db.zalaczniki_pojazdu(self.state.auto_id, "historia")
            # Rodzaj naprawy (pozycja wizyty ma rodzaj wizyty): chip na karcie i ostatnia
            # kolumna krotki — wartość filtra „Rodzaj”.
            rodzaje = {w[0]: w[15] for w in wpisy}
            wpisy = [tuple(w[:7]) + (pliki_wpisow.get(w[0], []),) + tuple(w[8:15])
                     + (utils.etykieta_podzialu(rozbicia.get(w[0])), db.etykieta_rodzaju_serwisu(w[15]))
                     for w in wpisy]

            if not wpisy:
                elementy.append(ft.Text("Brak wpisów w historii. Dotknij +, aby dodać.", color=ft.Colors.ON_SURFACE_VARIANT))
            else:
                opcje_sort = [
                    ("Data", "data", lambda x: (parsuj_date(x[1]), x[0])),
                    ("Przebieg", "przebieg", lambda x: int(x[2] or 0)),
                    # Kwota z karty: cena pozycji, a pozycja wizyty bez ceny — koszt całej wizyty.
                    ("Cena", "cena", lambda x: float((x[5] if x[4] and float(x[3] or 0) <= 0 else x[3]) or 0))
                ]

                sort_ui = utils.przycisk_sortowania(self._page, self.state, "historia", opcje_sort)
                spis_filtrow = [("rok", "historia_rok", 1), ("miesiac", "historia_mc", 1)]
                # „Podział” dopiero wtedy, gdy jest co dzielić — podzespół
                # wymieniany wyłącznie na wizytach nie ma tu własnych kwot.
                if any(w[15] for w in wpisy):
                    spis_filtrow.append(("kategoria", "historia_podzial", 15, "Podział"))
                if any(db.rodzaj_serwisu(r) for r in rodzaje.values()):
                    spis_filtrow.append(("kategoria", "historia_rodzaj", 16, "Rodzaj"))
                chipy_filtrow, wpisy_po_filtrach = utils.pasek_filtrow(
                    self._page, self.state, wpisy, spis_filtrow)

                elementy.append(ft.Row(controls=[sort_ui] + chipy_filtrow, scroll=ft.ScrollMode.ADAPTIVE, spacing=8))

                # --- POPRAWNA INICJALIZACJA WYSZUKIWARKI ---
                self.lista_kart = utils.lista_kart()
                self.wszystkie_karty = []
                self.miesiace = utils.GrupyMiesiecy(
                    self._page, self.lista_kart, wysokosc_pozycji=190, widok=self, klucz="historia"
                )

                def filtruj_historie(e):
                    zapytanie = e.control.value.lower().strip()
                    self.miesiace.ustaw(
                        [k for k in self.wszystkie_karty if zapytanie in k["szukaj"]],
                        grupuj=utils.czy_po_dacie(self.state, "historia"),
                    )
                    self.update()

                self.pole_wyszukiwarki = ft.TextField(
                    hint_text="Szukaj (przebieg, data, notatka)",
                    prefix_icon=ft.Icons.SEARCH,
                    on_change=utils.z_opoznieniem(self._page, filtruj_historie),
                    **utils.styl_pola()
                )
                elementy.append(utils.na_cala_szerokosc(self.pole_wyszukiwarki))
                # -------------------------------------------

                # Filtrowanie i sortowanie listy wpisów
                wpisy = wpisy_po_filtrach
                utils.posortuj_liste(wpisy, self.state, "historia", opcje_sort)

                def usun_wpis_od_razu(h_id):
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

                def notatka_wpisu(h_id):
                    utils.szybka_notatka(self._page, "historia", h_id,
                                         lambda: utils.przejdz(self._page, f"/historia/{z_id}"), "Notatka do wpisu")

                def otworz_menu_historii(h_id, w_id, pliki=None, notatka=None):
                    # Wpisu z wizyty zbiorczej nie edytujemy stąd (dane w wizycie), ale
                    # NOTATKĘ i gwarancję (wyjątek dla podzespołu) tak — należą do
                    # jednej pozycji; obie przechodzą przez sito roli.
                    do_listy = {"ikona": ft.Icons.CHECKLIST_RTL, "tekst": "Pokaż w Do zrobienia", "czyta": True,
                                "akcja": lambda: utils.przejdz(self._page, "/do-zrobienia/wykonane")} \
                        if h_id in z_listy else None
                    if w_id:
                        utils.pokaz_menu_kontekstowe(self._page, "Wpis z wizyty zbiorczej", utils.odsiej_akcje(
                            self.state.auto_id, [
                                utils.pozycja_menu_notatki(
                                    self._page, "historia", h_id, notatka,
                                    lambda: utils.przejdz(self._page, f"/historia/{z_id}"), "Notatka do wpisu"
                                ),
                                {"ikona": ft.Icons.GPP_GOOD,
                                 "tekst": "Zmień gwarancję tej pozycji" if h_id in gwarancje else "Gwarancja tej pozycji",
                                 "akcja": lambda: utils.dialog_gwarancji_wpisu(
                                     self._page, h_id, lambda: utils.przejdz(self._page, f"/historia/{z_id}"))},
                                {"ikona": ft.Icons.OPEN_IN_NEW, "tekst": "Edytuj w „Wizyty w warsztacie”", "czyta": True,
                                 "akcja": lambda: utils.przejdz(self._page, "/wizyty")},
                                do_listy,
                            ], "historia", h_id,
                        ))
                        return

                    def usun_wpis():
                        utils.potwierdz(self._page, "Usunąć?", "Czy na pewno usunąć ten wpis z historii?",
                                        lambda: usun_wpis_od_razu(h_id))

                    pozycje = utils.pozycje_menu_zalacznikow(
                        self._page, "historia", h_id, pliki, "Wpis historii",
                        lambda: utils.przejdz(self._page, f"/historia/{z_id}"))

                    pozycje.append(utils.pozycja_menu_notatki(
                        self._page, "historia", h_id, notatka,
                        lambda: utils.przejdz(self._page, f"/historia/{z_id}"), "Notatka do wpisu"
                    ))
                    pozycje.append({"ikona": ft.Icons.EDIT, "tekst": "Edytuj wpis", "akcja": lambda: utils.przejdz(self._page, f"/wpis/edytuj/{h_id}")})
                    pozycje.append({"ikona": ft.Icons.CONTENT_COPY, "tekst": "Duplikuj", "akcja": lambda: (setattr(self.state, "duplikuj_zrodlo_wpis", h_id), utils.przejdz(self._page, f"/wpis/nowy/{z_id}"))})
                    pozycje.append(do_listy)
                    pozycje.append({"ikona": ft.Icons.DELETE, "tekst": "Usuń wpis", "akcja": usun_wpis, "kolor": utils.KOLOR_STATUS["destructive"]})

                    pozycje = utils.odsiej_akcje(self.state.auto_id, pozycje, "historia", h_id)
                    utils.pokaz_menu_kontekstowe(self._page, "Opcje wpisu", pozycje)

                j = utils.jednostka_dystansu()  # raz na całą listę
                gesty = utils.wolno_zmieniac(self.state.auto_id)  # podgląd: bez gestów
                for w in wpisy:
                    (h_id, data, prz, cena, w_id, w_koszt, kategoria, pliki, dodane_przez,
                     zmodyfikowane_przez, data_modyfikacji, notatka, notatka_autor, notatka_data,
                     _robocizna, _podzial, etykieta_rodzaju) = w
                    jest_zbiorcza = w_id is not None
                    # Pozycja wizyty z własną ceną mówi, ile kosztowała ta wymiana; bez niej — koszt
                    # CAŁEJ wizyty z dopiskiem, żeby nie mylił się z kosztem tej pozycji.
                    z_cena_pozycji = jest_zbiorcza and float(cena or 0) > 0
                    koszt_wizyty = f"{utils.formatuj_liczba(float(w_koszt or 0))} {utils.symbol_waluty()}"
                    if jest_zbiorcza and not z_cena_pozycji:
                        k_str = f"{koszt_wizyty} (cała wizyta)"
                    else:
                        k_str = f"{utils.formatuj_liczba(float(cena or 0))} {utils.symbol_waluty()}"
                    sub_tekst = f"Przebieg: {utils.formatuj_dystans(int(prz or 0), 0, j)}  |  {'Wizyta zbiorcza' if jest_zbiorcza else 'Pojedynczy wpis'}"
                    if z_cena_pozycji:
                        sub_tekst += f" za {koszt_wizyty}"
                    if czy_opony and kategoria: sub_tekst += f"\nOpony: {kategoria}"
                    opis_magazynu = utils.opis_zuzycia_z_magazynu(zuzycie_wpisow.get(h_id))

                    tresc_h = [
                        ft.Row([
                            ft.Text(str(data), weight="bold", size=16, expand=True), 
                            ft.Row([
                                utils.wskaznik_zalacznikow(self._page, pliki, "Wpis historii"),
                                ft.Text(k_str, color=utils.KOLOR_STATUS["cost"], weight="bold")
                            ], spacing=6)
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Text(sub_tekst, size=13, color=ft.Colors.ON_SURFACE_VARIANT)
                    ]
                    chip_rodzaju = utils.chip_rodzaju_serwisu(rodzaje.get(h_id))
                    if chip_rodzaju:
                        tresc_h[1] = ft.Row([
                            ft.Text(sub_tekst, size=13, color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                            chip_rodzaju,
                        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START)
                    dopisek_rozbicia = utils.dopisek_rozbicia(rozbicia.get(h_id))
                    if dopisek_rozbicia:
                        tresc_h.append(dopisek_rozbicia)
                    if opis_magazynu:
                        tresc_h.append(ft.Text(opis_magazynu, size=13, color=ft.Colors.TEAL_700))
                    tekst_gwarancji = ""
                    if h_id in gwarancje:
                        tekst_gwarancji = utils.tekst_gwarancji(gwarancje[h_id], j)
                        tresc_h.append(utils.wiersz_gwarancji(gwarancje[h_id], j))
                    if h_id in z_listy:
                        tresc_h.append(utils.wiersz_z_listy_do_zrobienia(z_listy[h_id]))
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

                    def _on_click(e, hid=h_id, wid=w_id, kont=kontener, zal=pliki, nt=notatka):
                        if self.tryb_zaznaczania:
                            if wid:
                                utils.pokaz_komunikat(self._page, "Wpisów z wizyty zbiorczej nie można grupować stąd. Usuń całą wizytę.", utils.KOLOR_STATUS["warning"])
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

                    tekst_szukaj = (f"{data} {sub_tekst} {k_str} {utils.opis_rozbicia_kosztu(rozbicia.get(h_id))} "
                                    f"{opis_magazynu} {tekst_gwarancji} {notatka or ''} {z_listy.get(h_id, '')} "
                                    f"{etykieta_rodzaju if db.rodzaj_serwisu(rodzaje.get(h_id)) else ''}").lower()
                    # Wpisu z wizyty zbiorczej nie usuwa się stąd (całą wizytę) — zostaje mu notatka.
                    karta = utils.gesty_karty(
                        self._page, karta, widok=self,
                        usun=(lambda hid=h_id: usun_wpis_od_razu(hid)) if gesty and not jest_zbiorcza else None,
                        notatka=(lambda hid=h_id: notatka_wpisu(hid)) if gesty else None,
                    )
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
                elementy.append(self.lista_kart)

            # To jest linijka poza blokiem else (już ją masz)
            elementy.append(utils.dol_bezpieczny(10))
            return ft.Column(elementy, spacing=15)


        self.przewijana_tresc.controls = [utils.zbuduj_etapami(
            page, utils.szkielet_ekranu(page, kafle=2, karty=4), tresc, widok=self,
        )]
        super().__init__(
            route=f"/historia/{z_id}",
            padding=0,
            appbar=appbar,
            floating_action_button=fab,
            controls=[self.przewijana_tresc.kontrolka],
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
            utils.pokaz_komunikat_cofnij(self._page, f"Usunięto {db.liczba_z_odmiana(ile, 'wpis', 'wpisy', 'wpisów')} z historii.", wynik)

        utils.potwierdz(self._page, "Usuwanie wpisów", f"Czy na pewno usunąć {db.liczba_z_odmiana(ile, 'element', 'elementy', 'elementów')} z historii?", wykonaj)

class WizytyZbiorczeView(ft.View, utils.ZaznaczanieGrupowe):
    """Ekran „Wizyty w warsztacie”: podsumowanie, filtry, wyszukiwarka i karty wizyt
    w miesiącach (db.lista_wizyt); dotknięcie karty otwiera arkusz szczegółów z akcjami."""

    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state
        self.wspolny_id, _ = sync.czy_udostepniony(self.state.auto_id)
        self.moge_zmieniac = utils.wolno_zmieniac(self.state.auto_id)

        appbar = utils.zbuduj_pasek_z_powrotem(
            page, "Wizyty w warsztacie", "/",
            akcje_dodatkowe=[utils.przycisk_synchronizacji(page, utils.funkcja_szybkiej_synchronizacji(
                page, self.state.auto_id, "/wizyty"))] if self.wspolny_id else None
        )
        fab = (utils.fab_animowany(ft.Icons.ADD, lambda e: utils.przejdz(self._page, "/wizyty/nowa"),
                                   tooltip="Nowa wizyta") if self.moge_zmieniac else None)

        self.tryb_zaznaczania = False
        self.zaznaczone_id = set()
        self.oryginalny_appbar = appbar
        self.karty_ref = {}
        self.wszystkie_karty = []
        self.przewijana_tresc = utils.PrzewijanaTresc()
        self.przewijana_tresc.controls = [utils.zbuduj_etapami(
            page, utils.szkielet_ekranu(page, kafle=2, karty=4, linie=3), self._tresc, widok=self,
        )]
        super().__init__(
            route="/wizyty", padding=0, appbar=appbar, floating_action_button=fab,
            controls=[self.przewijana_tresc.kontrolka],
        )

    # ================= TREŚĆ =================

    def _tresc(self):
        wizyty = db.lista_wizyt(self.state.auto_id)
        if not wizyty:
            return ft.Column([self._pusto()], spacing=15)

        opcje_sort = [
            ("Data", "data", lambda w: (parsuj_date(w["data"]), w["id"])),
            ("Przebieg", "przebieg", lambda w: int(w["przebieg"] or 0)),
            ("Koszt", "koszt", lambda w: float(w["koszt"] or 0)),
        ]
        # Wartości filtrów „Podział” i „Rodzaj” — po nich najłatwiej znaleźć stare wizyty do uzupełnienia.
        for w in wizyty:
            w["podzial"] = utils.etykieta_podzialu(w["rozbicie"])
            w["etykieta_rodzaju"] = db.etykieta_rodzaju_serwisu(w["rodzaj"])
        spis_filtrow = [
            ("rok", "wizyty_rok", "data"),
            ("miesiac", "wizyty_mc", "data"),
            ("kategoria", "wizyty_wyk", "wykonawca", "Warsztat"),
            ("tag", "wizyty_tag", "tagi"),
        ]
        if any(w["podzial"] for w in wizyty):
            spis_filtrow.append(("kategoria", "wizyty_podzial", "podzial", "Podział"))
        if any(db.rodzaj_serwisu(w["rodzaj"]) for w in wizyty):
            spis_filtrow.append(("kategoria", "wizyty_rodzaj", "etykieta_rodzaju", "Rodzaj"))
        # Autor tylko przy pojeździe współdzielonym — jak na osi czasu i pozostałych listach.
        if self.wspolny_id:
            spis_filtrow.append(("autor", "wizyty_autor", "dodane_przez"))
        sort_ui = utils.przycisk_sortowania(self._page, self.state, "wizyty", opcje_sort)
        chipy_filtrow, po_filtrach = utils.pasek_filtrow(self._page, self.state, wizyty, spis_filtrow)
        utils.posortuj_liste(po_filtrach, self.state, "wizyty", opcje_sort)

        self.podsumowanie = utils.PodsumowanieWizyt(self._page, db.podsumowanie_wizyt(po_filtrach))
        self.pole_wyszukiwarki = ft.TextField(
            hint_text="Szukaj (podzespół, warsztat)", prefix_icon=ft.Icons.SEARCH,
            on_change=utils.z_opoznieniem(self._page, self._filtruj), **utils.styl_pola()
        )
        elementy = [
            self.podsumowanie.kontrolka,
            ft.Row(controls=[sort_ui] + chipy_filtrow, scroll=ft.ScrollMode.ADAPTIVE, spacing=8),
            utils.na_cala_szerokosc(self.pole_wyszukiwarki),
        ]
        self.lista_kart = utils.lista_kart()
        # Pod listą: odstęp kolumny (15), miejsce pod FAB-em (80) i dolny margines ekranu (15).
        self.miesiace = utils.GrupyMiesiecy(
            self._page, self.lista_kart, wysokosc_pozycji=200, widok=self, klucz="wizyty", ogon=110,
            odmiana=("wizyta", "wizyty", "wizyt"),
        )
        if po_filtrach:
            self._buduj_karty(po_filtrach)
            self.miesiace.ustaw(self.wszystkie_karty, grupuj=utils.czy_po_dacie(self.state, "wizyty"))
            elementy.append(self.lista_kart)
        else:
            elementy.append(ft.Row([ft.Text("Brak wizyt dla wybranych filtrów.", color=ft.Colors.ON_SURFACE_VARIANT)],
                                   alignment=ft.MainAxisAlignment.CENTER))
        elementy.append(utils.dol_bezpieczny(80))
        return ft.Column(elementy, spacing=15)

    def _buduj_karty(self, wizyty):
        mapa_tagow = db.mapa_kolorow_tagow(self.state.auto_id)
        j = utils.jednostka_dystansu()  # raz na całą listę
        # Telefon i adres z rejestru — raz na listę, po kluczu nazwy (wizyta trzyma warsztat jako tekst).
        kontakty = {db.klucz_nazwy(n): (t, a) for _i, n, t, a, _nt in db.pobierz_warsztaty(self.state.auto_id)}
        for w in wizyty:
            kontakt = kontakty.get(db.klucz_nazwy(w["warsztat"])) if w["warsztat"] else None
            karta, kontener = utils.karta_wizyty(
                self._page, w, j, kontakt, self.state.auto_id, mapa_tagow, bool(self.wspolny_id),
                on_notatka=lambda wid=w["id"]: self._notatka(wid),
            )
            self.karty_ref[w["id"]] = kontener
            self.podepnij_zdarzenia_grupowe(kontener, w["id"], lambda wiz=w, kon=kontakt: self._szczegoly(wiz, kon))
            karta = utils.gesty_karty(
                self._page, karta, widok=self,
                usun=(lambda wid=w["id"]: self._usun([wid])) if self.moge_zmieniac else None,
                notatka=(lambda wid=w["id"]: self._notatka(wid)) if self.moge_zmieniac else None,
            )
            self.wszystkie_karty.append({"karta": karta, "szukaj": utils.tekst_do_szukania(w),
                                         "data": w["data"], "kwota": w["koszt"], "wizyta": w})

    def _filtruj(self, e):
        """Wyszukiwarka: karty, nagłówki miesięcy i podsumowanie liczą tylko to, co widać."""
        zapytanie = (e.control.value or "").lower().strip()
        widoczne = [k for k in self.wszystkie_karty if zapytanie in k["szukaj"]]
        self.miesiace.ustaw(widoczne, grupuj=utils.czy_po_dacie(self.state, "wizyty"))
        self.podsumowanie.ustaw(db.podsumowanie_wizyt([k["wizyta"] for k in widoczne]))
        self.update()

    def _pusto(self):
        opis = ("Zapisz tu przegląd albo naprawę: warsztat, koszt z robocizną i częściami, wymienione "
                "podzespoły, gwarancję i zdjęcie rachunku.")
        if not self.moge_zmieniac:
            return ft.Container(padding=30, content=ft.Column([
                utils.rysunek_pustego_stanu(ft.Icons.HOME_REPAIR_SERVICE),
                ft.Text("Nie ma jeszcze wizyt", size=utils.FS["heading"], weight="bold"),
                ft.Text(opis, size=utils.FS["body"], color=ft.Colors.ON_SURFACE_VARIANT,
                        text_align=ft.TextAlign.CENTER),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10))
        return utils.ekran_braku_danych(
            ikona=ft.Icons.HOME_REPAIR_SERVICE, tytul="Nie ma jeszcze wizyt", opis=opis,
            tekst_przycisku="Dodaj pierwszą wizytę", on_click=lambda e: utils.przejdz(self._page, "/wizyty/nowa"),
        )

    # ================= AKCJE =================

    def _szczegoly(self, wizyta, kontakt):
        """Arkusz wizyty: szczegóły nad akcjami (utils.szczegoly_wizyty)."""
        wid = wizyta["id"]
        odswiez = lambda: utils.przejdz(self._page, "/wizyty")
        pozycje = [
            {"ikona": ft.Icons.EDIT, "tekst": "Edytuj wizytę",
             "akcja": lambda: utils.przejdz(self._page, f"/wizyty/edytuj/{wid}")},
            {"ikona": ft.Icons.CONTENT_COPY, "tekst": "Duplikuj wizytę", "akcja": lambda: self._duplikuj(wid)},
            *utils.akcje_kontaktu_wizyty(self._page, self.state, wizyta, kontakt),
            *utils.pozycje_menu_zalacznikow(self._page, "wizyty", wid, wizyta["pliki"], "Wizyta", odswiez),
            utils.pozycja_menu_notatki(self._page, "wizyty", wid, wizyta["notatki"], odswiez, "Notatka do wizyty"),
        ]
        # Droga powrotna do „Zamień na wizytę” z listy Do zrobienia: część bywa zamówiona
        # przy okazji wizyty, a montowana dopiero później.
        if wizyta["pozycje"]:
            pozycje.append({"ikona": ft.Icons.ASSIGNMENT_RETURN, "tekst": "Zwróć pozycję na listę Do zrobienia",
                            "akcja": lambda: self._zwroc_pozycje_na_liste(wid)})
        pozycje.append({
            "ikona": ft.Icons.DELETE, "tekst": "Usuń wizytę", "kolor": utils.KOLOR_STATUS["destructive"],
            "akcja": lambda: utils.potwierdz(
                self._page, "Usunąć wizytę?",
                "Wizyta trafi do kosza razem z pozycjami i plikami, a części z magazynu wrócą na półkę.",
                lambda: self._usun([wid])),
        })
        pozycje = utils.odsiej_akcje(self.state.auto_id, pozycje, "wizyty", wid)
        utils.pokaz_menu_kontekstowe(
            self._page, utils.tytul_wizyty(wizyta), pozycje,
            tresc=utils.szczegoly_wizyty(self._page, wizyta, utils.jednostka_dystansu(), self.state.auto_id,
                                         bool(self.wspolny_id)),
        )

    def _notatka(self, wizyta_id):
        utils.szybka_notatka(self._page, "wizyty", wizyta_id, lambda: utils.przejdz(self._page, "/wizyty"),
                             "Notatka do wizyty")

    def _duplikuj(self, wizyta_id):
        self.state.duplikuj_zrodlo_wizyta = wizyta_id
        utils.przejdz(self._page, "/wizyty/nowa")

    def _usun(self, ids):
        """Wizyty do kosza wpisów; podzespoły przeliczają się po usunięciu i po „Cofnij”."""
        wynik = db.usun_wizyty_z_cofnieciem(ids)
        if wynik:
            oryginalne_cofnij = wynik["cofnij"]

            def nowe_cofnij():
                oryginalne_cofnij()
                db.przelicz_wszystkie_zadania(self.state.auto_id)
            wynik["cofnij"] = nowe_cofnij
        db.przelicz_wszystkie_zadania(self.state.auto_id)
        utils.przejdz(self._page, "/wizyty")
        ile = db.liczba_z_odmiana(len(ids), "wizytę", "wizyty", "wizyt") if len(ids) > 1 else "wizytę"
        utils.pokaz_komunikat_cofnij(self._page, f"Usunięto {ile} w warsztacie.", wynik)

    def potwierdz_grupowe_usuwanie(self, e):
        ids = list(self.zaznaczone_id)

        def wykonaj():
            self.zakoncz_zaznaczanie()
            self._usun(ids)
        utils.potwierdz(self._page, "Usuwanie wizyt",
                        f"Czy na pewno usunąć {db.liczba_z_odmiana(len(ids), 'wybraną wizytę', 'wybrane wizyty', 'wybranych wizyt')}?",
                        wykonaj)

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
                ft.Column([utils.pole_wyboru(c) for c in checkboxy], tight=True, spacing=0),
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
