"""„Leasing i kredyt” (M-22): karta umowy (do spłaty, pasek zapłaconych, najbliższa
płatność, ostatnia rata, wykup, odsetki, kapitał) i rozwijany harmonogram z rozbiciem
rat. Liczy db.harmonogram_umowy (jak formularz, kafelek „Do spłaty” i Karta pojazdu).
„Zapłacono” płaci KOLEJNĄ pozycję (db.oznacz_zaplacony_wydatek_cykliczny →
db.zaplac_rate) z kosztem w Innych kosztach i „Cofnij”."""

from datetime import datetime

import flet as ft

import db
import log
import utils


# Słowa w nazwie wydatku cyklicznego, po których zgadujemy, że to rata
# wpisana jeszcze bez harmonogramu (podpowiedź „Przestaw na raty”).
SLOWA_RATY = ("rata", "raty", "leasing", "kredyt", "pożycz", "pozycz")


class RatyView(ft.View):
    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state
        self.podglad = bool(state.auto_id) and db.czy_tylko_podglad(state.auto_id)

        akcje = None
        if state.auto_id and not self.podglad:
            akcje = [ft.IconButton(
                ft.Icons.ADD, icon_color=ft.Colors.PRIMARY, tooltip="Dodaj leasing lub kredyt",
                on_click=lambda e: utils.przejdz(self._page, "/raty/nowa"),
            )]
        appbar = utils.zbuduj_pasek_z_powrotem(page, "Leasing i kredyt", "/", akcje_dodatkowe=akcje,
                                               ikona=ft.Icons.ACCOUNT_BALANCE)

        if not state.auto_id:
            super().__init__(
                route="/raty", padding=15, spacing=15, appbar=appbar,
                controls=[utils.ekran_braku_danych(
                    ikona=ft.Icons.DIRECTIONS_CAR,
                    tytul="Brak wybranego pojazdu",
                    opis="Dodaj pojazd, aby prowadzić jego leasing albo kredyt.",
                    tekst_przycisku="Dodaj pojazd",
                    on_click=lambda e: utils.przejdz(self._page, "/auto/nowy"),
                )],
            )
            return

        # Paski rat ruszają od zera raz na uruchomienie aplikacji — jak na
        # Karcie pojazdu i w „Ile zostało do…”.
        self.scena = utils.ScenaWejscia(
            wlaczona=db.czy_animacje_interfejsu() and utils.pierwsze_pokazanie(state, "raty", state.auto_id),
            kaskada=True,
        )
        self.umowy = db.pobierz_raty(state.auto_id)
        super().__init__(
            route="/raty", padding=15, spacing=12, appbar=appbar,
            controls=self._elementy(), scroll=ft.ScrollMode.AUTO,
        )
        self.scena.uruchom(page)

    # ================= SKŁAD EKRANU =================

    def _elementy(self):
        elementy = []
        if not self.umowy:
            elementy.append(self._pusto())
        else:
            naglowek = self._naglowek()
            if naglowek is not None:
                elementy.append(naglowek)
            for umowa in self.umowy:
                elementy.append(self._karta_umowy(umowa))
                if umowa["harmonogram"]["kompletna"]:
                    elementy.append(self._harmonogram(umowa))
        podpowiedz = self._podpowiedz_przestawienia()
        if podpowiedz is not None:
            elementy.append(podpowiedz)
        if self.umowy:
            elementy.append(self._nota())
        elementy.append(utils.dol_bezpieczny(10))
        return elementy

    def _odswiez(self):
        """Po płatności, cofnięciu albo usunięciu — ten sam widok, więc
        pozycja przewijania zostaje, a paski nie grają od nowa."""
        self.umowy = db.pobierz_raty(self.state.auto_id)
        self.scena = utils.ScenaWejscia(wlaczona=False, kaskada=True)
        self.controls = self._elementy()
        try:
            self.update()
        except Exception:
            log.polkniety("odświeżenie ekranu Leasing i kredyt")

    def _kwota(self, wartosc):
        return f"{utils.formatuj_liczba(wartosc)} {utils.symbol_waluty()}"

    def _naglowek(self):
        """Przy kilku trwających umowach — jedna suma nad kartami."""
        trwajace = [u["harmonogram"] for u in self.umowy
                    if u["harmonogram"]["kompletna"] and not u["harmonogram"]["zakonczona"]]
        if len(trwajace) < 2:
            return None
        return ft.Row([
            ft.Icon(ft.Icons.ACCOUNT_BALANCE, size=16, color=ft.Colors.PRIMARY),
            utils.etykieta(f"{db.liczba_z_odmiana(len(trwajace), 'umowa', 'umowy', 'umów')} • razem do spłaty"),
            utils.wartosc(self._kwota(sum(h["do_splaty"] for h in trwajace))),
        ], spacing=6)

    def _pusto(self):
        opis = ("Dodaj umowę — liczbę rat, termin pierwszej raty, wykup i kwotę finansowania — "
                "a policzę, ile zostało do spłaty, kiedy ostatnia rata i ile w tym odsetek. "
                "Raty przypomni dzwonek, a zapłacone trafią do Innych kosztów.")
        if self.podglad:
            return ft.Container(
                padding=30,
                content=ft.Column([
                    ft.Icon(ft.Icons.ACCOUNT_BALANCE, size=46, color=ft.Colors.PRIMARY),
                    ft.Text("Brak leasingu ani kredytu", size=utils.FS["heading"], weight="bold"),
                    ft.Text(opis, size=utils.FS["body"], color=ft.Colors.ON_SURFACE_VARIANT,
                            text_align=ft.TextAlign.CENTER),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
            )
        return utils.ekran_braku_danych(
            ikona=ft.Icons.ACCOUNT_BALANCE,
            tytul="Brak leasingu ani kredytu",
            opis=opis,
            tekst_przycisku="Dodaj leasing lub kredyt",
            on_click=lambda e: utils.przejdz(self._page, "/raty/nowa"),
        )

    def _podpowiedz_przestawienia(self):
        """Rata wpisana kiedyś jako zwykły wydatek cykliczny — po nazwie. Jedno
        dotknięcie przenosi ją do formularza umowy z nazwą, kwotą i terminem."""
        if self.podglad:
            return None
        kandydaci = [w for w in db.pobierz_wydatki_cykliczne(self.state.auto_id)
                     if w[6] == db.TYP_CYKLICZNY_WYDATEK and w[5]
                     and any(slowo in db.klucz_nazwy(w[1]) for slowo in SLOWA_RATY)]
        if not kandydaci:
            return None
        wiersze = [ft.Row([
            ft.Icon(ft.Icons.AUTORENEW, size=16, color=ft.Colors.PRIMARY),
            utils.etykieta("Te wydatki cykliczne wyglądają na raty — bez końca i bez sumy", expand=True),
        ], spacing=6)]
        for w_id, nazwa, kwota, okres_dni, _nastepna, _koszt, _typ in kandydaci:
            wiersze.append(ft.Row([
                ft.Column([
                    ft.Text(str(nazwa), size=utils.FS["body_strong"], weight="bold"),
                    utils.podpis(f"{self._kwota(kwota)} co {okres_dni} dni"),
                ], spacing=0, expand=True),
                ft.TextButton("Przestaw na raty", icon=ft.Icons.ACCOUNT_BALANCE,
                              on_click=lambda e, wid=w_id: utils.przejdz(self._page, f"/raty/edytuj/{wid}")),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER))
        return ft.Container(
            padding=utils.SPACING["md"],
            **utils.powierzchnia(self._page, "blok"),
            content=ft.Column(wiersze, spacing=utils.SPACING["sm"]),
        )

    # ================= KARTA UMOWY =================

    def _wiersz(self, etykieta, wartosc, kolor=None, sufiks=None):
        tresc = [
            utils.etykieta(etykieta, expand=True),
            utils.wartosc(wartosc, color=kolor) if kolor else utils.wartosc(wartosc),
        ]
        if sufiks:
            tresc.append(utils.podpis(sufiks))
        return ft.Row(tresc, spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def _menu(self, umowa):
        if self.podglad:
            return ft.Container()
        return ft.PopupMenuButton(items=[
            ft.PopupMenuItem(
                content=ft.Row([ft.Icon(ft.Icons.EDIT, size=18), ft.Text("Edytuj umowę")]),
                on_click=lambda e, wid=umowa["id"]: utils.przejdz(self._page, f"/raty/edytuj/{wid}"),
            ),
            ft.PopupMenuItem(
                content=ft.Row([ft.Icon(ft.Icons.DELETE, color=utils.KOLOR_STATUS["destructive"], size=18),
                                ft.Text("Usuń umowę")]),
                on_click=lambda e, u=umowa: self._usun(u),
            ),
        ])

    def _karta_umowy(self, umowa):
        h = umowa["harmonogram"]
        leasing = umowa["typ"] == db.TYP_CYKLICZNY_LEASING
        nazwa = str(umowa["nazwa"] or "").strip() or db.etykieta_umowy(umowa["typ"])
        rodzaj = db.etykieta_umowy(umowa["typ"])
        if h["kompletna"] and h["rodzaj_rat"] == db.RATY_MALEJACE:
            rodzaj += " • raty malejące"
        elif h["kompletna"]:
            rodzaj += " • raty równe"

        if not h["kompletna"]:
            kolor = utils.KOLOR_STATUS["warning"]
        elif h["zakonczona"]:
            kolor = utils.KOLOR_STATUS["ok"]
        elif h["po_terminie"]:
            kolor = utils.KOLOR_STATUS["critical"]
        else:
            kolor = ft.Colors.PRIMARY

        tresc = [ft.Row([
            ft.Icon(utils.IKONY_UMOW_RAT.get(umowa["typ"], ft.Icons.ACCOUNT_BALANCE), size=20, color=kolor),
            ft.Column([
                ft.Text(nazwa, size=utils.FS["title"], weight="bold", no_wrap=True,
                        overflow=ft.TextOverflow.ELLIPSIS),
                utils.podpis(rodzaj),
            ], spacing=0, expand=True),
            self._menu(umowa),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)]

        if not h["kompletna"]:
            tresc.append(utils.podpis(f"{h['powod']} — bez tego nie ma harmonogramu."))
            if not self.podglad:
                tresc.append(ft.FilledTonalButton(
                    "Uzupełnij umowę", icon=ft.Icons.EDIT,
                    on_click=lambda e, wid=umowa["id"]: utils.przejdz(self._page, f"/raty/edytuj/{wid}"),
                ))
            return self._karta(tresc, kolor)

        self.scena.nastepny_wiersz()
        if h["zakonczona"]:
            tresc.append(ft.Row([
                ft.Icon(ft.Icons.TASK_ALT, size=18, color=kolor),
                utils.wartosc(f"Spłacona • {h['data_ostatniej_raty'].strftime('%d.%m.%Y')}", color=kolor),
            ], spacing=6))
        else:
            tresc.append(ft.Row([
                ft.Column([
                    utils.etykieta("Zostało do spłaty"),
                    self.scena.liczba(h["do_splaty"], self._kwota, size=utils.FS["display"], weight="bold"),
                ], spacing=0, expand=True),
                ft.Column([
                    utils.etykieta("z wszystkich płatności"),
                    utils.wartosc(self._kwota(h["suma_platnosci"])),
                ], spacing=0, horizontal_alignment=ft.CrossAxisAlignment.END),
            ], vertical_alignment=ft.CrossAxisAlignment.END))
        tresc.append(self.scena.wskaznik(ft.ProgressBar(
            value=h["udzial"], color=kolor, bgcolor=utils.tlo_toru(self._page), height=8, border_radius=4,
        )))
        tresc.append(utils.podpis(utils.podpis_postepu_raty(h)))

        tresc.append(ft.Divider(height=8))
        nastepna = h["nastepna"]
        if nastepna:
            dni = (nastepna["data"] - datetime.now().date()).days
            kiedy = ("dziś" if dni == 0 else f"za {utils.formatuj_okres(dni)}" if dni > 0
                     else f"{utils.formatuj_okres(dni)} po terminie")
            tresc.append(self._wiersz(
                "Następna płatność", self._kwota(nastepna["kwota"]),
                utils.KOLOR_STATUS["critical"] if nastepna["po_terminie"] else None,
                sufiks=f"{db.opis_platnosci(umowa['typ'], nastepna, h['liczba_rat'])} • "
                       f"{nastepna['data'].strftime('%d.%m.%Y')} ({kiedy})",
            ))
        tresc.append(self._wiersz("Ostatnia rata", h["data_ostatniej_raty"].strftime("%d.%m.%Y")))
        if h["wykup"]:
            tresc.append(self._wiersz(
                db.slowo_wykupu(umowa["typ"]).capitalize(), self._kwota(h["wykup"]),
                utils.KOLOR_STATUS["ok"] if h["wykup_zaplacony"] else None,
                sufiks="zapłacony" if h["wykup_zaplacony"] else "w terminie ostatniej raty",
            ))
        if h.get("oplata_wstepna"):
            tresc.append(self._wiersz("Opłata wstępna", self._kwota(h["oplata_wstepna"]), sufiks="na start"))
        tresc.extend(self._wiersze_odsetek(h, leasing))

        if nastepna and not self.podglad:
            tresc.append(ft.FilledTonalButton(
                f"Zapłacono: {db.opis_platnosci(umowa['typ'], nastepna, h['liczba_rat'])}",
                icon=ft.Icons.CHECK_CIRCLE,
                on_click=lambda e, u=umowa: self._zaplac(u),
            ))
        return self._karta(tresc, kolor)

    def _wiersze_odsetek(self, h, leasing):
        if h["odsetki_razem"] is None:
            if h["niespojna"]:
                return [ft.Row([
                    ft.Icon(ft.Icons.WARNING_AMBER, size=16, color=utils.KOLOR_STATUS["warning"]),
                    ft.Text("Raty z wykupem nie pokrywają kwoty finansowania — sprawdź kwoty w umowie.",
                            size=utils.FS["caption"], color=utils.KOLOR_STATUS["warning"], expand=True),
                ], spacing=6)]
            return [utils.podpis("Podaj w umowie kwotę finansowania, a policzę odsetki i kapitał do spłaty.")]

        nazwa = "Koszt finansowania" if leasing else "Odsetki"
        wiersze = []
        if not h["zakonczona"]:
            wiersze.append(self._wiersz(f"{nazwa} do zapłaty", self._kwota(h["odsetki_do_zaplaty"]),
                                        utils.KOLOR_STATUS["cost"]))
            wiersze.append(self._wiersz("Kapitał do spłaty", self._kwota(h["kapital_do_splaty"])))
        wiersze.append(self._wiersz(
            f"{nazwa} łącznie", self._kwota(h["odsetki_razem"]),
            sufiks=f"zapłacono {utils.formatuj_liczba(h['odsetki_zaplacone'])}",
        ))
        if h["oprocentowanie"]:
            skad = "z umowy" if h["oprocentowanie_z"] == "umowa" else "wyliczone z raty"
            wiersze.append(self._wiersz("Oprocentowanie",
                                        f"{utils.formatuj_liczba(h['oprocentowanie'])}% rocznie", sufiks=skad))
        return wiersze

    def _karta(self, tresc, kolor):
        karta, kontener = utils.karta_listy(ft.Column(tresc, spacing=utils.SPACING["sm"]),
                                            kolor_paska=kolor, page=self._page)
        kontener.ink = False  # karta nie prowadzi dalej — akcje ma w środku
        return karta

    # ================= HARMONOGRAM =================

    def _harmonogram(self, umowa):
        """Wszystkie płatności, rocznikami. Zapłacone przygaszone, zaległe na
        czerwono, najbliższa wyróżniona — jak wyciąg z banku, tylko krótszy."""
        h = umowa["harmonogram"]
        znane = h["odsetki_razem"] is not None
        wiersze = []
        rok = None
        for p in h["platnosci"]:
            if p["data"].year != rok:
                rok = p["data"].year
                w_roku = [x for x in h["platnosci"] if x["data"].year == rok]
                wiersze.append(ft.Container(
                    padding=ft.Padding(0, utils.SPACING["sm"], 0, 0),
                    content=ft.Row([
                        utils.wartosc(str(rok)),
                        utils.podpis(f"{db.liczba_z_odmiana(len(w_roku), 'płatność', 'płatności', 'płatności')} • "
                                     f"{self._kwota(sum(x['kwota'] for x in w_roku))}"),
                    ], spacing=8),
                ))
            wiersze.append(self._wiersz_platnosci(umowa, p, p is h["nastepna"], znane))
        tytul = "Harmonogram płatności" if len(self.umowy) == 1 else f"Harmonogram: {umowa['nazwa']}"
        return utils.karta_formularza(wiersze, tytul, ft.Icons.TABLE_ROWS, page=self._page)

    def _wiersz_platnosci(self, umowa, p, najblizsza, znane):
        if p["zaplacona"]:
            ikona, kolor = ft.Icons.CHECK_CIRCLE, utils.KOLOR_STATUS["ok"]
        elif p["po_terminie"]:
            ikona, kolor = ft.Icons.ERROR_OUTLINE, utils.KOLOR_STATUS["critical"]
        elif najblizsza:
            ikona, kolor = ft.Icons.ARROW_CIRCLE_RIGHT, ft.Colors.PRIMARY
        else:
            ikona, kolor = ft.Icons.RADIO_BUTTON_UNCHECKED, utils.KOLOR_STATUS["neutral"]
        numer = (db.slowo_wykupu(umowa["typ"]).capitalize() if p["rodzaj"] == db.PLATNOSC_WYKUP
                 else f"{p['numer']}.")
        prawa = [utils.wartosc(self._kwota(p["kwota"]), color=kolor if p["po_terminie"] else None)]
        if znane and p["rodzaj"] == db.PLATNOSC_RATA:
            prawa.append(utils.podpis(
                f"kapitał {utils.formatuj_liczba(p['kapital'])} • odsetki {utils.formatuj_liczba(p['odsetki'])}"))
        return ft.Container(
            opacity=0.6 if p["zaplacona"] else 1.0,
            content=ft.Row([
                ft.Icon(ikona, size=16, color=kolor),
                ft.Column([
                    ft.Text(numer, size=utils.FS["body"], weight="bold" if najblizsza else "normal"),
                    utils.podpis(p["data"].strftime("%d.%m.%Y")),
                ], spacing=0, expand=True),
                ft.Column(prawa, spacing=0, horizontal_alignment=ft.CrossAxisAlignment.END),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )

    def _nota(self):
        return utils.nota_o_liczeniu(
            self._page, "Jak liczę raty i odsetki",
            "Raty idą co miesiąc, tego samego dnia co pierwsza. Przy racie z umowy oprocentowanie "
            "wynika z raty i kwoty finansowania, więc odsetki to wszystko, co zapłacisz, minus "
            "kapitał (przy leasingu: wartość auta minus opłata wstępna). Wykup albo rata balonowa "
            "to ostatnia płatność, w terminie ostatniej raty — dopiero ona zamyka umowę. "
            "„Zapłacono” zapisuje kolejną płatność w Innych kosztach (kategoria „Cykliczne”), "
            "a dzwonek przypomina o następnej.",
        )

    # ================= AKCJE =================

    def _zaplac(self, umowa):
        wynik = db.oznacz_zaplacony_wydatek_cykliczny(umowa["id"], self.state.auto_id)
        utils.pokaz_komunikat_wykonania(self._page, wynik, True, po_cofnieciu=self._odswiez)
        utils.wypchnij_w_tle(self._page, self.state.auto_id, "rata")
        self._odswiez()

    def _usun(self, umowa):
        def wykonaj():
            db.usun_wydatek_cykliczny(umowa["id"])
            self._odswiez()
            utils.pokaz_komunikat(self._page, "Usunięto umowę. Zapłacone raty zostały w Innych kosztach.")

        utils.potwierdz(
            self._page, "Usunąć umowę?",
            f"„{umowa['nazwa']}” zniknie razem z harmonogramem i przypomnieniem o racie. Zapłacone "
            "już raty zostaną w Innych kosztach.",
            wykonaj,
        )


__all__ = [
    "RatyView",
    "SLOWA_RATY",
]
