"""Magazyn części: rozliczanie zużycia, zwroty i zestawy opon."""

import os
import shutil
import sqlite3
import uuid
from datetime import datetime

from .stale import MIESIACE_ZIMOWE, SEZONY_PRZELACZALNE
from .polaczenie import polacz_baze
from .synchronizacja import czy_moge_zmieniac_rekord, usun_nagrobek, zarejestruj_nagrobek
from .zalaczniki import _upewnij_folder_odroczonych, usun_plik_zalacznika


# Zużycie części z magazynu ma dwa nośniki: wizytę zbiorczą i pojedynczy wpis
# serwisowy. Tabele są lustrzane, więc cała logika (pobranie, oddanie na stan,
# potrącenie) siedzi w jednym rdzeniu sparametryzowanym nazwą tabeli i kolumną
# wiążącą — zamiast dwóch kopii, które z czasem by się rozjechały.
POWIAZANIA_MAGAZYNU = {
    "wizyty": ("wizyta_czesci_magazynu", "wizyta_id"),
    "historia": ("historia_czesci_magazynu", "historia_id"),
}


def _pobierz_uzyte_czesci(zrodlo, rekord_id):
    tabela, kolumna = POWIAZANIA_MAGAZYNU[zrodlo]
    if not rekord_id:
        return []
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(f"SELECT magazyn_id, ilosc_uzyta FROM {tabela} WHERE {kolumna}=?", (rekord_id,))
        return c.fetchall()


def _przywroc_czesci(zrodlo, rekord_id, conn=None):
    """Oddaje do magazynu wykorzystane wcześniej części i usuwa powiązania.
    Zwraca listę zdalne_id usuniętych powiązań — WYWOŁUJĄCY musi je
    zarejestrować jako nagrobki (zarejestruj_nagrobek) DOPIERO PO
    zamknięciu/commicie bieżącej transakcji (conn). Rejestracja w środku
    otwartej transakcji otworzyłaby drugie połączenie do tego samego pliku
    SQLite i mogłaby zakleszczyć bazę."""
    tabela, kolumna = POWIAZANIA_MAGAZYNU[zrodlo]
    usuniete_zdalne_id = []

    def _wykonaj(c):
        cur = c.cursor()
        cur.execute(f"SELECT magazyn_id, ilosc_uzyta, zdalne_id FROM {tabela} WHERE {kolumna}=?", (rekord_id,))
        for magazyn_id, ilosc, zdalne_id in cur.fetchall():
            cur.execute("UPDATE magazyn_czesci SET ilosc = ilosc + ? WHERE id=?", (ilosc, magazyn_id))
            if zdalne_id:
                usuniete_zdalne_id.append(zdalne_id)
        cur.execute(f"DELETE FROM {tabela} WHERE {kolumna}=?", (rekord_id,))

    if conn is not None:
        _wykonaj(conn)
    else:
        with polacz_baze() as conn_local:
            _wykonaj(conn_local)

    return usuniete_zdalne_id


def _rozlicz_czesci(zrodlo, rekord_id, uzyte, conn=None):
    tabela, kolumna = POWIAZANIA_MAGAZYNU[zrodlo]
    if not uzyte:
        return

    def _wykonaj(c):
        cur = c.cursor()
        for magazyn_id, ilosc in uzyte:
            if not ilosc or ilosc <= 0:
                continue
            cur.execute(
                f"INSERT INTO {tabela} ({kolumna}, magazyn_id, ilosc_uzyta) VALUES (?,?,?)",
                (rekord_id, magazyn_id, ilosc)
            )
            cur.execute("UPDATE magazyn_czesci SET ilosc = MAX(0, ilosc - ?) WHERE id=?", (ilosc, magazyn_id))

    if conn is not None:
        _wykonaj(conn)
    else:
        with polacz_baze() as conn_local:
            _wykonaj(conn_local)


# --- Wizyta zbiorcza (nazwy zachowane, bo używa ich formularz wizyty) ---
def pobierz_uzyte_czesci_wizyty(wizyta_id):
    return _pobierz_uzyte_czesci("wizyty", wizyta_id)


