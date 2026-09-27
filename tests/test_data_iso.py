"""Kolumna `data_iso` — sortowalna kopia daty wpisu (migracja 44, db/daty.py).

`data` zostaje w formacie DD.MM.RRRR, a obok leży `data_iso` (RRRR-MM-DD), na
której SQLite umie sortować i ciąć zakresem. Pięć rzeczy psuje się tu osobno:

1. **Przeliczenie** — `na_iso` to logika `parsuj_date`: czego lista nie umie
   odczytać, nie ma też daty sortowalnej. `parsuj_date` działa jak dawniej.
2. **Audyt zapisu** — każdy jawny INSERT i UPDATE kolumny `data` w kodzie
   aplikacji pisze też `data_iso`. Wyzwalacze SQLite zrobiłyby to w jednym
   miejscu, ale spowalniały każde połączenie (db/daty.py) — pilnuje ten test.
3. **Ścieżki zapisu** — formularze, funkcje `db`, import CSV, rekord z chmury,
   przywrócenie z chmury, kosz z migawką sprzed wersji 44, cofnięcie usunięcia.
4. **Migracja 44** — wypełnia kolumnę wstecz z każdego formatu, który czyta lista.
5. **Odczyty** — eksport tnie i sortuje w SQL tak jak dawny filtr w Pythonie,
   a dwa miejsca, które sortowały DD.MM.RRRR jako tekst, idą chronologicznie.
"""

import ast
import json
import re
import sqlite3
import types
from collections import Counter
from datetime import date, datetime, timedelta

import pytest

import audyty
import db
import pomoce
import probki_baz
import sync
from date import na_iso, parsuj_date
from sync import pobieranie as sync_pobieranie
from sync import przywracanie as sync_przywracanie


# (tekst w kolumnie `data`, oczekiwana `data_iso`)
PRZYPADKI = [
    ("05.03.2024", "2024-03-05"),
    ("5.3.2024", "2024-03-05"),
    (" 05.03.2024\n", "2024-03-05"),
    ("2024-03-05", "2024-03-05"),
    ("2024.3.5", "2024-03-05"),
    ("05-03-2024", "2024-03-05"),
    ("05/03/2024", "2024-03-05"),
    ("29.02.2024", "2024-02-29"),
    ("29.02.2023", None),
    ("31.04.2024", None),
    ("2024/03/05", None),
    ("05.03.24", None),
    ("05.03.2024 12:30", None),
    ("brak", None),
    ("", None),
]


def niezgodne_daty_iso():
    """Wiersze, w których `data_iso` nie jest tym, co `na_iso` liczy z `data`."""
    zle = []
    with db.polacz_baze() as conn:
        for tabela in db.TABELE_Z_DATA_ISO:
            for id_, data, iso in conn.execute(f"SELECT id, data, data_iso FROM {tabela}").fetchall():
                if iso != na_iso(data):
                    zle.append((tabela, id_, data, iso))
    return zle


def data_iso_wiersza(tabela, rekord_id):
    with db.polacz_baze() as conn:
        return conn.execute(f"SELECT data, data_iso FROM {tabela} WHERE id=?", (rekord_id,)).fetchone()


# ------------------------------------------------------------ 1. przeliczenie


@pytest.mark.parametrize("tekst, oczekiwana", PRZYPADKI + [(None, None)])
def test_na_iso_czyta_to_samo_co_parsuj_date(tekst, oczekiwana):
    assert na_iso(tekst) == oczekiwana
    assert parsuj_date(tekst) == (date.fromisoformat(oczekiwana) if oczekiwana else datetime.min.date())


def test_tekst_iso_sortuje_sie_jak_daty():
    """Cały sens kolumny: porządek napisów RRRR-MM-DD to porządek dat — przez
    granice miesięcy i lat, gdzie DD.MM.RRRR jako tekst się rozjeżdża."""
    daty = ["31.12.2025", "01.01.2026", "15.01.2025", "02.02.2026", "09.10.2025"]
    assert sorted(daty) != sorted(daty, key=parsuj_date)
    assert sorted(daty, key=na_iso) == sorted(daty, key=parsuj_date)


