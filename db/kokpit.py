"""Metryki kokpitu — dane wszystkich kafelków zebrane w jednym miejscu.

Kafelki pytały bazę każdy osobno i przy każdej przebudowie ekranu: komplet
kafelków to ponad sto wejść do bazy, a na ekran główny wraca się po każdej
czynności. Teraz:

* `METRYKI_KOKPITU` mówi, JAK liczy się każda metryka,
* `METRYKI_KAFELKOW` mówi, CZEGO potrzebuje każdy kafelek,
* `metryki_kokpitu()` zbiera wszystko dla włączonych kafelków jednym
  wywołaniem, a pamięć (db/pamiec.py) trzyma wynik pod kluczem: metryka +
  pojazd + znacznik ostatniej zmiany danych + dzień.

Powrót na kokpit bez żadnego zapisu po drodze nie pyta więc bazy o żadną
liczbę. Metryka wspólna kilku kafelków liczy się raz: koszty miesięczne dla
„Kosztu w mies.” i „Wydatków 6 mies.”, porównanie dla „Kosztu / km”
i spalania. Kondycję i listę powiadomień pamięta już sama warstwa danych
(pobierz_rozbicie_kondycji, pobierz_powiadomienia) — przy jednym wejściu na
ekran główny liczyły je osobno kafelki, nagłówek pojazdu, dzwonek i porównanie.

Każda metryka woła funkcje danych PO NAZWIE w chwili liczenia (lambda, nie
gotowa referencja) — test, który podmienia funkcję danych we wszystkich
modułach, podmienia ją wtedy także tutaj.
"""

import calendar
import time
from datetime import datetime
from typing import Any

import log

from .stale import KATEGORIA_INNE_DROGOWE, TYP_CYKLICZNY_OPONY
from .pamiec import w_pamieci, z_pamieci
from .ustawienia import czy_skumulowany_z_cena_zakupu, pobierz_okno_kroczace
from .synchronizacja import czy_tylko_podglad
from .energia import domyslny_rodzaj_energii
from .magazyn import pobierz_stan_magazynu, pobierz_stan_opon
from .checklisty import podsumowanie_checklist
from .przebieg import oblicz_sredni_dzienny_przebieg
from .koszty import pobierz_koszt_miesiaca_do_dnia, pobierz_koszty_miesieczne, suma_kategorii_innych
from .powiadomienia import pobierz_powiadomienia
from .statystyki import (
    koszt_na_1000km, oblicz_kondycje_pojazdu, podsumowanie_do_zrobienia,
    pobierz_serie_dziennego_przebiegu, pobierz_serie_kosztu_km, pobierz_serie_spalania,
    pobierz_zasieg_ev,
)
from .pojazd import pobierz_dane_do_porownania
from .analiza import koszt_skumulowany, obserwacje_analityczne, pobierz_zasieg_na_baku, prognoza_kosztow, stan_budzetow
from .rejestry import pobierz_wydatki_cykliczne
from .nawigacja import pobierz_ostatnia_aktywnosc


def _koszt_poprzedniego_miesiaca(auto_id):
    """Koszt poprzedniego miesiąca do TEGO SAMEGO dnia — „Koszt w mies.”
    porównuje dzień do dnia, bo niepełny bieżący miesiąc kontra CAŁY poprzedni
    pokazywał drugiego dnia fałszywe „-95%”. Czy porównanie w ogóle pokazać
    (w pierwszym tygodniu jest zbyt szumiące), decyduje kafelek."""
    dzisiaj = datetime.now()
    rok, miesiac = dzisiaj.year, dzisiaj.month - 1
    if miesiac <= 0:
        miesiac += 12
        rok -= 1
    # 31 marca porównany z lutym: luty ma najwyżej 28 albo 29 dni.
    do_dnia = min(dzisiaj.day, calendar.monthrange(rok, miesiac)[1])
    return pobierz_koszt_miesiaca_do_dnia(auto_id, rok, miesiac, do_dnia)


