"""Do zrobienia ↔ Serwis: podpowiedź części z tytułu, „Zapisz w” w oknie „Wykonano” (część,
nowy podzespół, Inne koszty), pełny formularz wymiany z pozycji (też wykonanej — dawny koszt do
kosza), przekształcenie w podzespół, planowanie z karty podzespołu, znacznik i ślad w Serwisie."""

import asyncio

import flet as ft
import pytest

import audyty
import db
import pomoce
import utils
from pomoce import dzien, wstaw
from views.formularze.wpis_serwisowy import FormularzWpisView
from views.formularze.zadanie import FormularzZadanieView
from views.todo_view import WYKONANE, DO_ZROBIENIA, FormularzDoZrobieniaView


def jeden(sql, parametry=()):
    with db.polacz_baze() as conn:
        w = conn.execute(sql, parametry).fetchone()
    return (w[0] if len(w) == 1 else tuple(w)) if w else None


def zdarzenia(pozycja_id):
    return [z["rodzaj"] for z in db.pobierz_zdarzenia_do_zrobienia(pozycja_id)]


@pytest.fixture
def auto(baza):
    """Auto z licznikiem (dziś 120 000) i trzema podzespołami: olej z interwałem, klocki, tarcze."""
    db.zapisz_moje_imie("Kamil")
    a = wstaw("samochody", nazwa="Astra", typ_paliwa="Benzyna")
    wstaw("odczyty_przebiegu", auto_id=a, data=dzien(30), przebieg=117000)
    wstaw("odczyty_przebiegu", auto_id=a, data=dzien(0), przebieg=120000)
    return {"auto_id": a,
            "olej": wstaw("zadania", auto_id=a, nazwa="Olej silnikowy i filtr", interwal_km=15000, interwal_miesiace=12),
            "klocki": wstaw("zadania", auto_id=a, nazwa="Klocki hamulcowe"),
            "tarcze": wstaw("zadania", auto_id=a, nazwa="Tarcze hamulcowe")}


def pozycja(auto, tytul="Wymienić klocki hamulcowe przód", zadanie=None, **pola):
    return db.zapisz_pozycje_do_zrobienia(auto["auto_id"], {
        "tytul": tytul, "szacowany_koszt": 400, "zadanie_id": auto[zadanie] if zadanie else None, **pola})


@pytest.fixture
def ekran(monkeypatch):
    return pomoce.zbieraj_ekran(monkeypatch)


def zbuduj(auto, podzakladka=DO_ZROBIENIA):
    stan = pomoce.stan_aplikacji(auto["auto_id"], "Astra")
    stan.do_zrobienia_podzakladka = podzakladka
    strona = pomoce.zbuduj_strone()
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["DoZrobieniaView"], strona, stan)
    strona.page.views.append(widok)
    return strona, widok


def przycisk(korzen, napis):
    return next(b for b in pomoce.kontrolki(korzen, (ft.Button, ft.TextButton)) if b.content == napis)


def kliknij(arkusz, tytul):
    asyncio.run(next(t for t in pomoce.kontrolki(arkusz, ft.ListTile) if t.title.value == tytul).on_click(None))


def pola(okno):
    return {k.label: k for k in pomoce.kontrolki(okno, ft.TextField)}


# ============================================================================
#  PODPOWIEDŹ CZĘŚCI I NAZWA NOWEGO PODZESPOŁU
# ============================================================================

def pasujace(auto, tytul, zadanie_id=None):
    return [(z["nazwa"], z["pewne"]) for z in db.podzespoly_dla_pozycji(auto["auto_id"], tytul, zadanie_id) if z["pasuje"]]