def przywroc_czesci_wizyty(wizyta_id, conn=None):
    return _przywroc_czesci("wizyty", wizyta_id, conn)


def rozlicz_czesci_z_magazynu(wizyta_id, uzyte, conn=None):
    return _rozlicz_czesci("wizyty", wizyta_id, uzyte, conn)


# --- Pojedynczy wpis serwisowy (poza wizytą) ---
def pobierz_uzyte_czesci_wpisu(historia_id):
    return _pobierz_uzyte_czesci("historia", historia_id)


def przywroc_czesci_wpisu(historia_id, conn=None):
    return _przywroc_czesci("historia", historia_id, conn)


def rozlicz_czesci_z_magazynu_wpisu(historia_id, uzyte, conn=None):
    return _rozlicz_czesci("historia", historia_id, uzyte, conn)


def _zdejmij_powiazania_czesci_wpisow(historia_ids):
    """Przed skasowaniem wpisów serwisowych oddaje ich części na stan magazynu
    i zwraca zdjęte wiersze powiązań. CASCADE i tak skasowałby te powiązania —
    ale zrobiłby to CICHO, zostawiając sztuki „zużyte” w nieistniejącym już
    wpisie. Zwrócone wiersze pozwalają odtworzyć stan przy cofnięciu."""
    if not historia_ids:
        return []
    placeholders = ",".join("?" for _ in historia_ids)
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("PRAGMA table_info(historia_czesci_magazynu)")
        kolumny = [r["name"] for r in c.fetchall()]
        c.execute(
            f"SELECT * FROM historia_czesci_magazynu WHERE historia_id IN ({placeholders})",
            tuple(historia_ids)
        )
        wiersze = [{k: w[k] for k in kolumny} for w in c.fetchall()]
        if wiersze:
            for w in wiersze:
                c.execute("UPDATE magazyn_czesci SET ilosc = ilosc + ? WHERE id=?",
                          (w["ilosc_uzyta"], w["magazyn_id"]))
            c.execute(
                f"DELETE FROM historia_czesci_magazynu WHERE historia_id IN ({placeholders})",
                tuple(historia_ids)
            )
    return wiersze


def _przywroc_powiazania_czesci_wpisow(wiersze, mapa_historia=None):
    """Odwrotność _zdejmij_...: wstawia powiązania z powrotem (z oryginalnymi ID,
    o ile wolne) i ponownie potrąca sztuki ze stanu magazynu.

    mapa_historia przemapowuje historia_id: ścieżki cofania wstawiają wpis
    serwisowy BEZ oryginalnego id (patrz kolumny_bez_id), więc po przywróceniu
    zwykle ma on nowe ID i powiązanie wskazywałoby w próżnię."""
    if not wiersze:
        return
    mapa_historia = mapa_historia or {}
    with polacz_baze() as conn:
        c = conn.cursor()
        for w in wiersze:
            dane = dict(w)
            dane["historia_id"] = mapa_historia.get(dane.get("historia_id"), dane.get("historia_id"))
            c.execute("SELECT 1 FROM historia WHERE id=?", (dane["historia_id"],))
            if c.fetchone() is None:
                # Wpis nie wrócił (albo wrócił pod nieznanym ID) — powiązania nie
                # da się odtworzyć, a sztuki zostały już oddane na stan magazynu.
                continue
            stare_id = dane.get("id")
            if stare_id is not None:
                c.execute("SELECT 1 FROM historia_czesci_magazynu WHERE id=?", (stare_id,))
                if c.fetchone() is not None:
                    dane.pop("id", None)
            nazwy = list(dane.keys())
            c.execute(
                f"INSERT INTO historia_czesci_magazynu ({','.join(nazwy)}) "
                f"VALUES ({','.join('?' * len(nazwy))})",
                tuple(dane[k] for k in nazwy)
            )
            c.execute("UPDATE magazyn_czesci SET ilosc = MAX(0, ilosc - ?) WHERE id=?",
                      (dane["ilosc_uzyta"], dane["magazyn_id"]))


