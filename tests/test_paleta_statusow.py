"""Paleta statusów: kolor jako kod, a nie dekoracja.

W tej aplikacji kolor niesie informację — czerwień znaczy „po terminie”, bursztyn
„zbliża się”, zieleń „w porządku”. Cała wartość takiego kodu stoi na jednym
warunku: że ten sam odcień znaczy wszędzie to samo. Wystarczy, że w trzech
miejscach czerwień jest inna, a kod zamienia się w dekorację.

W chwili pisania tych testów `KOLOR_STATUS` było użyte 15 razy, a jego wartości
wpisane wprost — 250 razy, w kilku odcieniach obok siebie (`RED` i `RED_700`,
`ORANGE_700` i `ORANGE_800`, bursztyn przy konfliktach synchronizacji).

Plik ma trzy części:

1. **Sama paleta** — czy role istnieją i czy te, które MUSZĄ się różnić, różnią
   się naprawdę. Kilka ról dzieli dziś jeden odcień i to jest zamierzone; testy
   zapisują ten fakt, żeby rozdzielenie ich było świadomą zmianą, a nie
   przypadkiem.
2. **Audyt na syntetycznym kodzie** — przypadki, o których z góry wiadomo, czy
   są błędne. Audyt bez własnych testów cicho przestaje cokolwiek znajdować.
3. **Prawdziwy kod** — audyt ma nie znaleźć nic, a funkcje zwracające kolor
   statusu mają oddawać wyłącznie wartości z palety.
"""

import textwrap

import flet as ft
import pytest

import audyty
import utils


# ============================================================================
#  1. SAMA PALETA
# ============================================================================

ROLE_WYMAGANE = [
    "critical", "warning", "ok", "neutral",
    "error", "destructive", "cost", "info", "accent",
]


@pytest.mark.parametrize("rola", ROLE_WYMAGANE)
def test_rola_istnieje_i_jest_kolorem_fleta(rola):
    assert rola in utils.KOLOR_STATUS
    assert utils.KOLOR_STATUS[rola] in set(ft.Colors)


# Te cztery muszą dać się odróżnić wzrokiem — na nich stoi cały kod.
@pytest.mark.parametrize("a, b", [
    ("critical", "warning"), ("critical", "ok"), ("warning", "ok"),
    ("critical", "neutral"), ("warning", "neutral"), ("ok", "neutral"),
])
def test_stany_rzeczy_sa_rozroznialne(a, b):
    assert utils.KOLOR_STATUS[a] != utils.KOLOR_STATUS[b]


def test_role_dzielace_odcien_sa_zapisane_wprost():
    """Cztery role są dziś czerwone i to jest decyzja, a nie przeoczenie.

    Nazwa mówi, PO CO kolor stoi w danym miejscu — dzięki temu „odróżnij
    czerwień akcji usuwania od czerwieni terminu” jest zmianą jednej linijki.
    Ten test pilnuje, żeby takie rozdzielenie było świadome: gdy któraś z tych
    ról dostanie własny odcień, test upomni się o decyzję."""
    czerwone = {"critical", "error", "destructive", "cost"}
    odcienie = {utils.KOLOR_STATUS[r] for r in czerwone}

    assert odcienie == {ft.Colors.RED_700}, (
        "role czerwone rozjechały się na odcienie: "
        + ", ".join(f"{r}={utils.KOLOR_STATUS[r]}" for r in sorted(czerwone))
        + "\n\nJeśli to zamierzone, popraw ten test — ale sprawdź wcześniej, czy "
        "nowy odcień naprawdę niesie inną informację."
    )


def test_akcent_nie_jest_ostrzezeniem():
    """Bursztyn wyróżnienia („rekord”, „trofeum”) i pomarańcz ostrzeżenia leżą
    blisko siebie, więc łatwo je pomylić przy czytaniu kodu. W kodzie mają być
    różne, bo na ekranie znaczą co innego."""
    assert utils.KOLOR_STATUS["accent"] != utils.KOLOR_STATUS["warning"]


# ============================================================================
#  2. AUDYT NA SYNTETYCZNYM KODZIE
# ============================================================================

def _audyt(tmp_path, kod, nazwa="probka.py"):
    sciezka = tmp_path / nazwa
    sciezka.write_text(textwrap.dedent(kod), encoding="utf-8")
    return audyty.audyt_palety_statusow([sciezka], korzen=tmp_path)


