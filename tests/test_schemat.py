"""Listy w kodzie kontra rzeczywisty schemat bazy.

KONFIGURACJA_SYNC, KOLUMNY_POJAZDU, KOSZ_TABELE_* i KOLUMNY_ZE_SCIEZKAMI opisują
ten sam model danych z czterech stron. Każda zmiana schematu dotyka ich wszystkich
naraz, a pominięcie nie wywala aplikacji — po prostu coś po cichu nie jedzie do
chmury albo nie wraca z kosza. Dokładnie ten rodzaj kontroli, który maszyna robi
lepiej niż człowiek po każdej migracji.

Testy czytają PRAGMA z prawdziwej, zmigrowanej bazy — nie z kopii schematu
przepisanej do testu, bo taka kopia rozjeżdża się przy pierwszej migracji.
"""

import sqlite3

import pytest

import db
import pomoce
import sync


TABELE_SYNC = [k["tabela"] for k in sync.KONFIGURACJA_SYNC]


# Tabele, które MAJĄ auto_id, ale świadomie nie jadą do kosza razem z pojazdem.
# Dopisanie tu czegokolwiek jest decyzją: „te dane wolno stracić przy usunięciu auta".
POZA_KOSZEM_SWIADOMIE = {
    "wyciszone_powiadomienia",  # wyciszenie jest tymczasowe, przywiązane do chwili
    "kolejka_sync",             # kolejka wysyłki, czyszczona przy usunięciu (usun_z_kolejki_sync)
    "zdalne_nagrobki",          # zapis usunięć DO wysłania, nie dane pojazdu
}


@pytest.fixture(scope="module")
def _schemat_modulu(tmp_path_factory):
    """Jedna zmigrowana baza na cały plik — testy schematu tylko z niej czytają."""
    return None


def kolumny_tabeli(tabela):
    return set(pomoce.kolumny(tabela))


def wszystkie_tabele():
    return set(pomoce.nazwy_tabel())


# ------------------------------------------------- KONFIGURACJA_SYNC


def test_kazda_synchronizowana_tabela_istnieje(baza):
    brakujace = [t for t in TABELE_SYNC if t not in wszystkie_tabele()]
    assert brakujace == []


def test_kazda_synchronizowana_kolumna_istnieje(baza):
    bledy = []
    for konfig in sync.KONFIGURACJA_SYNC:
        istniejace = kolumny_tabeli(konfig["tabela"])
        for kolumna in konfig["kolumny"]:
            if kolumna not in istniejace:
                bledy.append(f"{konfig['tabela']}.{kolumna}")
    assert bledy == [], "kolumny z KONFIGURACJA_SYNC, których nie ma w bazie: " + ", ".join(bledy)


def test_synchronizowane_tabele_maja_kolumny_ksiegowe(baza):
    """Bez `zdalne_id` i `zdalny_hash` wypychanie i pobieranie nie ma się czego chwycić."""
    bledy = []
    for tabela in TABELE_SYNC:
        istniejace = kolumny_tabeli(tabela)
        for kolumna in ("zdalne_id", "zdalny_hash"):
            if kolumna not in istniejace:
                bledy.append(f"{tabela}.{kolumna}")
    assert bledy == []


def test_klucze_obce_sync_wskazuja_na_tabele_synchronizowane_wczesniej(baza):
    """Rodzic musi jechać PRZED dzieckiem — inaczej dziecko nie ma się do czego dowiązać."""
    for pozycja, konfig in enumerate(sync.KONFIGURACJA_SYNC):
        istniejace = kolumny_tabeli(konfig["tabela"])
        for kolumna, rodzic in (konfig.get("fk") or {}).items():
            assert kolumna in istniejace, f"{konfig['tabela']}.{kolumna} nie istnieje w bazie"
            assert rodzic in TABELE_SYNC, f"{konfig['tabela']}.{kolumna} wskazuje na niesynchronizowaną {rodzic}"
            assert TABELE_SYNC.index(rodzic) < pozycja, (
                f"{rodzic} jest w KONFIGURACJA_SYNC PO {konfig['tabela']}, "
                "a musi być przed nim, bo jest jego rodzicem"
            )


