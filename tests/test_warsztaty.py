"""Karta warsztatu: telefon, adres, „Zadzwoń” i „Pokaż na mapie” (M-05).

Rejestr warsztatów był w bazie od sierpnia 2026 bez ekranu — formularze
zapisywały samą nazwę, więc przyciski przy wyborze warsztatu nigdy się nie
pokazywały. Sprawdzamy:

1. **Karty** — rejestr plus nazwy z wizyt, dopasowane po kluczu nazwy;
   „Warsztat” (wizyta bez wykonawcy) karty nie dostaje, pozycja wizyty nie
   dubluje wizyty.
2. **Zapis** — nowa karta, poprawka kontaktu, zmiana nazwy przepisana na wizyty
   i historię; odmowy: nazwa zajęta, zastrzeżona, podgląd, cudze wpisy przy
   współautorze.
3. **Usunięcie** — nagrobek dla synchronizacji, cofnięcie z tym samym zdalne_id.
4. **Mapy** — `geo:` na Androidzie, Google Maps gdzie indziej, schowek awaryjnie.
5. **Ekran, panel, karta wizyty i formularz** — przyciski są tam, gdzie są dane.
"""

import asyncio

import flet as ft
import pytest

import audyty
import db
import pomoce
import utils


def _karta(auto_id, klucz):
    return next((k for k in db.pobierz_karty_warsztatow(auto_id) if k["klucz"] == klucz), None)


def _kontrolki(korzen):
    wynik, do_odwiedzenia = [], [korzen]
    while do_odwiedzenia:
        biezaca = do_odwiedzenia.pop(0)
        wynik.append(biezaca)
        do_odwiedzenia.extend(dziecko for _, dziecko in audyty._dzieci(biezaca))
    return wynik


def _napisy(korzen):
    """Teksty i napisy przycisków w poddrzewie (przycisk trzyma napis w `content`)."""
    napisy = []
    for k in _kontrolki(korzen):
        if isinstance(k, ft.Text) and k.value:
            napisy.append(k.value)
        elif isinstance(getattr(k, "content", None), str):
            napisy.append(k.content)
    return napisy


def _nazwy_wykonawcow(auto_id):
    with db.polacz_baze() as conn:
        wizyty = {r[0] for r in conn.execute("SELECT wykonawca FROM wizyty WHERE auto_id=?", (auto_id,))}
        historia = {r[0] for r in conn.execute(
            "SELECT h.wykonawca FROM historia h JOIN zadania z ON z.id = h.zadanie_id "
            "WHERE z.auto_id=? AND TRIM(COALESCE(h.wykonawca, '')) <> ''", (auto_id,))}
    return wizyty, historia


@pytest.fixture
def pojazd(baza):
    """Pojazd z pomoce.utworz_pojazd: wizyta z pozycją u „Warsztat u Janka”,
    który ma kartę z telefonem. Dokładamy wpis serwisowy poza wizytą (inna
    pisownia tej samej nazwy), wizytę „bez warsztatu” i wizytę w warsztacie,
    który karty nie ma."""
    ident = pomoce.utworz_pojazd(z_zalacznikami=False)
    auto = ident["auto_id"]
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO historia (zadanie_id, data, przebieg, cena, wykonawca) VALUES (?,?,?,?,?)",
                  (ident["zadanie"], "12.03.2026", 104000, 90.0, "warsztat  u janka "))
        c.execute("INSERT INTO wizyty (auto_id, data, przebieg, wykonawca, koszt_calkowity) VALUES (?,?,?,?,?)",
                  (auto, "01.02.2026", 102000, db.WARSZTAT_BEZ_NAZWY, 50.0))
        c.execute("INSERT INTO wizyty (auto_id, data, przebieg, wykonawca, koszt_calkowity) VALUES (?,?,?,?,?)",
                  (auto, "20.12.2025", 99000, "Serwis ASO", 700.0))
        db.przelicz_daty_iso(conn)
    return ident


