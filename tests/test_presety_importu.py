"""Presety importu z innych aplikacji: Fuelio, Drivvo, aCar, Simply Auto.

Próbki odtwarzają prawdziwe pliki: Fuelio — kopię CSV (sekcje, nagłówki,
kody paliw i kategorii) z publicznych konwerterów kopii Fuelio; Drivvo —
pozycje kolumn, na których opiera się konwerter FuelioImport; aCar —
nagłówek „Fill-Up Records” z eksportu opisanego na forum Fuelly; Simply
Auto — kolumny Fuel_Log.csv z oficjalnego „Import Guide”. Szczegóły i źródła:
claude/presety-importu.md.

Sprawdzamy trzy piętra: rozpoznanie aplikacji i rozbiór pliku na części
(`db.rozbierz_plik_importu`), walidację i zapis tym samym mechanizmem co
przy ręcznym dopasowaniu (`TYPY_IMPORTU`), i ekran, który importuje
wszystko naraz.
"""

import zipfile

import pytest

import db
import pomoce
import utils


FUELIO = '''"## Vehicle"
"Name","Description","DistUnit","FuelUnit","ConsumptionUnit","ImportCSVDateFormat","VIN","Insurance","Plate","Make","Model","Year","TankCount","Tank1Type","Tank2Type","Active","Tank1Capacity","Tank2Capacity","FuelUnitTank2","FuelConsumptionTank2"
"Auris z Fuelio","","0","0","0","yyyy-MM-dd","","","","toyota","auris","2018","1","100","0","1","50.0","0.0","0","0"
"## Log"
"Data","Odo (km)","Fuel (litres)","Full","Price (optional)","l/100km (optional)","latitude (optional)","longitude (optional)","City (optional)","Notes (optional)","Missed","TankNumber","FuelType","VolumePrice","StationID (optional)","ExcludeDistance","UniqueId","TankCalc"
"2018-10-07 16:01","12424","33.04","1","172.92","0.0","50.0436","14.4406","Orlen Kraków","","0","1","110","5.23","329285","0","105","0.0"
"2018-10-21 08:15","12950","40.10","0","209.80","0.0","0.0","0.0","BP Tarnów","Bak do połowy","0","1","110","5.23","0","0","106","0.0"
"2018-11-04","13480","38.50","1","","0.0","0.0","0.0","","","0","1","110","5.40","0","0","107","0.0"
"## CostCategories"
"CostTypeID","Name","priority","color"
"1","Service","0",""
"2","Maintenance","0",""
"5","Parking","0",""
"6","Wash","0",""
"7","Tolls","0",""
"31","Insurance","0",""
"33","Other","0","#424242"
"34","Winterreifen","0","#424242"
"## Costs"
"CostTitle","Date","Odo","CostTypeID","Notes","Cost","flag","idR","read","RemindOdo","RemindDate","isTemplate","RepeatOdo","RepeatMonths","isIncome","UniqueId"
"Wymiana oleju","2018-11-02","13300","1","Castrol 5W30","350.0","0","0","0","0","","0","0","0","0","51"
"Parking Praha","2018-11-05","0","5","","12.5","0","0","0","0","","0","0","0","0","52"
"A2 Konin","2018-11-06","0","7","","45.0","0","0","0","0","","0","0","0","0","53"
"OC","2018-12-01","0","31","PZU","1200.0","0","0","0","0","","0","0","0","0","54"
"Opony zimowe","2018-11-20","13800","34","","1600.0","0","0","0","0","","0","0","0","0","55"
"Wymiana klocków","2019-01-15","14500","33","","420.0","0","0","0","0","","0","0","0","0","56"
"Przegląd","2019-02-08","0","2","","0.0","0","0","0","0","2019-07-19","0","0","0","0","57"
"Sprzedaż felg","2019-03-01","0","33","","300.0","0","0","0","0","","0","0","0","1","58"
"Myjnia co miesiąc","2019-03-01","0","6","","30.0","0","0","0","0","","1","0","1","0","59"
"## FavStations"
"NameBrand","Latitude","Longitude","StationID","Description","CountryCode"
"Orlen","50.0","19.9","208772","Kraków","POL"
"## Category"
"IdCategory","Name"
"1","Private"
'''

