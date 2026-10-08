"""Pliki załączników: zapis, dwuetapowe zatwierdzanie, sprzątanie."""

import os
import shutil
import time
import uuid
from typing import Any
try:
    from PIL import Image, ImageOps
except ImportError:
    Image = None
    ImageOps = None

import log

from .stale import (
    FOLDER_KOSZ, FOLDER_ODROCZONE, FOLDER_ZALACZNIKI, STORAGE_PATH, TABELE_DAWNEGO_ZALACZNIKA,
    TABELE_Z_WIELOMA_ZALACZNIKAMI, TABELE_Z_ZALACZNIKIEM,
)
from .polaczenie import polacz_baze


# Gdzie w bazie mieszkają ścieżki do plików: zdjęcie pojazdu, pliki wpisów i dokumentów
# (`zalaczniki`) i kolumna `zalacznik` tabel, w których wiersz JEST plikiem.
KOLUMNY_ZE_SCIEZKAMI = ([("samochody", "zdjecie_glowne"), ("zalaczniki", "sciezka")]
                        + [(t, "zalacznik") for t in sorted(TABELE_Z_ZALACZNIKIEM)])


# ---------------------------------------------------------------- ścieżki w bazie
# Baza trzyma ścieżkę WZGLĘDNĄ wobec STORAGE_PATH, zawsze z '/':
# 'zalaczniki/<uuid>.jpg', w `pliki` kosza 'kosz_zalaczniki/<plik>'; STORAGE_PATH
# dokłada się dopiero przy odczycie. Starsze bazy mają ścieżki bezwzględne (Android) i
# względne z odwrotnym ukośnikiem (Windows) — odczyt rozumie wszystkie, bez migracji.
# Wartość z bazy do os.path / shutil / ft.Image tylko przez sciezka_pliku_zalacznika
# (albo utils.abs_zalacznik), zapis przez wzgledna_sciezka_zalacznika.


def _z_ukosnikami(sciezka) -> str:
    return str(sciezka).replace("\\", "/")


def _czy_bezwzgledna(tekst: str) -> bool:
    """Bezwzględna na KTÓRYMKOLWIEK systemie: ścieżka z Androida oglądana na
    Windows i ścieżka z Windows oglądana na Androidzie też się liczą."""
    return tekst.startswith("/") or (len(tekst) >= 3 and tekst[0].isalpha() and tekst[1:3] == ":/")


def _foldery_zalacznikow() -> list[tuple[str, str]]:
    """(nazwa, ścieżka) folderów aplikacji z plikami wskazywanymi z bazy."""
    return [(os.path.basename(os.path.normpath(folder)), folder) for folder in (FOLDER_ZALACZNIKI, FOLDER_KOSZ)]


def _folder_i_nazwa(sciezka) -> tuple[str, str] | None:
    """(nazwa folderu, nazwa pliku), gdy plik leży w folderze aplikacji — tutaj
    albo na innym urządzeniu. Pliki leżą w tych folderach płasko."""
    czesci = [c for c in _z_ukosnikami(sciezka).split("/") if c not in ("", ".")]
    if len(czesci) < 2 or czesci[-1] == "..":
        return None
    if czesci[-2] not in {nazwa for nazwa, _ in _foldery_zalacznikow()}:
        return None
    return czesci[-2], czesci[-1]


def wzgledna_sciezka_zalacznika(sciezka):
    """Postać do zapisu w bazie: 'zalaczniki/<nazwa>' albo 'kosz_zalaczniki/<nazwa>'.

    Działa tak samo dla ścieżki tutejszej, przywiezionej z innego urządzenia
    i już względnej. Ścieżkę spoza folderów aplikacji oddaje bez zmian, pustą też."""
    if not sciezka:
        return sciezka
    para = _folder_i_nazwa(sciezka)
    return f"{para[0]}/{para[1]}" if para else sciezka


