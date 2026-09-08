"""Cztery audyty wpięte w pytest — plus testy samych audytów.

Do tej pory były jednorazowymi skryptami: napisane, uruchomione raz, wyrzucone.
Każdy z nich wykrył prawdziwy błąd (24 rozciągnięte chipy po cofnięciu
`tight=True`, porzuconą korutynę hamburgera), więc każdy zasługuje na to, żeby
działać przy każdej następnej zmianie.

Plik ma dwie części:

1. **Testy audytów** — syntetyczne drzewka i syntetyczne pliki, o których z góry
   wiadomo, czy są błędne. Audyt bez własnych testów jest wart tyle, co jego
   ostatnie uruchomienie: cicho przestaje cokolwiek znajdować i nikt tego nie
   zauważa, bo zielono.
2. **Audyty na prawdziwym kodzie** — mają nie znaleźć nic.
"""

import textwrap

import flet as ft
import pytest

import audyty
import pomoce


# ============================================================================
#  1a. TESTY AUDYTU expand — siedem przypadków
# ============================================================================

def _tekst_expand():
    return ft.Text("cokolwiek", expand=True)


PRZYPADKI_EXPAND = [
    # (nazwa, drzewo, ile znalezisk)
    (
        "wiersz w wierszu",
        lambda: ft.Row([ft.Row([_tekst_expand()])]),
        1,
    ),
    (
        "wiersz z expand w wierszu",
        lambda: ft.Row([ft.Row([_tekst_expand()], expand=True)]),
        0,
    ),
    (
        "wiersz z width w wierszu",
        lambda: ft.Row([ft.Row([_tekst_expand()], width=200)]),
        0,
    ),
    (
        "pasek przewijany",
        lambda: ft.Row([_tekst_expand()], scroll=ft.ScrollMode.ALWAYS),
        1,
    ),
    (
        "pasek zawijany",
        lambda: ft.Row([_tekst_expand()], wrap=True),
        1,
    ),
    (
        "zwykły wiersz",
        lambda: ft.Row([_tekst_expand()]),
        0,
    ),
    (
        "kafelek o stałej szerokości",
        lambda: ft.Row([ft.Container(width=120, content=ft.Row([_tekst_expand()]))]),
        0,
    ),
]


@pytest.mark.parametrize(
    "nazwa, zbuduj, oczekiwane",
    PRZYPADKI_EXPAND,
    ids=[p[0].replace(" ", "_") for p in PRZYPADKI_EXPAND],
)
def test_audyt_expand_rozpoznaje_przypadek(nazwa, zbuduj, oczekiwane):
    znaleziska = audyty.znajdz_expand_bez_ograniczenia(zbuduj())
    assert len(znaleziska) == oczekiwane, f"{nazwa}: {znaleziska}"


def test_audyt_expand_wchodzi_w_glab_kolumn_i_kontenerow():
    """Znalezisko schowane trzy poziomy niżej też musi zostać znalezione."""
    drzewo = ft.Column([
        ft.Container(content=ft.Column([
            ft.Row([ft.Row([_tekst_expand()])]),
        ])),
    ])
    assert len(audyty.znajdz_expand_bez_ograniczenia(drzewo)) == 1


# ============================================================================
#  1b. TESTY AUDYTU CHIPÓW
# ============================================================================
# `wrap=True` to Wrap: dziecko dostaje maxWidth równe szerokości paska, więc
# wiersz bez `tight=True` (mainAxisSize.max) zajmuje CAŁĄ linijkę. W pasku
# przewijanym ten sam kod kurczy się do treści — dlatego błąd wychodzi dopiero
# po przejściu na zawijanie.

def _chip(tight=True, width=None):
    return ft.Container(
        width=width,
        content=ft.Row([ft.Icon(ft.Icons.CHECK), ft.Text("filtr")], tight=tight),
    )


