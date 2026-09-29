"""„Ile zostało do…” — wszystko, co w aucie ma koniec, na jednej liście.

Dzwonek pokazuje tylko to, co już weszło w próg powiadomienia, Karta pojazdu —
same dokumenty, zakładka Serwis — same podzespoły. Pytanie zadawane najczęściej
po otwarciu aplikacji („ile jeszcze do przeglądu, do OC, do oleju?”) nie miało
miejsca, w którym odpowiedź stoi w jednym rzędzie. Tu stoją: terminy dokumentów,
limit przebiegu gwarancji, gwarancje napraw, każdy podzespół z interwałem
i najbliższy okrągły przebieg — od najbliższego.

Nic nie liczy się tu po swojemu. Dokumenty biorą dni i status z
`terminy_pojazdu` (te same progi, co powiadomienia), podzespoły — z
`oblicz_stan_interwalu` (ten sam licznik „najpierw”, co karta w Serwisie
i dzwonek), gwarancje napraw — z `gwarancje_pojazdu` (ta sama ostatnia wymiana,
co karta w Serwisie), prognozy dat — z tego samego średniego przebiegu
dziennego. Nowy jest tylko pasek: jaka część okresu już minęła.

  • dokument — rok przed terminem: OC, AC, assistance i przegląd odnawia się
    co rok, a początku okresu baza nie trzyma;
  • gwarancja producenta — od pierwszej rejestracji, a bez niej od zakupu; bez
    żadnej z tych dat pasek nie ma początku (None) — zgadnięta długość
    gwarancji kłamałaby bardziej niż brak paska;
  • limit przebiegu gwarancji — od zera na liczniku;
  • gwarancja naprawy — od dnia (albo licznika) wymiany; tylko ta, która
    jeszcze trwa — po końcu nie ma już czego odliczać;
  • podzespół — zużycie interwału licznika, który skończy się pierwszy;
  • okrągły przebieg — od poprzedniej okrągłej liczby.
"""

import sqlite3
from datetime import datetime, timedelta
from typing import Any

from date import parsuj_date

from .stale import KM_W_MILI, STATUS_POJAZDU_AKTYWNY, STATUS_POJAZDU_SPRZEDANY
from .polaczenie import polacz_baze
from .ustawienia import pobierz_prog_dni, pobierz_prog_km
from .jednostki import dystans_z_km, jednostka_dystansu
from .przebieg import oblicz_sredni_dzienny_przebieg, pobierz_aktualny_przebieg
from .gwarancje import STATUS_GWARANCJI_BLISKO, gwarancje_pojazdu
from .powiadomienia import oblicz_stan_interwalu
from .pojazd import pobierz_dane_pojazdu, terminy_pojazdu


# Okrągły przebieg: co ile jednostek z Ustawień (km albo mil). 150 000 mil jest
# okrągłe dla kogoś, kto patrzy w mile — przeliczone 241 402 km już nie.
KROK_OKRAGLEGO_PRZEBIEGU = 10000

# Status licznika podzespołu (db.oblicz_stan_interwalu) -> status odliczania.
# Lista mówi językiem terminów dokumentów (terminy_pojazdu), bo te przyszły
# pierwsze i tak liczy je Karta pojazdu.
STATUS_Z_INTERWALU = {"przeterminowane": "po_terminie", "pilne": "blisko", "ok": "ok"}

# Okrągły przebieg nie jest obowiązkiem, więc nie bywa ani „blisko”, ani „po
# terminie” — ma własny status, który ekran maluje kolorem informacji.
STATUS_INFORMACJI = "info"

# Skąd pasek dokumentu bierze początek okresu (pokazuje to podpis wiersza).
POCZATEK_ROK = "rok"
POCZATEK_REJESTRACJA = "rejestracja"
POCZATEK_ZAKUP = "zakup"


def _dodatnia(wartosc):
    """Liczba całkowita > 0 albo None — puste pole i zero znaczą „nie ustawiono”."""
    try:
        liczba = int(float(wartosc))
    except (TypeError, ValueError):
        return None
    return liczba if liczba > 0 else None


def _rok_wczesniej(dzien):
    """Ten sam dzień rok wcześniej; 29 lutego cofa się na 28."""
    try:
        return dzien.replace(year=dzien.year - 1)
    except ValueError:
        return dzien.replace(year=dzien.year - 1, day=28)


