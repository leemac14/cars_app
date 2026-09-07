"""Narzędzia wspólne dla testów: zrzuty bazy, budowanie pojazdu z danymi.

Nic tu nie sprawdza — same asercje siedzą w plikach test_*.py. Tu jest tylko to,
co musi wyglądać tak samo w kilku testach naraz.
"""

import hashlib
import os
import sqlite3

import db


# Tabele pomijane przy porównywaniu zawartości bazy „przed” i „po”.
# `sqlite_sequence` to licznik AUTOINCREMENT, a `kosz_pojazdy` z definicji
# zmienia się w trakcie round-tripu (wpis powstaje i znika).
TABELE_POMIJANE_W_POROWNANIU = {"sqlite_sequence", "kosz_pojazdy"}


def nazwy_tabel(pomijane=()):
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        return [t for (t,) in c.fetchall() if not t.startswith("sqlite_") and t not in pomijane]


def kolumny(tabela):
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute(f"PRAGMA table_info({tabela})")
        return [r[1] for r in c.fetchall()]


def zrzut_schematu():
    """Schemat bazy w postaci porównywalnej: tabele, kolumny (nazwa, typ,
    NOT NULL, wartość domyślna, klucz główny), indeksy i klucze obce.

    Świadomie NIE porównujemy surowego `sqlite_master.sql`: `ALTER TABLE ADD
    COLUMN` nie przepisuje tekstu CREATE, więc ten sam efektywny schemat może
    mieć różny zapis. Liczy się to, co widzi zapytanie."""
    schemat = {}
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tabele = [t for (t,) in c.fetchall() if not t.startswith("sqlite_")]
        for tabela in tabele:
            c.execute(f"PRAGMA table_info({tabela})")
            kol = [(r[1], (r[2] or "").upper(), r[3], r[4], r[5]) for r in c.fetchall()]
            c.execute(f"PRAGMA foreign_key_list({tabela})")
            obce = sorted((r[2], r[3], r[4]) for r in c.fetchall())
            c.execute(f"PRAGMA index_list({tabela})")
            indeksy = []
            for wiersz in c.fetchall():
                nazwa_indeksu, unikalny = wiersz[1], wiersz[2]
                c.execute(f"PRAGMA index_info({nazwa_indeksu})")
                pola = tuple(r[2] for r in c.fetchall())
                indeksy.append((nazwa_indeksu, unikalny, pola))
            schemat[tabela] = {
                "kolumny": kol,
                "klucze_obce": obce,
                "indeksy": sorted(indeksy),
            }
    return schemat


def zrzut_danych(pomijane=TABELE_POMIJANE_W_POROWNANIU):
    """Cała zawartość bazy jako {tabela: posortowana lista krotek}.

    To jest operacyjne znaczenie „bit w bit" z notatki o koszu: nie bajty pliku
    .db (te zależą od układu stron i kolejności zapisów), tylko każdy wiersz
    każdej tabeli z każdą wartością."""
    dane = {}
    with db.polacz_baze() as conn:
        c = conn.cursor()
        for tabela in nazwy_tabel(pomijane):
            kol = kolumny(tabela)
            c.execute(f"SELECT {','.join(kol)} FROM {tabela}")
            dane[tabela] = sorted(c.fetchall(), key=lambda w: tuple(str(x) for x in w))
    return dane


def suma_pliku(sciezka):
    with open(sciezka, "rb") as plik:
        return hashlib.sha256(plik.read()).hexdigest()


def odciski_zalacznikow():
    """{ścieżka: sha256} dla wszystkich plików wskazywanych przez bazę.

    Sprawdza JEDNOCZEŚNIE dwie rzeczy: że odsyłacz w bazie prowadzi do
    istniejącego pliku i że treść pliku się nie zmieniła."""
    odciski = {}
    with db.polacz_baze() as conn:
        c = conn.cursor()
        for tabela, kolumna in db.KOLUMNY_ZE_SCIEZKAMI:
            if kolumna not in kolumny(tabela):
                continue
            c.execute(f"SELECT {kolumna} FROM {tabela} WHERE {kolumna} IS NOT NULL AND TRIM({kolumna})<>''")
            for (sciezka,) in c.fetchall():
                odciski[sciezka] = suma_pliku(sciezka) if os.path.exists(sciezka) else None
    return odciski


