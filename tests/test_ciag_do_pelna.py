"""Ostrzeżenie „to tankowanie przerywa ciąg” i dolewki we wskaźniku baku.

Zużycie liczy się wyłącznie z odcinków zamkniętych dwoma tankowaniami „do
pełna”. Niepełne po drodze nie przepadają — dopisują się do odcinka, który
zamknie następny pełny bak — ale dopóki go nie ma, zużycie za te kilometry
czeka. Użytkownik dowiadywał się o tym dopiero z dziury w statystykach,
tygodnie później i bez wskazania, który wpis ją zrobił. Teraz formularz mówi to
przy wpisie: pasek pod „do pełna”, gdy wpis byłby kolejnym z rzędu bez pełnego
baku, a odcinka nie zamyka jeszcze żaden późniejszy pełny.

Tu pilnujemy kolejności (ta sama, co w statystykach: data, potem licznik),
osobnego ciągu dla każdego źródła energii, wpisów z datą wstecz i edycji, treści
zdania — i tego, że obietnica „policzy się dopiero po pełnym baku” jest prawdą.

Przy okazji wskaźnik baku: liczył stan od ostatniego pełnego baku i pomijał
zapisane po nim dolewki, więc zaraz po niepełnym tankowaniu pokazywał za mało
paliwa (i potrafił zawołać „Czas zatankować”).
"""

from datetime import date

import pytest

import db
import pomoce
import utils


def _auto(typ="Benzyna", bak=None, nazwa="Ciąg"):
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO samochody (nazwa, marka, model, typ_paliwa, status, pojemnosc_baku) "
            "VALUES (?,?,?,?,?,?)",
            (nazwa, "Marka", "Model", typ, db.STATUS_POJAZDU_AKTYWNY, bak),
        )
        return c.lastrowid


def _tankuj(auto_id, data, przebieg, litry, pelny, rodzaj=None):
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO tankowania (auto_id, data, przebieg, dystans, litry, kwota, do_pelna, rodzaj_energii) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (auto_id, data, przebieg, 0, litry, litry * 7.0, 1 if pelny else 0, rodzaj),
        )
        return c.lastrowid


def _opis(auto_id, data, przebieg, rodzaj=db.ENERGIA_PALIWO, wyklucz_id=None):
    ciag = db.pobierz_ciag_do_pelna(auto_id, data, przebieg, rodzaj, wyklucz_id=wyklucz_id)
    return utils.opis_przerwanego_ciagu(ciag, rodzaj, przebieg)


# ------------------------------------------------------------ kiedy pasek jest


def test_po_pelnym_baku_nic_nie_czeka(baza):
    """Jedna dolewka po pełnym baku to codzienność, nie przerwany ciąg."""
    auto = _auto()
    _tankuj(auto, "01.09.2026", 10000, 40, True)

    assert _opis(auto, "10.09.2026", 10300) is None


def test_drugie_niepelne_z_rzedu(baza):
    auto = _auto()
    _tankuj(auto, "01.09.2026", 10000, 40, True)
    _tankuj(auto, "10.09.2026", 10300, 20, False)

    ciag = db.pobierz_ciag_do_pelna(auto, "20.09.2026", 10640, db.ENERGIA_PALIWO)
    assert ciag == {"niepelnych": 1, "pelny_data": "01.09.2026", "pelny_przebieg": 10000,
                    "najdalej": 10300, "zamkniety": False}
    assert utils.opis_przerwanego_ciagu(ciag, db.ENERGIA_PALIWO, 10640) == (
        "2 tankowania z rzędu bez „do pełna” — zużycie za 640 km "
        f"od {utils.formatuj_date_pl(date(2026, 9, 1))} policzy się dopiero po tankowaniu do pełna."
    )


def test_liczba_rosnie_z_ciagiem_i_odmienia_sie(baza):
    auto = _auto()
    _tankuj(auto, "01.09.2026", 10000, 40, True)
    for i in range(4):
        _tankuj(auto, f"0{i + 2}.09.2026", 10100 + 100 * i, 10, False)

    assert _opis(auto, "10.09.2026", 10600).startswith("5 tankowań z rzędu bez „do pełna”")


def test_bez_pelnego_baku_w_historii(baza):
    """Przed pierwszym pełnym bakiem nie ma od czego liczyć — i tak to mówimy."""
    auto = _auto()
    _tankuj(auto, "01.09.2026", 10000, 20, False)

    assert _opis(auto, "10.09.2026", 10300) == (
        "2 tankowania z rzędu bez „do pełna” — zużycie zacznie się liczyć dopiero "
        "od pierwszego tankowania do pełna."
    )


