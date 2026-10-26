"""Zmiana opon jako zdarzenie: dzień, licznik, koszt i warsztat → montaż kompletu, dziennik okresów
montażu, wpis w Serwisie (podzespół opon) albo Inny koszt, przesunięcie przypomnienia o sezonowej
zmianie; „Cofnij” wraca do stanu sprzed zmiany. Liczenie, pomiary i okresy — db/opony.py."""

import sqlite3
from datetime import datetime, timedelta
from typing import Any

from date import na_iso, parsuj_date

from .stale import KATEGORIA_INNE_DOMYSLNA, OKRES_ZMIANY_OPON_DNI, OSIE_MONTAZU, SEZONY_OPON, SEZONY_PRZELACZALNE
from .stale import TYP_CYKLICZNY_OPONY
from .polaczenie import polacz_baze
from .pomocnicze import _na_liczbe, normalizuj_nazwe
from .ustawienia import pobierz_moje_imie
from .notatki import przytnij_notatke
from .synchronizacja import czy_moge_dodawac
from .przebieg import aktualizuj_najnowszy_wpis, pobierz_aktualny_przebieg, szacuj_przebieg_w_dniu
from .kosz_wpisow import usun_do_kosza
from .awarie import domyslny_rodzaj_serwisu
from .opony import flagi_montazu, zapisz_okresy_montazu


def podzespol_opon(conn, auto_id) -> int | None:
    """Podzespół, pod którym zmiana opon trafia do Serwisu: oznaczony jako opony, najpierw „wymiana”."""
    w = conn.execute(
        "SELECT id FROM zadania WHERE auto_id=? AND dotyczy_opon=1 "
        "ORDER BY CASE WHEN lower(nazwa) LIKE '%wymian%' THEN 0 ELSE 1 END, id LIMIT 1", (auto_id,)).fetchone()
    return w[0] if w else None


def _flagi_po(przed, zestaw_id, os_montazu):
    """Zamontowane po założeniu kompletu na oś — jak oznacz_zamontowany_zestaw: „Wszystkie” zdejmuje
    resztę, jedna oś zdejmuje komplety z tej osi i z całego auta."""
    if os_montazu == "Wszystkie":
        return {zestaw_id: "Wszystkie"}
    po = {z: o for z, o in przed.items() if z != zestaw_id and o not in (os_montazu, "Wszystkie")}
    po[zestaw_id] = os_montazu
    return po


