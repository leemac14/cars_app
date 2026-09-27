"""Pole „cena za litr” w formularzu tankowania (M-01) i ostrzeżenie o nietypowej cenie.

Formularz miał litry i kwotę, a cena za litr liczyła się dopiero w statystykach
i w kalkulatorze trasy — choć na dystrybutorze widać ją pierwszą i najłatwiej ją
zapamiętać. Teraz stoją trzy pola: wpisujesz dowolne dwa, trzecie liczy się samo,
zawsze to, którego najdłużej nikt nie ruszał. Cena nie ma kolumny — zapisują się
litry i kwota, a cena zostaje ich ilorazem, tak jak wszędzie indziej w aplikacji.

Literówkę w trójce (cyfra albo przecinek za dużo lub za mało) łapie ostrzeżenie
o nietypowej cenie: cena co najmniej trzy razy inna od KAŻDEJ z cen tego samego
źródła z wpisów najbliższych w czasie. Pasek pod polami pokazuje się po wyjściu
z pola i znika od razu po poprawce, a zapis prosi o potwierdzenie jak przy
duplikacie.
"""

import pytest

import db
import pomoce
import utils
from date import na_iso


def _auto(typ="Benzyna", nazwa="Cena"):
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO samochody (nazwa, marka, model, typ_paliwa, status) VALUES (?,?,?,?,?)",
            (nazwa, "Marka", "Model", typ, db.STATUS_POJAZDU_AKTYWNY),
        )
        return c.lastrowid


def _tankuj(auto_id, data, przebieg, litry, kwota, rodzaj=None):
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO tankowania (auto_id, data, data_iso, przebieg, dystans, litry, kwota, do_pelna, rodzaj_energii) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (auto_id, data, na_iso(data), przebieg, 0, litry, kwota, 1, rodzaj),
        )
        return c.lastrowid


def _auto_z_historia(typ="Benzyna"):
    """Dwa tankowania po 6,50 zł/L na początku września 2026."""
    auto = _auto(typ)
    _tankuj(auto, "01.09.2026", 10000, 40, 260)
    _tankuj(auto, "10.09.2026", 10300, 38, 247)
    return auto


def _wiersze(auto_id):
    with db.polacz_baze() as conn:
        return conn.execute(
            "SELECT litry, kwota FROM tankowania WHERE auto_id=? ORDER BY id", (auto_id,)).fetchall()


@pytest.fixture
def formularz(monkeypatch):
    from views.formularze.tankowanie import FormularzTankowanieView

    def otworz(auto_id, t_id=None):
        strona = pomoce.zbuduj_strone()
        strona.page.on_route_change = lambda e: None  # zapis wraca trasą
        widok = FormularzTankowanieView(strona.page, pomoce.stan_aplikacji(auto_id, "Cena"), t_id)
        # Strona trzyma sesję przez weakref — musi żyć tak długo jak widok.
        widok._strona_testowa = strona
        monkeypatch.setattr(widok.k_trojka, "update", lambda *a, **k: None)
        monkeypatch.setattr(widok.baner_ciagu, "update", lambda *a, **k: None)
        return widok

    return otworz


def _wpisz(widok, klucz, tekst):
    """Jak palec na klawiaturze: nowa wartość, potem on_change."""
    pole = widok._pole_trojki(klucz)
    pole.value = tekst
    pole.on_change(None)


def _wyjdz(widok, klucz):
    widok._pole_trojki(klucz).on_blur(None)


def _wartosci(widok):
    return widok.e_l.value, widok.e_cena.value, widok.e_k.value


def _z_ikona(widok):
    """Pola oznaczone jako wyliczone (ikona kalkulatora)."""
    return [k for k in ("ilosc", "cena", "kwota") if widok._pole_trojki(k).suffix_icon]


