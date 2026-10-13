"""„Dolewki płynów” (N-12) — dolewki jednego płynu w okresach między wymianami, zużycie i ostrzeżenia.
Dane: db/dolewki.py; karta i słupki: utils/dolewki.py. Formularz leży NA tym ekranie (main.py)."""

import flet as ft

import db
import sync
import utils


class DolewkiView(ft.View):
    def __init__(self, page: ft.Page, state, plyn=None):
        self._page = page
        self.state = state
        trasa = f"/dolewki/{plyn}" if plyn else "/dolewki"
        akcje = None
        if state.auto_id and sync.czy_udostepniony(state.auto_id)[0]:
            akcje = [utils.przycisk_synchronizacji(page, utils.funkcja_szybkiej_synchronizacji(page, state.auto_id, trasa))]
        appbar = utils.zbuduj_pasek_z_powrotem(page, "Dolewki płynów", "/", akcje_dodatkowe=akcje, ikona=ft.Icons.WATER_DROP)

        if not state.auto_id:
            super().__init__(route=trasa, padding=15, spacing=15, appbar=appbar, controls=[utils.ekran_braku_danych(
                ikona=ft.Icons.DIRECTIONS_CAR, tytul="Brak wybranego pojazdu",
                opis="Dodaj pojazd, a dolewki oleju i płynów policzą jego zużycie między wymianami.",
                tekst_przycisku="Dodaj pojazd", on_click=lambda e: utils.przejdz(self._page, "/auto/nowy"),
            )])
            return

        self.moge_dodawac = db.czy_moge_dodawac(state.auto_id)
        self.j = utils.jednostka_dystansu()
        self.zuzycie = db.zuzycie_plynow(state.auto_id)
        plyny = db.plyny_pojazdu(state.auto_id)
        if plyn in db.RODZAJE_PLYNOW and plyn not in plyny:
            plyny.append(plyn)
        self.plyn = self._wybierz_plyn(plyn, plyny)
        state.dolewki_plyn = self.plyn

        elementy = [utils.pasek_plynow(plyny, self.plyn, self._zmien_plyn,
                                       {p: z["liczba"] for p, z in self.zuzycie.items()})]
        z = self.zuzycie.get(self.plyn)
        if not z:
            elementy.append(self._pusto())
        else:
            elementy.append(utils.karta_zuzycia(page, z, self.j))
            elementy.extend(self._okresy(z))
        elementy.append(utils.nota_o_liczeniu(page, "Jak liczone", self._opis_liczenia()))
        elementy.append(utils.dol_bezpieczny(80))  # miejsce pod FAB-em

        fab = utils.fab_animowany(ft.Icons.ADD, lambda e: utils.przejdz(self._page, f"/dolewki/nowa/{self.plyn}"),
                                  tooltip="Dodaj dolewkę") if self.moge_dodawac else None
        super().__init__(route=trasa, padding=15, spacing=12, appbar=appbar, floating_action_button=fab,
                         controls=elementy, scroll=ft.ScrollMode.AUTO)

    def _wybierz_plyn(self, plyn, plyny):
        """Z trasy, z pamięci ekranu, a bez nich — ostatnio dolewany, potem pierwszy z listy."""
        for kandydat in (plyn, getattr(self.state, "dolewki_plyn", None)):
            if kandydat in plyny:
                return kandydat
        ostatnie = sorted(self.zuzycie.values(), key=lambda z: (z["ostatnia"]["data_iso"] or "", z["ostatnia"]["id"]))
        return ostatnie[-1]["plyn"] if ostatnie else (plyny[0] if plyny else db.PLYN_OLEJ)

    def _zmien_plyn(self, plyn):
        utils.przejdz(self._page, f"/dolewki/{plyn}")

    # ================= AKCJE =================

    def _usun(self, d):
        def wykonaj():
            wynik = db.usun_dolewke_z_cofnieciem(d["id"])
            utils.odswiez_ekran(self._page)
            utils.pokaz_komunikat_cofnij(self._page, "Usunięto dolewkę.", wynik)

        tresc = "Litry z magazynu wrócą na półkę." if d["magazyn_id"] and d["ilosc_magazynu"] else "Wpis zniknie z listy."
        if d["koszt_id"]:
            tresc += " Jej koszt zniknie z Innych kosztów."
        utils.potwierdz(self._page, "Usunąć dolewkę?", tresc, wykonaj)

    def _menu(self, d):
        pozycje = utils.odsiej_akcje(self.state.auto_id, [
            {"ikona": ft.Icons.EDIT, "tekst": "Edytuj dolewkę",
             "akcja": lambda: utils.przejdz(self._page, f"/dolewki/edytuj/{d['id']}")},
            {"ikona": ft.Icons.DELETE, "tekst": "Usuń dolewkę", "kolor": utils.KOLOR_STATUS["destructive"],
             "akcja": lambda: self._usun(d)},
        ], "dolewki", d["id"])
        utils.pokaz_menu_kontekstowe(self._page, f"Dolewka {d['data']}", pozycje)

    # ================= TREŚĆ =================

    def _pusto(self):
        nazwa = db.RODZAJE_PLYNOW[self.plyn]["w_zdaniu"]
        opis = (f"Zapisz każdą dolewkę — {nazwa}, ilość i przebieg. Z kolejnych dolewek wyjdzie zużycie na "
                f"1000 {db.slowo_dystansu('skrot', self.j)} między wymianami.")
        if not self.moge_dodawac:
            return ft.Container(padding=30, content=utils.podpis(opis, text_align=ft.TextAlign.CENTER))
        return utils.ekran_braku_danych(
            ikona=utils.IKONY_PLYNOW.get(self.plyn, ft.Icons.WATER_DROP), tytul="Brak dolewek", opis=opis,
            tekst_przycisku="Dodaj dolewkę",
            on_click=lambda e: utils.przejdz(self._page, f"/dolewki/nowa/{self.plyn}"),
        )

    def _wiersz_dolewki(self, d):
        czesci = [utils.formatuj_dystans(d["przebieg"], 0, self.j) if d["przebieg"] else "bez przebiegu"]
        if d["produkt"]:
            czesci.append(d["produkt"])
        if d["magazyn_nazwa"]:
            czesci.append("z magazynu" if d["magazyn_nazwa"] == d["produkt"] else f"z magazynu: {d['magazyn_nazwa']}")
        if d["koszt"] is not None:
            czesci.append(f"{utils.formatuj_liczba(d['koszt'])} {utils.symbol_waluty()}")
        opis = [utils.podpis(" · ".join(czesci))]
        if d["notatka"]:
            opis.append(utils.podpis(d["notatka"], italic=True, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS))
        return ft.Container(
            padding=ft.Padding(0, 6, 0, 6), ink=True, border_radius=utils.RADIUS["sm"],
            on_click=lambda e: self._menu(d),
            content=ft.Row([
                ft.Icon(ft.Icons.WATER_DROP, size=16, color=utils.KOLORY_PLYNOW.get(d["plyn"])),
                ft.Column([ft.Row([utils.wartosc(db.tekst_litrow(d["ilosc"])), utils.etykieta(d["data"])], spacing=8),
                           *opis], spacing=2, tight=True, expand=True),
                ft.Icon(ft.Icons.MORE_VERT, size=18, color=ft.Colors.ON_SURFACE_VARIANT),
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.START),
        )

    def _okresy(self, z):
        """Karta na okres, od najnowszego: nagłówek z kilometrami i zużyciem, pod nim jego dolewki."""
        karty = []
        for okres in reversed(z["okresy"]):
            if okres["trwa"]:
                tytul = f"Bieżący okres · od {okres['od_data']}" if okres["od_data"] else "Bieżący okres"
            else:
                tytul = f"{okres['od_data'] or '…'} – {okres['do_data'] or '…'}"
            wynik = (db.tekst_zuzycia(okres["na_1000"], self.j) if okres["na_1000"] is not None
                     else f"za mało {db.slowo_dystansu('dopelniacz_pelny', self.j)} do oceny")
            kolor = (utils.KOLOR_STATUS[utils.ROLE_STATUSU[db.status_zuzycia(okres["na_1000"])]]
                     if z["ocena"] == db.OCENA_OLEJU and okres["na_1000"] is not None else None)
            tresc = [
                ft.Row([utils.wartosc(tytul, expand=True), utils.wartosc(wynik, color=kolor) if kolor else utils.etykieta(wynik)],
                       spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                utils.podpis(f"{utils.formatuj_dystans(okres['od_przebieg'], 0, self.j)}"
                             f"{' (pierwsza dolewka)' if okres['od_dolewki'] else ''} · {db.opis_okresu(okres, self.j)}"),
            ]
            tresc += [self._wiersz_dolewki(d) for d in reversed(okres["dolewki"])]
            karta, _kontener = utils.karta_listy(ft.Column(tresc, spacing=4), kolor_paska=kolor, page=self._page)
            karty.append(karta)
        if z["bez_przebiegu"]:
            tresc = [utils.wartosc("Bez przebiegu — poza zużyciem")]
            tresc += [self._wiersz_dolewki(d) for d in reversed(z["bez_przebiegu"])]
            karty.append(utils.karta_listy(ft.Column(tresc, spacing=4), page=self._page)[0])
        return karty

    def _opis_liczenia(self):
        jednostka = db.slowo_dystansu("skrot", self.j)
        return (f"Zużycie to litry dolane od wymiany podzielone przez {db.slowo_dystansu('dopelniacz_pelny', self.j)} "
                f"od wymiany do OSTATNIEJ dolewki, razy 1000 — tego, co przejechane po niej, nikt jeszcze nie zmierzył. Dolewaj "
                f"zawsze do tego samego poziomu (np. do kreski max), wtedy liczba jest dokładna. Wynik pokazuje się "
                f"od {utils.formatuj_dystans(db.MIN_KM_POMIARU, 0, self.j)} pomiaru; zamknięty okres bez dolewek to zero. "
                f"Wymiany to wpisy podzespołu z nazwą płynu (np. „Olej silnikowy i filtr”). Olej: do ok. "
                f"{db.tekst_zuzycia(db.PROG_ZUZYCIA_PODWYZSZONEGO, self.j)} mechanicy uznają za normę, instrukcje wielu "
                f"aut dopuszczają {db.tekst_zuzycia(db.PROG_ZUZYCIA_WYSOKIEGO, self.j)}, ale na co dzień to już dużo; "
                f"„rośnie” — półtora raza więcej niż we wcześniejszych okresach. Płyn chłodniczy i hamulcowy krążą "
                f"w zamkniętym układzie: dwie dolewki w roku to sygnał ubytku. Wartości w l/1000 {jednostka}.")


__all__ = [
    "DolewkiView",
]
