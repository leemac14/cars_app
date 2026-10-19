"""Kosz wpisów (Z-01): każde usunięcie z „Cofnij” idzie do kosza i wraca bit w bit — dane,
pliki, stan magazynu i nagrobki; do tego retencja, pojazd w koszu i ekran Kosza."""

import os
from datetime import datetime, timedelta

import flet as ft
import pytest

import audyty
import db
import pomoce
import utils


def stan_bazy(pomijane=pomoce.TABELE_POMIJANE_W_POROWNANIU):
    return pomoce.zrzut_danych(pomijane), pomoce.odciski_zalacznikow()


def pliki_kosza():
    return sorted(os.listdir(db.FOLDER_KOSZ)) if os.path.isdir(db.FOLDER_KOSZ) else []


def sql(zapytanie, parametry=()):
    with db.polacz_baze() as conn:
        return conn.execute(zapytanie, parametry).fetchall()


def pojazd(nazwa="Pierwszy", **opcje):
    """utworz_pojazd z podzespołami przeliczonymi z historii — tak, jak trzyma je aplikacja
    (przywrócenie wpisu serwisowego przelicza je samo)."""
    zid = pomoce.utworz_pojazd(nazwa, **opcje)
    db.przelicz_wszystkie_zadania(zid["auto_id"])
    return zid


# rodzaj → (usunięcie jak w widokach, tabela pozycji kosza)
USUNIECIA = {
    "tankowanie": (lambda z: db.usun_z_cofnieciem("tankowania", z["tankowanie"]), "tankowania"),
    "tankowania_grupowo": (lambda z: db.usun_wiele_z_cofnieciem("tankowania", [z["tankowanie"]]), "tankowania"),
    "inny_koszt": (lambda z: db.usun_z_cofnieciem("inne_koszty", z["inny_koszt"]), "inne_koszty"),
    "wpis_serwisowy": (lambda z: db.usun_z_cofnieciem("historia", z["historia"]), "historia"),
    "podzespol": (lambda z: db.usun_zadanie_z_cofnieciem(z["zadanie"]), "zadania"),
    "wizyta": (lambda z: db.usun_wizyty_z_cofnieciem([z["wizyta"]]), "wizyty"),
    "odczyt": (lambda z: db.usun_z_cofnieciem("odczyty_przebiegu", z["odczyt"]), "odczyty_przebiegu"),
    "przejazd": (lambda z: db.usun_z_cofnieciem("przejazdy", z["przejazd"]), "przejazdy"),
    "dolewka": (lambda z: db.usun_dolewke_z_cofnieciem(z["dolewka"]), "dolewki"),
    "dokument": (lambda z: db.usun_z_cofnieciem("dokumenty_pojazdu", z["dokument"]), "dokumenty_pojazdu"),
    "karoseria": (lambda z: db.usun_z_cofnieciem("zdjecia_karoserii", z["karoseria"]), "zdjecia_karoserii"),
    "do_zrobienia": (lambda z: db.usun_z_cofnieciem("do_zrobienia", z["do_zrobienia"]), "do_zrobienia"),
    "opony": (lambda z: db.usun_z_cofnieciem("zestawy_opon", z["opony"]), "zestawy_opon"),
    "czesc_magazynu": (lambda z: db.usun_czesc_magazynu_z_cofnieciem(z["magazyn"]), "magazyn_czesci"),
    "szkic": (lambda z: db.usun_z_cofnieciem("szkice_wpisow", z["szkic"]), "szkice_wpisow"),
    "warsztat": (lambda z: db.usun_z_cofnieciem("warsztaty", z["warsztat"]), "warsztaty"),
    "cena_czesci": (lambda z: db.usun_z_cofnieciem("ceny_czesci", z["cena_czesci"]), "ceny_czesci"),
}


# ------------------------------------------------------------- round-trip


