"""Końce linii — polityka pilnowana, a nie pamiętana.

Uwaga „pamiętaj o CRLF" wracała w czterech notatkach projektowych z rzędu, za
każdym razem jako pułapka do zapamiętania: skrypt zapisuje LF, cały plik
pokazuje się jako zmieniony, diff jest bezużyteczny. To nie był problem
warsztatowy, tylko konfiguracyjny — i jako taki nadaje się do sprawdzania
maszyną, a nie do zapamiętywania.

Projekt jest na LF (patrz `.gitattributes`). Ten plik tego pilnuje, a uruchomiony
wprost — naprawia:

    python tests/test_konce_linii.py            # raport
    python tests/test_konce_linii.py --napraw   # przepisanie na LF
"""

import pathlib
import sys

sys.path[:0] = [str(pathlib.Path(__file__).resolve().parent), str(pathlib.Path(__file__).resolve().parents[1])]

import pytest  # noqa: E402


KORZEN = pathlib.Path(__file__).resolve().parents[1]

# Katalogi spoza repozytorium albo z danymi użytkownika.
POMIJANE_KATALOGI = {
    ".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "build", "dist", "site", "zalaczniki", "zalaczniki_bak", "zalaczniki_odroczone",
    "kosz_zalaczniki", "kosz_zalaczniki_bak", "node_modules",
}

# Rozszerzenia, które w tym projekcie są tekstem. Świadomie lista, a nie
# zgadywanie po zawartości: plik binarny błędnie uznany za tekst dałby fałszywe
# trafienie, którego nikt by nie umiał naprawić.
ROZSZERZENIA_TEKSTOWE = {
    ".py", ".sql", ".md", ".txt", ".ini", ".cfg", ".toml", ".json",
    ".yml", ".yaml", ".html", ".css", ".js",
}

NAZWY_TEKSTOWE = {".gitignore", ".gitattributes"}

BOM_UTF8 = b"\xef\xbb\xbf"


def pliki_tekstowe(korzen=None):
    korzen = pathlib.Path(korzen or KORZEN)
    znalezione = []
    for sciezka in sorted(korzen.rglob("*")):
        if not sciezka.is_file():
            continue
        if any(czesc in POMIJANE_KATALOGI for czesc in sciezka.relative_to(korzen).parts):
            continue
        if sciezka.suffix.lower() in ROZSZERZENIA_TEKSTOWE or sciezka.name in NAZWY_TEKSTOWE:
            znalezione.append(sciezka)
    return znalezione


def z_crlf(korzen=None):
    """Pliki zawierające choć jeden CRLF, z liczbą wystąpień."""
    wynik = []
    for sciezka in pliki_tekstowe(korzen):
        dane = sciezka.read_bytes()
        ile = dane.count(b"\r\n")
        if ile:
            wynik.append((sciezka, ile))
    return wynik


def z_samotnym_cr(korzen=None):
    """Stary macowy koniec linii (samo CR) — rzadkość, ale psuje wszystko po cichu."""
    wynik = []
    for sciezka in pliki_tekstowe(korzen):
        dane = sciezka.read_bytes()
        if dane.replace(b"\r\n", b"").count(b"\r"):
            wynik.append(sciezka)
    return wynik


def z_bom(korzen=None):
    """UTF-8 BOM — Notatnik i `>` w PowerShellu dokładają go po cichu."""
    return [s for s in pliki_tekstowe(korzen) if s.read_bytes().startswith(BOM_UTF8)]


def napraw(korzen=None):
    """Przepisuje pliki na LF i zdejmuje BOM. Zwraca listę zmienionych."""
    zmienione = []
    for sciezka in pliki_tekstowe(korzen):
        dane = sciezka.read_bytes()
        naprawione = dane
        if naprawione.startswith(BOM_UTF8):
            naprawione = naprawione[len(BOM_UTF8):]
        naprawione = naprawione.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        if naprawione != dane:
            sciezka.write_bytes(naprawione)
            zmienione.append(sciezka)
    return zmienione


def _opis(sciezki):
    return "\n".join(f"  {s.relative_to(KORZEN).as_posix()}" for s in sciezki)


# ------------------------------------------------------------------- testy


