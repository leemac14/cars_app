import flet as ft
from datetime import datetime
import db
import utils
import json
import urllib.request
import urllib.parse
import asyncio
import sqlite3
import sync

def pobierz_dane_vin(vin: str) -> dict:
    """
    Pobiera dane pojazdu z darmowego, publicznego API NHTSA (vPIC) na podstawie VIN.
    Funkcja jest SYNCHRONICZNA i blokująca — wywołuj ją wyłącznie przez
    `await asyncio.to_thread(pobierz_dane_vin, vin)`, żeby nie zamrozić UI.
    Zwraca słownik pól (Make, Model, ModelYear, DisplacementCC, EngineHP...).
    W razie problemu rzuca wyjątek — obsługa błędów jest po stronie wywołującego.
    """
    url = f"https://vpic.nhtsa.dot.gov/api/vehicles/decodevinvalues/{urllib.parse.quote(vin)}?format=json"
    zapytanie = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

    with urllib.request.urlopen(zapytanie, timeout=12) as odpowiedz:
        surowe_dane = odpowiedz.read()

    dane_json = json.loads(surowe_dane)
    wyniki = dane_json.get("Results") or []
    if not wyniki:
        raise ValueError("Pusta odpowiedź z bazy NHTSA.")

    return wyniki[0]

# Tablica kodowania roku produkcji wg normy ISO 3779 (10. znak VIN).
# NHTSA rozpoznaje ją głównie dla aut sprzedawanych w USA — dla europejskich
# pojazdów pole ModelYear bywa puste, więc to lokalny fallback.
_ISO3779_KOD_ROKU = {
    "A": 1980, "B": 1981, "C": 1982, "D": 1983, "E": 1984, "F": 1985, "G": 1986, "H": 1987,
    "J": 1988, "K": 1989, "L": 1990, "M": 1991, "N": 1992, "P": 1993, "R": 1994, "S": 1995,
    "T": 1996, "V": 1997, "W": 1998, "X": 1999, "Y": 2000,
    "1": 2001, "2": 2002, "3": 2003, "4": 2004, "5": 2005, "6": 2006, "7": 2007, "8": 2008, "9": 2009,
}

def rok_produkcji_z_vin(vin: str):
    """Dekoduje przybliżony rok produkcji z 10. znaku VIN. Kod roku powtarza się
    w 30-letnim cyklu, więc cykl (np. 1994 czy 2024 dla znaku 'R') rozstrzygamy
    umowną, powszechnie stosowaną konwencją: jeśli 7. znak VIN to litera —
    nowszy cykl (2010+), jeśli cyfra — starszy (1980-2009).
    Zwraca None, jeśli VIN ma nietypową długość albo 10. znak nie jest rozpoznany."""
    vin = (vin or "").strip().upper()
    if len(vin) != 17:
        return None
    bazowy_rok = _ISO3779_KOD_ROKU.get(vin[9])
    if bazowy_rok is None:
        return None
    return bazowy_rok + 30 if vin[6].isalpha() else bazowy_rok

