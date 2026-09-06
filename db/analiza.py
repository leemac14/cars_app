"""Budżety, prognozy, trendy, podsumowanie roku i obserwacje."""

import sqlite3
from date import parsuj_date
from datetime import date as date_cls, datetime, timedelta

from .stale import ENERGIA_PALIWO, ENERGIA_PRAD
from .polaczenie import polacz_baze
from .pomocnicze import _liczba_lub_none, formatuj_liczba_eksport
from .ustawienia import pobierz_walute
from .synchronizacja import zarejestruj_nagrobek
from .energia import domyslny_rodzaj_energii, formatuj_zuzycie_tekst, rodzaje_energii_pojazdu
from .przebieg import oblicz_sredni_dzienny_przebieg, pobierz_aktualny_przebieg, pobierz_historie_przebiegu
from .koszty import DNI_W_MIESIACU, KATEGORIE_BUDZETU, _wiersze_kosztow, klucz_stacji, koszty_w_okresie, pobierz_trend_cen_paliwa
from .statystyki import pobierz_serie_spalania


# ==================== ANALIZA, PROGNOZY I BUDŻETY ====================
# Ta sekcja odpowiada na pytania, na które sama tabela liczb nie odpowiada:
# czy jest lepiej czy gorzej, ile to będzie kosztować do końca roku i czy zdążę
# przed własnym limitem. Wszystko liczone z danych, które użytkownik już wpisał —
# żadnych nowych obowiązków przy dodawaniu wpisu.
# db.py nie zna Fleta (korzysta z niego też eksport PDF i synchronizacja), więc
# obserwacje wracają stąd z KLUCZEM ikony i tonem, a nie z gotową kontrolką.

OKRESY_BUDZETU = {"miesiac": "Miesięcznie", "rok": "Rocznie"}


# Od ilu procent limitu budżet przestaje być „w normie”. 80% wybrane świadomie:
# przy 90% na reakcję jest już zwykle za późno.
PROG_UWAGI_BUDZETU = 0.80


# Zmiana spalania poniżej tego progu to szum (inna stacja, inaczej dolany „pełny”
# bak, jedna trasa autostradą), a nie trend — nie ma o czym informować.
PROG_ISTOTNOSCI_TRENDU = 5.0


# Dystanse do porównań w „Roku w pigułce”. Cel jest jeden: zamienić 18 000 km
# w coś, co da się sobie wyobrazić.
_DYSTANSE_ODNIESIENIA = [
    (40075, "okrążenie Ziemi wzdłuż równika"),
    (10000, "przejazd z Polski do Indii"),
    (3000, "przejazd z Warszawy do Lizbony"),
    (1600, "przejazd z Warszawy do Paryża"),
    (600, "przejazd z Warszawy do Berlina"),
    (300, "przejazd z Warszawy do Krakowa"),
]


# -------------------- BUDŻETY --------------------

def pobierz_budzety(auto_id):
    """Ustawione limity pojazdu: [{kategoria, okres, kwota}] w stałej kolejności
    (kategorie jak w KATEGORIE_BUDZETU, miesięczne przed rocznymi)."""
    if not auto_id:
        return []
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT kategoria, okres, kwota FROM budzety WHERE auto_id=? AND kwota > 0", (auto_id,))
        wiersze = c.fetchall()

    kolejnosc_kat = list(KATEGORIE_BUDZETU)
    kolejnosc_okr = list(OKRESY_BUDZETU)
    budzety = [
        {"kategoria": k, "okres": o, "kwota": float(kw or 0)}
        for k, o, kw in wiersze
        if k in KATEGORIE_BUDZETU and o in OKRESY_BUDZETU
    ]
    budzety.sort(key=lambda b: (kolejnosc_okr.index(b["okres"]), kolejnosc_kat.index(b["kategoria"])))
    return budzety


def zapisz_budzet(auto_id, kategoria, okres, kwota):
    """Ustawia albo kasuje limit (kwota <= 0 = brak limitu). Upsert po
    (auto_id, kategoria, okres) — ten sam limit nie może istnieć dwa razy."""
    if not auto_id or kategoria not in KATEGORIE_BUDZETU or okres not in OKRESY_BUDZETU:
        return False
    try:
        wartosc = float(kwota or 0)
    except (TypeError, ValueError):
        wartosc = 0.0

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT id FROM budzety WHERE auto_id=? AND kategoria=? AND okres=?", (auto_id, kategoria, okres))
        w = c.fetchone()
        if wartosc <= 0:
            if w:
                # Nagrobek, żeby skasowany limit zniknął też u współdzielących —
                # bez tego wróciłby przy najbliższej synchronizacji.
                c.execute("SELECT zdalne_id FROM budzety WHERE id=?", (w[0],))
                zdalne = c.fetchone()
                conn.execute("DELETE FROM budzety WHERE id=?", (w[0],))
                if zdalne and zdalne[0]:
                    zarejestruj_nagrobek("budzety", zdalne[0])
            return True
        if w:
            conn.execute("UPDATE budzety SET kwota=? WHERE id=?", (wartosc, w[0]))
        else:
            conn.execute(
                "INSERT INTO budzety (auto_id, kategoria, okres, kwota) VALUES (?,?,?,?)",
                (auto_id, kategoria, okres, wartosc)
            )
    return True


