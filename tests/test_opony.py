"""Opony: wiek z DOT, progi bieżnika sezonu, pomiary kół, okresy montażu i kilometry na komplecie,
prognoza zużycia, zmiana opon jako zdarzenie (Serwis, koszt, przypomnienie, „Cofnij”), odtworzenie
sezonów z Serwisu, dzwonek, kondycja, oś przyszłości, kalendarz i ekrany."""

import sys
from datetime import date, timedelta
from types import SimpleNamespace

import flet as ft
import pytest

import audyty
import db
import pomoce
import sync
import utils
from db import kalendarz as db_kalendarz
from db import plik_pojazdu as db_plik
from sync import konflikty as sync_konflikty
from sync import pobieranie as sync_pobieranie
from sync import wysylanie as sync_wysylanie
from views.formularze.wpis_serwisowy import FormularzWpisView
from views.garage_view import FormularzOponyView, MagazynView
from views.opony_view import FormularzPomiaruView, KompletOponView

DZIS = date(2026, 10, 20)


def auto(nazwa="Astra"):
    return pomoce.wstaw("samochody", nazwa=nazwa, typ_paliwa="Benzyna", status=db.STATUS_POJAZDU_AKTYWNY,
                        rola_wspoldzielenia=db.ROLA_WLASCICIEL)


def komplet(auto_id, sezon="Zimowe", zamontowany=False, **pola):
    return pomoce.wstaw("zestawy_opon", auto_id=auto_id, sezon=sezon, rozmiar="205/55 R16", ilosc=4,
                        zamontowane=int(zamontowany), os_montazu="Wszystkie", **pola)


def odczyt(auto_id, data, km):
    return pomoce.wstaw("odczyty_przebiegu", auto_id=auto_id, data=data, przebieg=km)


def podzespol_opon(auto_id):
    return pomoce.wstaw("zadania", auto_id=auto_id, nazwa="Wymiana opon / Kół", dotyczy_opon=1)


def d(tekst):
    return tekst


# ============================================================================
#  WIEK, PROGI, TEKSTY
# ============================================================================

def test_kod_dot_czyta_kilka_kodow_i_pelny_zapis():
    assert db.daty_produkcji("2321", DZIS) == [date.fromisocalendar(2021, 23, 1)]
    assert len(db.daty_produkcji("2321, 0222; 1523", DZIS)) == 3
    assert db.daty_produkcji("2321 0222", DZIS)[0].year == 2021
    # Pełny kod: grupy z literami to zakład i rozmiar — data to ostatnia grupa.
    assert db.daty_produkcji("DOT EX 2015 0322", DZIS) == [date.fromisocalendar(2022, 3, 1)]
    # Tydzień spoza 1–53 i rok z przyszłości to nie data produkcji.
    assert db.daty_produkcji("6021", DZIS) == []
    assert db.daty_produkcji("0199", DZIS) == []
    assert db.wiek_opon("", DZIS) is None


@pytest.mark.parametrize("kod, status", [("4224", "ok"), ("4220", "kontrola"), ("4215", "wymiana")])
def test_wiek_opon_progi(kod, status):
    wiek = db.wiek_opon(f"{kod}, 0125", DZIS)
    assert wiek["status"] == status
    assert wiek["kodow"] == 2  # najstarsza opona decyduje
    assert wiek["data_wymiany"].year == wiek["data"].year + db.WIEK_WYMIANY_OPON


def test_tekst_wieku_i_bieznika():
    assert db.tekst_wieku(db.wiek_opon("3226", DZIS)) == "2 mies."
    assert db.tekst_wieku(db.wiek_opon("4221", DZIS)) == "5 lat"
    assert db.tekst_bieznika(6.55) == "6,6 mm" or db.tekst_bieznika(6.55) == "6,5 mm"
    assert db.tekst_bieznika(None) is None


@pytest.mark.parametrize("sezon, mm, status", [
    ("Zimowe", 3.5, "uwaga"), ("Letnie", 3.5, "ok"), ("Całoroczne", 3.9, "uwaga"),
    ("Letnie", 2.9, "uwaga"), ("Zimowe", 1.5, "krytyczny"), ("Letnie", None, None),
])
def test_progi_bieznika_zaleza_od_sezonu(sezon, mm, status):
    assert db.status_bieznika(mm, sezon) == status


def test_tempo_zuzycia_najmniejszymi_kwadratami():
    assert db.tempo_zuzycia([(0, 8.0), (5000, 7.0), (10000, 6.0)]) == pytest.approx(0.2)
    assert db.tempo_zuzycia([(0, 8.0), (1000, 7.0)]) is None        # za krótko na tempo
    assert db.tempo_zuzycia([(0, 7.0), (6000, 6.9)]) is None        # spadek w granicy błędu miarki
    assert db.tempo_zuzycia([(0, 7.0), (6000, 7.4)]) is None        # bieżnik nie rośnie
    assert db.tempo_zuzycia([(0, 7.0)]) is None


# ============================================================================
#  POMIARY
# ============================================================================

def test_pomiar_kazdego_kola_i_bieznik_kompletu(baza):
    a = auto()
    z = komplet(a, "Zimowe", True)
    pid = db.zapisz_pomiar(a, z, {"data": "01.03.2026", "lp": "6,8", "pp": 6.6, "lt": 7.1, "pt": ""})
    pomiar = db.pobierz_pomiar(pid)
    assert pomiar["kola"] == {"lp": 6.8, "pp": 6.6, "lt": 7.1}
    assert pomiar["min"] == 6.6
    with db.polacz_baze() as conn:
        assert conn.execute("SELECT glebokosc_bieznika, data_pomiaru FROM zestawy_opon WHERE id=?",
                            (z,)).fetchone() == (6.6, "01.03.2026")
    assert db.blad_pomiaru({"data": "01.03.2026"}) == "Wpisz bieżnik choć jednego koła"
    assert db.blad_pomiaru({"data": "01.03.2026", "lp": "16"}) == "Bieżnik to od 0 do 15 mm"
    assert db.blad_pomiaru({"data": "", "lp": "5"}) == "Wybierz dzień pomiaru"


