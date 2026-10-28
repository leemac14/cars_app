"""Ekran „Wizyty w warsztacie” i formularz wizyty.

Lista: dane (pozycje z cenami, gwarancja wspólna i własna, część wymieniona później),
podsumowanie liczone po filtrach i wyszukiwarce, karta z warsztatem w tytule, arkusz
szczegółów z akcjami i rolą „podgląd”, gest usuwania z „Cofnij”, tło karty po zaznaczaniu,
pusty ekran. Formularz: wizyta bez podzespołu dopiero drugim „Zapisz”, szukanie w podzespołach
(zaznaczone na górze), ceny pozycji (zapis, edycja nie rusza niezmienionej, suma ponad koszt),
cena pozycji w historii podzespołu.
"""

from datetime import date, timedelta
from types import SimpleNamespace

import flet as ft
import pytest

import audyty
import db
import pomoce
import utils


@pytest.fixture
def bez_nawigacji(monkeypatch):
    zapis = SimpleNamespace(trasy=[], komunikaty=[])
    monkeypatch.setattr(utils, "przejdz", lambda page, trasa: zapis.trasy.append(trasa))
    monkeypatch.setattr(utils, "pokaz_komunikat", lambda page, tekst, *a, **k: zapis.komunikaty.append(tekst))
    return zapis


def pojazd(podzespoly=("Olej silnikowy i filtr", "Klocki hamulcowe", "Filtr powietrza"), nazwa="Warsztatowy"):
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO samochody (nazwa, typ_paliwa, status, rola_wspoldzielenia) VALUES (?,?,?,?)",
                  (nazwa, "Benzyna", db.STATUS_POJAZDU_AKTYWNY, db.ROLA_WLASCICIEL))
        auto = c.lastrowid
        zadania = {}
        for nazwa in podzespoly:
            c.execute("INSERT INTO zadania (auto_id, nazwa, interwal_km) VALUES (?,?,?)", (auto, nazwa, 15000))
            zadania[nazwa] = c.lastrowid
    return auto, zadania


def wizyta(auto, dni, koszt, wykonawca="AutoFix", pozycje=(), gwarancja=(None, None), **pola):
    """Wizyta wprost w bazie; `pozycje` — [(zadanie_id, cena)] z gwarancją wizyty, jak z formularza."""
    d = pomoce.dzien(dni)
    w_id = pomoce.wstaw("wizyty", auto_id=auto, data=d, przebieg=100000, wykonawca=wykonawca,
                        koszt_calkowity=koszt, gwarancja_data=gwarancja[0], gwarancja_przebieg=gwarancja[1], **pola)
    for zadanie, cena in pozycje:
        pomoce.wstaw("historia", wizyta_id=w_id, zadanie_id=zadanie, data=d, przebieg=100000, cena=cena,
                     wykonawca=wykonawca, gwarancja_data=gwarancja[0], gwarancja_przebieg=gwarancja[1])
    return w_id


def za_dni(dni):
    return (date.today() + timedelta(days=dni)).strftime("%d.%m.%Y")


def jeden(sql, parametry=()):
    with db.polacz_baze() as conn:
        wiersz = conn.execute(sql, parametry).fetchone()
    return wiersz[0] if wiersz and len(wiersz) == 1 else wiersz


def ceny(w_id):
    with db.polacz_baze() as conn:
        return dict(conn.execute("SELECT zadanie_id, cena FROM historia WHERE wizyta_id=?", (w_id,)).fetchall())


def zbuduj(klasa, auto, *argumenty, stan=None):
    strona = pomoce.zbuduj_strone()
    widok = klasa(strona.page, stan or pomoce.stan_aplikacji(auto, "Warsztatowy"), *argumenty)
    widok._strona_testowa = strona
    return widok


def lista(auto):
    from views.history_view import WizytyZbiorczeView
    widok = zbuduj(WizytyZbiorczeView, auto)
    widok.update = lambda *a, **k: None
    return widok


def formularz(auto, w_id=None, stan=None):
    from views.formularze import FormularzWizytyView
    return zbuduj(FormularzWizytyView, auto, w_id, stan=stan)


def zaznacz(widok, zadanie, wartosc=True):
    chk = next(c for c in widok.chk_czesci if c.data == zadanie)
    chk.value = wartosc
    chk.on_change(None)