def pelna_sciezka_zalacznika(zapisana) -> str | None:
    """Ścieżka na dysku dla wartości z bazy, BEZ szukania pliku.

    Względną skleja ze STORAGE_PATH tego urządzenia, bezwzględną (dawny zapis)
    oddaje bez zmian. Mówi, gdzie wpis każe szukać — nie, gdzie plik jest."""
    if not zapisana:
        return None
    tekst = _z_ukosnikami(zapisana)
    if _czy_bezwzgledna(tekst):
        return str(zapisana)
    return os.path.join(STORAGE_PATH, *[c for c in tekst.split("/") if c not in ("", ".")])


def sciezka_pliku_zalacznika(zapisana) -> str | None:
    """Ścieżka pliku z wartości w bazie. Najpierw pelna_sciezka_zalacznika; gdy pliku
    brak, a wpis wskazuje folder aplikacji — ta sama nazwa (UUID) w tutejszym folderze,
    potem w drugim (załączniki / kosz). Spoza folderów aplikacji nie szuka; nie
    znaleziony → ścieżka pełna (komunikat mówi, co stoi w bazie)."""
    pelna = pelna_sciezka_zalacznika(zapisana)
    if not pelna or os.path.exists(pelna):
        return pelna
    para = _folder_i_nazwa(zapisana)
    if para:
        foldery = sorted(_foldery_zalacznikow(), key=lambda f: f[0] != para[0])
        for _, folder in foldery:
            kandydat = os.path.join(folder, para[1])
            if os.path.isfile(kandydat):
                return kandydat
    return pelna


def napraw_sciezki_zalacznikow() -> tuple[int, int]:
    """Przepisuje nieaktualne ścieżki załączników (np. z kopii z telefonu) na tutejsze;
    zwraca (naprawione, brakujace). Wpis trafiający w plik zostaje; znaleziony przez
    sciezka_pliku_zalacznika dostaje postać względną; nieznaleziony NIE jest ruszany."""
    naprawione = 0
    brakujace = 0

    with polacz_baze() as conn:
        c = conn.cursor()
        for tabela, kolumna in KOLUMNY_ZE_SCIEZKAMI:
            try:
                c.execute(f"PRAGMA table_info({tabela})")
                if kolumna not in [r[1] for r in c.fetchall()]:
                    continue
                c.execute(
                    f"SELECT id, {kolumna} FROM {tabela} "
                    f"WHERE {kolumna} IS NOT NULL AND TRIM({kolumna}) <> ''"
                )
                wiersze = c.fetchall()
            except Exception:
                continue  # brak tabeli w starszej bazie — nie ma czego naprawiać

            for rekord_id, zapisana in wiersze:
                if os.path.exists(pelna_sciezka_zalacznika(zapisana) or ""):
                    continue
                tutejsza = sciezka_pliku_zalacznika(zapisana)
                if not tutejsza or not os.path.exists(tutejsza):
                    brakujace += 1
                    continue
                conn.execute(
                    f"UPDATE {tabela} SET {kolumna}=? WHERE id=?",
                    (wzgledna_sciezka_zalacznika(tutejsza), rekord_id)
                )
                naprawione += 1

    return naprawione, brakujace


def _upewnij_folder_odroczonych():
    os.makedirs(FOLDER_ODROCZONE, exist_ok=True)
    return FOLDER_ODROCZONE


def posprzataj_odroczone_zalaczniki(starsze_niz_sekundy=3600):
    """Usuwa pliki z folderu odroczonego, które zalegają dłużej niż określony czas."""
    folder = _upewnij_folder_odroczonych()
    try:
        obecny_czas = time.time()
        for nazwa_pliku in os.listdir(folder):
            sciezka = os.path.join(folder, nazwa_pliku)
            if os.path.isfile(sciezka):
                czas_modyfikacji = os.path.getmtime(sciezka)
                # Jeśli plik leży dłużej niż godzina (nagłe zamknięcie aplikacji)
                if (obecny_czas - czas_modyfikacji) > starsze_niz_sekundy:
                    try:
                        os.remove(sciezka)
                    except Exception:
                        pass
    except Exception:
        pass


