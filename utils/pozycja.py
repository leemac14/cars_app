"""Pamięć pozycji przewijania: ekran ma zostawać tam, gdzie był.

Router przebudowuje CAŁY stos widoków przy każdej zmianie sortowania, filtra
i po każdej akcji na wpisie — `przejdz(page, page.route)` robi
`page.views.clear()` i składa ekran od nowa. Nowa lista zaczyna się od zera,
więc ktoś, kto przewinął sto tankowań w dół i odhaczył jedno z nich, lądował
z powrotem na samej górze.

Nie przebudowywać wcale byłoby lepiej, ale to przepisanie dziesięciu ekranów na
odświeżanie w miejscu. Tańsza i — co ważniejsze — PEŁNIEJSZA odpowiedź: zapamiętać,
gdzie stał pasek, i wrócić tam zaraz po zbudowaniu. Działa dla każdego ekranu
naraz, także dla tych, które dopiero powstaną.

Dwie rzeczy, na których to stoi:

1. **Klucz musi przeżyć przebudowę, a kontrolka nie.** Po `views.clear()` nie ma
   ani widoku, ani listy — zostaje tylko `state`. Dlatego pozycje siedzą
   w `state.pozycje_przewijania` pod kluczem opisującym MIEJSCE (trasa, zakładka,
   nazwa listy), a nie obiekt.
2. **Powrót musi poczekać na układ.** `scroll_to` wywołane w chwili budowania nie
   ma jeszcze czego przewijać — Flutter nie policzył wysokości. Stąd krótkie
   oddanie sterowania, tak samo jak przy szkieletach (patrz utils.szkielet).
"""

import asyncio
import inspect
import log

from .animacje import _petla_dziala

# Tyle czekamy, zanim wrócimy na zapamiętaną pozycję. Wystarczy jedna klatka —
# chodzi tylko o to, żeby Flutter zdążył policzyć wysokość zawartości.
OPOZNIENIE_POWROTU_S = 0.08

# Druga próba, po oknie szkieletu. Ekrany z wykresami i długimi listami pokazują
# najpierw zarys, a treść dobudowują chwilę później (utils.szkielet) — w chwili
# pierwszej próby nie ma tam jeszcze czego przewijać. Powtórka nic nie kosztuje,
# a bez niej właśnie te ekrany, które przewija się najdłużej, wracałyby na górę.
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
    """Dokłada handler do `on_scroll`, ZAMIAST go podmieniać.

    Na tej samej liście siedzi dziś nagłówek miesiąca (utils.miesiace) i pamięć
    pozycji. Przypisanie wprost sprawiłoby, że ten, kto dopisze się drugi, po
    cichu wyłącza pierwszego — a najgorsze w takiej usterce jest to, że nic nie
    wybucha."""
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


def przewin_na(page, kontrolka, pikseli, nadal_aktualne=None):
    """Wraca na zadaną pozycję, gdy tylko Flutter policzy układ.

    Próbujemy DWA razy. Pierwsza próba idzie po jednej klatce i załatwia zwykłe
    listy. Druga czeka na okno szkieletu: ekrany z wykresami pokazują najpierw
    zarys, a treść dobudowują chwilę później (utils.szkielet) — w chwili
    pierwszej próby nie ma tam jeszcze czego przewijać.

    `nadal_aktualne` chroni przed szarpnięciem: jeśli w te dwieście milisekund
    użytkownik zdążył sam przewinąć, druga próba odpuszcza."""
    if not pikseli or pikseli < PROG_PAMIETANIA:
        return False

    cel = float(pikseli)

    async def _ustaw():
        # `scroll_to` jest we Flecie 0.86 KORUTYNĄ. Wywołane bez `await` tworzy
        # obiekt korutyny, wyrzuca go i nie przewija niczego — po cichu, bez
        # żadnego błędu. Dokładnie ta klasa usterki, co porzucony `run_task`
        # (patrz audyt 4 w tests/audyty.py). `isawaitable` zamiast samego
        # `await`, bo w starszych Fletach ta sama metoda bywa synchroniczna.
        try:
            wynik = kontrolka.scroll_to(offset=cel, duration=0)
            if inspect.isawaitable(wynik):
                await wynik
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
    return True


def pamietaj_pozycje(page, state, kontrolka, klucz):
    """Podpina zapisywanie pozycji i od razu wraca na zapamiętaną.

    Wołać zaraz po zbudowaniu kontrolki, jeszcze w trakcie budowania ekranu —
    im wcześniej ruszy powrót, tym mniejsza szansa, że użytkownik zdąży zobaczyć
    listę na górze i dopiero potem skok.

    `klucz` może być funkcją bez argumentów. To nie jest ozdoba: ekran główny
    NIE przebudowuje się przy zmianie zakładki (przełącza zawartość w miejscu),
    więc przewijana jest wciąż ta sama kontrolka, a miejsce, którego dotyczy —
    już inne. Klucz liczony w chwili przewijania trafia do właściwej zakładki,
    klucz zapamiętany przy podpięciu zapisywałby Kokpit pod Serwisem."""
    if kontrolka is None:
        return kontrolka

    def _biezacy_klucz():
        return klucz() if callable(klucz) else klucz

    def _zapisz(e):
        zapisz_pozycje(state, _biezacy_klucz(), getattr(e, "pixels", None))

    dodaj_obsluge_przewijania(kontrolka, _zapisz)
    cel = pobierz_pozycje(state, _biezacy_klucz())
    przewin_na(page, kontrolka, cel,
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
