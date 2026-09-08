"""Licznik kilometrów: odczyty, historia, wykrywanie podejrzanych skoków."""

import sqlite3
from date import parsuj_date
from datetime import datetime
from typing import Any

from .stale import ENERGIA_PALIWO, ENERGIA_PRAD, ZRODLA_ODCZYTU, ZRODLA_PRZEBIEGU, ZRODLO_ODCZYTU_DOMYSLNE
from .polaczenie import polacz_baze
from .ustawienia import pobierz_walute
from .notatki import przytnij_notatke, zapisz_notatke


def pobierz_aktualny_przebieg(auto_id):
    if not auto_id: return 0
    with polacz_baze() as conn:
        c = conn.cursor()
        wpisy = []

        # Zbieramy wszystkie przebiegi, nadając nowym ręcznym odczytom wyższy priorytet (2)
        c.execute("SELECT przebieg, data, 1 FROM tankowania WHERE auto_id = ?", (auto_id,))
        wpisy.extend(c.fetchall())
        
        c.execute("SELECT przebieg, data, 1 FROM wizyty WHERE auto_id = ?", (auto_id,))
        wpisy.extend(c.fetchall())
        
        c.execute("SELECT h.przebieg, h.data, 1 FROM historia h JOIN zadania z ON h.zadanie_id = z.id WHERE z.auto_id = ? AND h.wizyta_id IS NULL", (auto_id,))
        wpisy.extend(c.fetchall())
        
        c.execute("SELECT przebieg, data, 2 FROM odczyty_przebiegu WHERE auto_id = ?", (auto_id,))
        wpisy.extend(c.fetchall())

    parsed = []
    for prz, d_str, priorytet in wpisy:
        try:
            prz_val = int(prz)
            if prz_val > 0:
                parsed.append((parsuj_date(d_str), priorytet, prz_val))
        except (TypeError, ValueError):
            pass

    if not parsed: return 0
    
    # Sortujemy chronologicznie po dacie, potem po priorytecie, a na końcu po wartości
    parsed.sort(key=lambda x: (x[0], x[1], x[2]))
    return parsed[-1][2]


