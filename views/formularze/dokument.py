"""Formularz dokumentu ze skarbca (N-05): rodzaj, nazwa, numer, daty i strony skanu.
Polisa, przegląd, assistance i gwarancja producenta dzielą datę z Kartą pojazdu."""

import flet as ft

import db
import log
import utils
from date import na_iso


# Podpowiedź nazwy po rodzaju — przy polisie to towarzystwo, przy innej gwarancji jej przedmiot.
PODPOWIEDZI_NAZWY = {
    "oc": "np. PZU, Warta", "ac": "np. PZU, Warta", "assistance": "np. Mondial",
    "gwarancja_inna": "np. akumulator Varta", "umowa": "np. od pana Kowalskiego",
    "instrukcja": "np. instrukcja radia", "inne": "np. karta parkingowa, winieta",
}


class FormularzDokumentuView(ft.View):
    def __init__(self, page: ft.Page, state, dokument_id=None, rodzaj=None):
        self._page = page
        self.state = state
        self.dokument_id = dokument_id
        dokument = db.pobierz_dokument(dokument_id) if dokument_id else None
        if dokument and dokument["auto_id"] != state.auto_id:
            dokument, self.dokument_id = None, None
        rodzaje = [k for k, _, _ in db.RODZAJE_DOKUMENTOW]
        rodzaj = (dokument or {}).get("rodzaj") or (rodzaj if rodzaj in rodzaje else "dowod")
        if rodzaj not in rodzaje:  # rodzaj z nowszej wersji aplikacji — zostaje przy edycji
            rodzaje.append(rodzaj)
        self._dane_karty = (db.pobierz_dane_pojazdu(state.auto_id) or {}) if state.auto_id else {}
        # Data do pola: aktualny dokument z datą Karty pokazuje ją, nowy — podpowiada.
        if dokument:
            biezacy = next((d for d in db.dokumenty_pojazdu(state.auto_id) if d["id"] == self.dokument_id), None)
            waznosc = (biezacy or {}).get("waznosc") or ""
        else:
            waznosc = db.data_z_karty(state.auto_id, rodzaj) or ""

        self.e_rodzaj = ft.Dropdown(
            label="Rodzaj dokumentu", value=rodzaj, on_select=lambda e: self._zmiana_rodzaju(),
            options=[ft.DropdownOption(key=k, text=db.etykieta_dokumentu(k),
                                       leading_icon=utils.IKONY_DOKUMENTOW.get(k, ft.Icons.DESCRIPTION))
                     for k in rodzaje],
            **utils.styl_dropdown(),
        )
        self.e_nazwa = ft.TextField(label="Nazwa (opcjonalnie)", value=(dokument or {}).get("nazwa") or "",
                                    **utils.styl_pola(page=page))
        self.e_numer = ft.TextField(label="Numer dokumentu (opcjonalnie)", value=(dokument or {}).get("numer") or "",
                                    **utils.styl_pola(page=page))
        self.e_od = self._pole_daty_z_czyszczeniem("Wystawiony / od (opcjonalnie)",
                                                   (dokument or {}).get("data_wystawienia") or "")
        self.e_do = self._pole_daty_z_czyszczeniem("Ważny do (opcjonalnie)", waznosc)
        self.t_karta = utils.podpis("")
        self.e_notatki = ft.TextField(label="Notatki", value=(dokument or {}).get("notatki") or "", multiline=True,
                                      min_lines=2, max_lines=4, **utils.styl_pola(page=page))
        self.pliki = utils.PolaZalacznikow(page, "dokumenty_pojazdu", self.dokument_id, dokument=True)
        self._nowy = dokument is None
        if self._nowy:
            self._podpowiedz_z_karty(rodzaj)
        self._opisz_rodzaj(rodzaj)

        self._stan_poczatkowy = self._migawka_formularza()
        appbar = utils.zbuduj_pasek_z_powrotem(
            page, "Edycja dokumentu" if self.dokument_id else "Nowy dokument", "/dokumenty",
            on_save=self.zapisz, czy_zmieniono=self._czy_zmieniono)
        k1 = utils.karta_formularza([self.e_rodzaj, self.e_nazwa, self.e_numer, self.e_od, self.e_do, self.t_karta],
                                    "Dokument", ft.Icons.FOLDER_SHARED, domyslnie_otwarte=True, page=page)
        k2 = utils.karta_formularza([self.pliki.kontrolka], "Skan albo zdjęcia stron", ft.Icons.ATTACH_FILE,
                                    domyslnie_otwarte=True, page=page)
        k3 = utils.karta_formularza([self.e_notatki], "Notatki", ft.Icons.STICKY_NOTE_2_OUTLINED,
                                    domyslnie_otwarte=bool(self.e_notatki.value))
        super().__init__(
            route=f"/dokumenty/edytuj/{self.dokument_id}" if self.dokument_id else "/dokumenty/nowy",
            padding=15, spacing=15, appbar=appbar, scroll=ft.ScrollMode.AUTO,
            controls=[k1, k2, k3, utils.przyciski_akcji(page, "Zapisz dokument", self.zapisz, "/dokumenty")],
        )

    def _pole_daty_z_czyszczeniem(self, etykieta, wartosc):
        pole = utils.pole_daty(self._page, etykieta, wartosc)

        def wyczysc(e):
            pole.value = ""
            try:
                pole.update()
            except Exception:
                log.polkniety("czyszczenie daty dokumentu")

        pole.suffix = ft.Row([ft.IconButton(icon=ft.Icons.CLOSE, icon_size=18, tooltip="Bez daty", on_click=wyczysc),
                              pole.suffix], spacing=0, tight=True)
        return pole

    def _podpowiedz_z_karty(self, rodzaj):
        """Nowa polisa OC zaczyna od towarzystwa i numeru z Karty pojazdu."""
        if rodzaj == "oc":
            if not self.e_nazwa.value:
                self.e_nazwa.value = self._dane_karty.get("ubezpieczyciel") or ""
            if not self.e_numer.value:
                self.e_numer.value = self._dane_karty.get("nr_polisy") or ""

    def _opisz_rodzaj(self, rodzaj):
        self.e_nazwa.hint_text = PODPOWIEDZI_NAZWY.get(rodzaj)
        if rodzaj in db.KOLUMNY_DATY_DOKUMENTOW:
            self.t_karta.value = (f"Ważność najnowszego dokumentu „{db.etykieta_dokumentu(rodzaj)}” to ta sama data, "
                                  "co na Karcie pojazdu — zmiana tutaj zmienia ją tam i w przypomnieniach.")
        else:
            self.t_karta.value = "Z datą ważności dzwonek przypomni o końcu, jak o polisie."

    def _zmiana_rodzaju(self):
        rodzaj = self.e_rodzaj.value
        if self._nowy:
            if not self.e_do.value:
                self.e_do.value = db.data_z_karty(self.state.auto_id, rodzaj) or ""
            self._podpowiedz_z_karty(rodzaj)
        self._opisz_rodzaj(rodzaj)
        try:
            self.update()
        except Exception:
            log.polkniety("odświeżenie formularza dokumentu")

    def _migawka_formularza(self):
        return (self.e_rodzaj.value, self.e_nazwa.value, self.e_numer.value, self.e_od.value, self.e_do.value,
                self.e_notatki.value, self.pliki.migawka())

    def _czy_zmieniono(self):
        return self._migawka_formularza() != self._stan_poczatkowy

    def zapisz(self, e):
        for pole in (self.e_od, self.e_do):
            utils.ustaw_blad(pole)
        od, do = self.e_od.value or "", self.e_do.value or ""
        if od and do and (na_iso(do) or "") < (na_iso(od) or ""):
            return utils.pokaz_bledy_formularza(self._page, [(self.e_do, "Koniec ważności przed wystawieniem")])

        pola = {"rodzaj": self.e_rodzaj.value, "nazwa": self.e_nazwa.value, "numer": self.e_numer.value,
                "data_wystawienia": od, "data_waznosci": do, "notatki": self.e_notatki.value}
        with self.pliki.zapis(), db.polacz_baze() as conn:
            dokument_id = db.zapisz_dokument(conn, self.state.auto_id, pola, self.dokument_id)
            self.pliki.zapisz_w(conn, dokument_id, self.state.auto_id)

        utils.wypchnij_w_tle(self._page, self.state.auto_id, "dokument pojazdu")
        utils.przejdz(self._page, "/dokumenty")
        utils.pokaz_komunikat(self._page, f"Zapisano: {db.etykieta_dokumentu(pola['rodzaj'])}.")


__all__ = [
    "FormularzDokumentuView",
]
