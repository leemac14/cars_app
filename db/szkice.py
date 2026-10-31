"""Kolejka „do wpisania” (M-08): zdjęcie paragonu teraz, wpis później; od razu można
dopisać rodzaj, licznik i opis.

Szkic leży w OSOBNEJ tabeli `szkice_wpisow` (wpis bez kwot rozjechałby statystyki,
eksport i sync). Formularz zakłada zwykły wpis i w TEJ SAMEJ transakcji zamyka szkic
(`zamknij_szkic(conn=)`); zdjęcie przechodzi bez kopiowania (ta sama ścieżka
`zalaczniki/<nazwa>`). Szkice są lokalne (zdjęcia nie jadą do chmury, N-06); kosz
zabiera je z autem (`KOSZ_TABELE_POTOMNE`, `TABELE_Z_ZALACZNIKIEM`); usuwanie przez
`usun_z_cofnieciem("szkice_wpisow", id)`."""

import os
import sqlite3
import uuid
from datetime import date, datetime

import log
from date import na_iso

from .stale import TABELE_Z_WIELOMA_ZALACZNIKAMI
from .pamiec import z_pamieci
from .polaczenie import polacz_baze
from .zalaczniki import (TYP_PLIKU_DOKUMENTU, _auto_rekordu, _plik_w_uzyciu, _policz_pliki_dokumentu,
                         _upewnij_folder_odroczonych, sciezka_pliku_zalacznika, typ_dla_pliku,
                         usun_plik_zalacznika, wzgledna_sciezka_zalacznika, zapisz_zalacznik)

try:
    from PIL import Image
except ImportError:  # pragma: no cover — Pillow jest w requirements.txt
    Image = None


TABELA_SZKICOW = "szkice_wpisow"

# Rodzaj wpisu, którym szkic ma się stać — klucz idzie do bazy, etykieta na ekran.
RODZAJE_SZKICU = {
    "tankowanie": "Tankowanie",
    "koszt": "Inny koszt",
    "wizyta": "Wizyta w warsztacie",
    "serwis": "Serwis",
}

# Po tylu dniach najstarszego szkicu przypomina dzwonek.
DNI_PRZYPOMNIENIA_SZKICU = 3

# Krótki opis ma być podpowiedzią („myjnia”, „A4 bramki”), nie notatką.
MAKS_DLUGOSC_OPISU_SZKICU = 120

# Znaczniki EXIF: DateTimeOriginal (w podkatalogu Exif) i DateTime (IFD0).
_EXIF_IFD = 0x8769
_EXIF_CZAS_ZDJECIA = 0x9003
_EXIF_CZAS_PLIKU = 0x0132

_KOLUMNY = ("id", "auto_id", "data", "data_iso", "godzina", "zalacznik", "rodzaj", "przebieg", "opis")


def _rodzaj(wartosc):
    return wartosc if wartosc in RODZAJE_SZKICU else None


def _przebieg(wartosc):
    try:
        km = int(round(float(wartosc)))
    except (TypeError, ValueError):
        return None
    return km if km > 0 else None


def _opis(wartosc):
    tekst = " ".join(str(wartosc or "").split())
    return tekst[:MAKS_DLUGOSC_OPISU_SZKICU] or None