def sprawdz_czy_przebieg_podejrzany(auto_id, nowy_przebieg, wyklucz_id=None, tabela=None, nowa_data_str=None):
    """Zwraca ostrzeżenie (str), jeśli nowy_przebieg jest wyraźnie niższy niż
    najwyższy dotychczas zapisany wpis dla tego auta, albo jeśli oznaczałby
    nierealnie duży dzienny przebieg względem ostatniego chronologicznie
    wpisu (np. literówka z brakującą lub dodatkową cyfrą). Sprawdza
    tankowania, wizyty oraz pojedyncze wpisy w historii (niepowiązane z
    wizytą zbiorczą — te powiązane odzwierciedla już przebieg samej wizyty)."""
    if not auto_id or not nowy_przebieg or nowy_przebieg <= 0:
        return None

    with polacz_baze() as conn:
        c = conn.cursor()
        wpisy = []

        wyklucz_sql = " AND id != ?" if (tabela == "tankowania" and wyklucz_id) else ""
        params = [auto_id] + ([wyklucz_id] if wyklucz_sql else [])
        c.execute(f"SELECT przebieg, data FROM tankowania WHERE auto_id=?{wyklucz_sql}", params)
        wpisy += c.fetchall()

        wyklucz_sql = " AND id != ?" if (tabela == "wizyty" and wyklucz_id) else ""
        params = [auto_id] + ([wyklucz_id] if wyklucz_sql else [])
        c.execute(f"SELECT przebieg, data FROM wizyty WHERE auto_id=?{wyklucz_sql}", params)
        wpisy += c.fetchall()

        wyklucz_sql = " AND h.id != ?" if (tabela == "historia" and wyklucz_id) else ""
        params = [auto_id] + ([wyklucz_id] if wyklucz_sql else [])
        c.execute(
            f"SELECT h.przebieg, h.data FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
            f"WHERE z.auto_id=? AND h.wizyta_id IS NULL{wyklucz_sql}", params
        )
        wpisy += c.fetchall()

        wyklucz_sql = " AND id != ?" if (tabela == "odczyty_przebiegu" and wyklucz_id) else ""
        params = [auto_id] + ([wyklucz_id] if wyklucz_sql else [])
        c.execute(f"SELECT przebieg, data FROM odczyty_przebiegu WHERE auto_id=?{wyklucz_sql}", params)
        wpisy += c.fetchall()

    najwyzszy_dotychczas = None
    przebieg_ostatni, data_ostatniego = None, None

    for przebieg_raw, data_str in wpisy:
        przebieg = int(przebieg_raw or 0)
        najwyzszy_dotychczas = przebieg if najwyzszy_dotychczas is None else max(najwyzszy_dotychczas, przebieg)

        d = parsuj_date(data_str)
        if d != datetime.min.date() and (data_ostatniego is None or d > data_ostatniego):
            data_ostatniego, przebieg_ostatni = d, przebieg

    # 1) Przebieg niższy niż najwyższy dotychczas zapisany wpis (np. brakująca cyfra)
    if najwyzszy_dotychczas is not None and nowy_przebieg < najwyzszy_dotychczas:
        return (
            f"Uwaga: podany przebieg ({nowy_przebieg} km) jest niższy niż najwyższy dotychczas "
            f"zapisany wpis ({najwyzszy_dotychczas} km). Sprawdź, czy nie brakuje cyfry."
        )

    # 2) Nierealnie duży skok w górę względem ostatniego chronologicznie wpisu (np. dodatkowa cyfra)
    if przebieg_ostatni is not None and nowy_przebieg > przebieg_ostatni:
        nowa_data = parsuj_date(nowa_data_str) if nowa_data_str else datetime.now().date()
        if nowa_data == datetime.min.date():
            nowa_data = datetime.now().date()
            
        dni_od_ostatniego = max(1, (nowa_data - data_ostatniego).days)
        sredni_dzienny = oblicz_sredni_dzienny_przebieg(auto_id) or 150.0
        limit_dzienny = max(sredni_dzienny * 5, 500.0)
        implikowany_dzienny = (nowy_przebieg - przebieg_ostatni) / dni_od_ostatniego
        if implikowany_dzienny > limit_dzienny:
            return (
                f"Uwaga: od ostatniego wpisu ({przebieg_ostatni} km) minęło {dni_od_ostatniego} dni. "
                f"Wynikałoby to na ok. {int(implikowany_dzienny)} km/dzień. Sprawdź, czy nie ma dodatkowej cyfry w przebiegu."
            )

    return None


def sprawdz_czy_tankowanie_duplikat(auto_id, data_str, przebieg, kwota, wyklucz_id=None):
    """Zwraca ostrzeżenie (str), jeśli dla tego pojazdu istnieje już tankowanie
    z DOKŁADNIE tą samą datą, przebiegiem i kwotą — częsty efekt podwójnego
    zapisu tego samego wpisu (np. dubel kliknięcia „Zapisz”). Analogicznie do
    sprawdz_czy_przebieg_podejrzany: nie blokuje zapisu samodzielnie, tylko
    sygnalizuje możliwy duplikat do potwierdzenia przez użytkownika."""
    if not auto_id or not data_str:
        return None

    with polacz_baze() as conn:
        c = conn.cursor()
        wyklucz_sql = " AND id != ?" if wyklucz_id else ""
        params = [auto_id, data_str, int(przebieg or 0), float(kwota or 0)]
        if wyklucz_id:
            params.append(wyklucz_id)
        c.execute(
            f"SELECT id FROM tankowania WHERE auto_id=? AND data=? AND przebieg=? AND kwota=?{wyklucz_sql}",
            params
        )
        istnieje = c.fetchone()

    if istnieje:
        import utils
        return (
            f"Uwaga: masz już zapisane tankowanie z {data_str}, przebiegiem "
            f"{utils.formatuj_liczba(przebieg, 0)} km i kwotą {utils.formatuj_liczba(kwota, 2)} "
            f"{pobierz_walute()}. Czy to nie duplikat?"
        )
    return None


