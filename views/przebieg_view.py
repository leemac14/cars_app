import flet as ft
from datetime import datetime
import db
import sync
import utils


class OdczytyPrzebieguView(ft.View, utils.ZaznaczanieGrupowe):
    """Historia stanu licznika — WSZYSTKIE znane przebiegi, nie tylko wpisane
    ręcznie. Tankowanie, wizyta i wpis serwisowy też niosą stan licznika, więc
    pokazywanie samych własnych odczytów dawało obraz uboższy niż dane, które
    aplikacja już ma. Każdy wpis mówi, skąd pochodzi; edytować da się stąd
    wyłącznie własne odczyty, bo reszta to odbicie prawdziwego wpisu kosztowego
    i poprawianie go „tutaj” rozjeżdżałoby dane."""

    # Tabela z notatką dla danego źródła — notatkę da się dopisać do każdego
    # wpisu, niezależnie od tego, czy jego przebieg edytuje się stąd.
    TABELE_NOTATKI = {
        "odczyt": "odczyty_przebiegu",
        "tankowanie": "tankowania",
        "wizyta": "wizyty",
        "serwis": "historia",
    }

    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state

        wspolny_id, _ = sync.czy_udostepniony(state.auto_id)
        appbar = utils.zbuduj_pasek_z_powrotem(
            page, "Historia stanu licznika", "/", ikona=ft.Icons.SHOW_CHART,
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
        wpisy = db.pobierz_pelna_historie_przebiegu(self.state.auto_id)

        if not wpisy:
            elementy.append(utils.ekran_braku_danych(
                ikona=ft.Icons.SPEED,
                tytul="Brak zapisanych przebiegów",
                opis="Tu trafia każdy stan licznika, jaki zna aplikacja — z tankowań, wizyt "
                     "i wpisów serwisowych, a także szybkie odczyty z deski rozdzielczej.",
                tekst_przycisku="Dodaj odczyt",
                on_click=lambda e: self._dialog_odczytu()
            ))
        else:
            podsumowanie = db.podsumowanie_historii_przebiegu(self.state.auto_id, wpisy)
            elementy.append(self._karta_podsumowania(podsumowanie))

            wykres = utils.wykres_przebiegu(self._page, wpisy)
            if wykres:
                elementy.append(utils.karta_analizy(
                    self._page, "Licznik w czasie", ft.Icons.SHOW_CHART, [wykres],
                ))

            opcje_sort = [
                ("Data", "data", lambda x: (x["data_obj"], x["przebieg"])),
                ("Przebieg", "przebieg", lambda x: x["przebieg"]),
                ("Źródło", "zrodlo", lambda x: (x["etykieta_zrodla"], x["data_obj"])),
            ]

            sort_ui = utils.przycisk_sortowania(self._page, self.state, "odczyty_przebiegu", opcje_sort)
            filtr_zrodlo_ui = utils.przycisk_filtrowania_kategoria(
                self._page, self.state, "przebieg_zrodlo", wpisy, "etykieta_zrodla", "Źródło")
            filtr_rok_ui = utils.przycisk_filtrowania_rok(self._page, self.state, "odczyty_rok", wpisy, "data")
            filtr_mc_ui = utils.przycisk_filtrowania_miesiac(self._page, self.state, "odczyty_mc", wpisy, "data")

            elementy.append(ft.Row([sort_ui, filtr_zrodlo_ui, filtr_rok_ui, filtr_mc_ui],
                                   spacing=6, scroll=ft.ScrollMode.HIDDEN))

            def filtruj_odczyty(e):
                zapytanie = e.control.value.lower().strip()
                self.lista_kart.controls.clear()
                for k in self.wszystkie_karty:
                    if zapytanie in k["szukaj"]:
                        self.lista_kart.controls.append(k["karta"])
                self.update()

            elementy.append(
                ft.TextField(
                    hint_text="Szukaj (data, przebieg, źródło, notatka)...",
                    prefix_icon=ft.Icons.SEARCH,
                    on_change=utils.z_opoznieniem(self._page, filtruj_odczyty),
                    **utils.styl_pola()
                )
            )

            self.lista_kart = ft.ListView(spacing=12, padding=0, height=utils.wysokosc_listy(self._page), auto_scroll=False)
            self.wszystkie_karty = []
            self.uzyj_wirtualizacji = True

            po_filtrach = utils.filtruj_po_kategorii(wpisy, self.state, "przebieg_zrodlo", "etykieta_zrodla")
            po_filtrach = utils.filtruj_po_roku(po_filtrach, self.state, "odczyty_rok", "data")
            po_filtrach = utils.filtruj_po_miesiacu(po_filtrach, self.state, "odczyty_mc", "data")
            utils.posortuj_liste(po_filtrach, self.state, "odczyty_przebiegu", opcje_sort)

            if not po_filtrach:
                elementy.append(ft.Row([ft.Text("Brak wyników dla tych filtrów.", color=ft.Colors.ON_SURFACE_VARIANT)],
                                       alignment=ft.MainAxisAlignment.CENTER))
            else:
                for w in po_filtrach:
                    karta = self._karta_wpisu(w, wspolny_id)
                    self.wszystkie_karty.append(karta)
                    self.lista_kart.controls.append(karta["karta"])

            elementy.append(self.lista_kart)

        elementy.append(utils.dol_bezpieczny(10))

        super().__init__(
            route="/przebieg",
            padding=15,
            appbar=appbar, floating_action_button=fab,
            controls=[utils.z_odswiezaniem(page, elementy)]
        )

    # ================= PODSUMOWANIE =================

    def _karta_podsumowania(self, p):
        if not p:
            return ft.Container()

        chipy = [
            utils.odznaka_zrodla_przebiegu(zrodlo, f"{db.ZRODLA_PRZEBIEGU[zrodlo]}: {ile}")
            for zrodlo, ile in sorted(p["wg_zrodla"].items(), key=lambda kv: -kv[1])
        ]

        wiersze = [
            ft.Row([
                ft.Column([
                    ft.Text("Zapisanych stanów licznika", size=utils.FS["caption"],
                            color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Text(str(p["liczba"]), size=utils.FS["display"], weight="bold"),
                ], spacing=0, expand=True),
                ft.Column([
                    ft.Text("Objęty dystans", size=utils.FS["caption"],
                            color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Text(f"{utils.formatuj_liczba(p['dystans'], 0)} km",
                            size=utils.FS["display"], weight="bold"),
                ], spacing=0, horizontal_alignment=ft.CrossAxisAlignment.END),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Row(chipy, spacing=6, wrap=True),
        ]

        opis = []
        if p["srednia_dzienna"]:
            opis.append(f"średnio {utils.formatuj_liczba(p['srednia_dzienna'], 1)} km/dzień")
        if p["dni"]:
            opis.append(f"{p['dni']} dni historii")
        opis.append(
            "ostatni wpis dzisiaj" if p["dni_od_ostatniego"] == 0
            else f"ostatni wpis {p['dni_od_ostatniego']} dni temu"
        )
        wiersze.append(ft.Text(" • ".join(opis), size=utils.FS["caption"],
                               color=ft.Colors.ON_SURFACE_VARIANT))

        if p["anomalie"]:
            wiersze.append(ft.Container(
                padding=ft.Padding(10, 8, 10, 8), border_radius=utils.RADIUS["sm"],
                bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.RED_700),
                content=ft.Row([
                    ft.Icon(ft.Icons.WARNING_AMBER, size=16, color=ft.Colors.RED_700),
                    ft.Text(
                        f"{p['anomalie']} "
                        + ("nieścisłość" if p["anomalie"] == 1 else "nieścisłości")
                        + " w historii licznika — oznaczone kolorem niżej.",
                        size=utils.FS["caption"], color=ft.Colors.RED_700, expand=True),
                ], spacing=6),
            ))

        return ft.Container(
            padding=utils.SPACING["lg"], border_radius=utils.RADIUS["lg"],
            **utils.powierzchnia_karty(self._page, "md"),
            content=ft.Column(wiersze, spacing=utils.SPACING["sm"]),
        )

    # ================= KARTA WPISU =================

    def _karta_wpisu(self, w, wspolny_id):
        kolor_zrodla = utils.KOLORY_ZRODEL_PRZEBIEGU.get(w["zrodlo"], ft.Colors.ON_SURFACE_VARIANT)
        anomalia = w.get("anomalia")

        tresc = [
            ft.Row([
                ft.Text(str(w["data"]), weight="bold", size=16),
                ft.Text(f"{utils.formatuj_liczba(w['przebieg'], 0)} km", weight="bold", size=16,
                        color=ft.Colors.PRIMARY),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Row([
                utils.odznaka_zrodla_przebiegu(w["zrodlo"], w["etykieta_zrodla"], w.get("podzrodlo")),
                ft.Text(w["opis"], size=utils.FS["body"], color=ft.Colors.ON_SURFACE_VARIANT,
                        expand=True, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
            ], spacing=6),
        ]

        # Odcinek od poprzedniego wpisu — dopiero to zamienia listę liczb
        # w opowieść o tym, jak auto jeździło między zdarzeniami.
        if anomalia == "cofka":
            tresc.append(ft.Row([
                ft.Icon(ft.Icons.WARNING, size=13, color=ft.Colors.RED_700),
                ft.Text(f"Licznik niższy o {utils.formatuj_liczba(abs(w['dystans']), 0)} km niż "
                        f"w poprzednim wpisie — sprawdź datę albo przebieg",
                        size=12, color=ft.Colors.RED_700, expand=True),
            ], spacing=4))
        elif anomalia == "skok":
            tresc.append(ft.Row([
                ft.Icon(ft.Icons.WARNING, size=13, color=ft.Colors.ORANGE_700),
                ft.Text(f"{utils.formatuj_liczba(w['dystans'], 0)} km w {w['dni']} dni "
                        f"({utils.formatuj_liczba(w['srednia_dzienna'], 0)} km/dzień) — "
                        f"nietypowo dużo jak na to auto",
                        size=12, color=ft.Colors.ORANGE_700, expand=True),
            ], spacing=4))
        elif w.get("dystans") is not None:
            czesci = [f"{utils.formatuj_liczba(w['dystans'], 0)} km od poprzedniego"]
            if w.get("dni"):
                czesci.append(f"{w['dni']} dni")
            if w.get("srednia_dzienna"):
                czesci.append(f"{utils.formatuj_liczba(w['srednia_dzienna'], 1)} km/dzień")
            tresc.append(ft.Row([
                ft.Icon(ft.Icons.ARROW_UPWARD, size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Text(" • ".join(czesci), size=12, color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
            ], spacing=4))

        tresc.append(utils.podglad_notatki(
            self._page, w.get("notatka"), w.get("notatka_autor"), w.get("notatka_data"),
            f"Notatka • {w['etykieta_zrodla'].lower()}",
            on_edytuj=lambda tab=self.TABELE_NOTATKI[w["zrodlo"]], rid=w["id"]: utils.szybka_notatka(
                self._page, tab, rid, lambda: utils.przejdz(self._page, "/przebieg"), "Notatka"
            ),
            pokaz_podpis=bool(wspolny_id),
        ))

        # Pasek po lewej niesie od razu dwie informacje: kolor źródła, a przy
        # nieścisłości — ostrzeżenie. Korzystamy z gotowej karta_listy (ta sama,
        # co w historii serwisu), żeby karta wyglądała identycznie jak wszędzie.
        kolor_paska = (ft.Colors.RED_700 if anomalia == "cofka"
                       else ft.Colors.ORANGE_700 if anomalia == "skok" else kolor_zrodla)
        karta, kontener = utils.karta_listy(tresc, kolor_paska=kolor_paska, page=self._page)

        if w["edytowalny"]:
            # Tylko własne odczyty wchodzą w tryb zaznaczania — grupowe usuwanie
            # kasuje z odczyty_przebiegu, a tankowania nie wolno stąd ruszyć.
            self.karty_ref[w["id"]] = kontener
            self.podepnij_zdarzenia_grupowe(
                kontener, w["id"], lambda wpis=w: self._menu_wpisu(wpis), "odczyty_przebiegu")
        else:
            kontener.on_click = lambda e, wpis=w: self._menu_wpisu(wpis)

        tekst_szukaj = (f"{w['data']} {w['przebieg']} {w['etykieta_zrodla']} {w['opis']} "
                        f"{w.get('notatka') or ''}").lower()
        return {"karta": karta, "szukaj": tekst_szukaj}

    # ================= MENU =================

    def _menu_wpisu(self, w):
        odswiez = lambda: utils.przejdz(self._page, "/przebieg")
        pozycje = []

        if w["edytowalny"]:
            pozycje.append({"ikona": ft.Icons.EDIT, "tekst": "Edytuj odczyt",
                            "akcja": lambda: self._dialog_odczytu(w)})
        else:
            pozycje.append({
                "ikona": ft.Icons.OPEN_IN_NEW,
                "tekst": f"Otwórz wpis ({w['etykieta_zrodla'].lower()})",
                "akcja": lambda: utils.przejdz(self._page, w["trasa"]),
            })

        pozycje.append(utils.pozycja_menu_notatki(
            self._page, self.TABELE_NOTATKI[w["zrodlo"]], w["id"], w.get("notatka"), odswiez, "Notatka"))

        if w["edytowalny"]:
            def usun():
                def wykonaj():
                    wynik = db.usun_z_cofnieciem("odczyty_przebiegu", w["id"])
                    utils.przejdz(self._page, "/przebieg")
                    utils.pokaz_komunikat_cofnij(self._page, "Usunięto odczyt.", wynik)
                utils.potwierdz(self._page, "Usunąć?", "Czy na pewno usunąć ten odczyt przebiegu?", wykonaj)

            pozycje.append({"ikona": ft.Icons.DELETE, "tekst": "Usuń odczyt",
                            "akcja": usun, "kolor": ft.Colors.RED})

        podtytul = f"{w['data']} • {utils.formatuj_liczba(w['przebieg'], 0)} km"
        utils.pokaz_menu_kontekstowe(self._page, f"{w['etykieta_zrodla']}: {podtytul}", pozycje)

    def potwierdz_grupowe_usuwanie(self, e):
        ile = len(self.zaznaczone_id)
        def wykonaj():
            wynik = db.usun_wiele_z_cofnieciem(self.tabela_cel, list(self.zaznaczone_id))
            self.zakoncz_zaznaczanie()
            utils.przejdz(self._page, "/przebieg")
            utils.pokaz_komunikat_cofnij(self._page, f"Usunięto {ile} odczytów.", wynik)
        utils.potwierdz(self._page, "Usuwanie",
                        f"Czy na pewno usunąć {ile} zaznaczonych odczytów?", wykonaj)

    # ================= FORMULARZ ODCZYTU =================

    def _dialog_odczytu(self, odczyt=None):
        """odczyt: None (nowy) albo słownik wpisu z pobierz_pelna_historie_przebiegu.
        Otwierany wyłącznie dla WŁASNYCH odczytów — pozostałe wpisy mają swoje
        formularze i to tam się je poprawia."""
        edycja = odczyt is not None
        domyslna_data = odczyt["data"] if edycja else datetime.now().strftime("%d.%m.%Y")
        domyslny_przebieg = (str(odczyt["przebieg"]) if edycja
                             else str(db.pobierz_aktualny_przebieg(self.state.auto_id) or ""))
        notatka_bazowa = str((odczyt.get("notatka") if edycja else "") or "")

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

            wyklucz = odczyt["id"] if edycja else None
            if utils.sprawdz_podejrzany_przebieg(self._page, e_przebieg, self.state.auto_id, nowy,
                                                 wyklucz_id=wyklucz, tabela="odczyty_przebiegu",
                                                 nowa_data_str=e_data.value):
                return

            utils.zamknij_dialog(self._page, dlg)
            if edycja:
                db.aktualizuj_odczyt_przebiegu(odczyt["id"], nowy, e_data.value)
                utils.zapisz_notatke_z_formularza("odczyty_przebiegu", odczyt["id"],
                                                  e_notatka.value, notatka_bazowa)
                utils.pokaz_komunikat(self._page, "Zapisano zmiany!")
            else:
                nadpisano = db.dodaj_odczyt_przebiegu(self.state.auto_id, nowy, e_data.value,
                                                      e_notatka.value, zrodlo="reczny")
                utils.pokaz_komunikat(self._page, "Zaktualizowano odczyt z tego dnia!" if nadpisano
                                      else "Dodano odczyt przebiegu!")
            utils.wypchnij_w_tle(self._page, self.state.auto_id, "odczyt przebiegu")
            utils.przejdz(self._page, "/przebieg")

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([ft.Icon(ft.Icons.SPEED, color=ft.Colors.PRIMARY),
                          ft.Text("Edycja odczytu" if edycja else "Nowy odczyt", weight="bold")], spacing=8),
            content=ft.Column([
                e_data,
                e_przebieg,
                e_notatka,
                ft.Text(
                    "Jeśli dla wybranej daty istnieje już odczyt, zostanie zaktualizowany. "
                    "Przebiegi z tankowań, wizyt i serwisu pojawiają się w historii same.",
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
