"""Automatyczna kopia zapasowa: ZIP z bazą, zdjęciami i koszem, co N dni, do wskazanego
folderu, z rotacją do K ostatnich.
- To samo archiwum co kopia ręczna (`zapisz_archiwum_kopii`), wczytywane zwykłym
  „Wczytaj kopię bazy”.
- Starsze kopie znikają dopiero po sprawdzeniu nowej: `PRAGMA quick_check`, zapis do
  `.czesc`, test CRC, zmiana nazwy na `.zip`, rotacja.
- Rotacja rusza tylko własne pliki `flota_kopia_RRRR-MM-DD_GGMMSS.zip` w tym folderze.
- Ustawienia `kopia_*` należą do urządzenia i przeżywają wczytanie kopii
  (`ustawienia_kopii_urzadzenia`, `przywroc_ustawienia_kopii_urzadzenia`).
Folder domyślny: Android — Documents/Flota Mobile (przeżywa odinstalowanie, Android 11+
bez uprawnień); komputer — `kopie/` obok bazy."""

import errno
import io
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import uuid
import zipfile
from datetime import datetime, timedelta
from typing import Any

import log

from .stale import BAZA_DANYCH, FOLDER_KOSZ, FOLDER_ZALACZNIKI, STORAGE_PATH
from .pamiec import z_pamieci
from .polaczenie import polacz_baze
from .ustawienia import PRZEDROSTEK_USTAWIEN_NOWOSCI, pobierz_ustawienie, usun_ustawienie, zapisz_ustawienie


# ============================================================================
# USTAWIENIA
# ============================================================================
# Wszystkie klucze zaczynają się od `kopia_` — po przedrostku wczytanie kopii odkłada je
# i przywraca.

PRZEDROSTEK_USTAWIEN_KOPII = "kopia_"
KLUCZ_KOPIA_AUTOMATYCZNA = "kopia_automatyczna"
KLUCZ_KOPIA_CO_DNI = "kopia_co_dni"
KLUCZ_KOPIA_ILE = "kopia_ile"
KLUCZ_KOPIA_FOLDER = "kopia_folder"
KLUCZ_KOPIA_OSTATNIA_AUTO = "kopia_ostatnia_auto"
KLUCZ_KOPIA_OSTATNIA_RECZNA = "kopia_ostatnia_reczna"
KLUCZ_KOPIA_BLAD = "kopia_blad"

KOPIA_CO_DNI_OPCJE = [1, 3, 7, 14, 30]
KOPIA_CO_DNI_DOMYSLNIE = 7
KOPIA_ILE_OPCJE = [2, 3, 5, 10, 20]
KOPIA_ILE_DOMYSLNIE = 5

NAZWA_FOLDERU_KOPII_ANDROID = "Flota Mobile"
PRZEDROSTEK_PLIKU_KOPII = "flota_kopia_"
KONCOWKA_CZESCI_KOPII = ".czesc"

# Data i godzina w nazwie, od roku do sekundy: kolejność nazw jest kolejnością
# kopii, więc rotacja nie musi ufać datom modyfikacji (kopiowanie folderu na
# inny dysk albo synchronizacja w chmurze potrafią je przestawić).
_WZOR_PLIKU_KOPII = re.compile(r"^flota_kopia_(\d{4})-(\d{2})-(\d{2})_(\d{2})(\d{2})(\d{2})\.zip$")

# Zdjęcia są już skompresowane: deflate mieliłby je na telefonie sekundami
# i nic by nie zyskał. Baza i reszta plików idą skompresowane jak dotąd.
_BEZ_KOMPRESJI = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".gif")

# Zapas ponad wyliczony rozmiar kopii: nagłówki ZIP-a, migawka bazy w katalogu
# tymczasowym, pliki dopisane w trakcie.
_ZAPAS_MIEJSCA = 4 * 1024 * 1024


def _liczba_z_opcji(wartosc, opcje, domyslna):
    try:
        liczba = int(wartosc)
    except (TypeError, ValueError):
        return domyslna
    return liczba if liczba in opcje else domyslna


