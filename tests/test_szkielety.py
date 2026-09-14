"""Szkielet ekranu: zarys zamiast pustki, dopóki treść się nie policzy.

Ekrany z wykresami i długimi listami budują się kilkaset milisekund. Przez ten
czas nie widać NIC — a pustka wygląda dokładnie tak samo jak zepsuty ekran.
Zarys mówi „liczy się".

Te testy pilnują przede wszystkim tego, żeby ułatwienie dla oka nie zmieniło
tego, co ekran w końcu pokazuje: treść po dobudowie musi być identyczna z tą,
którą ekran narysowałby bez szkieletu, i musi powstać DOKŁADNIE RAZ.
"""

import asyncio

import flet as ft
import pytest

import db
import pomoce
import utils


def kontrolki(kontrolka, limit=20000):
    zebrane = []
    do_odwiedzenia = [kontrolka]
    while do_odwiedzenia and len(zebrane) < limit:
        biezaca = do_odwiedzenia.pop()
        zebrane.append(biezaca)
        for nazwa in ("controls", "content", "appbar", "floating_action_button"):
            wartosc = getattr(biezaca, nazwa, None)
            if isinstance(wartosc, (list, tuple)):
                do_odwiedzenia.extend(w for w in wartosc if isinstance(w, ft.Control))
            elif isinstance(wartosc, ft.Control):
                do_odwiedzenia.append(wartosc)
    return zebrane


def teksty(kontrolka):
    return [k.value for k in kontrolki(kontrolka) if isinstance(k, ft.Text)]


@pytest.fixture
def z_petla(monkeypatch):
    """Udaje działającą pętlę zdarzeń i zbiera zaplanowane zadania, żeby test
    mógł je wykonać wtedy, kiedy chce."""
    zaplanowane = []
    monkeypatch.setattr(utils.szkielet, "_petla_dziala", lambda strona: True)
    monkeypatch.setattr(ft.Page, "run_task", lambda self, handler, *a, **k: zaplanowane.append(handler))
    monkeypatch.setattr(ft.Page, "update", lambda self, *kontrolki: None)
    return zaplanowane


# ============================================================================
#  KLOCKI
# ============================================================================

def test_zarys_rusza_sie_bez_pomocy_pythona():
    """W chwili, gdy szkielet jest na ekranie, pętla zdarzeń liczy treść i nie ma
    kiedy animować. Dlatego każdy klocek to ProgressBar w trybie NIEOKREŚLONYM —
    ruch rysuje Flutter po swojej stronie."""
    paski = [k for k in kontrolki(utils.szkielet_ekranu(None, kafle=2, wykres=True, karty=2))
             if isinstance(k, ft.ProgressBar)]

    assert paski, "szkielet bez ani jednego klocka nie ma czego pokazać"
    assert all(p.value is None for p in paski), "klocek z wartością stałby nieruchomo"


def test_zarys_ma_ksztalt_tego_co_nadejdzie():
    """Zarys w kształcie treści sprawia, że po podmianie nic nie przeskakuje."""
    sama_lista = utils.szkielet_ekranu(None, karty=3)
    z_wykresem = utils.szkielet_ekranu(None, kafle=4, wykres=True, karty=3)

    assert len(kontrolki(z_wykresem)) > len(kontrolki(sama_lista))
    assert len(kontrolki(utils.szkielet_listy(None, ile=5))) > len(kontrolki(utils.szkielet_listy(None, ile=2)))


# ============================================================================
#  DWA ETAPY
# ============================================================================

def test_bez_petli_zdarzen_tresc_powstaje_od_razu():
    """Budowa bez okna (testy, audyty) ma widzieć prawdziwą zawartość, a nie
    zarys — inaczej szkielet przykryłby wszystko, co te testy sprawdzają."""
    kontener = utils.zbuduj_etapami(None, ft.Text("zarys"), lambda: ft.Text("treść"))

    assert kontener.content.value == "treść"


def test_z_petla_najpierw_zarys_potem_tresc(z_petla):
    strona = pomoce.zbuduj_strone()
    kontener = utils.zbuduj_etapami(strona.page, ft.Text("zarys"), lambda: ft.Text("treść"))

    assert kontener.content.value == "zarys"
    assert z_petla, "dobudowa ma zostać zaplanowana"

    asyncio.run(z_petla[0]())

    assert kontener.content.value == "treść"


def test_tresc_buduje_sie_dokladnie_raz(z_petla):
    strona = pomoce.zbuduj_strone()
    wywolania = []
    kontener = utils.zbuduj_etapami(
        strona.page, ft.Text("zarys"), lambda: (wywolania.append(1), ft.Text("treść"))[1]
    )

    asyncio.run(z_petla[0]())

    assert wywolania == [1]
    assert kontener.content.value == "treść"


def test_po_zbudowaniu_dostaje_glos_dopiero_po_tresci(z_petla):
    """`po_zbudowaniu` poprawia to, co zależy od treści, a leży poza nią —
    na przykład przycisk dodawania."""
    strona = pomoce.zbuduj_strone()
    kolejnosc = []
    utils.zbuduj_etapami(
        strona.page, ft.Text("zarys"),
        lambda: (kolejnosc.append("treść"), ft.Text("treść"))[1],
        po_zbudowaniu=lambda: kolejnosc.append("po"),
    )

    asyncio.run(z_petla[0]())

    assert kolejnosc == ["treść", "po"]


