"""Raport miesiąca na jedną stronę A4 (W-21): treść z `podsumowanie_miesiaca` (te same liczby,
co ekran i grafika), wpisy od najstarszego, terminy następnego miesiąca tylko te jeszcze przed
nami — i twardy warunek jednej strony: nadmiar wpisów schodzi do wiersza „i jeszcze N”."""

import asyncio
import re
import zlib
from datetime import date, datetime

import pytest

import db
import pomoce
import utils
from date import na_iso
from views.eksport_view import EksportView
from views.miesiac_view import MiesiacWPigulceView


class _Zegar(datetime):
    teraz = datetime(2026, 10, 15, 12, 0)

    @classmethod
    def now(cls, tz=None):
        return cls.teraz


@pytest.fixture
def pazdziernik(monkeypatch):
    """15.10.2026: październik w toku — tankowanie, wizyta z pozycją (liczona raz), koszt po
    dzisiejszym dniu (nie wchodzi), wrzesień i październik rok wcześniej do porównań."""
    monkeypatch.setattr(db.analiza, "datetime", _Zegar)
    with db.polacz_baze() as conn:
        a = conn.execute("INSERT INTO samochody (nazwa, nr_rej, typ_paliwa, status, rola_wspoldzielenia) "
                         "VALUES (?,?,?,?,?)", ("Miesięczny", "PO 12345", "Benzyna", db.STATUS_POJAZDU_AKTYWNY,
                                                db.ROLA_WLASCICIEL)).lastrowid
        conn.execute("INSERT INTO tankowania (auto_id, data, data_iso, przebieg, litry, kwota, do_pelna, stacja, "
                     "rodzaj_energii) VALUES (?,?,?,?,?,?,?,?,?)",
                     (a, "02.10.2026", "2026-10-02", 10000, 40.0, 200.0, 1, "Orlen", db.ENERGIA_PALIWO))
        zadanie = conn.execute("INSERT INTO zadania (auto_id, nazwa) VALUES (?,?)", (a, "Olej")).lastrowid
        wizyta = conn.execute("INSERT INTO wizyty (auto_id, data, data_iso, przebieg, wykonawca, koszt_calkowity) "
                              "VALUES (?,?,?,?,?,?)", (a, "11.10.2026", "2026-10-11", 10300, "Serwis ASO", 900.0)).lastrowid
        conn.execute("INSERT INTO historia (zadanie_id, wizyta_id, data, data_iso, przebieg, kategoria, cena, wykonawca) "
                     "VALUES (?,?,?,?,?,?,?,?)", (zadanie, wizyta, "11.10.2026", "2026-10-11", 10300, "Serwis", 700.0,
                                                  "Serwis ASO"))
        for dzien, kwota in (("20.10.2026", 5000.0), ("05.09.2026", 300.0), ("15.10.2025", 500.0)):
            conn.execute("INSERT INTO inne_koszty (auto_id, data, data_iso, kategoria, nazwa, kwota) VALUES (?,?,?,?,?,?)",
                         (a, dzien, na_iso(dzien), db.KATEGORIA_INNE_DOMYSLNA, "Myjnia", kwota))
    db.zanotuj_zmiane_danych()
    return a


def _tekst_pdf(bajty):
    """Napisy ze wszystkich strumieni PDF (fpdf2 kompresuje treść stron)."""
    teksty = []
    for strumien in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", bajty, re.S):
        try:
            teksty.append(zlib.decompress(strumien).decode("latin-1"))
        except zlib.error:
            teksty.append(strumien.decode("latin-1"))
    return "\n".join(teksty)


def _strony(bajty):
    return len(re.findall(rb"/Type\s*/Page\b(?!s)", bajty))


def test_tresc_raportu_to_liczby_miesiaca(baza, pazdziernik):
    w = utils.symbol_waluty()
    dane = db.dane_raportu_miesiaca(pazdziernik, 2026, 10, dzis=date(2026, 10, 15))
    assert dane["tytul"] == "Raport miesiąca: październik 2026"
    assert dane["podtytul"] == "Miesięczny · PO 12345 · miesiąc w toku, stan na 15.10.2026"
    assert [k[0] for k in dane["kafle"]][:2] == ["Przejechane", "Wydane łącznie"]
    assert dane["porownania"] == [f"Względem września (do 15.09): 300 {w} (+267%)",
                                  f"Względem października 2025 (do 15.10): 500 {w} (+120%)"]
    assert dane["kategorie"] == [("Paliwo i energia", f"200,00 {w}", 18), ("Serwis", f"900,00 {w}", 82),
                                 ("Inne koszty", f"0,00 {w}", 0)]
    assert dane["wpisy"] == [("02.10", "Tankowanie", "Orlen, 40,00 l, do pełna", f"200,00 {w}"),
                             ("11.10", "Wizyta", "Serwis ASO", f"900,00 {w}")]
    assert dane["suma_wpisow"] == f"1 100,00 {w}"
    assert (dane["tytul_terminow"], dane["terminy"]) == ("Terminy: listopad 2026", [])
    assert dane["nazwa_pliku"] == "raport_2026-10"
    assert db.dane_raportu_miesiaca(pazdziernik, 2026, 8, dzis=date(2026, 10, 15)) is None


