"""Słownik tagów kosztów."""

from .polaczenie import polacz_baze
from .synchronizacja import zarejestruj_nagrobek
from .nazwy import klucz_nazwy, normalizuj_nazwe


def pobierz_tagi(auto_id) -> list[tuple[int, str, str]]:
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT id, nazwa, kolor FROM tagi WHERE auto_id=?", (auto_id,))
        return c.fetchall()


def dodaj_tag(auto_id, nazwa, kolor):
    """Dopasowanie po klucz_nazwy, nie po LOWER(nazwa) — dzięki temu „Filtr oleju”,
    „filtr Oleju” i „filtr  oleju ” trafiają w ten sam tag, a nie zakładają trzech."""
    nazwa = normalizuj_nazwe(nazwa)
    if not nazwa:
        return None
    klucz = klucz_nazwy(nazwa)
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT id, nazwa FROM tagi WHERE auto_id=?", (auto_id,))
        for tag_id, istniejaca in c.fetchall():
            if klucz_nazwy(istniejaca) == klucz:
                return tag_id
        c.execute("INSERT INTO tagi (auto_id, nazwa, kolor) VALUES (?, ?, ?)", (auto_id, nazwa, kolor))
        return c.lastrowid


def usun_tag_ze_slownika(auto_id, tag_id, nazwa):
    """Usuwa tag z bazy i wymazuje jego nazwę z rekordów tekstowych we wszystkich tabelach."""
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT zdalne_id FROM tagi WHERE id=?", (tag_id,))
        w = c.fetchone()
        conn.execute("DELETE FROM tagi WHERE id=?", (tag_id,))

        for tabela in ["tankowania", "wizyty", "inne_koszty"]:
            c = conn.cursor()
            c.execute(f"SELECT id, tagi FROM {tabela} WHERE auto_id=? AND tagi LIKE ?", (auto_id, f'%{nazwa}%'))
            for r_id, tagi_str in c.fetchall():
                if not tagi_str: continue
                tagi_lista = [t.strip() for t in tagi_str.split(",") if t.strip()]
                if nazwa in tagi_lista:
                    tagi_lista.remove(nazwa)
                    nowe_tagi = ",".join(tagi_lista)
                    conn.execute(f"UPDATE {tabela} SET tagi=? WHERE id=?", (nowe_tagi, r_id))

    if w and w[0]:
        zarejestruj_nagrobek("tagi", w[0])


def edytuj_tag_w_slowniku(auto_id, tag_id, stara_nazwa, nowa_nazwa, nowy_kolor):
    """Aktualizuje nazwę/kolor taga i kaskadowo podmienia ją w tekstowych wpisach rekordu."""
    with polacz_baze() as conn:
        conn.execute("UPDATE tagi SET nazwa=?, kolor=? WHERE id=?", (nowa_nazwa, nowy_kolor, tag_id))
        
        if stara_nazwa != nowa_nazwa:
            for tabela in ["tankowania", "wizyty", "inne_koszty"]:
                c = conn.cursor()
                c.execute(f"SELECT id, tagi FROM {tabela} WHERE auto_id=? AND tagi LIKE ?", (auto_id, f'%{stara_nazwa}%'))
                for r_id, tagi_str in c.fetchall():
                    if not tagi_str: continue
                    tagi_lista = [t.strip() for t in tagi_str.split(",") if t.strip()]
                    if stara_nazwa in tagi_lista:
                        idx = tagi_lista.index(stara_nazwa)
                        tagi_lista[idx] = nowa_nazwa
                        nowe_tagi = ",".join(tagi_lista)
                        conn.execute(f"UPDATE {tabela} SET tagi=? WHERE id=?", (nowe_tagi, r_id))


__all__ = [
    "dodaj_tag",
    "edytuj_tag_w_slowniku",
    "pobierz_tagi",
    "usun_tag_ze_slownika",
]
