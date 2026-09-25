"""Jednostka dystansu: kilometry albo mile.

Baza trzyma wszystko w km, a mile istnieją tylko na ekranie, w plikach i przy
wpisywaniu (db/jednostki.py). Ten plik pilnuje czterech rzeczy:

1. **Przeliczanie w obie strony** — całe mile wracają na ekran bez zmian,
   a pole, którego nikt nie ruszył, wraca do bazy co do kilometra (inaczej
   poprawka ceny tankowania przesuwałaby licznik, a nowy wpis z podpowiedzianym
   licznikiem dostawałby ostrzeżenie „niższy niż najwyższy”).
2. **Ustawienia** — przełącznik km/mi podpowiada naturalną parę jednostek
   zużycia, powrót przywraca poprzednią, a próg ostrzegania staje się okrągłą
   liczbą mil. Lista jednostek zużycia elektryka znów stoi na ekranie.
3. **Cała aplikacja w milach** — każdy ekran buduje się z jednostką „mi”
   i nigdzie nie zostaje samotne „km”.
4. **Pliki** — eksport CSV i raport PDF idą za Ustawieniami, import rozpoznaje
   „(mi)” w nagłówku, a eksport w milach wraca importem do tych samych km.
"""

import re
from datetime import date, timedelta

import flet as ft
import pytest

import db
import pomoce
import utils


# Samodzielne „km” — nie część „km/l”, „/100km”, „kWh/100km” ani słowa.
SAMOTNE_KM = re.compile(r"(?<![\w/])km(?![\w/])")

POLA_DZIECI = ("controls", "content", "appbar", "floating_action_button", "drawer",
               "navigation_bar", "actions", "title", "subtitle", "leading", "trailing", "items")


def _kontrolki(korzen, limit=30000):
    do_odwiedzenia, widziane = [korzen], 0
    while do_odwiedzenia and widziane < limit:
        biezaca = do_odwiedzenia.pop()
        widziane += 1
        yield biezaca
        for nazwa in POLA_DZIECI:
            wartosc = getattr(biezaca, nazwa, None)
            if isinstance(wartosc, (list, tuple)):
                do_odwiedzenia.extend(w for w in wartosc if isinstance(w, ft.Control))
            elif isinstance(wartosc, ft.Control):
                do_odwiedzenia.append(wartosc)


def _napisy(korzen):
    """Wszystko, co człowiek przeczyta: teksty, etykiety i podpowiedzi pól, opcje list."""
    zebrane = []
    for k in _kontrolki(korzen):
        if isinstance(k, ft.Text):
            zebrane.append(k.value)
            zebrane.extend(getattr(s, "text", None) for s in (k.spans or []))
        if isinstance(k, (ft.TextField, ft.Dropdown)):
            zebrane.extend([k.label, getattr(k, "hint_text", None)])
        if isinstance(k, ft.Dropdown):
            zebrane.extend(o.text for o in (k.options or []))
        if isinstance(getattr(k, "tooltip", None), str):
            zebrane.append(k.tooltip)
    return [str(n) for n in zebrane if isinstance(n, str) and n]


def _widok(nazwa, stan, identyfikatory=None):
    strona = pomoce.zbuduj_strone()
    return strona, pomoce.zbuduj_widok(pomoce.klasy_widokow()[nazwa], strona, stan, identyfikatory)


# ------------------------------------------------------------------- rdzeń


def test_cale_mile_wracaja_na_ekran_bez_zmian():
    for mile in range(0, 400000, 997):
        km = db.dystans_na_km(mile, "mi", calkowity=True)
        assert round(db.dystans_z_km(km, "mi")) == mile


def test_nieruszone_pole_wraca_do_bazy_co_do_kilometra():
    # 19 868 km to 12 345 mi, ale 12 345 mi to już 19 867 km.
    assert db.wartosc_pola_dystansu(19868, "mi") == "12345"
    assert db.dystans_na_km(12345, "mi", calkowity=True) == 19867
    assert db.dystans_na_km(12345, "mi", calkowity=True, km_przy_otwarciu=19868) == 19868
    assert db.dystans_na_km(12346, "mi", calkowity=True, km_przy_otwarciu=19868) == 19869
    assert db.dystans_na_km(300, "mi", km_przy_otwarciu=482.8032) == 482.8032
    assert db.dystans_na_km(0, "mi", calkowity=True, km_przy_otwarciu=19868) == 0, "wyczyszczone pole to zero"


