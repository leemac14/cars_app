"""Wizyty serwisowe i ich powiązanie z listą Do zrobienia."""

import sqlite3
from date import na_iso
from datetime import datetime
from typing import Any

from .polaczenie import polacz_baze
from .ustawienia import pobierz_moje_imie
from .synchronizacja import usun_nagrobek, zarejestruj_nagrobek
from .zalaczniki import odloz_zalaczniki_rekordow, przywroc_odlozone_zalaczniki, skasuj_odlozone_zalaczniki
from .magazyn import _przywroc_powiazania_czesci_wpisow, _zdejmij_powiazania_czesci_wpisow
from .przebieg import pobierz_aktualny_przebieg, przelicz_wszystkie_zadania
from .kosz_wpisow import usun_do_kosza
from .awarie import domyslny_rodzaj_serwisu
from .nazwy import klucz_nazwy
from .do_zrobienia import ZDARZENIE_WIZYTA, ZDARZENIE_ZWROT, usun_zdarzenia_do_zrobienia, zanotuj_zdarzenie_do_zrobienia


_ODWOLANIA_DO_ZROBIENIA = {"zadanie_id": "zadania", "historia_id": "historia", "koszt_id": "inne_koszty",
                           "wizyta_id": "wizyty"}


def _przywroc_pozycje_do_zrobienia(conn, migawki):
    """Wiersze do_zrobienia wracają do stanu z migawki (cofnięcie); odwołanie do wiersza,
    którego już nie ma, wraca jako NULL."""
    for migawka in migawki:
        dane = {k: v for k, v in migawka.items() if k != "id"}
        for kolumna, tabela in _ODWOLANIA_DO_ZROBIENIA.items():
            if dane.get(kolumna) and not conn.execute(f"SELECT 1 FROM {tabela} WHERE id=?", (dane[kolumna],)).fetchone():
                dane[kolumna] = None
        conn.execute(f"UPDATE do_zrobienia SET {', '.join(f'{k}=?' for k in dane)} WHERE id=?",
                     (*dane.values(), migawka["id"]))


