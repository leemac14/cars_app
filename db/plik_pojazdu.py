"""Plik pojazdu: jedno auto z historią i zdjęciami w ZIP-ie — zapis z wyborem sekcji, podgląd
i wczytanie. Migawkę robi i odtwarza mechanika kosza (`zrzut_pojazdu`, `odtworz_pojazd`)."""

import json
import os
import shutil
import sqlite3
import uuid
import zipfile
from datetime import datetime
from typing import Any

import log

from .stale import (
    BAZA_DANYCH, FOLDER_ZALACZNIKI, STATUS_POJAZDU_AKTYWNY, STATUS_POJAZDU_SPRZEDANY, TABELE_Z_WIELOMA_ZALACZNIKAMI,
)
from .polaczenie import polacz_baze
from .pomocnicze import formatuj_rozmiar, liczba_z_odmiana
from .ustawienia import _pobierz_ustawienia_pojazdu, _przywroc_ustawienia_pojazdu
from .nowosci import WERSJA_APLIKACJI
from .zalaczniki import sciezka_pliku_zalacznika, wzgledna_sciezka_zalacznika
from .kosz import (
    KOSZ_KLUCZE_OBCE, KOSZ_TABELE_LICZONE, KOSZ_TABELE_POTOMNE, odtworz_pojazd, przywroc_auto_z_kosza,
    usun_auto_do_kosza, zrzut_pojazdu,
)
from .migracje import wersja_schematu_aplikacji


NAZWA_DANYCH_POJAZDU = "pojazd.json"
RODZAJ_PLIKU_POJAZDU = "plik_pojazdu"
FORMAT_PLIKU_POJAZDU = 1
ZESTAW_PELNY = "pelny"
ZESTAW_DLA_KUPUJACEGO = "kupujacy"

_FOLDER_W_ARCHIWUM = "pliki"
_MAKS_ROZMIAR_DANYCH = 64 * 1024 * 1024
_ZAPAS_MIEJSCA = 16 * 1024 * 1024
_BEZ_KOMPRESJI = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".gif")
_ROZSZERZENIA = set(_BEZ_KOMPRESJI) | {".pdf"}
_NIE_TEN_PLIK = "To nie jest plik pojazdu z tej aplikacji."
_USZKODZONY = "Plik pojazdu jest uszkodzony albo niekompletny."

# Tożsamość w chmurze nie jedzie w pliku: kod współautora to przepustka do cudzych danych,
# a wczytany pojazd ma być tylko na tym telefonie (lista jak w sync.odlacz_wspoldzielenie).
KOLUMNY_WSPOLDZIELENIA_POJAZDU = (
    "wspolny_pojazd_id", "kod_zaproszenia", "info_zdalne_id", "zdalny_hash_info", "znacznik_delty",
    "kod_wspolautora", "kod_podgladu", "rola_wspoldzielenia",
)
KOLUMNY_SYNCHRONIZACJI_WPISU = ("zdalne_id", "zdalny_hash")

# Tabele kosza spoza sekcji: tagi to słownik kolorów, a pliki wpisów idą za swoimi wpisami.
TABELE_ZAWSZE_W_PLIKU = ("tagi", "zalaczniki")

RODZAJE_DOKUMENTOW_TECHNICZNYCH = ("przeglad", "gwarancja", "gwarancja_inna", "instrukcja", "ksiazka")

