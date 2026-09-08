"""Jedno miejsce na skład liczby — i dowód, że naprawdę jedno.

Ekran, eksport CSV, generator grafiki i raport PDF miały po własnej kopii tych
samych trzech linijek: zaokrąglenie, przecinek dziesiętny, separator tysięcy.
Zaokrąglenia akurat się zgadzały — ale zgadzały się PRZYPADKIEM, bo nic ich nie
trzymało razem. Rozjazd o grosz między ekranem a eksportem jest błędem, którego
nikt nie zgłosi, a każdy zauważy.

Dziś skład robi `db.liczba_na_tekst` i tylko on. Reszta to opakowania, które
podejmują jedną decyzję: co pokazać, gdy wartości NIE MA. Ekran woli zero,
eksport pustą komórkę — i to jest różnica zamierzona, więc też ma swój test.

Drugą połowę pilnuje `audyty.audyt_recznego_formatowania`: nowe ręczne
składanie liczby zapala test, zamiast rozjeżdżać się latami.
"""

import pathlib
import random
import re
import sys

sys.path[:0] = [str(pathlib.Path(__file__).resolve().parent), str(pathlib.Path(__file__).resolve().parents[1])]

import pytest  # noqa: E402

import db  # noqa: E402
import log  # noqa: E402
import utils  # noqa: E402


# Separator tysięcy zdejmujemy TYLKO spomiędzy cyfr — spacja przed jednostką
# („7,5 l/100km") jest częścią tekstu, nie liczby.
_SEPARATOR_MIEDZY_CYFRAMI = re.compile(rf"(?<=\d){re.escape(db.SEPARATOR_TYSIECY)}(?=\d)")


def _cyfry(tekst):
    """Tekst bez separatora tysięcy — do porównania ekranu z eksportem."""
    return _SEPARATOR_MIEDZY_CYFRAMI.sub("", tekst)


def _probki():
    """Wartości losowe plus połówki i ćwiartki, na których zaokrąglanie się psuje."""
    losowe = random.Random(7)
    wartosci = [losowe.uniform(-100000, 100000) for _ in range(4000)]
    wartosci += [round(losowe.uniform(-1000, 1000), 2) for _ in range(4000)]
    for calkowita in range(-40, 41):
        wartosci += [calkowita + u for u in (0.5, 0.05, 0.005, 0.125, 0.135, 0.145, 0.995)]
    return wartosci


# ----------------------------------------------------- ekran kontra eksport


def test_ekran_i_eksport_zgadzaja_sie_co_do_liczby():
    """Ta sama wartość ma dać tę samą liczbę — różnić się wolno wyłącznie
    separatorem tysięcy, którego w arkuszu być nie może."""
    rozjazdy = []
    for decimale in (0, 1, 2):
        for wartosc in _probki():
            ekran = _cyfry(utils.formatuj_liczba(wartosc, decimale))
            eksport = db.formatuj_liczba_eksport(wartosc, decimale)
            if ekran != eksport:
                rozjazdy.append((decimale, wartosc, ekran, eksport))

    assert rozjazdy == [], "\n".join(
        f"  decimale={d} {w!r}: ekran {e!r} kontra eksport {x!r}" for d, w, e, x in rozjazdy[:10]
    )


@pytest.mark.parametrize("wartosc, decimale, oczekiwany", [
    (0.5, 0, "0"),      # zaokrąglanie „do parzystej" — takie samo po obu stronach
    (1.5, 0, "2"),
    (2.5, 0, "2"),
    (-0.5, 0, "0"),     # nie „-0": minus przy zerze to nie jest liczba do pokazania
    (1.005, 2, "1,00"),  # klasyk zapisu binarnego: 1.005 to naprawdę 1.00499…
    (2.675, 2, "2,67"),
    (0.045, 2, "0,04"),
    (1234.5678, 1, "1234,6"),
])
def test_zaokraglenie_jest_takie_samo_po_obu_stronach(wartosc, decimale, oczekiwany):
    """Wartości zapisane wprost, żeby zmiana zaokrąglania była WIDOCZNA w diffie,
    a nie tylko w wyniku porównania dwóch funkcji ze sobą."""
    assert db.formatuj_liczba_eksport(wartosc, decimale) == oczekiwany
    assert _cyfry(utils.formatuj_liczba(wartosc, decimale)) == oczekiwany


def test_separator_tysiecy_tylko_na_ekranie():
    assert utils.formatuj_liczba(1234567.891, 2) == "1 234 567,89"
    assert utils.formatuj_liczba(1234567.891, 0) == "1 234 568"
    assert utils.formatuj_liczba(-98765.4, 2) == "-98 765,40"
    # W arkuszu spacja w liczbie robi z niej tekst — i kolumna przestaje się sumować.
    assert db.formatuj_liczba_eksport(1234567.891, 2) == "1234567,89"
    assert db.SEPARATOR_TYSIECY not in db.formatuj_liczba_eksport(1234567.891, 2)


