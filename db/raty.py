"""Harmonogram leasingu i kredytu (M-22). Wpis cykliczny rodzaju „leasing”/„kredyt”
niesie umowę (migracja 49): liczba rat, pierwsza rata, wykup (kredyt: rata balonowa),
kwota finansowania, oprocentowanie (raty malejące lub liczone z oprocentowania).
Harmonogram: każda płatność z datą, kwotą, kapitałem, odsetkami i saldem.
- raty co miesiąc tego samego dnia (31. w krótszym miesiącu — ostatni dzień,
  `dodaj_miesiace`);
- wykup to OSOBNA, ostatnia płatność w terminie ostatniej raty — dopiero on zamyka
  umowę;
- raty równe: stopa z tego, co się płaci (kapitał = wartość bieżąca rat i wykupu), więc
  odsetki = płatności − kapitał;
- raty malejące (tylko kredyt): stała część kapitałowa + odsetki od salda;
- bez kwoty finansowania tylko sumy rat; odsetki i saldo None;
- `zaplacone_platnosci` — zapłacone pozycje od początku; przesuwa je „Zapłacone”,
  poprawia formularz.
`nastepna_data` = termin pierwszej niezapłaconej pozycji, po spłacie pusty napis
(kolumna NOT NULL) — przypomnienie znika samo."""

import sqlite3
from datetime import datetime
from typing import Any

from date import na_iso, parsuj_date

from .stale import (
    MAKS_LICZBA_RAT, RATY_MALEJACE, RATY_ROWNE, TYP_CYKLICZNY_KREDYT, TYP_CYKLICZNY_LEASING,
    TYPY_RAT,
)
from .polaczenie import polacz_baze
from .ustawienia import pobierz_moje_imie
from .synchronizacja import zarejestruj_nagrobek
from .gwarancje import dodaj_miesiace


# Kolumny umowy w `wydatki_cykliczne` (migracja 49), w kolejności z migracji.
KOLUMNY_UMOWY = (
    "liczba_rat", "zaplacone_platnosci", "data_pierwszej_raty", "kwota_finansowania",
    "oplata_wstepna", "wykup", "oprocentowanie", "rodzaj_rat",
)

_KOLUMNY_WPISU = ("id", "auto_id", "nazwa", "kwota", "okres_dni", "nastepna_data", "czy_koszt", "typ") + KOLUMNY_UMOWY

# Zapłacona rata ląduje w Innych kosztach w tej samej kategorii, co każdy
# wydatek cykliczny od zawsze (rejestry.oznacz_zaplacony_wydatek_cykliczny).
KATEGORIA_RATY = "Cykliczne"

# Rata co miesiąc. `okres_dni` wpisu czyta już tylko starsza wersja aplikacji
# i próg przypomnienia (jedna trzecia okresu).
OKRES_RATY_DNI = 30

# Pozycje harmonogramu.
PLATNOSC_RATA = "rata"
PLATNOSC_WYKUP = "wykup"

# Bisekcja miesięcznej stopy: 200 kroków to precyzja daleko poniżej grosza.
_KROKI_BISEKCJI = 200


# ==================== SŁOWA ====================

def czy_rata(typ) -> bool:
    return str(typ or "").strip() in TYPY_RAT


def etykieta_umowy(typ) -> str:
    return "Kredyt" if typ == TYP_CYKLICZNY_KREDYT else "Leasing"


def slowo_wykupu(typ) -> str:
    """Ostatnia, duża płatność: przy leasingu wykup, przy kredycie rata balonowa."""
    return "rata balonowa" if typ == TYP_CYKLICZNY_KREDYT else "wykup"


def opis_platnosci(typ, platnosc, liczba_rat) -> str:
    """„rata 13 z 48” albo „wykup” — do przypomnienia, nazwy kosztu i listy."""
    if platnosc.get("rodzaj") == PLATNOSC_WYKUP:
        return slowo_wykupu(typ)
    return f"rata {platnosc['numer']} z {liczba_rat}"


