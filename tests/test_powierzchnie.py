"""Powierzchnie kart: mniej sygnałów, więcej szczebli.

Ramka, wypełnienie, zaokrąglenie i cień to cztery sposoby powiedzenia „to jest
osobny obiekt”. Użyte na wszystkim naraz spłaszczają hierarchię — jeśli każda
karta krzyczy tak samo głośno, to ważna karta niczym się nie wyróżnia.

W chwili pisania tych testów drabinka `tlo_karty` miała trzy szczeble, z czego
używany był jeden: 103 ze 119 powierzchni siedziało na poziomie 1, a poziom 3
nie pojawiał się nigdzie. Reszta ekranów wymyślała własne odcienie — 0,04, 0,05,
0,06, 0,10, 0,14 — czyli szczeble, których na drabince nie ma.

Plik ma trzy części:

1. **Role i drabinka** — czy `utils.powierzchnia` naprawdę składa to, co obiecuje,
   w każdym z trzech motywów.
2. **Audyt na syntetycznym drzewie** — przypadki, o których z góry wiadomo, czy
   są błędne. Audyt bez własnych testów cicho przestaje cokolwiek znajdować.
3. **Prawdziwe widoki** — audyt ma nie znaleźć nic, a kokpit ma podnosić dokładnie
   te kafle, które mają coś do powiedzenia.
"""

import collections

import db
import flet as ft
import pytest

import audyty
import pomoce
import utils


class StronaMotywu:
    """Najmniejsza rzecz, na której `_czy_ciemny` potrafi się wypowiedzieć."""

    def __init__(self, tryb):
        self.theme_mode = tryb


JASNY = StronaMotywu(ft.ThemeMode.LIGHT)
CIEMNY = StronaMotywu(ft.ThemeMode.DARK)


@pytest.fixture
def oled(monkeypatch):
    """Wariant czystej czerni bez zaglądania do bazy."""
    monkeypatch.setitem(utils.wyglad._CACHE_CZERNI, "wartosc", True)
    return CIEMNY


# ============================================================================
#  1. ROLE I DRABINKA
# ============================================================================

@pytest.mark.parametrize("page", [JASNY, CIEMNY], ids=["jasny", "ciemny"])
def test_szczeble_drabinki_sa_rozroznialne(page):
    """Trzy szczeble, trzy różne jasności — inaczej „stopień wyżej” niczego nie
    mówi."""
    tla = [str(utils.tlo_karty(page, poziom=p)) for p in (1, 2, 3)]

    assert len(set(tla)) == 3, tla


def test_poza_drabinka_nie_ma_nic():
    assert utils.tlo_karty(JASNY, poziom=0) == ft.Colors.TRANSPARENT
    assert utils.tlo_karty(JASNY, poziom=4) == ft.Colors.TRANSPARENT


def test_karta_w_jasnym_unosi_sie_cieniem():
    plaszczyzna = utils.powierzchnia(JASNY, "karta")

    assert plaszczyzna["shadow"], "w jasnym motywie to cień robi krawędź karty"
    assert plaszczyzna["border"] is None, "cień i ramka to dwa sposoby na to samo"


def test_karta_w_ciemnym_bierze_mocniejsze_tlo_zamiast_cienia():
    """Cienia na ciemnym tle nie widać, więc krawędź musi zrobić jasność."""
    plaszczyzna = utils.powierzchnia(CIEMNY, "karta")

    assert plaszczyzna["shadow"] is None
    assert plaszczyzna["bgcolor"] == utils.tlo_karty(CIEMNY, poziom=2)


def test_karta_w_oled_bierze_ramke_zamiast_cienia(oled):
    """Bez cienia i bez rozjaśnionego tła karta nie miałaby żadnej krawędzi,
    a cały sens trybu OLED polega na zgaszonych pikselach."""
    plaszczyzna = utils.powierzchnia(oled, "karta")

    assert plaszczyzna["shadow"] is None
    assert plaszczyzna["border"] is not None
    assert plaszczyzna["bgcolor"] == utils.tlo_karty(oled, poziom=1)


