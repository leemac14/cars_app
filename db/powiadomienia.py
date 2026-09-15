"""Przypomnienia, odkładanie i wyciszanie powiadomień."""

import json
import sqlite3
from date import parsuj_date
from datetime import datetime, timedelta
from typing import Any

from .stale import PROG_ILOSC_MAGAZYNU_DOMYSLNY, TERMINY_DOKUMENTOW
from .polaczenie import polacz_baze
from .ustawienia import (
    _klucz_widzianych_powiadomien, pobierz_prog_dni, pobierz_prog_dni_dokumentu, pobierz_prog_km,
    pobierz_ustawienie, usun_ustawienie, zapisz_ustawienie,
)
from .przebieg import oblicz_sredni_dzienny_przebieg, pobierz_aktualny_przebieg


# ============================================================================
#  INTERWAŁ PODZESPOŁU — DWA LICZNIKI, JEDEN TERMIN
# ============================================================================
# Interwał „15 000 km albo 12 miesięcy” to dwa liczniki biegnące naraz, a o tym,
# kiedy jechać do warsztatu, decyduje ten, który skończy się PIERWSZY. Wcześniej
# każdy licznik miał własny, niezależny próg: powiadomienie sklejało dwa powody
# („Zostało 640 km • Zostało 20 dni”), datę musiał złożyć z nich sam użytkownik,
# a licznik jeszcze spoza progu w ogóle się nie pokazywał — choć „3 000 km
# zapasu” przy dwóch tygodniach do terminu znaczy co innego niż przy pół roku.
#
# Oba liczniki liczą się TUTAJ i tylko tutaj. Korzysta z tego powiadomienie
# i karta podzespołu w zakładce Serwis, więc obie mówią to samo tymi samymi
# liczbami.

# Miesiąc interwału w dniach. Ta sama wartość, co od zawsze w tym liczeniu —
# zmiana przesunęłaby termin wszystkim podzespołom naraz.
DNI_W_MIESIACU_INTERWALU = 30.5

# Kolejność statusów od najlżejszego. Status podzespołu to najgorszy z jego
# liczników; ta sama skala mówi dzwonkowi, czy powiadomienie się pogorszyło.
WAGA_STATUSU_POWIADOMIENIA = {"ok": 0, "pilne": 1, "przeterminowane": 2}


def _pole(wiersz, nazwa):
    """sqlite3.Row i słownik czytane tak samo: powiadomienia dostają wiersze
    prosto z kursora, zakładka Serwis — słowniki."""
    try:
        return wiersz[nazwa]
    except (KeyError, IndexError):
        return None


def _dodatnia_liczba(wartosc):
    """Liczba całkowita > 0 albo None. Zero i puste pole znaczą tu to samo:
    „nie ustawiono” — tak samo traktował je dotychczasowy warunek `if z[...]`."""
    try:
        liczba = int(float(wartosc))
    except (TypeError, ValueError):
        return None
    return liczba if liczba > 0 else None


def _status_licznika(zostalo, prog):
    if zostalo < 0:
        return "przeterminowane"
    return "pilne" if zostalo <= prog else "ok"


