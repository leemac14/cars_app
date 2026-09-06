"""Formularz interwału obsługi podzespołu."""

import db
import flet as ft
import utils


class FormularzInterwalView(ft.View):
    def __init__(self, page: ft.Page, state, z_id):
        self._page = page
        self.state = state
        self.z_id = z_id

        nazwa, ik, im = "", "", ""
        prog_km_val, prog_dni_val = "", ""
        with db.polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT nazwa, interwal_km, interwal_miesiace, prog_km, prog_dni FROM zadania WHERE id=?", (z_id,))
            w = c.fetchone()
            if w:
                nazwa, ik, im = str(w[0]), str(w[1] or ""), str(w[2] or "")
                prog_km_val, prog_dni_val = str(w[3] or ""), str(w[4] or "")

        self.e_ik = ft.TextField(label="Co ile kilometrów (np. 15000)", value=ik, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))
        self.e_im = ft.TextField(label="Co ile miesięcy (np. 12)", value=im, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))

        dozwolone_km = [str(v) for v in db.PROGI_KM_OPCJE]
        dozwolone_dni = [str(v) for v in db.PROGI_DNI_OPCJE]

        self.e_prog_km = ft.Dropdown(
            label="Ostrzegaj na ile km przed",
            options=(
                [ft.DropdownOption(key="", text=f"Domyślny z Ustawień ({db.pobierz_prog_km()} km)")]
                + [ft.DropdownOption(key=str(v), text=f"{v} km przed terminem") for v in db.PROGI_KM_OPCJE]
            ),
            value=prog_km_val if prog_km_val in dozwolone_km else "",
            **utils.styl_dropdown()
        )
        self.e_prog_dni = ft.Dropdown(
            label="Ostrzegaj na ile dni przed",
            options=(
                [ft.DropdownOption(key="", text=f"Domyślny z Ustawień ({db.pobierz_prog_dni()} dni)")]
                + [ft.DropdownOption(key=str(v), text=f"{v} dni przed terminem") for v in db.PROGI_DNI_OPCJE]
            ),
            value=prog_dni_val if prog_dni_val in dozwolone_dni else "",
            **utils.styl_dropdown()
        )

        self._stan_poczatkowy = self._migawka_formularza()
        appbar = utils.zbuduj_pasek_z_powrotem(page, f"Interwał: {nazwa}", "/", on_save=self.zapisz, czy_zmieniono=self._czy_zmieniono)
        k1 = utils.karta_formularza([self.e_ik, self.e_im], "Odstępy między wymianami", ft.Icons.TIMER, domyslnie_otwarte=True, page=page)
        k2 = utils.karta_formularza(
            [
                ft.Text(
                    "Domyślne progi z Ustawień obowiązują wszystkie podzespoły naraz. Tutaj możesz "
                    "ustawić własne okno ostrzegania tylko dla tego jednego — np. rozrząd 5000 km "
                    "wcześniej, a filtr powietrza dopiero 500 km przed terminem.",
                    size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT
                ),
                self.e_prog_km,
                self.e_prog_dni,
            ],
            "Próg ostrzeżenia dla tego podzespołu", ft.Icons.NOTIFICATIONS_ACTIVE, page=page
        )

        btn_czysc = ft.OutlinedButton("Wyczyść przypomnienia", on_click=self.usun_interwal, style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12), padding=15), width=float("inf"))

        elementy = [k1, k2, btn_czysc, utils.przyciski_akcji(page, "Zapisz interwał", self.zapisz, "/")]

        super().__init__(
            route=f"/interwal/{z_id}",
            padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO
        )

    def _migawka_formularza(self):
        return (self.e_ik.value, self.e_im.value, self.e_prog_km.value, self.e_prog_dni.value)

    def _czy_zmieniono(self):
        return self._migawka_formularza() != self._stan_poczatkowy

    def zapisz(self, e):
        utils.ustaw_blad(self.e_ik)
        utils.ustaw_blad(self.e_im)
        vk, vm = utils.parsuj_int(self.e_ik.value, None), utils.parsuj_int(self.e_im.value, None)

        if not vk and not vm:
            return utils.pokaz_bledy_formularza(self._page, [(self.e_ik, "Podaj wartość")])

        bledy = []
        if vk is not None and vk <= 0:
            bledy.append((self.e_ik, "Wartość musi być dodatnia"))
        if vm is not None and vm <= 0:
            bledy.append((self.e_im, "Wartość musi być dodatnia"))
        if bledy:
            return utils.pokaz_bledy_formularza(self._page, bledy)

        # Pusty wybór = None = korzystaj z globalnego progu z Ustawień.
        prog_km_zapis = utils.parsuj_int(self.e_prog_km.value, None) if self.e_prog_km.value else None
        prog_dni_zapis = utils.parsuj_int(self.e_prog_dni.value, None) if self.e_prog_dni.value else None

        with db.polacz_baze() as conn:
            conn.execute(
                "UPDATE zadania SET interwal_km=?, interwal_miesiace=?, prog_km=?, prog_dni=? WHERE id=?",
                (vk, vm, prog_km_zapis, prog_dni_zapis, self.z_id)
            )
        utils.wypchnij_w_tle(self._page, self.state.auto_id, "interwał")
        utils.przejdz(self._page, "/")
        utils.pokaz_komunikat(self._page, "Zapisano interwały.")

    def usun_interwal(self, e):
        with db.polacz_baze() as conn:
            conn.execute(
                "UPDATE zadania SET interwal_km=NULL, interwal_miesiace=NULL, prog_km=NULL, prog_dni=NULL WHERE id=?",
                (self.z_id,)
            )
        utils.przejdz(self._page, "/")
        utils.pokaz_komunikat(self._page, "Usunięto przypomnienie.")


__all__ = [
    "FormularzInterwalView",
]
