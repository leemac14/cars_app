"""Kolejka „do wpisania” (M-08): zdjęcie paragonu teraz, wpis wieczorem.

Szkic to zdjęcie z datą — i opcjonalnie rodzajem, licznikiem i opisem dopisanymi
po migawce — w osobnej, lokalnej tabeli `szkice_wpisow`. Formularz tankowania,
kosztu albo wizyty otwarty ze szkicu dostaje datę, zdjęcie jako załącznik (ten
sam plik, bez kopii), licznik i opis, a przy zapisie zamyka szkic w tej samej
transakcji. Kokpit pokazuje baner „3 paragony do wpisania”, szuflada — odznakę,
dzwonek — przypomnienie, gdy najstarszy leży trzy dni.

Tu: warstwa danych (zdjęcie z bajtów i z galerii z datą EXIF, kolejność, podsumowanie,
zamknięcie kontra usunięcie z cofnięciem, przeniesienie), trzy formularze ze szkicu,
baner, odznaka, dzwonek, ekran kolejki, ekran aparatu (z podstawionym aparatem)
i trasy. Kosz, schemat i migracje sprawdzają test_kosz / test_schemat / test_migracje
(szkic jest w `pomoce.utworz_pojazd`).
"""

import asyncio
import io
import os
from datetime import datetime, timedelta

import flet as ft
import pytest
from PIL import Image

import audyty
import db
import pomoce
import sync
import utils
from date import na_iso


# ---------------------------------------------------------------- pomocnicy

def _jpeg(kiedy=None, kolor=(200, 180, 160)):
    """Bajty małego JPEG-a, opcjonalnie z datą zdjęcia w EXIF."""
    obraz = Image.new("RGB", (40, 30), kolor)
    exif = obraz.getexif()
    if kiedy:
        exif.get_ifd(0x8769)[0x9003] = kiedy.strftime("%Y:%m:%d %H:%M:%S")
    bufor = io.BytesIO()
    obraz.save(bufor, "JPEG", exif=exif)
    return bufor.getvalue()


def _plik(tmp_path, nazwa, dane):
    sciezka = tmp_path / nazwa
    sciezka.write_bytes(dane)
    return str(sciezka)


def _auto(nazwa="Szkicowy", typ="Benzyna"):
    with db.polacz_baze() as conn:
        return conn.execute(
            "INSERT INTO samochody (nazwa, marka, model, typ_paliwa, status) VALUES (?,?,?,?,?)",
            (nazwa, "Marka", "Model", typ, db.STATUS_POJAZDU_AKTYWNY),
        ).lastrowid


def _szkic_z_pliku(auto_id, dni_temu=0, **dodatki):
    sciezka = os.path.join(db.FOLDER_ODROCZONE, f"test_{auto_id}_{dni_temu}_{len(dodatki)}.jpg")
    with open(sciezka, "wb") as plik:
        plik.write(_jpeg())
    kiedy = datetime.now().replace(hour=15, minute=40, second=0, microsecond=0) - timedelta(days=dni_temu)
    return db.dodaj_szkic(auto_id, sciezka, kiedy=kiedy, **dodatki)


def _wiersz(sql, parametry=()):
    with db.polacz_baze() as conn:
        return conn.execute(sql, parametry).fetchone()


def _teksty(korzen):
    wynik, do_odwiedzenia = [], [korzen]
    while do_odwiedzenia:
        kontrolka = do_odwiedzenia.pop()
        for pole in ("value", "label", "tooltip"):
            wartosc = getattr(kontrolka, pole, None)
            if isinstance(wartosc, str):
                wynik.append(wartosc)
        for pole in ("controls", "content", "title", "subtitle", "leading", "trailing", "actions",
                     "appbar", "floating_action_button"):
            dziecko = getattr(kontrolka, pole, None)
            if isinstance(dziecko, (list, tuple)):
                do_odwiedzenia.extend(d for d in dziecko if isinstance(d, ft.Control))
            elif isinstance(dziecko, ft.Control):
                do_odwiedzenia.append(dziecko)
    return wynik