# ------------------------------------------------------- brak wartości


def test_ekran_pokazuje_zero_a_eksport_pusta_komorke():
    """Jedyna zamierzona różnica między nimi. Pusty kafelek na kokpicie myli
    bardziej niż „0,00"; zero dopisane do arkusza kłamie o średniej kolumny."""
    for brak in (None, ""):
        assert utils.formatuj_liczba(brak, 2) == "0,00"
        assert db.formatuj_liczba_eksport(brak, 2) == ""


def test_rdzen_mowi_wprost_ze_to_nie_liczba():
    """`liczba_na_tekst` nie zgaduje za wołającego — zwraca None i zostawia mu
    decyzję. Cała różnica polityk bierze się z tego jednego miejsca."""
    for nie_liczba in (None, "", "abc", "   ", "-", float("nan"), float("inf")):
        assert db.liczba_na_tekst(nie_liczba) is None

    assert db.liczba_na_tekst(0) == "0,00"
    assert db.liczba_na_tekst(0, 0) == "0"


def test_tekst_nieliczbowy_przechodzi_przez_eksport_bez_zmian():
    """W eksporcie bywają kolumny opisowe — nie wolno ich zamienić na zero."""
    assert db.formatuj_liczba_eksport("Warsztat u Janka") == "Warsztat u Janka"


# --------------------------------------------------- liczba zapisana po polsku


@pytest.mark.parametrize("zapis, oczekiwany", [
    ("12,5", "12,50"),
    ("1 234,56", "1234,56"),
    ("45,20 zł", "45,20"),
    ("1,234.56", "1234,56"),
])
def test_liczba_zapisana_po_polsku_jest_rozumiana(zapis, oczekiwany):
    """Przed scaleniem `formatuj_liczba("12,5")` dawało „0,00", a eksport tej
    samej wartości „12,5". Dwa różne zdania o tej samej liczbie — dokładnie ten
    rodzaj rozjazdu, dla którego to zadanie powstało."""
    assert db.formatuj_liczba_eksport(zapis, 2) == oczekiwany
    assert _cyfry(utils.formatuj_liczba(zapis, 2)) == oczekiwany


def test_nan_i_inf_nie_wychodza_na_ekran():
    """`f"{nan:,.2f}"` daje „nan", a po doklejeniu przecinka dziesiętnego —
    „nan,". Taki napis trafiał wcześniej wprost na kafelek."""
    for nieliczba in (float("nan"), float("inf"), float("-inf")):
        assert utils.formatuj_liczba(nieliczba, 2) == "0,00"
        assert db.formatuj_liczba_eksport(nieliczba, 2) == ""


# ------------------------------------------------------------ rozmiary plików


@pytest.mark.parametrize("bajty", [0, 1, 512, 1023, 1024, 1025, 2048, 48000,
                                   1024 * 1024 - 1, 1024 * 1024, 3 * 1024 * 1024, 12345678])
def test_rozmiar_w_bajtach_ma_jedna_postac(bajty):
    """`log.py` ma WŁASNĄ kopię tej funkcji, bo nie importuje niczego z projektu
    — inaczej `db` nie mogłoby z niego korzystać. Kopia jest świadoma, więc musi
    być pilnowana: „1.5 MB" w koszu i „1,5 MB" w Ustawieniach to ta sama
    aplikacja mówiąca dwoma głosami."""
    assert db.formatuj_rozmiar(bajty) == log.formatuj_rozmiar(bajty)


def test_rozmiar_wyglada_jak_trzeba():
    assert db.formatuj_rozmiar(512) == "512 B"
    assert db.formatuj_rozmiar(2048) == "2,0 kB"
    assert db.formatuj_rozmiar(3 * 1024 * 1024) == "3,0 MB"
    assert "." not in db.formatuj_rozmiar(2048), "przecinek dziesiętny, tak jak wszędzie indziej"


# ------------------------------------------------------------ zużycie paliwa


def test_zuzycie_liczy_sie_raz_a_formatuje_dwa_razy(baza):
    """`utils.formatuj_spalanie` (ekran) i `db.formatuj_zuzycie_tekst` (dane)
    mają wspólne PRZELICZENIE od dawna. Po scaleniu formatowania mają też
    wspólny skład liczby, więc wolno im się różnić wyłącznie separatorem."""
    for na_100km in (7.5, 5.05, 12.345, 0.5):
        ekran = utils.formatuj_spalanie(na_100km)
        dane = db.formatuj_zuzycie_tekst(na_100km)
        assert _cyfry(ekran) == dane, f"{na_100km}: ekran {ekran!r} kontra dane {dane!r}"
