"""Zbieranie danych do eksportu CSV/PDF."""

import csv
import io
import os
import re
import zipfile
from date import parsuj_date
from datetime import datetime
try:
    from fpdf import FPDF
except ImportError:
    FPDF = None

from .polaczenie import polacz_baze
from .pomocnicze import formatuj_liczba_eksport
from .ustawienia import pobierz_prog_dni, pobierz_prog_km, pobierz_walute


# ==================== EKSPORT DANYCH (CSV / PDF) ====================

# Podpisy trafiają zarówno do checkboxów na ekranie eksportu, jak i do nagłówków
# sekcji w PDF — a czcionka raportu (DejaVu) nie ma glifów emoji i rysowała w ich
# miejscu puste prostokąty. Ikony dokłada UI z utils.IKONY_EKSPORTU.
KATEGORIE_EKSPORTU = {
    "tankowania": "Tankowania",
    "historia": "Historia serwisowa",
    "zadania": "Podzespoły i interwały",
    "wizyty": "Wizyty zbiorcze (warsztat)",
    "inne_koszty": "Inne koszty",
    "wydatki_cykliczne": "Wydatki cykliczne i przypomnienia",
    "magazyn_czesci": "Magazyn części i płynów",
    "zestawy_opon": "Zestawy opon",
    "do_zrobienia": "Lista Do zrobienia",
    "warsztaty": "Baza warsztatów",
    "odczyty_przebiegu": "Odczyty licznika",
    "tagi": "Tagi",
}


FOLDER_ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

CZCIONKA_PDF_REGULAR = os.path.join(FOLDER_ASSETS, "DejaVuSans.ttf")

CZCIONKA_PDF_BOLD = os.path.join(FOLDER_ASSETS, "DejaVuSans-Bold.ttf")


# Fallback dla PDF, gdy brak czcionki Unicode w assets/ — usuwa polskie znaki
# diakrytyczne zamiast wywalać wyjątek przy renderowaniu podstawowymi fontami PDF.
_MAPA_TRANSLITERACJI_PL = str.maketrans({
    "ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n", "ó": "o", "ś": "s", "ź": "z", "ż": "z",
    "Ą": "A", "Ć": "C", "Ę": "E", "Ł": "L", "Ń": "N", "Ó": "O", "Ś": "S", "Ź": "Z", "Ż": "Z",
})


def _data_w_zakresie(data_str, od_data, do_data):
    if not od_data and not do_data:
        return True
    d = parsuj_date(data_str)
    if d == datetime.min.date():
        return False
    if od_data and d < od_data:
        return False
    if do_data and d > do_data:
        return False
    return True


