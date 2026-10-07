"""Pamięć pozycji przewijania: router przebudowuje CAŁY stos (`page.views.clear()`) przy
sortowaniu, filtrze i akcji na wpisie, więc zapamiętujemy pozycję i wracamy po
zbudowaniu — działa dla każdego ekranu.
1. Pozycje w `state.pozycje_przewijania` pod kluczem MIEJSCA (trasa, zakładka, lista),
nie kontrolki.
2. Powrót czeka na układ (`scroll_to` przy budowie nie ma czego przewijać) — jak przy
szkieletach."""

import asyncio
import inspect
import log

from .animacje import _petla_dziala

# Tyle czekamy, zanim wrócimy na zapamiętaną pozycję. Wystarczy jedna klatka —
# chodzi tylko o to, żeby Flutter zdążył policzyć wysokość zawartości.
OPOZNIENIE_POWROTU_S = 0.08

# Druga próba po oknie szkieletu — ekrany z wykresami dobudowują treść później
# (utils.szkielet).
OPOZNIENIE_DRUGIEJ_PROBY_S = 0.20

# Poniżej tylu pikseli nie ma czego pamiętać. Bez tego progu każde muśnięcie
# palcem zapisywałoby pozycję „prawie na górze", a powrót na nią wyglądałby jak
# usterka: ekran drgałby po każdym wejściu.
PROG_PAMIETANIA = 24

# Odstęp zdarzeń przewijania. Pozycja ma być świeża w chwili przebudowy, a nie
# dokładna co do piksela — setki zdarzeń na sekundę nic tu nie wnoszą.
# Flet domyślnie daje 10 ms, czyli sto zdarzeń na sekundę na każdą przewijaną
# listę; traktujemy tę wartość jak „nikt się nie wypowiedział".
ODSTEP_ZDARZEN_MS = 100
ODSTEP_DOMYSLNY_FLETA_MS = 10


def _pamiec(state):
    pamiec = getattr(state, "pozycje_przewijania", None)
    if pamiec is None:
        pamiec = {}
        try:
            state.pozycje_przewijania = pamiec
        except Exception:
            log.polkniety("założenie pamięci pozycji przewijania")
    return pamiec


def dodaj_obsluge_przewijania(kontrolka, handler):
    """Dokłada handler do `on_scroll` ZAMIAST go podmieniać — na liście siedzą nagłówek
    miesiąca (utils.miesiace) i pamięć pozycji, a przypisanie po cichu wyłączyłoby
    pierwszego."""
    poprzedni = getattr(kontrolka, "on_scroll", None)

    if poprzedni is None:
        kontrolka.on_scroll = handler
    else:
        def _obaj(e, _a=poprzedni, _b=handler):
            _a(e)
            _b(e)
        kontrolka.on_scroll = _obaj

    try:
        biezacy = getattr(kontrolka, "scroll_interval", None)
        if not biezacy or biezacy in (ODSTEP_DOMYSLNY_FLETA_MS,) or biezacy > ODSTEP_ZDARZEN_MS:
            kontrolka.scroll_interval = ODSTEP_ZDARZEN_MS
    except Exception:
        log.polkniety("ustawienie odstępu zdarzeń przewijania")
    return kontrolka


def zapisz_pozycje(state, klucz, pikseli):
    """Zapisuje pozycję albo ją kasuje, gdy jesteśmy praktycznie na górze."""
    pamiec = _pamiec(state)
    try:
        pikseli = float(pikseli or 0)
    except (TypeError, ValueError):
        return
    if pikseli < PROG_PAMIETANIA:
        pamiec.pop(klucz, None)
    else:
        pamiec[klucz] = pikseli


def pobierz_pozycje(state, klucz):
    return _pamiec(state).get(klucz)


def zapomnij_pozycje(state, klucz=None):
    """Kasuje pozycję jednego miejsca albo wszystkich.

    Woła się to przy zmianie pojazdu: to samo miejsce na liście, ale zupełnie
    inne wpisy — powrót na dwa tysiące pikseli w dół nie miałby znaczenia."""
    pamiec = _pamiec(state)
    if klucz is None:
        pamiec.clear()
    else:
        pamiec.pop(klucz, None)


