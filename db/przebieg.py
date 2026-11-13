"""Licznik kilometrów: odczyty, historia, wykrywanie podejrzanych skoków."""

import sqlite3
from bisect import bisect_right
from date import na_iso, parsuj_date
from datetime import datetime, timedelta
from typing import Any

from .stale import (
    ENERGIA_PALIWO, ENERGIA_PRAD, RODZAJE_PLYNOW, STATUS_POJAZDU_AKTYWNY, ZRODLA_ODCZYTU, ZRODLA_PRZEBIEGU,
    ZRODLO_ODCZYTU_DOMYSLNE,
)
from .polaczenie import polacz_baze
from .pomocnicze import liczba_z_odmiana, odmien
from .ustawienia import pobierz_dni_przypomnienia_o_odczycie, pobierz_walute
from .jednostki import dystans_z_km, jednostka_dystansu, tekst_dystansu
from .notatki import przytnij_notatke, zapisz_notatke


# Źródła licznika: (klucz z ZRODLA_PRZEBIEGU, tabela, etap, zapytanie → id, data, licznik).
_ZRODLA_LICZNIKA = (
    ("tankowanie", "tankowania", "", "SELECT {nr}, id, data, przebieg FROM tankowania WHERE auto_id=:a"),
    ("wizyta", "wizyty", "", "SELECT {nr}, id, data, przebieg FROM wizyty WHERE auto_id=:a"),
    ("serwis", "historia", "", "SELECT {nr}, h.id, h.data, h.przebieg FROM historia h JOIN zadania z "
                               "ON h.zadanie_id=z.id WHERE z.auto_id=:a AND h.wizyta_id IS NULL"),
    ("odczyt", "odczyty_przebiegu", "", "SELECT {nr}, id, data, przebieg FROM odczyty_przebiegu WHERE auto_id=:a"),
    # Przejazd z ewidencji niesie licznik tylko wtedy, gdy ktoś go wpisał (stan PO przejeździe).
    ("przejazd", "przejazdy", "", "SELECT {nr}, id, data, licznik FROM przejazdy "
                                  "WHERE auto_id=:a AND licznik IS NOT NULL"),
    ("dolewka", "dolewki", "", "SELECT {nr}, id, data, przebieg FROM dolewki WHERE auto_id=:a"),
    # Od tego miejsca licznik wpisany PRZY OKAZJI (_PIERWSZE_PRZY_OKAZJI).
    ("opony", "montaze_opon", "", "SELECT {nr}, id, data, przebieg FROM montaze_opon "
                                  "WHERE auto_id=:a AND przebieg > 0"),
    ("opony", "montaze_opon", "zdjecie", "SELECT {nr}, id, data_zdjecia, przebieg_zdjecia FROM montaze_opon "
                                         "WHERE auto_id=:a AND przebieg_zdjecia > 0 AND data_zdjecia IS NOT NULL"),
    ("bieznik", "pomiary_bieznika", "", "SELECT {nr}, id, data, przebieg FROM pomiary_bieznika "
                                        "WHERE auto_id=:a AND przebieg > 0"),
    ("karoseria", "zdjecia_karoserii", "", "SELECT {nr}, id, data, przebieg FROM zdjecia_karoserii "
                                           "WHERE auto_id=:a AND przebieg > 0"),
    # Wykonanie z wpisem serwisowym albo wizytą niesie licznik w nim; z Innym kosztem — dzień kosztu.
    ("do_zrobienia", "do_zrobienia", "",
     "SELECT {nr}, d.id, COALESCE(k.data, d.data_wykonania), d.przebieg_wykonania FROM do_zrobienia d "
     "LEFT JOIN inne_koszty k ON k.id = d.koszt_id WHERE d.auto_id=:a AND d.wykonane=1 "
     "AND d.przebieg_wykonania > 0 AND d.historia_id IS NULL AND d.wizyta_id IS NULL"),
)
_PIERWSZE_PRZY_OKAZJI = 6
ZRODLA_PRZY_OKAZJI = tuple(dict.fromkeys(z[0] for z in _ZRODLA_LICZNIKA[_PIERWSZE_PRZY_OKAZJI:]))
_SQL_STANOW_LICZNIKA = " UNION ALL ".join(z[3].format(nr=nr) for nr, z in enumerate(_ZRODLA_LICZNIKA))