def zmien_opony(auto_id, zestaw_id, dane=None) -> dict[str, Any] | None:
    """Zakłada komplet na oś (`dane`: os, data, przebieg km, koszt, wykonawca, notatka, do_serwisu —
    domyślnie tak, historia_id — istniejący wpis zmiany, np. z wizyty, przypomnienie_id). Zamyka
    okresy zdjętych, otwiera okres założonego, zapisuje zmianę w Serwisie (bez podzespołu opon —
    koszt jako Inny koszt) i przy zmianie pory roku przesuwa przypomnienie od dnia zmiany. Zwraca
    ok, z, na, zestaw_id, opis_zestawu, historia_id, koszt_id, termin_przesuniety, nastepna_data,
    cofniecie (dla cofnij_zmiane_opon); {"ok": False, "powod": "juz_na_aucie"}; None — brak prawa,
    kompletu albo dnia."""
    dane = dane or {}
    if not auto_id or not zestaw_id or not czy_moge_dodawac(auto_id):
        return None
    os_montazu = dane.get("os") if dane.get("os") in OSIE_MONTAZU else "Wszystkie"
    data = str(dane.get("data") or datetime.now().strftime("%d.%m.%Y")).strip()
    dzien = parsuj_date(data)
    if dzien == datetime.min.date():
        return None
    przebieg = _na_liczbe(dane.get("przebieg"))
    przebieg = (int(przebieg) if przebieg and przebieg > 0
                else szacuj_przebieg_w_dniu(auto_id, data) or pobierz_aktualny_przebieg(auto_id) or None)
    koszt = _na_liczbe(dane.get("koszt"))
    koszt = round(koszt, 2) if koszt and koszt > 0 else None
    wykonawca = normalizuj_nazwe(dane.get("wykonawca")) or None
    notatka = przytnij_notatke(dane.get("notatka")) or None
    historia_id = dane.get("historia_id") or None
    przypomnienie_id = dane.get("przypomnienie_id") or None
    ja, podpis = pobierz_moje_imie() or None, datetime.now().strftime("%d.%m.%Y %H:%M")

    zadanie = utworzony_wpis = utworzony_koszt = None
    przesuniete = []
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        zestaw = c.execute("SELECT id, sezon, marka_model, rozmiar FROM zestawy_opon WHERE id=? AND auto_id=?",
                           (zestaw_id, auto_id)).fetchone()
        if not zestaw:
            return None
        sezon = str(zestaw["sezon"] or "")
        przed = flagi_montazu(conn, auto_id)
        if przed.get(zestaw_id) == os_montazu:
            return {"ok": False, "powod": "juz_na_aucie", "na": sezon}
        po = _flagi_po(przed, zestaw_id, os_montazu)
        sezony_przed = {str(r[0] or "") for r in c.execute(
            f"SELECT sezon FROM zestawy_opon WHERE id IN ({','.join('?' * len(przed)) or 'NULL'})", tuple(przed))}

        for z in przed:
            if z not in po:
                c.execute("UPDATE zestawy_opon SET zamontowane=0, os_montazu='Wszystkie' WHERE id=?", (z,))
        for z, o in po.items():
            if przed.get(z) != o:
                c.execute("UPDATE zestawy_opon SET zamontowane=1, os_montazu=? WHERE id=?", (o, z))
        okresy = zapisz_okresy_montazu(conn, auto_id, przed, po, data, przebieg)
        montaz_id = next((m for m in okresy["otwarte"]
                          if c.execute("SELECT zestaw_id FROM montaze_opon WHERE id=?", (m,)).fetchone()[0] == zestaw_id),
                         None)

        if not historia_id and dane.get("do_serwisu", True):
            zadanie = podzespol_opon(c, auto_id)
            if zadanie:
                rodzaj = domyslny_rodzaj_serwisu([zadanie], conn=conn)
                utworzony_wpis = c.execute(
                    "INSERT INTO historia (wizyta_id, zadanie_id, data, data_iso, przebieg, cena, wykonawca, kategoria, "
                    "rodzaj, dodane_przez, notatka, notatka_autor, notatka_data) VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (zadanie, data, na_iso(data), przebieg or 0, koszt or 0.0, wykonawca or "", sezon or None, rodzaj,
                     ja, notatka, ja if notatka else None, podpis if notatka else None)).lastrowid
                historia_id = utworzony_wpis
            elif koszt:
                utworzony_koszt = c.execute(
                    "INSERT INTO inne_koszty (auto_id, data, data_iso, kategoria, nazwa, kwota, dodane_przez, notatka, "
                    "notatka_autor, notatka_data) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (auto_id, data, na_iso(data), KATEGORIA_INNE_DOMYSLNA,
                     f"Zmiana opon na {sezon.lower()}" if sezon else "Zmiana opon", koszt, ja, notatka,
                     ja if notatka else None, podpis if notatka else None)).lastrowid
        if montaz_id and (historia_id or utworzony_koszt):
            c.execute("UPDATE montaze_opon SET historia_id=?, koszt_id=? WHERE id=?",
                      (historia_id, utworzony_koszt, montaz_id))

        zmiana_pory = os_montazu == "Wszystkie" and sezon in SEZONY_PRZELACZALNE and sezon not in sezony_przed
        if zmiana_pory or przypomnienie_id:
            for r in c.execute("SELECT id, nastepna_data, okres_dni FROM wydatki_cykliczne WHERE auto_id=? AND typ=?",
                               (auto_id, TYP_CYKLICZNY_OPONY)).fetchall():
                if przypomnienie_id and r["id"] != przypomnienie_id and not zmiana_pory:
                    continue
                nowa = (dzien + timedelta(days=int(r["okres_dni"] or OKRES_ZMIANY_OPON_DNI))).strftime("%d.%m.%Y")
                c.execute("UPDATE wydatki_cykliczne SET nastepna_data=? WHERE id=?", (nowa, r["id"]))
                przesuniete.append((r["id"], r["nastepna_data"], nowa))

    if utworzony_wpis:
        aktualizuj_najnowszy_wpis(zadanie)
    zdjete = sorted(z for z in przed if z not in po)
    return {
        "ok": True, "z": ", ".join(sorted(s for s in sezony_przed if s and s != sezon)) or None, "na": sezon,
        "zestaw_id": zestaw_id, "os": os_montazu, "zdjete": zdjete,
        "opis_zestawu": " ".join(x for x in (zestaw["marka_model"], zestaw["rozmiar"]) if x),
        "historia_id": historia_id, "koszt_id": utworzony_koszt, "data": data, "przebieg": przebieg,
        "termin_przesuniety": bool(przesuniete), "nastepna_data": przesuniete[0][2] if przesuniete else None,
        "cofniecie": {"auto_id": auto_id, "przed": przed, "po": po, "otwarte": okresy["otwarte"],
                      "zamkniete": okresy["zamkniete"], "wpis": utworzony_wpis, "zadanie": zadanie,
                      "koszt": utworzony_koszt, "przypomnienia": [(i, stara) for i, stara, _ in przesuniete]},
    }