def _rodzenstwo(korzen, szukana):
    """Lista kontrolek, w której stoi `szukana` (po drodze przez content)."""
    do_odwiedzenia = [korzen]
    while do_odwiedzenia:
        biezaca = do_odwiedzenia.pop()
        dzieci = getattr(biezaca, "controls", None)
        if isinstance(dzieci, list):
            if any(d is szukana for d in dzieci):
                return dzieci
            do_odwiedzenia.extend(dzieci)
        tresc = getattr(biezaca, "content", None)
        if tresc is not None and not isinstance(tresc, str):
            do_odwiedzenia.append(tresc)
    return None


# ------------------------------------------------------------ arytmetyka


def test_trzecie_pole_zaokraglone_jak_na_dystrybutorze():
    from views.formularze.tankowanie import _wylicz_pole

    assert _wylicz_pole("kwota", {"ilosc": 45.3, "cena": 6.49}) == 294.0, "kwota do groszy"
    assert _wylicz_pole("ilosc", {"kwota": 200, "cena": 6.49}) == 30.82, "litry do setnych, jak na liczniku"
    assert _wylicz_pole("cena", {"kwota": 293.99, "ilosc": 45.3}) == 6.49
    assert _wylicz_pole("cena", {"kwota": 71.56, "ilosc": 40}) == 1.789, "cena do tysięcznych (ceny w euro)"
    assert _wylicz_pole("kwota", {"ilosc": 45.3}) is None, "z jednego pola nic się nie policzy"
    assert _wylicz_pole("ilosc", {"kwota": 0.01, "cena": 99}) is None, "zero po zaokrągleniu to nie wynik"


# ------------------------------------------------------------ formularz


def test_uklad_litry_cena_kwota_i_typ_ladowania_nad_trojka(baza, formularz):
    widok = formularz(_auto())
    pola = widok.k_trojka.controls
    assert pola[0] is widok.e_l and pola[1] is widok.e_cena, "litry, cena, kwota — jak linijka paragonu"
    assert pola[2].controls[0] is widok.e_k and pola[2].controls[1] is widok.t_trojki, "podpis tuż pod kwotą"
    karta = _rodzenstwo(widok, widok.k_trojka)
    assert karta[karta.index(widok.k_trojka) - 1] is widok.e_ladowanie, "typ ładowania nie rozdziela trójki"
    assert widok.e_cena.label == f"Cena za litr ({utils.symbol_waluty()})"
    assert widok.t_trojki.value == "Wystarczą dwa z trzech pól — trzecie policzy się samo."


@pytest.mark.parametrize("wpisane, wyliczone, oczekiwane, podpis", [
    ((("ilosc", "45,3"), ("cena", "6,49")), "kwota", ("45,3", "6,49", "294"),
     "Kwota wyliczona z litrów i ceny — wpisz ją, a przeliczą się litry."),
    ((("cena", "6,49"), ("kwota", "200")), "ilosc", ("30,82", "6,49", "200"),
     "Litry wyliczone z ceny i kwoty — wpisz je, a przeliczy się cena."),
    ((("ilosc", "45,3"), ("kwota", "293,99")), "cena", ("45,3", "6,49", "293,99"),
     "Cena wyliczona z litrów i kwoty — wpisz ją, a przeliczą się litry."),
])
def test_dwa_dowolne_pola_licza_trzecie(baza, formularz, wpisane, wyliczone, oczekiwane, podpis):
    widok = formularz(_auto())
    for klucz, tekst in wpisane:
        _wpisz(widok, klucz, tekst)
    assert _wartosci(widok) == oczekiwane
    assert _z_ikona(widok) == [wyliczone]
    assert widok.t_trojki.value == podpis