def test_dawny_bieznik_kompletu_zostaje_pierwszym_pomiarem(baza):
    a = auto()
    z = komplet(a, "Letnie", glebokosc_bieznika=7.5, data_pomiaru="10.04.2025")
    # Przed pierwszym pomiarem dawny bieżnik kompletu udaje pomiar wszystkich kół.
    k = db.komplet_opon(a, z, DZIS)
    assert k["bieznik"] == 7.5 and k["ostatni_pomiar"]["dawny"]
    db.zapisz_pomiar(a, z, {"data": "01.10.2025", "lp": 6.9, "pp": 6.9, "lt": 7.0, "pt": 7.0})
    pomiary = db.pobierz_pomiary(a, z)
    assert [p["data"] for p in pomiary] == ["10.04.2025", "01.10.2025"]
    assert pomiary[0]["kola"] == {k: 7.5 for k in db.POZYCJE_KOL}


def test_usuniecie_pomiaru_cofa_bieznik_kompletu(baza):
    a = auto()
    z = komplet(a)
    db.zapisz_pomiar(a, z, {"data": "01.02.2026", "lp": 7.0})
    drugi = db.zapisz_pomiar(a, z, {"data": "01.03.2026", "lp": 6.0})
    wynik = db.usun_pomiar_z_cofnieciem(drugi)
    assert db.komplet_opon(a, z, DZIS)["bieznik"] == 7.0
    wynik["cofnij"]()
    assert db.komplet_opon(a, z, DZIS)["bieznik"] == 6.0
    assert db.pobierz_pomiar(drugi) is not None


# ============================================================================
#  ZMIANA OPON
# ============================================================================

def _auto_z_kompletami():
    a = auto()
    letnie = komplet(a, "Letnie", True)
    zimowe = komplet(a, "Zimowe", False, marka_model="Michelin Alpin 6")
    odczyt(a, "01.04.2026", 100000)
    odczyt(a, "01.10.2026", 106000)
    return a, letnie, zimowe


def test_zmiana_opon_przestawia_komplet_dziennik_serwis_i_przypomnienie(baza):
    a, letnie, zimowe = _auto_z_kompletami()
    zadanie = podzespol_opon(a)
    db.dodaj_przypomnienie_o_oponach(a, nastepna_data="05.11.2026")
    db.ustaw_poczatek_montazu(a, letnie, "01.04.2026", 100000)

    wynik = db.zmien_opony(a, zimowe, {"data": "01.10.2026", "przebieg": 106000, "koszt": "120",
                                       "wykonawca": "Wulkanizacja Kowalski"})
    assert wynik["ok"] and wynik["na"] == "Zimowe" and wynik["z"] == "Letnie"
    with db.polacz_baze() as conn:
        assert db.flagi_montazu(conn, a) == {zimowe: "Wszystkie"}
        historia = conn.execute("SELECT zadanie_id, data, przebieg, cena, wykonawca, kategoria FROM historia "
                                "WHERE id=?", (wynik["historia_id"],)).fetchone()
        termin = conn.execute("SELECT nastepna_data FROM wydatki_cykliczne WHERE auto_id=?", (a,)).fetchone()[0]
    assert historia == (zadanie, "01.10.2026", 106000, 120.0, "Wulkanizacja Kowalski", "Zimowe")
    # Termin liczy się od dnia zmiany, nie od dnia wpisania.
    assert termin == (date(2026, 10, 1) + timedelta(days=db.OKRES_ZMIANY_OPON_DNI)).strftime("%d.%m.%Y")

    okresy = {m["zestaw_id"]: m for m in db.pobierz_montaze(a)}
    assert okresy[letnie]["data_zdjecia"] == "01.10.2026" and okresy[letnie]["przebieg_zdjecia"] == 106000
    assert okresy[zimowe]["data_zdjecia"] is None and okresy[zimowe]["historia_id"] == wynik["historia_id"]
    assert db.komplet_opon(a, letnie, DZIS)["km"] == 6000


def test_cofniecie_zmiany_wraca_do_stanu_sprzed(baza):
    a, letnie, zimowe = _auto_z_kompletami()
    podzespol_opon(a)
    db.dodaj_przypomnienie_o_oponach(a, nastepna_data="05.11.2026")
    db.ustaw_poczatek_montazu(a, letnie, "01.04.2026", 100000)
    przed = pomoce.zrzut_danych()

    wynik = db.zmien_opony(a, zimowe, {"data": "01.10.2026", "przebieg": 106000, "koszt": 120})
    assert db.cofnij_zmiane_opon(wynik["cofniecie"])
    po = pomoce.zrzut_danych()
    for tabela in ("zestawy_opon", "montaze_opon", "historia", "wydatki_cykliczne", "inne_koszty"):
        assert po[tabela] == przed[tabela], tabela
    # Drugie „Cofnij” niczego już nie rusza.
    assert not db.cofnij_zmiane_opon(wynik["cofniecie"])


def test_cofniecie_odmawia_po_kolejnej_zmianie(baza):
    a, letnie, zimowe = _auto_z_kompletami()
    pierwsza = db.zmien_opony(a, zimowe, {"data": "01.10.2026"})
    db.zmien_opony(a, letnie, {"data": "02.10.2026"})
    assert not db.cofnij_zmiane_opon(pierwsza["cofniecie"])


def test_zmiana_bez_podzespolu_opon_zapisuje_inny_koszt(baza):
    a, letnie, zimowe = _auto_z_kompletami()
    wynik = db.zmien_opony(a, zimowe, {"data": "01.10.2026", "koszt": 99})
    assert wynik["historia_id"] is None and wynik["koszt_id"]
    with db.polacz_baze() as conn:
        assert conn.execute("SELECT nazwa, kwota FROM inne_koszty WHERE id=?",
                            (wynik["koszt_id"],)).fetchone() == ("Zmiana opon na zimowe", 99.0)
    # Bez kosztu i bez podzespołu — tylko dziennik montażu.
    wynik = db.zmien_opony(a, letnie, {"data": "02.10.2026"})
    assert wynik["historia_id"] is None and wynik["koszt_id"] is None


def test_zmiana_na_jedna_os_zostawia_druga(baza):
    a = auto()
    przod = komplet(a, "Letnie", True)
    tyl = komplet(a, "Letnie", False)
    db.zmien_opony(a, przod, {"data": "01.05.2026", "os": "Przód"})
    db.zmien_opony(a, tyl, {"data": "01.05.2026", "os": "Tył"})
    with db.polacz_baze() as conn:
        assert db.flagi_montazu(conn, a) == {przod: "Przód", tyl: "Tył"}
    assert db.zmien_opony(a, tyl, {"data": "02.05.2026", "os": "Tył"})["powod"] == "juz_na_aucie"


