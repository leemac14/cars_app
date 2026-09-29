"""Gwarancja na wykonaną naprawę — dwa limity przy wpisie historii serwisowej.

Gwarancja na całe auto siedzi w terminach pojazdu, ale to gwarancja na CZĘŚĆ
decyduje, czy za powtórną wymianę płaci się drugi raz — a przy sprzedaży auta
jest argumentem. Wpis historii (także pozycja wizyty zbiorczej) niesie dwa
limity: `gwarancja_data` (DD.MM.RRRR, jak data wpisu) i `gwarancja_przebieg`
(stan licznika w km, do którego gwarancja obowiązuje). Kończy ją to, co
przyjdzie pierwsze — tak jak gwarancję producenta.

Tu i tylko tu liczy się:
  • stan jednej gwarancji (`stan_gwarancji`) — ile zostało, czy już minęła
    i czy weszła w próg przypomnienia (te same progi, co podzespoły);
  • gwarancje pojazdu (`gwarancje_pojazdu`) — po jednej na podzespół, z jego
    OSTATNIEJ wymiany. Część z wcześniejszej wymiany w aucie już nie siedzi,
    więc jej gwarancja niczego nie chroni. Kolejność wymian ta sama, co
    w `aktualizuj_najnowszy_wpis`: data, potem licznik;
  • słowa („gwarancja jeszcze 8 miesięcy”) — wspólne dla kart, dzwonka,
    „Ile zostało do…” i paszportu PDF, żeby wszędzie brzmiały tak samo.
"""

import calendar
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from date import parsuj_date

from .polaczenie import polacz_baze
from .pomocnicze import liczba_z_odmiana
from .ustawienia import pobierz_moje_imie, pobierz_prog_dni, pobierz_prog_km
from .jednostki import tekst_dystansu
from .przebieg import oblicz_sredni_dzienny_przebieg, pobierz_aktualny_przebieg


# Statusy jak w „Ile zostało do…”: w progu przypomnienia — „blisko”, po końcu —
# „po_terminie”. Koniec gwarancji nie jest usterką, więc ekrany malują go
# kolorem neutralnym, a nie czerwienią (patrz utils/gwarancja.py).
STATUS_GWARANCJI_OK = "ok"
STATUS_GWARANCJI_BLISKO = "blisko"
STATUS_GWARANCJI_PO_TERMINIE = "po_terminie"

# Skróty w formularzu: miesiące od daty wymiany i dystans od przebiegu wymiany
# w jednostce z Ustawień (20 tysięcy mil, a nie 32 187 km).
OKRESY_GWARANCJI_MIESIACE = (6, 12, 24, 36)
DYSTANSE_GWARANCJI = (10000, 20000, 30000)

# Do dwóch miesięcy „jeszcze 45 dni” mówi więcej niż „jeszcze 1 miesiąc”.
DNI_GWARANCJI_W_DNIACH = 60


# ============================================================================
#  DATY I OKRESY
# ============================================================================

def _data(wartosc):
    """date albo None — z tekstu w każdym formacie, który czyta lista."""
    if isinstance(wartosc, datetime):
        return wartosc.date()
    if isinstance(wartosc, date):
        return wartosc
    dzien = parsuj_date(wartosc)
    return None if dzien == datetime.min.date() else dzien


def _dodatnia(wartosc):
    """Liczba całkowita > 0 albo None — puste pole i zero znaczą „nie ustawiono”."""
    try:
        liczba = int(float(wartosc))
    except (TypeError, ValueError):
        return None
    return liczba if liczba > 0 else None


def dodaj_miesiace(dzien, miesiace) -> date:
    """Ten sam dzień N miesięcy później. Dnia, którego w tamtym miesiącu nie ma,
    nie przeskakujemy: 31 stycznia + 1 miesiąc to ostatni dzień lutego."""
    indeks = dzien.month - 1 + int(miesiace)
    rok, miesiac = dzien.year + indeks // 12, indeks % 12 + 1
    return date(rok, miesiac, min(dzien.day, calendar.monthrange(rok, miesiac)[1]))