def przewin_na(page, kontrolka, pikseli, nadal_aktualne=None, opis=None):
    """Wraca na pozycję po policzeniu układu: dwie próby (po jednej klatce i po oknie
    szkieletu). `nadal_aktualne` — druga odpuszcza, gdy użytkownik zdążył sam przewinąć."""
    if not pikseli or pikseli < PROG_PAMIETANIA:
        return False

    cel = float(pikseli)

    nazwa = opis or type(kontrolka).__name__

    async def _ustaw():
        # `scroll_to` w Flecie 0.86 jest KORUTYNĄ — bez `await` po cichu nic nie robi
        # (jak porzucony `run_task`, audyt 4 w tests/audyty.py). `isawaitable`, bo w
        # starszych Fletach bywa synchroniczna.
        try:
            wynik = kontrolka.scroll_to(offset=cel, duration=0)
            if inspect.isawaitable(wynik):
                await wynik
            # Ślad w logu, bo tej jednej rzeczy nie da się sprawdzić testem:
            # czy Flutter po drugiej stronie NAPRAWDĘ przewinął. „przewinięto"
            # bez skutku na ekranie znaczy, że `scroll_to` jest dla tej
            # kontrolki puste i trzeba innej drogi (patrz claude/pozycja-przewijania.md).
            log.zapisz(f"pozycja: przewinięto {nazwa} na {cel:.0f} px")
        except Exception:
            # Zawartość mogła się skrócić (filtr) albo kontrolki już nie ma na
            # stronie. Zostanie góra listy — tak jak było przed tą zmianą.
            log.polkniety("powrót na zapamiętaną pozycję przewijania")

    if not _petla_dziala(page):
        return False

    async def _wroc():
        await asyncio.sleep(OPOZNIENIE_POWROTU_S)
        await _ustaw()
        await asyncio.sleep(OPOZNIENIE_DRUGIEJ_PROBY_S)
        if nadal_aktualne is None or nadal_aktualne():
            await _ustaw()

    try:
        page.run_task(_wroc)
    except Exception:
        log.polkniety("zaplanowanie powrotu na pozycję przewijania")
        return False
    log.zapisz(f"pozycja: planuję powrót {nazwa} na {cel:.0f} px")
    return True


def pamietaj_pozycje(page, state, kontrolka, klucz):
    """Podpina zapis pozycji i od razu wraca na zapamiętaną; wołać zaraz po zbudowaniu
    kontrolki. `klucz` może być funkcją — ekran główny przełącza zakładki w miejscu (ta
    sama kontrolka, inne miejsce), więc klucz liczony w chwili przewijania."""
    if kontrolka is None:
        return kontrolka

    def _biezacy_klucz():
        return klucz() if callable(klucz) else klucz

    def _zapisz(e):
        zapisz_pozycje(state, _biezacy_klucz(), getattr(e, "pixels", None))

    dodaj_obsluge_przewijania(kontrolka, _zapisz)
    cel = pobierz_pozycje(state, _biezacy_klucz())
    przewin_na(page, kontrolka, cel, opis=_biezacy_klucz(),
               nadal_aktualne=lambda: pobierz_pozycje(state, _biezacy_klucz()) == cel)
    return kontrolka


def klucz_ekranu(widok, state=None):
    """Klucz miejsca dla całego ekranu.

    Ekran główny to cztery ekrany pod jedną trasą, a dwa z nich mają jeszcze
    podzakładki — bez tego Kokpit odziedziczyłby pozycję po Serwisie, po którym
    akurat przełączono."""
    trasa = str(getattr(widok, "route", "") or type(widok).__name__)
    if trasa != "/" or state is None:
        return f"ekran:{trasa}"
    czesci = [
        int(getattr(state, "zakladka", 0) or 0),
        int(getattr(state, "koszty_podzakladka", 0) or 0),
        int(getattr(state, "stat_podzakladka", 0) or 0),
    ]
    return "ekran:/#" + "-".join(str(c) for c in czesci)


__all__ = [
    "ODSTEP_DOMYSLNY_FLETA_MS",
    "ODSTEP_ZDARZEN_MS",
    "OPOZNIENIE_DRUGIEJ_PROBY_S",
    "OPOZNIENIE_POWROTU_S",
    "PROG_PAMIETANIA",
    "dodaj_obsluge_przewijania",
    "klucz_ekranu",
    "pamietaj_pozycje",
    "pobierz_pozycje",
    "przewin_na",
    "zapisz_pozycje",
    "zapomnij_pozycje",
]