def test_pole_z_ulamkiem_pokazuje_ulamek_tylko_gdy_jest():
    assert db.wartosc_pola_dystansu(450.0, "km", decimale=2) == "450"
    assert db.wartosc_pola_dystansu(450.55, "km", decimale=2) == "450,55"
    assert db.wartosc_pola_dystansu(None, "mi") == ""


def test_etykieta_rusza_tylko_samodzielne_km():
    assert db.etykieta_z_dystansem("Koszt / 1000 km (okno)", "mi") == "Koszt / 1000 mi (okno)"
    assert db.etykieta_z_dystansem("Przebieg (km)", "mi") == "Przebieg (mi)"
    for bez_zmian in ("l/100km", "km/l", "kWh/100km", "Moc silnika (KM)"):
        assert db.etykieta_z_dystansem(bez_zmian, "mi") == bez_zmian
    assert db.etykieta_z_dystansem("Koszt / 1000 km (okno)", "km") == "Koszt / 1000 km (okno)"


def test_progi_w_milach_sa_okragle_a_zapisany_nie_znika():
    opcje = db.opcje_progow_km("mi", obecny_km=1500)
    podpisy = [p for _, p in opcje]
    assert {"300 mi", "1 000 mi", "3 000 mi"} <= set(podpisy)
    assert (1500, "932 mi") in opcje, "zapisany próg spoza listy zostaje jako opcja"
    assert db.najblizszy_prog_km(1500, "mi") == 1609
    assert db.najblizszy_prog_km(1609, "km") == 1500


def test_galon_brytyjski_daje_o_jedna_piata_wiecej():
    assert 282.480936 / 235.214583 == pytest.approx(4.54609 / 3.785411784)


# --------------------------------------------------------------- ustawienia


def test_domyslnie_kilometry_i_nic_sie_nie_zmienia(baza):
    assert db.pobierz_jednostke_dystansu() == "km"
    assert db.dystans_z_km(150000) == 150000
    assert db.dystans_na_km("150000", calkowity=True) == 150000
    assert utils.formatuj_dystans(123456) == "123 456 km"
    assert db.na_jednostke_dystansu(0.73) == 0.73


def test_zapis_nieznanej_jednostki_wraca_do_km(baza):
    db.zapisz_jednostke_dystansu("furlongi")
    assert db.pobierz_jednostke_dystansu() == "km"


def test_mile_na_ekranie_i_przy_wpisywaniu(baza):
    db.zapisz_jednostke_dystansu("mi")
    assert utils.formatuj_dystans(160934.4) == "100 000 mi"
    assert db.dystans_na_km(100, calkowity=True) == 161
    assert db.na_jednostke_dystansu(1.0) == pytest.approx(1.609344), "koszt mili jest większy niż kilometra"
    assert utils.formatuj_na_dystans(0.5, "zł/") == "0,80 zł/mi"
    assert db.etykiety_wielkosci_rdr()["km"] == "Mile"


@pytest.mark.parametrize("klucz, oczekiwane, podpis", [
    ("l/100km", 5.0, "l/100km"),
    ("km/l", 20.0, "km/l"),
    ("mpg", 235.214583 / 5, "mpg"),
    ("mpg UK", 282.480936 / 5, "mpg"),
])
def test_spalanie_we_wszystkich_jednostkach(baza, klucz, oczekiwane, podpis):
    db.zapisz_ustawienie("jednostka_spalania", klucz)
    wartosc, jednostka = db.przelicz_zuzycie(5.0)
    assert wartosc == pytest.approx(oczekiwane) and jednostka == podpis


def test_zuzycie_elektryka_w_milach(baza):
    db.zapisz_ustawienie("jednostka_zuzycia_ev", "kWh/100mi")
    wartosc, jednostka = db.przelicz_zuzycie(18.0, elektryczny=True)
    assert (wartosc, jednostka) == (pytest.approx(18.0 * 1.609344), "kWh/100mi")
    db.zapisz_ustawienie("jednostka_zuzycia_ev", "mi/kWh")
    assert db.przelicz_zuzycie(18.0, elektryczny=True)[0] == pytest.approx(100 / 1.609344 / 18.0)