def test_przelicza_sie_najdawniej_ruszane(baza, formularz):
    widok = formularz(_auto())
    _wpisz(widok, "ilosc", "45,3")
    _wpisz(widok, "cena", "6,49")
    assert widok.e_k.value == "294"

    _wpisz(widok, "kwota", "300")  # kwota z paragonu nadpisuje wyliczoną
    assert _wartosci(widok) == ("46,22", "6,49", "300"), "przeliczyły się litry — ruszane najdawniej"
    assert _z_ikona(widok) == ["ilosc"]
    assert widok.t_trojki.value == "Litry wyliczone z ceny i kwoty — wpisz je, a przeliczy się cena."

    _wpisz(widok, "cena", "6")
    assert _wartosci(widok) == ("50", "6", "300"), "litry dalej wyliczane, kwota zostaje"
    assert widok.t_trojki.value == "Litry wyliczone z ceny i kwoty — wpisz je, a przeliczy się kwota."


def test_edycja_zmiana_ceny_przelicza_litry_a_kwota_zostaje(baza, formularz):
    auto = _auto()
    _tankuj(auto, "01.09.2026", 10000, 40, 260)
    edytowany = _tankuj(auto, "10.09.2026", 10300, 40, 260)
    widok = formularz(auto, edytowany)

    assert _wartosci(widok) == ("40", "6,5", "260"), "cena wyliczona przy otwarciu"
    assert _z_ikona(widok) == ["cena"]
    assert not widok.baner_ceny.visible
    assert not widok._czy_zmieniono(), "wyliczona cena to nie zmiana"

    _wpisz(widok, "cena", "6,25")
    assert _wartosci(widok) == ("41,6", "6,25", "260")
    widok.zapisz(None)
    assert _wiersze(auto)[-1] == (41.6, 260.0)


def test_wyczyszczone_wyliczone_pole_wraca_dopiero_po_wyjsciu(baza, formularz):
    widok = formularz(_auto())
    _wpisz(widok, "ilosc", "45,3")
    _wpisz(widok, "cena", "6,49")

    _wpisz(widok, "kwota", "")  # zaznacz wszystko i usuń — zaraz wpiszę swoją
    assert widok.e_k.value == "", "nie wraca pod palcem"
    assert _z_ikona(widok) == []
    assert widok.t_trojki.value == "Wystarczą dwa z trzech pól — trzecie policzy się samo."

    _wyjdz(widok, "kwota")
    assert widok.e_k.value == "294"
    assert _z_ikona(widok) == ["kwota"]


def test_wyczyszczone_wpisane_pole_gasi_wyliczone(baza, formularz):
    widok = formularz(_auto())
    _wpisz(widok, "ilosc", "45,3")
    _wpisz(widok, "cena", "6,49")
    _wpisz(widok, "ilosc", "")
    assert _wartosci(widok) == ("", "6,49", ""), "kwota bez litrów nie ma z czego się wziąć"

    _wpisz(widok, "kwota", "200")
    assert _wartosci(widok) == ("30,82", "6,49", "200")


def test_zapis_liczy_brakujace_pole(baza, formularz):
    """Pole wypełnione bez zdarzeń (np. wklejone) — zapis i tak liczy trzecie."""
    auto = _auto_z_historia()
    widok = formularz(auto)
    widok.e_p.value = "10800"
    widok.e_cena.value, widok.e_k.value = "6,49", "200"
    widok.zapisz(None)
    litry, kwota = _wiersze(auto)[-1]
    assert (litry, kwota) == (30.82, 200.0)
    assert round(kwota / litry, 2) == 6.49, "cena to iloraz zapisanych litrów i kwoty"


def test_zapis_wymaga_dwoch_z_trzech(baza, formularz):
    auto = _auto_z_historia()
    widok = formularz(auto)
    widok.e_p.value = "10800"
    _wpisz(widok, "kwota", "200")
    widok.zapisz(None)
    assert utils.blad_kontrolki(widok.e_l) == utils.blad_kontrolki(widok.e_cena) == "Uzupełnij dwa z trzech pól"
    assert utils.blad_kontrolki(widok.e_k) is None
    assert len(_wiersze(auto)) == 2

    _wpisz(widok, "cena", "6,49")
    assert utils.blad_kontrolki(widok.e_l) is None, "błąd z poprzedniej próby znika przy wpisywaniu"


