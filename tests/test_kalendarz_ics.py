"""Terminy do kalendarza telefonu (katalog: N-03).

Plik iCalendar z osi przyszłości — rok do przodu, wpis całodniowy z alarmami o 9:00 w progu
terminu i dzień wcześniej — wysyłany systemowym „Udostępnij”. Pilnujemy czterech rzeczy:

1. **Co idzie do kalendarza** — terminy i płatności z datą; zaległe, zakładane wymiany,
   podpowiedzi, budżety i kilometry bez granicy czasu zostają w aplikacji, a wymiana liczona
   kilometrami idzie jako „najpóźniej” z licznika czasu.
2. **Plik** — poprawny iCalendar: CRLF, linie do 75 oktetów bez cięcia znaku, znaki ucieczki,
   wpis całodniowy, alarm w progu z Ustawień i dzień wcześniej, minione alarmy wypadają; wpis
   cykliczny to jedna seria (RRULE), UID bez daty, SEQUENCE rośnie z wysyłką; terminy
   jednorazowe na dwa lata (odnowiona polisa), płatności i serie na rok.
3. **Podpowiedź** — po wysyłce cisza, dopóki kalendarz zgadza się z aplikacją; inna data,
   nowa grupa w oknie pliku i koniec okna ją zapalają, zapłacony wpis cykliczny nie.
4. **Ekran i wysyłka** — przycisk i akcja w pasku, arkusz przy kilku autach, zapis dopiero po
   udanym „Udostępnij”; stan wysyłki należy do urządzenia, znacznik UID jedzie z kopią.
"""

import asyncio
import re
from datetime import date, datetime, timedelta

import flet as ft

import db
import pomoce
import utils
from date import na_iso


# ============================================================================
#  POMOCNIKI
# ============================================================================

def za_dni(dni):
    return (date.today() + timedelta(days=dni)).strftime("%d.%m.%Y")


def auto(nazwa="Kalendarzowe", **pola):
    kolumny = {"nazwa": nazwa, "typ_paliwa": "Benzyna", "status": db.STATUS_POJAZDU_AKTYWNY,
               "rola_wspoldzielenia": db.ROLA_WLASCICIEL}
    kolumny.update(pola)
    with db.polacz_baze() as conn:
        return conn.execute(
            f"INSERT INTO samochody ({', '.join(kolumny)}) VALUES ({', '.join('?' for _ in kolumny)})",
            list(kolumny.values())).lastrowid


def podzespol(auto_id, nazwa, interwal_km=None, interwal_miesiace=None, dni_temu=30, przebieg=None):
    data = za_dni(-dni_temu)
    with db.polacz_baze() as conn:
        return conn.execute(
            "INSERT INTO zadania (auto_id, nazwa, interwal_km, interwal_miesiace, data, data_iso, przebieg) "
            "VALUES (?,?,?,?,?,?,?)",
            (auto_id, nazwa, interwal_km, interwal_miesiace, data, na_iso(data), przebieg)).lastrowid


def z_licznikiem(auto_id, przebieg=102400):
    """Dwa odczyty 60 dni od siebie, 2 400 km różnicy — średnio 40 km dziennie."""
    with db.polacz_baze() as conn:
        for dni_temu, stan in ((60, przebieg - 2400), (0, przebieg)):
            conn.execute("INSERT INTO odczyty_przebiegu (auto_id, data, data_iso, przebieg, zrodlo) VALUES (?,?,?,?,?)",
                         (auto_id, za_dni(-dni_temu), na_iso(za_dni(-dni_temu)), stan, db.ZRODLO_ODCZYTU_DOMYSLNE))
    return auto_id


def grupy(auto_id):
    return [t["grupa"] for t in db.terminy_kalendarza(auto_id)]


def linie_pliku(dane):
    """(fizyczne linie, linie rozwinięte) — rozwinięcie wg RFC 5545: CRLF + spacja."""
    tekst = dane.decode("utf-8")
    assert tekst.endswith("\r\n") and "\n" not in tekst.replace("\r\n", "")
    fizyczne = tekst.split("\r\n")[:-1]
    rozwiniete = []
    for linia in fizyczne:
        if linia.startswith(" "):
            rozwiniete[-1] += linia[1:]
        else:
            rozwiniete.append(linia)
    return fizyczne, rozwiniete


