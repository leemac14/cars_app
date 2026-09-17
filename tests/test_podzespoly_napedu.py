"""Domyślne podzespoły składane z napędu — mapa zamiast listy na każde paliwo.

Wartość tej zmiany stoi na jednym: pozycja wspólna dla wszystkich aut istnieje
w kodzie DOKŁADNIE RAZ. Dlatego testy pilnują nie tyle konkretnych nazw, ile
tego, żeby mapa nie rozjechała się z TYPY_PALIWA, żeby składanie nie gubiło ani
nie dublowało pozycji i żeby „termin, nie interwał km” faktycznie dawał termin.
"""

import db
import pomoce


def nazwy(typ_paliwa):
    return [nazwa for nazwa, _, _ in db.domyslne_zadania(typ_paliwa)]


# ----------------------------------------------------------- samo składanie

def test_kazdy_typ_paliwa_ma_swoja_decyzje():
    """Równość, nie zawieranie: nowy typ paliwa ma wymusić decyzję, a nie po
    cichu dostać listę benzynową — na tym polegał cały problem."""
    assert set(db.PODZESPOLY_NAPEDU) == set(db.TYPY_PALIWA)


def test_benzyna_i_hybryda_to_sama_baza():
    assert nazwy("Benzyna") == list(db.DOMYSLNE_ZADANIA)
    assert nazwy("Hybryda") == list(db.DOMYSLNE_ZADANIA)


def test_elektryk_dostaje_to_samo_co_przed_zmiana():
    """Regresja na dawną stałą DOMYSLNE_ZADANIA_EV: skład listy elektryka po
    przejściu na mapę musi być ten sam, co przed nim."""
    assert set(nazwy("Elektryczny")) == {
        "Płyn hamulcowy", "Filtr kabinowy", "Płyn chłodzący baterii",
        "Wymiana opon / Kół", "Klocki hamulcowe", "Tarcze hamulcowe",
        "Przegląd układu wysokiego napięcia",
    }


def test_lpg_to_baza_plus_instalacja():
    """Auto na gaz jest autem benzynowym z instalacją — nic nie traci."""
    assert set(db.DOMYSLNE_ZADANIA) <= set(nazwy("LPG"))
    assert set(nazwy("LPG")) - set(db.DOMYSLNE_ZADANIA) == {
        "Filtr fazy lotnej", "Reduktor LPG", "Legalizacja butli LPG",
    }


def test_diesel_dostaje_swoje_filtry():
    assert set(nazwy("Diesel")) - set(db.DOMYSLNE_ZADANIA) == {
        "Filtr paliwa", "Filtr cząstek stałych (DPF)", "Pasek osprzętu",
    }


def test_plug_in_ma_i_spalanie_i_baterie():
    """Hybryda plug-in realnie serwisuje oba układy naraz."""
    lista = nazwy("Hybryda plug-in")
    assert "Olej silnikowy i filtr" in lista
    assert "Płyn chłodzący baterii" in lista


def test_nieznany_typ_paliwa_dostaje_baze():
    """Zachowanie sprzed zmiany dla wartości, której mapa nie zna."""
    assert nazwy("") == list(db.DOMYSLNE_ZADANIA)
    assert nazwy(None) == list(db.DOMYSLNE_ZADANIA)
    assert nazwy("Wodór") == list(db.DOMYSLNE_ZADANIA)


def test_zadna_lista_nie_ma_duplikatow_ani_emoji():
    for typ in db.TYPY_PALIWA:
        lista = nazwy(typ)
        klucze = [db.klucz_nazwy(n) for n in lista]
        assert len(klucze) == len(set(klucze)), typ
        assert lista == [db.bez_emoji(n) for n in lista], typ


def test_usuwane_pozycje_istnieja_w_bazie():
    """Literówka w „usun” nie usunęłaby niczego i nikt by tego nie zauważył."""
    bazowe = {db.klucz_nazwy(n) for n in db.DOMYSLNE_ZADANIA}
    for typ, modul in db.PODZESPOLY_NAPEDU.items():
        for nazwa in modul.get("usun", ()):
            assert db.klucz_nazwy(nazwa) in bazowe, (typ, nazwa)


def test_interwaly_trafiaja_w_istniejace_pozycje():
    """Klucz interwału pisany inaczej niż pozycja to interwał, który nigdy się
    nie przyłoży — i nic o tym nie powie."""
    wszystkie = set()
    for typ in db.TYPY_PALIWA:
        wszystkie |= set(nazwy(typ))
    for nazwa in db.DOMYSLNE_INTERWALY_MIESIACE:
        assert nazwa in wszystkie, nazwa


def test_legalizacja_butli_jest_terminem_a_nie_przebiegiem():
    """Butlę legalizuje się co dziesięć lat od badania — przejechane kilometry
    nie mają z tym nic wspólnego."""
    interwaly = {nazwa: miesiace for nazwa, miesiace, _ in db.domyslne_zadania("LPG")}
    assert interwaly["Legalizacja butli LPG"] == 120
    assert interwaly["Klocki hamulcowe"] is None


# ------------------------------------------------------------ zapis do bazy

def test_zakladanie_zapisuje_interwal_i_flage_opon(baza):
    auto = pomoce.utworz_pojazd("Gazowe")["auto_id"]

    db.dodaj_domyslne_zadania(auto, db.domyslne_zadania("LPG"))

    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT nazwa, interwal_km, interwal_miesiace, dotyczy_opon FROM zadania WHERE auto_id=?",
            (auto,),
        )
        wiersze = {w[0]: w[1:] for w in c.fetchall()}

    assert wiersze["Legalizacja butli LPG"] == (None, 120, 0)
    assert wiersze["Wymiana opon / Kół"][2] == 1
    assert wiersze["Reduktor LPG"] == (None, None, 0)