def _kontrolki(korzen, typ):
    wynik, do_odwiedzenia = [], [korzen]
    while do_odwiedzenia:
        kontrolka = do_odwiedzenia.pop()
        if isinstance(kontrolka, typ):
            wynik.append(kontrolka)
        for pole in ("controls", "content", "appbar", "floating_action_button"):
            dziecko = getattr(kontrolka, pole, None)
            if isinstance(dziecko, (list, tuple)):
                do_odwiedzenia.extend(d for d in dziecko if isinstance(d, ft.Control))
            elif isinstance(dziecko, ft.Control):
                do_odwiedzenia.append(dziecko)
    return wynik


def _formularz(klasa, auto_id, szkic_id):
    strona = pomoce.zbuduj_strone()
    trasy = []
    strona.page.on_route_change = lambda e: trasy.append(strona.page.route)
    widok = klasa(strona.page, pomoce.stan_aplikacji(auto_id, "Szkicowy"), None, szkic_id=szkic_id)
    widok._strona_testowa = strona
    return widok, trasy


# ======================================================= warstwa danych

def test_migawka_z_bajtow_zapisuje_zdjecie_z_dzisiejsza_data(baza):
    auto_id = _auto()
    przed = datetime.now()

    szkic_id = db.dodaj_szkic_z_bajtow(auto_id, _jpeg())
    szkic = db.pobierz_szkic(szkic_id)

    assert szkic["data"] == przed.strftime("%d.%m.%Y")
    assert szkic["data_iso"] == przed.strftime("%Y-%m-%d")
    assert szkic["godzina"] and szkic["dni"] == 0
    assert szkic["zalacznik"].startswith("zalaczniki/"), "do bazy idzie ścieżka względna"
    assert os.path.exists(db.sciezka_pliku_zalacznika(szkic["zalacznik"]))
    assert [n for n in os.listdir(db.FOLDER_ODROCZONE) if n.startswith("migawka_")] == [], \
        "plik pośredni z aparatu nie może zostać w folderze odroczonych"


def test_zdjecie_z_galerii_bierze_date_z_exif_a_bez_niej_dzisiejsza(baza, tmp_path):
    auto_id = _auto()
    dawno = datetime(2026, 9, 27, 14, 32, 5)
    z_exif = _plik(tmp_path, "paragon.jpg", _jpeg(dawno))
    bez_exif = _plik(tmp_path, "zrzut.jpg", _jpeg())
    z_przyszlosci = _plik(tmp_path, "zegar.jpg", _jpeg(datetime.now() + timedelta(days=40)))
    zepsuty = _plik(tmp_path, "nie_obraz.jpg", b"to nie jest zdjecie")

    assert db.czas_zdjecia(z_exif) == dawno
    assert db.czas_zdjecia(bez_exif) is None
    assert db.czas_zdjecia(z_przyszlosci) is None, "zegar aparatu w przyszłości — lepiej dziś"
    assert db.czas_zdjecia(zepsuty) is None

    dodane = db.dodaj_szkice_z_plikow(auto_id, [z_exif, bez_exif, str(tmp_path / "brak.jpg")])

    assert dodane == 2
    daty = {(s["data"], s["godzina"]) for s in db.pobierz_szkice(auto_id)}
    assert ("27.09.2026", "14:32") in daty
    assert any(d == datetime.now().strftime("%d.%m.%Y") for d, _ in daty)


def test_kolejka_idzie_od_najstarszego_a_podsumowanie_liczy_wiek(baza):
    auto_id = _auto()
    swiezy = _szkic_z_pliku(auto_id, 0)
    stary = _szkic_z_pliku(auto_id, 5)
    sredni = _szkic_z_pliku(auto_id, 2)

    assert [s["id"] for s in db.pobierz_szkice(auto_id)] == [stary, sredni, swiezy]
    stan = db.podsumowanie_szkicow(auto_id)
    assert stan["liczba"] == 3 and stan["najstarszy_id"] == stary and stan["dni"] == 5
    assert stan["najstarszy_data"] == db.pobierz_szkic(stary)["data"]

    # Pamięć metryk: nowy szkic (zapis przez polacz_baze) unieważnia podsumowanie.
    _szkic_z_pliku(auto_id, 1)
    assert db.podsumowanie_szkicow(auto_id)["liczba"] == 4
    assert db.podsumowanie_szkicow(None)["liczba"] == 0


