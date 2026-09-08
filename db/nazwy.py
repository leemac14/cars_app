"""Normalizacja i scalanie duplikatów nazw (stacje, warsztaty, tagi)."""

from typing import Any

from .polaczenie import polacz_baze
from .pomocnicze import bez_emoji
from .synchronizacja import zarejestruj_nagrobek
from .przebieg import przelicz_wszystkie_zadania


# ============================================================================
#  NORMALIZACJA NAZW
# ============================================================================
# Ten sam mechanizm, co klucz_stacji dla stacji paliw, tylko zastosowany szerzej:
# „Filtr oleju”, „filtr Oleju” i „filtr oleju ” to jedna nazwa, a nie trzy
# osobne pozycje w magazynie, w tagach, wśród warsztatów i podzespołów.
# Klucz służy WYŁĄCZNIE do porównywania — w bazie zostaje pisownia użytkownika.

# Nazwy porównujemy po zdjęciu emoji: podzespoły założone starszymi wersjami
# aplikacji mają je w nazwie („🛢️ Olej silnikowy i filtr”), a te same wpisy
# dodane dziś już nie.
def klucz_nazwy(tekst):
    """Klucz porównawczy nazwy: bez emoji, bez wielkości liter, ze scalonymi
    białymi znakami i bez interpunkcji na brzegach."""
    czysty = bez_emoji(tekst)
    return " ".join(czysty.split()).lower().strip(" .,;:-_/")


def normalizuj_nazwe(tekst):
    """Pisownia gotowa do ZAPISU: scalone spacje i obcięte brzegi. Nie zmienia
    wielkości liter ani treści — użytkownik ma prawo do swojej pisowni, chodzi
    tylko o to, żeby „filtr oleju ” i „filtr  oleju” nie były różnymi wpisami."""
    return " ".join(str(tekst or "").split()).strip()


# Gdzie normalizacja obowiązuje: tabela -> (kolumna z nazwą, etykieta dla UI).
# Kolejność steruje kolejnością sekcji w narzędziu scalania duplikatów.
POLA_NAZW_DO_NORMALIZACJI = [
    ("magazyn_czesci", "nazwa", "Części i płyny w magazynie"),
    ("tagi", "nazwa", "Tagi (kategorie kosztów)"),
    ("warsztaty", "nazwa", "Warsztaty"),
    ("zadania", "nazwa", "Podzespoły"),
]


def dopasuj_istniejaca_nazwe(auto_id, tabela, nazwa):
    """Jeśli podana nazwa to tylko inny wariant zapisu czegoś, co już istnieje
    dla tego pojazdu, zwraca ISTNIEJĄCĄ pisownię — dokładnie tak, jak
    dopasuj_do_slownika robi to dla stacji paliw. W przeciwnym razie zwraca
    nazwę po samej normalizacji białych znaków."""
    kolumna = next((k for t, k, _ in POLA_NAZW_DO_NORMALIZACJI if t == tabela), None)
    czysta = normalizuj_nazwe(nazwa)
    if not czysta or not auto_id or not kolumna:
        return czysta

    klucz = klucz_nazwy(czysta)
    if not klucz:
        return czysta

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(f"SELECT {kolumna} FROM {tabela} WHERE auto_id=?", (auto_id,))
        for (istniejaca,) in c.fetchall():
            if klucz_nazwy(istniejaca) == klucz:
                return str(istniejaca)
    return czysta