# ------------------------------------------------------------ nietypowa cena


def test_najblizsza_cena_zamiast_mediany():
    assert db.nietypowa_cena(6.9, [2.99, 3.09, 3.05]) is None, "benzyna po LPG to nie literówka"
    assert db.nietypowa_cena(3.2, [0.6, 0.62, 2.99]) is None, "szybka ładowarka, była już wcześniej"
    assert db.nietypowa_cena(6.49, []) is None, "bez historii nie ma z czym porównać"

    wynik = db.nietypowa_cena(64.9, [6.49, 6.39, 3.09])
    assert wynik["odniesienie"] == 6.49 and wynik["wyzsza"] and round(wynik["krotnosc"], 6) == 10
    assert db.nietypowa_cena(0.649, [6.49])["wyzsza"] is False

    assert db.nietypowa_cena(18.0, [6.0]) is not None, "trzy razy — już ostrzega"
    assert db.nietypowa_cena(17.9, [6.0]) is None


def test_ceny_odniesienia_z_okolicy_daty_i_tego_samego_zrodla(baza):
    auto = _auto("Hybryda plug-in")
    stary = _tankuj(auto, "10.03.2024", 5000, 40, 320, db.ENERGIA_PALIWO)   # 8,00
    _tankuj(auto, "20.03.2024", 5400, 40, 316, db.ENERGIA_PALIWO)          # 7,90
    _tankuj(auto, "01.09.2026", 30000, 40, 240, db.ENERGIA_PALIWO)         # 6,00
    _tankuj(auto, "05.09.2026", 30200, 10, 6, db.ENERGIA_PRAD)             # 0,60

    ceny = db.ceny_jednostkowe_w_poblizu(auto, "15.03.2024", db.ENERGIA_PALIWO, ile=2)
    assert sorted(round(c, 2) for c in ceny) == [7.9, 8.0], "wpis dopisany po latach porównuje się z tamtymi cenami"
    assert [round(c, 2) for c in db.ceny_jednostkowe_w_poblizu(auto, "10.09.2026", db.ENERGIA_PALIWO, ile=1)] == [6.0]
    assert [round(c, 2) for c in db.ceny_jednostkowe_w_poblizu(auto, "10.09.2026", db.ENERGIA_PRAD)] == [0.6]
    assert [round(c, 2) for c in db.ceny_jednostkowe_w_poblizu(
        auto, "15.03.2024", db.ENERGIA_PALIWO, wyklucz_id=stary, ile=1)] == [7.9]


def test_zdanie_o_nietypowej_cenie(baza):
    w = utils.symbol_waluty()
    assert utils.opis_nietypowej_ceny(
        {"cena": 64.9, "odniesienie": 6.49, "krotnosc": 10.0, "wyzsza": True}, db.ENERGIA_PALIWO) == (
        f"64,90 {w}/L — ok. 10 razy więcej niż w ostatnich tankowaniach (najbliżej 6,49 {w}/L). "
        "Sprawdź cyfry i przecinek w polach powyżej.")
    assert utils.opis_nietypowej_ceny(
        {"cena": 0.25, "odniesienie": 2.5, "krotnosc": 10.0, "wyzsza": False}, db.ENERGIA_PRAD) == (
        f"0,25 {w}/kWh — ok. 10 razy mniej niż w ostatnich ładowaniach (najbliżej 2,50 {w}/kWh). "
        "Sprawdź cyfry i przecinek w polach powyżej.")
    assert "0,004" in utils.opis_nietypowej_ceny(
        {"cena": 0.004, "odniesienie": 6.5, "krotnosc": 1625.0, "wyzsza": False}), "grosze nie udają zera"
    assert utils.opis_nietypowej_ceny(None) is None


