"""Harmonogram leasingu i kredytu (M-22).

Rata była wydatkiem cyklicznym bez końca i bez sumy — nie dało się powiedzieć,
ile jeszcze zostało do spłaty. Teraz wpis cykliczny rodzaju „leasing” albo
„kredyt” niesie umowę, a db/raty.py liczy z niej harmonogram. Sprawdzamy:

1. rachunek — rata równa, stopa z raty, raty malejące, wykup, sumy;
2. zapis i płatności — „Zapłacone” płaci KOLEJNĄ ratę, po wykupie wpis się
   kończy, „Cofnij” odwraca jedną płatność;
3. gdzie widać umowę — dzwonek, „Ile zostało do…”, kafelek, Karta pojazdu,
   porównanie pojazdów;
4. ekran „Leasing i kredyt” i formularz umowy (także przestawienie zwykłego
   wydatku na raty);
5. router i role;
6. migracja 49, chmura (kolumny jako `dopisane`) i kosz.
"""

import sqlite3
from datetime import date, timedelta

import flet as ft
import pytest

import db
import pomoce
import probki_baz
import sync
import utils
from sync import konflikty as sync_konflikty
from sync import pobieranie as sync_pobieranie
from sync import wysylanie as sync_wysylanie
from views.formularze import rata as formularz_raty

POLA_DZIECI = ("controls", "content", "items", "actions", "leading", "trailing", "title", "subtitle")
DRABINKA = probki_baz.wczytaj_drabinke()
DZIS = date.today()
KONFIG_WYDATKOW = next(k for k in sync.KONFIGURACJA_SYNC if k["tabela"] == "wydatki_cykliczne")


# ============================================================================
#  POMOCNIKI
# ============================================================================

def napis(dzien):
    return dzien.strftime("%d.%m.%Y")


def za_miesiecy(n, dni=0):
    return db.dodaj_miesiace(DZIS, n) + timedelta(days=dni)


def auto(nazwa="Toyota Corolla", **pola):
    kolumny = {"nazwa": nazwa, "typ_paliwa": "Benzyna", "status": db.STATUS_POJAZDU_AKTYWNY,
               "rola_wspoldzielenia": db.ROLA_WLASCICIEL}
    kolumny.update(pola)
    with db.polacz_baze() as conn:
        kursor = conn.execute(
            f"INSERT INTO samochody ({', '.join(kolumny)}) VALUES ({', '.join('?' for _ in kolumny)})",
            list(kolumny.values()))
        return kursor.lastrowid


def umowa(auto_id, **pola):
    """Leasing na trzy raty po 1 900 z pierwszą za tydzień — chyba że pola mówią inaczej."""
    domyslne = {"typ": db.TYP_CYKLICZNY_LEASING, "nazwa": "Leasing Corolli", "kwota": 1900.0,
                "liczba_rat": 3, "data_pierwszej_raty": napis(DZIS + timedelta(days=7))}
    domyslne.update(pola)
    return db.zapisz_umowe_raty(auto_id, domyslne)


def jeden(zapytanie, *parametry):
    with db.polacz_baze() as conn:
        return conn.execute(zapytanie, parametry).fetchone()


def wpis(wydatek_id):
    with db.polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        return dict(conn.execute("SELECT * FROM wydatki_cykliczne WHERE id=?", (wydatek_id,)).fetchone())


def koszty(auto_id):
    with db.polacz_baze() as conn:
        return conn.execute("SELECT data, data_iso, kategoria, nazwa, kwota FROM inne_koszty WHERE auto_id=? "
                            "ORDER BY id", (auto_id,)).fetchall()


def zaplac(wydatek_id, auto_id):
    return db.oznacz_zaplacony_wydatek_cykliczny(wydatek_id, auto_id)


def _wszystkie(korzen, typ):
    znalezione = []

    def zejdz(kontrolka):
        if isinstance(kontrolka, typ):
            znalezione.append(kontrolka)
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


def teksty(kontrolka):
    return [t.value for t in _wszystkie(kontrolka, ft.Text) if isinstance(t.value, str)]


def widok(nazwa, auto_id, identyfikatory=None, stan=None):
    stan = stan or pomoce.stan_aplikacji(auto_id, "Toyota Corolla")
    return pomoce.zbuduj_widok(pomoce.klasy_widokow()[nazwa], pomoce.zbuduj_strone(), stan, identyfikatory)


def kwota(wartosc):
    return f"{utils.formatuj_liczba(wartosc)} {utils.symbol_waluty()}"


# ============================================================================
#  1. RACHUNEK
# ============================================================================

def test_rata_rowna_jak_w_tabelach_bankowych():
    assert db.rata_rowna(100000, 60, 7.2) == 1989.57
    assert db.rata_rowna(12000, 12, 0) == 1000.0
    # Rata balonowa zostaje na koniec, więc rata spłaca tylko resztę kapitału.
    z_balonem = db.rata_rowna(100000, 36, 6, wykup=30000)
    assert db.stopa_z_raty(100000, 36, z_balonem, wykup=30000) * 1200 == pytest.approx(6.0, abs=0.01)
    assert db.rata_rowna(None, 60, 7.2) is None and db.rata_rowna(100000, 60, None) is None


def test_stopa_z_raty_odwraca_rate_a_zle_kwoty_odrzuca():
    assert db.stopa_z_raty(100000, 60, 1989.57) * 1200 == pytest.approx(7.2, abs=0.001)
    assert db.stopa_z_raty(60000, 60, 1000) == 0.0, "suma rat równa kapitałowi — umowa bez odsetek"
    assert db.stopa_z_raty(100000, 60, 1000) is None, "raty nie pokrywają nawet kapitału"


def test_harmonogram_leasingu_z_oplata_wstepna_i_wykupem():
    h = db.harmonogram_umowy({
        "typ": db.TYP_CYKLICZNY_LEASING, "liczba_rat": 47, "kwota": 1900, "data_pierwszej_raty": "31.01.2026",
        "kwota_finansowania": 120000, "oplata_wstepna": 12000, "wykup": 24000, "zaplacone_platnosci": 9,
    }, dzis=date(2026, 10, 5))

    assert h["kompletna"] and h["liczba_platnosci"] == 48
    # Ten sam dzień co pierwsza rata, a w krótszym miesiącu — jego ostatni dzień.
    assert [p["data"] for p in h["platnosci"][:3]] == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)]
    wykup = h["platnosci"][-1]
    assert (wykup["rodzaj"], wykup["kwota"], wykup["data"]) == (db.PLATNOSC_WYKUP, 24000, h["data_ostatniej_raty"])
    # Koszt finansowania = wszystko, co się wpłaca, minus wartość auta.
    assert h["odsetki_razem"] == pytest.approx(12000 + 47 * 1900 + 24000 - 120000 + 12000 - 12000, abs=0.01)
    assert h["platnosci"][46]["saldo"] == pytest.approx(24000, abs=0.01), "po ostatniej racie zostaje wykup"
    assert h["kapital_do_splaty"] + h["odsetki_do_zaplaty"] == pytest.approx(h["do_splaty"], abs=0.01)
    assert (h["zaplacone_raty"], h["zostalo_rat"], h["do_splaty"]) == (9, 38, 38 * 1900 + 24000)
    assert h["oprocentowanie_z"] == "rata" and 1.9 < h["oprocentowanie"] < 2.1


