"""Nagłówki miesięcy na długich listach: separator w liście i pasek przyklejony u góry
ekranu, gdy lista przewija się razem z nagłówkiem (`PrzewijanaTresc`). Pozycję
szacujemy z kolejności elementów i SKALUJEMY do prawdziwej wysokości listy
(`on_size_change`) — bez tego pasek rozjeżdżałby się z listą."""

import flet as ft
import log
from date import parsuj_date
from state import MIESIACE_NAZWY

from .stale import FS, RADIUS, SPACING, formatuj_liczba
from .format import _odmiana_liczby, symbol_waluty
from .pozycja import dodaj_obsluge_przewijania, pobierz_limit_listy, zapisz_limit_listy
from .wyglad import odstep_listy, tlo_karty

# Separator ma zadaną wysokość nie dla wyglądu, tylko dla rachunku: to jedyny
# element listy, którego wysokość znamy DOKŁADNIE.
WYSOKOSC_NAGLOWKA = 34

# Pasek przyklejony u góry: margines nad i pod pigułką (pas tła zasłania karty).
MARGINES_PASKA = 6

# Ile pikseli przed nagłówkiem uznajemy, że jesteśmy już w jego miesiącu —
# tyle, ile zajmuje przyklejony pasek. Dzięki temu pasek przełącza się dokładnie
# wtedy, kiedy separator chowa się pod nim.
PROG_PRZELACZENIA = WYSOKOSC_NAGLOWKA + MARGINES_PASKA

# Co leży w przewijanej treści POD listą: odstęp, `dol_bezpieczny(10)` i dolny
# margines listy ekranu — tyle odejmujemy, żeby znaleźć początek listy.
OGON_PRZEWIJANIA = 40

# Lista przewija się razem z ekranem, więc Flutter buduje KAŻDĄ kartę naraz (ListView
# budował tylko widoczne): przy 400 tankowaniach ekran stawał się kilka razy wolniej.
# Na start tyle wpisów, a „Pokaż kolejne” podwaja porcję.
PORCJA_WPISOW = 40


def klucz_miesiaca(data_tekst):
    """(rok, miesiąc) albo None, gdy daty nie da się odczytać."""
    d = parsuj_date(data_tekst)
    if d.year <= 1:
        return None
    return (d.year, d.month)


def nazwa_miesiaca(klucz):
    rok, mies = klucz
    return f"{MIESIACE_NAZWY[mies - 1]} {rok}"


ODMIANA_WPISOW = ("wpis", "wpisy", "wpisów")


def _podsumowanie(ile, suma, pokaz_kwoty, odmiana=ODMIANA_WPISOW):
    """„4 wpisy · 1 240 zł”. Przewijanie zamienia się wtedy w przegląd miesięcy —
    widać, który był drogi, bez wchodzenia w statystyki. `odmiana` — trzy formy nazwy."""
    czesci = [f"{ile} {_odmiana_liczby(ile, *odmiana)}"]
    if pokaz_kwoty and suma:
        czesci.append(f"{formatuj_liczba(suma, 0)} {symbol_waluty()}")
    return " • ".join(czesci)


def czy_po_dacie(state, klucz_listy, pola_dat=("data",)):
    """Czy lista jest w tej chwili posortowana po dacie.

    Nagłówki miesięcy mają sens WYŁĄCZNIE wtedy: lista ułożona po kwocie albo po
    nazwie skacze między miesiącami, a wtedy każdy nagłówek kłamałby o tym, co
    pod nim leży."""
    try:
        pole = (getattr(state, "sort", {}) or {}).get(klucz_listy, ("data", True))[0]
    except Exception:
        return True
    return pole in pola_dat


def lista_kart(odstep=None):
    """Kontener kart listy, który przewija się RAZEM z ekranem (bez własnej wysokości)."""
    return ft.Column(spacing=odstep_listy() if odstep is None else odstep)