PRZYPADKI_CHIPOW = [
    ("chip z tight", lambda: ft.Row([_chip(tight=True)], wrap=True), 0),
    ("chip bez tight", lambda: ft.Row([_chip(tight=False)], wrap=True), 1),
    ("chip bez tight, ale z width", lambda: ft.Row([_chip(tight=False, width=90)], wrap=True), 0),
    ("goły wiersz bez tight w pasku", lambda: ft.Row([ft.Row([ft.Text("x")])], wrap=True), 1),
    ("sam tekst w pasku", lambda: ft.Row([ft.Text("x")], wrap=True), 0),
    ("ten sam chip w pasku PRZEWIJANYM", lambda: ft.Row([_chip(tight=False)], scroll=ft.ScrollMode.ALWAYS), 0),
    ("zwykły wiersz, nie pasek", lambda: ft.Row([_chip(tight=False)]), 0),
    ("trzy chipy, dwa złe", lambda: ft.Row([_chip(True), _chip(False), _chip(False)], wrap=True), 2),
]


@pytest.mark.parametrize(
    "nazwa, zbuduj, oczekiwane",
    PRZYPADKI_CHIPOW,
    ids=[p[0].replace(" ", "_").replace(",", "") for p in PRZYPADKI_CHIPOW],
)
def test_audyt_chipow_rozpoznaje_przypadek(nazwa, zbuduj, oczekiwane):
    znaleziska = audyty.znajdz_rozciagliwe_chipy(zbuduj())
    assert len(znaleziska) == oczekiwane, f"{nazwa}: {znaleziska}"


def test_audyt_chipow_pomija_zawartosc_menu():
    """Rozwinięte menu rysuje się w osobnej warstwie i nie wpływa na szerokość
    chipa — inaczej każdy PopupMenuButton byłby fałszywym trafieniem."""
    menu = ft.PopupMenuButton(
        content=_chip(tight=True),
        items=[ft.PopupMenuItem(content=ft.Row([ft.Text("pozycja menu")]))],
    )
    assert audyty.znajdz_rozciagliwe_chipy(ft.Row([menu], wrap=True)) == []


# ============================================================================
#  1c. TESTY AUDYTÓW AST
# ============================================================================

def _plik_z_kodem(tmp_path, kod):
    sciezka = tmp_path / "probka.py"
    sciezka.write_text(textwrap.dedent(kod), encoding="utf-8")
    return [sciezka]


def test_audyt_pol_lapie_pole_ktorego_nie_ma(tmp_path):
    """W Flet 0.8x TextField ma `error`, nie `error_text` — a przypisanie do
    nieistniejącego pola NIE rzuca wyjątku, tylko po cichu nic nie robi."""
    pliki = _plik_z_kodem(tmp_path, """
        import flet as ft
        pole = ft.TextField(label="Kwota")
        pole.error_text = "Podaj kwotę"
    """)
    znaleziska = audyty.audyt_pol_kontrolek(pliki, korzen=tmp_path)
    assert len(znaleziska) == 1
    assert "error_text" in znaleziska[0]["opis"]


def test_audyt_pol_przepuszcza_prawidlowe_pole(tmp_path):
    pliki = _plik_z_kodem(tmp_path, """
        import flet as ft
        pole = ft.TextField(label="Kwota")
        pole.error = "Podaj kwotę"
        pole.value = "12"
    """)
    assert audyty.audyt_pol_kontrolek(pliki, korzen=tmp_path) == []


def test_audyt_pol_milczy_przy_zmiennej_o_niepewnym_typie(tmp_path):
    """Ta sama nazwa użyta dwa razy do różnych rzeczy nie może dawać fałszywek."""
    pliki = _plik_z_kodem(tmp_path, """
        import flet as ft
        pole = ft.TextField()
        pole = cos_innego()
        pole.error_text = "x"
    """)
    assert audyty.audyt_pol_kontrolek(pliki, korzen=tmp_path) == []


