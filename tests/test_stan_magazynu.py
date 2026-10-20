"""Stan magazynu = stan wyjściowy minus zużycie ze wszystkich telefonów (migracja 55).

Dawniej stan części jechał do chmury jako gotowa liczba: dwa telefony bez sieci, które
zużyły tę samą część, wysyłały po „4” i w chmurze zostawało 4 zamiast 3. Teraz do chmury
jedzie stan wyjściowy (`ilosc_bazowa`), a stan liczy każdy telefon: stan wyjściowy minus
zużycie z wpisów, wizyt i dolewek — także tych z drugiego telefonu. Sprawdzamy:

1. rachunek — wszystkie nośniki zużycia, zwroty, korekta, zakup, scalenie;
2. chmura — samo zużycie nie zmienia rekordu pozycji i nie robi konfliktu, korekta wygrywa
   (dwie korekty to konflikt), rekord ze starszej wersji niesie swój stan;
3. migracja 55 i kosz — stan na półce się nie zmienia, odcisk niezmienionego rekordu
   przechodzi na nową postać, stara migawka wraca ze swoim stanem.
"""

import json

import pytest

import db
import pomoce
import probki_baz
import sync
from pomoce import ChmuraWPamieci
from sync import konflikty as sync_konflikty
from sync import pobieranie as sync_pobieranie
from sync import pomocnicze as sync_pomocnicze
from sync import przebieg as sync_przebieg
from sync import wysylanie as sync_wysylanie

KONFIG = next(k for k in sync.KONFIGURACJA_SYNC if k["tabela"] == "magazyn_czesci")


def stan(czesc_id):
    with db.polacz_baze() as conn:
        return tuple(conn.execute("SELECT ilosc, ilosc_bazowa FROM magazyn_czesci WHERE id=?",
                                  (czesc_id,)).fetchone())


def nowy_wpis(ident, przebieg=101500):
    with db.polacz_baze() as conn:
        return conn.execute("INSERT INTO historia (zadanie_id, data, przebieg, kategoria, cena) VALUES (?,?,?,?,?)",
                            (ident["zadanie"], "01.03.2026", przebieg, "Serwis", 0.0)).lastrowid


@pytest.fixture
def czesc(baza):
    """Pojazd z pomoce.utworz_pojazd: filtr oleju 2 szt. na półce, 2 szt. już zużyte (wizyta i wpis)."""
    ident = pomoce.utworz_pojazd("Pierwszy")
    assert stan(ident["magazyn"]) == (2.0, 4.0)
    return ident


# ============================================================================
#  1. RACHUNEK
# ============================================================================

def test_kazdy_nosnik_zuzycia_schodzi_ze_stanu_i_wraca_po_zwrocie(czesc):
    m = czesc["magazyn"]
    wpis = nowy_wpis(czesc)
    db.rozlicz_czesci_z_magazynu_wpisu(wpis, [(m, 1.0)])
    assert stan(m) == (1.0, 4.0), "zużycie zmienia stan, nie stan wyjściowy"

    db.zapisz_dolewke(czesc["auto_id"], {"data": "02.03.2026", "przebieg": 101600, "plyn": db.PLYN_OLEJ,
                                         "ilosc": 0.5, "magazyn_id": m})
    assert stan(m) == (0.5, 4.0)

    db.przywroc_czesci_wpisu(wpis)
    assert stan(m) == (1.5, 4.0), "zwrot to po prostu mniej zużycia"


def test_zuzycie_ponad_stan_nie_zawyza_zwrotu(czesc):
    """Dawny zapis `MAX(0, ilosc - n)` gubił nadwyżkę, a zwrot dodawał ją z powrotem: z 2 sztuk
    i zużytych 5 robiło się po zwrocie 5. Teraz zwrot wraca dokładnie do stanu sprzed zużycia."""
    m = czesc["magazyn"]
    wpis = nowy_wpis(czesc)
    db.rozlicz_czesci_z_magazynu_wpisu(wpis, [(m, 5.0)])
    assert stan(m)[0] == 0.0

    db.przywroc_czesci_wpisu(wpis)
    assert stan(m) == (2.0, 4.0)