def test_podglad_nie_zmienia_opon(baza):
    a, letnie, zimowe = _auto_z_kompletami()
    db.ustaw_role_pojazdu(a, db.ROLA_PODGLAD)
    assert db.zmien_opony(a, zimowe, {"data": "01.10.2026"}) is None
    assert db.zapisz_pomiar(a, zimowe, {"data": "01.10.2026", "lp": 7}) is None


# ============================================================================
#  OKRESY, KILOMETRY, PROGNOZA
# ============================================================================

def test_poczatek_montazu_z_propozycji_serwisu_i_stary_okres(baza):
    a, letnie, zimowe = _auto_z_kompletami()
    zadanie = podzespol_opon(a)
    pomoce.wstaw("historia", zadanie_id=zadanie, data="03.04.2026", przebieg=100100, cena=100, kategoria="Letnie")
    propozycja = db.propozycja_poczatku_montazu(a, letnie, DZIS)
    assert propozycja["data"] == "03.04.2026" and propozycja["przebieg"] == 100100
    # Otwarty okres zdjętego kompletu (zmiana z innego telefonu) zamyka się dniem założenia.
    pomoce.wstaw("montaze_opon", auto_id=a, zestaw_id=zimowe, data="01.11.2025", os_montazu="Wszystkie")
    assert db.dane_opon(a, DZIS)["brak_poczatku"] == [letnie]
    db.ustaw_poczatek_montazu(a, letnie, propozycja["data"], propozycja["przebieg"], propozycja["historia_id"])
    okresy = {m["zestaw_id"]: m for m in db.pobierz_montaze(a)}
    assert okresy[zimowe]["data_zdjecia"] == "03.04.2026"
    assert db.dane_opon(a, DZIS)["brak_poczatku"] == []
    assert db.ustaw_poczatek_montazu(a, letnie, "03.04.2026") is None  # drugi otwarty okres nie powstaje


def test_odtworzenie_sezonow_z_serwisu(baza):
    a, letnie, zimowe = _auto_z_kompletami()
    zadanie = podzespol_opon(a)
    for data, km, sezon in (("05.11.2024", 80000, "Zimowe"), ("05.04.2025", 85000, "Letnie"),
                            ("06.11.2025", 92000, "Zimowe"), ("01.04.2026", 100000, "Letnie")):
        pomoce.wstaw("historia", zadanie_id=zadanie, data=data, przebieg=km, cena=100, kategoria=sezon)
    assert db.dane_opon(a, DZIS)["do_odtworzenia"] == 4
    assert db.odtworz_sezony_z_serwisu(a, DZIS) == 4
    zimowe_k = db.komplet_opon(a, zimowe, DZIS)
    assert zimowe_k["km"] == 5000 + 8000
    assert zimowe_k["km_sezonu"] == pytest.approx(6500)
    assert db.komplet_opon(a, letnie, DZIS)["otwarty"]["data"] == "01.04.2026"
    assert db.odtworz_sezony_z_serwisu(a, DZIS) == 0  # dziennik już jest


def test_prognoza_z_pomiarow_na_kilometrach_kompletu(baza):
    a, letnie, zimowe = _auto_z_kompletami()
    odczyt(a, "01.11.2024", 80000)
    for od, do, km_od, km_do in (("01.11.2024", "01.04.2025", 80000, 85000),
                                 ("01.11.2025", "01.04.2026", 92000, 100000)):
        pomoce.wstaw("montaze_opon", auto_id=a, zestaw_id=zimowe, os_montazu="Wszystkie", data=od, przebieg=km_od,
                     data_zdjecia=do, przebieg_zdjecia=km_do)
    # Latem komplet leży w piwnicy — pomiar z października to dalej 5 000 km na komplecie.
    for data, mm in (("01.11.2024", 8.0), ("01.10.2025", 7.0), ("01.04.2026", 5.4)):
        db.zapisz_pomiar(a, zimowe, {"data": data, "lp": mm, "pp": mm, "lt": mm + 0.5, "pt": mm + 0.5})
    k = db.komplet_opon(a, zimowe, DZIS)
    assert k["km"] == 13000
    prognoza = k["prognoza"]
    assert prognoza["tempo"] == pytest.approx(0.2, abs=0.01)
    assert prognoza["cel_mm"] == 4.0
    assert prognoza["zostalo_km"] == pytest.approx(7000, abs=200)
    assert prognoza["sezonow"] == pytest.approx(7000 / 6500, abs=0.1)
    assert db.opis_prognozy(prognoza).startswith("do 4 mm ok. 7 000 km")
    assert k["roznica_osi"] == pytest.approx(-0.5)


def test_zamontowany_bez_dziennika_liczy_z_licznika_auta(baza):
    a = auto()
    z = komplet(a, "Całoroczne", True)
    odczyt(a, "01.01.2026", 50000)
    odczyt(a, "01.09.2026", 60000)
    db.zapisz_pomiar(a, z, {"data": "01.01.2026", "przebieg": 50000, "lp": 7.0})
    db.zapisz_pomiar(a, z, {"data": "01.09.2026", "przebieg": 60000, "lp": 5.0})
    prognoza = db.komplet_opon(a, z, DZIS)["prognoza"]
    assert prognoza["tempo"] == pytest.approx(0.2)
    assert prognoza["sezonow"] is None and prognoza["data"] is not None


# ============================================================================
#  DZWONEK, KONDYCJA, OŚ
# ============================================================================

def test_dzwonek_i_kondycja_o_bierzniku_i_wieku(baza):
    a = auto()
    z = komplet(a, "Zimowe", True, numer_dot="0114")
    db.zapisz_pomiar(a, z, {"data": "01.10.2026", "lp": 3.5})
    sygnaly = {s["klucz"]: s for s in db.sygnaly_opon(a, DZIS)}
    assert sygnaly[f"opony:bieznik:{z}"]["status"] == "pilne"
    assert sygnaly[f"opony:wiek:{z}"]["status"] == "przeterminowane"
    klucze = {p["klucz"] for p in db.powody_kondycji_opon(a, db.dane_opon(a, DZIS))}
    assert klucze == {"bieznik_niski", "opony_wiek_wymiana"}
    # Komplet w piwnicy nie dzwoni.
    komplet(a, "Letnie", False, numer_dot="0110", glebokosc_bieznika=1.0, data_pomiaru="01.10.2026")
    assert len(db.sygnaly_opon(a, DZIS)) == 2


