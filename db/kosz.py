"""Kosz pojazdów: zrzut, przywracanie i trwałe kasowanie."""

import json
import os
import shutil
import sqlite3
import uuid
from datetime import datetime, timedelta

from .stale import DNI_KOSZA_DOMYSLNIE, DNI_KOSZA_OPCJE, FOLDER_KOSZ, TABELE_Z_ZALACZNIKIEM
from .polaczenie import polacz_baze
from .pomocnicze import parsuj_int_bezpiecznie
from .ustawienia import _pobierz_ustawienia_pojazdu, _przywroc_ustawienia_pojazdu, _usun_ustawienia_pojazdu, pobierz_ustawienie, zapisz_ustawienie
from .synchronizacja import usun_z_kolejki_sync, zakolejkuj_synchronizacje, zarejestruj_nagrobek
from .zalaczniki import usun_plik_zalacznika


def _upewnij_folder_kosza():
    os.makedirs(FOLDER_KOSZ, exist_ok=True)
    return FOLDER_KOSZ


# ============================================================================
#  KOSZ NA USUNIĘTE POJAZDY
# ============================================================================
# Usunięcie auta nie kasuje już danych: cały pojazd (tabela samochody + wszystkie
# tabele potomne) trafia jako migawka JSON do kosz_pojazdy, a fizyczne zdjęcia do
# FOLDER_KOSZ. Snackbar "Cofnij" przywraca od razu; bez cofnięcia pojazd czeka w
# koszu do ręcznego przywrócenia albo do wygaśnięcia retencji (patrz
# pobierz_dni_kosza / posprzataj_kosz).

# Kolejność MA ZNACZENIE przy odtwarzaniu — klucz obcy wymaga, żeby rodzic
# istniał wcześniej: historia zależy od zadań i wizyt, wizyta_czesci_magazynu od
# wizyt i magazynu, do_zrobienia od zadań.
KOSZ_TABELE_POTOMNE = [
    "zadania", "wizyty", "magazyn_czesci", "tagi", "tankowania",
    "inne_koszty", "zestawy_opon", "zdjecia_karoserii", "odczyty_przebiegu",
    "warsztaty", "wydatki_cykliczne", "pakiety_serwisowe_wlasne",
    "trasy_szablony", "checklisty",
    "do_zrobienia", "historia", "wizyta_czesci_magazynu", "historia_czesci_magazynu",
    "checklisty_pozycje",
    "budzety",
]


# Tabele bez kolumny auto_id — z pojazdem związane wyłącznie pośrednio.
KOSZ_TABELE_BEZ_AUTO_ID = {
    "historia", "wizyta_czesci_magazynu", "historia_czesci_magazynu", "checklisty_pozycje",
}


KOSZ_ZAPYTANIA_POSREDNIE = {
    "historia": "SELECT h.* FROM historia h JOIN zadania z ON h.zadanie_id = z.id WHERE z.auto_id=?",
    "wizyta_czesci_magazynu": "SELECT wcm.* FROM wizyta_czesci_magazynu wcm JOIN wizyty w ON wcm.wizyta_id = w.id WHERE w.auto_id=?",
    "historia_czesci_magazynu": (
        "SELECT hcm.* FROM historia_czesci_magazynu hcm "
        "JOIN historia h ON hcm.historia_id = h.id "
        "JOIN zadania z ON h.zadanie_id = z.id WHERE z.auto_id=?"
    ),
    "checklisty_pozycje": (
        "SELECT p.* FROM checklisty_pozycje p JOIN checklisty l ON p.checklista_id = l.id WHERE l.auto_id=?"
    ),
}


# Odwołania do przemapowania, gdy przywracany rekord NIE odzyska oryginalnego ID
# (bo w międzyczasie zajął je inny wpis — np. po imporcie bazy). Bez tego
# historia wróciłaby podpięta pod cudzy podzespół.
KOSZ_KLUCZE_OBCE = {
    "do_zrobienia": {"zadanie_id": "zadania"},
    "historia": {"zadanie_id": "zadania", "wizyta_id": "wizyty"},
    "wizyta_czesci_magazynu": {"wizyta_id": "wizyty", "magazyn_id": "magazyn_czesci"},
    "historia_czesci_magazynu": {"historia_id": "historia", "magazyn_id": "magazyn_czesci"},
    "checklisty_pozycje": {"checklista_id": "checklisty"},
}


