"""Kolory tagów: karty wpisów, filtr „Tagi”, wyszukiwarka i edytor tagów.

Kolor tagu wybiera użytkownik, a długo był tylko kolorem napisu na bladym tle:
chip wyglądał jak chip kategorii, a żółty i limonkowy ginęły na jasnej karcie.
Teraz tag ma PEŁNY kolor, a napis dobiera się do jasności tła.

Testy pilnują czterech rzeczy:
* napis na każdym kolorze palety jest czytelny (kontrast WCAG co najmniej 4,5:1);
* tag trafia w swój kolor niezależnie od pisowni we wpisie („myjnia” = „MYJNIA”),
  a tag spoza słownika NIE udaje żadnego koloru;
* filtr „Tagi” i wyszukiwarka mówią tym samym kolorem co karta;
* edytor proponuje nieużyty kolor i zapisuje tag pisownią ze słownika.
"""

import flet as ft
import pytest

import db
import pomoce
import utils
from views.search_view import SzukajView


POLA_DZIECI = ("controls", "content", "items", "actions", "leading", "trailing", "title", "subtitle")

HEX = utils.HEX_KOLOROW


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


def chipy_tagow(korzen, nazwy):
    """{nazwa: chip} — kontenery, których treścią jest sam napis z nazwą tagu."""
    return {k.content.value: k for k in _wszystkie(korzen, ft.Container)
            if isinstance(k.content, ft.Text) and k.content.value in nazwy}


def pojazd(nazwa, **tagi):
    """Pojazd z utworz_pojazd (ma już tag „Trasa” w kolorze #FF0000) plus tagi
    podane jako nazwa=kolor."""
    auto_id = pomoce.utworz_pojazd(nazwa)["auto_id"]
    for nazwa_tagu, kolor in tagi.items():
        db.dodaj_tag(auto_id, nazwa_tagu, kolor)
    return auto_id


def dodaj_koszt(auto_id, nazwa, tagi, kwota=40.0, kategoria=""):
    with db.polacz_baze() as conn:
        conn.execute(
            "INSERT INTO inne_koszty (auto_id, data, kategoria, nazwa, kwota, tagi) VALUES (?,?,?,?,?,?)",
            (auto_id, "05.09.2026", kategoria, nazwa, kwota, tagi))


# --------------------------------------------------------------- paleta


def test_paleta_tagow_zna_kazdy_kolor_do_wyboru():
    assert set(HEX) == set(utils.MAPA_KOLOROW) == set(db.KOLORY_MOTYWU)
    assert sorted(db.KOLEJNOSC_KOLOROW_TAGOW) == sorted(db.KOLORY_MOTYWU)
    assert db.KOLEJNOSC_KOLOROW_TAGOW[-1] == "Szary", "szary wygląda jak „bez koloru” — idzie na koniec"


@pytest.mark.parametrize("nazwa", db.KOLORY_MOTYWU)
def test_napis_na_kazdym_kolorze_palety_jest_czytelny(nazwa):
    tlo, napis = utils.kolory_chipa_tagu(nazwa)
    assert tlo == HEX[nazwa]
    assert utils.kontrast(tlo, napis) >= 4.5, f"{nazwa}: napis {napis} na {tlo} jest nieczytelny"


def test_jasne_kolory_dostaja_ciemny_napis_a_ciemne_bialy():
    for nazwa in ("Żółty", "Limonkowy", "Różowy", "Pomarańczowy"):
        assert utils.kolory_chipa_tagu(nazwa)[1] == utils.NAPIS_CIEMNY, nazwa
    for nazwa in ("Indygo", "Fioletowy"):
        assert utils.kolory_chipa_tagu(nazwa)[1] == utils.NAPIS_JASNY, nazwa


@pytest.mark.parametrize("kolor,tlo", [("#ff0000", "#FF0000"), ("2196F3", "#2196F3")])
def test_kolor_zapisany_jako_hex_tez_dziala(kolor, tlo):
    assert utils.kolory_chipa_tagu(kolor)[0] == tlo


