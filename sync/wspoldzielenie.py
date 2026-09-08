"""Włączenie i wyłączenie współdzielenia: kody, dołączanie, odłączanie.

Moduł jest NAJWYŻEJ w pakiecie, choć intuicja podpowiada odwrotnie. Powód jest
jeden: `utworz_udostepniony_pojazd` i `dolacz_po_kodzie` kończą pełnym
przebiegiem synchronizacji, więc muszą znać `przebieg`. Odwrócenie tej
zależności wymagałoby importu w środku funkcji — a założenie pakietu jest
takie, że zależności idą w jedną stronę i widać je w nagłówku pliku.

Czytane od góry układa się to zresztą sensownie: najpierw jest przebieg
synchronizacji, a dopiero potem operacja, która ten przebieg zamawia.
"""

import db
import log

from .stale import KONFIGURACJA_SYNC, TABELE_POSREDNIE
from .polaczenie import _upewnij_sesje
from .role import _nowy_kod, czy_udostepniony
from .przebieg import synchronizuj_wszystko


def utworz_udostepniony_pojazd(auto_id, nazwa):
    klient, uid = _upewnij_sesje()
    kod = _nowy_kod()

    wynik = klient.rpc("utworz_udostepniony_pojazd", {"p_nazwa": nazwa, "p_kod": kod}).execute()
    nowy_id = wynik.data 

    with db.polacz_baze() as conn:
        conn.execute(
            "UPDATE samochody SET wspolny_pojazd_id=?, kod_zaproszenia=?, rola_wspoldzielenia=? WHERE id=?",
            (nowy_id, kod, db.ROLA_WLASCICIEL, auto_id)
        )

    # Kody ról zakładamy od razu, ale ich brak nie może wywrócić udostępniania —
    # gdy w Supabase nie ma jeszcze tabeli kodów, pojazd i tak jest udostępniony
    # kodem pełnym, dokładnie jak przed wprowadzeniem ról.
    try:
        utworz_kody_rol(auto_id)
    except Exception:
        log.polkniety("zakładanie kodów ról przy udostępnianiu pojazdu")

    synchronizuj_wszystko(auto_id)
    return kod


def utworz_kody_rol(auto_id, odswiez=False):
    """Zakłada (albo odtwarza) dwa dodatkowe kody zaproszenia: dla współautora
    i dla podglądu. Kody są LOSOWE, a nie wyprowadzone z kodu pełnego —
    gdyby były jego wariantem („P-A1B2C3”), gość z podglądu odgadłby kod pełny
    w dwie sekundy i cała rola byłaby dekoracją.

    Wymaga funkcji `zarejestruj_kod_dostepu` po stronie Supabase (plik
    supabase/role_wspoldzielenia.sql). Bez niej rzuca wyjątkiem, a ekran
    Współdzielenia pokazuje, co trzeba dograć — kod pełny działa niezależnie.

    Zwraca {"wspolautor": kod, "podglad": kod}."""
    wspolny_id, kod_pelny = czy_udostepniony(auto_id)
    if not wspolny_id:
        raise ValueError("Ten pojazd nie jest współdzielony.")

    istniejace = db.kody_dostepu(auto_id)
    kody = {
        db.ROLA_WSPOLAUTOR: None if odswiez else istniejace.get("wspolautor"),
        db.ROLA_PODGLAD: None if odswiez else istniejace.get("podglad"),
    }
    if all(kody.values()):
        return {"wspolautor": kody[db.ROLA_WSPOLAUTOR], "podglad": kody[db.ROLA_PODGLAD]}

    klient, uid = _upewnij_sesje()
    for rola in (db.ROLA_WSPOLAUTOR, db.ROLA_PODGLAD):
        if kody[rola]:
            continue
        kod = _nowy_kod()
        klient.rpc("zarejestruj_kod_dostepu", {
            "p_pojazd_id": wspolny_id,
            "p_kod": kod,
            "p_kod_bazowy": kod_pelny,
            "p_rola": rola,
        }).execute()
        kody[rola] = kod

    db.zapisz_kody_dostepu(auto_id, kody[db.ROLA_WSPOLAUTOR], kody[db.ROLA_PODGLAD])
    return {"wspolautor": kody[db.ROLA_WSPOLAUTOR], "podglad": kody[db.ROLA_PODGLAD]}