def klucze_obce_spojne():
    """Pusta lista = wszystkie klucze obce wskazują na istniejące wiersze."""
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute("PRAGMA foreign_key_check")
        return c.fetchall()


def _plik_zalacznika(katalog, nazwa, tresc):
    os.makedirs(katalog, exist_ok=True)
    sciezka = os.path.join(katalog, nazwa)
    with open(sciezka, "wb") as plik:
        plik.write(tresc)
    return sciezka


def utworz_pojazd(nazwa="Testowy", z_zalacznikami=True, wspolny=False):
    """Pojazd z wpisem w KAŻDEJ tabeli potomnej kosza plus załączniki na dysku.

    Zwraca słownik z `auto_id` i identyfikatorami wpisów, których potrzebują
    testy przemapowania kluczy obcych. Wstawiamy SQL-em, a nie przez formularze,
    bo testowany jest kosz i schemat, nie warstwa interfejsu."""
    folder = db.FOLDER_ZALACZNIKI
    zid = {}

    with db.polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        zdjecie = _plik_zalacznika(folder, f"{nazwa}_glowne.jpg", b"GLOWNE-" + nazwa.encode()) if z_zalacznikami else None
        c.execute(
            "INSERT INTO samochody (nazwa, marka, model, typ_paliwa, nadwozie, status, "
            "zdjecie_glowne, wspolny_pojazd_id, info_zdalne_id, rola_wspoldzielenia) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (nazwa, "Marka", "Model", "Benzyna", "Sedan", db.STATUS_POJAZDU_AKTYWNY,
             zdjecie, "wspolny-1" if wspolny else None, "info-zdalne-1" if wspolny else None,
             db.ROLA_WLASCICIEL),
        )
        auto = c.lastrowid

        c.execute("INSERT INTO zadania (auto_id, nazwa, interwal_km, dotyczy_opon, zdalne_id) VALUES (?,?,?,?,?)",
                  (auto, "Olej silnikowy i filtr", 15000, 0, "zad-1"))
        zid["zadanie"] = c.lastrowid

        c.execute("INSERT INTO wizyty (auto_id, data, przebieg, wykonawca, koszt_calkowity, zalacznik, zdalne_id) VALUES (?,?,?,?,?,?,?)",
                  (auto, "2026-01-10", 100000, "Warsztat u Janka", 480.0,
                   _plik_zalacznika(folder, f"{nazwa}_wizyta.jpg", b"WIZYTA") if z_zalacznikami else None, "wiz-1"))
        zid["wizyta"] = c.lastrowid

        c.execute("INSERT INTO magazyn_czesci (auto_id, nazwa, kategoria, ilosc, jednostka, cena, zalacznik, zdalne_id) VALUES (?,?,?,?,?,?,?,?)",
                  (auto, "Filtr oleju", "Filtry", 2.0, "szt", 39.0,
                   _plik_zalacznika(folder, f"{nazwa}_czesc.jpg", b"CZESC") if z_zalacznikami else None, "mag-1"))
        zid["magazyn"] = c.lastrowid

        c.execute("INSERT INTO tagi (auto_id, nazwa, kolor, zdalne_id) VALUES (?,?,?,?)", (auto, "Trasa", "#FF0000", "tag-1"))
        zid["tag"] = c.lastrowid

        c.execute("INSERT INTO tankowania (auto_id, data, przebieg, dystans, litry, kwota, do_pelna, stacja, rodzaj_energii, notatka, zalacznik, zdalne_id) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (auto, "2026-02-01", 100500, 500.0, 32.5, 210.0, 1, "Orlen", db.ENERGIA_PALIWO, "Pełny bak przed trasą",
                   _plik_zalacznika(folder, f"{nazwa}_paragon.jpg", b"PARAGON") if z_zalacznikami else None, "tank-1"))
        zid["tankowanie"] = c.lastrowid

        c.execute("INSERT INTO inne_koszty (auto_id, data, kategoria, nazwa, kwota, zdalne_id) VALUES (?,?,?,?,?,?)",
                  (auto, "2026-02-03", db.KATEGORIA_INNE_DROGOWE, "Winieta", 120.0, "inne-1"))
        zid["inny_koszt"] = c.lastrowid

        c.execute("INSERT INTO zestawy_opon (auto_id, sezon, rozmiar, ilosc, zamontowane, os_montazu, zdalne_id) VALUES (?,?,?,?,?,?,?)",
                  (auto, "Zimowe", "205/55 R16", 4, 1, "Wszystkie", "opony-1"))
        zid["opony"] = c.lastrowid

        c.execute("INSERT INTO zdjecia_karoserii (auto_id, data, strefa, zalacznik, opis) VALUES (?,?,?,?,?)",
                  (auto, "2026-01-05", "Przód",
                   _plik_zalacznika(folder, f"{nazwa}_karoseria.jpg", b"KAROSERIA") if z_zalacznikami else os.path.join(folder, "brak.jpg"),
                   "Rysa na zderzaku"))
        zid["karoseria"] = c.lastrowid

        c.execute("INSERT INTO odczyty_przebiegu (auto_id, data, przebieg, zrodlo, zdalne_id) VALUES (?,?,?,?,?)",
                  (auto, "2026-02-10", 101000, db.ZRODLO_ODCZYTU_DOMYSLNE, "odczyt-1"))
        zid["odczyt"] = c.lastrowid

        c.execute("INSERT INTO warsztaty (auto_id, nazwa, telefon, zdalne_id) VALUES (?,?,?,?)", (auto, "Warsztat u Janka", "123456789", "warsztat-1"))
        zid["warsztat"] = c.lastrowid

        c.execute("INSERT INTO wydatki_cykliczne (auto_id, nazwa, kwota, okres_dni, nastepna_data, czy_koszt, typ, zdalne_id) VALUES (?,?,?,?,?,?,?,?)",
                  (auto, "Ubezpieczenie", 1200.0, 365, "2026-12-01", 1, db.TYP_CYKLICZNY_WYDATEK, "cykl-1"))
        zid["cykliczny"] = c.lastrowid

        c.execute("INSERT INTO pakiety_serwisowe_wlasne (auto_id, nazwa, pozycje, zdalne_id) VALUES (?,?,?,?)",
                  (auto, "Mój przegląd", "Olej silnikowy i filtr", "pakiet-1"))
        zid["pakiet"] = c.lastrowid

        c.execute("INSERT INTO trasy_szablony (auto_id, nazwa, dystans, powrot, osoby, oplaty, zdalne_id) VALUES (?,?,?,?,?,?,?)",
                  (auto, "Do teściów", 180.0, 1, 2, 45.0, "trasa-1"))
        zid["trasa"] = c.lastrowid

        c.execute("INSERT INTO checklisty (auto_id, nazwa, opis, zdalne_id) VALUES (?,?,?,?)",
                  (auto, "Przed dłuższą trasą", "Obchód auta", "check-1"))
        zid["checklista"] = c.lastrowid

        c.execute("INSERT INTO budzety (auto_id, kategoria, okres, kwota, zdalne_id) VALUES (?,?,?,?,?)",
                  (auto, "Paliwo", "miesiac", 600.0, "budzet-1"))
        zid["budzet"] = c.lastrowid

        c.execute("INSERT INTO do_zrobienia (auto_id, tytul, opis, priorytet, zadanie_id, wykonane, data_utworzenia, zdalne_id) VALUES (?,?,?,?,?,?,?,?)",
                  (auto, "Umówić przegląd", "Zadzwonić do Janka", "Wysoki", zid["zadanie"], 0, "2026-02-01", "todo-1"))
        zid["do_zrobienia"] = c.lastrowid

        c.execute("INSERT INTO historia (zadanie_id, wizyta_id, data, przebieg, kategoria, cena, wykonawca, notatka, zalacznik, zdalne_id) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (zid["zadanie"], zid["wizyta"], "2026-01-10", 100000, "Serwis", 480.0, "Warsztat u Janka", "Olej Castrol",
                   _plik_zalacznika(folder, f"{nazwa}_wpis.jpg", b"WPIS") if z_zalacznikami else None, "hist-1"))
        zid["historia"] = c.lastrowid

        c.execute("INSERT INTO wizyta_czesci_magazynu (wizyta_id, magazyn_id, ilosc_uzyta, zdalne_id) VALUES (?,?,?,?)",
                  (zid["wizyta"], zid["magazyn"], 1.0, "wcm-1"))
        zid["wizyta_czesc"] = c.lastrowid

        c.execute("INSERT INTO historia_czesci_magazynu (historia_id, magazyn_id, ilosc_uzyta, zdalne_id) VALUES (?,?,?,?)",
                  (zid["historia"], zid["magazyn"], 1.0, "hcm-1"))
        zid["historia_czesc"] = c.lastrowid

        c.execute("INSERT INTO checklisty_pozycje (checklista_id, tresc, kolejnosc, odhaczone, zdalne_id) VALUES (?,?,?,?,?)",
                  (zid["checklista"], "Ciśnienie w oponach", 0, 1, "poz-1"))
        zid["pozycja_checklisty"] = c.lastrowid

        # Tabela spoza kosza — świadomie, żeby testy widziały różnicę.
        c.execute("INSERT INTO wyciszone_powiadomienia (auto_id, klucz, do_dnia, tytul) VALUES (?,?,?,?)",
                  (auto, "oc", "2026-12-31", "Polisa OC"))

    # Ustawienie przywiązane do pojazdu — musi pojechać do kosza i wrócić.
    db.zapisz_ustawienie(db.ustawienia._klucz_kokpitu(auto), "przebieg,paliwo,terminy")

    return {"auto_id": auto, **zid}