# Auto w milach i galonach (USA), daty zapisane jak w nagłówku pojazdu,
# hybryda plug-in: drugi zbiornik to prąd (typ 600, kod ładowania 601).
FUELIO_USA_PHEV = '''"## Vehicle"
"Name","Description","DistUnit","FuelUnit","ConsumptionUnit","ImportCSVDateFormat","VIN","Insurance","Plate","Make","Model","Year","TankCount","Tank1Type","Tank2Type","Active","Tank1Capacity","Tank2Capacity","FuelUnitTank2","FuelConsumptionTank2"
"Prius Prime","","1","1","1","MM/dd/yyyy","","","","toyota","prius","2020","2","100","600","1","11.4","8.8","0","0"
"## Log"
"Data","Odo (mi)","Fuel (litres)","Full","Price (optional)","mpg (optional)","latitude (optional)","longitude (optional)","City (optional)","Notes (optional)","Missed","TankNumber","FuelType","VolumePrice","StationID (optional)","ExcludeDistance","UniqueId","TankCalc"
"03/10/2024","10000.0","10.0","1","35.90","0.0","0.0","0.0","Shell","","0","1","110","3.59","0","0","1","0.0"
"03/12/2024","10030.0","8.2","1","2.46","0.0","0.0","0.0","Home","","0","2","601","0.30","0","0","2","0.0"
'''

DRIVVO = '''##Vehicle
Name,Model,Plate,Brand,Year,Notes
Golf,VII,KR12345,VW,2016,
##Refuelling
Odometer,Date,Fuel,Price/L,Total cost,Liters,Full tank?,Missed previous refuelling?,Gas station,Payment method,Reason,Driver,Distance,Consumption,Cost per km,Latitude,Longitude,Tags,Notes
45000,21/05/2019 14:30,Gasoline,5.19,207.60,40.00,Yes,No,Orlen,Card,,,,,,,,,Pełny bak
45600,02/06/2019 08:10,Gasoline,5.29,158.70,30.00,No,No,BP,Card,,,,,,,,,
##Expense
Odometer,Date,Total cost,Expense type,Place,Payment method,Notes
45100,25/05/2019,15.00,Parking,Centrum,Card,Parking pod pracą
45200,28/05/2019,1200.00,Insurance,,Transfer,
##Service
Odometer,Date,Total cost,Service type,Place,Notes
45300,30/05/2019,650.00,Oil change,ASO Kraków,Olej i filtr
##Income
Odometer,Date,Total,Type
45400,01/06/2019,100.00,Refund
'''

ACAR = '''"Vehicles"
"Name","Make","Model"
"Civic","Honda","Civic"
"Jazz","Honda","Jazz"
"Fill-Up Records"
"Vehicle","Date","Time","Odometer Reading","Distance Unit","Volume","Volume Unit","Price per Unit","Total Cost","Payment","Partial Fill-Up?","Previously Missed Fill-Ups?","Fuel Efficiency","Fuel Efficiency Unit","Fuel Type","Has Fuel Additive?","Fuel Additive Name","Fuel Brand","Fueling Station Address","Latitude","Longitude","Driving Mode","City Driving Percentage","Highway Driving Percentage","Average Speed","Tags","Notes"
"Civic","03/14/2019","10:00","12,345","mi","10.500","gal (US)","$3.459","$36.32","Card","No","No","","","Regular","No","","Shell","1 Main St","","","","","","","",""
"Civic","03/28/2019","18:20","12,701","mi","9.800","gal (US)","$3.499","$34.29","Card","Yes","No","","","Regular","No","","","5 Oak Ave","","","","","","","","Half tank"
"Jazz","03/15/2019","09:00","8,000","mi","8.000","gal (US)","$3.459","$27.67","Card","No","No","","","Regular","No","","Shell","","","","","","","","",""
"Service Records"
"Vehicle","Date","Time","Odometer Reading","Distance Unit","Services","Total Cost","Payment","Service Center Name","Service Center Address","Tags","Notes"
"Civic","04/02/2019","12:00","12,900","mi","Oil Change, Oil Filter","$59.99","Card","Jiffy Lube","","",""
"Expense Records"
"Vehicle","Date","Time","Odometer Reading","Distance Unit","Expenses","Total Cost","Payment","Expense Center Name","Tags","Notes"
"Civic","04/05/2019","08:00","12,950","mi","Parking","$12.00","Cash","","",""
"Civic","04/10/2019","08:00","13,000","mi","Car Wash","$8.50","Cash","","",""
"Trip Records"
"Vehicle","Start Date"
"Civic","04/11/2019"
'''

