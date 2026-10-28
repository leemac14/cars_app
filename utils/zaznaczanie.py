"""Tryb zaznaczania wielu pozycji na listach."""

import flet as ft

from .stale import KOLOR_STATUS
from .sync_ui import wolno_zmieniac_rekord


class ZaznaczanieGrupowe:
    """Mixin: obsługa zaznaczania wielu kart + appbar trybu zaznaczania.
    Klasa używająca mixinu musi ustawić self.oryginalny_appbar i self.karty_ref
    oraz zaimplementować własne potwierdz_grupowe_usuwanie (bo logika usuwania
    i ewentualne przeliczenia różnią się w zależności od widoku)."""

    def zapomnij_listy_kart(self):
        """Kasuje `lista_kart*` i `wszystkie_karty*` po liście, która zeszła z ekranu —
        filtr albo zaznaczanie nie mają prawa sięgnąć do kart poprzedniej zakładki."""
        for nazwa in [n for n in list(vars(self)) if n.startswith(("lista_kart", "wszystkie_karty"))]:
            delattr(self, nazwa)

    def _oddaj_tlo(self, element_id, kontener):
        """Tło karty sprzed zaznaczenia — karta listy ma własne, nieprzezroczyste (pod nim
        leży cień), więc odznaczenie je oddaje zamiast zerować. Zapis innej karty (inna
        zakładka) się nie liczy."""
        kontener_tla, tlo = getattr(self, "_tla_kart", {}).pop(element_id, (None, None))
        kontener.bgcolor = tlo if kontener_tla is kontener else None

    def zakoncz_zaznaczanie(self, e=None):
        self.tryb_zaznaczania = False
        self.zaznaczone_id.clear()
        self.appbar = self.oryginalny_appbar
        for element_id, kontener in self.karty_ref.items():
            if element_id in getattr(self, "_tla_kart", {}):
                self._oddaj_tlo(element_id, kontener)
            kontener.border = None
        self._tla_kart = {}
        self.update()

    def wolno_zmieniac_zaznaczone(self):
        """Czy pasek zaznaczania pokazuje akcje zmieniające dane. Pytanie o samą rolę:
        podglądowi nie (db i tak nic nie skasuje); współautorowi tak —
        usun_wiele_z_cofnieciem kasuje jego wpisy i melduje pominięte cudze."""
        auto_id = getattr(getattr(self, "state", None), "auto_id", None)
        return wolno_zmieniac_rekord(auto_id)

    def aktualizuj_appbar_zaznaczania(self, dodatkowe_akcje=None):
        akcje = list(dodatkowe_akcje or [])
        if self.wolno_zmieniac_zaznaczone():
            akcje.append(ft.IconButton(ft.Icons.DELETE, icon_color=KOLOR_STATUS["destructive"], tooltip="Usuń zaznaczone", on_click=self.potwierdz_grupowe_usuwanie))
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
            self._oddaj_tlo(element_id, kontener)
            kontener.border = None
        else:
            self.zaznaczone_id.add(element_id)
            if not hasattr(self, "_tla_kart"):
                self._tla_kart = {}
            self._tla_kart[element_id] = (kontener, kontener.bgcolor)
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