def test_klucze_obce_sync_pokrywaja_sie_ze_schematem(baza):
    """Każdy klucz obcy zadeklarowany w bazie (poza auto_id) musi być opisany w `fk`.

    Pominięty klucz obcy oznacza rekord, który przyjedzie z chmury dowiązany
    do lokalnego ID z cudzego telefonu."""
    bledy = []
    with db.polacz_baze() as conn:
        c = conn.cursor()
        for konfig in sync.KONFIGURACJA_SYNC:
            c.execute(f"PRAGMA foreign_key_list({konfig['tabela']})")
            for wiersz in c.fetchall():
                tabela_docelowa, kolumna = wiersz[2], wiersz[3]
                if tabela_docelowa == "samochody":
                    continue
                if (konfig.get("fk") or {}).get(kolumna) != tabela_docelowa:
                    bledy.append(f"{konfig['tabela']}.{kolumna} -> {tabela_docelowa}")
    assert bledy == [], "klucze obce nieopisane w KONFIGURACJA_SYNC: " + ", ".join(bledy)


def test_klucz_scalania_ma_odpowiednik_w_unikalnym_indeksie(baza):
    """`klucz_scalania` istnieje po to, żeby rekord z chmury wszedł w istniejący
    wiersz zamiast rozbić się o UNIQUE. Bez indeksu nie ma o co się rozbić —
    a to znaczy, że klucz jest zbędny albo indeks zniknął."""
    schemat = pomoce.zrzut_schematu()
    for konfig in sync.KONFIGURACJA_SYNC:
        klucz = konfig.get("klucz_scalania")
        if not klucz:
            continue
        istniejace = kolumny_tabeli(konfig["tabela"])
        assert set(klucz) <= istniejace, f"{konfig['tabela']}: klucz_scalania {klucz} poza schematem"
        # Scalanie szuka wiersza zapytaniem `WHERE auto_id=? AND <klucz>`, więc
        # UNIQUE w bazie obejmuje te same kolumny plus auto_id.
        unikalne = {frozenset(pola) for _, unikalny, pola in schemat[konfig["tabela"]]["indeksy"] if unikalny}
        oczekiwane = frozenset(set(klucz) | {"auto_id"})
        assert oczekiwane in unikalne or frozenset(klucz) in unikalne, (
            f"{konfig['tabela']}: klucz_scalania {klucz} nie ma odpowiadającego UNIQUE"
        )


def test_podzial_na_tabele_z_auto_id_i_posrednie(baza):
    """Tabela bez auto_id MUSI mieć opis pośredni, a z auto_id — nie może go mieć."""
    for tabela in TABELE_SYNC:
        ma_auto_id = "auto_id" in kolumny_tabeli(tabela)
        opisana_posrednio = tabela in sync.TABELE_POSREDNIE
        assert ma_auto_id != opisana_posrednio, (
            f"{tabela}: auto_id={ma_auto_id}, opis pośredni={opisana_posrednio} — jedno i drugie musi się wykluczać"
        )


def test_zapytania_sync_sa_poprawnym_sql(baza):
    """Literówka w JOIN-ie TABELE_POSREDNIE wychodzi dopiero przy synchronizacji
    u kogoś, kto ma współdzielony pojazd. Tu wychodzi od razu."""
    pomoce.utworz_pojazd("Pierwszy")
    with db.polacz_baze() as conn:
        c = conn.cursor()
        for tabela in TABELE_SYNC:
            for pola, warunek in (("*", None), ("id, zdalne_id, zdalny_hash", "zdalne_id IS NOT NULL")):
                zapytanie = sync._zapytanie_tabeli(tabela, pola, warunek)
                c.execute(zapytanie, (1,))
                c.fetchall()


