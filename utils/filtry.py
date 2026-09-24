"""Filtry list: rok, miesiąc, kategoria i autor wpisu."""

import db
import flet as ft
from date import parsuj_date
from datetime import datetime
from state import MIESIACE_NAZWY

from .dialogi import odswiez_ekran
from .stale import kolory_chipa_tagu


WSZYSTKO = "Wszystko"

# Filtr autorstwa przy pojazdach współdzielonych: „kto to dodał”. Wpisy sprzed
# wprowadzenia kolumny dodane_przez (i te bez autora, jak odczyty licznika)
# lądują pod wspólną etykietą — inaczej filtr udawałby, że ich nie ma.
FILTR_AUTOR_MOJE = "Tylko moje"

FILTR_AUTOR_BEZ = "Bez autora"

# Ikona włączona, ikona wyłączona, domyślna etykieta — jedno miejsce dla
# pojedynczego przycisku i dla całego `pasek_filtrow`.
WYGLAD_FILTRA = {
    "rok": (ft.Icons.FILTER_ALT_ROUNDED, ft.Icons.FILTER_ALT_OUTLINED, "Rok"),
    "miesiac": (ft.Icons.DATE_RANGE_ROUNDED, ft.Icons.DATE_RANGE_OUTLINED, "Miesiąc"),
    "kategoria": (ft.Icons.LABEL_ROUNDED, ft.Icons.LABEL_OUTLINE, "Tagi"),
    # Tag to „kategoria” z kolorem ze słownika tagów: te same opcje i to samo
    # filtrowanie, tylko menu i włączony chip w kolorach tagów.
    "tag": (ft.Icons.LABEL_ROUNDED, ft.Icons.LABEL_OUTLINE, "Tagi"),
    "autor": (ft.Icons.PERSON, ft.Icons.PERSON_OUTLINE, "Autor"),
}


def _autor_rekordu(rekord, pole):
    try:
        return " ".join(str(rekord[pole] or "").split())
    except Exception:
        return ""


def _data_rekordu(rekord, pole):
    """Data wpisu albo None, gdy pola nie ma lub nie da się jej sparsować."""
    try:
        d = parsuj_date(rekord[pole])
    except Exception:
        return None
    return d if d != datetime.min.date() else None


def _wartosci_rekordu(rodzaj, rekord, pole, moje=""):
    """Opcje, pod które podpada ten rekord.

    Jedno źródło dla trzech rzeczy naraz: listy opcji w menu, licznika przy
    opcji i samego filtrowania. Gdyby licznik liczył po swojemu, obiecywałby
    inną liczbę wpisów, niż filtr potem pokazuje."""
    if rodzaj == "rok":
        d = _data_rekordu(rekord, pole)
        return {str(d.year)} if d else set()
    if rodzaj == "miesiac":
        d = _data_rekordu(rekord, pole)
        return {MIESIACE_NAZWY[d.month - 1]} if d else set()
    if rodzaj in ("kategoria", "tag"):
        try:
            wartosc = str(rekord[pole] or "").strip()
        except Exception:
            return set()
        if not wartosc or wartosc == "None":
            return set()
        return {t.strip() for t in wartosc.split(",") if t.strip()}

    autor = _autor_rekordu(rekord, pole)
    if not autor:
        return {FILTR_AUTOR_BEZ}
    return {autor, FILTR_AUTOR_MOJE} if autor == moje else {autor}


def _opcje_filtra(rodzaj, dane, pole, moje=""):
    """Zawartość menu: „Wszystko” i to, co naprawdę siedzi w danych."""
    wartosci = set()
    for w in dane:
        wartosci |= _wartosci_rekordu(rodzaj, w, pole, moje)

    if rodzaj == "rok":
        return [WSZYSTKO] + sorted(wartosci, reverse=True)
    if rodzaj == "miesiac":
        return [WSZYSTKO] + sorted(wartosci, key=MIESIACE_NAZWY.index)
    if rodzaj in ("kategoria", "tag"):
        return [WSZYSTKO] + sorted(wartosci)

    # „Tylko moje” stoi zawsze — przy dwóch domownikach działa jak przełącznik,
    # a własne imię nie dubluje się w liście osób.
    opcje = [WSZYSTKO, FILTR_AUTOR_MOJE]
    opcje += sorted(wartosci - {FILTR_AUTOR_MOJE, FILTR_AUTOR_BEZ, moje})
    if FILTR_AUTOR_BEZ in wartosci:
        opcje.append(FILTR_AUTOR_BEZ)
    return opcje