def sprawdz_czy_koszt_duplikat(auto_id, data_str, nazwa, kwota, wyklucz_id=None):
    """Zwraca ostrzeżenie (str), jeśli dla tego pojazdu istnieje już inny koszt
    z DOKŁADNIE tą samą datą, opisem i kwotą — częsty efekt podwójnego zapisu
    tego samego wpisu (np. dubel kliknięcia „Zapisz”). Analogicznie do
    sprawdz_czy_tankowanie_duplikat: nie blokuje zapisu samodzielnie, tylko
    sygnalizuje możliwy duplikat do potwierdzenia przez użytkownika."""
    if not auto_id or not data_str:
        return None

    with polacz_baze() as conn:
        c = conn.cursor()
        wyklucz_sql = " AND id != ?" if wyklucz_id else ""
        params = [auto_id, data_str, (nazwa or "").strip(), float(kwota or 0)]
        if wyklucz_id:
            params.append(wyklucz_id)
        c.execute(
            f"SELECT id FROM inne_koszty WHERE auto_id=? AND data=? AND nazwa=? AND kwota=?{wyklucz_sql}",
            params
        )
        istnieje = c.fetchone()

    if istnieje:
        import utils
        return (
            f"Uwaga: masz już zapisany koszt „{nazwa}” z {data_str} na kwotę "
            f"{utils.formatuj_liczba(kwota, 2)} {pobierz_walute()}. Czy to nie duplikat?"
        )
    return None


def oblicz_sredni_dzienny_przebieg(auto_id, min_dni=7):
    """Średni przebieg dzienny liczony na podstawie WSZYSTKICH źródeł przebiegu —
    dokładnie tych samych, których używa pobierz_historie_przebiegu() (wykres
    przebiegu w paszporcie PDF): tankowania, wizyty, pojedyncze wpisy historii
    i ręczne odczyty. Wcześniej ta funkcja liczyła TYLKO z tankowań i odczytów
    ręcznych — ktoś logujący wyłącznie wizyty serwisowe (bez tankowań w
    aplikacji) zawsze dostawał None, a przez to znikały mu prognozy terminów
    ("Zostanie ok. X dni") w powiadomieniach i na kartach podzespołów."""
    if not auto_id:
        return None

    punkty = pobierz_historie_przebiegu(auto_id)
    if len(punkty) < 2:
        return None

    pierwsza_data = parsuj_date(punkty[0][0])
    ostatnia_data = parsuj_date(punkty[-1][0])
    pierwszy_przebieg = punkty[0][1]
    ostatni_przebieg = punkty[-1][1]

    dni_roznica = (ostatnia_data - pierwsza_data).days
    km_roznica = ostatni_przebieg - pierwszy_przebieg

    if dni_roznica < min_dni or km_roznica <= 0:
        return None

    return km_roznica / dni_roznica


def pobierz_historie_przebiegu(auto_id) -> list[tuple[str, int]]:
    """Chronologiczna historia stanu licznika złożona ze wszystkich źródeł
    (tankowania, wizyty, historia bez wizyty, ręczne odczyty) — do wykresu
    przebiegu w paszporcie pojazdu. Dla każdej daty zostaje zapisany najwyższy
    zanotowany tego dnia przebieg; wynik jest posortowany chronologicznie.
    Zwraca listę krotek (data_str, przebieg_int)."""
    if not auto_id:
        return []

    with polacz_baze() as conn:
        c = conn.cursor()
        wpisy = []
        c.execute("SELECT data, przebieg FROM tankowania WHERE auto_id=?", (auto_id,))
        wpisy += c.fetchall()
        c.execute("SELECT data, przebieg FROM wizyty WHERE auto_id=?", (auto_id,))
        wpisy += c.fetchall()
        c.execute(
            "SELECT h.data, h.przebieg FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE z.auto_id=? AND h.wizyta_id IS NULL", (auto_id,)
        )
        wpisy += c.fetchall()
        c.execute("SELECT data, przebieg FROM odczyty_przebiegu WHERE auto_id=?", (auto_id,))
        wpisy += c.fetchall()

    wg_daty = {}
    for data_str, prz in wpisy:
        d = parsuj_date(data_str)
        if d == datetime.min.date():
            continue
        try:
            prz_i = int(prz or 0)
        except (TypeError, ValueError):
            continue
        if prz_i <= 0:
            continue
        if d not in wg_daty or prz_i > wg_daty[d][1]:
            wg_daty[d] = (data_str, prz_i)

    return [wg_daty[d] for d in sorted(wg_daty.keys())]


