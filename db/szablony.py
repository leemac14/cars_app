"""Szablony wpisów (M-02): nazwany wzór innego kosztu albo tankowania wołany z menu „+”.
Szablon jest cechą auta (jedzie synchronizacją jak zapisana trasa), licznik użyć — nawykiem
telefonu (poza sync). Koszt z kwotą zapisuje się jednym dotknięciem."""

import json
from datetime import datetime
from typing import Any

import log
from date import na_iso

from .stale import ENERGIA_PALIWO, ENERGIA_PRAD, TYPY_LADOWANIA
from .polaczenie import polacz_baze
from .pomocnicze import klucz_nazwy
from .ustawienia import pobierz_moje_imie
from .energia import normalizuj_rodzaj_energii
from .notatki import przytnij_notatke, zapisz_notatke
from .przebieg import sprawdz_czy_koszt_duplikat
from .kosz_wpisow import usun_do_kosza
from .koszty import etykieta_kategorii_innych

SZABLON_KOSZT = "koszt"
SZABLON_TANKOWANIE = "tankowanie"

# Co szablon zapamiętuje. Data, licznik, litry i pliki są z konkretnego dnia; kwota kosztu
# jest opcjonalna — bez niej szablon otwiera wypełniony formularz.
POLA_SZABLONU = {
    SZABLON_KOSZT: ("kategoria", "nazwa", "kwota", "tagi", "notatka"),
    SZABLON_TANKOWANIE: ("stacja", "rodzaj_energii", "typ_ladowania", "do_pelna", "tagi", "notatka"),
}

# Ile szablonów stoi wprost w menu „+” (reszta pod „Szablony…”).
SZABLONY_W_MENU = 3
MAKS_DLUGOSC_NAZWY_SZABLONU = 40


def _tekst_lub_none(wartosc):
    tekst = str(wartosc).strip() if wartosc is not None else ""
    return tekst or None


def oczysc_dane_szablonu(rodzaj, dane) -> dict[str, Any]:
    """Tylko pola z POLA_SZABLONU, w postaci, którą formularz przyjmie bez pytań."""
    dane = dane if isinstance(dane, dict) else {}
    wynik = {}
    for pole in POLA_SZABLONU.get(rodzaj, ()):
        wartosc = dane.get(pole)
        if pole == "kwota":
            try:
                wartosc = round(float(wartosc), 2) if wartosc not in (None, "") else None
            except (TypeError, ValueError):
                wartosc = None
            wartosc = wartosc if wartosc and wartosc > 0 else None
        elif pole == "do_pelna":
            wartosc = True if wartosc is None else bool(wartosc)
        elif pole == "rodzaj_energii":
            wartosc = wartosc if wartosc in (ENERGIA_PALIWO, ENERGIA_PRAD) else None
        elif pole == "typ_ladowania":
            wartosc = wartosc if wartosc in TYPY_LADOWANIA else None
        elif pole == "notatka":
            wartosc = _tekst_lub_none(przytnij_notatke(wartosc or ""))
        else:
            wartosc = _tekst_lub_none(wartosc)
        wynik[pole] = wartosc
    return wynik


def _dane_z_tekstu(rodzaj, tekst):
    try:
        dane = json.loads(tekst or "{}")
    except (TypeError, ValueError):
        log.polkniety("dane szablonu wpisu nie są JSON-em")
        dane = {}
    return oczysc_dane_szablonu(rodzaj, dane)


def _szablon(wiersz):
    sid, auto_id, nazwa, rodzaj, dane, uzycia, ostatnie = wiersz
    return {"id": sid, "auto_id": auto_id, "nazwa": nazwa, "rodzaj": rodzaj,
            "dane": _dane_z_tekstu(rodzaj, dane), "uzycia": int(uzycia or 0), "ostatnie_uzycie": ostatnie}


_KOLUMNY = "id, auto_id, nazwa, rodzaj, dane, uzycia, ostatnie_uzycie"


def pobierz_szablony(auto_id, rodzaj=None) -> list[dict[str, Any]]:
    """Szablony pojazdu w kolejności menu „+”: najczęściej używane, potem ostatnio użyte, potem nazwa."""
    if not auto_id:
        return []
    with polacz_baze(zmienia_dane=False) as conn:
        wiersze = conn.execute(f"SELECT {_KOLUMNY} FROM szablony_wpisow WHERE auto_id=?", (auto_id,)).fetchall()
    szablony = [_szablon(w) for w in wiersze if w[3] in POLA_SZABLONU and (rodzaj is None or w[3] == rodzaj)]
    szablony.sort(key=lambda s: klucz_nazwy(s["nazwa"]))
    szablony.sort(key=lambda s: s["ostatnie_uzycie"] or "", reverse=True)
    szablony.sort(key=lambda s: s["uzycia"], reverse=True)
    return szablony


