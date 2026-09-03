import flet as ft
import db
import utils


ETYKIETY_RETENCJI = {
    7: "7 dni",
    30: "30 dni",
    90: "90 dni",
    0: "bez limitu",
}


def _formatuj_rozmiar(bajty):
    """Rozmiar zdjęć zalegających w koszu — po to, żeby było widać, kiedy kosz
    zaczyna realnie zajmować miejsce na dysku."""
    bajty = int(bajty or 0)
    if bajty <= 0:
        return None
    if bajty < 1024 * 1024:
        return f"{bajty / 1024:.0f} KB"
    return f"{bajty / (1024 * 1024):.1f} MB"


class KoszView(ft.View):
    """Pojazdy usunięte, ale jeszcze nie skasowane. Do momentu trwałego usunięcia
    z tego ekranu (albo wygaśnięcia retencji) auto istnieje w całości: historia,
    tankowania, magazyn, zdjęcia — i wraca jednym kliknięciem."""

    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state

        appbar = utils.zbuduj_pasek_z_powrotem(
            page, "Kosz", "/", ikona=ft.Icons.DELETE_SWEEP,
            akcje_dodatkowe=[
                ft.IconButton(
                    icon=ft.Icons.DELETE_FOREVER,
                    icon_color=ft.Colors.RED_700,
                    tooltip="Opróżnij kosz",
                    on_click=self._oproznij,
                )
            ]
        )

        super().__init__(
            route="/kosz",
            padding=15,
            spacing=15,
            appbar=appbar,
            controls=self._zbuduj(),
            scroll=ft.ScrollMode.AUTO,
        )

    # ------------------------------------------------------------------ widok
    def _zbuduj(self):
        pozycje = db.pobierz_kosz()
        dni = db.pobierz_dni_kosza()
        elementy = [self._karta_informacyjna(dni, pozycje)]

        if not pozycje:
            elementy.append(
                ft.Container(
                    padding=30,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Column([
                        ft.Icon(ft.Icons.DELETE_OUTLINE, size=44, color=ft.Colors.ON_SURFACE_VARIANT),
                        ft.Text("Kosz jest pusty", weight="bold", size=15),
                        ft.Text(
                            "Usunięte pojazdy trafiają tutaj razem z całą historią i zdjęciami.",
                            size=12, color=ft.Colors.ON_SURFACE_VARIANT,
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
                )
            )
        else:
            for pozycja in pozycje:
                elementy.append(self._karta_pojazdu(pozycja))

        elementy.append(utils.dol_bezpieczny(10))
        return elementy

    def _karta_informacyjna(self, dni, pozycje):
        if dni:
            tresc = (
                f"Usunięte pojazdy czekają tutaj {ETYKIETY_RETENCJI.get(dni, f'{dni} dni')}, "
                "a potem znikają razem ze zdjęciami. Czas zmienisz w Ustawieniach."
            )
        else:
            tresc = (
                "Retencja jest wyłączona — pojazdy leżą w koszu bez limitu czasu i znikną "
                "dopiero, gdy sam je stąd usuniesz. Czas zmienisz w Ustawieniach."
            )

        laczny_rozmiar = _formatuj_rozmiar(sum(p["rozmiar_plikow"] for p in pozycje))
        if laczny_rozmiar:
            tresc += f" Zdjęcia w koszu zajmują {laczny_rozmiar}."

        return ft.Container(
            padding=15,
            border_radius=utils.RADIUS["md"],
            bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.PRIMARY),
            content=ft.Row([
                ft.Icon(ft.Icons.INFO_OUTLINE, color=ft.Colors.PRIMARY, size=18),
                ft.Text(tresc, size=12, color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
            ], spacing=8)
        )

    def _karta_pojazdu(self, pozycja):
        powierzchnia = utils.powierzchnia_karty(self._page, "md")

        opis = [f"Usunięto {pozycja['data_tekst']}"]
        if pozycja["liczba_wpisow"]:
            opis.append(f"{pozycja['liczba_wpisow']} wpisów")
        rozmiar = _formatuj_rozmiar(pozycja["rozmiar_plikow"])
        if rozmiar:
            opis.append(rozmiar)

        # Odliczanie pokazujemy tylko przy włączonej retencji; ostatnie 3 dni na
        # czerwono, żeby "zniknie jutro" nie przeszło niezauważone.
        dni = pozycja["dni_do_usuniecia"]
        odznaka = None
        if dni is not None:
            if dni <= 0:
                tekst, kolor = "Zniknie przy najbliższym starcie", ft.Colors.RED_700
            elif dni == 1:
                tekst, kolor = "Zniknie jutro", ft.Colors.RED_700
            elif dni <= 3:
                tekst, kolor = f"Zniknie za {dni} dni", ft.Colors.RED_700
            else:
                tekst, kolor = f"Zniknie za {dni} dni", ft.Colors.ORANGE_800
            odznaka = ft.Container(
                padding=ft.Padding(8, 3, 8, 3),
                border_radius=utils.RADIUS["pill"],
                bgcolor=ft.Colors.with_opacity(0.15, kolor),
                content=ft.Text(tekst, size=10, weight="bold", color=kolor),
            )

        naglowek = ft.Row([
            ft.Container(
                content=ft.Icon(ft.Icons.DIRECTIONS_CAR, size=20, color=ft.Colors.ON_SURFACE_VARIANT),
                bgcolor=ft.Colors.with_opacity(0.10, ft.Colors.ON_SURFACE),
                border_radius=utils.RADIUS["sm"],
                padding=8,
            ),
            ft.Column([
                ft.Text(pozycja["nazwa"], weight="bold", size=15, no_wrap=True,
                        overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text("  •  ".join(opis), size=11, color=ft.Colors.ON_SURFACE_VARIANT),
            ], spacing=2, expand=True),
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        przyciski = ft.Row([
            ft.ElevatedButton(
                "Przywróć",
                icon=ft.Icons.RESTORE_FROM_TRASH,
                bgcolor=ft.Colors.PRIMARY,
                color=ft.Colors.ON_PRIMARY,
                on_click=lambda e, p=pozycja: self._przywroc(p),
            ),
            ft.TextButton(
                "Usuń trwale",
                icon=ft.Icons.DELETE_FOREVER,
                style=ft.ButtonStyle(color=ft.Colors.RED_700),
                on_click=lambda e, p=pozycja: self._usun_trwale(p),
            ),
        ], spacing=8, alignment=ft.MainAxisAlignment.END, wrap=True)

        zawartosc = [naglowek]
        if odznaka:
            zawartosc.append(ft.Row([odznaka]))
        zawartosc.append(przyciski)

        return ft.Container(
            padding=15,
            border_radius=utils.RADIUS["lg"],
            bgcolor=powierzchnia["bgcolor"],
            shadow=powierzchnia["shadow"],
            border=powierzchnia["border"],
            content=ft.Column(zawartosc, spacing=10),
        )

    # ------------------------------------------------------------------ akcje
    def _przywroc(self, pozycja):
        nowe_id = db.przywroc_auto_z_kosza(pozycja["id"])
        if not nowe_id:
            utils.pokaz_komunikat(self._page, "Nie udało się przywrócić pojazdu.", ft.Colors.RED_700)
            utils.przejdz(self._page, "/kosz")
            return

        # Przywrócone auto od razu staje się aktywne — użytkownik wraca po nie,
        # więc oczekuje, że po przywróceniu na nie patrzy.
        self.state.auto_id = nowe_id
        db.zainicjuj_domyslne_auto(self.state)
        utils.przejdz(self._page, "/")
        utils.pokaz_komunikat(
            self._page,
            f"Przywrócono pojazd „{self.state.auto_nazwa}” wraz z historią.",
            ft.Colors.GREEN_700,
        )

    def _usun_trwale(self, pozycja):
        def wykonaj():
            db.usun_z_kosza_trwale(pozycja["id"])
            utils.przejdz(self._page, "/kosz")
            utils.pokaz_komunikat(
                self._page, f"Pojazd „{pozycja['nazwa']}” usunięty bezpowrotnie.", ft.Colors.RED_700
            )

        utils.potwierdz(
            self._page,
            "Usunąć bezpowrotnie?",
            f"„{pozycja['nazwa']}” zniknie na dobre razem z historią i zdjęciami. "
            "Tego już nie da się cofnąć.",
            wykonaj,
            tekst_potwierdzenia="Usuń trwale",
        )

    def _oproznij(self, e):
        pozycje = db.pobierz_kosz()
        if not pozycje:
            utils.pokaz_komunikat(self._page, "Kosz jest już pusty.", ft.Colors.ON_SURFACE_VARIANT)
            return

        def wykonaj():
            ile = db.oproznij_kosz()
            utils.przejdz(self._page, "/kosz")
            utils.pokaz_komunikat(
                self._page,
                f"Opróżniono kosz — usunięto {ile} {'pojazd' if ile == 1 else 'pojazdy/pojazdów'}.",
                ft.Colors.RED_700,
            )

        utils.potwierdz(
            self._page,
            "Opróżnić kosz?",
            f"Wszystkie pojazdy w koszu ({len(pozycje)}) znikną na dobre razem z historią "
            "i zdjęciami. Tego już nie da się cofnąć.",
            wykonaj,
            tekst_potwierdzenia="Opróżnij",
        )