def pobierz_dane_eksportu(auto_id, kategorie, od_data=None, do_data=None):
    """
    Zbiera dane pojazdu do eksportu wg wybranych kategorii (klucze z KATEGORIE_EKSPORTU),
    opcjonalnie przycięte do zakresu [od_data, do_data] (obiekty date, oba mogą być None).
    Magazyn, zestawy opon, lista Do zrobienia, definicje podzespołów (zadania),
    wydatki cykliczne, warsztaty i tagi to "stany aktualne" — eksportują się zawsze
    w całości, niezależnie od zakresu dat. Zakresowi podlegają tylko tankowania,
    historia, wizyty, inne koszty i odczyty przebiegu.
    """
    wynik = {}
    if not auto_id or not kategorie:
        return wynik

    with polacz_baze() as conn:
        c = conn.cursor()

        if "tankowania" in kategorie:
            c.execute(
                "SELECT data, przebieg, dystans, litry, kwota, do_pelna, stacja, tagi, notatka "
                "FROM tankowania WHERE auto_id=?", (auto_id,)
            )
            wiersze = []
            for data, prz, dys, lit, kwo, pelna, stacja, tagi, notatka in c.fetchall():
                if _data_w_zakresie(data, od_data, do_data):
                    wiersze.append([
                        data, int(prz or 0), formatuj_liczba_eksport(dys), formatuj_liczba_eksport(lit),
                        formatuj_liczba_eksport(kwo), "Tak" if pelna else "Nie", stacja or "", tagi or "",
                        notatka or ""
                    ])
            wiersze.sort(key=lambda w: parsuj_date(w[0]))
            wynik["tankowania"] = (
                ["Data", "Przebieg (km)", "Dystans (km)", "Litry", "Kwota", "Do pełna", "Stacja", "Tagi", "Notatka"], wiersze
            )

        if "historia" in kategorie:
            c.execute(
                "SELECT h.data, z.nazwa, h.przebieg, h.cena, h.wykonawca, h.kategoria, h.notatka "
                "FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
                "WHERE z.auto_id=? AND h.wizyta_id IS NULL", (auto_id,)
            )
            wiersze = []
            for data, nazwa, prz, cena, wyk, kat, notatka in c.fetchall():
                if _data_w_zakresie(data, od_data, do_data):
                    wiersze.append([data, nazwa, int(prz or 0), formatuj_liczba_eksport(cena), wyk or "", kat or "", notatka or ""])
            wiersze.sort(key=lambda w: parsuj_date(w[0]))
            wynik["historia"] = (["Data", "Podzespół", "Przebieg (km)", "Koszt", "Wykonawca", "Kategoria", "Notatka"], wiersze)

        if "wizyty" in kategorie:
            c.execute(
                "SELECT w.data, w.przebieg, w.wykonawca, w.koszt_calkowity, w.notatki, w.tagi, "
                "GROUP_CONCAT(z.nazwa, ', ') FROM wizyty w "
                "LEFT JOIN historia h ON h.wizyta_id = w.id "
                "LEFT JOIN zadania z ON h.zadanie_id = z.id "
                "WHERE w.auto_id=? GROUP BY w.id", (auto_id,)
            )
            wiersze = []
            for data, prz, wyk, kosz, notatki, tagi, czesci in c.fetchall():
                if _data_w_zakresie(data, od_data, do_data):
                    wiersze.append([
                        data, int(prz or 0), wyk or "", formatuj_liczba_eksport(kosz),
                        czesci or "", tagi or "", notatki or ""
                    ])
            wiersze.sort(key=lambda w: parsuj_date(w[0]))
            wynik["wizyty"] = (
                ["Data", "Przebieg (km)", "Warsztat", "Koszt", "Podzespoły", "Tagi", "Notatki"], wiersze
            )

        if "inne_koszty" in kategorie:
            c.execute("SELECT data, nazwa, kategoria, kwota, tagi, notatka FROM inne_koszty WHERE auto_id=?", (auto_id,))
            wiersze = []
            for data, nazwa, kat, kwota, tagi, notatka in c.fetchall():
                if _data_w_zakresie(data, od_data, do_data):
                    wiersze.append([data, nazwa or "", kat or "", formatuj_liczba_eksport(kwota), tagi or "", notatka or ""])
            wiersze.sort(key=lambda w: parsuj_date(w[0]))
            wynik["inne_koszty"] = (["Data", "Opis", "Kategoria", "Kwota", "Tagi", "Notatka"], wiersze)

        if "magazyn_czesci" in kategorie:
            c.execute(
                "SELECT nazwa, kategoria, ilosc, jednostka, cena, data_zakupu "
                "FROM magazyn_czesci WHERE auto_id=? ORDER BY nazwa", (auto_id,)
            )
            wiersze = [
                [nazwa, kat or "", formatuj_liczba_eksport(ilosc, 2), jedn or "szt", formatuj_liczba_eksport(cena), dz or ""]
                for nazwa, kat, ilosc, jedn, cena, dz in c.fetchall()
            ]
            wynik["magazyn_czesci"] = (["Nazwa", "Kategoria", "Ilość", "Jednostka", "Cena", "Data zakupu"], wiersze)

        if "zestawy_opon" in kategorie:
            c.execute(
                "SELECT sezon, rozmiar, marka_model, glebokosc_bieznika, ilosc, zamontowane, os_montazu, cena "
                "FROM zestawy_opon WHERE auto_id=? ORDER BY sezon", (auto_id,)
            )
            wiersze = []
            for sezon, rozmiar, marka, gl, il, zam, os_m, cena in c.fetchall():
                stan = f"Na aucie ({os_m})" if zam else "W magazynie"
                wiersze.append([sezon or "", rozmiar or "", marka or "", formatuj_liczba_eksport(gl, 1), il or 4, stan, formatuj_liczba_eksport(cena)])
            wynik["zestawy_opon"] = (["Sezon", "Rozmiar", "Marka/model", "Bieżnik (mm)", "Ilość", "Stan", "Cena"], wiersze)

        if "do_zrobienia" in kategorie:
            c.execute(
                "SELECT tytul, priorytet, szacowany_koszt, termin, wykonane FROM do_zrobienia "
                "WHERE auto_id=? ORDER BY priorytet", (auto_id,)
            )
            wiersze = [
                [tyt, pr or "", formatuj_liczba_eksport(koszt), term or "", "Tak" if wyk else "Nie"]
                for tyt, pr, koszt, term, wyk in c.fetchall()
            ]
            wynik["do_zrobienia"] = (["Tytuł", "Priorytet", "Szac. koszt", "Termin", "Wykonane"], wiersze)

        if "zadania" in kategorie:
            c.execute(
                "SELECT nazwa, interwal_km, interwal_miesiace, data, przebieg, prog_km, prog_dni, dotyczy_opon "
                "FROM zadania WHERE auto_id=? ORDER BY nazwa", (auto_id,)
            )
            dom_km, dom_dni = pobierz_prog_km(), pobierz_prog_dni()
            wiersze = []
            for nazwa, ik, im, data_o, prz_o, p_km, p_dni, opony in c.fetchall():
                wiersze.append([
                    nazwa or "",
                    f"{int(ik)} km" if ik else "",
                    f"{formatuj_liczba_eksport(im, 0)} mies." if im else "",
                    data_o or "",
                    int(prz_o or 0) if prz_o else "",
                    f"{int(p_km)} km" if p_km else f"{dom_km} km (domyślny)",
                    f"{int(p_dni)} dni" if p_dni else f"{dom_dni} dni (domyślny)",
                    "Tak" if opony else "Nie",
                ])
            wynik["zadania"] = (
                ["Podzespół", "Interwał km", "Interwał czasowy", "Ostatnia wymiana",
                 "Przebieg ost. wymiany", "Próg (km)", "Próg (dni)", "Dotyczy opon"],
                wiersze
            )

        if "wydatki_cykliczne" in kategorie:
            c.execute(
                "SELECT nazwa, kwota, okres_dni, nastepna_data, czy_koszt FROM wydatki_cykliczne "
                "WHERE auto_id=? ORDER BY nazwa", (auto_id,)
            )
            wiersze = [
                [n or "", formatuj_liczba_eksport(kw) if ck else "", int(okr or 0), nd or "", "Koszt" if ck else "Przypomnienie"]
                for n, kw, okr, nd, ck in c.fetchall()
            ]
            wynik["wydatki_cykliczne"] = (["Nazwa", "Kwota", "Co ile dni", "Następna płatność", "Typ"], wiersze)

        if "warsztaty" in kategorie:
            c.execute(
                "SELECT nazwa, telefon, adres, notatki FROM warsztaty WHERE auto_id=? ORDER BY nazwa",
                (auto_id,)
            )
            wiersze = [[n or "", tel or "", adr or "", nt or ""] for n, tel, adr, nt in c.fetchall()]
            wynik["warsztaty"] = (["Nazwa", "Telefon", "Adres", "Notatki"], wiersze)

        if "odczyty_przebiegu" in kategorie:
            c.execute("SELECT data, przebieg, notatka FROM odczyty_przebiegu WHERE auto_id=?", (auto_id,))
            wiersze = [
                [data, int(prz or 0), notatka or ""] for data, prz, notatka in c.fetchall()
                if _data_w_zakresie(data, od_data, do_data)
            ]
            wiersze.sort(key=lambda w: parsuj_date(w[0]))
            wynik["odczyty_przebiegu"] = (["Data", "Przebieg (km)", "Notatka"], wiersze)

        if "tagi" in kategorie:
            c.execute("SELECT nazwa, kolor FROM tagi WHERE auto_id=? ORDER BY nazwa", (auto_id,))
            wiersze = [[n or "", k or ""] for n, k in c.fetchall()]
            wynik["tagi"] = (["Nazwa", "Kolor"], wiersze)

    return wynik