def test_podpowiedz_czesci_z_tytulu(auto):
    for nazwa in ("Opony letnie", "🌀 Filtr kabinowy", "Filtr powietrza"):
        wstaw("zadania", auto_id=auto["auto_id"], nazwa=nazwa)

    assert pasujace(auto, "Wymienić klocki hamulcowe przód") == [("Klocki hamulcowe", True), ("Tarcze hamulcowe", False)]
    assert pasujace(auto, "wymiana oleju") == [("Olej silnikowy i filtr", True)], "odmiana i bez wielkich liter"
    assert pasujace(auto, "Sprawdzić ciśnienie w oponach") == [("Opony letnie", False)], "kontrola to nie wymiana"
    assert pasujace(auto, "Dolać olej") == [("Olej silnikowy i filtr", False)], "dolewka nie zeruje interwału"
    assert [p for _, p in pasujace(auto, "Filtr")] == [False, False, False], "dwa równe trafienia — bez pewności"
    assert pasujace(auto, "Wymienić filtr kabinowy") == [
        ("🌀 Filtr kabinowy", True), ("Filtr powietrza", False), ("Olej silnikowy i filtr", False)]
    assert pasujace(auto, "Umyć auto") == []
    lista = db.podzespoly_dla_pozycji(auto["auto_id"], "Wymienić klocki", zadanie_id=auto["tarcze"])
    assert lista[0]["nazwa"] == "Tarcze hamulcowe" and not any(z["pewne"] for z in lista), "powiązany na górze"
    assert [z["nazwa"] for z in db.podzespoly_dla_pozycji(auto["auto_id"], "Umyć auto")][:3] == \
        ["🌀 Filtr kabinowy", "Filtr powietrza", "Klocki hamulcowe"], "bez trafień — po nazwie, emoji nie liczy się"


@pytest.mark.parametrize("tytul, nazwa", [
    ("Wymienić klocki hamulcowe przód", "Klocki hamulcowe przód"),
    ("kupić nowe wycieraczki", "Wycieraczki"),
    ("Wymiana: Olej silnikowy", "Olej silnikowy"),
    ("Rozrząd", "Rozrząd"),
    ("Wymienić", "Wymienić"),
    ("🔧 wymienić akumulator", "🔧 Akumulator"),
])
def test_nazwa_podzespolu_z_tytulu(tytul, nazwa):
    assert db.nazwa_podzespolu_z_tytulu(tytul) == nazwa


# ============================================================================
#  WYKONANIE Z WYBRANĄ CZĘŚCIĄ (dane z okna „Wykonano”)
# ============================================================================

def test_wykonanie_pod_wybrana_czescia(auto):
    p = pozycja(auto)
    wynik = db.oznacz_wykonane_do_zrobienia([p], {"data": dzien(3), "przebieg": 119700, "koszt": 420,
                                                   "zadanie_id": auto["klocki"]})

    w = db.pozycja_do_zrobienia(p)
    assert (wynik["serwis"], wynik["podzespol"], w["zadanie_id"], w["koszt_id"]) == (1, "Klocki hamulcowe", auto["klocki"], None)
    assert jeden("SELECT zadanie_id, data, przebieg, cena FROM historia WHERE id=?", (w["historia_id"],)) == \
        (auto["klocki"], dzien(3), 119700, 420.0)
    assert jeden("SELECT data FROM zadania WHERE id=?", (auto["klocki"],)) == dzien(3), "interwał części od nowa"
    assert db.pobierz_zdarzenia_do_zrobienia(p)[-1]["dane"]["podzespol"] == "Klocki hamulcowe"


def test_nowy_podzespol_z_okna_a_ta_sama_nazwa_trafia_w_istniejacy(auto):
    p, q = pozycja(auto, "Wymienić amortyzatory"), pozycja(auto, "Amortyzatory raz jeszcze")
    wynik = db.oznacz_wykonane_do_zrobienia([p], {"data": dzien(1), "przebieg": 119900, "nowy_podzespol": "Amortyzatory"})
    drugi = db.oznacz_wykonane_do_zrobienia([q], {"data": dzien(0), "przebieg": 120000, "nowy_podzespol": " amortyzatory "})

    z = jeden("SELECT id FROM zadania WHERE nazwa='Amortyzatory'")
    assert (wynik["nowy_podzespol"], drugi["nowy_podzespol"]) == (True, False)
    assert jeden("SELECT COUNT(*) FROM zadania WHERE auto_id=?", (auto["auto_id"],)) == 4
    assert {db.pozycja_do_zrobienia(i)["zadanie_id"] for i in (p, q)} == {z}
    assert jeden("SELECT COUNT(*) FROM historia WHERE zadanie_id=?", (z,)) == 2