def czas_zdjecia(sciezka) -> datetime | None:
    """Kiedy zrobiono zdjęcie — z EXIF (DateTimeOriginal, potem DateTime); czas
    modyfikacji się nie nadaje (Android kopiuje plik przy wyborze). Brak, zera albo
    przyszłość → None (wołający bierze dziś)."""
    if Image is None or not sciezka:
        return None
    try:
        with Image.open(sciezka) as obraz:
            exif = obraz.getexif()
            tekst = exif.get_ifd(_EXIF_IFD).get(_EXIF_CZAS_ZDJECIA) or exif.get(_EXIF_CZAS_PLIKU)
    except (OSError, ValueError, SyntaxError):
        return None
    if isinstance(tekst, bytes):
        tekst = tekst.decode("ascii", "ignore")
    try:
        kiedy = datetime.strptime(str(tekst or "").strip()[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    if kiedy.year < 2000 or kiedy.date() > date.today():
        return None
    return kiedy


def dodaj_szkic(auto_id, sciezka_zdjecia, kiedy=None, rodzaj=None, przebieg=None, opis=None) -> int | None:
    """Zapisuje zdjęcie do załączników (obrócone wg EXIF i zmniejszone, jak każde
    inne — patrz zapisz_zalacznik) i zakłada szkic. `kiedy` to chwila zdjęcia;
    bez niej — teraz. Zwraca id szkicu albo None, gdy zdjęcia nie da się zapisać."""
    if not auto_id:
        return None
    zalacznik = zapisz_zalacznik(sciezka_zdjecia)
    if not zalacznik:
        return None
    kiedy = kiedy or datetime.now()
    data = kiedy.strftime("%d.%m.%Y")
    try:
        with polacz_baze() as conn:
            kursor = conn.execute(
                "INSERT INTO szkice_wpisow (auto_id, data, data_iso, godzina, zalacznik, rodzaj, przebieg, opis) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (auto_id, data, na_iso(data), kiedy.strftime("%H:%M"), zalacznik,
                 _rodzaj(rodzaj), _przebieg(przebieg), _opis(opis)),
            )
            return kursor.lastrowid
    except sqlite3.Error:
        # Zdjęcie bez szkicu byłoby sierotą w folderze załączników.
        usun_plik_zalacznika(zalacznik)
        raise


def dodaj_szkic_z_bajtow(auto_id, dane, rozszerzenie=".jpg") -> int | None:
    """Szkic z bajtów prosto z aparatu (flet-camera oddaje zakodowany JPEG).
    Plik pośredni leży w folderze odroczonych — gdyby aplikacja padła w środku,
    posprząta go posprzataj_odroczone_zalaczniki."""
    if not auto_id or not dane:
        return None
    sciezka = os.path.join(_upewnij_folder_odroczonych(), f"migawka_{uuid.uuid4().hex}{rozszerzenie}")
    with open(sciezka, "wb") as plik:
        plik.write(bytes(dane))
    try:
        return dodaj_szkic(auto_id, sciezka)
    finally:
        try:
            os.remove(sciezka)
        except OSError:
            log.polkniety("sprzątanie pliku pośredniego migawki")


def dodaj_szkice_z_plikow(auto_id, sciezki) -> int:
    """Zdjęcia z galerii — każde osobnym szkicem, z datą ze zdjęcia. Zwraca, ile
    szkiców powstało (plik, którego nie da się odczytać, jest pomijany)."""
    dodane = 0
    for sciezka in sciezki or []:
        if not sciezka or not os.path.exists(sciezka):
            continue
        if dodaj_szkic(auto_id, sciezka, kiedy=czas_zdjecia(sciezka)):
            dodane += 1
    return dodane


def _wiersz_szkicu(wiersz, dzis):
    szkic = dict(zip(_KOLUMNY, wiersz))
    try:
        szkic["dni"] = max(0, (dzis - date.fromisoformat(szkic["data_iso"])).days)
    except (TypeError, ValueError):
        szkic["dni"] = 0
    return szkic


def pobierz_szkice(auto_id):
    """Szkice pojazdu od najstarszego — w tej kolejności warto je wpisywać,
    bo formularz tankowania pilnuje, żeby licznik rósł razem z datą."""
    if not auto_id:
        return []
    dzis = date.today()
    with polacz_baze(zmienia_dane=False) as conn:
        wiersze = conn.execute(
            f"SELECT {', '.join(_KOLUMNY)} FROM szkice_wpisow WHERE auto_id=? "
            "ORDER BY data_iso, godzina, id",
            (auto_id,),
        ).fetchall()
    return [_wiersz_szkicu(w, dzis) for w in wiersze]


def pobierz_szkic(szkic_id):
    """Jeden szkic (słownik jak w pobierz_szkice) albo None."""
    if not szkic_id:
        return None
    with polacz_baze(zmienia_dane=False) as conn:
        wiersz = conn.execute(
            f"SELECT {', '.join(_KOLUMNY)} FROM szkice_wpisow WHERE id=?", (szkic_id,)
        ).fetchone()
    return _wiersz_szkicu(wiersz, date.today()) if wiersz else None


def podsumowanie_szkicow(auto_id):
    """{liczba, najstarszy_id, najstarszy_data, dni} — do baneru na kokpicie
    i przypomnienia w dzwonku. Trzyma je pamięć metryk do najbliższego zapisu,
    bo kokpit pyta o nie przy każdym powrocie na ekran."""
    pusto = {"liczba": 0, "najstarszy_id": None, "najstarszy_data": None, "dni": 0}
    if not auto_id:
        return pusto
    return z_pamieci("szkice", auto_id, lambda: _policz_podsumowanie_szkicow(auto_id, pusto))


def _policz_podsumowanie_szkicow(auto_id, pusto):
    szkice = pobierz_szkice(auto_id)
    if not szkice:
        return dict(pusto)
    najstarszy = szkice[0]
    return {"liczba": len(szkice), "najstarszy_id": najstarszy["id"],
            "najstarszy_data": najstarszy["data"], "dni": najstarszy["dni"]}


def opisz_szkic(szkic_id, rodzaj=None, przebieg=None, opis=None) -> bool:
    """Rodzaj, licznik (km) i krótki opis — wszystkie trzy naraz, tak jak stoją
    w oknie po migawce. Pusta wartość czyści pole."""
    with polacz_baze() as conn:
        kursor = conn.execute(
            "UPDATE szkice_wpisow SET rodzaj=?, przebieg=?, opis=? WHERE id=?",
            (_rodzaj(rodzaj), _przebieg(przebieg), _opis(opis), szkic_id),
        )
        return kursor.rowcount > 0


def przenies_szkic(szkic_id, auto_id) -> bool:
    """Zdjęcie zrobione przy złym aucie w aplikacji — przepina szkic na inne."""
    if not auto_id:
        return False
    with polacz_baze() as conn:
        kursor = conn.execute("UPDATE szkice_wpisow SET auto_id=? WHERE id=?", (auto_id, szkic_id))
        return kursor.rowcount > 0


def zamknij_szkic(szkic_id, conn=None):
    """Szkic stał się wpisem: znika z kolejki, a jego zdjęcie zostaje, bo nosi
    je już nowy wpis. Z `conn` — w transakcji formularza, więc wpis i koniec
    szkicu zapisują się razem albo wcale."""
    if not szkic_id:
        return
    if conn is not None:
        conn.execute("DELETE FROM szkice_wpisow WHERE id=?", (szkic_id,))
        return
    with polacz_baze() as polaczenie:
        polaczenie.execute("DELETE FROM szkice_wpisow WHERE id=?", (szkic_id,))


# ---------------------------------------------------------------- „Z zapisanych zdjęć”

def szkice_ze_zdjeciem(auto_id, pominiete=()):
    """Szkice pojazdu ze zdjęciem na dysku — do wyboru w formularzu; `pominiete` to id
    szkiców, które formularz już niesie."""
    return [s for s in pobierz_szkice(auto_id) if s["id"] not in pominiete and s.get("zalacznik")
            and os.path.exists(sciezka_pliku_zalacznika(s["zalacznik"]))]


def przejmij_szkic(conn, szkic_id, auto_id=None) -> str | None:
    """Zdjęcie szkicu przechodzi na wpis w transakcji wołającego: szkic znika z kolejki,
    wynik to ścieżka zdjęcia (bez kopii). None — szkicu już nie ma albo jest innego auta."""
    wiersz = conn.execute("SELECT zalacznik, auto_id FROM szkice_wpisow WHERE id=?", (szkic_id,)).fetchone()
    if not wiersz or not wiersz[0] or (auto_id is not None and wiersz[1] != auto_id):
        return None
    conn.execute("DELETE FROM szkice_wpisow WHERE id=?", (szkic_id,))
    return wiersz[0]


def dolacz_szkice_do_wpisu(tabela, rekord_id, szkic_ids) -> int:
    """Menu wpisu: zdjęcia szkiców jego auta dopisują się na koniec plików (bez kopii),
    a szkice znikają z kolejki — razem albo wcale. Zwraca liczbę dodanych zdjęć."""
    if tabela not in TABELE_Z_WIELOMA_ZALACZNIKAMI or not rekord_id or not szkic_ids:
        return 0
    dodane = 0
    with polacz_baze() as conn:
        auto_id = _auto_rekordu(conn, tabela, rekord_id)
        if auto_id is None:
            return 0
        wiersze = conn.execute("SELECT typ, kolejnosc FROM zalaczniki WHERE tabela=? AND rekord_id=?",
                               (tabela, rekord_id)).fetchall()
        typy = [w[0] for w in wiersze]
        nastepna = max((w[1] for w in wiersze), default=-1) + 1
        for szkic_id in szkic_ids:
            opis = conn.execute("SELECT opis FROM szkice_wpisow WHERE id=?", (szkic_id,)).fetchone()
            sciezka = przejmij_szkic(conn, szkic_id, auto_id)
            if not sciezka:
                continue
            typ = TYP_PLIKU_DOKUMENTU if tabela == "dokumenty_pojazdu" else typ_dla_pliku(sciezka, typy)
            typy.append(typ)
            conn.execute("INSERT INTO zalaczniki (auto_id, tabela, rekord_id, sciezka, typ, opis, kolejnosc) "
                         "VALUES (?,?,?,?,?,?,?)",
                         (auto_id, tabela, rekord_id, sciezka, typ, opis[0] if opis else None, nastepna + dodane))
            dodane += 1
        if dodane:
            _policz_pliki_dokumentu(conn, tabela, rekord_id)
    return dodane


def zamknij_szkice_po_kopii(sciezki) -> int:
    """Wpis z jednym plikiem (karoseria, zdjęcie pojazdu) dostał KOPIĘ zdjęcia z kolejki:
    po udanym zapisie szkic znika razem z oryginałem. Plik spoza kolejki nic nie robi."""
    szukane = {wzgledna_sciezka_zalacznika(s) for s in sciezki or [] if s}
    if not szukane:
        return 0
    with polacz_baze() as conn:
        szkice = [(i, z) for i, z in conn.execute("SELECT id, zalacznik FROM szkice_wpisow").fetchall()
                  if z and wzgledna_sciezka_zalacznika(z) in szukane]
        for szkic_id, _ in szkice:
            conn.execute("DELETE FROM szkice_wpisow WHERE id=?", (szkic_id,))
        do_skasowania = [z for _, z in szkice if not _plik_w_uzyciu(conn, z)]
    for sciezka in do_skasowania:
        usun_plik_zalacznika(sciezka)
    return len(szkice)


__all__ = [
    "DNI_PRZYPOMNIENIA_SZKICU",
    "MAKS_DLUGOSC_OPISU_SZKICU",
    "RODZAJE_SZKICU",
    "TABELA_SZKICOW",
    "czas_zdjecia",
    "dodaj_szkic",
    "dodaj_szkic_z_bajtow",
    "dodaj_szkice_z_plikow",
    "dolacz_szkice_do_wpisu",
    "opisz_szkic",
    "pobierz_szkic",
    "pobierz_szkice",
    "podsumowanie_szkicow",
    "przejmij_szkic",
    "przenies_szkic",
    "szkice_ze_zdjeciem",
    "zamknij_szkic",
    "zamknij_szkice_po_kopii",
]