def nazwa_kosztu_platnosci(umowa, platnosc, liczba_rat) -> str:
    """Nazwa wpisu w Innych kosztach: „Leasing Toyoty — rata 13 z 48”. Numer
    w nazwie, bo na liście kosztów dwanaście identycznych „Rat leasingu” nie
    mówi, której raty brakuje."""
    nazwa = str(umowa.get("nazwa") or "").strip() or etykieta_umowy(umowa.get("typ"))
    return f"{nazwa} — {opis_platnosci(umowa.get('typ'), platnosc, liczba_rat)}"


def opis_postepu_umowy(umowa) -> str:
    """Krótki stan umowy bez kwot: „rata 13 z 48”, „wykup”, „spłacona”."""
    h = umowa.get("harmonogram") or harmonogram_umowy(umowa)
    if not h["kompletna"]:
        return "umowa do uzupełnienia"
    if h["zakonczona"]:
        return "spłacona"
    return opis_platnosci(umowa.get("typ"), h["nastepna"], h["liczba_rat"])


# ==================== RACHUNEK ====================

def _kwota(wartosc):
    """Liczba > 0 albo None — puste pole i zero znaczą „nie ma”."""
    try:
        liczba = float(wartosc)
    except (TypeError, ValueError):
        return None
    return liczba if liczba > 0 else None


def _procent(wartosc):
    """Oprocentowanie roczne w procentach. Zero to prawdziwa wartość (kredyt
    0%), brak to None; ujemne i powyżej 100% to literówka."""
    if wartosc is None or wartosc == "":
        return None
    try:
        liczba = float(wartosc)
    except (TypeError, ValueError):
        return None
    return liczba if 0 <= liczba <= 100 else None


def _liczba_rat(wartosc):
    try:
        liczba = int(float(wartosc))
    except (TypeError, ValueError):
        return None
    return liczba if 1 <= liczba <= MAKS_LICZBA_RAT else None


def rodzaj_rat_umowy(umowa) -> str:
    """Raty malejące tylko przy kredycie — leasing ma zawsze raty równe."""
    rodzaj = str(umowa.get("rodzaj_rat") or "").strip()
    if umowa.get("typ") == TYP_CYKLICZNY_KREDYT and rodzaj == RATY_MALEJACE:
        return RATY_MALEJACE
    return RATY_ROWNE


def kwota_finansowana(umowa):
    """Kapitał, od którego liczą się odsetki: kwota kredytu, a przy leasingu
    wartość auta minus opłata wstępna (wpłacona od razu, więc bez odsetek).
    None, gdy kwoty nie podano albo opłata wstępna ją zjada."""
    wartosc = _kwota(umowa.get("kwota_finansowania"))
    if wartosc is None:
        return None
    if umowa.get("typ") != TYP_CYKLICZNY_KREDYT:
        wartosc -= _kwota(umowa.get("oplata_wstepna")) or 0.0
    return wartosc if wartosc > 0 else None


def rata_rowna(kapital, liczba_rat, oprocentowanie, wykup=0.0):
    """Rata równa przy oprocentowaniu rocznym w procentach, zaokrąglona do
    grosza. Wykup (rata balonowa) zostaje na koniec, więc raty spłacają kapitał
    pomniejszony o jego wartość bieżącą. None bez danych albo gdy wykup
    pokrywa cały kapitał."""
    kapital, n, procent = _kwota(kapital), _liczba_rat(liczba_rat), _procent(oprocentowanie)
    if kapital is None or n is None or procent is None:
        return None
    wykup = _kwota(wykup) or 0.0
    i = procent / 1200
    if i == 0:
        rata = (kapital - wykup) / n
    else:
        dyskonto = (1 + i) ** -n
        rata = (kapital - wykup * dyskonto) * i / (1 - dyskonto)
    rata = round(rata, 2)
    return rata if rata > 0 else None


def _wartosc_biezaca(rata, n, wykup, i):
    if i == 0:
        return rata * n + wykup
    dyskonto = (1 + i) ** -n
    return rata * (1 - dyskonto) / i + wykup * dyskonto


