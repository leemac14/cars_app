"""Formularz interwału obsługi podzespołu."""

import db
import flet as ft
import utils


class FormularzInterwalView(ft.View):
    def __init__(self, page: ft.Page, state, z_id):
        self._page = page
        self.state = state
        self.z_id = z_id

        nazwa, im = "", ""
        prog_km_val, prog_dni_val = "", ""
        # Interwał i próg w km, jak w bazie; pole i lista — w jednostce z Ustawień.
        self.ik_km = None
        j = utils.jednostka_dystansu()
        with db.polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT nazwa, interwal_km, interwal_miesiace, prog_km, prog_dni FROM zadania WHERE id=?", (z_id,))
            w = c.fetchone()
            if w:
                nazwa, im = str(w[0]), str(w[2] or "")
                self.ik_km = w[1] or None
                prog_km_val, prog_dni_val = str(w[3] or ""), str(w[4] or "")

        self.e_ik = ft.TextField(label=f"Co ile {db.slowo_dystansu('dopelniacz_pelny', j)} "
                                       f"(np. {15000 if j == 'km' else 10000})",
                                 value=db.wartosc_pola_dystansu(self.ik_km, j), keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))
        self.e_im = ft.TextField(label="Co ile miesięcy (np. 12)", value=im, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))

        # Własny próg spoza listy zostaje na niej jako dodatkowa opcja — zapis
        # formularza nie może go po cichu zamienić na domyślny.
        opcje_km = db.opcje_progow_km(j, obecny_km=prog_km_val or None)
        przyklady = db.opcje_progow_km(j)
        dozwolone_dni = [str(v) for v in db.PROGI_DNI_OPCJE]

        self.e_prog_km = ft.Dropdown(
            label=f"Ostrzegaj na ile {db.slowo_dystansu('dopelniacz', j)} przed",
            options=(
                [ft.DropdownOption(key="", text=f"Domyślny z Ustawień ({db.tekst_dystansu(db.pobierz_prog_km(), 0, j)})")]
                + [ft.DropdownOption(key=str(km), text=f"{tekst} przed terminem") for km, tekst in opcje_km]
            ),
            value=prog_km_val,
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
                    "ustawić własne okno ostrzegania tylko dla tego jednego — np. rozrząd "
                    f"{przyklady[-1][1]} wcześniej, a filtr powietrza dopiero {przyklady[0][1]} przed terminem.",
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

        # Pole w jednostce z Ustawień, baza w km; nieruszone wraca bez przeliczania.
        vk = db.dystans_na_km(vk, calkowity=True, km_przy_otwarciu=self.ik_km) if vk else vk
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