# ------------------------------------------------------------ 2. audyt zapisu


INSERT = re.compile(r"\bINSERT\s+(?:OR\s+\w+\s+)?INTO\s+(\w+)\s*\(([^)]*)\)(?:\s*VALUES\s*\(([^)]*)\))?", re.I)
UPDATE = re.compile(r"\bUPDATE\s+(\w+)\s+SET\s+(.*?)(?:\bWHERE\b|$)", re.I | re.S)
PRZYPISANIE_DATY = re.compile(r"(?<![\w.])data\s*=")
PRZYPISANIE_DATY_ISO = re.compile(r"(?<![\w.])data_iso\s*=")


def _napisy(drzewo):
    """(wiersz, tekst) każdego napisu w pliku. Wstawka f-stringu to `{}` —
    tabela podana zmienną nie pasuje do wzorca i świadomie wypada: takie zapisy
    (chmura, kosz, cofanie) sprawdzają testy ścieżek niżej."""
    kawalki_fstringow = {id(c) for w in ast.walk(drzewo) if isinstance(w, ast.JoinedStr) for c in w.values}
    for wezel in ast.walk(drzewo):
        if isinstance(wezel, ast.Constant) and isinstance(wezel.value, str) and id(wezel) not in kawalki_fstringow:
            yield wezel.lineno, wezel.value
        elif isinstance(wezel, ast.JoinedStr):
            yield wezel.lineno, "".join(c.value if isinstance(c, ast.Constant) else "{}" for c in wezel.values)


def zapisy_daty_bez_iso(zrodlo, nazwa="<kod>"):
    """Jawne INSERT/UPDATE kolumny `data` w tabeli z `data_iso`, które nie
    piszą `data_iso` — albo piszą ją, ale z inną liczbą wartości niż kolumn."""
    bledy = []
    for nr, tekst in _napisy(ast.parse(zrodlo)):
        for m in INSERT.finditer(tekst):
            kolumny = [k.strip() for k in m.group(2).split(",")]
            if m.group(1) not in db.TABELE_Z_DATA_ISO or "data" not in kolumny:
                continue
            if "data_iso" not in kolumny:
                bledy.append(f"{nazwa}:{nr} INSERT INTO {m.group(1)} bez data_iso")
            elif m.group(3) is not None and len(m.group(3).split(",")) != len(kolumny):
                bledy.append(f"{nazwa}:{nr} INSERT INTO {m.group(1)}: liczba wartości inna niż kolumn")
        for m in UPDATE.finditer(tekst):
            if (m.group(1) in db.TABELE_Z_DATA_ISO and PRZYPISANIE_DATY.search(m.group(2))
                    and not PRZYPISANIE_DATY_ISO.search(m.group(2))):
                bledy.append(f"{nazwa}:{nr} UPDATE {m.group(1)} zmienia data bez data_iso")
    return bledy


def test_kazdy_zapis_daty_w_kodzie_pisze_tez_data_iso():
    bledy = []
    for plik in audyty._pliki_projektu():
        nazwa = plik.relative_to(audyty.KORZEN_PROJEKTU).as_posix()
        bledy += zapisy_daty_bez_iso(plik.read_text(encoding="utf-8"), nazwa)
    assert bledy == [], (
        "zapis daty bez `data_iso` — lista i eksport rozjadą się na tym wpisie:\n"
        + "\n".join(bledy)
        + "\n\nDopisz kolumnę `data_iso` z wartością `na_iso(<ta sama data>)` (from date import na_iso)."
    )