def _granice_okresu(okres, dzis=None):
    """(początek, koniec, dni_okresu, dni_minione) bieżącego miesiąca albo roku.
    'dni_minione' liczy dzisiejszy dzień jako miniony — inaczej pierwszego dnia
    okresu tempo wydatków dzieliłoby przez zero."""
    dzis = dzis or datetime.now().date()
    if okres == "rok":
        poczatek = date_cls(dzis.year, 1, 1)
        koniec = date_cls(dzis.year, 12, 31)
    else:
        poczatek = date_cls(dzis.year, dzis.month, 1)
        if dzis.month == 12:
            koniec = date_cls(dzis.year, 12, 31)
        else:
            koniec = date_cls(dzis.year, dzis.month + 1, 1) - timedelta(days=1)
    dni_okresu = (koniec - poczatek).days + 1
    dni_minione = max(1, (dzis - poczatek).days + 1)
    return poczatek, koniec, dni_okresu, dni_minione


def stan_budzetow(auto_id, dzis=None):
    """Stan wykorzystania każdego ustawionego limitu. Dla każdego zwraca m.in.:
    wydano, limit, procent, pozostalo, tempo (prognoza całego okresu przy
    dotychczasowym tempie), status ('ok' / 'uwaga' / 'przekroczony') oraz
    'dzien_przekroczenia' — datę, na którą wypada wyczerpanie limitu, jeśli
    tempo się utrzyma. To ostatnie jest sednem: ostrzeżenie ma przyjść ZANIM
    limit padnie, a nie w dniu, w którym już nic się nie da zrobić."""
    budzety = pobierz_budzety(auto_id)
    if not budzety:
        return []

    dzis = dzis or datetime.now().date()
    cache_kosztow = {}
    wynik = []

    for b in budzety:
        poczatek, koniec, dni_okresu, dni_minione = _granice_okresu(b["okres"], dzis)
        if b["okres"] not in cache_kosztow:
            cache_kosztow[b["okres"]] = koszty_w_okresie(auto_id, poczatek, dzis)
        wydano = cache_kosztow[b["okres"]][b["kategoria"]]
        limit = b["kwota"]

        procent = (wydano / limit * 100) if limit > 0 else 0.0
        na_dzien = wydano / dni_minione
        tempo = na_dzien * dni_okresu

        if wydano > limit:
            status = "przekroczony"
        elif procent >= PROG_UWAGI_BUDZETU * 100 or tempo > limit:
            status = "uwaga"
        else:
            status = "ok"

        dzien_przekroczenia = None
        if status != "przekroczony" and na_dzien > 0 and limit > 0:
            dni_do_limitu = limit / na_dzien
            if dni_do_limitu <= dni_okresu:
                kandydat = poczatek + timedelta(days=int(dni_do_limitu))
                if kandydat > dzis:
                    dzien_przekroczenia = kandydat

        wynik.append({
            "kategoria": b["kategoria"],
            "etykieta_kategorii": KATEGORIE_BUDZETU[b["kategoria"]],
            "okres": b["okres"],
            "etykieta_okresu": OKRESY_BUDZETU[b["okres"]],
            "limit": limit,
            "wydano": wydano,
            "pozostalo": limit - wydano,
            "procent": procent,
            "tempo": tempo,
            "status": status,
            "dni_okresu": dni_okresu,
            "dni_minione": min(dni_minione, dni_okresu),
            "dni_pozostalo": max(0, (koniec - dzis).days),
            "dzien_przekroczenia": dzien_przekroczenia.strftime("%d.%m.%Y") if dzien_przekroczenia else None,
            "poczatek": poczatek,
            "koniec": koniec,
        })

    # Najpierw to, co się pali: przekroczone, potem ostrzeżenia, potem reszta.
    waga_statusu = {"przekroczony": 0, "uwaga": 1, "ok": 2}
    wynik.sort(key=lambda b: (waga_statusu[b["status"]], -b["procent"]))
    return wynik


# -------------------- TREND ZUŻYCIA --------------------

