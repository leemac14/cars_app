"""Warsztaty, wydatki cykliczne, szablony tras i własne pakiety serwisowe."""

from date import parsuj_date
from datetime import datetime, timedelta
from typing import Any

from .stale import (
    KATEGORIA_INNE_DOMYSLNA, OKRES_ZMIANY_OPON_DNI,
    TYPY_CYKLICZNE, TYP_CYKLICZNY_OPONY, TYP_CYKLICZNY_WYDATEK,
)
from .polaczenie import polacz_baze
from .ustawienia import pobierz_moje_imie
from .synchronizacja import zarejestruj_nagrobek
from .magazyn import przelacz_zestaw_sezonowy
from .nazwy import klucz_nazwy, normalizuj_nazwe


# ==================== WARSZTATY ====================

def pobierz_warsztaty(auto_id) -> list[tuple[int, str, str | None, str | None, str | None]]:
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

def _poprawny_typ(typ):
    """Nieznana wartość (stary wpis, rekord z chmury z nowszej wersji) ma
    zachowywać się jak zwykły wydatek, a nie wysadzać panelu."""
    typ = str(typ or "").strip() or TYP_CYKLICZNY_WYDATEK
    return typ if typ in TYPY_CYKLICZNE else TYP_CYKLICZNY_WYDATEK


def pobierz_wydatki_cykliczne(auto_id) -> list[tuple[int, str, float, int, str, int, str]]:
    """Krotki (id, nazwa, kwota, okres_dni, nastepna_data, czy_koszt, typ).
    `typ` doklejony NA KOŃCU celowo — rozpakowania w istniejącym kodzie, które
    biorą sześć pierwszych pól, dalej działają."""
    if not auto_id:
        return []
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, nazwa, kwota, okres_dni, nastepna_data, czy_koszt, typ FROM wydatki_cykliczne WHERE auto_id=?",
            (auto_id,)
        )
        wpisy = [(w[0], w[1], w[2], w[3], w[4], w[5], _poprawny_typ(w[6])) for w in c.fetchall()]
    wpisy.sort(key=lambda w: parsuj_date(w[4]))
    return wpisy


def dodaj_wydatek_cykliczny(auto_id, nazwa, kwota, okres_dni, nastepna_data, czy_koszt=1, typ=TYP_CYKLICZNY_WYDATEK):
    with polacz_baze() as conn:
        conn.execute(
            "INSERT INTO wydatki_cykliczne (auto_id, nazwa, kwota, okres_dni, nastepna_data, czy_koszt, typ) VALUES (?,?,?,?,?,?,?)",
            (auto_id, nazwa, kwota, okres_dni, nastepna_data, int(bool(czy_koszt)), _poprawny_typ(typ))
        )


def edytuj_wydatek_cykliczny(wydatek_id, nazwa, kwota, okres_dni, nastepna_data, czy_koszt=1, typ=TYP_CYKLICZNY_WYDATEK):
    with polacz_baze() as conn:
        conn.execute(
            "UPDATE wydatki_cykliczne SET nazwa=?, kwota=?, okres_dni=?, nastepna_data=?, czy_koszt=?, typ=? WHERE id=?",
            (nazwa, kwota, okres_dni, nastepna_data, int(bool(czy_koszt)), _poprawny_typ(typ), wydatek_id)
        )


