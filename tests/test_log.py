"""Rotujący log błędów — moduł `log.py`.

Log jest narzędziem diagnostycznym, więc ma dwie właściwości, których nie widać
w normalnym użyciu i które łatwo stracić po cichu:

1. **Łapie to, co inaczej ginie** — wyjątek połknięty przez `except: pass`,
   wyjątek z wątku, wyjątek korutyny puszczonej przez `page.run_task`.
2. **Nigdy nie wywala aplikacji** — brak prawa zapisu na katalog danych ma
   znaczyć „aplikacja działa bez logu", a nie „aplikacja się nie uruchamia".

Obie sprawdzamy tutaj, bo pierwszy raz, kiedy log jest potrzebny, jest zawsze
tym samym razem, kiedy nie ma już czasu sprawdzać, czy działa.
"""

import asyncio
import gc
import logging
import sys
import threading

import pytest

import log


@pytest.fixture
def czysty_log(tmp_path, monkeypatch):
    """Log w katalogu testu, z nietkniętym stanem globalnym po wyjściu.

    `log` jest z natury modułem globalnym: jeden uchwyt do pliku, haki wpięte
    w `sys`. Bez odtworzenia obu pierwszy test zabierałby ze sobą wszystkie
    następne — i cały przebieg pytesta, który też korzysta z `logging`."""
    monkeypatch.setattr(log, "PLIK_LOGU", str(tmp_path / "flota.log"))
    monkeypatch.setattr(log, "_uchwyt", None)
    monkeypatch.setattr(log, "_haki_zalozone", False)

    # Kopie list uchwytów: `wlacz()` dopisuje do kopii, oryginały zostają czyste.
    korzen = logging.getLogger()
    monkeypatch.setattr(korzen, "handlers", list(korzen.handlers))
    monkeypatch.setattr(log._logger, "handlers", list(log._logger.handlers))
    monkeypatch.setattr(log._logger, "propagate", log._logger.propagate)

    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(sys, "unraisablehook", sys.unraisablehook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)

    yield tmp_path

    if log._uchwyt is not None:
        log._uchwyt.close()


@pytest.fixture
def dziennik(czysty_log):
    """Włączony log — punkt wyjścia dla większości testów."""
    assert log.wlacz(), "log nie ruszył w katalogu testu"
    return czysty_log


# ============================================================ ZAPIS I ROTACJA


def test_wpis_trafia_do_pliku(dziennik):
    log.zapisz("ekran: /ustawienia")

    assert "ekran: /ustawienia" in log.tresc()


def test_plik_nie_powstaje_zanim_jest_co_zapisac(dziennik):
    """`delay=True` w uchwycie: świeża instalacja nie zakłada pustego pliku."""
    assert log.sciezki_logu() == []


def test_powtorne_wlaczenie_nie_dubluje_wpisow(dziennik):
    """Ten sam uchwyt wisi na naszym loggerze i na głównym. Gdyby nasz logger
    dodatkowo propagował wyżej, każdy wpis lądowałby w pliku dwa razy."""
    log.wlacz()
    log.zapisz("jedyny wpis")

    assert log.tresc().count("jedyny wpis") == 1


def test_log_rotuje_i_nie_rosnie_bez_konca(czysty_log):
    log.ROZMIAR_PLIKU = 2 * 1024
    try:
        assert log.wlacz()
        for numer in range(400):
            log.zapisz(f"wpis numer {numer} — wypełniacz, żeby plik urósł ponad próg")
    finally:
        log.ROZMIAR_PLIKU = 256 * 1024

    pliki = log.sciezki_logu()
    assert len(pliki) == log.LICZBA_KOPII + 1, "rotacja nie trzyma zadanej liczby plików"
    assert log.rozmiar() < 12 * 1024, "log rośnie mimo rotacji"
    assert "wpis numer 399" in log.tresc(), "najnowszy wpis wypadł z logu"
    assert "wpis numer 0" not in log.tresc(), "najstarszy wpis powinien już wypaść"


