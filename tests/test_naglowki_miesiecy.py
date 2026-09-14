"""Nagłówki miesięcy na długich listach.

Tankowania z trzech lat to jedna taśma dat — przy dwustu wpisach nie wiadomo,
gdzie się jest. Separator dzieli taśmę, pasek nad listą mówi, w którym miesiącu
jesteśmy teraz.

Dwie rzeczy, których te testy pilnują szczególnie: że przez grupowanie NIC nie
ginie (każda karta, którą widok oddał, ma trafić na listę), i że nagłówki
pojawiają się tylko wtedy, kiedy mówią prawdę — czyli gdy lista naprawdę idzie
po dacie.
"""

import flet as ft
import pytest

import db
import pomoce
import utils


class Przewiniecie:
    """Zdarzenie przewijania w kształcie, w jakim przychodzi z ListView."""

    def __init__(self, pixels, max_scroll_extent=0, viewport_dimension=0):
        self.pixels = pixels
        self.max_scroll_extent = max_scroll_extent
        self.viewport_dimension = viewport_dimension


def pozycje(*wpisy):
    """(data, kwota) → lista pozycji w formacie, jakiego oczekuje GrupyMiesiecy."""
    return [{"karta": ft.Text(f"karta {i}"), "data": d, "kwota": k}
            for i, (d, k) in enumerate(wpisy)]


def grupy(lista, ile_kart=1000):
    """Nazwy miesięcy z separatorów wstawionych do listy, po kolei."""
    nazwy = []
    for k in lista.controls[:ile_kart]:
        if isinstance(k, ft.Container) and k.height == utils.WYSOKOSC_NAGLOWKA:
            nazwy.append(k.content.controls[0].value)
    return nazwy


def nowa(lista=None, **kw):
    lista = lista if lista is not None else ft.ListView(spacing=15)
    return utils.GrupyMiesiecy(None, lista, **kw), lista


# ============================================================================
#  GRUPOWANIE
# ============================================================================

def test_lista_dzieli_sie_na_miesiace(baza):
    g, lista = nowa()

    g.ustaw(pozycje(("2026-09-10", 100), ("2026-09-03", 50), ("2026-08-28", 30)))

    assert grupy(lista) == ["Wrzesień 2026", "Sierpień 2026"]
    assert len(lista.controls) == 5, "trzy karty plus dwa separatory"


def test_kolejnosc_miesiecy_idzie_za_sortowaniem_widoku(baza):
    """Moduł niczego nie sortuje — nazywa to, co widok już ułożył. Lista rosnąco
    ma dać nagłówki rosnąco."""
    g, lista = nowa()

    g.ustaw(pozycje(("2026-07-01", 10), ("2026-08-01", 10), ("2026-09-01", 10)))

    assert grupy(lista) == ["Lipiec 2026", "Sierpień 2026", "Wrzesień 2026"]


def test_jeden_miesiac_nie_dostaje_separatora(baza):
    """Pasek nad listą mówi wtedy dokładnie to samo — separator byłby
    powtórzeniem tego samego napisu dwa razy pod rząd."""
    g, lista = nowa()

    g.ustaw(pozycje(("2026-09-10", 100), ("2026-09-03", 50)))

    assert grupy(lista) == []
    assert len(lista.controls) == 2
    assert g.kontrolka.visible is True
    assert g._tytul.value == "Wrzesień 2026"


def test_bez_grupowania_sa_same_karty():
    """Lista posortowana po kwocie skacze między miesiącami — nagłówek kłamałby
    o tym, co pod nim leży."""
    g, lista = nowa()

    g.ustaw(pozycje(("2026-09-10", 100), ("2026-08-03", 50)), grupuj=False)

    assert grupy(lista) == []
    assert len(lista.controls) == 2
    assert g.kontrolka.visible is False


def test_pusta_lista_chowa_pasek(baza):
    g, lista = nowa()
    g.ustaw(pozycje(("2026-09-10", 100)))

    g.ustaw([])

    assert lista.controls == []
    assert g.kontrolka.visible is False