def test_raty_malejace_splacaja_staly_kapital_z_odsetkami_od_salda():
    h = db.harmonogram_umowy({
        "typ": db.TYP_CYKLICZNY_KREDYT, "rodzaj_rat": db.RATY_MALEJACE, "liczba_rat": 12,
        "data_pierwszej_raty": "10.11.2026", "kwota_finansowania": 12000, "oprocentowanie": 12,
    })

    assert [round(p["kwota"], 2) for p in h["platnosci"]] == [1120 - 10 * i for i in range(12)]
    assert h["odsetki_razem"] == pytest.approx(780)
    assert h["platnosci"][-1]["saldo"] == 0.0 and h["rata"] == pytest.approx(1120)


def test_raty_malejace_tylko_przy_kredycie():
    pola = {"rodzaj_rat": db.RATY_MALEJACE, "liczba_rat": 12, "data_pierwszej_raty": "10.11.2026",
            "kwota_finansowania": 12000, "oprocentowanie": 12, "kwota": 1000}
    assert db.harmonogram_umowy({**pola, "typ": db.TYP_CYKLICZNY_LEASING})["rodzaj_rat"] == db.RATY_ROWNE


def test_bez_kwoty_finansowania_sa_tylko_sumy_rat():
    h = db.harmonogram_umowy({"typ": db.TYP_CYKLICZNY_LEASING, "liczba_rat": 24, "kwota": 1000,
                              "data_pierwszej_raty": "05.01.2026", "zaplacone_platnosci": 10})

    assert h["do_splaty"] == 14000 and h["zaplacono"] == 10000
    assert h["odsetki_razem"] is None and h["kapital_do_splaty"] is None and not h["niespojna"]
    assert all(p["kapital"] is None and p["odsetki"] is None for p in h["platnosci"])


def test_raty_niepokrywajace_kapitalu_to_niespojnosc_a_nie_ujemne_odsetki():
    h = db.harmonogram_umowy({"typ": db.TYP_CYKLICZNY_KREDYT, "liczba_rat": 60, "kwota": 1000,
                              "data_pierwszej_raty": "05.01.2026", "kwota_finansowania": 100000})
    assert h["kompletna"] and h["niespojna"] and h["odsetki_razem"] is None


@pytest.mark.parametrize("pola, powod", [
    ({"kwota": 1000, "data_pierwszej_raty": "05.01.2026"}, "Podaj liczbę rat"),
    ({"kwota": 1000, "liczba_rat": 12}, "Podaj datę pierwszej raty"),
    ({"liczba_rat": 12, "data_pierwszej_raty": "05.01.2026"}, "Podaj kwotę raty"),
])
def test_niekompletna_umowa_mowi_czego_brakuje(pola, powod):
    h = db.harmonogram_umowy({"typ": db.TYP_CYKLICZNY_LEASING, **pola})
    assert not h["kompletna"] and h["powod"].startswith(powod) and h["platnosci"] == []


def test_zaplacone_ponad_harmonogram_to_umowa_splacona():
    h = db.harmonogram_umowy({"typ": db.TYP_CYKLICZNY_LEASING, "liczba_rat": 2, "kwota": 1000, "wykup": 500,
                              "data_pierwszej_raty": "05.01.2026", "zaplacone_platnosci": 9})
    assert h["zakonczona"] and h["nastepna"] is None and h["do_splaty"] == 0 and h["wykup_zaplacony"]


def test_po_terminie_licza_sie_niezaplacone_z_przeszlosci():
    h = db.harmonogram_umowy({"typ": db.TYP_CYKLICZNY_LEASING, "liczba_rat": 12, "kwota": 1000,
                              "data_pierwszej_raty": "05.07.2026", "zaplacone_platnosci": 1},
                             dzis=date(2026, 10, 5))
    # 05.08 i 05.09 minęły bez zapłaty, 05.10 to dziś — jeszcze nie po terminie.
    assert h["po_terminie"] == 2 and h["nastepna"]["numer"] == 2 and h["nastepna"]["po_terminie"]


def test_podpowiedz_zaplaconych_z_kalendarza():
    assert db.sugerowane_zaplacone("31.01.2026", 47, date(2026, 10, 5)) == 9
    assert db.sugerowane_zaplacone("05.10.2026", 12, date(2026, 10, 5)) == 0, "rata z terminem dziś czeka"
    assert db.sugerowane_zaplacone("05.01.2020", 12, date(2026, 10, 5)) == 12
    assert db.sugerowane_zaplacone("", 12) == 0


# ============================================================================
#  2. ZAPIS I PŁATNOŚCI
# ============================================================================

def test_nowa_umowa_dostaje_termin_najblizszej_niezaplaconej_raty(baza):
    a = auto()
    pierwsza = za_miesiecy(-2, dni=3)
    w = wpis(umowa(a, data_pierwszej_raty=napis(pierwsza), liczba_rat=12, zaplacone_platnosci=2))

    assert (w["typ"], w["okres_dni"], w["czy_koszt"], w["kwota"]) == (db.TYP_CYKLICZNY_LEASING, 30, 1, 1900.0)
    assert w["nastepna_data"] == napis(db.dodaj_miesiace(pierwsza, 2))
    assert (w["liczba_rat"], w["zaplacone_platnosci"], w["data_pierwszej_raty"]) == (12, 2, napis(pierwsza))


def test_umowa_z_oprocentowania_zapisuje_wyliczona_rate(baza):
    a = auto()
    w = wpis(umowa(a, typ=db.TYP_CYKLICZNY_KREDYT, kwota=None, liczba_rat=60, kwota_finansowania=100000,
                   oprocentowanie=7.2))
    assert (w["kwota"], w["oprocentowanie"]) == (1989.57, 7.2)
    (zapisana,) = db.pobierz_raty(a)
    assert zapisana["harmonogram"]["oprocentowanie_z"] == "umowa"
    assert zapisana["harmonogram"]["oprocentowanie"] == pytest.approx(7.2, abs=0.001)