@pytest.mark.parametrize("sposob", ["z_kosza", "cofnij"])
@pytest.mark.parametrize("rodzaj", sorted(USUNIECIA))
def test_usuniety_wpis_czeka_w_koszu_i_wraca_bit_w_bit(baza, rodzaj, sposob):
    usun, tabela = USUNIECIA[rodzaj]
    zid = pojazd("Pierwszy", wspolny=True)
    przed = stan_bazy()

    wynik = usun(zid)
    assert wynik and wynik["w_koszu"] and wynik["kosz_id"]
    assert stan_bazy() != przed
    (pozycja,) = db.pobierz_kosz_wpisow()
    assert (pozycja["tabela"], pozycja["liczba"], pozycja["auto_id"]) == (tabela, 1, zid["auto_id"])
    wynik["finalizuj"]()  # komunikat zgasł — wpis nadal czeka
    assert db.liczba_wpisow_w_koszu() == 1

    odpowiedz = wynik["cofnij"]() if sposob == "cofnij" else db.przywroc_wpis_z_kosza(pozycja["id"])
    assert odpowiedz and odpowiedz["ok"], odpowiedz
    po = stan_bazy()
    if rodzaj == "czesc_magazynu":
        # Historia cen przeżywa pozycję (db/ceny_czesci.py): jej bieżący zakup zostaje w dzienniku.
        nowe = [w for w in po[0]["ceny_czesci"] if w not in przed[0]["ceny_czesci"]]
        assert [(w[2], w[5]) for w in nowe] == [("Filtr oleju", 19.5)]
        po[0]["ceny_czesci"] = przed[0]["ceny_czesci"]
    assert po == przed
    assert db.liczba_wpisow_w_koszu() == 0 and pliki_kosza() == []
    assert pomoce.klucze_obce_spojne() == []


def test_grupowe_usuniecie_to_jedna_pozycja_przywracana_w_calosci(baza):
    zid = pojazd("Pierwszy")
    pomoce.dosyp_dane(zid["auto_id"])
    ids = [w[0] for w in sql("SELECT id FROM tankowania WHERE auto_id=? ORDER BY id LIMIT 5", (zid["auto_id"],))]
    przed = stan_bazy()

    wynik = db.usun_wiele_z_cofnieciem("tankowania", ids)
    (pozycja,) = db.pobierz_kosz_wpisow()
    assert pozycja["liczba"] == 5 and sorted(w["id"] for w in pozycja["wiersze"]) == sorted(ids)
    assert wynik["pominiete"] == 0

    assert db.przywroc_wpis_z_kosza(pozycja["id"])["ok"]
    assert stan_bazy() == przed


def test_rozliczenie_cofa_sie_bez_kosza(baza):
    zid = pojazd("Pierwszy")
    przed = stan_bazy()

    wynik = db.usun_z_cofnieciem("rozliczenia", zid["rozliczenie"])
    assert wynik and not wynik["w_koszu"] and db.liczba_wpisow_w_koszu() == 0

    assert wynik["cofnij"]()["ok"]
    assert stan_bazy() == przed


# ------------------------------------------------------------- magazyn


def test_zuzyte_czesci_wracaja_na_polke_i_schodza_przy_przywroceniu(baza):
    zid = pojazd("Pierwszy")

    def na_polce():
        return sql("SELECT ilosc FROM magazyn_czesci WHERE id=?", (zid["magazyn"],))[0][0]

    assert na_polce() == 2.0
    wpis = db.usun_z_cofnieciem("historia", zid["historia"])
    assert na_polce() == 3.0, "część z wpisu serwisowego wraca na półkę"
    assert wpis["cofnij"]()["ok"] and na_polce() == 2.0

    wizyta = db.usun_wizyty_z_cofnieciem([zid["wizyta"]])
    assert na_polce() == 4.0, "wizyta oddaje swoje części i części swoich pozycji"
    assert db.przywroc_wpis_z_kosza(wizyta["kosz_id"])["ok"] and na_polce() == 2.0

    with db.polacz_baze() as conn:
        conn.execute("UPDATE dolewki SET ilosc_magazynu=0.5 WHERE id=?", (zid["dolewka"],))
    dolewka = db.usun_dolewke_z_cofnieciem(zid["dolewka"])
    assert na_polce() == 2.5
    assert db.przywroc_wpis_z_kosza(dolewka["kosz_id"])["ok"] and na_polce() == 2.0

    czesc = db.usun_czesc_magazynu_z_cofnieciem(zid["magazyn"])
    assert sql("SELECT COUNT(*) FROM historia_czesci_magazynu")[0][0] == 0
    assert sql("SELECT magazyn_id FROM dolewki WHERE id=?", (zid["dolewka"],))[0][0] is None
    assert db.przywroc_wpis_z_kosza(czesc["kosz_id"])["ok"]
    assert na_polce() == 2.0, "pozycja wraca z ilością sprzed usunięcia, bez potrącania jej zużycia"
    assert sql("SELECT magazyn_id FROM dolewki WHERE id=?", (zid["dolewka"],))[0][0] == zid["magazyn"]


# ------------------------------------------------------------- chmura