# Tabele, których zdalne odpowiedniki trzeba oznaczyć jako usunięte na serwerze.
# CELOWO używane dopiero przy TRWAŁYM kasowaniu z kosza — dopóki auto siedzi w
# koszu, u współdzielących nadal istnieje.
# Lista MUSI pokrywać się z sync.KONFIGURACJA_SYNC — pilnuje tego
# tests/test_schemat.py. Tabela synchronizowana, której tu brakuje, zostaje
# u współdzielących na zawsze, bo nikt nie zgłasza jej usunięcia na serwer.
KOSZ_TABELE_SYNCHRONIZOWANE = [
    "zadania", "wizyty", "magazyn_czesci", "tankowania", "inne_koszty",
    "zestawy_opon", "odczyty_przebiegu", "warsztaty", "wydatki_cykliczne",
    "do_zrobienia", "historia", "tagi", "wizyta_czesci_magazynu",
    "historia_czesci_magazynu", "pakiety_serwisowe_wlasne",
    "trasy_szablony", "checklisty", "checklisty_pozycje", "budzety",
]


# Tabele liczone do "ile wpisów przepadnie" pokazywanego przy pozycji kosza.
# Tagi, warsztaty czy pakiety to konfiguracja, nie historia — nie zawyżamy nimi
# liczby, którą użytkownik czyta jako "tyle mojej pracy tu leży".
KOSZ_TABELE_LICZONE = [
    "tankowania", "historia", "wizyty", "inne_koszty", "zestawy_opon",
    "magazyn_czesci", "zdjecia_karoserii", "odczyty_przebiegu", "do_zrobienia",
]


def pobierz_dni_kosza():
    """Ile dni pojazd leży w koszu, zanim zniknie na dobre. 0 = bez limitu."""
    try:
        w = int(pobierz_ustawienie("dni_kosza", str(DNI_KOSZA_DOMYSLNIE)))
    except (TypeError, ValueError):
        return DNI_KOSZA_DOMYSLNIE
    return w if w in DNI_KOSZA_OPCJE else DNI_KOSZA_DOMYSLNIE


def zapisz_dni_kosza(dni):
    zapisz_ustawienie("dni_kosza", str(parsuj_int_bezpiecznie(dni, DNI_KOSZA_DOMYSLNIE)))


def _zrzut_tabeli_pojazdu(c, tabela, auto_id):
    c.execute(f"PRAGMA table_info({tabela})")
    kolumny = [r["name"] for r in c.fetchall()]
    c.execute(KOSZ_ZAPYTANIA_POSREDNIE.get(tabela, f"SELECT * FROM {tabela} WHERE auto_id=?"), (auto_id,))
    return {"kolumny": kolumny, "wiersze": [{k: w[k] for k in kolumny} for w in c.fetchall()]}


