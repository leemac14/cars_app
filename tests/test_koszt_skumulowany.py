"""Koszt skumulowany: krzywa, której nie da się uśrednić.

Słupek miesięczny chowa przegląd za cztery tysiące między tankowaniami i po
kwartale nie widać go wcale. Suma narastająca zostawia każdy wydatek na sobie
na zawsze, więc jako jedyna pokazuje prawdziwą skalę rachunku za auto.

Testy pilnują trzech rzeczy, na których ta krzywa stoi: że oś zaczyna się tam,
gdzie trzeba (data i cena zakupu, a bez nich pierwszy wpis), że rachunek się
domyka (ostatni punkt = wszystko, co auto kosztowało), i że znacznik dostaje
wydatek ODSTAJĄCY, a nie co drugie tankowanie. Plus jedna umowa o zakresie
czasu: przycina WIDOK, nie rachunek.
"""

from datetime import date, timedelta

import flet as ft

import db
import pomoce
import utils

POLA_DZIECI = ("controls", "content", "items", "actions", "leading", "trailing", "title", "subtitle")


def _auto(cena_zakupu=60000.0, dni_temu_zakup=400, przebieg_zakupu=100000, **nadpisania):
    """Pojazd z wypełnioną kartą zakupu — bez niej krzywa nie ma od czego ruszyć."""
    pola = {
        "nazwa": "Skumulowany",
        "typ_paliwa": "Benzyna",
        "status": db.STATUS_POJAZDU_AKTYWNY,
        "data_zakupu": (date.today() - timedelta(days=dni_temu_zakup)).strftime("%d.%m.%Y")
        if dni_temu_zakup is not None else None,
        "cena_zakupu": cena_zakupu,
        "przebieg_zakupu": przebieg_zakupu,
    }
    pola.update(nadpisania)
    kolumny = [k for k, v in pola.items() if v is not None]
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            f"INSERT INTO samochody ({','.join(kolumny)}) VALUES ({','.join('?' * len(kolumny))})",
            [pola[k] for k in kolumny],
        )
        return c.lastrowid


def _tankowanie(auto_id, dni_temu, kwota, przebieg=110000, stacja="Orlen"):
    with db.polacz_baze() as conn:
        conn.execute(
            "INSERT INTO tankowania (auto_id, data, przebieg, litry, kwota, stacja) VALUES (?,?,?,?,?,?)",
            (auto_id, (date.today() - timedelta(days=dni_temu)).strftime("%d.%m.%Y"),
             przebieg, kwota / 6.0, kwota, stacja),
        )


def _wizyta(auto_id, dni_temu, kwota, wykonawca="Warsztat"):
    with db.polacz_baze() as conn:
        conn.execute(
            "INSERT INTO wizyty (auto_id, data, przebieg, wykonawca, koszt_calkowity) VALUES (?,?,?,?,?)",
            (auto_id, (date.today() - timedelta(days=dni_temu)).strftime("%d.%m.%Y"),
             110000, wykonawca, kwota),
        )


def _inny(auto_id, dni_temu, kwota, nazwa="Ubezpieczenie"):
    with db.polacz_baze() as conn:
        conn.execute(
            "INSERT INTO inne_koszty (auto_id, data, kategoria, nazwa, kwota) VALUES (?,?,?,?,?)",
            (auto_id, (date.today() - timedelta(days=dni_temu)).strftime("%d.%m.%Y"),
             "ubezpieczenie", nazwa, kwota),
        )


def _typowe_auto():
    """Auto z kilkunastoma tankowaniami i jedną drogą naprawą."""
    auto_id = _auto()
    for i in range(12):
        _tankowanie(auto_id, 360 - i * 25, 300.0, przebieg=105000 + i * 800)
    _wizyta(auto_id, 120, 4200.0, "Rozrząd")
    _inny(auto_id, 200, 1800.0)
    return auto_id


def _teksty(korzen):
    znalezione = []

    def zejdz(kontrolka):
        if isinstance(kontrolka, ft.Text) and kontrolka.value:
            znalezione.append(str(kontrolka.value))
        for nazwa in POLA_DZIECI:
            wartosc = getattr(kontrolka, nazwa, None)
            if isinstance(wartosc, (list, tuple)):
                for dziecko in wartosc:
                    if isinstance(dziecko, ft.Control):
                        zejdz(dziecko)
            elif isinstance(wartosc, ft.Control):
                zejdz(wartosc)

    zejdz(korzen)
    return znalezione


# ---------------------------------------------------------------- oś i start