# Kolejność = kolejność w oknie zapisu. `liczone` — tabele, których wiersze okno liczy jako
# wpisy (domyślnie wszystkie tabele sekcji).
SEKCJE_PLIKU_POJAZDU = [
    {"id": "serwis", "tytul": "Serwis i naprawy", "opis": "Podzespoły, wymiany, wizyty w warsztacie i własne pakiety",
     "tabele": ("zadania", "historia", "wizyty", "pakiety_serwisowe_wlasne"), "liczone": ("historia", "wizyty"),
     "dla_kupujacego": True},
    {"id": "tankowania", "tytul": "Tankowania i ładowania", "opis": "Paliwo i prąd ze stacją, ilością i kwotą",
     "tabele": ("tankowania",), "dla_kupujacego": True},
    {"id": "licznik", "tytul": "Odczyty licznika", "opis": "Historia przebiegu",
     "tabele": ("odczyty_przebiegu",), "dla_kupujacego": True},
    {"id": "opony", "tytul": "Opony", "opis": "Komplety z bieżnikiem i montażem",
     "tabele": ("zestawy_opon",), "dla_kupujacego": True},
    {"id": "karoseria", "tytul": "Karoseria", "opis": "Zdjęcia nadwozia z opisem",
     "tabele": ("zdjecia_karoserii",), "dla_kupujacego": True},
    {"id": "czesci", "tytul": "Części i ich ceny", "opis": "Magazyn, części zużyte przy naprawach, historia cen",
     "tabele": ("magazyn_czesci", "ceny_czesci", "wizyta_czesci_magazynu", "historia_czesci_magazynu"),
     "liczone": ("magazyn_czesci", "ceny_czesci"), "dla_kupujacego": True},
    {"id": "do_zrobienia", "tytul": "Do zrobienia i checklisty", "opis": "Zaplanowane prace i listy kontrolne",
     "tabele": ("do_zrobienia", "checklisty", "checklisty_pozycje"), "liczone": ("do_zrobienia", "checklisty"),
     "dla_kupujacego": True},
    {"id": "warsztaty", "tytul": "Warsztaty", "opis": "Kontakty do warsztatów",
     "tabele": ("warsztaty",), "dla_kupujacego": True},
    {"id": "dokumenty_techniczne", "tytul": "Dokumenty techniczne",
     "opis": "Przegląd, gwarancje, instrukcja i książka serwisowa ze skanami",
     "tabele": ("dokumenty_pojazdu",), "dla_kupujacego": True},
    {"id": "dokumenty_osobiste", "tytul": "Dokumenty osobiste",
     "opis": "Dowód rejestracyjny, polisy, umowa kupna i inne ze skanami",
     "tabele": ("dokumenty_pojazdu",), "dla_kupujacego": False},
    {"id": "inne_koszty", "tytul": "Inne koszty", "opis": "Myjnia, parkingi, opłaty, mandaty i reszta",
     "tabele": ("inne_koszty",), "dla_kupujacego": False},
    {"id": "cykliczne", "tytul": "Wydatki cykliczne, leasing i kredyt", "opis": "Abonamenty, raty i umowy",
     "tabele": ("wydatki_cykliczne",), "dla_kupujacego": False},
    {"id": "budzety", "tytul": "Budżety", "opis": "Limity wydatków",
     "tabele": ("budzety",), "dla_kupujacego": False},
    {"id": "rozliczenia", "tytul": "Rozliczenia między osobami", "opis": "Salda i przelewy za wspólne wydatki",
     "tabele": ("rozliczenia",), "dla_kupujacego": False},
    {"id": "ewidencja", "tytul": "Ewidencja przebiegu i trasy", "opis": "Przejazdy z celem i adresami, zapisane trasy",
     "tabele": ("przejazdy", "trasy_szablony"), "dla_kupujacego": False},
    {"id": "szkice", "tytul": "Paragony do wpisania", "opis": "Kolejka zdjęć paragonów",
     "tabele": ("szkice_wpisow",), "dla_kupujacego": False},
    {"id": "zakup", "tytul": "Zakup, sprzedaż i wycena",
     "opis": "Ceny i daty z karty pojazdu; bez nich auto wczyta się jako jeżdżące, nie sprzedane",
     "kolumny_pojazdu": ("data_zakupu", "cena_zakupu", "przebieg_zakupu", "wartosc_szacowana", "status",
                         "data_sprzedazy", "cena_sprzedazy"), "dla_kupujacego": False},
    {"id": "polisa", "tytul": "Polisa i składka", "opis": "Ubezpieczyciel, numer polisy, składka i notatka o ofertach",
     "kolumny_pojazdu": ("ubezpieczyciel", "nr_polisy", "skladka_roczna", "oferta_oc_ac", "oferta_oc_ac_data"),
     "dla_kupujacego": False},
    {"id": "podpisy", "tytul": "Podpisy osób", "opis": "Kto dodał i zmienił wpis, kto podpisał notatkę",
     "kolumny_wpisow": ("dodane_przez", "zmodyfikowane_przez", "notatka_autor"), "dla_kupujacego": False},
    {"id": "ustawienia", "tytul": "Ustawienia pojazdu", "opis": "Układ kokpitu, zakresy wykresów, tryb ewidencji",
     "ustawienia": True, "dla_kupujacego": False},
]

