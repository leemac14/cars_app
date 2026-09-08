"""Rotujący log błędów — jedyne miejsce, w którym aplikacja zapisuje, co jej nie wyszło.

`except Exception: pass` występuje w tym projekcie kilkadziesiąt razy i zwykle
słusznie: kontrolki nie ma jeszcze w drzewie strony, panel nie zdążył się
odświeżyć, starsza wersja Fleta nie zna zdarzenia. Cena jest jednak stała —
zgłoszone przez drugą osobę „u mnie nie działa" jest nie do zdiagnozowania, bo
po błędzie nie zostaje żaden ślad. Ten moduł zamienia zgłoszenie w informację.

DLACZEGO W KORZENIU, A NIE W `utils/`
-------------------------------------
Pisze tu KAŻDA warstwa: `db` (które celowo nie zna Fleta), `sync`, `utils`
i widoki. Moduł w `utils/` zmusiłby warstwę danych do zaimportowania warstwy
interfejsu — czyli do zbudowania dokładnie tego cyklu, którego zabrania
`claude/struktura-projektu-pakiety.md`. Stąd `log.py` obok `date.py` i
`state.py`, z zależnościami wyłącznie z biblioteki standardowej.

CO TRAFIA DO PLIKU
------------------
* wyjątki nieobsłużone (`sys.excepthook`), także z wątków i z `__del__`;
* wszystko, co biblioteki zgłaszają przez `logging` od poziomu WARNING w górę —
  w tym „Task exception was never retrieved" z asyncio, czyli błąd korutyny
  puszczonej przez `page.run_task`, który dziś nie zostawia po sobie nic;
* wyjątki połknięte świadomie — tam, gdzie zamiast `pass` woła się
  `log.polkniety("opis")`;
* okruszki: start aplikacji i każda zmiana ekranu. Bez nich wiadomo CO padło,
  ale nie wiadomo, co użytkownik wtedy robił.

Czego w pliku NIE MA: VIN-ów, numerów polis, telefonów ani kwot. Log trzyma
komunikaty błędów i nazwy ekranów, bo ma się nadawać do wysłania obcej osobie.

DIAGNOSTYKA NIE MA PRAWA WYWALIĆ APLIKACJI
------------------------------------------
Każdy krok jest zabezpieczony osobno. Brak prawa zapisu na katalog danych
znaczy „aplikacja działa bez logu", a nie „aplikacja się nie uruchamia".
"""

import logging
import logging.handlers
import os
import re
import sys
import threading
from datetime import datetime


# Ścieżkę liczymy z tej samej zmiennej co `db/stale.py`, więc log siada obok
# bazy — również na Androidzie, gdzie katalog danych wskazuje Flet.
STORAGE_PATH = os.environ.get("FLET_APP_STORAGE_DATA", "")

PLIK_LOGU = os.path.join(STORAGE_PATH, "flota.log")

# 256 kB razy trzy pliki to około pół megabajta na dysku i kilka tysięcy
# wpisów — dość, żeby sięgnąć kilka dni wstecz, za mało, żeby cokolwiek zająć.
ROZMIAR_PLIKU = 256 * 1024

LICZBA_KOPII = 2

NAZWA_LOGGERA = "flota"

FORMAT = "%(asctime)s  %(levelname)-7s %(message)s"

FORMAT_CZASU = "%Y-%m-%d %H:%M:%S"

# Wpis zaczyna się od znacznika czasu; wiersze śladu wyjątku — nie. Po tym
# rozróżnieniu liczy się wpisy i wyszukuje ostatni błąd.
WZORZEC_WPISU = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+(\w+)\s+(.*)$")

POZIOMY_BLEDU = ("ERROR", "CRITICAL")


_logger = logging.getLogger(NAZWA_LOGGERA)

_uchwyt = None

_haki_zalozone = False