def _auto_z_prognoza():
    """Całoroczne na aucie z dwoma pomiarami (prognoza końca bieżnika) i kodem DOT z 2017 (granica wieku)."""
    a = auto()
    z = komplet(a, "Całoroczne", True, numer_dot="0517")
    odczyt(a, "01.01.2026", 50000)
    odczyt(a, "01.09.2026", 60000)
    db.zapisz_pomiar(a, z, {"data": "01.01.2026", "przebieg": 50000, "lp": 6.0})
    db.zapisz_pomiar(a, z, {"data": "01.09.2026", "przebieg": 60000, "lp": 5.0})
    return a, z


def test_terminy_opon_na_osi(baza):
    a, z = _auto_z_prognoza()
    terminy = {t["rodzaj"]: t for t in db.terminy_opon(a, DZIS, DZIS + timedelta(days=730), db.dane_opon(a, DZIS))}
    assert terminy["opony_wiek"]["data"] == date.fromisocalendar(2017, 5, 1).replace(year=2027)
    assert terminy["opony_bieznik"]["prognoza"] and terminy["opony_bieznik"]["data"] > DZIS


def test_os_przyszlosci_i_kalendarz_z_prognoza_bieznika(baza):
    a, z = _auto_z_prognoza()
    pozycje = {p["rodzaj"]: p for p in db.os_przyszlosci(a, dni=730, dzis=DZIS)["pozycje"]
               if p["rodzaj"] in ("opony_bieznik", "opony_wiek")}
    bieznik, wiek = pozycje["opony_bieznik"], pozycje["opony_wiek"]
    assert (bieznik["ikona"], bieznik["trasa"], bieznik["prognoza"]) == ("opony", f"/magazyn/opony/{z}", True)
    assert bieznik["zostalo_km"] % 100 == 0  # szacunek, nie co do kilometra
    assert utils.opis_pozycji_osi(bieznik, "km").endswith("na komplecie · prognoza z pomiarów")
    assert utils.opis_pozycji_osi(wiek, "km").endswith("zalecana wymiana opon")
    # Kalendarz bierze datę prognozy końca bieżnika, nie granicę z licznika czasu.
    terminy = db.terminy_kalendarza(a, DZIS)
    daty = {t["grupa"]: t["data"] for t in terminy}
    assert (daty[f"opony:bieznik:{z}"], daty[f"opony:wiek:{z}"]) == (bieznik["data"], wiek["data"])
    db.zapamietaj_wysylke_kalendarza({a: terminy}, 1, DZIS)
    assert db.stan_kalendarza(a, DZIS) is None


def test_kalendarz_nie_zglasza_drobnego_przesuniecia_prognozy():
    wyslane = {"opony:bieznik:7": ["2027-05-01", 0], "opony:wiek:7": ["2027-02-01", 0]}

    def zmienione(bieznik, wiek):
        return db_kalendarz._zmienione_grupy(wyslane, {"opony:bieznik:7": (bieznik, 0),
                                                       "opony:wiek:7": (wiek, 0)}, DZIS)

    assert zmienione(date(2027, 5, 25), date(2027, 2, 1)) == 0   # prognoza płynie z jazdą
    assert zmienione(date(2027, 6, 5), date(2027, 2, 1)) == 1    # ponad miesiąc — czas na nowy plik
    assert zmienione(date(2027, 5, 1), date(2027, 2, 2)) == 1    # granica wieku jest sztywna


def test_dzwonek_kondycja_i_kokpit(baza):
    a = auto()
    z = komplet(a, "Zimowe", True, numer_dot="0114")
    db.zapisz_pomiar(a, z, {"data": "01.10.2026", "lp": 3.5})
    opony = [p for p in db.pobierz_powiadomienia(a) if p["typ"] == "opony"]
    assert len(opony) == 2 and {p["trasa"] for p in opony} == {f"/magazyn/opony/{z}"}
    powody = [p for p in db.pobierz_rozbicie_kondycji(a)["powody"] if p["typ"] == "opony"]
    assert sum(p["punkty"] for p in powody) == (db.KARY_KONDYCJI["bieznik_niski"]
                                                + db.KARY_KONDYCJI["opony_wiek_wymiana"])
    assert [k["id"] for k in db.metryka_kokpitu(a, "opony")["zamontowane"]] == [z]


def test_paszport_z_kompletami(baza):
    a, letnie, zimowe = _auto_z_kompletami()
    db.zapisz_pomiar(a, letnie, {"data": "01.09.2026", "lp": 2.5, "pp": 2.8, "lt": 3.1, "pt": 3.0})
    with db.polacz_baze() as conn:
        conn.execute("UPDATE zestawy_opon SET numer_dot='3521', na_felgach=1, felgi='alu 16' WHERE id=?", (zimowe,))
    dane = db.pobierz_dane_paszportu(a)
    opony = {nazwa: (opis, szczegoly, status) for nazwa, opis, szczegoly, status in dane["opony"]}
    opis, _, status = opony["Letnie · 205/55 R16"]
    assert (opis, status) == ("bieżnik 2,5 mm (01.09.2026) · na aucie", db.STATUS_BIEZNIKA_UWAGA)
    opis, szczegoly, status = opony["Zimowe · Michelin Alpin 6 · 205/55 R16"]
    assert opis.startswith("bieżnik niezmierzony · ") and opis.endswith("od produkcji · w magazynie")
    assert (szczegoly, status) == ("na felgach (alu 16) · DOT 3521", None)
    assert db.generuj_pdf_raportu("Astra", {}, "cały okres", tryb_paszportu=True, **dane)[:4] == b"%PDF"


