import flet as ft

import db
import utils
from state import MIESIACE_NAZWY
from views.rok_view import SekcjePigulki


class MiesiacWPigulceView(SekcjePigulki, ft.View):
    """„Rok w pigułce” dla miesiąca — ekran i grafika; wspólne z rokiem przez
    `SekcjePigulki`, własne: strzałki miesięcy, słupki dni, werdykt z porównaniami.
    Trasy: `/miesiac/2026/9` (szuflada, wyszukiwarka; powrót na start) i `/rok/2026/9`
    (słupek w Roku — ekran leży NA roku, „wstecz” wraca do roku)."""

    def __init__(self, page: ft.Page, state, rok=None, miesiac=None, z_roku=False):
        self._page = page
        self.state = state
        self.j = utils.jednostka_dystansu()  # km albo mi — raz na ekran
        self._prefiks = "/rok" if z_roku else "/miesiac"

        def pasek(powrot):
            return utils.zbuduj_pasek_z_powrotem(page, "Miesiąc w pigułce", powrot,
                                                 ikona=ft.Icons.CALENDAR_MONTH)

        if not self.state.auto_id:
            super().__init__(
                route="/miesiac", padding=15, spacing=15, appbar=pasek("/"),
                controls=[utils.ekran_braku_danych(
                    ikona=ft.Icons.DIRECTIONS_CAR,
                    tytul="Brak wybranego pojazdu",
                    opis="Wybierz pojazd, aby zobaczyć jego miesięczne podsumowanie.",
                    tekst_przycisku="Wróć na start",
                    on_click=lambda e: utils.przejdz(self._page, "/")
                )]
            )
            return

        self.miesiace = db.miesiace_z_danymi(self.state.auto_id)
        wybrany = db.wybierz_miesiac_pigulki(self.miesiace, rok, miesiac)
        if wybrany is None:
            super().__init__(
                route="/miesiac", padding=15, spacing=15, appbar=pasek("/"),
                controls=[utils.ekran_braku_danych(
                    ikona=ft.Icons.CALENDAR_MONTH,
                    tytul="Nie ma jeszcze czego podsumowywać",
                    opis="Dodaj tankowania i koszty, a pojawi się tu podsumowanie miesiąca "
                         "razem z grafiką do wysłania.",
                    tekst_przycisku="Dodaj tankowanie",
                    on_click=lambda e: utils.przejdz(self._page, "/tankowanie/nowe")
                )]
            )
            return
        self.rok, self.miesiac = wybrany

        # Paski „na co poszły pieniądze” najeżdżają od zera, kaskadą — raz na
        # uruchomienie aplikacji, jak w roku.
        self.scena = utils.ScenaWejscia(
            wlaczona=db.czy_animacje_interfejsu()
            and utils.pierwsze_pokazanie(state, "miesiac", state.auto_id),
            kaskada=True,
        )
        self.dane = None

        def tresc():
            # Kilkanaście zapytań — liczone dopiero po tym, jak zarys trafi na ekran.
            self.dane = db.podsumowanie_miesiaca(self.state.auto_id, self.rok, self.miesiac)

            elementy = [self._pasek_miesiecy()]
            if not self.dane:
                elementy.append(ft.Text("W tym miesiącu nie ma jeszcze wpisów do podsumowania.",
                                        color=ft.Colors.ON_SURFACE_VARIANT))
            else:
                elementy.append(self._karta_glowna())
                elementy.append(self._kafle())
                elementy.append(self._rozbicie_kosztow())
                elementy.append(self._wykres_dni())
                elementy.append(self._werdykty())
                elementy.append(self._przycisk_grafiki())

            elementy.append(utils.dol_bezpieczny(10))
            self.scena.uruchom(page)
            return ft.Column(elementy, spacing=15)

        super().__init__(
            route=f"{self._prefiks}/{self.rok}/{self.miesiac}", padding=15, spacing=15,
            appbar=pasek(f"/rok/{self.rok}" if z_roku else "/"),
            controls=[utils.zbuduj_etapami(
                page, utils.szkielet_ekranu(page, kafle=4, wykres=True, karty=2),
                tresc, widok=self,
            )],
            scroll=ft.ScrollMode.AUTO,
        )

    # ================= SEKCJE =================

    def _nazwa_miesiaca(self, rok, miesiac):
        return f"{MIESIACE_NAZWY[miesiac - 1]} {rok}"

    def _pasek_miesiecy(self):
        """Strzałki chodzą po miesiącach Z WPISAMI — pusty miesiąc nie ma czego
        podsumować, a krok o jeden wstecz wpadałby na same zera."""
        i = self.miesiace.index((self.rok, self.miesiac))  # lista od najnowszego
        starszy = self.miesiace[i + 1] if i + 1 < len(self.miesiace) else None
        nowszy = self.miesiace[i - 1] if i > 0 else None

        def strzalka(ikona, cel):
            return ft.IconButton(
                ikona, disabled=cel is None,
                tooltip=self._nazwa_miesiaca(*cel) if cel else None,
                on_click=(lambda e: utils.przejdz(self._page, f"{self._prefiks}/{cel[0]}/{cel[1]}"))
                if cel else None,
            )

        return ft.Row([
            strzalka(ft.Icons.CHEVRON_LEFT, starszy),
            ft.Container(
                ft.Text(self._nazwa_miesiaca(self.rok, self.miesiac), weight="bold", size=16),
                alignment=ft.Alignment.CENTER, expand=True,
            ),
            strzalka(ft.Icons.CHEVRON_RIGHT, nowszy),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

    def _karta_glowna(self):
        """Miesiąc, kilometry, pieniądze — trzy rzeczy, po które się tu
        przychodzi. Nazwa miesiąca sama w wierszu: „Październik” obok plakietki
        nie zmieściłby się na telefonie."""
        d = self.dane
        return ft.Container(
            padding=utils.SPACING["lg"], border_radius=utils.RADIUS["xl"],
            bgcolor=ft.Colors.with_opacity(0.10, ft.Colors.PRIMARY),
            content=ft.Column([
                ft.Text(MIESIACE_NAZWY[d["miesiac"] - 1], size=40, weight="bold", color=ft.Colors.PRIMARY,
                        no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Row([
                    ft.Text(f"{d['rok']} • {self.state.auto_nazwa}", size=utils.FS["title"], weight="bold",
                            expand=True, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Container(
                        padding=ft.Padding(10, 3, 10, 3), border_radius=utils.RADIUS["pill"],
                        bgcolor=utils.tlo_odznaki(self._page),
                        content=ft.Text("miesiąc w toku", size=utils.FS["caption"],
                                        color=ft.Colors.ON_SURFACE_VARIANT),
                        visible=bool(d.get("niepelny")),
                    ),
                ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                *self._liczby_karty(),
            ], spacing=utils.SPACING["sm"]),
        )

    def _wykres_dni(self):
        """Słupek na dzień, najdroższy podświetlony. Podpisy liczone w połówkach dnia
        (podpis zajmuje dwa dni wyśrodkowane na słupku); dni z podpisem jak na grafice
        (`db.podpisy_dni_miesiaca`)."""
        d = self.dane
        dni = d["dni"]
        maks = max(dni.values()) if dni else 0
        if maks <= 0:
            return ft.Container()

        WYS_MAX = 110
        liczba_dni = len(dni)
        szczyt = d["najdrozszy_dzien"]["dzien"]
        dopelniacz = utils.MIESIACE_DOPELNIACZ[d["miesiac"] - 1]
        waluta = utils.symbol_waluty()

        slupki = []
        for dzien in range(1, liczba_dni + 1):
            wartosc = dni[dzien]
            czy_szczyt = dzien == szczyt and wartosc > 0
            slupki.append(ft.Container(
                expand=2, height=WYS_MAX, alignment=ft.Alignment.BOTTOM_CENTER,
                tooltip=f"{dzien} {dopelniacz}: {utils.formatuj_liczba(wartosc)} {waluta}",
                content=ft.Container(
                    width=6, height=max(3, int(WYS_MAX * wartosc / maks)) if wartosc > 0 else 3,
                    bgcolor=ft.Colors.PRIMARY if czy_szczyt
                    else ft.Colors.with_opacity(0.45 if wartosc > 0 else 0.12, ft.Colors.ON_SURFACE),
                    border_radius=3,
                    animate=ft.Animation(300, ft.AnimationCurve.EASE_OUT),
                ),
            ))

        # Pasek podpisów w połówkach dnia: środek dnia `n` leży na 2n−1.
        podpisy, kursor = [], 0
        for dzien, napis in enumerate(db.podpisy_dni_miesiaca(liczba_dni, szczyt), start=1):
            if not napis:
                continue
            od, do = max(kursor, 2 * dzien - 3), min(2 * liczba_dni, 2 * dzien + 1)
            if od > kursor:
                podpisy.append(ft.Container(expand=od - kursor))
            czy_szczyt = dzien == szczyt
            podpisy.append(ft.Container(
                expand=do - od, alignment=ft.Alignment.CENTER,
                content=ft.Text(napis, size=10, no_wrap=True,
                                color=ft.Colors.PRIMARY if czy_szczyt else ft.Colors.ON_SURFACE_VARIANT,
                                weight="bold" if czy_szczyt else "normal"),
            ))
            kursor = do
        if kursor < 2 * liczba_dni:
            podpisy.append(ft.Container(expand=2 * liczba_dni - kursor))

        return utils.karta_analizy(self._page, "Dzień po dniu", ft.Icons.BAR_CHART, [
            ft.Row(slupki, spacing=0, vertical_alignment=ft.CrossAxisAlignment.END),
            ft.Row(podpisy, spacing=0),
        ])

    def _werdykty(self):
        d = self.dane
        waluta = utils.symbol_waluty()
        pozycje = []

        najdr = d["najdrozszy_dzien"]
        if najdr["kwota"] > 0:
            pozycje.append((ft.Icons.TRENDING_UP, utils.KOLOR_STATUS["critical"], "Najdroższy dzień",
                            f"{najdr['dzien']} {utils.MIESIACE_DOPELNIACZ[d['miesiac'] - 1]} • "
                            f"{utils.formatuj_liczba(najdr['kwota'])} {waluta}"))

        if d.get("najwiekszy_wydatek"):
            nw = d["najwiekszy_wydatek"]
            pozycje.append((ft.Icons.PRIORITY_HIGH, utils.KOLOR_STATUS["accent"], "Największy pojedynczy wydatek",
                            f"{nw['opis']} • {utils.formatuj_liczba(nw['kwota'])} {waluta} ({nw['data']})"))

        if d.get("ulubiona_stacja"):
            st = d["ulubiona_stacja"]
            pozycje.append((ft.Icons.STORE, utils.KOLOR_STATUS["accent"], "Ulubiona stacja",
                            f"{st['nazwa']} • {st['liczba']}x na {utils.formatuj_liczba(st['kwota'])} {waluta}"))

        # Poprzedni miesiąc mówi o trendzie, ten sam miesiąc rok temu — bez
        # sezonu: styczeń z wrześniem przegrywa zawsze, bo zimą auto więcej pali.
        for klucz, ikona in (("poprzedni_miesiac", ft.Icons.COMPARE_ARROWS), ("rok_temu", ft.Icons.HISTORY)):
            p = d.get(klucz)
            if not p or p.get("zmiana") is None:
                continue
            drozej = p["zmiana"] > 0
            pozycje.append((
                ikona, utils.KOLOR_STATUS["critical"] if drozej else utils.KOLOR_STATUS["ok"],
                db.opis_porownania_miesiaca(p, d["rok"], d.get("niepelny")),
                f"{'Drożej' if drozej else 'Taniej'} o {utils.formatuj_liczba(abs(p['zmiana']), 0)}% "
                f"({utils.formatuj_liczba(p['kwota'])} {waluta})",
            ))

        return self._karta_werdyktu("Werdykt miesiąca", pozycje)

    # ================= GRAFIKA =================

    def _rysuj_grafike(self, akcent):
        return db.generuj_grafike_miesiaca(self.state.auto_nazwa, self.dane, akcent)

    def _nazwa_grafiki(self):
        return (f"miesiac_{self.rok}-{self.miesiac:02d}_"
                f"{utils.bezpieczna_nazwa_pliku(self.state.auto_nazwa)}.png")
