"""Formularz umowy leasingu albo kredytu (M-22).

Jedno miejsce na nową umowę, jej poprawkę i PRZESTAWIENIE raty wpisanej dotąd
jako zwykły wydatek cykliczny: ten sam wiersz `wydatki_cykliczne` dostaje
rodzaj umowy i jej dane, więc przypomnienie, zapłacone już raty w Innych
kosztach i synchronizacja zostają, jak były.

Rata liczy się na trzy sposoby (pole „Jak liczyć raty”):
  • rata z umowy — wpisana kwota; oprocentowanie wynika z niej i z kwoty
    finansowania (bez kwoty są same sumy rat);
  • rata z oprocentowania — rata równa liczona przez aplikację;
  • raty malejące (tylko kredyt) — stała część kapitałowa plus odsetki od salda.
Podgląd pod polami liczy harmonogram na bieżąco tym samym rachunkiem, co ekran
„Leasing i kredyt” (db.harmonogram_umowy).
"""

from datetime import datetime

import flet as ft
from date import parsuj_date

import db
import log
import utils


TRYB_Z_UMOWY = "z_umowy"
TRYB_Z_OPROCENTOWANIA = "z_oprocentowania"
TRYB_MALEJACE = "malejace"


def _tekst_pola(wartosc, decimale=2):
    """Liczba z bazy do pola formularza: „1900”, „1989,57”, „7,2” — bez zer
    na końcu, z przecinkiem, który parser pola i tak przeczyta."""
    if wartosc in (None, ""):
        return ""
    tekst = db.liczba_na_tekst(wartosc, decimale) or ""
    if "," in tekst:
        tekst = tekst.rstrip("0").rstrip(",")
    return tekst


