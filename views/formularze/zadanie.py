"""Formularz podzespołu (pozycji serwisowej)."""

import db
import flet as ft
import utils
from datetime import datetime


class FormularzZadanieView(ft.View):
    def __init__(self, page: ft.Page, state, z_id=None):
        self._page = page
        self.state = state
        self.z_id = z_id

        stara_nazwa = ""
        dotyczy_opon_val = False
        if z_id:
            with db.polacz_baze() as conn:
                c = conn.cursor()
                c.execute("SELECT nazwa, dotyczy_opon FROM zadania WHERE id=?", (z_id,))
                w = c.fetchone()
                if w:
                    stara_nazwa = str(w[0])
                    dotyczy_opon_val = bool(w[1])

        self.e_n = ft.TextField(label="Nazwa (np. Olej silnikowy, Tarcze przód)", value=stara_nazwa, **utils.styl_pola(page=page))
        self.c_dotyczy_opon = ft.Checkbox(
            label="Podzespół dotyczy opon / kół (pokaże wybór sezonu przy wpisach)",
            value=dotyczy_opon_val
        )

        self.c_dodaj_wymiane = ft.Checkbox(label="Dodaj od razu pierwszą wymianę", value=False, visible=not bool(z_id))
        
        d_val = datetime.now().strftime("%d.%m.%Y")
        p_val = str(db.pobierz_aktualny_przebieg(self.state.auto_id) or "")
        
        self.e_d = utils.pole_daty(page, "Data wymiany", d_val)
        self.e_p = ft.TextField(label="Przebieg w momencie wymiany (km)", value=p_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))
        self.e_c = ft.TextField(label=f"Koszt usługi / części ({utils.symbol_waluty()})", value="", keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))
        self.k_wykonawca, self.get_wykonawca = utils.komponent_wyboru_warsztatu(page, state, "")
        
        # --- DODANE: Obsługa zdjęcia przy pierwszej wymianie ---
        self.k_zalacznik, self.get_zalacznik = utils.komponent_zalacznika(page, None)

        self.karta_wymiany = utils.karta_formularza(
            [self.e_d, self.e_p, self.e_c, self.k_wykonawca, self.k_zalacznik], 
            "Szczegóły pierwszej wymiany", ft.Icons.BUILD, domyslnie_otwarte=True
        )
        self.karta_wymiany.visible = False

        def toggle_wymiana(e):
            self.karta_wymiany.visible = self.c_dodaj_wymiane.value
            self.karta_wymiany.update()

        self.c_dodaj_wymiane.on_change = toggle_wymiana

        self._stan_poczatkowy = self._migawka_formularza()
        appbar = utils.zbuduj_pasek_z_powrotem(page, "Edycja podzespołu" if z_id else "Nowy podzespół", "/", on_save=self.zapisz, czy_zmieniono=self._czy_zmieniono)
        
        k1 = utils.karta_formularza([self.e_n, self.c_dotyczy_opon, self.c_dodaj_wymiane], "Śledzony podzespół", ft.Icons.HANDYMAN, domyslnie_otwarte=True, page=page)
        elementy = [k1, self.karta_wymiany, utils.przyciski_akcji(page, "Zapisz podzespół", self.zapisz, "/")]

        super().__init__(
            route=f"/zadanie/edytuj/{z_id}" if z_id else "/zadanie/nowy",
            padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO
        )

    def _migawka_formularza(self):
        return (self.e_n.value, self.c_dotyczy_opon.value, self.c_dodaj_wymiane.value,
                self.e_d.value, self.e_p.value, self.e_c.value, self.get_wykonawca())

    def _czy_zmieniono(self):
        return self._migawka_formularza() != self._stan_poczatkowy

    def zapisz(self, e):
        utils.ustaw_blad(self.e_p)
        utils.ustaw_blad(self.e_c)
        nazwa = db.normalizuj_nazwe(self.e_n.value)
        if not nazwa: return utils.pokaz_bledy_formularza(self._page, [(self.e_n, "Podaj nazwę")])

        dotyczy_opon = 1 if self.c_dotyczy_opon.value else 0

        prz = 0
        kos = 0.0
        nowy_zalacznik = None
        przygotowany = None
        
        if not self.z_id and self.c_dodaj_wymiane.value:
            prz = utils.parsuj_int(self.e_p.value, 0)
            kos = utils.parsuj_float(self.e_c.value, 0.0)
            bledy = []
            if not (self.e_p.value or "").strip() or prz < 0: bledy.append((self.e_p, "Błędny przebieg"))
            if kos < 0: bledy.append((self.e_c, "Błędny koszt"))
            if bledy: return utils.pokaz_bledy_formularza(self._page, bledy)
            
            przygotowany = db.przygotuj_nowy_zalacznik(self.get_zalacznik())
            nowy_zalacznik = przygotowany or None

        with db.polacz_baze() as conn:
            c = conn.cursor()
            # Porównanie po klucz_nazwy zamiast LOWER(nazwa): duplikat wykryjemy
            # też wtedy, gdy różni je emoji, spacja na końcu albo podwójna w środku.
            klucz_nowej = db.klucz_nazwy(nazwa)
            c.execute("SELECT id, nazwa FROM zadania WHERE auto_id=? AND id!=?", (self.state.auto_id, self.z_id or 0))
            if any(db.klucz_nazwy(istniejaca) == klucz_nowej for _, istniejaca in c.fetchall()):
                db.anuluj_nowy_zalacznik(przygotowany)
                return utils.pokaz_bledy_formularza(self._page, [(self.e_n, "Taka nazwa już istnieje")])
            
            if self.z_id: 
                conn.execute("UPDATE zadania SET nazwa=?, dotyczy_opon=? WHERE id=?", (nazwa, dotyczy_opon, self.z_id))
            else: 
                c.execute("INSERT INTO zadania (auto_id, nazwa, dotyczy_opon) VALUES (?,?,?)", (self.state.auto_id, nazwa, dotyczy_opon))
                nowe_z_id = c.lastrowid
                
                if self.c_dodaj_wymiane.value:
                    # ZAPIS NOWEGO WARSZTATU
                    wyk = self.get_wykonawca() or "Warsztat"
                    if wyk and wyk != "Warsztat":
                        db.dodaj_warsztat(self.state.auto_id, wyk)
                        
                    kat = "Letnie" if self.c_dotyczy_opon.value else None
                    c.execute(
                        "INSERT INTO historia (zadanie_id, data, przebieg, cena, wykonawca, kategoria, zalacznik, dodane_przez) VALUES (?,?,?,?,?,?,?,?)", 
                        (nowe_z_id, self.e_d.value, prz, kos, wyk, kat, nowy_zalacznik, db.pobierz_moje_imie())
                    )
        if not self.z_id and self.c_dodaj_wymiane.value:
            db.aktualizuj_najnowszy_wpis(nowe_z_id)

        utils.wypchnij_w_tle(self._page, self.state.auto_id, "podzespół")
        utils.przejdz(self._page, "/")
        utils.pokaz_komunikat(self._page, "Zapisano podzespół i wpis!")


__all__ = [
    "FormularzZadanieView",
]
