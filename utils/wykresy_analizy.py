"""Analiza › Wykresy: spis pytań w trzech grupach (wiersz = odpowiedź liczbą, zdanie
i mini-wykres) i treść ekranu jednego wykresu (/wykres/<klucz>). Dane liczy db."""

from datetime import datetime

import flet as ft

import db
import log
from date import parsuj_date

from .stale import (FS, IKONY_KATEGORII_KOSZTOW, KOLOR_STATUS, KOLORY_RODZAJU_SERWISU, RADIUS, SPACING,
                    formatuj_liczba, ikona_kategorii_innych, kolor_kategorii_innych, kolor_tagu_lub_neutralny)
from .format import MIESIACE_MIEJSCOWNIK, formatuj_dni, formatuj_spalanie, jednostka_dystansu, symbol_waluty
from .typografia import KOLOR_DRUGIEGO_PLANU, etykieta, podpis, wartosc
from .wyglad import powierzchnia, wiersz_udzialu
from .dialogi import odswiez_ekran, przejdz
from .koszt_naprawy import SERIE_ROZBICIA, karta_robocizny_i_czesci
from .wykresy import (KOLORY_SERII_KOSZTU, _jednostka_rdr, _kropka_legendy, granica_zakresu, karta_kosztu_1000km,
                      karta_kosztu_skumulowanego, karta_rok_do_roku, krzywa_1000_w_jednostce, mini_dwie_krzywe,
                      mini_slupki, okresy_slupkow, opis_zakresu, pasek_lat_rdr, pasek_okna_kroczacego,
                      pasek_skladu, pasek_zakresu_czasu, sparkline, wykres_miesieczny, zakres_wykresu,
                      znacznik_trendu)
from .komponenty import nota_o_liczeniu
from .awarie import karta_awarii

# Grupy spisu: (id, tytuł, ikona); przy elektryku trzecia mówi o ładowaniu.
GRUPY_WYKRESOW = (
    ("koszt", "Ile kosztuje auto", ft.Icons.PAYMENTS),
    ("podzial", "Na co idą pieniądze", ft.Icons.DONUT_SMALL),
    ("energia", "Tankowanie", ft.Icons.LOCAL_GAS_STATION),
)
GRUPA_ENERGII_PRAD = ("energia", "Ładowanie", ft.Icons.EV_STATION)

# Kolejność = kolejność spisu i „Następnego wykresu”. `{j}` — jednostka dystansu z Ustawień;
# klucze z `_prad` podmieniają tekst u elektryka. `klucz` jest też kluczem zakresu w ustawieniach.
WYKRESY_ANALIZY = [
    {"klucz": "skumulowany", "grupa": "koszt", "ikona": ft.Icons.STACKED_LINE_CHART,
     "pytanie": "Ile kosztowało do dziś?", "nazwa": "Koszt skumulowany",
     "opis": "Linia to suma wszystkich wydatków dzień po dniu — od zakupu albo od pierwszego wpisu. Im "
             "stromiej, tym szybciej idą pieniądze, a poziomy odcinek to czas bez wydatków. Kropki to "
             "większe jednorazowe wydatki: dotknij, żeby zobaczyć, co to było."},
    {"klucz": "koszt1000", "grupa": "koszt", "ikona": ft.Icons.AUTO_GRAPH,
     "pytanie": "Czy jazda drożeje?", "nazwa": "Koszt na 1000 {j}",
     "opis": "Każdy punkt to koszt przejechania 1000 {j} z wydatków i przebiegu ostatnich miesięcy (długość "
             "okna wybierasz nad wykresem). Suma roczna rośnie też wtedy, gdy więcej jeździsz — ta linia nie, "
             "więc jej wzrost znaczy, że auto naprawdę drożeje. Przerywana linia to średnia z całej historii."},
    {"klucz": "rok_do_roku", "grupa": "koszt", "ikona": ft.Icons.COMPARE_ARROWS,
     "pytanie": "Drożej niż rok temu?", "nazwa": "Rok do roku",
     "opis": "Wybrany rok grubą linią, poprzedni przerywaną, na wspólnej osi miesięcy. „Narastająco” "
             "pokazuje, od którego miesiąca lata się rozjechały, „Miesięcznie” — pojedyncze skoki. Nad "
             "wykresem wybierasz, co porównać: koszty, paliwo, serwis, inne albo przebieg."},
    {"klucz": "wydatki", "grupa": "koszt", "ikona": ft.Icons.BAR_CHART,
     "pytanie": "Ile wydajesz w miesiącu?", "nazwa": "Wydatki w czasie",
     "opis": "Słupek to suma wydatków w miesiącu, podzielona na paliwo, serwis i inne koszty. Przy "
             "dłuższej historii słupki zbierają kwartały albo lata. Przytrzymaj słupek, żeby zobaczyć kwoty."},
    {"klucz": "struktura", "grupa": "podzial", "ikona": ft.Icons.PIE_CHART,
     "pytanie": "Na co idą pieniądze?", "nazwa": "Struktura kosztów",
     "opis": "Jaką część wszystkich wydatków z wybranego okresu zjadło paliwo, serwis i inne koszty. "
             "Długość paska to udział w całości."},
    {"klucz": "kategorie", "grupa": "podzial", "ikona": ft.Icons.RECEIPT_LONG,
     "pytanie": "Co jest w innych kosztach?", "nazwa": "Inne koszty wg kategorii",
     "opis": "Inne koszty rozbite na kategorie: ubezpieczenie, parkingi, myjnia, opłaty. Widać, co poza "
             "paliwem i serwisem naprawdę rośnie."},
    {"klucz": "robocizna", "grupa": "podzial", "ikona": ft.Icons.HANDYMAN,
     "pytanie": "Warsztat czy części?", "nazwa": "Robocizna czy części",
     "opis": "Ile z rachunków za naprawy to praca warsztatu, a ile części. Liczą się naprawy z podziałem — "
             "robociznę wpisuje się w wizycie albo we wpisie serwisu. Niżej warsztaty i części kupione "
             "samemu obok tych z warsztatu."},
    {"klucz": "awarie", "grupa": "podzial", "ikona": ft.Icons.REPORT_PROBLEM,
     "pytanie": "Czy auto zaczyna się sypać?", "nazwa": "Awarie kontra eksploatacja",
     "opis": "Planowe naprawy to zwykły koszt jazdy, awarie — znak, że coś się psuje. Rosnący udział "
             "awarii i coraz krótsze odstępy między nimi mówią więcej niż sama suma serwisu."},
    {"klucz": "tagi", "grupa": "podzial", "ikona": ft.Icons.SELL,
     "pytanie": "Ile kosztują twoje tagi?", "nazwa": "Wydatki według tagów",
     "opis": "Tankowania, wizyty i inne koszty z danym tagiem — tagi nadajesz sam, więc to podział wydatków "
             "po twojemu: wyjazdy, praca, dojazdy. Wpis z kilkoma tagami liczy się przy każdym z nich. "
             "Dotknij tagu, żeby zobaczyć jego wpisy."},
    {"klucz": "spalanie", "grupa": "energia", "ikona": ft.Icons.SPEED,
     "pytanie": "Czy pali więcej niż zwykle?", "pytanie_prad": "Czy zużywa więcej prądu?",
     "nazwa": "Trend spalania", "nazwa_prad": "Trend zużycia energii",
     "opis": "Średnie spalanie w każdym miesiącu, liczone z tankowań do pełna. Zimą zwykle rośnie, dlatego "
             "znacznik u góry porównuje ostatnie tankowania z wcześniejszymi po odjęciu pory roku. "
             "Przerywana linia to średnia z wybranego okresu.",
     "opis_prad": "Średnie zużycie energii w każdym miesiącu, liczone z ładowań do pełna. Zimą zwykle rośnie, "
                  "dlatego znacznik u góry porównuje ostatnie ładowania z wcześniejszymi po odjęciu pory "
                  "roku. Przerywana linia to średnia z wybranego okresu."},
    {"klucz": "ceny", "grupa": "energia", "ikona": ft.Icons.LOCAL_GAS_STATION, "ikona_prad": ft.Icons.EV_STATION,
     "pytanie": "Gdzie tankować taniej?", "pytanie_prad": "Gdzie ładować taniej?",
     "nazwa": "Ceny paliwa i stacje", "nazwa_prad": "Ceny prądu i punkty ładowania",
     "opis": "Średnia cena litra w każdym miesiącu i ranking stacji z tego samego okresu — pierwsza na "
             "liście jest najtańsza. Przerywana linia to średnia cena z okresu.",
     "opis_prad": "Średnia cena kWh w każdym miesiącu i ranking punktów ładowania z tego samego okresu — "
                  "pierwszy na liście jest najtańszy. Przerywana linia to średnia cena z okresu."},
]

