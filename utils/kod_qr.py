"""Kod QR bez zewnętrznej biblioteki: koder w czystym Pythonie (Reed–Solomon nad
GF(256), maski — ISO/IEC 18004), obraz z Pillow; bez nowej zależności dla Androida. Tryb
bajtowy (UTF-8), wersje 1–10 (do 213 bajtów przy M); dłuższy tekst → ValueError. Poziom
korekcji z wywołania to MINIMUM — podnoszony, gdy mieści się w tej samej wersji
(zaproszenie: wersja 3, poziom Q). Sprawdzone czytnikami (OpenCV, ZXing) i z segno —
tests/test_kod_qr.py."""

import io


POZIOMY_KOREKCJI = ("L", "M", "Q", "H")

# Bity poziomu w informacji o formacie — kolejność z normy, nie alfabetyczna.
_BITY_POZIOMU = {"L": 1, "M": 0, "Q": 3, "H": 2}

# wersja -> poziom -> (kody korekcji w bloku, ((ile bloków, kody danych w bloku), ...))
_BLOKI = {
    1: {"L": (7, ((1, 19),)), "M": (10, ((1, 16),)), "Q": (13, ((1, 13),)), "H": (17, ((1, 9),))},
    2: {"L": (10, ((1, 34),)), "M": (16, ((1, 28),)), "Q": (22, ((1, 22),)), "H": (28, ((1, 16),))},
    3: {"L": (15, ((1, 55),)), "M": (26, ((1, 44),)), "Q": (18, ((2, 17),)), "H": (22, ((2, 13),))},
    4: {"L": (20, ((1, 80),)), "M": (18, ((2, 32),)), "Q": (26, ((2, 24),)), "H": (16, ((4, 9),))},
    5: {"L": (26, ((1, 108),)), "M": (24, ((2, 43),)),
        "Q": (18, ((2, 15), (2, 16))), "H": (22, ((2, 11), (2, 12)))},
    6: {"L": (18, ((2, 68),)), "M": (16, ((4, 27),)), "Q": (24, ((4, 19),)), "H": (28, ((4, 15),))},
    7: {"L": (20, ((2, 78),)), "M": (18, ((4, 31),)),
        "Q": (18, ((2, 14), (4, 15))), "H": (26, ((4, 13), (1, 14)))},
    8: {"L": (24, ((2, 97),)), "M": (22, ((2, 38), (2, 39))),
        "Q": (22, ((4, 18), (2, 19))), "H": (26, ((4, 14), (2, 15)))},
    9: {"L": (30, ((2, 116),)), "M": (22, ((3, 36), (2, 37))),
        "Q": (20, ((4, 16), (4, 17))), "H": (24, ((4, 12), (4, 13)))},
    10: {"L": (18, ((2, 68), (2, 69))), "M": (26, ((4, 43), (1, 44))),
         "Q": (24, ((6, 19), (2, 20))), "H": (28, ((6, 15), (2, 16)))},
}
NAJWYZSZA_WERSJA = max(_BLOKI)

# Środki wzorców wyrównania (wiersze i kolumny — ta sama lista w obu osiach).
_WYROWNANIE = {
    1: (), 2: (6, 18), 3: (6, 22), 4: (6, 26), 5: (6, 30), 6: (6, 34),
    7: (6, 22, 38), 8: (6, 24, 42), 9: (6, 26, 46), 10: (6, 28, 50),
}

# Ile bitów zostaje po ostatnim kodzie (wypełnione zerami).
_BITY_RESZTY = {1: 0, 2: 7, 3: 7, 4: 7, 5: 7, 6: 7, 7: 0, 8: 0, 9: 0, 10: 0}

# Kary za maskę (ISO/IEC 18004, 7.8.3): ciągi, bloki 2×2, wzór podobny do
# znacznika pozycji, odchylenie od połowy ciemnych modułów.
_KARA_CIAG, _KARA_BLOK, _KARA_ZNACZNIK, _KARA_PROPORCJA = 3, 3, 40, 10

_MASKI = (
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
)