def analizuj_trend_spalania(auto_id, rodzaj=None, ostatnie=3, tlo=6):
    """Porównuje zużycie z OSTATNICH odcinków ze średnią z odcinków
    wcześniejszych i mówi, czy auto zaczęło palić więcej.

    Odcinek = trasa między dwoma tankowaniami „do pełna” (patrz
    pobierz_serie_spalania), bo tylko tam ilość paliwa odpowiada przejechanym
    kilometrom. Świadomie NIE porównujemy „miesiąc do miesiąca”: przy dwóch
    tankowaniach na miesiąc taki podział daje skoki rzędu 20%, które są
    wyłącznie efektem tego, gdzie wypadła granica kalendarza.

    Zwraca None, dopóki nie ma czym porównywać (min. `ostatnie` + 2 odcinki) —
    lepiej nie powiedzieć nic, niż ogłosić trend z dwóch pomiarów."""
    if not auto_id:
        return None

    rodzaj = rodzaj or domyslny_rodzaj_energii(auto_id)
    seria = pobierz_serie_spalania(auto_id, limit=None, rodzaj=rodzaj)
    if len(seria) < ostatnie + 2:
        return None

    wartosci = [w for _, w in seria]
    ostatnie_w = wartosci[-ostatnie:]
    wczesniejsze = wartosci[max(0, len(wartosci) - ostatnie - tlo):-ostatnie]
    if not wczesniejsze:
        return None

    sr_ostatnie = sum(ostatnie_w) / len(ostatnie_w)
    sr_wczesniej = sum(wczesniejsze) / len(wczesniejsze)
    if sr_wczesniej <= 0:
        return None

    zmiana = (sr_ostatnie - sr_wczesniej) / sr_wczesniej * 100
    if abs(zmiana) < PROG_ISTOTNOSCI_TRENDU:
        kierunek = "stabilnie"
    elif zmiana > 0:
        kierunek = "wzrost"
    else:
        kierunek = "spadek"

    najstarsza = parsuj_date(seria[max(0, len(seria) - ostatnie - tlo)][0])
    najnowsza = parsuj_date(seria[-1][0])
    dni_okna = (najnowsza - najstarsza).days if najnowsza > najstarsza else 0

    return {
        "rodzaj": rodzaj,
        "srednia_ostatnia": sr_ostatnie,
        "srednia_wczesniej": sr_wczesniej,
        "zmiana_proc": zmiana,
        "kierunek": kierunek,
        "odcinkow_ostatnio": len(ostatnie_w),
        "odcinkow_wczesniej": len(wczesniejsze),
        "dni_okna": dni_okna,
        "data_ostatniego": seria[-1][0],
        # Różnica w koszcie na 100 km — sam procent nie mówi, czy to problem
        # wart reakcji, czy pół złotówki.
        "roznica_na_100km": sr_ostatnie - sr_wczesniej,
    }


def koszt_trendu_rocznie(auto_id, trend):
    """Ile kosztuje (albo oszczędza) zmiana zużycia z analizuj_trend_spalania,
    przeliczona na rok przy dotychczasowym przebiegu rocznym i ostatniej znanej
    cenie jednostkowej. Procent robi wrażenie, ale dopiero złotówki na rok
    odpowiadają na pytanie, czy warto jechać do mechanika."""
    if not trend or trend["kierunek"] == "stabilnie":
        return None

    sredni_dzienny = oblicz_sredni_dzienny_przebieg(auto_id)
    if not sredni_dzienny:
        return None

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT kwota, litry FROM tankowania "
            "WHERE auto_id=? AND COALESCE(rodzaj_energii, ?) = ? AND litry > 0 "
            "ORDER BY id DESC LIMIT 5",
            (auto_id, domyslny_rodzaj_energii(auto_id), trend["rodzaj"])
        )
        ostatnie = c.fetchall()
    if not ostatnie:
        return None

    litry_razem = sum(float(r[1] or 0) for r in ostatnie)
    if litry_razem <= 0:
        return None
    cena_jedn = sum(float(r[0] or 0) for r in ostatnie) / litry_razem

    km_rocznie = sredni_dzienny * 365
    roznica_jednostek = trend["roznica_na_100km"] / 100 * km_rocznie
    return roznica_jednostek * cena_jedn


# -------------------- ZASIĘG NA BAKU --------------------

def pobierz_zasieg_na_baku(auto_id):
    """Zasięg auta spalinowego: ile przejedzie na PEŁNYM baku i ile zostało
    od ostatniego tankowania do pełna.

    Ta druga liczba jest szacunkiem z licznika, nie odczytem z pływaka: bierzemy
    kilometry przejechane od ostatniego pełnego baku i mnożymy przez rzeczywiste
    zużycie. Dlatego zwracamy też 'pewnosc' i 'dni_od_tankowania' — im starsze
    tankowanie, tym większa szansa, że po drodze ktoś dolał paliwa bez wpisu.

    Zwraca None, gdy nie podano pojemności baku albo nie da się policzyć
    zużycia (mniej niż dwa tankowania „do pełna”)."""
    if not auto_id:
        return None

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT pojemnosc_baku FROM samochody WHERE id=?", (auto_id,))
        w = c.fetchone()
    pojemnosc = _liczba_lub_none(w[0]) if w else None
    if not pojemnosc:
        return None

    rodzaj = ENERGIA_PALIWO
    if rodzaj not in rodzaje_energii_pojazdu(auto_id):
        return None

    seria = pobierz_serie_spalania(auto_id, limit=5, rodzaj=rodzaj)
    if not seria:
        return None
    spalanie = sum(w for _, w in seria) / len(seria)
    if spalanie <= 0:
        return None

    zasieg_pelny = pojemnosc / spalanie * 100

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT data, przebieg FROM tankowania "
            "WHERE auto_id=? AND COALESCE(rodzaj_energii, ?) = ? AND do_pelna=1",
            (auto_id, domyslny_rodzaj_energii(auto_id), rodzaj)
        )
        pelne = c.fetchall()

    wynik = {
        "pojemnosc": pojemnosc,
        "spalanie": spalanie,
        "zasieg_pelny": zasieg_pelny,
        "odcinkow": len(seria),
        "przejechane": None,
        "pozostalo_jednostek": None,
        "zasieg_pozostaly": None,
        "procent_baku": None,
        "data_tankowania": None,
        "dni_od_tankowania": None,
        "pewnosc": "brak",
    }

    if not pelne:
        return wynik

    # Ostatnie tankowanie do pełna: po dacie, przy remisie po przebiegu — ta sama
    # kolejność co wszędzie indziej, żeby dwa tankowania jednego dnia nie dały
    # ujemnego dystansu.
    ostatnie = max(pelne, key=lambda r: (parsuj_date(r[0]), int(r[1] or 0)))
    data_tank = parsuj_date(ostatnie[0])
    przebieg_tank = int(ostatnie[1] or 0)
    aktualny = pobierz_aktualny_przebieg(auto_id) or 0

    przejechane = aktualny - przebieg_tank
    if przejechane < 0:
        return wynik

    zuzyte = przejechane * spalanie / 100
    pozostalo = pojemnosc - zuzyte
    dni = (datetime.now().date() - data_tank).days if data_tank != datetime.min.date() else None

    wynik.update({
        "przejechane": przejechane,
        "pozostalo_jednostek": max(0.0, pozostalo),
        "zasieg_pozostaly": max(0.0, pozostalo / spalanie * 100),
        "procent_baku": max(0.0, min(100.0, pozostalo / pojemnosc * 100)),
        "data_tankowania": ostatnie[0],
        "dni_od_tankowania": dni,
        # Szacunek starzeje się szybko: po dwóch tygodniach od tankowania szansa,
        # że ktoś dolał paliwa bez wpisu, jest już spora.
        "pewnosc": "niska" if (dni is None or dni > 21) else ("srednia" if dni > 7 else "wysoka"),
    })
    return wynik


