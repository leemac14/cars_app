"""Ustawienia globalne i per-pojazd: motyw, waluta, jednostki, progi."""

from .stale import JEDNOSTKI_SPALANIA, JEDNOSTKI_ZUZYCIA_EV, KLUCZE_TERMINOW, KOLEJNOSC_TRYBOW_MOTYWU, KOLORY_MOTYWU, PROG_DNI_POWIADOMIEN, PROG_KM_POWIADOMIEN, WALUTY
from .polaczenie import polacz_baze


def pobierz_ustawienie(klucz, domyslna=None):
    with polacz_baze() as conn:
        c = conn.cursor()
        c.execute("SELECT wartosc FROM ustawienia WHERE klucz=?", (klucz,))
        w = c.fetchone()
        return w[0] if w else domyslna


def zapisz_ustawienie(klucz, wartosc):
    with polacz_baze() as conn:
        conn.execute(
            "INSERT INTO ustawienia (klucz, wartosc) VALUES (?, ?) "
            "ON CONFLICT(klucz) DO UPDATE SET wartosc=excluded.wartosc",
            (klucz, wartosc)
        )


def usun_ustawienie(klucz):
    """Kasuje klucz, przez co ustawienie wraca do wartości domyślnej. Używane
    tam, gdzie „brak wpisu” znaczy coś innego niż pusty string — np. próg dni
    dla konkretnego terminu (wtedy obowiązuje globalny) albo układ kokpitu
    pojazdu (wtedy dziedziczy wspólny)."""
    with polacz_baze() as conn:
        conn.execute("DELETE FROM ustawienia WHERE klucz=?", (klucz,))


def pobierz_tryb_motywu():
    """Zwraca 'jasny' / 'ciemny' / 'system'. Jeśli nowy klucz nie był jeszcze
    zapisany, migruje w locie ze starego booleanowego 'tryb_ciemny'."""
    w = pobierz_ustawienie("tryb_motywu")
    if w in KOLEJNOSC_TRYBOW_MOTYWU:
        return w
    return "ciemny" if pobierz_ustawienie("tryb_ciemny", "0") == "1" else "jasny"


def zapisz_tryb_motywu(tryb):
    if tryb in KOLEJNOSC_TRYBOW_MOTYWU:
        zapisz_ustawienie("tryb_motywu", tryb)


def pobierz_czysta_czern():
    """Czy tryb ciemny ma używać czystej czerni (#000000) zamiast ciemnych
    szarości. Osobne ustawienie, a nie czwarty tryb motywu — dzięki temu działa
    też wtedy, gdy tryb „system” sam przełączy telefon na ciemny. Na ekranach
    OLED czarny piksel jest po prostu zgaszony, więc to realnie mniej prądu."""
    return pobierz_ustawienie("czysta_czern", "0") == "1"


def zapisz_czysta_czern(wlaczona):
    zapisz_ustawienie("czysta_czern", "1" if wlaczona else "0")


def pobierz_walute():
    w = pobierz_ustawienie("waluta", "PLN")
    return w if w in WALUTY else "PLN"


def pobierz_jednostke_spalania():
    w = pobierz_ustawienie("jednostka_spalania", "l/100km")
    return w if w in JEDNOSTKI_SPALANIA else "l/100km"


def pobierz_jednostke_zuzycia_ev():
    w = pobierz_ustawienie("jednostka_zuzycia_ev", "kWh/100km")
    return w if w in JEDNOSTKI_ZUZYCIA_EV else "kWh/100km"


def pobierz_kolor_motywu():
    w = pobierz_ustawienie("kolor_motywu", "Indygo")
    return w if w in KOLORY_MOTYWU else "Indygo"


def pobierz_kolor_auta(auto_id):
    """Zwraca kolor motywu przypisany do KONKRETNEGO pojazdu. Jeśli auto nie ma
    ustawionego własnego koloru (albo żadne auto nie jest aktualnie wybrane),
    zwraca globalny kolor domyślny z Ustawień."""
    if auto_id:
        with polacz_baze() as conn:
            c = conn.cursor()
            c.execute("SELECT kolor_motywu FROM samochody WHERE id=?", (auto_id,))
            w = c.fetchone()
            if w and w[0] in KOLORY_MOTYWU:
                return w[0]
    return pobierz_kolor_motywu()