@pytest.fixture
def cicho(monkeypatch):
    """Strona testowa nie ma żywej sesji — okna i komunikaty tylko zapisujemy."""
    otwarte = []
    monkeypatch.setattr(ft.Page, "update", lambda self, *kontrolki: None)
    for nazwa in ("pokaz_komunikat", "zamknij_dialog", "zamknij_dno"):
        monkeypatch.setattr(utils.warsztaty, nazwa, lambda *a, **k: None)
    monkeypatch.setattr(utils.warsztaty, "otworz_dialog", lambda strona, dlg: otwarte.append(dlg))
    monkeypatch.setattr(utils.warsztaty, "otworz_dno", lambda strona, bs: otwarte.append(bs))
    monkeypatch.setattr(utils.warsztaty, "wypchnij_w_tle", lambda strona, auto_id, powod="zapis": None)
    return otwarte


# ============================================================================
#  1. KARTY
# ============================================================================

def test_karty_lacza_rejestr_z_wizytami_po_kluczu_nazwy(pojazd):
    auto = pojazd["auto_id"]
    janek = _karta(auto, "warsztat u janka")

    assert (janek["id"], janek["telefon"]) == (pojazd["warsztat"], "123456789")
    # Wizyta i wpis poza wizytą; pozycja wizyty to ta sama wizyta.
    assert (janek["wizyt"], janek["wizyt_zbiorczych"]) == (2, 1)
    assert janek["nazwa_na_wizytach"] == "Warsztat u Janka"
    assert janek["ostatnia"] == "12.03.2026"

    aso = _karta(auto, "serwis aso")
    assert (aso["id"], aso["nazwa"], aso["wizyt"]) == (None, "Serwis ASO", 1)

    # „Warsztat” to brak wykonawcy, a nie warsztat.
    assert _karta(auto, "warsztat") is None
    assert [k["klucz"] for k in db.pobierz_karty_warsztatow(auto)] == ["warsztat u janka", "serwis aso"]


def test_wyszukiwarka_prowadzi_do_ekranu_warsztatow(pojazd):
    wyniki = db.globalne_wyszukiwanie(pojazd["auto_id"], "123456789")
    assert [(w["typ"], w["trasa"]) for w in wyniki] == [("Warsztat", "/warsztaty")]


# ============================================================================
#  2. ZAPIS
# ============================================================================

def test_zmiana_nazwy_przechodzi_na_wizyty_i_historie(pojazd):
    auto = pojazd["auto_id"]

    assert db.zapisz_warsztat(auto, pojazd["warsztat"], " Auto-Serwis  Jan ", "61 123 45 67",
                              "Poznań,  Polna 1", "pn–pt 8–16\n") is None

    wizyty, historia = _nazwy_wykonawcow(auto)
    assert wizyty == {"Auto-Serwis Jan", db.WARSZTAT_BEZ_NAZWY, "Serwis ASO"}
    # Także wpis z inną pisownią tej samej nazwy — karta liczyła go jako swój.
    assert historia == {"Auto-Serwis Jan"}
    karta = _karta(auto, "auto-serwis jan")
    assert (karta["id"], karta["wizyt"], karta["telefon"], karta["adres"], karta["notatki"]) == (
        pojazd["warsztat"], 2, "61 123 45 67", "Poznań, Polna 1", "pn–pt 8–16")
    assert _karta(auto, "warsztat u janka") is None


def test_nowa_karta_dla_nazwy_znanej_z_wizyt(pojazd):
    auto = pojazd["auto_id"]

    assert db.zapisz_warsztat(auto, None, "Serwis ASO", "600 100 200", "Konin, Kolejowa 2") is None

    aso = _karta(auto, "serwis aso")
    assert aso["id"] is not None and (aso["telefon"], aso["wizyt"]) == ("600 100 200", 1)
    assert "Serwis ASO" in _nazwy_wykonawcow(auto)[0]