def uniewaznij_kody_rol(auto_id):
    """Wycofuje dotychczasowe kody ról i wystawia nowe — do użycia, gdy kod
    wyciekł albo ktoś ma przestać mieć dostęp. Uczestnicy, którzy już dołączyli,
    zostają: kod służy do wejścia, nie do trzymania dostępu."""
    wspolny_id, _ = czy_udostepniony(auto_id)
    if not wspolny_id:
        raise ValueError("Ten pojazd nie jest współdzielony.")
    klient, uid = _upewnij_sesje()
    stare = db.kody_dostepu(auto_id)
    for kod in (stare.get("wspolautor"), stare.get("podglad")):
        if kod:
            try:
                klient.rpc("wycofaj_kod_dostepu", {"p_kod": kod}).execute()
            except Exception:
                log.polkniety("wycofanie kodu dostępu w Supabase")
    with db.polacz_baze() as conn:
        conn.execute("UPDATE samochody SET kod_wspolautora=NULL, kod_podgladu=NULL WHERE id=?", (auto_id,))
    return utworz_kody_rol(auto_id, odswiez=True)


def _unikalna_nazwa_pojazdu(cur, nazwa_bazowa):
    """Zwraca nazwę pojazdu różną (bez rozróżniania wielkości liter) od już
    istniejących w tabeli samochody. Używane WYŁĄCZNIE przy dołączaniu do
    współdzielonego pojazdu kodem (patrz dolacz_po_kodzie) — przy kolizji
    nazwy zawsze dopisujemy odróżnik, zamiast kiedykolwiek próbować
    "dopasować się" pod istniejący, prywatny wiersz."""
    cur.execute("SELECT LOWER(nazwa) FROM samochody")
    zajete = {r[0] for r in cur.fetchall()}
    if nazwa_bazowa.lower() not in zajete:
        return nazwa_bazowa
    kandydat = f"{nazwa_bazowa} (współdzielony)"
    if kandydat.lower() not in zajete:
        return kandydat
    i = 2
    while f"{kandydat} {i}".lower() in zajete:
        i += 1
    return f"{kandydat} {i}"


def _dolacz_z_rola(klient, kod):
    """Zamienia wpisany kod na (pojazd_id, nazwa, rola).

    Najpierw pyta o kod ROLOWY (`dolacz_do_pojazdu_z_rola` — funkcja z pliku
    supabase/role_wspoldzielenia.sql). Gdy jej nie ma albo kod nie jest kodem
    roli, wraca do dotychczasowego `dolacz_do_pojazdu`, który zna wyłącznie kod
    pełny. Dzięki temu aplikacja po aktualizacji działa tak samo, zanim SQL
    zostanie wgrany — tylko role są wtedy niedostępne."""
    try:
        wynik = klient.rpc("dolacz_do_pojazdu_z_rola", {"p_kod": kod}).execute()
        if wynik.data:
            w = wynik.data[0]
            rola = (w.get("rola") or db.ROLA_PELNA).strip()
            return w["pojazd_id"], w["nazwa"], (rola if rola in db.ETYKIETY_ROL else db.ROLA_PELNA)
    except Exception:
        # Brak funkcji na serwerze albo to nie jest kod roli — próbujemy dalej.
        log.polkniety("dołączanie do pojazdu kodem roli")

    wynik = klient.rpc("dolacz_do_pojazdu", {"p_kod": kod}).execute()
    if not wynik.data:
        raise ValueError("Nieprawidłowy kod zaproszenia.")
    return wynik.data[0]["pojazd_id"], wynik.data[0]["nazwa"], db.ROLA_PELNA