SIMPLY_AUTO = '''Row ID,Vehicle ID,Odometer,Qty,Partial Tank,Missed Fill Up,Total Cost,Distance Traveled,Eff,Octane,Fuel Brand,Filling Station,Notes,Day,Month,Year,Receipt Path,Record Type,Record Desc
1,car1,10000,40,0,0,220.00,0,0,95,Orlen,Orlen Kraków,,5,1,2020,,0,Fuel Record
2,car1,10500,35,1,0,190.50,500,7,95,BP,,Nie do pełna,20,1,2020,,0,Fuel Record
3,car1,10600,0,0,0,480.00,0,0,,,Auto Serwis,Opony,25,1,2020,,1,"Tire Rotation, Oil Change"
4,car1,10700,0,0,0,30.00,0,0,,,,,1,2,2020,,2,Parking
5,car2,5000,30,0,0,160.00,0,0,95,Shell,,,3,2,2020,,0,Fuel Record
6,car1,11000,38,0,0,210.00,400,7,95,Orlen,,,12,12,2020,,0,Fuel Record
'''


def _plik(tmp_path, tresc, nazwa="plik.csv"):
    sciezka = tmp_path / nazwa
    sciezka.write_text(tresc, encoding="utf-8")
    return str(sciezka)


def _wiersze(tmp_path, tresc):
    return db.wczytaj_wiersze_csv(_plik(tmp_path, tresc))


def _auto(nazwa="Z innej aplikacji", paliwo="Benzyna"):
    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO samochody (nazwa, marka, model, typ_paliwa, status) VALUES (?,?,?,?,?)",
                  (nazwa, "Marka", "Model", paliwo, db.STATUS_POJAZDU_AKTYWNY))
        return c.lastrowid


def _czesci(rozbior):
    return {c["typ"]: c for c in rozbior["czesci"]}


def _raport(auto_id, czesc, jednostka="km"):
    return db.TYPY_IMPORTU[czesc["typ"]]["przygotuj"](
        auto_id, czesc["naglowki"], czesc["wiersze"], czesc["mapowanie"],
        jednostka_pliku=jednostka, numery_wierszy=czesc["numery"])


# ------------------------------------------------------------ plik i liczby


def test_plik_z_sekcjami_czyta_separator_z_kolejnych_linii(tmp_path):
    """Pierwsza linia Fuelio to sam znacznik „## Vehicle” — bez przecinka.
    Wcześniej plik czytał się wtedy średnikiem, czyli jako jedna kolumna."""
    wiersze = _wiersze(tmp_path, FUELIO)
    assert wiersze[0] == ["## Vehicle"]
    assert len(wiersze[1]) == 20 and wiersze[1][2] == "DistUnit"


def test_zip_i_konce_linii_z_maca(tmp_path):
    archiwum = tmp_path / "vehicle-1-sync.csv.zip"
    with zipfile.ZipFile(archiwum, "w") as z:
        z.writestr("vehicle-1-sync.csv", FUELIO)
    assert db.wczytaj_wiersze_csv(str(archiwum)) == _wiersze(tmp_path, FUELIO)
    assert db.wczytaj_wiersze_csv(_plik(tmp_path, DRIVVO.replace("\n", "\r"), "mac.csv")) == _wiersze(tmp_path, DRIVVO)


def test_zip_simply_auto_bierze_fuel_log(tmp_path):
    archiwum = tmp_path / "SimplyAuto.zip"
    with zipfile.ZipFile(archiwum, "w") as z:
        z.writestr("Vehicles.csv", "Row ID,Make,Model,Vehicle ID\n1,Honda,Jazz,car1\n")
        z.writestr("Fuel_Log.csv", SIMPLY_AUTO)
    assert db.wczytaj_wiersze_csv(str(archiwum))[0][1] == "Vehicle ID"


@pytest.mark.parametrize("wartosci, oczekiwana", [
    (["05/13/2024", "01/02/2024"], "mdy"),
    (["13/05/2024", "01/02/2024"], "dmy"),
    (["01/02/2024", "03/04/2024"], "dmy"),      # nie wiadomo — domyślna
    (["2024-03-10", "2024-12-01"], "dmy"),      # ISO nie jest dwuznaczne
    (["13/05/2024", "05/13/2024"], "dmy"),      # sprzeczne — domyślna
])
def test_kolejnosc_dat_z_calej_kolumny(wartosci, oczekiwana):
    assert db.rozpoznaj_kolejnosc_dat(wartosci) == oczekiwana


