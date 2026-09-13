"""Animacja wejścia: liczby dojeżdżające do wartości, wskaźniki rosnące od zera.

Kokpit jest pierwszym, co widać po uruchomieniu aplikacji. Krótki ruch przy
wejściu robi z niego moment, a nie ekran — ale tylko pod warunkiem, że jest
KRÓTKI i JEDNORAZOWY. Animacja w pętli albo trwająca sekundę zamienia się
w opóźnienie odczytu: liczba jest wtedy nieczytelna dłużej, niż trwa spojrzenie
na kafelek.

Wszystkie kafelki jadą na JEDNYM zegarze (`ScenaWejscia`). Osobny timer na
kafelek dałby osiemnaście animacji rozjeżdżających się w czasie, a każda z nich
osobno budziłaby pętlę zdarzeń — na telefonie widać to jako szarpanie.
"""

import asyncio
import flet as ft
import log
import time

# Czas całego przejścia. Poniżej ~350 ms ruch jest tylko mignięciem, powyżej
# ~800 ms kafelek przestaje wyglądać jak kafelek, a zaczyna jak ładowanie.
CZAS_ANIMACJI_MS = 600

# Klatki liczymy z ZEGARA, nie z licznika kroków: na wolniejszym telefonie
# animacja zgubi klatki, ale skończy się w swoim czasie i na dokładnej
# wartości — zamiast rozciągnąć się na dwie sekundy.
KLATEK_NA_SEKUNDE = 30

# Widok trafia do drzewa strony dopiero po powrocie z buduj_* (router dokłada go
# do page.views i dopiero wtedy woła update). Bez tej pauzy pierwsze patche
# leciałyby w próżnię.
OPOZNIENIE_STARTU_S = 0.06

# Przejście między zakładkami. Krótsze od odliczania liczb, bo tu ruch ma tylko
# powiedzieć „to wciąż ta sama aplikacja”, a nie zwrócić na siebie uwagę.
# Zakładki przełącza się dziesiątki razy dziennie — powyżej ~300 ms każde takie
# przełączenie zaczyna się dłużyć.
CZAS_PRZEJSCIA_MS = 200

# Nowa zawartość wjeżdża z tej strony, po której leży w pasku — ale tylko o kilka
# procent szerokości. Pełny slide czytałby się jak przewracanie stron, a zakładki
# nie są stronami: mają wyglądać na sąsiadów, nie na kolejne kartki.
PRZESUNIECIE_PRZEJSCIA = 0.05

# Tyle wystarczy, żeby nowa zawartość zdążyła trafić na ekran w stanie
# początkowym. Gdyby stan początkowy i docelowy poszły jednym patchem, Flutter
# nie miałby czego animować.
OPOZNIENIE_KLATKI_S = 0.03


def wygladzenie(t):
    """Cubic ease-out: szybki początek, miękkie dojście do celu. Liczba ma
    „dolecieć” i stanąć — liniowy przebieg wygląda jak licznik taksówki, który
    urywa się w przypadkowym momencie."""
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def _petla_w_tym_watku():
    """`get_running_loop` rzuca, kiedy pętli nie ma — to zwykła odpowiedź „nie”,
    a nie błąd do zalogowania."""
    try:
        return asyncio.get_running_loop().is_running()
    except RuntimeError:
        return False


def _petla_dziala(page):
    """Czy jest pętla zdarzeń, w której animacja ma szansę w ogóle pojechać.

    Bez niej `page.run_task` tworzy korutynę, której nikt nie odbiera — tak
    dzieje się przy budowaniu widoków bez okna (testy) — a kafelki zostałyby na
    zawsze z zerami stanu początkowego. Niepewność rozstrzygamy więc na korzyść
    ODCZYTU: nie ma pętli, nie ma animacji, są za to od razu właściwe liczby."""
    if _petla_w_tym_watku():
        return True
    # Sięgnięcie do wnętrza Fleta jest tu świadome i osłonięte: gdy ta droga
    # kiedyś zniknie — albo sesja zdąży się rozpaść, a `page.session` RZUCI
    # zamiast zwrócić None — wyjdzie z tego brak animacji, a nie wyjątek
    # w środku budowania ekranu.
    try:
        petla = getattr(getattr(page.session, "connection", None), "loop", None)
        return bool(petla is not None and petla.is_running())
    except Exception:
        return False