def test_pasek_po_wyjsciu_z_pola_i_znika_od_razu_po_poprawce(baza, formularz):
    widok = formularz(_auto_z_historia())
    _wpisz(widok, "kwota", "293,99")
    _wpisz(widok, "ilosc", "4")
    assert not widok.baner_ceny.visible, "w trakcie pisania pierwsza cyfra daje dziesięć razy za dużo"
    _wpisz(widok, "ilosc", "4,53")
    assert not widok.baner_ceny.visible

    _wyjdz(widok, "ilosc")
    assert widok.baner_ceny.visible
    assert widok.t_ceny.value.startswith(f"64,90 {utils.symbol_waluty()}/L — ok. 10 razy więcej")
    assert f"najbliżej 6,50 {utils.symbol_waluty()}/L" in widok.t_ceny.value

    _wpisz(widok, "ilosc", "45,3")
    assert not widok.baner_ceny.visible, "poprawka gasi pasek od razu, bez wychodzenia z pola"


def test_nietypowa_cena_wymaga_potwierdzenia_przy_zapisie(baza, formularz):
    auto = _auto_z_historia()
    widok = formularz(auto)
    widok.e_p.value = "10800"
    _wpisz(widok, "ilosc", "4,53")
    _wpisz(widok, "kwota", "293,99")

    widok.zapisz(None)
    assert utils.blad_kontrolki(widok.e_cena) == "Nietypowa cena — kliknij Zapisz ponownie, aby potwierdzić"
    assert len(_wiersze(auto)) == 2, "pierwsze kliknięcie nic nie zapisuje"

    widok.zapisz(None)
    assert _wiersze(auto)[-1] == (4.53, 293.99), "drugie zapisuje to, co wpisano"


def test_otwarty_wpis_z_literowka_od_razu_pokazuje_pasek(baza, formularz):
    auto = _auto_z_historia()
    literowka = _tankuj(auto, "15.09.2026", 10600, 4.53, 293.99)
    widok = formularz(auto, literowka)
    assert widok.baner_ceny.visible, "edytowany wpis nie jest sam swoim odniesieniem"


def test_elektryk_mowi_o_kwh_i_ladowaniach(baza, formularz):
    auto = _auto("Elektryczny")
    _tankuj(auto, "01.09.2026", 10000, 40, 100, db.ENERGIA_PRAD)
    widok = formularz(auto)
    assert widok.e_cena.label == f"Cena za kWh ({utils.symbol_waluty()})"

    _wpisz(widok, "cena", "2,5")
    _wpisz(widok, "kwota", "100")
    assert widok.e_l.value == "40"
    assert widok.t_trojki.value == "kWh wyliczone z ceny i kwoty — wpisz je, a przeliczy się cena."

    _wpisz(widok, "cena", "25")  # przecinek zgubiony
    _wyjdz(widok, "cena")
    assert widok.e_l.value == "4"
    assert widok.baner_ceny.visible
    assert widok.t_ceny.value.startswith(f"25,00 {utils.symbol_waluty()}/kWh — ok. 10 razy więcej")
    assert "w ostatnich ładowaniach" in widok.t_ceny.value


def test_hybryda_porownuje_z_cenami_wybranego_zrodla(baza, formularz):
    auto = _auto("Hybryda plug-in")
    _tankuj(auto, "01.09.2026", 10000, 40, 260, db.ENERGIA_PALIWO)
    _tankuj(auto, "05.09.2026", 10100, 10, 6, db.ENERGIA_PRAD)
    widok = formularz(auto)
    assert widok.rodzaj_energii == db.ENERGIA_PALIWO

    _wpisz(widok, "ilosc", "10")
    _wpisz(widok, "kwota", "6,5")
    _wyjdz(widok, "kwota")
    assert widok.baner_ceny.visible, "0,65 za litr benzyny to literówka"

    widok.przelacznik_rodzaju.content.content.controls[1].on_click(None)  # „Prąd”
    assert widok.e_cena.label == f"Cena za kWh ({utils.symbol_waluty()})"
    assert not widok.baner_ceny.visible, "…a za kWh z gniazdka — zwykła cena"