def test_audyt_pol_lapie_nieistniejacy_argument_konstruktora(tmp_path):
    pliki = _plik_z_kodem(tmp_path, """
        import flet as ft
        t = ft.Text("hej", rozmiar=12)
    """)
    znaleziska = audyty.audyt_pol_kontrolek(pliki, korzen=tmp_path)
    assert len(znaleziska) == 1
    assert "rozmiar" in znaleziska[0]["opis"]


def test_audyt_pol_przepuszcza_style_z_gwiazdkowym_konstruktorem(tmp_path):
    """ButtonStyle, Theme i BoxShadow mają `__init__(*args, **kwargs)` — audyt
    musi brać ich pola z dataclassy, inaczej zgłasza cały projekt."""
    pliki = _plik_z_kodem(tmp_path, """
        import flet as ft
        s = ft.ButtonStyle(color=ft.Colors.RED, padding=4, shape=ft.RoundedRectangleBorder(radius=8))
        c = ft.Container(shadow=ft.BoxShadow(blur_radius=4, color=ft.Colors.BLACK))
    """)
    assert audyty.audyt_pol_kontrolek(pliki, korzen=tmp_path) == []


PRZYPADKI_RUN_TASK = [
    ("lambda", "page.run_task(lambda: cos(page))", 1),
    ("zwykła funkcja", "def robota():\n    pass\npage.run_task(robota)", 1),
    ("gotowa korutyna", "async def robota():\n    pass\npage.run_task(robota())", 1),
    ("prawidłowo", "async def robota():\n    pass\npage.run_task(robota)", 0),
]


@pytest.mark.parametrize(
    "nazwa, kod, oczekiwane",
    PRZYPADKI_RUN_TASK,
    ids=[p[0].replace(" ", "_") for p in PRZYPADKI_RUN_TASK],
)
def test_audyt_run_task_rozpoznaje_przypadek(tmp_path, nazwa, kod, oczekiwane):
    pliki = _plik_z_kodem(tmp_path, "import flet as ft\n" + kod)
    bledy, _ = audyty.audyt_run_task(pliki, korzen=tmp_path)
    assert len(bledy) == oczekiwane, f"{nazwa}: {bledy}"


def test_audyt_run_task_widzi_metody_klasy(tmp_path):
    pliki = _plik_z_kodem(tmp_path, """
        import flet as ft

        class Widok:
            def klik(self, e):
                self._page.run_task(self._robota)

            async def _robota(self):
                pass
    """)
    bledy, nierozstrzygniete = audyty.audyt_run_task(pliki, korzen=tmp_path)
    assert bledy == []
    assert nierozstrzygniete == []


# ============================================================================
#  1d. TESTY AUDYTU cichych `except: pass`
# ============================================================================

def _plik(tmp_path, nazwa, kod):
    sciezka = tmp_path / nazwa
    sciezka.write_text(textwrap.dedent(kod), encoding="utf-8")
    return sciezka


def test_audyt_cichych_liczy_tylko_bloki_z_samym_pass(tmp_path):
    sciezka = _plik(tmp_path, "moj.py", """
        def f():
            try:
                a()
            except Exception:
                pass
            try:
                b()
            except Exception:
                log.polkniety("b")
            try:
                c()
            except ValueError:
                pass
            try:
                d()
            except Exception:
                zapisz()
                pass
    """)

    # Trzeci blok liczy się też: wąski `except ValueError` bywa świadomy, ale
    # równie dobrze bywa przeoczeniem — audyt melduje, decyzję podejmuje człowiek.
    # Czwarty NIE, bo `pass` po instrukcji nic nie ucisza.
    assert audyty.znajdz_ciche_wyjatki([sciezka], korzen=tmp_path) == {"moj.py": 2}


def test_audyt_cichych_pomija_pliki_bez_znalezisk(tmp_path):
    sciezka = _plik(tmp_path, "czysty.py", """
        def f():
            try:
                a()
            except Exception:
                log.polkniety("a")
    """)

    assert audyty.znajdz_ciche_wyjatki([sciezka], korzen=tmp_path) == {}


