"""Generowanie PDF i grafiki „Rok w pigułce”."""

import io
import os
import sqlite3
from date import parsuj_date
from datetime import datetime
try:
    from fpdf import FPDF
except ImportError:
    FPDF = None
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
from .analiza import opis_porownania_miesiaca
from .przebieg import pobierz_aktualny_przebieg, pobierz_historie_przebiegu
from .gwarancje import STATUS_GWARANCJI_BLISKO, gwarancje_pojazdu, opis_gwarancji, zakres_gwarancji
from .nazwy import klucz_nazwy
from .rejestry import WARSZTAT_BEZ_NAZWY
from .eksport import FOLDER_ASSETS, KATEGORIE_EKSPORTU, _MAPA_TRANSLITERACJI_PL, _RaportPDF


# ==================== GRAFIKA „ROK / MIESIĄC W PIGUŁCE” ====================
# Podsumowanie roku albo miesiąca jako obrazek do wysłania — ta sama treść, co
# na ekranie, tylko w formie, którą da się wrzucić na czat. Rysowane Pillow
# (jest już w projekcie dla miniatur zdjęć), bez żadnej nowej zależności.
# Rysownik jest JEDEN (`_narysuj_pigulke`); rok i miesiąc podają mu tylko
# własny zestaw liczb.

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
    """Rysownik „w pigułce” — jeden dla roku i dla miesiąca. PNG 1080×1440:
    gradient, nagłówek z wielkim tytułem i plakietkami, kafle po dwa w rzędzie,
    słupki i wiersze faktów nad stopką. Rok i miesiąc różnią się wyłącznie
    zestawem liczb, który tu przychodzi:

    * `tytul` — wielki napis („2026”, „Wrzesień”); gdy razem z plakietkami nie
      mieści się w kadrze, kurczy się, zamiast uciec za krawędź,
    * `plakietki` — krótkie napisy w pigułkach obok tytułu („rok w toku”),
    * `kafle` — krotki (etykieta, wartość, podpis albo None), po dwa w rzędzie,
    * `wykres` — None albo {"tytul", "wartosci", "etykiety", "szczyt"}: słupek
      na każdą wartość, etykieta None to słupek bez podpisu, `szczyt` to indeks
      słupka w kolorze akcentu,
    * `fakty` — krotki (etykieta, wartość), tyle, ile zmieści się nad stopką.

    Rzuca RuntimeError, gdy Pillow jest niedostępne."""
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

    tekst((MARGINES, STOPKA_Y), f"Flota Mobile • {datetime.now().strftime('%d.%m.%Y')}", 22, (100, 116, 139))

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
    """PNG 1080×1440 „Miesiąc w pigułce” — ten sam rysownik, co rok, inny
    zestaw liczb: słupek na każdy dzień, średnia dzienna zamiast miesięcznej
    i porównania z poprzednim miesiącem oraz z tym samym miesiącem rok
    wcześniej. `dane` to wynik podsumowanie_miesiaca().
    Rzuca RuntimeError, gdy Pillow jest niedostępne."""
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


def _rysuj_strone_tytulowa_paszportu(pdf, auto_nazwa, zdjecie_glowne, specyfikacja, terminy, gwarancje=None):
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
    pdf.cell(0, 14, pdf.t(str(auto_nazwa or "Pojazd")), ln=1, align="C")

    pdf.set_font(pdf.czcionka, "", 10)
    pdf.set_text_color(110, 110, 110)
    pdf.cell(0, 7, pdf.t(f"Cyfrowy paszport pojazdu • wygenerowano {datetime.now().strftime('%d.%m.%Y %H:%M')}"), ln=1, align="C")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(6)

    if specyfikacja:
        pdf.set_font(pdf.czcionka, "B", 13)
        pdf.cell(0, 9, pdf.t("Specyfikacja pojazdu"), ln=1)
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
        pdf.cell(0, 9, pdf.t("Ważne terminy"), ln=1)
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
            pdf.cell(0, 7, pdf.t(tekst), ln=1)
            pdf.set_text_color(0, 0, 0)
        pdf.ln(6)

    if gwarancje:
        _rysuj_gwarancje_napraw(pdf, gwarancje)

    pdf.add_page()