def na_podglad(auto):
    with db.polacz_baze() as conn:
        conn.execute("UPDATE samochody SET wspolny_pojazd_id='wspolny-1' WHERE id=?", (auto,))
    db.ustaw_role_pojazdu(auto, db.ROLA_PODGLAD)


# ============================================================================
#  DANE LISTY
# ============================================================================

def test_lista_wizyt_zbiera_pozycje_ceny_rozbicie_i_gwarancje(baza):
    auto, z = pojazd()
    w1 = wizyta(auto, 30, 900.0, pozycje=[(z["Klocki hamulcowe"], 350.0), (z["Filtr powietrza"], 0)],
                gwarancja=(za_dni(365), None), koszt_robocizny=300.0)
    w2 = wizyta(auto, 10, 120.0, db.WARSZTAT_BEZ_NAZWY)
    wizyty = {w["id"]: w for w in db.lista_wizyt(auto)}
    a, b = wizyty[w1], wizyty[w2]

    assert (a["warsztat"], b["warsztat"], b["pozycje"]) == ("AutoFix", None, [])
    assert [(p["nazwa"], p["cena"]) for p in a["pozycje"]] == [("Filtr powietrza", 0.0), ("Klocki hamulcowe", 350.0)]
    assert a["gwarancja"]["status"] == db.STATUS_GWARANCJI_OK and not a["gwarancja"]["wygasla"]
    assert not any(p["wlasna_gwarancja"] for p in a["pozycje"]) and b["gwarancja"] is None
    assert (a["rozbicie"]["robocizna"], a["rozbicie"]["czesci"]) == (300.0, 600.0)


def test_gwarancja_wlasna_pozycji_i_czesc_wymieniona_pozniej(baza):
    auto, z = pojazd()
    klocki = z["Klocki hamulcowe"]
    w1 = wizyta(auto, 200, 500.0, pozycje=[(klocki, 0)], gwarancja=(za_dni(400), None))
    wizyta(auto, 20, 300.0, pozycje=[(klocki, 0)])

    # Klocki wymieniono jeszcze raz — gwarancja pierwszej wizyty jest już tylko historią.
    pierwsza = next(w for w in db.lista_wizyt(auto) if w["id"] == w1)
    assert pierwsza["gwarancja"]["wymieniona"] == pomoce.dzien(20)
    assert pierwsza["pozycje"][0]["gwarancja"]["wymieniona"] == pomoce.dzien(20)

    db.zapisz_gwarancje_wpisu(jeden("SELECT id FROM historia WHERE wizyta_id=?", (w1,)), None, 150000)
    pierwsza = next(w for w in db.lista_wizyt(auto) if w["id"] == w1)
    assert pierwsza["pozycje"][0]["wlasna_gwarancja"] is True
    assert "wymieniona" not in pierwsza["gwarancja"], "wspólna nie obejmuje już żadnej pozycji"


def test_podsumowanie_liczy_srednia_z_platnych_i_ostatnia_wizyte():
    dzis = date(2026, 10, 29)
    wizyty = [
        {"id": 1, "data": "01.10.2026", "koszt": 300.0, "warsztat": "AutoFix"},
        {"id": 2, "data": "20.10.2026", "koszt": 0.0, "warsztat": None},
        {"id": 3, "data": "20.10.2026", "koszt": 500.0, "warsztat": "ASO"},
        {"id": 4, "data": "kiedyś", "koszt": 100.0, "warsztat": "Bez daty"},
    ]
    wynik = db.podsumowanie_wizyt(wizyty, dzis)

    assert (wynik["liczba"], wynik["suma"], wynik["srednia"]) == (4, 900.0, 300.0)
    assert wynik["ostatnia"] == {"id": 3, "data": "20.10.2026", "dni": 9, "warsztat": "ASO"}
    assert db.podsumowanie_wizyt([], dzis) == {"liczba": 0, "suma": 0.0, "srednia": 0.0, "ostatnia": None}
    slowa = [utils.kiedy_ostatnia({"dni": d, "data": t}, dzis)
             for d, t in ((0, "29.10.2026"), (1, "28.10.2026"), (9, "20.10.2026"), (289, "14.01.2026"), (-3, "01.11.2026"))]
    assert slowa == ["dziś", "wczoraj", "9 dni temu", "9 miesięcy temu", None]


# ============================================================================
#  EKRAN LISTY
# ============================================================================