def _kropka_tagu(kolor, wyszarzona=False):
    """Kółko w kolorze tagu przed opcją w menu filtra. Tag bez koloru (spoza
    słownika) ma samo kółko obwódki — jak jego chip na karcie wpisu."""
    kolory = kolory_chipa_tagu(kolor)
    return ft.Container(
        width=10, height=10, shape=ft.BoxShape.CIRCLE,
        bgcolor=kolory[0] if kolory else None,
        border=None if kolory else ft.Border.all(1, ft.Colors.OUTLINE),
        opacity=0.38 if wyszarzona else 1.0,
    )


def _zbuduj_popup_filtra(page: ft.Page, state, klucz_stanu, opcje, etykieta,
                         ikona_aktywna, ikona_nieaktywna, liczniki=None, kolory_opcji=None):
    """Generyczna metoda budująca przycisk filtra z menu rozwijanym.

    `liczniki` (opcja → ile wpisów zostanie po jej wybraniu) dopisuje liczbę
    przy każdej opcji i przy włączonym filtrze na samym chipie. Bez nich chip
    wygląda jak dawniej.

    `kolory_opcji` (opcja → kolor tagu albo None) stawia kółko w kolorze przy
    każdej opcji, a włączony filtr maluje chip kolorem wybranego tagu."""
    aktualny_filtr = state.filtry.setdefault(klucz_stanu, WSZYSTKO)
    if aktualny_filtr not in opcje:
        aktualny_filtr = WSZYSTKO
        state.filtry[klucz_stanu] = aktualny_filtr

    def zmien_filtr(wartosc):
        state.filtry[klucz_stanu] = wartosc
        # Odświeżenie, a nie przebudowa stosu: filtr zmienia ZAWARTOŚĆ listy,
        # a nie ekran, na którym stoimy (patrz utils.odswiez_ekran).
        odswiez_ekran(page)

    elementy_menu = []
    for o in opcje:
        zaznaczone = (o == aktualny_filtr)
        liczba = liczniki.get(o, 0) if liczniki is not None else None
        # Opcja bez pokrycia zostaje w menu, traci tylko klikalność. Ukrywanie
        # przestawiałoby listę przy każdej zmianie sąsiedniego filtra, a „(0)”
        # to właśnie ta odpowiedź, po którą się do menu zagląda.
        puste = (liczba == 0 and not zaznaczone)
        kolor_opcji = ft.Colors.with_opacity(0.38, ft.Colors.ON_SURFACE) if puste else None
        wiersz = [
            ft.Icon(ft.Icons.CHECK, size=16, color=ft.Colors.PRIMARY, visible=zaznaczone),
            ft.Text(o, weight="bold" if zaznaczone else "normal", color=kolor_opcji)
        ]
        if kolory_opcji is not None and o in kolory_opcji:
            wiersz.insert(1, _kropka_tagu(kolory_opcji[o], wyszarzona=puste))
        if liczba is not None:
            wiersz.append(ft.Text(f"({liczba})", size=12,
                                  color=kolor_opcji or ft.Colors.ON_SURFACE_VARIANT))
        elementy_menu.append(
            ft.PopupMenuItem(
                content=ft.Row(wiersz),
                disabled=puste,
                on_click=None if puste else (lambda e, val=o: zmien_filtr(val))
            )
        )

    jest_aktywny = (aktualny_filtr != WSZYSTKO)
    kolor_glowny = ft.Colors.PRIMARY if jest_aktywny else ft.Colors.ON_SURFACE_VARIANT
    kolor_tla = ft.Colors.with_opacity(0.15, ft.Colors.PRIMARY) if jest_aktywny else ft.Colors.with_opacity(0.06, ft.Colors.ON_SURFACE)
    # Włączony filtr tagu nosi kolor tego tagu — tak jak jego chipy na kartach,
    # więc od razu widać, które wpisy zostały na liście.
    kolory_tagu = kolory_chipa_tagu(kolory_opcji.get(aktualny_filtr)) if (jest_aktywny and kolory_opcji) else None
    if kolory_tagu:
        kolor_tla, kolor_glowny = kolory_tagu

    pokazywany_tekst = aktualny_filtr if jest_aktywny else etykieta
    if len(pokazywany_tekst) > 9:
        pokazywany_tekst = pokazywany_tekst[:7] + ".."
    # Licznik dopisujemy PO skróceniu wartości: liczba jest tym, po co się na
    # chip patrzy, więc to nie ona ma ginąć w wielokropku.
    if jest_aktywny and liczniki is not None:
        pokazywany_tekst = f"{pokazywany_tekst} ({liczniki.get(aktualny_filtr, 0)})"

    # tight=True jest tu KONIECZNE. Bez niego wiersz ma mainAxisSize.max i bierze
    # całą szerokość, jaką dostanie. W pasku przewijanym poziomo szerokość była
    # nieograniczona, więc chip i tak kurczył się do treści — ale w pasku
    # ZAWIJANYM dostaje szerokość ekranu i każdy filtr ląduje w osobnej linijce.
    popup = ft.PopupMenuButton(
        items=elementy_menu,
        content=ft.Row([
            ft.Icon(ikona_aktywna if jest_aktywny else ikona_nieaktywna, size=13, color=kolor_glowny),
            # Pogrubiony jest tylko filtr WŁĄCZONY. Wcześniej pogrubione były
            # wszystkie, więc pasek nie odpowiadał na pytanie, po czym
            # aktualnie filtrujemy — a to jedyne pytanie, jakie się do niego ma.
            ft.Text(pokazywany_tekst, size=11, weight="bold" if jest_aktywny else "normal",
                    color=kolor_glowny),
        ], spacing=2, tight=True),
        tooltip=f"Filtruj po: {etykieta}"
    )

    return ft.Container(
        height=36,  # <-- SZTYWNA WYSOKOŚĆ
        bgcolor=kolor_tla,
        border_radius=18,
        padding=ft.Padding(12, 0, 12, 0),
        alignment=ft.Alignment.CENTER,
        content=popup
    )