def _stany_licznika(auto_id, bez=None) -> list[tuple[Any, int, str, int, str, str]]:
    """Stany licznika pojazdu ze wszystkich źródeł: (dzień, km, źródło, id, data, etap) — etap
    „zdjecie” to koniec okresu montażu. `bez` — (tabela, id) wpisu właśnie poprawianego.
    Licznik wpisany przy okazji (zmiana opon, bieżnik, karoseria, Do zrobienia) liczy się tylko
    wtedy, gdy mieści się między sąsiadami: wyżej niż wszystko do tego dnia i nie wyżej niż
    najniższy późniejszy wpis główny. Pole bywa tam wypełnione ostatnim znanym stanem albo liczbą
    z pamięci — kopia nie jest odczytem i nie może robić cofki we wpisach głównych."""
    if not auto_id:
        return []
    with polacz_baze() as conn:
        wiersze = conn.execute(_SQL_STANOW_LICZNIKA, {"a": auto_id}).fetchall()
    glowne, okazje = [], []
    for nr, rekord_id, data_str, przebieg in wiersze:
        zrodlo, tabela, etap, _ = _ZRODLA_LICZNIKA[nr]
        if bez and bez == (tabela, rekord_id):
            continue
        try:
            km = int(przebieg)
        except (TypeError, ValueError):
            continue
        if km <= 0:
            continue
        stan = (parsuj_date(data_str), km, zrodlo, rekord_id, data_str, etap)
        (okazje if nr >= _PIERWSZE_PRZY_OKAZJI else glowne).append(stan)
    if not okazje:
        return glowne

    glowne.sort(key=lambda s: (s[0], s[1]))
    dni = [s[0] for s in glowne]
    najwyzszy_do, najnizszy_od = [], [None] * (len(glowne) + 1)
    for s in glowne:
        najwyzszy_do.append(max(s[1], najwyzszy_do[-1]) if najwyzszy_do else s[1])
    for i in range(len(glowne) - 1, -1, -1):
        dalej = najnizszy_od[i + 1]
        najnizszy_od[i] = glowne[i][1] if dalej is None else min(glowne[i][1], dalej)

    przyjete, najwyzsza_okazja = [], 0
    for stan in sorted(okazje, key=lambda s: (s[0], s[1])):
        if stan[0] == datetime.min.date():
            continue
        ile = bisect_right(dni, stan[0])  # wpisy główne do tego dnia włącznie
        dol = max(najwyzszy_do[ile - 1] if ile else 0, najwyzsza_okazja)
        gora = najnizszy_od[ile]
        if stan[1] > dol and (gora is None or stan[1] <= gora):
            przyjete.append(stan)
            najwyzsza_okazja = stan[1]
    return glowne + przyjete


def pobierz_aktualny_przebieg(auto_id):
    """Stan licznika z najpóźniejszego dnia; tego samego dnia ręczny odczyt wygrywa z resztą,
    dalej wyższy stan. 0 bez auta i bez żadnego wpisu z licznikiem."""
    stany = _stany_licznika(auto_id)
    if not stany:
        return 0
    return max(stany, key=lambda s: (s[0], s[2] == "odczyt", s[1]))[1]