def test_poprawka_z_innych_kosztow_do_serwisu(auto):
    p = pozycja(auto)
    db.oznacz_wykonane_do_zrobienia([p], {"data": dzien(5), "koszt": 380})
    koszt = db.pozycja_do_zrobienia(p)["koszt_id"]

    db.oznacz_wykonane_do_zrobienia([p], {"data": dzien(5), "przebieg": 119500, "koszt": 380, "zadanie_id": auto["klocki"]})

    w = db.pozycja_do_zrobienia(p)
    assert w["koszt_id"] is None and jeden("SELECT zadanie_id FROM historia WHERE id=?", (w["historia_id"],)) == auto["klocki"]
    assert jeden("SELECT COUNT(*) FROM inne_koszty WHERE id=?", (koszt,)) == 0
    db.przywroc_wpis_z_kosza(jeden("SELECT id FROM kosz_wpisy WHERE tabela='inne_koszty'"))
    assert db.pozycja_do_zrobienia(p)["koszt_id"] is None, "przywrócony koszt nie przykleja się do pozycji"


def test_poprawka_przenosi_wpis_pod_inna_czesc(auto):
    p = pozycja(auto)
    db.oznacz_wykonane_do_zrobienia([p], {"data": dzien(4), "przebieg": 119600, "koszt": 400, "zadanie_id": auto["tarcze"]})
    h = db.pozycja_do_zrobienia(p)["historia_id"]

    db.oznacz_wykonane_do_zrobienia([p], {"data": dzien(4), "przebieg": 119600, "koszt": 400, "zadanie_id": auto["klocki"]})

    assert db.pozycja_do_zrobienia(p)["historia_id"] == h, "ten sam wpis, z plikami i częściami"
    assert jeden("SELECT zadanie_id FROM historia WHERE id=?", (h,)) == auto["klocki"]
    assert jeden("SELECT data FROM zadania WHERE id=?", (auto["tarcze"],)) in (None, ""), "tarcze bez wymiany"


def test_inne_koszty_zdejmuja_podzespol_a_znikniety_nie_zapisuje(auto):
    p = pozycja(auto, "Wymienić olej", zadanie="olej")
    db.oznacz_wykonane_do_zrobienia([p], {"data": dzien(2), "przebieg": 119800, "koszt": 250, "zadanie_id": None})

    w = db.pozycja_do_zrobienia(p)
    assert (w["zadanie_id"], w["historia_id"], bool(w["koszt_id"])) == (None, None, True)

    q = pozycja(auto, "Wymienić tarcze")
    assert db.oznacz_wykonane_do_zrobienia([q], {"data": dzien(0), "przebieg": 120000, "zadanie_id": 9999}) is None
    assert db.pozycja_do_zrobienia(q)["wykonane"] is False


# ============================================================================
#  PEŁNY FORMULARZ, POWIĄZANIE, ZNACZNIKI (warstwa db)
# ============================================================================

def wpis(auto, zadanie, data=None, przebieg=119000, cena=450.0, notatka=None, wizyta_id=None):
    return wstaw("historia", zadanie_id=auto[zadanie], data=data or dzien(2), przebieg=przebieg, cena=cena,
                 notatka=notatka, wizyta_id=wizyta_id)


