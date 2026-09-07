"""Ekran główny aplikacji — pasek zakładek, kokpit i cztery zakładki treści.

Powstał z rozbicia jednego pliku main_view.py. Każda zakładka mieszka w osobnym
module jako miksin; `MainView` poniżej tylko je składa i trzyma wspólny stan.
"""

import asyncio
import db
import flet as ft
import sync
import utils

from .kokpit import MiksinKokpitu
from .naglowek_auta import MiksinNaglowkaAuta
from .zakladka_serwis import MiksinZakladkiSerwis
from .zakladka_tankowania import MiksinZakladkiTankowania
from .zakladka_inne import MiksinZakladkiInne
from .zakladka_statystyki import MiksinZakladkiStatystyki


class MainView(
    MiksinKokpitu,
    MiksinNaglowkaAuta,
    MiksinZakladkiSerwis,
    MiksinZakladkiTankowania,
    MiksinZakladkiInne,
    MiksinZakladkiStatystyki,
    ft.View,
    utils.ZaznaczanieGrupowe,
):
    def __init__(self, page: ft.Page, state, cb_export, cb_import, cb_theme):
        self._page = page
        self.state = state
        self.elementy = []
        self.fab = None

        # Akcje rejestru ekranów (kopia bazy, motyw, usunięcie pojazdu) muszą
        # powstać PRZED paskiem, bo to one decydują, które pozycje szuflady
        # w ogóle się pokażą.
        self.akcje_nawigacji = utils.akcje_nawigacji(page, state, cb_export, cb_import, cb_theme)
        self.liczniki_nawigacji = db.liczniki_nawigacji(state.auto_id) if state.auto_id else {}

        appbar = utils.zbuduj_pasek_glowny(
            page, state, cb_export, cb_import, cb_theme, on_menu=self._otworz_nawigacje
        )
        # --- ZMIENNE DLA GRUPOWEGO USUWANIA ---
        self.tryb_zaznaczania = False
        self.zaznaczone_id = set()
        self.tabela_cel = ""  # zapamięta z jakiej zakładki usuwamy (tankowania, inne_koszty, zadania)
        self.oryginalny_appbar = appbar
        self.karty_ref = {}   # Przechowuje referencje do kontenerów kart, by je podświetlać
        self.uzyj_wirtualizacji = False  # True gdy w tej zakładce renderujemy przewijaną listę kart
        self.kokpit_edycja = False       # True = kafelki kokpitu można przeciągać (patrz _buduj_kokpit)
        self.kokpit_kontener = None      # kontener przełączany między karuzelą a trybem układania
        self._kokpit_budowniczy = {}     # id widżetu -> funkcja budująca kafelek
        self._przelacznik_pojazdow = None  # ustawiane w buduj_naglowek_auta (showroom aut)
        # --------------------------------------
        # --- CZTERY ZAKŁADKI = CZTERY POWODY, DLA KTÓRYCH SIĘ TU WCHODZI ---
        # Wcześniej dwie z czterech („Paliwo” i „Inne”) były tym samym pytaniem
        # — ile to kosztowało — rozbitym na dwie listy, a ekran startowy
        # (widżety kokpitu) nie miał własnego miejsca i doklejał się do Serwisu.
        # Teraz: Kokpit = „co się dzieje z autem”, Serwis = „co trzeba zrobić”,
        # Koszty = „ile to kosztuje”, Analiza = „jak to wygląda w czasie”.
        navbar = ft.SafeArea(
            content=ft.NavigationBar(
                destinations=[
                    ft.NavigationBarDestination(icon=ft.Icons.SPACE_DASHBOARD_OUTLINED, selected_icon=ft.Icons.SPACE_DASHBOARD, label="Kokpit"),
                    ft.NavigationBarDestination(icon=ft.Icons.BUILD_CIRCLE_OUTLINED, selected_icon=ft.Icons.BUILD_CIRCLE, label="Serwis"),
                    ft.NavigationBarDestination(icon=ft.Icons.PAYMENTS_OUTLINED, selected_icon=ft.Icons.PAYMENTS, label="Koszty"),
                    ft.NavigationBarDestination(icon=ft.Icons.INSIGHTS, selected_icon=ft.Icons.INSIGHTS, label="Analiza"),
                ],
                on_change=self.zmien_zakladke,
                selected_index=self.state.zakladka,
            ),
            avoid_intrusions_top=False,
        )

        if not self.state.auto_id:
            self.elementy.append(
                utils.ekran_braku_danych(
                    ikona=ft.Icons.DIRECTIONS_CAR,
                    tytul="Witaj w menedżerze!",
                    opis="Nie masz jeszcze dodanego żadnego pojazdu. Dodaj swój pierwszy pojazd, aby rozpocząć zarządzanie.",
                    tekst_przycisku="Dodaj pojazd",
                    on_click=lambda e: utils.przejdz(self._page, "/auto/nowy")
                )
            )
        else:
            self.buduj_naglowek_auta()
            # Pasek roli tuż pod nagłówkiem pojazdu. Bez niego „dlaczego nie ma
            # plusa” byłoby zagadką — przyciski po prostu znikają, a użytkownik
            # nie wie, że to celowe.
            pasek = utils.pasek_roli(page, self.state.auto_id)
            if getattr(pasek, "content", None) is not None:
                self.elementy.append(pasek)
            if self.state.zakladka == 0: self.buduj_kokpit_ekran()
            elif self.state.zakladka == 1: self.buduj_serwis()
            elif self.state.zakladka == 2: self.buduj_koszty()
            elif self.state.zakladka == 3: self.buduj_statystyki()

        # Szybkie dodawanie znika u kogoś, kto ma pojazd wyłącznie do wglądu.
        # FAB składają zakładki (patrz _buduj_fab_szybkich_akcji), więc gasimy go
        # tutaj — w jednym miejscu, przez które przechodzą wszystkie cztery.
        if self.state.auto_id and not utils.wolno_dodawac(self.state.auto_id):
            self.fab = None

        self.elementy.append(utils.dol_bezpieczny(10))

        # Szuflada powstaje RAZEM z widokiem, a nie dopiero przy kliknięciu
        # hamburgera: kontrolka musi już siedzieć w drzewie, żeby dało się ją
        # wysunąć, a dokładanie jej „w locie” i wołanie show_drawer w tej samej
        # chwili to wyścig, w którym panel czasem się nie pokazuje.
        szuflada = utils.zbuduj_szuflade(
            page, state, self.akcje_nawigacji,
            aktywny_ekran=utils.EKRAN_ZAKLADKI.get(
                (int(state.zakladka or 0), int(getattr(state, "koszty_podzakladka", 0) or 0))
            ),
            on_pojazdy=self._pokaz_wybor_pojazdow if state.auto_id else None,
            widok=self,
        )

        super().__init__(
            route="/",
            padding=15,
            spacing=15,                 # Zastępuje odstępy, które wcześniej robił wrapper
            appbar=appbar,
            navigation_bar=navbar,
            drawer=szuflada,
            controls=self.elementy,     # Przekazujemy elementy bezpośrednio
            scroll=ft.ScrollMode.AUTO,  # Włączamy natywne przewijanie całej strony
            floating_action_button=self.fab
        )

    def zmien_zakladke(self, e):
        self.state.zakladka = int(e.control.selected_index)
        utils.przejdz(self._page, "/")

    async def _otworz_nawigacje(self, e=None):
        """Hamburger w pasku górnym. Szuflada jest już zbudowana i wpięta w widok
        (patrz koniec __init__), więc zostaje samo wysunięcie panelu. Gdyby to
        się nie powiodło, ta sama mapa ekranów leci jako menu od dołu — przycisk
        nawigacji nie ma prawa nie zrobić NICZEGO."""
        try:
            await self.show_drawer()
        except Exception:
            utils.pokaz_nawigacje_awaryjna(self._page, self.state, self.akcje_nawigacji)

    def _pokaz_wybor_pojazdow(self):
        """Nagłówek szuflady prowadzi do tego samego showroomu, co kliknięcie
        nazwy auta na kafelku — jeden pojazd wybiera się w jednym miejscu."""
        if self._przelacznik_pojazdow:
            self._przelacznik_pojazdow(None)
        else:
            utils.przejdz(self._page, "/")

    async def _synchronizuj_teraz(self):
        try:
            wyslano, pobrano = await asyncio.to_thread(sync.synchronizuj_wszystko, self.state.auto_id)
            await asyncio.to_thread(sync.przetworz_kolejke_sync)
            utils.przejdz(self._page, "/")
            konflikty = sync.pobierz_konflikty_ostatniej_synchronizacji()
            odrzucone = sync.pobierz_odrzucone_ostatniej_synchronizacji()
            if konflikty:
                utils.pokaz_komunikat(self._page, utils.podsumowanie_konfliktow(konflikty), ft.Colors.AMBER_700)
                utils.pokaz_dialog_konfliktow(self._page, konflikty, self.state.auto_id)
            elif odrzucone:
                utils.pokaz_komunikat(self._page, utils.podsumowanie_odrzuconych(odrzucone), ft.Colors.ORANGE_700)
            elif db.czy_tylko_podglad(self.state.auto_id):
                utils.pokaz_komunikat(self._page, f"Pobrano {pobrano} zmian. Ten pojazd masz w trybie tylko do odczytu.")
            else:
                utils.pokaz_komunikat(self._page, f"Wysłano {wyslano}, pobrano {pobrano} nowych rekordów.")
        except sync.SynchronizacjaWToku:
            utils.pokaz_komunikat(self._page, "Synchronizacja już trwa — chwilę to potrwa.")
        except Exception as ex:
            db.zakolejkuj_synchronizacje(self.state.auto_id, "reczna", str(ex))
            utils.pokaz_komunikat(
                self._page,
                f"Błąd synchronizacji: {ex}. Zmiany zostały zakolejkowane i spróbujemy ponownie automatycznie.",
                ft.Colors.RED_700
            )

    def _buduj_fab_szybkich_akcji(self):
        akcje = [
            (ft.Icons.LOCAL_GAS_STATION, "Tankowanie", lambda e: utils.przejdz(self._page, "/tankowanie/nowe")),
            (ft.Icons.RECEIPT_LONG, "Inny koszt", lambda e: utils.przejdz(self._page, "/inne/nowy")),
            (ft.Icons.HANDYMAN, "Podzespół", lambda e: utils.przejdz(self._page, "/zadanie/nowy")),
            (ft.Icons.HOME_REPAIR_SERVICE, "Wizyta w warsztacie", lambda e: utils.przejdz(self._page, "/wizyty/nowa")),
            (ft.Icons.CHECKLIST_RTL, "Do zrobienia", lambda e: utils.przejdz(self._page, "/do-zrobienia/nowe")),
        ]
        return utils.fab_speed_dial(self._page, akcje, tooltip="Szybkie dodawanie")

    def potwierdz_grupowe_usuwanie(self, e):
        ile = len(self.zaznaczone_id)
        # Zaznaczenie grupowe omija router, więc rolę sprawdzamy tu wprost.
        # Przy współautorze nie da się z góry powiedzieć, czyje są WSZYSTKIE
        # zaznaczone wpisy — odsiewa je warstwa niżej (db.usun_wiele_z_cofnieciem).
        if utils.zablokowane(self._page, self.state.auto_id):
            return
        def wykonaj():
            if self.tabela_cel == "zadania":
                wynik = db.usun_wiele_zadan_z_cofnieciem(list(self.zaznaczone_id))
            else:
                wynik = db.usun_wiele_z_cofnieciem(self.tabela_cel, list(self.zaznaczone_id))

            self.zakoncz_zaznaczanie()
            utils.przejdz(self._page, "/")
            utils.pokaz_komunikat_cofnij(self._page, f"Pomyślnie usunięto {ile} elementów.", wynik)
        utils.potwierdz(self._page, "Usuwanie", f"Czy na pewno usunąć {ile} elementów?", wykonaj)

    # ================= KOSZTY — TANKOWANIA I POZOSTAŁE WYDATKI =================
    def buduj_koszty(self):
        """Paliwo i „inne” to były dwie zakładki na jedno pytanie: ile to auto
        kosztuje. Rozdzielone zajmowały połowę dolnego paska i zmuszały do
        przeskakiwania tam i z powrotem przy porównywaniu wydatków z jednego
        miesiąca. Teraz to jedna zakładka z przełącznikiem — a zwolnione miejsce
        dostał Kokpit."""
        def zmien(idx):
            self.state.koszty_podzakladka = int(idx)
            db.zapamietaj_podzakladke_kosztow(self.state.koszty_podzakladka)
            utils.przejdz(self._page, "/")

        self.elementy.append(utils.segmented_control(
            self._page,
            [("Tankowania", 0, ft.Icons.LOCAL_GAS_STATION), ("Inne koszty", 1, ft.Icons.RECEIPT_LONG)],
            int(getattr(self.state, "koszty_podzakladka", 0) or 0), zmien,
        ))

        if int(getattr(self.state, "koszty_podzakladka", 0) or 0) == 1:
            self.buduj_inne()
        else:
            self.buduj_tankowania()