@pytest.mark.parametrize("wartosci, oczekiwany", [
    (["12,345", "$45.67"], "."),                # aCar z USA: przecinek to tysiące
    (["12.345", "45,67"], ","),
    (["1.234.567", "10"], ","),
    (["212477.0", "46.301"], "."),              # Fuelio
    (["12,345", "1,234"], None),                # same dwuznaczne
    (["40.5", "250,00"], None),                 # plik mieszany — liczba po liczbie
    (["100000", "40"], None),
])
def test_separator_dziesietny_pliku(wartosci, oczekiwany):
    assert db.rozpoznaj_separator_dziesietny(wartosci) == oczekiwany


@pytest.mark.parametrize("nazwa, kategoria", [
    ("Parking", "Parking i garaż"),
    ("Parking fine", "Mandaty i opłaty drogowe"),
    ("Tolls", "Mandaty i opłaty drogowe"),
    ("Winieta", "Mandaty i opłaty drogowe"),
    ("Car Wash", "Myjnia i kosmetyka"),
    ("Lavagem", "Myjnia i kosmetyka"),
    ("OC/AC", "Ubezpieczenie"),
    ("Insurance", "Ubezpieczenie"),
    ("MOT", "Opłaty urzędowe"),
    ("Przegląd techniczny", "Opłaty urzędowe"),
    ("Accessories", "Wyposażenie i akcesoria"),
    ("myjnia i kosmetyka", "Myjnia i kosmetyka"),   # nazwa kategorii aplikacji
    ("Spark plugs", None),                           # „park” tylko od początku słowa
    ("Motor oil", None),                             # „MOT” tylko jako całe słowo
    ("Taxi", None),
    ("", None),
])
def test_kategoria_z_nazwy(nazwa, kategoria):
    assert db.kategoria_z_nazwy(nazwa) == kategoria


def test_kategorie_wzorcow_sa_kategoriami_aplikacji():
    from db import import_csv

    assert {k for k, _ in import_csv._WZORCE_KATEGORII} <= set(db.KATEGORIE_INNYCH_KOSZTOW)


@pytest.mark.parametrize("nazwa, serwis", [
    ("Service", True), ("Maintenance", True), ("Konserwacja", True), ("Wymiana klocków", True),
    ("Serviço", True), ("Przegląd techniczny", False), ("MOT", False), ("Parking", False), ("", False),
])
def test_nazwa_serwisowa(nazwa, serwis):
    assert db.czy_nazwa_serwisowa(nazwa) is serwis


# ------------------------------------------------------------- rozpoznanie


@pytest.mark.parametrize("tresc, aplikacja", [
    (FUELIO, "fuelio"), (FUELIO_USA_PHEV, "fuelio"), (DRIVVO, "drivvo"), (ACAR, "acar"),
    (SIMPLY_AUTO, "simply_auto"), ("Data;Licznik;Litry;Kwota\n01.02.2026;1000;40;250\n", None),
])
def test_rozpoznanie_aplikacji_po_zawartosci(tmp_path, tresc, aplikacja):
    assert db.rozpoznaj_aplikacje(_wiersze(tmp_path, tresc)) == aplikacja


@pytest.mark.parametrize("fraza", ["fuelio", "Drivvo", "acar", "simply auto"])
def test_wyszukiwarka_prowadzi_do_importu_po_nazwie_aplikacji(fraza):
    akcje = {e["akcja"]: (lambda: None) for e in utils.EKRANY if e.get("akcja")}
    assert [e["id"] for e in utils.znajdz_ekrany(fraza, akcje=akcje)] == ["import"]


def test_kazdy_preset_ma_opis_i_etykiete():
    for klucz, preset in db.PRESETY_IMPORTU.items():
        assert preset["etykieta"] and preset["opis"], klucz
        assert callable(preset["rozpoznaj"]) and callable(preset["rozbierz"]), klucz


# ------------------------------------------------------------------ Fuelio


def test_fuelio_rozklada_plik_na_trzy_typy(tmp_path):
    rozbior = db.rozbierz_plik_importu("fuelio", _wiersze(tmp_path, FUELIO))
    czesci = _czesci(rozbior)

    assert set(czesci) == {"tankowania", "inne_koszty", "wizyty"}
    assert rozbior["jednostka"] == "km" and rozbior["nazwa_pojazdu"] == "Auris z Fuelio"
    assert dict(rozbior["pominiete"]) == {"przypomnienia bez kwoty": 1, "przychody": 1, "szablony kosztów": 1}
    assert len(czesci["tankowania"]["wiersze"]) == 3
    assert len(czesci["inne_koszty"]["wiersze"]) == 4
    assert len(czesci["wizyty"]["wiersze"]) == 2


