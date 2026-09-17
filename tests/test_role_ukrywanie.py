"""Rola przy pojeździe a interfejs: co znika z menu i z paska zaznaczania,
oraz przypisanie nagrobków do pojazdu przy usuwaniu grupowym.

Dwie rzeczy, których nie widać z osobna, a razem tworzą jedną regułę: akcja,
która i tak zostanie odrzucona, nie ma się pokazywać (`utils.odsiej_akcje`),
a usunięcie ma zostawić ślad dający się odfiltrować przy synchronizacji
przyrostowej (`db.usun_wiele_z_cofnieciem`).
"""

import db
import flet as ft
import pytest
import utils

from pomoce import stan_aplikacji, utworz_pojazd


# ============================ ODSIEWANIE AKCJI ============================

def _menu():
    """Menu jak przy wpisie w historii: jedna pozycja czytająca, reszta zmienia."""
    return [
        {"ikona": ft.Icons.IMAGE, "tekst": "Pokaż zdjęcie", "czyta": True, "akcja": lambda: None},
        {"ikona": ft.Icons.EDIT, "tekst": "Edytuj wpis", "akcja": lambda: None},
        {"ikona": ft.Icons.DELETE, "tekst": "Usuń wpis", "akcja": lambda: None},
    ]


def _teksty(pozycje):
    return [p["tekst"] for p in pozycje]


def test_wlasciciel_widzi_cale_menu(baza):
    ident = utworz_pojazd("Moje")
    assert _teksty(utils.odsiej_akcje(ident["auto_id"], _menu(), "historia", ident["historia"])) == [
        "Pokaż zdjęcie", "Edytuj wpis", "Usuń wpis"
    ]


def test_podglad_nie_widzi_zadnej_akcji_zmieniajacej(baza):
    ident = utworz_pojazd("Cudze", wspolny=True)
    db.ustaw_role_pojazdu(ident["auto_id"], db.ROLA_PODGLAD)

    zostalo = utils.odsiej_akcje(ident["auto_id"], _menu(), "historia", ident["historia"])

    assert _teksty(zostalo) == ["Pokaż zdjęcie"]


def test_menu_bez_pozycji_czytajacych_tlumaczy_sie_zamiast_byc_puste(baza):
    """Arkusz z samym tytułem wygląda jak awaria. Zostaje jedna linijka
    z powodem — i nie jest przyciskiem: nie ma podpiętej akcji."""
    ident = utworz_pojazd("Cudze", wspolny=True)
    db.ustaw_role_pojazdu(ident["auto_id"], db.ROLA_PODGLAD)

    same_zmiany = [p for p in _menu() if not p.get("czyta")]
    zostalo = utils.odsiej_akcje(ident["auto_id"], same_zmiany, "historia", ident["historia"])

    assert len(zostalo) == 1
    assert zostalo[0]["akcja"] is None
    assert zostalo[0]["tekst"] == db.OPISY_ROL[db.ROLA_PODGLAD]


def test_wspolautor_widzi_menu_przy_wlasnym_wpisie_i_nie_przy_cudzym(baza):
    """Ograniczenie współautora jest per wpis, nie per ekran — dokładnie tak,
    jak rozstrzyga to db.czy_moge_zmieniac_rekord przy próbie zapisu."""
    ident = utworz_pojazd("Wspólne", wspolny=True)
    db.ustaw_role_pojazdu(ident["auto_id"], db.ROLA_WSPOLAUTOR)
    db.zapisz_moje_imie("Ania")

    with db.polacz_baze() as conn:
        conn.execute("UPDATE tankowania SET dodane_przez='Ania' WHERE id=?", (ident["tankowanie"],))
        kursor = conn.execute(
            "INSERT INTO tankowania (auto_id, data, przebieg, litry, kwota, stacja, rodzaj_energii, "
            "dodane_przez, zdalne_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (ident["auto_id"], "2026-03-01", 101000, 30.0, 200.0, "BP", db.ENERGIA_PALIWO, "Marek", "tank-cudze"),
        )
        cudze = kursor.lastrowid

    moje = utils.odsiej_akcje(ident["auto_id"], _menu(), "tankowania", ident["tankowanie"])
    nie_moje = utils.odsiej_akcje(ident["auto_id"], _menu(), "tankowania", cudze)

    assert len(moje) == 3
    assert _teksty(nie_moje) == ["Pokaż zdjęcie"]