def oblicz_podsumowanie_okresu(auto_id, od_data=None, do_data=None):
    """Zbiorcze koszty i wskaźniki (jak w porównaniu pojazdów), przycięte do okresu —
    używane w nagłówku raportu PDF."""
    if not auto_id:
        return None

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT data, kwota, litry, przebieg, do_pelna FROM tankowania WHERE auto_id=?", (auto_id,))
        tankowania = [r for r in c.fetchall() if _data_w_zakresie(r[0], od_data, do_data)]

        c.execute(
            "SELECT h.data, h.cena FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE z.auto_id=? AND h.wizyta_id IS NULL", (auto_id,)
        )
        historia = [r for r in c.fetchall() if _data_w_zakresie(r[0], od_data, do_data)]

        c.execute("SELECT data, koszt_calkowity FROM wizyty WHERE auto_id=?", (auto_id,))
        wizyty = [r for r in c.fetchall() if _data_w_zakresie(r[0], od_data, do_data)]

        c.execute("SELECT data, kwota FROM inne_koszty WHERE auto_id=?", (auto_id,))
        inne = [r for r in c.fetchall() if _data_w_zakresie(r[0], od_data, do_data)]

    koszt_paliwo = sum(float(t[1] or 0) for t in tankowania)
    koszt_serwis = sum(float(h[1] or 0) for h in historia) + sum(float(w[1] or 0) for w in wizyty)
    koszt_inne = sum(float(i[1] or 0) for i in inne)
    razem = koszt_paliwo + koszt_serwis + koszt_inne

    tank_sort = sorted(tankowania, key=lambda t: int(t[3] or 0))
    dystans = 0
    if len(tank_sort) >= 2:
        dystans = max(0, int(tank_sort[-1][3] or 0) - int(tank_sort[0][3] or 0))
    koszt_km = (razem / dystans) if dystans > 0 else None

    spalanie = None
    peln_idx = [i for i, t in enumerate(tank_sort) if t[4]]
    if len(peln_idx) >= 2:
        p, o = peln_idx[0], peln_idx[-1]
        d_p = int(tank_sort[o][3] or 0) - int(tank_sort[p][3] or 0)
        l_p = sum(float(tank_sort[k][2] or 0) for k in range(p + 1, o + 1))
        if d_p > 0:
            spalanie = (l_p / d_p) * 100

    return {
        "koszt_paliwo": koszt_paliwo, "koszt_serwis": koszt_serwis, "koszt_inne": koszt_inne,
        "razem": razem, "dystans": dystans, "koszt_km": koszt_km, "spalanie": spalanie,
        "waluta": pobierz_walute(),
    }