def usun_auto_do_kosza(auto_id):
    """Przenosi pojazd wraz z całą historią i zdjęciami do kosza.

    Zwraca słownik zgodny z utils.pokaz_komunikat_cofnij: "cofnij" przywraca auto
    natychmiast i zdejmuje je z kosza, a "finalizuj" (wywoływane po wygaśnięciu
    snackbara) NIE kasuje już niczego — pojazd zostaje w koszu. Dodatkowo
    "przywrocone_id" niesie ID pojazdu po cofnięciu (nie musi być tym samym, co
    przed usunięciem), żeby interfejs mógł wrócić na właściwe auto.
    """
    if not auto_id:
        return None

    folder = _upewnij_folder_kosza()
    tabele = {}

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("PRAGMA table_info(samochody)")
        kol_auta = [r["name"] for r in c.fetchall()]
        c.execute("SELECT * FROM samochody WHERE id=?", (auto_id,))
        w_auto = c.fetchone()
        if not w_auto:
            return None
        dane_auta = {k: w_auto[k] for k in kol_auta}

        for tab in KOSZ_TABELE_POTOMNE:
            tabele[tab] = _zrzut_tabeli_pojazdu(c, tab, auto_id)

    nazwa = str(dane_auta.get("nazwa") or "Pojazd")
    pliki = []

    # Zdjęcia wędrują do folderu kosza pod losowymi nazwami; oryginalna ścieżka
    # zostaje zapamiętana, żeby przywrócenie odtworzyło te same odsyłacze w bazie.
    def schowaj(sciezka, prefiks):
        if not sciezka or not os.path.exists(sciezka):
            return
        cel = os.path.join(folder, f"{prefiks}_{uuid.uuid4().hex}_{os.path.basename(sciezka)}")
        try:
            shutil.move(sciezka, cel)
            pliki.append([cel, sciezka])
        except Exception:
            pass

    schowaj(dane_auta.get("zdjecie_glowne"), "auto")
    for tab in KOSZ_TABELE_POTOMNE:
        if tab in TABELE_Z_ZALACZNIKIEM:
            for wiersz in tabele[tab]["wiersze"]:
                schowaj(wiersz.get("zalacznik"), "z")

    # Kaskada SQLite wyczyści wszystkie tabele potomne
    with polacz_baze() as conn:
        conn.execute("DELETE FROM samochody WHERE id=?", (auto_id,))

    # Zaległa auto-synchronizacja tego pojazdu nie ma już czego wypchnąć —
    # zostawiona w kolejce zapętlałaby próby na nieistniejącym aucie.
    usun_z_kolejki_sync(auto_id)

    liczba_wpisow = sum(len(tabele.get(t, {}).get("wiersze", [])) for t in KOSZ_TABELE_LICZONE)
    rozmiar = 0
    for para in pliki:
        try:
            rozmiar += os.path.getsize(para[0])
        except Exception:
            pass

    # Ustawienia przywiązane do tego auta (np. własny układ kokpitu) jadą razem
    # z nim — inaczej zostałyby w bazie jako sieroty, a po przywróceniu pod nowym
    # ID pojazd i tak by ich nie znalazł.
    ustawienia_auta = _pobierz_ustawienia_pojazdu(auto_id)
    _usun_ustawienia_pojazdu(auto_id)

    migawka = {
        "wersja": 1,
        "auto": {"kolumny": kol_auta, "wiersz": dane_auta},
        "tabele": tabele,
        "ustawienia": ustawienia_auta,
    }

    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO kosz_pojazdy (nazwa, data_usuniecia, migawka, pliki, liczba_wpisow, rozmiar_plikow, schemat_wersja) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                nazwa,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                json.dumps(migawka, ensure_ascii=False, default=str),
                json.dumps(pliki, ensure_ascii=False),
                liczba_wpisow,
                rozmiar,
                parsuj_int_bezpiecznie(pobierz_ustawienie("schema_version", "0"), 0),
            )
        )
        kosz_id = c.lastrowid

    wynik = {"kosz_id": kosz_id, "przywrocone_id": None, "cofniete": False}

    def cofnij():
        if wynik["cofniete"]:
            return
        wynik["cofniete"] = True
        wynik["przywrocone_id"] = przywroc_auto_z_kosza(kosz_id)

    def finalizuj():
        # Świadomie pusto: wygaśnięcie snackbara ZOSTAWIA pojazd w koszu.
        # To jest cała różnica względem dawnego, nieodwracalnego usuwania.
        return

    wynik["cofnij"] = cofnij
    wynik["finalizuj"] = finalizuj
    return wynik


