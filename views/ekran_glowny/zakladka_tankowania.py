"""Zakładka Koszty → Tankowania: lista tankowań i ładowań."""

import db
import flet as ft
import sqlite3
import sync
import utils
from date import parsuj_date


class MiksinZakladkiTankowania:
    """Zakładka Koszty → Tankowania: lista tankowań i ładowań."""

    def buduj_tankowania(self):
        wspolny_id, _ = sync.czy_udostepniony(self.state.auto_id)
        elektryczny = db.czy_pojazd_elektryczny(self.state.auto_id)
        etykiety = db.etykiety_paliwa(elektryczny)
        naglowek_bits = utils.tytul_sekcji(
            utils.ikona_z_mapy(utils.IKONY_AKTYWNOSCI, etykiety.get("ikona_listy", "tankowanie")),
            etykiety["naglowek_listy"],
        )
        if wspolny_id:
            naglowek_bits.append(utils.przycisk_synchronizacji(self._page, self._synchronizuj_teraz))
        self.elementy.append(ft.Row(naglowek_bits, vertical_alignment=ft.CrossAxisAlignment.CENTER))

        with db.polacz_baze() as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT * FROM tankowania WHERE auto_id=?", (self.state.auto_id,))
            baza_lista = [dict(row) for row in c.fetchall()]

        if not baza_lista:
            self.elementy.append(utils.ekran_braku_danych(
                ikona=ft.Icons.LOCAL_GAS_STATION,
                tytul="Brak tankowań",
                opis="Nie masz jeszcze historii paliwowej dla tego pojazdu.",
                tekst_przycisku="Dodaj pierwsze tankowanie",
                on_click=lambda e: utils.przejdz(self._page, "/tankowanie/nowe")
            ))
        else:
            baza_lista.sort(key=lambda x: int(x.get('przebieg') or 0))

            # Rodzaj energii normalizujemy raz: wpisy sprzed migracji 33 mają
            # NULL i biorą domyślny dla pojazdu.
            domyslny_rodzaj = db.domyslny_rodzaj_energii(self.state.auto_id)
            for t in baza_lista:
                t['rodzaj'] = str(t.get('rodzaj_energii') or domyslny_rodzaj)

            # Zużycie liczymy OSOBNO w obrębie każdego źródła — przy hybrydzie
            # plug-in odcinek „od pełnego baku do pełnego baku” nie ma nic
            # wspólnego z ładowaniami, które wypadły pomiędzy nimi.
            ostatni_pelny = {}
            poprzedni_przebieg = {}
            for i, t in enumerate(baza_lista):
                rodzaj = t['rodzaj']
                prz_akt = int(t.get('przebieg') or 0)

                poprz = poprzedni_przebieg.get(rodzaj)
                t['dystans'] = max(0, prz_akt - poprz) if poprz is not None else 0
                poprzedni_przebieg[rodzaj] = prz_akt

                t['spalanie'] = None
                if t.get('do_pelna'):
                    idx_poprzedniego = ostatni_pelny.get(rodzaj)
                    if idx_poprzedniego is not None:
                        prz_ostatni_pelny = int(baza_lista[idx_poprzedniego].get('przebieg') or 0)
                        dystans_od_pelnego = prz_akt - prz_ostatni_pelny
                        ilosc_od_pelnego = sum(
                            float(baza_lista[k].get('litry') or 0)
                            for k in range(idx_poprzedniego + 1, i + 1)
                            if baza_lista[k]['rodzaj'] == rodzaj
                        )
                        if dystans_od_pelnego > 0:
                            t['spalanie'] = (ilosc_od_pelnego / dystans_od_pelnego) * 100
                    ostatni_pelny[rodzaj] = i

            opcje_sort = [
                ("Data", "data", lambda x: (parsuj_date(x.get('data')), x.get('id', 0))),
                ("Przebieg", "przebieg", lambda x: int(x.get('przebieg') or 0)),
                ("Kwota", "kwota", lambda x: float(x.get('kwota') or 0)),
                ("Litry", "litry", lambda x: float(x.get('litry') or 0)),
            ]

            sort_ui = utils.przycisk_sortowania(self._page, self.state, "tankowania", opcje_sort)
            filtr_rok_ui = utils.przycisk_filtrowania_rok(self._page, self.state, "tankowania_rok", baza_lista, "data")
            filtr_mc_ui = utils.przycisk_filtrowania_miesiac(self._page, self.state, "tankowania_mc", baza_lista, "data")
            filtr_tag_ui = utils.przycisk_filtrowania_kategoria(self._page, self.state, "tankowania_tag", baza_lista, "tagi", "Tagi")

            # „Kto to dodał” ma sens dopiero przy pojeździe współdzielonym —
            # przy jednym użytkowniku każdy wpis jest jego i filtr byłby szumem.
            filtry_ui = [sort_ui, filtr_rok_ui, filtr_mc_ui, filtr_tag_ui]
            # Przy hybrydzie plug-in lista miesza tankowania z ładowaniami —
            # bez filtra nie da się obejrzeć samej jednej strony.
            if len(db.rodzaje_energii_pojazdu(self.state.auto_id)) > 1:
                filtry_ui.insert(1, utils.przycisk_filtrowania_kategoria(
                    self._page, self.state, "tankowania_rodzaj",
                    [{"rodzaj_opis": db.ETYKIETY_RODZAJU[t['rodzaj']]} for t in baza_lista],
                    "rodzaj_opis", "Źródło"
                ))
            if wspolny_id:
                filtry_ui.append(
                    utils.przycisk_filtrowania_autora(self._page, self.state, "tankowania_autor", baza_lista, "dodane_przez")
                )

            self.elementy.append(
                ft.Row(
                    controls=filtry_ui,
                    scroll=ft.ScrollMode.ADAPTIVE,
                    spacing=8
                )
            )

            def filtruj_tankowania(e):
                zapytanie = e.control.value.lower().strip()
                self.lista_kart_tankowania.controls.clear()
                for k in self.wszystkie_karty_tankowania:
                    if zapytanie in k["szukaj"]:
                        self.lista_kart_tankowania.controls.append(k["karta"])
                utils.dopasuj_wysokosc_listy(self.lista_kart_tankowania, self._page, wysokosc_pozycji=200)
                self.update()

            self.elementy.append(
                ft.TextField(
                    hint_text="Szukaj tankowania (stacja, data, kwota, dystans, notatka)...",
                    prefix_icon=ft.Icons.SEARCH,
                    on_change=utils.z_opoznieniem(self._page, filtruj_tankowania),
                    **utils.styl_pola()
                )
            )
            self.lista_kart_tankowania = ft.ListView(spacing=15, padding=0, height=utils.wysokosc_listy(self._page), auto_scroll=False)
            self.uzyj_wirtualizacji = True
            self.wszystkie_karty_tankowania = []

            po_filtrach = utils.filtruj_po_roku(baza_lista, self.state, "tankowania_rok", "data")
            po_filtrach = utils.filtruj_po_miesiacu(po_filtrach, self.state, "tankowania_mc", "data")
            po_filtrach = utils.filtruj_po_kategorii(po_filtrach, self.state, "tankowania_tag", "tagi")
            if len(db.rodzaje_energii_pojazdu(self.state.auto_id)) > 1:
                for t in po_filtrach:
                    t["rodzaj_opis"] = db.ETYKIETY_RODZAJU[t["rodzaj"]]
                po_filtrach = utils.filtruj_po_kategorii(po_filtrach, self.state, "tankowania_rodzaj", "rodzaj_opis")
            if wspolny_id:
                po_filtrach = utils.filtruj_po_autorze(po_filtrach, self.state, "tankowania_autor", "dodane_przez")
            utils.posortuj_liste(po_filtrach, self.state, "tankowania", opcje_sort)

            def otworz_menu_t(tid, zalacznik=None, notatka=None):
                def usun_tankowanie():
                    def wykonaj():
                        wynik = db.usun_z_cofnieciem("tankowania", tid)
                        utils.przejdz(self._page, "/")
                        utils.pokaz_komunikat_cofnij(self._page, "Usunięto tankowanie.", wynik)
                    utils.potwierdz(self._page, "Usunąć?", "Czy na pewno usunąć to tankowanie?", wykonaj)

                async def dodaj_zmien_zdj():
                    await utils.szybkie_dodanie_zdjecia(self._page, "tankowania", tid, zalacznik, lambda: utils.przejdz(self._page, "/"))

                pozycje = []
                if zalacznik:
                    pozycje.append({"ikona": ft.Icons.IMAGE, "tekst": "Pokaż zdjęcie", "akcja": lambda: utils.pokaz_podglad_zalacznika(self._page, zalacznik, "Tankowanie")})
                    pozycje.append({"ikona": ft.Icons.EDIT_DOCUMENT, "tekst": "Zmień zdjęcie", "akcja": dodaj_zmien_zdj})
                else:
                    pozycje.append({"ikona": ft.Icons.ADD_A_PHOTO, "tekst": "Dodaj zdjęcie (paragon)", "akcja": dodaj_zmien_zdj})

                pozycje.append(utils.pozycja_menu_notatki(
                    self._page, "tankowania", tid, notatka,
                    lambda: utils.przejdz(self._page, "/"), "Notatka do tankowania"
                ))
                pozycje.append({"ikona": ft.Icons.EDIT, "tekst": "Edytuj", "akcja": lambda: utils.przejdz(self._page, f"/tankowanie/edytuj/{tid}")})
                pozycje.append({"ikona": ft.Icons.CONTENT_COPY, "tekst": "Duplikuj", "akcja": lambda: (setattr(self.state, "duplikuj_zrodlo_tankowanie", tid), utils.przejdz(self._page, "/tankowanie/nowe"))})
                pozycje.append({"ikona": ft.Icons.DELETE, "tekst": "Usuń", "akcja": usun_tankowanie, "kolor": ft.Colors.RED})

                utils.pokaz_menu_kontekstowe(self._page, "Opcje tankowania", pozycje)

            if not po_filtrach:
                self.elementy.append(ft.Row([ft.Text("Brak wyników dla tych filtrów.", color=ft.Colors.ON_SURFACE_VARIANT)], alignment=ft.MainAxisAlignment.CENTER))
            else:
                mapa_tagow = {t[1]: t[2] for t in db.pobierz_tagi(self.state.auto_id)}
                dwuzrodlowy_lista = len(db.rodzaje_energii_pojazdu(self.state.auto_id)) > 1
                for w in po_filtrach:
                    # Etykiety idą za RODZAJEM WPISU, nie za typem pojazdu —
                    # w jednej liście plug-ina stoją obok siebie litry i kWh.
                    rodzaj_w = w.get('rodzaj') or db.ENERGIA_PALIWO
                    czy_prad_w = rodzaj_w == db.ENERGIA_PRAD
                    etykiety_w = db.etykiety_energii(rodzaj_w)
                    spalanie = w.get('spalanie')
                    sp_str = utils.formatuj_spalanie(spalanie, elektryczny=czy_prad_w)
                    kwota_val = float(w.get('kwota') or 0)
                    litry_val = float(w.get('litry') or 0)
                    cena_str = f"{utils.formatuj_liczba(kwota_val)}  {utils.symbol_waluty()}"
                    cena_litr_str = f"{utils.formatuj_liczba(kwota_val / litry_val, 2)} {utils.symbol_waluty()}/{etykiety_w['jednostka']}" if litry_val > 0 else "-"
                    dystans_val = w.get('dystans') or 0

                    tid = w.get('id')
                    tresc_karty = [
                        ft.Row([
                            ft.Text(f"{w.get('data')} • {w.get('stacja')}" if w.get('stacja') else str(w.get('data')), weight="bold", color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                            ft.Row([
                                # Odznaka źródła tylko przy plug-inie — przy aucie
                                # jednoźródłowym byłaby tą samą etykietą przy każdym wpisie.
                                ft.Container(
                                    padding=ft.Padding(6, 1, 6, 1),
                                    border_radius=utils.RADIUS["pill"],
                                    bgcolor=ft.Colors.with_opacity(0.14, ft.Colors.GREEN if czy_prad_w else ft.Colors.BLUE),
                                    content=ft.Row([
                                        ft.Icon(ft.Icons.EV_STATION if czy_prad_w else ft.Icons.LOCAL_GAS_STATION,
                                                size=11, color=ft.Colors.GREEN_800 if czy_prad_w else ft.Colors.BLUE_800),
                                        ft.Text(db.ETYKIETY_RODZAJU[rodzaj_w] + (f" · {w.get('typ_ladowania')}" if czy_prad_w and w.get('typ_ladowania') else ""),
                                                size=10, weight="bold",
                                                color=ft.Colors.GREEN_800 if czy_prad_w else ft.Colors.BLUE_800),
                                    ], spacing=3, tight=True),
                                ) if dwuzrodlowy_lista else ft.Container(),
                                utils.wskaznik_zalacznika(self._page, w.get('zalacznik'), "Tankowanie"),
                                ft.Icon(ft.Icons.EV_STATION if czy_prad_w else ft.Icons.LOCAL_GAS_STATION, size=14, color=ft.Colors.PRIMARY, tooltip="Do pełna") if w.get('do_pelna') else ft.Container(),
                                ft.Text(f"-{cena_str}", weight="bold", color=ft.Colors.RED_700)
                            ], spacing=4)
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Row([
                            ft.Column([ft.Text("Dystans", size=11, color=ft.Colors.ON_SURFACE_VARIANT), ft.Text(f"{dystans_val} km", weight="bold")]),
                            ft.Column([ft.Text(etykiety_w["zuzycie"], size=11, color=ft.Colors.ON_SURFACE_VARIANT), ft.Text(sp_str, weight="bold")]),
                            ft.Column([ft.Text(etykiety_w["cena_jednostkowa"], size=11, color=ft.Colors.ON_SURFACE_VARIANT), ft.Text(cena_litr_str, weight="bold")]),
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                    ]
                    if w.get('tagi'):
                        tresc_karty.append(utils.wizualizacja_tagow(w.get('tagi'), self.state.auto_id, mapa_tagow))
                    tresc_karty.append(utils.podglad_notatki(
                        self._page, w.get('notatka'), w.get('notatka_autor'), w.get('notatka_data'),
                        "Notatka do tankowania",
                        on_edytuj=lambda rid=tid: utils.szybka_notatka(
                            self._page, "tankowania", rid,
                            lambda: utils.przejdz(self._page, "/"), "Notatka do tankowania"
                        ),
                        pokaz_podpis=bool(wspolny_id)
                    ))
                    if wspolny_id and (w.get('dodane_przez') or w.get('zmodyfikowane_przez')):
                        tresc_karty.append(utils.znacznik_atrybucji(w.get('dodane_przez'), w.get('zmodyfikowane_przez'), w.get('data_modyfikacji')))

                    kontener = ft.Container(padding=15, border_radius=10, ink=True, content=ft.Column(tresc_karty))

                    self.karty_ref[tid] = kontener
                    self.podepnij_zdarzenia_grupowe(kontener, tid, lambda id_el=tid, zal=w.get('zalacznik'), nt=w.get('notatka'): otworz_menu_t(id_el, zal, nt), "tankowania")

                    karta_t = ft.Card(elevation=1, content=kontener)
                    tekst_szukaj = f"{w.get('data')} {w.get('stacja')} {cena_str} {dystans_val} {sp_str} {w.get('tagi')} {db.ETYKIETY_RODZAJU[rodzaj_w]} {w.get('typ_ladowania') or ''} {w.get('notatka') or ''}".lower()
                    self.wszystkie_karty_tankowania.append({"karta": karta_t, "szukaj": tekst_szukaj})
                    self.lista_kart_tankowania.controls.append(karta_t)

                utils.dopasuj_wysokosc_listy(self.lista_kart_tankowania, self._page, wysokosc_pozycji=200)
                self.elementy.append(self.lista_kart_tankowania)

        self.fab = self._buduj_fab_szybkich_akcji()