KLUCZE_WYKRESOW = [w["klucz"] for w in WYKRESY_ANALIZY]
KOLOR_SPALANIA = ft.Colors.TEAL_700
KOLOR_CEN = ft.Colors.BLUE_700


def wykres_analizy(klucz):
    """Wpis rejestru albo pierwszy wykres, gdy klucza nie ma (stara trasa, literówka)."""
    return next((w for w in WYKRESY_ANALIZY if w["klucz"] == klucz), WYKRESY_ANALIZY[0])


def nastepny_wykres(klucz):
    """Klucz kolejnego wykresu albo None za ostatnim."""
    i = KLUCZE_WYKRESOW.index(wykres_analizy(klucz)["klucz"])
    return KLUCZE_WYKRESOW[i + 1] if i + 1 < len(KLUCZE_WYKRESOW) else None


def _czy_prad(auto_id):
    return db.domyslny_rodzaj_energii(auto_id) == db.ENERGIA_PRAD


def tekst_wykresu(wpis, pole, prad=False):
    """Pytanie, nazwa albo opis wykresu z jednostką dystansu (i wariantem dla prądu)."""
    tekst = wpis.get(f"{pole}_prad") if prad else None
    return (tekst or wpis[pole]).replace("{j}", jednostka_dystansu())


_OKRESY_MIANOWNIK = {3: "ostatnie 3 miesiące", 6: "ostatnie 6 miesięcy", 12: "ostatni rok", 0: "cała historia"}


def okres_slowami(miesiace):
    """Zakres w mianowniku — do etykiet „Razem — ostatni rok” (opis_zakresu jest w bierniku)."""
    return _OKRESY_MIANOWNIK.get(miesiace, _OKRESY_MIANOWNIK[12])


def _kwota(x):
    """Kwota do zdania: pełne złote od stu wzwyż, grosze poniżej."""
    x = float(x or 0.0)
    return formatuj_liczba(x, 0 if abs(x) >= 100 else 2)


def _nazwa_paliwa(auto_id):
    if db.czy_pojazd_elektryczny(auto_id):
        return "prąd"
    return "energia" if db.czy_pojazd_dwuzrodlowy(auto_id) else "paliwo"


def _miesieczne(pary, granica):
    """[(data, wartość)] → [(„RRRR-MM”, średnia miesiąca)] od granicy, rosnąco."""
    wg_mc = {}
    for data_str, wartosc_w in pary:
        d = parsuj_date(data_str)
        if d == datetime.min.date() or (granica and d < granica):
            continue
        wg_mc.setdefault(f"{d.year}-{d.month:02d}", []).append(float(wartosc_w))
    return sorted((k, sum(v) / len(v)) for k, v in wg_mc.items())


# ============================== DANE ==============================

def dane_wykresu(state, klucz, pelne=False):
    """Wszystko, czego potrzebuje wiersz spisu i ekran wykresu `klucz` (z jego zakresem)."""
    auto_id = getattr(state, "auto_id", None)
    zakres = zakres_wykresu(state, klucz)
    granica = granica_zakresu(zakres)
    dane = {"zakres": zakres, "granica": granica}

    if klucz == "skumulowany":
        dane["skum"] = db.koszt_skumulowany(auto_id, z_cena_zakupu=db.czy_skumulowany_z_cena_zakupu())
    elif klucz == "koszt1000":
        dane["d"] = krzywa_1000_w_jednostce(db.koszt_na_1000km(auto_id, db.pobierz_okno_kroczace(auto_id)))
    elif klucz == "rok_do_roku":
        dane["d"] = db.koszty_rok_do_roku(
            auto_id, rok=getattr(state, "rdr_rok", None), wielkosc=getattr(state, "rdr_wielkosc", "razem"),
            narastajaco=bool(getattr(state, "rdr_narastajaco", True)))
    elif klucz == "wydatki":
        dane.update(_dane_wydatkow(auto_id, zakres))
    elif klucz == "struktura":
        dane["k"] = db.koszty_w_okresie(auto_id, granica)
        dane["paliwo"] = _nazwa_paliwa(auto_id)
    elif klucz == "kategorie":
        dane["lista"] = sorted(db.pobierz_koszty_innych_wg_kategorii(auto_id, granica), key=lambda r: -r[1])
    elif klucz == "robocizna":
        dane["r"] = db.pobierz_rozbicie_napraw(auto_id, granica)
        dane["porownania"] = db.porownaj_czesci_wlasne(auto_id, granica) if pelne else []
    elif klucz == "awarie":
        dane["a"] = db.awarie_i_eksploatacja(auto_id, granica)
    elif klucz == "tagi":
        dane["t"] = db.koszty_wg_tagow(auto_id, granica)
    elif klucz == "spalanie":
        dane.update(_dane_spalania(auto_id, granica))
    elif klucz == "ceny":
        dane.update(_dane_cen(auto_id, granica))
    return dane


