"""Nagłówki miesięcy na długich listach: separator w liście i pasek nad nią.

Tankowania z trzech lat to jedna długa taśma dat. Przy dwustu wpisach nie wiadomo,
gdzie się jest, dopóki nie przeczyta się daty na karcie — a wtedy przewijanie już
poszło dalej. Separator dzieli taśmę na miesiące, a pasek NAD listą stoi w miejscu
i mówi, w którym miesiącu jest się teraz.

Skąd wiadomo, gdzie jesteśmy? `ListView.on_scroll` podaje pozycję w pikselach,
a my znamy KOLEJNOŚĆ elementów, nie ich prawdziwe wysokości — karty rosną
z treścią. Szacujemy więc wysokość listy po swojemu (tak samo jak
`dopasuj_wysokosc_listy`), a potem SKALUJEMY ten szacunek do prawdy: zdarzenie
przewijania niesie `max_scroll_extent + viewport_dimension`, czyli rzeczywistą
wysokość całej zawartości. Iloraz tych dwóch liczb kasuje systematyczny błąd
oszacowania — bez niego nagłówek rozjeżdżałby się z listą tym bardziej, im dalej
w dół.
"""

import flet as ft
import log
from date import parsuj_date
from state import MIESIACE_NAZWY

from .stale import FS, RADIUS, SPACING, formatuj_liczba
from .format import _odmiana_liczby, symbol_waluty
from .pozycja import dodaj_obsluge_przewijania
from .wyglad import tlo_karty

# Separator ma zadaną wysokość nie dla wyglądu, tylko dla rachunku: to jedyny
# element listy, którego wysokość znamy DOKŁADNIE.
WYSOKOSC_NAGLOWKA = 34

# Ile pikseli przed nagłówkiem uznajemy, że jesteśmy już w jego miesiącu —
# tyle, ile sam zajmuje. Dzięki temu pasek przełącza się dokładnie wtedy, kiedy
# separator dojeżdża do górnej krawędzi.
PROG_PRZELACZENIA = WYSOKOSC_NAGLOWKA


def klucz_miesiaca(data_tekst):
    """(rok, miesiąc) albo None, gdy daty nie da się odczytać."""
    d = parsuj_date(data_tekst)
    if d.year <= 1:
        return None
    return (d.year, d.month)


def nazwa_miesiaca(klucz):
    rok, mies = klucz
    return f"{MIESIACE_NAZWY[mies - 1]} {rok}"


def _podsumowanie(ile, suma, pokaz_kwoty):
    """„4 wpisy · 1 240 zł”. Przewijanie zamienia się wtedy w przegląd miesięcy —
    widać, który był drogi, bez wchodzenia w statystyki."""
    czesci = [f"{ile} {_odmiana_liczby(ile, 'wpis', 'wpisy', 'wpisów')}"]
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


