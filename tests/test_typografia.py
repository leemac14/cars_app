"""Hierarchia wagi pisma: pogrubienie znaczy „wartość albo nagłówek”.

`weight="bold"` bywało w tym projekcie domyślną wagą etykiet — w chwili pisania
tych testów 247 razy. Kiedy wszystko jest ważne, nic nie jest, a najbardziej
boli to na kaflach kokpitu i kartach list, gdzie w małej przestrzeni stoi po
pięć elementów i oko nie ma się o co zaczepić.

Audyt chodzi DWIEMA drogami, bo jedna nie wystarcza:

* po **kodzie źródłowym** (AST) — łapie parę zapisaną wprost w wywołaniu;
* po **zbudowanym drzewie** kontrolek — łapie parę, która powstaje dopiero
  w czasie działania, gdy kolor przychodzi zmienną albo spod `.get(...)`.
  To ta druga droga znalazła „Brak wpisów" pogrubione i przygaszone naraz,
  bo zmienna `kol` akurat wyszła na ON_SURFACE_VARIANT — z kodu nie dało się
  tego zobaczyć.

Plik ma cztery części:

1. **Pomocniki** (`utils.etykieta`, `wartosc`, `podpis`, `pole`) — czy naprawdę
   składają to, co obiecują. Reguła zapisana w helperze jest warta tyle, ile
   helper.
2. **Audyty na syntetycznym kodzie i drzewie** — przypadki, o których z góry
   wiadomo, czy są błędne. Audyt bez własnych testów cicho przestaje cokolwiek
   znajdować i nikt tego nie zauważa, bo zielono.
3. **Audyt AST na prawdziwym kodzie** — ma nie znaleźć nic.
4. **Audyt drzewa na prawdziwych widokach** — jak wyżej, na tym, co się rysuje.
"""

import textwrap

import flet as ft
import pytest

import audyty
import pomoce
import utils


# ============================================================================
#  1. POMOCNIKI
# ============================================================================

def test_etykieta_jest_przygaszona_i_zwyklej_wagi():
    t = utils.etykieta("Dystans")
    assert t.weight is None, "etykieta pogrubiona to właśnie to, co ten moduł usuwa"
    assert t.color == ft.Colors.ON_SURFACE_VARIANT
    assert t.size == utils.FS["caption"]


def test_wartosc_jest_pogrubiona_i_bez_narzuconego_koloru():
    """Kolor wartości niesie znaczenie (czerwień wydatku, zieleń terminu),
    więc domyślnie żadnego nie narzucamy — zostaje sama waga."""
    t = utils.wartosc("412 km")
    assert t.weight == "bold"
    assert t.color is None
    assert t.size == utils.FS["body_strong"]


def test_podpis_wyglada_jak_etykieta_ale_stoi_sam():
    t = utils.podpis("2026-09-13 • Orlen")
    assert t.weight is None
    assert t.color == ft.Colors.ON_SURFACE_VARIANT


@pytest.mark.parametrize("buduj", [utils.etykieta, utils.wartosc, utils.podpis])
def test_pomocnik_ustepuje_temu_co_poda_wywolujacy(buduj):
    t = buduj("cokolwiek", size=17, no_wrap=True, expand=True)
    assert (t.size, t.no_wrap, t.expand) == (17, True, True)


@pytest.mark.parametrize("buduj", [utils.etykieta, utils.wartosc, utils.podpis])
def test_pomocnik_przepuszcza_gotowa_kontrolke(buduj):
    """Liczba z animacji wejścia przychodzi jako gotowy `ft.Text` zbudowany
    przez scenę — wywołujący nie ma obowiązku rozróżniać tych przypadków."""
    gotowa = ft.Text("już zbudowane")
    assert buduj(gotowa) is gotowa


def test_pole_sklada_etykiete_nad_wartoscia():
    kolumna = utils.pole("Dystans", "412 km")
    nazwa, liczba = kolumna.controls

    assert (nazwa.value, nazwa.weight) == ("Dystans", None)
    assert (liczba.value, liczba.weight) == ("412 km", "bold")


def test_pole_oddaje_nadpisania_wartosci():
    """Etykieta nie ma czego nadpisywać — kolor i rozmiar dotyczą liczby."""
    kolumna = utils.pole("Koszt", "-120 zł", color=ft.Colors.RED_700)

    assert kolumna.controls[0].color == ft.Colors.ON_SURFACE_VARIANT
    assert kolumna.controls[1].color == ft.Colors.RED_700