def _oplaty_drogowe(auto_id):
    """Winiety, bramki i mandaty od początku roku."""
    dzisiaj = datetime.now().date()
    return suma_kategorii_innych(auto_id, KATEGORIA_INNE_DROGOWE, dzisiaj.replace(month=1, day=1), dzisiaj)


def _spalanie(auto_id):
    """Seria dla strony, którą pokazuje kokpit: przy hybrydzie plug-in PALIWOWEJ,
    przy elektryku — prądowej. Litry i kWh w jednej serii dałyby liczbę bez
    znaczenia; pełne rozbicie jest w Statystykach."""
    rodzaj = domyslny_rodzaj_energii(auto_id)
    return {"rodzaj": rodzaj, "seria": pobierz_serie_spalania(auto_id, 12, rodzaj=rodzaj)}


def _opony(auto_id):
    """Zestaw na aucie i termin zmiany z przypomnienia typu „opony” — to ono jest
    w tej aplikacji źródłem prawdy o dacie. None: auto nie ma żadnego zestawu."""
    stan = pobierz_stan_opon(auto_id)
    if not stan:
        return None
    terminy = [w for w in pobierz_wydatki_cykliczne(auto_id) if w[6] == TYP_CYKLICZNY_OPONY]
    return {"stan": stan, "terminy": terminy}


def _koszt_1000km(auto_id):
    """W kilometrach, jak w bazie — na jednostkę z Ustawień przelicza kafelek."""
    return koszt_na_1000km(auto_id, pobierz_okno_kroczace(auto_id))


# Metryka -> funkcja pojazdu, która ją liczy. Liczy się tylko ta, której
# potrzebuje kafelek stojący akurat na kokpicie — krzywa narastająca to przejście
# po WSZYSTKICH wpisach kosztowych auta i nie ma powodu płacić za nią bez kafelka.
METRYKI_KOKPITU = {
    "koszty_miesieczne": lambda auto_id: pobierz_koszty_miesieczne(auto_id, 6),
    "koszt_poprzedniego_miesiaca": lambda auto_id: _koszt_poprzedniego_miesiaca(auto_id),
    "powiadomienia": lambda auto_id: pobierz_powiadomienia(auto_id),
    "porownanie": lambda auto_id: pobierz_dane_do_porownania(auto_id) or {},
    "spalanie": lambda auto_id: _spalanie(auto_id),
    # Iskry przy kafelkach liczbowych: liczba mówi „ile”, iskra — „w którą stronę”.
    "seria_przebiegu": lambda auto_id: pobierz_serie_dziennego_przebiegu(auto_id, 12),
    "sredni_przebieg": lambda auto_id: oblicz_sredni_dzienny_przebieg(auto_id),
    "seria_kosztu_km": lambda auto_id: pobierz_serie_kosztu_km(auto_id, 6),
    "skumulowany": lambda auto_id: koszt_skumulowany(auto_id, z_cena_zakupu=czy_skumulowany_z_cena_zakupu()),
    "koszt_1000km": lambda auto_id: _koszt_1000km(auto_id),
    "zasieg_ev": lambda auto_id: pobierz_zasieg_ev(auto_id),
    "ostatnia_aktywnosc": lambda auto_id: pobierz_ostatnia_aktywnosc(auto_id, limit=3),
    "kondycja": lambda auto_id: oblicz_kondycje_pojazdu(auto_id),
    "obserwacja": lambda auto_id: obserwacje_analityczne(auto_id, limit=1),
    "budzety": lambda auto_id: stan_budzetow(auto_id),
    "zasieg_bak": lambda auto_id: pobierz_zasieg_na_baku(auto_id),
    "prognoza": lambda auto_id: prognoza_kosztow(auto_id),
    "opony": lambda auto_id: _opony(auto_id),
    "checklista": lambda auto_id: podsumowanie_checklist(auto_id),
    "oplaty_drogowe": lambda auto_id: _oplaty_drogowe(auto_id),
    "do_zrobienia": lambda auto_id: podsumowanie_do_zrobienia(auto_id),
    "magazyn": lambda auto_id: pobierz_stan_magazynu(auto_id),
    # Rola przy pojeździe: kafelki akcji znikają przy „podglądzie”.
    "tylko_podglad": lambda auto_id: czy_tylko_podglad(auto_id),
}