def _udzial(poczatek, koniec, dzis):
    """Jaka część okresu [poczatek, koniec] już minęła, przycięta do 0–1.
    None, gdy okres nie ma długości (początek w dniu końca albo po nim)."""
    calosc = (koniec - poczatek).days
    if calosc <= 0:
        return None
    return max(0.0, min(1.0, (dzis - poczatek).days / calosc))


def _poczatek_gwarancji(dane, koniec):
    """(data, skąd) początku gwarancji producenta albo (None, None).

    Gwarancja rusza z dniem pierwszej rejestracji (wydania auta pierwszemu
    właścicielowi) — auto kupione z drugiej ręki ma ją krótszą o tyle, ile już
    jeździło. Data zakupu to zastępstwo dla aut kupionych nowych bez wpisanej
    rejestracji. Data, która nie jest PRZED końcem gwarancji, to literówka."""
    for kolumna, skad in (("data_pierwszej_rejestracji", POCZATEK_REJESTRACJA),
                          ("data_zakupu", POCZATEK_ZAKUP)):
        dzien = parsuj_date(dane.get(kolumna))
        if dzien != datetime.min.date() and dzien < koniec:
            return dzien, skad
    return None, None


def _prognoza(zostalo_km, sredni_dzienny, dzis):
    """(dni, data) do przejechania `zostalo_km` przy dzisiejszym tempie jazdy —
    tym samym wzorem, co prognoza licznika km w oblicz_stan_interwalu, żeby
    lista i karta podzespołu nie rozjechały się o dzień. (None, None) po
    przekroczeniu i bez średniego przebiegu."""
    if zostalo_km is None or zostalo_km < 0 or not sredni_dzienny or sredni_dzienny <= 0:
        return None, None
    dni = int(round(zostalo_km / sredni_dzienny))
    return dni, dzis + timedelta(days=dni)


def _pozycja(**pola):
    """Komplet kluczy pozycji — ekran i kafelek czytają je bez `.get()` na
    każdym kroku. Tytuł None: nazwa zależy od jednostki z Ustawień i składa ją
    dopiero ekran (utils.tytul_odliczania)."""
    pozycja = {
        "klucz": None, "rodzaj": None, "ikona": None, "tytul": None,
        "dni": None, "dni_sortowania": None, "data": None, "prognoza": False,
        "zostalo_km": None, "cel_km": None, "od_km": None, "udzial": None,
        "poczatek": None, "poczatek_z": None, "drugi": None, "gwarancja": None,
        "status": "ok", "trasa": None,
    }
    pozycja.update(pola)
    if pozycja["dni_sortowania"] is None:
        pozycja["dni_sortowania"] = pozycja["dni"]
    return pozycja


def _dokumenty(auto_id, dane, dzis):
    wynik = []
    for termin in terminy_pojazdu(auto_id, dane, dzis=dzis):
        koniec = termin["data_obj"]
        if termin["klucz"] == "gwarancja":
            poczatek, skad = _poczatek_gwarancji(dane, koniec)
        else:
            poczatek, skad = _rok_wczesniej(koniec), POCZATEK_ROK
        if termin["dni"] < 0:
            udzial = 1.0
        else:
            udzial = _udzial(poczatek, koniec, dzis) if poczatek else None
        wynik.append(_pozycja(
            klucz=f"dokument:{termin['klucz']}", rodzaj="dokument", ikona=termin["klucz"],
            tytul=termin["etykieta"], dni=termin["dni"], data=koniec,
            udzial=udzial, poczatek=poczatek, poczatek_z=skad,
            status=termin["status"], trasa=f"/auto/edytuj/{auto_id}",
        ))
    return wynik


def _limit_gwarancji(auto_id, dane, przebieg, sredni_dzienny, prog_km, dzis):
    """Limit przebiegu gwarancji. Bez znanego przebiegu nie ma czego odliczać:
    „zostało 150 000 km” przy pustym liczniku byłoby liczbą z niczego."""
    limit = _dodatnia(dane.get("gwarancja_przebieg"))
    if not limit or not przebieg:
        return []
    zostalo = limit - przebieg
    dni, data = _prognoza(zostalo, sredni_dzienny, dzis)
    status = "po_terminie" if zostalo < 0 else ("blisko" if zostalo <= prog_km else "ok")
    return [_pozycja(
        klucz="dokument:gwarancja_km", rodzaj="gwarancja_km", ikona="gwarancja",
        dni=dni, data=data, prognoza=True, zostalo_km=zostalo, cel_km=limit, od_km=0,
        udzial=max(0.0, min(1.0, przebieg / limit)), status=status,
        trasa=f"/auto/edytuj/{auto_id}",
    )]