@pytest.mark.parametrize("page", [JASNY, CIEMNY], ids=["jasny", "ciemny"])
def test_kafel_nie_ma_cienia(page):
    """Siedemnaście cieni obok siebie to szum, a odstępy w siatce i tak już
    mówią, gdzie kończy się jeden kafel."""
    assert utils.powierzchnia(page, "kafel")["shadow"] is None


@pytest.mark.parametrize("page", [JASNY, CIEMNY], ids=["jasny", "ciemny"])
def test_kafel_i_karta_leza_na_tym_samym_szczeblu(page):
    assert utils.powierzchnia(page, "kafel")["bgcolor"] == utils.powierzchnia(page, "karta")["bgcolor"]


@pytest.mark.parametrize("page", [JASNY, CIEMNY], ids=["jasny", "ciemny"])
def test_blok_stoi_stopien_wyzej_od_karty(page):
    """To jedyny sygnał, jakiego blok potrzebuje — jest już w karcie."""
    karta = utils.powierzchnia(page, "karta")
    blok = utils.powierzchnia(page, "blok")

    assert blok["bgcolor"] != karta["bgcolor"]
    assert blok["bgcolor"] == utils.tlo_karty(page, poziom=utils.poziom_karty(page) + 1)
    assert blok["shadow"] is None and blok["border"] is None
    assert blok["border_radius"] < karta["border_radius"], (
        "promień 20 w promieniu 20 powtarza informację, którą oko dostało sekundę wcześniej"
    )


def test_blok_w_karcie_podniesionej_wchodzi_wyzej_od_niej():
    blok = utils.powierzchnia(JASNY, "blok", poziom_rodzica=2)

    assert blok["bgcolor"] == utils.tlo_karty(JASNY, poziom=3)


def test_blok_nie_wychodzi_poza_drabinke():
    """Czwartego szczebla nie ma — powyżej trzeciego zostajemy na trzecim."""
    blok = utils.powierzchnia(JASNY, "blok", poziom_rodzica=utils.NAJWYZSZY_POZIOM)

    assert blok["bgcolor"] == utils.tlo_karty(JASNY, poziom=utils.NAJWYZSZY_POZIOM)


@pytest.mark.parametrize("stan", sorted(utils.STANY_PODNOSZACE))
@pytest.mark.parametrize("rola", ["karta", "kafel"])
def test_stan_barwi_powierzchnie(rola, stan):
    """Ten sam stopień wyżej, tylko wyrażony barwą, która i tak już mówi,
    co się dzieje — a nie szarością OBOK barwy."""
    plaszczyzna = utils.powierzchnia(JASNY, rola, stan=stan)

    assert plaszczyzna["bgcolor"] == utils.tlo_stanu(JASNY, stan)
    assert plaszczyzna["bgcolor"] != utils.powierzchnia(JASNY, rola)["bgcolor"]


@pytest.mark.parametrize("stan", [None, "ok", "neutral", "info", "cost"])
def test_stan_bez_powodu_do_dzialania_nie_podnosi(stan):
    """„Na czas” barwione na zielono krzyczało tak samo głośno jak termin po
    terminie. Brak powodu do działania nie jest powodem do wyróżnienia."""
    assert utils.powierzchnia(JASNY, "kafel", stan=stan)["bgcolor"] == utils.tlo_karty(JASNY, poziom=1)


@pytest.mark.parametrize("stan", sorted(utils.STANY_PODNOSZACE))
def test_stan_z_koloru_wraca_do_nazwy(stan):
    assert utils.stan_z_koloru(utils.KOLOR_STATUS[stan]) == stan


