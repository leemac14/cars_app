"""Checklisty — listy kontrolne odhaczane przed wyjazdem."""

from datetime import datetime
from typing import Any

from .stale import CHECKLISTA_PRZEDWYJAZDOWA
from .polaczenie import polacz_baze
from .synchronizacja import zarejestruj_nagrobek


# ============================================================================
#  CHECKLISTY
# ============================================================================
# Czym się różnią od listy „Do zrobienia”: pozycja z Do zrobienia znika po
# wykonaniu (zamienia się we wpis serwisowy albo w wizytę), a checklista jest
# WIELOKROTNEGO UŻYTKU — te same dziesięć punktów odhacza się przed każdą
# dłuższą trasą i zeruje po powrocie. Trzymanie tego w do_zrobienia wymagałoby
# co wyjazd przepisywania dziesięciu pozycji od nowa, a lista rzeczy do
# załatwienia zamieniłaby się w rytuał.
#
# Stąd osobne tabele: `checklisty` (nagłówek) + `checklisty_pozycje` (punkty ze
# stanem odhaczenia i kolejnością). Odhaczenie żyje w pozycji, bo to stan
# BIEŻĄCEGO przejścia listy, a nie historia — historii przejść świadomie nie
# zapisujemy, wystarczy `ostatnie_uzycie` w nagłówku.


def pobierz_checklisty(auto_id) -> list[dict[str, Any]]:
    """Wszystkie checklisty pojazdu razem z pozycjami — jednym zapytaniem na
    tabelę, bez N+1. Zwraca listę słowników gotowych do wyświetlenia."""
    if not auto_id:
        return []
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, nazwa, opis, ostatnie_uzycie FROM checklisty WHERE auto_id=? ORDER BY id",
            (auto_id,)
        )
        naglowki = c.fetchall()
        if not naglowki:
            return []
        c.execute(
            "SELECT p.id, p.checklista_id, p.tresc, p.odhaczone, p.kolejnosc "
            "FROM checklisty_pozycje p JOIN checklisty l ON p.checklista_id = l.id "
            "WHERE l.auto_id=? ORDER BY p.kolejnosc, p.id",
            (auto_id,)
        )
        pozycje = c.fetchall()

    wg_listy = {}
    for p_id, lista_id, tresc, odhaczone, kolejnosc in pozycje:
        wg_listy.setdefault(lista_id, []).append({
            "id": p_id, "tresc": str(tresc or ""), "odhaczone": bool(odhaczone),
            "kolejnosc": int(kolejnosc or 0),
        })

    wynik = []
    for l_id, nazwa, opis, ostatnie in naglowki:
        moje = wg_listy.get(l_id, [])
        zrobione = sum(1 for p in moje if p["odhaczone"])
        wynik.append({
            "id": l_id, "nazwa": str(nazwa or ""), "opis": str(opis or ""),
            "ostatnie_uzycie": ostatnie, "pozycje": moje,
            "razem": len(moje), "zrobione": zrobione,
            "procent": (zrobione / len(moje) * 100) if moje else 0.0,
        })
    return wynik


def pobierz_checkliste(checklista_id):
    """Pojedyncza checklista — do formularza edycji."""
    if not checklista_id:
        return None
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT id, auto_id, nazwa, opis, ostatnie_uzycie FROM checklisty WHERE id=?", (checklista_id,))
        w = c.fetchone()
        if not w:
            return None
        c.execute(
            "SELECT id, tresc, odhaczone, kolejnosc FROM checklisty_pozycje "
            "WHERE checklista_id=? ORDER BY kolejnosc, id",
            (checklista_id,)
        )
        pozycje = [
            {"id": p[0], "tresc": str(p[1] or ""), "odhaczone": bool(p[2]), "kolejnosc": int(p[3] or 0)}
            for p in c.fetchall()
        ]
    return {
        "id": w[0], "auto_id": w[1], "nazwa": str(w[2] or ""), "opis": str(w[3] or ""),
        "ostatnie_uzycie": w[4], "pozycje": pozycje,
        "razem": len(pozycje), "zrobione": sum(1 for p in pozycje if p["odhaczone"]),
    }


