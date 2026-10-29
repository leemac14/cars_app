"""Narzędzia wspólne dla testów: zrzuty bazy, budowanie pojazdu z danymi.

Nic tu nie sprawdza — same asercje siedzą w plikach test_*.py. Tu jest tylko to,
co musi wyglądać tak samo w kilku testach naraz.
"""

import hashlib
import os
import sqlite3
from datetime import date, timedelta

import db
from date import na_iso


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
                # Sklejenie ze STORAGE_PATH BEZ szukania po nazwie: odcisk ma
                # zaświadczyć, że wpis trafia w plik dokładnie tam, gdzie mówi.
                plik = db.pelna_sciezka_zalacznika(sciezka)
                odciski[sciezka] = suma_pliku(plik) if os.path.exists(plik) else None
    return odciski


def pliki_wpisu(tabela, rekord_id):
    """[(sciezka, typ, opis)] plików wpisu w kolejności z formularza (tabela `zalaczniki`)."""
    with db.polacz_baze() as conn:
        return conn.execute("SELECT sciezka, typ, opis FROM zalaczniki WHERE tabela=? AND rekord_id=? "
                            "ORDER BY kolejnosc, id", (tabela, rekord_id)).fetchall()


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


def jpeg(kiedy=None, kolor=(200, 180, 160)):
    """Bajty małego JPEG-a (jak z aparatu), opcjonalnie z datą zdjęcia w EXIF."""
    import io

    from PIL import Image

    obraz = Image.new("RGB", (40, 30), kolor)
    exif = obraz.getexif()
    if kiedy:
        exif.get_ifd(0x8769)[0x9003] = kiedy.strftime("%Y:%m:%d %H:%M:%S")
    bufor = io.BytesIO()
    obraz.save(bufor, "JPEG", exif=exif)
    return bufor.getvalue()


def dzien(dni, od=None):
    """DD.MM.RRRR sprzed `dni` dni od dziś albo od `od` (ujemne — w przyszłości)."""
    return ((od or date.today()) - timedelta(days=dni)).strftime("%d.%m.%Y")


def wstaw(tabela, /, **pola):
    """Wiersz wprost SQL-em (tabela z datą dostaje `data_iso`); zwraca id."""
    if "data" in pola and tabela in db.TABELE_Z_DATA_ISO:
        pola["data_iso"] = na_iso(pola["data"])
    with db.polacz_baze() as conn:
        return conn.execute(f"INSERT INTO {tabela} ({', '.join(pola)}) VALUES ({', '.join('?' * len(pola))})",
                            list(pola.values())).lastrowid