# Odwołania, bez których wiersz dalej ma sens (reszta bez rodzica wypada).
_KLUCZE_OPCJONALNE = {("do_zrobienia", "zadanie_id"), ("historia", "wizyta_id")}
# Wiersz, który JEST plikiem i bez niego nie istnieje (kolumna NOT NULL).
_WIERSZE_Z_PLIKIEM_WYMAGANYM = {"zalaczniki", "zdjecia_karoserii"}


class BladPlikuPojazdu(Exception):
    """Plik nie nadaje się do zapisu albo wczytania; treść idzie wprost do komunikatu."""


def sekcje_zestawu(zestaw) -> list[str]:
    """Id sekcji zestawu: ZESTAW_PELNY — wszystkie, ZESTAW_DLA_KUPUJACEGO — historia auta."""
    return [s["id"] for s in SEKCJE_PLIKU_POJAZDU if zestaw == ZESTAW_PELNY or s["dla_kupujacego"]]


def _sekcja_dokumentu(wiersz):
    return "dokumenty_techniczne" if wiersz.get("rodzaj") in RODZAJE_DOKUMENTOW_TECHNICZNYCH else "dokumenty_osobiste"


def _wiersze_sekcji(migawka, sekcja):
    tabele = migawka.get("tabele") or {}
    wynik = {}
    for tab in sekcja.get("tabele", ()):
        wiersze = (tabele.get(tab) or {}).get("wiersze") or []
        if tab == "dokumenty_pojazdu":
            wiersze = [w for w in wiersze if _sekcja_dokumentu(w) == sekcja["id"]]
        wynik[tab] = wiersze
    return wynik


def _wypelnione(kolumna, wartosc):
    return wartosc not in (None, "") and not (kolumna == "status" and wartosc == STATUS_POJAZDU_AKTYWNY)


def _opis_sekcji(migawka, sekcja):
    """Sekcja z podsumowaniem tego, co ma w migawce; None, gdy pusta."""
    podsumowanie = ""
    if "tabele" in sekcja:
        wiersze = _wiersze_sekcji(migawka, sekcja)
        if not any(wiersze.values()):
            return None
        liczba = sum(len(wiersze[t]) for t in sekcja.get("liczone") or sekcja["tabele"])
        if liczba:
            podsumowanie = liczba_z_odmiana(liczba, "wpis", "wpisy", "wpisów")
    elif "kolumny_pojazdu" in sekcja:
        auto = migawka["auto"]["wiersz"]
        liczba = sum(1 for k in sekcja["kolumny_pojazdu"] if _wypelnione(k, auto.get(k)))
        if not liczba:
            return None
        podsumowanie = liczba_z_odmiana(liczba, "pole", "pola", "pól")
    elif "kolumny_wpisow" in sekcja:
        osoby = sorted({str(w[k]).strip() for dane in (migawka.get("tabele") or {}).values()
                        for w in dane.get("wiersze") or [] for k in sekcja["kolumny_wpisow"]
                        if str(w.get(k) or "").strip()})
        if not osoby:
            return None
        podsumowanie = ", ".join(osoby[:4]) + (" i inne" if len(osoby) > 4 else "")
    else:
        liczba = len(migawka.get("ustawienia") or {})
        if not liczba:
            return None
        podsumowanie = liczba_z_odmiana(liczba, "ustawienie", "ustawienia", "ustawień")
    return {"id": sekcja["id"], "tytul": sekcja["tytul"], "opis": sekcja["opis"], "podsumowanie": podsumowanie,
            "dla_kupujacego": sekcja["dla_kupujacego"]}


def _sekcje_z_danymi(migawka):
    return [o for o in (_opis_sekcji(migawka, s) for s in SEKCJE_PLIKU_POJAZDU) if o]


def _liczba_wpisow(migawka):
    tabele = migawka.get("tabele") or {}
    return sum(len((tabele.get(t) or {}).get("wiersze") or []) for t in KOSZ_TABELE_LICZONE)