def stopa_z_raty(kapital, liczba_rat, rata, wykup=0.0):
    """Miesięczna stopa, przy której raty i wykup spłacają kapitał co do grosza
    (wewnętrzna stopa umowy). 0 — umowa bez odsetek; None — brak danych albo
    raty z wykupem nie pokrywają nawet kapitału (literówka w którejś kwocie)."""
    kapital, rata, n = _kwota(kapital), _kwota(rata), _liczba_rat(liczba_rat)
    if kapital is None or rata is None or n is None:
        return None
    wykup = _kwota(wykup) or 0.0
    suma = rata * n + wykup
    # Rata zaokrąglona do grosza może zgubić grosz na każdej racie — tyle wolno
    # sumie zabraknąć do kapitału, żeby była umową bez odsetek, a nie błędem.
    if suma <= kapital:
        return 0.0 if kapital - suma <= 0.01 * (n + 1) else None
    dolna, gorna = 0.0, 0.01
    while _wartosc_biezaca(rata, n, wykup, gorna) > kapital:
        gorna *= 2
        if gorna > 10:
            return None
    for _ in range(_KROKI_BISEKCJI):
        srodek = (dolna + gorna) / 2
        if _wartosc_biezaca(rata, n, wykup, srodek) > kapital:
            dolna = srodek
        else:
            gorna = srodek
    return (dolna + gorna) / 2


def _bez_szumu(wartosc):
    """Saldo, które po stu odejmowaniach wyszło -0,000001, to zero."""
    return 0.0 if abs(wartosc) < 0.005 else wartosc


def _szkielet(umowa) -> dict[str, Any]:
    return {
        "kompletna": False, "powod": None, "typ": umowa.get("typ"),
        "rodzaj_rat": rodzaj_rat_umowy(umowa),
        "platnosci": [], "liczba_rat": _liczba_rat(umowa.get("liczba_rat")), "liczba_platnosci": 0,
        "zaplacone": 0, "zaplacone_raty": 0, "zostalo_rat": None,
        "wykup": _kwota(umowa.get("wykup")), "wykup_zaplacony": False,
        "nastepna": None, "zakonczona": False, "po_terminie": 0, "udzial": None,
        "data_pierwszej_raty": None, "data_ostatniej_raty": None,
        "rata": _kwota(umowa.get("kwota")),
        "suma_platnosci": None, "zaplacono": None, "do_splaty": None,
        "kwota_finansowana": kwota_finansowana(umowa),
        "oplata_wstepna": _kwota(umowa.get("oplata_wstepna")) if umowa.get("typ") != TYP_CYKLICZNY_KREDYT else None,
        "odsetki_razem": None, "odsetki_zaplacone": None, "odsetki_do_zaplaty": None,
        "kapital_do_splaty": None, "oprocentowanie": None, "oprocentowanie_z": None,
        "niespojna": False,
    }