# ============================================================================
#  HEADLESS FLET
# ============================================================================
# Kontrolki Fleta budują się bez okna i bez pętli zdarzeń, ale `ft.Page` wymaga
# sesji i trzyma ją przez WEAKREF — obiekt sesji musi więc gdzieś żyć, inaczej
# `page.update()` wywala się na „An attempt to fetch destroyed session".
# Dlatego strona i jej sesja wracają razem, w jednym obiekcie.

class _SesjaZastepcza:
    """Minimum, którego oczekuje ft.Page. Każda inna metoda jest pustym gestem."""

    def __init__(self):
        self.index = {}

    def __getattr__(self, _nazwa):
        return lambda *args, **kwargs: None


class StronaTestowa:
    def __init__(self):
        import flet as ft

        self.sesja = _SesjaZastepcza()
        self.page = ft.Page(self.sesja)
        self.page.width = 420
        self.page.height = 900


def zbuduj_strone():
    return StronaTestowa()


def policz_kontrolki(kontrolka, limit=20000):
    """Ile kontrolek ma poddrzewo — prosty dowód, że widok cokolwiek narysował."""
    import flet as ft

    do_odwiedzenia = [kontrolka]
    ile = 0
    while do_odwiedzenia and ile < limit:
        biezaca = do_odwiedzenia.pop()
        ile += 1
        for nazwa in ("controls", "content", "appbar", "floating_action_button", "drawer", "navigation_bar"):
            wartosc = getattr(biezaca, nazwa, None)
            if isinstance(wartosc, (list, tuple)):
                do_odwiedzenia.extend(w for w in wartosc if isinstance(w, ft.Control))
            elif isinstance(wartosc, ft.Control):
                do_odwiedzenia.append(wartosc)
    return ile