def test_wymiana_z_formularza_wykonuje_aktywna_pozycje(auto):
    p = pozycja(auto)
    h = wpis(auto, "klocki", notatka="Brembo")

    assert db.wymiana_z_do_zrobienia(p, h) == {"poprawka": False, "do_kosza": 0, "podzespol": "Klocki hamulcowe"}
    w = db.pozycja_do_zrobienia(p)
    assert (w["wykonane"], w["historia_id"], w["zadanie_id"], w["data_wykonania"], w["koszt_wykonania"],
            w["notatka_wykonania"], w["wykonane_przez"]) == (True, h, auto["klocki"], dzien(2), 450.0, "Brembo", "Kamil")
    assert zdarzenia(p) == ["dodano", "wykonano"]


def test_wymiana_z_formularza_przenosi_wykonana_a_koszt_do_kosza(auto):
    p = pozycja(auto, "Wymienić żarówkę H7")
    db.oznacz_wykonane_do_zrobienia([p], {"data": dzien(6), "koszt": 35})
    h = wpis(auto, "klocki", data=dzien(6), cena=35.0)

    assert db.wymiana_z_do_zrobienia(p, h)["do_kosza"] == 1
    assert db.pozycja_do_zrobienia(p)["koszt_id"] is None and jeden("SELECT COUNT(*) FROM inne_koszty") == 0
    assert jeden("SELECT tabela FROM kosz_wpisy") == "inne_koszty" and zdarzenia(p)[-1] == "poprawka"
    db.przywroc_wpis_z_kosza(jeden("SELECT id FROM kosz_wpisy"))
    assert db.pozycja_do_zrobienia(p)["koszt_id"] is None, "odwołanie zdjęte przed koszem"


def test_wymiana_z_formularza_odmawia(auto, monkeypatch):
    p = pozycja(auto)
    wizyta = wstaw("wizyty", auto_id=auto["auto_id"], data=dzien(1), przebieg=119900)
    w_wizycie = wpis(auto, "klocki", wizyta_id=wizyta)
    assert db.wymiana_z_do_zrobienia(p, w_wizycie) is None, "wpis z wizyty nie jest wymianą z formularza"
    assert db.wymiana_z_do_zrobienia(p, 9999) is None

    monkeypatch.setattr(db.do_zrobienia, "czy_moge_dodawac", lambda auto_id: False)
    assert db.wymiana_z_do_zrobienia(p, wpis(auto, "klocki")) is None
    assert db.pozycja_do_zrobienia(p)["wykonane"] is False


def test_powiazanie_bez_wymiany_i_znaczniki(auto):
    p = pozycja(auto, termin=dzien(-14))
    assert db.powiaz_pozycje_z_podzespolem(p, auto["klocki"]) is True
    assert db.powiaz_pozycje_z_podzespolem(p, auto["klocki"]) is False, "bez zmiany — bez wpisu w dzienniku"
    assert db.pobierz_zdarzenia_do_zrobienia(p)[-1]["dane"] == {"pola": ["zadanie_id"], "zadanie": [None, "Klocki hamulcowe"]}
    assert db.pozycje_do_zrobienia_podzespolow(auto["auto_id"]) == {
        auto["klocki"]: [{"id": p, "tytul": "Wymienić klocki hamulcowe przód", "termin": dzien(-14), "termin_przebieg": None}]}

    db.oznacz_wykonane_do_zrobienia([p], {"data": dzien(0), "przebieg": 120000})
    assert db.pozycje_do_zrobienia_podzespolow(auto["auto_id"]) == {}, "wykonana już nie czeka"
    assert db.pozycje_do_zrobienia_wpisow(auto["klocki"]) == {db.pozycja_do_zrobienia(p)["historia_id"]: "Wymienić klocki hamulcowe przód"}
    assert db.powiaz_pozycje_z_podzespolem(p, auto["tarcze"]) is False, "wykonanej się nie przepina"


# ============================================================================
#  OKNO „WYKONANO”
# ============================================================================

