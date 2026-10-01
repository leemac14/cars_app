"""Kolejka „do wpisania” po stronie interfejsu: migawka, galeria, baner, pola.

Dane i zapis — db/szkice.py. Ekrany — views/migawka_view.py (aparat)
i views/do_wpisania_view.py (kolejka). Formularze tankowania, kosztu i wizyty
przyjmują `szkic_id` i stawiają na górze `pasek_szkicu`."""

import asyncio

import flet as ft

import db
import log

from .stale import FS, KOLOR_STATUS, RADIUS, SPACING
from .format import formatuj_dni, formatuj_dystans, jednostka_dystansu, parsuj_int
from .typografia import podpis, wartosc
from .wyglad import powierzchnia
from .dialogi import otworz_dialog, pokaz_komunikat, przejdz, zamknij_dialog
from .formularze import styl_pola
from .zalaczniki import abs_zalacznik, pokaz_podglad_zalacznika
from .komponenty import segmented_control


# Dokąd prowadzi szkic danego rodzaju — formularz dostaje id szkicu w trasie,
# więc przebudowa stosu widoków (router robi ją przy każdym przejściu) go nie gubi.
TRASY_FORMULARZY_SZKICU = {
    "tankowanie": "/tankowanie/nowe",
    "koszt": "/inne/nowy",
    "wizyta": "/wizyty/nowa",
}

IKONY_RODZAJU_SZKICU = {
    "tankowanie": ft.Icons.LOCAL_GAS_STATION,
    "koszt": ft.Icons.RECEIPT_LONG,
    "wizyta": ft.Icons.HOME_REPAIR_SERVICE,
}

# Tylko zdjęcia: jedno zdjęcie = jeden paragon = jeden szkic.
ROZSZERZENIA_ZDJEC_SZKICU = ["jpg", "jpeg", "png", "webp"]


def trasa_uzupelnienia(rodzaj, szkic_id):
    """„/tankowanie/nowe/szkic/12” — formularz rodzaju z podpiętym szkicem."""
    return f"{TRASY_FORMULARZY_SZKICU.get(rodzaj, TRASY_FORMULARZY_SZKICU['koszt'])}/szkic/{szkic_id}"


def szkic_z_trasy(segmenty):
    """Id szkicu z trasy formularza („…/nowe/szkic/12”) albo None."""
    if len(segmenty) >= 4 and segmenty[2] == "szkic":
        return parsuj_int(segmenty[3], None)
    return None


def szkic_do_formularza(state, szkic_id, rekord_id=None):
    """Szkic, który ma wypełnić NOWY wpis — tylko z bieżącego pojazdu (kolejka
    pokazuje szkice auta, przy którym się jest). Edycja istniejącego wpisu
    i szkic już wpisany (inna karta, drugi zapis) dają None: formularz
    otwiera się wtedy zwyczajnie."""
    if not szkic_id or rekord_id:
        return None
    szkic = db.pobierz_szkic(szkic_id)
    if not szkic or szkic["auto_id"] != getattr(state, "auto_id", None):
        return None
    return szkic


def trasa_po_zapisie_szkicu(auto_id, domyslna):
    """Po wpisaniu szkicu wracamy do kolejki, dopóki coś w niej czeka — wieczorne
    wpisywanie trzech paragonów to trzy formularze pod rząd, nie trzy wycieczki
    przez kokpit. Pusta kolejka oddaje zwykły powrót formularza."""
    return "/do-wpisania" if db.podsumowanie_szkicow(auto_id)["liczba"] else domyslna


def dopisek_kolejki(auto_id):
    """„ Do wpisania: 2 paragony.” — dopisek do komunikatu po zapisie wpisu."""
    ile = db.podsumowanie_szkicow(auto_id)["liczba"]
    if not ile:
        return " Kolejka paragonów jest pusta."
    return f" Do wpisania: {db.liczba_z_odmiana(ile, 'paragon', 'paragony', 'paragonów')}."


def etykieta_rodzaju_szkicu(rodzaj, auto_id=None, krotka=False):
    """Nazwa rodzaju na przycisku. Elektryk nie tankuje, tylko ładuje."""
    if rodzaj == "tankowanie":
        return "Ładowanie" if auto_id and db.czy_pojazd_elektryczny(auto_id) else "Tankowanie"
    if krotka:
        return {"koszt": "Koszt", "wizyta": "Wizyta"}.get(rodzaj, "")
    return db.RODZAJE_SZKICU.get(rodzaj, "")