def oblicz_stan_interwalu(zadanie, aktualny_przebieg, sredni_dzienny_przebieg=None,
                          prog_km=None, prog_dni=None, dzis=None) -> dict[str, Any]:
    """Oba liczniki interwału podzespołu i to, który z nich nadejdzie pierwszy.

    `zadanie` to wiersz tabeli `zadania` (sqlite3.Row albo słownik). Wynik:

    * "km", "czas" — licznik albo None (interwał go nie ma albo brakuje przebiegu
      czy daty ostatniej wymiany). Licznik to słownik: rodzaj, zostalo (km albo
      dni; ujemne znaczy po terminie), interwal (km albo dni), zuzycie (część
      interwału, która już minęła), prog, status, dni (ile dni do końca; przy
      kilometrach prognoza ze średniego przebiegu albo None), data (koniec
      licznika; przy kilometrach prognozowany), prognoza.
    * "pierwsze" — "km", "czas" albo None, gdy nie ma żadnego licznika.
    * "status" — najgorszy ze statusów liczników albo None.

    Progi zostają dwa, bo są w różnych jednostkach i ustawia się je osobno —
    ale rozstrzygają RAZEM: podzespół jest pilny, gdy KTÓRYKOLWIEK licznik wszedł
    w swoje okno. Termin, który przyjdzie wcześniej, nie może zasłaniać tego,
    o którym użytkownik kazał sobie przypomnieć z wyprzedzeniem.
    """
    dzis = dzis or datetime.now().date()
    if prog_km is None:
        prog_km = pobierz_prog_km()
    if prog_dni is None:
        prog_dni = pobierz_prog_dni()
    prog_km_z = _dodatnia_liczba(_pole(zadanie, "prog_km")) or int(prog_km)
    prog_dni_z = _dodatnia_liczba(_pole(zadanie, "prog_dni")) or int(prog_dni)

    km = None
    interwal_km = _dodatnia_liczba(_pole(zadanie, "interwal_km"))
    przebieg_wymiany = _dodatnia_liczba(_pole(zadanie, "przebieg"))
    przebieg_teraz = _dodatnia_liczba(aktualny_przebieg)
    if interwal_km and przebieg_wymiany and przebieg_teraz:
        zostalo_km = przebieg_wymiany + interwal_km - przebieg_teraz
        # Prognoza dni tylko przed terminem i tym samym wzorem, co w tekstach
        # („ok. 12 dni”) — inaczej karta i powiadomienie rozjechałyby się o dzień.
        dni_km = None
        if zostalo_km >= 0 and sredni_dzienny_przebieg and sredni_dzienny_przebieg > 0:
            dni_km = int(round(zostalo_km / sredni_dzienny_przebieg))
        km = {
            "rodzaj": "km", "zostalo": zostalo_km, "interwal": interwal_km,
            "zuzycie": (interwal_km - zostalo_km) / interwal_km,
            "prog": prog_km_z, "status": _status_licznika(zostalo_km, prog_km_z),
            "dni": dni_km,
            "data": dzis + timedelta(days=dni_km) if dni_km is not None else None,
            "prognoza": True,
        }

    czas = None
    try:
        interwal_dni = int(float(_pole(zadanie, "interwal_miesiace") or 0) * DNI_W_MIESIACU_INTERWALU)
    except (TypeError, ValueError):
        interwal_dni = 0
    data_wymiany = parsuj_date(_pole(zadanie, "data"))
    if interwal_dni > 0 and data_wymiany != datetime.min.date():
        termin = data_wymiany + timedelta(days=interwal_dni)
        zostalo_dni = (termin - dzis).days
        czas = {
            "rodzaj": "czas", "zostalo": zostalo_dni, "interwal": interwal_dni,
            "zuzycie": (interwal_dni - zostalo_dni) / interwal_dni,
            "prog": prog_dni_z, "status": _status_licznika(zostalo_dni, prog_dni_z),
            "dni": zostalo_dni, "data": termin, "prognoza": False,
        }

    if km is None and czas is None:
        return {"km": None, "czas": None, "pierwsze": None, "status": None}

    if km is None or czas is None:
        pierwsze = "km" if km is not None else "czas"
    elif km["zostalo"] < 0 or czas["zostalo"] < 0:
        # Licznik po terminie wyprzedza każdy, który jeszcze biegnie. Oba po
        # terminie: kiedy dokładnie skończyły się kilometry, nie wiadomo (średnia
        # mówi o dzisiejszym tempie, nie o tamtym), więc rozstrzyga to, który
        # interwał przekroczono o większą część.
        if km["zostalo"] >= 0:
            pierwsze = "czas"
        elif czas["zostalo"] >= 0:
            pierwsze = "km"
        else:
            pierwsze = "km" if km["zuzycie"] > czas["zuzycie"] else "czas"
    elif km["dni"] is not None:
        # Kilometry przełożone na dni: porównujemy te same dni, które widać
        # w prognozie. Remis rozstrzyga większa zużyta część interwału.
        pierwsze = "km" if (km["dni"], -km["zuzycie"]) < (czas["dni"], -czas["zuzycie"]) else "czas"
    else:
        # Bez średniego przebiegu nie ma prognozy daty. Porównanie zużytych
        # części interwału to wtedy ta sama prognoza, tylko liczona tempem jazdy
        # od ostatniej wymiany: kilometry skończą się pierwsze dokładnie wtedy,
        # gdy zjadły większą część swojego interwału niż czas swojego.
        pierwsze = "km" if km["zuzycie"] > czas["zuzycie"] else "czas"

    liczniki = [licznik for licznik in (km, czas) if licznik is not None]
    status = max((licznik["status"] for licznik in liczniki), key=WAGA_STATUSU_POWIADOMIENIA.get)
    return {"km": km, "czas": czas, "pierwsze": pierwsze, "status": status}


