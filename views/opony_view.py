"""Ekran kompletu opon (`/magazyn/opony/<id>`): stan, bieżnik kół z prognozą, pomiary i sezony na aucie;
formularz pomiaru bieżnika czterech kół. Dane: db/opony.py; okna zmiany i sezonu: utils/opony.py."""

from datetime import datetime

import flet as ft

import db
import log
import sync
import utils


def _z_wielkiej(zdanie):
    return zdanie[:1].upper() + zdanie[1:] if zdanie else zdanie


class KompletOponView(ft.View):
    def __init__(self, page: ft.Page, state, zestaw_id=None):
        self._page = page
        self.state = state
        self.zestaw_id = zestaw_id
        trasa = f"/magazyn/opony/{zestaw_id}" if zestaw_id else "/magazyn/opony"
        self.dane = db.dane_opon(state.auto_id) if state.auto_id else None
        self.k = next((k for k in (self.dane or {}).get("komplety", []) if k["id"] == zestaw_id), None)
        akcje = None
        if state.auto_id and sync.czy_udostepniony(state.auto_id)[0]:
            akcje = [utils.przycisk_synchronizacji(page, utils.funkcja_szybkiej_synchronizacji(page, state.auto_id, trasa))]
        tytul = f"{self.k['sezon']} — komplet" if self.k and self.k["sezon"] else "Komplet opon"
        appbar = utils.zbuduj_pasek_z_powrotem(page, tytul, "/magazyn", akcje_dodatkowe=akcje, ikona=ft.Icons.TIRE_REPAIR)

        if not self.k:
            super().__init__(route=trasa, padding=15, spacing=15, appbar=appbar, controls=[utils.ekran_braku_danych(
                ikona=ft.Icons.TIRE_REPAIR, tytul="Nie ma takiego kompletu",
                opis="Mógł zostać usunięty albo należy do innego pojazdu. Wszystkie komplety są w Magazynie.",
                tekst_przycisku="Wróć do opon", on_click=lambda e: self._idz("/magazyn"),
            )])
            return

        self.state.magazyn_zakladka = 0
        self.moge = db.czy_moge_dodawac(state.auto_id)
        self.j = utils.jednostka_dystansu()
        self.scena = utils.ScenaWejscia(
            wlaczona=db.czy_animacje_interfejsu() and utils.pierwsze_pokazanie(state, f"komplet-opon:{zestaw_id}",
                                                                             state.auto_id),
            kaskada=True,
        )
        elementy = [self._naglowek(), self._bieznik(), self._pomiary(), self._sezony(), self._nota(),
                    utils.dol_bezpieczny(80)]
        fab = utils.fab_animowany(ft.Icons.ADD, lambda e: self._idz(f"/magazyn/opony/{zestaw_id}/pomiar"),
                                  tooltip="Dodaj pomiar bieżnika") if self.moge else None
        super().__init__(route=trasa, padding=15, spacing=12, appbar=appbar, floating_action_button=fab,
                         controls=[e for e in elementy if e is not None], scroll=ft.ScrollMode.AUTO)
        self.scena.uruchom(page)

    def _idz(self, trasa):
        utils.przejdz(self._page, trasa)

    # ================= NAGŁÓWEK =================

    def _naglowek(self):
        k = self.k
        tresc = [ft.Row([utils.ikona_sezonu(k["sezon"], 22),
                         utils.wartosc(k["sezon"] or "Komplet opon", size=utils.FS["title"], expand=True),
                         utils.chip_kompletu(self._page, k)], spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER)]
        if utils.opis_kompletu(k):
            tresc.append(utils.podpis(utils.opis_kompletu(k), max_lines=2))
        wiek = k["wiek"]
        if wiek:
            tresc.append(utils.pole("Wiek", f"{db.tekst_wieku(wiek)} · produkcja {wiek['data']:%m.%Y}"
                                    + (f" (najstarsza z {wiek['kodow']})" if wiek["kodow"] > 1 else ""),
                                    color=utils.kolor_wieku(wiek)))
            if utils.opis_wieku(wiek):
                tresc.append(utils.podpis(_z_wielkiej(utils.opis_wieku(wiek, z_wiekiem=False)),
                                          color=utils.kolor_wieku(wiek), max_lines=3))
        elif k["numer_dot"]:
            tresc.append(utils.podpis(f"DOT {k['numer_dot']} — nie widzę w nim daty produkcji (TTRR)", max_lines=2))
        if k["km"] or k["km_biezacy"]:
            km = utils.formatuj_dystans(k["km"], 0, self.j) if k["km"] else "—"
            if k["km_biezacy"] and k["zamontowany"]:
                km += f" · w tym sezonie {utils.formatuj_dystans(k['km_biezacy'], 0, self.j)}"
            tresc.append(utils.pole("Przejechane na komplecie", km))
        if k["na_felgach"] is not None or k["felgi"]:
            felgi = ("Na felgach" if k["na_felgach"] else "Same opony, bez felg") if k["na_felgach"] is not None else "Felgi"
            tresc.append(utils.pole("Felgi", " · ".join(x for x in (felgi, k["felgi"]) if x)))
        przechowalnia = [k["miejsce"], f"kwit {k['numer_kwitu']}" if k["numer_kwitu"] else None,
                         f"{utils.formatuj_liczba(k['oplata_przechowania'])} {utils.symbol_waluty()} za sezon"
                         if k["oplata_przechowania"] else None]
        if any(przechowalnia):
            tresc.append(utils.pole("Gdzie leży" if not k["zamontowany"] else "Przechowalnia",
                                    " · ".join(x for x in przechowalnia if x)))
        zakup = [k["data_zakupu"] or None,
                 f"{utils.formatuj_liczba(k['cena'])} {utils.symbol_waluty()}" if (k["cena"] or 0) > 0 else None]
        if k["koszt_1000"]:
            zakup.append(f"{utils.formatuj_liczba(db.na_jednostke_dystansu(k['koszt_1000'], self.j))} "
                         f"{utils.symbol_waluty()} / 1000 {db.slowo_dystansu('skrot', self.j)}")
        if any(zakup):
            tresc.append(utils.pole("Zakup", " · ".join(x for x in zakup if x)))
        if k["notatki"]:
            tresc.append(utils.podpis(k["notatki"], italic=True, max_lines=4))

        akcje = []
        if self.moge and not (k["zamontowany"] and k["os"] == "Wszystkie"):
            akcje.append(ft.FilledButton("Załóż na auto", icon=ft.Icons.SWAP_HORIZ,
                                         on_click=lambda e: self._zaloz("Wszystkie")))
            akcje.append(ft.TextButton("Na jedną oś", icon=ft.Icons.SWAP_VERT, on_click=lambda e: self._menu_osi()))
        if self.moge:
            akcje.append(ft.TextButton("Edytuj", icon=ft.Icons.EDIT,
                                       on_click=lambda e: self._idz(f"/magazyn/opony/edytuj/{k['id']}")))
            akcje.append(ft.TextButton("Usuń", icon=ft.Icons.DELETE, on_click=lambda e: self._usun(),
                                       style=ft.ButtonStyle(color=utils.KOLOR_STATUS["destructive"])))
        if akcje:
            tresc.append(utils.pasek_zawijany(akcje, spacing=4))
        return ft.Container(padding=utils.SPACING["md"], **utils.powierzchnia(self._page, "karta",
                                                                              stan=utils.stan_kompletu(k)),
                            content=ft.Column(tresc, spacing=8))

    def _zaloz(self, os_montazu):
        utils.okno_zmiany_opon(self._page, self.state, self.k["id"], os_montazu)

    def _menu_osi(self):
        utils.pokaz_menu_kontekstowe(self._page, "Załóż na jedną oś", [
            {"ikona": ft.Icons.ARROW_UPWARD, "tekst": "Na przednią oś", "akcja": lambda: self._zaloz("Przód")},
            {"ikona": ft.Icons.ARROW_DOWNWARD, "tekst": "Na tylną oś", "akcja": lambda: self._zaloz("Tył")},
        ])

    def _usun(self):
        def wykonaj():
            wynik = db.usun_z_cofnieciem("zestawy_opon", self.k["id"])
            self._idz("/magazyn")
            utils.pokaz_komunikat_cofnij(self._page, "Usunięto komplet opon.", wynik)
        utils.potwierdz(self._page, "Usunąć komplet?", "Razem z nim znikną jego pomiary bieżnika i sezony na aucie.",
                        wykonaj)

    # ================= BIEŻNIK =================

    def _bieznik(self):
        k = self.k
        pomiar = k["ostatni_pomiar"]
        tresc = [utils.wartosc("Bieżnik")]
        if not pomiar:
            tresc.append(utils.podpis("Zmierz bieżnik każdego koła miarką albo monetą — z kolejnych pomiarów policzę "
                                      "tempo zużycia i to, ile sezonów zostało.", max_lines=4))
        else:
            kiedy = [pomiar["data"] or "data nieznana"]
            if pomiar["dawny"]:
                kiedy.append("zapisany w komplecie")
            tresc.append(utils.podpis(" · ".join(kiedy)))
            tresc.append(utils.schemat_kol(self._page, pomiar, k["sezon"]))
            tresc.append(utils.pasek_bieznika(k, self.scena))
            prognoza = k["prognoza"]
            if prognoza:
                if pomiar["min"] - prognoza["teraz_mm"] >= 0.2:
                    tresc.append(utils.podpis(f"Dziś szacunkowo {db.tekst_bieznika(prognoza['teraz_mm'])} "
                                              f"({db.tekst_bieznika(prognoza['tempo'])} na 1000 "
                                              f"{db.slowo_dystansu('skrot', self.j)})", max_lines=2))
                else:
                    tresc.append(utils.podpis(f"Zużycie {db.tekst_bieznika(prognoza['tempo'])} na 1000 "
                                              f"{db.slowo_dystansu('skrot', self.j)}", max_lines=2))
                tresc.append(utils.wartosc(_z_wielkiej(db.opis_prognozy(prognoza, self.j)), size=utils.FS["body"],
                                           max_lines=2))
                if prognoza["data"] and prognoza["zostalo_km"]:
                    tresc.append(utils.podpis(f"W tym tempie ok. {prognoza['data']:%m.%Y}", max_lines=2))
            elif len([p for p in k["pomiary"] if p["min"] is not None]) < 2:
                tresc.append(utils.podpis("Prognoza ruszy po drugim pomiarze, gdy komplet przejedzie co najmniej "
                                          f"{utils.formatuj_dystans(db.MIN_KM_TEMPA, 0, self.j)}.", max_lines=3))
            else:
                tresc.append(utils.podpis("Za mały spadek bieżnika albo przebieg między pomiarami, żeby liczyć tempo.",
                                          max_lines=3))
            for zdanie, kolor in ((utils.opis_bieznika_ponizej(k), utils.kolor_bieznika(k["status_bieznika"])),
                                  (utils.wskazowka_osi(k), utils.KOLOR_STATUS["warning"])):
                if zdanie:
                    tresc.append(utils.podpis(_z_wielkiej(zdanie), color=kolor, max_lines=3))
        if self.moge:
            tresc.append(ft.Row([ft.TextButton("Dodaj pomiar", icon=ft.Icons.ADD,
                                               on_click=lambda e: self._idz(f"/magazyn/opony/{k['id']}/pomiar"))],
                                alignment=ft.MainAxisAlignment.END))
        return ft.Container(padding=utils.SPACING["md"], **utils.powierzchnia(self._page, "karta"),
                            content=ft.Column(tresc, spacing=8))

    # ================= POMIARY =================

    def _wiersz_pomiaru(self, p):
        kola = " · ".join(f"{db.SKROTY_KOL[kolo]} {utils.formatuj_liczba(mm, 1)}" for kolo, mm in p["kola"].items())
        zdanie = [kola]
        if p["przebieg"]:
            zdanie.append(f"licznik {utils.formatuj_dystans(p['przebieg'], 0, self.j)}")
        if p["dodane_przez"]:
            zdanie.append(p["dodane_przez"])
        opis = [utils.podpis(" · ".join(zdanie), max_lines=2)]
        if p["uwagi"]:
            opis.append(utils.podpis(p["uwagi"], italic=True, max_lines=2))
        kolor = utils.kolor_bieznika(db.status_bieznika(p["min"], self.k["sezon"]))
        wiersz = ft.Row([
            ft.Icon(ft.Icons.SQUARE_FOOT, size=16, color=kolor),
            ft.Column([ft.Row([utils.wartosc(utils.tekst_zakresu_bieznika(p) or "—", color=kolor),
                               utils.etykieta(p["data"] or "zapisany w komplecie")], spacing=8, wrap=True),
                       *opis], spacing=2, tight=True, expand=True),
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.START)
        if p["dawny"] or not db.czy_moge_zmieniac_rekord(self.state.auto_id, "pomiary_bieznika", p["dodane_przez"]):
            return ft.Container(padding=ft.Padding(0, 6, 0, 6), content=wiersz)
        return ft.Container(padding=ft.Padding(0, 6, 0, 6), ink=True, border_radius=utils.RADIUS["sm"],
                            on_click=lambda e, pomiar=p: self._menu_pomiaru(pomiar), content=wiersz)

    def _menu_pomiaru(self, p):
        def usun():
            wynik = db.usun_pomiar_z_cofnieciem(p["id"])
            utils.odswiez_ekran(self._page)
            utils.pokaz_komunikat_cofnij(self._page, "Usunięto pomiar.", wynik)

        utils.pokaz_menu_kontekstowe(self._page, f"Pomiar {p['data']}", [
            {"ikona": ft.Icons.EDIT, "tekst": "Popraw pomiar",
             "akcja": lambda: self._idz(f"/magazyn/opony/pomiar/edytuj/{p['id']}")},
            {"ikona": ft.Icons.DELETE, "tekst": "Usuń pomiar", "kolor": utils.KOLOR_STATUS["destructive"],
             "akcja": usun},
        ])

    def _pomiary(self):
        pomiary = list(reversed(self.k["pomiary"]))
        if len(pomiary) < 2 and not (pomiary and pomiary[0]["uwagi"]):
            return None
        tresc = [utils.wartosc(f"Pomiary ({len(pomiary)})")] + [self._wiersz_pomiaru(p) for p in pomiary]
        return ft.Container(padding=utils.SPACING["md"], **utils.powierzchnia(self._page, "karta"),
                            content=ft.Column(tresc, spacing=2))

    # ================= SEZONY NA AUCIE =================

    def _wiersz_okresu(self, m):
        if m["data_zdjecia"]:
            kiedy = f"{m['data']} – {m['data_zdjecia']}"
        else:
            kiedy = f"od {m['data']}" + (" · trwa" if m["trwa"] else "")
        zdanie = []
        if m["km"] is not None and (m["km"] or not m["trwa"]):
            zdanie.append(utils.formatuj_dystans(m["km"], 0, self.j))
        elif m["trwa"] and m["km"] == 0:
            zdanie.append("dopiero założony")
        elif m["data_zdjecia"] or m["trwa"]:
            zdanie.append(f"bez licznika — {db.slowo_dystansu('mianownik', self.j).lower()} nieznane")
        else:
            zdanie.append("zdjęty na innym telefonie — dzień zdjęcia nieznany")
        if m["os_montazu"] != "Wszystkie":
            zdanie.append(utils.OSIE_SLOWAMI.get(m["os_montazu"], m["os_montazu"]))
        wiersz = ft.Row([
            ft.Icon(ft.Icons.EVENT_REPEAT, size=16, color=utils.KOLOR_STATUS["ok"] if m["trwa"] else None),
            ft.Column([utils.wartosc(kiedy, size=utils.FS["body"]), utils.podpis(" · ".join(zdanie), max_lines=2)],
                      spacing=2, tight=True, expand=True),
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.START)
        if not self.moge:
            return ft.Container(padding=ft.Padding(0, 6, 0, 6), content=wiersz)
        return ft.Container(padding=ft.Padding(0, 6, 0, 6), ink=True, border_radius=utils.RADIUS["sm"],
                            on_click=lambda e, okres=m: utils.okno_okresu_montazu(self._page, self.state, okres),
                            content=wiersz)

    def _sezony(self):
        k = self.k
        tresc = [utils.wartosc("Sezony na aucie")]
        if self.moge and k["zamontowany"] and not k["otwarty"]:
            tresc.append(utils.podpis("Od kiedy ten komplet jest na aucie? Bez tego dnia nie policzę jego kilometrów.",
                                      max_lines=3))
            tresc.append(ft.Row([ft.TextButton("Ustaw dzień założenia", icon=ft.Icons.EVENT,
                                               on_click=lambda e: utils.okno_poczatku_montazu(self._page, self.state,
                                                                                              k["id"]))],
                                alignment=ft.MainAxisAlignment.END))
        if self.moge and self.dane["do_odtworzenia"] and not self.dane["jest_dziennik"]:
            tresc.append(utils.podpis(f"W Serwisie są zmiany opon z rodzajem opon "
                                      f"({self.dane['do_odtworzenia']}) — mogę odtworzyć z nich sezony kompletów.",
                                      max_lines=3))
            tresc.append(ft.Row([ft.TextButton("Odtwórz z Serwisu", icon=ft.Icons.HISTORY,
                                               on_click=lambda e: self._odtworz())],
                                alignment=ft.MainAxisAlignment.END))
        okresy = list(reversed(k["montaze"]))
        if okresy:
            tresc += [self._wiersz_okresu(m) for m in okresy]
        elif not k["zamontowany"]:
            tresc.append(utils.podpis("Sezony zapisują się same przy każdej zmianie opon.", max_lines=2))
        return ft.Container(padding=utils.SPACING["md"], **utils.powierzchnia(self._page, "karta"),
                            content=ft.Column(tresc, spacing=4))

    def _odtworz(self):
        ile = db.odtworz_sezony_z_serwisu(self.state.auto_id)
        utils.wypchnij_w_tle(self._page, self.state.auto_id, "sezony opon")
        utils.odswiez_ekran(self._page)
        utils.pokaz_komunikat(self._page, f"Odtworzono sezony: {ile}." if ile else
                              "Nie było czego odtworzyć — sezon da się przypisać tylko kompletowi jedynemu w swojej porze roku.",
                              utils.KOLOR_STATUS["ok"] if ile else utils.KOLOR_STATUS["warning"])

    def _nota(self):
        j = self.j
        skrot = db.slowo_dystansu("skrot", j)
        return utils.nota_o_liczeniu(self._page, "Jak liczone", (
            f"{db.slowo_dystansu('mianownik', j)} kompletu to przebieg auta w sezonach, gdy był "
            "założony — zapisują je zmiany opon. Z pomiarów i tych przebiegów wychodzi tempo zużycia najpłytszego koła "
            f"(mm na 1000 {skrot}, od {utils.formatuj_dystans(db.MIN_KM_TEMPA, 0, j)} między pomiarami), a z niego — "
            f"ile zostało do {db.tekst_bieznika(db.PROGI_WYMIANY_BIEZNIKA['Letnie'])} w oponach letnich i "
            f"{db.tekst_bieznika(db.PROGI_WYMIANY_BIEZNIKA['Zimowe'])} w zimowych i całorocznych (zalecenia "
            f"producentów; minimum prawne to {db.tekst_bieznika(db.BIEZNIK_MINIMUM_PRAWNE)}). Sezony liczą się "
            "przebiegiem tego kompletu w poprzednich sezonach, a bez nich — średnią jazdą auta w jego miesiącach. "
            "Wiek to czas od daty produkcji z kodu DOT (cztery cyfry: tydzień i rok); od "
            f"{db.WIEK_KONTROLI_OPON} lat opony warto co roku obejrzeć, po {db.WIEK_WYMIANY_OPON} — wymienić "
            "niezależnie od bieżnika."))


class FormularzPomiaruView(ft.View):
    def __init__(self, page: ft.Page, state, zestaw_id=None, pomiar_id=None):
        self._page = page
        self.state = state
        self.pomiar = db.pobierz_pomiar(pomiar_id) if pomiar_id else None
        if self.pomiar:
            zestaw_id = self.pomiar["zestaw_id"]
        self.zestaw_id = zestaw_id
        self.pomiar_id = self.pomiar["id"] if self.pomiar else None
        self.k = db.komplet_opon(state.auto_id, zestaw_id) if state.auto_id and zestaw_id else None
        trasa = (f"/magazyn/opony/pomiar/edytuj/{self.pomiar_id}" if self.pomiar_id
                 else f"/magazyn/opony/{zestaw_id}/pomiar" if zestaw_id else "/magazyn/opony/pomiar")
        self.powrot = f"/magazyn/opony/{zestaw_id}" if self.k else "/magazyn"

        if not self.k or (pomiar_id and not self.pomiar):
            appbar = utils.zbuduj_pasek_z_powrotem(page, "Pomiar bieżnika", self.powrot, ikona=ft.Icons.SQUARE_FOOT)
            super().__init__(route=trasa, padding=15, spacing=15, appbar=appbar, controls=[utils.ekran_braku_danych(
                ikona=ft.Icons.TIRE_REPAIR, tytul="Nie ma takiego kompletu",
                opis="Pomiar zapisuje się przy komplecie opon — wybierz go w Magazynie.",
                tekst_przycisku="Wróć do opon", on_click=lambda e: utils.przejdz(self._page, "/magazyn"),
            )])
            return

        wstepny = getattr(state, "pomiar_wstepny", None) or {}
        state.pomiar_wstepny = None
        if self.pomiar:
            data_pocz, km_pocz = self.pomiar["data"], self.pomiar["przebieg"]
        else:
            data_pocz = wstepny.get("data") or datetime.now().strftime("%d.%m.%Y")
            km_pocz = wstepny.get("przebieg") or (
                (db.szacuj_przebieg_w_dniu(state.auto_id, data_pocz) or db.pobierz_aktualny_przebieg(state.auto_id))
                if self.k["zamontowany"] else None)
        self.km_pocz = km_pocz or None
        self.e_data = utils.pole_daty(page, "Dzień pomiaru", data_pocz)
        self.e_przebieg = ft.TextField(label=f"Licznik auta ({utils.jednostka_dystansu()}, opcjonalnie)",
                                       value=db.wartosc_pola_dystansu(self.km_pocz) if self.km_pocz else "",
                                       keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola())
        self.e_kola = {}
        for kolo in db.POZYCJE_KOL:
            wartosc = (self.pomiar or {}).get(kolo)
            pole = ft.TextField(label=utils.NAZWY_KOL[kolo], value=utils.liczba_do_pola(wartosc) if wartosc is not None
                                else "", suffix="mm", keyboard_type=ft.KeyboardType.NUMBER, expand=True, **utils.styl_pola())
            pole.on_blur = lambda e, k=kolo: self._przepisz(k)
            self.e_kola[kolo] = pole
        self.e_uwagi = ft.TextField(label="Uwagi (opcjonalnie)", value=(self.pomiar or {}).get("uwagi") or "",
                                    multiline=True, min_lines=1, max_lines=3, **utils.styl_pola())

        self._stan_poczatkowy = self._migawka_formularza()
        tytul = "Poprawka pomiaru" if self.pomiar else "Pomiar bieżnika"
        appbar = utils.zbuduj_pasek_z_powrotem(page, tytul, self.powrot, on_save=self.zapisz,
                                               czy_zmieniono=self._czy_zmieniono, ikona=ft.Icons.SQUARE_FOOT)
        opis = " · ".join(x for x in (utils.nazwa_kompletu(self.k), utils.opis_kompletu(self.k)) if x)
        siatka = ft.Column([
            utils.etykieta("przód"),
            ft.Row([self.e_kola["lp"], self.e_kola["pp"]], spacing=utils.SPACING["sm"]),
            ft.Row([self.e_kola["lt"], self.e_kola["pt"]], spacing=utils.SPACING["sm"]),
            utils.etykieta("tył"),
            utils.podpis("Wpisz pierwsze koło — pozostałe przepiszą się same; popraw te, które się różnią. "
                         f"Zalecana wymiana poniżej {db.tekst_bieznika(self.k['prog_wymiany'])}.", max_lines=3),
        ], spacing=utils.SPACING["sm"], horizontal_alignment=ft.CrossAxisAlignment.CENTER)
        elementy = [
            utils.podpis(opis, max_lines=2),
            utils.karta_formularza([utils.na_cala_szerokosc(self.e_data), utils.na_cala_szerokosc(self.e_przebieg)],
                                   "Kiedy", ft.Icons.EVENT,
                                   domyslnie_otwarte=True, page=page),
            utils.karta_formularza([siatka], "Bieżnik kół", ft.Icons.SQUARE_FOOT, domyslnie_otwarte=True, page=page),
            utils.karta_formularza([utils.na_cala_szerokosc(self.e_uwagi)], "Uwagi", ft.Icons.NOTES,
                                   domyslnie_otwarte=bool(self.e_uwagi.value), page=page),
            utils.przyciski_akcji(page, "Zapisz pomiar", self.zapisz, self.powrot),
        ]
        super().__init__(route=trasa, padding=15, spacing=15, appbar=appbar, controls=elementy,
                         scroll=ft.ScrollMode.AUTO)

    def _przepisz(self, kolo):
        """Pierwsza wpisana liczba trafia do pustych kół — zwykle różnią się o dziesiąte."""
        wartosc = (self.e_kola[kolo].value or "").strip()
        reszta = [p for k, p in self.e_kola.items() if k != kolo]
        if not wartosc or utils.parsuj_float(wartosc, None) is None or any((p.value or "").strip() for p in reszta):
            return
        for pole in reszta:
            pole.value = wartosc
        try:
            self.update()
        except Exception:
            log.polkniety("przepisanie bieżnika na pozostałe koła")

    def _migawka_formularza(self):
        return (self.e_data.value, self.e_przebieg.value, self.e_uwagi.value,
                *(p.value for p in self.e_kola.values()))

    def _czy_zmieniono(self):
        return self._migawka_formularza() != self._stan_poczatkowy

    def zapisz(self, e):
        for pole in (self.e_przebieg, *self.e_kola.values()):
            utils.ustaw_blad(pole)
        km, blad_km = None, None
        if (self.e_przebieg.value or "").strip():
            km = db.dystans_na_km(self.e_przebieg.value, calkowity=True, km_przy_otwarciu=self.km_pocz)
            if not km or km <= 0:
                blad_km = "Podaj poprawny stan licznika"
        dane = {"data": self.e_data.value, "przebieg": km, "uwagi": self.e_uwagi.value,
                **{k: p.value for k, p in self.e_kola.items()}}
        blad = db.blad_pomiaru(dane)
        if blad or blad_km:
            bledy = [(self.e_przebieg, blad_km)] if blad_km else []
            if blad:
                cel = next((p for k, p in self.e_kola.items() if (p.value or "").strip()
                            and db.blad_pomiaru({"data": "01.01.2026", k: p.value})), self.e_kola["lp"])
                bledy.append((cel, blad))
            return utils.pokaz_bledy_formularza(self._page, bledy)
        wynik = db.zapisz_pomiar(self.state.auto_id, self.zestaw_id, dane, self.pomiar_id)
        if not wynik:
            return utils.pokaz_komunikat(self._page, "Nie zapisano pomiaru: brak uprawnień albo kompletu już nie ma.",
                                         utils.KOLOR_STATUS["error"])
        utils.wypchnij_w_tle(self._page, self.state.auto_id, "pomiar bieżnika")
        utils.przejdz(self._page, self.powrot)
        k = db.komplet_opon(self.state.auto_id, self.zestaw_id) or {}
        komunikat = "Zapisano pomiar."
        if k.get("status_bieznika") in (db.STATUS_BIEZNIKA_UWAGA, db.STATUS_BIEZNIKA_KRYTYCZNY):
            komunikat += f" Uwaga: {utils.opis_bieznika_ponizej(k)}."
            return utils.pokaz_komunikat(self._page, komunikat, utils.KOLOR_STATUS["warning"])
        utils.pokaz_komunikat(self._page, komunikat)


__all__ = [
    "FormularzPomiaruView",
    "KompletOponView",
]