def test_dopisywanie_brakujacych_jest_idempotentne(baza):
    """Ta sama propozycja przyjęta dwa razy nie robi duplikatu."""
    auto = pomoce.utworz_pojazd("Po montazu LPG")["auto_id"]

    brakujace = db.brakujace_podzespoly(auto, "LPG")
    assert db.dodaj_domyslne_zadania(auto, brakujace) == len(brakujace)
    assert db.brakujace_podzespoly(auto, "LPG") == []
    assert db.dodaj_domyslne_zadania(auto, db.domyslne_zadania("LPG")) == 0


def test_pojazd_z_pomocy_juz_ma_olej(baza):
    """Pojazd testowy startuje z „Olej silnikowy i filtr”, więc propozycja dla
    benzyny musi być o tę pozycję krótsza — to samo, co po montażu instalacji
    w aucie już prowadzonym."""
    auto = pomoce.utworz_pojazd("Benzynowe")["auto_id"]

    brakujace = [n for n, _, _ in db.brakujace_podzespoly(auto, "Benzyna")]

    assert "Olej silnikowy i filtr" not in brakujace
    assert len(brakujace) == len(db.DOMYSLNE_ZADANIA) - 1


def test_wlasna_pisownia_nie_rodzi_duplikatu(baza):
    """Użytkownik wpisał pozycję po swojemu — propozycja ma tego nie dublować."""
    auto = pomoce.utworz_pojazd("Diesel")["auto_id"]
    with db.polacz_baze() as conn:
        conn.execute("INSERT INTO zadania (auto_id, nazwa) VALUES (?, ?)",
                     (auto, "filtr  paliwa "))

    brakujace = [n for n, _, _ in db.brakujace_podzespoly(auto, "Diesel")]

    assert "Filtr paliwa" not in brakujace
    assert "Filtr cząstek stałych (DPF)" in brakujace


def test_termin_bez_kilometrow_daje_powiadomienie(baza):
    """Cała obietnica „termin, nie interwał km” stoi na tym, że powiadomienia
    liczą zadanie z samym interwałem miesięcznym, bez przebiegu wymiany."""
    auto = pomoce.utworz_pojazd("Butla")["auto_id"]
    db.dodaj_domyslne_zadania(auto, db.domyslne_zadania("LPG"))
    with db.polacz_baze() as conn:
        conn.execute("UPDATE zadania SET data=? WHERE auto_id=? AND nazwa=?",
                     ("01.01.2010", auto, "Legalizacja butli LPG"))

    powiadomienia = db.pobierz_powiadomienia(auto, pomin_wyciszone=False)

    assert any("Legalizacja butli LPG" in " ".join(str(w) for w in p.values())
               for p in powiadomienia)


# --------------------------------------------------------- gotowe zestawy

def test_gotowe_zestawy_tylko_gdy_pojazd_ma_caly_sklad(baza):
    auto = pomoce.utworz_pojazd("Zestawy")["auto_id"]

    # Pojazd testowy ma jedną pozycję, więc żaden wbudowany zestaw nie jest
    # kompletny — a zestaw zaznaczający jedną trzecią siebie tylko myli.
    assert db.pakiety_dla_pojazdu(auto) == []

    db.dodaj_domyslne_zadania(auto, db.domyslne_zadania("Benzyna"))
    assert [n for n, _ in db.pakiety_dla_pojazdu(auto)] == list(db.PAKIETY_SERWISOWE)


def test_elektryk_nie_dostaje_zestawow_olejowych(baza):
    auto = pomoce.utworz_pojazd("Elektryk")["auto_id"]
    with db.polacz_baze() as conn:
        conn.execute("DELETE FROM zadania WHERE auto_id=?", (auto,))
    db.dodaj_domyslne_zadania(auto, db.domyslne_zadania("Elektryczny"))

    zestawy = [n for n, _ in db.pakiety_dla_pojazdu(auto)]

    assert "Przegląd olejowy" not in zestawy
    assert "Duży przegląd (rozrząd)" not in zestawy
    assert "Serwis hamulcowy (przód+tył)" in zestawy
    assert "Sezonowa wymiana opon" in zestawy


# ------------------------------------------- formularz nowego pojazdu (chipy)

def _formularz_nowego_pojazdu():
    """(widok, strona) — referencja do strony musi żyć razem z widokiem."""
    strona = pomoce.zbuduj_strone()
    widok = pomoce.zbuduj_widok(
        pomoce.klasy_widokow()["FormularzAutoView"], strona, pomoce.stan_aplikacji())
    return widok, strona


def test_formularz_przebudowuje_chipy_po_zmianie_napedu(baza):
    widok, _strona = _formularz_nowego_pojazdu()

    assert len(widok._wybrane_podzespoly()) == len(db.DOMYSLNE_ZADANIA)

    widok.e_pal.value = "LPG"
    widok.e_pal.on_select(None)

    ile_lpg = len(db.domyslne_zadania("LPG"))
    assert len(widok._wybrane_podzespoly()) == ile_lpg
    assert len(widok.pasek_podzespolow.content.controls) == ile_lpg


def test_odklikany_podzespol_wypada_z_listy_startowej(baza):
    widok, _strona = _formularz_nowego_pojazdu()
    assert not widok._czy_zmieniono()

    widok.pasek_podzespolow.content.controls[0].on_click(None)

    assert len(widok._wybrane_podzespoly()) == len(db.DOMYSLNE_ZADANIA) - 1
    assert widok._czy_zmieniono(), "odklikana pozycja to niezapisana zmiana formularza"