def test_fuelio_tankowania_przechodza_walidacje(baza, tmp_path):
    auto_id = _auto()
    czesc = _czesci(db.rozbierz_plik_importu("fuelio", _wiersze(tmp_path, FUELIO)))["tankowania"]
    raport = _raport(auto_id, czesc)

    assert raport["bledy"] == []
    pierwsze, drugie, trzecie = raport["gotowe"]
    assert (pierwsze["data"], pierwsze["przebieg"], pierwsze["litry"], pierwsze["kwota"]) == ("07.10.2018", 12424, 33.04, 172.92)
    assert pierwsze["stacja"] == "Orlen Kraków" and pierwsze["do_pelna"] == 1
    assert drugie["do_pelna"] == 0 and drugie["notatka"] == "Bak do połowy"
    # Kwota pusta — policzona z ilości i ceny za litr.
    assert trzecie["kwota"] == pytest.approx(38.5 * 5.4)


def test_fuelio_koszty_kategorie_i_serwis(baza, tmp_path):
    auto_id = _auto()
    czesci = _czesci(db.rozbierz_plik_importu("fuelio", _wiersze(tmp_path, FUELIO)))

    koszty = {g["nazwa"]: g for g in _raport(auto_id, czesci["inne_koszty"])["gotowe"]}
    assert koszty["Parking Praha"]["kategoria"] == "Parking i garaż" and not koszty["Parking Praha"]["tagi"]
    assert koszty["A2 Konin"]["kategoria"] == "Mandaty i opłaty drogowe"
    assert koszty["OC"]["kategoria"] == "Ubezpieczenie" and koszty["OC"]["notatka"] == "PZU"
    # Kategoria, której aplikacja nie zna, zostaje przy wpisie jako tag.
    assert koszty["Opony zimowe"]["kategoria"] == "Ogólne" and koszty["Opony zimowe"]["tagi"] == "Winterreifen"

    wizyty = {g["opis"]: g for g in _raport(auto_id, czesci["wizyty"])["gotowe"]}
    # „Service” z numeru 1, a „Wymiana klocków” z kategorii „Other” — po tytule.
    assert set(wizyty) == {"Wymiana oleju", "Wymiana klocków"}
    assert wizyty["Wymiana oleju"]["przebieg"] == 13300 and wizyty["Wymiana oleju"]["notatka"] == "Castrol 5W30"


def test_fuelio_mile_galony_i_prad_z_drugiego_zbiornika(baza, tmp_path):
    auto_id = _auto("Plug-in", "Hybryda plug-in")
    rozbior = db.rozbierz_plik_importu("fuelio", _wiersze(tmp_path, FUELIO_USA_PHEV))
    assert rozbior["jednostka"] == "mi"
    raport = _raport(auto_id, _czesci(rozbior)["tankowania"], jednostka=rozbior["jednostka"])

    benzyna, prad = raport["gotowe"]
    assert benzyna["data"] == "10.03.2024" and prad["data"] == "12.03.2024"
    assert benzyna["litry"] == pytest.approx(37.854, abs=0.001), "galony USA na litry"
    assert prad["litry"] == pytest.approx(8.2), "kWh z drugiego zbiornika bez przeliczania"
    assert (benzyna["rodzaj_energii"], prad["rodzaj_energii"]) == (db.ENERGIA_PALIWO, db.ENERGIA_PRAD)
    assert benzyna["przebieg"] == 16093


def test_pominiete_tankowanie_zostaje_w_uwagach(tmp_path):
    """Aplikacja nie zna flagi „Missed” — spalanie przez lukę wyjdzie zaniżone,
    więc człowiek ma się o tym dowiedzieć przed importem."""
    tresc = FUELIO.replace('"Bak do połowy","0"', '"Bak do połowy","1"')
    rozbior = db.rozbierz_plik_importu("fuelio", _wiersze(tmp_path, tresc))
    assert any("przy 1 wpisie" in uwaga for uwaga in rozbior["uwagi"])
    assert not any("Pominięte wcześniejsze" in u for u in db.rozbierz_plik_importu("fuelio", _wiersze(tmp_path, FUELIO))["uwagi"])


