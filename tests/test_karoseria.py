"""Rejestr karoserii: kolejność zdjęć po dacie, pary „przed / po”, podsumowanie stref i zapis
z aparatu (db/karoseria.py); galeria przewijana razem z ekranem zamiast siatki w okienku na pół
ekranu, mapa stref jako filtr, przeglądarka, porównanie przeciąganiem, formularz z chipami
i obchód auta aparatem."""

import asyncio
import os
import types
import uuid
from datetime import datetime

import flet as ft
import pytest

import audyty
import db
import pomoce
import utils
from date import na_iso

PRZED, PO, ZWYKLE = db.TYP_ZDJECIA_PRZED, db.TYP_ZDJECIA_PO, db.TYP_ZDJECIA_ZWYKLE


def _auto(nazwa="Karoseryjny"):
    with db.polacz_baze() as conn:
        return conn.execute(
            "INSERT INTO samochody (nazwa, typ_paliwa, status, rola_wspoldzielenia) VALUES (?,?,?,?)",
            (nazwa, "Benzyna", db.STATUS_POJAZDU_AKTYWNY, db.ROLA_WLASCICIEL),
        ).lastrowid


def _zdjecie(auto_id, data, strefa, typ=None, opis=""):
    """Wpis rejestru z prawdziwym (małym) plikiem JPEG w folderze załączników."""
    os.makedirs(db.FOLDER_ZALACZNIKI, exist_ok=True)
    nazwa = f"karoseria_{uuid.uuid4().hex}.jpg"
    with open(os.path.join(db.FOLDER_ZALACZNIKI, nazwa), "wb") as plik:
        plik.write(pomoce.jpeg())
    with db.polacz_baze() as conn:
        return conn.execute(
            "INSERT INTO zdjecia_karoserii (auto_id, data, data_iso, strefa, zalacznik, opis, typ_porownania) "
            "VALUES (?,?,?,?,?,?,?)",
            (auto_id, data, na_iso(data), strefa, f"zalaczniki/{nazwa}", opis, typ),
        ).lastrowid


def _widok(auto_id, klasa="KaroseriaView", strona=None):
    strona = strona or pomoce.zbuduj_strone()
    stan = pomoce.stan_aplikacji(auto_id, "Karoseryjny")
    return strona, pomoce.zbuduj_widok(pomoce.klasy_widokow()[klasa], strona, stan)


def _kafle(widok):
    return [k for rzad in pomoce.kontrolki(widok.galeria, ft.ResponsiveRow) for k in rzad.controls]


def _napisy(korzen):
    return pomoce.napisy(korzen)


# ============================================================================
#  1. DANE
# ============================================================================

def test_zdjecia_ida_od_najnowszej_daty_a_nie_od_kolejnosci_dodania(baza):
    auto_id = _auto()
    marzec = _zdjecie(auto_id, "01.03.2026", "Przód")
    maj = _zdjecie(auto_id, "15.05.2026", "Tył", typ="Brak")
    kwiecien = _zdjecie(auto_id, "10.04.2026", "Bok lewy", typ=PRZED)  # dodany jako ostatni

    zdjecia = db.zdjecia_karoserii_pojazdu(auto_id)

    assert [z["id"] for z in zdjecia] == [maj, kwiecien, marzec]
    assert [(z["typ"], z["etykieta_typu"]) for z in zdjecia] == [
        (ZWYKLE, "Zwykłe"), (PRZED, "Przed naprawą"), (ZWYKLE, "Zwykłe")], "NULL to zwykłe zdjęcie"
    assert db.zdjecia_karoserii_pojazdu(None) == []


