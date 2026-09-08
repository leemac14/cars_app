"""
Współdzielenie pojazdu — synchronizacja z Supabase.

Reszta aplikacji działa dokładnie jak dotychczas: w 100% lokalnie i offline.
Ten moduł włącza się TYLKO dla pojazdu świadomie oznaczonego jako współdzielony.
Synchronizowane są wszystkie wpisy za pomocą uniwersalnej tabeli zdalne_rekordy.

Trzy rzeczy, o których warto wiedzieć przed czytaniem dalej:

1. ROLE. Pojazd ma u każdego uczestnika swoją rolę (patrz db/synchronizacja):
   właściciel i pełny dostęp robią wszystko, współautor dopisuje własne wpisy,
   a podgląd wyłącznie czyta — przy tej roli NIC z tego telefonu nie leci do
   chmury, łącznie z usunięciami. Blokada w interfejsie to wygoda; twardą
   granicę stawia wyzwalacz po stronie Supabase (patrz supabase/role_wspoldzielenia.sql).

2. DELTA. Pobieranie pyta o rekordy zmienione od ostatniego razu
   (`zaktualizowano >= znacznik_delty`), a nie o komplet 19 tabel za każdym
   razem. Gdyby kolumny znacznika nie było, moduł raz to zauważa i wraca do
   pełnego pobierania — bez błędu widocznego dla użytkownika.

3. JEDNA NARAZ. Dwa zapisy formularza pod rząd odpalały dwie synchronizacje
   równolegle i potrafiły się wyścignąć o `zdalny_hash`. Teraz wejście do
   synchronizuj_wszystko jest pod zamkiem (_ZAMEK_SYNC).

Pakiet powstał z rozbicia jednego pliku sync.py. Moduły są ułożone od najmniej
zależnych do najbardziej: `stale` nie zależy od niczego, `wspoldzielenie` na
końcu, bo zamawia pełny przebieg synchronizacji. Cały interfejs jest
re-eksportowany tutaj, więc `import sync` i `sync.cokolwiek(...)` działa jak dawniej.

DWIE NAZWY NIE SĄ TU RE-EKSPORTOWANE i to jest zamierzone: `_klient_cache`
(polaczenie) oraz `_delta_dostepna` (delta). Obie są PRZYPISYWANE na nowo przez
`global`, więc kopia zrobiona przy imporcie zamarzłaby na wartości początkowej
i kłamała. Listy konfliktów są re-eksportowane, bo tamte mutują się w miejscu.
"""

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