@pytest.mark.parametrize("kolor", [ft.Colors.GREEN_700, ft.Colors.PRIMARY, ft.Colors.BLUE_GREY_700, None])
def test_stan_z_koloru_milczy_przy_kolorze_bez_pilnosci(kolor):
    assert utils.stan_z_koloru(kolor) is None


def test_tor_i_odznaka_maja_po_jednej_wartosci():
    """Pasek budżetu i pasek checklisty pokazują to samo — ile z czegoś minęło —
    więc nie ma powodu, żeby ich tory różniły się jasnością."""
    assert utils.tlo_toru(JASNY) == utils.tlo_toru(CIEMNY)
    assert utils.tlo_odznaki(JASNY) == utils.tlo_odznaki(CIEMNY)
    assert utils.tlo_toru(JASNY) != utils.tlo_odznaki(JASNY)


# ============================================================================
#  2. AUDYT NA SYNTETYCZNYM DRZEWIE
# ============================================================================

def _powierzchnia(page, rola="karta", **nadpisania):
    pola = dict(utils.powierzchnia(page, rola))
    pola.update(nadpisania)
    return ft.Container(**pola)


def test_audyt_lapie_powierzchnie_na_tym_samym_szczeblu():
    wnetrze = _powierzchnia(JASNY, "karta")
    drzewo = _powierzchnia(JASNY, "karta", content=wnetrze)

    znaleziska = audyty.znajdz_plaskie_powierzchnie(drzewo, JASNY)

    assert len(znaleziska) >= 1
    assert "tym samym szczeblu" in znaleziska[0]["powod"]


def test_audyt_przepuszcza_blok_w_karcie():
    drzewo = _powierzchnia(JASNY, "karta", content=_powierzchnia(JASNY, "blok"))

    assert audyty.znajdz_plaskie_powierzchnie(drzewo, JASNY) == []


def test_audyt_lapie_cien_pod_cieniem():
    wnetrze = _powierzchnia(JASNY, "blok", shadow=utils.cien_karty(JASNY, "sm"))
    drzewo = _powierzchnia(JASNY, "karta", content=wnetrze)

    powody = [z["powod"] for z in audyty.znajdz_plaskie_powierzchnie(drzewo, JASNY)]

    assert "cień pod cieniem" in powody


def test_audyt_lapie_cien_i_ramke_naraz():
    drzewo = _powierzchnia(JASNY, "karta", border=ft.Border.all(1, ft.Colors.ON_SURFACE))

    powody = [z["powod"] for z in audyty.znajdz_plaskie_powierzchnie(drzewo, JASNY)]

    assert any("cień i ramka" in p for p in powody)


def test_audyt_nie_uznaje_piguly_ani_toru_za_powierzchnie():
    """Odznaki i tory pasków mają własne, nazwane tła i nie udają kart —
    inaczej audyt zgłaszałby każdy chip w pasku filtrów."""
    drzewo = _powierzchnia(JASNY, "karta", content=ft.Column([
        ft.Container(bgcolor=utils.tlo_odznaki(JASNY), content=ft.Text("autor")),
        ft.ProgressBar(value=0.5, bgcolor=utils.tlo_toru(JASNY)),
    ]))

    assert audyty.znajdz_plaskie_powierzchnie(drzewo, JASNY) == []


def test_audyt_podaje_sciezke():
    """Znalezisko bez miejsca to zagadka, a nie znalezisko."""
    drzewo = _powierzchnia(JASNY, "karta", content=_powierzchnia(JASNY, "karta"))

    assert "Container" in audyty.znajdz_plaskie_powierzchnie(drzewo, JASNY)[0]["sciezka"]


# ============================================================================
#  3. PRAWDZIWE WIDOKI
# ============================================================================

SCENARIUSZE = ["pusty_garaz", "pojazd_z_historia"]

UKLADY_EKRANU_GLOWNEGO = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (2, 1, 0), (3, 0, 0), (3, 0, 1)]


def _opis(znaleziska):
    return "\n".join(f"  {z['powod']}: {z['sciezka']}" for z in znaleziska)


