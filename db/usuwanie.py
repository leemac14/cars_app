"""Usuwanie z możliwością cofnięcia (wpisy, zadania, zdjęcia)."""

import os
import shutil
import sqlite3
import uuid

from .stale import OSIE_MONTAZU, TABELE_Z_ZALACZNIKIEM
from .polaczenie import polacz_baze
from .synchronizacja import czy_moge_zmieniac_rekord, usun_nagrobek, zarejestruj_nagrobek
from .zalaczniki import _upewnij_folder_odroczonych, usun_plik_zalacznika
from .magazyn import _przywroc_powiazania_czesci_wpisow, _zdejmij_powiazania_czesci_wpisow


def aktualizuj_wiele_zdjec_karoserii(ids_list, strefa=None, typ_porownania=None, opis=None):
    """Masowa edycja wspólnych pól (strefa / typ zdjęcia / opis) dla wielu zdjęć
    karoserii naraz — używane przez zbiorczą edycję zaznaczonych zdjęć w galerii.
    Pole pozostawione jako None NIE jest zmieniane (stąd pusty opis trzeba
    przekazać jako pusty string, jeśli faktycznie ma zostać wyczyszczony)."""
    if not ids_list:
        return 0

    przypisania, wartosci = [], []
    if strefa is not None:
        przypisania.append("strefa=?")
        wartosci.append(strefa)
    if typ_porownania is not None:
        przypisania.append("typ_porownania=?")
        wartosci.append(typ_porownania)
    if opis is not None:
        przypisania.append("opis=?")
        wartosci.append(opis)

    if not przypisania:
        return 0

    placeholders = ",".join("?" for _ in ids_list)
    with polacz_baze() as conn:
        conn.execute(
            f"UPDATE zdjecia_karoserii SET {', '.join(przypisania)} WHERE id IN ({placeholders})",
            tuple(wartosci) + tuple(ids_list)
        )
    return len(ids_list)


def oznacz_zamontowany_zestaw(auto_id, zestaw_id, os_montazu="Wszystkie"):
    """Montuje zestaw opon na wskazanej osi. Zestaw montowany na całym aucie
    ('Wszystkie') wyklucza wszystkie pozostałe. Zestaw montowany na pojedynczej
    osi koliduje TYLKO z innym zestawem zajmującym tę samą oś (albo z zestawem
    'Wszystkie') — dzięki temu można mieć osobny, asymetryczny komplet
    jednocześnie z przodu i z tyłu."""
    if os_montazu not in OSIE_MONTAZU:
        os_montazu = "Wszystkie"

    with polacz_baze() as conn:
        if os_montazu == "Wszystkie":
            conn.execute("UPDATE zestawy_opon SET zamontowane=0, os_montazu='Wszystkie' WHERE auto_id=?", (auto_id,))
        else:
            conn.execute(
                "UPDATE zestawy_opon SET zamontowane=0 WHERE auto_id=? AND (os_montazu=? OR os_montazu='Wszystkie')",
                (auto_id, os_montazu)
            )
        conn.execute("UPDATE zestawy_opon SET zamontowane=1, os_montazu=? WHERE id=?", (os_montazu, zestaw_id))


def _auto_wiersza(tabela, dane):
    """Do którego pojazdu należy usuwany wiersz. Większość tabel ma auto_id
    wprost; historia serwisowa wisi pod podzespołem i trzeba ją dojechać
    JOIN-em."""
    if dane.get("auto_id"):
        return dane["auto_id"]
    if tabela == "historia" and dane.get("zadanie_id"):
        with polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT auto_id FROM zadania WHERE id=?", (dane["zadanie_id"],))
            w = c.fetchone()
        return w[0] if w else None
    return None


def _wolno_usunac(tabela, dane):
    """Ostatnia bramka przed skasowaniem czegokolwiek. Usuwanie z list omija
    router (nie zmienia trasy), więc bez tego sprawdzenia gość z rolą „tylko
    podgląd” mógłby wyczyścić cudzą historię u siebie — a nagrobki poszłyby
    do chmury i wyczyściłyby ją wszystkim."""
    auto_id = _auto_wiersza(tabela, dane)
    if not auto_id:
        return True  # wiersz bez pojazdu (np. dane globalne) — rola go nie dotyczy
    try:
        return czy_moge_zmieniac_rekord(auto_id, tabela, dane.get("dodane_przez"))
    except Exception:
        return True


