"""Cztery audyty, które do tej pory były jednorazowymi skryptami.

Dwa pierwsze chodzą po FAKTYCZNIE zbudowanym drzewie kontrolek — nie po kodzie
źródłowym — bo pytanie brzmi „co się narysuje", a to zależy od tego, co
konstruktor widoku naprawdę poskładał. Dwa ostatnie czytają AST, bo dotyczą
rzeczy, których w drzewie już nie widać.

Moduł da się uruchomić wprost, żeby zobaczyć raport:

    python tests/audyty.py
    python tests/audyty.py --zapisz   # odświeża zamek na cichych `except: pass`

Asercje siedzą w test_audyty.py; tutaj są same silniki.
"""

import ast
import dataclasses
import pathlib
import sys

sys.path[:0] = [str(pathlib.Path(__file__).resolve().parent), str(pathlib.Path(__file__).resolve().parents[1])]

import flet as ft  # noqa: E402


KORZEN_PROJEKTU = pathlib.Path(__file__).resolve().parents[1]


# ============================================================================
#  WSPÓLNE CHODZENIE PO DRZEWIE
# ============================================================================

# Pola, w których kontrolka trzyma dzieci. `items` PopupMenuButtona jest tu
# CELOWO pominięte przy audycie chipów (rozwinięte menu rysuje się w osobnej
# warstwie i nie wpływa na szerokość samego chipa) — patrz `POLA_DZIECI_CHIPY`.
POLA_DZIECI = ("controls", "content", "items", "actions", "leading", "trailing", "title", "subtitle")

POLA_DZIECI_CHIPY = tuple(p for p in POLA_DZIECI if p != "items")


def _dzieci(kontrolka, pola=POLA_DZIECI):
    for nazwa in pola:
        wartosc = getattr(kontrolka, nazwa, None)
        if isinstance(wartosc, (list, tuple)):
            for dziecko in wartosc:
                if isinstance(dziecko, ft.Control):
                    yield nazwa, dziecko
        elif isinstance(wartosc, ft.Control):
            yield nazwa, wartosc


def _opis(kontrolka):
    """Krótki opis kontrolki do komunikatu o znalezisku."""
    nazwa = type(kontrolka).__name__
    tekst = getattr(kontrolka, "value", None) or getattr(kontrolka, "label", None)
    if isinstance(tekst, str) and tekst.strip():
        return f"{nazwa}({tekst.strip()[:30]!r})"
    return nazwa


def _sciezka(przodkowie, kontrolka):
    return " > ".join([type(k).__name__ for k in przodkowie] + [_opis(kontrolka)])


def _jest_wierszem(kontrolka):
    return isinstance(kontrolka, ft.Row) and not isinstance(kontrolka, ft.ResponsiveRow)


def _przewijany(kontrolka):
    scroll = getattr(kontrolka, "scroll", None)
    return scroll is not None and scroll is not False


# ============================================================================
#  AUDYT 1 — expand tam, gdzie szerokość jest nieograniczona
# ============================================================================
# Model jak w RenderFlex Fluttera: dziecko wiersza dostaje w osi głównej
# NIEOGRANICZONĄ szerokość, chyba że jest Expanded. Wynikają z tego trzy
# sytuacje, w których `expand=True` wywala układ w czasie działania:
#
#   1. wiersz przewijany  — szerokość z definicji nieograniczona,
#   2. wiersz zawijany    — to Wrap, a Wrap nie obsługuje Expanded,
#   3. wiersz w wierszu   — wewnętrzny wiersz nie ma własnej szerokości.
#
# Wiersz odzyskuje ograniczoną szerokość, gdy ma własne `width` albo sam jest
# rozciągnięty (`expand`) w rodzicu o znanej szerokości.


def _wiersz_ma_ograniczona_szerokosc(wiersz, ograniczona_z_rodzica):
    if getattr(wiersz, "width", None) is not None:
        return True
    if getattr(wiersz, "expand", None):
        return ograniczona_z_rodzica
    return ograniczona_z_rodzica