def wiek_szkicu(dni):
    """„dziś”, „wczoraj”, „3 dni temu”."""
    if dni <= 0:
        return "dziś"
    if dni == 1:
        return "wczoraj"
    return f"{formatuj_dni(dni)} temu"


def opis_szkicu(szkic, auto_id=None):
    """Druga linia karty szkicu: rodzaj · licznik · opis — tylko to, co jest."""
    czesci = []
    if szkic.get("rodzaj"):
        czesci.append(etykieta_rodzaju_szkicu(szkic["rodzaj"], auto_id))
    if szkic.get("przebieg"):
        czesci.append(formatuj_dystans(szkic["przebieg"]))
    if szkic.get("opis"):
        czesci.append(szkic["opis"])
    return " · ".join(czesci)


# ---------------------------------------------------------------------------
#  Skąd się bierze szkic: aparat albo galeria
# ---------------------------------------------------------------------------

def aparat_dostepny(page: ft.Page) -> bool:
    """Aparat w aplikacji (flet-camera) działa na Androidzie i iOS. Na komputerze
    kontrolka rzuca wyjątek już przy pierwszej aktualizacji, więc tam jej
    w ogóle nie budujemy — paragon przychodzi z pliku."""
    try:
        import flet_camera  # noqa: F401 — sprawdzamy tylko, czy paczka jest
    except ImportError:
        return False
    return getattr(page, "platform", None) in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS)


def _wolno_dodac_szkic(page, state):
    if not getattr(state, "auto_id", None):
        pokaz_komunikat(page, "Najpierw dodaj pojazd — szkic należy do auta.", KOLOR_STATUS["warning"])
        return False
    if not db.czy_moge_dodawac(state.auto_id):
        pokaz_komunikat(page, "Ten pojazd masz w trybie tylko do odczytu — paragonów tu nie dopiszesz.",
                        KOLOR_STATUS["warning"])
        return False
    return True


def otworz_migawke(page: ft.Page, state):
    """Jedno dotknięcie z kokpitu albo z FAB-a: aparat na telefonie, wybór
    zdjęć z dysku na komputerze."""
    if not _wolno_dodac_szkic(page, state):
        return
    if aparat_dostepny(page):
        przejdz(page, "/paragon")
    else:
        wybierz_z_galerii(page, state, po_dodaniu=lambda: przejdz(page, "/do-wpisania"))


def komunikat_dodania(page, auto_id, dodane):
    ile = db.liczba_z_odmiana(dodane, "paragon", "paragony", "paragonów")
    w_kolejce = db.podsumowanie_szkicow(auto_id)["liczba"]
    pokaz_komunikat(page, f"Dodano {ile} do wpisania · w kolejce: {w_kolejce}")


def wybierz_z_galerii(page: ft.Page, state, po_dodaniu=None):
    """Zdjęcia paragonów zrobione wcześniej systemowym aparatem — kilka naraz,
    każde osobnym szkicem z datą ze zdjęcia (EXIF), nie z chwili wyboru."""
    if not _wolno_dodac_szkic(page, state):
        return
    auto_id = state.auto_id
    obsluzono = {"wartosc": False}

    async def dodaj(pliki):
        sciezki = [p.path for p in (pliki or []) if getattr(p, "path", None)]
        if not sciezki:
            if pliki:
                pokaz_komunikat(page, "Brak dostępu do ścieżki (Uprawnienia telefonu).", KOLOR_STATUS["error"])
            return
        # Zmniejszanie zdjęć to praca dla Pillow — poza wątkiem interfejsu.
        dodane = await asyncio.to_thread(db.dodaj_szkice_z_plikow, auto_id, sciezki)
        if not dodane:
            pokaz_komunikat(page, "Nie udało się odczytać wybranych zdjęć.", KOLOR_STATUS["error"])
            return
        komunikat_dodania(page, auto_id, dodane)
        if po_dodaniu:
            po_dodaniu()

    def po_wyborze(e):
        if obsluzono["wartosc"]:
            return
        obsluzono["wartosc"] = True
        page.run_task(dodaj, getattr(e, "files", None))

    async def wybierz():
        page.zalacznik_picker.on_result = po_wyborze
        page.zalacznik_picker.update()
        try:
            wynik = await page.zalacznik_picker.pick_files(
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=ROZSZERZENIA_ZDJEC_SZKICU,
                allow_multiple=True,
            )
        except Exception as ex:
            pokaz_komunikat(page, f"Błąd wczytywania pliku: {ex}", KOLOR_STATUS["error"])
            return
        if wynik is not None and not obsluzono["wartosc"]:
            obsluzono["wartosc"] = True
            pliki = getattr(wynik, "files", wynik)
            await dodaj(pliki if isinstance(pliki, list) else None)

    page.run_task(wybierz)