def usun_z_cofnieciem(tabela, rekord_id):
    """Usuwa pojedynczy rekord i zwraca callback cofnij() przywracający go z tymi
    samymi wartościami (i tym samym id, o ile nic go w międzyczasie nie zajęło).
    Dla tabel z załącznikiem plik NIE jest fizycznie kasowany od razu — zostaje
    przeniesiony do folderu tymczasowego i wraca na miejsce przy cofnięciu, albo
    zostaje skasowany dopiero wywołaniem usun_odroczony_zalacznik()."""
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(f"PRAGMA table_info({tabela})")
        kolumny = [r["name"] for r in c.fetchall()]

        c.execute(f"SELECT * FROM {tabela} WHERE id=?", (rekord_id,))
        wiersz = c.fetchone()
        if not wiersz:
            return None
        dane = {k: wiersz[k] for k in kolumny}

    if not _wolno_usunac(tabela, dane):
        return None

    zdalny_id_usuniety = dane.get("zdalne_id")

    sciezka_tymczasowa = None
    if tabela in TABELE_Z_ZALACZNIKIEM:
        oryginalna = dane.get("zalacznik")
        if oryginalna and os.path.exists(oryginalna):
            folder_tmp = _upewnij_folder_odroczonych()
            sciezka_tymczasowa = os.path.join(folder_tmp, os.path.basename(oryginalna))
            try:
                shutil.move(oryginalna, sciezka_tymczasowa)
            except Exception:
                sciezka_tymczasowa = None

    # Wpis serwisowy może mieć podpięte części z magazynu — oddajemy je na stan,
    # zanim CASCADE skasuje powiązania (patrz _zdejmij_powiazania_czesci_wpisow).
    czesci_wpisu = _zdejmij_powiazania_czesci_wpisow([rekord_id]) if tabela == "historia" else []

    with polacz_baze() as conn:
        conn.execute(f"DELETE FROM {tabela} WHERE id=?", (rekord_id,))

    # Nagrobek dostaje przypisanie do pojazdu (patrz db/synchronizacja), żeby
    # usunięcie z auta A nie próbowało się wysłać przy synchronizacji auta B —
    # a przy pojeździe „tylko do podglądu” nie wysłało się w ogóle. Tabele bez
    # własnego auto_id (historia) zostają z NULL-em i zachowują się jak dotąd.
    auto_nagrobka = dane.get("auto_id")
    if zdalny_id_usuniety:
        zarejestruj_nagrobek(tabela, zdalny_id_usuniety, auto_nagrobka)
    for w in czesci_wpisu:
        if w.get("zdalne_id"):
            zarejestruj_nagrobek("historia_czesci_magazynu", w["zdalne_id"], auto_nagrobka)

    stan = {"cofniete": False, "trwale_usuniete": False}

    def cofnij():
        if stan["cofniete"] or stan["trwale_usuniete"]:
            return
        stan["cofniete"] = True

        if zdalny_id_usuniety:
            usun_nagrobek(zdalny_id_usuniety)
        for w in czesci_wpisu:
            if w.get("zdalne_id"):
                usun_nagrobek(w["zdalne_id"])

        if sciezka_tymczasowa and os.path.exists(sciezka_tymczasowa):
            try:
                shutil.move(sciezka_tymczasowa, dane["zalacznik"])
            except Exception:
                pass

        kolumny_bez_id = [k for k in kolumny if k != "id"]
        wartosci = tuple(dane[k] for k in kolumny_bez_id)
        placeholders = ",".join("?" for _ in kolumny_bez_id)
        nazwy = ",".join(kolumny_bez_id)

        with polacz_baze() as conn:
            kursor = conn.cursor()
            kursor.execute(f"INSERT INTO {tabela} ({nazwy}) VALUES ({placeholders})", wartosci)
            nowe_id = kursor.lastrowid
        _przywroc_powiazania_czesci_wpisow(czesci_wpisu, {rekord_id: nowe_id})

    def finalizuj_usuniecie():
        """Wywołać po upłynięciu okna na cofnięcie — kasuje fizycznie odłożony plik."""
        if stan["cofniete"]:
            return
        stan["trwale_usuniete"] = True
        if sciezka_tymczasowa:
            usun_plik_zalacznika(sciezka_tymczasowa)

    return {"cofnij": cofnij, "finalizuj": finalizuj_usuniecie, "dane": dane}


