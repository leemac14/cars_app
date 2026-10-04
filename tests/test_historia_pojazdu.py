"""Przycisk „Sprawdź w CEPiK” na Karcie pojazdu (M-14).

Rządowa Historia Pojazdu (historiapojazdu.gov.pl) znajduje auto po trzech
danych — numerze rejestracyjnym, VIN-ie i dacie pierwszej rejestracji — a schowek
mieści jedną rzecz naraz. Pilnujemy czterech rzeczy:

1. **Dane do wklejenia bez poprawek** — kolejność pól formularza, numer i VIN
   bez odstępów i wielkimi literami, data jako DD.MM.RRRR (także z dawnego
   zapisu ISO), nieczytelna data tak, jak ją wpisano, brak jako pusty napis.
2. **Strona w osobnej przeglądarce** — tryb zewnętrznej aplikacji, bo z karty
   nad aplikacją nie wróci się po kolejną wartość bez utraty formularza; gdy
   przeglądarka się nie otworzy, adres trafia do schowka.
3. **Komplet: pierwszy krok jednym dotknięciem** — numer w schowku, strona
   otwarta, a w okienku wyróżniony VIN; dalej dotknięcie wiersza kopiuje
   i przesuwa wyróżnienie, „Otwórz stronę” bierze następną wartość.
4. **Brak: najpierw okienko** — strona sama się nie otwiera, brakujący wiersz
   ma myślnik i nie kopiuje, „Uzupełnij” prowadzi do formularza (podgląd go nie
   dostaje), a stronę i tak da się otworzyć z okienka.

Do tego: przycisk stoi w Specyfikacji tuż pod „Pierwszą rejestracją”, która
dostała przycisk kopiowania, a podpowiedź o „Wstecz” widać tylko na Androidzie.
"""

import asyncio
import inspect

import flet as ft
import pytest

import audyty
import db
import pomoce
import utils

POLA_DZIECI = ("controls", "content", "actions", "title")
ADRES = "https://historiapojazdu.gov.pl/"
KOMPLET = {"nr_rej": "po 1234a", "vin": "tmbjj7ne5k0123456", "data_pierwszej_rejestracji": "12.03.2019"}


# ============================================================================
#  POMOCNIKI
# ============================================================================

def auto(nazwa="Skoda Octavia", **pola):
    kolumny = {"nazwa": nazwa, "marka": "Skoda", "model": "Octavia", "typ_paliwa": "Benzyna",
               "status": db.STATUS_POJAZDU_AKTYWNY, "rola_wspoldzielenia": db.ROLA_WLASCICIEL}
    kolumny.update(pola)
    with db.polacz_baze() as conn:
        kursor = conn.execute(
            f"INSERT INTO samochody ({', '.join(kolumny)}) VALUES ({', '.join('?' for _ in kolumny)})",
            list(kolumny.values()))
        return kursor.lastrowid


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


def widok_pojazdu(auto_id, strona=None):
    strona = strona or pomoce.zbuduj_strone()
    stan = pomoce.stan_aplikacji(auto_id, "Skoda Octavia")
    return pomoce.zbuduj_widok(pomoce.klasy_widokow()["PojazdView"], strona.page, stan)


def przycisk(korzen, typ, napis):
    (znaleziony,) = [b for b in _wszystkie(korzen, typ) if getattr(b, "content", None) == napis]
    return znaleziony


def przycisk_cepik(widok):
    return przycisk(widok, ft.FilledTonalButton, "Sprawdź w CEPiK")


def wiersz(okno, klucz):
    (znaleziony,) = [c for c in _wszystkie(okno, ft.Container) if c.data == klucz]
    return znaleziony


def stan_wierszy(okno):
    """[(klucz, wartość, stan)] w kolejności okienka. Stan czytany z tego, co
    widać: ptaszek — skopiowana, kopiowanie w kolorze akcentu — następna,
    wyszarzone — czeka, bez ikony i bez dotknięcia — brak."""
    wynik = []
    for c in _wszystkie(okno, ft.Container):
        if c.data not in ("nr_rej", "vin", "data_pierwszej_rejestracji"):
            continue
        ikony = _wszystkie(c, ft.Icon)
        if c.on_click is None and not ikony:
            stan = "brak"
        elif ikony[0].icon == ft.Icons.CHECK_CIRCLE:
            stan = "skopiowana"
        elif ikony[0].color == ft.Colors.PRIMARY:
            stan = "następna"
        else:
            stan = "czeka"
        tekst = teksty(c)[2]   # numer pola, etykieta, wartość
        wynik.append((c.data, "" if tekst == "—" else tekst, stan))
    return wynik


