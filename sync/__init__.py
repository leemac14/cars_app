"""Współdzielenie pojazdu — synchronizacja z Supabase (uniwersalna tabela
zdalne_rekordy). Reszta aplikacji działa lokalnie i offline; moduł włącza się TYLKO dla
pojazdu współdzielonego.
1. ROLE (db/synchronizacja): właściciel i pełny — wszystko, współautor — własne wpisy,
podgląd — NIC nie wysyła (także usunięć). Twarda granica: wyzwalacz w Supabase
(supabase/role_wspoldzielenia.sql).
2. DELTA: pobieranie zmian od `znacznik_delty`; bez tej kolumny po stronie serwera —
ciche pełne pobieranie.
3. JEDNA NARAZ: synchronizuj_wszystko pod zamkiem (_ZAMEK_SYNC).
Moduły od `stale` do `wspoldzielenie`; całość re-eksportowana. DWIE NAZWY NIE SĄ
RE-EKSPORTOWANE celowo: `_klient_cache` (polaczenie) i `_delta_dostepna` (delta) —
przypisywane przez `global`, kopia z importu zamarzłaby. Listy konfliktów są
re-eksportowane, bo mutują się w miejscu."""

# Ten plik istnieje po to, żeby scalić moduły pakietu w jedną przestrzeń nazw —
# gwiazdki i „nieużywane” importy są tu zamierzone.
# ruff: noqa: F401, F403

from .stale import *
from .polaczenie import *
from .role import *
from .delta import *
from .nagrobki import *
from .konflikty import *
from .pomocnicze import *
from .wysylanie import *
from .pobieranie import *
from .przywracanie import *
from .przebieg import *
from .wspoldzielenie import *

from . import (
    stale,
    polaczenie,
    role,
    delta,
    nagrobki,
    konflikty,
    pomocnicze,
    wysylanie,
    pobieranie,
    przywracanie,
    przebieg,
    wspoldzielenie,
)
