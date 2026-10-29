import flet as ft
import sqlite3
from datetime import datetime
import db
import log
import sync
import utils
from date import parsuj_date

# Podzakładki: wartość w stanie (1 = Checklisty od dawna, w adresach i skrótach) i kolejność
# w pasku — Wykonane stoją przy liście, z której wyrastają.
DO_ZROBIENIA, CHECKLISTY, WYKONANE = 0, 1, 2
KOLEJNOSC_PODZAKLADEK = (DO_ZROBIENIA, WYKONANE, CHECKLISTY)
TYTULY_PODZAKLADEK = {
    DO_ZROBIENIA: ("Do zrobienia", ft.Icons.CHECKLIST, ft.Icons.CHECKLIST_RTL),
    WYKONANE: ("Wykonane", ft.Icons.TASK_ALT, ft.Icons.TASK_ALT),
    CHECKLISTY: ("Checklisty", ft.Icons.FACT_CHECK, ft.Icons.FACT_CHECK),
}


class DoZrobieniaView(ft.View, utils.ZaznaczanieGrupowe):
    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state

        podzakladka = int(getattr(state, "do_zrobienia_podzakladka", 0) or 0)
        podzakladka = podzakladka if podzakladka in KOLEJNOSC_PODZAKLADEK else DO_ZROBIENIA

        state.do_zrobienia_podzakladka = podzakladka
        self.wspolny_id, _ = sync.czy_udostepniony(state.auto_id)
        appbar = self._appbar_podzakladki()
        fab = self._fab_podzakladki()

        # --- ZMIENNE DLA GRUPOWEGO ZAZNACZANIA / USUWANIA ---
        self.tryb_zaznaczania = False
        self.zaznaczone_id = set()
        self.oryginalny_appbar = appbar
        self.karty_ref = {}
        # ------------------------------------------------------
        self.przewijana_tresc = utils.PrzewijanaTresc()

        # Trzy listy: „Do zrobienia” (wykonana pozycja przechodzi do Wykonanych z dniem,
        # licznikiem i kosztem), „Wykonane” i checklisty (odhaczane i zerowane); pasek nad nimi
        # zostaje na miejscu.
        self.pasek_podzakladek = ft.Container(content=self._pasek_podzakladek())
        self.przelacznik = utils.PrzelacznikEkranow(
            self._zawartosc_podzakladki(), wlaczony=db.czy_animacje_interfejsu()
        )

        self.przewijana_tresc.controls = [
            self.pasek_podzakladek,
            self.przelacznik.kontrolka,
            utils.dol_bezpieczny(10),
        ]

        super().__init__(
            route="/do-zrobienia",
            padding=0,
            appbar=appbar,
            floating_action_button=fab,
            controls=[self.przewijana_tresc.kontrolka],
        )

    # ----- Podzakładki: Do zrobienia / Wykonane / Checklisty -----
    def _podzakladka(self):
        return int(self.state.do_zrobienia_podzakladka or 0)

    def _pasek_podzakladek(self):
        return utils.segmented_control(
            self._page,
            [(TYTULY_PODZAKLADEK[p][0], p, TYTULY_PODZAKLADEK[p][2]) for p in KOLEJNOSC_PODZAKLADEK],
            self._podzakladka(), self._przelacz_podzakladke,
        )

    def _appbar_podzakladki(self):
        tytul, ikona, _ = TYTULY_PODZAKLADEK.get(self._podzakladka(), TYTULY_PODZAKLADEK[DO_ZROBIENIA])
        return utils.zbuduj_pasek_z_powrotem(
            self._page, tytul, "/", ikona=ikona,
            akcje_dodatkowe=[utils.przycisk_synchronizacji(
                self._page,
                utils.funkcja_szybkiej_synchronizacji(self._page, self.state.auto_id, "/do-zrobienia"),
            )] if self.wspolny_id else None,
        )

    def _fab_podzakladki(self):
        if self._podzakladka() == CHECKLISTY:
            return utils.fab_animowany(ft.Icons.ADD, lambda e: self._okno_edytora_checklisty(None))
        if self._podzakladka() == WYKONANE:
            return None
        return utils.fab_animowany(ft.Icons.ADD, lambda e: utils.przejdz(self._page, "/do-zrobienia/nowe"))

    def _przelacz_podzakladke(self, idx):
        stara = self._podzakladka()
        idx = int(idx)
        if idx == stara or idx not in KOLEJNOSC_PODZAKLADEK:
            return

        self.state.do_zrobienia_podzakladka = idx
        # Zaznaczanie dotyczy listy „Do zrobienia”; checklisty odhacza się,
        # a nie kasuje grupowo — stan nie ma prawa przejść między nimi.
        self.tryb_zaznaczania = False
        self.zaznaczone_id = set()
        self.karty_ref = {}
        self.zapomnij_listy_kart()
        self.przewijana_tresc.przyklej(None)

        self.pasek_podzakladek.content = self._pasek_podzakladek()
        self.przelacznik.pokaz(
            self._page, self._zawartosc_podzakladki(),
            kierunek=utils.PrzelacznikEkranow.kierunek(KOLEJNOSC_PODZAKLADEK.index(stara) if stara in
                                                       KOLEJNOSC_PODZAKLADEK else 0, KOLEJNOSC_PODZAKLADEK.index(idx)),
        )
        # Pasek górny niesie tytuł podzakładki, więc idzie za nią — razem
        # z kopią, do której wraca się po wyjściu z trybu zaznaczania.
        self.oryginalny_appbar = self._appbar_podzakladki()
        self.appbar = self.oryginalny_appbar
        self.floating_action_button = self._fab_podzakladki()
        try:
            self.update()
        except Exception:
            log.polkniety("odświeżenie listy Do zrobienia po zmianie podzakładki")

    def _zawartosc_podzakladki(self):
        """Zawartość aktywnej podzakładki jako JEDNA kontrolka — to ona jedzie
        przez przełącznik."""
        elementy = []
        podzakladka = self._podzakladka()
        if podzakladka == CHECKLISTY:
            self._buduj_checklisty(elementy)
        elif podzakladka == WYKONANE:
            self._buduj_wykonane(elementy)
        else:
            self._buduj_aktywne(elementy)
        return ft.Column(elementy, spacing=15)

    # ==================== DO ZROBIENIA I WYKONANE ====================

    def _podsumowanie(self, pary):
        """Karta z liczbami nad listą: (etykieta, wartość, kolor albo None)."""
        return ft.Container(
            padding=utils.wypelnienie_karty(), **utils.powierzchnia(self._page, "karta"),
            content=ft.Row([ft.Container(utils.pole(n, w, color=k), expand=True) for n, w, k in pary],
                           spacing=utils.SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.START),
        )

    def _pole_szukania(self, podpowiedz, klucz, pola_dat):
        def filtruj_pozycje(e):
            zapytanie = (e.control.value or "").lower().strip()
            self.miesiace.ustaw(
                [k for k in self.wszystkie_karty if zapytanie in k["szukaj"]],
                grupuj=utils.czy_po_dacie(self.state, klucz, pola_dat),
            )
            self.update()

        self.pole_wyszukiwarki = ft.TextField(
            hint_text=podpowiedz, prefix_icon=ft.Icons.SEARCH,
            on_change=utils.z_opoznieniem(self._page, filtruj_pozycje), **utils.styl_pola()
        )
        return utils.na_cala_szerokosc(self.pole_wyszukiwarki)

    @staticmethod
    def _brak_wynikow():
        return ft.Row([ft.Text("Brak wyników dla tych filtrów.", color=ft.Colors.ON_SURFACE_VARIANT)],
                      alignment=ft.MainAxisAlignment.CENTER)

    def _buduj_aktywne(self, elementy):
        pozycje = db.pobierz_pozycje_do_zrobienia(self.state.auto_id)
        if not pozycje:
            elementy.append(utils.ekran_braku_danych(
                ikona=ft.Icons.CHECKLIST_RTL,
                tytul="Lista jest pusta",
                opis="Dodawaj tu wszystko, co planujesz zrobić przy aucie. Gdy przyjdzie czas, zamienisz to jednym kliknięciem w Wizytę w warsztacie.",
                tekst_przycisku="Dodaj pozycję",
                on_click=lambda e: utils.przejdz(self._page, "/do-zrobienia/nowe")
            ))
            return

        # „Po terminie” liczy też termin przebiegowy, który licznik już minął.
        stan = db.podsumowanie_do_zrobienia(self.state.auto_id) or {}
        po_terminie, szacunek = stan.get("po_terminie", 0), stan.get("szacowany_koszt") or 0
        elementy.append(self._podsumowanie([
            ("Aktywne", str(stan.get("otwarte", len(pozycje))), None),
            ("Po terminie", str(po_terminie), utils.KOLOR_STATUS["critical"] if po_terminie else None),
            ("Szacunek", f"~{utils.formatuj_liczba(szacunek, 0)} {utils.symbol_waluty()}" if szacunek else "—", None),
        ]))

        opcje_sort = [
            ("Priorytet", "priorytet", lambda x: db.KOLEJNOSC_PRIORYTETU.get(x["priorytet"], 9)),
            ("Termin", "termin", lambda x: parsuj_date(x["termin"])),
            ("Nazwa", "nazwa", lambda x: x["tytul"].lower()),
            ("Koszt", "koszt", lambda x: float(x["szacowany_koszt"] or 0)),
        ]
        sort_ui = utils.przycisk_sortowania(self._page, self.state, "do_zrobienia", opcje_sort)
        chipy_filtrow, po_filtrach = utils.pasek_filtrow(
            self._page, self.state, pozycje, [("kategoria", "do_zrobienia_priorytet", "priorytet", "Priorytet")])
        elementy.append(ft.Row(controls=[sort_ui] + chipy_filtrow, scroll=ft.ScrollMode.ADAPTIVE, spacing=8))
        elementy.append(self._pole_szukania("Szukaj (tytuł, opis, podzespół)", "do_zrobienia", ("termin",)))

        self.lista_kart = utils.lista_kart()
        self.wszystkie_karty = []
        # Tu miesiąc bierze się z TERMINU, nie z daty dopisania — i tylko
        # przy sortowaniu po terminie, bo lista domyślnie idzie po
        # priorytecie i miesiące nie byłyby wtedy ciągłe.
        self.miesiace = utils.GrupyMiesiecy(
            self._page, self.lista_kart, wysokosc_pozycji=185, widok=self, klucz="do_zrobienia"
        )
        utils.posortuj_liste(po_filtrach, self.state, "do_zrobienia", opcje_sort)

        if not po_filtrach:
            elementy.append(self._brak_wynikow())
        else:
            j = utils.jednostka_dystansu()
            wolno = utils.wolno_zmieniac_rekord(self.state.auto_id)
            for p in po_filtrach:
                self.wszystkie_karty.append({
                    "karta": self._karta_pozycji(p, j, wolno),
                    "szukaj": f"{p['tytul']} {p['opis']} {p['priorytet']} {p['termin']} {p['zadanie_nazwa'] or ''}".lower(),
                    "data": p["termin"], "kwota": float(p["szacowany_koszt"] or 0),
                })
            self.miesiace.ustaw(
                self.wszystkie_karty,
                grupuj=utils.czy_po_dacie(self.state, "do_zrobienia", ("termin",)),
            )

        elementy.append(self.lista_kart)

    def _buduj_wykonane(self, elementy):
        pozycje = db.pobierz_pozycje_do_zrobienia(self.state.auto_id, wykonane=True)
        if not pozycje:
            elementy.append(utils.ekran_braku_danych(
                ikona=ft.Icons.TASK_ALT,
                tytul="Nic jeszcze nie wykonano",
                opis="Odhaczona pozycja trafia tutaj z dniem wykonania, stanem licznika i kosztem — razem "
                     "z historią: kiedy ją dodano, przesuwano i zrobiono.",
                tekst_przycisku="Przejdź do listy",
                on_click=lambda e: self._przelacz_podzakladke(DO_ZROBIENIA),
            ))
            return

        rok = datetime.now().year
        w_roku = [p for p in pozycje if parsuj_date(p["data_wykonania"]).year == rok]
        suma = sum(float(p["koszt_wykonania"] or 0) for p in w_roku)
        elementy.append(self._podsumowanie([
            ("W tym roku", str(len(w_roku)), None),
            ("Wydane w tym roku", f"{utils.formatuj_liczba(suma, 0)} {utils.symbol_waluty()}" if suma else "—", None),
            ("Wszystkie", str(len(pozycje)), None),
        ]))

        opcje_sort = [
            ("Data wykonania", "data", lambda x: parsuj_date(x["data_wykonania"])),
            ("Nazwa", "nazwa", lambda x: x["tytul"].lower()),
            ("Koszt", "koszt", lambda x: float(x["koszt_wykonania"] or 0)),
        ]
        sort_ui = utils.przycisk_sortowania(self._page, self.state, "do_zrobienia_wykonane", opcje_sort)
        chipy_filtrow, po_filtrach = utils.pasek_filtrow(
            self._page, self.state, pozycje, [("rok", "do_zrobienia_wykonane_rok", "data_wykonania", "Rok")])
        elementy.append(ft.Row(controls=[sort_ui] + chipy_filtrow, scroll=ft.ScrollMode.ADAPTIVE, spacing=8))
        elementy.append(self._pole_szukania("Szukaj (tytuł, notatka, podzespół)", "do_zrobienia_wykonane", ("data",)))

        self.lista_kart = utils.lista_kart()
        self.wszystkie_karty = []
        self.miesiace = utils.GrupyMiesiecy(
            self._page, self.lista_kart, wysokosc_pozycji=150, widok=self, klucz="do_zrobienia_wykonane"
        )
        utils.posortuj_liste(po_filtrach, self.state, "do_zrobienia_wykonane", opcje_sort)

        if not po_filtrach:
            elementy.append(self._brak_wynikow())
        else:
            j = utils.jednostka_dystansu()
            for p in po_filtrach:
                self.wszystkie_karty.append({
                    "karta": self._karta_wykonanej(p, j),
                    "szukaj": f"{p['tytul']} {p['opis']} {p['notatka_wykonania'] or ''} {p['zadanie_nazwa'] or ''} "
                              f"{p['data_wykonania'] or ''}".lower(),
                    "data": p["data_wykonania"], "kwota": float(p["koszt_wykonania"] or 0),
                })
            self.miesiace.ustaw(
                self.wszystkie_karty,
                grupuj=utils.czy_po_dacie(self.state, "do_zrobienia_wykonane", ("data",)),
            )

        elementy.append(self.lista_kart)

    # ==================== CHECKLISTY ====================
    # Lista przedwyjazdowa różni się od „Do zrobienia” jedną rzeczą, ale
    # zasadniczą: jest WIELOKROTNEGO UŻYTKU. Dlatego pozycji się tu nie usuwa,
    # tylko odhacza, a po powrocie zeruje jednym przyciskiem.

    def _buduj_checklisty(self, elementy):
        listy = db.pobierz_checklisty(self.state.auto_id)

        if not listy:
            elementy.append(utils.ekran_braku_danych(
                ikona=ft.Icons.FACT_CHECK,
                tytul="Brak checklist",
                opis="Lista kontrolna, którą odhaczasz przed dłuższą trasą: opony, olej, płyn do "
                     "spryskiwaczy, dokumenty. Po powrocie zerujesz ją jednym przyciskiem.",
                tekst_przycisku="Dodaj gotową listę przedwyjazdową",
                on_click=lambda e: self._utworz_domyslna(),
            ))
            elementy.append(ft.Row([
                ft.TextButton("Albo zbuduj własną listę", icon=ft.Icons.ADD,
                              on_click=lambda e: self._okno_edytora_checklisty(None)),
            ], alignment=ft.MainAxisAlignment.CENTER))
            return

        for lista in listy:
            elementy.append(self._karta_checklisty(lista))

        elementy.append(ft.Row([
            ft.TextButton("Nowa checklista", icon=ft.Icons.ADD,
                          on_click=lambda e: self._okno_edytora_checklisty(None)),
        ], alignment=ft.MainAxisAlignment.CENTER))

    def _utworz_domyslna(self):
        db.utworz_domyslna_checkliste(self.state.auto_id)
        utils.przejdz(self._page, "/do-zrobienia")

    def _karta_checklisty(self, lista):
        razem = lista["razem"]
        licznik = ft.Text("", weight="bold", size=13)
        pasek = ft.ProgressBar(height=6, border_radius=3,
                               bgcolor=utils.tlo_toru(self._page))

        def odswiez_naglowek():
            zrobione = sum(1 for c in checkboxy if c.value)
            gotowa = razem > 0 and zrobione == razem
            licznik.value = f"{zrobione} / {razem}"
            licznik.color = utils.KOLOR_STATUS["ok"] if gotowa else ft.Colors.ON_SURFACE_VARIANT
            pasek.value = (zrobione / razem) if razem else 0
            pasek.color = utils.KOLOR_STATUS["ok"] if gotowa else ft.Colors.PRIMARY

        def przelacz(e, pozycja_id):
            db.przelacz_pozycje_checklisty(pozycja_id, bool(e.control.value))
            odswiez_naglowek()
            # Odświeżamy sam nagłówek, a nie cały ekran: przy dziesięciu punktach
            # przeładowanie widoku po każdym ptaszku gubiłoby pozycję przewijania.
            try:
                self._page.update()
            except Exception:
                pass

        checkboxy = []
        for p in lista["pozycje"]:
            checkboxy.append(ft.Checkbox(
                label=p["tresc"], value=p["odhaczone"],
                on_change=lambda e, pid=p["id"]: przelacz(e, pid),
            ))
        odswiez_naglowek()

        def wyzeruj():
            db.wyzeruj_checkliste(lista["id"])
            utils.przejdz(self._page, "/do-zrobienia")
            utils.pokaz_komunikat(self._page, f"Wyzerowano „{lista['nazwa']}”.")

        def odhacz_wszystko():
            db.odhacz_cala_checkliste(lista["id"])
            utils.przejdz(self._page, "/do-zrobienia")
            utils.pokaz_komunikat(self._page, f"Odhaczono całą listę „{lista['nazwa']}”.")

        def usun():
            def wykonaj():
                db.usun_checkliste(lista["id"])
                utils.przejdz(self._page, "/do-zrobienia")
                utils.pokaz_komunikat(self._page, "Usunięto checklistę.")
            utils.potwierdz(
                self._page, "Usunąć checklistę?",
                f"„{lista['nazwa']}” zniknie razem z wszystkimi pozycjami.", wykonaj,
            )

        def menu(e):
            utils.pokaz_menu_kontekstowe(self._page, f"Checklista: {lista['nazwa']}", utils.odsiej_akcje(self.state.auto_id, [
                {"ikona": ft.Icons.EDIT, "tekst": "Edytuj listę i pozycje",
                 "akcja": lambda: self._okno_edytora_checklisty(lista)},
                {"ikona": ft.Icons.DONE_ALL, "tekst": "Odhacz wszystko", "akcja": odhacz_wszystko},
                {"ikona": ft.Icons.RESTART_ALT, "tekst": "Wyzeruj ptaszki", "akcja": wyzeruj},
                {"ikona": ft.Icons.DELETE, "tekst": "Usuń checklistę", "kolor": utils.KOLOR_STATUS["destructive"], "akcja": usun},
            ]))

        podpis = []
        if lista["ostatnie_uzycie"]:
            podpis.append(f"ostatnio: {lista['ostatnie_uzycie']}")
        if lista["opis"]:
            podpis.append(lista["opis"])

        naglowek = [
            ft.Row([
                ft.Icon(ft.Icons.FACT_CHECK, size=18, color=ft.Colors.PRIMARY),
                ft.Text(lista["nazwa"], weight="bold", size=16, expand=True,
                        no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                licznik,
                ft.IconButton(ft.Icons.MORE_VERT, icon_size=18, tooltip="Opcje listy", on_click=menu),
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            pasek,
        ]
        if podpis:
            naglowek.append(ft.Text(" • ".join(podpis), size=utils.FS["caption"],
                                    color=ft.Colors.ON_SURFACE_VARIANT))

        return ft.Card(elevation=1, content=ft.Container(
            padding=15,
            content=ft.Column(
                naglowek + [ft.Divider(height=10)] + ([utils.pole_wyboru(c) for c in checkboxy] or [
                    ft.Text("Ta lista nie ma jeszcze pozycji — dodaj je w edycji.",
                            size=12, italic=True, color=ft.Colors.ON_SURFACE_VARIANT)
                ]) + [
                    ft.Row([
                        ft.TextButton("Wyzeruj", icon=ft.Icons.RESTART_ALT, on_click=lambda e: wyzeruj()),
                        ft.TextButton("Odhacz wszystko", icon=ft.Icons.DONE_ALL, on_click=lambda e: odhacz_wszystko()),
                    ], alignment=ft.MainAxisAlignment.END, spacing=0),
                ],
                spacing=6,
            ),
        ))

    def _okno_edytora_checklisty(self, lista):
        """Jeden edytor do tworzenia i edycji. Pozycje wpisuje się jako zwykły
        tekst, po jednej w linii — wklejenie listy z notatnika ma po prostu
        zadziałać, a nie wymagać dziesięciu kliknięć „dodaj pozycję”."""
        edycja = lista is not None
        e_nazwa = ft.TextField(
            label="Nazwa listy", value=str(lista["nazwa"]) if edycja else "",
            **utils.styl_pola()
        )
        e_pozycje = ft.TextField(
            label="Pozycje — po jednej w linii",
            value="\n".join(p["tresc"] for p in lista["pozycje"]) if edycja else "",
            multiline=True, min_lines=6, max_lines=14, **utils.styl_pola()
        )

        def zapisz(e):
            utils.ustaw_blad(e_nazwa)
            utils.ustaw_blad(e_pozycje)
            nazwa = (e_nazwa.value or "").strip()
            pozycje = [w for w in (e_pozycje.value or "").splitlines() if w.strip()]
            bledy = []
            if not nazwa:
                bledy.append((e_nazwa, "Podaj nazwę listy"))
            if not pozycje:
                bledy.append((e_pozycje, "Dodaj przynajmniej jedną pozycję"))
            if bledy:
                for kontrolka, komunikat in bledy:
                    utils.ustaw_blad(kontrolka, komunikat)
                self._page.update()
                return
            if edycja:
                db.aktualizuj_checkliste(lista["id"], nazwa, pozycje)
            else:
                db.dodaj_checkliste(self.state.auto_id, nazwa, pozycje)
            utils.zamknij_dialog(self._page, dlg)
            utils.przejdz(self._page, "/do-zrobienia")

        dlg = ft.AlertDialog(
            title=ft.Text("Edytuj checklistę" if edycja else "Nowa checklista", weight="bold"),
            content=ft.Column([
                e_nazwa, e_pozycje,
                ft.Text("Zmiana nazwy albo dopisanie punktu NIE kasuje postawionych ptaszków — "
                        "pozycje dopasowują się po treści.",
                        size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT),
            ], tight=True, spacing=10, scroll=ft.ScrollMode.AUTO),
            actions=[
                ft.TextButton("Anuluj", on_click=lambda e: utils.zamknij_dialog(self._page, dlg)),
                ft.Button("Zapisz", on_click=zapisz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY),
            ],
        )
        utils.otworz_dialog(self._page, dlg)

    # --- KARTY POZYCJI ---
    def _podepnij_gesty(self, kontener, p_id):
        """Dotknięcie — szczegóły (w trybie zaznaczania: zaznacz), przytrzymanie — zaznaczanie."""
        def _on_click(e, pid=p_id):
            if self.tryb_zaznaczania:
                self.zaznacz_odznacz(pid, self.karty_ref[pid])
            else:
                self._pokaz_szczegoly(pid)

        def _on_long_press(e, pid=p_id):
            if not self.tryb_zaznaczania:
                self.tryb_zaznaczania = True
                self.zaznacz_odznacz(pid, self.karty_ref[pid])

        self.karty_ref[p_id] = kontener
        kontener.on_click = utils.z_efektem_nacisniecia(kontener, _on_click)
        kontener.on_long_press = _on_long_press

    def _karta_pozycji(self, p, j=None, wolno=True):
        kolor_priorytetu = utils.kolor_priorytetu(p["priorytet"])
        kolor_term, tekst_term = utils.kolor_i_tekst_terminu(p["termin"]) if p["termin"] else (None, None)

        # Ptaszek nie odhacza sam — otwiera okno „Wykonano” z dniem, licznikiem i kosztem.
        chk = ft.Checkbox(value=False, on_change=lambda e, pid=p["id"]: self._odhacz(e, pid),
                          active_color=utils.KOLOR_STATUS["ok"], tooltip="Oznacz jako wykonane", disabled=not wolno)

        podtytul_bits = []
        if p["opis"]:
            podtytul_bits.append(str(p["opis"]))
        # Planowana z Serwisu („Wymiana: Olej silnikowy”) ma podzespół już w tytule.
        if p["zadanie_nazwa"] and db.klucz_nazwy(p["zadanie_nazwa"]) not in db.klucz_nazwy(p["tytul"]):
            podtytul_bits.append(f"Podzespół: {p['zadanie_nazwa']}")

        stopka_bits = []
        if p["szacowany_koszt"]:
            stopka_bits.append(utils.podpis(f"~{utils.formatuj_liczba(float(p['szacowany_koszt']))} {utils.symbol_waluty()}"))
        if tekst_term:
            stopka_bits.append(ft.Text(tekst_term, size=12, weight="bold", color=kolor_term))

        tresc_kolumny = [
            ft.Row([
                ft.Text(str(p["tytul"]), size=16, weight="bold", expand=True),
                utils.chip_priorytetu(p["priorytet"]),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER)
        ]
        if podtytul_bits:
            tresc_kolumny.append(ft.Text("  •  ".join(podtytul_bits), size=13, color=ft.Colors.ON_SURFACE_VARIANT))
        if stopka_bits:
            tresc_kolumny.append(ft.Row(stopka_bits, spacing=12))
        przebieg = utils.termin_przebiegowy_karty(p, j)
        if przebieg:
            tresc_kolumny.append(przebieg)

        karta, kontener = utils.karta_listy(
            ft.Row([
                chk,
                ft.Column(tresc_kolumny, spacing=4, expand=True)
            ], vertical_alignment=ft.CrossAxisAlignment.START, spacing=10),
            kolor_paska=kolor_priorytetu,
            page=self._page,
        )
        self._podepnij_gesty(kontener, p["id"])
        return karta

    def _karta_wykonanej(self, p, j=None):
        tresc = [
            ft.Text(str(p["tytul"]), size=16, weight="bold"),
            utils.podpis(utils.tekst_wykonania(p, j), max_lines=2),
        ]
        if p["notatka_wykonania"]:
            tresc.append(ft.Text(f"„{p['notatka_wykonania']}”", size=13, italic=True, max_lines=2))
        dopiski = []
        if p["wizyta_id"]:
            dopiski.append((ft.Icons.HOME_REPAIR_SERVICE, "w wizycie"))
        elif p["historia_id"]:
            dopiski.append((ft.Icons.BUILD, "w serwisie"))
        if p["koszt_id"]:
            dopiski.append((ft.Icons.RECEIPT_LONG, "w Innych kosztach"))
        if self.wspolny_id and p["wykonane_przez"]:
            dopiski.append((ft.Icons.PERSON, str(p["wykonane_przez"])))
        if dopiski:
            tresc.append(ft.Row([
                ft.Row([ft.Icon(ikona, size=14, color=ft.Colors.ON_SURFACE_VARIANT), utils.podpis(tekst)],
                       spacing=4, tight=True)
                for ikona, tekst in dopiski
            ], spacing=12, wrap=True))

        karta, kontener = utils.karta_listy(
            ft.Row([
                ft.Icon(ft.Icons.TASK_ALT, size=22, color=utils.KOLOR_STATUS["ok"]),
                ft.Column(tresc, spacing=4, expand=True),
            ], vertical_alignment=ft.CrossAxisAlignment.START, spacing=10),
            kolor_paska=utils.KOLOR_STATUS["ok"],
            page=self._page,
        )
        self._podepnij_gesty(kontener, p["id"])
        return karta

    # --- WYKONANIE ---
    def _odhacz(self, e, p_id):
        e.control.value = False
        try:
            e.control.update()
        except Exception:
            log.polkniety("ptaszek pozycji Do zrobienia przed oknem wykonania")
        self._okno_wykonania([db.pozycja_do_zrobienia(p_id)])

    def _okno_wykonania(self, pozycje):
        utils.okno_wykonania(self._page, self.state.auto_id, pozycje, po_zapisie=self._po_wykonaniu, state=self.state)

    def _do_serwisu(self, p):
        """Część z Serwisu → pełny formularz wymiany wypełniony z pozycji; „Nowy podzespół…” →
        formularz podzespołu z nazwą z tytułu."""
        def po_wyborze(cel):
            if cel == utils.CEL_NOWY:
                utils.przejdz(self._page, f"/zadanie/nowy/do-zrobienia/{p['id']}")
            else:
                utils.przejdz(self._page, f"/wpis/nowy/{cel[2:]}/do-zrobienia/{p['id']}")

        utils.pokaz_wybor_podzespolu(self._page, self.state.auto_id, p, po_wyborze,
                                     "Przenieś do serwisu" if p["wykonane"] else "Dopisz do serwisu")

    def _po_wykonaniu(self, wynik, poprawka=False):
        # Ekran i tak buduje się od nowa (przejdz) — wystarczy zapomnieć zaznaczenie.
        self.tryb_zaznaczania, self.zaznaczone_id = False, set()
        self._odswiez(utils.komunikat_wykonania(wynik, poprawka))

    def _odswiez(self, komunikat=None):
        utils.wypchnij_w_tle(self._page, self.state.auto_id, "do zrobienia")
        utils.przejdz(self._page, "/do-zrobienia")
        if komunikat:
            utils.pokaz_komunikat(self._page, komunikat)

    def _cofnij_wykonanie(self, p):
        if p["historia_id"] and not p["w_wizycie"]:
            tresc = "Pozycja wróci na listę Do zrobienia, a wpis serwisowy z tego wykonania trafi do kosza."
        elif p["koszt_id"]:
            tresc = "Pozycja wróci na listę Do zrobienia, a Inny koszt z tego wykonania trafi do kosza."
        elif p["wizyta_id"]:
            tresc = "Pozycja wróci na listę Do zrobienia — wizyta zostaje bez zmian."
        else:
            tresc = "Pozycja wróci na listę Do zrobienia, a jej historia zapamięta to wykonanie."

        def wykonaj():
            wynik = db.cofnij_wykonanie_do_zrobienia(p["id"])
            if not wynik:
                utils.pokaz_komunikat(self._page, "Nie udało się cofnąć wykonania.", utils.KOLOR_STATUS["error"])
                return
            self._odswiez("Pozycja wróciła na listę." + (" Wpis z wykonania jest w koszu." if wynik["do_kosza"] else ""))

        utils.potwierdz(self._page, "Cofnąć wykonanie?", tresc, wykonaj, tekst_potwierdzenia="Cofnij", destrukcyjne=False)

    def _zwroc_z_wizyty(self, p):
        wynik = db.zwroc_pozycje_wizyty_do_zrobienia(p["wizyta_id"], [p["historia_id"]])
        utils.przejdz(self._page, "/do-zrobienia")
        utils.pokaz_komunikat_cofnij(self._page, "Pozycja wróciła z wizyty na listę.", wynik,
                                     wiadomosc_bledu="Nie udało się zwrócić pozycji z wizyty.")

    # --- SZCZEGÓŁY POZYCJI (BOTTOM SHEET) ---
    def _pokaz_szczegoly(self, p_id):
        p = db.pozycja_do_zrobienia(p_id)
        if not p:
            return
        j = utils.jednostka_dystansu()
        utils.pokaz_menu_kontekstowe(
            self._page, p["tytul"],
            utils.odsiej_akcje(self.state.auto_id, self._akcje_pozycji(p), "do_zrobienia", p_id),
            tresc=utils.szczegoly_pozycji_do_zrobienia(p, bool(self.wspolny_id), j),
            dopisek=utils.historia_pozycji_do_zrobienia(p, db.pobierz_zdarzenia_do_zrobienia(p_id), j),
        )

    def _akcje_pozycji(self, p):
        p_id, tytul = p["id"], p["tytul"]

        def usun_pozycje():
            def wykonaj():
                wynik = db.usun_z_cofnieciem("do_zrobienia", p_id)
                utils.przejdz(self._page, "/do-zrobienia")
                utils.pokaz_komunikat_cofnij(self._page, "Usunięto pozycję.", wynik)
            utils.potwierdz(self._page, "Usunąć?", "Czy na pewno chcesz usunąć tę pozycję razem z jej historią?", wykonaj)

        def poprosz_o_wizyte():
            self._zapytaj_i_utworz_wizyte(
                [p_id],
                "Utworzyć wizytę?",
                f"Z pozycji „{tytul}” powstanie nowa Wizyta w warsztacie, gotowa do uzupełnienia szczegółów. "
                "Pozycja trafi do Wykonanych z odnośnikiem do wizyty."
            )

        edytuj = {"ikona": ft.Icons.EDIT, "tekst": "Edytuj", "akcja": lambda: utils.przejdz(self._page, f"/do-zrobienia/edytuj/{p_id}")}
        usun = {"ikona": ft.Icons.DELETE, "tekst": "Usuń pozycję", "akcja": usun_pozycje, "kolor": utils.KOLOR_STATUS["destructive"]}
        do_serwisu = {"ikona": ft.Icons.BUILD, "tekst": "Przenieś do serwisu" if p["wykonane"] else "Dopisz do serwisu",
                      "akcja": lambda: self._do_serwisu(p)}
        if not p["wykonane"]:
            akcje = [
                {"ikona": ft.Icons.CHECK_CIRCLE, "tekst": "Oznacz jako wykonane", "akcja": lambda: self._okno_wykonania([p]),
                 "kolor": utils.KOLOR_STATUS["ok"]},
                do_serwisu,
            ]
            if not p["zadanie_id"]:
                akcje.append({"ikona": ft.Icons.HANDYMAN, "tekst": "Przekształć w podzespół Serwisu",
                              "akcja": lambda: utils.przejdz(self._page, f"/zadanie/nowy/do-zrobienia/{p_id}")})
            return akcje + [
                {"ikona": ft.Icons.EVENT_REPEAT, "tekst": "Przesuń termin",
                 "akcja": lambda: utils.okno_przesuniecia_terminu(self._page, p, po_zmianie=lambda: self._odswiez("Przesunięto termin."))},
                {"ikona": ft.Icons.BUILD_CIRCLE, "tekst": "Utwórz wizytę w warsztacie", "akcja": poprosz_o_wizyte, "kolor": ft.Colors.PRIMARY},
                edytuj, usun,
            ]

        akcje = []
        if not p["w_wizycie"]:
            akcje.append({"ikona": ft.Icons.EDIT_CALENDAR, "tekst": "Popraw wykonanie", "akcja": lambda: self._okno_wykonania([p])})
        if p["wizyta_id"]:
            akcje.append({"ikona": ft.Icons.HOME_REPAIR_SERVICE, "tekst": "Otwórz wizytę",
                          "akcja": lambda: utils.przejdz(self._page, f"/wizyty/edytuj/{p['wizyta_id']}")})
        elif p["historia_id"]:
            akcje.append({"ikona": ft.Icons.BUILD, "tekst": "Otwórz wpis serwisowy",
                          "akcja": lambda: utils.przejdz(self._page, f"/wpis/edytuj/{p['historia_id']}")})
        elif not p["w_wizycie"]:
            akcje.append(do_serwisu)
        if p["koszt_id"]:
            akcje.append({"ikona": ft.Icons.RECEIPT_LONG, "tekst": "Otwórz Inny koszt",
                          "akcja": lambda: utils.przejdz(self._page, f"/inne/edytuj/{p['koszt_id']}")})
        if p["w_wizycie"] and p["wizyta_id"] and p["historia_id"]:
            akcje.append({"ikona": ft.Icons.ASSIGNMENT_RETURN, "tekst": "Zwróć z wizyty na listę",
                          "akcja": lambda: self._zwroc_z_wizyty(p)})
        else:
            akcje.append({"ikona": ft.Icons.UNDO, "tekst": "Cofnij wykonanie", "akcja": lambda: self._cofnij_wykonanie(p),
                          "kolor": utils.KOLOR_STATUS["warning"]})
        return akcje + [edytuj, usun]

    def potwierdz_grupowe_usuwanie(self, e):
        ile = len(self.zaznaczone_id)
        def wykonaj():
            wynik = db.usun_wiele_z_cofnieciem("do_zrobienia", list(self.zaznaczone_id))
            self.zakoncz_zaznaczanie()
            utils.przejdz(self._page, "/do-zrobienia")
            utils.pokaz_komunikat_cofnij(self._page, f"Usunięto {db.liczba_z_odmiana(ile, 'pozycję', 'pozycje', 'pozycji')}.", wynik)
        utils.potwierdz(self._page, "Usuwanie", f"Czy na pewno chcesz usunąć zaznaczone pozycje ({ile})?", wykonaj)

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
                utils.pole_wyboru(chk_podzespoly),
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
            f"Z {ile} zaznaczonych pozycji powstanie nowa Wizyta w warsztacie, a te pozycje trafią do Wykonanych "
            "z odnośnikiem do wizyty. Kontynuować?"
        )

    def oznacz_zaznaczone_jako_wykonane(self, e):
        """Jedno okno „Wykonano” — wspólny dzień, licznik i notatka; koszt każdej to jej szacunek."""
        pozycje = [db.pozycja_do_zrobienia(i) for i in sorted(self.zaznaczone_id)]
        self._okno_wykonania([p for p in pozycje if p and not p["wykonane"]])

    def aktualizuj_appbar_zaznaczania(self, dodatkowe_akcje=None):
        extra = []
        if self.wolno_zmieniac_zaznaczone() and self._podzakladka() == DO_ZROBIENIA:
            extra.append(ft.IconButton(ft.Icons.TASK_ALT, tooltip="Oznacz zaznaczone jako wykonane",
                                       on_click=self.oznacz_zaznaczone_jako_wykonane))
            extra.append(ft.IconButton(ft.Icons.BUILD_CIRCLE, tooltip="Utwórz wizytę z zaznaczonych", on_click=self.utworz_wizyte_z_zaznaczonych))
        super().aktualizuj_appbar_zaznaczania(dodatkowe_akcje=extra)

class FormularzDoZrobieniaView(ft.View):
    def __init__(self, page: ft.Page, state, pozycja_id=None, zadanie_id=None):
        self._page = page
        self.state = state
        self.pozycja_id = pozycja_id
        self.zadanie_id = None
        self.trasa_powrotu = "/do-zrobienia"

        tyt_val, opis_val, priorytet_val = "", "", "Średni"
        koszt_val, termin_val, zadanie_val = "", "", ""
        self.km_terminu = None

        w = db.pozycja_do_zrobienia(pozycja_id) if pozycja_id else None
        if w:
            tyt_val = w["tytul"]
            opis_val = w["opis"]
            priorytet_val = w["priorytet"]
            koszt_val = utils.liczba_do_pola(w["szacowany_koszt"])
            termin_val = w["termin"]
            zadanie_val = str(w["zadanie_id"]) if w["zadanie_id"] else ""
            self.km_terminu = w["termin_przebieg"]

        with db.polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT id, nazwa FROM zadania WHERE auto_id=? ORDER BY nazwa", (self.state.auto_id,))
            lista_zadan = c.fetchall()

        # Planowana z karty podzespołu (/do-zrobienia/nowe/podzespol/<id>): tytuł, podzespół
        # i terminy z interwału; zapis i „Wróć” prowadzą z powrotem do Serwisu.
        plan = self._plan_z_podzespolu(zadanie_id) if zadanie_id and not pozycja_id else None
        if plan:
            tyt_val, zadanie_val, termin_val, self.km_terminu = plan
            self.zadanie_id, self.trasa_powrotu = zadanie_id, "/"

        self.e_tytul = ft.TextField(label="Co trzeba zrobić?*", value=tyt_val, hint_text="np. wymienić żarówkę", **utils.styl_pola())
        self.e_opis = ft.TextField(label="Szczegóły (opcjonalnie)", value=opis_val, multiline=True, min_lines=2, max_lines=4, **utils.styl_pola())
        self.e_priorytet = ft.Dropdown(
            label="Priorytet",
            options=[ft.DropdownOption(key=p, text=p) for p in db.PRIORYTETY_DO_ZROBIENIA],
            value=priorytet_val,
            **utils.styl_dropdown()
        )
        self.e_koszt = ft.TextField(label=f"Szacowany koszt ({utils.symbol_waluty()})", value=koszt_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola())
        self.e_termin = utils.pole_daty(page, "Termin realizacji", termin_val)
        # Termin przebiegowy: pasek na karcie liczy się od licznika z chwili zaplanowania.
        self.e_termin_km = ft.TextField(
            label=f"Albo przy przebiegu ({utils.jednostka_dystansu()})",
            value=db.wartosc_pola_dystansu(self.km_terminu) if self.km_terminu else "",
            hint_text="np. 150 000", keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola()
        )

        opcje_zadan = [ft.DropdownOption(key="", text="— Brak (utworzy się) —")]
        opcje_zadan += [ft.DropdownOption(key=str(z_id), text=str(z_nazwa)) for z_id, z_nazwa in lista_zadan]
        self.e_zadanie = ft.Dropdown(
            label="Powiąż z podzespołem",
            options=opcje_zadan,
            value=zadanie_val,
            **utils.styl_dropdown()
        )

        self._stan_poczatkowy = self._migawka_formularza()
        appbar = utils.zbuduj_pasek_z_powrotem(page, "Edycja pozycji" if pozycja_id else "Nowa pozycja", self.trasa_powrotu, on_save=self.zapisz, czy_zmieniono=self._czy_zmieniono)

        k1 = utils.karta_formularza([self.e_tytul, self.e_opis, self.e_priorytet], "Co i jak pilnie", ft.Icons.CHECKLIST_RTL)
        k2 = utils.karta_formularza([self.e_koszt, self.e_termin, self.e_termin_km], "Koszt i termin", ft.Icons.EVENT)
        k3 = utils.karta_formularza([self.e_zadanie], "Powiązanie z podzespołem", ft.Icons.LINK)

        elementy = [k1, k2, k3, utils.przyciski_akcji(page, "Zapisz pozycję", self.zapisz, self.trasa_powrotu)]

        if pozycja_id:
            trasa = f"/do-zrobienia/edytuj/{pozycja_id}"
        else:
            trasa = f"/do-zrobienia/nowe/podzespol/{self.zadanie_id}" if self.zadanie_id else "/do-zrobienia/nowe"
        super().__init__(
            route=trasa, padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO
        )

    def _plan_z_podzespolu(self, zadanie_id):
        """(tytuł, podzespół, termin, licznik terminu) pozycji planowanej z podzespołu — terminy
        z interwału (db.oblicz_stan_interwalu), gdy podzespół go ma i był już wymieniany."""
        with db.polacz_baze() as conn:
            conn.row_factory = sqlite3.Row
            z = conn.execute("SELECT * FROM zadania WHERE id=? AND auto_id=?", (zadanie_id, self.state.auto_id)).fetchone()
        if not z:
            return None
        z = dict(z)
        stan = db.oblicz_stan_interwalu(z, db.pobierz_aktualny_przebieg(self.state.auto_id))
        termin = stan["czas"]["data"].strftime("%d.%m.%Y") if stan["czas"] else ""
        km = int(z["przebieg"] + z["interwal_km"]) if stan["km"] else None
        return f"Wymiana: {z['nazwa']}", str(zadanie_id), termin, km

    def _migawka_formularza(self):
        return (self.e_tytul.value, self.e_opis.value, self.e_priorytet.value,
                self.e_koszt.value, self.e_termin.value, self.e_termin_km.value, self.e_zadanie.value)

    def _czy_zmieniono(self):
        return self._migawka_formularza() != self._stan_poczatkowy

    def zapisz(self, e):
        utils.ustaw_blad(self.e_tytul)
        utils.ustaw_blad(self.e_koszt)
        utils.ustaw_blad(self.e_termin_km)

        tytul = (self.e_tytul.value or "").strip()
        bledy = []
        if not tytul:
            bledy.append((self.e_tytul, "Podaj czego dotyczy zadanie"))

        koszt = None
        if (self.e_koszt.value or "").strip():
            koszt = utils.parsuj_float(self.e_koszt.value, None)
            if koszt is None or koszt < 0:
                bledy.append((self.e_koszt, "Podaj poprawny koszt"))

        km = None
        if (self.e_termin_km.value or "").strip():
            km = db.dystans_na_km(self.e_termin_km.value, calkowity=True, km_przy_otwarciu=self.km_terminu)
            if not km or km <= 0:
                bledy.append((self.e_termin_km, "Podaj poprawny stan licznika"))

        if bledy:
            return utils.pokaz_bledy_formularza(self._page, bledy)

        zadanie_id = utils.parsuj_int(self.e_zadanie.value, None) if self.e_zadanie.value else None
        zapisana = db.zapisz_pozycje_do_zrobienia(self.state.auto_id, {
            "tytul": tytul, "opis": self.e_opis.value, "priorytet": self.e_priorytet.value,
            "szacowany_koszt": koszt, "termin": self.e_termin.value, "zadanie_id": zadanie_id, "termin_przebieg": km,
        }, self.pozycja_id)
        if not zapisana:
            return utils.pokaz_komunikat(self._page, "Nie zapisano: pozycji już nie ma albo nie masz do niej uprawnień.",
                                         utils.KOLOR_STATUS["error"])

        utils.wypchnij_w_tle(self._page, self.state.auto_id, "do zrobienia")
        utils.przejdz(self._page, self.trasa_powrotu)
        utils.pokaz_komunikat(self._page, "Dodano do Do zrobienia." if self.zadanie_id else "Zapisano pozycję listy!")