def wydarzenia(dane):
    """VEVENT-y pliku jako słowniki (nazwa właściwości → wartość) z listą alarmów."""
    wynik, biezace, alarm = [], None, None
    for linia in linie_pliku(dane)[1]:
        nazwa, _, wartosc = linia.partition(":")
        if linia == "BEGIN:VEVENT":
            biezace = {"alarmy": []}
        elif linia == "END:VEVENT":
            wynik.append(biezace)
        elif linia == "BEGIN:VALARM":
            alarm = {}
        elif linia == "END:VALARM":
            biezace["alarmy"].append(alarm)
            alarm = None
        elif alarm is not None:
            alarm[nazwa] = wartosc
        elif biezace is not None:
            biezace[nazwa] = wartosc
    return wynik


def odczytaj_tekst(wartosc):
    return re.sub(r"\\(.)", lambda m: "\n" if m.group(1) in "nN" else m.group(1), wartosc)


def plik(auto_ids, teraz=None, numer=1):
    paczka = utils.wpisy_kalendarza(auto_ids, teraz or datetime.now())
    return db.generuj_ics(paczka["wpisy"], "Terminy", teraz=teraz, numer=numer), paczka


def wyslij(auto_ids, dzis=None):
    """To, co zapisuje udane „Udostępnij” — bez strony."""
    paczka = utils.wpisy_kalendarza(auto_ids)
    db.zapamietaj_wysylke_kalendarza(paczka["terminy"], db.numer_wysylki_kalendarza(), dzis=dzis)
    return paczka


# ============================================================================
#  CO IDZIE DO KALENDARZA
# ============================================================================

def test_do_kalendarza_ida_terminy_i_platnosci_z_data(baza):
    a = auto(oc_data=za_dni(40), przeglad_data=za_dni(500), ac_data=za_dni(-5), gwarancja_data=za_dni(800))
    db.dodaj_wydatek_cykliczny(a, "Abonament GPS", 49.0, 30, za_dni(5))
    db.dodaj_wydatek_cykliczny(a, "Garaż", 200.0, 30, za_dni(-3))
    zadanie = podzespol(a, "Filtr kabinowy", interwal_miesiace=3, dni_temu=30)
    db.zapisz_budzet(a, "paliwo", "miesiac", 1000)

    terminy = db.terminy_kalendarza(a)
    wg_grupy = {}
    for t in terminy:
        wg_grupy.setdefault(t["grupa"], []).append(t)
    assert "dokument:ac" not in wg_grupy, "zaległe zostaje w aplikacji"
    assert "dokument:gwarancja" not in wg_grupy, "poza oknem terminów"
    assert "dokument:przeglad" in wg_grupy, "termin jednorazowy idzie na dwa lata do przodu"
    assert not any(g.startswith("budzet") for g in wg_grupy), "koniec budżetu to nie termin"
    assert [t["data"] for t in wg_grupy["dokument:oc"]] == [date.today() + timedelta(days=40)]
    # Pierwsza wymiana tak, kolejne (zakładane) nie.
    assert [(t["data"] - date.today()).days for t in wg_grupy[f"podzespol:{zadanie}"]] == [61]

    wpisy = {w[1]: wg_grupy[f"cykliczny:{w[0]}"] for w in db.pobierz_wydatki_cykliczne(a)}
    (gps,), (garaz,) = wpisy["Abonament GPS"], wpisy["Garaż"]
    assert len(gps["wystapienia"]) == 13 and gps["okres_dni"] == 30, "seria tylko na rok do przodu"
    assert (garaz["data"] - date.today()).days == 30, "po zaległym następne od dziś, zaległego brak"
    assert [t["data"] for t in terminy] == sorted(t["data"] for t in terminy)