def generuj_csv(naglowki, wiersze):
    """Bajty pliku CSV (BOM UTF-8, separator ';') — ';' i przecinek dziesiętny
    (patrz formatuj_liczba_eksport) pasują do polskiego Excela."""
    bufor = io.StringIO()
    writer = csv.writer(bufor, delimiter=';', lineterminator='\r\n')
    writer.writerow(naglowki)
    for w in wiersze:
        writer.writerow(w)
    return ('\ufeff' + bufor.getvalue()).encode('utf-8')


def generuj_eksport_csv(dane_eksportu):
    """
    dane_eksportu: {klucz: (naglowki, wiersze)} z pobierz_dane_eksportu().
    1 kategoria -> (bajty, 'csv'). Więcej -> każda kategoria jako osobny .csv
    w archiwum ZIP -> (bajty, 'zip').
    """
    klucze = list(dane_eksportu.keys())
    if len(klucze) == 1:
        naglowki, wiersze = dane_eksportu[klucze[0]]
        return generuj_csv(naglowki, wiersze), "csv"

    bufor = io.BytesIO()
    with zipfile.ZipFile(bufor, "w", zipfile.ZIP_DEFLATED) as zf:
        for klucz, (naglowki, wiersze) in dane_eksportu.items():
            zf.writestr(f"{klucz}.csv", generuj_csv(naglowki, wiersze))
    bufor.seek(0)
    return bufor.read(), "zip"