def _oczysc_pozycje(pozycje):
    """Puste linijki i duplikaty odpadają — inaczej wklejenie listy z notatnika
    zostawiałoby w checkliście puste kwadraciki do odhaczenia."""
    wynik, widziane = [], set()
    for p in pozycje or []:
        tekst = " ".join(str(p or "").split())
        if not tekst or tekst.lower() in widziane:
            continue
        widziane.add(tekst.lower())
        wynik.append(tekst)
    return wynik


def dodaj_checkliste(auto_id, nazwa, pozycje, opis=None):
    nazwa = " ".join(str(nazwa or "").split())
    pozycje = _oczysc_pozycje(pozycje)
    if not auto_id or not nazwa:
        return None
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO checklisty (auto_id, nazwa, opis) VALUES (?,?,?)",
            (auto_id, nazwa, (opis or "").strip() or None)
        )
        lista_id = c.lastrowid
        for i, tresc in enumerate(pozycje):
            c.execute(
                "INSERT INTO checklisty_pozycje (checklista_id, tresc, kolejnosc, odhaczone) VALUES (?,?,?,0)",
                (lista_id, tresc, i)
            )
    return lista_id


def aktualizuj_checkliste(checklista_id, nazwa, pozycje, opis=None):
    """Zapis edycji. Pozycje dopasowujemy PO TREŚCI, a nie kasujemy i tworzymy
    od nowa: dzięki temu poprawienie nazwy listy albo dopisanie jednego punktu
    nie kasuje ptaszków postawionych przy pozostałych."""
    nazwa = " ".join(str(nazwa or "").split())
    pozycje = _oczysc_pozycje(pozycje)
    if not checklista_id or not nazwa:
        return
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE checklisty SET nazwa=?, opis=? WHERE id=?",
            (nazwa, (opis or "").strip() or None, checklista_id)
        )
        c.execute("SELECT id, tresc FROM checklisty_pozycje WHERE checklista_id=?", (checklista_id,))
        istniejace = {str(t or "").lower(): p_id for p_id, t in c.fetchall()}

        zostaja = []
        for i, tresc in enumerate(pozycje):
            p_id = istniejace.pop(tresc.lower(), None)
            if p_id:
                c.execute("UPDATE checklisty_pozycje SET tresc=?, kolejnosc=? WHERE id=?", (tresc, i, p_id))
                zostaja.append(p_id)
            else:
                c.execute(
                    "INSERT INTO checklisty_pozycje (checklista_id, tresc, kolejnosc, odhaczone) VALUES (?,?,?,0)",
                    (checklista_id, tresc, i)
                )
        for p_id in istniejace.values():
            c.execute("DELETE FROM checklisty_pozycje WHERE id=?", (p_id,))


def usun_checkliste(checklista_id):
    """Kasuje listę razem z pozycjami (CASCADE). Nagrobki rejestrujemy PO
    zamknięciu transakcji — zarejestruj_nagrobek otwiera własne połączenie."""
    if not checklista_id:
        return
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT zdalne_id FROM checklisty WHERE id=?", (checklista_id,))
        w = c.fetchone()
        zdalne_naglowka = w[0] if w else None
        c.execute("SELECT zdalne_id FROM checklisty_pozycje WHERE checklista_id=? AND zdalne_id IS NOT NULL", (checklista_id,))
        zdalne_pozycji = [r[0] for r in c.fetchall()]
        conn.execute("DELETE FROM checklisty WHERE id=?", (checklista_id,))
    if zdalne_naglowka:
        zarejestruj_nagrobek("checklisty", zdalne_naglowka)
    for z in zdalne_pozycji:
        zarejestruj_nagrobek("checklisty_pozycje", z)