def utworz_pojazd(nazwa="Testowy", z_zalacznikami=True, wspolny=False, sciezki_wzgledne=True):
    """Pojazd z wpisem w KAŻDEJ tabeli potomnej kosza plus załączniki na dysku.

    Ścieżki idą do bazy tak, jak zapisuje je aplikacja: względne
    ('zalaczniki/<nazwa>'). `sciezki_wzgledne=False` daje dawny zapis
    bezwzględny (Android sprzed zmiany) — baza czyta oba formaty.

    Zwraca słownik z `auto_id` i identyfikatorami wpisów, których potrzebują
    testy przemapowania kluczy obcych. Wstawiamy SQL-em, a nie przez formularze,
    bo testowany jest kosz i schemat, nie warstwa interfejsu."""
    folder = db.FOLDER_ZALACZNIKI
    zid = {}

    def wpis(sciezka):
        return db.wzgledna_sciezka_zalacznika(sciezka) if sciezki_wzgledne else sciezka

    def plik(nazwa_pliku, tresc):
        return wpis(_plik_zalacznika(folder, nazwa_pliku, tresc))

    with db.polacz_baze() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        zdjecie = plik(f"{nazwa}_glowne.jpg", b"GLOWNE-" + nazwa.encode()) if z_zalacznikami else None
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

        c.execute("INSERT INTO wizyty (auto_id, data, przebieg, wykonawca, koszt_calkowity, koszt_robocizny, "
                  "gwarancja_data, gwarancja_przebieg, rodzaj, zdalne_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (auto, "2026-01-10", 100000, "Warsztat u Janka", 480.0, 200.0, "10.01.2028", 130000,
                   db.SERWIS_PLANOWE, "wiz-1"))
        zid["wizyta"] = c.lastrowid

        c.execute("INSERT INTO magazyn_czesci (auto_id, nazwa, kategoria, ilosc, jednostka, cena, cena_jednostkowa, "
                  "sklep, link, zdalne_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (auto, "Filtr oleju", "Filtry", 2.0, "szt", 39.0, 19.5,
                   "Inter Cars", "https://example.com/filtr-oleju", "mag-1"))
        zid["magazyn"] = c.lastrowid

        # Wcześniejszy zakup tej samej części — historia cen ma z czym porównać
        # bieżącą cenę pozycji (19,50 zł teraz, 15,00 zł rok wcześniej).
        c.execute("INSERT INTO ceny_czesci (auto_id, nazwa, data, data_iso, cena_jednostkowa, jednostka, ilosc, sklep, zdalne_id) "
                  "VALUES (?,?,?,?,?,?,?,?,?)",
                  (auto, "Filtr oleju", "12.01.2025", "2025-01-12", 15.0, "szt", 2.0, "Allegro", "cena-1"))
        zid["cena_czesci"] = c.lastrowid

        c.execute("INSERT INTO tagi (auto_id, nazwa, kolor, zdalne_id) VALUES (?,?,?,?)", (auto, "Trasa", "#FF0000", "tag-1"))
        zid["tag"] = c.lastrowid

        c.execute("INSERT INTO tankowania (auto_id, data, przebieg, dystans, litry, kwota, do_pelna, stacja, rodzaj_energii, notatka, zdalne_id) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (auto, "2026-02-01", 100500, 500.0, 32.5, 210.0, 1, "Orlen", db.ENERGIA_PALIWO, "Pełny bak przed trasą",
                   "tank-1"))
        zid["tankowanie"] = c.lastrowid

        c.execute("INSERT INTO inne_koszty (auto_id, data, kategoria, nazwa, kwota, zdalne_id) VALUES (?,?,?,?,?,?)",
                  (auto, "2026-02-03", db.KATEGORIA_INNE_DROGOWE, "Winieta", 120.0, "inne-1"))
        zid["inny_koszt"] = c.lastrowid

        c.execute("INSERT INTO zestawy_opon (auto_id, sezon, rozmiar, ilosc, zamontowane, os_montazu, zdalne_id) VALUES (?,?,?,?,?,?,?)",
                  (auto, "Zimowe", "205/55 R16", 4, 1, "Wszystkie", "opony-1"))
        zid["opony"] = c.lastrowid
        # Pomiar bieżnika każdego koła (wersja 58) — kosz i plik pojazdu przemapowują komplet.
        c.execute("INSERT INTO pomiary_bieznika (auto_id, zestaw_id, data, przebieg, lp, pp, lt, pt, uwagi, "
                  "dodane_przez, zdalne_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (auto, zid["opony"], "02.02.2026", 100600, 6.8, 6.6, 7.1, 7.0, "Przed trasą", "Kamil", "pomiar-1"))
        zid["pomiar"] = c.lastrowid

        c.execute("INSERT INTO zdjecia_karoserii (auto_id, data, strefa, zalacznik, opis) VALUES (?,?,?,?,?)",
                  (auto, "2026-01-05", "Przód",
                   plik(f"{nazwa}_karoseria.jpg", b"KAROSERIA") if z_zalacznikami else wpis(os.path.join(folder, "brak.jpg")),
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

        c.execute("INSERT INTO trasy_szablony (auto_id, nazwa, dystans, powrot, osoby, oplaty, skad, dokad, cel, sluzbowy, "
                  "zdalne_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (auto, "Do teściów", 180.0, 1, 2, 45.0, "Dom", "Teściowie", "Wizyta rodzinna", 0, "trasa-1"))
        zid["trasa"] = c.lastrowid

        c.execute("INSERT INTO szablony_wpisow (auto_id, nazwa, rodzaj, dane, uzycia, zdalne_id) VALUES (?,?,?,?,?,?)",
                  (auto, "Myjnia", "koszt", '{"kategoria": "Myjnia i kosmetyka", "kwota": 40.0, "nazwa": "Myjnia", '
                   '"notatka": null, "tagi": "Trasa"}', 2, "szablon-1"))
        zid["szablon"] = c.lastrowid

        # Przejazd z ewidencji — służbowy, ze stanem licznika po przejeździe
        # (kolejne źródło historii licznika) i notatką z podpisem.
        c.execute("INSERT INTO przejazdy (auto_id, data, skad, dokad, cel, km, powrot, sluzbowy, kierowca, licznik, "
                  "notatka, notatka_autor, notatka_data, dodane_przez, zdalne_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (auto, "05.02.2026", "Dom", "Biuro klienta", "Spotkanie handlowe", 84.0, 1, 1, "Kamil", 100700,
                   "Parking 12 zł", "Kamil", "05.02.2026 18:00", "Kamil", "przejazd-1"))
        zid["przejazd"] = c.lastrowid

        # Dolewka oleju z pozycją magazynu (kosz i plik pojazdu przemapowują odwołanie) — bez kosztu, bo
        # Inny koszt jest tu jeden (test_kosz liczy); licznik to kolejne źródło historii licznika.
        c.execute("INSERT INTO dolewki (auto_id, data, przebieg, plyn, ilosc, produkt, magazyn_id, notatka, "
                  "notatka_autor, notatka_data, dodane_przez, zdalne_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (auto, "06.02.2026", 100800, db.PLYN_OLEJ, 0.5, "Castrol 5W-30", zid["magazyn"],
                   "Przed trasą", "Kamil", "06.02.2026 08:00", "Kamil", "dolewka-1"))
        zid["dolewka"] = c.lastrowid

        c.execute("INSERT INTO checklisty (auto_id, nazwa, opis, zdalne_id) VALUES (?,?,?,?)",
                  (auto, "Przed dłuższą trasą", "Obchód auta", "check-1"))
        zid["checklista"] = c.lastrowid

        c.execute("INSERT INTO budzety (auto_id, kategoria, okres, kwota, zdalne_id) VALUES (?,?,?,?,?)",
                  (auto, "Paliwo", "miesiac", 600.0, "budzet-1"))
        zid["budzet"] = c.lastrowid

        c.execute("INSERT INTO do_zrobienia (auto_id, tytul, opis, priorytet, zadanie_id, wykonane, data_utworzenia, "
                  "termin_przebieg, przebieg_startowy, zdalne_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (auto, "Umówić przegląd", "Zadzwonić do Janka", "Wysoki", zid["zadanie"], 0, "2026-02-01",
                   115000, 100000, "todo-1"))
        zid["do_zrobienia"] = c.lastrowid
        c.execute("INSERT INTO do_zrobienia_zdarzenia (pozycja_id, rodzaj, dane, moment, dodane_przez, zdalne_id) "
                  "VALUES (?,?,?,?,?,?)", (zid["do_zrobienia"], "dodano", "{}", "2026-02-01 10:00:00", "Kamil", "todo-zd-1"))
        zid["zdarzenie_do_zrobienia"] = c.lastrowid

        # Z gwarancją naprawy (dwa lata albo 30 000 km) i rodzajem, tymi samymi co
        # wizyty — kosz i synchronizacja mają je przenieść jak każdą inną kolumnę.
        c.execute("INSERT INTO historia (zadanie_id, wizyta_id, data, przebieg, kategoria, cena, wykonawca, notatka, "
                  "gwarancja_data, gwarancja_przebieg, rodzaj, zdalne_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (zid["zadanie"], zid["wizyta"], "2026-01-10", 100000, "Serwis", 480.0, "Warsztat u Janka", "Olej Castrol",
                   "10.01.2028", 130000, db.SERWIS_PLANOWE, "hist-1"))
        zid["historia"] = c.lastrowid
        # Odwołania pozycji do wpisu, kosztu i wizyty — kosz i plik pojazdu przemapowują je jak resztę.
        c.execute("UPDATE do_zrobienia SET historia_id=?, koszt_id=?, wizyta_id=? WHERE id=?",
                  (zid["historia"], zid["inny_koszt"], zid["wizyta"], zid["do_zrobienia"]))
        # Okres montażu kompletu z odwołaniem do wpisu i kosztu zmiany (wersja 58) — jak wyżej.
        c.execute("INSERT INTO montaze_opon (auto_id, zestaw_id, os_montazu, data, przebieg, historia_id, koszt_id, "
                  "dodane_przez, zdalne_id) VALUES (?,?,?,?,?,?,?,?,?)",
                  (auto, zid["opony"], "Wszystkie", "10.01.2026", 100000, zid["historia"], zid["inny_koszt"],
                   "Kamil", "montaz-1"))
        zid["montaz"] = c.lastrowid

        c.execute("INSERT INTO wizyta_czesci_magazynu (wizyta_id, magazyn_id, ilosc_uzyta, koszt, zdalne_id) VALUES (?,?,?,?,?)",
                  (zid["wizyta"], zid["magazyn"], 1.0, 19.5, "wcm-1"))
        zid["wizyta_czesc"] = c.lastrowid

        c.execute("INSERT INTO historia_czesci_magazynu (historia_id, magazyn_id, ilosc_uzyta, koszt, zdalne_id) VALUES (?,?,?,?,?)",
                  (zid["historia"], zid["magazyn"], 1.0, 19.5, "hcm-1"))
        zid["historia_czesc"] = c.lastrowid

        c.execute("INSERT INTO checklisty_pozycje (checklista_id, tresc, kolejnosc, odhaczone, zdalne_id) VALUES (?,?,?,?,?)",
                  (zid["checklista"], "Ciśnienie w oponach", 0, 1, "poz-1"))
        zid["pozycja_checklisty"] = c.lastrowid

        c.execute("INSERT INTO rozliczenia (auto_id, data, uczestnicy, salda, przelewy, notatka, klucz, "
                  "dodane_przez, data_utworzenia, zdalne_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (auto, "01.01.2026", '["Kamil", "Ola"]', '{"Kamil": 5000, "Ola": -5000}',
                   '[{"od": "Ola", "do": "Kamil", "kwota": 5000}]', "Przelew", f"rozl-{nazwa}",
                   "Kamil", "2026-01-01 20:00:00", "rozl-1"))
        zid["rozliczenie"] = c.lastrowid

        # Szkic z kolejki „do wpisania” — lokalny (bez zdalne_id), ze zdjęciem
        # paragonu, licznikiem i opisem dopisanymi po migawce. Z DZISIAJ: szkic
        # sprzed trzech dni to już przypomnienie w dzwonku i kaflu „Termin”,
        # a scenariusze mają być spokojne tam, gdzie dane są spokojne.
        c.execute("INSERT INTO szkice_wpisow (auto_id, data, godzina, zalacznik, rodzaj, przebieg, opis) "
                  "VALUES (?,?,?,?,?,?,?)",
                  (auto, date.today().strftime("%d.%m.%Y"), "17:45",
                   plik(f"{nazwa}_szkic.jpg", b"SZKIC") if z_zalacznikami else None,
                   "tankowanie", 101400, "Orlen przy A2"))
        zid["szkic"] = c.lastrowid

        # Dokument skarbca bez daty ważności — scenariusze mają być spokojne w dzwonku.
        c.execute("INSERT INTO dokumenty_pojazdu (auto_id, rodzaj, numer, notatki, liczba_plikow, dodane_przez, zdalne_id) "
                  "VALUES (?,?,?,?,?,?,?)",
                  (auto, "dowod", "DR/BAU 1234567", "Oryginał w schowku", 1 if z_zalacznikami else 0, "Kamil", "dok-1"))
        zid["dokument"] = c.lastrowid

        # Pliki wpisów (N-05): dwa przy wizycie — kolejność i rodzaj mają przetrwać kosz.
        if z_zalacznikami:
            for tabela, rekord_id, nazwa_pliku, tresc, typ, kolejnosc in (
                ("wizyty", zid["wizyta"], f"{nazwa}_wizyta.jpg", b"WIZYTA", "paragon", 0),
                ("wizyty", zid["wizyta"], f"{nazwa}_faktura.pdf", b"FAKTURA", "faktura", 1),
                ("magazyn_czesci", zid["magazyn"], f"{nazwa}_czesc.jpg", b"CZESC", "zdjecie_czesci", 0),
                ("tankowania", zid["tankowanie"], f"{nazwa}_paragon.jpg", b"PARAGON", "paragon", 0),
                ("historia", zid["historia"], f"{nazwa}_wpis.jpg", b"WPIS", "paragon", 0),
                ("dokumenty_pojazdu", zid["dokument"], f"{nazwa}_dowod.jpg", b"DOWOD", db.TYP_PLIKU_DOKUMENTU, 0),
            ):
                c.execute("INSERT INTO zalaczniki (auto_id, tabela, rekord_id, sciezka, typ, opis, kolejnosc) "
                          "VALUES (?,?,?,?,?,?,?)",
                          (auto, tabela, rekord_id, plik(nazwa_pliku, tresc), typ, "Strona 1" if kolejnosc else None,
                           kolejnosc))

        # Tabela spoza kosza — świadomie, żeby testy widziały różnicę.
        c.execute("INSERT INTO wyciszone_powiadomienia (auto_id, klucz, do_dnia, tytul) VALUES (?,?,?,?)",
                  (auto, "oc", "2026-12-31", "Polisa OC"))

        # Aplikacja dopisuje `data_iso` przy każdym zapisie daty — wpisy
        # wstawione tu SQL-em dostają ją tak, jak dostałyby w aplikacji.
        db.przelicz_daty_iso(conn)
        # Stan magazynu jak w aplikacji: stan wyjściowy = stan na półce + zużycie (db/stan_magazynu.py).
        db.zapewnij_stan_wyjsciowy(conn, [zid["magazyn"]])

    # Ustawienie przywiązane do pojazdu — musi pojechać do kosza i wrócić.
    db.zapisz_ustawienie(db.ustawienia._klucz_kokpitu(auto), "przebieg,paliwo,terminy")

    return {"auto_id": auto, **zid}


