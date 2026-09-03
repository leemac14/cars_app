import flet as ft
from datetime import datetime
import db
import sync
import utils
from state import MIESIACE_NAZWY


class PodzialKosztowView(ft.View):
    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state

        appbar = utils.zbuduj_pasek_z_powrotem(page, "Podział kosztów", "/", ikona=ft.Icons.HANDSHAKE)

        if not self.state.auto_id:
            super().__init__(
                route="/podzial", padding=15, spacing=15, appbar=appbar,
                controls=[utils.ekran_braku_danych(
                    ikona=ft.Icons.DIRECTIONS_CAR,
                    tytul="Brak wybranego pojazdu",
                    opis="Wybierz pojazd, aby zobaczyć podział kosztów.",
                    tekst_przycisku="Wróć na start",
                    on_click=lambda e: utils.przejdz(self._page, "/")
                )]
            )
            return

        wspolny_id, _ = sync.czy_udostepniony(self.state.auto_id)
        if not wspolny_id:
            super().__init__(
                route="/podzial", padding=15, spacing=15, appbar=appbar,
                controls=[utils.ekran_braku_danych(
                    ikona=ft.Icons.PEOPLE,
                    tytul="Ten pojazd nie jest współdzielony",
                    opis="Podział kosztów ma sens, gdy kilka osób dopisuje wydatki do tego samego pojazdu. Włącz współdzielenie, aby zacząć śledzić, kto ile wydał.",
                    tekst_przycisku="Przejdź do współdzielenia",
                    on_click=lambda e: utils.przejdz(self._page, "/wspoldzielenie")
                )]
            )
            return

        appbar = utils.zbuduj_pasek_z_powrotem(
            page, "Podział kosztów", "/", ikona=ft.Icons.HANDSHAKE,
            akcje_dodatkowe=[utils.przycisk_synchronizacji(page, utils.funkcja_szybkiej_synchronizacji(page, self.state.auto_id, "/podzial"))]
        )

        dzis = datetime.now()
        self.rok = getattr(state, "podzial_rok", None) or dzis.year
        self.miesiac = getattr(state, "podzial_miesiac", None) or dzis.month

        def zmien_miesiac(delta):
            m, r = self.miesiac + delta, self.rok
            while m < 1: m += 12; r -= 1
            while m > 12: m -= 12; r += 1
            self.state.podzial_rok, self.state.podzial_miesiac = r, m
            utils.przejdz(self._page, "/podzial")

        pasek_miesiaca = ft.Row([
            ft.IconButton(ft.Icons.CHEVRON_LEFT, on_click=lambda e: zmien_miesiac(-1)),
            ft.Container(
                ft.Text(f"{MIESIACE_NAZWY[self.miesiac - 1]} {self.rok}", weight="bold", size=16),
                alignment=ft.Alignment.CENTER, expand=True
            ),
            ft.IconButton(ft.Icons.CHEVRON_RIGHT, on_click=lambda e: zmien_miesiac(1)),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

        dane = db.pobierz_podzial_kosztow(self.state.auto_id, self.rok, self.miesiac)
        waluta = utils.symbol_waluty()
        wyniki = []

        if not dane:
            wyniki.append(ft.Container(
                padding=30,
                content=ft.Text("Brak wydatków w tym miesiącu.", color=ft.Colors.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER)
            ))
        else:
            suma_wszystkich = sum(d["razem"] for d in dane)
            liczba_osob = len(dane)
            uczciwa_czesc = (suma_wszystkich / liczba_osob) if liczba_osob else 0.0

            wyniki.append(ft.Container(
                padding=18, border_radius=16,
                bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.PRIMARY),
                content=ft.Column([
                    ft.Row([ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET, color=ft.Colors.PRIMARY),
                            ft.Text("Suma wydatków w miesiącu", weight="bold", color=ft.Colors.PRIMARY)], spacing=8),
                    ft.Text(f"{utils.formatuj_liczba(suma_wszystkich)} {waluta}", size=24, weight="bold"),
                    ft.Text(
                        f"Przy równym podziale między {liczba_osob} "
                        f"{'osobę' if liczba_osob == 1 else 'osoby' if 2 <= liczba_osob <= 4 else 'osób'}: "
                        f"{utils.formatuj_liczba(uczciwa_czesc)} {waluta}/os.",
                        size=12, color=ft.Colors.ON_SURFACE_VARIANT
                    )
                ], spacing=6)
            ))

            maks = max((d["razem"] for d in dane), default=0)
            for d in dane:
                proporcja = (d["razem"] / maks) if maks > 0 else 0
                roznica = d["razem"] - uczciwa_czesc
                if abs(roznica) < 0.01:
                    tekst_rozliczenia, kolor_rozliczenia = "Dokładnie tyle, ile powinien/powinna.", ft.Colors.ON_SURFACE_VARIANT
                elif roznica > 0:
                    tekst_rozliczenia = f"Dopłacił(a) {utils.formatuj_liczba(roznica)} {waluta} więcej niż uczciwa część — reszta powinna mu/jej to oddać."
                    kolor_rozliczenia = ft.Colors.GREEN_700
                else:
                    tekst_rozliczenia = f"Powinien(nna) dopłacić {utils.formatuj_liczba(abs(roznica))} {waluta}, by wyrównać."
                    kolor_rozliczenia = ft.Colors.ORANGE_700

                pary_kategorii = [
                    (utils.IKONY_KATEGORII_KOSZTOW["paliwo"], utils.formatuj_liczba(d["paliwo"], 0)) if d["paliwo"] > 0 else None,
                    (utils.IKONY_KATEGORII_KOSZTOW["serwis"], utils.formatuj_liczba(d["serwis"], 0)) if d["serwis"] > 0 else None,
                    (utils.IKONY_KATEGORII_KOSZTOW["inne"], utils.formatuj_liczba(d["inne"], 0)) if d["inne"] > 0 else None,
                ]
                opis_kategorii = utils.chipy_kwot(pary_kategorii) or ft.Text(
                    "Brak wydatków", size=12, color=ft.Colors.ON_SURFACE_VARIANT)

                wyniki.append(ft.Card(
                    elevation=1,
                    content=ft.Container(
                        padding=15, border_radius=10,
                        content=ft.Column([
                            ft.Row([
                                ft.Row([ft.Icon(ft.Icons.PERSON, color=ft.Colors.PRIMARY, size=18),
                                        ft.Text(d["osoba"], weight="bold", size=16)], spacing=6),
                                ft.Text(f"{utils.formatuj_liczba(d['razem'])} {waluta}", weight="bold", size=16, color=ft.Colors.RED_700)
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.ProgressBar(value=max(0.03, proporcja), color=ft.Colors.PRIMARY,
                                           bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE), height=8, border_radius=4),
                            opis_kategorii,
                            ft.Text(
                                f"Zatankował(a) {d['tankowania']}x • ok. {utils.formatuj_liczba(d['dystans_km'], 0)} km na liczniku"
                                if d["tankowania"] else "Brak tankowań w tym miesiącu",
                                size=12, color=ft.Colors.ON_SURFACE_VARIANT
                            ),
                            ft.Divider(height=10),
                            ft.Text(tekst_rozliczenia, size=12, weight="bold", color=kolor_rozliczenia),
                        ], spacing=8)
                    )
                ))

        info = ft.Container(
            padding=15, border_radius=10, bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.PRIMARY),
            content=ft.Row([
                ft.Icon(ft.Icons.INFO_OUTLINE, color=ft.Colors.PRIMARY, size=18),
                ft.Text(
                    "Wpisy sprzed włączenia tej funkcji trafiają pod „Nieprzypisane”. Przejechane km to "
                    "przybliżenie na podstawie tankowań — nie dokładny pomiar, kto siedział za kierownicą.",
                    size=12, color=ft.Colors.ON_SURFACE_VARIANT, expand=True
                )
            ], spacing=8)
        )

        elementy = [pasek_miesiaca, ft.Column(wyniki, spacing=15), info, utils.dol_bezpieczny(20)]

        super().__init__(
            route="/podzial", padding=15, spacing=15, appbar=appbar,
            controls=elementy, scroll=ft.ScrollMode.AUTO
        )