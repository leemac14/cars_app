"""Historia cen części (M-15). Dziennik `ceny_czesci` trzyma zakupy, których pozycja
magazynu już nie pamięta; zakupy jednej części łączy `klucz_nazwy`, osobno dla pojazdu.

Tożsamość zakupu = (klucz nazwy, dzień): ta sama data to POPRAWKA, inna — NOWY zakup.
Bieżące ceny pozycji nie trafiają do dziennika migracją: `historia_cen_pojazdu` dokłada
je w locie, a dziennik dostaje je dopiero, gdy pozycja traci cenę — dwa telefony nie
dublują zakupów. Moduł leży PRZED `magazyn`."""

import sqlite3
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit

from date import na_iso
from .polaczenie import polacz_baze
from .pomocnicze import _na_liczbe, formatuj_liczba_eksport, klucz_nazwy, liczba_z_odmiana, normalizuj_nazwe
from .synchronizacja import czy_moge_zmieniac_rekord


# Od ilu procent w górę od pierwszego zapisanego zakupu część trafia do
# obserwacji „Części drożeją”. Niżej to zwykle inny sklep albo promocja,
# a nie podwyżka, o której warto mówić.
PROG_PODWYZKI_CENY = 20


# ============================================================================
#  ZAKUP — JEDEN WIERSZ DZIENNIKA
# ============================================================================


def _dzien(data):
    """Dzień zakupu do porównań: RRRR-MM-DD, gdy datę da się odczytać, inaczej
    to, co wpisano. Pusty napis = zakup bez daty."""
    tekst = str(data or "").strip()
    return na_iso(tekst) or tekst


def _zakup(nazwa, data, cena_jednostkowa, jednostka=None, ilosc=None, sklep=None):
    """Słownik zakupu gotowy do zapisu albo None, gdy nie ma czego zapamiętać:
    bez nazwy albo bez ceny. Zero też nie jest ceną — część dostana albo
    z gwarancji nie mówi nic o tym, ile kosztuje w sklepie."""
    cena = _na_liczbe(cena_jednostkowa)
    nazwa = normalizuj_nazwe(nazwa)
    if cena is None or cena <= 0 or not klucz_nazwy(nazwa):
        return None
    ilosc = _na_liczbe(ilosc)
    return {
        "nazwa": nazwa,
        "data": str(data or "").strip(),
        "cena_jednostkowa": round(cena, 4),
        "jednostka": str(jednostka or "szt"),
        "ilosc": round(ilosc, 4) if ilosc is not None and ilosc > 0 else None,
        "sklep": normalizuj_nazwe(sklep) or None,
    }


def _zakup_pozycji(pozycja, ilosc=None):
    """Bieżący zakup pozycji magazynu (słownik z kolumnami `magazyn_czesci`).
    Ilość zakupu podaje się osobno: stan na półce to nie to samo, co kupiono."""
    if not pozycja:
        return None
    return _zakup(pozycja.get("nazwa"), pozycja.get("data_zakupu"), pozycja.get("cena_jednostkowa"),
                  pozycja.get("jednostka"), ilosc, pozycja.get("sklep"))


def _znajdz_zakup(conn, auto_id, klucz, data):
    """Id wiersza dziennika z tym samym kluczem nazwy i dniem zakupu — albo None.
    Przy kilku (dwa telefony zapisały ten sam zakup przed synchronizacją)
    najnowszy."""
    dzien = _dzien(data)
    for zakup_id, nazwa, data_wiersza in conn.execute(
            "SELECT id, nazwa, data FROM ceny_czesci WHERE auto_id=? ORDER BY id DESC", (auto_id,)).fetchall():
        if _dzien(data_wiersza) == dzien and klucz_nazwy(nazwa) == klucz:
            return zakup_id
    return None