# ============================================================================
#  CHMURA W PAMIĘCI
# ============================================================================

class _Odpowiedz:
    def __init__(self, data=None):
        self.data = data


class ChmuraWPamieci:
    """Supabase na tyle, na ile potrzebuje go `sync.wysylanie._wypchnij_tabele`: rekordy {zdalne_id: dane}."""

    def __init__(self, rekordy=None):
        self.rekordy = dict(rekordy or {})

    def rpc(self, nazwa, parametry):
        chmura = self

        class _Wywolanie:
            def execute(self):
                if nazwa == "aktualizuj_zdalny_rekord":
                    chmura.rekordy[parametry["p_id"]] = parametry["p_dane"]
                    return _Odpowiedz()
                nowe = f"{parametry.get('p_tabela', 'rekord')}-{len(chmura.rekordy) + 1}"
                chmura.rekordy[nowe] = parametry["p_dane"]
                return _Odpowiedz(nowe)
        return _Wywolanie()

    def table(self, nazwa):
        chmura = self

        class _Zapytanie:
            def select(self, *_):
                return self

            def in_(self, _pole, identyfikatory):
                self.identyfikatory = list(identyfikatory)
                return self

            def execute(self):
                return _Odpowiedz([{"id": i, "dane": chmura.rekordy[i]} for i in self.identyfikatory
                                   if i in chmura.rekordy])
        return _Zapytanie()