def pobierz_powiadomienia(auto_id, prog_km=None, prog_dni=None, pomin_wyciszone=True) -> list[dict[str, Any]]:
    """Każde powiadomienie niesie 'klucz' — stabilny identyfikator (typ + ID
    źródła), po którym rozpoznajemy je między odświeżeniami. Treść się do tego
    nie nadaje, bo opis zmienia się z każdym dniem („Zostało 12 dni”).
    pomin_wyciszone=False zwraca komplet, łącznie z odłożonymi — potrzebne
    panelowi powiadomień do sekcji „Odkładane”."""
    if not auto_id:
        return []

    if prog_km is None: prog_km = pobierz_prog_km()
    prog_dni_wymuszony = prog_dni is not None
    if prog_dni is None: prog_dni = pobierz_prog_dni()

    wyniki = []
    dzis = datetime.now().date()
    aktualny_przebieg = pobierz_aktualny_przebieg(auto_id) or 0
    sredni_dzienny_przebieg = oblicz_sredni_dzienny_przebieg(auto_id)

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute(
            "SELECT id, nazwa, data, przebieg, interwal_km, interwal_miesiace, prog_km, prog_dni FROM zadania "
            "WHERE auto_id=? AND (interwal_km IS NOT NULL OR interwal_miesiace IS NOT NULL)",
            (auto_id,)
        )
        for z in c.fetchall():
            # Jedno powiadomienie na podzespół i JEDEN termin wynikowy: najpierw
            # licznik, który skończy się pierwszy, pod nim drugi — nawet jeśli
            # sam jeszcze nie wszedł w swój próg (patrz oblicz_stan_interwalu).
            stan = oblicz_stan_interwalu(z, aktualny_przebieg, sredni_dzienny_przebieg,
                                         prog_km=prog_km, prog_dni=prog_dni, dzis=dzis)
            if stan["status"] not in ("pilne", "przeterminowane"):
                continue
            import utils
            linie = utils.linie_opisu_interwalu(stan)
            wyniki.append({
                "typ": "podzespol", "tytul": z["nazwa"], "opis": utils.polacz_linie_opisu(linie),
                # Te same zdania osobno — panel powiadomień stawia je w dwóch
                # wierszach, żeby licznik, który przyjdzie pierwszy, stał na górze.
                "linie_opisu": linie,
                "status": stan["status"], "trasa": f"/zadanie/edytuj/{z['id']}",
                "klucz": f"podzespol:{z['id']}",
            })

        kolumny_terminow = ", ".join(kol for _, kol, _ in TERMINY_DOKUMENTOW)
        c.execute(
            f"SELECT {kolumny_terminow}, gwarancja_przebieg FROM samochody WHERE id=?",
            (auto_id,)
        )
        w = c.fetchone()
        if w:
            # Każdy termin ma własny próg wyprzedzenia (Ustawienia → „Progi
            # powiadomień”); nieruszony termin dziedziczy wspólny prog_dni.
            # prog_dni podany jawnie w wywołaniu nadal wygrywa ze wszystkim —
            # służy do podglądu „co by było, gdyby” bez ruszania ustawień.
            for klucz, kolumna, etykieta in TERMINY_DOKUMENTOW:
                txt = w[kolumna]
                if not txt:
                    continue
                d_w = parsuj_date(txt)
                if d_w == datetime.min.date():
                    continue
                prog_terminu = prog_dni if prog_dni_wymuszony else pobierz_prog_dni_dokumentu(klucz)
                zost_dni = (d_w - dzis).days
                if zost_dni <= prog_terminu:
                    s = "przeterminowane" if zost_dni < 0 else "pilne"
                    opis = f"Przekroczono o {abs(zost_dni)} dni" if zost_dni < 0 else f"Zostało {zost_dni} dni"
                    wyniki.append({
                        "typ": "dokument", "tytul": etykieta, "opis": opis,
                        "status": s, "trasa": f"/auto/edytuj/{auto_id}",
                        "klucz": f"dokument:{klucz}",
                    })

            # Gwarancja ma dwa niezależne limity — datę i przebieg. Kilometry
            # potrafią się skończyć długo przed datą, więc liczymy je osobno.
            limit_km = w["gwarancja_przebieg"]
            if limit_km:
                zost_km_gw = int(limit_km) - aktualny_przebieg
                if zost_km_gw <= prog_km:
                    s = "przeterminowane" if zost_km_gw < 0 else "pilne"
                    opis = (f"Przekroczono limit o {abs(zost_km_gw)} km" if zost_km_gw < 0
                            else f"Zostało {zost_km_gw} km do końca gwarancji")
                    wyniki.append({
                        "typ": "dokument", "tytul": "Gwarancja (limit km)", "opis": opis,
                        "status": s, "trasa": f"/auto/edytuj/{auto_id}",
                        "klucz": "dokument:gwarancja_km",
                    })
        # Wydatki cykliczne (raty, abonamenty, ubezpieczenia ratalne) — termin
        # liczy się jak dla dokumentów, ale akcją jest "Zapłacone", nie przejście
        # do formularza (stąd "trasa": None).
        c.execute(
            "SELECT id, nazwa, nastepna_data, okres_dni, czy_koszt, typ FROM wydatki_cykliczne WHERE auto_id=?",
            (auto_id,)
        )
        for wc in c.fetchall():
            d_wc = parsuj_date(wc["nastepna_data"])
            if d_wc == datetime.min.date():
                continue
            zost_dni = (d_wc - dzis).days
            # Próg dla wydatków cyklicznych jest dodatkowo ograniczony częścią
            # ich WŁASNEGO okresu — inaczej pozycja płatna np. co 30 dni przy
            # globalnym progu powiadomień 30 dni byłaby "pilna" przez CAŁY
            # cykl, a kliknięcie "Zapłacone" (przesuwające termin o okres_dni)
            # od razu wracałoby jako to samo powiadomienie.
            wlasny_prog = max(1, int(wc["okres_dni"] or 30) // 3)
            prog_efektywny = min(prog_dni, wlasny_prog)
            if zost_dni <= prog_efektywny:
                s = "przeterminowane" if zost_dni < 0 else "pilne"
                opis = f"Przekroczono o {abs(zost_dni)} dni" if zost_dni < 0 else f"Zostało {zost_dni} dni"
                # "typ_cykliczny" niesie rodzaj wpisu (wydatek / opony), żeby panel
                # mógł dać sezonowej zmianie opon własną ikonę i własny podpis
                # przycisku ("Zmieniono") zamiast "Zapłacone".
                wyniki.append({
                    "typ": "cykliczny", "tytul": wc["nazwa"], "opis": opis,
                    "status": s, "trasa": None, "wydatek_id": wc["id"],
                    "czy_koszt": bool(wc["czy_koszt"]),
                    "typ_cykliczny": str(wc["typ"] or "wydatek").strip() or "wydatek",
                    "klucz": f"cykliczny:{wc['id']}",
                })

        # Niski stan magazynu (części i płyny) — indywidualny próg per pozycja,
        # z fallbackiem na wspólną wartość domyślną dla starszych wpisów bez własnego progu.
        import utils
        c.execute(
            "SELECT id, nazwa, ilosc, jednostka, prog_ostrzezenia FROM magazyn_czesci WHERE auto_id=?",
            (auto_id,)
        )
        for m in c.fetchall():
            prog_wlasny = m["prog_ostrzezenia"]
            prog_magazynu = float(prog_wlasny) if prog_wlasny is not None else PROG_ILOSC_MAGAZYNU_DOMYSLNY
            ilosc_m = float(m["ilosc"] or 0)
            if ilosc_m <= prog_magazynu:
                s = "przeterminowane" if ilosc_m <= 0 else "pilne"
                jednostka_m = m["jednostka"] or "szt"
                opis = "Brak na stanie" if ilosc_m <= 0 else f"Zostało {utils.formatuj_liczba(ilosc_m, 2)} {jednostka_m}"
                wyniki.append({
                    "typ": "magazyn", "tytul": m["nazwa"], "opis": opis,
                    "status": s, "trasa": "/magazyn",
                    "klucz": f"magazyn:{m['id']}",
                })

    kolejnosc = {"przeterminowane": 0, "pilne": 1}

    wyniki.sort(key=lambda w: kolejnosc.get(w["status"], 2))

    if pomin_wyciszone:
        wyciszone = pobierz_wyciszone_klucze(auto_id)
        wyniki = [w for w in wyniki if w.get("klucz") not in wyciszone]
    return wyniki


# ============================================================================
#  ODKŁADANIE POWIADOMIEŃ („drzemka”)
# ============================================================================
# „Wiem o przeglądzie, zrobię go za dwa tygodnie” — wyciszenie JEDNEGO
# przypomnienia na wybraną liczbę dni, bez oznaczania czegokolwiek jako wykonane
# i bez ruszania samego terminu. Po upływie dni powiadomienie wraca samo.

DNI_ODLOZENIA_OPCJE = [3, 7, 14, 30]


def odloz_powiadomienie(auto_id, klucz, dni, tytul=None):
    """Wycisza powiadomienie o danym kluczu na `dni` dni. Ponowne odłożenie tego
    samego powiadomienia nadpisuje termin (stąd UNIQUE na auto_id+klucz)."""
    if not auto_id or not klucz:
        return None
    try:
        dni = max(1, int(dni))
    except (TypeError, ValueError):
        dni = 7
    do_dnia = (datetime.now().date() + timedelta(days=dni)).strftime("%Y-%m-%d")
    with polacz_baze() as conn:
        conn.execute(
            "INSERT INTO wyciszone_powiadomienia (auto_id, klucz, do_dnia, tytul, utworzono) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(auto_id, klucz) DO UPDATE SET do_dnia=excluded.do_dnia, "
            "tytul=excluded.tytul, utworzono=excluded.utworzono",
            (auto_id, klucz, do_dnia, tytul, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
    return do_dnia


def przywroc_powiadomienie(auto_id, klucz):
    """Zdejmuje drzemkę — powiadomienie wraca na listę od razu."""
    if not auto_id or not klucz:
        return
    with polacz_baze() as conn:
        conn.execute("DELETE FROM wyciszone_powiadomienia WHERE auto_id=? AND klucz=?", (auto_id, klucz))


def _posprzataj_wygasle_wyciszenia(conn, auto_id):
    """Kasuje drzemki, których termin już minął — dzięki temu tabela nie rośnie,
    a powiadomienie wraca bez żadnej dodatkowej logiki."""
    conn.execute(
        "DELETE FROM wyciszone_powiadomienia WHERE auto_id=? AND do_dnia <= ?",
        (auto_id, datetime.now().date().strftime("%Y-%m-%d"))
    )


def pobierz_wyciszone_klucze(auto_id):
    """Zbiór kluczy powiadomień AKTUALNIE odłożonych (drzemka jeszcze trwa)."""
    if not auto_id:
        return set()
    with polacz_baze() as conn:
        c = conn.cursor()
        try:
            _posprzataj_wygasle_wyciszenia(conn, auto_id)
            c.execute("SELECT klucz FROM wyciszone_powiadomienia WHERE auto_id=?", (auto_id,))
        except sqlite3.OperationalError:
            return set()
        return {r[0] for r in c.fetchall()}


# ============================================================================
#  WIDZIANE — PER POWIADOMIENIE, NIE PER ZESTAW
# ============================================================================
# Dzwonek porównywał kiedyś sygnaturę CAŁEGO zestawu powiadomień z tą, którą
# użytkownik ostatnio widział. Skutek był dwojaki: zmiana jednego wpisu zapalała
# odznakę na wszystkich naraz, a nowe, ważne powiadomienie wśród pięciu już
# przeczytanych gasło tym samym kliknięciem co one — nic go nie wyróżniało.
#
# Teraz każde powiadomienie ma własną sygnaturę pod własnym kluczem
# („podzespol:12”, „dokument:oc” — tymi samymi, co przy drzemce). Sygnaturą jest
# STATUS, nie treść: opis zmienia się codziennie („zostało 12 dni” → „11 dni”)
# i to nie jest powód, żeby wołać od nowa. Powodem jest pogorszenie — pilne,
# które stało się przeterminowanym.
#
# Zapis siedzi w ustawieniach, osobno dla każdego pojazdu: na telefonie
# większość otwarć aplikacji to zimny start, a stan trzymany tylko w pamięci
# zapalałby po każdym z nich odznakę na wszystkim od nowa. Świadomie NIE jest
# synchronizowany — to, co ja widziałem na swoim telefonie, nie mówi nic o tym,
# co zobaczyła druga osoba.


def klucz_powiadomienia(powiadomienie):
    """Klucz powiadomienia. Źródło bez klucza dostaje zastępczy z typu i tytułu —
    bez niego obejrzenia nie dałoby się zapamiętać i odznaka nie gasłaby nigdy."""
    return powiadomienie.get("klucz") or f"{powiadomienie.get('typ')}:{powiadomienie.get('tytul')}"


def _sygnatura_powiadomienia(powiadomienie):
    """To, czego zmiana robi z obejrzanego powiadomienia znowu nowe: status."""
    return str(powiadomienie.get("status"))


def _waga_statusu(status):
    return WAGA_STATUSU_POWIADOMIENIA.get(status, 0)


def pobierz_widziane_powiadomienia(auto_id) -> dict[str, str]:
    """{klucz powiadomienia: status, w jakim użytkownik ostatnio je widział}."""
    if not auto_id:
        return {}
    surowe = pobierz_ustawienie(_klucz_widzianych_powiadomien(auto_id))
    if not surowe:
        return {}
    try:
        dane = json.loads(surowe)
    except (TypeError, ValueError):
        # Uszkodzony zapis nie może zablokować dzwonka — najwyżej wszystko
        # będzie raz jeszcze nowe.
        return {}
    if not isinstance(dane, dict):
        return {}
    return {str(k): v for k, v in dane.items() if isinstance(v, str)}


def _zapisz_widziane_powiadomienia(auto_id, widziane):
    klucz = _klucz_widzianych_powiadomien(auto_id)
    if widziane:
        zapisz_ustawienie(klucz, json.dumps(dict(sorted(widziane.items())), ensure_ascii=False))
    else:
        usun_ustawienie(klucz)


def niewidziane_powiadomienia(powiadomienia, widziane) -> list[dict[str, Any]]:
    """Powiadomienia, na które odznaka ma zwrócić uwagę: jeszcze nieoglądane
    albo takie, których status pogorszył się od ostatniego obejrzenia."""
    widziane = widziane or {}
    nowe = []
    for p in powiadomienia:
        klucz = klucz_powiadomienia(p)
        if klucz not in widziane or _waga_statusu(_sygnatura_powiadomienia(p)) > _waga_statusu(widziane[klucz]):
            nowe.append(p)
    return nowe


def przytnij_widziane_powiadomienia(auto_id, powiadomienia) -> dict[str, str]:
    """Zapomina obejrzenia powiadomień, których na liście już nie ma, i zwraca
    resztę. Powód zniknął (wymiana zapisana, polisa odnowiona, drzemka) — a kiedy
    wróci, ma wrócić jako nowy, nie jako coś, co już raz widziano."""
    widziane = pobierz_widziane_powiadomienia(auto_id)
    obecne = {klucz_powiadomienia(p) for p in powiadomienia}
    przyciete = {k: v for k, v in widziane.items() if k in obecne}
    if auto_id and przyciete != widziane:
        _zapisz_widziane_powiadomienia(auto_id, przyciete)
    return przyciete


def oznacz_powiadomienia_jako_widziane(auto_id, powiadomienia) -> set[str]:
    """Zapamiętuje stan, w jakim użytkownik właśnie zobaczył KAŻDE powiadomienie
    z listy, i zapomina te, których na niej nie ma. Zwraca klucze powiadomień,
    które do tej chwili były nowe — panel je oznacza, żeby nie ginęły wśród
    już znanych."""
    if not auto_id:
        return set()
    widziane = pobierz_widziane_powiadomienia(auto_id)
    nowe = {klucz_powiadomienia(p) for p in niewidziane_powiadomienia(powiadomienia, widziane)}
    biezace = {klucz_powiadomienia(p): _sygnatura_powiadomienia(p) for p in powiadomienia}
    if biezace != widziane:
        _zapisz_widziane_powiadomienia(auto_id, biezace)
    return nowe


def pobierz_odlozone_powiadomienia(auto_id) -> list[dict[str, Any]]:
    """Lista odłożonych powiadomień do sekcji „Odkładane” w panelu:
    [{klucz, tytul, do_dnia, data_tekst, dni_do_powrotu}] posortowana po dacie
    powrotu. Tytuł bierzemy z żywego powiadomienia, jeśli nadal istnieje —
    a z zapamiętanego, gdy powód wyciszenia zdążył sam zniknąć."""
    if not auto_id:
        return []

    with polacz_baze() as conn:
        c = conn.cursor()
        try:
            _posprzataj_wygasle_wyciszenia(conn, auto_id)
            c.execute(
                "SELECT klucz, do_dnia, tytul FROM wyciszone_powiadomienia "
                "WHERE auto_id=? ORDER BY do_dnia",
                (auto_id,)
            )
        except sqlite3.OperationalError:
            return []
        wiersze = c.fetchall()

    if not wiersze:
        return []

    zywe = {p.get("klucz"): p for p in pobierz_powiadomienia(auto_id, pomin_wyciszone=False)}
    dzis = datetime.now().date()
    pozycje = []
    for klucz, do_dnia, tytul in wiersze:
        try:
            data_obj = datetime.strptime(str(do_dnia), "%Y-%m-%d").date()
        except (TypeError, ValueError):
            continue
        zrodlo = zywe.get(klucz)
        pozycje.append({
            "klucz": klucz,
            "tytul": (zrodlo or {}).get("tytul") or tytul or "Powiadomienie",
            "opis": (zrodlo or {}).get("opis") or "",
            "status": (zrodlo or {}).get("status"),
            "trasa": (zrodlo or {}).get("trasa"),
            "do_dnia": do_dnia,
            "data_tekst": data_obj.strftime("%d.%m.%Y"),
            "dni_do_powrotu": max(0, (data_obj - dzis).days),
            "nadal_aktualne": zrodlo is not None,
        })
    return pozycje


__all__ = [
    "DNI_ODLOZENIA_OPCJE",
    "DNI_W_MIESIACU_INTERWALU",
    "WAGA_STATUSU_POWIADOMIENIA",
    "_posprzataj_wygasle_wyciszenia",
    "klucz_powiadomienia",
    "niewidziane_powiadomienia",
    "oblicz_stan_interwalu",
    "odloz_powiadomienie",
    "oznacz_powiadomienia_jako_widziane",
    "pobierz_odlozone_powiadomienia",
    "pobierz_powiadomienia",
    "pobierz_widziane_powiadomienia",
    "pobierz_wyciszone_klucze",
    "przytnij_widziane_powiadomienia",
    "przywroc_powiadomienie",
]