def test_fuelio_zapis_i_ponowny_import(baza, tmp_path):
    auto_id = _auto()
    db.zapisz_moje_imie("Kamil")
    rozbior = db.rozbierz_plik_importu("fuelio", _wiersze(tmp_path, FUELIO))
    for czesc in rozbior["czesci"]:
        raport = _raport(auto_id, czesc)
        assert db.TYPY_IMPORTU[czesc["typ"]]["zapisz"](auto_id, raport["gotowe"]) == len(raport["gotowe"])

    with db.polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT data_iso, notatka, notatka_autor FROM tankowania WHERE auto_id=? ORDER BY data_iso", (auto_id,))
        tankowania = c.fetchall()
        c.execute("SELECT kategoria, tagi FROM inne_koszty WHERE auto_id=? AND nazwa='Opony zimowe'", (auto_id,))
        opony = c.fetchone()
        c.execute("SELECT wykonawca, notatki, przebieg, dodane_przez FROM wizyty WHERE auto_id=? ORDER BY data_iso", (auto_id,))
        wizyty = c.fetchall()

    assert [t[0] for t in tankowania] == ["2018-10-07", "2018-10-21", "2018-11-04"]
    assert tankowania[1][1:] == ("Bak do połowy", "Kamil") and tankowania[0][1:] == (None, None)
    assert opony == ("Ogólne", "Winterreifen")
    assert wizyty[0] == ("Warsztat", "Wymiana oleju\nCastrol 5W30", 13300, "Kamil")

    # Ten sam plik drugi raz: wszystko to duplikaty.
    for czesc in db.rozbierz_plik_importu("fuelio", _wiersze(tmp_path, FUELIO))["czesci"]:
        raport = _raport(auto_id, czesc)
        assert raport["gotowe"] == [] and raport["duplikaty"] == len(czesc["wiersze"]), czesc["typ"]


# ------------------------------------------------------------------ Drivvo


def test_drivvo_sekcje_pozycje_i_przelozone_flagi(baza, tmp_path):
    auto_id = _auto()
    rozbior = db.rozbierz_plik_importu("drivvo", _wiersze(tmp_path, DRIVVO))
    czesci = _czesci(rozbior)
    assert rozbior["nazwa_pojazdu"] == "Golf VII"
    assert dict(rozbior["pominiete"]) == {"przychody": 1}

    tank = _raport(auto_id, czesci["tankowania"])["gotowe"]
    assert [(g["data"], g["przebieg"], g["litry"], g["kwota"], g["do_pelna"]) for g in tank] == [
        ("21.05.2019", 45000, 40.0, 207.6, 1), ("02.06.2019", 45600, 30.0, 158.7, 0)]
    assert tank[0]["stacja"] == "Orlen" and tank[0]["notatka"] == "Pełny bak"

    koszty = {g["nazwa"]: g["kategoria"] for g in _raport(auto_id, czesci["inne_koszty"])["gotowe"]}
    assert koszty == {"Parking": "Parking i garaż", "Insurance": "Ubezpieczenie"}

    (wizyta,) = _raport(auto_id, czesci["wizyty"])["gotowe"]
    assert (wizyta["opis"], wizyta["warsztat"], wizyta["kwota"], wizyta["notatka"]) == (
        "Oil change", "ASO Kraków", 650.0, "Olej i filtr")


def test_drivvo_po_polsku_i_po_hiszpansku(baza, tmp_path):
    auto_id = _auto()
    tresc = DRIVVO.replace(",Yes,", ",Tak,").replace(",No,No,", ",Nie,Nie,").replace("##Refuelling", "#Reabastecimiento")
    wiersze = _wiersze(tmp_path, tresc)
    assert db.rozpoznaj_aplikacje(wiersze) == "drivvo"
    tank = _raport(auto_id, _czesci(db.rozbierz_plik_importu("drivvo", wiersze))["tankowania"])["gotowe"]
    assert [g["do_pelna"] for g in tank] == [1, 0]


def test_drivvo_z_innym_ukladem_dopasowuje_po_nazwach(baza, tmp_path):
    """Nowsza wersja z przestawionymi kolumnami: pozycje z konwertera nie
    pasują, więc kolumny dopasowuje zwykły mechanizm — i mówi o tym."""
    tresc = "##Refuelling\nDate,Odometer,Liters,Total cost\n21/05/2019,45000,40,207.60\n"
    rozbior = db.rozbierz_plik_importu("drivvo", _wiersze(tmp_path, tresc))
    (czesc,) = rozbior["czesci"]
    assert any("dopasowana po nazwach" in u for u in rozbior["uwagi"])
    (gotowe,) = _raport(_auto(), czesc)["gotowe"]
    assert (gotowe["data"], gotowe["przebieg"], gotowe["litry"]) == ("21.05.2019", 45000, 40.0)


# -------------------------------------------------------------------- aCar


