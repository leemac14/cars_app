"""Warstwa danych aplikacji — baza SQLite, logika domenowa, eksport i import.

Pakiet powstał z rozbicia jednego pliku db.py. Moduły są ułożone od najmniej
zależnych do najbardziej: `stale` i `polaczenie` nie zależą od niczego,
`migracje` (init_db) na końcu, bo dotyka wszystkiego. Cały interfejs jest
re-eksportowany tutaj, więc `import db` i `db.cokolwiek(...)` działa jak dawniej.
"""

# Ten plik istnieje po to, żeby scalić moduły pakietu w jedną przestrzeń nazw —
# gwiazdki i „nieużywane” importy są tu zamierzone.
# ruff: noqa: F401, F403

from .stale import *
from .polaczenie import *
from .pomocnicze import *
from .ustawienia import *
from .synchronizacja import *
from .energia import *
from .notatki import *
from .zalaczniki import *
from .magazyn import *
from .checklisty import *
from .przebieg import *
from .koszty import *
from .powiadomienia import *
from .statystyki import *
from .pojazd import *
from .analiza import *
from .nazwy import *
from .tagi import *
from .rejestry import *
from .wizyty import *
from .usuwanie import *
from .kosz import *
from .nawigacja import *
from .wyszukiwanie import *
from .os_czasu import *
from .eksport import *
from .raporty import *
from .import_csv import *
from .migracje import *

from . import (
    stale,
    polaczenie,
    pomocnicze,
    ustawienia,
    synchronizacja,
    energia,
    notatki,
    zalaczniki,
    magazyn,
    checklisty,
    przebieg,
    koszty,
    powiadomienia,
    statystyki,
    pojazd,
    analiza,
    nazwy,
    tagi,
    rejestry,
    wizyty,
    usuwanie,
    kosz,
    nawigacja,
    wyszukiwanie,
    os_czasu,
    eksport,
    raporty,
    import_csv,
    migracje,
)

# Widok eksportu pyta wprost `db.FPDF is not None`, żeby wiedzieć, czy
# generowanie PDF jest w ogóle dostępne — nazwa musi więc zostać na wierzchu.
from .raporty import FPDF
