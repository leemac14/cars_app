"""Wspólne przygotowanie dla wszystkich testów.

Dwie rzeczy dzieją się TU i nigdzie indziej:

1. `FLET_APP_STORAGE_DATA` ustawiane jest PRZED pierwszym `import db`. Ścieżka
   bazy (`db.stale.BAZA_DANYCH`) liczy się w chwili importu modułu, więc
   ustawienie zmiennej później nie miałoby już żadnego skutku — testy pisałyby
   po prawdziwej `flota_zadania.db` obok repozytorium.

2. Fixture `magazyn` przestawia ścieżki na katalog testu. Nie wystarczy podmienić
   `db.stale`: moduły robią `from .stale import BAZA_DANYCH`, więc każdy ma
   WŁASNĄ kopię wartości z chwili importu. Dlatego podmiana leci po wszystkich
   załadowanych modułach aplikacji — dzięki temu nowy moduł, który jutro zaimportuje
   FOLDER_KOSZ, jest obsłużony bez dopisywania czegokolwiek tutaj.
"""

import os
import pathlib
import shutil
import sys
import tempfile

import pytest

KATALOG_TESTOW = pathlib.Path(__file__).resolve().parent
KORZEN_PROJEKTU = KATALOG_TESTOW.parent

if str(KORZEN_PROJEKTU) not in sys.path:
    sys.path.insert(0, str(KORZEN_PROJEKTU))

# MUSI być przed importem db — patrz punkt 1 w docstringu.
os.environ["FLET_APP_STORAGE_DATA"] = tempfile.mkdtemp(prefix="cars_app_testy_")

import db  # noqa: E402


# Nazwy stałych opisujących miejsce na dysku. Każda z nich bywa importowana
# wprost (`from .stale import FOLDER_KOSZ`), więc podmieniamy je wszędzie.
STALE_SCIEZEK = (
    "STORAGE_PATH",
    "BAZA_DANYCH",
    "FOLDER_ZALACZNIKI",
    "FOLDER_ODROCZONE",
    "FOLDER_KOSZ",
    "PLIK_LOGU",
)

# Pakiety aplikacji, w których takie stałe mogą siedzieć.
PRZEDROSTKI_MODULOW = ("db", "utils", "views", "sync", "main", "state", "log")


def _moduly_aplikacji():
    for nazwa, modul in list(sys.modules.items()):
        korzen = nazwa.split(".")[0]
        if korzen in PRZEDROSTKI_MODULOW and modul is not None:
            yield modul


@pytest.fixture
def magazyn(tmp_path, monkeypatch):
    """Pusty katalog danych na wyłączność testu: baza, załączniki, kosz.

    Zwraca `pathlib.Path` do katalogu. Baza jeszcze nie istnieje — zakłada ją
    dopiero `init_db()` (fixture `baza` albo test migracji, który robi to sam)."""
    katalog = tmp_path / "dane"
    katalog.mkdir()

    wartosci = {
        "STORAGE_PATH": str(katalog),
        "BAZA_DANYCH": str(katalog / "flota_zadania.db"),
        "FOLDER_ZALACZNIKI": str(katalog / "zalaczniki"),
        "FOLDER_ODROCZONE": str(katalog / "zalaczniki_odroczone"),
        "FOLDER_KOSZ": str(katalog / "kosz_zalaczniki"),
        "PLIK_LOGU": str(katalog / "flota.log"),
    }

    monkeypatch.setenv("FLET_APP_STORAGE_DATA", str(katalog))
    for modul in _moduly_aplikacji():
        for nazwa, wartosc in wartosci.items():
            if hasattr(modul, nazwa):
                monkeypatch.setattr(modul, nazwa, wartosc, raising=False)

    for podkatalog in ("zalaczniki", "zalaczniki_odroczone", "kosz_zalaczniki"):
        (katalog / podkatalog).mkdir()

    return katalog


@pytest.fixture(scope="session")
def wzorzec_bazy(tmp_path_factory):
    """Jedna zmigrowana baza na całą sesję, kopiowana potem do każdego testu.

    `init_db()` to czterdzieści bloków SQL — 50 ms razy kilkaset testów robi
    połowę czasu całego przebiegu. Kopia pliku kosztuje ułamek milisekundy
    i daje dokładnie tę samą, w pełni odizolowaną bazę. Drabinkę migracji
    sprawdza test_migracje.py, który zakłada bazy od zera."""
    sciezka = tmp_path_factory.mktemp("wzorzec") / "wzorzec.db"
    poprzednia = db.polaczenie.BAZA_DANYCH
    db.polaczenie.BAZA_DANYCH = str(sciezka)
    try:
        db.init_db()
    finally:
        db.polaczenie.BAZA_DANYCH = poprzednia
    return sciezka


@pytest.fixture
def baza(magazyn, wzorzec_bazy):
    """Świeża, w pełni zmigrowana baza w katalogu testu."""
    shutil.copyfile(wzorzec_bazy, db.BAZA_DANYCH)
    return magazyn


@pytest.fixture(scope="session")
def schemat_wzorcowy(wzorzec_bazy):
    """Schemat świeżej, w pełni zmigrowanej bazy — punkt odniesienia dla testów
    drabinki i próbek. Liczony raz na sesję: inaczej każdy z osiemdziesięciu
    przypadków budowałby własną bazę wzorcową."""
    import pomoce

    poprzednia = db.polaczenie.BAZA_DANYCH
    db.polaczenie.BAZA_DANYCH = str(wzorzec_bazy)
    try:
        return pomoce.zrzut_schematu()
    finally:
        db.polaczenie.BAZA_DANYCH = poprzednia


@pytest.fixture(autouse=True)
def bez_sieci(monkeypatch):
    """Żaden test nie ma prawa dobić do Supabase.

    Bez tego pojedyncza pomyłka (widok, który przy budowie woła synchronizację)
    zamienia się w test wiszący na timeoucie sieciowym zamiast w czytelny błąd.

    Podmiana leci po WSZYSTKICH modułach — z tego samego powodu, co w `magazyn`.
    Po rozbiciu sync.py na pakiet `sync/przywracanie.py` i `sync/przebieg.py`
    mają własne wiązanie `_upewnij_sesje` (z `from .polaczenie import ...`),
    więc podmiana samego `sync._upewnij_sesje` przestałaby cokolwiek blokować —
    i to bez żadnego czerwonego testu, bo blokada milczy dopóki działa.
    Pilnuje tego `test_sync_pakiet.py::test_zakaz_sieci_siega_do_kazdego_modulu`."""
    import sync  # noqa: F401  (musi być zaimportowany, żeby wejść na listę)

    def _zabroniony(*_a, **_k):
        raise AssertionError(
            "Test spróbował połączyć się z Supabase — to nigdy nie powinno się "
            "zdarzyć przy pojeździe, który nie jest współdzielony."
        )

    for modul in _moduly_aplikacji():
        for nazwa in ("_pobierz_klient", "_upewnij_sesje"):
            if hasattr(modul, nazwa):
                monkeypatch.setattr(modul, nazwa, _zabroniony)