def test_lista_jednostek_elektryka_jest_na_ekranie(baza):
    """Lista była budowana i zapisywana, ale nie trafiała do układu Ustawień."""
    _, widok = _widok("UstawieniaView", pomoce.stan_aplikacji())
    kontrolki = list(_kontrolki(widok))
    assert any(k is widok.e_jednostka_ev for k in kontrolki)
    assert any(k is widok.przelacznik_dystansu for k in kontrolki)
    assert "mpg (UK)" in [o.text for o in widok.e_jednostka.options]


def test_przelacznik_podpowiada_pare_i_wraca_do_poprzedniej(baza):
    db.zapisz_ustawienie("jednostka_spalania", "km/l")
    _, widok = _widok("UstawieniaView", pomoce.stan_aplikacji())
    assert widok.e_prog_km.value == "1500"

    widok._przelacz_dystans(1)
    assert (widok.e_jednostka.value, widok.e_jednostka_ev.value) == ("mpg", "kWh/100mi")
    assert widok.e_prog_km.value == "1609" and "mil" in widok.e_prog_km.label
    assert widok._czy_zmieniono()

    widok._przelacz_dystans(0)
    assert (widok.e_jednostka.value, widok.e_jednostka_ev.value) == ("km/l", "kWh/100km")
    assert widok.e_prog_km.value == "1500"
    assert not widok._czy_zmieniono(), "tam i z powrotem to brak zmian"


def test_zapis_ustawien_zapamietuje_mile(baza):
    strona, widok = _widok("UstawieniaView", pomoce.stan_aplikacji())
    strona.page.on_route_change = lambda e: None  # zapis wraca na kokpit
    widok._przelacz_dystans(1)
    widok.zapisz(None)
    assert db.pobierz_jednostke_dystansu() == "mi"
    assert db.pobierz_jednostke_spalania() == "mpg"
    assert db.pobierz_prog_km() == 1609


# --------------------------------------------------------------- formularze


def test_edycja_tankowania_w_milach_nie_przesuwa_licznika(baza):
    identyfikatory = pomoce.utworz_pojazd("Z USA")
    with db.polacz_baze() as conn:
        t_id, km = conn.execute(
            "SELECT id, przebieg FROM tankowania WHERE auto_id=? ORDER BY przebieg DESC LIMIT 1",
            (identyfikatory["auto_id"],)).fetchone()
        conn.execute("UPDATE tankowania SET przebieg=? WHERE id=?", (km + 1, t_id))
    km += 1  # licznik, który w milach NIE jest całą liczbą mil
    db.zapisz_jednostke_dystansu("mi")
    stan = pomoce.stan_aplikacji(identyfikatory["auto_id"], "Z USA")
    _, widok = _widok("FormularzTankowanieView", stan, dict(identyfikatory, tankowanie=t_id))

    assert widok.e_p.label == "Licznik (mi)"
    assert widok.e_p.value == str(round(km / 1.609344))
    assert widok._przebieg_z_pol() == km, "nieruszone pole — te same kilometry"
    widok.e_p.value = str(round(km / 1.609344) + 10)
    assert widok._przebieg_z_pol() == round((round(km / 1.609344) + 10) * 1.609344)


# ------------------------------------------------------ cała aplikacja w milach


def _bez_samotnego_km(napisy):
    return [n for n in napisy if SAMOTNE_KM.search(n)]


@pytest.mark.parametrize("scenariusz", ["pojazd_z_historia", "elektryk"])
@pytest.mark.parametrize("nazwa_widoku", [n for n in pomoce.klasy_widokow() if n != "UstawieniaView"])
def test_w_milach_zaden_ekran_nie_pokazuje_km(baza, nazwa_widoku, scenariusz):
    """Ustawienia są wyjątkiem z definicji — to tam stoi przełącznik „km | mi”."""
    db.zapisz_jednostke_dystansu("mi")
    stan, identyfikatory = pomoce.przygotuj_scenariusz(scenariusz)
    _, widok = _widok(nazwa_widoku, stan, identyfikatory)
    assert _bez_samotnego_km(_napisy(widok)) == []