def okres_gwarancji(koniec, data_wymiany) -> int | None:
    """Ile miesięcy od wymiany do końca gwarancji — tylko wtedy, gdy koniec
    wypada DOKŁADNIE N miesięcy po wymianie (24 miesiące, 2 lata). Przy każdej
    innej dacie None: 731 dni to nie okres gwarancji, tylko data z faktury."""
    koniec, start = _data(koniec), _data(data_wymiany)
    if not koniec or not start or koniec <= start:
        return None
    miesiace = (koniec.year - start.year) * 12 + koniec.month - start.month
    return miesiace if miesiace > 0 and dodaj_miesiace(start, miesiace) == koniec else None


def _pelne_miesiace(od, do):
    """Pełne miesiące kalendarzowe od `od` do `do` (do >= od)."""
    miesiace = (do.year - od.year) * 12 + do.month - od.month
    if miesiace > 0 and dodaj_miesiace(od, miesiace) > do:
        miesiace -= 1
    return max(0, miesiace)


def czas_slownie(od, do) -> str:
    """„45 dni”, „7 miesięcy”, „2 lata i 3 miesiące” — ile czasu od `od` do `do`.
    Miesiące PEŁNE, czyli w dół: gwarancja „na 8 miesięcy”, która ma siedem
    i pół, obiecywałaby dwa tygodnie, których nie ma."""
    dni = (do - od).days
    if dni <= DNI_GWARANCJI_W_DNIACH:
        return liczba_z_odmiana(dni, "dzień", "dni", "dni")
    miesiace = _pelne_miesiace(od, do)
    if miesiace < 24:
        return liczba_z_odmiana(miesiace, "miesiąc", "miesiące", "miesięcy")
    lata, reszta = divmod(miesiace, 12)
    tekst = liczba_z_odmiana(lata, "rok", "lata", "lat")
    if reszta:
        tekst += " i " + liczba_z_odmiana(reszta, "miesiąc", "miesiące", "miesięcy")
    return tekst


# ============================================================================
#  STAN JEDNEJ GWARANCJI
# ============================================================================

def stan_gwarancji(koniec, limit_km, data_wymiany=None, przebieg_wymiany=None,
                   aktualny_przebieg=None, sredni_dzienny=None, dzis=None,
                   prog_dni=None, prog_km=None) -> dict[str, Any] | None:
    """Stan gwarancji jednej naprawy albo None, gdy naprawa gwarancji nie ma.

    `koniec` — data końca (tekst jak w bazie albo date), `limit_km` — stan
    licznika w km. Nieczytelna data i limit ≤ 0 znaczą „nie ustawiono”.

    Słownik:
      * koniec (date|None), limit_km (int|None), data_wymiany (date|None),
        przebieg_wymiany (int|None);
      * dni — do końca terminu (ujemne: minął), None bez daty;
      * zostalo_km — do limitu przy dzisiejszym liczniku (ujemne: przekroczony),
        None bez limitu albo bez znanego przebiegu; dni_km i data_km —
        prognoza dojechania do limitu ze średniego przebiegu dziennego;
      * dni_do_konca — do końca wynikowego (bliższy z terminu i prognozy),
        pierwsze — który limit skończy się pierwszy ("data" / "przebieg");
      * wygasla — minął termin ALBO przekroczono limit, powod — co ją
        zakończyło; blisko_przez — który limit wszedł w próg przypomnienia;
      * status — "ok" / "blisko" / "po_terminie";
      * udzial — jaka część okresu gwarancji minęła (0–1), None bez początku.

    Dzień końca jeszcze się liczy (jak termin dokumentu, który „mija dziś”)."""
    koniec_d = _data(koniec)
    limit = _dodatnia(limit_km)
    if koniec_d is None and limit is None:
        return None
    dzis = dzis or datetime.now().date()
    prog_dni = pobierz_prog_dni() if prog_dni is None else prog_dni
    prog_km = pobierz_prog_km() if prog_km is None else prog_km
    start = _data(data_wymiany)
    start_km = _dodatnia(przebieg_wymiany)
    teraz_km = _dodatnia(aktualny_przebieg)

    dni = (koniec_d - dzis).days if koniec_d else None
    zostalo_km = limit - teraz_km if limit and teraz_km else None
    dni_km = data_km = None
    if zostalo_km is not None and zostalo_km >= 0 and sredni_dzienny and sredni_dzienny > 0:
        dni_km = int(round(zostalo_km / sredni_dzienny))
        data_km = dzis + timedelta(days=dni_km)

    po_dacie = dni is not None and dni < 0
    po_km = zostalo_km is not None and zostalo_km < 0
    wygasla = po_dacie or po_km
    # Oba limity za nami: winna jest data — ją znamy co do dnia, a chwili
    # przekroczenia kilometrów baza nie zna.
    powod = "data" if po_dacie else ("przebieg" if po_km else None)

    blisko_przez = None
    if not wygasla:
        if dni is not None and dni <= prog_dni:
            blisko_przez = "data"
        elif zostalo_km is not None and zostalo_km <= prog_km:
            blisko_przez = "przebieg"

    # Kilometry bez średniego przebiegu nie mają daty, więc z terminem porównać
    # się ich nie da — wtedy o końcu mówi data, jeśli jest.
    pierwsze = "data" if dni is not None and (dni_km is None or dni <= dni_km) else "przebieg"
    kandydaci = [d for d in (dni, dni_km) if d is not None]

    udzialy = []
    if koniec_d and start and koniec_d > start:
        udzialy.append((dzis - start).days / (koniec_d - start).days)
    if limit and start_km and teraz_km and limit > start_km:
        udzialy.append((teraz_km - start_km) / (limit - start_km))
    if wygasla:
        udzial = 1.0
    else:
        udzial = max(0.0, min(1.0, max(udzialy))) if udzialy else None

    if wygasla:
        status = STATUS_GWARANCJI_PO_TERMINIE
    elif blisko_przez:
        status = STATUS_GWARANCJI_BLISKO
    else:
        status = STATUS_GWARANCJI_OK

    return {
        "koniec": koniec_d, "limit_km": limit, "data_wymiany": start, "przebieg_wymiany": start_km,
        "dni": dni, "zostalo_km": zostalo_km, "dni_km": dni_km, "data_km": data_km,
        "dni_do_konca": min(kandydaci) if kandydaci else None, "pierwsze": pierwsze,
        "wygasla": wygasla, "powod": powod, "blisko_przez": blisko_przez,
        "status": status, "udzial": udzial,
    }