def znajdz_expand_bez_ograniczenia(korzen):
    """Zwraca listę {'sciezka', 'powod'} — miejsca, w których expand nie zadziała."""
    znaleziska = []

    def zejdz(kontrolka, przodkowie, ograniczona):
        # Kontener albo kolumna o zadanej szerokości domykają szerokość dzieciom.
        wlasna_szerokosc = getattr(kontrolka, "width", None) is not None

        if _jest_wierszem(kontrolka):
            moja_ograniczona = wlasna_szerokosc or ograniczona
            przewijany = _przewijany(kontrolka)
            zawijany = bool(getattr(kontrolka, "wrap", False))

            if przewijany:
                powod = "wiersz przewijany (szerokość nieograniczona)"
            elif zawijany:
                powod = "pasek zawijany (Wrap nie obsługuje expand)"
            elif not moja_ograniczona:
                powod = "wiersz o nieograniczonej szerokości (wiersz w wierszu)"
            else:
                powod = None

            for pole, dziecko in _dzieci(kontrolka):
                if powod and pole == "controls" and getattr(dziecko, "expand", None):
                    znaleziska.append({
                        "sciezka": _sciezka(przodkowie + [kontrolka], dziecko),
                        "powod": powod,
                    })
                # Dziecko wiersza dostaje nieograniczoną szerokość, chyba że jest
                # rozciągnięte w wierszu, który sam ma znaną szerokość.
                if przewijany or zawijany:
                    ograniczona_dziecka = zawijany
                else:
                    ograniczona_dziecka = bool(getattr(dziecko, "expand", None)) and moja_ograniczona
                zejdz(dziecko, przodkowie + [kontrolka], ograniczona_dziecka)
            return

        for _pole, dziecko in _dzieci(kontrolka):
            zejdz(dziecko, przodkowie + [kontrolka], wlasna_szerokosc or ograniczona)

    zejdz(korzen, [], True)
    return znaleziska


# ============================================================================
#  AUDYT 2 — chipy, które zajmą całą linijkę paska zawijanego
# ============================================================================
# `wrap=True` to we Flutterze Wrap: dziecko dostaje maxWidth równe szerokości
# paska. Wiersz bez `tight=True` ma mainAxisSize.max, więc bierze CAŁĄ tę
# szerokość — i chipy ustawiają się jeden pod drugim zamiast obok siebie.
# W pasku przewijanym ten sam kod kurczy się do treści, bo tam szerokość jest
# nieograniczona; dlatego błąd wychodzi dopiero po przejściu na zawijanie.


def znajdz_rozciagliwe_chipy(korzen):
    """Zwraca listę {'sciezka', 'powod'} — dzieci pasków zawijanych, które
    rozciągną się na całą linijkę."""
    znaleziska = []

    def rozciaga_sie(kontrolka, przodkowie):
        """Czy ta kontrolka (albo cokolwiek w środku) weźmie całą szerokość."""
        if getattr(kontrolka, "width", None) is not None:
            return None
        if _jest_wierszem(kontrolka) and not getattr(kontrolka, "tight", False):
            if _przewijany(kontrolka) or getattr(kontrolka, "wrap", False):
                return None  # własny pasek w pasku — inna historia, nie chip
            return _sciezka(przodkowie, kontrolka)
        for _pole, dziecko in _dzieci(kontrolka, POLA_DZIECI_CHIPY):
            trafienie = rozciaga_sie(dziecko, przodkowie + [kontrolka])
            if trafienie:
                return trafienie
        return None

    def zejdz(kontrolka, przodkowie):
        if _jest_wierszem(kontrolka) and getattr(kontrolka, "wrap", False):
            for pole, dziecko in _dzieci(kontrolka, POLA_DZIECI_CHIPY):
                if pole != "controls":
                    continue
                winowajca = rozciaga_sie(dziecko, przodkowie + [kontrolka])
                if winowajca:
                    znaleziska.append({
                        "sciezka": winowajca,
                        "powod": "dziecko paska zawijanego bez width i bez tight=True",
                    })
        for _pole, dziecko in _dzieci(kontrolka, POLA_DZIECI_CHIPY):
            zejdz(dziecko, przodkowie + [kontrolka])

    zejdz(korzen, [])
    return znaleziska