def _dane_wydatkow(auto_id, zakres):
    """Słupki okresów z sumą paliwa, serwisu i innych (siatka jak `okresy_slupkow`)."""
    dzis = datetime.now().date()
    miesiace = db.miesiace_z_danymi(auto_id)
    najstarszy = f"{miesiace[-1][0]}-{miesiace[-1][1]:02d}" if miesiace else None
    okresy = okresy_slupkow(zakres, najstarszy, dzis)
    klucze = [k for _, ks in okresy for k in ks]
    mapa = {f"{r}-{m:02d}": s for r, m, s in db.pobierz_koszty_miesieczne_wg_kategorii(auto_id, len(klucze))}
    sumy = [{kat: sum((mapa.get(k) or {}).get(kat, 0.0) for k in ks) for kat in KOLORY_SERII_KOSZTU}
            for _, ks in okresy]
    # Średnia miesiąca liczy się od pierwszego miesiąca z wydatkiem w zakresie, nie od jego początku.
    z_wydatkiem = [i for i, k in enumerate(klucze) if (mapa.get(k) or {}).get("razem")]
    miesiecy = len(klucze) - z_wydatkiem[0] if z_wydatkiem else 0
    biezacy = f"{dzis.year}-{dzis.month:02d}"
    return {"okresy": okresy, "sumy": sumy, "miesiecy": miesiecy,
            "biezacy_okres": next((i for i, (_, ks) in enumerate(okresy) if biezacy in ks), None)}


def _dane_spalania(auto_id, granica):
    rodzaj = db.domyslny_rodzaj_energii(auto_id)
    prad = rodzaj == db.ENERGIA_PRAD
    seria = db.pobierz_serie_spalania(auto_id, limit=None, rodzaj=rodzaj) if auto_id else []
    w_zakresie = [(d, w) for d, w in seria
                  if parsuj_date(d) != datetime.min.date() and not (granica and parsuj_date(d) < granica)]

    def na_ekran(w):
        return db.przelicz_zuzycie(w, prad)[0]

    punkty = [(k, na_ekran(w)) for k, w in _miesieczne(w_zakresie, None) if na_ekran(w) is not None]
    srednia = (sum(w for _, w in w_zakresie) / len(w_zakresie)) if w_zakresie else None
    return {"prad": prad, "punkty": punkty, "jednostka": db.jednostka_zuzycia(prad),
            "srednia": srednia, "srednia_ekran": na_ekran(srednia) if srednia else None,
            "trend": db.analizuj_trend_spalania(auto_id, rodzaj) if auto_id else None,
            "ostatnia": w_zakresie[-1][1] if w_zakresie else None}


def _dane_cen(auto_id, granica):
    rodzaj = db.domyslny_rodzaj_energii(auto_id)
    trend = db.pobierz_trend_cen_paliwa(auto_id, granica, rodzaj)
    ceny = [c for _, c in trend["punkty"]]
    return {"prad": rodzaj == db.ENERGIA_PRAD, "jednostka": db.etykiety_energii(rodzaj)["jednostka"],
            "punkty": _miesieczne(trend["punkty"], None), "stacje": trend["stacje"],
            "srednia": (sum(ceny) / len(ceny)) if ceny else None}


# ============================== SPIS ==============================
# Odpowiedź wiersza: (wartość albo None, chip albo None, zdanie, mini-wykres albo None).