class FormularzAutoView(ft.View):
    def __init__(self, page: ft.Page, state, auto_id=None):
        self._page = page
        self.state = state
        self.auto_id = auto_id
        
        n_val, r_val, v_val, ro_val, oc_val, pt_val = "", "", "", "", "", ""
        m_val, mod_val, gen_val = "", "", ""
        poj_val, moc_val, pal_val, skrz_val, not_val = "", "", "Benzyna", "Manualna", ""
        wp_val, wt_val, cp_val, ct_val = "", "", "", ""
        ot_val, op_val, akum_val, zm_val, zd_val = "", "", "", "", ""
        ac_val, asy_val, gas_val, apt_val = "", "", "", ""
        self.zg_val = None
        self.kolor_auta_val = None
        
        if auto_id:
            with db.polacz_baze() as c:
                c.row_factory = sqlite3.Row
                cur = c.cursor()
                cur.execute(
                    "SELECT nazwa, nr_rej, vin, rok_produkcji, oc_data, przeglad_data, "
                    "pojemnosc_silnika, moc_silnika, typ_paliwa, skrzynia_biegow, notatki, "
                    "wycieraczki_przod, wycieraczki_tyl, cisnienie_przod, cisnienie_tyl, "
                    "olej_typ, olej_pojemnosc, akumulator, zarowki_mijania, zarowki_drogowe, "
                    "ac_data, assistance_data, gasnica_data, apteczka_data, zdjecie_glowne, "
                    "marka, model, generacja, kolor_motywu "
                    "FROM samochody WHERE id=?", 
                    (auto_id,)
                )
                w = cur.fetchone()
                if w: 
                    n_val, r_val, v_val, ro_val = str(w["nazwa"] or ""), str(w["nr_rej"] or ""), str(w["vin"] or ""), str(w["rok_produkcji"] or "")
                    oc_val, pt_val = str(w["oc_data"] or ""), str(w["przeglad_data"] or "")
                    poj_val, moc_val = str(w["pojemnosc_silnika"] or ""), str(w["moc_silnika"] or "")
                    pal_val, skrz_val, not_val = str(w["typ_paliwa"] or "Benzyna"), str(w["skrzynia_biegow"] or "Manualna"), str(w["notatki"] or "")
                    wp_val, wt_val = str(w["wycieraczki_przod"] or ""), str(w["wycieraczki_tyl"] or "")
                    cp_val, ct_val = str(w["cisnienie_przod"] or ""), str(w["cisnienie_tyl"] or "")
                    ot_val, op_val = str(w["olej_typ"] or ""), str(w["olej_pojemnosc"] or "")
                    akum_val, zm_val, zd_val = str(w["akumulator"] or ""), str(w["zarowki_mijania"] or ""), str(w["zarowki_drogowe"] or "")
                    ac_val, asy_val = str(w["ac_data"] or ""), str(w["assistance_data"] or "")
                    gas_val, apt_val = str(w["gasnica_data"] or ""), str(w["apteczka_data"] or "")
                    self.zg_val = str(w["zdjecie_glowne"]) if w["zdjecie_glowne"] else None
                    self.kolor_auta_val = str(w["kolor_motywu"]) if w["kolor_motywu"] else None
                    
                    # Wczytywanie nowych kolumn
                    m_val = str(w["marka"] or "")
                    mod_val = str(w["model"] or "")
                    gen_val = str(w["generacja"] or "")
                    
                    # Zabezpieczenie wstecznej kompatybilności 
                    # Jeśli ktoś miał stare auto wpisane jako 1 string, wyświetlimy to w polu Marka
                    if n_val and not m_val and not mod_val:
                        m_val = n_val

        self.k_zdjecie, self.get_zdjecie = utils.komponent_zalacznika(page, self.zg_val)
        self.k_kolor, self.get_kolor = utils.komponent_wyboru_koloru(page, self.kolor_auta_val)

        # Nowe 3 pola zamiast jednego pola nazwy
        self.e_marka = ft.TextField(label="Marka pojazdu*", value=m_val, **utils.styl_pola(page=page))
        self.e_model = ft.TextField(label="Model pojazdu*", value=mod_val, **utils.styl_pola(page=page))
        self.e_generacja = ft.TextField(label="Generacja (opcjonalnie)", value=gen_val, **utils.styl_pola(page=page))
        
        self.e_rej = ft.TextField(label="Nr Rejestracyjny", value=r_val, **utils.styl_pola(page=page))
        self.e_rok = ft.TextField(label="Rok produkcji", value=ro_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))
        self.e_vin = ft.TextField(label="Numer VIN", value=v_val, **utils.styl_pola(page=page))
        self.btn_dekoduj_vin = ft.IconButton(
            icon=ft.Icons.AUTO_AWESOME,
            icon_color=ft.Colors.PRIMARY,
            icon_size=20,
            tooltip="Rozkoduj VIN",
            on_click=self.rozkoduj_vin,
        )
        self.e_vin.suffix = self.btn_dekoduj_vin
        self.e_oc = utils.pole_daty(page, "Polisa OC", oc_val)
        self.e_pt = utils.pole_daty(page, "Przegląd techniczny", pt_val)

        akt_przebieg = db.pobierz_aktualny_przebieg(auto_id) if auto_id else 0
        self.e_przebieg = ft.TextField(
            label="Aktualny przebieg (km)", 
            value=str(akt_przebieg) if akt_przebieg else "", 
            keyboard_type=ft.KeyboardType.NUMBER, 
            **utils.styl_pola(page=page)
        )

        self.e_poj = ft.TextField(label="Pojemność silnika (cm³)", value=poj_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))
        self.e_moc = ft.TextField(label="Moc silnika (KM)", value=moc_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))
        self.e_pal = ft.Dropdown(label="Typ paliwa", options=[ft.DropdownOption(key=x, text=x) for x in ["Benzyna", "Diesel", "LPG", "Hybryda", "Elektryczny"]], value=pal_val, **utils.styl_dropdown())
        self.e_skrz = ft.Dropdown(label="Skrzynia biegów", options=[ft.DropdownOption(key=x, text=x) for x in ["Manualna", "Automatyczna"]], value=skrz_val, **utils.styl_dropdown())
        self.e_not = ft.TextField(label="Dodatkowe notatki", value=not_val, multiline=True, min_lines=2, max_lines=4, **utils.styl_pola(page=page))

        self.e_wp = ft.TextField(label="Wycieraczki (przód)", value=wp_val, hint_text="np. 60cm", **utils.styl_pola(page=page))
        self.e_wt = ft.TextField(label="Wycieraczki (tył)", value=wt_val, hint_text="np. 40cm", **utils.styl_pola(page=page))
        self.e_cp = ft.TextField(label="Ciśnienie opon (przód)", value=cp_val, hint_text="np. 2.2 bar", **utils.styl_pola(page=page))
        self.e_ct = ft.TextField(label="Ciśnienie opon (tył)", value=ct_val, hint_text="np. 2.0 bar", **utils.styl_pola(page=page))
        self.e_ot = ft.TextField(label="Typ oleju silnikowego", value=ot_val, hint_text="np. 5W-30", **utils.styl_pola(page=page))
        self.e_op = ft.TextField(label="Pojemność oleju", value=op_val, hint_text="np. 4.5L", **utils.styl_pola(page=page))
        self.e_akum = ft.TextField(label="Akumulator", value=akum_val, hint_text="np. 60Ah 540A, prawy +", **utils.styl_pola(page=page))
        self.e_zm = ft.TextField(label="Żarówki (mijania)", value=zm_val, hint_text="np. H7", **utils.styl_pola(page=page))
        self.e_zd = ft.TextField(label="Żarówki (drogowe)", value=zd_val, hint_text="np. H1", **utils.styl_pola(page=page))

        self.e_ac = utils.pole_daty(page, "Polisa AC (Autocasco)", ac_val)
        self.e_asy = utils.pole_daty(page, "Ważność Assistance", asy_val)
        self.e_gas = utils.pole_daty(page, "Ważność gaśnicy", gas_val)
        self.e_apt = utils.pole_daty(page, "Ważność apteczki", apt_val)

        appbar = utils.zbuduj_pasek_z_powrotem(page, "Edycja pojazdu" if auto_id else "Nowy pojazd", "/", on_save=self.zapisz)

        wiersz_auto = ft.Row([ft.Container(self.e_marka, expand=True), ft.Container(self.e_model, expand=True)], spacing=10)
        wiersz_wycieraczki = ft.Row([ft.Container(self.e_wp, expand=True), ft.Container(self.e_wt, expand=True)], spacing=10)
        wiersz_cisnienie = ft.Row([ft.Container(self.e_cp, expand=True), ft.Container(self.e_ct, expand=True)], spacing=10)
        wiersz_olej = ft.Row([ft.Container(self.e_ot, expand=True), ft.Container(self.e_op, expand=True)], spacing=10)
        wiersz_zarowki = ft.Row([ft.Container(self.e_zm, expand=True), ft.Container(self.e_zd, expand=True)], spacing=10)
        
        k0 = utils.karta_formularza([self.k_zdjecie], "Zdjęcie profilowe", ft.Icons.ADD_A_PHOTO, domyslnie_otwarte=True)
        # Zastąpiono pojedyncze pole e_nazwa rzędem i polem generacji
        k1 = utils.karta_formularza([wiersz_auto, self.e_generacja, self.e_rej, self.e_vin, self.e_rok, self.e_przebieg], "Dane identyfikacyjne", ft.Icons.DIRECTIONS_CAR, domyslnie_otwarte=True, page=page)
        kk = utils.karta_formularza(
            [ft.Text("Ten kolor będzie używany w całym interfejsie, gdy ten pojazd jest aktywny.", size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT), self.k_kolor],
            "Kolor interfejsu dla tego pojazdu", ft.Icons.PALETTE
        )
        k2 = utils.karta_formularza([self.e_pal, self.e_skrz, self.e_poj, self.e_moc], "Specyfikacja techniczna", ft.Icons.SETTINGS)
        k3 = utils.karta_formularza([self.e_oc, self.e_pt], "Ważne daty", ft.Icons.CALENDAR_MONTH)
        k5 = utils.karta_formularza([wiersz_wycieraczki, wiersz_cisnienie, wiersz_olej, self.e_akum, wiersz_zarowki], "Ściągawka do sklepu", ft.Icons.SHOPPING_CART)
        k6 = utils.karta_formularza([self.e_ac, self.e_asy, self.e_gas, self.e_apt], "Dodatkowe polisy i BHP", ft.Icons.SHIELD)
        k4 = utils.karta_formularza([self.e_not], "Uwagi", ft.Icons.NOTES)
        
        elementy = [k0, k1, kk, k2, k3, k5, k6, k4, utils.przyciski_akcji(page, "✅ Zapisz pojazd", self.zapisz, "/")]
        super().__init__(route=f"/auto/edytuj/{auto_id}" if auto_id else "/auto/nowy", padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO)

    async def rozkoduj_vin(self, e):
        vin = (self.e_vin.value or "").strip().upper()

        if not vin or len(vin) < 17:
            self.e_vin.error_text = "Wpisz pełny, 17-znakowy numer VIN"
            self._page.update()
            utils.pokaz_komunikat(self._page, "VIN jest pusty lub za krótki (wymagane 17 znaków).", ft.Colors.RED_700)
            return

        self.e_vin.error_text = None
        self.btn_dekoduj_vin.icon = ft.Icons.HOURGLASS_TOP
        self.btn_dekoduj_vin.disabled = True
        self._page.update()

        try:
            dane = await asyncio.to_thread(pobierz_dane_vin, vin)
        except Exception as ex:
            self.btn_dekoduj_vin.icon = ft.Icons.AUTO_AWESOME
            self.btn_dekoduj_vin.disabled = False
            self._page.update()
            utils.pokaz_komunikat(self._page, f"Brak połączenia z bazą VIN ({ex}).", ft.Colors.RED_700)
            return

        self.btn_dekoduj_vin.icon = ft.Icons.AUTO_AWESOME
        self.btn_dekoduj_vin.disabled = False

        marka = (dane.get("Make") or "").strip()
        if not marka:
            blad_api = (dane.get("ErrorText") or "Nie znaleziono danych dla podanego numeru VIN.").strip()
            self._page.update()
            utils.pokaz_komunikat(self._page, f"Nie udało się rozkodować VIN: {blad_api[:150]}", ft.Colors.RED_700)
            return

        model = (dane.get("Model") or "").strip()
        
        # Przypisujemy do nowych pól
        self.e_marka.value = marka
        self.e_model.value = model

        rok = (dane.get("ModelYear") or "").strip()
        if not rok:
            rok_fallback = rok_produkcji_z_vin(vin)
            if rok_fallback:
                rok = str(rok_fallback)
        if rok:
            self.e_rok.value = rok

        poj_ccm = (dane.get("DisplacementCC") or "").strip()
        poj_l = (dane.get("DisplacementL") or "").strip()
        if poj_ccm:
            try:
                self.e_poj.value = str(int(round(float(poj_ccm))))
            except ValueError:
                pass
        elif poj_l:
            try:
                self.e_poj.value = str(int(round(float(poj_l) * 1000)))
            except ValueError:
                pass

        moc = (dane.get("EngineHP") or "").strip()
        if moc:
            try:
                self.e_moc.value = str(int(round(float(moc))))
            except ValueError:
                pass

        paliwo = (dane.get("FuelTypePrimary") or "").lower()
        mapa_paliwa = [
            ("diesel", "Diesel"),
            ("electric", "Elektryczny"),
            ("hybrid", "Hybryda"),
            ("natural gas", "LPG"),
            ("propane", "LPG"),
            ("liquefied petroleum", "LPG"),
            ("gasoline", "Benzyna"),
            ("flexible fuel", "Benzyna"),
        ]
        for fragment, wartosc_pl in mapa_paliwa:
            if fragment in paliwo:
                self.e_pal.value = wartosc_pl
                break

        skrzynia = (dane.get("TransmissionStyle") or "").lower()
        if "manual" in skrzynia:
            self.e_skrz.value = "Manualna"
        elif "automatic" in skrzynia or "cvt" in skrzynia:
            self.e_skrz.value = "Automatyczna"

        self._page.update()
        utils.pokaz_komunikat(self._page, "Rozkodowano dane z numeru VIN! Sprawdź uzupełnione pola.")

    def zapisz(self, e):
        for pole in (self.e_marka, self.e_model, self.e_rok, self.e_vin):
            pole.error_text = None

        bledy = []
        
        self.e_przebieg.error_text = None
        prz = utils.parsuj_int(self.e_przebieg.value, 0)
        if prz < 0:
            bledy.append((self.e_przebieg, "Błędny przebieg"))
        
        marka = (self.e_marka.value or "").strip()
        model = (self.e_model.value or "").strip()
        generacja = (self.e_generacja.value or "").strip()

        if not marka:
            bledy.append((self.e_marka, "Podaj markę"))
        if not model:
            bledy.append((self.e_model, "Podaj model"))
        
        if self.e_rok.value:
            r = utils.parsuj_int(self.e_rok.value, None)
            if r is None or r < db.ROK_MIN or r > datetime.now().year + 1:
                bledy.append((self.e_rok, "Błędny rok"))
        if self.e_vin.value and len(self.e_vin.value) > 17:
            bledy.append((self.e_vin, "Maks. 17 znaków"))
        
        if bledy:
            return utils.pokaz_bledy_formularza(self._page, bledy)

        # Dynamiczne złożenie nazwy pojazdu
        n = " ".join(filter(None, [marka, model, generacja]))

        # Weryfikacja unikalności konfiguracji przed przetwarzaniem załącznika
        with db.polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT id FROM samochody WHERE LOWER(nazwa)=LOWER(?) AND id!=?", (n, self.auto_id or 0))
            if c.fetchone():
                self.e_marka.error_text = "Pojazd o tej samej konfiguracji już istnieje!"
                self.e_model.error_text = "Zmień dane, aby były unikalne."
                self._page.update()
                return utils.pokaz_komunikat(self._page, "Pojazd o takiej nazwie już istnieje w bazie.", ft.Colors.RED_700)

        # PO:
        przygotowany_zdj = db.przygotuj_nowy_zalacznik(self.get_zdjecie())
        nowe_zdj = przygotowany_zdj if przygotowany_zdj is not None else self.zg_val
        nowy_kolor = self.get_kolor()

        try:
            with db.polacz_baze() as conn:
                if self.auto_id:
                    conn.execute(
                        "UPDATE samochody SET nazwa=?, nr_rej=?, vin=?, rok_produkcji=?, oc_data=?, przeglad_data=?, "
                        "pojemnosc_silnika=?, moc_silnika=?, typ_paliwa=?, skrzynia_biegow=?, notatki=?, "
                        "wycieraczki_przod=?, wycieraczki_tyl=?, cisnienie_przod=?, cisnienie_tyl=?, "
                        "olej_typ=?, olej_pojemnosc=?, akumulator=?, zarowki_mijania=?, zarowki_drogowe=?, "
                        "ac_data=?, assistance_data=?, gasnica_data=?, apteczka_data=?, zdjecie_glowne=?, "
                        "marka=?, model=?, generacja=?, kolor_motywu=? WHERE id=?", 
                        (n, self.e_rej.value, self.e_vin.value, self.e_rok.value, self.e_oc.value, self.e_pt.value, 
                         self.e_poj.value, self.e_moc.value, self.e_pal.value, self.e_skrz.value, self.e_not.value,
                         self.e_wp.value, self.e_wt.value, self.e_cp.value, self.e_ct.value,
                         self.e_ot.value, self.e_op.value, self.e_akum.value, self.e_zm.value, self.e_zd.value,
                         self.e_ac.value, self.e_asy.value, self.e_gas.value, self.e_apt.value, nowe_zdj, 
                         marka, model, generacja, nowy_kolor, self.auto_id)
                    )
                    if self.state.auto_id == self.auto_id:
                        self.state.auto_nazwa = n
                else:
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO samochody (nazwa, nr_rej, vin, rok_produkcji, oc_data, przeglad_data, "
                        "pojemnosc_silnika, moc_silnika, typ_paliwa, skrzynia_biegow, notatki, "
                        "wycieraczki_przod, wycieraczki_tyl, cisnienie_przod, cisnienie_tyl, "
                        "olej_typ, olej_pojemnosc, akumulator, zarowki_mijania, zarowki_drogowe, "
                        "ac_data, assistance_data, gasnica_data, apteczka_data, zdjecie_glowne, "
                        "marka, model, generacja, kolor_motywu) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", 
                        (n, self.e_rej.value, self.e_vin.value, self.e_rok.value, self.e_oc.value, self.e_pt.value,
                         self.e_poj.value, self.e_moc.value, self.e_pal.value, self.e_skrz.value, self.e_not.value,
                         self.e_wp.value, self.e_wt.value, self.e_cp.value, self.e_ct.value,
                         self.e_ot.value, self.e_op.value, self.e_akum.value, self.e_zm.value, self.e_zd.value,
                         self.e_ac.value, self.e_asy.value, self.e_gas.value, self.e_apt.value, nowe_zdj,
                         marka, model, generacja, nowy_kolor)
                    )
                    n_id = cur.lastrowid
                    for dz in db.DOMYSLNE_ZADANIA:
                        czy_opony = 1 if "opon" in dz.lower() or "kół" in dz.lower() else 0
                        conn.execute(
                            "INSERT INTO zadania (auto_id, nazwa, dotyczy_opon) VALUES (?, ?, ?)", 
                            (n_id, dz, czy_opony)
                        )
                    self.state.auto_id = n_id
                    self.state.auto_nazwa = n
                # --- ZAPIS KOREKTY PRZEBIEGU ---
                zapisane_id = self.auto_id if self.auto_id else n_id
                aktualny_prz = db.pobierz_aktualny_przebieg(zapisane_id)
                
                # Jeśli przebieg z formularza auta różni się od obecnego, zapisujemy to jako najnowszy odczyt
                if prz > 0 and prz != aktualny_prz:
                    conn.execute(
                        "INSERT INTO odczyty_przebiegu (auto_id, data, przebieg) VALUES (?, ?, ?)", 
                        (zapisane_id, datetime.now().strftime("%d.%m.%Y"), prz)
                    )

            db.zatwierdz_zalacznik(self.zg_val, przygotowany_zdj)

            wspolny_id, _ = sync.czy_udostepniony(self.state.auto_id)
            if wspolny_id:
                async def _wypchnij():
                    try:
                        await asyncio.to_thread(sync.synchronizuj_tankowania, self.state.auto_id)
                    except Exception:
                        pass  # brak sieci nie może zepsuć lokalnego zapisu — spróbuje się przy kolejnej synchronizacji
                self._page.run_task(_wypchnij)

            utils.przejdz(self._page, "/")
            utils.pokaz_komunikat(self._page, "Zapisano pojazd!")
        except Exception as ex:
            db.anuluj_nowy_zalacznik(przygotowany_zdj)
            utils.pokaz_komunikat(self._page, f"Błąd zapisu pojazdu: {ex}", ft.Colors.RED_700)