def usun_czesc_magazynu_z_cofnieciem(czesc_id):
    """Usuwa pozycję magazynową wraz z powiązanymi wpisami zużycia — zarówno
    w wizytach (wizyta_czesci_magazynu), jak i w pojedynczych wpisach serwisowych
    (historia_czesci_magazynu) — które SQLite skasowałoby cicho przez CASCADE.
    Zachowuje oryginalne ID pozycji."""
    if not czesc_id:
        return None

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("PRAGMA table_info(magazyn_czesci)")
        kol_m = [r["name"] for r in c.fetchall()]
        c.execute("SELECT * FROM magazyn_czesci WHERE id=?", (czesc_id,))
        w = c.fetchone()
        if not w:
            return None
        dane_czesc = {k: w[k] for k in kol_m}

        # Magazyn to wspólny inwentarz pojazdu, więc współautora nie ogranicza —
        # ale gość z rolą „tylko podgląd” nie ma prawa go czyścić (patrz
        # db/synchronizacja.czy_moge_zmieniac_rekord).
        try:
            if dane_czesc.get("auto_id") and not czy_moge_zmieniac_rekord(
                dane_czesc["auto_id"], "magazyn_czesci", None
            ):
                return None
        except Exception:
            pass

        c.execute("PRAGMA table_info(wizyta_czesci_magazynu)")
        kol_w = [r["name"] for r in c.fetchall()]
        c.execute("SELECT * FROM wizyta_czesci_magazynu WHERE magazyn_id=?", (czesc_id,))
        uzycia_dane = [{k: r[k] for k in kol_w} for r in c.fetchall()]

        c.execute("PRAGMA table_info(historia_czesci_magazynu)")
        kol_hw = [r["name"] for r in c.fetchall()]
        c.execute("SELECT * FROM historia_czesci_magazynu WHERE magazyn_id=?", (czesc_id,))
        uzycia_wpisow = [{k: r[k] for k in kol_hw} for r in c.fetchall()]

    sciezka_tymczasowa = None
    oryginalna = dane_czesc.get("zalacznik")
    if oryginalna and os.path.exists(oryginalna):
        folder_tmp = _upewnij_folder_odroczonych()
        sciezka_tymczasowa = os.path.join(folder_tmp, f"magazyn_{uuid.uuid4().hex}_{os.path.basename(oryginalna)}")
        try:
            shutil.move(oryginalna, sciezka_tymczasowa)
        except Exception:
            sciezka_tymczasowa = None

    with polacz_baze() as conn:
        conn.execute("DELETE FROM magazyn_czesci WHERE id=?", (czesc_id,))

    zdalny_id_czesci = dane_czesc.get("zdalne_id")
    if zdalny_id_czesci:
        zarejestruj_nagrobek("magazyn_czesci", zdalny_id_czesci)

    zdalne_id_uzycia = [d.get("zdalne_id") for d in uzycia_dane if d.get("zdalne_id")]
    for zid in zdalne_id_uzycia:
        zarejestruj_nagrobek("wizyta_czesci_magazynu", zid)

    zdalne_id_uzycia_wpisow = [d.get("zdalne_id") for d in uzycia_wpisow if d.get("zdalne_id")]
    for zid in zdalne_id_uzycia_wpisow:
        zarejestruj_nagrobek("historia_czesci_magazynu", zid)

    stan = {"cofniete": False, "trwale_usuniete": False}

    def cofnij():
        if stan["cofniete"] or stan["trwale_usuniete"]:
            return
        stan["cofniete"] = True

        if zdalny_id_czesci:
            usun_nagrobek(zdalny_id_czesci)
        for zid in zdalne_id_uzycia + zdalne_id_uzycia_wpisow:
            usun_nagrobek(zid)
        
        if sciezka_tymczasowa and os.path.exists(sciezka_tymczasowa):
            try:
                shutil.move(sciezka_tymczasowa, oryginalna)
            except Exception:
                pass
                
        with polacz_baze() as conn:
            n_m, p_m = ",".join(kol_m), ",".join("?" for _ in kol_m)
            conn.execute(f"INSERT INTO magazyn_czesci ({n_m}) VALUES ({p_m})", tuple(dane_czesc[k] for k in kol_m))
            if uzycia_dane:
                n_w, p_w = ",".join(kol_w), ",".join("?" for _ in kol_w)
                for d in uzycia_dane:
                    conn.execute(f"INSERT INTO wizyta_czesci_magazynu ({n_w}) VALUES ({p_w})", tuple(d[k] for k in kol_w))
            if uzycia_wpisow:
                n_hw, p_hw = ",".join(kol_hw), ",".join("?" for _ in kol_hw)
                for d in uzycia_wpisow:
                    conn.execute(f"INSERT INTO historia_czesci_magazynu ({n_hw}) VALUES ({p_hw})", tuple(d[k] for k in kol_hw))

    def finalizuj_usuniecie():
        if stan["cofniete"]:
            return
        stan["trwale_usuniete"] = True
        if sciezka_tymczasowa:
            usun_plik_zalacznika(sciezka_tymczasowa)

    return {"cofnij": cofnij, "finalizuj": finalizuj_usuniecie}