def test_raty_malejace_trzymaja_w_kwocie_najblizsza_rate(baza):
    a = auto()
    w = wpis(umowa(a, typ=db.TYP_CYKLICZNY_KREDYT, rodzaj_rat=db.RATY_MALEJACE, kwota=None, liczba_rat=12,
                   kwota_finansowania=12000, oprocentowanie=12, zaplacone_platnosci=3))
    assert w["kwota"] == pytest.approx(1090) and w["rodzaj_rat"] == db.RATY_MALEJACE


def test_przestawienie_wydatku_zostawia_wiersz_i_jego_chmure(baza):
    ids = pomoce.utworz_pojazd("Przestawiany")
    przed = wpis(ids["cykliczny"])

    wynik = db.zapisz_umowe_raty(ids["auto_id"], {"typ": db.TYP_CYKLICZNY_LEASING, "nazwa": "Leasing",
                                                  "kwota": 1200, "liczba_rat": 24,
                                                  "data_pierwszej_raty": "2026-12-01"}, ids["cykliczny"])

    po = wpis(ids["cykliczny"])
    assert wynik == ids["cykliczny"] and po["zdalne_id"] == przed["zdalne_id"] == "cykl-1"
    assert (po["typ"], po["liczba_rat"], po["data_pierwszej_raty"]) == (db.TYP_CYKLICZNY_LEASING, 24, "01.12.2026")


def test_zapis_nie_dotyka_wpisu_innego_pojazdu(baza):
    ids = pomoce.utworz_pojazd("Cudzy")
    przed = wpis(ids["cykliczny"])
    assert db.zapisz_umowe_raty(auto(), {"liczba_rat": 3, "kwota": 10, "data_pierwszej_raty": "01.01.2027"},
                                ids["cykliczny"]) is None
    assert wpis(ids["cykliczny"]) == przed


def test_zaplacono_placi_kolejna_rate_z_numerem_w_nazwie(baza):
    a = auto()
    w_id = umowa(a)
    pierwsza = DZIS + timedelta(days=7)

    wynik = zaplac(w_id, a)

    assert koszty(a) == [(napis(DZIS), DZIS.isoformat(), db.KATEGORIA_RATY, "Leasing Corolli — rata 1 z 3", 1900.0)]
    w = wpis(w_id)
    assert (w["zaplacone_platnosci"], w["nastepna_data"]) == (1, napis(db.dodaj_miesiace(pierwsza, 1)))
    assert (wynik["platnosc"]["numer"], wynik["zostalo_rat"], wynik["do_splaty"]) == (1, 2, 3800.0)
    assert wynik["czy_koszt"] and not wynik["zakonczona"] and wynik["cofnij"]


def test_nadrabiana_rata_trafia_w_swoj_miesiac(baza):
    a = auto()
    pierwsza = za_miesiecy(-2)
    w_id = umowa(a, data_pierwszej_raty=napis(pierwsza))

    zaplac(w_id, a)
    zaplac(w_id, a)

    assert [k[0] for k in koszty(a)] == [napis(pierwsza), napis(db.dodaj_miesiace(pierwsza, 1))]


def test_po_ostatniej_racie_wykup_a_po_wykupie_koniec(baza):
    a = auto()
    w_id = umowa(a, liczba_rat=2, wykup=5000)

    zaplac(w_id, a)
    po_racie = zaplac(w_id, a)
    assert not po_racie["zakonczona"] and wpis(w_id)["nastepna_data"], "wykup jeszcze czeka"
    po_wykupie = zaplac(w_id, a)

    assert [k[3] for k in koszty(a)] == ["Leasing Corolli — rata 1 z 2", "Leasing Corolli — rata 2 z 2",
                                         "Leasing Corolli — wykup"]
    assert koszty(a)[-1][4] == 5000.0
    assert po_wykupie["zakonczona"] and wpis(w_id)["nastepna_data"] == ""
    # Spłacona umowa nie ma już czego zapłacić — „Zapłacone” niczego nie dopisuje.
    kolejny = zaplac(w_id, a)
    assert kolejny["platnosc"] is None and len(koszty(a)) == 3


def test_kredyt_nazywa_ostatnia_platnosc_rata_balonowa(baza):
    a = auto()
    w_id = umowa(a, typ=db.TYP_CYKLICZNY_KREDYT, nazwa="Kredyt", liczba_rat=1, wykup=8000)
    zaplac(w_id, a)
    zaplac(w_id, a)
    assert koszty(a)[-1][3] == "Kredyt — rata balonowa"


def test_cofniecie_odwraca_jedna_platnosc(baza):
    a = auto()
    w_id = umowa(a)
    przed = wpis(w_id)

    wynik = zaplac(w_id, a)
    assert db.cofnij_platnosc_raty(wynik["cofnij"])

    po = wpis(w_id)
    assert (po["zaplacone_platnosci"], po["nastepna_data"], po["kwota"]) == (
        przed["zaplacone_platnosci"], przed["nastepna_data"], przed["kwota"])
    assert koszty(a) == []
    assert not db.cofnij_platnosc_raty(wynik["cofnij"]), "drugie cofnięcie tej samej płatności nic nie robi"


def test_cofniecie_po_kolejnej_platnosci_niczego_nie_rusza(baza):
    a = auto()
    w_id = umowa(a)
    pierwsza = zaplac(w_id, a)
    zaplac(w_id, a)

    assert not db.cofnij_platnosc_raty(pierwsza["cofnij"])
    assert wpis(w_id)["zaplacone_platnosci"] == 2 and len(koszty(a)) == 2


def test_cofniecie_kosztu_z_chmury_zostawia_nagrobek(baza):
    a = auto()
    w_id = umowa(a)
    wynik = zaplac(w_id, a)
    with db.polacz_baze() as conn:
        conn.execute("UPDATE inne_koszty SET zdalne_id='koszt-1' WHERE id=?", (wynik["cofnij"]["koszt_id"],))

    db.cofnij_platnosc_raty(wynik["cofnij"])

    assert [(n[1], n[2]) for n in db.pobierz_nagrobki(a)] == [("inne_koszty", "koszt-1")]