# ============================================================================
#  2. AUDYT NA SYNTETYCZNYM KODZIE
# ============================================================================

def _audyt(tmp_path, kod):
    sciezka = tmp_path / "probka.py"
    sciezka.write_text(textwrap.dedent(kod), encoding="utf-8")
    return audyty.audyt_pogrubien([sciezka], korzen=tmp_path)


PRZYPADKI = [
    (
        "pogrubiona etykieta w kolorze drugiego planu",
        'x = ft.Text("Dystans", size=11, weight="bold", color=ft.Colors.ON_SURFACE_VARIANT)',
        1,
    ),
    (
        "etykieta zwyklej wagi",
        'x = ft.Text("Dystans", size=11, color=ft.Colors.ON_SURFACE_VARIANT)',
        0,
    ),
    (
        "pogrubiona wartosc bez koloru",
        'x = ft.Text("412 km", weight="bold")',
        0,
    ),
    (
        "pogrubiona wartosc w kolorze znaczacym",
        'x = ft.Text("-120 zl", weight="bold", color=ft.Colors.RED_700)',
        0,
    ),
    (
        "waga warunkowa — pogrubienie tylko w pelnym kolorze",
        'x = ft.Text(m, weight="bold" if biezacy else "normal",\n'
        '            color=ft.Colors.PRIMARY if biezacy else ft.Colors.ON_SURFACE_VARIANT)',
        0,
    ),
    (
        "waga warunkowa, ale kolor zawsze przygaszony",
        'x = ft.Text(m, weight="bold" if pilne else "w700", color=ft.Colors.ON_SURFACE_VARIANT)',
        1,
    ),
    (
        "kolor spod .get() — nie do rozstrzygniecia, wiec przepuszczamy",
        'x = ft.Text(m, weight="bold", color=KOLORY.get(z, ft.Colors.ON_SURFACE_VARIANT))',
        0,
    ),
    (
        "zapis przez ft.FontWeight",
        'x = ft.Text(m, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE_VARIANT)',
        1,
    ),
    (
        "etykieta nadpisana pogrubieniem",
        'x = utils.etykieta("Dystans", weight="bold")',
        1,
    ),
    (
        "podpis nadpisany pogrubieniem",
        'x = utils.podpis(data, weight="bold")',
        1,
    ),
    (
        "wartosc przygaszona do drugiego planu",
        'x = utils.wartosc("412 km", color=ft.Colors.ON_SURFACE_VARIANT)',
        1,
    ),
    (
        "wartosc w kolorze znaczacym",
        'x = utils.wartosc("-120 zl", color=ft.Colors.RED_700)',
        0,
    ),
    (
        "inna kontrolka z ta sama para",
        'x = ft.ElevatedButton("Zapisz", weight="bold", color=ft.Colors.ON_SURFACE_VARIANT)',
        0,
    ),
]


@pytest.mark.parametrize(
    "nazwa, kod, oczekiwane",
    PRZYPADKI,
    ids=[p[0].replace(" ", "_").replace("—", "-") for p in PRZYPADKI],
)
def test_audyt_pogrubien_rozpoznaje_przypadek(nazwa, kod, oczekiwane, tmp_path):
    znaleziska = _audyt(tmp_path, kod)
    assert len(znaleziska) == oczekiwane, f"{nazwa}: {znaleziska}"


def test_audyt_drzewa_lapie_pare_powstala_w_czasie_dzialania():
    """Dokładnie ten przypadek, którego AST nie widzi: kolor przychodzi zmienną."""
    kolor = ft.Colors.ON_SURFACE_VARIANT
    drzewo = ft.Column([
        ft.Text("Olej silnikowy", size=16, weight="bold"),
        ft.Text("Brak wpisów", size=14, weight="bold", color=kolor),
    ])

    znaleziska = audyty.znajdz_pogrubienia_na_drugim_planie(drzewo)

    assert len(znaleziska) == 1
    assert znaleziska[0]["tekst"] == "Brak wpisów"
    assert "Column" in znaleziska[0]["sciezka"], "bez ścieżki znalezisko jest zagadką"


def test_audyt_drzewa_przepuszcza_pogrubienie_w_pelnym_kolorze():
    kolor = ft.Colors.RED_700
    drzewo = ft.Column([ft.Text("Po terminie", weight="bold", color=kolor)])

    assert audyty.znajdz_pogrubienia_na_drugim_planie(drzewo) == []