def test_opis_szkicu_normalizuje_rodzaj_licznik_i_opis(baza):
    auto_id = _auto()
    szkic_id = db.dodaj_szkic_z_bajtow(auto_id, _jpeg())

    assert db.opisz_szkic(szkic_id, "tankowanie", "101450", "  Orlen   przy  A2 ")
    szkic = db.pobierz_szkic(szkic_id)
    assert (szkic["rodzaj"], szkic["przebieg"], szkic["opis"]) == ("tankowanie", 101450, "Orlen przy A2")

    db.opisz_szkic(szkic_id, "cokolwiek", "0", "x" * 500)
    szkic = db.pobierz_szkic(szkic_id)
    assert szkic["rodzaj"] is None and szkic["przebieg"] is None
    assert len(szkic["opis"]) == db.MAKS_DLUGOSC_OPISU_SZKICU

    db.opisz_szkic(szkic_id, None, None, "")
    assert db.pobierz_szkic(szkic_id)["opis"] is None


def test_zamkniecie_szkicu_zostawia_zdjecie_a_usuniecie_je_zabiera_z_cofnieciem(baza):
    auto_id = _auto()
    wpisany = db.pobierz_szkic(db.dodaj_szkic_z_bajtow(auto_id, _jpeg()))
    odrzucony = db.pobierz_szkic(db.dodaj_szkic_z_bajtow(auto_id, _jpeg(kolor=(10, 20, 30))))

    db.zamknij_szkic(wpisany["id"])
    assert db.pobierz_szkic(wpisany["id"]) is None
    assert os.path.exists(db.sciezka_pliku_zalacznika(wpisany["zalacznik"])), "zdjęcie należy już do wpisu"

    plik = db.sciezka_pliku_zalacznika(odrzucony["zalacznik"])
    wynik = db.usun_z_cofnieciem(db.TABELA_SZKICOW, odrzucony["id"])
    assert db.pobierz_szkic(odrzucony["id"]) is None and not os.path.exists(plik)

    wynik["cofnij"]()
    # Cofnięcie wstawia wiersz od nowa (nowe id) — z tą samą datą i tym samym zdjęciem.
    przywrocone = [s for s in db.pobierz_szkice(auto_id) if s["zalacznik"] == odrzucony["zalacznik"]]
    assert len(przywrocone) == 1 and przywrocone[0]["data_iso"] == odrzucony["data_iso"]
    assert os.path.exists(plik)


def test_szkic_przenosi_sie_do_innego_pojazdu(baza):
    pierwszy, drugi = _auto("Pierwszy"), _auto("Drugi")
    szkic_id = db.dodaj_szkic_z_bajtow(pierwszy, _jpeg())

    assert db.przenies_szkic(szkic_id, drugi)
    assert db.podsumowanie_szkicow(pierwszy)["liczba"] == 0
    assert db.podsumowanie_szkicow(drugi)["liczba"] == 1
    assert not db.przenies_szkic(szkic_id, None)


def test_szkice_sa_lokalne_a_kosz_i_zalaczniki_je_znaja():
    """Zdjęcia nie jadą do chmury (N-06), więc szkic u drugiej osoby byłby
    odsyłaczem do pliku, którego ona nie ma. Kosz pojazdu i naprawa ścieżek
    załączników muszą za to o nim wiedzieć."""
    assert db.TABELA_SZKICOW not in [k["tabela"] for k in sync.KONFIGURACJA_SYNC]
    assert db.TABELA_SZKICOW in db.KOSZ_TABELE_POTOMNE
    assert (db.TABELA_SZKICOW, "zalacznik") in db.KOLUMNY_ZE_SCIEZKAMI
    assert db.TABELA_SZKICOW in db.TABELE_Z_DATA_ISO