def test_zwykly_wydatek_dalej_przesuwa_termin_od_dzis(baza):
    a = auto()
    db.dodaj_wydatek_cykliczny(a, "Abonament GPS", 30.0, 30, napis(DZIS - timedelta(days=3)))
    (w_id, *_), = db.pobierz_wydatki_cykliczne(a)

    wynik = zaplac(w_id, a)

    assert wynik["typ"] == db.TYP_CYKLICZNY_WYDATEK and "cofnij" not in wynik
    assert wpis(w_id)["nastepna_data"] == napis(DZIS + timedelta(days=30))
    assert koszty(a) == [(napis(DZIS), DZIS.isoformat(), "Cykliczne", "Abonament GPS", 30.0)]


def test_splacona_umowa_stoi_na_koncu_wydatkow_cyklicznych(baza):
    a = auto()
    splacona = umowa(a, nazwa="Stary leasing", data_pierwszej_raty="01.01.2020", zaplacone_platnosci=3)
    db.dodaj_wydatek_cykliczny(a, "Abonament", 30.0, 30, napis(DZIS + timedelta(days=40)))
    trwa = umowa(a, nazwa="Nowy leasing")

    kolejnosc = [w[0] for w in db.pobierz_wydatki_cykliczne(a)]
    assert kolejnosc[0] == trwa and kolejnosc[-1] == splacona


# ============================================================================
#  3. GDZIE WIDAĆ UMOWĘ
# ============================================================================

def przypomnienia(auto_id):
    return [p for p in db.pobierz_powiadomienia(auto_id, pomin_wyciszone=False) if p["typ"] == "cykliczny"]


def test_przypomnienie_mowi_ktora_to_rata(baza):
    a = auto()
    pierwsza = db.dodaj_miesiace(DZIS + timedelta(days=3), -1)
    umowa(a, data_pierwszej_raty=napis(pierwsza), liczba_rat=12, zaplacone_platnosci=1)

    (przypomnienie,) = przypomnienia(a)

    assert przypomnienie["tytul"] == "Leasing Corolli" and przypomnienie["opis"].endswith("• rata 2 z 12")
    assert przypomnienie["typ_cykliczny"] == db.TYP_CYKLICZNY_LEASING


def test_splacona_umowa_nie_przypomina(baza):
    a = auto()
    umowa(a, data_pierwszej_raty="01.01.2020", zaplacone_platnosci=3)
    assert przypomnienia(a) == []


def test_podsumowanie_sumuje_tylko_trwajace_umowy(baza):
    a = auto()
    umowa(a, nazwa="Spłacony", data_pierwszej_raty="01.01.2020", zaplacone_platnosci=3)
    umowa(a, nazwa="Leasing", liczba_rat=10, kwota=1000, kwota_finansowania=9500)
    umowa(a, typ=db.TYP_CYKLICZNY_KREDYT, nazwa="Kredyt", liczba_rat=4, kwota=500, zaplacone_platnosci=1)

    stan = db.podsumowanie_rat(a)

    assert (stan["liczba_umow"], stan["trwajace"], stan["splacone"]) == (3, 2, 1)
    assert stan["do_splaty"] == 10 * 1000 + 3 * 500
    assert (stan["zaplacone_raty"], stan["liczba_rat"]) == (1, 14)
    assert stan["odsetki_do_zaplaty"] is None, "kredyt bez kwoty — suma z połowy umów udawałaby całość"
    assert stan["najblizsza"]["nazwa"] in ("Leasing", "Kredyt")
    assert db.podsumowanie_rat(auto("Bez umowy")) is None


def test_ile_zostalo_do_odlicza_ostatnia_rate_potem_wykup(baza):
    a = auto()
    w_id = umowa(a, liczba_rat=2, wykup=5000)

    (pozycja,) = [p for p in db.odliczania_pojazdu(a) if p["rodzaj"] == "rata"]
    assert pozycja["tytul"] == "Leasing Corolli — ostatnia rata" and pozycja["trasa"] == "/raty"
    assert pozycja["data"] == db.dodaj_miesiace(DZIS + timedelta(days=7), 1) and pozycja["udzial"] == 0

    zaplac(w_id, a)
    zaplac(w_id, a)
    (pozycja,) = [p for p in db.odliczania_pojazdu(a) if p["rodzaj"] == "rata"]
    assert pozycja["tytul"] == "Leasing Corolli — wykup" and pozycja["udzial"] == pytest.approx(2 / 3)

    zaplac(w_id, a)
    assert not [p for p in db.odliczania_pojazdu(a) if p["rodzaj"] == "rata"]


def test_ekran_odliczan_pokazuje_postep_umowy(baza):
    a = auto()
    w_id = umowa(a)
    zaplac(w_id, a)

    tresc = teksty(widok("OdliczaniaView", a))

    assert "Leasing Corolli — ostatnia rata" in tresc
    assert f"Zapłacono 1 z 3 rat · do spłaty {kwota(3800)}" in tresc


def test_porownanie_niesie_do_splaty_tylko_przy_umowie(baza):
    a, b = auto("A"), auto("B")
    umowa(a, kwota_finansowania=5500)

    assert db.pobierz_dane_do_porownania(a)["do_splaty"] == 5700
    assert db.pobierz_dane_do_porownania(a)["odsetki_do_zaplaty"] == pytest.approx(200)
    assert db.pobierz_dane_do_porownania(b)["do_splaty"] is None

    tresc = teksty(widok("PorownanieView", a))
    assert "Do spłaty" in tresc and "brak umowy" in tresc and "Odsetki do zapłaty" in tresc


def test_porownanie_bez_umow_nie_ma_wierszy_rat(baza):
    a, _b = auto("A"), auto("B")
    assert "Do spłaty" not in teksty(widok("PorownanieView", a))


def kokpit(auto_id):
    db.zapisz_widgety_kokpitu(["do_splaty"], auto_id)
    stan = pomoce.stan_aplikacji(auto_id, "Toyota Corolla")
    stan.zakladka = 0
    return teksty(widok("MainView", auto_id, stan=stan).kokpit_kontener)


def test_kafel_do_splaty_pokazuje_kwote_raty_i_koniec(baza):
    a = auto()
    w_id = umowa(a)
    zaplac(w_id, a)
    koniec = db.dodaj_miesiace(DZIS + timedelta(days=7), 2)

    tresc = kokpit(a)

    assert "Do spłaty" in tresc
    assert f"{utils.formatuj_liczba(3800, 0)} {utils.symbol_waluty()}" in tresc
    assert f"1 z 3 rat • do {koniec.strftime('%m.%Y')}" in tresc


def test_kafel_do_splaty_po_splacie_i_bez_umowy(baza):
    a = auto()
    assert "Do spłaty" not in kokpit(a), "auto bez umowy — kafel „nie dotyczy” się chowa"
    umowa(a, data_pierwszej_raty="01.01.2020", zaplacone_platnosci=3)
    assert "Spłacone" in kokpit(a)