def przelacz_pozycje_checklisty(pozycja_id, stan):
    """Odhaczenie pojedynczego punktu. Ostatni postawiony ptaszek zapisuje datę
    w nagłówku — z niej bierze się „ostatnio: 12.09” na karcie listy."""
    if not pozycja_id:
        return
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("UPDATE checklisty_pozycje SET odhaczone=? WHERE id=?", (1 if stan else 0, pozycja_id))
        if not stan:
            return
        c.execute("SELECT checklista_id FROM checklisty_pozycje WHERE id=?", (pozycja_id,))
        w = c.fetchone()
        if not w:
            return
        lista_id = w[0]
        c.execute("SELECT COUNT(*) FROM checklisty_pozycje WHERE checklista_id=? AND odhaczone=0", (lista_id,))
        if c.fetchone()[0] == 0:
            c.execute(
                "UPDATE checklisty SET ostatnie_uzycie=? WHERE id=?",
                (datetime.now().strftime("%d.%m.%Y"), lista_id)
            )


def wyzeruj_checkliste(checklista_id):
    """Zdejmuje wszystkie ptaszki — lista czeka na kolejny wyjazd."""
    if not checklista_id:
        return
    with polacz_baze() as conn:
        conn.execute("UPDATE checklisty_pozycje SET odhaczone=0 WHERE checklista_id=?", (checklista_id,))


def odhacz_cala_checkliste(checklista_id):
    """Skrót „wszystko sprawdzone” — przydaje się, kiedy lista jest odhaczana
    po fakcie, a nie punkt po punkcie przy aucie."""
    if not checklista_id:
        return
    with polacz_baze() as conn:
        conn.execute("UPDATE checklisty_pozycje SET odhaczone=1 WHERE checklista_id=?", (checklista_id,))
        conn.execute(
            "UPDATE checklisty SET ostatnie_uzycie=? WHERE id=?",
            (datetime.now().strftime("%d.%m.%Y"), checklista_id)
        )


def utworz_domyslna_checkliste(auto_id):
    """Zakłada gotową listę przedwyjazdową. Wołane z pustego ekranu — nie ma
    sensu kazać komuś przepisywać dziesięciu oczywistych punktów ręcznie."""
    nazwa, pozycje = CHECKLISTA_PRZEDWYJAZDOWA
    return dodaj_checkliste(auto_id, nazwa, pozycje)


def podsumowanie_checklist(auto_id):
    """Jedna checklista do pokazania na kokpicie: najpierw ta ROZPOCZĘTA
    (przynajmniej jeden ptaszek, ale jeszcze nie komplet) — to ona woła o
    dokończenie. Jeśli żadnej nie zaczęto, pokazujemy pierwszą z listy."""
    listy = [l for l in pobierz_checklisty(auto_id) if l["razem"] > 0]
    if not listy:
        return None
    rozpoczete = [l for l in listy if 0 < l["zrobione"] < l["razem"]]
    wybrana = min(rozpoczete, key=lambda l: l["razem"] - l["zrobione"]) if rozpoczete else listy[0]
    return {
        "id": wybrana["id"], "nazwa": wybrana["nazwa"],
        "zrobione": wybrana["zrobione"], "razem": wybrana["razem"],
        "procent": wybrana["procent"], "ostatnie_uzycie": wybrana["ostatnie_uzycie"],
        "liczba_list": len(listy),
        "gotowa": wybrana["zrobione"] == wybrana["razem"],
    }


__all__ = [
    "_oczysc_pozycje",
    "aktualizuj_checkliste",
    "dodaj_checkliste",
    "odhacz_cala_checkliste",
    "pobierz_checkliste",
    "pobierz_checklisty",
    "podsumowanie_checklist",
    "przelacz_pozycje_checklisty",
    "usun_checkliste",
    "utworz_domyslna_checkliste",
    "wyzeruj_checkliste",
]