# ---------------------------------------------------------------------------
#  Baner na kokpicie i pasek w formularzu
# ---------------------------------------------------------------------------

def baner_szkicow(page: ft.Page, stan, on_click):
    """„3 paragony do wpisania” nad kafelkami kokpitu. Po DNI_PRZYPOMNIENIA_SZKICU
    dniach kolor przechodzi w ostrzeżenie — tak samo, jak odzywa się dzwonek."""
    ile = db.liczba_z_odmiana(stan["liczba"], "paragon", "paragony", "paragonów")
    stary = stan["dni"] >= db.DNI_PRZYPOMNIENIA_SZKICU
    kolor = KOLOR_STATUS["warning"] if stary else KOLOR_STATUS["info"]
    najstarszy = "" if stan["liczba"] == 1 else "najstarszy "
    return ft.Container(
        padding=ft.Padding(SPACING["md"], SPACING["sm"], SPACING["sm"], SPACING["sm"]),
        border_radius=RADIUS["lg"], bgcolor=ft.Colors.with_opacity(0.10, kolor),
        ink=True, on_click=on_click, tooltip="Otwórz kolejkę paragonów",
        content=ft.Row([
            ft.Icon(ft.Icons.PENDING_ACTIONS, size=22, color=kolor),
            ft.Column([
                wartosc(f"{ile} do wpisania", size=FS["body_strong"]),
                podpis(f"{najstarszy}z {stan['najstarszy_data']} ({wiek_szkicu(stan['dni'])}) · dotknij, żeby wpisać"),
            ], spacing=0, tight=True, expand=True),
            ft.Icon(ft.Icons.CHEVRON_RIGHT, size=20, color=ft.Colors.ON_SURFACE_VARIANT),
        ], spacing=SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.CENTER),
    )


def miniatura_szkicu(page: ft.Page, szkic, rozmiar=64):
    """Zdjęcie paragonu w ramce; dotknięcie otwiera pełny podgląd z przybliżaniem."""
    sciezka = abs_zalacznik(szkic.get("zalacznik"))
    if sciezka:
        tresc = ft.Image(src=sciezka, width=rozmiar, height=rozmiar, fit="cover", border_radius=RADIUS["sm"])
    else:
        tresc = ft.Icon(ft.Icons.NO_PHOTOGRAPHY, size=26, color=ft.Colors.ON_SURFACE_VARIANT)
    return ft.Container(
        width=rozmiar, height=rozmiar, alignment=ft.Alignment.CENTER, ink=True,
        **powierzchnia(page, "blok"),
        tooltip="Powiększ paragon", content=tresc,
        on_click=(lambda e: pokaz_podglad_zalacznika(page, szkic["zalacznik"], "Paragon")) if sciezka else None,
    )


def pasek_szkicu(page: ft.Page, szkic):
    """Nagłówek formularza otwartego ze szkicu: paragon przed oczami, bo z niego
    przepisuje się kwotę i litry."""
    kiedy = szkic["data"] + (f", {szkic['godzina']}" if szkic.get("godzina") else "")
    return ft.Container(
        padding=SPACING["md"], **powierzchnia(page, "blok"),
        content=ft.Row([
            miniatura_szkicu(page, szkic, 64),
            ft.Column([
                wartosc(f"Paragon z {kiedy}", size=FS["body_strong"]),
                podpis("Zdjęcie jest już w załączniku — dotknij miniatury, żeby je powiększyć. "
                       "Po zapisie szkic zniknie z kolejki."),
            ], spacing=2, tight=True, expand=True),
        ], spacing=SPACING["md"], vertical_alignment=ft.CrossAxisAlignment.START),
    )


# ---------------------------------------------------------------------------
#  Rodzaj, licznik, opis — po migawce i przy edycji szkicu
# ---------------------------------------------------------------------------