def test_karta_pojazdu_liczy_co_zostaje_po_sprzedazy_i_splacie(baza):
    a = auto(wartosc_szacowana="80000")
    umowa(a, liczba_rat=10, kwota=1000, kwota_finansowania=9500)
    (zapisana,) = db.pobierz_raty(a)
    kapital = zapisana["harmonogram"]["kapital_do_splaty"]

    tresc = teksty(widok("PojazdView", a))

    assert "Leasing i kredyt" in tresc and "Do spłaty" in tresc and kwota(10000) in tresc
    assert "Wartość dziś minus kapitał" in tresc and kwota(80000 - kapital) in tresc


def test_karta_pojazdu_bez_umowy_nie_ma_sekcji_rat(baza):
    assert "Leasing i kredyt" not in teksty(widok("PojazdView", auto()))


# ============================================================================
#  4. EKRAN I FORMULARZ
# ============================================================================

def test_ekran_pokazuje_do_splaty_najblizsza_rate_i_harmonogram(baza):
    a = auto()
    w_id = umowa(a, wykup=5000, kwota_finansowania=10000)
    zaplac(w_id, a)

    tresc = teksty(widok("RatyView", a))

    assert "Leasing Corolli" in tresc and "Zostało do spłaty" in tresc and kwota(8800) in tresc
    assert any(t.startswith("rata 2 z 3 • ") for t in tresc)
    assert "Harmonogram płatności" in tresc and "Wykup" in tresc and "Koszt finansowania łącznie" in tresc


def test_zaplata_z_ekranu_przesuwa_harmonogram_a_cofniecie_wraca(baza, monkeypatch):
    a = auto()
    w_id = umowa(a)
    pokazane = []
    monkeypatch.setattr(utils, "pokaz_komunikat_wykonania",
                        lambda strona, wynik, czy_koszt=True, po_cofnieciu=None: pokazane.append((wynik, po_cofnieciu)))
    monkeypatch.setattr(utils, "wypchnij_w_tle", lambda strona, auto_id, powod="zapis": None)
    ekran = widok("RatyView", a)

    (przycisk,) = [b for b in _wszystkie(ekran, ft.FilledTonalButton) if str(b.content).startswith("Zapłacono")]
    assert przycisk.content == "Zapłacono: rata 1 z 3"
    przycisk.on_click(None)

    assert wpis(w_id)["zaplacone_platnosci"] == 1 and len(koszty(a)) == 1
    assert any(t.startswith("rata 2 z 3 • ") for t in teksty(ekran)), "ekran przebudował się na miejscu"
    wynik, po_cofnieciu = pokazane[0]
    assert db.cofnij_platnosc_raty(wynik["cofnij"])
    po_cofnieciu()
    assert any(t.startswith("rata 1 z 3 • ") for t in teksty(ekran))


def test_ekran_podpowiada_przestawienie_raty_z_wydatkow(baza):
    a = auto()
    db.dodaj_wydatek_cykliczny(a, "Rata leasingu", 1900.0, 30, napis(DZIS + timedelta(days=10)))
    db.dodaj_wydatek_cykliczny(a, "Abonament GPS", 30.0, 30, napis(DZIS + timedelta(days=10)))

    ekran = widok("RatyView", a)

    przyciski = [b for b in _wszystkie(ekran, ft.TextButton) if b.content == "Przestaw na raty"]
    assert len(przyciski) == 1, "abonament nie wygląda na ratę"
    assert "Brak leasingu ani kredytu" in teksty(ekran)


def test_podglad_widzi_harmonogram_bez_przyciskow(baza):
    ids = pomoce.utworz_pojazd("Wspólny", wspolny=True)
    a = ids["auto_id"]
    umowa(a)
    with db.polacz_baze() as conn:
        conn.execute("UPDATE samochody SET rola_wspoldzielenia=? WHERE id=?", (db.ROLA_PODGLAD, a))

    ekran = widok("RatyView", a)

    assert "Leasing Corolli" in teksty(ekran)
    assert not _wszystkie(ekran, ft.FilledTonalButton) and not _wszystkie(ekran, ft.PopupMenuButton)


@pytest.fixture
def zapis_formularza(monkeypatch):
    """Zapis formularza bez nawigacji, okienek i sieci; zbiera komunikaty."""
    komunikaty = []
    monkeypatch.setattr(utils, "przejdz", lambda strona, trasa: None)
    monkeypatch.setattr(utils, "pokaz_komunikat", lambda strona, tekst, *a, **k: komunikaty.append(tekst))
    monkeypatch.setattr(utils, "wypchnij_w_tle", lambda strona, auto_id, powod="zapis": None)
    monkeypatch.setattr(utils, "pokaz_bledy_formularza",
                        lambda strona, bledy: komunikaty.extend(k for _, k in bledy))
    return komunikaty


def formularz(auto_id, wydatek_id=None):
    return widok("FormularzRatyView", auto_id, {"cykliczny": wydatek_id} if wydatek_id else None)


def wypelnij(f, **pola):
    for nazwa, wartosc in pola.items():
        getattr(f, nazwa).value = wartosc
    f._przelicz(odswiez=False)


def test_formularz_zapisuje_nowy_leasing(baza, zapis_formularza):
    a = auto()
    f = formularz(a)
    wypelnij(f, e_nazwa="Leasing w banku", e_kwota_fin="120 000", e_oplata="12000", e_liczba="47",
             e_data="31.01.2026", e_rata="1900,00", e_wykup="24000")

    f.zapisz(None)

    (zapisana,) = db.pobierz_raty(a)
    h = zapisana["harmonogram"]
    assert (zapisana["nazwa"], zapisana["typ"], zapisana["kwota"]) == ("Leasing w banku", db.TYP_CYKLICZNY_LEASING, 1900.0)
    assert (zapisana["kwota_finansowania"], zapisana["oplata_wstepna"], zapisana["wykup"]) == (120000, 12000, 24000)
    assert zapisana["oprocentowanie"] is None and h["oprocentowanie_z"] == "rata"
    assert zapisana["zaplacone_platnosci"] == db.sugerowane_zaplacone("31.01.2026", 47), "zapłacone z kalendarza"
    assert zapis_formularza[-1].startswith("Zapisano umowę • do spłaty")


def test_formularz_wymaga_raty_z_umowy(baza, zapis_formularza):
    a = auto()
    f = formularz(a)
    wypelnij(f, e_liczba="12", e_data="01.01.2027")

    f.zapisz(None)

    assert "Podaj ratę z umowy" in zapis_formularza and db.pobierz_raty(a) == []


