"""Rejestr karoserii: zdjęcia auta według strefy, pary „przed / po naprawie” i obchód
aparatem. Tabela `zdjecia_karoserii` jest lokalna (zdjęcia nie jadą do chmury, N-06);
kosz i plik pojazdu zabierają ją razem z plikami (`TABELE_Z_ZALACZNIKIEM`)."""

import os
import sqlite3
import uuid
from datetime import datetime

import log
from date import na_iso

from .polaczenie import polacz_baze
from .stale import STREFY_KAROSERII, TYPY_ZDJECIA
from .zalaczniki import _upewnij_folder_odroczonych, usun_plik_zalacznika, zapisz_zalacznik

# Wartości kolumny `typ_porownania`; NULL ze starych wpisów to zwykłe zdjęcie.
TYP_ZDJECIA_ZWYKLE, TYP_ZDJECIA_PRZED, TYP_ZDJECIA_PO = TYPY_ZDJECIA
ETYKIETY_TYPOW_ZDJECIA = {
    TYP_ZDJECIA_ZWYKLE: "Zwykłe",
    TYP_ZDJECIA_PRZED: "Przed naprawą",
    TYP_ZDJECIA_PO: "Po naprawie",
}
# Obchód z aparatem: od przodu zgodnie z ruchem wskazówek zegara, wnętrze na koniec.
STREFY_OBCHODU = ("Przód", "Bok prawy", "Tył", "Bok lewy", "Wnętrze / Kokpit")
STREFA_DOMYSLNA = "Inne"

_KOLUMNY = ("id", "data", "data_iso", "strefa", "zalacznik", "typ", "opis", "przebieg")


def typ_zdjecia(wartosc) -> str:
    """Rodzaj zdjęcia z bazy: NULL i wartość spoza słownika to zwykłe zdjęcie."""
    return wartosc if wartosc in TYPY_ZDJECIA else TYP_ZDJECIA_ZWYKLE


def _porzadek(data_iso):
    """RRRR-MM-DD jako liczba do sortowania; zdjęcie bez czytelnej daty idzie na koniec osi."""
    try:
        return int(str(data_iso).replace("-", ""))
    except (TypeError, ValueError):
        return 0


def zdjecia_karoserii_pojazdu(auto_id) -> list[dict]:
    """Zdjęcia auta od najnowszego (data, potem kolejność dodania); `typ` sprowadzony do
    `TYPY_ZDJECIA`, `porzadek` do sortowania, `szukaj` dla pola wyszukiwania."""
    if not auto_id:
        return []
    with polacz_baze() as conn:
        wiersze = conn.execute(
            "SELECT id, data, data_iso, strefa, zalacznik, typ_porownania, opis, przebieg "
            "FROM zdjecia_karoserii WHERE auto_id=? ORDER BY data_iso DESC, id DESC", (auto_id,),
        ).fetchall()
    zdjecia = []
    for wiersz in wiersze:
        z = dict(zip(_KOLUMNY, wiersz))
        z["typ"] = typ_zdjecia(z["typ"])
        z["etykieta_typu"] = ETYKIETY_TYPOW_ZDJECIA[z["typ"]]
        z["strefa"] = str(z["strefa"] or STREFA_DOMYSLNA)
        z["data"] = str(z["data"] or "")
        z["opis"] = str(z["opis"] or "")
        z["porzadek"] = _porzadek(z["data_iso"])
        z["szukaj"] = " ".join((z["strefa"], z["opis"], z["etykieta_typu"], z["data"])).lower()
        zdjecia.append(z)
    return zdjecia


def podsumowanie_stref(zdjecia) -> dict:
    """{strefa: {"liczba", "ostatnia"}} — każda strefa słownika (także bez zdjęć) i strefy
    spoza niego, które są w danych; `ostatnia` to data najnowszego zdjęcia strefy."""
    wynik = {strefa: {"liczba": 0, "ostatnia": None} for strefa in STREFY_KAROSERII}
    najnowsze = {}
    for z in zdjecia:
        strefa = wynik.setdefault(z["strefa"], {"liczba": 0, "ostatnia": None})
        strefa["liczba"] += 1
        if z["strefa"] not in najnowsze or z["porzadek"] > najnowsze[z["strefa"]]:
            najnowsze[z["strefa"]] = z["porzadek"]
            strefa["ostatnia"] = z["data"] or None
    return wynik