def pobierz_prog_km():
    return int(pobierz_ustawienie("prog_km_powiadomien", str(PROG_KM_POWIADOMIEN)) or PROG_KM_POWIADOMIEN)


def pobierz_prog_dni():
    return int(pobierz_ustawienie("prog_dni_powiadomien", str(PROG_DNI_POWIADOMIEN)) or PROG_DNI_POWIADOMIEN)


def pobierz_prog_dni_dokumentu(klucz):
    """Próg powiadomień (w dniach) dla KONKRETNEGO terminu — OC, przeglądu,
    apteczki itd. Brak własnego ustawienia oznacza „jak domyślny” i zwraca
    wspólny prog_dni_powiadomien, więc nieruszane terminy zachowują się jak
    przed rozbiciem progów."""
    if klucz not in KLUCZE_TERMINOW:
        return pobierz_prog_dni()
    zapisane = pobierz_ustawienie(f"prog_dni_{klucz}")
    if zapisane in (None, ""):
        return pobierz_prog_dni()
    try:
        wartosc = int(zapisane)
    except (TypeError, ValueError):
        return pobierz_prog_dni()
    return wartosc if wartosc > 0 else pobierz_prog_dni()


def zapisz_prog_dni_dokumentu(klucz, wartosc):
    """Pusta wartość KASUJE własny próg — termin wraca pod wspólny domyślny."""
    if klucz not in KLUCZE_TERMINOW:
        return
    tekst = str(wartosc or "").strip()
    if not tekst:
        usun_ustawienie(f"prog_dni_{klucz}")
        return
    zapisz_ustawienie(f"prog_dni_{klucz}", tekst)


def pobierz_wlasny_prog_dni_dokumentu(klucz):
    """Surowa wartość do formularza Ustawień: "" gdy termin idzie za domyślnym."""
    zapisane = pobierz_ustawienie(f"prog_dni_{klucz}")
    return str(zapisane) if zapisane not in (None, "") else ""


def pobierz_moje_imie():
    """Lokalna nazwa/imię tego użytkownika/urządzenia — dopisywana jako
    'dodane_przez' przy nowych wpisach kosztowych, żeby przy współdzielonym
    pojeździe było widać, kto co dodał. Domyślnie 'Kierowca', dopóki nie
    zostanie ustawiona w Ustawieniach."""
    return pobierz_ustawienie("moje_imie", "Kierowca") or "Kierowca"


def zapisz_moje_imie(imie):
    zapisz_ustawienie("moje_imie", (imie or "").strip() or "Kierowca")


# Zwinięte sekcje szuflady — lista identyfikatorów grup po przecinku. Trzymamy
# ZWINIĘTE, a nie rozwinięte, bo domyślnie wszystko jest otwarte: nowa grupa
# dołożona do rejestru ekranów ma być widoczna od razu, a nie ukryta dlatego, że
# nie było jej na starej liście.
def pobierz_zwiniete_grupy_szuflady():
    zapisane = pobierz_ustawienie("szuflada_zwiniete", "") or ""
    return [g.strip() for g in zapisane.split(",") if g.strip()]


def zapisz_zwiniete_grupy_szuflady(grupy):
    zapisz_ustawienie("szuflada_zwiniete", ",".join(dict.fromkeys(g for g in grupy if g)))


def przelacz_grupe_szuflady(grupa_id):
    """Zwija albo rozwija jedną sekcję. Zwraca stan PO zmianie (True = zwinięta)."""
    grupy = pobierz_zwiniete_grupy_szuflady()
    if grupa_id in grupy:
        grupy = [g for g in grupy if g != grupa_id]
        zwinieta = False
    else:
        grupy.append(grupa_id)
        zwinieta = True
    zapisz_zwiniete_grupy_szuflady(grupy)
    return zwinieta


