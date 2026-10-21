"""Słownik tagów kosztów i wydatki według tagów (U-16)."""

from datetime import date, datetime
from typing import Any

from .polaczenie import polacz_baze
from .daty import warunek_zakresu_dat
from .synchronizacja import zarejestruj_nagrobek
from .nazwy import TABELE_Z_TAGAMI, klucz_nazwy, normalizuj_nazwe, przepisz_tag_we_wpisach


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
    """{klucz_nazwy(tag): kolor} do kolorowania tagów na listach. Klucz, bo wpis trzyma
    tag jako TEKST i bywa w innej pisowni niż słownik. Kolor wyszukuje `kolor_tagu(mapa,
    nazwa)`."""
    return {klucz_nazwy(nazwa): kolor for _, nazwa, kolor in pobierz_tagi(auto_id)}


def kolor_tagu(mapa, nazwa) -> str | None:
    """Kolor tagu z `mapa_kolorow_tagow` albo None, gdy tagu nie ma w słowniku
    (np. przyszedł z importu CSV)."""
    return mapa.get(klucz_nazwy(nazwa))


def pierwszy_wolny_kolor_tagu(auto_id) -> str:
    """Kolor nowego tagu: pierwszy z KOLEJNOSC_KOLOROW_TAGOW nieużyty w pojeździe; po
    wyczerpaniu palety od nowa."""
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
    """Zmienia nazwę/kolor tagu i kaskadowo podmienia nazwę we wpisach. False (bez
    zmian), gdy nowa nazwa to inna pisownia INNEGO tagu pojazdu — do łączenia jest
    scalanie duplikatów."""
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


# Kwota wpisu w tabelach z tagami — tylko te wpisy mogą mieć tag.
KOLUMNY_KWOTY_TAGOWANYCH = {"tankowania": "kwota", "wizyty": "koszt_calkowity", "inne_koszty": "kwota"}


def koszty_wg_tagow(auto_id, od=None, do=None) -> dict[str, Any]:
    """Wydatki z tagami w okresie [od, do] (`date` albo None): na tag suma i liczba wpisów (wpis
    z kilkoma tagami liczy się przy KAŻDYM — suma tagów bywa większa niż wydatki), kolor ze
    słownika; osobno wpisy bez tagu i wszystko razem. Liczą się tankowania, wizyty i inne
    koszty — tylko one mają tagi."""
    wynik = {"tagi": [], "bez_tagu": {"kwota": 0.0, "liczba": 0}, "razem": 0.0, "liczba": 0}
    if not auto_id:
        return wynik
    slownik = {klucz_nazwy(n): (n, k) for _, n, k in pobierz_tagi(auto_id)}
    warunek, parametry = warunek_zakresu_dat("data_iso", od, do)
    sumy = {}
    with polacz_baze(zmienia_dane=False) as conn:
        for tabela in TABELE_Z_TAGAMI:
            kolumna = KOLUMNY_KWOTY_TAGOWANYCH[tabela]
            for kwota, tagi in conn.execute(
                    f"SELECT {kolumna}, tagi FROM {tabela} WHERE auto_id=?{warunek}", [auto_id, *parametry]):
                kwota = float(kwota or 0)
                if kwota <= 0:
                    continue
                wynik["razem"] += kwota
                wynik["liczba"] += 1
                klucze = {}
                for tag in str(tagi or "").split(","):
                    klucz = klucz_nazwy(tag)
                    if klucz and klucz not in klucze:
                        klucze[klucz] = tag.strip()
                if not klucze:
                    wynik["bez_tagu"]["kwota"] += kwota
                    wynik["bez_tagu"]["liczba"] += 1
                for klucz, tag in klucze.items():
                    nazwa, kolor = slownik.get(klucz, (tag, None))
                    pozycja = sumy.setdefault(klucz, {"nazwa": nazwa, "klucz": klucz, "kolor": kolor,
                                                      "kwota": 0.0, "liczba": 0})
                    pozycja["kwota"] += kwota
                    pozycja["liczba"] += 1
    wynik["tagi"] = sorted(sumy.values(), key=lambda p: (-p["kwota"], p["klucz"]))
    return wynik


def tagi_miesiaca(auto_id, dzis=None) -> dict[str, Any] | None:
    """Kafelek kokpitu: `koszty_wg_tagow` od 1. dnia bieżącego miesiąca do dziś; None, gdy auto
    nie ma ani jednego otagowanego wpisu (kafelek „nie dotyczy” chowa się sam)."""
    if not auto_id:
        return None
    dzis = dzis or datetime.now().date()
    with polacz_baze(zmienia_dane=False) as conn:
        uzywa = any(conn.execute(f"SELECT 1 FROM {t} WHERE auto_id=? AND tagi IS NOT NULL AND tagi <> '' LIMIT 1",
                                 (auto_id,)).fetchone() for t in TABELE_Z_TAGAMI)
    if not uzywa:
        return None
    return koszty_wg_tagow(auto_id, date(dzis.year, dzis.month, 1), dzis)


def sumy_tagow_roku(auto_id, rok=None) -> dict[str, dict[str, Any]]:
    """{klucz_nazwy(tag): pozycja z `koszty_wg_tagow`} za rok kalendarzowy (domyślnie bieżący) —
    kwota przy tagu w edytorze tagów."""
    rok = int(rok or datetime.now().year)
    return {p["klucz"]: p for p in koszty_wg_tagow(auto_id, date(rok, 1, 1), date(rok, 12, 31))["tagi"]}


__all__ = [
    "KOLEJNOSC_KOLOROW_TAGOW",
    "KOLUMNY_KWOTY_TAGOWANYCH",
    "koszty_wg_tagow",
    "sumy_tagow_roku",
    "tagi_miesiaca",
    "dodaj_tag",
    "edytuj_tag_w_slowniku",
    "kolor_tagu",
    "mapa_kolorow_tagow",
    "pierwszy_wolny_kolor_tagu",
    "pobierz_tagi",
    "usun_tag_ze_slownika",
]
