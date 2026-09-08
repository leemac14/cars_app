"""Wizyty serwisowe i ich powiązanie z listą Do zrobienia."""

import os
import shutil
import sqlite3
import uuid
from datetime import datetime
from typing import Any

from .polaczenie import polacz_baze
from .ustawienia import pobierz_moje_imie
from .synchronizacja import usun_nagrobek, zarejestruj_nagrobek
from .zalaczniki import _upewnij_folder_odroczonych, usun_plik_zalacznika
from .magazyn import _przywroc_powiazania_czesci_wpisow, _zdejmij_powiazania_czesci_wpisow, przywroc_czesci_wizyty
from .przebieg import pobierz_aktualny_przebieg, przelicz_wszystkie_zadania
from .nazwy import klucz_nazwy


def utworz_wizyte_z_do_zrobienia(auto_id, ids_list, utworz_podzespoly=False) -> tuple[int | None, list[str], dict[str, Any] | None]:
    """Zwraca (wizyta_id, duplikaty, wynik_cofniecia). wynik_cofniecia to słownik
    {"cofnij": fn, "finalizuj": fn} analogiczny do pozostałych operacji usuwających —
    pozwala pokazać snackbar z możliwością cofnięcia całej operacji."""
    if not ids_list: return None, [], None
    dzis = datetime.now().strftime("%d.%m.%Y")
    prz = pobierz_aktualny_przebieg(auto_id) or 0
    duplikaty = []
    nowo_utworzone_zadania_ids = []

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("PRAGMA table_info(do_zrobienia)")
        kol_dz = [r["name"] for r in cur.fetchall()]

        placeholders = ",".join("?" for _ in ids_list)
        cur.execute(f"SELECT * FROM do_zrobienia WHERE id IN ({placeholders})", tuple(ids_list))
        do_zrobienia_dane = [{k: w[k] for k in kol_dz} for w in cur.fetchall()]
        pozycje = [(d["tytul"], d["szacowany_koszt"], d["zadanie_id"]) for d in do_zrobienia_dane]

        suma_kosztow = sum((p[1] or 0.0) for p in pozycje)
        tytuly = [p[0] for p in pozycje]
        notatki = "Utworzono z listy: " + ", ".join(tytuly)

        cur.execute("INSERT INTO wizyty (auto_id, data, przebieg, wykonawca, koszt_calkowity, notatki, dodane_przez) VALUES (?,?,?,?,?,?,?)",
                    (auto_id, dzis, prz, "", suma_kosztow, notatki, pobierz_moje_imie()))
        wizyta_id = cur.lastrowid

        for tytul, koszt, zadanie_id in pozycje:
            czy_opony = False
            if not zadanie_id and utworz_podzespoly:
                # Dopasowanie po klucz_nazwy, więc „Filtr oleju” z listy trafia
                # w istniejący „🛢️ filtr oleju” zamiast zakładać drugi podzespół.
                klucz_tytulu = klucz_nazwy(tytul)
                cur.execute("SELECT id, nazwa, dotyczy_opon FROM zadania WHERE auto_id=?", (auto_id,))
                istniejacy = next((r for r in cur.fetchall() if klucz_nazwy(r["nazwa"]) == klucz_tytulu), None)

                if istniejacy:
                    zadanie_id = istniejacy["id"]
                    czy_opony = bool(istniejacy["dotyczy_opon"])
                    duplikaty.append(istniejacy["nazwa"])
                else:
                    czy_opony = 1 if "opon" in tytul.lower() or "kół" in tytul.lower() else 0
                    cur.execute("INSERT INTO zadania (auto_id, nazwa, dotyczy_opon) VALUES (?,?,?)", (auto_id, tytul.strip(), czy_opony))
                    zadanie_id = cur.lastrowid
                    nowo_utworzone_zadania_ids.append(zadanie_id)
            elif zadanie_id:
                cur.execute("SELECT dotyczy_opon FROM zadania WHERE id=?", (zadanie_id,))
                w = cur.fetchone()
                if w: czy_opony = bool(w["dotyczy_opon"])

            if zadanie_id:
                kat = "Letnie" if czy_opony else None
                cur.execute("INSERT INTO historia (wizyta_id, zadanie_id, data, przebieg, cena, wykonawca, kategoria, dodane_przez) VALUES (?,?,?,?,?,?,?,?)",
                            (wizyta_id, zadanie_id, dzis, prz, koszt or 0.0, "", kat, pobierz_moje_imie()))

        cur.execute(f"DELETE FROM do_zrobienia WHERE id IN ({placeholders})", tuple(ids_list))

    przelicz_wszystkie_zadania(auto_id)

    stan = {"cofniete": False}

    def cofnij():
        if stan["cofniete"]:
            return
        stan["cofniete"] = True
        with polacz_baze() as conn:
            conn.execute("DELETE FROM wizyty WHERE id=?", (wizyta_id,))  # kaskadowo skasuje wpisy historii tej wizyty
            if nowo_utworzone_zadania_ids:
                p_z = ",".join("?" for _ in nowo_utworzone_zadania_ids)
                conn.execute(f"DELETE FROM zadania WHERE id IN ({p_z})", tuple(nowo_utworzone_zadania_ids))
            if do_zrobienia_dane:
                kol_bez_id = [k for k in kol_dz if k != "id"]
                p_ins = ",".join("?" for _ in kol_bez_id)
                n_ins = ",".join(kol_bez_id)
                for d in do_zrobienia_dane:
                    conn.execute(f"INSERT INTO do_zrobienia ({n_ins}) VALUES ({p_ins})", tuple(d[k] for k in kol_bez_id))
        przelicz_wszystkie_zadania(auto_id)

    return wizyta_id, duplikaty, {"cofnij": cofnij, "finalizuj": lambda: None}