class _FiltrPoziomow(logging.Filter):
    """Nasze wpisy od INFO w górę, cudze dopiero od WARNING.

    Bez tego wystarczyłoby, żeby ktoś podkręcił logowanie Fleta albo httpx na
    DEBUG, a plik zapełniłby się ruchem sieciowym — i wypchnął z rotacji jedyny
    wpis, dla którego log w ogóle powstał."""

    def filter(self, record):
        nasz = record.name == NAZWA_LOGGERA or record.name.startswith(NAZWA_LOGGERA + ".")
        return record.levelno >= (logging.INFO if nasz else logging.WARNING)


# ============================================================================
#  WŁĄCZENIE
# ============================================================================

def wlacz():
    """Zakłada plik logu i podpina haki wyjątków. Wołane raz, na starcie `main()`.

    Zwraca True, jeśli log faktycznie pisze. Powtórne wywołanie nic nie psuje —
    uchwyt i haki zakładają się tylko za pierwszym razem."""
    global _uchwyt

    if _uchwyt is None:
        try:
            folder = os.path.dirname(PLIK_LOGU)
            if folder:
                os.makedirs(folder, exist_ok=True)

            uchwyt = logging.handlers.RotatingFileHandler(
                PLIK_LOGU,
                maxBytes=ROZMIAR_PLIKU,
                backupCount=LICZBA_KOPII,
                encoding="utf-8",
                delay=True,
            )
            uchwyt.setLevel(logging.INFO)
            uchwyt.setFormatter(logging.Formatter(FORMAT, FORMAT_CZASU))
            uchwyt.addFilter(_FiltrPoziomow())

            _logger.setLevel(logging.INFO)
            # propagate=False, bo TEN SAM uchwyt wisi też na loggerze głównym —
            # bez tego każdy nasz wpis wylądowałby w pliku dwa razy.
            _logger.propagate = False
            _logger.addHandler(uchwyt)

            # Logger główny łapie cudze błędy: asyncio („Task exception was never
            # retrieved"), Fleta, httpx. Poziomu głównego NIE ruszamy — domyślne
            # WARNING jest dokładnie tym, czego chcemy.
            logging.getLogger().addHandler(uchwyt)

            _uchwyt = uchwyt
        except Exception:
            return False

    _zaloz_haki()
    return True


def czy_wlaczony():
    return _uchwyt is not None


def _zaloz_haki():
    """Trzy haki na wyjątki, których nikt nie złapał. Każdy woła poprzednika,
    żeby zachowanie Pythona (ślad na konsoli) zostało bez zmian."""
    global _haki_zalozone
    if _haki_zalozone:
        return

    poprzedni_glowny = sys.excepthook

    def _hak_glowny(typ, wartosc, slad):
        _zapisz("Nieobsłużony wyjątek", logging.ERROR, (typ, wartosc, slad))
        poprzedni_glowny(typ, wartosc, slad)

    sys.excepthook = _hak_glowny

    poprzedni_watku = getattr(threading, "excepthook", None)
    if poprzedni_watku is not None:
        def _hak_watku(args):
            nazwa = getattr(getattr(args, "thread", None), "name", "?")
            _zapisz(f"Nieobsłużony wyjątek w wątku {nazwa}", logging.ERROR,
                    (args.exc_type, args.exc_value, args.exc_traceback))
            poprzedni_watku(args)

        threading.excepthook = _hak_watku

    poprzedni_niezglaszalny = getattr(sys, "unraisablehook", None)
    if poprzedni_niezglaszalny is not None:
        def _hak_niezglaszalny(args):
            # Wyjątki z `__del__` i z finalizatorów — Python nie ma ich komu
            # zgłosić, więc bez tego haka giną całkowicie.
            _zapisz(f"Błąd nie do zgłoszenia: {getattr(args, 'err_msg', '') or ''}".strip(),
                    logging.WARNING,
                    (args.exc_type, args.exc_value, args.exc_traceback))
            poprzedni_niezglaszalny(args)

        sys.unraisablehook = _hak_niezglaszalny

    _haki_zalozone = True


# ============================================================================
#  PISANIE
# ============================================================================