def _odpowiedz(state, klucz, dane, scena=None):
    w = symbol_waluty()
    za_okres = f"za {opis_zakresu(dane['zakres'])}"   # biernik: „za ostatni rok”, „za całą historię”
    okres = okres_slowami(dane["zakres"])

    if klucz == "skumulowany":
        d = dane["skum"]
        if not d.get("wydatki") or len(d.get("punkty") or []) < 2:
            return None, None, "Pojawi się po pierwszych wpisach kosztowych.", None
        czesci = ["od zakupu" if d.get("czy_od_zakupu") else f"od {d['start'].strftime('%m.%Y')}"]
        if d.get("z_cena_zakupu"):
            czesci[0] += " z ceną auta"
        if d.get("koszt_dzien"):
            czesci.append(f"{_kwota(d['koszt_dzien'])} {w} dziennie")
        return (f"{formatuj_liczba(d['suma'], 0)} {w}", None, " · ".join(czesci),
                sparkline(d.get("iskra"), ft.Colors.PRIMARY, wysokosc=30, szerokosc=88))

    if klucz == "koszt1000":
        d = dane["d"] or {}
        j = d.get("jednostka", jednostka_dystansu())
        if not d.get("biezacy") or len(d.get("punkty") or []) < 2:
            return None, None, "Potrzeba odczytów licznika i wydatków z dwóch pełnych okien.", None
        zdanie = f"za 1000 {j} z {d['okno']} mies."
        srednia = d.get("srednia_zyciowa")
        if srednia:
            nad = (d["biezacy"] - srednia) / srednia * 100
            if abs(nad) < 15:
                zdanie += " · w okolicach średniej"
            else:
                zdanie += f" · o {formatuj_liczba(abs(nad), 0)}% {'drożej' if nad > 0 else 'taniej'} niż średnio"
        chip = None
        if d.get("zmiana_rdr") is not None:
            chip = ft.Row([znacznik_trendu(d["zmiana_rdr"], wzrost_zly=True, rozmiar=FS["label"]),
                           podpis("r/r")], spacing=3, tight=True)
        return (f"{formatuj_liczba(d['biezacy'], 0)} {w}", chip, zdanie,
                sparkline(d.get("iskra"), ft.Colors.PRIMARY, wysokosc=30, szerokosc=88))

    if klucz == "rok_do_roku":
        d = dane["d"]
        roznica = d.get("roznica_koncowa")
        if roznica is None:
            return None, None, "Potrzeba wpisów z dwóch kolejnych lat.", None
        jedn = _jednostka_rdr(d)
        znak = "+" if roznica > 0 else "−" if roznica < 0 else ""
        zdanie = f"{d['etykieta']}: {d['rok']} kontra {d['rok_poprzedni']}"
        if d.get("miesiac_rozjazdu"):
            zdanie += f" · rozjechało się w {MIESIACE_MIEJSCOWNIK[d['miesiac_rozjazdu'] - 1]}"
        chip = (znacznik_trendu(d["zmiana_proc"], wzrost_zly=d.get("wzrost_zly", True), rozmiar=FS["label"])
                if d.get("zmiana_proc") is not None else None)
        return (f"{znak}{formatuj_liczba(abs(roznica), 0)}{jedn}", chip, zdanie,
                mini_dwie_krzywe(d.get("biezacy"), d.get("poprzedni"), szerokosc=88))

    if klucz == "wydatki":
        razem_okresow = [sum(s.values()) for s in dane["sumy"]]
        suma = sum(razem_okresow)
        if suma <= 0 or not dane["miesiecy"]:
            return None, None, f"Brak wydatków {za_okres}.", None
        return (f"{formatuj_liczba(suma / dane['miesiecy'], 0)} {w}", None,
                f"średnio w miesiącu · razem {formatuj_liczba(suma, 0)} {w} {za_okres}",
                mini_slupki(razem_okresow, szerokosc=88))

    if klucz == "struktura":
        k = dane["k"]
        if k["razem"] <= 0:
            return None, None, f"Brak wydatków {za_okres}.", None
        nazwy = {"paliwo": dane["paliwo"], "serwis": "serwis", "inne": "inne koszty"}
        udzialy = [(kat, k[kat] / k["razem"]) for kat in KOLORY_SERII_KOSZTU]
        kat, udzial = max(udzialy, key=lambda u: u[1])
        return (f"{formatuj_liczba(udzial * 100, 0)}% {nazwy[kat]}", None,
                f"z {formatuj_liczba(k['razem'], 0)} {w} {za_okres}",
                pasek_skladu([(u, KOLORY_SERII_KOSZTU[kt]) for kt, u in udzialy], 10, 88, scena))

    if klucz == "kategorie":
        lista = dane["lista"]
        razem = sum(s for _, s, _ in lista)
        if razem <= 0:
            return None, None, f"Brak innych kosztów {za_okres}.", None
        nazwa, suma_kat, _ = lista[0]
        return (f"{formatuj_liczba(suma_kat / razem * 100, 0)}% {nazwa.lower()}", None,
                f"najwięcej z {formatuj_liczba(razem, 0)} {w} innych kosztów {za_okres}",
                pasek_skladu([(s / razem, kolor_kategorii_innych(n)) for n, s, _ in lista], 10, 88, scena))

    if klucz == "robocizna":
        r = dane["r"]
        if not r["napraw"] or r["razem"] <= 0:
            zdanie = ("Żadna naprawa z okresu nie ma podziału na robociznę i części."
                      if r["bez_podzialu"] else f"Brak napraw {za_okres}.")
            return None, None, zdanie, None
        czesci = (r["czesci"] + r["z_magazynu"]) / r["razem"] * 100
        wartosc_w = (f"{formatuj_liczba(czesci, 0)}% to części" if czesci >= 50
                     else f"{formatuj_liczba(100 - czesci, 0)}% to robocizna")
        return (wartosc_w, None,
                f"{db.liczba_z_odmiana(r['napraw'], 'naprawa', 'naprawy', 'napraw')} z podziałem {za_okres}",
                pasek_skladu([(r[kl] / r["razem"], kolor) for kl, _t, _i, kolor in SERIE_ROZBICIA], 10, 88, scena))

    if klucz == "awarie":
        a = dane["a"]
        if not a["naprawy"] and not a["razem"]:
            return None, None, f"Brak napraw {za_okres}.", None
        if a["awarie"] >= 2 and a["odstep_dni"]:
            zdanie = f"awaria średnio co {formatuj_dni(round(a['odstep_dni']))}"
        elif a["awarie"] and a["ostatnia_awaria"]:
            zdanie = f"ostatnia awaria: {a['ostatnia_awaria'].strftime('%d.%m.%Y')}"
        else:
            zdanie = "żadnej awarii"
        udzial = a["udzial_awarii"]
        czesci = [((a["rodzaje"][r]["udzial"] or 0) / 100, KOLORY_RODZAJU_SERWISU[r])
                  for r in (db.SERWIS_AWARIA, db.SERWIS_PLANOWE, db.SERWIS_MODERNIZACJA, None)]
        return (f"{formatuj_liczba(udzial, 0)}% to awarie" if udzial is not None else "—", None,
                f"{zdanie} · {okres}", pasek_skladu(czesci, 10, 88, scena))

    if klucz == "tagi":
        t = dane["t"]
        if not t["tagi"]:
            zdanie = (f"Wpisy {za_okres} nie mają tagów — nadasz je w formularzu wpisu." if t["liczba"]
                      else f"Brak wydatków {za_okres}.")
            return None, None, zdanie, None
        pierwszy = t["tagi"][0]
        suma_tagow = sum(p["kwota"] for p in t["tagi"])
        return (f"{formatuj_liczba(pierwszy['kwota'], 0)} {w}", None,
                f"najwięcej: {pierwszy['nazwa']} · {db.liczba_z_odmiana(len(t['tagi']), 'tag', 'tagi', 'tagów')} "
                f"{za_okres}",
                pasek_skladu([(p["kwota"] / suma_tagow, kolor_tagu_lub_neutralny(p["kolor"])) for p in t["tagi"]],
                             10, 88, scena))

    if klucz == "spalanie":
        if not dane["punkty"] or dane["ostatnia"] is None:
            return None, None, "Potrzeba co najmniej dwóch tankowań do pełna.", None
        trend = dane["trend"]
        if trend:
            wartosc_w = formatuj_spalanie(trend["srednia_ostatnia"], elektryczny=dane["prad"])
            formy = ("ładowanie", "ładowania", "ładowań") if dane["prad"] else ("tankowanie", "tankowania", "tankowań")
            zdanie = (f"ostatnie {db.liczba_z_odmiana(trend['odcinkow_ostatnio'], *formy)} "
                      f"wobec {trend['odcinkow_wczesniej']} wcześniejszych")
        else:
            wartosc_w = formatuj_spalanie(dane["ostatnia"], elektryczny=dane["prad"])
            zdanie = f"z ostatniego odcinka do pełna · {okres}"
        return (wartosc_w, chip_trendu_zuzycia(trend), zdanie,
                sparkline([w_ for _, w_ in dane["punkty"]], KOLOR_SPALANIA, wysokosc=30, szerokosc=88))

    if klucz == "ceny":
        if not dane["punkty"]:
            return None, None, f"Brak {'ładowań' if dane['prad'] else 'tankowań'} {za_okres}.", None
        jedn = dane["jednostka"]
        iskra = sparkline([c for _, c in dane["punkty"]], KOLOR_CEN, wysokosc=30, szerokosc=88)
        stacje = dane["stacje"]
        if not stacje:
            return (f"{formatuj_liczba(dane['punkty'][-1][1], 2)} {w}/{jedn}", None,
                    "Dopisz stację przy tankowaniu, a pokażę najtańszą.", iskra)
        najtansza = stacje[0]
        zdanie = f"średnio {formatuj_liczba(najtansza['srednia_cena'], 2)} {w}/{jedn}"
        if len(stacje) > 1:
            roznica = stacje[-1]["srednia_cena"] - najtansza["srednia_cena"]
            zdanie += f" · o {formatuj_liczba(roznica, 2)} {w}/{jedn} taniej niż {stacje[-1]['nazwa']}"
        return najtansza["nazwa"], None, zdanie, iskra

    return None, None, "", None


def chip_trendu_zuzycia(trend):
    """Kierunek zużycia słowami (po odjęciu pory roku) — działa i dla l/100 km, i dla km/l."""
    if not trend:
        return None
    zmiana = trend["zmiana_po_sezonie"]
    if trend["kierunek"] == "wzrost":
        ikona, kolor, tekst = ft.Icons.TRENDING_UP, KOLOR_STATUS["critical"], f"więcej o {formatuj_liczba(zmiana, 0)}%"
    elif trend["kierunek"] == "spadek":
        ikona, kolor, tekst = ft.Icons.TRENDING_DOWN, KOLOR_STATUS["ok"], f"mniej o {formatuj_liczba(abs(zmiana), 0)}%"
    else:
        ikona, kolor, tekst = ft.Icons.TRENDING_FLAT, KOLOR_STATUS["neutral"], "Stabilnie"
    return ft.Row([ft.Icon(ikona, size=13, color=kolor),
                   ft.Text(tekst, size=FS["label"], color=kolor, no_wrap=True)], spacing=4, tight=True)


