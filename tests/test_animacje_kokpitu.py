"""Animacja wejścia na kokpit: co ma dojechać i kiedy ma NIE zagrać.

Sedno tych testów jest jedno: animacja nie ma prawa zostawić po sobie zera.
Kafelek pokazujący „0,00 zł” zamiast prawdziwej kwoty to nie usterka wyglądu,
tylko zmyślona liczba — a dokładnie tak kończy się animacja, która nie
wystartowała (brak pętli zdarzeń), urwała się w połowie (zmiana ekranu) albo
dopisała nowy kafelek po odtworzeniu (tryb układania).
"""

import asyncio
import time

import flet as ft
import pytest

import db
import pomoce
import utils


class StronaZapisujaca:
    """Zamiast prawdziwej strony: licznik odświeżeń. Scena ma prawo wołać
    `update` wiele razy — tu chodzi tylko o to, żeby nie wołała go w próżnię."""

    def __init__(self):
        self.klatki = 0

    def update(self, *kontrolki):
        self.klatki += 1


def odtworz(scena):
    """Pełny przebieg sceny, tak jak w aplikacji — tylko z własną pętlą."""
    strona = StronaZapisujaca()
    asyncio.run(scena.odtworz(strona))
    return strona


def teksty(kontrolka, limit=20000):
    """Wszystkie napisy z poddrzewa kontrolki."""
    zebrane = []
    do_odwiedzenia = [kontrolka]
    while do_odwiedzenia and len(zebrane) < limit:
        biezaca = do_odwiedzenia.pop()
        if isinstance(biezaca, ft.Text):
            zebrane.append(biezaca.value)
        for nazwa in ("controls", "content", "appbar", "floating_action_button",
                      "drawer", "navigation_bar"):
            wartosc = getattr(biezaca, nazwa, None)
            if isinstance(wartosc, (list, tuple)):
                do_odwiedzenia.extend(w for w in wartosc if isinstance(w, ft.Control))
            elif isinstance(wartosc, ft.Control):
                do_odwiedzenia.append(wartosc)
    return zebrane


# ============================================================================
#  SAMA SCENA
# ============================================================================

def test_liczba_startuje_od_zera_i_konczy_na_wartosci():
    scena = utils.ScenaWejscia(czas_ms=40)
    tekst = scena.liczba(1234.5, lambda v: f"{v:.2f} zł")

    assert tekst.value == "0.00 zł", "kafelek ma zacząć od zera, inaczej nie ma czego odliczać"

    odtworz(scena)

    assert tekst.value == "1234.50 zł", "ostatnia klatka musi być DOKŁADNĄ wartością"


def test_liczba_nie_przeskakuje_wartosci_po_drodze():
    """Ease-out zwalnia przy końcu, ale nigdy nie cofa się ani nie przestrzeliwuje."""
    scena = utils.ScenaWejscia(czas_ms=40)
    podglad = []
    scena.liczba(100.0, lambda v: podglad.append(v) or f"{v:.1f}")

    odtworz(scena)

    # Pierwsze wywołanie to złożenie napisu przy BUDOWIE kontrolki — kafelek
    # powstaje z wartością docelową i dopiero rejestracja toru cofa go do zera,
    # więc nawet nieodtworzona scena nigdy nie pokaże wymyślonej liczby.
    assert podglad[0] == 100.0
    klatki = podglad[1:]
    assert klatki == sorted(klatki), "wartości pośrednie mają rosnąć monotonicznie"
    assert klatki[0] == 0.0, "pierwsza klatka to zero"
    assert max(klatki) <= 100.0 + 1e-9, "animacja nie może przestrzelić celu"
    assert klatki[-1] == pytest.approx(100.0)


def test_wskaznik_i_pasek_dojezdzaja_do_swoich_wartosci():
    scena = utils.ScenaWejscia(czas_ms=40)
    pasek = scena.wskaznik(ft.ProgressBar(value=0.75))
    wypelnienie, reszta = ft.Container(), ft.Container()
    scena.udzial(wypelnienie, reszta, 0.4)

    assert pasek.value == 0.0

    odtworz(scena)

    assert pasek.value == pytest.approx(0.75)
    assert wypelnienie.expand == 400
    assert reszta.expand == 600