def _chip_filtra(page: ft.Page, state, rodzaj, klucz_stanu, lista_danych, pole,
                 etykieta=None, liczniki=None, moje=""):
    ikona_aktywna, ikona_nieaktywna, domyslna_etykieta = WYGLAD_FILTRA[rodzaj]
    return _zbuduj_popup_filtra(
        page, state, klucz_stanu, _opcje_filtra(rodzaj, lista_danych, pole, moje),
        etykieta or domyslna_etykieta, ikona_aktywna, ikona_nieaktywna, liczniki
    )


def przycisk_filtrowania_rok(page: ft.Page, state, klucz_stanu, lista_danych, index_daty,
                             liczniki=None):
    return _chip_filtra(page, state, "rok", klucz_stanu, lista_danych, index_daty,
                        liczniki=liczniki)


def przycisk_filtrowania_kategoria(page: ft.Page, state, klucz_stanu, lista_danych, index_pola,
                                   etykieta="Tagi", liczniki=None):
    return _chip_filtra(page, state, "kategoria", klucz_stanu, lista_danych, index_pola,
                        etykieta=etykieta, liczniki=liczniki)


def przycisk_filtrowania_autora(page: ft.Page, state, klucz_stanu, lista_danych, pole,
                                liczniki=None):
    """Filtr „Autor” obok Typ/Rok/Miesiąc. Opcje: Wszystko · Tylko moje ·
    każda osoba, która cokolwiek dodała. Przy dwóch domownikach działa jak
    przełącznik „tylko moje”, przy trzech od razu widać też konkretną osobę."""
    return _chip_filtra(page, state, "autor", klucz_stanu, lista_danych, pole,
                        liczniki=liczniki, moje=db.pobierz_moje_imie())


def przycisk_filtrowania_miesiac(page: ft.Page, state, klucz_stanu, lista_danych, index_daty,
                                 liczniki=None):
    return _chip_filtra(page, state, "miesiac", klucz_stanu, lista_danych, index_daty,
                        liczniki=liczniki)


def filtruj_po_roku(lista_danych, state, klucz_stanu, index_daty):
    filtr = state.filtry.get(klucz_stanu, WSZYSTKO)
    if filtr == WSZYSTKO:
        return lista_danych
    return [w for w in lista_danych if filtr in _wartosci_rekordu("rok", w, index_daty)]


def filtruj_po_miesiacu(lista_danych, state, klucz_stanu, index_daty):
    filtr = state.filtry.get(klucz_stanu, WSZYSTKO)
    if filtr == WSZYSTKO:
        return lista_danych
    return [w for w in lista_danych if filtr in _wartosci_rekordu("miesiac", w, index_daty)]


def filtruj_po_kategorii(lista_danych, state, klucz_stanu, index_pola):
    filtr = state.filtry.get(klucz_stanu, WSZYSTKO)
    if filtr == WSZYSTKO:
        return lista_danych
    return [w for w in lista_danych if filtr in _wartosci_rekordu("kategoria", w, index_pola)]


def filtruj_po_tagu(lista_danych, state, klucz_stanu, index_pola):
    """Tagi filtrują się dokładnie jak kategoria — różnią się tylko wyglądem chipa."""
    return filtruj_po_kategorii(lista_danych, state, klucz_stanu, index_pola)


def filtruj_po_autorze(lista_danych, state, klucz_stanu, pole):
    filtr = state.filtry.get(klucz_stanu, WSZYSTKO)
    if filtr == WSZYSTKO:
        return lista_danych
    moje = db.pobierz_moje_imie()
    return [w for w in lista_danych if filtr in _wartosci_rekordu("autor", w, pole, moje)]


