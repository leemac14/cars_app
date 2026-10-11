"""Awarie kontra eksploatacja: rodzaj naprawy wpisu i wizyty (migracja 52), udział awarii w
koszcie serwisu, odstępy między awariami, sygnał „auto zaczyna się sypać” i oznaczanie napraw
bez rodzaju. Naprawa = wizyta albo wpis spoza wizyty; pozycja wizyty ma rodzaj wizyty."""

from datetime import date, datetime, timedelta
from typing import Any

from .polaczenie import polacz_baze
from .daty import warunek_zakresu_dat
from .ustawienia import pobierz_moje_imie
from .synchronizacja import czy_moge_edytowac_w_tabeli, czy_moge_zmieniac_rekord, czy_tylko_podglad

SERWIS_PLANOWE = "planowe"
SERWIS_AWARIA = "awaria"
SERWIS_MODERNIZACJA = "modernizacja"
RODZAJE_SERWISU = (SERWIS_PLANOWE, SERWIS_AWARIA, SERWIS_MODERNIZACJA)
ETYKIETY_RODZAJU_SERWISU = {
    SERWIS_PLANOWE: "Planowe",
    SERWIS_AWARIA: "Awaria",
    SERWIS_MODERNIZACJA: "Modernizacja",
}
ETYKIETA_BEZ_RODZAJU = "Bez rodzaju"

# Sygnał „auto zaczyna się sypać” — obserwacja w Analizie i kafelek kokpitu.
PROG_NIEOZNACZONYCH = 0.2  # okres z większą częścią kosztu bez rodzaju się nie porównuje
PROG_WZROSTU_UDZIALU = 15.0  # punkty procentowe udziału awarii, rok do roku
PROG_UDZIALU_AWARII = 25.0  # i co najmniej tyle procent kosztu serwisu teraz
PROG_SKRACANIA_ODSTEPOW = 0.6  # dwa ostatnie odstępy najwyżej tyle co średnio wcześniejsze

TABELE_NAPRAW = ("wizyty", "historia")


def _bez_rodzaju(kolumna):
    znane = ", ".join(f"'{r}'" for r in RODZAJE_SERWISU)
    return f"({kolumna} IS NULL OR {kolumna} NOT IN ({znane}))"


def rodzaj_serwisu(wartosc) -> str | None:
    """Rodzaj z bazy albo pola jako jeden z RODZAJE_SERWISU; pusty i nieznany — None."""
    tekst = str(wartosc or "").strip().lower()
    return tekst if tekst in RODZAJE_SERWISU else None


def etykieta_rodzaju_serwisu(wartosc) -> str:
    rodzaj = rodzaj_serwisu(wartosc)
    return ETYKIETY_RODZAJU_SERWISU[rodzaj] if rodzaj else ETYKIETA_BEZ_RODZAJU


def domyslny_rodzaj_serwisu(zadania_ids, conn=None) -> str | None:
    """Podpowiedź dla nowej naprawy: „planowe”, gdy KAŻDY podzespół ma interwał (km albo
    miesiące); bez podzespołów albo z choć jednym bez interwału — None."""
    ids = sorted({int(z) for z in (zadania_ids or ()) if z})
    if not ids:
        return None
    zapytanie = (f"SELECT COUNT(*) FROM zadania WHERE id IN ({','.join('?' * len(ids))}) "
                 "AND (COALESCE(interwal_km, 0) > 0 OR COALESCE(interwal_miesiace, 0) > 0)")
    if conn is not None:
        ile = conn.execute(zapytanie, ids).fetchone()[0]
    else:
        with polacz_baze() as polaczenie:
            ile = polaczenie.execute(zapytanie, ids).fetchone()[0]
    return SERWIS_PLANOWE if ile == len(ids) else None