@pytest.mark.parametrize("warsztat, nazwa, fragment", [
    ("janek", " serwis  ASO ", "Na liście jest już „Serwis ASO”"),
    (None, "WARSZTAT U JANKA", "Na liście jest już „Warsztat u Janka”"),
    ("janek", "warsztat", "wpis bez wybranego warsztatu"),
    (None, "   ", "Podaj nazwę"),
])
def test_odmowa_nie_zmienia_niczego(pojazd, warsztat, nazwa, fragment):
    auto = pojazd["auto_id"]
    assert db.zapisz_warsztat(auto, None, "Serwis ASO") is None
    przed = (db.pobierz_warsztaty(auto), _nazwy_wykonawcow(auto))

    blad = db.zapisz_warsztat(auto, pojazd["warsztat"] if warsztat else None, nazwa, "999")

    assert blad and fragment in blad
    assert (db.pobierz_warsztaty(auto), _nazwy_wykonawcow(auto)) == przed


def test_wspolautor_nie_przepisze_cudzych_wizyt(baza):
    ident = pomoce.utworz_pojazd("Wspólne", z_zalacznikami=False, wspolny=True)
    auto = ident["auto_id"]
    db.ustaw_role_pojazdu(auto, db.ROLA_WSPOLAUTOR)
    db.zapisz_moje_imie("Ania")
    with db.polacz_baze() as conn:
        conn.execute("UPDATE wizyty SET dodane_przez='Marek' WHERE auto_id=?", (auto,))

    blad = db.zapisz_warsztat(auto, ident["warsztat"], "Janek i syn", "123456789")
    assert blad and "współautor" in blad
    assert _karta(auto, "warsztat u janka")["id"] == ident["warsztat"]

    # Sam kontakt — wolno: rejestr warsztatów to wspólny słownik pojazdu.
    assert db.zapisz_warsztat(auto, ident["warsztat"], "Warsztat u Janka", "600 100 200", "Konin") is None
    assert _karta(auto, "warsztat u janka")["adres"] == "Konin"

    # Gdy wszystkie wpisy z tą nazwą są moje, zmiana nazwy przechodzi.
    with db.polacz_baze() as conn:
        conn.execute("UPDATE wizyty SET dodane_przez='Ania' WHERE auto_id=?", (auto,))
        conn.execute("UPDATE historia SET dodane_przez='Ania' WHERE zadanie_id IN "
                     "(SELECT id FROM zadania WHERE auto_id=?)", (auto,))
    assert db.zapisz_warsztat(auto, ident["warsztat"], "Janek i syn", "600 100 200", "Konin") is None
    assert _nazwy_wykonawcow(auto)[0] == {"Janek i syn"}


def test_podglad_niczego_nie_zapisze_ani_nie_usunie(baza):
    ident = pomoce.utworz_pojazd("Podgląd", z_zalacznikami=False, wspolny=True)
    auto = ident["auto_id"]
    db.ustaw_role_pojazdu(auto, db.ROLA_PODGLAD)

    assert "tylko do odczytu" in db.zapisz_warsztat(auto, None, "Nowy warsztat", "123")
    assert "tylko do odczytu" in db.zapisz_warsztat(auto, ident["warsztat"], "Warsztat u Janka", "600 100 200")
    assert db.usun_z_cofnieciem("warsztaty", ident["warsztat"]) is None
    assert [(w[0], w[2]) for w in db.pobierz_warsztaty(auto)] == [(ident["warsztat"], "123456789")]


# ============================================================================
#  3. USUNIĘCIE
# ============================================================================

def test_usuniecie_karty_zostawia_nagrobek_a_cofniecie_go_zdejmuje(pojazd):
    auto = pojazd["auto_id"]

    wynik = db.usun_z_cofnieciem("warsztaty", pojazd["warsztat"])

    assert wynik
    with db.polacz_baze() as conn:
        nagrobki = conn.execute("SELECT tabela, zdalny_id, auto_id FROM zdalne_nagrobki").fetchall()
    assert ("warsztaty", "warsztat-1", auto) in nagrobki
    # Wizyty zachowują nazwę — warsztat zostaje na liście, tylko bez karty.
    janek = _karta(auto, "warsztat u janka")
    assert (janek["id"], janek["telefon"], janek["wizyt"]) == (None, None, 2)

    wynik["cofnij"]()

    with db.polacz_baze() as conn:
        nagrobki = conn.execute("SELECT zdalny_id FROM zdalne_nagrobki").fetchall()
        wiersz = conn.execute("SELECT zdalne_id, nazwa, telefon FROM warsztaty WHERE auto_id=?", (auto,)).fetchall()
    assert ("warsztat-1",) not in nagrobki
    assert wiersz == [("warsztat-1", "Warsztat u Janka", "123456789")]
    assert _karta(auto, "warsztat u janka")["id"] is not None


