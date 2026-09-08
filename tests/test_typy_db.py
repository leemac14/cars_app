"""Adnotacje zwrotu warstwy danych kontra to, co funkcje NAPRAWDĘ zwracają.

`pobierz_dane_timeline` urosło kiedyś z ośmiu elementów krotki do dziewięciu.
Rozpakowanie w innym pliku wywaliło się dopiero w czasie działania
(`too many values to unpack`) — u kogoś, kto akurat wszedł na ten ekran mając
dane. Adnotacja zwrotu opisuje dziś ten kształt, ale sama adnotacja niczego nie
sprawdza: Python jej nie egzekwuje, a nieaktualna kłamie równie gładko, jak
kłamał komentarz w docstringu.

Dlatego kształt pilnują dwie rzeczy naraz:

* **ten plik** — woła funkcje na bazie testowej i porównuje wynik z adnotacją;
  łapie zmianę U ŹRÓDŁA, w tej samej chwili, w której krotka rośnie;
* **`audyty.audyt_ksztaltu_wynikow`** — czyta AST i porównuje z adnotacją każde
  rozpakowanie i każdy indeks u KONSUMENTÓW.

Razem zamykają obieg: krotka rośnie → czerwony test wykonania → poprawiasz
adnotację → czerwony audyt na każdym miejscu, które trzeba dostosować.

Typów elementów nie sprawdzamy twardo: `None` przechodzi zawsze, bo w SQLite
prawie każda kolumna może być NULL i test sprawdzałby wtedy dane testowe,
a nie kod. Liczba elementów krotki — owszem, twardo. To ona się psuje.
"""

import types
import typing

import pytest

import audyty
import db
import pomoce


# Argumenty do wywołania każdej funkcji o znanym kształcie wyniku. Nieznana
# funkcja = błąd testu, a nie ciche pominięcie: nowa adnotacja ma się zgłosić po
# swoje wywołanie, inaczej dopisywałoby się adnotacje, których nikt nie sprawdza.
# `k` to kontekst: k["id"] — identyfikatory z utworz_pojazd(), k["tmp"] — katalog.
WYWOLANIA = {
    "generuj_eksport_csv": lambda k: (db.pobierz_dane_eksportu(k["id"]["auto_id"], list(db.KATEGORIE_EKSPORTU)),),
    "napraw_sciezki_zalacznikow": lambda k: (),
    "parsuj_zapytanie_kwotowe": lambda k: ("powyżej 100 zł",),
    "pobierz_budzety": lambda k: (k["id"]["auto_id"],),
    "pobierz_checklisty": lambda k: (k["id"]["auto_id"],),
    "pobierz_dane_timeline": lambda k: (k["id"]["auto_id"],),
    "pobierz_historie_przebiegu": lambda k: (k["id"]["auto_id"],),
    "pobierz_kolejke_sync": lambda k: (),
    "pobierz_kosz": lambda k: (),
    "pobierz_koszty_innych_wg_kategorii": lambda k: (k["id"]["auto_id"],),
    "pobierz_koszty_miesieczne": lambda k: (k["id"]["auto_id"],),
    "pobierz_nagrobki": lambda k: (k["id"]["auto_id"],),
    "pobierz_notatke": lambda k: ("tankowania", k["id"]["tankowanie"]),
    "pobierz_odlozone_powiadomienia": lambda k: (k["id"]["auto_id"],),
    "pobierz_ostatnia_aktywnosc": lambda k: (k["id"]["auto_id"],),
    "pobierz_pakiety_wlasne": lambda k: (k["id"]["auto_id"],),
    "pobierz_pelna_historie_przebiegu": lambda k: (k["id"]["auto_id"],),
    "pobierz_pojazdy": lambda k: (),
    "pobierz_powiadomienia": lambda k: (k["id"]["auto_id"],),
    "pobierz_pozycje_wizyty": lambda k: (k["id"]["wizyta"],),
    "pobierz_przebieg_miesieczny": lambda k: (k["id"]["auto_id"],),
    "pobierz_przypomnienia_o_oponach": lambda k: (k["id"]["auto_id"],),
    "pobierz_serie_dziennego_przebiegu": lambda k: (k["id"]["auto_id"],),
    "pobierz_serie_kosztu_km": lambda k: (k["id"]["auto_id"],),
    "pobierz_serie_spalania": lambda k: (k["id"]["auto_id"],),
    "pobierz_sprzedane_pojazdy": lambda k: (),
    "pobierz_statystyki_energii": lambda k: (k["id"]["auto_id"],),
    "pobierz_tagi": lambda k: (k["id"]["auto_id"],),
    "pobierz_trasy_szablony": lambda k: (k["id"]["auto_id"],),
    "pobierz_uzyte_czesci_wizyty": lambda k: (k["id"]["wizyta"],),
    "pobierz_uzyte_czesci_wpisu": lambda k: (k["id"]["historia"],),
    "pobierz_warsztaty": lambda k: (k["id"]["auto_id"],),
    "pobierz_wydatki_cykliczne": lambda k: (k["id"]["auto_id"],),
    "przelicz_zuzycie": lambda k: (7.5,),
    "sprawdz_kopie_przed_wczytaniem": lambda k: (db.BAZA_DANYCH,),
    "stan_budzetow": lambda k: (k["id"]["auto_id"],),
    "utworz_wizyte_z_do_zrobienia": lambda k: (k["id"]["auto_id"], [k["id"]["do_zrobienia"]]),
    "wczytaj_plik_csv": lambda k: (str(k["csv"]),),
    "znajdz_duplikaty_nazw": lambda k: (k["id"]["auto_id"],),
}


