"""Warsztaty, wydatki cykliczne i własne pakiety serwisowe."""

from date import parsuj_date
from datetime import datetime, timedelta

from .polaczenie import polacz_baze
from .ustawienia import pobierz_moje_imie
from .synchronizacja import zarejestruj_nagrobek
from .nazwy import klucz_nazwy, normalizuj_nazwe


# ==================== WARSZTATY ====================

def pobierz_warsztaty(auto_id):
    if not auto_id:
        return []
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT id, nazwa, telefon, adres, notatki FROM warsztaty WHERE auto_id=? ORDER BY nazwa", (auto_id,))
        return c.fetchall()


def dodaj_warsztat(auto_id, nazwa, telefon=None, adres=None, notatki=None):
    """Dodaje warsztat per pojazd. Jeśli warsztat o tej samej nazwie (po
    normalizacji: bez wielkości liter, emoji i nadmiarowych spacji) już istnieje,
    zwraca jego id zamiast tworzyć duplikat — analogicznie do dodaj_tag()."""
    nazwa = normalizuj_nazwe(nazwa)
    if not nazwa:
        return None
    klucz = klucz_nazwy(nazwa)
    with polacz_baze() as conn:
        c = conn.cursor()
        # Porównanie po klucz_nazwy zamiast LOWER(nazwa): łapie też spację na
        # końcu i podwójną w środku, na których stare porównanie się wykładało.
        c.execute("SELECT id, nazwa FROM warsztaty WHERE auto_id=?", (auto_id,))
        for w_id, istniejaca in c.fetchall():
            if klucz_nazwy(istniejaca) == klucz:
                return w_id
        c.execute(
            "INSERT INTO warsztaty (auto_id, nazwa, telefon, adres, notatki) VALUES (?,?,?,?,?)",
            (auto_id, nazwa, telefon or None, adres or None, notatki or None)
        )
        return c.lastrowid


# ==================== WYDATKI CYKLICZNE ====================

def pobierz_wydatki_cykliczne(auto_id):
    if not auto_id:
        return []
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, nazwa, kwota, okres_dni, nastepna_data, czy_koszt FROM wydatki_cykliczne WHERE auto_id=?",
            (auto_id,)
        )
        wpisy = c.fetchall()
    wpisy.sort(key=lambda w: parsuj_date(w[4]))
    return wpisy


def dodaj_wydatek_cykliczny(auto_id, nazwa, kwota, okres_dni, nastepna_data, czy_koszt=1):
    with polacz_baze() as conn:
        conn.execute(
            "INSERT INTO wydatki_cykliczne (auto_id, nazwa, kwota, okres_dni, nastepna_data, czy_koszt) VALUES (?,?,?,?,?,?)",
            (auto_id, nazwa, kwota, okres_dni, nastepna_data, int(bool(czy_koszt)))
        )


def edytuj_wydatek_cykliczny(wydatek_id, nazwa, kwota, okres_dni, nastepna_data, czy_koszt=1):
    with polacz_baze() as conn:
        conn.execute(
            "UPDATE wydatki_cykliczne SET nazwa=?, kwota=?, okres_dni=?, nastepna_data=?, czy_koszt=? WHERE id=?",
            (nazwa, kwota, okres_dni, nastepna_data, int(bool(czy_koszt)), wydatek_id)
        )


def usun_wydatek_cykliczny(wydatek_id):
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT zdalne_id FROM wydatki_cykliczne WHERE id=?", (wydatek_id,))
        w = c.fetchone()
        conn.execute("DELETE FROM wydatki_cykliczne WHERE id=?", (wydatek_id,))
    if w and w[0]:
        zarejestruj_nagrobek("wydatki_cykliczne", w[0])