def test_kosz_pojazdu_zabiera_i_oddaje_szkic_ze_zdjeciem(baza):
    identyfikatory = pomoce.utworz_pojazd("Koszowy")
    auto_id = identyfikatory["auto_id"]
    szkic = db.pobierz_szkic(identyfikatory["szkic"])
    plik = db.sciezka_pliku_zalacznika(szkic["zalacznik"])

    db.usun_auto_do_kosza(auto_id)
    assert _wiersz("SELECT COUNT(*) FROM szkice_wpisow")[0] == 0
    assert not os.path.exists(plik)

    db.przywroc_auto_z_kosza(db.pobierz_kosz()[0]["id"])
    wrocil = db.pobierz_szkice(auto_id)
    assert [(s["data"], s["rodzaj"], s["przebieg"], s["opis"]) for s in wrocil] == \
        [(szkic["data"], "tankowanie", 101400, "Orlen przy A2")]
    assert os.path.exists(db.sciezka_pliku_zalacznika(wrocil[0]["zalacznik"]))


# ============================================ odznaka, dzwonek, porównanie

def test_odznaka_w_szufladzie_liczy_szkice(baza):
    auto_id = _auto()
    assert "do-wpisania" not in db.liczniki_nawigacji(auto_id)

    for _ in range(3):
        db.dodaj_szkic_z_bajtow(auto_id, _jpeg())

    assert db.liczniki_nawigacji(auto_id)["do-wpisania"] == 3
    assert utils.EKRANY_WG_ID["do-wpisania"]["trasa"] == "/do-wpisania"


def test_dzwonek_odzywa_sie_dopiero_po_trzech_dniach_najstarszego(baza):
    auto_id = _auto()
    _szkic_z_pliku(auto_id, 1)
    assert not [p for p in db.pobierz_powiadomienia(auto_id) if p["typ"] == "szkice"]

    stary = _szkic_z_pliku(auto_id, db.DNI_PRZYPOMNIENIA_SZKICU + 1)
    przypomnienia = [p for p in db.pobierz_powiadomienia(auto_id) if p["typ"] == "szkice"]

    assert len(przypomnienia) == 1
    p = przypomnienia[0]
    assert p["klucz"] == f"szkice:{stary}" and p["trasa"] == "/do-wpisania" and p["status"] == "pilne"
    assert p["opis"] == "2 paragony w kolejce, najstarszy sprzed 4 dni"

    # Drzemka trzyma się najstarszego szkicu.
    db.odloz_powiadomienie(auto_id, p["klucz"], 3, p["tytul"])
    assert not [p for p in db.pobierz_powiadomienia(auto_id) if p["typ"] == "szkice"]


def test_porownanie_pojazdow_nie_liczy_paragonow_jako_terminu(baza):
    auto_id = _auto()
    przed = db.pobierz_dane_do_porownania(auto_id)["pilne"]
    _szkic_z_pliku(auto_id, 10)

    assert any(p["typ"] == "szkice" for p in db.pobierz_powiadomienia(auto_id))
    assert db.pobierz_dane_do_porownania(auto_id)["pilne"] == przed


# ======================================================= kokpit

@pytest.mark.parametrize("ile, napis", [(1, "1 paragon do wpisania"), (3, "3 paragony do wpisania"),
                                        (5, "5 paragonów do wpisania")])
def test_baner_na_kokpicie_mowi_ile_paragonow_czeka(baza, ile, napis):
    stan = pomoce.stan_aplikacji(_auto(), "Szkicowy")
    stan.zakladka = 0
    for _ in range(ile):
        db.dodaj_szkic_z_bajtow(stan.auto_id, _jpeg())

    strona = pomoce.zbuduj_strone()
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], strona, stan)

    assert napis in _teksty(widok)