def pobierz_kosz():
    """Pozycje kosza, najświeższe u góry. 'dni_do_usuniecia' to None przy
    retencji bez limitu, a 0 oznacza 'zniknie przy najbliższym starcie'."""
    dni_retencji = pobierz_dni_kosza()
    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        try:
            c.execute(
                "SELECT id, nazwa, data_usuniecia, liczba_wpisow, rozmiar_plikow "
                "FROM kosz_pojazdy ORDER BY data_usuniecia DESC, id DESC"
            )
        except sqlite3.OperationalError:
            return []
        wiersze = c.fetchall()

    teraz = datetime.now()
    pozycje = []
    for w in wiersze:
        usunieto = None
        try:
            usunieto = datetime.strptime(str(w["data_usuniecia"]), "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            pass
        if dni_retencji and usunieto:
            zostalo = dni_retencji - (teraz - usunieto).days
            dni_do_usuniecia = max(0, zostalo)
        else:
            dni_do_usuniecia = None
        pozycje.append({
            "id": w["id"],
            "nazwa": str(w["nazwa"] or "Pojazd"),
            "data_usuniecia": usunieto,
            "data_tekst": usunieto.strftime("%d.%m.%Y %H:%M") if usunieto else "—",
            "liczba_wpisow": int(w["liczba_wpisow"] or 0),
            "rozmiar_plikow": int(w["rozmiar_plikow"] or 0),
            "dni_do_usuniecia": dni_do_usuniecia,
        })
    return pozycje


def liczba_w_koszu():
    with polacz_baze() as conn:
        c = conn.cursor()
        try:
            c.execute("SELECT COUNT(*) FROM kosz_pojazdy")
        except sqlite3.OperationalError:
            return 0
        return int((c.fetchone() or [0])[0])


def przywroc_auto_z_kosza(kosz_id):
    """Przywraca pojazd z kosza. Zwraca ID przywróconego auta albo None.

    ID rekordów odzyskujemy 1:1, kiedy tylko są wolne. Gdy któreś zdążył zająć
    nowy wpis, rekord dostaje świeże ID, a wszystkie odwołania do niego są
    przemapowane (KOSZ_KLUCZE_OBCE). Kolumn, których nie ma już w bieżącym
    schemacie (migawka ze starszej wersji aplikacji), po prostu nie wstawiamy.
    """
    if not kosz_id:
        return None

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM kosz_pojazdy WHERE id=?", (kosz_id,))
        w = c.fetchone()
        if not w:
            return None
        try:
            migawka = json.loads(w["migawka"])
            pliki = json.loads(w["pliki"] or "[]")
        except (TypeError, ValueError):
            return None

    dane_auta = dict((migawka.get("auto") or {}).get("wiersz") or {})
    if not dane_auta:
        return None
    tabele = migawka.get("tabele") or {}

    # Zdjęcia wracają na swoje stare ścieżki. Gdy któraś jest już zajęta, plik
    # dostaje nową nazwę, a odwołanie w bazie jest podmieniane.
    podmiana = {}
    for para in pliki:
        try:
            zrodlo, oryginal = para[0], para[1]
        except (IndexError, TypeError):
            continue
        if not zrodlo or not os.path.exists(zrodlo):
            continue
        cel = oryginal
        if os.path.exists(cel):
            trzon, rozszerzenie = os.path.splitext(oryginal)
            cel = f"{trzon}_{uuid.uuid4().hex[:8]}{rozszerzenie}"
        try:
            katalog = os.path.dirname(cel)
            if katalog:
                os.makedirs(katalog, exist_ok=True)
            shutil.move(zrodlo, cel)
            if cel != oryginal:
                podmiana[oryginal] = cel
        except Exception:
            pass

    if dane_auta.get("zdjecie_glowne") in podmiana:
        dane_auta["zdjecie_glowne"] = podmiana[dane_auta["zdjecie_glowne"]]

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        def kolumny_tabeli(tab):
            c.execute(f"PRAGMA table_info({tab})")
            return {r["name"] for r in c.fetchall()}

        def id_wolne(tab, wartosc):
            if wartosc is None:
                return False
            c.execute(f"SELECT 1 FROM {tab} WHERE id=?", (wartosc,))
            return c.fetchone() is None

        # samochody.nazwa jest UNIQUE — jeśli w międzyczasie powstało auto o tej
        # samej nazwie, przywracane dostaje dopisek zamiast wywalić całą operację.
        nazwa_bazowa = str(dane_auta.get("nazwa") or "Pojazd")
        nazwa = nazwa_bazowa
        licznik = 2
        while True:
            c.execute("SELECT 1 FROM samochody WHERE nazwa=?", (nazwa,))
            if c.fetchone() is None:
                break
            nazwa = f"{nazwa_bazowa} ({licznik})"
            licznik += 1
        dane_auta["nazwa"] = nazwa

        kol_samochody = kolumny_tabeli("samochody")
        rekord = {k: v for k, v in dane_auta.items() if k in kol_samochody}
        if not id_wolne("samochody", rekord.get("id")):
            rekord.pop("id", None)
        nazwy_kolumn = list(rekord.keys())
        c.execute(
            f"INSERT INTO samochody ({','.join(nazwy_kolumn)}) VALUES ({','.join('?' * len(nazwy_kolumn))})",
            tuple(rekord[k] for k in nazwy_kolumn)
        )
        nowe_auto_id = c.lastrowid

        mapy = {}
        for tab in KOSZ_TABELE_POTOMNE:
            mapy[tab] = {}
            wiersze = (tabele.get(tab) or {}).get("wiersze") or []
            if not wiersze:
                continue
            kolumny = kolumny_tabeli(tab)
            for zrodlowy in wiersze:
                dane = {k: v for k, v in zrodlowy.items() if k in kolumny}
                if not dane:
                    continue
                stare_id = dane.get("id")
                if tab not in KOSZ_TABELE_BEZ_AUTO_ID and "auto_id" in kolumny:
                    dane["auto_id"] = nowe_auto_id
                for kolumna, rodzic in KOSZ_KLUCZE_OBCE.get(tab, {}).items():
                    if dane.get(kolumna) is not None:
                        dane[kolumna] = mapy.get(rodzic, {}).get(dane[kolumna], dane[kolumna])
                if dane.get("zalacznik") in podmiana:
                    dane["zalacznik"] = podmiana[dane["zalacznik"]]
                if not id_wolne(tab, stare_id):
                    dane.pop("id", None)
                nazwy_kolumn = list(dane.keys())
                c.execute(
                    f"INSERT INTO {tab} ({','.join(nazwy_kolumn)}) VALUES ({','.join('?' * len(nazwy_kolumn))})",
                    tuple(dane[k] for k in nazwy_kolumn)
                )
                if stare_id is not None:
                    mapy[tab][stare_id] = c.lastrowid

        c.execute("DELETE FROM kosz_pojazdy WHERE id=?", (kosz_id,))

    _przywroc_ustawienia_pojazdu(nowe_auto_id, migawka.get("ustawienia"))

    # Pojazd współdzielony wraca też do kolejki synchronizacji — przywrócenie
    # mogło zmienić lokalne ID, a serwer musi zobaczyć aktualny stan.
    if dane_auta.get("wspolny_pojazd_id"):
        try:
            zakolejkuj_synchronizacje(nowe_auto_id, "Przywrócenie pojazdu z kosza")
        except Exception:
            pass

    return nowe_auto_id


def usun_z_kosza_trwale(kosz_id):
    """Kasuje pozycję kosza bezpowrotnie: zdjęcia z dysku plus nagrobki, żeby
    usunięcie dotarło przy najbliższej synchronizacji także na serwer i do
    współdzielących. Zwraca nazwę usuniętego pojazdu albo None."""
    if not kosz_id:
        return None

    with polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM kosz_pojazdy WHERE id=?", (kosz_id,))
        w = c.fetchone()
        if not w:
            return None
        nazwa = str(w["nazwa"] or "Pojazd")
        try:
            migawka = json.loads(w["migawka"])
            pliki = json.loads(w["pliki"] or "[]")
        except (TypeError, ValueError):
            migawka, pliki = {}, []

    dane_auta = (migawka.get("auto") or {}).get("wiersz") or {}
    tabele = migawka.get("tabele") or {}

    for tab in KOSZ_TABELE_SYNCHRONIZOWANE:
        for wiersz in (tabele.get(tab) or {}).get("wiersze") or []:
            zdalne = wiersz.get("zdalne_id")
            if zdalne:
                zarejestruj_nagrobek(tab, zdalne)

    # Dane opisowe pojazdu mają własny zdalny odpowiednik (sync._synchronizuj_info_pojazdu)
    if dane_auta.get("info_zdalne_id"):
        zarejestruj_nagrobek("info_pojazdu", dane_auta["info_zdalne_id"])

    for para in pliki:
        try:
            usun_plik_zalacznika(para[0])
        except (IndexError, TypeError):
            pass

    with polacz_baze() as conn:
        conn.execute("DELETE FROM kosz_pojazdy WHERE id=?", (kosz_id,))

    return nazwa


def oproznij_kosz():
    """Trwale kasuje wszystkie pozycje kosza. Zwraca liczbę usuniętych pojazdów."""
    with polacz_baze() as conn:
        c = conn.cursor()
        try:
            c.execute("SELECT id FROM kosz_pojazdy")
        except sqlite3.OperationalError:
            return 0
        identyfikatory = [r[0] for r in c.fetchall()]

    usuniete = 0
    for kosz_id in identyfikatory:
        if usun_z_kosza_trwale(kosz_id):
            usuniete += 1
    return usuniete


def posprzataj_kosz():
    """Kasuje pozycje kosza starsze niż ustawiona retencja. Wywoływane raz, przy
    starcie aplikacji (init_db). Retencja 0 = trzymaj bez limitu."""
    # Sieroty po nagłym zamknięciu aplikacji sprzątamy ZAWSZE — także przy
    # retencji "nigdy", która wyłącza tylko kasowanie samych pozycji kosza.
    _posprzataj_osierocone_pliki_kosza()

    dni = pobierz_dni_kosza()
    if not dni:
        return 0

    granica = (datetime.now() - timedelta(days=dni)).strftime("%Y-%m-%d %H:%M:%S")
    with polacz_baze() as conn:
        c = conn.cursor()
        try:
            c.execute("SELECT id FROM kosz_pojazdy WHERE data_usuniecia <= ?", (granica,))
        except sqlite3.OperationalError:
            return 0
        identyfikatory = [r[0] for r in c.fetchall()]

    usuniete = 0
    for kosz_id in identyfikatory:
        try:
            if usun_z_kosza_trwale(kosz_id):
                usuniete += 1
        except Exception:
            pass

    return usuniete


def _posprzataj_osierocone_pliki_kosza():
    folder = _upewnij_folder_kosza()
    uzywane = set()
    with polacz_baze() as conn:
        c = conn.cursor()
        try:
            c.execute("SELECT pliki FROM kosz_pojazdy")
        except sqlite3.OperationalError:
            return
        for (surowe,) in c.fetchall():
            try:
                for para in json.loads(surowe or "[]"):
                    uzywane.add(os.path.normcase(os.path.abspath(para[0])))
            except (TypeError, ValueError, IndexError):
                continue
    try:
        for nazwa_pliku in os.listdir(folder):
            sciezka = os.path.join(folder, nazwa_pliku)
            if os.path.isfile(sciezka) and os.path.normcase(os.path.abspath(sciezka)) not in uzywane:
                try:
                    os.remove(sciezka)
                except Exception:
                    pass
    except Exception:
        pass


__all__ = [
    "KOSZ_KLUCZE_OBCE",
    "KOSZ_TABELE_BEZ_AUTO_ID",
    "KOSZ_TABELE_LICZONE",
    "KOSZ_TABELE_POTOMNE",
    "KOSZ_TABELE_SYNCHRONIZOWANE",
    "KOSZ_ZAPYTANIA_POSREDNIE",
    "_posprzataj_osierocone_pliki_kosza",
    "_upewnij_folder_kosza",
    "_zrzut_tabeli_pojazdu",
    "liczba_w_koszu",
    "oproznij_kosz",
    "pobierz_dni_kosza",
    "pobierz_kosz",
    "posprzataj_kosz",
    "przywroc_auto_z_kosza",
    "usun_auto_do_kosza",
    "usun_z_kosza_trwale",
    "zapisz_dni_kosza",
]
