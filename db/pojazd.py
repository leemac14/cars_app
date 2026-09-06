"""Tożsamość pojazdu, terminy dokumentów i metryki zbiorcze."""

import sqlite3
from date import parsuj_date
from datetime import date as date_cls, datetime

from .stale import ROK_MIN
from .polaczenie import polacz_baze
from .pomocnicze import _liczba_lub_none, parsuj_int_bezpiecznie
from .ustawienia import pobierz_prog_dni_dokumentu
from .przebieg import oblicz_sredni_dzienny_przebieg, pobierz_aktualny_przebieg
from .koszty import DNI_W_MIESIACU, koszty_w_okresie
from .powiadomienia import pobierz_powiadomienia
from .statystyki import oblicz_kondycje_pojazdu


# ==================== TOŻSAMOŚĆ I METRYKI POJAZDU ====================
# Jedno miejsce, z którego korzystają: kafel pojazdu na ekranie głównym, ekran
# „Dane pojazdu” i paszport PDF. Wcześniej każdy liczył sobie wiek i przebieg
# roczny po swojemu — albo nie liczył wcale.

# Umowna norma rocznego przebiegu w Polsce. Nie służy do oceniania, tylko do
# jednego zdania kontekstu: „to auto jeździ dwa razy więcej niż przeciętne”.
NORMA_PRZEBIEGU_ROCZNEGO = 15000


# Terminy dokumentów pokazywane w jednym rzędzie: klucz progu powiadomień,
# kolumna z datą i etykieta. Kolejność decyduje o tym, co wygra przy remisie dni.
TERMINY_POJAZDU = [
    ("oc", "oc_data", "Polisa OC"),
    ("przeglad", "przeglad_data", "Przegląd techniczny"),
    ("ac", "ac_data", "Polisa AC"),
    ("assistance", "assistance_data", "Assistance"),
    ("gwarancja", "gwarancja_data", "Gwarancja"),
    ("gasnica", "gasnica_data", "Gaśnica"),
    ("apteczka", "apteczka_data", "Apteczka"),
]


def pobierz_dane_pojazdu(auto_id):
    """Komplet kolumn pojazdu jako zwykły słownik — bez wypisywania listy pól
    w każdym widoku z osobna. Nowa kolumna dodana migracją pojawia się tu sama."""
    if not auto_id:
        return None
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM samochody WHERE id=?", (auto_id,))
        w = c.fetchone()
    return dict(w) if w else None


def terminy_pojazdu(auto_id, dane=None):
    """Wszystkie terminy dokumentów pojazdu z policzonymi dniami i statusem.
    Status ('po_terminie' / 'blisko' / 'ok') liczy się względem progu USTAWIONEGO
    DLA TEGO DOKUMENTU, więc pokrywa się dokładnie z momentem powiadomienia."""
    dane = dane or pobierz_dane_pojazdu(auto_id)
    if not dane:
        return []

    dzis = datetime.now().date()
    wynik = []
    for klucz, kolumna, etykieta in TERMINY_POJAZDU:
        wartosc = dane.get(kolumna)
        if not wartosc:
            continue
        data_obj = parsuj_date(wartosc)
        if data_obj == datetime.min.date():
            continue
        dni = (data_obj - dzis).days
        prog = pobierz_prog_dni_dokumentu(klucz)
        wynik.append({
            "klucz": klucz, "etykieta": etykieta, "data": wartosc, "data_obj": data_obj,
            "dni": dni, "prog": prog,
            "status": "po_terminie" if dni < 0 else ("blisko" if dni <= prog else "ok"),
        })
    wynik.sort(key=lambda t: t["dni"])
    return wynik


def najblizszy_termin_pojazdu(auto_id, dane=None):
    """Termin, który wypada najwcześniej — z przeterminowanymi na przedzie.
    To jedna informacja, którą kafel pojazdu musi pokazać bez klikania."""
    terminy = terminy_pojazdu(auto_id, dane)
    return terminy[0] if terminy else None