# ============================================================================
#  HEADLESS FLET
# ============================================================================
# Kontrolki Fleta budują się bez okna i bez pętli zdarzeń, ale `ft.Page` wymaga
# sesji i trzyma ją przez WEAKREF — obiekt sesji musi więc gdzieś żyć, inaczej
# `page.update()` wywala się na „An attempt to fetch destroyed session".
# Dlatego strona i jej sesja wracają razem, w jednym obiekcie.

# Flet 1.0 sprawdza każdą kontrolkę przed wysłaniem (reguły pól, np. `semantics_value >= 0`)
# i wtedy `page.update()` rzuca — strona testowa robi to samo. Błąd, który aplikacja
# połknie po drodze, zostaje w BLEDY_WYSYLKI i oblewa test na końcu (conftest).
BLEDY_WYSYLKI = []
_POLA_KLAS = {}
_PRZESTRZEN_FLETA = {}


def _przestrzen_fleta():
    """Nazwy ze wszystkich modułów Fleta — jego podpowiedzi typów sięgają po nazwy
    importowane tylko pod TYPE_CHECKING (`KeyValue`, `Page`…)."""
    if not _PRZESTRZEN_FLETA:
        import contextlib
        import sys

        import flet as ft

        for nazwa in getattr(ft, "__all__", ()):  # Flet ładuje moduły dopiero przy dostępie
            with contextlib.suppress(ImportError, AttributeError):
                getattr(ft, nazwa)
        for nazwa, modul in list(sys.modules.items()):
            if nazwa == "flet" or nazwa.startswith("flet."):
                _PRZESTRZEN_FLETA.update((k, v) for k, v in vars(modul).items() if not k.startswith("__"))
    return _PRZESTRZEN_FLETA


