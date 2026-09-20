"""Układanie kafelków WPROST w siatce (U-11).

Do tej pory układanie wyglądało tak: siatka znikała, a w jej miejsce wchodził
poziomy pasek abstrakcyjnych klocków, przewijany w bok przez dwadzieścia
pozycji — i ustawiał wyłącznie kolejność, bo widoczność kafelków mieszkała
w Ustawieniach, dwa ekrany dalej. Teraz kafelki zostają na swoich miejscach:
przeciąga się je w siatce, krzyżyk zdejmuje, a „Dodaj kafelek” przywraca.
"""

import flet as ft
import pytest

import db
import pomoce
import utils

UKLAD = ["koszt_miesiac", "termin", "wykres", "kondycja"]

POLA_DZIECI = ("controls", "content", "items", "actions", "leading", "trailing", "title", "subtitle")


def _wszystkie(korzen, typ):
    znalezione = []

    def zejdz(kontrolka):
        if isinstance(kontrolka, typ):
            znalezione.append(kontrolka)
        for nazwa in POLA_DZIECI:
            wartosc = getattr(kontrolka, nazwa, None)
            if isinstance(wartosc, (list, tuple)):
                for dziecko in wartosc:
                    if isinstance(dziecko, ft.Control):
                        zejdz(dziecko)
            elif isinstance(wartosc, ft.Control):
                zejdz(wartosc)

    zejdz(korzen)
    return znalezione


@pytest.fixture(autouse=True)
def cisza(monkeypatch):
    """Strona testowa nie ma żywej sesji Fleta, więc snackbary i odświeżenia
    strony tłumimy — sprawdzamy układ kafelków, nie warstwę Fleta."""
    monkeypatch.setattr(ft.Page, "update", lambda self, *kontrolki: None)
    monkeypatch.setattr(utils, "pokaz_komunikat", lambda strona, *a, **k: None)


class ZdarzenieUpuszczenia:
    """Udaje ft.DragTargetEvent: Flet rozwiązuje `src` przez żywą stronę,
    której w teście nie ma."""

    def __init__(self, wid):
        self.src = type("Zrodlo", (), {"data": wid})()


def kokpit(widgety=None, scenariusz="pojazd_z_danymi", edycja=True, otworz_z_ustawien=False):
    stan, _ = pomoce.przygotuj_scenariusz(scenariusz)
    stan.zakladka = 0
    stan.kokpit_otworz_ukladanie = otworz_z_ustawien
    db.zapisz_widgety_kokpitu(list(UKLAD if widgety is None else widgety), stan.auto_id)
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(), stan)
    if edycja and not widok.kokpit_edycja:
        widok._ustaw_tryb_ukladania(True)
    return widok, stan


def komorki(widok):
    return {k.data: k for k in _wszystkie(widok.kokpit_kontener, ft.DragTarget)}


def teksty(kontrolka):
    return [t.value for t in _wszystkie(kontrolka, ft.Text) if isinstance(t.value, str)]


def test_kafelek_laduje_na_miejscu_celu(baza):
    """Przy ruchu w lewo i w prawo tak samo: kafelek staje tam, gdzie stał cel."""
    widok, stan = kokpit()
    komorki(widok)["termin"].on_accept(ZdarzenieUpuszczenia("kondycja"))
    assert db.pobierz_widgety_kokpitu(stan.auto_id) == ["koszt_miesiac", "kondycja", "termin", "wykres"]

    komorki(widok)["wykres"].on_accept(ZdarzenieUpuszczenia("koszt_miesiac"))
    assert db.pobierz_widgety_kokpitu(stan.auto_id) == ["kondycja", "termin", "wykres", "koszt_miesiac"]


def test_upuszczenie_na_siebie_nic_nie_zmienia(baza):
    widok, stan = kokpit()
    komorki(widok)["termin"].on_accept(ZdarzenieUpuszczenia("termin"))
    komorki(widok)["termin"].on_accept(ZdarzenieUpuszczenia(None))
    assert db.pobierz_widgety_kokpitu(stan.auto_id) == UKLAD


def test_krzyzyk_zdejmuje_kafelek_z_kokpitu(baza):
    """Dawniej wyrzucenie kafelka wymagało wejścia w Ustawienia i odklikania
    checkboxa — teraz jest tam, gdzie kafelek."""
    widok, stan = kokpit()
    stos = komorki(widok)["wykres"].content.content
    krzyzyk = stos.controls[1]
    krzyzyk.on_click(None)

    assert "wykres" not in db.pobierz_widgety_kokpitu(stan.auto_id)
    assert "wykres" not in komorki(widok)


def test_zdjety_kafelek_wraca(baza):
    widok, stan = kokpit()
    widok._usun_kafelek("termin")
    widok._dodaj_kafelek("termin")
    assert db.pobierz_widgety_kokpitu(stan.auto_id)[-1] == "termin"
    assert "termin" in komorki(widok)


def test_menu_dodawania_pokazuje_tylko_zdjete(baza, monkeypatch):
    widok, stan = kokpit()
    pozycje = {}
    monkeypatch.setattr(utils, "pokaz_menu_kontekstowe",
                        lambda strona, tytul, poz: pozycje.update({"tytul": tytul, "poz": poz}))

    widok._menu_dodawania_kafelka()
    nazwy = [p["tekst"] for p in pozycje["poz"]]
    assert str(db.KOKPIT_WIDGETY["opony"]) in nazwy
    assert str(db.KOKPIT_WIDGETY["termin"]) not in nazwy, "kafelek już na kokpicie nie może być do dodania"


def test_w_ukladaniu_kafelek_nie_otwiera_ekranu(baza):
    """Dotknięcie kafelka w trybie układania nie może nawigować — palec ląduje
    na kafelku, bo się go właśnie przestawia."""
    widok, _ = kokpit()
    for wid, komorka in komorki(widok).items():
        kafel = komorka.content.content.controls[0]
        assert kafel.on_click is None, wid
        assert kafel.on_long_press is None, wid


def test_ustawienia_otwieraja_ukladanie(baza):
    """Ustawienia → „Ułóż kafelki kokpitu” tylko przełączają ekran; tryb
    układania włącza kokpit po fladze i od razu ją gasi."""
    widok, stan = kokpit(edycja=False, otworz_z_ustawien=True)
    assert widok.kokpit_edycja is True
    assert stan.kokpit_otworz_ukladanie is False


def test_pusty_kokpit_w_ukladaniu_ma_czym_dodac(baza):
    """Kto zdjął wszystko, musi mieć jak wrócić."""
    widok, stan = kokpit(widgety=["termin"])
    widok._usun_kafelek("termin")
    assert db.pobierz_widgety_kokpitu(stan.auto_id) == []
    assert "Dodaj kafelek" in teksty(widok.kokpit_kontener)


def test_gotowe_wraca_do_zwyklej_siatki(baza):
    widok, _ = kokpit()
    gotowe = [b for b in _wszystkie(widok.kokpit_kontener, ft.TextButton)
              if getattr(b, "content", None) == "Gotowe"][0]
    gotowe.on_click(None)
    assert widok.kokpit_edycja is False
    assert not komorki(widok)
