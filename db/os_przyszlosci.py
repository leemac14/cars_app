"""„Co przede mną” — wspólna oś przyszłości (N-02 w katalogu pomysłów).

Dziennik życia auta pokazuje przeszłość, dzwonek — tylko to, co już weszło
w próg powiadomienia, a „Ile zostało do…” — po jednym odliczaniu na rzecz. Nie
było miejsca, w którym widać cały rok do przodu: co, kiedy i za ile — a to
pytanie zadawane przed urlopem i przed zakupem drugiego auta. Tu stoi jedna
chronologiczna lista w oknie 30, 90 albo 365 dni:

  • terminy dokumentów, limit przebiegu gwarancji, koniec gwarancji napraw
    i okrągły przebieg — prosto z db.odliczania_pojazdu: te same dni, statusy
    i prognozy co w „Ile zostało do…”;
  • podzespoły — pierwsza wymiana też stamtąd, a kolejne dokładamy, zakładając
    wymianę w terminie: co interwał czasu albo co interwał kilometrów
    przeliczony średnim przebiegiem dziennym — co nadejdzie pierwsze;
  • wydatki cykliczne — każde wystąpienie w oknie; po zaległym terminie
    następne liczą się od dziś, bo tak przesuwa termin „Zapłacone”;
  • sezonowa zmiana opon — z przypomnienia, na przemian na zimowe i letnie;
    bez przypomnienia, przy komplecie letnim i zimowym — podpowiedź
    z kalendarza (MIESIACE_ZIMOWE: zimowe od listopada, letnie od kwietnia);
  • leasing i kredyt — każda niezapłacona płatność harmonogramu z jej kwotą
    (raty malejące mają co miesiąc inną);
  • budżety miesięczne i roczne — koniec bieżącego okresu: ile zostało albo
    o ile przekroczony (okno „ostatnie 30 dni” końca nie ma);
  • prognoza kosztu każdego miesiąca w oknie.

Zaległe (termin minął, a sprawa wciąż czeka: polisa, rata, wymiana) stoją na
górze bez względu na okno — to też jest „przede mną”. Skończona gwarancja już
nie: po niej nie ma czego załatwić.

PROGNOZA MIESIĄCA = bieżące + zaplanowane.

  • zaplanowane — kwoty pozycji z tej listy, które wypadają w miesiącu:
    wydatki cykliczne, raty, wymiany podzespołów po cenie ostatniej wymiany
    (szacunek);
  • bieżące — średnia miesięczna z ostatnich do 12 pełnych miesięcy (bieżący
    wykluczony, miesiące sprzed pierwszego wpisu też — jak w prognoza_kosztow)
    wszystkiego, czego NIE ma na liście jako pozycji zaplanowanej: paliwa
    i prądu, innych kosztów, napraw spoza podzespołów z interwałem. Zapłacone
    wydatki cykliczne (kategoria „Cykliczne” albo nazwa wpisu cyklicznego)
    i wymiany podzespołów z interwałem wypadają z tej średniej, bo przyszłe
    stoją na osi z kwotą — inaczej liczyłyby się dwa razy. Dwanaście miesięcy,
    a nie sześć: polisa płacona raz w roku wchodzi do średniej dokładnie raz,
    a nie podwójnie albo wcale.

Miesiąc przecięty brzegiem okna (bieżący — od dziś, ostatni — do końca okna)
dostaje część bieżących proporcjonalną do swoich dni, więc suma miesięcy to
prognoza całego okna.
"""

import calendar
from datetime import date as date_cls, datetime, timedelta
from typing import Any

from date import parsuj_date

from .stale import (
    MIESIACE_ZIMOWE, SEZONY_PRZELACZALNE, STATUS_POJAZDU_AKTYWNY, STATUS_POJAZDU_SPRZEDANY,
    TYP_CYKLICZNY_OPONY,
)
from .polaczenie import polacz_baze
from .pomocnicze import _na_liczbe, klucz_nazwy
from .daty import warunek_zakresu_dat
from .ustawienia import OKNO_PRZYSZLOSCI_DOMYSLNE, pobierz_prog_dni
from .przebieg import oblicz_sredni_dzienny_przebieg, pobierz_aktualny_przebieg
from .raty import KATEGORIA_RATY, OKRES_RATY_DNI, czy_rata, etykieta_umowy, opis_platnosci, pobierz_raty
from .powiadomienia import DNI_W_MIESIACU_INTERWALU
from .pojazd import pobierz_dane_pojazdu
from .magazyn import pobierz_stan_opon
from .analiza import stan_budzetow
from .rejestry import pobierz_wydatki_cykliczne
from .odliczania import STATUS_INFORMACJI, odliczania_pojazdu


