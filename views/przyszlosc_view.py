import flet as ft

import db
import log
import utils


class PrzyszloscView(ft.View):
    """„Co przede mną” (N-02): terminy, wymiany, cykliczne, raty, zmiana opon, końce
    budżetów i prognoza kosztu miesięcy w oknie 30/90/365 dni, zaległe na górze. Liczy
    db.os_przyszlosci, wiersze składa utils/przyszlosc.py, okno pamięta
    db.pobierz_okno_przyszlosci."""

    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state
        self.j = utils.jednostka_dystansu()  # km albo mi — raz na ekran

        appbar = utils.zbuduj_pasek_z_powrotem(page, "Co przede mną", "/", ikona=ft.Icons.EVENT_NOTE)

        if not self.state.auto_id:
            super().__init__(
                route="/co-przede-mna", padding=15, spacing=15, appbar=appbar,
                controls=[utils.ekran_braku_danych(
                    ikona=ft.Icons.DIRECTIONS_CAR,
                    tytul="Brak wybranego pojazdu",
                    opis="Dodaj pojazd, aby zobaczyć, co go czeka w najbliższych miesiącach.",
                    tekst_przycisku="Dodaj pojazd",
                    on_click=lambda e: utils.przejdz(self._page, "/auto/nowy"),
                )],
            )
            return

        self.podglad = db.czy_tylko_podglad(self.state.auto_id)
        self.dni = db.pobierz_okno_przyszlosci()
        self.os = None
        self.przelacznik = ft.Container()
        self.lista = ft.Column(spacing=10)

        def tresc():
            # Oś zbiera odliczania, harmonogramy rat, wpisy cykliczne, budżety
            # i średnią z roku kosztów — liczymy ją dopiero po zarysie ekranu.
            if db.czy_pojazd_sprzedany(self.state.auto_id):
                return ft.Column([self._sprzedany(), utils.dol_bezpieczny(10)])
            self.przelacznik.content = self._segmenty()
            self._przelicz()
            return ft.Column([self.przelacznik, self.lista], spacing=10)

        super().__init__(
            route="/co-przede-mna", padding=15, appbar=appbar,
            controls=[utils.zbuduj_etapami(
                page, utils.szkielet_ekranu(page, karty=5, linie=2), tresc, widok=self,
            )],
            scroll=ft.ScrollMode.AUTO,
        )

    # ================= OKNO =================

    def _segmenty(self):
        return utils.segmented_control(
            self._page, [(utils.formatuj_dni(dni), dni) for dni in db.OKNA_PRZYSZLOSCI],
            self.dni, self._zmien_okno,
        )

    def _przelicz(self):
        self.os = db.os_przyszlosci(self.state.auto_id, dni=self.dni)
        self.lista.controls = self._elementy()

    def _odswiez(self, opis):
        self._przelicz()
        try:
            self.update()
        except Exception:
            log.polkniety(opis)

    def _zmien_okno(self, dni):
        if dni == self.dni:
            return
        self.dni = dni
        db.zapisz_okno_przyszlosci(dni)
        self.przelacznik.content = self._segmenty()
        self._odswiez("przebudowa osi przyszłości po zmianie okna")

    def odswiez_w_miejscu(self):
        """Po „Zapłacone” w panelu wydatków albo wpisie licznika z banera
        (utils.odswiez_ekran): oś liczy się od nowa, okno i miejsce zostają."""
        if self.os is None:
            return
        self._odswiez("odświeżenie osi przyszłości w miejscu")

    # ================= STANY BEZ LISTY =================

    def _sprzedany(self):
        return utils.ekran_braku_danych(
            ikona=ft.Icons.SELL,
            tytul="Auto jest sprzedane",
            opis="Nic go już przed tobą nie czeka — cała historia została w archiwum.",
            tekst_przycisku="Wróć na start",
            on_click=lambda e: utils.przejdz(self._page, "/"),
        )

    def _pusto(self):
        opis = (f"W najbliższych {utils.formatuj_dni(self.dni)} nic nie wypada. Dłuższe okno pokaże dalszy "
                "plan, a terminy OC i przeglądu, podzespoły z interwałem i wydatki cykliczne staną tu "
                "z datą, gdy je uzupełnisz. Prognoza miesięcy pojawi się po pierwszym pełnym miesiącu wpisów.")
        if self.podglad:
            return ft.Container(
                padding=30,
                content=ft.Column([
                    ft.Icon(ft.Icons.EVENT_AVAILABLE, size=46, color=ft.Colors.PRIMARY),
                    ft.Text("Nic tu jeszcze nie wypada", size=utils.FS["heading"], weight="bold"),
                    ft.Text(opis, size=utils.FS["body"], color=ft.Colors.ON_SURFACE_VARIANT,
                            text_align=ft.TextAlign.CENTER),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
            )
        return utils.ekran_braku_danych(
            ikona=ft.Icons.EVENT_AVAILABLE,
            tytul="Nic tu jeszcze nie wypada",
            opis=opis,
            tekst_przycisku="Uzupełnij daty",
            on_click=lambda e: utils.przejdz(self._page, f"/auto/edytuj/{self.state.auto_id}"),
        )

    # ================= LISTA =================

    def _elementy(self):
        os_dane = self.os
        pozycje, bez_daty = os_dane["pozycje"], os_dane["bez_daty"]
        if not pozycje and not bez_daty and not os_dane["podsumowanie"]["razem"]:
            return [self._pusto(), utils.dol_bezpieczny(10)]

        elementy = [utils.karta_podsumowania_osi(self._page, os_dane)]
        baner = self._baner_licznika()
        if baner is not None:
            elementy.append(baner)

        zalegle = [p for p in pozycje if p["zalegla"]]
        if zalegle:
            kwota = os_dane["podsumowanie"]["kwota_zalegla"]
            elementy.append(utils.naglowek_grupy_osi(
                self._page, "Zaległe", opis="termin minął, a sprawa wciąż czeka",
                wartosc=f"{utils.formatuj_liczba(kwota)} {utils.symbol_waluty()}" if kwota else "",
                kolor=utils.KOLOR_STATUS["critical"],
            ))
            elementy.extend(self._karty(zalegle, z_miesiacem=True))

        miesiace = os_dane["miesiace"]
        maks = max((m["razem"] for m in miesiace), default=0.0)
        for miesiac in miesiace:
            elementy.append(utils.naglowek_miesiaca_osi(self._page, miesiac, maks))
            elementy.extend(self._karty([
                p for p in pozycje if not p["zalegla"] and miesiac["od"] <= p["data"] <= miesiac["do"]
            ]))

        if bez_daty:
            elementy.append(utils.naglowek_grupy_osi(
                self._page, "Bez daty",
                opis="kilometrów bez średniego przebiegu nie da się przełożyć na datę — wystarczą dwa odczyty licznika",
            ))
            elementy.extend(self._karty(bez_daty))

        elementy.append(self._nota_o_liczeniu())
        elementy.append(utils.dol_bezpieczny(10))
        return elementy

    def _baner_licznika(self):
        """Daty przy kilometrach liczą się od ostatniego znanego przebiegu —
        gdy ten jest stary, mówimy to raz, nad listą (jak w „Ile zostało do…”)."""
        wszystkie = self.os["pozycje"] + self.os["bez_daty"]
        if not any(p["prognoza"] or p["zostalo_km"] is not None for p in wszystkie):
            return None
        return utils.baner_nieswiezego_licznika(
            self._page, self.state.auto_id, db.swiezosc_licznika(self.state.auto_id),
            po_zapisie=lambda: utils.odswiez_ekran(self._page),
        )

    def _karty(self, pozycje, z_miesiacem=False):
        """Karty pozycji; kolejna pozycja tego samego dnia nie powtarza dnia —
        jak w kalendarzu. Wśród zaległych dzień stoi zawsze, z miesiącem."""
        karty, poprzedni = [], None
        for pozycja in pozycje:
            pokaz_dzien = z_miesiacem or pozycja["data"] is None or pozycja["data"] != poprzedni
            poprzedni = pozycja["data"]
            karta, kontener = utils.karta_listy(
                utils.wiersz_osi(pozycja, self.j, pokaz_dzien=pokaz_dzien, z_miesiacem=z_miesiacem),
                kolor_paska=utils.kolor_paska_osi(pozycja), page=self._page,
            )
            obsluga = self._obsluga(pozycja)
            if obsluga:
                kontener.on_click = utils.z_efektem_nacisniecia(kontener, obsluga)
            else:
                kontener.ink = False
            karty.append(karta)
        return karty

    def _trasa(self, pozycja):
        """Dokąd prowadzi wiersz. Formularze dokumentów i podzespołu to zmiana
        danych, więc podgląd dostaje Kartę pojazdu albo nic (jak w „Ile
        zostało do…”); harmonogram rat, budżet, licznik i wpis z gwarancją to
        ekrany do oglądania."""
        if not self.podglad:
            return pozycja["trasa"]
        if pozycja["rodzaj"] in ("dokument", "gwarancja_km"):
            return "/pojazd"
        if pozycja["rodzaj"] in ("przebieg", "gwarancja_naprawy", "rata", "budzet"):
            return pozycja["trasa"]
        return None

    def _obsluga(self, pozycja):
        """Wpis cykliczny otwiera panel wydatków („Zapłacone”, „Zmieniono”),
        podpowiedź zmiany opon — ekran Opon, gdzie ustawia się przypomnienie;
        reszta idzie trasą. Podgląd niczego tam nie zmieni, więc nic nie dostaje."""
        akcja = pozycja.get("akcja")
        if akcja:
            if self.podglad:
                return None
            if akcja == "opony":
                return lambda e: utils.otworz_ekran(self._page, self.state, "opony")
            return lambda e: utils.pokaz_panel_wydatkow_cyklicznych(
                self._page, self.state, po_zamknieciu=self.odswiez_w_miejscu)
        trasa = self._trasa(pozycja)
        if not trasa:
            return None
        return lambda e, t=trasa: utils.przejdz(self._page, t)

    def _nota_o_liczeniu(self):
        miesiecy = self.os["miesiecy_bazowych"]
        if miesiecy:
            biezace = (f"Bieżące to średnia z {db.liczba_z_odmiana(miesiecy, 'ostatniego pełnego miesiąca', 'ostatnich pełnych miesięcy', 'ostatnich pełnych miesięcy')}: "
                       "paliwo i prąd, inne koszty i naprawy poza podzespołami z interwałem — w miesiącu "
                       "przeciętym brzegiem okna proporcjonalnie do dni. ")
        else:
            biezace = "Bieżących jeszcze nie ma — średnia potrzebuje choć jednego pełnego miesiąca wpisów. "
        return utils.nota_o_liczeniu(
            self._page, "Jak liczona jest prognoza",
            "Prognoza miesiąca to bieżące plus zaplanowane. " + biezace
            + "Zaplanowane to kwoty pozycji z tej listy: wydatki cykliczne, raty z harmonogramu "
            "i wymiany podzespołów po cenie ostatniej wymiany (z „~”). Zapłacone wydatki cykliczne "
            "i wymiany podzespołów z interwałem nie wchodzą do średniej — ich przyszłe kwoty stoją "
            "na liście, więc nic nie liczy się dwa razy. Polisa i przegląd nie mają tu kwoty; "
            "zapłacone zwykłym kosztem są w średniej. Kolejne wymiany zakładają wymianę w terminie, "
            "a daty przy kilometrach to prognoza ze średniego przebiegu dziennego. Zaległe stoją "
            "na górze bez względu na okno. Kolor mówi to samo, co powiadomienia: pomarańczowy — "
            "w progu przypomnienia, czerwony — po terminie albo ponad budżet.",
        )