def _upewnij_folder_zalacznikow():
    os.makedirs(FOLDER_ZALACZNIKI, exist_ok=True)
    return FOLDER_ZALACZNIKI


def zapisz_zalacznik(sciezka_zrodlowa):
    if not sciezka_zrodlowa or not os.path.exists(sciezka_zrodlowa):
        return None
    folder = _upewnij_folder_zalacznikow()
    rozszerzenie = os.path.splitext(sciezka_zrodlowa)[1].lower()

    # Do bazy idzie postać względna (wzgledna_sciezka_zalacznika) — bezwzględna
    # z tego urządzenia nie istniałaby na innym po przeniesieniu kopii.
    # Jeśli to PDF, kopiujemy 1:1, bez zmiany rozszerzenia
    if rozszerzenie == ".pdf":
        nazwa = f"{uuid.uuid4().hex}.pdf"
        docelowa = os.path.join(folder, nazwa)
        shutil.copyfile(sciezka_zrodlowa, docelowa)
        return wzgledna_sciezka_zalacznika(docelowa)

    # Domyślnie traktujemy jako obraz – wymuszamy .jpg dla mniejszego rozmiaru
    nazwa = f"{uuid.uuid4().hex}.jpg"
    docelowa = os.path.join(folder, nazwa)
    
    if Image is not None:
        try:
            with Image.open(sciezka_zrodlowa) as img:
                # Korekta orientacji z tagu EXIF Orientation — PIL nie stosuje jej sam,
                # więc bez niej zdjęcie zostaje „położone”.
                img = ImageOps.exif_transpose(img)

                # JPEG zna tylko RGB i skalę szarości. Wcześniej zamieniane były
                # wyłącznie RGBA i P, więc PNG w szarości z przezroczystością (LA),
                # 16-bitowy albo CMYK wywracał zapis i szedł do fallbacku —
                # czyli kopiował się bajt w bajt jako plik PNG z końcówką .jpg.
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")
                
                # Zmniejszenie rozdzielczości, jeśli zdjęcie jest za szerokie
                max_szerokosc = 1600
                if img.width > max_szerokosc:
                    proporcja = max_szerokosc / float(img.width)
                    nowa_wysokosc = int(float(img.height) * float(proporcja))
                    img = img.resize((max_szerokosc, nowa_wysokosc), Image.Resampling.LANCZOS)
                
                img.save(docelowa, "JPEG", quality=85)
            return wzgledna_sciezka_zalacznika(docelowa)
        except Exception:
            pass # W razie problemów z PIL przejdzie do fallbacka poniżej

    # Fallback, jeśli obraz nie dał się skompresować lub brak biblioteki
    shutil.copyfile(sciezka_zrodlowa, docelowa)
    return wzgledna_sciezka_zalacznika(docelowa)


def usun_plik_zalacznika(sciezka_wzgledna):
    if not sciezka_wzgledna:
        return
    try:
        sciezka = sciezka_pliku_zalacznika(sciezka_wzgledna)
        if os.path.exists(sciezka):
            os.remove(sciezka)
    except Exception:
        pass


# Dwuetapowy, bezpieczny zapis załącznika: "przygotuj" (zapisz nowy plik, NIE ruszaj
# starego) + "zatwierdź" (dopiero po udanym zapisie do bazy kasuje stary plik).
# Błąd zapisu do bazy nie kasuje już poprawnego, starego załącznika.
def przygotuj_nowy_zalacznik(wynik_komponentu):
    if wynik_komponentu is None:
        return None
    if wynik_komponentu == "":
        return ""
    return zapisz_zalacznik(wynik_komponentu)


def zatwierdz_zalacznik(stara_sciezka, przygotowany):
    if przygotowany is None:
        return stara_sciezka
    usun_plik_zalacznika(stara_sciezka)
    return przygotowany or None