def _zapisz_zakup(conn, auto_id, zakup, zakup_id=None):
    """INSERT albo UPDATE jednego zakupu; zwraca jego id. Przy poprawce ilość
    zakupu zostaje taka, jaką dziennik już zna, jeśli nowej nie podano."""
    if zakup_id:
        conn.execute(
            "UPDATE ceny_czesci SET nazwa=?, data=?, data_iso=?, cena_jednostkowa=?, jednostka=?, "
            "ilosc=COALESCE(?, ilosc), sklep=? WHERE id=?",
            (zakup["nazwa"], zakup["data"], na_iso(zakup["data"]), zakup["cena_jednostkowa"],
             zakup["jednostka"], zakup["ilosc"], zakup["sklep"], zakup_id)
        )
        return zakup_id
    kursor = conn.execute(
        "INSERT INTO ceny_czesci (auto_id, nazwa, data, data_iso, cena_jednostkowa, jednostka, ilosc, sklep) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (auto_id, zakup["nazwa"], zakup["data"], na_iso(zakup["data"]), zakup["cena_jednostkowa"],
         zakup["jednostka"], zakup["ilosc"], zakup["sklep"])
    )
    return kursor.lastrowid


def zachowaj_zakup_pozycji(conn, auto_id, pozycja) -> None:
    """Dopisuje do dziennika bieżący zakup pozycji, jeśli dziennik go jeszcze nie
    zna — tuż przed tym, jak pozycja tę cenę straci (usunięcie, scalenie, nowy
    zakup). Tak trafiają do historii ceny wpisane przed wersją 48. Ilość zakupu
    jest wtedy nieznana: stan na półce to nie to, co kupiono."""
    zakup = _zakup_pozycji(pozycja)
    if not auto_id or not zakup:
        return
    if _znajdz_zakup(conn, auto_id, klucz_nazwy(zakup["nazwa"]), zakup["data"]) is None:
        _zapisz_zakup(conn, auto_id, zakup)


def _przenies_historie(conn, auto_id, klucz_stary, nowa_nazwa, czesc_id):
    """Zmiana nazwy pozycji zabiera jej historię pod nową nazwę — chyba że starą
    nosi jeszcze inna pozycja tego pojazdu; wtedy historia zostaje przy niej."""
    for (nazwa,) in conn.execute("SELECT nazwa FROM magazyn_czesci WHERE auto_id=? AND id<>?",
                                 (auto_id, czesc_id or -1)).fetchall():
        if klucz_nazwy(nazwa) == klucz_stary:
            return
    for zakup_id, nazwa in conn.execute("SELECT id, nazwa FROM ceny_czesci WHERE auto_id=?", (auto_id,)).fetchall():
        if klucz_nazwy(nazwa) == klucz_stary:
            conn.execute("UPDATE ceny_czesci SET nazwa=? WHERE id=?", (nowa_nazwa, zakup_id))


def zanotuj_zakup_czesci(conn, auto_id, przed, po) -> None:
    """Zapis pozycji magazynu → dziennik zakupów; w TEJ SAMEJ transakcji, po
    INSERT/UPDATE. `przed` (None przy nowej) i `po` — słowniki pozycji.
    - nowa z ceną → zakup (ilość = stan początkowy);
    - ta sama data → poprawka zakupu;
    - inna data → nowy zakup (ilość = przyrost stanu), poprzedni zostaje;
    - zmiana nazwy przenosi historię."""
    if not auto_id or not po:
        return
    klucz_po = klucz_nazwy(po.get("nazwa"))
    if przed is None:
        nowy = _zakup_pozycji(po, ilosc=po.get("ilosc"))
    else:
        klucz_przed = klucz_nazwy(przed.get("nazwa"))
        if klucz_przed and klucz_po and klucz_przed != klucz_po:
            _przenies_historie(conn, auto_id, klucz_przed, normalizuj_nazwe(po.get("nazwa")), przed.get("id"))
        przed = {**przed, "nazwa": po.get("nazwa")}
        nowy = _zakup_pozycji(po)
        nowy_dzien = _dzien(po.get("data_zakupu")) != _dzien(przed.get("data_zakupu"))
        # Pozycja traci dotychczasową cenę — bo to nowy zakup albo bo cenę
        # skasowano — więc dotychczasowa zostaje w historii.
        if nowy_dzien or nowy is None:
            zachowaj_zakup_pozycji(conn, auto_id, przed)
        if nowy and nowy_dzien:
            przyrost = (_na_liczbe(po.get("ilosc")) or 0.0) - (_na_liczbe(przed.get("ilosc")) or 0.0)
            nowy["ilosc"] = round(przyrost, 4) if przyrost > 0 else None
    if nowy:
        _zapisz_zakup(conn, auto_id, nowy, _znajdz_zakup(conn, auto_id, klucz_po, nowy["data"]))