def pary_przed_po(zdjecia) -> list[dict]:
    """Pary {strefa, przed, po}: zdjęcie „po naprawie” bierze najpóźniejsze wolne „przed
    naprawą” tej samej strefy sprzed siebie (ten sam dzień też). Od najnowszej naprawy."""
    pary, czekajace = [], {}
    for z in sorted(zdjecia, key=lambda z: (z["porzadek"], z["id"])):
        if z["typ"] == TYP_ZDJECIA_PRZED:
            czekajace.setdefault(z["strefa"], []).append(z)
        elif z["typ"] == TYP_ZDJECIA_PO and czekajace.get(z["strefa"]):
            pary.append({"strefa": z["strefa"], "przed": czekajace[z["strefa"]].pop(), "po": z})
    pary.sort(key=lambda p: (p["po"]["porzadek"], p["po"]["id"]), reverse=True)
    return pary


def dodaj_zdjecie_karoserii(auto_id, sciezka_zdjecia, strefa, typ=None, opis=None, kiedy=None,
                            przebieg=None) -> int | None:
    """Zapisuje zdjęcie do załączników (obrót z EXIF i zmniejszenie — `zapisz_zalacznik`) i
    dodaje je do rejestru z datą `kiedy` (bez niej — dziś). Zwraca id wpisu albo None."""
    if not auto_id:
        return None
    zalacznik = zapisz_zalacznik(sciezka_zdjecia)
    if not zalacznik:
        return None
    data = (kiedy or datetime.now()).strftime("%d.%m.%Y")
    try:
        with polacz_baze() as conn:
            kursor = conn.execute(
                "INSERT INTO zdjecia_karoserii (auto_id, data, data_iso, strefa, zalacznik, opis, przebieg, "
                "typ_porownania) VALUES (?,?,?,?,?,?,?,?)",
                (auto_id, data, na_iso(data), strefa if strefa in STREFY_KAROSERII else STREFA_DOMYSLNA,
                 zalacznik, " ".join(str(opis or "").split()), przebieg or None, typ_zdjecia(typ)),
            )
            return kursor.lastrowid
    except sqlite3.Error:
        # Plik bez wpisu byłby sierotą w folderze załączników.
        usun_plik_zalacznika(zalacznik)
        raise


def dodaj_zdjecie_karoserii_z_bajtow(auto_id, dane, strefa, typ=None, przebieg=None,
                                     rozszerzenie=".jpg") -> int | None:
    """Zdjęcie prosto z aparatu (flet-camera oddaje zakodowany JPEG). Plik pośredni leży w
    folderze odroczonych — po awarii w środku posprząta go `posprzataj_odroczone_zalaczniki`."""
    if not auto_id or not dane:
        return None
    sciezka = os.path.join(_upewnij_folder_odroczonych(), f"obchod_{uuid.uuid4().hex}{rozszerzenie}")
    with open(sciezka, "wb") as plik:
        plik.write(bytes(dane))
    try:
        return dodaj_zdjecie_karoserii(auto_id, sciezka, strefa, typ=typ, przebieg=przebieg)
    finally:
        try:
            os.remove(sciezka)
        except OSError:
            log.polkniety("sprzątanie pliku pośredniego obchodu karoserii")


__all__ = [
    "ETYKIETY_TYPOW_ZDJECIA",
    "STREFA_DOMYSLNA",
    "STREFY_OBCHODU",
    "TYP_ZDJECIA_PO",
    "TYP_ZDJECIA_PRZED",
    "TYP_ZDJECIA_ZWYKLE",
    "dodaj_zdjecie_karoserii",
    "dodaj_zdjecie_karoserii_z_bajtow",
    "pary_przed_po",
    "podsumowanie_stref",
    "typ_zdjecia",
    "zdjecia_karoserii_pojazdu",
]