def zapisz_kopie_automatyczna(wlaczona):
    zapisz_ustawienie(KLUCZ_KOPIA_AUTOMATYCZNA, "1" if wlaczona else "0")


def zapisz_kopie_co_dni(dni):
    zapisz_ustawienie(KLUCZ_KOPIA_CO_DNI, str(_liczba_z_opcji(dni, KOPIA_CO_DNI_OPCJE, KOPIA_CO_DNI_DOMYSLNIE)))


def pobierz_ile_kopii():
    return _liczba_z_opcji(pobierz_ustawienie(KLUCZ_KOPIA_ILE), KOPIA_ILE_OPCJE, KOPIA_ILE_DOMYSLNIE)


def zapisz_ile_kopii(ile):
    zapisz_ustawienie(KLUCZ_KOPIA_ILE, str(_liczba_z_opcji(ile, KOPIA_ILE_OPCJE, KOPIA_ILE_DOMYSLNIE)))


# ============================================================================
#  FOLDER
# ============================================================================

def na_androidzie():
    """Python we Flecie na Androidzie. `sys.platform` mówi tam „linux” (aż do
    Pythona 3.13), więc platformę zdradza środowisko procesu aplikacji."""
    return (sys.platform == "android" or hasattr(sys, "getandroidapilevel")
            or bool(os.environ.get("ANDROID_ROOT") and os.environ.get("ANDROID_DATA")))


def domyslny_folder_kopii():
    """Documents/Flota Mobile na telefonie, `kopie/` obok bazy na komputerze. Nie folder
    aplikacji — ginie z nią (odinstalowanie, „Wyczyść dane”); w Dokumentach i Pobranych
    Android 11+ pozwala pisać bez uprawnień."""
    if na_androidzie():
        pamiec = os.environ.get("EXTERNAL_STORAGE") or "/storage/emulated/0"
        return os.path.join(pamiec, "Documents", NAZWA_FOLDERU_KOPII_ANDROID)
    return os.path.abspath(os.path.join(STORAGE_PATH, "kopie"))


def _wlasny_folder(wartosc):
    """Folder wskazany w Ustawieniach albo None. Ścieżka, która na TYM systemie
    nie jest bezwzględna (`E:\\…` czytane na telefonie), nie liczy się wcale."""
    wartosc = (wartosc or "").strip()
    return wartosc if wartosc and os.path.isabs(wartosc) else None


def pobierz_folder_kopii():
    return _wlasny_folder(pobierz_ustawienie(KLUCZ_KOPIA_FOLDER)) or domyslny_folder_kopii()


def czy_folder_kopii_domyslny():
    return _wlasny_folder(pobierz_ustawienie(KLUCZ_KOPIA_FOLDER)) is None


def zapisz_folder_kopii(sciezka):
    """Pusta ścieżka albo None — powrót do folderu domyślnego."""
    if sciezka:
        zapisz_ustawienie(KLUCZ_KOPIA_FOLDER, os.path.abspath(sciezka))
    else:
        usun_ustawienie(KLUCZ_KOPIA_FOLDER)


def _opis_bledu_zapisu(ex):
    """Błąd systemu plików słowami, które coś mówią na ekranie telefonu."""
    numer = getattr(ex, "errno", None)
    if isinstance(ex, PermissionError) or numer in (errno.EACCES, errno.EPERM, errno.EROFS):
        if na_androidzie():
            return "brak dostępu do folderu — na telefonie wybierz folder w Dokumentach albo Pobranych"
        return "brak dostępu do folderu"
    if numer == errno.ENOSPC:
        return "za mało miejsca w pamięci"
    if isinstance(ex, FileNotFoundError) or numer == errno.ENOENT:
        return "folder jest niedostępny (odłączona karta albo dysk?)"
    return f"błąd zapisu: {getattr(ex, 'strerror', None) or ex}"