def wiersz_spisu(page: ft.Page, state, wpis, scena=None, prad=False):
    """Wiersz spisu: pytanie, odpowiedź liczbą (z chipem), mini-wykres i jedno zdanie; dotyk
    otwiera ekran wykresu."""
    try:
        odpowiedz = _odpowiedz(state, wpis["klucz"], dane_wykresu(state, wpis["klucz"]), scena)
    except Exception:
        log.polkniety(f"wiersz spisu wykresów: {wpis['klucz']}")
        odpowiedz = (None, None, "Nie udało się policzyć — otwórz wykres.", None)
    wartosc_w, chip, zdanie, mini = odpowiedz

    srodek = [ft.Text(wartosc_w or "Brak danych", size=FS["heading"] if wartosc_w else FS["body_strong"],
                      weight="bold" if wartosc_w else "normal",
                      color=ft.Colors.ON_SURFACE if wartosc_w else KOLOR_DRUGIEGO_PLANU,
                      max_lines=2, overflow=ft.TextOverflow.ELLIPSIS, expand=True)]
    if mini is not None:
        srodek.append(mini)
    # Chip trendu stoi przed zdaniem, nie przy liczbie — obok mini-wykresu łamał jednostkę („7,3 l/↵100km”).
    dol = [podpis(zdanie, max_lines=3, overflow=ft.TextOverflow.ELLIPSIS, expand=True)]
    if chip is not None:
        dol.insert(0, chip)

    ikona = wpis.get("ikona_prad") if prad and wpis.get("ikona_prad") else wpis["ikona"]
    return ft.Container(
        padding=ft.Padding(SPACING["md"], 12, SPACING["sm"], 12), ink=True,
        border_radius=RADIUS["md"],
        on_click=lambda e, k=wpis["klucz"]: przejdz(page, f"/wykres/{k}"),
        content=ft.Row([
            ft.Container(padding=9, border_radius=RADIUS["sm"],
                         bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.PRIMARY),
                         content=ft.Icon(ikona, size=18, color=ft.Colors.PRIMARY)),
            ft.Column([
                ft.Row([
                    ft.Text(tekst_wykresu(wpis, "pytanie", prad), size=FS["body_strong"],
                            color=ft.Colors.ON_SURFACE, max_lines=2, expand=True),
                    ft.Icon(ft.Icons.CHEVRON_RIGHT, size=18, color=KOLOR_DRUGIEGO_PLANU),
                ], spacing=4, vertical_alignment=ft.CrossAxisAlignment.START),
                ft.Row(srodek, spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Row(dol, spacing=6, vertical_alignment=ft.CrossAxisAlignment.START),
            ], spacing=4, expand=True),
        ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.START),
    )


def naglowek_analizy(ikona, tytul):
    """Nagłówek grupy w Analizie (Liczby, Wykresy): ikona w barwie motywu, tytuł w kolorze tekstu."""
    return ft.Row([ft.Icon(ikona, size=18, color=ft.Colors.PRIMARY),
                   ft.Text(tytul, size=FS["title"], weight="bold", color=ft.Colors.ON_SURFACE, expand=True)],
                  spacing=SPACING["sm"])


def kafel_liczby(page: ft.Page, ikona, tytul, wartosc_tekst, kolor=ft.Colors.PRIMARY, expand=None,
                 opis=None):
    """Kafel podzakładki Liczby: ikona na podbarwionym tle i etykieta nad wartością, na powierzchni
    jak karty Wykresów (zamiast dawnego ft.Card z ramką). `opis` — drobny dopisek pod wartością
    (np. czego brakuje, zamiast zdania w miejscu liczby)."""
    tresc = [
        ft.Row([
            ft.Container(padding=6, border_radius=RADIUS["xs"], bgcolor=ft.Colors.with_opacity(0.13, kolor),
                         content=ft.Icon(ikona, color=kolor, size=18)),
            etykieta(tytul, size=FS["label"], expand=True, max_lines=2),
        ], spacing=SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        wartosc(wartosc_tekst, size=FS["heading"]),
    ]
    if opis:
        tresc.append(podpis(opis, max_lines=2))
    return ft.Container(
        expand=expand, padding=SPACING["md"], **powierzchnia(page, "karta"),
        content=ft.Column(tresc, spacing=SPACING["sm"]),
    )


def spis_wykresow(page: ft.Page, state, scena=None):
    """Podzakładka Wykresy: na grupę nagłówek i karta z wierszami pytań."""
    prad = _czy_prad(getattr(state, "auto_id", None)) if getattr(state, "auto_id", None) else False
    elementy = [podpis("Dotknij pytania, żeby zobaczyć wykres i to, jak go czytać.")]
    for grupa in GRUPY_WYKRESOW:
        id_grupy, tytul, ikona = GRUPA_ENERGII_PRAD if (prad and grupa[0] == "energia") else grupa
        wiersze = []
        for wpis in (w for w in WYKRESY_ANALIZY if w["grupa"] == id_grupy):
            if wiersze:
                wiersze.append(ft.Divider(height=1, thickness=1, leading_indent=64,
                                          color=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE)))
            wiersze.append(wiersz_spisu(page, state, wpis, scena, prad))
        elementy.append(naglowek_analizy(ikona, tytul))
        elementy.append(ft.Container(padding=ft.Padding(0, 4, 0, 4), **powierzchnia(page, "karta"),
                                     content=ft.Column(wiersze, spacing=0)))
    elementy.append(nota_spisu(page))
    return elementy


# ============================== EKRAN WYKRESU ==============================

def _karta(page, wiersze, spacing=SPACING["md"]):
    return ft.Container(padding=SPACING["lg"], **powierzchnia(page, "karta", cien="md"),
                        content=ft.Column(wiersze, spacing=spacing))


def _brak(page, tekst):
    return _karta(page, [ft.Text(tekst, size=FS["body"], italic=True, color=KOLOR_DRUGIEGO_PLANU)])


def chip_ceny_zakupu(page: ft.Page, dane_skum):
    """Przełącznik „Z ceną zakupu” — tylko gdy jest co doliczyć (data i cena zakupu)."""
    if not (dane_skum.get("cena_zakupu") and dane_skum.get("czy_od_zakupu")):
        return None
    z_zakupem = bool(dane_skum.get("z_cena_zakupu"))

    def przelacz(e):
        db.zapisz_skumulowany_z_cena_zakupu(not db.czy_skumulowany_z_cena_zakupu())
        odswiez_ekran(page)

    return ft.Container(
        height=28, padding=ft.Padding(12, 0, 12, 0),
        border_radius=RADIUS["pill"], ink=True,
        bgcolor=ft.Colors.PRIMARY if z_zakupem else ft.Colors.TRANSPARENT,
        border=None if z_zakupem else ft.Border.all(1, ft.Colors.OUTLINE),
        on_click=przelacz,
        tooltip=("Krzywa startuje od ceny zakupu — dotknij, aby zobaczyć samą eksploatację"
                 if z_zakupem else "Krzywa pokazuje samą eksploatację — dotknij, aby doliczyć cenę zakupu"),
        content=ft.Row([
            ft.Icon(ft.Icons.SHOPPING_CART, size=13,
                    color=ft.Colors.ON_PRIMARY if z_zakupem else ft.Colors.ON_SURFACE_VARIANT),
            ft.Text("Z ceną zakupu", size=FS["caption"], weight="bold" if z_zakupem else "normal",
                    color=ft.Colors.ON_PRIMARY if z_zakupem else ft.Colors.ON_SURFACE_VARIANT, no_wrap=True),
        ], spacing=5, tight=True),
    )


def karta_wydatkow(page: ft.Page, dane, wysokosc_slupka=120):
    """Słupki okresów złożone z paliwa, serwisu i innych (paliwo przy osi), średnia i najdroższy
    okres w nagłówku; kwoty w dymku słupka."""
    w = symbol_waluty()
    okresy, sumy = dane["okresy"], dane["sumy"]
    razem = [sum(s.values()) for s in sumy]
    if sum(razem) <= 0 or not dane["miesiecy"]:
        return _brak(page, "Brak wydatków w wybranym okresie.")
    najwiecej = max(razem)
    ile = len(okresy)
    rozmiar = 11 if ile <= 6 else 10 if ile <= 9 else 9
    szerokosc = 28 if ile <= 6 else 22 if ile <= 9 else 16
    kolumny = []
    for i, (etyk, _) in enumerate(okresy):
        if razem[i] > 0:
            segmenty = [ft.Container(height=max(2, int(sumy[i][kat] / najwiecej * wysokosc_slupka)), bgcolor=kolor)
                        for kat, kolor in reversed(list(KOLORY_SERII_KOSZTU.items())) if sumy[i][kat] > 0]
            opis = "\n".join(f"{db.KATEGORIE_BUDZETU.get(kat, kat)}: {formatuj_liczba(sumy[i][kat], 0)} {w}"
                             for kat in KOLORY_SERII_KOSZTU if sumy[i][kat] > 0)
            dymek = f"{etyk}: {formatuj_liczba(razem[i], 0)} {w}\n{opis}"
        else:
            segmenty = [ft.Container(height=4, bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.ON_SURFACE))]
            dymek = f"{etyk}: bez wydatków"
        biezacy = i == dane["biezacy_okres"]
        kolumny.append(ft.Column([
            ft.Container(width=szerokosc, content=ft.Column(segmenty, spacing=1, tight=True), border_radius=4,
                         clip_behavior=ft.ClipBehavior.HARD_EDGE, tooltip=dymek),
            ft.Text(etyk.replace("/", "\n") if ile > 9 or len(etyk) > 5 else etyk, size=rozmiar,
                    weight="bold" if biezacy else "normal", text_align=ft.TextAlign.CENTER,
                    color=ft.Colors.ON_SURFACE if biezacy else KOLOR_DRUGIEGO_PLANU),
        ], alignment=ft.MainAxisAlignment.END, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=4, expand=True))

    i_max = razem.index(najwiecej)
    naglowek = ft.Row([
        ft.Column([etykieta("Średnio w miesiącu"),
                   wartosc(f"{formatuj_liczba(sum(razem) / dane['miesiecy'], 0)} {w}", size=FS["display"])],
                  spacing=2, expand=True),
        ft.Column([etykieta("Razem"), wartosc(f"{formatuj_liczba(sum(razem), 0)} {w}")],
                  spacing=2, horizontal_alignment=ft.CrossAxisAlignment.END),
    ], vertical_alignment=ft.CrossAxisAlignment.END)
    return _karta(page, [
        naglowek,
        ft.Row(kolumny, spacing=4 if ile <= 9 else 2, vertical_alignment=ft.CrossAxisAlignment.END),
        ft.Row([_kropka_legendy(kolor, db.KATEGORIE_BUDZETU.get(kat, kat)) for kat, kolor in KOLORY_SERII_KOSZTU.items()],
               spacing=SPACING["md"], wrap=True, run_spacing=4),
        podpis(f"Najwięcej: {okresy[i_max][0]} — {formatuj_liczba(najwiecej, 0)} {w}."),
    ])