def test_niewyslany_nagrobek_znika_a_wysylany_wpis_jedzie_jako_nowy(baza):
    zid = pojazd("Pierwszy", wspolny=True)
    wynik = db.usun_z_cofnieciem("tankowania", zid["tankowanie"])
    assert [n[2] for n in db.pobierz_nagrobki(zid["auto_id"])] == ["tank-1"]

    with db.polacz_baze() as conn:
        conn.execute("DELETE FROM zdalne_nagrobki")  # synchronizacja zdążyła go wysłać
    assert db.przywroc_wpis_z_kosza(wynik["kosz_id"])["ok"]
    assert sql("SELECT zdalne_id, zdalny_hash FROM tankowania WHERE id=?", (zid["tankowanie"],)) == [(None, None)]
    assert db.pobierz_nagrobki(zid["auto_id"]) == []


def test_wpis_ktory_wrocil_z_chmury_nie_dubluje_sie(baza):
    zid = pojazd("Pierwszy", wspolny=True)
    wynik = db.usun_z_cofnieciem("tankowania", zid["tankowanie"])
    with db.polacz_baze() as conn:  # nagrobek odrzucony, pełne pobranie oddało rekord pod nowym id
        conn.execute("INSERT INTO tankowania (auto_id, data, przebieg, litry, kwota, zdalne_id) VALUES (?,?,?,?,?,?)",
                     (zid["auto_id"], "2026-02-01", 100500, 32.5, 210.0, "tank-1"))
    assert db.przywroc_wpis_z_kosza(wynik["kosz_id"])["ok"]
    (wiersz,) = sql("SELECT id FROM tankowania WHERE zdalne_id='tank-1'")
    assert pomoce.pliki_wpisu("tankowania", wiersz[0]), "paragon wraca przy wpisie, który już jest"


def test_przy_podgladzie_wpisu_nie_da_sie_przywrocic(baza):
    zid = pojazd("Pierwszy", wspolny=True)
    wynik = db.usun_z_cofnieciem("tankowania", zid["tankowanie"])
    db.ustaw_role_pojazdu(zid["auto_id"], db.ROLA_PODGLAD)  # właściciel zabrał prawa

    odmowa = db.przywroc_wpis_z_kosza(wynik["kosz_id"])
    assert odmowa["ok"] is False and "podgląd" in odmowa["powod"]
    assert db.liczba_wpisow_w_koszu() == 1
    assert db.usun_z_cofnieciem("tankowania", zid["tankowanie"]) is None, "podgląd niczego nie usuwa"


# ------------------------------------------------------------- klucze


def test_zajete_id_przemapowuje_historie_czesci_pliki_i_dowiazania(baza):
    zid = pojazd("Pierwszy")
    wynik = db.usun_zadanie_z_cofnieciem(zid["zadanie"])
    with db.polacz_baze() as conn:  # ktoś zajął id podzespołu i wpisu (np. wczytana kopia)
        conn.execute("INSERT INTO zadania (id, auto_id, nazwa) VALUES (?,?,?)",
                     (zid["zadanie"], zid["auto_id"], "Nowy podzespół"))
        conn.execute("INSERT INTO historia (id, zadanie_id, data, przebieg, kategoria, cena) VALUES (?,?,?,?,?,?)",
                     (zid["historia"], zid["zadanie"], "2026-03-01", 101500, "Serwis", 50.0))

    assert db.przywroc_wpis_z_kosza(wynik["kosz_id"])["ok"]
    (zadanie,) = sql("SELECT id FROM zadania WHERE nazwa='Olej silnikowy i filtr'")
    (wpis,) = sql("SELECT id, zadanie_id FROM historia WHERE notatka='Olej Castrol'")
    assert zadanie[0] != zid["zadanie"] and wpis[0] != zid["historia"] and wpis[1] == zadanie[0]
    assert sql("SELECT historia_id FROM historia_czesci_magazynu") == [(wpis[0],)]
    assert sql("SELECT zadanie_id FROM do_zrobienia WHERE id=?", (zid["do_zrobienia"],)) == [(zadanie[0],)]
    ((sciezka, _, _),) = pomoce.pliki_wpisu("historia", wpis[0])
    assert os.path.exists(db.pelna_sciezka_zalacznika(sciezka))
    assert pomoce.klucze_obce_spojne() == []


