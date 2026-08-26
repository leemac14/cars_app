import flet as ft
from datetime import datetime, timedelta, date
import db
import utils

PRESETY_OKRESU = [
    "Cały okres",
    "Ostatnie 30 dni",
    "Ostatnie 3 miesiące",
    "Ostatnie 6 miesięcy",
    "Bieżący rok",
    "Poprzedni rok",
    "Zakres niestandardowy",
]


def _okres_z_presetu(nazwa):
    """Zwraca (od_data, do_data, opis) — obiekty date (lub None dla otwartego końca)."""
    dzis = datetime.now().date()
    if nazwa == "Ostatnie 30 dni":
        return dzis - timedelta(days=30), dzis, "Ostatnie 30 dni"
    if nazwa == "Ostatnie 3 miesiące":
        return dzis - timedelta(days=92), dzis, "Ostatnie 3 miesiące"
    if nazwa == "Ostatnie 6 miesięcy":
        return dzis - timedelta(days=183), dzis, "Ostatnie 6 miesięcy"
    if nazwa == "Bieżący rok":
        return date(dzis.year, 1, 1), dzis, f"Rok {dzis.year}"
    if nazwa == "Poprzedni rok":
        rok = dzis.year - 1
        return date(rok, 1, 1), date(rok, 12, 31), f"Rok {rok}"
    return None, None, "Cały dostępny okres"