def harmonogram_umowy(umowa, dzis=None) -> dict[str, Any]:
    """Pełny harmonogram umowy (wiersz `wydatki_cykliczne` albo pola formularza).
    Klucze:
    - kompletna, powod (czego brakuje);
    - platnosci — [{numer, rodzaj („rata”/„wykup”), data, kwota, kapital, odsetki,
      saldo, zaplacona, po_terminie}]; kapital, odsetki, saldo None bez kwoty
      finansowania;
    - liczba_rat, liczba_platnosci, zaplacone, zaplacone_raty, zostalo_rat, wykup,
      wykup_zaplacony, udzial (0–1);
    - nastepna, zakonczona, po_terminie (ile zaległych); data_pierwszej_raty,
      data_ostatniej_raty; rata (najbliższa);
    - suma_platnosci, zaplacono, do_splaty (zawsze przy komplecie);
    - kwota_finansowana, oplata_wstepna, odsetki_razem, odsetki_zaplacone,
      odsetki_do_zaplaty, kapital_do_splaty (None bez kwoty finansowania);
    - oprocentowanie (roczne, %), oprocentowanie_z („umowa”/„rata”), niespojna (raty z
      wykupem nie pokrywają kapitału)."""
    dzis = dzis or datetime.now().date()
    wynik = _szkielet(umowa)
    n = wynik["liczba_rat"]
    if n is None:
        wynik["powod"] = "Podaj liczbę rat"
        return wynik
    pierwsza = parsuj_date(umowa.get("data_pierwszej_raty"))
    if pierwsza == datetime.min.date():
        wynik["powod"] = "Podaj datę pierwszej raty"
        return wynik

    wykup = wynik["wykup"] or 0.0
    kapital = wynik["kwota_finansowana"]
    procent = _procent(umowa.get("oprocentowanie"))

    if wynik["rodzaj_rat"] == RATY_MALEJACE:
        if kapital is None or procent is None:
            wynik["powod"] = "Raty malejące liczą się z kwoty kredytu i oprocentowania"
            return wynik
        if wykup >= kapital:
            wynik["powod"] = "Rata balonowa nie może pokryć całego kredytu"
            return wynik
        stopa, skad = procent / 1200, "umowa"
        czesc_kapitalowa = (kapital - wykup) / n
        kwoty, odsetki, saldo = [], [], kapital
        for _ in range(n):
            odsetki.append(saldo * stopa)
            kwoty.append(czesc_kapitalowa + odsetki[-1])
            saldo -= czesc_kapitalowa
    else:
        rata = _kwota(umowa.get("kwota"))
        if rata is None and kapital is not None and procent is not None:
            rata = rata_rowna(kapital, n, procent, wykup)
        if rata is None:
            wynik["powod"] = "Podaj kwotę raty albo kwotę finansowania z oprocentowaniem"
            return wynik
        kwoty = [rata] * n
        stopa = stopa_z_raty(kapital, n, rata, wykup) if kapital is not None else None
        skad = None if stopa is None else ("umowa" if procent is not None else "rata")
        wynik["niespojna"] = kapital is not None and stopa is None
        odsetki = None
        if stopa is not None:
            odsetki, saldo = [], kapital
            for kwota in kwoty:
                odsetki.append(saldo * stopa)
                saldo -= kwota - odsetki[-1]

    platnosci = []
    saldo = kapital if odsetki is not None else None
    for j in range(n):
        o = odsetki[j] if odsetki is not None else None
        kapitalowa = kwoty[j] - o if o is not None else None
        if saldo is not None:
            saldo = _bez_szumu(saldo - kapitalowa)
        platnosci.append({
            "numer": j + 1, "rodzaj": PLATNOSC_RATA, "data": dodaj_miesiace(pierwsza, j),
            "kwota": kwoty[j], "kapital": kapitalowa, "odsetki": o, "saldo": saldo,
        })
    if wykup > 0:
        znane = odsetki is not None
        platnosci.append({
            "numer": n + 1, "rodzaj": PLATNOSC_WYKUP, "data": platnosci[-1]["data"], "kwota": wykup,
            "kapital": wykup if znane else None, "odsetki": 0.0 if znane else None,
            "saldo": 0.0 if znane else None,
        })

    zaplacone = max(0, min(int(_kwota(umowa.get("zaplacone_platnosci")) or 0), len(platnosci)))
    for p in platnosci:
        p["zaplacona"] = p["numer"] <= zaplacone
        p["po_terminie"] = not p["zaplacona"] and p["data"] < dzis
    nastepna = platnosci[zaplacone] if zaplacone < len(platnosci) else None
    nastepna_rata = next((p for p in platnosci[zaplacone:] if p["rodzaj"] == PLATNOSC_RATA), None)

    suma = sum(p["kwota"] for p in platnosci)
    zaplacono = sum(p["kwota"] for p in platnosci[:zaplacone])
    wynik.update(
        kompletna=True, platnosci=platnosci, liczba_platnosci=len(platnosci),
        zaplacone=zaplacone, zaplacone_raty=min(zaplacone, n), zostalo_rat=n - min(zaplacone, n),
        wykup_zaplacony=wykup > 0 and zaplacone > n,
        nastepna=nastepna, zakonczona=nastepna is None,
        po_terminie=sum(1 for p in platnosci if p["po_terminie"]),
        udzial=zaplacone / len(platnosci),
        data_pierwszej_raty=pierwsza, data_ostatniej_raty=platnosci[n - 1]["data"],
        rata=(nastepna_rata or platnosci[n - 1])["kwota"],
        suma_platnosci=suma, zaplacono=zaplacono, do_splaty=_bez_szumu(suma - zaplacono),
    )
    if odsetki is not None:
        razem = sum(p["odsetki"] for p in platnosci)
        zaplacone_odsetki = sum(p["odsetki"] for p in platnosci[:zaplacone])
        wynik.update(
            odsetki_razem=razem, odsetki_zaplacone=zaplacone_odsetki,
            odsetki_do_zaplaty=_bez_szumu(razem - zaplacone_odsetki),
            kapital_do_splaty=platnosci[zaplacone - 1]["saldo"] if zaplacone else kapital,
            oprocentowanie=stopa * 1200, oprocentowanie_z=skad,
        )
    return wynik