def oznacz_zaplacony_wydatek_cykliczny(wydatek_id, auto_id):
    """Dla klasycznego wydatku (czy_koszt=1) tworzy wpis w inne_koszty na podstawie
    wydatku cyklicznego, tak jak dotychczas. Dla samego przypomnienia bez kosztu
    (czy_koszt=0, np. "co miesiąc sprawdź ciśnienie w oponach") NIE dopisuje nic
    do inne_koszty — tylko odnotowuje wykonanie. W obu przypadkach przesuwa
    następny termin o okres_dni od DZISIAJ (nie od starej daty — dzięki temu
    spóźniona pozycja nie generuje serii zaległych powiadomień pod rząd)."""
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT nazwa, kwota, okres_dni, czy_koszt FROM wydatki_cykliczne WHERE id=?", (wydatek_id,))
        w = c.fetchone()
        if not w:
            return
        nazwa, kwota, okres_dni, czy_koszt = w
        dzis = datetime.now()
        if czy_koszt:
            conn.execute(
                "INSERT INTO inne_koszty (auto_id, data, kategoria, nazwa, kwota, dodane_przez) VALUES (?,?,?,?,?,?)",
                (auto_id, dzis.strftime("%d.%m.%Y"), "Cykliczne", nazwa, kwota, pobierz_moje_imie())
            )
        nowa_data = (dzis + timedelta(days=int(okres_dni or 30))).strftime("%d.%m.%Y")
        conn.execute("UPDATE wydatki_cykliczne SET nastepna_data=? WHERE id=?", (nowa_data, wydatek_id))


# ==================== WŁASNE PAKIETY SERWISOWE ====================

def pobierz_pakiety_wlasne(auto_id):
    """Zwraca listę (id, nazwa, [lista_pozycji]) własnych pakietów użytkownika
    dla danego pojazdu, obok wbudowanych PAKIETY_SERWISOWE."""
    if not auto_id:
        return []
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT id, nazwa, pozycje FROM pakiety_serwisowe_wlasne WHERE auto_id=? ORDER BY nazwa", (auto_id,))
        return [
            (p_id, nazwa, [p.strip() for p in (pozycje or "").split(",") if p.strip()])
            for p_id, nazwa, pozycje in c.fetchall()
        ]


def dodaj_pakiet_wlasny(auto_id, nazwa, pozycje_lista):
    with polacz_baze() as conn:
        conn.execute(
            "INSERT INTO pakiety_serwisowe_wlasne (auto_id, nazwa, pozycje) VALUES (?,?,?)",
            (auto_id, nazwa, ",".join(pozycje_lista))
        )


def aktualizuj_pakiet_wlasny(pakiet_id, nazwa, pozycje_lista):
    """Zmiana nazwy i/lub składu istniejącego własnego pakietu. Nie ruszamy
    zdalny_hash — sync sam wykryje różnicę treści i wypchnie edycję."""
    with polacz_baze() as conn:
        conn.execute(
            "UPDATE pakiety_serwisowe_wlasne SET nazwa=?, pozycje=? WHERE id=?",
            (nazwa, ",".join(pozycje_lista), pakiet_id)
        )


def usun_pakiet_wlasny(pakiet_id):
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT zdalne_id FROM pakiety_serwisowe_wlasne WHERE id=?", (pakiet_id,))
        w = c.fetchone()
        zdalne = w[0] if w else None
        conn.execute("DELETE FROM pakiety_serwisowe_wlasne WHERE id=?", (pakiet_id,))
    # Nagrobek POZA blokiem with — otwiera własne połączenie do tego samego pliku.
    if zdalne:
        zarejestruj_nagrobek("pakiety_serwisowe_wlasne", zdalne)


__all__ = [
    "aktualizuj_pakiet_wlasny",
    "dodaj_pakiet_wlasny",
    "dodaj_warsztat",
    "dodaj_wydatek_cykliczny",
    "edytuj_wydatek_cykliczny",
    "oznacz_zaplacony_wydatek_cykliczny",
    "pobierz_pakiety_wlasne",
    "pobierz_warsztaty",
    "pobierz_wydatki_cykliczne",
    "usun_pakiet_wlasny",
    "usun_wydatek_cykliczny",
]