def test_kokpit_bez_szkicow_nie_ma_baneru_a_ma_kafel_paragonu(baza):
    stan = pomoce.stan_aplikacji(_auto(), "Szkicowy")
    stan.zakladka = 0
    db.zapisz_widgety_kokpitu(["akcja_paragon"], stan.auto_id)

    strona = pomoce.zbuduj_strone()
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], strona, stan)
    teksty = _teksty(widok)

    assert not any("do wpisania" in t for t in teksty)
    assert "Paragon" in teksty and "akcja_paragon" in db.KOKPIT_WIDGETY_DOMYSLNE
    assert "Paragon na później" in teksty, "pozycja w FAB-ie szybkiego dodawania"


# ======================================================= formularze

def test_tankowanie_ze_szkicu_bierze_date_zdjecie_licznik_i_opis(baza):
    auto_id = _auto()
    for dni_temu, przebieg in ((20, 101000), (1, 101900)):
        # Drugie tankowanie jest PÓŹNIEJSZE od paragonu, a wpisane przed nim —
        # nie może udawać „poprzedniego licznika”.
        data = (datetime.now() - timedelta(days=dni_temu)).strftime("%d.%m.%Y")
        with db.polacz_baze() as conn:
            conn.execute("INSERT INTO tankowania (auto_id, data, data_iso, przebieg, litry, kwota, do_pelna) "
                         "VALUES (?,?,?,?,?,?,?)", (auto_id, data, na_iso(data), przebieg, 40, 260, 1))
    szkic_id = _szkic_z_pliku(auto_id, 3, rodzaj="tankowanie", przebieg=101450, opis="Orlen przy A2")
    drugi = _szkic_z_pliku(auto_id, 1)
    szkic = db.pobierz_szkic(szkic_id)

    from views.formularze import FormularzTankowanieView
    widok, trasy = _formularz(FormularzTankowanieView, auto_id, szkic_id)

    assert widok.route == f"/tankowanie/nowe/szkic/{szkic_id}"
    assert widok.e_d.value == szkic["data"]
    assert widok.e_p.value == "101450" and widok.e_dys.value == "450"
    assert [p["sciezka"] for p in widok.pliki.pozycje] == [szkic["zalacznik"]]
    assert widok.k_notatka.value == "Orlen przy A2"
    assert "Paragon z " + szkic["data"] + ", 15:40" in _teksty(widok)

    widok.e_l.value, widok.e_k.value = "30", "195"
    widok.zapisz(None)

    wpis = _wiersz("SELECT id, przebieg, dystans, data FROM tankowania WHERE auto_id=? AND przebieg=?",
                   (auto_id, 101450))
    assert wpis[1:] == (101450, 450.0, szkic["data"])
    assert pomoce.pliki_wpisu("tankowania", wpis[0]) == [(szkic["zalacznik"], "paragon", None)], \
        "zdjęcie szkicu to pierwszy plik wpisu — bez kopiowania"
    assert db.pobierz_szkic(szkic_id) is None
    assert os.path.exists(db.sciezka_pliku_zalacznika(szkic["zalacznik"]))
    assert trasy[-1] == "/do-wpisania", "w kolejce czeka jeszcze jeden paragon"
    assert db.pobierz_szkic(drugi) is not None


def test_koszt_ze_szkicu_ma_opis_jako_nazwe_i_ostatni_wraca_na_kokpit(baza):
    auto_id = _auto()
    szkic_id = _szkic_z_pliku(auto_id, 2, rodzaj="koszt", opis="Myjnia")
    szkic = db.pobierz_szkic(szkic_id)

    from views.formularze import FormularzInneView
    widok, trasy = _formularz(FormularzInneView, auto_id, szkic_id)

    assert widok.route == f"/inne/nowy/szkic/{szkic_id}"
    assert (widok.e_d.value, widok.e_o.value) == (szkic["data"], "Myjnia")
    assert [p["sciezka"] for p in widok.pliki.pozycje] == [szkic["zalacznik"]]
    widok.e_kw.value = "35"
    widok.zapisz(None)

    koszt = _wiersz("SELECT id, nazwa, kwota FROM inne_koszty WHERE auto_id=?", (auto_id,))
    assert koszt[1:] == ("Myjnia", 35.0)
    assert [p[0] for p in pomoce.pliki_wpisu("inne_koszty", koszt[0])] == [szkic["zalacznik"]]
    assert db.pobierz_szkic(szkic_id) is None
    assert trasy[-1] == "/", "pusta kolejka — zwykły powrót formularza"


