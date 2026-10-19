"""Nagłówki miesięcy na długich listach.

Tankowania z trzech lat to jedna taśma dat — przy dwustu wpisach nie wiadomo,
gdzie się jest. Separator dzieli taśmę, a gdy lista przewinie się pod górną
krawędź, pasek przyklejony u góry ekranu mówi, w którym miesiącu jesteśmy teraz.

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
    lista = lista if lista is not None else ft.Column(spacing=15)
    return utils.GrupyMiesiecy(None, lista, **kw), lista


class Rozmiar:
    """Zdarzenie `on_size_change` listy — tylko wysokość."""

    def __init__(self, height):
        self.height = height


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


def test_jeden_miesiac_tez_dostaje_separator(baza):
    """Przyklejony pasek pokazuje się dopiero, gdy lista dojedzie do góry ekranu —
    do tej chwili miesiąc mówi tylko separator, także przy jednym miesiącu."""
    g, lista = nowa()

    g.ustaw(pozycje(("2026-09-10", 100), ("2026-09-03", 50)))

    assert grupy(lista) == ["Wrzesień 2026"]
    assert len(lista.controls) == 3
    assert g.kontrolka.visible is False
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
#  PORCJE — długa lista nie buduje się cała naraz
# ============================================================================

def przyciski_kolejnych(lista):
    return [k.content for k in lista.controls
            if isinstance(k, ft.Container) and isinstance(k.content, ft.OutlinedButton)]


def sto_wpisow():
    """Sto wpisów po jednym dziennie wstecz od 30 września 2026 — kilka miesięcy."""
    from datetime import date, timedelta
    return pozycje(*[((date(2026, 9, 30) - timedelta(days=i)).isoformat(), 10) for i in range(100)])


def test_dluga_lista_rysuje_porcje_a_reszte_odslania_przycisk(baza):
    """Lista przewija się z ekranem, więc Flutter buduje każdą kartę — przy setkach
    tankowań ekran stawał się kilka razy wolniejszy. Najpierw porcja, potem przycisk."""
    g, lista = nowa(porcja=40)

    g.ustaw(sto_wpisow())

    assert len(karty_na_liscie(lista)) == 40 + 1, "40 kart i kontener przycisku"
    (przycisk,) = przyciski_kolejnych(lista)
    assert przycisk.content == "Pokaż kolejne 40 z 60"
    assert g._opis.value.startswith("30 wpisów"), "podsumowanie miesiąca liczy wszystkie wpisy"

    g._pokaz_kolejne()
    assert len([k for k in karty_na_liscie(lista) if isinstance(k, ft.Text)]) == 80
    g._pokaz_kolejne()
    assert len([k for k in karty_na_liscie(lista) if isinstance(k, ft.Text)]) == 100
    assert przyciski_kolejnych(lista) == []


def test_bez_grupowania_tez_porcjami():
    g, lista = nowa(porcja=10)

    g.ustaw(sto_wpisow(), grupuj=False)

    assert len(lista.controls) == 11 and przyciski_kolejnych(lista)


def test_rozwiniecie_przezywa_przebudowe_ekranu(baza):
    """Akcja na wpisie przebudowuje ekran — rozwinięta lista ma zostać rozwinięta,
    inaczej powrót na zapamiętaną pozycję trafiałby w przycisk zamiast we wpis."""
    stan = pomoce.stan_aplikacji(1, "Auto")
    widok = type("W", (), {"state": stan})()
    g, _ = nowa(porcja=40, widok=widok, klucz="tankowania")
    g.ustaw(sto_wpisow())
    g._pokaz_kolejne()

    drugi, lista = nowa(porcja=40, widok=widok, klucz="tankowania")
    drugi.ustaw(sto_wpisow())

    assert len([k for k in karty_na_liscie(lista) if isinstance(k, ft.Text)]) == 80


def test_po_rozlozeniu_wola_sie_tez_po_odslonieciu(baza):
    """Oś czasu poprawia końcówki kreski po każdym ułożeniu — także po „Pokaż kolejne”."""
    ulozenia = []
    g, _ = nowa(porcja=40, po_rozlozeniu=ulozenia.append)

    g.ustaw(sto_wpisow())
    g._pokaz_kolejne()

    assert len(ulozenia) == 2
    assert sum(len(w) for _, w in ulozenia[-1]) == 80


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


def test_pasek_czeka_az_lista_dojedzie_do_gory(baza):
    """Lista przewija się razem z ekranem: nad nią 500 px nagłówka (filtry,
    wyszukiwarka). Pasek nie może zasłaniać nagłówka — pojawia się dopiero, gdy
    pierwszy separator schowa się pod górną krawędzią, i od razu zna miesiąc."""
    g, _ = nowa(wysokosc_pozycji=100, ogon=40)
    g.ustaw(pozycje(("2026-09-10", 1), ("2026-09-03", 1), ("2026-08-28", 1), ("2026-07-05", 1)))
    lista = g._wysokosc_szacowana
    g._zmierzona(Rozmiar(lista))
    calosc = 500 + lista + 40

    g._przewiniete(Przewiniecie(300, calosc - 800, 800))
    assert g.kontrolka.visible is False, "pasek zasłaniałby filtry nad listą"

    g._przewiniete(Przewiniecie(500 + 10, calosc - 800, 800))
    assert g.kontrolka.visible is True
    assert g._tytul.value == "Wrzesień 2026"

    g._przewiniete(Przewiniecie(500 + g._offsety[1][0], calosc - 800, 800))
    assert g._tytul.value == "Sierpień 2026"


def test_pomiar_listy_skaluje_szacunek(baza):
    """Karty wyszły dwa razy wyższe od szacunku — mnożnik bierze się z prawdziwej
    wysokości LISTY, więc nagłówek nad nią nie psuje rachunku."""
    g, _ = nowa(wysokosc_pozycji=100, ogon=0)
    g.ustaw(pozycje(("2026-09-10", 1), ("2026-08-28", 1), ("2026-07-05", 1)))
    lista = g._wysokosc_szacowana * 2
    g._zmierzona(Rozmiar(lista))

    g._przewiniete(Przewiniecie(300 + g._offsety[2][0] * 2, 300 + lista - 700, 700))

    assert g._tytul.value == "Lipiec 2026"
    assert g.kontrolka.visible is True


def test_bez_pomiaru_pasek_sie_nie_pokazuje(baza):
    """Dopóki Flutter nie podał wysokości listy, nie wiadomo, gdzie ona się zaczyna —
    lepiej bez paska niż z paskiem na nagłówku ekranu."""
    g, _ = nowa(wysokosc_pozycji=100)
    g.ustaw(pozycje(("2026-09-10", 1), ("2026-08-28", 1)))

    g._przewiniete(Przewiniecie(400, 1000, 400))

    assert g.kontrolka.visible is False


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

    assert widok.przewijana_tresc.miejsce.content is widok.miesiace_tankowania.kontrolka
    assert widok.przewijana_tresc.miejsce.visible is True
    assert grupy(widok.lista_kart_tankowania)
    assert len(karty_na_liscie(widok.lista_kart_tankowania)) == len(widok.wszystkie_karty_tankowania)


def test_zmiana_zakladki_zdejmuje_pasek(baza):
    """Pasek tankowań nie może zostać nad Kokpitem — przełączenie zakładki w miejscu
    zdejmuje go z góry ekranu."""
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_historia")
    stan.zakladka = 2
    stan.koszty_podzakladka = 0
    stan.sort["tankowania"] = ("data", True)
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(), stan)

    widok.przelacz_zakladke(0)

    assert widok.przewijana_tresc.miejsce.visible is False
    assert widok.przewijana_tresc.miejsce.content is None


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
    assert widok.przewijana_tresc.miejsce.content is grupator.kontrolka, "pasek nie trafił na górę ekranu"


def test_os_czasu_urywa_linie_na_granicy_miesiaca(baza):
    """Oś to ciągła kreska między zdarzeniami. Nagłówek ją przerywa, więc linia
    musi urywać się przed nim i zaczynać po nim — inaczej wystaje w tło."""
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_historia")

    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["TimelineView"], pomoce.zbuduj_strone(), stan)
    wynik = widok.miesiace.ustaw(widok.wszystkie_karty, grupuj=True)
    for _, wiersze in wynik:
        widok._popraw_koncowki_osi(wiersze)

    # Wiersz osi musi nieść datę — bez niej cała oś lądowała w jednej grupie bez nagłówków.
    assert len(wynik) > 1 and all(klucz is not None for klucz, _ in wynik)

    for _, wiersze in wynik:
        if not wiersze:
            continue
        assert wiersze[0]["gora"].bgcolor == ft.Colors.TRANSPARENT
        assert wiersze[-1]["dol"].bgcolor == ft.Colors.TRANSPARENT
