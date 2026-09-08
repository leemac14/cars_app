"""Pakiet `sync/` — czy podział trzyma się zasad, na których został zrobiony.

`sync.py` był ostatnim z pięciu dużych plików rozbijanych według tej samej
zasady: moduły od najmniej zależnych do najbardziej, zależności wyłącznie
w dół, `__init__.py` bez logiki. Różnica polega na tym, że tutaj błąd nie
psuje ekranu, tylko cudze dane — dlatego zasady mają testy, a nie tylko
akapit w dokumentacji.

Trzy pułapki są tu prawdziwe, nie teoretyczne, i każda milczy:

1. `from .modul import nazwa` robi KOPIĘ wiązania. Nazwa przypisywana potem
   przez `global` rozjeżdża się z oryginałem — a kopia w `sync/__init__.py`
   zostaje na wartości z chwili importu i po cichu kłamie.
2. Ta sama kopia unieważnia `monkeypatch.setattr(sync, ...)`. Blokada sieci
   z conftestu przestałaby cokolwiek blokować, nie zapalając ani jednego
   czerwonego testu — bo blokada, która działa, jest niema.
3. Nazwa zapomniana w `__all__` znika z `import sync` dopiero u wołającego.
"""

import ast
import pathlib

import pytest

import audyty
import sync


PAKIET = pathlib.Path(sync.__file__).resolve().parent

# Kolejność z `sync/__init__.py` — ona JEST deklaracją warstw. Zależność wolno
# mieć wyłącznie do modułu stojącego wyżej na tej liście.
KOLEJNOSC = ["stale", "polaczenie", "role", "delta", "nagrobki", "konflikty",
             "pomocnicze", "wysylanie", "pobieranie", "przywracanie", "przebieg",
             "wspoldzielenie"]


def _moduly():
    return [getattr(sync, nazwa) for nazwa in KOLEJNOSC]


def _drzewo(nazwa):
    return ast.parse((PAKIET / f"{nazwa}.py").read_text(encoding="utf-8"))


# ------------------------------------------------------------- kształt pakietu


def test_pakiet_ma_dokladnie_te_moduly_co_deklaruje():
    """Nowy plik w `sync/` bez wpisu w `__init__.py` nie zostałby zaimportowany
    — i nikt by tego nie zauważył, dopóki ktoś czegoś z niego nie zawoła."""
    na_dysku = {p.stem for p in PAKIET.glob("*.py")} - {"__init__"}
    assert na_dysku == set(KOLEJNOSC), f"na dysku {sorted(na_dysku)}, w kolejności {KOLEJNOSC}"


def test_init_nie_ma_wlasnej_logiki():
    """`__init__.py` jest spisem treści. Definicja, która by tu wylądowała,
    nie miałaby swojego miejsca w warstwach i nie dałaby się przetestować."""
    drzewo = ast.parse((PAKIET / "__init__.py").read_text(encoding="utf-8"))
    obce = [w for w in drzewo.body
            if not isinstance(w, (ast.Import, ast.ImportFrom, ast.Expr))]
    assert obce == [], f"logika w __init__.py w liniach {[w.lineno for w in obce]}"


def test_zaleznosci_ida_tylko_w_dol():
    """Zasada całego podziału: od najmniej zależnych do najbardziej. Import
    wstecz oznacza cykl, a cykl w tym pakiecie kończy się importem w środku
    funkcji — czyli zależnością, której nie widać w nagłówku pliku."""
    wstecz = []
    for i, nazwa in enumerate(KOLEJNOSC):
        for w in ast.walk(_drzewo(nazwa)):
            if isinstance(w, ast.ImportFrom) and w.level == 1 and w.module in KOLEJNOSC:
                if KOLEJNOSC.index(w.module) >= i:
                    wstecz.append(f"{nazwa} -> {w.module} (linia {w.lineno})")
    assert wstecz == [], "import wstecz:\n  " + "\n  ".join(wstecz)


def test_all_wymienia_to_co_modul_naprawde_definiuje():
    """Literówka w `__all__` nie jest błędem dla Pythona — nazwa po prostu
    znika z `import sync` i wraca jako AttributeError u wołającego."""
    for nazwa in KOLEJNOSC:
        modul = getattr(sync, nazwa)
        brakuje = [n for n in modul.__all__ if not hasattr(modul, n)]
        assert brakuje == [], f"{nazwa}.__all__ wymienia nieistniejące: {brakuje}"