def test_acar_wybiera_pojazd_i_przelicza_usa(baza, tmp_path):
    auto_id = _auto()
    wiersze = _wiersze(tmp_path, ACAR)
    rozbior = db.rozbierz_plik_importu("acar", wiersze)
    czesci = _czesci(rozbior)

    assert [(k, n) for k, _, n in rozbior["pojazdy"]] == [("Civic", 5), ("Jazz", 1)]
    assert rozbior["pojazd"] == "Civic" and rozbior["jednostka"] == "mi"
    assert dict(rozbior["pominiete"]) == {"wpisy innych pojazdów z pliku": 1}

    pierwsze, drugie = _raport(auto_id, czesci["tankowania"], jednostka="mi")["gotowe"]
    assert pierwsze["data"] == "14.03.2019" and pierwsze["przebieg"] == 19867, "12,345 mi — przecinek to tysiące"
    assert pierwsze["litry"] == pytest.approx(39.747, abs=0.001) and pierwsze["kwota"] == 36.32
    assert pierwsze["stacja"] == "Shell" and drugie["stacja"] == "5 Oak Ave"
    assert (pierwsze["do_pelna"], drugie["do_pelna"]) == (1, 0) and drugie["notatka"] == "Half tank"

    (wizyta,) = _raport(auto_id, czesci["wizyty"], jednostka="mi")["gotowe"]
    assert (wizyta["opis"], wizyta["warsztat"], wizyta["kwota"]) == ("Oil Change, Oil Filter", "Jiffy Lube", 59.99)

    koszty = {g["nazwa"]: g["kategoria"] for g in _raport(auto_id, czesci["inne_koszty"])["gotowe"]}
    assert koszty == {"Parking": "Parking i garaż", "Car Wash": "Myjnia i kosmetyka"}

    jazz = _czesci(db.rozbierz_plik_importu("acar", wiersze, pojazd="Jazz"))
    assert set(jazz) == {"tankowania"} and len(jazz["tankowania"]["wiersze"]) == 1


# ------------------------------------------------------------- Simply Auto


def test_simply_auto_rozdziela_rodzaje_wpisow(baza, tmp_path):
    auto_id = _auto()
    rozbior = db.rozbierz_plik_importu("simply_auto", _wiersze(tmp_path, SIMPLY_AUTO))
    czesci = _czesci(rozbior)
    assert rozbior["pojazd"] == "car1" and dict(rozbior["pominiete"]) == {"wpisy innych pojazdów z pliku": 1}

    tank = _raport(auto_id, czesci["tankowania"])["gotowe"]
    assert [(g["data"], g["przebieg"], g["do_pelna"], g["stacja"]) for g in tank] == [
        ("05.01.2020", 10000, 1, "Orlen Kraków"), ("20.01.2020", 10500, 0, "BP"), ("12.12.2020", 11000, 1, "Orlen")]
    assert tank[1]["dystans"] == 500 and tank[1]["notatka"] == "Nie do pełna"

    (wizyta,) = _raport(auto_id, czesci["wizyty"])["gotowe"]
    assert (wizyta["opis"], wizyta["warsztat"], wizyta["notatka"]) == ("Tire Rotation, Oil Change", "Auto Serwis", "Opony")

    (koszt,) = _raport(auto_id, czesci["inne_koszty"])["gotowe"]
    assert (koszt["nazwa"], koszt["kategoria"], koszt["data"]) == ("Parking", "Parking i garaż", "01.02.2020")


def test_simply_auto_miesiace_od_zera(tmp_path):
    tresc = SIMPLY_AUTO.replace(",5,1,2020,", ",5,0,2020,").replace(",12,12,2020,", ",12,11,2020,")
    rozbior = db.rozbierz_plik_importu("simply_auto", _wiersze(tmp_path, tresc))
    czesc = _czesci(rozbior)["tankowania"]
    daty = [w[czesc["mapowanie"]["data"]] for w in czesc["wiersze"]]
    assert daty == ["05.01.2020", "20.02.2020", "12.12.2020"]
    assert any("od zera" in u for u in rozbior["uwagi"])


# ------------------------------------------------------ zwykły import (bez presetu)


