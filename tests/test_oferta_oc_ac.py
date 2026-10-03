"""Notatka „najlepsza oferta OC/AC”.

Ubezpieczenie kupuje się raz w roku i za każdym razem porównanie zaczynało od
zera, bo zeszłoroczne nigdzie nie zostało. Jedno pole tekstowe pojazdu (cena
i towarzystwo) plus data ostatniej zmiany tekstu robi z tego ciągłość.
Pilnujemy pięciu rzeczy:

1. **Data należy do tekstu** — odświeża się tylko wtedy, gdy zmienił się tekst;
   zapis formularza z poprawioną rejestracją nie robi ze starej oferty
   „zapisanej dziś”, a pusty tekst kasuje i tekst, i datę.
2. **Notatka stoi przy polisie** — na Karcie pojazdu pod terminem OC/AC (z
   okienkiem zmiany, bez niego dla podglądu), w „Ile zostało do…” tylko przy
   OC i AC, w panelu powiadomień i na kaflu „Termin”; zmiana notatki nie
   zapala odznaki dzwonka.
3. **Formularz nie nadpisuje cudzej zmiany** — pole nietknięte w formularzu nie
   jedzie do bazy, więc zmiana z Karty pojazdu albo z synchronizacji przeżywa
   zapis formularza.
4. **Synchronizacja karty pojazdu** — dwie nowe kolumny jadą do drugiej osoby,
   a pierwsza synchronizacja PO aktualizacji niczego nie wysyła i nie nadpisuje
   zmian, które druga osoba zdążyła zrobić (hash sprzed dołożenia kolumn).
5. **Migracja i kosz** — wersja 47 dokłada kolumny bez ruszania danych, a pojazd
   przeniesiony do kosza i przywrócony zachowuje notatkę razem z datą.
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
from sync import pobieranie as sync_pobieranie
from sync import wysylanie as sync_wysylanie

POLA_DZIECI = ("controls", "content", "items", "actions", "leading", "trailing", "title", "subtitle")
DRABINKA = probki_baz.wczytaj_drabinke()
DZIS = date(2026, 10, 3)
NOTATKA = "Warta — 1 240 zł (OC + AC)"


# ============================================================================
#  POMOCNIKI
# ============================================================================

def dzien(dni):
    return (date.today() + timedelta(days=dni)).strftime("%d.%m.%Y")


def auto(nazwa="Skoda Octavia", **pola):
    kolumny = {"nazwa": nazwa, "marka": "Skoda", "model": "Octavia", "typ_paliwa": "Benzyna",
               "status": db.STATUS_POJAZDU_AKTYWNY, "rola_wspoldzielenia": db.ROLA_WLASCICIEL}
    kolumny.update(pola)
    with db.polacz_baze() as conn:
        kursor = conn.execute(
            f"INSERT INTO samochody ({', '.join(kolumny)}) VALUES ({', '.join('?' for _ in kolumny)})",
            list(kolumny.values()))
        return kursor.lastrowid


def jeden(zapytanie, *parametry):
    with db.polacz_baze() as conn:
        return conn.execute(zapytanie, parametry).fetchone()


def oferta_w_bazie(auto_id):
    return tuple(jeden("SELECT oferta_oc_ac, oferta_oc_ac_data FROM samochody WHERE id=?", auto_id))


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


def widok_pojazdu(auto_id, stan=None):
    stan = stan or pomoce.stan_aplikacji(auto_id, "Skoda Octavia")
    return pomoce.zbuduj_widok(pomoce.klasy_widokow()["PojazdView"], pomoce.zbuduj_strone(), stan)


def przycisk_zmiany(widok):
    return [b for b in _wszystkie(widok, ft.IconButton) if b.tooltip == "Zmień notatkę"]


# ============================================================================
#  1. TEKST I DATA
# ============================================================================

def test_nowy_tekst_dostaje_dzisiejsza_date():
    assert db.ustal_oferte_oc_ac(NOTATKA, None, None, DZIS) == (NOTATKA, "03.10.2026")


def test_ten_sam_tekst_zachowuje_date_nawet_z_innymi_odstepami():
    assert db.ustal_oferte_oc_ac(f"  {NOTATKA}\n", NOTATKA, "01.09.2025", DZIS) == (NOTATKA, "01.09.2025")


def test_zmiana_tekstu_odswieza_date():
    assert db.ustal_oferte_oc_ac("Link4 — 980 zł", NOTATKA, "01.09.2025", DZIS) == ("Link4 — 980 zł", "03.10.2026")


def test_pusty_tekst_kasuje_tekst_i_date():
    assert db.ustal_oferte_oc_ac("  \n ", NOTATKA, "01.09.2025", DZIS) == (None, None)
    assert db.ustal_oferte_oc_ac(None, None, None, DZIS) == (None, None)


def test_tekst_ponad_limit_jest_ucinany():
    tekst, _ = db.ustal_oferte_oc_ac("x" * (db.MAKS_DLUGOSC_OFERTY_OC_AC + 50), None, None, DZIS)
    assert len(tekst) == db.MAKS_DLUGOSC_OFERTY_OC_AC


def test_jedna_linia_skleja_wiersze_i_ucina_nadmiar():
    assert db.oferta_w_jednej_linii("  Warta \n\n 1 240   zł \n") == "Warta · 1 240 zł"
    assert db.oferta_w_jednej_linii(None) == "" and db.oferta_w_jednej_linii("  \n ") == ""
    dluga = db.oferta_w_jednej_linii("a" * 500, limit=40)
    assert len(dluga) == 40 and dluga.endswith("…")


def test_zdanie_ma_etykiete_i_date_zapisu():
    assert db.zdanie_oferty_oc_ac("Warta", "03.10.2026") == "Najlepsza oferta OC/AC: Warta · zapisano 03.10.2026"
    assert db.zdanie_oferty_oc_ac("Warta") == "Najlepsza oferta OC/AC: Warta"
    assert db.zdanie_oferty_oc_ac("  ", "03.10.2026") == ""


def test_zapis_z_karty_zmienia_date_tylko_z_trescia(baza):
    auto_id = auto()
    assert oferta_w_bazie(auto_id) == (None, None)

    assert db.zapisz_oferte_oc_ac(auto_id, NOTATKA, DZIS) is True
    assert oferta_w_bazie(auto_id) == (NOTATKA, "03.10.2026")

    assert db.zapisz_oferte_oc_ac(auto_id, f" {NOTATKA} ", date(2026, 11, 1)) is False, "ta sama treść"
    assert oferta_w_bazie(auto_id) == (NOTATKA, "03.10.2026")

    assert db.zapisz_oferte_oc_ac(auto_id, "Link4 — 980 zł", date(2026, 11, 1)) is True
    assert oferta_w_bazie(auto_id) == ("Link4 — 980 zł", "01.11.2026")

    assert db.zapisz_oferte_oc_ac(auto_id, "") is True
    assert oferta_w_bazie(auto_id) == (None, None)
    assert db.zapisz_oferte_oc_ac(auto_id, "") is False, "pusta po pustej niczego nie zmienia"
    assert db.zapisz_oferte_oc_ac(None, NOTATKA) is False and db.zapisz_oferte_oc_ac(99999, NOTATKA) is False


def test_oferta_pojazdu_niesie_tekst_linie_date_i_zdanie(baza):
    auto_id = auto()
    assert db.oferta_oc_ac_pojazdu(db.pobierz_dane_pojazdu(auto_id)) is None
    assert db.oferta_oc_ac_pojazdu(None) is None

    db.zapisz_oferte_oc_ac(auto_id, "Warta\n1 240 zł", DZIS)
    oferta = db.oferta_oc_ac_pojazdu(db.pobierz_dane_pojazdu(auto_id))
    assert oferta == {"tekst": "Warta\n1 240 zł", "linia": "Warta · 1 240 zł", "data": "03.10.2026",
                      "zdanie": "Najlepsza oferta OC/AC: Warta · 1 240 zł · zapisano 03.10.2026"}


# ============================================================================
#  2. FORMULARZ POJAZDU
# ============================================================================

@pytest.fixture
def zapis_formularza(monkeypatch):
    """Zapis formularza bez nawigacji, okienek i sieci; zbiera komunikaty."""
    komunikaty = []
    monkeypatch.setattr(utils, "przejdz", lambda strona, trasa: None)
    monkeypatch.setattr(utils, "pokaz_komunikat", lambda strona, tekst, *a, **k: komunikaty.append(tekst))
    monkeypatch.setattr(utils, "wypchnij_w_tle", lambda strona, auto_id, powod="zapis": None)
    return komunikaty


def formularz(auto_id):
    stan = pomoce.stan_aplikacji(auto_id, "Skoda Octavia")
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["FormularzAutoView"], pomoce.zbuduj_strone(), stan,
                                {"auto_id": auto_id})
    widok._zaproponuj_podzespoly_po_zmianie_napedu = lambda: None
    return widok


def test_formularz_pokazuje_notatke_i_date_zapisu(baza):
    auto_id = auto()
    db.zapisz_oferte_oc_ac(auto_id, NOTATKA, date(2025, 9, 1))

    widok = formularz(auto_id)

    assert widok.e_oferta.value == NOTATKA and widok.e_oferta.label == "Najlepsza oferta OC/AC"
    assert widok.e_oferta.max_length == db.MAKS_DLUGOSC_OFERTY_OC_AC
    assert widok.info_oferta.visible and widok.info_oferta.value == "Zapisano 01.09.2025"


def test_formularz_bez_notatki_nie_pokazuje_daty(baza):
    widok = formularz(auto())
    assert widok.e_oferta.value == "" and not widok.info_oferta.visible


def test_notatka_wchodzi_do_wykrywania_niezapisanych_zmian(baza):
    widok = formularz(auto())
    assert not widok._czy_zmieniono()
    widok.e_oferta.value = NOTATKA
    assert widok._czy_zmieniono()


def test_formularz_zapisuje_notatke_z_dzisiejsza_data(baza, zapis_formularza):
    auto_id = auto()
    widok = formularz(auto_id)
    widok.e_oferta.value = f"  {NOTATKA} "

    widok.zapisz(None)

    assert zapis_formularza == ["Zapisano pojazd!"]
    assert oferta_w_bazie(auto_id) == (NOTATKA, date.today().strftime("%d.%m.%Y"))


def test_formularz_nie_odswieza_daty_gdy_pola_nie_ruszono(baza, zapis_formularza):
    auto_id = auto()
    db.zapisz_oferte_oc_ac(auto_id, NOTATKA, date(2025, 9, 1))
    widok = formularz(auto_id)
    widok.e_rej.value = "WX 12345"

    widok.zapisz(None)

    assert zapis_formularza == ["Zapisano pojazd!"]
    assert jeden("SELECT nr_rej FROM samochody WHERE id=?", auto_id)[0] == "WX 12345"
    assert oferta_w_bazie(auto_id) == (NOTATKA, "01.09.2025")


def test_formularz_nie_nadpisuje_notatki_zmienionej_w_miedzyczasie(baza, zapis_formularza):
    """Formularz otwarty ze starą notatką, a w międzyczasie nowa przyszła z Karty
    pojazdu albo z synchronizacji: zapis innego pola jej nie cofa."""
    auto_id = auto()
    db.zapisz_oferte_oc_ac(auto_id, NOTATKA, date(2025, 9, 1))
    widok = formularz(auto_id)
    db.zapisz_oferte_oc_ac(auto_id, "Link4 — 980 zł", DZIS)
    widok.e_rej.value = "WX 12345"

    widok.zapisz(None)

    assert oferta_w_bazie(auto_id) == ("Link4 — 980 zł", "03.10.2026")


def test_formularz_kasuje_notatke_razem_z_data(baza, zapis_formularza):
    auto_id = auto()
    db.zapisz_oferte_oc_ac(auto_id, NOTATKA, date(2025, 9, 1))
    widok = formularz(auto_id)
    widok.e_oferta.value = ""

    widok.zapisz(None)

    assert oferta_w_bazie(auto_id) == (None, None)


def test_formularz_nowego_pojazdu_zapisuje_notatke(baza, zapis_formularza):
    widok = formularz(None)
    widok.e_marka.value, widok.e_model.value = "Skoda", "Fabia"
    widok.e_oferta.value = NOTATKA

    widok.zapisz(None)

    assert zapis_formularza == ["Zapisano pojazd!"]
    assert jeden("SELECT oferta_oc_ac, oferta_oc_ac_data FROM samochody WHERE nazwa='Skoda Fabia'") == (
        NOTATKA, date.today().strftime("%d.%m.%Y"))


# ============================================================================
#  3. KARTA POJAZDU
# ============================================================================

def test_karta_stawia_notatke_tuz_pod_terminem_polisy(baza):
    auto_id = auto(oc_data=dzien(10), przeglad_data=dzien(25))
    db.zapisz_oferte_oc_ac(auto_id, NOTATKA, date(2025, 9, 1))

    tresc = teksty(widok_pojazdu(auto_id))

    assert tresc.index("Polisa OC") < tresc.index("Najlepsza oferta OC/AC") < tresc.index("Przegląd techniczny")
    assert NOTATKA in tresc and "Zapisano 01.09.2025" in tresc


def test_notatka_stoi_pod_pierwsza_polisa_a_nie_pod_kazda(baza):
    auto_id = auto(oc_data=dzien(10), ac_data=dzien(40))
    db.zapisz_oferte_oc_ac(auto_id, NOTATKA, DZIS)

    assert teksty(widok_pojazdu(auto_id)).count("Najlepsza oferta OC/AC") == 1


def test_notatka_nie_znika_razem_z_datami_polis(baza):
    auto_id = auto(przeglad_data=dzien(25))
    db.zapisz_oferte_oc_ac(auto_id, NOTATKA, DZIS)
    assert NOTATKA in teksty(widok_pojazdu(auto_id))

    bez_dat = auto("Bez dat")
    db.zapisz_oferte_oc_ac(bez_dat, "Link4 — 980 zł", DZIS)
    assert "Link4 — 980 zł" in teksty(widok_pojazdu(bez_dat, pomoce.stan_aplikacji(bez_dat, "Bez dat")))


def test_bez_notatki_zacheta_jest_tylko_przy_polisie(baza):
    z_polisa = auto(oc_data=dzien(100))
    bez_polisy = auto("Bez polisy", przeglad_data=dzien(100))

    assert "Zapisz najlepszą ofertę OC/AC" in teksty(widok_pojazdu(z_polisa))
    assert "Zapisz najlepszą ofertę OC/AC" not in teksty(
        widok_pojazdu(bez_polisy, pomoce.stan_aplikacji(bez_polisy, "Bez polisy")))


def test_podglad_czyta_notatke_ale_nie_ma_jak_jej_zmienic(baza):
    stan, ids = pomoce.przygotuj_scenariusz("wspoldzielony_podglad")
    with db.polacz_baze() as conn:
        conn.execute("UPDATE samochody SET oc_data=? WHERE id=?", (dzien(10), stan.auto_id))
    db.zapisz_oferte_oc_ac(stan.auto_id, NOTATKA, DZIS)

    widok = widok_pojazdu(stan.auto_id, stan)

    assert NOTATKA in teksty(widok) and przycisk_zmiany(widok) == []
    db.zapisz_oferte_oc_ac(stan.auto_id, "")
    assert "Zapisz najlepszą ofertę OC/AC" not in teksty(widok_pojazdu(stan.auto_id, stan))


def test_okienko_zapisuje_notatke_wypycha_ja_i_odswieza_karte(baza, monkeypatch):
    auto_id = auto(oc_data=dzien(10))
    db.zapisz_oferte_oc_ac(auto_id, NOTATKA, date(2025, 9, 1))
    widok = widok_pojazdu(auto_id)

    otwarte, zamkniete, wypchniete, odswiezone, komunikaty = [], [], [], [], []
    monkeypatch.setattr(utils, "otworz_dialog", lambda strona, dlg: otwarte.append(dlg))
    monkeypatch.setattr(utils, "zamknij_dialog", lambda strona, dlg: zamkniete.append(dlg))
    monkeypatch.setattr(utils, "wypchnij_w_tle", lambda strona, a_id, powod="zapis": wypchniete.append((a_id, powod)))
    monkeypatch.setattr(utils, "odswiez_ekran", lambda strona: odswiezone.append(True))
    monkeypatch.setattr(utils, "pokaz_komunikat", lambda strona, tekst, *a, **k: komunikaty.append(tekst))

    (przycisk,) = przycisk_zmiany(widok)
    przycisk.on_click(None)
    (okno,) = otwarte
    (pole,) = _wszystkie(okno, ft.TextField)
    assert pole.value == NOTATKA

    pole.value = "Link4 — 980 zł"
    (zapisz,) = [b for b in okno.actions if getattr(b, "content", None) == "Zapisz"]
    zapisz.on_click(None)

    assert oferta_w_bazie(auto_id) == ("Link4 — 980 zł", date.today().strftime("%d.%m.%Y"))
    assert zamkniete == [okno] and wypchniete == [(auto_id, "oferta")] and odswiezone == [True]
    assert komunikaty == ["Zapisano notatkę o ofercie OC/AC"]


def test_okienko_z_ta_sama_trescia_niczego_nie_wypycha(baza, monkeypatch):
    auto_id = auto(oc_data=dzien(10))
    db.zapisz_oferte_oc_ac(auto_id, NOTATKA, date(2025, 9, 1))
    widok = widok_pojazdu(auto_id)
    otwarte, wypchniete = [], []
    monkeypatch.setattr(utils, "otworz_dialog", lambda strona, dlg: otwarte.append(dlg))
    monkeypatch.setattr(utils, "zamknij_dialog", lambda strona, dlg: None)
    monkeypatch.setattr(utils, "wypchnij_w_tle", lambda *a, **k: wypchniete.append(a))
    monkeypatch.setattr(utils, "odswiez_ekran", lambda strona: wypchniete.append("odswiez"))

    widok._edytuj_oferte()
    (zapisz,) = [b for b in otwarte[0].actions if getattr(b, "content", None) == "Zapisz"]
    zapisz.on_click(None)

    assert wypchniete == [] and oferta_w_bazie(auto_id) == (NOTATKA, "01.09.2025")


def test_odswiezenie_w_miejscu_pokazuje_nowa_notatke(baza, monkeypatch):
    auto_id = auto(oc_data=dzien(10))
    widok = widok_pojazdu(auto_id)
    assert NOTATKA not in teksty(widok)
    monkeypatch.setattr(type(widok), "update", lambda self: None)

    db.zapisz_oferte_oc_ac(auto_id, NOTATKA, DZIS)
    widok.odswiez_w_miejscu()

    assert NOTATKA in teksty(widok) and "Zapisano 03.10.2026" in teksty(widok)
    assert not widok.scena.wlaczona, "paski nie grają od nowa przy zmianie notatki"


# ============================================================================
#  4. „ILE ZOSTAŁO DO…” I POWIADOMIENIA
# ============================================================================

def test_odliczania_niosa_notatke_tylko_przy_oc_i_ac(baza):
    auto_id = auto(oc_data=dzien(10), ac_data=dzien(40), przeglad_data=dzien(20))
    db.zapisz_oferte_oc_ac(auto_id, NOTATKA, date(2025, 9, 1))

    pozycje = {p["klucz"]: p for p in db.odliczania_pojazdu(auto_id)}

    zdanie = "Najlepsza oferta OC/AC: Warta — 1 240 zł (OC + AC) · zapisano 01.09.2025"
    assert pozycje["dokument:oc"]["opis_oferty"] == zdanie
    assert pozycje["dokument:ac"]["opis_oferty"] == zdanie
    assert pozycje["dokument:przeglad"]["opis_oferty"] is None


def test_odliczania_bez_notatki_nie_maja_dopiska(baza):
    auto_id = auto(oc_data=dzien(10))
    assert all(p["opis_oferty"] is None for p in db.odliczania_pojazdu(auto_id))


def test_ekran_odliczan_pokazuje_notatke_pod_oc(baza):
    auto_id = auto(oc_data=dzien(10), przeglad_data=dzien(20))
    db.zapisz_oferte_oc_ac(auto_id, NOTATKA, date(2025, 9, 1))
    stan = pomoce.stan_aplikacji(auto_id, "Skoda Octavia")

    tresc = teksty(pomoce.zbuduj_widok(pomoce.klasy_widokow()["OdliczaniaView"], pomoce.zbuduj_strone(), stan))

    assert tresc.count("Najlepsza oferta OC/AC: Warta — 1 240 zł (OC + AC) · zapisano 01.09.2025") == 1
    assert tresc.index("Polisa OC") < tresc.index("Najlepsza oferta OC/AC: Warta — 1 240 zł (OC + AC) · zapisano 01.09.2025") \
        < tresc.index("Przegląd techniczny")


def powiadomienie(auto_id, klucz):
    (p,) = [p for p in db.pobierz_powiadomienia(auto_id, pomin_wyciszone=False) if p["klucz"] == klucz]
    return p


def test_powiadomienie_o_polisie_niesie_notatke(baza):
    auto_id = auto(oc_data=dzien(10), przeglad_data=dzien(10))
    db.zapisz_oferte_oc_ac(auto_id, "Warta\n1 240 zł", date(2025, 9, 1))

    oc = powiadomienie(auto_id, "dokument:oc")
    assert oc["oferta"] == "Warta · 1 240 zł"
    assert oc["opis_oferty"] == "Najlepsza oferta OC/AC: Warta · 1 240 zł · zapisano 01.09.2025"
    przeglad = powiadomienie(auto_id, "dokument:przeglad")
    assert "oferta" not in przeglad and "opis_oferty" not in przeglad


def test_powiadomienie_bez_notatki_jej_nie_ma(baza):
    auto_id = auto(oc_data=dzien(10))
    assert "oferta" not in powiadomienie(auto_id, "dokument:oc")


def test_zmiana_notatki_nie_robi_z_powiadomienia_nowego_ani_nie_czeka_na_zapis(baza):
    """Sygnatura „widziane” to status. A notatka z Karty pojazdu ma być w
    powiadomieniu od razu, mimo pamięci metryk — zapis unieważnia ją sam."""
    auto_id = auto(oc_data=dzien(10))
    db.oznacz_powiadomienia_jako_widziane(auto_id, db.pobierz_powiadomienia(auto_id))

    db.zapisz_oferte_oc_ac(auto_id, NOTATKA, DZIS)

    powiadomienia = db.pobierz_powiadomienia(auto_id)
    assert powiadomienie(auto_id, "dokument:oc")["oferta"] == NOTATKA
    assert db.niewidziane_powiadomienia(powiadomienia, db.pobierz_widziane_powiadomienia(auto_id)) == []


def test_panel_powiadomien_stawia_notatke_pod_terminem(baza, monkeypatch):
    auto_id = auto(oc_data=dzien(10))
    db.zapisz_oferte_oc_ac(auto_id, NOTATKA, date(2025, 9, 1))
    otwarte = []
    monkeypatch.setattr(utils.powiadomienia, "otworz_dno", lambda strona, arkusz: otwarte.append(arkusz))

    utils.pokaz_panel_powiadomien(pomoce.zbuduj_strone().page, pomoce.stan_aplikacji(auto_id, "Skoda Octavia"))

    (kafel,) = [k for k in _wszystkie(otwarte[0].content.content, ft.ListTile)
                if k.title is not None and "Polisa OC" in teksty(k.title)]
    opis, oferta = teksty(kafel.subtitle)
    assert opis.startswith("Zostało 10 dni")
    assert oferta == "Najlepsza oferta OC/AC: Warta — 1 240 zł (OC + AC) · zapisano 01.09.2025"


def test_kafel_termin_pokazuje_jedna_linie_oferty(baza):
    auto_id = auto(oc_data=dzien(10))
    db.zapisz_oferte_oc_ac(auto_id, "Warta\n1 240 zł", DZIS)
    db.zapisz_widgety_kokpitu(["termin"], auto_id)
    stan = pomoce.stan_aplikacji(auto_id, "Skoda Octavia")
    stan.zakladka = 0

    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(), stan)
    tresc = teksty(widok.kokpit_kontener)

    assert "Polisa OC" in tresc and "Oferta: Warta · 1 240 zł" in tresc


def test_kafel_termin_bez_notatki_nie_ma_linii_oferty(baza):
    auto_id = auto(oc_data=dzien(10))
    db.zapisz_widgety_kokpitu(["termin"], auto_id)
    stan = pomoce.stan_aplikacji(auto_id, "Skoda Octavia")
    stan.zakladka = 0

    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(), stan)

    assert not any(t.startswith("Oferta:") for t in teksty(widok.kokpit_kontener))


# ============================================================================
#  5. SYNCHRONIZACJA KARTY POJAZDU
# ============================================================================

class _Odpowiedz:
    def __init__(self, data=None):
        self.data = data


class ChmuraKarty:
    """Supabase na tyle, na ile potrzebuje go `_synchronizuj_info_pojazdu`:
    jeden rekord `info_pojazdu` i wywołania, które do niego trafiły."""

    def __init__(self, dane):
        self.rekord = {"id": "info-1", "dane": dict(dane)}
        self.wywolania = []

    def table(self, _nazwa):
        chmura = self

        class _Zapytanie:
            def select(self, *_):
                return self

            def eq(self, *_):
                return self

            def execute(self):
                return _Odpowiedz([chmura.rekord])
        return _Zapytanie()

    def rpc(self, nazwa, parametry):
        chmura = self

        class _Wywolanie:
            def execute(self):
                chmura.wywolania.append((nazwa, parametry))
                if nazwa == "aktualizuj_zdalny_rekord":
                    chmura.rekord["dane"] = dict(parametry["p_dane"])
                return _Odpowiedz("info-1")
        return _Wywolanie()


def karta(auto_id):
    with db.polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        w = conn.execute(f"SELECT {', '.join(sync.KOLUMNY_POJAZDU)} FROM samochody WHERE id=?", (auto_id,)).fetchone()
    return {k: w[k] for k in sync.KOLUMNY_POJAZDU}


def sprzed_aktualizacji(dane):
    """Karta tak, jak zapamiętała ją wersja aplikacji bez notatki."""
    return {k: v for k, v in dane.items() if k not in sync.KOLUMNY_POJAZDU_DOPISANE}


def pojazd_zsynchronizowany_starsza_wersja(**pola):
    auto_id = auto(**pola)
    stara = sprzed_aktualizacji(karta(auto_id))
    with db.polacz_baze() as conn:
        conn.execute("UPDATE samochody SET info_zdalne_id='info-1', zdalny_hash_info=? WHERE id=?",
                     (sync_wysylanie._hash_zawartosci(stara), auto_id))
    return auto_id, stara


def synchronizuj(chmura, auto_id):
    return sync_pobieranie._synchronizuj_info_pojazdu(chmura, "wspolny", auto_id)


def test_notatka_jedzie_do_chmury_jako_kolumny_pojazdu():
    assert {"oferta_oc_ac", "oferta_oc_ac_data"} <= set(sync.KOLUMNY_POJAZDU)
    assert set(sync.KOLUMNY_POJAZDU_DOPISANE) <= set(sync.KOLUMNY_POJAZDU)


def test_pierwsza_synchronizacja_po_aktualizacji_niczego_nie_wysyla(baza):
    auto_id, stara = pojazd_zsynchronizowany_starsza_wersja(wiadomosc_statusu="Odebrany z myjni")
    chmura = ChmuraKarty(stara)

    assert synchronizuj(chmura, auto_id) == (0, 0)

    assert chmura.wywolania == []
    assert jeden("SELECT zdalny_hash_info FROM samochody WHERE id=?", auto_id)[0] == \
        sync_wysylanie._hash_zawartosci(karta(auto_id)), "zapamiętany hash przechodzi na nowy układ kluczy"
    assert synchronizuj(chmura, auto_id) == (0, 0) and chmura.wywolania == []


def test_zmiana_drugiej_osoby_przezywa_pierwsza_synchronizacje_po_aktualizacji(baza):
    """Sedno zabezpieczenia: telefon po aktualizacji nie ma lokalnych zmian, więc
    NIE wysyła swojej karty nad tą, którą druga osoba zdążyła zmienić."""
    auto_id, stara = pojazd_zsynchronizowany_starsza_wersja(wiadomosc_statusu="Odebrany z myjni")
    chmura = ChmuraKarty({**stara, "wiadomosc_statusu": "Zatankowany do pełna"})

    assert synchronizuj(chmura, auto_id) == (0, 1)

    assert chmura.wywolania == []
    assert jeden("SELECT wiadomosc_statusu FROM samochody WHERE id=?", auto_id)[0] == "Zatankowany do pełna"


def test_notatka_z_telefonu_zaktualizowanego_wczesniej_dojezdza(baza):
    auto_id, stara = pojazd_zsynchronizowany_starsza_wersja()
    chmura = ChmuraKarty({**stara, "oferta_oc_ac": "Link4 — 980 zł", "oferta_oc_ac_data": "02.10.2026"})

    assert synchronizuj(chmura, auto_id) == (0, 1)

    assert chmura.wywolania == []
    assert oferta_w_bazie(auto_id) == ("Link4 — 980 zł", "02.10.2026")


def test_wpisana_notatka_jedzie_do_chmury(baza):
    auto_id, stara = pojazd_zsynchronizowany_starsza_wersja()
    chmura = ChmuraKarty(stara)
    db.zapisz_oferte_oc_ac(auto_id, NOTATKA, DZIS)

    assert synchronizuj(chmura, auto_id) == (1, 0)

    assert [nazwa for nazwa, _ in chmura.wywolania] == ["aktualizuj_zdalny_rekord"]
    assert (chmura.rekord["dane"]["oferta_oc_ac"], chmura.rekord["dane"]["oferta_oc_ac_data"]) == (NOTATKA, "03.10.2026")
    assert synchronizuj(chmura, auto_id) == (0, 0), "po wysłaniu karty są zgodne"


def test_inna_zmiana_lokalna_jedzie_mimo_pustej_notatki(baza):
    """Tolerancja dotyczy tylko PUSTYCH kolumn dołożonych: prawdziwa lokalna
    zmiana (tu: status) nadal wygrywa i jedzie do chmury."""
    auto_id, stara = pojazd_zsynchronizowany_starsza_wersja(wiadomosc_statusu="Odebrany z myjni")
    chmura = ChmuraKarty(stara)
    with db.polacz_baze() as conn:
        conn.execute("UPDATE samochody SET wiadomosc_statusu='W warsztacie' WHERE id=?", (auto_id,))

    assert synchronizuj(chmura, auto_id) == (1, 0)
    assert chmura.rekord["dane"]["wiadomosc_statusu"] == "W warsztacie"


# ============================================================================
#  6. MIGRACJA I KOSZ
# ============================================================================

def test_migracja_47_dokłada_kolumny_i_nie_rusza_danych(magazyn):
    probki_baz.zbuduj_baze_w_wersji(db.BAZA_DANYCH, 46, DRABINKA)
    conn = sqlite3.connect(db.BAZA_DANYCH)
    conn.execute("INSERT INTO samochody (nazwa, typ_paliwa, oc_data, ubezpieczyciel) "
                 "VALUES ('Stary', 'Benzyna', '10.11.2026', 'PZU')")
    conn.commit()
    conn.close()
    assert not {"oferta_oc_ac", "oferta_oc_ac_data"} & set(pomoce.kolumny("samochody"))

    db.init_db()

    assert {"oferta_oc_ac", "oferta_oc_ac_data"} <= set(pomoce.kolumny("samochody"))
    assert tuple(jeden("SELECT oc_data, ubezpieczyciel, oferta_oc_ac, oferta_oc_ac_data FROM samochody")) == (
        "10.11.2026", "PZU", None, None)


def test_kosz_przenosi_notatke_z_data(baza):
    ids = pomoce.utworz_pojazd("Do kosza")
    db.zapisz_oferte_oc_ac(ids["auto_id"], NOTATKA, date(2025, 9, 1))

    wynik = db.usun_auto_do_kosza(ids["auto_id"])
    assert jeden("SELECT COUNT(*) FROM samochody WHERE nazwa='Do kosza'")[0] == 0
    db.przywroc_auto_z_kosza(wynik["kosz_id"])

    assert tuple(jeden("SELECT oferta_oc_ac, oferta_oc_ac_data FROM samochody WHERE nazwa='Do kosza'")) == (
        NOTATKA, "01.09.2025")