def test_audyt_zapisu_daty_lapie_brak_i_przepuszcza_poprawne():
    zle = (
        'c.execute("INSERT INTO tankowania (auto_id, data, kwota) VALUES (?,?,?)")\n'
        'c.execute("UPDATE historia SET data=?, cena=? WHERE id=?")\n'
        'c.execute(f"INSERT INTO wizyty (auto_id, data, data_iso) VALUES (?,?)")\n'
    )
    assert len(zapisy_daty_bez_iso(zle)) == 3

    dobre = (
        'c.execute("INSERT INTO tankowania (auto_id, data, data_iso, kwota) VALUES (?,?,?,?)")\n'
        'c.execute("UPDATE historia SET data=?, data_iso=?, cena=? WHERE id=?")\n'
        'c.execute("UPDATE tankowania SET kwota=?, data_modyfikacji=? WHERE data=?")\n'
        'c.execute("INSERT INTO warsztaty (auto_id, nazwa) VALUES (?,?)")\n'
        'c.execute(f"INSERT INTO {tabela} ({kolumny}) VALUES ({znaki})")\n'
    )
    assert zapisy_daty_bez_iso(dobre) == []


# ------------------------------------------------------------ 3. ścieżki zapisu


def _widok(nazwa, identyfikatory, auto_id):
    strona = pomoce.zbuduj_strone()
    strona.page.on_route_change = lambda e: None  # zapis wraca trasą
    stan = pomoce.stan_aplikacji(auto_id, "Daty")
    return strona, pomoce.zbuduj_widok(pomoce.klasy_widokow()[nazwa], strona, stan, identyfikatory)


# Nowa data zostawia licznik w porządku chronologicznym — inaczej formularz
# zatrzyma się na ostrzeżeniu o podejrzanym przebiegu i nic nie zapisze.
@pytest.mark.parametrize("klasa, klucz, tabela, nowa, iso", [
    ("FormularzTankowanieView", "tankowanie", "tankowania", "04.02.2026", "2026-02-04"),
    ("FormularzInneView", "inny_koszt", "inne_koszty", "04.02.2026", "2026-02-04"),
    ("FormularzWpisView", "historia", "historia", "12.01.2026", "2026-01-12"),
    ("FormularzWizytyView", "wizyta", "wizyty", "12.01.2026", "2026-01-12"),
    ("FormularzZdjecieKaroseriiView", "karoseria", "zdjecia_karoserii", "04.02.2026", "2026-02-04"),
])
def test_edycja_daty_w_formularzu_przelicza_date_iso(baza, klasa, klucz, tabela, nowa, iso):
    identyfikatory = pomoce.utworz_pojazd("Daty")
    strona, widok = _widok(klasa, identyfikatory, identyfikatory["auto_id"])
    widok.e_d.value = nowa
    widok.zapisz(None)

    assert data_iso_wiersza(tabela, identyfikatory[klucz]) == (nowa, iso)
    assert niezgodne_daty_iso() == []


def test_nowe_wpisy_z_formularzy_maja_date_iso(baza):
    identyfikatory = pomoce.utworz_pojazd("Daty")
    auto_id = identyfikatory["auto_id"]

    strona, widok = _widok("FormularzInneView", {"auto_id": auto_id}, auto_id)
    widok.e_d.value, widok.e_o.value, widok.e_kw.value = "06.02.2026", "Myjnia", "35"
    widok.zapisz(None)

    strona, widok = _widok("FormularzTankowanieView", {"auto_id": auto_id}, auto_id)
    widok.e_d.value, widok.e_p.value, widok.e_l.value, widok.e_k.value = "12.02.2026", "101300", "30", "200"
    widok.zapisz(None)

    with db.polacz_baze() as conn:
        assert conn.execute("SELECT data_iso FROM inne_koszty WHERE nazwa='Myjnia'").fetchone() == ("2026-02-06",)
        assert conn.execute("SELECT data_iso FROM tankowania WHERE przebieg=101300").fetchone() == ("2026-02-12",)
    assert niezgodne_daty_iso() == []