def sprawdz_czy_przebieg_podejrzany(auto_id, nowy_przebieg, wyklucz_id=None, tabela=None, nowa_data_str=None):
    """Ostrzeżenie (str), gdy nowy_przebieg nie pasuje do sąsiadów W CZASIE: niższy niż
    najwyższy z tej samej lub wcześniejszej daty, wyższy niż wpis późniejszy albo z
    nierealnym dziennym przebiegiem od poprzedniego. Źródła jak w historii licznika
    (_stany_licznika); `tabela` + `wyklucz_id` — wpis właśnie poprawiany."""
    if not auto_id or not nowy_przebieg or nowy_przebieg <= 0:
        return None

    wpisy = [(s[1], s[4]) for s in _stany_licznika(
        auto_id, bez=(tabela, wyklucz_id) if tabela and wyklucz_id else None)]

    nowa_data = parsuj_date(nowa_data_str) if nowa_data_str else datetime.now().date()
    if nowa_data == datetime.min.date():
        nowa_data = datetime.now().date()

    # Wpis bez czytelnej daty traktujemy jak wcześniejszy — tak jak liczyła to
    # dotąd cała historia, z którą był porównywany.
    wczesniejsze, pozniejsze = [], []
    for przebieg_raw, data_str in wpisy:
        try:
            przebieg = int(przebieg_raw or 0)
        except (TypeError, ValueError):
            continue
        if przebieg <= 0:
            continue
        d = parsuj_date(data_str)
        (pozniejsze if d > nowa_data else wczesniejsze).append((d, przebieg))

    # 1) Niższy niż najwyższy wpis z tej samej albo wcześniejszej daty (np. brakująca cyfra)
    najwyzszy_wczesniej = max((p for _, p in wczesniejsze), default=None)
    if najwyzszy_wczesniej is not None and nowy_przebieg < najwyzszy_wczesniej:
        return (
            f"Uwaga: podany przebieg ({tekst_dystansu(nowy_przebieg)}) jest niższy niż najwyższy dotychczas "
            f"zapisany wpis ({tekst_dystansu(najwyzszy_wczesniej)}). Sprawdź, czy nie brakuje cyfry."
        )

    # 2) Wyższy niż wpis z datą PÓŹNIEJSZĄ — licznik nie cofa się w czasie
    if pozniejsze:
        d_poz, najnizszy_pozniej = min(pozniejsze, key=lambda w: (w[1], w[0]))
        if nowy_przebieg > najnizszy_pozniej:
            return (
                f"Uwaga: podany przebieg ({tekst_dystansu(nowy_przebieg)}) jest wyższy niż we wpisie z późniejszą "
                f"datą ({tekst_dystansu(najnizszy_pozniej)}, {d_poz.strftime('%d.%m.%Y')}). Sprawdź datę albo przebieg."
            )

    # 3) Nierealnie duży skok względem poprzedzającego wpisu (np. dodatkowa cyfra)
    z_data = [w for w in wczesniejsze if w[0] != datetime.min.date()]
    if z_data:
        data_poprzedniego, przebieg_poprzedni = max(z_data)
        if nowy_przebieg > przebieg_poprzedni:
            dni_od_poprzedniego = max(1, (nowa_data - data_poprzedniego).days)
            sredni_dzienny = oblicz_sredni_dzienny_przebieg(auto_id) or 150.0
            limit_dzienny = max(sredni_dzienny * 5, 500.0)
            implikowany_dzienny = (nowy_przebieg - przebieg_poprzedni) / dni_od_poprzedniego
            if implikowany_dzienny > limit_dzienny:
                return (
                    f"Uwaga: od poprzedniego wpisu ({tekst_dystansu(przebieg_poprzedni)}) "
                    f"{odmien(dni_od_poprzedniego, 'minął', 'minęły', 'minęło')} "
                    f"{liczba_z_odmiana(dni_od_poprzedniego, 'dzień', 'dni', 'dni')}. "
                    f"Wynikałoby to na ok. {int(dystans_z_km(implikowany_dzienny))} {jednostka_dystansu()}/dzień. "
                    "Sprawdź, czy nie ma dodatkowej cyfry w przebiegu."
                )

    return None


def sprawdz_czy_tankowanie_duplikat(auto_id, data_str, przebieg, kwota, wyklucz_id=None):
    """Ostrzeżenie (str), gdy pojazd ma już tankowanie z DOKŁADNIE tą samą datą,
    przebiegiem i kwotą (dubel „Zapisz”). Nie blokuje — prosi o potwierdzenie."""
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
            f"{tekst_dystansu(przebieg)} i kwotą {utils.formatuj_liczba(kwota, 2)} "
            f"{pobierz_walute()}. Czy to nie duplikat?"
        )
    return None


