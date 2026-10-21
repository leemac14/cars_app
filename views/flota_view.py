import flet as ft

import db
import log
import utils


class FlotaView(ft.View):
    """Flota (N-07): wszystkie auta naraz — wydatki miesiąca i roku z porównaniem do zeszłego roku,
    auta z kondycją, udziałem w wydatkach i pilnymi terminami, terminy wszystkich aut na jednej osi
    (okno jak w „Co przede mną”). Liczy db.dane_floty; klocki — utils/flota.py i utils/przyszlosc.py.
    Dotknięcie auta albo terminu najpierw wybiera to auto."""

    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state
        self.j = utils.jednostka_dystansu()  # km albo mi — raz na ekran
        self.dni = db.pobierz_okno_przyszlosci()
        self.dane = None
        self.przelacznik = ft.Container()
        self.lista = ft.Column(spacing=10)
        self.scena = utils.ScenaWejscia(
            wlaczona=db.czy_animacje_interfejsu() and utils.pierwsze_pokazanie(state, "flota", None),
            kaskada=True,
        )

        if not db.auta_floty():
            super().__init__(
                route="/flota", padding=15, spacing=15,
                appbar=utils.zbuduj_pasek_z_powrotem(page, "Flota", "/", ikona=utils.IKONA_FLOTY),
                controls=[utils.ekran_braku_danych(
                    ikona=ft.Icons.GARAGE,
                    tytul="Garaż jest pusty",
                    opis="Dodaj auto — flota pokaże wydatki, terminy i kondycję wszystkich aut naraz.",
                    tekst_przycisku="Dodaj pojazd",
                    on_click=lambda e: utils.przejdz(self._page, "/auto/nowy"),
                )],
            )
            return

        akcje = [ft.IconButton(icon=ft.Icons.EDIT_CALENDAR, tooltip="Terminy wszystkich aut do kalendarza",
                               on_click=self._do_kalendarza)]
        appbar = utils.zbuduj_pasek_z_powrotem(page, "Flota", "/", akcje_dodatkowe=akcje, ikona=utils.IKONA_FLOTY)

        def tresc():
            self.przelacznik.content = self._segmenty()
            self._przelicz()
            return self.lista

        super().__init__(
            route="/flota", padding=15, appbar=appbar,
            controls=[utils.zbuduj_etapami(
                page, utils.szkielet_ekranu(page, karty=5, linie=2), tresc, widok=self,
                po_zbudowaniu=lambda: self.scena.uruchom(page),
            )],
            scroll=ft.ScrollMode.AUTO,
        )

    # ================= LICZENIE =================

    def _przelicz(self):
        self.dane = db.dane_floty(self.dni)
        self.lista.controls = self._elementy()

    def _odswiez(self, opis):
        # Odświeżenie to nie wejście na ekran — paski nie grają od nowa.
        self.scena = utils.ScenaWejscia(wlaczona=False, kaskada=True)
        self._przelicz()
        try:
            self.update()
        except Exception:
            log.polkniety(opis)

    def odswiez_w_miejscu(self):
        """Po „Zapłacone” w panelu wydatków, wysyłce do kalendarza albo „Cofnij” (utils.odswiez_ekran):
        flota liczy się od nowa, okno i miejsce zostają."""
        if self.dane is None:
            return
        self._odswiez("odświeżenie floty w miejscu")

    def _segmenty(self):
        return utils.segmented_control(
            self._page, [(utils.formatuj_dni(dni), dni) for dni in db.OKNA_PRZYSZLOSCI],
            self.dni, self._zmien_okno,
        )

    def _zmien_okno(self, dni):
        if dni == self.dni:
            return
        self.dni = dni
        db.zapisz_okno_przyszlosci(dni)
        self.przelacznik.content = self._segmenty()
        self._odswiez("przebudowa floty po zmianie okna")

    def _do_kalendarza(self, e=None):
        identyfikatory = [a["id"] for a in db.auta_floty()]

        async def _wyslij():
            await utils.wyslij_do_kalendarza(self._page, identyfikatory, self.odswiez_w_miejscu)

        self._page.run_task(_wyslij)

    # ================= PRZEJŚCIA DO AUTA =================

    def _wybierz_auto(self, auto):
        self.state.auto_id = auto["id"]
        self.state.auto_nazwa = str(auto["nazwa"])

    def _na_kokpit(self, auto):
        self._wybierz_auto(auto)
        self.state.zakladka = 0
        utils.przejdz(self._page, "/")

    def _trasa(self, pozycja):
        """Jak w „Co przede mną”: podgląd dostaje Kartę pojazdu albo ekran do oglądania."""
        if not pozycja["pojazd"]["podglad"]:
            return pozycja["trasa"]
        if pozycja["rodzaj"] in ("dokument", "gwarancja_km"):
            return "/pojazd"
        if pozycja["rodzaj"] in ("przebieg", "gwarancja_naprawy", "rata", "budzet", "skarbiec"):
            return pozycja["trasa"]
        return None

    def _obsluga(self, pozycja):
        """Wpis cykliczny — panel wydatków tego auta, podpowiedź opon — jego Opony, reszta trasą;
        przy podglądzie akcje znikają."""
        auto = pozycja["pojazd"]
        akcja = pozycja.get("akcja")
        if akcja:
            if auto["podglad"]:
                return None
            if akcja == "opony":
                def opony(e, a=auto):
                    self._wybierz_auto(a)
                    utils.otworz_ekran(self._page, self.state, "opony")
                return opony

            def cykliczne(e, a=auto):
                self._wybierz_auto(a)
                utils.pokaz_panel_wydatkow_cyklicznych(self._page, self.state, po_zamknieciu=self.odswiez_w_miejscu)
            return cykliczne
        trasa = self._trasa(pozycja)
        if not trasa:
            return None

        def do_trasy(e, a=auto, t=trasa):
            self._wybierz_auto(a)
            utils.przejdz(self._page, t)
        return do_trasy

    # ================= TREŚĆ =================

    def _elementy(self):
        dane = self.dane
        elementy = []
        if len(dane["auta"]) == 1:
            elementy.append(self._jedno_auto())
        elementy.append(utils.karta_wydatkow_floty(self._page, dane["koszty"], scena=self.scena))

        liczba = db.liczba_z_odmiana(len(dane["auta"]), "auto", "auta", "aut")
        pilne = utils.opis_pilnych(dane["pilne"], sum(a["zalegle"] for a in dane["auta"]))
        elementy.append(utils.naglowek_sekcji_floty(
            ft.Icons.DIRECTIONS_CAR, "Auta", f"{liczba} w garażu" + (f" · {pilne}" if pilne else "")))
        elementy.extend(self._karta_auta(a) for a in dane["auta"])

        elementy.append(utils.naglowek_sekcji_floty(
            ft.Icons.EVENT_NOTE, "Terminy wszystkich aut", "zaległe na górze, dalej od najbliższego"))
        elementy.append(self.przelacznik)
        elementy.extend(self._terminy())
        elementy.append(utils.nota_o_liczeniu(self._page, "Jak liczymy", utils.nota_floty()))
        elementy.append(utils.dol_bezpieczny(10))
        return elementy

    def _jedno_auto(self):
        return ft.Container(
            padding=utils.SPACING["md"], **utils.powierzchnia(self._page, "blok"),
            content=ft.Column([
                utils.podpis("Flota pokazuje wszystkie auta naraz — z jednym autem to te same liczby, co na "
                             "jego kokpicie. Drugie auto doda sumy i porównanie."),
                ft.Row([ft.TextButton("Dodaj pojazd", icon=ft.Icons.ADD_CIRCLE_OUTLINE,
                                      on_click=lambda e: utils.przejdz(self._page, "/auto/nowy"))],
                       alignment=ft.MainAxisAlignment.END),
            ], spacing=utils.SPACING["xs"]),
        )

    def _karta_auta(self, auto):
        karta, kontener = utils.karta_auta_floty(
            self._page, auto,
            on_kondycja=lambda e, a=auto: utils.pokaz_panel_kondycji(self._page, self.state, auto_id=a["id"],
                                                                     nazwa=a["nazwa"]),
            scena=self.scena,
        )
        kontener.on_click = utils.z_efektem_nacisniecia(kontener, lambda e, a=auto: self._na_kokpit(a))
        return karta

    def _terminy(self):
        os_dane = self.dane["os"]
        pozycje, bez_daty = os_dane["pozycje"], os_dane["bez_daty"]
        if not pozycje and not bez_daty:
            return [ft.Container(padding=utils.SPACING["md"], content=utils.podpis(
                f"W najbliższych {utils.formatuj_dni(self.dni)} żadne auto nie ma terminu. Dłuższe okno pokaże "
                "dalszy plan; daty OC, przeglądu i podzespołów uzupełnisz w danych każdego auta."))]

        elementy = [utils.karta_podsumowania_osi(self._page, os_dane)]
        zalegle = [p for p in pozycje if p["zalegla"]]
        if zalegle:
            kwota = os_dane["podsumowanie"]["kwota_zalegla"]
            elementy.append(utils.naglowek_grupy_osi(
                self._page, "Zaległe", opis="termin minął, a sprawa wciąż czeka",
                wartosc=utils.kwota_floty(kwota) if kwota else "", kolor=utils.KOLOR_STATUS["critical"],
            ))
            elementy.extend(self._karty(zalegle, z_miesiacem=True))

        miesiace = os_dane["miesiace"]
        maks = max((m["razem"] for m in miesiace), default=0.0)
        for miesiac in miesiace:
            w_miesiacu = [p for p in pozycje if not p["zalegla"] and miesiac["od"] <= p["data"] <= miesiac["do"]]
            elementy.append(utils.naglowek_miesiaca_osi(self._page, miesiac, maks))
            elementy.extend(self._karty(w_miesiacu))

        if bez_daty:
            elementy.append(utils.naglowek_grupy_osi(
                self._page, "Bez daty",
                opis="kilometrów bez średniego przebiegu nie da się przełożyć na datę — wystarczą dwa odczyty licznika",
            ))
            elementy.extend(self._karty(bez_daty))
        return elementy

    def _karty(self, pozycje, z_miesiacem=False):
        """Karty pozycji z autem nad nazwą; kolejna pozycja tego samego dnia nie powtarza dnia."""
        karty, poprzedni = [], None
        for pozycja in pozycje:
            pokaz_dzien = z_miesiacem or pozycja["data"] is None or pozycja["data"] != poprzedni
            poprzedni = pozycja["data"]
            karta, kontener = utils.karta_listy(
                utils.wiersz_osi(pozycja, self.j, pokaz_dzien=pokaz_dzien, z_miesiacem=z_miesiacem,
                                 pojazd=pozycja["pojazd"]),
                kolor_paska=utils.kolor_paska_osi(pozycja), page=self._page,
            )
            obsluga = self._obsluga(pozycja)
            if obsluga:
                kontener.on_click = utils.z_efektem_nacisniecia(kontener, obsluga)
            else:
                kontener.ink = False
            karty.append(karta)
        return karty
