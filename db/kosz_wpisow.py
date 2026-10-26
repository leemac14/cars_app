"""Kosz wpisów (Z-01): usunięty wpis z kaskadą jako migawka JSON w `kosz_wpisy`, pliki
w kosz_zalaczniki/; przywracanie z przemapowaniem kluczy. Archiwum: `kosz-wpisow`."""

import json
import os
import shutil
import sqlite3
import uuid
from datetime import datetime
from typing import Any

import log

from .stale import DNI_KOSZA_DOMYSLNIE, DNI_KOSZA_OPCJE, FOLDER_KOSZ, TABELE_Z_WIELOMA_ZALACZNIKAMI, TABELE_Z_ZALACZNIKIEM
from .polaczenie import polacz_baze
from .pomocnicze import parsuj_int_bezpiecznie
from .daty import uzupelnij_date_iso
from .ustawienia import pobierz_ustawienie, zapisz_ustawienie
from .synchronizacja import czy_moge_zmieniac_rekord, czy_tylko_podglad, zarejestruj_nagrobek
from .zalaczniki import (
    KOLUMNY_ZE_SCIEZKAMI, _upewnij_folder_odroczonych, pelna_sciezka_zalacznika, sciezka_pliku_zalacznika,
    usun_plik_zalacznika, wzgledna_sciezka_zalacznika,
)
from .przebieg import przelicz_wszystkie_zadania
from .stan_magazynu import ZUZYCIE_MAGAZYNU, przelicz_stan_magazynu, zapewnij_stan_wyjsciowy


# Kolejność MA ZNACZENIE przy odtwarzaniu (pojazdu i wpisów) — klucz obcy wymaga, żeby
# rodzic istniał wcześniej: historia zależy od zadań i wizyt, wizyta_czesci_magazynu od
# wizyt i magazynu, do_zrobienia od zadań, wpisu serwisowego, kosztu i wizyty (a jej
# dziennik od niej). `zalaczniki` na końcu: ich rekord_id przemapowuje się po wpisach
# każdej tabeli.
KOSZ_TABELE_POTOMNE = [
    "zadania", "wizyty", "magazyn_czesci", "tagi", "tankowania",
    "inne_koszty", "zestawy_opon", "zdjecia_karoserii", "odczyty_przebiegu",
    "warsztaty", "wydatki_cykliczne", "pakiety_serwisowe_wlasne",
    "trasy_szablony", "szablony_wpisow", "checklisty",
    "historia", "wizyta_czesci_magazynu", "historia_czesci_magazynu",
    "checklisty_pozycje", "do_zrobienia", "do_zrobienia_zdarzenia",
    "budzety", "rozliczenia", "szkice_wpisow", "ceny_czesci", "przejazdy",
    "dolewki", "pomiary_bieznika", "montaze_opon", "dokumenty_pojazdu", "zalaczniki",
]


# Tabele bez kolumny auto_id — z pojazdem związane wyłącznie pośrednio.
KOSZ_TABELE_BEZ_AUTO_ID = {
    "historia", "wizyta_czesci_magazynu", "historia_czesci_magazynu", "checklisty_pozycje",
    "do_zrobienia_zdarzenia",
}


# Odwołania do przemapowania, gdy przywracany rekord NIE odzyska oryginalnego ID
# (bo w międzyczasie zajął je inny wpis — np. po imporcie bazy). Bez tego
# historia wróciłaby podpięta pod cudzy podzespół. Kosz wpisów czyta stąd też
# kaskadę usunięcia (ON DELETE CASCADE zabiera dziecko, SET NULL zeruje odwołanie).
KOSZ_KLUCZE_OBCE = {
    "do_zrobienia": {"zadanie_id": "zadania", "historia_id": "historia", "koszt_id": "inne_koszty",
                     "wizyta_id": "wizyty"},
    "do_zrobienia_zdarzenia": {"pozycja_id": "do_zrobienia"},
    "historia": {"zadanie_id": "zadania", "wizyta_id": "wizyty"},
    "wizyta_czesci_magazynu": {"wizyta_id": "wizyty", "magazyn_id": "magazyn_czesci"},
    "historia_czesci_magazynu": {"historia_id": "historia", "magazyn_id": "magazyn_czesci"},
    "checklisty_pozycje": {"checklista_id": "checklisty"},
    "dolewki": {"magazyn_id": "magazyn_czesci", "koszt_id": "inne_koszty"},
    "pomiary_bieznika": {"zestaw_id": "zestawy_opon"},
    "montaze_opon": {"zestaw_id": "zestawy_opon", "historia_id": "historia", "koszt_id": "inne_koszty"},
}