# ============================================================================
#  HISTORIA — ODCZYT
# ============================================================================


def _kolejnosc_zakupu(punkt):
    """Od najstarszego. Cena bez daty z dziennika jest „kiedyś, przed resztą”
    (to stara cena pozycji, która daty nie miała), a bieżąca cena pozycji bez
    daty — „teraz”, za wszystkimi datowanymi."""
    if punkt["data_iso"]:
        return (1, punkt["data_iso"], punkt["id"] is None, punkt["id"] or 0)
    return (2 if punkt["obecna"] else 0, "", punkt["id"] is None, punkt["id"] or 0)


def historia_cen_pojazdu(auto_id) -> dict[str, list[dict[str, Any]]]:
    """{klucz_nazwy: [zakup, …]} od najstarszego. Zakup: id, ids, nazwa, data, data_iso,
    cena, jednostka, ilosc, sklep, obecna, magazyn_id. `obecna` — bieżąca cena pozycji
    (przy tym samym dniu wygrywa z dziennikiem); cena nieznana dziennikowi dochodzi jako
    punkt bez `id`; `ids` — wszystkie wiersze dziennika punktu (dubel z dwóch
    telefonów)."""
    if not auto_id:
        return {}
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        zakupy = conn.execute(
            "SELECT id, nazwa, data, data_iso, cena_jednostkowa, jednostka, ilosc, sklep "
            "FROM ceny_czesci WHERE auto_id=? ORDER BY id", (auto_id,)
        ).fetchall()
        pozycje = conn.execute(
            "SELECT id, nazwa, data_zakupu, cena_jednostkowa, jednostka, sklep "
            "FROM magazyn_czesci WHERE auto_id=? ORDER BY id", (auto_id,)
        ).fetchall()

    grupy = {}
    for r in zakupy:
        zakup = _zakup(r["nazwa"], r["data"], r["cena_jednostkowa"], r["jednostka"], r["ilosc"], r["sklep"])
        if not zakup:
            continue
        punkty = grupy.setdefault(klucz_nazwy(zakup["nazwa"]), [])
        dzien = _dzien(zakup["data"])
        blizniak = next((p for p in punkty if _dzien(p["data"]) == dzien
                         and p["cena"] == zakup["cena_jednostkowa"] and p["jednostka"] == zakup["jednostka"]), None)
        if blizniak:
            blizniak["ids"].append(r["id"])
            continue
        punkty.append({
            "id": r["id"], "ids": [r["id"]], "nazwa": zakup["nazwa"], "data": zakup["data"],
            "data_iso": r["data_iso"] or na_iso(zakup["data"]), "cena": zakup["cena_jednostkowa"],
            "jednostka": zakup["jednostka"], "ilosc": zakup["ilosc"], "sklep": zakup["sklep"],
            "obecna": False, "magazyn_id": None,
        })

    for p in pozycje:
        zakup = _zakup_pozycji(dict(p))
        if not zakup:
            continue
        punkty = grupy.setdefault(klucz_nazwy(zakup["nazwa"]), [])
        dzien = _dzien(zakup["data"])
        punkt = next((x for x in punkty if not x["obecna"] and _dzien(x["data"]) == dzien), None)
        if punkt is None:
            punkt = {"id": None, "ids": [], "ilosc": None, "sklep": None,
                     "data": zakup["data"], "data_iso": na_iso(zakup["data"])}
            punkty.append(punkt)
        punkt.update({
            "nazwa": zakup["nazwa"], "cena": zakup["cena_jednostkowa"], "jednostka": zakup["jednostka"],
            "sklep": zakup["sklep"] or punkt["sklep"], "obecna": True, "magazyn_id": p["id"],
        })

    for punkty in grupy.values():
        punkty.sort(key=_kolejnosc_zakupu)
    return grupy


def historia_cen_czesci(auto_id, nazwa, historia=None) -> list[dict[str, Any]]:
    """Zakupy jednej części (po klucz_nazwy), od najstarszego. `historia` —
    gotowy wynik historia_cen_pojazdu, żeby lista nie pytała bazy co kartę."""
    if historia is None:
        historia = historia_cen_pojazdu(auto_id)
    return list(historia.get(klucz_nazwy(nazwa), []))


