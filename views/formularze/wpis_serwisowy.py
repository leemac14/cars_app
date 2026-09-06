"""Formularz pojedynczego wpisu w historii serwisowej."""

import db
import flet as ft
import utils
from datetime import datetime


class FormularzWpisView(ft.View):
    def __init__(self, page: ft.Page, state, h_id=None, z_id_param=None):
        self._page = page
        self.state = state
        self.h_id = h_id
        self.z_id = z_id_param

        if h_id:
            with db.polacz_baze() as conn:
                c = conn.cursor()
                c.execute("SELECT zadanie_id FROM historia WHERE id=?", (h_id,))
                w = c.fetchone()
                self.z_id = w[0] if w else z_id_param

        nazwa = ""
        czy_opony = False
        if self.z_id:
            with db.polacz_baze() as conn:
                c = conn.cursor()
                c.execute("SELECT nazwa, dotyczy_opon FROM zadania WHERE id=?", (self.z_id,))
                w = c.fetchone()
                if w:
                    nazwa = str(w[0])
                    czy_opony = bool(w[1])
        self.trasa_powrotu = f"/historia/{self.z_id}" if self.z_id else "/"

        d_val, p_val, c_val, w_val, kat_val = datetime.now().strftime("%d.%m.%Y"), str(db.pobierz_aktualny_przebieg(self.state.auto_id) or ""), "", "", "Letnie"
        notatka_val = ""
        self.zalacznik_val = None  # <-- NOWE

        duplikuj_id = getattr(state, "duplikuj_zrodlo_wpis", None) if not h_id else None
        state.duplikuj_zrodlo_wpis = None  # zużywamy jednorazowo, niezależnie od wyniku

        if h_id or duplikuj_id:
            with db.polacz_baze() as conn:
                c = conn.cursor()
                c.execute("SELECT data, przebieg, cena, wykonawca, kategoria, zalacznik, notatka FROM historia WHERE id=?", (h_id or duplikuj_id,))
                w = c.fetchone()
                if w:
                    d_val, p_val, c_val, w_val = str(w[0] or ""), str(w[1] or ""), str(w[2] or ""), str(w[3] or "")
                    if czy_opony and w[4]: kat_val = str(w[4])
                    self.zalacznik_val = w[5]  # <-- NOWE
                    notatka_val = str(w[6] or "")
                    if duplikuj_id:
                        d_val = datetime.now().strftime("%d.%m.%Y")
                        self.zalacznik_val = None

        self.e_d = utils.pole_daty(page, "Data wymiany", d_val)
        self.e_p = ft.TextField(label="Przebieg w momencie wymiany (km)", value=p_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))
        self.e_c = ft.TextField(label=f"Koszt usługi / części ({utils.symbol_waluty()})", value=c_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))
        self.k_wykonawca, self.get_wykonawca = utils.komponent_wyboru_warsztatu(page, state, w_val)
        self.e_kat = ft.Dropdown(
            label="Rodzaj opon", 
            options=[
                ft.DropdownOption(key="Letnie", text="Letnie"), 
                ft.DropdownOption(key="Zimowe", text="Zimowe"), 
                ft.DropdownOption(key="Całoroczne", text="Całoroczne")
            ], 
            value=kat_val, 
            visible=czy_opony,
            **utils.styl_dropdown()
        )
        self.k_zalacznik, self.get_zalacznik = utils.komponent_zalacznika(page, self.zalacznik_val)  # <-- NOWE
        self.notatka_bazowa = (notatka_val or "").strip()
        self.k_notatka = utils.pole_notatki(notatka_val, page)

        # Magazyn części — dokładnie ta sama mechanika, co przy wizycie zbiorczej.
        # Wcześniej stan magazynu schodził tylko przy wizycie, więc wymiana oleju
        # zapisana jako pojedynczy wpis zostawiała butelkę „na stanie” w nieskończoność.
        poprzednio_uzyte = dict(db.pobierz_uzyte_czesci_wpisu(h_id)) if h_id else {}
        with db.polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT id, nazwa, ilosc, jednostka FROM magazyn_czesci WHERE auto_id=? ORDER BY nazwa", (self.state.auto_id,))
            wszystkie_czesci_magazynu = c.fetchall()

        self.magazyn_kontrolki = []
        wiersze_magazynu = []
        for m_id, m_nazwa, m_ilosc, m_jedn in wszystkie_czesci_magazynu:
            juz_uzyto = float(poprzednio_uzyte.get(m_id, 0) or 0)
            # Przy edycji doliczamy to, co ten wpis już zdjął ze stanu — inaczej
            # własna, wcześniej zapisana ilość wyglądałaby na niedostępną.
            dostepna = float(m_ilosc or 0) + juz_uzyto
            if dostepna <= 0:
                continue

            zaznaczone = m_id in poprzednio_uzyte
            pole_ilosc = ft.TextField(
                value=utils.formatuj_liczba(juz_uzyto, 2) if zaznaczone else "1",
                width=90, visible=zaznaczone,
                keyboard_type=ft.KeyboardType.NUMBER,
                **utils.styl_pola(page=page)
            )

            def _przelacz(e, pole=pole_ilosc):
                pole.visible = e.control.value
                pole.update()

            chk = ft.Checkbox(
                label=f"{m_nazwa} (dost.: {utils.formatuj_liczba(dostepna, 2)} {m_jedn or 'szt'})",
                value=zaznaczone, data=m_id, on_change=_przelacz
            )

            self.magazyn_kontrolki.append((chk, pole_ilosc, {"id": m_id, "dostepna": dostepna}))
            wiersze_magazynu.append(ft.Row([chk, pole_ilosc], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER))

        self.magazyn_lista_kontener = ft.Column(wiersze_magazynu, spacing=8, visible=bool(poprzednio_uzyte))

        def _przelacz_magazyn(e):
            self.magazyn_lista_kontener.visible = e.control.value
            self.magazyn_lista_kontener.update()

        self.c_uzyj_magazynu = ft.Checkbox(
            label="Wykorzystaj własne części z magazynu",
            value=bool(poprzednio_uzyte),
            on_change=_przelacz_magazyn
        )

        self._stan_poczatkowy = self._migawka_formularza()
        appbar = utils.zbuduj_pasek_z_powrotem(page, f"{'Edycja' if h_id else 'Nowa wymiana'}: {nazwa}", self.trasa_powrotu, on_save=self.zapisz, czy_zmieniono=self._czy_zmieniono)
        k1 = utils.karta_formularza([self.e_d, self.e_p, self.e_kat, self.e_c, self.k_wykonawca], "Informacje o serwisie", ft.Icons.BUILD, domyslnie_otwarte=True, page=page)
        k2 = utils.karta_formularza([self.k_zalacznik], "Załącznik (paragon / faktura)", ft.Icons.ATTACH_FILE)  # <-- NOWE
        k3 = utils.karta_formularza([self.k_notatka], "Notatka", ft.Icons.STICKY_NOTE_2_OUTLINED,
                                    domyslnie_otwarte=bool(notatka_val))

        elementy = [k1, k2, k3]
        if self.magazyn_kontrolki:
            elementy.append(utils.karta_formularza(
                [self.c_uzyj_magazynu, self.magazyn_lista_kontener],
                "Magazyn części", ft.Icons.INVENTORY_2
            ))
        elementy.append(utils.przyciski_akcji(page, "Zapisz wpis", self.zapisz, self.trasa_powrotu))

        super().__init__(
            route=f"/wpis/edytuj/{h_id}" if h_id else f"/wpis/nowy/{self.z_id}",
            padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO
        )

    def _migawka_formularza(self):
        return (
            self.e_d.value, self.e_p.value, self.e_c.value, self.get_wykonawca(), self.e_kat.value,
            self.k_notatka.value, self.c_uzyj_magazynu.value,
            tuple((chk.value, pole.value) for chk, pole, _ in self.magazyn_kontrolki),
        )

    def _czy_zmieniono(self):
        return self._migawka_formularza() != self._stan_poczatkowy

    def zapisz(self, e):
        for pole in (self.e_p, self.e_c): utils.ustaw_blad(pole)
        prz, kos = utils.parsuj_int(self.e_p.value, 0), utils.parsuj_float(self.e_c.value, 0.0)
        bledy = []
        if not (self.e_p.value or "").strip() or prz < 0: bledy.append((self.e_p, "Błędny przebieg"))
        if kos < 0: bledy.append((self.e_c, "Błędny koszt"))

        nowe_uzyte = []
        for chk, pole_ilosc, poz in self.magazyn_kontrolki:
            utils.ustaw_blad(pole_ilosc)
            if self.c_uzyj_magazynu.value and chk.value:
                ilosc = utils.parsuj_float(pole_ilosc.value, None)
                if ilosc is None or ilosc <= 0 or ilosc > poz["dostepna"] + 1e-9:
                    utils.ustaw_blad(pole_ilosc, f"Maks. {utils.formatuj_liczba(poz['dostepna'], 2)}")
                else:
                    nowe_uzyte.append((poz["id"], ilosc))
        blad_magazynu = any(utils.blad_kontrolki(pole) for _, pole, _ in self.magazyn_kontrolki)

        if bledy or blad_magazynu:
            self._page.update()
            if bledy:
                return utils.pokaz_bledy_formularza(self._page, bledy)
            return utils.pokaz_komunikat(self._page, "Sprawdź ilości wykorzystanych części z magazynu.", ft.Colors.RED_700)

        # Pobieramy wykonawcę i jeśli wpisano z palca nową nazwę, zapisujemy ją do bazy
        wyk = self.get_wykonawca() or "Warsztat"
        if wyk and wyk != "Warsztat":
            db.dodaj_warsztat(self.state.auto_id, wyk)
            
        kat = self.e_kat.value if self.e_kat.visible else None

        if utils.sprawdz_podejrzany_przebieg(self._page, self.e_p, self.state.auto_id, prz, wyklucz_id=self.h_id, tabela="historia", nowa_data_str=self.e_d.value):
            return

        przygotowany = db.przygotuj_nowy_zalacznik(self.get_zalacznik())
        nowy_zalacznik = przygotowany if przygotowany is not None else self.zalacznik_val

        zdalne_id_czesci_do_nagrobka = []
        with db.polacz_baze() as conn:
            if self.h_id:
                conn.execute("UPDATE historia SET data=?, przebieg=?, cena=?, wykonawca=?, kategoria=?, zalacznik=?, zmodyfikowane_przez=?, data_modyfikacji=? WHERE id=?", (self.e_d.value, prz, kos, wyk, kat, nowy_zalacznik, db.pobierz_moje_imie(), datetime.now().strftime("%d.%m.%Y %H:%M"), self.h_id))
                historia_id = self.h_id
                # Edycja: najpierw oddajemy do magazynu to, co ten wpis zdjął
                # poprzednio, a dopiero potem potrącamy nowy zestaw. Inaczej
                # zmiana ilości z 2 na 1 zdjęłaby ze stanu kolejną sztukę.
                zdalne_id_czesci_do_nagrobka = db.przywroc_czesci_wpisu(historia_id, conn=conn)
            else:
                kursor = conn.cursor()
                kursor.execute("INSERT INTO historia (zadanie_id, data, przebieg, cena, wykonawca, kategoria, zalacznik, dodane_przez) VALUES (?,?,?,?,?,?,?,?)", (self.z_id, self.e_d.value, prz, kos, wyk, kat, nowy_zalacznik, db.pobierz_moje_imie()))
                historia_id = kursor.lastrowid

            db.rozlicz_czesci_z_magazynu_wpisu(historia_id, nowe_uzyte, conn=conn)

        utils.zapisz_notatke_z_formularza("historia", historia_id, self.k_notatka.value, self.notatka_bazowa)
        db.zatwierdz_zalacznik(self.zalacznik_val, przygotowany)

        # Nagrobki rejestrujemy PO commicie transakcji powyżej — zarejestruj_nagrobek
        # otwiera własne połączenie do SQLite i w środku otwartej transakcji
        # mogłoby zakleszczyć bazę (ten sam powód, co w formularzu wizyty).
        for zid in zdalne_id_czesci_do_nagrobka:
            db.zarejestruj_nagrobek("historia_czesci_magazynu", zid)

        db.aktualizuj_najnowszy_wpis(self.z_id)
        utils.wypchnij_w_tle(self._page, self.state.auto_id, "wpis serwisowy")
        utils.przejdz(self._page, self.trasa_powrotu)
        utils.pokaz_komunikat(self._page, "Zapisano wpis!")


__all__ = [
    "FormularzWpisView",
]
