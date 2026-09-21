import flet as ft
import db
import utils

IKONY_WYSZUKIWANIA = {
    "Tankowanie": (ft.Icons.LOCAL_GAS_STATION, ft.Colors.BLUE_700),
    "Serwis": (ft.Icons.BUILD, ft.Colors.ORANGE_700),
    "Podzespół": (ft.Icons.BUILD_CIRCLE, ft.Colors.DEEP_ORANGE_700),
    "Wizyta zbiorcza": (ft.Icons.HOME_REPAIR_SERVICE, ft.Colors.RED_700),
    "Inny koszt": (ft.Icons.RECEIPT_LONG, ft.Colors.GREEN_700),
    "Do zrobienia": (ft.Icons.CHECKLIST_RTL, ft.Colors.PURPLE_700),
    "Magazyn": (ft.Icons.INVENTORY_2, ft.Colors.TEAL_700),
    "Opony": (ft.Icons.TIRE_REPAIR, ft.Colors.INDIGO_700),
    "Warsztat": (ft.Icons.HANDYMAN, ft.Colors.BROWN_700),
    "Wydatek cykliczny": (ft.Icons.AUTORENEW, ft.Colors.CYAN_700),
    "Zapisana trasa": (ft.Icons.ROUTE, ft.Colors.ORANGE_700),
    "Checklista": (ft.Icons.FACT_CHECK, ft.Colors.LIGHT_GREEN_700),
    "Odczyt licznika": (ft.Icons.SPEED, ft.Colors.BLUE_GREY_700),
}