def test_wpis_bez_podzespolu_czeka_az_wroci_podzespol(baza):
    zid = pojazd("Pierwszy")
    przed = stan_bazy()
    wpis = db.usun_z_cofnieciem("historia", zid["historia"])
    podzespol = db.usun_zadanie_z_cofnieciem(zid["zadanie"])
    pliki = pliki_kosza()

    odmowa = db.przywroc_wpis_z_kosza(wpis["kosz_id"])
    assert odmowa["ok"] is False and "Podzespołu" in odmowa["powod"]
    assert db.liczba_wpisow_w_koszu() == 2 and pliki_kosza() == pliki, "odmowa niczego nie rusza"

    assert db.przywroc_wpis_z_kosza(podzespol["kosz_id"])["ok"]
    assert db.przywroc_wpis_z_kosza(wpis["kosz_id"])["ok"]
    assert stan_bazy() == przed


# ------------------------------------------------------------- pliki


def test_plik_wskazywany_przez_inny_wpis_zostaje_na_miejscu(baza):
    zid = pojazd("Pierwszy")
    ((sciezka, _, _),) = pomoce.pliki_wpisu("tankowania", zid["tankowanie"])
    with db.polacz_baze() as conn:
        conn.execute("UPDATE zdjecia_karoserii SET zalacznik=? WHERE id=?", (sciezka, zid["karoseria"]))

    wynik = db.usun_z_cofnieciem("tankowania", zid["tankowanie"])
    assert os.path.exists(db.pelna_sciezka_zalacznika(sciezka)), "zdjęcie karoserii dalej go pokazuje"
    assert len(pliki_kosza()) == 1, "do kosza idzie kopia"
    assert db.usun_wpis_z_kosza_trwale(wynik["kosz_id"])
    assert os.path.exists(db.pelna_sciezka_zalacznika(sciezka)) and pliki_kosza() == []


def test_sprzatanie_startowe_zostawia_pliki_kosza_wpisow(baza):
    zid = pojazd("Pierwszy")
    wynik = db.usun_z_cofnieciem("tankowania", zid["tankowanie"])
    pliki = pliki_kosza()
    assert pliki

    db.porzadki_startowe()
    assert pliki_kosza() == pliki and db.liczba_wpisow_w_koszu() == 1
    assert db.przywroc_wpis_z_kosza(wynik["kosz_id"])["ok"]
    ((sciezka, _, _),) = pomoce.pliki_wpisu("tankowania", zid["tankowanie"])
    assert os.path.exists(db.pelna_sciezka_zalacznika(sciezka))


def _postarz(kosz_id, dni):
    data = (datetime.now() - timedelta(days=dni)).strftime("%Y-%m-%d %H:%M:%S")
    with db.polacz_baze() as conn:
        conn.execute("UPDATE kosz_wpisy SET data_usuniecia=? WHERE id=?", (data, kosz_id))


def test_retencja_kasuje_stare_wpisy_razem_z_plikami(baza):
    zid = pojazd("Pierwszy")
    stary = db.usun_z_cofnieciem("tankowania", zid["tankowanie"])
    swiezy = db.usun_z_cofnieciem("inne_koszty", zid["inny_koszt"])
    _postarz(stary["kosz_id"], 31)
    (pozycja,) = [p for p in db.pobierz_kosz_wpisow() if p["id"] == stary["kosz_id"]]
    assert pozycja["dni_do_usuniecia"] == 0

    assert db.posprzataj_kosz() == 1
    assert [p["id"] for p in db.pobierz_kosz_wpisow()] == [swiezy["kosz_id"]]
    assert pliki_kosza() == []

    db.zapisz_dni_kosza(0)
    _postarz(swiezy["kosz_id"], 400)
    assert db.posprzataj_kosz() == 0 and db.liczba_wpisow_w_koszu() == 1


def test_oproznienie_kasuje_wpisy_ale_nie_te_czekajace_z_pojazdem(baza):
    pierwszy = pomoce.utworz_pojazd("Pierwszy")
    drugi = pomoce.utworz_pojazd("Drugi")
    db.usun_z_cofnieciem("tankowania", pierwszy["tankowanie"])
    db.usun_z_cofnieciem("tankowania", drugi["tankowanie"])
    db.usun_auto_do_kosza(drugi["auto_id"])

    assert db.oproznij_kosz_wpisow() == 1
    assert sql("SELECT COUNT(*) FROM kosz_wpisy WHERE kosz_pojazdu_id IS NOT NULL") == [(1,)]


# ------------------------------------------------------------- pojazd w koszu