# -------------------- PROGNOZA KOSZTÓW --------------------

def prognoza_kosztow(auto_id, dzis=None, miesiecy_bazowych=6):
    """Ekstrapolacja wydatków do końca roku ze średniej z OSTATNICH PEŁNYCH
    miesięcy. Bieżący miesiąc jest z podstawy wykluczony — 3. dnia miesiąca
    zaniżałby średnią o dwie trzecie, a to właśnie na początku miesiąca ktoś
    najczęściej zagląda w prognozę.

    Zwraca None, gdy nie ma ani jednego pełnego miesiąca z wydatkami: prognoza
    z jednego tankowania to nie prognoza, tylko losowa liczba."""
    if not auto_id:
        return None

    dzis = dzis or datetime.now().date()
    koniec_roku = date_cls(dzis.year, 12, 31)

    # Pełne miesiące wstecz, licząc od miesiąca poprzedzającego bieżący.
    okresy = []
    rok, miesiac = dzis.year, dzis.month
    for _ in range(miesiecy_bazowych):
        miesiac -= 1
        if miesiac == 0:
            miesiac, rok = 12, rok - 1
        okresy.append((rok, miesiac))

    with polacz_baze() as conn:
        wiersze = _wiersze_kosztow(conn, auto_id)

    sumy_miesiecy = {o: 0.0 for o in okresy}
    wydano_w_roku = 0.0
    wydano_kategorie = {k: 0.0 for k in KATEGORIE_BUDZETU}
    poprzedni_rok_suma = 0.0
    najstarsza_data = None

    for data_str, kwota, kategoria in wiersze:
        d = parsuj_date(data_str)
        if d == datetime.min.date():
            continue
        wartosc = float(kwota or 0.0)
        if najstarsza_data is None or d < najstarsza_data:
            najstarsza_data = d
        klucz = (d.year, d.month)
        if klucz in sumy_miesiecy:
            sumy_miesiecy[klucz] += wartosc
        if d.year == dzis.year and d <= dzis:
            wydano_w_roku += wartosc
            wydano_kategorie[kategoria] += wartosc
            wydano_kategorie["razem"] += wartosc
        elif d.year == dzis.year - 1:
            poprzedni_rok_suma += wartosc

    # Miesiące SPRZED pierwszego wpisu nie są „miesiącem bez wydatków” — to
    # miesiące, w których aplikacja nie znała jeszcze tego auta. Wliczenie ich
    # jako zer rozcieńczyłoby średnią do zera.
    pelne_miesiace = [
        suma for (r, m), suma in sumy_miesiecy.items()
        if najstarsza_data is not None and (r, m) >= (najstarsza_data.year, najstarsza_data.month)
    ]
    if not pelne_miesiace or sum(pelne_miesiace) <= 0:
        return None

    srednia_miesieczna = sum(pelne_miesiace) / len(pelne_miesiace)
    dni_pozostalo = max(0, (koniec_roku - dzis).days)
    prognoza_do_konca = srednia_miesieczna / DNI_W_MIESIACU * dni_pozostalo
    prognoza_calego_roku = wydano_w_roku + prognoza_do_konca

    if len(pelne_miesiace) >= 4:
        pewnosc = "wysoka"
    elif len(pelne_miesiace) >= 2:
        pewnosc = "srednia"
    else:
        pewnosc = "niska"

    return {
        "srednia_miesieczna": srednia_miesieczna,
        "miesiecy_bazowych": len(pelne_miesiace),
        "wydano_w_roku": wydano_w_roku,
        "wydano_kategorie": wydano_kategorie,
        "prognoza_do_konca": prognoza_do_konca,
        "prognoza_calego_roku": prognoza_calego_roku,
        "dni_pozostalo": dni_pozostalo,
        "rok": dzis.year,
        "poprzedni_rok": poprzedni_rok_suma if poprzedni_rok_suma > 0 else None,
        "zmiana_rdr": (
            (prognoza_calego_roku - poprzedni_rok_suma) / poprzedni_rok_suma * 100
            if poprzedni_rok_suma > 0 else None
        ),
        "pewnosc": pewnosc,
    }


