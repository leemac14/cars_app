"""Zakładka Koszty → Inne: pozostałe wydatki i przełącznik podzakładek."""

import db
import flet as ft
import sqlite3
import sync
import utils
from date import parsuj_date


class MiksinZakladkiInne:
    """Zakładka Koszty → Inne: pozostałe wydatki i przełącznik podzakładek."""

    def buduj_inne(self):
        wspolny_id, _ = sync.czy_udostepniony(self.state.auto_id)
        naglowek_inne = utils.tytul_sekcji(ft.Icons.RECEIPT_LONG, "Inne koszty")
        if wspolny_id:
            naglowek_inne.append(utils.przycisk_synchronizacji(self._page, self._synchronizuj_teraz))
        self.elementy.append(ft.Row(naglowek_inne, vertical_alignment=ft.CrossAxisAlignment.CENTER))

        with db.polacz_baze() as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT * FROM inne_koszty WHERE auto_id=?", (self.state.auto_id,))
            baza_lista = [dict(row) for row in c.fetchall()]

        # Pusta kategoria (wpisy sprzed słownika) czyta się jako „Ogólne” — inaczej
        # filtr pokazywałby bezimienną pozycję, a karta pusty chip.
        for w in baza_lista:
            w["kategoria"] = db.etykieta_kategorii_innych(w.get("kategoria"))

        if not baza_lista:
            self.elementy.append(utils.ekran_braku_danych(
                ikona=ft.Icons.RECEIPT_LONG,
                tytul="Brak kosztów",
                opis="Dodaj opłaty takie jak ubezpieczenie, myjnia, autostrady czy raty leasingu.",
                tekst_przycisku="Dodaj wydatek",
                on_click=lambda e: utils.przejdz(self._page, "/inne/nowy")
            ))
        else:
            opcje_sort = [
                ("Data", "data", lambda x: (parsuj_date(x.get('data')), x.get('id', 0))),
                ("Kategoria", "kategoria", lambda x: str(x.get('kategoria') or "").lower()),
                ("Kwota", "kwota", lambda x: float(x.get('kwota') or 0)),
            ]

            sort_ui = utils.przycisk_sortowania(self._page, self.state, "inne", opcje_sort)
            filtr_rok_ui = utils.przycisk_filtrowania_rok(self._page, self.state, "inne_rok", baza_lista, "data")
            filtr_mc_ui = utils.przycisk_filtrowania_miesiac(self._page, self.state, "inne_mc", baza_lista, "data")
            filtr_kat_ui = utils.przycisk_filtrowania_kategoria(self._page, self.state, "inne_kat", baza_lista, "kategoria", "Kategoria")

            filtry_ui = [sort_ui, filtr_rok_ui, filtr_mc_ui, filtr_kat_ui]
            if wspolny_id:
                filtry_ui.append(
                    utils.przycisk_filtrowania_autora(self._page, self.state, "inne_autor", baza_lista, "dodane_przez")
                )

            self.elementy.append(
                ft.Row(
                    controls=filtry_ui,
                    scroll=ft.ScrollMode.ADAPTIVE,
                    spacing=8
                )
            )

            def filtruj_inne(e):
                zapytanie = e.control.value.lower().strip()
                self.miesiace_inne.ustaw(
                    [k for k in self.wszystkie_karty_inne if zapytanie in k["szukaj"]],
                    grupuj=utils.czy_po_dacie(self.state, "inne"),
                )
                utils.dopasuj_wysokosc_listy(self.lista_kart_inne, self._page, wysokosc_pozycji=190)
                self.update()

            self.elementy.append(
                ft.TextField(
                    hint_text="Szukaj kosztu (opis, kategoria, kwota, data, notatka)...",
                    prefix_icon=ft.Icons.SEARCH,
                    on_change=utils.z_opoznieniem(self._page, filtruj_inne),
                    **utils.styl_pola()
                )
            )
            self.lista_kart_inne = ft.ListView(spacing=15, padding=0, height=utils.wysokosc_listy(self._page), auto_scroll=False)
            utils.pamietaj_pozycje(self._page, self.state, self.lista_kart_inne, "lista:koszty_inne")
            self.uzyj_wirtualizacji = True
            self.wszystkie_karty_inne = []
            self.miesiace_inne = utils.GrupyMiesiecy(
                self._page, self.lista_kart_inne, wysokosc_pozycji=190
            )

            po_filtrach = utils.filtruj_po_roku(baza_lista, self.state, "inne_rok", "data")
            po_filtrach = utils.filtruj_po_miesiacu(po_filtrach, self.state, "inne_mc", "data")
            po_filtrach = utils.filtruj_po_kategorii(po_filtrach, self.state, "inne_kat", "kategoria")
            if wspolny_id:
                po_filtrach = utils.filtruj_po_autorze(po_filtrach, self.state, "inne_autor", "dodane_przez")
            utils.posortuj_liste(po_filtrach, self.state, "inne", opcje_sort)

            # Menu kosztu składa się tak samo jak menu tankowania i wpisu
            # serwisowego — słownikami przez pokaz_menu_kontekstowe. Ręcznie
            # budowany BottomSheet robił to samo o kilkanaście linii dłużej
            # (własne zamykanie arkusza przy każdej pozycji) i, co ważniejsze,
            # nie dawał się przepuścić przez utils.odsiej_akcje.
            def otworz_menu_i(iid, zalacznik=None, notatka=None):
                def usun_koszt():
                    def wykonaj():
                        wynik = db.usun_z_cofnieciem("inne_koszty", iid)
                        utils.przejdz(self._page, "/")
                        utils.pokaz_komunikat_cofnij(self._page, "Usunięto koszt.", wynik)
                    utils.potwierdz(self._page, "Usunąć?", "Czy na pewno usunąć ten koszt?", wykonaj)

                async def dodaj_zmien_zdj():
                    await utils.szybkie_dodanie_zdjecia(self._page, "inne_koszty", iid, zalacznik, lambda: utils.przejdz(self._page, "/"))

                pozycje = []
                if zalacznik:
                    pozycje.append({"ikona": ft.Icons.IMAGE, "tekst": "Pokaż zdjęcie", "czyta": True,
                                    "akcja": lambda: utils.pokaz_podglad_zalacznika(self._page, zalacznik, "Koszt")})
                    pozycje.append({"ikona": ft.Icons.EDIT_DOCUMENT, "tekst": "Zmień zdjęcie", "akcja": dodaj_zmien_zdj})
                else:
                    pozycje.append({"ikona": ft.Icons.ADD_A_PHOTO, "tekst": "Dodaj zdjęcie (faktura/paragon)", "akcja": dodaj_zmien_zdj})

                pozycje.append(utils.pozycja_menu_notatki(
                    self._page, "inne_koszty", iid, notatka,
                    lambda: utils.przejdz(self._page, "/"), "Notatka do kosztu"
                ))
                pozycje.append({"ikona": ft.Icons.EDIT, "tekst": "Edytuj koszt",
                                "akcja": lambda: utils.przejdz(self._page, f"/inne/edytuj/{iid}")})
                pozycje.append({"ikona": ft.Icons.CONTENT_COPY, "tekst": "Duplikuj",
                                "akcja": lambda: (setattr(self.state, "duplikuj_zrodlo_koszt", iid),
                                                  utils.przejdz(self._page, "/inne/nowy"))})
                pozycje.append({"ikona": ft.Icons.DELETE, "tekst": "Usuń koszt", "akcja": usun_koszt,
                                "kolor": utils.KOLOR_STATUS["destructive"]})

                pozycje = utils.odsiej_akcje(self.state.auto_id, pozycje, "inne_koszty", iid)
                utils.pokaz_menu_kontekstowe(self._page, "Opcje kosztu", pozycje)

            if not po_filtrach:
                self.elementy.append(ft.Row([ft.Text("Brak wyników dla tych filtrów.", color=ft.Colors.ON_SURFACE_VARIANT)], alignment=ft.MainAxisAlignment.CENTER))
            else:
                mapa_tagow = {t[1]: t[2] for t in db.pobierz_tagi(self.state.auto_id)}
                for w in po_filtrach:
                    cena_str = f"{utils.formatuj_liczba(float(w.get('kwota') or 0))}  {utils.symbol_waluty()}"
                    iid = w.get('id')
                    tresc_i = [
                        ft.Row([
                            utils.podpis(str(w.get('data')), expand=True),
                            ft.Row([
                                utils.wskaznik_zalacznika(self._page, w.get('zalacznik'), "Koszt"),
                                ft.Text(f"-{cena_str}", weight="bold", color=utils.KOLOR_STATUS["cost"])
                            ], spacing=6)
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Text(str(w.get('nazwa')) if w.get('nazwa') else "Brak opisu", size=16, weight="bold"),
                        # Kategoria ma własny chip z ikoną i stoi PRZED tagami:
                        # to ona odpowiada na pytanie „co to za wydatek”, tagi są
                        # dodatkiem. Wcześniej jedno i drugie leciało do tej samej
                        # linijki tagów, więc opłata drogowa wyglądała jak tag.
                        ft.Row([
                            utils.odznaka_kategorii_innych(w.get('kategoria')),
                            ft.Container(
                                content=utils.wizualizacja_tagow(w.get('tagi'), self.state.auto_id, mapa_tagow),
                                expand=True,
                            ),
                        ], spacing=6, wrap=False, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    ]
                    tresc_i.append(utils.podglad_notatki(
                        self._page, w.get('notatka'), w.get('notatka_autor'), w.get('notatka_data'),
                        "Notatka do kosztu",
                        on_edytuj=lambda rid=iid: utils.szybka_notatka(
                            self._page, "inne_koszty", rid,
                            lambda: utils.przejdz(self._page, "/"), "Notatka do kosztu"
                        ),
                        pokaz_podpis=bool(wspolny_id)
                    ))
                    if wspolny_id and (w.get('dodane_przez') or w.get('zmodyfikowane_przez')):
                        tresc_i.append(utils.znacznik_atrybucji(w.get('dodane_przez'), w.get('zmodyfikowane_przez'), w.get('data_modyfikacji')))
                    kontener = ft.Container(padding=15, border_radius=10, ink=True, content=ft.Column(tresc_i))

                    self.karty_ref[iid] = kontener
                    self.podepnij_zdarzenia_grupowe(kontener, iid, lambda id_el=iid, zal=w.get('zalacznik'), nt=w.get('notatka'): otworz_menu_i(id_el, zal, nt), "inne_koszty")

                    karta_i = ft.Card(elevation=1, content=kontener)
                    tekst_szukaj = f"{w.get('data')} {w.get('nazwa')} {w.get('kategoria')} {cena_str} {w.get('notatka') or ''}".lower()
                    self.wszystkie_karty_inne.append({
                        "karta": karta_i, "szukaj": tekst_szukaj,
                        "data": w.get('data'), "kwota": float(w.get('kwota') or 0),
                    })

                self.miesiace_inne.ustaw(
                    self.wszystkie_karty_inne,
                    grupuj=utils.czy_po_dacie(self.state, "inne"),
                )
                utils.dopasuj_wysokosc_listy(self.lista_kart_inne, self._page, wysokosc_pozycji=190)
                self.elementy.append(self.miesiace_inne.kontrolka)
                self.elementy.append(self.lista_kart_inne)

        self.fab = self._buduj_fab_szybkich_akcji()