class PrzewijanaTresc:
    """Treść ekranu w JEDNYM przewijaniu (nagłówek, filtry i lista razem) plus miejsce na
    pasek miesiąca przyklejony u góry. Widok wstawia `kontrolka` jako jedyne dziecko
    `ft.View(padding=0)` bez `scroll`, treść daje przez `controls`; pamięć pozycji i
    pasek słuchają `przewijana`."""

    def __init__(self, kontrolki=None, padding=15, spacing=15):
        self.zawartosc = ft.Column(list(kontrolki or []), spacing=spacing)
        # Kolumna, nie ListView: ListView SZACUJE wysokość treści z dzieci, które już
        # zbudował (max_scroll_extent skakał o tysiące pikseli), a pasek liczy z niej
        # początek listy.
        self.przewijana = ft.Column([ft.Container(self.zawartosc, padding=padding)],
                                    scroll=ft.ScrollMode.AUTO)
        self.miejsce = ft.Container(top=0, left=0, right=0, visible=False)
        self.grupy = None
        self.kontrolka = ft.Stack([self.przewijana, self.miejsce], fit=ft.StackFit.EXPAND, expand=True)
        # Dokładamy się do `on_scroll`: na tej samej kontrolce siedzi pamięć pozycji.
        dodaj_obsluge_przewijania(self.przewijana, self._przewiniete)

    @property
    def controls(self):
        return self.zawartosc.controls

    @controls.setter
    def controls(self, kontrolki):
        self.zawartosc.controls = list(kontrolki)

    def przyklej(self, grupy):
        """Pasek tych grup idzie na górę ekranu; `None` zdejmuje poprzedni (zmiana zakładki)."""
        self.grupy = grupy
        self.miejsce.content = grupy.kontrolka if grupy is not None else None
        self.miejsce.visible = grupy is not None

    def _przewiniete(self, e):
        if self.grupy is not None:
            self.grupy._przewiniete(e)