def test_eksport_kompletow_pomiarow_i_sezonow(baza):
    a, letnie, zimowe = _auto_z_kompletami()
    with db.polacz_baze() as conn:
        conn.execute("UPDATE zestawy_opon SET miejsce='Wulkanizacja Kowalski', numer_kwitu='K-17' WHERE id=?",
                     (zimowe,))
    db.ustaw_poczatek_montazu(a, letnie, "01.04.2026", 100000)
    db.zapisz_pomiar(a, letnie, {"data": "01.04.2026", "przebieg": 100000, "lp": 7.0, "pp": 7.0, "lt": 7.2, "pt": 7.2})
    db.zapisz_pomiar(a, letnie, {"data": "01.10.2026", "przebieg": 106000, "lp": 6.1, "pp": 6.0, "lt": 6.5, "pt": 6.6,
                                 "uwagi": "Po wakacjach"})
    db.zmien_opony(a, zimowe, {"data": "01.10.2026", "przebieg": 106000})

    dane = db.pobierz_dane_eksportu(a, ["zestawy_opon", "pomiary_bieznika", "montaze_opon"])
    naglowki, wiersze = dane["zestawy_opon"]
    komplety = {w[0]: dict(zip(naglowki, w)) for w in wiersze}
    assert (komplety["Letnie"]["Na komplecie (km)"], komplety["Letnie"]["Bieżnik (mm)"]) == (6000, "6,0")
    assert (komplety["Zimowe"]["Stan"], komplety["Zimowe"]["Gdzie leży"], komplety["Zimowe"]["Nr kwitu"]) == \
        ("Na aucie (Wszystkie)", "Wulkanizacja Kowalski", "K-17")
    naglowki, wiersze = dane["pomiary_bieznika"]
    assert [dict(zip(naglowki, w))["Najpłytsze (mm)"] for w in wiersze] == ["7,0", "6,0"]
    assert wiersze[-1][-1] == "Po wakacjach"
    naglowki, wiersze = dane["montaze_opon"]
    assert [(w[0], w[2], w[4], w[6]) for w in wiersze] == [("Letnie", "01.04.2026", "01.10.2026", 6000),
                                                          ("Zimowe Michelin Alpin 6", "01.10.2026", "", 0)]
    # Zakres dat filtruje pomiary i sezony po dniu.
    jesien = db.pobierz_dane_eksportu(a, ["pomiary_bieznika", "montaze_opon"], date(2026, 6, 1), date(2026, 12, 31))
    assert [w[0] for w in jesien["pomiary_bieznika"][1]] == ["01.10.2026"]
    assert [w[2] for w in jesien["montaze_opon"][1]] == ["01.10.2026"]
    assert db.generuj_eksport_csv(dane)[0]


def test_wyszukiwarka_znajduje_komplet_po_przechowalni(baza):
    a = auto()
    z = komplet(a, "Zimowe", numer_dot="2321", miejsce="Wulkanizacja Kowalski", numer_kwitu="K-17")
    for fraza in ("K-17", "Kowalski"):
        assert [w["trasa"] for w in db.globalne_wyszukiwanie(a, fraza)] == [f"/magazyn/opony/{z}"], fraza


# ============================================================================
#  CHMURA, KOSZ, PLIK DLA KUPUJĄCEGO, ROLE
# ============================================================================

def test_pomiar_i_sezon_jada_na_drugi_telefon(baza):
    a, letnie, zimowe = _auto_z_kompletami()
    podzespol_opon(a)
    with db.polacz_baze() as conn:
        conn.execute("UPDATE zestawy_opon SET miejsce=?, numer_kwitu=?, oplata_przechowania=?, na_felgach=1, felgi=? "
                     "WHERE id=?", ("Wulkanizacja Kowalski", "K-17", 150.0, "alu 16", zimowe))
    db.zapisz_pomiar(a, zimowe, {"data": "01.10.2026", "przebieg": 106000, "lp": 7.8, "pp": 7.7, "lt": 8.0, "pt": 8.1,
                                 "uwagi": "Po przechowalni"})
    db.ustaw_poczatek_montazu(a, letnie, "01.04.2026", 100000)
    db.zmien_opony(a, zimowe, {"data": "01.10.2026", "przebieg": 106000, "koszt": 120})
    chmura = pomoce.ChmuraWPamieci()
    for konfig in sync.KONFIGURACJA_SYNC:
        sync_wysylanie._wypchnij_tabele(chmura, "wspolny", a, konfig, db.ROLA_WLASCICIEL)
    (pomiar,) = [d for z, d in chmura.rekordy.items() if z.startswith("pomiary_bieznika-")]
    assert pomiar["zestaw_id_zdalne"] and "data_iso" not in pomiar
    (otwarty,) = [d for z, d in chmura.rekordy.items() if z.startswith("montaze_opon-") and not d["data_zdjecia"]]
    assert otwarty["zestaw_id_zdalne"] and otwarty["historia_id_zdalne"]

    # Drugi telefon to druga baza — tu ten sam plik, więc pojazd A znika, zanim B dostanie rekordy.
    with db.polacz_baze() as conn:
        conn.execute("DELETE FROM samochody WHERE id=?", (a,))
    b = auto("Drugi telefon")
    for konfig in sync.KONFIGURACJA_SYNC:
        for zdalne_id, dane in chmura.rekordy.items():
            if zdalne_id.startswith(f"{konfig['tabela']}-"):
                sync_pobieranie._zastosuj_rekord(konfig, {"id": zdalne_id, "dane": dane}, b, {})
    (na_aucie,) = db.dane_opon(b, DZIS)["zamontowane"]
    assert (na_aucie["sezon"], na_aucie["miejsce"], na_aucie["numer_kwitu"], na_aucie["oplata_przechowania"],
            na_aucie["na_felgach"], na_aucie["felgi"]) == ("Zimowe", "Wulkanizacja Kowalski", "K-17", 150.0, 1, "alu 16")
    assert na_aucie["ostatni_pomiar"]["kola"] == {"lp": 7.8, "pp": 7.7, "lt": 8.0, "pt": 8.1}
    assert na_aucie["otwarty"]["data_iso"] == "2026-10-01" and na_aucie["otwarty"]["historia_id"]
    assert db.komplet_opon(b, next(k["id"] for k in db.dane_opon(b, DZIS)["komplety"] if k["sezon"] == "Letnie"),
                           DZIS)["km"] == 6000