# ============================================================================
#  4. MAPY
# ============================================================================

@pytest.mark.parametrize("platforma, poczatek", [
    ("android", "geo:0,0?q="),
    (ft.PagePlatform.ANDROID, "geo:0,0?q="),
    ("windows", "https://www.google.com/maps/search/?api=1&query="),
    (None, "https://www.google.com/maps/search/?api=1&query="),
])
def test_link_mapy_zalezy_od_systemu(platforma, poczatek):
    assert utils.link_mapy("  Poznań,  Polna 1 ", platforma) == poczatek + "Pozna%C5%84%2C%20Polna%201"


def test_link_mapy_bez_adresu_jest_pusty():
    assert utils.link_mapy("   ", "android") == ""
    assert utils.link_mapy(None) == ""


class _StronaMap:
    """Tyle strony, ile potrzebuje pokaz_na_mapie: platforma, launch_url, run_task."""

    platform = "android"

    def __init__(self, blad=False):
        self.blad = blad
        self.otwarte = []

    def launch_url(self, url):
        if self.blad:
            raise RuntimeError("brak aplikacji map")
        self.otwarte.append(url)

    def run_task(self, zadanie):
        asyncio.run(zadanie())


def test_pokaz_na_mapie_otwiera_link_a_bez_map_kopiuje_adres(monkeypatch):
    skopiowane = []
    monkeypatch.setattr(utils.system, "kopiuj_do_schowka",
                        lambda strona, wartosc, komunikat="": skopiowane.append(wartosc))

    strona = _StronaMap()
    utils.pokaz_na_mapie(strona, "Konin")
    assert strona.otwarte == ["geo:0,0?q=Konin"] and skopiowane == []

    utils.pokaz_na_mapie(_StronaMap(blad=True), "Konin")
    assert skopiowane == ["Konin"]


# ============================================================================
#  5. EKRAN, PANEL, KARTA WIZYTY, FORMULARZ
# ============================================================================

def test_ekran_ma_przyciski_tylko_przy_danych(pojazd):
    from views.warsztaty_view import WarsztatyView

    strona = pomoce.zbuduj_strone()
    widok = WarsztatyView(strona.page, pomoce.stan_aplikacji(pojazd["auto_id"], "Testowy"))
    napisy = _napisy(widok)

    assert napisy.count("Zadzwoń") == 1          # Janek ma telefon
    assert "Pokaż na mapie" not in napisy        # nikt nie ma adresu
    assert "Z historii wizyt — bez karty" in napisy and "Dodaj kartę" in napisy  # Serwis ASO
    assert widok.floating_action_button is not None
    assert audyty.znajdz_expand_bez_ograniczenia(widok) == []
    assert audyty.znajdz_expand_w_kontenerze(widok) == []


def test_podglad_nie_dostaje_fab_ani_dodawania(baza):
    from views.warsztaty_view import WarsztatyView

    ident = pomoce.utworz_pojazd("Podgląd", z_zalacznikami=False, wspolny=True)
    db.ustaw_role_pojazdu(ident["auto_id"], db.ROLA_PODGLAD)
    with db.polacz_baze() as conn:
        conn.execute("INSERT INTO wizyty (auto_id, data, przebieg, wykonawca, koszt_calkowity) VALUES (?,?,?,?,?)",
                     (ident["auto_id"], "20.12.2025", 99000, "Serwis ASO", 700.0))

    strona = pomoce.zbuduj_strone()
    widok = WarsztatyView(strona.page, pomoce.stan_aplikacji(ident["auto_id"], "Podgląd"))
    napisy = _napisy(widok)

    assert widok.floating_action_button is None
    assert "Dodaj kartę" not in napisy and "Zadzwoń" in napisy


