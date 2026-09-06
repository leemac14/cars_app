"""Paliwo i prąd: typy, etykiety, przeliczanie zużycia, pojazdy dwuźródłowe."""

from .stale import ENERGIA_PALIWO, ENERGIA_PRAD, RODZAJE_ENERGII, TYPY_PALIWA_DWUZRODLOWE, TYPY_PALIWA_ELEKTRYCZNE
from .polaczenie import polacz_baze
from .pomocnicze import formatuj_liczba_eksport
from .ustawienia import pobierz_jednostke_spalania, pobierz_jednostke_zuzycia_ev


def przelicz_zuzycie(wartosc_na_100km, elektryczny=False):
    """(wartość w jednostce wybranej w Ustawieniach, nazwa jednostki). Wejściem
    ZAWSZE jest zużycie na 100 km — dokładnie to, co liczy reszta aplikacji.
    Jedno miejsce na to przeliczenie, bo korzysta z niego i interfejs
    (utils.formatuj_spalanie), i teksty obserwacji budowane tutaj, w db.
    Uwaga na kierunek: przy km/l i mpg WIĘKSZA liczba znaczy MNIEJSZE zużycie,
    więc żaden tekst nie może wnioskować o trendzie z samej tej wartości."""
    jednostka = pobierz_jednostke_zuzycia_ev() if elektryczny else pobierz_jednostke_spalania()
    try:
        val = float(wartosc_na_100km)
    except (TypeError, ValueError):
        return None, jednostka
    if val <= 0:
        return None, jednostka
    if jednostka in ("km/l", "km/kWh"):
        return 100.0 / val, jednostka
    if jednostka == "mpg":
        return 235.214583 / val, jednostka
    return val, jednostka


def formatuj_zuzycie_tekst(wartosc_na_100km, elektryczny=False, decimale=1):
    """Zużycie jako gotowy tekst z jednostką — wersja dla warstwy danych
    (teksty obserwacji, eksport). Interfejs używa utils.formatuj_spalanie,
    które formatuje liczbę po swojemu, ale przelicza tym samym kodem."""
    wynik, jednostka = przelicz_zuzycie(wartosc_na_100km, elektryczny)
    if wynik is None:
        return f"- {jednostka}"
    return f"{formatuj_liczba_eksport(wynik, decimale)} {jednostka}"


def czy_pojazd_elektryczny(auto_id):
    """True tylko dla auta jeżdżącego WYŁĄCZNIE na prąd. Hybryda plug-in tu NIE
    wchodzi — ona ma oba źródła i o etykietach decyduje rodzaj konkretnego wpisu
    (patrz rodzaje_energii_pojazdu / etykiety_energii)."""
    if not auto_id:
        return False
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT typ_paliwa FROM samochody WHERE id=?", (auto_id,))
        w = c.fetchone()
    return bool(w) and str(w[0] or "") in TYPY_PALIWA_ELEKTRYCZNE


def etykiety_paliwa(elektryczny=False):
    """Wszystkie etykiety i jednostki zależne od typu napędu w jednym miejscu.
    Zero zmian w schemacie bazy — kolumny 'litry' i 'stacja' zostają te same,
    zmienia się tylko to, jak je nazywamy w interfejsie."""
    if elektryczny:
        return {
            "jednostka": "kWh",
            "ilosc": "Naładowano (kWh)",
            "punkt": "Punkt ładowania",
            "punkt_opcjonalnie": "Punkt ładowania (opcjonalnie)",
            "punkt_hint": "np. Orlen Charge, GreenWay, garaż",
            "punkt_recznie": "Wpisz nazwę punktu ładowania",
            "do_pelna": "Naładowano do pełna (wymagane do zużycia)",
            "cena_jednostkowa": "Cena/kWh",
            "zuzycie": "Średnie zużycie",
            "naglowek_listy": "Historia ładowań",
            "ikona_listy": "ladowanie",
            "zdarzenie": "ładowanie",
            "suma_ilosci": "Naładowano",
            "brak_pelnych": "Wymaga 2x do pełna",
        }
    return {
        "jednostka": "L",
        "ilosc": "Zatankowano (Litry)",
        "punkt": "Stacja paliw",
        "punkt_opcjonalnie": "Stacja paliw (opcjonalnie)",
        "punkt_hint": "np. Orlen, Shell, BP",
        "punkt_recznie": "Wpisz nazwę stacji",
        "do_pelna": "Zatankowano do pełna (wymagane do spalania)",
        "cena_jednostkowa": "Cena/L",
        "zuzycie": "Średnie spalanie",
        "naglowek_listy": "Historia tankowań",
        "ikona_listy": "tankowanie",
        "zdarzenie": "tankowanie",
        "suma_ilosci": "Zatankowano",
        "brak_pelnych": "Wymaga 2x do pełna",
    }


def pobierz_typ_paliwa(auto_id):
    if not auto_id:
        return ""
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT typ_paliwa FROM samochody WHERE id=?", (auto_id,))
        w = c.fetchone()
    return str((w or [""])[0] or "")


def czy_pojazd_dwuzrodlowy(auto_id):
    """True dla hybrydy plug-in — jedynego napędu, który realnie tankuje OBA
    źródła i wymaga, żeby pojedynczy wpis powiedział, którego dotyczy."""
    return pobierz_typ_paliwa(auto_id) in TYPY_PALIWA_DWUZRODLOWE


def rodzaje_energii_pojazdu(auto_id):
    """Które źródła energii ma sens pokazywać dla tego auta.
    Elektryk → sam prąd, plug-in → oba, reszta → samo paliwo."""
    typ = pobierz_typ_paliwa(auto_id)
    if typ in TYPY_PALIWA_DWUZRODLOWE:
        return list(RODZAJE_ENERGII)
    if typ in TYPY_PALIWA_ELEKTRYCZNE:
        return [ENERGIA_PRAD]
    return [ENERGIA_PALIWO]


def domyslny_rodzaj_energii(auto_id):
    """Rodzaj podstawiany nowemu wpisowi, zanim użytkownik cokolwiek przełączy."""
    return rodzaje_energii_pojazdu(auto_id)[0]


def normalizuj_rodzaj_energii(wartosc, auto_id=None):
    """Stare wpisy (sprzed migracji 33) i dane z importu mogą nie mieć rodzaju —
    wtedy decyduje typ pojazdu."""
    tekst = str(wartosc or "").strip().lower()
    if tekst in RODZAJE_ENERGII:
        return tekst
    return domyslny_rodzaj_energii(auto_id) if auto_id else ENERGIA_PALIWO


def etykiety_energii(rodzaj):
    """Etykiety zależne od RODZAJU WPISU, a nie od typu pojazdu — przy hybrydzie
    plug-in jedno auto ma i tankowania, i ładowania, więc nazwy muszą podążać za
    konkretnym wpisem. etykiety_paliwa() zostaje jako cieńsza nakładka na to."""
    return etykiety_paliwa(rodzaj == ENERGIA_PRAD)


ETYKIETY_RODZAJU = {
    ENERGIA_PALIWO: "Paliwo",
    ENERGIA_PRAD: "Prąd",
}


__all__ = [
    "ETYKIETY_RODZAJU",
    "czy_pojazd_dwuzrodlowy",
    "czy_pojazd_elektryczny",
    "domyslny_rodzaj_energii",
    "etykiety_energii",
    "etykiety_paliwa",
    "formatuj_zuzycie_tekst",
    "normalizuj_rodzaj_energii",
    "pobierz_typ_paliwa",
    "przelicz_zuzycie",
    "rodzaje_energii_pojazdu",
]