def test_terminy_tylko_te_przed_nami(baza, pazdziernik):
    with db.polacz_baze() as conn:
        conn.execute("UPDATE samochody SET oc_data=?, przeglad_data=? WHERE id=?",
                     ("12.11.2026", "20.10.2026", pazdziernik))
    db.zanotuj_zmiane_danych()
    biezacy = db.dane_raportu_miesiaca(pazdziernik, 2026, 10, dzis=date(2026, 10, 15))
    assert [t[:2] for t in biezacy["terminy"]] == [("12.11", "Polisa OC")]
    # Wrzesień drukowany 15.10: z października została druga połowa — z przeglądem 20.10.
    wrzesien = db.dane_raportu_miesiaca(pazdziernik, 2026, 9, dzis=date(2026, 10, 15))
    assert wrzesien["tytul_terminow"] == "Terminy: październik 2026 (od 15.10)"
    assert [t[:2] for t in wrzesien["terminy"]] == [("20.10", "Przegląd techniczny")]
    # Październik 2025: listopad 2025 dawno minął — sekcji nie ma.
    stary = db.dane_raportu_miesiaca(pazdziernik, 2025, 10, dzis=date(2026, 10, 15))
    assert (stary["tytul_terminow"], stary["terminy"]) == (None, [])


def test_pdf_ma_zawsze_jedna_strone(baza, pazdziernik):
    dane = db.dane_raportu_miesiaca(pazdziernik, 2026, 10, dzis=date(2026, 10, 15))
    pdf = db.generuj_pdf_miesiaca(dane)
    assert pdf.startswith(b"%PDF") and _strony(pdf) == 1
    tekst = _tekst_pdf(pdf)
    assert "Serwis ASO" in tekst and "i jeszcze" not in tekst

    # Sześćdziesiąt wpisów nie zrobi drugiej strony — reszta to jeden wiersz.
    dane["wpisy"] = [(f"{d % 28 + 1:02d}.10", "Inny koszt", f"Wpis numer {d}", "10,00 PLN") for d in range(60)]
    pdf = db.generuj_pdf_miesiaca(dane)
    tekst = _tekst_pdf(pdf)
    assert _strony(pdf) == 1 and "i jeszcze" in tekst and "Wpis numer 0" in tekst and "Wpis numer 59" not in tekst

    # Bez wpisów, porównań, przebiegu i terminów też jedna, poprawna strona.
    dane.update({"wpisy": [], "porownania": [], "przebieg": [], "tytul_terminow": None, "terminy": []})
    assert _strony(db.generuj_pdf_miesiaca(dane)) == 1


def _zapis(monkeypatch, strona):
    zapisane = []

    async def zapisz(nazwa, bajty):
        zapisane.append((nazwa, bajty))
        return True

    strona.page.zapisz_bajty_pliku = zapisz
    for nazwa in ("pokaz_ladowanie", "ukryj_ladowanie", "pokaz_komunikat"):
        monkeypatch.setattr(utils, nazwa, lambda *a, **k: None)
    return zapisane


def test_przycisk_na_ekranie_miesiaca_zapisuje_pdf(baza, pazdziernik, monkeypatch):
    strona = pomoce.zbuduj_strone()
    zapisane = _zapis(monkeypatch, strona)
    widok = MiesiacWPigulceView(strona.page, pomoce.stan_aplikacji(pazdziernik, "Miesięczny"), 2026, 10)
    assert "Raport PDF na jedną stronę A4" in pomoce.napisy(widok)
    asyncio.run(widok._zapisz_raport(None))
    (nazwa, bajty), = zapisane
    assert nazwa.startswith("raport_2026-10_") and nazwa.endswith(".pdf") and bajty.startswith(b"%PDF")


def test_eksport_zapisuje_raport_wybranego_miesiaca(baza, pazdziernik, monkeypatch):
    strona = pomoce.zbuduj_strone()
    zapisane = _zapis(monkeypatch, strona)
    widok = EksportView(strona.page, pomoce.stan_aplikacji(pazdziernik, "Miesięczny"), lambda *a: None)
    assert widok.e_miesiac_raportu.value == "2026-9", "domyślnie ostatni PEŁNY miesiąc, jak w pigułce"
    assert [o.key for o in widok.e_miesiac_raportu.options][:2] == ["2026-10", "2026-9"]
    widok.e_miesiac_raportu.value = "2026-10"
    asyncio.run(widok.zapisz_raport_miesiaca(None))
    assert zapisane[0][0].startswith("raport_2026-10_") and zapisane[0][1].startswith(b"%PDF")

    pusty = EksportView(strona.page, pomoce.stan_aplikacji(), lambda *a: None)
    assert "Brak wybranego pojazdu" in pomoce.napisy(pusty)