class PolaSzkicu:
    """Trzy opcjonalne pola szkicu. Licznik w jednostce z Ustawień, do bazy w km
    (nieruszone pole wraca bez przeliczania — patrz db.dystans_na_km)."""

    def __init__(self, page: ft.Page, auto_id, szkic=None):
        szkic = szkic or {}
        self._page = page
        self.auto_id = auto_id
        self.rodzaj = szkic.get("rodzaj")
        self.j = jednostka_dystansu()
        self._km_przy_otwarciu = szkic.get("przebieg")
        self.przelacznik = ft.Container(content=self._zbuduj_przelacznik())
        self.e_przebieg = ft.TextField(
            label=f"Stan licznika ({self.j}) — paragon go nie ma",
            value=db.wartosc_pola_dystansu(szkic["przebieg"], self.j) if szkic.get("przebieg") else "",
            keyboard_type=ft.KeyboardType.NUMBER, **styl_pola(page=page),
        )
        self.e_opis = ft.TextField(
            label="Krótki opis (np. myjnia, A4 bramki)", value=szkic.get("opis") or "",
            max_length=db.MAKS_DLUGOSC_OPISU_SZKICU, **styl_pola(page=page),
        )

    def _zbuduj_przelacznik(self):
        opcje = [(etykieta_rodzaju_szkicu(r, self.auto_id, krotka=True), r, IKONY_RODZAJU_SZKICU[r])
                 for r in db.RODZAJE_SZKICU]
        return segmented_control(self._page, opcje, self.rodzaj, self._zmien_rodzaj)

    def _zmien_rodzaj(self, rodzaj):
        # Drugie dotknięcie wybranego rodzaju zdejmuje wybór — pole jest opcjonalne.
        self.rodzaj = None if rodzaj == self.rodzaj else rodzaj
        self.przelacznik.content = self._zbuduj_przelacznik()
        try:
            self.przelacznik.update()
        except RuntimeError:
            log.polkniety("odświeżenie przełącznika rodzaju szkicu")

    def kontrolki(self):
        return [podpis("Czym ten paragon będzie? (opcjonalnie)"), self.przelacznik, self.e_przebieg, self.e_opis]

    def wartosci(self):
        """(rodzaj, przebieg w km albo None, opis)."""
        km = None
        wpisany = parsuj_int(self.e_przebieg.value, None)
        if wpisany and wpisany > 0:
            km = db.dystans_na_km(wpisany, self.j, calkowity=True, km_przy_otwarciu=self._km_przy_otwarciu)
        return self.rodzaj, km, (self.e_opis.value or "").strip()

    def zapisz(self, szkic_id):
        rodzaj, km, opis = self.wartosci()
        return db.opisz_szkic(szkic_id, rodzaj, km, opis)


def dialog_opisu_szkicu(page: ft.Page, auto_id, szkic, po_zapisie=None):
    """Rodzaj, licznik i opis szkicu z kolejki — to samo, co w panelu po migawce."""
    pola = PolaSzkicu(page, auto_id, szkic)

    def zapisz(e):
        pola.zapisz(szkic["id"])
        zamknij_dialog(page, dlg)
        if po_zapisie:
            po_zapisie()

    dlg = ft.AlertDialog(
        title=ft.Text("Rodzaj, licznik i opis", size=FS["heading"], weight="bold"),
        content=ft.Container(width=360, content=ft.Column(pola.kontrolki(), spacing=SPACING["sm"], tight=True)),
        actions=[
            ft.TextButton("Anuluj", on_click=lambda e: zamknij_dialog(page, dlg)),
            ft.TextButton("Zapisz", icon=ft.Icons.CHECK, on_click=zapisz),
        ],
    )
    otworz_dialog(page, dlg)


__all__ = [
    "IKONY_RODZAJU_SZKICU",
    "PolaSzkicu",
    "ROZSZERZENIA_ZDJEC_SZKICU",
    "TRASY_FORMULARZY_SZKICU",
    "aparat_dostepny",
    "baner_szkicow",
    "dialog_opisu_szkicu",
    "dopisek_kolejki",
    "etykieta_rodzaju_szkicu",
    "komunikat_dodania",
    "miniatura_szkicu",
    "opis_szkicu",
    "otworz_migawke",
    "pasek_szkicu",
    "szkic_do_formularza",
    "szkic_z_trasy",
    "trasa_po_zapisie_szkicu",
    "trasa_uzupelnienia",
    "wiek_szkicu",
    "wybierz_z_galerii",
]