def test_okno_podpowiada_czesc_z_tytulu_i_zapisuje_pod_nia(auto, ekran):
    p = pozycja(auto)
    strona, widok = zbuduj(auto)
    widok._okno_wykonania([db.pozycja_do_zrobienia(p)])

    (okno,) = ekran.okna
    teksty = pomoce.napisy(okno)
    assert "Serwis: Klocki hamulcowe" in teksty and any(t.startswith("Podpowiedź z tytułu pozycji.") for t in teksty)
    assert audyty.znajdz_uciete_napisy(okno) == []
    pomoce.kontrolki(okno, ft.Button)[-1].on_click(None)

    w = db.pozycja_do_zrobienia(p)
    assert jeden("SELECT zadanie_id, cena FROM historia WHERE id=?", (w["historia_id"],)) == (auto["klocki"], 400.0)
    assert "(Klocki hamulcowe)" in ekran.komunikaty[-1]


def test_okno_zmiana_celu_z_arkusza(auto, ekran):
    p = pozycja(auto, "Wymienić olej", zadanie="olej")
    strona, widok = zbuduj(auto)
    widok._okno_wykonania([db.pozycja_do_zrobienia(p)])
    (okno,) = ekran.okna
    assert "Serwis: Olej silnikowy i filtr" in pomoce.napisy(okno)

    przycisk(okno, "Zmień").on_click(None)
    arkusz = ekran.okna[-1]
    kafle = pomoce.kontrolki(arkusz, ft.ListTile)
    assert kafle[0].title.value == "Olej silnikowy i filtr" and kafle[0].leading.icon == ft.Icons.CHECK
    assert {"Nowy podzespół…", "Inne koszty", "Nigdzie — tylko odhacz"} <= {k.title.value for k in kafle}
    kliknij(arkusz, "Inne koszty")
    assert "Inne koszty" in pomoce.napisy(okno) and "Pełny formularz wymiany" not in [
        b.content for b in pomoce.kontrolki(okno, ft.TextButton) if b.visible]
    pomoce.kontrolki(okno, ft.Button)[-1].on_click(None)

    w = db.pozycja_do_zrobienia(p)
    assert (w["zadanie_id"], w["historia_id"], bool(w["koszt_id"])) == (None, None, True)


def test_okno_nowy_podzespol_wymaga_nazwy(auto, ekran):
    p = pozycja(auto, "Wymienić amortyzatory przód")
    strona, widok = zbuduj(auto)
    widok._okno_wykonania([db.pozycja_do_zrobienia(p)])
    (okno,) = ekran.okna
    przycisk(okno, "Zmień").on_click(None)
    kliknij(ekran.okna[-1], "Nowy podzespół…")

    nazwa = pola(okno)["Nazwa podzespołu"]
    wiersz = next(r for r in pomoce.kontrolki(okno, ft.Row) if any(c is nazwa for c in r.controls))
    assert nazwa.value == "Amortyzatory przód" and wiersz.visible
    nazwa.value = " "
    pomoce.kontrolki(okno, ft.Button)[-1].on_click(None)
    assert nazwa.error and db.pozycja_do_zrobienia(p)["wykonane"] is False

    nazwa.value = "Amortyzatory przód"
    pomoce.kontrolki(okno, ft.Button)[-1].on_click(None)
    z = jeden("SELECT id FROM zadania WHERE nazwa='Amortyzatory przód'")
    assert z and db.pozycja_do_zrobienia(p)["zadanie_id"] == z and "Podzespół założony w Serwisie." in ekran.komunikaty[-1]


