"""Budżety, prognozy, trendy, podsumowanie roku i obserwacje."""

import sqlite3
from date import parsuj_date
from datetime import date as date_cls, datetime, timedelta
from typing import Any

from .stale import ENERGIA_PALIWO, ENERGIA_PRAD, STATUS_POJAZDU_AKTYWNY, STATUS_POJAZDU_SPRZEDANY
from .polaczenie import polacz_baze
from .pomocnicze import _liczba_lub_none, formatuj_liczba_eksport, liczba_z_odmiana, parsuj_int_bezpiecznie
from .ustawienia import pobierz_okno_kroczace, pobierz_walute
from .synchronizacja import zarejestruj_nagrobek
from .energia import domyslny_rodzaj_energii, formatuj_zuzycie_tekst, rodzaje_energii_pojazdu
from .przebieg import oblicz_sredni_dzienny_przebieg, pobierz_aktualny_przebieg, pobierz_historie_przebiegu
from .koszty import DNI_W_MIESIACU, KATEGORIE_BUDZETU, _wiersze_kosztow, etykieta_kategorii_innych, klucz_stacji, koszty_w_okresie, pobierz_rozbicie_napraw, pobierz_trend_cen_paliwa, porownaj_czesci_wlasne
from .statystyki import koszt_na_1000km, pobierz_serie_spalania
from .pojazd import pobierz_dane_pojazdu


# ==================== ANALIZA, PROGNOZY I BUDŻETY ====================
# Ta sekcja odpowiada na pytania, na które sama tabela liczb nie odpowiada:
# czy jest lepiej czy gorzej, ile to będzie kosztować do końca roku i czy zdążę
# przed własnym limitem. Wszystko liczone z danych, które użytkownik już wpisał —
# żadnych nowych obowiązków przy dodawaniu wpisu.
# db.py nie zna Fleta (korzysta z niego też eksport PDF i synchronizacja), więc
# obserwacje wracają stąd z KLUCZEM ikony i tonem, a nie z gotową kontrolką.

OKRESY_BUDZETU = {"miesiac": "Miesięcznie", "30dni": "Ostatnie 30 dni", "rok": "Rocznie"}


# Okres RUCHOMY: okno kończy się dzisiaj i przesuwa się z każdym dniem — najstarszy
# dzień z niego wypada. Miesiąc kalendarzowy pasuje do pensji, ale nie do kosztów
# auta: dwa tankowania i przegląd potrafią wypaść w jednym tygodniu na przełomie
# miesiąca i w żadnym z nich nie wyglądać groźnie. Takie okno jest CAŁE za nami,
# więc nie ma w nim czego prognozować ani ile „okresu minęło” — pasek pokazuje samą
# sumę, bez znacznika upływu i bez daty przekroczenia.
OKRESY_RUCHOME = {"30dni"}
DNI_OKNA_BUDZETU = 30


# Od ilu procent limitu budżet przestaje być „w normie”. 80% wybrane świadomie:
# przy 90% na reakcję jest już zwykle za późno.
PROG_UWAGI_BUDZETU = 0.80


# Zmiana spalania poniżej tego progu to szum (inna stacja, inaczej dolany „pełny”
# bak, jedna trasa autostradą), a nie trend — nie ma o czym informować.
PROG_ISTOTNOSCI_TRENDU = 5.0


# Od ilu procent NAD średnią życiową koszt na 1000 km przestaje być szumem.
# Pięć procent mieści się w jednym droższym przeglądzie; piętnaście to już
# zmiana, o której warto powiedzieć zdaniem, a nie tylko krzywą.
PROG_DROZENIA_1000KM = 15.0


# Sezon. Listopad zawsze wypadnie gorzej od września — zimna, krótkie trasy,
# opony, dłuższe rozgrzewanie. Alarm, który zapala się co roku o tej samej porze,
# przestaje być alarmem, więc zanim ogłosimy trend, odejmujemy tyle, ile ta sama
# zmiana kalendarza dawała w poprzednich latach.
#   TOLERANCJA — tankowania nie wypadają rok w rok tego samego dnia, więc okna
#   sprzed roku poszerzamy w obie strony;
#   MIN_ODCINKOW — jeden odcinek sprzed roku to anegdota, nie sezon;
#   PROG_POKAZANIA — poniżej tego sezon jest tak mały, że zdanie o nim tylko
#   zaśmieciłoby komunikat;
#   MAX_LAT — dalej w przeszłość nie ma po co schodzić, a pętla musi się kończyć.
TOLERANCJA_SEZONU_DNI = 21
MIN_ODCINKOW_SEZONU = 2
PROG_POKAZANIA_SEZONU = 2.0
MAX_LAT_SEZONU = 10


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

def pobierz_budzety(auto_id) -> list[dict[str, Any]]:
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
    """(początek, koniec, dni_okresu, dni_minione) bieżącego okresu budżetu.
    'dni_minione' liczy dzisiejszy dzień jako miniony — inaczej pierwszego dnia
    okresu tempo wydatków dzieliłoby przez zero. Okno ruchome kończy się dzisiaj,
    więc minione = całość — i właśnie dlatego nic w nim nie prognozujemy."""
    dzis = dzis or datetime.now().date()
    if okres in OKRESY_RUCHOME:
        poczatek = dzis - timedelta(days=DNI_OKNA_BUDZETU - 1)
        koniec = dzis
    elif okres == "rok":
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