class FormularzRatyView(ft.View):
    def __init__(self, page: ft.Page, state, wydatek_id=None):
        self._page = page
        self.state = state

        wpis = db.wczytaj_umowe(wydatek_id) if wydatek_id else None
        if wpis and wpis.get("auto_id") != state.auto_id:
            wpis = None  # wpis innego pojazdu z adresu — zakładamy nową umowę
        self.wydatek_id = wpis["id"] if wpis else None
        self.wpis = wpis or {}
        czy_umowa = bool(wpis) and db.czy_rata(wpis.get("typ"))
        # Zwykły wydatek cykliczny, z którego robi się rata z harmonogramem.
        self.przestawiany = bool(wpis) and not czy_umowa

        self.typ = wpis["typ"] if czy_umowa else db.TYP_CYKLICZNY_LEASING
        if czy_umowa and db.rodzaj_rat_umowy(wpis) == db.RATY_MALEJACE:
            self.tryb = TRYB_MALEJACE
        elif czy_umowa and wpis.get("oprocentowanie") is not None:
            self.tryb = TRYB_Z_OPROCENTOWANIA
        else:
            self.tryb = TRYB_Z_UMOWY

        waluta = utils.symbol_waluty()
        w = self.wpis
        styl = utils.styl_pola(page=page)
        liczbowe = dict(keyboard_type=ft.KeyboardType.NUMBER, on_change=lambda e: self._przelicz())

        self.e_nazwa = ft.TextField(label="Nazwa", hint_text="np. Leasing w banku, Kredyt na auto",
                                    value=str(w.get("nazwa") or ""), **styl)
        self.e_kwota_fin = ft.TextField(value=_tekst_pola(w.get("kwota_finansowania")), **liczbowe, **styl)
        self.e_oplata = ft.TextField(label=f"Opłata wstępna ({waluta})", value=_tekst_pola(w.get("oplata_wstepna")),
                                     **liczbowe, **styl)
        self.e_liczba = ft.TextField(label="Liczba rat", value=str(int(w["liczba_rat"])) if w.get("liczba_rat") else "",
                                     **liczbowe, **styl)
        # Przy przestawianiu wydatku jedyny znany termin to najbliższa rata —
        # lepszy punkt wyjścia niż puste pole (podpowiedź mówi, co poprawić).
        data_val = parsuj_date(w.get("data_pierwszej_raty") or (w.get("nastepna_data") if self.przestawiany else ""))
        data_val = data_val.strftime("%d.%m.%Y") if data_val != datetime.min.date() else ""
        self.e_data = utils.pole_daty(page, "Termin pierwszej raty", data_val, po_zmianie=self._przelicz)
        self.e_tryb = ft.Dropdown(
            label="Jak liczyć raty",
            value=self.tryb,
            options=self._opcje_trybu(),
            **utils.styl_dropdown()
        )
        # Dropdown w Flet 0.8x ma on_select, nie on_change (patrz utils/zgodnosc).
        self.e_tryb.on_select = self._zmien_tryb
        self.opis_trybu = utils.podpis("")
        self.e_rata = ft.TextField(label=f"Rata miesięczna ({waluta})",
                                   value=_tekst_pola(w.get("kwota")) if self.tryb == TRYB_Z_UMOWY else "",
                                   **liczbowe, **styl)
        self.e_procent = ft.TextField(label="Oprocentowanie roczne (%)", value=_tekst_pola(w.get("oprocentowanie"), 3),
                                      **liczbowe, **styl)
        self.e_wykup = ft.TextField(value=_tekst_pola(w.get("wykup")), **liczbowe, **styl)

        # Zapłacone raty: w nowej i przestawianej umowie podpowiada je kalendarz
        # (raty z terminem przed dzisiaj), dopóki nikt nie wpisze ich sam.
        zaplacone = int(float(w.get("zaplacone_platnosci") or 0)) if czy_umowa else 0
        liczba_rat = int(w.get("liczba_rat") or 0) if czy_umowa else 0
        self._zaplacone_reczne = czy_umowa
        self.e_zaplacone = ft.TextField(label="Zapłacone raty", value=str(min(zaplacone, liczba_rat)) if czy_umowa else "",
                                        keyboard_type=ft.KeyboardType.NUMBER, on_change=self._zmien_zaplacone, **styl)
        self.podpowiedz_zaplaconych = utils.podpis("")
        self.e_wykup_zaplacony = ft.Switch(label="Wykup też już zapłacony",
                                           value=bool(czy_umowa and liczba_rat and zaplacone > liczba_rat),
                                           on_change=lambda e: self._przelicz())

        self.podglad = ft.Column([], spacing=utils.SPACING["xs"])
        self.przelacznik_rodzaju = ft.Container(content=self._przelacznik_rodzaju())
        self._przelicz(odswiez=False)

        self._stan_poczatkowy = self._migawka_formularza()
        appbar = utils.zbuduj_pasek_z_powrotem(
            page, "Umowa raty" if self.wydatek_id else "Nowy leasing lub kredyt", "/raty",
            on_save=self.zapisz, czy_zmieniono=self._czy_zmieniono,
        )
        elementy = []
        if self.przestawiany:
            elementy.append(self._pasek_przestawiania())
        elementy += [
            utils.karta_formularza([self.przelacznik_rodzaju, self.e_nazwa], "Umowa", ft.Icons.DESCRIPTION,
                                   domyslnie_otwarte=True, page=page),
            utils.karta_formularza(
                [self.e_kwota_fin, self.e_oplata, self.e_liczba, self.e_data, self.e_tryb, self.opis_trybu,
                 self.e_rata, self.e_procent, self.e_wykup],
                "Raty", ft.Icons.CALENDAR_MONTH, domyslnie_otwarte=True, page=page,
            ),
            utils.karta_formularza([self.e_zaplacone, self.podpowiedz_zaplaconych, self.e_wykup_zaplacony],
                                   "Co już zapłacone", ft.Icons.TASK_ALT, domyslnie_otwarte=True, page=page),
            utils.karta_formularza([self.podglad], "Podgląd harmonogramu", ft.Icons.PREVIEW,
                                   domyslnie_otwarte=True, page=page),
            utils.przyciski_akcji(page, "Zapisz umowę", self.zapisz, "/raty"),
        ]
        super().__init__(
            route=f"/raty/edytuj/{self.wydatek_id}" if self.wydatek_id else "/raty/nowa",
            padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO,
        )

    # ================= PRZEŁĄCZNIKI =================

    def _przelacznik_rodzaju(self):
        opcje = [("Leasing", 0, utils.IKONY_UMOW_RAT[db.TYP_CYKLICZNY_LEASING]),
                 ("Kredyt", 1, utils.IKONY_UMOW_RAT[db.TYP_CYKLICZNY_KREDYT])]
        return utils.segmented_control(self._page, opcje, 1 if self.typ == db.TYP_CYKLICZNY_KREDYT else 0,
                                       self._zmien_rodzaj)

    def _opcje_trybu(self):
        opcje = [
            ft.DropdownOption(key=TRYB_Z_UMOWY, text="Rata z umowy"),
            ft.DropdownOption(key=TRYB_Z_OPROCENTOWANIA, text="Rata z oprocentowania"),
        ]
        # Leasing ma zawsze raty równe — malejące to wariant kredytu.
        if self.typ == db.TYP_CYKLICZNY_KREDYT:
            opcje.append(ft.DropdownOption(key=TRYB_MALEJACE, text="Raty malejące"))
        return opcje

    def _zmien_rodzaj(self, indeks):
        self.typ = db.TYP_CYKLICZNY_KREDYT if indeks == 1 else db.TYP_CYKLICZNY_LEASING
        if self.typ == db.TYP_CYKLICZNY_LEASING and self.tryb == TRYB_MALEJACE:
            self.tryb = TRYB_Z_UMOWY
        self.e_tryb.options = self._opcje_trybu()
        self.e_tryb.value = self.tryb
        self.przelacznik_rodzaju.content = self._przelacznik_rodzaju()
        self._przelicz()

    def _zmien_tryb(self, e=None):
        wybrany = self.e_tryb.value
        self.tryb = wybrany if wybrany in (TRYB_Z_UMOWY, TRYB_Z_OPROCENTOWANIA, TRYB_MALEJACE) else TRYB_Z_UMOWY
        self._przelicz()

    def _zmien_zaplacone(self, e=None):
        self._zaplacone_reczne = True
        self._przelicz()

    def _pasek_przestawiania(self):
        nazwa = str(self.wpis.get("nazwa") or "").strip()
        return ft.Container(
            padding=utils.SPACING["md"],
            **utils.powierzchnia(self._page, "blok"),
            content=ft.Row([
                ft.Icon(ft.Icons.INFO_OUTLINE, size=18, color=utils.KOLOR_STATUS["info"]),
                ft.Text(
                    f"Przestawiasz wydatek cykliczny „{nazwa}” na harmonogram rat. Nazwa i rata są już "
                    "w polach, a w terminie pierwszej raty stoi najbliższy termin — popraw go na datę "
                    "PIERWSZEJ raty z umowy. Zapłacone dotąd raty zostają w Innych kosztach.",
                    size=utils.FS["body"], expand=True,
                ),
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.START),
        )

    # ================= PODGLĄD =================

    def _zaplacone(self):
        """Liczba zapłaconych POZYCJI harmonogramu: raty z pola, a przy
        zapłaconym wykupie — o jedną więcej."""
        zaplacone = max(0, utils.parsuj_int(self.e_zaplacone.value, 0))
        liczba_rat = utils.parsuj_int(self.e_liczba.value, 0)
        if self.e_wykup_zaplacony.visible and self.e_wykup_zaplacony.value and liczba_rat and zaplacone >= liczba_rat:
            return liczba_rat + 1
        return zaplacone

    def _pola(self):
        """Pola formularza w kształcie wiersza umowy (db.harmonogram_umowy,
        db.zapisz_umowe_raty). Pola ukryte w danym trybie nie jadą wcale."""
        leasing = self.typ == db.TYP_CYKLICZNY_LEASING
        return {
            "typ": self.typ,
            "nazwa": (self.e_nazwa.value or "").strip(),
            "kwota": utils.parsuj_float(self.e_rata.value, None) if self.tryb == TRYB_Z_UMOWY else None,
            "liczba_rat": utils.parsuj_int(self.e_liczba.value, 0),
            "data_pierwszej_raty": self.e_data.value,
            "kwota_finansowania": utils.parsuj_float(self.e_kwota_fin.value, None),
            "oplata_wstepna": utils.parsuj_float(self.e_oplata.value, None) if leasing else None,
            "wykup": utils.parsuj_float(self.e_wykup.value, None),
            "oprocentowanie": utils.parsuj_float(self.e_procent.value, None) if self.tryb != TRYB_Z_UMOWY else None,
            "rodzaj_rat": db.RATY_MALEJACE if self.tryb == TRYB_MALEJACE else db.RATY_ROWNE,
            "zaplacone_platnosci": self._zaplacone(),
        }

    def _ustaw_pola(self):
        """Etykiety i widoczność pól według rodzaju umowy i trybu liczenia."""
        waluta = utils.symbol_waluty()
        leasing = self.typ == db.TYP_CYKLICZNY_LEASING
        self.e_kwota_fin.label = (f"Wartość auta w umowie ({waluta})" if leasing
                                  else f"Kwota kredytu ({waluta})")
        self.e_wykup.label = (f"Wykup ({waluta}, jeśli jest)" if leasing
                              else f"Rata balonowa ({waluta}, jeśli jest)")
        self.e_oplata.visible = leasing
        self.e_rata.visible = self.tryb == TRYB_Z_UMOWY
        self.e_procent.visible = self.tryb != TRYB_Z_UMOWY
        self.opis_trybu.value = {
            TRYB_Z_UMOWY: "Wpisz ratę z umowy. Oprocentowanie policzę z raty i kwoty finansowania — "
                          "bez kwoty pokażę same sumy rat.",
            TRYB_Z_OPROCENTOWANIA: "Ratę równą policzę z kwoty finansowania, oprocentowania i liczby rat.",
            TRYB_MALEJACE: "Stała część kapitałowa plus odsetki od salda — rata spada co miesiąc.",
        }[self.tryb]
        liczba_rat = utils.parsuj_int(self.e_liczba.value, 0)
        self.e_wykup_zaplacony.label = "Wykup też już zapłacony" if leasing else "Rata balonowa też już zapłacona"
        self.e_wykup_zaplacony.visible = bool(
            (utils.parsuj_float(self.e_wykup.value, None) or 0) > 0 and liczba_rat
            and utils.parsuj_int(self.e_zaplacone.value, 0) >= liczba_rat
        )

    def _przelicz(self, odswiez=True):
        """Podpowiedź zapłaconych rat i podgląd harmonogramu — po każdej zmianie."""
        dzis = datetime.now().date()
        liczba_rat = utils.parsuj_int(self.e_liczba.value, 0)
        sugestia = db.sugerowane_zaplacone(self.e_data.value, liczba_rat, dzis)
        if not self._zaplacone_reczne:
            self.e_zaplacone.value = str(sugestia) if liczba_rat and self.e_data.value else ""
        self.podpowiedz_zaplaconych.value = (
            f"Z kalendarza: {db.liczba_z_odmiana(sugestia, 'rata ma', 'raty mają', 'rat ma')} termin "
            "przed dzisiaj." if liczba_rat and self.e_data.value
            else "Podpowiem z kalendarza po wpisaniu liczby rat i terminu pierwszej."
        )
        self._ustaw_pola()
        self.podglad.controls = self._wiersze_podgladu(db.harmonogram_umowy(self._pola(), dzis))
        if odswiez:
            try:
                self._page.update()
            except Exception:
                log.polkniety("podgląd formularza umowy raty")

    def _wiersz(self, etykieta, wartosc, kolor=None):
        return ft.Row([
            utils.etykieta(etykieta, expand=True),
            utils.wartosc(wartosc, color=kolor) if kolor else utils.wartosc(wartosc),
        ], spacing=8)

    def _wiersze_podgladu(self, h):
        if not h["kompletna"]:
            return [utils.podpis(h["powod"])]
        waluta = utils.symbol_waluty()

        def kwota(w):
            return f"{utils.formatuj_liczba(w)} {waluta}"

        leasing = self.typ == db.TYP_CYKLICZNY_LEASING
        wiersze = []
        raty = [p for p in h["platnosci"] if p["rodzaj"] == db.PLATNOSC_RATA]
        if h["rodzaj_rat"] == db.RATY_MALEJACE:
            wiersze.append(self._wiersz("Rata", f"{kwota(raty[0]['kwota'])} → {kwota(raty[-1]['kwota'])}"))
        else:
            wiersze.append(self._wiersz("Rata wyliczona" if self.tryb == TRYB_Z_OPROCENTOWANIA else "Rata",
                                        kwota(raty[0]["kwota"])))
        ostatnia = h["data_ostatniej_raty"].strftime("%d.%m.%Y")
        wiersze.append(self._wiersz("Ostatnia rata", ostatnia))
        if h["wykup"]:
            wiersze.append(self._wiersz(db.slowo_wykupu(self.typ).capitalize(), f"{kwota(h['wykup'])} • {ostatnia}"))
        wiersze.append(self._wiersz("Wszystkie płatności", kwota(h["suma_platnosci"])))
        if h["odsetki_razem"] is not None:
            procent = f" (≈ {utils.formatuj_liczba(h['oprocentowanie'])}% rocznie)" if h["oprocentowanie"] else ""
            wiersze.append(self._wiersz("Koszt finansowania" if leasing else "Odsetki łącznie",
                                        f"{kwota(h['odsetki_razem'])}{procent}", utils.KOLOR_STATUS["cost"]))
        elif h["niespojna"]:
            wiersze.append(ft.Row([
                ft.Icon(ft.Icons.WARNING_AMBER, size=16, color=utils.KOLOR_STATUS["warning"]),
                ft.Text("Raty z wykupem nie pokrywają kwoty finansowania — sprawdź kwoty z umowy. "
                        "Odsetek bez tego nie policzę.", size=utils.FS["caption"],
                        color=utils.KOLOR_STATUS["warning"], expand=True),
            ], spacing=6))
        else:
            wiersze.append(utils.podpis("Podaj kwotę finansowania, a policzę odsetki i saldo po każdej racie."))
        if h["zakonczona"]:
            wiersze.append(self._wiersz("Stan", "spłacona", utils.KOLOR_STATUS["ok"]))
        else:
            wiersze.append(self._wiersz("Zostało do spłaty", kwota(h["do_splaty"])))
            nastepna = h["nastepna"]
            kolor = utils.KOLOR_STATUS["critical"] if nastepna["po_terminie"] else None
            wiersze.append(self._wiersz(
                "Następna płatność",
                f"{db.opis_platnosci(self.typ, nastepna, h['liczba_rat'])} • {nastepna['data'].strftime('%d.%m.%Y')}",
                kolor,
            ))
        return wiersze

    # ================= ZAPIS =================

    def _migawka_formularza(self):
        return (
            self.typ, self.tryb, self.e_nazwa.value, self.e_kwota_fin.value, self.e_oplata.value,
            self.e_liczba.value, self.e_data.value, self.e_rata.value, self.e_procent.value,
            self.e_wykup.value, self.e_zaplacone.value, self.e_wykup_zaplacony.value,
        )

    def _czy_zmieniono(self):
        return self._migawka_formularza() != self._stan_poczatkowy

    def _sprawdz(self):
        """Lista (pole, komunikat) — pusta, gdy umowa daje się policzyć."""
        bledy = []
        liczba_rat = utils.parsuj_int(self.e_liczba.value, 0)
        if not 1 <= liczba_rat <= db.MAKS_LICZBA_RAT:
            bledy.append((self.e_liczba, f"Podaj liczbę rat (od 1 do {db.MAKS_LICZBA_RAT})"))
        if not self.e_data.value:
            bledy.append((self.e_data, "Wybierz termin pierwszej raty"))

        def kwota(pole, wymagana=False, komunikat="Podaj kwotę"):
            tekst = (pole.value or "").strip()
            if not tekst:
                if wymagana:
                    bledy.append((pole, komunikat))
                return None
            wartosc = utils.parsuj_float(tekst, None)
            if wartosc is None or wartosc < 0:
                bledy.append((pole, "Wpisz liczbę, np. 1250,50"))
                return None
            return wartosc

        z_procentu = self.tryb != TRYB_Z_UMOWY
        finansowanie = kwota(self.e_kwota_fin, wymagana=z_procentu,
                             komunikat="Bez tej kwoty nie policzę rat z oprocentowania")
        if self.tryb == TRYB_Z_UMOWY:
            rata = kwota(self.e_rata, wymagana=True, komunikat="Podaj ratę z umowy")
            if rata == 0:
                bledy.append((self.e_rata, "Rata musi być większa od zera"))
        else:
            procent = kwota(self.e_procent, wymagana=True, komunikat="Podaj oprocentowanie roczne")
            if procent is not None and procent > 100:
                bledy.append((self.e_procent, "Oprocentowanie roczne w procentach — od 0 do 100"))
        oplata = kwota(self.e_oplata) if self.typ == db.TYP_CYKLICZNY_LEASING else None
        wykup = kwota(self.e_wykup)
        if finansowanie:
            kapital = finansowanie - (oplata or 0)
            if oplata and kapital <= 0:
                bledy.append((self.e_oplata, "Opłata wstępna nie może pokryć całej wartości auta"))
            elif wykup and wykup >= kapital:
                bledy.append((self.e_wykup, "Wykup nie może pokryć całej kwoty finansowania"))
        elif z_procentu and finansowanie == 0:
            bledy.append((self.e_kwota_fin, "Kwota musi być większa od zera"))

        zaplacone = (self.e_zaplacone.value or "").strip()
        if zaplacone:
            liczba = utils.parsuj_float(zaplacone, None)
            if liczba is None or liczba < 0 or liczba != int(liczba) or (liczba_rat and liczba > liczba_rat):
                bledy.append((self.e_zaplacone, f"Od 0 do {liczba_rat or 'liczby rat'}"))
        return bledy

    def zapisz(self, e):
        for pole in (self.e_nazwa, self.e_kwota_fin, self.e_oplata, self.e_liczba, self.e_data,
                     self.e_rata, self.e_procent, self.e_wykup, self.e_zaplacone):
            utils.ustaw_blad(pole)
        bledy = self._sprawdz()
        if bledy:
            return utils.pokaz_bledy_formularza(self._page, bledy)

        pola = self._pola()
        harmonogram = db.harmonogram_umowy(pola)
        if not harmonogram["kompletna"]:
            return utils.pokaz_komunikat(self._page, harmonogram["powod"], utils.KOLOR_STATUS["error"])
        if not db.zapisz_umowe_raty(self.state.auto_id, pola, self.wydatek_id):
            return utils.pokaz_komunikat(self._page, "Nie zapisano — tej umowy już nie ma.", utils.KOLOR_STATUS["error"])

        utils.wypchnij_w_tle(self._page, self.state.auto_id, "umowa raty")
        utils.przejdz(self._page, "/raty")
        if harmonogram["zakonczona"]:
            utils.pokaz_komunikat(self._page, "Zapisano umowę — jest już spłacona.")
        else:
            utils.pokaz_komunikat(
                self._page,
                f"Zapisano umowę • do spłaty {utils.formatuj_liczba(harmonogram['do_splaty'])} "
                f"{utils.symbol_waluty()}",
            )


__all__ = [
    "FormularzRatyView",
    "TRYB_MALEJACE",
    "TRYB_Z_OPROCENTOWANIA",
    "TRYB_Z_UMOWY",
]