def test_zapisy_z_warstwy_danych_licza_date_iso(baza):
    identyfikatory = pomoce.utworz_pojazd("Daty")
    auto_id = identyfikatory["auto_id"]

    db.dodaj_odczyt_przebiegu(auto_id, 101500, "7.2.2026")
    db.aktualizuj_odczyt_przebiegu(identyfikatory["odczyt"], 101100, "11.02.2026")
    db.utworz_wizyte_z_do_zrobienia(auto_id, [identyfikatory["do_zrobienia"]])
    db.oznacz_zaplacony_wydatek_cykliczny(identyfikatory["cykliczny"], auto_id)
    db.zapisz_moje_imie("Kamil")
    db.zapisz_rozliczenie(auto_id, "12.02.2026")
    db.przelicz_wszystkie_zadania(auto_id)
    db.zaimportuj_tankowania(auto_id, [{"data": "13.02.2026", "przebieg": 101700, "dystans": 200.0, "litry": 15.0,
                                        "kwota": 100.0, "do_pelna": 1, "stacja": "BP"}])
    db.zaimportuj_inne_koszty(auto_id, [{"data": "14.02.2026", "nazwa": "Parking", "kwota": 12.0, "tagi": ""}])
    db.zaimportuj_odczyty(auto_id, [{"data": "15.02.2026", "przebieg": 101900}])

    dzis = na_iso(datetime.now().strftime("%d.%m.%Y"))
    with db.polacz_baze() as conn:
        iso = {t: {r[0] for r in conn.execute(f"SELECT data_iso FROM {t} WHERE data_iso IS NOT NULL")}
               for t in db.TABELE_Z_DATA_ISO if t != "historia"}
        iso["historia"] = {r[0] for r in conn.execute("SELECT data_iso FROM historia WHERE data_iso IS NOT NULL")}
        iso_zadan = {r[0] for r in conn.execute("SELECT data_iso FROM zadania WHERE auto_id=?", (auto_id,))}
    assert {"2026-02-07", "2026-02-11", "2026-02-15"} <= iso["odczyty_przebiegu"]
    assert "2026-02-13" in iso["tankowania"]
    assert {dzis, "2026-02-14"} <= iso["inne_koszty"]
    assert dzis in iso["wizyty"] and dzis in iso["historia"]
    assert "2026-02-12" in iso["rozliczenia"]
    assert iso_zadan - {None}, "podzespół z historią ma datę ostatniej wymiany"
    assert niezgodne_daty_iso() == []


KONFIG_TANKOWAN = next(k for k in sync.KONFIGURACJA_SYNC if k["tabela"] == "tankowania")


def _znane(auto_id):
    with db.polacz_baze() as conn:
        return {z: {"id": i, "hash": h} for i, z, h in conn.execute(
            "SELECT id, zdalne_id, zdalny_hash FROM tankowania WHERE auto_id=? AND zdalne_id IS NOT NULL", (auto_id,))}


def test_rekord_z_chmury_dostaje_date_iso_przy_wpisaniu_i_zmianie(baza):
    auto_id = pomoce.utworz_pojazd("Daty")["auto_id"]
    dane = {"data": "20.02.2026", "przebieg": 102000, "dystans": 300.0, "litry": 20.0, "kwota": 130.0, "do_pelna": 1}

    assert sync_pobieranie._zastosuj_rekord(KONFIG_TANKOWAN, {"id": "zdalny-9", "dane": dane}, auto_id, _znane(auto_id)) == 1
    znane = _znane(auto_id)
    assert data_iso_wiersza("tankowania", znane["zdalny-9"]["id"]) == ("20.02.2026", "2026-02-20")

    zmienione = dict(dane, data="21.02.2026")
    assert sync_pobieranie._zastosuj_rekord(KONFIG_TANKOWAN, {"id": "zdalny-9", "dane": zmienione}, auto_id, znane) == 1
    assert data_iso_wiersza("tankowania", znane["zdalny-9"]["id"]) == ("21.02.2026", "2026-02-21")
    assert niezgodne_daty_iso() == []