# Zużycie z magazynu (`ZUZYCIE_MAGAZYNU`, db/stan_magazynu.py) wraca na półkę, gdy wiersz znika
# bez swojej pozycji (i schodzi z niej znowu przy przywróceniu) — stan to stan wyjściowy minus
# zużycie, więc wystarczy go przeliczyć. Usunięta sama pozycja niczego nie oddaje.


# Usuwane bez kosza, z samym „Cofnij”: rozliczenie cofa się tylko ostatnie liczące się
# (db/rozliczenia.py) — przywrócone po tygodniu rozjechałoby saldo.
POZA_KOSZEM_WPISOW = {"rozliczenia"}


# Rodzic, bez którego wpis nie wróci (przywrócenie odmawia i mówi, co przywrócić najpierw).
POWODY_BRAKU_RODZICA = {
    "zadania": "Podzespołu tego wpisu już nie ma — przywróć go najpierw z kosza.",
    "wizyty": "Wizyty tego wpisu już nie ma — przywróć ją najpierw z kosza.",
}


class BrakRodzica(Exception):
    """Korzeń przywracanego wpisu wskazuje rodzica, którego już nie ma."""

    def __init__(self, tabela):
        super().__init__(tabela)
        self.tabela = tabela


def pobierz_dni_kosza():
    """Ile dni usunięte wpisy i pojazdy leżą w koszu, zanim znikną na dobre. 0 = bez limitu."""
    try:
        w = int(pobierz_ustawienie("dni_kosza", str(DNI_KOSZA_DOMYSLNIE)))
    except (TypeError, ValueError):
        return DNI_KOSZA_DOMYSLNIE
    return w if w in DNI_KOSZA_OPCJE else DNI_KOSZA_DOMYSLNIE


def zapisz_dni_kosza(dni):
    zapisz_ustawienie("dni_kosza", str(parsuj_int_bezpiecznie(dni, DNI_KOSZA_DOMYSLNIE)))


def _upewnij_folder_kosza():
    os.makedirs(FOLDER_KOSZ, exist_ok=True)
    return FOLDER_KOSZ