class ScenaWejscia:
    """Zbiór torów animacji jednego ekranu, odtwarzany raz — przy wejściu.

    Kafelek nie wie nic o animacji: prosi scenę o kontrolkę (`liczba`,
    `wskaznik`, `wysokosc`), a scena zapamiętuje, jak tę kontrolkę prowadzić od
    stanu początkowego do docelowego. Scena wyłączona (`wlaczona=False`) zwraca
    te same kontrolki od razu w stanie docelowym — dzięki temu w kodzie kafelków
    nie ma ani jednego „jeśli animacje włączone”.
    """

    def __init__(self, wlaczona=True, czas_ms=CZAS_ANIMACJI_MS):
        self.wlaczona = bool(wlaczona)
        self.czas_ms = max(1, int(czas_ms))
        self._tory = []        # ustaw(postep) — wołane co klatkę
        self._skoki = []       # ustaw() — wołane raz, na starcie sceny
        self._kontrolki = []   # do page.update(*...) — bez powtórzeń
        self._odtworzona = False

    @property
    def pusta(self):
        return not self._tory and not self._skoki

    @property
    def czynna(self):
        """Scena przyjmuje nowe tory tylko DO chwili odtworzenia. Kafelki
        zbudowane później — przy odświeżeniu kokpitu albo w trybie układania —
        dostają wartości docelowe od razu; inaczej zostałyby z zerami, bo
        animacja już się odbyła i nikt ich do końca nie doprowadzi."""
        return self.wlaczona and not self._odtworzona

    def wygas(self):
        """Zamyka scenę na nowe tory, nie ruszając tego, co już narysowane.
        Woła to ekran, który przebudowuje kafelki poza wejściem."""
        self._odtworzona = True

    # ----- rejestracja torów -----
    def _zapamietaj(self, kontrolka):
        if kontrolka is not None and all(k is not kontrolka for k in self._kontrolki):
            self._kontrolki.append(kontrolka)

    def tor(self, ustaw, *kontrolki):
        """Własny tor: `ustaw(postep)` dostaje 0.0 → 1.0 i sam decyduje, co z tym
        zrobić. `kontrolki` to te, które po zmianie trzeba odświeżyć."""
        if not self.czynna:
            ustaw(1.0)
            return
        ustaw(0.0)
        self._tory.append(ustaw)
        for k in kontrolki:
            self._zapamietaj(k)

    def skok(self, ustaw_poczatek, ustaw_koniec, *kontrolki):
        """Tor dla kontrolek, które Flet animuje SAM (`Container.animate`):
        stan początkowy ustawiamy przy budowie, docelowy — jedną zmianą na
        starcie sceny, a płynne przejście dokłada już Flutter. Taniej niż
        liczyć klatki pośrednie w Pythonie, więc tak robimy wszędzie, gdzie
        kontrolka to potrafi."""
        if not self.czynna:
            ustaw_koniec()
            return
        ustaw_poczatek()
        self._skoki.append(ustaw_koniec)
        for k in kontrolki:
            self._zapamietaj(k)

    def liczba(self, wartosc, formatuj, od=0.0, **pola):
        """Główna liczba kafelka jako ft.Text, który przy wejściu odlicza od `od`
        do `wartosc`. `formatuj` dostaje wartość pośrednią i zwraca CAŁY napis —
        z jednostką i separatorami — więc kafelek nie musi wiedzieć nic
        o animacji, a animacja nic o walucie.

        Uwaga na jednostki odwrotne (km/l, mpg): wołający ma podać liczbę JUŻ
        przeliczoną na to, co widać na ekranie. Animowanie l/100km i formatowanie
        na km/l dałoby odliczanie w złą stronę, a start od zera — dzielenie przez
        zero."""
        try:
            cel = float(wartosc)
        except (TypeError, ValueError):
            # Kafelek bez liczby (np. „Brak danych”) — nie ma czego animować.
            return ft.Text(str(wartosc), **pola)

        tekst = ft.Text(formatuj(cel), **pola)

        def ustaw(postep, _t=tekst, _od=float(od), _cel=cel):
            _t.value = formatuj(_od + (_cel - _od) * postep)

        self.tor(ustaw, tekst)
        return tekst

    def wskaznik(self, kontrolka, wartosc=None, od=0.0):
        """Pasek albo pierścień postępu napełniający się od zera. Flet nie
        animuje `value` sam (ani ProgressBar, ani ProgressRing), więc tu klatki
        muszą lecieć z Pythona. Wartość docelowa domyślnie jest tą, z którą
        kontrolka powstała — nie trzeba jej podawać drugi raz."""
        try:
            cel = float(kontrolka.value if wartosc is None else wartosc)
        except (TypeError, ValueError):
            return kontrolka

        def ustaw(postep, _k=kontrolka, _od=float(od), _cel=cel):
            _k.value = _od + (_cel - _od) * postep

        self.tor(ustaw, kontrolka)
        return kontrolka

    def wysokosc(self, kontener, docelowa, od=0):
        """Słupek wykresu wyrastający od dołu. Kontener dostaje własne
        `animate`, więc przejście rysuje Flutter — my zmieniamy wysokość raz."""
        try:
            cel = float(docelowa)
        except (TypeError, ValueError):
            return kontener

        if self.czynna:
            # Czas ten sam, co reszta sceny — inaczej słupki stanęłyby przed
            # liczbami albo po nich, i wejście rozpadłoby się na dwa ruchy.
            kontener.animate = ft.Animation(self.czas_ms, ft.AnimationCurve.EASE_OUT)
        self.skok(
            lambda _k=kontener, _od=od: setattr(_k, "height", _od),
            lambda _k=kontener, _c=cel: setattr(_k, "height", _c),
            kontener,
        )
        return kontener

    def udzial(self, wypelnienie, reszta, docelowy_udzial, skala=1000):
        """Pasek zbudowany z dwóch kontenerów na `expand` (tak rysuje się pasek
        budżetu). Fletowe `animate` nie obejmuje `expand` — to pole układu, nie
        wygląd kontenera — więc ten pasek jedzie klatka po klatce."""
        try:
            cel = max(0.0, min(1.0, float(docelowy_udzial)))
        except (TypeError, ValueError):
            return

        def ustaw(postep, _w=wypelnienie, _r=reszta, _c=cel, _s=skala):
            udzial = _c * postep
            _w.expand = max(1, int(udzial * _s))
            _r.expand = max(1, int((1 - udzial) * _s))

        self.tor(ustaw, wypelnienie, reszta)

    # ----- odtwarzanie -----
    def uruchom(self, page):
        """Odpala scenę w pętli zdarzeń strony.

        `run_task` sprawdza `asyncio.iscoroutinefunction` i odrzuca wszystko, co
        nie jest `async def` — lambda zwracająca korutynę też (patrz notatka
        o zgodności z Fletem), stąd nazwana korutyna poniżej."""
        if not self.wlaczona or self.pusta or self._odtworzona or page is None:
            return
        self._odtworzona = True

        if not _petla_dziala(page):
            self.zakoncz()
            return

        async def _graj():
            await self.odtworz(page)

        try:
            page.run_task(_graj)
        except Exception:
            # Gdyby mimo wszystko nie dało się zaplanować zadania — kafelki i tak
            # muszą pokazać swoje właściwe wartości.
            self.zakoncz()

    async def odtworz(self, page):
        await asyncio.sleep(OPOZNIENIE_STARTU_S)
        odstep = 1.0 / KLATEK_NA_SEKUNDE
        poczatek = time.monotonic()
        try:
            for ustaw_koniec in self._skoki:
                ustaw_koniec()
            while True:
                uplynelo_ms = (time.monotonic() - poczatek) * 1000
                if uplynelo_ms >= self.czas_ms:
                    break
                postep = wygladzenie(uplynelo_ms / self.czas_ms)
                for ustaw in self._tory:
                    ustaw(postep)
                self._odswiez(page)
                await asyncio.sleep(odstep)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Najczęściej: ekran zmienił się w trakcie i kafelków nie ma już
            # w drzewie strony. Idziemy dalej — `finally` i tak ustawi wartości
            # docelowe — ale zostawiamy ślad, bo to samo wygląda tak, jak
            # prawdziwy błąd w torze animacji.
            log.polkniety("animacja wejścia na kokpit")
        finally:
            self.zakoncz(page)

    def zakoncz(self, page=None):
        """Ostatnia klatka jest ZAWSZE dokładną wartością docelową. Pętla po
        zegarze potrafi wyjść przy 0,98 postępu i bez tego kafelek zostałby
        z liczbą „prawie dobrą” — czyli po prostu złą."""
        try:
            for ustaw_koniec in self._skoki:
                ustaw_koniec()
            for ustaw in self._tory:
                ustaw(1.0)
        except Exception:
            log.polkniety("dokończenie animacji kokpitu na wartościach docelowych")
        if page is not None:
            try:
                self._odswiez(page)
            except Exception:
                log.polkniety("odświeżenie kokpitu po animacji")

    def _odswiez(self, page):
        """Jedno `page.update` na klatkę dla wszystkich kafelków naraz — Flet
        potrafi opatchować wiele kontrolek jednym wywołaniem, a osobny update
        na kontrolkę to osobna wiadomość do klienta."""
        if not self._kontrolki:
            return
        page.update(*self._kontrolki)


