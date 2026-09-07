"""Zakładka Serwis: podzespoły, interwały i historia wpisów."""

import db
import flet as ft
import sqlite3
import sync
import utils
from date import parsuj_date
from datetime import datetime, timedelta


class MiksinZakladkiSerwis:
    """Zakładka Serwis: podzespoły, interwały i historia wpisów."""

    def buduj_serwis(self):
        wspolny_id, _ = sync.czy_udostepniony(self.state.auto_id)

        naglowek_serwis = utils.tytul_sekcji(ft.Icons.BUILD_CIRCLE, "Serwis")
        if wspolny_id:
            naglowek_serwis.append(utils.przycisk_synchronizacji(self._page, self._synchronizuj_teraz))

        self.elementy.append(ft.Row(naglowek_serwis, vertical_alignment=ft.CrossAxisAlignment.CENTER))

        # --- SEKCJE „POD-SERWISOWE” JAKO KARTY, A NIE MENU ⋮ ---
        # Wizyty, zadania i magazyn siedziały pod trzema kropkami w rogu
        # nagłówka — czyli w miejscu, w które zagląda się wtedy, gdy się już WIE,
        # że tam coś jest. Jako karty z opisem i licznikiem mówią same o sobie,
        # co mają w środku i czy wymagają uwagi. Karoseria przeniosła się do
        # grupy „Pojazd”: to dokumentacja stanu auta, a nie czynność serwisowa.
        self.elementy.append(utils.pasek_sekcji(
            self._page, self.state,
            ["wizyty", "do-zrobienia", "magazyn"],
            self.akcje_nawigacji, self.liczniki_nawigacji,
        ))

        akt_prz = int(db.pobierz_aktualny_przebieg(self.state.auto_id))
        prog_km = db.pobierz_prog_km()
        prog_dni = db.pobierz_prog_dni()

        sredni_dzienny = db.oblicz_sredni_dzienny_przebieg(self.state.auto_id)
        with db.polacz_baze() as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT * FROM zadania WHERE auto_id=?", (self.state.auto_id,))
            baza_lista = [dict(row) for row in c.fetchall()]

        # --- Wyraźne oddzielenie skrótów od właściwej listy podzespołów ---
        self.elementy.append(ft.Divider(height=20))

        if not baza_lista:
            self.elementy.append(utils.ekran_braku_danych(
                ikona=ft.Icons.HANDYMAN,
                tytul="Brak podzespołów",
                opis="Dodaj części (np. olej, filtry, rozrząd), aby śledzić wymiany i interwały.",
                tekst_przycisku="Dodaj część",
                on_click=lambda e: utils.przejdz(self._page, "/zadanie/nowy")
            ))
        else:
            self.tekst_licznik_zadan = ft.Text("", size=16, weight="bold", color=ft.Colors.PRIMARY)

            self.elementy.append(
                ft.Row([
                    ft.Icon(ft.Icons.HANDYMAN, color=ft.Colors.PRIMARY, size=20),
                    self.tekst_licznik_zadan,
                ], spacing=8)
            )

            opcje_sort = [
                ("Nazwa", "nazwa", lambda r: str(r.get('nazwa', '')).lower()),
                ("Ostatnia data", "data", lambda r: parsuj_date(r.get('data'))),
                ("Przebieg", "przebieg", lambda r: int(r.get('przebieg') or 0)),
            ]

            sort_ui = utils.przycisk_sortowania(self._page, self.state, "zadania", opcje_sort)
            filtr_rok_ui = utils.przycisk_filtrowania_rok(self._page, self.state, "serwis_rok", baza_lista, "data")
            filtr_mc_ui = utils.przycisk_filtrowania_miesiac(self._page, self.state, "serwis_mc", baza_lista, "data")

            self.elementy.append(
                ft.Row(
                    controls=[sort_ui, filtr_rok_ui, filtr_mc_ui],
                    scroll=ft.ScrollMode.ADAPTIVE,
                    spacing=8
                )
            )

            def filtruj_zadania(e):
                zapytanie = e.control.value.lower().strip()
                self.lista_kart_serwis.controls.clear()
                for k in self.wszystkie_karty_serwis:
                    if zapytanie in k["szukaj"]:
                        self.lista_kart_serwis.controls.append(k["karta"])

                self.tekst_licznik_zadan.value = f"Śledzone podzespoły ({len(self.lista_kart_serwis.controls)})"
                utils.dopasuj_wysokosc_listy(self.lista_kart_serwis, self._page, wysokosc_pozycji=190)
                self.update()

            self.elementy.append(
                ft.TextField(
                    hint_text="Szukaj podzespołu (np. olej, klocki, filtr)...",
                    prefix_icon=ft.Icons.SEARCH,
                    on_change=utils.z_opoznieniem(self._page, filtruj_zadania),
                    **utils.styl_pola()
                )
            )
            self.lista_kart_serwis = ft.ListView(spacing=15, padding=0, height=utils.wysokosc_listy(self._page), auto_scroll=False)
            self.uzyj_wirtualizacji = True
            self.wszystkie_karty_serwis = []

            po_filtrach = utils.filtruj_po_roku(baza_lista, self.state, "serwis_rok", "data")
            po_filtrach = utils.filtruj_po_miesiacu(po_filtrach, self.state, "serwis_mc", "data")
            utils.posortuj_liste(po_filtrach, self.state, "zadania", opcje_sort)

            self.tekst_licznik_zadan.value = f"Śledzone podzespoły ({len(po_filtrach)})"

            def pokaz_menu(zid, zn):
                self.state.wybrane_zadanie_id = zid
                self.state.wybrane_zadanie_nazwa = str(zn)

                def usun_zadanie(e):
                    utils.zamknij_dno(self._page, bs)
                    def wykonaj():
                        wynik = db.usun_zadanie_z_cofnieciem(zid)
                        utils.przejdz(self._page, "/")
                        utils.pokaz_komunikat_cofnij(self._page, "Usunięto podzespół.", wynik)
                    utils.potwierdz(self._page, "Usunąć?", "Na pewno usunąć ten podzespół?", wykonaj)

                bs = ft.BottomSheet(ft.Container(padding=20, bgcolor=ft.Colors.SURFACE, content=ft.Column([
                    ft.Text(str(zn), weight="bold", size=20, color=ft.Colors.PRIMARY), ft.Divider(),
                    ft.ListTile(leading=ft.Icon(ft.Icons.ADD_CIRCLE, color=ft.Colors.GREEN), title=ft.Text("Dodaj Wymianę", weight="bold"), on_click=lambda e: (utils.zamknij_dno(self._page, bs), utils.przejdz(self._page, f"/wpis/nowy/{zid}"))),
                    ft.ListTile(leading=ft.Icon(ft.Icons.HISTORY), title=ft.Text("Historia wymian"), on_click=lambda e: (utils.zamknij_dno(self._page, bs), utils.przejdz(self._page, f"/historia/{zid}"))),
                    ft.ListTile(leading=ft.Icon(ft.Icons.TIMER), title=ft.Text("Ustaw interwał przypomnień"), on_click=lambda e: (utils.zamknij_dno(self._page, bs), utils.przejdz(self._page, f"/interwal/{zid}"))),
                    ft.ListTile(leading=ft.Icon(ft.Icons.EDIT), title=ft.Text("Zmień nazwę"), on_click=lambda e: (utils.zamknij_dno(self._page, bs), utils.przejdz(self._page, f"/zadanie/edytuj/{zid}"))),
                    ft.ListTile(leading=ft.Icon(ft.Icons.DELETE, color=ft.Colors.RED), title=ft.Text("Usuń podzespół", color=ft.Colors.RED), on_click=usun_zadanie),
                ], tight=True)))
                utils.otworz_dno(self._page, bs)

            if not po_filtrach:
                self.elementy.append(ft.Row([ft.Text("Brak wyników dla tych filtrów.", color=ft.Colors.ON_SURFACE_VARIANT)], alignment=ft.MainAxisAlignment.CENTER))
            else:
                for z in po_filtrach:
                    kol, ico = ft.Colors.GREEN_700, ft.Icons.CHECK_CIRCLE  # domyślny status
                    stxt = []
                    procent_km = None
                    procent_dni = None
                    prog_km_z = int(z.get('prog_km') or prog_km)
                    prog_dni_z = int(z.get('prog_dni') or prog_dni)
                    if z.get('interwal_km') and z.get('przebieg'):
                        interwal_km = int(z.get('interwal_km'))
                        zost_km = (int(z.get('przebieg')) + interwal_km) - akt_prz
                        procent_km = (interwal_km - zost_km) / interwal_km if interwal_km > 0 else None
                        if zost_km < 0:
                            stxt.append(f"{utils.formatuj_liczba(abs(zost_km), 0)} km po!")
                            kol, ico = ft.Colors.RED_700, ft.Icons.WARNING
                        elif zost_km <= prog_km_z:
                            prognoza = utils.formatuj_prognoze_km(zost_km, sredni_dzienny)
                            stxt.append(prognoza or f"{utils.formatuj_liczba(zost_km, 0)} km")
                            kol, ico = ft.Colors.ORANGE_700, ft.Icons.HOURGLASS_BOTTOM
                        else:
                            prognoza = utils.formatuj_prognoze_km(zost_km, sredni_dzienny)
                            stxt.append(prognoza or f"{utils.formatuj_liczba(zost_km, 0)} km")

                    if z.get('interwal_miesiace') and z.get('data'):
                        d_w = parsuj_date(z.get('data'))
                        if d_w != datetime.min.date():
                            interwal_dni = int(float(z.get('interwal_miesiace')) * 30.5)
                            zost_dni = (d_w + timedelta(days=interwal_dni) - datetime.now().date()).days
                            procent_dni = (interwal_dni - zost_dni) / interwal_dni if interwal_dni > 0 else None
                            if zost_dni < 0:
                                stxt.append(f"{abs(zost_dni)} dni po!")
                                kol, ico = ft.Colors.RED_700, ft.Icons.WARNING
                            elif zost_dni <= prog_dni_z:
                                stxt.append(f"{zost_dni} dni")
                                if kol != ft.Colors.RED_700: kol, ico = ft.Colors.ORANGE_700, ft.Icons.HOURGLASS_BOTTOM
                            else: stxt.append(f"~{zost_dni//30} m-cy")

                    if stxt: final_status = " | ".join(stxt)
                    else:
                        final_status = "Brak interwału" if not z.get('interwal_km') and not z.get('interwal_miesiace') else "Brak wpisów"
                        kol, ico = ft.Colors.ON_SURFACE_VARIANT, ft.Icons.INFO_OUTLINE

                    data_w = str(z.get('data')) if z.get('data') else '-'
                    prz_w = f"{utils.formatuj_liczba(int(z.get('przebieg')), 0)} km" if z.get('przebieg') else '-'

                    zid = z.get('id')
                    zn = z.get('nazwa')

                    # Jeśli podzespół ma zarówno interwał km, jak i miesięczny,
                    # pasek pokazuje ten, który jest BLIŻEJ przekroczenia (wyższy
                    # procent zużycia) — to ten sam interwał, który decyduje
                    # o kolorze/pilności karty wyliczonym wyżej.
                    kandydaci_procent = [p for p in (procent_km, procent_dni) if p is not None]
                    procent_do_paska = max(kandydaci_procent) if kandydaci_procent else None

                    wiersz_statusu = (
                        utils.pasek_postepu(final_status, f"{int(max(0.0, min(1.0, procent_do_paska)) * 100)}%", procent_do_paska, kol)
                        if procent_do_paska is not None
                        else ft.Text(final_status, size=utils.FS["body_strong"], weight="bold", color=kol)
                    )
                    karta_z, kontener = utils.karta_listy(
                        ft.Column([
                            ft.Row([ft.Text(str(zn), weight="bold", size=utils.FS["title"], expand=True), ft.Icon(ico, color=kol)]),
                            ft.Text(f"Wymieniono: {data_w} | Przy: {prz_w}", size=utils.FS["body"], color=ft.Colors.ON_SURFACE_VARIANT),
                            wiersz_statusu
                        ]),
                        kolor_paska=kol,
                        page=self._page,
                    )

                    self.karty_ref[zid] = kontener
                    self.podepnij_zdarzenia_grupowe(kontener, zid, lambda zid=zid, zn=zn: pokaz_menu(zid, zn), "zadania")
                    tekst_szukaj = f"{zn} {data_w} {prz_w} {final_status}".lower()
                    self.wszystkie_karty_serwis.append({"karta": karta_z, "szukaj": tekst_szukaj})
                    self.lista_kart_serwis.controls.append(karta_z)

                utils.dopasuj_wysokosc_listy(self.lista_kart_serwis, self._page, wysokosc_pozycji=190)
                self.elementy.append(self.lista_kart_serwis)

        self.fab = self._buduj_fab_szybkich_akcji()
