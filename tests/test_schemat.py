"""Listy w kodzie kontra rzeczywisty schemat bazy.

KONFIGURACJA_SYNC, KOLUMNY_POJAZDU, KOSZ_TABELE_* i KOLUMNY_ZE_SCIEZKAMI opisują
ten sam model danych z czterech stron. Każda zmiana schematu dotyka ich wszystkich
naraz, a pominięcie nie wywala aplikacji — po prostu coś po cichu nie jedzie do
chmury albo nie wraca z kosza. Dokładnie ten rodzaj kontroli, który maszyna robi
lepiej niż człowiek po każdej migracji.

Testy czytają PRAGMA z prawdziwej, zmigrowanej bazy — nie z kopii schematu
przepisanej do testu, bo taka kopia rozjeżdża się przy pierwszej migracji.

Plik ma dwie części. Pierwsza sprawdza, czy lista w kodzie nie wskazuje na
kolumnę, której nie ma — kierunek łatwiejszy, bo usunięta kolumna wywala
zapytanie od razu. Druga (na dole) sprawdza kierunek ODWROTNY: czy każda
kolumna w bazie jest przez kod rozstrzygnięta. To ten kierunek psuje się po
cichu.
"""

import sqlite3

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



# ============================================================================
#  KIERUNEK ODWROTNY: schemat -> kod
# ============================================================================
# Testy powyżej pilnują, żeby lista w kodzie nie wskazywała na kolumnę, której
# nie ma. To jest kierunek ŁATWIEJSZY i mniej groźny: usunięta kolumna wywala
# zapytanie od razu.
#
# Groźny jest kierunek odwrotny. Dopisujesz migracją kolumnę, zapominasz dopisać
# ją do listy — i nic się nie dzieje. Aplikacja działa, testy są zielone, a dane
# po prostu nie jadą do chmury. Wychodzi to dopiero wtedy, gdy druga osoba pyta,
# czemu u niej tego nie ma; czyli tygodnie później i bez wskazania winowajcy.
#
# Poniższe zbiory są zamkiem tego kierunku: każda kolumna spoza listy musi być
# wpisana tutaj ŚWIADOMIE, z powodem. `test_wyjatki_nie_gnija` pilnuje, żeby
# wpis, który przestał być potrzebny, nie został tu na zawsze.


# Kolumny księgowe każdej synchronizowanej tabeli — klucz własny, powiązanie
# z pojazdem i para znaczników wysyłki. Nigdy nie są DANYMI.
KOLUMNY_TECHNICZNE_SYNC = {"id", "auto_id", "zdalne_id", "zdalny_hash"}


POZA_SYNC_SWIADOMIE = {
    # Zdjęcia nadal nie jadą do chmury (pomysł N-06, dług zapisany wprost
    # w notatce o współdzieleniu). Kolumna `zalacznik` niesie ścieżkę do pliku,
    # który istnieje wyłącznie na tym urządzeniu — wysłanie samej ścieżki dałoby
    # drugiej osobie odsyłacz donikąd.
    ("tankowania", "zalacznik"),
    ("wizyty", "zalacznik"),
    ("historia", "zalacznik"),
    ("magazyn_czesci", "zalacznik"),
    ("zestawy_opon", "zalacznik"),
    ("inne_koszty", "zalacznik"),
    # WYLICZANE, nie wpisywane: `aktualizuj_najnowszy_wpis` przepisuje tu datę
    # i przebieg najnowszego wpisu z `historia`, a synchronizacja woła
    # `przelicz_wszystkie_zadania` po KAŻDYM pobraniu. Wysyłanie ich znaczyłoby
    # wysyłanie tego samego dwa razy — i produkowanie konfliktów tam, gdzie
    # źródło prawdy (`historia`) i tak przyjeżdża komplet.
    ("zadania", "data"),
    ("zadania", "przebieg"),
}


# Kolumny `samochody`, które opisują WSPÓŁDZIELENIE, a nie pojazd. Z definicji
# lokalne: to one prowadzą rozmowę z chmurą, więc nie mogą w niej jechać.
KOLUMNY_KSIEGOWE_POJAZDU = {
    "id", "wspolny_pojazd_id", "kod_zaproszenia", "kod_wspolautora",
    "kod_podgladu", "rola_wspoldzielenia", "info_zdalne_id", "zdalny_hash_info",
    "znacznik_delty",
}


