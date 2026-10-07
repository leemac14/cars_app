import flet as ft

import db
import utils


class CoNowegoView(ft.View):
    """„Co nowego” — wydania od najnowszego (M-19). Raz po aktualizacji otwiera się samo
    nad kokpitem (main.py); poza tym w menu bocznym i Ustawieniach › O aplikacji.
    Niewidziane wydania na górze z plakietką „Nowe”.

    Wejście oznacza wszystko jako widziane, ale próg „nowego” trzyma `state.nowosci_od`
    (start albo pierwsze wejście w sesji), więc przebudowa nie gasi plakietek w pół
    czytania. „Pokaż” przez utils.otworz_ekran; znika bez pojazdu i przy roli, której
    router odmówi (`wolno_wejsc(trasa)`). Treść: db/nowosci.py."""

    def __init__(self, page: ft.Page, state, wolno_wejsc=None):
        self._page = page
        self.state = state
        self._wolno_wejsc = wolno_wejsc

        if getattr(state, "nowosci_od", None) is None:
            state.nowosci_od = db.pobierz_widziana_wersje() or db.WERSJA_APLIKACJI
        nowe = db.wydania_po(state.nowosci_od)
        self.nowe = {wydanie["wersja"] for wydanie in nowe}
        db.oznacz_nowosci_jako_widziane()

        appbar = utils.zbuduj_pasek_z_powrotem(page, "Co nowego", "/", ikona=ft.Icons.NEW_RELEASES)

        elementy = [self._naglowek(nowe)]
        wczesniej_dodane = False
        for wydanie in db.NOWOSCI:
            if self.nowe and not wczesniej_dodane and wydanie["wersja"] not in self.nowe:
                elementy.append(self._naglowek_wczesniej())
                wczesniej_dodane = True
            elementy.append(self._wydanie(wydanie))
        if self.nowe:
            elementy.append(ft.Container(
                padding=ft.Padding(0, utils.SPACING["sm"], 0, 0),
                content=ft.FilledButton("Gotowe", icon=ft.Icons.CHECK,
                                        on_click=lambda e: utils.przejdz(self._page, "/")),
            ))
        elementy.append(utils.dol_bezpieczny(10))

        super().__init__(
            route="/co-nowego", padding=15, spacing=12, appbar=appbar,
            controls=elementy, scroll=ft.ScrollMode.AUTO,
        )

    # ================= NAGŁÓWKI =================

    def _naglowek(self, nowe):
        """Co się stało od ostatniego razu — albo, gdy nic, że to historia zmian."""
        wersja = db.WERSJA_APLIKACJI
        dzien = db.data_wydania(wersja)
        z_dnia = f" z {utils.formatuj_date_pl(dzien)}" if dzien else ""
        if nowe:
            ile = sum(len(wydanie["pozycje"]) for wydanie in nowe)
            tytul = "Co się zmieniło od Twojej poprzedniej wersji"
            podpis = (f"{db.liczba_z_odmiana(ile, 'nowość', 'nowości', 'nowości')} · "
                      f"teraz wersja {wersja}{z_dnia}. „Pokaż” prowadzi prosto do funkcji.")
        else:
            tytul = "Historia zmian"
            podpis = f"Wersja {wersja}{z_dnia} · od najnowszych zmian."
        return ft.Container(
            padding=utils.SPACING["md"],
            **utils.powierzchnia(self._page, "karta"),
            content=ft.Row([
                self._kolko(ft.Icons.NEW_RELEASES, ft.Colors.PRIMARY, rozmiar=44),
                ft.Column([
                    utils.wartosc(tytul, size=utils.FS["title"]),
                    utils.podpis(podpis),
                ], spacing=2, tight=True, expand=True),
            ], spacing=utils.SPACING["md"], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )

    def _naglowek_wczesniej(self):
        return ft.Container(
            padding=ft.Padding(0, utils.SPACING["md"], 0, 0),
            content=ft.Row([
                ft.Icon(ft.Icons.HISTORY, size=16, color=ft.Colors.ON_SURFACE_VARIANT),
                utils.etykieta("Wcześniej — to ten telefon już widział"),
            ], spacing=6),
        )

    # ================= WYDANIA I POZYCJE =================

    def _wydanie(self, wydanie):
        dzien = db.data_wydania(wydanie["wersja"])
        naglowek = [utils.wartosc(utils.formatuj_date_pl(dzien) if dzien else wydanie["wersja"],
                                  size=utils.FS["title"])]
        if dzien:
            naglowek.append(utils.podpis(f"wersja {wydanie['wersja']}"))
        if wydanie["wersja"] in self.nowe:
            naglowek.append(self._plakietka_nowe())
        return ft.Column(
            [ft.Row(naglowek, spacing=utils.SPACING["sm"], wrap=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER)]
            + [self._pozycja(pozycja) for pozycja in wydanie["pozycje"]],
            spacing=utils.SPACING["sm"],
        )

    def _plakietka_nowe(self):
        kolor = utils.KOLOR_STATUS["info"]
        return ft.Container(
            padding=ft.Padding(8, 1, 8, 1), border_radius=utils.RADIUS["pill"],
            bgcolor=ft.Colors.with_opacity(0.15, kolor),
            content=ft.Text("Nowe", size=utils.FS["caption"], weight="bold", color=kolor),
        )

    def _kolko(self, ikona, kolor, rozmiar=36):
        return ft.Container(
            width=rozmiar, height=rozmiar, border_radius=utils.RADIUS["pill"],
            bgcolor=ft.Colors.with_opacity(0.12, kolor), alignment=ft.Alignment.CENTER,
            content=ft.Icon(ikona, size=round(rozmiar * 0.55), color=kolor),
        )

    def _pozycja(self, pozycja):
        ekran = utils.EKRANY_WG_ID.get(pozycja.get("ekran"))
        ikona = getattr(ft.Icons, pozycja.get("ikona") or "", None) or (ekran or {}).get("ikona") \
            or ft.Icons.AUTO_AWESOME
        kolor = utils.kolor_ekranu(ekran) if ekran else ft.Colors.PRIMARY

        tresc = [
            utils.wartosc(pozycja["tytul"]),
            ft.Text(pozycja["opis"], size=utils.FS["body"]),
        ]
        if ekran:
            wiersz = [
                ft.Icon(ft.Icons.MENU, size=14, color=ft.Colors.ON_SURFACE_VARIANT),
                utils.podpis(self._gdzie(ekran), expand=True),
            ]
            if self._wolno_pokazac(ekran):
                wiersz.append(ft.TextButton(
                    "Pokaż", icon=ft.Icons.ARROW_FORWARD,
                    on_click=lambda e, ek=ekran: utils.otworz_ekran(self._page, self.state, ek),
                ))
            tresc.append(ft.Row(wiersz, spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER))

        karta, kontener = utils.karta_listy(
            ft.Row([
                self._kolko(ikona, kolor),
                ft.Column(tresc, spacing=utils.SPACING["xs"], tight=True, expand=True),
            ], spacing=utils.SPACING["md"], vertical_alignment=ft.CrossAxisAlignment.START),
            page=self._page,
        )
        kontener.ink = False
        return karta

    @staticmethod
    def _gdzie(ekran):
        """„Menu boczne › Serwis i zadania › Warsztaty” — żeby po „Pokaż” było
        wiadomo, jak trafić tam drugi raz. Kokpit leży w menu bez grupy."""
        grupa = utils.GRUPY_WG_ID.get(ekran.get("grupa"))
        if not grupa or grupa["id"] == "start":
            return f"Menu boczne › {ekran['tytul']}"
        return f"Menu boczne › {grupa['tytul']} › {ekran['tytul']}"

    def _wolno_pokazac(self, ekran):
        """Czy „Pokaż” ma dokąd prowadzić: ekran z trasą albo zakładką, pojazd,
        gdy ekran go wymaga, i rola, której router nie odmówi."""
        if not (ekran.get("trasa") or ekran.get("zakladka") is not None):
            return False
        if ekran.get("wymaga_pojazdu", True) and not self.state.auto_id:
            return False
        if ekran.get("trasa") and callable(self._wolno_wejsc):
            return bool(self._wolno_wejsc(ekran["trasa"]))
        return True