def test_formularz_kredytu_z_oprocentowania_liczy_rate(baza, zapis_formularza):
    a = auto()
    f = formularz(a)
    f._zmien_rodzaj(1)
    f.e_tryb.value = formularz_raty.TRYB_Z_OPROCENTOWANIA
    f._zmien_tryb()
    wypelnij(f, e_kwota_fin="100000", e_liczba="60", e_data="15.01.2027", e_procent="7,2")

    assert not f.e_rata.visible and f.e_procent.visible and not f.e_oplata.visible
    assert "Rata wyliczona" in teksty(f.podglad)
    f.zapisz(None)

    (zapisana,) = db.pobierz_raty(a)
    assert (zapisana["typ"], zapisana["kwota"], zapisana["oprocentowanie"]) == (db.TYP_CYKLICZNY_KREDYT, 1989.57, 7.2)


def test_raty_malejace_tylko_w_formularzu_kredytu(baza):
    f = formularz(auto())
    klucze = lambda: [o.key for o in f.e_tryb.options]  # noqa: E731
    assert formularz_raty.TRYB_MALEJACE not in klucze()

    f._zmien_rodzaj(1)
    f.e_tryb.value = formularz_raty.TRYB_MALEJACE
    f._zmien_tryb()
    assert formularz_raty.TRYB_MALEJACE in klucze()

    f._zmien_rodzaj(0)
    assert f.tryb == formularz_raty.TRYB_Z_UMOWY and formularz_raty.TRYB_MALEJACE not in klucze()


def test_formularz_przestawia_zwykly_wydatek_w_miejscu(baza, zapis_formularza):
    ids = pomoce.utworz_pojazd("Pełny")
    f = formularz(ids["auto_id"], ids["cykliczny"])

    assert f.przestawiany and f.wydatek_id == ids["cykliczny"]
    assert (f.e_nazwa.value, f.e_rata.value, f.e_data.value) == ("Ubezpieczenie", "1200", "01.12.2026")
    assert any("Przestawiasz wydatek cykliczny „Ubezpieczenie”" in t for t in teksty(f))
    wypelnij(f, e_liczba="12")
    f.zapisz(None)

    po = wpis(ids["cykliczny"])
    assert (po["typ"], po["liczba_rat"], po["zdalne_id"]) == (db.TYP_CYKLICZNY_LEASING, 12, "cykl-1")


def test_edycja_nie_cofa_zaplaconego_wykupu(baza, zapis_formularza):
    a = auto()
    w_id = umowa(a, liczba_rat=2, wykup=5000, data_pierwszej_raty="01.01.2020", zaplacone_platnosci=3)
    f = formularz(a, w_id)

    assert f.e_zaplacone.value == "2" and f.e_wykup_zaplacony.visible and f.e_wykup_zaplacony.value
    assert not f._czy_zmieniono()
    f.zapisz(None)

    assert wpis(w_id)["zaplacone_platnosci"] == 3 and wpis(w_id)["nastepna_data"] == ""


def test_edycja_zachowuje_tryb_i_wykrywa_zmiany(baza):
    a = auto()
    w_id = umowa(a, typ=db.TYP_CYKLICZNY_KREDYT, rodzaj_rat=db.RATY_MALEJACE, kwota=None, liczba_rat=12,
                 kwota_finansowania=12000, oprocentowanie=12)
    f = formularz(a, w_id)

    assert (f.typ, f.tryb, f.e_procent.value, f.e_kwota_fin.value) == (
        db.TYP_CYKLICZNY_KREDYT, formularz_raty.TRYB_MALEJACE, "12", "12000")
    assert not f._czy_zmieniono()
    f.e_procent.value = "11"
    assert f._czy_zmieniono()


def test_podglad_ostrzega_przed_niespojnymi_kwotami(baza):
    f = formularz(auto())
    wypelnij(f, e_kwota_fin="100000", e_liczba="60", e_data="01.01.2027", e_rata="1000")
    assert any("nie pokrywają kwoty finansowania" in t for t in teksty(f.podglad))


# ============================================================================
#  5. ROUTER I ROLE
# ============================================================================

def test_router_kladzie_formularz_umowy_na_harmonogramie(baza, monkeypatch):
    a = auto()
    w_id = umowa(a)
    db.zapisz_widziana_wersje(db.WERSJA_APLIKACJI)
    monkeypatch.setattr(ft, "run", lambda *args, **kwargs: None)
    import log
    import main

    monkeypatch.setattr(log, "wlacz", lambda: True)
    monkeypatch.setitem(utils.wyglad._OSTATNI_MOTYW, "nazwa", utils.wyglad._OSTATNI_MOTYW["nazwa"])
    strona = pomoce.zbuduj_strone()
    page = strona.page
    monkeypatch.setattr(type(page), "run_task", lambda self, *args, **kwargs: None)
    main.main(page)

    utils.przejdz(page, "/raty/nowa")
    assert [type(w).__name__ for w in page.views] == ["MainView", "RatyView", "FormularzRatyView"]
    utils.przejdz(page, f"/raty/edytuj/{w_id}")
    assert page.views[-1].wydatek_id == w_id and page.views[-1].route == f"/raty/edytuj/{w_id}"
    utils.przejdz(page, "/raty")
    assert [type(w).__name__ for w in page.views] == ["MainView", "RatyView"]


def test_formularz_umowy_zmienia_dane_a_harmonogram_nie(baza, monkeypatch):
    monkeypatch.setattr(ft, "run", lambda *args, **kwargs: None)
    import main

    assert main._cel_trasy(["raty"])[0] is False
    assert main._cel_trasy(["raty", "nowa"])[:2] == (True, True)
    assert main._cel_trasy(["raty", "edytuj", "5"])[:2] == (True, False)

    a = auto(rola_wspoldzielenia=db.ROLA_PODGLAD)
    assert main._wolno_wejsc(a, ["raty"])[0]
    assert not main._wolno_wejsc(a, ["raty", "nowa"])[0]


def test_ekran_w_rejestrze_i_wyszukiwarce():
    ekran = utils.EKRANY_WG_ID["raty"]
    assert (ekran["trasa"], ekran["grupa"]) == ("/raty", "koszty")
    assert "raty" in [e["id"] for e in utils.znajdz_ekrany("leasing")]
    assert "raty" in [e["id"] for e in utils.znajdz_ekrany("wykup")]


