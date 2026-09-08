"""Jeden przebieg synchronizacji — kolejność, zamek i wynik.

Moduł jest wysoko w pakiecie, bo woła wszystko poniżej: sesję, role, nagrobki,
wysyłanie i pobieranie. Kolejność w `_synchronizuj_pod_zamkiem` jest treścią,
a nie szczegółem: najpierw wypchnięcie własnych zmian, potem pobranie cudzych.

Tu mieszka też `_ZAMEK_SYNC` — jedyne miejsce, w którym pakiet pilnuje, żeby
dwa przebiegi nie szły równolegle.
"""

import db
import sqlite3
import threading
from datetime import datetime

from .stale import KONFIGURACJA_SYNC, SynchronizacjaWToku
from .polaczenie import _upewnij_sesje
from .role import czy_udostepniony
from .nagrobki import _wypchnij_nagrobki
from .konflikty import _konflikty_biezacej_synchronizacji, _odrzucone_biezacej_synchronizacji
from .pomocnicze import _zapytanie_tabeli
from .wysylanie import _wypchnij_tabele
from .pobieranie import _pobierz_tabele, _synchronizuj_info_pojazdu, _zastosuj_rekord


# Zamek na całą synchronizację jednego urządzenia. Auto-synchronizacja po
# zapisie formularza leci przez page.run_task, więc dwa szybkie zapisy pod rząd
# uruchamiały dwa przebiegi naraz: obydwa czytały ten sam `zdalny_hash`, obydwa
# wypychały i jeden nadpisywał drugiemu wynik.
_ZAMEK_SYNC = threading.Lock()


def synchronizuj_wszystko(auto_id, pelne=False, czekaj=True):
    """Jedna synchronizacja pojazdu. `pelne=True` ignoruje znacznik delty
    i ściąga komplet („Pobierz wszystko od nowa”).

    Cały przebieg jest pod zamkiem: auto-synchronizacja po zapisie formularza
    leci przez page.run_task, więc dwa szybkie zapisy pod rząd uruchamiały dwa
    przebiegi naraz — obydwa czytały ten sam `zdalny_hash`, obydwa wypychały
    i jeden nadpisywał drugiemu wynik. Wywołanie z `czekaj=False` (tło) po
    prostu odpuszcza, gdy inna synchronizacja właśnie trwa; ręczne czeka."""
    wspolny_id, _ = czy_udostepniony(auto_id)
    if not wspolny_id:
        return 0, 0

    nabyty = _ZAMEK_SYNC.acquire(timeout=180) if czekaj else _ZAMEK_SYNC.acquire(blocking=False)
    if not nabyty:
        raise SynchronizacjaWToku("Inna synchronizacja właśnie trwa.")
    try:
        return _synchronizuj_pod_zamkiem(auto_id, wspolny_id, pelne)
    finally:
        _ZAMEK_SYNC.release()


def pelna_synchronizacja(auto_id):
    """Pomija deltę i przechodzi całą chmurę od zera — ratunek, gdy lokalna baza
    rozjechała się z serwerem (np. po przywróceniu kopii zapasowej)."""
    db.wyczysc_znacznik_delty(auto_id)
    return synchronizuj_wszystko(auto_id, pelne=True)


def _synchronizuj_pod_zamkiem(auto_id, wspolny_id, pelne=False):
    # --- ZABEZPIECZENIE: Reset starszych tankowań wgranych starą metodą ---
    # Wymuszamy, by stare tankowania (mające ID ze starej tabeli Supabase) 
    # zostały uznane za nowe i wypchnięte do nowej tabeli zdalne_rekordy.
    if db.pobierz_ustawienie("migracja_tankowan_v4") != "1":
        with db.polacz_baze() as conn:
            conn.execute("UPDATE tankowania SET zdalne_id = NULL, zdalny_hash = NULL")
        db.zapisz_ustawienie("migracja_tankowan_v4", "1")
    # ----------------------------------------------------------------------

    klient, uid = _upewnij_sesje()
    rola = db.rola_pojazdu(auto_id)
    _konflikty_biezacej_synchronizacji.clear()
    _odrzucone_biezacej_synchronizacji.clear()

    # Znacznik delty: pobieramy tylko to, co zmieniło się od ostatniego razu.
    # Pusty znacznik (pierwsza synchronizacja, świeżo dołączony pojazd, żądanie
    # pełnego pobrania) oznacza przejście całej chmury, tak jak dotąd.
    znacznik = None if pelne else db.znacznik_delty(auto_id)

    wyslano = 0
    pobrano = 0
    do_cofniecia = {}

    if rola != db.ROLA_PODGLAD:
        _wypchnij_nagrobki(klient, auto_id)

    w_info, p_info = _synchronizuj_info_pojazdu(klient, wspolny_id, auto_id, rola)
    wyslano += w_info
    pobrano += p_info

    for konfig in KONFIGURACJA_SYNC:
        ile, cofnij = _wypchnij_tabele(klient, wspolny_id, auto_id, konfig, rola)
        wyslano += ile
        if cofnij:
            do_cofniecia[konfig["tabela"]] = cofnij

    najwyzszy_znacznik = None
    for konfig in KONFIGURACJA_SYNC:
        ile, znacznik_tabeli = _pobierz_tabele(klient, wspolny_id, auto_id, konfig, znacznik)
        pobrano += ile
        if znacznik_tabeli and (najwyzszy_znacznik is None or str(znacznik_tabeli) > str(najwyzszy_znacznik)):
            najwyzszy_znacznik = znacznik_tabeli

    # Zmiany odrzucone przez rolę współautora cofamy do wersji z chmury. Robimy
    # to osobnym, celowanym zapytaniem, bo przy synchronizacji przyrostowej te
    # rekordy nie zmieniły się zdalnie i w deltę by nie weszły.
    for konfig in KONFIGURACJA_SYNC:
        identyfikatory = do_cofniecia.get(konfig["tabela"])
        if identyfikatory:
            ile, _ = _pobierz_tabele(klient, wspolny_id, auto_id, konfig, tylko_id=identyfikatory)
            pobrano += ile

    if najwyzszy_znacznik:
        db.zapisz_znacznik_delty(auto_id, najwyzszy_znacznik)

    db.przelicz_wszystkie_zadania(auto_id)
    db.zapisz_ustawienie("ostatnia_synchronizacja", datetime.now().strftime("%d.%m.%Y %H:%M"))
    # Udana synchronizacja zamyka sprawę także dla kolejki. Wcześniej wpis
    # kasował się wyłącznie w synchronizuj_w_tle i przetworz_kolejke_sync, więc
    # po ręcznym „Synchronizuj teraz” pomarańczowa kropka „czeka na wysłanie”
    # potrafiła wisieć aż do końca backoffu — nawet godzinę po tym, jak
    # wszystko już poszło.
    db.usun_z_kolejki_sync(auto_id)

    return wyslano, pobrano