def test_komplet_sprzed_aktualizacji_nie_jedzie_drugi_raz(baza):
    """Komplet wysłany starszą wersją (bez przechowalni i felg) po aktualizacji jest taki sam — jedzie
    dopiero, gdy ktoś wpisze, gdzie leży. Inaczej pierwsza synchronizacja wysłałaby wszystkie komplety."""
    konfig = next(k for k in sync.KONFIGURACJA_SYNC if k["tabela"] == "zestawy_opon")
    nowe_kolumny = ("miejsce", "numer_kwitu", "oplata_przechowania", "na_felgach", "felgi")  # migracja 58
    for kolumna in nowe_kolumny:
        assert kolumna in konfig["kolumny"] and kolumna in konfig["dopisane"], kolumna
    stary = {**konfig, "kolumny": [k for k in konfig["kolumny"] if k not in nowe_kolumny], "dopisane": []}

    def wypchnij(auto_id, konfiguracja, chmura):
        sync_konflikty._konflikty_biezacej_synchronizacji.clear()
        return sync_wysylanie._wypchnij_tabele(chmura, "wspolny", auto_id, konfiguracja, db.ROLA_WLASCICIEL)[0]

    a = auto()
    z = komplet(a, "Zimowe")
    chmura = pomoce.ChmuraWPamieci()
    assert wypchnij(a, stary, chmura) == 1
    assert wypchnij(a, konfig, chmura) == 0
    with db.polacz_baze() as conn:
        conn.execute("UPDATE zestawy_opon SET miejsce='Garaż' WHERE id=?", (z,))
    assert wypchnij(a, konfig, chmura) == 1
    (dane,) = chmura.rekordy.values()
    assert (dane["miejsce"], dane["na_felgach"]) == ("Garaż", None)
    assert sync_konflikty._konflikty_biezacej_synchronizacji == []
    # Bez tolerancji pustych dopisanych kolumn ten sam komplet pojechałby od nowa.
    b = auto("Drugie")
    komplet(b, "Letnie")
    chmura = pomoce.ChmuraWPamieci()
    assert wypchnij(b, stary, chmura) == 1
    assert wypchnij(b, {**konfig, "dopisane": []}, chmura) == 1


def test_kosz_kompletu_i_plik_dla_kupujacego(baza):
    p = pomoce.utworz_pojazd("Z oponami")
    a = p["auto_id"]
    # Komplet idzie do kosza z pomiarami i sezonami, „Cofnij” oddaje je z odwołaniami do Serwisu i kosztu.
    wynik = db.usun_z_cofnieciem("zestawy_opon", p["opony"])
    assert db.pobierz_pomiary(a) == [] and db.pobierz_montaze(a) == []
    wynik["cofnij"]()
    (pomiar,) = db.pobierz_pomiary(a)
    (okres,) = db.pobierz_montaze(a)
    assert (pomiar["uwagi"], okres["historia_id"], okres["koszt_id"]) == ("Przed trasą", p["historia"], p["inny_koszt"])

    wynik = db.usun_pomiar_z_cofnieciem(pomiar["id"])
    pozycja = next(x for x in db.pobierz_kosz_wpisow() if x["tabela"] == "pomiary_bieznika")
    import views.kosz_view as kosz_view
    assert kosz_view._opis_wpisu(pozycja, "km") == (ft.Icons.STRAIGHTEN, "Pomiar bieżnika", ["02.02.2026", "6,6 mm"])
    wynik["cofnij"]()

    # Kupujący dostaje pomiary i sezony; koszt zmiany (Inne koszty) zostaje u sprzedającego.
    migawka = db.zrzut_pojazdu(a)
    db_plik._wytnij_sekcje(migawka, db_plik.sekcje_zestawu(db_plik.ZESTAW_DLA_KUPUJACEGO))
    db_plik._uporzadkuj_powiazania(migawka)
    assert len(migawka["tabele"]["pomiary_bieznika"]["wiersze"]) == 1
    (okres,) = migawka["tabele"]["montaze_opon"]["wiersze"]
    assert (okres["historia_id"], okres["koszt_id"]) == (p["historia"], None)


def test_wspolautor_poprawia_tylko_swoje_pomiary(baza):
    a = auto()
    z = komplet(a, "Letnie", True)
    cudzy = pomoce.wstaw("pomiary_bieznika", auto_id=a, zestaw_id=z, data="01.05.2026", lp=7.0, dodane_przez="Kamil")
    db.zapisz_moje_imie("Ania")
    db.ustaw_role_pojazdu(a, db.ROLA_WSPOLAUTOR)
    assert db.zapisz_pomiar(a, z, {"data": "01.05.2026", "lp": 6.0}, cudzy) is None
    assert db.usun_pomiar_z_cofnieciem(cudzy) is None and db.pobierz_pomiar(cudzy)["lp"] == 7.0
    wlasny = db.zapisz_pomiar(a, z, {"data": "01.09.2026", "lp": 6.5})
    assert db.zapisz_pomiar(a, z, {"data": "01.09.2026", "lp": 6.4}, wlasny) == wlasny
    assert db.pobierz_pomiar(wlasny)["dodane_przez"] == "Ania"
    # Komplety to wspólny inwentarz — zmiana opon nie ma autora.
    assert db.zmien_opony(a, komplet(a, "Zimowe"), {"data": "01.10.2026"})["ok"]


def test_wymiana_w_serwisie_zaklada_najgrubszy_komplet_sezonu(baza):
    a, letnie, zimowe = _auto_z_kompletami()
    grubsze = komplet(a, "Zimowe", glebokosc_bieznika=8.0, data_pomiaru="01.04.2026")
    zadanie = podzespol_opon(a)
    h = pomoce.wstaw("historia", zadanie_id=zadanie, data="01.10.2026", przebieg=106000, cena=100, kategoria="Zimowe")
    wynik = db.zamontuj_po_wymianie(a, "Zimowe", "01.10.2026", 106000, h)
    assert (wynik["ok"], wynik["zestaw_id"], wynik["historia_id"], wynik["koszt_id"]) == (True, grubsze, h, None)
    with db.polacz_baze() as conn:
        assert db.flagi_montazu(conn, a) == {grubsze: "Wszystkie"}
        assert conn.execute("SELECT COUNT(*) FROM historia").fetchone()[0] == 1  # wpis już jest — bez drugiego
    assert db.komplet_opon(a, grubsze, DZIS)["otwarty"]["historia_id"] == h
    assert db.zamontuj_po_wymianie(a, "Zimowe", "02.10.2026") is None        # zimowe już są na aucie
    assert db.zamontuj_po_wymianie(a, "Całoroczne", "02.10.2026") is None    # takiego kompletu nie ma


# ============================================================================
#  EKRANY I OKNA
# ============================================================================