def test_obietnica_jest_prawdziwa_pelny_bak_zamyka_caly_ciag(baza):
    """Pasek mówi „policzy się dopiero po pełnym baku”, nie „nie policzy się”:
    niepełne wchodzą do odcinka zamkniętego następnym pełnym."""
    auto = _auto()
    _tankuj(auto, "01.09.2026", 10000, 40, True)
    _tankuj(auto, "05.09.2026", 10300, 20, False)
    _tankuj(auto, "10.09.2026", 10640, 20, False)
    assert db.pobierz_serie_spalania(auto, rodzaj=db.ENERGIA_PALIWO) == []

    _tankuj(auto, "20.09.2026", 11000, 30, True)
    seria = db.pobierz_serie_spalania(auto, rodzaj=db.ENERGIA_PALIWO)
    assert len(seria) == 1 and seria[0][1] == pytest.approx(7.0)   # 70 l na 1000 km


# ------------------------------------------------------------ kolejność i edycja


def test_kolejnosc_jak_w_statystykach_data_potem_licznik(baza):
    auto = _auto()
    _tankuj(auto, "01.09.2026", 10000, 40, True)
    _tankuj(auto, "10.09.2026", 10500, 35, True)

    # Bez licznika wpis staje na końcu swojego dnia — za pełnym bakiem z 10.09.
    bez_licznika = db.pobierz_ciag_do_pelna(auto, "10.09.2026", None, db.ENERGIA_PALIWO)
    assert (bez_licznika["pelny_przebieg"], bez_licznika["zamkniety"]) == (10500, False)
    # Z niższym licznikiem ten sam dzień stawia go PRZED tym pełnym bakiem.
    wczesniej = db.pobierz_ciag_do_pelna(auto, "10.09.2026", 10200, db.ENERGIA_PALIWO)
    assert (wczesniej["pelny_przebieg"], wczesniej["zamkniety"]) == (10000, True)


def test_wpis_wstecz_w_zamknietym_odcinku_milczy(baza):
    """Dopisane po czasie tankowanie wpada w odcinek, który już się policzył."""
    auto = _auto()
    _tankuj(auto, "01.09.2026", 10000, 40, True)
    _tankuj(auto, "05.09.2026", 10200, 15, False)
    _tankuj(auto, "20.09.2026", 10700, 30, True)

    ciag = db.pobierz_ciag_do_pelna(auto, "10.09.2026", 10400, db.ENERGIA_PALIWO)
    assert (ciag["niepelnych"], ciag["zamkniety"]) == (1, True)
    assert utils.opis_przerwanego_ciagu(ciag, db.ENERGIA_PALIWO, 10400) is None


def test_wpis_wstecz_w_otwartym_ciagu_liczy_tez_pozniejsze(baza):
    auto = _auto()
    _tankuj(auto, "01.09.2026", 10000, 40, True)
    _tankuj(auto, "20.09.2026", 10700, 30, False)

    ciag = db.pobierz_ciag_do_pelna(auto, "10.09.2026", 10400, db.ENERGIA_PALIWO)
    assert (ciag["niepelnych"], ciag["najdalej"], ciag["zamkniety"]) == (1, 10700, False)
    assert "za 700 km" in utils.opis_przerwanego_ciagu(ciag, db.ENERGIA_PALIWO, 10400)


def test_edytowany_wpis_nie_stoi_sam_przed_soba(baza):
    auto = _auto()
    _tankuj(auto, "01.09.2026", 10000, 40, True)
    niepelny = _tankuj(auto, "10.09.2026", 10300, 20, False)

    assert _opis(auto, "10.09.2026", 10300, wyklucz_id=niepelny) is None
    assert _opis(auto, "10.09.2026", 10300) is not None, "bez wyłączenia liczyłby się sam"


def test_hybryda_liczy_ciag_osobno_dla_kazdego_zrodla(baza):
    """Ładowania między dwoma tankowaniami nie mają nic wspólnego z bakiem."""
    auto = _auto("Hybryda plug-in")
    _tankuj(auto, "01.09.2026", 10000, 40, True, db.ENERGIA_PALIWO)
    _tankuj(auto, "03.09.2026", 10100, 8, False, db.ENERGIA_PRAD)
    _tankuj(auto, "05.09.2026", 10200, 9, False, db.ENERGIA_PRAD)

    assert _opis(auto, "10.09.2026", 10300, db.ENERGIA_PALIWO) is None
    assert _opis(auto, "10.09.2026", 10300, db.ENERGIA_PRAD) == (
        "3 ładowania z rzędu bez „do pełna” — zużycie zacznie się liczyć dopiero "
        "od pierwszego ładowania do pełna."
    )


def test_elektryk_mowi_o_ladowaniu(baza):
    auto = _auto("Elektryczny")
    _tankuj(auto, "01.09.2026", 10000, 50, True)
    _tankuj(auto, "05.09.2026", 10200, 20, False)

    assert _opis(auto, "10.09.2026", 10400, db.ENERGIA_PRAD).endswith("po ładowaniu do pełna.")


# ------------------------------------------------------------ formularz