@pytest.mark.parametrize("zakladka, podzakladka", [(0, 0), (1, 0), (2, 0), (2, 1), (3, 0)])
def test_w_milach_zadna_zakladka_nie_pokazuje_km(baza, zakladka, podzakladka):
    db.zapisz_jednostke_dystansu("mi")
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_historia")
    db.zapisz_widgety_kokpitu(list(db.KOKPIT_WIDGETY), stan.auto_id)
    stan.zakladka, stan.koszty_podzakladka = zakladka, podzakladka
    _, widok = _widok("MainView", stan)
    assert _bez_samotnego_km(_napisy(widok)) == []


def test_teksty_warstwy_danych_w_milach(baza):
    identyfikatory = pomoce.utworz_pojazd("Obserwowany")
    pomoce.dosyp_dane(identyfikatory["auto_id"])
    db.zapisz_jednostke_dystansu("mi")
    auto_id = identyfikatory["auto_id"]
    teksty = [z[4] for z in db.pobierz_dane_timeline(auto_id)]
    teksty += [p.get("opis") or "" for p in db.pobierz_powiadomienia(auto_id, pomin_wyciszone=False)]
    teksty += [o["tekst"] for o in db.obserwacje_analityczne(auto_id)]
    teksty += [w["opis"] for w in db.wyszukiwanie._wszystkie_wpisy(auto_id)]
    assert any(" mi" in t for t in teksty)
    assert _bez_samotnego_km(teksty) == []


def test_porownanie_dwoch_aut_w_milach(baza):
    db.zapisz_jednostke_dystansu("mi")
    pierwszy = pomoce.utworz_pojazd("Pierwszy")["auto_id"]
    pomoce.utworz_pojazd("Drugi")
    stan = pomoce.stan_aplikacji(pierwszy, "Pierwszy")
    stan.porownanie_piata_os = "Koszt / 1000 km (okno)"
    _, widok = _widok("PorownanieView", stan)
    napisy = _napisy(widok)
    assert any(n.endswith(" mi") or "/mi" in n for n in napisy)
    assert "Koszt / 1000 mi (okno)" in napisy
    assert _bez_samotnego_km(napisy) == []


# -------------------------------------------------------------------- pliki


def test_eksport_w_milach_ma_naglowki_i_liczby_w_milach(baza):
    auto_id = pomoce.utworz_pojazd("Eksport")["auto_id"]
    with db.polacz_baze() as conn:
        km = sorted(p for (p,) in conn.execute("SELECT przebieg FROM tankowania WHERE auto_id=?", (auto_id,)))
    db.zapisz_jednostke_dystansu("mi")

    naglowki, wiersze = db.pobierz_dane_eksportu(auto_id, ["tankowania"])["tankowania"]
    assert naglowki[1:3] == ["Przebieg (mi)", "Dystans (mi)"]
    assert sorted(w[1] for w in wiersze) == [round(k / 1.609344) for k in km]


def test_eksport_w_milach_wraca_importem_z_dokladnoscia_do_kilometra(baza):
    """Plik ma całe mile, a pół mili to 0,8 km — więcej niż kilometra zgubić się nie da."""
    auto_id = pomoce.utworz_pojazd("Tam")["auto_id"]
    db.zapisz_jednostke_dystansu("mi")
    naglowki, wiersze = db.pobierz_dane_eksportu(auto_id, ["odczyty_przebiegu"])["odczyty_przebiegu"]
    with db.polacz_baze() as conn:
        km = sorted(p for (p,) in conn.execute("SELECT przebieg FROM odczyty_przebiegu WHERE auto_id=?", (auto_id,)))

    db.zapisz_jednostke_dystansu("km")  # importuje ktoś, kto liczy w km
    drugie = pomoce.utworz_pojazd("Z powrotem")["auto_id"]
    with db.polacz_baze() as conn:
        conn.execute("DELETE FROM odczyty_przebiegu WHERE auto_id=?", (drugie,))
    tekstowe = [[str(k) for k in w] for w in wiersze]
    mapowanie = db.dopasuj_kolumny_odczytow(naglowki)
    assert db.rozpoznaj_jednostke_pliku(naglowki, mapowanie) == "mi"
    raport = db.przygotuj_import_odczytow(drugie, naglowki, tekstowe, mapowanie, jednostka_pliku="mi")
    wrocone = sorted(g["przebieg"] for g in raport["gotowe"])
    assert len(wrocone) == len(km) and all(abs(a - b) <= 1 for a, b in zip(wrocone, km))