def test_wpis_bez_czytelnej_daty_nie_ginie(baza):
    """Karta bez daty i tak musi trafić na listę — inaczej wyszukiwarka gubiłaby
    wpisy bez niczyjej winy."""
    g, lista = nowa()

    g.ustaw(pozycje(("2026-09-10", 100), ("", 50), ("2026-08-01", 20)))

    assert len(lista.controls) == 5, "trzy karty plus dwa separatory"


@pytest.mark.parametrize("ile,oczekiwane", [(1, "1 wpis"), (2, "2 wpisy"), (5, "5 wpisów"),
                                            (12, "12 wpisów"), (22, "22 wpisy")])
def test_podsumowanie_odmienia_wpisy_po_polsku(ile, oczekiwane):
    g, _ = nowa()

    g.ustaw(pozycje(*[("2026-09-10", 0)] * ile))

    assert g._opis.value == oczekiwane


def test_podsumowanie_sumuje_kwoty_miesiaca(baza):
    """„Wrzesień 2026 · 2 wpisy · 150 zł” — przewijanie zamienia się w przegląd
    miesięcy, widać który był drogi."""
    g, _ = nowa()

    g.ustaw(pozycje(("2026-09-10", 100), ("2026-09-03", 50)))

    assert g._opis.value.startswith("2 wpisy • 150")


def test_listy_bez_kwot_pokazuja_same_wpisy():
    """W osi czasu i odczytach licznika kwota albo nic nie znaczy, albo miesza
    tankowania z wizytami."""
    g, _ = nowa(pokaz_kwoty=False)

    g.ustaw(pozycje(("2026-09-10", 100), ("2026-09-03", 50)))

    assert g._opis.value == "2 wpisy"


def test_ustaw_zwraca_granice_grup(baza):
    """Oś czasu rysuje ciągłą kreskę między zdarzeniami i musi ją urwać na każdym
    nagłówku — do tego potrzebuje wiedzieć, gdzie przebiegają granice."""
    g, _ = nowa()

    wynik = g.ustaw(pozycje(("2026-09-10", 1), ("2026-09-03", 1), ("2026-08-28", 1)))

    assert [k for k, _ in wynik] == [(2026, 9), (2026, 8)]
    assert [len(w) for _, w in wynik] == [2, 1]


# ============================================================================
#  PRZEWIJANIE
# ============================================================================

def test_pasek_zmienia_miesiac_razem_z_przewijaniem(baza):
    g, lista = nowa(wysokosc_pozycji=100)
    g.ustaw(pozycje(("2026-09-10", 1), ("2026-09-03", 1), ("2026-08-28", 1), ("2026-07-05", 1)))
    # Lista bez skalowania: szacunek jest wtedy prawdą.
    realna = g._wysokosc_szacowana

    assert g._tytul.value == "Wrzesień 2026"

    g._przewiniete(Przewiniecie(g._offsety[1][0], realna - 200, 200))
    assert g._tytul.value == "Sierpień 2026"

    g._przewiniete(Przewiniecie(g._offsety[2][0], realna - 200, 200))
    assert g._tytul.value == "Lipiec 2026"

    g._przewiniete(Przewiniecie(0, realna - 200, 200))
    assert g._tytul.value == "Wrzesień 2026", "powrót na górę wraca do pierwszego miesiąca"


def test_szacunek_skaluje_sie_do_prawdziwej_wysokosci(baza):
    """Karty rosną z treścią, więc nasze wysokości są tylko przybliżeniem.
    Zdarzenie przewijania niesie rzeczywistą wysokość zawartości — iloraz kasuje
    systematyczny błąd, bez którego nagłówek rozjeżdżałby się tym bardziej, im
    dalej w dół."""
    g, _ = nowa(wysokosc_pozycji=100)
    g.ustaw(pozycje(("2026-09-10", 1), ("2026-08-28", 1), ("2026-07-05", 1)))

    # Prawdziwa lista okazuje się DWA RAZY wyższa od oszacowania.
    realna = g._wysokosc_szacowana * 2
    g._przewiniete(Przewiniecie(g._offsety[2][0] * 2, realna - 300, 300))

    assert g._tytul.value == "Lipiec 2026"