POZA_POJAZDEM_SWIADOMIE = {
    # Jak wyżej: sama ścieżka bez pliku jest dla drugiej strony bezużyteczna.
    "zdjecie_glowne",
    # DECYZJA, nie przeoczenie: kolor interfejsu przy tym aucie zostaje lokalny.
    # Argument za wysyłaniem istnieje (kolor jest cechą pojazdu, tak jak
    # nadwozie), więc gdyby kiedyś przeważył, wystarczy przenieść tę nazwę do
    # KOLUMNY_POJAZDU — test przypomni się sam.
    "kolor_motywu",
}


# Kolumna, której nazwa brzmi jak ścieżka do pliku, a nią nie jest.
POZA_SCIEZKAMI_SWIADOMIE = {
    ("kosz_pojazdy", "pliki"),           # lista nazw plików migawki, w JSON
    ("kosz_pojazdy", "rozmiar_plikow"),  # liczba bajtów
}

# Po tych cząstkach nazwy poznajemy kolumnę niosącą ścieżkę. Heurystyka, i to
# jest w porządku: jej zadaniem jest ZAPYTAĆ przy nowej kolumnie, a nie wyrokować.
CZASTKI_NAZW_SCIEZEK = ("sciezka", "zalacznik", "zdjecie", "foto", "plik", "obraz")


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

# ------------------------------------------------- kierunek odwrotny


def test_kazda_kolumna_synchronizowanej_tabeli_jest_rozstrzygnieta(baza):
    """Nowa kolumna w synchronizowanej tabeli albo jedzie, albo jest wyjątkiem.

    Trzeciej możliwości nie ma — a dziś trzecia możliwość jest domyślna i cicha."""
    nierozstrzygniete = []
    for konfig in sync.KONFIGURACJA_SYNC:
        tabela = konfig["tabela"]
        opisane = set(konfig["kolumny"]) | set(konfig.get("fk") or {}) | KOLUMNY_TECHNICZNE_SYNC
        for kolumna in kolumny_tabeli(tabela):
            if kolumna in opisane or (tabela, kolumna) in POZA_SYNC_SWIADOMIE:
                continue
            nierozstrzygniete.append(f"{tabela}.{kolumna}")

    assert nierozstrzygniete == [], (
        "kolumny, które NIE jadą do chmury i nikt tego nie zadeklarował:\n  "
        + "\n  ".join(nierozstrzygniete)
        + "\n\nDopisz je do `kolumny` w KONFIGURACJA_SYNC (sync.py) albo, jeśli mają "
        "zostać lokalne, do POZA_SYNC_SWIADOMIE w tym pliku — z powodem."
    )


def test_kazda_kolumna_samochodu_jest_rozstrzygnieta(baza):
    """To samo dla pojazdu. Pominięta kolumna znaczy: druga osoba nie zobaczy
    daty przeglądu, telefonu do assistance albo tego, że auto zostało sprzedane."""
    rozstrzygniete = set(sync.KOLUMNY_POJAZDU) | KOLUMNY_KSIEGOWE_POJAZDU | POZA_POJAZDEM_SWIADOMIE
    nierozstrzygniete = [k for k in kolumny_tabeli("samochody") if k not in rozstrzygniete]

    assert nierozstrzygniete == [], (
        "kolumny `samochody`, które nie jadą do chmury i nikt tego nie zadeklarował: "
        + ", ".join(nierozstrzygniete)
        + "\n\nDopisz je do KOLUMNY_POJAZDU (sync.py) albo do POZA_POJAZDEM_SWIADOMIE "
        "w tym pliku — z powodem."
    )


