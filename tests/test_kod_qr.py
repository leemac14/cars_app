"""Własny koder QR (utils/kod_qr.py) — bez biblioteki, więc z własnym dowodem.

Przy pisaniu macierze porównano moduł po module z generatorem Nayukiego
(qrcodegen) — 5288 przypadków z wymuszoną maską i 661 z maską wybraną
automatycznie, wersje 1–10, wszystkie poziomy korekcji — a obrazy odczytały
OpenCV i ZXing (z tego drugiego korzysta większość czytników na Androidzie).
Te biblioteki nie są zależnością projektu, więc tutaj zostaje to, co da się
sprawdzić bez nich:

* wektory z normy i z jej przykładu („HELLO WORLD” 1-M), bity formatu i wersji;
* odczyt macierzy z powrotem — maska z informacji o formacie, kody w zygzaku,
  korekcja każdego bloku, dane bajt w bajt — dla każdej wersji i poziomu;
* odciski macierzy policzone przy porównaniu z Nayukim: zmiana kodera, która
  przestawi choć jeden moduł (np. inna kara za maskę), musi być świadoma.
"""

import hashlib
import io

import pytest
from PIL import Image

import sync
import utils
from utils import kod_qr


def _odcisk(macierz):
    bity = "".join("1" if m else "0" for wiersz in macierz for m in wiersz)
    return hashlib.sha256(bity.encode("ascii")).hexdigest()[:16]


# ------------------------------------------------------------ wektory z normy

def test_korekcja_z_przykladu_hello_world():
    """Przykład 1-M z normy (i z każdego poradnika): 16 kodów danych → 10 kodów korekcji."""
    dane = [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17]
    assert kod_qr.kody_korekcji(dane, 10) == [196, 35, 39, 119, 235, 215, 231, 226, 93, 23]


@pytest.mark.parametrize("poziom, bity", [
    ("L", "111011111000100"),
    ("M", "101010000010010"),
    ("Q", "011010101011111"),
    ("H", "001011010001001"),
])
def test_bity_formatu_przy_masce_zero(poziom, bity):
    assert format(kod_qr._bity_formatu(poziom, 0), "015b") == bity


def test_bity_wersji_siodmej():
    assert format(kod_qr._bity_wersji(7), "018b") == "000111110010010100"


# ------------------------------------------------------------ wersja i poziom

@pytest.mark.parametrize("dlugosc, poziom, oczekiwane", [
    (0, "L", (1, "H")),        # pusto: najmniejsza wersja, najwyższy poziom
    (14, "M", (1, "M")),       # pełna wersja 1-M
    (15, "M", (2, "Q")),       # wersja 2 i tak, a w niej mieści się Q
    (27, "M", (3, "Q")),       # link zaproszenia: wersja 3, podbita do Q
    (213, "M", (10, "M")),     # ostatni bajt, który się mieści
    (271, "L", (10, "L")),
])
def test_dobor_wersji_i_podbicie_poziomu(dlugosc, poziom, oczekiwane):
    assert kod_qr.dobierz_wersje(dlugosc, poziom) == oczekiwane


@pytest.mark.parametrize("dlugosc, poziom", [(214, "M"), (272, "L")])
def test_za_dlugi_tekst_rzuca_zamiast_sie_uciac(dlugosc, poziom):
    with pytest.raises(ValueError):
        kod_qr.dobierz_wersje(dlugosc, poziom)
    with pytest.raises(ValueError):
        kod_qr.macierz_qr(b"x" * dlugosc, poziom)


def test_link_zaproszenia_ma_wersje_3_z_poziomem_q():
    macierz = utils.macierz_qr(sync.link_zaproszenia("A1B2C3"))
    assert len(macierz) == 29
    assert _odczytaj(macierz)[0] == "Q"


# ------------------------------------------------------------ odczyt z powrotem

_POZIOMY_Z_BITOW = {1: "L", 0: "M", 3: "Q", 2: "H"}


def _odczytaj(macierz):
    """(poziom, maska, dane) — dekoder w minimalnej wersji: tylko tryb bajtowy,
    bez naprawiania błędów (sprawdza, że korekcja się ZGADZA)."""
    bok = len(macierz)
    wersja = (bok - 17) // 4

    # Informacja o formacie: obie kopie identyczne, maska z bitów 10–12.
    kopia1 = [macierz[i][8] for i in range(6)] + [macierz[7][8], macierz[8][8], macierz[8][7]]
    kopia1 += [macierz[8][14 - i] for i in range(9, 15)]
    kopia2 = [macierz[8][bok - 1 - i] for i in range(8)] + [macierz[bok - 15 + i][8] for i in range(8, 15)]
    assert kopia1 == kopia2, "dwie kopie informacji o formacie"
    format_ = sum(1 << i for i, b in enumerate(kopia1) if b) ^ 0x5412
    poziom, maska = _POZIOMY_Z_BITOW[format_ >> 13], (format_ >> 10) & 7
    assert kod_qr._bity_formatu(poziom, maska) == format_ ^ 0x5412, "BCH formatu"

    wzor = kod_qr._Macierz(wersja)
    wzor.rysuj_wzorce()
    if wersja >= 7:
        for i in range(18):
            a, b = bok - 11 + i % 3, i // 3
            assert macierz[b][a] == macierz[a][b] == bool((kod_qr._bity_wersji(wersja) >> i) & 1)

    bity = []
    for prawa in range(bok - 1, 0, -2):
        if prawa <= 6:
            prawa -= 1
        w_gore = (prawa + 1) & 2 == 0
        for krok in range(bok):
            y = bok - 1 - krok if w_gore else krok
            for x in (prawa, prawa - 1):
                if not wzor.funkcyjne[y][x]:
                    bity.append(macierz[y][x] ^ kod_qr._MASKI[maska](x, y))
    kody = [sum(b << (7 - k) for k, b in enumerate(bity[i:i + 8])) for i in range(0, len(bity) - 7, 8)]

    ile_korekcji, grupy = kod_qr._BLOKI[wersja][poziom]
    dlugosci = [d for ile, d in grupy for _ in range(ile)]
    bloki = [[] for _ in dlugosci]
    pozycja = 0
    for i in range(max(dlugosci)):
        for nr, d in enumerate(dlugosci):
            if i < d:
                bloki[nr].append(kody[pozycja])
                pozycja += 1
    korekcje = [[] for _ in dlugosci]
    for _ in range(ile_korekcji):
        for nr in range(len(dlugosci)):
            korekcje[nr].append(kody[pozycja])
            pozycja += 1
    for blok, korekcja in zip(bloki, korekcje):
        assert kod_qr.kody_korekcji(blok, ile_korekcji) == korekcja, "korekcja bloku"

    strumien = "".join(format(b, "08b") for blok in bloki for b in blok)
    assert strumien[:4] == "0100", "tryb bajtowy"
    dl_licznika = 8 if wersja < 10 else 16
    ile = int(strumien[4:4 + dl_licznika], 2)
    start = 4 + dl_licznika
    dane = bytes(int(strumien[start + 8 * i:start + 8 * i + 8], 2) for i in range(ile))
    return poziom, maska, dane