# ============================================================================
#  AUDYT 3 — pola kontrolek Fleta (AST)
# ============================================================================
# Kontrolki Fleta to dataclassy BEZ __slots__, więc `pole.czegostam = x` nigdy
# nie rzuca wyjątku — dokleja nowy, nikomu niepotrzebny atrybut. Po zmianie
# nazwy pola między wersjami Fleta kod dalej „działa", tylko efekt przestaje być
# widoczny: komunikat błędu się nie pokazuje, ikona się nie przełącza.
#
# Zgłaszamy WYŁĄCZNIE zmienne o jednoznacznie ustalonym typie: przypisane
# dokładnie raz, wprost wywołaniem `ft.Cokolwiek(...)`. Inaczej audyt sypałby
# fałszywkami przy każdej zmiennej o wspólnej nazwie.

# Świadome wyjątki — miejsca, w których niezgodność jest zamierzona.
DOZWOLONE_POLA = {
    # Ścieżka dla starszych wersji Fleta, w których pick_files() nie zwracało
    # wyniku. Na 0.8x warunek `hasattr` jest fałszywy i wynik przychodzi z await.
    ("main.py", "FilePicker", "on_result"),
}


def _pliki_projektu():
    pomijane = {".venv", "__pycache__", "tests", ".git", "build", "dist"}
    for sciezka in sorted(KORZEN_PROJEKTU.rglob("*.py")):
        if any(czesc in pomijane for czesc in sciezka.parts):
            continue
        yield sciezka


def _klasa_fleta(nazwa):
    klasa = getattr(ft, nazwa, None)
    return klasa if isinstance(klasa, type) and dataclasses.is_dataclass(klasa) else None


def _dozwolone_pola_klasy(klasa):
    pola = {f.name for f in dataclasses.fields(klasa)}
    # Właściwości (property) to też prawdziwe, ustawialne atrybuty.
    for przodek in klasa.__mro__:
        for nazwa, wartosc in vars(przodek).items():
            if isinstance(wartosc, property):
                pola.add(nazwa)
    return pola


def _dozwolone_argumenty_klasy(klasa):
    """Nazwy argumentów, które konstruktor naprawdę przyjmuje.

    Sama sygnatura nie wystarcza: część klas Fleta (ButtonStyle, Theme,
    BoxShadow, TextStyle…) ma `__init__(*args, **kwargs)` po opakowaniu
    dekoratorem, więc `inspect.signature` nie widzi ani jednego pola.
    `__dataclass_fields__` widzi wszystkie, razem z InitVar-ami (`ref`, `sess`),
    których `dataclasses.fields()` nie zwraca."""
    import inspect

    dozwolone = set(getattr(klasa, "__dataclass_fields__", {}))
    try:
        parametry = inspect.signature(klasa.__init__).parameters
        dozwolone |= {
            nazwa for nazwa, parametr in parametry.items()
            if nazwa != "self" and parametr.kind not in (parametr.VAR_POSITIONAL, parametr.VAR_KEYWORD)
        }
    except (TypeError, ValueError):
        pass
    return dozwolone


def _nazwa_konstruktora(wezel):
    """`ft.TextField(...)` -> 'TextField'; wszystko inne -> None."""
    if not isinstance(wezel, ast.Call):
        return None
    cel = wezel.func
    if isinstance(cel, ast.Attribute) and isinstance(cel.value, ast.Name) and cel.value.id == "ft":
        return cel.attr
    return None