def karta_struktury(page: ft.Page, dane, scena=None):
    k = dane["k"]
    if k["razem"] <= 0:
        return _brak(page, "Brak wydatków w wybranym okresie.")
    w = symbol_waluty()
    nazwy = {"paliwo": dane["paliwo"].capitalize(), "serwis": "Serwis", "inne": "Inne koszty"}
    wiersze = [
        ft.Column([etykieta(f"Razem — {okres_slowami(dane['zakres'])}"),
                   wartosc(f"{formatuj_liczba(k['razem'])} {w}", size=FS["display"])], spacing=2),
        pasek_skladu([(k[kat] / k["razem"], kolor) for kat, kolor in KOLORY_SERII_KOSZTU.items()], 12),
    ]
    wiersze += [wiersz_udzialu(page, IKONY_KATEGORII_KOSZTOW[kat], nazwy[kat], k[kat], k[kat] / k["razem"] * 100,
                               kolor, scena=scena) for kat, kolor in KOLORY_SERII_KOSZTU.items()]
    return _karta(page, wiersze)


def karta_kategorii(page: ft.Page, dane, scena=None):
    lista = dane["lista"]
    razem = sum(s for _, s, _ in lista)
    if razem <= 0:
        return _brak(page, "Brak innych kosztów w wybranym okresie.")
    wiersze = [
        ft.Column([etykieta(f"Inne koszty — {okres_slowami(dane['zakres'])}"),
                   wartosc(f"{formatuj_liczba(razem)} {symbol_waluty()}", size=FS["display"])], spacing=2),
        pasek_skladu([(s / razem, kolor_kategorii_innych(n)) for n, s, _ in lista], 12),
    ]
    wiersze += [wiersz_udzialu(page, ikona_kategorii_innych(n), n, s, s / razem * 100, kolor_kategorii_innych(n),
                               dopisek=db.liczba_z_odmiana(liczba, "wpis", "wpisy", "wpisów"), scena=scena)
                for n, s, liczba in lista]
    return _karta(page, wiersze)