def znajdz_duplikaty_nazw(auto_id) -> list[dict[str, Any]]:
    """Grupy nazw, które po normalizacji są tym samym, a w bazie siedzą jako
    osobne wiersze. Zwraca listę słowników gotowych do pokazania w Ustawieniach:
    {tabela, etykieta, klucz, kanoniczna, warianty:[(id, nazwa, ile_uzyc)]}.
    Kanoniczna to wariant użyty najczęściej — przy remisie ten o najniższym ID
    (czyli najstarszy), żeby wynik był powtarzalny."""
    if not auto_id:
        return []

    # Ile razy dana pozycja jest faktycznie używana — po tym wybieramy zwycięzcę
    # scalania i to pokazujemy użytkownikowi przy każdym wariancie.
    zapytania_uzyc = {
        "magazyn_czesci": (
            "SELECT magazyn_id, COUNT(*) FROM ("
            " SELECT magazyn_id FROM wizyta_czesci_magazynu"
            " UNION ALL SELECT magazyn_id FROM historia_czesci_magazynu"
            ") GROUP BY magazyn_id"
        ),
        "zadania": "SELECT zadanie_id, COUNT(*) FROM historia GROUP BY zadanie_id",
    }

    grupy = []
    with polacz_baze() as conn:
        c = conn.cursor()
        for tabela, kolumna, etykieta in POLA_NAZW_DO_NORMALIZACJI:
            uzycia = {}
            if tabela in zapytania_uzyc:
                c.execute(zapytania_uzyc[tabela])
                uzycia = {r[0]: int(r[1] or 0) for r in c.fetchall()}

            c.execute(f"SELECT id, {kolumna} FROM {tabela} WHERE auto_id=? ORDER BY id", (auto_id,))
            wiersze = c.fetchall()

            wg_klucza = {}
            for wiersz_id, nazwa in wiersze:
                klucz = klucz_nazwy(nazwa)
                if not klucz:
                    continue
                wg_klucza.setdefault(klucz, []).append(
                    (wiersz_id, str(nazwa or ""), uzycia.get(wiersz_id, 0))
                )

            for klucz, warianty in wg_klucza.items():
                if len(warianty) < 2:
                    continue
                kanoniczny = max(warianty, key=lambda w: (w[2], -w[0]))
                grupy.append({
                    "tabela": tabela,
                    "kolumna": kolumna,
                    "etykieta": etykieta,
                    "klucz": klucz,
                    "kanoniczna": kanoniczny,
                    "warianty": sorted(warianty, key=lambda w: (-w[2], w[0])),
                })
    return grupy


# Dokąd przepisać powiązania przy scalaniu: tabela nazw -> [(tabela, kolumna)].
PRZEPIECIA_PRZY_SCALANIU = {
    "magazyn_czesci": [("wizyta_czesci_magazynu", "magazyn_id"), ("historia_czesci_magazynu", "magazyn_id")],
    "zadania": [("historia", "zadanie_id"), ("do_zrobienia", "zadanie_id")],
    "warsztaty": [],
    "tagi": [],
}


