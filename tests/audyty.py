"""Sześć audytów, które do tej pory były jednorazowymi skryptami.

Dwa pierwsze chodzą po FAKTYCZNIE zbudowanym drzewie kontrolek — nie po kodzie
źródłowym — bo pytanie brzmi „co się narysuje", a to zależy od tego, co
konstruktor widoku naprawdę poskładał. Trzy ostatnie czytają AST, bo dotyczą
rzeczy, których w drzewie już nie widać.

Moduł da się uruchomić wprost, żeby zobaczyć raport:

    python tests/audyty.py
    python tests/audyty.py --zapisz   # odświeża zamek na cichych `except: pass`

Asercje siedzą w test_audyty.py; tutaj są same silniki.
"""

import ast
import collections
import dataclasses
import inspect
import pathlib
import sys
import types
import typing

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
#  AUDYT 5 — kształt wyniku funkcji `db` (AST)
# ============================================================================
# `pobierz_dane_timeline` urosło kiedyś z ośmiu elementów krotki do dziewięciu.
# Rozpakowanie w innym pliku wywaliło się dopiero W CZASIE DZIAŁANIA, komunikatem
# „too many values to unpack" — czyli po wejściu na ekran, u kogoś, kto akurat
# miał dane. Adnotacje zwrotu na publicznych funkcjach `db` opisują ten kształt;
# ten audyt sprawdza, czy miejsca konsumpcji się z nim zgadzają.
#
# To nie jest kontrola typów, tylko kontrola ARNOŚCI — jedynej rzeczy, którą da
# się złamać cicho: `a, b, c = f()` przy czteroelementowej krotce, `w[7]` przy
# siedmiu polach, `w[0]` na słowniku.
#
# Zasada ostrożności jest ta sama, co w audycie pól kontrolek: śledzimy tylko
# zmienne wiązane w swoim zakresie DOKŁADNIE RAZ. Zmienna nadpisywana w pętli
# albo pod warunkiem może w danym miejscu trzymać cokolwiek, a audyt, który
# sypie fałszywkami, przestaje być czytany.
#
# Czego audyt NIE zobaczy: wiersza, który poszedł do funkcji pomocniczej
# (`utils.filtruj_po_kategorii(zdarzenia, …)`) albo do metody jako argument.
# Od tej strony pilnuje tego test wykonania — `tests/test_typy_db.py` woła
# funkcje na bazie testowej i sprawdza, czy naprawdę zwracają to, co deklarują.
# Razem zamykają obieg: zmiana kształtu zapala test wykonania, a poprawiona
# adnotacja zapala ten audyt na każdym miejscu, które trzeba dostosować.


def _rozbierz_adnotacje(adnotacja):
    """Adnotacja zwrotu -> (rodzaj, arność).

    rodzaj: 'krotka' (funkcja zwraca samą krotkę), 'lista-krotek',
    'lista-slownikow' albo 'inny'. Arność ma sens tylko dla dwóch pierwszych;
    None znaczy „nie wiadomo" (np. `tuple[int, ...]`)."""
    def bez_none(a):
        # `tuple[…] | None` — interesuje nas kształt, nie to, że bywa pusto.
        if typing.get_origin(a) in (types.UnionType, typing.Union):
            warianty = [x for x in typing.get_args(a) if x is not type(None)]
            return warianty[0] if len(warianty) == 1 else None
        return a

    adnotacja = bez_none(adnotacja)
    if adnotacja is None:
        return "inny", None

    zrodlo = typing.get_origin(adnotacja)
    argumenty = typing.get_args(adnotacja)

    if zrodlo is tuple:
        return ("krotka", None if Ellipsis in argumenty else len(argumenty))

    if zrodlo is list and argumenty:
        element = bez_none(argumenty[0])
        if element is not None:
            zrodlo_elementu = typing.get_origin(element)
            if zrodlo_elementu is tuple:
                argumenty_elementu = typing.get_args(element)
                return ("lista-krotek",
                        None if Ellipsis in argumenty_elementu else len(argumenty_elementu))
            if zrodlo_elementu is dict or element is dict:
                return "lista-slownikow", None

    return "inny", None


