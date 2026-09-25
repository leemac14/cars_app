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

        d_val, w_val, kat_val = datetime.now().strftime("%d.%m.%Y"), "", "Letnie"
        # Licznik w km, jak w bazie; pole pokazuje go w jednostce z Ustawień.
        self.p_km = db.pobierz_aktualny_przebieg(self.state.auto_id) or None
        koszt_zrodla, robocizna_zrodla = None, None
        notatka_val = ""
        self.zalacznik_val = None  # <-- NOWE

        duplikuj_id = getattr(state, "duplikuj_zrodlo_wpis", None) if not h_id else None
        state.duplikuj_zrodlo_wpis = None  # zużywamy jednorazowo, niezależnie od wyniku

        if h_id or duplikuj_id:
            with db.polacz_baze() as conn:
                c = conn.cursor()
                c.execute("SELECT data, przebieg, cena, wykonawca, kategoria, zalacznik, notatka, koszt_robocizny FROM historia WHERE id=?", (h_id or duplikuj_id,))
                w = c.fetchone()
                if w:
                    d_val, w_val = str(w[0] or ""), str(w[3] or "")
                    self.p_km = w[1] or None
                    koszt_zrodla, robocizna_zrodla = float(w[2] or 0.0), w[7]
                    if czy_opony and w[4]: kat_val = str(w[4])
                    self.zalacznik_val = w[5]  # <-- NOWE
                    notatka_val = str(w[6] or "")
                    if duplikuj_id:
                        d_val = datetime.now().strftime("%d.%m.%Y")
                        self.zalacznik_val = None

        # Magazyn części — ta sama karta, co przy wizycie zbiorczej. Koszt zużytych
        # części dolicza się do kosztu wpisu, więc w polach kosztu stoi sama usługa:
        # od zapisanego kosztu odejmujemy to, co doliczył magazyn. Duplikat zużycia
        # nie przenosi, ale koszt źródła je zawierał — więc odejmujemy i tam.
        self.zuzycie = utils.ZuzycieMagazynu(page, self.state.auto_id, "historia", h_id)
        doliczone = 0.0
        if h_id or duplikuj_id:
            doliczone = (self.zuzycie.koszt_doliczony if h_id
                         else db.koszt_doliczony(db.pobierz_zuzycie_czesci("historia", duplikuj_id)))

        self.e_d = utils.pole_daty(page, "Data wymiany", d_val)
        self.e_p = ft.TextField(label=f"Przebieg w momencie wymiany ({utils.jednostka_dystansu()})", value=db.wartosc_pola_dystansu(self.p_km), keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))
        # Robocizna i części osobno — tak samo jak przy wizycie. Wymiana zrobiona
        # samemu to robocizna zero, a nie „bez podziału”.
        self.koszt = utils.KosztNaprawy(page, self.zuzycie, koszt_zrodla, robocizna_zrodla, doliczone,
                                        etykieta_kwoty="Koszt usługi / części")
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

        self._stan_poczatkowy = self._migawka_formularza()
        appbar = utils.zbuduj_pasek_z_powrotem(page, f"{'Edycja' if h_id else 'Nowa wymiana'}: {nazwa}", self.trasa_powrotu, on_save=self.zapisz, czy_zmieniono=self._czy_zmieniono)
        k1 = utils.karta_formularza([self.e_d, self.e_p, self.e_kat, *self.koszt.kontrolki(), self.k_wykonawca], "Informacje o serwisie", ft.Icons.BUILD, domyslnie_otwarte=True, page=page)
        k2 = utils.karta_formularza([self.k_zalacznik], "Załącznik (paragon / faktura)", ft.Icons.ATTACH_FILE)  # <-- NOWE
        k3 = utils.karta_formularza([self.k_notatka], "Notatka", ft.Icons.STICKY_NOTE_2_OUTLINED,
                                    domyslnie_otwarte=bool(notatka_val))

        elementy = [k1, k2, k3]
        karta_magazynu = self.zuzycie.karta()
        if karta_magazynu:
            elementy.append(karta_magazynu)
        elementy.append(utils.przyciski_akcji(page, "Zapisz wpis", self.zapisz, self.trasa_powrotu))

        super().__init__(
            route=f"/wpis/edytuj/{h_id}" if h_id else f"/wpis/nowy/{self.z_id}",
            padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO
        )

    def _migawka_formularza(self):
        return (
            self.e_d.value, self.e_p.value, self.koszt.migawka(), self.get_wykonawca(), self.e_kat.value,
            self.k_notatka.value, self.zuzycie.migawka(),
        )

    def _czy_zmieniono(self):
        return self._migawka_formularza() != self._stan_poczatkowy

    def zapisz(self, e):
        utils.ustaw_blad(self.e_p)
        # Pole w jednostce z Ustawień, baza w km; nieruszone pole wraca bez przeliczania.
        prz = db.dystans_na_km(utils.parsuj_int(self.e_p.value, 0), calkowity=True, km_przy_otwarciu=self.p_km)
        kos, robocizna, bledy_kosztu = self.koszt.sprawdz()
        bledy = []
        if not (self.e_p.value or "").strip() or prz < 0: bledy.append((self.e_p, "Błędny przebieg"))
        bledy += bledy_kosztu

        # Zużycie przychodzi już wycenione: koszt każdej części liczy się tu raz
        # i ten sam trafia do powiązania i do kosztu wpisu.
        nowe_uzyte, blad_magazynu = self.zuzycie.sprawdz()
        koszt_czesci = db.suma_kosztu_zuzycia(nowe_uzyte)
        koszt_razem = round(kos + koszt_czesci, 2)

        if bledy or blad_magazynu:
            self._page.update()
            if bledy:
                return utils.pokaz_bledy_formularza(self._page, bledy)
            return utils.pokaz_komunikat(self._page, "Sprawdź ilości wykorzystanych części z magazynu.", utils.KOLOR_STATUS["error"])

        if utils.sprawdz_podejrzany_przebieg(self._page, self.e_p, self.state.auto_id, prz, wyklucz_id=self.h_id, tabela="historia", nowa_data_str=self.e_d.value):
            return

        # Nowy warsztat wpisany z palca trafia do bazy dopiero PO wszystkich
        # sprawdzeniach — przy przerwanym zapisie (nietypowy przebieg,
        # a potem „Wróć”) zostawał w słowniku warsztatów bez żadnego wpisu.
        wyk = self.get_wykonawca() or "Warsztat"
        if wyk and wyk != "Warsztat":
            db.dodaj_warsztat(self.state.auto_id, wyk)

        kat = self.e_kat.value if self.e_kat.visible else None

        przygotowany = db.przygotuj_nowy_zalacznik(self.get_zalacznik())
        nowy_zalacznik = przygotowany if przygotowany is not None else self.zalacznik_val

        zdalne_id_czesci_do_nagrobka = []
        with db.polacz_baze() as conn:
            if self.h_id:
                conn.execute("UPDATE historia SET data=?, przebieg=?, cena=?, koszt_robocizny=?, wykonawca=?, kategoria=?, zalacznik=?, zmodyfikowane_przez=?, data_modyfikacji=? WHERE id=?", (self.e_d.value, prz, koszt_razem, robocizna, wyk, kat, nowy_zalacznik, db.pobierz_moje_imie(), datetime.now().strftime("%d.%m.%Y %H:%M"), self.h_id))
                historia_id = self.h_id
                # Edycja: najpierw oddajemy do magazynu to, co ten wpis zdjął
                # poprzednio, a dopiero potem potrącamy nowy zestaw. Inaczej
                # zmiana ilości z 2 na 1 zdjęłaby ze stanu kolejną sztukę.
                zdalne_id_czesci_do_nagrobka = db.przywroc_czesci_wpisu(historia_id, conn=conn)
            else:
                kursor = conn.cursor()
                kursor.execute("INSERT INTO historia (zadanie_id, data, przebieg, cena, koszt_robocizny, wykonawca, kategoria, zalacznik, dodane_przez) VALUES (?,?,?,?,?,?,?,?,?)", (self.z_id, self.e_d.value, prz, koszt_razem, robocizna, wyk, kat, nowy_zalacznik, db.pobierz_moje_imie()))
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
        if koszt_czesci > 0:
            utils.pokaz_komunikat(self._page, f"Zapisano wpis! Doliczono części z magazynu: {utils.formatuj_liczba(koszt_czesci)} {utils.symbol_waluty()}.")
        else:
            utils.pokaz_komunikat(self._page, "Zapisano wpis!")


__all__ = [
    "FormularzWpisView",
]