FILTROWANIE = {
    "rok": filtruj_po_roku,
    "miesiac": filtruj_po_miesiacu,
    "kategoria": filtruj_po_kategorii,
    "tag": filtruj_po_tagu,
    "autor": filtruj_po_autorze,
}


def pasek_filtrow(page: ft.Page, state, dane, specyfikacje):
    """Chipy jednego paska filtrów plus dane przepuszczone przez nie wszystkie.

    `specyfikacje` to krotki `(rodzaj, klucz_stanu, pole)` albo
    `(rodzaj, klucz_stanu, pole, etykieta)`, w kolejności wyświetlania;
    rodzaj: „rok”, „miesiac”, „kategoria”, „tag” (kategoria w kolorach
    tagów), „autor”. Zwraca listę chipów (do
    wsadzenia w `ft.Row(scroll=ADAPTIVE)`, razem z przyciskiem sortowania) i
    listę po filtrach — dzięki temu opis filtra stoi w jednym miejscu, a nie
    raz przy budowie chipa i drugi raz przy filtrowaniu.

    Liczniki są KRZYŻOWE: przy opcji stoi liczba wpisów, które zostaną po jej
    wybraniu, przy pozostałych filtrach ustawionych tak jak teraz. Dlatego
    liczy CAŁY pasek naraz — pojedynczy chip liczyłby na surowej liście i
    obiecywał wpisy, których po sąsiednim filtrze już nie ma.

    Opcje biorą się z listy NIEfiltrowanej, żeby menu nie skakało przy każdej
    zmianie sąsiada; te bez pokrycia dostają „(0)” i przestają być klikalne."""
    spec = [(s[0], s[1], s[2], s[3] if len(s) > 3 else None) for s in specyfikacje]
    moje = db.pobierz_moje_imie() if any(r == "autor" for r, _, _, _ in spec) else ""
    mapa_tagow = (db.mapa_kolorow_tagow(getattr(state, "auto_id", None))
                  if any(r == "tag" for r, _, _, _ in spec) else {})

    opcje = {klucz: _opcje_filtra(rodzaj, dane, pole, moje)
             for rodzaj, klucz, pole, _ in spec}
    # Zapamiętany filtr, którego nie ma już w danych (skasowany tag, rok bez
    # wpisów), zerujemy PRZED liczeniem — inaczej licznik odsiewałby po
    # wartości, którą chip za chwilę i tak zresetuje.
    for _, klucz, _, _ in spec:
        if state.filtry.setdefault(klucz, WSZYSTKO) not in opcje[klucz]:
            state.filtry[klucz] = WSZYSTKO

    wartosci = {klucz: [_wartosci_rekordu(rodzaj, w, pole, moje) for w in dane]
                for rodzaj, klucz, pole, _ in spec}

    kontrolki = []
    for rodzaj, klucz, pole, etykieta in spec:
        pozostale = [(k, state.filtry[k]) for _, k, _, _ in spec
                     if k != klucz and state.filtry[k] != WSZYSTKO]
        liczniki = {o: 0 for o in opcje[klucz]}
        for i in range(len(dane)):
            if all(wybrany in wartosci[k][i] for k, wybrany in pozostale):
                liczniki[WSZYSTKO] += 1
                for wartosc in wartosci[klucz][i]:
                    if wartosc in liczniki:
                        liczniki[wartosc] += 1
        ikona_aktywna, ikona_nieaktywna, domyslna_etykieta = WYGLAD_FILTRA[rodzaj]
        kolory_opcji = ({o: db.kolor_tagu(mapa_tagow, o) for o in opcje[klucz] if o != WSZYSTKO}
                        if rodzaj == "tag" else None)
        kontrolki.append(_zbuduj_popup_filtra(
            page, state, klucz, opcje[klucz], etykieta or domyslna_etykieta,
            ikona_aktywna, ikona_nieaktywna, liczniki, kolory_opcji
        ))

    wynik = dane
    for rodzaj, klucz, pole, _ in spec:
        wynik = FILTROWANIE[rodzaj](wynik, state, klucz, pole)
    return kontrolki, wynik


__all__ = [
    "FILTROWANIE",
    "FILTR_AUTOR_BEZ",
    "FILTR_AUTOR_MOJE",
    "WSZYSTKO",
    "WYGLAD_FILTRA",
    "_autor_rekordu",
    "_chip_filtra",
    "_data_rekordu",
    "_opcje_filtra",
    "_wartosci_rekordu",
    "_zbuduj_popup_filtra",
    "filtruj_po_autorze",
    "filtruj_po_kategorii",
    "filtruj_po_miesiacu",
    "filtruj_po_roku",
    "filtruj_po_tagu",
    "pasek_filtrow",
    "przycisk_filtrowania_autora",
    "przycisk_filtrowania_kategoria",
    "przycisk_filtrowania_miesiac",
    "przycisk_filtrowania_rok",
]