def test_korekta_zakup_i_scalenie_zmieniaja_stan_wyjsciowy(czesc):
    m = czesc["magazyn"]
    with db.polacz_baze() as conn:
        db.ustaw_stan_magazynu(conn, m, 7)
    assert stan(m) == (7.0, 9.0), "na półce ma być 7 — zużycie dalej się odejmuje"

    wynik = db.kup_ponownie(m, 3, 20.0)
    assert wynik["stan"] == 10.0 and stan(m) == (10.0, 12.0)

    wpis = nowy_wpis(czesc)
    with db.polacz_baze() as conn:
        drugi = conn.execute("INSERT INTO magazyn_czesci (auto_id, nazwa, ilosc, ilosc_bazowa, jednostka) "
                             "VALUES (?,?,?,?,?)", (czesc["auto_id"], "filtr oleju", 1.0, 2.0, "szt")).lastrowid
        conn.execute("INSERT INTO historia_czesci_magazynu (historia_id, magazyn_id, ilosc_uzyta) VALUES (?,?,?)",
                     (wpis, drugi, 1.0))
    assert db.scal_duplikaty_nazw(czesc["auto_id"], "magazyn_czesci", m, [drugi]) == 1
    assert stan(m)[0] == 11.0, "po scaleniu stan to suma stanów, a zużycie duplikatu przechodzi na docelową"


def test_zuzycie_z_drugiego_telefonu_schodzi_po_synchronizacji(czesc):
    """Po pobraniu zużycia z chmury synchronizacja przelicza stan (db.przelicz_stan_magazynu)."""
    m = czesc["magazyn"]
    with db.polacz_baze() as conn:
        conn.execute("INSERT INTO historia_czesci_magazynu (historia_id, magazyn_id, ilosc_uzyta, zdalne_id) "
                     "VALUES (?,?,?,?)", (nowy_wpis(czesc), m, 1.0, "hcm-z-drugiego"))

    db.przelicz_stan_magazynu(auto_id=czesc["auto_id"])

    assert stan(m) == (1.0, 4.0)


# ============================================================================
#  2. CHMURA
# ============================================================================

def wypchnij(chmura, auto_id):
    sync_konflikty._konflikty_biezacej_synchronizacji.clear()
    return sync_wysylanie._wypchnij_tabele(chmura, "wspolny", auto_id, KONFIG, db.ROLA_WLASCICIEL)[0]


def zsynchronizowana(czesc):
    """Pozycja wysłana do chmury; zwraca (chmura, zdalne_id)."""
    chmura = ChmuraWPamieci()
    with db.polacz_baze() as conn:
        conn.execute("UPDATE magazyn_czesci SET zdalne_id=NULL, zdalny_hash=NULL WHERE id=?", (czesc["magazyn"],))
    assert wypchnij(chmura, czesc["auto_id"]) == 1
    (zdalne_id,) = chmura.rekordy
    assert chmura.rekordy[zdalne_id]["ilosc_bazowa"] == 4.0
    return chmura, zdalne_id


def test_samo_zuzycie_nie_zmienia_rekordu_ani_nie_robi_konfliktu(czesc):
    chmura, zdalne_id = zsynchronizowana(czesc)
    db.rozlicz_czesci_z_magazynu_wpisu(nowy_wpis(czesc), [(czesc["magazyn"], 1.0)])
    # Drugi telefon w tym czasie też zużył (pół sztuki) i wysłał swój stan — pochodną.
    chmura.rekordy[zdalne_id] = dict(chmura.rekordy[zdalne_id], ilosc=1.5)

    assert wypchnij(chmura, czesc["auto_id"]) == 0, "zużycie to nie zmiana pozycji"
    assert sync_konflikty._konflikty_biezacej_synchronizacji == []
    assert chmura.rekordy[zdalne_id]["ilosc_bazowa"] == 4.0
    assert chmura.rekordy[zdalne_id]["ilosc"] == 1.0, "starsza wersja czyta stan z chmury — dostaje tutejszy"