class FormularzTankowanieView(ft.View):
    def __init__(self, page: ft.Page, state, t_id=None):
        self._page = page
        self.state = state
        self.t_id = t_id
        self._blokada_sync = False

        d_val = datetime.now().strftime("%d.%m.%Y")
        p_val, dys_val, l_val, k_val, stacja_val = "", "", "", "", ""
        pelna_val = True
        self.zalacznik_val = None
        tagi_val = ""

        self.ostatni_prz = 0
        with db.polacz_baze() as conn:
            c = conn.cursor()
            if t_id:
                c.execute("SELECT data, przebieg, dystans, litry, kwota, do_pelna, stacja, zalacznik, tagi FROM tankowania WHERE id=?", (t_id,))
                w = c.fetchone()
                if w: 
                    d_val = str(w[0] or "")
                    p_val = str(w[1] or "") if w[1] else ""
                    dys_val = str(w[2] or "") if w[2] else ""
                    l_val = str(w[3] or "")
                    k_val = str(w[4] or "")
                    pelna_val = bool(w[5])
                    stacja_val = str(w[6] or "") if len(w) > 6 else ""
                    self.zalacznik_val = w[7] if len(w) > 7 else None
                    tagi_val = str(w[8] or "") if len(w) > 8 else ""
                    
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
        self.e_stacja = ft.TextField(label="Stacja paliw (opcjonalnie)", value=stacja_val, hint_text="np. Orlen, Shell", **utils.styl_pola(page=page))
        hint_prz = f"Ost.: {self.ostatni_prz} km" if self.ostatni_prz > 0 else "np. 150000"
        
        self.e_p = ft.TextField(label="Licznik (km)", value=p_val, hint_text=hint_prz, keyboard_type=ft.KeyboardType.NUMBER, on_change=on_przebieg_changed, **utils.styl_pola(page=page))
        self.e_dys = ft.TextField(label="Dystans (km)", value=dys_val, hint_text="np. 450", keyboard_type=ft.KeyboardType.NUMBER, on_change=on_dystans_changed, **utils.styl_pola(page=page))
        
        self.e_l = ft.TextField(label="Zatankowano (Litry)", value=l_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))
        self.e_k = ft.TextField(label=f"Całkowity Koszt ({utils.symbol_waluty()})", value=k_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))
        self.c_pel = ft.Checkbox(label="Zatankowano do pełna (wymagane do spalania)", value=pelna_val)
        self.k_tagi, self.get_tagi = utils.komponent_tagow(page, state, tagi_val)
        self.k_zalacznik, self.get_zalacznik = utils.komponent_zalacznika(page, self.zalacznik_val)

        appbar = utils.zbuduj_pasek_z_powrotem(page, "Edycja tankowania" if t_id else "Nowe tankowanie", "/", on_save=self.zapisz)
        
        wiersz_przebiegu = ft.Row([
            ft.Container(self.e_p, expand=True),
            ft.Icon(ft.Icons.SYNC_ALT, color=ft.Colors.with_opacity(0.3, ft.Colors.PRIMARY), tooltip="Pola powiązane automatycznie"),
            ft.Container(self.e_dys, expand=True),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

        k1 = utils.karta_formularza([self.e_d, wiersz_przebiegu], "Przebieg i Data", ft.Icons.SPEED, domyslnie_otwarte=True, page=page)
        k2 = utils.karta_formularza(
            [self.e_stacja, self.e_l, self.e_k, self.c_pel, ft.Text("Przypisane tagi:", size=13, weight="bold"), self.k_tagi],
            "Szczegóły transakcji", ft.Icons.LOCAL_GAS_STATION
        )
        k3 = utils.karta_formularza([self.k_zalacznik], "Załącznik", ft.Icons.ATTACH_FILE)

        elementy = [k1, k2, k3, utils.przyciski_akcji(page, "✅ Zapisz tankowanie", self.zapisz, "/")]

        super().__init__(
            route=f"/tankowanie/edytuj/{t_id}" if t_id else "/tankowanie/nowe",
            padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO
        )

    def zapisz(self, e):
        for pole in (self.e_p, self.e_dys, self.e_l, self.e_k, self.e_stacja): pole.error_text = None
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

        wybrane_tagi = self.get_tagi()
        przygotowany = db.przygotuj_nowy_zalacznik(self.get_zalacznik())
        nowy_zalacznik = przygotowany if przygotowany is not None else self.zalacznik_val

        with db.polacz_baze() as conn:
            if self.t_id: 
                conn.execute("UPDATE tankowania SET data=?, przebieg=?, dystans=?, litry=?, kwota=?, do_pelna=?, stacja=?, zalacznik=?, tagi=? WHERE id=?", 
                             (self.e_d.value, prz, dys, lit, kwo, 1 if self.c_pel.value else 0, self.e_stacja.value, nowy_zalacznik, wybrane_tagi, self.t_id))
            else: 
                conn.execute("INSERT INTO tankowania (auto_id, data, przebieg, dystans, litry, kwota, do_pelna, stacja, zalacznik, tagi) VALUES (?,?,?,?,?,?,?,?,?,?)", 
                             (self.state.auto_id, self.e_d.value, prz, dys, lit, kwo, 1 if self.c_pel.value else 0, self.e_stacja.value, nowy_zalacznik, wybrane_tagi))
        db.zatwierdz_zalacznik(self.zalacznik_val, przygotowany)

        utils.przejdz(self._page, "/")
        utils.pokaz_komunikat(self._page, "Zapisano tankowanie!")


class FormularzInneView(ft.View):
    def __init__(self, page: ft.Page, state, i_id=None):
        self._page = page
        self.state = state
        self.i_id = i_id

        d_val, op_val, kw_val, tagi_val = datetime.now().strftime("%d.%m.%Y"), "", "", ""
        self.zalacznik_val = None
        if i_id:
            with db.polacz_baze() as conn:
                c = conn.cursor()
                c.execute("SELECT data, kategoria, nazwa, kwota, tagi, zalacznik FROM inne_koszty WHERE id=?", (i_id,))
                w = c.fetchone()
                if w: 
                    d_val, op_val, kw_val = str(w[0] or ""), str(w[2] or ""), str(w[3] or "")
                    tagi_val = str(w[4] or w[1] or "")
                    self.zalacznik_val = w[5]
        
        self.e_d = utils.pole_daty(page, "Data", d_val)
        
        self.k_tagi, self.get_tagi = utils.komponent_tagow(page, state, tagi_val)
        
        self.e_o = ft.TextField(label="Opis / Nazwa usługi", value=op_val, **utils.styl_pola(page=page))
        self.e_kw = ft.TextField(label=f"Kwota całkowita ({utils.symbol_waluty()})", value=kw_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))
        self.k_zalacznik, self.get_zalacznik = utils.komponent_zalacznika(page, self.zalacznik_val)

        appbar = utils.zbuduj_pasek_z_powrotem(page, "Edycja kosztu" if i_id else "Nowy koszt", "/", on_save=self.zapisz)
        k1 = utils.karta_formularza(
            [self.e_d, ft.Text("Przypisane tagi:", size=13, weight="bold"), self.k_tagi, self.e_o, self.e_kw], 
            "Szczegóły wydatku", ft.Icons.RECEIPT_LONG, domyslnie_otwarte=True, page=page
        )
        k2 = utils.karta_formularza([self.k_zalacznik], "Załącznik", ft.Icons.ATTACH_FILE)
        elementy = [k1, k2, utils.przyciski_akcji(page, "✅ Zapisz koszt", self.zapisz, "/")]

        super().__init__(
            route=f"/inne/edytuj/{i_id}" if i_id else "/inne/nowy",
            padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO
        )

    def zapisz(self, e):
        for pole in (self.e_o, self.e_kw): pole.error_text = None
        opis, kwo = (self.e_o.value or "").strip(), utils.parsuj_float(self.e_kw.value, 0.0)
        bledy = []
        if not opis: bledy.append((self.e_o, "Podaj opis"))
        if kwo <= 0: bledy.append((self.e_kw, "Podaj kwotę"))
        if bledy: return utils.pokaz_bledy_formularza(self._page, bledy)

        wybrane_tagi = self.get_tagi()
        przygotowany = db.przygotuj_nowy_zalacznik(self.get_zalacznik())
        nowy_zalacznik = przygotowany if przygotowany is not None else self.zalacznik_val

        with db.polacz_baze() as conn:
            if self.i_id: 
                conn.execute(
                    "UPDATE inne_koszty SET data=?, nazwa=?, kwota=?, tagi=?, zalacznik=? WHERE id=?", 
                    (self.e_d.value, opis, kwo, wybrane_tagi, nowy_zalacznik, self.i_id)
                )
            else: 
                conn.execute(
                    "INSERT INTO inne_koszty (auto_id, data, kategoria, nazwa, kwota, tagi, zalacznik) VALUES (?,?,?,?,?,?,?)", 
                    (self.state.auto_id, self.e_d.value, "", opis, kwo, wybrane_tagi, nowy_zalacznik)
                )
                
        db.zatwierdz_zalacznik(self.zalacznik_val, przygotowany)

        utils.przejdz(self._page, "/")
        utils.pokaz_komunikat(self._page, "Zapisano koszt z nowymi tagami!")

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
            label="🛞 Podzespół dotyczy opon / kół (pokaże wybór sezonu przy wpisach)",
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

        appbar = utils.zbuduj_pasek_z_powrotem(page, "Edycja podzespołu" if z_id else "Nowy podzespół", "/", on_save=self.zapisz)
        
        k1 = utils.karta_formularza([self.e_n, self.c_dotyczy_opon, self.c_dodaj_wymiane], "Śledzony podzespół", ft.Icons.HANDYMAN, domyslnie_otwarte=True, page=page)
        elementy = [k1, self.karta_wymiany, utils.przyciski_akcji(page, "✅ Zapisz podzespół", self.zapisz, "/")]

        super().__init__(
            route=f"/zadanie/edytuj/{z_id}" if z_id else "/zadanie/nowy",
            padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO
        )

    def zapisz(self, e):
        self.e_p.error_text = None
        self.e_c.error_text = None
        nazwa = (self.e_n.value or "").strip()
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
            c.execute("SELECT id FROM zadania WHERE auto_id=? AND LOWER(nazwa)=LOWER(?) AND id!=?", (self.state.auto_id, nazwa, self.z_id or 0))
            if c.fetchone():
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
                        "INSERT INTO historia (zadanie_id, data, przebieg, cena, wykonawca, kategoria, zalacznik) VALUES (?,?,?,?,?,?,?)", 
                        (nowe_z_id, self.e_d.value, prz, kos, wyk, kat, nowy_zalacznik)
                    )

        if not self.z_id and self.c_dodaj_wymiane.value:
            db.aktualizuj_najnowszy_wpis(nowe_z_id)

        utils.przejdz(self._page, "/")
        utils.pokaz_komunikat(self._page, "Zapisano podzespół i wpis!")