# -------------------- ROK W PIGUŁCE --------------------

def _porownanie_dystansu(km):
    """Zamienia przebieg w obraz („to prawie okrążenie Ziemi”). Bierzemy
    największy dystans odniesienia, który mieści się w przejechanym — tak, żeby
    porównanie zawsze brzmiało jak osiągnięcie, a nie jak wymówka."""
    if not km or km <= 0:
        return None
    for dystans, opis in _DYSTANSE_ODNIESIENIA:
        if km >= dystans:
            razy = km / dystans
            if razy >= 1.9:
                return f"{opis} — {formatuj_liczba_eksport(razy, 1)} raza"
            return f"prawie {opis}"
    return None


def podsumowanie_roku(auto_id, rok=None):
    """Wszystko, co da się powiedzieć o jednym roku pojazdu: przejechane
    kilometry, koszty w rozbiciu, najdroższy i najtańszy miesiąc, ulubiona
    stacja, największy pojedynczy wydatek, średnie zużycie i porównanie z rokiem
    poprzednim. Podstawa ekranu „Rok w pigułce” i generowanej z niego grafiki.

    Zwraca None dla roku bez ani jednego wpisu — pusty ekran z sześcioma zerami
    nie jest podsumowaniem."""
    if not auto_id:
        return None
    rok = int(rok or datetime.now().year)
    poczatek, koniec = date_cls(rok, 1, 1), date_cls(rok, 12, 31)
    dzis = datetime.now().date()
    granica = min(koniec, dzis) if rok == dzis.year else koniec

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        wiersze_kosztow = _wiersze_kosztow(conn, auto_id)
        c.execute(
            "SELECT data, przebieg, litry, kwota, stacja, do_pelna, rodzaj_energii "
            "FROM tankowania WHERE auto_id=?", (auto_id,)
        )
        tankowania = [dict(r) for r in c.fetchall()]
        c.execute("SELECT data, nazwa, kwota FROM inne_koszty WHERE auto_id=?", (auto_id,))
        inne = [dict(r) for r in c.fetchall()]
        c.execute(
            "SELECT h.data, h.cena, z.nazwa FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE z.auto_id=? AND h.wizyta_id IS NULL", (auto_id,)
        )
        serwis_wpisy = [dict(r) for r in c.fetchall()]
        c.execute("SELECT data, koszt_calkowity, wykonawca FROM wizyty WHERE auto_id=?", (auto_id,))
        wizyty_wpisy = [dict(r) for r in c.fetchall()]

    # --- koszty roku i rozkład na miesiące ---
    kategorie = {k: 0.0 for k in KATEGORIE_BUDZETU}
    miesiace = {m: 0.0 for m in range(1, 13)}
    miesiace_z_danymi = set()
    for data_str, kwota, kategoria in wiersze_kosztow:
        d = parsuj_date(data_str)
        if d == datetime.min.date() or d.year != rok or d > granica:
            continue
        wartosc = float(kwota or 0.0)
        kategorie[kategoria] += wartosc
        kategorie["razem"] += wartosc
        miesiace[d.month] += wartosc
        miesiace_z_danymi.add(d.month)

    if not miesiace_z_danymi:
        return None

    aktywne = {m: miesiace[m] for m in sorted(miesiace_z_danymi)}
    najdrozszy = max(aktywne.items(), key=lambda kv: kv[1])
    najtanszy = min(aktywne.items(), key=lambda kv: kv[1])

    # --- kilometry ---
    historia_prz = pobierz_historie_przebiegu(auto_id)
    przed_rokiem, w_roku = None, []
    for data_str, prz in historia_prz:
        d = parsuj_date(data_str)
        if d == datetime.min.date():
            continue
        if d < poczatek:
            przed_rokiem = prz
        elif d <= granica:
            w_roku.append(prz)
    # Punkt startowy to ostatni odczyt SPRZED roku, jeśli istnieje — inaczej
    # styczniowy przebieg policzyłby się jako „przejechane od zera”.
    start = przed_rokiem if przed_rokiem is not None else (min(w_roku) if w_roku else None)
    koniec_prz = max(w_roku) if w_roku else None
    km = (koniec_prz - start) if (start is not None and koniec_prz is not None and koniec_prz > start) else 0

    # --- tankowania roku ---
    tank_roku = []
    for t in tankowania:
        d = parsuj_date(t.get("data"))
        if d != datetime.min.date() and d.year == rok and d <= granica:
            tank_roku.append(t)

    litry = sum(float(t.get("litry") or 0) for t in tank_roku
                if (t.get("rodzaj_energii") or ENERGIA_PALIWO) == ENERGIA_PALIWO)
    kwh = sum(float(t.get("litry") or 0) for t in tank_roku
              if t.get("rodzaj_energii") == ENERGIA_PRAD)

    # Ulubiona stacja — po liczbie tankowań, z kanoniczną pisownią z grupy.
    grupy_stacji = {}
    for t in tank_roku:
        nazwa = " ".join(str(t.get("stacja") or "").split())
        klucz = klucz_stacji(nazwa)
        if not klucz:
            continue
        grupa = grupy_stacji.setdefault(klucz, {"ile": 0, "kwota": 0.0, "warianty": {}})
        grupa["ile"] += 1
        grupa["kwota"] += float(t.get("kwota") or 0)
        grupa["warianty"][nazwa] = grupa["warianty"].get(nazwa, 0) + 1
    ulubiona = None
    if grupy_stacji:
        klucz_top = max(grupy_stacji.items(), key=lambda kv: (kv[1]["ile"], kv[1]["kwota"]))
        ulubiona = {
            "nazwa": max(klucz_top[1]["warianty"].items(), key=lambda kv: (kv[1], kv[0]))[0],
            "liczba": klucz_top[1]["ile"],
            "kwota": klucz_top[1]["kwota"],
        }

    # --- średnie zużycie roku: odcinki zamknięte W TYM roku ---
    seria = pobierz_serie_spalania(auto_id, limit=None, rodzaj=domyslny_rodzaj_energii(auto_id))
    zuzycie_roku = [w for data_str, w in seria
                    if parsuj_date(data_str) != datetime.min.date()
                    and parsuj_date(data_str).year == rok]
    srednie_zuzycie = (sum(zuzycie_roku) / len(zuzycie_roku)) if zuzycie_roku else None

    # --- największy pojedynczy wydatek ---
    kandydaci = []
    for w in inne:
        kandydaci.append((w.get("data"), float(w.get("kwota") or 0), str(w.get("nazwa") or "Inny koszt")))
    for w in serwis_wpisy:
        kandydaci.append((w.get("data"), float(w.get("cena") or 0), str(w.get("nazwa") or "Serwis")))
    for w in wizyty_wpisy:
        kandydaci.append((w.get("data"), float(w.get("koszt_calkowity") or 0),
                          f"Wizyta: {w.get('wykonawca') or 'warsztat'}"))
    for t in tank_roku:
        kandydaci.append((t.get("data"), float(t.get("kwota") or 0),
                          f"Tankowanie: {t.get('stacja') or 'stacja nieznana'}"))
    kandydaci = [k for k in kandydaci
                 if parsuj_date(k[0]) != datetime.min.date()
                 and parsuj_date(k[0]).year == rok and parsuj_date(k[0]) <= granica and k[1] > 0]
    najwiekszy = max(kandydaci, key=lambda k: k[1]) if kandydaci else None

    # --- porównanie z poprzednim rokiem ---
    poprzedni = 0.0
    for data_str, kwota, _kat in wiersze_kosztow:
        d = parsuj_date(data_str)
        if d != datetime.min.date() and d.year == rok - 1:
            poprzedni += float(kwota or 0.0)

    return {
        "rok": rok,
        "niepelny": rok == dzis.year,
        "km": km,
        "koszty": kategorie,
        "koszt_km": (kategorie["razem"] / km) if km > 0 else None,
        "miesiace": miesiace,
        "najdrozszy_miesiac": {"miesiac": najdrozszy[0], "kwota": najdrozszy[1]},
        "najtanszy_miesiac": {"miesiac": najtanszy[0], "kwota": najtanszy[1]},
        "liczba_tankowan": len(tank_roku),
        "litry": litry,
        "kwh": kwh,
        "ulubiona_stacja": ulubiona,
        "srednie_zuzycie": srednie_zuzycie,
        "liczba_wizyt": len([w for w in wizyty_wpisy
                             if parsuj_date(w.get("data")) != datetime.min.date()
                             and parsuj_date(w.get("data")).year == rok]),
        "liczba_wpisow_serwisu": len([w for w in serwis_wpisy
                                      if parsuj_date(w.get("data")) != datetime.min.date()
                                      and parsuj_date(w.get("data")).year == rok]),
        "najwiekszy_wydatek": ({"data": najwiekszy[0], "kwota": najwiekszy[1], "opis": najwiekszy[2]}
                               if najwiekszy else None),
        "poprzedni_rok": poprzedni if poprzedni > 0 else None,
        "zmiana_rdr": ((kategorie["razem"] - poprzedni) / poprzedni * 100) if poprzedni > 0 else None,
        "porownanie_dystansu": _porownanie_dystansu(km),
        "sredni_koszt_miesiaca": (kategorie["razem"] / len(miesiace_z_danymi)) if miesiace_z_danymi else 0.0,
    }