@pytest.mark.parametrize("kolor", [None, "", "blue", "#12345", "#GGGGGG"])
def test_nieznany_kolor_to_brak_koloru(kolor):
    assert utils.kolory_chipa_tagu(kolor) is None


# --------------------------------------------------------------- słownik


def test_kolor_tagu_nie_zalezy_od_pisowni_we_wpisie(baza):
    auto_id = pojazd("Pisownia", MYJNIA="Zielony")
    mapa = db.mapa_kolorow_tagow(auto_id)
    for pisownia in ("MYJNIA", "myjnia", " Myjnia ", "myjnia."):
        assert db.kolor_tagu(mapa, pisownia) == "Zielony", pisownia
    assert db.kolor_tagu(mapa, "Opony") is None


def test_nowy_tag_dostaje_pierwszy_wolny_kolor(baza):
    auto_id = pojazd("Wolne kolory")
    assert db.pierwszy_wolny_kolor_tagu(auto_id) == "Niebieski"
    db.dodaj_tag(auto_id, "Myjnia", "Niebieski")
    db.dodaj_tag(auto_id, "Opony", "Zielony")
    assert db.pierwszy_wolny_kolor_tagu(auto_id) == "Pomarańczowy"


def test_gdy_paleta_sie_skonczy_kolory_ida_od_nowa(baza):
    auto_id = pojazd("Pełna paleta")
    for numer, kolor in enumerate(db.KOLEJNOSC_KOLOROW_TAGOW):
        db.dodaj_tag(auto_id, f"Tag {numer}", kolor)
    ile = len(db.pobierz_tagi(auto_id))
    assert db.pierwszy_wolny_kolor_tagu(auto_id) == db.KOLEJNOSC_KOLOROW_TAGOW[ile % len(db.KOLEJNOSC_KOLOROW_TAGOW)]


# --------------------------------------------------------------- karty wpisów


def test_chip_tagu_ma_pelny_kolor_i_czytelny_napis():
    chip = utils.chip_tagu("Myjnia", "Żółty")
    assert chip.bgcolor == HEX["Żółty"]
    assert chip.content.color == utils.NAPIS_CIEMNY
    assert chip.content.weight == "bold"


def test_tag_bez_koloru_nie_udaje_niebieskiego():
    chip = utils.chip_tagu("Paliwo", None)
    assert chip.bgcolor is None
    assert chip.border is not None
    assert chip.content.color == ft.Colors.ON_SURFACE_VARIANT


def test_karty_innych_kosztow_maja_kolory_tagow(baza):
    auto_id = pojazd("Karty", UBEZPIECZENIE="Czerwony", MYJNIA="Limonkowy")
    dodaj_koszt(auto_id, "OC", "ubezpieczenie,Paliwo", 900.0, "Ubezpieczenie")
    dodaj_koszt(auto_id, "Mycie", "MYJNIA", 40.0, "Myjnia i kosmetyka")
    stan = pomoce.stan_aplikacji(auto_id, "Karty")
    stan.zakladka = 2
    stan.koszty_podzakladka = 1

    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(), stan)
    chipy = chipy_tagow(widok.lista_kart_inne, {"ubezpieczenie", "MYJNIA", "Paliwo"})

    assert chipy["ubezpieczenie"].bgcolor == HEX["Czerwony"], "pisownia z wpisu trafia w kolor ze słownika"
    assert chipy["MYJNIA"].bgcolor == HEX["Limonkowy"]
    assert chipy["Paliwo"].bgcolor is None, "tagu spoza słownika nie malujemy na niebiesko"


