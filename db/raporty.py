"""Generowanie PDF i grafiki „Rok w pigułce”."""

import io
import os
import sqlite3
from date import parsuj_date
import calendar
from datetime import date, datetime
from typing import Any
try:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos
    # Zamiast `ln=1`, które fpdf2 wycofuje (ostrzeżenie od 2.5.2): kursor na lewy
    # margines następnej linii.
    NOWA_LINIA = {"new_x": XPos.LMARGIN, "new_y": YPos.NEXT}
except ImportError:
    FPDF = None
    NOWA_LINIA = {}
try:
    from PIL import Image, ImageOps
except ImportError:
    Image = None
    ImageOps = None

import log

from .polaczenie import polacz_baze
from .zalaczniki import sciezka_pliku_zalacznika
from .pomocnicze import SEPARATOR_TYSIECY, formatuj_liczba_eksport, liczba_na_tekst, liczba_z_odmiana
from .ustawienia import pobierz_walute
from .jednostki import dystans_z_km, jednostka_dystansu, na_jednostke_dystansu, slowo_dystansu
from .energia import formatuj_zuzycie_tekst
from .analiza import _wpisy_okresu, opis_porownania_miesiaca, podsumowanie_miesiaca
from .przebieg import pobierz_aktualny_przebieg, pobierz_historie_przebiegu
from .gwarancje import STATUS_GWARANCJI_BLISKO, gwarancje_pojazdu, opis_gwarancji, zakres_gwarancji
from .opony import STATUS_BIEZNIKA_KRYTYCZNY, STATUS_BIEZNIKA_UWAGA, dane_opon, tekst_bieznika, tekst_wieku
from .nazwy import klucz_nazwy
from .rejestry import WARSZTAT_BEZ_NAZWY
from .pojazd import pobierz_dane_pojazdu
from .os_przyszlosci import os_przyszlosci
from .eksport import FOLDER_ASSETS, KATEGORIE_EKSPORTU, _MAPA_TRANSLITERACJI_PL, _RaportPDF, generuj_csv
from .stale import NAZWA_APLIKACJI


# ==================== GRAFIKA „ROK / MIESIĄC W PIGUŁCE” ====================
# Podsumowanie jako obrazek do wysłania, rysowane Pillow. Rysownik jest JEDEN
# (`_narysuj_pigulke`); rok i miesiąc podają tylko liczby.

# Auto z logo w stopce (assets/ w korzeniu, obok czcionek), na białej plakietce —
# czarny dach na granatowym tle by zniknął.
PLIK_LOGO_GRAFIKI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "assets", "logo.png")
SZEROKOSC_LOGO_STOPKI = 96

MIESIACE_SKROT = ["sty", "lut", "mar", "kwi", "maj", "cze",
                  "lip", "sie", "wrz", "paź", "lis", "gru"]

# Tytuł grafiki miesiąca.
MIESIACE_PELNE = ["Styczeń", "Luty", "Marzec", "Kwiecień", "Maj", "Czerwiec",
                  "Lipiec", "Sierpień", "Wrzesień", "Październik", "Listopad", "Grudzień"]


