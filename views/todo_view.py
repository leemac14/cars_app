import flet as ft
from datetime import datetime
import db
import utils


class DoZrobieniaView(ft.View, utils.ZaznaczanieGrupowe):
    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state

        appbar = utils.zbuduj_pasek_z_powrotem(page, "📝 Do zrobienia", "/")
        fab = utils.fab_animowany(ft.Icons.ADD, lambda e: utils.przejdz(self._page, "/do-zrobienia/nowe"))

        # --- ZMIENNE DLA GRUPOWEGO ZAZNACZANIA / USUWANIA ---
        self.tryb_zaznaczania = False
        self.zaznaczone_id = set()
        self.oryginalny_appbar = appbar
        self.karty_ref = {}
        self.uzyj_wirtualizacji = False
        # ------------------------------------------------------

        elementy = []

        with db.polacz_baze() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT d.id, d.tytul, d.opis, d.priorytet, d.szacowany_koszt, d.termin, "
                "d.zadanie_id, d.wykonane, z.nazwa "
                "FROM do_zrobienia d LEFT JOIN zadania z ON d.zadanie_id = z.id "
                "WHERE d.auto_id=?", (self.state.auto_id,)
            )
            pozycje = c.fetchall()

        if not pozycje:
            elementy.append(utils.ekran_braku_danych(
                ikona=ft.Icons.CHECKLIST_RTL,
                tytul="Lista jest pusta",
                opis="Dodawaj tu wszystko, co planujesz zrobić przy aucie. Gdy przyjdzie czas, zamienisz to jednym kliknięciem w Wizytę w warsztacie.",
                tekst_przycisku="Dodaj pozycję",
                on_click=lambda e: utils.przejdz(self._page, "/do-zrobienia/nowe")
            ))
        else:
            # Doklejamy syntetyczne pole statusu, żeby użyć gotowego mechanizmu filtrowania po kategorii
            dane = [tuple(p) + ("Zakończone" if p[7] else "Aktywne",) for p in pozycje]

            opcje_sort = [
                ("Priorytet", "priorytet", lambda x: db.KOLEJNOSC_PRIORYTETU.get(x[3], 9)),
                ("Termin", "termin", lambda x: utils.parsuj_date(x[5])),
                ("Nazwa", "nazwa", lambda x: str(x[1]).lower()),
                ("Koszt", "koszt", lambda x: float(x[4] or 0)),
            ]

            sort_ui = utils.przycisk_sortowania(self._page, self.state, "do_zrobienia", opcje_sort)
            filtr_status_ui = utils.przycisk_filtrowania_kategoria(self._page, self.state, "do_zrobienia_status", dane, 9, "Status")
            filtr_priorytet_ui = utils.przycisk_filtrowania_kategoria(self._page, self.state, "do_zrobienia_priorytet", dane, 3, "Priorytet")

            elementy.append(ft.Row([sort_ui, filtr_status_ui, filtr_priorytet_ui], spacing=6, scroll=ft.ScrollMode.HIDDEN))

            def filtruj_pozycje(e):
                zapytanie = e.control.value.lower().strip()
                self.lista_kart.controls.clear()
                for k in self.wszystkie_karty:
                    if zapytanie in k["szukaj"]:
                        self.lista_kart.controls.append(k["karta"])
                self.update()

            self.pole_wyszukiwarki = ft.TextField(
                hint_text="Szukaj (tytuł, opis, podzespół)...",
                prefix_icon=ft.Icons.SEARCH,
                on_change=utils.z_opoznieniem(self._page, filtruj_pozycje),
                **utils.styl_pola()
            )
            elementy.append(self.pole_wyszukiwarki)

            self.lista_kart = ft.ListView(spacing=15, padding=0, height=utils.wysokosc_listy(self._page), auto_scroll=False)
            self.wszystkie_karty = []
            self.uzyj_wirtualizacji = True

            po_filtrach = utils.filtruj_po_kategorii(dane, self.state, "do_zrobienia_status", 9)
            po_filtrach = utils.filtruj_po_kategorii(po_filtrach, self.state, "do_zrobienia_priorytet", 3)
            utils.posortuj_liste(po_filtrach, self.state, "do_zrobienia", opcje_sort)

            if not po_filtrach:
                elementy.append(ft.Row([ft.Text("Brak wyników dla tych filtrów.", color=ft.Colors.ON_SURFACE_VARIANT)], alignment=ft.MainAxisAlignment.CENTER))
            else:
                for w in po_filtrach:
                    karta = self._karta_pozycji(w)
                    _, tytul, opis, priorytet, koszt, termin, _, _, zadanie_nazwa = w[:9]
                    tekst_szukaj = f"{tytul} {opis} {priorytet} {termin} {zadanie_nazwa}".lower()
                    self.wszystkie_karty.append({"karta": karta, "szukaj": tekst_szukaj})
                    self.lista_kart.controls.append(karta)

            elementy.append(self.lista_kart)

        elementy.append(utils.dol_bezpieczny(10))

        super().__init__(
            route="/do-zrobienia",
            padding=15,
            appbar=appbar,
            floating_action_button=fab,
            controls=[utils.z_odswiezaniem(page, elementy)]
        )

    # --- KARTA POJEDYNCZEJ POZYCJI ---
    def _karta_pozycji(self, w):
        p_id, tytul, opis, priorytet, koszt, termin, zadanie_id, wykonane, zadanie_nazwa = w[:9]
        priorytet = priorytet or "Średni"
        zrobione = bool(wykonane)

        kolor_priorytetu = {
            "Wysoki": ft.Colors.RED_700,
            "Średni": ft.Colors.ORANGE_700,
            "Niski": ft.Colors.BLUE_700,
        }.get(priorytet, ft.Colors.ON_SURFACE_VARIANT)

        chip_priorytet = ft.Container(
            padding=8, border_radius=20,
            bgcolor=ft.Colors.with_opacity(0.15, kolor_priorytetu),
            content=ft.Text(str(priorytet), size=11, weight="bold", color=kolor_priorytetu)
        )

        kolor_term, tekst_term = utils.kolor_i_tekst_terminu(termin) if termin else (None, None)

        def przelacz(e, pid=p_id):
            db.przelacz_wykonane_do_zrobienia(pid, e.control.value)
            utils.przejdz(self._page, "/do-zrobienia")

        chk = ft.Checkbox(value=zrobione, on_change=przelacz, active_color=ft.Colors.GREEN_700, tooltip="Oznacz jako zrobione")

        podtytul_bits = []
        if opis:
            podtytul_bits.append(str(opis))
        if zadanie_nazwa:
            podtytul_bits.append(f"🔗 {zadanie_nazwa}")

        stopka_bits = []
        if koszt:
            stopka_bits.append(ft.Text(f"~{utils.formatuj_liczba(float(koszt))} {utils.symbol_waluty()}", size=12, weight="bold", color=ft.Colors.ON_SURFACE_VARIANT))
        if tekst_term:
            stopka_bits.append(ft.Text(tekst_term, size=12, weight="bold", color=kolor_term))

        tresc_kolumny = [
            ft.Row([
                ft.Text(str(tytul), size=16, weight="bold", expand=True,
                        color=ft.Colors.ON_SURFACE_VARIANT if zrobione else ft.Colors.ON_SURFACE),
                chip_priorytet
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER)
        ]
        if podtytul_bits:
            tresc_kolumny.append(ft.Text("  •  ".join(podtytul_bits), size=13, color=ft.Colors.ON_SURFACE_VARIANT))
        if stopka_bits:
            tresc_kolumny.append(ft.Row(stopka_bits, spacing=12))

        karta, kontener = utils.karta_listy(
            ft.Row([
                chk,
                ft.Column(tresc_kolumny, spacing=4, expand=True)
            ], vertical_alignment=ft.CrossAxisAlignment.START, spacing=10),
            kolor_paska=kolor_priorytetu,
            page=self._page,
        )
        karta.content.opacity = 0.55 if zrobione else 1.0

        self.karty_ref[p_id] = kontener

        def _on_click(e, pid=p_id, tyt=tytul, zr=zrobione):
            if self.tryb_zaznaczania:
                self.zaznacz_odznacz(pid, self.karty_ref[pid])
            else:
                self._otworz_menu(pid, tyt, zr)

        def _on_long_press(e, pid=p_id):
            if not self.tryb_zaznaczania:
                self.tryb_zaznaczania = True
                self.zaznacz_odznacz(pid, self.karty_ref[pid])

        kontener.on_click = _on_click
        kontener.on_long_press = _on_long_press

        return karta

    # --- MENU POJEDYNCZEJ POZYCJI (BOTTOM SHEET) ---
    def _otworz_menu(self, p_id, tytul, zrobione):
        def usun_pozycje():
            def wykonaj():
                wynik = db.usun_z_cofnieciem("do_zrobienia", p_id)
                utils.przejdz(self._page, "/do-zrobienia")
                utils.pokaz_komunikat_cofnij(self._page, "Usunięto pozycję.", wynik)
            utils.potwierdz(self._page, "Usunąć?", "Czy na pewno chcesz usunąć tę pozycję z listy?", wykonaj)

        def przelacz_status():
            db.przelacz_wykonane_do_zrobienia(p_id, not zrobione)
            utils.przejdz(self._page, "/do-zrobienia")
            utils.pokaz_komunikat(self._page, "Cofnięto oznaczenie." if zrobione else "Oznaczono jako zrobione!")

        def poprosz_o_wizyte():
            self._zapytaj_i_utworz_wizyte(
                [p_id], 
                "Utworzyć wizytę?", 
                f"Z pozycji „{tytul}” powstanie nowa Wizyta w warsztacie, gotowa do uzupełnienia szczegółów."
            )

        utils.pokaz_menu_kontekstowe(self._page, str(tytul), [
            {"ikona": ft.Icons.BUILD_CIRCLE, "tekst": "Utwórz wizytę w warsztacie", "akcja": poprosz_o_wizyte, "kolor": ft.Colors.PRIMARY},
            {"ikona": ft.Icons.UNDO if zrobione else ft.Icons.CHECK_CIRCLE, "tekst": "Cofnij ukończenie" if zrobione else "Oznacz jako zrobione", "akcja": przelacz_status, "kolor": ft.Colors.GREEN},
            {"ikona": ft.Icons.EDIT, "tekst": "Edytuj", "akcja": lambda: utils.przejdz(self._page, f"/do-zrobienia/edytuj/{p_id}")},
            {"ikona": ft.Icons.DELETE, "tekst": "Usuń pozycję", "akcja": usun_pozycje, "kolor": ft.Colors.RED}
        ])

    def potwierdz_grupowe_usuwanie(self, e):
        ile = len(self.zaznaczone_id)
        def wykonaj():
            wynik = db.usun_wiele_z_cofnieciem("do_zrobienia", list(self.zaznaczone_id))
            self.zakoncz_zaznaczanie()
            utils.przejdz(self._page, "/do-zrobienia")
            utils.pokaz_komunikat_cofnij(self._page, f"Usunięto {ile} pozycji.", wynik)
        utils.potwierdz(self._page, "Usuwanie", f"Czy na pewno chcesz usunąć {ile} zaznaczonych pozycji?", wykonaj)

    def _zapytaj_i_utworz_wizyte(self, ids, tytul_dialogu, tresc_dialogu):
        chk_podzespoly = ft.Checkbox(label="Zapisz luźne pozycje jako stałe podzespoły", value=False)
        
        def wykonaj(e):
            utils.zamknij_dialog(self._page, dlg)
            self.zakoncz_zaznaczanie()
            nowa_id, duplikaty, wynik_cofniecia = db.utworz_wizyte_z_do_zrobienia(self.state.auto_id, ids, chk_podzespoly.value)
            if nowa_id:
                utils.przejdz(self._page, f"/wizyty/edytuj/{nowa_id}")
                if duplikaty:
                    nazwy_dupl = ", ".join(f"„{d}”" for d in duplikaty)
                    komunikat = f"Utworzono wizytę! Podzespół {nazwy_dupl} już istnieje w bazie – dopisano do niego nową historię." if len(duplikaty) == 1 else f"Utworzono wizytę! Podzespoły ({nazwy_dupl}) już istnieją w bazie – dopisano do nich nową historię."
                else:
                    komunikat = "Utworzono wizytę w warsztacie! Sprawdź i zapisz szczegóły."
                utils.pokaz_komunikat_cofnij(self._page, komunikat, wynik_cofniecia)
                
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(tytul_dialogu, weight="bold"),
            content=ft.Column([
                ft.Text(tresc_dialogu),
                ft.Container(height=5),
                chk_podzespoly,
                ft.Text(
                    "Pozycje bez podzespołu (przy odznaczonej opcji powyżej) trafią do wizyty "
                    "wyłącznie jako łączny koszt i notatka — nie pojawią się jako osobne części wizyty.",
                    size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
                )
            ], tight=True),
            actions=[
                ft.TextButton("Anuluj", on_click=lambda e: utils.zamknij_dialog(self._page, dlg)),
                ft.TextButton("Utwórz", style=ft.ButtonStyle(color=ft.Colors.PRIMARY), on_click=wykonaj)
            ],
            actions_alignment=ft.MainAxisAlignment.END
        )
        utils.otworz_dialog(self._page, dlg)

    def utworz_wizyte_z_zaznaczonych(self, e):
        ids = list(self.zaznaczone_id)
        ile = len(ids)
        self._zapytaj_i_utworz_wizyte(
            ids, 
            "Utworzyć wizytę?", 
            f"Z {ile} zaznaczonych pozycji powstanie nowa Wizyta w warsztacie, a te pozycje znikną z listy Do zrobienia. Kontynuować?"
        )

    def aktualizuj_appbar_zaznaczania(self, dodatkowe_akcje=None):
        extra = [ft.IconButton(ft.Icons.BUILD_CIRCLE, tooltip="Utwórz wizytę z zaznaczonych", on_click=self.utworz_wizyte_z_zaznaczonych)]
        super().aktualizuj_appbar_zaznaczania(dodatkowe_akcje=extra)