def test_krzywa_startuje_od_ceny_zakupu(baza):
    """Sedno wykresu: pierwszy punkt to kwota zakupu, nie zero. Inaczej krzywa
    pokazywałaby koszt jeżdżenia, a nie koszt posiadania."""
    auto_id = _typowe_auto()
    dane = db.koszt_skumulowany(auto_id, z_cena_zakupu=True)

    assert dane["czy_od_zakupu"] is True
    assert dane["z_cena_zakupu"] is True
    assert dane["punkty"][0]["razem"] == 60000.0
    assert dane["punkty"][0]["dzien"] == 0
    assert dane["suma"] == 60000.0 + dane["wydatki"]


def test_bez_ceny_zakupu_krzywa_rusza_od_zera(baza):
    """Przełącznik na karcie wykresu: ta sama krzywa, sama eksploatacja."""
    auto_id = _typowe_auto()
    z_zakupem = db.koszt_skumulowany(auto_id, z_cena_zakupu=True)
    bez_zakupu = db.koszt_skumulowany(auto_id, z_cena_zakupu=False)

    assert bez_zakupu["punkty"][0]["razem"] == 0.0
    assert bez_zakupu["z_cena_zakupu"] is False
    assert bez_zakupu["suma"] == bez_zakupu["wydatki"]
    # Wydatki są te same — różni się tylko punkt, od którego je liczymy.
    assert bez_zakupu["wydatki"] == z_zakupem["wydatki"]
    assert z_zakupem["suma"] - bez_zakupu["suma"] == 60000.0


def test_bez_daty_zakupu_start_w_pierwszym_wpisie(baza):
    """Karta pojazdu bywa niewypełniona. Wtedy oś zaczyna się w pierwszym
    wpisie, a `czy_od_zakupu` mówi wołającemu, że podpis „od zakupu" byłby
    nieprawdą — cena zakupu bez daty nie ma gdzie stanąć."""
    auto_id = _auto(dni_temu_zakup=None, cena_zakupu=60000.0)
    _tankowanie(auto_id, 100, 300.0)
    _tankowanie(auto_id, 50, 320.0)
    dane = db.koszt_skumulowany(auto_id, z_cena_zakupu=True)

    assert dane["czy_od_zakupu"] is False
    assert dane["z_cena_zakupu"] is False
    assert dane["start"] == date.today() - timedelta(days=100)
    # Dzień zerowy JEST tu pierwszym wydatkiem, więc krzywa rusza od jego kwoty.
    # Dorysowywanie zera dzień wcześniej byłoby wymyślaniem daty, której nie ma.
    assert dane["punkty"][0]["dzien"] == 0
    assert dane["punkty"][0]["razem"] == 300.0
    assert dane["suma"] == 620.0


def test_wpisy_sprzed_zakupu_nie_wchodza_do_rachunku(baza):
    """Koszt poprzedniego właściciela (albo literówka w dacie) nie jest tym,
    ile auto kosztowało CIEBIE — tak samo liczy okno wydatków w metrykach."""
    auto_id = _auto(dni_temu_zakup=100)
    _tankowanie(auto_id, 300, 999.0)   # sprzed zakupu
    _tankowanie(auto_id, 50, 300.0)
    dane = db.koszt_skumulowany(auto_id, z_cena_zakupu=False)

    assert dane["wydatki"] == 300.0
    assert all(p["data"] >= dane["start"] for p in dane["punkty"])


def test_krzywa_nie_maleje_i_domyka_rachunek(baza):
    """Suma narastająca nie ma prawa spaść, a ostatni punkt musi być równy
    wszystkiemu, co auto kosztowało — to jedyna gwarancja, że wykres nie kłamie."""
    auto_id = _typowe_auto()
    dane = db.koszt_skumulowany(auto_id, z_cena_zakupu=True)
    wartosci = [p["razem"] for p in dane["punkty"]]

    assert wartosci == sorted(wartosci)
    assert wartosci[-1] == dane["suma"]
    # Serie kategorii sumują się do krzywej razem, bez ceny zakupu.
    ostatni = dane["punkty"][-1]
    assert round(ostatni["paliwo"] + ostatni["serwis"] + ostatni["inne"], 2) == round(dane["wydatki"], 2)


def test_cisza_po_ostatnim_wpisie_to_poziomy_odcinek(baza):
    """Pół roku bez wydatku ma być NA wykresie, a nie poza nim: ostatni punkt
    stoi w dniu dzisiejszym, więc płaski odcinek widać."""
    auto_id = _auto(dni_temu_zakup=400)
    _tankowanie(auto_id, 380, 300.0)
    _tankowanie(auto_id, 200, 300.0)
    dane = db.koszt_skumulowany(auto_id, z_cena_zakupu=False)

    assert dane["punkty"][-1]["data"] == date.today()
    assert dane["punkty"][-1]["razem"] == dane["punkty"][-2]["razem"]