def usun_wiele_czesci_magazynu_z_cofnieciem(ids_list):
    wyniki = [w for w in (usun_czesc_magazynu_z_cofnieciem(cid) for cid in ids_list) if w]
    if not wyniki:
        return None

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

    return {"cofnij": cofnij, "finalizuj": finalizuj_usuniecie}


def pobierz_stan_magazynu(auto_id):
    """Ile pozycji leży na półce i ile z nich zeszło poniżej własnego progu —
    jedna liczba, po którą sięga kafelek kokpitu i podsumowania."""
    if not auto_id:
        return {"razem": 0, "niski": 0, "nazwy_niskich": []}
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT nazwa, ilosc, jednostka, prog_ostrzezenia FROM magazyn_czesci WHERE auto_id=?",
            (auto_id,)
        )
        wiersze = c.fetchall()

    niskie = []
    for nazwa, ilosc, jednostka, prog in wiersze:
        try:
            prog_efektywny = float(prog) if prog is not None else 1.0
        except (TypeError, ValueError):
            prog_efektywny = 1.0
        if float(ilosc or 0) <= prog_efektywny:
            niskie.append(str(nazwa or ""))
    return {"razem": len(wiersze), "niski": len(niskie), "nazwy_niskich": niskie}


# ============================================================================
#  SEZONOWA ZMIANA OPON
# ============================================================================
# Zmiana opon to jedyne cykliczne przypomnienie, którego wykonanie ZMIENIA STAN
# w bazie: po niej na aucie stoi drugi komplet. Dopóki było zwykłym wpisem
# w kalendarzu, magazyn opon i tak trzeba było poprawić ręcznie w drugim
# miejscu — a że nikt tego nie robił, aplikacja przez pół roku twierdziła, że
# auto jeździ na zimówkach w lipcu.


def _docelowy_sezon(zamontowany_sezon, dzis=None):
    """Na co zmieniamy. Kierunek bierzemy z tego, co JEST na aucie — to jedyna
    pewna informacja. Dopiero gdy nic nie jest zamontowane (albo stoją opony
    całoroczne, które nie mają pary), decyduje kalendarz."""
    if zamontowany_sezon in SEZONY_PRZELACZALNE:
        return "Letnie" if zamontowany_sezon == "Zimowe" else "Zimowe"
    miesiac = (dzis or datetime.now()).month
    return "Zimowe" if miesiac in MIESIACE_ZIMOWE else "Letnie"