def _naprawy(conn, auto_id, od_data=None, do_data=None):
    """Naprawy z [od, do] od najstarszej: (data_iso, przebieg km, kwota, rodzaj). Pozycje
    wizyty pomijane — koszt i rodzaj niesie wizyta (jak `_wiersze_kosztow`)."""
    warunek_w, parametry_w = warunek_zakresu_dat("data_iso", od_data, do_data)
    warunek_h, parametry_h = warunek_zakresu_dat("h.data_iso", od_data, do_data)
    wiersze = conn.execute(
        f"SELECT data_iso, przebieg, koszt_calkowity, rodzaj, id FROM wizyty WHERE auto_id=?{warunek_w} "
        "UNION ALL SELECT h.data_iso, h.przebieg, h.cena, h.rodzaj, h.id FROM historia h "
        f"JOIN zadania z ON h.zadanie_id=z.id WHERE z.auto_id=? AND h.wizyta_id IS NULL{warunek_h} "
        "ORDER BY 1, 5", [auto_id, *parametry_w, auto_id, *parametry_h]).fetchall()
    return [(d, int(p or 0), max(0.0, float(k or 0.0)), rodzaj_serwisu(r)) for d, p, k, r, _id in wiersze]


def _dni_awarii(naprawy):
    """Awarie jako zdarzenia — naprawy z jednego dnia to jedna awaria: [(dzień, licznik km
    albo 0)], od najstarszej."""
    dni = {}
    for data_iso, przebieg, _kwota, rodzaj in naprawy:
        if rodzaj == SERWIS_AWARIA and data_iso:
            dni[data_iso] = max(dni.get(data_iso, 0), przebieg)
    return [(date.fromisoformat(d), km) for d, km in sorted(dni.items())]


def awarie_i_eksploatacja(auto_id, od_data=None, do_data=None, dzis=None) -> dict[str, Any]:
    """Serwis z [od, do] wg rodzaju naprawy. `rodzaje`: {rodzaj albo None: {kwota, liczba,
    udzial}} (% kosztu serwisu, None bez kosztu); `awarie` — dni z awarią; `odstep_dni` /
    `odstep_km` — średni odstęp (od dwóch awarii); `odstep_ostatnich_dni` kontra
    `odstep_wczesniej_dni` — dwa ostatnie odstępy i reszta (od czterech); `naprawy` —
    [(data_iso, kwota, rodzaj)] do słupków."""
    dzis = dzis or datetime.now().date()
    rodzaje = {r: {"kwota": 0.0, "liczba": 0, "udzial": None} for r in (*RODZAJE_SERWISU, None)}
    wynik = {"razem": 0.0, "rodzaje": rodzaje, "udzial_awarii": None, "awarie": 0,
             "odstep_dni": None, "odstep_km": None, "odstep_ostatnich_dni": None,
             "odstep_wczesniej_dni": None, "ostatnia_awaria": None, "dni_od_awarii": None,
             "nieoznaczone": 0, "naprawy": []}
    if not auto_id:
        return wynik
    with polacz_baze() as conn:
        naprawy = _naprawy(conn, auto_id, od_data, do_data)

    for _data, _km, kwota, rodzaj in naprawy:
        rodzaje[rodzaj]["kwota"] += kwota
        rodzaje[rodzaj]["liczba"] += 1
    razem = sum(g["kwota"] for g in rodzaje.values())
    for grupa in rodzaje.values():
        grupa["udzial"] = grupa["kwota"] / razem * 100 if razem > 0 else None
        grupa["kwota"] = round(grupa["kwota"], 2)
    wynik.update(razem=round(razem, 2), udzial_awarii=rodzaje[SERWIS_AWARIA]["udzial"],
                 nieoznaczone=rodzaje[None]["liczba"],
                 naprawy=[(d, kwota, rodzaj) for d, _km, kwota, rodzaj in naprawy if d])

    dni = _dni_awarii(naprawy)
    wynik["awarie"] = len(dni)
    if dni:
        wynik["ostatnia_awaria"] = dni[-1][0]
        wynik["dni_od_awarii"] = max(0, (dzis - dni[-1][0]).days)
    odstepy = [(b - a).days for (a, _ka), (b, _kb) in zip(dni, dni[1:])]
    if odstepy:
        wynik["odstep_dni"] = sum(odstepy) / len(odstepy)
    if len(odstepy) >= 3:
        wynik["odstep_ostatnich_dni"] = sum(odstepy[-2:]) / 2
        wynik["odstep_wczesniej_dni"] = sum(odstepy[:-2]) / len(odstepy[:-2])
    liczniki = [km for _d, km in dni if km > 0]
    if len(liczniki) >= 2 and liczniki[-1] > liczniki[0]:
        wynik["odstep_km"] = (liczniki[-1] - liczniki[0]) / (len(liczniki) - 1)
    return wynik


