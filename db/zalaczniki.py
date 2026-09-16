"""Pliki załączników: zapis, dwuetapowe zatwierdzanie, sprzątanie."""

import os
import shutil
import time
import uuid
try:
    from PIL import Image, ImageOps
except ImportError:
    Image = None
    ImageOps = None

from .stale import FOLDER_KOSZ, FOLDER_ODROCZONE, FOLDER_ZALACZNIKI, STORAGE_PATH, TABELE_Z_ZALACZNIKIEM
from .polaczenie import polacz_baze


# Gdzie w bazie mieszkają ścieżki do plików. Poza kolumną `zalacznik` w tabelach
# z TABELE_Z_ZALACZNIKIEM jest jeszcze zdjęcie profilowe pojazdu.
KOLUMNY_ZE_SCIEZKAMI = [("samochody", "zdjecie_glowne")] + [(t, "zalacznik") for t in sorted(TABELE_Z_ZALACZNIKIEM)]


# ---------------------------------------------------------------- ścieżki w bazie
# Baza trzyma ścieżkę WZGLĘDNĄ wobec STORAGE_PATH, zawsze z '/':
# 'zalaczniki/<uuid>.jpg', w kolumnie `pliki` kosza 'kosz_zalaczniki/<plik>'.
# STORAGE_PATH zależy od urządzenia (Android: /data/user/0/<pakiet>/files/data,
# komputer: ""), więc ścieżka bezwzględna z jednego urządzenia na drugim wskazuje
# w pustkę. Sklejenie ze STORAGE_PATH dzieje się dopiero przy odczycie.
#
# Starsze bazy mają jeszcze ścieżki bezwzględne (Android) i względne z '\'
# (Windows). Odczyt rozumie wszystkie, więc migracji danych nie ma: każdą wartość
# z bazy, zanim trafi do os.path / shutil / ft.Image, przepuszcza się przez
# sciezka_pliku_zalacznika (albo utils.abs_zalacznik), a zapisuje przez
# wzgledna_sciezka_zalacznika.


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
    """Ścieżka do pliku wskazanego wartością z bazy — do odczytu, przeniesienia, skasowania.

    Najpierw pelna_sciezka_zalacznika. Gdy tam pliku nie ma, a wpis wskazuje
    folder aplikacji, szuka tej samej nazwy w tutejszym folderze o tej nazwie,
    potem w drugim (załączniki / kosz) — tak trafia dawny wpis bezwzględny
    z innego urządzenia. Nazwy to losowe UUID-y, więc dopasowanie jest
    jednoznaczne. Plików spoza folderów aplikacji (np. odroczonych) nie szuka.
    Gdy pliku nie ma nigdzie, oddaje ścieżkę pełną: komunikat o braku mówi
    wtedy o tym, co faktycznie stoi w bazie."""
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
    """Przepisuje nieaktualne ścieżki załączników na tutejsze i zwraca (naprawione, brakujace).

    Kopia zapasowa zrobiona na telefonie niesie dawne ścieżki bezwzględne
    (/data/user/0/<pakiet>/files/data/zalaczniki/...), których na komputerze nie
    ma. Pliki jadą w ZIP-ie i lądują w folderze załączników, ale wpis wskazuje
    katalog innego urządzenia. Tak samo w drugą stronę.

    Wpis, który wskazuje istniejący plik, zostaje, jaki jest — także dawny
    bezwzględny (bez migracji). Wpis bez pliku pod wskazaną ścieżką, którego
    plik znajduje sciezka_pliku_zalacznika, dostaje postać względną. Wpisów,
    których pliku nie ma nigdzie, NIE ruszamy — lepiej zostawić ślad, dokąd
    prowadziły, niż podmienić je na inną nieistniejącą ścieżkę."""
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
                # Korekta orientacji na podstawie tagu EXIF — zdjęcia z telefonu
                # (zwłaszcza robione z aparatem trzymanym pionowo) mają "surowe"
                # piksele obrócone, a poprawną orientację niesie wyłącznie tag
                # EXIF Orientation. PIL go NIE stosuje automatycznie przy zapisie,
                # więc bez tej korekty zapisany JPEG zostaje trwale "położony".
                img = ImageOps.exif_transpose(img)

                # Usunięcie kanału alfa (przezroczystości), aby bezpiecznie zapisać do JPEG
                if img.mode in ("RGBA", "P"):
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


def polacz_zdjecia_w_pdf(sciezki_zdjec):
    """Łączy kilka zdjęć w jeden wielostronicowy plik PDF (jedno zdjęcie = jedna
    strona), zapisany jako plik tymczasowy w FOLDER_ODROCZONE — sprzątany
    automatycznie po godzinie przez posprzataj_odroczone_zalaczniki, gdyby coś
    poszło nie tak i plik nie trafił finalnie do bazy. Koryguje orientację EXIF
    tak samo jak zapisz_zalacznik(). Zwraca ścieżkę do PDF-a albo None, jeśli się
    nie uda (brak Pillow albo któregoś z plików źródłowych)."""
    if Image is None or not sciezki_zdjec:
        return None

    obrazy = []
    try:
        for sciezka in sciezki_zdjec:
            if not os.path.exists(sciezka):
                continue
            img = Image.open(sciezka)
            img = ImageOps.exif_transpose(img)
            if img.mode != "RGB":
                img = img.convert("RGB")
            obrazy.append(img)

        if not obrazy:
            return None

        folder_tmp = _upewnij_folder_odroczonych()
        docelowa = os.path.join(folder_tmp, f"polaczone_{uuid.uuid4().hex}.pdf")
        pierwszy, reszta = obrazy[0], obrazy[1:]
        pierwszy.save(docelowa, "PDF", save_all=True, append_images=reszta)
        return docelowa
    except Exception:
        return None
    finally:
        for img in obrazy:
            try:
                img.close()
            except Exception:
                pass


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


__all__ = [
    "KOLUMNY_ZE_SCIEZKAMI",
    "_upewnij_folder_odroczonych",
    "_upewnij_folder_zalacznikow",
    "anuluj_nowy_zalacznik",
    "napraw_sciezki_zalacznikow",
    "pelna_sciezka_zalacznika",
    "polacz_zdjecia_w_pdf",
    "posprzataj_odroczone_zalaczniki",
    "przygotuj_nowy_zalacznik",
    "sciezka_pliku_zalacznika",
    "usun_plik_zalacznika",
    "wzgledna_sciezka_zalacznika",
    "zapisz_zalacznik",
    "zatwierdz_zalacznik",
]
