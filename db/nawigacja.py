"""Pamięć nawigacji: kokpit, przypięte skróty, liczniki i ostatnie ekrany."""

import sqlite3
from datetime import datetime

from .polaczenie import polacz_baze
from .ustawienia import pobierz_ustawienie, zapisz_ustawienie
from .pojazd import terminy_pojazdu
from .kosz import liczba_w_koszu


def _sparsuj_datetime(tekst):
    """Parsuje string w formacie 'DD.MM.YYYY' lub 'DD.MM.YYYY HH:MM' na obiekt
    datetime — pomocnicze dla pobierz_ostatnia_aktywnosc(), żeby móc sortować
    na wspólnej osi dodania (bez godziny — nigdy nie była zapisywana) i edycje
    (z dokładną godziną, patrz data_modyfikacji)."""
    if not tekst:
        return None
    for wzorzec in ("%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return datetime.strptime(str(tekst).strip(), wzorzec)
        except ValueError:
            continue
    return None


def pobierz_ostatnia_aktywnosc(auto_id, limit=5):
    """Zwraca listę ostatnich zdarzeń (dodań i edycji) z tankowań, serwisu,
    wizyt i innych kosztów — dla widżetu 'Ostatnia aktywność' w kokpicie
    (patrz MainView._buduj_kokpit). Każde zdarzenie to krotka:
    (opis, kto, kiedy_tekst, kiedy_sort, ikona, trasa). Dodanie i edycja tego
    samego wpisu mogą pojawić się jako dwa osobne zdarzenia.
    `ikona` to KLUCZ ("tankowanie" / "serwis" / "wizyta" / "inny_koszt"), który
    warstwa UI tłumaczy na ft.Icons przez utils.IKONY_AKTYWNOSCI."""
    if not auto_id:
        return []

    zdarzenia = []

    def _dodaj(dana_data, dodane_przez, zmodyfikowane_przez, data_modyfikacji, opis, ikona, trasa):
        if dodane_przez:
            kiedy_sort = _sparsuj_datetime(dana_data)
            if kiedy_sort:
                zdarzenia.append((f"Dodano: {opis}", dodane_przez, str(dana_data), kiedy_sort, ikona, trasa))
        if zmodyfikowane_przez and data_modyfikacji:
            kiedy_sort = _sparsuj_datetime(data_modyfikacji)
            if kiedy_sort:
                zdarzenia.append((f"Edytowano: {opis}", zmodyfikowane_przez, str(data_modyfikacji), kiedy_sort, ikona, trasa))

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute(
            "SELECT id, data, stacja, dodane_przez, zmodyfikowane_przez, data_modyfikacji "
            "FROM tankowania WHERE auto_id=?", (auto_id,)
        )
        for r in c.fetchall():
            opis = "Tankowanie" + (f" • {r['stacja']}" if r["stacja"] else "")
            _dodaj(r["data"], r["dodane_przez"], r["zmodyfikowane_przez"], r["data_modyfikacji"],
                   opis, "tankowanie", f"/tankowanie/edytuj/{r['id']}")

        c.execute(
            "SELECT h.id, h.data, z.nazwa, h.dodane_przez, h.zmodyfikowane_przez, h.data_modyfikacji "
            "FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE z.auto_id=? AND h.wizyta_id IS NULL", (auto_id,)
        )
        for r in c.fetchall():
            _dodaj(r["data"], r["dodane_przez"], r["zmodyfikowane_przez"], r["data_modyfikacji"],
                   str(r["nazwa"]), "serwis", f"/wpis/edytuj/{r['id']}")

        c.execute(
            "SELECT id, data, wykonawca, dodane_przez, zmodyfikowane_przez, data_modyfikacji "
            "FROM wizyty WHERE auto_id=?", (auto_id,)
        )
        for r in c.fetchall():
            opis = "Wizyta w warsztacie" + (f" • {r['wykonawca']}" if r["wykonawca"] else "")
            _dodaj(r["data"], r["dodane_przez"], r["zmodyfikowane_przez"], r["data_modyfikacji"],
                   opis, "wizyta", f"/wizyty/edytuj/{r['id']}")

        c.execute(
            "SELECT id, data, nazwa, dodane_przez, zmodyfikowane_przez, data_modyfikacji "
            "FROM inne_koszty WHERE auto_id=?", (auto_id,)
        )
        for r in c.fetchall():
            _dodaj(r["data"], r["dodane_przez"], r["zmodyfikowane_przez"], r["data_modyfikacji"],
                   str(r["nazwa"] or "Inny koszt"), "inny_koszt", f"/inne/edytuj/{r['id']}")

    zdarzenia.sort(key=lambda z: z[3], reverse=True)
    return zdarzenia[:limit]


LICZBA_ZAKLADEK_GLOWNYCH = 4   # Kokpit, Serwis, Koszty, Analiza


def zapamietaj_ostatnia_pozycje(auto_id, zakladka):
    """Zapamiętuje, na czym użytkownik skończył — pojazd i zakładkę główną.
    Wywoływane przy każdej nawigacji (patrz main.trasa_zmieniona), ale tylko
    wtedy, gdy coś się faktycznie zmieniło."""
    if auto_id:
        zapisz_ustawienie("ostatni_pojazd", str(int(auto_id)))
    zapisz_ustawienie("ostatnia_zakladka", str(int(zakladka or 0)))


def pobierz_ostatnia_zakladke():
    try:
        z = int(pobierz_ustawienie("ostatnia_zakladka", "0") or 0)
    except (TypeError, ValueError):
        return 0
    return z if 0 <= z < LICZBA_ZAKLADEK_GLOWNYCH else 0


def zapamietaj_podzakladke_kosztow(idx):
    zapisz_ustawienie("ostatnia_podzakladka_kosztow", str(int(idx or 0)))


def pobierz_podzakladke_kosztow():
    try:
        z = int(pobierz_ustawienie("ostatnia_podzakladka_kosztow", "0") or 0)
    except (TypeError, ValueError):
        return 0
    return z if z in (0, 1) else 0


# ============ PAMIĘĆ NAWIGACJI (rejestr ekranów żyje w utils.EKRANY) ============
# Tu trzymamy tylko to, CZEGO użytkownik używa — sam katalog ekranów jest po
# stronie UI, bo składa się z ikon Fleta. Rozdzielenie jest celowe: baza nie
# musi wiedzieć, jak ekran wygląda, a UI nie musi wiedzieć, jak liczyć użycia.

# Zestaw startowy skrótów: karta pojazdu i karoseria, bo nie leżą na żadnym
# pasku sekcji, plus to, po co sięga się najczęściej. Użytkownik i tak zmienia
# go jednym dotknięciem („Wybierz” nad siatką skrótów).
DOMYSLNE_PRZYPIETE = ["pojazd", "przebieg", "wizyty", "do-zrobienia", "karoseria", "rok"]

MAKS_PRZYPIETYCH = 8


def zanotuj_uzycie_ekranu(ekran_id):
    """Wywoływane przy każdym wejściu na ekran z rejestru. Cicho ignoruje błędy —
    statystyka używalności nigdy nie może wywrócić nawigacji."""
    if not ekran_id:
        return
    try:
        with polacz_baze() as conn:
            conn.execute(
                "INSERT INTO ekrany_uzycie (ekran_id, licznik, ostatnio) VALUES (?, 1, ?) "
                "ON CONFLICT(ekran_id) DO UPDATE SET licznik = licznik + 1, ostatnio = excluded.ostatnio",
                (str(ekran_id), datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
    except Exception:
        pass


def pobierz_ostatnie_ekrany(limit=5, pomin=()):
    """Ostatnio otwierane ekrany, najświeższy pierwszy. `pomin` odsiewa te, które
    i tak są już widoczne (np. przypięte kafelki), żeby nie dublować wejść."""
    try:
        with polacz_baze() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT ekran_id FROM ekrany_uzycie WHERE ostatnio IS NOT NULL "
                "ORDER BY ostatnio DESC LIMIT ?", (max(1, int(limit)) + len(pomin) + 4,)
            )
            wynik = [r[0] for r in c.fetchall() if r[0] not in set(pomin)]
        return wynik[:limit]
    except Exception:
        return []


def pobierz_przypiete_ekrany():
    """Kafelki skrótów na Kokpicie. Pusty wynik oznacza „użytkownik jeszcze nic
    nie wybrał” — wtedy dostaje sensowny zestaw startowy, a nie pustą sekcję.
    Świadomie odpięcie wszystkiego zapisujemy jako znacznik, żeby odróżnić je
    od stanu początkowego."""
    try:
        with polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT ekran_id FROM ekrany_uzycie WHERE przypiety=1 ORDER BY kolejnosc, ekran_id")
            wybrane = [r[0] for r in c.fetchall()]
        if wybrane:
            return wybrane
        return [] if pobierz_ustawienie("skroty_wyczyszczone", "0") == "1" else list(DOMYSLNE_PRZYPIETE)
    except Exception:
        return list(DOMYSLNE_PRZYPIETE)


def liczniki_nawigacji(auto_id):
    """Odznaki przy pozycjach nawigacji — POLICZONE RAZ, jednym wejściem do bazy.
    Szuflada, kafelki sekcji i pasek zakładek pokazują te same liczby, więc
    liczenie ich osobno w każdym miejscu byłoby trzema zapytaniami o to samo.

    Zwraca słownik {ekran_id: liczba}; brak klucza = brak odznaki."""
    wynik = {}
    if not auto_id:
        return wynik
    try:
        with polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM do_zrobienia WHERE auto_id=? AND wykonane=0", (auto_id,))
            n = (c.fetchone() or [0])[0]
            if n:
                wynik["do-zrobienia"] = n

            # Magazyn sygnalizuje NISKI STAN, a nie liczbę pozycji — odznaka ma
            # znaczyć „zajmij się tym”, nie „tyle tu leży”.
            c.execute(
                "SELECT COUNT(*) FROM magazyn_czesci WHERE auto_id=? AND ilosc <= COALESCE(prog_ostrzezenia, 1)",
                (auto_id,)
            )
            n = (c.fetchone() or [0])[0]
            if n:
                wynik["magazyn"] = n
    except Exception:
        pass

    try:
        # Terminy pojazdu (OC, przegląd, ...) — odznaka na Karcie pojazdu liczy
        # tylko te po terminie albo tuż przed nim, więc spokojne auto jej nie ma.
        pilne = 0
        for termin in (terminy_pojazdu(auto_id) or []):
            if termin.get("status") in ("po_terminie", "blisko"):
                pilne += 1
        if pilne:
            wynik["pojazd"] = pilne
    except Exception:
        pass

    try:
        n = liczba_w_koszu()
        if n:
            wynik["kosz"] = n
    except Exception:
        pass

    return wynik


def ustaw_przypiete_ekrany(identyfikatory):
    """Nadpisuje CAŁĄ listę skrótów naraz — tak działa edytor skrótów, w którym
    użytkownik zaznacza wszystko za jednym razem i dopiero potem zatwierdza."""
    wybrane = [str(e) for e in (identyfikatory or [])][:MAKS_PRZYPIETYCH]
    try:
        with polacz_baze() as conn:
            conn.execute("UPDATE ekrany_uzycie SET przypiety=0, kolejnosc=0")
            for poz, eid in enumerate(wybrane):
                conn.execute(
                    "INSERT INTO ekrany_uzycie (ekran_id, przypiety, kolejnosc) VALUES (?, 1, ?) "
                    "ON CONFLICT(ekran_id) DO UPDATE SET przypiety=1, kolejnosc=excluded.kolejnosc",
                    (eid, poz)
                )
        zapisz_ustawienie("skroty_wyczyszczone", "0" if wybrane else "1")
        return True
    except Exception:
        return False


def przywroc_domyslne_skroty():
    try:
        with polacz_baze() as conn:
            conn.execute("UPDATE ekrany_uzycie SET przypiety=0, kolejnosc=0")
            for poz, eid in enumerate(DOMYSLNE_PRZYPIETE):
                conn.execute(
                    "INSERT INTO ekrany_uzycie (ekran_id, przypiety, kolejnosc) VALUES (?, 1, ?) "
                    "ON CONFLICT(ekran_id) DO UPDATE SET przypiety=1, kolejnosc=excluded.kolejnosc",
                    (eid, poz)
                )
        zapisz_ustawienie("skroty_wyczyszczone", "0")
        return True
    except Exception:
        return False


def pobierz_ostatni_pojazd():
    try:
        return int(pobierz_ustawienie("ostatni_pojazd", "") or 0) or None
    except (TypeError, ValueError):
        return None


def zainicjuj_domyslne_auto(state):
    """Ustala, na którym aucie stoi aplikacja.

    Auto SPRZEDANE nadal da się tu podstawić — archiwum otwiera jego historię
    przez zwykłe przełączenie state.auto_id i bez tego wyjątku wracalibyśmy
    natychmiast na pierwsze auto z garażu. Sprzedany pojazd nie zostanie za to
    NIGDY wybrany automatycznie: ani jako zapamiętany, ani jako awaryjny."""
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT id, nazwa, COALESCE(status, 'aktywny') FROM samochody ORDER BY nazwa")
        wszystkie = c.fetchall()

    aktualne_id = state.auto_id
    for a_id, a_nazwa, _status in wszystkie:
        if a_id == aktualne_id:
            state.auto_nazwa = str(a_nazwa)
            return

    auta = [(a_id, a_nazwa) for a_id, a_nazwa, status in wszystkie if status != "sprzedany"]
    if not auta:
        state.auto_id = None
        state.auto_nazwa = "Brak pojazdów"
        return

    # Brak dopasowania to albo świeży start aplikacji, albo zniknięcie
    # dotychczasowego auta. W pierwszym przypadku wracamy tam, gdzie użytkownik
    # skończył ostatnim razem — pierwsze auto alfabetycznie zostaje dopiero
    # awaryjnym wyborem, gdy zapamiętanego pojazdu już nie ma.
    ostatni = pobierz_ostatni_pojazd()
    if ostatni:
        for a_id, a_nazwa in auta:
            if a_id == ostatni:
                state.auto_id = a_id
                state.auto_nazwa = str(a_nazwa)
                return
    state.auto_id = auta[0][0]
    state.auto_nazwa = str(auta[0][1])


__all__ = [
    "DOMYSLNE_PRZYPIETE",
    "LICZBA_ZAKLADEK_GLOWNYCH",
    "MAKS_PRZYPIETYCH",
    "_sparsuj_datetime",
    "liczniki_nawigacji",
    "pobierz_ostatni_pojazd",
    "pobierz_ostatnia_aktywnosc",
    "pobierz_ostatnia_zakladke",
    "pobierz_ostatnie_ekrany",
    "pobierz_podzakladke_kosztow",
    "pobierz_przypiete_ekrany",
    "przywroc_domyslne_skroty",
    "ustaw_przypiete_ekrany",
    "zainicjuj_domyslne_auto",
    "zanotuj_uzycie_ekranu",
    "zapamietaj_ostatnia_pozycje",
    "zapamietaj_podzakladke_kosztow",
]