def bledy_gwarancji(koniec, limit_km, data_wymiany=None, przebieg_wymiany=None) -> dict[str, str]:
    """Błędy pól gwarancji: {"data": …, "przebieg": …}, pusty słownik, gdy wszystko
    się zgadza. Gwarancja kończy się PO dniu wymiany, a jej limit stoi wyżej niż
    licznik przy wymianie — inaczej nie ma czego chronić, a pomyłka (rok
    w dacie, zero za dużo w limicie) wyszłaby dopiero po zapisie."""
    bledy = {}
    koniec_d, start = _data(koniec), _data(data_wymiany)
    if koniec_d and start and koniec_d <= start:
        bledy["data"] = "Gwarancja musi kończyć się po dniu wymiany"
    if limit_km is not None:
        start_km = _dodatnia(przebieg_wymiany)
        if _dodatnia(limit_km) is None:
            bledy["przebieg"] = "Błędny przebieg"
        elif start_km and _dodatnia(limit_km) <= start_km:
            bledy["przebieg"] = "Limit musi być wyższy niż przebieg przy wymianie"
    return bledy


def klucz_gwarancji(koniec, limit_km) -> tuple[str | None, int | None]:
    """Gwarancja w postaci do porównań i do zapisu: data DD.MM.RRRR (albo None)
    i limit w km (albo None) — „2027-05-12” i „12.05.2027” to ta sama gwarancja,
    a zero w limicie to jego brak."""
    koniec_d = _data(koniec)
    return (koniec_d.strftime("%d.%m.%Y") if koniec_d else None, _dodatnia(limit_km))