def test_przewijanie_bez_grup_nic_nie_psuje():
    g, _ = nowa()
    g.ustaw(pozycje(("2026-09-10", 1)), grupuj=False)

    g._przewiniete(Przewiniecie(500, 1000, 400))

    assert g.kontrolka.visible is False


# ============================================================================
#  KIEDY NAGŁÓWKI MAJĄ SENS
# ============================================================================

def test_czy_po_dacie_patrzy_na_aktualne_sortowanie():
    stan = pomoce.stan_aplikacji(1, "Auto")

    stan.sort["tankowania"] = ("data", True)
    assert utils.czy_po_dacie(stan, "tankowania") is True

    stan.sort["tankowania"] = ("kwota", True)
    assert utils.czy_po_dacie(stan, "tankowania") is False


def test_czy_po_dacie_przyjmuje_wlasne_pole_daty():
    """Lista „Do zrobienia” grupuje się po TERMINIE, a nie po dacie dopisania."""
    stan = pomoce.stan_aplikacji(1, "Auto")

    stan.sort["do_zrobienia"] = ("termin", False)
    assert utils.czy_po_dacie(stan, "do_zrobienia", ("termin",)) is True

    stan.sort["do_zrobienia"] = ("priorytet", False)
    assert utils.czy_po_dacie(stan, "do_zrobienia", ("termin",)) is False


# ============================================================================
#  EKRANY
# ============================================================================

def karty_na_liscie(lista):
    return [k for k in lista.controls
            if not (isinstance(k, ft.Container) and k.height == utils.WYSOKOSC_NAGLOWKA)]


def test_tankowania_dostaja_naglowki_i_pasek(baza):
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_historia")
    stan.zakladka = 2
    stan.koszty_podzakladka = 0
    stan.sort["tankowania"] = ("data", True)

    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(), stan)

    assert widok.miesiace_tankowania.kontrolka.visible is True
    assert len(karty_na_liscie(widok.lista_kart_tankowania)) == len(widok.wszystkie_karty_tankowania)


def test_sortowanie_po_kwocie_gasi_naglowki(baza):
    """Lista ułożona po kwocie skacze między miesiącami — wtedy nagłówków nie ma
    wcale, bo każdy kłamałby o tym, co pod nim leży."""
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_historia")
    stan.zakladka = 2
    stan.koszty_podzakladka = 0
    stan.sort["tankowania"] = ("kwota", True)

    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(), stan)

    assert widok.miesiace_tankowania.kontrolka.visible is False
    assert grupy(widok.lista_kart_tankowania) == []


@pytest.mark.parametrize("nazwa,pole", [
    ("TimelineView", "miesiace"),
    ("OdczytyPrzebieguView", "miesiace"),
    ("WizytyZbiorczeView", "miesiace"),
    ("DoZrobieniaView", "miesiace"),
])
def test_pozostale_listy_maja_grupy_miesiecy(baza, nazwa, pole):
    stan, identyfikatory = pomoce.przygotuj_scenariusz("pojazd_z_historia")

    widok = pomoce.zbuduj_widok(
        pomoce.klasy_widokow()[nazwa], pomoce.zbuduj_strone(), stan, identyfikatory
    )

    grupator = getattr(widok, pole, None)
    assert isinstance(grupator, utils.GrupyMiesiecy), f"{nazwa} nie grupuje listy po miesiącach"
    assert len(karty_na_liscie(grupator.lista)) == len(widok.wszystkie_karty)


def test_os_czasu_urywa_linie_na_granicy_miesiaca(baza):
    """Oś to ciągła kreska między zdarzeniami. Nagłówek ją przerywa, więc linia
    musi urywać się przed nim i zaczynać po nim — inaczej wystaje w tło."""
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_historia")

    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["TimelineView"], pomoce.zbuduj_strone(), stan)
    wynik = widok.miesiace.ustaw(widok.wszystkie_karty, grupuj=True)
    for _, wiersze in wynik:
        widok._popraw_koncowki_osi(wiersze)

    for _, wiersze in wynik:
        if not wiersze:
            continue
        assert wiersze[0]["gora"].bgcolor == ft.Colors.TRANSPARENT
        assert wiersze[-1]["dol"].bgcolor == ft.Colors.TRANSPARENT