# ============================================================================
#  WIDOKI
# ============================================================================
# Lista widoków NIE jest nigdzie wypisana ręcznie — bierze się z przejścia
# pakietu `views`. Nowy ekran jest objęty testami od razu.

# Argumenty konstruktorów poza `page` i `state`. Nieznana nazwa = błąd testu,
# a nie ciche podanie None: nowy widok z nowym argumentem ma się zgłosić.
ARGUMENTY_WYWOLYWALNE = {"cb_export", "cb_import", "cb_theme", "cb_eksportuj"}

# Nazwa argumentu -> klucz w słowniku z utworz_pojazd().
ARGUMENTY_IDENTYFIKATOROW = {
    "auto_id": "auto_id",
    "z_id": "zadanie",
    "z_id_param": "zadanie",
    "t_id": "tankowanie",
    "w_id": "wizyta",
    "h_id": "historia",
    "i_id": "inny_koszt",
    "zestaw_id": "opony",
    "czesc_id": "magazyn",
    "wpis_id": "karoseria",
    "pozycja_id": "do_zrobienia",
}

_KLASY_WIDOKOW = None


def klasy_widokow():
    """{nazwa klasy: klasa} dla wszystkich podklas ft.View w pakiecie `views`."""
    global _KLASY_WIDOKOW
    if _KLASY_WIDOKOW is not None:
        return _KLASY_WIDOKOW

    import importlib
    import inspect
    import pkgutil

    import flet as ft
    import views

    znalezione = {}
    for modul in pkgutil.walk_packages(views.__path__, "views."):
        zaimportowany = importlib.import_module(modul.name)
        for nazwa, obiekt in vars(zaimportowany).items():
            if (
                inspect.isclass(obiekt)
                and issubclass(obiekt, ft.View)
                and obiekt is not ft.View
                and obiekt.__module__ == modul.name
            ):
                znalezione[nazwa] = obiekt
    _KLASY_WIDOKOW = dict(sorted(znalezione.items()))
    return _KLASY_WIDOKOW