class _RaportPDF(FPDF if FPDF is not None else object):
    """Wrapper na FPDF z automatycznym doborem czcionki: jeśli w assets/ jest
    DejaVuSans(.ttf/-Bold.ttf), używa jej (pełne wsparcie polskich znaków).
    W przeciwnym razie używa wbudowanej Helvetiki i transliteruje diakrytyki (metoda t()).
    orientation: "L" (poziomo, domyślnie — pasuje do szerokich tabel w zwykłym
    raporcie) albo "P" (pionowo — używane przez tryb paszportu pojazdu)."""
    def __init__(self, orientation="L"):
        super().__init__(orientation=orientation, unit="mm", format="A4")
        self.set_auto_page_break(auto=True, margin=15)
        self.uzywa_utf8 = False
        self.czcionka = "Helvetica"
        if os.path.exists(CZCIONKA_PDF_REGULAR):
            try:
                self.add_font("DejaVu", "", CZCIONKA_PDF_REGULAR)
                self.add_font("DejaVu", "B", CZCIONKA_PDF_BOLD if os.path.exists(CZCIONKA_PDF_BOLD) else CZCIONKA_PDF_REGULAR)
                self.czcionka = "DejaVu"
                self.uzywa_utf8 = True
            except Exception:
                self.czcionka = "Helvetica"

    def t(self, tekst):
        tekst = "" if tekst is None else str(tekst)
        
        # 1. Zamieniamy typograficzne ozdobniki z aplikacji na zwykłe odpowiedniki ASCII
        zamienniki = {
            '•': '-', '▲': '^', '—': '-', '–': '-', '„': '"', '”': '"', '…': '...'
        }
        for znak, zamiennik in zamienniki.items():
            tekst = tekst.replace(znak, zamiennik)
            
        # 2. TWARDE CZYSZCZENIE: Zostawiamy TYLKO znaki podstawowe i rozszerzone łacińskie (w tym polskie ogonki).
        # To wycina absolutnie wszystkie emoji, chińskie znaczki czy niewidzialne błędy formatowania.
        tekst = re.sub(r'[^\u0000-\u017F]', '', tekst)
        
        # 3. Jeśli nie załadowało czcionki DejaVu, "spłaszczamy" polskie znaki do zwykłych
        if not self.uzywa_utf8:
            tekst = tekst.translate(_MAPA_TRANSLITERACJI_PL)
            tekst = tekst.encode('latin-1', 'replace').decode('latin-1')
            
        return tekst


__all__ = [
    "CZCIONKA_PDF_BOLD",
    "CZCIONKA_PDF_REGULAR",
    "FOLDER_ASSETS",
    "KATEGORIE_EKSPORTU",
    "_MAPA_TRANSLITERACJI_PL",
    "_RaportPDF",
    "_data_w_zakresie",
    "generuj_csv",
    "generuj_eksport_csv",
    "oblicz_podsumowanie_okresu",
    "pobierz_dane_eksportu",
]
