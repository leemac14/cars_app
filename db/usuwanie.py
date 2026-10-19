"""Usuwanie z możliwością cofnięcia (wpisy, podzespoły, części) — przez kosz wpisów
(db/kosz_wpisow.py); wynik dla utils.pokaz_komunikat_cofnij."""

from .stale import OSIE_MONTAZU
from .polaczenie import polacz_baze
from .ceny_czesci import zachowaj_zakup_pozycji
from .kosz_wpisow import POZA_KOSZEM_WPISOW, usun_do_kosza


def aktualizuj_wiele_zdjec_karoserii(ids_list, strefa=None, typ_porownania=None, opis=None):
    """Masowa edycja wspólnych pól (strefa / typ / opis) zaznaczonych zdjęć karoserii.
    None = bez zmian; pusty opis trzeba podać jako pusty napis."""
    if not ids_list:
        return 0

    przypisania, wartosci = [], []
    if strefa is not None:
        przypisania.append("strefa=?")
        wartosci.append(strefa)
    if typ_porownania is not None:
        przypisania.append("typ_porownania=?")
        wartosci.append(typ_porownania)
    if opis is not None:
        przypisania.append("opis=?")
        wartosci.append(opis)

    if not przypisania:
        return 0

    placeholders = ",".join("?" for _ in ids_list)
    with polacz_baze() as conn:
        conn.execute(
            f"UPDATE zdjecia_karoserii SET {', '.join(przypisania)} WHERE id IN ({placeholders})",
            tuple(wartosci) + tuple(ids_list)
        )
    return len(ids_list)


def oznacz_zamontowany_zestaw(auto_id, zestaw_id, os_montazu="Wszystkie"):
    """Montuje zestaw opon na osi. 'Wszystkie' wyklucza pozostałe; zestaw na jednej osi
    koliduje tylko z tą samą osią albo 'Wszystkie' (asymetryczne komplety przód/tył)."""
    if os_montazu not in OSIE_MONTAZU:
        os_montazu = "Wszystkie"

    with polacz_baze() as conn:
        if os_montazu == "Wszystkie":
            conn.execute("UPDATE zestawy_opon SET zamontowane=0, os_montazu='Wszystkie' WHERE auto_id=?", (auto_id,))
        else:
            conn.execute(
                "UPDATE zestawy_opon SET zamontowane=0 WHERE auto_id=? AND (os_montazu=? OR os_montazu='Wszystkie')",
                (auto_id, os_montazu)
            )
        conn.execute("UPDATE zestawy_opon SET zamontowane=1, os_montazu=? WHERE id=?", (os_montazu, zestaw_id))


def usun_z_cofnieciem(tabela, rekord_id):
    """Usuwa rekord z kaskadą do kosza wpisów i zwraca {"cofnij", "finalizuj", "dane"}: cofnij()
    przywraca z kosza (id 1:1, gdy wolne), finalizuj() nic nie kasuje. Tabele z
    POZA_KOSZEM_WPISOW — tylko „Cofnij” (pliki w folderze odroczonych do finalizuj())."""
    return usun_do_kosza(tabela, [rekord_id], do_kosza=tabela not in POZA_KOSZEM_WPISOW)


def usun_wiele_z_cofnieciem(tabela, ids_list):
    """Grupowe usuwanie jako JEDNA pozycja kosza; cudze wpisy (rola współautora) zostają,
    ich liczba w "pominiete"."""
    return usun_do_kosza(tabela, ids_list, do_kosza=tabela not in POZA_KOSZEM_WPISOW)


def przelacz_wykonane_do_zrobienia(pozycja_id, status):
    with polacz_baze() as conn:
        conn.execute("UPDATE do_zrobienia SET wykonane=? WHERE id=?", (1 if status else 0, pozycja_id))


def usun_zadanie_z_cofnieciem(zadanie_id):
    """Usuwa podzespół z całą historią, plikami i częściami (wracają na półkę) do kosza."""
    return usun_do_kosza("zadania", [zadanie_id])


def usun_wiele_zadan_z_cofnieciem(ids_list):
    return usun_do_kosza("zadania", ids_list)


def _zachowaj_zakupy(conn, wiersze):
    # Historia cen przeżywa pozycję: jej ostatni zakup zostaje w dzienniku (db/ceny_czesci.py),
    # a przywrócona pozycja znowu przykrywa ten sam zakup — bez drugiego punktu na krzywej.
    for dane in wiersze:
        zachowaj_zakup_pozycji(conn, dane.get("auto_id"), dane)


def usun_czesc_magazynu_z_cofnieciem(czesc_id):
    """Usuwa pozycję magazynu z jej zużyciem w wizytach i wpisach (dolewka zostaje bez
    odwołania) do kosza; magazyn to wspólny inwentarz — współautora nie ogranicza."""
    return usun_do_kosza("magazyn_czesci", [czesc_id], przed_usunieciem=_zachowaj_zakupy)


def usun_wiele_czesci_magazynu_z_cofnieciem(ids_list):
    return usun_do_kosza("magazyn_czesci", ids_list, przed_usunieciem=_zachowaj_zakupy)


__all__ = [
    "aktualizuj_wiele_zdjec_karoserii",
    "oznacz_zamontowany_zestaw",
    "przelacz_wykonane_do_zrobienia",
    "usun_czesc_magazynu_z_cofnieciem",
    "usun_wiele_czesci_magazynu_z_cofnieciem",
    "usun_wiele_z_cofnieciem",
    "usun_wiele_zadan_z_cofnieciem",
    "usun_z_cofnieciem",
    "usun_zadanie_z_cofnieciem",
]