class FormularzInterwalView(ft.View):
    def __init__(self, page: ft.Page, state, z_id):
        self._page = page
        self.state = state
        self.z_id = z_id

        nazwa, ik, im = "", "", ""
        with db.polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT nazwa, interwal_km, interwal_miesiace FROM zadania WHERE id=?", (z_id,))
            w = c.fetchone()
            if w: nazwa, ik, im = str(w[0]), str(w[1] or ""), str(w[2] or "")

        self.e_ik = ft.TextField(label="Co ile kilometrów (np. 15000)", value=ik, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))
        self.e_im = ft.TextField(label="Co ile miesięcy (np. 12)", value=im, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))

        appbar = utils.zbuduj_pasek_z_powrotem(page, f"Interwał: {nazwa}", "/", on_save=self.zapisz)
        k1 = utils.karta_formularza([self.e_ik, self.e_im], "Odstępy między wymianami", ft.Icons.TIMER, domyslnie_otwarte=True, page=page)
        
        btn_czysc = ft.OutlinedButton("Wyczyść przypomnienia", on_click=self.usun_interwal, style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12), padding=15), width=float("inf"))
        
        elementy = [k1, btn_czysc, utils.przyciski_akcji(page, "✅ Zapisz interwał", self.zapisz, "/")]

        super().__init__(
            route=f"/interwal/{z_id}",
            padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO
        )

    def zapisz(self, e):
        self.e_ik.error_text = None
        self.e_im.error_text = None
        vk, vm = utils.parsuj_int(self.e_ik.value, None), utils.parsuj_int(self.e_im.value, None)
        if not vk and not vm: return utils.pokaz_bledy_formularza(self._page, [(self.e_ik, "Podaj wartość")])
        with db.polacz_baze() as conn: conn.execute("UPDATE zadania SET interwal_km=?, interwal_miesiace=? WHERE id=?", (vk, vm, self.z_id))
        utils.przejdz(self._page, "/")
        utils.pokaz_komunikat(self._page, "Zapisano interwały.")

    def usun_interwal(self, e):
        with db.polacz_baze() as conn: conn.execute("UPDATE zadania SET interwal_km=NULL, interwal_miesiace=NULL WHERE id=?", (self.z_id,))
        utils.przejdz(self._page, "/")
        utils.pokaz_komunikat(self._page, "Usunięto przypomnienie.")


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
        self.zalacznik_val = None  # <-- NOWE

        if h_id:
            with db.polacz_baze() as conn:
                c = conn.cursor()
                c.execute("SELECT data, przebieg, cena, wykonawca, kategoria, zalacznik FROM historia WHERE id=?", (h_id,))
                w = c.fetchone()
                if w:
                    d_val, p_val, c_val, w_val = str(w[0] or ""), str(w[1] or ""), str(w[2] or ""), str(w[3] or "")
                    if czy_opony and w[4]: kat_val = str(w[4])
                    self.zalacznik_val = w[5]  # <-- NOWE

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

        appbar = utils.zbuduj_pasek_z_powrotem(page, f"{'Edycja' if h_id else 'Nowa wymiana'}: {nazwa}", self.trasa_powrotu, on_save=self.zapisz)
        k1 = utils.karta_formularza([self.e_d, self.e_p, self.e_kat, self.e_c, self.k_wykonawca], "Informacje o serwisie", ft.Icons.BUILD, domyslnie_otwarte=True, page=page)
        k2 = utils.karta_formularza([self.k_zalacznik], "Załącznik (paragon / faktura)", ft.Icons.ATTACH_FILE)  # <-- NOWE
        
        elementy = [k1, k2, utils.przyciski_akcji(page, "✅ Zapisz wpis", self.zapisz, self.trasa_powrotu)]

        super().__init__(
            route=f"/wpis/edytuj/{h_id}" if h_id else f"/wpis/nowy/{self.z_id}",
            padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO
        )

    def zapisz(self, e):
        for pole in (self.e_p, self.e_c): pole.error_text = None
        prz, kos = utils.parsuj_int(self.e_p.value, 0), utils.parsuj_float(self.e_c.value, 0.0)
        bledy = []
        if not (self.e_p.value or "").strip() or prz < 0: bledy.append((self.e_p, "Błędny przebieg"))
        if kos < 0: bledy.append((self.e_c, "Błędny koszt"))
        if bledy: return utils.pokaz_bledy_formularza(self._page, bledy)

        # Pobieramy wykonawcę i jeśli wpisano z palca nową nazwę, zapisujemy ją do bazy
        wyk = self.get_wykonawca() or "Warsztat"
        if wyk and wyk != "Warsztat":
            db.dodaj_warsztat(self.state.auto_id, wyk)
            
        kat = self.e_kat.value if self.e_kat.visible else None

        if utils.sprawdz_podejrzany_przebieg(self._page, self.e_p, self.state.auto_id, prz, wyklucz_id=self.h_id, tabela="historia", nowa_data_str=self.e_d.value):
            return

        przygotowany = db.przygotuj_nowy_zalacznik(self.get_zalacznik())
        nowy_zalacznik = przygotowany if przygotowany is not None else self.zalacznik_val

        with db.polacz_baze() as conn:
            if self.h_id: 
                conn.execute("UPDATE historia SET data=?, przebieg=?, cena=?, wykonawca=?, kategoria=?, zalacznik=? WHERE id=?", (self.e_d.value, prz, kos, wyk, kat, nowy_zalacznik, self.h_id))
            else: 
                conn.execute("INSERT INTO historia (zadanie_id, data, przebieg, cena, wykonawca, kategoria, zalacznik) VALUES (?,?,?,?,?,?,?)", (self.z_id, self.e_d.value, prz, kos, wyk, kat, nowy_zalacznik))
        db.zatwierdz_zalacznik(self.zalacznik_val, przygotowany)

        db.aktualizuj_najnowszy_wpis(self.z_id)
        utils.przejdz(self._page, self.trasa_powrotu)
        utils.pokaz_komunikat(self._page, "Zapisano wpis!")