def dodaj_odczyt_przebiegu(auto_id, przebieg, data_str=None, notatka=None, zrodlo=ZRODLO_ODCZYTU_DOMYSLNE):
    """Zapisuje szybki, ręczny odczyt licznika (np. z deski rozdzielczej) w osobnym
    dzienniku — bez tworzenia sztucznego tankowania czy wpisu serwisowego tylko po
    to, by odświeżyć aktualny przebieg. Jeśli w danym dniu istnieje już odczyt,
    aktualizuje go zamiast duplikować. Zwraca True, jeśli nadpisano istniejący
    wpis z tego dnia, False, jeśli dodano zupełnie nowy."""
    if not auto_id or not przebieg or przebieg <= 0:
        return False
    if not data_str:
        data_str = datetime.now().strftime("%d.%m.%Y")

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT id FROM odczyty_przebiegu WHERE auto_id=? AND data=?", (auto_id, data_str))
        w = c.fetchone()
        zrodlo = zrodlo if zrodlo in ZRODLA_ODCZYTU else ZRODLO_ODCZYTU_DOMYSLNE
        if w:
            # Nadpisując odczyt z tego samego dnia przepisujemy też źródło:
            # liczy się to, skąd pochodzi AKTUALNA wartość, a nie ta sprzed chwili.
            conn.execute("UPDATE odczyty_przebiegu SET przebieg=?, zrodlo=? WHERE id=?", (przebieg, zrodlo, w[0]))
            rekord_id, nadpisano = w[0], True
        else:
            kursor = conn.execute(
                "INSERT INTO odczyty_przebiegu (auto_id, data, przebieg, zrodlo) VALUES (?,?,?,?)",
                (auto_id, data_str, przebieg, zrodlo)
            )
            rekord_id, nadpisano = kursor.lastrowid, False

    # Notatka POZA transakcją powyżej — zapisz_notatke otwiera własne połączenie
    # i w środku otwartej transakcji potrafi zakleszczyć bazę (ten sam powód, co
    # przy nagrobkach w formularzu wpisu).
    # Pustej notatki celowo NIE zapisujemy: to ścieżka DODAWANIA, a przy trafieniu
    # w istniejący odczyt z tego samego dnia wyczyściłaby notatkę, której formularz
    # dodawania nawet nie pokazał. Kasowanie notatki idzie osobną drogą — przez
    # edycję odczytu albo pozycję „Notatka” w jego menu.
    if przytnij_notatke(notatka):
        zapisz_notatke("odczyty_przebiegu", rekord_id, notatka)
    return nadpisano


# Ile razy średni dzienny przebieg musi zostać przekroczony, żeby uznać skok
# licznika za podejrzany. Sześciokrotność bierze się stąd, że jeden wyjazd
# wakacyjny potrafi dać 4-5× normy i NIE jest błędem — dopiero powyżej robi się
# nieprawdopodobny. Dolny próg pilnuje aut jeżdżących mało: przy średniej
# 3 km/dzień samo pomnożenie dałoby alarm po każdej wycieczce za miasto.
KROTNOSC_SKOKU_PRZEBIEGU = 6

MIN_SKOK_PRZEBIEGU_NA_DZIEN = 400