def test_pary_przed_po_lacza_strefe_z_najblizszym_wczesniejszym_przed(baza):
    auto_id = _auto()
    przod_1 = _zdjecie(auto_id, "01.03.2026", "Przód", PRZED)
    przod_2 = _zdjecie(auto_id, "05.03.2026", "Przód", PRZED)
    przod_po_1 = _zdjecie(auto_id, "10.03.2026", "Przód", PO)
    przod_po_2 = _zdjecie(auto_id, "20.03.2026", "Przód", PO)
    _zdjecie(auto_id, "01.02.2026", "Tył", PO)       # „po” bez wcześniejszego „przed”
    _zdjecie(auto_id, "02.02.2026", "Tył", PRZED)    # „przed” bez późniejszego „po”
    bok = _zdjecie(auto_id, "01.04.2026", "Bok lewy", PRZED)
    bok_po = _zdjecie(auto_id, "01.04.2026", "Bok lewy", PO)  # ten sam dzień
    _zdjecie(auto_id, "01.01.2026", "Bok prawy", PRZED)
    _zdjecie(auto_id, "02.01.2026", "Inne", PO)      # inna strefa — nie para

    pary = db.pary_przed_po(db.zdjecia_karoserii_pojazdu(auto_id))

    assert [(p["strefa"], p["przed"]["id"], p["po"]["id"]) for p in pary] == [
        ("Bok lewy", bok, bok_po),
        ("Przód", przod_1, przod_po_2),
        ("Przód", przod_2, przod_po_1),
    ]


def test_podsumowanie_stref_liczy_zdjecia_i_ostatnia_date(baza):
    auto_id = _auto()
    _zdjecie(auto_id, "01.03.2026", "Przód")
    _zdjecie(auto_id, "20.05.2026", "Przód")
    _zdjecie(auto_id, "10.04.2026", "Przód")
    _zdjecie(auto_id, "02.02.2026", "Dach")  # strefa spoza słownika (stary wpis)

    podsumowanie = db.podsumowanie_stref(db.zdjecia_karoserii_pojazdu(auto_id))

    assert podsumowanie["Przód"] == {"liczba": 3, "ostatnia": "20.05.2026"}
    assert podsumowanie["Tył"] == {"liczba": 0, "ostatnia": None}
    assert podsumowanie["Dach"] == {"liczba": 1, "ostatnia": "02.02.2026"}
    assert set(db.STREFY_KAROSERII) <= set(podsumowanie)
    assert set(db.STREFY_OBCHODU) <= set(db.STREFY_KAROSERII)


def test_zdjecie_z_aparatu_trafia_do_rejestru_z_dzisiejsza_data(baza):
    auto_id = _auto()

    zid = db.dodaj_zdjecie_karoserii_z_bajtow(auto_id, pomoce.jpeg(), "Bok prawy", przebieg=123456)
    obce = db.dodaj_zdjecie_karoserii_z_bajtow(auto_id, pomoce.jpeg(), "Gdzieś", typ=PO)

    (z,) = [z for z in db.zdjecia_karoserii_pojazdu(auto_id) if z["id"] == zid]
    dzis = datetime.now().strftime("%d.%m.%Y")
    assert (z["data"], z["data_iso"], z["strefa"], z["typ"], z["przebieg"]) == (
        dzis, na_iso(dzis), "Bok prawy", ZWYKLE, 123456)
    assert os.path.exists(db.sciezka_pliku_zalacznika(z["zalacznik"]))
    assert not [p for p in os.listdir(db.FOLDER_ODROCZONE) if p.startswith("obchod_")], "plik pośredni zostaje"
    (o,) = [z for z in db.zdjecia_karoserii_pojazdu(auto_id) if z["id"] == obce]
    assert (o["strefa"], o["typ"]) == (db.STREFA_DOMYSLNA, PO)
    assert db.dodaj_zdjecie_karoserii_z_bajtow(auto_id, b"", "Przód") is None