def test_kazda_kolumna_wygladajaca_na_sciezke_jest_rozstrzygnieta(baza):
    """Kolumna ze ścieżką, której nie ma w KOLUMNY_ZE_SCIEZKAMI, jest niewidzialna
    dla `napraw_sciezki_zalacznikow` — czyli po przeniesieniu kopii na inne
    urządzenie wskazuje w pustkę i nikt tego nie naprawi."""
    znane = set(db.KOLUMNY_ZE_SCIEZKAMI)
    nierozstrzygniete = []
    for tabela in sorted(wszystkie_tabele()):
        for kolumna in kolumny_tabeli(tabela):
            if not any(czastka in kolumna.lower() for czastka in CZASTKI_NAZW_SCIEZEK):
                continue
            if (tabela, kolumna) in znane or (tabela, kolumna) in POZA_SCIEZKAMI_SWIADOMIE:
                continue
            nierozstrzygniete.append(f"{tabela}.{kolumna}")

    assert nierozstrzygniete == [], (
        "kolumny wyglądające na ścieżkę pliku, o których nie wie naprawa ścieżek: "
        + ", ".join(nierozstrzygniete)
        + "\n\nDopisz je do KOLUMNY_ZE_SCIEZKAMI (db/stale.py) albo, jeśli mimo nazwy "
        "nie niosą ścieżki, do POZA_SCIEZKAMI_SWIADOMIE w tym pliku."
    )


def test_wyjatki_nie_gnija(baza):
    """Wyjątek, który przestał być potrzebny, jest gorszy od braku wyjątku:
    wygląda jak decyzja, a jest śmieciem po zmianie sprzed pół roku.

    Sprawdzamy dwie rzeczy naraz — czy wskazywana kolumna jeszcze istnieje
    i czy nadal jest poza listą, do której wyjątek się odnosi."""
    bledy = []

    opisane_w_sync = {
        k["tabela"]: set(k["kolumny"]) | set(k.get("fk") or {})
        for k in sync.KONFIGURACJA_SYNC
    }
    for tabela, kolumna in sorted(POZA_SYNC_SWIADOMIE):
        if tabela not in opisane_w_sync:
            bledy.append(f"POZA_SYNC_SWIADOMIE: {tabela} nie jest już synchronizowana")
        elif kolumna not in kolumny_tabeli(tabela):
            bledy.append(f"POZA_SYNC_SWIADOMIE: {tabela}.{kolumna} nie istnieje w bazie")
        elif kolumna in opisane_w_sync[tabela]:
            bledy.append(f"POZA_SYNC_SWIADOMIE: {tabela}.{kolumna} JEDZIE już do chmury")

    kolumny_samochodow = kolumny_tabeli("samochody")
    for kolumna in sorted(POZA_POJAZDEM_SWIADOMIE | KOLUMNY_KSIEGOWE_POJAZDU):
        if kolumna not in kolumny_samochodow:
            bledy.append(f"wyjątki pojazdu: samochody.{kolumna} nie istnieje w bazie")
        elif kolumna in sync.KOLUMNY_POJAZDU:
            bledy.append(f"wyjątki pojazdu: samochody.{kolumna} JEDZIE już do chmury")

    for tabela, kolumna in sorted(POZA_SCIEZKAMI_SWIADOMIE):
        if tabela not in wszystkie_tabele() or kolumna not in kolumny_tabeli(tabela):
            bledy.append(f"POZA_SCIEZKAMI_SWIADOMIE: {tabela}.{kolumna} nie istnieje w bazie")
        elif (tabela, kolumna) in set(db.KOLUMNY_ZE_SCIEZKAMI):
            bledy.append(f"POZA_SCIEZKAMI_SWIADOMIE: {tabela}.{kolumna} jest już w KOLUMNY_ZE_SCIEZKAMI")

    for tabela in sorted(POZA_KOSZEM_SWIADOMIE):
        if tabela not in wszystkie_tabele():
            bledy.append(f"POZA_KOSZEM_SWIADOMIE: {tabela} nie istnieje w bazie")
        elif tabela in db.KOSZ_TABELE_POTOMNE:
            bledy.append(f"POZA_KOSZEM_SWIADOMIE: {tabela} jest już zabierana do kosza")

    assert bledy == [], "nieaktualne wpisy na listach świadomych wyjątków:\n  " + "\n  ".join(bledy)