def sugerowane_zaplacone(data_pierwszej_raty, liczba_rat, dzis=None) -> int:
    """Ile rat ma termin PRZED dzisiejszym dniem — podpowiedź „zapłacone” przy
    zakładaniu umowy, która trwa od dawna. Rata z terminem dziś jeszcze czeka."""
    dzis = dzis or datetime.now().date()
    n = _liczba_rat(liczba_rat)
    pierwsza = parsuj_date(data_pierwszej_raty)
    if n is None or pierwsza == datetime.min.date():
        return 0
    zaplacone = 0
    while zaplacone < n and dodaj_miesiace(pierwsza, zaplacone) < dzis:
        zaplacone += 1
    return zaplacone


# ==================== BAZA ====================

def _stan_wpisu(umowa, harmonogram):
    """(nastepna_data, kwota) wpisu po zmianie umowy: termin pierwszej niezapłaconej
    pozycji, po spłacie pusty napis (NOT NULL); kwota — rata (przy malejących najbliższa
    — tyle zapłaci starsza wersja aplikacji)."""
    nastepna = harmonogram["nastepna"]
    data = nastepna["data"].strftime("%d.%m.%Y") if nastepna else ""
    kwota = harmonogram["rata"] if harmonogram["kompletna"] else _kwota(umowa.get("kwota"))
    return data, round(float(kwota or 0.0), 2)


def wczytaj_umowe(wydatek_id, conn=None) -> dict[str, Any] | None:
    """Wpis cykliczny (każdego rodzaju — formularz umowy przestawia na raty
    także zwykły wydatek) jako słownik albo None."""
    if not wydatek_id:
        return None
    zapytanie = f"SELECT {', '.join(_KOLUMNY_WPISU)} FROM wydatki_cykliczne WHERE id=?"
    if conn is not None:
        kursor = conn.cursor()
        kursor.row_factory = sqlite3.Row
        wiersz = kursor.execute(zapytanie, (wydatek_id,)).fetchone()
        return dict(wiersz) if wiersz else None
    with polacz_baze() as polaczenie:
        return wczytaj_umowe(wydatek_id, conn=polaczenie)


def _klucz_kolejnosci_umowy(umowa):
    """Trwające od najbliższej płatności, potem do uzupełnienia, spłacone na końcu."""
    h = umowa["harmonogram"]
    if h["kompletna"] and not h["zakonczona"]:
        return (0, h["nastepna"]["data"].toordinal(), umowa["id"])
    if not h["kompletna"]:
        return (1, 0, umowa["id"])
    return (2, -h["data_ostatniej_raty"].toordinal(), umowa["id"])