def przesun_gwarancje(koniec, limit_km, data_zrodla, przebieg_zrodla, nowa_data, nowy_przebieg) -> dict[str, Any]:
    """Gwarancja duplikatu: ten sam OKRES od nowej wymiany, nie ta sama data.

    Zwraca {"koniec": tekst|None, "limit_km": int|None, "miesiace": int|None,
    "dystans_km": int|None}. Dwa ostatnie to okres, który formularz trzyma przy
    wymianie — zmiana jej daty albo licznika przesuwa wtedy gwarancję dalej.
    Gwarancji bez czytelnej daty albo licznika źródła nie da się przesunąć,
    więc duplikat jej nie dostaje (stara data kłamałaby już od pierwszego dnia)."""
    wynik = {"koniec": None, "limit_km": None, "miesiace": None, "dystans_km": None}
    koniec_d, start, nowa = _data(koniec), _data(data_zrodla), _data(nowa_data)
    if koniec_d and start and nowa and koniec_d > start:
        miesiace = okres_gwarancji(koniec_d, start)
        nowy_koniec = dodaj_miesiace(nowa, miesiace) if miesiace else nowa + (koniec_d - start)
        wynik.update(koniec=nowy_koniec.strftime("%d.%m.%Y"), miesiace=miesiace)
    limit, start_km, nowy_km = _dodatnia(limit_km), _dodatnia(przebieg_zrodla), _dodatnia(nowy_przebieg)
    if limit and start_km and nowy_km and limit > start_km:
        wynik.update(limit_km=nowy_km + (limit - start_km), dystans_km=limit - start_km)
    return wynik


# ============================================================================
#  SŁOWA
# ============================================================================

def ile_zostalo_gwarancji(stan, j=None) -> str:
    """„jeszcze 8 miesięcy”, „jeszcze 8 miesięcy albo 12 000 km”, „jeszcze
    12 000 km”, „kończy się dziś”, „wygasła 12.05.2025”, „wygasła — przekroczono
    180 000 km”. Bez znanego licznika limit km zostaje limitem („do 180 000 km”)."""
    if stan["wygasla"]:
        if stan["powod"] == "data":
            return f"wygasła {stan['koniec'].strftime('%d.%m.%Y')}"
        return f"wygasła — przekroczono {tekst_dystansu(stan['limit_km'], 0, j)}"
    dni = stan["dni"]
    if dni == 0:
        return "kończy się dziś"
    if dni == 1:
        return "kończy się jutro"
    czesci = []
    if dni is not None:
        czesci.append(czas_slownie(stan["koniec"] - timedelta(days=dni), stan["koniec"]))
    if stan["zostalo_km"] is not None:
        czesci.append(tekst_dystansu(stan["zostalo_km"], 0, j))
    elif stan["limit_km"]:
        czesci.append(f"do {tekst_dystansu(stan['limit_km'], 0, j)}")
    if dni is None and stan["zostalo_km"] is None:
        return czesci[0]
    return "jeszcze " + " albo ".join(czesci)


def opis_gwarancji(stan, j=None) -> str:
    """„gwarancja jeszcze 8 miesięcy” — to, co stoi po nazwie części:
    „Klocki hamulcowe — gwarancja jeszcze 8 miesięcy”."""
    return f"gwarancja {ile_zostalo_gwarancji(stan, j)}"


def zakres_gwarancji(stan, j=None) -> str:
    """„do 12.05.2027 lub 180 000 km” — same limity, bez liczenia."""
    czesci = []
    if stan["koniec"]:
        czesci.append(stan["koniec"].strftime("%d.%m.%Y"))
    if stan["limit_km"]:
        czesci.append(tekst_dystansu(stan["limit_km"], 0, j))
    return "do " + " lub ".join(czesci)


def linie_przypomnienia_gwarancji(gwarancja, j=None) -> list[str]:
    """[co się kończy, po co o tym mówić] — dwie linijki powiadomienia
    o gwarancji w progu przypomnienia (pozycja z gwarancje_pojazdu)."""
    if gwarancja["blisko_przez"] == "data":
        dni = gwarancja["dni"]
        if dni == 0:
            pierwsza = "Gwarancja kończy się dziś"
        elif dni == 1:
            pierwsza = "Gwarancja kończy się jutro"
        else:
            pierwsza = (f"Gwarancja kończy się za {liczba_z_odmiana(dni, 'dzień', 'dni', 'dni')} "
                        f"({gwarancja['koniec'].strftime('%d.%m.%Y')})")
    else:
        pierwsza = f"Do końca gwarancji: {tekst_dystansu(gwarancja['zostalo_km'], 0, j)}"
        if gwarancja["data_km"]:
            pierwsza += f" (ok. {gwarancja['data_km'].strftime('%d.%m.%Y')})"
    druga = "Sprawdź część, zanim minie"
    if gwarancja.get("data"):
        druga += f" — wymiana {gwarancja['data']}"
    return [pierwsza, druga]