def dolacz_po_kodzie(kod):
    klient, uid = _upewnij_sesje()
    kod = kod.strip().upper()
    wspolny_id, nazwa_zdalna, rola = _dolacz_z_rola(klient, kod)

    with db.polacz_baze() as conn:
        cur = conn.cursor()

        # WAŻNE — bezpieczeństwo danych: NIGDY nie dopasowujemy po nazwie do
        # istniejącego lokalnego pojazdu. Dwa różne auta o tej samej, popularnej
        # nazwie (np. dwie "Škoda Octavia" różnych osób) mogłyby się przez to
        # przypadkiem zlać w jeden wiersz — a zaraz potem synchronizuj_wszystko()
        # poniżej wypchnęłoby CAŁĄ dotychczasową, prywatną historię lokalnego
        # auta (tankowania, serwis, koszty...) do CUDZEGO współdzielonego
        # pojazdu. Dołączenie po kodzie zawsze tworzy NOWY wiersz; przy kolizji
        # nazwy dopisujemy odróżnik.
        cur.execute("SELECT COUNT(*) FROM samochody WHERE LOWER(nazwa)=LOWER(?)", (nazwa_zdalna,))
        kolizja_nazwy = cur.fetchone()[0] > 0
        nazwa = _unikalna_nazwa_pojazdu(cur, nazwa_zdalna) if kolizja_nazwy else nazwa_zdalna

        # Kod zaproszenia zapisujemy TYLKO przy pełnym dostępie. Kod roli nie
        # jest kodem pojazdu — gdyby wylądował w tej kolumnie, gość z podglądu
        # zobaczyłby go u siebie jako „kod do rozdawania” i rozesłał dalej
        # zaproszenie, którego nie ma prawa wystawiać.
        cur.execute(
            "INSERT INTO samochody (nazwa, wspolny_pojazd_id, kod_zaproszenia, rola_wspoldzielenia) VALUES (?,?,?,?)",
            (nazwa, wspolny_id, kod if rola in db.ROLE_Z_PELNYM_DOSTEPEM else None, rola)
        )
        nowy_auto_id = cur.lastrowid

    synchronizuj_wszystko(nowy_auto_id)
    return nowy_auto_id, nazwa, kolizja_nazwy, rola


def odlacz_wspoldzielenie(auto_id):
    with db.polacz_baze() as conn:
        # Razem ze współdzieleniem znikają rola i kody — pojazd wraca do stanu
        # w pełni offline, w którym „wszystko wolno”, a nie do trybu podglądu
        # bez chmury, w którym nie dałoby się już nic dopisać.
        conn.execute(
            "UPDATE samochody SET wspolny_pojazd_id=NULL, kod_zaproszenia=NULL, "
            "info_zdalne_id=NULL, zdalny_hash_info=NULL, znacznik_delty=NULL, "
            "kod_wspolautora=NULL, kod_podgladu=NULL, rola_wspoldzielenia=? WHERE id=?",
            (db.ROLA_WLASCICIEL, auto_id)
        )
        for konfig in KONFIGURACJA_SYNC:
            tabela = konfig["tabela"]
            opis_posredni = TABELE_POSREDNIE.get(tabela)
            warunek = opis_posredni["reset_where"] if opis_posredni else "auto_id=?"
            conn.execute(
                f"UPDATE {tabela} SET zdalne_id=NULL, zdalny_hash=NULL WHERE {warunek}",
                (auto_id,)
            )


__all__ = [
    "_dolacz_z_rola",
    "_unikalna_nazwa_pojazdu",
    "dolacz_po_kodzie",
    "odlacz_wspoldzielenie",
    "uniewaznij_kody_rol",
    "utworz_kody_rol",
    "utworz_udostepniony_pojazd",
]