def pobierz_raty(auto_id, dzis=None) -> list[dict[str, Any]]:
    """Umowy leasingu i kredytu pojazdu: wiersz wpisu plus `harmonogram`
    (harmonogram_umowy). Trwające od najbliższej płatności, spłacone na końcu."""
    if not auto_id:
        return []
    with polacz_baze() as conn:
        kursor = conn.cursor()
        kursor.row_factory = sqlite3.Row
        kursor.execute(
            f"SELECT {', '.join(_KOLUMNY_WPISU)} FROM wydatki_cykliczne "
            f"WHERE auto_id=? AND typ IN ({', '.join('?' * len(TYPY_RAT))})",
            (auto_id, *TYPY_RAT),
        )
        umowy = [dict(w) for w in kursor.fetchall()]
    for umowa in umowy:
        umowa["harmonogram"] = harmonogram_umowy(umowa, dzis)
    umowy.sort(key=_klucz_kolejnosci_umowy)
    return umowy


def podsumowanie_rat(auto_id, dzis=None) -> dict[str, Any] | None:
    """Wszystkie umowy pojazdu w jednej liczbie (kafelek, Karta pojazdu, porównanie);
    None bez umów. Sumy z umów TRWAJĄCYCH; odsetki i kapitał None, gdy którejś brak
    kwoty finansowania."""
    umowy = pobierz_raty(auto_id, dzis)
    if not umowy:
        return None
    trwajace = [u["harmonogram"] for u in umowy
                if u["harmonogram"]["kompletna"] and not u["harmonogram"]["zakonczona"]]

    def suma(klucz):
        wartosci = [h[klucz] for h in trwajace]
        if not wartosci or any(w is None for w in wartosci):
            return None
        return sum(wartosci)

    najblizsza = None
    if trwajace:
        umowa = next(u for u in umowy if u["harmonogram"] is trwajace[0])
        h = trwajace[0]
        najblizsza = {"id": umowa["id"], "nazwa": umowa["nazwa"], "typ": umowa["typ"],
                      "data": h["nastepna"]["data"], "kwota": h["nastepna"]["kwota"],
                      "opis": opis_platnosci(umowa["typ"], h["nastepna"], h["liczba_rat"])}
    return {
        "umowy": umowy,
        "liczba_umow": len(umowy),
        "trwajace": len(trwajace),
        "splacone": sum(1 for u in umowy if u["harmonogram"]["zakonczona"]),
        "niekompletne": sum(1 for u in umowy if not u["harmonogram"]["kompletna"]),
        "do_splaty": sum(h["do_splaty"] for h in trwajace),
        "odsetki_do_zaplaty": suma("odsetki_do_zaplaty"),
        "kapital_do_splaty": suma("kapital_do_splaty"),
        "zaplacone_raty": sum(h["zaplacone_raty"] for h in trwajace),
        "liczba_rat": sum(h["liczba_rat"] for h in trwajace),
        "udzial": (sum(h["zaplacone"] for h in trwajace) / sum(h["liczba_platnosci"] for h in trwajace)
                   if trwajace else None),
        "data_konca": max((h["data_ostatniej_raty"] for h in trwajace), default=None),
        "po_terminie": sum(h["po_terminie"] for h in trwajace),
        "najblizsza": najblizsza,
    }