def anuluj_nowy_zalacznik(przygotowany):
    if przygotowany:
        usun_plik_zalacznika(przygotowany)


# ---------------------------------------------------------------- wiele plików na wpis
# Tabela `zalaczniki` (N-05): (tabela, rekord_id) wskazuje wpis z TABELE_Z_WIELOMA_ZALACZNIKAMI,
# `auto_id` wiezie pojazd (kosz, kaskada), `kolejnosc` to porządek z formularza. Lokalna
# jak same pliki (N-06), więc rekord_id to tutejsze id wpisu.

RODZAJE_ZALACZNIKOW = {
    "paragon": "Paragon",
    "faktura": "Faktura",
    "gwarancja": "Karta gwarancyjna",
    "zdjecie_czesci": "Zdjęcie części",
    "zdjecie": "Zdjęcie",
    "inne": "Inny plik",
}

# Plik dokumentu ze skarbca — strona skanu, bez rodzaju do wyboru.
TYP_PLIKU_DOKUMENTU = "dokument"

_KOLUMNY_ZALACZNIKA = ("id", "auto_id", "tabela", "rekord_id", "sciezka", "typ", "opis", "kolejnosc")


def czy_pdf(sciezka) -> bool:
    return str(sciezka or "").lower().endswith(".pdf")


def typ_dla_pliku(sciezka, obecne=()) -> str:
    """Podpowiedź rodzaju nowego pliku wpisu: PDF to faktura, pierwsze zdjęcie paragon, kolejne — zdjęcie."""
    if czy_pdf(sciezka):
        return "faktura"
    return "zdjecie" if {"paragon", "faktura"} & set(obecne) else "paragon"


def _jako_slownik(wiersz) -> dict[str, Any]:
    return dict(zip(_KOLUMNY_ZALACZNIKA, wiersz))


def _auto_rekordu(conn, tabela, rekord_id):
    if tabela == "historia":
        w = conn.execute("SELECT z.auto_id FROM historia h JOIN zadania z ON z.id = h.zadanie_id "
                         "WHERE h.id=?", (rekord_id,)).fetchone()
    else:
        w = conn.execute(f"SELECT auto_id FROM {tabela} WHERE id=?", (rekord_id,)).fetchone()
    return w[0] if w else None


def _policz_pliki_dokumentu(conn, tabela, rekord_id):
    """Dokument skarbca jedzie do chmury bez plików — ich liczba mówi drugiej osobie, że plik jest gdzie indziej."""
    if tabela == "dokumenty_pojazdu":
        conn.execute("UPDATE dokumenty_pojazdu SET liczba_plikow=(SELECT COUNT(*) FROM zalaczniki "
                     "WHERE tabela='dokumenty_pojazdu' AND rekord_id=?) WHERE id=?", (rekord_id, rekord_id))


def pobierz_zalaczniki(tabela, rekord_id) -> list[dict[str, Any]]:
    """Pliki wpisu w kolejności z formularza; słowniki z kolumnami tabeli `zalaczniki`."""
    if not rekord_id:
        return []
    with polacz_baze() as conn:
        wiersze = conn.execute(
            f"SELECT {', '.join(_KOLUMNY_ZALACZNIKA)} FROM zalaczniki WHERE tabela=? AND rekord_id=? "
            "ORDER BY kolejnosc, id", (tabela, rekord_id)).fetchall()
    return [_jako_slownik(w) for w in wiersze]


def zalaczniki_pojazdu(auto_id, tabela) -> dict[int, list[dict[str, Any]]]:
    """{rekord_id: [plik…]} całej listy ekranu jednym zapytaniem, zamiast jednego na kartę."""
    wynik = {}
    if not auto_id:
        return wynik
    with polacz_baze() as conn:
        wiersze = conn.execute(
            f"SELECT {', '.join(_KOLUMNY_ZALACZNIKA)} FROM zalaczniki WHERE auto_id=? AND tabela=? "
            "ORDER BY rekord_id, kolejnosc, id", (auto_id, tabela)).fetchall()
    for w in wiersze:
        z = _jako_slownik(w)
        wynik.setdefault(z["rekord_id"], []).append(z)
    return wynik


