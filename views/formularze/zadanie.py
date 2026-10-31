"""Formularz podzespołu (pozycji serwisowej)."""

import db
import flet as ft
import utils
from date import na_iso
from datetime import datetime


class FormularzZadanieView(ft.View):
    def __init__(self, page: ft.Page, state, z_id=None, pozycja_id=None, szkic_id=None):
        self._page = page
        self.state = state
        self.z_id = z_id
        # Przekształcenie pozycji Do zrobienia (/zadanie/nowy/do-zrobienia/<p>): nazwa z tytułu,
        # pierwsza wymiana z pozycji; bez wymiany pozycja czeka powiązana z nowym podzespołem.
        self.pozycja = db.pozycja_do_zrobienia(pozycja_id) if pozycja_id and not z_id else None
        if self.pozycja and (self.pozycja["w_wizycie"] or self.pozycja["auto_id"] != state.auto_id):
            self.pozycja = None
        wstepne = utils.pola_wymiany_z_pozycji(state, self.pozycja) if self.pozycja else {}
        # „Serwis” → „Nowy podzespół…” z kolejki „do wpisania”: pierwsza wymiana ze zdjęcia.
        self.szkic = None if self.pozycja else utils.szkic_do_formularza(state, szkic_id, z_id)
        self.trasa_powrotu = "/"
        if self.pozycja:
            self.trasa_powrotu = "/do-zrobienia/wykonane" if self.pozycja["wykonane"] else "/do-zrobienia"
        elif self.szkic:
            self.trasa_powrotu = "/do-wpisania"
            wstepne = {"nazwa": db.nazwa_podzespolu_z_tytulu(self.szkic["opis"]) if self.szkic["opis"] else "",
                       "data": self.szkic["data"], "przebieg": self.szkic["przebieg"]}

        stara_nazwa = wstepne.get("nazwa", "")
        dotyczy_opon_val = db.dotyczy_opon_z_tytulu(self.pozycja["tytul"]) if self.pozycja else False
        if z_id:
            with db.polacz_baze() as conn:
                c = conn.cursor()
                c.execute("SELECT nazwa, dotyczy_opon FROM zadania WHERE id=?", (z_id,))
                w = c.fetchone()
                if w:
                    stara_nazwa = str(w[0])
                    dotyczy_opon_val = bool(w[1])

        self.e_n = ft.TextField(label="Nazwa podzespołu", hint_text="np. Olej silnikowy", value=stara_nazwa, **utils.styl_pola(page=page))
        self.c_dotyczy_opon = ft.Checkbox(
            label="Podzespół dotyczy opon / kół (pokaże wybór sezonu przy wpisach)",
            value=dotyczy_opon_val
        )

        # Pozycja wykonana wchodzi zawsze z wymianą; z okna „Wykonano” — wymiana zaznaczona.
        wymiana_od_razu = bool(self.szkic) or (bool(self.pozycja) and (self.pozycja["wykonane"] or wstepne["z_okna"]))
        self.c_dodaj_wymiane = ft.Checkbox(
            label="Wpisz od razu wymianę — pozycja trafi do Wykonanych" if self.pozycja else "Dodaj od razu pierwszą wymianę",
            value=wymiana_od_razu)
        self.w_dodaj_wymiane = utils.pole_wyboru(self.c_dodaj_wymiane)
        self.w_dodaj_wymiane.visible = not z_id and not (self.pozycja and self.pozycja["wykonane"])

        d_val = wstepne.get("data") or datetime.now().strftime("%d.%m.%Y")
        # Licznik w km, jak w bazie; pole pokazuje go w jednostce z Ustawień.
        self.p_km = wstepne.get("przebieg") or db.pobierz_aktualny_przebieg(self.state.auto_id) or None
        p_val = db.wartosc_pola_dystansu(self.p_km)

        self.e_d = utils.pole_daty(page, "Data wymiany", d_val)
        self.e_p = ft.TextField(label=f"Przebieg przy wymianie ({utils.jednostka_dystansu()})", value=p_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))
        self.e_c = ft.TextField(label=f"Koszt usługi / części ({utils.symbol_waluty()})",
                                value=utils.liczba_do_pola(wstepne["koszt"]) if wstepne.get("koszt") else "",
                                keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))
        self.k_wykonawca, self.get_wykonawca = utils.komponent_wyboru_warsztatu(page, state, "")

        # Pliki pierwszej wymiany (paragon, faktura, zdjęcie części).
        self.pliki = utils.PolaZalacznikow(page, "historia", szkic=self.szkic, auto_id=state.auto_id)
        # Nowy podzespół nie ma jeszcze interwału, więc rodzaj bez podpowiedzi.
        self.rodzaj = utils.PoleRodzajuSerwisu(page)
        self.k_notatka = utils.pole_notatki(wstepne.get("notatka", ""), page)

        self.karta_wymiany = utils.karta_formularza(
            [self.rodzaj.kontrolka, self.e_d, self.e_p, self.e_c, self.k_wykonawca, self.pliki.kontrolka, self.k_notatka],
            "Szczegóły pierwszej wymiany", ft.Icons.BUILD, domyslnie_otwarte=True
        )
        self.karta_wymiany.visible = wymiana_od_razu

        def toggle_wymiana(e):
            self.karta_wymiany.visible = self.c_dodaj_wymiane.value
            self.karta_wymiany.update()

        self.c_dodaj_wymiane.on_change = toggle_wymiana

        self._stan_poczatkowy = self._migawka_formularza()
        appbar = utils.zbuduj_pasek_z_powrotem(page, "Edycja podzespołu" if z_id else "Nowy podzespół", self.trasa_powrotu, on_save=self.zapisz, czy_zmieniono=self._czy_zmieniono)

        k1 = utils.karta_formularza([self.e_n, utils.pole_wyboru(self.c_dotyczy_opon), self.w_dodaj_wymiane], "Śledzony podzespół", ft.Icons.HANDYMAN, domyslnie_otwarte=True, page=page)
        elementy = [k1, self.karta_wymiany, utils.przyciski_akcji(page, "Zapisz podzespół", self.zapisz, self.trasa_powrotu)]
        if self.pozycja:
            elementy.insert(0, utils.wiersz_pozycji_w_formularzu(self.pozycja, podzespol=True))
        if self.szkic:
            elementy.insert(0, utils.pasek_szkicu(page, self.szkic))

        if z_id:
            trasa = f"/zadanie/edytuj/{z_id}"
        else:
            trasa = (f"/zadanie/nowy/do-zrobienia/{self.pozycja['id']}" if self.pozycja
                     else f"/zadanie/nowy/szkic/{self.szkic['id']}" if self.szkic else "/zadanie/nowy")
        super().__init__(
            route=trasa, padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO
        )

    def _migawka_formularza(self):
        return (self.e_n.value, self.c_dotyczy_opon.value, self.c_dodaj_wymiane.value,
                self.e_d.value, self.e_p.value, self.e_c.value, self.get_wykonawca(), self.pliki.migawka(),
                self.rodzaj.migawka(), self.k_notatka.value)

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

        if not self.z_id and self.c_dodaj_wymiane.value:
            # Pole w jednostce z Ustawień, baza w km; nieruszone pole wraca bez przeliczania.
            prz = db.dystans_na_km(utils.parsuj_int(self.e_p.value, 0), calkowity=True, km_przy_otwarciu=self.p_km)
            kos = utils.parsuj_float(self.e_c.value, 0.0)
            bledy = []
            if not (self.e_p.value or "").strip() or prz < 0: bledy.append((self.e_p, "Błędny przebieg"))
            if kos < 0: bledy.append((self.e_c, "Błędny koszt"))
            if bledy: return utils.pokaz_bledy_formularza(self._page, bledy)

        with self.pliki.zapis(), db.polacz_baze() as conn:
            c = conn.cursor()
            # Porównanie po klucz_nazwy zamiast LOWER(nazwa): duplikat wykryjemy
            # też wtedy, gdy różni je emoji, spacja na końcu albo podwójna w środku.
            klucz_nowej = db.klucz_nazwy(nazwa)
            c.execute("SELECT id, nazwa FROM zadania WHERE auto_id=? AND id!=?", (self.state.auto_id, self.z_id or 0))
            if any(db.klucz_nazwy(istniejaca) == klucz_nowej for _, istniejaca in c.fetchall()):
                return utils.pokaz_bledy_formularza(self._page, [(
                    self.e_n, "Taki podzespół już jest — wybierz go z listy" if self.pozycja else "Taka nazwa już istnieje")])

            historia_id = None
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
                        "INSERT INTO historia (zadanie_id, data, data_iso, przebieg, cena, wykonawca, kategoria, rodzaj, dodane_przez) VALUES (?,?,?,?,?,?,?,?,?)",
                        (nowe_z_id, self.e_d.value, na_iso(self.e_d.value), prz, kos, wyk, kat, self.rodzaj.wartosc, db.pobierz_moje_imie())
                    )
                    historia_id = c.lastrowid
                    self.pliki.zapisz_w(conn, historia_id, self.state.auto_id)
                    # Wymiana i koniec szkicu razem albo wcale — zdjęcie ma już nowy wpis.
                    if self.szkic:
                        db.zamknij_szkic(self.szkic["id"], conn=conn)
        if historia_id:
            utils.zapisz_notatke_z_formularza("historia", historia_id, self.k_notatka.value, "")
            db.aktualizuj_najnowszy_wpis(nowe_z_id)

        komunikat = "Zapisano podzespół i wpis!"
        if self.pozycja and not self.z_id:
            if historia_id:
                z_pozycji = db.wymiana_z_do_zrobienia(self.pozycja["id"], historia_id)
                komunikat = "Zapisano podzespół z wymianą. " + (
                    "Pozycja jest w Wykonanych." if z_pozycji else "Pozycji z listy już nie było.")
            else:
                db.powiaz_pozycje_z_podzespolem(self.pozycja["id"], nowe_z_id)
                komunikat = "Zapisano podzespół. Pozycja czeka na liście, powiązana z nim."
        utils.wypchnij_w_tle(self._page, self.state.auto_id, "podzespół")
        if self.szkic:
            utils.przejdz(self._page, utils.trasa_po_zapisie_szkicu(self.state.auto_id, "/"))
            utils.pokaz_komunikat(self._page, komunikat + utils.dopisek_kolejki(self.state.auto_id))
            return
        utils.przejdz(self._page, self.trasa_powrotu)
        utils.pokaz_komunikat(self._page, komunikat)


__all__ = [
    "FormularzZadanieView",
]