def zapisz_umowe_raty(auto_id, pola, wydatek_id=None, dzis=None) -> int | None:
    """Zapis z formularza umowy: nowy wpis albo przestawienie istniejącego —
    także zwykłego wydatku, którym rata była do tej pory — na raty. Termin
    przypomnienia i kwota wpisu wynikają z harmonogramu. Zwraca id wpisu."""
    if not auto_id:
        return None
    typ = pola.get("typ") if czy_rata(pola.get("typ")) else TYP_CYKLICZNY_LEASING
    # Data jak każda inna data wpisu cyklicznego: dd.mm.rrrr, niezależnie od
    # tego, w jakim formacie przyszła (stary wpis, import, chmura).
    pierwsza = parsuj_date(pola.get("data_pierwszej_raty"))
    umowa = {
        "typ": typ,
        "nazwa": str(pola.get("nazwa") or "").strip() or etykieta_umowy(typ),
        "kwota": _kwota(pola.get("kwota")),
        "liczba_rat": _liczba_rat(pola.get("liczba_rat")),
        "zaplacone_platnosci": max(0, int(_kwota(pola.get("zaplacone_platnosci")) or 0)),
        "data_pierwszej_raty": pierwsza.strftime("%d.%m.%Y") if pierwsza != datetime.min.date() else None,
        "kwota_finansowania": _kwota(pola.get("kwota_finansowania")),
        "oplata_wstepna": _kwota(pola.get("oplata_wstepna")) if typ == TYP_CYKLICZNY_LEASING else None,
        "wykup": _kwota(pola.get("wykup")),
        "oprocentowanie": _procent(pola.get("oprocentowanie")),
        "rodzaj_rat": RATY_MALEJACE if (typ == TYP_CYKLICZNY_KREDYT and pola.get("rodzaj_rat") == RATY_MALEJACE)
        else RATY_ROWNE,
    }
    harmonogram = harmonogram_umowy(umowa, dzis)
    umowa["zaplacone_platnosci"] = harmonogram["zaplacone"] if harmonogram["kompletna"] else 0
    nastepna_data, kwota = _stan_wpisu(umowa, harmonogram)
    wartosci = (typ, umowa["nazwa"], kwota, OKRES_RATY_DNI, nastepna_data, 1) + tuple(
        umowa[k] for k in KOLUMNY_UMOWY)
    kolumny = ("typ", "nazwa", "kwota", "okres_dni", "nastepna_data", "czy_koszt") + KOLUMNY_UMOWY
    with polacz_baze() as conn:
        if wydatek_id:
            kursor = conn.execute(
                f"UPDATE wydatki_cykliczne SET {', '.join(f'{k}=?' for k in kolumny)} WHERE id=? AND auto_id=?",
                wartosci + (wydatek_id, auto_id),
            )
            return wydatek_id if kursor.rowcount else None
        kursor = conn.execute(
            f"INSERT INTO wydatki_cykliczne (auto_id, {', '.join(kolumny)}) VALUES ({', '.join('?' * (len(kolumny) + 1))})",
            (auto_id,) + wartosci,
        )
        return kursor.lastrowid