def test_wspolautor_rusza_wspolny_inwentarz_pojazdu(baza):
    """Magazyn, opony i podzespoły nie mają autora — to wyposażenie auta,
    a nie czyjeś wpisy. Blokowanie ich odcięłoby współautora od rzeczy,
    które sam zakłada."""
    ident = utworz_pojazd("Wspólne", wspolny=True)
    db.ustaw_role_pojazdu(ident["auto_id"], db.ROLA_WSPOLAUTOR)
    db.zapisz_moje_imie("Ania")

    zostalo = utils.odsiej_akcje(ident["auto_id"], _menu(), "magazyn_czesci", ident["magazyn"])

    assert len(zostalo) == 3


def test_pozycja_bez_flagi_znika_przy_podgladzie(baza):
    """Domyślnie zamknięte: akcja dopisana kiedyś do menu bez `czyta` nie
    pokaże się podglądowi, zamiast odbić się komunikatem."""
    ident = utworz_pojazd("Cudze", wspolny=True)
    db.ustaw_role_pojazdu(ident["auto_id"], db.ROLA_PODGLAD)

    nowa = [{"ikona": ft.Icons.STAR, "tekst": "Nowiutka akcja", "akcja": lambda: None},
            {"ikona": ft.Icons.INFO, "tekst": "Podejrzyj", "czyta": True, "akcja": lambda: None}]

    assert _teksty(utils.odsiej_akcje(ident["auto_id"], nowa, "historia", ident["historia"])) == ["Podejrzyj"]


def test_menu_kontekstowe_pomija_puste_pozycje(monkeypatch):
    """odsiej_akcje bywa wołane tam, gdzie lista i tak była budowana warunkowo —
    None w środku nie może wywrócić budowy arkusza."""
    zlapane = {}
    monkeypatch.setattr(utils.dialogi, "otworz_dno", lambda page, bs: zlapane.setdefault("bs", bs))

    utils.pokaz_menu_kontekstowe(
        None, "Opcje", [{"ikona": ft.Icons.EDIT, "tekst": "Edytuj", "akcja": None}, None])

    teksty = [k.title.value for k in zlapane["bs"].content.content.controls if isinstance(k, ft.ListTile)]
    assert teksty == ["Edytuj"]


# ======================= PASEK ZAZNACZANIA GRUPOWEGO =======================

class _WidokZZaznaczaniem(utils.ZaznaczanieGrupowe):
    """Najmniejszy obiekt, jakiego mixin potrzebuje do zbudowania paska."""

    def __init__(self, auto_id):
        self.state = stan_aplikacji(auto_id, "Auto")
        self.zaznaczone_id = {1, 2}
        self.oryginalny_appbar = None
        self.karty_ref = {}
        self.appbar = None

    def update(self):
        pass

    def potwierdz_grupowe_usuwanie(self, e):
        pass


def _ikony_paska(auto_id):
    widok = _WidokZZaznaczaniem(auto_id)
    widok.aktualizuj_appbar_zaznaczania()
    return [a.icon for a in widok.appbar.actions if isinstance(a, ft.IconButton)]


def test_kosz_w_pasku_zaznaczania_jest_przy_pelnych_prawach(baza):
    ident = utworz_pojazd("Moje")
    assert ft.Icons.DELETE in _ikony_paska(ident["auto_id"])


def test_kosz_w_pasku_zaznaczania_znika_przy_podgladzie(baza):
    ident = utworz_pojazd("Cudze", wspolny=True)
    db.ustaw_role_pojazdu(ident["auto_id"], db.ROLA_PODGLAD)
    assert ft.Icons.DELETE not in _ikony_paska(ident["auto_id"])


def test_kosz_zostaje_wspolautorowi(baza):
    """Zaznaczenie zbiorcze wolno mu mieć mieszane — usun_wiele_z_cofnieciem
    skasuje swoje i zamelduje, ile cudzych pominięto."""
    ident = utworz_pojazd("Wspólne", wspolny=True)
    db.ustaw_role_pojazdu(ident["auto_id"], db.ROLA_WSPOLAUTOR)
    assert ft.Icons.DELETE in _ikony_paska(ident["auto_id"])


# ============================== NAGROBKI ==============================

def _auto_nagrobka(zdalny_id):
    with db.polacz_baze() as conn:
        w = conn.execute("SELECT auto_id FROM zdalne_nagrobki WHERE zdalny_id=?", (zdalny_id,)).fetchone()
    return w[0] if w else "BRAK NAGROBKA"


def _drugi_pojazd():
    with db.polacz_baze() as conn:
        kursor = conn.execute(
            "INSERT INTO samochody (nazwa, typ_paliwa, status, rola_wspoldzielenia, wspolny_pojazd_id) "
            "VALUES (?,?,?,?,?)",
            ("Drugie", "Benzyna", db.STATUS_POJAZDU_AKTYWNY, db.ROLA_WLASCICIEL, "wspolny-2"),
        )
        return kursor.lastrowid