def test_karty_tankowan_maja_kolor_z_danych(baza):
    """Dane testowe zapisują kolor jako #RRGGBB — też ma trafić na kartę."""
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_historia")
    stan.zakladka = 2
    stan.koszty_podzakladka = 0

    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(), stan)
    chipy = chipy_tagow(widok.lista_kart_tankowania, {"Miasto", "Urlop"})

    assert chipy["Miasto"].bgcolor == "#2196F3"
    assert chipy["Urlop"].bgcolor == "#4CAF50"


def test_inne_koszty_maja_filtr_tagow_obok_kategorii(baza):
    auto_id = pojazd("Filtr innych", MYJNIA="Zielony")
    dodaj_koszt(auto_id, "Mycie", "MYJNIA")
    stan = pomoce.stan_aplikacji(auto_id, "Filtr innych")
    stan.zakladka = 2
    stan.koszty_podzakladka = 1

    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(), stan)
    filtry = [p.tooltip for p in _wszystkie(widok, ft.PopupMenuButton) if str(p.tooltip).startswith("Filtruj po:")]

    assert filtry.index("Filtruj po: Tagi") == filtry.index("Filtruj po: Kategoria") + 1


# --------------------------------------------------------------- filtr „Tagi”


def opcje_menu(chip):
    """{opcja: kółko albo None} z rozwijanego menu chipa."""
    wynik = {}
    for poz in chip.content.items:
        teksty = [k for k in poz.content.controls if isinstance(k, ft.Text)]
        kolka = [k for k in poz.content.controls if isinstance(k, ft.Container)]
        wynik[teksty[0].value] = kolka[0] if kolka else None
    return wynik


DANE_TAGOW = [{"tagi": "myjnia"}, {"tagi": "Myjnia,Paliwo"}, {"tagi": ""}]


def test_menu_filtra_tagow_ma_kolka_w_kolorach(baza):
    auto_id = pojazd("Menu", Myjnia="Zielony")
    stan = pomoce.stan_aplikacji(auto_id)

    chipy, _ = utils.pasek_filtrow(pomoce.zbuduj_strone().page, stan, DANE_TAGOW, [("tag", "t_tag", "tagi")])
    opcje = opcje_menu(chipy[0])

    assert opcje[utils.WSZYSTKO] is None
    assert opcje["Myjnia"].bgcolor == HEX["Zielony"]
    assert opcje["myjnia"].bgcolor == HEX["Zielony"]
    assert opcje["Paliwo"].bgcolor is None and opcje["Paliwo"].border is not None


def test_wlaczony_filtr_tagu_ma_kolor_tagu(baza):
    auto_id = pojazd("Włączony", Myjnia="Żółty")
    stan = pomoce.stan_aplikacji(auto_id)
    stan.filtry["t_tag"] = "Myjnia"

    chipy, wynik = utils.pasek_filtrow(pomoce.zbuduj_strone().page, stan, DANE_TAGOW, [("tag", "t_tag", "tagi")])
    tlo, napis = utils.kolory_chipa_tagu("Żółty")
    teksty = [k for k in chipy[0].content.content.controls if isinstance(k, ft.Text)]

    assert chipy[0].bgcolor == tlo
    assert teksty[0].color == napis
    assert wynik == [DANE_TAGOW[1]]


def test_wlaczony_tag_bez_koloru_wyglada_jak_zwykly_filtr(baza):
    auto_id = pojazd("Bez koloru")
    strona = pomoce.zbuduj_strone()
    stan_tag = pomoce.stan_aplikacji(auto_id)
    stan_tag.filtry["f"] = "Paliwo"
    stan_kat = pomoce.stan_aplikacji(auto_id)
    stan_kat.filtry["f"] = "Paliwo"

    tag, _ = utils.pasek_filtrow(strona.page, stan_tag, DANE_TAGOW, [("tag", "f", "tagi")])
    kat, _ = utils.pasek_filtrow(strona.page, stan_kat, DANE_TAGOW, [("kategoria", "f", "tagi", "Tagi")])

    assert tag[0].bgcolor == kat[0].bgcolor