def zaplac_rate(conn, wydatek_id, auto_id, dzis=None) -> dict[str, Any] | None:
    """„Zapłacone” przy racie: KOLEJNA pozycja harmonogramu → Inne koszty (kwota z
    harmonogramu, nazwa z numerem), licznik +1, termin przechodzi na następną (po
    wykupie znika). Data kosztu = termin raty, chyba że płaci się przed nim. W
    transakcji wołającego (rejestry.oznacz_zaplacony_wydatek_cykliczny); zwraca jak ona
    plus platnosc, liczba_rat, zostalo_rat, do_splaty, zakonczona i cofnij. Umowa
    niekompletna lub spłacona — bez zmian."""
    dzis = dzis or datetime.now().date()
    umowa = wczytaj_umowe(wydatek_id, conn=conn)
    if not umowa:
        return None
    przed = harmonogram_umowy(umowa, dzis)
    wynik = {
        "typ": umowa["typ"], "nazwa": str(umowa["nazwa"] or ""), "czy_koszt": False,
        "nastepna_data": umowa["nastepna_data"], "opony": None, "platnosc": None,
        "liczba_rat": przed["liczba_rat"], "zostalo_rat": przed["zostalo_rat"],
        "do_splaty": przed["do_splaty"], "zakonczona": przed["zakonczona"],
        "kompletna": przed["kompletna"], "cofnij": None,
    }
    platnosc = przed["nastepna"]
    if not przed["kompletna"] or platnosc is None:
        return wynik

    data_wpisu = min(dzis, platnosc["data"]).strftime("%d.%m.%Y")
    kursor = conn.execute(
        "INSERT INTO inne_koszty (auto_id, data, data_iso, kategoria, nazwa, kwota, dodane_przez) VALUES (?,?,?,?,?,?,?)",
        (auto_id, data_wpisu, na_iso(data_wpisu), KATEGORIA_RATY,
         nazwa_kosztu_platnosci(umowa, platnosc, przed["liczba_rat"]), round(platnosc["kwota"], 2),
         pobierz_moje_imie()),
    )
    koszt_id = kursor.lastrowid
    po = harmonogram_umowy({**umowa, "zaplacone_platnosci": przed["zaplacone"] + 1}, dzis)
    nastepna_data, kwota = _stan_wpisu(umowa, po)
    conn.execute(
        "UPDATE wydatki_cykliczne SET zaplacone_platnosci=?, nastepna_data=?, kwota=? WHERE id=?",
        (po["zaplacone"], nastepna_data, kwota, wydatek_id),
    )
    wynik.update(
        czy_koszt=True, nastepna_data=nastepna_data,
        platnosc={"numer": platnosc["numer"], "rodzaj": platnosc["rodzaj"], "kwota": platnosc["kwota"],
                  "data": platnosc["data"]},
        zostalo_rat=po["zostalo_rat"], do_splaty=po["do_splaty"], zakonczona=po["zakonczona"],
        cofnij={"wydatek_id": wydatek_id, "koszt_id": koszt_id, "zaplacone": przed["zaplacone"],
                "nastepna_data": umowa["nastepna_data"], "kwota": umowa["kwota"]},
    )
    return wynik


def cofnij_platnosc_raty(cofniecie) -> bool:
    """Odwraca jedno „Zapłacone” przy racie: licznik, termin i kwota wracają,
    koszt znika (z nagrobkiem, jeśli zdążył pojechać do chmury). Tylko wtedy,
    gdy licznik stoi tam, gdzie zostawiła go ta płatność — po następnej
    płatności albo poprawce w formularzu cofnięcie niczego nie rusza."""
    if not cofniecie:
        return False
    with polacz_baze() as conn:
        kursor = conn.cursor()
        wiersz = kursor.execute("SELECT zaplacone_platnosci FROM wydatki_cykliczne WHERE id=?",
                                (cofniecie["wydatek_id"],)).fetchone()
        if not wiersz or int(wiersz[0] or 0) != int(cofniecie["zaplacone"]) + 1:
            return False
        conn.execute(
            "UPDATE wydatki_cykliczne SET zaplacone_platnosci=?, nastepna_data=?, kwota=? WHERE id=?",
            (cofniecie["zaplacone"], cofniecie["nastepna_data"], cofniecie["kwota"], cofniecie["wydatek_id"]),
        )
        koszt = kursor.execute("SELECT zdalne_id, auto_id FROM inne_koszty WHERE id=?",
                               (cofniecie["koszt_id"],)).fetchone()
        conn.execute("DELETE FROM inne_koszty WHERE id=?", (cofniecie["koszt_id"],))
    if koszt and koszt[0]:
        zarejestruj_nagrobek("inne_koszty", koszt[0], koszt[1])
    return True


__all__ = [
    "KATEGORIA_RATY",
    "KOLUMNY_UMOWY",
    "OKRES_RATY_DNI",
    "PLATNOSC_RATA",
    "PLATNOSC_WYKUP",
    "cofnij_platnosc_raty",
    "czy_rata",
    "etykieta_umowy",
    "harmonogram_umowy",
    "kwota_finansowana",
    "nazwa_kosztu_platnosci",
    "opis_platnosci",
    "opis_postepu_umowy",
    "pobierz_raty",
    "podsumowanie_rat",
    "rata_rowna",
    "rodzaj_rat_umowy",
    "slowo_wykupu",
    "stopa_z_raty",
    "sugerowane_zaplacone",
    "wczytaj_umowe",
    "zapisz_umowe_raty",
    "zaplac_rate",
]