def test_wizyta_ze_szkicu_bierze_licznik_i_opis(baza):
    identyfikatory = pomoce.utworz_pojazd("Warsztatowy")
    auto_id = identyfikatory["auto_id"]
    szkic_id = _szkic_z_pliku(auto_id, 0, rodzaj="wizyta", przebieg=102000, opis="Wymiana oleju u Janka")
    szkic = db.pobierz_szkic(szkic_id)

    from views.formularze import FormularzWizytyView
    widok, trasy = _formularz(FormularzWizytyView, auto_id, szkic_id)

    assert widok.route == f"/wizyty/nowa/szkic/{szkic_id}"
    assert (widok.e_d.value, widok.e_p.value, widok.e_n.value) == (szkic["data"], "102000", "Wymiana oleju u Janka")
    for chk in widok.chk_czesci:
        chk.value = True
    widok.koszt.e_kwota.value = "480"
    widok.zapisz(None)

    wizyta = _wiersz("SELECT id, przebieg, notatki FROM wizyty WHERE auto_id=? AND przebieg=102000", (auto_id,))
    assert wizyta[1:] == (102000, "Wymiana oleju u Janka")
    assert [p[0] for p in pomoce.pliki_wpisu("wizyty", wizyta[0])] == [szkic["zalacznik"]]
    assert db.pobierz_szkic(szkic_id) is None
    # W kolejce został szkic z `utworz_pojazd`, więc formularz wraca do niej.
    assert trasy[-1] == "/do-wpisania"


def test_szkic_obcego_pojazdu_albo_edycja_nie_wypelnia_formularza(baza):
    auto_id, obcy = _auto("Mój"), _auto("Obcy")
    szkic_id = db.dodaj_szkic_z_bajtow(obcy, _jpeg())
    stan = pomoce.stan_aplikacji(auto_id)

    assert utils.szkic_do_formularza(stan, szkic_id) is None
    assert utils.szkic_do_formularza(pomoce.stan_aplikacji(obcy), szkic_id, rekord_id=7) is None
    assert utils.szkic_do_formularza(pomoce.stan_aplikacji(obcy), szkic_id)["id"] == szkic_id

    from views.formularze import FormularzTankowanieView
    widok, _ = _formularz(FormularzTankowanieView, auto_id, szkic_id)
    assert widok.szkic is None and widok.route == "/tankowanie/nowe" and widok.pliki.pozycje == []


# ======================================================= trasy i ekrany

def test_trasy_szkicu_i_rola(baza, monkeypatch):
    # main.py kończy się `ft.run(main)` — import bez okna wymaga zaślepki.
    monkeypatch.setattr(ft, "run", lambda *a, **k: None)
    import main

    assert utils.trasa_uzupelnienia("tankowanie", 5) == "/tankowanie/nowe/szkic/5"
    assert utils.trasa_uzupelnienia("wizyta", 5) == "/wizyty/nowa/szkic/5"
    assert utils.szkic_z_trasy(["inne", "nowy", "szkic", "9"]) == 9
    assert utils.szkic_z_trasy(["inne", "nowy"]) is None
    # Aparat i kolejka zakładają szkice — rola „podgląd” dostaje komunikat, nie ekran.
    assert main._cel_trasy(["paragon"]) == (True, True, None, None)
    assert main._cel_trasy(["do-wpisania"]) == (True, True, None, None)
    assert main._cel_trasy(["tankowanie", "nowe", "szkic", "3"]) == (True, True, None, None)