def test_sekcje_galerii_to_miesiace_albo_strefy(baza):
    auto_id = _auto()
    _zdjecie(auto_id, "20.05.2026", "Tył")
    _zdjecie(auto_id, "02.05.2026", "Przód")
    _zdjecie(auto_id, "10.04.2026", "Przód")
    zdjecia = db.zdjecia_karoserii_pojazdu(auto_id)

    assert [(t, o, len(l)) for t, o, l in utils.sekcje_galerii(zdjecia)] == [
        (utils.nazwa_miesiaca((2026, 5)), "2 zdjęcia", 2),
        (utils.nazwa_miesiaca((2026, 4)), "1 zdjęcie", 1),
    ]
    assert [t for t, _o, _l in utils.sekcje_galerii(zdjecia, po_dacie=False)] == ["Tył", "Przód"]
    bez_daty = dict(zdjecia[0], data="kiedyś")
    assert utils.sekcje_galerii([bez_daty])[0][0] == "Bez daty"


# ============================================================================
#  2. GALERIA
# ============================================================================

def test_galeria_przewija_sie_razem_z_ekranem_zamiast_okienka_na_pol_ekranu(baza):
    """Dawniej siatka miała wysokość połowy ekranu i własne przewijanie — zdjęcia urywały się
    w połowie, a pod nimi zostawało puste pole („biały prostokąt”)."""
    auto_id = _auto()
    for dzien in range(1, 10):
        _zdjecie(auto_id, f"{dzien:02d}.0{dzien % 3 + 4}.2026", db.STREFY_KAROSERII[dzien % 7])
    strona, widok = _widok(auto_id)

    assert widok.scroll == ft.ScrollMode.AUTO
    assert pomoce.kontrolki(widok, ft.GridView) == [] and pomoce.kontrolki(widok, ft.ListView) == []
    kafle = _kafle(widok)
    assert len(kafle) == 9
    assert all(k.aspect_ratio == 1 and k.col == utils.KOLUMNY_GALERII and k.height is None for k in kafle)
    assert all(isinstance(i.cache_width, int) for i in pomoce.kontrolki(widok.galeria, ft.Image))
    assert "Mapa karoserii" in _napisy(widok)
    assert audyty.znajdz_expand_bez_ograniczenia(widok) == []
    assert audyty.znajdz_uciete_napisy(widok) == []


def test_pusty_rejestr_i_auto_tylko_do_odczytu(baza):
    auto_id = _auto()
    _strona, widok = _widok(auto_id)
    assert "Brak zdjęć karoserii" in _napisy(widok) and widok.floating_action_button is not None
    assert "Mapa karoserii" not in _napisy(widok)

    stan, _ = pomoce.przygotuj_scenariusz("wspoldzielony_podglad")
    podglad = pomoce.zbuduj_widok(pomoce.klasy_widokow()["KaroseriaView"], pomoce.zbuduj_strone(), stan)
    assert podglad.floating_action_button is None


def test_mapa_filtruje_galerie_a_pusta_strefa_otwiera_formularz(baza, monkeypatch):
    auto_id = _auto()
    _zdjecie(auto_id, "01.03.2026", "Przód", opis="rysa na zderzaku")
    _zdjecie(auto_id, "02.03.2026", "Przód")
    _zdjecie(auto_id, "03.03.2026", "Tył")
    strona, widok = _widok(auto_id)
    monkeypatch.setattr(type(widok), "update", lambda self: None)
    strona.page.views.append(widok)
    trasy = []
    strona.page.on_route_change = lambda e: trasy.append(strona.page.route)

    widok._wybierz_strefe("Przód")
    assert widok.state.filtry["karoseria_strefa"] == "Przód"
    assert len(_kafle(widok)) == 2 and {z["strefa"] for z in widok.widoczne} == {"Przód"}
    assert any("Pokazuję tylko: Przód" in n for n in _napisy(widok))

    widok._wybierz_strefe("Przód")
    assert widok.state.filtry["karoseria_strefa"] == utils.WSZYSTKO and len(_kafle(widok)) == 3

    widok._wybierz_strefe("Bok lewy")
    assert trasy == ["/karoseria/nowe"] and widok.state.karoseria_nowa_strefa == "Bok lewy"
    formularz = pomoce.zbuduj_widok(pomoce.klasy_widokow()["FormularzZdjecieKaroseriiView"], strona, widok.state)
    assert formularz.e_strefa.value == "Bok lewy" and widok.state.karoseria_nowa_strefa is None


