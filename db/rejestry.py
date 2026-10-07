"""Warsztaty, wydatki cykliczne, szablony tras, własne pakiety serwisowe
i domyślne podzespoły zależne od napędu."""

from collections import Counter
from date import na_iso, parsuj_date
from datetime import datetime, timedelta
from typing import Any

from .stale import (
    DOMYSLNE_INTERWALY_MIESIACE, DOMYSLNE_ZADANIA, KATEGORIA_INNE_DOMYSLNA,
    OKRES_ZMIANY_OPON_DNI, PAKIETY_SERWISOWE, PODZESPOLY_NAPEDU,
    TYPY_CYKLICZNE, TYP_CYKLICZNY_OPONY, TYP_CYKLICZNY_WYDATEK,
)
from .polaczenie import polacz_baze
from .ustawienia import pobierz_moje_imie
from .synchronizacja import (
    ROLA_PODGLAD, ROLA_WSPOLAUTOR, czy_moge_zmieniac_wpis, rola_pojazdu, zarejestruj_nagrobek,
)
from .magazyn import przelacz_zestaw_sezonowy
from .raty import czy_rata, zaplac_rate
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


# Formularze wizyty i wpisu serwisowego zapisują „Warsztat”, gdy nikt nie
# wybrał wykonawcy — to nie nazwa, tylko jej brak. Karta pod tą nazwą zebrałaby
# wszystkie wizyty „bez warsztatu” naraz, więc karty takiej nie ma i nie wolno
# jej nadać tej nazwy.
WARSZTAT_BEZ_NAZWY = "Warsztat"


def _wpisy_z_warsztatem(c, auto_id):
    """Wiersze wizyt i historii serwisowej pojazdu z wpisanym wykonawcą:
    (tabela, id, wykonawca, data, data_iso, wizyta_id, dodane_przez).
    Historia nie ma auto_id — jedzie przez podzespół."""
    c.execute("SELECT id, wykonawca, data, data_iso, dodane_przez FROM wizyty "
              "WHERE auto_id=? AND TRIM(COALESCE(wykonawca, '')) <> ''", (auto_id,))
    wynik = [("wizyty", r[0], r[1], r[2], r[3], None, r[4]) for r in c.fetchall()]
    c.execute("SELECT h.id, h.wykonawca, h.data, h.data_iso, h.wizyta_id, h.dodane_przez "
              "FROM historia h JOIN zadania z ON z.id = h.zadanie_id "
              "WHERE z.auto_id=? AND TRIM(COALESCE(h.wykonawca, '')) <> ''", (auto_id,))
    wynik += [("historia", r[0], r[1], r[2], r[3], r[4], r[5]) for r in c.fetchall()]
    return wynik