def _zapisz(wiadomosc, poziom=logging.INFO, wyjatek=None):
    try:
        _logger.log(poziom, str(wiadomosc), exc_info=wyjatek)
    except Exception:
        pass  # log, który wywala aplikację, jest gorszy od braku logu


def zapisz(wiadomosc):
    """Okruszek: start aplikacji, zmiana ekranu, wczytanie kopii. Bez śladu
    wyjątku — to nie jest błąd, tylko kontekst dla błędu, który dopiero będzie."""
    _zapisz(wiadomosc, logging.INFO)


def ostrzezenie(wiadomosc):
    _zapisz(wiadomosc, logging.WARNING)


def blad(wiadomosc, wyjatek=None):
    """Błąd wraz ze śladem stosu. Wołane z bloku `except` bierze ślad bieżącego
    wyjątku; poza nim można podać wyjątek wprost."""
    if wyjatek is None:
        wyjatek = sys.exc_info()[0] is not None
    _zapisz(wiadomosc, logging.ERROR, wyjatek)


def polkniety(kontekst):
    """Wpis w miejscu, w którym aplikacja ŚWIADOMIE idzie dalej mimo błędu.

    Zamiennik dla `except Exception: pass`. Zachowanie programu się nie zmienia —
    zmienia się tylko to, że da się potem powiedzieć, co zostało połknięte.
    Poziom WARNING, nie ERROR: to nie jest awaria, to jest ślad."""
    typ, wartosc, _ = sys.exc_info()
    if typ is None:
        _zapisz(f"{kontekst}: nie powiodło się", logging.WARNING)
        return
    _zapisz(f"{kontekst}: {typ.__name__}: {wartosc}", logging.WARNING, True)


# ============================================================================
#  CZYTANIE
# ============================================================================

def sciezki_logu():
    """Istniejące pliki logu, od najstarszego do najnowszego."""
    kandydaci = [f"{PLIK_LOGU}.{i}" for i in range(LICZBA_KOPII, 0, -1)] + [PLIK_LOGU]
    return [s for s in kandydaci if os.path.exists(s)]


def rozmiar():
    suma = 0
    for sciezka in sciezki_logu():
        try:
            suma += os.path.getsize(sciezka)
        except OSError:
            pass
    return suma


def tresc():
    """Cały log jako jeden tekst, najstarsze wpisy na górze."""
    czesci = []
    for sciezka in sciezki_logu():
        try:
            with open(sciezka, "r", encoding="utf-8", errors="replace") as f:
                czesci.append(f.read())
        except OSError:
            pass
    return "".join(czesci)


def ostatnie_linie(ile=150):
    linie = tresc().splitlines()
    return "\n".join(linie[-ile:])


def podsumowanie():
    """Liczby na kartę w Ustawieniach: ile wpisów, ile błędów, kiedy ostatni.

    Ostatni błąd jest tu najważniejszy — to jedyna rzecz, którą warto pokazać
    zanim ktokolwiek otworzy podgląd."""
    wpisy = bledy = ostrzezenia = 0
    ostatni_blad = None

    for linia in tresc().splitlines():
        dopasowanie = WZORZEC_WPISU.match(linia)
        if not dopasowanie:
            continue
        czas, poziom, wiadomosc = dopasowanie.groups()
        wpisy += 1
        if poziom in POZIOMY_BLEDU:
            bledy += 1
            ostatni_blad = (czas, wiadomosc)
        elif poziom == "WARNING":
            ostrzezenia += 1

    return {
        "rozmiar": rozmiar(),
        "pliki": len(sciezki_logu()),
        "wpisy": wpisy,
        "bledy": bledy,
        "ostrzezenia": ostrzezenia,
        "ostatni_blad": ostatni_blad,
    }


