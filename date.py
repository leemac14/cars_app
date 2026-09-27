from datetime import date, datetime

FORMATY_DATY = ('%d.%m.%Y', '%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%Y.%m.%d')


def _sparsuj(data_str) -> date | None:
    if not data_str:
        return None
    for fmt in FORMATY_DATY:
        try:
            return datetime.strptime(str(data_str).strip(), fmt).date()
        except ValueError:
            pass
    return None


def parsuj_date(data_str):
    return _sparsuj(data_str) or datetime.min.date()


def na_iso(data_str) -> str | None:
    """Wartość kolumny `data_iso`: RRRR-MM-DD, więc SQLite sortuje ją i porównuje
    zakresem jak datę. Ta sama logika co `parsuj_date` — czego lista nie umie
    odczytać, nie dostaje też daty sortowalnej (NULL, nie 0001-01-01)."""
    d = _sparsuj(data_str)
    return d.isoformat() if d else None