def test_zaden_plik_tekstowy_nie_ma_crlf():
    znalezione = z_crlf()
    assert znalezione == [], (
        "pliki z końcami linii CRLF (projekt jest na LF — patrz .gitattributes):\n"
        + "\n".join(f"  {s.relative_to(KORZEN).as_posix()}  ({ile} razy)" for s, ile in znalezione)
        + "\n\nNaprawa: python tests/test_konce_linii.py --napraw"
    )


def test_zaden_plik_nie_ma_samotnego_cr():
    znalezione = z_samotnym_cr()
    assert znalezione == [], "pliki ze starym macowym CR:\n" + _opis(znalezione)


def test_zaden_plik_nie_ma_bom():
    znalezione = z_bom()
    assert znalezione == [], (
        "pliki z UTF-8 BOM (dokłada go Notatnik i przekierowanie `>` w PowerShellu):\n"
        + _opis(znalezione)
        + "\n\nNaprawa: python tests/test_konce_linii.py --napraw"
    )


def test_polityka_konca_linii_jest_zapisana():
    """Sam test nie wystarczy: bez `.gitattributes` git przy każdym pobraniu
    repozytorium na Windowsie przywróci CRLF i test zacznie padać bez powodu."""
    plik = KORZEN / ".gitattributes"
    assert plik.exists(), "brak .gitattributes — bez niego polityka nie przetrwa `git clone`"

    tresc = plik.read_text(encoding="utf-8")
    linie = [w.split("#")[0].strip() for w in tresc.splitlines()]
    assert any(w.startswith("*") and "eol=lf" in w for w in linie), (
        ".gitattributes nie wymusza `eol=lf` dla wszystkich plików — `text=auto` samo "
        "nie wystarczy, bo o końcach linii w kopii roboczej decyduje wtedy `core.autocrlf` "
        "z ustawień maszyny"
    )


def test_naprawa_dziala(tmp_path):
    """Test naprawiacza, nie projektu — żeby `--napraw` nie okazał się pusty
    w dniu, w którym będzie potrzebny."""
    (tmp_path / "z_crlf.py").write_bytes(b"a = 1\r\nb = 2\r\n")
    (tmp_path / "z_bom.md").write_bytes(BOM_UTF8 + b"# tytul\n")
    (tmp_path / "juz_dobry.py").write_bytes(b"c = 3\n")
    (tmp_path / "obrazek.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    zmienione = {s.name for s in napraw(tmp_path)}

    assert zmienione == {"z_crlf.py", "z_bom.md"}
    assert (tmp_path / "z_crlf.py").read_bytes() == b"a = 1\nb = 2\n"
    assert (tmp_path / "z_bom.md").read_bytes() == b"# tytul\n"
    assert (tmp_path / "obrazek.png").read_bytes() == b"\x89PNG\r\n\x1a\n", "plik binarny ma zostać nietknięty"
    assert z_crlf(tmp_path) == []


def test_naprawiacz_pomija_katalogi_z_danymi(tmp_path):
    """`.venv` i foldery ze zdjęciami użytkownika nie są częścią projektu."""
    (tmp_path / ".venv" / "Lib").mkdir(parents=True)
    (tmp_path / ".venv" / "Lib" / "obce.py").write_bytes(b"x = 1\r\n")
    (tmp_path / "zalaczniki").mkdir()
    (tmp_path / "zalaczniki" / "opis.txt").write_bytes(b"tekst\r\n")
    (tmp_path / "moj.py").write_bytes(b"y = 2\r\n")

    zmienione = {s.name for s in napraw(tmp_path)}

    assert zmienione == {"moj.py"}


if __name__ == "__main__":
    if "--napraw" in sys.argv:
        zmienione = napraw()
        if zmienione:
            print(f"Przepisano na LF ({len(zmienione)}):")
            print(_opis(zmienione))
        else:
            print("Nie było czego naprawiać — cały projekt jest już na LF.")
    else:
        problemy = z_crlf()
        if problemy:
            print(f"Pliki z CRLF ({len(problemy)}):")
            for s, ile in problemy:
                print(f"  {s.relative_to(KORZEN).as_posix()}  ({ile} razy)")
            print("\nNaprawa: python tests/test_konce_linii.py --napraw")
        else:
            print(f"Wszystkie {len(pliki_tekstowe())} plików tekstowych ma końce linii LF.")
