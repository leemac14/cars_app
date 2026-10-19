"""Rejestr karoserii: galeria zdjęć auta z mapą stref i parami „przed / po” oraz formularz
zdjęć. Dane: db/karoseria.py; kafle, mapa, porównanie i przeglądarka: utils/karoseria.py;
obchód aparatem: views/obchod_view.py."""

from datetime import datetime

import flet as ft

import db
import log
import utils
from date import na_iso

KLUCZ_FILTRA_STREFY = "karoseria_strefa"
KLUCZ_FILTRA_TYPU = "karoseria_typ"
KLUCZ_SORTOWANIA = "karoseria"


def _kolejnosc_strefy(strefa):
    try:
        return db.STREFY_KAROSERII.index(strefa)
    except ValueError:
        return len(db.STREFY_KAROSERII)


# Po dacie — sekcje miesięcy; po strefie — sekcje stref (utils.sekcje_galerii).
OPCJE_SORTOWANIA = [
    ("Data", "data", lambda z: (z["porzadek"], z["id"])),
    ("Strefa", "strefa", lambda z: (_kolejnosc_strefy(z["strefa"]), z["porzadek"], z["id"])),
]


class KaroseriaView(ft.View, utils.ZaznaczanieGrupowe):
    """Galeria przewija się razem z ekranem (dawniej siatka w okienku na pół ekranu urywała
    zdjęcia w połowie). Dotknięcie zdjęcia — przeglądarka, ⋮ — menu, przytrzymanie —
    zaznaczanie; filtry, sortowanie i mapa odświeżają ekran w miejscu."""

    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state
        appbar = utils.zbuduj_pasek_z_powrotem(page, "Rejestr karoserii", "/", ikona=ft.Icons.PHOTO_CAMERA)

        self.tryb_zaznaczania = False
        self.zaznaczone_id = set()
        self.tabela_cel = "zdjecia_karoserii"
        self.oryginalny_appbar = appbar
        self.karty_ref = {}
        self.zdjecia, self.po_filtrach, self.widoczne, self.pary = [], [], [], {}
        self.tresc = ft.Column(spacing=utils.SPACING["md"])
        self.galeria = ft.Column(spacing=utils.SPACING["lg"])
        self.pole_szukaj = ft.TextField(
            hint_text="Szukaj (strefa, opis, data)", prefix_icon=ft.Icons.SEARCH,
            on_change=utils.z_opoznieniem(page, self._szukaj), **utils.styl_pola(),
        )
        self.wiersz_szukaj = utils.na_cala_szerokosc(self.pole_szukaj)
        self.moge_dodawac = self.aparat = False

        if not state.auto_id:
            super().__init__(route="/karoseria", padding=15, spacing=15, appbar=appbar, controls=[
                utils.ekran_braku_danych(
                    ikona=ft.Icons.DIRECTIONS_CAR, tytul="Brak wybranego pojazdu",
                    opis="Dodaj pojazd, a potem dokumentuj zdjęciami stan lakieru, rysy i naprawy.",
                    tekst_przycisku="Dodaj pojazd", on_click=lambda e: utils.przejdz(self._page, "/auto/nowy"),
                )])
            return

        self.moge_dodawac = db.czy_moge_dodawac(state.auto_id)
        self.aparat = utils.aparat_dostepny(page)

        def tresc():
            self._przelicz()
            return self.tresc

        super().__init__(
            route="/karoseria", padding=15, appbar=appbar, floating_action_button=self._fab(),
            controls=[utils.zbuduj_etapami(
                page, utils.szkielet_ekranu(page, kafle=2, karty=3), tresc, widok=self,
            )],
            scroll=ft.ScrollMode.AUTO,
        )

    # ================= TREŚĆ =================

    def _fab(self):
        if not self.moge_dodawac:
            return None
        if not self.aparat:
            return utils.fab_animowany(ft.Icons.ADD_A_PHOTO, lambda e: utils.przejdz(self._page, "/karoseria/nowe"),
                                       tooltip="Dodaj zdjęcia")
        return utils.fab_speed_dial(self._page, [
            (ft.Icons.THREESIXTY, "Obchód auta aparatem", lambda e: utils.przejdz(self._page, "/karoseria/obchod")),
            (ft.Icons.PHOTO_LIBRARY, "Zdjęcia z galerii", lambda e: utils.przejdz(self._page, "/karoseria/nowe")),
        ], ikona_glowna=ft.Icons.ADD_A_PHOTO, tooltip="Dodaj zdjęcia")

    def _przelicz(self):
        """Dane, mapa, pary, filtry i galeria od nowa — przy wejściu i przy odświeżeniu w miejscu."""
        self.zdjecia = db.zdjecia_karoserii_pojazdu(self.state.auto_id)
        lista_par = db.pary_przed_po(self.zdjecia)
        self.pary = {z["id"]: para for para in lista_par for z in (para["przed"], para["po"])}
        if not self.zdjecia:
            self.karty_ref = {}
            self.tresc.controls = [self._pusto()]
            return

        sort_ui = utils.przycisk_sortowania(self._page, self.state, KLUCZ_SORTOWANIA, OPCJE_SORTOWANIA)
        chipy, po_filtrach = utils.pasek_filtrow(self._page, self.state, self.zdjecia, [
            ("kategoria", KLUCZ_FILTRA_STREFY, "strefa", "Strefa"),
            ("kategoria", KLUCZ_FILTRA_TYPU, "etykieta_typu", "Rodzaj"),
        ])
        self.po_filtrach = utils.posortuj_liste(list(po_filtrach), self.state, KLUCZ_SORTOWANIA, OPCJE_SORTOWANIA)
        aktywna = self.state.filtry.get(KLUCZ_FILTRA_STREFY)

        elementy = [utils.mapa_karoserii(
            self._page, db.podsumowanie_stref(self.zdjecia),
            aktywna=None if aktywna == utils.WSZYSTKO else aktywna, on_strefa=self._wybierz_strefe,
            moge_dodawac=self.moge_dodawac,
        )]
        if lista_par:
            elementy.append(utils.pasek_par_przed_po(self._page, lista_par, self._porownaj_pare))
        elementy += [
            ft.Row([sort_ui] + chipy, scroll=ft.ScrollMode.ADAPTIVE, spacing=8),
            self.wiersz_szukaj,
            self.galeria,
            utils.dol_bezpieczny(80),  # miejsce pod FAB-em
        ]
        self.tresc.controls = elementy
        self._uloz_galerie()

    def _uloz_galerie(self):
        zapytanie = (self.pole_szukaj.value or "").lower().strip()
        self.widoczne = [z for z in self.po_filtrach if zapytanie in z["szukaj"]]
        self.karty_ref = {}
        if not self.widoczne:
            self.galeria.controls = [self._brak_wynikow()]
            return
        po_dacie = utils.czy_po_dacie(self.state, KLUCZ_SORTOWANIA)
        self.galeria.controls = [
            utils.sekcja_galerii(tytul, opis, [self._kafel(z) for z in lista])
            for tytul, opis, lista in utils.sekcje_galerii(self.widoczne, po_dacie=po_dacie)
        ]

    def _kafel(self, z):
        kafel, nakladka = utils.kafel_zdjecia_karoserii(self._page, z, on_menu=lambda: self._menu(z))
        self.karty_ref[z["id"]] = nakladka
        if z["id"] in self.zaznaczone_id:
            nakladka.bgcolor = ft.Colors.with_opacity(0.15, ft.Colors.PRIMARY)
            nakladka.border = ft.Border.all(2, ft.Colors.PRIMARY)
        self.podepnij_zdarzenia_grupowe(nakladka, z["id"], lambda: self._otworz(z["id"]))
        return kafel

    def _pusto(self):
        if not self.moge_dodawac:
            return ft.Container(padding=30, content=ft.Column([
                utils.rysunek_pustego_stanu(ft.Icons.PHOTO_CAMERA),
                utils.podpis("Ten pojazd nie ma jeszcze zdjęć karoserii.", text_align=ft.TextAlign.CENTER),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12))
        ekran = utils.ekran_braku_danych(
            ikona=ft.Icons.PHOTO_CAMERA, tytul="Brak zdjęć karoserii",
            opis="Udokumentuj stan auta: przód, boki, tył i wnętrze. Zdjęcia „przed naprawą” i „po "
                 "naprawie” tej samej strefy same połączą się w pary do porównania.",
            tekst_przycisku="Obchód auta aparatem" if self.aparat else "Dodaj zdjęcia",
            ikona_przycisku=ft.Icons.THREESIXTY if self.aparat else ft.Icons.ADD_A_PHOTO,
            on_click=lambda e: utils.przejdz(self._page, "/karoseria/obchod" if self.aparat else "/karoseria/nowe"),
        )
        if self.aparat:
            ekran.content.controls.insert(len(ekran.content.controls) - 1, ft.TextButton(
                "Wybierz zdjęcia z galerii", icon=ft.Icons.PHOTO_LIBRARY,
                on_click=lambda e: utils.przejdz(self._page, "/karoseria/nowe"),
            ))
        return ekran

    def _brak_wynikow(self):
        return ft.Container(padding=ft.Padding(0, 16, 0, 16), content=ft.Column([
            utils.podpis("Żadne zdjęcie nie pasuje do filtrów i wyszukiwania.", text_align=ft.TextAlign.CENTER),
            ft.TextButton("Pokaż wszystkie zdjęcia", icon=ft.Icons.FILTER_ALT_OFF, on_click=self._wyczysc_filtry),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4))

    # ================= AKCJE =================

    def odswiez_w_miejscu(self):
        """Filtr, sortowanie, mapa i usunięcie (utils.odswiez_ekran): galeria liczy się od nowa,
        ekran zostaje w tym samym miejscu."""
        if not self.state.auto_id:
            utils.przejdz(self._page, "/karoseria")
            return
        self._przelicz()
        self.update()

    def _szukaj(self, e):
        self._uloz_galerie()
        try:
            self.galeria.update()
        except RuntimeError:
            log.polkniety("odświeżenie galerii karoserii po wyszukiwaniu")

    def _wyczysc_filtry(self, e=None):
        for klucz in (KLUCZ_FILTRA_STREFY, KLUCZ_FILTRA_TYPU):
            self.state.filtry[klucz] = utils.WSZYSTKO
        self.pole_szukaj.value = ""
        utils.odswiez_ekran(self._page)

    def _wybierz_strefe(self, strefa):
        """Strefa z mapy: ze zdjęciami — filtr (drugie dotknięcie go zdejmuje); bez zdjęć —
        formularz nowych zdjęć z tą strefą."""
        if not any(z["strefa"] == strefa for z in self.zdjecia):
            if self.moge_dodawac:
                self.state.karoseria_nowa_strefa = strefa
                utils.przejdz(self._page, "/karoseria/nowe")
            else:
                utils.pokaz_komunikat(self._page, f"{strefa}: brak zdjęć.", utils.KOLOR_STATUS["info"])
            return
        obecna = self.state.filtry.get(KLUCZ_FILTRA_STREFY)
        self.state.filtry[KLUCZ_FILTRA_STREFY] = utils.WSZYSTKO if obecna == strefa else strefa
        utils.wibracja(self._page, "wybor")
        utils.odswiez_ekran(self._page)

    def _otworz(self, zid):
        indeks = next((i for i, z in enumerate(self.widoczne) if z["id"] == zid), None)
        if indeks is not None:
            utils.pokaz_przegladarke_karoserii(self._page, self.widoczne, indeks, on_menu=self._menu, pary=self.pary)

    def _porownaj_pare(self, para):
        utils.porownaj_zdjecia_karoserii(self._page, para["przed"], para["po"])

    def _menu(self, z, przegladarka=None):
        """Menu zdjęcia — z kafla albo z przeglądarki (wtedy edycja i usunięcie najpierw ją zamykają)."""
        zid = z["id"]

        def zamknij_przegladarke():
            if przegladarka is not None:
                przegladarka.zamknij()

        def edytuj():
            zamknij_przegladarke()
            utils.przejdz(self._page, f"/karoseria/edytuj/{zid}")

        def usun():
            def wykonaj():
                zamknij_przegladarke()
                wynik = db.usun_z_cofnieciem("zdjecia_karoserii", zid)
                utils.odswiez_ekran(self._page)
                utils.pokaz_komunikat_cofnij(self._page, "Usunięto zdjęcie z rejestru.", wynik)
            utils.potwierdz(self._page, "Usunąć zdjęcie?", "Wpis i plik zdjęcia znikną z rejestru karoserii.", wykonaj)

        pozycje = []
        para = self.pary.get(zid)
        if para:
            pozycje.append({"ikona": ft.Icons.COMPARE, "tekst": "Porównaj przed i po", "czyta": True,
                            "akcja": lambda: self._porownaj_pare(para)})
        if przegladarka is None:
            pozycje += [
                {"ikona": ft.Icons.FULLSCREEN, "tekst": "Pełny ekran", "czyta": True, "akcja": lambda: self._otworz(zid)},
                {"ikona": ft.Icons.CHECKLIST, "tekst": "Wybierz do porównania", "czyta": True,
                 "akcja": lambda: self.wymus_tryb_zaznaczania(zid)},
            ]
        pozycje += [
            {"ikona": ft.Icons.EDIT, "tekst": "Edytuj wpis", "akcja": edytuj},
            {"ikona": ft.Icons.DELETE, "tekst": "Usuń zdjęcie", "akcja": usun,
             "kolor": utils.KOLOR_STATUS["destructive"]},
        ]
        utils.pokaz_menu_kontekstowe(self._page, f"{z['strefa']} · {z['data']}",
                                     utils.odsiej_akcje(self.state.auto_id, pozycje, "zdjecia_karoserii", zid))

    # ================= ZAZNACZANIE =================

    def wymus_tryb_zaznaczania(self, element_id):
        if element_id not in self.karty_ref:
            return
        self.tryb_zaznaczania = True
        self.zaznacz_odznacz(element_id, self.karty_ref[element_id])
        utils.pokaz_komunikat(self._page, "Zaznacz jeszcze jedno zdjęcie do porównania.", ft.Colors.PRIMARY)

    def aktualizuj_appbar_zaznaczania(self, dodatkowe_akcje=None):
        # Porównanie zostaje przy każdej roli — niczego nie zapisuje. Edycja
        # zbiorcza znika razem z koszem, bo przy podglądzie i tak nie ma czego
        # zapisać.
        extra = []
        if self.wolno_zmieniac_zaznaczone():
            extra.append(ft.IconButton(ft.Icons.EDIT, tooltip="Edytuj zaznaczone zbiorczo", on_click=self.edytuj_zaznaczone_zbiorczo))
        if len(self.zaznaczone_id) == 2:
            extra.append(ft.IconButton(ft.Icons.COMPARE, tooltip="Porównaj zaznaczone", on_click=self.otworz_porownanie))
        super().aktualizuj_appbar_zaznaczania(dodatkowe_akcje=extra)
        # Przy trzech akcjach „Zaznaczono: 2” nie mieści się na telefonie — „2 zdjęcia” tak.
        if isinstance(self.appbar.title, ft.Text):
            self.appbar.title.value = db.liczba_z_odmiana(len(self.zaznaczone_id), "zdjęcie", "zdjęcia", "zdjęć")
            try:
                self.update()
            except RuntimeError:
                log.polkniety("tytuł paska zaznaczania karoserii")

    def edytuj_zaznaczone_zbiorczo(self, e):
        ids = list(self.zaznaczone_id)
        ile = len(ids)
        BRAK_ZMIAN = "— Bez zmian —"

        e_strefa = ft.Dropdown(
            label="Strefa karoserii",
            options=[ft.DropdownOption(BRAK_ZMIAN)] + [ft.DropdownOption(s) for s in db.STREFY_KAROSERII],
            value=BRAK_ZMIAN,
            **utils.styl_dropdown()
        )
        e_typ = ft.Dropdown(
            label="Rodzaj zdjęcia",
            options=[ft.DropdownOption(BRAK_ZMIAN)] + [ft.DropdownOption(key=t, text=db.ETYKIETY_TYPOW_ZDJECIA[t])
                                                      for t in db.TYPY_ZDJECIA],
            value=BRAK_ZMIAN,
            **utils.styl_dropdown()
        )
        c_opis = ft.Checkbox(label="Zmień opis dla wszystkich zaznaczonych", value=False)
        e_opis = ft.TextField(label="Nowy opis", multiline=True, min_lines=2, max_lines=4, visible=False, **utils.styl_pola())

        def przelacz_opis(ev):
            e_opis.visible = c_opis.value
            e_opis.update()
        c_opis.on_change = przelacz_opis

        def zapisz(ev):
            strefa = e_strefa.value if e_strefa.value != BRAK_ZMIAN else None
            typ = e_typ.value if e_typ.value != BRAK_ZMIAN else None
            opis = e_opis.value if c_opis.value else None

            if strefa is None and typ is None and opis is None:
                utils.pokaz_komunikat(self._page, "Nie wybrano żadnej zmiany do zastosowania.", utils.KOLOR_STATUS["warning"])
                return

            db.aktualizuj_wiele_zdjec_karoserii(ids, strefa=strefa, typ_porownania=typ, opis=opis)
            utils.zamknij_dialog(self._page, dlg)
            self.zakoncz_zaznaczanie()
            utils.odswiez_ekran(self._page)
            utils.pokaz_komunikat(self._page, f"Zaktualizowano: {db.liczba_z_odmiana(ile, 'zdjęcie', 'zdjęcia', 'zdjęć')}.")

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row([ft.Icon(ft.Icons.EDIT, color=ft.Colors.PRIMARY), ft.Text(f"Edycja zbiorcza ({ile})", weight="bold", expand=True)], spacing=8),
            content=ft.Column([
                ft.Text("Zmień wybrane pola dla wszystkich zaznaczonych zdjęć naraz. Pozostaw „Bez zmian”, aby nie ruszać danego pola.", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                e_strefa,
                e_typ,
                c_opis,
                e_opis,
            ], tight=True, spacing=10, scroll=ft.ScrollMode.AUTO),
            actions=[
                ft.TextButton("Anuluj", on_click=lambda e2: utils.zamknij_dialog(self._page, dlg)),
                ft.Button("Zapisz", on_click=zapisz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY)
            ],
            actions_alignment=ft.MainAxisAlignment.END
        )
        utils.otworz_dialog(self._page, dlg)

    def potwierdz_grupowe_usuwanie(self, e):
        ile = len(self.zaznaczone_id)

        def wykonaj():
            wynik = db.usun_wiele_z_cofnieciem(self.tabela_cel, list(self.zaznaczone_id))
            self.zakoncz_zaznaczanie()
            utils.odswiez_ekran(self._page)
            utils.pokaz_komunikat_cofnij(self._page, f"Usunięto: {db.liczba_z_odmiana(ile, 'zdjęcie', 'zdjęcia', 'zdjęć')}.", wynik)

        utils.potwierdz(self._page, "Usuwanie grupowe", f"Czy na pewno usunąć zaznaczone ({ile})?", wykonaj)

    def otworz_porownanie(self, e):
        wybrane = [z for z in self.zdjecia if z["id"] in self.zaznaczone_id]
        if len(wybrane) != 2:
            return
        self.zakoncz_zaznaczanie()
        utils.porownaj_zdjecia_karoserii(self._page, *wybrane)


class FormularzZdjecieKaroseriiView(ft.View):
    def __init__(self, page: ft.Page, state, wpis_id=None):
        self._page = page
        self.state = state
        self.wpis_id = wpis_id

        d_val = datetime.now().strftime("%d.%m.%Y")
        # Licznik w km, jak w bazie; pole pokazuje go w jednostce z Ustawień.
        self.p_km = db.pobierz_aktualny_przebieg(self.state.auto_id) or None
        # Strefa dotknięta na mapie karoserii (bez zdjęć) przychodzi już wybrana.
        z_mapy = getattr(state, "karoseria_nowa_strefa", None)
        strefa_val = z_mapy if z_mapy in db.STREFY_KAROSERII else db.STREFY_KAROSERII[0]
        state.karoseria_nowa_strefa = None
        typ_val = db.TYPY_ZDJECIA[0]
        opis_val = ""
        self.zalacznik_val = None

        if wpis_id:
            with db.polacz_baze() as conn:
                c = conn.cursor()
                c.execute("SELECT data, strefa, zalacznik, opis, przebieg, typ_porownania FROM zdjecia_karoserii WHERE id=?", (wpis_id,))
                w = c.fetchone()
                if w:
                    d_val, strefa_val, self.zalacznik_val = str(w[0]), str(w[1]), w[2]
                    opis_val, typ_val = str(w[3] or ""), str(w[5] or "Brak")
                    self.p_km = w[4] or None

        # Edycja jednego, konkretnego zdjęcia -> pojedynczy załącznik.
        # Dodawanie nowych -> masowy wybór wielu zdjęć naraz; każde stanie się
        # osobnym wpisem w galerii ze wspólnymi metadanymi z formularza poniżej.
        if wpis_id:
            self.k_zalacznik, self.get_zalacznik = utils.komponent_zalacznika(page, self.zalacznik_val)
        else:
            self.k_zalacznik, self.get_wiele_zdjec = utils.komponent_wielu_nowych_zdjec(page)

        self.e_d = utils.pole_daty(page, "Data zrobienia zdjęcia", d_val)
        self.e_p = ft.TextField(label=f"Przebieg ({utils.jednostka_dystansu()})", value=db.wartosc_pola_dystansu(self.p_km), keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola())

        # Strefa spoza słownika (stary wpis) zostaje jako własny chip — zapis jej nie podmieni.
        strefy = db.STREFY_KAROSERII + ([strefa_val] if strefa_val not in db.STREFY_KAROSERII else [])
        self.e_strefa = utils.WyborChipami(strefy, strefa_val)
        self.e_typ = utils.WyborChipami(db.TYPY_ZDJECIA, typ_val, etykiety=db.ETYKIETY_TYPOW_ZDJECIA)
        self.e_opis = ft.TextField(label="Opis / Notatki", value=opis_val, multiline=True, min_lines=2, max_lines=4, **utils.styl_pola())

        self._stan_poczatkowy = self._migawka_formularza()
        appbar = utils.zbuduj_pasek_z_powrotem(
            page, "Edycja wpisu galerii" if wpis_id else "Nowe zdjęcia do rejestru", "/karoseria",
            on_save=self.zapisz, czy_zmieniono=self._czy_zmieniono
        )

        if wpis_id:
            k1 = utils.karta_formularza([self.k_zalacznik], "Wymagane zdjęcie", ft.Icons.ADD_A_PHOTO, domyslnie_otwarte=True)
            tytul_k2 = "Co widać na zdjęciu"
        else:
            opis_pomocy = utils.podpis(
                "Zaznacz od razu kilka zdjęć — każde trafi do galerii osobno, ze wspólną strefą, "
                "rodzajem, opisem i datą ustawionymi poniżej."
            )
            k1 = utils.karta_formularza([opis_pomocy, self.k_zalacznik], "Zdjęcia", ft.Icons.ADD_A_PHOTO, domyslnie_otwarte=True)
            tytul_k2 = "Co widać na zdjęciach (wspólne dla wszystkich)"

        k2 = utils.karta_formularza([
            utils.etykieta("Strefa auta"), self.e_strefa.kontrolka,
            utils.etykieta("Rodzaj zdjęcia"), self.e_typ.kontrolka,
            utils.podpis("„Przed naprawą” i „Po naprawie” tej samej strefy połączą się w galerii w parę do porównania."),
            self.e_opis,
        ], tytul_k2, ft.Icons.INFO_OUTLINE, domyslnie_otwarte=True)
        k3 = utils.karta_formularza([self.e_d, self.e_p], "Kontekst", ft.Icons.SPEED)

        tekst_przycisku = "Zapisz zdjęcie" if wpis_id else "Zapisz zdjęcia"
        elementy = [k1, k2, k3, utils.przyciski_akcji(page, tekst_przycisku, self.zapisz, "/karoseria")]

        super().__init__(
            route=f"/karoseria/edytuj/{wpis_id}" if wpis_id else "/karoseria/nowe",
            padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO
        )

    def _migawka_formularza(self):
        podstawa = (self.e_d.value, self.e_p.value, self.e_strefa.value, self.e_typ.value, self.e_opis.value)
        if self.wpis_id:
            return podstawa
        return podstawa + (tuple(self.get_wiele_zdjec() or []),)

    def _czy_zmieniono(self):
        return self._migawka_formularza() != self._stan_poczatkowy

    def zapisz(self, e):
        for pole in (self.e_p, self.e_opis):
            utils.ustaw_blad(pole)
        # Pole w jednostce z Ustawień, baza w km; nieruszone pole wraca bez przeliczania.
        prz = db.dystans_na_km(utils.parsuj_int(self.e_p.value, 0), calkowity=True, km_przy_otwarciu=self.p_km)

        if self.wpis_id:
            wynik_komponentu = self.get_zalacznik()
            bedzie_zdjecie = (
                (wynik_komponentu is None and self.zalacznik_val) or
                (wynik_komponentu not in (None, ""))
            )
            if not bedzie_zdjecie:
                return utils.pokaz_komunikat(self._page, "Wymagane jest fizyczne zdjęcie!", utils.KOLOR_STATUS["error"])

            przygotowany = db.przygotuj_nowy_zalacznik(wynik_komponentu)
            nowy_zalacznik = przygotowany if przygotowany is not None else self.zalacznik_val

            with db.polacz_baze() as conn:
                conn.execute(
                    "UPDATE zdjecia_karoserii SET data=?, data_iso=?, strefa=?, zalacznik=?, opis=?, przebieg=?, typ_porownania=? WHERE id=?",
                    (self.e_d.value, na_iso(self.e_d.value), self.e_strefa.value, nowy_zalacznik, self.e_opis.value, prz, self.e_typ.value, self.wpis_id)
                )
            db.zatwierdz_zalacznik(self.zalacznik_val, przygotowany)

            utils.przejdz(self._page, "/karoseria")
            utils.pokaz_komunikat(self._page, "Zapisano wpis w galerii!")
            return

        # --- Tryb masowego dodawania: jedno zdjęcie = jeden nowy wpis w galerii ---
        sciezki_zrodlowe = self.get_wiele_zdjec()
        if not sciezki_zrodlowe:
            return utils.pokaz_komunikat(self._page, "Wybierz co najmniej jedno zdjęcie!", utils.KOLOR_STATUS["error"])

        przygotowane = []
        try:
            for sciezka in sciezki_zrodlowe:
                nowy = db.przygotuj_nowy_zalacznik(sciezka)
                if nowy:
                    przygotowane.append(nowy)

            if not przygotowane:
                return utils.pokaz_komunikat(self._page, "Nie udało się wczytać żadnego z wybranych zdjęć.", utils.KOLOR_STATUS["error"])

            with db.polacz_baze() as conn:
                for zalacznik in przygotowane:
                    conn.execute(
                        "INSERT INTO zdjecia_karoserii (auto_id, data, data_iso, strefa, zalacznik, opis, przebieg, typ_porownania) VALUES (?,?,?,?,?,?,?,?)",
                        (self.state.auto_id, self.e_d.value, na_iso(self.e_d.value), self.e_strefa.value, zalacznik, self.e_opis.value, prz, self.e_typ.value)
                    )
        except Exception as ex:
            for zalacznik in przygotowane:
                db.anuluj_nowy_zalacznik(zalacznik)
            return utils.pokaz_komunikat(self._page, f"Błąd zapisu galerii: {ex}", utils.KOLOR_STATUS["error"])

        utils.przejdz(self._page, "/karoseria")
        ile_wybranych, ile_zapisanych = len(sciezki_zrodlowe), len(przygotowane)
        if ile_zapisanych < ile_wybranych:
            utils.pokaz_komunikat(
                self._page,
                f"Zapisano {ile_zapisanych} z {ile_wybranych} zdjęć — część plików była niedostępna.",
                utils.KOLOR_STATUS["warning"]
            )
        else:
            utils.pokaz_komunikat(self._page, f"Dodano do galerii: {db.liczba_z_odmiana(ile_zapisanych, 'zdjęcie', 'zdjęcia', 'zdjęć')}.")