def test_korekta_wygrywa_bez_konfliktu_gdy_druga_strona_tylko_zuzywala(czesc):
    chmura, zdalne_id = zsynchronizowana(czesc)
    chmura.rekordy[zdalne_id] = dict(chmura.rekordy[zdalne_id], ilosc=1.0)
    with db.polacz_baze() as conn:
        db.ustaw_stan_magazynu(conn, czesc["magazyn"], 6)

    assert wypchnij(chmura, czesc["auto_id"]) == 1
    assert sync_konflikty._konflikty_biezacej_synchronizacji == []
    assert chmura.rekordy[zdalne_id]["ilosc_bazowa"] == 8.0


def test_dwie_korekty_to_konflikt_a_wygrywa_ostatnia(czesc):
    chmura, zdalne_id = zsynchronizowana(czesc)
    chmura.rekordy[zdalne_id] = dict(chmura.rekordy[zdalne_id], ilosc=5.0, ilosc_bazowa=7.0)
    with db.polacz_baze() as conn:
        db.ustaw_stan_magazynu(conn, czesc["magazyn"], 6)

    assert wypchnij(chmura, czesc["auto_id"]) == 1

    (konflikt,) = sync_konflikty._konflikty_biezacej_synchronizacji
    assert konflikt["dane_zdalne"]["ilosc_bazowa"] == 7.0
    assert chmura.rekordy[zdalne_id]["ilosc_bazowa"] == 8.0


def test_pochodna_nie_nadpisuje_cudzej_korekty(czesc):
    """Tu tylko zużycie, w chmurze cudza korekta: wysłanie samej pochodnej nadpisałoby korektę
    drugiej osoby — czeka, aż pobranie ją przyniesie."""
    chmura, zdalne_id = zsynchronizowana(czesc)
    chmura.rekordy[zdalne_id] = dict(chmura.rekordy[zdalne_id], ilosc=5.0, ilosc_bazowa=7.0)
    db.rozlicz_czesci_z_magazynu_wpisu(nowy_wpis(czesc), [(czesc["magazyn"], 1.0)])

    assert wypchnij(chmura, czesc["auto_id"]) == 0
    assert sync_konflikty._konflikty_biezacej_synchronizacji == []
    assert (chmura.rekordy[zdalne_id]["ilosc"], chmura.rekordy[zdalne_id]["ilosc_bazowa"]) == (5.0, 7.0)


class _PustaChmura:
    """Chmura bez rekordów na cały przebieg `_synchronizuj_pod_zamkiem`: przyjmuje każde wysłanie."""

    class _Odpowiedz:
        def __init__(self, data):
            self.data = data

    def rpc(self, nazwa, parametry):
        return type("W", (), {"execute": lambda _s: self._Odpowiedz(f"{parametry.get('p_tabela', 'r')}-nowy")})()

    def table(self, nazwa):
        chmura = self

        class _Zapytanie:
            def __getattr__(self, _nazwa):
                return lambda *a, **k: self

            def execute(self):
                return chmura._Odpowiedz([])
        return _Zapytanie()


def test_synchronizacja_przelicza_stan_po_pobraniu(czesc, monkeypatch):
    """Zużycie przyjechało z chmury (wiersz bez przeliczenia) — przebieg synchronizacji kończy
    się przeliczeniem stanu, tak jak przeliczeniem podzespołów."""
    with db.polacz_baze() as conn:
        conn.execute("INSERT INTO historia_czesci_magazynu (historia_id, magazyn_id, ilosc_uzyta, zdalne_id) "
                     "VALUES (?,?,?,?)", (nowy_wpis(czesc), czesc["magazyn"], 1.5, "hcm-pobrany"))
    assert stan(czesc["magazyn"]) == (2.0, 4.0)
    monkeypatch.setattr(sync_przebieg, "_upewnij_sesje", lambda: (_PustaChmura(), "uid"))

    sync_przebieg._synchronizuj_pod_zamkiem(czesc["auto_id"], "wspolny")

    assert stan(czesc["magazyn"]) == (0.5, 4.0)


