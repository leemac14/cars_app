"""Kokpit jako SIATKA, a nie karuzela.

Kafelki kokpitu jechały wcześniej w poziomej karuzeli. Karuzela chowa część
kafelków za krawędzią ekranu, a Flutter nie przewija zawartości myszą — stąd
brał się w niej wymuszony, zawsze widoczny suwak, którego cała rola sprowadzała
się do sygnału „tam jeszcze coś jest”. Te testy pilnują, że kokpit pokazuje
wszystko naraz: siatka `ResponsiveRow` z kafelkami w dwóch rozmiarach, bez
ani jednego poziomego przewijania i bez szerokości liczonych w Pythonie.
"""

import flet as ft

import db
import pomoce
from views.ekran_glowny import kokpit as mod_kokpit

POLA_DZIECI = ("controls", "content", "items", "actions", "leading", "trailing", "title", "subtitle")


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


def kokpit_z_kompletem_kafelkow(scenariusz="pojazd_z_danymi"):
    """Kokpit ze WSZYSTKIMI kafelkami — rozmiar kafelka zależy od jego treści,
    więc trzy domyślne nie powiedziałyby o siatce niczego."""
    stan, _ = pomoce.przygotuj_scenariusz(scenariusz)
    stan.zakladka = 0
    db.zapisz_widgety_kokpitu(list(db.KOKPIT_WIDGETY), stan.auto_id)
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(), stan)
    wlaczone = [w for w in db.pobierz_widgety_kokpitu(stan.auto_id) if w in widok._kokpit_budowniczy]
    return widok, wlaczone


def siatka_kokpitu(widok):
    return _wszystkie(widok.kokpit_kontener, ft.ResponsiveRow)[0]


def test_kokpit_jest_siatka_bez_przewijania_w_bok(baza):
    """Sedno zmiany: żaden kafelek nie chowa się za krawędzią, więc w kokpicie
    nie ma czego przewijać w bok. Pasek przewijany poznaje się po `scroll`."""
    widok, wlaczone = kokpit_z_kompletem_kafelkow()
    siatka = siatka_kokpitu(widok)

    # Każdy włączony widżet plus kafelek wejścia w tryb układania.
    assert len(siatka.controls) == len(wlaczone) + 1

    przewijane = [w for w in _wszystkie(widok.kokpit_kontener, ft.Row) if getattr(w, "scroll", None)]
    assert przewijane == [], "kokpit znowu przewija się w bok"


def test_kafelek_nie_trzyma_wlasnej_szerokosci(baza):
    """Szerokość liczy Flet z rzeczywistej szerokości ekranu. Kafelek z własnym
    `width` wracałby do stałego rozmiaru — a po to, żeby nie liczyć szerokości
    w Pythonie, siatka w ogóle powstała (przy pierwszym starcie `page.width`
    jeszcze nie jest znane)."""
    widok, _ = kokpit_z_kompletem_kafelkow()
    siatka = siatka_kokpitu(widok)

    assert all(k.width is None for k in siatka.controls)
    assert all(k.col in (mod_kokpit.KOL_KAFLA_1X1, mod_kokpit.KOL_KAFLA_2X1) for k in siatka.controls)


def test_dwa_rozmiary_kafelka_1x1_i_2x1(baza):
    """Kafelek 2×1 zajmuje dokładnie dwie komórki 1×1 — w każdym progu
    szerokości, inaczej siatka rozjechałaby się na tablecie.

    Rozmiar bierze się z treści: „Wydatki 6 mies.” rysuje sześć słupków
    i dostaje dwie komórki, a „Kondycja” — sama liczba z paskiem — jedną."""
    for prog, waskie in mod_kokpit.KOL_KAFLA_1X1.items():
        assert mod_kokpit.KOL_KAFLA_2X1[prog] == 2 * waskie

    widok, wlaczone = kokpit_z_kompletem_kafelkow()
    rozmiary = dict(zip(wlaczone, siatka_kokpitu(widok).controls))

    assert rozmiary["wykres"].col == mod_kokpit.KOL_KAFLA_2X1
    assert rozmiary["kondycja"].col == mod_kokpit.KOL_KAFLA_1X1


def test_tryb_ukladania_wchodzi_i_wraca_do_siatki(baza):
    """Przejście w układanie i z powrotem — to ten sam kontener, więc zamiana
    siatki na klocki (i odwrotnie) musi działać w obie strony."""
    widok, _ = kokpit_z_kompletem_kafelkow()

    widok._ustaw_tryb_ukladania(True)
    assert _wszystkie(widok.kokpit_kontener, ft.ReorderableListView)
    assert not _wszystkie(widok.kokpit_kontener, ft.ResponsiveRow)

    widok._ustaw_tryb_ukladania(False)
    assert not _wszystkie(widok.kokpit_kontener, ft.ReorderableListView)
    assert _wszystkie(widok.kokpit_kontener, ft.ResponsiveRow)
