"""„Ewidencja przebiegu” — przejazdy prywatne i służbowe miesiąc po miesiącu (N-01).

Aplikacja znała licznik, a nie wiedziała, PO CO były kilometry. Ten ekran
prowadzi ewidencję: przejazdy wybranego miesiąca, ich podział na służbowe
i prywatne, kwotę kilometrówki, podział kosztów miesiąca w tej samej
proporcji i licznik na początek i koniec okresu — z „nieopisanymi km”, czyli
tym, czego w ewidencji brakuje. Stąd idzie raport miesiąca (PDF albo CSV)
w jednym z trzech układów i „Zamknij miesiąc” — stan licznika na ostatni dzień.

Liczy wszystko db.podsumowanie_ewidencji; ten sam rachunek stoi na kafelku
kokpitu, w przypomnieniu i w raporcie. Tryb ewidencji (podział, kilometrówka,
VAT) i stawka należą do pojazdu na tym telefonie — ustawia się je zębatką
w pasku.
"""

from datetime import datetime

import flet as ft

import db
import log
import utils
from views.formularze.przejazd import dzien_dla_miesiaca


IKONY_TRYBU = {
    "podzial": ft.Icons.PIE_CHART_OUTLINE,
    "kilometrowka": ft.Icons.PAYMENTS,
    "vat": ft.Icons.BUSINESS_CENTER,
}


