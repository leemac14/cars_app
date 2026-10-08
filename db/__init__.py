"""Warstwa danych: SQLite, logika domenowa, eksport i import. Moduły ułożone od najmniej
zależnych (`stale`, `pamiec`, `polaczenie`) do najbardziej (`migracje`, za nią
`manifest_kopii`); całość re-eksportowana tutaj, więc działa `db.cokolwiek(...)`."""

# Ten plik istnieje po to, żeby scalić moduły pakietu w jedną przestrzeń nazw —
# gwiazdki i „nieużywane” importy są tu zamierzone.
# ruff: noqa: F401, F403

from .stale import *
from .pamiec import *
from .polaczenie import *
from .pomocnicze import *
from .daty import *
from .ustawienia import *
from .nowosci import *
from .jednostki import *
from .synchronizacja import *
from .energia import *
from .notatki import *
from .zalaczniki import *
from .dokumenty import *
from .szkice import *
from .kopie import *
from .ceny_czesci import *
from .magazyn import *
from .checklisty import *
from .przebieg import *
from .koszty import *
from .gwarancje import *
from .raty import *
from .ewidencja import *
from .powiadomienia import *
from .statystyki import *
from .pojazd import *
from .analiza import *
from .nazwy import *
from .tagi import *
from .rejestry import *
from .wizyty import *
from .usuwanie import *
from .rozliczenia import *
from .kosz import *
from .nawigacja import *
from .odliczania import *
from .os_przyszlosci import *
from .kokpit import *
from .wyszukiwanie import *
from .os_czasu import *
from .eksport import *
from .raporty import *
from .import_csv import *
from .presety_importu import *
from .migracje import *
from .manifest_kopii import *

from . import (
    stale,
    pamiec,
    polaczenie,
    pomocnicze,
    daty,
    ustawienia,
    nowosci,
    jednostki,
    synchronizacja,
    energia,
    notatki,
    zalaczniki,
    dokumenty,
    szkice,
    kopie,
    ceny_czesci,
    magazyn,
    checklisty,
    przebieg,
    koszty,
    gwarancje,
    raty,
    ewidencja,
    powiadomienia,
    statystyki,
    pojazd,
    analiza,
    nazwy,
    tagi,
    rejestry,
    wizyty,
    usuwanie,
    rozliczenia,
    kosz,
    nawigacja,
    odliczania,
    os_przyszlosci,
    kokpit,
    wyszukiwanie,
    os_czasu,
    eksport,
    raporty,
    import_csv,
    presety_importu,
    migracje,
    manifest_kopii,
)

# Widok eksportu pyta wprost `db.FPDF is not None`, żeby wiedzieć, czy
# generowanie PDF jest w ogóle dostępne — nazwa musi więc zostać na wierzchu.
from .raporty import FPDF