def test_pelny_formularz_z_okna_niesie_wpisane_pola(auto, ekran):
    p = pozycja(auto, opis="przód, komplet")
    strona, widok = zbuduj(auto)
    widok._okno_wykonania([db.pozycja_do_zrobienia(p)])
    (okno,) = ekran.okna
    pole = pola(okno)
    pole["Data wykonania"].value = dzien(3)
    pole["Stan licznika (km)"].value = "119 500"
    pole[f"Faktyczny koszt ({utils.symbol_waluty()})"].value = "450"
    pole["Notatka (opcjonalnie)"].value = "Brembo"
    przycisk(okno, "Pełny formularz wymiany").on_click(None)
    assert ekran.trasy[-1] == f"/wpis/nowy/{auto['klocki']}/do-zrobienia/{p}"

    formularz = FormularzWpisView(strona.page, widok.state, None, auto["klocki"], pozycja_id=p)
    assert (formularz.e_d.value, formularz.e_p.value, formularz.k_notatka.value) == (dzien(3), "119500", "Brembo")
    assert utils.parsuj_float(formularz.koszt.e_kwota.value) == 450 and widok.state.wykonanie_do_zrobienia is None
    assert "Z listy Do zrobienia: „Wymienić klocki hamulcowe przód”. Po zapisie pozycja trafi do Wykonanych." in \
        pomoce.napisy(formularz)
    formularz.zapisz(None)

    w = db.pozycja_do_zrobienia(p)
    assert (w["wykonane"], w["zadanie_id"]) == (True, auto["klocki"])
    assert jeden("SELECT data, przebieg, cena, notatka FROM historia WHERE id=?", (w["historia_id"],)) == \
        (dzien(3), 119500, 450.0, "Brembo")
    assert ekran.trasy[-1] == "/do-zrobienia" and "Pozycja jest w Wykonanych." in ekran.komunikaty[-1]


# ============================================================================
#  MENU POZYCJI, FORMULARZE Z POZYCJI
# ============================================================================

def test_menu_pozycji_prowadzi_do_serwisu(auto, ekran):
    luzna, z_czescia, w_kosztach = pozycja(auto), pozycja(auto, "Wymienić olej", zadanie="olej"), pozycja(auto, "Żarówka")
    db.oznacz_wykonane_do_zrobienia([w_kosztach], {"data": dzien(1), "koszt": 30})
    strona, widok = zbuduj(auto)

    def akcje(pid):
        return [a["tekst"] for a in widok._akcje_pozycji(db.pozycja_do_zrobienia(pid))]

    assert {"Dopisz do serwisu", "Przekształć w podzespół Serwisu"} <= set(akcje(luzna))
    assert "Dopisz do serwisu" in akcje(z_czescia) and "Przekształć w podzespół Serwisu" not in akcje(z_czescia)
    assert "Przenieś do serwisu" in akcje(w_kosztach)
    db.oznacz_wykonane_do_zrobienia([z_czescia], {"data": dzien(0), "przebieg": 120000})
    assert "Przenieś do serwisu" not in akcje(z_czescia) and "Otwórz wpis serwisowy" in akcje(z_czescia)

    widok._do_serwisu(db.pozycja_do_zrobienia(luzna))
    arkusz = ekran.okna[-1]
    tytuly = [k.title.value for k in pomoce.kontrolki(arkusz, ft.ListTile)]
    assert tytuly[:3] == ["Klocki hamulcowe", "Tarcze hamulcowe", "Nowy podzespół…"] and "Inne koszty" not in tytuly
    kliknij(arkusz, "Klocki hamulcowe")
    assert ekran.trasy[-1] == f"/wpis/nowy/{auto['klocki']}/do-zrobienia/{luzna}"
    widok._do_serwisu(db.pozycja_do_zrobienia(w_kosztach))
    kliknij(ekran.okna[-1], "Nowy podzespół…")
    assert ekran.trasy[-1] == f"/zadanie/nowy/do-zrobienia/{w_kosztach}"


def test_przeniesienie_wykonanej_pelnym_formularzem(auto, ekran):
    p = pozycja(auto, "Wymienić żarówkę H7")
    db.oznacz_wykonane_do_zrobienia([p], {"data": dzien(5), "przebieg": 119000, "koszt": 35})
    zarowki = wstaw("zadania", auto_id=auto["auto_id"], nazwa="Żarówki")
    strona, widok = zbuduj(auto, WYKONANE)

    formularz = FormularzWpisView(strona.page, widok.state, None, zarowki, pozycja_id=p)
    assert (formularz.e_d.value, formularz.e_p.value, formularz.trasa_powrotu) == (dzien(5), "119000", "/do-zrobienia/wykonane")
    formularz.zapisz(None)

    w = db.pozycja_do_zrobienia(p)
    assert (w["koszt_id"], w["zadanie_id"]) == (None, zarowki)
    assert jeden("SELECT data, cena FROM historia WHERE id=?", (w["historia_id"],)) == (dzien(5), 35.0)
    assert "Dawny Inny koszt trafił do kosza." in ekran.komunikaty[-1]