def pobierz_stan_opon(auto_id):
    """Co stoi na aucie i co czeka w piwnicy — jedno źródło dla kafelka kokpitu
    i dla samego przełączania. Zwraca None, gdy pojazd nie ma ani jednego
    zestawu (wtedy nie ma o czym mówić)."""
    if not auto_id:
        return None
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, sezon, rozmiar, marka_model, glebokosc_bieznika, zamontowane, os_montazu "
            "FROM zestawy_opon WHERE auto_id=? ORDER BY zamontowane DESC, id",
            (auto_id,)
        )
        wiersze = c.fetchall()
    if not wiersze:
        return None

    zestawy = [
        {"id": w[0], "sezon": str(w[1] or ""), "rozmiar": str(w[2] or ""),
         "marka_model": str(w[3] or ""), "bieznik": w[4],
         "zamontowany": bool(w[5]), "os": str(w[6] or "Wszystkie")}
        for w in wiersze
    ]
    zamontowane = [z for z in zestawy if z["zamontowany"]]
    biezniki = [float(z["bieznik"]) for z in zamontowane if z["bieznik"] not in (None, "")]
    sezon_teraz = zamontowane[0]["sezon"] if zamontowane else None
    docelowy = _docelowy_sezon(sezon_teraz)
    czeka = [z for z in zestawy if not z["zamontowany"] and z["sezon"] == docelowy]

    return {
        "zestawy": zestawy,
        "zamontowane": zamontowane,
        "sezon": sezon_teraz,
        "bieznik": min(biezniki) if biezniki else None,
        "docelowy_sezon": docelowy,
        "kandydaci": czeka,
        "ma_para": bool(czeka),
    }


def przelacz_zestaw_sezonowy(auto_id, docelowy_sezon=None):
    """Zdejmuje obecny komplet i montuje ten z drugiego sezonu.

    Zwraca słownik z opisem tego, co się stało (`ok`, `z`, `na`, `powod`) —
    interfejs musi umieć powiedzieć „zmieniono z Zimowych na Letnie” ALBO
    „nie ma czego zamontować”, a nie tylko cicho przesunąć termin.

    Kandydatów rozstrzygamy po najgrubszym bieżniku: jeśli ktoś trzyma dwa
    komplety letnich, na auto ma trafić ten lepszy, a nie ten z niższym ID.
    """
    stan = pobierz_stan_opon(auto_id)
    if not stan:
        return {"ok": False, "powod": "brak_zestawow"}

    docelowy = docelowy_sezon or stan["docelowy_sezon"]
    kandydaci = [z for z in stan["zestawy"] if not z["zamontowany"] and z["sezon"] == docelowy]
    if not kandydaci:
        return {"ok": False, "powod": "brak_kompletu", "docelowy_sezon": docelowy,
                "z": stan["sezon"]}

    def waga(z):
        try:
            return -float(z["bieznik"])
        except (TypeError, ValueError):
            return 0.0

    nowy = sorted(kandydaci, key=lambda z: (waga(z), z["id"]))[0]

    with polacz_baze() as conn:
        conn.execute("UPDATE zestawy_opon SET zamontowane=0 WHERE auto_id=?", (auto_id,))
        conn.execute(
            "UPDATE zestawy_opon SET zamontowane=1, os_montazu='Wszystkie' WHERE id=?",
            (nowy["id"],)
        )

    return {
        "ok": True,
        "z": stan["sezon"],
        "na": nowy["sezon"],
        "zestaw_id": nowy["id"],
        "opis_zestawu": " ".join(x for x in (nowy["marka_model"], nowy["rozmiar"]) if x),
        "bieznik": nowy["bieznik"],
    }


__all__ = [
    "POWIAZANIA_MAGAZYNU",
    "_docelowy_sezon",
    "_pobierz_uzyte_czesci",
    "_przywroc_czesci",
    "_przywroc_powiazania_czesci_wpisow",
    "_rozlicz_czesci",
    "_zdejmij_powiazania_czesci_wpisow",
    "pobierz_stan_magazynu",
    "pobierz_stan_opon",
    "pobierz_uzyte_czesci_wizyty",
    "pobierz_uzyte_czesci_wpisu",
    "przelacz_zestaw_sezonowy",
    "przywroc_czesci_wizyty",
    "przywroc_czesci_wpisu",
    "rozlicz_czesci_z_magazynu",
    "rozlicz_czesci_z_magazynu_wpisu",
    "usun_czesc_magazynu_z_cofnieciem",
    "usun_wiele_czesci_magazynu_z_cofnieciem",
]
