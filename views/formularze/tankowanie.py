"""Formularz tankowania i ładowania."""

import db
import flet as ft
import utils
from date import na_iso
from datetime import datetime


# Litry, cena i kwota: wystarczą dowolne dwa pola, trzecie liczy się samo.
_POLA_TROJKI = ("ilosc", "cena", "kwota")


def _wylicz_pole(cel, wartosci):
    """Wartość pola `cel` z dwóch pozostałych (`wartosci`: klucz -> liczba > 0)
    albo None. Zaokrąglenie jak na dystrybutorze: litry i kwota do setnych, cena
    do tysięcznych — to, co stoi w polu, idzie do bazy bez zmian."""
    ilosc, cena, kwota = (wartosci.get(k) for k in _POLA_TROJKI)
    if cel == "kwota" and ilosc and cena:
        wynik = round(ilosc * cena, 2)
    elif cel == "ilosc" and kwota and cena:
        wynik = round(kwota / cena, 2)
    elif cel == "cena" and kwota and ilosc:
        wynik = round(kwota / ilosc, 3)
    else:
        return None
    return wynik if wynik > 0 else None


def _formy_pola(klucz, prad):
    """(na początek zdania, mianownik, dopełniacz, zaimek w bierniku, czy liczba
    pojedyncza) — do podpisu pod trójką. „kWh” się nie odmienia."""
    if klucz == "ilosc":
        return ("kWh", "kWh", "kWh", "je", False) if prad else ("Litry", "litry", "litrów", "je", False)
    if klucz == "cena":
        return ("Cena", "cena", "ceny", "ją", True)
    return ("Kwota", "kwota", "kwoty", "ją", True)