def test_zamek_cichych_wyjatkow_czyta_to_co_zapisal(tmp_path):
    """Zapis i odczyt muszą się zgadzać — plik jest tu jedynym punktem odniesienia."""
    plik = tmp_path / "ciche_wyjatki.txt"
    znalezione = {"db/kosz.py": 9, "utils/komponenty.py": 11}

    plik.write_text(audyty.tresc_pliku_cichych_wyjatkow(znalezione), encoding="utf-8", newline="\n")

    assert audyty.wczytaj_ciche_wyjatki(plik) == znalezione


def test_porownanie_rozpoznaje_nowy_plik_i_przyrost():
    zapisane = {"a.py": 2, "b.py": 1}
    znalezione = {"a.py": 3, "c.py": 1}

    nowe, przybylo, ubylo = audyty.porownaj_ciche_wyjatki(znalezione, zapisane)

    assert nowe == [("c.py", 1)]
    assert przybylo == [("a.py", 2, 3)]
    assert ubylo == [("b.py", 1, 0)]


# ============================================================================
#  2. AUDYTY NA PRAWDZIWYM KODZIE
# ============================================================================

# Dwa układy danych wystarczą: pusty garaż rysuje stany puste, pełny pojazd
# rysuje wszystkie listy, chipy i paski. Reszta scenariuszy nie zmienia
# STRUKTURY drzewa, tylko liczby w środku.
SCENARIUSZE_AUDYTU = ["pusty_garaz", "pojazd_z_historia"]


@pytest.mark.parametrize("scenariusz", SCENARIUSZE_AUDYTU)
@pytest.mark.parametrize("nazwa_widoku", list(pomoce.klasy_widokow()))
def test_widok_nie_ma_expand_bez_ograniczenia(baza, nazwa_widoku, scenariusz):
    """`expand` w wierszu o nieograniczonej szerokości wywala układ w czasie
    działania — Flutter rzuca „RenderFlex children have non-zero flex but
    incoming width constraints are unbounded"."""
    stan, identyfikatory = pomoce.przygotuj_scenariusz(scenariusz)
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()[nazwa_widoku], pomoce.zbuduj_strone(), stan, identyfikatory)

    znaleziska = audyty.znajdz_expand_bez_ograniczenia(widok)

    assert znaleziska == [], "\n".join(f"{z['powod']}: {z['sciezka']}" for z in znaleziska)


@pytest.mark.parametrize("scenariusz", SCENARIUSZE_AUDYTU)
@pytest.mark.parametrize("nazwa_widoku", list(pomoce.klasy_widokow()))
def test_widok_nie_ma_rozciagliwych_chipow(baza, nazwa_widoku, scenariusz):
    """Chip bez `tight=True` w pasku zawijanym zajmuje całą linijkę i filtry
    ustawiają się jeden pod drugim zamiast obok siebie."""
    stan, identyfikatory = pomoce.przygotuj_scenariusz(scenariusz)
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()[nazwa_widoku], pomoce.zbuduj_strone(), stan, identyfikatory)

    znaleziska = audyty.znajdz_rozciagliwe_chipy(widok)

    assert znaleziska == [], "\n".join(z["sciezka"] for z in znaleziska)


# Ekran główny to cztery ekrany pod jedną klasą, a dwa z nich mają jeszcze
# podzakładki. Paski filtrów i sortowania mieszkają właśnie tam.
UKLADY_EKRANU_GLOWNEGO = [
    (0, 0, 0),  # Kokpit
    (1, 0, 0),  # Serwis
    (2, 0, 0),  # Koszty / Tankowania
    (2, 1, 0),  # Koszty / Inne
    (3, 0, 0),  # Analiza / miesiące
    (3, 0, 1),  # Analiza / lata
]