# --------------------------------------------------- kopie wiązań i `global`


def _przypisywane_globalnie(nazwa):
    """Nazwy modułowe, którym moduł przypisuje NOWĄ wartość (`global x; x = ...`)."""
    drzewo = _drzewo(nazwa)
    globalne = {n for w in ast.walk(drzewo) if isinstance(w, ast.Global) for n in w.names}
    return {n for n in globalne
            if any(isinstance(w, ast.Assign) and any(getattr(t, "id", None) == n for t in w.targets)
                   for w in ast.walk(drzewo))}


def _nazwy_importowane(nazwa):
    """Wszystko, co moduł ściąga do siebie przez `from ... import ...`."""
    return {a.name for w in ast.walk(_drzewo(nazwa))
            if isinstance(w, ast.ImportFrom) for a in w.names}


def test_nazwa_przypisywana_globalnie_nie_wychodzi_z_modulu():
    """`from .delta import _delta_dostepna` robi kopię wiązania. Gdy `_wylacz_delte`
    przypisze tam False, kopia zostaje na None — i `sync._delta_dostepna` mówi
    coś innego niż `sync.delta._delta_dostepna`. Dwie prawdy o tej samej rzeczy.

    Dlatego takie nazwy zostają w swoim module: nie ma ich w żadnym `__all__`
    ani w żadnym `from .… import`. Dziś dotyczy to `_klient_cache` i
    `_delta_dostepna`.

    Test patrzy z drugiej strony niż intuicja: pyta nie „czy TEN moduł ją
    wystawia", tylko „czy KTOKOLWIEK ją wystawia albo importuje". Zamiana
    `lista.clear()` na `lista = []` w module, który tę listę tylko importuje,
    jest właśnie takim przypadkiem — nazwa nagle staje się przypisywana,
    a wystawia ją zupełnie inny plik."""
    for nazwa in KOLEJNOSC:
        for zmienna in _przypisywane_globalnie(nazwa):
            for inny in KOLEJNOSC:
                assert zmienna not in getattr(sync, inny).__all__, (
                    f"`{zmienna}` jest przypisywana na nowo w sync/{nazwa}.py, "
                    f"a sync/{inny}.py wystawia ją w `__all__` — `sync.{zmienna}` "
                    "będzie kopią zamrożoną w chwili importu."
                )
                if inny != nazwa:
                    assert zmienna not in _nazwy_importowane(inny), (
                        f"`{zmienna}` jest przypisywana na nowo w sync/{nazwa}.py, "
                        f"a sync/{inny}.py ją importuje — dostanie kopię, nie tę zmienną."
                    )


def test_listy_konfliktow_sa_jednym_obiektem():
    """Odwrotna strona tej samej monety: listy konfliktów WOLNO re-eksportować,
    bo są mutowane w miejscu (`append`, `clear`) i nigdy nie przypisywane na nowo.

    Gdyby ktoś kiedyś zamienił `_konflikty_biezacej_synchronizacji.clear()` na
    `_konflikty_biezacej_synchronizacji = []`, `_synchronizuj_pod_zamkiem`
    czyściłby własną kopię, a użytkownik oglądałby konflikty z poprzedniego
    przebiegu. Ten test idzie czerwony w tej samej chwili."""
    for zmienna in ("_konflikty_biezacej_synchronizacji", "_odrzucone_biezacej_synchronizacji"):
        wzorzec = getattr(sync.konflikty, zmienna)
        assert getattr(sync, zmienna) is wzorzec
        assert getattr(sync.przebieg, zmienna) is wzorzec, (
            f"{zmienna} w sync.przebieg to inny obiekt — czyszczenie na starcie "
            "synchronizacji nie dotrze do tego, co czyta interfejs."
        )


# ------------------------------------------------------------ blokada sieci


# Miejsca, w których wejście do Supabase ma swoje wiązanie. Zamek jak przy
# `tests/ciche_wyjatki.txt`: nowy moduł na tej liście to decyzja, a nie przypadek.
WEJSCIA_DO_SIECI = {
    "sync._pobierz_klient", "sync._upewnij_sesje",
    "sync.polaczenie._pobierz_klient", "sync.polaczenie._upewnij_sesje",
    "sync.przywracanie._upewnij_sesje",
    "sync.przebieg._upewnij_sesje",
    "sync.wspoldzielenie._upewnij_sesje",
}


