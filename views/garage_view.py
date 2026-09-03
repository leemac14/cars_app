import flet as ft
import db
import sync
import utils

SEZONY = ["Letnie", "Zimowe", "Całoroczne"]
IKONY_SEZONU = {
    "Letnie": ft.Icons.WB_SUNNY,
    "Zimowe": ft.Icons.AC_UNIT,
    "Całoroczne": ft.Icons.AUTORENEW,
}

IKONY_KATEGORII_MAGAZYNU = {
    "Płyny eksploatacyjne": ft.Icons.WATER_DROP,
    "Oleje i smary": ft.Icons.OIL_BARREL,
    "Żarówki i bezpieczniki": ft.Icons.LIGHTBULB,
    "Filtry": ft.Icons.FILTER_ALT,
    "Akcesoria": ft.Icons.HANDYMAN,
    "Inne": ft.Icons.INVENTORY_2,
}


def interpretuj_dot(kod):
    """Jeśli kod wygląda jak standardowy 4-cyfrowy znacznik DOT (tydzień+rok), zwraca czytelny opis."""
    kod = (kod or "").strip()
    if len(kod) == 4 and kod.isdigit():
        tydzien = int(kod[:2])
        rok = int(kod[2:])
        if 1 <= tydzien <= 53:
            rok_pelny = 2000 + rok if rok <= 79 else 1900 + rok
            return f"tydz. {tydzien:02d}/{rok_pelny}"
    return None