def _data_usuniecia(tekst):
    try:
        return datetime.strptime(str(tekst), "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def _dni_do_usuniecia(usunieto, dni_retencji, teraz):
    """None przy retencji bez limitu, 0 — zniknie przy najbliższym starcie."""
    if not dni_retencji or not usunieto:
        return None
    return max(0, dni_retencji - (teraz - usunieto).days)


# ---------------------------------------------------------------- uprawnienia


def _auto_wiersza(tabela, dane):
    """Do którego pojazdu należy usuwany wiersz. Większość tabel ma auto_id
    wprost; historia serwisowa wisi pod podzespołem i trzeba ją dojechać
    JOIN-em."""
    if dane.get("auto_id"):
        return dane["auto_id"]
    if tabela == "historia" and dane.get("zadanie_id"):
        with polacz_baze(zmienia_dane=False) as conn:
            w = conn.execute("SELECT auto_id FROM zadania WHERE id=?", (dane["zadanie_id"],)).fetchone()
        return w[0] if w else None
    return None


def _wolno_usunac(tabela, dane, auto_id=None):
    """Ostatnia bramka przed skasowaniem czegokolwiek. Usuwanie z list omija
    router (nie zmienia trasy), więc bez tego sprawdzenia gość z rolą „tylko
    podgląd” mógłby wyczyścić cudzą historię u siebie — a nagrobki poszłyby
    do chmury i wyczyściłyby ją wszystkim."""
    auto_id = auto_id if auto_id is not None else _auto_wiersza(tabela, dane)
    if not auto_id:
        return True  # wiersz bez pojazdu (np. dane globalne) — rola go nie dotyczy
    try:
        return czy_moge_zmieniac_rekord(auto_id, tabela, dane.get("dodane_przez"))
    except Exception:
        log.polkniety("sprawdzenie roli przed usunięciem")
        return True


# ---------------------------------------------------------------- migawka


def _kolumny(c, tabela) -> list[str]:
    return [w[1] for w in c.execute(f"PRAGMA table_info({tabela})").fetchall()]


def _kaskadowe(c) -> dict[tuple[str, str], bool]:
    """{(tabela, kolumna): czy ON DELETE CASCADE} dla kluczy z KOSZ_KLUCZE_OBCE."""
    wynik = {}
    for tabela in KOSZ_KLUCZE_OBCE:
        for w in c.execute(f"PRAGMA foreign_key_list({tabela})").fetchall():
            wynik[(tabela, w[3])] = str(w[6]).upper() == "CASCADE"
    return wynik


def _paczki(wartosci, rozmiar=500):
    wartosci = list(wartosci)
    for i in range(0, len(wartosci), rozmiar):
        yield wartosci[i:i + rozmiar]


def _wiersze(c, tabela, kolumna, wartosci, warunek="", parametry=()) -> list[dict[str, Any]]:
    wynik = []
    for paczka in _paczki(wartosci):
        c.execute(f"SELECT * FROM {tabela} WHERE {warunek}{kolumna} IN ({','.join('?' * len(paczka))})",
                  (*parametry, *paczka))
        wynik += [dict(w) for w in c.fetchall()]
    return wynik


def _zrzut_wpisow(c, korzenie) -> dict[str, Any]:
    """Migawka usunięcia: wiersze korzeni ({tabela: [id]}), wszystko, co zabierze kaskada,
    odwołania zerowane przez ON DELETE SET NULL i wiersze plików (`zalaczniki`)."""
    tabele = {}
    kaskada = _kaskadowe(c)

    def dodaj(tabela, wiersze):
        znane = tabele.setdefault(tabela, {})
        nowe = [w["id"] for w in wiersze if w["id"] not in znane]
        znane.update({w["id"]: w for w in wiersze})
        return nowe

    kolejka = [(t, dodaj(t, _wiersze(c, t, "id", ids))) for t, ids in korzenie.items()]
    dowiazania = []
    while kolejka:
        rodzic, ids = kolejka.pop(0)
        if not ids:
            continue
        for dziecko, klucze in KOSZ_KLUCZE_OBCE.items():
            for kolumna, tabela_rodzica in klucze.items():
                if tabela_rodzica != rodzic:
                    continue
                wiersze = _wiersze(c, dziecko, kolumna, ids)
                if kaskada.get((dziecko, kolumna)):
                    kolejka.append((dziecko, dodaj(dziecko, wiersze)))
                else:
                    dowiazania += [[dziecko, w["id"], kolumna, rodzic, w[kolumna]] for w in wiersze]
    # Wiersz, który sam idzie do kosza, wraca z odwołaniem z migawki.
    dowiazania = [d for d in dowiazania if d[1] not in tabele.get(d[0], {})]
    for tabela in TABELE_Z_WIELOMA_ZALACZNIKAMI:
        if tabele.get(tabela):
            dodaj("zalaczniki", _wiersze(c, "zalaczniki", "rekord_id", list(tabele[tabela]), "tabela=? AND ", (tabela,)))
    return {"tabele": {t: list(w.values()) for t, w in tabele.items() if w}, "dowiazania": dowiazania}


def _sciezki_migawki(tabele) -> list[str]:
    sciezki = [w.get("sciezka") for w in tabele.get("zalaczniki") or []]
    for tabela in sorted(TABELE_Z_ZALACZNIKIEM):
        sciezki += [w.get("zalacznik") for w in tabele.get(tabela) or []]
    return list(dict.fromkeys(s for s in sciezki if s))


def _wskazywany_poza_migawka(c, zapisana, tabele):
    """Czy plik wskazuje jeszcze wiersz spoza usuwanych — wtedy do kosza idzie kopia."""
    for tabela, kolumna in KOLUMNY_ZE_SCIEZKAMI:
        swoje = {w.get("id") for w in tabele.get(tabela) or []}
        if any(w[0] not in swoje for w in c.execute(f"SELECT id FROM {tabela} WHERE {kolumna}=?", (zapisana,))):
            return True
    return False


def _odloz_pliki(c, tabele, folder) -> list[list[str]]:
    """Pliki migawki do `folder`; pary [miejsce w folderze, wartość z bazy]."""
    pary = []
    for zapisana in _sciezki_migawki(tabele):
        zrodlo = sciezka_pliku_zalacznika(zapisana)
        if not zrodlo or not os.path.isfile(zrodlo):
            continue
        cel = os.path.join(folder, f"w_{uuid.uuid4().hex}_{os.path.basename(zrodlo)}")
        try:
            if _wskazywany_poza_migawka(c, zapisana, tabele):
                shutil.copyfile(zrodlo, cel)
            else:
                shutil.move(zrodlo, cel)
        except OSError:
            log.polkniety("plik usuwanego wpisu do kosza")
            continue
        pary.append([wzgledna_sciezka_zalacznika(cel), zapisana])
    return pary


def _plan_plikow(pary) -> tuple[list[tuple[str, str]], dict[str, str]]:
    """(przeniesienia z kosza, podmiana {wartość z migawki: nowa}) — zajęte miejsce albo
    ścieżka z innego urządzenia dostaje nową nazwę w tutejszym folderze."""
    ruchy, podmiana, zajete = [], {}, set()
    for para in pary or []:
        try:
            zrodlo, oryginal = sciezka_pliku_zalacznika(para[0]), para[1]
        except (IndexError, TypeError):
            continue
        if not zrodlo or not os.path.isfile(zrodlo) or not oryginal:
            continue
        wskazana = pelna_sciezka_zalacznika(oryginal)
        cel = pelna_sciezka_zalacznika(wzgledna_sciezka_zalacznika(oryginal))
        if os.path.exists(cel) or os.path.normcase(cel) in zajete:
            trzon, rozszerzenie = os.path.splitext(cel)
            cel = f"{trzon}_{uuid.uuid4().hex[:8]}{rozszerzenie}"
        zajete.add(os.path.normcase(cel))
        ruchy.append((zrodlo, cel))
        if os.path.normcase(os.path.abspath(cel)) != os.path.normcase(os.path.abspath(wskazana)):
            podmiana[oryginal] = wzgledna_sciezka_zalacznika(cel)
    return ruchy, podmiana


def _przenies(ruchy) -> list[tuple[str, str]]:
    zrobione = []
    for zrodlo, cel in ruchy:
        try:
            if os.path.dirname(cel):
                os.makedirs(os.path.dirname(cel), exist_ok=True)
            shutil.move(zrodlo, cel)
            zrobione.append((zrodlo, cel))
        except OSError:
            log.polkniety("przeniesienie pliku wpisu z kosza")
    return zrobione


def _cofnij_odlozenie(pary):
    """Usunięcie się nie udało — pliki wracają tam, skąd wyszły (kopia znika)."""
    for miejsce, oryginal in pary:
        zrodlo = sciezka_pliku_zalacznika(miejsce)
        cel = pelna_sciezka_zalacznika(oryginal)
        if not zrodlo or not os.path.isfile(zrodlo):
            continue
        if cel and not os.path.exists(cel):
            _przenies([(zrodlo, cel)])
        else:
            usun_plik_zalacznika(miejsce)


def _opis_wpisu(c, tabela, wiersze):
    """Kontekst, którego po usunięciu nie da się już doczytać: nazwa podzespołu wpisu serwisowego."""
    if tabela != "historia":
        return None
    nazwy = _wiersze(c, "zadania", "id", {w.get("zadanie_id") for w in wiersze if w.get("zadanie_id")})
    return ", ".join(sorted({str(n.get("nazwa") or "") for n in nazwy} - {""})) or None


def _zwroty_magazynu(tabele) -> list[tuple[int, float]]:
    """(pozycja, ilość) zużycia, które wraca na półkę — tylko gdy pozycja sama zostaje."""
    czesci = {w.get("id") for w in tabele.get("magazyn_czesci") or []}
    zwroty = []
    for tabela, kolumna in ZUZYCIE_MAGAZYNU.items():
        for w in tabele.get(tabela) or []:
            if w.get("magazyn_id") and w["magazyn_id"] not in czesci and w.get(kolumna):
                zwroty.append((w["magazyn_id"], w[kolumna]))
    return zwroty


# ---------------------------------------------------------------- usunięcie


def usun_do_kosza(tabela, ids, wlasne=None, do_kosza=True, przed_usunieciem=None) -> dict[str, Any] | None:
    """Usuwa wpisy `tabela` o `ids` z kaskadą (plus `wlasne` {tabela: [id]} — wiersze, które
    wpis posiada, np. koszt dolewki) do kosza wpisów. Wynik dla utils.pokaz_komunikat_cofnij:
    „cofnij” przywraca, „finalizuj” — przy koszu nic, bez kosza kasuje odłożone pliki;
    „pominiete” — cudze wpisy (rola). None — nic nie usunięto. `przed_usunieciem(conn,
    wiersze)` chodzi w transakcji usunięcia."""
    ids = [i for i in ids or [] if i is not None]
    if not ids:
        return None
    with polacz_baze(zmienia_dane=False) as conn:
        conn.row_factory = sqlite3.Row
        wiersze = _wiersze(conn.cursor(), tabela, "id", ids)
    if not wiersze:
        return None

    grupy = {}
    for w in wiersze:
        auto_id = _auto_wiersza(tabela, w)
        if _wolno_usunac(tabela, w, auto_id):
            grupy.setdefault(auto_id, []).append(w)
    if not grupy:
        return None
    pominiete = len(wiersze) - sum(len(g) for g in grupy.values())

    wyniki = [_usun_grupe(tabela, auto_id, grupa, wlasne if i == 0 else None, do_kosza, przed_usunieciem)
              for i, (auto_id, grupa) in enumerate(grupy.items())]
    stan = {"cofniete": False, "trwale": False}

    def cofnij():
        if stan["cofniete"] or stan["trwale"]:
            return None
        stan["cofniete"] = True
        odpowiedzi = [w["cofnij"]() for w in wyniki]
        nieudane = [o for o in odpowiedzi if not o or not o.get("ok")]
        return nieudane[0] if nieudane else (odpowiedzi[0] if odpowiedzi else None)

    def finalizuj():
        if stan["cofniete"] or do_kosza:
            return  # wpis czeka w koszu — „Cofnij” po zgaśnięciu komunikatu robi to samo co Kosz
        stan["trwale"] = True
        for w in wyniki:
            w["finalizuj"]()

    return {
        "cofnij": cofnij, "finalizuj": finalizuj, "dane": wyniki[0]["dane"], "pominiete": pominiete,
        "w_koszu": do_kosza, "dni_kosza": pobierz_dni_kosza() if do_kosza else None,
        "kosz_id": wyniki[0]["kosz_id"], "kosz_ids": [w["kosz_id"] for w in wyniki if w["kosz_id"]],
    }


def _usun_grupe(tabela, auto_id, wiersze, wlasne, do_kosza, przed_usunieciem) -> dict[str, Any]:
    korzenie = {tabela: [w["id"] for w in wiersze]}
    for t, dodatkowe in (wlasne or {}).items():
        korzenie.setdefault(t, []).extend(i for i in dodatkowe if i is not None)

    with polacz_baze(zmienia_dane=False) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        migawka = _zrzut_wpisow(c, korzenie)
        opis = _opis_wpisu(c, tabela, wiersze)
        folder = _upewnij_folder_kosza() if do_kosza else _upewnij_folder_odroczonych()
        pary = _odloz_pliki(c, migawka["tabele"], folder)
    migawka.update({"wersja": 1, "tabela": tabela, "korzenie": korzenie})

    rozmiar = 0
    for para in pary:
        try:
            rozmiar += os.path.getsize(sciezka_pliku_zalacznika(para[0]))
        except (OSError, TypeError):
            log.polkniety("rozmiar pliku w koszu wpisów")

    kosz_id = None
    try:
        with polacz_baze() as conn:
            if przed_usunieciem:
                przed_usunieciem(conn, wiersze)
            zwroty = {magazyn_id for magazyn_id, _ in _zwroty_magazynu(migawka["tabele"])}
            zapewnij_stan_wyjsciowy(conn, zwroty)
            for t in [t for t in reversed(KOSZ_TABELE_POTOMNE) if korzenie.get(t)]:
                for paczka in _paczki(korzenie[t]):
                    conn.execute(f"DELETE FROM {t} WHERE id IN ({','.join('?' * len(paczka))})", tuple(paczka))
            for paczka in _paczki([w["id"] for w in migawka["tabele"].get("zalaczniki") or []]):
                conn.execute(f"DELETE FROM zalaczniki WHERE id IN ({','.join('?' * len(paczka))})", tuple(paczka))
            przelicz_stan_magazynu(conn, zwroty)
            if do_kosza:
                kosz_id = conn.execute(
                    "INSERT INTO kosz_wpisy (auto_id, tabela, opis, liczba, data_usuniecia, migawka, pliki, "
                    "rozmiar_plikow, schemat_wersja) VALUES (?,?,?,?,?,?,?,?,?)",
                    (auto_id, tabela, opis, len(wiersze), datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                     json.dumps(migawka, ensure_ascii=False, default=str), json.dumps(pary, ensure_ascii=False),
                     rozmiar, parsuj_int_bezpiecznie(pobierz_ustawienie("schema_version", "0"), 0)),
                ).lastrowid
    except Exception:
        _cofnij_odlozenie(pary)
        raise

    # Nagrobek z pojazdem PO zatwierdzeniu (otwarta transakcja zakleszczyłaby drugie połączenie).
    for t, wiersze_t in migawka["tabele"].items():
        for w in wiersze_t:
            if w.get("zdalne_id"):
                zarejestruj_nagrobek(t, w["zdalne_id"], auto_id)

    stan = {"cofniete": False, "trwale": False}

    def cofnij():
        if stan["cofniete"] or stan["trwale"]:
            return None
        stan["cofniete"] = True
        if do_kosza:
            return przywroc_wpis_z_kosza(kosz_id)
        return _przywroc_migawke(auto_id, migawka, pary)

    def finalizuj():
        if stan["cofniete"] or do_kosza:
            return
        stan["trwale"] = True
        for para in pary:
            usun_plik_zalacznika(para[0])

    return {"cofnij": cofnij, "finalizuj": finalizuj, "dane": wiersze[0], "kosz_id": kosz_id}


# ---------------------------------------------------------------- przywracanie


def _rodzic_pojazdu(c, tabela, rekord_id, auto_id):
    """Czy wiersz istnieje i należy do pojazdu (historia — przez swój podzespół)."""
    if tabela == "historia":
        c.execute("SELECT 1 FROM historia h JOIN zadania z ON h.zadanie_id = z.id WHERE h.id=? AND z.auto_id=?",
                  (rekord_id, auto_id))
    elif tabela in KOSZ_TABELE_BEZ_AUTO_ID:
        c.execute(f"SELECT 1 FROM {tabela} WHERE id=?", (rekord_id,))
    else:
        c.execute(f"SELECT 1 FROM {tabela} WHERE id=? AND auto_id=?", (rekord_id, auto_id))
    return c.fetchone() is not None


def _podepnij_rodzicow(c, tabela, dane, mapy, odpadle, auto_id, kaskada):
    """Odwołania wiersza na przywrócone albo istniejące wiersze. Zwraca tabelę brakującego
    WYMAGANEGO rodzica (wiersz nie wróci) albo None; brak opcjonalnego zeruje odwołanie."""
    for kolumna, rodzic in KOSZ_KLUCZE_OBCE.get(tabela, {}).items():
        wartosc = dane.get(kolumna)
        if wartosc is None:
            continue
        if wartosc in mapy.get(rodzic, {}):
            dane[kolumna] = mapy[rodzic][wartosc]
        elif wartosc in odpadle.get(rodzic, ()) or not _rodzic_pojazdu(c, rodzic, wartosc, auto_id):
            if kaskada.get((tabela, kolumna)):
                return rodzic
            dane[kolumna] = None
    if tabela == "zalaczniki":
        rodzic, wartosc = dane.get("tabela"), dane.get("rekord_id")
        if rodzic not in TABELE_Z_WIELOMA_ZALACZNIKAMI:
            return rodzic or "zalaczniki"
        if wartosc in mapy.get(rodzic, {}):
            dane["rekord_id"] = mapy[rodzic][wartosc]
        elif wartosc in odpadle.get(rodzic, ()) or not _rodzic_pojazdu(c, rodzic, wartosc, auto_id):
            return rodzic
    return None


def _odtworz_wpisy(conn, auto_id, migawka, podmiana) -> dict[str, Any]:
    """Wstawia wiersze migawki w transakcji `conn` (rodzic przed dzieckiem); id 1:1, gdy wolne.
    Wiersz bez wymaganego rodzica odpada, korzeń — cała operacja (BrakRodzica). Niewysłany
    nagrobek znika; wysłany — wiersz jedzie do chmury jako nowy (tamten rekord jest usunięty)."""
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    tabele = migawka.get("tabele") or {}
    korzenie = {t: set(ids or []) for t, ids in (migawka.get("korzenie") or {}).items()}
    czesci_w_migawce = {w.get("id") for w in tabele.get("magazyn_czesci") or []}
    kaskada = _kaskadowe(c)
    mapy, odpadle, zuzycie = {}, {}, []
    # Pozycje spoza migawki, z których zużycie znów zejdzie: stan wyjściowy PRZED wstawieniem.
    zapewnij_stan_wyjsciowy(conn, {w["magazyn_id"] for t in ZUZYCIE_MAGAZYNU for w in tabele.get(t) or []
                                   if w.get("magazyn_id") and w["magazyn_id"] not in czesci_w_migawce})

    for tabela in KOSZ_TABELE_POTOMNE:
        wiersze = tabele.get(tabela) or []
        if not wiersze:
            continue
        kolumny = set(_kolumny(c, tabela))
        mapy[tabela], odpadle[tabela] = {}, set()
        for zrodlowy in wiersze:
            dane = {k: v for k, v in zrodlowy.items() if k in kolumny}
            stare_id = dane.get("id")
            if "auto_id" in kolumny and tabela not in KOSZ_TABELE_BEZ_AUTO_ID:
                dane["auto_id"] = auto_id
            brak = _podepnij_rodzicow(c, tabela, dane, mapy, odpadle, auto_id, kaskada)
            if brak:
                if stare_id in korzenie.get(tabela, ()):
                    raise BrakRodzica(brak)
                odpadle[tabela].add(stare_id)
                continue
            zdalne = dane.get("zdalne_id")
            if zdalne:
                istniejacy = c.execute(f"SELECT id FROM {tabela} WHERE zdalne_id=?", (zdalne,)).fetchone()
                if istniejacy:
                    mapy[tabela][stare_id] = istniejacy[0]  # wrócił z chmury — bez dubla
                    continue
                if c.execute("DELETE FROM zdalne_nagrobki WHERE zdalny_id=?", (zdalne,)).rowcount == 0:
                    dane["zdalne_id"] = None
                    if "zdalny_hash" in dane:
                        dane["zdalny_hash"] = None
            for kolumna in ("sciezka", "zalacznik"):
                if dane.get(kolumna) in podmiana:
                    dane[kolumna] = podmiana[dane[kolumna]]
            uzupelnij_date_iso(tabela, dane)
            if stare_id is None or c.execute(f"SELECT 1 FROM {tabela} WHERE id=?", (stare_id,)).fetchone():
                dane.pop("id", None)
            nazwy = list(dane)
            c.execute(f"INSERT INTO {tabela} ({','.join(nazwy)}) VALUES ({','.join('?' * len(nazwy))})",
                      tuple(dane[k] for k in nazwy))
            mapy[tabela][stare_id] = c.lastrowid
            kolumna_ilosci = ZUZYCIE_MAGAZYNU.get(tabela)
            if (kolumna_ilosci and dane.get("magazyn_id") and dane.get(kolumna_ilosci)
                    and zrodlowy.get("magazyn_id") not in czesci_w_migawce):
                zuzycie.append((dane["magazyn_id"], dane[kolumna_ilosci]))

    for dziecko, dziecko_id, kolumna, rodzic, rodzic_id in migawka.get("dowiazania") or []:
        nowy = mapy.get(rodzic, {}).get(rodzic_id)
        if nowy is not None and KOSZ_KLUCZE_OBCE.get(dziecko, {}).get(kolumna) == rodzic:
            c.execute(f"UPDATE {dziecko} SET {kolumna}=? WHERE id=? AND {kolumna} IS NULL", (nowy, dziecko_id))
    # Stan = stan wyjściowy minus zużycie: przywrócone zużycie i przywrócone pozycje (migawka
    # sprzed migracji 55 nie ma stanu wyjściowego — liczy się wtedy z zapisanego stanu).
    przelicz_stan_magazynu(conn, {magazyn_id for magazyn_id, _ in zuzycie}
                           | set((mapy.get("magazyn_czesci") or {}).values()))
    return {"mapy": mapy, "odpadle": sum(len(v) for v in odpadle.values())}


def _przywroc_migawke(auto_id, migawka, pary, kosz_id=None) -> dict[str, Any]:
    ruchy, podmiana = _plan_plikow(pary)
    zrobione = _przenies(ruchy)
    try:
        with polacz_baze() as conn:
            wynik = _odtworz_wpisy(conn, auto_id, migawka, podmiana)
            if kosz_id:
                conn.execute("DELETE FROM kosz_wpisy WHERE id=?", (kosz_id,))
    except BrakRodzica as e:
        _przenies([(cel, zrodlo) for zrodlo, cel in zrobione])
        return {"ok": False, "powod": POWODY_BRAKU_RODZICA.get(
            e.tabela, "Brakuje wpisu, do którego to należało — przywróć go najpierw z kosza.")}
    except Exception:
        _przenies([(cel, zrodlo) for zrodlo, cel in zrobione])
        raise
    if {"historia", "zadania", "wizyty"} & set(migawka.get("tabele") or {}):
        przelicz_wszystkie_zadania(auto_id)
    korzen = migawka.get("tabela")
    return {"ok": True, "auto_id": auto_id, "tabela": korzen,
            "liczba": len((migawka.get("korzenie") or {}).get(korzen) or []), "odpadle": wynik["odpadle"]}


def przywroc_wpis_z_kosza(kosz_id) -> dict[str, Any] | None:
    """Przywraca pozycję kosza wpisów: {"ok", "powod"} (odmowa — auto w koszu, podgląd,
    brak podzespołu) albo {"ok": True, "auto_id", "tabela", "liczba"}; None — pozycji nie ma."""
    if not kosz_id:
        return None
    with polacz_baze(zmienia_dane=False) as conn:
        conn.row_factory = sqlite3.Row
        try:
            w = conn.execute("SELECT * FROM kosz_wpisy WHERE id=?", (kosz_id,)).fetchone()
        except sqlite3.OperationalError:
            return None
        if not w:
            return None
        auto_id = w["auto_id"]
        istnieje = auto_id is not None and conn.execute("SELECT 1 FROM samochody WHERE id=?", (auto_id,)).fetchone()
    if w["kosz_pojazdu_id"] or not istnieje:
        return {"ok": False, "powod": "Pojazd tego wpisu jest w koszu — przywróć najpierw pojazd."}
    if czy_tylko_podglad(auto_id):
        return {"ok": False, "powod": "Przy tym pojeździe masz tylko podgląd — wpisu nie da się przywrócić."}
    try:
        migawka = json.loads(w["migawka"])
        pary = json.loads(w["pliki"] or "[]")
    except (TypeError, ValueError):
        return {"ok": False, "powod": "Zapis tego wpisu w koszu jest uszkodzony."}
    return _przywroc_migawke(auto_id, migawka, pary, kosz_id)


# ---------------------------------------------------------------- lista i sprzątanie


def pobierz_kosz_wpisow() -> list[dict[str, Any]]:
    """Wpisy w koszu, najświeższe u góry (bez czekających razem z usuniętym pojazdem).
    'wiersze' — usunięte wpisy, 'zalezne' — {tabela: ile} tego, co zabrały ze sobą."""
    dni_retencji = pobierz_dni_kosza()
    with polacz_baze(zmienia_dane=False) as conn:
        conn.row_factory = sqlite3.Row
        try:
            wiersze = conn.execute(
                "SELECT k.*, s.nazwa AS nazwa_auta FROM kosz_wpisy k LEFT JOIN samochody s ON s.id = k.auto_id "
                "WHERE k.kosz_pojazdu_id IS NULL ORDER BY k.data_usuniecia DESC, k.id DESC").fetchall()
        except sqlite3.OperationalError:
            return []
    teraz = datetime.now()
    pozycje = []
    for w in wiersze:
        try:
            migawka = json.loads(w["migawka"])
            pliki = json.loads(w["pliki"] or "[]")
        except (TypeError, ValueError):
            migawka, pliki = {}, []
        tabele = migawka.get("tabele") or {}
        ids = set((migawka.get("korzenie") or {}).get(w["tabela"]) or [])
        usunieto = _data_usuniecia(w["data_usuniecia"])
        pozycje.append({
            "id": w["id"], "auto_id": w["auto_id"], "nazwa_auta": w["nazwa_auta"], "tabela": w["tabela"],
            "opis": w["opis"], "liczba": int(w["liczba"] or 0),
            "wiersze": [r for r in tabele.get(w["tabela"]) or [] if r.get("id") in ids],
            "zalezne": {t: len(r) for t, r in tabele.items() if t not in (w["tabela"], "zalaczniki")},
            "liczba_plikow": len(pliki), "rozmiar_plikow": int(w["rozmiar_plikow"] or 0),
            "data_usuniecia": usunieto,
            "data_tekst": usunieto.strftime("%d.%m.%Y %H:%M") if usunieto else "—",
            "dni_do_usuniecia": _dni_do_usuniecia(usunieto, dni_retencji, teraz),
        })
    return pozycje


def liczba_wpisow_w_koszu():
    with polacz_baze(zmienia_dane=False) as conn:
        try:
            return int(conn.execute("SELECT COUNT(*) FROM kosz_wpisy WHERE kosz_pojazdu_id IS NULL").fetchone()[0])
        except sqlite3.OperationalError:
            return 0


def _usun_pozycje_wpisow(warunek, parametry=()) -> int:
    """Trwale kasuje pozycje kosza wpisów spełniające `warunek` (pliki z dysku); nagrobki
    poszły już przy usunięciu. Zwraca liczbę pozycji."""
    with polacz_baze() as conn:
        try:
            wiersze = conn.execute(f"SELECT id, pliki FROM kosz_wpisy WHERE {warunek}", parametry).fetchall()
        except sqlite3.OperationalError:
            return 0
        for kosz_id, _ in wiersze:
            conn.execute("DELETE FROM kosz_wpisy WHERE id=?", (kosz_id,))
    for _, surowe in wiersze:
        try:
            pary = json.loads(surowe or "[]")
        except (TypeError, ValueError):
            pary = []
        for para in pary:
            if isinstance(para, list) and para:
                usun_plik_zalacznika(para[0])
    return len(wiersze)


def usun_wpis_z_kosza_trwale(kosz_id):
    """Kasuje pozycję kosza wpisów bezpowrotnie. True, gdy była."""
    return bool(kosz_id) and _usun_pozycje_wpisow("id=?", (kosz_id,)) > 0


def oproznij_kosz_wpisow():
    """Trwale kasuje wszystkie wpisy z kosza (poza czekającymi z usuniętym pojazdem)."""
    return _usun_pozycje_wpisow("kosz_pojazdu_id IS NULL")


def pliki_kosza_wpisow() -> list[str]:
    """Miejsca plików w folderze kosza zajęte przez pozycje kosza wpisów (dla sprzątania sierot)."""
    with polacz_baze(zmienia_dane=False) as conn:
        try:
            wiersze = conn.execute("SELECT pliki FROM kosz_wpisy").fetchall()
        except sqlite3.OperationalError:
            return []
    miejsca = []
    for (surowe,) in wiersze:
        try:
            miejsca += [p[0] for p in json.loads(surowe or "[]") if isinstance(p, list) and p]
        except (TypeError, ValueError):
            continue
    return miejsca


__all__ = [
    "KOSZ_KLUCZE_OBCE",
    "KOSZ_TABELE_BEZ_AUTO_ID",
    "KOSZ_TABELE_POTOMNE",
    "POZA_KOSZEM_WPISOW",
    "_upewnij_folder_kosza",
    "liczba_wpisow_w_koszu",
    "oproznij_kosz_wpisow",
    "pliki_kosza_wpisow",
    "pobierz_dni_kosza",
    "pobierz_kosz_wpisow",
    "przywroc_wpis_z_kosza",
    "usun_do_kosza",
    "usun_wpis_z_kosza_trwale",
    "zapisz_dni_kosza",
]