def usun_wiele_z_cofnieciem(tabela, ids_list):
    """Grupowe usuwanie z możliwością cofnięcia. Zwraca callback cofnij() i finalizuj()."""
    if not ids_list:
        return None

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(f"PRAGMA table_info({tabela})")
        kolumny = [r["name"] for r in c.fetchall()]

        placeholders = ",".join("?" for _ in ids_list)
        c.execute(f"SELECT * FROM {tabela} WHERE id IN ({placeholders})", tuple(ids_list))
        wiersze = c.fetchall()

        if not wiersze:
            return None
        dane_lista = [{k: w[k] for k in kolumny} for w in wiersze]

    # Przy roli współautora zaznaczenie grupowe może obejmować i moje, i cudze
    # wpisy. Nie odrzucamy wtedy całej operacji — kasujemy to, do czego mam
    # prawo, i zostawiamy resztę. Odrzucone wracają w wyniku, żeby interfejs
    # mógł powiedzieć, ile i dlaczego pominięto.
    dozwolone = [d for d in dane_lista if _wolno_usunac(tabela, d)]
    ile_pominietych = len(dane_lista) - len(dozwolone)
    if ile_pominietych:
        if not dozwolone:
            return None
        dane_lista = dozwolone
        # Listę identyfikatorów odbudowujemy z wierszy, a nie filtrujemy
        # wejściową: te przychodzą z interfejsu i bywają tekstem, a tu muszą
        # trafić w kolumnę id jako liczby.
        ids_list = [d["id"] for d in dane_lista]
        placeholders = ",".join("?" for _ in ids_list)

    zdalne_id_usuniete = [d.get("zdalne_id") for d in dane_lista if d.get("zdalne_id")]

    sciezki_tymczasowe = []
    if tabela in TABELE_Z_ZALACZNIKIEM:
        folder_tmp = _upewnij_folder_odroczonych()
        for dane in dane_lista:
            oryginalna = dane.get("zalacznik")
            if oryginalna and os.path.exists(oryginalna):
                # Unikalny prefiks, by pliki o tej samej nazwie się nie nadpisały przy usuwaniu wielu
                sciezka_tmp = os.path.join(folder_tmp, f"bulk_{uuid.uuid4().hex}_{os.path.basename(oryginalna)}")
                try:
                    shutil.move(oryginalna, sciezka_tmp)
                    sciezki_tymczasowe.append((sciezka_tmp, oryginalna))
                except Exception:
                    pass

    # Jak przy usuwaniu pojedynczego wpisu — części wracają na stan magazynu,
    # zamiast zniknąć cicho razem z powiązaniem skasowanym przez CASCADE.
    czesci_wpisow = _zdejmij_powiazania_czesci_wpisow(ids_list) if tabela == "historia" else []

    with polacz_baze() as conn:
        conn.execute(f"DELETE FROM {tabela} WHERE id IN ({placeholders})", tuple(ids_list))

    for zid in zdalne_id_usuniete:
        zarejestruj_nagrobek(tabela, zid)
    for w in czesci_wpisow:
        if w.get("zdalne_id"):
            zarejestruj_nagrobek("historia_czesci_magazynu", w["zdalne_id"])

    stan = {"cofniete": False, "trwale_usuniete": False}

    def cofnij():
        if stan["cofniete"] or stan["trwale_usuniete"]:
            return
        stan["cofniete"] = True

        for zid in zdalne_id_usuniete:
            usun_nagrobek(zid)
        for w in czesci_wpisow:
            if w.get("zdalne_id"):
                usun_nagrobek(w["zdalne_id"])

        for tmp, oryg in sciezki_tymczasowe:
            if os.path.exists(tmp):
                try:
                    shutil.move(tmp, oryg)
                except Exception:
                    pass

        kolumny_bez_id = [k for k in kolumny if k != "id"]
        placeholders_ins = ",".join("?" for _ in kolumny_bez_id)
        nazwy = ",".join(kolumny_bez_id)

        mapa_id = {}
        with polacz_baze() as conn:
            kursor = conn.cursor()
            for dane in dane_lista:
                wartosci = tuple(dane[k] for k in kolumny_bez_id)
                kursor.execute(f"INSERT INTO {tabela} ({nazwy}) VALUES ({placeholders_ins})", wartosci)
                if dane.get("id") is not None:
                    mapa_id[dane["id"]] = kursor.lastrowid
        _przywroc_powiazania_czesci_wpisow(czesci_wpisow, mapa_id)

    def finalizuj_usuniecie():
        if stan["cofniete"]:
            return
        stan["trwale_usuniete"] = True
        for tmp, _ in sciezki_tymczasowe:
            usun_plik_zalacznika(tmp)

    return {"cofnij": cofnij, "finalizuj": finalizuj_usuniecie, "pominiete": ile_pominietych}