def _pola_klasy(klasa):
    """(pola do przejścia, pola przyjmujące tylko liczbę) — liczone raz na klasę."""
    if klasa not in _POLA_KLAS:
        import dataclasses
        import types
        import typing

        podpowiedzi = {}
        for baza in klasa.__mro__:  # klasa aplikacji z nieznaną nazwą → podpowiedzi przodka z Fleta
            if dataclasses.is_dataclass(baza):
                try:
                    podpowiedzi = typing.get_type_hints(baza, localns=_przestrzen_fleta())
                    break
                except Exception:
                    continue
        przejscie, liczbowe = [], []
        for pole in dataclasses.fields(klasa):
            if pole.metadata.get("skip", False):
                continue
            przejscie.append(pole.name)
            typ = podpowiedzi.get(pole.name)
            sklad = typing.get_args(typ) if typing.get_origin(typ) in (typing.Union, types.UnionType) else (typ,)
            sklad = [t for t in sklad if t is not type(None)]
            if sklad and all(isinstance(t, type) and issubclass(t, (int, float)) for t in sklad):
                liczbowe.append(pole.name)
        _POLA_KLAS[klasa] = (tuple(przejscie), tuple(liczbowe))
    return _POLA_KLAS[klasa]


def bledy_kontrolek(korzen, sprawdzone=None):
    """Kontrolki poddrzewa, których Flet nie wyśle: złamana reguła pola albo tekst w polu
    liczbowym (przejście jak we Flecie: pola dataclass, listy, słowniki). `sprawdzone`
    (id → kontrolka) pomija już obejrzane."""
    import dataclasses

    from flet.controls.base_control import BaseControl
    from flet.utils.validation import validate

    sprawdzone = {} if sprawdzone is None else sprawdzone
    bledy, kolejka, odwiedzone = [], [korzen], set()
    while kolejka:
        obiekt = kolejka.pop()
        if isinstance(obiekt, (list, tuple)):
            kolejka.extend(obiekt)
            continue
        if isinstance(obiekt, dict):
            kolejka.extend(obiekt.values())
            continue
        if not dataclasses.is_dataclass(obiekt) or isinstance(obiekt, type) or id(obiekt) in odwiedzone:
            continue
        odwiedzone.add(id(obiekt))
        przejscie, liczbowe = _pola_klasy(type(obiekt))
        if isinstance(obiekt, BaseControl) and id(obiekt) not in sprawdzone:
            sprawdzone[id(obiekt)] = obiekt
            try:
                validate(obiekt)
            except (ValueError, TypeError) as blad:
                bledy.append(f"{type(obiekt).__name__}: {blad}")
            bledy.extend(f"{type(obiekt).__name__}.{pole}: tekst {getattr(obiekt, pole)!r} zamiast liczby"
                         for pole in liczbowe if isinstance(getattr(obiekt, pole, None), str))
        kolejka.extend(getattr(obiekt, pole, None) for pole in przejscie)
    return bledy