def sprawdz_czy_koszt_duplikat(auto_id, data_str, nazwa, kwota, wyklucz_id=None):
    """Ostrzeżenie (str), gdy pojazd ma już inny koszt z DOKŁADNIE tą samą datą, opisem
    i kwotą. Nie blokuje — prosi o potwierdzenie."""
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


class TempoJazdy(float):
    """Średni przebieg dzienny (km) razem z dniem ostatniego stanu licznika (`od`) — od niego,
    nie od dziś, biegnie prognoza z tempa (prognoza_z_tempa). W rachunkach zwykła liczba."""

    od = None

    def __new__(cls, km_dziennie, od=None):
        tempo = super().__new__(cls, km_dziennie)
        tempo.od = od
        return tempo


def prognoza_z_tempa(zostalo_km, sredni_dzienny, dzis=None) -> tuple[int | None, Any]:
    """(dni od dziś, dzień), w którym auto przejedzie `zostalo_km` w tempie `sredni_dzienny`.
    Liczy od dnia stanu licznika (TempoJazdy.od): przy starym odczycie część drogi jest już za
    autem. Dzień, który wypadł przed dziś, to dziś; zwykła liczba liczy od dziś. (None, None) po
    przekroczeniu i bez tempa."""
    if zostalo_km is None or zostalo_km < 0 or not sredni_dzienny or sredni_dzienny <= 0:
        return None, None
    dzis = dzis or datetime.now().date()
    od = getattr(sredni_dzienny, "od", None)
    start = od if od and od < dzis else dzis
    dzien = max(dzis, start + timedelta(days=int(round(zostalo_km / sredni_dzienny))))
    return (dzien - dzis).days, dzien


def oblicz_sredni_dzienny_przebieg(auto_id, min_dni=7, punkty=None):
    """Średni przebieg dzienny (TempoJazdy) ze WSZYSTKICH źródeł licznika — tych samych co
    pobierz_historie_przebiegu(). `punkty` — gotowa historia, gdy wołający już ją ma
    (swiezosc_licznika)."""
    if not auto_id:
        return None

    if punkty is None:
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

    return TempoJazdy(km_roznica / dni_roznica, ostatnia_data)


def pobierz_historie_przebiegu(auto_id) -> list[tuple[str, int]]:
    """Chronologiczna historia licznika ze wszystkich źródeł (_stany_licznika: tankowania,
    wizyty, wpisy serwisowe, odczyty, przejazdy, dolewki oraz licznik wpisany przy zmianie opon,
    pomiarze bieżnika, zdjęciu karoserii i wykonaniu pozycji Do zrobienia); na dzień najwyższy
    przebieg. Zwraca [(data_str, przebieg_int)]."""
    if not auto_id:
        return []

    wg_daty = {}
    for dzien, km, _zrodlo, _id, data_str, _etap in _stany_licznika(auto_id):
        if dzien != datetime.min.date() and (dzien not in wg_daty or km > wg_daty[dzien][1]):
            wg_daty[dzien] = (data_str, km)

    return [wg_daty[d] for d in sorted(wg_daty.keys())]


def przejechane_km(auto_id, od=None, do=None, punkty=None) -> int:
    """Kilometry w [od, do] (końce opcjonalne) z historii licznika ze wszystkich źródeł — od
    ostatniego stanu sprzed okresu (bez niego od najniższego w okresie) do najwyższego w okresie.
    Ta sama miara w Roku w pigułce, Analizie, porównaniu i raporcie; 0, gdy nie ma z czego odjąć."""
    punkty = pobierz_historie_przebiegu(auto_id) if punkty is None else punkty
    przed_okresem, w_okresie = None, []
    for data_str, prz in punkty:
        d = parsuj_date(data_str)
        if d == datetime.min.date():
            continue
        if od and d < od:
            przed_okresem = prz
        elif not do or d <= do:
            w_okresie.append(prz)
    start = przed_okresem if przed_okresem is not None else (min(w_okresie) if w_okresie else None)
    koniec = max(w_okresie) if w_okresie else None
    return (koniec - start) if (start is not None and koniec is not None and koniec > start) else 0