def test_komunikat_platnosci_mowi_ktora_rata_i_ile_zostalo(baza):
    waluta = utils.symbol_waluty()
    rata = {"typ": db.TYP_CYKLICZNY_LEASING, "liczba_rat": 36, "do_splaty": 1234.5, "zakonczona": False,
            "platnosc": {"numer": 7, "rodzaj": db.PLATNOSC_RATA}}
    assert utils.komunikat_po_wykonaniu(rata) == f"Zapisano ratę 7 z 36 • do spłaty 1 234,50 {waluta}."
    wykup = {**rata, "zakonczona": True, "platnosc": {"numer": 37, "rodzaj": db.PLATNOSC_WYKUP}}
    assert utils.komunikat_po_wykonaniu(wykup) == "Zapisano wykup — umowa spłacona."
    assert utils.komunikat_po_wykonaniu({**wykup, "typ": db.TYP_CYKLICZNY_KREDYT}) == \
        "Zapisano ratę balonową — umowa spłacona."
    assert utils.komunikat_po_wykonaniu({**rata, "platnosc": None, "zakonczona": True}) == "Ta umowa jest już spłacona."


def panel_wydatkow(auto_id, monkeypatch):
    otwarte = []
    monkeypatch.setattr(utils.powiadomienia, "otworz_dno", lambda strona, arkusz: otwarte.append(arkusz))
    utils.pokaz_panel_wydatkow_cyklicznych(pomoce.zbuduj_strone().page,
                                           pomoce.stan_aplikacji(auto_id, "Toyota Corolla"))
    return otwarte[0].content.content


def test_panel_wydatkow_pokazuje_ktora_rata_i_prowadzi_do_harmonogramu(baza, monkeypatch):
    a = auto()
    w_id = umowa(a)
    zaplac(w_id, a)
    db.dodaj_wydatek_cykliczny(a, "Abonament GPS", 30.0, 30, napis(DZIS + timedelta(days=40)))

    panel = panel_wydatkow(a, monkeypatch)

    kafle = {teksty(k.title)[0]: k for k in _wszystkie(panel, ft.ListTile) if k.title is not None}
    (podpis,) = teksty(kafle["Leasing Corolli"].subtitle)
    assert podpis.startswith(f"{kwota(1900)} • rata 2 z 3 • ")
    menu_raty = [teksty(p.content)[-1] for p in kafle["Leasing Corolli"].trailing.items]
    assert menu_raty == ["Zapłacone", "Harmonogram", "Edytuj umowę", "Usuń"]
    menu_wydatku = [teksty(p.content)[-1] for p in kafle["Abonament GPS"].trailing.items]
    assert "Przestaw na raty" in menu_wydatku
    assert "Dodaj leasing lub kredyt" in [b.content for b in _wszystkie(panel, ft.TextButton)]


def test_komunikat_platnosci_raty_daje_cofnij(baza, monkeypatch):
    a = auto()
    w_id = umowa(a)
    strona = pomoce.zbuduj_strone()
    otwarte, komunikaty, po = [], [], []
    monkeypatch.setattr(type(strona.page), "open", lambda self, kontrolka: otwarte.append(kontrolka), raising=False)
    monkeypatch.setattr(utils.powiadomienia, "pokaz_komunikat", lambda strona, tekst, *a, **k: komunikaty.append(tekst))

    utils.pokaz_komunikat_wykonania(strona.page, zaplac(w_id, a), po_cofnieciu=lambda: po.append(True))
    (snack,) = otwarte
    assert snack.action == "Cofnij" and teksty(snack.content) == [
        f"Zapisano ratę 1 z 3 • do spłaty {kwota(3800)}."]
    snack.on_action(None)

    assert wpis(w_id)["zaplacone_platnosci"] == 0 and koszty(a) == [] and po == [True]
    assert komunikaty == ["Cofnięto płatność — rata znowu czeka na zapłatę."]

    # Zwykły wydatek nie ma czego cofać — sam komunikat, bez akcji.
    db.dodaj_wydatek_cykliczny(a, "Abonament GPS", 30.0, 30, napis(DZIS))
    gps = max(w[0] for w in db.pobierz_wydatki_cykliczne(a))
    utils.pokaz_komunikat_wykonania(strona.page, zaplac(gps, a))
    assert len(otwarte) == 1 and komunikaty[-1] == "Zapisano płatność i przesunięto termin."


# ============================================================================
#  6. MIGRACJA, CHMURA, KOSZ
# ============================================================================

def test_migracja_49_doklada_kolumny_i_nie_rusza_wydatkow(magazyn):
    probki_baz.zbuduj_baze_w_wersji(db.BAZA_DANYCH, 48, DRABINKA)
    conn = sqlite3.connect(db.BAZA_DANYCH)
    c = conn.cursor()
    c.execute("INSERT INTO samochody (nazwa, typ_paliwa) VALUES ('Stary', 'Benzyna')")
    a = c.lastrowid
    c.execute("INSERT INTO wydatki_cykliczne (auto_id, nazwa, kwota, okres_dni, nastepna_data, czy_koszt, typ) "
              "VALUES (?, 'Rata leasingu', 1900, 30, '10.11.2026', 1, 'wydatek')", (a,))
    conn.commit()
    conn.close()
    assert not set(db.KOLUMNY_UMOWY) & set(pomoce.kolumny("wydatki_cykliczne"))

    db.init_db()

    assert set(db.KOLUMNY_UMOWY) <= set(pomoce.kolumny("wydatki_cykliczne"))
    w = jeden("SELECT typ, kwota, nastepna_data, " + ", ".join(db.KOLUMNY_UMOWY) + " FROM wydatki_cykliczne")
    assert tuple(w) == ("wydatek", 1900.0, "10.11.2026") + (None,) * len(db.KOLUMNY_UMOWY)
    assert db.pobierz_raty(a) == []


def test_umowa_jedzie_do_chmury_jako_dopisane_kolumny():
    for kolumna in db.KOLUMNY_UMOWY:
        assert kolumna in KONFIG_WYDATKOW["kolumny"] and kolumna in KONFIG_WYDATKOW["dopisane"], kolumna


class _Odpowiedz:
    def __init__(self, data=None):
        self.data = data