def test_tresc_idzie_od_najstarszego(czysty_log):
    """Kolejność jest tu treścią: log czyta się po to, żeby zobaczyć, co było
    PRZED błędem."""
    log.ROZMIAR_PLIKU = 1024
    try:
        assert log.wlacz()
        for numer in range(200):
            log.zapisz(f"wpis {numer:03d} — wypełniacz wydłużający wiersz do rotacji")
    finally:
        log.ROZMIAR_PLIKU = 256 * 1024

    numery = [int(w.split("wpis ")[1][:3]) for w in log.tresc().splitlines() if "wpis " in w]
    assert numery == sorted(numery)


# ============================================================ ŁAPANIE BŁĘDÓW


def test_polkniety_zapisuje_rodzaj_i_slad(dziennik):
    """Zamiennik `pass` — zachowanie bez zmian, ale zostaje po czym poznać, co padło."""
    try:
        {}["brak"]
    except Exception:
        log.polkniety("odświeżenie panelu")

    tresc = log.tresc()
    assert "odświeżenie panelu: KeyError" in tresc
    assert "Traceback" in tresc, "bez śladu stosu nie wiadomo, gdzie to było"
    assert "WARNING" in tresc, "połknięty wyjątek to ślad, nie awaria"


def test_polkniety_poza_blokiem_except_nie_wywala_sie(dziennik):
    log.polkniety("coś, co nie miało wyjątku")

    assert "nie powiodło się" in log.tresc()


def test_blad_zapisuje_slad_biezacego_wyjatku(dziennik):
    try:
        raise ValueError("nieudany import kopii")
    except Exception:
        log.blad("import kopii zapasowej")

    tresc = log.tresc()
    assert "ERROR" in tresc
    assert "ValueError: nieudany import kopii" in tresc


def test_porzucona_korutyna_trafia_do_logu(dziennik):
    """Najcenniejszy przypadek: `page.run_task` z korutyną, która rzuca wyjątek.

    Dziś taki błąd kończy się linijką na konsoli, której na telefonie nie widzi
    nikt. asyncio zgłasza go przez `logging`, więc uchwyt na loggerze głównym
    łapie go bez jednej linijki zmian w kodzie aplikacji."""
    async def bum():
        raise ValueError("korutyna z run_task")

    async def scenariusz():
        asyncio.ensure_future(bum())
        await asyncio.sleep(0.05)

    asyncio.run(scenariusz())
    gc.collect()

    assert "korutyna z run_task" in log.tresc()


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_wyjatek_z_watku_trafia_do_logu(dziennik):
    """`asyncio.to_thread` jest w tym projekcie wszędzie — od synchronizacji po
    generowanie PDF-a. Wyjątek w wątku nie przechodzi przez `sys.excepthook`."""
    def bum():
        raise RuntimeError("wątek w tle")

    watek = threading.Thread(target=bum, name="test-tla")
    watek.start()
    watek.join()

    tresc = log.tresc()
    assert "RuntimeError" in tresc and "wątek w tle" in tresc
    assert "test-tla" in tresc, "bez nazwy wątku nie wiadomo, co go uruchomiło"


def test_hak_glowny_zapisuje_i_oddaje_sterowanie_poprzednikowi(czysty_log):
    """Hak ma dokładać wpis, a nie zmieniać zachowanie Pythona."""
    wywolania = []
    sys.excepthook = lambda *args: wywolania.append(args)

    assert log.wlacz()
    try:
        raise KeyError("nieobsłużony")
    except Exception:
        sys.excepthook(*sys.exc_info())

    assert len(wywolania) == 1, "poprzedni hak przestał być wołany"
    assert "Nieobsłużony wyjątek" in log.tresc()


def test_cudze_ostrzezenia_wchodza_a_cudze_info_nie(dziennik):
    """Filtr poziomów: gdyby ktoś podkręcił logowanie Fleta albo httpx na DEBUG,
    ruch sieciowy wypchnąłby z rotacji jedyny wpis, dla którego log powstał."""
    obcy = logging.getLogger("httpx")
    obcy.setLevel(logging.DEBUG)
    try:
        obcy.warning("timeout do Supabase")
        obcy.info("szczegół, którego nikt nie potrzebuje")
    finally:
        obcy.setLevel(logging.NOTSET)

    tresc = log.tresc()
    assert "timeout do Supabase" in tresc
    assert "szczegół" not in tresc


# ============================================================ ODCZYT I RAPORT