def sprawdz_folder_kopii(sciezka) -> tuple[bool, str]:
    """(True, "") gdy aplikacja może w tym folderze zakładać pliki.

    Sprawdzane plikiem próbnym, nie `os.access`: na Androidzie o dostępie
    decyduje MIEJSCE (Dokumenty i Pobrane tak, korzeń pamięci i karta SD nie),
    a `os.access` potrafi powiedzieć „tak” na wyrost."""
    if not sciezka:
        return False, "nie wskazano folderu"
    probny = os.path.join(sciezka, f".flota_proba_{uuid.uuid4().hex}")
    try:
        os.makedirs(sciezka, exist_ok=True)
        with open(probny, "wb") as plik:
            plik.write(b"ok")
        os.remove(probny)
    except OSError as ex:
        return False, _opis_bledu_zapisu(ex)
    return True, ""


# ============================================================================
#  ARCHIWUM — to samo dla kopii ręcznej i automatycznej
# ============================================================================

class BladKopii(Exception):
    """Kopia nie powstała z powodu, który da się powiedzieć człowiekowi."""


def _foldery_kopii():
    # Kosz obowiązkowo: baza niesie migawki pojazdów z kosza, więc bez jego
    # zdjęć wczytanie odtworzyłoby kosz z pustymi odsyłaczami do plików.
    return (FOLDER_ZALACZNIKI, FOLDER_KOSZ)


def skopiuj_baze(sciezka_zrodlowa, sciezka_docelowa):
    """Spójna kopia pliku bazy przez API kopii SQLite — także wtedy, gdy ktoś
    akurat pisze (zwykłe kopiowanie pliku złapałoby go w pół transakcji)."""
    zrodlo = sqlite3.connect(sciezka_zrodlowa)
    cel = sqlite3.connect(sciezka_docelowa)
    try:
        zrodlo.backup(cel)
    finally:
        cel.close()
        zrodlo.close()


def _sprawdz_spojnosc_migawki(sciezka):
    conn = sqlite3.connect(sciezka)
    try:
        wynik = conn.execute("PRAGMA quick_check").fetchone()
    finally:
        conn.close()
    if not wynik or wynik[0] != "ok":
        raise BladKopii("baza nie przeszła kontroli spójności, więc starsze kopie zostały nietknięte")


def zapisz_archiwum_kopii(cel, sprawdz_spojnosc=False):
    """Archiwum kopii (baza + załączniki + kosz) do pliku albo obiektu plikowego `cel`,
    w formacie „Wczytaj kopię bazy” (main.wykonaj_import). `sprawdz_spojnosc=True` —
    `PRAGMA quick_check` na migawce przed zapisem. Na końcu `manifest.json` (wersja
    schematu, liczba wpisów, suma kontrolna, bilans załączników) do podglądu przed
    wczytaniem."""
    nazwa_bazy = os.path.basename(BAZA_DANYCH)
    with tempfile.TemporaryDirectory() as tmp:
        migawka = os.path.join(tmp, nazwa_bazy)
        if os.path.exists(BAZA_DANYCH):
            skopiuj_baze(BAZA_DANYCH, migawka)
            if sprawdz_spojnosc:
                _sprawdz_spojnosc_migawki(migawka)
        with zipfile.ZipFile(cel, "w", zipfile.ZIP_DEFLATED) as zf:
            if os.path.exists(migawka):
                zf.write(migawka, arcname=nazwa_bazy)
            for folder in _foldery_kopii():
                if not os.path.isdir(folder):
                    continue
                nazwa_folderu = os.path.basename(folder)
                for korzen, _, pliki in os.walk(folder):
                    for nazwa_pliku in pliki:
                        pelna = os.path.join(korzen, nazwa_pliku)
                        arcname = os.path.join(nazwa_folderu, os.path.relpath(pelna, folder))
                        kompresja = (zipfile.ZIP_STORED if nazwa_pliku.lower().endswith(_BEZ_KOMPRESJI)
                                     else zipfile.ZIP_DEFLATED)
                        try:
                            zf.write(pelna, arcname=arcname, compress_type=kompresja)
                        except FileNotFoundError:
                            # Plik zniknął między listowaniem a zapisem: sprzątanie
                            # kosza albo usunięcie załącznika w tej samej chwili.
                            # Archiwum bez niego zgadza się z tym, co baza zaraz opisze.
                            log.polkniety(f"plik zniknął w trakcie kopii: {arcname}")
            if os.path.exists(migawka):
                # Manifest na końcu: bilans załączników liczy się z tego, co
                # faktycznie spakowano. Import dopiero tu — manifest liczy wpisy
                # tabelami z kosza i czyta schemat z migracji, a oba moduły leżą
                # w pakiecie PÓŹNIEJ niż ten (patrz db/manifest_kopii.py).
                from .manifest_kopii import dopisz_manifest_kopii
                dopisz_manifest_kopii(zf, migawka)


