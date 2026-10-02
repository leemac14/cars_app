"""Manifest kopii zapasowej i podgląd archiwum, zanim cokolwiek zostanie nadpisane."""

import hashlib
import json
import os
import pathlib
import sqlite3
import tempfile
import zipfile
from datetime import datetime

import log

from .stale import BAZA_DANYCH, FOLDER_KOSZ, FOLDER_ZALACZNIKI, TABELE_Z_DATA_ISO
from .pomocnicze import SEPARATOR_TYSIECY, formatuj_rozmiar, liczba_na_tekst, liczba_z_odmiana
from .kosz import KOSZ_TABELE_LICZONE, KOSZ_ZAPYTANIA_POSREDNIE
from .migracje import sprawdz_kopie_przed_wczytaniem, wersja_schematu_aplikacji, wersja_schematu_pliku


# ============================================================================
#  MANIFEST KOPII ZAPASOWEJ
# ============================================================================
# Wczytanie kopii było skokiem w ciemno: nie widać, z którego dnia jest plik,
# ile w nim pracy ani czy po drodze nic się nie stało. Archiwum dostaje więc
# `manifest.json` — wersję schematu, liczbę wpisów, sumę kontrolną bazy i bilans
# załączników — a import pokazuje to, zanim ruszy cokolwiek na dysku.
#
# Manifest dopisuje `zapisz_archiwum_kopii` (db/kopie.py) — to jedno miejsce, w którym
# powstaje archiwum kopii ręcznej i automatycznej, więc obie go mają.
#
# Podgląd NIE czyta liczb z manifestu. Liczy je z samej bazy w archiwum, więc
# działa tak samo dla kopii zrobionych przed manifestem i dla gołych plików .db.
# Manifest służy do sprawdzenia, czy to, co leży w środku, jest tym, co eksport
# zapisał — a nie do opisywania zawartości.

NAZWA_MANIFESTU = "manifest.json"
FORMAT_MANIFESTU = 1

# Foldery z plikami po NAZWIE — tak pakuje je eksport (main.py: FOLDERY_KOPII),
# niezależnie od tego, gdzie leżą na urządzeniu.
_FOLDERY_ZALACZNIKOW = (os.path.basename(FOLDER_ZALACZNIKI), os.path.basename(FOLDER_KOSZ))

_KAWALEK = 1024 * 1024
_MAKS_ROZMIAR_MANIFESTU = 1024 * 1024


class _KopiaNieDoOdczytu(Exception):
    """Powód (po polsku), dla którego nie da się zajrzeć do kopii."""


def _tysiace(liczba):
    return liczba_na_tekst(liczba, 0, SEPARATOR_TYSIECY)


def _suma_sha256(strumien):
    skrot = hashlib.sha256()
    for kawalek in iter(lambda: strumien.read(_KAWALEK), b""):
        skrot.update(kawalek)
    return skrot.hexdigest()


def _otworz_do_odczytu(sciezka):
    """Tak samo jak `wersja_schematu_pliku`: plik, który tylko oglądamy, nie ma
    prawa się przy tym zmienić ani powstać."""
    adres = pathlib.Path(sciezka).resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(adres, uri=True)


def _zapytaj(polaczenie, sql, parametry=()):
    """Wiersze zapytania albo None, gdy kopia pochodzi ze schematu, który nie ma
    jeszcze użytej tabeli czy kolumny. Starsza kopia dociąga się drabinką migracji,
    więc brak kolumny w niej to nie błąd — inne błędy (blokada, uszkodzony plik)
    lecą dalej."""
    try:
        return polaczenie.execute(sql, parametry).fetchall()
    except sqlite3.OperationalError as ex:
        if str(ex).startswith("no such"):
            return None
        raise


def _liczba(polaczenie, sql, parametry=()):
    wiersze = _zapytaj(polaczenie, sql, parametry)
    return int(wiersze[0][0] or 0) if wiersze else 0