def scal_duplikaty_nazw(auto_id, tabela, id_docelowy, ids_zrodlowe):
    """Zlewa warianty w jeden wpis: przepina powiązania na wpis docelowy,
    a same duplikaty kasuje. Zwraca liczbę scalonych pozycji.

    Magazyn ma dodatkowo stan ilościowy — sztuki z duplikatów DOLICZAMY do
    pozycji docelowej, bo fizycznie leżą w tym samym pudełku, tylko były
    zapisane pod dwiema pisowniami. Tagi i warsztaty żyją w polach tekstowych
    innych tabel, więc tam podmieniamy nazwę zamiast ID."""
    ids_zrodlowe = [i for i in (ids_zrodlowe or []) if i and i != id_docelowy]
    if not auto_id or not tabela or not id_docelowy or not ids_zrodlowe:
        return 0

    kolumna = next((k for t, k, _ in POLA_NAZW_DO_NORMALIZACJI if t == tabela), None)
    if not kolumna:
        return 0

    placeholders = ",".join("?" for _ in ids_zrodlowe)
    zdalne_do_nagrobka = []

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(f"SELECT {kolumna} FROM {tabela} WHERE id=?", (id_docelowy,))
        w = c.fetchone()
        if not w:
            return 0
        nazwa_docelowa = str(w[0] or "")

        c.execute(f"SELECT id, {kolumna}, zdalne_id FROM {tabela} WHERE id IN ({placeholders})", tuple(ids_zrodlowe))
        znikajace = c.fetchall()
        zdalne_do_nagrobka = [r[2] for r in znikajace if r[2]]

        if tabela == "magazyn_czesci":
            c.execute(
                f"SELECT COALESCE(SUM(ilosc), 0) FROM magazyn_czesci WHERE id IN ({placeholders})",
                tuple(ids_zrodlowe)
            )
            suma = float((c.fetchone() or [0])[0] or 0)
            if suma:
                c.execute("UPDATE magazyn_czesci SET ilosc = ilosc + ? WHERE id=?", (suma, id_docelowy))

        for tab_powiazana, kol_powiazana in PRZEPIECIA_PRZY_SCALANIU.get(tabela, []):
            c.execute(
                f"UPDATE {tab_powiazana} SET {kol_powiazana}=? WHERE {kol_powiazana} IN ({placeholders})",
                (id_docelowy, *ids_zrodlowe)
            )

        # Tagi i warsztaty są w innych tabelach zapisane NAZWĄ, nie kluczem obcym.
        if tabela == "tagi":
            for _, stara_nazwa, _ in znikajace:
                _podmien_tag_w_tekstach(c, auto_id, stara_nazwa, nazwa_docelowa)
        elif tabela == "warsztaty":
            for _, stara_nazwa, _ in znikajace:
                for tab in ("wizyty", "historia"):
                    if tab == "historia":
                        c.execute(
                            "UPDATE historia SET wykonawca=? WHERE wykonawca=? AND zadanie_id IN "
                            "(SELECT id FROM zadania WHERE auto_id=?)",
                            (nazwa_docelowa, stara_nazwa, auto_id)
                        )
                    else:
                        c.execute(
                            "UPDATE wizyty SET wykonawca=? WHERE wykonawca=? AND auto_id=?",
                            (nazwa_docelowa, stara_nazwa, auto_id)
                        )

        c.execute(f"DELETE FROM {tabela} WHERE id IN ({placeholders})", tuple(ids_zrodlowe))

    for zid in zdalne_do_nagrobka:
        zarejestruj_nagrobek(tabela, zid)

    if tabela == "zadania":
        przelicz_wszystkie_zadania(auto_id)

    return len(ids_zrodlowe)


def _podmien_tag_w_tekstach(c, auto_id, stara_nazwa, nowa_nazwa):
    """Tagi trzymane są jako lista rozdzielona przecinkami w kolumnie 'tagi'.
    Podmieniamy element listy, nie fragment tekstu — inaczej tag „UB” zjadłby
    kawałek nazwy „UBEZPIECZENIE”."""
    for tabela in ("tankowania", "wizyty", "inne_koszty"):
        c.execute(f"SELECT id, tagi FROM {tabela} WHERE auto_id=? AND tagi IS NOT NULL AND tagi <> ''", (auto_id,))
        for wiersz_id, tekst in c.fetchall():
            elementy = [t.strip() for t in str(tekst or "").split(",") if t.strip()]
            zmienione, widziane = [], set()
            for element in elementy:
                docelowy = nowa_nazwa if element == stara_nazwa else element
                if docelowy not in widziane:
                    widziane.add(docelowy)
                    zmienione.append(docelowy)
            nowy_tekst = ", ".join(zmienione)
            if nowy_tekst != tekst:
                c.execute(f"UPDATE {tabela} SET tagi=? WHERE id=?", (nowy_tekst, wiersz_id))


__all__ = [
    "POLA_NAZW_DO_NORMALIZACJI",
    "PRZEPIECIA_PRZY_SCALANIU",
    "_podmien_tag_w_tekstach",
    "dopasuj_istniejaca_nazwe",
    "klucz_nazwy",
    "normalizuj_nazwe",
    "scal_duplikaty_nazw",
    "znajdz_duplikaty_nazw",
]
