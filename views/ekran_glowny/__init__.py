"""Ekran główny aplikacji — pasek zakładek, kokpit i cztery zakładki treści.

Powstał z rozbicia jednego pliku main_view.py. Każda zakładka mieszka w osobnym
module jako miksin; `MainView` poniżej tylko je składa i trzyma wspólny stan.
"""

import asyncio
import db
import flet as ft
import log
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
        self.kokpit_kontener = None      # kontener przełączany między siatką a trybem układania
        self._kokpit_budowniczy = {}     # id widżetu -> funkcja budująca kafelek
        self._scena_zakladki = None      # animacja wejścia aktywnej zakładki (utils.ScenaWejscia)
        self.przelacznik_zakladek = None # zawartość zakładki żyje w nim (patrz przelacz_zakladke)
        self._gotowy = False             # True dopiero po super().__init__ (patrz _po_zbudowaniu_zakladki)
        self.pasek_zakladek = None       # ustawiany niżej, razem z dolnym paskiem
        self._przelacznik_pojazdow = None  # ustawiane w buduj_naglowek_auta (showroom aut)
        # --------------------------------------
        # --- CZTERY ZAKŁADKI = CZTERY POWODY, DLA KTÓRYCH SIĘ TU WCHODZI ---
        # Wcześniej dwie z czterech („Paliwo” i „Inne”) były tym samym pytaniem
        # — ile to kosztowało — rozbitym na dwie listy, a ekran startowy
        # (widżety kokpitu) nie miał własnego miejsca i doklejał się do Serwisu.
        # Teraz: Kokpit = „co się dzieje z autem”, Serwis = „co trzeba zrobić”,
        # Koszty = „ile to kosztuje”, Analiza = „jak to wygląda w czasie”.
        # Referencję do samego paska trzymamy, bo zakładkę zmienia się teraz także
        # spoza niego (kafelki kokpitu) — a wtedy zaznaczenie trzeba przestawić
        # ręcznie, skoro ekran nie powstaje od nowa.
        self.pasek_zakladek = ft.NavigationBar(
            destinations=[
                ft.NavigationBarDestination(icon=ft.Icons.SPACE_DASHBOARD_OUTLINED, selected_icon=ft.Icons.SPACE_DASHBOARD, label="Kokpit"),
                ft.NavigationBarDestination(icon=ft.Icons.BUILD_CIRCLE_OUTLINED, selected_icon=ft.Icons.BUILD_CIRCLE, label="Serwis"),
                ft.NavigationBarDestination(icon=ft.Icons.PAYMENTS_OUTLINED, selected_icon=ft.Icons.PAYMENTS, label="Koszty"),
                ft.NavigationBarDestination(icon=ft.Icons.INSIGHTS, selected_icon=ft.Icons.INSIGHTS, label="Analiza"),
            ],
            on_change=self.zmien_zakladke,
            selected_index=self.state.zakladka,
        )
        navbar = ft.SafeArea(content=self.pasek_zakladek, avoid_intrusions_top=False)

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
            # Nagłówek auta i oba paski zostają na miejscu przy zmianie zakładki —
            # zmienia się WYŁĄCZNIE to, co siedzi w przełączniku.
            self.przelacznik_zakladek = utils.PrzelacznikEkranow(
                self._zawartosc_zakladki(), wlaczony=db.czy_animacje_interfejsu()
            )
            self.elementy.append(self.przelacznik_zakladek.kontrolka)

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
        self._gotowy = True

    def zmien_zakladke(self, e):
        self.przelacz_zakladke(int(e.control.selected_index))

    def _zawartosc_zakladki(self):
        """Zawartość aktywnej zakładki jako JEDNA kontrolka — to ona jedzie przez
        przełącznik.

        Budowa jest ODROCZONA: najpierw idzie szkielet, treść dolicza się chwilę
        później (patrz utils.zbuduj_etapami). Lista tankowań z pięciu lat to
        kilkaset kontrolek — bez tego zakładka przez ułamek sekundy pokazuje
        pustkę, a pustka wygląda tak samo jak zepsuty ekran."""
        self._scena_zakladki = self._nowa_scena_zakladki()

        def zbuduj():
            # Buildery zakładek dopisują do `self.elementy` i ustawiają
            # `self.fab`, więc na czas budowy podstawiamy im własną listę. Poza tą
            # chwilą `self.elementy` znaczy dokładnie to, co znaczyło.
            wspolne, self.elementy = self.elementy, []
            self.fab = None
            try:
                if self.state.zakladka == 1:
                    self.buduj_serwis()
                elif self.state.zakladka == 2:
                    self.buduj_koszty()
                elif self.state.zakladka == 3:
                    self.buduj_statystyki()
                else:
                    self.buduj_kokpit_ekran()
                zebrane = self.elementy
            finally:
                self.elementy = wspolne

            # Szybkie dodawanie znika u kogoś, kto ma pojazd wyłącznie do wglądu.
            # FAB składają zakładki (patrz _buduj_fab_szybkich_akcji), więc gasimy
            # go tutaj — w jednym miejscu, przez które przechodzą wszystkie cztery.
            if self.state.auto_id and not utils.wolno_dodawac(self.state.auto_id):
                self.fab = None

            # Scena animacji rusza dopiero, gdy zawartość jest zbudowana.
            self._scena_zakladki.uruchom(self._page)

            # `spacing` odtwarza odstęp, który przy płaskiej liście dawał sam widok.
            return ft.Column(zebrane, spacing=15)

        return utils.zbuduj_etapami(
            self._page, self._szkielet_zakladki(), zbuduj,
            widok=self, po_zbudowaniu=self._po_zbudowaniu_zakladki,
        )

    def _szkielet_zakladki(self):
        """Zarys w kształcie tego, co za chwilę stanie na jego miejscu — inaczej
        treść „przeskakuje" po podmianie zamiast się w zarys wpasować."""
        zakladka = int(self.state.zakladka or 0)
        if zakladka == 0:
            return utils.szkielet_ekranu(self._page, kafle=2, karty=2, linie=1)
        if zakladka == 3:
            return utils.szkielet_ekranu(self._page, kafle=4, wykres=True, karty=1)
        return utils.szkielet_ekranu(self._page, karty=4)

    def _po_zbudowaniu_zakladki(self):
        """Przycisk dodawania zależy od zakładki, a powstaje razem z jej treścią —
        czyli już PO tym, jak widok trafił na ekran. Trzeba go więc dostawić.

        Bez pętli zdarzeń treść buduje się jeszcze w konstruktorze, zanim widok
        stanie się widokiem — wtedy nie ma czego dostawiać, bo `self.fab` i tak
        pojedzie do `super().__init__`."""
        if not self._gotowy:
            return
        self.floating_action_button = self.fab
        try:
            self.update()
        except Exception:
            log.polkniety("dostawienie przycisku dodawania po zbudowaniu zakładki")

    def _nowa_scena_zakladki(self):
        """Każda zakładka animuje się po swojemu, więc scenę dobiera się do niej,
        a nie odwrotnie.

        Kokpit odlicza LICZBY, wspólnym ruchem i tylko przy starcie aplikacji albo
        po zmianie pojazdu (patrz _czy_animowac_kokpit). Serwis i Analiza to listy
        PASKÓW — tam sens niesie kaskada: paski ruszają jeden po drugim, więc
        widać, który dojechał dalej. Koszty nie mają czego animować, dostają więc
        scenę wyłączoną i nie płacą za nic."""
        zakladka = int(self.state.zakladka or 0)

        if zakladka == 0:
            gra = self._czy_animowac_kokpit()
            if gra:
                # Znacznik stawiamy w chwili podjęcia decyzji — kolejne wejścia na
                # kokpit tego pojazdu mają już nie odliczać.
                self.state.kokpit_animacja_dla = self.state.auto_id
            return utils.ScenaWejscia(wlaczona=gra)

        if zakladka in (1, 3):
            klucz = "serwis" if zakladka == 1 else "analiza"
            return utils.ScenaWejscia(
                wlaczona=db.czy_animacje_interfejsu()
                and utils.pierwsze_pokazanie(self.state, klucz, self.state.auto_id),
                kaskada=True,
            )

        return utils.ScenaWejscia(wlaczona=False)

    def _wyczysc_stan_zakladki(self):
        """Stan, który przy przebudowie ekranu zerował konstruktor: tryb
        zaznaczania, referencje kart, wirtualizacja list i cały stan kokpitu.

        Bez tego zaznaczanie zaczęte w Serwisie przeszłoby na Koszty i skasowało
        nie te wpisy, co trzeba — a to jest dokładnie ta klasa błędu, którą
        przebudowa całego widoku dotąd maskowała."""
        self.tryb_zaznaczania = False
        self.zaznaczone_id = set()
        self.tabela_cel = ""
        self.karty_ref = {}
        self.uzyj_wirtualizacji = False
        self.zapomnij_listy_kart()
        self.appbar = self.oryginalny_appbar
        self.kokpit_edycja = False
        self.kokpit_kontener = None
        self._kokpit_budowniczy = {}
        self._scena_zakladki = None

    def _odswiez_szuflade(self):
        """Podświetlenie aktywnego ekranu w szufladzie jedzie za zakładką.
        Podmieniamy panel w momencie, w którym jest ZAMKNIĘTY — przy samym
        otwieraniu byłby to wyścig, w którym szuflada czasem się nie pokazuje."""
        try:
            self.drawer = utils.zbuduj_szuflade(
                self._page, self.state, self.akcje_nawigacji,
                aktywny_ekran=utils.EKRAN_ZAKLADKI.get(
                    (int(self.state.zakladka or 0),
                     int(getattr(self.state, "koszty_podzakladka", 0) or 0))
                ),
                on_pojazdy=self._pokaz_wybor_pojazdow if self.state.auto_id else None,
                widok=self,
            )
        except Exception:
            log.polkniety("odświeżenie szuflady po zmianie zakładki")

    def przelacz_zakladke(self, zakladka, podzakladka=None):
        """Zmiana zakładki BEZ przebudowy całego ekranu.

        Dotąd każde dotknięcie dolnego paska szło przez router: powstawał nowy
        MainView, z nowym nagłówkiem auta, nowym paskiem górnym i nową szufladą.
        Cztery zakładki wyglądały wtedy jak cztery ekrany podstawiane pod ten sam
        pasek — choć jedyne, co naprawdę miało się zmienić, to zawartość.

        Teraz nagłówek i oba paski ZOSTAJĄ, a zawartość ustępuje miejsca nowej
        przez przełącznik. Przy okazji jest to po prostu mniej pracy."""
        zakladka = int(zakladka or 0)
        stara = (int(self.state.zakladka or 0),
                 int(getattr(self.state, "koszty_podzakladka", 0) or 0))
        nowa = (zakladka, int(self.state.koszty_podzakladka if podzakladka is None else podzakladka))

        if not self.przelacznik_zakladek:
            # Ekran bez pojazdu nie ma czego przełączać — wraca stara droga.
            self.state.zakladka = zakladka
            utils.przejdz(self._page, "/")
            return
        if nowa == stara:
            # Dotknięcie zakładki, na której już się jest, nic nie zmienia —
            # dawniej przeładowywało cały ekran.
            return

        self.state.zakladka = zakladka
        if podzakladka is not None:
            self.state.koszty_podzakladka = int(podzakladka)

        self._wyczysc_stan_zakladki()
        # Liczniki przy skrótach i w szufladzie liczyły się dotąd w konstruktorze,
        # czyli przy każdym przełączeniu zakładki. Skoro konstruktor już nie
        # powstaje, przeliczamy je tutaj — inaczej kafelek pokazywałby stan sprzed
        # odhaczenia zrobionego przed chwilą w poprzedniej zakładce.
        self.liczniki_nawigacji = db.liczniki_nawigacji(self.state.auto_id) if self.state.auto_id else {}
        self.przelacznik_zakladek.pokaz(
            self._page, self._zawartosc_zakladki(),
            kierunek=utils.PrzelacznikEkranow.kierunek(stara, nowa),
        )
        # Przełączenie zakładki nie idzie przez router, więc nikt nie wróci na
        # zapamiętaną pozycję za nas. Zapisywanie działa samo — klucz liczy się
        # w chwili przewijania (patrz utils.pamietaj_pozycje).
        klucz_miejsca = utils.klucz_ekranu(self, self.state)
        utils.przewin_na(self._page, self, utils.pobierz_pozycje(self.state, klucz_miejsca),
                         opis=klucz_miejsca)
        self.floating_action_button = self.fab
        self._odswiez_szuflade()
        if self.pasek_zakladek is not None:
            self.pasek_zakladek.selected_index = zakladka

        # Zapisy, które przy starej drodze robił router (patrz
        # main.trasa_zmieniona): pamięć startu i historia „ostatnio używanych”.
        db.zapamietaj_ostatnia_pozycje(self.state.auto_id, zakladka)
        utils.zanotuj_ekran_dla_trasy(self.state, [])
        log.zapisz(f"zakładka: {nowa[0]}/{nowa[1]}")

    def odswiez_w_miejscu(self):
        """Przelicza ZAWARTOŚĆ bieżącej zakładki, nie ruszając reszty ekranu.

        Dotąd zmiana sortowania i filtra szła przez router: `page.views.clear()`
        i budowa wszystkiego od nowa — nagłówka auta, obu pasków, szuflady
        i listy. Ekran wracał przez to na samą górę, bo nowa lista nie wie nic
        o starej, a przewijana jest CAŁA strona, nie tylko lista.

        Tutaj strona zostaje ta sama, więc pozycja przewijania zostaje sama
        z siebie — bez zapamiętywania, bez `scroll_to` i bez czekania na układ.
        Wymienia się tylko zawartość zakładki, tak samo jak przy przełączaniu
        między zakładkami (patrz `przelacz_zakladke`), tyle że bez przesunięcia:
        nic się nie przesuwa w bok, bo nigdzie nie idziemy.

        Nagłówka auta NIE przebudowujemy: sortowanie i filtr nie zmieniają ani
        nazwy pojazdu, ani przebiegu. Akcja, która zmienia dane pojazdu, nadal
        idzie przez router."""
        if not self.przelacznik_zakladek:
            utils.przejdz(self._page, "/")
            return

        self._wyczysc_stan_zakladki()
        self.liczniki_nawigacji = db.liczniki_nawigacji(self.state.auto_id) if self.state.auto_id else {}
        self.przelacznik_zakladek.pokaz(self._page, self._zawartosc_zakladki(), kierunek=0)
        self.floating_action_button = self.fab
        self._odswiez_szuflade()

        try:
            self.update()
        except Exception:
            log.polkniety("odświeżenie ekranu po zmianie zakładki")

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
                utils.pokaz_komunikat(self._page, utils.podsumowanie_konfliktow(konflikty), utils.KOLOR_STATUS["warning"])
                utils.pokaz_dialog_konfliktow(self._page, konflikty, self.state.auto_id)
            elif odrzucone:
                utils.pokaz_komunikat(self._page, utils.podsumowanie_odrzuconych(odrzucone), utils.KOLOR_STATUS["warning"])
            elif db.czy_tylko_podglad(self.state.auto_id):
                utils.pokaz_komunikat(self._page, f"Pobrano {db.liczba_z_odmiana(pobrano, 'zmianę', 'zmiany', 'zmian')}. Ten pojazd masz w trybie tylko do odczytu.")
            else:
                utils.pokaz_komunikat(self._page, f"Wysłano {db.liczba_z_odmiana(wyslano, 'rekord', 'rekordy', 'rekordów')}, "
                                      f"pobrano {db.liczba_z_odmiana(pobrano, 'rekord', 'rekordy', 'rekordów')}.")
        except sync.SynchronizacjaWToku:
            utils.pokaz_komunikat(self._page, "Synchronizacja już trwa — chwilę to potrwa.")
        except Exception as ex:
            db.zakolejkuj_synchronizacje(self.state.auto_id, "reczna", str(ex))
            utils.pokaz_komunikat(
                self._page,
                f"Błąd synchronizacji: {ex}. Zmiany zostały zakolejkowane i spróbujemy ponownie automatycznie.",
                utils.KOLOR_STATUS["error"]
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
            utils.pokaz_komunikat_cofnij(self._page, f"Usunięto {db.liczba_z_odmiana(ile, 'element', 'elementy', 'elementów')}.", wynik)
        utils.potwierdz(self._page, "Usuwanie", f"Czy na pewno usunąć {db.liczba_z_odmiana(ile, 'element', 'elementy', 'elementów')}?", wykonaj)

    # ================= KOSZTY — TANKOWANIA I POZOSTAŁE WYDATKI =================
    def buduj_koszty(self):
        """Paliwo i „inne” to były dwie zakładki na jedno pytanie: ile to auto
        kosztuje. Rozdzielone zajmowały połowę dolnego paska i zmuszały do
        przeskakiwania tam i z powrotem przy porównywaniu wydatków z jednego
        miesiąca. Teraz to jedna zakładka z przełącznikiem — a zwolnione miejsce
        dostał Kokpit."""
        def zmien(idx):
            db.zapamietaj_podzakladke_kosztow(int(idx))
            self.przelacz_zakladke(2, podzakladka=int(idx))

        self.elementy.append(utils.segmented_control(
            self._page,
            [("Tankowania", 0, ft.Icons.LOCAL_GAS_STATION), ("Inne koszty", 1, ft.Icons.RECEIPT_LONG)],
            int(getattr(self.state, "koszty_podzakladka", 0) or 0), zmien,
        ))

        if int(getattr(self.state, "koszty_podzakladka", 0) or 0) == 1:
            self.buduj_inne()
        else:
            self.buduj_tankowania()