def _wpisy_pojazdu(polaczenie, auto_id):
    """Wpisy jednego pojazdu — tym samym kluczem, którym liczy je kosz (tabele
    z KOSZ_TABELE_LICZONE; `historia` nie ma auto_id, więc idzie zapytaniem
    pośrednim z kosza)."""
    razem = 0
    for tabela in KOSZ_TABELE_LICZONE:
        if tabela in KOSZ_ZAPYTANIA_POSREDNIE:
            sql = f"SELECT COUNT(*) FROM ({KOSZ_ZAPYTANIA_POSREDNIE[tabela]})"
        else:
            sql = f"SELECT COUNT(*) FROM {tabela} WHERE auto_id=?"
        razem += _liczba(polaczenie, sql, (auto_id,))
    return razem


def podsumowanie_bazy(sciezka) -> dict | None:
    """Co leży w pliku bazy: schemat, wpisy (razem i wg tabel), pojazdy z liczbą
    wpisów i data ostatniego wpisu. None = plik nie do odczytania.

    „Wpis” znaczy to samo co w koszu (KOSZ_TABELE_LICZONE): historia pracy, nie
    konfiguracja — tagi, warsztaty i pakiety nie zawyżają liczby, którą człowiek
    czyta jako „tyle mojego czasu tu leży”. Plik otwieramy tylko do odczytu."""
    try:
        polaczenie = _otworz_do_odczytu(sciezka)
    except (sqlite3.Error, ValueError, OSError):
        return None

    try:
        wg_tabel = {t: _liczba(polaczenie, f"SELECT COUNT(*) FROM {t}") for t in KOSZ_TABELE_LICZONE}

        pojazdy = []
        for auto_id, nazwa in _zapytaj(polaczenie, "SELECT id, nazwa FROM samochody ORDER BY id") or []:
            pojazdy.append({"nazwa": nazwa or "", "wpisy": _wpisy_pojazdu(polaczenie, auto_id)})

        # `data_iso` sortuje się tekstowo, więc MAX działa bez parsowania. Stara
        # kopia (schemat sprzed kolumny) po prostu nie da daty.
        daty = []
        for tabela in KOSZ_TABELE_LICZONE:
            if tabela in TABELE_Z_DATA_ISO:
                wiersze = _zapytaj(polaczenie, f"SELECT MAX(data_iso) FROM {tabela}")
                if wiersze and wiersze[0][0]:
                    daty.append(wiersze[0][0])
    except sqlite3.Error:
        return None
    finally:
        polaczenie.close()

    return {
        "schemat": wersja_schematu_pliku(sciezka),
        "wpisy": sum(wg_tabel.values()),
        "wpisy_wg_tabel": wg_tabel,
        "pojazdy": pojazdy,
        "ostatni_wpis": max(daty) if daty else None,
    }


def _zalaczniki_w_archiwum(archiwum):
    """{liczba, rozmiar} plików w folderach załączników archiwum — rozmiar
    z katalogu archiwum, bez czytania zdjęć. Tym samym kodem liczy eksport
    (po spakowaniu) i import (przed wczytaniem), więc oba bilanse muszą się
    zgadzać, o ile archiwum nikt nie ruszył."""
    liczba = rozmiar = 0
    for informacja in archiwum.infolist():
        if informacja.is_dir():
            continue
        folder = informacja.filename.replace("\\", "/").split("/", 1)[0]
        if folder in _FOLDERY_ZALACZNIKOW:
            liczba += 1
            rozmiar += informacja.file_size
    return {"liczba": liczba, "rozmiar": rozmiar}


def zbuduj_manifest_kopii(sciezka_bazy, zalaczniki=None) -> dict:
    """Manifest dla pliku bazy, który trafia do archiwum.

    `sciezka_bazy` to spójna kopia zrobiona przez SQLite backup (nie żywy plik),
    więc liczby i suma opisują dokładnie to, co leży w archiwum."""
    podsumowanie = podsumowanie_bazy(sciezka_bazy)
    if podsumowanie is None:
        raise ValueError("Kopia bazy do manifestu nie jest poprawną bazą SQLite.")

    with open(sciezka_bazy, "rb") as plik:
        suma = _suma_sha256(plik)

    return {
        "format": FORMAT_MANIFESTU,
        "utworzono": datetime.now().astimezone().isoformat(timespec="seconds"),
        "schemat": podsumowanie["schemat"],
        "baza": {
            "plik": os.path.basename(BAZA_DANYCH),
            "rozmiar": os.path.getsize(sciezka_bazy),
            "sha256": suma,
        },
        "wpisy": {"razem": podsumowanie["wpisy"], "wg_tabel": podsumowanie["wpisy_wg_tabel"]},
        "zalaczniki": zalaczniki or {"liczba": 0, "rozmiar": 0},
    }