def przygotuj_zip_kopii():
    """Archiwum kopii w pamięci — dla ręcznej „Kopii zapasowej bazy”, która
    oddaje bajty oknu zapisu pliku."""
    bufor = io.BytesIO()
    zapisz_archiwum_kopii(bufor)
    return bufor.getvalue()


def sprawdz_archiwum_kopii(sciezka) -> tuple[bool, str]:
    """(True, "") gdy archiwum ma w środku bazę, a każdy plik zgadza się ze
    swoją sumą CRC. Czyta całe archiwum — na zdjęciach to sekunda, ale tylko
    tak wiadomo, że plik nadaje się do wczytania."""
    try:
        with zipfile.ZipFile(sciezka) as zf:
            if os.path.basename(BAZA_DANYCH) not in zf.namelist():
                return False, "w archiwum brakuje pliku bazy"
            uszkodzony = zf.testzip()
            if uszkodzony is not None:
                return False, f"uszkodzony plik w archiwum: {uszkodzony}"
    except Exception as ex:
        # Szeroko z rozmysłem: zepsuty strumień deflate rzuca zlib.error, ucięty
        # plik EOFError — a każde z nich znaczy to samo: tej kopii nie wczytasz.
        return False, f"archiwum nie daje się odczytać ({ex})"
    return True, ""


# ============================================================================
#  STAN — kokpit, dzwonek i Ustawienia pytają o to samo
# ============================================================================

def _czas(tekst, teraz):
    """Moment z ustawień albo None. Data z przyszłości (zegar telefonu cofnięty
    po kopii) też jest None — inaczej kopia nie byłaby należna aż do niej."""
    try:
        moment = datetime.fromisoformat(tekst) if tekst else None
    except ValueError:
        return None
    if moment is not None and moment.date() > teraz.date():
        return None
    return moment


def _ustawienia_kopii():
    """Wszystkie klucze `kopia_*` jednym zapytaniem — kokpit pyta przy każdym
    wejściu, a każde `pobierz_ustawienie` to osobne połączenie z bazą."""
    with polacz_baze() as conn:
        wiersze = conn.execute(
            "SELECT klucz, wartosc FROM ustawienia WHERE klucz LIKE ? ESCAPE '\\'",
            (PRZEDROSTEK_USTAWIEN_KOPII.replace("_", "\\_") + "%",),
        ).fetchall()
    return dict(wiersze)


def _ma_dane():
    """Pusta instalacja nie ma czego chronić — bez tego świeżo zainstalowana
    aplikacja witałaby ostrzeżeniem o kopii, zanim cokolwiek się w niej wpisze."""
    with polacz_baze() as conn:
        if conn.execute("SELECT EXISTS(SELECT 1 FROM samochody)").fetchone()[0]:
            return True
        try:
            return bool(conn.execute("SELECT EXISTS(SELECT 1 FROM kosz_pojazdy)").fetchone()[0])
        except sqlite3.OperationalError:
            return False