def _zaraz_po(kontrolka, szukana):
    """Kontrolka stojąca w drzewie tuż za `szukana` (ta sama lista dzieci)."""
    do_odwiedzenia = [kontrolka]
    while do_odwiedzenia:
        biezaca = do_odwiedzenia.pop()
        dzieci = getattr(biezaca, "controls", None)
        if isinstance(dzieci, list):
            for i, dziecko in enumerate(dzieci):
                if dziecko is szukana:
                    return dzieci[i + 1] if i + 1 < len(dzieci) else None
            do_odwiedzenia.extend(dzieci)
        tresc = getattr(biezaca, "content", None)
        if tresc is not None and not isinstance(tresc, str):
            do_odwiedzenia.append(tresc)
    return None


@pytest.fixture
def otworz_formularz(monkeypatch):
    from views.formularze.tankowanie import FormularzTankowanieView

    def otworz(auto_id, duplikuj=None):
        strona = pomoce.zbuduj_strone()
        stan = pomoce.stan_aplikacji(auto_id, "Ciąg")
        stan.duplikuj_zrodlo_tankowanie = duplikuj
        widok = FormularzTankowanieView(strona.page, stan)
        # Strona trzyma sesję przez weakref — musi żyć tak długo jak widok.
        widok._strona_testowa = strona
        monkeypatch.setattr(widok.baner_ciagu, "update", lambda *a, **k: None)
        return widok

    return otworz


def test_pasek_pod_do_pelna_przed_zapisem(baza, otworz_formularz):
    auto = _auto()
    _tankuj(auto, "01.09.2026", 10000, 40, True)
    _tankuj(auto, "10.09.2026", 10300, 20, False)
    widok = otworz_formularz(auto)
    assert _zaraz_po(widok, widok.c_pel) is widok.baner_ciagu, "pasek stoi pod polem, którego dotyczy"

    assert widok.c_pel.value and not widok.baner_ciagu.visible, "nowe tankowanie jest domyślnie do pełna"

    widok.c_pel.value = False
    widok.c_pel.on_change(None)
    assert widok.baner_ciagu.visible
    assert "za 300 km" in widok.t_ciagu.value, "bez licznika — kilometry znanej części ciągu"

    widok.e_p.value = "10640"
    widok._odswiez_ostrzezenie_ciagu()
    assert "za 640 km" in widok.t_ciagu.value

    widok.c_pel.value = True
    widok.c_pel.on_change(None)
    assert not widok.baner_ciagu.visible


def test_duplikat_niepelnego_od_razu_pokazuje_pasek(baza, otworz_formularz):
    """Duplikat przenosi „do pełna” ze źródła — tak najłatwiej przerwać ciąg
    niechcący, więc pasek stoi od pierwszej chwili."""
    auto = _auto()
    _tankuj(auto, "01.09.2026", 10000, 40, True)
    niepelny = _tankuj(auto, "10.09.2026", 10300, 20, False)
    widok = otworz_formularz(auto, duplikuj=niepelny)

    assert widok.c_pel.value is False
    assert widok.baner_ciagu.visible and widok.t_ciagu.value.startswith("2 tankowania z rzędu")


# ------------------------------------------------------------ wskaźnik baku


def test_dolewka_po_pelnym_baku_jest_w_baku(baza):
    auto = _auto(bak="50")
    _tankuj(auto, "01.09.2026", 10000, 40, True)
    _tankuj(auto, "10.09.2026", 10500, 35, True)      # 7 l/100 km
    assert db.pobierz_zasieg_na_baku(auto)["pozostalo_jednostek"] == pytest.approx(50)

    _tankuj(auto, "15.09.2026", 10800, 20, False)     # 300 km = 21 l, dolane 20 l
    bak = db.pobierz_zasieg_na_baku(auto)
    assert bak["pozostalo_jednostek"] == pytest.approx(49)
    assert bak["procent_baku"] == pytest.approx(98)
    assert (bak["przejechane"], bak["data_tankowania"]) == (300, "10.09.2026"), "liczone od pełnego baku"


def test_dolewka_nie_przelewa_baku_ani_nie_zaczyna_od_minusa(baza):
    auto = _auto(bak="50")
    _tankuj(auto, "01.09.2026", 10000, 40, True)
    _tankuj(auto, "10.09.2026", 10500, 35, True)
    _tankuj(auto, "15.09.2026", 10600, 30, False)     # 43 l + 30 l — więcej się nie zmieści

    assert db.pobierz_zasieg_na_baku(auto)["pozostalo_jednostek"] == pytest.approx(50)

    # 900 km przy 7 l/100 km to 63 l z 50-litrowego baku: szacunek przestrzelił,
    # auto nie jechało na minusie. Dolewka liczy się od pustego baku.
    auto = _auto(bak="50", nazwa="Ciąg bez rezerwy")
    _tankuj(auto, "01.09.2026", 10000, 40, True)
    _tankuj(auto, "10.09.2026", 10500, 35, True)
    _tankuj(auto, "20.09.2026", 11400, 10, False)

    assert db.pobierz_zasieg_na_baku(auto)["pozostalo_jednostek"] == pytest.approx(10)
