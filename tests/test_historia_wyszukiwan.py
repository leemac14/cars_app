"""Ostatnie wyszukiwania: co wchodzi do historii i co z niej wypada.

Szuflada pamięta ostatnio otwierane ekrany, bo rzeczy używanych raz na miesiąc
nie pamięta się między sesjami; wyszukiwarka dostała to samo. Cała trudność jest
w tym, KIEDY zapisać: pole szuka przy każdej literze, więc naiwny zapis zrobiłby
z historii zapis pisania na klawiaturze („mar”, „marz”, „marze”, „marzec”).
Dlatego fraza wchodzi dopiero przy otwarciu wyniku albo przy rozpoznanym
filtrze z wynikami, a fraza, której początkiem jest fraza już zapisana, tamtą
wypiera. Te dwie reguły mają tu testy, bo ich złamanie niczego nie wywraca —
tylko po cichu zaśmieca listę.
"""

import pytest

import db
import pomoce


@pytest.fixture
def pojazd(baza):
    return pomoce.utworz_pojazd(z_zalacznikami=False)["auto_id"]


# ------------------------------------------------------------ warstwa danych


def test_najswiezsza_fraza_jest_pierwsza(baza):
    db.zanotuj_wyszukiwanie("olej")
    db.zanotuj_wyszukiwanie("stacja:orlen")
    assert db.pobierz_ostatnie_wyszukiwania() == ["stacja:orlen", "olej"]


def test_dluzsza_fraza_wypiera_swoj_poczatek(baza):
    """Pisanie „marzec 2026” przechodzi przez „marzec” — w historii ma zostać
    to, co użytkownik naprawdę chciał."""
    for etap in ("marzec", "marzec 2", "marzec 2026"):
        db.zanotuj_wyszukiwanie(etap)
    assert db.pobierz_ostatnie_wyszukiwania() == ["marzec 2026"]


def test_powtorzona_fraza_nie_dubluje_sie_tylko_wraca_na_gore(baza):
    db.zanotuj_wyszukiwanie("olej")
    db.zanotuj_wyszukiwanie("opony")
    db.zanotuj_wyszukiwanie("OLEJ")
    assert db.pobierz_ostatnie_wyszukiwania() == ["OLEJ", "opony"]


def test_lista_nie_rosnie_ponad_limit(baza):
    for numer in range(db.MAKS_OSTATNICH_WYSZUKIWAN + 3):
        db.zanotuj_wyszukiwanie(f"fraza {numer}")
    frazy = db.pobierz_ostatnie_wyszukiwania()
    assert len(frazy) == db.MAKS_OSTATNICH_WYSZUKIWAN
    assert frazy[0] == f"fraza {db.MAKS_OSTATNICH_WYSZUKIWAN + 2}"
    assert "fraza 0" not in frazy


def test_jednoznakowa_fraza_nie_wchodzi(baza):
    db.zanotuj_wyszukiwanie("o")
    assert db.pobierz_ostatnie_wyszukiwania() == []


def test_kasowanie_pojedynczej_frazy_i_calej_listy(baza):
    db.zanotuj_wyszukiwanie("olej")
    db.zanotuj_wyszukiwanie("opony")

    assert db.usun_ostatnie_wyszukiwanie("  OLEJ ") == ["opony"]

    db.wyczysc_ostatnie_wyszukiwania()
    assert db.pobierz_ostatnie_wyszukiwania() == []


def test_wylaczony_przelacznik_nic_nie_zapisuje_i_nic_nie_pokazuje(baza):
    db.zanotuj_wyszukiwanie("olej")
    db.zapisz_zapamietywanie_wyszukiwan(False)

    assert db.pobierz_ostatnie_wyszukiwania() == []
    db.zanotuj_wyszukiwanie("opony")

    db.zapisz_zapamietywanie_wyszukiwan(True)
    assert db.pobierz_ostatnie_wyszukiwania() == ["olej"], "nic nie doszło przy wyłączonym"


# ------------------------------------------------------------ ekran /szukaj


@pytest.fixture
def ekran(pojazd, monkeypatch):
    from views.search_view import SzukajView

    strona = pomoce.zbuduj_strone()
    widok = SzukajView(strona.page, pomoce.stan_aplikacji(pojazd, "Testowy"))
    # Strona trzyma sesję przez weakref — musi żyć tak długo jak widok.
    widok._strona_testowa = strona
    monkeypatch.setattr(widok, "update", lambda *a, **k: None)
    return widok


def _chipy(widok):
    return widok.sekcja_ostatnich.controls[1].controls if widok.sekcja_ostatnich.visible else []


def _szukaj(widok, fraza):
    widok.pole_wyszukiwarki.value = fraza
    widok._wyszukaj(None)


def test_chipy_stoja_tylko_przy_pustym_polu(ekran):
    db.zanotuj_wyszukiwanie("stacja:orlen")

    _szukaj(ekran, "olej")
    assert not ekran.sekcja_ostatnich.visible, "w trakcie pisania miejsce należy się wynikom"

    _szukaj(ekran, "")
    assert ekran.sekcja_ostatnich.visible
    assert len(_chipy(ekran)) == 1


def test_otwarcie_wyniku_zapamietuje_fraze(ekran, monkeypatch):
    import utils

    monkeypatch.setattr(utils, "przejdz", lambda *a, **k: None)
    _szukaj(ekran, "Filtr oleju")
    assert ekran.lista_wynikow.controls, "„Filtr oleju” trafia w część z magazynu"

    ekran.lista_wynikow.controls[0].content.on_click(None)

    assert db.pobierz_ostatnie_wyszukiwania() == ["Filtr oleju"]


def test_filtr_z_wynikami_zapamietuje_sie_sam(ekran):
    """„luty 2026” przegląda się w całości, nie otwierając żadnego wpisu."""
    _szukaj(ekran, "luty 2026")
    assert db.pobierz_ostatnie_wyszukiwania() == ["luty 2026"]


def test_fraza_bez_wynikow_nie_zasmieca_historii(ekran):
    _szukaj(ekran, "marzec 2031")
    _szukaj(ekran, "czegotuniema")
    assert db.pobierz_ostatnie_wyszukiwania() == []


def test_chip_powtarza_wyszukiwanie(ekran):
    db.zanotuj_wyszukiwanie("stacja:orlen")
    _szukaj(ekran, "")

    _chipy(ekran)[0].on_click(None)

    assert ekran.pole_wyszukiwarki.value == "stacja:orlen"
    assert ekran.lista_wynikow.controls
    assert not ekran.sekcja_ostatnich.visible


def test_dlugie_przytrzymanie_kasuje_chip_a_przycisk_cala_liste(ekran):
    db.zanotuj_wyszukiwanie("olej")
    db.zanotuj_wyszukiwanie("opony")
    _szukaj(ekran, "")

    _chipy(ekran)[0].on_long_press(None)
    assert db.pobierz_ostatnie_wyszukiwania() == ["olej"]
    assert len(_chipy(ekran)) == 1

    ekran.sekcja_ostatnich.controls[0].controls[2].on_click(None)
    assert db.pobierz_ostatnie_wyszukiwania() == []
    assert not ekran.sekcja_ostatnich.visible