def pobierz_pozycje_wizyty(wizyta_id) -> list[dict[str, Any]]:
    """Pozycje wizyty nadające się do zwrotu na listę Do zrobienia — czyli wpisy
    historii podpięte pod tę wizytę, razem z nazwą podzespołu i ceną."""
    if not wizyta_id:
        return []
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT h.id, h.cena, h.zadanie_id, z.nazwa "
            "FROM historia h JOIN zadania z ON h.zadanie_id = z.id "
            "WHERE h.wizyta_id=? ORDER BY z.nazwa",
            (wizyta_id,)
        )
        return [
            {"id": r["id"], "nazwa": str(r["nazwa"] or "Pozycja"),
             "cena": float(r["cena"] or 0.0), "zadanie_id": r["zadanie_id"]}
            for r in c.fetchall()
        ]


def zwroc_pozycje_wizyty_do_zrobienia(wizyta_id, historia_ids):
    """Zdejmuje wskazane pozycje z wizyty i odkłada je z powrotem na listę
    Do zrobienia — droga powrotna do utworz_wizyte_z_do_zrobienia, potrzebna
    gdy część została zamówiona, ale nie zamontowana przy tej samej okazji.

    Cena pozycji wraca jako szacowany koszt i jest ODEJMOWANA od kosztu
    całkowitego wizyty — w wizycie zostaje tylko to, co faktycznie zrobiono.
    Zwraca słownik zgodny z utils.pokaz_komunikat_cofnij, wzbogacony o "liczba"
    i "nazwy" zwróconych pozycji.
    """
    if not wizyta_id or not historia_ids:
        return None

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("SELECT auto_id, data, wykonawca, koszt_calkowity FROM wizyty WHERE id=?", (wizyta_id,))
        wiz = c.fetchone()
        if not wiz:
            return None
        auto_id = wiz["auto_id"]
        koszt_przed = float(wiz["koszt_calkowity"] or 0.0)

        c.execute("PRAGMA table_info(historia)")
        kolumny_historii = [r["name"] for r in c.fetchall()]

        placeholders = ",".join("?" for _ in historia_ids)
        c.execute(
            f"SELECT h.*, z.nazwa AS nazwa_zadania FROM historia h "
            f"JOIN zadania z ON h.zadanie_id = z.id "
            f"WHERE h.wizyta_id=? AND h.id IN ({placeholders})",
            (wizyta_id, *historia_ids)
        )
        wiersze = c.fetchall()
        if not wiersze:
            return None

        historia_dane = [{k: r[k] for k in kolumny_historii} for r in wiersze]
        nazwy = [str(r["nazwa_zadania"] or "Pozycja") for r in wiersze]

    suma_zwrocona = sum(float(d.get("cena") or 0.0) for d in historia_dane)
    dzis = datetime.now().strftime("%d.%m.%Y")
    opis_zrodla = f"Zwrócone z wizyty z {wiz['data']}"
    if wiz["wykonawca"]:
        opis_zrodla += f" ({wiz['wykonawca']})"

    # Załączniki (paragony) zdejmowanych wpisów historii chowamy tak jak przy
    # każdym innym usuwaniu z opcją cofnięcia — do_zrobienia nie ma kolumny na
    # załącznik, więc plik czeka w folderze odroczonym na ewentualne cofnięcie.
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

    # Zwracana pozycja znika z historii, więc jej części wracają na stan magazynu.
    czesci_wpisow = _zdejmij_powiazania_czesci_wpisow([d["id"] for d in historia_dane])

    nowe_do_zrobienia_ids = []
    with polacz_baze() as conn:
        c = conn.cursor()
        for d, nazwa in zip(historia_dane, nazwy):
            c.execute(
                "INSERT INTO do_zrobienia (auto_id, tytul, opis, priorytet, szacowany_koszt, "
                "zadanie_id, wykonane, data_utworzenia) VALUES (?,?,?,?,?,?,0,?)",
                (auto_id, nazwa, opis_zrodla, "Średni", float(d.get("cena") or 0.0),
                 d.get("zadanie_id"), dzis)
            )
            nowe_do_zrobienia_ids.append(c.lastrowid)

        c.execute(f"DELETE FROM historia WHERE id IN ({placeholders})", tuple(historia_ids))
        c.execute(
            "UPDATE wizyty SET koszt_calkowity = MAX(0, koszt_calkowity - ?) WHERE id=?",
            (suma_zwrocona, wizyta_id)
        )

    zdalne_id_historii = [d.get("zdalne_id") for d in historia_dane if d.get("zdalne_id")]
    for zid in zdalne_id_historii:
        zarejestruj_nagrobek("historia", zid)
    for w in czesci_wpisow:
        if w.get("zdalne_id"):
            zarejestruj_nagrobek("historia_czesci_magazynu", w["zdalne_id"])

    przelicz_wszystkie_zadania(auto_id)

    stan = {"cofniete": False, "sfinalizowane": False}

    def cofnij():
        if stan["cofniete"] or stan["sfinalizowane"]:
            return
        stan["cofniete"] = True

        for zid in zdalne_id_historii:
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

        with polacz_baze() as conn:
            if nowe_do_zrobienia_ids:
                p_dz = ",".join("?" for _ in nowe_do_zrobienia_ids)
                conn.execute(f"DELETE FROM do_zrobienia WHERE id IN ({p_dz})", tuple(nowe_do_zrobienia_ids))
            nazwy_kol = ",".join(kolumny_historii)
            znaki = ",".join("?" for _ in kolumny_historii)
            for d in historia_dane:
                conn.execute(f"INSERT INTO historia ({nazwy_kol}) VALUES ({znaki})",
                             tuple(d[k] for k in kolumny_historii))
            # Koszt całkowity wraca do wartości sprzed zwrotu, a nie przez
            # dodanie sumy — MAX(0, ...) przy odejmowaniu mogło ją przyciąć.
            conn.execute("UPDATE wizyty SET koszt_calkowity=? WHERE id=?", (koszt_przed, wizyta_id))
        # Wpisy historii wracają tu z oryginalnymi ID (kolumny_historii zawierają id)
        _przywroc_powiazania_czesci_wpisow(czesci_wpisow)
        przelicz_wszystkie_zadania(auto_id)

    def finalizuj():
        if stan["cofniete"]:
            return
        stan["sfinalizowane"] = True
        for tmp, _ in sciezki_tymczasowe:
            usun_plik_zalacznika(tmp)

    return {
        "cofnij": cofnij, "finalizuj": finalizuj,
        "liczba": len(historia_dane), "nazwy": nazwy,
        "kwota": suma_zwrocona, "auto_id": auto_id,
    }


