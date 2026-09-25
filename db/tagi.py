"""Słownik tagów kosztów."""

from .polaczenie import polacz_baze
from .synchronizacja import zarejestruj_nagrobek
from .nazwy import klucz_nazwy, normalizuj_nazwe, przepisz_tag_we_wpisach


# Kolejność, w jakiej nowe tagi dostają kolory: najpierw barwy najłatwiejsze do
# odróżnienia na liście, szary na samym końcu — szary chip wygląda jak „bez
# koloru”. Ta sama paleta co kolor pojazdu (KOLORY_MOTYWU), tylko inny porządek.
KOLEJNOSC_KOLOROW_TAGOW = [
    "Niebieski", "Zielony", "Pomarańczowy", "Fioletowy", "Czerwony",
    "Indygo", "Różowy", "Limonkowy", "Żółty", "Szary",
]


def pobierz_tagi(auto_id) -> list[tuple[int, str, str]]:
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT id, nazwa, kolor FROM tagi WHERE auto_id=?", (auto_id,))
        return c.fetchall()


def mapa_kolorow_tagow(auto_id) -> dict[str, str]:
    """{klucz_nazwy(tag): kolor} — do kolorowania tagów na listach wpisów.

    Klucz, a nie sama nazwa, bo wpis trzyma tagi jako TEKST, a ten bywa
    zapisany inaczej niż w słowniku: przy „myjnia” wpisanym do istniejącego
    „MYJNIA” dodaj_tag nie zakłada drugiego tagu, ale wpis dostaje pisownię
    z klawiatury. Szukany po nazwie taki tag wypadał ze słownika i udawał
    domyślny niebieski. Do wyszukania koloru: `kolor_tagu(mapa, nazwa)`."""
    return {klucz_nazwy(nazwa): kolor for _, nazwa, kolor in pobierz_tagi(auto_id)}


def kolor_tagu(mapa, nazwa) -> str | None:
    """Kolor tagu z `mapa_kolorow_tagow` albo None, gdy tagu nie ma w słowniku
    (np. przyszedł z importu CSV)."""
    return mapa.get(klucz_nazwy(nazwa))


def pierwszy_wolny_kolor_tagu(auto_id) -> str:
    """Kolor dla nowego tagu: pierwszy z KOLEJNOSC_KOLOROW_TAGOW, którego nie ma
    jeszcze żaden tag pojazdu. Wcześniej każdy nowy tag startował jako
    „Niebieski” i zwykle tak zostawał — stąd lista wpisów, na której wszystkie
    tagi wyglądały tak samo. Gdy paleta się skończy, kolory idą od nowa po kolei."""
    tagi = pobierz_tagi(auto_id)
    zajete = {kolor for _, _, kolor in tagi}
    for kolor in KOLEJNOSC_KOLOROW_TAGOW:
        if kolor not in zajete:
            return kolor
    return KOLEJNOSC_KOLOROW_TAGOW[len(tagi) % len(KOLEJNOSC_KOLOROW_TAGOW)]


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
        przepisz_tag_we_wpisach(c, auto_id, nazwa)

    if w and w[0]:
        zarejestruj_nagrobek("tagi", w[0])


def edytuj_tag_w_slowniku(auto_id, tag_id, stara_nazwa, nowa_nazwa, nowy_kolor):
    """Aktualizuje nazwę/kolor taga i kaskadowo podmienia ją w tekstowych
    wpisach. Zwraca False (i niczego nie zmienia), gdy nowa nazwa to tylko
    inna pisownia INNEGO tagu tego pojazdu — dwa tagi o jednym kluczu nie
    dałyby się odróżnić ani w filtrze, ani przy kolorowaniu. Do połączenia
    dwóch tagów służy narzędzie scalania duplikatów."""
    nowa_nazwa = normalizuj_nazwe(nowa_nazwa)
    if not nowa_nazwa:
        return False
    klucz = klucz_nazwy(nowa_nazwa)
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT id, nazwa FROM tagi WHERE auto_id=? AND id<>?", (auto_id, tag_id))
        if any(klucz_nazwy(n) == klucz for _, n in c.fetchall()):
            return False
        conn.execute("UPDATE tagi SET nazwa=?, kolor=? WHERE id=?", (nowa_nazwa, nowy_kolor, tag_id))
        if stara_nazwa != nowa_nazwa:
            przepisz_tag_we_wpisach(c, auto_id, stara_nazwa, nowa_nazwa)
    return True


__all__ = [
    "KOLEJNOSC_KOLOROW_TAGOW",
    "dodaj_tag",
    "edytuj_tag_w_slowniku",
    "kolor_tagu",
    "mapa_kolorow_tagow",
    "pierwszy_wolny_kolor_tagu",
    "pobierz_tagi",
    "usun_tag_ze_slownika",
]
