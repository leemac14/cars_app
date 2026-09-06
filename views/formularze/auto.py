"""Formularz pojazdu: dane techniczne, terminy dokumentów i zdjęcie."""

import asyncio
import db
import flet as ft
import sqlite3
import utils
from datetime import datetime

from .vin import dekoduj_wmi_lokalnie, pobierz_dane_vin, rok_produkcji_z_vin


class FormularzAutoView(ft.View):
    def __init__(self, page: ft.Page, state, auto_id=None):
        self._page = page
        self.state = state
        self.auto_id = auto_id
        
        n_val, r_val, v_val, ro_val, oc_val, pt_val = "", "", "", "", "", ""
        m_val, mod_val, gen_val = "", "", ""
        poj_val, moc_val, pal_val, skrz_val, not_val = "", "", "Benzyna", "Manualna", ""
        nadw_val = ""
        bat_val, zas_val, bak_val = "", "", ""
        wp_val, wt_val, cp_val, ct_val = "", "", "", ""
        ot_val, op_val, akum_val, zm_val, zd_val = "", "", "", "", ""
        ac_val, asy_val, gas_val, apt_val = "", "", "", ""
        gw_val, gwp_val = "", ""
        # Dane z wersji 37: zakup i wartość, ubezpieczenie, rozszerzona ściągawka.
        dz_val, cz_val, pz_val, ws_val = "", "", "", ""
        ub_val, pol_val, skl_val, tel_val = "", "", "", ""
        lak_val, opon_val, felg_val, srub_val, mom_val, zlacze_val = "", "", "", "", "", ""
        pierwsza_rej_val = ""
        self.zg_val = None
        self.kolor_auta_val = None
        
        if auto_id:
            with db.polacz_baze() as c:
                c.row_factory = sqlite3.Row
                cur = c.cursor()
                # SELECT * zamiast wyliczanki kolumn: przy 50 polach każda nowa
                # migracja oznaczała dopisanie nazwy w trzech miejscach tego pliku
                # i cichy błąd, gdy się o którymś zapomniało.
                cur.execute("SELECT * FROM samochody WHERE id=?", (auto_id,))
                w = cur.fetchone()
                if w: 
                    n_val, r_val, v_val, ro_val = str(w["nazwa"] or ""), str(w["nr_rej"] or ""), str(w["vin"] or ""), str(w["rok_produkcji"] or "")
                    oc_val, pt_val = str(w["oc_data"] or ""), str(w["przeglad_data"] or "")
                    poj_val, moc_val = str(w["pojemnosc_silnika"] or ""), str(w["moc_silnika"] or "")
                    pal_val, skrz_val, not_val = str(w["typ_paliwa"] or "Benzyna"), str(w["skrzynia_biegow"] or "Manualna"), str(w["notatki"] or "")
                    nadw_val = str(w["nadwozie"] or "")
                    bat_val = str(w["pojemnosc_baterii"] or "")
                    zas_val = str(w["zasieg_ev"] or "")
                    bak_val = str(w["pojemnosc_baku"] or "")
                    dz_val = str(w["data_zakupu"] or "")
                    cz_val = utils.formatuj_liczba(w["cena_zakupu"], 0) if w["cena_zakupu"] else ""
                    pz_val = str(w["przebieg_zakupu"] or "")
                    ws_val = utils.formatuj_liczba(w["wartosc_szacowana"], 0) if w["wartosc_szacowana"] else ""
                    ub_val = str(w["ubezpieczyciel"] or "")
                    pol_val = str(w["nr_polisy"] or "")
                    skl_val = utils.formatuj_liczba(w["skladka_roczna"], 0) if w["skladka_roczna"] else ""
                    tel_val = str(w["telefon_assistance"] or "")
                    lak_val = str(w["kod_lakieru"] or "")
                    opon_val = str(w["rozmiar_opon"] or "")
                    felg_val = str(w["rozmiar_felg"] or "")
                    srub_val = str(w["rozstaw_srub"] or "")
                    mom_val = str(w["moment_dokrecania"] or "")
                    zlacze_val = str(w["typ_zlacza_ev"] or "")
                    pierwsza_rej_val = str(w["data_pierwszej_rejestracji"] or "")
                    wp_val, wt_val = str(w["wycieraczki_przod"] or ""), str(w["wycieraczki_tyl"] or "")
                    cp_val, ct_val = str(w["cisnienie_przod"] or ""), str(w["cisnienie_tyl"] or "")
                    ot_val, op_val = str(w["olej_typ"] or ""), str(w["olej_pojemnosc"] or "")
                    akum_val, zm_val, zd_val = str(w["akumulator"] or ""), str(w["zarowki_mijania"] or ""), str(w["zarowki_drogowe"] or "")
                    ac_val, asy_val = str(w["ac_data"] or ""), str(w["assistance_data"] or "")
                    gas_val, apt_val = str(w["gasnica_data"] or ""), str(w["apteczka_data"] or "")
                    gw_val, gwp_val = str(w["gwarancja_data"] or ""), str(w["gwarancja_przebieg"] or "")
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

        self.k_zdjecie, self.get_zdjecie = utils.komponent_zalacznika(page, self.zg_val, tylko_zdjecie=True)
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
        self.e_pal = ft.Dropdown(label="Typ paliwa", options=[ft.DropdownOption(key=x, text=x) for x in db.TYPY_PALIWA], value=pal_val, **utils.styl_dropdown())
        self.e_skrz = ft.Dropdown(label="Skrzynia biegów", options=[ft.DropdownOption(key=x, text=x) for x in ["Manualna", "Automatyczna"]], value=skrz_val, **utils.styl_dropdown())
        # Nadwozie służy przede wszystkim ODZNACE w selektorze pojazdów: sylwetka
        # w kolorze auta pozwala rozpoznać je bez czytania nazwy. Puste = ogólna
        # ikona samochodu, więc pole jest w pełni opcjonalne.
        # Bateria i zasięg mają sens tylko przy napędzie z prądem — przy diesla
        # byłyby dwoma pustymi polami do przewinięcia.
        def czy_naped_z_pradem(typ):
            return typ in db.TYPY_PALIWA_ELEKTRYCZNE or typ in db.TYPY_PALIWA_DWUZRODLOWE

        # Bak to odpowiednik baterii dla spalinowego: z pojemności i rzeczywistego
        # zużycia liczy się zasięg. Przy elektryku ukryty, bo nie ma czego tankować;
        # przy hybrydzie plug-in widoczny RAZEM z baterią — takie auto ma oba.
        def czy_naped_z_paliwem(typ):
            return typ not in db.TYPY_PALIWA_ELEKTRYCZNE

        self.e_bak = ft.TextField(
            label="Pojemność baku (l)", value=bak_val, hint_text="np. 55",
            keyboard_type=ft.KeyboardType.NUMBER, visible=czy_naped_z_paliwem(pal_val), **utils.styl_pola(page=page)
        )
        self.info_bak = ft.Text(
            "Z pojemności baku i Twojego rzeczywistego spalania aplikacja policzy zasięg — "
            "na pełnym baku i ten pozostały od ostatniego tankowania do pełna.",
            size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT,
            visible=czy_naped_z_paliwem(pal_val),
        )

        self.e_bateria = ft.TextField(
            label="Pojemność baterii (kWh)", value=bat_val, hint_text="np. 52",
            keyboard_type=ft.KeyboardType.NUMBER, visible=czy_naped_z_pradem(pal_val), **utils.styl_pola(page=page)
        )
        self.e_zasieg = ft.TextField(
            label="Deklarowany zasięg EV (km)", value=zas_val, hint_text="np. 380 (WLTP)",
            keyboard_type=ft.KeyboardType.NUMBER, visible=czy_naped_z_pradem(pal_val), **utils.styl_pola(page=page)
        )
        self.info_bateria = ft.Text(
            "Z pojemności i Twojego RZECZYWISTEGO zużycia aplikacja policzy realny "
            "zasięg — zwykle sporo niższy niż katalogowy.",
            size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT,
            visible=czy_naped_z_pradem(pal_val),
        )

        self.podglad_odznaki = ft.Row(spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        def odswiez_podglad_odznaki(e=None):
            """Odznaka jest po to, żeby rozpoznać auto na liście — więc pokazujemy
            od razu, jak będzie wyglądać, zamiast kazać wracać do selektora."""
            wybrane = self.e_nadwozie.value or None
            self.podglad_odznaki.controls = [
                utils.odznaka_pojazdu(
                    {"nadwozie": wybrane, "kolor_motywu": self.get_kolor()},
                    rozmiar=40,
                ),
                ft.Text(
                    "Tak pojazd będzie oznaczony na liście wyboru"
                    + ("" if wybrane else " (bez typu nadwozia — ogólna ikona)"),
                    size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT, expand=True,
                ),
            ]
            try:
                self.podglad_odznaki.update()
            except Exception:
                pass

        self.e_nadwozie = ft.Dropdown(
            label="Typ nadwozia",
            options=[ft.DropdownOption(key="", text="— nie podano —")]
                    + [ft.DropdownOption(key=x, text=x) for x in db.TYPY_NADWOZIA],
            value=nadw_val if nadw_val in db.TYPY_NADWOZIA else "",
            on_select=odswiez_podglad_odznaki,
            **utils.styl_dropdown()
        )
        odswiez_podglad_odznaki()
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
        # --- Zakup i wartość ---
        self.e_data_zakupu = utils.pole_daty(page, "Data zakupu", dz_val)
        self.e_cena_zakupu = ft.TextField(
            label=f"Cena zakupu ({utils.symbol_waluty()})", value=cz_val, hint_text="np. 42000",
            keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))
        self.e_przebieg_zakupu = ft.TextField(
            label="Przebieg przy zakupie (km)", value=pz_val, hint_text="np. 98000",
            keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))
        self.e_wartosc = ft.TextField(
            label=f"Szacowana wartość dziś ({utils.symbol_waluty()})", value=ws_val,
            hint_text="np. 33000", keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))
        self.info_zakup = ft.Text(
            "Z ceny zakupu i dzisiejszej wartości policzę utratę wartości — zwykle "
            "największy koszt auta, którego nie widać w żadnym wpisie. Wartość warto "
            "odświeżać raz na jakiś czas.",
            size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT)

        # --- Ubezpieczenie i pomoc ---
        self.e_ubezpieczyciel = ft.TextField(
            label="Ubezpieczyciel", value=ub_val, hint_text="np. PZU, Warta, Link4",
            **utils.styl_pola(page=page))
        self.e_polisa = ft.TextField(
            label="Numer polisy", value=pol_val, **utils.styl_pola(page=page))
        self.e_skladka = ft.TextField(
            label=f"Składka roczna ({utils.symbol_waluty()})", value=skl_val,
            keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))
        self.e_assistance = ft.TextField(
            label="Telefon do assistance", value=tel_val, hint_text="np. 801 102 102",
            keyboard_type=ft.KeyboardType.PHONE, **utils.styl_pola(page=page))

        # --- Ściągawka: rzeczy, których szuka się w sklepie i przy kołach ---
        self.e_lakier = ft.TextField(
            label="Kod lakieru", value=lak_val, hint_text="np. Z20R / LY9B",
            **utils.styl_pola(page=page))
        self.e_opony = ft.TextField(
            label="Rozmiar opon", value=opon_val, hint_text="np. 205/55 R16",
            **utils.styl_pola(page=page))
        self.e_felgi = ft.TextField(
            label="Felgi", value=felg_val, hint_text="np. 6.5Jx16 ET40",
            **utils.styl_pola(page=page))
        self.e_srub = ft.TextField(
            label="Rozstaw śrub", value=srub_val, hint_text="np. 5x115",
            **utils.styl_pola(page=page))
        self.e_moment = ft.TextField(
            label="Moment dokręcania kół", value=mom_val, hint_text="np. 110 Nm",
            **utils.styl_pola(page=page))
        self.e_zlacze = ft.TextField(
            label="Typ złącza ładowania", value=zlacze_val, hint_text="np. Type 2 / CCS",
            visible=czy_naped_z_pradem(pal_val), **utils.styl_pola(page=page))

        self.e_pierwsza_rej = utils.pole_daty(page, "Pierwsza rejestracja", pierwsza_rej_val)
        self.e_gw = utils.pole_daty(page, "Gwarancja producenta (do)", gw_val)
        self.e_gwp = ft.TextField(label="Gwarancja — limit przebiegu (km)", value=gwp_val, hint_text="np. 150000", keyboard_type=ft.KeyboardType.NUMBER, **utils.styl_pola(page=page))

        self._stan_poczatkowy = self._migawka_formularza()
        appbar = utils.zbuduj_pasek_z_powrotem(page, "Edycja pojazdu" if auto_id else "Nowy pojazd", "/", on_save=self.zapisz, czy_zmieniono=self._czy_zmieniono)

        wiersz_auto = ft.Row([ft.Container(self.e_marka, expand=True), ft.Container(self.e_model, expand=True)], spacing=10)
        wiersz_wycieraczki = ft.Row([ft.Container(self.e_wp, expand=True), ft.Container(self.e_wt, expand=True)], spacing=10)
        wiersz_cisnienie = ft.Row([ft.Container(self.e_cp, expand=True), ft.Container(self.e_ct, expand=True)], spacing=10)
        wiersz_olej = ft.Row([ft.Container(self.e_ot, expand=True), ft.Container(self.e_op, expand=True)], spacing=10)
        wiersz_zarowki = ft.Row([ft.Container(self.e_zm, expand=True), ft.Container(self.e_zd, expand=True)], spacing=10)
        wiersz_opon = ft.Row([ft.Container(self.e_opony, expand=True), ft.Container(self.e_felgi, expand=True)], spacing=10)
        wiersz_srub = ft.Row([ft.Container(self.e_srub, expand=True), ft.Container(self.e_moment, expand=True)], spacing=10)
        wiersz_zakup = ft.Row([ft.Container(self.e_cena_zakupu, expand=True), ft.Container(self.e_przebieg_zakupu, expand=True)], spacing=10)
        
        k0 = utils.karta_formularza([self.k_zdjecie], "Zdjęcie profilowe", ft.Icons.ADD_A_PHOTO, domyslnie_otwarte=True)
        # Zastąpiono pojedyncze pole e_nazwa rzędem i polem generacji
        k1 = utils.karta_formularza([wiersz_auto, self.e_generacja, self.e_rej, self.e_vin, self.e_rok, self.e_przebieg], "Dane identyfikacyjne", ft.Icons.DIRECTIONS_CAR, domyslnie_otwarte=True, page=page)
        kk = utils.karta_formularza(
            [ft.Text("Ten kolor będzie używany w całym interfejsie, gdy ten pojazd jest aktywny.", size=11, italic=True, color=ft.Colors.ON_SURFACE_VARIANT), self.k_kolor],
            "Kolor interfejsu dla tego pojazdu", ft.Icons.PALETTE
        )
        def na_zmiane_paliwa(e=None):
            widoczne = czy_naped_z_pradem(self.e_pal.value)
            for kontrolka in (self.e_bateria, self.e_zasieg, self.info_bateria, self.e_zlacze):
                kontrolka.visible = widoczne
            widoczne_paliwo = czy_naped_z_paliwem(self.e_pal.value)
            for kontrolka in (self.e_bak, self.info_bak):
                kontrolka.visible = widoczne_paliwo
            try:
                self._page.update()
            except Exception:
                pass

        self.e_pal.on_select = na_zmiane_paliwa

        k2 = utils.karta_formularza(
            [self.e_pal, self.e_skrz, self.e_nadwozie, self.podglad_odznaki,
             self.e_poj, self.e_moc, self.e_bak, self.info_bak,
             self.e_bateria, self.e_zasieg, self.info_bateria, self.e_zlacze],
            "Specyfikacja techniczna", ft.Icons.SETTINGS
        )
        k3 = utils.karta_formularza([self.e_pierwsza_rej, self.e_oc, self.e_pt],
                                    "Ważne daty", ft.Icons.CALENDAR_MONTH)
        k5 = utils.karta_formularza(
            [wiersz_wycieraczki, wiersz_cisnienie, wiersz_olej, self.e_akum, wiersz_zarowki,
             self.e_lakier, wiersz_opon, wiersz_srub],
            "Ściągawka do sklepu", ft.Icons.SHOPPING_CART)
        k6 = utils.karta_formularza([self.e_ac, self.e_asy, self.e_gas, self.e_apt, self.e_gw, self.e_gwp], "Dodatkowe polisy, gwarancja i BHP", ft.Icons.SHIELD)
        k7 = utils.karta_formularza(
            [self.e_data_zakupu, wiersz_zakup, self.e_wartosc, self.info_zakup],
            "Zakup i wartość", ft.Icons.SELL,
            domyslnie_otwarte=bool(dz_val or cz_val), page=page)
        k8 = utils.karta_formularza(
            [self.e_ubezpieczyciel, self.e_polisa, self.e_skladka, self.e_assistance],
            "Ubezpieczenie i pomoc", ft.Icons.SUPPORT_AGENT,
            domyslnie_otwarte=bool(ub_val or tel_val), page=page)
        k4 = utils.karta_formularza([self.e_not], "Uwagi", ft.Icons.NOTES)
        
        elementy = [k0, k1, kk, k2, k3, k7, k8, k5, k6, k4, utils.przyciski_akcji(page, "Zapisz pojazd", self.zapisz, "/")]
        super().__init__(route=f"/auto/edytuj/{auto_id}" if auto_id else "/auto/nowy", padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO)

    async def rozkoduj_vin(self, e):
        vin = (self.e_vin.value or "").strip().upper()

        if not vin or len(vin) != 17:
            utils.ustaw_blad(self.e_vin, "Wpisz pełny, 17-znakowy numer VIN")
            self._page.update()
            utils.pokaz_komunikat(self._page, "VIN jest pusty albo ma nieprawidłową długość (wymagane dokładnie 17 znaków).", ft.Colors.RED_700)
            return

        utils.ustaw_blad(self.e_vin)
        self.btn_dekoduj_vin.icon = ft.Icons.HOURGLASS_TOP
        self.btn_dekoduj_vin.disabled = True
        self._page.update()

        # --- KROK 1: rozpoznanie lokalne, offline, po samym WMI — działa dla
        # każdego regionu świata, w tym modeli sprzedawanych tylko w Europie. ---
        marka_lokalna, region = dekoduj_wmi_lokalnie(vin)
        rok_lokalny = rok_produkcji_z_vin(vin)

        if marka_lokalna:
            self.e_marka.value = marka_lokalna
        if rok_lokalny:
            self.e_rok.value = str(rok_lokalny)

        # --- KROK 2: próba wzbogacenia (model, silnik, moc, paliwo, skrzynia)
        # przez darmowe API NHTSA — TRAKTOWANA JAKO BONUS. Jej brak/błąd nie
        # jest już porażką całej operacji, bo krok 1 i tak dał markę i rok. ---
        try:
            dane = await asyncio.to_thread(pobierz_dane_vin, vin)
        except Exception:
            dane = {}

        self.btn_dekoduj_vin.icon = ft.Icons.AUTO_AWESOME
        self.btn_dekoduj_vin.disabled = False

        wzbogacono_api = False

        marka_api = (dane.get("Make") or "").strip()
        if marka_api:
            self.e_marka.value = marka_api
            wzbogacono_api = True

        model = (dane.get("Model") or "").strip()
        if model:
            self.e_model.value = model
            wzbogacono_api = True

        rok_api = (dane.get("ModelYear") or "").strip()
        if rok_api:
            self.e_rok.value = rok_api
            wzbogacono_api = True

        poj_ccm = (dane.get("DisplacementCC") or "").strip()
        poj_l = (dane.get("DisplacementL") or "").strip()
        if poj_ccm:
            try:
                self.e_poj.value = str(int(round(float(poj_ccm))))
                wzbogacono_api = True
            except ValueError:
                pass
        elif poj_l:
            try:
                self.e_poj.value = str(int(round(float(poj_l) * 1000)))
                wzbogacono_api = True
            except ValueError:
                pass

        moc = (dane.get("EngineHP") or "").strip()
        if moc:
            try:
                self.e_moc.value = str(int(round(float(moc))))
                wzbogacono_api = True
            except ValueError:
                pass

        paliwo = (dane.get("FuelTypePrimary") or "").lower()
        mapa_paliwa = [
            ("diesel", "Diesel"), ("electric", "Elektryczny"), ("hybrid", "Hybryda"),
            ("natural gas", "LPG"), ("propane", "LPG"), ("liquefied petroleum", "LPG"),
            ("gasoline", "Benzyna"), ("flexible fuel", "Benzyna"),
        ]
        for fragment, wartosc_pl in mapa_paliwa:
            if fragment in paliwo:
                self.e_pal.value = wartosc_pl
                wzbogacono_api = True
                break

        skrzynia = (dane.get("TransmissionStyle") or "").lower()
        if "manual" in skrzynia:
            self.e_skrz.value = "Manualna"
            wzbogacono_api = True
        elif "automatic" in skrzynia or "cvt" in skrzynia:
            self.e_skrz.value = "Automatyczna"
            wzbogacono_api = True

        self._page.update()

        # --- Komunikat końcowy dopasowany do tego, co faktycznie się udało ---
        if marka_lokalna and wzbogacono_api:
            utils.pokaz_komunikat(self._page, "Rozkodowano VIN! Markę i rok rozpoznano lokalnie, resztę uzupełniono z bazy NHTSA.")
        elif marka_lokalna and not wzbogacono_api:
            utils.pokaz_komunikat(
                self._page,
                "Rozpoznano markę i rok produkcji lokalnie (baza WMI). Baza NHTSA nie miała dodatkowych "
                "danych dla tego VIN-u (typowe dla aut spoza USA) — resztę uzupełnij ręcznie.",
                ft.Colors.ORANGE_700
            )
        elif wzbogacono_api:
            utils.pokaz_komunikat(self._page, "Rozkodowano dane z numeru VIN! Sprawdź uzupełnione pola.")
        elif region:
            utils.pokaz_komunikat(
                self._page,
                f"Nie rozpoznano dokładnej marki, ale VIN wskazuje na region: {region}. Uzupełnij dane ręcznie.",
                ft.Colors.ORANGE_700
            )
        else:
            utils.pokaz_komunikat(
                self._page,
                "Nie udało się rozkodować VIN-u — sprawdź poprawność numeru albo uzupełnij dane ręcznie.",
                ft.Colors.RED_700
            )

    def _migawka_formularza(self):
        return (
            self.e_marka.value, self.e_model.value, self.e_generacja.value,
            self.e_rej.value, self.e_rok.value, self.e_vin.value, self.e_przebieg.value,
            self.e_oc.value, self.e_pt.value, self.e_poj.value, self.e_moc.value,
            self.e_pal.value, self.e_skrz.value, self.e_nadwozie.value,
            self.e_bateria.value, self.e_zasieg.value, self.e_bak.value, self.e_zlacze.value,
            self.e_pierwsza_rej.value, self.e_data_zakupu.value, self.e_cena_zakupu.value,
            self.e_przebieg_zakupu.value, self.e_wartosc.value,
            self.e_ubezpieczyciel.value, self.e_polisa.value, self.e_skladka.value,
            self.e_assistance.value, self.e_lakier.value, self.e_opony.value,
            self.e_felgi.value, self.e_srub.value, self.e_moment.value,
            self.e_not.value,
            self.e_wp.value, self.e_wt.value, self.e_cp.value, self.e_ct.value,
            self.e_ot.value, self.e_op.value, self.e_akum.value, self.e_zm.value, self.e_zd.value,
            self.e_ac.value, self.e_asy.value, self.e_gas.value, self.e_apt.value,
            self.e_gw.value, self.e_gwp.value,
            self.get_kolor(),
        )

    def _czy_zmieniono(self):
        return self._migawka_formularza() != self._stan_poczatkowy            

    def zapisz(self, e):
        for pole in (self.e_marka, self.e_model, self.e_rok, self.e_vin):
            utils.ustaw_blad(pole)

        bledy = []
        
        utils.ustaw_blad(self.e_przebieg)
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
                bledy.append((self.e_rok, f"Rok poza zakresem {db.ROK_MIN}–{datetime.now().year + 1}"))
        if self.e_vin.value and len(self.e_vin.value) > 17:
            bledy.append((self.e_vin, "Maks. 17 znaków"))

        utils.ustaw_blad(self.e_gwp)
        gwarancja_km = None
        if (self.e_gwp.value or "").strip():
            gwarancja_km = utils.parsuj_int(self.e_gwp.value, None)
            if gwarancja_km is None or gwarancja_km <= 0:
                bledy.append((self.e_gwp, "Podaj poprawny limit km"))

        if bledy:
            return utils.pokaz_bledy_formularza(self._page, bledy)

        # Dynamiczne złożenie nazwy pojazdu
        n = " ".join(filter(None, [marka, model, generacja]))

        # Weryfikacja unikalności konfiguracji przed przetwarzaniem załącznika
        with db.polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT id FROM samochody WHERE LOWER(nazwa)=LOWER(?) AND id!=?", (n, self.auto_id or 0))
            if c.fetchone():
                utils.ustaw_blad(self.e_marka, "Pojazd o tej samej konfiguracji już istnieje!")
                utils.ustaw_blad(self.e_model, "Zmień dane, aby były unikalne.")
                self._page.update()
                return utils.pokaz_komunikat(self._page, "Pojazd o takiej nazwie już istnieje w bazie.", ft.Colors.RED_700)

        # PO:
        przygotowany_zdj = db.przygotuj_nowy_zalacznik(self.get_zdjecie())
        nowe_zdj = przygotowany_zdj if przygotowany_zdj is not None else self.zg_val
        nowy_kolor = self.get_kolor()

        # Komplet pól pojazdu jako słownik, z którego składamy SQL. Ręcznie
        # pisany UPDATE/INSERT po 50 kolumnach był miejscem, w którym jedna
        # przesunięta wartość zapisywała ciśnienie opon do pola z żarówkami —
        # a taki błąd nie rzuca wyjątku, tylko cicho psuje dane.
        dane_pojazdu = {
            "nazwa": n, "marka": marka, "model": model, "generacja": generacja,
            "nr_rej": self.e_rej.value, "vin": self.e_vin.value,
            "rok_produkcji": self.e_rok.value,
            "data_pierwszej_rejestracji": (self.e_pierwsza_rej.value or None),
            "oc_data": self.e_oc.value, "przeglad_data": self.e_pt.value,
            "ac_data": self.e_ac.value, "assistance_data": self.e_asy.value,
            "gasnica_data": self.e_gas.value, "apteczka_data": self.e_apt.value,
            "gwarancja_data": self.e_gw.value, "gwarancja_przebieg": gwarancja_km,
            "pojemnosc_silnika": self.e_poj.value, "moc_silnika": self.e_moc.value,
            "typ_paliwa": self.e_pal.value, "skrzynia_biegow": self.e_skrz.value,
            "nadwozie": (self.e_nadwozie.value or None),
            "pojemnosc_baku": (self.e_bak.value or None),
            "pojemnosc_baterii": (self.e_bateria.value or None),
            "zasieg_ev": (self.e_zasieg.value or None),
            "typ_zlacza_ev": (self.e_zlacze.value or None),
            "notatki": self.e_not.value,
            "wycieraczki_przod": self.e_wp.value, "wycieraczki_tyl": self.e_wt.value,
            "cisnienie_przod": self.e_cp.value, "cisnienie_tyl": self.e_ct.value,
            "olej_typ": self.e_ot.value, "olej_pojemnosc": self.e_op.value,
            "akumulator": self.e_akum.value,
            "zarowki_mijania": self.e_zm.value, "zarowki_drogowe": self.e_zd.value,
            "kod_lakieru": (self.e_lakier.value or None),
            "rozmiar_opon": (self.e_opony.value or None),
            "rozmiar_felg": (self.e_felgi.value or None),
            "rozstaw_srub": (self.e_srub.value or None),
            "moment_dokrecania": (self.e_moment.value or None),
            "data_zakupu": (self.e_data_zakupu.value or None),
            "cena_zakupu": utils.parsuj_float(self.e_cena_zakupu.value, None),
            "przebieg_zakupu": utils.parsuj_int(self.e_przebieg_zakupu.value, None),
            "wartosc_szacowana": utils.parsuj_float(self.e_wartosc.value, None),
            "ubezpieczyciel": (self.e_ubezpieczyciel.value or None),
            "nr_polisy": (self.e_polisa.value or None),
            "skladka_roczna": utils.parsuj_float(self.e_skladka.value, None),
            "telefon_assistance": (self.e_assistance.value or None),
            "zdjecie_glowne": nowe_zdj, "kolor_motywu": nowy_kolor,
        }

        try:
            with db.polacz_baze() as conn:
                if self.auto_id:
                    przypisania = ", ".join(f"{kolumna}=?" for kolumna in dane_pojazdu)
                    conn.execute(
                        f"UPDATE samochody SET {przypisania} WHERE id=?",
                        tuple(dane_pojazdu.values()) + (self.auto_id,)
                    )
                    if self.state.auto_id == self.auto_id:
                        self.state.auto_nazwa = n
                else:
                    cur = conn.cursor()
                    nazwy_kolumn = ", ".join(dane_pojazdu)
                    znaki = ",".join("?" for _ in dane_pojazdu)
                    cur.execute(
                        f"INSERT INTO samochody ({nazwy_kolumn}) VALUES ({znaki})",
                        tuple(dane_pojazdu.values())
                    )
                    n_id = cur.lastrowid
                    # Elektryk nie ma oleju ani filtra oleju — startuje z listą
                    # dopasowaną do swojego napędu.
                    lista_startowa = (db.DOMYSLNE_ZADANIA_EV
                                      if self.e_pal.value in db.TYPY_PALIWA_ELEKTRYCZNE
                                      else db.DOMYSLNE_ZADANIA)
                    for dz in lista_startowa:
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
                    # Korekta przebiegu z formularza pojazdu ma własne źródło —
                    # w historii licznika od razu widać, że nie jest to odczyt
                    # z deski rozdzielczej, tylko poprawka danych auta.
                    conn.execute(
                        "INSERT INTO odczyty_przebiegu (auto_id, data, przebieg, zrodlo) VALUES (?, ?, ?, ?)", 
                        (zapisane_id, datetime.now().strftime("%d.%m.%Y"), prz, "pojazd")
                    )

            db.zatwierdz_zalacznik(self.zg_val, przygotowany_zdj)

            utils.wypchnij_w_tle(self._page, self.state.auto_id, "pojazd")

            utils.przejdz(self._page, "/")
            utils.pokaz_komunikat(self._page, "Zapisano pojazd!")
        except Exception as ex:
            db.anuluj_nowy_zalacznik(przygotowany_zdj)
            utils.pokaz_komunikat(self._page, f"Błąd zapisu pojazdu: {ex}", ft.Colors.RED_700)


__all__ = [
    "FormularzAutoView",
]
