"""Formularz pojedynczego wpisu w historii serwisowej."""

import db
import flet as ft
import utils
from date import na_iso
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
        # Gwarancja naprawy: przy edycji ta zapisana, przy duplikacie — ten sam
        # OKRES od dzisiejszej wymiany (db.przesun_gwarancje), nie stara data.
        gwarancja = {"koniec": None, "limit_km": None, "miesiace": None, "dystans_km": None}

        duplikuj_id = getattr(state, "duplikuj_zrodlo_wpis", None) if not h_id else None
        state.duplikuj_zrodlo_wpis = None  # zużywamy jednorazowo, niezależnie od wyniku

        if h_id or duplikuj_id:
            with db.polacz_baze() as conn:
                c = conn.cursor()
                c.execute("SELECT data, przebieg, cena, wykonawca, kategoria, notatka, koszt_robocizny, gwarancja_data, gwarancja_przebieg FROM historia WHERE id=?", (h_id or duplikuj_id,))
                w = c.fetchone()
                if w:
                    d_val, w_val = str(w[0] or ""), str(w[3] or "")
                    self.p_km = w[1] or None
                    koszt_zrodla, robocizna_zrodla = float(w[2] or 0.0), w[6]
                    if czy_opony and w[4]: kat_val = str(w[4])
                    notatka_val = str(w[5] or "")
                    gwarancja.update(koniec=w[7], limit_km=w[8])
                    if duplikuj_id:
                        d_val = datetime.now().strftime("%d.%m.%Y")
                        # Licznik duplikatu zostaje ze źródła (poprawia się go
                        # ręcznie), więc limit jedzie za polem: poprawka licznika
                        # przesunie go o tyle samo.
                        gwarancja = db.przesun_gwarancje(w[7], w[8], w[0], w[1], d_val, w[1])

        # Magazyn części — ta sama karta, co przy wizycie zbiorczej. Koszt zużytych
        # części dolicza się do kosztu wpisu, więc w polach kosztu stoi sama usługa:
        # od zapisanego kosztu odejmujemy to, co doliczył magazyn. Duplikat zużycia
        # nie przenosi, ale koszt źródła je zawierał — więc odejmujemy i tam.
        self.zuzycie = utils.ZuzycieMagazynu(page, self.state.auto_id, "historia", h_id)
        doliczone = 0.0
        if h_id or duplikuj_id:
            doliczone = (self.zuzycie.koszt_doliczony if h_id
                         else db.koszt_doliczony(db.pobierz_zuzycie_czesci("historia", duplikuj_id)))

        # Data i licznik wymiany niosą za sobą gwarancję ustawioną skrótem
        # („2 lata”, „+20 tys. km”) — patrz utils.PolaGwarancji.
        self.e_d = utils.pole_daty(page, "Data wymiany", d_val,
                                   po_zmianie=lambda: self.gwarancja.przy_zmianie_wymiany())
        self.e_p = ft.TextField(label=f"Przebieg w momencie wymiany ({utils.jednostka_dystansu()})", value=db.wartosc_pola_dystansu(self.p_km), keyboard_type=ft.KeyboardType.NUMBER,
                                on_change=lambda e: self.gwarancja.przy_zmianie_wymiany(), **utils.styl_pola(page=page))
        self.gwarancja = utils.PolaGwarancji(
            page, gwarancja["koniec"], gwarancja["limit_km"],
            data_wymiany=lambda: self.e_d.value, przebieg_wymiany=self._przebieg_km,
            miesiace=gwarancja["miesiace"], dystans_km=gwarancja["dystans_km"],
        )
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
        # Duplikat zaczyna bez plików — faktura jest z tamtej wymiany.
        self.pliki = utils.PolaZalacznikow(page, "historia", h_id)
        self.notatka_bazowa = (notatka_val or "").strip()
        self.k_notatka = utils.pole_notatki(notatka_val, page)

        self._stan_poczatkowy = self._migawka_formularza()
        appbar = utils.zbuduj_pasek_z_powrotem(page, f"{'Edycja' if h_id else 'Nowa wymiana'}: {nazwa}", self.trasa_powrotu, on_save=self.zapisz, czy_zmieniono=self._czy_zmieniono)
        k1 = utils.karta_formularza([self.e_d, self.e_p, self.e_kat, *self.koszt.kontrolki(), self.k_wykonawca], "Informacje o serwisie", ft.Icons.BUILD, domyslnie_otwarte=True, page=page)
        k_gwarancja = utils.karta_formularza(
            self.gwarancja.kontrolki(), "Gwarancja na naprawę", ft.Icons.GPP_GOOD,
            domyslnie_otwarte=bool(gwarancja["koniec"] or gwarancja["limit_km"]), page=page,
        )
        k2 = utils.karta_formularza([self.pliki.kontrolka], "Pliki (paragon, faktura, zdjęcie części)", ft.Icons.ATTACH_FILE,
                                    domyslnie_otwarte=bool(self.pliki.pozycje))
        k3 = utils.karta_formularza([self.k_notatka], "Notatka", ft.Icons.STICKY_NOTE_2_OUTLINED,
                                    domyslnie_otwarte=bool(notatka_val))

        elementy = [k1, k_gwarancja, k2, k3]
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
            self.k_notatka.value, self.zuzycie.migawka(), self.gwarancja.migawka(), self.pliki.migawka(),
        )

    def _przebieg_km(self):
        """Licznik wymiany w km albo None (puste albo błędne pole)."""
        wartosc = utils.parsuj_int(self.e_p.value, None)
        if wartosc is None or wartosc <= 0:
            return None
        return db.dystans_na_km(wartosc, calkowity=True, km_przy_otwarciu=self.p_km)

    def _czy_zmieniono(self):
        return self._migawka_formularza() != self._stan_poczatkowy

    def zapisz(self, e):
        utils.ustaw_blad(self.e_p)
        # Pole w jednostce z Ustawień, baza w km; nieruszone pole wraca bez przeliczania.
        prz = db.dystans_na_km(utils.parsuj_int(self.e_p.value, 0), calkowity=True, km_przy_otwarciu=self.p_km)
        kos, robocizna, bledy_kosztu = self.koszt.sprawdz()
        gw_koniec, gw_limit, bledy_gwarancji = self.gwarancja.sprawdz()
        bledy = []
        if not (self.e_p.value or "").strip() or prz < 0: bledy.append((self.e_p, "Błędny przebieg"))
        bledy += bledy_kosztu + bledy_gwarancji

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

        zdalne_id_czesci_do_nagrobka = []
        with self.pliki.zapis(), db.polacz_baze() as conn:
            if self.h_id:
                conn.execute("UPDATE historia SET data=?, data_iso=?, przebieg=?, cena=?, koszt_robocizny=?, wykonawca=?, kategoria=?, gwarancja_data=?, gwarancja_przebieg=?, zmodyfikowane_przez=?, data_modyfikacji=? WHERE id=?", (self.e_d.value, na_iso(self.e_d.value), prz, koszt_razem, robocizna, wyk, kat, gw_koniec, gw_limit, db.pobierz_moje_imie(), datetime.now().strftime("%d.%m.%Y %H:%M"), self.h_id))
                historia_id = self.h_id
                # Edycja: najpierw oddajemy do magazynu to, co ten wpis zdjął
                # poprzednio, a dopiero potem potrącamy nowy zestaw. Inaczej
                # zmiana ilości z 2 na 1 zdjęłaby ze stanu kolejną sztukę.
                zdalne_id_czesci_do_nagrobka = db.przywroc_czesci_wpisu(historia_id, conn=conn)
            else:
                kursor = conn.cursor()
                kursor.execute("INSERT INTO historia (zadanie_id, data, data_iso, przebieg, cena, koszt_robocizny, wykonawca, kategoria, gwarancja_data, gwarancja_przebieg, dodane_przez) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (self.z_id, self.e_d.value, na_iso(self.e_d.value), prz, koszt_razem, robocizna, wyk, kat, gw_koniec, gw_limit, db.pobierz_moje_imie()))
                historia_id = kursor.lastrowid

            db.rozlicz_czesci_z_magazynu_wpisu(historia_id, nowe_uzyte, conn=conn)
            self.pliki.zapisz_w(conn, historia_id, self.state.auto_id)

        utils.zapisz_notatke_z_formularza("historia", historia_id, self.k_notatka.value, self.notatka_bazowa)

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
