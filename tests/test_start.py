"""Co się dzieje przy starcie aplikacji — i co się już wtedy NIE dzieje.

`init_db()` robiło przy każdym uruchomieniu cztery rzeczy: przechodziło drabinkę
migracji, kasowało odroczone załączniki, sprzątało wygasły kosz i (raz)
naprawiało ścieżki. Trzy ostatnie nie są potrzebne do narysowania pierwszego
ekranu, a każda rośnie razem z danymi — kosz kasuje pliki, naprawa chodzi po
wszystkich załącznikach w bazie. Zostały wyniesione do `porzadki_startowe()`,
które `main.py` woła w wątku w tle PO pierwszym renderze.

Ten plik pilnuje podziału z obu stron: że `init_db()` już tego nie robi
(inaczej przeniesienie byłoby pozorne) i że `porzadki_startowe()` robi to
naprawdę (inaczej sprzątanie przestałoby się dziać w ogóle).
"""

import os
import pathlib
import sys
from datetime import datetime, timedelta

sys.path[:0] = [str(pathlib.Path(__file__).resolve().parent), str(pathlib.Path(__file__).resolve().parents[1])]

import db  # noqa: E402
import pomoce  # noqa: E402


def _wygasla_pozycja_kosza(dni=8):
    """Pojazd w koszu z datą usunięcia cofniętą poza retencję."""
    pomoce.utworz_pojazd("Do skasowania")
    db.zapisz_dni_kosza(7)
    kosz_id = db.usun_auto_do_kosza(1)["kosz_id"]
    data = (datetime.now() - timedelta(days=dni)).strftime("%Y-%m-%d %H:%M:%S")
    with db.polacz_baze() as conn:
        conn.execute("UPDATE kosz_pojazdy SET data_usuniecia=? WHERE id=?", (data, kosz_id))
    return kosz_id


def _zalegly_odroczony_plik(godzin=3):
    """Plik w folderze odroczonym, starszy niż godzina — ślad po nagłym zamknięciu."""
    os.makedirs(db.FOLDER_ODROCZONE, exist_ok=True)
    sciezka = os.path.join(db.FOLDER_ODROCZONE, "zalegly.jpg")
    with open(sciezka, "wb") as plik:
        plik.write(b"ZALEGLY")
    dawno = datetime.now().timestamp() - godzin * 3600
    os.utime(sciezka, (dawno, dawno))
    return sciezka


# ------------------------------------------------- init_db robi tylko schemat


def test_init_db_nie_sprzata_kosza(baza):
    """Gdyby sprzątał, przeniesienie do tła byłoby tylko na papierze."""
    _wygasla_pozycja_kosza()

    db.init_db()

    assert db.liczba_w_koszu() == 1


def test_init_db_nie_kasuje_odroczonych_zalacznikow(baza):
    sciezka = _zalegly_odroczony_plik()

    db.init_db()

    assert os.path.exists(sciezka)


def test_init_db_nie_odhacza_naprawy_sciezek(baza):
    """Znacznik naprawy ma zostać nietknięty — inaczej porządki w tle uznałyby,
    że naprawa już poszła, i nie zrobiłyby jej nigdy."""
    db.usun_ustawienie("naprawa_sciezek_zalacznikow_v1")

    db.init_db()

    assert db.pobierz_ustawienie("naprawa_sciezek_zalacznikow_v1") is None


# --------------------------------------------- porządki robią to, co przejęły


def test_porzadki_sprzataja_wygasly_kosz(baza):
    _wygasla_pozycja_kosza()

    db.porzadki_startowe()

    assert db.liczba_w_koszu() == 0


def test_porzadki_kasuja_zalegle_odroczone_zalaczniki(baza):
    zalegly = _zalegly_odroczony_plik()
    swiezy = os.path.join(db.FOLDER_ODROCZONE, "swiezy.jpg")
    with open(swiezy, "wb") as plik:
        plik.write(b"SWIEZY")

    db.porzadki_startowe()

    assert not os.path.exists(zalegly)
    assert os.path.exists(swiezy), "plik sprzed godziny może jeszcze czekać na cofnięcie"


def test_naprawa_sciezek_idzie_dokladnie_raz(baza, monkeypatch):
    """Naprawa chodzi po WSZYSTKICH załącznikach w bazie, więc ma pójść raz
    w życiu instalacji — znacznik jest tu całą treścią."""
    wywolania = []

    def _naprawa():
        wywolania.append(1)
        return 3, 1

    monkeypatch.setattr(db.migracje, "napraw_sciezki_zalacznikow", _naprawa)
    db.usun_ustawienie("naprawa_sciezek_zalacznikow_v1")

    assert db.porzadki_startowe() == (3, 1)
    assert db.porzadki_startowe() == (0, 0)
    assert db.porzadki_startowe() == (0, 0)

    assert len(wywolania) == 1
    assert db.pobierz_ustawienie("naprawa_sciezek_zalacznikow_v1") == "1"


def test_nieudana_naprawa_nie_wywala_startu(baza, monkeypatch):
    """Brak zdjęć nie może uniemożliwić uruchomienia aplikacji — a znacznik
    i tak ma polecieć, żeby nieudana naprawa nie wracała przy każdym starcie."""
    def _wybuch():
        raise OSError("dysk tylko do odczytu")

    monkeypatch.setattr(db.migracje, "napraw_sciezki_zalacznikow", _wybuch)
    db.usun_ustawienie("naprawa_sciezek_zalacznikow_v1")

    assert db.porzadki_startowe() == (0, 0)
    assert db.pobierz_ustawienie("naprawa_sciezek_zalacznikow_v1") == "1"


def test_porzadki_naprawiaja_sciezke_z_innego_urzadzenia(baza):
    """Prawdziwa naprawa, bez podmieniania: ścieżka jak z Androida, plik leżący
    tutaj. To jest scenariusz kopii przeniesionej między urządzeniami."""
    identyfikatory = pomoce.utworz_pojazd("Przeniesiony")
    with db.polacz_baze() as conn:
        conn.execute(
            "UPDATE tankowania SET zalacznik=? WHERE id=?",
            ("/data/user/0/pl.flota/files/data/zalaczniki/przeniesione.jpg",
             identyfikatory["tankowanie"]),
        )
    with open(os.path.join(db.FOLDER_ZALACZNIKI, "przeniesione.jpg"), "wb") as plik:
        plik.write(b"ZDJECIE")
    db.usun_ustawienie("naprawa_sciezek_zalacznikow_v1")

    naprawione, brakujace = db.porzadki_startowe()

    assert naprawione >= 1 and brakujace == 0
    with db.polacz_baze() as conn:
        sciezka = conn.execute(
            "SELECT zalacznik FROM tankowania WHERE id=?", (identyfikatory["tankowanie"],)
        ).fetchone()[0]
    assert os.path.exists(sciezka), "po naprawie ścieżka ma wskazywać istniejący plik"