def test_przywrocenie_z_chmury_liczy_date_iso(baza):
    auto_id = pomoce.utworz_pojazd("Daty")["auto_id"]
    rekordy = [{"id": "zdalny-7", "usuniete": False,
                "dane": {"data": "22.02.2026", "przebieg": 102500, "dystans": 0, "litry": 10.0, "kwota": 70.0}}]

    class Zapytanie:
        def select(self, *_):
            return self

        def eq(self, *_):
            return self

        def execute(self):
            return types.SimpleNamespace(data=rekordy)

    klient = types.SimpleNamespace(table=lambda _nazwa: Zapytanie())
    assert sync_przywracanie._przywroc_tabele(klient, "wspolny-1", auto_id, KONFIG_TANKOWAN) == 1
    with db.polacz_baze() as conn:
        assert conn.execute("SELECT data_iso FROM tankowania WHERE zdalne_id='zdalny-7'").fetchone() == ("2026-02-22",)


def test_kosz_z_migawka_sprzed_wersji_44_przywraca_wpisy_z_data_iso(baza):
    """Migawka zrobiona starszą aplikacją nie zna kolumny — po przywróceniu
    wpisy nie mogą zostać bez daty sortowalnej, bo zniknęłyby z każdego zakresu."""
    pomoce.utworz_pojazd("Daty")
    kosz_id = db.usun_auto_do_kosza(1)["kosz_id"]
    with db.polacz_baze() as conn:
        migawka = json.loads(conn.execute("SELECT migawka FROM kosz_pojazdy WHERE id=?", (kosz_id,)).fetchone()[0])
        ze_starej_wersji = set()
        for tabela, opis in migawka["tabele"].items():
            if "data_iso" in opis["kolumny"]:
                opis["kolumny"].remove("data_iso")
                ze_starej_wersji.add(tabela)
            for wiersz in opis["wiersze"]:
                wiersz.pop("data_iso", None)
        conn.execute("UPDATE kosz_pojazdy SET migawka=? WHERE id=?", (json.dumps(migawka), kosz_id))
    assert ze_starej_wersji == set(db.TABELE_Z_DATA_ISO), "migawka miała nieść data_iso każdej tabeli"

    assert db.przywroc_auto_z_kosza(kosz_id) == 1
    with db.polacz_baze() as conn:
        for tabela in db.TABELE_Z_DATA_ISO:
            bez = conn.execute(f"SELECT COUNT(*) FROM {tabela} WHERE data IS NOT NULL AND data_iso IS NULL").fetchone()[0]
            assert bez == 0, f"{tabela}: wpis z datą wrócił bez data_iso"
    assert niezgodne_daty_iso() == []


def test_cofniecie_usuniecia_wraca_z_ta_sama_data_iso(baza):
    identyfikatory = pomoce.utworz_pojazd("Daty")
    przed = data_iso_wiersza("tankowania", identyfikatory["tankowanie"])
    wynik = db.usun_z_cofnieciem("tankowania", identyfikatory["tankowanie"])
    wynik["cofnij"]()
    with db.polacz_baze() as conn:
        assert conn.execute("SELECT data, data_iso FROM tankowania WHERE zdalne_id='tank-1'").fetchone() == przed
    assert niezgodne_daty_iso() == []


# ------------------------------------------------------------ 4. migracja 44