def test_pobrana_korekta_zmienia_stan_a_sama_pochodna_nie(czesc):
    chmura, zdalne_id = zsynchronizowana(czesc)
    with db.polacz_baze() as conn:
        zapamietany = conn.execute("SELECT zdalny_hash FROM magazyn_czesci WHERE id=?",
                                   (czesc["magazyn"],)).fetchone()[0]

    def pobierz(dane):
        znane = {zdalne_id: {"id": czesc["magazyn"], "hash": zapamietany}}
        wynik = sync_pobieranie._zastosuj_rekord(KONFIG, {"id": zdalne_id, "dane": dane}, czesc["auto_id"], znane)
        db.przelicz_stan_magazynu(auto_id=czesc["auto_id"])
        return wynik

    assert pobierz(dict(chmura.rekordy[zdalne_id], ilosc=0.0)) == 0, "cudza pochodna nie nadpisuje tutejszej"
    assert stan(czesc["magazyn"]) == (2.0, 4.0)

    assert pobierz(dict(chmura.rekordy[zdalne_id], ilosc_bazowa=10.0)) == 1
    assert stan(czesc["magazyn"]) == (8.0, 10.0)


def test_rekord_ze_starszej_wersji_niesie_swoj_stan(czesc):
    """Starsza wersja nie zna stanu wyjściowego: jej stan to prawda tamtego telefonu."""
    chmura, zdalne_id = zsynchronizowana(czesc)
    stary = {k: v for k, v in chmura.rekordy[zdalne_id].items() if k != "ilosc_bazowa"}
    stary["ilosc"] = 5.0
    znane = {zdalne_id: {"id": czesc["magazyn"], "hash": "z innej synchronizacji"}}

    assert sync_pobieranie._zastosuj_rekord(KONFIG, {"id": zdalne_id, "dane": stary}, czesc["auto_id"], znane) == 1
    db.przelicz_stan_magazynu(auto_id=czesc["auto_id"])

    assert stan(czesc["magazyn"]) == (5.0, 7.0)
    # Najbliższa synchronizacja dosyła stan wyjściowy — bez konfliktu, bo chmura się nie zmieniła.
    chmura.rekordy[zdalne_id] = stary
    assert wypchnij(chmura, czesc["auto_id"]) == 1
    assert sync_konflikty._konflikty_biezacej_synchronizacji == []
    assert chmura.rekordy[zdalne_id]["ilosc_bazowa"] == 7.0


# ============================================================================
#  3. MIGRACJA 55 I KOSZ
# ============================================================================

def test_odcisk_migracji_liczy_sie_jak_odcisk_chmury():
    dane = {"nazwa": "Filtr", "ilosc": 2.0, "cena": None, "_autor_uid": "x", "link": "ą"}
    assert db.stan_magazynu._odcisk_jak_w_chmurze(dane) == sync_wysylanie._hash_zawartosci(dane)


