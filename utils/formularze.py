"""Budulec formularzy: pola, style, walidacja i ostrzeżenia przed zapisem."""

import db
import flet as ft
from datetime import date, datetime, timezone

from .stale import FS, RADIUS, SPACING
from .wyglad import dol_bezpieczny, powierzchnia_karty, tlo_karty
from .zgodnosc import ustaw_blad, ustaw_ikone
from .dialogi import otworz_dialog, pokaz_komunikat, przejdz


def pole_daty(page: ft.Page, label, wartosc_poczatkowa=None):
    pole = ft.TextField(
        label=label, 
        value=str(wartosc_poczatkowa) if wartosc_poczatkowa else "",
        read_only=True, 
        hint_text="Wybierz datę",
        **styl_pola()
    )

    def otworz(e):
        try:
            data_pocz = datetime.strptime(pole.value, "%d.%m.%Y") if pole.value else datetime.now()
        except Exception:
            data_pocz = datetime.now()

        def po_wyborze(e2):
            if e2.control.value:
                val = e2.control.value

                # 1. Obsługa formatu tekstowego ISO
                if isinstance(val, str):
                    try:
                        val = datetime.fromisoformat(val.replace("Z", "+00:00"))
                    except Exception:
                        pass

                # 2. Przeliczenie ze strefy UTC na lokalną
                if isinstance(val, datetime):
                    if val.tzinfo is not None:
                        val = val.astimezone()
                    elif val.hour != 0:
                        val = val.replace(tzinfo=timezone.utc).astimezone()
                    
                    pole.value = val.strftime("%d.%m.%Y")
                elif isinstance(val, date):
                    pole.value = val.strftime("%d.%m.%Y")
                else:
                    pole.value = str(val)

                ustaw_blad(pole)
                page.update()

        picker = ft.DatePicker(
            value=data_pocz, 
            first_date=datetime(1990, 1, 1), 
            last_date=datetime(2100, 12, 31),
            on_change=po_wyborze, 
            cancel_text="Anuluj", 
            confirm_text="Wybierz", 
            help_text=label
        )
        otworz_dialog(page, picker)

    pole.suffix = ft.IconButton(
        icon=ft.Icons.CALENDAR_MONTH, 
        tooltip="Wybierz datę", 
        on_click=otworz, 
        icon_size=20
    )
    return pole


def pokaz_bledy_formularza(page: ft.Page, bledy):
    for kontrolka, komunikat in bledy:
        ustaw_blad(kontrolka, komunikat)
    page.update()
    pokaz_komunikat(page, "Popraw zaznaczone pola formularza.", ft.Colors.RED_700)


def sprawdz_podejrzany_przebieg(page: ft.Page, pole_przebiegu: ft.TextField, auto_id, nowy_przebieg, wyklucz_id=None, tabela=None, nowa_data_str=None):
    """
    Wspólna logika 'niski przebieg — potwierdź ponownie' używana przy zapisie
    tankowań i wpisów historii. Pamięta DOKŁADNĄ wartość, która została już
    potwierdzona (nie tylko fakt, że jakieś ostrzeżenie się kiedyś pojawiło),
    więc zmiana na INNĄ podejrzaną wartość ponownie wymusi potwierdzenie.

    Zwraca True, jeśli zapis należy przerwać (pokazano świeże ostrzeżenie).
    Zwraca False, jeśli można kontynuować zapis.
    """
    ostrzezenie = db.sprawdz_czy_przebieg_podejrzany(auto_id, nowy_przebieg, wyklucz_id=wyklucz_id, tabela=tabela, nowa_data_str=nowa_data_str)

    if ostrzezenie and getattr(pole_przebiegu, "_potwierdzona_wartosc", None) != nowy_przebieg:
        pole_przebiegu._potwierdzona_wartosc = nowy_przebieg
        ustaw_blad(pole_przebiegu, "Niski przebieg — kliknij Zapisz ponownie, aby potwierdzić")
        page.update()
        pokaz_komunikat(page, ostrzezenie, ft.Colors.ORANGE_700)
        return True

    pole_przebiegu._potwierdzona_wartosc = None
    return False