def zbuduj_widok(klasa, strona, stan, identyfikatory=None):
    """Woła konstruktor, dobierając argumenty po NAZWIE, nie po pozycji."""
    import inspect

    def nic(*args, **kwargs):
        return None

    wartosci = []
    for nazwa, parametr in list(inspect.signature(klasa.__init__).parameters.items())[1:]:
        if nazwa == "page":
            wartosci.append(strona.page)
        elif nazwa == "state":
            wartosci.append(stan)
        elif nazwa in ARGUMENTY_WYWOLYWALNE:
            wartosci.append(nic)
        elif nazwa in ARGUMENTY_IDENTYFIKATOROW:
            wartosci.append((identyfikatory or {}).get(ARGUMENTY_IDENTYFIKATOROW[nazwa]))
        elif nazwa == "rok":
            wartosci.append(2026 if identyfikatory else None)
        elif parametr.default is not inspect.Parameter.empty:
            wartosci.append(parametr.default)
        else:
            raise AssertionError(
                f"{klasa.__name__}: nieznany argument konstruktora `{nazwa}` — dopisz go do "
                "ARGUMENTY_IDENTYFIKATOROW albo ARGUMENTY_WYWOLYWALNE w tests/pomoce.py"
            )
    return klasa(*wartosci)


SCENARIUSZE = [
    "pusty_garaz",
    "pojazd_bez_danych",
    "pojazd_z_danymi",
    "pojazd_z_historia",
    "elektryk",
    "hybryda_plug_in",
    "sprzedany",
    "wspoldzielony_podglad",
    "kosz_pelny",
]


def stan_aplikacji(auto_id=None, nazwa="Brak pojazdów"):
    from state import AppState

    stan = AppState()
    stan.auto_id = auto_id
    stan.auto_nazwa = nazwa
    return stan


