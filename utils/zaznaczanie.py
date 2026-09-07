"""Tryb zaznaczania wielu pozycji na listach."""

import flet as ft

from .formularze import dopasuj_wysokosc_listy


class ZaznaczanieGrupowe:
    """Mixin: obsługa zaznaczania wielu kart + appbar trybu zaznaczania.
    Klasa używająca mixinu musi ustawić self.oryginalny_appbar i self.karty_ref
    oraz zaimplementować własne potwierdz_grupowe_usuwanie (bo logika usuwania
    i ewentualne przeliczenia różnią się w zależności od widoku)."""

    def dostosuj_wysokosc_listy(self):
        """Metoda wywoływana przy zdarzeniu on_resized ekranu.
        Dynamicznie przelicza wysokość dla wszystkich list wirtualizowanych w widoku.

        Liczy DOKŁADNIE tak samo jak dopasuj_wysokosc_listy przy budowie widoku
        (bierze pod uwagę liczbę kart), więc obrót ekranu nie przywraca pustego
        prostokąta pod krótką listą."""
        if not getattr(self, "uzyj_wirtualizacji", False):
            return

        try:
            # Flet View ma domyślnie właściwość .page, ale wspieramy też Twoje self._page
            strona = getattr(self, "page", None) or getattr(self, "_page", None)
            if not strona: return

            # Magia Pythona: dynamicznie szukamy atrybutów, które nazwałeś jako 'lista_kart...'
            for nazwa_atrybutu in dir(self):
                if nazwa_atrybutu.startswith("lista_kart"):
                    lista = getattr(self, nazwa_atrybutu)
                    if not hasattr(lista, "height"):
                        continue
                    poprzednia = lista.height
                    dopasuj_wysokosc_listy(
                        lista, strona,
                        wysokosc_pozycji=getattr(lista, "_wys_pozycji", 175),
                        na_wiersz=getattr(lista, "_na_wiersz", 1),
                        udzial=getattr(lista, "_udzial_ekranu", 0.5),
                    )
                    if lista.height != poprzednia:
                        lista.update()
        except Exception:
            pass

    def zakoncz_zaznaczanie(self, e=None):
        self.tryb_zaznaczania = False
        self.zaznaczone_id.clear()
        self.appbar = self.oryginalny_appbar
        for kontener in self.karty_ref.values():
            kontener.bgcolor = None
            kontener.border = None
        self.update()

    def aktualizuj_appbar_zaznaczania(self, dodatkowe_akcje=None):
        akcje = list(dodatkowe_akcje or [])
        akcje.append(ft.IconButton(ft.Icons.DELETE, icon_color=ft.Colors.RED_700, tooltip="Usuń zaznaczone", on_click=self.potwierdz_grupowe_usuwanie))
        akcje.append(ft.Container(width=10))
        self.appbar = ft.AppBar(
            leading=ft.IconButton(ft.Icons.CLOSE, on_click=self.zakoncz_zaznaczanie),
            title=ft.Text(f"Zaznaczono: {len(self.zaznaczone_id)}", weight="bold"),
            bgcolor=ft.Colors.with_opacity(0.2, ft.Colors.PRIMARY),
            actions=akcje
        )
        self.update()

    def zaznacz_odznacz(self, element_id, kontener):
        if element_id in self.zaznaczone_id:
            self.zaznaczone_id.remove(element_id)
            kontener.bgcolor = None
            kontener.border = None
        else:
            self.zaznaczone_id.add(element_id)
            kontener.bgcolor = ft.Colors.with_opacity(0.15, ft.Colors.PRIMARY)
            kontener.border = ft.Border.all(2, ft.Colors.PRIMARY)

        if not self.zaznaczone_id:
            self.zakoncz_zaznaczanie()
        else:
            self.aktualizuj_appbar_zaznaczania()

    def podepnij_zdarzenia_grupowe(self, kontener, element_id, callback_pojedynczy, tabela=None):
        def _on_click(e):
            if self.tryb_zaznaczania:
                if tabela is None or getattr(self, "tabela_cel", tabela) == tabela:
                    self.zaznacz_odznacz(element_id, kontener)
            else:
                callback_pojedynczy()

        def _on_long_press(e):
            if not self.tryb_zaznaczania:
                self.tryb_zaznaczania = True
                if tabela is not None:
                    self.tabela_cel = tabela
                self.zaznacz_odznacz(element_id, kontener)

        kontener.on_click = _on_click
        kontener.on_long_press = _on_long_press


__all__ = [
    "ZaznaczanieGrupowe",
]