# ------------------------------------------------------------- wyróżnienia

def test_znacznik_dostaje_wydatek_odstajacy_a_nie_kazde_tankowanie(baza):
    """Próg to trzykrotność mediany wpisu. Przy dwukrotności znacznik dostawało
    co drugie tankowanie i krzywa zarastała kropkami."""
    auto_id = _typowe_auto()
    dane = db.koszt_skumulowany(auto_id, z_cena_zakupu=True)
    kwoty = [w["kwota"] for w in dane["wyroznione"]]

    assert 4200.0 in kwoty and 1800.0 in kwoty
    assert 300.0 not in kwoty
    # Opis mówi, CO było skokiem — sama kwota zostawia z pytaniem.
    assert any("Rozrząd" in w["opis"] for w in dane["wyroznione"])
    # Znaczniki idą chronologicznie i siedzą na krzywej, a nie obok niej.
    assert [w["dzien"] for w in dane["wyroznione"]] == sorted(w["dzien"] for w in dane["wyroznione"])
    dni_punktow = {p["dzien"]: p["razem"] for p in dane["punkty"]}
    assert all(dni_punktow[w["dzien"]] == w["skumulowana"] for w in dane["wyroznione"])


def test_znacznikow_nie_moze_byc_wiecej_niz_szesc(baza):
    """Dziesięć kropek na telefonie to już nie wyróżnienie, tylko szum."""
    auto_id = _auto()
    for i in range(20):
        _tankowanie(auto_id, 300 - i * 5, 300.0, przebieg=105000 + i * 500)
    for i in range(10):
        _wizyta(auto_id, 250 - i * 10, 5000.0 + i * 100)
    dane = db.koszt_skumulowany(auto_id, z_cena_zakupu=True)

    assert len(dane["wyroznione"]) == db.MAKS_WYROZNIONYCH_WYDATKOW
    # Zostają NAJDROŻSZE, a nie pierwsze z brzegu.
    assert min(w["kwota"] for w in dane["wyroznione"]) >= 5400.0


def test_same_rowne_wpisy_nie_wyrozniaja_niczego(baza):
    """Dwanaście identycznych tankowań nie ma w sobie żadnego „większego
    wydatku" — i wykres nie ma prawa go wymyślić."""
    auto_id = _auto()
    for i in range(12):
        _tankowanie(auto_id, 300 - i * 20, 300.0, przebieg=105000 + i * 700)

    assert db.koszt_skumulowany(auto_id, z_cena_zakupu=True)["wyroznione"] == []


# --------------------------------------------------------- sprzedaż i liczby

def test_sprzedane_auto_zamyka_rachunek_na_dniu_sprzedazy(baza):
    """Rachunek sprzedanego auta jest ZAMKNIĘTY: wpisy po sprzedaży nie wchodzą,
    dni liczą się do dnia sprzedaży (inaczej koszt dzienny malałby sam z siebie),
    a cena sprzedaży wraca osobno — to jedyna pozycja, która rachunek obniża."""
    dzien_sprzedazy = date.today() - timedelta(days=30)
    auto_id = _auto(
        dni_temu_zakup=400,
        status=db.STATUS_POJAZDU_SPRZEDANY,
        data_sprzedazy=dzien_sprzedazy.strftime("%d.%m.%Y"),
        cena_sprzedazy=45000.0,
    )
    _tankowanie(auto_id, 100, 400.0)
    _tankowanie(auto_id, 10, 999.0)  # już po sprzedaży
    dane = db.koszt_skumulowany(auto_id, z_cena_zakupu=True)

    assert dane["wydatki"] == 400.0
    assert dane["punkty"][-1]["data"] == dzien_sprzedazy
    assert dane["dni"] == 370
    assert dane["sprzedaz"]["cena"] == 45000.0
    assert dane["sprzedaz"]["po_odliczeniu"] == 60400.0 - 45000.0


def test_sprzedaz_bez_ceny_zakupu_w_krzywej_nie_odlicza(baza):
    """Bez ceny zakupu w krzywej nie ma od czego odjąć ceny sprzedaży — data
    zostaje, odliczenie znika."""
    auto_id = _auto(
        status=db.STATUS_POJAZDU_SPRZEDANY,
        data_sprzedazy=(date.today() - timedelta(days=10)).strftime("%d.%m.%Y"),
        cena_sprzedazy=45000.0,
    )
    _tankowanie(auto_id, 100, 400.0)
    dane = db.koszt_skumulowany(auto_id, z_cena_zakupu=False)

    assert dane["sprzedaz"]["po_odliczeniu"] is None