def lata_z_danymi(auto_id):
    """Lata, w których pojazd ma jakikolwiek wpis — malejąco. Selektor roku w
    „Roku w pigułce” pokazuje tylko te, dla których jest co pokazywać."""
    if not auto_id:
        return []
    with polacz_baze() as conn:
        wiersze = _wiersze_kosztow(conn, auto_id)
    lata = set()
    for data_str, _kwota, _kat in wiersze:
        d = parsuj_date(data_str)
        if d != datetime.min.date():
            lata.add(d.year)
    return sorted(lata, reverse=True)


# -------------------- SILNIK OBSERWACJI --------------------
# Jedno miejsce, w którym liczby zamieniają się w zdania. Każda reguła zwraca
# obserwację z WAGĄ; kokpit bierze najważniejszą, zakładka Analiza wszystkie.
# Reguła, która nie ma nic sensownego do powiedzenia, nie zwraca nic — cisza
# jest lepsza niż „wszystko w normie” powtarzane przy każdym uruchomieniu.

def _obserwacja(klucz, ton, ikona, tytul, tekst, waga, trasa=None):
    return {"klucz": klucz, "ton": ton, "ikona": ikona, "tytul": tytul,
            "tekst": tekst, "waga": waga, "trasa": trasa}


def _kwota_txt(wartosc, decimale=0):
    return f"{formatuj_liczba_eksport(wartosc, decimale)} {pobierz_walute()}"