class _SesjaZastepcza:
    """Minimum, którego oczekuje ft.Page. Wysyłka sprawdza kontrolki jak Flet; każda inna
    metoda jest pustym gestem."""

    def __init__(self):
        self.index = {}
        self.sprawdzone = {}

    def patch_control(self, kontrolka, *_args, **_kwargs):
        bledy = bledy_kontrolek(kontrolka, self.sprawdzone)
        if bledy:
            BLEDY_WYSYLKI.extend(bledy)
            raise ValueError("Flet odrzuciłby wysyłkę:\n" + "\n".join(bledy))

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


def napisy(korzen):
    """Wszystkie napisy z drzewa kontrolek (też etykiety przycisków i przełączników) — do
    sprawdzania okien, których strona testowa nie pokazuje."""
    import flet as ft

    wynik, do_odwiedzenia = [], [korzen]
    while do_odwiedzenia:
        kontrolka = do_odwiedzenia.pop()
        for pole in ("value", "label", "tooltip"):
            wartosc = getattr(kontrolka, pole, None)
            if isinstance(wartosc, str):
                wynik.append(wartosc)
        for pole in ("controls", "content", "title", "subtitle", "leading", "trailing", "actions"):
            dziecko = getattr(kontrolka, pole, None)
            if isinstance(dziecko, str):
                wynik.append(dziecko)
            elif isinstance(dziecko, (list, tuple)):
                do_odwiedzenia.extend(d for d in dziecko if isinstance(d, ft.Control))
            elif isinstance(dziecko, ft.Control):
                do_odwiedzenia.append(dziecko)
    return wynik


