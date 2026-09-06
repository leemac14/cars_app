"""Warstwa wspólnych elementów interfejsu — wszystko, czego używa więcej niż
jeden ekran.

Pakiet powstał z rozbicia jednego pliku utils.py. Moduły idą od najmniej
zależnych (`stale`, `format`) do tych, które składają się z pozostałych
(`nawigacja`). Cały interfejs jest re-eksportowany tutaj, więc `import utils`
i `utils.cokolwiek(...)` działa jak dawniej.
"""

# Ten plik istnieje po to, żeby scalić moduły pakietu w jedną przestrzeń nazw —
# gwiazdki i „nieużywane” importy są tu zamierzone.
# ruff: noqa: F401, F403

from .stale import *
from .format import *
from .wyglad import *
from .zgodnosc import *
from .dialogi import *
from .listy import *
from .filtry import *
from .sync_ui import *
from .formularze import *
from .notatki import *
from .zalaczniki import *
from .wykresy import *
from .pojazd import *
from .system import *
from .komponenty import *
from .powiadomienia import *
from .nawigacja import *
from .zaznaczanie import *

from . import (
    stale,
    format,
    wyglad,
    zgodnosc,
    dialogi,
    listy,
    filtry,
    sync_ui,
    formularze,
    notatki,
    zalaczniki,
    wykresy,
    pojazd,
    system,
    komponenty,
    powiadomienia,
    nawigacja,
    zaznaczanie,
)