def test_kilometry_tylko_z_granica_czasu(baza):
    """Olej: 3 000 km przy 40 km dziennie to prognoza za 75 dni — w kalendarzu stoi
    termin z interwału czasu jako „najpóźniej”. Rozrząd bez interwału czasu wypada."""
    a = z_licznikiem(auto())
    olej = podzespol(a, "Olej silnikowy", interwal_km=15000, interwal_miesiace=12, przebieg=102400 - 12000)
    podzespol(a, "Rozrząd", interwal_km=120000, przebieg=50000)

    os_dane = db.os_przyszlosci(a, dni=365)
    (na_osi,) = [p for p in os_dane["pozycje"] if p["klucz"] == f"podzespol:{olej}"]
    assert na_osi["prognoza"] and na_osi["dni"] == 75

    (termin,) = db.terminy_kalendarza(a)
    assert termin["grupa"] == f"podzespol:{olej}" and termin["najpozniej"]
    assert termin["data"] == na_osi["zrodlo"]["drugi"]["data"]
    assert "kilometry mogą skończyć się wcześniej" in utils.opis_wpisu_kalendarza(
        termin, db.pobierz_dane_pojazdu(a), date.today())


def test_sprzedane_i_podpowiedzi_nie_ida(baza):
    sprzedane = auto("Sprzedane", oc_data=za_dni(40), status=db.STATUS_POJAZDU_SPRZEDANY)
    assert db.terminy_kalendarza(sprzedane) == []

    a = auto()
    with db.polacz_baze() as conn:
        for sezon, zamontowane in (("Letnie", 1), ("Zimowe", 0)):
            conn.execute("INSERT INTO zestawy_opon (auto_id, sezon, zamontowane) VALUES (?,?,?)",
                         (a, sezon, zamontowane))
    assert any(p["sugestia"] for p in db.os_przyszlosci(a, dni=365)["pozycje"])
    assert grupy(a) == [], "podpowiedź zmiany opon z kalendarza zostaje w aplikacji"

    db.dodaj_przypomnienie_o_oponach(a, za_dni(20))
    (przypomnienie,) = [w[0] for w in db.pobierz_wydatki_cykliczne(a)]
    assert grupy(a) == [f"cykliczny:{przypomnienie}"], "przypomnienie już idzie"
    (termin,) = db.terminy_kalendarza(a)
    assert utils.tytul_wpisu_kalendarza(termin) == "Zmiana opon"
    assert "Kolejne zmiany: na zimowe " in utils.opis_wpisu_kalendarza(termin, {"nazwa": "X"}, date.today())


# ============================================================================
#  PLIK
# ============================================================================

def test_plik_jest_poprawnym_icalendarem(baza):
    a = auto(oc_data=za_dni(40), nr_rej="WX 12345")
    db.dodaj_wydatek_cykliczny(a, "Abonament GPS", 49.0, 30, za_dni(5))
    dane, paczka = plik([a])

    fizyczne, rozwiniete = linie_pliku(dane)
    assert all(len(linia.encode("utf-8")) <= 75 for linia in fizyczne)
    assert rozwiniete[:2] == ["BEGIN:VCALENDAR", "VERSION:2.0"] and rozwiniete[-1] == "END:VCALENDAR"
    for blok in ("VEVENT", "VALARM"):
        assert rozwiniete.count(f"BEGIN:{blok}") == rozwiniete.count(f"END:{blok}")

    zdarzenia = wydarzenia(dane)
    assert len(zdarzenia) == len(paczka["wpisy"]) == 2
    assert len({z["UID"] for z in zdarzenia}) == 2
    oc = next(z for z in zdarzenia if odczytaj_tekst(z["SUMMARY"]).startswith("Polisa OC"))
    dzien = date.today() + timedelta(days=40)
    assert oc["DTSTART;VALUE=DATE"] == f"{dzien:%Y%m%d}"
    assert oc["DTEND;VALUE=DATE"] == f"{dzien + timedelta(days=1):%Y%m%d}"
    assert oc["TRANSP"] == "TRANSPARENT" and oc["SEQUENCE"] == "1"
    assert odczytaj_tekst(oc["SUMMARY"]) == "Polisa OC — koniec ważności · Kalendarzowe"
    opis = odczytaj_tekst(oc["DESCRIPTION"]).split("\n")
    assert opis[0] == "Ostatni dzień ważności." and opis[1] == "Pojazd: Kalendarzowe (WX 12345)."
    gps = next(z for z in zdarzenia if odczytaj_tekst(z["SUMMARY"]).startswith("Abonament GPS"))
    assert odczytaj_tekst(gps["DESCRIPTION"]).startswith(f"Kwota 49,00 {utils.symbol_waluty()}, powtarza się co miesiąc.")
    assert gps["RRULE"] == "FREQ=DAILY;INTERVAL=30;COUNT=13" and "RRULE" not in oc


