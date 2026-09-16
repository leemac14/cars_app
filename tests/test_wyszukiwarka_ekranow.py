"""Wyszukiwarka: kiedy ekrany stoją nad wpisami, a kiedy schodzą pod nie.

Zasada „kto wpisuje »budżet«, chce ekran budżetu” jest słuszna dla nazw funkcji.
Ale „rozrząd” czy „olej” to słowa z danych — kto je wpisuje, szuka swojego wpisu,
a ekran łapał się na nie tylko przez słowa pomocnicze i mimo to wskakiwał na górę.

1. **Krótka fraza** (poniżej `DLUGA_FRAZA_OD` znaków) albo brak trafień we wpisy —
   wszystkie ekrany nad wpisami, jak dotąd.
2. **Długa fraza z trafieniami we wpisy** — każdy ekran osobno: trafienie w tytuł
   zostaje u góry, trafienie tylko w opis albo słowa pomocnicze schodzi pod wpisy
   („Powiązane ekrany”).
3. **Słowa pomocnicze od początku słowa** — „oc” nie trafia już w „samochód”,
   „klocki” ani „tryb nocny”. Tytuły pasują dowolnym fragmentem, jak dotąd.
"""

import flet as ft
import pytest

import audyty
import db
import pomoce
import utils

# Każda akcja „dostępna” — inaczej ekrany-akcje (motyw, kopia, usunięcie pojazdu)
# w ogóle nie brałyby udziału w dopasowaniu.
AKCJE = {e["akcja"]: (lambda: None) for e in utils.EKRANY if e.get("akcja")}


def identyfikatory(ekrany):
    return [e["id"] for e in ekrany]


def rozstaw(fraza, sa_wpisy, akcje=None):
    nad, pod = utils.rozstaw_ekrany(fraza, sa_wpisy, akcje=akcje)
    return identyfikatory(nad), identyfikatory(pod)


def znajdz(fraza):
    return identyfikatory(utils.znajdz_ekrany(fraza, akcje=AKCJE))


# ============================================================================
#  REGUŁA ROZSTAWIENIA
# ============================================================================

@pytest.mark.parametrize("fraza", ["oc", "lpg", "ole", "  ole  "])
def test_krotka_fraza_zostawia_wszystkie_ekrany_nad_wpisami(fraza):
    """Wszystkie cztery trafiają tylko w słowa pomocnicze, a i tak zostają u góry:
    trzy znaki to za mało, żeby uznać frazę za słowo z danych. Spacje na brzegach
    się nie liczą."""
    nad, pod = rozstaw(fraza, sa_wpisy=True)
    assert nad and pod == []


def test_dluga_fraza_z_danych_oddaje_gore_wpisom():
    assert rozstaw("olej", sa_wpisy=True) == ([], ["magazyn", "serwis"])
    assert rozstaw("rozrząd", sa_wpisy=True) == ([], ["serwis"])
    assert rozstaw("  olej  ", sa_wpisy=True) == ([], ["magazyn", "serwis"])


def test_bez_trafien_we_wpisy_ekrany_zostaja_na_gorze():
    """Wpisów nie ma, więc nie ma z czym przegrać."""
    assert rozstaw("rozrząd", sa_wpisy=False) == (["serwis"], [])
    assert rozstaw("olej", sa_wpisy=False) == (["magazyn", "serwis"], [])


def test_trafienie_w_tytul_trzyma_ekran_u_gory_osobno_dla_kazdego():
    assert rozstaw("opony", sa_wpisy=True) == (["opony"], ["magazyn"])
    assert rozstaw("budżet", sa_wpisy=True) == (["budzet"], [])
    # Fraza ze środka tytułu to też trafienie w tytuł.
    assert rozstaw("koszt", sa_wpisy=True) == (["inne", "podzial"], ["import", "kalkulator", "porownanie"])


@pytest.mark.parametrize("sa_wpisy", [True, False])
@pytest.mark.parametrize("fraza", ["kosz", "koszt", "opony", "olej", "rok", "oc", "pojazd", "przegląd"])
def test_rozstawienie_dzieli_te_same_ekrany_niczego_nie_gubiac(fraza, sa_wpisy):
    """Te same ekrany w tej samej kolejności co `znajdz_ekrany`, tylko rozdzielone.
    Limit obejmuje obie grupy razem — „kosz” ma dziewięć trafień, pokazuje sześć."""
    nad, pod = utils.rozstaw_ekrany(fraza, sa_wpisy, akcje=AKCJE)
    assert identyfikatory(nad + pod) == znajdz(fraza)
    assert len(nad) + len(pod) <= 6


# ============================================================================
#  SŁOWA POMOCNICZE OD POCZĄTKU SŁOWA
# ============================================================================

def test_slowa_pomocnicze_pasuja_tylko_od_poczatku_slowa():
    # Dowolnym fragmentem „oc” trafiało w osiem ekranów: „samochód”, „klocki”,
    # „tryb nocny”, „przywróć”, „roczne”…
    assert znajdz("oc") == ["pojazd"]
    # Końcówka „rozrząd” nie zaczyna żadnego słowa.
    assert "serwis" not in znajdz("rząd")
    # Fraza wielowyrazowa liczy się od swojego początku.
    assert znajdz("tryb noc") == ["motyw"]
    assert "opony" in znajdz("wymiana op")
    # Bez ogonków i bez względu na wielkość liter — jak dotąd.
    assert znajdz("ROZRZAD") == ["serwis"]


