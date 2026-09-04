import flet as ft
import db
import sync
import utils


class BudzetView(ft.View):
    """Limity wydatków pojazdu. Jeden ekran łączy dwie rzeczy, które zwykle są
    rozdzielone: USTAWIENIE limitu i JEGO STAN. Bez tego drugiego ustawianie
    kwoty jest strzelaniem na oślep — dopiero pasek obok pola mówi, czy 800 zł
    miesięcznie to dużo, czy o połowę za mało."""

    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state

        appbar = utils.zbuduj_pasek_z_powrotem(page, "Budżet pojazdu", "/", ikona=ft.Icons.SAVINGS)

        if not self.state.auto_id:
            super().__init__(
                route="/budzet", padding=15, spacing=15, appbar=appbar,
                controls=[utils.ekran_braku_danych(
                    ikona=ft.Icons.DIRECTIONS_CAR,
                    tytul="Brak wybranego pojazdu",
                    opis="Wybierz pojazd, aby ustawić dla niego limity wydatków.",
                    tekst_przycisku="Wróć na start",
                    on_click=lambda e: utils.przejdz(self._page, "/")
                )]
            )
            return

        wspolny_id, _ = sync.czy_udostepniony(self.state.auto_id)
        ustawione = {(b["kategoria"], b["okres"]): b["kwota"] for b in db.pobierz_budzety(self.state.auto_id)}
        stany = {(s["kategoria"], s["okres"]): s for s in db.stan_budzetow(self.state.auto_id)}

        self.pola = {}
        elementy = [self._naglowek(wspolny_id)]

        for okres, etykieta_okresu in db.OKRESY_BUDZETU.items():
            wiersze = []
            for kategoria, etykieta_kat in db.KATEGORIE_BUDZETU.items():
                kwota = ustawione.get((kategoria, okres))
                pole = ft.TextField(
                    label=f"{etykieta_kat} ({utils.symbol_waluty()})",
                    value=utils.formatuj_liczba(kwota, 0) if kwota else "",
                    hint_text="puste = bez limitu",
                    keyboard_type=ft.KeyboardType.NUMBER,
                    **utils.styl_pola(page=page)
                )
                self.pola[(kategoria, okres)] = pole
                wiersze.append(pole)

                stan = stany.get((kategoria, okres))
                if stan:
                    wiersze.append(ft.Container(
                        padding=ft.Padding(2, 0, 2, utils.SPACING["sm"]),
                        content=utils.pasek_budzetu(self._page, stan),
                    ))

            elementy.append(utils.karta_formularza(
                wiersze,
                f"Limit {etykieta_okresu.lower()}",
                ft.Icons.CALENDAR_MONTH if okres == "miesiac" else ft.Icons.CALENDAR_TODAY,
                domyslnie_otwarte=(okres == "miesiac" or any(k[1] == okres for k in ustawione)),
                page=page,
            ))

        elementy.append(self._nota_o_liczeniu())
        elementy.append(utils.przyciski_akcji(page, "Zapisz limity", self.zapisz, "/"))
        elementy.append(utils.dol_bezpieczny(10))

        super().__init__(
            route="/budzet", padding=15, spacing=15, appbar=appbar,
            controls=elementy, scroll=ft.ScrollMode.AUTO,
        )

    def _naglowek(self, wspolny_id):
        tekst = (
            "Limit pilnuje wydatków tego pojazdu. „Wszystko razem” liczy paliwo, "
            "serwis i inne koszty łącznie — możesz ustawić sam limit zbiorczy, same "
            "szczegółowe albo jedno i drugie naraz."
        )
        if wspolny_id:
            tekst += " Pojazd jest współdzielony, więc limit obowiązuje obie osoby."
        return ft.Container(
            padding=utils.SPACING["md"], border_radius=utils.RADIUS["lg"],
            bgcolor=ft.Colors.with_opacity(0.07, ft.Colors.PRIMARY),
            content=ft.Row([
                ft.Icon(ft.Icons.SAVINGS, size=20, color=ft.Colors.PRIMARY),
                ft.Text(tekst, size=utils.FS["body"], color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
            ], spacing=utils.SPACING["sm"]),
        )

    def _nota_o_liczeniu(self):
        return ft.Container(
            padding=utils.SPACING["md"], border_radius=utils.RADIUS["md"],
            bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.ON_SURFACE),
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.INFO_OUTLINE, size=15, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Text("Jak liczony jest stan", size=utils.FS["label"], weight="bold",
                            color=ft.Colors.ON_SURFACE_VARIANT),
                ], spacing=6),
                ft.Text(
                    "Wydatki sumują się od pierwszego dnia okresu do dzisiaj. Wizyta zbiorcza "
                    "wchodzi jako całość, a jej pozycje nie liczą się drugi raz. Ostrzeżenie "
                    "zapala się przy 80% limitu ALBO wtedy, gdy dotychczasowe tempo wskazuje "
                    "na przekroczenie przed końcem okresu — czarna kreska na pasku pokazuje, "
                    "ile okresu już minęło.",
                    size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT,
                ),
            ], spacing=4),
        )

    def zapisz(self, e):
        # Najpierw sprawdzamy WSZYSTKIE pola, a dopiero potem zapisujemy. Zapis
        # w trakcie sprawdzania zostawiałby przy literówce w jednym polu połowę
        # limitów zmienionych, a połowę nie — i nie byłoby po czym poznać, którą.
        do_zapisu = []
        bledy = []
        for (kategoria, okres), pole in self.pola.items():
            pole.error_text = None
            tekst = (pole.value or "").strip()
            if not tekst:
                do_zapisu.append((kategoria, okres, 0.0))
                continue
            kwota = utils.parsuj_float(tekst, None)
            if kwota is None or kwota < 0:
                bledy.append((pole, "Podaj kwotę lub zostaw puste"))
                continue
            do_zapisu.append((kategoria, okres, kwota))

        if bledy:
            return utils.pokaz_bledy_formularza(self._page, bledy)

        zmienione = 0
        for kategoria, okres, kwota in do_zapisu:
            db.zapisz_budzet(self.state.auto_id, kategoria, okres, kwota)
            zmienione += 1

        # Limit jest częścią danych pojazdu, więc przy współdzieleniu leci do
        # partnera tą samą drogą co reszta — inaczej każdy patrzyłby na swój.
        utils.wypchnij_w_tle(self._page, self.state.auto_id, "budżet")
        utils.przejdz(self._page, "/budzet")
        utils.pokaz_komunikat(self._page, "Zapisano limity." if zmienione else "Brak zmian.")
