import flet as ft
from datetime import datetime
from date import parsuj_date
import db
import sync
import utils
from state import MIESIACE_NAZWY


class PodzialKosztowView(ft.View):
    """Saldo współdzielonego auta: kto ile zapłacił, kto komu ile jest winien
    i „Rozliczone”, które zeruje saldo z datą. Pod saldem zostaje zestawienie
    miesiąca (proporcje), na dole historia rozliczeń.

    Saldo liczy się z całej podpisanej historii minus migawki rozliczeń (patrz
    db/rozliczenia.py), więc spóźniony albo poprawiony wpis sprzed rozliczenia
    pojawia się tu jako korekta, zamiast zniknąć z rachunku."""

    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state

        appbar = utils.zbuduj_pasek_z_powrotem(page, "Podział kosztów", "/", ikona=ft.Icons.HANDSHAKE)

        if not self.state.auto_id:
            super().__init__(
                route="/podzial", padding=15, spacing=15, appbar=appbar,
                controls=[utils.ekran_braku_danych(
                    ikona=ft.Icons.DIRECTIONS_CAR,
                    tytul="Brak wybranego pojazdu",
                    opis="Wybierz pojazd, aby zobaczyć podział kosztów.",
                    tekst_przycisku="Wróć na start",
                    on_click=lambda e: utils.przejdz(self._page, "/")
                )]
            )
            return

        wspolny_id, _ = sync.czy_udostepniony(self.state.auto_id)
        if not wspolny_id:
            super().__init__(
                route="/podzial", padding=15, spacing=15, appbar=appbar,
                controls=[utils.ekran_braku_danych(
                    ikona=ft.Icons.PEOPLE,
                    tytul="Ten pojazd nie jest współdzielony",
                    opis="Podział kosztów ma sens, gdy kilka osób dopisuje wydatki do tego samego pojazdu. Włącz współdzielenie, aby zacząć śledzić, kto ile wydał.",
                    tekst_przycisku="Przejdź do współdzielenia",
                    on_click=lambda e: utils.przejdz(self._page, "/wspoldzielenie")
                )]
            )
            return

        # Paski udziałów w zestawieniu miesiąca najeżdżają od zera, jeden po
        # drugim — tam liczy się nie sama kwota, tylko PROPORCJA między
        # domownikami, a tę widać dopiero, kiedy paski zatrzymają się w różnych
        # miejscach. Saldo nad nimi stoi od razu: to po nie się tu przychodzi.
        self.scena = utils.ScenaWejscia(
            wlaczona=db.czy_animacje_interfejsu()
            and utils.pierwsze_pokazanie(state, "podzial", state.auto_id),
            kaskada=True,
        )

        appbar = utils.zbuduj_pasek_z_powrotem(
            page, "Podział kosztów", "/", ikona=ft.Icons.HANDSHAKE,
            akcje_dodatkowe=[utils.przycisk_synchronizacji(page, utils.funkcja_szybkiej_synchronizacji(page, self.state.auto_id, "/podzial"))]
        )

        self.waluta = utils.symbol_waluty()
        self.saldo = db.saldo_rozliczen(self.state.auto_id)
        self.historia = db.pobierz_rozliczenia(self.state.auto_id)
        self.moge_rozliczac = db.czy_moge_dodawac(self.state.auto_id)

        elementy = [
            self._karta_salda(),
            *self._sekcja_miesiaca(),
            *self._sekcja_historii(),
            self._nota(),
            utils.dol_bezpieczny(20),
        ]

        super().__init__(
            route="/podzial", padding=15, spacing=15, appbar=appbar,
            controls=elementy, scroll=ft.ScrollMode.AUTO
        )
        self.scena.uruchom(page)

    # ------------------------------------------------------------- kwoty

    def _kwota(self, zl):
        return f"{utils.formatuj_liczba(zl)} {self.waluta}"

    def _kwota_ze_znakiem(self, zl):
        if abs(zl) < 0.005:
            return self._kwota(0)
        return f"{'+' if zl > 0 else '−'}{self._kwota(abs(zl))}"

    # ------------------------------------------------------------- saldo

    def _karta_salda(self):
        """Na górze ekranu, bo to po nie się tu przychodzi: kto jest na plusie,
        kto na minusie i jakim przelewem to wyrównać."""
        s = self.saldo
        tresc = [
            ft.Row(utils.tytul_sekcji(ft.Icons.ACCOUNT_BALANCE_WALLET, "Saldo", rozmiar=18),
                   spacing=utils.SPACING["sm"]),
            utils.podpis(self._opis_okresu()),
        ]

        for o in s["osoby"]:
            tresc.append(self._wiersz_osoby(o))

        tresc.append(self._blok_przelewow())
        tresc.extend(self._uwagi_salda())

        przycisk = self._przycisk_rozliczenia()
        if przycisk:
            tresc.append(ft.Row([przycisk], alignment=ft.MainAxisAlignment.END))

        return ft.Container(
            padding=utils.SPACING["md"],
            **utils.powierzchnia(self._page, "karta"),
            content=ft.Column(tresc, spacing=utils.SPACING["sm"]),
        )

    def _opis_okresu(self):
        s = self.saldo
        od = (f"Od rozliczenia {s['od_dnia'].strftime(db.FORMAT_DATY_ROZLICZENIA)}"
              if s["od_dnia"] else "Od pierwszego podpisanego wpisu")
        if not s["suma"]:
            return (f"{od} nie ma nowych wydatków." if s["od_dnia"]
                    else "Nie ma jeszcze wydatków podpisanych imieniem.")
        osob = s["uczestnikow"]
        return (f"{od}: wydatki {self._kwota(s['suma'])} · po {self._kwota(s['na_osobe'])} "
                f"na osobę ({osob} {utils._odmiana_liczby(osob, 'osoba', 'osoby', 'osób')}).")

    def _wiersz_osoby(self, o):
        if o["saldo"] > 0.004:
            kolor, stan = utils.KOLOR_STATUS["ok"], "dostaje"
        elif o["saldo"] < -0.004:
            kolor, stan = utils.KOLOR_STATUS["warning"], "oddaje"
        else:
            kolor, stan = None, "kwita"

        szczegoly = f"zapłacone {self._kwota(o['zaplacil'])} · przypada {self._kwota(o['przypada'])}"
        if abs(o["korekta"]) >= 0.005:
            szczegoly += f" · korekta {self._kwota_ze_znakiem(o['korekta'])}"

        return ft.Row([
            ft.Icon(ft.Icons.PERSON, color=ft.Colors.PRIMARY, size=18),
            ft.Column([
                ft.Text(o["osoba"], size=utils.FS["body_strong"], no_wrap=True,
                        overflow=ft.TextOverflow.ELLIPSIS),
                utils.podpis(szczegoly),
            ], spacing=2, expand=True),
            ft.Column([
                utils.wartosc(self._kwota_ze_znakiem(o["saldo"]), color=kolor, no_wrap=True),
                utils.podpis(stan),
            ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.END),
        ], spacing=utils.SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.START)

    def _blok_przelewow(self):
        """„Kto komu ile” — to, co trzeba zrobić, a nie tylko stan konta."""
        przelewy = self.saldo["przelewy"]
        if przelewy:
            wiersze = [utils.etykieta("Kto komu ile")] + [self._wiersz_przelewu(p) for p in przelewy]
        else:
            wiersze = [ft.Row([
                ft.Icon(ft.Icons.CHECK_CIRCLE, size=18, color=utils.KOLOR_STATUS["ok"]),
                ft.Text("Wszyscy są kwita.", size=utils.FS["body"], expand=True),
            ], spacing=6)]
        return ft.Container(
            padding=utils.SPACING["sm"],
            **utils.powierzchnia(self._page, "blok"),
            content=ft.Column(wiersze, spacing=6),
        )

    def _wiersz_przelewu(self, p):
        """„Ola → Kamil ... 100,00 zł” — ten sam wiersz w karcie i w oknie."""
        return ft.Row([
            ft.Text(p["od"], size=utils.FS["body"], no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
            ft.Icon(ft.Icons.ARROW_FORWARD, size=14, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Text(p["do"], size=utils.FS["body"], no_wrap=True,
                    overflow=ft.TextOverflow.ELLIPSIS, expand=True),
            utils.wartosc(self._kwota(p["kwota"]), no_wrap=True),
        ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def _uwagi_salda(self):
        s = self.saldo
        uwagi = []
        if not s["rozliczen"] and s["suma"]:
            uwagi.append("Saldo obejmuje wszystko od pierwszego podpisanego wpisu. Jeśli wcześniejsze "
                         "koszty nie są wspólne, kliknij „Rozliczone” z datą, od której liczycie razem.")
        if s["uczestnikow"] == 1:
            uwagi.append("W rachunku jest na razie jedna osoba — druga dojdzie z pierwszym wpisem podpisanym "
                         "swoim imieniem (Ustawienia → Twoja atrybucja przy współdzieleniu).")
        if s["korekty"]:
            uwagi.append("Saldo zawiera korekty: wpisy sprzed ostatniego rozliczenia dopisane, poprawione "
                         "albo usunięte już po nim.")
        if s["bez_podpisu"]:
            n = s["bez_podpisu"]
            uwagi.append(f"{n} {utils._odmiana_liczby(n, 'wydatek', 'wydatki', 'wydatków')} bez podpisu "
                         f"({self._kwota(s['kwota_bez_podpisu'])}) poza saldem — nie wiadomo, kto płacił.")
        return [ft.Row([
            ft.Icon(ft.Icons.INFO_OUTLINE, size=15, color=ft.Colors.ON_SURFACE_VARIANT),
            utils.podpis(tekst, expand=True),
        ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.START) for tekst in uwagi]

    def _przycisk_rozliczenia(self):
        """Podgląd nie dostaje przycisku wcale — przycisk, który zawsze odmawia,
        jest gorszy od jego braku. Bez przelewów przycisk gaśnie, chyba że nie
        było jeszcze żadnego rozliczenia: wtedy służy do wskazania, od kiedy
        liczyć."""
        if not self.moge_rozliczac:
            return None
        s = self.saldo
        aktywny = bool(s["przelewy"]) or (not s["rozliczen"] and bool(s["suma"]))
        return ft.FilledButton(
            "Rozliczone", icon=ft.Icons.DONE_ALL, disabled=not aktywny,
            on_click=lambda e: self._okno_rozliczenia(),
        )

    def _okno_rozliczenia(self):
        """Data (domyślnie dziś), notatka i podgląd przelewów liczony na
        wybraną datę — wpisy z późniejszą datą zostają w nowym saldzie."""
        page = self._page
        auto_id = self.state.auto_id
        podglad = ft.Column(spacing=6, tight=True)

        def odswiez_podglad():
            utils.ustaw_blad(e_data)
            blad = db.blad_daty_rozliczenia(auto_id, e_data.value)
            if blad:
                utils.ustaw_blad(e_data, blad)
                podglad.controls = []
                return
            stan = db.saldo_rozliczen(auto_id, parsuj_date(e_data.value))
            if stan["przelewy"]:
                podglad.controls = [utils.etykieta("Kto komu ile")] + [
                    self._wiersz_przelewu(p) for p in stan["przelewy"]]
            else:
                podglad.controls = [utils.podpis("Do tej daty wszyscy są kwita — rozliczenie tylko zamknie okres.")]

        e_data = utils.pole_daty(page, "Data rozliczenia", datetime.now().strftime(db.FORMAT_DATY_ROZLICZENIA),
                                 po_zmianie=odswiez_podglad)
        e_notatka = utils.pole_notatki("", page, label="Notatka (np. przelew, gotówka)")
        odswiez_podglad()

        def zapisz(e):
            blad = db.blad_daty_rozliczenia(auto_id, e_data.value)
            if blad:
                utils.ustaw_blad(e_data, blad)
                page.update()
                return
            rozliczenie_id = db.zapisz_rozliczenie(auto_id, e_data.value, e_notatka.value)
            utils.zamknij_dialog(page, dlg)
            if not rozliczenie_id:
                utils.pokaz_komunikat(page, "Nie zapisano rozliczenia — przy tej roli nie dopisujesz niczego.",
                                      utils.KOLOR_STATUS["error"])
                return
            # Saldo jest wspólne: bez wysyłki drugi telefon dalej pokazywałby
            # dług, który właśnie został oddany.
            utils.wypchnij_w_tle(page, auto_id, "rozliczenie")
            utils.przejdz(page, "/podzial")
            utils.pokaz_komunikat(page, "Rozliczone — saldo wyzerowane.")

        dlg = ft.AlertDialog(
            modal=True,
            shape=ft.RoundedRectangleBorder(radius=utils.RADIUS["lg"]),
            title=ft.Row([
                ft.Icon(ft.Icons.DONE_ALL, color=ft.Colors.PRIMARY),
                ft.Text("Rozliczyć saldo?", weight="bold", expand=True),
            ], spacing=8),
            content=ft.Column([
                podglad,
                e_data,
                e_notatka,
                utils.podpis("Saldo wpisów do tej daty włącznie wróci do zera. Wpisy z późniejszą datą "
                             "trafią do nowego salda — tak samo jak wpisy sprzed niej dopisane albo "
                             "poprawione później."),
            ], tight=True, spacing=10),
            actions=[
                ft.TextButton("Anuluj", on_click=lambda e: utils.zamknij_dialog(page, dlg)),
                ft.FilledButton("Rozliczone", icon=ft.Icons.DONE_ALL, on_click=zapisz),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        utils.otworz_dialog(page, dlg)

    # ------------------------------------------------------------- miesiąc

    def _sekcja_miesiaca(self):
        """Kto ile wydał w wybranym miesiącu — proporcje, bez rad o „uczciwej
        części”: to, kto komu ile oddaje, mówi saldo nad tą sekcją."""
        dzis = datetime.now()
        self.rok = getattr(self.state, "podzial_rok", None) or dzis.year
        self.miesiac = getattr(self.state, "podzial_miesiac", None) or dzis.month

        def zmien_miesiac(delta):
            m, r = self.miesiac + delta, self.rok
            while m < 1: m += 12; r -= 1
            while m > 12: m -= 12; r += 1
            self.state.podzial_rok, self.state.podzial_miesiac = r, m
            utils.przejdz(self._page, "/podzial")

        tytul = ft.Row(utils.tytul_sekcji(ft.Icons.CALENDAR_MONTH, "Kto ile wydał w miesiącu", rozmiar=18),
                       spacing=utils.SPACING["sm"])

        pasek_miesiaca = ft.Row([
            ft.IconButton(ft.Icons.CHEVRON_LEFT, on_click=lambda e: zmien_miesiac(-1)),
            ft.Container(
                ft.Text(f"{MIESIACE_NAZWY[self.miesiac - 1]} {self.rok}", weight="bold", size=16),
                alignment=ft.Alignment.CENTER, expand=True
            ),
            ft.IconButton(ft.Icons.CHEVRON_RIGHT, on_click=lambda e: zmien_miesiac(1)),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

        dane = db.pobierz_podzial_kosztow(self.state.auto_id, self.rok, self.miesiac)
        waluta = self.waluta
        wyniki = []

        if not dane:
            wyniki.append(ft.Container(
                padding=30,
                content=ft.Text("Brak wydatków w tym miesiącu.", color=ft.Colors.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER)
            ))
        else:
            suma_wszystkich = sum(d["razem"] for d in dane)

            wyniki.append(ft.Container(
                padding=18, border_radius=16,
                bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.PRIMARY),
                content=ft.Column([
                    ft.Row([ft.Icon(ft.Icons.ACCOUNT_BALANCE_WALLET, color=ft.Colors.PRIMARY),
                            ft.Text("Suma wydatków w miesiącu", weight="bold", color=ft.Colors.PRIMARY)], spacing=8),
                    ft.Text(f"{utils.formatuj_liczba(suma_wszystkich)} {waluta}", size=24, weight="bold"),
                    utils.podpis("Tyle wydano w tym miesiącu. Kto komu ile oddaje, pokazuje saldo."),
                ], spacing=6)
            ))

            maks = max((d["razem"] for d in dane), default=0)
            for d in dane:
                proporcja = (d["razem"] / maks) if maks > 0 else 0
                self.scena.nastepny_wiersz()

                pary_kategorii = [
                    (utils.IKONY_KATEGORII_KOSZTOW["paliwo"], utils.formatuj_liczba(d["paliwo"], 0)) if d["paliwo"] > 0 else None,
                    (utils.IKONY_KATEGORII_KOSZTOW["serwis"], utils.formatuj_liczba(d["serwis"], 0)) if d["serwis"] > 0 else None,
                    (utils.IKONY_KATEGORII_KOSZTOW["inne"], utils.formatuj_liczba(d["inne"], 0)) if d["inne"] > 0 else None,
                ]
                opis_kategorii = utils.chipy_kwot(pary_kategorii) or ft.Text(
                    "Brak wydatków", size=12, color=ft.Colors.ON_SURFACE_VARIANT)

                wyniki.append(ft.Card(
                    elevation=1,
                    content=ft.Container(
                        padding=15, border_radius=10,
                        content=ft.Column([
                            ft.Row([
                                ft.Row([ft.Icon(ft.Icons.PERSON, color=ft.Colors.PRIMARY, size=18),
                                        ft.Text(d["osoba"], weight="bold", size=16, expand=True,
                                                no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS)],
                                       spacing=6, expand=True),
                                ft.Text(f"{utils.formatuj_liczba(d['razem'])} {waluta}", weight="bold", size=16, color=utils.KOLOR_STATUS["cost"], no_wrap=True)
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            self.scena.wskaznik(ft.ProgressBar(
                                value=max(0.03, proporcja), color=ft.Colors.PRIMARY,
                                bgcolor=utils.tlo_toru(self._page),
                                height=8, border_radius=4)),
                            opis_kategorii,
                            ft.Text(
                                f"Zatankował(a) {d['tankowania']}x • ok. {utils.formatuj_dystans(d['dystans_km'])} na liczniku"
                                if d["tankowania"] else "Brak tankowań w tym miesiącu",
                                size=12, color=ft.Colors.ON_SURFACE_VARIANT
                            ),
                        ], spacing=8)
                    )
                ))

        return [tytul, pasek_miesiaca, ft.Column(wyniki, spacing=15)]

    # ------------------------------------------------------------- historia

    def _sekcja_historii(self):
        tytul = ft.Row(utils.tytul_sekcji(ft.Icons.HISTORY, "Rozliczenia", rozmiar=18),
                       spacing=utils.SPACING["sm"])
        if not self.historia:
            return [tytul, utils.podpis("Jeszcze nic nie rozliczono. Po „Rozliczone” pojawi się tu data, "
                                        "kto komu ile oddał i kto to zapisał.")]
        return [tytul, ft.Column([self._karta_rozliczenia(r) for r in self.historia],
                                 spacing=utils.SPACING["sm"])]

    def _karta_rozliczenia(self, r):
        tresc = [ft.Row([
            utils.wartosc(r["data"]),
            utils.podpis("nie liczy się") if not r["liczy_sie"] else ft.Container(),
        ], spacing=utils.SPACING["sm"])]
        if r["przelewy"]:
            tresc += [utils.podpis(f"{p['od']} → {p['do']}: {self._kwota(p['kwota'])}") for p in r["przelewy"]]
        else:
            tresc.append(utils.podpis("Bez przelewów — wszyscy byli kwita."))
        kto = f"Zapisał(a): {r['dodane_przez']}" if r["dodane_przez"] else "Zapisane bez podpisu"
        tresc.append(utils.podpis(f"{kto} · {r['notatka']}" if r["notatka"] else kto))
        if not r["liczy_sie"]:
            tresc.append(utils.podpis(
                "Zapisane równolegle z innym rozliczeniem (dwa telefony naraz) — liczy się tylko "
                "pierwsze, to można usunąć.", italic=True))

        wiersz = [ft.Column(tresc, spacing=2, expand=True)]
        if r["do_cofniecia"] and self.moge_rozliczac and utils.wolno_zmieniac_rekord(
                self.state.auto_id, "rozliczenia", autor=r["dodane_przez"]):
            wiersz.append(ft.IconButton(
                ft.Icons.UNDO if r["liczy_sie"] else ft.Icons.DELETE_OUTLINE,
                tooltip="Cofnij rozliczenie" if r["liczy_sie"] else "Usuń rozliczenie",
                on_click=lambda e, rid=r["id"], liczy=r["liczy_sie"]: self._cofnij(rid, liczy),
            ))

        return ft.Container(
            padding=utils.SPACING["md"],
            **utils.powierzchnia(self._page, "karta"),
            content=ft.Row(wiersz, spacing=utils.SPACING["sm"],
                           vertical_alignment=ft.CrossAxisAlignment.START),
        )

    def _cofnij(self, rozliczenie_id, liczy_sie=True):
        page = self._page

        def wykonaj():
            wynik = db.cofnij_rozliczenie(self.state.auto_id, rozliczenie_id)
            utils.przejdz(page, "/podzial")
            utils.pokaz_komunikat_cofnij(
                page, "Cofnięto rozliczenie — saldo wróciło." if liczy_sie else "Usunięto rozliczenie.",
                wynik,
                wiadomosc_bledu="Nie cofnięto: doszło nowsze rozliczenie albo przy tej roli nie możesz go zmienić.",
            )

        if liczy_sie:
            utils.potwierdz(page, "Cofnąć rozliczenie?",
                            "Saldo wróci do stanu sprzed tego rozliczenia — tak, jakby go nie było.",
                            wykonaj, tekst_potwierdzenia="Cofnij")
        else:
            utils.potwierdz(page, "Usunąć rozliczenie?",
                            "To rozliczenie i tak się nie liczy — saldo się nie zmieni.", wykonaj)

    # ------------------------------------------------------------- nota

    def _nota(self):
        return ft.Container(
            padding=utils.SPACING["md"],
            **utils.powierzchnia(self._page, "blok"),
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.INFO_OUTLINE, size=15, color=ft.Colors.ON_SURFACE_VARIANT),
                    utils.podpis("Jak liczone jest saldo"),
                ], spacing=6),
                ft.Text(
                    "Saldo liczy podpisane wydatki: tankowania, wpisy serwisowe, wizyty i inne koszty. "
                    "Każdy okres między rozliczeniami dzieli się po równo między osoby, które wtedy "
                    "dzieliły auto — także te, które nic nie zapłaciły. „Rozliczone” zeruje saldo "
                    "z wybraną datą; wpis sprzed niej dopisany, poprawiony albo usunięty później nie "
                    "przepada, tylko trafia do bieżącego salda jako korekta. Wpisy bez podpisu (sprzed "
                    "ustawienia imienia) nie wchodzą do salda. Kilometry w zestawieniu miesięcznym to "
                    "przybliżenie na podstawie tankowań, a nie pomiar, kto siedział za kierownicą.",
                    size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
                ),
            ], spacing=4),
        )