@pytest.fixture
def ekran(monkeypatch):
    """Okna, komunikaty i przejścia zbierane zamiast pokazywane (strona testowa ich nie pokaże)."""
    zebrane = SimpleNamespace(okna=[], komunikaty=[], trasy=[])
    monkeypatch.setattr(ft.Page, "show_dialog", lambda self, okno: zebrane.okna.append(okno))
    monkeypatch.setattr(ft.Page, "pop_dialog", lambda self: None)
    podmiany = {"pokaz_komunikat": lambda page, tekst, *a, **k: zebrane.komunikaty.append(tekst),
                "przejdz": lambda page, trasa: zebrane.trasy.append(trasa),
                "wypchnij_w_tle": lambda *a, **k: None}
    for nazwa_modulu, modul in list(sys.modules.items()):
        if modul is not None and nazwa_modulu.split(".")[0] in ("utils", "views"):
            for nazwa, wartosc in podmiany.items():
                if hasattr(modul, nazwa):
                    monkeypatch.setattr(modul, nazwa, wartosc)
    return zebrane


def kontrolki(korzen, typ):
    wynik, kolejka = [], [korzen]
    while kolejka:
        k = kolejka.pop(0)
        if isinstance(k, typ):
            wynik.append(k)
        kolejka.extend(d for _, d in audyty._dzieci(k))
    return wynik


def pola_okna(okno):
    return {p.label: p for p in kontrolki(okno, ft.TextField)}


def bez_usterek_ukladu(widok, strona):
    assert audyty.znajdz_expand_bez_ograniczenia(widok) == []
    assert audyty.znajdz_rozciagliwe_chipy(widok) == []
    assert audyty.znajdz_plaskie_powierzchnie(widok, strona.page) == []


def test_magazyn_karta_na_aucie_i_komplety_w_magazynie(baza, ekran):
    a, letnie, zimowe = _auto_z_kompletami()
    with db.polacz_baze() as conn:
        conn.execute("UPDATE zestawy_opon SET miejsce='Wulkanizacja Kowalski', numer_dot='4221' WHERE id=?", (zimowe,))
        conn.execute("UPDATE samochody SET cisnienie_przod='2,3', cisnienie_tyl='2,1' WHERE id=?", (a,))
    db.zapisz_pomiar(a, letnie, {"data": "01.10.2026", "lp": 2.8})
    strona = pomoce.zbuduj_strone()
    widok = MagazynView(strona.page, pomoce.stan_aplikacji(a, "Astra"))
    teksty = pomoce.napisy(widok)
    assert {"Na aucie: Letnie", "W magazynie (1)", "Zmień na zimowe", "Pomiar", "Ustaw dzień założenia",
            "Ustaw przypomnienie", "Ciśnienie (przód / tył): 2,3 / 2,1",
            "Bieżnik poniżej zalecanych 3 mm — czas na nowe"} <= set(teksty)
    assert any("Wulkanizacja Kowalski" in t for t in teksty)
    bez_usterek_ukladu(widok, strona)


def test_ekran_kompletu_z_pomiarami_i_sezonami(baza, ekran):
    a, letnie, zimowe = _auto_z_kompletami()
    db.ustaw_poczatek_montazu(a, letnie, "01.04.2026", 100000)
    with db.polacz_baze() as conn:
        conn.execute("UPDATE zestawy_opon SET numer_dot='2321', na_felgach=0 WHERE id=?", (letnie,))
    db.zapisz_pomiar(a, letnie, {"data": "01.04.2026", "przebieg": 100000, "lp": 7.0, "pp": 7.0, "lt": 7.4, "pt": 7.4})
    db.zapisz_pomiar(a, letnie, {"data": "01.10.2026", "przebieg": 106000, "lp": 5.8, "pp": 5.9, "lt": 6.9, "pt": 7.0,
                                 "uwagi": "Po wakacjach"})
    strona = pomoce.zbuduj_strone()
    stan = pomoce.stan_aplikacji(a, "Astra")
    widok = KompletOponView(strona.page, stan, letnie)
    teksty = pomoce.napisy(widok)
    assert {"Bieżnik", "Pomiary (2)", "Sezony na aucie", "Przejechane na komplecie", "Felgi", "Same opony, bez felg",
            "Po wakacjach", "od 01.04.2026 · trwa",
            "Przód zużywa się szybciej o 1,1 mm — przy zmianie zamień osie"} <= set(teksty)
    assert any(t.startswith("Do 3 mm ok.") for t in teksty)
    bez_usterek_ukladu(widok, strona)
    assert "Nie ma takiego kompletu" in pomoce.napisy(KompletOponView(strona.page, stan, 9999))


def test_formularz_pomiaru_przepisuje_kola_i_zapisuje(baza, ekran):
    a, letnie, zimowe = _auto_z_kompletami()
    strona = pomoce.zbuduj_strone()
    stan = pomoce.stan_aplikacji(a, "Astra")
    # Po zmianie opon formularz zdejmowanego kompletu dostaje dzień i licznik zmiany.
    stan.pomiar_wstepny = {"data": "01.10.2026", "przebieg": 106000}
    f = FormularzPomiaruView(strona.page, stan, zimowe)
    assert (f.e_data.value, f.e_przebieg.value, stan.pomiar_wstepny) == ("01.10.2026", "106000", None)
    f.e_kola["lp"].value = "3,4"
    f._przepisz("lp")
    assert [p.value for p in f.e_kola.values()] == ["3,4"] * 4
    f.e_kola["pt"].value = "3,8"
    f._przepisz("pt")  # pozostałe koła są już wpisane — nic się nie nadpisuje
    assert f.e_kola["lp"].value == "3,4"
    f.zapisz(None)
    (p,) = db.pobierz_pomiary(a, zimowe)
    assert (p["kola"], p["przebieg"]) == ({"lp": 3.4, "pp": 3.4, "lt": 3.4, "pt": 3.8}, 106000)
    assert ekran.trasy[-1] == f"/magazyn/opony/{zimowe}"
    assert ekran.komunikaty[-1] == "Zapisano pomiar. Uwaga: bieżnik poniżej zalecanych 4 mm — czas na nowe."

    e = FormularzPomiaruView(strona.page, stan, None, p["id"])
    assert (e.e_data.value, e.e_kola["pt"].value) == ("01.10.2026", "3,8")
    e.e_kola["pt"].value = "3,9"
    e.zapisz(None)
    assert db.pobierz_pomiar(p["id"])["pt"] == 3.9 and len(db.pobierz_pomiary(a, zimowe)) == 1


