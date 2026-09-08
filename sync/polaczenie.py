"""Klient Supabase i sesja anonimowa — jedno wejście dla całego pakietu.

`_pobierz_klient` importuje `supabase` DOPIERO przy pierwszym wywołaniu.
To nie jest ozdoba: aplikacja ma działać w 100% offline, a import biblioteki
sieciowej na starcie kosztowałby czas przy każdym uruchomieniu, także temu,
kto żadnego auta nie współdzieli.

`_klient_cache` jest tu ŚWIADOMIE nieujęte w `__all__` — patrz komentarz niżej.
"""

import db
import log

from .stale import SUPABASE_ANON_KEY, SUPABASE_URL


# Poza `__all__` ŚWIADOMIE: `_pobierz_klient` PRZYPISUJE tę nazwę na nowo
# (`global`), więc re-eksport w sync/__init__.py zamroziłby kopię z chwili
# importu — `sync._klient_cache` na zawsze None, mimo działającego klienta.
_klient_cache = None


def _pobierz_klient():
    global _klient_cache
    if _klient_cache is None:
        from supabase import create_client
        _klient_cache = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    return _klient_cache


def _upewnij_sesje():
    klient = _pobierz_klient()

    token = db.pobierz_ustawienie("supabase_access_token")
    refresh = db.pobierz_ustawienie("supabase_refresh_token")
    if token and refresh:
        try:
            wynik = klient.auth.set_session(access_token=token, refresh_token=refresh)
            sesja = wynik.session
            db.zapisz_ustawienie("supabase_access_token", sesja.access_token)
            db.zapisz_ustawienie("supabase_refresh_token", sesja.refresh_token)
            klient.postgrest.auth(token=sesja.access_token)
            return klient, sesja.user.id
        except Exception:
            log.polkniety("odtworzenie zapisanej sesji Supabase")

    wynik = klient.auth.sign_in_anonymously()
    sesja = wynik.session
    db.zapisz_ustawienie("supabase_access_token", sesja.access_token)
    db.zapisz_ustawienie("supabase_refresh_token", sesja.refresh_token)
    klient.postgrest.auth(token=sesja.access_token)
    return klient, sesja.user.id


__all__ = [
    "_pobierz_klient",
    "_upewnij_sesje",
]
