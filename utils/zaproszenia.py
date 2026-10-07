"""Zaproszenie do współdzielonego pojazdu: QR z linkiem carsapp://app/dolacz/<KOD>
(`sync.link_zaproszenia`) otwiera aplikację na ekranie dołączania z wpisanym kodem
(dołącza dopiero „Dołącz”), zaproszenie wysłane dalej i kod wklejony ze schowka. Kod
stoi też pod QR."""

import flet as ft

import db
import log
import sync

from .stale import FS, KOLOR_STATUS, RADIUS, SPACING
from .typografia import podpis
from .dialogi import otworz_dialog, pokaz_komunikat, zamknij_dialog
from .sync_ui import KOLORY_ROL
from .system import kopiuj_do_schowka, odczytaj_schowek, udostepnij_tekst, ustaw_jasnosc_kodu
from .komponenty import segmented_control
from .kod_qr import obraz_qr_png


# Kolejność ma znaczenie: od najszerszych uprawnień do najwęższych, żeby
# rozdający kod czytał listę jak zjazd w dół, a nie losowy zbiór opcji.
OPIS_KODOW = [
    ("pelny", db.ROLA_PELNA, ft.Icons.KEY,
     "Robi wszystko to, co Ty: dodaje, poprawia i kasuje dowolny wpis. Dla drugiego właściciela auta."),
    ("wspolautor", db.ROLA_WSPOLAUTOR, ft.Icons.EDIT_NOTE,
     "Dopisuje własne tankowania i wpisy, poprawia to, co sam dodał. Cudzych nie ruszy. Dla kogoś, kto jeździ autem na co dzień."),
    ("podglad", db.ROLA_PODGLAD, ft.Icons.VISIBILITY,
     "Widzi całą historię, nie zmienia niczego. Nic z jego telefonu nie trafia do chmury. Dla kupującego, warsztatu, rodzica."),
]

# Podpisy segmentów przełącznika — pełne nazwy ról nie mieszczą się w trzech.
SKROTY_KODOW = {"pelny": "Pełny", "wspolautor": "Współautor", "podglad": "Podgląd"}

# Bok kodu na ekranie. Aparat z odległości ręki czyta go bez przybliżania,
# a okno mieści się na najwęższym telefonie.
BOK_KODU_QR = 232
SZEROKOSC_OKNA_QR = BOK_KODU_QR + 2 * SPACING["md"]


def tekst_zaproszenia(nazwa_pojazdu, rola, kod):
    """Wiadomość na SMS albo komunikator. Link otworzy aplikację tam, gdzie
    komunikator go podświetli; reszta mówi, co zrobić, gdy nie podświetli."""
    rodzaj = db.ETYKIETY_ROL.get(rola, rola).lower()
    return (
        f"Zaproszenie do pojazdu „{nazwa_pojazdu}” ({rodzaj}):\n"
        f"{sync.link_zaproszenia(kod)}\n\n"
        f"Link się nie otwiera? Skopiuj tę wiadomość, otwórz w aplikacji ekran "
        f"„Współdziel pojazd” i dotknij „Wklej” — albo wpisz kod {kod}."
    )