def przygotuj_scenariusz(nazwa):
    """Zwraca (stan aplikacji, identyfikatory wpisów albo None). Wymaga fixture'u `baza`."""
    if nazwa == "pusty_garaz":
        return stan_aplikacji(), None

    if nazwa == "pojazd_bez_danych":
        with db.polacz_baze() as conn:
            conn.execute(
                "INSERT INTO samochody (nazwa, typ_paliwa, status, rola_wspoldzielenia) VALUES (?,?,?,?)",
                ("Goły", "Benzyna", db.STATUS_POJAZDU_AKTYWNY, db.ROLA_WLASCICIEL),
            )
        return stan_aplikacji(1, "Goły"), None

    if nazwa == "pojazd_z_danymi":
        identyfikatory = utworz_pojazd("Pełny")
        return stan_aplikacji(identyfikatory["auto_id"], "Pełny"), identyfikatory

    if nazwa == "pojazd_z_historia":
        identyfikatory = utworz_pojazd("Zajeżdżony")
        dosyp_dane(identyfikatory["auto_id"])
        return stan_aplikacji(identyfikatory["auto_id"], "Zajeżdżony"), identyfikatory

    if nazwa in ("elektryk", "hybryda_plug_in"):
        paliwo = "Elektryczny" if nazwa == "elektryk" else "Hybryda plug-in"
        identyfikatory = utworz_pojazd("Prądowy")
        with db.polacz_baze() as conn:
            conn.execute("UPDATE samochody SET typ_paliwa=?, pojemnosc_baterii=? WHERE id=?",
                         (paliwo, 58.0, identyfikatory["auto_id"]))
            conn.execute("UPDATE tankowania SET rodzaj_energii=?, typ_ladowania=? WHERE auto_id=?",
                         (db.ENERGIA_PRAD, "AC", identyfikatory["auto_id"]))
        return stan_aplikacji(identyfikatory["auto_id"], "Prądowy"), identyfikatory

    if nazwa == "sprzedany":
        identyfikatory = utworz_pojazd("Sprzedany")
        db.oznacz_pojazd_sprzedany(identyfikatory["auto_id"], "2026-06-01", 32000.0)
        return stan_aplikacji(identyfikatory["auto_id"], "Sprzedany"), identyfikatory

    if nazwa == "wspoldzielony_podglad":
        identyfikatory = utworz_pojazd("Cudzy", wspolny=True)
        db.ustaw_role_pojazdu(identyfikatory["auto_id"], db.ROLA_PODGLAD)
        return stan_aplikacji(identyfikatory["auto_id"], "Cudzy"), identyfikatory

    if nazwa == "kosz_pelny":
        identyfikatory = utworz_pojazd("Do kosza")
        db.usun_auto_do_kosza(identyfikatory["auto_id"])
        return stan_aplikacji(), None

    raise AssertionError(f"nieznany scenariusz {nazwa}")