def sprawdz_duplikat_tankowania(page: ft.Page, pole_kwoty: ft.TextField, auto_id, data_str, przebieg, kwota, wyklucz_id=None):
    """Analogicznie do sprawdz_podejrzany_przebieg — ostrzega, jeśli identyczne
    tankowanie (data+przebieg+kwota) już istnieje, zamiast cicho zapisać
    potencjalny duplikat. Zwraca True, jeśli zapis należy przerwać."""
    klucz = (data_str, przebieg, kwota)
    ostrzezenie = db.sprawdz_czy_tankowanie_duplikat(auto_id, data_str, przebieg, kwota, wyklucz_id=wyklucz_id)

    if ostrzezenie and getattr(pole_kwoty, "_duplikat_potwierdzony", None) != klucz:
        pole_kwoty._duplikat_potwierdzony = klucz
        ustaw_blad(pole_kwoty, "Możliwy duplikat — kliknij Zapisz ponownie, aby potwierdzić")
        page.update()
        pokaz_komunikat(page, ostrzezenie, ft.Colors.ORANGE_700)
        return True

    pole_kwoty._duplikat_potwierdzony = None
    return False


def sprawdz_duplikat_kosztu(page: ft.Page, pole_kwoty: ft.TextField, auto_id, data_str, nazwa, kwota, wyklucz_id=None):
    """Analogicznie do sprawdz_duplikat_tankowania — ostrzega, jeśli identyczny
    koszt (data+nazwa+kwota) już istnieje, zamiast cicho zapisać potencjalny
    duplikat. Zwraca True, jeśli zapis należy przerwać."""
    klucz = (data_str, nazwa, kwota)
    ostrzezenie = db.sprawdz_czy_koszt_duplikat(auto_id, data_str, nazwa, kwota, wyklucz_id=wyklucz_id)

    if ostrzezenie and getattr(pole_kwoty, "_duplikat_potwierdzony", None) != klucz:
        pole_kwoty._duplikat_potwierdzony = klucz
        ustaw_blad(pole_kwoty, "Możliwy duplikat — kliknij Zapisz ponownie, aby potwierdzić")
        page.update()
        pokaz_komunikat(page, ostrzezenie, ft.Colors.ORANGE_700)
        return True

    pole_kwoty._duplikat_potwierdzony = None
    return False


def styl_pola(page: ft.Page = None):
    return {
        "border_radius": RADIUS["md"],
        "border_color": ft.Colors.TRANSPARENT,   # ramka niewidoczna...
        "border_width": 1.5,
        "focused_border_color": ft.Colors.PRIMARY,  # ...i pojawia się tylko na focus
        "focused_border_width": 2,
        "content_padding": ft.Padding(16, 14, 16, 14),  # 16 poziomo / 14 pionowo — pole ~52-56px
        "filled": True,
        "bgcolor": tlo_karty(page, poziom=2),
    }


def styl_dropdown(page: ft.Page = None):
    return {
        "border_radius": RADIUS["md"],
        "border_color": ft.Colors.TRANSPARENT,
        "border_width": 1.5,
        "focused_border_color": ft.Colors.PRIMARY,
        "focused_border_width": 2,
        "content_padding": ft.Padding(16, 14, 16, 14),
        "filled": True,
        "fill_color": tlo_karty(page, poziom=2),  # UWAGA: nie "bgcolor" — patrz niżej
        "text_size": 15,
    }


def wysokosc_listy(page: ft.Page, udzial=0.5, minimalna=260):
    """Sugerowana wysokość (px) dla zwirtualizowanej listy/siatki (ListView/GridView)
    osadzonej w przewijanym widoku. Używamy jej zamiast `expand=True`, bo gdy nad listą
    jest dużo stałych elementów (nagłówek auta, skróty, pasek sortowania, wyszukiwarka),
    `expand` potrafi skurczyć się do zera na mniejszych telefonach i lista znika
    całkowicie. Dzięki stałej wysokości lista ZAWSZE jest widoczna i przewija się sama,
    a resztę strony (nagłówek itp.) przewija się nad nią jak zwykłą stronę."""
    try:
        wys_ekranu = page.height or getattr(page.window, "height", None) or 800
    except Exception:
        wys_ekranu = 800
    return max(minimalna, int(wys_ekranu * udzial))