def audyt_pol_kontrolek(sciezki=None, korzen=None):
    """Przypisania do nieistniejących pól i nieistniejące argumenty konstruktorów.

    `korzen` służy wyłącznie do skracania ścieżek w komunikatach — testy audytu
    podają własny, bo pracują na plikach syntetycznych w katalogu tymczasowym."""
    korzen = korzen or KORZEN_PROJEKTU
    znaleziska = []

    for sciezka in sciezki if sciezki is not None else _pliki_projektu():
        wzgledna = sciezka.relative_to(korzen).as_posix()
        drzewo = ast.parse(sciezka.read_text(encoding="utf-8"), filename=str(sciezka))

        # 1. Argumenty nazwane w konstruktorach — tu Flet i tak rzuca TypeError,
        #    więc to błąd twardy, tylko wychodzący dopiero przy wejściu na ekran.
        for wezel in ast.walk(drzewo):
            nazwa_klasy = _nazwa_konstruktora(wezel)
            klasa = _klasa_fleta(nazwa_klasy) if nazwa_klasy else None
            if klasa is None:
                continue
            dozwolone = _dozwolone_argumenty_klasy(klasa)
            for argument in wezel.keywords:
                if argument.arg and argument.arg not in dozwolone:
                    znaleziska.append({
                        "plik": wzgledna,
                        "linia": wezel.lineno,
                        "opis": f"ft.{nazwa_klasy}({argument.arg}=…) — takiego argumentu nie ma",
                    })

        # 2. Przypisania do pól zmiennych o jednoznacznie ustalonym typie.
        typy = {}      # nazwa -> klasa Fleta
        wieloznaczne = set()
        for wezel in ast.walk(drzewo):
            if not isinstance(wezel, (ast.Assign, ast.AnnAssign)):
                continue
            cele = wezel.targets if isinstance(wezel, ast.Assign) else [wezel.target]
            wartosc = wezel.value
            for cel in cele:
                klucz = _klucz_zmiennej(cel)
                if klucz is None:
                    continue
                nazwa_klasy = _nazwa_konstruktora(wartosc) if wartosc is not None else None
                klasa = _klasa_fleta(nazwa_klasy) if nazwa_klasy else None
                if klasa is None or klucz in typy:
                    wieloznaczne.add(klucz)
                else:
                    typy[klucz] = klasa

        for wezel in ast.walk(drzewo):
            if not isinstance(wezel, ast.Assign):
                continue
            for cel in wezel.targets:
                if not isinstance(cel, ast.Attribute):
                    continue
                klucz = _klucz_zmiennej(cel.value)
                if klucz is None or klucz in wieloznaczne or klucz not in typy:
                    continue
                klasa = typy[klucz]
                if cel.attr in _dozwolone_pola_klasy(klasa):
                    continue
                if (wzgledna, klasa.__name__, cel.attr) in DOZWOLONE_POLA:
                    continue
                znaleziska.append({
                    "plik": wzgledna,
                    "linia": wezel.lineno,
                    "opis": f"{klucz}.{cel.attr} = … — ft.{klasa.__name__} nie ma takiego pola",
                })

    return znaleziska


def _klucz_zmiennej(wezel):
    """'x' dla zmiennej, 'self.x' dla atrybutu; None dla czegokolwiek innego."""
    if isinstance(wezel, ast.Name):
        return wezel.id
    if isinstance(wezel, ast.Attribute) and isinstance(wezel.value, ast.Name) and wezel.value.id == "self":
        return f"self.{wezel.attr}"
    return None


# ============================================================================
#  AUDYT 3b — page.run_task wymaga prawdziwego `async def`
# ============================================================================
# run_task sprawdza `asyncio.iscoroutinefunction(handler)` i odrzuca wszystko
# inne. Lambda ZWRACAJĄCA korutynę jest odrzucana tak samo jak zwykła funkcja —
# a to myli, bo `asyncio.create_task(lambda_zwracajaca_korutyne())` jest w
# porządku. Skutek odrzucenia: korutyna, której nikt nie awaituje, i funkcja,
# która po cichu nie robi NIC.

# Argumenty, których audyt nie potrafi rozstrzygnąć w obrębie jednego pliku.
# Każdy wpis to świadoma decyzja, że sprawdzono to ręcznie.
NIEROZSTRZYGNIETE_RUN_TASK = {
    # Callback wstrzykiwany z main.py — tam jest `async def eksportuj_dane_zaawansowane`.
    ("views/eksport_view.py", "self.cb_eksportuj"),
}


