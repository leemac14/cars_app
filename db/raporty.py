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

from .polaczenie import polacz_baze
from .pomocnicze import formatuj_liczba_eksport
from .ustawienia import pobierz_walute
from .energia import formatuj_zuzycie_tekst
from .przebieg import pobierz_aktualny_przebieg, pobierz_historie_przebiegu
from .eksport import FOLDER_ASSETS, KATEGORIE_EKSPORTU, _MAPA_TRANSLITERACJI_PL, _RaportPDF


# ==================== GRAFIKA „ROK W PIGUŁCE” ====================
# Podsumowanie roku jako obrazek do wysłania — ta sama treść, co na ekranie,
# tylko w formie, którą da się wrzucić na czat. Rysowane Pillow (jest już
# w projekcie dla miniatur zdjęć), bez żadnej nowej zależności.

MIESIACE_SKROT = ["sty", "lut", "mar", "kwi", "maj", "cze",
                  "lip", "sie", "wrz", "paź", "lis", "gru"]


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


def generuj_grafike_roku(auto_nazwa, dane, akcent=(56, 189, 248)):
    """PNG 1080×1440 z podsumowaniem roku. `dane` to wynik podsumowanie_roku().
    Zwraca bajty pliku albo rzuca RuntimeError, gdy Pillow jest niedostępne."""
    if Image is None:
        raise RuntimeError("Biblioteka Pillow nie jest zainstalowana — grafika jest niedostępna.")
    from PIL import ImageDraw, ImageFont

    # 1080×1440 (3:4) — mieści komplet faktów bez ściskania, a przy tym jest
    # standardowym pionowym kadrem, który nie zostanie przycięty na czacie.
    SZER, WYS = 1080, 1440
    TLO_GORA, TLO_DOL = (15, 23, 42), (30, 41, 59)
    BIALY, PRZYGASZONY = (248, 250, 252), (148, 163, 184)

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
    tekst((MARGINES, y), "ROK W PIGUŁCE", 30, akcent, True, maks_szer=SZER_UZYTECZNA)
    y += 46
    tekst((MARGINES, y), auto_nazwa, 46, BIALY, True, maks_szer=SZER_UZYTECZNA)
    y += 70

    # Rok i dopisek o niepełnym roku jako OSOBNE elementy: sklejone w jeden napis
    # nie mieściły się w kadrze, a sam rok ma być tym, co widać z miniatury.
    tekst((MARGINES, y), str(dane["rok"]), 132, BIALY, True)
    if dane.get("niepelny"):
        f_rok = czcionka(132, True)
        x_pill = MARGINES + rysuj.textlength(str(dane["rok"]), font=f_rok) + 24
        rysuj.rounded_rectangle([x_pill, y + 46, x_pill + 234, y + 100], radius=27, fill=(51, 65, 85))
        tekst((x_pill + 22, y + 58), "rok w toku", 26, PRZYGASZONY, True)
    y += 176

    waluta = pobierz_walute()

    def kafelek(x, y_kafla, szer, etykieta, wartosc, podpis=None):
        WYS_KAFLA = 172
        rysuj.rounded_rectangle([x, y_kafla, x + szer, y_kafla + WYS_KAFLA], radius=26,
                                fill=(24, 34, 54), outline=(51, 65, 85), width=2)
        wnetrze = szer - 56
        tekst((x + 28, y_kafla + 26), etykieta, 24, PRZYGASZONY, maks_szer=wnetrze)
        tekst((x + 28, y_kafla + 62), wartosc, 52, BIALY, True, maks_szer=wnetrze)
        if podpis:
            tekst((x + 28, y_kafla + 126), podpis, 22, PRZYGASZONY, maks_szer=wnetrze)
        return y_kafla + WYS_KAFLA

    szer_kafla = (SZER_UZYTECZNA - 24) // 2
    kafelek(MARGINES, y, szer_kafla, "Przejechane", f"{formatuj_liczba_eksport(dane['km'], 0)} km",
            dane.get("porownanie_dystansu"))
    kafelek(MARGINES + szer_kafla + 24, y, szer_kafla, "Wydane łącznie",
            f"{formatuj_liczba_eksport(dane['koszty']['razem'], 0)} {waluta}",
            f"~{formatuj_liczba_eksport(dane['sredni_koszt_miesiaca'], 0)} {waluta} na miesiąc")
    y += 196

    koszt_km = f"{formatuj_liczba_eksport(dane['koszt_km'], 2)} {waluta}" if dane.get("koszt_km") else "—"
    zuzycie = formatuj_zuzycie_tekst(dane["srednie_zuzycie"]) if dane.get("srednie_zuzycie") else "—"
    kafelek(MARGINES, y, szer_kafla, "Koszt kilometra", koszt_km,
            f"{dane['liczba_tankowan']} tankowań w roku")
    kafelek(MARGINES + szer_kafla + 24, y, szer_kafla, "Średnie zużycie", zuzycie,
            f"{formatuj_liczba_eksport(dane['litry'], 0)} l zatankowane" if dane.get("litry") else None)
    y += 214

    # --- rytm roku: koszty miesiąc po miesiącu ---
    maks = max(dane["miesiace"].values()) if dane["miesiace"] else 0
    if maks > 0:
        tekst((MARGINES, y), "KOSZTY MIESIĄC PO MIESIĄCU", 24, PRZYGASZONY, True)
        y += 44
        WYS_WYKRESU = 150
        szer_kolumny = SZER_UZYTECZNA / 12
        for m in range(1, 13):
            wartosc = dane["miesiace"][m]
            wysokosc = int(WYS_WYKRESU * (wartosc / maks)) if wartosc > 0 else 3
            x0 = MARGINES + (m - 1) * szer_kolumny + 6
            x1 = MARGINES + m * szer_kolumny - 6
            gora = y + WYS_WYKRESU - wysokosc
            czy_szczyt = (m == dane["najdrozszy_miesiac"]["miesiac"])
            rysuj.rounded_rectangle([x0, gora, x1, y + WYS_WYKRESU], radius=8,
                                    fill=akcent if czy_szczyt else (51, 65, 85))
            f_m = czcionka(20, czy_szczyt)
            etykieta_m = t(MIESIACE_SKROT[m - 1])
            szer_et = rysuj.textlength(etykieta_m, font=f_m)
            rysuj.text(((x0 + x1) / 2 - szer_et / 2, y + WYS_WYKRESU + 12), etykieta_m,
                       font=f_m, fill=akcent if czy_szczyt else PRZYGASZONY)
        y += WYS_WYKRESU + 56

    # --- wiersze faktów: tyle, ile zmieści się nad stopką ---
    STOPKA_Y = WYS - 74
    WYS_WIERSZA = 66

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
        znak = "+" if dane["zmiana_rdr"] > 0 else ""
        fakty.append((f"Względem {dane['rok'] - 1}",
                      f"{znak}{formatuj_liczba_eksport(dane['zmiana_rdr'], 0)}%"))

    for etykieta, wartosc in fakty:
        if y + WYS_WIERSZA > STOPKA_Y - 20:
            break
        tekst((MARGINES, y), etykieta, 26, PRZYGASZONY, maks_szer=SZER_UZYTECZNA * 0.45)
        tekst((SZER - MARGINES, y - 2), wartosc, 28, BIALY, True, prawy=True,
              maks_szer=SZER_UZYTECZNA * 0.5)
        rysuj.line([(MARGINES, y + 44), (SZER - MARGINES, y + 44)], fill=(45, 58, 80), width=2)
        y += WYS_WIERSZA

    tekst((MARGINES, STOPKA_Y), f"Flota Mobile • {datetime.now().strftime('%d.%m.%Y')}", 22, (100, 116, 139))

    bufor = io.BytesIO()
    obraz.save(bufor, format="PNG", optimize=True)
    return bufor.getvalue()


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
        pdf.cell(20, 5, pdf.t(f"{int(wart):,}".replace(",", " ")), align="R")

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


