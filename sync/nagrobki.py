"""Usunięcie w chmurze przez nagrobek (brak rekordu wygląda jak „jeszcze nie pobrano”).
Osobny moduł, bo nagrobek ma licznik prób."""

import db


def _wypchnij_nagrobki(klient, auto_id=None):
    """Wysyła zaległe usunięcia TEGO pojazdu (albo bez przypisania — sprzed migracji
    40). Nieudana próba zwiększa licznik; nagrobek odrzucany w nieskończoność przestaje
    po kilku próbach."""
    for nagrobek_id, tabela, zdalny_id in db.pobierz_nagrobki(auto_id):
        try:
            klient.rpc("usun_zdalny_rekord", {"p_id": zdalny_id}).execute()
            db.usun_nagrobek_po_id(nagrobek_id)
        except Exception:
            db.zwieksz_proby_nagrobka(nagrobek_id)


__all__ = [
    "_wypchnij_nagrobki",
]
