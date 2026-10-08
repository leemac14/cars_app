import flet as ft

import db
import utils


class OdliczaniaView(ft.View):
    """„Ile zostało do…” — jedna lista odliczań od najbliższego: dokumenty, gwarancja,
    podzespoły z interwałem, okrągły przebieg; ma kafelek na kokpicie. Liczby:
    db.odliczania_pojazdu, słowa: utils/format.py."""

    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state
        self.j = utils.jednostka_dystansu()  # km albo mi — raz na ekran

        appbar = utils.zbuduj_pasek_z_powrotem(page, "Ile zostało do…", "/", ikona=ft.Icons.HOURGLASS_BOTTOM)

        if not self.state.auto_id:
            super().__init__(
                route="/ile-zostalo", padding=15, spacing=15, appbar=appbar,
                controls=[utils.ekran_braku_danych(
                    ikona=ft.Icons.DIRECTIONS_CAR,
                    tytul="Brak wybranego pojazdu",
                    opis="Dodaj pojazd, aby odliczać jego terminy.",
                    tekst_przycisku="Dodaj pojazd",
                    on_click=lambda e: utils.przejdz(self._page, "/auto/nowy"),
                )],
            )
            return

        # Paski ruszają od zera kaskadą — dopiero ruch pokazuje, który okres
        # zjadł już najwięcej. Raz na uruchomienie aplikacji, jak na Karcie
        # pojazdu: przy kolejnym wejściu animacja byłaby tylko zwłoką.
        self.scena = utils.ScenaWejscia(
            wlaczona=db.czy_animacje_interfejsu()
            and utils.pierwsze_pokazanie(state, "ile-zostalo", state.auto_id),
            kaskada=True,
        )

        self.podglad = db.czy_tylko_podglad(self.state.auto_id)
        self.pozycje = db.odliczania_pojazdu(self.state.auto_id)

        if db.czy_pojazd_sprzedany(self.state.auto_id):
            elementy = [self._sprzedany()]
        elif not self.pozycje:
            elementy = [self._pusto()]
        else:
            elementy = [self._naglowek()]
            baner = self._baner_licznika()
            if baner is not None:
                elementy.append(baner)
            elementy.extend(self._karta(pozycja) for pozycja in self.pozycje)
            elementy.append(self._nota_o_liczeniu())
            elementy.append(self._link_do_przyszlosci())
        elementy.append(utils.dol_bezpieczny(10))

        super().__init__(
            route="/ile-zostalo", padding=15, spacing=10, appbar=appbar,
            controls=elementy, scroll=ft.ScrollMode.AUTO,
        )
        self.scena.uruchom(page)

    # ================= STANY BEZ LISTY =================

    def _sprzedany(self):
        return utils.ekran_braku_danych(
            ikona=ft.Icons.SELL,
            tytul="Auto jest sprzedane",
            opis="Terminy i przeglądy już go nie dotyczą — cała historia została w archiwum.",
            tekst_przycisku="Wróć na start",
            on_click=lambda e: utils.przejdz(self._page, "/"),
        )

    def _pusto(self):
        opis = ("Wpisz datę OC i przeglądu w danych pojazdu albo dodaj podzespół z interwałem — "
                "każde z nich dostanie tu swój pasek i datę. Okrągły przebieg pojawi się "
                "po pierwszym stanie licznika.")
        if self.podglad:
            # Rola „tylko podgląd” niczego nie uzupełni — przycisk, który zawsze
            # odmawia, jest gorszy od jego braku.
            return ft.Container(
                padding=30,
                content=ft.Column([
                    ft.Icon(ft.Icons.HOURGLASS_EMPTY, size=46, color=ft.Colors.PRIMARY),
                    ft.Text("Nic tu jeszcze nie odlicza", size=utils.FS["heading"], weight="bold"),
                    ft.Text(opis, size=utils.FS["body"], color=ft.Colors.ON_SURFACE_VARIANT,
                            text_align=ft.TextAlign.CENTER),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
            )
        return utils.ekran_braku_danych(
            ikona=ft.Icons.HOURGLASS_EMPTY,
            tytul="Nic tu jeszcze nie odlicza",
            opis=opis,
            tekst_przycisku="Uzupełnij daty",
            on_click=lambda e: utils.przejdz(self._page, f"/auto/edytuj/{self.state.auto_id}"),
        )

    # ================= LISTA =================

    def _naglowek(self):
        """Ile jest odliczań i czy coś z nich goni. Najbliższe stoi zaraz pod
        spodem jako pierwsza karta — powtarzanie go w nagłówku nic nie wnosi."""
        tekst = f"{db.liczba_z_odmiana(len(self.pozycje), 'odliczanie', 'odliczania', 'odliczań')} od najbliższego"
        stan = utils.stan_odliczan(self.pozycje)
        wiersz = [
            ft.Icon(ft.Icons.HOURGLASS_BOTTOM, size=16, color=ft.Colors.PRIMARY),
            utils.etykieta(tekst),
        ]
        if stan:
            po_terminie = any(p["status"] == "po_terminie" for p in self.pozycje)
            kolor = utils.KOLOR_STATUS["critical" if po_terminie else "warning"]
            wiersz.append(ft.Text(f"· {stan}", size=utils.FS["caption"], color=kolor, expand=True))
        return ft.Row(wiersz, spacing=6)

    def _baner_licznika(self):
        """Kilometry na liście liczą się od ostatniego znanego przebiegu — gdy
        ten jest stary, mówimy to raz, nad listą (jak w zakładce Serwis)."""
        if not any(p["zostalo_km"] is not None for p in self.pozycje):
            return None
        return utils.baner_nieswiezego_licznika(
            self._page, self.state.auto_id, db.swiezosc_licznika(self.state.auto_id),
            po_zapisie=lambda: utils.odswiez_ekran(self._page),
        )

    def _trasa(self, pozycja):
        """Dokąd prowadzi wiersz. Formularz dokumentów i podzespołu to zmiana
        danych, więc podgląd dostaje Kartę pojazdu albo nic."""
        if not self.podglad:
            return pozycja["trasa"]
        if pozycja["rodzaj"] in ("dokument", "gwarancja_km"):
            return "/pojazd"
        # Harmonogram rat to ekran do oglądania — zapłatę i tak blokuje rola.
        if pozycja["rodzaj"] in ("przebieg", "gwarancja_naprawy", "rata", "skarbiec"):
            return pozycja["trasa"]
        return None

    def _karta(self, pozycja):
        karta, kontener = utils.karta_listy(
            utils.wiersz_odliczania(self._page, pozycja, self.j, scena=self.scena),
            kolor_paska=utils.kolor_odliczania(pozycja), page=self._page,
        )
        trasa = self._trasa(pozycja)
        if trasa:
            kontener.on_click = utils.z_efektem_nacisniecia(
                kontener, lambda e, t=trasa: utils.przejdz(self._page, t))
        else:
            kontener.ink = False
        return karta

    def _link_do_przyszlosci(self):
        """Ta lista mówi, ile zostało do każdej rzeczy z osobna. Kalendarz
        całego roku — z ratami, wpisami cyklicznymi i prognozą miesięcy —
        stoi w „Co przede mną”."""
        return ft.Row([ft.TextButton(
            "Cały rok do przodu", icon=ft.Icons.EVENT_NOTE,
            on_click=lambda e: utils.przejdz(self._page, "/co-przede-mna"),
        )], alignment=ft.MainAxisAlignment.CENTER)

    def _nota_o_liczeniu(self):
        krok = f"{utils.formatuj_liczba(db.KROK_OKRAGLEGO_PRZEBIEGU, 0)} {self.j}"
        return utils.nota_o_liczeniu(
            self._page, "Jak liczony jest pasek",
            "Pasek pokazuje, jaka część okresu już minęła. OC, AC, assistance, przegląd, "
            "gaśnica i apteczka liczą rok przed terminem; gwarancja producenta — od "
            "pierwszej rejestracji, a bez niej od zakupu; jej limit przebiegu — od zera na "
            "liczniku; gwarancja naprawy — od dnia (albo licznika) wymiany. Podzespół "
            "i gwarancja naprawy pokazują licznik, który skończy się pierwszy — ten sam, co "
            "karta w zakładce Serwis i dzwonek. Okrągły przebieg to najbliższe pełne "
            f"{krok}. Leasing i kredyt odliczają do ostatniej raty (wykup płaci się w jej "
            "terminie), a ich pasek to część zapłaconych płatności. Daty przy kilometrach "
            "to prognoza ze średniego przebiegu dziennego. "
            "Kolor mówi to samo, co powiadomienia: pomarańczowy — termin w progu "
            "przypomnienia, czerwony — po terminie.",
        )