def przyjmij_wersje_z_chmury(auto_id, konflikty):
    """Cofa nadpisanie wykryte przy konflikcie: wpisuje lokalnie wersje
    zapamiętane w chwili wykrycia i odsyła je do chmury, żeby obie strony
    znów mówiły to samo. Zwraca liczbę przywróconych rekordów."""
    wspolny_id, _ = czy_udostepniony(auto_id)
    if not wspolny_id:
        return 0

    po_tabelach = {}
    for k in konflikty or []:
        if k.get("dane_zdalne") is None or not k.get("zdalne_id"):
            continue
        po_tabelach.setdefault(k.get("tabela"), []).append(k)
    if not po_tabelach:
        return 0

    klient, uid = _upewnij_sesje()
    przyjeto = 0

    for konfig in KONFIGURACJA_SYNC:
        pozycje = po_tabelach.get(konfig["tabela"])
        if not pozycje:
            continue

        zapytanie_znane = _zapytanie_tabeli(konfig["tabela"], "id, zdalne_id, zdalny_hash", "zdalne_id IS NOT NULL")
        with db.polacz_baze() as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute(zapytanie_znane, (auto_id,))
            znane = {r["zdalne_id"]: {"id": r["id"], "hash": r["zdalny_hash"]} for r in c.fetchall()}

        for k in pozycje:
            rekord = {"id": k["zdalne_id"], "dane": k["dane_zdalne"], "usuniete": False}
            przyjeto += _zastosuj_rekord(konfig, rekord, auto_id, znane)
            klient.rpc("aktualizuj_zdalny_rekord", {"p_id": k["zdalne_id"], "p_dane": k["dane_zdalne"]}).execute()

    db.przelicz_wszystkie_zadania(auto_id)
    return przyjeto


def synchronizuj_w_tle(auto_id, powod="zapis"):
    """Cicha synchronizacja po zapisie formularza. NIE rzuca wyjątków, ale — w
    przeciwieństwie do dawnego `except: pass` — nieudana próba trafia do kolejki
    (kolejka_sync) i zostanie automatycznie ponowiona. Zwraca (czy_udane, blad)."""
    wspolny_id, _ = czy_udostepniony(auto_id)
    if not wspolny_id:
        return True, None
    try:
        # czekaj=False: gdy inna synchronizacja właśnie trwa, ta odpuszcza
        # zamiast wyścigać się z nią o `zdalny_hash`. Zapis nie ginie — pojazd
        # ląduje w kolejce i zostanie dociągnięty przy ponowieniu.
        synchronizuj_wszystko(auto_id, czekaj=False)
        db.usun_z_kolejki_sync(auto_id)
        return True, None
    except SynchronizacjaWToku:
        db.zakolejkuj_synchronizacje(auto_id, powod, "Inna synchronizacja w toku")
        return False, None
    except Exception as ex:
        db.zakolejkuj_synchronizacje(auto_id, powod, str(ex))
        return False, str(ex)


def przetworz_kolejke_sync(limit=5):
    """Ponawia zaległe synchronizacje, których termin ponowienia już minął.
    Wołane przy starcie aplikacji i przy każdym kolejnym zapisie — nie rzuca
    wyjątków, kolejny nieudany strzał tylko odsuwa termin (backoff w db).
    Zwraca liczbę pojazdów zsynchronizowanych z zaległości."""
    udane = 0
    for auto_id, _powod, _proby in db.pobierz_kolejke_sync(limit=limit):
        wspolny_id, _ = czy_udostepniony(auto_id)
        if not wspolny_id:
            db.usun_z_kolejki_sync(auto_id)  # pojazd odłączony od chmury — kolejka bezprzedmiotowa
            continue
        try:
            # Tu czekamy na zamek: to już jest ponowienie, więc odpuszczenie
            # oznaczałoby kolejne odsunięcie terminu zamiast wykonania roboty.
            synchronizuj_wszystko(auto_id)
            db.usun_z_kolejki_sync(auto_id)
            udane += 1
        except SynchronizacjaWToku:
            continue  # zostaje w kolejce na następne podejście, bez backoffu
        except Exception as ex:
            db.zakolejkuj_synchronizacje(auto_id, "ponowienie", str(ex))
    return udane


__all__ = [
    "_ZAMEK_SYNC",
    "_synchronizuj_pod_zamkiem",
    "pelna_synchronizacja",
    "przetworz_kolejke_sync",
    "przyjmij_wersje_z_chmury",
    "synchronizuj_w_tle",
    "synchronizuj_wszystko",
]