def test_migracja_44_wypelnia_date_iso_wstecz_z_kazdego_formatu(magazyn):
    probki_baz.zbuduj_baze_w_wersji(db.BAZA_DANYCH, 43, probki_baz.wczytaj_drabinke())
    conn = sqlite3.connect(db.BAZA_DANYCH)
    conn.execute("INSERT INTO samochody (id, nazwa) VALUES (1, 'Sprzed aktualizacji')")
    conn.execute("INSERT INTO zadania (id, auto_id, nazwa, data) VALUES (1, 1, 'Olej', '5.3.2024')")
    conn.execute("INSERT INTO zadania (id, auto_id, nazwa, data) VALUES (2, 1, 'Opony', NULL)")
    for i, (tekst, _) in enumerate(PRZYPADKI):
        conn.execute("INSERT INTO tankowania (auto_id, data, przebieg, litry, kwota) VALUES (1, ?, ?, 1, 1)",
                     (tekst, 1000 + i))
    conn.execute("INSERT INTO inne_koszty (auto_id, data, kategoria, kwota) VALUES (1, '01.12.2023', 'Inne', 5)")
    conn.execute("INSERT INTO wizyty (auto_id, data, przebieg) VALUES (1, '2024-01-15', 5000)")
    conn.execute("INSERT INTO historia (zadanie_id, data) VALUES (1, '15/01/2024')")
    conn.execute("INSERT INTO odczyty_przebiegu (auto_id, data, przebieg) VALUES (1, '2024.02.01', 6000)")
    conn.execute("INSERT INTO rozliczenia (auto_id, data) VALUES (1, '31.01.2024')")
    conn.execute("INSERT INTO zdjecia_karoserii (auto_id, data, strefa, zalacznik) VALUES (1, '20.12.2023', 'Przód', 'x.jpg')")
    conn.commit()
    conn.close()

    db.init_db()

    assert niezgodne_daty_iso() == []
    with db.polacz_baze() as conn:
        tankowania = conn.execute("SELECT data, data_iso FROM tankowania ORDER BY przebieg").fetchall()
        zadania = conn.execute("SELECT data_iso FROM zadania ORDER BY id").fetchall()
        pozostale = {t: conn.execute(f"SELECT data_iso FROM {t}").fetchone()[0]
                     for t in ("inne_koszty", "wizyty", "historia", "odczyty_przebiegu", "rozliczenia", "zdjecia_karoserii")}
    assert tankowania == PRZYPADKI
    assert zadania == [("2024-03-05",), (None,)]
    assert pozostale == {"inne_koszty": "2023-12-01", "wizyty": "2024-01-15", "historia": "2024-01-15",
                         "odczyty_przebiegu": "2024-02-01", "rozliczenia": "2024-01-31",
                         "zdjecia_karoserii": "2023-12-20"}


def test_indeksy_pod_zakres_dat(baza):
    """(auto_id, data_iso) — a w historii, która nie ma auto_id, (zadanie_id,
    data_iso). Bez nich zakres w SQL i tak czytałby cały pojazd."""
    schemat = pomoce.zrzut_schematu()
    for tabela in db.TABELE_Z_DATA_ISO:
        klucz = "zadanie_id" if tabela == "historia" else "auto_id"
        pola = [pola for _nazwa, _unikalny, pola in schemat[tabela]["indeksy"]]
        assert (klucz, "data_iso") in pola, f"{tabela}: brak indeksu ({klucz}, data_iso)"


# ------------------------------------------------------------ 5. odczyty


def _pojazd_z_tankowaniami(daty):
    with db.polacz_baze() as conn:
        auto_id = conn.execute("INSERT INTO samochody (nazwa) VALUES ('Zakresy')").lastrowid
        for i, tekst in enumerate(daty):
            conn.execute(
                "INSERT INTO tankowania (auto_id, data, data_iso, przebieg, litry, kwota) VALUES (?,?,?,?,?,?)",
                (auto_id, tekst, na_iso(tekst), 1000 + i, 10.0, 50.0 + i),
            )
    return auto_id


def _daty_eksportu(auto_id, od=None, do=None, kategoria="tankowania"):
    return [w[0] for w in db.pobierz_dane_eksportu(auto_id, [kategoria], od, do)[kategoria][1]]


def test_eksport_tnie_zakres_i_sortuje_chronologicznie(baza):
    auto_id = _pojazd_z_tankowaniami(["15.01.2026", "03.02.2026", "28.12.2025", "10.02.2026", "brak daty"])

    assert _daty_eksportu(auto_id) == ["brak daty", "28.12.2025", "15.01.2026", "03.02.2026", "10.02.2026"]
    assert _daty_eksportu(auto_id, date(2026, 1, 1), date(2026, 2, 3)) == ["15.01.2026", "03.02.2026"]
    assert _daty_eksportu(auto_id, od=date(2026, 2, 1)) == ["03.02.2026", "10.02.2026"]
    assert _daty_eksportu(auto_id, do=date(2025, 12, 31)) == ["28.12.2025"]

    podsumowanie = db.oblicz_podsumowanie_okresu(auto_id, date(2026, 1, 1), date(2026, 2, 3))
    assert podsumowanie["koszt_paliwo"] == pytest.approx(50.0 + 51.0)