class FormularzWizytyView(ft.View):
    def __init__(self, page: ft.Page, state, w_id=None):
        self._page = page
        self.state = state
        self.w_id = w_id

        d_val, p_val, wyk_val, kosz_val, not_val, podpiete = datetime.now().strftime("%d.%m.%Y"), str(db.pobierz_aktualny_przebieg(self.state.auto_id) or ""), "", "", "", set()
        self.zalacznik_val = None
        tagi_val = ""
        kat_val = "Letnie"
        if w_id:
            with db.polacz_baze() as conn:
                c = conn.cursor()
                c.execute("SELECT data, przebieg, wykonawca, koszt_calkowity, notatki, zalacznik, tagi FROM wizyty WHERE id=?", (w_id,))
                w = c.fetchone()
                if w: 
                    d_val, p_val, wyk_val, kosz_val, not_val = str(w[0] or ""), str(w[1] or ""), str(w[2] or ""), str(w[3] or ""), str(w[4] or "")
                    self.zalacznik_val = w[5]
                    tagi_val = str(w[6] or "")
                c.execute("SELECT zadanie_id, kategoria FROM historia WHERE wizyta_id=?", (w_id,))
                dane_h = c.fetchall()
                podpiete = {r[0] for r in dane_h}
                for r in dane_h:
                    if r[1]: kat_val = str(r[1])

        self.e_d = utils.pole_daty(page, "Data odebrania z warsztatu", d_val)
        self.e_p = ft.TextField(label="Przebieg podczas wizyty (km)", value=p_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))
        self.k_wykonawca, self.get_wykonawca = utils.komponent_wyboru_warsztatu(page, state, wyk_val)
        self.e_k = ft.TextField(label=f"Całkowity koszt naprawy ({utils.symbol_waluty()})", value=kosz_val, keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))
        self.e_n = ft.TextField(label="Notatki i uwagi", value=not_val, multiline=True, min_lines=2, max_lines=4, **utils.styl_pola(page=page))
        self.k_zalacznik, self.get_zalacznik = utils.komponent_zalacznika(page, self.zalacznik_val)
        self.k_tagi, self.get_tagi = utils.komponent_tagow(page, state, tagi_val)
        self.blad_czesci = ft.Text("", color=ft.Colors.RED_700, size=13)

        self.chk_czesci = []
        self.zadania_opon_ids = set()
        
        def odswiez_widocznosc_opon(e=None):
            czy_zaznaczono_opony = any(chk.value for chk in self.chk_czesci if chk.data in self.zadania_opon_ids)
            self.e_kat_wizyty.visible = czy_zaznaczono_opony
            self.e_kat_wizyty.update()

        self._odswiez_widocznosc_opon = odswiez_widocznosc_opon

        with db.polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT id, nazwa, dotyczy_opon FROM zadania WHERE auto_id=? ORDER BY nazwa", (self.state.auto_id,))
            for z_i, z_n, z_opon in c.fetchall():
                chk = ft.Checkbox(label=str(z_n), value=(z_i in podpiete), data=z_i, on_change=odswiez_widocznosc_opon)
                self.chk_czesci.append(chk)
                if z_opon:
                    self.zadania_opon_ids.add(z_i)

        self.btn_pakiety = self._zbuduj_przycisk_pakietow()

        czy_na_start_opony = any(z_i in podpiete for z_i in self.zadania_opon_ids)
                    
        self.e_kat_wizyty = ft.Dropdown(
            label="Rodzaj opon",
            options=[ft.DropdownOption(key=k, text=k) for k in ("Letnie", "Zimowe", "Całoroczne")],
            value=kat_val,
            visible=czy_na_start_opony,
            **utils.styl_dropdown()
        )

        poprzednio_uzyte = dict(db.pobierz_uzyte_czesci_wizyty(w_id)) if w_id else {}
        with db.polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT id, nazwa, ilosc, jednostka FROM magazyn_czesci WHERE auto_id=? ORDER BY nazwa", (self.state.auto_id,))
            wszystkie_czesci_magazynu = c.fetchall()

        self.magazyn_kontrolki = []
        wiersze_magazynu = []
        for m_id, m_nazwa, m_ilosc, m_jedn in wszystkie_czesci_magazynu:
            juz_uzyto = float(poprzednio_uzyte.get(m_id, 0) or 0)
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

        appbar = utils.zbuduj_pasek_z_powrotem(page, "Edycja wizyty" if w_id else "Nowa wizyta zbiorcza", "/wizyty", on_save=self.zapisz)
        
        k1 = utils.karta_formularza(
            [self.e_d, self.e_p, self.k_wykonawca, self.e_k, self.e_n, ft.Text("Przypisane tagi:", size=13, weight="bold"), self.k_tagi],
            "Ogólne informacje", ft.Icons.HOME_REPAIR_SERVICE, domyslnie_otwarte=True, page=page
        )
        k1b = utils.karta_formularza([self.k_zalacznik], "Załącznik (paragon / zdjęcie)", ft.Icons.ATTACH_FILE)
        k2 = utils.karta_formularza([self.btn_pakiety, ft.Column(self.chk_czesci, spacing=2), self.blad_czesci, self.e_kat_wizyty], "Zaznacz wymienione podzespoły", ft.Icons.CHECKLIST)
        elementy = [k1, k1b, k2]

        if self.magazyn_kontrolki:
            k3 = utils.karta_formularza(
                [self.c_uzyj_magazynu, self.magazyn_lista_kontener],
                "Magazyn części", ft.Icons.INVENTORY_2
            )
            elementy.append(k3)

        elementy.append(utils.przyciski_akcji(page, "✅ Zapisz wizytę", self.zapisz, "/wizyty"))

        super().__init__(
            route=f"/wizyty/edytuj/{w_id}" if w_id else "/wizyty/nowa",
            padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO
        )

    def _zbuduj_przycisk_pakietow(self):
        return ft.PopupMenuButton(
            items=self._zbuduj_pozycje_menu_pakietow(),
            content=ft.Container(
                padding=ft.Padding(12, 8, 12, 8),
                border_radius=10,
                bgcolor=ft.Colors.with_opacity(0.1, ft.Colors.PRIMARY),
                content=ft.Row([
                    ft.Icon(ft.Icons.PLAYLIST_ADD_CHECK, size=16, color=ft.Colors.PRIMARY),
                    ft.Text("Zastosuj pakiet serwisowy", size=12, weight="bold", color=ft.Colors.PRIMARY)
                ], spacing=6, tight=True)
            ),
            tooltip="Zaznacz od razu kilka podzespołów naraz"
        )

    def _zbuduj_pozycje_menu_pakietow(self):
        items = []

        for nazwa_pakietu, pozycje in db.PAKIETY_SERWISOWE.items():
            items.append(
                ft.PopupMenuItem(
                    content=ft.Column([
                        ft.Text(nazwa_pakietu, weight="bold"),
                        ft.Text(", ".join(pozycje), size=11, color=ft.Colors.ON_SURFACE_VARIANT)
                    ], spacing=0, tight=True),
                    on_click=lambda e, nz=nazwa_pakietu, poz=pozycje: self._zastosuj_pakiet(nz, poz)
                )
            )

        pakiety_wlasne = db.pobierz_pakiety_wlasne(self.state.auto_id)
        if pakiety_wlasne:
            items.append(ft.PopupMenuItem(content=ft.Divider(height=1)))
            for p_id, nazwa_pakietu, pozycje in pakiety_wlasne:
                items.append(
                    ft.PopupMenuItem(
                        content=ft.Column([
                            ft.Row([
                                ft.Icon(ft.Icons.BOOKMARK, size=14, color=ft.Colors.TEAL_700),
                                ft.Text(nazwa_pakietu, weight="bold")
                            ], spacing=4, tight=True),
                            ft.Text(", ".join(pozycje) or "Pusty pakiet", size=11, color=ft.Colors.ON_SURFACE_VARIANT)
                        ], spacing=0, tight=True),
                        on_click=lambda e, nz=nazwa_pakietu, poz=pozycje: self._zastosuj_pakiet(nz, poz)
                    )
                )

        items.append(ft.PopupMenuItem(content=ft.Divider(height=1)))
        items.append(
            ft.PopupMenuItem(
                content=ft.Row([
                    ft.Icon(ft.Icons.ADD_CIRCLE_OUTLINE, size=16, color=ft.Colors.GREEN_700),
                    ft.Text("Zapisz obecne zaznaczenie jako pakiet", color=ft.Colors.GREEN_700)
                ], spacing=6),
                on_click=lambda e: self._okno_nowego_pakietu()
            )
        )
        if pakiety_wlasne:
            items.append(
                ft.PopupMenuItem(
                    content=ft.Row([
                        ft.Icon(ft.Icons.DELETE_SWEEP, size=16, color=ft.Colors.RED_700),
                        ft.Text("Zarządzaj własnymi pakietami", color=ft.Colors.RED_700)
                    ], spacing=6),
                    on_click=lambda e: self._okno_zarzadzania_pakietami()
                )
            )

        return items

    def _odswiez_przycisk_pakietow(self):
        self.btn_pakiety.items = self._zbuduj_pozycje_menu_pakietow()
        try:
            self.btn_pakiety.update()
        except Exception:
            pass

    def _zastosuj_pakiet(self, nazwa_pakietu, pozycje_pakietu):
        # Odznacz to, co zaznaczył POPRZEDNIO zastosowany pakiet, a nie jest
        # częścią nowego — inaczej przełączanie między pakietami zostawiało
        # "resztki" zaznaczeń z wcześniejszego wyboru.
        poprzednie = getattr(self, "_ostatni_pakiet_pozycje", [])
        for chk in self.chk_czesci:
            if chk.label in pozycje_pakietu:
                if not chk.value:
                    chk.value = True
                    chk.update()
            elif chk.label in poprzednie:
                if chk.value:
                    chk.value = False
                    chk.update()

        self._ostatni_pakiet_pozycje = list(pozycje_pakietu)
        self._odswiez_widocznosc_opon()

        dopasowane = sum(1 for chk in self.chk_czesci if chk.label in pozycje_pakietu)
        if dopasowane:
            utils.pokaz_komunikat(self._page, f"Zastosowano pakiet „{nazwa_pakietu}” ({dopasowane}/{len(pozycje_pakietu)} pozycji).")
        else:
            utils.pokaz_komunikat(self._page, "Żadna pozycja z pakietu nie pasuje do Twoich podzespołów — dodaj je najpierw w sekcji Serwis.", ft.Colors.ORANGE_700)

    def _okno_nowego_pakietu(self):
        zaznaczone_teraz = [chk.label for chk in self.chk_czesci if chk.value]
        if not zaznaczone_teraz:
            utils.pokaz_komunikat(self._page, "Najpierw zaznacz podzespoły, które mają wejść w skład pakietu.", ft.Colors.ORANGE_700)
            return

        e_nazwa = ft.TextField(label="Nazwa pakietu", hint_text="np. Przegląd zimowy", **utils.styl_pola())
        podglad = ft.Text(", ".join(zaznaczone_teraz), size=12, color=ft.Colors.ON_SURFACE_VARIANT)

        def zapisz(e):
            e_nazwa.error_text = None
            nazwa = (e_nazwa.value or "").strip()
            if not nazwa:
                e_nazwa.error_text = "Podaj nazwę"
                e_nazwa.update()
                return
            db.dodaj_pakiet_wlasny(self.state.auto_id, nazwa, zaznaczone_teraz)
            utils.zamknij_dialog(self._page, dlg)
            self._odswiez_przycisk_pakietow()
            utils.pokaz_komunikat(self._page, f"Zapisano pakiet „{nazwa}”.")

        dlg = ft.AlertDialog(
            title=ft.Text("Nowy pakiet serwisowy", weight="bold"),
            content=ft.Column([
                ft.Text("Pakiet zapisze dokładnie te podzespoły, które są teraz zaznaczone:", size=12),
                podglad,
                e_nazwa,
            ], tight=True, spacing=10),
            actions=[
                ft.TextButton("Anuluj", on_click=lambda e: utils.zamknij_dialog(self._page, dlg)),
                ft.ElevatedButton("Zapisz", on_click=zapisz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY)
            ]
        )
        utils.otworz_dialog(self._page, dlg)

    def _okno_zarzadzania_pakietami(self):
        pakiety_wlasne = db.pobierz_pakiety_wlasne(self.state.auto_id)

        def usun(p_id, nazwa):
            def wykonaj():
                db.usun_pakiet_wlasny(p_id)
                utils.zamknij_dialog(self._page, dlg)
                self._odswiez_przycisk_pakietow()
                utils.pokaz_komunikat(self._page, f"Usunięto pakiet „{nazwa}”.")
            utils.potwierdz(self._page, "Usunąć pakiet?", f"Czy na pewno usunąć pakiet „{nazwa}”?", wykonaj)

        wiersze = [
            ft.ListTile(
                leading=ft.Icon(ft.Icons.BOOKMARK, color=ft.Colors.TEAL_700),
                title=ft.Text(nazwa, weight="bold"),
                subtitle=ft.Text(", ".join(pozycje) or "Pusty pakiet", size=11),
                trailing=ft.IconButton(ft.Icons.DELETE, icon_color=ft.Colors.RED_700, on_click=lambda e, pid=p_id, n=nazwa: usun(pid, n))
            )
            for p_id, nazwa, pozycje in pakiety_wlasne
        ]

        dlg = ft.AlertDialog(
            title=ft.Text("Własne pakiety serwisowe", weight="bold"),
            content=ft.Column(wiersze, tight=True, spacing=2, scroll=ft.ScrollMode.AUTO) if wiersze else ft.Text("Brak zapisanych pakietów.", italic=True),
            actions=[ft.TextButton("Zamknij", on_click=lambda e: utils.zamknij_dialog(self._page, dlg))]
        )
        utils.otworz_dialog(self._page, dlg)

    def zapisz(self, e):
        self.e_p.error_text = None
        self.e_k.error_text = None
        prz, kos = utils.parsuj_int(self.e_p.value, 0), utils.parsuj_float(self.e_k.value, 0.0)
        bledy = []
        if not (self.e_p.value or "").strip(): bledy.append((self.e_p, "Wymagane"))
        if kos < 0: bledy.append((self.e_k, "Wymagane"))
        
        wybrane = [chk.data for chk in self.chk_czesci if chk.value]
        self.blad_czesci.value = "Zaznacz co najmniej jedną część!" if not wybrane else ""

        nowe_uzyte = []
        for chk, pole_ilosc, poz in self.magazyn_kontrolki:
            pole_ilosc.error_text = None
            if self.c_uzyj_magazynu.value and chk.value:
                ilosc = utils.parsuj_float(pole_ilosc.value, None)
                if ilosc is None or ilosc <= 0 or ilosc > poz["dostepna"] + 1e-9:
                    pole_ilosc.error_text = f"Maks. {utils.formatuj_liczba(poz['dostepna'], 2)}"
                else:
                    nowe_uzyte.append((poz["id"], ilosc))

        blad_magazynu = any(pole.error_text for _, pole, _ in self.magazyn_kontrolki)

        if bledy or self.blad_czesci.value or blad_magazynu:
            self._page.update()
            if bledy:
                utils.pokaz_bledy_formularza(self._page, bledy)
            elif blad_magazynu:
                utils.pokaz_komunikat(self._page, "Sprawdź ilości wykorzystanych części z magazynu.", ft.Colors.RED_700)
            elif self.blad_czesci.value:
                utils.pokaz_komunikat(self._page, "Zaznacz co najmniej jedną część z listy!", ft.Colors.RED_700)
            return

        if utils.sprawdz_podejrzany_przebieg(self._page, self.e_p, self.state.auto_id, prz, wyklucz_id=self.w_id, tabela="wizyty", nowa_data_str=self.e_d.value):
            return

        # ZAPIS NOWEGO WARSZTATU
        wyk = self.get_wykonawca() or "Warsztat"
        if wyk and wyk != "Warsztat":
            db.dodaj_warsztat(self.state.auto_id, wyk)
            
        wybrane_tagi = self.get_tagi()
        przygotowany = db.przygotuj_nowy_zalacznik(self.get_zalacznik())
        nowy_zalacznik = przygotowany if przygotowany is not None else self.zalacznik_val
        with db.polacz_baze() as conn:
            cur = conn.cursor()
            if self.w_id:
                cur.execute("UPDATE wizyty SET data=?, przebieg=?, wykonawca=?, koszt_calkowity=?, notatki=?, zalacznik=?, tagi=? WHERE id=?", (self.e_d.value, prz, wyk, kos, self.e_n.value, nowy_zalacznik, wybrane_tagi, self.w_id))
                cur.execute("DELETE FROM historia WHERE wizyta_id=?", (self.w_id,))
                for zid in wybrane: 
                    kat = self.e_kat_wizyty.value if zid in self.zadania_opon_ids else None
                    cur.execute("INSERT INTO historia (wizyta_id, zadanie_id, data, przebieg, cena, wykonawca, kategoria) VALUES (?,?,?,?,0,?,?)", (self.w_id, zid, self.e_d.value, prz, wyk, kat))
                wizyta_id = self.w_id
                db.przywroc_czesci_wizyty(wizyta_id, conn=conn)
            else:
                cur.execute("INSERT INTO wizyty (auto_id, data, przebieg, wykonawca, koszt_calkowity, notatki, zalacznik, tagi) VALUES (?,?,?,?,?,?,?,?)", (self.state.auto_id, self.e_d.value, prz, wyk, kos, self.e_n.value, nowy_zalacznik, wybrane_tagi))
                wizyta_id = cur.lastrowid
                for zid in wybrane: 
                    kat = self.e_kat_wizyty.value if zid in self.zadania_opon_ids else None
                    cur.execute("INSERT INTO historia (wizyta_id, zadanie_id, data, przebieg, cena, wykonawca, kategoria) VALUES (?,?,?,?,0,?,?)", (wizyta_id, zid, self.e_d.value, prz, wyk, kat))
 
            db.rozlicz_czesci_z_magazynu(wizyta_id, nowe_uzyte, conn=conn)
        db.zatwierdz_zalacznik(self.zalacznik_val, przygotowany)

        db.przelicz_wszystkie_zadania(self.state.auto_id)
        utils.przejdz(self._page, "/wizyty")
        utils.pokaz_komunikat(self._page, "Zapisano wizytę!")