def test_ekran_ma_podsumowanie_karty_z_warsztatem_i_naglowki_wizyt(baza, bez_nawigacji):
    auto, z = pojazd()
    wizyta(auto, 40, 900.0, pozycje=[(z["Klocki hamulcowe"], 350.0)], koszt_robocizny=300.0)
    wizyta(auto, 5, 0.0, db.WARSZTAT_BEZ_NAZWY, notatki="Diagnostyka")
    widok = lista(auto)
    teksty = pomoce.napisy(widok)

    assert "Wizyty w warsztacie" in pomoce.napisy(widok.appbar)
    assert {"AutoFix", utils.TYTUL_WIZYTY_BEZ_WARSZTATU, "Klocki hamulcowe · 350,00 PLN",
            "Robocizna 300,00 PLN", "Części 600,00 PLN", "Bez wymienionych podzespołów"} <= set(teksty)
    assert "Bez podziału na robociznę i części" not in teksty
    assert any(t.startswith(("1 wizyta", "2 wizyty")) for t in teksty)
    assert not any("wpis" in t for t in teksty if "•" in t), "nagłówek miesiąca liczy wizyty"
    pods = widok.podsumowanie
    # Darmowa wizyta (gwarancja, diagnostyka) nie zaniża średniej.
    assert (pods._liczba.value, pods._suma.value, pods._srednia.value) == ("2", "900,00 PLN", "900,00 PLN")
    assert pods._ostatnia.value == f"Ostatnia: {pomoce.dzien(5)} (5 dni temu)"

    widok._filtruj(SimpleNamespace(control=SimpleNamespace(value="klocki")))
    widoczne = [k for k in widok.wszystkie_karty if any(k["karta"] is c for c in widok.lista_kart.controls)]
    assert len(widoczne) == 1 and pods._liczba.value == "1"
    assert pods._ostatnia.value.endswith("· AutoFix")


def test_karta_pokazuje_najwyzej_cztery_podzespoly_i_reszte_liczba(baza, bez_nawigacji):
    nazwy = [f"Część {i}" for i in range(1, 7)]
    auto, z = pojazd(nazwy)
    wizyta(auto, 3, 600.0, pozycje=[(z[n], 0) for n in nazwy])

    teksty = pomoce.napisy(lista(auto).wszystkie_karty[0]["karta"])
    assert sorted(t for t in teksty if t.startswith("Część")) == nazwy[:4] and "+2" in teksty


def test_arkusz_szczegolow_ma_pozycje_gwarancje_i_akcje_a_podglad_tylko_kontakt(baza, bez_nawigacji, monkeypatch):
    auto, z = pojazd()
    pomoce.wstaw("warsztaty", auto_id=auto, nazwa="AutoFix", telefon="123456789", adres="Polna 1, Lublin")
    w = wizyta(auto, 30, 900.0, pozycje=[(z["Klocki hamulcowe"], 350.0), (z["Filtr powietrza"], 0)],
               gwarancja=(za_dni(365), None), koszt_robocizny=300.0)
    arkusze = []
    monkeypatch.setattr(utils, "pokaz_menu_kontekstowe",
                        lambda page, tytul, pozycje, tresc=None, dopisek=None: arkusze.append((tytul, pozycje, tresc)))

    lista(auto).karty_ref[w].on_click(None)
    tytul, pozycje, tresc = arkusze[-1]
    teksty = [t for k in tresc for t in pomoce.napisy(k)]
    assert tytul == "AutoFix"
    assert {"Koszt wizyty", "900,00 PLN", "Wymienione podzespoły (2)", "Klocki hamulcowe", "350,00 PLN",
            "Filtr powietrza"} <= set(teksty)
    assert any(t.startswith("Gwarancja jeszcze") for t in teksty)
    akcje = [p["tekst"] for p in pozycje]
    assert akcje[:5] == ["Edytuj wizytę", "Duplikuj wizytę", "Zadzwoń: 123 456 789", "Pokaż na mapie", "Karta warsztatu"]
    assert akcje[-2:] == ["Zwróć pozycję na listę Do zrobienia", "Usuń wizytę"]
    kolumna = ft.Column(tresc)
    for audyt in (audyty.znajdz_uciete_napisy, audyty.znajdz_pogrubienia_na_drugim_planie,
                  audyty.znajdz_expand_bez_ograniczenia, audyty.znajdz_expand_w_kontenerze):
        assert audyt(kolumna) == []

    na_podglad(auto)
    widok = lista(auto)
    assert widok.floating_action_button is None and not pomoce.kontrolki(widok, ft.Dismissible)
    widok.karty_ref[w].on_click(None)
    assert [p["tekst"] for p in arkusze[-1][1]] == ["Zadzwoń: 123 456 789", "Pokaż na mapie", "Karta warsztatu"]