def _policz_stan_kopii():
    teraz = datetime.now()
    u = _ustawienia_kopii()
    wlaczona = (u.get(KLUCZ_KOPIA_AUTOMATYCZNA) or "1") == "1"
    co_dni = _liczba_z_opcji(u.get(KLUCZ_KOPIA_CO_DNI), KOPIA_CO_DNI_OPCJE, KOPIA_CO_DNI_DOMYSLNIE)
    auto = _czas(u.get(KLUCZ_KOPIA_OSTATNIA_AUTO), teraz)
    reczna = _czas(u.get(KLUCZ_KOPIA_OSTATNIA_RECZNA), teraz)
    ostatnia = max([m for m in (auto, reczna) if m is not None], default=None)
    dni = (teraz.date() - ostatnia.date()).days if ostatnia else None
    dni_auto = (teraz.date() - auto.date()).days if auto else None
    blad = u.get(KLUCZ_KOPIA_BLAD) or None
    ma_dane = _ma_dane()

    # Należna — harmonogram kopii AUTOMATYCZNEJ, liczony od niej samej: ręczny
    # eksport udostępniony na Dysk nie przesuwa rotacji w folderze.
    nalezna = wlaczona and ma_dane and (dni_auto is None or dni_auto >= co_dni)

    # Zaległa — dane bez świeżej kopii JAKIEJKOLWIEK. Przy włączonej kopii
    # automatycznej i braku błędu nie mówimy nic: ten sam start zaraz ją zrobi,
    # a ostrzeżenie mignęłoby tylko na sekundę. Mówimy, gdy kopia się nie udała
    # albo gdy jest wyłączona.
    stara = dni is None or dni >= co_dni
    zalegla = ma_dane and stara and (not wlaczona or blad is not None)

    return {
        "wlaczona": wlaczona,
        "co_dni": co_dni,
        "ile": _liczba_z_opcji(u.get(KLUCZ_KOPIA_ILE), KOPIA_ILE_OPCJE, KOPIA_ILE_DOMYSLNIE),
        "folder": _wlasny_folder(u.get(KLUCZ_KOPIA_FOLDER)) or domyslny_folder_kopii(),
        "folder_domyslny": _wlasny_folder(u.get(KLUCZ_KOPIA_FOLDER)) is None,
        "ostatnia": ostatnia,
        "ostatnia_auto": auto,
        "ostatnia_reczna": reczna,
        "rodzaj_ostatniej": None if ostatnia is None else ("automatyczna" if ostatnia == auto else "ręczna"),
        "dni": dni,
        "blad": blad,
        "ma_dane": ma_dane,
        "nalezna": nalezna,
        "zalegla": zalegla,
    }


def stan_kopii_zapasowej() -> dict[str, Any]:
    """Wszystko dla kokpitu, dzwonka i Ustawień jednym odczytem, z pamięci do zapisu lub
    zmiany daty. Klucze: wlaczona, co_dni, ile, folder, folder_domyslny, ostatnia
    (świeższa z automatycznej i ręcznej), ostatnia_auto, ostatnia_reczna,
    rodzaj_ostatniej, dni, blad, ma_dane, nalezna (kopia ma ruszyć), zalegla
    (ostrzegać)."""
    return z_pamieci("kopia_zapasowa", None, _policz_stan_kopii)


def kopia_w_toku():
    return _ZAMEK_KOPII.locked()


def zanotuj_kopie_reczna():
    """Kopia ręczna zapisana albo udostępniona — liczy się do „ostatniej kopii”
    na kokpicie, ale nie przesuwa harmonogramu kopii automatycznej."""
    zapisz_ustawienie(KLUCZ_KOPIA_OSTATNIA_RECZNA, datetime.now().isoformat(timespec="seconds"))


# ============================================================================
#  KOPIE W FOLDERZE
# ============================================================================

def _data_z_nazwy(nazwa):
    dopasowanie = _WZOR_PLIKU_KOPII.match(nazwa)
    if not dopasowanie:
        return None
    try:
        return datetime(*(int(x) for x in dopasowanie.groups()))
    except ValueError:
        return None


def _nazwy_kopii(folder):
    """Nazwy własnych kopii w folderze, od najnowszej. Same pliki — katalog
    o pasującej nazwie nie jest kopią."""
    try:
        nazwy = os.listdir(folder)
    except OSError:
        return []
    return sorted((n for n in nazwy if _data_z_nazwy(n) is not None
                   and os.path.isfile(os.path.join(folder, n))), reverse=True)