def audyt_run_task(sciezki=None, korzen=None):
    """Zwraca (bledy, nierozstrzygniete)."""
    korzen = korzen or KORZEN_PROJEKTU
    bledy = []
    nierozstrzygniete = []

    for sciezka in sciezki if sciezki is not None else _pliki_projektu():
        wzgledna = sciezka.relative_to(korzen).as_posix()
        drzewo = ast.parse(sciezka.read_text(encoding="utf-8"), filename=str(sciezka))

        korutyny = set()
        zwykle_funkcje = set()
        for wezel in ast.walk(drzewo):
            if isinstance(wezel, ast.AsyncFunctionDef):
                korutyny.add(wezel.name)
            elif isinstance(wezel, ast.FunctionDef):
                zwykle_funkcje.add(wezel.name)

        for wezel in ast.walk(drzewo):
            if not (isinstance(wezel, ast.Call)
                    and isinstance(wezel.func, ast.Attribute)
                    and wezel.func.attr == "run_task"
                    and wezel.args):
                continue
            argument = wezel.args[0]
            miejsce = {"plik": wzgledna, "linia": wezel.lineno}

            if isinstance(argument, ast.Lambda):
                bledy.append({**miejsce, "opis": "run_task(lambda …) — run_task odrzuca lambdy, korutyna przepadnie"})
            elif isinstance(argument, ast.Name):
                if argument.id in korutyny:
                    continue
                if argument.id in zwykle_funkcje:
                    bledy.append({**miejsce, "opis": f"run_task({argument.id}) — to zwykłe `def`, nie `async def`"})
                else:
                    nierozstrzygniete.append({**miejsce, "cel": argument.id})
            elif isinstance(argument, ast.Attribute) and isinstance(argument.value, ast.Name) and argument.value.id == "self":
                if argument.attr in korutyny:
                    continue
                if argument.attr in zwykle_funkcje:
                    bledy.append({**miejsce, "opis": f"run_task(self.{argument.attr}) — to zwykłe `def`, nie `async def`"})
                else:
                    nierozstrzygniete.append({**miejsce, "cel": f"self.{argument.attr}"})
            elif isinstance(argument, ast.Call):
                bledy.append({**miejsce, "opis": "run_task(cos()) — run_task chce FUNKCJI, nie gotowej korutyny"})
            else:
                nierozstrzygniete.append({**miejsce, "cel": ast.dump(argument)[:60]})

    nierozstrzygniete = [n for n in nierozstrzygniete
                         if (n["plik"], n["cel"]) not in NIEROZSTRZYGNIETE_RUN_TASK]
    return bledy, nierozstrzygniete


# ============================================================================
#  AUDYT 4 — ciche `except: pass` (AST)
# ============================================================================
# `except Exception: pass` jest w tym projekcie świadomą techniką i najczęściej
# słuszną: kontrolki nie ma jeszcze w drzewie strony, starsza wersja Fleta nie
# zna zdarzenia. Każde takie miejsce jest jednak potencjalnym „nie działa",
# którego nie da się zdiagnozować — a od czasu `log.py` alternatywa kosztuje
# jedną linijkę: `log.polkniety("opis")`.
#
# Audyt nie zabrania cichych bloków. Liczy je per plik i porównuje z zamrożoną
# listą, dokładnie tak jak zamek na odciskach pilnuje wydanych migracji: nowe
# ciche miejsce ma być decyzją zapisaną w pliku, a nie odruchem, który przeszedł
# niezauważony.

PLIK_CICHYCH_WYJATKOW = KORZEN_PROJEKTU / "tests" / "ciche_wyjatki.txt"


def znajdz_ciche_wyjatki(sciezki=None, korzen=None):
    """{plik: liczba} — bloki `except …:` z samym `pass` w środku.

    Kluczem jest PLIK, nie numer linii: numer zmienia się przy każdej edycji
    powyżej i lista wymagałaby odświeżania po każdej zmianie, czyli dokładnie
    tego odruchu, którego ma nie być."""
    korzen = korzen or KORZEN_PROJEKTU
    wynik = {}

    for sciezka in sciezki if sciezki is not None else _pliki_projektu():
        drzewo = ast.parse(sciezka.read_text(encoding="utf-8"), filename=str(sciezka))
        ile = sum(
            1 for wezel in ast.walk(drzewo)
            if isinstance(wezel, ast.ExceptHandler)
            and len(wezel.body) == 1
            and isinstance(wezel.body[0], ast.Pass)
        )
        if ile:
            wynik[sciezka.relative_to(korzen).as_posix()] = ile

    return dict(sorted(wynik.items()))


def wczytaj_ciche_wyjatki(plik=None):
    """Zamrożona lista jako {plik: liczba}. Brak pliku = pusta lista."""
    plik = pathlib.Path(plik or PLIK_CICHYCH_WYJATKOW)
    if not plik.exists():
        return {}

    zapisane = {}
    for linia in plik.read_text(encoding="utf-8").splitlines():
        linia = linia.split("#")[0].strip()
        if not linia:
            continue
        nazwa, _, liczba = linia.rpartition(" ")
        zapisane[nazwa.strip()] = int(liczba)
    return zapisane