def szacuj_przebieg_w_dniu(auto_id, data_str, punkty=None):
    """Licznik (km) w danym dniu z historii licznika: wpis z tego dnia, liniowo między
    sąsiednimi, po ostatnim — ostatni znany. None przed pierwszym wpisem i bez historii."""
    d = parsuj_date(data_str)
    if not auto_id or d == datetime.min.date():
        return None
    punkty = pobierz_historie_przebiegu(auto_id) if punkty is None else punkty
    poprzedni = None
    for tekst, km in punkty:
        dzien = parsuj_date(tekst)
        if dzien == d:
            return km
        if dzien > d:
            if not poprzedni:
                return None
            d0, km0 = poprzedni
            return int(round(km0 + (km - km0) * (d - d0).days / max(1, (dzien - d0).days)))
        poprzedni = (dzien, km)
    return poprzedni[1] if poprzedni else None


def dodaj_odczyt_przebiegu(auto_id, przebieg, data_str=None, notatka=None, zrodlo=ZRODLO_ODCZYTU_DOMYSLNE):
    """Ręczny odczyt licznika w osobnym dzienniku; odczyt z tego samego dnia jest
    nadpisywany. Zwraca True przy nadpisaniu, False przy nowym."""
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
                "INSERT INTO odczyty_przebiegu (auto_id, data, data_iso, przebieg, zrodlo) VALUES (?,?,?,?,?)",
                (auto_id, data_str, na_iso(data_str), przebieg, zrodlo)
            )
            rekord_id, nadpisano = kursor.lastrowid, False

    # Notatka POZA transakcją — zapisz_notatke otwiera własne połączenie (w otwartej
    # transakcji groziłoby zakleszczenie). Pustej celowo NIE zapisujemy: przy trafieniu
    # w istniejący odczyt wyczyściłaby jego notatkę.
    if przytnij_notatke(notatka):
        zapisz_notatke("odczyty_przebiegu", rekord_id, notatka)
    return nadpisano


# Krotność średniego dziennego przebiegu, od której skok licznika jest podejrzany
# (wakacyjny wyjazd daje 4–5× i to nie błąd); dolny próg chroni auta jeżdżące mało.
KROTNOSC_SKOKU_PRZEBIEGU = 6

MIN_SKOK_PRZEBIEGU_NA_DZIEN = 400