# Z ilu ostatnich pełnych miesięcy liczy się średnia bieżących kosztów.
MIESIECY_BAZOWYCH_PROGNOZY = 12

# Bezpiecznik pętli powtórzeń: wpis „co 1 dzień” przez rok to 366 wystąpień.
MAKS_POWTORZEN = 400

# Okno kafelka „Co przede mną” na kokpicie: najbliższy miesiąc. Kafelek ma
# odpowiedzieć „co mnie czeka i ile to kosztuje”, a rok do przodu jest
# jedno dotknięcie dalej.
OKNO_KAFELKA_PRZYSZLOSCI = 30


def _poprzedni_miesiac(miesiac):
    return (miesiac - 2) % 12 + 1


# Pierwszy miesiąc sezonu zimowego i letniego — liczony z MIESIACE_ZIMOWE, żeby
# podpowiedź zmiany opon i kierunek zmiany w magazynie (db._docelowy_sezon)
# znały jeden kalendarz. Dla {11, 12, 1, 2, 3}: listopad i kwiecień.
MIESIAC_OPON_ZIMOWYCH = next(
    m for m in range(1, 13) if m in MIESIACE_ZIMOWE and _poprzedni_miesiac(m) not in MIESIACE_ZIMOWE)
MIESIAC_OPON_LETNICH = next(
    m for m in range(1, 13) if m not in MIESIACE_ZIMOWE and _poprzedni_miesiac(m) in MIESIACE_ZIMOWE)

# Kolejność pozycji z tego samego dnia: najpierw papiery i pieniądze, na końcu
# to, co tylko informuje.
KOLEJNOSC_RODZAJOW = {
    "dokument": 0, "rata": 1, "cykliczny": 2, "opony": 3, "podzespol": 4,
    "gwarancja_naprawy": 5, "gwarancja_km": 6, "budzet": 7, "przebieg": 8,
}


def _dodatnia(wartosc):
    """Liczba całkowita > 0 albo None — puste pole i zero znaczą „nie ustawiono”."""
    try:
        liczba = int(float(wartosc))
    except (TypeError, ValueError):
        return None
    return liczba if liczba > 0 else None


def _liczba(wartosc):
    return _na_liczbe(wartosc) or 0.0


def _pozycja(**pola):
    """Komplet kluczy pozycji osi — ekran i kafelek czytają je bez `.get()`."""
    pozycja = {
        "klucz": None, "rodzaj": None, "ikona": None, "tytul": None,
        "data": None, "dni": None, "zalegla": False,
        "prognoza": False, "najpozniej": False, "zakladana": False, "sugestia": False,
        "kwota": None, "szacunek": False,
        "status": "ok", "trasa": None, "akcja": None,
        "okres_dni": None, "platnosc": None, "budzet": None, "sezon": None,
        "zrodlo": None, "cel_km": None, "zostalo_km": None,
    }
    pozycja.update(pola)
    return pozycja


# ============================================================================
#  POZYCJE Z „ILE ZOSTAŁO DO…”
# ============================================================================

def _granica(odliczanie):
    """Dzień, którego pozycja bez własnej daty na pewno nie przekroczy:
    drugi, czasowy licznik podzespołu (kilometry bez średniego przebiegu
    skończą się najpóźniej razem z nim) albo termin gwarancji naprawy liczonej
    także kilometrami. None, gdy takiej granicy nie ma."""
    drugi = odliczanie.get("drugi")
    if drugi and drugi.get("rodzaj") == "czas" and (drugi.get("zostalo") or 0) >= 0:
        return drugi.get("data")
    gwarancja = odliczanie.get("gwarancja")
    if gwarancja and gwarancja.get("koniec") and (gwarancja.get("dni") or 0) >= 0:
        return gwarancja["koniec"]
    return None


def _z_odliczan(odliczania, dzis, koniec):
    """(pozycje, bez_daty) z odliczań pojazdu. Umowy rat odliczają tam do
    ostatniej raty — na osi stoi zamiast tego każda płatność (_raty)."""
    pozycje, bez_daty = [], []
    for o in odliczania:
        if o["rodzaj"] == "rata":
            continue
        wspolne = dict(
            klucz=o["klucz"], rodzaj=o["rodzaj"], ikona=o["ikona"], tytul=o["tytul"],
            status=o["status"], trasa=o["trasa"], zrodlo=o,
            cel_km=o["cel_km"], zostalo_km=o["zostalo_km"],
        )
        if o["status"] == "po_terminie":
            # Skończona gwarancja (data albo limit przebiegu) to nie sprawa do
            # załatwienia — polisa, przegląd i wymiana już tak.
            if o["ikona"] == "gwarancja":
                continue
            pozycje.append(_pozycja(**wspolne, data=o["data"], dni=o["dni"], zalegla=True,
                                    prognoza=o["prognoza"]))
            continue
        data, najpozniej = o["data"], False
        if data is None:
            data = _granica(o)
            najpozniej = data is not None
        if data is None:
            # Okrągły przebieg bez prognozy po prostu nie wypada; reszta bez
            # daty idzie na koniec listy, żeby nie zniknąć bez śladu.
            if o["rodzaj"] != "przebieg":
                bez_daty.append(_pozycja(**wspolne))
            continue
        if data > koniec:
            continue
        pozycje.append(_pozycja(
            **wspolne, data=data, dni=(data - dzis).days,
            prognoza=bool(o["prognoza"]) and not najpozniej, najpozniej=najpozniej,
        ))
    return pozycje, bez_daty