def zawartosc_pojazdu(auto_id) -> dict[str, Any] | None:
    """Do okna zapisu: {"nazwa", "sekcje"} — tylko sekcje z danymi; None, gdy auta nie ma."""
    migawka = zrzut_pojazdu(auto_id)
    if not migawka:
        return None
    migawka["ustawienia"] = _pobierz_ustawienia_pojazdu(auto_id)
    return {"nazwa": str(migawka["auto"]["wiersz"].get("nazwa") or "Pojazd"), "sekcje": _sekcje_z_danymi(migawka)}


def _wytnij_sekcje(migawka, wybrane):
    tabele = migawka["tabele"]
    auto = migawka["auto"]["wiersz"]
    for sekcja in SEKCJE_PLIKU_POJAZDU:
        if sekcja["id"] in wybrane:
            continue
        for tab in sekcja.get("tabele", ()):
            if tab in tabele:
                tabele[tab]["wiersze"] = [w for w in tabele[tab]["wiersze"]
                                          if tab == "dokumenty_pojazdu" and _sekcja_dokumentu(w) != sekcja["id"]]
        for kolumna in sekcja.get("kolumny_pojazdu", ()):
            auto.pop(kolumna, None)
        for kolumna in sekcja.get("kolumny_wpisow", ()):
            for dane in tabele.values():
                for w in dane["wiersze"]:
                    w.pop(kolumna, None)
        if sekcja.get("ustawienia"):
            migawka["ustawienia"] = {}


def _bez_synchronizacji(migawka):
    """Bez tych kolumn wiersz dostaje wartości domyślne: rolę właściciela, wpisy jak nigdy niewysłane."""
    auto = migawka["auto"]["wiersz"]
    for kolumna in KOLUMNY_WSPOLDZIELENIA_POJAZDU:
        auto.pop(kolumna, None)
    for dane in migawka["tabele"].values():
        for w in dane.get("wiersze") or []:
            for kolumna in KOLUMNY_SYNCHRONIZACJI_WPISU:
                w.pop(kolumna, None)


def _uporzadkuj_powiazania(migawka):
    """Wiersz bez wymaganego rodzica w migawce wypada, odwołanie opcjonalne zmienia się w NULL,
    plik wpisu zostaje tylko przy wpisie z migawki — inaczej trafiłby w cudzy wiersz o tym ID."""
    tabele = migawka["tabele"]

    def identyfikatory(tab):
        return {w.get("id") for w in (tabele.get(tab) or {}).get("wiersze") or [] if w.get("id") is not None}

    for tab in KOSZ_TABELE_POTOMNE:
        klucze = KOSZ_KLUCZE_OBCE.get(tab)
        if not klucze or tab not in tabele:
            continue
        rodzice = {rodzic: identyfikatory(rodzic) for rodzic in set(klucze.values())}
        zostaja = []
        for w in tabele[tab]["wiersze"]:
            sierota = False
            for kolumna, rodzic in klucze.items():
                if w.get(kolumna) is None or w[kolumna] in rodzice[rodzic]:
                    continue
                if (tab, kolumna) in _KLUCZE_OPCJONALNE:
                    w[kolumna] = None
                else:
                    sierota = True
            if not sierota:
                zostaja.append(w)
        tabele[tab]["wiersze"] = zostaja

    if "zalaczniki" in tabele:
        wpisy = {tab: identyfikatory(tab) for tab in TABELE_Z_WIELOMA_ZALACZNIKAMI}
        tabele["zalaczniki"]["wiersze"] = [w for w in tabele["zalaczniki"]["wiersze"]
                                           if w.get("rekord_id") in wpisy.get(w.get("tabela"), ())]


def _kolumna_pliku(tabela):
    return "sciezka" if tabela == "zalaczniki" else "zalacznik"


def _odwolania_do_plikow(migawka):
    """Ścieżki plików z migawki (zdjęcie auta, wiersze-pliki, pliki wpisów), bez powtórzeń."""
    wynik = []
    wartosci = [migawka["auto"]["wiersz"].get("zdjecie_glowne")]
    for tab in KOSZ_TABELE_POTOMNE:
        wartosci += [w.get(_kolumna_pliku(tab)) for w in (migawka["tabele"].get(tab) or {}).get("wiersze") or []]
    for wartosc in wartosci:
        if wartosc and isinstance(wartosc, str) and wartosc not in wynik:
            wynik.append(wartosc)
    return wynik