# ============================================================================
#  GWARANCJE Z BAZY
# ============================================================================

_KOLUMNY_WPISU = (
    "h.id, h.zadanie_id, h.wizyta_id, h.data, h.data_iso, h.przebieg, h.wykonawca, "
    "h.gwarancja_data, h.gwarancja_przebieg, z.nazwa, z.auto_id"
)


def _wpisy(warunek, parametry):
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(f"SELECT {_KOLUMNY_WPISU} FROM historia h JOIN zadania z ON z.id = h.zadanie_id "
                  f"WHERE {warunek}", parametry)
        return [dict(w) for w in c.fetchall()]


def _kolejnosc_wymian(wpis):
    """Kolejność wymian podzespołu — ta sama, co w aktualizuj_najnowszy_wpis:
    data, potem licznik (wpis bez czytelnej daty idzie na początek), na końcu
    kolejność zapisu."""
    return (wpis["data_iso"] or "", int(wpis["przebieg"] or 0), wpis["id"])


def _ma_gwarancje(wpis):
    return _data(wpis["gwarancja_data"]) is not None or _dodatnia(wpis["gwarancja_przebieg"]) is not None


def _kontekst(auto_id, wpisy, dzis, aktualny_przebieg, sredni_dzienny, prog_dni, prog_km):
    """Licznik, tempo jazdy i progi — raz na pojazd, nie raz na wpis. Średni
    przebieg liczy się z całej historii, więc tylko wtedy, gdy któraś
    gwarancja ma limit kilometrów."""
    if aktualny_przebieg is None:
        aktualny_przebieg = pobierz_aktualny_przebieg(auto_id)
    if (sredni_dzienny is None and _dodatnia(aktualny_przebieg)
            and any(_dodatnia(w["gwarancja_przebieg"]) for w in wpisy)):
        sredni_dzienny = oblicz_sredni_dzienny_przebieg(auto_id)
    return {
        "aktualny_przebieg": aktualny_przebieg, "sredni_dzienny": sredni_dzienny,
        "dzis": dzis or datetime.now().date(),
        "prog_dni": pobierz_prog_dni() if prog_dni is None else prog_dni,
        "prog_km": pobierz_prog_km() if prog_km is None else prog_km,
    }


def _gwarancja_wpisu(wpis, kontekst):
    stan = stan_gwarancji(wpis["gwarancja_data"], wpis["gwarancja_przebieg"],
                          data_wymiany=wpis["data"], przebieg_wymiany=wpis["przebieg"], **kontekst)
    if stan is None:
        return None
    return {
        **stan,
        "historia_id": wpis["id"], "zadanie_id": wpis["zadanie_id"], "wizyta_id": wpis["wizyta_id"],
        "nazwa": wpis["nazwa"], "data": wpis["data"], "przebieg": wpis["przebieg"],
        "wykonawca": wpis["wykonawca"],
    }


def _klucz_konca(gwarancja):
    """Najpierw ta, która skończy się najwcześniej; bez żadnej daty — na końcu."""
    dni = gwarancja["dni_do_konca"]
    return (dni is None, dni if dni is not None else 0, str(gwarancja["nazwa"] or "").lower())


def gwarancje_pojazdu(auto_id, dzis=None, tylko_aktywne=True, aktualny_przebieg=None,
                      sredni_dzienny=None, prog_dni=None, prog_km=None) -> list[dict[str, Any]]:
    """Gwarancje napraw pojazdu — po jednej na podzespół, z jego OSTATNIEJ
    wymiany — od tej, która skończy się najwcześniej.

    Pozycja to stan_gwarancji() plus: historia_id, zadanie_id, wizyta_id,
    nazwa (podzespołu), data i przebieg wymiany (jak w bazie) oraz wykonawca.
    `tylko_aktywne=False` dokłada gwarancje, które już minęły. Licznik, średni
    przebieg i progi można podać, gdy wołający i tak je ma."""
    if not auto_id:
        return []
    ostatnie = {}
    for wpis in _wpisy("z.auto_id = ?", (auto_id,)):
        biezacy = ostatnie.get(wpis["zadanie_id"])
        if biezacy is None or _kolejnosc_wymian(wpis) > _kolejnosc_wymian(biezacy):
            ostatnie[wpis["zadanie_id"]] = wpis
    z_gwarancja = [w for w in ostatnie.values() if _ma_gwarancje(w)]
    if not z_gwarancja:
        return []
    kontekst = _kontekst(auto_id, z_gwarancja, dzis, aktualny_przebieg, sredni_dzienny, prog_dni, prog_km)
    wynik = []
    for wpis in z_gwarancja:
        gwarancja = _gwarancja_wpisu(wpis, kontekst)
        if gwarancja and not (tylko_aktywne and gwarancja["wygasla"]):
            wynik.append(gwarancja)
    wynik.sort(key=_klucz_konca)
    return wynik