def test_przeksztalcenie_bez_wymiany_zostawia_pozycje_na_liscie(auto, ekran):
    p = pozycja(auto, "Wymienić amortyzatory przód")
    strona, widok = zbuduj(auto)
    formularz = FormularzZadanieView(strona.page, widok.state, None, pozycja_id=p)
    assert (formularz.e_n.value, formularz.c_dodaj_wymiane.value, formularz.karta_wymiany.visible) == \
        ("Amortyzatory przód", False, False)
    assert audyty.znajdz_uciete_napisy(formularz) == []
    formularz.zapisz(None)

    z = jeden("SELECT id FROM zadania WHERE nazwa='Amortyzatory przód'")
    w = db.pozycja_do_zrobienia(p)
    assert (w["wykonane"], w["zadanie_id"]) == (False, z) and jeden("SELECT COUNT(*) FROM historia") == 0
    assert ekran.trasy[-1] == "/do-zrobienia" and "czeka na liście" in ekran.komunikaty[-1]
    assert zdarzenia(p) == ["dodano", "zmiana"]


def test_przeksztalcenie_z_okna_wpisuje_wymiane_z_notatka(auto, ekran):
    p = pozycja(auto, "Wymienić amortyzatory przód", opis="Bilstein B4")
    strona, widok = zbuduj(auto)
    widok._okno_wykonania([db.pozycja_do_zrobienia(p)])
    (okno,) = ekran.okna
    przycisk(okno, "Zmień").on_click(None)
    kliknij(ekran.okna[-1], "Nowy podzespół…")
    przycisk(okno, "Pełny formularz wymiany").on_click(None)
    assert ekran.trasy[-1] == f"/zadanie/nowy/do-zrobienia/{p}"

    formularz = FormularzZadanieView(strona.page, widok.state, None, pozycja_id=p)
    assert (formularz.c_dodaj_wymiane.value, formularz.karta_wymiany.visible, formularz.k_notatka.value) == \
        (True, True, "Bilstein B4")
    formularz.zapisz(None)

    w = db.pozycja_do_zrobienia(p)
    z = jeden("SELECT id FROM zadania WHERE nazwa='Amortyzatory przód'")
    assert w["wykonane"] and jeden("SELECT zadanie_id, cena, notatka FROM historia WHERE id=?", (w["historia_id"],)) == \
        (z, 400.0, "Bilstein B4")
    assert jeden("SELECT data FROM zadania WHERE id=?", (z,)) == w["data_wykonania"]


# ============================================================================
#  SERWIS: PLANOWANIE Z KARTY, ZNACZNIK, ŚLAD W HISTORII
# ============================================================================

def test_planowanie_z_karty_podzespolu_bierze_termin_z_interwalu(auto, ekran):
    with db.polacz_baze() as conn:
        conn.execute("UPDATE zadania SET data=?, przebieg=? WHERE id=?", (dzien(300), 110000, auto["olej"]))
    strona = pomoce.zbuduj_strone()
    formularz = FormularzDoZrobieniaView(strona.page, pomoce.stan_aplikacji(auto["auto_id"], "Astra"), None,
                                         zadanie_id=auto["olej"])

    assert (formularz.e_tytul.value, formularz.e_zadanie.value, formularz.e_termin.value, formularz.e_termin_km.value) == \
        ("Wymiana: Olej silnikowy i filtr", str(auto["olej"]), dzien(-66), "125000")
    formularz.zapisz(None)

    assert (ekran.trasy[-1], ekran.komunikaty[-1]) == ("/", "Dodano do Do zrobienia.")
    (p,) = db.pobierz_pozycje_do_zrobienia(auto["auto_id"])
    assert (p["zadanie_id"], p["termin"], p["termin_przebieg"]) == (auto["olej"], dzien(-66), 125000)


