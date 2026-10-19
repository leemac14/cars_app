"""Formularz dolewki (N-12): płyn, data, przebieg, ilość z szybkimi przyciskami, skąd (pozycja magazynu
w l albo ml — stan zejdzie sam — albo spoza magazynu), produkt i koszt. Koszt z półki liczy się z ceny
za jednostkę (przy edycji tej samej pozycji — z poprzedniego zapisu); wpisany ręcznie już nie."""

from datetime import datetime

import flet as ft

import db
import log
import utils


BEZ_MAGAZYNU = "brak"


class FormularzDolewkiView(ft.View):
    def __init__(self, page: ft.Page, state, dolewka_id=None, plyn=None):
        self._page = page
        self.state = state
        self.j = utils.jednostka_dystansu()
        self.waluta = utils.symbol_waluty()
        wpis = db.pobierz_dolewke(dolewka_id) if dolewka_id else None
        if wpis and wpis["auto_id"] != state.auto_id:
            wpis = None  # dolewka innego pojazdu z adresu — zakładamy nową
        self.wpis = wpis
        self.dolewka_id = wpis["id"] if wpis else None

        self.plyny = db.plyny_pojazdu(state.auto_id)
        plyn = wpis["plyn"] if wpis else (plyn if plyn in db.RODZAJE_PLYNOW else getattr(state, "dolewki_plyn", None))
        if plyn not in self.plyny:
            if wpis or plyn in db.RODZAJE_PLYNOW:
                self.plyny.append(plyn)
            else:
                plyn = self.plyny[0] if self.plyny else db.PLYN_OLEJ
        self.p_km = wpis["przebieg"] if wpis else (db.pobierz_aktualny_przebieg(state.auto_id) or None)
        self._koszt_reczny = bool(wpis and wpis["koszt"] is not None and not wpis["magazyn_id"])
        self._produkt_auto = None  # produkt wpisany przez wybór pozycji (zmiana pozycji go podmienia)

        styl = utils.styl_pola(page=page)
        self.e_plyn = ft.Dropdown(
            label="Płyn", value=plyn,
            options=[ft.DropdownOption(key=p, text=db.nazwa_plynu(p), leading_icon=utils.IKONY_PLYNOW.get(p))
                     for p in self.plyny],
            **utils.styl_dropdown(),
        )
        self.e_plyn.on_select = self._zmiana_plynu  # Dropdown we Flecie 0.8x: on_select
        self.e_data = utils.pole_daty(page, "Data dolewki", wpis["data"] if wpis else datetime.now().strftime("%d.%m.%Y"))
        self.e_przebieg = ft.TextField(label=f"Przebieg ({self.j})", value=db.wartosc_pola_dystansu(self.p_km, self.j),
                                       keyboard_type=ft.KeyboardType.NUMBER, **styl)
        self.e_ilosc = ft.TextField(label="Ilość (l)", value=utils.liczba_do_pola(wpis["ilosc"]) if wpis else "",
                                    keyboard_type=ft.KeyboardType.NUMBER, on_change=lambda e: self._przelicz(), **styl)
        self.szybkie = ft.Row([ft.TextButton(db.tekst_litrow(x), on_click=lambda e, x=x: self._ustaw_ilosc(x))
                               for x in db.SZYBKIE_ILOSCI], spacing=0, wrap=True)
        self.e_magazyn = ft.Dropdown(label="Skąd", **utils.styl_dropdown())
        self.e_magazyn.on_select = lambda e: self._zmiana_pozycji()
        self.t_magazyn = utils.podpis("")
        self.e_produkt = ft.TextField(label="Produkt (opcjonalnie)", hint_text="np. Castrol Edge 5W-30",
                                      value=(wpis["produkt"] or "") if wpis else self._produkt_domyslny(plyn), **styl)
        self.e_koszt = ft.TextField(label=f"Koszt ({self.waluta}, opcjonalnie)",
                                    value=utils.liczba_do_pola(wpis["koszt"]) if wpis else "",
                                    keyboard_type=ft.KeyboardType.NUMBER, on_change=self._zmiana_kosztu, **styl)
        self.t_koszt = utils.podpis("")
        self.notatka_bazowa = ((wpis or {}).get("notatka") or "").strip()
        self.k_notatka = utils.pole_notatki(self.notatka_bazowa, page)

        self._wypelnij_magazyn(plyn, wpis["magazyn_id"] if wpis else None)
        self._przelicz(aktualizuj=False)
        self._stan_poczatkowy = self._migawka_formularza()

        powrot = f"/dolewki/{plyn}"
        appbar = utils.zbuduj_pasek_z_powrotem(page, "Edycja dolewki" if wpis else "Nowa dolewka", powrot,
                                               on_save=self.zapisz, czy_zmieniono=self._czy_zmieniono)
        k1 = utils.karta_formularza(
            [self.e_plyn, self.e_data, self.e_przebieg, self.e_ilosc, self.szybkie],
            "Dolewka", ft.Icons.WATER_DROP, domyslnie_otwarte=True, page=page)
        k2 = utils.karta_formularza(
            [self.e_magazyn, self.t_magazyn, self.e_produkt, self.e_koszt, self.t_koszt],
            "Skąd i za ile", ft.Icons.INVENTORY_2, domyslnie_otwarte=True, page=page)
        k3 = utils.karta_formularza([self.k_notatka], "Notatka", ft.Icons.STICKY_NOTE_2_OUTLINED,
                                    domyslnie_otwarte=bool(self.notatka_bazowa))
        super().__init__(
            route=f"/dolewki/edytuj/{self.dolewka_id}" if wpis else f"/dolewki/nowa/{plyn}",
            padding=15, spacing=15, appbar=appbar, scroll=ft.ScrollMode.AUTO,
            controls=[k1, k2, k3, utils.przyciski_akcji(page, "Zapisz dolewkę", self.zapisz, powrot)],
        )

    # ================= POLA =================

    def _produkt_domyslny(self, plyn):
        """Nowa dolewka oleju podpowiada olej z Karty pojazdu („5W-30”)."""
        if plyn != db.PLYN_OLEJ or not self.state.auto_id:
            return ""
        with db.polacz_baze() as conn:
            w = conn.execute("SELECT olej_typ FROM samochody WHERE id=?", (self.state.auto_id,)).fetchone()
        return str((w[0] if w else "") or "").strip()

    def _wypelnij_magazyn(self, plyn, wybrana=None):
        self.pozycje = {str(p["id"]): p for p in db.pozycje_magazynu_dla_plynu(self.state.auto_id, plyn)}
        opcje = [ft.DropdownOption(key=BEZ_MAGAZYNU, text="Spoza magazynu")]
        opcje += [ft.DropdownOption(key=k, text=f"{p['nazwa']} — {utils.formatuj_liczba(self._dostepne(p), 2)} "
                                                f"{p['jednostka']} na stanie") for k, p in self.pozycje.items()]
        self.e_magazyn.options = opcje
        klucz = str(wybrana) if wybrana is not None and str(wybrana) in self.pozycje else BEZ_MAGAZYNU
        self.e_magazyn.value = klucz

    def _pozycja(self):
        return self.pozycje.get(self.e_magazyn.value)

    def _dostepne(self, p):
        """Stan pozycji dla TEJ dolewki — przy edycji z tym, co zdjęła poprzednio."""
        wlasne = (self.wpis["ilosc_magazynu"] or 0) if self.wpis and self.wpis["magazyn_id"] == p["id"] else 0
        return (p["ilosc"] or 0) + wlasne

    def _cena(self, p):
        """Cena za jednostkę pozycji: przy edycji tej samej pozycji z kosztem — z poprzedniego zapisu."""
        w = self.wpis
        if w and w["magazyn_id"] == p["id"] and w["koszt"] is not None and w["ilosc"]:
            return w["koszt"] / db.ilosc_w_jednostce(w["ilosc"], p["jednostka"])
        return p["cena_jednostkowa"]

    def _ustaw_ilosc(self, litry):
        self.e_ilosc.value = utils.liczba_do_pola(litry)
        self._przelicz()

    def _zmiana_plynu(self, e):
        plyn = self.e_plyn.value
        if (self.e_produkt.value or "").strip() in ("", self._produkt_auto, self._produkt_domyslny(db.PLYN_OLEJ)):
            self.e_produkt.value = self._produkt_domyslny(plyn)
            self._produkt_auto = None
        self._wypelnij_magazyn(plyn)
        self._przelicz()

    def _zmiana_pozycji(self):
        p = self._pozycja()
        produkt = (self.e_produkt.value or "").strip()
        if p and produkt in ("", self._produkt_auto, self._produkt_domyslny(self.e_plyn.value)):
            self.e_produkt.value = p["nazwa"]
            self._produkt_auto = p["nazwa"]
        elif not p and produkt and produkt == self._produkt_auto:
            self.e_produkt.value = ""
            self._produkt_auto = None
        self._przelicz()

    def _zmiana_kosztu(self, e):
        self._koszt_reczny = True  # także wyczyszczone — dolewka z półki bez kosztu
        self._przelicz()

    def _przelicz(self, aktualizuj=True):
        """Koszt z półki, podpis pod nim i ostrzeżenie o stanie — po każdej zmianie ilości i pozycji."""
        p = self._pozycja()
        ilosc = utils.parsuj_float(self.e_ilosc.value, 0.0)
        self.t_magazyn.value, self.t_magazyn.color = "", None
        self.t_koszt.value = f"Pusty — bez kosztu. Koszt trafi do Innych kosztów („{db.KATEGORIA_INNE_DOLEWKI}”)."
        if p:
            ilosc_j = db.ilosc_w_jednostce(ilosc, p["jednostka"])
            dostepne = self._dostepne(p)
            if ilosc_j > dostepne + 1e-9:
                self.t_magazyn.value = (f"Na półce tylko {utils.formatuj_liczba(dostepne, 2)} {p['jednostka']} — "
                                        "zejdzie tyle, ile jest.")
                self.t_magazyn.color = utils.KOLOR_STATUS["warning"]
            elif ilosc_j > 0:
                self.t_magazyn.value = (f"Zejdzie {utils.tekst_ilosci(ilosc_j)} {p['jednostka']}, zostanie "
                                        f"{utils.tekst_ilosci(dostepne - ilosc_j)} {p['jednostka']}.")
            cena = self._cena(p)
            if cena is not None and ilosc_j > 0:
                koszt = round(ilosc_j * cena, 2)
                if not self._koszt_reczny:
                    self.e_koszt.value = utils.liczba_do_pola(koszt)
                self.t_koszt.value = (f"Z półki: {utils.tekst_ilosci(ilosc_j)} {p['jednostka']} × "
                                      f"{utils.formatuj_liczba(cena, 2)} {self.waluta} = {utils.formatuj_liczba(koszt)} "
                                      f"{self.waluta}" + (" — w polu kwota wpisana ręcznie." if self._koszt_reczny else "."))
            elif cena is None:
                self.t_koszt.value = "Pozycja bez ceny — wpisz koszt sam albo zostaw pusty."
        self.t_magazyn.visible = bool(self.t_magazyn.value)
        if aktualizuj:
            try:
                self._page.update()
            except Exception:
                log.polkniety("odświeżenie formularza dolewki")

    # ================= ZAPIS =================

    def _migawka_formularza(self):
        return (self.e_plyn.value, self.e_data.value, self.e_przebieg.value, self.e_ilosc.value, self.e_magazyn.value,
                self.e_produkt.value, self.e_koszt.value, self.k_notatka.value)

    def _czy_zmieniono(self):
        return self._migawka_formularza() != self._stan_poczatkowy

    def _przebieg_km(self):
        wartosc = utils.parsuj_int(self.e_przebieg.value, 0)
        return db.dystans_na_km(wartosc, calkowity=True, km_przy_otwarciu=self.p_km) if wartosc > 0 else 0

    def zapisz(self, e):
        for pole in (self.e_ilosc, self.e_przebieg, self.e_koszt):
            utils.ustaw_blad(pole)
        p = self._pozycja()
        dane = {
            "plyn": self.e_plyn.value, "data": self.e_data.value, "przebieg": self._przebieg_km(),
            "ilosc": utils.parsuj_float(self.e_ilosc.value, 0.0), "produkt": self.e_produkt.value,
            "magazyn_id": p["id"] if p else None, "koszt": utils.parsuj_float(self.e_koszt.value, 0.0) or None,
        }
        bledy = []
        if dane["ilosc"] <= 0:
            bledy.append((self.e_ilosc, "Podaj ilość w litrach"))
        elif dane["ilosc"] > db.MAKS_ILOSC_DOLEWKI:
            bledy.append((self.e_ilosc, f"Za dużo jak na dolewkę (najwyżej {db.tekst_litrow(db.MAKS_ILOSC_DOLEWKI)})"))
        if dane["przebieg"] <= 0:
            bledy.append((self.e_przebieg, "Podaj przebieg — od niego liczy się zużycie"))
        if (self.e_koszt.value or "").strip() and utils.parsuj_float(self.e_koszt.value, -1.0) < 0:
            bledy.append((self.e_koszt, "Koszt to liczba albo puste pole"))
        if bledy:
            return utils.pokaz_bledy_formularza(self._page, bledy)
        if utils.sprawdz_podejrzany_przebieg(self._page, self.e_przebieg, self.state.auto_id, dane["przebieg"],
                                             wyklucz_id=self.dolewka_id, tabela="dolewki", nowa_data_str=dane["data"]):
            return

        rekord_id = db.zapisz_dolewke(self.state.auto_id, dane, self.dolewka_id)
        if not rekord_id:
            return utils.pokaz_komunikat(self._page, "Nie zapisano — tej dolewki już nie ma albo nie możesz jej zmienić.",
                                         utils.KOLOR_STATUS["error"])
        utils.zapisz_notatke_z_formularza("dolewki", rekord_id, self.k_notatka.value, self.notatka_bazowa)
        utils.wypchnij_w_tle(self._page, self.state.auto_id, "dolewka")
        self.state.dolewki_plyn = dane["plyn"]
        utils.przejdz(self._page, f"/dolewki/{dane['plyn']}")
        z = db.zuzycie_plynu(self.state.auto_id, dane["plyn"])
        dopisek = f" • zużycie {db.tekst_zuzycia(z['na_1000'], self.j)}" if z and z["na_1000"] is not None else ""
        utils.pokaz_komunikat(self._page, f"Zapisano dolewkę {db.tekst_litrow(dane['ilosc'])}{dopisek}")


__all__ = [
    "FormularzDolewkiView",
]