@pytest.fixture
def wyjscia(monkeypatch):
    """Wszystko, co wychodzi poza aplikację albo poza ekran, trafia na listy."""
    zebrane = {"schowek": [], "strony": [], "okna": [], "zamkniete": [], "trasy": []}
    monkeypatch.setattr(utils, "kopiuj_do_schowka",
                        lambda strona, wartosc, komunikat="": zebrane["schowek"].append(wartosc))
    monkeypatch.setattr(utils, "otworz_strone", lambda strona, adres: zebrane["strony"].append(adres))
    monkeypatch.setattr(utils, "otworz_dialog", lambda strona, dlg: zebrane["okna"].append(dlg))
    monkeypatch.setattr(utils, "zamknij_dialog", lambda strona, dlg: zebrane["zamkniete"].append(dlg))
    monkeypatch.setattr(utils, "przejdz", lambda strona, trasa: zebrane["trasy"].append(trasa))
    # Okienko poza stroną testową nie ma sesji — odświeżenie listy wierszy
    # sprawdzamy po jej zawartości, nie po wysłaniu do klienta.
    monkeypatch.setattr(ft.Column, "update", lambda self, *a, **k: None)
    return zebrane


# ============================================================================
#  1. DANE DO WKLEJENIA
# ============================================================================

def test_trzy_dane_w_kolejnosci_formularza_i_postaci_do_wklejenia():
    pola = db.pola_historii_pojazdu({"nr_rej": " po 1234a ", "vin": "tmbjj7ne5k 0123456",
                                     "data_pierwszej_rejestracji": "12.03.2019"})
    assert [(p["klucz"], p["etykieta"], p["wartosc"]) for p in pola] == [
        ("nr_rej", "Numer rejestracyjny", "PO1234A"),
        ("vin", "VIN", "TMBJJ7NE5K0123456"),
        ("data_pierwszej_rejestracji", "Data pierwszej rejestracji", "12.03.2019"),
    ]


@pytest.mark.parametrize("zapisana, do_wklejenia", [
    ("2019-03-12", "12.03.2019"),      # dawny zapis ISO
    ("12/03/2019", "12.03.2019"),
    (" 12.03.2019 ", "12.03.2019"),
    ("marzec 2019", "marzec 2019"),    # nieczytelna — tak, jak ją wpisano
    (None, ""),
    ("  ", ""),
])
def test_data_jako_dd_mm_rrrr(zapisana, do_wklejenia):
    pola = db.pola_historii_pojazdu({"data_pierwszej_rejestracji": zapisana})
    assert pola[2]["wartosc"] == do_wklejenia


def test_brak_danych_to_puste_napisy():
    assert [p["wartosc"] for p in db.pola_historii_pojazdu(None)] == ["", "", ""]
    assert [p["wartosc"] for p in db.pola_historii_pojazdu({"nr_rej": None, "vin": ""})] == ["", "", ""]


# ============================================================================
#  2. STRONA W OSOBNEJ PRZEGLĄDARCE
# ============================================================================

class _Strona:
    """Tyle strony, ile potrzebuje otworz_strone: run_task."""

    def __init__(self, bez_petli=False):
        self.bez_petli = bez_petli

    def run_task(self, zadanie):
        if self.bez_petli:
            raise RuntimeError("strona bez pętli zdarzeń")
        asyncio.run(zadanie())


def _uruchamiacz(otwarte, blad=False):
    class Uruchamiacz:
        async def launch_url(self, url, *, mode=None, **_):
            if blad:
                raise RuntimeError("brak przeglądarki")
            otwarte.append((url, mode))

    return Uruchamiacz


def test_strona_otwiera_sie_w_zewnetrznej_przegladarce(monkeypatch):
    otwarte, skopiowane = [], []
    monkeypatch.setattr(ft, "UrlLauncher", _uruchamiacz(otwarte))
    monkeypatch.setattr(utils.system, "kopiuj_do_schowka",
                        lambda strona, wartosc, komunikat="": skopiowane.append(wartosc))

    utils.otworz_strone(_Strona(), db.ADRES_HISTORII_POJAZDU)

    assert db.ADRES_HISTORII_POJAZDU == ADRES
    assert otwarte == [(ADRES, ft.LaunchMode.EXTERNAL_APPLICATION)] and skopiowane == []