def _nazwa_typu(wartosc):
    return type(wartosc).__name__


def niezgodnosc(wartosc, adnotacja, gdzie="wynik"):
    """Opis pierwszej niezgodności wartości z adnotacją albo None.

    `None` przepuszczamy zawsze — patrz docstring modułu."""
    if wartosc is None or adnotacja is typing.Any:
        return None

    zrodlo = typing.get_origin(adnotacja)
    argumenty = typing.get_args(adnotacja)

    if zrodlo in (types.UnionType, typing.Union):
        if any(w is not type(None) and niezgodnosc(wartosc, w, gdzie) is None for w in argumenty):
            return None
        return f"{gdzie}: {_nazwa_typu(wartosc)} nie pasuje do {adnotacja}"

    if zrodlo is list:
        if not isinstance(wartosc, list):
            return f"{gdzie}: {_nazwa_typu(wartosc)} zamiast listy"
        for numer, element in enumerate(wartosc):
            blad = niezgodnosc(element, argumenty[0], f"{gdzie}[{numer}]") if argumenty else None
            if blad:
                return blad
        return None

    if zrodlo is tuple:
        if not isinstance(wartosc, tuple):
            return f"{gdzie}: {_nazwa_typu(wartosc)} zamiast krotki"
        if Ellipsis in argumenty:
            return None
        if len(wartosc) != len(argumenty):
            return (f"{gdzie}: krotka ma {len(wartosc)} elementów, "
                    f"a adnotacja mówi o {len(argumenty)}")
        for numer, (element, oczekiwany) in enumerate(zip(wartosc, argumenty)):
            blad = niezgodnosc(element, oczekiwany, f"{gdzie}[{numer}]")
            if blad:
                return blad
        return None

    if zrodlo is dict or adnotacja is dict:
        if not isinstance(wartosc, dict):
            return f"{gdzie}: {_nazwa_typu(wartosc)} zamiast słownika"
        return None

    if isinstance(adnotacja, type):
        # `float` przyjmuje też `int` — tak samo widzą to wszystkie sprawdzacze
        # typów, a SUM po pustym zbiorze potrafi zwrócić zero jako int.
        dozwolone = (int, float) if adnotacja is float else adnotacja
        if not isinstance(wartosc, dozwolone):
            return f"{gdzie}: {_nazwa_typu(wartosc)} zamiast {adnotacja.__name__}"

    return None