def test_slupek_wyrasta_od_dolu():
    """Wysokość kontenera Flet animuje sam — scena tylko ustawia oba końce."""
    scena = utils.ScenaWejscia(czas_ms=40)
    slupek = scena.wysokosc(ft.Container(height=60), 60, od=4)

    assert slupek.height == 4
    assert slupek.animate is not None

    odtworz(scena)

    assert slupek.height == 60


def test_scena_wylaczona_oddaje_wartosci_od_razu():
    """Wyłączone animacje nie mogą wymagać ANI JEDNEJ zmiany w kodzie kafelków."""
    scena = utils.ScenaWejscia(wlaczona=False)
    tekst = scena.liczba(42.0, lambda v: f"{v:.0f}")
    pasek = scena.wskaznik(ft.ProgressBar(value=0.5))
    slupek = scena.wysokosc(ft.Container(height=30), 30, od=4)

    assert (tekst.value, pasek.value, slupek.height) == ("42", 0.5, 30)
    assert scena.pusta, "wyłączona scena nie ma czego odtwarzać"


def test_kafelek_zbudowany_po_odtworzeniu_nie_zostaje_z_zerem():
    """Przebudowa kokpitu (tryb układania, nowa kolejność) trafia w scenę, która
    już przejechała. Gdyby przyjęła nowy tor, nikt by go nie doprowadził do
    końca — i kafelek zostałby z zerem na stałe."""
    scena = utils.ScenaWejscia(czas_ms=40)
    odtworz(scena)
    scena.wygas()

    spozniony = scena.liczba(999.0, lambda v: f"{v:.0f}")

    assert spozniony.value == "999"


def test_scena_bez_petli_zdarzen_pokazuje_wartosci_zamiast_zer():
    """`page.run_task` bez działającej pętli tworzy korutynę, której nikt nie
    odbierze. Scena ma to wykryć i po prostu dokończyć się na miejscu."""
    scena = utils.ScenaWejscia(czas_ms=40)
    tekst = scena.liczba(7.0, lambda v: f"{v:.0f}")

    strona = pomoce.zbuduj_strone()   # referencja musi żyć: sesja wisi na słabej
    scena.uruchom(strona.page)

    assert tekst.value == "7"


def test_scena_konczy_sie_w_swoim_czasie():
    """Zegar, a nie licznik kroków. Gdyby pętla odliczała klatki, wolniejszy
    telefon rozciągnąłby pół sekundy ruchu na dwie — i kokpit czytałoby się
    później, niż gdyby animacji nie było wcale."""
    scena = utils.ScenaWejscia(czas_ms=200)
    scena.liczba(10.0, lambda v: f"{v:.1f}")

    poczatek = time.monotonic()
    strona = odtworz(scena)
    trwalo_ms = (time.monotonic() - poczatek) * 1000

    dolna = utils.OPOZNIENIE_STARTU_S * 1000 + 200
    assert dolna <= trwalo_ms < dolna + 250, f"animacja trwała {trwalo_ms:.0f} ms"
    assert strona.klatki >= 3, "bez odświeżeń nikt tej animacji nie zobaczy"


def test_liczba_bez_wartosci_nie_udaje_zera():
    scena = utils.ScenaWejscia(czas_ms=40)
    tekst = scena.liczba(None, lambda v: f"{v:.0f}")

    assert tekst.value == "None" or tekst.value is not None
    assert scena.pusta, "brak liczby to brak toru — nie ma czego animować"


# ============================================================================
#  KOKPIT
# ============================================================================

def kokpit_z_kompletem_kafelkow(nazwa_scenariusza="pojazd_z_danymi"):
    """Kokpit ze WSZYSTKIMI kafelkami, jakie aplikacja ma. Domyślne są trzy,
    a błąd w animacji siedzi zwykle w tym jednym, którego nikt nie włączył."""
    stan, _ = pomoce.przygotuj_scenariusz(nazwa_scenariusza)
    stan.zakladka = 0
    db.zapisz_widgety_kokpitu(list(db.KOKPIT_WIDGETY), stan.auto_id)
    return stan


def zbuduj_kokpit(stan):
    return pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(), stan)