def poprzednie_zakupy(punkty, czesc_id=None) -> list[dict[str, Any]]:
    """Zakupy sprzed bieżącego zakupu pozycji `czesc_id`, od najnowszego. Bez
    `czesc_id` (nowa pozycja w formularzu) — wszystkie znane zakupy tej nazwy."""
    punkty = list(punkty or [])
    if czesc_id is not None:
        wlasny = next((i for i, p in enumerate(punkty) if p["obecna"] and p["magazyn_id"] == czesc_id), None)
        if wlasny is not None:
            punkty = punkty[:wlasny]
    return list(reversed(punkty))


def zmiana_ceny(punkty, do=None) -> dict[str, Any] | None:
    """Zmiana ceny od pierwszego DATOWANEGO zakupu w tej samej jednostce do
    zakupu `do` (domyślnie ostatniego): {"od", "do", "proc"} albo None, gdy nie
    ma z czym porównać. Bieżąca cena bez daty to „teraz”, stara cena bez daty
    nie ma „kiedy”, więc nie bywa początkiem porównania."""
    punkty = list(punkty or [])
    if not punkty:
        return None
    do = do or punkty[-1]
    if not do.get("data_iso") and not do.get("obecna"):
        return None
    wczesniejsze = [p for p in punkty if p is not do and p.get("data_iso") and p["jednostka"] == do["jednostka"]
                    and (not do.get("data_iso") or p["data_iso"] < do["data_iso"])]
    if not wczesniejsze:
        return None
    od = wczesniejsze[0]
    return {"od": od, "do": do, "proc": round((do["cena"] - od["cena"]) / od["cena"] * 100, 1)}


def najtanszy_zakup(punkty) -> dict[str, Any] | None:
    """Najtańszy zakup w jednostce ostatniego — przy remisie najnowszy. None,
    gdy porównywać nie ma czego (mniej niż dwa zakupy w tej jednostce)."""
    punkty = list(punkty or [])
    if not punkty:
        return None
    jednostka = punkty[-1]["jednostka"]
    porownywalne = [p for p in punkty if p["jednostka"] == jednostka]
    if len(porownywalne) < 2:
        return None
    return min(reversed(porownywalne), key=lambda p: p["cena"])


def podwyzki_cen_czesci(auto_id, prog=PROG_PODWYZKI_CENY, historia=None) -> list[dict[str, Any]]:
    """Części z magazynu, które od pierwszego zapisanego zakupu podrożały co
    najmniej o `prog` procent — od największej podwyżki. Element: {"nazwa",
    "od", "do", "proc"}. Tylko części, które w magazynie wciąż są: o tej, której
    się już nie kupuje, nie ma po co mówić."""
    if historia is None:
        historia = historia_cen_pojazdu(auto_id)
    wynik = []
    for punkty in historia.values():
        if not any(p["obecna"] for p in punkty):
            continue
        zmiana = zmiana_ceny(punkty)
        if zmiana and zmiana["proc"] >= prog:
            wynik.append({"nazwa": zmiana["do"]["nazwa"], **zmiana})
    wynik.sort(key=lambda z: -z["proc"])
    return wynik


def tekst_ceny_zakupu(punkt, waluta) -> str:
    """„45,00 zł/szt” — do zdań warstwy danych (obserwacje). Groszowe ceny
    (mililitr, gram) z czterema miejscami po przecinku."""
    cena = punkt["cena"]
    return f"{formatuj_liczba_eksport(cena, 4 if 0 < abs(cena) < 1 else 2)} {waluta}/{punkt['jednostka']}"


def odstep_zakupow(od, do, dzis=None) -> str:
    """„2 lata wcześniej”, „ponad rok wcześniej”, „3 miesiące wcześniej” —
    ile minęło między zakupami. Zakup bez daty po stronie `do` to dzisiaj."""
    try:
        poczatek = date.fromisoformat(od["data_iso"])
        koniec = date.fromisoformat(do["data_iso"]) if do.get("data_iso") else (dzis or datetime.now().date())
    except (TypeError, ValueError):
        return "wcześniej"
    miesiecy = (koniec.year - poczatek.year) * 12 + (koniec.month - poczatek.month)
    if koniec.day < poczatek.day:
        miesiecy -= 1
    if miesiecy < 1:
        dni = max(0, (koniec - poczatek).days)
        if dni == 0:
            return "tego samego dnia"
        return "dzień wcześniej" if dni == 1 else f"{liczba_z_odmiana(dni, 'dzień', 'dni', 'dni')} wcześniej"
    if miesiecy < 12:
        return "miesiąc wcześniej" if miesiecy == 1 else f"{liczba_z_odmiana(miesiecy, 'miesiąc', 'miesiące', 'miesięcy')} wcześniej"
    lat = miesiecy // 12
    slownie = "rok" if lat == 1 else liczba_z_odmiana(lat, "rok", "lata", "lat")
    return f"{'ponad ' if miesiecy % 12 else ''}{slownie} wcześniej"