def pobierz_karty_warsztatow(auto_id) -> list[dict[str, Any]]:
    """Karty ekranu „Warsztaty”: rejestr pojazdu plus nazwy z wizyt i wpisów, które
    karty nie mają (`id` None). Warsztat to w bazie NAZWA (tekst), dopasowanie po
    `klucz_nazwy`. Klucze: id, nazwa, klucz, telefon, adres, notatki, wizyt (wizyty +
    wpisy poza wizytą), wizyt_zbiorczych, nazwa_na_wizytach (wartość filtra „Warsztat”),
    ostatnia (data jak w bazie). Od ostatnio odwiedzonego; bez wizyt na końcu,
    alfabetycznie."""
    if not auto_id:
        return []
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT id, nazwa, telefon, adres, notatki FROM warsztaty WHERE auto_id=?", (auto_id,))
        rejestr = c.fetchall()
        wpisy = _wpisy_z_warsztatem(c, auto_id)

    pomijany = klucz_nazwy(WARSZTAT_BEZ_NAZWY)
    statystyki = {}
    for tabela, _id, wykonawca, data, data_iso, wizyta_id, _autor in wpisy:
        klucz = klucz_nazwy(wykonawca)
        if not klucz or klucz == pomijany or (tabela == "historia" and wizyta_id):
            continue
        s = statystyki.setdefault(klucz, {"wizyt": 0, "wizyt_zbiorczych": 0, "iso": "", "data": None,
                                           "pisownie": Counter(), "pisownie_wizyt": Counter()})
        s["wizyt"] += 1
        s["pisownie"][normalizuj_nazwe(wykonawca)] += 1
        if tabela == "wizyty":
            s["wizyt_zbiorczych"] += 1
            s["pisownie_wizyt"][wykonawca] += 1
        iso = data_iso or na_iso(data) or ""
        if iso > s["iso"]:
            s["iso"], s["data"] = iso, data

    def karta(w_id, nazwa, klucz, telefon, adres, notatki, s):
        s = s or {}
        pisownie_wizyt = s.get("pisownie_wizyt")
        return {
            "id": w_id, "nazwa": nazwa, "klucz": klucz,
            "telefon": telefon or None, "adres": adres or None, "notatki": notatki or None,
            "wizyt": s.get("wizyt", 0), "wizyt_zbiorczych": s.get("wizyt_zbiorczych", 0),
            "nazwa_na_wizytach": pisownie_wizyt.most_common(1)[0][0] if pisownie_wizyt else None,
            "ostatnia": s.get("data"), "_iso": s.get("iso", ""),
        }

    karty, z_karta = [], set()
    for w_id, nazwa, telefon, adres, notatki in rejestr:
        klucz = klucz_nazwy(nazwa)
        # Dwa wpisy rejestru o jednej nazwie (z dwóch telefonów naraz) — wizyty
        # liczymy raz; drugi wpis czeka na scalenie duplikatów w Ustawieniach.
        karty.append(karta(w_id, nazwa, klucz, telefon, adres, notatki,
                           None if klucz in z_karta else statystyki.get(klucz)))
        z_karta.add(klucz)
    for klucz, s in statystyki.items():
        if klucz not in z_karta:
            karty.append(karta(None, s["pisownie"].most_common(1)[0][0], klucz, None, None, None, s))

    karty.sort(key=lambda k: k["klucz"])
    karty.sort(key=lambda k: k["_iso"], reverse=True)  # sortowanie stabilne: remis zostaje alfabetyczny
    for k in karty:
        del k["_iso"]
    return karty