def test_zawijanie_i_znaki_ucieczki():
    tytul = "Przegląd; OC, AC \\ żółć — " + "ąęść" * 30
    opis = "Pierwsza linia\nDruga, z przecinkiem; i średnikiem"
    dane = db.generuj_ics([{"uid": "x-1@cars-app", "data": date(2026, 11, 15), "tytul": tytul, "opis": opis,
                            "alarmy": [(30, "Za 30 dni")]}], "Kalendarz, test")
    fizyczne, _ = linie_pliku(dane)
    for linia in fizyczne:
        assert len(linia.encode("utf-8")) <= 75, linia
        linia.encode("utf-8").decode("utf-8")
    (z,) = wydarzenia(dane)
    assert odczytaj_tekst(z["SUMMARY"]) == tytul and odczytaj_tekst(z["DESCRIPTION"]) == opis
    assert ";" not in z["SUMMARY"].replace("\\;", "") and "," not in z["SUMMARY"].replace("\\,", "")
    assert z["alarmy"] == [{"ACTION": "DISPLAY", "DESCRIPTION": "Za 30 dni", "TRIGGER": "-P29DT15H"}]


def test_alarmy_w_progu_i_dzien_wczesniej(baza):
    db.zapisz_prog_dni_dokumentu("oc", 45)
    a = auto(oc_data=za_dni(60))
    db.dodaj_wydatek_cykliczny(a, "Abonament GPS", 49.0, 30, za_dni(20))
    teraz = datetime.combine(date.today(), datetime.min.time()).replace(hour=8)
    zdarzenia = {odczytaj_tekst(z["SUMMARY"]).split(" ")[0]: z for z in wydarzenia(plik([a], teraz)[0])}

    oc = zdarzenia["Polisa"]
    assert [al["TRIGGER"] for al in oc["alarmy"]] == ["-P44DT15H", "-PT15H"], "próg OC z Ustawień i dzień przed"
    assert odczytaj_tekst(oc["alarmy"][0]["DESCRIPTION"]).endswith(": za 45 dni")
    assert odczytaj_tekst(oc["alarmy"][1]["DESCRIPTION"]).endswith(": jutro")
    # Wpis cykliczny co miesiąc: wspólne 30 dni przycięte do trzeciej części okresu.
    assert [al["TRIGGER"] for al in zdarzenia["Abonament"]["alarmy"]] == ["-P9DT15H", "-PT15H"]

    jutro, za_piec = date.today() + timedelta(days=1), date.today() + timedelta(days=5)
    assert db.alarmy_terminu(za_piec, 30, teraz) == [1], "próg już minął"
    assert db.alarmy_terminu(jutro, 30, teraz) == [1], "dzisiaj o 9:00 jeszcze przed nami"
    assert db.alarmy_terminu(jutro, 30, teraz.replace(hour=10)) == []
    assert db.alarmy_terminu(za_piec, 1, teraz) == [1], "próg jednego dnia to jeden alarm"


def test_uid_stale_a_seria_jednym_wpisem(baza):
    a = auto(oc_data=za_dni(40))
    db.dodaj_wydatek_cykliczny(a, "Myjnia", 40.0, 30, za_dni(0))
    pierwszy = {w["uid"]: (w["data"], w["powtorz"]) for w in plik([a])[1]["wpisy"]}
    assert pierwszy == {w["uid"]: (w["data"], w["powtorz"]) for w in plik([a])[1]["wpisy"]}
    assert all(re.fullmatch(r"[0-9a-f]{8}-\d+-[a-z0-9-]+@cars-app", uid) for uid in pierwszy)

    db.oznacz_zaplacony_wydatek_cykliczny(db.pobierz_wydatki_cykliczne(a)[0][0], a)
    drugi = {w["uid"]: (w["data"], w["powtorz"]) for w in plik([a])[1]["wpisy"]}
    assert set(drugi) == set(pierwszy), "zapłacone przesuwa serię, nie dokłada wpisów"
    (myjnia,) = [u for u in drugi if "-cykliczny-" in u]
    assert pierwszy[myjnia] == (date.today(), (30, 13))
    assert drugi[myjnia] == (date.today() + timedelta(days=30), (30, 12))

    assert db.numer_wysylki_kalendarza() == 1
    wyslij([a])
    assert db.numer_wysylki_kalendarza() == 2
    assert {z["SEQUENCE"] for z in wydarzenia(plik([a], numer=db.numer_wysylki_kalendarza())[0])} == {"2"}


