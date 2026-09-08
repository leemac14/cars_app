"""Kasowanie w chmurze: nagrobek zamiast cichego zniknięcia.

Usunięcie wpisu na jednym telefonie musi dotrzeć do pozostałych, a nie da się
tego zrobić brakiem rekordu — brak wygląda tak samo jak „jeszcze nie pobrano".
Dlatego usunięcie zostawia nagrobek, a ten moduł go wypycha.

Osobny plik, bo nagrobek ma własny licznik prób: rekord, którego nie da się
wypchnąć, nie może wisieć w kolejce w nieskończoność.
"""

import db


def _wypchnij_nagrobki(klient, auto_id=None):
    """Wysyła zaległe usunięcia. Dwie zmiany względem poprzedniej wersji:

    - leci tylko to, co należy do TEGO pojazdu (albo nie ma przypisania —
      nagrobki sprzed migracji 40), zamiast wszystkiego, co jest w tabeli;
    - nieudana próba zwiększa licznik zamiast znikać w `except: pass`. Nagrobek
      odrzucany przez serwer w nieskończoność (bo nie mam prawa kasować tego
      rekordu) przestaje po kilku próbach obciążać każdą synchronizację."""
    for nagrobek_id, tabela, zdalny_id in db.pobierz_nagrobki(auto_id):
        try:
            klient.rpc("usun_zdalny_rekord", {"p_id": zdalny_id}).execute()
            db.usun_nagrobek_po_id(nagrobek_id)
        except Exception:
            db.zwieksz_proby_nagrobka(nagrobek_id)


__all__ = [
    "_wypchnij_nagrobki",
]