def pobierz_metryki_pojazdu(auto_id, dane=None):
    """Liczby opisujące pojazd jako całość: wiek, tempo jazdy, koszt posiadania.

    Sedno jest w koszcie posiadania: paliwo i serwis to tylko część rachunku,
    a największą pozycją bywa UTRATA WARTOŚCI, której nie widać w żadnym wpisie.
    Dopiero cena zakupu i dzisiejsza wartość pozwalają powiedzieć, ile naprawdę
    kosztuje kilometr. Każda z tych liczb jest opcjonalna — pola, których
    użytkownik nie uzupełnił, po prostu nie mają wyniku (None), zamiast psuć
    pozostałe."""
    dane = dane or pobierz_dane_pojazdu(auto_id)
    if not dane:
        return None

    dzis = datetime.now().date()
    przebieg = pobierz_aktualny_przebieg(auto_id) or 0

    # --- wiek: pierwsza rejestracja jest dokładniejsza niż sam rocznik ---
    data_rej = parsuj_date(dane.get("data_pierwszej_rejestracji"))
    if data_rej == datetime.min.date():
        data_rej = None
    rok_prod = parsuj_int_bezpiecznie(dane.get("rok_produkcji"), 0)
    if data_rej:
        dni_wieku = (dzis - data_rej).days
    elif ROK_MIN <= rok_prod <= dzis.year:
        # Bez dnia i miesiąca zakładamy środek roku — mniejszy błąd niż 1 stycznia.
        dni_wieku = (dzis - date_cls(rok_prod, 7, 1)).days
    else:
        dni_wieku = None
    wiek_lat = (dni_wieku / 365.25) if dni_wieku and dni_wieku > 0 else None

    # --- tempo jazdy ---
    przebieg_roczny = (przebieg / wiek_lat) if (wiek_lat and wiek_lat >= 0.5 and przebieg > 0) else None
    intensywnosc = (przebieg_roczny / NORMA_PRZEBIEGU_ROCZNEGO * 100) if przebieg_roczny else None

    # --- posiadanie ---
    data_zakupu = parsuj_date(dane.get("data_zakupu"))
    if data_zakupu == datetime.min.date():
        data_zakupu = None
    dni_posiadania = (dzis - data_zakupu).days if data_zakupu else None
    przebieg_zakupu = parsuj_int_bezpiecznie(dane.get("przebieg_zakupu"), 0)
    km_u_ciebie = (przebieg - przebieg_zakupu) if (przebieg_zakupu > 0 and przebieg > przebieg_zakupu) else None
    if km_u_ciebie is None and dni_posiadania and przebieg > 0 and not przebieg_zakupu:
        km_u_ciebie = None  # bez przebiegu przy zakupie nie ma czego odjąć

    km_rocznie_u_ciebie = (
        km_u_ciebie / (dni_posiadania / 365.25)
        if (km_u_ciebie and dni_posiadania and dni_posiadania >= 30) else None
    )

    # --- wartość i amortyzacja ---
    cena_zakupu = _liczba_lub_none(dane.get("cena_zakupu"))
    wartosc = _liczba_lub_none(dane.get("wartosc_szacowana"))
    utrata = (cena_zakupu - wartosc) if (cena_zakupu and wartosc is not None) else None
    utrata_rocznie = (
        utrata / (dni_posiadania / 365.25)
        if (utrata is not None and dni_posiadania and dni_posiadania >= 90) else None
    )
    utrata_na_km = (utrata / km_u_ciebie) if (utrata is not None and km_u_ciebie) else None
    procent_wartosci = (wartosc / cena_zakupu * 100) if (cena_zakupu and wartosc is not None) else None

    # --- koszt posiadania: wydatki + utrata wartości ---
    wydatki = koszty_w_okresie(auto_id, data_zakupu, dzis)["razem"] if data_zakupu else koszty_w_okresie(auto_id)["razem"]
    koszt_calkowity = wydatki + (utrata or 0)
    koszt_km_pelny = (koszt_calkowity / km_u_ciebie) if km_u_ciebie else None
    koszt_miesieczny = (
        koszt_calkowity / (dni_posiadania / DNI_W_MIESIACU)
        if (dni_posiadania and dni_posiadania >= 30) else None
    )

    return {
        "przebieg": przebieg,
        "wiek_lat": wiek_lat,
        "dni_wieku": dni_wieku,
        "data_wieku": data_rej.strftime("%d.%m.%Y") if data_rej else (str(rok_prod) if rok_prod else None),
        "zrodlo_wieku": "rejestracja" if data_rej else ("rocznik" if rok_prod else None),
        "przebieg_roczny": przebieg_roczny,
        "intensywnosc": intensywnosc,
        "data_zakupu": dane.get("data_zakupu"),
        "dni_posiadania": dni_posiadania,
        "lata_posiadania": (dni_posiadania / 365.25) if dni_posiadania else None,
        "km_u_ciebie": km_u_ciebie,
        "km_rocznie_u_ciebie": km_rocznie_u_ciebie,
        "cena_zakupu": cena_zakupu,
        "wartosc_szacowana": wartosc,
        "procent_wartosci": procent_wartosci,
        "utrata_wartosci": utrata,
        "utrata_rocznie": utrata_rocznie,
        "utrata_na_km": utrata_na_km,
        "wydatki_od_zakupu": wydatki,
        "koszt_calkowity": koszt_calkowity,
        "koszt_km_pelny": koszt_km_pelny,
        "koszt_miesieczny": koszt_miesieczny,
        "kondycja": oblicz_kondycje_pojazdu(auto_id),
    }