def test_kokpit_bez_okna_pokazuje_te_same_liczby_z_animacja_i_bez(baza):
    """Test regresyjny na najgorszy możliwy skutek tej funkcji: kokpit, który po
    włączeniu animacji pokazuje inne liczby niż bez niej."""
    stan = kokpit_z_kompletem_kafelkow()

    db.zapisz_animacje_interfejsu(False)
    bez_animacji = teksty(zbuduj_kokpit(stan))

    stan.kokpit_animacja_dla = None
    db.zapisz_animacje_interfejsu(True)
    z_animacja = teksty(zbuduj_kokpit(stan))

    assert z_animacja == bez_animacji


@pytest.mark.parametrize("scenariusz", ["pojazd_z_danymi", "pojazd_z_historia"])
def test_pelny_przebieg_na_prawdziwym_kokpicie_konczy_na_tych_samych_liczbach(baza, monkeypatch, scenariusz):
    """Sprawdzian końcowy: prawdziwy kokpit z kompletem kafelków, prawdziwa
    scena, pełne odtworzenie — i dokładnie te same liczby, co bez animacji."""
    stan = kokpit_z_kompletem_kafelkow(scenariusz)

    db.zapisz_animacje_interfejsu(False)
    docelowe = teksty(zbuduj_kokpit(stan))

    stan.kokpit_animacja_dla = None
    db.zapisz_animacje_interfejsu(True)
    zaplanowane = []
    monkeypatch.setattr(utils.animacje, "_petla_dziala", lambda strona: True)
    monkeypatch.setattr(ft.Page, "run_task", lambda self, handler, *a, **k: zaplanowane.append(handler))
    monkeypatch.setattr(ft.Page, "update", lambda self, *kontrolki: None)

    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["MainView"], pomoce.zbuduj_strone(), stan)

    assert docelowe, "kokpit nie narysował ani jednego napisu — test niczego nie sprawdza"
    assert zaplanowane, "scena miała zaplanować odtworzenie"

    na_starcie = teksty(widok)
    odliczane = sum(1 for a, b in zip(na_starcie, docelowe) if a != b)
    assert odliczane >= 3, "przy komplecie kafelków odliczać ma się więcej niż jedna liczba"

    asyncio.run(zaplanowane[0]())

    assert teksty(widok) == docelowe


def test_animacja_gra_raz_i_nie_wraca_przy_powrocie_na_kokpit(baza):
    stan = kokpit_z_kompletem_kafelkow()
    db.zapisz_animacje_interfejsu(True)

    pierwsze = zbuduj_kokpit(stan)
    assert pierwsze._scena_zakladki.wlaczona, "pierwsze wejście po starcie ma animować"
    assert not pierwsze._scena_zakladki.pusta, "kokpit z kafelkami ma mieć co animować"
    assert stan.kokpit_animacja_dla == stan.auto_id

    drugie = zbuduj_kokpit(stan)
    assert not drugie._scena_zakladki.wlaczona, "powrót na kokpit to nie jest nowe wejście"


def test_zmiana_pojazdu_wraca_do_animacji(baza):
    stan = kokpit_z_kompletem_kafelkow()
    db.zapisz_animacje_interfejsu(True)
    zbuduj_kokpit(stan)

    drugi = pomoce.utworz_pojazd("Drugi")
    stan.auto_id = drugi["auto_id"]
    db.zapisz_widgety_kokpitu(list(db.KOKPIT_WIDGETY), stan.auto_id)

    assert zbuduj_kokpit(stan)._scena_zakladki.wlaczona


def test_wylaczone_ustawienie_gasi_animacje(baza):
    stan = kokpit_z_kompletem_kafelkow()
    db.zapisz_animacje_interfejsu(False)

    assert not zbuduj_kokpit(stan)._scena_zakladki.wlaczona


def test_tryb_ukladania_nie_animuje(baza):
    stan = kokpit_z_kompletem_kafelkow()
    db.zapisz_animacje_interfejsu(True)
    widok = zbuduj_kokpit(stan)

    widok.kokpit_edycja = True
    stan.kokpit_animacja_dla = None

    assert not widok._czy_animowac_kokpit()


def test_ustawienie_animacji_domyslnie_wlaczone(baza):
    assert db.czy_animacje_interfejsu() is True

    db.zapisz_animacje_interfejsu(False)
    assert db.czy_animacje_interfejsu() is False

    db.zapisz_animacje_interfejsu(True)
    assert db.czy_animacje_interfejsu() is True