def przelacz_wykonane_do_zrobienia(pozycja_id, status):
    with polacz_baze() as conn:
        conn.execute("UPDATE do_zrobienia SET wykonane=? WHERE id=?", (1 if status else 0, pozycja_id))


def usun_zadanie_z_cofnieciem(zadanie_id):
    """Usuwa podzespół (zadanie) wraz z całą jego kaskadową historią,
    załącznikami i powiązaniami z opcją pełnego cofnięcia."""
    if not zadanie_id:
        return None

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # 1. Pobieramy dane usuwanego zadania
        c.execute("PRAGMA table_info(zadania)")
        kol_z = [r["name"] for r in c.fetchall()]
        c.execute("SELECT * FROM zadania WHERE id=?", (zadanie_id,))
        w_zad = c.fetchone()
        if not w_zad:
            return None
        dane_zad = {k: w_zad[k] for k in kol_z}
        if not _wolno_usunac("zadania", dane_zad):
            return None

        # 2. Pobieramy powiązaną historię (która zniknie przez CASCADE)
        c.execute("PRAGMA table_info(historia)")
        kol_h = [r["name"] for r in c.fetchall()]
        c.execute("SELECT * FROM historia WHERE zadanie_id=?", (zadanie_id,))
        historia_dane = [{k: w[k] for k in kol_h} for w in c.fetchall()]

        # 3. Zapamiętujemy wpisy 'do_zrobienia' (klucz obcy ustawi im zadanie_id na NULL)
        c.execute("SELECT id FROM do_zrobienia WHERE zadanie_id=?", (zadanie_id,))
        do_zrobienia_ids = [r["id"] for r in c.fetchall()]

    # 4. Zabezpieczamy fizyczne pliki załączników powiązane z historią tego zadania
    sciezki_tymczasowe = []
    folder_tmp = _upewnij_folder_odroczonych()
    for d in historia_dane:
        zal = d.get("zalacznik")
        if zal and os.path.exists(zal):
            tmp = os.path.join(folder_tmp, f"h_{uuid.uuid4().hex}_{os.path.basename(zal)}")
            try:
                shutil.move(zal, tmp)
                sciezki_tymczasowe.append((tmp, zal))
            except Exception:
                pass

    # 5. Części z magazynu użyte w tych wpisach wracają na stan — CASCADE
    # skasowałby powiązania po cichu, zostawiając sztuki „zużyte” w nieistniejącym
    # już podzespole.
    czesci_wpisow = _zdejmij_powiazania_czesci_wpisow([d["id"] for d in historia_dane])

    # 6. Usunięcie zadania (SQLite CASCADE automatycznie wyczyści powiązaną historię)
    with polacz_baze() as conn:
        conn.execute("DELETE FROM zadania WHERE id=?", (zadanie_id,))

    zdalny_id_zadania = dane_zad.get("zdalne_id")
    zdalne_id_historii = [d.get("zdalne_id") for d in historia_dane if d.get("zdalne_id")]
    auto_nagrobka = dane_zad.get("auto_id")
    if zdalny_id_zadania:
        zarejestruj_nagrobek("zadania", zdalny_id_zadania, auto_nagrobka)
    for zid in zdalne_id_historii:
        zarejestruj_nagrobek("historia", zid, auto_nagrobka)
    for w in czesci_wpisow:
        if w.get("zdalne_id"):
            zarejestruj_nagrobek("historia_czesci_magazynu", w["zdalne_id"], auto_nagrobka)

    stan = {"cofniete": False, "trwale_usuniete": False}

    def cofnij():
        if stan["cofniete"] or stan["trwale_usuniete"]:
            return
        stan["cofniete"] = True

        if zdalny_id_zadania:
            usun_nagrobek(zdalny_id_zadania)
        for zid in zdalne_id_historii:
            usun_nagrobek(zid)
        for w in czesci_wpisow:
            if w.get("zdalne_id"):
                usun_nagrobek(w["zdalne_id"])

        # Przywrócenie plików na dysk
        for tmp, oryg in sciezki_tymczasowe:
            if os.path.exists(tmp):
                try:
                    shutil.move(tmp, oryg)
                except Exception:
                    pass

        # Przywrócenie rekordów w bazie danych z zachowaniem ich oryginalnych ID
        with polacz_baze() as conn:
            # 1. Przywrócenie zadania
            p_z = ",".join("?" for _ in kol_z)
            n_z = ",".join(kol_z)
            conn.execute(f"INSERT INTO zadania ({n_z}) VALUES ({p_z})", tuple(dane_zad[k] for k in kol_z))

            # 2. Przywrócenie wpisów historii
            if historia_dane:
                p_h = ",".join("?" for _ in kol_h)
                n_h = ",".join(kol_h)
                for d in historia_dane:
                    conn.execute(f"INSERT INTO historia ({n_h}) VALUES ({p_h})", tuple(d[k] for k in kol_h))

            # 3. Ponowne podpięcie ID zadania do pozycji 'do_zrobienia'
            if do_zrobienia_ids:
                placeholders = ",".join("?" for _ in do_zrobienia_ids)
                conn.execute(
                    f"UPDATE do_zrobienia SET zadanie_id=? WHERE id IN ({placeholders})",
                    (zadanie_id, *do_zrobienia_ids)
                )

        # 4. Wpisy historii wróciły z ORYGINALNYMI ID, więc powiązania z magazynem
        # wstawiamy bez przemapowania; sztuki znów schodzą ze stanu.
        _przywroc_powiazania_czesci_wpisow(czesci_wpisow)

    def finalizuj_usuniecie():
        if stan["cofniete"]:
            return
        stan["trwale_usuniete"] = True
        for tmp, _ in sciezki_tymczasowe:
            usun_plik_zalacznika(tmp)

    return {"cofnij": cofnij, "finalizuj": finalizuj_usuniecie, "dane": dane_zad}