def test_wyszukiwanie_i_powrot_do_wszystkich(baza, monkeypatch):
    auto_id = _auto()
    _zdjecie(auto_id, "01.03.2026", "Przód", opis="Rysa na zderzaku")
    _zdjecie(auto_id, "02.03.2026", "Tył", opis="Tablica")
    strona, widok = _widok(auto_id)
    monkeypatch.setattr(type(widok), "update", lambda self: None)
    strona.page.views.append(widok)

    widok.pole_szukaj.value = "zderzak"
    widok._szukaj(None)
    assert [z["opis"] for z in widok.widoczne] == ["Rysa na zderzaku"] and len(_kafle(widok)) == 1

    widok.pole_szukaj.value = "nie ma takiego"
    widok._szukaj(None)
    assert _kafle(widok) == [] and "Pokaż wszystkie zdjęcia" in _napisy(widok.galeria)

    widok._wyczysc_filtry()
    assert widok.pole_szukaj.value == "" and len(_kafle(widok)) == 2


def test_zaznaczenie_dwoch_zdjec_otwiera_porownanie(baza, monkeypatch):
    auto_id = _auto()
    nowsze = _zdjecie(auto_id, "10.03.2026", "Przód", PO)
    starsze = _zdjecie(auto_id, "01.03.2026", "Przód", PRZED)
    strona, widok = _widok(auto_id)
    monkeypatch.setattr(type(widok), "update", lambda self: None)
    otwarte = []
    monkeypatch.setattr(ft.Page, "show_dialog", lambda self, okno: otwarte.append(okno))

    widok.wymus_tryb_zaznaczania(nowsze)
    widok.zaznacz_odznacz(starsze, widok.karty_ref[starsze])
    assert widok.appbar.title.value == "2 zdjęcia"
    assert widok.karty_ref[starsze].border is not None, "zaznaczenie widać na nakładce kafla"

    widok.otworz_porownanie(None)
    assert not widok.tryb_zaznaczania
    napisy = _napisy(otwarte[-1])
    assert "PRZED · 01.03.2026" in napisy and "PO · 10.03.2026" in napisy


# ============================================================================
#  3. PRZEGLĄDARKA I PORÓWNANIE
# ============================================================================

def _przegladarka(auto_id):
    zdjecia = db.zdjecia_karoserii_pojazdu(auto_id)
    pary = {z["id"]: p for p in db.pary_przed_po(zdjecia) for z in (p["przed"], p["po"])}
    return zdjecia, utils.PrzegladarkaKaroserii(pomoce.zbuduj_strone().page, zdjecia, 0, pary=pary)


def _gest(x, y=0.0, palce=1):
    return types.SimpleNamespace(velocity=types.SimpleNamespace(x=x, y=y), pointer_count=palce)


def test_przegladarka_strzalki_i_przesuniecie_palcem(baza):
    auto_id = _auto()
    _zdjecie(auto_id, "03.03.2026", "Tył", opis="Tablica")
    _zdjecie(auto_id, "02.03.2026", "Przód", PO)
    _zdjecie(auto_id, "01.03.2026", "Przód", PRZED)
    zdjecia, p = _przegladarka(auto_id)

    assert (p.licznik.value, p.w_lewo.visible, p.w_prawo.visible) == ("1 z 3", False, True)
    assert p.opis.value == "Tablica" and not p.przycisk_pary.visible
    assert pomoce.kontrolki(p.dialog, ft.InteractiveViewer), "zdjęcie da się przybliżyć"

    p.nastepne()
    assert p.indeks == 1 and p.przycisk_pary.visible and p.w_lewo.visible
    p._koniec_gestu(_gest(-900))
    assert p.indeks == 2 and not p.w_prawo.visible
    p._koniec_gestu(_gest(-900))
    assert p.indeks == 2, "za ostatnim zdjęciem nie ma dokąd iść"
    p._koniec_gestu(_gest(900))
    assert p.indeks == 1
    for powolny_albo_pionowy in (_gest(-200), _gest(-700, 900)):
        p._koniec_gestu(powolny_albo_pionowy)
        assert p.indeks == 1

    p._poczatek_gestu(types.SimpleNamespace(pointer_count=2))
    p._koniec_gestu(_gest(-900))
    assert p.indeks == 1, "po przybliżeniu dwoma palcami przesunięcie nie zmienia zdjęcia"
    p.poprzednie()
    p._koniec_gestu(_gest(-900))
    assert p.indeks == 1, "nowe zdjęcie — przesunięcie znowu działa"


