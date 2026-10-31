from datetime import datetime

import flet as ft
import db
import log
import sync
import utils

# Lista sezonów i ich ikony przeniosły się do wspólnych stałych: te same
# wartości czyta teraz warstwa danych (przelacz_zestaw_sezonowy) i kafelek
# kokpitu, a trzy kopie tego samego słownika prędzej czy później by się
# rozjechały.
SEZONY = db.SEZONY_OPON
IKONY_SEZONU = utils.IKONY_SEZONU_OPON

IKONY_KATEGORII_MAGAZYNU = {
    "Płyny eksploatacyjne": ft.Icons.WATER_DROP,
    "Oleje i smary": ft.Icons.OIL_BARREL,
    "Żarówki i bezpieczniki": ft.Icons.LIGHTBULB,
    "Filtry": ft.Icons.FILTER_ALT,
    "Akcesoria": ft.Icons.HANDYMAN,
    "Inne": ft.Icons.INVENTORY_2,
}


def _z_wielkiej(zdanie):
    return zdanie[:1].upper() + zdanie[1:] if zdanie else zdanie


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
        # --------------------------------------

        # Pasek podzakładek zostaje na miejscu, zmienia się tylko to, co pod nim —
        # tak samo jak przy czterech zakładkach ekranu głównego (patrz
        # MainView.przelacz_zakladke). Opony i części to dwie połowy jednego
        # magazynu, a nie dwa ekrany.
        self.trasa_fab = "/magazyn/opony/nowy"
        self.pasek_podzakladek = ft.Container(content=self._pasek_podzakladek())
        self.przelacznik = utils.PrzelacznikEkranow(
            self._zawartosc_podzakladki(), wlaczony=db.czy_animacje_interfejsu()
        )

        elementy = [
            self.pasek_podzakladek,
            self.przelacznik.kontrolka,
            utils.dol_bezpieczny(10),
        ]

        fab = self._fab_podzakladki()

        super().__init__(
            route="/magazyn",
            padding=15,
            appbar=appbar,
            floating_action_button=fab,
            spacing=15,
            controls=elementy,          # lub self.elementy, w zależności jak masz w tym pliku
            scroll=ft.ScrollMode.AUTO,  # włączasz natywne przewijanie
        )
        
    # ----- Podzakładki magazynu: Opony / Części i płyny -----
    def _pasek_podzakladek(self):
        return utils.segmented_control(
            self._page,
            [("Opony", 0, ft.Icons.TIRE_REPAIR), ("Części i płyny", 1, ft.Icons.HANDYMAN)],
            int(self.state.magazyn_zakladka or 0), self._przelacz_podzakladke,
        )

    def _fab_podzakladki(self):
        return utils.fab_animowany(ft.Icons.ADD, lambda e: utils.przejdz(self._page, self.trasa_fab))

    def _ustal_trase_fab(self):
        """Trasa „plusa” zależy tylko od tego, którą połowę magazynu widać —
        ustalamy ją PRZED budową treści, bo przycisk powstaje wcześniej niż ona."""
        self.trasa_fab = ("/magazyn/czesci/nowa" if int(self.state.magazyn_zakladka or 0) == 1
                          else "/magazyn/opony/nowy")
        return self.trasa_fab

    def _zawartosc_podzakladki(self):
        """Zawartość aktywnej podzakładki jako JEDNA kontrolka — to ona jedzie
        przez przełącznik. Budowa jest odroczona za szkielet, bo lista zestawów
        albo części potrafi mieć swoje kilkadziesiąt kart."""
        self._ustal_trase_fab()

        def tresc():
            if int(self.state.magazyn_zakladka or 0) == 1:
                elementy = self._buduj_czesci()
            else:
                elementy = self._buduj_opony()
            return ft.Column(list(elementy), spacing=15)

        return utils.zbuduj_etapami(
            self._page, utils.szkielet_listy(self._page, ile=4), tresc, widok=self,
        )

    def _przelacz_podzakladke(self, idx):
        stara = int(self.state.magazyn_zakladka or 0)
        idx = int(idx)
        if idx == stara:
            return

        self.state.magazyn_zakladka = idx
        # Zaznaczanie dotyczy JEDNEJ listy — przeniesione na drugą połowę
        # magazynu kasowałoby nie te pozycje, co trzeba.
        self.tryb_zaznaczania = False
        self.zaznaczone_id = set()
        self.tabela_cel = ""
        self.karty_ref = {}
        self.zapomnij_listy_kart()
        self.appbar = self.oryginalny_appbar

        self.pasek_podzakladek.content = self._pasek_podzakladek()
        self.przelacznik.pokaz(
            self._page, self._zawartosc_podzakladki(),
            kierunek=utils.PrzelacznikEkranow.kierunek(stara, idx),
        )
        self.floating_action_button = self._fab_podzakladki()
        try:
            self.update()
        except Exception:
            log.polkniety("odświeżenie magazynu po zmianie podzakładki")

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
            utils.pokaz_komunikat_cofnij(self._page, f"Usunięto {db.liczba_z_odmiana(ile, 'element', 'elementy', 'elementów')}.", wynik)

        tresc = f"Czy na pewno chcesz usunąć {ile} zaznaczonych elementów?"
        if tabela == "magazyn_czesci":
            tresc += self._ostrzezenie_o_zuzyciu(self.zaznaczone_id)
        utils.potwierdz(self._page, "Usuwanie", tresc, wykonaj)

    def _ostrzezenie_o_zuzyciu(self, ids):
        """Dopisek do potwierdzenia usunięcia pozycji użytej w serwisie: usunięcie
        kasuje jej zużycia; koszt zostaje we wpisach, ale ginie ślad, skąd się wziął."""
        podsumowanie = db.pobierz_podsumowanie_zuzycia(self.state.auto_id)
        uzycia = [podsumowanie[i] for i in ids if i in podsumowanie]
        if not uzycia:
            return ""
        liczba = sum(u["liczba"] for u in uzycia)
        koszt = round(sum(u["koszt"] for u in uzycia), 2)
        tekst = f"\n\nUżyto jej w serwisie {liczba} {utils._odmiana_liczby(liczba, 'raz', 'razy', 'razy')}"
        if len(ids) > 1:
            tekst = f"\n\nZaznaczone pozycje użyto w serwisie {liczba} {utils._odmiana_liczby(liczba, 'raz', 'razy', 'razy')}"
        if koszt > 0:
            tekst += f" (doliczono {utils.formatuj_liczba(koszt)} {utils.symbol_waluty()})"
        return (tekst + ". Koszt zostanie w tamtych wpisach i wizytach, ale zniknie z nich informacja "
                "o zużytej części. Jeśli po prostu się skończyła, możesz zostawić ją z zerowym stanem.")

    # ============== ZAKŁADKA: OPONY ==============
    def _buduj_opony(self):
        """Na górze karta „Na aucie” (bieżnik, wiek, kilometry sezonu, prognoza, zmiana, ciśnienie),
        pod nią komplety w magazynie. Dotknięcie otwiera ekran kompletu (views/opony_view.py)."""
        auto_id = self.state.auto_id
        dane = db.dane_opon(auto_id) if auto_id else None
        # Lista kompletów w magazynie przewija się razem z ekranem (pamięć pozycji szuka jej tu).
        self.lista_kart_opony = utils.lista_kart()
        if not dane or not dane["komplety"]:
            return [ft.Text("Brak zapisanych zestawów opon. Dotknij + poniżej, aby dodać pierwszy zestaw — ten na "
                            "aucie i ten z piwnicy; aplikacja policzy ich kilometry, bieżnik i wiek.",
                            color=ft.Colors.ON_SURFACE_VARIANT)]
        self.moge_opony = db.czy_moge_dodawac(auto_id)
        self.j_opon = utils.jednostka_dystansu()
        self.pliki_opon = db.zalaczniki_pojazdu(auto_id, "zestawy_opon")
        elementy = self._karty_na_aucie(dane)
        baner = self._baner_dziennika_opon(dane)
        if baner is not None:
            elementy.append(baner)

        w_magazynie = [k for k in dane["komplety"] if not k["zamontowany"]]
        if not w_magazynie:
            elementy.append(utils.podpis("W magazynie nie ma drugiego kompletu — dodaj go plusem, a zmiana sezonu "
                                         "przestawi oba jednym dotknięciem.", max_lines=3))
            return elementy

        elementy.append(utils.wartosc(f"W magazynie ({len(w_magazynie)})"))
        if len(w_magazynie) > 3:
            sort_opcje = [
                ("Sezon", "sezon", lambda k: k["sezon"].lower()),
                ("Bieżnik", "bieznik", lambda k: k["bieznik"] or 0.0),
                ("Wiek", "wiek", lambda k: (k["wiek"] or {}).get("lata") or 0.0),
            ]
            sort_ui = utils.przycisk_sortowania(self._page, self.state, "opony_magazyn", sort_opcje)
            chipy_filtrow, w_magazynie = utils.pasek_filtrow(
                self._page, self.state, w_magazynie, [("kategoria", "opony_sezon", "sezon", "Sezon")])
            elementy.append(ft.Row(controls=[sort_ui] + chipy_filtrow, scroll=ft.ScrollMode.ADAPTIVE, spacing=8))
            utils.posortuj_liste(w_magazynie, self.state, "opony_magazyn", sort_opcje)
        self.lista_kart_opony.controls.extend(self._karta_zestawu(k) for k in w_magazynie)
        elementy.append(self.lista_kart_opony)
        return elementy

    def _karty_na_aucie(self, dane):
        """Karta zamontowanego kompletu (przy osiach — po jednej) z akcjami zmiany na pierwszej."""
        page = self._page
        if not dane["zamontowane"]:
            return [ft.Container(
                padding=utils.SPACING["md"], **utils.powierzchnia(page, "karta"),
                content=ft.Column([
                    ft.Row([ft.Icon(ft.Icons.TIRE_REPAIR, size=20, color=ft.Colors.ON_SURFACE_VARIANT),
                            utils.wartosc("Żaden komplet nie jest na aucie", expand=True, max_lines=2)], spacing=8),
                    utils.podpis("Dotknij kompletu niżej i wybierz „Załóż na auto” — od tego dnia policzę jego "
                                 "kilometry.", max_lines=3),
                ], spacing=8),
            )]

        stan = db.pobierz_stan_opon(self.state.auto_id) or {}
        przypomnienia = db.pobierz_przypomnienia_o_oponach(self.state.auto_id)
        pojazd = db.pobierz_dane_pojazdu(self.state.auto_id) or {}
        cisnienie = " / ".join(str(x) for x in (pojazd.get("cisnienie_przod"), pojazd.get("cisnienie_tyl")) if x)
        karty = []
        for numer, k in enumerate(dane["zamontowane"]):
            naglowek = f"Na aucie: {k['sezon']}" if k["sezon"] else "Na aucie"
            if k["os"] != "Wszystkie":
                naglowek += f" · {k['os'].lower()}"
            tresc = [ft.Row([utils.ikona_sezonu(k["sezon"], 22),
                             utils.wartosc(naglowek, size=utils.FS["title"], expand=True, max_lines=2),
                             ft.Icon(ft.Icons.CHEVRON_RIGHT, size=20, color=ft.Colors.ON_SURFACE_VARIANT)],
                            spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)]
            if utils.opis_kompletu(k):
                tresc.append(utils.podpis(utils.opis_kompletu(k), max_lines=2))
            tresc.append(utils.pasek_bieznika(k))
            linia = [db.tekst_wieku(k["wiek"])]
            if k["km_biezacy"]:
                linia.append(f"{utils.formatuj_dystans(k['km_biezacy'], 0, self.j_opon)} w tym sezonie")
            if k["km"] and k["km"] != k["km_biezacy"]:
                linia.append(f"razem {utils.formatuj_dystans(k['km'], 0, self.j_opon)}")
            if any(linia):
                tresc.append(utils.podpis(" · ".join(x for x in linia if x), max_lines=2))
            if k["prognoza"]:
                tresc.append(utils.podpis(_z_wielkiej(db.opis_prognozy(k["prognoza"], self.j_opon)), max_lines=2))
            for zdanie, kolor in ((utils.opis_bieznika_ponizej(k), utils.kolor_bieznika(k["status_bieznika"])),
                                  (utils.opis_wieku(k["wiek"]), utils.kolor_wieku(k["wiek"])),
                                  (utils.wskazowka_osi(k), utils.KOLOR_STATUS["warning"])):
                if zdanie:
                    tresc.append(utils.podpis(_z_wielkiej(zdanie), color=kolor, max_lines=3))
            if numer == 0:
                docelowy = str(stan.get("docelowy_sezon") or "").lower()
                if przypomnienia:
                    termin = utils.tekst_terminu_zmiany(dane["termin_zmiany"])
                    tresc.append(utils.podpis(f"Zmiana na {docelowy}: {termin}" if termin and docelowy
                                              else f"Następna zmiana: {termin or przypomnienia[0][4]}", max_lines=2))
                else:
                    tresc.append(utils.podpis("Bez przypomnienia o sezonowej zmianie", max_lines=2))
                if cisnienie:
                    tresc.append(utils.podpis(f"Ciśnienie (przód / tył): {cisnienie}", max_lines=2))
            if self.moge_opony and k["id"] in dane["brak_poczatku"]:
                tresc.append(utils.podpis("Od kiedy ten komplet jest na aucie? Bez tego dnia nie policzę jego "
                                          "kilometrów.", max_lines=3))
            akcje = self._akcje_na_aucie(k, stan, przypomnienia, dane) if numer == 0 or (
                self.moge_opony and k["id"] in dane["brak_poczatku"]) else []
            if akcje:
                tresc.append(utils.pasek_zawijany(akcje, spacing=4))
            karty.append(ft.Container(
                padding=utils.SPACING["md"], **utils.powierzchnia(page, "karta", stan=utils.stan_kompletu(k)),
                ink=True, on_click=lambda e, zid=k["id"]: utils.przejdz(self._page, f"/magazyn/opony/{zid}"),
                content=ft.Column(tresc, spacing=8),
            ))
        return karty

    def _akcje_na_aucie(self, k, stan, przypomnienia, dane):
        if not self.moge_opony:
            return []
        akcje = []
        if k["id"] in dane["brak_poczatku"]:
            akcje.append(ft.TextButton("Ustaw dzień założenia", icon=ft.Icons.EVENT, on_click=lambda e, zid=k["id"]:
                                       utils.okno_poczatku_montazu(self._page, self.state, zid)))
        if k is not dane["zamontowane"][0]:
            return akcje
        kandydat = utils.kandydat_zmiany(self.state.auto_id)
        if kandydat:
            przypomnienie = przypomnienia[0] if przypomnienia else None

            def zmien(e, zid=kandydat, wpis=przypomnienie):
                utils.okno_zmiany_opon(self._page, self.state, zid, przypomnienie_id=wpis[0] if wpis else None,
                                       koszt=wpis[2] if wpis and wpis[2] else None)

            akcje.append(ft.FilledButton(f"Zmień na {str(stan.get('docelowy_sezon') or '').lower()}",
                                         icon=ft.Icons.SWAP_HORIZ, on_click=zmien))
        akcje.append(ft.TextButton("Pomiar", icon=ft.Icons.SQUARE_FOOT,
                                   on_click=lambda e, zid=k["id"]: utils.przejdz(self._page, f"/magazyn/opony/{zid}/pomiar")))
        if not przypomnienia:
            def ustaw_przypomnienie(e):
                db.dodaj_przypomnienie_o_oponach(self.state.auto_id)
                utils.przejdz(self._page, "/magazyn")
                utils.pokaz_komunikat(self._page, "Dodano przypomnienie o sezonowej zmianie opon (co pół roku).")

            akcje.append(ft.TextButton("Ustaw przypomnienie", icon=ft.Icons.NOTIFICATIONS_ACTIVE,
                                       on_click=ustaw_przypomnienie))
        return akcje

    def _baner_dziennika_opon(self, dane):
        """Zmiany opon z Serwisu, z których da się odtworzyć sezony kompletów (auto bez dziennika)."""
        if not self.moge_opony or not dane["do_odtworzenia"] or dane["jest_dziennik"]:
            return None

        def odtworz(e):
            ile = db.odtworz_sezony_z_serwisu(self.state.auto_id)
            utils.wypchnij_w_tle(self._page, self.state.auto_id, "sezony opon")
            utils.przejdz(self._page, "/magazyn")
            utils.pokaz_komunikat(self._page, f"Odtworzono sezony: {ile}." if ile else
                                  "Nie było czego odtworzyć — sezon da się przypisać tylko kompletowi jedynemu "
                                  "w swojej porze roku.", utils.KOLOR_STATUS["ok"] if ile else utils.KOLOR_STATUS["warning"])

        return ft.Container(
            padding=utils.SPACING["md"], **utils.powierzchnia(self._page, "karta"),
            content=ft.Column([
                ft.Row([ft.Icon(ft.Icons.HISTORY, size=20, color=ft.Colors.PRIMARY),
                        utils.wartosc("Sezony z historii serwisu", expand=True, max_lines=2)], spacing=8),
                utils.podpis(f"W Serwisie są zmiany opon z rodzajem opon ({dane['do_odtworzenia']}) — odtworzę z nich, "
                             "kiedy który komplet był na aucie, i policzę jego kilometry.", max_lines=4),
                ft.Row([ft.TextButton("Odtwórz z Serwisu", icon=ft.Icons.HISTORY, on_click=odtworz)],
                       alignment=ft.MainAxisAlignment.END),
            ], spacing=6),
        )

    def _karta_zestawu(self, k):
        pliki = self.pliki_opon.get(k["id"], [])
        tresc = [ft.Row([
            utils.wskaznik_zalacznikow(self._page, pliki, "Zestaw opon") if pliki else ft.Container(),
            ft.Row([utils.ikona_sezonu(k["sezon"], 17),
                    utils.wartosc(k["sezon"] or "Komplet", size=utils.FS["title"], no_wrap=True,
                                  overflow=ft.TextOverflow.ELLIPSIS)], spacing=6, expand=True),
            utils.chip_kompletu(self._page, k),
        ], spacing=6)]
        tresc.append(utils.podpis(utils.opis_kompletu(k) or "Brak danych o rozmiarze i marce", max_lines=2))
        tresc.append(utils.pasek_bieznika(k))
        if utils.linijka_kompletu(k, self.j_opon):
            tresc.append(utils.podpis(utils.linijka_kompletu(k, self.j_opon), max_lines=2))
        for zdanie, kolor in ((utils.opis_bieznika_ponizej(k), utils.kolor_bieznika(k["status_bieznika"])),
                              (utils.opis_wieku(k["wiek"]), utils.kolor_wieku(k["wiek"]))):
            if zdanie:
                tresc.append(utils.podpis(_z_wielkiej(zdanie), color=kolor, max_lines=3))
        karta, kontener = utils.karta_listy(
            ft.Column(tresc, spacing=6),
            kolor_paska=utils.kolor_bieznika(k["status_bieznika"]) if k["status_bieznika"] else None,
            page=self._page,
        )
        self.karty_ref[k["id"]] = kontener
        self.podepnij_zdarzenia_grupowe(
            kontener, k["id"], lambda zid=k["id"], zk=k, zpl=pliki: self._pokaz_menu(zk, zpl), "zestawy_opon")
        return karta

    def _pokaz_menu(self, k, pliki=None):
        zid, sezon = k["id"], k["sezon"]

        def zaloz(os_montazu):
            utils.okno_zmiany_opon(self._page, self.state, zid, os_montazu)

        def usun_zestaw():
            def wykonaj():
                wynik = db.usun_z_cofnieciem("zestawy_opon", zid)
                utils.przejdz(self._page, "/magazyn")
                utils.pokaz_komunikat_cofnij(self._page, "Usunięto zestaw opon.", wynik)
            utils.potwierdz(self._page, "Usunąć?", f"Czy na pewno usunąć zestaw „{sezon}” razem z jego pomiarami "
                                                   "i sezonami?", wykonaj)

        pozycje_menu = [{"ikona": ft.Icons.TIRE_REPAIR, "tekst": "Szczegóły kompletu", "czyta": True,
                         "akcja": lambda: utils.przejdz(self._page, f"/magazyn/opony/{zid}")}]
        pozycje_menu += utils.pozycje_menu_zalacznikow(self._page, "zestawy_opon", zid, pliki, "Zestaw opon",
                                                       lambda: utils.przejdz(self._page, "/magazyn"))
        pozycje_menu.extend([
            {"ikona": ft.Icons.SWAP_HORIZ, "tekst": "Załóż na całe auto", "akcja": lambda: zaloz("Wszystkie"),
             "kolor": utils.KOLOR_STATUS["ok"]},
            {"ikona": ft.Icons.ARROW_UPWARD, "tekst": "Załóż tylko na przednią oś", "akcja": lambda: zaloz("Przód")},
            {"ikona": ft.Icons.ARROW_DOWNWARD, "tekst": "Załóż tylko na tylną oś", "akcja": lambda: zaloz("Tył")},
            {"ikona": ft.Icons.SQUARE_FOOT, "tekst": "Dodaj pomiar bieżnika",
             "akcja": lambda: utils.przejdz(self._page, f"/magazyn/opony/{zid}/pomiar")},
            {"ikona": ft.Icons.EDIT, "tekst": "Edytuj zestaw", "akcja": lambda: utils.przejdz(self._page, f"/magazyn/opony/edytuj/{zid}")},
            {"ikona": ft.Icons.DELETE, "tekst": "Usuń zestaw", "akcja": usun_zestaw, "kolor": utils.KOLOR_STATUS["destructive"]}
        ])

        pozycje_menu = utils.odsiej_akcje(self.state.auto_id, pozycje_menu, "zestawy_opon", zid)
        utils.pokaz_menu_kontekstowe(self._page, f"Zestaw: {sezon}", pozycje_menu)

    # ============== ZAKŁADKA: CZĘŚCI I PŁYNY ==============
    def _buduj_czesci(self):
        elementy = []
        with db.polacz_baze() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT id, nazwa, kategoria, ilosc, jednostka, cena, data_zakupu, notatki, NULL, prog_ostrzezenia, cena_jednostkowa, "
                "sklep, link FROM magazyn_czesci WHERE auto_id=? ORDER BY nazwa",
                (self.state.auto_id,)
            )
            # Pole 8 — lista plików pozycji (db.zalaczniki_pojazdu), jednym zapytaniem.
            pliki_czesci = db.zalaczniki_pojazdu(self.state.auto_id, "magazyn_czesci")
            czesci = [cz[:8] + (pliki_czesci.get(cz[0], []),) + cz[9:] for cz in c.fetchall()]

        if not czesci:
            elementy.append(ft.Text("Brak części i płynów w magazynie. Dotknij + poniżej, aby dodać pierwszą pozycję.", color=ft.Colors.ON_SURFACE_VARIANT))
            return elementy

        # Zużycie całego magazynu jednym zapytaniem — karta pozycji nie pyta
        # bazy sama za siebie.
        self._zuzycie_czesci = db.pobierz_podsumowanie_zuzycia(self.state.auto_id)
        # Historia cen całego magazynu też jednym zapytaniem (M-15).
        self._historia_cen = db.historia_cen_pojazdu(self.state.auto_id)
        wartosc = db.pobierz_wartosc_magazynu(self.state.auto_id)
        # Bez ani jednej wycenionej pozycji na stanie karta nie ma nic do
        # powiedzenia poza „0,00” — a to czyta się jak pusty magazyn.
        if wartosc["na_stanie"] > wartosc["bez_ceny"]:
            elementy.append(self._karta_wartosci_magazynu(wartosc))

        sort_opcje = [
            ("Nazwa", "nazwa", lambda x: str(x[1]).lower()),
            ("Ilość", "ilosc", lambda x: float(x[3] or 0)),
            ("Kategoria", "kategoria", lambda x: str(x[2] or "").lower()),
            ("Wartość", "wartosc", lambda x: float(x[3] or 0) * float(x[10] or 0)),
        ]
        sort_ui = utils.przycisk_sortowania(self._page, self.state, "magazyn_czesci", sort_opcje)
        chipy_filtrow, czesci_po_filtrach = utils.pasek_filtrow(
            self._page, self.state, czesci, [("kategoria", "magazyn_kategoria", 2, "Kategoria")])

        elementy.append(ft.Row(controls=[sort_ui] + chipy_filtrow, scroll=ft.ScrollMode.ADAPTIVE, spacing=8))

        def filtruj_czesci(e):
            zapytanie = e.control.value.lower().strip()
            self.lista_kart_czesci.controls.clear()
            for k in self.wszystkie_karty_czesci:
                if zapytanie in k["szukaj"]:
                    self.lista_kart_czesci.controls.append(k["karta"])
            self.update()

        elementy.append(utils.na_cala_szerokosc(
            ft.TextField(
                hint_text="Szukaj części (nazwa, sklep)",
                prefix_icon=ft.Icons.SEARCH,
                on_change=utils.z_opoznieniem(self._page, filtruj_czesci),
                **utils.styl_pola()
            )
        ))
        self.lista_kart_czesci = utils.lista_kart()
        self.wszystkie_karty_czesci = []

        czesci = czesci_po_filtrach
        utils.posortuj_liste(czesci, self.state, "magazyn_czesci", sort_opcje)

        for cz in czesci:
            karta = self._karta_czesci(cz)
            c_id, nazwa, kategoria, ilosc, jednostka, cena, data_zakupu, notatki, pliki, prog_ostrzezenia, cena_jedn, sklep, link = cz
            tekst_szukaj = f"{nazwa} {kategoria} {notatki} {sklep or ''}".lower()
            self.wszystkie_karty_czesci.append({"karta": karta, "szukaj": tekst_szukaj})
            self.lista_kart_czesci.controls.append(karta)

        elementy.append(self.lista_kart_czesci)
        return elementy

    def _karta_wartosci_magazynu(self, wartosc):
        """Ile wart jest magazyn — stan razy cena za jednostkę. Pozycje bez ceny
        podane osobno: bez tej liczby suma udawałaby kompletną."""
        na_stanie = wartosc["na_stanie"]
        opis = [f"{na_stanie} {utils._odmiana_liczby(na_stanie, 'pozycja', 'pozycje', 'pozycji')} na stanie"]
        if wartosc["bez_ceny"]:
            opis.append(f"{wartosc['bez_ceny']} bez ceny, nie wliczone")
        return ft.Container(
            padding=ft.Padding(16, 12, 16, 12),
            **utils.powierzchnia(self._page, "karta"),
            content=ft.Row([
                ft.Icon(ft.Icons.INVENTORY_2, size=22, color=ft.Colors.PRIMARY),
                ft.Column([
                    utils.etykieta("Wartość magazynu"),
                    utils.wartosc(f"{utils.formatuj_liczba(wartosc['wartosc'])} {utils.symbol_waluty()}"),
                    utils.podpis(" · ".join(opis)),
                ], spacing=2, tight=True, expand=True),
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )

    def _karta_czesci(self, cz):
        c_id, nazwa, kategoria, ilosc, jednostka, cena, data_zakupu, notatki, pliki, prog_ostrzezenia, cena_jedn, sklep, link = cz
        ikona = IKONY_KATEGORII_MAGAZYNU.get(kategoria, ft.Icons.BUILD)
        waluta = utils.symbol_waluty()

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
            kolor_stan = utils.KOLOR_STATUS["critical"]
        elif ilosc_f <= prog_f:
            kolor_stan = utils.KOLOR_STATUS["warning"]
        else:
            kolor_stan = utils.KOLOR_STATUS["ok"]
        tekst_stan = f"{utils.tekst_ilosci(ilosc_f)} {jednostka}" if ilosc_f > 0 else "Brak na stanie"

        znacznik = ft.Container(
            padding=8, border_radius=20,
            bgcolor=ft.Colors.with_opacity(0.15, kolor_stan),
            content=ft.Text(tekst_stan, size=11, weight="bold", color=kolor_stan)
        )

        # Cena za jednostkę i wartość tego, co leży na półce — to z niej liczy się
        # koszt zużycia. Sam koszt zakupu zostaje tylko tam, gdzie ceny za
        # jednostkę nie da się ustalić.
        stopka_bits = []
        cena_jedn_f = float(cena_jedn) if cena_jedn is not None else None
        if cena_jedn_f is not None:
            tekst_ceny = f"{utils.tekst_ceny(cena_jedn_f)} {waluta}/{jednostka}"
            if ilosc_f > 0:
                tekst_ceny += f" · wartość {utils.formatuj_liczba(ilosc_f * cena_jedn_f)} {waluta}"
            stopka_bits.append(tekst_ceny)
        elif cena is not None and str(cena).strip():
            stopka_bits.append(f"Koszt zakupu: {utils.formatuj_liczba(cena)} {waluta}")
        if data_zakupu:
            stopka_bits.append(f"Zakup: {data_zakupu}")

        zuzycie = (getattr(self, "_zuzycie_czesci", None) or {}).get(c_id)
        tekst_zuzycia = ""
        if zuzycie:
            czesci_zuzycia = [f"Użyto {zuzycie['liczba']}×, razem {utils.tekst_ilosci(zuzycie['ilosc'])} {jednostka}"]
            if zuzycie["koszt"] > 0:
                czesci_zuzycia.append(f"doliczono {utils.formatuj_liczba(zuzycie['koszt'])} {waluta}")
            if zuzycie["ostatnio"]:
                czesci_zuzycia.append(f"ostatnio {zuzycie['ostatnio']}")
            tekst_zuzycia = " · ".join(czesci_zuzycia)

        tresc = [
            ft.Row([
                utils.wskaznik_zalacznikow(self._page, pliki, "Część/płyn") if pliki else ft.Container(),
                ft.Row([
                    ft.Icon(ikona, size=17, color=ft.Colors.PRIMARY),
                    ft.Text(str(nazwa), weight="bold", size=16, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                ], spacing=6, expand=True),
                znacznik,
            ], spacing=6),
            ft.Text(str(kategoria) if kategoria else "Bez kategorii", size=13, color=ft.Colors.ON_SURFACE_VARIANT),
        ]
        # Sklep obok daty zakupu; z linkiem dotknięcie otwiera stronę produktu.
        chip_sklepu = utils.chip_sklepu(self._page, sklep, link)
        if stopka_bits and chip_sklepu:
            tresc.append(ft.Row([
                ft.Text("  |  ".join(stopka_bits), size=12, color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                chip_sklepu,
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER))
        elif stopka_bits:
            tresc.append(ft.Text("  |  ".join(stopka_bits), size=12, color=ft.Colors.ON_SURFACE_VARIANT))
        elif chip_sklepu:
            tresc.append(chip_sklepu)
        if tekst_zuzycia:
            tresc.append(ft.Text(tekst_zuzycia, size=12, color=ft.Colors.ON_SURFACE_VARIANT))
        # Ile ta część kosztowała przy poprzednich zakupach (M-15).
        punkty_cen = db.historia_cen_czesci(self.state.auto_id, nazwa, getattr(self, "_historia_cen", None) or {})
        wiersz_cen = utils.wiersz_cen_na_karcie(punkty_cen, c_id, jednostka)
        if wiersz_cen:
            tresc.append(wiersz_cen)

        karta, kontener = utils.karta_listy(
            ft.Column(tresc, spacing=4), kolor_paska=kolor_stan, page=self._page
        )

        self.karty_ref[c_id] = kontener
        self.podepnij_zdarzenia_grupowe(
            kontener, c_id,
            lambda cid=c_id, cn=nazwa, cpl=pliki, cj=jednostka, uz=bool(zuzycie), sk=sklep, ln=link:
                self._pokaz_menu_czesci(cid, cn, cpl, cj, uz, sk, ln),
            "magazyn_czesci")

        return karta

    def _pokaz_historie_zuzycia(self, cid, nazwa, jednostka):
        """Gdzie ta pozycja zeszła z magazynu. Dotknięcie wpisu otwiera jego
        edycję — to tam poprawia się ilość albo oddaje część na stan."""
        historia = db.pobierz_historie_zuzycia(cid)
        waluta = utils.symbol_waluty()
        bs = ft.BottomSheet(ft.Container(padding=ft.Padding(16, 16, 16, 8), bgcolor=ft.Colors.SURFACE))

        def otworz(trasa):
            utils.zamknij_dno(self._page, bs)
            utils.przejdz(self._page, trasa)

        razem_ilosc = sum(p["ilosc"] for p in historia)
        razem_koszt = round(sum(p["koszt"] or 0 for p in historia), 2)
        podsumowanie = f"Zużyto razem {utils.tekst_ilosci(razem_ilosc)} {jednostka}"
        if razem_koszt > 0:
            podsumowanie += f" · doliczono {utils.formatuj_liczba(razem_koszt)} {waluta}"

        zawartosc = [
            ft.Row([
                ft.Icon(ft.Icons.HISTORY, size=22, color=ft.Colors.PRIMARY),
                ft.Column([
                    ft.Text(f"Historia zużycia: {nazwa}", weight="bold", size=18, color=ft.Colors.PRIMARY),
                    utils.podpis(podsumowanie),
                ], spacing=0, tight=True, expand=True),
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Divider(height=14),
        ]
        if not historia:
            zawartosc.append(utils.podpis("Ta pozycja nie była jeszcze użyta w żadnym wpisie, wizycie ani dolewce."))
        for pozycja in historia:
            kwota = (f"{utils.formatuj_liczba(pozycja['koszt'])} {waluta}" if pozycja["koszt"] is not None
                     else "bez doliczenia")
            zawartosc.append(ft.Container(
                padding=ft.Padding(12, 10, 12, 10), ink=True,
                on_click=lambda e, t=pozycja["trasa"]: otworz(t),
                **utils.powierzchnia(self._page, "blok"),
                content=ft.Row([
                    ft.Icon({"wizyty": ft.Icons.HOME_REPAIR_SERVICE, "dolewki": ft.Icons.WATER_DROP}.get(
                        pozycja["zrodlo"], ft.Icons.BUILD), size=18, color=ft.Colors.PRIMARY),
                    ft.Column([
                        ft.Text(pozycja["tytul"], size=utils.FS["body"], weight="w500",
                                max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                        utils.podpis(f"{pozycja['data']} · {pozycja['opis']}"),
                    ], spacing=1, tight=True, expand=True),
                    ft.Column([
                        utils.wartosc(f"{utils.tekst_ilosci(pozycja['ilosc'])} {jednostka}", size=utils.FS["body"]),
                        utils.podpis(kwota),
                    ], spacing=1, tight=True, horizontal_alignment=ft.CrossAxisAlignment.END),
                ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ))

        bs.content.content = ft.Column(zawartosc, tight=True, spacing=8)
        utils.otworz_dno(self._page, bs)

    def _pokaz_menu_czesci(self, cid, nazwa, pliki=None, jednostka="szt", uzyta=False, sklep=None, link=None):
        def usun_czesc():
            def wykonaj():
                wynik = db.usun_czesc_magazynu_z_cofnieciem(cid)   # było: db.usun_z_cofnieciem("magazyn_czesci", cid)
                utils.przejdz(self._page, "/magazyn")
                utils.pokaz_komunikat_cofnij(self._page, f"Usunięto '{nazwa}'.", wynik)
            tresc = f"Czy na pewno usunąć pozycję „{nazwa}”?" + self._ostrzezenie_o_zuzyciu([cid])
            utils.potwierdz(self._page, "Usunąć?", tresc, wykonaj)

        pozycje_menu = utils.pozycje_menu_zalacznikow(self._page, "magazyn_czesci", cid, pliki, "Część/płyn",
                                                      lambda: utils.przejdz(self._page, "/magazyn"))

        # Historia cen i kolejny zakup (M-15). „Kupiłem ponownie” zmienia stan,
        # więc przy podglądzie znika; historię i link wolno tylko oglądać.
        czesc = {"id": cid, "nazwa": nazwa, "jednostka": jednostka, "sklep": sklep, "link": link}

        def odswiez():
            utils.przejdz(self._page, "/magazyn")

        pozycje_menu.append({"ikona": ft.Icons.ADD_SHOPPING_CART, "tekst": "Kupiłem ponownie",
                             "akcja": lambda: utils.dialog_kupilem_ponownie(self._page, self.state.auto_id, czesc, odswiez)})
        pozycje_menu.append({"ikona": ft.Icons.SHOW_CHART, "tekst": "Historia cen", "czyta": True,
                             "akcja": lambda: utils.pokaz_historie_cen(self._page, self.state.auto_id, czesc, odswiez)})
        pozycje_menu.extend(utils.akcje_linku(self._page, link))
        if uzyta:
            pozycje_menu.append({"ikona": ft.Icons.HISTORY, "tekst": "Historia zużycia", "czyta": True,
                                 "akcja": lambda: self._pokaz_historie_zuzycia(cid, nazwa, jednostka)})
        pozycje_menu.extend([
            {"ikona": ft.Icons.EDIT, "tekst": "Edytuj pozycję", "akcja": lambda: utils.przejdz(self._page, f"/magazyn/czesci/edytuj/{cid}")},
            {"ikona": ft.Icons.DELETE, "tekst": "Usuń pozycję", "akcja": usun_czesc, "kolor": utils.KOLOR_STATUS["destructive"]}
        ])

        pozycje_menu = utils.odsiej_akcje(self.state.auto_id, pozycje_menu, "magazyn_czesci", cid)
        utils.pokaz_menu_kontekstowe(self._page, f"Pozycja: {nazwa}", pozycje_menu)

class FormularzOponyView(ft.View):
    # Kolumny kompletu w formularzu — kolejność jak w zapytaniu.
    POLA = ("sezon", "rozmiar", "marka_model", "numer_dot", "ilosc", "data_zakupu", "przebieg_zakupu", "cena", "notatki",
            "miejsce", "numer_kwitu", "oplata_przechowania", "na_felgach", "felgi")

    def __init__(self, page: ft.Page, state, zestaw_id=None):
        self._page = page
        self.state = state
        self.zestaw_id = zestaw_id
        w = {}
        if zestaw_id:
            with db.polacz_baze() as conn:
                wiersz = conn.execute(f"SELECT {', '.join(self.POLA)} FROM zestawy_opon WHERE id=?",
                                      (zestaw_id,)).fetchone()
            w = dict(zip(self.POLA, wiersz)) if wiersz else {}
        else:
            # Nowy komplet zwykle ma rozmiar z Karty pojazdu — ten sam, co na naklejce w drzwiach.
            w["rozmiar"] = (db.pobierz_dane_pojazdu(state.auto_id) or {}).get("rozmiar_opon") if state.auto_id else None
        self.pz_km = w.get("przebieg_zakupu") or None  # przebieg przy zakupie w km, jak w bazie
        self.na_felgach_pocz = w.get("na_felgach")
        self.powrot = f"/magazyn/opony/{zestaw_id}" if zestaw_id else "/magazyn"

        def tekst(pole):
            return str(w.get(pole) or "")

        self.pliki = utils.PolaZalacznikow(page, "zestawy_opon", zestaw_id, auto_id=state.auto_id)
        # Ikona idzie do leading_icon, a NIE do tekstu: ft.Icons to wyliczenie,
        # więc f"{IKONY_SEZONU[s]} {s}" renderowało się jako „74139 Letnie”.
        self.e_sezon = ft.Dropdown(
            label="Sezon",
            options=[ft.DropdownOption(key=s, text=s, leading_icon=IKONY_SEZONU[s]) for s in SEZONY],
            value=tekst("sezon") or SEZONY[0], **utils.styl_dropdown()
        )
        self.e_rozmiar = ft.TextField(label="Rozmiar (np. 205/55 R16)", value=tekst("rozmiar"), **utils.styl_pola())
        self.e_marka = ft.TextField(label="Marka / model opony", value=tekst("marka_model"), **utils.styl_pola())
        self.e_dot = ft.TextField(label="Kod DOT (data produkcji)", value=tekst("numer_dot"),
                                  hint_text="np. 2321, 0222 — tydzień i rok", **utils.styl_pola())
        self.e_il = ft.TextField(label="Ilość opon w zestawie", value=str(w.get("ilosc") or 4),
                                 keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola())

        # Nowy komplet: pierwszy pomiar i montaż od razu; potem zmienia się je na ekranie kompletu.
        self.e_gl = ft.TextField(label="Bieżnik teraz (mm, opcjonalnie)", keyboard_type=ft.KeyboardType.NUMBER,
                                 **utils.styl_pola())
        self.e_zam = ft.Checkbox(label="Ten komplet jest teraz na aucie", value=False)
        self.e_os = ft.Dropdown(label="Na jakiej osi", options=[ft.DropdownOption(key=o, text=o) for o in db.OSIE_MONTAZU],
                                value="Wszystkie", visible=False, **utils.styl_dropdown())
        self.e_od = utils.pole_daty(page, "Na aucie od (opcjonalnie)", "")
        self.e_od.visible = False

        def _przelacz_os(e):
            self.e_os.visible = self.e_od.visible = bool(self.e_zam.value)
            self.update()

        self.e_zam.on_change = _przelacz_os

        self.e_miejsce = ft.TextField(label="Gdzie leży (garaż, przechowalnia)", value=tekst("miejsce"), **utils.styl_pola())
        self.e_kwit = ft.TextField(label="Numer kwitu przechowalni", value=tekst("numer_kwitu"), **utils.styl_pola())
        self.e_oplata = ft.TextField(label=f"Opłata za sezon ({utils.symbol_waluty()})",
                                     value=utils.liczba_do_pola(w.get("oplata_przechowania"))
                                     if w.get("oplata_przechowania") else "",
                                     keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola())
        self.e_na_felgach = ft.Checkbox(label="Opony są na felgach (komplet kół)", value=bool(w.get("na_felgach")))
        self.e_felgi = ft.TextField(label="Felgi (np. alu 16″ 6,5J ET42)", value=tekst("felgi"), **utils.styl_pola())

        self.e_dz = utils.pole_daty(page, "Data zakupu", tekst("data_zakupu"))
        self.e_pz = ft.TextField(label=f"Przebieg przy zakupie ({utils.jednostka_dystansu()})",
                                 value=db.wartosc_pola_dystansu(self.pz_km) if self.pz_km else "",
                                 keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola())
        self.e_cena = ft.TextField(label=f"Koszt zakupu ({utils.symbol_waluty()})",
                                   value=utils.liczba_do_pola(w.get("cena")) if w.get("cena") else "",
                                   keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola())
        self.e_not = ft.TextField(label="Dodatkowe notatki", value=tekst("notatki"), multiline=True, min_lines=2,
                                  max_lines=4, **utils.styl_pola())

        self._stan_poczatkowy = self._migawka_formularza()
        appbar = utils.zbuduj_pasek_z_powrotem(page, "Edycja zestawu opon" if zestaw_id else "Nowy zestaw opon",
                                               self.powrot, on_save=self.zapisz, czy_zmieniono=self._czy_zmieniono)

        k1 = utils.karta_formularza([self.e_sezon, self.e_rozmiar, self.e_marka, self.e_dot, self.e_il],
                                    "Specyfikacja opony", ft.Icons.INFO_OUTLINE, domyslnie_otwarte=True)
        if zestaw_id:
            k2 = utils.karta_formularza([utils.podpis(
                "Bieżnik każdego koła i zmiany opon zapisujesz na ekranie kompletu — z nich liczą się kilometry, "
                "tempo zużycia i prognoza.", max_lines=4)], "Stan i montaż", ft.Icons.SQUARE_FOOT)
        else:
            k2 = utils.karta_formularza([self.e_gl, utils.pole_wyboru(self.e_zam), self.e_os, self.e_od],
                                        "Stan i montaż", ft.Icons.SQUARE_FOOT, domyslnie_otwarte=True)
        k3 = utils.karta_formularza([self.e_miejsce, self.e_kwit, self.e_oplata, utils.pole_wyboru(self.e_na_felgach),
                                     self.e_felgi], "Przechowywanie i felgi", ft.Icons.WAREHOUSE,
                                    domyslnie_otwarte=bool(w.get("miejsce") or w.get("felgi")))
        k4 = utils.karta_formularza([self.e_dz, self.e_pz, self.e_cena, self.e_not], "Zakup i uwagi", ft.Icons.SHOPPING_CART)
        k5 = utils.karta_formularza([self.pliki.kontrolka], "Pliki (faktura, zdjęcia opon)", ft.Icons.ATTACH_FILE,
                                    domyslnie_otwarte=bool(self.pliki.pozycje))

        elementy = [k1, k2, k3, k4, k5, utils.przyciski_akcji(page, "Zapisz zestaw", self.zapisz, self.powrot)]

        super().__init__(
            route=f"/magazyn/opony/edytuj/{zestaw_id}" if zestaw_id else "/magazyn/opony/nowy",
            padding=15,
            spacing=15,
            appbar=appbar,
            controls=elementy,
            scroll=ft.ScrollMode.AUTO
        )

    def _migawka_formularza(self):
        return (self.e_sezon.value, self.e_rozmiar.value, self.e_marka.value, self.e_dot.value, self.e_il.value,
                self.e_gl.value, self.e_zam.value, self.e_os.value, self.e_od.value, self.e_miejsce.value,
                self.e_kwit.value, self.e_oplata.value, self.e_na_felgach.value, self.e_felgi.value,
                self.e_dz.value, self.e_pz.value, self.e_cena.value, self.e_not.value, self.pliki.migawka())

    def _czy_zmieniono(self):
        return self._migawka_formularza() != self._stan_poczatkowy

    def zapisz(self, e):
        for pole in (self.e_gl, self.e_il, self.e_cena, self.e_oplata):
            utils.ustaw_blad(pole)

        bledy = []
        glebokosc = None
        if not self.zestaw_id and (self.e_gl.value or "").strip():
            glebokosc = utils.parsuj_float(self.e_gl.value, None)
            if glebokosc is None or glebokosc < 0 or glebokosc > db.MAKS_BIEZNIK:
                bledy.append((self.e_gl, "Podaj sensowną głębokość (0–15 mm)"))

        # Bez `or 4`: wpisane 0 albo wartość ujemna ma trafić na walidację poniżej,
        # a nie zostać po cichu podmienione na 4.
        ilosc = utils.parsuj_int(self.e_il.value, 4)
        if ilosc <= 0 or ilosc > 8:
            bledy.append((self.e_il, "Podaj sensowną ilość opon (1–8)"))

        kwoty = {}
        for pole, nazwa in ((self.e_cena, "cena"), (self.e_oplata, "oplata")):
            kwoty[nazwa] = None
            if (pole.value or "").strip():
                kwoty[nazwa] = utils.parsuj_float(pole.value, None)
                if kwoty[nazwa] is None or kwoty[nazwa] < 0:
                    bledy.append((pole, "Kwota nie może być ujemna"))

        if bledy:
            return utils.pokaz_bledy_formularza(self._page, bledy)

        przebieg_zakupu = (db.dystans_na_km(utils.parsuj_int(self.e_pz.value, None), calkowity=True,
                                            km_przy_otwarciu=self.pz_km)
                           if (self.e_pz.value or "").strip() else None)
        # Pole wyboru nie umie „nie wiadomo”: nieruszone przy pustej kolumnie zostaje puste.
        na_felgach = int(bool(self.e_na_felgach.value))
        if self.na_felgach_pocz is None and not self.e_na_felgach.value:
            na_felgach = None
        wartosci = (self.e_sezon.value, self.e_rozmiar.value, self.e_marka.value, (self.e_dot.value or "").strip(),
                    ilosc, self.e_dz.value, przebieg_zakupu, kwoty["cena"], self.e_not.value,
                    (self.e_miejsce.value or "").strip() or None, (self.e_kwit.value or "").strip() or None,
                    kwoty["oplata"], na_felgach, (self.e_felgi.value or "").strip() or None)
        nowy_id = self.zestaw_id

        with self.pliki.zapis(), db.polacz_baze() as conn:
            cur = conn.cursor()
            if self.zestaw_id:
                cur.execute(f"UPDATE zestawy_opon SET {', '.join(f'{p}=?' for p in self.POLA)} WHERE id=?",
                            wartosci + (self.zestaw_id,))
            else:
                cur.execute(f"INSERT INTO zestawy_opon (auto_id, zamontowane, {', '.join(self.POLA)}) "
                            f"VALUES (?,0,{','.join('?' * len(self.POLA))})", (self.state.auto_id,) + wartosci)
                nowy_id = cur.lastrowid
            self.pliki.zapisz_w(conn, nowy_id, self.state.auto_id)

        if not self.zestaw_id and nowy_id:
            if glebokosc is not None:
                db.zapisz_pomiar(self.state.auto_id, nowy_id, {
                    "data": datetime.now().strftime("%d.%m.%Y"), **{k: glebokosc for k in db.POZYCJE_KOL}})
            if self.e_zam.value:
                db.oznacz_zamontowany_zestaw(self.state.auto_id, nowy_id, self.e_os.value,
                                             data=(self.e_od.value or "").strip() or None)

        utils.wypchnij_w_tle(self._page, self.state.auto_id, "zestaw opon")
        utils.przejdz(self._page, f"/magazyn/opony/{nowy_id}" if self.zestaw_id else "/magazyn")
        if glebokosc is not None and glebokosc < db.BIEZNIK_MINIMUM_PRAWNE:
            utils.pokaz_komunikat(
                self._page,
                f"Zapisano zestaw opon! Uwaga: bieżnik poniżej minimum prawnego "
                f"({db.tekst_bieznika(db.BIEZNIK_MINIMUM_PRAWNE)}).",
                utils.KOLOR_STATUS["warning"]
            )
        else:
            utils.pokaz_komunikat(self._page, "Zapisano zestaw opon!")


class FormularzCzesciView(ft.View):
    def __init__(self, page: ft.Page, state, czesc_id=None):
        self._page = page
        self.state = state
        self.czesc_id = czesc_id

        nazwa_val, kat_val, il_val, jedn_val = "", db.KATEGORIE_MAGAZYNU[0], "1", "szt"
        # Nowa pozycja to zwykle zakup sprzed chwili — data zakupu domyślnie
        # dzisiejsza, bo bez daty cena nie ma swojego miejsca w historii cen.
        cena_val, cena_jedn_val, data_val, not_val = "", "", datetime.now().strftime("%d.%m.%Y"), ""
        prog_val = "1"
        sklep_val, link_val = "", ""

        if czesc_id:
            with db.polacz_baze() as conn:
                c = conn.cursor()
                c.execute(
                    "SELECT nazwa, kategoria, ilosc, jednostka, cena, data_zakupu, notatki, prog_ostrzezenia, cena_jednostkowa, "
                    "sklep, link FROM magazyn_czesci WHERE id=?", (czesc_id,)
                )
                w = c.fetchone()
                if w:
                    nazwa_val = str(w[0] or "")
                    kat_val = str(w[1] or db.KATEGORIE_MAGAZYNU[0])
                    il_val = str(w[2]) if w[2] is not None else "1"
                    jedn_val = str(w[3] or "szt")
                    cena_val = utils.liczba_do_pola(w[4])
                    data_val = str(w[5] or "")
                    not_val = str(w[6] or "")
                    prog_val = str(w[7]) if w[7] is not None else "1"
                    cena_jedn_val = utils.liczba_do_pola(w[8])
                    sklep_val, link_val = str(w[9] or ""), str(w[10] or "")

        self.pliki = utils.PolaZalacznikow(page, "magazyn_czesci", czesc_id, auto_id=state.auto_id)
        self.e_nazwa = ft.TextField(label="Nazwa*", value=nazwa_val, hint_text="np. Olej 5W-30, żarówka H7", **utils.styl_pola())
        self.e_kat = ft.Dropdown(
            label="Kategoria",
            options=[ft.DropdownOption(key=k, text=k) for k in db.KATEGORIE_MAGAZYNU],
            value=kat_val, **utils.styl_dropdown()
        )
        self.e_ilosc = ft.TextField(label="Na stanie", value=il_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola())
        self.e_jedn = ft.Dropdown(
            label="Jednostka",
            options=[ft.DropdownOption(key=j, text=j) for j in db.JEDNOSTKI_MAGAZYNU],
            value=jedn_val, **utils.styl_dropdown()
        )
        self.e_prog = ft.TextField(
            label="Ostrzegaj poniżej", value=prog_val, hint_text="np. 1",
            keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola()
        )
        self.e_cena = ft.TextField(label=f"Koszt zakupu ({utils.symbol_waluty()}, opcjonalnie)", value=cena_val, hint_text="ile zapłaciłeś za całą ilość", keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola())
        self.e_cena_jedn = ft.TextField(label=self._etykieta_ceny_jedn(jedn_val), value=cena_jedn_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola())
        self.e_data = utils.pole_daty(page, "Data zakupu", data_val)
        self.e_not = ft.TextField(label="Notatki", value=not_val, multiline=True, min_lines=2, max_lines=4, **utils.styl_pola())
        # Sklep z podpowiedziami i link do produktu (M-15).
        self.sklep = utils.PoleSklepu(page, db.sklepy_czesci(state.auto_id), sklep_val)
        self.e_sklep = self.sklep.pole
        self.e_link = ft.TextField(label="Link do produktu", value=link_val,
                                   hint_text="np. allegro.pl/oferta/…", keyboard_type=ft.KeyboardType.URL,
                                   prefix_icon=ft.Icons.LINK, **utils.styl_pola())
        # Przy nazwie: ile ta część kosztowała ostatnio. Historia czytana raz —
        # przez czas otwarcia formularza się nie zmienia.
        self._historia_cen = db.historia_cen_pojazdu(state.auto_id)
        self.t_poprzednio = utils.podpis("", visible=False)
        self._pokaz_poprzednie_ceny()
        self.e_nazwa.on_change = utils.z_opoznieniem(page, lambda e: self._pokaz_poprzednie_ceny(odswiez=True))

        # Koszt zakupu i cena za jednostkę liczą się nawzajem przez ilość:
        # wpisujesz to, co wiesz (zwykle kwotę z paragonu), a drugie pole
        # uzupełnia się samo. Pole wpisane ręcznie przestaje być przeliczane —
        # poprawiona cena za litr nie może zniknąć tylko dlatego, że ktoś
        # dopisał ilość.
        self._wyliczane = {"zakup": not cena_val, "jedn": not cena_jedn_val}
        self.e_cena.on_change = lambda e: self._przelicz_ceny("zakup")
        self.e_cena_jedn.on_change = lambda e: self._przelicz_ceny("jedn")
        self.e_ilosc.on_change = lambda e: self._przelicz_ceny("ilosc")
        self.e_jedn.on_select = lambda e: self._zmien_jednostke()

        self._stan_poczatkowy = self._migawka_formularza()
        appbar = utils.zbuduj_pasek_z_powrotem(page, "Edycja pozycji" if czesc_id else "Nowa część / płyn", "/magazyn", on_save=self.zapisz, czy_zmieniono=self._czy_zmieniono)

        wiersz_ilosc = ft.Row([ft.Container(self.e_ilosc, expand=True), ft.Container(self.e_jedn, expand=True)], spacing=10)

        k1 = utils.karta_formularza([self.e_nazwa, self.t_poprzednio, self.e_kat], "Co to jest", ft.Icons.INVENTORY_2, domyslnie_otwarte=True)
        k2 = utils.karta_formularza([wiersz_ilosc, self.e_prog], "Stan magazynowy", ft.Icons.NUMBERS)
        k3 = utils.karta_formularza([
            self.e_cena, self.e_cena_jedn,
            utils.podpis("Cena za jednostkę dolicza się do kosztu wpisu albo wizyty, gdy użyjesz tej części z magazynu."),
            self.e_data,
            utils.podpis("Inna data zakupu niż dotąd to nowy zakup — poprzednia cena zostaje w historii cen. "
                         "Ta sama data poprawia cenę tego zakupu.") if czesc_id else ft.Container(),
            self.sklep.kontrolka, self.e_link, self.e_not,
        ], "Zakup i uwagi", ft.Icons.SHOPPING_CART)
        k4 = utils.karta_formularza([self.pliki.kontrolka], "Pliki (paragon, zdjęcie części)", ft.Icons.ATTACH_FILE,
                                    domyslnie_otwarte=bool(self.pliki.pozycje))

        elementy = [k1, k2, k3, k4, utils.przyciski_akcji(page, "Zapisz pozycję", self.zapisz, "/magazyn")]

        super().__init__(
            route=f"/magazyn/czesci/edytuj/{czesc_id}" if czesc_id else "/magazyn/czesci/nowa",
            padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO
        )

    def _migawka_formularza(self):
        return (self.e_nazwa.value, self.e_kat.value, self.e_ilosc.value, self.e_jedn.value,
                self.e_prog.value, self.e_cena.value, self.e_cena_jedn.value, self.e_data.value, self.e_not.value,
                self.e_sklep.value, self.e_link.value, self.pliki.migawka())

    def _pokaz_poprzednie_ceny(self, odswiez=False):
        """Linijka pod nazwą: ostatnia cena tej części (i najtańsza, jeśli była
        niższa) — przy nowej pozycji wszystkie dotychczasowe zakupy tej nazwy,
        przy edycji te sprzed bieżącego zakupu pozycji."""
        punkty = db.historia_cen_czesci(self.state.auto_id, self.e_nazwa.value, self._historia_cen)
        tekst = utils.podpowiedz_ceny(punkty, self.czesc_id)
        self.t_poprzednio.value = tekst
        self.t_poprzednio.visible = bool(tekst)
        if odswiez:
            self._odswiez()

    def _czy_zmieniono(self):
        return self._migawka_formularza() != self._stan_poczatkowy

    @staticmethod
    def _etykieta_ceny_jedn(jednostka):
        return f"Cena za 1 {jednostka or 'szt'} ({utils.symbol_waluty()})"

    def _zmien_jednostke(self):
        self.e_cena_jedn.label = self._etykieta_ceny_jedn(self.e_jedn.value)
        self._odswiez()

    def _przelicz_ceny(self, zrodlo):
        """Uzupełnia pole wyliczane z drugiego pola i ilości (patrz _wyliczane)."""
        ilosc = utils.parsuj_float(self.e_ilosc.value, None)
        zakup = utils.parsuj_float(self.e_cena.value, None) if (self.e_cena.value or "").strip() else None
        jedn = utils.parsuj_float(self.e_cena_jedn.value, None) if (self.e_cena_jedn.value or "").strip() else None

        if zrodlo == "zakup":
            self._wyliczane["zakup"] = zakup is None
        elif zrodlo == "jedn":
            self._wyliczane["jedn"] = jedn is None

        if zrodlo in ("zakup", "ilosc") and self._wyliczane["jedn"] and not self._wyliczane["zakup"]:
            self.e_cena_jedn.value = utils.liczba_do_pola(db.cena_jednostkowa_z_zakupu(zakup, ilosc))
        elif zrodlo in ("jedn", "ilosc") and self._wyliczane["zakup"] and not self._wyliczane["jedn"]:
            wyliczony = round(jedn * ilosc, 2) if jedn is not None and ilosc is not None and ilosc > 0 else None
            self.e_cena.value = utils.liczba_do_pola(wyliczony)
        elif zrodlo == "zakup" and self._wyliczane["zakup"] and self._wyliczane["jedn"]:
            self.e_cena_jedn.value = ""
        elif zrodlo == "jedn" and self._wyliczane["jedn"] and self._wyliczane["zakup"]:
            self.e_cena.value = ""
        self._odswiez()

    def _odswiez(self):
        try:
            self._page.update()
        except Exception:
            log.polkniety("odświeżenie formularza pozycji magazynu")

    def zapisz(self, e):
        for pole in (self.e_nazwa, self.e_ilosc, self.e_cena, self.e_cena_jedn, self.e_prog, self.e_link):
            utils.ustaw_blad(pole)

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

        # Cena za jednostkę jest tym, co naprawdę trafia do kosztu serwisu. Puste
        # pole przy znanym koszcie zakupu i ilości liczymy tak samo, jak robi to
        # formularz na żywo — zapis nie może zależeć od tego, czy zdarzenie
        # zmiany pola zdążyło dojść.
        cena_jedn = None
        if (self.e_cena_jedn.value or "").strip():
            cena_jedn = utils.parsuj_float(self.e_cena_jedn.value, None)
            if cena_jedn is None or cena_jedn < 0:
                bledy.append((self.e_cena_jedn, "Podaj poprawną cenę"))
        elif cena is not None and ilosc:
            cena_jedn = db.cena_jednostkowa_z_zakupu(cena, ilosc)

        prog = utils.parsuj_float(self.e_prog.value, 1.0)
        if prog < 0:
            bledy.append((self.e_prog, "Próg nie może być ujemny"))

        blad_linku = db.blad_linku(self.e_link.value)
        if blad_linku:
            bledy.append((self.e_link, blad_linku))

        if bledy:
            return utils.pokaz_bledy_formularza(self._page, bledy)

        # „inter cars” zapisuje się jako istniejące „Inter Cars” — jak stacje paliw.
        sklep = db.dopasuj_sklep(self.state.auto_id, self.e_sklep.value)
        link = db.normalizuj_link(self.e_link.value)

        with self.pliki.zapis(), db.polacz_baze() as conn:
            # Pozycja sprzed zapisu — z bazy, nie z chwili otwarcia formularza:
            # druga osoba mogła ją w międzyczasie zmienić (historia cen porównuje
            # datę zakupu przed i po).
            przed = None
            if self.czesc_id:
                kolumny = ("id", "nazwa", "ilosc", "jednostka", "cena_jednostkowa", "data_zakupu", "sklep")
                wiersz = conn.execute(
                    f"SELECT {', '.join(kolumny)} FROM magazyn_czesci WHERE id=?", (self.czesc_id,)
                ).fetchone()
                przed = dict(zip(kolumny, wiersz)) if wiersz else None
                conn.execute(
                    "UPDATE magazyn_czesci SET nazwa=?, kategoria=?, jednostka=?, cena=?, cena_jednostkowa=?, data_zakupu=?, notatki=?, prog_ostrzezenia=?, "
                    "sklep=?, link=? WHERE id=?",
                    (nazwa, self.e_kat.value, self.e_jedn.value, cena, cena_jedn, self.e_data.value, self.e_not.value, prog,
                     sklep, link, self.czesc_id)
                )
                # Ilość z formularza to korekta stanu na półce: zmienia stan wyjściowy, a zużycie
                # z innych telefonów dalej się od niego odejmuje (db/stan_magazynu.py).
                db.ustaw_stan_magazynu(conn, self.czesc_id, ilosc)
                czesc_id = self.czesc_id
            else:
                kursor = conn.execute(
                    "INSERT INTO magazyn_czesci (auto_id, nazwa, kategoria, ilosc, ilosc_bazowa, jednostka, cena, cena_jednostkowa, data_zakupu, notatki, prog_ostrzezenia, sklep, link) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (self.state.auto_id, nazwa, self.e_kat.value, ilosc, ilosc, self.e_jedn.value, cena, cena_jedn, self.e_data.value, self.e_not.value, prog,
                     sklep, link)
                )
                czesc_id = kursor.lastrowid
            # Historia cen (M-15): nowa data zakupu = nowy zakup, ta sama = poprawka.
            db.zanotuj_zakup_czesci(conn, self.state.auto_id, przed, {
                "id": czesc_id, "nazwa": nazwa, "ilosc": ilosc, "jednostka": self.e_jedn.value,
                "cena_jednostkowa": cena_jedn, "data_zakupu": self.e_data.value, "sklep": sklep,
            })
            self.pliki.zapisz_w(conn, czesc_id, self.state.auto_id)

        utils.wypchnij_w_tle(self._page, self.state.auto_id, "magazyn")
        utils.przejdz(self._page, "/magazyn")
        utils.pokaz_komunikat(self._page, "Zapisano pozycję magazynu!")