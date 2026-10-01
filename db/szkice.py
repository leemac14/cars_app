"""Kolejka „do wpisania” (M-08): zdjęcie paragonu teraz, wpis wieczorem.

Największy wróg tej aplikacji to chwila przy dystrybutorze, kiedy nie ma czasu
na formularz. Szkic obniża próg wejścia do jednego dotknięcia migawki: zdjęcie
z datą (i godziną) trafia do kolejki, a formularz wypełnia się później, na
kanapie. Zaraz po migawce można — nie trzeba — dopisać rodzaj wpisu, stan
licznika (paragon go nie ma, a wieczorem nikt go nie pamięta) i krótki opis.

Szkic leży w OSOBNEJ tabeli `szkice_wpisow`, a nie jako flaga przy tankowaniach
i kosztach: wpis bez kwoty i litrów rozjechałby każdą statystykę, eksport
i synchronizację, które ufają, że tankowanie ma liczby. Formularz uzupełniający
zakłada zwykły wpis i w TEJ SAMEJ transakcji zamyka szkic (`zamknij_szkic`
z `conn=`), a zdjęcie przechodzi na wpis bez kopiowania — ta sama ścieżka
`zalaczniki/<nazwa>` trafia do kolumny `zalacznik` nowego wpisu.

Szkice są lokalne: zdjęcia nie jadą do chmury (N-06), więc szkic u drugiej
osoby byłby odsyłaczem do pliku, którego ona nie ma. Kosz pojazdu zabiera je
razem z autem (`KOSZ_TABELE_POTOMNE`), a zdjęcie — jak każdy załącznik
(`TABELE_Z_ZALACZNIKIEM`). Usuwanie z cofnięciem robi ogólne
`usun_z_cofnieciem("szkice_wpisow", id)`."""

import os
import sqlite3
import uuid
from datetime import date, datetime

import log
from date import na_iso

from .pamiec import z_pamieci
from .polaczenie import polacz_baze
from .zalaczniki import _upewnij_folder_odroczonych, usun_plik_zalacznika, zapisz_zalacznik

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
    """Kiedy zdjęcie zrobiono — z EXIF (DateTimeOriginal, a bez niego DateTime).

    Zdjęcie wybrane z galerii wieczorem ma mieć datę sprzed dystrybutora, nie
    datę wyboru. Czas modyfikacji pliku się do tego nie nadaje: wybór pliku na
    Androidzie kopiuje go do pamięci podręcznej, więc „modyfikacja” to chwila
    kopiowania. Brak EXIF-u, zera w dacie albo data z przyszłości → None
    (wywołujący bierze wtedy dzisiejszą)."""
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


__all__ = [
    "DNI_PRZYPOMNIENIA_SZKICU",
    "MAKS_DLUGOSC_OPISU_SZKICU",
    "RODZAJE_SZKICU",
    "TABELA_SZKICOW",
    "czas_zdjecia",
    "dodaj_szkic",
    "dodaj_szkic_z_bajtow",
    "dodaj_szkice_z_plikow",
    "opisz_szkic",
    "pobierz_szkic",
    "pobierz_szkice",
    "podsumowanie_szkicow",
    "przenies_szkic",
    "zamknij_szkic",
]