def _rysuj_galerie_karoserii(pdf, zdjecia_karoserii):
    """Siatka zdjęć karoserii (3 na wiersz) z podpisami data/strefa, doklejana
    na końcu paszportu. zdjecia_karoserii: lista krotek (data, strefa, zalacznik, opis)."""
    pdf.add_page()
    pdf.set_font(pdf.czcionka, "B", 16)
    pdf.cell(0, 12, pdf.t("Zdjęcia karoserii"), ln=1)
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
                         gwarancje=None):
    """
    kategorie_dane: {klucz: (naglowki, wiersze)} — jak z pobierz_dane_eksportu().
    podsumowanie: opcjonalny słownik z oblicz_podsumowanie_okresu() do nagłówka raportu.
    tryb_paszportu: gdy True, zamiast prostego 3-liniowego nagłówka renderuje pełną
    stronę tytułową (zdjęcie, nazwa, specyfikacja, ważne terminy) i — jeśli podano —
    wykres przebiegu w czasie oraz galerię zdjęć karoserii na końcu. Używane przez
    generuj_pdf_paszportu() do zbudowania "Cyfrowego paszportu pojazdu". Pozostałe
    nowe parametry mają znaczenie tylko w tym trybie. `gwarancje` — krotki
    (część, „gwarancja jeszcze…”, szczegóły, status) z pobierz_dane_paszportu().
    Zwraca bajty pliku PDF. Rzuca RuntimeError, jeśli fpdf2 nie jest zainstalowane.
    """
    if FPDF is None:
        raise RuntimeError("Biblioteka 'fpdf2' nie jest zainstalowana — eksport do PDF jest niedostępny. Zainstaluj: pip install fpdf2")

    pdf = _RaportPDF(orientation="P" if tryb_paszportu else "L")
    pdf.add_page()

    if tryb_paszportu:
        _rysuj_strone_tytulowa_paszportu(pdf, auto_nazwa, zdjecie_glowne, specyfikacja or [], terminy or [],
                                         gwarancje or [])
    else:
        pdf.set_font(pdf.czcionka, "B", 18)
        pdf.cell(0, 12, pdf.t(f"Raport pojazdu: {auto_nazwa}"), ln=1)

        pdf.set_font(pdf.czcionka, "", 11)
        pdf.set_text_color(110, 110, 110)
        pdf.cell(0, 7, pdf.t(f"Okres: {okres_opis}"), ln=1)
        pdf.cell(0, 7, pdf.t(f"Wygenerowano: {datetime.now().strftime('%d.%m.%Y %H:%M')}"), ln=1)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(4)

    if podsumowanie:
        waluta = podsumowanie.get("waluta", "PLN")
        j = jednostka_dystansu()
        pdf.set_font(pdf.czcionka, "B", 13)
        pdf.cell(0, 9, pdf.t("Podsumowanie kosztów"), ln=1)
        pdf.set_draw_color(200, 200, 200)
        pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 180, pdf.get_y())
        pdf.ln(3)

        for etyk, wart in (("Paliwo", podsumowanie["koszt_paliwo"]), ("Serwis", podsumowanie["koszt_serwis"]),
                           ("Inne koszty", podsumowanie["koszt_inne"]), ("RAZEM", podsumowanie["razem"])):
            pdf.set_font(pdf.czcionka, "B" if etyk == "RAZEM" else "", 11)
            pdf.cell(60, 7, pdf.t(etyk))
            pdf.cell(0, 7, pdf.t(f"{formatuj_liczba_eksport(wart)} {waluta}"), ln=1)

        if podsumowanie.get("dystans"):
            pdf.set_font(pdf.czcionka, "", 11)
            pdf.cell(0, 7, pdf.t(f"Przejechany dystans: "
                                 f"{formatuj_liczba_eksport(dystans_z_km(podsumowanie['dystans'], j), 0)} {j}"), ln=1)
        if podsumowanie.get("koszt_km"):
            pdf.cell(0, 7, pdf.t(f"Koszt eksploatacji: "
                                 f"{formatuj_liczba_eksport(na_jednostke_dystansu(podsumowanie['koszt_km'], j), 2)} "
                                 f"{waluta}/{j}"), ln=1)
        if podsumowanie.get("spalanie"):
            # Jednostka z Ustawień (l/100km, km/l, mpg — albo kWh/100km
            # u elektryka), tak samo jak na ekranie, a nie zawsze „l/100km”.
            elektryczny = bool(podsumowanie.get("zuzycie_elektryczne"))
            etykieta = "Średnie zużycie energii" if elektryczny else "Średnie spalanie"
            pdf.cell(0, 7, pdf.t(f"{etykieta}: {formatuj_zuzycie_tekst(podsumowanie['spalanie'], elektryczny)}"), ln=1)
        pdf.ln(6)

    if tryb_paszportu and punkty_przebiegu:
        if pdf.get_y() > pdf.h - 80:
            pdf.add_page()
        pdf.set_font(pdf.czcionka, "B", 13)
        pdf.cell(0, 9, pdf.t("Przebieg w czasie"), ln=1)
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
        # Notatki wpisów pomijamy w PDF: tabela dzieli szerokość strony PO RÓWNO
        # między kolumny i przycina zawartość, więc kolumna wolnego tekstu byłaby
        # nieczytelna („Tankowanie po...”), a przy okazji zwęziłaby wszystkie
        # pozostałe. W CSV, gdzie szerokość nie ogranicza niczego, notatki są.
        # Wizyty nazywają tę kolumnę „Notatki” — dopóki miały siedem kolumn,
        # przeciskała się niezauważona; przy robociźnie i częściach już nie.
        for kolumna_notatek in ("Notatka", "Notatki"):
            if kolumna_notatek in naglowki:
                i_not = naglowki.index(kolumna_notatek)
                naglowki = [h for j, h in enumerate(naglowki) if j != i_not]
                wiersze = [[k for j, k in enumerate(w) if j != i_not] for w in wiersze]

        tytul = KATEGORIE_EKSPORTU.get(klucz, klucz)
        pdf.set_font(pdf.czcionka, "B", 13)
        pdf.cell(0, 9, pdf.t(f"{tytul} ({len(wiersze)})"), ln=1)
        pdf.set_draw_color(200, 200, 200)
        pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 180, pdf.get_y())
        pdf.ln(2)

        if not wiersze:
            pdf.set_font(pdf.czcionka, "", 10)
            pdf.set_text_color(140, 140, 140)
            pdf.cell(0, 7, pdf.t("Brak danych w wybranym zakresie."), ln=1)
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
    """Zbiera dane do wzbogacenia raportu PDF o 'paszport pojazdu': zdjęcie
    profilowe, specyfikację, ważne terminy, historię przebiegu (do wykresu)
    i zdjęcia karoserii (do galerii na końcu). Używane przez
    eksportuj_dane_zaawansowane() w main.py, gdy w ekranie eksportu zaznaczono
    'Dołącz pełny paszport pojazdu'. Zwraca słownik kwargs gotowy do
    rozpakowania w generuj_pdf_raportu(tryb_paszportu=True, **wynik)."""
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
    }


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


__all__ = [
    "MIESIACE_PELNE",
    "MIESIACE_SKROT",
    "_CZCIONKI_KANDYDACI",
    "_gwarancje_do_paszportu",
    "_kafle_pigulki",
    "_narysuj_pigulke",
    "_narysuj_wykres_liniowy",
    "_procent_zmiany",
    "_przytnij_do_szerokosci",
    "_rysuj_galerie_karoserii",
    "_rysuj_gwarancje_napraw",
    "_rysuj_strone_tytulowa_paszportu",
    "_znajdz_czcionki_grafiki",
    "generuj_grafike_miesiaca",
    "generuj_grafike_roku",
    "generuj_pdf_raportu",
    "pobierz_dane_paszportu",
    "podpisy_dni_miesiaca",
]