def test_audyt_drzewa_przepuszcza_przygaszona_etykiete():
    drzewo = ft.Column([utils.etykieta("Dystans"), utils.wartosc("412 km")])

    assert audyty.znajdz_pogrubienia_na_drugim_planie(drzewo) == []


def test_audyt_podaje_plik_i_linie(tmp_path):
    """Komunikat bez miejsca to zagadka, a nie znalezisko."""
    znaleziska = _audyt(tmp_path, """
        import flet as ft

        def karta():
            return ft.Text("Dystans", weight="bold", color=ft.Colors.ON_SURFACE_VARIANT)
    """)

    assert znaleziska[0]["plik"] == "probka.py"
    assert znaleziska[0]["linia"] == 5


# ============================================================================
#  3. AUDYT NA PRAWDZIWYM KODZIE
# ============================================================================

def test_pogrubienie_nie_chodzi_w_parze_z_kolorem_drugiego_planu():
    """Przygaszony kolor mówi „drugi plan”, pogrubienie mówi „pierwszy”.
    Postawione razem znoszą się i zostaje sam szum."""
    znaleziska = audyty.audyt_pogrubien()
    assert znaleziska == [], (
        "\n".join(f"{z['plik']}:{z['linia']} — {z['opis']}" for z in znaleziska)
        + "\n\nEtykiety składa utils.etykieta() / utils.podpis(), wartości "
        "utils.wartosc(), a parę „nazwa nad liczbą” — utils.pole(). Jeśli to "
        "miejsce naprawdę jest nagłówkiem, zostaw pogrubienie i zdejmij "
        "przygaszenie: nagłówek ma być czytelny, nie przyciszony."
    )


# ============================================================================
#  4. AUDYT DRZEWA NA PRAWDZIWYCH WIDOKACH
# ============================================================================

# Te same dwa układy danych, co w tests/test_audyty.py: pusty garaż rysuje stany
# puste (to właśnie one najczęściej wychodzą przygaszone i pogrubione naraz),
# pełny pojazd rysuje wszystkie listy, chipy i paski.
SCENARIUSZE = ["pusty_garaz", "pojazd_z_historia"]

# Ekran główny to cztery ekrany pod jedną klasą, a dwa z nich mają podzakładki.
UKLADY_EKRANU_GLOWNEGO = [
    (0, 0, 0),  # Kokpit
    (1, 0, 0),  # Serwis
    (2, 0, 0),  # Koszty / Tankowania
    (2, 1, 0),  # Koszty / Inne
    (3, 0, 0),  # Analiza / miesiące
    (3, 0, 1),  # Analiza / lata
]


def _opis(znaleziska):
    return "\n".join(f"  {z['tekst']!r} — {z['sciezka']}" for z in znaleziska)


@pytest.mark.parametrize("scenariusz", SCENARIUSZE)
@pytest.mark.parametrize("nazwa_widoku", list(pomoce.klasy_widokow()))
def test_widok_nie_laczy_pogrubienia_z_drugim_planem(baza, nazwa_widoku, scenariusz):
    stan, identyfikatory = pomoce.przygotuj_scenariusz(scenariusz)
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()[nazwa_widoku], pomoce.zbuduj_strone(), stan, identyfikatory)

    znaleziska = audyty.znajdz_pogrubienia_na_drugim_planie(widok)

    assert znaleziska == [], (
        "pogrubione i przygaszone naraz:\n" + _opis(znaleziska)
        + "\n\nNajczęstsza przyczyna: kolor przychodzi zmienną, która przy braku "
        "danych wychodzi na ON_SURFACE_VARIANT. Wtedy waga też ma zależeć od tego "
        "samego warunku — „Brak wpisów” nie jest wartością."
    )


@pytest.mark.parametrize("zakladka, podzakladka_kosztow, podzakladka_statystyk", UKLADY_EKRANU_GLOWNEGO)
def test_ekran_glowny_nie_laczy_pogrubienia_z_drugim_planem(baza, zakladka, podzakladka_kosztow, podzakladka_statystyk):
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_historia")
    stan.zakladka = zakladka
    stan.koszty_podzakladka = podzakladka_kosztow
    stan.stat_podzakladka = podzakladka_statystyk
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(), stan)

    znaleziska = audyty.znajdz_pogrubienia_na_drugim_planie(widok)

    assert znaleziska == [], "pogrubione i przygaszone naraz:\n" + _opis(znaleziska)
