import flet as ft

import db
import log
import utils


class ZdrowieDanychView(ft.View):
    """„Zdrowie danych” (N-08): nieścisłości pojazdu w jednym miejscu — każda z poprawką albo
    wpisem do otwarcia i „To nie błąd” (na tym telefonie). Liczy db.zdrowie_danych, zdania
    i klocki — utils/zdrowie_danych.py. Otwarcie ekranu to przegląd: dzwonek milknie na kwartał."""

    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state
        self.j = utils.jednostka_dystansu()  # km albo mi — raz na ekran

        appbar = utils.zbuduj_pasek_z_powrotem(page, "Zdrowie danych", "/", ikona=ft.Icons.HEALTH_AND_SAFETY)

        if not self.state.auto_id:
            super().__init__(
                route="/zdrowie-danych", padding=15, spacing=15, appbar=appbar,
                controls=[utils.ekran_braku_danych(
                    ikona=ft.Icons.DIRECTIONS_CAR,
                    tytul="Brak wybranego pojazdu",
                    opis="Dodaj pojazd, aby sprawdzić, czy jego dane się zgadzają.",
                    tekst_przycisku="Dodaj pojazd",
                    on_click=lambda e: utils.przejdz(self._page, "/auto/nowy"),
                )],
            )
            return

        self.podglad = db.czy_tylko_podglad(self.state.auto_id)
        self.stan = None
        self.rozwiniete = set()
        self.lista = ft.Column(spacing=10)

        def tresc():
            db.zanotuj_przeglad_danych(self.state.auto_id)
            self._przelicz()
            return self.lista

        super().__init__(
            route="/zdrowie-danych", padding=15, appbar=appbar,
            controls=[utils.zbuduj_etapami(
                page, utils.szkielet_ekranu(page, karty=5, linie=2), tresc, widok=self,
            )],
            scroll=ft.ScrollMode.AUTO,
        )

    # ================= LICZENIE =================

    def _przelicz(self):
        self.stan = db.zdrowie_danych(self.state.auto_id)
        self.lista.controls = self._elementy()

    def _odswiez(self, opis):
        self._przelicz()
        try:
            self.update()
        except Exception:
            log.polkniety(opis)

    def odswiez_w_miejscu(self):
        """Po scaleniu nazw, arkuszu rodzaju napraw albo „Cofnij” (utils.odswiez_ekran): lista
        liczy się od nowa, ekran zostaje w miejscu."""
        if self.stan is None:
            return
        self._odswiez("odświeżenie Zdrowia danych w miejscu")

    # ================= LISTA =================

    def _elementy(self):
        stan = self.stan
        elementy = [utils.karta_podsumowania_zdrowia(self._page, stan)]
        if self.podglad:
            elementy.append(utils.podpis("Masz tylko podgląd tego pojazdu — poprawki zrobi właściciel. "
                                         "„To nie błąd” działa na tym telefonie."))
        for rodzaj in db.SPRAWDZENIA_ZDROWIA:
            pozycje = [p for p in stan["pozycje"] if p["rodzaj"] == rodzaj]
            if not pozycje:
                continue
            elementy.append(utils.naglowek_sekcji_zdrowia(
                self._page, rodzaj, len(pozycje), self.j, akcje=self._akcje_sekcji(rodzaj, pozycje)))
            widoczne = pozycje if rodzaj in self.rozwiniete else pozycje[:utils.POZYCJI_W_SEKCJI_ZDROWIA]
            elementy.extend(self._karta(p) for p in widoczne)
            if len(widoczne) < len(pozycje):
                elementy.append(ft.Row([ft.TextButton(
                    f"Pokaż wszystkie ({utils.formatuj_liczba(len(pozycje), 0)})",
                    on_click=lambda e, r=rodzaj: self._rozwin(r),
                )], alignment=ft.MainAxisAlignment.CENTER))

        czyste = [r for r in stan["sprawdzone"] if not stan["liczby"].get(r)]
        if czyste:
            elementy.append(utils.karta_czystych_sprawdzen(self._page, czyste))
        if stan["pominiete"]:
            elementy.append(self._ukryte(stan["pominiete"]))
        elementy.append(utils.nota_o_liczeniu(self._page, "Jak sprawdzamy", utils.nota_zdrowia_danych(self.j)))
        elementy.append(utils.dol_bezpieczny(10))
        return elementy

    def _akcje_sekcji(self, rodzaj, pozycje):
        if rodzaj != "pliki" or self.podglad:
            return None
        akcje = [ft.TextButton("Odszukaj pliki", on_click=self._odszukaj_pliki)]
        usuwalne = [p for p in pozycje if p.get("usuwalny")]
        if len(usuwalne) > 1:
            akcje.append(ft.TextButton(
                f"Usuń wszystkie ({utils.formatuj_liczba(len(usuwalne), 0)})",
                style=ft.ButtonStyle(color=utils.KOLOR_STATUS["destructive"]),
                on_click=lambda e: self._usun_martwe(usuwalne),
            ))
        return akcje

    def _karta(self, p):
        dzien = utils.dzien_zdrowia(p.get("data_iso"), p.get("data")) if (p.get("data_iso") or p.get("data")) else ""
        tresc = [
            ft.Row([
                ft.Text(utils.tytul_pozycji_zdrowia(p), size=utils.FS["body"], weight="w500", expand=True,
                        max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                utils.podpis(dzien) if dzien else ft.Container(),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START),
            ft.Text(utils.opis_pozycji_zdrowia(p, self.j), size=utils.FS["label"],
                    color=ft.Colors.ON_SURFACE_VARIANT),
        ]
        if p["rodzaj"] == "do_pelna":
            tresc.append(self._wpisy_ciagu(p))
        tresc.append(ft.Row(self._przyciski(p), wrap=True, spacing=4, run_spacing=0,
                            alignment=ft.MainAxisAlignment.END))

        karta, kontener = utils.karta_listy(
            ft.Column(tresc, spacing=utils.SPACING["xs"]),
            kolor_paska=utils.KOLORY_WAGI_ZDROWIA.get(p["waga"]), page=self._page,
        )
        dotkniecie = self._dotkniecie(p)
        if dotkniecie:
            kontener.on_click = utils.z_efektem_nacisniecia(kontener, dotkniecie)
        else:
            kontener.ink = False
        return karta

    def _wpisy_ciagu(self, p):
        """Daty wpisów ciągu „do pełna” — każda otwiera swój wpis (przed pierwszym pełnym bakiem
        najstarsze, w otwartym ciągu najnowsze)."""
        wpisy = p["wpisy"]
        ile = utils.WPISOW_CIAGU_NA_KARCIE
        widoczne = wpisy[:ile] if p["polozenie"] == "przed_pierwszym" else wpisy[-ile:]
        chipy = [utils.chip_wpisu_zdrowia(
            utils.dzien_zdrowia(w["data_iso"], w["data"]),
            None if self.podglad else (lambda e, t=w["trasa"]: utils.przejdz(self._page, t)),
        ) for w in widoczne]
        if len(wpisy) > len(widoczne):
            chipy.append(utils.podpis(f"i jeszcze {utils.formatuj_liczba(len(wpisy) - len(widoczne), 0)}"))
        return utils.pasek_zawijany(chipy)

    def _trasa(self, p):
        """Formularze to zmiana danych — podgląd dostaje tylko Historię przebiegu."""
        trasa = p.get("trasa")
        if self.podglad and trasa != "/przebieg":
            return None
        return trasa

    def _dotkniecie(self, p):
        """Co robi dotknięcie karty: narzędzie albo wpis. Usuwanie nigdy — tylko przyciskiem."""
        rodzaj = p["rodzaj"]
        if rodzaj == "nazwy":
            return None if self.podglad else (lambda e: self._scal(p))
        if rodzaj == "rodzaj":
            return None if self.podglad else self._oznacz_rodzaj
        trasa = self._trasa(p)
        return (lambda e: utils.przejdz(self._page, trasa)) if trasa else None

    def _przyciski(self, p):
        rodzaj = p["rodzaj"]
        przyciski = [ft.TextButton("To nie błąd", on_click=lambda e: self._pomin(p))]
        if rodzaj == "pliki" and p.get("usuwalny") and not self.podglad:
            przyciski.append(ft.TextButton("Usuń", style=ft.ButtonStyle(color=utils.KOLOR_STATUS["destructive"]),
                                           on_click=lambda e: self._usun_martwe([p])))
        dotkniecie = self._dotkniecie(p)
        if dotkniecie:
            if rodzaj == "nazwy":
                napis = "Scal"
            elif rodzaj == "rodzaj":
                napis = "Oznacz"
            elif rodzaj in ("terminy", "pojazd"):
                napis = "Uzupełnij"
            elif p.get("trasa") == "/przebieg":
                napis = "Pokaż w historii"
            else:
                napis = "Otwórz wpis"
            przyciski.append(ft.TextButton(napis, on_click=dotkniecie))
        return przyciski

    def _ukryte(self, pozycje):
        wiersze = [ft.Row([
            ft.Column([
                ft.Text(utils.tytul_pozycji_zdrowia(p), size=utils.FS["body"], max_lines=2,
                        overflow=ft.TextOverflow.ELLIPSIS),
                utils.podpis(db.SPRAWDZENIA_ZDROWIA[p["rodzaj"]]),
            ], spacing=0, tight=True, expand=True),
            ft.TextButton("Przywróć", on_click=lambda e, p=p: self._przywroc(p)),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER) for p in pozycje]
        return utils.karta_formularza(
            [utils.podpis("Te pozycje nie liczą się na tym telefonie. Przywrócona wraca do listy.")] + wiersze,
            f"To nie błąd ({utils.formatuj_liczba(len(pozycje), 0)})", ft.Icons.VISIBILITY_OFF, page=self._page,
        )

    # ================= AKCJE =================

    def _rozwin(self, rodzaj):
        self.rozwiniete.add(rodzaj)
        self._odswiez("rozwinięcie sekcji Zdrowia danych")

    def _pomin(self, p):
        db.pomin_w_zdrowiu_danych(self.state.auto_id, [p["klucz"]])
        self._odswiez("odświeżenie Zdrowia danych po „To nie błąd”")

    def _przywroc(self, p):
        db.przywroc_w_zdrowiu_danych(self.state.auto_id, [p["klucz"]])
        self._odswiez("odświeżenie Zdrowia danych po przywróceniu pozycji")

    def _scal(self, p):
        utils.potwierdz_scalenie_duplikatow(self._page, self.state.auto_id, p["grupa"],
                                            po_scaleniu=self.odswiez_w_miejscu)

    def _oznacz_rodzaj(self, e=None):
        utils.pokaz_oznaczanie_napraw(self._page, self.state.auto_id, po_zamknieciu=self.odswiez_w_miejscu)

    def _odszukaj_pliki(self, e=None):
        naprawione, _brakujace = db.napraw_sciezki_zalacznikow()
        if naprawione:
            utils.pokaz_komunikat(
                self._page, f"Odnaleziono {db.liczba_z_odmiana(naprawione, 'plik', 'pliki', 'plików')} "
                            "— ścieżki poprawione.", utils.KOLOR_STATUS["ok"])
        else:
            utils.pokaz_komunikat(self._page, "Żadnego z brakujących plików nie ma na tym telefonie.",
                                  utils.KOLOR_STATUS["warning"])
        self._odswiez("odświeżenie Zdrowia danych po szukaniu plików")

    def _usun_martwe(self, pozycje):
        """Martwe pliki do kosza wpisów, z „Cofnij”; kilka naraz — po pytaniu."""
        usuwalne = [p for p in pozycje if p.get("usuwalny")]
        if not usuwalne:
            return

        def wykonaj():
            wynik = db.usun_martwe_pliki(usuwalne)
            liczba = wynik["liczba"] if wynik else 0
            utils.pokaz_komunikat_cofnij(
                self._page, f"Usunięto z wpisów {db.liczba_z_odmiana(liczba, 'martwy plik', 'martwe pliki', 'martwych plików')}.",
                wynik)
            self._odswiez("odświeżenie Zdrowia danych po usunięciu martwych plików")

        if len(usuwalne) == 1:
            wykonaj()
            return
        utils.potwierdz(
            self._page, "Usunąć martwe pliki?",
            f"{db.liczba_z_odmiana(len(usuwalne), 'martwy plik trafi', 'martwe pliki trafią', 'martwych plików trafi')} "
            "do kosza — znikną z wpisów, a same wpisy zostają. Z kosza da się je przywrócić.",
            wykonaj, tekst_potwierdzenia="Usuń",
        )