def karta_spalania(page: ft.Page, dane):
    prad = dane["prad"]
    if len(dane["punkty"]) < 2:
        return _brak(page, f"Za mało danych do wykresu — potrzeba zużycia z co najmniej 2 różnych miesięcy "
                           f"w wybranym zakresie (min. 3 {'ładowania' if prad else 'tankowania'} „do pełna”).")
    jedn = dane["jednostka"]
    trend = dane["trend"]
    naglowek = [ft.Column([
        etykieta(f"Ostatnie {'ładowania' if prad else 'tankowania'} do pełna" if trend else "Ostatni odcinek"),
        wartosc(formatuj_spalanie(trend["srednia_ostatnia"] if trend else dane["ostatnia"], elektryczny=prad),
                size=FS["display"]),
    ], spacing=2, expand=True)]
    chip = chip_trendu_zuzycia(trend)
    if chip is not None:
        naglowek.append(chip)
    wiersze = [ft.Row(naglowek, spacing=SPACING["md"], vertical_alignment=ft.CrossAxisAlignment.CENTER),
               wykres_miesieczny(page, dane["punkty"], KOLOR_SPALANIA, lambda v: f"{formatuj_liczba(v, 1)} {jedn}",
                                 srednia=dane["srednia_ekran"])]
    if dane["srednia_ekran"]:
        wiersze.append(_kropka_legendy(KOLOR_DRUGIEGO_PLANU, f"średnia z okresu: "
                                       f"{formatuj_liczba(dane['srednia_ekran'], 1)} {jedn}", obwodka=True))
    sezon = db.opis_sezonowosci_trendu(trend)
    if sezon:
        wiersze.append(podpis(sezon))
    return _karta(page, wiersze)


def karta_cen(page: ft.Page, dane):
    jedn = dane["jednostka"]
    w = symbol_waluty()
    if len(dane["punkty"]) < 2:
        return _brak(page, f"Za mało danych do wykresu cen — potrzeba {'ładowań' if dane['prad'] else 'tankowań'} "
                           "z co najmniej 2 różnych miesięcy w wybranym zakresie.")
    ostatni_klucz, ostatnia = dane["punkty"][-1]
    pierwsza = dane["punkty"][0][1]
    naglowek = [ft.Column([etykieta(f"Średnia cena w {ostatni_klucz[5:7]}/{ostatni_klucz[:4]}"),
                           wartosc(f"{formatuj_liczba(ostatnia, 2)} {w}/{jedn}", size=FS["display"])],
                          spacing=2, expand=True)]
    if pierwsza > 0:
        naglowek.append(znacznik_trendu((ostatnia - pierwsza) / pierwsza * 100, wzrost_zly=True, rozmiar=FS["label"]))
    wiersze = [ft.Row(naglowek, spacing=SPACING["md"], vertical_alignment=ft.CrossAxisAlignment.CENTER),
               wykres_miesieczny(page, dane["punkty"], KOLOR_CEN, lambda v: f"{formatuj_liczba(v, 2)} {w}/{jedn}",
                                 srednia=dane["srednia"], dziesietne=2)]
    if dane["srednia"]:
        wiersze.append(_kropka_legendy(KOLOR_DRUGIEGO_PLANU, f"średnia z okresu: {formatuj_liczba(dane['srednia'], 2)} "
                                       f"{w}/{jedn}", obwodka=True))
    return _karta(page, wiersze)


