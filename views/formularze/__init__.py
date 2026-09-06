"""Formularze dodawania i edycji — po jednym module na typ wpisu.

Powstało z rozbicia jednego pliku forms_view.py. Nazwy klas zostały bez zmian,
więc `from views.formularze import FormularzAutoView` działa jak dawniej.
"""

from .vin import dekoduj_wmi_lokalnie, pobierz_dane_vin, rok_produkcji_z_vin
from .auto import FormularzAutoView
from .tankowanie import FormularzTankowanieView
from .inne_koszty import FormularzInneView
from .zadanie import FormularzZadanieView
from .interwal import FormularzInterwalView
from .wpis_serwisowy import FormularzWpisView
from .wizyta import FormularzWizytyView

__all__ = [
    "FormularzAutoView",
    "FormularzInneView",
    "FormularzInterwalView",
    "FormularzTankowanieView",
    "FormularzWizytyView",
    "FormularzWpisView",
    "FormularzZadanieView",
    "dekoduj_wmi_lokalnie",
    "pobierz_dane_vin",
    "rok_produkcji_z_vin",
]