def stan_budzetow(auto_id, dzis=None) -> list[dict[str, Any]]:
    """Stan wykorzystania każdego ustawionego limitu. Dla każdego zwraca m.in.:
    wydano, limit, procent, pozostalo, tempo (prognoza całego okresu przy
    dotychczasowym tempie), 'ruchomy' (okno kończące się dzisiaj — bez prognozy),
    status ('ok' / 'uwaga' / 'przekroczony') oraz
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
        ruchomy = b["okres"] in OKRESY_RUCHOME
        poczatek, koniec, dni_okresu, dni_minione = _granice_okresu(b["okres"], dzis)
        if b["okres"] not in cache_kosztow:
            cache_kosztow[b["okres"]] = koszty_w_okresie(auto_id, poczatek, dzis)
        wydano = cache_kosztow[b["okres"]][b["kategoria"]]
        limit = b["kwota"]

        procent = (wydano / limit * 100) if limit > 0 else 0.0
        na_dzien = wydano / dni_minione
        # W oknie ruchomym „ile wyjdzie do końca okresu” to dokładnie tyle, ile już
        # wydano — koniec okna to dzisiaj, więc ekstrapolacja nie ma czego liczyć.
        tempo = wydano if ruchomy else na_dzien * dni_okresu

        if wydano > limit:
            status = "przekroczony"
        elif procent >= PROG_UWAGI_BUDZETU * 100 or tempo > limit:
            status = "uwaga"
        else:
            status = "ok"

        dzien_przekroczenia = None
        if not ruchomy and status != "przekroczony" and na_dzien > 0 and limit > 0:
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
            "ruchomy": ruchomy,
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

def _przesun_o_lata(d, lat):
    """Ta sama data `lat` lat wcześniej. 29 lutego cofamy na 28 — jeden dzień
    w roku nie ma prawa wywrócić całej analizy."""
    try:
        return d.replace(year=d.year - lat)
    except ValueError:
        return d.replace(year=d.year - lat, day=28)


def _srednia_okna(seria_dat, od, do):
    """Średnie zużycie z odcinków, których data mieści się w oknie.
    Zwraca (średnia, ile_odcinków) albo (None, 0), gdy odcinków za mało."""
    wartosci = [w for d, w in seria_dat if od <= d <= do]
    if len(wartosci) < MIN_ODCINKOW_SEZONU:
        return None, 0
    return sum(wartosci) / len(wartosci), len(wartosci)


def _sezonowosc_zmiany(seria_dat, tlo_od, tlo_do, ost_od, ost_do):
    """Ile punktów procentowych dawało samo przejście przez ten sam kawałek
    kalendarza w poprzednich latach.

    Bierzemy oba okna — „tło” i „ostatnie odcinki” — cofamy je o rok, dwa, trzy
    i liczymy na tamtych danych dokładnie tę samą zmianę. Średnia z tych zmian
    to sezon: tyle zużycie rośnie na przełomie września i listopada co roku,
    niezależnie od stanu auta. Okna poszerzamy o TOLERANCJA_SEZONU_DNI, ale nie
    pozwalamy im na siebie zachodzić — ten sam odcinek po obu stronach
    porównania ściągnąłby wynik do zera.

    Zwraca (sezon_w_procentach, liczba_lat) albo (None, 0), gdy nie ma z czym
    porównywać. Brak historii sprzed roku nie jest błędem: aplikacja działa
    wtedy tak, jak działała zawsze."""
    if not seria_dat:
        return None, 0

    najstarsza = seria_dat[0][0]
    tol = timedelta(days=TOLERANCJA_SEZONU_DNI)
    zmiany = []
    for lat in range(1, MAX_LAT_SEZONU + 1):
        t_od, t_do = _przesun_o_lata(tlo_od, lat), _przesun_o_lata(tlo_do, lat)
        o_od, o_do = _przesun_o_lata(ost_od, lat), _przesun_o_lata(ost_do, lat)
        if o_do < najstarsza:
            break
        a_od, a_do = t_od - tol, t_do + tol
        b_od, b_do = o_od - tol, o_do + tol
        if b_od <= a_do:
            srodek = t_do + (o_od - t_do) / 2
            a_do, b_od = min(a_do, srodek), max(b_od, srodek + timedelta(days=1))
        sr_tlo, _ile_tlo = _srednia_okna(seria_dat, a_od, a_do)
        sr_ost, _ile_ost = _srednia_okna(seria_dat, b_od, b_do)
        if sr_tlo and sr_ost and sr_tlo > 0:
            zmiany.append((sr_ost - sr_tlo) / sr_tlo * 100)

    if not zmiany:
        return None, 0
    return sum(zmiany) / len(zmiany), len(zmiany)


def analizuj_trend_spalania(auto_id, rodzaj=None, ostatnie=3, tlo=6):
    """Porównuje zużycie z OSTATNICH odcinków ze średnią z odcinków
    wcześniejszych i mówi, czy auto zaczęło palić więcej.

    Odcinek = trasa między dwoma tankowaniami „do pełna” (patrz
    pobierz_serie_spalania), bo tylko tam ilość paliwa odpowiada przejechanym
    kilometrom. Świadomie NIE porównujemy „miesiąc do miesiąca”: przy dwóch
    tankowaniach na miesiąc taki podział daje skoki rzędu 20%, które są
    wyłącznie efektem tego, gdzie wypadła granica kalendarza.

    Granica kalendarza to nie jedyna pułapka: samo porównanie września
    z listopadem zawsze wyjdzie na wzrost, bo zima. Dlatego obok surowej zmiany
    liczymy SEZON (`_sezonowosc_zmiany`) i to dopiero różnica po jego odjęciu
    (`zmiana_po_sezonie`) decyduje o `kierunek` — alarm ma się zapalać, gdy auto
    pali więcej, a nie gdy kalendarz pokazuje listopad. Bez danych sprzed roku
    `sezon_proc` jest None, a wszystko działa jak wcześniej.

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

    seria_dat = [(parsuj_date(d), w) for d, w in seria]
    poczatek_tla = max(0, len(seria) - ostatnie - tlo)
    sezon_proc, lat_sezonu = _sezonowosc_zmiany(
        seria_dat,
        seria_dat[poczatek_tla][0], seria_dat[len(seria) - ostatnie - 1][0],
        seria_dat[len(seria) - ostatnie][0], seria_dat[-1][0],
    )
    zmiana_po_sezonie = zmiana - sezon_proc if sezon_proc is not None else zmiana

    # Kierunek — i cały alarm — z różnicy PO odjęciu sezonu.
    if abs(zmiana_po_sezonie) < PROG_ISTOTNOSCI_TRENDU:
        kierunek = "stabilnie"
    elif zmiana_po_sezonie > 0:
        kierunek = "wzrost"
    else:
        kierunek = "spadek"

    # Osobne pytanie niż sezon: czy auto pali więcej niż rok temu o tej samej
    # porze. Tu porównujemy ostatnie odcinki z tym samym oknem kalendarza
    # sprzed roku, więc pora roku wypada z równania sama z siebie.
    tol = timedelta(days=TOLERANCJA_SEZONU_DNI)
    sr_rok_temu, odcinkow_rok_temu = _srednia_okna(
        seria_dat,
        _przesun_o_lata(seria_dat[len(seria) - ostatnie][0], 1) - tol,
        _przesun_o_lata(seria_dat[-1][0], 1) + tol,
    )
    rdr_proc = ((sr_ostatnie - sr_rok_temu) / sr_rok_temu * 100
                if sr_rok_temu and sr_rok_temu > 0 else None)

    najstarsza = parsuj_date(seria[max(0, len(seria) - ostatnie - tlo)][0])
    najnowsza = parsuj_date(seria[-1][0])
    dni_okna = (najnowsza - najstarsza).days if najnowsza > najstarsza else 0

    return {
        "rodzaj": rodzaj,
        "srednia_ostatnia": sr_ostatnie,
        "srednia_wczesniej": sr_wczesniej,
        "zmiana_proc": zmiana,
        # Ile z tej zmiany to sama pora roku i co zostaje po jej odjęciu.
        "sezon_proc": sezon_proc,
        "zmiana_po_sezonie": zmiana_po_sezonie,
        "lat_sezonu": lat_sezonu,
        "srednia_rok_temu": sr_rok_temu,
        "odcinkow_rok_temu": odcinkow_rok_temu,
        "rdr_proc": rdr_proc,
        "kierunek": kierunek,
        "odcinkow_ostatnio": len(ostatnie_w),
        "odcinkow_wczesniej": len(wczesniejsze),
        "dni_okna": dni_okna,
        "data_ostatniego": seria[-1][0],
        # Różnica w koszcie na 100 km — sam procent nie mówi, czy to problem
        # wart reakcji, czy pół złotówki.
        "roznica_na_100km": sr_ostatnie - sr_wczesniej,
        # To samo, ale bez części, którą tłumaczy kalendarz — z tego liczymy
        # złotówki na rok, żeby nie obiecywać oszczędności, która i tak sama
        # wróci na wiosnę.
        "roznica_po_sezonie_na_100km": sr_wczesniej * zmiana_po_sezonie / 100,
    }


