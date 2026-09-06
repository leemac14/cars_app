"""Przypomnienia, odkładanie i wyciszanie powiadomień."""

import sqlite3
from date import parsuj_date
from datetime import datetime, timedelta

from .stale import PROG_ILOSC_MAGAZYNU_DOMYSLNY, TERMINY_DOKUMENTOW
from .polaczenie import polacz_baze
from .ustawienia import pobierz_prog_dni, pobierz_prog_dni_dokumentu, pobierz_prog_km
from .przebieg import oblicz_sredni_dzienny_przebieg, pobierz_aktualny_przebieg


def pobierz_powiadomienia(auto_id, prog_km=None, prog_dni=None, pomin_wyciszone=True):
    """Każde powiadomienie niesie 'klucz' — stabilny identyfikator (typ + ID
    źródła), po którym rozpoznajemy je między odświeżeniami. Treść się do tego
    nie nadaje, bo opis zmienia się z każdym dniem („Zostało 12 dni”).
    pomin_wyciszone=False zwraca komplet, łącznie z odłożonymi — potrzebne
    panelowi powiadomień do sekcji „Odkładane”."""
    if not auto_id:
        return []

    if prog_km is None: prog_km = pobierz_prog_km()
    prog_dni_wymuszony = prog_dni is not None
    if prog_dni is None: prog_dni = pobierz_prog_dni()

    wyniki = []
    dzis = datetime.now().date()
    aktualny_przebieg = pobierz_aktualny_przebieg(auto_id) or 0
    sredni_dzienny_przebieg = oblicz_sredni_dzienny_przebieg(auto_id)

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute(
            "SELECT id, nazwa, data, przebieg, interwal_km, interwal_miesiace, prog_km, prog_dni FROM zadania "
            "WHERE auto_id=? AND (interwal_km IS NOT NULL OR interwal_miesiace IS NOT NULL)",
            (auto_id,)
        )
        for z in c.fetchall():
            powody, status_zadania = [], None
            prog_km_z = int(z["prog_km"]) if z["prog_km"] else prog_km
            prog_dni_z = int(z["prog_dni"]) if z["prog_dni"] else prog_dni

            if z["interwal_km"] and z["przebieg"] and aktualny_przebieg:
                zost_km = (int(z["przebieg"]) + int(z["interwal_km"])) - aktualny_przebieg
                if zost_km <= prog_km_z:
                    s = "przeterminowane" if zost_km < 0 else "pilne"
                    if zost_km < 0:
                        powody.append(f"Przekroczono o {abs(zost_km)} km")
                    else:
                        import utils
                        prognoza = utils.formatuj_prognoze_km(zost_km, sredni_dzienny_przebieg)
                        powody.append(f"Zostało {prognoza}")
                    status_zadania = s

            if z["interwal_miesiace"] and z["data"]:
                d_w = parsuj_date(z["data"])
                if d_w != datetime.min.date():
                    termin = d_w + timedelta(days=int(float(z["interwal_miesiace"]) * 30.5))
                    zost_dni = (termin - dzis).days
                    if zost_dni <= prog_dni_z:
                        s = "przeterminowane" if zost_dni < 0 else "pilne"
                        powody.append(f"Przekroczono o {abs(zost_dni)} dni" if zost_dni < 0 else f"Zostało {zost_dni} dni")
                        if status_zadania != "przeterminowane":
                            status_zadania = s

            if powody:
                wyniki.append({
                    "typ": "podzespol", "tytul": z["nazwa"], "opis": " • ".join(powody),
                    "status": status_zadania, "trasa": f"/zadanie/edytuj/{z['id']}",
                    "klucz": f"podzespol:{z['id']}",
                })

        kolumny_terminow = ", ".join(kol for _, kol, _ in TERMINY_DOKUMENTOW)
        c.execute(
            f"SELECT {kolumny_terminow}, gwarancja_przebieg FROM samochody WHERE id=?",
            (auto_id,)
        )
        w = c.fetchone()
        if w:
            # Każdy termin ma własny próg wyprzedzenia (Ustawienia → „Progi
            # powiadomień”); nieruszony termin dziedziczy wspólny prog_dni.
            # prog_dni podany jawnie w wywołaniu nadal wygrywa ze wszystkim —
            # służy do podglądu „co by było, gdyby” bez ruszania ustawień.
            for klucz, kolumna, etykieta in TERMINY_DOKUMENTOW:
                txt = w[kolumna]
                if not txt:
                    continue
                d_w = parsuj_date(txt)
                if d_w == datetime.min.date():
                    continue
                prog_terminu = prog_dni if prog_dni_wymuszony else pobierz_prog_dni_dokumentu(klucz)
                zost_dni = (d_w - dzis).days
                if zost_dni <= prog_terminu:
                    s = "przeterminowane" if zost_dni < 0 else "pilne"
                    opis = f"Przekroczono o {abs(zost_dni)} dni" if zost_dni < 0 else f"Zostało {zost_dni} dni"
                    wyniki.append({
                        "typ": "dokument", "tytul": etykieta, "opis": opis,
                        "status": s, "trasa": f"/auto/edytuj/{auto_id}",
                        "klucz": f"dokument:{klucz}",
                    })

            # Gwarancja ma dwa niezależne limity — datę i przebieg. Kilometry
            # potrafią się skończyć długo przed datą, więc liczymy je osobno.
            limit_km = w["gwarancja_przebieg"]
            if limit_km:
                zost_km_gw = int(limit_km) - aktualny_przebieg
                if zost_km_gw <= prog_km:
                    s = "przeterminowane" if zost_km_gw < 0 else "pilne"
                    opis = (f"Przekroczono limit o {abs(zost_km_gw)} km" if zost_km_gw < 0
                            else f"Zostało {zost_km_gw} km do końca gwarancji")
                    wyniki.append({
                        "typ": "dokument", "tytul": "Gwarancja (limit km)", "opis": opis,
                        "status": s, "trasa": f"/auto/edytuj/{auto_id}",
                        "klucz": "dokument:gwarancja_km",
                    })
        # Wydatki cykliczne (raty, abonamenty, ubezpieczenia ratalne) — termin
        # liczy się jak dla dokumentów, ale akcją jest "Zapłacone", nie przejście
        # do formularza (stąd "trasa": None).
        c.execute(
            "SELECT id, nazwa, nastepna_data, okres_dni, czy_koszt FROM wydatki_cykliczne WHERE auto_id=?",
            (auto_id,)
        )
        for wc in c.fetchall():
            d_wc = parsuj_date(wc["nastepna_data"])
            if d_wc == datetime.min.date():
                continue
            zost_dni = (d_wc - dzis).days
            # Próg dla wydatków cyklicznych jest dodatkowo ograniczony częścią
            # ich WŁASNEGO okresu — inaczej pozycja płatna np. co 30 dni przy
            # globalnym progu powiadomień 30 dni byłaby "pilna" przez CAŁY
            # cykl, a kliknięcie "Zapłacone" (przesuwające termin o okres_dni)
            # od razu wracałoby jako to samo powiadomienie.
            wlasny_prog = max(1, int(wc["okres_dni"] or 30) // 3)
            prog_efektywny = min(prog_dni, wlasny_prog)
            if zost_dni <= prog_efektywny:
                s = "przeterminowane" if zost_dni < 0 else "pilne"
                opis = f"Przekroczono o {abs(zost_dni)} dni" if zost_dni < 0 else f"Zostało {zost_dni} dni"
                wyniki.append({
                    "typ": "cykliczny", "tytul": wc["nazwa"], "opis": opis,
                    "status": s, "trasa": None, "wydatek_id": wc["id"],
                    "czy_koszt": bool(wc["czy_koszt"]),
                    "klucz": f"cykliczny:{wc['id']}",
                })

        # Niski stan magazynu (części i płyny) — indywidualny próg per pozycja,
        # z fallbackiem na wspólną wartość domyślną dla starszych wpisów bez własnego progu.
        import utils
        c.execute(
            "SELECT id, nazwa, ilosc, jednostka, prog_ostrzezenia FROM magazyn_czesci WHERE auto_id=?",
            (auto_id,)
        )
        for m in c.fetchall():
            prog_wlasny = m["prog_ostrzezenia"]
            prog_magazynu = float(prog_wlasny) if prog_wlasny is not None else PROG_ILOSC_MAGAZYNU_DOMYSLNY
            ilosc_m = float(m["ilosc"] or 0)
            if ilosc_m <= prog_magazynu:
                s = "przeterminowane" if ilosc_m <= 0 else "pilne"
                jednostka_m = m["jednostka"] or "szt"
                opis = "Brak na stanie" if ilosc_m <= 0 else f"Zostało {utils.formatuj_liczba(ilosc_m, 2)} {jednostka_m}"
                wyniki.append({
                    "typ": "magazyn", "tytul": m["nazwa"], "opis": opis,
                    "status": s, "trasa": "/magazyn",
                    "klucz": f"magazyn:{m['id']}",
                })

    kolejnosc = {"przeterminowane": 0, "pilne": 1}

    wyniki.sort(key=lambda w: kolejnosc.get(w["status"], 2))

    if pomin_wyciszone:
        wyciszone = pobierz_wyciszone_klucze(auto_id)
        wyniki = [w for w in wyniki if w.get("klucz") not in wyciszone]
    return wyniki


# ============================================================================
#  ODKŁADANIE POWIADOMIEŃ („drzemka”)
# ============================================================================
# „Wiem o przeglądzie, zrobię go za dwa tygodnie” — wyciszenie JEDNEGO
# przypomnienia na wybraną liczbę dni, bez oznaczania czegokolwiek jako wykonane
# i bez ruszania samego terminu. Po upływie dni powiadomienie wraca samo.

DNI_ODLOZENIA_OPCJE = [3, 7, 14, 30]


def odloz_powiadomienie(auto_id, klucz, dni, tytul=None):
    """Wycisza powiadomienie o danym kluczu na `dni` dni. Ponowne odłożenie tego
    samego powiadomienia nadpisuje termin (stąd UNIQUE na auto_id+klucz)."""
    if not auto_id or not klucz:
        return None
    try:
        dni = max(1, int(dni))
    except (TypeError, ValueError):
        dni = 7
    do_dnia = (datetime.now().date() + timedelta(days=dni)).strftime("%Y-%m-%d")
    with polacz_baze() as conn:
        conn.execute(
            "INSERT INTO wyciszone_powiadomienia (auto_id, klucz, do_dnia, tytul, utworzono) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(auto_id, klucz) DO UPDATE SET do_dnia=excluded.do_dnia, "
            "tytul=excluded.tytul, utworzono=excluded.utworzono",
            (auto_id, klucz, do_dnia, tytul, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
    return do_dnia


def przywroc_powiadomienie(auto_id, klucz):
    """Zdejmuje drzemkę — powiadomienie wraca na listę od razu."""
    if not auto_id or not klucz:
        return
    with polacz_baze() as conn:
        conn.execute("DELETE FROM wyciszone_powiadomienia WHERE auto_id=? AND klucz=?", (auto_id, klucz))


def _posprzataj_wygasle_wyciszenia(conn, auto_id):
    """Kasuje drzemki, których termin już minął — dzięki temu tabela nie rośnie,
    a powiadomienie wraca bez żadnej dodatkowej logiki."""
    conn.execute(
        "DELETE FROM wyciszone_powiadomienia WHERE auto_id=? AND do_dnia <= ?",
        (auto_id, datetime.now().date().strftime("%Y-%m-%d"))
    )


def pobierz_wyciszone_klucze(auto_id):
    """Zbiór kluczy powiadomień AKTUALNIE odłożonych (drzemka jeszcze trwa)."""
    if not auto_id:
        return set()
    with polacz_baze() as conn:
        c = conn.cursor()
        try:
            _posprzataj_wygasle_wyciszenia(conn, auto_id)
            c.execute("SELECT klucz FROM wyciszone_powiadomienia WHERE auto_id=?", (auto_id,))
        except sqlite3.OperationalError:
            return set()
        return {r[0] for r in c.fetchall()}


def pobierz_odlozone_powiadomienia(auto_id):
    """Lista odłożonych powiadomień do sekcji „Odkładane” w panelu:
    [{klucz, tytul, do_dnia, data_tekst, dni_do_powrotu}] posortowana po dacie
    powrotu. Tytuł bierzemy z żywego powiadomienia, jeśli nadal istnieje —
    a z zapamiętanego, gdy powód wyciszenia zdążył sam zniknąć."""
    if not auto_id:
        return []

    with polacz_baze() as conn:
        c = conn.cursor()
        try:
            _posprzataj_wygasle_wyciszenia(conn, auto_id)
            c.execute(
                "SELECT klucz, do_dnia, tytul FROM wyciszone_powiadomienia "
                "WHERE auto_id=? ORDER BY do_dnia",
                (auto_id,)
            )
        except sqlite3.OperationalError:
            return []
        wiersze = c.fetchall()

    if not wiersze:
        return []

    zywe = {p.get("klucz"): p for p in pobierz_powiadomienia(auto_id, pomin_wyciszone=False)}
    dzis = datetime.now().date()
    pozycje = []
    for klucz, do_dnia, tytul in wiersze:
        try:
            data_obj = datetime.strptime(str(do_dnia), "%Y-%m-%d").date()
        except (TypeError, ValueError):
            continue
        zrodlo = zywe.get(klucz)
        pozycje.append({
            "klucz": klucz,
            "tytul": (zrodlo or {}).get("tytul") or tytul or "Powiadomienie",
            "opis": (zrodlo or {}).get("opis") or "",
            "status": (zrodlo or {}).get("status"),
            "trasa": (zrodlo or {}).get("trasa"),
            "do_dnia": do_dnia,
            "data_tekst": data_obj.strftime("%d.%m.%Y"),
            "dni_do_powrotu": max(0, (data_obj - dzis).days),
            "nadal_aktualne": zrodlo is not None,
        })
    return pozycje


__all__ = [
    "DNI_ODLOZENIA_OPCJE",
    "_posprzataj_wygasle_wyciszenia",
    "odloz_powiadomienie",
    "pobierz_odlozone_powiadomienia",
    "pobierz_powiadomienia",
    "pobierz_wyciszone_klucze",
    "przywroc_powiadomienie",
]