def test_gest_usuwa_wizyte_do_kosza_a_cofnij_oddaje_ja_z_podzespolem(baza, bez_nawigacji, monkeypatch):
    auto, z = pojazd()
    klocki = z["Klocki hamulcowe"]
    w = wizyta(auto, 30, 400.0, pozycje=[(klocki, 0)])
    db.przelicz_wszystkie_zadania(auto)
    komunikaty = []
    monkeypatch.setattr(utils, "pokaz_komunikat_cofnij",
                        lambda page, tekst, wynik, *a, **k: komunikaty.append((tekst, wynik)))

    pomoce.kontrolki(lista(auto), ft.Dismissible)[0].on_dismiss(None)
    assert jeden("SELECT COUNT(*) FROM wizyty WHERE auto_id=?", (auto,)) == 0
    assert jeden("SELECT data FROM zadania WHERE id=?", (klocki,)) is None
    tekst, wynik = komunikaty[-1]
    assert tekst == "Usunięto wizytę w warsztacie."

    wynik["cofnij"]()
    assert jeden("SELECT COUNT(*) FROM historia WHERE wizyta_id=?", (w,)) == 1
    assert jeden("SELECT data FROM zadania WHERE id=?", (klocki,)) == pomoce.dzien(30)


def test_koniec_zaznaczania_oddaje_karcie_jej_tlo(baza, bez_nawigacji):
    auto, _ = pojazd()
    w1, w2 = wizyta(auto, 30, 400.0), wizyta(auto, 20, 200.0)
    widok = lista(auto)
    tla = {w: widok.karty_ref[w].bgcolor for w in (w1, w2)}
    assert all(tla.values()), "karta listy ma własne tło (pod nim leży cień)"

    widok.karty_ref[w1].on_long_press(None)
    assert widok.karty_ref[w1].bgcolor != tla[w1]
    widok.zakoncz_zaznaczanie()
    assert {w: widok.karty_ref[w].bgcolor for w in (w1, w2)} == tla


def test_pusty_ekran_z_przyciskiem_a_w_podgladzie_bez(baza, bez_nawigacji):
    auto, _ = pojazd()
    assert {"Nie ma jeszcze wizyt", "Dodaj pierwszą wizytę"} <= set(pomoce.napisy(lista(auto)))

    na_podglad(auto)
    teksty = pomoce.napisy(lista(auto))
    assert "Nie ma jeszcze wizyt" in teksty and "Dodaj pierwszą wizytę" not in teksty


# ============================================================================
#  FORMULARZ
# ============================================================================

def test_wizyta_bez_podzespolu_zapisuje_sie_drugim_zapisz(baza, bez_nawigacji):
    auto, z = pojazd()
    widok = formularz(auto)
    widok.e_p.value = "100000"
    widok.koszt.e_robocizna.value = "150"

    widok.zapisz(None)
    assert jeden("SELECT COUNT(*) FROM wizyty") == 0
    assert widok.blad_czesci.value.startswith("Nie zaznaczono podzespołu")
    assert "ponownie" in bez_nawigacji.komunikaty[-1]

    # Ruszone zaznaczenie zdejmuje potwierdzenie — pytanie wraca.
    zaznacz(widok, z["Klocki hamulcowe"])
    zaznacz(widok, z["Klocki hamulcowe"], False)
    widok.zapisz(None)
    assert jeden("SELECT COUNT(*) FROM wizyty") == 0

    widok.zapisz(None)
    assert jeden("SELECT koszt_calkowity FROM wizyty") == 150.0
    assert jeden("SELECT COUNT(*) FROM historia") == 0