def dopisz_manifest_kopii(archiwum, sciezka_bazy) -> dict | None:
    """Dopisuje `manifest.json` do archiwum, w którym leży już baza i foldery
    załączników (bilans załączników liczy się z tego, co faktycznie spakowano).

    Manifest to metadane o kopii, nie jej treść — jego błąd nie ma prawa
    zatrzymać kopii. Gdy nie da się go policzyć, wpis w logu i archiwum zostaje
    bez manifestu: wczytuje się dokładnie jak kopia sprzed tej zmiany. Zapis
    (writestr) jest już poza tą osłoną — brak miejsca na dysku to błąd kopii."""
    try:
        manifest = zbuduj_manifest_kopii(sciezka_bazy, _zalaczniki_w_archiwum(archiwum))
    except Exception:
        log.polkniety("manifest kopii zapasowej")
        return None
    archiwum.writestr(NAZWA_MANIFESTU, json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


# ============================================================================
#  SPRAWDZENIE I PODGLĄD
# ============================================================================


def _z_manifestu(manifest, *klucze):
    """Zagnieżdżona wartość manifestu albo None — manifest bywa niepełny,
    poprawiany ręcznie albo z innej wersji aplikacji."""
    wartosc = manifest
    for klucz in klucze:
        if not isinstance(wartosc, dict):
            return None
        wartosc = wartosc.get(klucz)
    return wartosc


def sprawdz_manifest(manifest, suma_bazy, podsumowanie, zalaczniki) -> list[str]:
    """Rozbieżności między manifestem a tym, co naprawdę leży w archiwum.
    Pusta lista = zgodne.

    Liczbę wpisów i schemat porównujemy WYŁĄCZNIE przy niezgodnej sumie, jako
    szczegół. Przy zgodnej sumie plik bazy jest bit w bit tym, który widział
    eksport, a rozbieżność liczb wynikałaby tylko z tego, że inna wersja
    aplikacji liczy wpisy po swojemu — czyli z fałszywego alarmu."""
    uwagi = []

    oczekiwana = _z_manifestu(manifest, "baza", "sha256")
    if isinstance(oczekiwana, str) and suma_bazy and oczekiwana.lower() != suma_bazy:
        uwagi.append(
            "Suma kontrolna bazy nie zgadza się z manifestem — plik bazy w archiwum "
            "został zmieniony albo uszkodzony po utworzeniu kopii."
        )
        zapisane_wpisy = _z_manifestu(manifest, "wpisy", "razem")
        if isinstance(zapisane_wpisy, int) and zapisane_wpisy != podsumowanie["wpisy"]:
            uwagi.append(
                f"Manifest zapisuje {liczba_z_odmiana(zapisane_wpisy, 'wpis', 'wpisy', 'wpisów')}, "
                f"a w bazie jest {liczba_z_odmiana(podsumowanie['wpisy'], 'wpis', 'wpisy', 'wpisów')}."
            )
        zapisany_schemat = _z_manifestu(manifest, "schemat")
        if (isinstance(zapisany_schemat, int) and podsumowanie["schemat"] is not None
                and zapisany_schemat != podsumowanie["schemat"]):
            uwagi.append(
                f"Manifest zapisuje schemat bazy {zapisany_schemat}, a baza ma {podsumowanie['schemat']}."
            )

    zapisane = _z_manifestu(manifest, "zalaczniki")
    if isinstance(zapisane, dict) and zalaczniki is not None:
        zapisana_liczba = zapisane.get("liczba")
        zapisany_rozmiar = zapisane.get("rozmiar")
        if isinstance(zapisana_liczba, int) and zalaczniki["liczba"] < zapisana_liczba:
            brakuje = zapisana_liczba - zalaczniki["liczba"]
            uwagi.append(
                f"W archiwum brakuje {liczba_z_odmiana(brakuje, 'załącznika', 'załączników', 'załączników')} — "
                f"manifest zapisuje ich {_tysiace(zapisana_liczba)}, a w archiwum jest {_tysiace(zalaczniki['liczba'])}."
            )
        elif isinstance(zapisany_rozmiar, int) and zalaczniki["rozmiar"] < zapisany_rozmiar:
            uwagi.append(
                f"Załączniki w archiwum zajmują mniej, niż zapisano w manifeście "
                f"({formatuj_rozmiar(zalaczniki['rozmiar'])} zamiast {formatuj_rozmiar(zapisany_rozmiar)}) — "
                "któryś plik może być obcięty."
            )

    return uwagi


def _wczytaj_manifest(archiwum):
    """(manifest, uszkodzony). Brak pliku to nie uszkodzenie, tylko kopia sprzed
    manifestu."""
    if NAZWA_MANIFESTU not in archiwum.namelist():
        return None, False
    try:
        if archiwum.getinfo(NAZWA_MANIFESTU).file_size > _MAKS_ROZMIAR_MANIFESTU:
            return None, True
        manifest = json.loads(archiwum.read(NAZWA_MANIFESTU).decode("utf-8"))
    except (ValueError, zipfile.BadZipFile):
        return None, True
    return (manifest, False) if isinstance(manifest, dict) else (None, True)


def _data_manifestu(manifest):
    tekst = _z_manifestu(manifest, "utworzono")
    try:
        datetime.fromisoformat(tekst)
    except (TypeError, ValueError):
        return None
    return tekst


def _wypakuj_baze(archiwum, nazwa_bazy, katalog):
    """Rozpakowuje SAM plik bazy i liczy jego SHA-256 w tym samym przebiegu.
    Błąd sumy CRC archiwum wychodzi tu jako BadZipFile — po ostatnim bajcie."""
    cel = os.path.join(katalog, nazwa_bazy)
    skrot = hashlib.sha256()
    with archiwum.open(nazwa_bazy) as zrodlo, open(cel, "wb") as plik:
        for kawalek in iter(lambda: zrodlo.read(_KAWALEK), b""):
            skrot.update(kawalek)
            plik.write(kawalek)
    return cel, skrot.hexdigest()


def _odczytaj_archiwum(podglad, sciezka, katalog):
    nazwa_bazy = os.path.basename(BAZA_DANYCH)
    with zipfile.ZipFile(sciezka, "r") as archiwum:
        if nazwa_bazy not in archiwum.namelist():
            raise _KopiaNieDoOdczytu("Archiwum nie zawiera pliku bazy danych.")

        manifest, manifest_uszkodzony = _wczytaj_manifest(archiwum)
        sciezka_bazy, suma = _wypakuj_baze(archiwum, nazwa_bazy, katalog)
        podglad["zalaczniki"] = _zalaczniki_w_archiwum(archiwum)

        data = _data_manifestu(manifest) if manifest is not None else None
        if data:
            podglad["utworzono"], podglad["data_z_manifestu"] = data, True
        else:
            # Kopia sprzed manifestu: eksport pakował świeżą migawkę bazy, więc
            # czas pliku w archiwum to praktycznie chwila wykonania kopii.
            try:
                podglad["utworzono"] = datetime(*archiwum.getinfo(nazwa_bazy).date_time).isoformat(timespec="seconds")
            except ValueError:
                podglad["utworzono"] = None

    # „Jest manifest” znaczy tu: jest z czym porównać sumę kontrolną. Manifest bez
    # niej (obca wersja, ręczna edycja) niczego nie potwierdza, więc okno nie może
    # pokazać zielonego „zgadza się”.
    podglad["manifest"] = isinstance(_z_manifestu(manifest, "baza", "sha256"), str)
    podsumowanie = _podsumowanie_do_podgladu(podglad, sciezka_bazy)

    if manifest_uszkodzony:
        podglad["uwagi"].append("Manifest w archiwum jest nieczytelny — nie da się sprawdzić sumy kontrolnej.")
    elif manifest is not None:
        podglad["uwagi"] += sprawdz_manifest(manifest, suma, podsumowanie, podglad["zalaczniki"])


def _odczytaj_plik_bazy(podglad, sciezka):
    # Goły plik .db (dawny format kopii): data to czas zapisu pliku.
    podglad["utworzono"] = datetime.fromtimestamp(os.path.getmtime(sciezka)).isoformat(timespec="seconds")
    _podsumowanie_do_podgladu(podglad, sciezka)


def _podsumowanie_do_podgladu(podglad, sciezka_bazy):
    podsumowanie = podsumowanie_bazy(sciezka_bazy)
    if podsumowanie is None:
        raise _KopiaNieDoOdczytu("Plik bazy danych w kopii nie jest poprawną bazą SQLite.")
    podglad.update(
        schemat=podsumowanie["schemat"],
        wpisy=podsumowanie["wpisy"],
        wpisy_wg_tabel=podsumowanie["wpisy_wg_tabel"],
        pojazdy=podsumowanie["pojazdy"],
        ostatni_wpis=podsumowanie["ostatni_wpis"],
    )
    return podsumowanie


def podglad_kopii(sciezka) -> dict:
    """Co jest w kopii, zanim import cokolwiek nadpisze. Nie rzuca wyjątków:
    nieczytelny plik wraca jako podgląd z `nieczytelna=True` i powodem w `uwagi`.

    Klucze: plik, rodzaj ("zip" albo "baza"), manifest (czy archiwum ma manifest
    z sumą kontrolną do porównania), utworzono (ISO) i data_z_manifestu
    (False = data z pliku), schemat
    i schemat_aplikacji, wpisy, wpisy_wg_tabel, pojazdy [{nazwa, wpisy}],
    ostatni_wpis (ISO), zalaczniki {liczba, rozmiar} (None dla gołego .db),
    obecna {wpisy, pojazdy} — stan bazy, którą import zastąpi, uwagi
    (niezgodności z manifestem, czerwone w oknie), odmowa (powód, gdy kopia jest
    z nowszej wersji aplikacji) i nieczytelna."""
    sciezka = str(sciezka)
    podglad = {
        "plik": os.path.basename(sciezka),
        "rodzaj": "zip" if sciezka.lower().endswith(".zip") else "baza",
        "manifest": False,
        "utworzono": None,
        "data_z_manifestu": False,
        "schemat": None,
        "schemat_aplikacji": wersja_schematu_aplikacji(),
        "wpisy": 0,
        "wpisy_wg_tabel": {},
        "pojazdy": [],
        "ostatni_wpis": None,
        "zalaczniki": None,
        "obecna": None,
        "uwagi": [],
        "odmowa": "",
        "nieczytelna": False,
    }

    powod = None
    try:
        with tempfile.TemporaryDirectory() as katalog:
            if podglad["rodzaj"] == "zip":
                _odczytaj_archiwum(podglad, sciezka, katalog)
            else:
                _odczytaj_plik_bazy(podglad, sciezka)
    except _KopiaNieDoOdczytu as ex:
        powod = str(ex)
    except zipfile.BadZipFile:
        powod = "Plik nie jest poprawnym archiwum ZIP albo jest uszkodzony."
    except Exception:
        log.polkniety("podgląd kopii zapasowej przed wczytaniem")
        powod = "Nie udało się odczytać pliku."

    if powod is not None:
        podglad["nieczytelna"] = True
        podglad["uwagi"].append(f"Nie można odczytać zawartości kopii. {powod}")

    obecna = podsumowanie_bazy(BAZA_DANYCH)
    if obecna is not None:
        podglad["obecna"] = {"wpisy": obecna["wpisy"], "pojazdy": len(obecna["pojazdy"])}

    wolno, powod_odmowy = sprawdz_kopie_przed_wczytaniem(sciezka)
    podglad["odmowa"] = "" if wolno else powod_odmowy
    return podglad


__all__ = [
    "FORMAT_MANIFESTU",
    "NAZWA_MANIFESTU",
    "dopisz_manifest_kopii",
    "podglad_kopii",
    "podsumowanie_bazy",
    "sprawdz_manifest",
    "zbuduj_manifest_kopii",
]