# ============================================================================
#  PODPOWIEDŹ
# ============================================================================

def test_podpowiedz_milczy_dopoki_kalendarz_sie_zgadza(baza):
    a = auto(oc_data=za_dni(40))
    db.dodaj_wydatek_cykliczny(a, "Myjnia", 40.0, 30, za_dni(0))
    assert db.stan_kalendarza(a) is None, "nie wysyłano — nie ma czego porównywać"
    wyslij([a])
    assert db.stan_kalendarza(a) is None

    db.oznacz_zaplacony_wydatek_cykliczny(db.pobierz_wydatki_cykliczne(a)[0][0], a)
    assert db.stan_kalendarza(a) is None, "zapłacone w terminie zgadza się z kalendarzem"

    with db.polacz_baze() as conn:
        conn.execute("UPDATE wydatki_cykliczne SET nastepna_data=? WHERE auto_id=?", (za_dni(32), a))
    assert db.stan_kalendarza(a) is None, f"przesunięcie o 2 dni mieści się w {db.TOLERANCJA_SERII_DNI}"
    with db.polacz_baze() as conn:
        conn.execute("UPDATE wydatki_cykliczne SET nastepna_data=? WHERE auto_id=?", (za_dni(20), a))
    assert db.stan_kalendarza(a)["zmienione"] == 1, "seria rozjechała się o 10 dni"

    # Niezapłacone po terminie: następne liczą się od dziś i płyną z każdym dniem —
    # to sprawa do załatwienia w aplikacji, nie powód do ponownej wysyłki.
    with db.polacz_baze() as conn:
        conn.execute("UPDATE wydatki_cykliczne SET nastepna_data=? WHERE auto_id=?", (za_dni(0), a))
    wyslij([a])
    pojutrze = date.today() + timedelta(days=5)
    assert all(t["po_zaleglym"] for t in db.terminy_kalendarza(a, dzis=pojutrze) if t["okres_dni"])
    assert db.stan_kalendarza(a, dzis=pojutrze) is None


def test_podpowiedz_po_zmianie_terminow_i_na_koniec_okna(baza):
    a = auto(oc_data=za_dni(40), przeglad_data=za_dni(100))
    wyslij([a])

    with db.polacz_baze() as conn:
        conn.execute("UPDATE samochody SET oc_data=? WHERE id=?", (za_dni(400), a))
    stan = db.stan_kalendarza(a)
    assert stan["zmienione"] == 1 and stan["wyslano"] == date.today(), "odnowione OC — data za ponad rok"
    assert grupy(a) == ["dokument:przeglad", "dokument:oc"], "i trafi do pliku od razu"
    assert stan["do"] == date.today() + timedelta(days=db.OKNO_KALENDARZA) and not stan["konczy_sie"]

    with db.polacz_baze() as conn:
        conn.execute("UPDATE samochody SET oc_data=?, przeglad_data=NULL WHERE id=?", (za_dni(40), a))
    assert db.stan_kalendarza(a) is None, "zniknięcie terminu nie zapala podpowiedzi"
    db.dodaj_wydatek_cykliczny(a, "Abonament GPS", 49.0, 30, za_dni(5))
    assert db.stan_kalendarza(a)["zmienione"] == 1, "nowy wpis w oknie pliku"

    wyslij([a])
    dzis = date.today() + timedelta(days=db.OKNO_KALENDARZA - db.DNI_ZAPASU_KALENDARZA)
    with db.polacz_baze() as conn:
        conn.execute("UPDATE samochody SET oc_data=? WHERE id=?",
                     ((dzis + timedelta(days=20)).strftime("%d.%m.%Y"), a))
        conn.execute("UPDATE wydatki_cykliczne SET nastepna_data=? WHERE auto_id=?",
                     ((dzis + timedelta(days=5)).strftime("%d.%m.%Y"), a))
    stan = db.stan_kalendarza(a, dzis=dzis)
    assert stan["konczy_sie"], "kalendarz ma terminy tylko do końca okna"
    strona = pomoce.zbuduj_strone()
    baner = utils.baner_kalendarza(strona.page, dict(stan, zmienione=0), None)
    assert any(t.startswith("Kalendarz ma terminy tylko do") for t in pomoce.napisy(baner))