class ChmuraWPamieci:
    """Supabase na tyle, na ile potrzebuje go `_wypchnij_tabele`."""

    def __init__(self, rekordy=None):
        self.rekordy = dict(rekordy or {})

    def rpc(self, nazwa, parametry):
        chmura = self

        class _Wywolanie:
            def execute(self):
                if nazwa == "aktualizuj_zdalny_rekord":
                    chmura.rekordy[parametry["p_id"]] = parametry["p_dane"]
                    return _Odpowiedz()
                nowe = f"nowy-{len(chmura.rekordy) + 1}"
                chmura.rekordy[nowe] = parametry["p_dane"]
                return _Odpowiedz(nowe)
        return _Wywolanie()

    def table(self, nazwa):
        chmura = self

        class _Zapytanie:
            def select(self, *_):
                return self

            def in_(self, _pole, identyfikatory):
                self.identyfikatory = list(identyfikatory)
                return self

            def execute(self):
                return _Odpowiedz([{"id": i, "dane": chmura.rekordy[i]} for i in self.identyfikatory
                                   if i in chmura.rekordy])
        return _Zapytanie()


def wypchnij(chmura, auto_id, konfig=KONFIG_WYDATKOW):
    return sync_wysylanie._wypchnij_tabele(chmura, "wspolny", auto_id, konfig, db.ROLA_WLASCICIEL)[0]


def test_pierwsza_synchronizacja_po_aktualizacji_nie_wysyla_wydatkow(baza):
    """Wpis zsynchronizowany starszą wersją: hash i chmura bez kluczy umowy.
    Puste nowe kolumny to nie zmiana — dopiero przestawienie na raty jedzie."""
    a = auto()
    db.dodaj_wydatek_cykliczny(a, "Abonament GPS", 30.0, 30, "10.11.2026")
    (w_id, *_), = db.pobierz_wydatki_cykliczne(a)
    stare = {k: v for k, v in wpis(w_id).items() if k in KONFIG_WYDATKOW["kolumny"] and k not in db.KOLUMNY_UMOWY}
    with db.polacz_baze() as conn:
        conn.execute("UPDATE wydatki_cykliczne SET zdalne_id='cykl-A', zdalny_hash=? WHERE id=?",
                     (sync_wysylanie._hash_zawartosci(stare), w_id))
    sync_konflikty._konflikty_biezacej_synchronizacji.clear()
    chmura = ChmuraWPamieci({"cykl-A": stare})

    assert wypchnij(chmura, a) == 0

    db.zapisz_umowe_raty(a, {"typ": db.TYP_CYKLICZNY_LEASING, "nazwa": "Leasing", "kwota": 1900,
                             "liczba_rat": 36, "data_pierwszej_raty": "10.11.2026"}, w_id)
    assert wypchnij(chmura, a) == 1
    assert chmura.rekordy["cykl-A"]["liczba_rat"] == 36 and chmura.rekordy["cykl-A"]["typ"] == "leasing"
    assert sync_konflikty._konflikty_biezacej_synchronizacji == []

    # Bez tolerancji pustych dopisanych kolumn poleciałyby po aktualizacji wszystkie wpisy.
    db.dodaj_wydatek_cykliczny(a, "Myjnia abonament", 50.0, 30, "12.11.2026")
    myjnia = max(w[0] for w in db.pobierz_wydatki_cykliczne(a))
    stare = {k: v for k, v in wpis(myjnia).items() if k in KONFIG_WYDATKOW["kolumny"] and k not in db.KOLUMNY_UMOWY}
    with db.polacz_baze() as conn:
        conn.execute("UPDATE wydatki_cykliczne SET zdalne_id='cykl-M', zdalny_hash=? WHERE id=?",
                     (sync_wysylanie._hash_zawartosci(stare), myjnia))
    assert wypchnij(ChmuraWPamieci({"cykl-A": chmura.rekordy["cykl-A"], "cykl-M": stare}), a) == 0
    assert wypchnij(ChmuraWPamieci({"cykl-A": chmura.rekordy["cykl-A"], "cykl-M": stare}), a,
                    {**KONFIG_WYDATKOW, "dopisane": []}) == 1


def test_umowa_i_zaplacone_raty_dojezdzaja_na_drugi_telefon(baza):
    a = auto()
    w_id = umowa(a, liczba_rat=12, kwota_finansowania=21000, wykup=1000)
    zaplac(w_id, a)
    chmura = ChmuraWPamieci()
    assert wypchnij(chmura, a) == 1
    (wyslany,) = chmura.rekordy.values()

    drugie = auto("Drugi telefon")
    assert sync_pobieranie._zastosuj_rekord(KONFIG_WYDATKOW, {"id": "cykl-B", "dane": wyslany}, drugie, {}) == 1

    (u1,), (u2,) = db.pobierz_raty(a), db.pobierz_raty(drugie)
    assert u2["harmonogram"]["zaplacone"] == 1
    for klucz in ("do_splaty", "odsetki_do_zaplaty", "data_ostatniej_raty", "nastepna"):
        assert u2["harmonogram"][klucz] == u1["harmonogram"][klucz], klucz


def test_rekord_ze_starszej_wersji_nie_kasuje_umowy(baza):
    """Druga osoba ze starą aplikacją odhaczyła ratę po swojemu: przesunęła
    termin, kluczy umowy nie zna. Umowa na tym telefonie zostaje."""
    a = auto()
    w_id = umowa(a, liczba_rat=12)
    with db.polacz_baze() as conn:
        conn.execute("UPDATE wydatki_cykliczne SET zdalne_id='cykl-C' WHERE id=?", (w_id,))
    znane = {"cykl-C": {"id": w_id, "hash": "inny"}}
    stary = {"nazwa": "Leasing Corolli", "kwota": 1900.0, "okres_dni": 30, "nastepna_data": "01.01.2030",
             "czy_koszt": 1, "typ": "leasing"}

    sync_pobieranie._zastosuj_rekord(KONFIG_WYDATKOW, {"id": "cykl-C", "dane": stary}, a, znane)

    w = wpis(w_id)
    assert w["nastepna_data"] == "01.01.2030" and w["liczba_rat"] == 12 and w["data_pierwszej_raty"]


def test_kosz_przenosi_umowe_z_harmonogramem(baza):
    ids = pomoce.utworz_pojazd("Do kosza")
    w_id = umowa(ids["auto_id"], liczba_rat=24, kwota_finansowania=40000, wykup=1000, zaplacone_platnosci=5)
    przed = {k: wpis(w_id)[k] for k in db.KOLUMNY_UMOWY + ("typ", "nastepna_data")}

    wynik = db.usun_auto_do_kosza(ids["auto_id"])
    assert jeden("SELECT COUNT(*) FROM wydatki_cykliczne WHERE id=?", w_id)[0] == 0
    db.przywroc_auto_z_kosza(wynik["kosz_id"])

    a = jeden("SELECT id FROM samochody WHERE nazwa='Do kosza'")[0]
    (po,) = [u for u in db.pobierz_raty(a)]
    assert {k: po[k] for k in przed} == przed