def test_podsumowanie_liczy_wpisy_i_wskazuje_ostatni_blad(dziennik):
    log.zapisz("ekran: /")
    try:
        raise ValueError("pierwszy")
    except Exception:
        log.blad("błąd pierwszy")
    try:
        raise ValueError("drugi")
    except Exception:
        log.blad("błąd drugi")
    try:
        raise ValueError("trzeci")
    except Exception:
        log.polkniety("coś połkniętego")

    dane = log.podsumowanie()

    assert dane["wpisy"] == 4, "wiersze śladu stosu nie są osobnymi wpisami"
    assert dane["bledy"] == 2
    assert dane["ostrzezenia"] == 1
    assert dane["ostatni_blad"][1] == "błąd drugi"


def test_podsumowanie_pustego_logu_nie_wywala_sie(dziennik):
    dane = log.podsumowanie()

    assert dane["wpisy"] == 0 and dane["bledy"] == 0
    assert dane["ostatni_blad"] is None


def test_raport_ma_naglowek_dolozony_przez_wolajacego(dziennik):
    """`log.py` nie zna ani Fleta, ani bazy — wersje dokłada widok Ustawień."""
    log.zapisz("ekran: /ustawienia")

    raport = log.zbierz_raport({"Flet": "0.86.5", "Wersja schematu": "40"})

    assert "Flet:" in raport and "0.86.5" in raport
    assert "Wersja schematu:" in raport and "40" in raport
    assert "ekran: /ustawienia" in raport, "sam nagłówek bez treści logu jest bezużyteczny"
    assert "VIN" in raport, "raport ma mówić wprost, czego w nim nie ma"


def test_raport_z_pustego_logu_mowi_ze_jest_pusty(dziennik):
    assert "(log jest pusty)" in log.zbierz_raport()


def test_nazwa_pliku_raportu_niesie_date():
    from datetime import datetime

    nazwa = log.nazwa_pliku_raportu(datetime(2026, 9, 8, 21, 5))

    assert nazwa == "log_flota_2026-09-08_2105.txt"


def test_czyszczenie_kasuje_pliki_i_pozwala_pisac_dalej(dziennik):
    log.zapisz("przed czyszczeniem")
    assert log.rozmiar() > 0

    usuniete = log.wyczysc()

    assert usuniete == 1
    assert log.rozmiar() == 0

    log.zapisz("po czyszczeniu")
    tresc = log.tresc()
    assert "po czyszczeniu" in tresc
    assert "przed czyszczeniem" not in tresc


def test_odmiana_przez_liczbe():
    assert log.odmien(1, "wpis", "wpisy", "wpisów") == "wpis"
    assert log.odmien(3, "wpis", "wpisy", "wpisów") == "wpisy"
    assert log.odmien(5, "wpis", "wpisy", "wpisów") == "wpisów"
    assert log.odmien(12, "wpis", "wpisy", "wpisów") == "wpisów", "nastolatki idą z 'wpisów'"
    assert log.odmien(22, "wpis", "wpisy", "wpisów") == "wpisy"
    assert log.odmien(0, "wpis", "wpisy", "wpisów") == "wpisów"


def test_formatowanie_rozmiaru():
    assert log.formatuj_rozmiar(512) == "512 B"
    assert log.formatuj_rozmiar(2048) == "2,0 kB"
    assert log.formatuj_rozmiar(3 * 1024 * 1024) == "3,0 MB"


# ============================================================ ODPORNOŚĆ


def test_brak_miejsca_na_log_nie_wywala_aplikacji(czysty_log, monkeypatch):
    """Katalog, którego nie da się założyć. `wlacz()` ma zwrócić False, a każda
    kolejna funkcja modułu ma milczeć — log nigdy nie jest ważniejszy od tego,
    co loguje."""
    monkeypatch.setattr(log, "PLIK_LOGU", str(czysty_log / "plik.txt" / "flota.log"))
    (czysty_log / "plik.txt").write_text("nie jestem katalogiem", encoding="utf-8")

    assert log.wlacz() is False
    assert log.czy_wlaczony() is False

    log.zapisz("nikt tego nie zapisze")
    log.polkniety("ani tego")
    assert log.tresc() == ""
    assert log.podsumowanie()["wpisy"] == 0
    assert log.wyczysc() == 0
