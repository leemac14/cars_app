"""Formularz tankowania i ładowania."""

import db
import flet as ft
import utils
from datetime import datetime


class FormularzTankowanieView(ft.View):
    def __init__(self, page: ft.Page, state, t_id=None):
        self._page = page
        self.state = state
        self.t_id = t_id
        self._blokada_sync = False
        # Hybryda plug-in tankuje OBA źródła, więc o etykietach nie decyduje już
        # typ pojazdu, tylko rodzaj KONKRETNEGO wpisu (patrz db.etykiety_energii).
        self.rodzaje = db.rodzaje_energii_pojazdu(state.auto_id)
        self.dwuzrodlowy = len(self.rodzaje) > 1
        self.rodzaj_energii = self.rodzaje[0]
        self.elektryczny = db.czy_pojazd_elektryczny(state.auto_id)

        duplikuj_id = getattr(state, "duplikuj_zrodlo_tankowanie", None) if not t_id else None
        state.duplikuj_zrodlo_tankowanie = None  # zużywamy jednorazowo
        zrodlo_id = t_id or duplikuj_id

        d_val = datetime.now().strftime("%d.%m.%Y")
        p_val, dys_val, l_val, k_val, stacja_val = "", "", "", "", ""
        ladowanie_val = ""
        pelna_val = True
        self.zalacznik_val = None
        tagi_val = ""
        notatka_val = ""

        self.ostatni_prz = 0
        with db.polacz_baze() as conn:
            c = conn.cursor()
            if zrodlo_id:
                c.execute("SELECT data, przebieg, dystans, litry, kwota, do_pelna, stacja, zalacznik, tagi, rodzaj_energii, typ_ladowania, notatka FROM tankowania WHERE id=?", (zrodlo_id,))
                w = c.fetchone()
                if w: 
                    self.rodzaj_energii = db.normalizuj_rodzaj_energii(w[9], self.state.auto_id)
                    ladowanie_val = str(w[10] or "") if w[10] else ""
                    d_val = str(w[0] or "")
                    p_val = str(w[1] or "") if w[1] else ""
                    dys_val = str(w[2] or "") if w[2] else ""
                    l_val = str(w[3] or "")
                    k_val = str(w[4] or "")
                    pelna_val = bool(w[5])
                    stacja_val = str(w[6] or "") if len(w) > 6 else ""
                    self.zalacznik_val = w[7] if len(w) > 7 else None
                    tagi_val = str(w[8] or "") if len(w) > 8 else ""
                    # Duplikat przenosi też notatkę — kontekst („tankowanie na
                    # trasie do Krakowa”) jest zwykle tym, co się powtarza.
                    notatka_val = str(w[11] or "") if len(w) > 11 else ""
                    
                    cur_prz = int(w[1] or 0)
                    c.execute("SELECT MAX(przebieg) FROM tankowania WHERE auto_id=? AND przebieg < ?", (self.state.auto_id, cur_prz))
                    prev_res = c.fetchone()
                    if prev_res and prev_res[0]:
                        self.ostatni_prz = int(prev_res[0])
                    elif w[2]:
                        self.ostatni_prz = max(0, int(cur_prz - float(w[2])))
            else:
                c.execute("SELECT MAX(przebieg) FROM tankowania WHERE auto_id=?", (self.state.auto_id,))
                res = c.fetchone()
                if res and res[0]:
                    self.ostatni_prz = int(res[0])
                if duplikuj_id:
                    d_val = datetime.now().strftime("%d.%m.%Y")
                    self.zalacznik_val = None

        def on_przebieg_changed(e):
            if self._blokada_sync:
                return
            self._blokada_sync = True
            try:
                txt = (self.e_p.value or "").strip().replace(" ", "")
                if not txt:
                    self.e_dys.value = ""
                else:
                    prz = int(txt)
                    if self.ostatni_prz > 0 and prz >= self.ostatni_prz:
                        dys = float(prz - self.ostatni_prz)
                        self.e_dys.value = str(int(dys)) if dys.is_integer() else str(round(dys, 1))
                    else:
                        self.e_dys.value = ""
                self.e_dys.update()
            except ValueError:
                pass
            finally:
                self._blokada_sync = False

        def on_dystans_changed(e):
            if self._blokada_sync:
                return
            self._blokada_sync = True
            try:
                txt = (self.e_dys.value or "").strip().replace(" ", "").replace(",", ".")
                if not txt or txt == ".":
                    self.e_p.value = ""
                else:
                    dys = float(txt)
                    if self.ostatni_prz > 0:
                        self.e_p.value = str(int(self.ostatni_prz + dys))
                    else:
                        self.e_p.value = str(int(dys))
                self.e_p.update()
            except ValueError:
                pass
            finally:
                self._blokada_sync = False

        self.e_d = utils.pole_daty(page, "Data tankowania", d_val)
        self.k_stacja, self.get_stacja, self.ustaw_stacja = utils.komponent_wyboru_stacji(
            page, state, stacja_val,
            elektryczny=(self.rodzaj_energii == db.ENERGIA_PRAD)
        )
        hint_prz = f"Ost.: {self.ostatni_prz} km" if self.ostatni_prz > 0 else "np. 150000"
        
        self.e_p = ft.TextField(label="Licznik (km)", value=p_val, hint_text=hint_prz, keyboard_type=ft.KeyboardType.NUMBER, on_change=on_przebieg_changed, **utils.styl_pola(page=page))
        self.e_dys = ft.TextField(label="Dystans (km)", value=dys_val, hint_text="np. 450", keyboard_type=ft.KeyboardType.NUMBER, on_change=on_dystans_changed, **utils.styl_pola(page=page))
        
        self.etykiety = db.etykiety_energii(self.rodzaj_energii)

        self.e_l = ft.TextField(label=self.etykiety["ilosc"], value=l_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))
        self.e_k = ft.TextField(label=f"Całkowity Koszt ({utils.symbol_waluty()})", value=k_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))
        self.c_pel = ft.Checkbox(label=self.etykiety["do_pelna"], value=pelna_val)

        # Wolne ładowanie w domu bywa kilka razy tańsze od szybkiego na trasie —
        # bez tego rozróżnienia średnia cena za kWh nic nie mówi.
        self.e_ladowanie = ft.Dropdown(
            label="Typ ładowania",
            options=[ft.DropdownOption(key="", text="— nie podano —")]
                    + [ft.DropdownOption(key=t, text=db.OPISY_LADOWANIA[t]) for t in db.TYPY_LADOWANIA],
            value=ladowanie_val if ladowanie_val in db.TYPY_LADOWANIA else "",
            visible=(self.rodzaj_energii == db.ENERGIA_PRAD),
            **utils.styl_dropdown()
        )

        def przelacz_rodzaj(nowy_idx):
            """Zmiana źródła podmienia etykiety i jednostki w locie — formularz
            zostaje ten sam, bo dane (data, licznik, kwota) są wspólne."""
            self.rodzaj_energii = self.rodzaje[nowy_idx]
            self.etykiety = db.etykiety_energii(self.rodzaj_energii)
            self.e_l.label = self.etykiety["ilosc"]
            self.c_pel.label = self.etykiety["do_pelna"]
            self.e_ladowanie.visible = (self.rodzaj_energii == db.ENERGIA_PRAD)
            if not self.e_ladowanie.visible:
                self.e_ladowanie.value = ""
            self.przelacznik_rodzaju.content = utils.segmented_control(
                self._page,
                [(db.ETYKIETY_RODZAJU[r], i, ft.Icons.EV_STATION if r == db.ENERGIA_PRAD else ft.Icons.LOCAL_GAS_STATION)
                 for i, r in enumerate(self.rodzaje)],
                nowy_idx, przelacz_rodzaj,
            )
            try:
                self._page.update()
            except Exception:
                pass

        self.przelacznik_rodzaju = ft.Container(
            visible=self.dwuzrodlowy,
            content=utils.segmented_control(
                page,
                [(db.ETYKIETY_RODZAJU[r], i, ft.Icons.EV_STATION if r == db.ENERGIA_PRAD else ft.Icons.LOCAL_GAS_STATION)
                 for i, r in enumerate(self.rodzaje)],
                self.rodzaje.index(self.rodzaj_energii), przelacz_rodzaj,
            ) if self.dwuzrodlowy else ft.Container(),
        )
        self.k_tagi, self.get_tagi = utils.komponent_tagow(page, state, tagi_val)
        self.k_zalacznik, self.get_zalacznik = utils.komponent_zalacznika(page, self.zalacznik_val)
        self.notatka_bazowa = (notatka_val or "").strip()
        self.k_notatka = utils.pole_notatki(notatka_val, page)

        self._stan_poczatkowy = self._migawka_formularza()
        appbar = utils.zbuduj_pasek_z_powrotem(page, f"Edycja: {self.etykiety['zdarzenie']}" if t_id else f"Nowe {self.etykiety['zdarzenie']}", "/", on_save=self.zapisz, czy_zmieniono=self._czy_zmieniono)
        
        wiersz_przebiegu = ft.Row([
            ft.Container(self.e_p, expand=True),
            ft.Icon(ft.Icons.SYNC_ALT, color=ft.Colors.with_opacity(0.3, ft.Colors.PRIMARY), tooltip="Pola powiązane automatycznie"),
            ft.Container(self.e_dys, expand=True),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

        k1 = utils.karta_formularza([self.e_d, wiersz_przebiegu], "Przebieg i Data", ft.Icons.SPEED, domyslnie_otwarte=True, page=page)
        zawartosc_k2 = []
        if self.dwuzrodlowy:
            zawartosc_k2 += [
                ft.Text("Czym tankowałeś?", size=12, weight="bold", color=ft.Colors.ON_SURFACE_VARIANT),
                self.przelacznik_rodzaju,
            ]
        zawartosc_k2 += [
            self.k_stacja, self.e_l, self.e_ladowanie, self.e_k, self.c_pel,
            ft.Text("Przypisane tagi:", size=13, weight="bold"), self.k_tagi,
        ]
        k2 = utils.karta_formularza(
            zawartosc_k2,
            "Szczegóły transakcji",
            ft.Icons.EV_STATION if self.rodzaj_energii == db.ENERGIA_PRAD else ft.Icons.LOCAL_GAS_STATION
        )
        k3 = utils.karta_formularza([self.k_zalacznik], "Załącznik", ft.Icons.ATTACH_FILE)
        # Karta notatki rozwinięta, gdy wpis już jakąś ma — inaczej trzeba by
        # klikać w zwinięty nagłówek, żeby w ogóle zobaczyć, że notatka istnieje.
        k4 = utils.karta_formularza([self.k_notatka], "Notatka", ft.Icons.STICKY_NOTE_2_OUTLINED,
                                    domyslnie_otwarte=bool(notatka_val))

        elementy = [k1, k2, k3, k4, utils.przyciski_akcji(page, "Zapisz tankowanie", self.zapisz, "/")]

        super().__init__(
            route=f"/tankowanie/edytuj/{t_id}" if t_id else "/tankowanie/nowe",
            padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO
        )

    def _migawka_formularza(self):
        return (self.e_d.value, self.e_p.value, self.e_dys.value, self.e_l.value,
                self.e_k.value, self.c_pel.value, self.get_stacja(), self.get_tagi(),
                self.rodzaj_energii, self.e_ladowanie.value, self.k_notatka.value)
    
    def _czy_zmieniono(self):
        return self._migawka_formularza() != self._stan_poczatkowy

    def zapisz(self, e):
        for pole in (self.e_p, self.e_dys, self.e_l, self.e_k): utils.ustaw_blad(pole)
        prz = utils.parsuj_int(self.e_p.value, 0)
        dys = utils.parsuj_float(self.e_dys.value, 0.0)
        lit = utils.parsuj_float(self.e_l.value, 0.0)
        kwo = utils.parsuj_float(self.e_k.value, 0.0)
        
        bledy = []
        if lit <= 0: bledy.append((self.e_l, "Wymagane"))
        if kwo <= 0: bledy.append((self.e_k, "Wymagane"))
        if prz <= 0 and dys <= 0: 
            bledy.append((self.e_p, "Wymagane"))
            bledy.append((self.e_dys, "Wymagane"))
            
        if bledy: 
            return utils.pokaz_bledy_formularza(self._page, bledy)

        if prz == 0 and dys > 0: 
            prz = int(self.ostatni_prz + dys)
        elif dys == 0.0 and prz > 0 and self.ostatni_prz > 0 and prz > self.ostatni_prz: 
            dys = float(prz - self.ostatni_prz)

        if utils.sprawdz_podejrzany_przebieg(self._page, self.e_p, self.state.auto_id, prz, wyklucz_id=self.t_id, tabela="tankowania", nowa_data_str=self.e_d.value):
            return

        if utils.sprawdz_duplikat_tankowania(self._page, self.e_k, self.state.auto_id, self.e_d.value, prz, kwo, wyklucz_id=self.t_id):
            return

        wybrane_tagi = self.get_tagi()
        
        przygotowany = db.przygotuj_nowy_zalacznik(self.get_zalacznik())
        nowy_zalacznik = przygotowany if przygotowany is not None else self.zalacznik_val
        stacja_wart = self.get_stacja()
        # Typ ładowania zapisujemy TYLKO przy prądzie — przy paliwie byłby
        # zaszumionym polem bez znaczenia.
        typ_lad = (self.e_ladowanie.value or None) if self.rodzaj_energii == db.ENERGIA_PRAD else None

        with db.polacz_baze() as conn:
            if self.t_id: 
                conn.execute("UPDATE tankowania SET data=?, przebieg=?, dystans=?, litry=?, kwota=?, do_pelna=?, stacja=?, zalacznik=?, tagi=?, rodzaj_energii=?, typ_ladowania=?, zmodyfikowane_przez=?, data_modyfikacji=? WHERE id=?", 
                             (self.e_d.value, prz, dys, lit, kwo, 1 if self.c_pel.value else 0, stacja_wart, nowy_zalacznik, wybrane_tagi, self.rodzaj_energii, typ_lad, db.pobierz_moje_imie(), datetime.now().strftime("%d.%m.%Y %H:%M"), self.t_id))
                rekord_id = self.t_id
            else: 
                kursor = conn.execute("INSERT INTO tankowania (auto_id, data, przebieg, dystans, litry, kwota, do_pelna, stacja, zalacznik, tagi, rodzaj_energii, typ_ladowania, dodane_przez) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", 
                             (self.state.auto_id, self.e_d.value, prz, dys, lit, kwo, 1 if self.c_pel.value else 0, stacja_wart, nowy_zalacznik, wybrane_tagi, self.rodzaj_energii, typ_lad, db.pobierz_moje_imie()))
                rekord_id = kursor.lastrowid
        # Notatkę zapisujemy osobno i TYLKO gdy treść się zmieniła — inaczej
        # poprawka ceny przestemplowałaby cudzy podpis pod notatką na swój.
        utils.zapisz_notatke_z_formularza("tankowania", rekord_id, self.k_notatka.value, self.notatka_bazowa)
        db.zatwierdz_zalacznik(self.zalacznik_val, przygotowany)

        utils.wypchnij_w_tle(self._page, self.state.auto_id, "tankowanie")

        utils.przejdz(self._page, "/")
        utils.pokaz_komunikat(self._page, f"Zapisano {self.etykiety['zdarzenie']}!")


__all__ = [
    "FormularzTankowanieView",
]