@pytest.mark.parametrize("wybrany", [utils.WSZYSTKO, "myjnia", "Myjnia", "Paliwo"])
def test_filtr_tagow_odsiewa_tak_jak_kategoria(baza, wybrany):
    auto_id = pojazd("Jak kategoria", Myjnia="Zielony")
    strona = pomoce.zbuduj_strone()
    stan_tag = pomoce.stan_aplikacji(auto_id)
    stan_tag.filtry["f"] = wybrany
    stan_kat = pomoce.stan_aplikacji(auto_id)
    stan_kat.filtry["f"] = wybrany

    _, wynik_tag = utils.pasek_filtrow(strona.page, stan_tag, DANE_TAGOW, [("tag", "f", "tagi")])
    _, wynik_kat = utils.pasek_filtrow(strona.page, stan_kat, DANE_TAGOW, [("kategoria", "f", "tagi")])

    assert wynik_tag == wynik_kat


# --------------------------------------------------------------- wyszukiwarka


def test_wyniki_wyszukiwania_niosa_tagi_zamiast_dopisywac_je_do_opisu(baza):
    auto_id = pojazd("Szukanie", MYJNIA="Limonkowy")
    dodaj_koszt(auto_id, "Myjnia ręczna", "MYJNIA", 47.0)

    tekstowe = [w for w in db.globalne_wyszukiwanie(auto_id, "ręczna") if w["typ"] == "Inny koszt"]
    po_kwocie = [w for w in db.globalne_wyszukiwanie(auto_id, ">46") if w["tytul"] == "Myjnia ręczna"]

    for wynik in (tekstowe[0], po_kwocie[0]):
        assert wynik["tagi"] == "MYJNIA"
        assert "MYJNIA" not in wynik["opis"], "tag stoi na karcie jako chip — w opisie byłby drugi raz"


def test_karta_wyniku_ma_tagi_w_kolorach(baza, monkeypatch):
    auto_id = pojazd("Karta wyniku", MYJNIA="Limonkowy")
    dodaj_koszt(auto_id, "Myjnia ręczna", "myjnia")
    strona = pomoce.zbuduj_strone()
    widok = SzukajView(strona.page, pomoce.stan_aplikacji(auto_id, "Karta wyniku"))
    widok._strona_testowa = strona
    monkeypatch.setattr(widok, "update", lambda *a, **k: None)

    widok.pole_wyszukiwarki.value = "ręczna"
    widok._wyszukaj(None)

    assert chipy_tagow(widok.lista_wynikow, {"myjnia"})["myjnia"].bgcolor == HEX["Limonkowy"]


# --------------------------------------------------------------- edytor tagów


@pytest.fixture
def edytor(monkeypatch):
    """Buduje komponent_tagow; okna dialogowe lądują na liście zamiast na stronie."""
    otwarte = []
    monkeypatch.setattr(utils.komponenty, "otworz_dialog", lambda page, dlg: otwarte.append(dlg))
    monkeypatch.setattr(utils.komponenty, "zamknij_dialog", lambda page, dlg: None)
    strony = []

    def zbuduj(auto_id, tagi_wpisu):
        strona = pomoce.zbuduj_strone()
        strony.append(strona)
        kontener, pobierz = utils.komponent_tagow(strona.page, pomoce.stan_aplikacji(auto_id), tagi_wpisu)
        return kontener, pobierz, otwarte

    return zbuduj


def napis(chip):
    return [k for k in chip.content.controls if isinstance(k, ft.Text)][-1].value


def chip_o_napisie(kontener, tekst):
    return [c for c in kontener.controls if isinstance(c.content, ft.Row) and napis(c) == tekst][0]


def kolka(okno):
    return okno.content.controls[2].controls


