"""Archiwum sprzedanych pojazdów — historia po zamknięciu rachunku."""

import flet as ft
import db
import utils


class ArchiwumView(ft.View):
    """Auta, które odeszły, ale których historia została.

    Czym się różni od Kosza: kosz trzyma MIGAWKĘ usuniętego auta i istnieje po
    to, żeby cofnąć pomyłkę — danych z niego nie da się przeglądać ani
    wyeksportować, dopóki pojazd nie wróci. Archiwum trzyma auto w komplecie,
    tyle że poza garażem: historia, koszty i eksport są dostępne od ręki, bo po
    sprzedaży sięga się do nich najczęściej (rozliczenie z kupującym, gwarancja
    na wymienioną część, porównanie z następnym autem).
    """

    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state

        appbar = utils.zbuduj_pasek_z_powrotem(
            page, "Archiwum pojazdów", "/", ikona=ft.Icons.INVENTORY
        )

        super().__init__(
            route="/archiwum",
            padding=15,
            spacing=15,
            appbar=appbar,
            controls=self._zbuduj(),
            scroll=ft.ScrollMode.AUTO,
        )

    # ------------------------------------------------------------------ widok
    def _zbuduj(self):
        auta = db.pobierz_sprzedane_pojazdy()

        if not auta:
            return [utils.ekran_braku_danych(
                ikona=ft.Icons.INVENTORY,
                tytul="Archiwum jest puste",
                opis="Gdy sprzedasz auto, wybierz w menu „Sprzedaj pojazd”. Zniknie z garażu, "
                     "ale cała jego historia — tankowania, serwis, koszty — zostanie tutaj, "
                     "gotowa do przejrzenia i wyeksportowania.",
                tekst_przycisku="Wróć na start",
                on_click=lambda e: utils.przejdz(self._page, "/"),
            )]

        elementy = [
            ft.Container(
                padding=utils.SPACING["md"], border_radius=utils.RADIUS["lg"],
                bgcolor=utils.tlo_karty(self._page, poziom=1),
                content=ft.Row([
                    ft.Icon(ft.Icons.INFO_OUTLINE, size=18, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Text(
                        f"{len(auta)} {'pojazd' if len(auta) == 1 else 'pojazdy/-ów'} poza garażem. "
                        "Dane są nienaruszone — możesz je przeglądać, eksportować i w każdej chwili "
                        "przywrócić auto do garażu.",
                        size=12, color=ft.Colors.ON_SURFACE_VARIANT, expand=True,
                    ),
                ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            )
        ]
        elementy += [self._karta_auta(a) for a in auta]
        elementy.append(utils.dol_bezpieczny(10))
        return elementy

    def _miniatura(self, a):
        kolor = utils.MAPA_KOLOROW.get(a.get("kolor_motywu") or "", ft.Colors.PRIMARY)
        zastepcza = ft.Container(
            width=64, height=64, border_radius=utils.RADIUS["md"],
            bgcolor=ft.Colors.with_opacity(0.10, kolor),
            alignment=ft.Alignment.CENTER,
            content=ft.Icon(utils.ikona_nadwozia(a.get("nadwozie")), size=28,
                            color=ft.Colors.with_opacity(0.60, kolor)),
        )
        if not a.get("zdjecie_glowne"):
            return zastepcza
        return ft.Container(
            width=64, height=64, border_radius=utils.RADIUS["md"], clip_behavior=ft.ClipBehavior.HARD_EDGE,
            content=ft.Image(
                src=utils.abs_zalacznik(a["zdjecie_glowne"]),
                width=64, height=64, fit="cover", error_content=zastepcza,
            ),
        )

    def _karta_auta(self, a):
        waluta = utils.symbol_waluty()
        podpis = []
        if a.get("data_sprzedazy"):
            podpis.append(f"sprzedany {a['data_sprzedazy']}")
        if a.get("nr_rej"):
            podpis.append(str(a["nr_rej"]))

        fakty = []
        if a.get("cena_sprzedazy") is not None:
            fakty.append(("Sprzedano za", f"{utils.formatuj_liczba(a['cena_sprzedazy'])} {waluta}"))
        # Utrata wartości ma sens tylko wtedy, gdy znamy OBIE ceny — inaczej
        # pokazywalibyśmy różnicę względem szacunku, czyli liczbę bez pokrycia.
        if a.get("cena_zakupu") and a.get("cena_sprzedazy") is not None:
            strata = float(a["cena_zakupu"]) - float(a["cena_sprzedazy"])
            fakty.append(("Utrata wartości", f"{utils.formatuj_liczba(strata)} {waluta}"))
        fakty.append(("Wydatki w historii", f"{utils.formatuj_liczba(a.get('koszt_razem') or 0)} {waluta}"))
        if a.get("przebieg"):
            fakty.append(("Licznik na koniec", f"{utils.formatuj_liczba(a['przebieg'], 0)} km"))
        fakty.append(("Zachowanych wpisów", str(a.get("liczba_wpisow") or 0)))

        wiersze_faktow = [
            ft.Row([
                ft.Text(etykieta, size=12, color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                ft.Text(wartosc, size=12, weight="bold", no_wrap=True),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
            for etykieta, wartosc in fakty
        ]

        return ft.Card(elevation=1, content=ft.Container(
            padding=15,
            content=ft.Column([
                ft.Row([
                    self._miniatura(a),
                    ft.Column([
                        ft.Text(str(a["nazwa"]), weight="bold", size=16,
                                no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(" • ".join(podpis) if podpis else "brak daty sprzedaży",
                                size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT),
                    ], spacing=2, expand=True),
                    ft.IconButton(ft.Icons.MORE_VERT, icon_size=18, tooltip="Opcje pojazdu",
                                  on_click=lambda e, auto=a: self._menu(auto)),
                ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Divider(height=12),
                ft.Column(wiersze_faktow, spacing=4),
                ft.Row([
                    ft.TextButton("Otwórz historię", icon=ft.Icons.HISTORY,
                                  on_click=lambda e, auto=a: self._otworz(auto)),
                    ft.TextButton("Eksport", icon=ft.Icons.SUMMARIZE,
                                  on_click=lambda e, auto=a: self._otworz(auto, "/eksport")),
                ], alignment=ft.MainAxisAlignment.END, spacing=0),
            ], spacing=6),
        ))

    # ----------------------------------------------------------------- akcje
    def _otworz(self, a, trasa="/"):
        """Przełącza aplikację na sprzedany pojazd. Działa, bo zainicjuj_domyslne_auto
        akceptuje KAŻDE istniejące auto podstawione wprost — filtruje tylko wybór
        automatyczny. Dzięki temu nie trzeba było dublować całego ekranu historii."""
        self.state.auto_id = a["id"]
        self.state.auto_nazwa = str(a["nazwa"])
        utils.przejdz(self._page, trasa)
        utils.pokaz_komunikat(self._page, f"Podgląd archiwalnego pojazdu „{a['nazwa']}”.")

    def _menu(self, a):
        def przywroc():
            db.przywroc_pojazd_do_garazu(a["id"])
            self.state.auto_id = a["id"]
            db.zainicjuj_domyslne_auto(self.state)
            utils.przejdz(self._page, "/")
            utils.pokaz_komunikat(self._page, f"„{a['nazwa']}” wrócił do garażu.")

        def do_kosza():
            def wykonaj():
                wynik = db.usun_auto_do_kosza(a["id"])
                utils.przejdz(self._page, "/archiwum")
                utils.pokaz_komunikat_cofnij(
                    self._page, f"„{a['nazwa']}” przeniesiony do kosza.", wynik
                )
            dni = db.pobierz_dni_kosza()
            okres = f"przez {dni} dni" if dni else "bez limitu czasu"
            utils.potwierdz(
                self._page, "Przenieść do kosza?",
                f"„{a['nazwa']}” zniknie także z archiwum i trafi do kosza, gdzie poczeka {okres}. "
                "Dopóki tam leży, historii nie da się przeglądać ani eksportować.",
                wykonaj, tekst_potwierdzenia="Przenieś do kosza",
            )

        utils.pokaz_menu_kontekstowe(self._page, f"Pojazd: {a['nazwa']}", [
            {"ikona": ft.Icons.HISTORY, "tekst": "Otwórz historię",
             "akcja": lambda: self._otworz(a)},
            {"ikona": ft.Icons.SUMMARIZE, "tekst": "Eksport danych (CSV/PDF)",
             "akcja": lambda: self._otworz(a, "/eksport")},
            {"ikona": ft.Icons.BADGE, "tekst": "Karta pojazdu",
             "akcja": lambda: self._otworz(a, "/pojazd")},
            {"ikona": ft.Icons.UNARCHIVE, "tekst": "Przywróć do garażu",
             "akcja": przywroc},
            {"ikona": ft.Icons.DELETE_OUTLINE, "tekst": "Przenieś do kosza",
             "kolor": ft.Colors.RED, "akcja": do_kosza},
        ])


__all__ = [
    "ArchiwumView",
]