def test_karta_serwisu_ma_znacznik_i_akcje_planowania(auto, ekran):
    pozycja(auto, "Wymienić olej", zadanie="olej", termin=dzien(-20))
    stan = pomoce.stan_aplikacji(auto["auto_id"], "Astra")
    stan.zakladka = 1
    strona = pomoce.zbuduj_strone()
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], strona, stan)

    assert f"Zaplanowane w Do zrobienia · {dzien(-20)}" in pomoce.napisy(widok.lista_kart_serwis)
    widok.karty_ref[auto["olej"]].on_click(None)
    arkusz = ekran.okna[-1]
    assert {"Zaplanuj w Do zrobienia", "Zaplanowane w Do zrobienia (1)"} <= set(pomoce.napisy(arkusz))
    kliknij(arkusz, "Zaplanuj w Do zrobienia")
    assert ekran.trasy[-1] == f"/do-zrobienia/nowe/podzespol/{auto['olej']}"
    widok.karty_ref[auto["klocki"]].on_click(None)
    assert "Zaplanowane w Do zrobienia (1)" not in pomoce.napisy(ekran.okna[-1])


def test_historia_podzespolu_ma_slad_z_listy(auto, ekran):
    p = pozycja(auto, "Wymienić olej", zadanie="olej")
    db.oznacz_wykonane_do_zrobienia([p], {"data": dzien(2), "przebieg": 119800})
    h = db.pozycja_do_zrobienia(p)["historia_id"]
    strona = pomoce.zbuduj_strone()
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["HistoriaView"], strona,
                                pomoce.stan_aplikacji(auto["auto_id"], "Astra"), {"zadanie": auto["olej"]})

    assert "Z listy Do zrobienia: „Wymienić olej”" in pomoce.napisy(widok)
    widok.karty_ref[h].on_click(None)
    kliknij(ekran.okna[-1], "Pokaż w Do zrobienia")
    assert ekran.trasy[-1] == "/do-zrobienia/wykonane"


def test_trasy_formularzy_z_pozycji(auto, monkeypatch):
    monkeypatch.setattr(ft, "run", lambda *a, **k: None)
    import log
    import main

    monkeypatch.setattr(log, "wlacz", lambda: True)
    monkeypatch.setitem(utils.wyglad._OSTATNI_MOTYW, "nazwa", utils.wyglad._OSTATNI_MOTYW["nazwa"])
    db.zapisz_widziana_wersje(db.WERSJA_APLIKACJI)
    p = pozycja(auto)
    strona = pomoce.zbuduj_strone()
    page = strona.page
    monkeypatch.setattr(type(page), "run_task", lambda self, *a, **k: None)
    main.main(page)

    def stos():
        return [type(v).__name__ for v in page.views[-2:]]

    utils.przejdz(page, f"/wpis/nowy/{auto['klocki']}/do-zrobienia/{p}")
    assert stos() == ["DoZrobieniaView", "FormularzWpisView"] and page.views[-1].pozycja["id"] == p
    utils.przejdz(page, f"/zadanie/nowy/do-zrobienia/{p}")
    assert stos() == ["DoZrobieniaView", "FormularzZadanieView"] and page.views[-1].pozycja["id"] == p
    utils.przejdz(page, f"/do-zrobienia/nowe/podzespol/{auto['olej']}")
    assert stos() == ["MainView", "FormularzDoZrobieniaView"] and page.views[-1].zadanie_id == auto["olej"]
    utils.przejdz(page, f"/wpis/nowy/{auto['klocki']}")
    assert stos() == ["HistoriaView", "FormularzWpisView"] and page.views[-1].pozycja is None