def test_koszt_na_dzien_i_na_kilometr(baza):
    """Dwie liczby z nagłówka karty. Kilometry liczą się OD ZAKUPU — bez
    przebiegu przy zakupie nie ma czego odjąć i liczby po prostu nie ma."""
    auto_id = _auto(dni_temu_zakup=100, cena_zakupu=10000.0, przebieg_zakupu=100000)
    _tankowanie(auto_id, 50, 1000.0, przebieg=110000)
    dane = db.koszt_skumulowany(auto_id, z_cena_zakupu=True)

    assert dane["km"] == 10000
    assert dane["koszt_km"] == 11000.0 / 10000
    assert dane["koszt_dzien"] == 11000.0 / 100

    bez_przebiegu = _auto(nazwa="Bez przebiegu", przebieg_zakupu=None, dni_temu_zakup=100)
    _tankowanie(bez_przebiegu, 50, 1000.0, przebieg=110000)
    assert db.koszt_skumulowany(bez_przebiegu)["km"] is None
    assert db.koszt_skumulowany(bez_przebiegu)["koszt_km"] is None


def test_pusty_pojazd_i_brak_pojazdu_nie_wywracaja_sie(baza):
    """Kafelek kokpitu i zakładka wołają tę funkcję zanim cokolwiek wpisano."""
    assert db.koszt_skumulowany(None)["punkty"] == []
    assert db.koszt_skumulowany(99999)["suma"] == 0.0
    goly = _auto(cena_zakupu=None, przebieg_zakupu=None)
    assert db.koszt_skumulowany(goly)["wydatki"] == 0.0


# ----------------------------------------------------------------- wykres

def test_zakres_czasu_przycina_widok_a_nie_rachunek(baza):
    """Umowa paska zakresu: „ostatnie 3 miesiące" pokazują OGON krzywej, wysoko
    nad zerem. Gdyby zakres przycinał rachunek, powstałby trzeci z kolei wykres
    wydatków miesięcznych — a nie suma narastająca."""
    auto_id = _typowe_auto()
    dane = db.koszt_skumulowany(auto_id, z_cena_zakupu=True)
    strona = pomoce.zbuduj_strone()

    pelny = utils.wykres_kosztu_skumulowanego(strona.page, dane)
    przyciety = utils.wykres_kosztu_skumulowanego(
        strona.page, dane, od_daty=utils.granica_zakresu(3))

    assert pelny is not None and przyciety is not None
    serie_pelne = pelny.controls[0].content.data_series[-1].points
    serie_ciete = przyciety.controls[0].content.data_series[-1].points
    assert len(serie_ciete) < len(serie_pelne)
    # Krzywa wchodzi w kadr wysoko: pierwszy widoczny punkt to nadal suma
    # narastająca od zakupu, a nie zero.
    assert serie_ciete[0].y >= 60000.0


def test_karta_mowi_o_braku_danych_zamiast_rysowac_kreske(baza):
    """Jeden wpis to nie krzywa. Zamiast kreski w powietrzu — zdanie o tym,
    czego brakuje i gdzie się to uzupełnia."""
    strona = pomoce.zbuduj_strone()
    auto_id = _auto()
    karta = utils.karta_kosztu_skumulowanego(strona.page, db.koszt_skumulowany(auto_id))

    assert any("Za mało danych" in t for t in _teksty(karta))


def test_karta_pokazuje_sume_i_legende(baza):
    """Nagłówek karty odpowiada na pytanie bez czytania wykresu, a legenda
    nazywa cztery serie — bez niej cienkie krzywe są trzema kreskami."""
    strona = pomoce.zbuduj_strone()
    dane = db.koszt_skumulowany(_typowe_auto(), z_cena_zakupu=True)
    teksty = _teksty(utils.karta_kosztu_skumulowanego(strona.page, dane))

    assert any("Razem od zakupu" in t for t in teksty)
    assert any("Na dzień" in t for t in teksty)
    assert "Razem" in teksty and "Serwis" in teksty
    assert any("cena zakupu" in t for t in teksty)


def test_kafelek_kokpitu_pokazuje_krzywa(baza):
    """Kafelek na ekranie startowym: liczba, iskra i skrót do pełnego wykresu."""
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    stan.zakladka = 0
    db.zapisz_widgety_kokpitu(["skumulowany"], stan.auto_id)
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(), stan)

    assert "skumulowany" in widok._kokpit_budowniczy
    assert any("Koszt skumulowany" in t for t in _teksty(widok.kokpit_kontener))