class GrupyMiesiecy:
    """Nagłówki miesięcy dla jednej listy kart.

    Widok buduje karty jak dotąd, a zamiast dopisywać je wprost do
    `lista.controls`, oddaje je tutaj przez `ustaw()`. Ta sama metoda obsługuje
    filtrowanie wyszukiwarką — po prostu dostaje krótszą listę. `widok` z
    `przewijana_tresc` dostaje pasek przyklejony u góry ekranu.
    """

    def __init__(self, page, lista, wysokosc_pozycji=175, pokaz_kwoty=True, widok=None,
                 ogon=OGON_PRZEWIJANIA, klucz=None, porcja=PORCJA_WPISOW, po_rozlozeniu=None,
                 odmiana=ODMIANA_WPISOW):
        self._page = page
        self.lista = lista
        self.wysokosc_pozycji = wysokosc_pozycji
        self.pokaz_kwoty = pokaz_kwoty
        self.odmiana = odmiana
        self.ogon = ogon
        # Rozwinięcie listy pamięta stan aplikacji pod `klucz` (przebudowa po akcji na
        # wpisie ma go nie zwijać); `po_rozlozeniu(grupy)` woła się po każdym ułożeniu.
        self._state = getattr(widok, "state", None)
        self._klucz = klucz
        self.porcja = max(1, int(porcja))
        self._limit = self.porcja
        if self._state is not None and klucz:
            self._limit = max(self.porcja, int(pobierz_limit_listy(self._state, klucz) or 0))
        self.po_rozlozeniu = po_rozlozeniu
        self._pozycje, self._grupuj = [], True

        self._offsety = []          # [(offset w szacowanych pikselach, klucz miesiąca)]
        self._opisy = {}            # klucz miesiąca -> podsumowanie
        self._wysokosc_szacowana = 0
        self._wysokosc_realna = None  # prawdziwa wysokość listy (on_size_change)
        self._biezacy = None

        self._tytul = ft.Text("", size=FS["label"], weight="bold", color=ft.Colors.PRIMARY,
                              no_wrap=True)
        self._opis = ft.Text("", size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT, no_wrap=True,
                             overflow=ft.TextOverflow.ELLIPSIS, expand=True, text_align=ft.TextAlign.END)
        # Pasek wygląda jak separator, który dojechał do góry. Leży NAD przewijaną
        # treścią, więc pas pod pigułką ma pełne tło (sam szczebel drabinki jest
        # półprzezroczysty i prześwitywałyby przez niego karty).
        self.kontrolka = ft.Container(
            visible=False,
            bgcolor=ft.Colors.SURFACE,
            padding=ft.Padding(SPACING["md"], MARGINES_PASKA, SPACING["md"], MARGINES_PASKA),
            shadow=ft.BoxShadow(blur_radius=6, offset=ft.Offset(0, 2),
                                color=ft.Colors.with_opacity(0.12, ft.Colors.SHADOW)),
            content=ft.Container(
                height=WYSOKOSC_NAGLOWKA,
                padding=ft.Padding(SPACING["sm"], 0, SPACING["sm"], 0),
                border_radius=RADIUS["sm"],
                bgcolor=tlo_karty(page, poziom=2),
                content=ft.Row([self._tytul, self._opis], spacing=SPACING["sm"],
                               vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ),
        )

        # Prawdziwa wysokość listy — mnożnik dla szacunku i początek listy w treści.
        lista.on_size_change = self._zmierzona
        lista.size_change_interval = 100

        tresc = getattr(widok, "przewijana_tresc", None)
        if tresc is not None:
            tresc.przyklej(self)

    def _zmierzona(self, e):
        wysokosc = getattr(e, "height", None)
        if wysokosc:
            self._wysokosc_realna = float(wysokosc)

    # ----- budowa -----
    def _naglowek(self, klucz):
        # Lista bez odstępów (oś czasu: odstęp siedzi w wierszach) — separator dostaje
        # własny margines, inaczej przyklejałby się do karty pod nim.
        bez_odstepu = not (getattr(self.lista, "spacing", 0) or 0)
        return ft.Container(
            height=WYSOKOSC_NAGLOWKA,
            margin=ft.Margin(0, 0, 0, SPACING["sm"]) if bez_odstepu else None,
            padding=ft.Padding(SPACING["sm"], 0, SPACING["sm"], 0),
            border_radius=RADIUS["sm"],
            bgcolor=tlo_karty(self._page, poziom=2),
            content=ft.Row([
                ft.Text(nazwa_miesiaca(klucz), size=FS["label"], weight="bold",
                        color=ft.Colors.PRIMARY, no_wrap=True),
                ft.Text(self._opisy.get(klucz, ""), size=FS["caption"],
                        color=ft.Colors.ON_SURFACE_VARIANT, no_wrap=True,
                        overflow=ft.TextOverflow.ELLIPSIS, expand=True,
                        text_align=ft.TextAlign.END),
            ], spacing=SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )

    def ustaw(self, pozycje, grupuj=True):
        """Wypełnia listę kartami z separatorami na granicach miesięcy. `pozycje`:
        [{karta, data, kwota?}]; `grupuj=False` (lista nie po dacie) — same karty.
        Rysuje najwyżej porcję (reszta pod „Pokaż kolejne”), podsumowania miesięcy liczy
        ze wszystkich. Zwraca [(klucz miesiąca, [narysowane pozycje])] w kolejności (np.
        dla osi czasu urywanej na nagłówkach)."""
        self._pozycje, self._grupuj = list(pozycje or []), grupuj
        return self._rozloz()

    def _po(self, wynik):
        if self.po_rozlozeniu is not None:
            self.po_rozlozeniu(wynik)
        return wynik

    def _przycisk_kolejnych(self, reszta):
        # Zapas pod przyciskiem, żeby dało się go wysunąć nad pływający „+”.
        return ft.Container(
            alignment=ft.Alignment.CENTER,
            padding=ft.Padding(0, SPACING["sm"], 0, 72),
            content=ft.OutlinedButton(
                f"Pokaż kolejne {min(reszta, self._limit)} z {reszta}",
                icon=ft.Icons.EXPAND_MORE, on_click=self._pokaz_kolejne,
            ),
        )

    def _pokaz_kolejne(self, e=None):
        self._limit *= 2
        if self._state is not None and self._klucz:
            zapisz_limit_listy(self._state, self._klucz, self._limit)
        self._rozloz()
        try:
            self.lista.update()
        except Exception:
            log.polkniety("odsłonięcie kolejnych wpisów listy")

    def _rozloz(self):
        pozycje, grupuj = self._pozycje, self._grupuj
        self.lista.controls = []
        self._offsety, self._opisy, self._biezacy = [], {}, None
        self._wysokosc_szacowana = 0

        if not pozycje:
            self.kontrolka.visible = False
            return self._po([])

        # Grupy w KOLEJNOŚCI, w jakiej przyszły — sortowanie należy do widoku,
        # my tylko nazywamy to, co już ułożone.
        grupy, kolejnosc = {}, []
        for p in pozycje:
            klucz = klucz_miesiaca(p.get("data")) if grupuj else None
            if klucz is not None and klucz not in grupy:
                grupy[klucz] = []
                kolejnosc.append(klucz)
            if klucz is not None:
                grupy[klucz].append(p)

        if not grupuj or len(kolejnosc) < 1:
            widoczne = pozycje[:self._limit]
            self.lista.controls = [p["karta"] for p in widoczne]
            if len(pozycje) > len(widoczne):
                self.lista.controls.append(self._przycisk_kolejnych(len(pozycje) - len(widoczne)))
            self.kontrolka.visible = False
            return self._po([(None, widoczne)])

        for klucz in kolejnosc:
            wpisy = grupy[klucz]
            suma = sum(float(p.get("kwota") or 0) for p in wpisy)
            self._opisy[klucz] = _podsumowanie(len(wpisy), suma, self.pokaz_kwoty, self.odmiana)

        # Separator także przy jednym miesiącu: przyklejony pasek pokazuje się
        # dopiero, gdy lista dojedzie do góry ekranu — wcześniej mówi separator.
        odstep = getattr(self.lista, "spacing", 0) or 0
        wysokosc, zostalo = 0, self._limit
        wynik = []

        for klucz in kolejnosc:
            if zostalo <= 0:
                break
            self._offsety.append((wysokosc, klucz))
            self.lista.controls.append(self._naglowek(klucz))
            wysokosc += WYSOKOSC_NAGLOWKA + odstep
            narysowane = grupy[klucz][:zostalo]
            zostalo -= len(narysowane)
            for p in narysowane:
                self.lista.controls.append(p["karta"])
                wysokosc += self.wysokosc_pozycji + odstep
            wynik.append((klucz, narysowane))

        # Pozycje bez czytelnej daty i tak muszą trafić na listę — inaczej
        # wyszukiwarka „gubiłaby” wpisy, których nie widać po niczyjej winie.
        bez_daty = [p for p in pozycje if klucz_miesiaca(p.get("data")) is None][:max(0, zostalo)]
        self.lista.controls.extend(p["karta"] for p in bez_daty)
        wysokosc += len(bez_daty) * (self.wysokosc_pozycji + odstep)
        if bez_daty:
            wynik.append((None, bez_daty))

        reszta = len(pozycje) - sum(len(w) for _, w in wynik)
        if reszta > 0:
            self.lista.controls.append(self._przycisk_kolejnych(reszta))

        self._wysokosc_szacowana = max(1, wysokosc)
        # Pasek wraca przy najbliższym przewinięciu — na górze listy mówi separator.
        self.kontrolka.visible = False
        self._pokaz(kolejnosc[0])
        return self._po(wynik)

    # ----- przewijanie -----
    def _pokaz(self, klucz):
        if klucz == self._biezacy:
            return
        self._biezacy = klucz
        self._tytul.value = nazwa_miesiaca(klucz)
        self._opis.value = self._opisy.get(klucz, "")

    def _przewiniete(self, e):
        if not self._offsety:
            return
        try:
            calosc = (getattr(e, "max_scroll_extent", 0) or 0) + (getattr(e, "viewport_dimension", 0) or 0)
            lista = self._wysokosc_realna
            # Nasze wysokości są szacowane, prawdziwą zna tylko Flutter — iloraz
            # kasuje systematyczny błąd oszacowania kart.
            if lista and calosc > 0:
                # Lista leży na dole przewijanej treści: nad nią nagłówek ekranu,
                # pod nią tylko ogon (OGON_PRZEWIJANIA).
                poczatek = max(0.0, calosc - lista - self.ogon)
                korekta = lista / self._wysokosc_szacowana
            else:
                poczatek = 0.0
                korekta = (calosc / self._wysokosc_szacowana) if calosc > 0 else 1.0
            pozycja = ((getattr(e, "pixels", 0) or 0) - poczatek) / (korekta or 1.0)

            klucz = self._offsety[0][1]
            for offset, k in self._offsety:
                if offset <= pozycja + PROG_PRZELACZENIA:
                    klucz = k
                else:
                    break

            poprzedni = (self._biezacy, self.kontrolka.visible)
            self._pokaz(klucz)
            # Pasek dopiero wtedy, gdy pierwszy separator schował się pod górną
            # krawędzią — i dopiero po pomiarze listy (bez niego nie wiadomo, gdzie jest).
            self.kontrolka.visible = bool(lista) and pozycja >= 0
            if poprzedni != (self._biezacy, self.kontrolka.visible):
                self.kontrolka.update()
        except Exception:
            log.polkniety("aktualizacja nagłówka miesiąca przy przewijaniu")


__all__ = [
    "GrupyMiesiecy",
    "MARGINES_PASKA",
    "ODMIANA_WPISOW",
    "OGON_PRZEWIJANIA",
    "PORCJA_WPISOW",
    "PrzewijanaTresc",
    "czy_po_dacie",
    "PROG_PRZELACZENIA",
    "WYSOKOSC_NAGLOWKA",
    "klucz_miesiaca",
    "lista_kart",
    "nazwa_miesiaca",
]