@pytest.fixture
def kontekst(baza, tmp_path):
    """Pojazd z wpisem w każdej tabeli plus objętość danych — im więcej wierszy,
    tym więcej krotek do sprawdzenia."""
    identyfikatory = pomoce.utworz_pojazd("Typowany")
    pomoce.dosyp_dane(identyfikatory["auto_id"])

    plik_csv = tmp_path / "import.csv"
    plik_csv.write_text("Data;Kwota\n01.02.2026;120,50\n", encoding="utf-8")

    return {"id": identyfikatory, "tmp": tmp_path, "csv": plik_csv}


# --------------------------------------------------------------- pokrycie


def test_kazdy_znany_ksztalt_ma_wywolanie():
    """Adnotacja bez wywołania to adnotacja, której nikt nie sprawdza."""
    bez_wywolania = sorted(set(audyty.ksztalty_db()) - set(WYWOLANIA))
    assert bez_wywolania == [], (
        "funkcje `db` z adnotacją kształtu, których ten test nie woła: "
        + ", ".join(bez_wywolania)
        + "\n\nDopisz je do WYWOLANIA w tym pliku."
    )


def test_wywolania_nie_gnija():
    """Wpis dla funkcji, która straciła adnotację albo zniknęła, tylko myli."""
    zbedne = sorted(set(WYWOLANIA) - set(audyty.ksztalty_db()))
    assert zbedne == [], (
        "wywołania bez odpowiadającej adnotacji kształtu: " + ", ".join(zbedne)
    )


def test_kazda_konsumowana_funkcja_db_ma_adnotacje():
    """Nowa funkcja zwracająca krotki, której wynik ktoś już rozpakowuje, ma
    powiedzieć jak wygląda — inaczej audyt kształtu po cichu jej nie widzi."""
    bez_adnotacji = audyty.funkcje_db_konsumowane_bez_adnotacji()
    assert bez_adnotacji == [], (
        "wynik tych funkcji `db` jest rozpakowywany albo indeksowany, a nie mają "
        "adnotacji zwrotu: " + ", ".join(bez_adnotacji)
    )


# ------------------------------------------------------- wykonanie kontra kod


@pytest.mark.parametrize("nazwa", sorted(WYWOLANIA))
def test_funkcja_zwraca_to_co_deklaruje(kontekst, nazwa):
    funkcja = getattr(db, nazwa)
    adnotacja = funkcja.__annotations__["return"]

    wynik = funkcja(*WYWOLANIA[nazwa](kontekst))

    blad = niezgodnosc(wynik, adnotacja)
    assert blad is None, (
        f"db.{nazwa}() nie zwraca tego, co deklaruje — {blad}.\n"
        f"Adnotacja: {adnotacja}\n\n"
        "Jeśli zmiana kształtu jest zamierzona, popraw adnotację i uruchom audyt "
        "kształtu (python -m pytest tests/test_audyty.py -k ksztalt) — pokaże "
        "wszystkie miejsca, które trzeba dostosować."
    )


def test_sprawdzacz_ksztaltu_lapie_zla_arnosc():
    """Test samego sprawdzacza — inaczej cicho przestałby cokolwiek łapać."""
    assert niezgodnosc([(1, "a")], list[tuple[int, str]]) is None
    assert "krotka ma 3 elementów" in niezgodnosc([(1, "a", 2)], list[tuple[int, str]])
    assert "zamiast listy" in niezgodnosc((1, 2), list[tuple[int, str]])
    assert "zamiast krotki" in niezgodnosc([{"a": 1}], list[tuple[int, str]])
    assert "zamiast słownika" in niezgodnosc([(1,)], list[dict[str, typing.Any]])


def test_sprawdzacz_ksztaltu_przepuszcza_none_i_unie():
    assert niezgodnosc([("a", None)], list[tuple[str, float]]) is None, "NULL z bazy ma przechodzić"
    assert niezgodnosc(None, tuple[int, int]) is None
    assert niezgodnosc((1, None, "x"), tuple[int, str | None, str]) is None
    assert niezgodnosc([(1, 2)], list[tuple[int, float]]) is None, "int tam, gdzie float, jest w porządku"
    assert "zamiast int" in niezgodnosc([(1.5, 2)], list[tuple[int, float]])