@pytest.mark.parametrize("zakladka, podzakladka_kosztow, podzakladka_statystyk", UKLADY_EKRANU_GLOWNEGO)
def test_ekran_glowny_przechodzi_oba_audyty_drzewa(baza, zakladka, podzakladka_kosztow, podzakladka_statystyk):
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_historia")
    stan.zakladka = zakladka
    stan.koszty_podzakladka = podzakladka_kosztow
    stan.stat_podzakladka = podzakladka_statystyk
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(), stan)

    assert audyty.znajdz_expand_bez_ograniczenia(widok) == []
    assert audyty.znajdz_rozciagliwe_chipy(widok) == []


@pytest.mark.parametrize("nazwa_widoku, pole_stanu, wartosc", [
    ("MagazynView", "magazyn_zakladka", 0),
    ("MagazynView", "magazyn_zakladka", 1),
    ("DoZrobieniaView", "do_zrobienia_podzakladka", 0),
    ("DoZrobieniaView", "do_zrobienia_podzakladka", 1),
])
def test_podzakladki_list_przechodza_oba_audyty(baza, nazwa_widoku, pole_stanu, wartosc):
    stan, identyfikatory = pomoce.przygotuj_scenariusz("pojazd_z_historia")
    setattr(stan, pole_stanu, wartosc)
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()[nazwa_widoku], pomoce.zbuduj_strone(), stan, identyfikatory)

    assert audyty.znajdz_expand_bez_ograniczenia(widok) == []
    assert audyty.znajdz_rozciagliwe_chipy(widok) == []


def test_projekt_nie_ustawia_nieistniejacych_pol_kontrolek():
    znaleziska = audyty.audyt_pol_kontrolek()
    assert znaleziska == [], "\n".join(f"{z['plik']}:{z['linia']} — {z['opis']}" for z in znaleziska)


def test_projekt_podaje_run_task_prawdziwe_korutyny():
    bledy, nierozstrzygniete = audyty.audyt_run_task()
    assert bledy == [], "\n".join(f"{z['plik']}:{z['linia']} — {z['opis']}" for z in bledy)
    assert nierozstrzygniete == [], (
        "argumenty run_task, których audyt nie umie rozstrzygnąć w obrębie pliku — "
        "sprawdź ręcznie i dopisz do NIEROZSTRZYGNIETE_RUN_TASK w tests/audyty.py:\n"
        + "\n".join(f"{z['plik']}:{z['linia']} — {z['cel']}" for z in nierozstrzygniete)
    )

def test_ciche_wyjatki_nie_przybywaja():
    """Zamek na `except …: pass`, w duchu zamka na odciskach migracji.

    Nie chodzi o to, żeby cichych bloków nie było — większość z nich jest
    słuszna. Chodzi o to, żeby NOWY był decyzją: od czasu `log.py` zapisanie,
    co zostało połknięte, kosztuje jedną linijkę."""
    zapisane = audyty.wczytaj_ciche_wyjatki()
    assert zapisane, (
        f"brak {audyty.PLIK_CICHYCH_WYJATKOW.name} — załóż go poleceniem: "
        "python tests/audyty.py --zapisz"
    )

    nowe, przybylo, ubylo = audyty.porownaj_ciche_wyjatki(zapisane=zapisane)

    assert nowe == [] and przybylo == [], (
        "przybyło cichych `except …: pass`:\n"
        + "\n".join(f"  {n} — {ile} (plik nie był na liście)" for n, ile in nowe)
        + "\n".join(f"  {n} — było {bylo}, jest {jest}" for n, bylo, jest in przybylo)
        + "\n\nZamiast `pass` wystarczy `log.polkniety(\"co robiliśmy\")` — zachowanie "
        "bez zmian, a po błędzie zostaje ślad. Jeśli cisza jest tu świadoma, "
        "odśwież zamek: python tests/audyty.py --zapisz"
    )

    assert ubylo == [], (
        "ubyło cichych bloków — to dobra wiadomość, ale zamek trzeba odświeżyć, "
        "inaczej przestaje cokolwiek pilnować:\n"
        + "\n".join(f"  {n} — było {bylo}, jest {jest}" for n, bylo, jest in ubylo)
        + "\n\npython tests/audyty.py --zapisz"
    )