def pobierz_pelna_historie_przebiegu(auto_id) -> list[dict[str, Any]]:
    """WSZYSTKIE znane stany licznika (_stany_licznika) z informacją, SKĄD pochodzą i czy da
    się je stąd edytować; licznik wpisany przy okazji ma `notatka` None (ekran nie pokazuje
    wtedy notatki). Lista słowników rosnąco po
    (data, przebieg) z dystansem i dniami od poprzedniego, średnią dzienną odcinka i
    anomalią ('cofka'/'skok')."""
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

        # Przejazd z ewidencji niesie licznik tylko wtedy, gdy ktoś go wpisał.
        # Poprawia się go w formularzu przejazdu — stąd, jak tankowanie, nie.
        c.execute(
            "SELECT id, data, licznik, skad, dokad, cel, notatka, notatka_autor, notatka_data "
            "FROM przejazdy WHERE auto_id=? AND licznik IS NOT NULL", (auto_id,)
        )
        for r in c.fetchall():
            trasa_przejazdu = " – ".join(x for x in (r["skad"], r["dokad"]) if x)
            wpisy.append({
                "zrodlo": "przejazd", "podzrodlo": None,
                "id": r["id"], "data": r["data"], "przebieg": int(r["licznik"] or 0),
                "opis": trasa_przejazdu or r["cel"] or "Przejazd",
                "notatka": r["notatka"], "notatka_autor": r["notatka_autor"],
                "notatka_data": r["notatka_data"],
                "trasa": f"/ewidencja/edytuj/{r['id']}", "edytowalny": False,
            })

        c.execute("SELECT id, data, przebieg, plyn, notatka, notatka_autor, notatka_data FROM dolewki WHERE auto_id=?",
                  (auto_id,))
        for r in c.fetchall():
            wpisy.append({
                "zrodlo": "dolewka", "podzrodlo": None,
                "id": r["id"], "data": r["data"], "przebieg": int(r["przebieg"] or 0),
                "opis": RODZAJE_PLYNOW.get(r["plyn"], {}).get("nazwa", "Dolewka"),
                "notatka": r["notatka"], "notatka_autor": r["notatka_autor"],
                "notatka_data": r["notatka_data"],
                "trasa": f"/dolewki/edytuj/{r['id']}", "edytowalny": False,
            })

        # Licznik wpisany przy okazji: dzień i stan z _stany_licznika (tylko przyjęte), stąd opis i trasa.
        przy_okazji = [s for s in _stany_licznika(auto_id) if s[2] in ZRODLA_PRZY_OKAZJI]
        if przy_okazji:
            komplety = {r["id"]: " ".join(x for x in (r["sezon"], r["marka_model"]) if x) for r in c.execute(
                "SELECT id, sezon, marka_model FROM zestawy_opon WHERE auto_id=?", (auto_id,)).fetchall()}
            montaze = {r["id"]: r["zestaw_id"] for r in c.execute(
                "SELECT id, zestaw_id FROM montaze_opon WHERE auto_id=?", (auto_id,)).fetchall()}
            pomiary = {r["id"]: r["zestaw_id"] for r in c.execute(
                "SELECT id, zestaw_id FROM pomiary_bieznika WHERE auto_id=?", (auto_id,)).fetchall()}
            strefy = {r["id"]: r["strefa"] for r in c.execute(
                "SELECT id, strefa FROM zdjecia_karoserii WHERE auto_id=?", (auto_id,)).fetchall()}
            tytuly = {r["id"]: r["tytul"] for r in c.execute(
                "SELECT id, tytul FROM do_zrobienia WHERE auto_id=?", (auto_id,)).fetchall()}
        for _dzien, km, zrodlo, rekord_id, data_str, etap in przy_okazji:
            if zrodlo == "opony":
                zestaw_id = montaze.get(rekord_id)
                opis = f"{'Zdjęte' if etap else 'Założone'}: {komplety.get(zestaw_id) or 'komplet opon'}"
                trasa = f"/magazyn/opony/{zestaw_id}" if zestaw_id else "/magazyn"
            elif zrodlo == "bieznik":
                opis = komplety.get(pomiary.get(rekord_id)) or "Komplet opon"
                trasa = f"/magazyn/opony/pomiar/edytuj/{rekord_id}"
            elif zrodlo == "karoseria":
                opis, trasa = strefy.get(rekord_id) or "Zdjęcie", f"/karoseria/edytuj/{rekord_id}"
            else:
                opis, trasa = tytuly.get(rekord_id) or "Wykonana pozycja", "/do-zrobienia/wykonane"
            wpisy.append({
                "zrodlo": zrodlo, "podzrodlo": None, "id": rekord_id, "data": data_str, "przebieg": km,
                "opis": opis, "notatka": None, "notatka_autor": None, "notatka_data": None,
                "trasa": trasa, "edytowalny": False,
                "klucz": f"{zrodlo}_{rekord_id}" + (f"_{etap}" if etap else ""),
            })

    # Wpisy bez sensownego przebiegu (0 albo brak) nie mówią nic o liczniku —
    # w historii licznika byłyby wyłącznie szumem.
    wpisy = [w for w in wpisy if w["przebieg"] > 0]
    for w in wpisy:
        w["data_obj"] = parsuj_date(w["data"])
        w.setdefault("klucz", f"{w['zrodlo']}_{w['id']}")
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


def _zaokraglij_szacunek_km(km):
    """Szacunek podajemy w setkach kilometrów — pojedyncze udawałyby dokładność,
    której średnia nie ma. Poniżej 50 km nie ma o czym mówić."""
    if km is None or km < 50:
        return None
    return max(100, int(round(km / 100.0)) * 100)