def zapisz_zalaczniki_rekordu(conn, tabela, rekord_id, auto_id, pozycje) -> list[str]:
    """Ustawia pliki wpisu na `pozycje` (id albo None, sciezka w postaci z bazy, typ, opis) w tej
    kolejności, w transakcji formularza. Zwraca ścieżki usuniętych wierszy — pliki do skasowania
    dopiero PO zatwierdzeniu."""
    stare = dict(conn.execute("SELECT id, sciezka FROM zalaczniki WHERE tabela=? AND rekord_id=?",
                              (tabela, rekord_id)).fetchall())
    zostaja = set()
    for kolejnosc, p in enumerate(pozycje):
        opis = (p.get("opis") or "").strip() or None
        if p.get("id") in stare:
            conn.execute("UPDATE zalaczniki SET typ=?, opis=?, kolejnosc=? WHERE id=?",
                         (p.get("typ"), opis, kolejnosc, p["id"]))
            zostaja.add(p["id"])
        else:
            conn.execute(
                "INSERT INTO zalaczniki (auto_id, tabela, rekord_id, sciezka, typ, opis, kolejnosc) "
                "VALUES (?,?,?,?,?,?,?)", (auto_id, tabela, rekord_id, p["sciezka"], p.get("typ"), opis, kolejnosc))
    usuniete = [i for i in stare if i not in zostaja]
    for i in usuniete:
        conn.execute("DELETE FROM zalaczniki WHERE id=?", (i,))
    if usuniete or len(zostaja) < len(pozycje):
        _policz_pliki_dokumentu(conn, tabela, rekord_id)
    return [stare[i] for i in usuniete]


def dodaj_zalaczniki(tabela, rekord_id, sciezki_zrodlowe) -> int:
    """Dopisuje pliki na koniec wpisu („Dodaj plik” z listy); zwraca, ile się zapisało."""
    if tabela not in TABELE_Z_WIELOMA_ZALACZNIKAMI or not rekord_id:
        return 0
    nowe = [z for z in (zapisz_zalacznik(s) for s in sciezki_zrodlowe or []) if z]
    if not nowe:
        return 0
    auto_id = None
    try:
        with polacz_baze() as conn:
            auto_id = _auto_rekordu(conn, tabela, rekord_id)
            if auto_id is not None:
                wiersze = conn.execute("SELECT typ, kolejnosc FROM zalaczniki WHERE tabela=? AND rekord_id=?",
                                       (tabela, rekord_id)).fetchall()
                typy = [w[0] for w in wiersze]
                nastepna = max((w[1] for w in wiersze), default=-1) + 1
                for i, sciezka in enumerate(nowe):
                    typ = TYP_PLIKU_DOKUMENTU if tabela == "dokumenty_pojazdu" else typ_dla_pliku(sciezka, typy)
                    typy.append(typ)
                    conn.execute("INSERT INTO zalaczniki (auto_id, tabela, rekord_id, sciezka, typ, kolejnosc) "
                                 "VALUES (?,?,?,?,?,?)", (auto_id, tabela, rekord_id, sciezka, typ, nastepna + i))
                _policz_pliki_dokumentu(conn, tabela, rekord_id)
    finally:
        if auto_id is None:
            for sciezka in nowe:
                usun_plik_zalacznika(sciezka)
    return len(nowe) if auto_id is not None else 0