def test_zapis_wysylki_sprzata_usuniete_auta_i_zly_zapis(baza):
    a, b = auto("Pierwsze", oc_data=za_dni(40)), auto("Drugie", oc_data=za_dni(50))
    wyslij([a, b])
    assert set(db.pobierz_eksport_kalendarza()["pojazdy"]) == {str(a), str(b)}
    with db.polacz_baze() as conn:
        conn.execute("DELETE FROM samochody WHERE id=?", (b,))
    wyslij([a])
    assert set(db.pobierz_eksport_kalendarza()["pojazdy"]) == {str(a)}

    db.zapisz_ustawienie(db.KLUCZ_EKSPORTU_KALENDARZA, "{zepsute")
    assert db.pobierz_eksport_kalendarza() == {"numer": 0, "pojazdy": {}}
    assert db.stan_kalendarza(a) is None


def test_stan_wysylki_nalezy_do_urzadzenia(baza):
    a = auto(oc_data=za_dni(40))
    wyslij([a])
    assert db.KLUCZ_EKSPORTU_KALENDARZA.startswith(db.PRZEDROSTEK_USTAWIEN_KALENDARZA)
    assert db.PRZEDROSTEK_USTAWIEN_KALENDARZA in db.PRZEDROSTKI_USTAWIEN_URZADZENIA
    assert db.KLUCZ_EKSPORTU_KALENDARZA in db.ustawienia_kopii_urzadzenia()
    assert db.ustawienie_interfejsu(db.KLUCZ_EKSPORTU_KALENDARZA), "wysyłka nie unieważnia metryk"
    # Znacznik UID jedzie z kopią: nowy telefon z tą kopią podmieni te same wpisy.
    assert not db.KLUCZ_ZNACZNIKA_KALENDARZA.startswith(db.PRZEDROSTKI_USTAWIEN_URZADZENIA)
    assert db.KLUCZ_ZNACZNIKA_KALENDARZA not in db.ustawienia_kopii_urzadzenia()
    assert db.znacznik_kalendarza() == db.znacznik_kalendarza()


# ============================================================================
#  EKRAN I WYSYŁKA
# ============================================================================

def ekran(strona, auto_id, nazwa="Kalendarzowe"):
    stan = pomoce.stan_aplikacji(auto_id, nazwa)
    return pomoce.zbuduj_widok(pomoce.klasy_widokow()["PrzyszloscView"], strona, stan)


def _zapisywacz(pliki, wynik=True):
    async def zapisz(nazwa, dane):
        pliki[nazwa] = dane
        return wynik
    return zapisz


def test_ekran_ma_przycisk_akcje_i_podpowiedz(baza):
    strona = pomoce.zbuduj_strone()
    a = auto(oc_data=za_dni(40))
    widok = ekran(strona, a)
    przyciski = [b for b in pomoce.kontrolki(widok, ft.FilledTonalButton) if b.content == "Dodaj terminy do kalendarza"]
    assert len(przyciski) == 1 and utils.OPIS_KALENDARZA in pomoce.napisy(widok)
    assert [b.icon for b in pomoce.kontrolki(widok.appbar, ft.IconButton)].count(ft.Icons.EDIT_CALENDAR) == 1
    assert not any("terminy się zmieniły" in t for t in pomoce.napisy(widok))

    wyslij([a])
    with db.polacz_baze() as conn:
        conn.execute("UPDATE samochody SET oc_data=? WHERE id=?", (za_dni(45), a))
    assert any("terminy się zmieniły — 1 zmiana" in t for t in pomoce.napisy(ekran(strona, a)))

    sprzedane = auto("Sprzedane", oc_data=za_dni(40), status=db.STATUS_POJAZDU_SPRZEDANY)
    widok = ekran(strona, sprzedane, "Sprzedane")
    assert ft.Icons.EDIT_CALENDAR not in [b.icon for b in pomoce.kontrolki(widok.appbar, ft.IconButton)]