def _podzespoly(auto_id, przebieg, sredni_dzienny, prog_km, prog_dni, dzis):
    """Jeden wiersz na podzespół — licznikiem, który skończy się pierwszy, bo to
    on jest terminem (ta sama zasada, co w powiadomieniu i na karcie w Serwisie).
    Drugi licznik jedzie obok jako `drugi`. Podzespół bez interwału albo bez
    pierwszej wymiany nie ma licznika i na liście go nie ma."""
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT id, nazwa, data, przebieg, interwal_km, interwal_miesiace, prog_km, prog_dni FROM zadania "
            "WHERE auto_id=? AND (interwal_km IS NOT NULL OR interwal_miesiace IS NOT NULL) ORDER BY nazwa, id",
            (auto_id,)
        )
        zadania = c.fetchall()

    wynik = []
    for zadanie in zadania:
        stan = oblicz_stan_interwalu(zadanie, przebieg, sredni_dzienny,
                                     prog_km=prog_km, prog_dni=prog_dni, dzis=dzis)
        if not stan["pierwsze"]:
            continue
        licznik = stan[stan["pierwsze"]]
        drugi = stan["czas" if stan["pierwsze"] == "km" else "km"]
        czy_km = licznik["rodzaj"] == "km"
        # Kilometry bez średniego przebiegu nie mają daty. Termin drugiego,
        # czasowego licznika jest wtedy granicą, której podzespół na pewno nie
        # przekroczy (kilometry skończą się PRZED nim) — lepsze miejsce na
        # liście niż sam koniec, gdzie stoją rzeczy bez żadnej daty.
        dni_sortowania = licznik["dni"]
        if dni_sortowania is None and drugi and drugi["zostalo"] >= 0:
            dni_sortowania = drugi["dni"]
        wynik.append(_pozycja(
            klucz=f"podzespol:{zadanie['id']}", rodzaj="podzespol", ikona="podzespol",
            tytul=zadanie["nazwa"], dni=licznik["dni"], dni_sortowania=dni_sortowania,
            data=licznik["data"], prognoza=licznik["prognoza"],
            zostalo_km=licznik["zostalo"] if czy_km else None,
            udzial=max(0.0, min(1.0, licznik["zuzycie"])), drugi=drugi,
            status=STATUS_Z_INTERWALU.get(licznik["status"], "ok"),
            trasa=f"/zadanie/edytuj/{zadanie['id']}",
        ))
    return wynik


def _gwarancje_napraw(auto_id, przebieg, sredni_dzienny, prog_km, prog_dni, dzis):
    """Jeden wiersz na gwarancję naprawy, która jeszcze trwa — limitem, który
    skończy się pierwszy (jak podzespół). Pełny stan gwarancji jedzie obok
    w `gwarancja`: podpis wiersza pokazuje oba limity i dzień wymiany."""
    wynik = []
    for g in gwarancje_pojazdu(auto_id, dzis=dzis, aktualny_przebieg=przebieg,
                               sredni_dzienny=sredni_dzienny, prog_dni=prog_dni, prog_km=prog_km):
        po_km = g["pierwsze"] == "przebieg"
        wynik.append(_pozycja(
            klucz=f"gwarancja:{g['historia_id']}", rodzaj="gwarancja_naprawy", ikona="gwarancja_naprawy",
            tytul=f"{g['nazwa']} — gwarancja",
            dni=g["dni_km"] if po_km else g["dni"], dni_sortowania=g["dni_do_konca"],
            data=g["data_km"] if po_km else g["koniec"], prognoza=po_km,
            zostalo_km=g["zostalo_km"] if po_km else None,
            cel_km=g["limit_km"], od_km=g["przebieg_wymiany"],
            udzial=g["udzial"], poczatek=g["data_wymiany"], gwarancja=g,
            status="blisko" if g["status"] == STATUS_GWARANCJI_BLISKO else "ok",
            trasa=f"/historia/{g['zadanie_id']}",
        ))
    return wynik