def tresc_pliku_cichych_wyjatkow(znalezione=None):
    znalezione = znalezione if znalezione is not None else znajdz_ciche_wyjatki()
    szerokosc = max((len(n) for n in znalezione), default=0)
    naglowek = [
        "# Ciche `except …: pass` — zamrożony stan, plik po pliku.",
        "#",
        "# Nie jest to lista wstydu: te bloki są w większości słuszne. Jest to",
        "# zamek — nowy cichy blok zapala test, żeby był decyzją, a nie odruchem.",
        "# Alternatywa kosztuje jedną linijkę: log.polkniety(\"opis\").",
        "#",
        "# Odświeżenie po świadomej zmianie: python tests/audyty.py --zapisz",
        "",
    ]
    wiersze = [f"{nazwa:<{szerokosc}} {ile}" for nazwa, ile in znalezione.items()]
    return "\n".join(naglowek + wiersze) + "\n"


def porownaj_ciche_wyjatki(znalezione=None, zapisane=None):
    """Zwraca (nowe, przybylo, ubylo) — po jednej liście na rodzaj rozjazdu."""
    znalezione = znalezione if znalezione is not None else znajdz_ciche_wyjatki()
    zapisane = zapisane if zapisane is not None else wczytaj_ciche_wyjatki()

    nowe = [(n, ile) for n, ile in znalezione.items() if n not in zapisane]
    przybylo = [(n, zapisane[n], ile) for n, ile in znalezione.items()
                if n in zapisane and ile > zapisane[n]]
    ubylo = [(n, zapisane[n], znalezione.get(n, 0)) for n in zapisane
             if znalezione.get(n, 0) < zapisane[n]]
    return nowe, przybylo, ubylo


# ============================================================================
#  RAPORT
# ============================================================================

if __name__ == "__main__":
    import os
    import tempfile

    os.environ.setdefault("FLET_APP_STORAGE_DATA", tempfile.mkdtemp(prefix="audyt_"))

    if "--zapisz" in sys.argv:
        # newline="\n" jawnie: projekt jest na LF (patrz .gitattributes oraz
        # tests/test_konce_linii.py), a domyślny newline dałby na Windowsie CRLF.
        znalezione = znajdz_ciche_wyjatki()
        PLIK_CICHYCH_WYJATKOW.write_text(tresc_pliku_cichych_wyjatkow(znalezione),
                                         encoding="utf-8", newline="\n")
        print(f"{PLIK_CICHYCH_WYJATKOW.name}: zapisano {sum(znalezione.values())} "
              f"cichych bloków w {len(znalezione)} plikach.")
        raise SystemExit(0)

    print("== Audyt pól kontrolek Fleta ==")
    for z in audyt_pol_kontrolek():
        print(f"  {z['plik']}:{z['linia']} — {z['opis']}")

    bledy, nierozstrzygniete = audyt_run_task()
    print("\n== Audyt run_task ==")
    for z in bledy:
        print(f"  {z['plik']}:{z['linia']} — {z['opis']}")
    for z in nierozstrzygniete:
        print(f"  [?] {z['plik']}:{z['linia']} — {z['cel']}")

    nowe, przybylo, ubylo = porownaj_ciche_wyjatki()
    print("\n== Audyt cichych `except: pass` ==")
    print(f"  razem: {sum(znajdz_ciche_wyjatki().values())} bloków")
    for nazwa, ile in nowe:
        print(f"  [nowy plik] {nazwa} — {ile}")
    for nazwa, bylo, jest in przybylo:
        print(f"  [przybyło]  {nazwa} — {bylo} -> {jest}")
    for nazwa, bylo, jest in ubylo:
        print(f"  [ubyło]     {nazwa} — {bylo} -> {jest}")
    if not (nowe or przybylo or ubylo):
        print("  zgodne z zamkiem")

    print("\nAudyty drzewa kontrolek (expand, chipy) uruchamia pytest:")
    print("  python -m pytest tests/test_audyty.py -q")