def _baner_ostrzezenia(page, ikona):
    """Pasek ostrzeżenia pod polem, którego dotyczy: (kontener, tekst). Ukryty,
    dopóki formularz nie ma czego powiedzieć."""
    kolor = utils.KOLOR_STATUS["warning"]
    tekst = ft.Text("", size=utils.FS["caption"], color=kolor, expand=True)
    baner = ft.Container(
        visible=False,
        padding=ft.Padding(12, 8, 12, 8), border_radius=utils.RADIUS["sm"],
        bgcolor=utils.tlo_stanu(page, "warning"),
        content=ft.Row([
            ft.Icon(ikona, size=18, color=kolor),
            tekst,
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
    )
    return baner, tekst


class FormularzTankowanieView(ft.View):
    def __init__(self, page: ft.Page, state, t_id=None, szkic_id=None):
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
        # Pola licznika i dystansu są w jednostce z Ustawień (km albo mi);
        # `ostatni_prz` i cały zapis — w km, jak baza.
        self.j = utils.jednostka_dystansu()

        duplikuj_id = getattr(state, "duplikuj_zrodlo_tankowanie", None) if not t_id else None
        state.duplikuj_zrodlo_tankowanie = None  # zużywamy jednorazowo
        # Szkic z kolejki „do wpisania” (utils/szkice.py) — nowy wpis z paragonu.
        self.szkic = utils.szkic_do_formularza(state, szkic_id, t_id)
        if self.szkic:
            duplikuj_id = None
        zrodlo_id = t_id or duplikuj_id

        d_val = datetime.now().strftime("%d.%m.%Y")
        p_val, dys_val, l_val, k_val, stacja_val = "", "", "", "", ""
        ladowanie_val = ""
        pelna_val = True
        tagi_val = ""
        notatka_val = ""

        self.ostatni_prz = 0
        # km z bazy pokazane w polach — nieruszone pole wraca do bazy bez zmian
        # (patrz db.dystans_na_km), a nie przeliczone tam i z powrotem.
        self.prz_przy_otwarciu = self.dys_przy_otwarciu = None
        with db.polacz_baze() as conn:
            c = conn.cursor()
            if zrodlo_id:
                c.execute("SELECT data, przebieg, dystans, litry, kwota, do_pelna, stacja, tagi, rodzaj_energii, typ_ladowania, notatka FROM tankowania WHERE id=?", (zrodlo_id,))
                w = c.fetchone()
                if w:
                    self.rodzaj_energii = db.normalizuj_rodzaj_energii(w[8], self.state.auto_id)
                    ladowanie_val = str(w[9] or "") if w[9] else ""
                    d_val = str(w[0] or "")
                    self.prz_przy_otwarciu, self.dys_przy_otwarciu = w[1] or None, w[2] or None
                    p_val = db.wartosc_pola_dystansu(w[1], self.j) if w[1] else ""
                    dys_val = db.wartosc_pola_dystansu(w[2], self.j, decimale=2) if w[2] else ""
                    # Ten sam zapis, co pole wyliczane obok („45,3”, nie „45.3”).
                    l_val = utils.liczba_do_pola(w[3]) if w[3] else ""
                    k_val = utils.liczba_do_pola(w[4]) if w[4] else ""
                    pelna_val = bool(w[5])
                    stacja_val = str(w[6] or "")
                    tagi_val = str(w[7] or "")
                    # Duplikat przenosi też notatkę — kontekst („tankowanie na
                    # trasie do Krakowa”) jest zwykle tym, co się powtarza.
                    notatka_val = str(w[10] or "")
                    
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
        if self.szkic:
            # Data migawki, zdjęcie paragonu jako załącznik (bez kopiowania pliku),
            # licznik i opis wpisane zaraz po zdjęciu.
            d_val = self.szkic["data"]
            notatka_val = self.szkic["opis"] or ""
            if self.szkic["przebieg"]:
                self.prz_przy_otwarciu = self.szkic["przebieg"]
                p_val = db.wartosc_pola_dystansu(self.szkic["przebieg"], self.j)
                # Poprzedni licznik jak przy edycji — najwyższy PONIŻEJ licznika
                # z paragonu, bo późniejsze tankowania mogły wejść do bazy wcześniej.
                with db.polacz_baze() as conn:
                    w_prz = conn.execute(
                        "SELECT MAX(przebieg) FROM tankowania WHERE auto_id=? AND przebieg < ?",
                        (self.state.auto_id, self.szkic["przebieg"]),
                    ).fetchone()
                self.ostatni_prz = int(w_prz[0]) if w_prz and w_prz[0] else 0

        # Poprzedni licznik tak, jak stoi w polu — całe km albo całe mile.
        self.ostatni_prz_pola = round(db.dystans_z_km(self.ostatni_prz, self.j))
        if self.szkic and p_val and 0 < self.ostatni_prz_pola <= utils.parsuj_int(p_val, 0):
            dys_val = str(utils.parsuj_int(p_val, 0) - self.ostatni_prz_pola)

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
                    if self.ostatni_prz_pola > 0 and prz >= self.ostatni_prz_pola:
                        dys = float(prz - self.ostatni_prz_pola)
                        self.e_dys.value = str(int(dys)) if dys.is_integer() else str(round(dys, 1))
                    else:
                        self.e_dys.value = ""
                self.e_dys.update()
                self._odswiez_ostrzezenie_ciagu()
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
                    if self.ostatni_prz_pola > 0:
                        self.e_p.value = str(int(self.ostatni_prz_pola + dys))
                    else:
                        self.e_p.value = str(int(dys))
                self.e_p.update()
                self._odswiez_ostrzezenie_ciagu()
            except ValueError:
                pass
            finally:
                self._blokada_sync = False

        self.e_d = utils.pole_daty(page, "Data tankowania", d_val, po_zmianie=self._po_zmianie_daty)
        self.k_stacja, self.get_stacja, self.ustaw_stacja = utils.komponent_wyboru_stacji(
            page, state, stacja_val,
            elektryczny=(self.rodzaj_energii == db.ENERGIA_PRAD)
        )
        hint_prz = f"Ost.: {self.ostatni_prz_pola} {self.j}" if self.ostatni_prz > 0 else "np. 150000"
        
        self.e_p = ft.TextField(label=f"Licznik ({self.j})", value=p_val, hint_text=hint_prz, keyboard_type=ft.KeyboardType.NUMBER, on_change=on_przebieg_changed, **utils.styl_pola(page=page))
        self.e_dys = ft.TextField(label=f"Dystans ({self.j})", value=dys_val, hint_text="np. 450", keyboard_type=ft.KeyboardType.NUMBER, on_change=on_dystans_changed, **utils.styl_pola(page=page))
        
        self.etykiety = db.etykiety_energii(self.rodzaj_energii)

        # Litry, cena i kwota: wpisujesz dowolne dwa, trzecie liczy się samo —
        # zawsze to, którego najdłużej nikt nie ruszał, więc trójka zawsze się
        # zgadza. Cena nie ma kolumny: zapisują się litry i kwota, a cena zostaje
        # ich ilorazem, tak jak w statystykach.
        self.e_l = ft.TextField(label=self.etykiety["ilosc"], value=l_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))
        self.e_cena = ft.TextField(label=f"{self.etykiety['cena_za']} ({utils.symbol_waluty()})", keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))
        self.e_k = ft.TextField(label=f"Całkowity Koszt ({utils.symbol_waluty()})", value=k_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))
        for klucz in _POLA_TROJKI:
            pole = self._pole_trojki(klucz)
            pole.on_change = lambda e, k=klucz: self._zmiana_w_trojce(k)
            pole.on_blur = lambda e, k=klucz: self._wyjscie_z_trojki(k)
        # Otwarty wpis ma litry i kwotę z bazy; zmiana ceny przelicza wtedy litry,
        # bo kwota to pieniądze z paragonu i wyciągu — z trzech liczb najpewniejsza.
        self._wpisane = [k for k, wartosc in (("ilosc", l_val), ("kwota", k_val)) if wartosc]
        self._przelicz_trojke()
        self.t_trojki = utils.podpis("")

        # Nietypowa cena (db.nietypowa_cena): pasek pod trójką, a przy zapisie
        # potwierdzenie jak przy duplikacie. Ceny odniesienia czytane raz na
        # datę i źródło — pole zmienia się przy każdej cyfrze, historia nie.
        self.baner_ceny, self.t_ceny = _baner_ostrzezenia(page, ft.Icons.PRICE_CHANGE)
        self._pamiec_cen = {}
        self.k_trojka = ft.Column([
            self.e_l, self.e_cena,
            ft.Column([self.e_k, self.t_trojki], spacing=utils.SPACING["xs"]),
            self.baner_ceny,
        ], spacing=utils.SPACING["md"])
        self._odswiez_opis_trojki()
        self._odswiez_ostrzezenie_ceny(aktualizuj=False)

        self.c_pel = ft.Checkbox(label=self.etykiety["do_pelna"], value=pelna_val,
                                 on_change=lambda e: self._odswiez_ostrzezenie_ciagu())

        # Pasek „przerywa ciąg” pod polem, którego dotyczy, i jeszcze PRZED
        # zapisem: zapomniany pełny bak poprawia się jednym kliknięciem, a celowe
        # dolewanie przechodzi bez dodatkowego potwierdzenia.
        self.baner_ciagu, self.t_ciagu = _baner_ostrzezenia(page, ft.Icons.LINK_OFF)
        self._odswiez_ostrzezenie_ciagu(aktualizuj=False)

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
            self.e_cena.label = f"{self.etykiety['cena_za']} ({utils.symbol_waluty()})"
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
            self._odswiez_ostrzezenie_ciagu(aktualizuj=False)
            self._odswiez_opis_trojki()
            self._odswiez_ostrzezenie_ceny(aktualizuj=False)
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
        # Duplikat zaczyna bez plików — paragon jest z tamtego dnia.
        self.pliki = utils.PolaZalacznikow(page, "tankowania", t_id, szkic=self.szkic)
        self.notatka_bazowa = (notatka_val or "").strip()
        self.k_notatka = utils.pole_notatki(notatka_val, page)

        self._stan_poczatkowy = self._migawka_formularza()
        # Formularz ze szkicu wraca do kolejki — i przy anulowaniu, i po zapisie.
        self.powrot = "/do-wpisania" if self.szkic else "/"
        appbar = utils.zbuduj_pasek_z_powrotem(page, f"Edycja: {self.etykiety['zdarzenie']}" if t_id else f"Nowe {self.etykiety['zdarzenie']}", self.powrot, on_save=self.zapisz, czy_zmieniono=self._czy_zmieniono)
        
        wiersz_przebiegu = ft.Row([
            ft.Container(self.e_p, expand=True),
            ft.Icon(ft.Icons.SYNC_ALT, color=ft.Colors.with_opacity(0.3, ft.Colors.PRIMARY), tooltip="Pola powiązane automatycznie"),
            ft.Container(self.e_dys, expand=True),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

        k1 = utils.karta_formularza([self.e_d, wiersz_przebiegu], "Przebieg i Data", ft.Icons.SPEED, domyslnie_otwarte=True, page=page)
        zawartosc_k2 = []
        if self.dwuzrodlowy:
            zawartosc_k2 += [
                utils.podpis("Czym tankowałeś?"),
                self.przelacznik_rodzaju,
            ]
        zawartosc_k2 += [
            self.k_stacja, self.e_ladowanie, self.k_trojka, self.c_pel, self.baner_ciagu,
            ft.Text("Przypisane tagi:", size=13, weight="bold"), self.k_tagi,
        ]
        k2 = utils.karta_formularza(
            zawartosc_k2,
            "Szczegóły transakcji",
            ft.Icons.EV_STATION if self.rodzaj_energii == db.ENERGIA_PRAD else ft.Icons.LOCAL_GAS_STATION
        )
        k3 = utils.karta_formularza([self.pliki.kontrolka], "Pliki (paragon, zdjęcia)", ft.Icons.ATTACH_FILE,
                                    domyslnie_otwarte=bool(self.pliki.pozycje))
        # Karta notatki rozwinięta, gdy wpis już jakąś ma — inaczej trzeba by
        # klikać w zwinięty nagłówek, żeby w ogóle zobaczyć, że notatka istnieje.
        k4 = utils.karta_formularza([self.k_notatka], "Notatka", ft.Icons.STICKY_NOTE_2_OUTLINED,
                                    domyslnie_otwarte=bool(notatka_val))

        elementy = [k1, k2, k3, k4, utils.przyciski_akcji(page, f"Zapisz {self.etykiety['zdarzenie']}", self.zapisz, self.powrot)]
        if self.szkic:
            elementy.insert(0, utils.pasek_szkicu(page, self.szkic))

        super().__init__(
            route=(f"/tankowanie/edytuj/{t_id}" if t_id
                   else utils.trasa_uzupelnienia("tankowanie", self.szkic["id"]) if self.szkic
                   else "/tankowanie/nowe"),
            padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO
        )

    def _migawka_formularza(self):
        return (self.e_d.value, self.e_p.value, self.e_dys.value, self.e_l.value,
                self.e_cena.value, self.e_k.value, self.c_pel.value, self.get_stacja(), self.get_tagi(),
                self.rodzaj_energii, self.e_ladowanie.value, self.k_notatka.value, self.pliki.migawka())
    
    def _czy_zmieniono(self):
        return self._migawka_formularza() != self._stan_poczatkowy

    def _przebieg_z_pol(self):
        """Licznik tak, jak policzy go zapis: wpisany wprost albo z dystansu od
        poprzedniego wpisu. None, dopóki oba pola są puste. W km — jak baza."""
        prz = db.dystans_na_km(utils.parsuj_int(self.e_p.value, 0), self.j, calkowity=True,
                               km_przy_otwarciu=self.prz_przy_otwarciu)
        dys = db.dystans_na_km(utils.parsuj_float(self.e_dys.value, 0.0), self.j,
                               km_przy_otwarciu=self.dys_przy_otwarciu)
        if prz <= 0 and dys > 0:
            prz = int(self.ostatni_prz + dys)
        return prz if prz > 0 else None

    def _odswiez_ostrzezenie_ciagu(self, aktualizuj=True):
        """Pasek pod „do pełna”: widoczny, gdy ten wpis byłby kolejnym z rzędu
        bez pełnego baku, a odcinka nie zamyka jeszcze żaden późniejszy pełny.
        Liczony od nowa przy każdej zmianie, od której zależy: pole „do pełna”,
        data, licznik i źródło energii."""
        tekst = None
        if not self.c_pel.value:
            przebieg = self._przebieg_z_pol()
            ciag = db.pobierz_ciag_do_pelna(self.state.auto_id, self.e_d.value, przebieg,
                                            self.rodzaj_energii, wyklucz_id=self.t_id)
            tekst = utils.opis_przerwanego_ciagu(ciag, self.rodzaj_energii, przebieg)
        self.t_ciagu.value = tekst or ""
        self.baner_ciagu.visible = bool(tekst)
        if aktualizuj:
            self.baner_ciagu.update()

    def _po_zmianie_daty(self):
        """Data zmienia i ciąg „do pełna”, i ceny odniesienia. Stronę odświeża
        potem pole_daty — stąd bez własnych update()."""
        self._odswiez_ostrzezenie_ciagu(aktualizuj=False)
        self._odswiez_ostrzezenie_ceny(aktualizuj=False)

    # ------------------------------------------------ litry · cena · kwota

    def _pole_trojki(self, klucz):
        return {"ilosc": self.e_l, "cena": self.e_cena, "kwota": self.e_k}[klucz]

    def _wartosci_trojki(self):
        """{klucz: liczba > 0} — pola, z których da się liczyć; puste i błędne
        (zero, litery) pomija."""
        wartosci = {}
        for klucz in _POLA_TROJKI:
            liczba = utils.parsuj_float(self._pole_trojki(klucz).value, None)
            if liczba is not None and liczba > 0:
                wartosci[klucz] = liczba
        return wartosci

    def _zmiana_w_trojce(self, klucz):
        """Pole ruszone ręcznie staje się najświeższe. `_wpisane` trzyma dwa
        ostatnio ruszane pola (najdawniejsze pierwsze), a trzecie liczy się z nich
        — więc wpisanie pola wyliczonego przelicza to, którego najdłużej nikt nie
        ruszał. Pole wyczyszczone wypada z listy."""
        if klucz in self._wpisane:
            self._wpisane.remove(klucz)
        if (self._pole_trojki(klucz).value or "").strip():
            self._wpisane.append(klucz)
            del self._wpisane[:-2]
        # Błędy z poprzedniej próby zapisu mówią już o innych liczbach.
        for pole in (self.e_l, self.e_cena, self.e_k):
            utils.ustaw_blad(pole)
        self._przelicz_trojke(pomin=klucz)
        self._odswiez_opis_trojki()
        self._odswiez_ostrzezenie_ceny(pokaz=False, aktualizuj=False)
        self.k_trojka.update()

    def _wyjscie_z_trojki(self, klucz):
        """Wyczyszczone i opuszczone pole wraca wyliczone z dwóch pozostałych.
        Dopiero teraz może też pokazać się pasek ceny — w trakcie pisania pierwsza
        cyfra litrów daje cenę dziesięć razy za wysoką i pasek migałby co wpis."""
        if klucz not in self._wpisane and not (self._pole_trojki(klucz).value or "").strip():
            self._przelicz_trojke()
            self._odswiez_opis_trojki()
        self._odswiez_ostrzezenie_ceny(pokaz=True, aktualizuj=False)
        self.k_trojka.update()

    def _przelicz_trojke(self, pomin=None):
        """Pole spoza dwóch ostatnio ruszanych — wyliczone z nich, a przy mniej niż
        dwóch puste (nie ma z czego liczyć). Pole właśnie wyczyszczone (`pomin`)
        zostaje puste do wyjścia z niego: wróciłoby pod palcem, zanim zdąży się
        wpisać nową wartość."""
        for klucz in _POLA_TROJKI:
            if klucz in self._wpisane or klucz == pomin:
                continue
            wartosc = _wylicz_pole(klucz, self._wartosci_trojki()) if len(self._wpisane) == 2 else None
            self._pole_trojki(klucz).value = utils.liczba_do_pola(wartosc)

    def _wyliczane_pole(self):
        """Klucz pola, które stoi wyliczone z dwóch pozostałych, albo None."""
        if len(self._wpisane) < 2:
            return None
        klucz = next(k for k in _POLA_TROJKI if k not in self._wpisane)
        return klucz if (self._pole_trojki(klucz).value or "").strip() else None

    def _odswiez_opis_trojki(self):
        """Ikona kalkulatora w polu wyliczonym i podpis pod trójką — mówi, z czego
        pole wyszło i co przeliczy się, gdy wpisać je ręcznie."""
        wyliczane = self._wyliczane_pole()
        for klucz in _POLA_TROJKI:
            self._pole_trojki(klucz).suffix_icon = ft.Icons.CALCULATE_OUTLINED if klucz == wyliczane else None
        if not wyliczane:
            self.t_trojki.value = "Wystarczą dwa z trzech pól — trzecie policzy się samo."
            return
        prad = self.rodzaj_energii == db.ENERGIA_PRAD
        poczatek, _, _, zaimek, pojedyncza = _formy_pola(wyliczane, prad)
        zrodla = " i ".join(_formy_pola(k, prad)[2] for k in _POLA_TROJKI if k != wyliczane)
        _, nastepne, _, _, nastepne_pojedyncze = _formy_pola(self._wpisane[0], prad)
        self.t_trojki.value = (
            f"{poczatek} {'wyliczona' if pojedyncza else 'wyliczone'} z {zrodla} — wpisz {zaimek}, "
            f"a {'przeliczy się' if nastepne_pojedyncze else 'przeliczą się'} {nastepne}."
        )

    def _cena_z_pol(self):
        """Cena, jaką zapisze formularz: iloraz kwoty i ilości, a dopóki jednej
        z nich brakuje — cena wpisana wprost. None, gdy nie ma z czego jej wziąć."""
        wartosci = self._wartosci_trojki()
        if "ilosc" in wartosci and "kwota" in wartosci:
            return wartosci["kwota"] / wartosci["ilosc"]
        return wartosci.get("cena")

    def _ceny_odniesienia(self):
        klucz = (self.rodzaj_energii, self.e_d.value)
        if klucz not in self._pamiec_cen:
            self._pamiec_cen[klucz] = db.ceny_jednostkowe_w_poblizu(
                self.state.auto_id, self.e_d.value, self.rodzaj_energii, wyklucz_id=self.t_id)
        return self._pamiec_cen[klucz]

    def _odswiez_ostrzezenie_ceny(self, pokaz=True, aktualizuj=True):
        """Pasek pod trójką, gdy cena odstaje co najmniej trzykrotnie od każdej
        z cen tego samego źródła z wpisów najbliższych w czasie. Znika od razu,
        gdy literówka jest poprawiona; pokazuje się tylko przy `pokaz` (wyjście
        z pola, otwarcie formularza, zmiana daty albo źródła)."""
        cena = self._cena_z_pol()
        wynik = db.nietypowa_cena(cena, self._ceny_odniesienia()) if cena else None
        if not wynik:
            self.baner_ceny.visible = False
        elif pokaz or self.baner_ceny.visible:
            self.t_ceny.value = utils.opis_nietypowej_ceny(wynik, self.rodzaj_energii)
            self.baner_ceny.visible = True
        if aktualizuj:
            self.k_trojka.update()

    def _trojka_do_zapisu(self):
        """(litry, kwota, błędy). Wystarczą dwa pola z trzech — brakujące liczy
        się tak samo jak na żywo. Zapisują się litry i kwota; cena nie ma kolumny,
        zostaje ich ilorazem."""
        wartosci, bledy = {}, []
        for klucz in _POLA_TROJKI:
            pole = self._pole_trojki(klucz)
            if not (pole.value or "").strip():
                continue
            liczba = utils.parsuj_float(pole.value, None)
            if liczba is None or liczba <= 0:
                bledy.append((pole, "Podaj liczbę większą od zera"))
            else:
                wartosci[klucz] = liczba
        if bledy:
            return None, None, bledy
        if len(wartosci) < 2:
            return None, None, [(self._pole_trojki(k), "Uzupełnij dwa z trzech pól")
                                for k in _POLA_TROJKI if k not in wartosci]
        lit = wartosci.get("ilosc") or _wylicz_pole("ilosc", wartosci)
        kwo = wartosci.get("kwota") or _wylicz_pole("kwota", wartosci)
        if not lit or not kwo:
            # Grosz za tysiąc litrów: po zaokrągleniu do setnych zostaje zero.
            brakujace = "ilosc" if not lit else "kwota"
            return None, None, [(self._pole_trojki(brakujace), "Podaj liczbę większą od zera")]
        return lit, kwo, []

    def zapisz(self, e):
        for pole in (self.e_p, self.e_dys, self.e_l, self.e_cena, self.e_k): utils.ustaw_blad(pole)
        prz = utils.parsuj_int(self.e_p.value, 0)
        dys = utils.parsuj_float(self.e_dys.value, 0.0)
        lit, kwo, bledy = self._trojka_do_zapisu()
        if prz <= 0 and dys <= 0: 
            bledy.append((self.e_p, "Wymagane"))
            bledy.append((self.e_dys, "Wymagane"))
            
        if bledy: 
            return utils.pokaz_bledy_formularza(self._page, bledy)

        # Od tego miejsca wszystko w km: pola były w jednostce z Ustawień.
        prz = db.dystans_na_km(prz, self.j, calkowity=True, km_przy_otwarciu=self.prz_przy_otwarciu)
        dys = db.dystans_na_km(dys, self.j, km_przy_otwarciu=self.dys_przy_otwarciu)
        if prz == 0 and dys > 0: 
            prz = int(self.ostatni_prz + dys)
        elif dys == 0.0 and prz > 0 and self.ostatni_prz > 0 and prz > self.ostatni_prz: 
            dys = float(prz - self.ostatni_prz)

        if utils.sprawdz_podejrzany_przebieg(self._page, self.e_p, self.state.auto_id, prz, wyklucz_id=self.t_id, tabela="tankowania", nowa_data_str=self.e_d.value):
            return

        if utils.sprawdz_nietypowa_cene(self._page, self.e_cena, self.state.auto_id, self.e_d.value,
                                        self.rodzaj_energii, kwo / lit, wyklucz_id=self.t_id):
            return

        if utils.sprawdz_duplikat_tankowania(self._page, self.e_k, self.state.auto_id, self.e_d.value, prz, kwo, wyklucz_id=self.t_id):
            return

        wybrane_tagi = self.get_tagi()
        stacja_wart = self.get_stacja()
        # Typ ładowania zapisujemy TYLKO przy prądzie — przy paliwie byłby
        # zaszumionym polem bez znaczenia.
        typ_lad = (self.e_ladowanie.value or None) if self.rodzaj_energii == db.ENERGIA_PRAD else None

        with self.pliki.zapis(), db.polacz_baze() as conn:
            if self.t_id:
                conn.execute("UPDATE tankowania SET data=?, data_iso=?, przebieg=?, dystans=?, litry=?, kwota=?, do_pelna=?, stacja=?, tagi=?, rodzaj_energii=?, typ_ladowania=?, zmodyfikowane_przez=?, data_modyfikacji=? WHERE id=?",
                             (self.e_d.value, na_iso(self.e_d.value), prz, dys, lit, kwo, 1 if self.c_pel.value else 0, stacja_wart, wybrane_tagi, self.rodzaj_energii, typ_lad, db.pobierz_moje_imie(), datetime.now().strftime("%d.%m.%Y %H:%M"), self.t_id))
                rekord_id = self.t_id
            else:
                kursor = conn.execute("INSERT INTO tankowania (auto_id, data, data_iso, przebieg, dystans, litry, kwota, do_pelna, stacja, tagi, rodzaj_energii, typ_ladowania, dodane_przez) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (self.state.auto_id, self.e_d.value, na_iso(self.e_d.value), prz, dys, lit, kwo, 1 if self.c_pel.value else 0, stacja_wart, wybrane_tagi, self.rodzaj_energii, typ_lad, db.pobierz_moje_imie()))
                rekord_id = kursor.lastrowid
                # Wpis i koniec szkicu razem albo wcale — zdjęcie ma już nowy wpis.
                if self.szkic:
                    db.zamknij_szkic(self.szkic["id"], conn=conn)
            self.pliki.zapisz_w(conn, rekord_id, self.state.auto_id)
        # Notatkę zapisujemy osobno i TYLKO gdy treść się zmieniła — inaczej
        # poprawka ceny przestemplowałaby cudzy podpis pod notatką na swój.
        utils.zapisz_notatke_z_formularza("tankowania", rekord_id, self.k_notatka.value, self.notatka_bazowa)

        utils.wypchnij_w_tle(self._page, self.state.auto_id, "tankowanie")

        if self.szkic:
            utils.przejdz(self._page, utils.trasa_po_zapisie_szkicu(self.state.auto_id, "/"))
            utils.pokaz_komunikat(self._page, f"Zapisano {self.etykiety['zdarzenie']}!{utils.dopisek_kolejki(self.state.auto_id)}")
            return
        utils.przejdz(self._page, "/")
        utils.pokaz_komunikat(self._page, f"Zapisano {self.etykiety['zdarzenie']}!")


__all__ = [
    "FormularzTankowanieView",
]