def test_blad_w_tresci_zostawia_zarys_zamiast_pustki(z_petla):
    """Ekran, który się nie policzył, ma nadal wyglądać jak ekran — pusty wygląda
    tak samo jak zepsuty."""
    strona = pomoce.zbuduj_strone()

    def wybuchowa():
        raise RuntimeError("nie dziś")

    kontener = utils.zbuduj_etapami(strona.page, ft.Text("zarys"), wybuchowa)
    asyncio.run(z_petla[0]())

    assert kontener.content.value == "zarys"


# ============================================================================
#  PIERWSZEŃSTWO DLA EKRANU NA WIERZCHU
# ============================================================================

def test_widok_pod_spodem_ustepuje_temu_na_wierzchu():
    """Router dokłada ekran główny POD każdy inny ekran. Gdyby ten pod spodem
    zaczął liczyć pierwszy, zablokowałby pętlę i użytkownik czekałby na ekran,
    którego nie widzi."""
    strona = pomoce.zbuduj_strone()
    spod, wierzch = ft.View(), ft.View()
    strona.page.views = [spod, wierzch]

    assert utils.szkielet._pod_spodem(strona.page, spod) is True
    assert utils.szkielet._pod_spodem(strona.page, wierzch) is False
    assert utils.szkielet._pod_spodem(strona.page, ft.View()) is False, "widok spoza stosu nie czeka"
    assert utils.szkielet._pod_spodem(strona.page, None) is False


# ============================================================================
#  EKRANY
# ============================================================================

def zbuduj(nazwa, stan, strona=None, identyfikatory=None):
    return pomoce.zbuduj_widok(
        pomoce.klasy_widokow()[nazwa], strona or pomoce.zbuduj_strone(), stan, identyfikatory
    )


@pytest.mark.parametrize("zakladka", [0, 1, 2, 3])
def test_zakladka_pokazuje_zarys_zanim_policzy_tresc(baza, z_petla, zakladka):
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    stan.zakladka = zakladka

    widok = zbuduj("MainView", stan)
    zarys = widok.przelacznik_zakladek.kontrolka.content.content

    paski = [k for k in kontrolki(zarys) if isinstance(k, ft.ProgressBar)]
    assert paski and all(p.value is None for p in paski), "na ekranie ma stać ruchomy zarys"

    for zadanie in list(z_petla):
        asyncio.run(zadanie())

    assert isinstance(widok.przelacznik_zakladek.kontrolka.content.content.content, ft.Column)


def test_zakladka_po_dobudowie_ma_te_sama_tresc_co_bez_szkieletu(baza, monkeypatch):
    """Sprawdzian końcowy: szkielet nie ma prawa zmienić tego, co ekran pokazuje."""
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    stan.zakladka = 2
    db.zapisz_animacje_interfejsu(False)

    bez_szkieletu = teksty(zbuduj("MainView", stan))

    zaplanowane = []
    monkeypatch.setattr(utils.szkielet, "_petla_dziala", lambda strona: True)
    monkeypatch.setattr(ft.Page, "run_task", lambda self, handler, *a, **k: zaplanowane.append(handler))
    monkeypatch.setattr(ft.Page, "update", lambda self, *kontrolki: None)

    widok = zbuduj("MainView", stan)
    assert teksty(widok) != bez_szkieletu, "przed dobudową na ekranie stoi sam zarys"

    for zadanie in list(zaplanowane):
        asyncio.run(zadanie())

    assert teksty(widok) == bez_szkieletu


def test_przycisk_dodawania_dostawia_sie_po_zbudowaniu_zakladki(baza, z_petla):
    """FAB powstaje razem z treścią zakładki, czyli już PO tym, jak widok trafił
    na ekran — bez dostawienia zostałby na nim przycisk z poprzedniej zakładki
    albo żaden."""
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    stan.zakladka = 1

    widok = zbuduj("MainView", stan)
    assert widok.floating_action_button is None, "zarys nie zna jeszcze przycisku"

    for zadanie in list(z_petla):
        asyncio.run(zadanie())

    assert widok.floating_action_button is not None


@pytest.mark.parametrize("nazwa", [
    "RokWPigulceView", "TimelineView", "OdczytyPrzebieguView", "MagazynView",
])
def test_ciezkie_ekrany_pokazuja_zarys(baza, z_petla, nazwa):
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_historia")

    widok = zbuduj(nazwa, stan)

    paski = [k for k in kontrolki(widok) if isinstance(k, ft.ProgressBar) and k.value is None]
    assert paski, f"{nazwa} nie pokazuje zarysu"

    for zadanie in list(z_petla):
        asyncio.run(zadanie())

    assert len(kontrolki(widok)) > len(paski), "po dobudowie ekran ma mieć treść, nie sam zarys"


def test_historia_podzespolu_pokazuje_zarys(baza, z_petla):
    stan, identyfikatory = pomoce.przygotuj_scenariusz("pojazd_z_danymi")

    widok = zbuduj("HistoriaView", stan, identyfikatory=identyfikatory)

    assert [k for k in kontrolki(widok) if isinstance(k, ft.ProgressBar) and k.value is None]

    for zadanie in list(z_petla):
        asyncio.run(zadanie())

    assert teksty(widok), "po dobudowie ekran ma mieć napisy"