def zamontuj_po_wymianie(auto_id, sezon, data, przebieg=None, historia_id=None) -> dict[str, Any] | None:
    """Wymiana opon zapisana w Serwisie (wizyta albo wpis z rodzajem opon) zakłada komplet tej pory roku,
    gdy na aucie stoi inny: najgrubszy wolny komplet sezonu, wpis staje się zmianą (bez drugiego wpisu).
    None — komplet tego sezonu już jest na aucie albo w magazynie żadnego nie ma."""
    if not auto_id or sezon not in SEZONY_OPON:
        return None
    with polacz_baze() as conn:
        wiersze = conn.execute("SELECT id, zamontowane, glebokosc_bieznika FROM zestawy_opon WHERE auto_id=? AND sezon=?",
                               (auto_id, sezon)).fetchall()
    if not wiersze or any(w[1] for w in wiersze):
        return None
    kandydat = sorted(wiersze, key=lambda w: (-(_na_liczbe(w[2]) or 0.0), w[0]))[0][0]
    return zmien_opony(auto_id, kandydat, {"data": data, "przebieg": przebieg, "historia_id": historia_id,
                                           "do_serwisu": False})


def cofnij_zmiane_opon(cofniecie) -> bool:
    """Wraca do kompletów, okresów i terminu sprzed zmiany — tylko gdy nic jej w międzyczasie nie
    przestawiło (te same zamontowane, okresy zmiany wciąż otwarte). Wpis serwisowy i koszt zmiany
    znikają z nagrobkiem, nie do kosza."""
    if not cofniecie:
        return False
    auto_id = cofniecie["auto_id"]
    przed = {int(z): o for z, o in cofniecie["przed"].items()}
    po = {int(z): o for z, o in cofniecie["po"].items()}
    with polacz_baze() as conn:
        if flagi_montazu(conn, auto_id) != po:
            return False
        for m in cofniecie["otwarte"]:
            w = conn.execute("SELECT data_zdjecia FROM montaze_opon WHERE id=?", (m,)).fetchone()
            if not w or w[0] is not None:
                return False
        for z in set(przed) | set(po):
            if z in przed:
                conn.execute("UPDATE zestawy_opon SET zamontowane=1, os_montazu=? WHERE id=?", (przed[z], z))
            else:
                conn.execute("UPDATE zestawy_opon SET zamontowane=0, os_montazu='Wszystkie' WHERE id=?", (z,))
        for m in cofniecie["zamkniete"]:
            conn.execute("UPDATE montaze_opon SET data_zdjecia=NULL, przebieg_zdjecia=NULL WHERE id=?", (m,))
        for wydatek_id, stara in cofniecie["przypomnienia"]:
            conn.execute("UPDATE wydatki_cykliczne SET nastepna_data=? WHERE id=?", (stara, wydatek_id))

    wlasne = {t: [i] for t, i in (("historia", cofniecie["wpis"]), ("inne_koszty", cofniecie["koszt"])) if i}
    if cofniecie["otwarte"]:
        usuniecia = [usun_do_kosza("montaze_opon", cofniecie["otwarte"], wlasne=wlasne or None, do_kosza=False)]
    else:
        usuniecia = [usun_do_kosza(tabela, ids, do_kosza=False) for tabela, ids in wlasne.items()]
    for wynik in usuniecia:
        if wynik:
            wynik["finalizuj"]()
    if cofniecie["wpis"] and cofniecie["zadanie"]:
        aktualizuj_najnowszy_wpis(cofniecie["zadanie"])
    return True


__all__ = [
    "cofnij_zmiane_opon",
    "podzespol_opon",
    "zamontuj_po_wymianie",
    "zmien_opony",
]