class OknoKoduQR:
    """Kod QR do zeskanowania drugim telefonem. Przełącznik ról u góry zmienia
    kod bez zamykania okna, a ekran świeci pełną jasnością, dopóki okno jest
    otwarte. Pod kodem: sam kod (dla aparatu, który linku nie otworzy) i link."""

    def __init__(self, page: ft.Page, kody, nazwa_pojazdu, klucz="pelny"):
        self._page = page
        self.kody = kody
        self.nazwa_pojazdu = nazwa_pojazdu or "pojazd"
        self.dostepne = [(k, rola) for k, rola, _ikona, _opis in OPIS_KODOW if kody.get(k)]
        if not self.dostepne:
            raise ValueError("Ten pojazd nie ma jeszcze kodu zaproszenia.")
        klucze = [k for k, _ in self.dostepne]
        self.klucz = klucz if klucz in klucze else klucze[0]
        self._obrazy = {}
        self._jasno = False

        self.przelacznik = ft.Container(width=SZEROKOSC_OKNA_QR)
        self.ikona_roli = ft.Icon(ft.Icons.KEY, size=18)
        self.t_rola = ft.Text("", size=FS["body_strong"], weight="bold")
        self.t_opis = podpis("", text_align=ft.TextAlign.CENTER)
        self.obraz = ft.Image(
            src=b"", width=BOK_KODU_QR, height=BOK_KODU_QR, fit=ft.BoxFit.CONTAIN,
            # Bez wygładzania: brzegi modułów zostają ostre po przeskalowaniu.
            filter_quality=ft.FilterQuality.NONE, semantics_label="Kod QR zaproszenia",
        )
        self.t_kod = ft.Text("", size=FS["display"], weight="bold", selectable=True,
                             style=ft.TextStyle(letter_spacing=4))
        self.t_link = podpis("", selectable=True, text_align=ft.TextAlign.CENTER)

        tresc = ft.Column([
            self.przelacznik,
            ft.Row([self.ikona_roli, self.t_rola], spacing=6, tight=True,
                   alignment=ft.MainAxisAlignment.CENTER),
            self.t_opis,
            ft.Container(
                # Białe tło także w ciemnym motywie: kod musi być ciemny na jasnym.
                bgcolor=ft.Colors.WHITE, border_radius=RADIUS["md"], padding=SPACING["xs"],
                content=self.obraz,
            ),
            self.t_kod,
            self.t_link,
            podpis("Na drugim telefonie otwórz aparat i nakieruj go na kod — aplikacja otworzy się "
                   "z wpisanym kodem. Aparat pokazał sam tekst? Skopiuj go i dotknij „Wklej” "
                   "na ekranie „Współdziel pojazd”.", text_align=ft.TextAlign.CENTER),
        ], tight=True, spacing=SPACING["sm"], horizontal_alignment=ft.CrossAxisAlignment.CENTER)

        self.dlg = ft.AlertDialog(
            modal=False, scrollable=True, on_dismiss=self._po_zamknieciu,
            inset_padding=ft.Padding.symmetric(horizontal=SPACING["md"], vertical=SPACING["lg"]),
            title=ft.Row([
                ft.Icon(ft.Icons.QR_CODE_2, color=ft.Colors.PRIMARY),
                ft.Text("Zeskanuj drugim telefonem", weight="bold", expand=True),
                ft.IconButton(ft.Icons.CLOSE, tooltip="Zamknij", on_click=self.zamknij),
            ], spacing=8),
            content=ft.Container(width=SZEROKOSC_OKNA_QR, content=tresc),
            actions=[
                ft.TextButton("Kopiuj link", icon=ft.Icons.COPY, on_click=self._kopiuj_link),
                ft.Button("Udostępnij", icon=ft.Icons.SHARE, on_click=self._udostepnij,
                          bgcolor=ft.Colors.PRIMARY, color=ft.Colors.ON_PRIMARY),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self._wypelnij()

    # ------------------------------------------------------------ STAN
    @property
    def rola(self):
        return dict(self.dostepne)[self.klucz]

    @property
    def kod(self):
        return self.kody[self.klucz]

    def _png(self, kod):
        if kod not in self._obrazy:
            self._obrazy[kod] = obraz_qr_png(sync.link_zaproszenia(kod), skala=12)
        return self._obrazy[kod]

    def _wypelnij(self):
        kolor = KOLORY_ROL.get(self.rola, ft.Colors.PRIMARY)
        ikona, opis = next((i, o) for k, _r, i, o in OPIS_KODOW if k == self.klucz)
        if len(self.dostepne) > 1:
            klucze = [k for k, _ in self.dostepne]
            self.przelacznik.content = segmented_control(
                self._page, [(SKROTY_KODOW[k], i) for i, k in enumerate(klucze)],
                klucze.index(self.klucz), self.zmien_role,
            )
        self.ikona_roli.icon = ikona
        self.ikona_roli.color = kolor
        self.t_rola.value = db.ETYKIETY_ROL.get(self.rola, self.rola)
        self.t_rola.color = kolor
        self.t_opis.value = opis
        self.obraz.src = self._png(self.kod)
        self.t_kod.value = self.kod
        self.t_link.value = sync.link_zaproszenia(self.kod)

    # ------------------------------------------------------------ AKCJE
    def otworz(self):
        otworz_dialog(self._page, self.dlg)
        self._jasno = True
        ustaw_jasnosc_kodu(self._page, True)

    def zamknij(self, e=None):
        zamknij_dialog(self._page, self.dlg)
        self._po_zamknieciu()

    def _po_zamknieciu(self, e=None):
        # Zamknięcie przyciskiem i on_dismiss potrafią przyjść oba — jasność
        # oddajemy raz.
        if self._jasno:
            self._jasno = False
            ustaw_jasnosc_kodu(self._page, False)

    def zmien_role(self, indeks):
        self.klucz = self.dostepne[indeks][0]
        self._wypelnij()
        try:
            self._page.update()
        except Exception:
            log.polkniety("zmiana roli w oknie kodu QR")

    def _kopiuj_link(self, e):
        kopiuj_do_schowka(self._page, sync.link_zaproszenia(self.kod), "Skopiowano link zaproszenia")

    def _udostepnij(self, e):
        udostepnij_tekst(
            self._page, tekst_zaproszenia(self.nazwa_pojazdu, self.rola, self.kod),
            temat=f"Zaproszenie do pojazdu „{self.nazwa_pojazdu}”",
            komunikat_awaryjny="Zaproszenie skopiowane — wklej je w SMS-ie albo komunikatorze",
        )


def pokaz_kod_qr(page: ft.Page, kody, nazwa_pojazdu, klucz="pelny"):
    """Otwiera okno z kodem QR roli `klucz` („pelny”, „wspolautor”, „podglad”)."""
    okno = OknoKoduQR(page, kody, nazwa_pojazdu, klucz)
    okno.otworz()
    return okno


def wklej_kod_zaproszenia(page: ft.Page, pole, po_wklejeniu=None):
    """„Wklej” przy polu kodu: kod ze schowka — z samego kodu, linku albo
    całego zaproszenia z SMS-a. Pole zmienia się tylko, gdy w schowku naprawdę
    jest kod; `po_wklejeniu(kod)` dostaje go po wpisaniu."""
    async def _zadanie():
        kod = sync.kod_z_zaproszenia(await odczytaj_schowek(page))
        if not kod:
            pokaz_komunikat(page, "W schowku nie ma kodu ani linku zaproszenia.", KOLOR_STATUS["warning"])
            return
        pole.value = kod
        if callable(po_wklejeniu):
            po_wklejeniu(kod)
        try:
            page.update()
        except Exception:
            log.polkniety("wklejenie kodu zaproszenia")

    page.run_task(_zadanie)


__all__ = [
    "BOK_KODU_QR",
    "OPIS_KODOW",
    "OknoKoduQR",
    "SKROTY_KODOW",
    "SZEROKOSC_OKNA_QR",
    "pokaz_kod_qr",
    "tekst_zaproszenia",
    "wklej_kod_zaproszenia",
]