PRZYPADKI = [
    (
        "czerwien wpisana wprost",
        'x = ft.Text("Po terminie", color=ft.Colors.RED_700)',
        1,
    ),
    (
        "kolor wziety z palety",
        'x = ft.Text("Po terminie", color=utils.KOLOR_STATUS["critical"])',
        0,
    ),
    (
        "dwa odcienie w jednym wyrazeniu",
        'x = ft.Colors.RED_700 if pilne else ft.Colors.ORANGE_700',
        2,
    ),
    (
        "sasiad o stopien obok tez sie liczy",
        'x = ft.Text("Konflikt", color=ft.Colors.ORANGE_800)',
        1,
    ),
    (
        "kolor spoza palety statusow",
        'x = ft.Text("Tankowanie", color=ft.Colors.TEAL_700)',
        0,
    ),
    (
        "kolor w nazwanej mapie tozsamosci",
        'IKONY_TIMELINE = {\n    "Serwis": (ft.Icons.BUILD, ft.Colors.ORANGE_700),\n}',
        0,
    ),
    (
        "ta sama mapa pod inna nazwa juz nie",
        'MOJE_KOLORY = {\n    "Serwis": (ft.Icons.BUILD, ft.Colors.ORANGE_700),\n}',
        1,
    ),
    (
        "znacznik w tej samej linii",
        'x = kafel("Serwis", ft.Colors.ORANGE_700)  # paleta: tożsamość — kolor kategorii',
        0,
    ),
    (
        "znacznik w linii nad",
        '# paleta: tożsamość\nx = kafel("Serwis", ft.Colors.ORANGE_700)',
        0,
    ),
    (
        "znacznik dwie linie wyzej juz nie zdejmuje",
        '# paleta: tożsamość\n\nx = kafel("Serwis", ft.Colors.ORANGE_700)',
        1,
    ),
]


@pytest.mark.parametrize(
    "nazwa, kod, oczekiwane",
    PRZYPADKI,
    ids=[p[0].replace(" ", "_") for p in PRZYPADKI],
)
def test_audyt_palety_rozpoznaje_przypadek(nazwa, kod, oczekiwane, tmp_path):
    znaleziska = _audyt(tmp_path, kod)
    assert len(znaleziska) == oczekiwane, f"{nazwa}: {znaleziska}"


def test_audyt_podaje_plik_linie_i_kolor(tmp_path):
    """Komunikat bez miejsca to zagadka, a nie znalezisko."""
    znaleziska = _audyt(tmp_path, """
        import flet as ft

        def karta():
            return ft.Text("Po terminie", color=ft.Colors.RED_700)
    """)

    z = znaleziska[0]
    assert (z["plik"], z["linia"], z["kolor"]) == ("probka.py", 5, "RED_700")


def test_dom_palety_jest_zwolniony(tmp_path):
    """`utils/stale.py` to jedyne miejsce, w którym odcień wolno napisać wprost —
    bo tam właśnie się go NAZYWA."""
    katalog = tmp_path / "utils"
    katalog.mkdir()
    znaleziska = _audyt(tmp_path, 'KOLOR_STATUS = {"critical": ft.Colors.RED_700}',
                        nazwa="utils/stale.py")

    assert znaleziska == []


# ============================================================================
#  3. PRAWDZIWY KOD
# ============================================================================

def test_zaden_ekran_nie_wpisuje_odcienia_statusu_wprost():
    znaleziska = audyty.audyt_palety_statusow()
    assert znaleziska == [], (
        "\n".join(f"{z['plik']}:{z['linia']} — {z['opis']}" for z in znaleziska)
        + "\n\nKolory statusu bierze się z utils.KOLOR_STATUS po nazwie roli "
        "(critical / warning / ok / neutral / error / destructive / cost / info / "
        "accent). Jeśli ten kolor naprawdę nie mówi nic o stanie, tylko odróżnia "
        "rzecz od rzeczy — dopisz w tej linii `# paleta: tożsamość — <powód>`."
    )


def test_kolor_terminu_zawsze_z_palety():
    """Funkcja, przez którą przechodzą WSZYSTKIE terminy w aplikacji. Gdyby
    pojawił się tu czwarty odcień, rozjechałby się z paskami i kafelkami, które
    liczą na te same trzy."""
    from datetime import date, timedelta

    dzis = date.today()
    probki = [None, "", (dzis - timedelta(days=5)).isoformat(), dzis.isoformat(),
              (dzis + timedelta(days=1)).isoformat(), (dzis + timedelta(days=5)).isoformat(),
              (dzis + timedelta(days=200)).isoformat()]

    kolory = {utils.kolor_i_tekst_terminu(p)[0] for p in probki}

    assert kolory <= set(utils.KOLOR_STATUS.values()), (
        f"kolory spoza palety: {kolory - set(utils.KOLOR_STATUS.values())}"
    )


@pytest.mark.parametrize("wynik", [None, 0, 30, 49, 50, 79, 80, 100])
def test_kolor_kondycji_zawsze_z_palety(wynik):
    kolor = utils.wskaznik_kondycji(wynik)[0]

    assert kolor in set(utils.KOLOR_STATUS.values())


def test_mapy_statusow_wskazuja_na_palete():
    """Trzy osobne mapy powtarzały tę samą trójkę odcieni. Przy zmianie palety
    ruszyłaby się jedna z nich, a dwie zostałyby w tyle — i dokładnie tak
    powstaje „w trzech miejscach inna czerwień”."""
    paleta = set(utils.KOLOR_STATUS.values())

    assert set(utils.KOLORY_STATUSU_TERMINU.values()) <= paleta
    assert set(utils.KOLORY_TONU.values()) - {ft.Colors.BLUE_GREY_700} <= paleta