def usun_wiele_zadan_z_cofnieciem(ids_list):
    """Bulk-owy wrapper na usun_zadanie_z_cofnieciem — każdy podzespół usuwa
    pełną, kaskadowo bezpieczną ścieżką (z historią i załącznikami), łącząc
    wyniki w jeden wspólny callback cofnij()/finalizuj()."""
    wyniki = [w for w in (usun_zadanie_z_cofnieciem(zid) for zid in ids_list) if w]
    if not wyniki:
        return None
    # None z usun_zadanie_z_cofnieciem znaczy „nie ma” albo „nie wolno” (patrz
    # _wolno_usunac) — liczbę pominiętych oddajemy dalej, żeby komunikat mówił
    # prawdę zamiast chwalić się usunięciem wszystkiego.
    ile_pominietych = len(list(ids_list)) - len(wyniki)

    stan = {"cofniete": False, "trwale_usuniete": False}

    def cofnij():
        if stan["cofniete"] or stan["trwale_usuniete"]:
            return
        stan["cofniete"] = True
        for w in wyniki:
            w["cofnij"]()

    def finalizuj_usuniecie():
        if stan["cofniete"]:
            return
        stan["trwale_usuniete"] = True
        for w in wyniki:
            w["finalizuj"]()

    return {"cofnij": cofnij, "finalizuj": finalizuj_usuniecie, "pominiete": ile_pominietych}


__all__ = [
    "aktualizuj_wiele_zdjec_karoserii",
    "oznacz_zamontowany_zestaw",
    "przelacz_wykonane_do_zrobienia",
    "usun_wiele_z_cofnieciem",
    "usun_wiele_zadan_z_cofnieciem",
    "usun_z_cofnieciem",
    "usun_zadanie_z_cofnieciem",
]