def test_porownanie_ustawia_starsze_jako_przed_i_idzie_za_palcem(baza, monkeypatch):
    auto_id = _auto()
    _zdjecie(auto_id, "10.03.2026", "Przód", PO)
    _zdjecie(auto_id, "01.03.2026", "Przód", PRZED)
    po, przed = db.zdjecia_karoserii_pojazdu(auto_id)
    otwarte = []
    monkeypatch.setattr(ft.Page, "show_dialog", lambda self, okno: otwarte.append(okno))
    strona = pomoce.zbuduj_strone()

    okno = utils.porownaj_zdjecia_karoserii(strona.page, po, przed)  # kolejność odwrotna

    assert otwarte == [okno]
    assert "PRZED · 01.03.2026" in _napisy(okno) and "PO · 10.03.2026" in _napisy(okno)
    (gest,) = pomoce.kontrolki(okno, ft.GestureDetector)
    (suwak,) = pomoce.kontrolki(okno, ft.Slider)
    (warstwa,) = [c for c in pomoce.kontrolki(okno, ft.Container) if c.clip_behavior == ft.ClipBehavior.HARD_EDGE]
    for x, oczekiwane in ((40, 40), (-30, 0), (99999, suwak.max)):
        gest.on_horizontal_drag_update(types.SimpleNamespace(local_position=types.SimpleNamespace(x=x)))
        assert warstwa.width == oczekiwane and suwak.value == oczekiwane
    assert audyty.znajdz_uciete_napisy(okno) == []


# ============================================================================
#  4. FORMULARZ I OBCHÓD
# ============================================================================

def test_formularz_zapisuje_strefe_i_rodzaj_wybrane_chipami(baza, tmp_path):
    auto_id = _auto()
    strona, widok = _widok(auto_id, "FormularzZdjecieKaroseriiView")
    strona.page.on_route_change = lambda e: None
    sciezki = []
    for i in range(2):
        sciezka = tmp_path / f"z{i}.jpg"
        sciezka.write_bytes(pomoce.jpeg())
        sciezki.append(str(sciezka))
    widok.get_wiele_zdjec = lambda: sciezki

    assert widok.e_typ.value == ZWYKLE and widok.e_typ.chipy[ZWYKLE].label.value == "Zwykłe"
    widok.e_strefa.wybierz("Tył")
    widok.e_typ.wybierz(PRZED)
    widok.e_typ.wybierz(PRZED)  # drugie dotknięcie nie gasi wyboru
    assert [o for o, chip in widok.e_typ.chipy.items() if chip.selected] == [PRZED]

    widok.zapisz(None)

    assert [(z["strefa"], z["typ"]) for z in db.zdjecia_karoserii_pojazdu(auto_id)] == [("Tył", PRZED)] * 2


def test_router_wpuszcza_na_obchod_tylko_z_prawem_dodawania(baza, monkeypatch):
    monkeypatch.setattr(ft, "run", lambda *a, **k: None)
    import main

    assert main._cel_trasy(["karoseria", "obchod"]) == (True, True, None, None)
    assert main._cel_trasy(["karoseria"]) == (False, False, None, None)