def lista_kopii(folder=None) -> list[dict[str, Any]]:
    """Kopie automatyczne w folderze (domyślnie w bieżącym), od najnowszej:
    {nazwa, sciezka, data, rozmiar}. Pliki z innymi nazwami nie istnieją dla
    tej listy — dokładnie tak samo jak dla rotacji."""
    folder = folder or pobierz_folder_kopii()
    kopie = []
    for nazwa in _nazwy_kopii(folder):
        sciezka = os.path.join(folder, nazwa)
        try:
            rozmiar = os.path.getsize(sciezka)
        except OSError:
            continue
        kopie.append({"nazwa": nazwa, "sciezka": sciezka, "data": _data_z_nazwy(nazwa), "rozmiar": rozmiar})
    return kopie


def _rotuj_kopie(folder, ile, zostaw):
    """Kasuje kopie ponad `ile` najnowszych i resztki po przerwanym zapisie.
    Nowej kopii (`zostaw`) nie rusza w żadnym wypadku. Zwraca liczbę
    skasowanych kopii."""
    usuniete = 0
    for nazwa in _nazwy_kopii(folder)[max(1, ile):]:
        sciezka = os.path.join(folder, nazwa)
        if os.path.abspath(sciezka) == os.path.abspath(zostaw):
            continue
        try:
            os.remove(sciezka)
            usuniete += 1
        except OSError:
            log.polkniety(f"rotacja kopii zapasowych: {nazwa}")
    # `.czesc` po kopii przerwanej w pół zapisu (aplikacja zamknięta, telefon
    # wyłączony). Zamek pilnuje, że żadna inna kopia nie pisze w tej chwili.
    try:
        resztki = [n for n in os.listdir(folder) if n.endswith(KONCOWKA_CZESCI_KOPII)
                   and _data_z_nazwy(n[:-len(KONCOWKA_CZESCI_KOPII)]) is not None]
    except OSError:
        resztki = []
    for nazwa in resztki:
        try:
            os.remove(os.path.join(folder, nazwa))
        except OSError:
            log.polkniety(f"sprzątanie po przerwanej kopii: {nazwa}")
    return usuniete


def _nowa_sciezka_kopii(folder, teraz):
    """Nazwa z datą i godziną; dwie kopie w tej samej sekundzie dostają kolejne."""
    for przesuniecie in range(120):
        moment = teraz + timedelta(seconds=przesuniecie)
        sciezka = os.path.join(folder, moment.strftime(PRZEDROSTEK_PLIKU_KOPII + "%Y-%m-%d_%H%M%S.zip"))
        if not os.path.exists(sciezka):
            return sciezka
    raise BladKopii("nie da się nadać nazwy nowej kopii")


def _sprawdz_miejsce(folder):
    """Brak miejsca wykryty PRZED zapisem — zamiast w połowie archiwum."""
    potrzeba = os.path.getsize(BAZA_DANYCH) if os.path.exists(BAZA_DANYCH) else 0
    for katalog in _foldery_kopii():
        for korzen, _, pliki in os.walk(katalog):
            for nazwa in pliki:
                try:
                    potrzeba += os.path.getsize(os.path.join(korzen, nazwa))
                except OSError:
                    continue
    try:
        wolne = shutil.disk_usage(folder).free
    except OSError:
        return  # nie wiadomo — o miejscu powie najwyżej sam zapis
    if wolne < potrzeba + _ZAPAS_MIEJSCA:
        import utils
        raise BladKopii(f"za mało miejsca: kopia potrzebuje ok. {utils.formatuj_rozmiar(potrzeba)}, "
                        f"a wolne jest {utils.formatuj_rozmiar(wolne)}")


# ============================================================================
#  KOPIA
# ============================================================================

# Start aplikacji, powrót z tła i „Zrób teraz” potrafią trafić w tę samą chwilę.
# Druga kopia nie czeka w kolejce — zgłasza `w_toku` i kończy.
_ZAMEK_KOPII = threading.Lock()