def test_zwykly_import_kosztow_rozpoznaje_kategorie_z_tagow(baza):
    auto_id = _auto()
    naglowki = ["Data", "Opis", "Kwota", "Tagi", "Uwagi"]
    wiersze = [["01.02.2026", "Mycie", "40", "Myjnia", "przed zimą"], ["02.02.2026", "Coś", "10", "Różne", ""]]
    mapowanie = db.dopasuj_kolumny_innych_kosztow(naglowki)
    assert mapowanie["notatka"] == 4
    myjnia, rozne = sorted(db.przygotuj_import_innych_kosztow(auto_id, naglowki, wiersze, mapowanie)["gotowe"],
                           key=lambda g: g["data"])
    assert (myjnia["kategoria"], myjnia["tagi"], myjnia["notatka"]) == ("Myjnia i kosmetyka", "Myjnia", "przed zimą")
    assert (rozne["kategoria"], rozne["tagi"]) == ("Ogólne", "Różne")


def test_zwykly_import_wizyt(baza):
    auto_id = _auto()
    naglowki = ["Data", "Przebieg", "Koszt", "Zakres prac", "Warsztat", "Notatki"]
    wiersze = [["12.03.2024", "123 456", "450,00", "Wymiana oleju", "Auto-Mech", ""],
               ["13.03.2024", "", "0", "", "", ""]]
    mapowanie = db.dopasuj_kolumny_wizyt(naglowki)
    assert [mapowanie[p] for p in ("data", "przebieg", "kwota", "opis", "warsztat", "notatka")] == [0, 1, 2, 3, 4, 5]
    raport = db.przygotuj_import_wizyt(auto_id, naglowki, wiersze, mapowanie)
    assert raport["bledy"] == [(3, "zerowy koszt i brak opisu prac")]
    (wizyta,) = raport["gotowe"]
    assert (wizyta["przebieg"], wizyta["kwota"], wizyta["warsztat"]) == (123456, 450.0, "Auto-Mech")


def test_zwykly_import_z_datami_amerykanskimi(baza):
    auto_id = _auto()
    naglowki = ["Date", "Odometer", "Liters", "Total"]
    wiersze = [["05/13/2024", "1,000", "40.5", "250.10"], ["06/02/2024", "1,500", "38", "230"]]
    gotowe = db.przygotuj_import_tankowan(auto_id, naglowki, wiersze, db.dopasuj_kolumny_tankowan(naglowki))["gotowe"]
    assert [(g["data"], g["przebieg"]) for g in gotowe] == [("13.05.2024", 1000), ("02.06.2024", 1500)]


# ------------------------------------------------------------------- ekran


def _ekran(auto_id, nazwa="Z innej aplikacji"):
    strona = pomoce.zbuduj_strone()
    widok = pomoce.zbuduj_widok(pomoce.klasy_widokow()["ImportCSVView"], strona,
                                pomoce.stan_aplikacji(auto_id, nazwa))
    return strona, widok


def test_ekran_rozpoznaje_fuelio_i_importuje_wszystko_naraz(baza, tmp_path):
    auto_id = _auto()
    strona, widok = _ekran(auto_id)
    widok._po_wczytaniu("vehicle-1.csv", _wiersze(tmp_path, FUELIO))

    assert widok.zrodlo == "fuelio" and widok.e_zrodlo.value == "fuelio"
    assert not widok.e_typ.visible, "przy presecie typ wybiera plik, nie człowiek"
    assert [c["typ"] for c in widok.czesci] == ["tankowania", "inne_koszty", "wizyty"]
    assert len(widok.gotowe) == 9

    widok._przelacz_czesc(widok.czesci[2], False)
    assert len(widok.gotowe) == 7

    ile = widok._zapisz_czesci()
    assert ile == {"tankowania": 3, "inne_koszty": 4}
    with db.polacz_baze() as conn:
        assert conn.execute("SELECT COUNT(*) FROM wizyty WHERE auto_id=?", (auto_id,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM inne_koszty WHERE auto_id=?", (auto_id,)).fetchone()[0] == 4


def test_ekran_pojazd_w_pliku_i_powrot_do_arkusza(baza, tmp_path):
    auto_id = _auto()
    strona, widok = _ekran(auto_id)
    widok._po_wczytaniu("Fuel_Log.csv", _wiersze(tmp_path, SIMPLY_AUTO))

    assert widok.zrodlo == "simply_auto" and widok.e_pojazd.visible
    assert len(widok.gotowe) == 5
    widok.e_pojazd.value = "car2"
    widok._zmien_pojazd(None)
    assert len(widok.gotowe) == 1 and widok.czesci[0]["typ"] == "tankowania"

    widok.e_zrodlo.value = "arkusz"
    widok._zmien_zrodlo(None)
    assert widok.e_typ.visible and not widok.e_pojazd.visible
    assert [c["typ"] for c in widok.czesci] == ["tankowania"]