# ============================================================================
#  PODZESPOŁY: KWOTY I KOLEJNE WYMIANY
# ============================================================================

def _id_zadania(klucz):
    try:
        return int(str(klucz).split(":")[1])
    except (IndexError, ValueError):
        return None


def _zadania_i_ceny(auto_id, identyfikatory):
    """({id: wiersz interwału}, {id: cena ostatniej wymiany > 0}) podzespołów
    z osi. Cena z OSTATNIEGO wpisu z kwotą — kolejność dat robi SQL."""
    if not identyfikatory:
        return {}, {}
    znaki = ", ".join("?" for _ in identyfikatory)
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(f"SELECT id, interwal_km, interwal_miesiace FROM zadania WHERE id IN ({znaki})",
                  tuple(identyfikatory))
        zadania = {w[0]: {"interwal_km": w[1], "interwal_miesiace": w[2]} for w in c.fetchall()}
        c.execute(
            f"SELECT zadanie_id, cena FROM historia WHERE zadanie_id IN ({znaki}) "
            "ORDER BY data_iso, id", tuple(identyfikatory))
        ceny = {}
        for zadanie_id, cena in c.fetchall():
            wartosc = _liczba(cena)
            if wartosc > 0:
                ceny[zadanie_id] = wartosc
    return zadania, ceny


def _okres_wymiany(zadanie, sredni_dzienny):
    """Co ile dni wypada wymiana: interwał czasu albo interwał kilometrów
    przeliczony średnim przebiegiem dziennym — krótszy. None, gdy kilometrów
    nie da się przełożyć na dni (bez średniej): kolejnej daty wtedy nie znamy,
    bo kilometry mogą skończyć się dużo przed czasem."""
    okresy = []
    km = _dodatnia(zadanie.get("interwal_km"))
    if km:
        if not sredni_dzienny or sredni_dzienny <= 0:
            return None
        okresy.append(int(round(km / sredni_dzienny)))
    try:
        dni = int(float(zadanie.get("interwal_miesiace") or 0) * DNI_W_MIESIACU_INTERWALU)
    except (TypeError, ValueError):
        dni = 0
    if dni > 0:
        okresy.append(dni)
    okres = min(okresy) if okresy else None
    return okres if okres and okres > 0 else None


def _podzespoly(pozycje, zadania, ceny, sredni_dzienny, dzis, koniec):
    """Dopisuje pierwszym wymianom cenę ostatniej wymiany i zwraca KOLEJNE
    wymiany w oknie — zakładając każdą w terminie. Po zaległej wymianie
    następna liczy się od dziś (zrobiona dziś, wróci za interwał); po
    terminie „najpóźniej” kolejnej nie ma, bo pierwszej daty nie znamy."""
    kolejne = []
    for p in [p for p in pozycje if p["rodzaj"] == "podzespol"]:
        zadanie_id = _id_zadania(p["klucz"])
        cena = ceny.get(zadanie_id)
        if cena:
            p["kwota"], p["szacunek"] = cena, True
        zadanie = zadania.get(zadanie_id)
        okres = _okres_wymiany(zadanie, sredni_dzienny) if zadanie else None
        if not okres or p["najpozniej"]:
            continue
        if p["zalegla"]:
            nastepna = dzis + timedelta(days=okres)
        elif p["data"] is not None:
            nastepna = p["data"] + timedelta(days=okres)
        else:
            continue
        numer = 1
        while nastepna <= koniec and numer <= MAKS_POWTORZEN:
            kolejne.append(_pozycja(
                klucz=f"{p['klucz']}:{numer}", rodzaj="podzespol", ikona="podzespol",
                tytul=p["tytul"], data=nastepna, dni=(nastepna - dzis).days,
                zakladana=True, prognoza=True, kwota=cena, szacunek=bool(cena),
                trasa=p["trasa"], zrodlo=p["zrodlo"],
            ))
            nastepna += timedelta(days=okres)
            numer += 1
    return kolejne