def dosyp_dane(auto_id, dni_wstecz=200):
    """Dokłada OBJĘTOŚĆ i RÓŻNORODNOŚĆ do pojazdu z utworz_pojazd().

    Ma znaczenie przy audytach interfejsu: pasek filtrów pokazuje się dopiero
    wtedy, gdy jest z czego wybierać (kilka stacji, kilka kategorii, kilka
    tagów), a lista rysuje karty dopiero wtedy, gdy ma wpisy. Na pojedynczym
    wpisie połowa chipów w ogóle nie powstaje i audyt nie ma czego sprawdzić."""
    from datetime import date, timedelta

    dzis = date.today()

    def data(dni):
        return (dzis - timedelta(days=dni)).strftime("%Y-%m-%d")

    stacje = ["Orlen", "BP", "Shell", "Circle K"]
    kategorie = [db.KATEGORIA_INNE_DOMYSLNA, db.KATEGORIA_INNE_DROGOWE, "Myjnia i kosmetyka", "Parking i garaż"]
    tagi = ["Trasa", "Miasto", "Urlop"]
    priorytety = db.PRIORYTETY_DO_ZROBIENIA

    with db.polacz_baze() as conn:
        c = conn.cursor()

        for i, nazwa_tagu in enumerate(tagi[1:], start=1):
            c.execute("INSERT INTO tagi (auto_id, nazwa, kolor) VALUES (?,?,?)",
                      (auto_id, nazwa_tagu, ["#2196F3", "#4CAF50"][i - 1]))

        przebieg = 101000
        for i in range(10):
            przebieg += 480 + i * 7
            c.execute(
                "INSERT INTO tankowania (auto_id, data, przebieg, dystans, litry, kwota, do_pelna, stacja, tagi, "
                "rodzaj_energii, notatka) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (auto_id, data(dni_wstecz - i * 18), przebieg, 480 + i * 7, 30.0 + i, 190.0 + i * 4,
                 1 if i % 4 else 0, stacje[i % len(stacje)], tagi[i % len(tagi)],
                 db.ENERGIA_PALIWO, "Notatka przy tankowaniu" if i % 3 == 0 else None),
            )

        for i in range(8):
            c.execute(
                "INSERT INTO inne_koszty (auto_id, data, kategoria, nazwa, kwota, tagi) VALUES (?,?,?,?,?,?)",
                (auto_id, data(dni_wstecz - i * 22), kategorie[i % len(kategorie)],
                 f"Wydatek {i + 1}", 60.0 + i * 15, tagi[i % len(tagi)]),
            )

        c.execute("INSERT INTO warsztaty (auto_id, nazwa, telefon) VALUES (?,?,?)",
                  (auto_id, "Serwis ASO", "222333444"))

        zadania = []
        for nazwa_zadania, interwal in (("Filtr powietrza", 30000), ("Klocki hamulcowe", 60000), ("Wymiana opon / Kół", 0)):
            c.execute("INSERT INTO zadania (auto_id, nazwa, interwal_km, dotyczy_opon) VALUES (?,?,?,?)",
                      (auto_id, nazwa_zadania, interwal, 1 if "opon" in nazwa_zadania.lower() else 0))
            zadania.append(c.lastrowid)

        for i in range(4):
            c.execute("INSERT INTO wizyty (auto_id, data, przebieg, wykonawca, koszt_calkowity) VALUES (?,?,?,?,?)",
                      (auto_id, data(dni_wstecz - i * 40), 100000 + i * 2000,
                       ["Warsztat u Janka", "Serwis ASO"][i % 2], 300.0 + i * 90))
            wizyta = c.lastrowid
            c.execute(
                "INSERT INTO historia (zadanie_id, wizyta_id, data, przebieg, kategoria, cena, wykonawca) "
                "VALUES (?,?,?,?,?,?,?)",
                (zadania[i % len(zadania)], wizyta, data(dni_wstecz - i * 40), 100000 + i * 2000,
                 "Serwis", 150.0 + i * 40, ["Warsztat u Janka", "Serwis ASO"][i % 2]),
            )

        for i in range(6):
            c.execute("INSERT INTO odczyty_przebiegu (auto_id, data, przebieg, zrodlo) VALUES (?,?,?,?)",
                      (auto_id, data(dni_wstecz - i * 25), 100200 + i * 900,
                       list(db.ZRODLA_ODCZYTU)[i % len(db.ZRODLA_ODCZYTU)]))

        for i in range(5):
            c.execute(
                "INSERT INTO do_zrobienia (auto_id, tytul, opis, priorytet, szacowany_koszt, termin, wykonane, "
                "data_utworzenia) VALUES (?,?,?,?,?,?,?,?)",
                (auto_id, f"Zadanie {i + 1}", "Opis zadania", priorytety[i % len(priorytety)],
                 100.0 * (i + 1), data(-30 + i * 5), 1 if i % 3 == 0 else 0, data(dni_wstecz)),
            )

        for i, strefa in enumerate(db.STREFY_KAROSERII[:4]):
            c.execute("INSERT INTO zdjecia_karoserii (auto_id, data, strefa, zalacznik, opis, przebieg) "
                      "VALUES (?,?,?,?,?,?)",
                      (auto_id, data(dni_wstecz - i * 30), strefa,
                       os.path.join(db.FOLDER_ZALACZNIKI, f"brak_{i}.jpg"), f"Zdjęcie {i + 1}", 100000 + i * 500))

        for i, kategoria in enumerate(db.KATEGORIE_MAGAZYNU[:4]):
            c.execute("INSERT INTO magazyn_czesci (auto_id, nazwa, kategoria, ilosc, jednostka, cena) "
                      "VALUES (?,?,?,?,?,?)",
                      (auto_id, f"Część {i + 1}", kategoria, 1.0 + i, "szt", 25.0 * (i + 1)))

        c.execute("INSERT INTO zestawy_opon (auto_id, sezon, rozmiar, ilosc, zamontowane, os_montazu) "
                  "VALUES (?,?,?,?,?,?)",
                  (auto_id, "Letnie", "205/55 R16", 4, 0, "Wszystkie"))
