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

from .stale import FOLDER_ODROCZONE, FOLDER_ZALACZNIKI


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

    # Jeśli to PDF, kopiujemy 1:1, bez zmiany rozszerzenia
    if rozszerzenie == ".pdf":
        nazwa = f"{uuid.uuid4().hex}.pdf"
        docelowa = os.path.join(folder, nazwa)
        shutil.copyfile(sciezka_zrodlowa, docelowa)
        return docelowa

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
            return docelowa
        except Exception:
            pass # W razie problemów z PIL przejdzie do fallbacka poniżej

    # Fallback, jeśli obraz nie dał się skompresować lub brak biblioteki
    shutil.copyfile(sciezka_zrodlowa, docelowa)
    return docelowa


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
        if os.path.exists(sciezka_wzgledna):
            os.remove(sciezka_wzgledna)
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
    "_upewnij_folder_odroczonych",
    "_upewnij_folder_zalacznikow",
    "anuluj_nowy_zalacznik",
    "polacz_zdjecia_w_pdf",
    "posprzataj_odroczone_zalaczniki",
    "przygotuj_nowy_zalacznik",
    "usun_plik_zalacznika",
    "zapisz_zalacznik",
    "zatwierdz_zalacznik",
]