def swiezosc_licznika(auto_id, dzis=None, aktualny_przebieg=None, sredni_dzienny=None) -> dict[str, Any] | None:
    """Świeżość stanu licznika, z którego liczą się WSZYSTKIE prognozy kilometrowe.
    `dni` — od ostatniego wpisu z przebiegiem (tego samego, co ostatni w „Historii
    licznika”; None bez przebiegu). `nieswiezy` — próg z Ustawień przekroczony albo brak
    przebiegu, przypominanie włączone, auto niesprzedane. `okres` — numer okresu ciszy
    (nowy = nowe powiadomienie); `przebieg` (pobierz_aktualny_przebieg); `przybylo_km` —
    szacunek w setkach km albo None. `aktualny_przebieg` i `sredni_dzienny` może podać
    wołający. None tylko bez auta."""
    if not auto_id:
        return None
    with polacz_baze() as conn:
        w = conn.execute("SELECT status FROM samochody WHERE id=?", (auto_id,)).fetchone()
    if not w:
        return None

    dzis = dzis or datetime.now().date()
    aktywny = str(w[0] or STATUS_POJAZDU_AKTYWNY) == STATUS_POJAZDU_AKTYWNY
    prog = pobierz_dni_przypomnienia_o_odczycie()

    punkty = pobierz_historie_przebiegu(auto_id)
    data = dni = przebieg = None
    if punkty:
        data = parsuj_date(punkty[-1][0])
        dni = max(0, (dzis - data).days)
        przebieg = aktualny_przebieg or pobierz_aktualny_przebieg(auto_id) or punkty[-1][1]

    nieswiezy = bool(aktywny and prog > 0 and (dni is None or dni >= prog))
    okres = 0
    przybylo_km = None
    if nieswiezy:
        okres = dni // prog if dni is not None else 1
        if dni:
            sredni = sredni_dzienny or oblicz_sredni_dzienny_przebieg(auto_id, punkty=punkty)
            if sredni:
                przybylo_km = _zaokraglij_szacunek_km(sredni * dni)

    return {
        "dni": dni,
        "data": data,
        "przebieg": przebieg,
        "prog": prog,
        "aktywny": aktywny,
        "nieswiezy": nieswiezy,
        "okres": okres,
        "przybylo_km": przybylo_km,
    }


def aktualizuj_odczyt_przebiegu(odczyt_id, przebieg, data_str):
    """Edycja konkretnego, istniejącego odczytu (z poziomu listy historii) —
    aktualizuje po ID, bez logiki upsert po dacie użytej w dodaj_odczyt_przebiegu."""
    with polacz_baze() as conn:
        conn.execute(
            "UPDATE odczyty_przebiegu SET przebieg=?, data=?, data_iso=? WHERE id=?",
            (przebieg, data_str, na_iso(data_str), odczyt_id)
        )


def aktualizuj_najnowszy_wpis(zadanie_id):
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT data, przebieg FROM historia WHERE zadanie_id = ?", (zadanie_id,))
        wpisy = c.fetchall()
        if wpisy:
            wpisy.sort(key=lambda x: (parsuj_date(x[0]), int(x[1] or 0)), reverse=True)
            c.execute("UPDATE zadania SET data=?, data_iso=?, przebieg=? WHERE id=?",
                      (wpisy[0][0], na_iso(wpisy[0][0]), int(wpisy[0][1] or 0), zadanie_id))
        else:
            c.execute("UPDATE zadania SET data=NULL, data_iso=NULL, przebieg=NULL WHERE id=?", (zadanie_id,))


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
    "TempoJazdy",
    "ZRODLA_PRZY_OKAZJI",
    "aktualizuj_najnowszy_wpis",
    "aktualizuj_odczyt_przebiegu",
    "dodaj_odczyt_przebiegu",
    "oblicz_sredni_dzienny_przebieg",
    "pobierz_aktualny_przebieg",
    "pobierz_historie_przebiegu",
    "pobierz_pelna_historie_przebiegu",
    "podsumowanie_historii_przebiegu",
    "prognoza_z_tempa",
    "przejechane_km",
    "przelicz_wszystkie_zadania",
    "sprawdz_czy_koszt_duplikat",
    "sprawdz_czy_przebieg_podejrzany",
    "sprawdz_czy_tankowanie_duplikat",
    "swiezosc_licznika",
    "szacuj_przebieg_w_dniu",
]
