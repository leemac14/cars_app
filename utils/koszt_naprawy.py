"""Robocizna i części: pola kosztu w formularzu wizyty i wpisu serwisowego,
dopiski na kartach list i karta w Analizie.

Jedna kwota nie odpowiada na pytanie, czy drogi jest warsztat, czy części —
a od tego zależy, czy szukać innego mechanika, czy kupować części samemu.
Dlatego dwa pola zamiast jednego, a przełącznik zostawia jedną kwotę dla
rachunku bez podziału i dla wpisów sprzed tej zmiany, dopóki ktoś ich nie
rozbije. W bazie ląduje koszt całkowity i robocizna (NULL = bez podziału);
części to reszta, więc rozbicie zawsze się sumuje (patrz db.rozbicie_kosztu).
"""

import db
import flet as ft
import log

from .stale import FS, SPACING, formatuj_liczba
from .format import _odmiana_liczby, parsuj_float, symbol_waluty
from .typografia import KOLOR_DRUGIEGO_PLANU, podpis
from .wyglad import powierzchnia, tlo_toru
from .zgodnosc import ustaw_blad
from .formularze import styl_pola
from .magazyn import koszt_bez_czesci_do_pola, liczba_do_pola


# Wartości filtra „Podział” na listach wizyt i wpisów. Naprawa, przy której
# nie ma czego dzielić (koszt zero), nie ma żadnej — widać ją tylko pod
# „Wszystko”, bo ani nie czeka na rozbicie, ani nic nie wnosi do porównania.
PODZIAL_TAK = "Z podziałem"
PODZIAL_NIE = "Bez podziału"


def etykieta_podzialu(rozbicie):
    """Wartość filtra „Podział” dla rozbicia z db.rozbicie_kosztu."""
    if not rozbicie or rozbicie["razem"] <= 0:
        return ""
    return PODZIAL_TAK if rozbicie["podzielony"] else PODZIAL_NIE


def opis_rozbicia_kosztu(rozbicie):
    """„Robocizna 300,00 zł · części 650,00 zł (w tym własne 200,00 zł)” —
    dopisek na kartach wizyt i wpisów. Części razem z magazynem, żeby obie
    kwoty sumowały się do kwoty karty. Naprawa bez podziału mówi to wprost,
    a taka, przy której nie ma czego dzielić, nie mówi nic."""
    if not rozbicie or rozbicie["razem"] <= 0:
        return ""
    if not rozbicie["podzielony"]:
        return "Bez podziału na robociznę i części"
    w = symbol_waluty()
    tekst = (f"Robocizna {formatuj_liczba(rozbicie['robocizna'])} {w} · "
             f"części {formatuj_liczba(rozbicie['czesci'] + rozbicie['z_magazynu'])} {w}")
    if rozbicie["z_magazynu"] > 0:
        tekst += f" (w tym własne {formatuj_liczba(rozbicie['z_magazynu'])} {w})"
    return tekst


def dopisek_rozbicia(rozbicie):
    """Kontrolka z `opis_rozbicia_kosztu` do karty listy albo None. „Bez
    podziału” pochyłym — to brak w danych, a nie ich treść."""
    tekst = opis_rozbicia_kosztu(rozbicie)
    if not tekst:
        return None
    return podpis(tekst, italic=not rozbicie["podzielony"])


# Serie karty „Robocizna czy części”. Kolor odróżnia składnik od składnika,
# a nie stan od stanu — dlatego żaden z odcieni palety statusów.
SERIE_ROZBICIA = (
    ("robocizna", "Robocizna", ft.Icons.HANDYMAN, ft.Colors.INDIGO_400),  # paleta: tożsamość — seria wykresu
    ("czesci", "Części na rachunku", ft.Icons.RECEIPT_LONG, ft.Colors.DEEP_ORANGE_400),  # paleta: tożsamość — seria wykresu
    ("z_magazynu", "Części z magazynu", ft.Icons.INVENTORY_2, ft.Colors.TEAL_600),  # paleta: tożsamość — seria wykresu
)