def kontrolki(korzen, typ=None):
    """Kontrolki poddrzewa wszerz — wszystkie albo danego typu (też tła gestów i paski)."""
    import flet as ft

    wynik, kolejka = [], [korzen]
    while kolejka:
        kontrolka = kolejka.pop(0)
        if typ is None or isinstance(kontrolka, typ):
            wynik.append(kontrolka)
        for pole in ("controls", "content", "title", "subtitle", "leading", "trailing", "actions",
                     "appbar", "background", "secondary_background"):
            dziecko = getattr(kontrolka, pole, None)
            if isinstance(dziecko, (list, tuple)):
                kolejka.extend(d for d in dziecko if isinstance(d, ft.Control))
            elif isinstance(dziecko, ft.Control):
                kolejka.append(dziecko)
    return wynik


def zbieraj_ekran(monkeypatch):
    """Okna, komunikaty i przejścia zbierane zamiast pokazywane (strona testowa ich nie pokaże):
    SimpleNamespace(okna, komunikaty, trasy); wysyłka w tle wyłączona."""
    import sys
    from types import SimpleNamespace

    import flet as ft

    zebrane = SimpleNamespace(okna=[], komunikaty=[], trasy=[])
    monkeypatch.setattr(ft.Page, "show_dialog", lambda self, okno: zebrane.okna.append(okno))
    monkeypatch.setattr(ft.Page, "pop_dialog", lambda self: None)
    podmiany = {"pokaz_komunikat": lambda page, tekst, *a, **k: zebrane.komunikaty.append(tekst),
                "pokaz_komunikat_cofnij": lambda page, tekst, *a, **k: zebrane.komunikaty.append(tekst),
                "przejdz": lambda page, trasa: zebrane.trasy.append(trasa),
                "wypchnij_w_tle": lambda *a, **k: None}
    for nazwa_modulu, modul in list(sys.modules.items()):
        if modul is not None and nazwa_modulu.split(".")[0] in ("utils", "views"):
            for nazwa, wartosc in podmiany.items():
                if hasattr(modul, nazwa):
                    monkeypatch.setattr(modul, nazwa, wartosc)
    return zebrane


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
    # Formularz umowy raty na zwykłym wydatku cyklicznym — przestawienie na raty.
    "wydatek_id": "cykliczny",
    "przejazd_id": "przejazd",
    "dokument_id": "dokument",
    "dolewka_id": "dolewka",
    "pomiar_id": "pomiar",
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
    widok = klasa(*wartosci)
    bledy = bledy_kontrolek(widok, getattr(getattr(strona, "sesja", None), "sprawdzone", None))
    assert not bledy, f"{klasa.__name__}: Flet nie wyśle tego ekranu:\n" + "\n".join(bledy)
    return widok


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

        # Co druga wizyta z robocizną: lista, filtr „Podział” i karta Analizy
        # mają wtedy obie strony — naprawy z podziałem i bez.
        for i in range(4):
            c.execute("INSERT INTO wizyty (auto_id, data, przebieg, wykonawca, koszt_calkowity, koszt_robocizny) "
                      "VALUES (?,?,?,?,?,?)",
                      (auto_id, data(dni_wstecz - i * 40), 100000 + i * 2000,
                       ["Warsztat u Janka", "Serwis ASO"][i % 2], 300.0 + i * 90,
                       120.0 + i * 20 if i % 2 == 0 else None))
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

        # Wykonane (co trzecie) z dniem, licznikiem, kosztem i notatką; jedno aktywne z terminem przebiegowym.
        for i in range(5):
            wykonane = i % 3 == 0
            c.execute(
                "INSERT INTO do_zrobienia (auto_id, tytul, opis, priorytet, szacowany_koszt, termin, wykonane, "
                "data_utworzenia, data_wykonania, przebieg_wykonania, koszt_wykonania, notatka_wykonania, "
                "wykonane_przez, termin_przebieg, przebieg_startowy) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (auto_id, f"Zadanie {i + 1}", "Opis zadania", priorytety[i % len(priorytety)],
                 100.0 * (i + 1), data(-30 + i * 5), 1 if wykonane else 0, data(dni_wstecz),
                 data(5 + i) if wykonane else None, 101000 + i * 300 if wykonane else None,
                 90.0 * (i + 1) if wykonane else None, "Zrobione w garażu u Janka" if i == 3 else None,
                 "Kamil" if wykonane else None, 104000 if i == 1 else None, 101000 if i == 1 else None),
            )

        for i, strefa in enumerate(db.STREFY_KAROSERII[:4]):
            c.execute("INSERT INTO zdjecia_karoserii (auto_id, data, strefa, zalacznik, opis, przebieg) "
                      "VALUES (?,?,?,?,?,?)",
                      (auto_id, data(dni_wstecz - i * 30), strefa,
                       os.path.join(db.FOLDER_ZALACZNIKI, f"brak_{i}.jpg"), f"Zdjęcie {i + 1}", 100000 + i * 500))

        # Połowa pozycji z ceną za jednostkę, połowa bez — karta magazynu ma
        # dwie gałęzie (cena i wartość albo sam koszt zakupu) i obie mają się rysować.
        for i, kategoria in enumerate(db.KATEGORIE_MAGAZYNU[:4]):
            c.execute("INSERT INTO magazyn_czesci (auto_id, nazwa, kategoria, ilosc, jednostka, cena, cena_jednostkowa) "
                      "VALUES (?,?,?,?,?,?,?)",
                      (auto_id, f"Część {i + 1}", kategoria, 1.0 + i, "szt", 25.0 * (i + 1),
                       25.0 * (i + 1) / (1.0 + i) if i % 2 == 0 else None))

        c.execute("INSERT INTO zestawy_opon (auto_id, sezon, rozmiar, ilosc, zamontowane, os_montazu) "
                  "VALUES (?,?,?,?,?,?)",
                  (auto_id, "Letnie", "205/55 R16", 4, 0, "Wszystkie"))

        # Leasing z harmonogramem (M-22): ekran „Leasing i kredyt”, kafelek „Do
        # spłaty”, „Ile zostało do…” i Karta pojazdu mają co rysować. Pięć rat
        # zapłaconych, następna za dwa tygodnie — poza progiem przypomnienia,
        # więc dzwonek i kafel „Termin” zostają, jakie były.
        pierwsza = db.dodaj_miesiace(dzis, -5) + timedelta(days=15)
        c.execute("INSERT INTO wydatki_cykliczne (auto_id, nazwa, kwota, okres_dni, nastepna_data, czy_koszt, typ, "
                  "liczba_rat, zaplacone_platnosci, data_pierwszej_raty, kwota_finansowania, oplata_wstepna, "
                  "wykup, rodzaj_rat) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (auto_id, "Leasing", 1900.0, 30, db.dodaj_miesiace(pierwsza, 5).strftime("%d.%m.%Y"), 1,
                   db.TYP_CYKLICZNY_LEASING, 36, 5, pierwsza.strftime("%d.%m.%Y"), 110000.0, 11000.0, 40000.0,
                   db.RATY_ROWNE))

        db.przelicz_daty_iso(conn)