# ============================================================================
#  WYDATKI CYKLICZNE, OPONY, RATY, BUDŻETY
# ============================================================================

def _przeciwny_sezon(sezon):
    return "Letnie" if sezon == "Zimowe" else "Zimowe"


def _sezon_z_kalendarza(dzien):
    """Na co zmienia się opony w okolicy tego dnia, gdy nie wiadomo, co jest na
    aucie: na sezon, który trwa miesiąc później (koniec października —
    zimowe, koniec marca — letnie)."""
    return "Zimowe" if (dzien + timedelta(days=30)).month in MIESIACE_ZIMOWE else "Letnie"


def _poczatek_sezonu(sezon, od):
    """Najbliższy dzień ≥ `od`, w którym zaczyna się `sezon`."""
    miesiac = MIESIAC_OPON_ZIMOWYCH if sezon == "Zimowe" else MIESIAC_OPON_LETNICH
    kandydat = date_cls(od.year, miesiac, 1)
    return kandydat if kandydat >= od else date_cls(od.year + 1, miesiac, 1)


def _trwa_sezon(sezon, dzien):
    zimowy = dzien.month in MIESIACE_ZIMOWE
    return zimowy if sezon == "Zimowe" else not zimowy


def _wystapienia(pierwsza, okres, dzis, koniec):
    """Daty kolejnych wystąpień wpisu cyklicznego do `koniec`: pierwsza (także
    zaległa) i dalej co okres. Po zaległej następne liczą się od dziś — tak
    przesuwa termin „Zapłacone” (oznacz_zaplacony_wydatek_cykliczny)."""
    if pierwsza > koniec:
        return []
    daty = [pierwsza]
    nastepna = max(pierwsza, dzis) + timedelta(days=okres)
    while nastepna <= koniec and len(daty) < MAKS_POWTORZEN:
        daty.append(nastepna)
        nastepna += timedelta(days=okres)
    return daty