def test_wysylka_zapisuje_dopiero_po_udostepnieniu(baza, monkeypatch):
    strona = pomoce.zbuduj_strone()
    komunikaty = []
    monkeypatch.setattr(utils.kalendarz, "pokaz_komunikat", lambda s, tekst, *x, **k: komunikaty.append(tekst))
    a = auto(oc_data=za_dni(40))
    pliki = {}

    strona.page.zapisz_bajty_pliku = _zapisywacz(pliki, wynik=False)
    assert asyncio.run(utils.wyslij_do_kalendarza(strona.page, [a])) is False
    assert list(pliki) == ["terminy_Kalendarzowe.ics"] and db.pobierz_eksport_kalendarza()["pojazdy"] == {}

    odswiezone = []
    strona.page.zapisz_bajty_pliku = _zapisywacz(pliki)
    assert asyncio.run(utils.wyslij_do_kalendarza(strona.page, [a], po_wyslaniu=lambda: odswiezone.append(1)))
    assert pliki["terminy_Kalendarzowe.ics"].startswith(b"BEGIN:VCALENDAR\r\n")
    assert str(a) in db.pobierz_eksport_kalendarza()["pojazdy"] and odswiezone == [1]
    assert komunikaty[-1] == "W pliku 1 termin — otwórz go w kalendarzu telefonu."

    pliki.clear()
    pusty = auto("Pusty")
    assert asyncio.run(utils.wyslij_do_kalendarza(strona.page, [pusty])) is False
    assert pliki == {} and komunikaty[-1].startswith("Na najbliższy rok nie ma terminów z datą")


def test_przy_kilku_autach_arkusz_wyboru(baza, monkeypatch):
    strona = pomoce.zbuduj_strone()
    monkeypatch.setattr(utils.kalendarz, "pokaz_komunikat", lambda *x, **k: None)
    menu = []
    monkeypatch.setattr(utils.kalendarz, "pokaz_menu_kontekstowe", lambda s, tytul, pozycje: menu.append(pozycje))
    zadania = []
    strona.page.run_task = lambda funkcja, *x: zadania.append(funkcja)
    pliki = {}
    strona.page.zapisz_bajty_pliku = _zapisywacz(pliki)

    a = auto("Astra", oc_data=za_dni(40))
    utils.wyslij_terminy_do_kalendarza(strona.page, pomoce.stan_aplikacji(a, "Astra"))
    assert menu == [] and len(zadania) == 1, "jedno aktywne auto — bez pytania"
    asyncio.run(zadania[0]())
    assert list(pliki) == ["terminy_Astra.ics"]

    b = auto("Berlingo", przeglad_data=za_dni(60))
    auto("Corsa", oc_data=za_dni(30), status=db.STATUS_POJAZDU_SPRZEDANY)
    pliki.clear()
    utils.wyslij_terminy_do_kalendarza(strona.page, pomoce.stan_aplikacji(b, "Berlingo"))
    (pozycje,) = menu
    assert [p["tekst"] for p in pozycje] == ["Tylko Berlingo", "Wszystkie aktywne (2)"]
    asyncio.run(pozycje[1]["akcja"]())
    tytuly = [odczytaj_tekst(z["SUMMARY"]) for z in wydarzenia(pliki["terminy_pojazdow.ics"])]
    assert tytuly == ["Polisa OC — koniec ważności · Astra", "Przegląd techniczny — koniec ważności · Berlingo"]
    assert set(db.pobierz_eksport_kalendarza()["pojazdy"]) == {str(a), str(b)}


def test_wyszukiwarka_prowadzi_do_kalendarza():
    for fraza in ("kalendarz telefonu", "ics"):
        assert "co-przede-mna" in [e["id"] for e in utils.znajdz_ekrany(fraza)], fraza