def pobierz_pelna_historie_przebiegu(auto_id) -> list[dict[str, Any]]:
    """WSZYSTKIE znane stany licznika pojazdu, nie tylko ręczne odczyty.

    Każde tankowanie, każda wizyta i każdy wpis serwisowy niosą przebieg — do tej
    pory ta wiedza leżała rozrzucona po czterech ekranach, a historia licznika
    pokazywała wyłącznie to, co ktoś wpisał osobno. Tutaj składamy jedno,
    chronologiczne źródło prawdy o liczniku wraz z informacją, SKĄD każdy wpis
    pochodzi i czy da się go stąd edytować.

    Zwraca listę słowników posortowaną rosnąco po (data, przebieg), z policzonymi
    już: dystansem od poprzedniego wpisu, liczbą dni, średnią dzienną na tym
    odcinku i ewentualną anomalią ('cofka' albo 'skok')."""
    if not auto_id:
        return []

    wpisy = []
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute(
            "SELECT id, data, przebieg, zrodlo, notatka, notatka_autor, notatka_data "
            "FROM odczyty_przebiegu WHERE auto_id=?", (auto_id,)
        )
        for r in c.fetchall():
            podzrodlo = r["zrodlo"] if r["zrodlo"] in ZRODLA_ODCZYTU else ZRODLO_ODCZYTU_DOMYSLNE
            wpisy.append({
                "zrodlo": "odczyt", "podzrodlo": podzrodlo,
                "id": r["id"], "data": r["data"], "przebieg": int(r["przebieg"] or 0),
                "opis": ZRODLA_ODCZYTU[podzrodlo],
                "notatka": r["notatka"], "notatka_autor": r["notatka_autor"],
                "notatka_data": r["notatka_data"],
                "trasa": None, "edytowalny": True,
            })

        c.execute(
            "SELECT id, data, przebieg, stacja, rodzaj_energii, notatka, notatka_autor, notatka_data "
            "FROM tankowania WHERE auto_id=?", (auto_id,)
        )
        for r in c.fetchall():
            czy_prad = (r["rodzaj_energii"] or ENERGIA_PALIWO) == ENERGIA_PRAD
            wpisy.append({
                "zrodlo": "tankowanie", "podzrodlo": None,
                "id": r["id"], "data": r["data"], "przebieg": int(r["przebieg"] or 0),
                "opis": r["stacja"] or ("Ładowanie" if czy_prad else "Tankowanie"),
                "notatka": r["notatka"], "notatka_autor": r["notatka_autor"],
                "notatka_data": r["notatka_data"],
                "trasa": f"/tankowanie/edytuj/{r['id']}", "edytowalny": False,
            })

        c.execute("SELECT id, data, przebieg, wykonawca, notatki FROM wizyty WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            wpisy.append({
                "zrodlo": "wizyta", "podzrodlo": None,
                "id": r["id"], "data": r["data"], "przebieg": int(r["przebieg"] or 0),
                "opis": r["wykonawca"] or "Wizyta w warsztacie",
                # Wizyta trzyma notatkę w starym polu 'notatki' (patrz POLA_NOTATKI)
                # i nie ma podpisu — stąd None w autorze i dacie.
                "notatka": r["notatki"], "notatka_autor": None, "notatka_data": None,
                "trasa": f"/wizyty/edytuj/{r['id']}", "edytowalny": False,
            })

        c.execute(
            "SELECT h.id, h.data, h.przebieg, h.notatka, h.notatka_autor, h.notatka_data, "
            "z.nazwa, z.id AS zadanie_id "
            "FROM historia h JOIN zadania z ON h.zadanie_id = z.id "
            "WHERE z.auto_id=? AND h.wizyta_id IS NULL", (auto_id,)
        )
        for r in c.fetchall():
            wpisy.append({
                "zrodlo": "serwis", "podzrodlo": None,
                "id": r["id"], "data": r["data"], "przebieg": int(r["przebieg"] or 0),
                "opis": r["nazwa"] or "Wpis serwisowy",
                "notatka": r["notatka"], "notatka_autor": r["notatka_autor"],
                "notatka_data": r["notatka_data"],
                "trasa": f"/wpis/edytuj/{r['id']}", "edytowalny": False,
            })

    # Wpisy bez sensownego przebiegu (0 albo brak) nie mówią nic o liczniku —
    # w historii licznika byłyby wyłącznie szumem.
    wpisy = [w for w in wpisy if w["przebieg"] > 0]
    for w in wpisy:
        w["data_obj"] = parsuj_date(w["data"])
        w["klucz"] = f"{w['zrodlo']}_{w['id']}"
        w["etykieta_zrodla"] = ZRODLA_PRZEBIEGU[w["zrodlo"]]
    wpisy = [w for w in wpisy if w["data_obj"] != datetime.min.date()]
    wpisy.sort(key=lambda w: (w["data_obj"], w["przebieg"]))

    sredni_dzienny = oblicz_sredni_dzienny_przebieg(auto_id) or 0
    prog_skoku = max(MIN_SKOK_PRZEBIEGU_NA_DZIEN, sredni_dzienny * KROTNOSC_SKOKU_PRZEBIEGU)

    poprzedni = None
    for w in wpisy:
        if poprzedni is None:
            w["dystans"] = None
            w["dni"] = None
            w["srednia_dzienna"] = None
            w["anomalia"] = None
        else:
            dystans = w["przebieg"] - poprzedni["przebieg"]
            dni = (w["data_obj"] - poprzedni["data_obj"]).days
            w["dystans"] = dystans
            w["dni"] = dni
            # Dwa wpisy tego samego dnia dzielimy przez 1, a nie przez 0 —
            # inaczej każde tankowanie w dniu przeglądu byłoby „skokiem”.
            w["srednia_dzienna"] = dystans / max(1, dni) if dystans >= 0 else None
            if dystans < 0:
                w["anomalia"] = "cofka"
            elif w["srednia_dzienna"] and w["srednia_dzienna"] > prog_skoku and dni >= 1:
                w["anomalia"] = "skok"
            else:
                w["anomalia"] = None
        w["poprzedni_klucz"] = poprzedni["klucz"] if poprzedni else None
        poprzedni = w

    return wpisy