def odloz_zalaczniki_rekordow(tabela, ids) -> dict[str, Any]:
    """Przed usunięciem wpisów z „Cofnij”: wiersze plików znikają z bazy, pliki czekają w folderze
    odroczonych. Paczka idzie do `przywroc_odlozone_zalaczniki` albo `skasuj_odlozone_zalaczniki`."""
    paczka = {"wiersze": [], "pliki": []}
    ids = [i for i in ids or [] if i is not None]
    if tabela not in TABELE_Z_WIELOMA_ZALACZNIKAMI or not ids:
        return paczka
    with polacz_baze() as conn:
        for rekord_id in ids:
            wiersze = conn.execute(
                f"SELECT {', '.join(_KOLUMNY_ZALACZNIKA)} FROM zalaczniki WHERE tabela=? AND rekord_id=? "
                "ORDER BY kolejnosc, id", (tabela, rekord_id)).fetchall()
            paczka["wiersze"] += [_jako_slownik(w) for w in wiersze]
            conn.execute("DELETE FROM zalaczniki WHERE tabela=? AND rekord_id=?", (tabela, rekord_id))
    for w in paczka["wiersze"]:
        oryginalna = sciezka_pliku_zalacznika(w["sciezka"])
        if not oryginalna or not os.path.exists(oryginalna):
            continue
        tmp = os.path.join(_upewnij_folder_odroczonych(), f"z_{uuid.uuid4().hex}_{os.path.basename(oryginalna)}")
        try:
            shutil.move(oryginalna, tmp)
            paczka["pliki"].append((tmp, oryginalna))
        except OSError:
            log.polkniety("odłożenie pliku usuwanego wpisu")
    return paczka


def przywroc_odlozone_zalaczniki(paczka, mapa_id=None):
    """„Cofnij”: pliki wracają na miejsce, wiersze — przy wpisie o id z `mapa_id` (usuwanie
    z cofnięciem wstawia wpis od nowa, często z nowym id)."""
    for tmp, oryginalna in paczka.get("pliki") or []:
        if os.path.exists(tmp):
            try:
                shutil.move(tmp, oryginalna)
            except OSError:
                log.polkniety("powrót pliku wpisu po cofnięciu")
    wiersze = paczka.get("wiersze") or []
    if not wiersze:
        return
    mapa_id = mapa_id or {}
    with polacz_baze() as conn:
        for w in wiersze:
            conn.execute(
                "INSERT INTO zalaczniki (auto_id, tabela, rekord_id, sciezka, typ, opis, kolejnosc) VALUES (?,?,?,?,?,?,?)",
                (w["auto_id"], w["tabela"], mapa_id.get(w["rekord_id"], w["rekord_id"]), w["sciezka"], w["typ"],
                 w["opis"], w["kolejnosc"]))


def skasuj_odlozone_zalaczniki(paczka):
    """Po oknie na cofnięcie — pliki odłożone przez `odloz_zalaczniki_rekordow` znikają z dysku."""
    for tmp, _ in paczka.get("pliki") or []:
        usun_plik_zalacznika(tmp)


def usun_zalaczniki_rekordow(conn, tabela, ids) -> list[str]:
    """Wiersze plików usuwanych wpisów, w transakcji wołającego (wpis usunięty na drugim
    telefonie). Zwraca zapisane ścieżki — pliki kasuje wołający PO zatwierdzeniu."""
    sciezki = []
    if tabela not in TABELE_Z_WIELOMA_ZALACZNIKAMI:
        return sciezki
    for rekord_id in ids or []:
        sciezki += [w[0] for w in conn.execute("SELECT sciezka FROM zalaczniki WHERE tabela=? AND rekord_id=?",
                                               (tabela, rekord_id)).fetchall()]
        conn.execute("DELETE FROM zalaczniki WHERE tabela=? AND rekord_id=?", (tabela, rekord_id))
    return sciezki


def _plik_w_uzyciu(conn, sciezka) -> bool:
    return any(conn.execute(f"SELECT 1 FROM {t} WHERE {k}=? LIMIT 1", (sciezka,)).fetchone()
               for t, k in KOLUMNY_ZE_SCIEZKAMI)