# Kafelek (klucz z db.KOKPIT_WIDGETY) -> metryki, których potrzebuje. Kafelek
# sięgający po metrykę spoza swojej listy wywraca budowę kokpitu, gdy stoi na
# nim sam — i tego pilnuje tests/test_pamiec_metryk.py.
METRYKI_KAFELKOW = {
    "koszt_miesiac": ("koszty_miesieczne", "koszt_poprzedniego_miesiaca"),
    "termin": ("powiadomienia",),
    "wykres": ("koszty_miesieczne",),
    "skumulowany": ("skumulowany",),
    "koszt_1000km": ("koszt_1000km",),
    "koszt_km": ("porownanie", "seria_kosztu_km"),
    "spalanie": ("porownanie", "spalanie"),
    "przebieg_dzienny": ("sredni_przebieg", "seria_przebiegu"),
    "ostatnia_aktywnosc": ("ostatnia_aktywnosc",),
    "kondycja": ("kondycja",),
    "zasieg_ev": ("zasieg_ev",),
    "obserwacja": ("obserwacja",),
    "budzet": ("budzety",),
    "zasieg_bak": ("zasieg_bak",),
    "prognoza_rok": ("prognoza",),
    "opony": ("opony",),
    "checklist": ("checklista",),
    "oplaty_drogowe": ("oplaty_drogowe",),
    "do_zrobienia": ("do_zrobienia",),
    "magazyn": ("magazyn",),
    "akcja_tankowanie": ("tylko_podglad",),
    "akcja_licznik": ("tylko_podglad",),
    "akcja_inny_koszt": ("tylko_podglad",),
    "akcja_wizyta": ("tylko_podglad",),
    "akcja_podzespol": ("tylko_podglad",),
    "akcja_do_zrobienia": ("tylko_podglad",),
}


def _klucz_pamieci(nazwa):
    return f"kokpit:{nazwa}"


def metryka_kokpitu(auto_id, nazwa) -> Any:
    """Jedna metryka — z pamięci, a gdy jej tam nie ma, policzona i zapamiętana."""
    licz = METRYKI_KOKPITU[nazwa]
    return z_pamieci(_klucz_pamieci(nazwa), auto_id, lambda: licz(auto_id))


def metryki_kokpitu(auto_id, widgety) -> dict[str, Any]:
    """Dane podanych kafelków naraz: {nazwa metryki: wartość}.

    Metryka wspólna kilku kafelków liczy się raz, a policzona wcześniej i nie
    unieważniona zapisem — wcale. Gdy trzeba było coś policzyć, w logu zostaje
    jedna linijka z czasem: tylko tak widać, ile kokpit kosztuje NA TYM
    telefonie i jak często pamięć musi liczyć od nowa."""
    potrzebne = []
    for wid in widgety:
        for nazwa in METRYKI_KAFELKOW.get(wid, ()):
            if nazwa not in potrzebne:
                potrzebne.append(nazwa)
    brakujace = [n for n in potrzebne if not w_pamieci(_klucz_pamieci(n), auto_id)]
    poczatek = time.perf_counter()
    wynik = {nazwa: metryka_kokpitu(auto_id, nazwa) for nazwa in potrzebne}
    if brakujace:
        milisekundy = (time.perf_counter() - poczatek) * 1000
        log.zapisz(f"metryki kokpitu: policzone {len(brakujace)} z {len(potrzebne)} w {milisekundy:.0f} ms")
    return wynik


__all__ = [
    "METRYKI_KAFELKOW",
    "METRYKI_KOKPITU",
    "metryka_kokpitu",
    "metryki_kokpitu",
]
