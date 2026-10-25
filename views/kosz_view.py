import flet as ft
import db
import utils


ETYKIETY_RETENCJI = {
    7: "7 dni",
    30: "30 dni",
    90: "90 dni",
    0: "bez limitu",
}

ZAKLADKA_WPISY, ZAKLADKA_POJAZDY = 0, 1


def _formatuj_rozmiar(bajty):
    """Rozmiar zdjęć zalegających w koszu — po to, żeby było widać, kiedy kosz
    zaczyna realnie zajmować miejsce na dysku.

    Sam skład rozmiaru robi `db.formatuj_rozmiar`; tutaj zostaje decyzja, że
    ZERO bajtów to nie „0 B", tylko brak zdania do pokazania."""
    bajty = int(bajty or 0)
    return db.formatuj_rozmiar(bajty) if bajty > 0 else None


# Wpis w koszu: ikona i nazwa w trzech formach (1 / 2–4 / 5+); opis buduje _opis_wpisu
# z migawki, bo samego wpisu w bazie już nie ma.
RODZAJE_WPISOW = {
    "tankowania": (ft.Icons.LOCAL_GAS_STATION, ("tankowanie", "tankowania", "tankowań")),
    "inne_koszty": (ft.Icons.RECEIPT_LONG, ("inny koszt", "inne koszty", "innych kosztów")),
    "historia": (ft.Icons.BUILD, ("wpis serwisowy", "wpisy serwisowe", "wpisów serwisowych")),
    "wizyty": (ft.Icons.HOME_REPAIR_SERVICE, ("wizyta", "wizyty", "wizyt")),
    "zadania": (ft.Icons.SETTINGS, ("podzespół", "podzespoły", "podzespołów")),
    "odczyty_przebiegu": (ft.Icons.SPEED, ("odczyt licznika", "odczyty licznika", "odczytów licznika")),
    "przejazdy": (ft.Icons.ALT_ROUTE, ("przejazd", "przejazdy", "przejazdów")),
    "dolewki": (ft.Icons.WATER_DROP, ("dolewka", "dolewki", "dolewek")),
    "dokumenty_pojazdu": (ft.Icons.DESCRIPTION, ("dokument", "dokumenty", "dokumentów")),
    "zdjecia_karoserii": (ft.Icons.CAMERA_ALT, ("zdjęcie karoserii", "zdjęcia karoserii", "zdjęć karoserii")),
    "do_zrobienia": (ft.Icons.CHECKLIST, ("pozycja do zrobienia", "pozycje do zrobienia", "pozycji do zrobienia")),
    "zestawy_opon": (ft.Icons.TIRE_REPAIR, ("komplet opon", "komplety opon", "kompletów opon")),
    "magazyn_czesci": (ft.Icons.INVENTORY_2, ("część z magazynu", "części z magazynu", "części z magazynu")),
    "szkice_wpisow": (ft.Icons.RECEIPT, ("szkic paragonu", "szkice paragonów", "szkiców paragonów")),
    "warsztaty": (ft.Icons.CAR_REPAIR, ("warsztat", "warsztaty", "warsztatów")),
    "ceny_czesci": (ft.Icons.SELL, ("cena części", "ceny części", "cen części")),
    "szablony_wpisow": (ft.Icons.BOOKMARK, ("szablon wpisu", "szablony wpisów", "szablonów wpisów")),
    # Martwe pliki usunięte ze Zdrowia danych (N-08) — sam wpis pliku, bez pliku na dysku.
    "zalaczniki": (ft.Icons.BROKEN_IMAGE, ("plik wpisu", "pliki wpisów", "plików wpisów")),
}
RODZAJ_DOMYSLNY = (ft.Icons.DELETE_OUTLINE, ("wpis", "wpisy", "wpisów"))

# Kwota sumowana przy kilku wpisach usuniętych naraz.
POLE_KWOTY = {"tankowania": "kwota", "inne_koszty": "kwota", "historia": "cena", "wizyty": "koszt_calkowity"}


