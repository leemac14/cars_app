"""Co poszło nie tak w tym przebiegu — do pokazania człowiekowi.

Dwie listy zbierane podczas jednej synchronizacji: rekordy nadpisane mimo
zmiany po obu stronach oraz zmiany odrzucone przez rolę. Bez tego
synchronizacja kończy się słowem „gotowe" nawet wtedy, gdy po drodze zjadła
czyjąś edycję.

UWAGA: obie listy są mutowane W MIEJSCU (`append`, `clear`) i nigdy nie są
przypisywane na nowo. Dzięki temu każdy moduł, który je zaimportuje, trzyma
TEN SAM obiekt — inaczej `_synchronizuj_pod_zamkiem` czyściłby własną kopię,
a `pobierz_konflikty_ostatniej_synchronizacji` czytało cudzą.
Pilnuje tego `test_listy_konfliktow_sa_jednym_obiektem`.
"""

from .stale import ETYKIETY_TABEL_SYNC


# Konflikty wykryte podczas bieżącej synchronizacji — rekordy nadpisane mimo że
# zmieniły się niezależnie po obu stronach (edycja z dwóch urządzeń offline).
# Czyszczone na starcie każdego synchronizuj_wszystko().
_konflikty_biezacej_synchronizacji = []


# Zmiany, których serwer nie przyjąłby, bo dotyczą cudzych wpisów, a mam rolę
# współautora. Nie wysyłamy ich w ogóle i cofamy lokalnie do wersji z chmury —
# inaczej telefon w nieskończoność pokazywałby zmianę, o której nikt inny nie wie.
_odrzucone_biezacej_synchronizacji = []


def _opis_rekordu(tabela, dane):
    """Krótki, ludzki opis konfliktowego rekordu — żeby komunikat mówił CO zostało
    nadpisane, a nie tylko ile rzeczy. Buduje się wyłącznie z pól, które i tak
    lecą do chmury (patrz KONFIGURACJA_SYNC), więc nie wymaga dobicia do bazy."""
    dane = dane or {}

    def pole(*nazwy):
        for n in nazwy:
            w = dane.get(n)
            if w not in (None, ""):
                return str(w)
        return ""

    czesci = []
    data_txt = pole("data", "termin", "nastepna_data", "data_zakupu")
    if data_txt:
        czesci.append(data_txt)

    nazwa_txt = pole("nazwa", "tytul", "stacja", "wykonawca", "sezon")
    if nazwa_txt:
        czesci.append(nazwa_txt)

    kwota = dane.get("kwota", dane.get("cena", dane.get("koszt_calkowity", dane.get("szacowany_koszt"))))
    if kwota not in (None, ""):
        try:
            czesci.append(f"{float(kwota):.2f}")
        except (TypeError, ValueError):
            pass

    if not czesci:
        przebieg = pole("przebieg")
        if przebieg:
            czesci.append(f"{przebieg} km")

    etykieta = ETYKIETY_TABEL_SYNC.get(tabela, tabela)
    return f"{etykieta}: {' • '.join(czesci)}" if czesci else etykieta


def _zarejestruj_konflikt(tabela, dane=None, zdalne_id=None, dane_zdalne=None):
    """`dane_zdalne` to wersja, którą właśnie nadpisujemy. Trzymamy ją, bo bez
    niej przycisk „Weź wersję z chmury” nie miałby czego przywrócić — chwilę po
    wykryciu konfliktu tamtej wersji już na serwerze nie ma."""
    _konflikty_biezacej_synchronizacji.append({
        "tabela": tabela,
        "etykieta": ETYKIETY_TABEL_SYNC.get(tabela, tabela),
        "opis": _opis_rekordu(tabela, dane),
        "opis_zdalny": _opis_rekordu(tabela, dane_zdalne) if dane_zdalne else "",
        "zdalne_id": zdalne_id,
        "dane_zdalne": dane_zdalne,
    })


def _zarejestruj_odrzucenie(tabela, dane=None, zdalne_id=None):
    _odrzucone_biezacej_synchronizacji.append({
        "tabela": tabela,
        "etykieta": ETYKIETY_TABEL_SYNC.get(tabela, tabela),
        "opis": _opis_rekordu(tabela, dane),
        "zdalne_id": zdalne_id,
    })


def pobierz_konflikty_ostatniej_synchronizacji():
    """Lista nadpisanych rekordów z ostatniej synchronizacji:
    [{"tabela","etykieta","opis","opis_zdalny","zdalne_id","dane_zdalne"}, ...].
    Pusta lista = brak konfliktów."""
    return list(_konflikty_biezacej_synchronizacji)


def pobierz_odrzucone_ostatniej_synchronizacji():
    """Zmiany cofnięte, bo dotyczyły cudzych wpisów przy roli współautora."""
    return list(_odrzucone_biezacej_synchronizacji)


__all__ = [
    "_konflikty_biezacej_synchronizacji",
    "_odrzucone_biezacej_synchronizacji",
    "_opis_rekordu",
    "_zarejestruj_konflikt",
    "_zarejestruj_odrzucenie",
    "pobierz_konflikty_ostatniej_synchronizacji",
    "pobierz_odrzucone_ostatniej_synchronizacji",
]