def _cykliczne(wpisy, z_harmonogramem, zamontowany, prog_dni, dzis, koniec):
    """Każde wystąpienie wydatku cyklicznego, przypomnienia i zmiany opon.
    Umowy rat z pełnym harmonogramem pomijamy — ich płatności liczy _raty.
    Status pierwszego wystąpienia tym samym progiem, co dzwonek (ograniczonym
    trzecią częścią własnego okresu), dalsze stoją spokojnie jako „ok”."""
    wynik = []
    for wid, nazwa, kwota, okres_dni, nastepna, czy_koszt, typ in wpisy:
        if wid in z_harmonogramem:
            continue
        pierwsza = parsuj_date(nastepna)
        if not nastepna or pierwsza == datetime.min.date():
            continue
        okres = _dodatnia(okres_dni) or 30
        wlasny_prog = min(prog_dni, max(1, okres // 3))
        kwota_wpisu = _liczba(kwota) if czy_koszt else 0.0
        opony, rata = typ == TYP_CYKLICZNY_OPONY, czy_rata(typ)
        nazwa = str(nazwa or "").strip()
        for indeks, dzien in enumerate(_wystapienia(pierwsza, okres, dzis, koniec)):
            dni = (dzien - dzis).days
            if indeks == 0:
                status = "po_terminie" if dni < 0 else ("blisko" if dni <= wlasny_prog else "ok")
            else:
                status = "ok"
            pola = dict(
                klucz=f"cykliczny:{wid}:{dzien.isoformat()}", data=dzien, dni=dni, zalegla=dni < 0,
                kwota=kwota_wpisu if kwota_wpisu > 0 else None, status=status, okres_dni=okres,
                tytul=nazwa, rodzaj="cykliczny", ikona="cykliczny" if czy_koszt else "przypomnienie",
                akcja="cykliczne",
            )
            if opony:
                # Kierunek z tego, co JEST na aucie (na przemian od pierwszej
                # zmiany), a bez kompletu na aucie — z kalendarza.
                if zamontowany in SEZONY_PRZELACZALNE:
                    sezon = _przeciwny_sezon(zamontowany) if indeks % 2 == 0 else zamontowany
                else:
                    sezon = _sezon_z_kalendarza(dzien)
                pola.update(rodzaj="opony", ikona="opony", sezon=sezon,
                            tytul=f"Zmiana opon na {sezon.lower()}")
            elif rata:
                # Umowa bez kompletu danych do harmonogramu: termin i kwota
                # z wpisu, a dotknięcie prowadzi tam, gdzie się ją uzupełnia.
                pola.update(rodzaj="rata", ikona=typ, tytul=nazwa or etykieta_umowy(typ),
                            akcja=None, trasa="/raty")
            wynik.append(_pozycja(**pola))
    return wynik


def _podpowiedz_opon(stan_opon, ma_przypomnienie, dzis, koniec):
    """Zmiana opon z kalendarza — tylko przy komplecie letnim i zimowym i bez
    ustawionego przypomnienia (z nim zmiana stoi na osi jako wpis cykliczny).
    Kierunek z kompletu na aucie; gdy jego sezon już trwa (letnie w grudniu),
    zmiana jest spóźniona i stoi na dziś w kolorze uwagi."""
    if ma_przypomnienie or not stan_opon:
        return []
    sezony = {z["sezon"] for z in stan_opon["zestawy"]}
    if not all(s in sezony for s in SEZONY_PRZELACZALNE):
        return []
    zamontowany = stan_opon["sezon"]
    if zamontowany in SEZONY_PRZELACZALNE:
        sezon = _przeciwny_sezon(zamontowany)
        spozniona = _trwa_sezon(sezon, dzis)
        dzien = dzis if spozniona else _poczatek_sezonu(sezon, dzis)
    else:
        sezon = min(SEZONY_PRZELACZALNE, key=lambda s: _poczatek_sezonu(s, dzis))
        spozniona, dzien = False, _poczatek_sezonu(sezon, dzis)

    wynik = []
    while dzien <= koniec and len(wynik) < MAKS_POWTORZEN:
        wynik.append(_pozycja(
            klucz=f"opony:podpowiedz:{dzien.isoformat()}", rodzaj="opony", ikona="opony",
            tytul=f"Zmiana opon na {sezon.lower()}", data=dzien, dni=(dzien - dzis).days,
            sugestia=True, sezon=sezon, status="blisko" if spozniona else STATUS_INFORMACJI,
            akcja="opony",
        ))
        sezon = _przeciwny_sezon(sezon)
        dzien, spozniona = _poczatek_sezonu(sezon, dzien + timedelta(days=1)), False
    return wynik


def _raty(umowy, prog_dni, dzis, koniec):
    """(pozycje, id umów z harmonogramem): każda niezapłacona płatność w oknie
    z jej kwotą. Zaległe stoją na górze; pierwsza niezapłacona (ta, o której
    przypomina dzwonek) dostaje status tym samym progiem, co wpis cykliczny."""
    wynik, z_harmonogramem = [], set()
    for umowa in umowy:
        h = umowa["harmonogram"]
        if not h["kompletna"]:
            continue
        z_harmonogramem.add(umowa["id"])
        if h["zakonczona"]:
            continue
        nazwa = str(umowa["nazwa"] or "").strip() or etykieta_umowy(umowa["typ"])
        okres = _dodatnia(umowa.get("okres_dni")) or OKRES_RATY_DNI
        wlasny_prog = min(prog_dni, max(1, okres // 3))
        pierwsza = True
        for p in h["platnosci"]:
            if p["zaplacona"]:
                continue
            if p["data"] > koniec:
                break
            dni = (p["data"] - dzis).days
            if dni < 0:
                status = "po_terminie"
            else:
                status = "blisko" if pierwsza and dni <= wlasny_prog else "ok"
            pierwsza = False
            wynik.append(_pozycja(
                klucz=f"rata:{umowa['id']}:{p['numer']}", rodzaj="rata", ikona=umowa["typ"],
                tytul=nazwa, data=p["data"], dni=dni, zalegla=dni < 0, kwota=p["kwota"],
                status=status, trasa="/raty",
                platnosc=opis_platnosci(umowa["typ"], p, h["liczba_rat"]),
            ))
    return wynik, z_harmonogramem


def _budzety(auto_id, dzis, koniec):
    """Koniec bieżącego okresu każdego budżetu miesięcznego i rocznego, który
    wypada w oknie. Kolor jak na ekranie budżetu: przekroczony — czerwony,
    „uwaga” (80% albo tempo ponad limit) — pomarańczowy."""
    wynik = []
    for b in stan_budzetow(auto_id, dzis):
        if b["ruchomy"] or b["koniec"] > koniec:
            continue
        wynik.append(_pozycja(
            klucz=f"budzet:{b['kategoria']}:{b['okres']}", rodzaj="budzet", ikona="budzet",
            tytul=f"Budżet: {b['etykieta_kategorii']}", data=b["koniec"],
            dni=(b["koniec"] - dzis).days, budzet=b, trasa="/budzet",
            status={"przekroczony": "po_terminie", "uwaga": "blisko"}.get(b["status"], "ok"),
        ))
    return wynik


# ============================================================================
#  PROGNOZA MIESIĘCY
# ============================================================================

def _indeks_miesiaca(dzien):
    return dzien.year * 12 + dzien.month - 1


def _suma_biezacych(c, auto_id, od, do, planowe_zadania, nazwy_cykliczne):
    """Suma kosztów z [od, do], których przyszłe odpowiedniki NIE stoją na osi
    z kwotą: paliwo i prąd, inne koszty bez zapłaconych wpisów cyklicznych,
    naprawy spoza podzespołów z interwałem (z wizyty — reszta po odjęciu ich
    pozycji). Zakres dat w SQL po `data_iso`."""
    warunek, parametry = warunek_zakresu_dat("data_iso", od, do)
    suma = 0.0
    c.execute(f"SELECT kwota FROM tankowania WHERE auto_id=?{warunek}", (auto_id, *parametry))
    suma += sum(_liczba(w[0]) for w in c.fetchall())

    c.execute(f"SELECT kwota, kategoria, nazwa FROM inne_koszty WHERE auto_id=?{warunek}",
              (auto_id, *parametry))
    for kwota, kategoria, nazwa in c.fetchall():
        if str(kategoria or "").strip() == KATEGORIA_RATY or klucz_nazwy(nazwa or "") in nazwy_cykliczne:
            continue
        suma += _liczba(kwota)

    warunek_h, parametry_h = warunek_zakresu_dat("h.data_iso", od, do)
    c.execute("SELECT h.zadanie_id, h.cena FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
              f"WHERE z.auto_id=? AND h.wizyta_id IS NULL{warunek_h}", (auto_id, *parametry_h))
    suma += sum(_liczba(cena) for zadanie_id, cena in c.fetchall() if zadanie_id not in planowe_zadania)

    c.execute(f"SELECT id, koszt_calkowity FROM wizyty WHERE auto_id=?{warunek}", (auto_id, *parametry))
    wizyty = c.fetchall()
    if wizyty:
        warunek_w, parametry_w = warunek_zakresu_dat("w.data_iso", od, do)
        c.execute("SELECT h.wizyta_id, h.zadanie_id, h.cena FROM historia h JOIN wizyty w ON h.wizyta_id=w.id "
                  f"WHERE w.auto_id=?{warunek_w}", (auto_id, *parametry_w))
        planowe = {}
        for wizyta_id, zadanie_id, cena in c.fetchall():
            if zadanie_id in planowe_zadania:
                planowe[wizyta_id] = planowe.get(wizyta_id, 0.0) + _liczba(cena)
        suma += sum(max(0.0, _liczba(koszt) - planowe.get(wizyta_id, 0.0)) for wizyta_id, koszt in wizyty)
    return suma


def _wydano_w_miesiacu(auto_id, dzis):
    """Wszystkie koszty od pierwszego dnia miesiąca do dziś — tak jak liczy je
    reszta aplikacji (_wiersze_kosztow: wizyta zbiorcza jako całość, bez swoich
    pozycji), tylko z zakresem dat w SQL."""
    od = date_cls(dzis.year, dzis.month, 1)
    warunek, parametry = warunek_zakresu_dat("data_iso", od, dzis)
    warunek_h, parametry_h = warunek_zakresu_dat("h.data_iso", od, dzis)
    suma = 0.0
    with polacz_baze() as conn:
        c = conn.cursor()
        for tabela, kolumna in (("tankowania", "kwota"), ("inne_koszty", "kwota"), ("wizyty", "koszt_calkowity")):
            c.execute(f"SELECT {kolumna} FROM {tabela} WHERE auto_id=?{warunek}", (auto_id, *parametry))
            suma += sum(_liczba(w[0]) for w in c.fetchall())
        c.execute("SELECT h.cena FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
                  f"WHERE z.auto_id=? AND h.wizyta_id IS NULL{warunek_h}", (auto_id, *parametry_h))
        suma += sum(_liczba(w[0]) for w in c.fetchall())
    return suma


def _srednia_biezaca(auto_id, dzis, planowe_zadania, nazwy_cykliczne):
    """(średnia miesięczna bieżących kosztów, z ilu pełnych miesięcy) albo None,
    gdy nie ma ani jednego pełnego miesiąca od pierwszego wpisu."""
    biezacy = date_cls(dzis.year, dzis.month, 1)
    koniec_bazy = biezacy - timedelta(days=1)
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT MIN(d) FROM ("
            "SELECT MIN(data_iso) AS d FROM tankowania WHERE auto_id=? AND data_iso > '' "
            "UNION ALL SELECT MIN(data_iso) FROM inne_koszty WHERE auto_id=? AND data_iso > '' "
            "UNION ALL SELECT MIN(data_iso) FROM wizyty WHERE auto_id=? AND data_iso > '' "
            "UNION ALL SELECT MIN(h.data_iso) FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE z.auto_id=? AND h.data_iso > '')",
            (auto_id, auto_id, auto_id, auto_id),
        )
        pierwszy = parsuj_date((c.fetchone() or [None])[0])
        if pierwszy == datetime.min.date():
            return None
        indeks = max(_indeks_miesiaca(pierwszy), _indeks_miesiaca(biezacy) - MIESIECY_BAZOWYCH_PROGNOZY)
        poczatek = date_cls(indeks // 12, indeks % 12 + 1, 1)
        if poczatek > koniec_bazy:
            return None
        suma = _suma_biezacych(c, auto_id, poczatek, koniec_bazy, planowe_zadania, nazwy_cykliczne)
    miesiecy = _indeks_miesiaca(koniec_bazy) - _indeks_miesiaca(poczatek) + 1
    return suma / miesiecy, miesiecy


def _miesiace_okna(pozycje, srednia, wydano, dzis, koniec):
    """Kawałki kalendarzowych miesięcy w oknie z prognozą każdego. Bieżące
    proporcjonalnie do dni kawałka, zaplanowane — kwoty niezaległych pozycji,
    które w nim wypadają."""
    wynik = []
    poczatek = dzis
    while poczatek <= koniec:
        dni_miesiaca = calendar.monthrange(poczatek.year, poczatek.month)[1]
        koniec_miesiaca = date_cls(poczatek.year, poczatek.month, dni_miesiaca)
        do = min(koniec_miesiaca, koniec)
        biezace = srednia * ((do - poczatek).days + 1) / dni_miesiaca if srednia is not None else None
        w_miesiacu = [p for p in pozycje if not p["zalegla"] and p["data"] and poczatek <= p["data"] <= do]
        zaplanowane = sum(p["kwota"] or 0.0 for p in w_miesiacu)
        wynik.append({
            "rok": poczatek.year, "miesiac": poczatek.month, "od": poczatek, "do": do,
            "pelny": poczatek.day == 1 and do == koniec_miesiaca, "biezacy": poczatek == dzis,
            "biezace": biezace, "zaplanowane": zaplanowane, "razem": (biezace or 0.0) + zaplanowane,
            "liczba": len(w_miesiacu), "wydano": wydano if poczatek == dzis else None,
        })
        poczatek = koniec_miesiaca + timedelta(days=1)
    return wynik


# ============================================================================
#  OŚ
# ============================================================================

def _klucz_kolejnosci(p):
    """Zaległe na górze (najdawniejsze pierwsze), dalej od najbliższej daty;
    w obrębie dnia — papiery i pieniądze przed resztą."""
    kolejnosc = KOLEJNOSC_RODZAJOW.get(p["rodzaj"], 9)
    if p["zalegla"]:
        return (0, p["dni"] if p["dni"] is not None else 0, kolejnosc, str(p["tytul"] or ""))
    return (1, p["data"].toordinal(), kolejnosc, str(p["tytul"] or ""))


def _pusta_os(dni_okna, dzis, koniec):
    return {
        "dni": dni_okna, "od": dzis, "do": koniec,
        "pozycje": [], "bez_daty": [], "miesiace": [],
        "srednia_miesieczna": None, "miesiecy_bazowych": 0,
        "podsumowanie": {
            "liczba": 0, "zalegle": 0, "kwota_zalegla": 0.0,
            "zaplanowane": 0.0, "biezace": None, "razem": 0.0,
        },
    }


def os_przyszlosci(auto_id, dni=None, dzis=None) -> dict[str, Any]:
    """Wszystko, co pojazd ma przed sobą w oknie `dni` (domyślnie
    OKNO_PRZYSZLOSCI_DOMYSLNE) dni od `dzis`. Słownik:

    * dni, od, do — okno (do = od + dni);
    * pozycje — lista od zaległych, dalej po dacie. Pozycja to słownik:
      klucz, rodzaj ("dokument" / "gwarancja_km" / "gwarancja_naprawy" /
      "podzespol" / "przebieg" / "cykliczny" / "opony" / "rata" / "budzet"),
      ikona (klucz ikony), tytul (None przy nazwach zależnych od jednostki —
      jak w odliczaniach), data, dni (ujemne: zaległa; None: kilometry po
      terminie), zalegla, prognoza (data z kilometrów), najpozniej (data to
      granica, nie termin), zakladana (kolejna wymiana przy wymianach
      w terminie), sugestia (zmiana opon z kalendarza), kwota (None: bez
      kwoty), szacunek (kwota to cena ostatniej wymiany), status ("po_terminie"
      / "blisko" / "ok" / "info"), trasa albo akcja ("cykliczne" — panel
      wydatków, "opony" — ekran opon), okres_dni (wpis cykliczny), platnosc
      („rata 13 z 48”), budzet (stan z db.stan_budzetow), sezon (zmiana opon),
      zrodlo (pozycja z db.odliczania_pojazdu), cel_km, zostalo_km;
    * bez_daty — podzespoły i limity, których kilometrów bez średniego
      przebiegu nie da się przełożyć na datę;
    * miesiace — kawałki miesięcy w oknie: rok, miesiac, od, do, pelny,
      biezacy, biezace (None bez pełnego miesiąca danych), zaplanowane, razem,
      liczba pozycji, wydano (tylko bieżący: od pierwszego do dziś);
    * srednia_miesieczna, miesiecy_bazowych — skąd bieżące;
    * podsumowanie — liczba, zalegle (ile), kwota_zalegla, zaplanowane,
      biezace (None bez średniej), razem.

    Bez pojazdu i dla sprzedanego auta — pusta oś."""
    dzis = dzis or datetime.now().date()
    dni_okna = _dodatnia(dni) or OKNO_PRZYSZLOSCI_DOMYSLNE
    koniec = dzis + timedelta(days=dni_okna)
    wynik = _pusta_os(dni_okna, dzis, koniec)
    if not auto_id:
        return wynik
    dane = pobierz_dane_pojazdu(auto_id)
    if not dane or str(dane.get("status") or STATUS_POJAZDU_AKTYWNY) == STATUS_POJAZDU_SPRZEDANY:
        return wynik

    pozycje, bez_daty = _z_odliczan(odliczania_pojazdu(auto_id, dzis=dzis), dzis, koniec)

    planowe_zadania = {_id_zadania(p["klucz"]) for p in pozycje + bez_daty if p["rodzaj"] == "podzespol"}
    planowe_zadania.discard(None)
    zadania, ceny = _zadania_i_ceny(auto_id, sorted(planowe_zadania))
    przebieg = pobierz_aktualny_przebieg(auto_id) or 0
    sredni_dzienny = oblicz_sredni_dzienny_przebieg(auto_id) if przebieg else None
    pozycje += _podzespoly(pozycje, zadania, ceny, sredni_dzienny, dzis, koniec)

    prog_dni = pobierz_prog_dni()
    raty, z_harmonogramem = _raty(pobierz_raty(auto_id, dzis=dzis), prog_dni, dzis, koniec)
    pozycje += raty

    wpisy = pobierz_wydatki_cykliczne(auto_id)
    stan_opon = pobierz_stan_opon(auto_id)
    pozycje += _cykliczne(wpisy, z_harmonogramem, stan_opon["sezon"] if stan_opon else None,
                          prog_dni, dzis, koniec)
    pozycje += _podpowiedz_opon(stan_opon, any(w[6] == TYP_CYKLICZNY_OPONY for w in wpisy), dzis, koniec)
    pozycje += _budzety(auto_id, dzis, koniec)
    pozycje.sort(key=_klucz_kolejnosci)

    nazwy_cykliczne = {klucz_nazwy(w[1]) for w in wpisy if str(w[1] or "").strip()}
    baza = _srednia_biezaca(auto_id, dzis, planowe_zadania, nazwy_cykliczne)
    srednia = baza[0] if baza else None
    wydano = _wydano_w_miesiacu(auto_id, dzis)
    miesiace = _miesiace_okna(pozycje, srednia, wydano, dzis, koniec)

    zalegle = [p for p in pozycje if p["zalegla"]]
    kwota_zalegla = sum(p["kwota"] or 0.0 for p in zalegle)
    zaplanowane = sum(m["zaplanowane"] for m in miesiace)
    biezace = sum(m["biezace"] for m in miesiace) if srednia is not None else None
    wynik.update(
        pozycje=pozycje, bez_daty=bez_daty, miesiace=miesiace,
        srednia_miesieczna=srednia, miesiecy_bazowych=baza[1] if baza else 0,
        podsumowanie={
            "liczba": len(pozycje), "zalegle": len(zalegle), "kwota_zalegla": kwota_zalegla,
            "zaplanowane": zaplanowane, "biezace": biezace,
            "razem": zaplanowane + (biezace or 0.0) + kwota_zalegla,
        },
    )
    return wynik


__all__ = [
    "KOLEJNOSC_RODZAJOW",
    "MAKS_POWTORZEN",
    "MIESIAC_OPON_LETNICH",
    "MIESIAC_OPON_ZIMOWYCH",
    "MIESIECY_BAZOWYCH_PROGNOZY",
    "OKNO_KAFELKA_PRZYSZLOSCI",
    "os_przyszlosci",
]