def pobierz_szablon(szablon_id) -> dict[str, Any] | None:
    if not szablon_id:
        return None
    with polacz_baze(zmienia_dane=False) as conn:
        w = conn.execute(f"SELECT {_KOLUMNY} FROM szablony_wpisow WHERE id=?", (szablon_id,)).fetchone()
    return _szablon(w) if w and w[3] in POLA_SZABLONU else None


def dane_szablonu_z_wpisu(rodzaj, rekord_id) -> dict[str, Any] | None:
    """Pola szablonu z istniejącego kosztu albo tankowania (menu wpisu → „Zapisz jako szablon”)."""
    with polacz_baze(zmienia_dane=False) as conn:
        if rodzaj == SZABLON_KOSZT:
            w = conn.execute("SELECT auto_id, kategoria, nazwa, kwota, tagi, notatka FROM inne_koszty WHERE id=?",
                             (rekord_id,)).fetchone()
            if not w:
                return None
            dane = {"kategoria": etykieta_kategorii_innych(w[1]), "nazwa": w[2], "kwota": w[3],
                    "tagi": w[4], "notatka": w[5]}
        elif rodzaj == SZABLON_TANKOWANIE:
            w = conn.execute("SELECT auto_id, stacja, rodzaj_energii, typ_ladowania, do_pelna, tagi, notatka "
                             "FROM tankowania WHERE id=?", (rekord_id,)).fetchone()
            if not w:
                return None
            dane = {"stacja": w[1], "rodzaj_energii": normalizuj_rodzaj_energii(w[2], w[0]),
                    "typ_ladowania": w[3], "do_pelna": bool(w[4]), "tagi": w[5], "notatka": w[6]}
        else:
            return None
    return oczysc_dane_szablonu(rodzaj, dane)


def proponowana_nazwa_szablonu(rodzaj, dane) -> str:
    """Opis kosztu albo stacja — to, co i tak widać na karcie wpisu."""
    dane = dane or {}
    if rodzaj == SZABLON_KOSZT:
        nazwa = dane.get("nazwa") or dane.get("kategoria") or "Koszt"
    else:
        nazwa = dane.get("stacja") or ("Ładowanie" if dane.get("rodzaj_energii") == ENERGIA_PRAD else "Tankowanie")
    return str(nazwa)[:MAKS_DLUGOSC_NAZWY_SZABLONU]


def zapisz_szablon(auto_id, rodzaj, nazwa, dane, szablon_id=None) -> dict[str, Any]:
    """Nowy szablon albo poprawka istniejącego. Nowy o nazwie, która już jest (bez wielkości
    liter i ogonków), nadpisuje tamten — dwa „Myjnia” w menu nie dałyby się odróżnić; poprawka
    na nazwę innego szablonu odmawia. U kosztu nazwa szablonu JEST opisem wpisu.
    Wynik: {"ok", "id", "nowy", "powod"}."""
    nazwa = (nazwa or "").strip()[:MAKS_DLUGOSC_NAZWY_SZABLONU]
    if not auto_id or rodzaj not in POLA_SZABLONU:
        return {"ok": False, "id": None, "nowy": False, "powod": "Nieznany rodzaj szablonu."}
    if not nazwa:
        return {"ok": False, "id": None, "nowy": False, "powod": "Podaj nazwę szablonu."}
    dane = dict(dane or {})
    if rodzaj == SZABLON_KOSZT:
        dane["nazwa"] = nazwa
    tekst = json.dumps(oczysc_dane_szablonu(rodzaj, dane), ensure_ascii=False, sort_keys=True)
    klucz = klucz_nazwy(nazwa)
    with polacz_baze() as conn:
        tacy = [sid for sid, n in conn.execute(
            "SELECT id, nazwa FROM szablony_wpisow WHERE auto_id=? AND rodzaj=?", (auto_id, rodzaj)
        ).fetchall() if klucz_nazwy(n) == klucz]
        if szablon_id is not None and any(sid != szablon_id for sid in tacy):
            return {"ok": False, "id": szablon_id, "nowy": False, "powod": "Szablon o tej nazwie już jest."}
        cel = szablon_id if szablon_id is not None else (tacy[0] if tacy else None)
        if cel is None:
            cel = conn.execute("INSERT INTO szablony_wpisow (auto_id, nazwa, rodzaj, dane) VALUES (?,?,?,?)",
                               (auto_id, nazwa, rodzaj, tekst)).lastrowid
            return {"ok": True, "id": cel, "nowy": True, "powod": None}
        conn.execute("UPDATE szablony_wpisow SET nazwa=?, dane=? WHERE id=? AND auto_id=?", (nazwa, tekst, cel, auto_id))
    return {"ok": True, "id": cel, "nowy": False, "powod": None}