def test_okno_zmiany_zapisuje_i_cofa(baza, ekran):
    a, letnie, zimowe = _auto_z_kompletami()
    zadanie = podzespol_opon(a)
    pomoce.wstaw("historia", zadanie_id=zadanie, data="03.04.2026", przebieg=100100, cena=100, kategoria="Letnie",
                 wykonawca="Wulkanizacja Kowalski")
    strona = pomoce.zbuduj_strone()
    okno = utils.okno_zmiany_opon(strona.page, pomoce.stan_aplikacji(a, "Astra"), zimowe)
    assert ekran.okna == [okno] and okno.title.value == "Zmiana na zimowe"
    pola = pola_okna(okno)
    koszt = pola[f"Koszt ({utils.symbol_waluty()})"]
    # Warsztat i podpowiedź kosztu z ostatniej zmiany w Serwisie.
    assert (pola["Warsztat (opcjonalnie)"].value, koszt.hint_text) == ("Wulkanizacja Kowalski", "ostatnio 100,00")
    pola["Dzień zmiany"].value = "01.10.2026"
    pola[f"Stan licznika ({utils.jednostka_dystansu()})"].value = "106000"
    koszt.value = "120"
    next(b for b in kontrolki(okno, ft.Button) if b.content == "Zapisz").on_click(None)
    with db.polacz_baze() as conn:
        assert db.flagi_montazu(conn, a) == {zimowe: "Wszystkie"}
        assert conn.execute("SELECT cena, wykonawca FROM historia ORDER BY id DESC").fetchone() == \
            (120.0, "Wulkanizacja Kowalski")
    snack = next(k for k in strona.page.overlay if isinstance(k, ft.SnackBar))
    assert snack.content.value == ("Założono opony zimowe — Michelin Alpin 6 205/55 R16 (zdjęto: letnie). "
                                   "Zmiana jest w Serwisie.")
    snack.on_action(None)
    with db.polacz_baze() as conn:
        assert db.flagi_montazu(conn, a) == {letnie: "Wszystkie"}
    assert ekran.komunikaty[-1] == "Cofnięto zmianę opon."


def test_zmieniono_w_przypomnieniu_otwiera_okno_zmiany(baza, ekran):
    a, letnie, zimowe = _auto_z_kompletami()
    db.dodaj_przypomnienie_o_oponach(a, nastepna_data="05.11.2026", kwota=150)
    (wpis,) = db.pobierz_przypomnienia_o_oponach(a)
    strona = pomoce.zbuduj_strone()
    stan = pomoce.stan_aplikacji(a, "Astra")
    assert utils.zmien_opony_z_przypomnienia(strona.page, stan, wpis[0])
    (okno,) = ekran.okna
    assert pola_okna(okno)[f"Koszt ({utils.symbol_waluty()})"].value == "150"
    # Bez kompletu do założenia „Zmieniono” zostaje zwykłym odhaczeniem terminu.
    with db.polacz_baze() as conn:
        conn.execute("DELETE FROM zestawy_opon WHERE id=?", (zimowe,))
    assert not utils.zmien_opony_z_przypomnienia(strona.page, stan, wpis[0])


def test_formularz_nowego_kompletu_z_bieznikiem_montazem_i_przechowalnia(baza, ekran):
    a = auto()
    with db.polacz_baze() as conn:
        conn.execute("UPDATE samochody SET rozmiar_opon='205/55 R16' WHERE id=?", (a,))
    odczyt(a, "01.10.2026", 106000)
    strona = pomoce.zbuduj_strone()
    stan = pomoce.stan_aplikacji(a, "Astra")
    f = FormularzOponyView(strona.page, stan)
    assert f.e_rozmiar.value == "205/55 R16"  # z Karty pojazdu
    f.e_sezon.value, f.e_dot.value, f.e_gl.value = "Zimowe", "4223, 0124", "8,5"
    f.e_zam.value, f.e_od.value = True, "01.10.2026"
    f.e_miejsce.value, f.e_kwit.value = "Garaż", "K-1"
    f.zapisz(None)
    (k,) = db.dane_opon(a)["komplety"]
    assert (k["sezon"], k["zamontowany"], k["bieznik"], k["miejsce"], k["numer_kwitu"], k["na_felgach"]) == \
        ("Zimowe", True, 8.5, "Garaż", "K-1", None)
    assert k["ostatni_pomiar"]["kola"] == {kolo: 8.5 for kolo in db.POZYCJE_KOL}
    assert (k["otwarty"]["data"], k["wiek"]["kodow"]) == ("01.10.2026", 2)
    assert ekran.trasy[-1] == "/magazyn"

    # Edycja wraca na ekran kompletu, nie dotyka pomiarów, a nieruszone „na felgach” zostaje niewiadome.
    e = FormularzOponyView(strona.page, stan, k["id"])
    e.e_felgi.value = "stalowe 16″"
    e.zapisz(None)
    k = db.komplet_opon(a, k["id"])
    assert (k["felgi"], k["na_felgach"], len(k["pomiary"])) == ("stalowe 16″", None, 1)
    assert ekran.trasy[-1] == f"/magazyn/opony/{k['id']}"


def test_wpis_serwisowy_z_wymiana_opon_zaklada_komplet(baza, ekran):
    a, letnie, zimowe = _auto_z_kompletami()
    zadanie = podzespol_opon(a)
    strona = pomoce.zbuduj_strone()
    f = FormularzWpisView(strona.page, pomoce.stan_aplikacji(a, "Astra"), None, zadanie)
    f.e_d.value, f.e_p.value, f.e_kat.value = "01.10.2026", "106000", "Zimowe"
    f.zapisz(None)
    with db.polacz_baze() as conn:
        assert db.flagi_montazu(conn, a) == {zimowe: "Wszystkie"}
        (h,) = conn.execute("SELECT id FROM historia").fetchone()
    assert db.komplet_opon(a, zimowe, DZIS)["otwarty"]["historia_id"] == h
    assert ekran.komunikaty[-1] == "Zapisano wpis! Założono opony zimowe z magazynu."


def test_router_opon(monkeypatch):
    monkeypatch.setattr(ft, "run", lambda *a, **k: None)
    import main

    assert main._cel_trasy(["magazyn", "opony", "5"]) == (False, False, None, None)
    assert main._cel_trasy(["magazyn", "opony", "5", "pomiar"]) == (True, True, None, None)
    assert main._cel_trasy(["magazyn", "opony", "pomiar", "edytuj", "7"]) == (True, False, "pomiary_bieznika", 7)
