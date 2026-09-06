"""Odczyt danych z numeru VIN: zapytanie do NHTSA i rozpoznanie lokalne."""

import json
import urllib.request


def pobierz_dane_vin(vin: str) -> dict:
    """
    Pobiera dane pojazdu z darmowego, publicznego API NHTSA (vPIC) na podstawie VIN.
    Funkcja jest SYNCHRONICZNA i blokująca — wywołuj ją wyłącznie przez
    `await asyncio.to_thread(pobierz_dane_vin, vin)`, żeby nie zamrozić UI.
    Zwraca słownik pól (Make, Model, ModelYear, DisplacementCC, EngineHP...).
    W razie problemu rzuca wyjątek — obsługa błędów jest po stronie wywołującego.
    """
    url = f"https://vpic.nhtsa.dot.gov/api/vehicles/decodevinvalues/{urllib.parse.quote(vin)}?format=json"
    zapytanie = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

    with urllib.request.urlopen(zapytanie, timeout=12) as odpowiedz:
        surowe_dane = odpowiedz.read()

    dane_json = json.loads(surowe_dane)
    wyniki = dane_json.get("Results") or []
    if not wyniki:
        raise ValueError("Pusta odpowiedź z bazy NHTSA.")

    return wyniki[0]


# Tablica kodowania roku produkcji wg normy ISO 3779 (10. znak VIN).
# NHTSA rozpoznaje ją głównie dla aut sprzedawanych w USA — dla europejskich
# pojazdów pole ModelYear bywa puste, więc to lokalny fallback.
_ISO3779_KOD_ROKU = {
    "A": 1980, "B": 1981, "C": 1982, "D": 1983, "E": 1984, "F": 1985, "G": 1986, "H": 1987,
    "J": 1988, "K": 1989, "L": 1990, "M": 1991, "N": 1992, "P": 1993, "R": 1994, "S": 1995,
    "T": 1996, "V": 1997, "W": 1998, "X": 1999, "Y": 2000,
    "1": 2001, "2": 2002, "3": 2003, "4": 2004, "5": 2005, "6": 2006, "7": 2007, "8": 2008, "9": 2009,
}


def rok_produkcji_z_vin(vin: str):
    """Dekoduje przybliżony rok produkcji z 10. znaku VIN. Kod roku powtarza się
    w 30-letnim cyklu, więc cykl (np. 1994 czy 2024 dla znaku 'R') rozstrzygamy
    umowną, powszechnie stosowaną konwencją: jeśli 7. znak VIN to litera —
    nowszy cykl (2010+), jeśli cyfra — starszy (1980-2009).
    Zwraca None, jeśli VIN ma nietypową długość albo 10. znak nie jest rozpoznany."""
    vin = (vin or "").strip().upper()
    if len(vin) != 17:
        return None
    bazowy_rok = _ISO3779_KOD_ROKU.get(vin[9])
    if bazowy_rok is None:
        return None
    return bazowy_rok + 30 if vin[6].isalpha() else bazowy_rok


# --- Lokalne rozpoznawanie WMI (3 pierwsze znaki VIN) — działa offline, dla
# KAŻDEGO regionu świata, w przeciwieństwie do NHTSA (patrz niżej), które zna
# głównie modele kiedykolwiek sprzedawane w USA. Baza nie jest wyczerpująca —
# światowy rejestr WMI liczy tysiące kodów (często kilka na jednego producenta,
# wg fabryki/linii modelowej) — ale pokrywa najpopularniejsze marki w Europie.
WMI_PRODUCENCI = {
    # Niemcy
    "WVW": "Volkswagen", "WV1": "Volkswagen", "WV2": "Volkswagen", "WV3": "Volkswagen",
    "WAU": "Audi", "WA1": "Audi", "WUA": "Audi Sport",
    "WBA": "BMW", "WBS": "BMW M", "WBY": "BMW i",
    "WMW": "MINI",
    "WDB": "Mercedes-Benz", "WDC": "Mercedes-Benz", "WDD": "Mercedes-Benz", "WDF": "Mercedes-Benz",
    "W1K": "Mercedes-Benz", "W1N": "Mercedes-Benz", "W1V": "Mercedes-Benz",
    "WME": "smart",
    "WP0": "Porsche", "WP1": "Porsche",
    "W0L": "Opel", "W0V": "Opel",
    "WF0": "Ford",
    # Francja
    "VF1": "Renault", "VF6": "Renault",
    "VF3": "Peugeot",
    "VF7": "Citroën",
    "VSS": "SEAT",
    # Włochy
    "ZFA": "Fiat",
    "ZAR": "Alfa Romeo",
    "ZLA": "Lancia",
    "ZFF": "Ferrari",
    "ZAM": "Maserati",
    # Czechy
    "TMB": "Škoda",
    # Wielka Brytania
    "SAJ": "Jaguar", "SAL": "Land Rover",
    "SCC": "Lotus", "SCA": "Rolls-Royce", "SCB": "Bentley",
    "SB1": "Toyota",
    # Szwecja
    "YV1": "Volvo", "YV4": "Volvo", "YS3": "Saab",
    # Rumunia
    "UU1": "Dacia",
    # Słowacja / Węgry
    "TMK": "Kia", "TSM": "Suzuki",
    # Popularne importy spoza Europy
    "KMH": "Hyundai", "KNA": "Kia", "KNM": "Renault Samsung",
    "JTD": "Toyota", "JTN": "Toyota", "JHM": "Honda", "JN1": "Nissan", "JMZ": "Mazda", "JF1": "Subaru",
    "1FA": "Ford", "1FT": "Ford", "1G1": "Chevrolet", "1HG": "Honda",
}


# Region na podstawie SAMEGO pierwszego znaku VIN (wg ISO 3780) — używany jako
# informacja zapasowa, gdy dokładny 3-znakowy kod producenta nie jest w bazie wyżej.
REGION_WMI = {
    "W": "Niemcy", "V": "Francja/Hiszpania", "Z": "Włochy", "T": "Czechy/Szwajcaria/Węgry",
    "S": "Wielka Brytania", "Y": "Szwecja/Finlandia/Belgia", "U": "Rumunia/Węgry/Dania",
    "X": "Rosja/Holandia", "J": "Japonia", "K": "Korea Południowa", "L": "Chiny",
    "1": "USA", "4": "USA", "5": "USA", "2": "Kanada", "3": "Meksyk", "9": "Brazylia/Argentyna",
    "6": "Australia",
}


def dekoduj_wmi_lokalnie(vin: str):
    """Rozpoznaje markę WYŁĄCZNIE na podstawie kodu WMI, bez zapytania do
    internetu. Działa dla każdego auta zgodnego z normą VIN, niezależnie od
    tego, czy model był kiedykolwiek sprzedawany w USA. Zwraca (marka, region)
    — marka może być None, jeśli dokładny WMI nie jest w bazie (wtedy dostajesz
    chociaż sam region)."""
    vin = (vin or "").strip().upper()
    if len(vin) != 17:
        return None, None
    marka = WMI_PRODUCENCI.get(vin[:3])
    region = REGION_WMI.get(vin[0])
    return marka, region


__all__ = [
    "REGION_WMI",
    "WMI_PRODUCENCI",
    "_ISO3779_KOD_ROKU",
    "dekoduj_wmi_lokalnie",
    "pobierz_dane_vin",
    "rok_produkcji_z_vin",
]