def test_migracja_55_nie_rusza_stanu_i_przepisuje_odcisk_niezmienionego(magazyn):
    probka = next(p for p in probki_baz.probki() if probki_baz.wersja_probki(p) == 54)
    probki_baz.odtworz_z_probki(probka, db.BAZA_DANYCH)
    kolumny = [k for k in KONFIG["kolumny"] if k != "ilosc_bazowa"]
    with db.polacz_baze() as conn:
        conn.row_factory = None
        wiersze = conn.execute(f"SELECT id, {', '.join(kolumny)} FROM magazyn_czesci ORDER BY id").fetchall()
        assert len(wiersze) >= 2, "próbka musi nieść pozycje magazynu"
        (czysty, *_), (zmieniony, *_) = wiersze[0], wiersze[1]
        dawne = dict(zip(kolumny, wiersze[0][1:]))
        conn.execute("UPDATE magazyn_czesci SET zdalne_id='mag-1', zdalny_hash=? WHERE id=?",
                     (sync_wysylanie._hash_zawartosci(dawne), czysty))
        conn.execute("UPDATE magazyn_czesci SET zdalne_id='mag-2', zdalny_hash='zmieniony lokalnie' WHERE id=?",
                     (zmieniony,))
        przed = dict(conn.execute("SELECT id, ilosc FROM magazyn_czesci").fetchall())

    db.init_db()

    with db.polacz_baze() as conn:
        po = {i: (ilosc, baza) for i, ilosc, baza in conn.execute("SELECT id, ilosc, ilosc_bazowa FROM magazyn_czesci")}
        zuzycie = db.zuzycie_pozycji(conn)
        zapamietane = dict(conn.execute("SELECT id, zdalny_hash FROM magazyn_czesci"))
        biezace = dict(zip(KONFIG["kolumny"], conn.execute(
            f"SELECT {', '.join(KONFIG['kolumny'])} FROM magazyn_czesci WHERE id=?", (czysty,)).fetchone()))
    for i, ilosc in przed.items():
        assert po[i][0] == ilosc, "migracja nie zmienia stanu na półce"
        assert po[i][1] == pytest.approx((db.pomocnicze._na_liczbe(ilosc) or 0) + zuzycie.get(i, 0.0))
    # Niezmieniony rekord: pierwsza synchronizacja po aktualizacji go nie wyśle.
    assert zapamietane[czysty] == sync_pomocnicze._hash_rekordu(biezace, KONFIG)
    assert sync_wysylanie._zgodny_z_zapamietanym(biezace, zapamietane[czysty], KONFIG["dopisane"], KONFIG["pochodne"])
    assert zapamietane[zmieniony] == "zmieniony lokalnie", "zmiana sprzed aktualizacji dalej czeka na wysłanie"


def test_przywrocone_zuzycie_schodzi_takze_z_pozycji_bez_stanu_wyjsciowego(czesc):
    """Stan wyjściowy liczy się PRZED zmianą zużycia — po niej wziąłby za punkt wyjścia stan
    już z przywróconym zużyciem i część nie zeszłaby z półki."""
    m = czesc["magazyn"]
    wynik = db.usun_z_cofnieciem("historia", czesc["historia"])
    assert stan(m) == (3.0, 4.0)
    with db.polacz_baze() as conn:
        conn.execute("UPDATE magazyn_czesci SET ilosc_bazowa=NULL WHERE id=?", (m,))

    assert db.przywroc_wpis_z_kosza(wynik["kosz_id"])["ok"]

    assert stan(m) == (2.0, 4.0)


def test_migawka_sprzed_55_wraca_ze_swoim_stanem(czesc):
    kosz_id = db.usun_auto_do_kosza(czesc["auto_id"])["kosz_id"]
    with db.polacz_baze() as conn:
        migawka = json.loads(conn.execute("SELECT migawka FROM kosz_pojazdy WHERE id=?", (kosz_id,)).fetchone()[0])
        for wiersz in migawka["tabele"]["magazyn_czesci"]["wiersze"]:
            wiersz.pop("ilosc_bazowa", None)
        conn.execute("UPDATE kosz_pojazdy SET migawka=? WHERE id=?", (json.dumps(migawka), kosz_id))

    auto_id = db.przywroc_auto_z_kosza(kosz_id)

    with db.polacz_baze() as conn:
        (m,) = conn.execute("SELECT id FROM magazyn_czesci WHERE auto_id=?", (auto_id,)).fetchone()
    assert stan(m) == (2.0, 4.0)