@pytest.mark.parametrize("naglowek, oczekiwana", [
    ("Przebieg (mi)", "mi"), ("Odometer miles", "mi"), ("Licznik (km)", "km"),
    ("Przebieg", None), ("Mileage", None),
])
def test_import_rozpoznaje_jednostke_z_naglowka(naglowek, oczekiwana):
    naglowki = ["Data", naglowek, "Litry", "Kwota"]
    mapowanie = db.dopasuj_kolumny_tankowan(naglowki)
    assert mapowanie["przebieg"] == 1
    assert db.rozpoznaj_jednostke_pliku(naglowki, mapowanie) == oczekiwana


def test_import_tankowan_z_pliku_w_milach_zapisuje_km(baza):
    auto_id = pomoce.utworz_pojazd("Import")["auto_id"]
    naglowki = ["Data", "Przebieg (mi)", "Dystans (mi)", "Litry", "Kwota"]
    wiersze = [[(date.today() - timedelta(days=3)).strftime("%d.%m.%Y"), "100000", "300", "40", "250"]]
    mapowanie = db.dopasuj_kolumny_tankowan(naglowki)
    raport = db.przygotuj_import_tankowan(auto_id, naglowki, wiersze, mapowanie, jednostka_pliku="mi")
    assert raport["gotowe"][0]["przebieg"] == 160934
    assert raport["gotowe"][0]["dystans"] == pytest.approx(482.8032)


def test_ekran_importu_rozpoznaje_mile_i_pozwala_przelaczyc(baza):
    auto_id = pomoce.utworz_pojazd("Z pliku")["auto_id"]
    _, widok = _widok("ImportCSVView", pomoce.stan_aplikacji(auto_id, "Z pliku"))
    widok.naglowki = ["Data", "Przebieg (mi)", "Litry", "Kwota"]
    widok.wiersze = [[(date.today() - timedelta(days=2)).strftime("%d.%m.%Y"), "100000", "40", "250"]]

    widok._zbuduj_mapowanie()
    widok._odswiez_podglad()
    assert widok.jednostka_pliku == "mi" and widok.dropdowny["przebieg"].label == "Licznik (mi)"
    assert widok.gotowe[0]["przebieg"] == 160934

    widok._zmien_jednostke_pliku(0)
    assert widok.dropdowny["przebieg"].label == "Licznik (km)"
    assert widok.gotowe[0]["przebieg"] == 100000


def test_raport_pdf_w_milach(baza, monkeypatch):
    from db import raporty

    auto_id = pomoce.utworz_pojazd("Paszport")["auto_id"]
    pomoce.dosyp_dane(auto_id)  # kilka tankowań z licznikiem — jest z czego liczyć dystans
    db.zapisz_jednostke_dystansu("mi")
    napisy = []
    oryginal = raporty._RaportPDF.cell

    def cell(self, *argumenty, **nazwane):
        if len(argumenty) >= 3:
            napisy.append(str(argumenty[2]))
        return oryginal(self, *argumenty, **nazwane)

    monkeypatch.setattr(raporty._RaportPDF, "cell", cell)
    pdf = db.generuj_pdf_raportu(
        "Paszport", db.pobierz_dane_eksportu(auto_id, ["tankowania"]), "cały okres",
        podsumowanie=db.oblicz_podsumowanie_okresu(auto_id), tryb_paszportu=True,
        **db.pobierz_dane_paszportu(auto_id),
    )

    assert pdf.startswith(b"%PDF")
    assert any(n.startswith("Przejechany dystans:") and n.endswith(" mi") for n in napisy)
    assert "Przebieg (mi)" in napisy
    assert _bez_samotnego_km(napisy) == []
