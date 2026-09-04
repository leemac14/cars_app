import flet as ft
import asyncio
from datetime import datetime

import db
import utils
from state import MIESIACE_NAZWY


class RokWPigulceView(ft.View):
    """Podsumowanie roku — ekran i grafika do wysłania. Ton celowo taki sam, jak
    „Werdykt” w Porównaniu pojazdów: krótkie zdania i konkretne liczby zamiast
    tabeli, po której trzeba wodzić palcem."""

    def __init__(self, page: ft.Page, state, rok=None):
        self._page = page
        self.state = state

        appbar = utils.zbuduj_pasek_z_powrotem(page, "Rok w pigułce", "/", ikona=ft.Icons.AUTO_AWESOME)

        if not self.state.auto_id:
            super().__init__(
                route="/rok", padding=15, spacing=15, appbar=appbar,
                controls=[utils.ekran_braku_danych(
                    ikona=ft.Icons.DIRECTIONS_CAR,
                    tytul="Brak wybranego pojazdu",
                    opis="Wybierz pojazd, aby zobaczyć jego roczne podsumowanie.",
                    tekst_przycisku="Wróć na start",
                    on_click=lambda e: utils.przejdz(self._page, "/")
                )]
            )
            return

        lata = db.lata_z_danymi(self.state.auto_id)
        if not lata:
            super().__init__(
                route="/rok", padding=15, spacing=15, appbar=appbar,
                controls=[utils.ekran_braku_danych(
                    ikona=ft.Icons.AUTO_AWESOME,
                    tytul="Nie ma jeszcze czego podsumowywać",
                    opis="Dodaj tankowania i koszty, a po kilku wpisach pojawi się tu "
                         "podsumowanie roku razem z grafiką do wysłania.",
                    tekst_przycisku="Dodaj tankowanie",
                    on_click=lambda e: utils.przejdz(self._page, "/tankowanie/nowe")
                )]
            )
            return

        self.rok = int(rok) if rok and int(rok) in lata else lata[0]
        self.dane = db.podsumowanie_roku(self.state.auto_id, self.rok)

        elementy = []
        if len(lata) > 1:
            elementy.append(utils.segmented_control(
                page, [(str(r), r) for r in lata[:4]], self.rok,
                lambda r: utils.przejdz(self._page, f"/rok/{r}")
            ))

        if not self.dane:
            elementy.append(ft.Text(f"Brak wpisów w roku {self.rok}.",
                                    color=ft.Colors.ON_SURFACE_VARIANT))
        else:
            elementy.append(self._karta_glowna())
            elementy.append(self._kafle())
            elementy.append(self._rozbicie_kosztow())
            elementy.append(self._wykres_miesiecy())
            elementy.append(self._werdykty())
            elementy.append(self._przycisk_grafiki())

        elementy.append(utils.dol_bezpieczny(10))

        super().__init__(
            route=f"/rok/{self.rok}", padding=15, spacing=15, appbar=appbar,
            controls=[utils.z_odswiezaniem(page, elementy)],
        )

    # ================= SEKCJE =================

    def _karta_glowna(self):
        """Trzy liczby, po które przychodzi się na ten ekran: rok, kilometry,
        pieniądze. Reszta jest rozwinięciem tych trzech."""
        d = self.dane
        return ft.Container(
            padding=utils.SPACING["lg"], border_radius=utils.RADIUS["xl"],
            bgcolor=ft.Colors.with_opacity(0.10, ft.Colors.PRIMARY),
            content=ft.Column([
                ft.Row([
                    ft.Text(str(d["rok"]), size=44, weight="bold", color=ft.Colors.PRIMARY),
                    ft.Container(
                        padding=ft.Padding(10, 3, 10, 3), border_radius=utils.RADIUS["pill"],
                        bgcolor=ft.Colors.with_opacity(0.14, ft.Colors.ON_SURFACE),
                        content=ft.Text("rok w toku", size=utils.FS["caption"],
                                        color=ft.Colors.ON_SURFACE_VARIANT),
                        visible=bool(d.get("niepelny")),
                    ),
                ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Text(self.state.auto_nazwa, size=utils.FS["title"], weight="bold"),
                ft.Divider(height=14),
                ft.Row([
                    self._liczba("Przejechane", f"{utils.formatuj_liczba(d['km'], 0)} km"),
                    self._liczba("Wydane", f"{utils.formatuj_liczba(d['koszty']['razem'])} {utils.symbol_waluty()}"),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([
                    ft.Icon(ft.Icons.PUBLIC, size=15, color=ft.Colors.PRIMARY),
                    ft.Text(f"To {d['porownanie_dystansu']}.", size=utils.FS["body"],
                            color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                ], spacing=6, visible=bool(d.get("porownanie_dystansu"))),
            ], spacing=utils.SPACING["sm"]),
        )

    def _liczba(self, etykieta, wartosc):
        return ft.Column([
            ft.Text(etykieta, size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Text(wartosc, size=utils.FS["display"], weight="bold"),
        ], spacing=0)

    def _kafle(self):
        d = self.dane
        elektryczny = db.czy_pojazd_elektryczny(self.state.auto_id)

        def kafel(ikona, etykieta, wartosc, kolor):
            return ft.Container(
                expand=1, padding=utils.SPACING["md"], border_radius=utils.RADIUS["lg"],
                bgcolor=utils.tlo_karty(self._page, poziom=1),
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ikona, size=15, color=kolor),
                        ft.Text(etykieta, size=utils.FS["caption"],
                                color=ft.Colors.ON_SURFACE_VARIANT, expand=True,
                                no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                    ], spacing=6),
                    ft.Text(wartosc, size=utils.FS["title"], weight="bold",
                            no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                ], spacing=4),
            )

        koszt_km = (f"{utils.formatuj_liczba(d['koszt_km'], 2)} {utils.symbol_waluty()}"
                    if d.get("koszt_km") else "—")
        zuzycie = (utils.formatuj_spalanie(d["srednie_zuzycie"], elektryczny=elektryczny)
                   if d.get("srednie_zuzycie") else "—")
        ilosc = (f"{utils.formatuj_liczba(d['kwh'], 0)} kWh" if elektryczny and d.get("kwh")
                 else f"{utils.formatuj_liczba(d['litry'], 0)} l")

        return ft.Column([
            ft.Row([
                kafel(ft.Icons.ADD_ROAD, "Koszt kilometra", koszt_km, ft.Colors.PURPLE_700),
                kafel(ft.Icons.SPEED, "Średnie zużycie", zuzycie, ft.Colors.TEAL_700),
            ], spacing=10),
            ft.Row([
                kafel(ft.Icons.LOCAL_GAS_STATION, "Tankowań", str(d["liczba_tankowan"]), ft.Colors.BLUE_700),
                kafel(ft.Icons.WATER_DROP, "Zatankowane", ilosc, ft.Colors.CYAN_700),
            ], spacing=10),
            ft.Row([
                kafel(ft.Icons.BUILD, "Wpisy serwisowe", str(d["liczba_wpisow_serwisu"]), ft.Colors.ORANGE_700),
                kafel(ft.Icons.HOME_REPAIR_SERVICE, "Wizyty w warsztacie", str(d["liczba_wizyt"]), ft.Colors.RED_700),
            ], spacing=10),
        ], spacing=10)

    def _rozbicie_kosztow(self):
        d = self.dane
        razem = d["koszty"]["razem"] or 1

        def pasek(etykieta, wartosc, kolor):
            procent = wartosc / razem * 100
            return ft.Column([
                ft.Row([
                    ft.Text(etykieta, size=utils.FS["body_strong"], weight="bold", expand=True),
                    ft.Text(f"{utils.formatuj_liczba(wartosc)} {utils.symbol_waluty()} "
                            f"({utils.formatuj_liczba(procent, 0)}%)",
                            size=utils.FS["body"], weight="bold", color=kolor),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.ProgressBar(value=max(0.0, min(1.0, procent / 100)), color=kolor,
                               bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE),
                               height=8, border_radius=4),
            ], spacing=4)

        return utils.karta_analizy(self._page, "Na co poszły pieniądze", ft.Icons.PIE_CHART, [
            pasek("Paliwo i energia", d["koszty"]["paliwo"], ft.Colors.BLUE_700),
            pasek("Serwis", d["koszty"]["serwis"], ft.Colors.ORANGE_700),
            pasek("Inne koszty", d["koszty"]["inne"], ft.Colors.GREEN_700),
        ])

    def _wykres_miesiecy(self):
        """Rok najlepiej widać w rytmie miesięcy — jeden słupek na miesiąc,
        najdroższy podświetlony, bo to on zwykle ma swoją historię."""
        d = self.dane
        maks = max(d["miesiace"].values()) if d["miesiace"] else 0
        if maks <= 0:
            return ft.Container()

        WYS_MAX = 110
        kolumny = []
        for m in range(1, 13):
            wartosc = d["miesiace"][m]
            wysokosc = int(WYS_MAX * (wartosc / maks)) if wartosc > 0 else 4
            czy_szczyt = (m == d["najdrozszy_miesiac"]["miesiac"] and wartosc > 0)
            kolumny.append(ft.Column([
                ft.Container(
                    width=18, height=max(4, wysokosc),
                    bgcolor=ft.Colors.PRIMARY if czy_szczyt
                    else ft.Colors.with_opacity(0.45 if wartosc > 0 else 0.12, ft.Colors.ON_SURFACE),
                    border_radius=5,
                    tooltip=f"{MIESIACE_NAZWY[m - 1]}: {utils.formatuj_liczba(wartosc)} {utils.symbol_waluty()}",
                    animate=ft.Animation(300, ft.AnimationCurve.EASE_OUT),
                ),
                ft.Text(MIESIACE_NAZWY[m - 1][:3].lower(), size=10,
                        color=ft.Colors.PRIMARY if czy_szczyt else ft.Colors.ON_SURFACE_VARIANT,
                        weight="bold" if czy_szczyt else "normal"),
            ], alignment=ft.MainAxisAlignment.END,
               horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4))

        return utils.karta_analizy(self._page, "Miesiąc po miesiącu", ft.Icons.BAR_CHART, [
            ft.Row(kolumny, alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                   vertical_alignment=ft.CrossAxisAlignment.END),
        ])

    def _werdykty(self):
        d = self.dane
        pozycje = []

        najdr = d["najdrozszy_miesiac"]
        pozycje.append((ft.Icons.TRENDING_UP, ft.Colors.RED_700, "Najdroższy miesiąc",
                        f"{MIESIACE_NAZWY[najdr['miesiac'] - 1]} • "
                        f"{utils.formatuj_liczba(najdr['kwota'])} {utils.symbol_waluty()}"))

        najt = d["najtanszy_miesiac"]
        if najt["miesiac"] != najdr["miesiac"]:
            pozycje.append((ft.Icons.TRENDING_DOWN, ft.Colors.GREEN_700, "Najspokojniejszy miesiąc",
                            f"{MIESIACE_NAZWY[najt['miesiac'] - 1]} • "
                            f"{utils.formatuj_liczba(najt['kwota'])} {utils.symbol_waluty()}"))

        if d.get("ulubiona_stacja"):
            st = d["ulubiona_stacja"]
            pozycje.append((ft.Icons.STORE, ft.Colors.AMBER_800, "Ulubiona stacja",
                            f"{st['nazwa']} • {st['liczba']}x na "
                            f"{utils.formatuj_liczba(st['kwota'])} {utils.symbol_waluty()}"))

        if d.get("najwiekszy_wydatek"):
            nw = d["najwiekszy_wydatek"]
            pozycje.append((ft.Icons.PRIORITY_HIGH, ft.Colors.DEEP_ORANGE_700, "Największy pojedynczy wydatek",
                            f"{nw['opis']} • {utils.formatuj_liczba(nw['kwota'])} {utils.symbol_waluty()} "
                            f"({nw['data']})"))

        if d.get("zmiana_rdr") is not None:
            drozej = d["zmiana_rdr"] > 0
            pozycje.append((
                ft.Icons.COMPARE_ARROWS, ft.Colors.RED_700 if drozej else ft.Colors.GREEN_700,
                f"Względem {d['rok'] - 1} roku",
                f"{'Drożej' if drozej else 'Taniej'} o {utils.formatuj_liczba(abs(d['zmiana_rdr']), 0)}% "
                f"({utils.formatuj_liczba(d['poprzedni_rok'])} {utils.symbol_waluty()})"
            ))

        wiersze = [
            ft.Row([
                ft.Icon(ikona, size=20, color=kolor),
                ft.Column([
                    ft.Text(etykieta, size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Text(wartosc, size=utils.FS["body_strong"], weight="bold", color=kolor),
                ], spacing=0, expand=True),
            ], spacing=10)
            for ikona, kolor, etykieta, wartosc in pozycje
        ]

        return ft.Container(
            padding=18, border_radius=16,
            bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.PRIMARY),
            content=ft.Column([
                ft.Row([ft.Icon(ft.Icons.EMOJI_EVENTS, color=ft.Colors.AMBER_700),
                        ft.Text("Werdykt roku", weight="bold", size=16, color=ft.Colors.PRIMARY)], spacing=8),
                ft.Divider(height=15),
                ft.Column(wiersze, spacing=12),
            ]),
        )

    def _przycisk_grafiki(self):
        return ft.Column([
            ft.FilledButton(
                "Zapisz grafikę do wysłania", icon=ft.Icons.IOS_SHARE,
                on_click=self.zapisz_grafike, width=10000, height=48,
            ),
            ft.Text(
                "Obrazek 1080×1440 z tym podsumowaniem — do zapisania w galerii "
                "albo wysłania bliskim.",
                size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
            ),
        ], spacing=6)

    # ================= AKCJE =================

    async def zapisz_grafike(self, e):
        zapisywacz = getattr(self._page, "zapisz_bajty_pliku", None)
        if zapisywacz is None:
            utils.pokaz_komunikat(self._page, "Zapis pliku jest niedostępny w tej wersji aplikacji.",
                                  ft.Colors.RED_700)
            return

        dialog = utils.pokaz_ladowanie(self._page, "Rysuję podsumowanie...")
        try:
            kolor_akcentu = utils.rgb_koloru_motywu(db.pobierz_kolor_auta(self.state.auto_id))
            # Rysowanie idzie do wątku: przy dużym kadrze i gradiencie potrafi
            # zająć ułamek sekundy, a interfejs nie ma prawa w tym czasie zamarzać.
            png = await asyncio.to_thread(
                db.generuj_grafike_roku, self.state.auto_nazwa, self.dane, kolor_akcentu
            )
        except Exception as ex:
            utils.ukryj_ladowanie(self._page, dialog)
            utils.pokaz_komunikat(self._page, f"Nie udało się wygenerować grafiki: {ex}", ft.Colors.RED_700)
            return

        utils.ukryj_ladowanie(self._page, dialog)
        nazwa = f"rok_{self.rok}_{utils.bezpieczna_nazwa_pliku(self.state.auto_nazwa)}.png"
        await zapisywacz(nazwa, png)