class EwidencjaPrzebieguView(ft.View):
    def __init__(self, page: ft.Page, state, rok=None, miesiac=None):
        self._page = page
        self.state = state
        self.j = utils.jednostka_dystansu()
        dzis = datetime.now().date()
        rok, miesiac = utils.parsuj_int(rok, 0), utils.parsuj_int(miesiac, 0)
        if 2000 <= rok <= 2100 and 1 <= miesiac <= 12 and (rok, miesiac) <= (dzis.year, dzis.month):
            self.rok, self.miesiac = rok, miesiac
        else:
            self.rok, self.miesiac = dzis.year, dzis.month
        self.podglad = bool(state.auto_id) and db.czy_tylko_podglad(state.auto_id)
        self.dane = None

        akcje = [ft.IconButton(ft.Icons.TUNE, tooltip="Ustawienia ewidencji",
                               on_click=lambda e: self._okno_ustawien())] if state.auto_id else None
        appbar = utils.zbuduj_pasek_z_powrotem(page, "Ewidencja przebiegu", "/", akcje_dodatkowe=akcje,
                                               ikona=ft.Icons.ALT_ROUTE)

        if not state.auto_id:
            super().__init__(
                route="/ewidencja", padding=15, spacing=15, appbar=appbar,
                controls=[utils.ekran_braku_danych(
                    ikona=ft.Icons.DIRECTIONS_CAR,
                    tytul="Brak wybranego pojazdu",
                    opis="Dodaj pojazd, aby prowadzić jego ewidencję przebiegu.",
                    tekst_przycisku="Dodaj pojazd",
                    on_click=lambda e: utils.przejdz(self._page, "/auto/nowy"),
                )],
            )
            return

        fab = None if self.podglad else utils.fab_animowany(ft.Icons.ADD, lambda e: self._dodaj(),
                                                            tooltip="Dodaj przejazd")
        super().__init__(
            route=f"/ewidencja/{self.rok}/{self.miesiac}", padding=15, spacing=12, appbar=appbar,
            floating_action_button=fab,
            controls=[utils.zbuduj_etapami(page, utils.szkielet_ekranu(page, kafle=2, karty=3), self._tresc,
                                           widok=self)],
            scroll=ft.ScrollMode.AUTO,
        )

    # ================= SKŁAD EKRANU =================

    def _tresc(self):
        self.dane = db.podsumowanie_ewidencji(self.state.auto_id, self.rok, self.miesiac)
        elementy = [self._pasek_miesiecy(), self._karta_miesiaca()]
        elementy += self._zdania()
        elementy.append(self._przyciski())
        elementy += self._lista()
        elementy.append(utils.dol_bezpieczny(70))
        return ft.Column(elementy, spacing=12)

    def odswiez_w_miejscu(self):
        """Po filtrze, zmianie rodzaju, usunięciu albo zamknięciu miesiąca —
        ten sam ekran, więc pozycja przewijania zostaje (utils.odswiez_ekran)."""
        self.controls = [self._tresc()]
        try:
            self.update()
        except Exception:
            log.polkniety("odświeżenie ekranu ewidencji przebiegu")

    def _km(self, km):
        return db.tekst_km_przejazdu(km, self.j)

    def _kwota(self, wartosc):
        return f"{utils.formatuj_liczba(wartosc or 0)} {utils.symbol_waluty()}"

    def _pasek_miesiecy(self):
        """Strzałki chodzą po kolejnych miesiącach, także pustych — ewidencję
        dopisuje się też do miesiąca, w którym jeszcze nic nie ma. Dalej niż
        bieżący miesiąc nie wolno. Nazwa miesiąca otwiera listę miesięcy
        z przejazdami."""
        dzis = datetime.now().date()
        poprzedni = (self.rok - 1, 12) if self.miesiac == 1 else (self.rok, self.miesiac - 1)
        nastepny = (self.rok + 1, 1) if self.miesiac == 12 else (self.rok, self.miesiac + 1)
        nastepny = nastepny if nastepny <= (dzis.year, dzis.month) else None

        def strzalka(ikona, cel):
            return ft.IconButton(
                ikona, disabled=cel is None,
                tooltip=db.nazwa_miesiaca(*cel).capitalize() if cel else None,
                on_click=(lambda e: utils.przejdz(self._page, f"/ewidencja/{cel[0]}/{cel[1]}")) if cel else None,
            )

        return ft.Row([
            strzalka(ft.Icons.CHEVRON_LEFT, poprzedni),
            ft.Container(
                content=ft.Row([
                    ft.Text(db.nazwa_miesiaca(self.rok, self.miesiac).capitalize(), weight="bold",
                            size=utils.FS["title"]),
                    ft.Icon(ft.Icons.ARROW_DROP_DOWN, size=20, color=ft.Colors.ON_SURFACE_VARIANT),
                ], spacing=2, tight=True, alignment=ft.MainAxisAlignment.CENTER),
                alignment=ft.Alignment.CENTER, expand=True, ink=True, border_radius=utils.RADIUS["sm"],
                padding=ft.Padding(8, 6, 8, 6), tooltip="Miesiące z przejazdami",
                on_click=lambda e: self._okno_miesiecy(),
            ),
            strzalka(ft.Icons.CHEVRON_RIGHT, nastepny),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

    def _karta_miesiaca(self):
        d = self.dane
        kolor_sl = utils.KOLORY_RODZAJU_PRZEJAZDU[db.RODZAJ_SLUZBOWY]
        kolor_pr = utils.KOLORY_RODZAJU_PRZEJAZDU[db.RODZAJ_PRYWATNY]
        udzial = d["udzial_sluzbowy"]
        tryb = d["tryb"]

        wiersze = [
            ft.Row([
                ft.Icon(IKONY_TRYBU.get(tryb, ft.Icons.ALT_ROUTE), size=16, color=ft.Colors.PRIMARY),
                utils.etykieta(db.TRYBY_EWIDENCJI[tryb], expand=True),
            ], spacing=6),
            ft.Row([
                ft.Column([utils.etykieta("Służbowo"),
                           utils.wartosc(self._km(d["km_sluzbowe"]), size=utils.FS["display"], color=kolor_sl)],
                          spacing=0, tight=True),
                ft.Column([utils.etykieta("Prywatnie"),
                           utils.wartosc(self._km(d["km_prywatne"]), size=utils.FS["display"], color=kolor_pr)],
                          spacing=0, tight=True, horizontal_alignment=ft.CrossAxisAlignment.END),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.ProgressBar(value=udzial or 0, color=kolor_sl,
                           bgcolor=kolor_pr if d["km"] else utils.tlo_toru(self._page), height=8, border_radius=4),
            utils.podpis(
                (f"{utils.formatuj_liczba((udzial or 0) * 100, 0)}% służbowo • " if udzial is not None else "")
                + db.liczba_z_odmiana(d["liczba"], "przejazd", "przejazdy", "przejazdów")
                + (f" • razem {self._km(d['km'])}" if d["km"] else "")
            ),
        ]
        bloki = []
        if tryb == "kilometrowka" or (d["kilometrowka"]["stawka"] and d["km_sluzbowe"]):
            bloki.append(self._blok_kilometrowki())
        if tryb == "podzial" and d["koszty"] and d["koszty"]["razem"]:
            bloki.append(self._blok_kosztow())
        bloki.append(self._blok_licznika())
        r = d["rok_do_dzis"]
        if r["km"] and self.miesiac > 1:
            bloki.append(utils.podpis(
                f"Od początku {self.rok}: {self._km(r['km'])}, z tego "
                f"{utils.formatuj_liczba((r['udzial_sluzbowy'] or 0) * 100, 0)}% służbowo"))
        return ft.Container(
            padding=utils.SPACING["lg"], **utils.powierzchnia(self._page, "karta", cien="md"),
            content=ft.Column(wiersze + bloki, spacing=utils.SPACING["sm"]),
        )

    def _blok(self, ikona, tytul, linie, kolor=None):
        return ft.Container(
            padding=utils.SPACING["sm"], **utils.powierzchnia(self._page, "blok"),
            content=ft.Column([
                ft.Row([ft.Icon(ikona, size=15, color=kolor or ft.Colors.PRIMARY),
                        utils.etykieta(tytul, expand=True)], spacing=6),
                *linie,
            ], spacing=2),
        )

    def _blok_kilometrowki(self):
        k = self.dane["kilometrowka"]
        if not k["stawka"]:
            return self._blok(ft.Icons.PAYMENTS, "Kilometrówka", [
                utils.podpis("Ustaw stawkę za kilometr, a policzę kwotę do zwrotu."),
                ft.Row([ft.TextButton("Ustaw stawkę", icon=ft.Icons.TUNE, on_click=lambda e: self._okno_ustawien())]),
            ])
        return self._blok(ft.Icons.PAYMENTS, "Kilometrówka", [
            utils.wartosc(self._kwota(k["kwota"])),
            utils.podpis(f"{self._km(k['km'])} służbowo × {utils.formatuj_liczba(k['stawka'])} "
                         f"{utils.symbol_waluty()}/{self.j}"),
        ])

    def _blok_kosztow(self):
        d = self.dane
        koszty = d["koszty"]
        linie = [utils.wartosc(self._kwota(koszty["razem"]))]
        if d["koszty_sluzbowe"] is not None:
            linie.append(utils.podpis(f"służbowe {self._kwota(d['koszty_sluzbowe'])} • "
                                      f"prywatne {self._kwota(d['koszty_prywatne'])} — w proporcji kilometrów"))
        return self._blok(ft.Icons.PIE_CHART_OUTLINE, "Koszty miesiąca", linie)

    def _blok_licznika(self):
        licznik = self.dane["licznik"]
        if licznik["start"] is None and licznik["koniec"] is None:
            return self._blok(ft.Icons.SPEED, "Licznik", [
                utils.podpis("Brak odczytów licznika z tego okresu — wpisz stan po przejeździe albo zamknij miesiąc.")])
        linie = []
        if licznik["start"] is not None:
            linie.append(utils.podpis(f"Początek: {db.tekst_dystansu(licznik['start'], 0, self.j)} "
                                      f"({licznik['data_start'].strftime('%d.%m.%Y')})"))
        if licznik["koniec"] is not None:
            linie.append(utils.podpis(f"Koniec: {db.tekst_dystansu(licznik['koniec'], 0, self.j)} "
                                      f"({licznik['data_koniec'].strftime('%d.%m.%Y')})"))
        kolor = None
        reszta = licznik["nieopisane_km"]
        if licznik["km"] is not None:
            linie.append(utils.wartosc(f"{self._km(licznik['km'])} według licznika"))
            if reszta is not None and self.dane["tryb"] != "kilometrowka":
                if abs(reszta) < 1:
                    kolor = utils.KOLOR_STATUS["ok"]
                    linie.append(utils.podpis("Licznik zgadza się z ewidencją.", color=kolor))
                elif reszta > 0:
                    kolor = utils.KOLOR_STATUS["warning"]
                    linie.append(utils.podpis(f"Nieopisane: {self._km(reszta)}", color=kolor))
                else:
                    kolor = utils.KOLOR_STATUS["warning"]
                    linie.append(utils.podpis(f"W ewidencji więcej o {self._km(-reszta)}", color=kolor))
        return self._blok(ft.Icons.SPEED, "Licznik", linie, kolor)

    def _zdania(self):
        """Ostrzeżenia miesiąca dla trybu pojazdu — te same zdania stoją pod
        tabelą raportu."""
        wynik = []
        for poziom, zdanie in db.zdania_ewidencji(self.dane):
            kolor = utils.KOLOR_STATUS["warning"] if poziom == "warning" else utils.KOLOR_STATUS["info"]
            wynik.append(ft.Container(
                padding=utils.SPACING["sm"], border_radius=utils.RADIUS["sm"],
                bgcolor=ft.Colors.with_opacity(0.10, kolor),
                content=ft.Row([
                    ft.Icon(ft.Icons.WARNING_AMBER if poziom == "warning" else ft.Icons.INFO_OUTLINE,
                            size=16, color=kolor),
                    ft.Text(zdanie, size=utils.FS["label"], expand=True),
                ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START),
            ))
        return wynik

    def _przyciski(self):
        przyciski = [ft.OutlinedButton("Raport miesiąca", icon=ft.Icons.PICTURE_AS_PDF,
                                       on_click=lambda e: self._okno_raportu())]
        stan = db.stan_na_koniec_miesiaca(self.state.auto_id, self.rok, self.miesiac)
        if stan["zamkniety"]:
            przyciski.append(ft.Row([
                ft.Icon(ft.Icons.EVENT_AVAILABLE, size=16, color=utils.KOLOR_STATUS["ok"]),
                utils.podpis(f"Stan na {stan['koniec'].strftime('%d.%m')}: "
                             f"{db.tekst_dystansu(stan['odczyt'], 0, self.j)}"),
            ], spacing=4, tight=True))
        elif stan["mozna_zamknac"] and not self.podglad:
            przyciski.append(ft.OutlinedButton("Zamknij miesiąc", icon=ft.Icons.EVENT_AVAILABLE,
                                               on_click=lambda e: self._okno_zamkniecia()))
        return utils.pasek_zawijany(przyciski, spacing=8, run_spacing=8)

    # ================= LISTA PRZEJAZDÓW =================

    def _lista(self):
        przejazdy = self.dane["przejazdy"]
        if not przejazdy:
            opis = ("Dodaj przejazd — datę, skąd, dokąd, cel i kilometry — a policzę podział na służbowe "
                    "i prywatne, kilometrówkę i raport miesiąca.")
            if self.podglad:
                return [utils.podpis(f"W tym miesiącu nie ma przejazdów. {opis}")]
            return [utils.ekran_braku_danych(
                ikona=ft.Icons.ALT_ROUTE, tytul="Brak przejazdów w tym miesiącu", opis=opis,
                tekst_przycisku="Dodaj przejazd", on_click=lambda e: self._dodaj(),
            )]
        chipy, po_filtrach = utils.pasek_filtrow(self._page, self.state, przejazdy, [
            ("kategoria", "ewidencja_rodzaj", "rodzaj", "Rodzaj"),
            ("autor", "ewidencja_kierowca", "kierowca", "Kierowca"),
        ])
        elementy = [ft.Row(controls=chipy, scroll=ft.ScrollMode.ADAPTIVE, spacing=8)]
        if not po_filtrach:
            elementy.append(utils.podpis("Żaden przejazd nie pasuje do filtrów."))
        mapa_numerow = {p["id"]: i for i, p in enumerate(przejazdy, 1)}
        for p in reversed(po_filtrach):
            elementy.append(self._karta_przejazdu(p, mapa_numerow[p["id"]]))
        return elementy

    def _karta_przejazdu(self, p, numer):
        kolor = utils.KOLORY_RODZAJU_PRZEJAZDU[p["rodzaj"]]
        tresc = [
            ft.Row([
                ft.Text(p["data"], weight="bold", size=utils.FS["body_strong"]),
                ft.Container(
                    content=ft.Text(p["rodzaj"].lower(), size=utils.FS["caption"], color=kolor),
                    padding=ft.Padding(8, 2, 8, 2), border_radius=utils.RADIUS["pill"],
                    border=ft.Border.all(1, kolor),
                ),
                ft.Container(expand=True),
                utils.wartosc(self._km(p["km"])),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ]
        if p["trasa"]:
            tresc.append(ft.Row([
                ft.Icon(ft.Icons.ROUTE, size=14, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Text(p["trasa"], size=utils.FS["body"], expand=True),
            ], spacing=6))
        if p["cel"]:
            tresc.append(utils.podpis(p["cel"]))
        dopiski = [f"nr {numer}"]
        if p["kierowca"]:
            dopiski.append(p["kierowca"])
        if p["licznik"]:
            dopiski.append(f"licznik {db.tekst_dystansu(p['licznik'], 0, self.j)}")
        tresc.append(utils.podpis(" • ".join(dopiski)))
        tresc.append(utils.podglad_notatki(self._page, p.get("notatka"), p.get("notatka_autor"),
                                           p.get("notatka_data"), "Notatka przejazdu", pokaz_podpis=False))
        karta, kontener = utils.karta_listy(tresc, kolor_paska=kolor, page=self._page)
        kontener.on_click = lambda e, x=p: self._menu(x)
        return karta

    def _menu(self, p):
        auto_id = self.state.auto_id
        tytul = p["trasa"] or p["cel"] or "Przejazd"
        dodawanie = []
        if db.czy_moge_dodawac(auto_id):
            dodawanie.append({"ikona": ft.Icons.REPLAY, "tekst": "Powtórz dziś",
                              "opis": "Ta sama trasa z dzisiejszą datą",
                              "akcja": lambda: utils.przejdz(self._page, f"/ewidencja/powtorz/{p['id']}")})
            if not p["powrot"] and p["skad"] and p["dokad"]:
                dodawanie.append({"ikona": ft.Icons.U_TURN_LEFT, "tekst": "Trasa powrotna",
                                  "akcja": lambda: utils.przejdz(self._page, f"/ewidencja/powrot/{p['id']}")})
            dodawanie.append({"ikona": ft.Icons.BOOKMARK_ADD, "tekst": "Zapisz jako trasę",
                              "akcja": lambda: self._zapisz_jako_trase(p)})
        zmiany = utils.odsiej_akcje(auto_id, [
            {"ikona": ft.Icons.EDIT, "tekst": "Edytuj",
             "akcja": lambda: utils.przejdz(self._page, f"/ewidencja/edytuj/{p['id']}")},
            {"ikona": ft.Icons.HOME_OUTLINED if p["sluzbowy"] else ft.Icons.WORK_OUTLINE,
             "tekst": "Oznacz jako prywatny" if p["sluzbowy"] else "Oznacz jako służbowy",
             "akcja": lambda: self._zmien_rodzaj(p)},
            {"ikona": ft.Icons.STICKY_NOTE_2_OUTLINED, "tekst": "Notatka",
             "akcja": lambda: utils.szybka_notatka(self._page, "przejazdy", p["id"],
                                                   lambda: utils.odswiez_ekran(self._page), "Notatka przejazdu")},
            {"ikona": ft.Icons.DELETE, "tekst": "Usuń przejazd", "kolor": utils.KOLOR_STATUS["destructive"],
             "akcja": lambda: self._usun(p)},
        ], "przejazdy", p["id"])
        utils.pokaz_menu_kontekstowe(self._page, tytul, dodawanie + zmiany)

    def _zmien_rodzaj(self, p):
        if db.ustaw_rodzaj_przejazdu(p["id"], not p["sluzbowy"]):
            utils.wypchnij_w_tle(self._page, self.state.auto_id, "rodzaj przejazdu")
            utils.odswiez_ekran(self._page)
            utils.pokaz_komunikat(self._page, "Przejazd jest teraz " + ("prywatny." if p["sluzbowy"] else "służbowy."))

    def _usun(self, p):
        def wykonaj():
            # Nagrobek i „Cofnij” robi ogólny mechanizm usuwania; wypychamy
            # dopiero przy następnej synchronizacji, żeby cofnięcie miało sens.
            wynik = db.usun_z_cofnieciem("przejazdy", p["id"])
            utils.odswiez_ekran(self._page)
            utils.pokaz_komunikat_cofnij(self._page, f"Usunięto przejazd z {p['data']}.", wynik)

        utils.potwierdz(self._page, "Usunąć przejazd?",
                        f"{p['data']} • {p['trasa'] or p['cel']} • {self._km(p['km'])}", wykonaj)

    def _zapisz_jako_trase(self, p):
        e_nazwa = ft.TextField(label="Nazwa trasy", value=db.opis_trasy(p["skad"], p["dokad"]) or p["cel"],
                               **utils.styl_pola())

        def zapisz(e):
            utils.ustaw_blad(e_nazwa)
            if not (e_nazwa.value or "").strip():
                utils.ustaw_blad(e_nazwa, "Podaj nazwę trasy")
                return self._page.update()
            db.zapisz_szablon_przejazdu(self.state.auto_id, e_nazwa.value, p["skad"], p["dokad"], p["cel"],
                                        p["sluzbowy"], p["km_jednej_strony"], p["powrot"])
            utils.zamknij_dialog(self._page, dlg)
            utils.wypchnij_w_tle(self._page, self.state.auto_id, "zapisana trasa")
            utils.pokaz_komunikat(self._page, "Zapisano trasę — jest w formularzu przejazdu i w kalkulatorze.")

        dlg = ft.AlertDialog(
            title=ft.Text("Zapisz jako trasę", weight="bold"),
            content=ft.Column([e_nazwa, utils.podpis(" • ".join(x for x in (
                p["trasa"], p["cel"], self._km(p["km"]), p["rodzaj"].lower()) if x))], tight=True, spacing=10),
            actions=[
                ft.TextButton("Anuluj", on_click=lambda e: utils.zamknij_dialog(self._page, dlg)),
                ft.Button("Zapisz", on_click=zapisz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY),
            ],
        )
        utils.otworz_dialog(self._page, dlg)

    def _dodaj(self):
        dzien = dzien_dla_miesiaca(self.rok, self.miesiac)
        if dzien == datetime.now().strftime("%d.%m.%Y"):
            utils.przejdz(self._page, "/ewidencja/nowy")
        else:
            utils.przejdz(self._page, f"/ewidencja/nowy/dzien/{dzien}")

    # ================= OKNA =================

    def _okno_miesiecy(self):
        miesiace = db.miesiace_ewidencji(self.state.auto_id)
        dzis = datetime.now().date()
        pozycje = [{"ikona": ft.Icons.TODAY, "tekst": f"Bieżący: {db.nazwa_miesiaca(dzis.year, dzis.month)}",
                    "czyta": True, "akcja": lambda: utils.przejdz(self._page, f"/ewidencja/{dzis.year}/{dzis.month}")}]
        for rok, miesiac, liczba, km in miesiace[:24]:
            pozycje.append({
                "ikona": ft.Icons.CALENDAR_MONTH, "czyta": True,
                "tekst": (f"{db.nazwa_miesiaca(rok, miesiac).capitalize()} — "
                          f"{db.liczba_z_odmiana(liczba, 'przejazd', 'przejazdy', 'przejazdów')}, {self._km(km)}"),
                "akcja": lambda r=rok, m=miesiac: utils.przejdz(self._page, f"/ewidencja/{r}/{m}"),
            })
        utils.pokaz_menu_kontekstowe(self._page, "Miesiące ewidencji", pozycje)

    def _okno_zamkniecia(self):
        """Stan licznika na ostatni dzień miesiąca — odczyt ze źródła
        „ewidencja”. Podpowiedź: ostatni odczyt plus przejazdy po nim."""
        stan = db.stan_na_koniec_miesiaca(self.state.auto_id, self.rok, self.miesiac)
        koniec = stan["koniec"].strftime("%d.%m.%Y")
        pole = ft.TextField(label=f"Stan licznika na {koniec} ({self.j})",
                            value=db.wartosc_pola_dystansu(stan["podpowiedz"], self.j) if stan["podpowiedz"] else "",
                            keyboard_type=ft.KeyboardType.NUMBER, autofocus=True, **utils.styl_pola())
        linie = [utils.podpis("Zapisze się w historii licznika jako odczyt z ostatniego dnia miesiąca — to stan "
                              "na koniec okresu w ewidencji i początek następnego.")]
        if stan["podpowiedz"]:
            podpowiedz = (f"Podpowiedź: odczyt z {stan['data_odczytu'].strftime('%d.%m')} "
                          f"({db.tekst_dystansu(stan['odczyt'], 0, self.j)})")
            if stan["km_po_odczycie"]:
                podpowiedz += f" + przejazdy po nim ({self._km(stan['km_po_odczycie'])})"
            linie.append(utils.podpis(podpowiedz + "."))

        def zapisz(e):
            utils.ustaw_blad(pole)
            wartosc = utils.parsuj_float(pole.value, None)
            if wartosc is None or wartosc <= 0:
                utils.ustaw_blad(pole, "Podaj stan licznika")
                return self._page.update()
            km = db.dystans_na_km(wartosc, self.j, calkowity=True, km_przy_otwarciu=stan["podpowiedz"])
            if utils.sprawdz_podejrzany_przebieg(self._page, pole, self.state.auto_id, km, nowa_data_str=koniec):
                return
            db.zamknij_miesiac_ewidencji(self.state.auto_id, self.rok, self.miesiac, km)
            utils.zamknij_dialog(self._page, dlg)
            utils.wypchnij_w_tle(self._page, self.state.auto_id, "stan licznika na koniec miesiąca")
            utils.odswiez_ekran(self._page)
            utils.pokaz_komunikat(self._page, f"Zamknięto {db.nazwa_miesiaca(self.rok, self.miesiac)}: stan "
                                              f"{db.tekst_dystansu(km, 0, self.j)} na {koniec}.")

        dlg = ft.AlertDialog(
            title=ft.Text(f"Zamknij {db.nazwa_miesiaca(self.rok, self.miesiac)}", weight="bold"),
            content=ft.Column([pole, *linie], tight=True, spacing=10),
            actions=[
                ft.TextButton("Anuluj", on_click=lambda e: utils.zamknij_dialog(self._page, dlg)),
                ft.Button("Zapisz stan", on_click=zapisz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY),
            ],
        )
        utils.otworz_dialog(self._page, dlg)

    def _okno_raportu(self):
        """Układ i format raportu miesiąca. Układ podpowiada tryb pojazdu."""
        uklady = list(db.UKLADY_RAPORTU_EWIDENCJI)
        wybor = {"uklad": uklady.index(self.dane["tryb"]) if self.dane["tryb"] in uklady else 0, "format": 0}
        opisy = {
            "podzial": "Wszystkie przejazdy z rodzajem, podział kilometrów i kosztów miesiąca.",
            "vat": "Układ z art. 86a ustawy o VAT: numer rejestracyjny, stan licznika na początek i koniec "
                   "okresu, kolejne wpisy z celem, trasą, kilometrami i kierowcą, miejsce na podpis.",
            "kilometrowka": "Tylko przejazdy służbowe ze stawką i kwotą, Twoje dane i miejsce na podpis "
                            "pracodawcy.",
        }
        kontener_ukladu = ft.Container()
        kontener_formatu = ft.Container(width=220)
        opis = utils.podpis("")

        def odswiez():
            kontener_ukladu.content = utils.segmented_control(
                self._page, [(db.UKLADY_RAPORTU_EWIDENCJI[k], i) for i, k in enumerate(uklady)],
                wybor["uklad"], zmien_uklad)
            kontener_formatu.content = utils.segmented_control(
                self._page, [("PDF", 0, ft.Icons.PICTURE_AS_PDF), ("CSV", 1, ft.Icons.TABLE_CHART)],
                wybor["format"], zmien_format)
            opis.value = opisy[uklady[wybor["uklad"]]]

        def zmien_uklad(i):
            wybor["uklad"] = i
            odswiez()
            self._page.update()

        def zmien_format(i):
            wybor["format"] = i
            odswiez()
            self._page.update()

        async def generuj(e):
            utils.zamknij_dialog(self._page, dlg)
            await self._zapisz_raport(uklady[wybor["uklad"]], "csv" if wybor["format"] else "pdf")

        odswiez()
        dlg = ft.AlertDialog(
            title=ft.Text(f"Raport: {db.nazwa_miesiaca(self.rok, self.miesiac)}", weight="bold"),
            content=ft.Column([kontener_ukladu, opis, kontener_formatu], tight=True, spacing=12, width=420),
            actions=[
                ft.TextButton("Anuluj", on_click=lambda e: utils.zamknij_dialog(self._page, dlg)),
                ft.Button("Zapisz raport", icon=ft.Icons.IOS_SHARE, on_click=generuj,
                          bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY),
            ],
        )
        utils.otworz_dialog(self._page, dlg)

    async def _zapisz_raport(self, uklad, format_pliku):
        zapisywacz = getattr(self._page, "zapisz_bajty_pliku", None)
        if zapisywacz is None:
            utils.pokaz_komunikat(self._page, "Zapis pliku jest niedostępny w tej wersji aplikacji.",
                                  utils.KOLOR_STATUS["error"])
            return
        try:
            dane = db.dane_raportu_ewidencji(self.state.auto_id, self.rok, self.miesiac, uklad)
            bajty = (db.generuj_csv_ewidencji(dane) if format_pliku == "csv" else db.generuj_pdf_ewidencji(dane))
        except Exception as ex:
            log.polkniety("raport ewidencji przebiegu")
            utils.pokaz_komunikat(self._page, f"Nie udało się przygotować raportu: {ex}", utils.KOLOR_STATUS["error"])
            return
        nazwa = f"{dane['nazwa_pliku']}_{utils.bezpieczna_nazwa_pliku(self.state.auto_nazwa)}.{format_pliku}"
        await zapisywacz(nazwa, bajty)

    def _okno_ustawien(self):
        """Tryb ewidencji i stawka kilometrówki (pojazd na tym telefonie) oraz
        dane osoby do nagłówka kilometrówki (wspólne dla pojazdów)."""
        auto_id = self.state.auto_id
        ustawienia = db.pobierz_ustawienia_ewidencji(auto_id)
        osoba = db.pobierz_dane_osoby_ewidencji()
        tryb = {"wartosc": ustawienia["tryb"]}
        styl = utils.styl_pola()
        grupa = ft.RadioGroup(
            value=tryb["wartosc"],
            content=ft.Column([ft.Radio(value=k, label=v) for k, v in db.TRYBY_EWIDENCJI.items()], spacing=0),
        )
        domyslna = db.domyslna_stawka_kilometrowki(auto_id)
        e_stawka = ft.TextField(
            label=f"Stawka za 1 {self.j} ({utils.symbol_waluty()})",
            value=utils.formatuj_liczba(ustawienia["stawka"], 2) if ustawienia["stawka"] else "",
            hint_text=(f"puste = {utils.formatuj_liczba(domyslna, 2)} z pojemności silnika" if domyslna else None),
            keyboard_type=ft.KeyboardType.NUMBER, **styl,
        )
        e_osoba = ft.TextField(label="Imię i nazwisko", value=osoba["osoba"], **styl)
        e_adres = ft.TextField(label="Adres zamieszkania", value=osoba["adres"], **styl)
        e_pracodawca = ft.TextField(label="Pracodawca (opcjonalnie)", value=osoba["pracodawca"], **styl)

        def chip_stawki(opis, stawka):
            def wybierz(e):
                e_stawka.value = utils.formatuj_liczba(stawka, 2)
                self._page.update()
            return ft.Container(
                content=ft.Text(f"{utils.formatuj_liczba(stawka, 2)} — {opis.lower()}", size=utils.FS["label"]),
                padding=ft.Padding(10, 4, 10, 4), border_radius=utils.RADIUS["pill"],
                border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT), ink=True, on_click=wybierz,
            )

        stawki = []
        if utils.symbol_waluty() == "PLN" and self.j == "km":
            stawki = [utils.pasek_zawijany([chip_stawki(o, s) for o, s in db.STAWKI_KILOMETROWKI]),
                      utils.podpis("Stawki z rozporządzenia to kwoty maksymalne — pracodawca może płacić mniej.")]

        def zapisz(e):
            utils.ustaw_blad(e_stawka)
            tekst = (e_stawka.value or "").strip()
            stawka = utils.parsuj_float(tekst, None) if tekst else None
            if tekst and (stawka is None or stawka <= 0):
                utils.ustaw_blad(e_stawka, "Wpisz kwotę, np. 1,15")
                return self._page.update()
            db.zapisz_ustawienia_ewidencji(auto_id, grupa.value, stawka)
            db.zapisz_dane_osoby_ewidencji(e_osoba.value, e_adres.value, e_pracodawca.value)
            utils.zamknij_dialog(self._page, dlg)
            utils.odswiez_ekran(self._page)
            utils.pokaz_komunikat(self._page, "Zapisano ustawienia ewidencji.")

        dlg = ft.AlertDialog(
            title=ft.Text("Ustawienia ewidencji", weight="bold"),
            content=ft.Column([
                utils.etykieta("Po co prowadzisz ewidencję tego auta?"), grupa,
                ft.Divider(height=8),
                utils.etykieta("Kilometrówka"), e_stawka, *stawki,
                ft.Divider(height=8),
                utils.etykieta("Dane do raportu kilometrówki"), e_osoba, e_adres, e_pracodawca,
            ], tight=True, spacing=8, scroll=ft.ScrollMode.AUTO, width=440),
            actions=[
                ft.TextButton("Anuluj", on_click=lambda e: utils.zamknij_dialog(self._page, dlg)),
                ft.Button("Zapisz", on_click=zapisz, bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY),
            ],
        )
        utils.otworz_dialog(self._page, dlg)


__all__ = [
    "EwidencjaPrzebieguView",
    "IKONY_TRYBU",
]
