"""Paski terminów, budżetów i zużycia: wypełnianie od zera przy wejściu.

Pasek terminu wypełnia się dopiero, gdy termin wchodzi w próg powiadomienia —
„zielony i pusty" znaczy „jeszcze długo". Decyzja dobra, ale z jednego spojrzenia
nieczytelna: pusty pasek wygląda jak brak danych. Ruch przy wejściu pokazuje,
GDZIE pasek się zatrzymał, i to jest cała jego treść. Stąd dwie rzeczy, których
te testy pilnują: że pasek kończy dokładnie tam, gdzie ma, i że pasek, który nie
ma się czym wypełnić, faktycznie nie drga.
"""

import asyncio
from datetime import datetime, timedelta

import flet as ft
import pytest

import db
import pomoce
import utils


class StronaZapisujaca:
    def __init__(self):
        self.klatki = 0

    def update(self, *kontrolki):
        self.klatki += 1


def odtworz(scena):
    asyncio.run(scena.odtworz(StronaZapisujaca()))


def paski(kontrolka, limit=5000):
    """Wszystkie ProgressBary z poddrzewa, w kolejności od góry."""
    zebrane = []
    do_odwiedzenia = [kontrolka]
    while do_odwiedzenia and len(zebrane) < limit:
        biezaca = do_odwiedzenia.pop(0)
        if isinstance(biezaca, ft.ProgressBar):
            zebrane.append(biezaca)
        for nazwa in ("controls", "content", "appbar", "floating_action_button"):
            wartosc = getattr(biezaca, nazwa, None)
            if isinstance(wartosc, (list, tuple)):
                do_odwiedzenia.extend(w for w in wartosc if isinstance(w, ft.Control))
            elif isinstance(wartosc, ft.Control):
                do_odwiedzenia.append(wartosc)
    return zebrane


def opoznienia(scena):
    return sorted({o for _, o in scena._tory} | {o for _, o in scena._skoki})


def ustaw_terminy(auto_id, *dni):
    """Daty dokumentów liczone od dziś — tyle dni do każdego z nich."""
    kolumny = [k for _, k, _ in db.TERMINY_DOKUMENTOW][:len(dni)]
    dzis = datetime.now()
    with db.polacz_baze() as conn:
        conn.execute(
            f"UPDATE samochody SET {', '.join(k + '=?' for k in kolumny)} WHERE id=?",
            [(dzis + timedelta(days=d)).strftime("%d.%m.%Y") for d in dni] + [auto_id],
        )


# ============================================================================
#  KASKADA
# ============================================================================

def test_kolejne_wiersze_startuja_pozniej():
    scena = utils.ScenaWejscia(czas_ms=40, kaskada=True)

    kroki = [scena.nastepny_wiersz() for _ in range(4)]

    assert kroki == [0, utils.KROK_KASKADY_MS, 2 * utils.KROK_KASKADY_MS, 3 * utils.KROK_KASKADY_MS]


def test_kaskada_ma_gorny_limit():
    """Przy dwudziestu paskach ostatni ruszałby po dwóch sekundach — a to już nie
    jest wejście na ekran, tylko ładowanie."""
    scena = utils.ScenaWejscia(czas_ms=40, kaskada=True)

    kroki = [scena.nastepny_wiersz() for _ in range(30)]

    assert max(kroki) == utils.MAKS_OPOZNIENIA_KASKADY_MS
    assert kroki[-1] == kroki[-2], "od pewnego momentu paski startują razem"


def test_scena_bez_kaskady_nie_rozsuwa_wierszy():
    scena = utils.ScenaWejscia(czas_ms=40)

    assert [scena.nastepny_wiersz() for _ in range(3)] == [0, 0, 0]

    scena.wskaznik(ft.ProgressBar(value=0.5))
    assert opoznienia(scena) == [0]


def test_tor_stoi_do_swojej_kolejki_i_konczy_na_wartosci():
    scena = utils.ScenaWejscia(czas_ms=60, kaskada=True)
    scena.nastepny_wiersz()
    pierwszy = scena.wskaznik(ft.ProgressBar(value=1.0))
    scena.nastepny_wiersz()
    drugi = scena.wskaznik(ft.ProgressBar(value=1.0))

    podglad = []
    scena._tory.append((lambda p: podglad.append((pierwszy.value, drugi.value)), 0))
    odtworz(scena)

    ruszyl_pierwszy = next((i for i, (a, _) in enumerate(podglad) if a > 0), None)
    ruszyl_drugi = next((i for i, (_, b) in enumerate(podglad) if b > 0), None)
    assert ruszyl_pierwszy is not None and ruszyl_drugi is not None
    assert ruszyl_pierwszy < ruszyl_drugi, "drugi pasek ma ruszyć PO pierwszym"
    assert (pierwszy.value, drugi.value) == (1.0, 1.0)