def _okragly_przebieg(przebieg, sredni_dzienny, dzis):
    """Najbliższa wielokrotność KROK_OKRAGLEGO_PRZEBIEGU w jednostce z Ustawień.
    Stan dokładnie na okrągłej liczbie celuje już w następną."""
    if not przebieg:
        return []
    j = jednostka_dystansu()
    teraz = dystans_z_km(przebieg, j)
    krok = KROK_OKRAGLEGO_PRZEBIEGU
    cel = (int(teraz // krok) + 1) * krok
    na_km = KM_W_MILI if j == "mi" else 1
    cel_km = cel * na_km
    zostalo = cel_km - przebieg
    dni, data = _prognoza(zostalo, sredni_dzienny, dzis)
    return [_pozycja(
        klucz="przebieg", rodzaj="przebieg", ikona="przebieg",
        dni=dni, data=data, prognoza=True, zostalo_km=zostalo,
        cel_km=cel_km, od_km=(cel - krok) * na_km,
        udzial=max(0.0, min(1.0, (teraz - (cel - krok)) / krok)),
        status=STATUS_INFORMACJI, trasa="/przebieg",
    )]


def _klucz_kolejnosci(pozycja):
    """Po terminie na górze (najdawniej przeterminowane pierwsze), dalej od
    najbliższej daty, na końcu to, czego nie da się umieścić w kalendarzu. Przy
    remisie wyżej staje to, co zjadło większą część swojego okresu."""
    dni = pozycja["dni_sortowania"]
    zjedzone = -(pozycja["udzial"] or 0.0)
    if pozycja["status"] == "po_terminie":
        return (0, dni if dni is not None else 0, zjedzone)
    if dni is not None:
        return (1, dni, zjedzone)
    return (2, 0, zjedzone)


def odliczania_pojazdu(auto_id, dzis=None) -> list[dict[str, Any]]:
    """Wszystkie odliczania pojazdu od najbliższego. Pozycja to słownik:

    * klucz, rodzaj ("dokument" / "gwarancja_km" / "gwarancja_naprawy" /
      "podzespol" / "przebieg"),
      ikona (klucz ikony), tytul (None przy pozycjach, których nazwa zależy od
      jednostki dystansu), trasa (dokąd prowadzi dotknięcie wiersza);
    * dni — do końca (ujemne: po terminie; None: nie wiadomo, np. kilometry bez
      średniego przebiegu albo już przekroczone), data (koniec; przy
      kilometrach prognozowany), prognoza (czy data jest prognozą);
    * zostalo_km — przy licznikach w kilometrach (ujemne: przekroczone),
      cel_km i od_km — gdzie licznik się kończy i skąd liczy pasek;
    * udzial — jaka część okresu minęła (0–1; None: okres bez początku),
      poczatek i poczatek_z — skąd pasek dokumentu liczy okres;
    * drugi — drugi licznik podzespołu (z db.oblicz_stan_interwalu) albo None;
    * gwarancja — pełny stan gwarancji naprawy (z db.gwarancje_pojazdu) albo None;
    * status — "po_terminie" / "blisko" / "ok" / "info" (okrągły przebieg).

    Sprzedane auto nie ma już czego odliczać — lista jest pusta."""
    if not auto_id:
        return []
    dane = pobierz_dane_pojazdu(auto_id)
    if not dane or str(dane.get("status") or STATUS_POJAZDU_AKTYWNY) == STATUS_POJAZDU_SPRZEDANY:
        return []

    dzis = dzis or datetime.now().date()
    przebieg = pobierz_aktualny_przebieg(auto_id) or 0
    sredni_dzienny = oblicz_sredni_dzienny_przebieg(auto_id) if przebieg else None
    prog_km = pobierz_prog_km()
    prog_dni = pobierz_prog_dni()

    wynik = (
        _dokumenty(auto_id, dane, dzis)
        + _limit_gwarancji(auto_id, dane, przebieg, sredni_dzienny, prog_km, dzis)
        + _gwarancje_napraw(auto_id, przebieg, sredni_dzienny, prog_km, prog_dni, dzis)
        + _podzespoly(auto_id, przebieg, sredni_dzienny, prog_km, prog_dni, dzis)
        + _okragly_przebieg(przebieg, sredni_dzienny, dzis)
    )
    wynik.sort(key=_klucz_kolejnosci)
    return wynik


__all__ = [
    "KROK_OKRAGLEGO_PRZEBIEGU",
    "POCZATEK_REJESTRACJA",
    "POCZATEK_ROK",
    "POCZATEK_ZAKUP",
    "STATUS_INFORMACJI",
    "STATUS_Z_INTERWALU",
    "odliczania_pojazdu",
]