class MagazynView(ft.View, utils.ZaznaczanieGrupowe):
    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state

        wspolny_id, _ = sync.czy_udostepniony(state.auto_id)
        appbar = utils.zbuduj_pasek_z_powrotem(
            page, "Magazyn", "/", ikona=ft.Icons.INVENTORY_2,
            akcje_dodatkowe=[utils.przycisk_synchronizacji(page, utils.funkcja_szybkiej_synchronizacji(page, state.auto_id, "/magazyn"))] if wspolny_id else None
        )

        # --- ZMIENNE DLA GRUPOWEGO USUWANIA (wspólne dla obu zakładek) ---
        self.tryb_zaznaczania = False
        self.zaznaczone_id = set()
        self.tabela_cel = ""
        self.oryginalny_appbar = appbar
        self.karty_ref = {}
        self.uzyj_wirtualizacji = False
        # --------------------------------------

        zakladka = self.state.magazyn_zakladka

        def zmien_zakladke(idx):
            self.state.magazyn_zakladka = idx
            utils.przejdz(self._page, "/magazyn")

        elementy = [utils.segmented_control(
            page,
            [("Opony", 0, ft.Icons.TIRE_REPAIR), ("Części i płyny", 1, ft.Icons.HANDYMAN)],
            zakladka, zmien_zakladke
        )]

        if zakladka == 0:
            elementy.extend(self._buduj_opony())
            trasa_fab = "/magazyn/opony/nowy"
        else:
            elementy.extend(self._buduj_czesci())
            trasa_fab = "/magazyn/czesci/nowa"

        elementy.append(utils.dol_bezpieczny(10))

        fab = utils.fab_animowany(ft.Icons.ADD, lambda e: utils.przejdz(self._page, trasa_fab))

        super().__init__(
            route="/magazyn",
            padding=15,
            appbar=appbar,
            floating_action_button=fab,
            spacing=15,
            controls=elementy,          # lub self.elementy, w zależności jak masz w tym pliku
            scroll=ft.ScrollMode.AUTO,  # włączasz natywne przewijanie
        )
        
    def potwierdz_grupowe_usuwanie(self, e):
        ile = len(self.zaznaczone_id)
        tabela = self.tabela_cel

        def wykonaj():
            if tabela == "magazyn_czesci":
                wynik = db.usun_wiele_czesci_magazynu_z_cofnieciem(list(self.zaznaczone_id))
            else:
                wynik = db.usun_wiele_z_cofnieciem(tabela, list(self.zaznaczone_id))
            self.zakoncz_zaznaczanie()
            utils.przejdz(self._page, "/magazyn")
            utils.pokaz_komunikat_cofnij(self._page, f"Usunięto {ile} elementów.", wynik)

        utils.potwierdz(self._page, "Usuwanie", f"Czy na pewno chcesz usunąć {ile} zaznaczonych elementów?", wykonaj)
    # ============== ZAKŁADKA: OPONY ==============
    def _buduj_opony(self):
        elementy = []
        with db.polacz_baze() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT id, sezon, rozmiar, marka_model, glebokosc_bieznika, data_pomiaru, numer_dot, ilosc, zamontowane, cena, os_montazu, zalacznik "
                "FROM zestawy_opon WHERE auto_id=? ORDER BY zamontowane DESC, sezon",
                (self.state.auto_id,)
            )
            zestawy = c.fetchall()

        if not zestawy:
            elementy.append(ft.Text("Brak zapisanych zestawów opon. Kliknij + poniżej, aby dodać pierwszy zestaw.", color=ft.Colors.ON_SURFACE_VARIANT))
            return elementy

        sort_opcje = [
            ("Zamontowane", "zamontowane", lambda x: int(x[8] or 0)),
            ("Sezon", "sezon", lambda x: str(x[1]).lower()),
            ("Bieżnik", "bieznik", lambda x: float(x[4] or 0)),
        ]
        sort_ui = utils.przycisk_sortowania(self._page, self.state, "zestawy_opon", sort_opcje)
        filtr_sezon_ui = utils.przycisk_filtrowania_kategoria(self._page, self.state, "opony_sezon", zestawy, 1, "Sezon")
        
        elementy.append(ft.Row([sort_ui, filtr_sezon_ui], spacing=6, scroll=ft.ScrollMode.HIDDEN))

        def filtruj_opony(e):
            zapytanie = e.control.value.lower().strip()
            self.lista_kart_opony.controls.clear()
            for k in self.wszystkie_karty_opony:
                if zapytanie in k["szukaj"]:
                    self.lista_kart_opony.controls.append(k["karta"])
            self.update()

        elementy.append(
            ft.TextField(
                hint_text="Szukaj opon (sezon, rozmiar, marka, DOT)...",
                prefix_icon=ft.Icons.SEARCH,
                on_change=utils.z_opoznieniem(self._page, filtruj_opony),
                **utils.styl_pola()
            )
        )
        self.lista_kart_opony = ft.ListView(spacing=15, padding=0, height=utils.wysokosc_listy(self._page), auto_scroll=False)
        self.wszystkie_karty_opony = []
        self.uzyj_wirtualizacji = True

        zestawy = utils.filtruj_po_kategorii(zestawy, self.state, "opony_sezon", 1)
        utils.posortuj_liste(zestawy, self.state, "zestawy_opon", sort_opcje)

        for z in zestawy:
            karta = self._karta_zestawu(z)
            z_id, sezon, rozmiar, marka, glebokosc, data_pomiaru, dot, ilosc, zamontowane, cena, os_montazu, zalacznik = z
            tekst_szukaj = f"{sezon} {rozmiar} {marka} {dot} {cena}".lower()
            self.wszystkie_karty_opony.append({"karta": karta, "szukaj": tekst_szukaj})
            self.lista_kart_opony.controls.append(karta)

        elementy.append(self.lista_kart_opony)
        return elementy

    def _karta_zestawu(self, z):
        z_id, sezon, rozmiar, marka, glebokosc, data_pomiaru, dot, ilosc, zamontowane, cena, os_montazu, zalacznik = z
        ikona_sezonu = IKONY_SEZONU.get(sezon, ft.Icons.TIRE_REPAIR)

        if glebokosc is not None and str(glebokosc) != "":
            try:
                g = float(glebokosc)
                if g < 1.6:
                    kol_gl = ft.Colors.RED_700
                elif g < 3.0:
                    kol_gl = ft.Colors.ORANGE_700
                else:
                    kol_gl = ft.Colors.GREEN_700
                tekst_gl = f"{utils.formatuj_liczba(g, 1)} mm"
            except (TypeError, ValueError):
                kol_gl = ft.Colors.ON_SURFACE_VARIANT
                tekst_gl = "-"
        else:
            kol_gl = ft.Colors.ON_SURFACE_VARIANT
            tekst_gl = "brak pomiaru"

        podtytul_bits = [str(x) for x in (rozmiar, marka) if x]
        podtytul = "  |  ".join(podtytul_bits) if podtytul_bits else "Brak danych o rozmiarze / marce"

        dot_tekst = str(dot) if dot else "-"
        interpretacja = interpretuj_dot(dot)
        if interpretacja:
            dot_tekst += f" ({interpretacja})"

        if zamontowane:
            etykieta_osi = f" ({os_montazu})" if os_montazu and os_montazu != "Wszystkie" else ""
            znacznik = ft.Container(
                padding=8, border_radius=20, bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.GREEN),
                content=ft.Text(f"Na aucie{etykieta_osi}", size=11, weight="bold", color=ft.Colors.GREEN_700)
            )
        else:
            znacznik = ft.Container(
                padding=8, border_radius=20, bgcolor=ft.Colors.with_opacity(0.10, ft.Colors.ON_SURFACE),
                content=ft.Text("W magazynie", size=11, weight="bold", color=ft.Colors.ON_SURFACE_VARIANT)
            )

        stopka = f"Ilość: {ilosc or 4} szt."
        if cena is not None and str(cena).strip():
            stopka += f"  |  Cena: {utils.formatuj_liczba(cena)}  {utils.symbol_waluty()}"
        if data_pomiaru:
            stopka += f"\nPomiar bieżnika: {data_pomiaru}"

        karta, kontener = utils.karta_listy(
            ft.Column([
                ft.Row([
                    utils.wskaznik_zalacznika(self._page, zalacznik, "Zestaw opon") if zalacznik else ft.Container(),
                    ft.Row([
                        ft.Icon(ikona_sezonu, size=17, color=ft.Colors.PRIMARY),
                        ft.Text(str(sezon), weight="bold", size=16, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                    ], spacing=6, expand=True),
                    znacznik,
                ], spacing=6),
                ft.Text(podtytul, size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Row([
                    ft.Text("Bieżnik:", size=13, weight="bold"),
                    ft.Text(tekst_gl, size=13, weight="bold", color=kol_gl),
                    ft.Text(f"|  DOT: {dot_tekst}", size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                ], spacing=6),
                ft.Text(stopka, size=12, color=ft.Colors.ON_SURFACE_VARIANT),
            ], spacing=4),
            kolor_paska=kol_gl if (glebokosc is not None and str(glebokosc) != "") else None,
            page=self._page,
        )

        self.karty_ref[z_id] = kontener
        self.podepnij_zdarzenia_grupowe(kontener, z_id, lambda zid=z_id, zsez=sezon, zzal=zalacznik: self._pokaz_menu(zid, zsez, zzal), "zestawy_opon")

        return karta

    def _pokaz_menu(self, zid, sezon, zalacznik=None):
        def zamontuj(os):
            db.oznacz_zamontowany_zestaw(self.state.auto_id, zid, os)
            utils.przejdz(self._page, "/magazyn")
            etykieta = {"Wszystkie": "na całym aucie", "Przód": "na przedniej osi", "Tył": "na tylnej osi"}[os]
            utils.pokaz_komunikat(self._page, f"Zestaw „{sezon}” oznaczono jako zamontowany {etykieta}.")

        def usun_zestaw():
            def wykonaj():
                wynik = db.usun_z_cofnieciem("zestawy_opon", zid)
                utils.przejdz(self._page, "/magazyn")
                utils.pokaz_komunikat_cofnij(self._page, "Usunięto zestaw opon.", wynik)
            utils.potwierdz(self._page, "Usunąć?", f"Czy na pewno usunąć zestaw „{sezon}”?", wykonaj)

        async def dodaj_zmien_zdj():
            await utils.szybkie_dodanie_zdjecia(self._page, "zestawy_opon", zid, zalacznik, lambda: utils.przejdz(self._page, "/magazyn"))

        pozycje_menu = []
        if zalacznik:
            pozycje_menu.append({"ikona": ft.Icons.IMAGE, "tekst": "Pokaż zdjęcie", "akcja": lambda: utils.pokaz_podglad_zalacznika(self._page, zalacznik, "Zestaw opon")})
            pozycje_menu.append({"ikona": ft.Icons.EDIT_DOCUMENT, "tekst": "Zmień zdjęcie", "akcja": dodaj_zmien_zdj})
        else:
            pozycje_menu.append({"ikona": ft.Icons.ADD_A_PHOTO, "tekst": "Dodaj zdjęcie (faktura/opona)", "akcja": dodaj_zmien_zdj})

        pozycje_menu.extend([
            {"ikona": ft.Icons.CHECK_CIRCLE, "tekst": "Zamontuj na całym aucie", "akcja": lambda: zamontuj("Wszystkie"), "kolor": ft.Colors.GREEN},
            {"ikona": ft.Icons.ARROW_UPWARD, "tekst": "Zamontuj tylko na przedniej osi", "akcja": lambda: zamontuj("Przód"), "kolor": ft.Colors.GREEN},
            {"ikona": ft.Icons.ARROW_DOWNWARD, "tekst": "Zamontuj tylko na tylnej osi", "akcja": lambda: zamontuj("Tył"), "kolor": ft.Colors.GREEN},
            {"ikona": ft.Icons.EDIT, "tekst": "Edytuj zestaw", "akcja": lambda: utils.przejdz(self._page, f"/magazyn/opony/edytuj/{zid}")},
            {"ikona": ft.Icons.DELETE, "tekst": "Usuń zestaw", "akcja": usun_zestaw, "kolor": ft.Colors.RED}
        ])

        utils.pokaz_menu_kontekstowe(self._page, f"Zestaw: {sezon}", pozycje_menu)

    # ============== ZAKŁADKA: CZĘŚCI I PŁYNY ==============
    def _buduj_czesci(self):
        elementy = []
        with db.polacz_baze() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT id, nazwa, kategoria, ilosc, jednostka, cena, data_zakupu, notatki, zalacznik, prog_ostrzezenia "
                "FROM magazyn_czesci WHERE auto_id=? ORDER BY nazwa",
                (self.state.auto_id,)
            )
            czesci = c.fetchall()

        if not czesci:
            elementy.append(ft.Text("Brak części i płynów w magazynie. Kliknij + poniżej, aby dodać pierwszą pozycję.", color=ft.Colors.ON_SURFACE_VARIANT))
            return elementy

        sort_opcje = [
            ("Nazwa", "nazwa", lambda x: str(x[1]).lower()),
            ("Ilość", "ilosc", lambda x: float(x[3] or 0)),
            ("Kategoria", "kategoria", lambda x: str(x[2] or "").lower()),
        ]
        sort_ui = utils.przycisk_sortowania(self._page, self.state, "magazyn_czesci", sort_opcje)
        filtr_kat_ui = utils.przycisk_filtrowania_kategoria(self._page, self.state, "magazyn_kategoria", czesci, 2, "Kategoria")

        elementy.append(ft.Row([sort_ui, filtr_kat_ui], spacing=6, scroll=ft.ScrollMode.HIDDEN))

        def filtruj_czesci(e):
            zapytanie = e.control.value.lower().strip()
            self.lista_kart_czesci.controls.clear()
            for k in self.wszystkie_karty_czesci:
                if zapytanie in k["szukaj"]:
                    self.lista_kart_czesci.controls.append(k["karta"])
            self.update()

        elementy.append(
            ft.TextField(
                hint_text="Szukaj części (nazwa, kategoria)...",
                prefix_icon=ft.Icons.SEARCH,
                on_change=utils.z_opoznieniem(self._page, filtruj_czesci),
                **utils.styl_pola()
            )
        )
        self.lista_kart_czesci = ft.ListView(spacing=15, padding=0, height=utils.wysokosc_listy(self._page), auto_scroll=False)
        self.wszystkie_karty_czesci = []
        self.uzyj_wirtualizacji = True

        czesci = utils.filtruj_po_kategorii(czesci, self.state, "magazyn_kategoria", 2)
        utils.posortuj_liste(czesci, self.state, "magazyn_czesci", sort_opcje)

        for cz in czesci:
            karta = self._karta_czesci(cz)
            c_id, nazwa, kategoria, ilosc, jednostka, cena, data_zakupu, notatki, zalacznik, prog_ostrzezenia = cz
            tekst_szukaj = f"{nazwa} {kategoria} {notatki}".lower()
            self.wszystkie_karty_czesci.append({"karta": karta, "szukaj": tekst_szukaj})
            self.lista_kart_czesci.controls.append(karta)

        elementy.append(self.lista_kart_czesci)
        return elementy

    def _karta_czesci(self, cz):
        c_id, nazwa, kategoria, ilosc, jednostka, cena, data_zakupu, notatki, zalacznik, prog_ostrzezenia = cz
        ikona = IKONY_KATEGORII_MAGAZYNU.get(kategoria, ft.Icons.BUILD)

        try:
            ilosc_f = float(ilosc or 0)
        except (TypeError, ValueError):
            ilosc_f = 0.0
        try:
            prog_f = float(prog_ostrzezenia) if prog_ostrzezenia is not None else db.PROG_ILOSC_MAGAZYNU_DOMYSLNY
        except (TypeError, ValueError):
            prog_f = db.PROG_ILOSC_MAGAZYNU_DOMYSLNY

        jednostka = jednostka or "szt"
        if ilosc_f <= 0:
            kolor_stan = ft.Colors.RED_700
        elif ilosc_f <= prog_f:
            kolor_stan = ft.Colors.ORANGE_700
        else:
            kolor_stan = ft.Colors.GREEN_700
        tekst_stan = f"{utils.formatuj_liczba(ilosc_f, 2)} {jednostka}" if ilosc_f > 0 else "Brak na stanie"

        znacznik = ft.Container(
            padding=8, border_radius=20,
            bgcolor=ft.Colors.with_opacity(0.15, kolor_stan),
            content=ft.Text(tekst_stan, size=11, weight="bold", color=kolor_stan)
        )

        stopka_bits = []
        if cena is not None and str(cena).strip():
            stopka_bits.append(f"Cena: {utils.formatuj_liczba(cena)} {utils.symbol_waluty()}")
        if data_zakupu:
            stopka_bits.append(f"Zakup: {data_zakupu}")

        tresc = [
            ft.Row([
                utils.wskaznik_zalacznika(self._page, zalacznik, "Część/płyn") if zalacznik else ft.Container(),
                ft.Row([
                    ft.Icon(ikona, size=17, color=ft.Colors.PRIMARY),
                    ft.Text(str(nazwa), weight="bold", size=16, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                ], spacing=6, expand=True),
                znacznik,
            ], spacing=6),
            ft.Text(str(kategoria) if kategoria else "Bez kategorii", size=13, color=ft.Colors.ON_SURFACE_VARIANT),
        ]
        if stopka_bits:
            tresc.append(ft.Text("  |  ".join(stopka_bits), size=12, color=ft.Colors.ON_SURFACE_VARIANT))

        karta, kontener = utils.karta_listy(
            ft.Column(tresc, spacing=4), kolor_paska=kolor_stan, page=self._page
        )

        self.karty_ref[c_id] = kontener
        self.podepnij_zdarzenia_grupowe(kontener, c_id, lambda cid=c_id, cn=nazwa, czal=zalacznik: self._pokaz_menu_czesci(cid, cn, czal), "magazyn_czesci")

        return karta

    def _pokaz_menu_czesci(self, cid, nazwa, zalacznik=None):
        def usun_czesc():
            def wykonaj():
                wynik = db.usun_czesc_magazynu_z_cofnieciem(cid)   # było: db.usun_z_cofnieciem("magazyn_czesci", cid)
                utils.przejdz(self._page, "/magazyn")
                utils.pokaz_komunikat_cofnij(self._page, f"Usunięto '{nazwa}'.", wynik)
            utils.potwierdz(self._page, "Usunąć?", f"Czy na pewno usunąć pozycję „{nazwa}”?", wykonaj)

        async def dodaj_zmien_zdj():
            await utils.szybkie_dodanie_zdjecia(self._page, "magazyn_czesci", cid, zalacznik, lambda: utils.przejdz(self._page, "/magazyn"))

        pozycje_menu = []
        if zalacznik:
            pozycje_menu.append({"ikona": ft.Icons.IMAGE, "tekst": "Pokaż zdjęcie", "akcja": lambda: utils.pokaz_podglad_zalacznika(self._page, zalacznik, "Część/płyn")})
            pozycje_menu.append({"ikona": ft.Icons.EDIT_DOCUMENT, "tekst": "Zmień zdjęcie", "akcja": dodaj_zmien_zdj})
        else:
            pozycje_menu.append({"ikona": ft.Icons.ADD_A_PHOTO, "tekst": "Dodaj zdjęcie (faktura/część)", "akcja": dodaj_zmien_zdj})

        pozycje_menu.extend([
            {"ikona": ft.Icons.EDIT, "tekst": "Edytuj pozycję", "akcja": lambda: utils.przejdz(self._page, f"/magazyn/czesci/edytuj/{cid}")},
            {"ikona": ft.Icons.DELETE, "tekst": "Usuń pozycję", "akcja": usun_czesc, "kolor": ft.Colors.RED}
        ])

        utils.pokaz_menu_kontekstowe(self._page, f"Pozycja: {nazwa}", pozycje_menu)

class FormularzOponyView(ft.View):
    def __init__(self, page: ft.Page, state, zestaw_id=None):
        self._page = page
        self.state = state
        self.zestaw_id = zestaw_id

        sezon_val, rozmiar_val, marka_val = SEZONY[0], "", ""
        gl_val, dp_val, dot_val, il_val = "", "", "", "4"
        zam_val, dz_val, pz_val, cena_val, not_val = False, "", "", "", ""
        os_val = "Wszystkie"
        self.zalacznik_val = None

        if zestaw_id:
            with db.polacz_baze() as conn:
                c = conn.cursor()
                c.execute(
                    "SELECT sezon, rozmiar, marka_model, glebokosc_bieznika, data_pomiaru, numer_dot, "
                    "ilosc, zamontowane, data_zakupu, przebieg_zakupu, cena, notatki, os_montazu, zalacznik FROM zestawy_opon WHERE id=?",
                    (zestaw_id,)
                )
                w = c.fetchone()
                if w:
                    sezon_val = str(w[0] or SEZONY[0])
                    rozmiar_val = str(w[1] or "")
                    marka_val = str(w[2] or "")
                    gl_val = str(w[3] or "")
                    dp_val = str(w[4] or "")
                    dot_val = str(w[5] or "")
                    il_val = str(w[6] or "4")
                    zam_val = bool(w[7])
                    dz_val = str(w[8] or "")
                    pz_val = str(w[9] or "")
                    cena_val = str(w[10] or "")
                    not_val = str(w[11] or "")
                    os_val = str(w[12] or "Wszystkie")
                    self.zalacznik_val = w[13] if len(w) > 13 else None

        self.k_zalacznik, self.get_zalacznik = utils.komponent_zalacznika(page, self.zalacznik_val)
        self.e_sezon = ft.Dropdown(label="Sezon", options=[ft.DropdownOption(key=s, text=f"{IKONY_SEZONU[s]} {s}") for s in SEZONY], value=sezon_val, **utils.styl_dropdown())
        self.e_rozmiar = ft.TextField(label="Rozmiar (np. 205/55 R16)", value=rozmiar_val, **utils.styl_pola())
        self.e_marka = ft.TextField(label="Marka / model opony", value=marka_val, **utils.styl_pola())
        
        self.e_gl = ft.TextField(label="Głębokość bieżnika (mm)", value=gl_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola())
        self.e_dp = utils.pole_daty(page, "Data pomiaru bieżnika", dp_val)
        self.e_dot = ft.TextField(label="Numer DOT (np. 2321 = tydz. 23 / 2021)", value=dot_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola())
        self.e_il = ft.TextField(label="Ilość opon w zestawie", value=il_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola())
        self.e_zam = ft.Checkbox(label="Ten zestaw jest aktualnie zamontowany na aucie", value=zam_val)
        self.e_os = ft.Dropdown(
            label="Na jakiej osi",
            options=[ft.DropdownOption(key=o, text=o) for o in db.OSIE_MONTAZU],
            value=os_val,
            visible=zam_val,
            **utils.styl_dropdown()
        )

        def _przelacz_os(e):
            self.e_os.visible = self.e_zam.value
            self.e_os.update()

        self.e_zam.on_change = _przelacz_os
        
        self.e_dz = utils.pole_daty(page, "Data zakupu", dz_val)
        self.e_pz = ft.TextField(label="Przebieg przy zakupie (km)", value=pz_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola())
        self.e_cena = ft.TextField(label=f"Koszt zakupu ({utils.symbol_waluty()})", value=cena_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola())
        self.e_not = ft.TextField(label="Dodatkowe notatki", value=not_val, multiline=True, min_lines=2, max_lines=4, **utils.styl_pola())

        self._stan_poczatkowy = self._migawka_formularza()
        appbar = utils.zbuduj_pasek_z_powrotem(page, "Edycja zestawu opon" if zestaw_id else "Nowy zestaw opon", "/magazyn", on_save=self.zapisz, czy_zmieniono=self._czy_zmieniono)
        
        k1 = utils.karta_formularza([self.e_sezon, self.e_rozmiar, self.e_marka], "Specyfikacja opony", ft.Icons.INFO_OUTLINE, domyslnie_otwarte=True)
        k2 = utils.karta_formularza([self.e_gl, self.e_dp, self.e_dot, self.e_il, self.e_zam, self.e_os], "Stan i pomiary", ft.Icons.SEARCH)
        k3 = utils.karta_formularza([self.e_dz, self.e_pz, self.e_cena, self.e_not], "Zakup i uwagi", ft.Icons.SHOPPING_CART)
        k4 = utils.karta_formularza([self.k_zalacznik], "Załącznik (paragon / zdjęcie)", ft.Icons.ATTACH_FILE)
        
        elementy = [k1, k2, k3, k4, utils.przyciski_akcji(page, "Zapisz zestaw", self.zapisz, "/magazyn")]

        super().__init__(
            route=f"/magazyn/opony/edytuj/{zestaw_id}" if zestaw_id else "/magazyn/opony/nowy",
            padding=15, 
            spacing=15, 
            appbar=appbar, 
            controls=elementy, 
            scroll=ft.ScrollMode.AUTO
        )

    def _migawka_formularza(self):
        return (self.e_sezon.value, self.e_rozmiar.value, self.e_marka.value, self.e_gl.value,
                self.e_dp.value, self.e_dot.value, self.e_il.value, self.e_zam.value, self.e_os.value,
                self.e_dz.value, self.e_pz.value, self.e_cena.value, self.e_not.value)

    def _czy_zmieniono(self):
        return self._migawka_formularza() != self._stan_poczatkowy

    def zapisz(self, e):
        for pole in (self.e_gl, self.e_il, self.e_cena):
            pole.error_text = None

        bledy = []

        glebokosc = None
        if (self.e_gl.value or "").strip():
            glebokosc = utils.parsuj_float(self.e_gl.value, None)
            if glebokosc is None or glebokosc < 0 or glebokosc > 15:
                bledy.append((self.e_gl, "Podaj sensowną głębokość (0–15 mm)"))

        ilosc = utils.parsuj_int(self.e_il.value, 4) or 4
        if ilosc <= 0 or ilosc > 8:
            bledy.append((self.e_il, "Podaj sensowną ilość opon (1–8)"))

        cena = None
        if (self.e_cena.value or "").strip():
            cena = utils.parsuj_float(self.e_cena.value, None)
            if cena is not None and cena < 0:
                bledy.append((self.e_cena, "Cena nie może być ujemna"))

        if bledy:
            return utils.pokaz_bledy_formularza(self._page, bledy)

        bieznik_nizki = glebokosc is not None and glebokosc < 1.6

        dot = (self.e_dot.value or "").strip()
        przebieg_zakupu = utils.parsuj_int(self.e_pz.value, None) if (self.e_pz.value or "").strip() else None
        nowy_id = self.zestaw_id
        
        przygotowany = db.przygotuj_nowy_zalacznik(self.get_zalacznik())
        nowy_zalacznik = przygotowany if przygotowany is not None else self.zalacznik_val

        with db.polacz_baze() as conn:
            cur = conn.cursor()
            if self.zestaw_id:
                cur.execute(
                    "UPDATE zestawy_opon SET sezon=?, rozmiar=?, marka_model=?, glebokosc_bieznika=?, "
                    "data_pomiaru=?, numer_dot=?, ilosc=?, data_zakupu=?, przebieg_zakupu=?, cena=?, notatki=?, zalacznik=? WHERE id=?",
                    (self.e_sezon.value, self.e_rozmiar.value, self.e_marka.value, glebokosc,
                    self.e_dp.value, dot, ilosc, self.e_dz.value, przebieg_zakupu, cena, self.e_not.value, nowy_zalacznik,
                    self.zestaw_id)
                )
            else:
                cur.execute(
                    "INSERT INTO zestawy_opon (auto_id, sezon, rozmiar, marka_model, glebokosc_bieznika, "
                    "data_pomiaru, numer_dot, ilosc, zamontowane, data_zakupu, przebieg_zakupu, cena, notatki, zalacznik) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (self.state.auto_id, self.e_sezon.value, self.e_rozmiar.value, self.e_marka.value,
                    glebokosc, self.e_dp.value, dot, ilosc, 0, self.e_dz.value, przebieg_zakupu, cena, self.e_not.value, nowy_zalacznik)
                )
                nowy_id = cur.lastrowid
        db.zatwierdz_zalacznik(self.zalacznik_val, przygotowany)

        if self.e_zam.value and nowy_id:
            db.oznacz_zamontowany_zestaw(self.state.auto_id, nowy_id, self.e_os.value)
        elif self.zestaw_id and not self.e_zam.value:
            with db.polacz_baze() as conn:
                conn.execute("UPDATE zestawy_opon SET zamontowane=0 WHERE id=?", (self.zestaw_id,))

        utils.przejdz(self._page, "/magazyn")
        if bieznik_nizki:
            utils.pokaz_komunikat(
                self._page,
                "Zapisano zestaw opon! Uwaga: głębokość bieżnika poniżej ustawowego minimum (1.6 mm).",
                ft.Colors.ORANGE_700
            )
        else:
            utils.pokaz_komunikat(self._page, "Zapisano zestaw opon!")


class FormularzCzesciView(ft.View):
    def __init__(self, page: ft.Page, state, czesc_id=None):
        self._page = page
        self.state = state
        self.czesc_id = czesc_id

        nazwa_val, kat_val, il_val, jedn_val = "", db.KATEGORIE_MAGAZYNU[0], "1", "szt"
        cena_val, data_val, not_val = "", "", ""
        prog_val = "1"
        self.zalacznik_val = None

        if czesc_id:
            with db.polacz_baze() as conn:
                c = conn.cursor()
                c.execute(
                    "SELECT nazwa, kategoria, ilosc, jednostka, cena, data_zakupu, notatki, zalacznik, prog_ostrzezenia "
                    "FROM magazyn_czesci WHERE id=?", (czesc_id,)
                )
                w = c.fetchone()
                if w:
                    nazwa_val = str(w[0] or "")
                    kat_val = str(w[1] or db.KATEGORIE_MAGAZYNU[0])
                    il_val = str(w[2]) if w[2] is not None else "1"
                    jedn_val = str(w[3] or "szt")
                    cena_val = str(w[4]) if w[4] not in (None, "") else ""
                    data_val = str(w[5] or "")
                    not_val = str(w[6] or "")
                    self.zalacznik_val = w[7] if len(w) > 7 else None
                    prog_val = str(w[8]) if len(w) > 8 and w[8] is not None else "1"

        self.k_zalacznik, self.get_zalacznik = utils.komponent_zalacznika(page, self.zalacznik_val)
        self.e_nazwa = ft.TextField(label="Nazwa*", value=nazwa_val, hint_text="np. Olej 5W-30, żarówka H7", **utils.styl_pola())
        self.e_kat = ft.Dropdown(
            label="Kategoria",
            options=[ft.DropdownOption(key=k, text=k) for k in db.KATEGORIE_MAGAZYNU],
            value=kat_val, **utils.styl_dropdown()
        )
        self.e_ilosc = ft.TextField(label="Ilość na stanie", value=il_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola())
        self.e_jedn = ft.Dropdown(
            label="Jednostka",
            options=[ft.DropdownOption(key=j, text=j) for j in db.JEDNOSTKI_MAGAZYNU],
            value=jedn_val, **utils.styl_dropdown()
        )
        self.e_prog = ft.TextField(
            label="Próg niskiego stanu (ostrzegaj poniżej)", value=prog_val, hint_text="np. 1",
            keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola()
        )
        self.e_cena = ft.TextField(label=f"Koszt zakupu ({utils.symbol_waluty()}, opcjonalnie)", value=cena_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola())
        self.e_data = utils.pole_daty(page, "Data zakupu", data_val)
        self.e_not = ft.TextField(label="Notatki", value=not_val, multiline=True, min_lines=2, max_lines=4, **utils.styl_pola())

        self._stan_poczatkowy = self._migawka_formularza()
        appbar = utils.zbuduj_pasek_z_powrotem(page, "Edycja pozycji" if czesc_id else "Nowa część / płyn", "/magazyn", on_save=self.zapisz, czy_zmieniono=self._czy_zmieniono)

        wiersz_ilosc = ft.Row([ft.Container(self.e_ilosc, expand=True), ft.Container(self.e_jedn, expand=True)], spacing=10)

        k1 = utils.karta_formularza([self.e_nazwa, self.e_kat], "Co to jest", ft.Icons.INVENTORY_2, domyslnie_otwarte=True)
        k2 = utils.karta_formularza([wiersz_ilosc, self.e_prog], "Stan magazynowy", ft.Icons.NUMBERS)
        k3 = utils.karta_formularza([self.e_cena, self.e_data, self.e_not], "Zakup i uwagi", ft.Icons.SHOPPING_CART)
        k4 = utils.karta_formularza([self.k_zalacznik], "Załącznik (paragon / zdjęcie)", ft.Icons.ATTACH_FILE)

        elementy = [k1, k2, k3, k4, utils.przyciski_akcji(page, "Zapisz pozycję", self.zapisz, "/magazyn")]

        super().__init__(
            route=f"/magazyn/czesci/edytuj/{czesc_id}" if czesc_id else "/magazyn/czesci/nowa",
            padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO
        )

    def _migawka_formularza(self):
        return (self.e_nazwa.value, self.e_kat.value, self.e_ilosc.value, self.e_jedn.value,
                self.e_prog.value, self.e_cena.value, self.e_data.value, self.e_not.value)

    def _czy_zmieniono(self):
        return self._migawka_formularza() != self._stan_poczatkowy

    def zapisz(self, e):
        for pole in (self.e_nazwa, self.e_ilosc, self.e_cena, self.e_prog):
            pole.error_text = None

        # Wpisanie innego wariantu zapisu ("filtr Oleju ") nie zakłada nowej
        # pozycji — nazwa wraca w pisowni tej, która już jest w magazynie.
        # Ten sam mechanizm, co przy podpowiadaniu stacji paliw.
        nazwa = db.dopasuj_istniejaca_nazwe(self.state.auto_id, "magazyn_czesci", self.e_nazwa.value)
        bledy = []
        if not nazwa:
            bledy.append((self.e_nazwa, "Podaj nazwę"))

        ilosc = utils.parsuj_float(self.e_ilosc.value, None)
        if ilosc is None or ilosc < 0:
            bledy.append((self.e_ilosc, "Podaj poprawną ilość"))

        cena = None
        if (self.e_cena.value or "").strip():
            cena = utils.parsuj_float(self.e_cena.value, None)
            if cena is not None and cena < 0:
                bledy.append((self.e_cena, "Cena nie może być ujemna"))

        prog = utils.parsuj_float(self.e_prog.value, 1.0)
        if prog < 0:
            bledy.append((self.e_prog, "Próg nie może być ujemny"))

        if bledy:
            return utils.pokaz_bledy_formularza(self._page, bledy)

        przygotowany = db.przygotuj_nowy_zalacznik(self.get_zalacznik())
        nowy_zalacznik = przygotowany if przygotowany is not None else self.zalacznik_val

        with db.polacz_baze() as conn:
            if self.czesc_id:
                conn.execute(
                    "UPDATE magazyn_czesci SET nazwa=?, kategoria=?, ilosc=?, jednostka=?, cena=?, data_zakupu=?, notatki=?, zalacznik=?, prog_ostrzezenia=? WHERE id=?",
                    (nazwa, self.e_kat.value, ilosc, self.e_jedn.value, cena, self.e_data.value, self.e_not.value, nowy_zalacznik, prog, self.czesc_id)
                )
            else:
                conn.execute(
                    "INSERT INTO magazyn_czesci (auto_id, nazwa, kategoria, ilosc, jednostka, cena, data_zakupu, notatki, zalacznik, prog_ostrzezenia) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (self.state.auto_id, nazwa, self.e_kat.value, ilosc, self.e_jedn.value, cena, self.e_data.value, self.e_not.value, nowy_zalacznik, prog)
                )

        db.zatwierdz_zalacznik(self.zalacznik_val, przygotowany)

        utils.przejdz(self._page, "/magazyn")
        utils.pokaz_komunikat(self._page, "Zapisano pozycję magazynu!")