def gwarancje_wpisow(zadanie_id, dzis=None) -> dict[int, dict[str, Any]]:
    """Gwarancje wpisów jednego podzespołu po identyfikatorze wpisu — dla listy
    „Historia”, razem z tymi, które minęły. Wpis, po którym podzespół wymieniono
    jeszcze raz, ma w `wymieniona` datę tej następnej wymiany: jego część
    w aucie już nie siedzi, więc gwarancja jest tylko zapisem historii."""
    wpisy = sorted(_wpisy("h.zadanie_id = ?", (zadanie_id,)), key=_kolejnosc_wymian)
    z_gwarancja = [w for w in wpisy if _ma_gwarancje(w)]
    if not z_gwarancja:
        return {}
    kontekst = _kontekst(wpisy[0]["auto_id"], z_gwarancja, dzis, None, None, None, None)
    wynik = {}
    for i, wpis in enumerate(wpisy):
        if not _ma_gwarancje(wpis):
            continue
        gwarancja = _gwarancja_wpisu(wpis, kontekst)
        nastepny = wpisy[i + 1] if i + 1 < len(wpisy) else None
        gwarancja["wymieniona"] = nastepny["data"] if nastepny else None
        wynik[wpis["id"]] = gwarancja
    return wynik


def pobierz_gwarancje_wpisu(historia_id) -> dict[str, Any] | None:
    """Wpis z jego gwarancją, datą i licznikiem wymiany, nazwą podzespołu
    i pojazdem — dla okna „Gwarancja” przy pozycji wizyty zbiorczej."""
    wpisy = _wpisy("h.id = ?", (historia_id,))
    return wpisy[0] if wpisy else None


def zapisz_gwarancje_wpisu(historia_id, koniec, limit_km) -> int | None:
    """Gwarancja JEDNEGO wpisu — wyjątek od wspólnej gwarancji wizyty. Pusta
    data i limit zdejmują gwarancję. Zwraca auto_id (do wypchnięcia zmiany)."""
    koniec_d = _data(koniec)
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE historia SET gwarancja_data=?, gwarancja_przebieg=?, zmodyfikowane_przez=?, "
            "data_modyfikacji=? WHERE id=?",
            (koniec_d.strftime("%d.%m.%Y") if koniec_d else None, _dodatnia(limit_km),
             pobierz_moje_imie(), datetime.now().strftime("%d.%m.%Y %H:%M"), historia_id),
        )
        c.execute("SELECT z.auto_id FROM historia h JOIN zadania z ON z.id = h.zadanie_id WHERE h.id=?",
                  (historia_id,))
        wiersz = c.fetchone()
    return wiersz[0] if wiersz else None


__all__ = [
    "DNI_GWARANCJI_W_DNIACH",
    "DYSTANSE_GWARANCJI",
    "OKRESY_GWARANCJI_MIESIACE",
    "STATUS_GWARANCJI_BLISKO",
    "STATUS_GWARANCJI_OK",
    "STATUS_GWARANCJI_PO_TERMINIE",
    "bledy_gwarancji",
    "czas_slownie",
    "dodaj_miesiace",
    "gwarancje_pojazdu",
    "gwarancje_wpisow",
    "ile_zostalo_gwarancji",
    "klucz_gwarancji",
    "linie_przypomnienia_gwarancji",
    "okres_gwarancji",
    "opis_gwarancji",
    "pobierz_gwarancje_wpisu",
    "przesun_gwarancje",
    "stan_gwarancji",
    "zakres_gwarancji",
    "zapisz_gwarancje_wpisu",
]