def wyczysc():
    """Kasuje log razem z plikami z rotacji. Zwraca liczbę skasowanych plików.

    Strumień zamykamy na chwilę, bo skasowanie pliku otwartego do zapisu na
    Windowsie po prostu się nie udaje. `delay=True` otworzy go z powrotem przy
    następnym wpisie, więc nie trzeba niczego przestawiać."""
    if _uchwyt is not None:
        try:
            _uchwyt.acquire()
            try:
                if _uchwyt.stream is not None:
                    _uchwyt.stream.close()
                    _uchwyt.stream = None
            finally:
                _uchwyt.release()
        except Exception:
            pass

    usuniete = 0
    for sciezka in sciezki_logu():
        try:
            os.remove(sciezka)
            usuniete += 1
        except OSError:
            pass
    return usuniete


# ============================================================================
#  RAPORT DO WYSŁANIA
# ============================================================================

def formatuj_rozmiar(bajty):
    if bajty < 1024:
        return f"{bajty} B"
    if bajty < 1024 * 1024:
        return f"{bajty / 1024:.1f} kB".replace(".", ",")
    return f"{bajty / (1024 * 1024):.1f} MB".replace(".", ",")


def odmien(liczba, jeden, dwa, wiele):
    """Polska odmiana przez liczbę: 1 wpis, 2 wpisy, 5 wpisów.

    Własna, choć drobna: `utils/format.py` jest po drugiej stronie granicy,
    której ten moduł świadomie nie przekracza."""
    liczba = abs(int(liczba))
    if liczba == 1:
        return jeden
    if 2 <= liczba % 10 <= 4 and not 12 <= liczba % 100 <= 14:
        return dwa
    return wiele


def nazwa_pliku_raportu(teraz=None):
    teraz = teraz or datetime.now()
    return f"log_flota_{teraz.strftime('%Y-%m-%d_%H%M')}.txt"


def zbierz_raport(dodatkowe=None):
    """Nagłówek diagnostyczny plus cała treść logu — to, co wychodzi z „Wyślij log".

    `dodatkowe` to słownik etykieta → wartość, dokładany przez wołającego:
    ten moduł nie zna ani Fleta, ani bazy, a wersja Fleta i wersja schematu są
    pierwszą rzeczą, o którą trzeba by dopytywać przy każdym zgłoszeniu."""
    dane = podsumowanie()

    wiersze = {
        "Zebrano": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Python": sys.version.split()[0],
        "System": sys.platform,
    }
    wiersze.update(dodatkowe or {})
    wiersze["Log"] = (
        f"{formatuj_rozmiar(dane['rozmiar'])} w {dane['pliki']} "
        f"{odmien(dane['pliki'], 'pliku', 'plikach', 'plikach')}, "
        f"{dane['wpisy']} {odmien(dane['wpisy'], 'wpis', 'wpisy', 'wpisów')} "
        f"(błędy: {dane['bledy']}, ostrzeżenia: {dane['ostrzezenia']})"
    )

    szerokosc = max((len(k) for k in wiersze), default=0) + 2
    naglowek = [
        "=" * 72,
        " Flota Mobile — log diagnostyczny",
        "=" * 72,
    ]
    naglowek += [f"{k + ':':<{szerokosc}}{w}" for k, w in wiersze.items()]
    naglowek += [
        "",
        "W logu nie ma VIN-ów, numerów polis, telefonów ani kwot — wyłącznie",
        "komunikaty błędów i nazwy otwieranych ekranów.",
        "-" * 72,
        "",
    ]

    return "\n".join(naglowek) + (tresc() or "(log jest pusty)\n")


__all__ = [
    "FORMAT",
    "FORMAT_CZASU",
    "LICZBA_KOPII",
    "NAZWA_LOGGERA",
    "PLIK_LOGU",
    "POZIOMY_BLEDU",
    "ROZMIAR_PLIKU",
    "STORAGE_PATH",
    "WZORZEC_WPISU",
    "blad",
    "czy_wlaczony",
    "formatuj_rozmiar",
    "odmien",
    "nazwa_pliku_raportu",
    "ostatnie_linie",
    "ostrzezenie",
    "podsumowanie",
    "polkniety",
    "rozmiar",
    "sciezki_logu",
    "tresc",
    "wlacz",
    "wyczysc",
    "zapisz",
    "zbierz_raport",
]