def dopasuj_wysokosc_listy(lista, page: ft.Page, wysokosc_pozycji=175, na_wiersz=1, udzial=0.5):
    """Dociąga wysokość zwirtualizowanej listy do tego, co w niej NAPRAWDĘ leży.

    `wysokosc_listy` daje pół ekranu i tyle samo zajmowała lista z jedną kartą,
    co z pięćdziesięcioma — pod krótką listą zostawał wtedy pusty prostokąt na
    pół ekranu (najbardziej rzucało się to w oczy w Wizytach i Karoserii, gdzie
    tło listy jest jasne). Teraz bierzemy MNIEJSZĄ z dwóch wartości: sugerowaną
    połowę ekranu i szacowaną wysokość zawartości.

    `wysokosc_pozycji` to przybliżona wysokość jednej karty razem z odstępem —
    lepiej ją PRZESZACOWAĆ, bo zapas oznacza tylko trochę wolnego miejsca, a
    niedoszacowanie chowa ostatnią kartę za wewnętrznym przewijaniem.
    `na_wiersz` > 1 dla siatek (GridView), gdzie w jednym wierszu stoi kilka
    kafelków.

    Wołać PO wypełnieniu listy kartami. Wysokość zapamiętuje się na kontrolce,
    żeby obrót ekranu (dostosuj_wysokosc_listy) przeliczył ją tak samo."""
    try:
        liczba = len(lista.controls or [])
    except Exception:
        return lista

    lista._wys_pozycji = wysokosc_pozycji
    lista._na_wiersz = max(1, int(na_wiersz or 1))
    lista._udzial_ekranu = udzial

    if liczba <= 0:
        # Pusty ListView ma stałą wysokość i sam w sobie zostawiał pustkę pod
        # komunikatem „brak danych”. Skoro nie ma czego pokazać — niech go nie ma.
        lista.height = 0
        lista.visible = False
        return lista

    lista.visible = True
    wiersze = -(-liczba // lista._na_wiersz)   # ceil bez importu math
    potrzebna = wiersze * wysokosc_pozycji
    lista.height = min(wysokosc_listy(page, udzial=udzial), max(wysokosc_pozycji, potrzebna))
    return lista


def karta_formularza(zawartosc, tytul=None, ikona=None, domyslnie_otwarte=False, page: ft.Page = None):
    powierzchnia = powierzchnia_karty(page, "md")

    if not tytul:
        return ft.Container(
            padding=SPACING["lg"], border_radius=RADIUS["lg"],
            bgcolor=powierzchnia["bgcolor"], shadow=powierzchnia["shadow"],
            border=powierzchnia["border"],
            content=ft.Column(zawartosc, spacing=SPACING["md"])
        )

    cialo = ft.Container(
        padding=ft.Padding(SPACING["lg"], 0, SPACING["lg"], SPACING["lg"]),
        visible=domyslnie_otwarte,
        content=ft.Column(zawartosc, spacing=SPACING["md"])
    )

    ikona_strzalki = ft.Icon(
        ft.Icons.KEYBOARD_ARROW_UP if domyslnie_otwarte else ft.Icons.KEYBOARD_ARROW_DOWN,
        color=ft.Colors.PRIMARY
    )

    def przelacz_rozwijanie(e):
        cialo.visible = not cialo.visible
        ustaw_ikone(ikona_strzalki, ft.Icons.KEYBOARD_ARROW_UP if cialo.visible else ft.Icons.KEYBOARD_ARROW_DOWN)
        e.control.page.update()

    naglowek = ft.Container(
        padding=ft.Padding(SPACING["lg"], SPACING["md"], SPACING["lg"], SPACING["md"]),
        on_click=przelacz_rozwijanie,
        content=ft.Row([
            ft.Icon(ikona, color=ft.Colors.PRIMARY, size=20) if ikona else ft.Container(),
            ft.Text(tytul, weight="bold", size=FS["title"], color=ft.Colors.ON_SURFACE, expand=True),
            ikona_strzalki
        ], spacing=10)
    )

    return ft.Container(
        border_radius=RADIUS["lg"],
        bgcolor=powierzchnia["bgcolor"], shadow=powierzchnia["shadow"],
        border=powierzchnia["border"],
        content=ft.Column([naglowek, cialo], spacing=0)
    )


def przyciski_akcji(page: ft.Page, tekst_zapisu, on_zapisz, trasa_anuluj, ikona_zapisu=ft.Icons.CHECK):
    btn_zapisz = ft.ElevatedButton(
        tekst_zapisu,
        icon=ikona_zapisu,
        on_click=on_zapisz, 
        bgcolor=ft.Colors.PRIMARY, 
        color=ft.Colors.ON_PRIMARY, 
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=RADIUS["md"]), padding=15),
        width=float("inf")
    )
    btn_anuluj = ft.OutlinedButton(
        "Anuluj",
        icon=ft.Icons.CLOSE,
        on_click=lambda e: przejdz(page, trasa_anuluj), 
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=RADIUS["md"]), padding=15),
        width=float("inf")
    )
    return ft.Column([ft.Divider(height=10, color="transparent"), btn_zapisz, btn_anuluj, dol_bezpieczny(30)], spacing=10)


__all__ = [
    "dopasuj_wysokosc_listy",
    "karta_formularza",
    "pokaz_bledy_formularza",
    "pole_daty",
    "przyciski_akcji",
    "sprawdz_duplikat_kosztu",
    "sprawdz_duplikat_tankowania",
    "sprawdz_podejrzany_przebieg",
    "styl_dropdown",
    "styl_pola",
    "wysokosc_listy",
]