def test_wpisy_czekaja_z_usunietym_pojazdem_i_wracaja_razem_z_nim(baza):
    zid = pojazd("Pierwszy")
    bez_wyciszen = pomoce.TABELE_POMIJANE_W_POROWNANIU | {"wyciszone_powiadomienia"}  # jak w test_kosz.py
    przed = stan_bazy(bez_wyciszen)
    wpis = db.usun_z_cofnieciem("tankowania", zid["tankowanie"])
    auto = db.usun_auto_do_kosza(zid["auto_id"])

    assert db.pobierz_kosz_wpisow() == [] and db.liczba_wpisow_w_koszu() == 0
    assert "Pojazd" in db.przywroc_wpis_z_kosza(wpis["kosz_id"])["powod"]

    assert db.przywroc_auto_z_kosza(auto["kosz_id"]) == zid["auto_id"]
    (pozycja,) = db.pobierz_kosz_wpisow()
    assert pozycja["auto_id"] == zid["auto_id"]
    assert db.przywroc_wpis_z_kosza(wpis["kosz_id"])["ok"]
    assert stan_bazy(bez_wyciszen) == przed


def test_nowe_auto_pod_starym_id_nie_przejmuje_wpisow_z_kosza(baza):
    zid = pojazd("Pierwszy")
    wpis = db.usun_z_cofnieciem("tankowania", zid["tankowanie"])
    auto = db.usun_auto_do_kosza(zid["auto_id"])
    with db.polacz_baze() as conn:
        conn.execute("INSERT INTO samochody (id, nazwa, typ_paliwa, status, rola_wspoldzielenia) VALUES (?,?,?,?,?)",
                     (zid["auto_id"], "Nowy", "Benzyna", db.STATUS_POJAZDU_AKTYWNY, db.ROLA_WLASCICIEL))
    assert db.pobierz_kosz_wpisow() == []

    nowe_id = db.przywroc_auto_z_kosza(auto["kosz_id"])
    assert nowe_id != zid["auto_id"]
    assert db.przywroc_wpis_z_kosza(wpis["kosz_id"])["ok"]
    assert sql("SELECT auto_id FROM tankowania WHERE stacja='Orlen'") == [(nowe_id,)]
    assert pomoce.klucze_obce_spojne() == []


def test_trwale_usuniecie_pojazdu_zabiera_jego_wpisy_z_kosza(baza):
    zid = pojazd("Pierwszy")
    db.usun_z_cofnieciem("tankowania", zid["tankowanie"])
    auto = db.usun_auto_do_kosza(zid["auto_id"])

    db.usun_z_kosza_trwale(auto["kosz_id"])
    assert sql("SELECT COUNT(*) FROM kosz_wpisy") == [(0,)]
    assert pliki_kosza() == []


# ------------------------------------------------------------- lista


def test_lista_kosza_opisuje_wpis_i_to_co_zabral(baza):
    zid = pojazd("Pierwszy")
    db.usun_wizyty_z_cofnieciem([zid["wizyta"]])
    db.usun_z_cofnieciem("tankowania", zid["tankowanie"])
    pomoce.utworz_pojazd("Drugi")
    wpis = db.usun_z_cofnieciem("historia", sql("SELECT id FROM historia WHERE notatka='Olej Castrol' "
                                                 "AND zadanie_id IN (SELECT id FROM zadania WHERE auto_id=2)")[0][0])

    tankowanie, wizyta = [p for p in db.pobierz_kosz_wpisow() if p["auto_id"] == zid["auto_id"]]
    assert tankowanie["tabela"] == "tankowania" and tankowanie["liczba_plikow"] == 1
    assert wizyta["zalezne"] == {"historia": 1, "wizyta_czesci_magazynu": 1, "historia_czesci_magazynu": 1}
    assert wizyta["liczba_plikow"] == 3 and wizyta["nazwa_auta"] == "Pierwszy"
    assert wizyta["dni_do_usuniecia"] == db.DNI_KOSZA_DOMYSLNIE
    (serwis,) = [p for p in db.pobierz_kosz_wpisow() if p["id"] == wpis["kosz_id"]]
    assert serwis["opis"] == "Olej silnikowy i filtr" and serwis["nazwa_auta"] == "Drugi"


# ------------------------------------------------------------- ekran i komunikat


def _widok_kosza(stan):
    strona = pomoce.zbuduj_strone()
    return strona, pomoce.zbuduj_widok(pomoce.klasy_widokow()["KoszView"], strona, stan)


def _usun_po_trochu(zid):
    for rodzaj in ("tankowanie", "wpis_serwisowy", "inny_koszt", "odczyt", "dokument", "karoseria", "szkic"):
        USUNIECIA[rodzaj][0](zid)
    db.usun_wiele_z_cofnieciem("przejazdy", [zid["przejazd"]])
    db.usun_wizyty_z_cofnieciem([zid["wizyta"]])