def karta_stacji(page: ft.Page, dane):
    jedn = dane["jednostka"]
    w = symbol_waluty()
    stacje = dane["stacje"][:6]
    if not stacje:
        return _brak(page, "Dopisuj stację przy tankowaniu, a ranking pokaże najtańsze miejsca."
                     if not dane["prad"] else "Dopisuj punkt ładowania, a ranking pokaże najtańsze miejsca.")
    wiersze = [ft.Row([ft.Icon(ft.Icons.EMOJI_EVENTS, size=18, color=KOLOR_STATUS["accent"]),
                       ft.Text(f"Ranking {'punktów' if dane['prad'] else 'stacji'} — średnia cena",
                               size=FS["body_strong"], weight="bold", expand=True)], spacing=SPACING["sm"])]
    for i, s in enumerate(stacje):
        wiersze.append(ft.Row([
            ft.Text(f"{i + 1}.", size=FS["body"], color=KOLOR_DRUGIEGO_PLANU, width=22),
            ft.Text(s["nazwa"], size=FS["body"], weight="bold" if i == 0 else "normal", color=ft.Colors.ON_SURFACE,
                    max_lines=2, overflow=ft.TextOverflow.ELLIPSIS, expand=True),
            ft.Text(f"{formatuj_liczba(s['srednia_cena'], 2)} {w}/{jedn}", size=FS["body"],
                    weight="bold" if i == 0 else "normal", color=ft.Colors.ON_SURFACE, no_wrap=True),
            ft.Text(f"{s['liczba_tankowan']}×", size=FS["label"], color=KOLOR_DRUGIEGO_PLANU, no_wrap=True,
                    width=30, text_align=ft.TextAlign.RIGHT),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER))
    if len(dane["stacje"]) > 1:
        roznica = dane["stacje"][-1]["srednia_cena"] - stacje[0]["srednia_cena"]
        wiersze.append(podpis(f"{stacje[0]['nazwa']} wychodzi średnio o {formatuj_liczba(roznica, 2)} {w}/{jedn} "
                              f"taniej niż {dane['stacje'][-1]['nazwa']}."))
    return _karta(page, wiersze, spacing=10)


def _szukaj_tagu(page: ft.Page, state, nazwa, od=None):
    """Wyszukiwarka z operatorem tagu (w cudzysłowie, gdy nazwa ma spację) od granicy zakresu."""
    fraza = f'tag:"{nazwa}"' if " " in nazwa else f"tag:{nazwa}"
    if od:
        fraza += f" od {od.strftime('%d.%m.%Y')}"
    state.fraza_wyszukiwania = fraza
    przejdz(page, "/szukaj")


def karta_tagow(page: ft.Page, state, dane, scena=None):
    """Suma na tag z udziałem we WSZYSTKICH wydatkach okresu; dotknięcie tagu — jego wpisy."""
    t = dane["t"]
    if not t["tagi"]:
        return _brak(page, "Żaden wpis z wybranego okresu nie ma tagu. Tag nadasz w formularzu tankowania, "
                           "wizyty albo innego kosztu.")
    razem = t["razem"]
    w = symbol_waluty()
    wiersze = [ft.Column([etykieta(f"Wydatki z tagami — {okres_slowami(dane['zakres'])}"),
                          wartosc(f"{formatuj_liczba(razem - t['bez_tagu']['kwota'])} {w}", size=FS["display"]),
                          podpis(f"z {formatuj_liczba(razem)} {w} wszystkich wydatków")], spacing=2)]
    for p in t["tagi"]:
        wiersze.append(ft.Container(
            ink=True, border_radius=RADIUS["sm"], tooltip=f"Pokaż wpisy z tagiem „{p['nazwa']}”",
            on_click=lambda e, n=p["nazwa"]: _szukaj_tagu(page, state, n, dane["granica"]),
            content=wiersz_udzialu(page, ft.Icons.SELL, p["nazwa"], p["kwota"], p["kwota"] / razem * 100,
                                   kolor_tagu_lub_neutralny(p["kolor"]), scena=scena,
                                   dopisek=db.liczba_z_odmiana(p["liczba"], "wpis", "wpisy", "wpisów")),
        ))
    bez = t["bez_tagu"]
    if bez["liczba"]:
        wiersze.append(wiersz_udzialu(page, ft.Icons.LABEL_OFF_OUTLINED, "Bez tagu", bez["kwota"],
                                      bez["kwota"] / razem * 100, ft.Colors.OUTLINE, scena=scena,
                                      dopisek=db.liczba_z_odmiana(bez["liczba"], "wpis", "wpisy", "wpisów")))
    wiersze.append(nota_o_liczeniu(
        page, "Jak liczone",
        "Liczą się tankowania, wizyty i inne koszty — tylko one mają tagi. Wpis z kilkoma tagami liczy się "
        "przy każdym z nich, więc tagi razem mogą dać więcej niż wydatki; procent to udział we wszystkich "
        "wydatkach okresu."))
    return _karta(page, wiersze)


def tresc_wykresu(page: ft.Page, state, klucz, scena=None):
    """Kontrolki ekranu wykresu pod wstępem: przełączniki (każdy w swoim wierszu, żeby na 360 dp
    nic się nie ścisnęło) i karta(y)."""
    auto_id = getattr(state, "auto_id", None)
    dane = dane_wykresu(state, klucz, pelne=True)

    if klucz == "skumulowany":
        chip = chip_ceny_zakupu(page, dane["skum"])
        return [k for k in (chip, pasek_zakresu_czasu(page, state, "skumulowany"),
                            karta_kosztu_skumulowanego(page, dane["skum"], od_daty=dane["granica"]))
                if k is not None]
    if klucz == "koszt1000":
        return [pasek_okna_kroczacego(page, state), karta_kosztu_1000km(page, dane["d"])]
    if klucz == "rok_do_roku":
        return [pasek_lat_rdr(page, state), karta_rok_do_roku(page, state)]
    if klucz == "wydatki":
        return [pasek_zakresu_czasu(page, state, "wydatki"), karta_wydatkow(page, dane)]
    if klucz == "struktura":
        return [pasek_zakresu_czasu(page, state, "struktura"), karta_struktury(page, dane, scena)]
    if klucz == "kategorie":
        return [pasek_zakresu_czasu(page, state, "kategorie"), karta_kategorii(page, dane, scena)]
    if klucz == "robocizna":
        r = dane["r"]
        naglowek = [ft.Column([etykieta(f"Rachunki z podziałem — {okres_slowami(dane['zakres'])}"),
                               wartosc(f"{formatuj_liczba(r['razem'])} {symbol_waluty()}", size=FS["display"])],
                              spacing=2)] if r["napraw"] else []
        return [pasek_zakresu_czasu(page, state, "robocizna"),
                karta_robocizny_i_czesci(page, r, dane["porownania"], scena, naglowek=naglowek)]
    if klucz == "awarie":
        return [pasek_zakresu_czasu(page, state, "awarie"),
                karta_awarii(page, auto_id, dane["a"], dane["zakres"], scena,
                             po_zmianie=lambda: odswiez_ekran(page))]
    if klucz == "tagi":
        return [pasek_zakresu_czasu(page, state, "tagi"), karta_tagow(page, state, dane, scena)]
    if klucz == "spalanie":
        return [pasek_zakresu_czasu(page, state, "spalanie"), karta_spalania(page, dane)]
    if klucz == "ceny":
        return [pasek_zakresu_czasu(page, state, "ceny"), karta_cen(page, dane), karta_stacji(page, dane)]
    return []


def wstep_wykresu(page: ft.Page, wpis, prad=False):
    """Pytanie i „jak czytać” nad wykresem — tło w barwie motywu, jak opis na Budżecie."""
    return ft.Container(
        padding=SPACING["md"], border_radius=RADIUS["lg"],
        bgcolor=ft.Colors.with_opacity(0.07, ft.Colors.PRIMARY),
        content=ft.Row([
            ft.Icon(wpis.get("ikona_prad") if prad and wpis.get("ikona_prad") else wpis["ikona"],
                    size=20, color=ft.Colors.PRIMARY),
            ft.Column([
                ft.Text(tekst_wykresu(wpis, "pytanie", prad), size=FS["title"], weight="bold",
                        color=ft.Colors.ON_SURFACE),
                ft.Text(tekst_wykresu(wpis, "opis", prad), size=FS["body"], color=ft.Colors.ON_SURFACE_VARIANT),
            ], spacing=4, expand=True),
        ], spacing=SPACING["sm"], vertical_alignment=ft.CrossAxisAlignment.START),
    )


def karta_nastepnego(page: ft.Page, klucz, prad=False):
    """Na dole ekranu: odnośnik do następnego wykresu, za ostatnim — powrót do spisu."""
    nastepny = nastepny_wykres(klucz)
    if nastepny is None:
        tytul, tekst, ikona, trasa = "To był ostatni wykres", "Wróć do wszystkich wykresów", ft.Icons.APPS, "/"
    else:
        wpis = wykres_analizy(nastepny)
        tytul, tekst, trasa = "Następny wykres", tekst_wykresu(wpis, "pytanie", prad), f"/wykres/{nastepny}"
        ikona = wpis.get("ikona_prad") if prad and wpis.get("ikona_prad") else wpis["ikona"]
    return ft.Container(
        padding=ft.Padding(SPACING["md"], 12, SPACING["sm"], 12), ink=True,
        **powierzchnia(page, "karta"),
        on_click=lambda e: przejdz(page, trasa),
        content=ft.Row([
            ft.Icon(ikona, size=20, color=ft.Colors.PRIMARY),
            ft.Column([etykieta(tytul), ft.Text(tekst, size=FS["body_strong"], color=ft.Colors.ON_SURFACE)],
                      spacing=2, expand=True),
            ft.Icon(ft.Icons.CHEVRON_RIGHT, size=20, color=KOLOR_DRUGIEGO_PLANU),
        ], spacing=SPACING["md"], vertical_alignment=ft.CrossAxisAlignment.CENTER),
    )


def nota_spisu(page: ft.Page):
    """Nota pod spisem: skąd liczby i gdzie ustawia się zakres."""
    return nota_o_liczeniu(
        page, "Jak liczone",
        "Każdy wykres pamięta swój zakres czasu osobno dla pojazdu — zmienia się go na ekranie wykresu, "
        "a liczba w spisie liczy się z tego samego okresu. Wizyta zbiorcza wchodzi jako całość, a jej "
        "pozycje nie liczą się drugi raz.",
    )


__all__ = [
    "GRUPA_ENERGII_PRAD",
    "GRUPY_WYKRESOW",
    "KLUCZE_WYKRESOW",
    "KOLOR_CEN",
    "KOLOR_SPALANIA",
    "WYKRESY_ANALIZY",
    "_OKRESY_MIANOWNIK",
    "_odpowiedz",
    "chip_ceny_zakupu",
    "chip_trendu_zuzycia",
    "dane_wykresu",
    "karta_cen",
    "karta_kategorii",
    "karta_nastepnego",
    "karta_spalania",
    "karta_stacji",
    "karta_struktury",
    "karta_tagow",
    "karta_wydatkow",
    "kafel_liczby",
    "naglowek_analizy",
    "nastepny_wykres",
    "nota_spisu",
    "okres_slowami",
    "spis_wykresow",
    "tekst_wykresu",
    "tresc_wykresu",
    "wiersz_spisu",
    "wstep_wykresu",
    "wykres_analizy",
]