# Same podpisy — ikony dobiera warstwa UI (utils.IKONY_KOKPITU), bo db.py
# celowo nie zna Fleta (korzysta z niego też eksport PDF i synchronizacja).
KOKPIT_WIDGETY = {
    "koszt_miesiac": "Koszt w tym miesiącu",
    "termin": "Najbliższy termin",
    "wykres": "Wykres wydatków (6 mies.)",
    "koszt_km": "Koszt eksploatacji / km",
    "spalanie": "Średnie spalanie",
    "przebieg_dzienny": "Średni przebieg dzienny",
    "ostatnia_aktywnosc": "Ostatnia aktywność",
    "kondycja": "Kondycja pojazdu",
    "zasieg_ev": "Realny zasięg na prądzie",
    "obserwacja": "Obserwacja dnia",
    "budzet": "Budżet",
    "zasieg_bak": "Zasięg na baku",
    "prognoza_rok": "Prognoza roczna",
    "opony": "Opony na aucie",
    "checklist": "Checklista przed trasą",
    "oplaty_drogowe": "Opłaty drogowe i mandaty",
    "do_zrobienia": "Do zrobienia",
    "magazyn": "Magazyn — niski stan",
}

KOKPIT_WIDGETY_DOMYSLNE = ["koszt_miesiac", "termin", "wykres"]


# Kokpit ustawia się osobno dla każdego pojazdu — auto służbowe i prywatne
# rzadko potrzebują tych samych kafelków. Klucz per auto to "kokpit_widgety_<id>";
# dopóki go nie ma, pojazd DZIEDZICZY wspólny układ spod "kokpit_widgety".
# Dzięki temu aktualizacja nie ruszyła nikomu kokpitu, a auto bez własnego
# układu podąża za zmianami wspólnego.
def _klucz_kokpitu(auto_id=None):
    return f"kokpit_widgety_{int(auto_id)}" if auto_id else "kokpit_widgety"


def czy_kokpit_wlasny(auto_id):
    """Czy pojazd ma WŁASNY układ kokpitu, czy dziedziczy wspólny."""
    return bool(auto_id) and pobierz_ustawienie(_klucz_kokpitu(auto_id)) is not None


def przywroc_kokpit_wspolny(auto_id):
    """Odpina pojazd od własnego układu — od tej chwili znowu dziedziczy wspólny."""
    if auto_id:
        usun_ustawienie(_klucz_kokpitu(auto_id))


def _odczytaj_kolejnosc_kokpitu(zapisane):
    kolejnosc, widziane = [], set()
    for w in zapisane.split(","):
        w = w.strip()
        if w in KOKPIT_WIDGETY and w not in widziane:
            widziane.add(w)
            kolejnosc.append(w)
    return kolejnosc


def pobierz_widgety_kokpitu(auto_id=None):
    """Zwraca listę ID widżetów kokpitu wybranych przez użytkownika (patrz
    MainView._buduj_kokpit) — W KOLEJNOŚCI, W JAKIEJ ZOSTAŁY ZAPISANE, bo tę
    kolejność użytkownik ustawia sam, przeciągając kafelki w trybie edycji
    kokpitu. Najpierw szuka układu WŁASNEGO dla pojazdu, potem wspólnego, a na
    końcu wraca do trzech podstawowych widżetów."""
    zapisane = pobierz_ustawienie(_klucz_kokpitu(auto_id)) if auto_id else None
    if zapisane is None:
        zapisane = pobierz_ustawienie("kokpit_widgety")
    if zapisane is None:
        return list(KOKPIT_WIDGETY_DOMYSLNE)
    return _odczytaj_kolejnosc_kokpitu(zapisane)


