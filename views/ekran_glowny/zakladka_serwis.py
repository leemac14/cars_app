"""Zakładka Serwis: podzespoły, interwały i historia wpisów."""

import db
import flet as ft
import sqlite3
import sync
import utils
from date import parsuj_date


# Status podzespołu (db.oblicz_stan_interwalu) -> kolor paska karty i ikona.
STATUS_KARTY_PODZESPOLU = {
    "przeterminowane": (utils.KOLOR_STATUS["critical"], ft.Icons.WARNING),
    "pilne": (utils.KOLOR_STATUS["warning"], ft.Icons.HOURGLASS_BOTTOM),
    "ok": (utils.KOLOR_STATUS["ok"], ft.Icons.CHECK_CIRCLE),
}


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
            chipy_filtrow, serwis_po_filtrach = utils.pasek_filtrow(
                self._page, self.state, baza_lista,
                [("rok", "serwis_rok", "data"), ("miesiac", "serwis_mc", "data")])

            self.elementy.append(
                ft.Row(
                    controls=[sort_ui] + chipy_filtrow,
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
            utils.pamietaj_pozycje(self._page, self.state, self.lista_kart_serwis, "lista:serwis")
            self.uzyj_wirtualizacji = True
            self.wszystkie_karty_serwis = []

            po_filtrach = serwis_po_filtrach
            utils.posortuj_liste(po_filtrach, self.state, "zadania", opcje_sort)

            self.tekst_licznik_zadan.value = f"Śledzone podzespoły ({len(po_filtrach)})"

            def pokaz_menu(zid, zn):
                self.state.wybrane_zadanie_id = zid
                self.state.wybrane_zadanie_nazwa = str(zn)

                def usun_zadanie():
                    def wykonaj():
                        wynik = db.usun_zadanie_z_cofnieciem(zid)
                        utils.przejdz(self._page, "/")
                        utils.pokaz_komunikat_cofnij(self._page, "Usunięto podzespół.", wynik)
                    utils.potwierdz(self._page, "Usunąć?", "Na pewno usunąć ten podzespół?", wykonaj)

                # Jak w pozostałych zakładkach: słowniki zamiast ręcznego
                # BottomSheetu, żeby menu dało się przepuścić przez
                # utils.odsiej_akcje. Historia wymian to jedyna pozycja, która
                # niczego nie zmienia — przy podglądzie zostaje tylko ona.
                pozycje = utils.odsiej_akcje(self.state.auto_id, [
                    {"ikona": ft.Icons.ADD_CIRCLE, "tekst": "Dodaj Wymianę", "kolor": ft.Colors.GREEN,
                     "akcja": lambda: utils.przejdz(self._page, f"/wpis/nowy/{zid}")},
                    {"ikona": ft.Icons.HISTORY, "tekst": "Historia wymian", "czyta": True,
                     "akcja": lambda: utils.przejdz(self._page, f"/historia/{zid}")},
                    {"ikona": ft.Icons.TIMER, "tekst": "Ustaw interwał przypomnień",
                     "akcja": lambda: utils.przejdz(self._page, f"/interwal/{zid}")},
                    {"ikona": ft.Icons.EDIT, "tekst": "Zmień nazwę",
                     "akcja": lambda: utils.przejdz(self._page, f"/zadanie/edytuj/{zid}")},
                    {"ikona": ft.Icons.DELETE, "tekst": "Usuń podzespół", "akcja": usun_zadanie,
                     "kolor": utils.KOLOR_STATUS["destructive"]},
                ], "zadania", zid)
                utils.pokaz_menu_kontekstowe(self._page, str(zn), pozycje)

            if not po_filtrach:
                self.elementy.append(ft.Row([ft.Text("Brak wyników dla tych filtrów.", color=ft.Colors.ON_SURFACE_VARIANT)], alignment=ft.MainAxisAlignment.CENTER))
            else:
                for z in po_filtrach:
                    # Oba liczniki liczy to samo miejsce, co powiadomienia — karta
                    # i dzwonek nie mogą się nie zgadzać co do tego, co jest pilne
                    # ani który licznik skończy się pierwszy.
                    stan_interwalu = db.oblicz_stan_interwalu(
                        z, akt_prz, sredni_dzienny, prog_km=prog_km, prog_dni=prog_dni)
                    wiersz_statusu = utils.liczniki_interwalu(
                        stan_interwalu, scena=self._scena_zakladki, page=self._page)

                    if wiersz_statusu is not None:
                        kol, ico = STATUS_KARTY_PODZESPOLU[stan_interwalu["status"]]
                        final_status = " ".join(
                            " ".join(utils.opis_licznika_na_karte(stan_interwalu[r]))
                            for r in ("km", "czas") if stan_interwalu[r])
                    else:
                        final_status = "Brak interwału" if not z.get('interwal_km') and not z.get('interwal_miesiace') else "Brak wpisów"
                        kol, ico = ft.Colors.ON_SURFACE_VARIANT, ft.Icons.INFO_OUTLINE
                        # „Brak wpisów" i „Brak interwału" to informacja o BRAKU
                        # danych, a nie status pilności — pogrubione konkurowały
                        # z nazwą podzespołu nad nimi, nie mając czego powiedzieć.
                        wiersz_statusu = utils.etykieta(final_status, size=utils.FS["body_strong"])

                    data_w = str(z.get('data')) if z.get('data') else '-'
                    prz_w = f"{utils.formatuj_liczba(int(z.get('przebieg')), 0)} km" if z.get('przebieg') else '-'

                    zid = z.get('id')
                    zn = z.get('nazwa')
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