def zapisz_warsztat(auto_id, warsztat_id, nazwa, telefon=None, adres=None, notatki=None) -> str | None:
    """Nowa karta (`warsztat_id` None) albo poprawka; zwraca None po zapisie albo zdanie
    odmowy (pod nazwą w formularzu). Zmiana nazwy przepisuje ją po kluczu na wizytach i
    wpisach (warsztat żyje tam jako tekst). Współautor: gdy nazwę noszą też cudze wpisy,
    odmowa w całości (chmura by ich nie przyjęła)."""
    nazwa = normalizuj_nazwe(nazwa)
    klucz = klucz_nazwy(nazwa)
    if not klucz:
        return "Podaj nazwę warsztatu"
    if klucz == klucz_nazwy(WARSZTAT_BEZ_NAZWY):
        return f"„{WARSZTAT_BEZ_NAZWY}” to wpis bez wybranego warsztatu — nadaj własną nazwę"
    if not auto_id:
        return "Najpierw wybierz pojazd"
    rola = rola_pojazdu(auto_id)
    if rola == ROLA_PODGLAD:
        return "Ten pojazd masz w trybie tylko do odczytu — możesz go oglądać, ale nie zmieniać."

    telefon = " ".join(str(telefon or "").split()) or None
    adres = " ".join(str(adres or "").split()) or None
    notatki = str(notatki or "").strip() or None

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT id, nazwa FROM warsztaty WHERE auto_id=?", (auto_id,))
        rejestr = c.fetchall()
        stara = next((n for i, n in rejestr if i == warsztat_id), None)
        if warsztat_id is not None and stara is None:
            return "Tego warsztatu już nie ma — mógł zniknąć przy synchronizacji."
        zajety = next((n for i, n in rejestr if i != warsztat_id and klucz_nazwy(n) == klucz), None)
        if zajety:
            return f"Na liście jest już „{zajety}” — dwie karty scalisz w Ustawieniach (duplikaty nazw)."
        do_przepisania = []
        if stara is not None and stara != nazwa:
            stary_klucz = klucz_nazwy(stara)
            do_przepisania = [(t, i, autor) for t, i, wyk, _d, _di, _w, autor in _wpisy_z_warsztatem(c, auto_id)
                              if klucz_nazwy(wyk) == stary_klucz and wyk != nazwa]

    if do_przepisania and rola == ROLA_WSPOLAUTOR:
        autorzy = {autor for _t, _i, autor in do_przepisania}
        if not all(czy_moge_zmieniac_wpis(auto_id, autor) for autor in autorzy):
            return ("Tę nazwę noszą też wizyty innych osób, a współautor zmienia tylko swoje "
                    "wpisy. Telefon, adres i notatkę zapiszesz bez zmiany nazwy.")

    with polacz_baze() as conn:
        c = conn.cursor()
        if warsztat_id is None:
            c.execute("INSERT INTO warsztaty (auto_id, nazwa, telefon, adres, notatki) VALUES (?,?,?,?,?)",
                      (auto_id, nazwa, telefon, adres, notatki))
            return None
        c.execute("UPDATE warsztaty SET nazwa=?, telefon=?, adres=?, notatki=? WHERE id=?",
                  (nazwa, telefon, adres, notatki, warsztat_id))
        for tabela, rekord_id, _autor in do_przepisania:
            c.execute(f"UPDATE {tabela} SET wykonawca=? WHERE id=?", (nazwa, rekord_id))
    return None


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
    # Spłacona umowa raty nie ma już terminu (db/raty.py) — stoi na końcu,
    # a nie na samej górze jako „najdawniejsza”.
    wpisy.sort(key=lambda w: (not w[4], parsuj_date(w[4])))
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
    """„Zapłacone/Wykonano” wpisu cyklicznego. czy_koszt=1 — wpis w inne_koszty;
    czy_koszt=0 — tylko odnotowanie. Termin przesuwa się o okres_dni od DZISIAJ
    (spóźniona pozycja nie robi serii zaległych). Typ 'opony' PRZESTAWIA zamontowany
    komplet (brak drugiego nie blokuje — powód w wyniku). Rata leasingu lub kredytu
    płaci KOLEJNĄ pozycję harmonogramu (db.zaplac_rate). Zwraca słownik z opisem skutków
    do komunikatu."""
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT nazwa, kwota, okres_dni, czy_koszt, typ FROM wydatki_cykliczne WHERE id=?", (wydatek_id,))
        w = c.fetchone()
        if not w:
            return None
        nazwa, kwota, okres_dni, czy_koszt, typ = w
        typ = _poprawny_typ(typ)
        if czy_rata(typ):
            # Rata leasingu i kredytu ma harmonogram: płaci się KOLEJNĄ ratę
            # z umowy (jej kwotą i w jej terminie), a po wykupie wpis się kończy,
            # zamiast przesuwać termin o okres od dzisiaj (db/raty.py).
            return zaplac_rate(conn, wydatek_id, auto_id)
        dzis = datetime.now()
        if czy_koszt:
            kategoria = "Cykliczne" if typ == TYP_CYKLICZNY_WYDATEK else KATEGORIA_INNE_DOMYSLNA
            data_wpisu = dzis.strftime("%d.%m.%Y")
            conn.execute(
                "INSERT INTO inne_koszty (auto_id, data, data_iso, kategoria, nazwa, kwota, dodane_przez) VALUES (?,?,?,?,?,?,?)",
                (auto_id, data_wpisu, na_iso(data_wpisu), kategoria, nazwa, kwota, pobierz_moje_imie())
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
    """Przesuwa przypomnienie o zmianie opon o pół roku OD DZIŚ — przy każdej faktycznej
    zmianie, także ręcznej z Magazynu."""
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
    """Zmiana opon WPROST z magazynu: przestawia komplet i przesuwa termin następnej
    zmiany. Zwraca to co przelacz_zestaw_sezonowy plus `termin_przesuniety`."""
    wynik = przelacz_zestaw_sezonowy(auto_id, docelowy_sezon)
    wynik["termin_przesuniety"] = przesun_przypomnienie_o_oponach(auto_id) if wynik.get("ok") else False
    return wynik


# ==================== SZABLONY TRAS ====================
# Szablon pamięta CECHY TRASY (dystans, powrót, ekipa, opłaty), NIE spalanie ani cenę
# paliwa — te zawsze z aktualnych danych.


def pobierz_trasy_szablony(auto_id) -> list[dict[str, Any]]:
    if not auto_id:
        return []
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, nazwa, dystans, powrot, osoby, oplaty, notatki, skad, dokad, cel, sluzbowy "
            "FROM trasy_szablony WHERE auto_id=? ORDER BY nazwa COLLATE NOCASE",
            (auto_id,)
        )
        # Skąd, dokąd, cel i rodzaj (wersja 50) robią z trasy wzór przejazdu
        # w ewidencji; w trasie zapisanej tylko w kalkulatorze są puste,
        # a `sluzbowy` None znaczy „rodzaj nieustalony”.
        return [
            {"id": r[0], "nazwa": str(r[1] or ""), "dystans": float(r[2] or 0),
             "powrot": bool(r[3]), "osoby": max(1, int(r[4] or 1)),
             "oplaty": float(r[5] or 0), "notatki": str(r[6] or ""),
             "skad": str(r[7] or ""), "dokad": str(r[8] or ""), "cel": str(r[9] or ""),
             "sluzbowy": None if r[10] is None else bool(r[10])}
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


def zapisz_szablon_przejazdu(auto_id, nazwa, skad="", dokad="", cel="", sluzbowy=None, dystans=0.0,
                             powrot=False, trasa_id=None):
    """Wzór przejazdu z formularza ewidencji — ta sama tabela co trasy kalkulatora
    (wspólne chipy). Bez `trasa_id` kluczem jest nazwa; nadpisanie zmienia tylko pola
    przejazdu (dystans, powrót, skąd, dokąd, cel, rodzaj), osoby i opłaty zostają.
    Zwraca id albo None (brak nazwy)."""
    nazwa = normalizuj_nazwe(nazwa)
    if not auto_id or not nazwa:
        return None
    pola = (nazwa, float(dystans or 0), int(bool(powrot)), normalizuj_nazwe(skad) or None,
            normalizuj_nazwe(dokad) or None, normalizuj_nazwe(cel) or None,
            None if sluzbowy is None else int(bool(sluzbowy)))
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
            c.execute("UPDATE trasy_szablony SET nazwa=?, dystans=?, powrot=?, skad=?, dokad=?, cel=?, sluzbowy=? "
                      "WHERE id=?", pola + (trasa_id,))
            return trasa_id
        c.execute("INSERT INTO trasy_szablony (auto_id, nazwa, dystans, powrot, skad, dokad, cel, sluzbowy) "
                  "VALUES (?,?,?,?,?,?,?,?)", (auto_id,) + pola)
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


# ==================== DOMYŚLNE PODZESPOŁY NAPĘDU ====================

def _czy_o_oponach(nazwa):
    """Podzespół oznaczony flagą opon wchodzi w sezonową zmianę kompletu."""
    tekst = str(nazwa or "").lower()
    return "opon" in tekst or "kół" in tekst


def domyslne_zadania(typ_paliwa) -> list[tuple[str, int | None, int]]:
    """Lista startowa podzespołów dla napędu: (nazwa, interwał w miesiącach albo None,
    dotyczy_opon), z DOMYSLNE_ZADANIA i PODZESPOLY_NAPEDU (pozycja wspólna istnieje
    RAZ). Nieznany typ paliwa → sama baza."""
    modul = PODZESPOLY_NAPEDU.get(str(typ_paliwa or "").strip(), {})
    bez = {klucz_nazwy(x) for x in modul.get("usun", ())}
    wynik, widziane = [], set()
    for nazwa in list(DOMYSLNE_ZADANIA) + list(modul.get("dodaj", ())):
        klucz = klucz_nazwy(nazwa)
        if klucz in bez or klucz in widziane:
            continue
        widziane.add(klucz)
        wynik.append((
            normalizuj_nazwe(nazwa),
            DOMYSLNE_INTERWALY_MIESIACE.get(nazwa),
            1 if _czy_o_oponach(nazwa) else 0,
        ))
    return wynik


def brakujace_podzespoly(auto_id, typ_paliwa) -> list[tuple[str, int | None, int]]:
    """Pozycje listy startowej napędu, których pojazd jeszcze NIE ma (np. LPG założony
    po zakupie); porównanie po kluczu nazwy."""
    if not auto_id:
        return []
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT nazwa FROM zadania WHERE auto_id=?", (auto_id,))
        ma = {klucz_nazwy(w[0]) for w in c.fetchall()}
    return [poz for poz in domyslne_zadania(typ_paliwa) if klucz_nazwy(poz[0]) not in ma]


def dodaj_domyslne_zadania(auto_id, pozycje) -> int:
    """Zakłada podzespoły z listy (nazwa, interwał miesięcy, dotyczy_opon), pomija
    istniejące; zwraca liczbę dopisanych. Jedno miejsce INSERT dla nowego pojazdu i
    zmiany napędu."""
    if not auto_id or not pozycje:
        return 0
    dopisane = 0
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT nazwa FROM zadania WHERE auto_id=?", (auto_id,))
        ma = {klucz_nazwy(w[0]) for w in c.fetchall()}
        for nazwa, interwal_miesiace, dotyczy_opon in pozycje:
            klucz = klucz_nazwy(nazwa)
            if klucz in ma:
                continue
            ma.add(klucz)
            c.execute(
                "INSERT INTO zadania (auto_id, nazwa, interwal_miesiace, dotyczy_opon) VALUES (?,?,?,?)",
                (auto_id, normalizuj_nazwe(nazwa), interwal_miesiace, int(dotyczy_opon or 0)),
            )
            dopisane += 1
    return dopisane


def pakiety_dla_pojazdu(auto_id) -> list[tuple[str, list[str]]]:
    """Wbudowane PAKIETY_SERWISOWE wykonalne w TYM pojeździe w całości (wszystkie
    pozycje — nazwa zestawu obiecuje skład). ŚWIADOMIE po zawartości pojazdu, nie po
    typie paliwa."""
    if not auto_id:
        return [(nazwa, list(pozycje)) for nazwa, pozycje in PAKIETY_SERWISOWE.items()]
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT nazwa FROM zadania WHERE auto_id=?", (auto_id,))
        ma = {klucz_nazwy(w[0]) for w in c.fetchall()}
    return [
        (nazwa, list(pozycje))
        for nazwa, pozycje in PAKIETY_SERWISOWE.items()
        if all(klucz_nazwy(pozycja) in ma for pozycja in pozycje)
    ]


__all__ = [
    "WARSZTAT_BEZ_NAZWY",
    "_czy_o_oponach",
    "_poprawny_typ",
    "aktualizuj_pakiet_wlasny",
    "brakujace_podzespoly",
    "dodaj_domyslne_zadania",
    "dodaj_pakiet_wlasny",
    "dodaj_przypomnienie_o_oponach",
    "dodaj_warsztat",
    "dodaj_wydatek_cykliczny",
    "domyslne_zadania",
    "edytuj_wydatek_cykliczny",
    "oznacz_zaplacony_wydatek_cykliczny",
    "pakiety_dla_pojazdu",
    "pobierz_pakiety_wlasne",
    "pobierz_karty_warsztatow",
    "pobierz_przypomnienia_o_oponach",
    "pobierz_trasy_szablony",
    "pobierz_warsztaty",
    "pobierz_wydatki_cykliczne",
    "przesun_przypomnienie_o_oponach",
    "usun_pakiet_wlasny",
    "usun_trase_szablon",
    "usun_wydatek_cykliczny",
    "wykonaj_sezonowa_zmiane_opon",
    "zapisz_szablon_przejazdu",
    "zapisz_trase_szablon",
    "zapisz_warsztat",
]