class PrzelacznikEkranow:
    """Jedna zawartość ustępuje drugiej: przenikanie plus przesunięcie w kierunku
    ruchu.

    Cztery zakładki przełącza się dziesiątki razy dziennie. Płynne przejście robi
    z nich JEDNĄ aplikację; twarda podmiana — cztery ekrany podstawiane pod ten
    sam pasek.

    Flet daje w `AnimatedSwitcher` tylko FADE, SCALE i ROTATION, więc
    przesunięcie dokładamy sami: opakowanie startuje z `offset` i dojeżdża do
    zera własnym `animate_offset`. Wychodzi to lepiej niż gotowy slide — obie
    części przejścia rysuje Flutter, a Python nie liczy tu ani jednej klatki.
    """

    def __init__(self, zawartosc, wlaczony=True, czas_ms=CZAS_PRZEJSCIA_MS):
        self.wlaczony = bool(wlaczony)
        self.czas_ms = max(1, int(czas_ms))
        self._licznik = 0
        self._opakowanie = self._opakuj(zawartosc, kierunek=0)
        self.kontrolka = ft.AnimatedSwitcher(
            content=self._opakowanie,
            # Wyłączone animacje = zerowy czas. Jedna ścieżka kodu zamiast dwóch,
            # a przełącznik i tak zostaje tam, gdzie był.
            duration=self.czas_ms if self.wlaczony else 0,
            # Stara zawartość gaśnie szybciej, niż pojawia się nowa — inaczej
            # przez chwilę widać dwie naraz i przejście robi się mętne.
            reverse_duration=int(self.czas_ms * 0.6) if self.wlaczony else 0,
            switch_in_curve=ft.AnimationCurve.EASE_OUT,
            switch_out_curve=ft.AnimationCurve.EASE_IN,
            transition=ft.AnimatedSwitcherTransition.FADE,
        )

    @staticmethod
    def kierunek(stara_pozycja, nowa_pozycja):
        """+1, gdy nowa rzecz leży w pasku na PRAWO od poprzedniej (wjeżdża
        z prawej), -1 gdy na lewo. Pozycją może być numer zakładki albo krotka
        (zakładka, podzakładka) — porównanie krotek załatwia oba naraz."""
        if nowa_pozycja == stara_pozycja:
            return 0
        return 1 if nowa_pozycja > stara_pozycja else -1

    def _opakuj(self, zawartosc, kierunek):
        """Każda zawartość dostaje WŁASNY klucz. Bez niego Flutter uznałby nowe
        dziecko za to samo co poprzednie i przejścia by nie było."""
        self._licznik += 1
        przesuniecie = PRZESUNIECIE_PRZEJSCIA * kierunek if self.wlaczony else 0
        return ft.Container(
            content=zawartosc,
            key=f"ekran-{self._licznik}",
            offset=ft.Offset(przesuniecie, 0),
            animate_offset=ft.Animation(self.czas_ms, ft.AnimationCurve.EASE_OUT),
        )

    def pokaz(self, page, zawartosc, kierunek=0):
        """Podmienia zawartość przełącznika. `kierunek` z `PrzelacznikEkranow.kierunek`."""
        opakowanie = self._opakuj(zawartosc, kierunek)
        self._opakowanie = opakowanie
        self.kontrolka.content = opakowanie
        try:
            self.kontrolka.update()
        except Exception:
            # Przełącznik nie jest jeszcze w drzewie strony — zawartość i tak
            # jest podmieniona i pokaże się przy najbliższym renderze.
            log.polkniety("podmiana zawartości przełącznika ekranów")
        self._dojedz(page, opakowanie)
        return opakowanie

    def _dojedz(self, page, opakowanie):
        """Zerowanie offsetu MUSI pójść osobnym patchem, już po tym, jak nowa
        zawartość trafi na ekran przesunięta."""
        if not self.wlaczony or page is None or not opakowanie.offset.x:
            return

        if not _petla_dziala(page):
            opakowanie.offset = ft.Offset(0, 0)
            return

        async def _dojedz_teraz():
            await asyncio.sleep(OPOZNIENIE_KLATKI_S)
            opakowanie.offset = ft.Offset(0, 0)
            try:
                opakowanie.update()
            except Exception:
                log.polkniety("dojazd przejścia między zakładkami")

        try:
            page.run_task(_dojedz_teraz)
        except Exception:
            opakowanie.offset = ft.Offset(0, 0)


__all__ = [
    "CZAS_ANIMACJI_MS",
    "CZAS_PRZEJSCIA_MS",
    "KLATEK_NA_SEKUNDE",
    "OPOZNIENIE_KLATKI_S",
    "OPOZNIENIE_STARTU_S",
    "PRZESUNIECIE_PRZEJSCIA",
    "PrzelacznikEkranow",
    "ScenaWejscia",
    "wygladzenie",
]
