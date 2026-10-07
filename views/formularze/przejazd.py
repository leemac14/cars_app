"""Formularz przejazdu w ewidencji (N-01): nowy, poprawka, „Powtórz dziś” i powrót
(skąd/dokąd zamienione). Wypełnienie ręcznie albo z zapisanej trasy (jak w
kalkulatorze), podpowiedzi z historii. Km w jedną stronę z przełącznikiem „tam i z
powrotem” — do bazy idzie CAŁY przejazd. Opcjonalny licznik po przejeździe liczy km sam
i jest źródłem historii licznika."""

from datetime import date, datetime

import flet as ft
from date import parsuj_date

import db
import log
import utils


SLUZBOWY, PRYWATNY = 0, 1


class FormularzPrzejazduView(ft.View):
    def __init__(self, page: ft.Page, state, przejazd_id=None, zrodlo=None, powrot_do=None):
        """`zrodlo` mówi, czym wypełnić nowy przejazd: {"powtorz": id},
        {"powrot": id}, {"szablon": id}, {"kalkulator": (km w jedną stronę,
        powrót, id trasy albo None)} albo {"dzien": "DD.MM.RRRR"}."""
        self._page = page
        self.state = state
        self.j = utils.jednostka_dystansu()
        zrodlo = zrodlo or {}

        wpis = db.pobierz_przejazd(przejazd_id) if przejazd_id else None
        if wpis and wpis["auto_id"] != state.auto_id:
            wpis = None  # przejazd innego pojazdu z adresu — zakładamy nowy
        self.przejazd_id = wpis["id"] if wpis else None
        self.szablony = db.pobierz_trasy_szablony(state.auto_id) if state.auto_id else []
        self.podpowiedzi = db.podpowiedzi_przejazdow(state.auto_id)

        dane = self._dane_poczatkowe(wpis, zrodlo)
        self._km_przy_otwarciu = dane["km_jednej_strony"] or None
        self._licznik_przy_otwarciu = dane.get("licznik")
        self._km_z_licznika = False  # czy kilometry wpisał licznik, a nie człowiek
        self.rodzaj = SLUZBOWY if dane["sluzbowy"] else PRYWATNY

        styl = utils.styl_pola(page=page)
        self.e_data = utils.pole_daty(page, "Data przejazdu", dane["data"], po_zmianie=self._po_zmianie_licznika)
        self.e_skad = ft.TextField(label="Skąd", value=dane["skad"], hint_text="np. Dom, Biuro, Warszawa",
                                   on_blur=lambda e: self._podpowiedz_kilometry(), **styl)
        self.e_dokad = ft.TextField(label="Dokąd", value=dane["dokad"], hint_text="np. Klient ABC, Łódź",
                                    on_blur=lambda e: self._podpowiedz_kilometry(), **styl)
        self.e_cel = ft.TextField(label="Cel wyjazdu", value=dane["cel"],
                                  hint_text="np. Spotkanie z klientem, serwis u klienta", **styl)
        self.e_km = ft.TextField(label=f"Dystans w jedną stronę ({self.j})",
                                 value=db.wartosc_pola_dystansu(dane["km_jednej_strony"], self.j, 1)
                                 if dane["km_jednej_strony"] else "",
                                 keyboard_type=ft.KeyboardType.NUMBER, on_change=self._zmiana_km, **styl)
        self.c_powrot = ft.Checkbox(label="Tam i z powrotem (×2)", value=bool(dane["powrot"]),
                                    on_change=lambda e: self._odswiez_razem())
        self.t_razem = utils.podpis("")
        self.ostatnio = ft.Container(visible=False)
        self.e_licznik = ft.TextField(label=f"Stan licznika po przejeździe ({self.j}, opcjonalnie)",
                                      value=db.wartosc_pola_dystansu(dane["licznik"], self.j)
                                      if dane.get("licznik") else "",
                                      keyboard_type=ft.KeyboardType.NUMBER,
                                      on_blur=lambda e: self._po_zmianie_licznika(), **styl)
        self.t_licznik = utils.podpis("")
        self.e_kierowca = ft.TextField(label="Kierowca (imię i nazwisko)", value=dane["kierowca"], **styl)
        self.notatka_bazowa = (dane.get("notatka") or "").strip()
        self.k_notatka = utils.pole_notatki(self.notatka_bazowa, page)
        self.przelacznik_rodzaju = ft.Container(content=self._segmenty_rodzaju(), width=320)

        self._odswiez_razem(aktualizuj=False)
        self._po_zmianie_licznika(aktualizuj=False)
        self._podpowiedz_kilometry(aktualizuj=False)

        self._stan_poczatkowy = self._migawka_formularza()
        self.powrot_do = powrot_do or self._trasa_miesiaca(dane["data"])
        tytul = {"powtorz": "Powtórz przejazd", "powrot": "Trasa powrotna"}.get(
            next((k for k in ("powtorz", "powrot") if k in zrodlo), ""), "Nowy przejazd")
        appbar = utils.zbuduj_pasek_z_powrotem(
            page, "Przejazd" if self.przejazd_id else tytul, self.powrot_do,
            on_save=self.zapisz, czy_zmieniono=self._czy_zmieniono, ikona=ft.Icons.ALT_ROUTE,
        )

        elementy = [
            self._karta_tras(),
            utils.karta_formularza(
                [self.e_data, self.e_skad, self._chipy(self.podpowiedzi["miejsca"], self.e_skad),
                 ft.Row([ft.TextButton("Zamień skąd i dokąd", icon=ft.Icons.SWAP_VERT,
                                       on_click=lambda e: self._zamien())], alignment=ft.MainAxisAlignment.END),
                 self.e_dokad, self._chipy(self.podpowiedzi["miejsca"], self.e_dokad),
                 self.e_cel, self._chipy(self.podpowiedzi["cele"], self.e_cel)],
                "Trasa i cel", ft.Icons.ROUTE, domyslnie_otwarte=True, page=page,
            ),
            utils.karta_formularza(
                [self.przelacznik_rodzaju, self.e_km, self.c_powrot, self.ostatnio, self.t_razem,
                 self.e_licznik, self.t_licznik],
                "Kilometry", ft.Icons.SPEED, domyslnie_otwarte=True, page=page,
            ),
            utils.karta_formularza(
                [self.e_kierowca, self._chipy(self.podpowiedzi["kierowcy"], self.e_kierowca)],
                "Kierowca", ft.Icons.PERSON, domyslnie_otwarte=True, page=page,
            ),
            utils.karta_formularza([self.k_notatka], "Notatka", ft.Icons.STICKY_NOTE_2_OUTLINED,
                                   domyslnie_otwarte=bool(self.notatka_bazowa), page=page),
            utils.przyciski_akcji(page, "Zapisz przejazd", self.zapisz, self.powrot_do),
        ]
        super().__init__(
            route=f"/ewidencja/edytuj/{self.przejazd_id}" if self.przejazd_id else "/ewidencja/nowy",
            padding=15, spacing=15, appbar=appbar, controls=elementy, scroll=ft.ScrollMode.AUTO,
        )

    # ================= DANE POCZĄTKOWE =================

    def _dane_poczatkowe(self, wpis, zrodlo):
        dzis = datetime.now().strftime("%d.%m.%Y")
        if wpis:
            return dict(wpis)
        tryb = db.pobierz_ustawienia_ewidencji(self.state.auto_id)["tryb"] if self.state.auto_id else "podzial"
        ostatnie = db.pobierz_przejazdy(self.state.auto_id)[-1:] if self.state.auto_id else []
        # Przy podziale kosztów rodzaj podpowiada ostatni przejazd; przy
        # kilometrówce i VAT liczą się jazdy służbowe, więc to one są domyślne.
        sluzbowy = ostatnie[0]["sluzbowy"] if (ostatnie and tryb == "podzial") else True
        dane = {"data": dzis, "skad": "", "dokad": "", "cel": "", "km_jednej_strony": 0.0, "powrot": False,
                "sluzbowy": sluzbowy, "kierowca": self._domyslny_kierowca(), "licznik": None, "notatka": ""}

        zrodlowy_id = zrodlo.get("powtorz") or zrodlo.get("powrot")
        zrodlowy = db.pobierz_przejazd(zrodlowy_id) if zrodlowy_id else None
        if zrodlowy and zrodlowy["auto_id"] == self.state.auto_id:
            dane.update({k: zrodlowy[k] for k in ("skad", "dokad", "cel", "km_jednej_strony", "powrot",
                                                   "sluzbowy", "kierowca")})
            if "powrot" in zrodlo:
                # Droga z powrotem: ta sama trasa odwrotnie, tego samego dnia.
                dane.update({"skad": zrodlowy["dokad"], "dokad": zrodlowy["skad"], "powrot": False,
                             "data": zrodlowy["data"]})

        szablon_id = zrodlo.get("szablon")
        kalkulator = zrodlo.get("kalkulator")
        if kalkulator:
            szablon_id = kalkulator[2] or szablon_id
        szablon = next((t for t in self.szablony if t["id"] == szablon_id), None) if szablon_id else None
        if szablon:
            dane.update(self._z_szablonu(szablon))
        if kalkulator:
            dane.update({"km_jednej_strony": float(kalkulator[0] or 0), "powrot": bool(kalkulator[1])})
        if zrodlo.get("dzien") and parsuj_date(zrodlo["dzien"]) != datetime.min.date():
            dane["data"] = zrodlo["dzien"]
        return dane

    def _domyslny_kierowca(self):
        osoba = db.pobierz_dane_osoby_ewidencji()["osoba"]
        moje = db.pobierz_moje_imie()
        return osoba or (moje if moje and moje != "Kierowca" else "")

    @staticmethod
    def _z_szablonu(t):
        dane = {"km_jednej_strony": t["dystans"], "powrot": t["powrot"]}
        for pole in ("skad", "dokad", "cel"):
            if t[pole]:
                dane[pole] = t[pole]
        if t["sluzbowy"] is not None:
            dane["sluzbowy"] = t["sluzbowy"]
        return dane

    @staticmethod
    def _trasa_miesiaca(data_str):
        d = parsuj_date(data_str)
        if d == datetime.min.date():
            return "/ewidencja"
        return f"/ewidencja/{d.year}/{d.month}"

    # ================= SKŁADNIKI =================

    def _segmenty_rodzaju(self):
        return utils.segmented_control(
            self._page,
            [("Służbowy", SLUZBOWY, ft.Icons.WORK_OUTLINE), ("Prywatny", PRYWATNY, ft.Icons.HOME_OUTLINED)],
            self.rodzaj, self._zmien_rodzaj,
        )

    def _zmien_rodzaj(self, indeks):
        self.rodzaj = indeks
        self.przelacznik_rodzaju.content = self._segmenty_rodzaju()
        self._aktualizuj(self.przelacznik_rodzaju)

    def _chipy(self, wartosci, pole):
        """Podpowiedzi z historii pod polem — dotknięcie wpisuje wartość."""
        if not wartosci:
            return ft.Container(visible=False)

        def chip(tekst):
            return ft.Container(
                content=ft.Text(tekst, size=utils.FS["label"], no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                padding=ft.Padding(10, 4, 10, 4), border_radius=utils.RADIUS["pill"],
                border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT), ink=True,
                on_click=lambda e, t=tekst: self._wpisz(pole, t),
            )
        return utils.pasek_zawijany([chip(w) for w in wartosci])

    def _wpisz(self, pole, tekst):
        pole.value = tekst
        utils.ustaw_blad(pole)
        if pole in (self.e_skad, self.e_dokad):
            self._podpowiedz_kilometry(aktualizuj=False)
        self._aktualizuj()

    def _karta_tras(self):
        """Zapisane trasy — te same, co w kalkulatorze podróży."""
        if self.szablony:
            chipy = [self._chip_trasy(t) for t in self.szablony]
            tresc = utils.pasek_zawijany(chipy)
        else:
            tresc = utils.podpis("Wypełnij przejazd i dotknij „Zapisz jako trasę” — następnym razem wystarczy "
                                 "jedno dotknięcie.")
        return ft.Container(
            padding=utils.SPACING["md"], **utils.powierzchnia(self._page, "karta"),
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.BOOKMARKS, size=16, color=ft.Colors.PRIMARY),
                    ft.Text("Zapisane trasy", weight="bold", size=utils.FS["body"], color=ft.Colors.PRIMARY,
                            expand=True),
                    ft.TextButton("Zapisz jako trasę", icon=ft.Icons.BOOKMARK_ADD,
                                  on_click=lambda e: self._okno_zapisu_trasy()),
                ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                tresc,
            ], spacing=8),
        )

    def _chip_trasy(self, t):
        opis = utils.formatuj_dystans(t["dystans"], 0, self.j) + (" ×2" if t["powrot"] else "")
        return ft.Container(
            padding=ft.Padding(12, 7, 12, 7), border_radius=utils.RADIUS["pill"],
            bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.PRIMARY), ink=True,
            tooltip="Dotknij, aby wypełnić przejazd tą trasą",
            on_click=lambda e, tr=t: self._zastosuj_szablon(tr),
            content=ft.Row([
                ft.Icon(ft.Icons.ROUTE, size=15, color=ft.Colors.PRIMARY),
                ft.Text(t["nazwa"], size=utils.FS["body"], weight="bold", color=ft.Colors.PRIMARY, no_wrap=True),
                ft.Text(opis, size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT, no_wrap=True),
            ], spacing=6, tight=True),
        )

    def _zastosuj_szablon(self, t):
        dane = self._z_szablonu(t)
        for pole, kontrolka in (("skad", self.e_skad), ("dokad", self.e_dokad), ("cel", self.e_cel)):
            if pole in dane:
                kontrolka.value = dane[pole]
        self.e_km.value = db.wartosc_pola_dystansu(dane["km_jednej_strony"], self.j, 1) if dane["km_jednej_strony"] else ""
        self._km_przy_otwarciu = dane["km_jednej_strony"] or None
        self._km_z_licznika = False
        self.c_powrot.value = bool(dane["powrot"])
        if "sluzbowy" in dane:
            self.rodzaj = SLUZBOWY if dane["sluzbowy"] else PRYWATNY
            self.przelacznik_rodzaju.content = self._segmenty_rodzaju()
        self._odswiez_razem(aktualizuj=False)
        self._podpowiedz_kilometry(aktualizuj=False)
        self._aktualizuj()
        utils.pokaz_komunikat(self._page, f"Wypełniono trasą „{t['nazwa']}”.")

    # ================= KILOMETRY I LICZNIK =================

    def _km_jednej_strony(self):
        """Kilometry w jedną stronę z pola (w km) albo None."""
        wartosc = utils.parsuj_float(self.e_km.value, None)
        if wartosc is None or wartosc <= 0:
            return None
        return db.dystans_na_km(wartosc, self.j, km_przy_otwarciu=self._km_przy_otwarciu)

    def _km_razem(self):
        km = self._km_jednej_strony()
        return db.km_przejazdu(km, self.c_powrot.value) if km else None

    def _zmiana_km(self, e=None):
        self._km_z_licznika = False
        self._odswiez_razem()

    def _odswiez_razem(self, aktualizuj=True):
        km = self._km_razem()
        if km and self.c_powrot.value:
            self.t_razem.value = f"Razem {db.tekst_km_przejazdu(km, self.j)} (tam i z powrotem)"
        elif km:
            self.t_razem.value = f"Razem {db.tekst_km_przejazdu(km, self.j)}"
        else:
            self.t_razem.value = ""
        self.t_razem.visible = bool(km)
        if aktualizuj:
            self._aktualizuj(self.t_razem)

    def _podpowiedz_kilometry(self, aktualizuj=True):
        """Chip „Ostatnio ta trasa: 84 km” — kilometry ostatniego przejazdu
        tą samą trasą (w którąkolwiek stronę). Dotknięcie wpisuje je w pole."""
        ostatni = db.ostatni_przejazd_trasy(self.state.auto_id, self.e_skad.value, self.e_dokad.value,
                                            wyklucz_id=self.przejazd_id)
        if not ostatni:
            self.ostatnio.visible = False
        else:
            km = ostatni["km_jednej_strony"]
            self.ostatnio.content = ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.HISTORY, size=15, color=ft.Colors.PRIMARY),
                    ft.Text(f"Ostatnio ta trasa: {db.tekst_km_przejazdu(km, self.j)} ({ostatni['data']})",
                            size=utils.FS["label"], color=ft.Colors.PRIMARY),
                ], spacing=6, tight=True),
                padding=ft.Padding(10, 5, 10, 5), border_radius=utils.RADIUS["pill"],
                border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT), ink=True,
                on_click=lambda e, k=km: self._wpisz_km(k),
            )
            self.ostatnio.visible = True
        if aktualizuj:
            self._aktualizuj(self.ostatnio)

    def _wpisz_km(self, km):
        self.e_km.value = db.wartosc_pola_dystansu(km, self.j, 1)
        self._km_przy_otwarciu = km
        self._km_z_licznika = False
        utils.ustaw_blad(self.e_km)
        self._odswiez_razem(aktualizuj=False)
        self._aktualizuj()

    def _licznik_km(self):
        wartosc = utils.parsuj_float(self.e_licznik.value, None)
        if wartosc is None or wartosc <= 0:
            return None
        return db.dystans_na_km(wartosc, self.j, calkowity=True, km_przy_otwarciu=self._licznik_przy_otwarciu)

    def _po_zmianie_licznika(self, aktualizuj=True):
        """Podpis pod licznikiem: poprzedni znany stan, a przy wpisanym stanie
        po przejeździe — kilometry z różnicy. Puste pole kilometrów (albo
        wypełnione wcześniej z licznika) dostaje je samo."""
        licznik = self._licznik_km()
        poprzedni = db.poprzedni_stan_licznika(self.state.auto_id, self.e_data.value, licznik,
                                               wyklucz_id=self.przejazd_id)
        if not poprzedni:
            self.t_licznik.value = ("Wpisany stan po przejeździe trafi do historii licznika."
                                    if licznik is None else "Brak wcześniejszego stanu licznika — kilometry wpisz sam.")
        elif licznik is None:
            self.t_licznik.value = (f"Poprzedni stan: {db.tekst_dystansu(poprzedni['przebieg'], 0, self.j)} "
                                    f"({poprzedni['data']}, {poprzedni['etykieta'].lower()}). Po wpisaniu "
                                    "stanu po przejeździe kilometry policzą się same.")
        else:
            roznica = licznik - poprzedni["przebieg"]
            self.t_licznik.value = (f"Od poprzedniego stanu ({db.tekst_dystansu(poprzedni['przebieg'], 0, self.j)}, "
                                    f"{poprzedni['data']}): {db.tekst_km_przejazdu(roznica, self.j)}.")
            if roznica > 0 and (not (self.e_km.value or "").strip() or self._km_z_licznika):
                jedna_strona = roznica / 2 if self.c_powrot.value else roznica
                self.e_km.value = db.wartosc_pola_dystansu(jedna_strona, self.j, 1)
                self._km_przy_otwarciu = jedna_strona
                self._km_z_licznika = True
                self._odswiez_razem(aktualizuj=False)
        if aktualizuj:
            self._aktualizuj()

    # ================= ZAMIANA, ZAPIS TRASY =================

    def _zamien(self):
        self.e_skad.value, self.e_dokad.value = self.e_dokad.value, self.e_skad.value
        self._aktualizuj()

    def _okno_zapisu_trasy(self):
        km = self._km_jednej_strony()
        nazwa_domyslna = db.opis_trasy(self.e_skad.value, self.e_dokad.value) or (self.e_cel.value or "").strip()
        e_nazwa = ft.TextField(label="Nazwa trasy", value=nazwa_domyslna, hint_text="np. Do biura, Klient ABC",
                               **utils.styl_pola())
        opis = [db.opis_trasy(self.e_skad.value, self.e_dokad.value, self.c_powrot.value) or "bez trasy"]
        if km:
            opis.append(db.tekst_km_przejazdu(km, self.j) + (" ×2" if self.c_powrot.value else ""))
        opis.append("służbowy" if self.rodzaj == SLUZBOWY else "prywatny")
        if (self.e_cel.value or "").strip():
            opis.append(self.e_cel.value.strip())

        def zapisz(e):
            utils.ustaw_blad(e_nazwa)
            if not (e_nazwa.value or "").strip():
                utils.ustaw_blad(e_nazwa, "Podaj nazwę trasy")
                return self._page.update()
            if not km:
                utils.ustaw_blad(e_nazwa, "Najpierw podaj kilometry przejazdu")
                return self._page.update()
            db.zapisz_szablon_przejazdu(
                self.state.auto_id, e_nazwa.value, self.e_skad.value, self.e_dokad.value, self.e_cel.value,
                self.rodzaj == SLUZBOWY, km, self.c_powrot.value,
            )
            utils.zamknij_dialog(self._page, dlg)
            utils.wypchnij_w_tle(self._page, self.state.auto_id, "zapisana trasa")
            utils.pokaz_komunikat(self._page, f"Zapisano trasę „{' '.join(e_nazwa.value.split())}” — "
                                              "jest też w kalkulatorze podróży.")

        dlg = ft.AlertDialog(
            title=ft.Text("Zapisz jako trasę", weight="bold"),
            content=ft.Column([e_nazwa, utils.podpis("Zapamiętam: " + " • ".join(opis))], tight=True, spacing=10),
            actions=[
                ft.TextButton("Anuluj", on_click=lambda e: utils.zamknij_dialog(self._page, dlg)),
                ft.Button("Zapisz", on_click=zapisz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY),
            ],
        )
        utils.otworz_dialog(self._page, dlg)

    # ================= ZAPIS =================

    def _aktualizuj(self, kontrolka=None):
        try:
            (kontrolka or self._page).update()
        except Exception:
            # Kontrolka jeszcze poza stroną (budowa widoku) — pierwszy render
            # i tak pokaże aktualny stan.
            log.polkniety("odświeżenie formularza przejazdu")

    def _migawka_formularza(self):
        return (self.e_data.value, self.e_skad.value, self.e_dokad.value, self.e_cel.value, self.e_km.value,
                self.c_powrot.value, self.rodzaj, self.e_licznik.value, self.e_kierowca.value, self.k_notatka.value)

    def _czy_zmieniono(self):
        return self._migawka_formularza() != self._stan_poczatkowy

    def _dane(self):
        km = self._km_razem()
        return {
            "data": self.e_data.value, "skad": self.e_skad.value, "dokad": self.e_dokad.value,
            "cel": self.e_cel.value, "km": km or 0, "powrot": self.c_powrot.value,
            "sluzbowy": self.rodzaj == SLUZBOWY, "kierowca": self.e_kierowca.value,
            "licznik": self._licznik_km(),
        }

    def zapisz(self, e):
        for pole in (self.e_data, self.e_skad, self.e_km, self.e_licznik):
            utils.ustaw_blad(pole)
        dane = self._dane()
        bledy = []
        if not self.e_data.value:
            bledy.append((self.e_data, "Wybierz datę przejazdu"))
        if not dane["km"]:
            bledy.append((self.e_km, "Podaj kilometry większe od zera"))
        if not any((dane[k] or "").strip() for k in ("skad", "dokad", "cel")):
            bledy.append((self.e_skad, "Podaj trasę albo cel przejazdu"))
        if (self.e_licznik.value or "").strip() and dane["licznik"] is None:
            bledy.append((self.e_licznik, "Stan licznika to liczba większa od zera"))
        if bledy:
            return utils.pokaz_bledy_formularza(self._page, bledy)

        if dane["licznik"] and utils.sprawdz_podejrzany_przebieg(
                self._page, self.e_licznik, self.state.auto_id, dane["licznik"], wyklucz_id=self.przejazd_id,
                tabela="przejazdy", nowa_data_str=dane["data"]):
            return

        rekord_id = db.zapisz_przejazd(self.state.auto_id, dane, self.przejazd_id)
        if not rekord_id:
            return utils.pokaz_komunikat(self._page, "Nie zapisano — tego przejazdu już nie ma.",
                                         utils.KOLOR_STATUS["error"])
        utils.zapisz_notatke_z_formularza("przejazdy", rekord_id, self.k_notatka.value, self.notatka_bazowa)
        utils.wypchnij_w_tle(self._page, self.state.auto_id, "przejazd")
        utils.przejdz(self._page, self._trasa_miesiaca(dane["data"]))
        rodzaj = "służbowo" if dane["sluzbowy"] else "prywatnie"
        utils.pokaz_komunikat(self._page, f"Zapisano przejazd • {db.tekst_km_przejazdu(dane['km'], self.j)} {rodzaj}")


def dzien_dla_miesiaca(rok, miesiac, dzis=None) -> str:
    """Domyślna data nowego przejazdu dodawanego z ekranu danego miesiąca:
    dziś w bieżącym miesiącu, ostatni dzień w minionym, pierwszy w przyszłym."""
    dzis = dzis or datetime.now().date()
    if (rok, miesiac) == (dzis.year, dzis.month):
        return dzis.strftime("%d.%m.%Y")
    if (rok, miesiac) < (dzis.year, dzis.month):
        return db.koniec_miesiaca(rok, miesiac).strftime("%d.%m.%Y")
    return date(rok, miesiac, 1).strftime("%d.%m.%Y")


__all__ = [
    "FormularzPrzejazduView",
    "PRYWATNY",
    "SLUZBOWY",
    "dzien_dla_miesiaca",
]