def _zanotuj_wynik(udana, blad=None):
    try:
        if udana:
            zapisz_ustawienie(KLUCZ_KOPIA_OSTATNIA_AUTO, datetime.now().isoformat(timespec="seconds"))
            usun_ustawienie(KLUCZ_KOPIA_BLAD)
        else:
            zapisz_ustawienie(KLUCZ_KOPIA_BLAD, blad)
    except Exception:
        log.polkniety("zapis wyniku kopii zapasowej w ustawieniach")


def wykonaj_kopie(wymus=False) -> dict[str, Any]:
    """Kopia do folderu z rotacją; bez `wymus` tylko należna (start i powrót z tła
    wołają bez sprawdzania), `wymus=True` — „Zrób teraz”. Zwraca {ok, pominieta, w_toku,
    sciezka, rozmiar, usuniete, folder, blad}. Nie rzuca (woła ją wątek w tle): błąd
    zostaje w ustawieniach i dzienniku błędów."""
    wynik = {"ok": False, "pominieta": False, "w_toku": False, "sciezka": None,
             "rozmiar": 0, "usuniete": 0, "folder": None, "blad": None}
    if not wymus and not stan_kopii_zapasowej()["nalezna"]:
        wynik["pominieta"] = True
        return wynik
    if not _ZAMEK_KOPII.acquire(blocking=False):
        wynik["w_toku"] = True
        return wynik

    czesc = None
    try:
        folder = pobierz_folder_kopii()
        wynik["folder"] = folder
        os.makedirs(folder, exist_ok=True)
        _sprawdz_miejsce(folder)
        sciezka = _nowa_sciezka_kopii(folder, datetime.now())
        czesc = sciezka + KONCOWKA_CZESCI_KOPII
        zapisz_archiwum_kopii(czesc, sprawdz_spojnosc=True)
        poprawne, powod = sprawdz_archiwum_kopii(czesc)
        if not poprawne:
            raise BladKopii(f"zapisane archiwum nie przeszło sprawdzenia: {powod}")
        os.replace(czesc, sciezka)
        czesc = None
        wynik.update(ok=True, sciezka=sciezka, rozmiar=os.path.getsize(sciezka))
        _zanotuj_wynik(True)
        wynik["usuniete"] = _rotuj_kopie(folder, pobierz_ile_kopii(), zostaw=sciezka)
        log.zapisz(f"Kopia zapasowa: {os.path.basename(sciezka)}, {wynik['rozmiar']} B, "
                   f"rotacja usunęła {wynik['usuniete']}")
    except BladKopii as ex:
        wynik["blad"] = str(ex)
    except sqlite3.DatabaseError as ex:
        # Plik bazy tak zepsuty, że nie da się nawet zrobić migawki albo jej
        # sprawdzić — dokładnie ten wypadek, przed którym kopie mają chronić.
        wynik["blad"] = f"baza jest uszkodzona ({ex}), więc starsze kopie zostały nietknięte"
    except OSError as ex:
        wynik["blad"] = _opis_bledu_zapisu(ex)
    except Exception as ex:
        wynik["blad"] = f"nieoczekiwany błąd: {ex}"
        log.blad("nieoczekiwany błąd kopii zapasowej")
    finally:
        if czesc is not None and os.path.exists(czesc):
            try:
                os.remove(czesc)
            except OSError:
                log.polkniety("sprzątanie niedokończonej kopii zapasowej")
        _ZAMEK_KOPII.release()

    if wynik["blad"]:
        log.blad(f"Kopia zapasowa nie powstała ({wynik['folder']}): {wynik['blad']}", wyjatek=False)
        _zanotuj_wynik(False, wynik["blad"])
    return wynik


# ============================================================================
# USTAWIENIA URZĄDZENIA PRZY WCZYTYWANIU KOPII
# ============================================================================
# Wczytanie kopii podmienia CAŁĄ bazę z ustawieniami, a folder, rytm, liczba i daty
# kopii opisują urządzenie — dlatego są odkładane i przywracane.