def _rysuj_strone_tytulowa_paszportu(pdf, auto_nazwa, zdjecie_glowne, specyfikacja, terminy):
    """Strona tytułowa 'Cyfrowego paszportu pojazdu': zdjęcie, nazwa, specyfikacja
    w dwóch kolumnach oraz ważne terminy kolorowane jak w reszcie aplikacji.
    Używane wyłącznie przez generuj_pdf_raportu(tryb_paszportu=True)."""
    if zdjecie_glowne and os.path.exists(zdjecie_glowne):
        try:
            szer_strony = pdf.w - pdf.l_margin - pdf.r_margin
            szer_zdj = min(120, szer_strony)
            pdf.image(zdjecie_glowne, x=pdf.l_margin + (szer_strony - szer_zdj) / 2, y=pdf.get_y(), w=szer_zdj)
            pdf.set_y(pdf.get_y() + szer_zdj * 0.62 + 6)
        except Exception:
            pass

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
                         terminy=None, punkty_przebiegu=None, zdjecia_karoserii=None):
    """
    kategorie_dane: {klucz: (naglowki, wiersze)} — jak z pobierz_dane_eksportu().
    podsumowanie: opcjonalny słownik z oblicz_podsumowanie_okresu() do nagłówka raportu.
    tryb_paszportu: gdy True, zamiast prostego 3-liniowego nagłówka renderuje pełną
    stronę tytułową (zdjęcie, nazwa, specyfikacja, ważne terminy) i — jeśli podano —
    wykres przebiegu w czasie oraz galerię zdjęć karoserii na końcu. Używane przez
    generuj_pdf_paszportu() do zbudowania "Cyfrowego paszportu pojazdu". Pozostałe
    nowe parametry mają znaczenie tylko w tym trybie.
    Zwraca bajty pliku PDF. Rzuca RuntimeError, jeśli fpdf2 nie jest zainstalowane.
    """
    if FPDF is None:
        raise RuntimeError("Biblioteka 'fpdf2' nie jest zainstalowana — eksport do PDF jest niedostępny. Zainstaluj: pip install fpdf2")

    pdf = _RaportPDF(orientation="P" if tryb_paszportu else "L")
    pdf.add_page()

    if tryb_paszportu:
        _rysuj_strone_tytulowa_paszportu(pdf, auto_nazwa, zdjecie_glowne, specyfikacja or [], terminy or [])
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
            pdf.cell(0, 7, pdf.t(f"Przejechany dystans: {formatuj_liczba_eksport(podsumowanie['dystans'], 0)} km"), ln=1)
        if podsumowanie.get("koszt_km"):
            pdf.cell(0, 7, pdf.t(f"Koszt eksploatacji: {formatuj_liczba_eksport(podsumowanie['koszt_km'], 2)} {waluta}/km"), ln=1)
        if podsumowanie.get("spalanie"):
            pdf.cell(0, 7, pdf.t(f"Średnie spalanie: {formatuj_liczba_eksport(podsumowanie['spalanie'], 1)} l/100km"), ln=1)
        pdf.ln(6)

    if tryb_paszportu and punkty_przebiegu:
        if pdf.get_y() > pdf.h - 80:
            pdf.add_page()
        pdf.set_font(pdf.czcionka, "B", 13)
        pdf.cell(0, 9, pdf.t("Przebieg w czasie"), ln=1)
        pdf.set_draw_color(200, 200, 200)
        pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 180, pdf.get_y())
        pdf.ln(6)
        _narysuj_wykres_liniowy(pdf, punkty_przebiegu, pdf.l_margin + 24, pdf.get_y(), pdf.w - pdf.l_margin - pdf.r_margin - 26, 55)
        pdf.set_y(pdf.get_y() + 55 + 14)

    for klucz, (naglowki, wiersze) in kategorie_dane.items():
        # Notatki wpisów pomijamy w PDF: tabela dzieli szerokość strony PO RÓWNO
        # między kolumny i przycina zawartość, więc kolumna wolnego tekstu byłaby
        # nieczytelna („Tankowanie po...”), a przy okazji zwęziłaby wszystkie
        # pozostałe. W CSV, gdzie szerokość nie ogranicza niczego, notatki są.
        if "Notatka" in naglowki:
            i_not = naglowki.index("Notatka")
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
            "WHERE auto_id=? ORDER BY data", (auto_id,)
        )
        zdjecia_karoserii = c.fetchall()

    aktualny_przebieg = pobierz_aktualny_przebieg(auto_id)

    specyfikacja = [
        (e, w) for e, w in (
            ("Marka", auto["marka"]), ("Model", auto["model"]), ("Generacja", auto["generacja"]),
            ("Nr rej.", auto["nr_rej"]), ("VIN", auto["vin"]), ("Rocznik", auto["rok_produkcji"]),
            ("Silnik", f"{auto['pojemnosc_silnika']} cm³" if auto["pojemnosc_silnika"] else None),
            ("Moc", f"{auto['moc_silnika']} KM" if auto["moc_silnika"] else None),
            ("Paliwo", auto["typ_paliwa"]), ("Skrzynia", auto["skrzynia_biegow"]),
            ("Gwarancja do", f"{formatuj_liczba_eksport(auto['gwarancja_przebieg'], 0)} km" if auto["gwarancja_przebieg"] else None),
            ("Aktualny przebieg", f"{formatuj_liczba_eksport(aktualny_przebieg, 0)} km" if aktualny_przebieg else None),
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
    }


__all__ = [
    "MIESIACE_SKROT",
    "_CZCIONKI_KANDYDACI",
    "_narysuj_wykres_liniowy",
    "_rysuj_galerie_karoserii",
    "_rysuj_strone_tytulowa_paszportu",
    "_znajdz_czcionki_grafiki",
    "generuj_grafike_roku",
    "generuj_pdf_raportu",
    "pobierz_dane_paszportu",
]