class SzukajView(ft.View):
    PODPOWIEDZ_STARTOWA = (
        "Wpisz min. 2 znaki, aby przeszukać tankowania, serwis, wizyty, "
        "inne koszty, warsztaty, wydatki cykliczne, zapisane trasy, checklisty, "
        "notatki wpisów i listę Do zrobienia bieżącego pojazdu. Zamiast tekstu można "
        "wpisać okres („marzec 2026”, „ostatni tydzień”), pole („stacja:orlen”, "
        "„tag:ubezpieczenie”, „kategoria:opłaty”) albo kwotę („>1000”) — i łączyć to ze sobą. "
        "Szukanie obejmuje też EKRANY aplikacji — wpisz „rok”, „budżet” albo „przebieg”, "
        "żeby wejść prosto tam, gdzie trzeba."
    )

    def __init__(self, page: ft.Page, state):
        self._page = page
        self.state = state

        appbar = utils.zbuduj_pasek_z_powrotem(page, "Szukaj we wszystkim", "/", ikona=ft.Icons.SEARCH)

        if not self.state.auto_id:
            super().__init__(
                route="/szukaj", padding=15, spacing=15, appbar=appbar,
                controls=[utils.ekran_braku_danych(
                    ikona=ft.Icons.DIRECTIONS_CAR,
                    tytul="Brak wybranego pojazdu",
                    opis="Wybierz pojazd, aby móc przeszukać jego dane.",
                    tekst_przycisku="Wróć na start",
                    on_click=lambda e: utils.przejdz(self._page, "/")
                )]
            )
            return

        self.pole_wyszukiwarki = ft.TextField(
            hint_text="Szukaj wpisów i ekranów (stacja, część, kwota, „rok w pigułce”)...",
            prefix_icon=ft.Icons.SEARCH,
            autofocus=True,
            on_change=utils.z_opoznieniem(self._page, self._wyszukaj),
            **utils.styl_pola()
        )

        self.tekst_pomocniczy = ft.Text(
            self.PODPOWIEDZ_STARTOWA,
            size=13, color=ft.Colors.ON_SURFACE_VARIANT, text_align=ft.TextAlign.CENTER
        )
        self.kontener_pomocniczy = ft.Container(
            padding=ft.Padding.symmetric(vertical=20),
            content=self.tekst_pomocniczy,
            alignment=ft.Alignment.CENTER,
        )

        # Składnia poleceń jest odkrywalna tylko wtedy, gdy się o niej powie —
        # sam „>1000” ani „stacja:” nikomu nie przyjdzie do głowy w polu opisanym
        # „Szukaj”. Chipy są klikalne, więc wzór nie wymaga przepisywania.
        self.podpowiedz_skladni = ft.Container(
            padding=ft.Padding(12, 10, 12, 10),
            border_radius=utils.RADIUS["sm"],
            bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.PRIMARY),
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.BOLT, size=16, color=ft.Colors.PRIMARY),
                    ft.Text(
                        "Kliknij wzór i dopisz resztę — filtry sumują się ze sobą",
                        size=11, color=ft.Colors.ON_SURFACE_VARIANT, expand=True,
                    ),
                ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                utils.pasek_zawijany(
                    [self._chip_skladni(wzor, opis) for wzor, opis in db.PRZYKLADY_SKLADNI],
                    spacing=6),
            ], spacing=8, tight=True),
        )

        # Pasek pokazywany dopiero wtedy, gdy zapytanie ZOSTAŁO rozpoznane jako
        # filtr — inaczej nie wiadomo, czemu „450” nie znalazło daty z 450, ani
        # czemu „marzec” pominął wpis ze słowem „marzec” w notatce.
        self.pasek_trybu = ft.Container(visible=False)

        # Wyszukiwarka przestała być tylko przeglądarką WPISÓW. Najczęstszym
        # pytaniem w rozrosłej aplikacji nie jest „ile zapłaciłem na Orlenie”,
        # tylko „gdzie to było” — więc to samo pole odpowiada teraz na oba.
        # Ekrany stoją NAD wpisami, bo kto wpisuje „budżet”, chce wejść na ekran
        # budżetu, a nie przeczytać wpis, w którym padło to słowo. Ale „rozrząd”
        # czy „olej” to słowa z danych: przy frazie od DLUGA_FRAZA_OD znaków,
        # która trafiła we wpisy, ekran znaleziony tylko przez słowa pomocnicze
        # schodzi POD wpisy (utils.rozstaw_ekrany). Trafienie w tytuł zostaje u góry.
        self.sekcja_ekranow = ft.Column(spacing=8, visible=False)
        self.sekcja_ekranow_pod = ft.Column(spacing=8, visible=False)

        self.lista_wynikow = ft.ListView(
            spacing=12, padding=0, height=utils.wysokosc_listy(self._page), auto_scroll=False
        )
        utils.pamietaj_pozycje(self._page, self.state, self.lista_wynikow, "lista:wyszukiwarka")

        elementy = [
            self.pole_wyszukiwarki, self.podpowiedz_skladni, self.pasek_trybu,
            self.sekcja_ekranow, self.kontener_pomocniczy, self.lista_wynikow,
            self.sekcja_ekranow_pod,
        ]

        super().__init__(
            route="/szukaj", padding=15, spacing=15, appbar=appbar,
            controls=elementy, scroll=ft.ScrollMode.AUTO
        )

    def _chip_skladni(self, wzor, opis):
        """Klikalny wzór polecenia. Wstawia CAŁY wzór i od razu szuka — po
        „stacja:” nie ma jeszcze czego znaleźć, ale pasek trybu pokazuje, że
        polecenie zostało rozpoznane, i widać, co dopisać."""
        def wstaw(e):
            self.pole_wyszukiwarki.value = wzor
            self._wyszukaj(None)

        return ft.Container(
            padding=ft.Padding(10, 6, 10, 6), border_radius=utils.RADIUS["sm"], ink=True,
            bgcolor=ft.Colors.with_opacity(0.10, ft.Colors.PRIMARY),
            on_click=wstaw,
            content=ft.Row([
                ft.Text(wzor, size=utils.FS["caption"], weight="bold", color=ft.Colors.PRIMARY),
                ft.Text(opis, size=utils.FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT),
            ], spacing=6, tight=True),
        )

    def _wiersz_ekranu(self, ekran):
        kolor = utils.kolor_ekranu(ekran)
        return ft.Container(
            padding=ft.Padding(12, 10, 12, 10), border_radius=utils.RADIUS["md"], ink=True,
            bgcolor=ft.Colors.with_opacity(0.07, kolor),
            on_click=lambda e, ek=ekran: utils.otworz_ekran(
                self._page, self.state, ek, self._akcje_ekranow()),
            content=ft.Row([
                ft.Container(
                    width=32, height=32, border_radius=utils.RADIUS["sm"],
                    alignment=ft.Alignment.CENTER,
                    bgcolor=ft.Colors.with_opacity(0.16, kolor),
                    content=ft.Icon(ekran["ikona"], size=17, color=kolor),
                ),
                ft.Column([
                    ft.Text(ekran["tytul"], size=utils.FS["body"], weight="bold"),
                    ft.Text(ekran.get("opis") or "", size=utils.FS["caption"],
                            color=ft.Colors.ON_SURFACE_VARIANT, max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS),
                ], spacing=1, tight=True, expand=True),
                ft.Icon(ft.Icons.ARROW_FORWARD_IOS, size=13, color=ft.Colors.ON_SURFACE_VARIANT),
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )

    def _akcje_ekranow(self):
        """Wyszukiwarka nie ma dostępu do kopii bazy ani przełącznika motywu (te
        siedzą w module głównym), ale panele czysto interfejsowe — wydatki
        cykliczne, edycja i usunięcie pojazdu — potrafi otworzyć sama. Reszta po
        prostu nie pojawia się w wynikach, zamiast prowadzić donikąd."""
        return utils.akcje_nawigacji(self._page, self.state)

    def _wypelnij_sekcje_ekranow(self, sekcja, ekrany, naglowek):
        sekcja.controls.clear()
        sekcja.visible = bool(ekrany)
        if not ekrany:
            return
        sekcja.controls.append(ft.Row([
            ft.Icon(ft.Icons.APPS, size=16, color=ft.Colors.PRIMARY),
            ft.Text(naglowek, size=utils.FS["label"], weight="bold",
                    color=ft.Colors.PRIMARY, expand=True),
        ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER))
        for ekran in ekrany:
            sekcja.controls.append(self._wiersz_ekranu(ekran))

    def _pokaz_ekrany(self, zapytanie, sa_wpisy):
        """Zwraca liczbę dopasowanych ekranów — wołający używa jej do rozróżnienia
        „nic nie znaleziono” od „znaleziono tylko ekran, ale żadnego wpisu”.
        Puste zapytanie chowa obie sekcje."""
        nad, pod = utils.rozstaw_ekrany(
            zapytanie, sa_wpisy, akcje=self._akcje_ekranow(), ma_pojazd=bool(self.state.auto_id))
        self._wypelnij_sekcje_ekranow(self.sekcja_ekranow, nad, "Ekrany i funkcje")
        # Inny nagłówek niż u góry: przy „opony” obie sekcje stoją naraz, a dwa
        # identyczne napisy na jednym ekranie wyglądają jak zdublowana lista.
        self._wypelnij_sekcje_ekranow(self.sekcja_ekranow_pod, pod, "Powiązane ekrany")
        return len(nad) + len(pod)

    def _karta_wyniku(self, w):
        ikona, kolor = IKONY_WYSZUKIWANIA.get(w["typ"], (ft.Icons.EVENT_NOTE, ft.Colors.ON_SURFACE_VARIANT))

        def po_kliknieciu(e, wynik=w):
            if wynik["trasa"] == "__wydatki_cykliczne__":
                utils.pokaz_panel_wydatkow_cyklicznych(self._page, self.state)
            elif wynik["trasa"] == "__checklisty__":
                # Checklisty mieszkają w podzakładce ekranu „Do zrobienia”,
                # więc samo przejście pod adres wylądowałoby na liście zadań.
                self.state.do_zrobienia_podzakladka = 1
                utils.przejdz(self._page, "/do-zrobienia")
            else:
                utils.przejdz(self._page, wynik["trasa"])

        return ft.Card(
            elevation=1,
            content=ft.Container(
                padding=15, border_radius=10,
                on_click=po_kliknieciu,
                content=ft.Row([
                    ft.Container(
                        width=36, height=36, border_radius=18,
                        bgcolor=ft.Colors.with_opacity(0.15, kolor),
                        alignment=ft.Alignment.CENTER,
                        content=ft.Icon(ikona, size=16, color=kolor)
                    ),
                    ft.Column([
                        ft.Row([
                            ft.Text(w["typ"], size=11, weight="bold", color=kolor),
                            ft.Text(str(w["data"]) if w["data"] else "", size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Text(w["tytul"], size=15, weight="bold"),
                        ft.Text(w["opis"], size=12, color=ft.Colors.ON_SURFACE_VARIANT) if w["opis"] else ft.Container(),
                    ], spacing=3, expand=True),
                ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.START)
            )
        )

    def _wyszukaj(self, e):
        zapytanie = (self.pole_wyszukiwarki.value or "").strip()
        self.lista_wynikow.controls.clear()

        filtr = db.parsuj_zapytanie(zapytanie)
        # Jednoznakowe zapytanie z filtrem („5”, „>9”) ma sens, więc próg 2 znaków
        # obowiązuje tylko zwykły tekst.
        if not filtr and len(zapytanie) < 2:
            self.tekst_pomocniczy.value = self.PODPOWIEDZ_STARTOWA
            self.kontener_pomocniczy.visible = True
            self.pasek_trybu.visible = False
            self.podpowiedz_skladni.visible = True
            self._pokaz_ekrany("", sa_wpisy=False)
            self.update()
            return

        if filtr:
            # Waluta dokleja się tylko przy kwocie — i tylko na końcu, bo opis
            # filtrów trzyma kwotę jako ostatnią właśnie po to.
            opis = f"{filtr['opis']} {utils.symbol_waluty()}" if filtr["kwota"] else filtr["opis"]
            self.pasek_trybu.content = ft.Row([
                ft.Icon(ft.Icons.FILTER_ALT, size=16, color=ft.Colors.PRIMARY),
                ft.Text(f"Szukam: {opis}",
                        size=12, weight="bold", color=ft.Colors.PRIMARY, expand=True),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)
            self.pasek_trybu.padding = ft.Padding(12, 10, 12, 10)
            self.pasek_trybu.border_radius = utils.RADIUS["sm"]
            self.pasek_trybu.bgcolor = ft.Colors.with_opacity(0.12, ft.Colors.PRIMARY)
            self.pasek_trybu.visible = True
            self.podpowiedz_skladni.visible = False
        else:
            self.pasek_trybu.visible = False
            self.podpowiedz_skladni.visible = True

        # Najpierw wpisy: od tego, czy fraza w nie trafiła, zależy, gdzie staną ekrany.
        wyniki = db.globalne_wyszukiwanie(self.state.auto_id, zapytanie)

        # Zapytanie z filtrem („>1000”, „marzec 2026”, „stacja:orlen”) nie jest
        # nazwą ekranu — pokazywanie przy nim listy ekranów byłoby szumem. Sekcje
        # trzeba wtedy jawnie schować: bez tego szybka zamiana „olej” na „450”
        # zostawiała ekrany z poprzedniej frazy.
        ile_ekranow = self._pokaz_ekrany("" if filtr else zapytanie, sa_wpisy=bool(wyniki))

        if not wyniki:
            self.tekst_pomocniczy.value = (
                f"Brak wpisów pasujących do zapytania „{zapytanie}”."
                if filtr else (
                    f"Brak wpisów dla „{zapytanie}” — pasuje za to ekran powyżej."
                    if ile_ekranow else f"Brak wyników dla „{zapytanie}”."
                )
            )
            self.kontener_pomocniczy.visible = True
        else:
            self.kontener_pomocniczy.visible = False
            for w in wyniki:
                self.lista_wynikow.controls.append(self._karta_wyniku(w))

        # Lista wyników rośnie i kurczy się z każdą literą — wysokość musi iść za
        # nią, inaczej trzy trafienia zostawiają pod sobą pół pustego ekranu.
        utils.dopasuj_wysokosc_listy(self.lista_wynikow, self._page, wysokosc_pozycji=104)
        self.update()