def _kwota(wartosc):
    return f"{utils.formatuj_liczba(wartosc)} {utils.symbol_waluty()}" if wartosc else None


def _opis_wpisu(pozycja, j):
    """(ikona, tytuł, szczegóły) pozycji kosza wpisów — z usuniętych wierszy migawki."""
    ikona, formy = RODZAJE_WPISOW.get(pozycja["tabela"], RODZAJ_DOMYSLNY)
    wiersze = pozycja["wiersze"] or [{}]
    if pozycja["liczba"] > 1:
        daty = [w.get("data") for w in sorted(wiersze, key=lambda w: str(w.get("data_iso") or "")) if w.get("data")]
        zakres = f"{daty[0]} – {daty[-1]}" if len(set(daty)) > 1 else (daty[0] if daty else None)
        pole = POLE_KWOTY.get(pozycja["tabela"])
        suma = sum(float(w.get(pole) or 0) for w in wiersze) if pole else 0
        return ikona, db.liczba_z_odmiana(pozycja["liczba"], *formy), [zakres, _kwota(suma)]

    w, tabela = wiersze[0], pozycja["tabela"]
    data = w.get("data")
    if tabela == "tankowania":
        return ikona, " · ".join(filter(None, ["Tankowanie", w.get("stacja")])), [data, _kwota(w.get("kwota"))]
    if tabela == "inne_koszty":
        return ikona, w.get("nazwa") or w.get("kategoria") or "Inny koszt", [data, _kwota(w.get("kwota"))]
    if tabela == "historia":
        return ikona, pozycja["opis"] or "Wpis serwisowy", [data, _kwota(w.get("cena")), w.get("wykonawca")]
    if tabela == "wizyty":
        pozycje = pozycja["zalezne"].get("historia")
        return ikona, " · ".join(filter(None, ["Wizyta", w.get("wykonawca")])), [
            data, _kwota(w.get("koszt_calkowity")),
            db.liczba_z_odmiana(pozycje, "pozycja", "pozycje", "pozycji") if pozycje else None]
    if tabela == "zadania":
        wpisy = pozycja["zalezne"].get("historia")
        return ikona, w.get("nazwa") or "Podzespół", [
            "Podzespół", f"z historią: {db.liczba_z_odmiana(wpisy, 'wpis', 'wpisy', 'wpisów')}" if wpisy else None]
    if tabela == "odczyty_przebiegu":
        return ikona, "Odczyt licznika", [data, utils.formatuj_dystans(w.get("przebieg"), 0, j)]
    if tabela == "przejazdy":
        trasa = f"{w['skad']} → {w['dokad']}" if w.get("skad") and w.get("dokad") else None
        return ikona, trasa or w.get("cel") or "Przejazd", [data, utils.formatuj_dystans(w.get("km"), 0, j)]
    if tabela == "dolewki":
        plyn = (db.RODZAJE_PLYNOW.get(w.get("plyn")) or {}).get("nazwa")
        return ikona, " · ".join(filter(None, ["Dolewka", plyn])), [data, db.tekst_litrow(w.get("ilosc"))]
    if tabela == "dokumenty_pojazdu":
        return ikona, w.get("nazwa") or db.etykieta_dokumentu(w.get("rodzaj")), [w.get("numer")]
    if tabela == "zdjecia_karoserii":
        return ikona, " · ".join(filter(None, ["Zdjęcie karoserii", w.get("strefa")])), [data, w.get("opis")]
    if tabela == "do_zrobienia":
        if w.get("wykonane"):
            return ikona, w.get("tytul") or "Do zrobienia", ["Wykonane", w.get("data_wykonania")]
        return ikona, w.get("tytul") or "Do zrobienia", ["Do zrobienia", w.get("priorytet")]
    if tabela == "zestawy_opon":
        return ikona, " · ".join(filter(None, ["Opony", w.get("sezon")])), [w.get("rozmiar")]
    if tabela == "magazyn_czesci":
        ilosc = f"{utils.tekst_ilosci(w.get('ilosc'))} {w.get('jednostka') or ''}".strip()
        return ikona, w.get("nazwa") or "Część", ["Magazyn", ilosc]
    if tabela == "szkice_wpisow":
        return ikona, "Paragon do wpisania", [" ".join(filter(None, [data, w.get("godzina")])), w.get("opis")]
    if tabela == "warsztaty":
        return ikona, w.get("nazwa") or "Warsztat", ["Warsztat", w.get("telefon")]
    if tabela == "ceny_czesci":
        return ikona, w.get("nazwa") or "Cena części", ["Cena części", data]
    if tabela == "szablony_wpisow":
        rodzaj = "Szablon tankowania" if w.get("rodzaj") == db.SZABLON_TANKOWANIE else "Szablon kosztu"
        return ikona, w.get("nazwa") or "Szablon wpisu", [rodzaj]
    if tabela == "zalaczniki":
        nazwa = str(w.get("sciezka") or "").replace("\\", "/").rsplit("/", 1)[-1]
        return ikona, "Plik wpisu", [nazwa or None, db.ETYKIETY_WPISOW.get(w.get("tabela"))]
    return ikona, formy[0].capitalize(), [data]