def _tylko_przywiezione_pliki(migawka, podmiana):
    """Odwołanie do pliku, którego nie ma w archiwum, znika (wiersz-plik razem z wierszem) —
    obca ścieżka nie może zostać w bazie. Zwraca liczbę pominiętych odwołań."""
    pominiete = 0
    auto = migawka["auto"]["wiersz"]
    if auto.get("zdjecie_glowne") and auto["zdjecie_glowne"] not in podmiana:
        auto["zdjecie_glowne"] = None
        pominiete += 1
    for tab, dane in migawka["tabele"].items():
        kolumna = _kolumna_pliku(tab)
        zostaja = []
        for w in dane.get("wiersze") or []:
            if w.get(kolumna) and w[kolumna] not in podmiana:
                pominiete += 1
                if tab in _WIERSZE_Z_PLIKIEM_WYMAGANYM:
                    continue
                w[kolumna] = None
            zostaja.append(w)
        dane["wiersze"] = zostaja
    return pominiete


def _rozszerzenie(nazwa):
    rozszerzenie = os.path.splitext(str(nazwa))[1].lower()
    return rozszerzenie if rozszerzenie in _ROZSZERZENIA else ""


def _sprzatnij(sciezki):
    for sciezka in sciezki:
        try:
            if os.path.exists(sciezka):
                os.remove(sciezka)
        except OSError:
            log.polkniety(f"sprzątanie po pliku pojazdu: {sciezka}")