def pobierz_dane_do_porownania(auto_id):
    """Zbiorcze dane pojazdu (specyfikacja, koszty, przebieg, spalanie, serwis)
    wykorzystywane przez ekran porównania pojazdów. Zwraca None, jeśli auto nie istnieje."""
    if not auto_id:
        return None

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT nazwa, nr_rej, rok_produkcji, pojemnosc_silnika, moc_silnika, "
            "typ_paliwa, skrzynia_biegow, oc_data, przeglad_data, ac_data, assistance_data, "
            "zdjecie_glowne FROM samochody WHERE id=?",
            (auto_id,)
        )
        w = c.fetchone()
        if not w:
            return None
        dane = dict(w)

        c.execute("SELECT COALESCE(SUM(kwota),0) FROM tankowania WHERE auto_id=?", (auto_id,))
        dane["koszt_paliwo"] = float(c.fetchone()[0] or 0.0)

        c.execute(
            "SELECT COALESCE(SUM(h.cena),0) FROM historia h JOIN zadania z ON h.zadanie_id=z.id "
            "WHERE z.auto_id=? AND h.wizyta_id IS NULL", (auto_id,)
        )
        koszt_historia = float(c.fetchone()[0] or 0.0)
        c.execute("SELECT COALESCE(SUM(koszt_calkowity),0) FROM wizyty WHERE auto_id=?", (auto_id,))
        koszt_wizyty = float(c.fetchone()[0] or 0.0)
        dane["koszt_serwis"] = koszt_historia + koszt_wizyty

        c.execute("SELECT COALESCE(SUM(kwota),0) FROM inne_koszty WHERE auto_id=?", (auto_id,))
        dane["koszt_inne"] = float(c.fetchone()[0] or 0.0)

        dane["koszt_razem"] = dane["koszt_paliwo"] + dane["koszt_serwis"] + dane["koszt_inne"]

        c.execute("SELECT przebieg, litry, do_pelna FROM tankowania WHERE auto_id=? ORDER BY przebieg", (auto_id,))
        tankowania = c.fetchall()

        c.execute("SELECT COUNT(*) FROM historia h JOIN zadania z ON h.zadanie_id=z.id WHERE z.auto_id=?", (auto_id,))
        dane["liczba_wpisow_historii"] = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM wizyty WHERE auto_id=?", (auto_id,))
        dane["liczba_wizyt"] = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM do_zrobienia WHERE auto_id=? AND wykonane=0", (auto_id,))
        dane["do_zrobienia_aktywne"] = c.fetchone()[0]
        c.execute(
            "SELECT COUNT(*) FROM magazyn_czesci WHERE auto_id=? AND ilosc <= COALESCE(prog_ostrzezenia, 1)",
            (auto_id,)
        )
        dane["magazyn_niski_stan"] = c.fetchone()[0]

    dane["aktualny_przebieg"] = pobierz_aktualny_przebieg(auto_id)
    dane["sredni_dzienny"] = oblicz_sredni_dzienny_przebieg(auto_id)
    # Wskaźnik 0-100 (ten sam, co kafelek „Kondycja” w kokpicie) — jedna z osi
    # radaru w porównaniu pojazdów.
    dane["kondycja"] = oblicz_kondycje_pojazdu(auto_id)

    dystans = 0
    if len(tankowania) >= 2:
        dystans = max(0, int(tankowania[-1]["przebieg"] or 0) - int(tankowania[0]["przebieg"] or 0))
    dane["koszt_km"] = (dane["koszt_razem"] / dystans) if dystans > 0 else None

    spalanie = None
    peln_idx = [i for i, t in enumerate(tankowania) if t["do_pelna"]]
    if len(peln_idx) >= 2:
        p, o = peln_idx[0], peln_idx[-1]
        d_p = int(tankowania[o]["przebieg"] or 0) - int(tankowania[p]["przebieg"] or 0)
        l_p = sum(float(tankowania[k]["litry"] or 0) for k in range(p + 1, o + 1))
        if d_p > 0:
            spalanie = (l_p / d_p) * 100
    dane["spalanie"] = spalanie

    powiadomienia = pobierz_powiadomienia(auto_id)
    dane["przeterminowane"] = sum(1 for p in powiadomienia if p["status"] == "przeterminowane")
    dane["pilne"] = sum(1 for p in powiadomienia if p["status"] == "pilne")

    return dane


__all__ = [
    "NORMA_PRZEBIEGU_ROCZNEGO",
    "TERMINY_POJAZDU",
    "najblizszy_termin_pojazdu",
    "pobierz_dane_do_porownania",
    "pobierz_dane_pojazdu",
    "pobierz_metryki_pojazdu",
    "terminy_pojazdu",
]