# Ten sam los czeka „Co nowego”: to, które wydania ten telefon już pokazał,
# opisuje urządzenie, nie dane — kopia z drugiego telefonu pokazałaby nowości
# jeszcze raz albo schowała te, których tu nikt nie widział (db/nowosci.py).
PRZEDROSTKI_USTAWIEN_URZADZENIA = (PRZEDROSTEK_USTAWIEN_KOPII, PRZEDROSTEK_USTAWIEN_NOWOSCI)


def _warunek_ustawien_urzadzenia():
    """(warunek WHERE, parametry) na klucze z przedrostkami urządzenia."""
    warunek = " OR ".join(["klucz LIKE ? ESCAPE '\\'"] * len(PRZEDROSTKI_USTAWIEN_URZADZENIA))
    return warunek, tuple(p.replace("_", "\\_") + "%" for p in PRZEDROSTKI_USTAWIEN_URZADZENIA)


def ustawienia_kopii_urzadzenia():
    """Ustawienia urządzenia tej bazy (`kopia_*` i `nowosci_*`) — do odłożenia
    przed wczytaniem kopii. Pusty słownik, gdy bazy nie da się przeczytać
    (wtedy nie ma czego chronić)."""
    warunek, parametry = _warunek_ustawien_urzadzenia()
    try:
        with polacz_baze() as conn:
            return dict(conn.execute(
                f"SELECT klucz, wartosc FROM ustawienia WHERE {warunek}", parametry).fetchall())
    except sqlite3.Error:
        log.polkniety("odczyt ustawień kopii przed wczytaniem kopii")
        return {}


def przywroc_ustawienia_kopii_urzadzenia(ustawienia):
    """Po wczytaniu kopii: ustawienia urządzenia wracają dokładnie do stanu
    sprzed — także te, których wtedy nie było (wraca wartość domyślna)."""
    warunek, parametry = _warunek_ustawien_urzadzenia()
    with polacz_baze() as conn:
        conn.execute(f"DELETE FROM ustawienia WHERE {warunek}", parametry)
        conn.executemany("INSERT INTO ustawienia (klucz, wartosc) VALUES (?, ?)",
                         list((ustawienia or {}).items()))


__all__ = [
    "BladKopii",
    "KLUCZ_KOPIA_AUTOMATYCZNA",
    "KLUCZ_KOPIA_BLAD",
    "KLUCZ_KOPIA_CO_DNI",
    "KLUCZ_KOPIA_FOLDER",
    "KLUCZ_KOPIA_ILE",
    "KLUCZ_KOPIA_OSTATNIA_AUTO",
    "KLUCZ_KOPIA_OSTATNIA_RECZNA",
    "KONCOWKA_CZESCI_KOPII",
    "KOPIA_CO_DNI_DOMYSLNIE",
    "KOPIA_CO_DNI_OPCJE",
    "KOPIA_ILE_DOMYSLNIE",
    "KOPIA_ILE_OPCJE",
    "NAZWA_FOLDERU_KOPII_ANDROID",
    "PRZEDROSTEK_PLIKU_KOPII",
    "PRZEDROSTEK_USTAWIEN_KOPII",
    "PRZEDROSTKI_USTAWIEN_URZADZENIA",
    "czy_folder_kopii_domyslny",
    "domyslny_folder_kopii",
    "kopia_w_toku",
    "lista_kopii",
    "na_androidzie",
    "pobierz_folder_kopii",
    "pobierz_ile_kopii",
    "przygotuj_zip_kopii",
    "przywroc_ustawienia_kopii_urzadzenia",
    "skopiuj_baze",
    "sprawdz_archiwum_kopii",
    "sprawdz_folder_kopii",
    "stan_kopii_zapasowej",
    "ustawienia_kopii_urzadzenia",
    "wykonaj_kopie",
    "zanotuj_kopie_reczna",
    "zapisz_archiwum_kopii",
    "zapisz_folder_kopii",
    "zapisz_ile_kopii",
    "zapisz_kopie_automatyczna",
    "zapisz_kopie_co_dni",
]