def test_edytor_sprowadza_tag_wpisu_do_pisowni_slownika(baza, edytor):
    auto_id = pojazd("Edytor", MYJNIA="Zielony")
    kontener, pobierz, _ = edytor(auto_id, "myjnia")

    assert pobierz() == "MYJNIA"
    assert chip_o_napisie(kontener, "MYJNIA").bgcolor == HEX["Zielony"], "zaznaczony = pełny kolor, jak na karcie"
    assert chip_o_napisie(kontener, "Trasa").bgcolor is None, "niezaznaczony = sama obwódka"


def test_tag_spoza_slownika_widac_w_edytorze_takze_po_odznaczeniu(baza, edytor):
    auto_id = pojazd("Sierota")
    kontener, pobierz, _ = edytor(auto_id, "Paliwo")
    assert pobierz() == "Paliwo"

    chip_o_napisie(kontener, "Paliwo").on_click(None)

    assert pobierz() == ""
    assert chip_o_napisie(kontener, "Paliwo") is not None


def test_nowy_tag_proponuje_wolny_kolor_i_trafia_w_slownik(baza, edytor):
    auto_id = pojazd("Nowy tag", MYJNIA="Niebieski")
    kontener, pobierz, otwarte = edytor(auto_id, "")

    kontener.controls[-1].on_click(None)  # „Nowy”
    okno = otwarte[-1]
    zaznaczone = [k.tooltip for k in kolka(okno) if k.content is not None]

    assert len(kolka(okno)) == len(db.KOLORY_MOTYWU), "tag musi mieć kolor — bez pozycji „Brak”"
    assert zaznaczone == [db.pierwszy_wolny_kolor_tagu(auto_id)] == ["Zielony"]

    okno.content.controls[0].value = "myjnia"
    okno.actions[-1].on_click(None)

    assert pobierz() == "MYJNIA", "istniejący tag inną pisownią — wpis dostaje nazwę ze słownika"
    assert [n for _, n, _ in db.pobierz_tagi(auto_id) if db.klucz_nazwy(n) == "myjnia"] == ["MYJNIA"]


def test_przytrzymanie_tagu_spoza_slownika_nadaje_mu_kolor(baza, edytor):
    auto_id = pojazd("Nadaj kolor")
    kontener, pobierz, otwarte = edytor(auto_id, "Paliwo")

    chip_o_napisie(kontener, "Paliwo").on_long_press(None)
    okno = otwarte[-1]
    assert okno.content.controls[0].value == "Paliwo"
    [k for k in kolka(okno) if k.tooltip == "Fioletowy"][0].on_click(None)
    okno.actions[-1].on_click(None)

    assert db.kolor_tagu(db.mapa_kolorow_tagow(auto_id), "Paliwo") == "Fioletowy"
    assert pobierz() == "Paliwo"
    assert chip_o_napisie(kontener, "Paliwo").bgcolor == HEX["Fioletowy"]


def test_edycja_tagu_z_kolorem_spoza_palety_nie_gubi_koloru(baza, edytor):
    """„Trasa” ma kolor #FF0000, którego nie ma wśród kółek. Zapis bez nowego
    wyboru nie może wpisać pustego koloru (kolumna jest NOT NULL)."""
    auto_id = pojazd("Kolor spoza palety")
    kontener, _, otwarte = edytor(auto_id, "")

    chip_o_napisie(kontener, "Trasa").on_long_press(None)
    otwarte[-1].actions[-1].on_click(None)

    assert db.kolor_tagu(db.mapa_kolorow_tagow(auto_id), "Trasa") == "#FF0000"


def test_wybor_koloru_pojazdu_zostaje_z_pozycja_brak():
    wiersz, pobierz = utils.komponent_wyboru_koloru(pomoce.zbuduj_strone().page, "Żółty")
    zolty = [k for k in wiersz.controls if k.tooltip == "Żółty"][0]

    assert len(wiersz.controls) == len(db.KOLORY_MOTYWU) + 1
    assert zolty.content.color == utils.NAPIS_CIEMNY, "biały ptaszek ginął na żółtym"
    assert pobierz() == "Żółty"