def test_fraza_nie_skleja_sie_przez_granice_slow_pomocniczych():
    """„oc” i „ac” to dwa osobne słowa Karty pojazdu, a nie jedno „oc ac”."""
    assert znajdz("oc ac") == []


def test_tytul_dalej_pasuje_dowolnym_fragmentem():
    assert {"eksport", "import"} <= set(znajdz("port"))
    assert "kalkulator" in znajdz("ulator")


# ============================================================================
#  EKRAN WYSZUKIWARKI
# ============================================================================

def teksty(kontrolka):
    wynik, do_odwiedzenia = [], [kontrolka]
    while do_odwiedzenia:
        biezaca = do_odwiedzenia.pop(0)
        if isinstance(biezaca, ft.Text) and biezaca.value:
            wynik.append(biezaca.value)
        do_odwiedzenia.extend(dziecko for _, dziecko in audyty._dzieci(biezaca))
    return wynik


def szukaj(widok, fraza):
    """(napisy sekcji nad wpisami, napisy sekcji pod wpisami) — pusta lista, gdy
    sekcja jest schowana."""
    widok.pole_wyszukiwarki.value = fraza
    widok._wyszukaj(None)
    return (teksty(widok.sekcja_ekranow) if widok.sekcja_ekranow.visible else [],
            teksty(widok.sekcja_ekranow_pod) if widok.sekcja_ekranow_pod.visible else [])


@pytest.fixture
def wyszukiwarka(baza, monkeypatch):
    from views.search_view import SzukajView

    dane = pomoce.utworz_pojazd(z_zalacznikami=False)
    with db.polacz_baze() as conn:
        conn.execute(
            "INSERT INTO inne_koszty (auto_id, data, kategoria, nazwa, kwota) VALUES (?,?,?,?,?)",
            (dane["auto_id"], "2026-03-01", db.KATEGORIA_INNE_DROGOWE, "Łatanie opony po kapciu", 80.0),
        )
    strona = pomoce.zbuduj_strone()
    widok = SzukajView(strona.page, pomoce.stan_aplikacji(dane["auto_id"], "Testowy"))
    # Strona trzyma sesję przez weakref — musi żyć tak długo jak widok.
    widok._strona_testowa = strona
    # Widok nie jest wpięty w stronę, a samo odświeżenie nie jest tu sprawdzane.
    monkeypatch.setattr(widok, "update", lambda *a, **k: None)
    return widok


def test_fraza_z_danych_stawia_wpisy_nad_ekranami(wyszukiwarka):
    nad, pod = szukaj(wyszukiwarka, "olej")
    assert wyszukiwarka.lista_wynikow.controls, "„olej” trafia w podzespół i część z magazynu"
    assert nad == []
    assert pod[0] == "Powiązane ekrany"
    assert {"Magazyn", "Podzespoły i interwały"} <= set(pod)
    kolejnosc = wyszukiwarka.controls
    assert kolejnosc.index(wyszukiwarka.lista_wynikow) < kolejnosc.index(wyszukiwarka.sekcja_ekranow_pod)


def test_tytul_u_gory_a_slowa_pomocnicze_pod_wpisami(wyszukiwarka):
    nad, pod = szukaj(wyszukiwarka, "opony")
    assert wyszukiwarka.lista_wynikow.controls, "„opony” trafia w inny koszt"
    assert nad[:2] == ["Ekrany i funkcje", "Opony"]
    assert "Magazyn" in pod and "Opony" not in pod


def test_bez_trafien_we_wpisy_ekran_zostaje_na_gorze(wyszukiwarka):
    nad, pod = szukaj(wyszukiwarka, "licznik")
    assert wyszukiwarka.lista_wynikow.controls == []
    assert "Historia przebiegu" in nad and pod == []
    assert "pasuje za to ekran powyżej" in wyszukiwarka.tekst_pomocniczy.value


def test_kwota_i_krotka_fraza_chowaja_obie_sekcje(wyszukiwarka):
    """Szybka zamiana „opony” na „450” to jedno wywołanie po ciszy — sekcja ekranów
    zostawała wtedy z poprzedniej frazy, bo chowała się tylko przy pustym polu."""
    szukaj(wyszukiwarka, "opony")
    assert szukaj(wyszukiwarka, "450") == ([], [])
    szukaj(wyszukiwarka, "olej")
    assert szukaj(wyszukiwarka, "o") == ([], [])


def test_obie_sekcje_przechodza_audyty(wyszukiwarka):
    szukaj(wyszukiwarka, "opony")
    assert wyszukiwarka.sekcja_ekranow.visible and wyszukiwarka.sekcja_ekranow_pod.visible
    assert audyty.znajdz_expand_bez_ograniczenia(wyszukiwarka) == []
    assert audyty.znajdz_pogrubienia_na_drugim_planie(wyszukiwarka) == []