def _napraw(n):
    return f"{n} {_odmiana_liczby(n, 'naprawa', 'naprawy', 'napraw')}"


def karta_robocizny_i_czesci(page: ft.Page, rozbicie, porownania=(), scena=None):
    """Karta Analizy: ile z kosztu napraw to robocizna, ile części na rachunku,
    a ile części z własnego magazynu (db.pobierz_rozbicie_napraw), pod spodem
    warsztaty i podzespoły z częściami raz z warsztatu, raz z magazynu
    (db.porownaj_czesci_wlasne). Paski idą przez `scena` jak reszta zakładki.

    Naprawy bez podziału stoją osobnym zdaniem, nie paskiem: ich kwoty nie da
    się przypisać do żadnego składnika, a w pasku „inne” zlałyby się z tym,
    o co tu pytamy."""
    w = symbol_waluty()
    wiersze = []
    razem = rozbicie["razem"]

    if not rozbicie["napraw"]:
        tekst = ("Żadna naprawa z tego okresu nie ma podziału na robociznę i części. Rozbij je "
                 "w edycji wizyty albo wpisu — na liście wizyt znajdzie je filtr „Podział”."
                 if rozbicie["bez_podzialu"] else "Brak napraw w wybranym okresie.")
        wiersze.append(ft.Text(tekst, size=FS["body"], italic=True, color=KOLOR_DRUGIEGO_PLANU))
    else:
        for klucz, tytul, ikona, kolor in SERIE_ROZBICIA:
            kwota = rozbicie[klucz]
            if klucz == "z_magazynu" and kwota <= 0:
                continue
            procent = kwota / razem * 100 if razem > 0 else 0.0
            tor = ft.ProgressBar(value=procent / 100 if procent > 0 else 0, color=kolor,
                                 bgcolor=tlo_toru(page), height=6, border_radius=3)
            if scena is not None:
                scena.nastepny_wiersz()
                tor = scena.wskaznik(tor)
            wiersze.append(ft.Column([
                ft.Row([
                    ft.Row([
                        ft.Icon(ikona, size=15, color=kolor),
                        ft.Text(tytul, weight="bold", size=13, color=ft.Colors.ON_SURFACE,
                                no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS, expand=True),
                    ], spacing=6, expand=True),
                    ft.Text(f"{formatuj_liczba(kwota)} {w} ({formatuj_liczba(procent, 0)}%)",
                            weight="bold", size=13, color=kolor, no_wrap=True),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                tor,
            ], spacing=3))
        opis = f"Naprawy z podziałem: {rozbicie['napraw']}"
        if rozbicie["bez_podzialu"]:
            opis += (f" · bez podziału: {rozbicie['bez_podzialu']} na "
                     f"{formatuj_liczba(rozbicie['kwota_bez_podzialu'])} {w}, poza porównaniem")
        wiersze.append(podpis(opis))

    if rozbicie["warsztaty"]:
        wiersze.append(ft.Text("Warsztaty", weight="bold", size=FS["body"], color=ft.Colors.ON_SURFACE))
        for warsztat in rozbicie["warsztaty"]:
            wiersze.append(ft.Column([
                ft.Text(warsztat["nazwa"], size=FS["body"], color=ft.Colors.ON_SURFACE,
                        no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                podpis(f"{_napraw(warsztat['napraw'])} · robocizna średnio "
                       f"{formatuj_liczba(warsztat['srednia_robocizna'])} {w} · "
                       f"{formatuj_liczba(warsztat['udzial_robocizny'], 0)}% rachunku"),
            ], spacing=1))

    if porownania:
        wiersze.append(ft.Text("Części z warsztatu a z magazynu", weight="bold", size=FS["body"],
                               color=ft.Colors.ON_SURFACE))
        for p in porownania:
            wiersze.append(ft.Column([
                ft.Text(p["nazwa"], size=FS["body"], color=ft.Colors.ON_SURFACE,
                        no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                podpis(f"z warsztatu średnio {formatuj_liczba(p['z_warsztatu'])} {w} "
                       f"({p['ile_z_warsztatu']}×) · z magazynu {formatuj_liczba(p['wlasne'])} {w} "
                       f"({p['ile_wlasnych']}×)"),
            ], spacing=1))

    return ft.Container(
        padding=SPACING["lg"],
        **powierzchnia(page, "karta", cien="md"),
        content=ft.Column(wiersze, spacing=12),
    )


def _kwota_do_pola(kwota):
    """Zero daje puste pole — tak jak w dotychczasowym polu kosztu."""
    return liczba_do_pola(kwota) if kwota else ""


class KosztNaprawy:
    """Pola kosztu naprawy razem z linijką podsumowania.

    `koszt`, `robocizna` i `doliczone` opisują zapisany rekord (przy edycji)
    albo źródło duplikatu: koszt całkowity, zapisaną robociznę (None = bez
    podziału) i to, co z kosztu przyszło z magazynu. Nowy rekord przychodzi
    bez nich i od razu dostaje podział. Rekord bez podziału otwiera się jedną
    kwotą — przełączenie przenosi ją do części, a wpisywana robocizna schodzi
    z niej, dopóki ktoś nie poprawi części ręcznie. Dzięki temu rozbicie
    starej wizyty to wpisanie jednej liczby, a nie przepisywanie dwóch.

    Formularz wstawia `kontrolki()`, do wykrywania zmian bierze `migawka()`,
    a przy zapisie woła `sprawdz()`."""

    def __init__(self, page: ft.Page, zuzycie=None, koszt=None, robocizna=None, doliczone=0.0,
                 etykieta_kwoty="Całkowity koszt naprawy"):
        self._page = page
        self._zuzycie = zuzycie
        self._waluta = symbol_waluty()
        self._do_podzialu = None
        self._czesci_recznie = False

        rozbicie = db.rozbicie_kosztu(koszt, robocizna, doliczone)
        podzial = koszt is None or rozbicie["podzielony"]

        self.przelacznik = ft.Switch(
            label="Osobno robocizna i części", value=podzial,
            on_change=lambda e: self.przelacz(bool(self.przelacznik.value)),
        )
        self.e_robocizna = ft.TextField(
            label=f"Robocizna ({self._waluta})",
            value=_kwota_do_pola(rozbicie["robocizna"]) if podzial else "",
            keyboard_type=ft.KeyboardType.NUMBER, expand=1,
            on_change=lambda e: self._zmiana_robocizny(),
            **styl_pola(page=page)
        )
        self.e_czesci = ft.TextField(
            label=f"Części ({self._waluta})",
            value=_kwota_do_pola(rozbicie["czesci"]) if podzial else "",
            keyboard_type=ft.KeyboardType.NUMBER, expand=1,
            on_change=lambda e: self._zmiana_czesci(),
            **styl_pola(page=page)
        )
        self.wiersz_podzialu = ft.Row([self.e_robocizna, self.e_czesci], spacing=10, visible=podzial)
        self.e_kwota = ft.TextField(
            label=f"{etykieta_kwoty} ({self._waluta})",
            value="" if podzial else koszt_bez_czesci_do_pola(koszt, doliczone),
            keyboard_type=ft.KeyboardType.NUMBER, visible=not podzial,
            on_change=lambda e: self._odswiez(odswiez_strone=True),
            **styl_pola(page=page)
        )
        self.podsumowanie = ft.Text("", size=FS["label"], color=KOLOR_DRUGIEGO_PLANU, visible=False)

        if zuzycie is not None:
            zuzycie.przy_zmianie(self._odswiez)
        self._odswiez()

    # ------------------------------------------------------------ dla formularza

    def kontrolki(self):
        return [self.przelacznik, self.wiersz_podzialu, self.e_kwota, self.podsumowanie]

    def czy_podzial(self):
        return bool(self.przelacznik.value)

    def migawka(self):
        """Stan do wykrywania niezapisanych zmian — po wartościach, nie po
        tekście pól: przełączenie w tę i z powrotem nie jest zmianą."""
        if self.czy_podzial():
            return ("podział", self._liczba(self.e_robocizna), self._liczba(self.e_czesci))
        return ("kwota", self._liczba(self.e_kwota))

    def sprawdz(self):
        """(kwota bez części z magazynu, robocizna albo None, błędy) — błędy
        w kształcie utils.pokaz_bledy_formularza."""
        for pole in (self.e_robocizna, self.e_czesci, self.e_kwota):
            ustaw_blad(pole)
        pola = (self.e_robocizna, self.e_czesci) if self.czy_podzial() else (self.e_kwota,)
        bledy = [(pole, "Kwota nie może być ujemna") for pole in pola
                 if (parsuj_float(pole.value, 0.0) or 0.0) < 0]
        if self.czy_podzial():
            robocizna, czesci = self._liczba(self.e_robocizna), self._liczba(self.e_czesci)
            return round(robocizna + czesci, 2), round(robocizna, 2), bledy
        return round(self._liczba(self.e_kwota), 2), None, bledy

    def przelacz(self, podzial):
        """Podział albo jedna kwota — bez gubienia tego, co już wpisane."""
        self.przelacznik.value = bool(podzial)
        if podzial:
            kwota = self._liczba(self.e_kwota)
            self._do_podzialu = kwota if kwota > 0 else None
            self._czesci_recznie = False
            self.e_robocizna.value = ""
            self.e_czesci.value = _kwota_do_pola(kwota)
        else:
            self.e_kwota.value = _kwota_do_pola(round(self._liczba(self.e_robocizna) + self._liczba(self.e_czesci), 2))
            self._do_podzialu = None
        for pole in (self.e_robocizna, self.e_czesci, self.e_kwota):
            ustaw_blad(pole)
        self.wiersz_podzialu.visible = bool(podzial)
        self.e_kwota.visible = not podzial
        self._odswiez(odswiez_strone=True)

    # ------------------------------------------------------------ środek

    @staticmethod
    def _liczba(pole):
        return max(0.0, parsuj_float(pole.value, 0.0) or 0.0)

    def _zmiana_robocizny(self):
        if self._do_podzialu is not None and not self._czesci_recznie:
            reszta = max(0.0, round(self._do_podzialu - self._liczba(self.e_robocizna), 2))
            self.e_czesci.value = _kwota_do_pola(reszta)
        self._odswiez(odswiez_strone=True)

    def _zmiana_czesci(self):
        self._czesci_recznie = True
        self._odswiez(odswiez_strone=True)

    def _odswiez(self, odswiez_strone=False):
        w = self._waluta
        z_magazynu = self._zuzycie.koszt() if self._zuzycie is not None else 0.0
        if self.czy_podzial():
            robocizna, czesci = self._liczba(self.e_robocizna), self._liczba(self.e_czesci)
            wlasne = robocizna + czesci
            # Przy samych dwóch polach „razem” mówi coś dopiero, gdy oba są
            # wypełnione — przy jednym powtarzałoby tę samą liczbę.
            tekst = (f"Razem {formatuj_liczba(wlasne)} {w}"
                     if robocizna > 0 and czesci > 0 and z_magazynu <= 0 else "")
        else:
            wlasne = self._liczba(self.e_kwota)
            tekst = ""
        if z_magazynu > 0:
            tekst = (f"+ części z magazynu {formatuj_liczba(z_magazynu)} {w}"
                     f" = razem {formatuj_liczba(wlasne + z_magazynu)} {w}")
        self.podsumowanie.value = tekst
        self.podsumowanie.visible = bool(tekst)
        if odswiez_strone:
            self._odswiez_strone()

    def _odswiez_strone(self):
        try:
            self._page.update()
        except Exception:
            log.polkniety("odświeżenie pól kosztu naprawy")


__all__ = [
    "KosztNaprawy",
    "PODZIAL_NIE",
    "PODZIAL_TAK",
    "SERIE_ROZBICIA",
    "_kwota_do_pola",
    "_napraw",
    "dopisek_rozbicia",
    "etykieta_podzialu",
    "karta_robocizny_i_czesci",
    "opis_rozbicia_kosztu",
]