def _porownywalny(okres):
    return okres["razem"] > 0 and okres["rodzaje"][None]["kwota"] <= okres["razem"] * PROG_NIEOZNACZONYCH


def sygnal_awarii(auto_id, dzis=None) -> dict[str, Any]:
    """Udział awarii z ostatnich 12 miesięcy (`teraz`) wobec 12 poprzednich (`wczesniej`) —
    None, gdy okres ma ponad PROG_NIEOZNACZONYCH kosztu bez rodzaju; `rosnie` / `maleje` wg
    progów; `skracaja_sie` — dwa ostatnie odstępy z całej historii wobec wcześniejszych
    (ostatnia awaria w ostatnim roku, naprawy między pierwszą a ostatnią oznaczone). `rok` —
    `awarie_i_eksploatacja` 12 miesięcy; `ostatnia_awaria` i `napraw_razem` — z całej historii."""
    dzis = dzis or datetime.now().date()
    teraz = awarie_i_eksploatacja(auto_id, dzis - timedelta(days=364), dzis, dzis)
    wczesniej = awarie_i_eksploatacja(auto_id, dzis - timedelta(days=729), dzis - timedelta(days=365), dzis)
    calosc = awarie_i_eksploatacja(auto_id, None, dzis, dzis)
    wynik = {"teraz": teraz["udzial_awarii"] if _porownywalny(teraz) else None,
             "wczesniej": wczesniej["udzial_awarii"] if _porownywalny(wczesniej) else None,
             "zmiana": None, "awarie_teraz": teraz["awarie"], "rosnie": False, "maleje": False,
             "skracaja_sie": False, "odstep_ostatnich_dni": calosc["odstep_ostatnich_dni"],
             "odstep_wczesniej_dni": calosc["odstep_wczesniej_dni"], "rok": teraz,
             "ostatnia_awaria": calosc["ostatnia_awaria"], "dni_od_awarii": calosc["dni_od_awarii"],
             "napraw_razem": sum(g["liczba"] for g in calosc["rodzaje"].values())}
    if wynik["teraz"] is not None and wynik["wczesniej"] is not None:
        zmiana = wynik["teraz"] - wynik["wczesniej"]
        wynik["zmiana"] = zmiana
        wynik["rosnie"] = (zmiana >= PROG_WZROSTU_UDZIALU and wynik["teraz"] >= PROG_UDZIALU_AWARII
                           and teraz["awarie"] >= 2)
        wynik["maleje"] = -zmiana >= PROG_WZROSTU_UDZIALU and wynik["wczesniej"] >= PROG_UDZIALU_AWARII

    ostatnie, wczesniejsze = calosc["odstep_ostatnich_dni"], calosc["odstep_wczesniej_dni"]
    if ostatnie is not None and wczesniejsze and (calosc["dni_od_awarii"] or 0) <= 365:
        daty_awarii = [d for d, _k, r in calosc["naprawy"] if r == SERWIS_AWARIA]
        miedzy = [r for d, _k, r in calosc["naprawy"] if daty_awarii[0] <= d <= daty_awarii[-1]]
        oznaczone = sum(1 for r in miedzy if r) >= len(miedzy) * (1 - PROG_NIEOZNACZONYCH)
        wynik["skracaja_sie"] = oznaczone and ostatnie <= wczesniejsze * PROG_SKRACANIA_ODSTEPOW
    return wynik