def zapisz_plik_pojazdu(auto_id, cel, sekcje=None) -> dict[str, Any]:
    """Zapisuje auto do ZIP-a `cel` (dane w pojazd.json, pliki w pliki/); `sekcje` — id z
    SEKCJE_PLIKU_POJAZDU, None = wszystkie. Zwraca {"nazwa", "wpisy", "pliki", "brakujace", "rozmiar"}."""
    migawka = zrzut_pojazdu(auto_id)
    if not migawka:
        raise BladPlikuPojazdu("Tego pojazdu nie ma już w aplikacji.")
    migawka["ustawienia"] = _pobierz_ustawienia_pojazdu(auto_id)
    zadane = None if sekcje is None else set(sekcje)
    wybrane = [s["id"] for s in SEKCJE_PLIKU_POJAZDU if zadane is None or s["id"] in zadane]
    _wytnij_sekcje(migawka, set(wybrane))
    _bez_synchronizacji(migawka)
    _uporzadkuj_powiazania(migawka)

    pliki, brakujace = [], 0
    for numer, oryginal in enumerate(_odwolania_do_plikow(migawka), 1):
        sciezka = sciezka_pliku_zalacznika(oryginal)
        if not sciezka or not os.path.isfile(sciezka):
            brakujace += 1
            continue
        pliki.append((f"{_FOLDER_W_ARCHIWUM}/{numer:04d}{_rozszerzenie(sciezka)}", oryginal, sciezka))

    dane = {
        "rodzaj": RODZAJ_PLIKU_POJAZDU,
        "format": FORMAT_PLIKU_POJAZDU,
        "aplikacja": WERSJA_APLIKACJI,
        "schemat": wersja_schematu_aplikacji(),
        "utworzono": datetime.now().astimezone().isoformat(timespec="seconds"),
        "sekcje": wybrane,
        "migawka": migawka,
        "pliki": [[nazwa, oryginal] for nazwa, oryginal, _ in pliki],
    }
    try:
        with zipfile.ZipFile(cel, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(NAZWA_DANYCH_POJAZDU, json.dumps(dane, ensure_ascii=False, default=str))
            for nazwa, _, sciezka in pliki:
                zf.write(sciezka, nazwa, compress_type=zipfile.ZIP_STORED if nazwa.endswith(_BEZ_KOMPRESJI)
                         else zipfile.ZIP_DEFLATED)
    except Exception:
        _sprzatnij([cel])
        raise
    return {"nazwa": str(migawka["auto"]["wiersz"].get("nazwa") or "Pojazd"), "wpisy": _liczba_wpisow(migawka),
            "pliki": len(pliki), "brakujace": brakujace, "rozmiar": os.path.getsize(cel)}


def rodzaj_archiwum(sciezka) -> str | None:
    """'pojazd' (plik pojazdu), 'kopia' (kopia bazy: ZIP z bazą albo goły plik SQLite) albo None."""
    if not sciezka or not os.path.isfile(sciezka):
        return None
    try:
        if zipfile.is_zipfile(sciezka):
            with zipfile.ZipFile(sciezka) as zf:
                nazwy = set(zf.namelist())
            if NAZWA_DANYCH_POJAZDU in nazwy:
                return "pojazd"
            return "kopia" if os.path.basename(BAZA_DANYCH) in nazwy else None
        with open(sciezka, "rb") as plik:
            return "kopia" if plik.read(16) == b"SQLite format 3\x00" else None
    except (OSError, zipfile.BadZipFile):
        return None


def _skalar(wartosc):
    return wartosc is None or isinstance(wartosc, (str, int, float))


def _poprawny_wiersz(wiersz):
    return (isinstance(wiersz, dict) and all(isinstance(k, str) and _skalar(v) for k, v in wiersz.items())
            and (wiersz.get("id") is None or (isinstance(wiersz["id"], int) and not isinstance(wiersz["id"], bool))))


def _poprawne_dane(dane):
    migawka = dane.get("migawka")
    if not isinstance(migawka, dict) or not isinstance(migawka.get("auto"), dict):
        return False
    if not migawka["auto"].get("wiersz") or not _poprawny_wiersz(migawka["auto"]["wiersz"]):
        return False
    tabele = migawka.get("tabele")
    if not isinstance(tabele, dict) or not all(
            isinstance(t, dict) and isinstance(t.get("wiersze", []), list) and all(map(_poprawny_wiersz, t.get("wiersze", [])))
            for t in tabele.values()):
        return False
    ustawienia = migawka.get("ustawienia")
    if ustawienia is not None and not (isinstance(ustawienia, dict) and all(
            isinstance(k, str) and isinstance(v, str) for k, v in ustawienia.items())):
        return False
    pliki = dane.get("pliki")
    return isinstance(pliki, list) and all(
        isinstance(p, list) and len(p) == 2 and all(isinstance(x, str) for x in p) for p in pliki)


def _czytaj_dane(zf):
    """pojazd.json sprawdzony co do kształtu, z pustymi tabelami tam, gdzie plik ich nie ma."""
    try:
        info = zf.getinfo(NAZWA_DANYCH_POJAZDU)
    except KeyError:
        raise BladPlikuPojazdu(_NIE_TEN_PLIK) from None
    if info.file_size > _MAKS_ROZMIAR_DANYCH:
        raise BladPlikuPojazdu(_USZKODZONY)
    try:
        dane = json.loads(zf.read(info).decode("utf-8"))
    except (ValueError, zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, OSError):
        raise BladPlikuPojazdu(_USZKODZONY) from None
    if not isinstance(dane, dict) or dane.get("rodzaj") != RODZAJ_PLIKU_POJAZDU:
        raise BladPlikuPojazdu(_NIE_TEN_PLIK)
    format_pliku = dane.get("format")
    if not isinstance(format_pliku, int) or isinstance(format_pliku, bool):
        raise BladPlikuPojazdu(_USZKODZONY)
    if format_pliku > FORMAT_PLIKU_POJAZDU:
        raise BladPlikuPojazdu("Plik zapisała nowsza wersja aplikacji w formacie, którego ta jeszcze nie zna. "
                               "Zaktualizuj aplikację i wczytaj go ponownie.")
    if not _poprawne_dane(dane):
        raise BladPlikuPojazdu(_USZKODZONY)
    for dane_tabeli in dane["migawka"]["tabele"].values():
        dane_tabeli.setdefault("wiersze", [])
    return dane


def _klucz_tozsamosci(tekst, minimum):
    znaki = "".join(z for z in str(tekst or "").upper() if z.isalnum())
    return znaki if len(znaki) >= minimum else None


def _ten_sam_pojazd(auto):
    """Auto z aplikacji o tym samym VIN-ie, a gdy VIN-u nie da się porównać — numerze rejestracyjnym."""
    vin, rejestracja = _klucz_tozsamosci(auto.get("vin"), 8), _klucz_tozsamosci(auto.get("nr_rej"), 4)
    if not vin and not rejestracja:
        return None
    with polacz_baze(zmienia_dane=False) as conn:
        conn.row_factory = sqlite3.Row
        wiersze = conn.execute(
            "SELECT id, nazwa, status, vin, nr_rej, wspolny_pojazd_id FROM samochody ORDER BY id").fetchall()

    def opis(w, po_czym):
        return {"id": w["id"], "nazwa": str(w["nazwa"]), "po_czym": po_czym,
                "sprzedany": w["status"] == STATUS_POJAZDU_SPRZEDANY, "wspolny": bool(w["wspolny_pojazd_id"])}

    for w in wiersze:
        if vin and _klucz_tozsamosci(w["vin"], 8) == vin:
            return opis(w, "VIN")
    for w in wiersze:
        vin_tutaj = _klucz_tozsamosci(w["vin"], 8)
        if rejestracja and not (vin and vin_tutaj) and _klucz_tozsamosci(w["nr_rej"], 4) == rejestracja:
            return opis(w, "numer rejestracyjny")
    return None


def podglad_pliku_pojazdu(sciezka) -> dict[str, Any]:
    """Co jest w pliku, zanim cokolwiek się zmieni; `rodzaj` jak w rodzaj_archiwum, `blad` —
    powód po polsku, gdy pliku nie da się wczytać. Nie zmienia bazy ani plików."""
    podglad = {"plik": os.path.basename(str(sciezka or "")), "rodzaj": rodzaj_archiwum(sciezka), "blad": None}
    if podglad["rodzaj"] != "pojazd":
        podglad["blad"] = _NIE_TEN_PLIK if sciezka and os.path.isfile(sciezka) else "Nie można odczytać wybranego pliku."
        return podglad
    try:
        with zipfile.ZipFile(sciezka) as zf:
            dane = _czytaj_dane(zf)
            rozmiary = {i.filename: i.file_size for i in zf.infolist()}
    except BladPlikuPojazdu as ex:
        podglad["blad"] = str(ex)
        return podglad
    except (OSError, zipfile.BadZipFile):
        podglad["blad"] = _USZKODZONY
        return podglad

    migawka = dane["migawka"]
    auto = migawka["auto"]["wiersz"]
    obecne = {nazwa for nazwa, _ in dane["pliki"] if nazwa in rozmiary}
    schemat = dane.get("schemat") if isinstance(dane.get("schemat"), int) else None
    uwagi = []
    if schemat and schemat > wersja_schematu_aplikacji():
        uwagi.append("Plik zapisała nowsza wersja aplikacji — dane, których ta jeszcze nie zna, zostaną pominięte. "
                     "Po aktualizacji aplikacji wczytasz go w całości.")
    brakujace = len({nazwa for nazwa, _ in dane["pliki"]}) - len(obecne)
    if brakujace:
        uwagi.append(f"W pliku brakuje {liczba_z_odmiana(brakujace, 'pliku', 'plików', 'plików')} "
                     "ze zdjęciami — wpisy wczytają się bez nich.")
    podglad.update({
        "nazwa": str(auto.get("nazwa") or "Pojazd"),
        "opis_auta": " ".join(str(auto[k]) for k in ("marka", "model", "rok_produkcji") if auto.get(k)),
        "vin": str(auto.get("vin") or ""),
        "nr_rej": str(auto.get("nr_rej") or ""),
        "sprzedany": auto.get("status") == STATUS_POJAZDU_SPRZEDANY,
        "utworzono": dane["utworzono"] if isinstance(dane.get("utworzono"), str) else None,
        "aplikacja": str(dane.get("aplikacja") or ""),
        "sekcje": _sekcje_z_danymi(migawka),
        "wpisy": _liczba_wpisow(migawka),
        "pliki": len(obecne),
        "rozmiar": sum(rozmiary[n] for n in obecne),
        "uwagi": uwagi,
        "ten_sam": _ten_sam_pojazd(auto),
    })
    return podglad


def _wypakuj_pliki(zf, pliki, potrzebne, nowe):
    """Pliki, do których odwołuje się migawka, do folderu załączników pod NOWYMI nazwami (nazwa
    z archiwum nie trafia na dysk); zwraca {ścieżka z migawki: nowa}. Utworzone dopisuje do `nowe`."""
    w_archiwum = {i.filename: i for i in zf.infolist()}
    do_wypakowania = {}
    for nazwa, oryginal in pliki:
        if nazwa in w_archiwum and oryginal in potrzebne and oryginal not in do_wypakowania:
            do_wypakowania[oryginal] = w_archiwum[nazwa]
    os.makedirs(FOLDER_ZALACZNIKI, exist_ok=True)
    rozmiar = sum(i.file_size for i in do_wypakowania.values())
    if rozmiar + _ZAPAS_MIEJSCA > shutil.disk_usage(FOLDER_ZALACZNIKI).free:
        raise BladPlikuPojazdu(f"Za mało miejsca: zdjęcia z pliku zajmą {formatuj_rozmiar(rozmiar)}.")
    podmiana = {}
    for oryginal, info in do_wypakowania.items():
        cel = os.path.join(FOLDER_ZALACZNIKI, f"{uuid.uuid4().hex}{_rozszerzenie(info.filename)}")
        nowe.append(cel)
        try:
            with zf.open(info) as zrodlo, open(cel, "wb") as plik:
                shutil.copyfileobj(zrodlo, plik)
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError) as ex:
            raise BladPlikuPojazdu(_USZKODZONY) from ex
        podmiana[oryginal] = wzgledna_sciezka_zalacznika(cel)
    return podmiana


