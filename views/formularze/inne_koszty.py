"""Formularz pozostałych kosztów."""

import db
import flet as ft
import utils
from datetime import datetime


class FormularzInneView(ft.View):
    def __init__(self, page: ft.Page, state, i_id=None):
        self._page = page
        self.state = state
        self.i_id = i_id

        duplikuj_id = getattr(state, "duplikuj_zrodlo_koszt", None) if not i_id else None
        state.duplikuj_zrodlo_koszt = None  # zużywamy jednorazowo
        zrodlo_id = i_id or duplikuj_id

        d_val, op_val, kw_val, tagi_val = datetime.now().strftime("%d.%m.%Y"), "", "", ""
        notatka_val = ""
        kat_val = db.KATEGORIA_INNE_DOMYSLNA
        self.zalacznik_val = None
        if zrodlo_id:
            with db.polacz_baze() as conn:
                c = conn.cursor()
                c.execute("SELECT data, kategoria, nazwa, kwota, tagi, zalacznik, notatka FROM inne_koszty WHERE id=?", (zrodlo_id,))
                w = c.fetchone()
                if w: 
                    d_val, op_val, kw_val = str(w[0] or ""), str(w[2] or ""), str(w[3] or "")
                    # Do niedawna kolumna `kategoria` służyła jako pierwsza wersja
                    # tagów i nowe wpisy zapisywały w niej pusty łańcuch, a etykiety
                    # szły do `tagi`. Wpisy sprzed tej zmiany mają tam własny tekst,
                    # więc czytamy go jako kategorię — pusty zamieniamy na „Ogólne”.
                    kat_val = db.etykieta_kategorii_innych(w[1])
                    tagi_val = str(w[4] or "")
                    self.zalacznik_val = w[5]
                    notatka_val = str(w[6] or "")
                    if duplikuj_id:
                        d_val = datetime.now().strftime("%d.%m.%Y")
                        self.zalacznik_val = None

        # Kategoria opisuje RODZAJ wydatku (winieta, myjnia, polisa), tagi —
        # cokolwiek innego, co użytkownik chce po sobie znaleźć. To dwie różne
        # rzeczy i dlatego mają dwa różne pola. Wartość spoza słownika (import
        # CSV, stary wpis) dokładamy do listy, żeby edycja jej nie skasowała.
        kategorie = list(db.KATEGORIE_INNYCH_KOSZTOW)
        if kat_val not in kategorie:
            kategorie.append(kat_val)
        self.e_kat = ft.Dropdown(
            label="Kategoria",
            options=[
                ft.DropdownOption(key=k, text=k, leading_icon=utils.ikona_kategorii_innych(k))
                for k in kategorie
            ],
            value=kat_val, **utils.styl_dropdown()
        )

        self.e_d = utils.pole_daty(page, "Data", d_val)
        
        self.k_tagi, self.get_tagi = utils.komponent_tagow(page, state, tagi_val)
        
        self.e_o = ft.TextField(label="Opis / Nazwa usługi", value=op_val, **utils.styl_pola(page=page))
        self.e_kw = ft.TextField(label=f"Kwota całkowita ({utils.symbol_waluty()})", value=kw_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))
        self.k_zalacznik, self.get_zalacznik = utils.komponent_zalacznika(page, self.zalacznik_val)
        self.notatka_bazowa = (notatka_val or "").strip()
        self.k_notatka = utils.pole_notatki(notatka_val, page)

        self._stan_poczatkowy = self._migawka_formularza()
        appbar = utils.zbuduj_pasek_z_powrotem(page, "Edycja kosztu" if i_id else "Nowy koszt", "/", on_save=self.zapisz, czy_zmieniono=self._czy_zmieniono)
        k1 = utils.karta_formularza(
            [self.e_d, self.e_kat, ft.Text("Przypisane tagi:", size=13, weight="bold"), self.k_tagi, self.e_o, self.e_kw],
            "Szczegóły wydatku", ft.Icons.RECEIPT_LONG, domyslnie_otwarte=True, page=page
        )
        k2 = utils.karta_formularza([self.k_zalacznik], "Załącznik", ft.Icons.ATTACH_FILE)
        k3 = utils.karta_formularza([self.k_notatka], "Notatka", ft.Icons.STICKY_NOTE_2_OUTLINED,
                                    domyslnie_otwarte=bool(notatka_val))
        elementy = [k1, k2, k3, utils.przyciski_akcji(page, "Zapisz koszt", self.zapisz, "/")]

        super().__init__(
            route=f"/inne/edytuj/{i_id}" if i_id else "/inne/nowy",
            padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO
        )

    def _migawka_formularza(self):
        return (self.e_d.value, self.e_kat.value, self.get_tagi(), self.e_o.value, self.e_kw.value, self.k_notatka.value)

    def _czy_zmieniono(self):
        return self._migawka_formularza() != self._stan_poczatkowy

    def zapisz(self, e):
        for pole in (self.e_o, self.e_kw): utils.ustaw_blad(pole)
        opis, kwo = (self.e_o.value or "").strip(), utils.parsuj_float(self.e_kw.value, 0.0)
        bledy = []
        if not opis: bledy.append((self.e_o, "Podaj opis"))
        if kwo <= 0: bledy.append((self.e_kw, "Podaj kwotę"))
        if bledy: return utils.pokaz_bledy_formularza(self._page, bledy)

        if utils.sprawdz_duplikat_kosztu(self._page, self.e_kw, self.state.auto_id, self.e_d.value, opis, kwo, wyklucz_id=self.i_id):
            return

        wybrane_tagi = self.get_tagi()
        kategoria = db.etykieta_kategorii_innych(self.e_kat.value)
        przygotowany = db.przygotuj_nowy_zalacznik(self.get_zalacznik())
        nowy_zalacznik = przygotowany if przygotowany is not None else self.zalacznik_val

        with db.polacz_baze() as conn:
            if self.i_id: 
                conn.execute(
                    "UPDATE inne_koszty SET data=?, kategoria=?, nazwa=?, kwota=?, tagi=?, zalacznik=?, zmodyfikowane_przez=?, data_modyfikacji=? WHERE id=?",
                    (self.e_d.value, kategoria, opis, kwo, wybrane_tagi, nowy_zalacznik, db.pobierz_moje_imie(), datetime.now().strftime("%d.%m.%Y %H:%M"), self.i_id)
                )
                rekord_id = self.i_id
            else: 
                kursor = conn.execute(
                    "INSERT INTO inne_koszty (auto_id, data, kategoria, nazwa, kwota, tagi, zalacznik, dodane_przez) VALUES (?,?,?,?,?,?,?,?)",
                    (self.state.auto_id, self.e_d.value, kategoria, opis, kwo, wybrane_tagi, nowy_zalacznik, db.pobierz_moje_imie())
                )
                rekord_id = kursor.lastrowid

        utils.zapisz_notatke_z_formularza("inne_koszty", rekord_id, self.k_notatka.value, self.notatka_bazowa)
        db.zatwierdz_zalacznik(self.zalacznik_val, przygotowany)

        utils.wypchnij_w_tle(self._page, self.state.auto_id, "inny koszt")

        utils.przejdz(self._page, "/")
        utils.pokaz_komunikat(self._page, f"Zapisano koszt • {kategoria}")


__all__ = [
    "FormularzInneView",
]