KATEGORIE_Z_ZAKRESEM = {
    "tankowania": "SELECT data FROM tankowania WHERE auto_id=?",
    "historia": "SELECT h.data FROM historia h JOIN zadania z ON h.zadanie_id=z.id WHERE z.auto_id=? AND h.wizyta_id IS NULL",
    "wizyty": "SELECT data FROM wizyty WHERE auto_id=?",
    "inne_koszty": "SELECT data FROM inne_koszty WHERE auto_id=?",
    "odczyty_przebiegu": "SELECT data FROM odczyty_przebiegu WHERE auto_id=?",
}


@pytest.mark.parametrize("od_dni, do_dni", [(None, None), (120, None), (None, 60), (150, 40), (5, 0)])
def test_eksport_zgadza_sie_z_dawnym_filtrem_w_pythonie(baza, od_dni, do_dni):
    identyfikatory = pomoce.utworz_pojazd("Daty")
    auto_id = identyfikatory["auto_id"]
    pomoce.dosyp_dane(auto_id)
    with db.polacz_baze() as conn:
        conn.execute("INSERT INTO historia (zadanie_id, data, data_iso, cena) VALUES (?, 'nieczytelna', NULL, 5)",
                     (identyfikatory["zadanie"],))
    dzis = date.today()
    od = dzis - timedelta(days=od_dni) if od_dni is not None else None
    do = dzis - timedelta(days=do_dni) if do_dni is not None else None

    def dawny_filtr(tekst):
        if not od and not do:
            return True
        d = parsuj_date(tekst)
        return d != datetime.min.date() and not (od and d < od) and not (do and d > do)

    dane = db.pobierz_dane_eksportu(auto_id, list(KATEGORIE_Z_ZAKRESEM), od, do)
    with db.polacz_baze() as conn:
        for kategoria, zapytanie in KATEGORIE_Z_ZAKRESEM.items():
            daty = [w[0] for w in dane[kategoria][1]]
            oczekiwane = [r[0] for r in conn.execute(zapytanie, (auto_id,)) if dawny_filtr(r[0])]
            assert Counter(daty) == Counter(oczekiwane), kategoria
            assert daty == sorted(daty, key=parsuj_date), f"{kategoria}: nie chronologicznie"


def test_zdjecia_karoserii_w_paszporcie_ida_chronologicznie(baza):
    auto_id = _pojazd_z_tankowaniami([])
    with db.polacz_baze() as conn:
        for tekst in ("20.12.2025", "05.01.2026", "15.11.2025"):
            conn.execute("INSERT INTO zdjecia_karoserii (auto_id, data, data_iso, strefa, zalacznik) VALUES (?,?,?,?,?)",
                         (auto_id, tekst, na_iso(tekst), "Przód", f"{tekst}.jpg"))
    zdjecia = db.pobierz_dane_paszportu(auto_id)["zdjecia_karoserii"]
    assert [z[0] for z in zdjecia] == ["15.11.2025", "20.12.2025", "05.01.2026"]


def test_archiwum_sprzedanych_idzie_od_ostatnio_sprzedanego(baza):
    with db.polacz_baze() as conn:
        ids = [conn.execute("INSERT INTO samochody (nazwa) VALUES (?)", (n,)).lastrowid for n in ("Astra", "Bravo", "Corsa")]
    db.oznacz_pojazd_sprzedany(ids[0], data_sprzedazy="31.01.2024")
    db.oznacz_pojazd_sprzedany(ids[1], data_sprzedazy="15.06.2025")
    db.oznacz_pojazd_sprzedany(ids[2], data_sprzedazy="")
    assert [a["nazwa"] for a in db.pobierz_sprzedane_pojazdy()] == ["Bravo", "Astra", "Corsa"]