def test_kaskada_daje_paskom_krotszy_czas_niz_liczbom():
    """Pasek w kaskadzie jedzie krócej niż liczba na kafelku — inaczej ostatni
    z sześciu kończyłby dopiero po sekundzie."""
    assert utils.ScenaWejscia(kaskada=True).czas_ms == utils.CZAS_PASKA_MS
    assert utils.ScenaWejscia().czas_ms == utils.CZAS_ANIMACJI_MS
    assert utils.CZAS_PASKA_MS < utils.CZAS_ANIMACJI_MS
    assert utils.ScenaWejscia(kaskada=True, czas_ms=90).czas_ms == 90, "jawny czas ma pierwszeństwo"


def test_scena_z_kaskada_trwa_dluzej_o_najdluzsze_opoznienie():
    scena = utils.ScenaWejscia(czas_ms=200, kaskada=True)
    for _ in range(3):
        scena.nastepny_wiersz()
        scena.wskaznik(ft.ProgressBar(value=0.5))

    assert scena.czas_calosci_ms == 200 + 2 * utils.KROK_KASKADY_MS


# ============================================================================
#  ZNACZNIK „JUŻ GRAŁO"
# ============================================================================

def test_pierwsze_pokazanie_wpuszcza_tylko_raz():
    stan = pomoce.stan_aplikacji(1, "Auto")

    assert utils.pierwsze_pokazanie(stan, "pojazd", 1) is True
    assert utils.pierwsze_pokazanie(stan, "pojazd", 1) is False


def test_pierwsze_pokazanie_wraca_przy_zmianie_pojazdu():
    """Inny pojazd to inne terminy i inne budżety — czyli w praktyce inny ekran."""
    stan = pomoce.stan_aplikacji(1, "Auto")
    utils.pierwsze_pokazanie(stan, "pojazd", 1)

    assert utils.pierwsze_pokazanie(stan, "pojazd", 2) is True


def test_pierwsze_pokazanie_rozroznia_ekrany_i_dziala_bez_pojazdu():
    stan = pomoce.stan_aplikacji(1, "Auto")

    assert utils.pierwsze_pokazanie(stan, "budzet", 1) is True
    assert utils.pierwsze_pokazanie(stan, "rok", 1) is True
    # Ekran niezwiązany z pojazdem zapisuje się pod None — i też ma zagrać RAZ,
    # a nie ani razu.
    assert utils.pierwsze_pokazanie(stan, "porownanie") is True
    assert utils.pierwsze_pokazanie(stan, "porownanie") is False


# ============================================================================
#  PASEK TERMINU
# ============================================================================

def termin(dni, prog=30):
    return {
        "klucz": "oc", "etykieta": "Polisa OC", "data": "01.01.2027",
        "dni": dni, "prog": prog, "status": "ok",
    }


def test_pasek_terminu_bez_sceny_jest_od_razu_wypelniony():
    wiersz = utils.pasek_terminu(None, termin(10))

    assert paski(wiersz)[0].value == pytest.approx(1 - 10 / 30)


def test_pasek_terminu_ze_scena_wypelnia_sie_od_zera():
    scena = utils.ScenaWejscia(czas_ms=40, kaskada=True)
    wiersz = utils.pasek_terminu(None, termin(10), scena=scena)
    pasek = paski(wiersz)[0]

    assert pasek.value == 0.0

    odtworz(scena)

    assert pasek.value == pytest.approx(1 - 10 / 30)


def test_odlegly_termin_nie_drga():
    """„Zielony i pusty" znaczy „jeszcze długo" — brak ruchu jest tu informacją,
    a nie brakiem animacji."""
    scena = utils.ScenaWejscia(czas_ms=40, kaskada=True)
    pasek = paski(utils.pasek_terminu(None, termin(200), scena=scena))[0]

    odtworz(scena)

    assert pasek.value == 0.0


def test_termin_po_czasie_dojezdza_do_konca():
    scena = utils.ScenaWejscia(czas_ms=40, kaskada=True)
    pasek = paski(utils.pasek_terminu(None, termin(-3), scena=scena))[0]

    odtworz(scena)

    assert pasek.value == 1.0