# ------------------------------------------------------------ GF(256)
def _tablice_ciala():
    """Potęgi i logarytmy elementu pierwotnego α=2 przy wielomianie 0x11D."""
    potegi, logarytmy = [0] * 512, [0] * 256
    x = 1
    for i in range(255):
        potegi[i] = x
        logarytmy[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        potegi[i] = potegi[i - 255]
    return potegi, logarytmy


_POTEGI, _LOGARYTMY = _tablice_ciala()


def _iloczyn(a, b):
    if a == 0 or b == 0:
        return 0
    return _POTEGI[_LOGARYTMY[a] + _LOGARYTMY[b]]


def _wielomian_generujacy(stopien):
    """Współczynniki ∏(x − αⁱ), i = 0…stopien−1, od najwyższej potęgi."""
    wynik = [1]
    for i in range(stopien):
        nowy = wynik + [0]
        for j, wsp in enumerate(wynik):
            nowy[j + 1] ^= _iloczyn(wsp, _POTEGI[i])
        wynik = nowy
    return wynik


def kody_korekcji(dane, ile):
    """Reszta z dzielenia dane(x)·xⁿ przez wielomian generujący — `ile` kodów."""
    generator = _wielomian_generujacy(ile)
    reszta = [0] * ile
    for bajt in dane:
        czynnik = bajt ^ reszta[0]
        reszta = reszta[1:] + [0]
        if czynnik:
            for j in range(ile):
                reszta[j] ^= _iloczyn(generator[j + 1], czynnik)
    return reszta


# ------------------------------------------------------------ DANE
def _pojemnosc(wersja, poziom):
    """Liczba kodów (bajtów) danych w danej wersji i na danym poziomie."""
    _, grupy = _BLOKI[wersja][poziom]
    return sum(ile * dlugosc for ile, dlugosc in grupy)


def _bity_dlugosci(wersja):
    return 8 if wersja < 10 else 16


def _miesci_sie(dlugosc, wersja, poziom):
    potrzeba = 4 + _bity_dlugosci(wersja) + 8 * dlugosc
    return potrzeba <= 8 * _pojemnosc(wersja, poziom)


def dobierz_wersje(dlugosc, poziom="M"):
    """(wersja, poziom) dla `dlugosc` bajtów: najmniejsza wersja mieszcząca dane
    na poziomie `poziom`, a w niej najwyższy poziom, który dalej się mieści."""
    if poziom not in POZIOMY_KOREKCJI:
        raise ValueError(f"Nieznany poziom korekcji: {poziom}")
    for wersja in range(1, NAJWYZSZA_WERSJA + 1):
        if _miesci_sie(dlugosc, wersja, poziom):
            wyzsze = POZIOMY_KOREKCJI[POZIOMY_KOREKCJI.index(poziom):]
            return wersja, [p for p in wyzsze if _miesci_sie(dlugosc, wersja, p)][-1]
    raise ValueError("Tekst za długi na kod QR do wersji 10.")


def _kody_danych(dane, wersja, poziom):
    """Tryb bajtowy, długość, dane, terminator i bajty wypełnienia 0xEC/0x11."""
    bity = []

    def dopisz(wartosc, dlugosc):
        bity.extend((wartosc >> i) & 1 for i in range(dlugosc - 1, -1, -1))

    dopisz(0b0100, 4)
    dopisz(len(dane), _bity_dlugosci(wersja))
    for bajt in dane:
        dopisz(bajt, 8)

    pojemnosc = _pojemnosc(wersja, poziom)
    bity.extend([0] * min(4, 8 * pojemnosc - len(bity)))
    bity.extend([0] * (-len(bity) % 8))

    kody = []
    for i in range(0, len(bity), 8):
        bajt = 0
        for bit in bity[i:i + 8]:
            bajt = (bajt << 1) | bit
        kody.append(bajt)
    wypelnienie, zajete = (0xEC, 0x11), len(kody)
    while len(kody) < pojemnosc:
        kody.append(wypelnienie[(len(kody) - zajete) % 2])
    return kody


def _ciag_kodow(kody, wersja, poziom):
    """Bloki z korekcją, przeplecione: najpierw dane kolumnami, potem korekcja."""
    ile_korekcji, grupy = _BLOKI[wersja][poziom]
    bloki, pozycja = [], 0
    for ile, dlugosc in grupy:
        for _ in range(ile):
            bloki.append(kody[pozycja:pozycja + dlugosc])
            pozycja += dlugosc
    korekcje = [kody_korekcji(blok, ile_korekcji) for blok in bloki]

    wynik = []
    for i in range(max(len(blok) for blok in bloki)):
        wynik.extend(blok[i] for blok in bloki if i < len(blok))
    for i in range(ile_korekcji):
        wynik.extend(korekcja[i] for korekcja in korekcje)
    return wynik


# ------------------------------------------------------------ MACIERZ
def _bity_formatu(poziom, maska):
    dane = _BITY_POZIOMU[poziom] << 3 | maska
    reszta = dane
    for _ in range(10):
        reszta = (reszta << 1) ^ ((reszta >> 9) * 0x537)
    return (dane << 10 | reszta) ^ 0x5412


def _bity_wersji(wersja):
    reszta = wersja
    for _ in range(12):
        reszta = (reszta << 1) ^ ((reszta >> 11) * 0x1F25)
    return wersja << 12 | reszta


class _Macierz:
    """Moduły [wiersz][kolumna] i znacznik pól funkcyjnych, których nie
    dotykają ani dane, ani maska."""

    def __init__(self, wersja):
        self.wersja = wersja
        self.bok = 17 + 4 * wersja
        self.moduly = [[False] * self.bok for _ in range(self.bok)]
        self.funkcyjne = [[False] * self.bok for _ in range(self.bok)]

    def ustaw(self, x, y, ciemny):
        self.moduly[y][x] = ciemny
        self.funkcyjne[y][x] = True

    def rysuj_wzorce(self):
        n = self.bok
        for i in range(n):
            self.ustaw(6, i, i % 2 == 0)
            self.ustaw(i, 6, i % 2 == 0)
        # Znaczniki pozycji razem z jasną obwódką (odległość 4 od środka).
        for sx, sy in ((3, 3), (n - 4, 3), (3, n - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = sx + dx, sy + dy
                    if 0 <= x < n and 0 <= y < n:
                        self.ustaw(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        srodki = _WYROWNANIE[self.wersja]
        ostatni = len(srodki) - 1
        for i, sx in enumerate(srodki):
            for j, sy in enumerate(srodki):
                if (i, j) in ((0, 0), (0, ostatni), (ostatni, 0)):
                    continue  # tam stoją znaczniki pozycji
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.ustaw(sx + dx, sy + dy, max(abs(dx), abs(dy)) != 1)
        self.rysuj_format("L", 0)  # tylko rezerwacja pól — właściwy format po wyborze maski
        if self.wersja >= 7:
            bity = _bity_wersji(self.wersja)
            for i in range(18):
                ciemny = (bity >> i) & 1 == 1
                a, b = n - 11 + i % 3, i // 3
                self.ustaw(a, b, ciemny)
                self.ustaw(b, a, ciemny)

    def rysuj_format(self, poziom, maska):
        n = self.bok
        bity = _bity_formatu(poziom, maska)

        def bit(i):
            return (bity >> i) & 1 == 1

        for i in range(6):
            self.ustaw(8, i, bit(i))
        self.ustaw(8, 7, bit(6))
        self.ustaw(8, 8, bit(7))
        self.ustaw(7, 8, bit(8))
        for i in range(9, 15):
            self.ustaw(14 - i, 8, bit(i))
        for i in range(8):
            self.ustaw(n - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.ustaw(8, n - 15 + i, bit(i))
        self.ustaw(8, n - 8, True)  # ciemny moduł — zawsze

    def rozmiesc(self, ciag):
        """Zygzak od prawego dolnego rogu, parami kolumn, z pominięciem kolumny 6."""
        n = self.bok
        bity = [(bajt >> (7 - k)) & 1 == 1 for bajt in ciag for k in range(8)]
        bity += [False] * _BITY_RESZTY[self.wersja]
        i = 0
        for prawa in range(n - 1, 0, -2):
            if prawa <= 6:
                prawa -= 1
            w_gore = (prawa + 1) & 2 == 0
            for krok in range(n):
                y = n - 1 - krok if w_gore else krok
                for x in (prawa, prawa - 1):
                    if not self.funkcyjne[y][x] and i < len(bity):
                        self.moduly[y][x] = bity[i]
                        i += 1
        if i != len(bity):
            raise RuntimeError("Rozmieszczenie bitów nie wypełniło macierzy.")

    def naloz_maske(self, maska):
        warunek = _MASKI[maska]
        for y in range(self.bok):
            for x in range(self.bok):
                if not self.funkcyjne[y][x] and warunek(x, y):
                    self.moduly[y][x] = not self.moduly[y][x]


# ------------------------------------------------------------ KARY
def _kara_linii(linia, bok):
    """Kara N1 (ciągi ≥ 5) i N3 (wzór 1:1:3:1:1 z czterema jasnymi obok) dla
    jednego wiersza albo kolumny — liczone jak w generatorze Nayukiego, którego
    wynik przy tej samej masce zgadza się z normą."""
    kara = 0
    historia = [0] * 7
    kolor, dlugosc = False, 0

    def do_historii(dl):
        if historia[0] == 0:
            dl += bok  # jasny margines przed pierwszym ciągiem
        historia.insert(0, dl)
        historia.pop()

    def wzorce():
        n = historia[1]
        rdzen = n > 0 and historia[2] == historia[4] == historia[5] == n and historia[3] == 3 * n
        return ((1 if rdzen and historia[0] >= 4 * n and historia[6] >= n else 0)
                + (1 if rdzen and historia[6] >= 4 * n and historia[0] >= n else 0))

    for modul in linia:
        if modul == kolor:
            dlugosc += 1
            if dlugosc == 5:
                kara += _KARA_CIAG
            elif dlugosc > 5:
                kara += 1
        else:
            do_historii(dlugosc)
            if not kolor:
                kara += wzorce() * _KARA_ZNACZNIK
            kolor, dlugosc = modul, 1
    if kolor:
        do_historii(dlugosc)
        dlugosc = 0
    do_historii(dlugosc + bok)  # jasny margines za ostatnim ciągiem
    return kara + wzorce() * _KARA_ZNACZNIK


def kara_maski(moduly):
    """Łączna kara macierzy po nałożeniu maski — wygrywa najmniejsza."""
    bok = len(moduly)
    kara = sum(_kara_linii(wiersz, bok) for wiersz in moduly)
    kara += sum(_kara_linii([moduly[y][x] for y in range(bok)], bok) for x in range(bok))
    for y in range(bok - 1):
        for x in range(bok - 1):
            if moduly[y][x] == moduly[y][x + 1] == moduly[y + 1][x] == moduly[y + 1][x + 1]:
                kara += _KARA_BLOK
    ciemne = sum(sum(1 for m in wiersz if m) for wiersz in moduly)
    wszystkie = bok * bok
    k = (abs(ciemne * 20 - wszystkie * 10) + wszystkie - 1) // wszystkie - 1
    return kara + k * _KARA_PROPORCJA


# ------------------------------------------------------------ WEJŚCIE
def macierz_qr(tekst, poziom="M", maska=None):
    """Macierz kodu QR: lista wierszy, True = ciemny moduł, bez marginesu.

    `tekst` — str (kodowany w UTF-8) albo bajty. `poziom` — minimalny poziom
    korekcji (patrz opis modułu). `maska` — 0…7 na sztywno; domyślnie ta
    z najmniejszą karą."""
    dane = tekst.encode("utf-8") if isinstance(tekst, str) else bytes(tekst)
    wersja, poziom = dobierz_wersje(len(dane), poziom)
    ciag = _ciag_kodow(_kody_danych(dane, wersja, poziom), wersja, poziom)

    baza = _Macierz(wersja)
    baza.rysuj_wzorce()
    baza.rozmiesc(ciag)

    najlepsza = None
    for numer in (range(8) if maska is None else (maska,)):
        kandydat = _Macierz(wersja)
        kandydat.moduly = [wiersz[:] for wiersz in baza.moduly]
        kandydat.funkcyjne = baza.funkcyjne
        kandydat.naloz_maske(numer)
        kandydat.rysuj_format(poziom, numer)
        kara = kara_maski(kandydat.moduly)
        if najlepsza is None or kara < najlepsza[0]:
            najlepsza = (kara, kandydat.moduly)
    return najlepsza[1]


def obraz_qr_png(tekst, poziom="M", skala=10, margines=4):
    """PNG z kodem QR: czarne moduły na białym tle, z marginesem `margines`
    modułów (norma wymaga co najmniej 4) i `skala` pikseli na moduł.

    Zawsze ciemne na jasnym, także w ciemnym motywie — kodu w negatywie część
    czytników nie widzi."""
    from PIL import Image  # dopiero tu: start aplikacji nie ładuje Pillow

    moduly = macierz_qr(tekst, poziom)
    bok = len(moduly) + 2 * margines
    piksele = [255] * (bok * bok)
    for y, wiersz in enumerate(moduly):
        poczatek = (y + margines) * bok + margines
        for x, ciemny in enumerate(wiersz):
            if ciemny:
                piksele[poczatek + x] = 0

    obraz = Image.new("L", (bok, bok), 255)
    obraz.putdata(piksele)
    obraz = obraz.resize((bok * skala, bok * skala), Image.Resampling.NEAREST)
    bufor = io.BytesIO()
    obraz.save(bufor, format="PNG", optimize=True)
    return bufor.getvalue()


__all__ = [
    "NAJWYZSZA_WERSJA",
    "POZIOMY_KOREKCJI",
    "dobierz_wersje",
    "kara_maski",
    "kody_korekcji",
    "macierz_qr",
    "obraz_qr_png",
]