def zapisz_widgety_kokpitu(lista_id, auto_id=None):
    """Zapisuje ZESTAW oraz KOLEJNOŚĆ widżetów kokpitu — lista wchodzi tu już
    ułożona tak, jak ma wyglądać karuzela. Duplikaty i nieznane ID odpadają.
    Z auto_id zapis odpina pojazd od wspólnego układu; bez niego zmienia układ
    wspólny (i tym samym wszystkie auta, które nadal go dziedziczą)."""
    poprawne, widziane = [], set()
    for w in lista_id:
        if w in KOKPIT_WIDGETY and w not in widziane:
            widziane.add(w)
            poprawne.append(w)
    zapisz_ustawienie(_klucz_kokpitu(auto_id), ",".join(poprawne))


def scal_widgety_kokpitu(zaznaczone, auto_id=None):
    """Łączy nowy ZESTAW włączonych widżetów (np. z checkboxów w Ustawieniach)
    z już zapisaną KOLEJNOŚCIĄ: to, co użytkownik ułożył, zostaje na swoim
    miejscu, a świeżo włączone pozycje dopisują się na końcu (w kolejności
    KOKPIT_WIDGETY). Dzięki temu zaznaczenie checkboxa nie kasuje układu."""
    zaznaczone = set(zaznaczone)
    wynik = [w for w in pobierz_widgety_kokpitu(auto_id) if w in zaznaczone]
    wynik += [w for w in KOKPIT_WIDGETY if w in zaznaczone and w not in wynik]
    return wynik


# Ustawienia przywiązane do KONKRETNEGO pojazdu — przenoszone razem z nim do
# kosza i z powrotem (ID po przywróceniu może się zmienić, patrz
# przywroc_auto_z_kosza), żeby nie zostawały w bazie jako sieroty.
USTAWIENIA_PER_POJAZD = [_klucz_kokpitu]


def _pobierz_ustawienia_pojazdu(auto_id):
    dane = {}
    for buduj_klucz in USTAWIENIA_PER_POJAZD:
        klucz = buduj_klucz(auto_id)
        wartosc = pobierz_ustawienie(klucz)
        if wartosc is not None:
            dane[buduj_klucz.__name__] = wartosc
    return dane


def _usun_ustawienia_pojazdu(auto_id):
    for buduj_klucz in USTAWIENIA_PER_POJAZD:
        usun_ustawienie(buduj_klucz(auto_id))


def _przywroc_ustawienia_pojazdu(auto_id, dane):
    for buduj_klucz in USTAWIENIA_PER_POJAZD:
        wartosc = (dane or {}).get(buduj_klucz.__name__)
        if wartosc is not None:
            zapisz_ustawienie(buduj_klucz(auto_id), wartosc)


__all__ = [
    "KOKPIT_WIDGETY",
    "KOKPIT_WIDGETY_DOMYSLNE",
    "USTAWIENIA_PER_POJAZD",
    "_klucz_kokpitu",
    "_odczytaj_kolejnosc_kokpitu",
    "_pobierz_ustawienia_pojazdu",
    "_przywroc_ustawienia_pojazdu",
    "_usun_ustawienia_pojazdu",
    "czy_kokpit_wlasny",
    "pobierz_zwiniete_grupy_szuflady",
    "przelacz_grupe_szuflady",
    "zapisz_zwiniete_grupy_szuflady",
    "pobierz_czysta_czern",
    "pobierz_jednostke_spalania",
    "pobierz_jednostke_zuzycia_ev",
    "pobierz_kolor_auta",
    "pobierz_kolor_motywu",
    "pobierz_moje_imie",
    "pobierz_prog_dni",
    "pobierz_prog_dni_dokumentu",
    "pobierz_prog_km",
    "pobierz_tryb_motywu",
    "pobierz_ustawienie",
    "pobierz_walute",
    "pobierz_widgety_kokpitu",
    "pobierz_wlasny_prog_dni_dokumentu",
    "przywroc_kokpit_wspolny",
    "scal_widgety_kokpitu",
    "usun_ustawienie",
    "zapisz_czysta_czern",
    "zapisz_moje_imie",
    "zapisz_prog_dni_dokumentu",
    "zapisz_tryb_motywu",
    "zapisz_ustawienie",
    "zapisz_widgety_kokpitu",
]