# ============================================================================
#  ZAPIS Z EKRANÓW — „KUPIŁEM PONOWNIE”, „DOPISZ CENĘ”
# ============================================================================


def kup_ponownie(czesc_id, ilosc, cena_jednostkowa, sklep=None, data=None) -> dict[str, Any] | None:
    """Kolejny zakup części z magazynu: stan rośnie o `ilosc`, a cena, data i sklep
    pozycji stają się tymi z TEGO zakupu (ostatnia cena, nie średnia); poprzedni zostaje
    w historii. Zwraca {auto_id, stan, dodano} albo None."""
    ilosc = _na_liczbe(ilosc)
    cena = _na_liczbe(cena_jednostkowa)
    if not czesc_id or ilosc is None or ilosc <= 0 or cena is None or cena <= 0:
        return None
    data = str(data or "").strip() or datetime.now().strftime("%d.%m.%Y")

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        w = conn.execute(
            "SELECT id, auto_id, nazwa, ilosc, jednostka, cena, cena_jednostkowa, data_zakupu, sklep "
            "FROM magazyn_czesci WHERE id=?", (czesc_id,)
        ).fetchone()
    if not w or not czy_moge_zmieniac_rekord(w["auto_id"], "magazyn_czesci"):
        return None
    przed = dict(w)
    auto_id = przed["auto_id"]
    sklep = dopasuj_sklep(auto_id, sklep) if normalizuj_nazwe(sklep) else przed["sklep"]
    stan = round((_na_liczbe(przed["ilosc"]) or 0.0) + ilosc, 4)

    with polacz_baze() as conn:
        conn.execute(
            "UPDATE magazyn_czesci SET ilosc=?, cena=?, cena_jednostkowa=?, data_zakupu=?, sklep=? WHERE id=?",
            (stan, round(ilosc * cena, 2), round(cena, 4), data, sklep, czesc_id)
        )
        nowy = _zakup(przed["nazwa"], data, cena, przed["jednostka"], ilosc, sklep)
        if nowy is None:
            return {"auto_id": auto_id, "stan": stan, "dodano": ilosc}
        klucz = klucz_nazwy(przed["nazwa"])
        if _dzien(przed["data_zakupu"]) != _dzien(data):
            zachowaj_zakup_pozycji(conn, auto_id, przed)
            zakup_id = _znajdz_zakup(conn, auto_id, klucz, data)
        else:
            # Drugi zakup tego samego dnia dokłada się do pierwszego: jeden dzień,
            # jeden punkt na krzywej, a ilość — razem.
            zakup_id = _znajdz_zakup(conn, auto_id, klucz, data)
            if zakup_id:
                (bylo,) = conn.execute("SELECT ilosc FROM ceny_czesci WHERE id=?", (zakup_id,)).fetchone()
                if _na_liczbe(bylo):
                    nowy["ilosc"] = round(_na_liczbe(bylo) + ilosc, 4)
        _zapisz_zakup(conn, auto_id, nowy, zakup_id)
    return {"auto_id": auto_id, "stan": stan, "dodano": ilosc}


def dopisz_cene_czesci(auto_id, nazwa, data, cena_jednostkowa, jednostka="szt", sklep=None,
                       ilosc=None) -> int | None:
    """Zakup ze starego paragonu dopisany ręcznie w arkuszu historii cen — żeby
    trend było widać od razu, a nie dopiero po kolejnych zakupach. Ten sam dzień
    co zakup już zapisany poprawia tamten zamiast dublować punkt. Bez daty nie
    przyjmujemy: zakup bez „kiedy” niczego na krzywej nie pokaże."""
    zakup = _zakup(nazwa, data, cena_jednostkowa, jednostka, ilosc, sklep)
    if not auto_id or not zakup or not na_iso(zakup["data"]):
        return None
    if not czy_moge_zmieniac_rekord(auto_id, "ceny_czesci"):
        return None
    if zakup["sklep"]:
        zakup["sklep"] = dopasuj_sklep(auto_id, zakup["sklep"])
    with polacz_baze() as conn:
        return _zapisz_zakup(conn, auto_id, zakup,
                             _znajdz_zakup(conn, auto_id, klucz_nazwy(zakup["nazwa"]), zakup["data"]))