def test_ceny_pozycji_zapis_edycja_bez_ruszania_i_suma_ponad_koszt(baza, bez_nawigacji):
    auto, z = pojazd()
    klocki, filtr = z["Klocki hamulcowe"], z["Filtr powietrza"]
    widok = formularz(auto)
    widok.e_p.value = "100000"
    widok.koszt.e_robocizna.value, widok.koszt.e_czesci.value = "200", "400"
    zaznacz(widok, klocki)
    zaznacz(widok, filtr)
    assert widok.wiersze_czesci[klocki].controls[1].visible, "pole ceny przy zaznaczonym"
    widok.ceny_pozycji[klocki].value = "350,50"
    widok.zapisz(None)
    w = jeden("SELECT MAX(id) FROM wizyty")
    assert ceny(w) == {klocki: 350.5, filtr: 0.0}

    # Cena zapisana inaczej niż z pola (np. z Do zrobienia) zostaje co do grosza, ruszona — się zmienia.
    with db.polacz_baze() as conn:
        conn.execute("UPDATE historia SET cena=33.333 WHERE wizyta_id=? AND zadanie_id=?", (w, filtr))
    edycja = formularz(auto, w)
    assert edycja.ceny_pozycji[klocki].value == "350,5" and not edycja._czy_zmieniono()
    assert [r.controls[0].data for r in edycja.kolumna_czesci.controls[:2]] == [filtr, klocki], "zaznaczone na górze"
    edycja.ceny_pozycji[klocki].value = "300"
    assert edycja._czy_zmieniono()
    edycja.zapisz(None)
    assert ceny(w) == {klocki: 300.0, filtr: 33.333}

    edycja = formularz(auto, w)
    edycja.ceny_pozycji[klocki].value = "700"
    edycja.ceny_pozycji[filtr].value = "abc"
    edycja.zapisz(None)
    assert edycja.ceny_pozycji[filtr].error == "Błędna kwota"
    edycja.ceny_pozycji[filtr].value = ""
    edycja.zapisz(None)
    assert edycja.ceny_pozycji[klocki].error.startswith("Pozycje razem 700,00 PLN — więcej niż koszt wizyty")
    assert ceny(w) == {klocki: 300.0, filtr: 33.333}

    stan = pomoce.stan_aplikacji(auto, "Warsztatowy")
    stan.duplikuj_zrodlo_wizyta = w
    assert formularz(auto, stan=stan).ceny_pozycji[klocki].value == "300", "duplikat przenosi ceny pozycji"


def test_szukanie_w_podzespolach_trzyma_zaznaczone_na_gorze(baza, bez_nawigacji):
    nazwy = [f"Podzespół {i}" for i in range(1, 8)] + ["Łożysko koła"]
    auto, z = pojazd(nazwy)
    widok = formularz(auto)
    assert any(k is widok.szukaj_czesci for k in pomoce.kontrolki(widok.sekcja_czesci))
    zaznacz(widok, z["Podzespół 3"])
    assert widok.licznik_czesci.value == "Zaznaczone: 1 z 8"

    widok.szukaj_czesci.value = "lozysko"
    widok._szukaj_czesci()
    widoczne = [w.controls[0].data for w in widok.kolumna_czesci.controls if w.visible]
    assert widoczne == [z["Podzespół 3"], z["Łożysko koła"]], "zaznaczony zawsze widać, szukanie bez ogonków"

    widok.szukaj_czesci.value = ""
    widok._szukaj_czesci()
    assert widok.kolumna_czesci.controls[0].controls[0].data == z["Podzespół 3"]
    assert all(w.visible for w in widok.kolumna_czesci.controls)

    krotki, _ = pojazd(("Olej", "Filtr"), nazwa="Krótki")
    maly = formularz(krotki)
    assert not any(k is maly.szukaj_czesci for k in pomoce.kontrolki(maly.sekcja_czesci)), "krótka lista bez szukania"


def test_historia_podzespolu_pokazuje_cene_pozycji_wizyty(baza, bez_nawigacji):
    from views.history_view import HistoriaView

    auto, z = pojazd()
    klocki = z["Klocki hamulcowe"]
    wizyta(auto, 30, 900.0, pozycje=[(klocki, 350.0)])
    wizyta(auto, 10, 500.0, pozycje=[(klocki, 0)])

    teksty = pomoce.napisy(zbuduj(HistoriaView, auto, klocki))
    assert "350,00 PLN" in teksty and "500,00 PLN (cała wizyta)" in teksty
    assert any(t.endswith("Wizyta zbiorcza za 900,00 PLN") for t in teksty)