class GrupyMiesiecy:
    """Nagłówki miesięcy dla jednej listy kart.

    Widok buduje karty jak dotąd, a zamiast dopisywać je wprost do
    `lista.controls`, oddaje je tutaj przez `ustaw()`. Ta sama metoda obsługuje
    filtrowanie wyszukiwarką — po prostu dostaje krótszą listę.
    """

    def __init__(self, page, lista, wysokosc_pozycji=175, pokaz_kwoty=True):
        self._page = page
        self.lista = lista
        self.wysokosc_pozycji = wysokosc_pozycji
        self.pokaz_kwoty = pokaz_kwoty

        self._offsety = []          # [(offset w szacowanych pikselach, klucz miesiąca)]
        self._opisy = {}            # klucz miesiąca -> podsumowanie
        self._wysokosc_szacowana = 0
        self._biezacy = None

        self._tytul = ft.Text("", size=FS["label"], weight="bold", no_wrap=True,
                              overflow=ft.TextOverflow.ELLIPSIS, expand=True)
        self._opis = ft.Text("", size=FS["caption"], color=ft.Colors.ON_SURFACE_VARIANT, no_wrap=True)
        self.kontrolka = ft.Container(
            visible=False,
            padding=ft.Padding(SPACING["md"], 6, SPACING["md"], 6),
            border_radius=RADIUS["pill"],
            bgcolor=ft.Colors.with_opacity(0.10, ft.Colors.PRIMARY),
            content=ft.Row([
                ft.Icon(ft.Icons.CALENDAR_MONTH, size=15, color=ft.Colors.PRIMARY),
                self._tytul,
                self._opis,
            ], spacing=SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )

        # Dokładamy się do `on_scroll`, a nie podmieniamy go: na tej samej liście
        # siedzi też pamięć pozycji (utils.pozycja), a przypisanie wprost
        # wyłączyłoby po cichu tego, kto dopisał się pierwszy.
        # Przy okazji odstęp zdarzeń: pasek ma nadążać za palcem, a nie dostawać
        # setki zdarzeń na sekundę.
        dodaj_obsluge_przewijania(lista, self._przewiniete)

    # ----- budowa -----
    def _naglowek(self, klucz):
        return ft.Container(
            height=WYSOKOSC_NAGLOWKA,
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
        """Wypełnia listę kartami, wstawiając separatory na granicach miesięcy.

        `pozycje`: lista słowników z kluczami `karta` (kontrolka), `data` (tekst)
        i opcjonalnie `kwota`. `grupuj=False` (np. lista posortowana po kwocie,
        a nie po dacie) wstawia same karty — miesiące nie są wtedy ciągłe i każdy
        nagłówek kłamałby.

        Zwraca listę grup `[(klucz miesiąca, [pozycje])]` w kolejności wyświetlania.
        Przydaje się listom, które rysują coś PONAD kartami i muszą wiedzieć, gdzie
        przebiegają granice — na przykład osi czasu, której linia ma się urywać na
        każdym nagłówku."""
        self.lista.controls = []
        self._offsety, self._opisy, self._biezacy = [], {}, None
        self._wysokosc_szacowana = 0

        if not pozycje:
            self.kontrolka.visible = False
            return []

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
            self.lista.controls = [p["karta"] for p in pozycje]
            self.kontrolka.visible = False
            return [(None, list(pozycje))]

        for klucz in kolejnosc:
            wpisy = grupy[klucz]
            suma = sum(float(p.get("kwota") or 0) for p in wpisy)
            self._opisy[klucz] = _podsumowanie(len(wpisy), suma, self.pokaz_kwoty)

        # Jeden miesiąc to jeden separator na samej górze — pasek mówi wtedy
        # dokładnie to samo, więc separator byłby powtórzeniem.
        z_naglowkami = len(kolejnosc) > 1
        odstep = getattr(self.lista, "spacing", 0) or 0
        wysokosc = 0

        for klucz in kolejnosc:
            if z_naglowkami:
                self._offsety.append((wysokosc, klucz))
                self.lista.controls.append(self._naglowek(klucz))
                wysokosc += WYSOKOSC_NAGLOWKA + odstep
            else:
                self._offsety.append((wysokosc, klucz))
            for p in grupy[klucz]:
                self.lista.controls.append(p["karta"])
                wysokosc += self.wysokosc_pozycji + odstep

        # Pozycje bez czytelnej daty i tak muszą trafić na listę — inaczej
        # wyszukiwarka „gubiłaby” wpisy, których nie widać po niczyjej winie.
        bez_daty = [p["karta"] for p in pozycje if klucz_miesiaca(p.get("data")) is None]
        self.lista.controls.extend(bez_daty)
        wysokosc += len(bez_daty) * (self.wysokosc_pozycji + odstep)

        self._wysokosc_szacowana = max(1, wysokosc)
        self.kontrolka.visible = True
        self._pokaz(kolejnosc[0])

        wynik = [(klucz, grupy[klucz]) for klucz in kolejnosc]
        if bez_daty:
            wynik.append((None, [p for p in pozycje if klucz_miesiaca(p.get("data")) is None]))
        return wynik

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
            realna = (e.max_scroll_extent or 0) + (e.viewport_dimension or 0)
            # Nasze wysokości są szacowane, prawdziwą zna tylko Flutter — iloraz
            # kasuje systematyczny błąd oszacowania kart.
            korekta = (realna / self._wysokosc_szacowana) if realna > 0 else 1.0
            pozycja = (e.pixels or 0) / (korekta or 1.0)

            klucz = self._offsety[0][1]
            for offset, k in self._offsety:
                if offset <= pozycja + PROG_PRZELACZENIA:
                    klucz = k
                else:
                    break

            poprzedni = self._biezacy
            self._pokaz(klucz)
            if poprzedni != self._biezacy:
                self.kontrolka.update()
        except Exception:
            log.polkniety("aktualizacja nagłówka miesiąca przy przewijaniu")


__all__ = [
    "GrupyMiesiecy",
    "czy_po_dacie",
    "PROG_PRZELACZENIA",
    "WYSOKOSC_NAGLOWKA",
    "klucz_miesiaca",
    "nazwa_miesiaca",
]
