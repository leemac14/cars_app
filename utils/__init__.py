"""Wspólne elementy interfejsu. Moduły od `stale`, `format` do `nawigacja`; całość
re-eksportowana, więc działa `utils.cokolwiek(...)`."""

# Ten plik istnieje po to, żeby scalić moduły pakietu w jedną przestrzeń nazw —
# gwiazdki i „nieużywane” importy są tu zamierzone.
# ruff: noqa: F401, F403

from .stale import *
from .format import *
from .kod_qr import *
from .typografia import *
from .animacje import *
from .wyglad import *
from .szkielet import *
from .pozycja import *
from .miesiace import *
from .zgodnosc import *
from .dialogi import *
from .listy import *
from .filtry import *
from .sync_ui import *
from .formularze import *
from .magazyn import *
from .koszt_naprawy import *
from .gwarancja import *
from .notatki import *
from .zalaczniki import *
from .wykresy import *
from .pojazd import *
from .start import *
from .system import *
from .komponenty import *
from .warsztaty import *
from .ceny_czesci import *
from .szkice import *
from .kopie import *
from .plik_pojazdu import *
from .zaproszenia import *
from .powiadomienia import *
from .przyszlosc import *
from .nawigacja import *
from .zaznaczanie import *

from . import (
    stale,
    format,
    kod_qr,
    typografia,
    animacje,
    wyglad,
    szkielet,
    pozycja,
    miesiace,
    zgodnosc,
    dialogi,
    listy,
    filtry,
    sync_ui,
    formularze,
    magazyn,
    koszt_naprawy,
    gwarancja,
    notatki,
    zalaczniki,
    wykresy,
    pojazd,
    start,
    system,
    komponenty,
    warsztaty,
    ceny_czesci,
    szkice,
    kopie,
    plik_pojazdu,
    zaproszenia,
    powiadomienia,
    przyszlosc,
    nawigacja,
    zaznaczanie,
)