def test_bez_przegladarki_adres_trafia_do_schowka(monkeypatch):
    otwarte, skopiowane = [], []
    monkeypatch.setattr(ft, "UrlLauncher", _uruchamiacz(otwarte, blad=True))
    monkeypatch.setattr(utils.system, "kopiuj_do_schowka",
                        lambda strona, wartosc, komunikat="": skopiowane.append((wartosc, komunikat)))

    utils.otworz_strone(_Strona(), ADRES)
    utils.otworz_strone(_Strona(bez_petli=True), ADRES)
    utils.otworz_strone(_Strona(), "")

    assert otwarte == []
    assert skopiowane == [(ADRES, "Nie udało się otworzyć przeglądarki — adres w schowku"),
                          (ADRES, "Adres skopiowany do schowka")]


def test_flet_wciaz_ma_tryb_zewnetrznej_aplikacji():
    """Podmiana w testach wyżej ukryłaby zmianę API — ten test patrzy na prawdziwego Fleta."""
    assert "mode" in inspect.signature(ft.UrlLauncher.launch_url).parameters
    assert ft.LaunchMode.EXTERNAL_APPLICATION.value == "externalApplication"


# ============================================================================
#  3. KOMPLET — PIERWSZY KROK JEDNYM DOTKNIĘCIEM
# ============================================================================

def test_komplet_kopiuje_numer_otwiera_strone_i_wyroznia_vin(baza, wyjscia):
    przycisk_cepik(widok_pojazdu(auto(**KOMPLET))).on_click(None)

    (okno,) = wyjscia["okna"]
    assert wyjscia["schowek"] == ["PO1234A"] and wyjscia["strony"] == [ADRES]
    assert stan_wierszy(okno) == [
        ("nr_rej", "PO1234A", "skopiowana"),
        ("vin", "TMBJJ7NE5K0123456", "następna"),
        ("data_pierwszej_rejestracji", "12.03.2019", "czeka"),
    ]
    assert "Bez kompletu strona nie znajdzie auta." not in teksty(okno)
    assert audyty.znajdz_expand_bez_ograniczenia(okno) == []
    assert audyty.znajdz_expand_w_kontenerze(okno) == []
    assert audyty.znajdz_pogrubienia_na_drugim_planie(okno) == []


def test_dotkniecie_wiersza_kopiuje_i_przesuwa_wyroznienie(baza, wyjscia):
    przycisk_cepik(widok_pojazdu(auto(**KOMPLET))).on_click(None)
    (okno,) = wyjscia["okna"]

    wiersz(okno, "vin").on_click(None)
    assert wyjscia["schowek"][-1] == "TMBJJ7NE5K0123456"
    assert [s for _, _, s in stan_wierszy(okno)] == ["skopiowana", "skopiowana", "następna"]

    # Skopiowaną wartość da się wziąć jeszcze raz — schowek mógł się nadpisać.
    wiersz(okno, "nr_rej").on_click(None)
    assert wyjscia["schowek"][-1] == "PO1234A"
    assert wyjscia["strony"] == [ADRES], "dotknięcie wiersza samo strony nie otwiera"


def test_otworz_strone_bierze_nastepna_wartosc(baza, wyjscia):
    przycisk_cepik(widok_pojazdu(auto(**KOMPLET))).on_click(None)
    (okno,) = wyjscia["okna"]
    otworz = przycisk(okno, ft.Button, "Otwórz stronę")

    otworz.on_click(None)
    assert wyjscia["schowek"] == ["PO1234A", "TMBJJ7NE5K0123456"] and wyjscia["strony"] == [ADRES] * 2

    otworz.on_click(None)
    otworz.on_click(None)   # wszystko skopiowane — już tylko otwiera
    assert wyjscia["schowek"] == ["PO1234A", "TMBJJ7NE5K0123456", "12.03.2019"]
    assert wyjscia["strony"] == [ADRES] * 4
    assert [s for _, _, s in stan_wierszy(okno)] == ["skopiowana"] * 3


def test_zamknij_zamyka_okienko(baza, wyjscia):
    przycisk_cepik(widok_pojazdu(auto(**KOMPLET))).on_click(None)
    (okno,) = wyjscia["okna"]
    przycisk(okno, ft.TextButton, "Zamknij").on_click(None)
    assert wyjscia["zamkniete"] == [okno]


# ============================================================================
#  4. BRAK — NAJPIERW OKIENKO
# ============================================================================