def usun_wizyty_z_cofnieciem(ids_list):
    """Grupowe (lub pojedyncze) usuwanie wizyt zbiorczych z pełnym cofaniem, w tym magazynu."""
    if not ids_list:
        return None

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        placeholders = ",".join("?" for _ in ids_list)

        # 1. Pobieramy wizyty
        c.execute("PRAGMA table_info(wizyty)")
        kolumny_wizyty = [r["name"] for r in c.fetchall()]
        c.execute(f"SELECT * FROM wizyty WHERE id IN ({placeholders})", tuple(ids_list))
        wizyty_dane = [{k: w[k] for k in kolumny_wizyty} for w in c.fetchall()]

        # 2. Pobieramy powiązaną historię
        c.execute("PRAGMA table_info(historia)")
        kolumny_historia = [r["name"] for r in c.fetchall()]
        c.execute(f"SELECT * FROM historia WHERE wizyta_id IN ({placeholders})", tuple(ids_list))
        historia_dane = [{k: w[k] for k in kolumny_historia} for w in c.fetchall()]

        # 3. Pobieramy użyte części
        c.execute("PRAGMA table_info(wizyta_czesci_magazynu)")
        kolumny_czesci = [r["name"] for r in c.fetchall()]
        c.execute(f"SELECT * FROM wizyta_czesci_magazynu WHERE wizyta_id IN ({placeholders})", tuple(ids_list))
        czesci_dane = [{k: w[k] for k in kolumny_czesci} for w in c.fetchall()]

    if not wizyty_dane:
        return None

    # Bezpieczne chowanie załączników z wizyt
    sciezki_tymczasowe = []
    folder_tmp = _upewnij_folder_odroczonych()
    for dane in wizyty_dane:
        oryginalna = dane.get("zalacznik")
        if oryginalna and os.path.exists(oryginalna):
            sciezka_tmp = os.path.join(folder_tmp, f"wizyta_{uuid.uuid4().hex}_{os.path.basename(oryginalna)}")
            try:
                shutil.move(oryginalna, sciezka_tmp)
                sciezki_tymczasowe.append((sciezka_tmp, oryginalna))
            except Exception:
                pass

    # Faktyczne operacje kasowania (oddajemy też części do magazynu!)
    with polacz_baze() as conn:
        for wid in ids_list:
            przywroc_czesci_wizyty(wid, conn=conn)
        conn.execute(f"DELETE FROM historia WHERE wizyta_id IN ({placeholders})", tuple(ids_list))
        conn.execute(f"DELETE FROM wizyty WHERE id IN ({placeholders})", tuple(ids_list))

    zdalne_id_wizyt = [d.get("zdalne_id") for d in wizyty_dane if d.get("zdalne_id")]
    zdalne_id_historii = [d.get("zdalne_id") for d in historia_dane if d.get("zdalne_id")]
    zdalne_id_czesci = [d.get("zdalne_id") for d in czesci_dane if d.get("zdalne_id")]
    for zid in zdalne_id_wizyt:
        zarejestruj_nagrobek("wizyty", zid)
    for zid in zdalne_id_historii:
        zarejestruj_nagrobek("historia", zid)
    for zid in zdalne_id_czesci:
        zarejestruj_nagrobek("wizyta_czesci_magazynu", zid)

    stan = {"cofniete": False, "trwale_usuniete": False}

    def cofnij():
        if stan["cofniete"] or stan["trwale_usuniete"]: return
        stan["cofniete"] = True

        for zid in zdalne_id_wizyt:
            usun_nagrobek(zid)
        for zid in zdalne_id_historii:
            usun_nagrobek(zid)
        for zid in zdalne_id_czesci:
            usun_nagrobek(zid)

        for tmp, oryg in sciezki_tymczasowe:
            if os.path.exists(tmp):
                try: shutil.move(tmp, oryg)
                except Exception: pass

        with polacz_baze() as conn:
            if wizyty_dane:
                p_w = ",".join("?" for _ in kolumny_wizyty)
                n_w = ",".join(kolumny_wizyty)
                for d in wizyty_dane:
                    conn.execute(f"INSERT INTO wizyty ({n_w}) VALUES ({p_w})", tuple(d[k] for k in kolumny_wizyty))
            
            if historia_dane:
                p_h = ",".join("?" for _ in kolumny_historia)
                n_h = ",".join(kolumny_historia)
                for d in historia_dane:
                    conn.execute(f"INSERT INTO historia ({n_h}) VALUES ({p_h})", tuple(d[k] for k in kolumny_historia))

            if czesci_dane:
                p_c = ",".join("?" for _ in kolumny_czesci)
                n_c = ",".join(kolumny_czesci)
                for d in czesci_dane:
                    conn.execute(f"INSERT INTO wizyta_czesci_magazynu ({n_c}) VALUES ({p_c})", tuple(d[k] for k in kolumny_czesci))
                    # Ponownie potrącamy części ze stanu magazynu
                    conn.execute("UPDATE magazyn_czesci SET ilosc = MAX(0, ilosc - ?) WHERE id=?", (d["ilosc_uzyta"], d["magazyn_id"]))

    def finalizuj_usuniecie():
        if stan["cofniete"]: return
        stan["trwale_usuniete"] = True
        for tmp, _ in sciezki_tymczasowe:
            usun_plik_zalacznika(tmp)

    return {"cofnij": cofnij, "finalizuj": finalizuj_usuniecie}


__all__ = [
    "pobierz_pozycje_wizyty",
    "usun_wizyty_z_cofnieciem",
    "utworz_wizyte_z_do_zrobienia",
    "zwroc_pozycje_wizyty_do_zrobienia",
]
