import flet as ft

import db
import sync
import utils


class WarsztatyView(ft.View):
    """„Warsztaty” — karta każdego warsztatu pojazdu: telefon, adres, notatka
    i dwa przyciski, „Zadzwoń” i „Pokaż na mapie” (M-05 w katalogu pomysłów).

    Rejestr warsztatów był w bazie od sierpnia 2026, ale bez ekranu: formularze
    zapisywały samą nazwę, więc telefonu i adresu nie miał kto wpisać, a przyciski
    przy wyborze warsztatu w formularzu nigdy się nie pokazywały. Pod kartami stoją
    nazwy, które są na wizytach, a karty nie mają (sprzed rejestru albo po
    usunięciu karty) — jednym dotknięciem dostają kartę.

    Dane liczy db.pobierz_karty_warsztatow, kartę i formularz rysuje
    utils/warsztaty.py (ta sama karta otwiera się z listy wizyt)."""

    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state

        akcje = None
        if self.state.auto_id:
            wspolny_id, _ = sync.czy_udostepniony(self.state.auto_id)
            if wspolny_id:
                akcje = [utils.przycisk_synchronizacji(page, utils.funkcja_szybkiej_synchronizacji(
                    page, self.state.auto_id, "/warsztaty"))]
        appbar = utils.zbuduj_pasek_z_powrotem(page, "Warsztaty", "/", akcje_dodatkowe=akcje,
                                               ikona=ft.Icons.CAR_REPAIR)

        if not self.state.auto_id:
            super().__init__(
                route="/warsztaty", padding=15, spacing=15, appbar=appbar,
                controls=[utils.ekran_braku_danych(
                    ikona=ft.Icons.DIRECTIONS_CAR,
                    tytul="Brak wybranego pojazdu",
                    opis="Dodaj pojazd, aby zapisywać jego warsztaty.",
                    tekst_przycisku="Dodaj pojazd",
                    on_click=lambda e: utils.przejdz(self._page, "/auto/nowy"),
                )],
            )
            return

        # Podgląd niczego nie dopisze — FAB, „Dodaj kartę” i pozycje menu
        # zmieniające dane po prostu się nie pokazują.
        self.moge_zmieniac = utils.wolno_zmieniac_rekord(self.state.auto_id, "warsztaty")
        karty = db.pobierz_karty_warsztatow(self.state.auto_id)
        z_karta = [k for k in karty if k["id"] is not None]
        bez_karty = [k for k in karty if k["id"] is None]

        elementy = []
        if not karty:
            elementy.append(self._pusto())
        if z_karta:
            elementy.append(self._naglowek(len(z_karta)))
            elementy.extend(self._karta(k) for k in z_karta)
        if bez_karty:
            elementy.append(self._naglowek_bez_karty(po_kartach=bool(z_karta)))
            elementy.extend(self._karta_bez_danych(k) for k in bez_karty)
        elementy.append(utils.dol_bezpieczny(80))  # miejsce pod FAB-em

        fab = (utils.fab_animowany(ft.Icons.ADD, lambda e: self._formularz(), tooltip="Dodaj warsztat")
               if self.moge_zmieniac else None)
        super().__init__(
            route="/warsztaty", padding=15, spacing=10, appbar=appbar,
            floating_action_button=fab, controls=elementy, scroll=ft.ScrollMode.AUTO,
        )

    # ================= AKCJE =================

    def _odswiez(self):
        utils.odswiez_ekran(self._page)

    def _formularz(self, karta=None):
        utils.pokaz_formularz_warsztatu(self._page, self.state, karta, po_zapisie=self._odswiez)

    def _pokaz_wizyty(self, karta):
        """Lista wizyt z filtrem „Warsztat” ustawionym na ten warsztat — filtr
        porównuje dokładną pisownię, więc bierzemy tę, która stoi na wizytach."""
        self.state.filtry["wizyty_wyk"] = karta["nazwa_na_wizytach"]
        utils.przejdz(self._page, "/wizyty")

    def _usun(self, karta):
        def wykonaj():
            # Nagrobek dla synchronizacji i cofnięcie robi ogólny mechanizm usuwania.
            # Bez wypychania od razu: w oknie „Cofnij” nagrobek nie może już
            # siedzieć w chmurze, bo przywrócona karta by do niej nie wróciła.
            wynik = db.usun_z_cofnieciem("warsztaty", karta["id"])
            self._odswiez()
            utils.pokaz_komunikat_cofnij(self._page, f"Usunięto warsztat „{karta['nazwa']}”.", wynik)

        tresc = f"„{karta['nazwa']}” zniknie z listy razem z telefonem i adresem."
        if karta.get("wizyt"):
            tresc += " Wizyty i wpisy zachowają jego nazwę."
        utils.potwierdz(self._page, "Usunąć warsztat?", tresc, wykonaj)

    def _menu(self, karta):
        telefon, adres = karta.get("telefon"), karta.get("adres")
        pozycje = []
        if telefon:
            pozycje.append({"ikona": ft.Icons.PHONE, "tekst": f"Zadzwoń: {telefon}", "czyta": True,
                            "akcja": lambda: utils.zadzwon(self._page, telefon)})
        if adres:
            pozycje.append({"ikona": ft.Icons.MAP, "tekst": "Pokaż na mapie", "czyta": True,
                            "akcja": lambda: utils.pokaz_na_mapie(self._page, adres)})
        if telefon:
            pozycje.append({"ikona": ft.Icons.CONTENT_COPY, "tekst": "Kopiuj numer", "czyta": True,
                            "akcja": lambda: utils.kopiuj_do_schowka(self._page, telefon, "Skopiowano numer")})
        if adres:
            pozycje.append({"ikona": ft.Icons.CONTENT_COPY, "tekst": "Kopiuj adres", "czyta": True,
                            "akcja": lambda: utils.kopiuj_do_schowka(self._page, adres, "Skopiowano adres")})
        if karta.get("wizyt_zbiorczych"):
            pozycje.append({"ikona": ft.Icons.HOME_REPAIR_SERVICE, "tekst": "Wizyty w tym warsztacie",
                            "czyta": True, "akcja": lambda: self._pokaz_wizyty(karta)})
        if karta["id"] is not None:
            pozycje.append({"ikona": ft.Icons.EDIT, "tekst": "Edytuj dane",
                            "akcja": lambda: self._formularz(karta)})
            pozycje.append({"ikona": ft.Icons.DELETE, "tekst": "Usuń warsztat",
                            "kolor": utils.KOLOR_STATUS["destructive"], "akcja": lambda: self._usun(karta)})
        else:
            pozycje.append({"ikona": ft.Icons.ADD, "tekst": "Dodaj kartę z telefonem i adresem",
                            "akcja": lambda: self._formularz(karta)})
        pozycje = utils.odsiej_akcje(self.state.auto_id, pozycje, "warsztaty", karta["id"])
        utils.pokaz_menu_kontekstowe(self._page, karta["nazwa"], pozycje)

    # ================= STANY I KARTY =================

    def _pusto(self):
        opis = ("Warsztat trafia tu sam, gdy zapiszesz wizytę albo wpis serwisowy z jego nazwą. "
                "Dopisz mu telefon i adres, a zadzwonisz i dojedziesz jednym dotknięciem.")
        if not self.moge_zmieniac:
            return ft.Container(
                padding=30,
                content=ft.Column([
                    ft.Icon(ft.Icons.CAR_REPAIR, size=46, color=ft.Colors.PRIMARY),
                    ft.Text("Nie ma jeszcze warsztatów", size=utils.FS["heading"], weight="bold"),
                    ft.Text(opis, size=utils.FS["body"], color=ft.Colors.ON_SURFACE_VARIANT,
                            text_align=ft.TextAlign.CENTER),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
            )
        return utils.ekran_braku_danych(
            ikona=ft.Icons.CAR_REPAIR,
            tytul="Nie ma jeszcze warsztatów",
            opis=opis,
            tekst_przycisku="Dodaj warsztat",
            on_click=lambda e: self._formularz(),
        )

    def _naglowek(self, ile):
        return ft.Row([
            ft.Icon(ft.Icons.CAR_REPAIR, size=16, color=ft.Colors.PRIMARY),
            utils.etykieta(f"{db.liczba_z_odmiana(ile, 'warsztat', 'warsztaty', 'warsztatów')}"
                           " · od ostatnio odwiedzonego"),
        ], spacing=6)

    def _karta(self, karta):
        tresc = utils.tresc_karty_warsztatu(
            self._page, karta,
            na_uzupelnienie=(lambda: self._formularz(karta)) if self.moge_zmieniac else None,
        )
        karta_ui, kontener = utils.karta_listy(tresc, page=self._page)
        kontener.on_click = utils.z_efektem_nacisniecia(kontener, lambda e: self._menu(karta))
        return karta_ui

    def _naglowek_bez_karty(self, po_kartach):
        return ft.Container(
            padding=ft.Padding(0, utils.SPACING["md"] if po_kartach else 0, 0, 0),
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.HISTORY, size=16, color=ft.Colors.ON_SURFACE_VARIANT),
                    utils.etykieta("Z historii wizyt — bez karty"),
                ], spacing=6),
                utils.podpis("Te nazwy stoją na wizytach i wpisach serwisowych, ale nie mają karty. "
                             "Dopisz telefon i adres, a warsztat dostanie przyciski."),
            ], spacing=2, tight=True),
        )

    def _karta_bez_danych(self, karta):
        wiersz = [ft.Column([
            utils.wartosc(karta["nazwa"], size=utils.FS["body_strong"]),
            utils.podpis(utils.opis_wizyt_warsztatu(karta)),
        ], spacing=0, tight=True, expand=True)]
        if self.moge_zmieniac:
            wiersz.append(ft.TextButton("Dodaj kartę", icon=ft.Icons.ADD,
                                        on_click=lambda e: self._formularz(karta)))
        karta_ui, kontener = utils.karta_listy(
            ft.Row(wiersz, vertical_alignment=ft.CrossAxisAlignment.CENTER), page=self._page)
        kontener.on_click = utils.z_efektem_nacisniecia(kontener, lambda e: self._menu(karta))
        return karta_ui