def funkcje_db():
    """Nazwy wszystkich publicznych funkcji pakietu `db`."""
    import db

    return {n for n in dir(db)
            if not n.startswith("_") and inspect.isfunction(getattr(db, n))}


def ksztalty_db():
    """{funkcja: (rodzaj, arność)} — z adnotacji zwrotu, tylko dla tych,
    z których w ogóle da się odczytać kształt."""
    import db

    ksztalty = {}
    for nazwa in funkcje_db():
        adnotacja = getattr(getattr(db, nazwa), "__annotations__", {}).get("return")
        if adnotacja is None:
            continue
        rodzaj, arnosc = _rozbierz_adnotacje(adnotacja)
        if rodzaj != "inny":
            ksztalty[nazwa] = (rodzaj, arnosc)
    return ksztalty


def _wezly_zakresu(zakres):
    """Węzły należące do TEGO zakresu — bez wnętrza zagnieżdżonych funkcji i klas.

    `ast.walk` zszedłby do funkcji wewnętrznych i policzył ich zmienne jako
    nasze; przy nazwach w rodzaju `w`, `t`, `r` to gwarancja fałszywek."""
    do_odwiedzenia = list(ast.iter_child_nodes(zakres))
    while do_odwiedzenia:
        wezel = do_odwiedzenia.pop()
        if isinstance(wezel, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        yield wezel
        do_odwiedzenia.extend(ast.iter_child_nodes(wezel))


def _zakresy(drzewo):
    yield drzewo
    for wezel in ast.walk(drzewo):
        if isinstance(wezel, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield wezel


def _wiazania(zakres):
    """Ile razy każda nazwa jest w tym zakresie wiązana — przypisaniem, pętlą,
    wyrażeniem listowym, `with … as`, `except … as` albo jako argument."""
    licznik = collections.Counter()

    def policz(cel):
        if isinstance(cel, ast.Name):
            licznik[cel.id] += 1
        elif isinstance(cel, (ast.Tuple, ast.List)):
            for element in cel.elts:
                policz(element)
        elif isinstance(cel, ast.Starred):
            policz(cel.value)

    if isinstance(zakres, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for grupa in (zakres.args.posonlyargs, zakres.args.args, zakres.args.kwonlyargs):
            for argument in grupa:
                licznik[argument.arg] += 1

    for wezel in _wezly_zakresu(zakres):
        if isinstance(wezel, ast.Assign):
            for cel in wezel.targets:
                policz(cel)
        elif isinstance(wezel, (ast.AugAssign, ast.AnnAssign, ast.NamedExpr)):
            policz(wezel.target)
        elif isinstance(wezel, (ast.For, ast.AsyncFor)):
            policz(wezel.target)
        elif isinstance(wezel, ast.comprehension):
            policz(wezel.target)
        elif isinstance(wezel, ast.withitem) and wezel.optional_vars is not None:
            policz(wezel.optional_vars)
        elif isinstance(wezel, ast.ExceptHandler) and wezel.name:
            licznik[wezel.name] += 1

    return licznik


def _wywolanie_db(wezel, znane):
    """`db.cokolwiek(...)` -> 'cokolwiek', o ile to nazwa z `znane`."""
    if not isinstance(wezel, ast.Call) or not isinstance(wezel.func, ast.Attribute):
        return None
    cel = wezel.func
    if isinstance(cel.value, ast.Name) and cel.value.id == "db" and cel.attr in znane:
        return cel.attr
    return None


def konsumpcje_db(sciezki=None, korzen=None, znane=None):
    """Miejsca, w których wynik `db.*` jest rozpakowywany albo indeksowany.

    Zwraca listę słowników {plik, linia, funkcja, rodzaj, liczba}:
    'rozpakowanie-wiersza' (liczba = ile nazw po lewej), 'rozpakowanie-wyniku'
    (funkcja zwraca samą krotkę) albo 'indeks' (liczba = użyty indeks)."""
    korzen = korzen or KORZEN_PROJEKTU
    znane = znane if znane is not None else funkcje_db()
    konsumpcje = []

    for sciezka in sciezki if sciezki is not None else _pliki_projektu():
        wzgledna = sciezka.relative_to(korzen).as_posix()
        drzewo = ast.parse(sciezka.read_text(encoding="utf-8"), filename=str(sciezka))

        for zakres in _zakresy(drzewo):
            raz = {n for n, ile in _wiazania(zakres).items() if ile == 1}
            wynik = {}    # zmienna -> funkcja db (trzyma CAŁY wynik)
            wiersz = {}   # zmienna -> funkcja db (trzyma JEDEN element listy)

            def zrodlo(wezel):
                nazwa = _wywolanie_db(wezel, znane)
                if nazwa:
                    return nazwa
                if isinstance(wezel, ast.Name) and wezel.id in raz:
                    return wynik.get(wezel.id)
                return None

            # 1. `zmienna = db.f(...)`
            for wezel in _wezly_zakresu(zakres):
                if (isinstance(wezel, ast.Assign) and len(wezel.targets) == 1
                        and isinstance(wezel.targets[0], ast.Name)
                        and wezel.targets[0].id in raz):
                    nazwa = _wywolanie_db(wezel.value, znane)
                    if nazwa:
                        wynik[wezel.targets[0].id] = nazwa

            # 2. pętle, wyrażenia listowe i rozpakowania
            for wezel in _wezly_zakresu(zakres):
                iteracje = []
                if isinstance(wezel, (ast.For, ast.AsyncFor)):
                    iteracje.append((wezel.target, wezel.iter, wezel.lineno))
                elif isinstance(wezel, ast.comprehension):
                    iteracje.append((wezel.target, wezel.iter, getattr(wezel.iter, "lineno", 0)))

                for cel, iterowane, linia in iteracje:
                    nazwa = zrodlo(iterowane)
                    if not nazwa:
                        continue
                    if isinstance(cel, ast.Name):
                        if cel.id in raz:
                            wiersz[cel.id] = nazwa
                    elif isinstance(cel, (ast.Tuple, ast.List)):
                        if not any(isinstance(e, ast.Starred) for e in cel.elts):
                            konsumpcje.append({"plik": wzgledna, "linia": linia, "funkcja": nazwa,
                                               "rodzaj": "rozpakowanie-wiersza", "liczba": len(cel.elts)})

                if (isinstance(wezel, ast.Assign) and len(wezel.targets) == 1
                        and isinstance(wezel.targets[0], (ast.Tuple, ast.List))):
                    nazwa = _wywolanie_db(wezel.value, znane)
                    cele = wezel.targets[0].elts
                    if nazwa and not any(isinstance(e, ast.Starred) for e in cele):
                        konsumpcje.append({"plik": wzgledna, "linia": wezel.lineno, "funkcja": nazwa,
                                           "rodzaj": "rozpakowanie-wyniku", "liczba": len(cele)})

            # 3. `wiersz[i]`
            for wezel in _wezly_zakresu(zakres):
                if not (isinstance(wezel, ast.Subscript) and isinstance(wezel.value, ast.Name)):
                    continue
                nazwa = wiersz.get(wezel.value.id)
                indeks = wezel.slice
                if not nazwa or not isinstance(indeks, ast.Constant):
                    continue
                if not isinstance(indeks.value, int) or isinstance(indeks.value, bool):
                    continue
                konsumpcje.append({"plik": wzgledna, "linia": wezel.lineno, "funkcja": nazwa,
                                   "rodzaj": "indeks", "liczba": indeks.value})

    return konsumpcje


def audyt_ksztaltu_wynikow(sciezki=None, korzen=None, ksztalty=None):
    """Konsumpcje wyników `db` niezgodne z adnotacją zwrotu."""
    ksztalty = ksztalty if ksztalty is not None else ksztalty_db()
    znaleziska = []

    for uzycie in konsumpcje_db(sciezki, korzen, znane=set(ksztalty)):
        rodzaj, arnosc = ksztalty[uzycie["funkcja"]]
        miejsce = {"plik": uzycie["plik"], "linia": uzycie["linia"]}
        wolane = f"db.{uzycie['funkcja']}()"

        if uzycie["rodzaj"] == "rozpakowanie-wiersza":
            if rodzaj == "lista-slownikow":
                znaleziska.append({**miejsce,
                    "opis": f"{wolane} zwraca słowniki, a wiersz jest rozpakowywany na {uzycie['liczba']} nazwy"})
            elif rodzaj == "lista-krotek" and arnosc is not None and uzycie["liczba"] != arnosc:
                znaleziska.append({**miejsce,
                    "opis": f"{wolane} zwraca krotki {arnosc}-elementowe, a rozpakowanie bierze {uzycie['liczba']}"})

        elif uzycie["rodzaj"] == "rozpakowanie-wyniku":
            if rodzaj == "krotka" and arnosc is not None and uzycie["liczba"] != arnosc:
                znaleziska.append({**miejsce,
                    "opis": f"{wolane} zwraca krotkę {arnosc}-elementową, a rozpakowanie bierze {uzycie['liczba']}"})

        elif uzycie["rodzaj"] == "indeks":
            if rodzaj == "lista-slownikow":
                znaleziska.append({**miejsce,
                    "opis": f"{wolane} zwraca słowniki, a wiersz jest indeksowany liczbą [{uzycie['liczba']}]"})
            elif rodzaj == "lista-krotek" and arnosc is not None and not -arnosc <= uzycie["liczba"] < arnosc:
                znaleziska.append({**miejsce,
                    "opis": f"{wolane} zwraca krotki {arnosc}-elementowe, a odczyt sięga po [{uzycie['liczba']}]"})

    return znaleziska


def funkcje_db_konsumowane_bez_adnotacji(sciezki=None, korzen=None):
    """Funkcje `db`, których wynik ktoś rozpakowuje albo indeksuje, a które nie
    mówią, jaki ten wynik ma kształt.

    Bez tego lista adnotacji po cichu przestaje nadążać za kodem: nowa funkcja
    zwracająca krotki nie zapala niczego, dopóki komuś nie wywali się przy
    rozpakowaniu — czyli w czasie działania, u użytkownika."""
    ksztalty = ksztalty_db()
    return sorted({u["funkcja"] for u in konsumpcje_db(sciezki, korzen)
                   if u["funkcja"] not in ksztalty})


# ============================================================================
#  AUDYT 6 — ręczne składanie liczb (AST)
# ============================================================================
# Przecinek dziesiętny i spacja co trzy cyfry to DECYZJA O WYGLĄDZIE, a nie
# szczegół implementacyjny. Rozsypana po plikach potrafi się rozjechać w sposób,
# którego nikt nie zgłosi, a każdy zauważy — jak „1.5 MB" na jednym ekranie
# i „1,5 MB" na drugim, w tej samej aplikacji.
#
# Audyt szuka dwóch rzeczy, które nie mają żadnego innego zastosowania niż skład
# liczby: separatora tysięcy w formacie (`:,`) oraz podmiany kropki na przecinek
# (i odwrotnie). Nie rusza `:.2f` — ten bywa potrzebny do rzeczy, które nie idą
# na ekran (pomiary czasu w logu).

# Miejsca, którym wolno składać liczbę samodzielnie. Każde jest decyzją:
#   db/pomocnicze.py — RDZEŃ, czyli to jedno miejsce, do którego reszta woła;
#   log.py           — świadoma kopia, bo log nie importuje niczego z projektu
#                      (zgodności obu pilnuje test w tests/test_formatowanie.py).
WOLNO_SKLADAC_LICZBY = {"db/pomocnicze.py", "log.py"}


def _spec_formatu(wezel):
    """Tekst specyfikacji formatu z `f"{x:,.2f}"` albo None."""
    if not isinstance(wezel, ast.FormattedValue) or wezel.format_spec is None:
        return None
    czesci = []
    for kawalek in wezel.format_spec.values:
        if isinstance(kawalek, ast.Constant) and isinstance(kawalek.value, str):
            czesci.append(kawalek.value)
    return "".join(czesci)


# Podmiany, które robi się WYŁĄCZNIE po to, żeby złożyć liczbę do pokazania.
# `replace(",", "")` i `replace(",", ".")` celowo tu nie ma — to idiomy PARSERA
# (patrz `_parsuj_liczbe_csv`), a audyt, który je zgłasza, sypie fałszywkami.
PODMIANY_SKLADU_LICZBY = {(".", ","), (",", " ")}


def _podmiana_separatora(wezel):
    """Opis, jeśli węzeł składa liczbę podmianą separatora."""
    if not (isinstance(wezel, ast.Call) and isinstance(wezel.func, ast.Attribute)
            and wezel.func.attr == "replace" and len(wezel.args) == 2):
        return None
    argumenty = [a.value for a in wezel.args
                 if isinstance(a, ast.Constant) and isinstance(a.value, str)]
    if len(argumenty) != 2:
        return None
    if tuple(argumenty) in PODMIANY_SKLADU_LICZBY:
        return f"replace({argumenty[0]!r}, {argumenty[1]!r})"
    return None


def audyt_recznego_formatowania(sciezki=None, korzen=None, dozwolone=None):
    """Miejsca, w których liczba jest składana z palca zamiast przez rdzeń."""
    korzen = korzen or KORZEN_PROJEKTU
    dozwolone = WOLNO_SKLADAC_LICZBY if dozwolone is None else dozwolone
    znaleziska = []

    for sciezka in sciezki if sciezki is not None else _pliki_projektu():
        wzgledna = sciezka.relative_to(korzen).as_posix()
        if wzgledna in dozwolone:
            continue
        drzewo = ast.parse(sciezka.read_text(encoding="utf-8"), filename=str(sciezka))

        for wezel in ast.walk(drzewo):
            spec = _spec_formatu(wezel)
            if spec and "," in spec:
                znaleziska.append({
                    "plik": wzgledna, "linia": wezel.lineno,
                    "opis": f"separator tysięcy w formacie {{…:{spec}}} zamiast db.liczba_na_tekst",
                })
            podmiana = _podmiana_separatora(wezel)
            if podmiana:
                znaleziska.append({
                    "plik": wzgledna, "linia": wezel.lineno,
                    "opis": f"ręczna podmiana separatora — {podmiana} — zamiast db.liczba_na_tekst",
                })

    return znaleziska


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

    print("\n== Audyt kształtu wyników db ==")
    ksztalty = ksztalty_db()
    print(f"  funkcji z opisanym kształtem: {len(ksztalty)}")
    print(f"  sprawdzonych miejsc konsumpcji: {len(konsumpcje_db(znane=set(ksztalty)))}")
    for z in audyt_ksztaltu_wynikow(ksztalty=ksztalty):
        print(f"  {z['plik']}:{z['linia']} — {z['opis']}")
    bez_adnotacji = funkcje_db_konsumowane_bez_adnotacji()
    for nazwa in bez_adnotacji:
        print(f"  [bez adnotacji] db.{nazwa}()")

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

    print("\n== Audyt ręcznego składania liczb ==")
    for z in audyt_recznego_formatowania():
        print(f"  {z['plik']}:{z['linia']} — {z['opis']}")

    print("\nAudyty drzewa kontrolek (expand, chipy) uruchamia pytest:")
    print("  python -m pytest tests/test_audyty.py -q")