def wczytaj_plik_pojazdu(sciezka, zastap_auto_id=None) -> dict[str, Any]:
    """Wczytuje auto z pliku jako nowe, tylko na tym telefonie; `zastap_auto_id` idzie najpierw do
    kosza (wraca, gdy wczytanie padnie). Zwraca {"auto_id", "nazwa", "status", "pliki", "pominiete",
    "kosz_id"}; plik nie do wczytania → BladPlikuPojazdu z powodem."""
    if rodzaj_archiwum(sciezka) != "pojazd":
        raise BladPlikuPojazdu(_NIE_TEN_PLIK if sciezka and os.path.isfile(sciezka)
                               else "Nie można odczytać wybranego pliku.")
    nowe_pliki = []
    try:
        with zipfile.ZipFile(sciezka) as zf:
            dane = _czytaj_dane(zf)
            migawka = dane["migawka"]
            _bez_synchronizacji(migawka)
            _uporzadkuj_powiazania(migawka)
            podmiana = _wypakuj_pliki(zf, dane["pliki"], set(_odwolania_do_plikow(migawka)), nowe_pliki)
        pominiete = _tylko_przywiezione_pliki(migawka, podmiana)
        kosz = usun_auto_do_kosza(zastap_auto_id) if zastap_auto_id else None
        try:
            with polacz_baze() as conn:
                auto_id = odtworz_pojazd(conn, migawka, podmiana, nowe_id=True)
        except Exception:
            if kosz:
                przywroc_auto_z_kosza(kosz["kosz_id"])
            raise
    except zipfile.BadZipFile as ex:
        _sprzatnij(nowe_pliki)
        raise BladPlikuPojazdu(_USZKODZONY) from ex
    except Exception:
        _sprzatnij(nowe_pliki)
        raise

    _przywroc_ustawienia_pojazdu(auto_id, migawka.get("ustawienia"))
    with polacz_baze(zmienia_dane=False) as conn:
        nazwa, status = conn.execute("SELECT nazwa, status FROM samochody WHERE id=?", (auto_id,)).fetchone()
    return {"auto_id": auto_id, "nazwa": nazwa, "status": status, "pliki": len(podmiana), "pominiete": pominiete,
            "kosz_id": kosz["kosz_id"] if kosz else None}


__all__ = [
    "BladPlikuPojazdu",
    "FORMAT_PLIKU_POJAZDU",
    "KOLUMNY_SYNCHRONIZACJI_WPISU",
    "KOLUMNY_WSPOLDZIELENIA_POJAZDU",
    "NAZWA_DANYCH_POJAZDU",
    "RODZAJE_DOKUMENTOW_TECHNICZNYCH",
    "RODZAJ_PLIKU_POJAZDU",
    "SEKCJE_PLIKU_POJAZDU",
    "TABELE_ZAWSZE_W_PLIKU",
    "ZESTAW_DLA_KUPUJACEGO",
    "ZESTAW_PELNY",
    "podglad_pliku_pojazdu",
    "rodzaj_archiwum",
    "sekcje_zestawu",
    "wczytaj_plik_pojazdu",
    "zapisz_plik_pojazdu",
    "zawartosc_pojazdu",
]