def zanotuj_uzycie_szablonu(szablon_id, conn=None):
    """Licznik do kolejności w menu „+” — pamięć telefonu, nie dane (metryk nie unieważnia)."""
    zapytanie = "UPDATE szablony_wpisow SET uzycia = COALESCE(uzycia, 0) + 1, ostatnie_uzycie=? WHERE id=?"
    parametry = (datetime.now().isoformat(timespec="seconds"), szablon_id)
    if conn is not None:
        conn.execute(zapytanie, parametry)
        return
    with polacz_baze(zmienia_dane=False) as polaczenie:
        polaczenie.execute(zapytanie, parametry)


def czy_szablon_od_razu(szablon) -> bool:
    """Koszt z kwotą zapisuje się jednym dotknięciem; reszta otwiera formularz."""
    return bool(szablon and szablon.get("rodzaj") == SZABLON_KOSZT and (szablon.get("dane") or {}).get("kwota"))


def ostrzezenie_szablonu_dzis(auto_id, szablon, data=None):
    """Zdanie, gdy dziś jest już identyczny koszt — podwójne dotknięcie nie dubluje go po cichu."""
    if not czy_szablon_od_razu(szablon):
        return None
    dane = szablon["dane"]
    return sprawdz_czy_koszt_duplikat(auto_id, data or datetime.now().strftime("%d.%m.%Y"),
                                      dane.get("nazwa") or szablon["nazwa"], dane["kwota"])


def zapisz_koszt_z_szablonu(auto_id, szablon_id, data=None) -> int | None:
    """Inny koszt z szablonu z kwotą: dzisiejsza data, autor i notatka z podpisem jak z
    formularza. Id nowego wpisu albo None (szablon bez kwoty, z innego auta, nie kosztu)."""
    szablon = pobierz_szablon(szablon_id)
    if not czy_szablon_od_razu(szablon) or szablon["auto_id"] != auto_id:
        return None
    dane = szablon["dane"]
    data = data or datetime.now().strftime("%d.%m.%Y")
    with polacz_baze() as conn:
        rekord_id = conn.execute(
            "INSERT INTO inne_koszty (auto_id, data, data_iso, kategoria, nazwa, kwota, tagi, dodane_przez) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (auto_id, data, na_iso(data), etykieta_kategorii_innych(dane.get("kategoria")),
             dane.get("nazwa") or szablon["nazwa"], dane["kwota"], dane.get("tagi") or "", pobierz_moje_imie()),
        ).lastrowid
        zanotuj_uzycie_szablonu(szablon_id, conn=conn)
    if dane.get("notatka"):
        zapisz_notatke("inne_koszty", rekord_id, dane["notatka"])
    return rekord_id


def cofnij_koszt_z_szablonu(koszt_id) -> bool:
    """„Cofnij” po zapisie jednym dotknięciem: koszt istniał kilka sekund, więc znika bez
    kosza; wysłany już do chmury zostawia nagrobek jak każde usunięcie."""
    wynik = usun_do_kosza("inne_koszty", [koszt_id], do_kosza=False)
    if not wynik:
        return False
    wynik["finalizuj"]()
    return True


__all__ = [
    "MAKS_DLUGOSC_NAZWY_SZABLONU",
    "POLA_SZABLONU",
    "SZABLONY_W_MENU",
    "SZABLON_KOSZT",
    "SZABLON_TANKOWANIE",
    "cofnij_koszt_z_szablonu",
    "czy_szablon_od_razu",
    "dane_szablonu_z_wpisu",
    "oczysc_dane_szablonu",
    "ostrzezenie_szablonu_dzis",
    "pobierz_szablon",
    "pobierz_szablony",
    "proponowana_nazwa_szablonu",
    "zanotuj_uzycie_szablonu",
    "zapisz_koszt_z_szablonu",
    "zapisz_szablon",
]
