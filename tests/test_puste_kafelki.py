"""Puste kafelki kokpitu chowają się same (U-10).

Kokpit ma dwadzieścia kafelków do wyboru. Ten, który REGULARNIE nie ma nic do
powiedzenia — budżet bez ustawionego limitu, zasięg EV w aucie spalinowym,
checklista, której nie ma — uczy oko, żeby przestało czytać całą siatkę. Chowana
jest wyłącznie pustka typu „nie dotyczy / nieustawione”: kafelek czekający na
dane („za mało danych”) zostaje, bo jego pustka sama się skończy.
"""

import flet as ft

import db
import pomoce

POLA_DZIECI = ("controls", "content", "items", "actions", "leading", "trailing", "title", "subtitle")

# W aucie bez ani jednego wpisu te kafelki nie mają o czym mówić i znikają.
CHOWANE = {"budzet", "opony", "checklist", "magazyn", "zasieg_bak", "zasieg_ev", "oplaty_drogowe"}
# ...a te zostają: mówią „na czas”, „za mało danych” albo liczą kondycję —
# ich pustka jest tymczasowa i jest zaproszeniem do wpisania czegoś.
ZOSTAJA = {"koszt_miesiac", "termin", "kondycja", "spalanie", "prognoza_rok", "ostatnia_aktywnosc"}


def _wszystkie(korzen, typ):
    """Wszystkie kontrolki danego typu w drzewie — kolejnością odwiedzin."""
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


def kokpit(scenariusz="pojazd_bez_danych", widgety=None):
    stan, _ = pomoce.przygotuj_scenariusz(scenariusz)
    stan.zakladka = 0
    db.zapisz_widgety_kokpitu(list(widgety or db.KOKPIT_WIDGETY), stan.auto_id)
    return pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(), stan)


def teksty(kontrolka):
    return [t.value for t in _wszystkie(kontrolka, ft.Text) if isinstance(t.value, str)]


def test_kafelki_bez_tresci_znikaja_z_siatki(baza):
    """Sedno zmiany: siedem kafelków, które w gołym aucie pokazywały myślnik,
    nie wchodzi do siatki w ogóle."""
    widok = kokpit()
    assert CHOWANE <= set(widok._kokpit_puste)


def test_kafelki_czekajace_na_dane_zostaja(baza):
    """Granica chowania: „za mało danych” to nie to samo, co „nie dotyczy”."""
    widok = kokpit()
    assert not (ZOSTAJA & set(widok._kokpit_puste))


def test_wylaczony_przelacznik_pokazuje_wszystko(baza):
    """Ustawienia → „Chowaj puste kafelki” wyłączone = kokpit jak przed zmianą."""
    db.zapisz_chowanie_pustych_kafelkow(False)
    widok = kokpit()
    assert widok._kokpit_puste == []
    tresc = teksty(widok.kokpit_kontener)
    assert "Nie ustawiono" in tresc
    assert "Brak zestawów" in tresc


def test_kafelek_z_trescia_nie_znika(baza):
    """Magazyn ma w tym scenariuszu pozycję na stanie — chowanie go nie dotyczy."""
    widok = kokpit("pojazd_z_danymi")
    assert "magazyn" not in widok._kokpit_puste


def test_zacheta_zamiast_pustej_siatki(baza):
    """Gdy milczą WSZYSTKIE włączone kafelki, pusta siatka wyglądałaby na awarię."""
    widok = kokpit(widgety=["budzet", "opony", "checklist"])
    assert widok._kokpit_puste == ["budzet", "opony", "checklist"]
    assert not _wszystkie(widok.kokpit_kontener, ft.ResponsiveRow)
    assert any("Kokpit ożyje" in t for t in teksty(widok.kokpit_kontener))


def test_zacheta_umie_pokazac_puste(baza):
    """Przycisk „Pokaż puste” to droga powrotna bez szukania w Ustawieniach."""
    widok = kokpit(widgety=["budzet", "opony", "checklist"])
    # Flet 0.86 trzyma napis przycisku w `content`, nie w `text` (patrz
    # utils/zgodnosc.py — ustaw_tekst_przycisku).
    przyciski = [p for p in _wszystkie(widok.kokpit_kontener, ft.TextButton)
                 if getattr(p, "content", None) == "Pokaż puste"]
    assert przyciski
    przyciski[0].on_click(None)
    assert db.czy_chowac_puste_kafelki() is False
    assert _wszystkie(widok.kokpit_kontener, ft.ResponsiveRow)


def test_uklad_pokazuje_ktore_kafelki_sa_schowane(baza):
    """W trybie układania schowany kafelek musi dać się odróżnić od wyłączonego."""
    widok = kokpit()
    schowane = len(widok._kokpit_puste)
    widok._ustaw_tryb_ukladania(True)
    assert any("teraz pusty" in t for t in teksty(widok.kokpit_kontener))
    przygaszone = [k for k in _wszystkie(widok.kokpit_kontener, ft.Container)
                   if getattr(k, "opacity", 1) is not None and getattr(k, "opacity", 1) < 1]
    assert len(przygaszone) == schowane


def test_ustawienie_domyslnie_wlaczone(baza):
    assert db.czy_chowac_puste_kafelki() is True
    db.zapisz_chowanie_pustych_kafelkow(False)
    assert db.czy_chowac_puste_kafelki() is False
    db.zapisz_chowanie_pustych_kafelkow(True)
    assert db.czy_chowac_puste_kafelki() is True
