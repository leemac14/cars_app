"""Kafelki akcji na kokpicie (U-11).

Kokpit odpowiadał wyłącznie na pytanie „co się dzieje”. Dwie najczęstsze
czynności w aplikacji — tankowanie i stan licznika — siedziały pod FAB-em
w rogu ekranu. Teraz każda akcja może stanąć w siatce jako pełnoprawny kafelek,
a stan licznika zapisuje się bez schodzenia z kokpitu.
"""

import flet as ft

import db
import pomoce
import utils

AKCJE = ["akcja_tankowanie", "akcja_licznik", "akcja_inny_koszt",
         "akcja_wizyta", "akcja_podzespol", "akcja_do_zrobienia"]

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


def kokpit(scenariusz="pojazd_z_danymi", widgety=None):
    stan, _ = pomoce.przygotuj_scenariusz(scenariusz)
    stan.zakladka = 0
    db.zapisz_widgety_kokpitu(list(widgety or AKCJE), stan.auto_id)
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(), stan)
    return widok, stan


def siatka(widok):
    return _wszystkie(widok.kokpit_kontener, ft.ResponsiveRow)[0]


def teksty(kontrolka):
    return [t.value for t in _wszystkie(kontrolka, ft.Text) if isinstance(t.value, str)]


def test_kazda_akcja_ma_swoj_kafelek(baza):
    """Sześć akcji, sześć kafelków — każdy z własnym dotknięciem."""
    widok, _ = kokpit()
    assert widok._kokpit_puste == []
    komorki = siatka(widok).controls
    # Sześć akcji plus komórka „Ułóż kafelki”.
    assert len(komorki) == len(AKCJE) + 1
    assert all(k.on_click is not None for k in komorki)
    assert "Tankowanie" in teksty(widok.kokpit_kontener)
    assert "Stan licznika" in teksty(widok.kokpit_kontener)


def test_akcje_wchodza_tylko_do_ukladu_domyslnego(baza):
    """Auto z własnym układem nie zmienia się samo po aktualizacji."""
    assert db.KOKPIT_WIDGETY_DOMYSLNE[:2] == ["akcja_tankowanie", "akcja_licznik"]
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    db.zapisz_widgety_kokpitu(["koszt_miesiac", "termin"], stan.auto_id)
    assert db.pobierz_widgety_kokpitu(stan.auto_id) == ["koszt_miesiac", "termin"]


def test_podglad_nie_dostaje_kafelkow_akcji(baza):
    """Rola „podgląd” i tak nie zapisze wpisu — przycisk, który zawsze odmawia,
    jest gorszy od jego braku (ta sama zasada, co przy menu wpisu)."""
    widok, _ = kokpit("wspoldzielony_podglad")
    assert set(widok._kokpit_puste) == set(AKCJE)
    assert not _wszystkie(widok.kokpit_kontener, ft.ResponsiveRow) or \
        len(siatka(widok).controls) == 1  # zostaje sama komórka „Ułóż kafelki”


def test_kafelek_licznika_zapisuje_odczyt_bez_zmiany_ekranu(baza, monkeypatch):
    """Sedno kafelka „Stan licznika”: okno z jednym polem, zapis i powrót na
    kokpit — bez wchodzenia na ekran historii licznika."""
    widok, stan = kokpit(widgety=["akcja_licznik"])

    otwarte = []
    # Strona testowa nie ma żywej sesji Fleta, a formularz w kilku miejscach
    # odświeża widok — tak samo robi to test animacji kokpitu.
    monkeypatch.setattr(ft.Page, "update", lambda self, *kontrolki: None)
    monkeypatch.setattr(utils.pojazd, "pokaz_komunikat", lambda strona, *a, **k: None)
    monkeypatch.setattr(utils.pojazd, "otworz_dialog", lambda strona, dlg: otwarte.append(dlg))
    monkeypatch.setattr(utils.pojazd, "zamknij_dialog", lambda strona, dlg: None)
    monkeypatch.setattr(utils.pojazd, "wypchnij_w_tle", lambda strona, auto_id, powod="zapis": None)
    odswiezone = []
    monkeypatch.setattr(utils, "odswiez_ekran", lambda strona: odswiezone.append(True))

    siatka(widok).controls[0].on_click(None)
    assert otwarte, "kafelek nie otworzył okna odczytu"
    dlg = otwarte[0]

    pole = [p for p in _wszystkie(dlg, ft.TextField) if p.label == "Przebieg (km)"][0]
    nowy = (db.pobierz_aktualny_przebieg(stan.auto_id) or 0) + 500
    pole.value = str(nowy)

    zapisz = [b for b in dlg.actions if getattr(b, "content", None) == "Zapisz"][0]
    zapisz.on_click(None)

    assert db.pobierz_aktualny_przebieg(stan.auto_id) == nowy
    assert odswiezone, "po zapisie kokpit nie został odświeżony"


def test_bledny_przebieg_nie_zapisuje_nic(baza, monkeypatch):
    """Walidacja jest ta sama, co w formularzu na ekranie licznika — bo to
    dosłownie ten sam formularz (utils.dialog_odczytu_przebiegu)."""
    widok, stan = kokpit(widgety=["akcja_licznik"])
    przed = db.pobierz_aktualny_przebieg(stan.auto_id)

    otwarte = []
    monkeypatch.setattr(ft.Page, "update", lambda self, *kontrolki: None)
    monkeypatch.setattr(utils.pojazd, "pokaz_komunikat", lambda strona, *a, **k: None)
    monkeypatch.setattr(utils.pojazd, "otworz_dialog", lambda strona, dlg: otwarte.append(dlg))
    monkeypatch.setattr(utils.pojazd, "wypchnij_w_tle", lambda strona, auto_id, powod="zapis": None)

    siatka(widok).controls[0].on_click(None)
    dlg = otwarte[0]
    pole = [p for p in _wszystkie(dlg, ft.TextField) if p.label == "Przebieg (km)"][0]
    pole.value = "nie liczba"
    [b for b in dlg.actions if getattr(b, "content", None) == "Zapisz"][0].on_click(None)

    assert db.pobierz_aktualny_przebieg(stan.auto_id) == przed