def utworz_wizyte_z_do_zrobienia(auto_id, ids_list, utworz_podzespoly=False) -> tuple[int | None, list[str], dict[str, Any] | None]:
    """Pozycje idą do Wykonanych z odnośnikiem do nowej wizyty (i swojego wpisu w niej).
    Zwraca (wizyta_id, duplikaty, wynik_cofniecia). wynik_cofniecia to słownik
    {"cofnij": fn, "finalizuj": fn} analogiczny do pozostałych operacji usuwających —
    pozwala pokazać snackbar z możliwością cofnięcia całej operacji."""
    if not ids_list: return None, [], None
    dzis = datetime.now().strftime("%d.%m.%Y")
    prz = pobierz_aktualny_przebieg(auto_id) or 0
    ja = pobierz_moje_imie()
    duplikaty = []
    nowo_utworzone_zadania_ids = []
    zdarzenia = []

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("PRAGMA table_info(do_zrobienia)")
        kol_dz = [r["name"] for r in cur.fetchall()]

        placeholders = ",".join("?" for _ in ids_list)
        cur.execute(f"SELECT * FROM do_zrobienia WHERE id IN ({placeholders})", tuple(ids_list))
        do_zrobienia_dane = [{k: w[k] for k in kol_dz} for w in cur.fetchall()]
        pozycje = [(d["id"], d["tytul"], d["szacowany_koszt"], d["zadanie_id"]) for d in do_zrobienia_dane]

        suma_kosztow = sum((p[2] or 0.0) for p in pozycje)
        tytuly = [p[1] for p in pozycje]
        notatki = "Utworzono z listy: " + ", ".join(tytuly)

        cur.execute("INSERT INTO wizyty (auto_id, data, data_iso, przebieg, wykonawca, koszt_calkowity, notatki, dodane_przez) VALUES (?,?,?,?,?,?,?,?)",
                    (auto_id, dzis, na_iso(dzis), prz, "", suma_kosztow, notatki, ja))
        wizyta_id = cur.lastrowid
        zadania_wizyty = []
        wpisy_pozycji = {}

        for pozycja_id, tytul, koszt, zadanie_id in pozycje:
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
                cur.execute("INSERT INTO historia (wizyta_id, zadanie_id, data, data_iso, przebieg, cena, wykonawca, kategoria, dodane_przez) VALUES (?,?,?,?,?,?,?,?,?)",
                            (wizyta_id, zadanie_id, dzis, na_iso(dzis), prz, koszt or 0.0, "", kat, ja))
                zadania_wizyty.append(zadanie_id)
                wpisy_pozycji[pozycja_id] = cur.lastrowid

        # Rodzaj jak w nowej wizycie z formularza: „planowe”, gdy każdy podzespół ma interwał.
        rodzaj = domyslny_rodzaj_serwisu(zadania_wizyty, conn=conn)
        if rodzaj:
            cur.execute("UPDATE wizyty SET rodzaj=? WHERE id=?", (rodzaj, wizyta_id))
            cur.execute("UPDATE historia SET rodzaj=? WHERE wizyta_id=?", (rodzaj, wizyta_id))

        # Pozycje nie znikają: trafiają do Wykonanych z odnośnikiem do wizyty (i swojego wpisu).
        for pozycja_id, _, koszt, _ in pozycje:
            cur.execute("UPDATE do_zrobienia SET wykonane=1, data_wykonania=?, przebieg_wykonania=?, koszt_wykonania=?, "
                        "notatka_wykonania=NULL, wykonane_przez=?, wizyta_id=?, historia_id=?, koszt_id=NULL WHERE id=?",
                        (dzis, prz or None, koszt, ja or None, wizyta_id, wpisy_pozycji.get(pozycja_id), pozycja_id))
            zdarzenia.append(zanotuj_zdarzenie_do_zrobienia(conn, pozycja_id, ZDARZENIE_WIZYTA,
                                                            {"wizyta_id": wizyta_id, "data": dzis}, ja))

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
            _przywroc_pozycje_do_zrobienia(conn, do_zrobienia_dane)
        usun_zdarzenia_do_zrobienia(zdarzenia, auto_id)
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
    """Zdejmuje pozycje z wizyty i odkłada na listę Do zrobienia (odwrotność
    utworz_wizyte_z_do_zrobienia): pozycja, z której wpis powstał, wraca z Wykonanych,
    reszta jako nowe. Cena pozycji wraca jako szacowany koszt i jest ODEJMOWANA od kosztu
    wizyty. Zwraca słownik dla utils.pokaz_komunikat_cofnij z „liczba” i „nazwy”."""
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

    # Pliki zdejmowanych wpisów czekają w folderze odroczonych na ewentualne cofnięcie —
    # pozycja do zrobienia nie ma plików.
    pliki_historii = odloz_zalaczniki_rekordow("historia", [d["id"] for d in historia_dane])

    # Zwracana pozycja znika z historii, więc jej części wracają na stan magazynu.
    czesci_wpisow = _zdejmij_powiazania_czesci_wpisow([d["id"] for d in historia_dane])

    nowe_do_zrobienia_ids = []
    wznowione, zdarzenia = [], []
    ja = pobierz_moje_imie()
    zrodlo = {"data": wiz["data"], "wykonawca": wiz["wykonawca"] or None}
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        for d, nazwa in zip(historia_dane, nazwy):
            # Pozycja, z której wpis powstał, wraca na listę sama — z całym swoim dziennikiem.
            dawna = c.execute("SELECT * FROM do_zrobienia WHERE historia_id=? AND wykonane=1 ORDER BY id LIMIT 1",
                              (d["id"],)).fetchone()
            cena = float(d.get("cena") or 0.0)
            if dawna:
                wznowione.append(dict(dawna))
                c.execute("UPDATE do_zrobienia SET wykonane=0, data_wykonania=NULL, przebieg_wykonania=NULL, "
                          "koszt_wykonania=NULL, notatka_wykonania=NULL, wykonane_przez=NULL, historia_id=NULL, "
                          "koszt_id=NULL, wizyta_id=NULL, szacowany_koszt=? WHERE id=?",
                          (cena or dawna["szacowany_koszt"], dawna["id"]))
                zdarzenia.append(zanotuj_zdarzenie_do_zrobienia(conn, dawna["id"], ZDARZENIE_ZWROT, zrodlo, ja))
                continue
            nowa = c.execute(
                "INSERT INTO do_zrobienia (auto_id, tytul, opis, priorytet, szacowany_koszt, "
                "zadanie_id, wykonane, data_utworzenia) VALUES (?,?,?,?,?,?,0,?)",
                (auto_id, nazwa, opis_zrodla, "Średni", cena,
                 d.get("zadanie_id"), dzis)
            ).lastrowid
            nowe_do_zrobienia_ids.append(nowa)
            zanotuj_zdarzenie_do_zrobienia(conn, nowa, ZDARZENIE_ZWROT, zrodlo, ja)

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
            _przywroc_pozycje_do_zrobienia(conn, wznowione)
        usun_zdarzenia_do_zrobienia(zdarzenia, auto_id)
        # Wpisy historii wracają tu z oryginalnymi ID (kolumny_historii zawierają id)
        _przywroc_powiazania_czesci_wpisow(czesci_wpisow)
        przywroc_odlozone_zalaczniki(pliki_historii)
        przelicz_wszystkie_zadania(auto_id)

    def finalizuj():
        if stan["cofniete"]:
            return
        stan["sfinalizowane"] = True
        skasuj_odlozone_zalaczniki(pliki_historii)

    return {
        "cofnij": cofnij, "finalizuj": finalizuj,
        "liczba": len(historia_dane), "nazwy": nazwy,
        "kwota": suma_zwrocona, "auto_id": auto_id,
    }


def usun_wizyty_z_cofnieciem(ids_list):
    """Usuwa wizyty z pozycjami, plikami i zużytymi częściami (wracają na półkę) do kosza
    wpisów — grupa to jedna pozycja kosza. Wynik jak db.usun_z_cofnieciem."""
    return usun_do_kosza("wizyty", ids_list)


__all__ = [
    "pobierz_pozycje_wizyty",
    "usun_wizyty_z_cofnieciem",
    "utworz_wizyte_z_do_zrobienia",
    "zwroc_pozycje_wizyty_do_zrobienia",
]