@pytest.fixture
def pojazd_z_tankowaniami(baza):
    ident = utworz_pojazd("Pierwsze", wspolny=True)
    with db.polacz_baze() as conn:
        for nr in (1, 2):
            conn.execute(
                "INSERT INTO tankowania (auto_id, data, przebieg, litry, kwota, stacja, rodzaj_energii, zdalne_id) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (ident["auto_id"], f"2026-03-0{nr}", 101000 + nr, 30.0, 200.0, "BP",
                 db.ENERGIA_PALIWO, f"tank-grupa-{nr}"),
            )
    with db.polacz_baze() as conn:
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM tankowania WHERE zdalne_id LIKE 'tank-grupa-%'").fetchall()]
    return ident, ids


def test_grupowe_usuwanie_przypisuje_nagrobki_do_pojazdu(pojazd_z_tankowaniami):
    ident, ids = pojazd_z_tankowaniami

    assert db.usun_wiele_z_cofnieciem("tankowania", ids)

    assert _auto_nagrobka("tank-grupa-1") == ident["auto_id"]
    assert _auto_nagrobka("tank-grupa-2") == ident["auto_id"]


def test_nagrobek_z_jednego_auta_nie_leci_przy_synchronizacji_drugiego(pojazd_z_tankowaniami):
    """Po to jest w nagrobku auto_id: bez niego usunięcie z auta A wisi w każdym
    cyklu synchronizacji auta B, aż licznik prób (5) je ucisza."""
    _, ids = pojazd_z_tankowaniami
    drugie = _drugi_pojazd()

    db.usun_wiele_z_cofnieciem("tankowania", ids)

    zdalne_drugiego = {z for _, _, z in db.pobierz_nagrobki(drugie)}
    assert not zdalne_drugiego & {"tank-grupa-1", "tank-grupa-2"}


def test_nagrobek_bez_pojazdu_nadal_leci_przy_kazdym_aucie(pojazd_z_tankowaniami):
    """Celowa usterka: tak wyglądał każdy nagrobek ze ścieżki zbiorczej przed
    tą poprawką. Wpisy sprzed migracji 40 zachowują się tak dalej — świadomie,
    bo nie ma z czego odtworzyć ich pojazdu."""
    _, _ = pojazd_z_tankowaniami
    drugie = _drugi_pojazd()

    db.zarejestruj_nagrobek("tankowania", "tank-sprzed-migracji", None)

    assert "tank-sprzed-migracji" in {z for _, _, z in db.pobierz_nagrobki(drugie)}


def test_historia_dostaje_pojazd_przez_zadanie_w_obu_sciezkach(baza):
    """Historia nie ma własnej kolumny auto_id — pojazd dojeżdża JOIN-em przez
    podzespół. Bez tego nagrobek wpisu serwisowego zostawał z NULL-em."""
    ident = utworz_pojazd("Serwisowane", wspolny=True)
    with db.polacz_baze() as conn:
        kursor = conn.execute(
            "INSERT INTO historia (zadanie_id, data, przebieg, kategoria, cena, zdalne_id) VALUES (?,?,?,?,?,?)",
            (ident["zadanie"], "2026-04-01", 102000, "Serwis", 300.0, "hist-pojedyncza"),
        )
        pojedyncza = kursor.lastrowid

    assert db.usun_wiele_z_cofnieciem("historia", [ident["historia"]])
    assert db.usun_z_cofnieciem("historia", pojedyncza)

    assert _auto_nagrobka("hist-1") == ident["auto_id"]
    assert _auto_nagrobka("hist-pojedyncza") == ident["auto_id"]
    # Części zdjęte z kasowanego wpisu dziedziczą pojazd tego wpisu.
    assert _auto_nagrobka("hcm-1") == ident["auto_id"]


def test_cofniecie_grupowego_usuwania_kasuje_nagrobki(pojazd_z_tankowaniami):
    """Nagrobki trzymamy teraz parami (zdalne_id, auto_id) — cofnięcie musi
    dalej trafiać w sam identyfikator."""
    _, ids = pojazd_z_tankowaniami

    wynik = db.usun_wiele_z_cofnieciem("tankowania", ids)
    wynik["cofnij"]()

    assert not {z for _, _, z in db.pobierz_nagrobki()} & {"tank-grupa-1", "tank-grupa-2"}


def test_podglad_nie_kasuje_grupowo_mimo_ominiecia_interfejsu(baza):
    """Ukrycie kosza to trzecia warstwa, nie jedyna — db dalej odmawia."""
    ident = utworz_pojazd("Cudze", wspolny=True)
    db.ustaw_role_pojazdu(ident["auto_id"], db.ROLA_PODGLAD)

    assert db.usun_wiele_z_cofnieciem("tankowania", [ident["tankowanie"]]) is None
    assert db.pobierz_nagrobki() == []