# Kandydaci na czcionkę, w kolejności od najlepszego. Assets projektu wygrywają,
# potem typowe czcionki systemowe (Windows / Android / Linux), a gdy nie ma nic —
# wbudowana czcionka Pillow, przy której transliterujemy polskie znaki (dokładnie
# ta sama zasada, co w eksporcie PDF).
_CZCIONKI_KANDYDACI = [
    ("C:/Windows/Fonts", "segoeui.ttf", "segoeuib.ttf"),
    ("C:/Windows/Fonts", "arial.ttf", "arialbd.ttf"),
    ("/system/fonts", "Roboto-Regular.ttf", "Roboto-Bold.ttf"),
    ("/system/fonts", "NotoSans-Regular.ttf", "NotoSans-Bold.ttf"),
    ("/usr/share/fonts/truetype/dejavu", "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
]


def _znajdz_czcionki_grafiki():
    """(ścieżka_regular, ścieżka_bold) albo (None, None), gdy nic nie znaleziono."""
    kandydaci = [(FOLDER_ASSETS, "DejaVuSans.ttf", "DejaVuSans-Bold.ttf")] + _CZCIONKI_KANDYDACI
    for folder, reg, bold in kandydaci:
        sciezka_reg = os.path.join(folder, reg)
        if os.path.exists(sciezka_reg):
            sciezka_bold = os.path.join(folder, bold)
            return sciezka_reg, (sciezka_bold if os.path.exists(sciezka_bold) else sciezka_reg)
    return None, None


def _narysuj_pigulke(naglowek, nazwa, tytul, plakietki, kafle, wykres, fakty, akcent) -> bytes:
    """Rysownik „w pigułce” dla roku i miesiąca, PNG 1080×1440. Parametry:
    - `tytul` — wielki napis (kurczy się, gdy z plakietkami nie mieści się w kadrze);
    - `plakietki` — krótkie napisy obok tytułu;
    - `kafle` — (etykieta, wartość, podpis albo None), po dwa w rzędzie;
    - `wykres` — None albo {tytul, wartosci, etykiety, szczyt}: etykieta None = słupek
      bez podpisu, `szczyt` — indeks słupka w akcencie;
    - `fakty` — (etykieta, wartość), ile się zmieści nad stopką.
    RuntimeError bez Pillow."""
    if Image is None:
        raise RuntimeError("Biblioteka Pillow nie jest zainstalowana — grafika jest niedostępna.")
    from PIL import ImageDraw, ImageFont

    # 1080×1440 (3:4) — mieści komplet faktów bez ściskania, a przy tym jest
    # standardowym pionowym kadrem, który nie zostanie przycięty na czacie.
    SZER, WYS = 1080, 1440
    TLO_GORA, TLO_DOL = (15, 23, 42), (30, 41, 59)
    BIALY, PRZYGASZONY = (248, 250, 252), (148, 163, 184)
    TLO_PIGULKI = (51, 65, 85)

    reg_path, bold_path = _znajdz_czcionki_grafiki()

    def czcionka(rozmiar, pogrubiona=False):
        sciezka = bold_path if pogrubiona else reg_path
        if sciezka:
            try:
                return ImageFont.truetype(sciezka, rozmiar)
            except Exception:
                pass
        try:
            return ImageFont.load_default(size=rozmiar)
        except TypeError:
            # Bardzo stare Pillow: load_default() bez rozmiaru, bitmapowa.
            return ImageFont.load_default()

    # Bez własnej czcionki nie mamy pewności co do polskich znaków — wtedy
    # transliterujemy, zamiast rysować puste prostokąty.
    transliteruj = reg_path is None

    def t(tekst):
        tekst = "" if tekst is None else str(tekst)
        tekst = tekst.replace("•", "-").replace("…", "...").replace("≈", "~")
        return tekst.translate(_MAPA_TRANSLITERACJI_PL) if transliteruj else tekst

    obraz = Image.new("RGB", (SZER, WYS), TLO_GORA)
    rysuj = ImageDraw.Draw(obraz)

    # Pionowy gradient tła — jedna linia na wiersz pikseli.
    for y in range(WYS):
        udzial = y / WYS
        rysuj.line(
            [(0, y), (SZER, y)],
            fill=tuple(int(TLO_GORA[i] + (TLO_DOL[i] - TLO_GORA[i]) * udzial) for i in range(3)),
        )
    # Delikatna poświata w rogu, żeby tło nie było płaskie.
    rysuj.ellipse([SZER - 420, -260, SZER + 200, 360],
                  fill=tuple(min(255, int(TLO_GORA[i] + (akcent[i] - TLO_GORA[i]) * 0.16)) for i in range(3)))

    MARGINES = 72
    SZER_UZYTECZNA = SZER - 2 * MARGINES

    def zmiesc(tresc, maks_szer, rozmiar, pogrubiony=False, min_rozmiar=16):
        """Dobiera rozmiar czcionki tak, żeby tekst zmieścił się w zadanej
        szerokości; gdy nawet minimalny nie wystarcza, ucina z wielokropkiem.
        Bez tego długa nazwa auta albo „przejazd z Warszawy do Lizbony — 2,1 raza”
        wychodziły poza kadr — a obrazek ma iść na czat, nie do poprawek."""
        tresc = t(tresc)
        while rozmiar > min_rozmiar:
            if rysuj.textlength(tresc, font=czcionka(rozmiar, pogrubiony)) <= maks_szer:
                return tresc, rozmiar
            rozmiar -= 2
        f = czcionka(rozmiar, pogrubiony)
        while tresc and rysuj.textlength(tresc + "...", font=f) > maks_szer:
            tresc = tresc[:-1]
        return (tresc + "...") if tresc else "", rozmiar

    def tekst(xy, tresc, rozmiar, kolor=BIALY, pogrubiony=False, prawy=False, maks_szer=None):
        tresc = t(tresc)
        if maks_szer:
            tresc, rozmiar = zmiesc(tresc, maks_szer, rozmiar, pogrubiony)
        f = czcionka(rozmiar, pogrubiony)
        x, y_t = xy
        if prawy:
            x -= rysuj.textlength(tresc, font=f)
        rysuj.text((x, y_t), tresc, font=f, fill=kolor)
        return y_t + rozmiar

    y = 78
    tekst((MARGINES, y), naglowek, 30, akcent, True, maks_szer=SZER_UZYTECZNA)
    y += 46
    tekst((MARGINES, y), nazwa, 46, BIALY, True, maks_szer=SZER_UZYTECZNA)
    y += 70

    # Tytuł i plakietki jako OSOBNE elementy: sklejone w jeden napis nie
    # mieściły się w kadrze, a sam tytuł ma być tym, co widać z miniatury.
    # Pigułka ma szerokość swojego napisu — „2026” i „rok w toku” to nie ten
    # sam rozmiar.
    ROZMIAR_TYTULU = 132
    f_plakietki = czcionka(26, True)
    plakietki = [t(p) for p in plakietki or []]
    szer_plakietek = [rysuj.textlength(p, font=f_plakietki) + 44 for p in plakietki]
    zajete = (sum(szer_plakietek) + 24 + 12 * (len(plakietki) - 1)) if plakietki else 0
    tytul, rozmiar = zmiesc(tytul, SZER_UZYTECZNA - zajete, ROZMIAR_TYTULU, True, min_rozmiar=48)

    # Skurczony tytuł („Październik” obok dwóch plakietek) stoi na tej samej
    # linii bazowej, co pełnowymiarowy, a plakietki trzymają się środka jego
    # wersalików — inaczej wisiałyby nad napisem.
    def wersaliki(f):
        _x0, gora, _x1, dol = rysuj.textbbox((0, 0), "H", font=f)
        return gora, dol

    f_tytulu = czcionka(rozmiar, True)
    gora_pelna, dol_pelny = wersaliki(czcionka(ROZMIAR_TYTULU, True))
    gora, dol = wersaliki(f_tytulu)
    y_tytulu = y + (dol_pelny - dol)
    tekst((MARGINES, y_tytulu), tytul, rozmiar, BIALY, True)
    x_pill = MARGINES + rysuj.textlength(tytul, font=f_tytulu) + 24
    y_pill = y + 46 + round((y_tytulu - y) + (gora + dol) / 2 - (gora_pelna + dol_pelny) / 2)
    for napis, szer_p in zip(plakietki, szer_plakietek):
        rysuj.rounded_rectangle([x_pill, y_pill, x_pill + szer_p, y_pill + 54], radius=27, fill=TLO_PIGULKI)
        tekst((x_pill + 22, y_pill + 12), napis, 26, PRZYGASZONY, True)
        x_pill += szer_p + 12
    y += 176

    def kafelek(x, y_kafla, szer, etykieta, wartosc, podpis=None):
        WYS_KAFLA = 172
        rysuj.rounded_rectangle([x, y_kafla, x + szer, y_kafla + WYS_KAFLA], radius=26,
                                fill=(24, 34, 54), outline=TLO_PIGULKI, width=2)
        wnetrze = szer - 56
        tekst((x + 28, y_kafla + 26), etykieta, 24, PRZYGASZONY, maks_szer=wnetrze)
        tekst((x + 28, y_kafla + 62), wartosc, 52, BIALY, True, maks_szer=wnetrze)
        if podpis:
            tekst((x + 28, y_kafla + 126), podpis, 22, PRZYGASZONY, maks_szer=wnetrze)
        return y_kafla + WYS_KAFLA

    szer_kafla = (SZER_UZYTECZNA - 24) // 2
    for i in range(0, len(kafle), 2):
        for kolumna, (etykieta, wartosc, podpis) in enumerate(kafle[i:i + 2]):
            kafelek(MARGINES + kolumna * (szer_kafla + 24), y, szer_kafla, etykieta, wartosc, podpis)
        y += 196
    y += 18

    # --- rytm okresu: słupek na miesiąc roku albo na dzień miesiąca ---
    wartosci = list((wykres or {}).get("wartosci") or [])
    maks = max(wartosci) if wartosci else 0
    if maks > 0:
        tekst((MARGINES, y), wykres["tytul"], 24, PRZYGASZONY, True)
        y += 44
        WYS_WYKRESU = 150
        szer_kolumny = SZER_UZYTECZNA / len(wartosci)
        etykiety = list(wykres.get("etykiety") or [None] * len(wartosci))
        for i, wartosc in enumerate(wartosci):
            wysokosc = int(WYS_WYKRESU * (wartosc / maks)) if wartosc > 0 else 3
            x0 = MARGINES + i * szer_kolumny + 6
            x1 = MARGINES + (i + 1) * szer_kolumny - 6
            gora = y + WYS_WYKRESU - wysokosc
            czy_szczyt = (i == wykres.get("szczyt"))
            rysuj.rounded_rectangle([x0, gora, x1, y + WYS_WYKRESU], radius=8,
                                    fill=akcent if czy_szczyt else TLO_PIGULKI)
            if i < len(etykiety) and etykiety[i]:
                f_m = czcionka(20, czy_szczyt)
                etykieta_m = t(etykiety[i])
                szer_et = rysuj.textlength(etykieta_m, font=f_m)
                rysuj.text(((x0 + x1) / 2 - szer_et / 2, y + WYS_WYKRESU + 12), etykieta_m,
                           font=f_m, fill=akcent if czy_szczyt else PRZYGASZONY)
        y += WYS_WYKRESU + 56

    # --- wiersze faktów: tyle, ile zmieści się nad stopką ---
    STOPKA_Y = WYS - 74
    # 66 px na wiersz; przy pięciu faktach (miesiąc) wiersze się zagęszczają —
    # do 56 px — zanim którykolwiek odpadnie.
    WYS_WIERSZA = max(56, min(66, (STOPKA_Y - 20 - y) // len(fakty))) if fakty else 66

    for etykieta, wartosc in fakty:
        if y + WYS_WIERSZA > STOPKA_Y - 20:
            break
        # Wartość dostaje do połowy szerokości, etykieta resztę: „Względem
        # września 2025 (do 15.09)” obok „+12%” nie musi się kurczyć.
        wartosc_t, rozmiar_w = zmiesc(wartosc, SZER_UZYTECZNA * 0.5, 28, True)
        miejsce_etykiety = max(SZER_UZYTECZNA * 0.45,
                               SZER_UZYTECZNA - rysuj.textlength(wartosc_t, font=czcionka(rozmiar_w, True)) - 24)
        tekst((MARGINES, y), etykieta, 26, PRZYGASZONY, maks_szer=miejsce_etykiety)
        tekst((SZER - MARGINES, y - 2), wartosc, 28, BIALY, True, prawy=True,
              maks_szer=SZER_UZYTECZNA * 0.5)
        rysuj.line([(MARGINES, y + 44), (SZER - MARGINES, y + 44)], fill=(45, 58, 80), width=2)
        y += WYS_WIERSZA

    x_stopki = MARGINES
    try:
        with Image.open(PLIK_LOGO_GRAFIKI) as plik_logo:
            logo = plik_logo.convert("RGBA")
        logo = logo.resize((SZEROKOSC_LOGO_STOPKI, round(logo.height * SZEROKOSC_LOGO_STOPKI / logo.width)),
                           Image.Resampling.LANCZOS)
        gora = STOPKA_Y + 11 - (logo.height + 12) // 2
        rysuj.rounded_rectangle((MARGINES, gora, MARGINES + logo.width + 16, gora + logo.height + 12),
                                radius=10, fill=(255, 255, 255))
        obraz.paste(logo, (MARGINES + 8, gora + 6), logo)
        x_stopki = MARGINES + logo.width + 16 + 14
    except (OSError, ValueError):
        log.polkniety("logo w stopce grafiki")
    tekst((x_stopki, STOPKA_Y), f"{NAZWA_APLIKACJI} • {datetime.now().strftime('%d.%m.%Y')}", 22, (100, 116, 139))

    bufor = io.BytesIO()
    obraz.save(bufor, format="PNG", optimize=True)
    return bufor.getvalue()


def _kafle_pigulki(dane, waluta, j, srednia, okres):
    """Cztery kafle grafiki — te same w roku i w miesiącu. Różni je tylko podpis
    średniej („~600 zł na miesiąc” / „~40 zł dziennie”) i okres przy liczbie
    tankowań („w roku” / „w miesiącu”)."""
    elektryczny = bool(dane.get("zuzycie_elektryczne"))
    koszt_km = (f"{formatuj_liczba_eksport(na_jednostke_dystansu(dane['koszt_km'], j), 2)} {waluta}"
                if dane.get("koszt_km") else "—")
    zuzycie = formatuj_zuzycie_tekst(dane["srednie_zuzycie"], elektryczny) if dane.get("srednie_zuzycie") else "—"
    if elektryczny:
        ilosc = f"{formatuj_liczba_eksport(dane['kwh'], 0)} kWh naładowane" if dane.get("kwh") else None
        wpisy = liczba_z_odmiana(dane["liczba_tankowan"], "ładowanie", "ładowania", "ładowań")
    else:
        ilosc = f"{formatuj_liczba_eksport(dane['litry'], 0)} l zatankowane" if dane.get("litry") else None
        wpisy = liczba_z_odmiana(dane["liczba_tankowan"], "tankowanie", "tankowania", "tankowań")
    return [
        ("Przejechane", f"{formatuj_liczba_eksport(dystans_z_km(dane['km'], j), 0)} {j}",
         dane.get("porownanie_dystansu")),
        ("Wydane łącznie", f"{formatuj_liczba_eksport(dane['koszty']['razem'], 0)} {waluta}", srednia),
        (f"Koszt {slowo_dystansu('dopelniacz_lp', j)}", koszt_km, f"{wpisy} {okres}"),
        ("Średnie zużycie", zuzycie, ilosc),
    ]


def _procent_zmiany(zmiana):
    """„+12%” / „-5%” — znak zawsze widoczny, bo bez plusa wzrost wygląda jak
    sam udział."""
    return f"{'+' if zmiana > 0 else ''}{formatuj_liczba_eksport(zmiana, 0)}%"


def generuj_grafike_roku(auto_nazwa, dane, akcent=(56, 189, 248)) -> bytes:
    """PNG 1080×1440 z podsumowaniem roku. `dane` to wynik podsumowanie_roku().
    Zwraca bajty pliku albo rzuca RuntimeError, gdy Pillow jest niedostępne."""
    waluta = pobierz_walute()
    j = jednostka_dystansu()

    fakty = []
    najdrozszy = dane["najdrozszy_miesiac"]
    fakty.append(("Najdroższy miesiąc",
                  f"{MIESIACE_SKROT[najdrozszy['miesiac'] - 1]} • "
                  f"{formatuj_liczba_eksport(najdrozszy['kwota'], 0)} {waluta}"))
    if dane.get("ulubiona_stacja"):
        st = dane["ulubiona_stacja"]
        fakty.append(("Ulubiona stacja", f"{st['nazwa']} • {st['liczba']}x"))
    if dane.get("najwiekszy_wydatek"):
        nw = dane["najwiekszy_wydatek"]
        fakty.append(("Największy wydatek",
                      f"{nw['opis']} • {formatuj_liczba_eksport(nw['kwota'], 0)} {waluta}"))
    if dane.get("zmiana_rdr") is not None:
        etykieta_rdr = (f"Względem {dane['rok'] - 1} (do {dane['poprzedni_do'][:5]})"
                        if dane.get("niepelny") and dane.get("poprzedni_do") else f"Względem {dane['rok'] - 1}")
        fakty.append((etykieta_rdr, _procent_zmiany(dane["zmiana_rdr"])))

    return _narysuj_pigulke(
        naglowek="ROK W PIGUŁCE",
        nazwa=auto_nazwa,
        tytul=str(dane["rok"]),
        plakietki=["rok w toku"] if dane.get("niepelny") else [],
        kafle=_kafle_pigulki(
            dane, waluta, j,
            srednia=f"~{formatuj_liczba_eksport(dane['sredni_koszt_miesiaca'], 0)} {waluta} na miesiąc",
            okres="w roku",
        ),
        wykres={
            "tytul": "KOSZTY MIESIĄC PO MIESIĄCU",
            "wartosci": [dane["miesiace"][m] for m in range(1, 13)],
            "etykiety": MIESIACE_SKROT,
            "szczyt": najdrozszy["miesiac"] - 1,
        },
        fakty=fakty,
        akcent=akcent,
    )


def podpisy_dni_miesiaca(liczba_dni, szczyt):
    """Podpisy pod słupkami dni: 1, 5, 10 … 30 i najdroższy dzień. Podpis tuż
    obok szczytu ustępuje mu miejsca — przy trzydziestu jeden słupkach na
    szerokości kadru „10” i „11” zlewają się w jedno."""
    stale = {1} | set(range(5, liczba_dni + 1, 5))
    return [str(d) if d == szczyt or (d in stale and abs(d - szczyt) > 1) else None
            for d in range(1, liczba_dni + 1)]


def generuj_grafike_miesiaca(auto_nazwa, dane, akcent=(56, 189, 248)) -> bytes:
    """PNG 1080×1440 „Miesiąc w pigułce” z wyniku podsumowanie_miesiaca(): słupek na
    dzień, średnia dzienna, porównania z poprzednim miesiącem i rokiem wcześniej.
    RuntimeError bez Pillow."""
    waluta = pobierz_walute()
    j = jednostka_dystansu()
    rok, miesiac = dane["rok"], dane["miesiac"]
    liczba_dni = len(dane["dni"])
    szczyt = dane["najdrozszy_dzien"]["dzien"]

    fakty = []
    # Miesiąc samych zerowych wpisów nie ma najdroższego dnia — „5 sty • 0 zł”
    # byłoby faktem tylko z nazwy.
    if dane["najdrozszy_dzien"]["kwota"] > 0:
        fakty.append(("Najdroższy dzień",
                      f"{szczyt} {MIESIACE_SKROT[miesiac - 1]} • "
                      f"{formatuj_liczba_eksport(dane['najdrozszy_dzien']['kwota'], 0)} {waluta}"))
    if dane.get("najwiekszy_wydatek"):
        nw = dane["najwiekszy_wydatek"]
        fakty.append(("Największy wydatek",
                      f"{nw['opis']} • {formatuj_liczba_eksport(nw['kwota'], 0)} {waluta}"))
    if dane.get("ulubiona_stacja"):
        st = dane["ulubiona_stacja"]
        fakty.append(("Ulubiona stacja", f"{st['nazwa']} • {st['liczba']}x"))
    for klucz in ("poprzedni_miesiac", "rok_temu"):
        porownanie = dane.get(klucz)
        if porownanie and porownanie.get("zmiana") is not None:
            fakty.append((opis_porownania_miesiaca(porownanie, rok, dane.get("niepelny")),
                          _procent_zmiany(porownanie["zmiana"])))

    return _narysuj_pigulke(
        naglowek="MIESIĄC W PIGUŁCE",
        nazwa=auto_nazwa,
        tytul=MIESIACE_PELNE[miesiac - 1],
        plakietki=[str(rok)] + (["w toku"] if dane.get("niepelny") else []),
        kafle=_kafle_pigulki(
            dane, waluta, j,
            srednia=f"~{formatuj_liczba_eksport(dane['sredni_koszt_dnia'], 0)} {waluta} dziennie",
            okres="w miesiącu",
        ),
        wykres={
            "tytul": "KOSZTY DZIEŃ PO DNIU",
            "wartosci": [dane["dni"][d] for d in range(1, liczba_dni + 1)],
            "etykiety": podpisy_dni_miesiaca(liczba_dni, szczyt),
            "szczyt": szczyt - 1,
        },
        fakty=fakty,
        akcent=akcent,
    )


def _narysuj_wykres_liniowy(pdf, punkty, x, y, w, h):
    """Prosty wykres liniowy narysowany prymitywami fpdf2 (bez matplotlib).
    punkty: lista (etykieta_x: str, wartosc: float), posortowana chronologicznie."""
    if len(punkty) < 2:
        pdf.set_font(pdf.czcionka, "", 10)
        pdf.set_text_color(140, 140, 140)
        pdf.set_xy(x, y + h / 2 - 4)
        pdf.cell(w, 8, pdf.t("Za mało danych do wykresu przebiegu."), align="C")
        pdf.set_text_color(0, 0, 0)
        return

    wartosci = [p[1] for p in punkty]
    min_v, max_v = min(wartosci), max(wartosci)
    if max_v == min_v:
        max_v = min_v + 1

    pdf.set_draw_color(210, 210, 210)
    pdf.set_line_width(0.2)
    pdf.rect(x, y, w, h)
    for i in range(1, 4):
        yy = y + h * i / 4
        pdf.line(x, yy, x + w, yy)

    pdf.set_font(pdf.czcionka, "", 7)
    pdf.set_text_color(120, 120, 120)
    for wart, frakcja in ((max_v, 0.0), ((max_v + min_v) / 2, 0.5), (min_v, 1.0)):
        pdf.set_xy(x - 22, y + h * frakcja - 2.5)
        pdf.cell(20, 5, pdf.t(liczba_na_tekst(wart, 0, SEPARATOR_TYSIECY)), align="R")

    n = len(punkty)

    def punkt_na_xy(i, wartosc):
        px = x + (w * i / (n - 1))
        py = y + h - ((wartosc - min_v) / (max_v - min_v)) * h
        return px, py

    pdf.set_draw_color(30, 100, 220)
    pdf.set_line_width(0.6)
    for i in range(n - 1):
        x1, y1 = punkt_na_xy(i, wartosci[i])
        x2, y2 = punkt_na_xy(i + 1, wartosci[i + 1])
        pdf.line(x1, y1, x2, y2)

    pdf.set_fill_color(30, 100, 220)
    for i in range(n):
        px, py = punkt_na_xy(i, wartosci[i])
        pdf.ellipse(px - 0.8, py - 0.8, 1.6, 1.6, style="F")

    pdf.set_font(pdf.czcionka, "", 7)
    for i in sorted(set([0, n // 2, n - 1])):
        px, _ = punkt_na_xy(i, wartosci[i])
        pdf.set_xy(px - 15, y + h + 2)
        pdf.cell(30, 5, pdf.t(str(punkty[i][0])[:5]), align="C")

    pdf.set_text_color(0, 0, 0)


def _przytnij_do_szerokosci(pdf, tekst, szerokosc):
    """Tekst w bieżącej czcionce, który zmieści się w `szerokosc` mm — z „...”
    na końcu, gdy trzeba było uciąć. `cell` nie zawija, a wychodzący za margines
    napis przepada na krawędzi kartki."""
    tekst = pdf.t(tekst)
    if pdf.get_string_width(tekst) <= szerokosc:
        return tekst
    while tekst and pdf.get_string_width(tekst + "...") > szerokosc:
        tekst = tekst[:-1]
    return tekst.rstrip() + "..."


def _rysuj_gwarancje_napraw(pdf, gwarancje):
    """Sekcja „Gwarancje na naprawy”: część i ile zostało (zielono, a w progu
    przypomnienia pomarańczowo — jak w aplikacji), pod spodem limity, dzień
    wymiany i warsztat. Dla kupującego to lista rzeczy, za które nie zapłaci
    drugi raz."""
    pdf.set_font(pdf.czcionka, "B", 13)
    pdf.cell(0, 9, pdf.t("Gwarancje na naprawy"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(200, 200, 200)
    pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 180, pdf.get_y())
    pdf.ln(3)

    szerokosc = pdf.w - pdf.l_margin - pdf.r_margin
    for nazwa, opis, szczegoly, status in gwarancje:
        kolor = (210, 130, 20) if status == STATUS_GWARANCJI_BLISKO else (40, 150, 70)
        pdf.set_font(pdf.czcionka, "B", 10)
        pdf.set_text_color(0, 0, 0)
        nazwa = _przytnij_do_szerokosci(pdf, f"{nazwa} — ", szerokosc * 0.55)
        szer_nazwy = pdf.get_string_width(nazwa) + 1
        pdf.cell(szer_nazwy, 6, nazwa)
        pdf.set_font(pdf.czcionka, "", 10)
        pdf.set_text_color(*kolor)
        pdf.cell(0, 6, _przytnij_do_szerokosci(pdf, opis, szerokosc - szer_nazwy), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(pdf.czcionka, "", 8.5)
        pdf.set_text_color(110, 110, 110)
        pdf.cell(0, 5, _przytnij_do_szerokosci(pdf, szczegoly, szerokosc), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(5)


def _rysuj_opony(pdf, opony):
    """Sekcja „Opony”: komplet, bieżnik ostatniego pomiaru i wiek (kolor jak w aplikacji: czerwony
    poniżej minimum prawnego, pomarańczowy poniżej zalecanego), pod spodem kilometry i felgi."""
    pdf.set_font(pdf.czcionka, "B", 13)
    pdf.cell(0, 9, pdf.t("Opony"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(200, 200, 200)
    pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 180, pdf.get_y())
    pdf.ln(3)

    szerokosc = pdf.w - pdf.l_margin - pdf.r_margin
    kolory = {STATUS_BIEZNIKA_KRYTYCZNY: (200, 40, 40), STATUS_BIEZNIKA_UWAGA: (210, 130, 20)}
    for nazwa, opis, szczegoly, status in opony:
        pdf.set_font(pdf.czcionka, "B", 10)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 6, _przytnij_do_szerokosci(pdf, nazwa, szerokosc), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(pdf.czcionka, "", 10)
        pdf.set_text_color(*kolory.get(status, (40, 150, 70) if status else (110, 110, 110)))
        pdf.cell(0, 6, _przytnij_do_szerokosci(pdf, opis, szerokosc), new_x="LMARGIN", new_y="NEXT")
        if szczegoly:
            pdf.set_font(pdf.czcionka, "", 8.5)
            pdf.set_text_color(110, 110, 110)
            pdf.cell(0, 5, _przytnij_do_szerokosci(pdf, szczegoly, szerokosc), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(5)


def _rysuj_strone_tytulowa_paszportu(pdf, auto_nazwa, zdjecie_glowne, specyfikacja, terminy, gwarancje=None,
                                     opony=None):
    """Strona tytułowa 'Cyfrowego paszportu pojazdu': zdjęcie, nazwa, specyfikacja
    w dwóch kolumnach, ważne terminy kolorowane jak w reszcie aplikacji i trwające
    gwarancje napraw. Używane wyłącznie przez generuj_pdf_raportu(tryb_paszportu=True)."""
    zdjecie_glowne = sciezka_pliku_zalacznika(zdjecie_glowne)
    if zdjecie_glowne and os.path.exists(zdjecie_glowne):
        try:
            szer_strony = pdf.w - pdf.l_margin - pdf.r_margin
            szer_zdj = min(120, szer_strony)
            # Wysokość z PRAWDZIWYCH proporcji zdjęcia. Stałe 0,62 pasowało
            # tylko do kadru poziomego — zdjęcie zrobione pionowo wychodziło
            # wyżej, niż zakładał kursor, i nazwa auta lądowała na nim.
            # Wysokie kadry zwężamy, żeby strona tytułowa się zmieściła.
            proporcja = 0.62
            if Image is not None:
                with Image.open(zdjecie_glowne) as obraz:
                    szer_px, wys_px = obraz.size
                if szer_px > 0:
                    proporcja = wys_px / szer_px
            wys_maks = 90
            if szer_zdj * proporcja > wys_maks:
                szer_zdj = wys_maks / proporcja
            pdf.image(zdjecie_glowne, x=pdf.l_margin + (szer_strony - szer_zdj) / 2, y=pdf.get_y(),
                      w=szer_zdj, h=szer_zdj * proporcja)
            pdf.set_y(pdf.get_y() + szer_zdj * proporcja + 6)
        except Exception:
            log.polkniety("zdjęcie pojazdu na stronie tytułowej paszportu")

    pdf.set_font(pdf.czcionka, "B", 22)
    pdf.cell(0, 14, pdf.t(str(auto_nazwa or "Pojazd")), **NOWA_LINIA, align="C")

    pdf.set_font(pdf.czcionka, "", 10)
    pdf.set_text_color(110, 110, 110)
    pdf.cell(0, 7, pdf.t(f"Cyfrowy paszport pojazdu • wygenerowano {datetime.now().strftime('%d.%m.%Y %H:%M')}"), **NOWA_LINIA, align="C")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(6)

    if specyfikacja:
        pdf.set_font(pdf.czcionka, "B", 13)
        pdf.cell(0, 9, pdf.t("Specyfikacja pojazdu"), **NOWA_LINIA)
        pdf.set_draw_color(200, 200, 200)
        pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 180, pdf.get_y())
        pdf.ln(3)

        szer_kolumny = (pdf.w - pdf.l_margin - pdf.r_margin) / 2
        for i in range(0, len(specyfikacja), 2):
            para = specyfikacja[i:i + 2]
            y_wiersza = pdf.get_y()
            for j, (etyk, wart) in enumerate(para):
                pdf.set_xy(pdf.l_margin + j * szer_kolumny, y_wiersza)
                pdf.set_font(pdf.czcionka, "B", 10)
                pdf.cell(38, 7, pdf.t(f"{etyk}:"))
                pdf.set_font(pdf.czcionka, "", 10)
                pdf.cell(szer_kolumny - 38, 7, pdf.t(str(wart)))
            pdf.set_y(y_wiersza + 7)
        pdf.ln(4)

    if terminy:
        pdf.set_font(pdf.czcionka, "B", 13)
        pdf.cell(0, 9, pdf.t("Ważne terminy"), **NOWA_LINIA)
        pdf.set_draw_color(200, 200, 200)
        pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 180, pdf.get_y())
        pdf.ln(3)

        for etykieta, data_str in terminy:
            if not data_str:
                continue
            d_obj = parsuj_date(data_str)
            if d_obj == datetime.min.date():
                kolor, tekst = (120, 120, 120), str(data_str)
            else:
                roz = (d_obj - datetime.now().date()).days
                if roz < 0:
                    kolor, tekst = (200, 40, 40), f"{data_str}  (po terminie)"
                elif roz <= 30:
                    kolor, tekst = (210, 130, 20), f"{data_str}  (zbliża się)"
                else:
                    kolor, tekst = (40, 150, 70), str(data_str)
            pdf.set_font(pdf.czcionka, "B", 10)
            pdf.set_text_color(0, 0, 0)
            pdf.cell(45, 7, pdf.t(f"{etykieta}:"))
            pdf.set_font(pdf.czcionka, "", 10)
            pdf.set_text_color(*kolor)
            pdf.cell(0, 7, pdf.t(tekst), **NOWA_LINIA)
            pdf.set_text_color(0, 0, 0)
        pdf.ln(6)

    if gwarancje:
        _rysuj_gwarancje_napraw(pdf, gwarancje)
    if opony:
        _rysuj_opony(pdf, opony)

    pdf.add_page()


def _rysuj_galerie_karoserii(pdf, zdjecia_karoserii):
    """Siatka zdjęć karoserii (3 na wiersz) z podpisami data/strefa, doklejana
    na końcu paszportu. zdjecia_karoserii: lista krotek (data, strefa, zalacznik, opis)."""
    pdf.add_page()
    pdf.set_font(pdf.czcionka, "B", 16)
    pdf.cell(0, 12, pdf.t("Zdjęcia karoserii"), **NOWA_LINIA)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 180, pdf.get_y())
    pdf.ln(4)

    szer_zdj, wys_zdj, odstep, na_wiersz = 55, 42, 8, 3
    x_start = pdf.l_margin
    y_wiersza = pdf.get_y()

    for i, (data_z, strefa_z, zalacznik_z, opis_z) in enumerate(zdjecia_karoserii):
        kol = i % na_wiersz
        if kol == 0:
            if pdf.get_y() > pdf.h - (wys_zdj + 24):
                pdf.add_page()
            y_wiersza = pdf.get_y()

        x = x_start + kol * (szer_zdj + odstep)
        zalacznik_z = sciezka_pliku_zalacznika(zalacznik_z)
        if zalacznik_z and os.path.exists(zalacznik_z):
            try:
                pdf.image(zalacznik_z, x=x, y=y_wiersza, w=szer_zdj, h=wys_zdj)
            except Exception:
                pdf.set_xy(x, y_wiersza)
                pdf.set_font(pdf.czcionka, "", 8)
                pdf.cell(szer_zdj, wys_zdj, pdf.t("Błąd wczytania"), border=1, align="C")
        else:
            pdf.set_xy(x, y_wiersza)
            pdf.set_font(pdf.czcionka, "", 8)
            pdf.cell(szer_zdj, wys_zdj, pdf.t("Brak zdjęcia"), border=1, align="C")

        pdf.set_xy(x, y_wiersza + wys_zdj + 1)
        pdf.set_font(pdf.czcionka, "", 8)
        pdf.cell(szer_zdj, 5, pdf.t(f"{data_z} • {strefa_z}"[:32]), align="C")

        if kol == na_wiersz - 1 or i == len(zdjecia_karoserii) - 1:
            pdf.set_y(y_wiersza + wys_zdj + 9)


def generuj_pdf_raportu(auto_nazwa, kategorie_dane, okres_opis, podsumowanie=None,
                         tryb_paszportu=False, zdjecie_glowne=None, specyfikacja=None,
                         terminy=None, punkty_przebiegu=None, zdjecia_karoserii=None,
                         gwarancje=None, opony=None):
    """PDF raportu; zwraca bajty. kategorie_dane: {klucz: (naglowki, wiersze)} jak z
    pobierz_dane_eksportu(); podsumowanie — opcjonalnie z oblicz_podsumowanie_okresu().
    tryb_paszportu=True (generuj_pdf_paszportu) — strona tytułowa (zdjęcie,
    specyfikacja, terminy), wykres przebiegu i galeria karoserii; pozostałe parametry
    tylko w tym trybie. `gwarancje` — (część, „gwarancja jeszcze…”, szczegóły, status), `opony` —
    (komplet, bieżnik i wiek, szczegóły, status bieżnika).
    RuntimeError bez fpdf2."""
    if FPDF is None:
        raise RuntimeError("Biblioteka 'fpdf2' nie jest zainstalowana — eksport do PDF jest niedostępny. Zainstaluj: pip install fpdf2")

    pdf = _RaportPDF(orientation="P" if tryb_paszportu else "L")
    pdf.add_page()

    if tryb_paszportu:
        _rysuj_strone_tytulowa_paszportu(pdf, auto_nazwa, zdjecie_glowne, specyfikacja or [], terminy or [],
                                         gwarancje or [], opony or [])
    else:
        pdf.set_font(pdf.czcionka, "B", 18)
        pdf.cell(0, 12, pdf.t(f"Raport pojazdu: {auto_nazwa}"), **NOWA_LINIA)

        pdf.set_font(pdf.czcionka, "", 11)
        pdf.set_text_color(110, 110, 110)
        pdf.cell(0, 7, pdf.t(f"Okres: {okres_opis}"), **NOWA_LINIA)
        pdf.cell(0, 7, pdf.t(f"Wygenerowano: {datetime.now().strftime('%d.%m.%Y %H:%M')}"), **NOWA_LINIA)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(4)

    if podsumowanie:
        waluta = podsumowanie.get("waluta", "PLN")
        j = jednostka_dystansu()
        pdf.set_font(pdf.czcionka, "B", 13)
        pdf.cell(0, 9, pdf.t("Podsumowanie kosztów"), **NOWA_LINIA)
        pdf.set_draw_color(200, 200, 200)
        pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 180, pdf.get_y())
        pdf.ln(3)

        for etyk, wart in (("Paliwo", podsumowanie["koszt_paliwo"]), ("Serwis", podsumowanie["koszt_serwis"]),
                           ("Inne koszty", podsumowanie["koszt_inne"]), ("RAZEM", podsumowanie["razem"])):
            pdf.set_font(pdf.czcionka, "B" if etyk == "RAZEM" else "", 11)
            pdf.cell(60, 7, pdf.t(etyk))
            pdf.cell(0, 7, pdf.t(f"{formatuj_liczba_eksport(wart)} {waluta}"), **NOWA_LINIA)

        if podsumowanie.get("dystans"):
            pdf.set_font(pdf.czcionka, "", 11)
            pdf.cell(0, 7, pdf.t(f"Przejechany dystans: "
                                 f"{formatuj_liczba_eksport(dystans_z_km(podsumowanie['dystans'], j), 0)} {j}"), **NOWA_LINIA)
        if podsumowanie.get("koszt_km"):
            pdf.cell(0, 7, pdf.t(f"Koszt eksploatacji: "
                                 f"{formatuj_liczba_eksport(na_jednostke_dystansu(podsumowanie['koszt_km'], j), 2)} "
                                 f"{waluta}/{j}"), **NOWA_LINIA)
        if podsumowanie.get("spalanie"):
            # Jednostka z Ustawień (l/100km, km/l, mpg — albo kWh/100km
            # u elektryka), tak samo jak na ekranie, a nie zawsze „l/100km”.
            elektryczny = bool(podsumowanie.get("zuzycie_elektryczne"))
            etykieta = "Średnie zużycie energii" if elektryczny else "Średnie spalanie"
            pdf.cell(0, 7, pdf.t(f"{etykieta}: {formatuj_zuzycie_tekst(podsumowanie['spalanie'], elektryczny)}"), **NOWA_LINIA)
        pdf.ln(6)

    if tryb_paszportu and punkty_przebiegu:
        if pdf.get_y() > pdf.h - 80:
            pdf.add_page()
        pdf.set_font(pdf.czcionka, "B", 13)
        pdf.cell(0, 9, pdf.t("Przebieg w czasie"), **NOWA_LINIA)
        pdf.set_draw_color(200, 200, 200)
        pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 180, pdf.get_y())
        pdf.ln(6)
        # Oś w jednostce z Ustawień — tak jak wykres na ekranie.
        j = jednostka_dystansu()
        punkty_w_jednostce = [(e, dystans_z_km(v, j)) for e, v in punkty_przebiegu]
        _narysuj_wykres_liniowy(pdf, punkty_w_jednostce, pdf.l_margin + 24, pdf.get_y(),
                                pdf.w - pdf.l_margin - pdf.r_margin - 26, 55)
        pdf.set_y(pdf.get_y() + 55 + 14)

    for klucz, (naglowki, wiersze) in kategorie_dane.items():
        # Notatek i linków do produktu nie ma w PDF: tabela dzieli szerokość po równo i
        # ucina tekst. W CSV są.
        for kolumna_notatek in ("Notatka", "Notatki", "Link"):
            if kolumna_notatek in naglowki:
                i_not = naglowki.index(kolumna_notatek)
                naglowki = [h for j, h in enumerate(naglowki) if j != i_not]
                wiersze = [[k for j, k in enumerate(w) if j != i_not] for w in wiersze]

        tytul = KATEGORIE_EKSPORTU.get(klucz, klucz)
        pdf.set_font(pdf.czcionka, "B", 13)
        pdf.cell(0, 9, pdf.t(f"{tytul} ({len(wiersze)})"), **NOWA_LINIA)
        pdf.set_draw_color(200, 200, 200)
        pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 180, pdf.get_y())
        pdf.ln(2)

        if not wiersze:
            pdf.set_font(pdf.czcionka, "", 10)
            pdf.set_text_color(140, 140, 140)
            pdf.cell(0, 7, pdf.t("Brak danych w wybranym zakresie."), **NOWA_LINIA)
            pdf.set_text_color(0, 0, 0)
            pdf.ln(4)
            continue

        szer_strony = pdf.w - pdf.l_margin - pdf.r_margin
        szer_kol = szer_strony / len(naglowki)
        maks_znakow = max(4, int(szer_kol / 1.8))

        def naglowek_tabeli(naglowki=naglowki, szer_kol=szer_kol):
            pdf.set_font(pdf.czcionka, "B", 8.5)
            pdf.set_fill_color(230, 230, 230)
            for h in naglowki:
                pdf.cell(szer_kol, 7, pdf.t(h), border=1, fill=True)
            pdf.ln()
            pdf.set_font(pdf.czcionka, "", 8)

        naglowek_tabeli()
        for w in wiersze:
            if pdf.get_y() > pdf.h - 20:
                pdf.add_page()
                naglowek_tabeli()
            for wartosc in w:
                tekst = pdf.t(wartosc)
                if len(tekst) > maks_znakow:
                    # Zmiana: używamy trzech zwykłych kropek ASCII zamiast znaku Unicode
                    tekst = tekst[:maks_znakow - 3] + "..."
                pdf.cell(szer_kol, 6, tekst, border=1)
            pdf.ln()
        pdf.ln(5)

    if tryb_paszportu and zdjecia_karoserii:
        _rysuj_galerie_karoserii(pdf, zdjecia_karoserii)

    return bytes(pdf.output())


def pobierz_dane_paszportu(auto_id):
    """Dane „paszportu pojazdu” do PDF: zdjęcie, specyfikacja, terminy, historia
    przebiegu, zdjęcia karoserii. Wynik to kwargs do
    generuj_pdf_raportu(tryb_paszportu=True, **wynik) (main.py:
    eksportuj_dane_zaawansowane)."""
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT nazwa, marka, model, generacja, nr_rej, vin, rok_produkcji, "
            "pojemnosc_silnika, moc_silnika, typ_paliwa, skrzynia_biegow, "
            "oc_data, przeglad_data, ac_data, assistance_data, gwarancja_data, gwarancja_przebieg, "
            "zdjecie_glowne "
            "FROM samochody WHERE id=?", (auto_id,)
        )
        auto = c.fetchone()
        if not auto:
            return {}

        c.execute(
            "SELECT data, strefa, zalacznik, opis FROM zdjecia_karoserii "
            "WHERE auto_id=? ORDER BY data_iso, id", (auto_id,)
        )
        zdjecia_karoserii = c.fetchall()

    aktualny_przebieg = pobierz_aktualny_przebieg(auto_id)
    j = jednostka_dystansu()

    specyfikacja = [
        (e, w) for e, w in (
            ("Marka", auto["marka"]), ("Model", auto["model"]), ("Generacja", auto["generacja"]),
            ("Nr rej.", auto["nr_rej"]), ("VIN", auto["vin"]), ("Rocznik", auto["rok_produkcji"]),
            ("Silnik", f"{auto['pojemnosc_silnika']} cm³" if auto["pojemnosc_silnika"] else None),
            ("Moc", f"{auto['moc_silnika']} KM" if auto["moc_silnika"] else None),
            ("Paliwo", auto["typ_paliwa"]), ("Skrzynia", auto["skrzynia_biegow"]),
            ("Gwarancja do", f"{formatuj_liczba_eksport(dystans_z_km(auto['gwarancja_przebieg'], j), 0)} {j}"
             if auto["gwarancja_przebieg"] else None),
            ("Aktualny przebieg", f"{formatuj_liczba_eksport(dystans_z_km(aktualny_przebieg, j), 0)} {j}"
             if aktualny_przebieg else None),
        ) if w
    ]

    terminy = [
        ("Polisa OC", auto["oc_data"]), ("Przegląd techniczny", auto["przeglad_data"]),
        ("Polisa AC", auto["ac_data"]), ("Assistance", auto["assistance_data"]),
        ("Gwarancja producenta", auto["gwarancja_data"]),
    ]

    return {
        "zdjecie_glowne": auto["zdjecie_glowne"],
        "specyfikacja": specyfikacja,
        "terminy": terminy,
        "punkty_przebiegu": pobierz_historie_przebiegu(auto_id),
        "zdjecia_karoserii": zdjecia_karoserii,
        "gwarancje": _gwarancje_do_paszportu(auto_id, j),
        "opony": _opony_do_paszportu(auto_id, j),
    }


def _opony_do_paszportu(auto_id, j):
    """Komplety opon dla kupującego: (komplet, bieżnik z dniem pomiaru i wiek, kilometry i felgi,
    status bieżnika)."""
    wynik = []
    for k in dane_opon(auto_id)["komplety"]:
        nazwa = " · ".join(x for x in (k["sezon"] or "Opony", k["marka_model"], k["rozmiar"]) if x)
        pomiar = k["ostatni_pomiar"]
        opis = [f"bieżnik {tekst_bieznika(k['bieznik'])}" + (f" ({pomiar['data']})" if pomiar["data"] else "")
                if pomiar else "bieżnik niezmierzony"]
        if k["wiek"]:
            opis.append(f"{tekst_wieku(k['wiek'])} od produkcji")
        opis.append(("na aucie" if k["os"] == "Wszystkie" else f"na aucie ({k['os'].lower()})")
                    if k["zamontowany"] else "w magazynie")
        szczegoly = []
        if k["km"]:
            szczegoly.append(f"{formatuj_liczba_eksport(dystans_z_km(k['km'], j), 0)} {j} na komplecie")
        if k["na_felgach"]:
            szczegoly.append("na felgach" + (f" ({k['felgi']})" if k["felgi"] else ""))
        if k["numer_dot"]:
            szczegoly.append(f"DOT {k['numer_dot']}")
        wynik.append((nazwa, " · ".join(opis), " · ".join(szczegoly), k["status_bieznika"]))
    return wynik


def _gwarancje_do_paszportu(auto_id, j):
    """Trwające gwarancje napraw jako (część, „gwarancja jeszcze…”, szczegóły,
    status). Minione pomijamy: kupującego obchodzi to, co jeszcze chroni."""
    wynik = []
    for g in gwarancje_pojazdu(auto_id):
        szczegoly = f"{zakres_gwarancji(g, j)} · wymiana {g['data']}"
        if g["wykonawca"] and klucz_nazwy(g["wykonawca"]) != klucz_nazwy(WARSZTAT_BEZ_NAZWY):
            szczegoly += f" · {g['wykonawca']}"
        wynik.append((g["nazwa"], opis_gwarancji(g, j), szczegoly, g["status"]))
    return wynik


# ==================== EWIDENCJA PRZEBIEGU — RAPORT MIESIĄCA ====================
# Treść składa db.dane_raportu_ewidencji, tu tylko rysunek. Tabela ma WŁASNE szerokości
# kolumn i zawija tekst w komórce (cel i trasa są podpisywane). Linijki przez `cell`,
# bez `ln` (przestarzały w fpdf2).

def _zawin_tekst(pdf, tekst, szerokosc):
    """Linijki tekstu mieszczące się w `szerokosc` (mm) przy bieżącej czcionce.
    Słowo dłuższe niż cała szerokość dzieli się twardo."""
    linie, biezaca = [], ""
    for slowo in pdf.t(tekst).split():
        proba = f"{biezaca} {slowo}" if biezaca else slowo
        if pdf.get_string_width(proba) <= szerokosc:
            biezaca = proba
            continue
        if biezaca:
            linie.append(biezaca)
        while len(slowo) > 1 and pdf.get_string_width(slowo) > szerokosc:
            k = len(slowo) - 1
            while k > 1 and pdf.get_string_width(slowo[:k]) > szerokosc:
                k -= 1
            linie.append(slowo[:k])
            slowo = slowo[k:]
        biezaca = slowo
    if biezaca:
        linie.append(biezaca)
    return linie or [""]


def _wiersz_tabeli(pdf, x0, szerokosci, wartosci, wyrownania, wysokosc_linii, pogrubiony=False, tlo=None):
    """Jeden wiersz tabeli z zawijaniem; zwraca jego wysokość. Wołający dba
    o nową stronę przed wierszem (`_wysokosc_wiersza`)."""
    pdf.set_font(pdf.czcionka, "B" if pogrubiony else "", 8.5)
    margines = 1.2
    kolumny = [_zawin_tekst(pdf, w, s - 2 * margines) for w, s in zip(wartosci, szerokosci)]
    wysokosc = max(len(linie) for linie in kolumny) * wysokosc_linii + 2 * margines
    y0, x = pdf.get_y(), x0
    for linie, szer, wyr in zip(kolumny, szerokosci, wyrownania):
        if tlo:
            pdf.set_fill_color(*tlo)
            pdf.rect(x, y0, szer, wysokosc, style="DF")
        else:
            pdf.rect(x, y0, szer, wysokosc)
        for i, linia in enumerate(linie):
            pdf.set_xy(x + margines, y0 + margines + i * wysokosc_linii)
            pdf.cell(szer - 2 * margines, wysokosc_linii, linia, align=wyr)
        x += szer
    pdf.set_xy(x0, y0 + wysokosc)
    return wysokosc


def _wysokosc_wiersza(pdf, szerokosci, wartosci, wysokosc_linii, pogrubiony=False):
    pdf.set_font(pdf.czcionka, "B" if pogrubiony else "", 8.5)
    return (max(len(_zawin_tekst(pdf, w, s - 2.4)) for w, s in zip(wartosci, szerokosci))
            * wysokosc_linii + 2.4)


def generuj_pdf_ewidencji(dane) -> bytes:
    """PDF raportu miesiąca ewidencji przebiegu (A4 poziomo) z treści
    db.dane_raportu_ewidencji: nagłówek z danymi pojazdu i okresu, tabela
    przejazdów z wierszem „Razem”, podsumowanie, uwagi i miejsca na podpis.
    Rzuca RuntimeError bez fpdf2 — jak pozostałe raporty."""
    if FPDF is None:
        raise RuntimeError("Biblioteka 'fpdf2' nie jest zainstalowana — eksport do PDF jest niedostępny. "
                           "Zainstaluj: pip install fpdf2")
    pdf = _RaportPDF(orientation="L")
    pdf.set_margins(12, 12, 12)
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()
    szer_strony = pdf.w - pdf.l_margin - pdf.r_margin
    dol = pdf.h - 14

    pdf.set_font(pdf.czcionka, "B", 16)
    pdf.cell(0, 9, pdf.t(dane["tytul"]))
    pdf.ln(9)
    pdf.set_font(pdf.czcionka, "", 10.5)
    pdf.set_text_color(110, 110, 110)
    pdf.cell(0, 6, pdf.t(dane["podtytul"]))
    pdf.ln(9)
    pdf.set_text_color(0, 0, 0)

    # Nagłówek: dwie kolumny par „etykieta: wartość”.
    pary = dane["naglowek"]
    polowa = (len(pary) + 1) // 2
    szer_kolumny = szer_strony / 2
    y_start = pdf.get_y()
    y_koniec = y_start
    for kolumna, czesc in enumerate((pary[:polowa], pary[polowa:])):
        pdf.set_xy(pdf.l_margin + kolumna * szer_kolumny, y_start)
        for etykieta, wartosc in czesc:
            x = pdf.l_margin + kolumna * szer_kolumny
            pdf.set_x(x)
            pdf.set_font(pdf.czcionka, "", 9)
            pdf.set_text_color(110, 110, 110)
            pdf.cell(52, 5.5, pdf.t(etykieta))
            pdf.set_text_color(0, 0, 0)
            pdf.set_font(pdf.czcionka, "B", 9)
            linie = _zawin_tekst(pdf, wartosc, szer_kolumny - 56)
            for i, linia in enumerate(linie):
                pdf.set_x(x + 52)
                pdf.cell(szer_kolumny - 56, 5.5, linia)
                pdf.ln(5.5)
        y_koniec = max(y_koniec, pdf.get_y())
    pdf.set_xy(pdf.l_margin, y_koniec + 4)

    # Tabela przejazdów.
    waga = sum(k[1] for k in dane["kolumny"])
    szerokosci = [szer_strony * k[1] / waga for k in dane["kolumny"]]
    wyrownania = [k[2] for k in dane["kolumny"]]
    naglowki = [k[0] for k in dane["kolumny"]]
    linia = 4.2

    def naglowek_tabeli():
        _wiersz_tabeli(pdf, pdf.l_margin, szerokosci, naglowki, ["C"] * len(naglowki), linia,
                       pogrubiony=True, tlo=(230, 230, 230))

    if not dane["wiersze"]:
        pdf.set_font(pdf.czcionka, "", 10)
        pdf.set_text_color(140, 140, 140)
        pdf.cell(0, 7, pdf.t("Brak przejazdów w tym okresie."))
        pdf.ln(9)
        pdf.set_text_color(0, 0, 0)
    else:
        naglowek_tabeli()
        wiersze = list(dane["wiersze"]) + ([dane["razem"]] if dane.get("razem") else [])
        for i, wiersz in enumerate(wiersze):
            ostatni = dane.get("razem") is not None and i == len(wiersze) - 1
            if pdf.get_y() + _wysokosc_wiersza(pdf, szerokosci, wiersz, linia, ostatni) > dol:
                pdf.add_page()
                naglowek_tabeli()
            _wiersz_tabeli(pdf, pdf.l_margin, szerokosci, wiersz, wyrownania, linia, pogrubiony=ostatni,
                           tlo=(245, 245, 245) if ostatni else None)
        pdf.ln(5)

    # Podsumowanie, uwagi, podpisy — każdy blok przenosi się w całości na
    # następną stronę, gdy się nie mieści.
    def miejsce(potrzeba):
        if pdf.get_y() + potrzeba > dol:
            pdf.add_page()

    if dane["podsumowanie"]:
        miejsce(8 + 6 * len(dane["podsumowanie"]))
        pdf.set_font(pdf.czcionka, "B", 11)
        pdf.cell(0, 7, pdf.t("Podsumowanie"))
        pdf.ln(8)
        for etykieta, wartosc in dane["podsumowanie"]:
            pdf.set_font(pdf.czcionka, "", 9.5)
            pdf.cell(80, 5.8, pdf.t(etykieta))
            pdf.set_font(pdf.czcionka, "B", 9.5)
            for j, linia_wartosci in enumerate(_zawin_tekst(pdf, wartosc, szer_strony - 82)):
                if j:
                    pdf.set_x(pdf.l_margin + 80)
                pdf.cell(szer_strony - 80, 5.8, linia_wartosci)
                pdf.ln(5.8)
        pdf.ln(3)

    if dane["uwagi"]:
        pdf.set_font(pdf.czcionka, "", 9)
        linie_uwag = [_zawin_tekst(pdf, u, szer_strony - 6) for u in dane["uwagi"]]
        miejsce(8 + 5 * sum(len(linie) for linie in linie_uwag))
        pdf.set_font(pdf.czcionka, "B", 10)
        pdf.cell(0, 6, pdf.t("Uwagi"))
        pdf.ln(7)
        pdf.set_font(pdf.czcionka, "", 9)
        pdf.set_text_color(160, 80, 0)
        for linie in linie_uwag:
            for j, tekst in enumerate(linie):
                pdf.set_x(pdf.l_margin + (4 if j else 0))
                pdf.cell(szer_strony - 4, 5, (pdf.t("• ") if j == 0 else "") + tekst)
                pdf.ln(5)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(3)

    if dane["podpisy"]:
        miejsce(26)
        pdf.ln(8)
        szer_podpisu = min(110.0, szer_strony / len(dane["podpisy"]) - 10)
        y = pdf.get_y()
        for i, podpis in enumerate(dane["podpisy"]):
            x = pdf.l_margin + i * (szer_strony / len(dane["podpisy"]))
            pdf.set_draw_color(120, 120, 120)
            pdf.line(x, y + 8, x + szer_podpisu, y + 8)
            pdf.set_xy(x, y + 9)
            pdf.set_font(pdf.czcionka, "", 8.5)
            pdf.set_text_color(110, 110, 110)
            pdf.cell(szer_podpisu, 5, pdf.t(podpis), align="C")
        pdf.set_text_color(0, 0, 0)
        pdf.set_xy(pdf.l_margin, y + 18)

    pdf.set_font(pdf.czcionka, "", 7.5)
    pdf.set_text_color(150, 150, 150)
    pdf.set_xy(pdf.l_margin, pdf.h - 10)
    pdf.cell(0, 4, pdf.t(f"Wygenerowano {datetime.now().strftime('%d.%m.%Y %H:%M')} • "
                         f"przejazdów w tabeli: {dane.get('liczba_przejazdow', len(dane['wiersze']))}"))
    return bytes(pdf.output())


def generuj_csv_ewidencji(dane) -> bytes:
    """Ta sama tabela co w PDF — dla arkusza albo księgowej. Wiersz „Razem”
    na końcu, nagłówek i podsumowanie zostają w PDF."""
    wiersze = list(dane["wiersze"]) + ([dane["razem"]] if dane.get("razem") else [])
    return generuj_csv([k[0] for k in dane["kolumny"]], wiersze)


# ==================== RAPORT MIESIĄCA NA JEDNĄ STRONĘ A4 (W-21) ====================
# Treść liczy `dane_raportu_miesiaca` (z tego samego `podsumowanie_miesiaca`, co ekran
# i grafika), `generuj_pdf_miesiaca` tylko ją układa. Jedna strona to zasada: wpisy, które
# się nie zmieszczą, schodzą do jednego wiersza „i jeszcze N”.

# Nazwy kategorii budżetu w raporcie (bez „razem”).
KATEGORIE_RAPORTU_MIESIACA = {"paliwo": "Paliwo i energia", "serwis": "Serwis", "inne": "Inne koszty"}
# Terminów następnego miesiąca najwyżej tyle — reszta zabrałaby miejsce wpisom.
MAKS_TERMINOW_RAPORTU = 8


def _kwota_raportu(kwota, waluta, miejsca=2):
    return f"{liczba_na_tekst(kwota or 0, miejsca, SEPARATOR_TYSIECY)} {waluta}"


def _wpisy_raportu(auto_id, od, do, waluta) -> tuple[list[tuple[str, str, str, str]], float]:
    """(data, rodzaj, opis, kwota) każdego wpisu kosztowego z [od, do] od najstarszego i ich suma."""
    with polacz_baze(zmienia_dane=False) as conn:
        wpisy = _wpisy_okresu(conn, auto_id, od, do)
    wiersze = []
    for w in wpisy["tankowania"]:
        prad = w.get("rodzaj_energii") == "prad"
        jedn = "kWh" if prad else "l"
        opis = ", ".join(filter(None, [
            w.get("stacja"),
            f"{liczba_na_tekst(w['litry'], 2, SEPARATOR_TYSIECY)} {jedn}" if w.get("litry") else None,
            "do pełna" if w.get("do_pelna") else None,
        ]))
        wiersze.append((w["data_iso"], "Ładowanie" if prad else "Tankowanie", opis, float(w["kwota"] or 0)))
    wiersze += [(w["data_iso"], "Serwis", w.get("nazwa") or "", float(w["cena"] or 0)) for w in wpisy["serwis"]]
    wiersze += [(w["data_iso"], "Wizyta", w.get("wykonawca") or WARSZTAT_BEZ_NAZWY,
                 float(w["koszt_calkowity"] or 0)) for w in wpisy["wizyty"]]
    wiersze += [(w["data_iso"], "Inny koszt", w.get("nazwa") or "", float(w["kwota"] or 0)) for w in wpisy["inne"]]
    wiersze.sort(key=lambda w: w[0])
    suma = sum(w[3] for w in wiersze)
    return [(f"{d[8:10]}.{d[5:7]}", rodzaj, opis, _kwota_raportu(kwota, waluta)) for d, rodzaj, opis, kwota in wiersze], suma


def _terminy_raportu(auto_id, rok, miesiac, dzis, waluta) -> tuple[str | None, list[tuple[str, str, str]]]:
    """Terminy miesiąca po raportowanym — tylko te jeszcze przed nami; (tytuł sekcji, wiersze)."""
    nastepny = (rok + 1, 1) if miesiac == 12 else (rok, miesiac + 1)
    poczatek = date(nastepny[0], nastepny[1], 1)
    koniec = date(nastepny[0], nastepny[1], calendar.monthrange(*nastepny)[1])
    od = max(poczatek, dzis)
    if od > koniec:
        return None, []
    os_czasu = os_przyszlosci(auto_id, dni=(koniec - dzis).days + 1, dzis=dzis)
    wiersze = []
    for p in os_czasu["pozycje"]:
        if not p.get("data") or not od <= p["data"] <= koniec or p.get("sugestia") or p.get("rodzaj") == "budzet":
            continue
        kwota = (("ok. " if p.get("szacunek") else "") + _kwota_raportu(p["kwota"], waluta, 0)) if p.get("kwota") else ""
        wiersze.append((p["data"].strftime("%d.%m"), str(p.get("tytul") or ""), kwota))
    tytul = f"Terminy: {MIESIACE_PELNE[nastepny[1] - 1].lower()} {nastepny[0]}"
    if od > poczatek:
        tytul += f" (od {od.strftime('%d.%m')})"
    return tytul, wiersze[:MAKS_TERMINOW_RAPORTU]


def dane_raportu_miesiaca(auto_id, rok, miesiac, dzis=None) -> dict[str, Any] | None:
    """Treść raportu miesiąca na A4 z `podsumowanie_miesiaca`: nagłówek, kafle, porównania
    z poprzednim miesiącem i rokiem wcześniej, kategorie, przebieg i tankowania, wpisy od
    najstarszego, terminy następnego miesiąca. None bez wpisów kosztowych."""
    dzis = dzis or datetime.now().date()
    dane = podsumowanie_miesiaca(auto_id, rok, miesiac)
    if not dane:
        return None
    pojazd = pobierz_dane_pojazdu(auto_id) or {}
    waluta, j = pobierz_walute(), jednostka_dystansu()
    rok, miesiac = dane["rok"], dane["miesiac"]
    razem = dane["koszty"]["razem"]
    elektryczny = bool(dane.get("zuzycie_elektryczne"))

    porownania = []
    for klucz in ("poprzedni_miesiac", "rok_temu"):
        p = dane.get(klucz)
        if p and p.get("kwota"):
            zmiana = f" ({_procent_zmiany(p['zmiana'])})" if p.get("zmiana") is not None else ""
            porownania.append(f"{opis_porownania_miesiaca(p, rok, dane.get('niepelny'))}: "
                              f"{_kwota_raportu(p['kwota'], waluta, 0)}{zmiana}")

    kategorie = [(KATEGORIE_RAPORTU_MIESIACA[k], _kwota_raportu(dane["koszty"][k], waluta),
                  round(dane["koszty"][k] / razem * 100) if razem > 0 else 0)
                 for k in ("paliwo", "serwis", "inne")]

    przebieg = []
    if dane.get("km"):
        przebieg.append(("Przejechane", f"{liczba_na_tekst(dystans_z_km(dane['km'], j), 0, SEPARATOR_TYSIECY)} {j}"))
    if dane.get("srednie_zuzycie"):
        przebieg.append(("Średnie zużycie", formatuj_zuzycie_tekst(dane["srednie_zuzycie"], elektryczny)))
    if dane.get("liczba_tankowan"):
        ilosc = dane.get("kwh") if elektryczny else dane.get("litry")
        przebieg.append(("Ładowania" if elektryczny else "Tankowania",
                         str(dane["liczba_tankowan"]) + (f", {liczba_na_tekst(ilosc, 0, SEPARATOR_TYSIECY)} "
                                                         f"{'kWh' if elektryczny else 'l'}" if ilosc else "")))
    if dane.get("ulubiona_stacja"):
        st = dane["ulubiona_stacja"]
        przebieg.append(("Ulubiona stacja", f"{st['nazwa']} ({st['liczba']}×)"))
    if dane.get("liczba_wizyt") or dane.get("liczba_wpisow_serwisu"):
        przebieg.append(("Serwis", ", ".join(filter(None, [
            liczba_z_odmiana(dane["liczba_wizyt"], "wizyta", "wizyty", "wizyt") if dane.get("liczba_wizyt") else None,
            liczba_z_odmiana(dane["liczba_wpisow_serwisu"], "wpis", "wpisy", "wpisów")
            if dane.get("liczba_wpisow_serwisu") else None]))))
    if dane.get("najwiekszy_wydatek"):
        nw = dane["najwiekszy_wydatek"]
        przebieg.append(("Największy wydatek", f"{nw['opis']}, {_kwota_raportu(nw['kwota'], waluta, 0)}"))

    od = date(rok, miesiac, 1)
    wpisy, suma_wpisow = _wpisy_raportu(auto_id, od, parsuj_date(dane["do"]), waluta)
    tytul_terminow, terminy = _terminy_raportu(auto_id, rok, miesiac, dzis, waluta)
    nazwa_miesiaca = f"{MIESIACE_PELNE[miesiac - 1].lower()} {rok}"
    return {
        "tytul": f"Raport miesiąca: {nazwa_miesiaca}",
        "podtytul": " · ".join(filter(None, [
            pojazd.get("nazwa"), pojazd.get("nr_rej"),
            f"miesiąc w toku, stan na {dane['do']}" if dane.get("niepelny") else None])),
        "kafle": _kafle_pigulki(dane, waluta, j,
                                srednia=f"~{formatuj_liczba_eksport(dane['sredni_koszt_dnia'], 0)} {waluta} dziennie",
                                okres="w miesiącu"),
        "porownania": porownania,
        "kategorie": kategorie,
        "przebieg": przebieg,
        "wpisy": wpisy,
        "suma_wpisow": _kwota_raportu(suma_wpisow, waluta),
        "waluta": waluta,
        "tytul_terminow": tytul_terminow,
        "terminy": terminy,
        "stopka": f"Wygenerowano {dzis.strftime('%d.%m.%Y')} · wydatki razem {_kwota_raportu(razem, waluta)}",
        "nazwa_pliku": f"raport_{rok}-{miesiac:02d}",
    }


_SZARY_RAPORTU = (110, 110, 110)
_TLO_RAPORTU = (242, 244, 247)


def _sekcja_raportu(pdf, x, y, szerokosc, tytul, akcent):
    pdf.set_xy(x, y)
    pdf.set_font(pdf.czcionka, "B", 10.5)
    pdf.set_text_color(*akcent)
    pdf.cell(szerokosc, 6, _przytnij_do_szerokosci(pdf, tytul, szerokosc))
    pdf.set_draw_color(*akcent)
    pdf.line(x, y + 6.6, x + szerokosc, y + 6.6)
    pdf.set_draw_color(0, 0, 0)
    pdf.set_text_color(0, 0, 0)
    return y + 8.5


def generuj_pdf_miesiaca(dane, akcent=(37, 99, 235)) -> bytes:
    """PDF raportu miesiąca na JEDNĄ stronę A4 (W-21) z treści `dane_raportu_miesiaca`. Wpisy,
    które się nie mieszczą, schodzą do wiersza „i jeszcze N”. RuntimeError bez fpdf2."""
    if FPDF is None:
        raise RuntimeError("Biblioteka 'fpdf2' nie jest zainstalowana — eksport do PDF jest niedostępny. "
                           "Zainstaluj: pip install fpdf2")
    pdf = _RaportPDF(orientation="P")
    pdf.set_margins(12, 12, 12)
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()
    x0, szer = pdf.l_margin, pdf.w - pdf.l_margin - pdf.r_margin
    dol = pdf.h - 18

    pdf.set_font(pdf.czcionka, "B", 17)
    pdf.cell(szer, 9, _przytnij_do_szerokosci(pdf, dane["tytul"], szer), **NOWA_LINIA)
    pdf.set_font(pdf.czcionka, "", 10)
    pdf.set_text_color(*_SZARY_RAPORTU)
    pdf.cell(szer, 6, _przytnij_do_szerokosci(pdf, dane["podtytul"], szer), **NOWA_LINIA)
    pdf.set_text_color(0, 0, 0)

    # Kafle: cztery liczby miesiąca, jak na grafice.
    y = pdf.get_y() + 3
    odstep, wys = 3, 21
    szer_kafla = (szer - odstep * (len(dane["kafle"]) - 1)) / max(1, len(dane["kafle"]))
    for i, (etykieta_k, wartosc_k, podpis_k) in enumerate(dane["kafle"]):
        x = x0 + i * (szer_kafla + odstep)
        pdf.set_fill_color(*_TLO_RAPORTU)
        pdf.rect(x, y, szer_kafla, wys, style="F")
        pdf.set_fill_color(*akcent)
        pdf.rect(x, y, 1.2, wys, style="F")
        pdf.set_font(pdf.czcionka, "", 7.5)
        pdf.set_text_color(*_SZARY_RAPORTU)
        pdf.set_xy(x + 3.5, y + 2.5)
        pdf.cell(szer_kafla - 5, 4, _przytnij_do_szerokosci(pdf, etykieta_k, szer_kafla - 5))
        pdf.set_font(pdf.czcionka, "B", 12.5)
        pdf.set_text_color(0, 0, 0)
        pdf.set_xy(x + 3.5, y + 7)
        pdf.cell(szer_kafla - 5, 6.5, _przytnij_do_szerokosci(pdf, wartosc_k, szer_kafla - 5))
        if podpis_k:
            pdf.set_font(pdf.czcionka, "", 7.5)
            pdf.set_text_color(*_SZARY_RAPORTU)
            pdf.set_xy(x + 3.5, y + 14.5)
            pdf.cell(szer_kafla - 5, 4, _przytnij_do_szerokosci(pdf, podpis_k, szer_kafla - 5))
    pdf.set_text_color(0, 0, 0)
    y += wys + 3

    if dane["porownania"]:
        pdf.set_font(pdf.czcionka, "", 9)
        pdf.set_xy(x0, y)
        pdf.cell(szer, 5, _przytnij_do_szerokosci(pdf, "   ·   ".join(dane["porownania"]), szer))
        y += 7

    # Dwie kolumny: kategorie z paskami i przebieg z tankowaniami.
    kol = (szer - 8) / 2
    yl = _sekcja_raportu(pdf, x0, y, kol, "Na co poszły pieniądze", akcent)
    for nazwa, kwota_txt, udzial in dane["kategorie"]:
        pdf.set_xy(x0, yl)
        pdf.set_font(pdf.czcionka, "", 9)
        pdf.cell(kol * 0.5, 5, _przytnij_do_szerokosci(pdf, nazwa, kol * 0.5))
        pdf.set_font(pdf.czcionka, "B", 9)
        pdf.cell(kol * 0.34, 5, pdf.t(kwota_txt), align="R")
        pdf.set_font(pdf.czcionka, "", 8)
        pdf.set_text_color(*_SZARY_RAPORTU)
        pdf.cell(kol * 0.16, 5, f"{udzial}%", align="R")
        pdf.set_text_color(0, 0, 0)
        pdf.set_fill_color(*_TLO_RAPORTU)
        pdf.rect(x0, yl + 5.6, kol, 1.8, style="F")
        if udzial > 0:
            pdf.set_fill_color(*akcent)
            pdf.rect(x0, yl + 5.6, kol * min(udzial, 100) / 100, 1.8, style="F")
        yl += 9.5
    xr = x0 + kol + 8
    yr = _sekcja_raportu(pdf, xr, y, kol, "Przebieg i tankowania", akcent)
    for etykieta_p, wartosc_p in dane["przebieg"] or [("Przebieg", "brak odczytów w tym miesiącu")]:
        pdf.set_font(pdf.czcionka, "", 9)
        pdf.set_text_color(*_SZARY_RAPORTU)
        pdf.set_xy(xr, yr)
        pdf.cell(kol * 0.4, 5, _przytnij_do_szerokosci(pdf, etykieta_p, kol * 0.4))
        pdf.set_text_color(0, 0, 0)
        pdf.set_font(pdf.czcionka, "B", 9)
        for i, linia in enumerate(_zawin_tekst(pdf, wartosc_p, kol * 0.6)[:2]):
            pdf.set_xy(xr + kol * 0.4, yr)
            pdf.cell(kol * 0.6, 5, linia)
            yr += 5 if i == 0 else 4.6
        yr += 0.9
    y = max(yl, yr) + 2

    # Terminy rezerwują miejsce na dole; wpisy biorą resztę strony.
    terminy = dane["terminy"] if dane.get("tytul_terminow") else []
    rezerwa = (8.5 + 5.2 * max(1, len(terminy)) + 3) if dane.get("tytul_terminow") else 0
    koniec_wpisow = dol - rezerwa

    y = _sekcja_raportu(pdf, x0, y, szer, f"Wpisy miesiąca ({len(dane['wpisy'])}) · razem {dane['suma_wpisow']}",
                        akcent)
    pdf.set_xy(x0, y)
    szerokosci = [17, 25, szer - 17 - 25 - 30, 30]
    wyrownania = ["L", "L", "L", "R"]
    linia = 4.2
    if not dane["wpisy"]:
        pdf.set_font(pdf.czcionka, "", 9)
        pdf.cell(szer, 6, pdf.t("Brak wpisów kosztowych w tym miesiącu."))
        pdf.set_y(y + 7)
    else:
        _wiersz_tabeli(pdf, x0, szerokosci, ["Data", "Rodzaj", "Opis", "Kwota"], wyrownania, linia,
                       pogrubiony=True, tlo=(235, 235, 235))
        wpisy = dane["wpisy"]
        for i, wiersz in enumerate(wpisy):
            zostalo = len(wpisy) - i
            wysokosc = _wysokosc_wiersza(pdf, szerokosci, wiersz, linia)
            if pdf.get_y() + wysokosc + (6.6 if zostalo > 1 else 0) > koniec_wpisow:
                reszta = wpisy[i:]
                pdf.set_font(pdf.czcionka, "", 8.5)
                pdf.set_text_color(*_SZARY_RAPORTU)
                pdf.set_x(x0)
                pdf.cell(szer, 6, pdf.t(f"… i jeszcze {liczba_z_odmiana(len(reszta), 'wpis', 'wpisy', 'wpisów')} "
                                        f"— pełna lista w eksporcie CSV albo PDF."), **NOWA_LINIA)
                pdf.set_text_color(0, 0, 0)
                break
            _wiersz_tabeli(pdf, x0, szerokosci, list(wiersz), wyrownania, linia)

    if dane.get("tytul_terminow"):
        y = _sekcja_raportu(pdf, x0, pdf.get_y() + 4, szer, dane["tytul_terminow"], akcent)
        pdf.set_font(pdf.czcionka, "", 9)
        if not terminy:
            pdf.set_xy(x0, y)
            pdf.cell(szer, 5, pdf.t("Do końca miesiąca bez terminów z datą."))
        for data_t, tytul_t, kwota_t in terminy:
            pdf.set_xy(x0, y)
            pdf.set_font(pdf.czcionka, "B", 9)
            pdf.cell(17, 5, data_t)
            pdf.set_font(pdf.czcionka, "", 9)
            pdf.cell(szer - 17 - 32, 5, _przytnij_do_szerokosci(pdf, tytul_t, szer - 17 - 34))
            pdf.cell(32, 5, pdf.t(kwota_t), align="R")
            y += 5.2

    pdf.set_font(pdf.czcionka, "", 7.5)
    pdf.set_text_color(*_SZARY_RAPORTU)
    pdf.set_xy(x0, pdf.h - 12)
    pdf.cell(szer, 4, _przytnij_do_szerokosci(pdf, dane["stopka"], szer))
    return bytes(pdf.output())


__all__ = [
    "MIESIACE_PELNE",
    "MIESIACE_SKROT",
    "PLIK_LOGO_GRAFIKI",
    "SZEROKOSC_LOGO_STOPKI",
    "_CZCIONKI_KANDYDACI",
    "_gwarancje_do_paszportu",
    "_opony_do_paszportu",
    "_kafle_pigulki",
    "_narysuj_pigulke",
    "_narysuj_wykres_liniowy",
    "_procent_zmiany",
    "_przytnij_do_szerokosci",
    "_rysuj_galerie_karoserii",
    "_rysuj_gwarancje_napraw",
    "_rysuj_opony",
    "_rysuj_strone_tytulowa_paszportu",
    "_wiersz_tabeli",
    "_wysokosc_wiersza",
    "_zawin_tekst",
    "_znajdz_czcionki_grafiki",
    "generuj_grafike_miesiaca",
    "generuj_grafike_roku",
    "generuj_csv_ewidencji",
    "generuj_pdf_ewidencji",
    "generuj_pdf_miesiaca",
    "generuj_pdf_raportu",
    "pobierz_dane_paszportu",
    "podpisy_dni_miesiaca",
    "KATEGORIE_RAPORTU_MIESIACA",
    "MAKS_TERMINOW_RAPORTU",
    "dane_raportu_miesiaca",
]