def test_karta_wizyty_ma_wiersz_warsztatu(pojazd):
    from views.history_view import WizytyZbiorczeView

    strona = pomoce.zbuduj_strone()
    widok = WizytyZbiorczeView(strona.page, pomoce.stan_aplikacji(pojazd["auto_id"], "Testowy"))
    kontrolki = _kontrolki(widok)

    wiersze = [k for k in kontrolki if isinstance(k, ft.Container) and k.on_click
               and isinstance(k.content, ft.Row) and isinstance(k.content.controls[0], ft.Icon)
               and k.content.controls[0].icon == ft.Icons.CAR_REPAIR]
    telefony = [k for k in kontrolki if isinstance(k, ft.IconButton) and k.tooltip == "Zadzwoń"]
    # Janek i Serwis ASO — „Warsztat” (wizyta bez wykonawcy) wiersza nie dostaje;
    # słuchawka tylko przy warsztacie z telefonem w karcie.
    assert len(wiersze) == 2 and len(telefony) == 1


def test_panel_karty_z_wiersza_wizyty(pojazd, cicho):
    stan = pomoce.stan_aplikacji(pojazd["auto_id"], "Testowy")
    strona = pomoce.zbuduj_strone()

    janek = utils.pokaz_karte_warsztatu(strona.page, stan, "Warsztat u Janka")
    aso = utils.pokaz_karte_warsztatu(strona.page, stan, "Serwis ASO")

    assert {"Warsztat u Janka", "Zadzwoń", "Edytuj dane", "123456789"} <= set(_napisy(janek.content))
    assert {"Serwis ASO", "Bez telefonu i adresu", "Dodaj telefon i adres"} <= set(_napisy(aso.content))
    for panel in (janek, aso):
        assert audyty.znajdz_expand_bez_ograniczenia(panel.content) == []
        assert audyty.znajdz_expand_w_kontenerze(panel.content) == []


def test_formularz_waliduje_i_zapisuje(pojazd, cicho):
    auto = pojazd["auto_id"]
    stan = pomoce.stan_aplikacji(auto, "Testowy")
    strona = pomoce.zbuduj_strone()
    zapisane = []

    dlg = utils.pokaz_formularz_warsztatu(strona.page, stan, _karta(auto, "warsztat u janka"),
                                          po_zapisie=lambda: zapisane.append(True))
    e_nazwa, uwaga, e_telefon, e_adres, _e_notatki = dlg.content.controls
    zapisz = [b for b in dlg.actions if getattr(b, "content", None) == "Zapisz"][0].on_click

    e_telefon.value = "brak"
    zapisz(None)
    assert utils.blad_kontrolki(e_telefon) and not zapisane

    e_telefon.value = "61 123 45 67"
    e_adres.value = "Konin, Kolejowa 2"
    e_nazwa.value = "warsztat"
    zapisz(None)
    assert "wpis bez wybranego warsztatu" in utils.blad_kontrolki(e_nazwa) and not zapisane

    # Zmiana nazwy zapowiada, ile wizyt dostanie nową pisownię.
    e_nazwa.value = "Janek i syn"
    e_nazwa.on_change(None)
    assert uwaga.visible and "2 wizytach" in uwaga.value

    zapisz(None)
    assert zapisane == [True]
    karta = _karta(auto, "janek i syn")
    assert (karta["telefon"], karta["adres"], karta["wizyt"]) == ("61 123 45 67", "Konin, Kolejowa 2", 2)


def test_wybor_warsztatu_w_formularzu_pokazuje_przyciski(pojazd):
    auto = pojazd["auto_id"]
    stan = pomoce.stan_aplikacji(auto, "Testowy")
    strona = pomoce.zbuduj_strone()

    kontener, _ = utils.komponent_wyboru_warsztatu(strona.page, stan, "Warsztat u Janka")
    dzwon, mapa = kontener.controls[1].controls
    assert (dzwon.visible, mapa.visible) == (True, False)

    db.zapisz_warsztat(auto, pojazd["warsztat"], "Warsztat u Janka", "123456789", "Konin, Kolejowa 2")
    kontener, _ = utils.komponent_wyboru_warsztatu(strona.page, stan, "Warsztat u Janka")
    dzwon, mapa = kontener.controls[1].controls
    assert (dzwon.visible, mapa.visible, mapa.content) == (True, True, "Pokaż na mapie")