def podsumowanie_historii_przebiegu(auto_id, wpisy=None):
    """Nagłówek historii licznika: ile wpisów i z czego się składają, jaki
    dystans obejmują, jak dawno był ostatni i ile jest nieścisłości."""
    wpisy = pobierz_pelna_historie_przebiegu(auto_id) if wpisy is None else wpisy
    if not wpisy:
        return None

    wg_zrodla = {}
    for w in wpisy:
        wg_zrodla[w["zrodlo"]] = wg_zrodla.get(w["zrodlo"], 0) + 1

    pierwszy, ostatni = wpisy[0], wpisy[-1]
    dni = (ostatni["data_obj"] - pierwszy["data_obj"]).days
    dystans = ostatni["przebieg"] - pierwszy["przebieg"]

    return {
        "liczba": len(wpisy),
        "wg_zrodla": wg_zrodla,
        "pierwszy": pierwszy,
        "ostatni": ostatni,
        "dystans": dystans if dystans > 0 else 0,
        "dni": dni,
        "srednia_dzienna": (dystans / dni) if dni > 0 and dystans > 0 else None,
        "dni_od_ostatniego": max(0, (datetime.now().date() - ostatni["data_obj"]).days),
        "anomalie": sum(1 for w in wpisy if w.get("anomalia")),
        "recznych": wg_zrodla.get("odczyt", 0),
    }


def aktualizuj_odczyt_przebiegu(odczyt_id, przebieg, data_str):
    """Edycja konkretnego, istniejącego odczytu (z poziomu listy historii) —
    aktualizuje po ID, bez logiki upsert po dacie użytej w dodaj_odczyt_przebiegu."""
    with polacz_baze() as conn:
        conn.execute("UPDATE odczyty_przebiegu SET przebieg=?, data=? WHERE id=?", (przebieg, data_str, odczyt_id))


def aktualizuj_najnowszy_wpis(zadanie_id):
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT data, przebieg FROM historia WHERE zadanie_id = ?", (zadanie_id,))
        wpisy = c.fetchall()
        if wpisy:
            wpisy.sort(key=lambda x: (parsuj_date(x[0]), int(x[1] or 0)), reverse=True)
            c.execute("UPDATE zadania SET data=?, przebieg=? WHERE id=?", (wpisy[0][0], int(wpisy[0][1] or 0), zadanie_id))
        else:
            c.execute("UPDATE zadania SET data=NULL, przebieg=NULL WHERE id=?", (zadanie_id,))


def przelicz_wszystkie_zadania(auto_id):
    if not auto_id: return
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT id FROM zadania WHERE auto_id = ?", (auto_id,))
        for r in c.fetchall():
            aktualizuj_najnowszy_wpis(r[0])


__all__ = [
    "KROTNOSC_SKOKU_PRZEBIEGU",
    "MIN_SKOK_PRZEBIEGU_NA_DZIEN",
    "aktualizuj_najnowszy_wpis",
    "aktualizuj_odczyt_przebiegu",
    "dodaj_odczyt_przebiegu",
    "oblicz_sredni_dzienny_przebieg",
    "pobierz_aktualny_przebieg",
    "pobierz_historie_przebiegu",
    "pobierz_pelna_historie_przebiegu",
    "podsumowanie_historii_przebiegu",
    "przelicz_wszystkie_zadania",
    "sprawdz_czy_koszt_duplikat",
    "sprawdz_czy_przebieg_podejrzany",
    "sprawdz_czy_tankowanie_duplikat",
]