def opis_sezonowosci_trendu(trend):
    """Jedno zdanie o tym, ile ze zmiany zużycia to zwykła pora roku.

    Zwraca None, gdy nie ma danych sprzed roku albo sezon jest na tyle mały, że
    zdanie o nim tylko zaśmieciłoby komunikat."""
    if not trend or trend.get("sezon_proc") is None:
        return None

    sezon = trend["sezon_proc"]
    if abs(sezon) < PROG_POKAZANIA_SEZONU:
        return None

    reszta = trend["zmiana_po_sezonie"]
    if abs(reszta) < PROG_ISTOTNOSCI_TRENDU:
        koniec = "po odjęciu sezonu nie zostaje nic, co odstawałoby od normy"
    else:
        koniec = (f"po odjęciu sezonu zostaje {formatuj_liczba_eksport(abs(reszta), 0)}% "
                  f"{'w górę' if reszta > 0 else 'w dół'}")
    return (f"Typowo o tej porze roku zużycie {'rośnie' if sezon > 0 else 'spada'} "
            f"o {formatuj_liczba_eksport(abs(sezon), 0)} pkt proc. — {koniec}.")


def koszt_trendu_rocznie(auto_id, trend):
    """Ile kosztuje (albo oszczędza) zmiana zużycia z analizuj_trend_spalania,
    przeliczona na rok przy dotychczasowym przebiegu rocznym i ostatniej znanej
    cenie jednostkowej. Procent robi wrażenie, ale dopiero złotówki na rok
    odpowiadają na pytanie, czy warto jechać do mechanika.

    Liczymy z różnicy PO odjęciu sezonu: zimowy skok wróci sam na wiosnę, więc
    mnożenie go przez cały rok obiecywałoby koszt, którego nie będzie."""
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
    roznica = trend.get("roznica_po_sezonie_na_100km", trend["roznica_na_100km"])
    roznica_jednostek = roznica / 100 * km_rocznie
    return roznica_jednostek * cena_jedn


# -------------------- ZASIĘG NA BAKU --------------------