def test_warunki_resetu_sync_sa_poprawnym_sql(baza):
    """`reset_where` wykonuje się przy odłączaniu współdzielenia."""
    pomoce.utworz_pojazd("Pierwszy")
    with db.polacz_baze() as conn:
        c = conn.cursor()
        for tabela, opis in sync.TABELE_POSREDNIE.items():
            c.execute(f"SELECT COUNT(*) FROM {tabela} WHERE {opis['reset_where']}", (1,))
            c.fetchone()


def test_kazda_synchronizowana_tabela_ma_ludzka_etykiete(baza):
    """Komunikat o konflikcie ma powiedzieć CO zostało nadpisane."""
    bez_etykiety = [t for t in TABELE_SYNC if t not in sync.ETYKIETY_TABEL_SYNC]
    assert bez_etykiety == []


def test_kolumny_pojazdu_istnieja_w_samochodach(baza):
    istniejace = kolumny_tabeli("samochody")
    brakujace = [k for k in sync.KOLUMNY_POJAZDU if k not in istniejace]
    assert brakujace == [], "KOLUMNY_POJAZDU poza schematem: " + ", ".join(brakujace)


# --------------------------------------------------------- listy kosza


def _tabele_zwiazane_z_pojazdem():
    """Tabele, które dowiązują się do samochodu — wprost albo przez rodzica."""
    powiazane = set()
    with db.polacz_baze() as conn:
        c = conn.cursor()
        krawedzie = {}
        for tabela in pomoce.nazwy_tabel():
            c.execute(f"PRAGMA foreign_key_list({tabela})")
            krawedzie[tabela] = {w[2] for w in c.fetchall()}
    zmiana = True
    while zmiana:
        zmiana = False
        for tabela, rodzice in krawedzie.items():
            if tabela in powiazane:
                continue
            if "samochody" in rodzice or (rodzice & powiazane):
                powiazane.add(tabela)
                zmiana = True
    return powiazane


def test_kosz_zabiera_wszystkie_tabele_pojazdu(baza):
    """Nowa tabela dowiązana do auta musi trafić do kosza albo na listę wyjątków.

    Pominięcie znaczy: usunięcie pojazdu kasuje te dane bezpowrotnie, a
    przywrócenie z kosza ich nie odtworzy — po cichu, bez żadnego błędu."""
    pominiete = _tabele_zwiazane_z_pojazdem() - set(db.KOSZ_TABELE_POTOMNE) - POZA_KOSZEM_SWIADOMIE
    assert pominiete == set(), (
        "tabele dowiązane do pojazdu, których kosz nie zabiera: " + ", ".join(sorted(pominiete))
    )


def test_kolejnosc_odtwarzania_kosza_stawia_rodzica_przed_dzieckiem(baza):
    for tabela, klucze in db.KOSZ_KLUCZE_OBCE.items():
        assert tabela in db.KOSZ_TABELE_POTOMNE
        for kolumna, rodzic in klucze.items():
            assert kolumna in kolumny_tabeli(tabela), f"{tabela}.{kolumna} nie istnieje"
            assert rodzic in db.KOSZ_TABELE_POTOMNE, f"{rodzic} nie jest odtwarzany z kosza"
            assert db.KOSZ_TABELE_POTOMNE.index(rodzic) < db.KOSZ_TABELE_POTOMNE.index(tabela), (
                f"{rodzic} odtwarzany PO {tabela} — klucz obcy nie będzie miał na czym stanąć"
            )


def test_klucze_obce_kosza_pokrywaja_sie_ze_schematem(baza):
    """Klucz obcy nieopisany w KOSZ_KLUCZE_OBCE = odwołanie, którego przy kolizji
    ID nikt nie przemapuje. Historia wraca podpięta pod cudzy podzespół."""
    bledy = []
    with db.polacz_baze() as conn:
        c = conn.cursor()
        for tabela in db.KOSZ_TABELE_POTOMNE:
            c.execute(f"PRAGMA foreign_key_list({tabela})")
            for wiersz in c.fetchall():
                docelowa, kolumna = wiersz[2], wiersz[3]
                if docelowa == "samochody":
                    continue
                if db.KOSZ_KLUCZE_OBCE.get(tabela, {}).get(kolumna) != docelowa:
                    bledy.append(f"{tabela}.{kolumna} -> {docelowa}")
    assert bledy == [], "klucze obce nieopisane w KOSZ_KLUCZE_OBCE: " + ", ".join(bledy)