def posprzataj_osierocone_zalaczniki() -> int:
    """Pliki wpisów, których już nie ma (usunięte na drugim telefonie, kaskada po podzespole):
    wiersz znika, plik też, chyba że wskazuje go coś jeszcze. Zwraca liczbę wierszy."""
    do_skasowania = []
    with polacz_baze() as conn:
        for tabela in TABELE_Z_WIELOMA_ZALACZNIKAMI:
            warunek = f"tabela=? AND rekord_id NOT IN (SELECT id FROM {tabela})"
            sieroty = [w[0] for w in conn.execute(f"SELECT sciezka FROM zalaczniki WHERE {warunek}",
                                                  (tabela,)).fetchall()]
            if sieroty:
                conn.execute(f"DELETE FROM zalaczniki WHERE {warunek}", (tabela,))
                do_skasowania += sieroty
        pliki = [s for s in do_skasowania if not _plik_w_uzyciu(conn, s)]
    for sciezka in pliki:
        usun_plik_zalacznika(sciezka)
    return len(do_skasowania)


def dopisz_dawny_zalacznik(conn, auto_id, tabela, rekord_id, sciezka) -> bool:
    """Wartość dawnej kolumny `zalacznik` jako pierwszy plik wpisu (migracja 51, stara migawka kosza)."""
    if not str(sciezka or "").strip() or auto_id is None:
        return False
    conn.execute("INSERT INTO zalaczniki (auto_id, tabela, rekord_id, sciezka, typ, kolejnosc) VALUES (?,?,?,?,?,0)",
                 (auto_id, tabela, rekord_id, sciezka, typ_dla_pliku(sciezka)))
    return True


def przenies_dawne_zalaczniki(conn) -> int:
    """Migracja 51: kolumna `zalacznik` wpisów przechodzi do `zalaczniki` i zostaje pusta. Zwraca liczbę plików."""
    przeniesione = 0
    for tabela in TABELE_DAWNEGO_ZALACZNIKA:
        auto = "(SELECT z.auto_id FROM zadania z WHERE z.id = t.zadanie_id)" if tabela == "historia" else "t.auto_id"
        wiersze = conn.execute(f"SELECT t.id, {auto}, t.zalacznik FROM {tabela} t "
                               "WHERE TRIM(COALESCE(t.zalacznik, '')) <> ''").fetchall()
        for rekord_id, auto_id, sciezka in wiersze:
            if dopisz_dawny_zalacznik(conn, auto_id, tabela, rekord_id, sciezka):
                conn.execute(f"UPDATE {tabela} SET zalacznik=NULL WHERE id=?", (rekord_id,))
                przeniesione += 1
    return przeniesione


__all__ = [
    "KOLUMNY_ZE_SCIEZKAMI",
    "RODZAJE_ZALACZNIKOW",
    "TYP_PLIKU_DOKUMENTU",
    "_upewnij_folder_odroczonych",
    "_upewnij_folder_zalacznikow",
    "anuluj_nowy_zalacznik",
    "czy_pdf",
    "dodaj_zalaczniki",
    "dopisz_dawny_zalacznik",
    "napraw_sciezki_zalacznikow",
    "odloz_zalaczniki_rekordow",
    "pelna_sciezka_zalacznika",
    "pobierz_zalaczniki",
    "posprzataj_odroczone_zalaczniki",
    "posprzataj_osierocone_zalaczniki",
    "przenies_dawne_zalaczniki",
    "przygotuj_nowy_zalacznik",
    "przywroc_odlozone_zalaczniki",
    "sciezka_pliku_zalacznika",
    "skasuj_odlozone_zalaczniki",
    "typ_dla_pliku",
    "usun_plik_zalacznika",
    "usun_zalaczniki_rekordow",
    "wzgledna_sciezka_zalacznika",
    "zalaczniki_pojazdu",
    "zapisz_zalacznik",
    "zapisz_zalaczniki_rekordu",
    "zatwierdz_zalacznik",
]