def test_brak_daty_okienko_bez_otwierania_strony(baza, wyjscia):
    auto_id = auto(nr_rej="PO 1234A", vin="TMBJJ7NE5K0123456")
    przycisk_cepik(widok_pojazdu(auto_id)).on_click(None)

    (okno,) = wyjscia["okna"]
    assert wyjscia["schowek"] == [] and wyjscia["strony"] == []
    assert stan_wierszy(okno) == [
        ("nr_rej", "PO1234A", "następna"),
        ("vin", "TMBJJ7NE5K0123456", "czeka"),
        ("data_pierwszej_rejestracji", "", "brak"),
    ]
    assert "brak w danych pojazdu" in teksty(okno)
    assert "Bez kompletu strona nie znajdzie auta." in teksty(okno)

    przycisk(okno, ft.TextButton, "Uzupełnij").on_click(None)
    assert wyjscia["zamkniete"] == [okno] and wyjscia["trasy"] == [f"/auto/edytuj/{auto_id}"]


def test_strone_i_tak_da_sie_otworzyc_z_okienka(baza, wyjscia):
    przycisk_cepik(widok_pojazdu(auto(vin="TMBJJ7NE5K0123456"))).on_click(None)
    (okno,) = wyjscia["okna"]

    przycisk(okno, ft.Button, "Otwórz stronę").on_click(None)

    assert wyjscia["schowek"] == ["TMBJJ7NE5K0123456"] and wyjscia["strony"] == [ADRES]
    assert [s for _, _, s in stan_wierszy(okno)] == ["brak", "skopiowana", "brak"]


def test_bez_zadnych_danych_otwarcie_niczego_nie_kopiuje(baza, wyjscia):
    przycisk_cepik(widok_pojazdu(auto())).on_click(None)
    (okno,) = wyjscia["okna"]

    przycisk(okno, ft.Button, "Otwórz stronę").on_click(None)

    assert wyjscia["schowek"] == [] and wyjscia["strony"] == [ADRES]
    assert [s for _, _, s in stan_wierszy(okno)] == ["brak"] * 3


def test_podglad_nie_dostaje_uzupelnij(baza, wyjscia):
    przycisk_cepik(widok_pojazdu(auto(rola_wspoldzielenia=db.ROLA_PODGLAD, vin="X"))).on_click(None)
    (okno,) = wyjscia["okna"]

    assert "Bez kompletu strona nie znajdzie auta." in teksty(okno)
    assert [b for b in _wszystkie(okno, ft.TextButton) if b.content == "Uzupełnij"] == []


# ============================================================================
#  5. KARTA POJAZDU
# ============================================================================

def test_przycisk_stoi_w_specyfikacji_pod_pierwsza_rejestracja(baza):
    widok = widok_pojazdu(auto(**KOMPLET))
    napisy = teksty(widok)

    assert przycisk_cepik(widok).on_click is not None
    assert (napisy.index("VIN") < napisy.index("Pierwsza rejestracja")
            < napisy.index("historiapojazdu.gov.pl, bezpłatnie") < napisy.index("Pojemność silnika"))


def test_przycisk_stoi_takze_bez_danych(baza):
    assert przycisk_cepik(widok_pojazdu(auto())).on_click is not None


def test_pierwsza_rejestracja_ma_przycisk_kopiowania(baza, monkeypatch):
    skopiowane = []
    monkeypatch.setattr(utils.komponenty, "kopiuj_do_schowka",
                        lambda strona, wartosc, komunikat="": skopiowane.append((wartosc, komunikat)))
    widok = widok_pojazdu(auto(**KOMPLET))

    (rzad,) = [r for r in _wszystkie(widok, ft.Row)
               if any(isinstance(c, ft.Column) and "Pierwsza rejestracja" in teksty(c) for c in r.controls)]
    (kopiuj,) = [b for b in rzad.controls if isinstance(b, ft.IconButton) and b.tooltip == "Kopiuj"]
    kopiuj.on_click(None)

    assert skopiowane == [("12.03.2019", "Skopiowano: Pierwsza rejestracja")]


def test_podpowiedz_o_wstecz_tylko_na_androidzie(baza, wyjscia):
    strona = pomoce.zbuduj_strone()
    widok = widok_pojazdu(auto(**KOMPLET), strona)

    widok._sprawdz_w_cepik()
    assert not any("Wstecz" in t for t in teksty(wyjscia["okna"][-1]))

    strona.page.platform = ft.PagePlatform.ANDROID
    widok._sprawdz_w_cepik()
    assert any("„Wstecz”" in t for t in teksty(wyjscia["okna"][-1]))