def test_tabele_kosza_bez_auto_id_zgadzaja_sie_ze_schematem(baza):
    bez_auto_id = {t for t in db.KOSZ_TABELE_POTOMNE if "auto_id" not in kolumny_tabeli(t)}
    assert bez_auto_id == set(db.KOSZ_TABELE_BEZ_AUTO_ID)
    assert set(db.KOSZ_ZAPYTANIA_POSREDNIE) == set(db.KOSZ_TABELE_BEZ_AUTO_ID)


def test_zapytania_posrednie_kosza_sa_poprawnym_sql(baza):
    pomoce.utworz_pojazd("Pierwszy")
    with db.polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        for tabela, zapytanie in db.KOSZ_ZAPYTANIA_POSREDNIE.items():
            c.execute(zapytanie, (1,))
            assert len(c.fetchall()) == 1, f"{tabela}: zapytanie pośrednie nie znalazło wpisu testowego pojazdu"


def test_listy_pochodne_kosza_sa_podzbiorem_tabel_potomnych(baza):
    assert set(db.KOSZ_TABELE_SYNCHRONIZOWANE) <= set(db.KOSZ_TABELE_POTOMNE)
    assert set(db.KOSZ_TABELE_LICZONE) <= set(db.KOSZ_TABELE_POTOMNE)
    # Nagrobek da się wystawić tylko dla tabeli, która w ogóle ma zdalny odpowiednik.
    assert set(db.KOSZ_TABELE_SYNCHRONIZOWANE) == set(TABELE_SYNC), (
        "lista tabel z nagrobkiem rozjechała się z KONFIGURACJA_SYNC"
    )


# ------------------------------------------------- załączniki i notatki


def test_kolumny_ze_sciezkami_istnieja(baza):
    for tabela, kolumna in db.KOLUMNY_ZE_SCIEZKAMI:
        assert tabela in wszystkie_tabele(), f"{tabela} nie istnieje"
        assert kolumna in kolumny_tabeli(tabela), f"{tabela}.{kolumna} nie istnieje"


def test_tabele_z_zalacznikiem_maja_kolumne_zalacznik(baza):
    for tabela in db.TABELE_Z_ZALACZNIKIEM:
        assert "zalacznik" in kolumny_tabeli(tabela), f"{tabela} nie ma kolumny zalacznik"
        assert tabela in db.KOSZ_TABELE_POTOMNE, f"{tabela} ma załącznik, ale kosz jej nie zabiera — plik zostanie sierotą"


def test_pola_notatki_istnieja(baza):
    for tabela, kolumna in db.POLA_NOTATKI.items():
        assert kolumna in kolumny_tabeli(tabela), f"{tabela}.{kolumna} nie istnieje"


def test_notatki_z_podpisem_maja_autora_i_date(baza):
    for tabela in db.TABELE_NOTATKI_Z_PODPISEM:
        istniejace = kolumny_tabeli(tabela)
        assert db.POLA_NOTATKI[tabela] == "notatka", f"{tabela}: podpis dotyczy wyłącznie kolumny `notatka`"
        assert {"notatka_autor", "notatka_data"} <= istniejace, f"{tabela} nie ma podpisu notatki"


def test_kolumny_terminow_dokumentow_istnieja(baza):
    istniejace = kolumny_tabeli("samochody")
    for _, kolumna, _ in db.TERMINY_DOKUMENTOW:
        assert kolumna in istniejace, f"samochody.{kolumna} nie istnieje"