def dodaj_przypomnienie_o_oponach(auto_id, nastepna_data=None, nazwa="Sezonowa zmiana opon", kwota=0.0):
    """Skrót zakładający wpis typu 'opony' z sensownym okresem — z pustego stanu
    panelu i z ekranu magazynu opon."""
    data = nastepna_data or (datetime.now() + timedelta(days=OKRES_ZMIANY_OPON_DNI)).strftime("%d.%m.%Y")
    dodaj_wydatek_cykliczny(
        auto_id, nazwa, float(kwota or 0.0), OKRES_ZMIANY_OPON_DNI, data,
        czy_koszt=1 if float(kwota or 0.0) > 0 else 0, typ=TYP_CYKLICZNY_OPONY,
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
    spóźniona pozycja nie generuje serii zaległych powiadomień pod rząd).

    Wpis typu 'opony' dodatkowo PRZESTAWIA ZAMONTOWANY KOMPLET w magazynie opon.
    To cały sens tego typu: potwierdzenie „zrobione” ma zostawić bazę w stanie
    zgodnym z rzeczywistością, a nie kazać poprawiać drugiego ekranu ręcznie.
    Brak drugiego kompletu nie blokuje odhaczenia — termin i tak się przesuwa,
    a wołający dostaje w wyniku powód, żeby móc o tym powiedzieć.

    Zwraca słownik opisujący, co się stało (typ wpisu, czy powstał koszt, wynik
    zmiany opon) — interfejs buduje z tego komunikat."""
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT nazwa, kwota, okres_dni, czy_koszt, typ FROM wydatki_cykliczne WHERE id=?", (wydatek_id,))
        w = c.fetchone()
        if not w:
            return None
        nazwa, kwota, okres_dni, czy_koszt, typ = w
        typ = _poprawny_typ(typ)
        dzis = datetime.now()
        if czy_koszt:
            kategoria = "Cykliczne" if typ == TYP_CYKLICZNY_WYDATEK else KATEGORIA_INNE_DOMYSLNA
            conn.execute(
                "INSERT INTO inne_koszty (auto_id, data, kategoria, nazwa, kwota, dodane_przez) VALUES (?,?,?,?,?,?)",
                (auto_id, dzis.strftime("%d.%m.%Y"), kategoria, nazwa, kwota, pobierz_moje_imie())
            )
        nowa_data = (dzis + timedelta(days=int(okres_dni or 30))).strftime("%d.%m.%Y")
        conn.execute("UPDATE wydatki_cykliczne SET nastepna_data=? WHERE id=?", (nowa_data, wydatek_id))

    # Zmiana opon POZA transakcją powyżej — przelacz_zestaw_sezonowy otwiera
    # własne połączenie do tego samego pliku (jak zarejestruj_nagrobek).
    opony = przelacz_zestaw_sezonowy(auto_id) if typ == TYP_CYKLICZNY_OPONY else None
    return {
        "typ": typ, "nazwa": str(nazwa or ""), "czy_koszt": bool(czy_koszt),
        "nastepna_data": nowa_data, "opony": opony,
    }


def pobierz_przypomnienia_o_oponach(auto_id) -> list[tuple[int, str, float, int, str, int, str]]:
    """Wpisy cykliczne typu 'opony' danego pojazdu (zwykle zero albo jeden)."""
    return [w for w in pobierz_wydatki_cykliczne(auto_id) if w[6] == TYP_CYKLICZNY_OPONY]


def przesun_przypomnienie_o_oponach(auto_id, utworz_gdy_brak=False):
    """Przesuwa termin przypomnienia o zmianie opon o pół roku OD DZIŚ.

    Woła się to zawsze wtedy, kiedy opony faktycznie zostały zmienione — także
    ręcznie, z ekranu Magazynu. Bez tego przypomnienie dalej dobijało się o
    czynność, która została już wykonana, a użytkownik musiał je odklikiwać
    drugi raz w panelu wydatków cyklicznych."""
    wpisy = pobierz_przypomnienia_o_oponach(auto_id)
    if not wpisy:
        if utworz_gdy_brak:
            dodaj_przypomnienie_o_oponach(auto_id)
            return True
        return False
    nowa_data = (datetime.now() + timedelta(days=OKRES_ZMIANY_OPON_DNI)).strftime("%d.%m.%Y")
    with polacz_baze() as conn:
        for w in wpisy:
            conn.execute("UPDATE wydatki_cykliczne SET nastepna_data=? WHERE id=?", (nowa_data, w[0]))
    return True


def wykonaj_sezonowa_zmiane_opon(auto_id, docelowy_sezon=None):
    """Zmiana opon uruchomiona WPROST z magazynu, a nie z listy przypomnień.

    Robi obie rzeczy naraz: przestawia zamontowany komplet i przesuwa termin
    następnej zmiany. Wcześniej te dwie połowy tej samej czynności leżały
    w dwóch różnych miejscach aplikacji i trzeba było pamiętać o obu.

    Zwraca to samo, co przelacz_zestaw_sezonowy, plus `termin_przesuniety`."""
    wynik = przelacz_zestaw_sezonowy(auto_id, docelowy_sezon)
    wynik["termin_przesuniety"] = przesun_przypomnienie_o_oponach(auto_id) if wynik.get("ok") else False
    return wynik


# ==================== SZABLONY TRAS ====================
# Kalkulator podróży liczył za każdym razem od zera, choć trasy powtarzają się
# co do kilometra: „do teściów”, „do pracy i z powrotem”, „nad morze”. Szablon
# zapamiętuje to, co jest CECHĄ TRASY (dystans, powrót, ekipa, opłaty), a NIE
# zapamiętuje spalania ani ceny paliwa — te mają się brać z aktualnych danych
# pojazdu, inaczej zapisana trasa z zeszłego roku liczyłaby po starych cenach.


def pobierz_trasy_szablony(auto_id) -> list[dict[str, Any]]:
    if not auto_id:
        return []
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, nazwa, dystans, powrot, osoby, oplaty, notatki "
            "FROM trasy_szablony WHERE auto_id=? ORDER BY nazwa COLLATE NOCASE",
            (auto_id,)
        )
        return [
            {"id": r[0], "nazwa": str(r[1] or ""), "dystans": float(r[2] or 0),
             "powrot": bool(r[3]), "osoby": max(1, int(r[4] or 1)),
             "oplaty": float(r[5] or 0), "notatki": str(r[6] or "")}
            for r in c.fetchall()
        ]


def zapisz_trase_szablon(auto_id, nazwa, dystans, powrot=False, osoby=1, oplaty=0.0, notatki=None, trasa_id=None):
    """Zapis nowej trasy albo nadpisanie istniejącej. Bez `trasa_id` nazwa jest
    kluczem: druga „Do teściów” nadpisuje pierwszą zamiast tworzyć bliźniaka —
    porównanie po klucz_nazwy, więc „do teściów ” też trafi w istniejącą."""
    nazwa = normalizuj_nazwe(nazwa)
    if not auto_id or not nazwa:
        return None
    dane = (nazwa, float(dystans or 0), int(bool(powrot)), max(1, int(osoby or 1)),
            float(oplaty or 0), (notatki or "").strip() or None)
    with polacz_baze() as conn:
        c = conn.cursor()
        if trasa_id is None:
            klucz = klucz_nazwy(nazwa)
            c.execute("SELECT id, nazwa FROM trasy_szablony WHERE auto_id=?", (auto_id,))
            for t_id, istniejaca in c.fetchall():
                if klucz_nazwy(istniejaca) == klucz:
                    trasa_id = t_id
                    break
        if trasa_id is not None:
            c.execute(
                "UPDATE trasy_szablony SET nazwa=?, dystans=?, powrot=?, osoby=?, oplaty=?, notatki=? WHERE id=?",
                dane + (trasa_id,)
            )
            return trasa_id
        c.execute(
            "INSERT INTO trasy_szablony (auto_id, nazwa, dystans, powrot, osoby, oplaty, notatki) VALUES (?,?,?,?,?,?,?)",
            (auto_id,) + dane
        )
        return c.lastrowid


def usun_trase_szablon(trasa_id):
    if not trasa_id:
        return
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT zdalne_id FROM trasy_szablony WHERE id=?", (trasa_id,))
        w = c.fetchone()
        zdalne = w[0] if w else None
        conn.execute("DELETE FROM trasy_szablony WHERE id=?", (trasa_id,))
    if zdalne:
        zarejestruj_nagrobek("trasy_szablony", zdalne)


# ==================== WŁASNE PAKIETY SERWISOWE ====================

def pobierz_pakiety_wlasne(auto_id) -> list[tuple[int, str, list[str]]]:
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
    "_poprawny_typ",
    "aktualizuj_pakiet_wlasny",
    "dodaj_pakiet_wlasny",
    "dodaj_przypomnienie_o_oponach",
    "dodaj_warsztat",
    "dodaj_wydatek_cykliczny",
    "edytuj_wydatek_cykliczny",
    "oznacz_zaplacony_wydatek_cykliczny",
    "pobierz_pakiety_wlasne",
    "pobierz_przypomnienia_o_oponach",
    "pobierz_trasy_szablony",
    "pobierz_warsztaty",
    "pobierz_wydatki_cykliczne",
    "przesun_przypomnienie_o_oponach",
    "usun_pakiet_wlasny",
    "usun_trase_szablon",
    "usun_wydatek_cykliczny",
    "wykonaj_sezonowa_zmiane_opon",
    "zapisz_trase_szablon",
]