def _odznaka_retencji(dni):
    """„Zniknie za N dni” — ostatnie 3 dni na czerwono, żeby „zniknie jutro” nie przeszło
    niezauważone. None przy retencji bez limitu."""
    if dni is None:
        return None
    if dni <= 0:
        tekst, kolor = "Zniknie przy najbliższym starcie", utils.KOLOR_STATUS["critical"]
    elif dni == 1:
        tekst, kolor = "Zniknie jutro", utils.KOLOR_STATUS["critical"]
    else:
        kolor = utils.KOLOR_STATUS["critical"] if dni <= 3 else utils.KOLOR_STATUS["warning"]
        tekst = f"Zniknie za {dni} dni"
    return ft.Container(
        padding=ft.Padding(8, 3, 8, 3),
        border_radius=utils.RADIUS["pill"],
        bgcolor=ft.Colors.with_opacity(0.15, kolor),
        content=ft.Text(tekst, size=10, weight="bold", color=kolor),
    )


class KoszView(ft.View):
    """Usunięte wpisy i pojazdy, jeszcze nie skasowane (Z-01). Do trwałego usunięcia albo
    końca retencji wpis wraca ze zdjęciami i plikami, a pojazd z całą historią."""

    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state
        self.wpisy = db.pobierz_kosz_wpisow()
        self.pojazdy = db.pobierz_kosz()
        if getattr(state, "kosz_zakladka", None) is None:
            state.kosz_zakladka = ZAKLADKA_POJAZDY if self.pojazdy and not self.wpisy else ZAKLADKA_WPISY
        self.zakladka = state.kosz_zakladka

        appbar = utils.zbuduj_pasek_z_powrotem(
            page, "Kosz", "/", ikona=ft.Icons.DELETE_SWEEP,
            akcje_dodatkowe=[
                ft.IconButton(
                    icon=ft.Icons.DELETE_FOREVER,
                    icon_color=utils.KOLOR_STATUS["destructive"],
                    tooltip="Opróżnij kosz",
                    on_click=self._oproznij,
                )
            ]
        )

        super().__init__(
            route="/kosz",
            padding=15,
            spacing=15,
            appbar=appbar,
            controls=self._zbuduj(),
            scroll=ft.ScrollMode.AUTO,
        )

    # ------------------------------------------------------------------ widok
    def _zbuduj(self):
        dni = db.pobierz_dni_kosza()
        elementy = [utils.segmented_control(self._page, [
            (f"Wpisy ({len(self.wpisy)})", ZAKLADKA_WPISY, ft.Icons.RECEIPT_LONG),
            (f"Pojazdy ({len(self.pojazdy)})", ZAKLADKA_POJAZDY, ft.Icons.DIRECTIONS_CAR),
        ], self.zakladka, self._zmien_zakladke)]

        if self.zakladka == ZAKLADKA_WPISY:
            elementy.append(self._karta_informacyjna(dni, self.wpisy, "Usunięte wpisy",
                                                     "razem ze zdjęciami i plikami"))
            if not self.wpisy:
                elementy.append(self._pusto("Brak usuniętych wpisów",
                                            "Usunięte tankowania, koszty, wpisy serwisowe, odczyty i zdjęcia "
                                            "trafiają tutaj razem z plikami — i stąd wracają."))
            else:
                j = utils.jednostka_dystansu()
                z_autem = len({p["auto_id"] for p in self.wpisy} | {self.state.auto_id}) > 1
                lista = utils.lista_kart()
                lista.controls = [self._karta_wpisu(p, j, z_autem) for p in self.wpisy]
                elementy.append(lista)
        else:
            elementy.append(self._karta_informacyjna(dni, self.pojazdy, "Usunięte pojazdy",
                                                     "razem ze zdjęciami"))
            if not self.pojazdy:
                elementy.append(self._pusto("Brak usuniętych pojazdów",
                                            "Usunięte pojazdy trafiają tutaj razem z całą historią i zdjęciami."))
            else:
                elementy.extend(self._karta_pojazdu(p) for p in self.pojazdy)

        elementy.append(utils.dol_bezpieczny(10))
        return elementy

    def _zmien_zakladke(self, indeks):
        self.state.kosz_zakladka = indeks
        utils.przejdz(self._page, "/kosz")

    def _pusto(self, tytul, opis):
        return ft.Container(
            padding=30,
            alignment=ft.Alignment.CENTER,
            content=ft.Column([
                utils.rysunek_pustego_stanu(ft.Icons.DELETE_OUTLINE),
                ft.Text(tytul, weight="bold", size=15),
                ft.Text(opis, size=12, color=ft.Colors.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER),
            ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
        )

    def _karta_informacyjna(self, dni, pozycje, kto, z_czym):
        if dni:
            tresc = (
                f"{kto} czekają tutaj {ETYKIETY_RETENCJI.get(dni, f'{dni} dni')}, "
                f"a potem znikają {z_czym}. Czas zmienisz w Ustawieniach."
            )
        else:
            tresc = (
                f"Retencja jest wyłączona — {kto.lower()} leżą w koszu bez limitu czasu i znikną "
                "dopiero, gdy sam je stąd usuniesz. Czas zmienisz w Ustawieniach."
            )

        laczny_rozmiar = _formatuj_rozmiar(sum(p["rozmiar_plikow"] for p in pozycje))
        if laczny_rozmiar:
            tresc += f" Zdjęcia i pliki w koszu zajmują {laczny_rozmiar}."

        return ft.Container(
            padding=15,
            border_radius=utils.RADIUS["md"],
            bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.PRIMARY),
            content=ft.Row([
                ft.Icon(ft.Icons.INFO_OUTLINE, color=ft.Colors.PRIMARY, size=18),
                ft.Text(tresc, size=12, color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
            ], spacing=8)
        )

    def _karta_wpisu(self, pozycja, j, z_autem):
        ikona, tytul, szczegoly = _opis_wpisu(pozycja, j)
        usunieto = [f"Usunięto {pozycja['data_tekst']}"]
        if z_autem and pozycja["nazwa_auta"]:
            usunieto.append(pozycja["nazwa_auta"])
        if pozycja["liczba_plikow"]:
            usunieto.append(db.liczba_z_odmiana(pozycja["liczba_plikow"], "plik", "pliki", "plików"))

        dolny = [utils.podpis("  •  ".join(usunieto), max_lines=2)]
        odznaka = _odznaka_retencji(pozycja["dni_do_usuniecia"])
        if odznaka:
            dolny.append(odznaka)

        tresc = ft.Column([
            ft.Row([
                ft.Container(
                    content=ft.Icon(ikona, size=20, color=ft.Colors.ON_SURFACE_VARIANT),
                    bgcolor=utils.tlo_odznaki(self._page), border_radius=utils.RADIUS["sm"], padding=8,
                ),
                ft.Column([
                    utils.wartosc(tytul, size=utils.FS["body_strong"], max_lines=2,
                                  overflow=ft.TextOverflow.ELLIPSIS),
                    utils.podpis("  •  ".join(s for s in szczegoly if s) or "—", max_lines=2),
                ], spacing=2, expand=True),
                ft.IconButton(icon=ft.Icons.RESTORE_FROM_TRASH, tooltip="Przywróć", icon_color=ft.Colors.PRIMARY,
                              on_click=lambda e, p=pozycja: self._przywroc_wpis(p)),
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row(dolny, spacing=8, wrap=True),
        ], spacing=utils.SPACING["sm"])
        karta, kontener = utils.karta_listy(tresc, page=self._page)
        kontener.on_click = utils.z_efektem_nacisniecia(kontener, lambda e, p=pozycja: self._menu_wpisu(p, tytul))
        return karta

    def _karta_pojazdu(self, pozycja):
        plaszczyzna = utils.powierzchnia(self._page, "karta", cien="md")

        opis = [f"Usunięto {pozycja['data_tekst']}"]
        if pozycja["liczba_wpisow"]:
            opis.append(db.liczba_z_odmiana(pozycja['liczba_wpisow'], 'wpis', 'wpisy', 'wpisów'))
        rozmiar = _formatuj_rozmiar(pozycja["rozmiar_plikow"])
        if rozmiar:
            opis.append(rozmiar)
        odznaka = _odznaka_retencji(pozycja["dni_do_usuniecia"])

        naglowek = ft.Row([
            ft.Container(
                content=ft.Icon(ft.Icons.DIRECTIONS_CAR, size=20, color=ft.Colors.ON_SURFACE_VARIANT),
                bgcolor=utils.tlo_odznaki(self._page),
                border_radius=utils.RADIUS["sm"],
                padding=8,
            ),
            ft.Column([
                ft.Text(pozycja["nazwa"], weight="bold", size=15, no_wrap=True,
                        overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text("  •  ".join(opis), size=11, color=ft.Colors.ON_SURFACE_VARIANT),
            ], spacing=2, expand=True),
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        przyciski = ft.Row([
            ft.Button(
                "Przywróć",
                icon=ft.Icons.RESTORE_FROM_TRASH,
                bgcolor=ft.Colors.PRIMARY,
                color=ft.Colors.ON_PRIMARY,
                on_click=lambda e, p=pozycja: self._przywroc(p),
            ),
            ft.TextButton(
                "Usuń trwale",
                icon=ft.Icons.DELETE_FOREVER,
                style=ft.ButtonStyle(color=utils.KOLOR_STATUS["destructive"]),
                on_click=lambda e, p=pozycja: self._usun_trwale(p),
            ),
        ], spacing=8, alignment=ft.MainAxisAlignment.END, wrap=True)

        zawartosc = [naglowek]
        if odznaka:
            zawartosc.append(ft.Row([odznaka]))
        zawartosc.append(przyciski)

        return ft.Container(
            padding=15,
            **plaszczyzna,
            content=ft.Column(zawartosc, spacing=10),
        )

    # ------------------------------------------------------------------ akcje wpisów
    def _menu_wpisu(self, pozycja, tytul):
        utils.pokaz_menu_kontekstowe(self._page, tytul, [
            {"ikona": ft.Icons.RESTORE_FROM_TRASH, "tekst": "Przywróć", "kolor": ft.Colors.PRIMARY,
             "akcja": lambda: self._przywroc_wpis(pozycja)},
            {"ikona": ft.Icons.DELETE_FOREVER, "tekst": "Usuń trwale", "kolor": utils.KOLOR_STATUS["destructive"],
             "akcja": lambda: self._usun_wpis_trwale(pozycja, tytul)},
        ])

    def _przywroc_wpis(self, pozycja):
        wynik = db.przywroc_wpis_z_kosza(pozycja["id"])
        if wynik is None:
            utils.przejdz(self._page, "/kosz")
            return
        if not wynik.get("ok"):
            utils.pokaz_komunikat(self._page, wynik.get("powod") or "Nie udało się przywrócić wpisu.",
                                  utils.KOLOR_STATUS["error"])
            return
        _, tytul, _ = _opis_wpisu(pozycja, utils.jednostka_dystansu())
        tekst = f"Przywrócono: {tytul}."
        if pozycja["auto_id"] != self.state.auto_id and pozycja["nazwa_auta"]:
            tekst += f" Pojazd: „{pozycja['nazwa_auta']}”."
        utils.przejdz(self._page, "/kosz")
        utils.pokaz_komunikat(self._page, tekst, utils.KOLOR_STATUS["ok"])

    def _usun_wpis_trwale(self, pozycja, tytul):
        def wykonaj():
            db.usun_wpis_z_kosza_trwale(pozycja["id"])
            utils.przejdz(self._page, "/kosz")
            utils.pokaz_komunikat(self._page, f"„{tytul}” usunięto bezpowrotnie.", utils.KOLOR_STATUS["destructive"])

        utils.potwierdz(
            self._page, "Usunąć bezpowrotnie?",
            f"„{tytul}” zniknie na dobre razem ze zdjęciami i plikami. Tego już nie da się cofnąć.",
            wykonaj, tekst_potwierdzenia="Usuń trwale",
        )

    # ------------------------------------------------------------------ akcje pojazdów
    def _przywroc(self, pozycja):
        nowe_id = db.przywroc_auto_z_kosza(pozycja["id"])
        if not nowe_id:
            utils.pokaz_komunikat(self._page, "Nie udało się przywrócić pojazdu.", utils.KOLOR_STATUS["error"])
            utils.przejdz(self._page, "/kosz")
            return

        # Przywrócone auto od razu staje się aktywne — użytkownik wraca po nie,
        # więc oczekuje, że po przywróceniu na nie patrzy.
        self.state.auto_id = nowe_id
        db.zainicjuj_domyslne_auto(self.state)
        utils.przejdz(self._page, "/")
        utils.pokaz_komunikat(
            self._page,
            f"Przywrócono pojazd „{self.state.auto_nazwa}” wraz z historią.",
            utils.KOLOR_STATUS["ok"],
        )

    def _usun_trwale(self, pozycja):
        def wykonaj():
            db.usun_z_kosza_trwale(pozycja["id"])
            utils.przejdz(self._page, "/kosz")
            utils.pokaz_komunikat(
                self._page, f"Pojazd „{pozycja['nazwa']}” usunięty bezpowrotnie.", utils.KOLOR_STATUS["destructive"]
            )

        utils.potwierdz(
            self._page,
            "Usunąć bezpowrotnie?",
            f"„{pozycja['nazwa']}” zniknie na dobre razem z historią i zdjęciami. "
            "Tego już nie da się cofnąć.",
            wykonaj,
            tekst_potwierdzenia="Usuń trwale",
        )

    def _oproznij(self, e):
        if self.zakladka == ZAKLADKA_WPISY:
            ile = db.liczba_wpisow_w_koszu()
            co, z_czym, oproznij = "Usunięte wpisy", "ze zdjęciami i plikami", db.oproznij_kosz_wpisow
        else:
            ile = len(db.pobierz_kosz())
            co, z_czym, oproznij = "Pojazdy w koszu", "z historią i zdjęciami", db.oproznij_kosz
        if not ile:
            utils.pokaz_komunikat(self._page, "Ta część kosza jest już pusta.", ft.Colors.ON_SURFACE_VARIANT)
            return

        def wykonaj():
            usuniete = oproznij()
            utils.przejdz(self._page, "/kosz")
            utils.pokaz_komunikat(
                self._page,
                f"Opróżniono kosz — usunięto {db.liczba_z_odmiana(usuniete, 'pozycję', 'pozycje', 'pozycji')}.",
                utils.KOLOR_STATUS["destructive"],
            )

        utils.potwierdz(
            self._page,
            "Opróżnić kosz?",
            f"{co} ({ile}) znikną na dobre razem {z_czym}. Tego już nie da się cofnąć.",
            wykonaj,
            tekst_potwierdzenia="Opróżnij",
        )
