"""Jedenaście audytów, które do tej pory były jednorazowymi skryptami.

Dwa pierwsze chodzą po FAKTYCZNIE zbudowanym drzewie kontrolek — nie po kodzie
źródłowym — bo pytanie brzmi „co się narysuje", a to zależy od tego, co
konstruktor widoku naprawdę poskładał. Pozostałe czytają AST, bo dotyczą rzeczy,
których w drzewie już nie widać albo których w drzewie nie da się odróżnić od
słusznego wyjątku.

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
import utils  # noqa: E402


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


def znajdz_menu_w_pasku_zawijanym(korzen):
    """PopupMenuButton w pasku zawijanym — zajmie całą linijkę.

    Audyt wyżej szuka WIERSZY bez `tight=True`, bo o nie chodziło przy jego
    pisaniu. Chip filtra to jednak `Container > PopupMenuButton > Row(tight=True)`
    — wiersz w środku jest ciasny, więc tamten audyt przepuszcza go bez słowa,
    a mimo to chip rozkłada się na całą szerokość: `PopupMenuButton` nie ma
    własnej szerokości, a `Wrap` daje mu maxWidth całego paska.

    Tak rozjechał się pasek filtrów w „Dzienniku życia auta" — jedynym ekranie,
    który używał paska zawijanego zamiast przewijanego."""
    znaleziska = []

    def zawiera_menu(kontrolka, przodkowie):
        if isinstance(kontrolka, ft.PopupMenuButton):
            return _sciezka(przodkowie, kontrolka)
        if getattr(kontrolka, "width", None) is not None:
            return None
        for _pole, dziecko in _dzieci(kontrolka, POLA_DZIECI_CHIPY):
            trafienie = zawiera_menu(dziecko, przodkowie + [kontrolka])
            if trafienie:
                return trafienie
        return None

    def zejdz(kontrolka, przodkowie):
        if _jest_wierszem(kontrolka) and getattr(kontrolka, "wrap", False):
            for pole, dziecko in _dzieci(kontrolka, POLA_DZIECI_CHIPY):
                if pole != "controls":
                    continue
                winowajca = zawiera_menu(dziecko, przodkowie + [kontrolka])
                if winowajca:
                    znaleziska.append({
                        "sciezka": winowajca,
                        "powod": "PopupMenuButton w pasku zawijanym — weźmie całą linijkę; "
                                 "pasek filtrów robi się przewijany poziomo",
                    })
        for _pole, dziecko in _dzieci(kontrolka, POLA_DZIECI_CHIPY):
            zejdz(dziecko, przodkowie + [kontrolka])

    zejdz(korzen, [])
    return znaleziska


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
#  AUDYT 2b — płaskie zagnieżdżenia powierzchni (drzewo kontrolek)
# ============================================================================
# Ramka, wypełnienie, zaokrąglenie i cień to cztery sposoby powiedzenia „to jest
# osobny obiekt". Użyte na wszystkim naraz spłaszczają hierarchię: jeśli każda
# karta krzyczy tak samo głośno, to ważna karta niczym się nie wyróżnia.
#
# Audyt chodzi po ZBUDOWANYM drzewie, bo pytanie brzmi „co widać", a poziom
# powierzchni powstaje dopiero z motywu (jasny/ciemny/OLED). Sprawdza trzy rzeczy:
#
#   1. blok w karcie ma INNE tło niż karta — inaczej granica znika i zagnieżdżenie
#      nie czyta się wcale;
#   2. cień nie leży pod cieniem — druga warstwa unoszenia nic nie dodaje;
#   3. jedna powierzchnia nie łączy cienia z ramką — to dwa sposoby na to samo.
#
# Powierzchnią jest tylko to, co ma tło ze wspólnej drabinki (`utils.powierzchnia`).
# Pigułki, tory pasków i awatary mają własne, nazwane tła i nie udają kart.


def _drabinka_powierzchni(page):
    """Tła, które w tym motywie oznaczają powierzchnię: szczeble drabinki
    i ich kolorowe odpowiedniki dla stanów."""
    mapa = {}
    for poziom in (1, 2, 3):
        mapa[str(utils.tlo_karty(page, poziom=poziom))] = f"poziom {poziom}"
    for stan in utils.STANY_PODNOSZACE:
        mapa[str(utils.tlo_stanu(page, stan))] = f"stan {stan}"
    return mapa


def znajdz_plaskie_powierzchnie(korzen, page=None):
    """Powierzchnie, które powtarzają sygnał rodzica zamiast go stopniować."""
    drabinka = _drabinka_powierzchni(page)
    znaleziska = []

    def zejdz(kontrolka, przodkowie, rodzic_tlo, rodzic_cien):
        tlo = str(getattr(kontrolka, "bgcolor", "") or "")
        opis_tla = drabinka.get(tlo)
        if isinstance(kontrolka, ft.Container) and opis_tla:
            ma_cien = bool(getattr(kontrolka, "shadow", None))
            ma_ramke = bool(getattr(kontrolka, "border", None))
            sciezka = _sciezka(przodkowie, kontrolka)

            if rodzic_tlo is not None and tlo == rodzic_tlo:
                znaleziska.append({
                    "powod": f"powierzchnia w powierzchni na tym samym szczeblu ({opis_tla})",
                    "sciezka": sciezka,
                })
            if ma_cien and rodzic_cien:
                znaleziska.append({"powod": "cień pod cieniem", "sciezka": sciezka})
            if ma_cien and ma_ramke:
                znaleziska.append({
                    "powod": "cień i ramka naraz — dwa sposoby na to samo",
                    "sciezka": sciezka,
                })
            rodzic_tlo, rodzic_cien = tlo, rodzic_cien or ma_cien

        for _, dziecko in _dzieci(kontrolka):
            zejdz(dziecko, przodkowie + [kontrolka], rodzic_tlo, rodzic_cien)

    zejdz(korzen, [], None, False)
    return znaleziska


# ============================================================================
#  AUDYT 2c — `expand` bezpośrednio w kontenerze (drzewo kontrolek)
# ============================================================================
# `expand` tłumaczy się na flutterowy `Expanded`, a `Expanded` MUSI być dzieckiem
# Row albo Column. `Container.content` nie jest niczym takim — rozciągliwe
# dziecko nie ma tam czego wypełnić.
#
# Objaw jest mylący, bo nic nie wybucha: kontrolka dostaje nieograniczoną
# wysokość i szerokość. Przewijana kolumna przestaje się przewijać, a pasek
# filtrów w nieograniczonej szerokości rozkłada każdy chip na osobną linijkę.
# Dokładnie to stało się „Dziennikowi życia auta" po wprowadzeniu szkieletów:
# `zbuduj_etapami` opakowuje treść w `ft.Container`, a treść wracała jako
# `Column(expand=True, scroll=ALWAYS)`.


def znajdz_expand_w_kontenerze(korzen):
    """Rozciągliwe kontrolki wstawione wprost do `Container.content`."""
    znaleziska = []

    def zejdz(kontrolka, przodkowie):
        if isinstance(kontrolka, ft.Container):
            dziecko = getattr(kontrolka, "content", None)
            # Kontener z WŁASNĄ wysokością (albo sam rozciągliwy) ogranicza dziecko,
            # więc `expand` jest tam co najwyżej zbędny — bez wysokości dziecko
            # dostaje nieskończoność i to dopiero psuje ekran.
            ograniczony = bool(getattr(kontrolka, "height", None) or getattr(kontrolka, "expand", None))
            if isinstance(dziecko, ft.Control) and getattr(dziecko, "expand", None) and not ograniczony:
                znaleziska.append({
                    "powod": f"{type(dziecko).__name__}(expand=…) w Containerze bez wysokości "
                             "— `Expanded` działa tylko w Row/Column, więc dziecko dostaje nieskończoność",
                    "sciezka": _sciezka(przodkowie + [kontrolka], dziecko),
                })
        for _, dziecko in _dzieci(kontrolka):
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
#  AUDYT 7 — pogrubienie na drugim planie (AST)
# ============================================================================
# `weight="bold"` bywało w tym projekcie domyślną wagą etykiet. Kiedy wszystko
# jest ważne, nic nie jest — a na kaflach kokpitu i kartach list, gdzie w małej
# przestrzeni stoi po pięć elementów, oko nie ma się wtedy o co zaczepić.
#
# Audyt pilnuje jednej reguły, bo tylko ona daje się rozstrzygnąć z kodu:
# **pogrubienie nie chodzi w parze z ON_SURFACE_VARIANT**. Przygaszony kolor
# mówi „drugi plan", pogrubienie mówi „pierwszy" — postawione razem znoszą się
# i zostaje sam szum. Nagłówki i wartości zostają pogrubione, ale w pełnym
# kolorze tekstu; etykiety zostają przygaszone, ale zwykłą wagą.
#
# Zgłaszamy WYŁĄCZNIE przypadki rozstrzygnięte na pewno. Kolor spod `.get(...)`
# albo z gołej zmiennej jest nie do odczytania z AST i audyt go nie rusza —
# lepiej przepuścić kilka niż nauczyć zespół, że ten audyt sypie fałszywkami.

WAGI_POGRUBIONE = {"bold", "w600", "w700", "w800", "w900"}

KOLOR_DRUGIEGO_PLANU = "ON_SURFACE_VARIANT"

# Pomocniki z utils/typografia.py: same w sobie trzymają regułę, więc pilnujemy
# tylko tego, żeby nie obchodzić jej nadpisaniem przy wywołaniu.
POMOCNIKI_DRUGIEGO_PLANU = {"etykieta", "podpis"}
POMOCNIKI_WARTOSCI = {"wartosc"}


def _mozliwe_wagi(wezel):
    """Wagi, jakie węzeł MOŻE przyjąć. Pusty zbiór = nie do rozstrzygnięcia.

    Wyrażenie warunkowe (`"bold" if biezacy else "normal"`) rozbieramy na obie
    gałęzie: taka waga niesie znaczenie („jesteś tutaj") i wolno jej zostać,
    dopóki gałąź pogrubiona nie jest przygaszona."""
    if isinstance(wezel, ast.Constant) and isinstance(wezel.value, str):
        return {wezel.value}
    if isinstance(wezel, ast.IfExp):
        return _mozliwe_wagi(wezel.body) | _mozliwe_wagi(wezel.orelse)
    # ft.FontWeight.BOLD — w projekcie rzadkie, ale zapis równoważny napisowi.
    if isinstance(wezel, ast.Attribute) and isinstance(wezel.value, ast.Attribute) \
            and wezel.value.attr == "FontWeight":
        return {wezel.attr.lower()}
    return set()


def _mozliwe_kolory(wezel):
    """Nazwy kolorów, jakie węzeł MOŻE przyjąć (ostatni człon `ft.Colors.X`)."""
    if isinstance(wezel, ast.Attribute):
        return {wezel.attr}
    if isinstance(wezel, ast.IfExp):
        return _mozliwe_kolory(wezel.body) | _mozliwe_kolory(wezel.orelse)
    return set()


def _argument(wezel, nazwa):
    for slowo in wezel.keywords:
        if slowo.arg == nazwa:
            return slowo.value
    return None


def _nazwa_wywolania(wezel):
    """`utils.etykieta(...)` i `etykieta(...)` -> 'etykieta'."""
    if isinstance(wezel.func, ast.Attribute):
        return wezel.func.attr
    if isinstance(wezel.func, ast.Name):
        return wezel.func.id
    return None


def znajdz_pogrubienia_na_drugim_planie(korzen):
    """Ta sama reguła, ale na ZBUDOWANYM drzewie — bo połowa kolorów powstaje
    dopiero w czasie działania.

    `KOLORY_STATUSU.get(...)`, `kolor if pilne else ...`, kolor podany zmienną —
    z kodu źródłowego nie da się ich rozstrzygnąć, a to właśnie one dają
    najbrzydsze trafienia: „Brak wpisów" pogrubione i przygaszone naraz, bo
    zmienna `kol` akurat tym razem wyszła na ON_SURFACE_VARIANT."""
    znaleziska = []

    def zejdz(kontrolka, przodkowie):
        if isinstance(kontrolka, ft.Text):
            waga = str(getattr(kontrolka, "weight", "") or "")
            kolor = str(getattr(kontrolka, "color", "") or "")
            tekst = str(getattr(kontrolka, "value", "") or "").strip()
            if tekst and waga.lower() in WAGI_POGRUBIONE and kolor.endswith(KOLOR_DRUGIEGO_PLANU):
                znaleziska.append({
                    "tekst": tekst[:60],
                    "sciezka": _sciezka(przodkowie, kontrolka),
                })
        for _, dziecko in _dzieci(kontrolka):
            zejdz(dziecko, przodkowie + [kontrolka])

    zejdz(korzen, [])
    return znaleziska


def audyt_pogrubien(sciezki=None, korzen=None):
    """Teksty, w których pogrubienie spotyka się z kolorem drugiego planu."""
    korzen = korzen or KORZEN_PROJEKTU
    znaleziska = []

    for sciezka in sciezki if sciezki is not None else _pliki_projektu():
        wzgledna = sciezka.relative_to(korzen).as_posix()
        drzewo = ast.parse(sciezka.read_text(encoding="utf-8"), filename=str(sciezka))

        for wezel in ast.walk(drzewo):
            if not isinstance(wezel, ast.Call):
                continue
            nazwa = _nazwa_wywolania(wezel)
            wagi = _mozliwe_wagi(_argument(wezel, "weight") or ast.Pass())
            pogrubione = bool(wagi) and wagi <= WAGI_POGRUBIONE

            if _nazwa_konstruktora(wezel) == "Text":
                kolory = _mozliwe_kolory(_argument(wezel, "color") or ast.Pass())
                if pogrubione and kolory == {KOLOR_DRUGIEGO_PLANU}:
                    znaleziska.append({
                        "plik": wzgledna, "linia": wezel.lineno,
                        "opis": "pogrubiony tekst w kolorze drugiego planu "
                                f"({KOLOR_DRUGIEGO_PLANU}) — etykieta albo wartość, wybierz jedno",
                    })
            elif nazwa in POMOCNIKI_DRUGIEGO_PLANU and pogrubione:
                znaleziska.append({
                    "plik": wzgledna, "linia": wezel.lineno,
                    "opis": f"utils.{nazwa}() nadpisane pogrubieniem — to wtedy już nie etykieta",
                })
            elif nazwa in POMOCNIKI_WARTOSCI:
                kolory = _mozliwe_kolory(_argument(wezel, "color") or ast.Pass())
                if kolory == {KOLOR_DRUGIEGO_PLANU}:
                    znaleziska.append({
                        "plik": wzgledna, "linia": wezel.lineno,
                        "opis": f"utils.{nazwa}() przygaszone do koloru drugiego planu "
                                "— wartość albo się liczy, albo nie",
                    })

    return znaleziska


# ============================================================================
#  AUDYT 8 — paleta statusów (AST)
# ============================================================================
# Kolor jest w tej aplikacji nośnikiem informacji: czerwień znaczy „po terminie",
# bursztyn „zbliża się", zieleń „w porządku". Cała wartość tego kodu stoi na
# jednym warunku — że ten sam odcień znaczy wszędzie to samo. Wystarczy, że
# w trzech miejscach czerwień jest inna, a przestaje być kodem, a staje się
# dekoracją.
#
# Audyt szuka odcieni statusowych wpisanych wprost w widoku, zamiast wziętych
# z `KOLOR_STATUS`. Nie chodzi o piksele — te zwykle się zgadzają — tylko o to,
# że taki literał jest kopią, która nie wie, że jest kopią: zmiana palety jej
# nie dotyczy.
#
# Trzy drogi wyjścia, w kolejności od najlepszej:
#   1. wziąć kolor z KOLOR_STATUS po nazwie roli;
#   2. dopisać go do nazwanej mapy tożsamości (patrz MAPY_TOZSAMOSCI);
#   3. oznaczyć miejsce komentarzem `# paleta: tożsamość` — gdy kolor naprawdę
#      nic nie mówi o stanie, tylko odróżnia rzecz od rzeczy (kategoria kosztu,
#      typ wpisu, seria wykresu).

# Odcienie, które w tej aplikacji NIOSĄ znaczenie — razem z sąsiadami o jeden
# stopień obok, bo to właśnie one rozjeżdżają kod: „prawie ta sama czerwień"
# jest gorsza niż zupełnie inny kolor, bo wygląda na pomyłkę dopiero obok.
ODCIENIE_STATUSU = {
    "RED", "RED_700",
    "ORANGE_700", "ORANGE_800", "DEEP_ORANGE_700",
    "GREEN_700",
    "AMBER_700", "AMBER_800",
}

# Plik, w którym paleta i mapy tożsamości mają prawo istnieć. To jedyne miejsce,
# gdzie odcień wolno napisać wprost — bo tu właśnie się go NAZYWA.
DOM_PALETY = "utils/stale.py"

# Nazwane mapy, w których kolor odróżnia rzecz od rzeczy, a nie stan od stanu.
# TEAL przy kategorii nie mówi nic o pilności — i właśnie dlatego nie podlega
# palecie statusów.
MAPY_TOZSAMOSCI = {
    "IKONY_TIMELINE",
    "IKONY_WYSZUKIWANIA",
    "PALETA_KOLOROW",
    "KOLORY_ROL",
    "EKRANY",
    "GRUPY_EKRANOW",
}

# Znacznik przy linii (albo w linijce nad nią) zdejmujący miejsce z audytu.
# Wyjątek stoi TAM, gdzie zapadła decyzja — nie na liście w innym pliku, która
# rozjeżdża się z kodem przy pierwszym przesunięciu linii.
ZNACZNIK_TOZSAMOSCI = "# paleta: tożsamość"


def _kolor_fleta(wezel):
    """`ft.Colors.RED_700` -> 'RED_700'; wszystko inne -> None."""
    if not isinstance(wezel, ast.Attribute):
        return None
    cel = wezel.value
    if isinstance(cel, ast.Attribute) and cel.attr == "Colors":
        return wezel.attr
    return None


def _miejsca_w_mapach_tozsamosci(drzewo):
    """Pozycje kolorów stojących wewnątrz nazwanej mapy tożsamości."""
    zwolnione = set()
    for wezel in ast.walk(drzewo):
        cele = []
        if isinstance(wezel, ast.Assign):
            cele = wezel.targets
        elif isinstance(wezel, ast.AnnAssign):
            cele = [wezel.target]
        if not any(isinstance(c, ast.Name) and c.id in MAPY_TOZSAMOSCI for c in cele):
            continue
        for w in ast.walk(wezel.value):
            if _kolor_fleta(w):
                zwolnione.add((w.lineno, w.col_offset))
    return zwolnione


def audyt_palety_statusow(sciezki=None, korzen=None):
    """Odcienie statusowe wpisane wprost, zamiast wzięte z KOLOR_STATUS."""
    korzen = korzen or KORZEN_PROJEKTU
    znaleziska = []

    for sciezka in sciezki if sciezki is not None else _pliki_projektu():
        wzgledna = sciezka.relative_to(korzen).as_posix()
        if wzgledna == DOM_PALETY:
            continue

        tresc = sciezka.read_text(encoding="utf-8")
        linie = tresc.splitlines()
        drzewo = ast.parse(tresc, filename=str(sciezka))
        zwolnione = _miejsca_w_mapach_tozsamosci(drzewo)

        for wezel in ast.walk(drzewo):
            nazwa = _kolor_fleta(wezel)
            if nazwa not in ODCIENIE_STATUSU:
                continue
            if (wezel.lineno, wezel.col_offset) in zwolnione:
                continue
            sasiedztwo = linie[max(0, wezel.lineno - 2):wezel.lineno]
            if any(ZNACZNIK_TOZSAMOSCI in w for w in sasiedztwo):
                continue
            znaleziska.append({
                "plik": wzgledna, "linia": wezel.lineno, "col": wezel.col_offset,
                "kolor": nazwa,
                "opis": f"ft.Colors.{nazwa} wpisane wprost zamiast roli z KOLOR_STATUS",
            })

    return znaleziska


# ============================================================================
#  AUDYT 9 — porzucone korutyny metod Fleta (AST)
# ============================================================================
# Bliźniak audytu `run_task`. Część metod kontrolek Fleta to KORUTYNY —
# `scroll_to`, `show_drawer`, `launch_url`, `pick_files`, `take_screenshot`.
# Wywołane bez `await` tworzą obiekt korutyny, wyrzucają go i nie robią NIC.
# Po cichu: żadnego błędu, żadnego ostrzeżenia w interfejsie, ekran po prostu
# zachowuje się tak, jakby kodu nie było.
#
# Ta usterka zjadła w tym projekcie całą pamięć pozycji przewijania: powrót na
# zapamiętane miejsce był napisany, przetestowany i nigdy nie zadziałał, bo
# `kontrolka.scroll_to(...)` stało bez `await`.
#
# Listę nazw bierzemy Z FLETA, a nie z własnego spisu: przy zmianie wersji
# biblioteki spis rozjechałby się po cichu, a to jest dokładnie ten rodzaj
# cichego rozjazdu, któremu ten audyt ma zapobiegać.

# Klasy, z których zbieramy nazwy metod asynchronicznych.
KLASY_FLETA_DO_SKANU = ("Page", "View", "Control", "ListView", "FilePicker")

# Nazwy, które kolidują z czymś własnym albo są wołane wyłącznie przez Fleta.
POMIJANE_NAZWY_ASYNC = {"login", "logout"}

# Świadome wyjątki: (plik, metoda). Wszystkie trzy to gałąź dla STARSZYCH Fletów,
# w których `save_file`/`pick_files` były synchroniczne, a wynik przychodził przez
# `on_result`. Na 0.8x warunek `hasattr(page, "services")` jest prawdziwy, więc
# ta gałąź w ogóle się nie wykonuje — ale ma zostać, bo to ona obsługuje starsze
# wersje (ta sama sytuacja, co wpis FilePicker/on_result w DOZWOLONE_POLA).
DOZWOLONE_KORUTYNY = {
    ("main.py", "save_file"),
    ("main.py", "pick_files"),
}


def nazwy_metod_async_fleta():
    """Nazwy metod Fleta, które są korutynami."""
    nazwy = set()
    for nazwa_klasy in KLASY_FLETA_DO_SKANU:
        klasa = getattr(ft, nazwa_klasy, None)
        if klasa is None:
            continue
        for nazwa in dir(klasa):
            if nazwa.startswith("_"):
                continue
            if inspect.iscoroutinefunction(getattr(klasa, nazwa, None)):
                nazwy.add(nazwa)
    return nazwy - POMIJANE_NAZWY_ASYNC


def _zmienne_sprawdzane_isawaitable(zakres):
    """Nazwy, o które ktoś w tym zakresie pyta `inspect.isawaitable`.

    To zgodnościowy idiom tego projektu: ta sama metoda bywa w starszych Fletach
    synchroniczna, więc wynik sprawdza się przed `await`. Taki zapis jest
    poprawny i audyt ma go przepuścić."""
    nazwy = set()
    for wezel in ast.walk(zakres):
        if not (isinstance(wezel, ast.Call) and isinstance(wezel.func, ast.Attribute)):
            continue
        if wezel.func.attr != "isawaitable" or not wezel.args:
            continue
        cel = wezel.args[0]
        if isinstance(cel, ast.Name):
            nazwy.add(cel.id)
    return nazwy


def audyt_porzuconych_korutyn(sciezki=None, korzen=None):
    """Wywołania asynchronicznych metod Fleta, których nikt nie odbiera."""
    korzen = korzen or KORZEN_PROJEKTU
    nazwy_async = nazwy_metod_async_fleta()
    znaleziska = []

    for sciezka in sciezki if sciezki is not None else _pliki_projektu():
        wzgledna = sciezka.relative_to(korzen).as_posix()
        drzewo = ast.parse(sciezka.read_text(encoding="utf-8"), filename=str(sciezka))

        # Rodzic każdego węzła — po to, żeby odróżnić `await x.scroll_to()`
        # od samotnego `x.scroll_to()`.
        rodzice = {}
        for wezel in ast.walk(drzewo):
            for dziecko in ast.iter_child_nodes(wezel):
                rodzice[dziecko] = wezel

        pilnowane = _zmienne_sprawdzane_isawaitable(drzewo)

        for wezel in ast.walk(drzewo):
            if not (isinstance(wezel, ast.Call) and isinstance(wezel.func, ast.Attribute)):
                continue
            nazwa = wezel.func.attr
            if nazwa not in nazwy_async:
                continue

            rodzic = rodzice.get(wezel)
            if isinstance(rodzic, ast.Await):
                continue
            # `wynik = x.scroll_to(...)` plus `inspect.isawaitable(wynik)` niżej.
            if isinstance(rodzic, ast.Assign):
                cele = [c.id for c in rodzic.targets if isinstance(c, ast.Name)]
                if any(c in pilnowane for c in cele):
                    continue

            if (wzgledna, nazwa) in DOZWOLONE_KORUTYNY:
                continue

            znaleziska.append({
                "plik": wzgledna, "linia": wezel.lineno, "metoda": nazwa,
                "opis": f"`{nazwa}(...)` bez await — korutyna powstaje i ginie, nic się nie dzieje",
            })

    return znaleziska


# ============================================================================
#  AUDYT 10 — tekst ucięty na wąskim telefonie (drzewo kontrolek)
# ============================================================================
# Flutter o uciętym napisie milczy: linia z `no_wrap` kończy się „…”, wiersz
# szerszy niż ekran gubi koniec, za długa etykieta pola łamie się w dwie linie
# w środku pustego pola, a ściśnięta kolumna łamie słowo litera po literze.
# Audyt rozkłada szerokość jak RenderFlex (wiersz: najpierw dzieci sztywne,
# reszta po równo dla `expand`) na telefonie 360 dp i mierzy napisy metryką
# Roboto. Pomija przewijane paski i rozwijane menu — tam szerokości nie brakuje.

SZEROKOSC_TELEFONU = 360
TOLERANCJA_DP = 1.0
ZNAK_SPOZA_TABELI_EM = 0.6

# Szerokości znaków Roboto w em (Google Fonts, wagi 400/500/700).
_SZEROKOSCI_ROBOTO = {
    400: {
        0.17: "'", 0.2: ',‘’‚', 0.21: ';', 0.24: ':ijl|', 0.25: ' \xa0í', 0.26: '!.·', 0.27: 'I[]ł',
        0.28: '-', 0.31: '`', 0.32: '"', 0.33: 't', 0.34: '(r{}„•', 0.35: ')f“', 0.36: '”', 0.37: '°²³',
        0.41: '/\\', 0.42: '^', 0.43: '*', 0.45: '_', 0.47: '?y«»', 0.48: 'v', 0.5: 'xzźż', 0.51: '<k',
        0.52: '>csçćś', 0.53: 'e×éèêëę±', 0.54: 'LaäáąŁ', 0.55: '=FJhnuüúñń', 0.56: '$0123456789bdgp€',
        0.57: '+EoqöóÉóĘ−', 0.59: 'SŚ', 0.6: 'TYZŹŻ', 0.62: '#&BR', 0.63: 'KPX™', 0.64: 'V',
        0.65: 'ACUÜÄÁĄĆ', 0.66: 'D–', 0.67: '…', 0.68: 'G~', 0.69: 'OQÖÓ', 0.71: 'HNŃ', 0.73: '%', 0.75: 'w',
        0.78: '—', 0.87: 'M', 0.88: 'm', 0.89: 'W', 0.9: '@',
    },
    500: {
        0.17: "'", 0.22: ',‘’', 0.23: '‚', 0.24: ';', 0.25: ' j|\xa0', 0.26: 'ilí', 0.27: '!:[]',
        0.28: '.I·', 0.29: 'ł', 0.32: '"`', 0.33: '-t', 0.34: '{}', 0.35: '()fr•', 0.37: '²³', 0.38: '°“„',
        0.39: '”', 0.4: '/', 0.42: '\\', 0.43: '^', 0.44: '*', 0.45: '_', 0.49: '?vy«»', 0.5: 'xzźż',
        0.51: '<', 0.52: '>cksçćś', 0.53: '×', 0.54: 'Laeéèêëäáąę±', 0.55: 'FŁ', 0.56: '+=Jbdhnpuüúñń−',
        0.57: '$0123456789EgoqöóÉóĘ€', 0.6: 'SZŚŹŻ', 0.61: '#TY', 0.62: 'R', 0.63: 'BKX™', 0.64: '&P',
        0.65: 'CDUVÜĆ–', 0.66: '~', 0.67: 'AÄÁĄ', 0.68: 'G', 0.69: 'OQÖÓ', 0.71: 'HNŃ…', 0.73: '%',
        0.74: 'w', 0.77: '—', 0.87: 'm', 0.88: 'MW', 0.89: '@',
    },
    700: {
        0.16: "'", 0.23: '‘’', 0.24: ',', 0.25: ' |\xa0‚', 0.26: ';j', 0.27: '!ilí', 0.28: ':[]', 0.29: '.I',
        0.3: '·', 0.31: 'ł', 0.32: '"', 0.33: '`{}', 0.34: 't', 0.35: '()', 0.36: 'fr•', 0.37: '/²³',
        0.39: '-°', 0.4: '„', 0.41: '“”', 0.42: '\\', 0.44: '^', 0.45: '*_', 0.5: '?y«»', 0.51: '<svxzśźż',
        0.52: '>cçć', 0.53: 'k×', 0.54: 'Laeéèêëäáąę±', 0.55: '+F', 0.56: 'EJbdhnpquüúñÉńĘŁ−',
        0.57: '$0123456789=goöóó€', 0.6: '#', 0.61: 'SZŚŹŻ', 0.62: 'TY', 0.63: 'K–™', 0.64: 'BRX',
        0.65: 'CDPV~Ć', 0.66: '&UÜ', 0.67: 'AÄÁĄ', 0.68: 'G', 0.69: 'OQÖÓ', 0.71: 'HNŃ', 0.73: 'w',
        0.74: '%…', 0.76: '—', 0.87: 'Wm', 0.88: 'M', 0.9: '@',
    },
}

_ZNAKI_ROBOTO = {waga: {znak: em for em, znaki in grupy.items() for znak in znaki}
                 for waga, grupy in _SZEROKOSCI_ROBOTO.items()}

# Style Material 3: (rozmiar, waga, odstęp liter).
STYL_TRESCI = (14, 400, 0.25)       # bodyMedium — ft.Text bez stylu
STYL_POLA = (16, 400, 0.5)          # bodyLarge — wartość, etykieta i podpowiedź pola
STYL_ETYKIETY_UNIESIONEJ = (12, 400, 0.5)
STYL_PRZYCISKU = (14, 500, 0.1)     # labelLarge
STYL_TYTULU_PASKA = (22, 400, 0.0)  # titleLarge
STYL_PODPISU_NAWIGACJI = (12, 500, 0.5)
STYLE_MOTYWU = {
    "displaylarge": (57, 400, -0.25), "displaymedium": (45, 400, 0.0), "displaysmall": (36, 400, 0.0),
    "headlinelarge": (32, 400, 0.0), "headlinemedium": (28, 400, 0.0), "headlinesmall": (24, 400, 0.0),
    "titlelarge": STYL_TYTULU_PASKA, "titlemedium": (16, 500, 0.15), "titlesmall": (14, 500, 0.1),
    "bodylarge": STYL_POLA, "bodymedium": STYL_TRESCI, "bodysmall": (12, 400, 0.4),
    "labellarge": STYL_PRZYCISKU, "labelmedium": STYL_PODPISU_NAWIGACJI, "labelsmall": (11, 500, 0.5),
}

# Stałe układu Fleta/Material 3 potrzebne do policzenia miejsca na napis (dp).
POLE_SZEROKOSC_W_KOLUMNIE = 300     # TextField w ft.Column bez width — zmierzone na flet-web 0.86
POLE_PADDING_DOMYSLNY = 24
POLE_IKONA_PRZEDROSTKA = 45         # ikona przed tekstem razem z lewym marginesem
POLE_IKONA_ZA = 48
LISTA_POZA_TEKSTEM = 71             # ft.Dropdown: lewy margines + strzałka (zmierzone na flet-web 0.86)
LISTA_DOPELNIENIE_OPCJI = 88        # szerokość listy bez `width`: najdłuższa opcja (14 dp) + to
LISTA_DOPELNIENIE_ETYKIETY = 99     # … albo etykieta (12 dp) + to, jeśli dłuższa
POLE_WYBORU_KWADRAT = {"Checkbox": 40, "Radio": 40, "Switch": 60}
PRZYCISK_PADDING = 48               # Button / FilledButton / OutlinedButton: 24 + 24
PRZYCISK_TEKSTOWY_PADDING = 24      # TextButton: 12 + 12
PRZYCISK_IKONA = 26                 # ikona 18 + odstęp 8
IKONA_PRZYCISKU_ROZMIAR = 48
KARTA_MARGINES = 8                  # ft.Card: 4 + 4
OKNO_MARGINES = 80                  # ft.AlertDialog: 40 dp z każdej strony ekranu
OKNO_PADDING = 48                   # tytuł i treść okna: 24 + 24
STYL_TYTULU_OKNA = (24, 400, 0.0)   # headlineSmall
SZUFLADA_ODSTEP = 56                # szuflada nawigacji zostawia pas ekranu z prawej
WIERSZ_ODSTEP_DOMYSLNY = 10


def _waga_pisma(waga):
    if waga is None:
        return None
    tekst = str(getattr(waga, "value", waga)).lower()
    if tekst in ("bold", "w600", "w700", "w800", "w900"):
        return 700
    if tekst == "w500":
        return 500
    return 400


def szerokosc_tekstu(tekst, styl=STYL_TRESCI):
    """Szerokość napisu w jednej linii (dp) — metryka Roboto, odstęp liter z Material 3."""
    rozmiar, waga, odstep = styl
    tabela = _ZNAKI_ROBOTO[waga]
    return sum(tabela.get(znak, ZNAK_SPOZA_TABELI_EM) for znak in tekst) * rozmiar + odstep * len(tekst)


def _styl_napisu(napis, domyslny=STYL_TRESCI):
    rozmiar, waga, odstep = domyslny
    motyw = getattr(napis, "theme_style", None)
    if motyw is not None:
        klucz = str(getattr(motyw, "value", motyw)).replace("_", "").lower()
        rozmiar, waga, odstep = STYLE_MOTYWU.get(klucz, domyslny)
    styl = getattr(napis, "style", None)
    if styl is not None:
        rozmiar = getattr(styl, "size", None) or rozmiar
        waga = _waga_pisma(getattr(styl, "weight", None)) or waga
        if getattr(styl, "letter_spacing", None) is not None:
            odstep = styl.letter_spacing
    rozmiar = getattr(napis, "size", None) or rozmiar
    waga = _waga_pisma(getattr(napis, "weight", None)) or waga
    return rozmiar, waga, odstep


def _tresc_spanu(span):
    return (getattr(span, "text", None) or "") + "".join(_tresc_spanu(s) for s in (getattr(span, "spans", None) or []))


def _tresc_napisu(napis):
    tresc = napis.value if isinstance(napis.value, str) else ("" if napis.value is None else str(napis.value))
    return tresc + "".join(_tresc_spanu(s) for s in (napis.spans or []))


def _skrot(tekst, ile=40):
    tekst = " ".join(str(tekst).split())
    return tekst if len(tekst) <= ile else tekst[:ile - 1] + "…"


def _czesci_slowa(slowo):
    """Słowo pocięte w miejscach, w których Flutter wolno złamać linię (po „/” i „-”)."""
    czesci, biezaca = [], ""
    for i, znak in enumerate(slowo):
        biezaca += znak
        if znak in "/-" and i + 1 < len(slowo):
            czesci.append(biezaca)
            biezaca = ""
    return czesci + ([biezaca] if biezaca else [])


def linie_tekstu(tekst, szerokosc, styl=STYL_TRESCI):
    """(liczba linii, słowo łamane w środku albo None) przy zawijaniu po słowach."""
    spacja = szerokosc_tekstu(" ", styl)
    linie, lamane = 0, None
    for akapit in str(tekst).split("\n"):
        linie += 1
        biezaca = 0.0
        for slowo in akapit.split(" "):
            for kawalek in _czesci_slowa(slowo) or [""]:
                w = szerokosc_tekstu(kawalek, styl)
                if w > szerokosc + TOLERANCJA_DP and lamane is None:
                    lamane = slowo
                if biezaca and biezaca + spacja + w > szerokosc + TOLERANCJA_DP:
                    linie += 1
                    biezaca = w
                else:
                    biezaca += (spacja if biezaca else 0) + w
    return linie, lamane


def _poziomo(odstep):
    """Suma lewego i prawego odstępu (padding/margin) w dp."""
    if odstep is None:
        return 0
    if isinstance(odstep, (int, float)):
        return 2 * odstep
    return (getattr(odstep, "left", 0) or 0) + (getattr(odstep, "right", 0) or 0)


def _elastycznosc(kontrolka):
    rozciagnij = getattr(kontrolka, "expand", None) or getattr(kontrolka, "expand_loose", None)
    if rozciagnij is True:
        return 1
    return rozciagnij if isinstance(rozciagnij, int) and rozciagnij > 0 else 0


def _kolumna_responsywna(kontrolka):
    col = getattr(kontrolka, "col", None)
    if isinstance(col, dict):
        for klucz in ("xs", "sm", "md", "lg", "xl", "xxl"):
            if klucz in col:
                return col[klucz]
        return 12
    return col if isinstance(col, (int, float)) and col else 12


def _klasy(*nazwy):
    return tuple(k for k in (getattr(ft, n, None) for n in nazwy) if isinstance(k, type))


PRZYCISKI = _klasy("Button", "ElevatedButton", "FilledButton", "FilledTonalButton", "OutlinedButton", "TextButton")
PRZYCISKI_TEKSTOWE = _klasy("TextButton")
POLA_WYBORU = _klasy("Checkbox", "Switch", "Radio")
OPAKOWANIA_BEZ_ZMIANY_SZEROKOSCI = _klasy(
    "GestureDetector", "AnimatedSwitcher", "Semantics", "MergeSemantics", "TransparentPointer",
    "Draggable", "DragTarget", "Dismissible", "SafeArea", "WindowDragArea", "Tooltip", "Hero",
)


class _AudytNapisow:
    """Jedno przejście po drzewie: szerokość dostępna dla każdej kontrolki i zgłoszenia."""

    def __init__(self, szerokosc):
        self.szerokosc = szerokosc
        self.znaleziska = []
        self._odwiedzone = set()

    def zglos(self, rodzaj, przodkowie, kontrolka, opis):
        self.znaleziska.append({"rodzaj": rodzaj, "sciezka": _sciezka(przodkowie, kontrolka), "opis": opis})

    # ---------------- szerokość własna (jak intrinsic width) ----------------

    def naturalna(self, k, styl=STYL_TRESCI):
        """Szerokość, którą kontrolka zajmie, gdy nikt jej nie ogranicza."""
        if not isinstance(k, ft.Control) or getattr(k, "visible", True) is False:
            return 0.0
        if isinstance(k, ft.Text):
            if getattr(k, "width", None):
                return k.width
            return max((szerokosc_tekstu(linia, _styl_napisu(k, styl)) for linia in _tresc_napisu(k).split("\n")),
                       default=0.0)
        szer = getattr(k, "width", None)
        if isinstance(k, (ft.Container, ft.Card)):
            margines = _poziomo(getattr(k, "margin", None)) + (KARTA_MARGINES if isinstance(k, ft.Card) else 0)
            if szer is not None:
                return szer + margines
            return self.naturalna(k.content, styl) + _poziomo(getattr(k, "padding", None)) + margines
        if szer is not None:
            return szer
        if isinstance(k, ft.Icon):
            return k.size or 24
        if isinstance(k, ft.IconButton):
            return IKONA_PRZYCISKU_ROZMIAR
        if isinstance(k, POLA_WYBORU):
            etykieta = k.label if isinstance(k.label, str) else ""
            return POLE_WYBORU_KWADRAT[type(k).__name__] + szerokosc_tekstu(etykieta)
        if isinstance(k, (ft.TextField, ft.Dropdown)):
            return POLE_SZEROKOSC_W_KOLUMNIE
        if isinstance(k, ft.ProgressRing):
            return 36
        if isinstance(k, PRZYCISKI):
            return self._przycisk_naturalny(k)
        if isinstance(k, ft.PopupMenuButton):
            return self.naturalna(k.content, styl) if isinstance(k.content, ft.Control) else IKONA_PRZYCISKU_ROZMIAR
        if _jest_wierszem(k):
            widoczne = [d for _, d in _dzieci(k, ("controls",)) if getattr(d, "visible", True) is not False]
            odstep = k.spacing if k.spacing is not None else WIERSZ_ODSTEP_DOMYSLNY
            return sum(self.naturalna(d, styl) for d in widoczne) + odstep * max(0, len(widoczne) - 1)
        if isinstance(k, (ft.ResponsiveRow, ft.ProgressBar, ft.Divider, ft.Image)):
            return 0.0
        if isinstance(k, ft.ListView) and getattr(k, "horizontal", False):
            return 0.0
        dzieci = [d for _, d in _dzieci(k, ("controls", "content"))]
        return max((self.naturalna(d, styl) for d in dzieci), default=0.0) + _poziomo(getattr(k, "padding", None))

    def _przycisk_naturalny(self, k):
        tresc = k.content
        if isinstance(tresc, str):
            w = szerokosc_tekstu(tresc, STYL_PRZYCISKU)
        else:
            w = self.naturalna(tresc, STYL_PRZYCISKU)
        if getattr(k, "icon", None):
            w += PRZYCISK_IKONA
        return max(64.0, w + self._padding_przycisku(k))

    @staticmethod
    def _padding_przycisku(k):
        styl = getattr(k, "style", None)
        padding = getattr(styl, "padding", None) if styl is not None else None
        if padding is not None and not isinstance(padding, dict):
            return _poziomo(padding)
        return PRZYCISK_TEKSTOWY_PADDING if isinstance(k, PRZYCISKI_TEKSTOWE) else PRZYCISK_PADDING

    # ---------------- zejście z szerokością dostępną ----------------

    def zejdz(self, k, szer, przodkowie, styl=STYL_TRESCI, w_kolumnie=False, jedna_linia=False):
        if not isinstance(k, ft.Control) or id(k) in self._odwiedzone:
            return
        self._odwiedzone.add(id(k))
        sciezka = przodkowie + [k]

        if isinstance(k, ft.Text):
            self._napis(k, szer, przodkowie, styl, jedna_linia)
        elif isinstance(k, ft.TextField):
            self._pole(k, szer, przodkowie, w_kolumnie)
        elif isinstance(k, ft.Dropdown):
            self._lista(k, szer, przodkowie)
        elif isinstance(k, POLA_WYBORU):
            self._pole_wyboru(k, szer, przodkowie)
        elif isinstance(k, ft.View):
            self._widok(k, szer, przodkowie)
        elif isinstance(k, ft.AppBar):
            self._pasek_tytulu(k, szer, przodkowie)
        elif isinstance(k, ft.AlertDialog):
            self._okno(k, szer, przodkowie)
        elif isinstance(k, ft.NavigationDrawer):
            for _, d in _dzieci(k, ("controls",)):
                self.zejdz(d, None if szer is None else min(szer - SZUFLADA_ODSTEP, 360), sciezka)
        elif isinstance(k, ft.ResponsiveRow):
            odstep = k.spacing if isinstance(k.spacing, (int, float)) else WIERSZ_ODSTEP_DOMYSLNY
            for _, d in _dzieci(k, ("controls",)):
                udzial = _kolumna_responsywna(d) / 12
                self.zejdz(d, None if szer is None else (szer + odstep) * udzial - odstep, sciezka, styl)
        elif _jest_wierszem(k):
            self._wiersz(k, szer, przodkowie, styl, jedna_linia)
        elif isinstance(k, ft.GridView):
            self._siatka(k, szer, sciezka, styl)
        elif isinstance(k, ft.ListTile):
            self._kafel_listy(k, szer, przodkowie)
        elif isinstance(k, PRZYCISKI):
            wewn = None
            if szer is not None:
                wewn = szer - self._padding_przycisku(k) - (PRZYCISK_IKONA if getattr(k, "icon", None) else 0)
            if isinstance(k.content, ft.Control):
                self.zejdz(k.content, wewn, sciezka, STYL_PRZYCISKU, jedna_linia=jedna_linia)
        elif isinstance(k, ft.PopupMenuButton):
            if isinstance(k.content, ft.Control):
                self.zejdz(k.content, None, sciezka, styl)
        elif isinstance(k, (ft.Container, ft.Card)):
            wewn = szer
            if wewn is not None:
                wewn -= _poziomo(getattr(k, "margin", None)) + (KARTA_MARGINES if isinstance(k, ft.Card) else 0)
            if getattr(k, "width", None) is not None:
                wewn = k.width if wewn is None else min(wewn, k.width)
            if wewn is not None:
                wewn -= _poziomo(getattr(k, "padding", None))
            self.zejdz(k.content, wewn, sciezka, styl, w_kolumnie=w_kolumnie, jedna_linia=jedna_linia)
        elif isinstance(k, ft.ListView):
            wewn = None if (szer is None or k.horizontal) else szer - _poziomo(k.padding)
            for _, d in _dzieci(k, ("controls",)):
                self.zejdz(d, wewn, sciezka, styl)
        elif isinstance(k, ft.Column):
            rozciaga = str(getattr(k.horizontal_alignment, "value", k.horizontal_alignment)).lower() == "stretch"
            if getattr(k, "width", None) is not None:
                szer = k.width if szer is None else min(szer, k.width)
            for _, d in _dzieci(k, ("controls",)):
                self.zejdz(d, szer, sciezka, styl, w_kolumnie=not rozciaga)
        elif isinstance(k, ft.Stack):
            for _, d in _dzieci(k, ("controls",)):
                self.zejdz(d, szer, sciezka, styl)
        else:
            for _, d in _dzieci(k, ("controls", "content")):
                self.zejdz(d, szer, sciezka, styl, w_kolumnie=w_kolumnie, jedna_linia=jedna_linia)

    def _napis(self, napis, szer, przodkowie, styl, jedna_linia):
        tekst = _tresc_napisu(napis)
        if szer is None or not tekst.strip():
            return
        if getattr(napis, "width", None):
            szer = min(szer, napis.width)
        st = _styl_napisu(napis, styl)
        # Pasek tytułu nie zawija tekstu, chyba że ten sam poda `max_lines` > 1.
        if (jedna_linia and not (napis.max_lines or 0) > 1) or napis.no_wrap or napis.max_lines == 1:
            w = max(szerokosc_tekstu(linia, st) for linia in tekst.split("\n"))
            if w > szer + TOLERANCJA_DP:
                self.zglos("tekst", przodkowie, napis,
                           f"„{_skrot(tekst)}” w jednej linii: potrzeba {w:.0f} dp, jest {szer:.0f} dp")
            return
        linie, lamane = linie_tekstu(tekst, szer, st)
        if lamane:
            self.zglos("słowo", przodkowie, napis,
                       f"słowo „{_skrot(lamane, 30)}” łamie się w środku: kolumna ma {szer:.0f} dp")
        elif napis.max_lines and linie > napis.max_lines:
            self.zglos("tekst", przodkowie, napis,
                       f"„{_skrot(tekst)}” potrzebuje {linie} linii, dostaje {napis.max_lines} ({szer:.0f} dp)")

    def _wiersz(self, wiersz, szer, przodkowie, styl, jedna_linia):
        sciezka = przodkowie + [wiersz]
        dzieci = [d for _, d in _dzieci(wiersz, ("controls",))]
        if szer is None or _przewijany(wiersz):
            for d in dzieci:
                self.zejdz(d, None, sciezka, styl, jedna_linia=jedna_linia)
            return
        if wiersz.wrap:
            for d in dzieci:
                w = self.naturalna(d, styl)
                if w > szer + TOLERANCJA_DP and not _elastycznosc(d):
                    self.zglos("wiersz", sciezka, d, f"element szerszy niż linia paska: {w:.0f} dp z {szer:.0f} dp")
                self.zejdz(d, szer, sciezka, styl, jedna_linia=jedna_linia)
            return
        widoczne = [d for d in dzieci if getattr(d, "visible", True) is not False]
        odstep = wiersz.spacing if wiersz.spacing is not None else WIERSZ_ODSTEP_DOMYSLNY
        sztywne = sum(self.naturalna(d, styl) for d in widoczne if not _elastycznosc(d))
        potrzeba = sztywne + odstep * max(0, len(widoczne) - 1)
        if potrzeba > szer + TOLERANCJA_DP:
            napisy = [_skrot(_tresc_napisu(n), 25) for n in _napisy_w(wiersz)][:3]
            self.zglos("wiersz", przodkowie, wiersz,
                       f"wiersz potrzebuje {potrzeba:.0f} dp, ma {szer:.0f} dp — {' | '.join(napisy)}")
        suma_flex = sum(_elastycznosc(d) for d in widoczne) or 1
        reszta = max(0.0, szer - potrzeba)
        for d in dzieci:
            flex = _elastycznosc(d)
            self.zejdz(d, reszta * flex / suma_flex if flex else None, sciezka, styl, jedna_linia=jedna_linia)

    def _siatka(self, siatka, szer, sciezka, styl):
        dzieci = [d for _, d in _dzieci(siatka, ("controls",))]
        if szer is None or getattr(siatka, "horizontal", False):
            for d in dzieci:
                self.zejdz(d, None, sciezka, styl)
            return
        szer -= _poziomo(getattr(siatka, "padding", None))
        odstep = getattr(siatka, "spacing", None) or 0
        if getattr(siatka, "runs_count", None):
            n = siatka.runs_count
        else:
            n = max(1, -(-int(szer) // int((siatka.max_extent or szer) + odstep)))
        for d in dzieci:
            self.zejdz(d, (szer - odstep * (n - 1)) / n, sciezka, styl)

    def _kafel_listy(self, kafel, szer, przodkowie):
        sciezka = przodkowie + [kafel]
        if szer is not None:
            szer -= _poziomo(kafel.content_padding) if kafel.content_padding is not None else 40
            odstep = kafel.horizontal_spacing if kafel.horizontal_spacing is not None else 16
            for boczny in (kafel.leading, kafel.trailing):
                if isinstance(boczny, ft.Control):
                    szer -= max(self.naturalna(boczny), 24) + odstep
        for pole, styl in (("title", STYL_POLA), ("subtitle", STYL_TRESCI)):
            wartosc = getattr(kafel, pole, None)
            if isinstance(wartosc, ft.Control):
                self.zejdz(wartosc, szer, sciezka, styl)

    def _pasek_tytulu(self, pasek, szer, przodkowie):
        if szer is None or not isinstance(pasek.title, ft.Control):
            return
        akcje = [a for a in (pasek.actions or []) if getattr(a, "visible", True) is not False]
        lewa = (pasek.leading_width or 56) + 16 if (pasek.leading or pasek.automatically_imply_leading) else 16
        prawa = sum(max(self.naturalna(a), IKONA_PRZYCISKU_ROZMIAR) for a in akcje) or 16
        self.zejdz(pasek.title, szer - lewa - prawa, przodkowie + [pasek], STYL_TYTULU_PASKA, jedna_linia=True)

    def _okno(self, okno, szer, przodkowie):
        sciezka = przodkowie + [okno]
        szerokosc = min(szer - OKNO_MARGINES, 560) if szer is not None else None
        for pole, padding, styl in (("title", okno.title_padding, STYL_TYTULU_OKNA),
                                    ("content", okno.content_padding, STYL_TRESCI)):
            wartosc = getattr(okno, pole, None)
            if isinstance(wartosc, ft.Control):
                odstep = _poziomo(padding) if padding is not None else OKNO_PADDING
                self.zejdz(wartosc, None if szerokosc is None else szerokosc - odstep, sciezka, styl)

    def _widok(self, widok, szer, przodkowie):
        sciezka = przodkowie + [widok]
        if isinstance(getattr(widok, "drawer", None), ft.Control):
            self.zejdz(widok.drawer, szer, sciezka)
        if isinstance(widok.appbar, ft.Control):
            self.zejdz(widok.appbar, szer, sciezka)
        wewn = szer - _poziomo(widok.padding)
        for _, d in _dzieci(widok, ("controls",)):
            self.zejdz(d, wewn, sciezka, w_kolumnie=True)
        pasek = getattr(widok, "navigation_bar", None)
        cele = getattr(pasek, "destinations", None) or []
        for cel in cele:
            etykieta = getattr(cel, "label", None)
            if isinstance(etykieta, str) and szerokosc_tekstu(etykieta, STYL_PODPISU_NAWIGACJI) > szer / len(cele) - 8:
                self.zglos("tekst", sciezka, cel, f"podpis zakładki „{etykieta}” nie mieści się w {szer / len(cele):.0f} dp")

    # ---------------- pola formularzy ----------------

    def _szerokosc_pola(self, pole, szer, w_kolumnie):
        if getattr(pole, "width", None):
            return pole.width if szer is None else min(szer, pole.width)
        if szer is None:
            return POLE_SZEROKOSC_W_KOLUMNIE
        if w_kolumnie and isinstance(pole, ft.TextField):
            return min(szer, POLE_SZEROKOSC_W_KOLUMNIE)
        return szer

    def _pole(self, pole, szer, przodkowie, w_kolumnie):
        szerokosc = self._szerokosc_pola(pole, szer, w_kolumnie)
        padding = _poziomo(pole.content_padding) if pole.content_padding is not None else POLE_PADDING_DOMYSLNY
        lewa = padding / 2
        prawa = padding / 2
        if pole.prefix_icon is not None or pole.icon is not None:
            lewa = POLE_IKONA_PRZEDROSTKA
        if pole.suffix_icon is not None or isinstance(pole.suffix, ft.Control):
            prawa = POLE_IKONA_ZA
        miejsce = szerokosc - lewa - prawa
        etykieta = pole.label if isinstance(pole.label, str) else None
        if etykieta and szerokosc_tekstu(etykieta, STYL_POLA) > miejsce + TOLERANCJA_DP:
            self.zglos("etykieta", przodkowie, pole,
                       f"etykieta „{_skrot(etykieta)}” zawija się w pustym polu: "
                       f"{szerokosc_tekstu(etykieta, STYL_POLA):.0f} dp w {miejsce:.0f} dp")
        # Przedrostek i przyrostek widać dopiero przy pisaniu — razem z podpowiedzią.
        for tekst_obok in (pole.prefix, pole.suffix):
            if isinstance(tekst_obok, str):
                miejsce -= szerokosc_tekstu(tekst_obok, STYL_POLA) + 4
        if pole.hint_text and not pole.multiline and szerokosc_tekstu(pole.hint_text, STYL_POLA) > miejsce + TOLERANCJA_DP:
            self.zglos("podpowiedź", przodkowie, pole,
                       f"podpowiedź „{_skrot(pole.hint_text)}” ucięta: "
                       f"{szerokosc_tekstu(pole.hint_text, STYL_POLA):.0f} dp w {miejsce:.0f} dp")

    def _lista(self, lista, szer, przodkowie):
        teksty = [o.text or o.key for o in (lista.options or [])
                  if isinstance(getattr(o, "text", None) or getattr(o, "key", None), str)]
        styl = ((lista.text_size or STYL_POLA[0]), 400, STYL_POLA[2])
        najdluzszy = max(teksty, key=lambda t: szerokosc_tekstu(t, styl), default="")
        etykieta = lista.label if isinstance(lista.label, str) else ""
        ikona = POLE_IKONA_PRZEDROSTKA if lista.leading_icon else 0
        # Bez `width` i `expand` Flutter mierzy listę po najdłuższej opcji w 14 dp
        # (i po etykiecie), choć pole pisze `text_size` — dłuższa opcja wychodzi pod strzałkę.
        if getattr(lista, "width", None):
            szerokosc = lista.width
        elif _elastycznosc(lista) and szer is not None:
            szerokosc = szer
        else:
            szerokosc = max(max((szerokosc_tekstu(t) for t in teksty), default=0) + LISTA_DOPELNIENIE_OPCJI,
                            szerokosc_tekstu(etykieta, STYL_ETYKIETY_UNIESIONEJ) + LISTA_DOPELNIENIE_ETYKIETY) + ikona
        if szer is not None:
            szerokosc = min(szerokosc, szer)
        miejsce = szerokosc - LISTA_POZA_TEKSTEM - ikona
        if najdluzszy and szerokosc_tekstu(najdluzszy, styl) > miejsce + TOLERANCJA_DP:
            self.zglos("opcja", przodkowie, lista,
                       f"opcja „{_skrot(najdluzszy)}” ucięta: {szerokosc_tekstu(najdluzszy, styl):.0f} dp w {miejsce:.0f} dp")
        padding = _poziomo(lista.content_padding) if lista.content_padding is not None else POLE_PADDING_DOMYSLNY
        if etykieta and szerokosc_tekstu(etykieta, STYL_ETYKIETY_UNIESIONEJ) > szerokosc - padding + TOLERANCJA_DP:
            self.zglos("etykieta", przodkowie, lista,
                       f"etykieta listy „{_skrot(etykieta)}” łamie się nad polem: "
                       f"{szerokosc_tekstu(etykieta, STYL_ETYKIETY_UNIESIONEJ):.0f} dp w {szerokosc - padding:.0f} dp")

    def _pole_wyboru(self, pole, szer, przodkowie):
        if szer is None or not isinstance(pole.label, str) or not pole.label:
            return
        potrzeba = POLE_WYBORU_KWADRAT[type(pole).__name__] + szerokosc_tekstu(pole.label)
        if potrzeba > szer + TOLERANCJA_DP:
            self.zglos("pole wyboru", przodkowie, pole,
                       f"etykieta „{_skrot(pole.label)}” ucięta (Flet jej nie zawija): {potrzeba:.0f} dp w {szer:.0f} dp")


def _napisy_w(kontrolka, limit=50):
    """Napisy (ft.Text) w poddrzewie — do opisu zgłoszenia."""
    wynik, kolejka = [], [kontrolka]
    while kolejka and len(wynik) < limit:
        k = kolejka.pop(0)
        if isinstance(k, ft.Text) and _tresc_napisu(k).strip():
            wynik.append(k)
        kolejka.extend(d for _, d in _dzieci(k))
    return wynik


def znajdz_uciete_napisy(korzen, szerokosc=SZEROKOSC_TELEFONU):
    """Lista {'rodzaj', 'sciezka', 'opis'} — napisy, które na telefonie o danej
    szerokości zostaną ucięte, złamane w środku słowa albo wyjdą poza wiersz."""
    audyt = _AudytNapisow(szerokosc)
    audyt.zejdz(korzen, szerokosc, [])
    return audyt.znaleziska


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

    print("\n== Audyt pogrubień na drugim planie ==")
    for z in audyt_pogrubien():
        print(f"  {z['plik']}:{z['linia']} — {z['opis']}")

    print("\n== Audyt palety statusów ==")
    for z in audyt_palety_statusow():
        print(f"  {z['plik']}:{z['linia']} — {z['opis']}")

    print("\n== Audyt porzuconych korutyn Fleta ==")
    print(f"  pilnowane metody: {', '.join(sorted(nazwy_metod_async_fleta()))}")
    for z in audyt_porzuconych_korutyn():
        print(f"  {z['plik']}:{z['linia']} — {z['opis']}")

    print("\nAudyty drzewa kontrolek (expand, chipy, powierzchnie, ucięte napisy) uruchamia pytest:")
    print("  python -m pytest tests/test_audyty.py tests/test_powierzchnie.py -q")