def pobierz_zasieg_na_baku(auto_id):
    """Zasięg auta spalinowego: ile przejedzie na PEŁNYM baku i ile zostało
    od ostatniego tankowania do pełna.

    Ta druga liczba jest szacunkiem z licznika, nie odczytem z pływaka: bierzemy
    kilometry przejechane od ostatniego pełnego baku i mnożymy przez rzeczywiste
    zużycie, a dolewki zapisane po nim (tankowania bez „do pełna”) dodajemy do
    stanu. Dlatego zwracamy też 'pewnosc' i 'dni_od_tankowania' — im starsze
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
            "SELECT data, przebieg, litry, do_pelna FROM tankowania "
            "WHERE auto_id=? AND COALESCE(rodzaj_energii, ?) = ?",
            (auto_id, domyslny_rodzaj_energii(auto_id), rodzaj)
        )
        # Po dacie, przy remisie po przebiegu — ta sama kolejność co wszędzie
        # indziej, żeby dwa tankowania jednego dnia nie dały ujemnego dystansu.
        wpisy = sorted(c.fetchall(), key=lambda r: (parsuj_date(r[0]), int(r[1] or 0)))
    pelne = [i for i, r in enumerate(wpisy) if r[3] and int(r[1] or 0) > 0]

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
        "dni_do_pustego": None,
        "data_pustego": None,
        "pewnosc": "brak",
    }

    if not pelne:
        return wynik

    ostatnie = wpisy[pelne[-1]]
    data_tank = parsuj_date(ostatnie[0])
    przebieg_tank = int(ostatnie[1] or 0)
    aktualny = pobierz_aktualny_przebieg(auto_id) or 0

    przejechane = aktualny - przebieg_tank
    if przejechane < 0:
        return wynik

    # Dolewki po ostatnim pełnym baku też są w baku — bez nich po dolaniu
    # wskaźnik pokazywał tyle, jakby nikt nic nie dolał, i zaraz po tankowaniu
    # straszył „Czas zatankować”. Krok po kroku: zużycie do dolewki, potem
    # dolewka — nigdy poniżej pustego baku ani ponad jego pojemność.
    pozostalo, licznik = pojemnosc, przebieg_tank
    for _, przebieg_d, litry_d, _ in wpisy[pelne[-1] + 1:]:
        przebieg_d = max(licznik, int(przebieg_d or 0))
        pozostalo = max(0.0, pozostalo - (przebieg_d - licznik) * spalanie / 100)
        pozostalo = min(pojemnosc, pozostalo + float(litry_d or 0))
        licznik = przebieg_d
    pozostalo -= (max(aktualny, licznik) - licznik) * spalanie / 100
    dni = (datetime.now().date() - data_tank).days if data_tank != datetime.min.date() else None
    zasieg_pozostaly = max(0.0, pozostalo / spalanie * 100)

    # Prognoza „zabraknie za X dni” — to samo tempo km/dzień, którego już
    # używają terminy podzespołów (patrz db.powiadomienia). Brak historii
    # licznika (sredni_dzienny=None) albo zerowe tempo = brak prognozy,
    # zamiast dzielenia przez zero.
    sredni_dzienny = oblicz_sredni_dzienny_przebieg(auto_id)
    dni_do_pustego, data_pustego = None, None
    if sredni_dzienny and sredni_dzienny > 0:
        dni_do_pustego = max(0, int(round(zasieg_pozostaly / sredni_dzienny)))
        data_pustego = (datetime.now().date() + timedelta(days=dni_do_pustego)).strftime("%d.%m.%Y")

    wynik.update({
        "przejechane": przejechane,
        "pozostalo_jednostek": max(0.0, pozostalo),
        "zasieg_pozostaly": zasieg_pozostaly,
        "procent_baku": max(0.0, min(100.0, pozostalo / pojemnosc * 100)),
        "data_tankowania": ostatnie[0],
        "dni_od_tankowania": dni,
        "dni_do_pustego": dni_do_pustego,
        "data_pustego": data_pustego,
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

# Od jakiej części dystansu odniesienia wolno powiedzieć „prawie”.
PROG_PRAWIE = 0.9


def _porownanie_dystansu(km):
    """Zamienia przebieg w obraz („to prawie okrążenie Ziemi”). Bierzemy
    największy dystans odniesienia, który mieści się w przejechanym — tak, żeby
    porównanie zawsze brzmiało jak osiągnięcie, a nie jak wymówka.

    „Prawie” tylko wtedy, gdy do następnego dystansu brakuje niewiele (90%).
    Wcześniej „prawie przejazd do Berlina” dostawał ktoś, kto przejechał
    650 km — czyli WIĘCEJ niż do Berlina."""
    if not km or km <= 0:
        return None
    for i, (dystans, opis) in enumerate(_DYSTANSE_ODNIESIENIA):
        if km >= dystans:
            wiekszy = _DYSTANSE_ODNIESIENIA[i - 1] if i > 0 else None
            if wiekszy and km >= wiekszy[0] * PROG_PRAWIE:
                return f"prawie {wiekszy[1]}"
            razy = km / dystans
            if razy >= 1.9:
                return f"{opis} — {formatuj_liczba_eksport(razy, 1)} raza"
            return f"więcej niż {opis}"
    najmniejszy, opis = _DYSTANSE_ODNIESIENIA[-1]
    return f"prawie {opis}" if km >= najmniejszy * PROG_PRAWIE else None


def _zmiana_1000km(koszt, km, koszt_poprzedni, km_poprzedni):
    """Procentowa zmiana kosztu na 1000 km rok do roku; None, gdy któregoś roku
    nie da się policzyć (brak kilometrów albo brak wydatków)."""
    if not (km and km_poprzedni and koszt_poprzedni > 0):
        return None
    teraz = koszt / km
    wczesniej = koszt_poprzedni / km_poprzedni
    return ((teraz - wczesniej) / wczesniej * 100) if wczesniej > 0 else None


def _km_w_roku(historia_prz, rok, granica=None):
    """Kilometry przejechane w danym roku, z historii odczytów licznika.

    Punkt startowy to ostatni odczyt SPRZED roku, jeśli istnieje — inaczej
    styczniowy stan licznika policzyłby się jako „przejechane od zera”."""
    poczatek = date_cls(rok, 1, 1)
    kres = granica or date_cls(rok, 12, 31)
    przed_rokiem, w_roku = None, []
    for data_str, prz in historia_prz:
        d = parsuj_date(data_str)
        if d == datetime.min.date():
            continue
        if d < poczatek:
            przed_rokiem = prz
        elif d <= kres:
            w_roku.append(prz)
    start = przed_rokiem if przed_rokiem is not None else (min(w_roku) if w_roku else None)
    koniec = max(w_roku) if w_roku else None
    return (koniec - start) if (start is not None and koniec is not None and koniec > start) else 0


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
    koniec = date_cls(rok, 12, 31)
    dzis = datetime.now().date()
    granica = min(koniec, dzis) if rok == dzis.year else koniec
    # Rok w toku porównujemy z TYM SAMYM kawałkiem roku poprzedniego (styczeń
    # – dzisiejszy dzień), a nie z całym rokiem: inaczej we wrześniu każdy rok
    # wychodził „taniej o 30%”, bo brakowało mu jeszcze jesieni.
    granica_poprzedniego = _przesun_o_lata(granica, 1)

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
    km = _km_w_roku(historia_prz, rok, granica)
    # Rok poprzedni liczymy tą samą miarą — bez niego „koszt na 1000 km” nie ma
    # z czym się porównać, a sama kwota nie mówi, czy auto drożeje.
    km_poprzedni = _km_w_roku(historia_prz, rok - 1, granica_poprzedniego)

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
    rodzaj_zuzycia = domyslny_rodzaj_energii(auto_id)
    seria = pobierz_serie_spalania(auto_id, limit=None, rodzaj=rodzaj_zuzycia)
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

    # --- porównanie z poprzednim rokiem (ten sam okres, patrz wyżej) ---
    poprzedni = 0.0
    for data_str, kwota, _kat in wiersze_kosztow:
        d = parsuj_date(data_str)
        if d != datetime.min.date() and d.year == rok - 1 and d <= granica_poprzedniego:
            poprzedni += float(kwota or 0.0)

    return {
        "rok": rok,
        "niepelny": rok == dzis.year,
        "km": km,
        "koszty": kategorie,
        "koszt_km": (kategorie["razem"] / km) if km > 0 else None,
        "koszt_1000km": (kategorie["razem"] / km * 1000) if km > 0 else None,
        "km_poprzedni": km_poprzedni or None,
        "koszt_1000km_poprzedni": ((poprzedni / km_poprzedni * 1000)
                                   if (poprzedni > 0 and km_poprzedni > 0) else None),
        "miesiace": miesiace,
        "najdrozszy_miesiac": {"miesiac": najdrozszy[0], "kwota": najdrozszy[1]},
        "najtanszy_miesiac": {"miesiac": najtanszy[0], "kwota": najtanszy[1]},
        "liczba_tankowan": len(tank_roku),
        "litry": litry,
        "kwh": kwh,
        "ulubiona_stacja": ulubiona,
        "srednie_zuzycie": srednie_zuzycie,
        # W jakiej jednostce jest `srednie_zuzycie` — grafika roku pisała
        # zużycie elektryka w l/100km, bo o źródle nic nie wiedziała.
        "zuzycie_elektryczne": rodzaj_zuzycia == ENERGIA_PRAD,
        "liczba_wizyt": len([w for w in wizyty_wpisy
                             if parsuj_date(w.get("data")) != datetime.min.date()
                             and parsuj_date(w.get("data")).year == rok]),
        "liczba_wpisow_serwisu": len([w for w in serwis_wpisy
                                      if parsuj_date(w.get("data")) != datetime.min.date()
                                      and parsuj_date(w.get("data")).year == rok]),
        "najwiekszy_wydatek": ({"data": najwiekszy[0], "kwota": najwiekszy[1], "opis": najwiekszy[2]}
                               if najwiekszy else None),
        "poprzedni_rok": poprzedni if poprzedni > 0 else None,
        # Do którego dnia liczy się `poprzedni_rok` — przy roku w toku to ten
        # sam dzień rok wcześniej, przy zamkniętym 31 grudnia.
        "poprzedni_do": granica_poprzedniego.strftime("%d.%m.%Y"),
        "zmiana_rdr": ((kategorie["razem"] - poprzedni) / poprzedni * 100) if poprzedni > 0 else None,
        # Zmiana kwoty rok do roku rośnie także wtedy, gdy po prostu jeździsz
        # więcej. Ta druga liczba dzieli przez dystans, więc mówi o CENIE jazdy.
        "zmiana_1000km": _zmiana_1000km(kategorie["razem"], km, poprzedni, km_poprzedni),
        "porownanie_dystansu": _porownanie_dystansu(km),
        "sredni_koszt_miesiaca": (kategorie["razem"] / len(miesiace_z_danymi)) if miesiace_z_danymi else 0.0,
    }


def lata_z_danymi(auto_id) -> list[int]:
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


# -------------------- KOSZT SKUMULOWANY --------------------
# Słupki miesięczne uśredniają wrażenie: przegląd za cztery tysiące ląduje
# w jednym słupku obok tankowań i po kwartale nie widać go wcale. Suma
# narastająca niczego nie uśrednia — każdy wydatek zostaje na krzywej na
# zawsze — więc jako jedyna pokazuje PRAWDZIWĄ skalę tego, co auto kosztuje.
#
# Oś ma od czego zacząć, bo karta pojazdu zna datę i cenę zakupu. Bez daty
# zakupu krzywa startuje w pierwszym wpisie — i wołający dowiaduje się o tym
# z `czy_od_zakupu`, żeby nie podpisać wykresu „od zakupu” wbrew prawdzie.

# Ile razy wpis musi przebić medianę wpisu, żeby dostać własny znacznik.
# Przy dwukrotności znacznik dostawało co drugie tankowanie do pełna; przy
# trzykrotności zostają awarie, przeglądy, opony i ubezpieczenie — czyli to,
# po co się w ogóle na tę krzywą patrzy.
PROG_WYROZNIENIA_WYDATKU = 3.0
MAKS_WYROZNIONYCH_WYDATKOW = 6

# Ile punktów dostaje iskra na kafelku kokpitu. Więcej i tak nie zmieści się
# w trzydziestu pikselach wysokości, a krzywa narastająca jest gładka, więc
# przy rzadszym próbkowaniu nic z jej kształtu nie ginie.
PUNKTOW_ISKRY_SKUMULOWANEJ = 24


def _wiersze_kosztow_z_opisem(conn, auto_id):
    """To samo, co `_wiersze_kosztow`, tylko z nazwą wpisu: krzywa skumulowana
    musi umieć powiedzieć, CO było tym skokiem w górę — sama kwota bez nazwy
    zostawia użytkownika z pytaniem, po które tu przyszedł.

    Reguła wizyty zbiorczej bez zmian: wizyta wchodzi w CAŁOŚCI, a należące do
    niej pozycje historii są pomijane, żeby ten sam koszt nie policzył się
    dwa razy."""
    c = conn.cursor()
    wiersze = []
    c.execute("SELECT data, kwota, stacja FROM tankowania WHERE auto_id=?", (auto_id,))
    wiersze += [(d, k, "paliwo", str(s or "").strip() or "Tankowanie")
                for d, k, s in c.fetchall()]
    c.execute(
        "SELECT h.data, h.cena, z.nazwa FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
        "WHERE z.auto_id=? AND h.wizyta_id IS NULL", (auto_id,)
    )
    wiersze += [(d, k, "serwis", str(n or "").strip() or "Wpis serwisowy")
                for d, k, n in c.fetchall()]
    c.execute("SELECT data, koszt_calkowity, wykonawca FROM wizyty WHERE auto_id=?", (auto_id,))
    wiersze += [(d, k, "serwis", f"Wizyta — {str(w).strip()}" if str(w or "").strip() else "Wizyta w serwisie")
                for d, k, w in c.fetchall()]
    c.execute("SELECT data, kwota, nazwa, kategoria FROM inne_koszty WHERE auto_id=?", (auto_id,))
    wiersze += [(d, k, "inne", str(n or "").strip() or etykieta_kategorii_innych(kat))
                for d, k, n, kat in c.fetchall()]
    return wiersze


def koszt_skumulowany(auto_id, z_cena_zakupu=True, dzis=None) -> dict[str, Any]:
    """Suma narastająca wydatków na pojazd — dzień po dniu, od zakupu.

    `z_cena_zakupu` decyduje, czy krzywa startuje od kwoty zakupu (pełny
    rachunek za posiadanie), czy od zera (sama eksploatacja). Bez daty albo bez
    ceny zakupu nie ma czego postawić na starcie, więc start jest zerowy
    niezależnie od flagi.

    Auto sprzedane ma rachunek ZAMKNIĘTY na dniu sprzedaży — dokładnie tak jak
    w `pobierz_metryki_pojazdu`, żeby koszt dzienny sprzedanego auta nie malał
    sam z siebie z każdym kolejnym dniem po sprzedaży. Cena sprzedaży wraca
    osobno, bo to jedyna pozycja w tym rachunku, która go OBNIŻA."""
    pusty = {
        "punkty": [], "wyroznione": [], "iskra": [],
        "start": None, "czy_od_zakupu": False,
        "cena_zakupu": None, "z_cena_zakupu": False, "wartosc_startowa": 0.0,
        "wydatki": 0.0, "suma": 0.0, "dni": 0, "km": None,
        "koszt_dzien": None, "koszt_km": None, "sprzedaz": None,
    }
    if not auto_id:
        return pusty

    dane = pobierz_dane_pojazdu(auto_id)
    if not dane:
        return pusty

    dzien_dzis = dzis or datetime.now().date()

    sprzedany = str(dane.get("status") or STATUS_POJAZDU_AKTYWNY) == STATUS_POJAZDU_SPRZEDANY
    data_sprzedazy = parsuj_date(dane.get("data_sprzedazy")) if sprzedany else None
    if data_sprzedazy == datetime.min.date() or (data_sprzedazy and data_sprzedazy > dzien_dzis):
        data_sprzedazy = None
    dzien_odniesienia = data_sprzedazy or dzien_dzis

    data_zakupu = parsuj_date(dane.get("data_zakupu"))
    if data_zakupu == datetime.min.date() or data_zakupu > dzien_odniesienia:
        data_zakupu = None

    with polacz_baze() as conn:
        surowe = _wiersze_kosztow_z_opisem(conn, auto_id)

    # Wpisy sprzed zakupu to koszty poprzedniego właściciela albo literówka
    # w dacie — do rachunku „ile mnie kosztowało to auto” nie należą. Tak samo
    # liczy okno wydatków w `pobierz_metryki_pojazdu`, więc obie liczby zgadzają
    # się ze sobą.
    wpisy = []
    for data_str, kwota, kategoria, opis in surowe:
        d = parsuj_date(data_str)
        if d == datetime.min.date() or d > dzien_odniesienia:
            continue
        if data_zakupu and d < data_zakupu:
            continue
        wartosc = float(kwota or 0.0)
        if wartosc <= 0:
            continue
        wpisy.append((d, wartosc, kategoria, opis))
    wpisy.sort(key=lambda w: w[0])

    cena_zakupu = _liczba_lub_none(dane.get("cena_zakupu"))
    wlicz_zakup = bool(z_cena_zakupu and data_zakupu and cena_zakupu)
    wartosc_startowa = float(cena_zakupu) if wlicz_zakup else 0.0
    start = data_zakupu or (wpisy[0][0] if wpisy else dzien_odniesienia)

    # Jeden punkt na DZIEŃ z wpisem. Dwa wydatki tego samego dnia dają jeden
    # skok — dwa punkty o tym samym X zrobiłyby z krzywej pionową kreskę
    # i nic poza tym.
    biezace = {k: 0.0 for k in KATEGORIE_BUDZETU if k != "razem"}
    punkty = [dict({"data": start, "dzien": 0, "razem": wartosc_startowa}, **biezace)]
    skumulowana_dnia = {}
    for d, wartosc, kategoria, _opis in wpisy:
        biezace[kategoria] = biezace.get(kategoria, 0.0) + wartosc
        razem = wartosc_startowa + sum(biezace.values())
        if punkty[-1]["data"] == d:
            punkty[-1].update(dict(biezace, razem=razem))
        else:
            punkty.append(dict(biezace, data=d, dzien=(d - start).days, razem=razem))
        skumulowana_dnia[d] = razem

    # Ogon do dnia odniesienia: pół roku bez wydatku to na tej krzywej POZIOMY
    # odcinek, a nie jej brak. Bez tego punktu wykres kończyłby się na ostatnim
    # tankowaniu i cisza po nim byłaby niewidoczna.
    if punkty[-1]["data"] < dzien_odniesienia:
        punkty.append(dict(punkty[-1], data=dzien_odniesienia,
                           dzien=(dzien_odniesienia - start).days))

    kwoty = sorted(w[1] for w in wpisy)
    mediana = kwoty[len(kwoty) // 2] if kwoty else 0.0
    prog = mediana * PROG_WYROZNIENIA_WYDATKU
    kandydaci = sorted((w for w in wpisy if prog > 0 and w[1] >= prog),
                       key=lambda w: w[1], reverse=True)
    wyroznione = [
        {"data": d, "dzien": (d - start).days, "kwota": wartosc,
         "kategoria": kategoria, "opis": opis,
         "skumulowana": skumulowana_dnia.get(d, wartosc_startowa)}
        for d, wartosc, kategoria, opis
        in sorted(kandydaci[:MAKS_WYROZNIONYCH_WYDATKOW], key=lambda w: w[0])
    ]

    wydatki = sum(biezace.values())
    suma = wartosc_startowa + wydatki
    dni = max(0, (dzien_odniesienia - start).days)

    przebieg = pobierz_aktualny_przebieg(auto_id) or 0
    przebieg_zakupu = parsuj_int_bezpiecznie(dane.get("przebieg_zakupu"), 0)
    km = (przebieg - przebieg_zakupu) if (przebieg_zakupu > 0 and przebieg > przebieg_zakupu) else None

    cena_sprzedazy = _liczba_lub_none(dane.get("cena_sprzedazy"))
    sprzedaz = None
    if data_sprzedazy:
        sprzedaz = {
            "data": data_sprzedazy,
            "dzien": (data_sprzedazy - start).days,
            "cena": cena_sprzedazy,
            # Odejmować jest od czego tylko wtedy, gdy w krzywej siedzi cena
            # zakupu. Przy krzywej samej eksploatacji „minus cena sprzedaży”
            # dałoby liczbę ujemną bez żadnego znaczenia.
            "po_odliczeniu": ((suma - cena_sprzedazy)
                              if (wlicz_zakup and cena_sprzedazy is not None) else None),
        }

    krok_iskry = max(1, -(-len(punkty) // PUNKTOW_ISKRY_SKUMULOWANEJ))
    iskra = [p["razem"] for p in punkty[::krok_iskry]]
    if iskra and iskra[-1] != punkty[-1]["razem"]:
        iskra.append(punkty[-1]["razem"])

    return {
        "punkty": punkty,
        "wyroznione": wyroznione,
        "iskra": iskra,
        "start": start,
        "czy_od_zakupu": data_zakupu is not None,
        "cena_zakupu": cena_zakupu,
        "z_cena_zakupu": wlicz_zakup,
        "wartosc_startowa": wartosc_startowa,
        "wydatki": wydatki,
        "suma": suma,
        "dni": dni,
        "km": km,
        "koszt_dzien": (suma / dni) if dni >= 1 else None,
        "koszt_km": (suma / km) if km else None,
        "sprzedaz": sprzedaz,
    }


# -------------------- ROK DO ROKU NA JEDNEJ OSI --------------------
# Porównanie rok do roku istniało dotąd jako ZDANIE („drożej o 23%”) i liczba
# w podsumowaniu roku. Obie odpowiadają na pytanie „o ile”, żadna na pytanie
# „od kiedy” — a to drugie jest zwykle ważniejsze, bo wskazuje zdarzenie:
# miesiąc, w którym zaczął się abonament, wymiana rozrządu albo dłuższe dojazdy.
# Dwie krzywe na jednej osi miesięcy idą razem do tego miesiąca i od niego się
# rozchodzą.

WIELKOSCI_RDR = {
    "razem": ("Koszty razem", "waluta", True),
    "paliwo": ("Paliwo", "waluta", True),
    "serwis": ("Serwis", "waluta", True),
    "inne": ("Inne", "waluta", True),
    "km": ("Kilometry", "km", False),
    "koszt1000": ("Koszt / 1000 km", "waluta", True),
}

# Jaki udział w końcowej różnicy musi mieć JEDEN miesiąc, żeby dało się
# powiedzieć „wtedy się rozjechało”. Poniżej tego progu różnica narastała
# stopniowo i wskazywanie palcem jednego miesiąca byłoby zmyślaniem.
PROG_ROZJAZDU = 0.25


def _km_miesiecznie_w_roku(historia_prz, rok):
    """Kilometry w kolejnych miesiącach roku — dwanaście liczb, także zer.

    Ta sama zasada, co w `pobierz_przebieg_miesieczny`: miesiąc bez odczytu ma
    zero, a dystans dopisuje się do miesiąca, w którym licznik został wreszcie
    odczytany. Inaczej luka w zapiskach robiłaby ujemny przebieg."""
    odczyty = []
    for data_str, prz in historia_prz:
        d = parsuj_date(data_str)
        if d != datetime.min.date():
            odczyty.append((d, prz))

    def stan_na_koniec(rok_k, mies_k):
        koniec = (date_cls(rok_k + 1, 1, 1) if mies_k == 12
                  else date_cls(rok_k, mies_k + 1, 1)) - timedelta(days=1)
        wczesniejsze = [p for d, p in odczyty if d <= koniec]
        return max(wczesniejsze) if wczesniejsze else None

    wynik = []
    for m in range(1, 13):
        poprz_m, poprz_r = (m - 1, rok) if m > 1 else (12, rok - 1)
        koniec = stan_na_koniec(rok, m)
        poczatek = stan_na_koniec(poprz_r, poprz_m)
        km = (koniec - poczatek) if (koniec is not None and poczatek is not None) else 0
        wynik.append(max(0, km))
    return wynik


def _serie_roku(wiersze_kosztow, historia_prz, rok, wielkosc):
    """Dwanaście wartości miesięcznych wybranej wielkości dla jednego roku."""
    koszty = {kat: [0.0] * 12 for kat in KATEGORIE_BUDZETU}
    for data_str, kwota, kategoria in wiersze_kosztow:
        d = parsuj_date(data_str)
        if d == datetime.min.date() or d.year != rok:
            continue
        wartosc = float(kwota or 0.0)
        koszty[kategoria][d.month - 1] += wartosc
        koszty["razem"][d.month - 1] += wartosc

    if wielkosc == "km":
        return [float(km) for km in _km_miesiecznie_w_roku(historia_prz, rok)]
    if wielkosc == "koszt1000":
        # Wielkość ILORAZOWA — miesięcznych ilorazów nie wolno sumować, więc
        # wracają tu składniki, a dzielenie robi się dopiero po zsumowaniu okna.
        km = _km_miesiecznie_w_roku(historia_prz, rok)
        return [(koszty["razem"][i], float(km[i])) for i in range(12)]
    return list(koszty.get(wielkosc, koszty["razem"]))


def _narastajaco(seria, wielkosc):
    """Suma narastająca od stycznia. Iloraz liczy się z sum składników, a nie
    jako suma ilorazów — inaczej tani miesiąc z jednym kilometrem ważyłby tyle,
    co cały grudzień."""
    wynik, suma = [], 0.0
    if wielkosc == "koszt1000":
        koszt, km = 0.0, 0.0
        for k, kilometry in seria:
            koszt += k
            km += kilometry
            wynik.append((koszt / km * 1000) if km > 0 else None)
        return wynik
    for wartosc in seria:
        suma += wartosc
        wynik.append(suma)
    return wynik


def _miesiecznie(seria, wielkosc):
    if wielkosc == "koszt1000":
        return [(k / km * 1000) if km > 0 else None for k, km in seria]
    return list(seria)


def koszty_rok_do_roku(auto_id, rok=None, wielkosc="razem", narastajaco=True, dzis=None) -> dict[str, Any]:
    """Dwie krzywe — wybrany rok i poprzedni — na jednej osi miesięcy.

    `narastajaco` decyduje o postaci: suma od stycznia (wtedy widać MIESIĄC,
    w którym lata się rozeszły) albo wartości miesięczne (wtedy widać, czy skok
    był jednorazowy). Miesiąc rozjazdu liczy się zawsze z krzywych narastających
    — w postaci miesięcznej byłby tylko najwyższym słupkiem.

    Rok w toku kończy się na bieżącym miesiącu, a procent liczy się wobec tych
    SAMYCH miesięcy roku poprzedniego: styczeń–maj kontra styczeń–maj."""
    dzien = dzis or datetime.now().date()
    etykieta, jednostka, wzrost_zly = WIELKOSCI_RDR.get(wielkosc) or WIELKOSCI_RDR["razem"]
    if wielkosc not in WIELKOSCI_RDR:
        wielkosc = "razem"
    lata = lata_z_danymi(auto_id)
    wybrany = int(rok) if rok else (lata[0] if lata else dzien.year)

    pusty = {
        "rok": wybrany, "rok_poprzedni": wybrany - 1, "lata": lata,
        "wielkosc": wielkosc, "etykieta": etykieta, "jednostka": jednostka,
        "wzrost_zly": wzrost_zly, "narastajaco": bool(narastajaco),
        "biezacy": [], "poprzedni": [], "roznice": [],
        "ostatni_miesiac": 0, "niepelny": False,
        "miesiac_rozjazdu": None, "roznica_koncowa": None, "zmiana_proc": None,
    }
    if not auto_id or not lata:
        return pusty

    with polacz_baze() as conn:
        wiersze = _wiersze_kosztow(conn, auto_id)
    historia_prz = pobierz_historie_przebiegu(auto_id)

    surowe_b = _serie_roku(wiersze, historia_prz, wybrany, wielkosc)
    surowe_p = _serie_roku(wiersze, historia_prz, wybrany - 1, wielkosc)

    # Rok, w którym nie ma ANI JEDNEGO wpisu, to brak danych — nie zero. Płaska
    # linia przy zerze mówiłaby „wtedy nic nie kosztowało”, a prawda jest taka,
    # że wtedy nikt nic nie zapisywał (albo auta jeszcze nie było).
    if wybrany - 1 not in lata:
        return dict(pusty, biezacy=[], poprzedni=[], roznice=[],
                    ostatni_miesiac=(dzien.month if wybrany == dzien.year else 12),
                    niepelny=wybrany == dzien.year)

    niepelny = wybrany == dzien.year
    ostatni = dzien.month if niepelny else 12

    kum_b = _narastajaco(surowe_b, wielkosc)
    kum_p = _narastajaco(surowe_p, wielkosc)
    pokaz_b = kum_b if narastajaco else _miesiecznie(surowe_b, wielkosc)
    pokaz_p = kum_p if narastajaco else _miesiecznie(surowe_p, wielkosc)

    # Rok w toku urywa się na bieżącym miesiącu: krzywa ciągnąca się do grudnia
    # po zerach wyglądałaby jak nagły spadek kosztów.
    biezacy = [w if (i < ostatni) else None for i, w in enumerate(pokaz_b)]

    roznice = [
        (biezacy[i] - pokaz_p[i])
        if (biezacy[i] is not None and pokaz_p[i] is not None) else None
        for i in range(12)
    ]

    # Rozjazd zawsze z krzywych NARASTAJĄCYCH: szukamy miesiąca, w którym luka
    # między latami urosła najbardziej w stronę wyniku końcowego.
    luki = [
        (kum_b[i] - kum_p[i]) if (kum_b[i] is not None and kum_p[i] is not None) else None
        for i in range(ostatni)
    ]
    luki_znane = [l for l in luki if l is not None]
    koncowa = luki_znane[-1] if luki_znane else None

    miesiac_rozjazdu = None
    if koncowa:
        kierunek = 1 if koncowa > 0 else -1
        przyrosty = []
        poprzednia = 0.0
        for i, luka in enumerate(luki):
            if luka is None:
                continue
            przyrosty.append((i + 1, (luka - poprzednia) * kierunek))
            poprzednia = luka
        if przyrosty:
            miesiac, przyrost = max(przyrosty, key=lambda p: p[1])
            if przyrost / abs(koncowa) >= PROG_ROZJAZDU:
                miesiac_rozjazdu = miesiac

    baza = kum_p[ostatni - 1] if ostatni else None
    teraz = kum_b[ostatni - 1] if ostatni else None
    zmiana = (((teraz - baza) / baza * 100)
              if (baza and teraz is not None and baza > 0) else None)

    return {
        "rok": wybrany, "rok_poprzedni": wybrany - 1, "lata": lata,
        "wielkosc": wielkosc, "etykieta": etykieta, "jednostka": jednostka,
        "wzrost_zly": wzrost_zly, "narastajaco": bool(narastajaco),
        "biezacy": biezacy, "poprzedni": list(pokaz_p), "roznice": roznice,
        "ostatni_miesiac": ostatni, "niepelny": niepelny,
        "miesiac_rozjazdu": miesiac_rozjazdu,
        "roznica_koncowa": koncowa, "zmiana_proc": zmiana,
    }


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
                         f"{b['dzien_przekroczenia']} — "
                         f"{liczba_z_odmiana(b['dni_pozostalo'], 'dzień', 'dni', 'dni')} przed końcem okresu.")
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
            tekst_baku = (
                f"Szacunkowo zostało około {formatuj_liczba_eksport(bak['zasieg_pozostaly'], 0)} km "
                f"({formatuj_liczba_eksport(bak['procent_baku'], 0)}% baku)."
            )
            if bak.get("dni_do_pustego") is not None:
                ile = bak["dni_do_pustego"]
                opis_dni = "dziś" if ile <= 0 else "jutro" if ile == 1 else f"za około {ile} dni"
                tekst_baku += f" Przy Twoim tempie zabraknie paliwa {opis_dni}."
            obserwacje.append(_obserwacja(
                "bak_niski", "uwaga", "bak", "Czas zatankować",
                tekst_baku,
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
        # Słowo „wyższe/niższe” opisuje SUROWĄ zmianę (te dwie liczby widać na
        # ekranie), a tytuł i sam fakt pojawienia się obserwacji biorą się ze
        # zmiany po odjęciu sezonu. Te dwie rzeczy mogą się rozjechać i tak ma
        # być: spadek o 3% w maju to i tak wzrost, jeśli w maju zwykle spada o 9%.
        if abs(trend["zmiana_proc"]) < 1:
            surowa = "zużycie praktycznie bez zmian"
        else:
            surowa = (f"zużycie {'wyższe' if trend['zmiana_proc'] > 0 else 'niższe'} "
                      f"o {procent}%")
        sezon = opis_sezonowosci_trendu(trend)
        tresc = (f"Ostatnie {trend['odcinkow_ostatnio']} odcinki: {teraz} wobec {wczesniej} "
                 f"wcześniej — {surowa}." + (f" {sezon}" if sezon else "") + ogon)
        w_gore = trend["kierunek"] == "wzrost"
        obserwacje.append(_obserwacja(
            "trend_spalania", "uwaga" if w_gore else "dobry", "spalanie",
            "Zużycie w górę" if w_gore else "Zużycie w dół",
            tresc, 80 if w_gore else 60, "/",
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

    # 6. Ceny paliwa: gdzie tankujesz drożej, niż musisz. Jedno źródło energii
    #    naraz — przy hybrydzie plug-in ładowarka w garażu nie może wygrać
    #    rankingu stacji paliw, a oszczędność liczy się tym samym źródłem.
    rodzaj_cen = domyslny_rodzaj_energii(auto_id)
    ceny = pobierz_trend_cen_paliwa(auto_id, rodzaj=rodzaj_cen)
    stacje = [st for st in ceny.get("stacje", []) if st["liczba_tankowan"] >= 2]
    if len(stacje) >= 2:
        najtansza, najdrozsza = stacje[0], stacje[-1]
        roznica = najdrozsza["srednia_cena"] - najtansza["srednia_cena"]
        if najtansza["srednia_cena"] > 0 and roznica / najtansza["srednia_cena"] >= 0.04:
            litry_rocznie = 0.0
            seria = pobierz_serie_spalania(auto_id, limit=5, rodzaj=rodzaj_cen)
            sredni_dzienny = oblicz_sredni_dzienny_przebieg(auto_id)
            if seria and sredni_dzienny:
                spalanie = sum(w for _, w in seria) / len(seria)
                litry_rocznie = spalanie / 100 * sredni_dzienny * 365
            oszczednosc = roznica * litry_rocznie
            prad = rodzaj_cen == ENERGIA_PRAD
            ogon = (f" {'Ładując' if prad else 'Tankując'} zawsze tam, zaoszczędziłbyś około "
                    f"{_kwota_txt(oszczednosc)} rocznie." if oszczednosc >= 50 else "")
            obserwacje.append(_obserwacja(
                "stacje_ceny", "neutralny", "stacja", "Różnice między stacjami",
                f"„{najtansza['nazwa']}” wychodzi średnio o "
                f"{formatuj_liczba_eksport(roznica, 2)} {pobierz_walute()} na "
                f"{'kWh' if prad else 'litrze'} taniej niż „{najdrozsza['nazwa']}”.{ogon}",
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

    # 8. Koszt na 1000 km w oknie kroczącym — liczba, która mówi „sprzedaj”.
    #    Roczna suma rośnie też wtedy, gdy po prostu jeździsz więcej; ta nie,
    #    bo dzieli wydatek przez dystans, za który go poniesiono.
    krzywa = koszt_na_1000km(auto_id, pobierz_okno_kroczace(auto_id))
    srednia_1000 = krzywa.get("srednia_zyciowa")
    biezacy_1000 = krzywa.get("biezacy")
    if srednia_1000 and biezacy_1000 and srednia_1000 > 0:
        nad = (biezacy_1000 - srednia_1000) / srednia_1000 * 100
        if nad >= PROG_DROZENIA_1000KM:
            obserwacje.append(_obserwacja(
                "drozeje_1000km", "zly" if nad >= 2 * PROG_DROZENIA_1000KM else "uwaga",
                "koszt_km", "Auto drożeje",
                f"Ostatnie {liczba_z_odmiana(krzywa['okno'], 'miesiąc', 'miesiące', 'miesięcy')} to "
                f"{_kwota_txt(biezacy_1000)} na 1000 km — "
                f"o {formatuj_liczba_eksport(nad, 0)}% więcej niż średnia z całej historii "
                f"({_kwota_txt(srednia_1000)}). Sama suma roczna tego nie pokaże: rośnie też "
                f"wtedy, gdy po prostu jeździsz więcej.",
                85,
            ))
        elif nad <= -PROG_DROZENIA_1000KM:
            obserwacje.append(_obserwacja(
                "tanieje_1000km", "dobry", "koszt_km", "Auto tanieje",
                f"Ostatnie {liczba_z_odmiana(krzywa['okno'], 'miesiąc', 'miesiące', 'miesięcy')} to "
                f"{_kwota_txt(biezacy_1000)} na 1000 km — "
                f"o {formatuj_liczba_eksport(abs(nad), 0)}% taniej niż średnia z całej historii "
                f"({_kwota_txt(srednia_1000)}).",
                45,
            ))

    # 9. Robocizna czy części — pytanie, na które sama kwota naprawy nie
    #    odpowiada: płacisz za ręce warsztatu czy za części. Tylko naprawy
    #    z podziałem i tylko rok wstecz, bo stawki warsztatów idą w górę.
    rozbicie = pobierz_rozbicie_napraw(auto_id, _przesun_o_lata(dzis, 1), dzis)
    if rozbicie["napraw"] >= 2 and rozbicie["razem"] > 0:
        udzial = rozbicie["robocizna"] / rozbicie["razem"] * 100
        tekst = (f"W ostatnich 12 miesiącach robocizna to {formatuj_liczba_eksport(udzial, 0)}% kosztu napraw "
                 f"({_kwota_txt(rozbicie['robocizna'])} z {_kwota_txt(rozbicie['razem'])}), "
                 f"a części {formatuj_liczba_eksport(100 - udzial, 0)}%")
        if rozbicie["z_magazynu"] > 0:
            tekst += f" — w tym {_kwota_txt(rozbicie['z_magazynu'])} z własnego magazynu"
        tekst += "."
        # Warsztaty porównujemy dopiero przy dwóch naprawach w każdym — jedna
        # wymiana rozrządu obok jednej wymiany żarówki nie mówi o stawce nic.
        warsztaty = [w for w in rozbicie["warsztaty"] if w["napraw"] >= 2]
        if len(warsztaty) >= 2:
            drogi, tani = warsztaty[0], warsztaty[-1]
            if tani["srednia_robocizna"] > 0 and drogi["srednia_robocizna"] >= 1.25 * tani["srednia_robocizna"]:
                tekst += (f" Najdrożej liczy „{drogi['nazwa']}”: średnio {_kwota_txt(drogi['srednia_robocizna'])} "
                          f"robocizny na naprawę, a „{tani['nazwa']}” {_kwota_txt(tani['srednia_robocizna'])}.")
        if rozbicie["bez_podzialu"]:
            tekst += f" Naprawy bez podziału pominięte: {rozbicie['bez_podzialu']}."
        obserwacje.append(_obserwacja(
            "robocizna_czesci", "neutralny", "warsztat", "Robocizna czy części", tekst, 30, "/wizyty",
        ))

    # 10. Własne części kontra kupione przez warsztat — ten sam podzespół raz
    #     tak, raz tak. Trzy lata wstecz: przy starszych naprawach różnica
    #     mówiłaby więcej o inflacji niż o tym, gdzie kupować.
    for p in porownaj_czesci_wlasne(auto_id, _przesun_o_lata(dzis, 3), dzis):
        roznica = p["roznica"]
        if abs(roznica) < 20 or abs(roznica) < 0.1 * max(p["z_warsztatu"], p["wlasne"]):
            continue
        if roznica > 0:
            obserwacje.append(_obserwacja(
                "czesci_wlasne", "dobry", "czesci", "Własne części wychodzą taniej",
                f"„{p['nazwa']}”: części z własnego magazynu kosztowały średnio {_kwota_txt(p['wlasne'])}, "
                f"a kupione przez warsztat {_kwota_txt(p['z_warsztatu'])} — o {_kwota_txt(roznica)} mniej "
                f"na każdej naprawie.",
                40, f"/historia/{p['zadanie_id']}",
            ))
        else:
            obserwacje.append(_obserwacja(
                "czesci_wlasne", "neutralny", "czesci", "Warsztat kupuje części taniej",
                f"„{p['nazwa']}”: części kupione przez warsztat kosztowały średnio {_kwota_txt(p['z_warsztatu'])}, "
                f"a z własnego magazynu {_kwota_txt(p['wlasne'])} — kupowanie samemu wyszło o "
                f"{_kwota_txt(-roznica)} drożej na naprawie.",
                40, f"/historia/{p['zadanie_id']}",
            ))
        break

    obserwacje.sort(key=lambda o: -o["waga"])
    return obserwacje[:limit] if limit else obserwacje


__all__ = [
    "MAKS_WYROZNIONYCH_WYDATKOW",
    "MAX_LAT_SEZONU",
    "MIN_ODCINKOW_SEZONU",
    "OKRESY_BUDZETU",
    "PROG_DROZENIA_1000KM",
    "PROG_PRAWIE",
    "PROG_ROZJAZDU",
    "PROG_ISTOTNOSCI_TRENDU",
    "PROG_WYROZNIENIA_WYDATKU",
    "PUNKTOW_ISKRY_SKUMULOWANEJ",
    "PROG_POKAZANIA_SEZONU",
    "PROG_UWAGI_BUDZETU",
    "TOLERANCJA_SEZONU_DNI",
    "WIELKOSCI_RDR",
    "_DYSTANSE_ODNIESIENIA",
    "_granice_okresu",
    "_km_miesiecznie_w_roku",
    "_km_w_roku",
    "_kwota_txt",
    "_obserwacja",
    "_porownanie_dystansu",
    "_przesun_o_lata",
    "_sezonowosc_zmiany",
    "_miesiecznie",
    "_narastajaco",
    "_serie_roku",
    "_srednia_okna",
    "_zmiana_1000km",
    "_wiersze_kosztow_z_opisem",
    "analizuj_trend_spalania",
    "koszt_skumulowany",
    "koszty_rok_do_roku",
    "koszt_trendu_rocznie",
    "lata_z_danymi",
    "obserwacje_analityczne",
    "opis_sezonowosci_trendu",
    "OKRESY_RUCHOME",
    "pobierz_budzety",
    "pobierz_zasieg_na_baku",
    "podsumowanie_roku",
    "prognoza_kosztow",
    "stan_budzetow",
    "zapisz_budzet",
]