def naprawy_bez_rodzaju(auto_id) -> list[dict[str, Any]]:
    """Naprawy bez rodzaju, które ta rola może zmienić, od najnowszej: [{tabela, id, data,
    data_iso, kwota, opis, wykonawca, sugestia}]; `opis` — podzespoły, `sugestia` —
    `domyslny_rodzaj_serwisu` jej podzespołów."""
    if not auto_id or czy_tylko_podglad(auto_id):
        return []
    interwal = "(COALESCE(z.interwal_km, 0) > 0 OR COALESCE(z.interwal_miesiace, 0) > 0)"
    with polacz_baze() as conn:
        wiersze = conn.execute(
            "SELECT 'wizyty', w.id, w.data, w.data_iso, w.koszt_calkowity, w.wykonawca, w.dodane_przez, "
            f"GROUP_CONCAT(z.nazwa, ', '), COUNT(z.id), SUM(CASE WHEN {interwal} THEN 1 ELSE 0 END) "
            "FROM wizyty w LEFT JOIN historia h ON h.wizyta_id = w.id LEFT JOIN zadania z ON h.zadanie_id = z.id "
            f"WHERE w.auto_id=? AND {_bez_rodzaju('w.rodzaj')} GROUP BY w.id "
            "UNION ALL SELECT 'historia', h.id, h.data, h.data_iso, h.cena, h.wykonawca, h.dodane_przez, "
            f"z.nazwa, 1, CASE WHEN {interwal} THEN 1 ELSE 0 END "
            "FROM historia h JOIN zadania z ON h.zadanie_id = z.id "
            f"WHERE z.auto_id=? AND h.wizyta_id IS NULL AND {_bez_rodzaju('h.rodzaj')}",
            (auto_id, auto_id)).fetchall()
    naprawy = [
        {"tabela": tabela, "id": rid, "data": data or "", "data_iso": data_iso,
         "kwota": max(0.0, float(kwota or 0.0)), "opis": str(nazwy or "").strip(),
         "wykonawca": str(wykonawca or "").strip(),
         "sugestia": SERWIS_PLANOWE if podzespolow and z_interwalem == podzespolow else None}
        for tabela, rid, data, data_iso, kwota, wykonawca, autor, nazwy, podzespolow, z_interwalem in wiersze
        if czy_moge_zmieniac_rekord(auto_id, tabela, autor)
    ]
    naprawy.sort(key=lambda n: (n["data_iso"] or "", n["tabela"], n["id"]), reverse=True)
    return naprawy


def ustaw_rodzaj_napraw(auto_id, naprawy, rodzaj) -> int:
    """Rodzaj dla [(tabela, id)] jednym zapisem; wizyta przenosi go na swoje pozycje. Pomija
    naprawy innego pojazdu i te, których ta rola nie zmienia. Zwraca liczbę zmienionych."""
    rodzaj = rodzaj_serwisu(rodzaj)
    do_zmiany = [(t, int(i)) for t, i in naprawy or () if t in TABELE_NAPRAW and i
                 and czy_moge_edytowac_w_tabeli(auto_id, t, int(i))]
    if not auto_id or not do_zmiany:
        return 0
    kto, kiedy = pobierz_moje_imie(), datetime.now().strftime("%d.%m.%Y %H:%M")
    zmienione = 0
    with polacz_baze() as conn:
        for tabela, rekord_id in do_zmiany:
            if tabela == "wizyty":
                kursor = conn.execute(
                    "UPDATE wizyty SET rodzaj=?, zmodyfikowane_przez=?, data_modyfikacji=? WHERE id=? AND auto_id=?",
                    (rodzaj, kto, kiedy, rekord_id, auto_id))
                if kursor.rowcount:
                    conn.execute("UPDATE historia SET rodzaj=? WHERE wizyta_id=?", (rodzaj, rekord_id))
            else:
                kursor = conn.execute(
                    "UPDATE historia SET rodzaj=?, zmodyfikowane_przez=?, data_modyfikacji=? WHERE id=? "
                    "AND zadanie_id IN (SELECT id FROM zadania WHERE auto_id=?)",
                    (rodzaj, kto, kiedy, rekord_id, auto_id))
            zmienione += kursor.rowcount
    return zmienione


__all__ = [
    "ETYKIETA_BEZ_RODZAJU",
    "ETYKIETY_RODZAJU_SERWISU",
    "PROG_NIEOZNACZONYCH",
    "PROG_SKRACANIA_ODSTEPOW",
    "PROG_UDZIALU_AWARII",
    "PROG_WZROSTU_UDZIALU",
    "RODZAJE_SERWISU",
    "SERWIS_AWARIA",
    "SERWIS_MODERNIZACJA",
    "SERWIS_PLANOWE",
    "TABELE_NAPRAW",
    "_bez_rodzaju",
    "_dni_awarii",
    "_naprawy",
    "_porownywalny",
    "awarie_i_eksploatacja",
    "domyslny_rodzaj_serwisu",
    "etykieta_rodzaju_serwisu",
    "naprawy_bez_rodzaju",
    "rodzaj_serwisu",
    "sygnal_awarii",
    "ustaw_rodzaj_napraw",
]