def obserwacje_analityczne(auto_id, limit=None):
    """Lista automatycznych spostrzeżeń o pojeździe, posortowana malejąco po
    ważności. Każde ma 'ton' ('zly' / 'uwaga' / 'dobry' / 'neutralny'), klucz
    ikony i — gdy jest dokąd pójść — trasę do odpowiedniego ekranu."""
    if not auto_id:
        return []

    obserwacje = []
    dzis = datetime.now().date()

    # 1. Budżety — najpilniejsze, bo dotyczą pieniędzy, które właśnie wyciekają.
    for b in stan_budzetow(auto_id, dzis):
        etykieta = f"{b['etykieta_kategorii'].lower()} ({b['etykieta_okresu'].lower()})"
        if b["status"] == "przekroczony":
            obserwacje.append(_obserwacja(
                f"budzet_{b['kategoria']}_{b['okres']}", "zly", "budzet",
                "Budżet przekroczony",
                f"Limit na {etykieta} przekroczony o {_kwota_txt(abs(b['pozostalo']))} "
                f"({formatuj_liczba_eksport(b['procent'], 0)}% limitu).",
                100, "/budzet",
            ))
        elif b["status"] == "uwaga":
            if b["dzien_przekroczenia"]:
                tekst = (f"Przy obecnym tempie limit na {etykieta} skończy się "
                         f"{b['dzien_przekroczenia']} — {b['dni_pozostalo']} dni przed końcem okresu.")
            else:
                tekst = (f"Wykorzystane {formatuj_liczba_eksport(b['procent'], 0)}% limitu na {etykieta}, "
                         f"zostało {_kwota_txt(b['pozostalo'])}.")
            obserwacje.append(_obserwacja(
                f"budzet_{b['kategoria']}_{b['okres']}", "uwaga", "budzet",
                "Budżet pod presją", tekst, 90, "/budzet",
            ))

    # 2. Zasięg na baku — jedyna obserwacja, która może uratować przed pchaniem auta.
    bak = pobierz_zasieg_na_baku(auto_id)
    if bak and bak.get("zasieg_pozostaly") is not None and bak["pewnosc"] in ("wysoka", "srednia"):
        if bak["zasieg_pozostaly"] < 80:
            obserwacje.append(_obserwacja(
                "bak_niski", "uwaga", "bak", "Czas zatankować",
                f"Szacunkowo zostało około {formatuj_liczba_eksport(bak['zasieg_pozostaly'], 0)} km "
                f"({formatuj_liczba_eksport(bak['procent_baku'], 0)}% baku).",
                85, "/tankowanie/nowe",
            ))

    # 3. Trend zużycia — to, o co pyta się najczęściej po zatankowaniu.
    trend = analizuj_trend_spalania(auto_id)
    if trend and trend["kierunek"] != "stabilnie":
        czy_prad = trend["rodzaj"] == ENERGIA_PRAD
        # Wartości podajemy w jednostce użytkownika, ale KIERUNEK opisujemy
        # słowem („zużycie wyższe”), a nie porównaniem liczb: przy km/l i mpg
        # rosnące zużycie oznacza MALEJĄCĄ liczbę i „o 14% więcej” byłoby
        # wprost sprzeczne z tym, co widać na kafelku.
        teraz = formatuj_zuzycie_tekst(trend["srednia_ostatnia"], czy_prad)
        wczesniej = formatuj_zuzycie_tekst(trend["srednia_wczesniej"], czy_prad)
        procent = formatuj_liczba_eksport(abs(trend["zmiana_proc"]), 0)
        rocznie = koszt_trendu_rocznie(auto_id, trend)
        ogon = (f" To około {_kwota_txt(abs(rocznie))} rocznie."
                if rocznie and abs(rocznie) >= 50 else "")
        if trend["kierunek"] == "wzrost":
            obserwacje.append(_obserwacja(
                "trend_spalania", "uwaga", "spalanie", "Zużycie w górę",
                f"Ostatnie {trend['odcinkow_ostatnio']} odcinki: {teraz} wobec {wczesniej} "
                f"wcześniej — zużycie wyższe o {procent}%.{ogon}",
                80, "/",
            ))
        else:
            obserwacje.append(_obserwacja(
                "trend_spalania", "dobry", "spalanie", "Zużycie w dół",
                f"Ostatnie {trend['odcinkow_ostatnio']} odcinki: {teraz} wobec {wczesniej} "
                f"wcześniej — zużycie niższe o {procent}%.{ogon}",
                60, "/",
            ))

    # 4. Prognoza roczna i zestawienie z poprzednim rokiem.
    prognoza = prognoza_kosztow(auto_id, dzis)
    if prognoza and prognoza["dni_pozostalo"] > 14:
        obserwacje.append(_obserwacja(
            "prognoza_rok", "neutralny", "prognoza", "Prognoza do końca roku",
            f"Przy obecnym tempie do końca roku dojdzie jeszcze około "
            f"{_kwota_txt(prognoza['prognoza_do_konca'])} — cały {prognoza['rok']} zamknie się "
            f"kwotą około {_kwota_txt(prognoza['prognoza_calego_roku'])}.",
            55, "/rok",
        ))
    if prognoza and prognoza.get("zmiana_rdr") is not None and abs(prognoza["zmiana_rdr"]) >= 10:
        w_gore = prognoza["zmiana_rdr"] > 0
        obserwacje.append(_obserwacja(
            "prognoza_rdr", "uwaga" if w_gore else "dobry", "prognoza",
            "Rok do roku",
            f"Ten rok zapowiada się {'drożej' if w_gore else 'taniej'} od poprzedniego o "
            f"{formatuj_liczba_eksport(abs(prognoza['zmiana_rdr']), 0)}% "
            f"({_kwota_txt(prognoza['poprzedni_rok'])} → {_kwota_txt(prognoza['prognoza_calego_roku'])}).",
            50, "/rok",
        ))

    # 5. Bieżący miesiąc na tle średniej — porównujemy TEMPO, nie kwoty, bo
    #    5. dnia miesiąca każda kwota będzie niższa od średniej.
    if prognoza and prognoza["srednia_miesieczna"] > 0:
        poczatek_mc = date_cls(dzis.year, dzis.month, 1)
        wydano_mc = koszty_w_okresie(auto_id, poczatek_mc, dzis)["razem"]
        dni_minione = (dzis - poczatek_mc).days + 1
        tempo_mc = wydano_mc / dni_minione * DNI_W_MIESIACU
        odchylenie = (tempo_mc - prognoza["srednia_miesieczna"]) / prognoza["srednia_miesieczna"] * 100
        if dni_minione >= 7 and abs(odchylenie) >= 25:
            drozej = odchylenie > 0
            obserwacje.append(_obserwacja(
                "tempo_miesiaca", "uwaga" if drozej else "dobry", "miesiac",
                "Ten miesiąc odstaje",
                f"Do dziś {_kwota_txt(wydano_mc)}; w tym tempie miesiąc skończy się kwotą około "
                f"{_kwota_txt(tempo_mc)}, czyli o {formatuj_liczba_eksport(abs(odchylenie), 0)}% "
                f"{'więcej' if drozej else 'mniej'} niż zwykle.",
                45,
            ))

    # 6. Ceny paliwa: gdzie tankujesz drożej, niż musisz.
    ceny = pobierz_trend_cen_paliwa(auto_id)
    stacje = [st for st in ceny.get("stacje", []) if st["liczba_tankowan"] >= 2]
    if len(stacje) >= 2:
        najtansza, najdrozsza = stacje[0], stacje[-1]
        roznica = najdrozsza["srednia_cena"] - najtansza["srednia_cena"]
        if najtansza["srednia_cena"] > 0 and roznica / najtansza["srednia_cena"] >= 0.04:
            litry_rocznie = 0.0
            seria = pobierz_serie_spalania(auto_id, limit=5, rodzaj=ENERGIA_PALIWO)
            sredni_dzienny = oblicz_sredni_dzienny_przebieg(auto_id)
            if seria and sredni_dzienny:
                spalanie = sum(w for _, w in seria) / len(seria)
                litry_rocznie = spalanie / 100 * sredni_dzienny * 365
            oszczednosc = roznica * litry_rocznie
            ogon = (f" Tankując zawsze tam, zaoszczędziłbyś około {_kwota_txt(oszczednosc)} rocznie."
                    if oszczednosc >= 50 else "")
            obserwacje.append(_obserwacja(
                "stacje_ceny", "neutralny", "stacja", "Różnice między stacjami",
                f"„{najtansza['nazwa']}” wychodzi średnio o "
                f"{formatuj_liczba_eksport(roznica, 2)} {pobierz_walute()} na jednostce taniej niż "
                f"„{najdrozsza['nazwa']}”.{ogon}",
                40,
            ))

    # 7. Cisza w danych — statystyki są tyle warte, ile kompletność wpisów.
    ostatnie_daty = []
    with polacz_baze() as conn:
        for data_str, _kwota, _kat in _wiersze_kosztow(conn, auto_id):
            d = parsuj_date(data_str)
            if d != datetime.min.date():
                ostatnie_daty.append(d)
    if ostatnie_daty:
        dni_ciszy = (dzis - max(ostatnie_daty)).days
        if dni_ciszy >= 45:
            obserwacje.append(_obserwacja(
                "cisza", "neutralny", "cisza", "Dawno nic nie dopisałeś",
                f"Ostatni wpis kosztowy ma {dni_ciszy} dni. Im więcej luk, tym mniej warte "
                f"są wszystkie liczby powyżej.",
                35,
            ))

    obserwacje.sort(key=lambda o: -o["waga"])
    return obserwacje[:limit] if limit else obserwacje


__all__ = [
    "OKRESY_BUDZETU",
    "PROG_ISTOTNOSCI_TRENDU",
    "PROG_UWAGI_BUDZETU",
    "_DYSTANSE_ODNIESIENIA",
    "_granice_okresu",
    "_kwota_txt",
    "_obserwacja",
    "_porownanie_dystansu",
    "analizuj_trend_spalania",
    "koszt_trendu_rocznie",
    "lata_z_danymi",
    "obserwacje_analityczne",
    "pobierz_budzety",
    "pobierz_zasieg_na_baku",
    "podsumowanie_roku",
    "prognoza_kosztow",
    "stan_budzetow",
    "zapisz_budzet",
]