class FormularzDoZrobieniaView(ft.View):
    def __init__(self, page: ft.Page, state, pozycja_id=None):
        self._page = page
        self.state = state
        self.pozycja_id = pozycja_id

        tyt_val, opis_val, priorytet_val = "", "", "Średni"
        koszt_val, termin_val, zadanie_val = "", "", ""

        if pozycja_id:
            with db.polacz_baze() as conn:
                c = conn.cursor()
                c.execute(
                    "SELECT tytul, opis, priorytet, szacowany_koszt, termin, zadanie_id FROM do_zrobienia WHERE id=?",
                    (pozycja_id,)
                )
                w = c.fetchone()
                if w:
                    tyt_val = str(w[0] or "")
                    opis_val = str(w[1] or "")
                    priorytet_val = str(w[2] or "Średni")
                    koszt_val = str(w[3]) if w[3] not in (None, "") else ""
                    termin_val = str(w[4] or "")
                    zadanie_val = str(w[5]) if w[5] else ""

        with db.polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT id, nazwa FROM zadania WHERE auto_id=? ORDER BY nazwa", (self.state.auto_id,))
            lista_zadan = c.fetchall()

        self.e_tytul = ft.TextField(label="Co trzeba zrobić?*", value=tyt_val, hint_text="np. Wymienić żarówkę, sprawdzić klimatyzację", **utils.styl_pola())
        self.e_opis = ft.TextField(label="Szczegóły (opcjonalnie)", value=opis_val, multiline=True, min_lines=2, max_lines=4, **utils.styl_pola())
        self.e_priorytet = ft.Dropdown(
            label="Priorytet",
            options=[ft.DropdownOption(key=p, text=p) for p in db.PRIORYTETY_DO_ZROBIENIA],
            value=priorytet_val,
            **utils.styl_dropdown()
        )
        self.e_koszt = ft.TextField(label=f"Szacowany koszt ({utils.symbol_waluty()}, opcjonalnie)", value=koszt_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola())
        self.e_termin = utils.pole_daty(page, "Termin realizacji (opcjonalnie)", termin_val)

        opcje_zadan = [ft.DropdownOption(key="", text="— Brak / utworzy się automatycznie —")]
        opcje_zadan += [ft.DropdownOption(key=str(z_id), text=str(z_nazwa)) for z_id, z_nazwa in lista_zadan]
        self.e_zadanie = ft.Dropdown(
            label="Powiąż z istniejącym podzespołem (opcjonalnie)",
            options=opcje_zadan,
            value=zadanie_val,
            **utils.styl_dropdown()
        )

        appbar = utils.zbuduj_pasek_z_powrotem(page, "Edycja pozycji" if pozycja_id else "Nowa pozycja", "/do-zrobienia", on_save=self.zapisz)

        k1 = utils.karta_formularza([self.e_tytul, self.e_opis, self.e_priorytet], "Co i jak pilnie", ft.Icons.CHECKLIST_RTL)
        k2 = utils.karta_formularza([self.e_koszt, self.e_termin], "Koszt i termin", ft.Icons.EVENT)
        k3 = utils.karta_formularza([self.e_zadanie], "Powiązanie z podzespołem", ft.Icons.LINK)

        elementy = [k1, k2, k3, utils.przyciski_akcji(page, "✅ Zapisz pozycję", self.zapisz, "/do-zrobienia")]

        super().__init__(
            route=f"/do-zrobienia/edytuj/{pozycja_id}" if pozycja_id else "/do-zrobienia/nowe",
            padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO
        )

    def zapisz(self, e):
        self.e_tytul.error_text = None
        self.e_koszt.error_text = None

        tytul = (self.e_tytul.value or "").strip()
        bledy = []
        if not tytul:
            bledy.append((self.e_tytul, "Podaj czego dotyczy zadanie"))

        koszt = None
        if (self.e_koszt.value or "").strip():
            koszt = utils.parsuj_float(self.e_koszt.value, None)
            if koszt is None or koszt < 0:
                bledy.append((self.e_koszt, "Podaj poprawny koszt"))

        if bledy:
            return utils.pokaz_bledy_formularza(self._page, bledy)

        zadanie_id = utils.parsuj_int(self.e_zadanie.value, None) if self.e_zadanie.value else None

        with db.polacz_baze() as conn:
            if self.pozycja_id:
                conn.execute(
                    "UPDATE do_zrobienia SET tytul=?, opis=?, priorytet=?, szacowany_koszt=?, termin=?, zadanie_id=? WHERE id=?",
                    (tytul, self.e_opis.value, self.e_priorytet.value, koszt, self.e_termin.value, zadanie_id, self.pozycja_id)
                )
            else:
                conn.execute(
                    "INSERT INTO do_zrobienia (auto_id, tytul, opis, priorytet, szacowany_koszt, termin, zadanie_id, wykonane, data_utworzenia) "
                    "VALUES (?,?,?,?,?,?,?,0,?)",
                    (self.state.auto_id, tytul, self.e_opis.value, self.e_priorytet.value, koszt, self.e_termin.value, zadanie_id, datetime.now().strftime("%d.%m.%Y"))
                )

        utils.przejdz(self._page, "/do-zrobienia")
        utils.pokaz_komunikat(self._page, "Zapisano pozycję listy!")