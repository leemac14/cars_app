"""Wyszukiwanie globalne, w tym zapytania kwotowe."""

import re
import sqlite3
from date import parsuj_date

from .polaczenie import polacz_baze
from .pomocnicze import formatuj_liczba_eksport
from .ustawienia import pobierz_walute


# Zapytanie kwotowe rozpoznajemy WPROST w polu wyszukiwarki — bez dodatkowych
# kontrolek, tak jak „>1000” czy „200-500” pisze się w arkuszu kalkulacyjnym.
# Sam tekst dalej działa jak dotąd; kwota to tylko dodatkowa ścieżka.
_WZORZEC_ZAKRESU = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(?:-|–|—|\.\.|do)\s*(\d+(?:[.,]\d+)?)$")

_WZORZEC_POROWNANIA = re.compile(r"^(>=|<=|>|<|od|do)\s*(\d+(?:[.,]\d+)?)$", re.IGNORECASE)

_WZORZEC_LICZBY = re.compile(r"^(\d+(?:[.,]\d+)?)$")


# Tolerancja dla „szukam kwoty około tyle”: paragon rzadko pamięta się co do
# grosza, więc samo „450” łapie 441–459 zamiast wyłącznie równych 450.
TOLERANCJA_KWOTY = 0.02


def _na_liczbe(tekst):
    try:
        return float(str(tekst).replace("\xa0", "").replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def parsuj_zapytanie_kwotowe(zapytanie):
    """Rozpoznaje zapytanie o kwotę i zwraca (min, max, opis) albo None.

    Obsługiwane formy: „450” (±2%), „>1000”, „>=1000”, „<50”, „<=50”,
    „200-500” (też z półpauzą, „..” i słowem „do”), „od 200”, „do 500”.
    """
    tekst = " ".join(str(zapytanie or "").split())
    if not tekst:
        return None

    dopasowanie = _WZORZEC_ZAKRESU.match(tekst)
    if dopasowanie:
        a, b = _na_liczbe(dopasowanie.group(1)), _na_liczbe(dopasowanie.group(2))
        if a is None or b is None:
            return None
        dolna, gorna = min(a, b), max(a, b)
        return (dolna, gorna, f"kwota od {formatuj_liczba_eksport(dolna, 2)} do {formatuj_liczba_eksport(gorna, 2)}")

    dopasowanie = _WZORZEC_POROWNANIA.match(tekst)
    if dopasowanie:
        operator = dopasowanie.group(1).lower()
        wartosc = _na_liczbe(dopasowanie.group(2))
        if wartosc is None:
            return None
        if operator in (">", ">=", "od"):
            return (wartosc, None, f"kwota od {formatuj_liczba_eksport(wartosc, 2)}")
        return (None, wartosc, f"kwota do {formatuj_liczba_eksport(wartosc, 2)}")

    dopasowanie = _WZORZEC_LICZBY.match(tekst)
    if dopasowanie:
        wartosc = _na_liczbe(dopasowanie.group(1))
        if wartosc is None:
            return None
        margines = max(wartosc * TOLERANCJA_KWOTY, 0.5)
        return (wartosc - margines, wartosc + margines,
                f"kwota około {formatuj_liczba_eksport(wartosc, 2)}")

    return None


def _w_zakresie(wartosc, dolna, gorna):
    if wartosc is None:
        return False
    try:
        wartosc = float(wartosc)
    except (TypeError, ValueError):
        return False
    if dolna is not None and wartosc < dolna - 1e-9:
        return False
    if gorna is not None and wartosc > gorna + 1e-9:
        return False
    return True


def wyszukiwanie_po_kwocie(auto_id, dolna, gorna):
    """Przeszukuje WSZYSTKIE kwoty pojazdu: tankowania, wpisy serwisowe, wizyty,
    inne koszty, ceny w magazynie i oponach, szacunki z listy Do zrobienia oraz
    wydatki cykliczne. Zwraca ten sam kształt wyników, co globalne_wyszukiwanie."""
    if not auto_id or (dolna is None and gorna is None):
        return []

    waluta = pobierz_walute()
    wyniki = []

    def dodaj(typ, tytul, kwota, opis, data, trasa, **extra):
        if not _w_zakresie(kwota, dolna, gorna):
            return
        pelny_opis = f"{formatuj_liczba_eksport(kwota, 2)} {waluta}"
        if opis:
            pelny_opis += f" • {opis}"
        wpis = {"typ": typ, "tytul": tytul, "opis": pelny_opis, "data": data or "", "trasa": trasa}
        wpis.update(extra)
        wyniki.append(wpis)

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("SELECT id, data, kwota, litry, stacja FROM tankowania WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            opis = f"{formatuj_liczba_eksport(r['litry'], 1)} L"
            if r["stacja"]:
                opis += f" • {r['stacja']}"
            dodaj("Tankowanie", r["stacja"] or "Tankowanie", r["kwota"], opis,
                  r["data"], f"/tankowanie/edytuj/{r['id']}")

        c.execute(
            "SELECT h.id, h.data, h.cena, h.wykonawca, z.nazwa FROM historia h "
            "JOIN zadania z ON h.zadanie_id=z.id WHERE z.auto_id=? AND h.wizyta_id IS NULL",
            (auto_id,)
        )
        for r in c.fetchall():
            dodaj("Serwis", str(r["nazwa"]), r["cena"], r["wykonawca"] or "",
                  r["data"], f"/wpis/edytuj/{r['id']}")

        c.execute(
            "SELECT w.id, w.data, w.koszt_calkowity, w.wykonawca, "
            "GROUP_CONCAT(z.nazwa, ', ') AS czesci FROM wizyty w "
            "LEFT JOIN historia h ON h.wizyta_id=w.id LEFT JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE w.auto_id=? GROUP BY w.id",
            (auto_id,)
        )
        for r in c.fetchall():
            opis = str(r["czesci"] or "Brak podpiętych części")
            if r["wykonawca"]:
                opis += f" • {r['wykonawca']}"
            dodaj("Wizyta zbiorcza", "Wizyta w warsztacie", r["koszt_calkowity"], opis,
                  r["data"], f"/wizyty/edytuj/{r['id']}")

        c.execute("SELECT id, data, nazwa, kwota, kategoria, tagi FROM inne_koszty WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            dodaj("Inny koszt", str(r["nazwa"] or "Koszt"), r["kwota"],
                  str(r["kategoria"] or r["tagi"] or ""), r["data"], f"/inne/edytuj/{r['id']}")

        c.execute("SELECT id, nazwa, cena, ilosc, jednostka FROM magazyn_czesci WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            dodaj("Magazyn", str(r["nazwa"]), r["cena"],
                  f"{formatuj_liczba_eksport(r['ilosc'], 2)} {r['jednostka'] or 'szt'}", "", "/magazyn")

        c.execute("SELECT id, sezon, rozmiar, marka_model, cena, data_zakupu FROM zestawy_opon WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            opis = str(r["rozmiar"] or "")
            if r["marka_model"]:
                opis += f" • {r['marka_model']}" if opis else str(r["marka_model"])
            dodaj("Opony", f"Zestaw: {r['sezon']}", r["cena"], opis, r["data_zakupu"], "/magazyn")

        c.execute("SELECT id, tytul, szacowany_koszt, termin, priorytet FROM do_zrobienia WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            dodaj("Do zrobienia", str(r["tytul"]), r["szacowany_koszt"],
                  f"szacunek • {r['priorytet'] or 'bez priorytetu'}",
                  r["termin"], f"/do-zrobienia/edytuj/{r['id']}")

        c.execute("SELECT id, nazwa, kwota, okres_dni, nastepna_data, czy_koszt FROM wydatki_cykliczne WHERE auto_id=?", (auto_id,))
        for r in c.fetchall():
            if not r["czy_koszt"]:
                continue
            dodaj("Wydatek cykliczny", str(r["nazwa"]), r["kwota"],
                  f"co {int(r['okres_dni'] or 0)} dni", r["nastepna_data"], "__wydatki_cykliczne__")

    wyniki.sort(key=lambda w: parsuj_date(w["data"]), reverse=True)
    return wyniki


def skrot_notatki(tekst, maks=60):
    """Notatka w jednej linii wyniku wyszukiwania — bez tego długa uwaga
    rozpychałaby kartę wyniku i zasłaniała resztę opisu."""
    tekst = " ".join(str(tekst or "").split())
    if not tekst:
        return ""
    return tekst if len(tekst) <= maks else tekst[:maks - 1].rstrip() + "…"


def globalne_wyszukiwanie(auto_id, zapytanie):
    """Przeszukuje jednocześnie tankowania, historię serwisową, wizyty zbiorcze,
    inne koszty, notatki wpisów oraz listę Do zrobienia BIEŻĄCEGO pojazdu. Używane przez widok
    /szukaj — jedną wspólną wyszukiwarkę dostępną z paska głównego, w odróżnieniu
    od lokalnych pól filtruj_* działających tylko na już wczytanej liście.
    Zwraca listę słowników {typ, tytul, opis, data, trasa}, posortowaną malejąco
    po dacie (nierozpoznane daty lądują na końcu)."""
    if not auto_id or not zapytanie or not zapytanie.strip():
        return []

    # Zapytanie wyglądające na kwotę („450”, „>1000”, „200-500”) idzie zupełnie
    # inną ścieżką: porównujemy liczby, a nie tekst. Bez tego „450” trafiało
    # tylko tam, gdzie ten ciąg przypadkiem był w dacie albo nazwie.
    zakres = parsuj_zapytanie_kwotowe(zapytanie)
    if zakres:
        return wyszukiwanie_po_kwocie(auto_id, zakres[0], zakres[1])

    q = f"%{zapytanie.strip()}%"
    wyniki = []

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute(
            "SELECT id, data, przebieg, stacja, tagi, notatka FROM tankowania "
            "WHERE auto_id=? AND (stacja LIKE ? OR tagi LIKE ? OR data LIKE ? OR notatka LIKE ?)",
            (auto_id, q, q, q, q)
        )
        for r in c.fetchall():
            opis = f"{int(r['przebieg'] or 0)} km" + (f" • {r['stacja']}" if r["stacja"] else "")
            if r["notatka"]:
                opis += f" • {skrot_notatki(r['notatka'])}"
            wyniki.append({
                "typ": "Tankowanie", "tytul": r["stacja"] or "Tankowanie", "opis": opis,
                "data": r["data"], "trasa": f"/tankowanie/edytuj/{r['id']}",
            })

        c.execute(
            "SELECT h.id, h.data, h.przebieg, h.wykonawca, h.kategoria, h.notatka, z.nazwa "
            "FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE z.auto_id=? AND h.wizyta_id IS NULL AND "
            "(z.nazwa LIKE ? OR h.wykonawca LIKE ? OR h.kategoria LIKE ? OR h.data LIKE ? OR h.notatka LIKE ?)",
            (auto_id, q, q, q, q, q)
        )
        for r in c.fetchall():
            opis = f"{int(r['przebieg'] or 0)} km" + (f" • {r['wykonawca']}" if r["wykonawca"] else "")
            if r["notatka"]:
                opis += f" • {skrot_notatki(r['notatka'])}"
            wyniki.append({
                "typ": "Serwis", "tytul": str(r["nazwa"]), "opis": opis,
                "data": r["data"], "trasa": f"/wpis/edytuj/{r['id']}",
            })

        c.execute(
            "SELECT id, nazwa, interwal_km, interwal_miesiace FROM zadania "
            "WHERE auto_id=? AND nazwa LIKE ?",
            (auto_id, q)
        )
        for r in c.fetchall():
            bits = []
            if r["interwal_km"]:
                bits.append(f"co {int(r['interwal_km'])} km")
            if r["interwal_miesiace"]:
                bits.append(f"co {int(r['interwal_miesiace'])} mies.")
            opis = " • ".join(bits) if bits else "Brak ustawionego interwału"
            wyniki.append({
                "typ": "Podzespół", "tytul": str(r["nazwa"]), "opis": opis,
                "data": "", "trasa": f"/historia/{r['id']}",
            })

        c.execute(
            "SELECT w.id, w.data, w.wykonawca, w.notatki, w.tagi, "
            "GROUP_CONCAT(z.nazwa, ', ') as czesci "
            "FROM wizyty w LEFT JOIN historia h ON h.wizyta_id=w.id LEFT JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE w.auto_id=? GROUP BY w.id "
            "HAVING (w.wykonawca LIKE ? OR w.notatki LIKE ? OR w.tagi LIKE ? OR w.data LIKE ? OR czesci LIKE ?)",
            (auto_id, q, q, q, q, q)
        )
        for r in c.fetchall():
            opis = str(r["czesci"] or "Brak podpiętych części") + (f" • {r['wykonawca']}" if r["wykonawca"] else "")
            wyniki.append({
                "typ": "Wizyta zbiorcza", "tytul": "Wizyta w warsztacie", "opis": opis,
                "data": r["data"], "trasa": f"/wizyty/edytuj/{r['id']}",
            })

        c.execute(
            "SELECT id, data, nazwa, kategoria, tagi, notatka FROM inne_koszty "
            "WHERE auto_id=? AND (nazwa LIKE ? OR kategoria LIKE ? OR tagi LIKE ? OR data LIKE ? OR notatka LIKE ?)",
            (auto_id, q, q, q, q, q)
        )
        for r in c.fetchall():
            opis = str(r["kategoria"] or r["tagi"] or "Inny koszt")
            if r["notatka"]:
                opis += f" • {skrot_notatki(r['notatka'])}"
            wyniki.append({
                "typ": "Inny koszt", "tytul": str(r["nazwa"] or "Koszt"), "opis": opis,
                "data": r["data"], "trasa": f"/inne/edytuj/{r['id']}",
            })

        c.execute(
            "SELECT id, tytul, opis, priorytet, termin FROM do_zrobienia "
            "WHERE auto_id=? AND (tytul LIKE ? OR opis LIKE ? OR priorytet LIKE ?)",
            (auto_id, q, q, q)
        )
        for r in c.fetchall():
            wyniki.append({
                "typ": "Do zrobienia", "tytul": str(r["tytul"]), "opis": str(r["opis"] or r["priorytet"] or ""),
                "data": r["termin"] or "", "trasa": f"/do-zrobienia/edytuj/{r['id']}",
            })

        # Odczyty licznika trafiają do wyników WYŁĄCZNIE przez notatkę: sam
        # „12.03.2026 • 145 000 km” nie niesie treści, po której ktoś szuka,
        # ale zostawiona przy nim uwaga („licznik po wymianie zegarów”) — owszem.
        c.execute(
            "SELECT id, data, przebieg, notatka FROM odczyty_przebiegu "
            "WHERE auto_id=? AND notatka LIKE ?",
            (auto_id, q)
        )
        for r in c.fetchall():
            wyniki.append({
                "typ": "Odczyt licznika",
                "tytul": f"{formatuj_liczba_eksport(r['przebieg'] or 0, 0)} km",
                "opis": skrot_notatki(r["notatka"]),
                "data": r["data"], "trasa": "/przebieg",
            })

        # NOWE: Magazyn (części i płyny) — było obiecane w podpowiedzi wyszukiwarki
        # ("część"), ale dotąd nieprzeszukiwane.
        c.execute(
            "SELECT id, nazwa, kategoria, ilosc, jednostka FROM magazyn_czesci "
            "WHERE auto_id=? AND (nazwa LIKE ? OR kategoria LIKE ?)",
            (auto_id, q, q)
        )
        for r in c.fetchall():
            opis = f"{formatuj_liczba_eksport(r['ilosc'], 2)} {r['jednostka'] or 'szt'}" + (f" • {r['kategoria']}" if r["kategoria"] else "")
            wyniki.append({
                "typ": "Magazyn", "tytul": str(r["nazwa"]), "opis": opis,
                "data": "", "trasa": "/magazyn",
            })

        # NOWE: Zestawy opon
        c.execute(
            "SELECT id, sezon, rozmiar, marka_model, numer_dot FROM zestawy_opon "
            "WHERE auto_id=? AND (sezon LIKE ? OR rozmiar LIKE ? OR marka_model LIKE ? OR numer_dot LIKE ?)",
            (auto_id, q, q, q, q)
        )
        for r in c.fetchall():
            opis = str(r["rozmiar"] or "") + (f" • {r['marka_model']}" if r["marka_model"] else "")
            wyniki.append({
                "typ": "Opony", "tytul": f"Zestaw: {r['sezon']}", "opis": opis,
                "data": "", "trasa": "/magazyn",
            })

        # NOWE: Warsztaty
        c.execute(
            "SELECT id, nazwa, telefon, adres, notatki FROM warsztaty "
            "WHERE auto_id=? AND (nazwa LIKE ? OR telefon LIKE ? OR adres LIKE ? OR notatki LIKE ?)",
            (auto_id, q, q, q, q)
        )
        for r in c.fetchall():
            opis = str(r["adres"] or "") + (f" • {r['telefon']}" if r["telefon"] else "")
            wyniki.append({
                "typ": "Warsztat", "tytul": str(r["nazwa"]), "opis": opis or "Brak telefonu / adresu",
                "data": "", "trasa": "/wizyty",
            })

        # NOWE: Wydatki cykliczne
        c.execute(
            "SELECT id, nazwa, kwota, okres_dni, nastepna_data, czy_koszt FROM wydatki_cykliczne "
            "WHERE auto_id=? AND nazwa LIKE ?",
            (auto_id, q)
        )
        for r in c.fetchall():
            if r["czy_koszt"]:
                opis = f"{formatuj_liczba_eksport(r['kwota'], 2)} {pobierz_walute()} • co {int(r['okres_dni'] or 0)} dni"
            else:
                opis = f"Przypomnienie • co {int(r['okres_dni'] or 0)} dni"
            wyniki.append({
                "typ": "Wydatek cykliczny", "tytul": str(r["nazwa"]), "opis": opis,
                "data": r["nastepna_data"] or "", "trasa": "__wydatki_cykliczne__",
            })

        # Zapisane trasy kalkulatora i checklisty — szuka się ich po nazwie
        # („teściów”, „przed zimą”), a bez tego były jedynymi danymi pojazdu
        # niewidocznymi dla wyszukiwarki.
        c.execute(
            "SELECT id, nazwa, dystans, powrot, osoby FROM trasy_szablony "
            "WHERE auto_id=? AND (nazwa LIKE ? OR notatki LIKE ?)",
            (auto_id, q, q)
        )
        for r in c.fetchall():
            opis = f"{formatuj_liczba_eksport(r['dystans'], 0)} km"
            if r["powrot"]:
                opis += " • tam i z powrotem"
            opis += f" • {int(r['osoby'] or 1)} os."
            wyniki.append({
                "typ": "Zapisana trasa", "tytul": str(r["nazwa"]), "opis": opis,
                "data": "", "trasa": "/kalkulator",
            })

        c.execute(
            "SELECT l.id, l.nazwa, l.ostatnie_uzycie, "
            "       (SELECT COUNT(*) FROM checklisty_pozycje p WHERE p.checklista_id = l.id) AS razem, "
            "       (SELECT COUNT(*) FROM checklisty_pozycje p WHERE p.checklista_id = l.id AND p.odhaczone=1) AS zrobione "
            "FROM checklisty l WHERE l.auto_id=? AND (l.nazwa LIKE ? OR l.opis LIKE ? OR EXISTS "
            "   (SELECT 1 FROM checklisty_pozycje p WHERE p.checklista_id = l.id AND p.tresc LIKE ?))",
            (auto_id, q, q, q)
        )
        for r in c.fetchall():
            wyniki.append({
                "typ": "Checklista", "tytul": str(r["nazwa"]),
                "opis": f"odhaczone {int(r['zrobione'] or 0)} z {int(r['razem'] or 0)}",
                "data": r["ostatnie_uzycie"] or "", "trasa": "__checklisty__",
            })

        # NOWE: Podzespoły — samodzielna kategoria, bo świeżo dodany podzespół bez
        # ŻADNEJ historii wymiany (powyższy JOIN wymaga wpisu w historii) był dotąd
        # całkowicie niewidoczny dla wyszukiwarki.
        c.execute(
            "SELECT id, nazwa FROM zadania WHERE auto_id=? AND nazwa LIKE ?",
            (auto_id, q)
        )
        for r in c.fetchall():
            wyniki.append({
                "typ": "Podzespół", "tytul": str(r["nazwa"]), "opis": "Śledzony podzespół",
                "data": "", "trasa": f"/historia/{r['id']}",
            })

    wyniki.sort(key=lambda w: parsuj_date(w["data"]), reverse=True)

    return wyniki


__all__ = [
    "TOLERANCJA_KWOTY",
    "_WZORZEC_LICZBY",
    "_WZORZEC_POROWNANIA",
    "_WZORZEC_ZAKRESU",
    "_na_liczbe",
    "_w_zakresie",
    "globalne_wyszukiwanie",
    "parsuj_zapytanie_kwotowe",
    "skrot_notatki",
    "wyszukiwanie_po_kwocie",
]