def test_ekran_kolejki_pokazuje_szkice_i_wyroznia_wybrany_rodzaj(baza):
    auto_id = _auto()
    _szkic_z_pliku(auto_id, 4, rodzaj="wizyta", przebieg=150000, opis="Klocki")
    _szkic_z_pliku(auto_id, 0)

    strona = pomoce.zbuduj_strone()
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["DoWpisaniaView"], strona,
                                pomoce.stan_aplikacji(auto_id, "Szkicowy"))
    teksty = _teksty(widok)

    assert "2 paragony · od najstarszego" in teksty
    assert "4 dni temu" in teksty and "dziś" in teksty
    assert any(t.startswith("Wizyta w warsztacie · 150") and t.endswith(" · Klocki") for t in teksty)
    # Rodzaj wybrany po migawce stoi pierwszy i jako jedyny pełny przycisk.
    pelne = [b.content for b in _kontrolki(widok, ft.Button)]
    assert pelne == ["Wizyta"]


def test_pusta_kolejka_zaprasza_do_zdjecia(baza):
    auto_id = _auto()
    strona = pomoce.zbuduj_strone()
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["DoWpisaniaView"], strona,
                                pomoce.stan_aplikacji(auto_id, "Szkicowy"))

    assert "Nic nie czeka na wpisanie" in _teksty(widok)


class _AparatNaNiby:
    def __init__(self, dane):
        self.dane = dane

    async def take_picture(self):
        return self.dane


def test_ekran_aparatu_na_telefonie_robi_szkic_i_zapisuje_dopiski(baza):
    import flet_camera

    auto_id = _auto()
    strona = pomoce.zbuduj_strone()
    strona.page.platform = ft.PagePlatform.ANDROID
    trasy = []
    strona.page.on_route_change = lambda e: trasy.append(strona.page.route)
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MigawkaView"], strona,
                                pomoce.stan_aplikacji(auto_id, "Szkicowy"))

    assert isinstance(widok.aparat, flet_camera.Camera)
    assert _kontrolki(widok, flet_camera.Camera) == [widok.aparat]
    # test_audyty buduje widoki bez telefonu, więc wizjera nie widzi — tu tak.
    assert audyty.znajdz_expand_bez_ograniczenia(widok) == []
    assert audyty.znajdz_expand_w_kontenerze(widok) == []

    # Spust przed uruchomieniem aparatu nie robi nic.
    asyncio.run(widok._migawka(None))
    assert db.podsumowanie_szkicow(auto_id)["liczba"] == 0

    widok.aparat = _AparatNaNiby(_jpeg())
    widok._gotowy = True
    asyncio.run(widok._migawka(None))

    szkic_id = widok.szkic_id
    assert szkic_id and widok.panel.visible and not widok.pasek_spustu.visible
    assert audyty.znajdz_expand_bez_ograniczenia(widok) == []
    assert audyty.znajdz_expand_w_kontenerze(widok) == []
    assert db.pobierz_szkic(szkic_id)["data"] == datetime.now().strftime("%d.%m.%Y")

    widok.pola._zmien_rodzaj("tankowanie")
    widok.pola.e_przebieg.value = "123456"
    widok.pola.e_opis.value = "Shell"
    widok._gotowe(None)

    szkic = db.pobierz_szkic(szkic_id)
    assert (szkic["rodzaj"], szkic["przebieg"], szkic["opis"]) == ("tankowanie", 123456, "Shell")
    assert trasy[-1] == "/"


def test_ekran_aparatu_na_komputerze_proponuje_pliki(baza):
    auto_id = _auto()
    strona = pomoce.zbuduj_strone()
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MigawkaView"], strona,
                                pomoce.stan_aplikacji(auto_id, "Szkicowy"))

    assert widok.aparat is None and not utils.aparat_dostepny(strona.page)
    assert "Aparat działa na telefonie" in _teksty(widok)


def test_drugie_dotkniecie_rodzaju_zdejmuje_wybor(baza):
    auto_id = _auto(typ="Elektryczny")
    strona = pomoce.zbuduj_strone()
    pola = utils.PolaSzkicu(strona.page, auto_id)

    assert "Ładowanie" in _teksty(pola.przelacznik), "elektryk nie tankuje"
    pola._zmien_rodzaj("koszt")
    assert pola.rodzaj == "koszt"
    pola._zmien_rodzaj("koszt")
    assert pola.rodzaj is None
    assert pola.wartosci() == (None, None, "")