def test_zakaz_sieci_siega_do_kazdego_modulu():
    """Fixture `bez_sieci` z conftestu podmienia `_upewnij_sesje` we WSZYSTKICH
    modułach, nie tylko w pakiecie. Gdyby podmieniała samo `sync._upewnij_sesje`,
    `przywroc_z_chmury` wołałoby prawdziwą funkcję ze swojej kopii wiązania —
    a blokada milczałaby dalej, bo blokada, która działa, nic nie mówi.

    Sprawdzamy PODMIANĘ, a nie zachowanie: wywołanie prawdziwego `_upewnij_sesje`
    na maszynie z zainstalowanym `supabase` poszłoby do sieci, czyli test
    zamiast zapalić się na czerwono wisiałby na timeoucie — dokładnie to,
    czemu ta blokada ma zapobiegać."""
    wiazania = {}
    for miejsce in [sync] + _moduly():
        for funkcja in ("_pobierz_klient", "_upewnij_sesje"):
            if funkcja in vars(miejsce):
                wiazania[f"{miejsce.__name__}.{funkcja}"] = vars(miejsce)[funkcja]

    assert set(wiazania) == WEJSCIA_DO_SIECI, (
        "zmieniła się lista wiązań wejścia do Supabase — dopisz je do "
        f"WEJSCIA_DO_SIECI po sprawdzeniu, że blokada je obejmuje:\n"
        f"  doszło: {sorted(set(wiazania) - WEJSCIA_DO_SIECI)}\n"
        f"  ubyło:  {sorted(WEJSCIA_DO_SIECI - set(wiazania))}"
    )

    nieobjete = [m for m, f in wiazania.items() if f.__name__ != "_zabroniony"]
    assert nieobjete == [], (
        "blokada sieci nie objęła tych wiązań — test może dobić do Supabase:\n  "
        + "\n  ".join(nieobjete)
    )


# ------------------------------------------------- publiczny interfejs pakietu


def _nazwy_wolane_w_projekcie():
    """Wszystkie `sync.cos` napisane gdziekolwiek w aplikacji (bez testów)."""
    uzycia = {}
    for sciezka in audyty._pliki_projektu():
        drzewo = ast.parse(sciezka.read_text(encoding="utf-8"), filename=str(sciezka))
        for w in ast.walk(drzewo):
            if (isinstance(w, ast.Attribute) and isinstance(w.value, ast.Name)
                    and w.value.id == "sync"):
                uzycia.setdefault(w.attr, []).append(
                    f"{sciezka.relative_to(audyty.KORZEN_PROJEKTU).as_posix()}:{w.lineno}")
    return uzycia


def test_wszystko_czego_uzywa_aplikacja_jest_pod_sync():
    """Sedno `__init__.py`: `import sync` ma dawać dokładnie to, co dawał jeden
    plik. Nazwa zapomniana w `__all__` przechodzi przez testy jednostkowe
    i wywala się dopiero u użytkownika — na ekranie, którego nikt nie otworzył
    podczas przeglądu."""
    braki = {n: m for n, m in _nazwy_wolane_w_projekcie().items() if not hasattr(sync, n)}
    assert braki == {}, "aplikacja woła nazwy, których pakiet nie wystawia:\n  " + "\n  ".join(
        f"sync.{n} — {', '.join(m)}" for n, m in sorted(braki.items()))


def test_stary_plik_sync_py_juz_niczego_nie_definiuje():
    """Pakiet ma pierwszeństwo przy imporcie, więc `sync.py` obok niego jest
    martwy. Zostawiony wyłącznie dlatego, że nie mam prawa kasować plików —
    ale gdyby ktoś dopisał tam kod, ten kod nigdy by się nie uruchomił."""
    stary = audyty.KORZEN_PROJEKTU / "sync.py"
    if not stary.exists():
        pytest.skip("sync.py już usunięty — tak też jest dobrze")
    assert ast.parse(stary.read_text(encoding="utf-8")).body == [], (
        "sync.py zawiera kod, którego nikt nie uruchomi — pierwszeństwo ma pakiet sync/"
    )