@pytest.mark.parametrize("scenariusz", SCENARIUSZE)
@pytest.mark.parametrize("nazwa_widoku", list(pomoce.klasy_widokow()))
def test_widok_stopniuje_zagniezdzone_powierzchnie(baza, nazwa_widoku, scenariusz):
    stan, identyfikatory = pomoce.przygotuj_scenariusz(scenariusz)
    strona = pomoce.zbuduj_strone()
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()[nazwa_widoku], strona, stan, identyfikatory)

    znaleziska = audyty.znajdz_plaskie_powierzchnie(widok, strona)

    assert znaleziska == [], (
        "powierzchnie powtarzają sygnał rodzica:\n" + _opis(znaleziska)
        + "\n\nKawałek leżący W ŚRODKU karty składa się przez "
        "utils.powierzchnia(page, \"blok\") — bierze wtedy tło o stopień wyżej "
        "i nie dokłada cienia ani ramki."
    )


@pytest.mark.parametrize("zakladka, podzakladka_kosztow, podzakladka_statystyk", UKLADY_EKRANU_GLOWNEGO)
def test_ekran_glowny_stopniuje_zagniezdzone_powierzchnie(baza, zakladka, podzakladka_kosztow, podzakladka_statystyk):
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_historia")
    stan.zakladka = zakladka
    stan.koszty_podzakladka = podzakladka_kosztow
    stan.stat_podzakladka = podzakladka_statystyk
    strona = pomoce.zbuduj_strone()
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], strona, stan)

    znaleziska = audyty.znajdz_plaskie_powierzchnie(widok, strona)

    assert znaleziska == [], _opis(znaleziska)


def _kokpit_z_kompletem(scenariusz):
    stan, _ = pomoce.przygotuj_scenariusz(scenariusz)
    stan.zakladka = 0
    db.zapisz_widgety_kokpitu(list(db.KOKPIT_WIDGETY), stan.auto_id)
    strona = pomoce.zbuduj_strone()
    return strona, pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], strona, stan)


def _tla_kafli(widok, strona):
    """Tła kontenerów kokpitu, zliczone po tym, którym szczeblem drabinki są."""
    drabinka = audyty._drabinka_powierzchni(strona)
    licz = collections.Counter()

    def zejdz(kontrolka):
        tlo = str(getattr(kontrolka, "bgcolor", "") or "")
        if isinstance(kontrolka, ft.Container) and tlo in drabinka:
            licz[drabinka[tlo]] += 1
        for _, dziecko in audyty._dzieci(kontrolka):
            zejdz(dziecko)

    zejdz(widok)
    return licz


def test_kokpit_z_historia_podnosi_kafle_ktore_maja_co_powiedziec(baza):
    """Sedno całej zmiany: kafel wymagający reakcji ma się różnić od kafla
    z zasięgiem czymś więcej niż treścią."""
    strona, widok = _kokpit_z_kompletem("pojazd_z_historia")

    licz = _tla_kafli(widok, strona)

    podniesione = sum(n for klucz, n in licz.items() if klucz.startswith("stan "))
    assert podniesione > 0, f"żaden kafel się nie wybił, a jest co pokazywać: {dict(licz)}"
    assert licz["poziom 1"] > podniesione, (
        "podniosła się większość kafli — wyróżnienie, które dotyczy wszystkich, "
        f"nie wyróżnia niczego: {dict(licz)}"
    )


def test_kokpit_bez_powodow_do_dzialania_zostaje_spokojny(baza):
    """Świeży pojazd nie ma po terminie ani niczego na wyczerpaniu — kokpit ma
    być wtedy równy, a nie kolorowy „na wszelki wypadek”."""
    strona, widok = _kokpit_z_kompletem("pojazd_z_danymi")

    licz = _tla_kafli(widok, strona)

    assert not [k for k in licz if k.startswith("stan ")], dict(licz)