def test_ekran_kosza_pokazuje_wpisy_i_pojazdy_w_zakladkach(baza):
    stan, zid = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    _usun_po_trochu(zid)
    db.usun_auto_do_kosza(pomoce.utworz_pojazd("Drugi")["auto_id"])

    strona, widok = _widok_kosza(stan)
    napisy = pomoce.napisy(widok)
    assert "Wpisy (9)" in napisy and "Pojazdy (1)" in napisy
    assert "Tankowanie · Orlen" in napisy and "Olej silnikowy i filtr" in napisy
    assert "Wizyta · Warsztat u Janka" in napisy and "Drugi" not in napisy
    _audyty(widok)

    stan.kosz_zakladka = 1
    strona, widok = _widok_kosza(stan)
    assert "Drugi" in pomoce.napisy(widok) and "Tankowanie · Orlen" not in pomoce.napisy(widok)
    _audyty(widok)


def _audyty(widok):
    for znajdz in (audyty.znajdz_expand_bez_ograniczenia, audyty.znajdz_expand_w_kontenerze,
                   audyty.znajdz_rozciagliwe_chipy, audyty.znajdz_uciete_napisy,
                   audyty.znajdz_pogrubienia_na_drugim_planie):
        assert znajdz(widok) == [], znajdz.__name__
    assert pomoce.bledy_kontrolek(widok) == []


def test_pusty_kosz_otwiera_sie_na_zakladce_z_pojazdami_gdy_tylko_one_sa(baza):
    stan, _ = pomoce.przygotuj_scenariusz("kosz_pelny")
    _strona, widok = _widok_kosza(stan)
    assert stan.kosz_zakladka == 1 and "Do kosza" in pomoce.napisy(widok)


def test_przywrocenie_z_ekranu_mowi_co_wrocilo_albo_dlaczego_nie(baza, monkeypatch):
    stan, zid = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    wpis = db.usun_z_cofnieciem("historia", zid["historia"])
    db.usun_z_cofnieciem("tankowania", zid["tankowanie"])
    db.usun_zadanie_z_cofnieciem(zid["zadanie"])
    komunikaty = []
    monkeypatch.setattr(utils, "przejdz", lambda page, trasa: None)
    monkeypatch.setattr(utils, "pokaz_komunikat", lambda page, tekst, kolor=None: komunikaty.append(tekst))

    _strona, widok = _widok_kosza(stan)
    pozycje = {p["tabela"]: p for p in widok.wpisy}
    widok._przywroc_wpis(pozycje["historia"])
    assert "Podzespołu" in komunikaty[-1] and db.liczba_wpisow_w_koszu() == 3

    widok._przywroc_wpis(pozycje["tankowania"])
    assert komunikaty[-1] == "Przywrócono: Tankowanie · Orlen." and db.liczba_wpisow_w_koszu() == 2
    assert sql("SELECT COUNT(*) FROM kosz_wpisy WHERE id=?", (wpis["kosz_id"],)) == [(1,)]


def test_komunikat_po_usunieciu_mowi_o_koszu_a_nieudane_cofniecie_o_powodzie(baza, monkeypatch):
    strona = pomoce.zbuduj_strone()
    page = strona.page
    monkeypatch.setattr(type(page), "run_task", lambda self, f, *a, **k: None)
    pokazane = []
    monkeypatch.setattr(utils.dialogi, "przejdz", lambda p, trasa: None)
    monkeypatch.setattr(utils.dialogi, "pokaz_komunikat", lambda p, tekst, kolor=None: pokazane.append(tekst))

    otwarte = []
    if hasattr(page, "open"):
        monkeypatch.setattr(type(page), "open", lambda self, kontrolka: otwarte.append(kontrolka))

    wynik = {"cofnij": lambda: {"ok": False, "powod": "Pojazd tego wpisu jest w koszu."},
             "finalizuj": lambda: None, "w_koszu": True, "dni_kosza": 30}
    utils.pokaz_komunikat_cofnij(page, "Usunięto tankowanie.", wynik)
    snack = (otwarte or [k for k in page.overlay if isinstance(k, ft.SnackBar)])[-1]
    assert snack.content.value == "Usunięto tankowanie. W koszu przez 30 dni."

    snack.on_action(None)
    assert pokazane == ["Pojazd tego wpisu jest w koszu."]