class _AparatNaNiby:
    def __init__(self, dane):
        self.dane = dane

    async def take_picture(self):
        return self.dane


def test_obchod_aparatem_idzie_strefa_po_strefie(baza, monkeypatch):
    import flet_camera

    monkeypatch.setattr(utils, "wibracja", lambda *a, **k: None)
    auto_id = _auto()
    strona = pomoce.zbuduj_strone()
    strona.page.platform = ft.PagePlatform.ANDROID
    trasy = []
    strona.page.on_route_change = lambda e: trasy.append(strona.page.route)
    _strona, widok = _widok(auto_id, "ObchodKaroseriiView", strona)

    assert isinstance(widok.aparat, flet_camera.Camera)
    assert audyty.znajdz_expand_bez_ograniczenia(widok) == []
    assert audyty.znajdz_expand_w_kontenerze(widok) == []

    asyncio.run(widok._migawka(None))
    assert db.zdjecia_karoserii_pojazdu(auto_id) == [], "spust przed uruchomieniem aparatu nic nie robi"

    widok.aparat = _AparatNaNiby(pomoce.jpeg())
    widok._gotowy = True
    kolejne = []
    for _ in db.STREFY_OBCHODU:
        asyncio.run(widok._migawka(None))
        kolejne.append(widok.strefa)

    assert kolejne == list(db.STREFY_OBCHODU[1:]) + [db.STREFY_OBCHODU[-1]]
    assert "Obchód kompletny" in widok.komunikat.value
    zapisane = db.zdjecia_karoserii_pojazdu(auto_id)
    assert sorted(z["strefa"] for z in zapisane) == sorted(db.STREFY_OBCHODU)
    assert {z["data"] for z in zapisane} == {datetime.now().strftime("%d.%m.%Y")}

    widok._ustaw_strefe("Uszkodzenie / Rysa")
    asyncio.run(widok._migawka(None))
    assert widok.strefa == "Uszkodzenie / Rysa", "poza obchodem strefa zostaje"

    widok._gotowe(None)
    assert trasy[-1] == "/karoseria"


def test_obchod_na_komputerze_proponuje_formularz(baza):
    _strona, widok = _widok(_auto(), "ObchodKaroseriiView")
    assert widok.aparat is None and "Aparat działa na telefonie" in _napisy(widok)


@pytest.mark.parametrize("strefa", db.STREFY_KAROSERII)
def test_kazda_strefa_ma_podpowiedz_obchodu(strefa):
    from views.obchod_view import WSKAZOWKI_STREF

    assert WSKAZOWKI_STREF[strefa]


def test_wybrane_zdjecia_to_siatka_miniatur_z_kaflem_dodaj(baza, tmp_path):
    strona = pomoce.zbuduj_strone()
    sciezki = []
    for i in range(3):
        sciezka = tmp_path / f"w{i}.jpg"
        sciezka.write_bytes(pomoce.jpeg())
        sciezki.append(str(sciezka))

    async def pick_files(**_):
        return [types.SimpleNamespace(path=s) for s in sciezki + [sciezki[0]]]

    strona.page.zalacznik_picker = types.SimpleNamespace(pick_files=pick_files)
    kontener, pobierz = utils.komponent_wielu_nowych_zdjec(strona.page)
    (siatka,) = pomoce.kontrolki(kontener, ft.ResponsiveRow)
    assert len(siatka.controls) == 1 and siatka.controls[0].on_click, "na starcie sam kafel „Dodaj”"

    asyncio.run(siatka.controls[0].on_click(None))
    assert pobierz() == sciezki, "ten sam plik drugi raz nie wchodzi"
    assert len(siatka.controls) == 4 and all(k.aspect_ratio == 1 for k in siatka.controls)
    assert "Wybrane: 3 zdjęcia" in _napisy(kontener)

    (usun,) = pomoce.kontrolki(siatka.controls[1], ft.IconButton)
    usun.on_click(None)
    assert pobierz() == sciezki[1:] and len(siatka.controls) == 3