# ============================================================================
#  SKLEP I LINK
# ============================================================================


def sklepy_czesci(auto_id) -> list[str]:
    """Sklepy, w których kupowano części do tego auta — z pozycji magazynu
    i z historii cen, od najczęstszego. Warianty zapisu tego samego sklepu są
    scalane po klucz_nazwy; wygrywa pisownia użyta najczęściej."""
    if not auto_id:
        return []
    with polacz_baze() as conn:
        wiersze = conn.execute(
            "SELECT sklep FROM magazyn_czesci WHERE auto_id=? AND sklep IS NOT NULL AND TRIM(sklep)<>'' "
            "UNION ALL SELECT sklep FROM ceny_czesci WHERE auto_id=? AND sklep IS NOT NULL AND TRIM(sklep)<>''",
            (auto_id, auto_id)
        ).fetchall()
    grupy = {}
    for (sklep,) in wiersze:
        pisownia = normalizuj_nazwe(sklep)
        klucz = klucz_nazwy(pisownia)
        if not klucz:
            continue
        grupa = grupy.setdefault(klucz, {"razem": 0, "warianty": {}})
        grupa["razem"] += 1
        grupa["warianty"][pisownia] = grupa["warianty"].get(pisownia, 0) + 1
    nazwy = [(max(g["warianty"].items(), key=lambda w: (w[1], w[0]))[0], g["razem"]) for g in grupy.values()]
    nazwy.sort(key=lambda n: (-n[1], n[0].lower()))
    return [nazwa for nazwa, _ in nazwy]


def dopasuj_sklep(auto_id, tekst):
    """Istniejąca pisownia sklepu, jeśli wpisano tylko inny wariant zapisu
    („inter cars” → „Inter Cars”) — jak stacje paliw. None przy pustym."""
    czysty = normalizuj_nazwe(tekst)
    if not czysty:
        return None
    klucz = klucz_nazwy(czysty)
    return next((nazwa for nazwa in sklepy_czesci(auto_id) if klucz_nazwy(nazwa) == klucz), czysty)


def normalizuj_link(tekst):
    """Adres strony do zapisu: bez spacji na brzegach, z https:// przed gołą
    domeną („allegro.pl/oferta/…” też się wkleja). Pusty → None."""
    adres = str(tekst or "").strip()
    if not adres:
        return None
    if "://" not in adres:
        adres = "https://" + adres.lstrip("/")
    return adres


def blad_linku(tekst):
    """Opis błędu adresu strony albo None, gdy adres jest w porządku (pusty też)."""
    adres = normalizuj_link(tekst)
    if adres is None:
        return None
    if any(znak.isspace() for znak in adres):
        return "Adres strony nie może zawierać spacji"
    try:
        czesci = urlsplit(adres)
    except ValueError:
        return "To nie wygląda na adres strony"
    if czesci.scheme.lower() not in ("http", "https"):
        return "Adres strony zaczyna się od http:// albo https://"
    if "." not in (czesci.hostname or "").strip("."):
        return "To nie wygląda na adres strony"
    return None


def domena_linku(adres):
    """„allegro.pl” z pełnego adresu — podpis linku, gdy sklepu nie wpisano."""
    try:
        host = (urlsplit(normalizuj_link(adres) or "").hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


__all__ = [
    "PROG_PODWYZKI_CENY",
    "blad_linku",
    "domena_linku",
    "dopasuj_sklep",
    "dopisz_cene_czesci",
    "historia_cen_czesci",
    "historia_cen_pojazdu",
    "kup_ponownie",
    "najtanszy_zakup",
    "normalizuj_link",
    "odstep_zakupow",
    "podwyzki_cen_czesci",
    "poprzednie_zakupy",
    "sklepy_czesci",
    "tekst_ceny_zakupu",
    "zachowaj_zakup_pozycji",
    "zanotuj_zakup_czesci",
    "zmiana_ceny",
]
