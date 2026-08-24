from datetime import datetime

def parsuj_date(data_str):
    if not data_str:
        return datetime.min.date()
    for fmt in ('%d.%m.%Y', '%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%Y.%m.%d'):
        try:
            return datetime.strptime(str(data_str).strip(), fmt).date()
        except ValueError:
            pass
    return datetime.min.date()