class EksportView(ft.View):
    def __init__(self, page: ft.Page, state, cb_eksportuj):
        self._page = page
        self.state = state
        self.cb_eksportuj = cb_eksportuj

        appbar = utils.zbuduj_pasek_z_powrotem(page, "📤 Eksport danych", "/")

        if not self.state.auto_id:
            super().__init__(
                route="/eksport", padding=15, spacing=15, appbar=appbar,
                controls=[utils.ekran_braku_danych(
                    ikona=ft.Icons.DIRECTIONS_CAR,
                    tytul="Brak wybranego pojazdu",
                    opis="Dodaj lub wybierz pojazd, aby móc wyeksportować jego dane.",
                    tekst_przycisku="Wróć na start",
                    on_click=lambda e: utils.przejdz(self._page, "/")
                )]
            )
            return

        # --- Zakres dat ---
        self.e_okres = ft.Dropdown(
            label="Okres",
            options=[ft.DropdownOption(o) for o in PRESETY_OKRESU],
            value=PRESETY_OKRESU[0],
            **utils.styl_dropdown()
        )
        self.e_od = utils.pole_daty(page, "Od (włącznie)")
        self.e_do = utils.pole_daty(page, "Do (włącznie)")
        self.wiersz_niestandardowy = ft.Row(
            [ft.Container(self.e_od, expand=True), ft.Container(self.e_do, expand=True)],
            spacing=10, visible=False
        )

        def zmien_okres(e):
            self.wiersz_niestandardowy.visible = (self.e_okres.value == "Zakres niestandardowy")
            self.wiersz_niestandardowy.update()

        self.e_okres.on_change = zmien_okres

        # --- Kategorie danych ---
        self.checkboxy_kategorii = [
            ft.Checkbox(label=etykieta, value=True, data=klucz)
            for klucz, etykieta in db.KATEGORIE_EKSPORTU.items()
        ]

        def zaznacz_wszystkie(e):
            for chk in self.checkboxy_kategorii: chk.value = True
            self._page.update()

        def odznacz_wszystkie(e):
            for chk in self.checkboxy_kategorii: chk.value = False
            self._page.update()

        wiersz_szybkie = ft.Row([
            ft.TextButton("Zaznacz wszystko", on_click=zaznacz_wszystkie),
            ft.TextButton("Odznacz wszystko", on_click=odznacz_wszystkie),
        ], spacing=4)

        self.blad_kategorii = ft.Text("", color=ft.Colors.RED_700, size=13)

        # --- Format ---
        pdf_dostepny = db.FPDF is not None
        self.e_format = ft.RadioGroup(
            content=ft.Row([
                ft.Radio(value="csv", label="📄 CSV (arkusz kalkulacyjny)"),
                ft.Radio(value="pdf", label="📕 PDF (czytelny raport)", disabled=not pdf_dostepny),
            ], wrap=True, spacing=15),
            value="pdf" if pdf_dostepny else "csv"
        )
        self.c_podsumowanie = ft.Checkbox(label="Dołącz podsumowanie kosztów (tylko PDF)", value=True)
        self.c_paszport = ft.Checkbox(
            label="Dołącz pełny paszport pojazdu — zdjęcie, specyfikacja, wykres przebiegu, zdjęcia karoserii (tylko PDF)",
            value=False
        )

        k1 = utils.karta_formularza(
            [self.e_okres, self.wiersz_niestandardowy],
            "Zakres dat", ft.Icons.DATE_RANGE, domyslnie_otwarte=True
        )
        k2 = utils.karta_formularza(
            [ft.Text("Zaznacz, co ma się znaleźć w eksporcie:", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
             wiersz_szybkie] + self.checkboxy_kategorii + [self.blad_kategorii],
            "Dane do uwzględnienia", ft.Icons.CHECKLIST, domyslnie_otwarte=True
        )
        elementy_k3 = [self.e_format, self.c_podsumowanie, self.c_paszport]
        if not pdf_dostepny:
            elementy_k3.append(ft.Text(
                "Aby włączyć eksport do PDF, doinstaluj bibliotekę: pip install fpdf2",
                size=11, italic=True, color=ft.Colors.ORANGE_700
            ))
        k3 = utils.karta_formularza(elementy_k3, "Format eksportu", ft.Icons.DESCRIPTION, domyslnie_otwarte=True)

        info = ft.Container(
            padding=15, border_radius=10, bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.PRIMARY),
            content=ft.Row([
                ft.Icon(ft.Icons.INFO_OUTLINE, color=ft.Colors.PRIMARY, size=18),
                ft.Text(
                    "Magazyn, zestawy opon i lista Do zrobienia eksportują się jako aktualny stan, "
                    "niezależnie od wybranego zakresu dat.",
                    size=12, color=ft.Colors.ON_SURFACE_VARIANT, expand=True
                )
            ], spacing=8)
        )

        self.btn_eksportuj = ft.ElevatedButton(
            "📤 Eksportuj",
            on_click=self.eksportuj,
            bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12), padding=15),
            width=float("inf")
        )

        elementy = [k1, k2, k3, info, ft.Container(height=10), self.btn_eksportuj, utils.dol_bezpieczny(30)]

        super().__init__(
            route="/eksport", padding=15, spacing=15, appbar=appbar,
            controls=elementy, scroll=ft.ScrollMode.AUTO
        )

    def eksportuj(self, e):
        wybrane = [chk.data for chk in self.checkboxy_kategorii if chk.value]
        if not wybrane:
            self.blad_kategorii.value = "Zaznacz co najmniej jedną kategorię danych."
            self._page.update()
            return
        self.blad_kategorii.value = ""

        if self.e_okres.value == "Zakres niestandardowy":
            od_txt = (self.e_od.value or "").strip()
            do_txt = (self.e_do.value or "").strip()
            od_d = utils.parsuj_date(od_txt) if od_txt else None
            do_d = utils.parsuj_date(do_txt) if do_txt else None
            if od_d == datetime.min.date(): od_d = None
            if do_d == datetime.min.date(): do_d = None
            if od_d and do_d and od_d > do_d:
                utils.pokaz_komunikat(self._page, "Data 'Od' nie może być późniejsza niż 'Do'.", ft.Colors.RED_700)
                return
            opis_okresu = f"{od_txt or 'początek'} – {do_txt or 'dziś'}"
        else:
            od_d, do_d, opis_okresu = _okres_z_presetu(self.e_okres.value)

        self.btn_eksportuj.disabled = True
        self.btn_eksportuj.text = "⏳ Przygotowywanie..."
        self._page.update()

        self._page.run_task(
            self.cb_eksportuj,
            self.state.auto_id, self.state.auto_nazwa, wybrane, od_d, do_d, opis_okresu,
            self.e_format.value, self.c_podsumowanie.value, self.c_paszport.value,
            self._po_zakonczeniu
        )

    def _po_zakonczeniu(self):
        self.btn_eksportuj.disabled = False
        self.btn_eksportuj.text = "📤 Eksportuj"
        try:
            self._page.update()
        except Exception:
            pass