def test_kazdy_termin_to_osobny_wiersz_kaskady():
    scena = utils.ScenaWejscia(czas_ms=40, kaskada=True)
    for dni in (5, 10, 20):
        utils.pasek_terminu(None, termin(dni), scena=scena)

    assert opoznienia(scena) == [0, utils.KROK_KASKADY_MS, 2 * utils.KROK_KASKADY_MS]


# ============================================================================
#  EKRANY
# ============================================================================

def test_karta_pojazdu_animuje_paski_terminow(baza):
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    ustaw_terminy(stan.auto_id, 5, 12, 40, 200)
    db.zapisz_animacje_interfejsu(True)

    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["PojazdView"], pomoce.zbuduj_strone(), stan)

    assert widok.scena.wlaczona
    assert len(widok.scena._tory) >= 4, "każdy termin ma własny pasek"
    assert opoznienia(widok.scena)[:3] == [0, utils.KROK_KASKADY_MS, 2 * utils.KROK_KASKADY_MS]


def test_karta_pojazdu_animuje_sie_raz_na_uruchomienie(baza):
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    ustaw_terminy(stan.auto_id, 5, 12)
    db.zapisz_animacje_interfejsu(True)
    K = pomoce.klasy_widokow()["PojazdView"]

    pomoce.zbuduj_widok(K, pomoce.zbuduj_strone(), stan)
    drugie = pomoce.zbuduj_widok(K, pomoce.zbuduj_strone(), stan)

    assert not drugie.scena.wlaczona


def test_budzet_animuje_pasek_i_kwote_w_tym_samym_rytmie(baza):
    """Kwota „wydano / limit" należy do tego samego wiersza co pasek pod nią —
    gdyby dostała własny krok kaskady, liczba ruszałaby po swoim pasku."""
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    db.zapisz_budzet(stan.auto_id, "razem", "miesiac", 1500)
    db.zapisz_budzet(stan.auto_id, "paliwo", "miesiac", 800)
    db.zapisz_animacje_interfejsu(True)

    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["BudzetView"], pomoce.zbuduj_strone(), stan)

    assert widok.scena.wlaczona
    assert len(widok.scena._tory) >= 4, "każdy budżet to pasek PLUS kwota"
    assert len(opoznienia(widok.scena)) == len(widok.scena._tory) // 2


def test_serwis_animuje_pasek_zuzycia_podzespolu(baza):
    """Pasek na karcie podzespołu mówi to samo co pasek terminu, tylko
    w kilometrach: ile z interwału już minęło."""
    stan, identyfikatory = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    with db.polacz_baze() as conn:
        conn.execute("UPDATE zadania SET przebieg=?, data=? WHERE id=?",
                     (100000, "01.01.2026", identyfikatory["zadanie"]))
    stan.zakladka = 1
    db.zapisz_animacje_interfejsu(True)

    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(), stan)

    assert widok._scena_zakladki.kaskada
    assert widok._scena_zakladki._tory, "podzespół z interwałem ma mieć pasek postępu"


def test_wylaczone_animacje_daja_te_same_paski_co_pelne_odtworzenie(baza, monkeypatch):
    """Sprawdzian końcowy: karta pojazdu z animacją, przejechana do końca, ma
    dokładnie te same wartości pasków, co ta sama karta bez animacji."""
    stan, _ = pomoce.przygotuj_scenariusz("pojazd_z_danymi")
    ustaw_terminy(stan.auto_id, 3, 12, 40, 200, 400)
    K = pomoce.klasy_widokow()["PojazdView"]

    db.zapisz_animacje_interfejsu(False)
    docelowe = [p.value for p in paski(pomoce.zbuduj_widok(K, pomoce.zbuduj_strone(), stan))]

    stan.animacje_pokazane = {}
    db.zapisz_animacje_interfejsu(True)
    zaplanowane = []
    monkeypatch.setattr(utils.animacje, "_petla_dziala", lambda strona: True)
    monkeypatch.setattr(ft.Page, "run_task", lambda self, handler, *a, **k: zaplanowane.append(handler))
    monkeypatch.setattr(ft.Page, "update", lambda self, *kontrolki: None)

    widok = pomoce.zbuduj_widok(K, pomoce.zbuduj_strone(), stan)
    na_starcie = [p.value for p in paski(widok)]

    assert docelowe, "karta pojazdu ma paski — bez nich test niczego nie sprawdza"
    assert any(w != 0 for w in docelowe), "przynajmniej jeden termin ma być w progu"
    assert all(w == 0 for w in na_starcie), "przed animacją wszystkie paski stoją na zerze"

    asyncio.run(zaplanowane[-1]())

    assert [p.value for p in paski(widok)] == docelowe