# Długości z każdej wersji 1–10; pary, które się nie mieszczą (213 bajtów przy H),
# odpadają tu, a nie jako pominięte testy.
_PROBKI = [(d, p) for d in (0, 1, 14, 27, 42, 60, 84, 100, 122, 150, 180, 213) for p in "LMQH"
           if kod_qr._miesci_sie(d, kod_qr.NAJWYZSZA_WERSJA, p)]


@pytest.mark.parametrize("dlugosc, poziom", _PROBKI)
def test_macierz_czyta_sie_z_powrotem(dlugosc, poziom):
    dane = bytes((i * 37 + dlugosc) % 256 for i in range(dlugosc))
    oczekiwana_wersja, oczekiwany_poziom = kod_qr.dobierz_wersje(dlugosc, poziom)
    macierz = kod_qr.macierz_qr(dane, poziom)
    assert len(macierz) == 17 + 4 * oczekiwana_wersja
    odczytany_poziom, _, odczytane = _odczytaj(macierz)
    assert (odczytany_poziom, odczytane) == (oczekiwany_poziom, dane)


@pytest.mark.parametrize("maska", range(8))
def test_kazda_maska_czyta_sie_z_powrotem(maska):
    tekst = "Zażółć gęślą jaźń — carsapp://app/dolacz/A1B2C3"
    _, odczytana, dane = _odczytaj(kod_qr.macierz_qr(tekst, "M", maska=maska))
    assert odczytana == maska and dane.decode("utf-8") == tekst


def test_wzorce_stale():
    macierz = kod_qr.macierz_qr("x" * 150)  # wersja 7+: z informacją o wersji
    bok = len(macierz)
    for x0, y0 in ((0, 0), (bok - 7, 0), (0, bok - 7)):
        assert all(macierz[y0][x0 + i] and macierz[y0 + 6][x0 + i] for i in range(7)), "ramka znacznika"
        assert all(macierz[y0 + 2 + j][x0 + 2 + i] for i in range(3) for j in range(3)), "środek znacznika"
        assert not macierz[y0 + 1][x0 + 1], "jasny pierścień znacznika"
    assert [macierz[6][x] for x in range(8, bok - 8)] == [x % 2 == 0 for x in range(8, bok - 8)]
    assert [macierz[y][6] for y in range(8, bok - 8)] == [y % 2 == 0 for y in range(8, bok - 8)]
    assert macierz[bok - 8][8], "ciemny moduł"


# ------------------------------------------------------------ odciski

# Wersje 3 (maska 0), 1 (maska 7) i 9 (maska 2, z informacją o wersji).
@pytest.mark.parametrize("tekst, poziom, odcisk", [
    ("carsapp://app/dolacz/A1B2C3", "M", "2d6c55ad63fcffdf"),
    ("HELLO WORLD", "Q", "c8f8e388ba1abb60"),
    ("Zaproszenie do pojazdu „Octavia” — " + "x" * 120, "M", "25ccc1b991e7ff5d"),
])
def test_odcisk_macierzy_jak_przy_porownaniu_z_nayukim(tekst, poziom, odcisk):
    assert _odcisk(kod_qr.macierz_qr(tekst, poziom)) == odcisk


# ------------------------------------------------------------ obraz

def test_obraz_png_z_marginesem_i_ciemnym_znacznikiem():
    png = utils.obraz_qr_png(sync.link_zaproszenia("A1B2C3"), skala=10, margines=4)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    obraz = Image.open(io.BytesIO(png))
    bok = (29 + 2 * 4) * 10
    assert obraz.size == (bok, bok)
    piksel = obraz.convert("L").getpixel
    assert piksel((5, 5)) == 255 and piksel((bok - 5, bok - 5)) == 255, "biały margines"
    assert piksel((4 * 10 + 5, 4 * 10 + 5)) == 0, "lewy górny róg znacznika pozycji"
    assert piksel((4 * 10 + 15, 4 * 10 + 15)) == 255, "jasny pierścień znacznika"
