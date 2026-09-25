"""Pamięć wyników liczonych z bazy — ważna do najbliższej zmiany danych.

ZNACZNIK ZMIAN
--------------
Liczba, która rośnie po każdym zatwierdzonym zapisie zmieniającym choć jeden
wiersz. Podbija ją `polacz_baze` (patrz db/polaczenie.py), więc żaden zapis
z formularza, synchronizacji, kosza czy importu CSV nie musi o niej pamiętać.
Wprost woła ją tylko ten, kto zmienia bazę z pominięciem `polacz_baze` — np.
`init_db()` po podmianie całego pliku przy wczytaniu kopii zapasowej.

Jeden znacznik na całą bazę, a nie osobny na pojazd: waluta, progi, jednostki
i kosz są wspólne dla wszystkich aut, a na ekranie i tak stoi jedno auto naraz.
Zapis przy aucie B czyści więc także pamięć auta A — policzy się ono raz, przy
pierwszym powrocie na jego ekran.

PAMIĘĆ
------
`z_pamieci(nazwa, auto_id, licz)` trzyma wynik pod kluczem (nazwa, pojazd)
razem ze znacznikiem i DNIEM, dla którego go policzono. Inny znacznik znaczy
„ktoś coś zapisał”, inny dzień — „terminy, miesiące i dni do przeglądu
przesunęły się same, bez żadnego zapisu”. W obu przypadkach cała pamięć idzie
do kosza naraz; trzymanie starych wpisów nie miałoby sensu, bo do starego
znacznika nic już nie wraca.

Żyje wyłącznie w pamięci procesu: pierwsze wejście po uruchomieniu aplikacji
liczy wszystko, każde następne bierze gotowe. Nic z tego nie trafia do bazy
ani do kopii zapasowej.
"""

import copy
import threading
from datetime import date

_znacznik = 0
_pamiec = {}
# (znacznik, dzień), dla którego policzono to, co leży w _pamiec.
_stan_pamieci = None
# Formularze i synchronizacja zapisują z wątków obsługi zdarzeń, a ekran może
# się w tym czasie budować na innym — podbicie znacznika i podmiana pamięci
# muszą być niepodzielne.
_zamek = threading.Lock()


def _dzien():
    """Osobna funkcja, żeby test mógł przestawić kalendarz bez ruszania zegara."""
    return date.today()


def znacznik_zmian_danych() -> int:
    """Numer ostatniej zmiany danych — rośnie po każdym zapisie (patrz wyżej)."""
    return _znacznik


def zanotuj_zmiane_danych():
    """Unieważnia wszystko, co policzono z bazy przed tą chwilą."""
    global _znacznik
    with _zamek:
        _znacznik += 1


def z_pamieci(nazwa, auto_id, licz):
    """Wynik `licz()` zapamiętany pod (nazwa, auto_id) do najbliższej zmiany
    danych albo zmiany daty.

    Wywołujący dostaje KOPIĘ: lista czy słownik zmienione w miejscu przez jeden
    ekran nie mogą po cichu zmienić liczb, które pamięć wyda następnemu.

    Wynik liczony w chwili, gdy ktoś inny akurat zapisuje, NIE trafia do
    pamięci — nie wiadomo, czy widział stan sprzed zapisu, czy po nim, więc
    następne wejście policzy go jeszcze raz, już po zapisie."""
    global _stan_pamieci
    stan = (_znacznik, _dzien())
    klucz = (nazwa, auto_id)
    with _zamek:
        if _stan_pamieci == stan and klucz in _pamiec:
            return copy.deepcopy(_pamiec[klucz])

    wynik = licz()

    with _zamek:
        if (_znacznik, _dzien()) == stan:
            if _stan_pamieci != stan:
                _pamiec.clear()
                _stan_pamieci = stan
            _pamiec[klucz] = copy.deepcopy(wynik)
    return wynik


def w_pamieci(nazwa, auto_id) -> bool:
    """Czy wynik leży w pamięci i jest nadal ważny — bez liczenia go."""
    with _zamek:
        return _stan_pamieci == (_znacznik, _dzien()) and (nazwa, auto_id) in _pamiec


__all__ = [
    "w_pamieci",
    "z_pamieci",
    "zanotuj_zmiane_danych",
    "znacznik_zmian_danych",
]
