"""„Dokumenty pojazdu” (N-05) — skarbiec skanów: dowód, polisy, umowa kupna, gwarancje,
instrukcja, z datą ważności. Dane: db/dokumenty.py; pliki: utils/zalaczniki.py."""

import flet as ft

import db
import utils


# Rodzaje, których brak podpowiada pasek „Dodaj” — reszta zostaje pod przyciskiem „+”.
PODSTAWOWE_RODZAJE = ("dowod", "oc", "przeglad", "umowa", "instrukcja")


class DokumentyView(ft.View):
    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state
        appbar = utils.zbuduj_pasek_z_powrotem(page, "Dokumenty pojazdu", "/", ikona=ft.Icons.FOLDER_SHARED)

        if not state.auto_id:
            super().__init__(
                route="/dokumenty", padding=15, spacing=15, appbar=appbar,
                controls=[utils.ekran_braku_danych(
                    ikona=ft.Icons.DIRECTIONS_CAR, tytul="Brak wybranego pojazdu",
                    opis="Dodaj pojazd, a jego dowód, polisa i umowa kupna będą tu pod ręką.",
                    tekst_przycisku="Dodaj pojazd", on_click=lambda e: utils.przejdz(self._page, "/auto/nowy"),
                )],
            )
            return

        self.moge_dodawac = db.czy_moge_dodawac(state.auto_id)
        dokumenty = db.dokumenty_pojazdu(state.auto_id)
        self.pliki = db.zalaczniki_pojazdu(state.auto_id, "dokumenty_pojazdu")
        aktualne = [d for d in dokumenty if not d["archiwalny"]]
        archiwalne = [d for d in dokumenty if d["archiwalny"]]

        elementy = []
        if not dokumenty:
            elementy.append(self._pusto())
        else:
            elementy.append(self._naglowek(aktualne))
            elementy.extend(self._karta(d) for d in aktualne)
        brakujace = self._brakujace(dokumenty) if dokumenty else None
        if brakujace:
            elementy.append(brakujace)
        if archiwalne:
            elementy.append(utils.etykieta("Poprzednie — starsze polisy i przeglądy"))
            elementy.extend(self._karta(d) for d in archiwalne)
        elementy.append(utils.dol_bezpieczny(80))  # miejsce pod FAB-em

        fab = utils.fab_animowany(ft.Icons.ADD, lambda e: utils.przejdz(self._page, "/dokumenty/nowy"),
                                  tooltip="Dodaj dokument") if self.moge_dodawac else None
        super().__init__(
            route="/dokumenty", padding=15, spacing=10, appbar=appbar,
            floating_action_button=fab, controls=elementy, scroll=ft.ScrollMode.AUTO,
        )

    # ================= AKCJE =================

    def _odswiez(self):
        utils.odswiez_ekran(self._page)

    def _usun(self, d):
        def wykonaj():
            wynik = db.usun_z_cofnieciem("dokumenty_pojazdu", d["id"])
            self._odswiez()
            utils.pokaz_komunikat_cofnij(self._page, f"Usunięto: {d['tytul']}.", wynik)

        tresc = "Pliki dokumentu znikną razem z nim."
        if d["z_karty"]:
            tresc += " Data na Karcie pojazdu zostaje."
        utils.potwierdz(self._page, "Usunąć dokument?", tresc, wykonaj)

    def _menu(self, d, pliki):
        async def udostepnij():
            await utils.udostepnij_pliki(self._page, [utils.abs_zalacznik(z["sciezka"]) for z in pliki])

        pozycje = utils.pozycje_menu_zalacznikow(self._page, "dokumenty_pojazdu", d["id"], pliki, d["tytul"],
                                                 self._odswiez)
        if pliki:
            pozycje.insert(1, {"ikona": ft.Icons.SHARE, "tekst": "Udostępnij pliki", "czyta": True,
                               "akcja": udostepnij})
        pozycje.append({"ikona": ft.Icons.EDIT, "tekst": "Edytuj dokument",
                        "akcja": lambda: utils.przejdz(self._page, f"/dokumenty/edytuj/{d['id']}")})
        pozycje.append({"ikona": ft.Icons.DELETE, "tekst": "Usuń dokument", "kolor": utils.KOLOR_STATUS["destructive"],
                        "akcja": lambda: self._usun(d)})
        pozycje = utils.odsiej_akcje(self.state.auto_id, pozycje, "dokumenty_pojazdu", d["id"])
        utils.pokaz_menu_kontekstowe(self._page, d["tytul"], pozycje)

    # ================= STANY I KARTY =================

    def _pusto(self):
        opis = ("Zdjęcia dowodu, polisy, umowy kupna, gwarancji i instrukcji w jednym miejscu — z datą "
                "ważności, o której przypomni dzwonek.")
        if not self.moge_dodawac:
            return ft.Container(padding=30, content=ft.Column([
                ft.Icon(ft.Icons.FOLDER_SHARED, size=46, color=ft.Colors.PRIMARY),
                ft.Text("Brak dokumentów", size=utils.FS["heading"], weight="bold"),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10))
        return ft.Column([
            utils.ekran_braku_danych(
                ikona=ft.Icons.FOLDER_SHARED, tytul="Skarbiec jest pusty", opis=opis,
                tekst_przycisku="Dodaj dokument", on_click=lambda e: utils.przejdz(self._page, "/dokumenty/nowy"),
            ),
            self._pasek_rodzajow(PODSTAWOWE_RODZAJE),
        ], spacing=0, tight=True)

    def _naglowek(self, aktualne):
        pilne = sum(1 for d in aktualne if d["status"] in ("po_terminie", "blisko"))
        tekst = db.liczba_z_odmiana(len(aktualne), "dokument", "dokumenty", "dokumentów")
        if pilne:
            tekst += f" · {db.liczba_z_odmiana(pilne, 'wymaga', 'wymagają', 'wymaga')} uwagi"
        return ft.Row([
            ft.Icon(ft.Icons.FOLDER_SHARED, size=16, color=ft.Colors.PRIMARY),
            utils.etykieta(f"{tekst} · od najbliższego terminu", expand=True),
        ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def _pasek_rodzajow(self, rodzaje):
        chipy = [
            ft.TextButton(db.etykieta_dokumentu(r), icon=utils.IKONY_DOKUMENTOW.get(r, ft.Icons.DESCRIPTION),
                          on_click=lambda e, r=r: utils.przejdz(self._page, f"/dokumenty/nowy/{r}"))
            for r in rodzaje
        ]
        return ft.Row(chipy, spacing=4, wrap=True, run_spacing=0, alignment=ft.MainAxisAlignment.CENTER)

    def _brakujace(self, dokumenty):
        if not self.moge_dodawac:
            return None
        jest = {d["rodzaj"] for d in dokumenty}
        brak = [r for r in PODSTAWOWE_RODZAJE if r not in jest]
        if not brak:
            return None
        return ft.Column([utils.etykieta("Brakuje jeszcze:"), self._pasek_rodzajow(brak)], spacing=2, tight=True)

    def _linia_daty(self, d):
        if not d["waznosc"]:
            return utils.podpis("Bez daty ważności")
        kolor = (utils.KOLORY_STATUSU_TERMINU.get(d["status"], ft.Colors.ON_SURFACE_VARIANT)
                 if d["status"] else ft.Colors.ON_SURFACE_VARIANT)
        czesci = [utils.wartosc(f"do {d['waznosc']}", size=utils.FS["body"], color=kolor)]
        if d["status"]:
            czesci.append(utils.podpis(utils.opis_dni_terminu(d["dni"]), color=kolor))
        if d["z_karty"]:
            czesci.append(utils.podpis("· data z Karty pojazdu"))
        return ft.Row([ft.Icon(ft.Icons.EVENT, size=15, color=kolor)] + czesci, spacing=6, wrap=True,
                      vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def _pasek_plikow(self, d, pliki):
        if pliki:
            miniatury = [
                utils.miniatura_zalacznika(self._page, utils.abs_zalacznik(z["sciezka"]), 48,
                                           on_click=lambda e: utils.pokaz_zalaczniki(self._page, pliki, d["tytul"]))
                for z in pliki[:4]
            ]
            if len(pliki) > 4:
                miniatury.append(utils.podpis(f"+{len(pliki) - 4}"))
            return ft.Row(miniatury, spacing=utils.SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.CENTER)
        if d["liczba_plikow"]:
            ile = db.liczba_z_odmiana(d["liczba_plikow"], "plik", "pliki", "plików")
            return ft.Row([ft.Icon(ft.Icons.PHONELINK, size=15, color=ft.Colors.ON_SURFACE_VARIANT),
                           utils.podpis(f"{ile} na innym telefonie — zdjęcia nie jadą do chmury")], spacing=6)
        return utils.podpis("Bez pliku — dodaj zdjęcie albo PDF z menu")

    def _karta(self, d):
        pliki = self.pliki.get(d["id"], [])
        opis = [x for x in (d["etykieta"] if d["nazwa"] else None, d["numer"]) if x]
        info = [utils.wartosc(d["tytul"])]
        if opis:
            info.append(utils.podpis(" · ".join(opis)))
        tresc = [
            ft.Row([
                ft.Icon(utils.IKONY_DOKUMENTOW.get(d["rodzaj"], ft.Icons.DESCRIPTION), size=22,
                        color=ft.Colors.ON_SURFACE_VARIANT if d["archiwalny"] else ft.Colors.PRIMARY),
                ft.Column(info, spacing=2, tight=True, expand=True),
                ft.IconButton(icon=ft.Icons.MORE_VERT, tooltip="Więcej", on_click=lambda e: self._menu(d, pliki)),
            ], spacing=utils.SPACING["md"], vertical_alignment=ft.CrossAxisAlignment.START),
            self._linia_daty(d),
            self._pasek_plikow(d, pliki),
        ]
        if d["notatki"]:
            tresc.append(utils.podpis(d["notatki"], max_lines=3, overflow=ft.TextOverflow.ELLIPSIS))
        kolor = utils.KOLORY_STATUSU_TERMINU.get(d["status"]) if d["status"] in ("po_terminie", "blisko") else None
        karta_ui, kontener = utils.karta_listy(ft.Column(tresc, spacing=utils.SPACING["sm"]), kolor_paska=kolor,
                                               page=self._page)
        kontener.on_click = utils.z_efektem_nacisniecia(
            kontener, lambda e: utils.pokaz_zalaczniki(self._page, pliki, d["tytul"]) if pliki else self._menu(d, pliki))
        return karta_ui


__all__ = [
    "DokumentyView",
]
